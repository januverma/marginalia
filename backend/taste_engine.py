"""
Taste engine — builds and refreshes the reader's prose portrait.

- extract_signals(message)     — Haiku: pull short taste phrases from a user message
- generate_taste_profile(db)   — Sonnet: write the prose portrait
- refresh_if_needed(db)        — generate only when state has changed enough (cooldown + delta)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import anthropic
from sqlalchemy.orm import Session as DBSession

from .config import ANTHROPIC_API_KEY, DEEP_MODEL, SIGNAL_MODEL
from .models import TasteProfile, TasteSignal, ReadingLog, Note, Quote, Book, LibrarianPrompt

logger = logging.getLogger(__name__)

# Re-export for backward compatibility within this module; PORTRAIT_MODEL is what
# the portrait, delta, and librarian-prompt calls have used historically.
PORTRAIT_MODEL = DEEP_MODEL
REFRESH_COOLDOWN = timedelta(seconds=45)
LIBRARIAN_PROMPT_COOLDOWN = timedelta(days=7)


_LIBRARIAN_QUESTION_PROMPT = """You are an attentive librarian who has been keeping notes on a reader's evolving taste. After noticing a recent shift in their reading, you are deciding whether to ask them one perceptive question — the kind that opens a real conversation rather than fishing for compliments.

WHAT YOU NOTICED (recent shift):
{delta}

CURRENT PORTRAIT:
{summary}

Decide: is there one specific question worth asking? Good questions are short, kind, genuinely curious, and grounded in something specific you observed. They open a real conversation, not a yes/no.

Examples of the right register:
- You've started three books and finished only one this past month. Are you in a reading rut, or is something else competing for your attention?
- I notice your shelf has gotten quieter — more interior, fewer narrative arcs. Are you reaching for something specific from books right now?
- You keep coming back to translated work. Is there a tradition you'd like a guided walk through?

If nothing is genuinely worth asking — if the shifts are minor or the question would feel forced — return exactly the word "none" and nothing else.

Return either the question (no quotes, no preamble, no scaffolding) or the literal word "none"."""


def _maybe_generate_librarian_prompt(db: DBSession, current: TasteProfile) -> Optional[LibrarianPrompt]:
    """Decide whether the librarian wants to ask the reader a question. Called after a delta is produced."""
    if not ANTHROPIC_API_KEY:
        return None
    if not current.delta_summary:
        return None  # nothing observably shifted

    # Only one pending prompt at a time
    if db.query(LibrarianPrompt).filter(LibrarianPrompt.status == "pending").first():
        return None

    # Cooldown across all prompts (answered or dismissed too)
    last = db.query(LibrarianPrompt).order_by(LibrarianPrompt.generated_at.desc()).first()
    if last:
        last_at = last.generated_at
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_at < LIBRARIAN_PROMPT_COOLDOWN:
            return None

    prompt = _LIBRARIAN_QUESTION_PROMPT.format(
        delta=current.delta_summary,
        summary=current.summary,
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=PORTRAIT_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Librarian prompt generation failed: {e}")
        return None

    # Strip wrapping quotes if Claude added them despite instructions
    text = text.strip("\"'“”")
    if not text or text.lower().startswith("none"):
        return None
    if len(text) > 600:  # too rambly — discard
        return None

    p = LibrarianPrompt(question=text, status="pending")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

_SIGNAL_PROMPT = """A reader sent this message to their personal literary curator:

"{message}"

Extract any taste signals — preferences, moods, wants, dislikes, directions — \
that would help with future book recommendations. Return a JSON array of short \
phrases (3–8 words each).

Good signals:
- "tired of long novels"
- "wants more translated literature"
- "interested in Japanese writers"
- "avoiding heavy philosophy right now"
- "craving immersive world-building"

NOT signals (do not extract):
- greetings or small talk
- questions about a specific book
- requests without preference content

Return ONLY the JSON array. If nothing meaningful, return []."""


_PORTRAIT_PROMPT = """You are writing a brief, perceptive portrait of a reader for a personal literary curator — yourself, in future conversations. The portrait helps you suggest better books for this reader.

Write the portrait as prose in 3–5 paragraphs. Like a librarian's private notes about a patron. Do not enumerate or list. Make specific observations tied to the evidence.

READING HISTORY:
{reading}

NOTES THIS READER HAS WRITTEN:
{notes}

PASSAGES THIS READER HAS COLLECTED:
{quotes}

TASTE SIGNALS EXTRACTED FROM CONVERSATIONS:
{signals}

Focus on:
- What draws this reader (themes, styles, moods, traditions, languages)
- The phase of reading they seem to be in right now
- Tensions, gaps, or edges worth gently expanding
- What they're likely not in the mood for
- Anything distinctive about how they read

Avoid:
- Generic observations that could apply to any reader
- Flattery, mysticism, or formulaic summary
- Listing books or authors by name unless pointing to a pattern
- Claims not grounded in the evidence

If the evidence is thin, write a shorter honest portrait acknowledging what you see so far. Never fabricate.

Write the portrait in plain prose first — no headers, no scaffolding.

WITHIN the prose, wrap 5-7 short phrases (3-12 words each) in double-equals markers like ==this is a key phrase==. These should be your most distinctive, specific observations — the lines worth pulling out as headlines. They must flow naturally within the surrounding sentence; don't tack them on. Avoid generic phrases ("loves to read"). Aim for substance ("an appetite for prose that withholds rather than explains").

Then, AFTER the prose, return a structured JSON block (fenced in ```json ... ```) describing the reader's taste as themes and the connections between them. This is for an internal visualization the reader will see as a constellation of their interests.

Schema (compact — no extra prose, no comments):
{{
  "themes": [
    {{"name": "...", "category": "...", "weight": 1-10, "books": ["..."]}}
  ],
  "connections": [
    {{"from": "...", "to": "..."}}
  ]
}}

Rules:
- 8–12 themes. Be specific ("post-war Japanese melancholy" not "fiction").
- categories: form | mood | region | era | concern | style
- weight: 10 = defining preoccupation, 3 = faint trace
- "books": 1–2 actual titles from the data, or omit the field
- 6–10 connections. Each must reflect a real overlap.
- Theme names in connections must exactly match a name in "themes".
- Return only valid JSON. No trailing commas. No reasons. No comments."""


def extract_signals(message: str) -> List[str]:
    """Return a list of taste-signal phrases extracted from a user message."""
    if not ANTHROPIC_API_KEY or not message.strip():
        return []
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=SIGNAL_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": _SIGNAL_PROMPT.format(message=message)}],
        )
        text = resp.content[0].text
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if not isinstance(arr, list):
            return []
        return [str(s).strip() for s in arr if str(s).strip()][:10]
    except Exception as e:
        logger.warning(f"Signal extraction failed: {e}")
        return []


def save_signals(db: DBSession, session_id: int, signals: List[str]) -> int:
    count = 0
    for s in signals:
        if s and len(s) <= 200:
            db.add(TasteSignal(session_id=session_id, signal=s))
            count += 1
    if count:
        db.commit()
    return count


def _snapshot(db: DBSession) -> dict:
    return {
        "reading_log": db.query(ReadingLog).count(),
        "notes": db.query(Note).count(),
        "quotes": db.query(Quote).count(),
        "signals": db.query(TasteSignal).count(),
    }


def _build_reading_input(db: DBSession) -> str:
    parts: List[str] = []

    read = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.status == "read")
        .order_by(ReadingLog.finished_at.desc(), ReadingLog.id.desc())
        .all()
    )
    if read:
        parts.append("Books finished:")
        for log, book in read:
            year = f" ({book.pub_year})" if book.pub_year else ""
            rating = f" — rated {log.rating}/5" if log.rating else ""
            parts.append(f"- {book.title}{year} by {book.author}{rating}")

    reading = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.status == "reading")
        .all()
    )
    if reading:
        parts.append("\nCurrently reading:")
        for _, book in reading:
            parts.append(f"- {book.title} by {book.author}")

    abandoned = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.status == "abandoned")
        .all()
    )
    if abandoned:
        parts.append("\nAbandoned:")
        for _, book in abandoned:
            parts.append(f"- {book.title} by {book.author}")

    want = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.status == "want_to_read")
        .all()
    )
    if want:
        parts.append("\nWants to read:")
        for _, book in want:
            parts.append(f"- {book.title} by {book.author}")

    return "\n".join(parts) if parts else "(nothing logged yet)"


def _build_notes_input(db: DBSession) -> str:
    rows = db.query(Note, Book).join(Book).order_by(Note.created_at.desc()).limit(30).all()
    if not rows:
        return "(no notes yet)"
    return "\n".join(f"[{book.title}] {note.content}" for note, book in rows)


def _build_quotes_input(db: DBSession) -> str:
    rows = db.query(Quote, Book).join(Book).order_by(Quote.created_at.desc()).limit(8).all()
    if not rows:
        return "(no passages yet)"
    parts = []
    for q, book in rows:
        page = f" (p.{q.page})" if q.page else ""
        parts.append(f"[{book.title}{page}] \"{q.content}\"")
    return "\n\n".join(parts)


def _build_signals_input(db: DBSession) -> str:
    rows = db.query(TasteSignal).order_by(TasteSignal.extracted_at.desc()).limit(40).all()
    if not rows:
        return "(no signals yet)"
    return "\n".join(f"- {s.signal}" for s in rows)


def _balance_json(s: str) -> Optional[str]:
    """Given a possibly-truncated JSON object string, trim back to the last balanced }
    and close any unclosed strings/arrays. Returns None if unrecoverable."""
    depth = 0
    in_str = False
    escape = False
    last_balanced = -1
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_balanced = i
    if last_balanced >= 0:
        return s[: last_balanced + 1]
    return None


_DELTA_PROMPT = """You are comparing two snapshots of a reader's taste portrait. Write a short, perceptive note — 2 or 3 sentences — describing what has shifted between the two snapshots.

PREVIOUS PORTRAIT (from {prev_date}):
{prev_summary}

PREVIOUS THEMES: {prev_themes}

CURRENT PORTRAIT (from {curr_date}):
{curr_summary}

CURRENT THEMES: {curr_themes}

Focus on:
- New themes or interests that have emerged
- Older preoccupations that have faded
- Tonal shifts (lighter, heavier, more selective, more curious)

Avoid:
- Restating either portrait
- Generic observations
- Lists or headers — flowing prose only

If the two snapshots are basically the same, say so honestly in one sentence.

Return ONLY the prose, no scaffolding."""


def _themes_short(structured_json: Optional[str]) -> str:
    """One-line list of theme names for the delta prompt."""
    if not structured_json:
        return "(none)"
    try:
        data = json.loads(structured_json)
        names = [t.get("name", "?") for t in (data.get("themes") or []) if t.get("name")]
        return ", ".join(names) if names else "(none)"
    except (json.JSONDecodeError, ValueError):
        return "(none)"


def _generate_delta(previous: TasteProfile, current: TasteProfile) -> Optional[str]:
    """Compare two consecutive profiles. Returns prose or None if too close in time / fails."""
    if not ANTHROPIC_API_KEY:
        return None
    prev_at = previous.created_at
    curr_at = current.created_at
    if prev_at.tzinfo is None:
        prev_at = prev_at.replace(tzinfo=timezone.utc)
    if curr_at.tzinfo is None:
        curr_at = curr_at.replace(tzinfo=timezone.utc)
    if curr_at - prev_at < timedelta(hours=24):
        return None  # not enough time has passed to be meaningful

    prompt = _DELTA_PROMPT.format(
        prev_date=prev_at.strftime("%b %d, %Y"),
        curr_date=curr_at.strftime("%b %d, %Y"),
        prev_summary=previous.summary,
        curr_summary=current.summary,
        prev_themes=_themes_short(previous.structured),
        curr_themes=_themes_short(current.structured),
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=PORTRAIT_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Taste delta generation failed: {e}")
        return None


def _split_prose_and_structured(text: str) -> tuple[str, Optional[dict]]:
    """Extract the trailing ```json {...} ``` block (themes/connections) from the model response.
    Tolerant of missing closing fence (truncation): finds ```json then balances the JSON itself."""
    fence_start = re.search(r"```json\s*", text)
    if not fence_start:
        return text.strip(), None

    after = text[fence_start.end():]
    # Try the well-formed case first: closing ``` exists
    closing = re.search(r"\n```", after)
    if closing:
        json_str = after[: closing.start()]
        prose_after = after[closing.end():]
    else:
        json_str = after
        prose_after = ""

    # Brace-balance to recover from truncation
    balanced = _balance_json(json_str)
    if not balanced:
        return text.strip(), None

    try:
        data = json.loads(balanced)
        if isinstance(data, dict) and isinstance(data.get("themes"), list):
            prose = (text[: fence_start.start()] + prose_after).strip()
            return prose, data
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse taste structured JSON: {e}")

    return text.strip(), None


def generate_taste_profile(db: DBSession) -> Optional[TasteProfile]:
    """Generate and persist a new taste profile from current state."""
    if not ANTHROPIC_API_KEY:
        return None
    counts = _snapshot(db)
    if sum(counts.values()) == 0:
        return None

    prompt = _PORTRAIT_PROMPT.format(
        reading=_build_reading_input(db),
        notes=_build_notes_input(db),
        quotes=_build_quotes_input(db),
        signals=_build_signals_input(db),
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=PORTRAIT_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
    except Exception as e:
        logger.error(f"Taste profile generation failed: {e}")
        return None

    prose, structured = _split_prose_and_structured(raw)

    # Find the previous profile BEFORE inserting the new one
    previous = (
        db.query(TasteProfile)
        .order_by(TasteProfile.created_at.desc())
        .first()
    )

    profile = TasteProfile(
        summary=prose,
        generated_from=json.dumps(counts),
        structured=json.dumps(structured) if structured else None,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Generate the delta against the previous profile (if any, and far enough apart)
    if previous is not None:
        delta = _generate_delta(previous, profile)
        if delta:
            profile.delta_summary = delta
            db.commit()
            db.refresh(profile)
            # And — only if there was something to notice — consider asking the reader a question.
            _maybe_generate_librarian_prompt(db, profile)

    return profile


def should_refresh(db: DBSession, min_delta: int = 1) -> bool:
    current = _snapshot(db)
    if sum(current.values()) == 0:
        return False
    latest = db.query(TasteProfile).order_by(TasteProfile.created_at.desc()).first()
    if not latest:
        return True

    last_at = latest.created_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - last_at < REFRESH_COOLDOWN:
        return False

    try:
        prev = json.loads(latest.generated_from or "{}")
    except Exception:
        return True

    delta = sum(max(0, current.get(k, 0) - prev.get(k, 0)) for k in current)
    return delta >= min_delta


def refresh_if_needed(db: DBSession, min_delta: int = 1) -> Optional[TasteProfile]:
    if should_refresh(db, min_delta=min_delta):
        return generate_taste_profile(db)
    return None


def refresh_in_background() -> None:
    """Entry point for FastAPI BackgroundTasks — creates its own DB session."""
    from .database import SessionLocal
    db = SessionLocal()
    try:
        refresh_if_needed(db, min_delta=1)
    except Exception as e:
        logger.warning(f"Background taste refresh failed: {e}")
    finally:
        db.close()
