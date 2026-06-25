from __future__ import annotations

from typing import Optional, List
from sqlalchemy.orm import Session as DBSession
from .models import Session, Message, TasteProfile, TasteSignal, ReadingLog, Suggestion, Book

_CORE_TOOLS_SECTION = """TOOLS:
You have access to a web_search tool. Your literary knowledge is deep — use search sparingly, only when it materially improves the recommendation. Reach for it when:
- You need to verify a book is currently in print
- The reader's request hinges on recency (e.g. "the best novel of the last two years", "recently translated")
- You are considering a book published after your training cutoff
- You need to confirm a current edition, translation, or availability

Do NOT search for general literary background, themes, plot summaries, or analysis — answer from your own knowledge. Use at most 2-3 searches per response. Integrate findings naturally into your prose; don't recite search results or list URLs.

"""


CORE_SYSTEM_PROMPT_TEMPLATE = """You are a personal literary curator — a private librarian for one reader. \
Your job is to recommend books worth their time, following the voice and selection stance you are given below.

CORE PRINCIPLES:
- Suggest 2-3 books per response, no more.
- Only recommend real books that are currently in print.
- For each book give (1) why it fits this request and this reader, and (2) what makes it \
distinctive and worth reading. Argue for books — don't just list them.
- Keep a quality floor: never recommend something you don't believe is genuinely good.
- NEVER recommend a book the reader has already read or is currently reading — these appear \
under "About This Reader" / Reading History. Always offer something new.
- The reader's portrait and reading history below are your evidence about who they are. \
EVERY voice uses them — but in different ways and to different degrees, as your selection stance directs.
- You may resurface a book you suggested before if the timing is now better, but don't \
re-suggest books the reader has dismissed.
- If the request is vague, you may ask ONE focused question instead of guessing.

{tools_section}FORMAT:
For each book, provide:
- Title and Author (with original publication year)
- A compelling paragraph on why this book matches AND why it's worth reading
- A single evocative sentence — your own distillation of what the book does to a reader

After your recommendations, return a structured JSON block (fenced in ```json ... ```) with the \
books you mentioned:
[
  {
    "title": "...",
    "author": "...",
    "pub_year": ...,
    "reason": "one-sentence summary of why you suggested this"
  }
]
This is used by the system to track suggestions. The reader won't see it."""

VOICE_PROMPTS = {
    "sage": (
        "VOICE — The Sage:\n"
        "SELECTION: your purpose is the reader's education, and you STRIVE to expand them beyond "
        "where they are. Use their taste portrait and reading history to locate what is MISSING — "
        "the traditions, forms, periods, and foundational/canonical authors absent from their "
        "shelf — and deliberately recommend INTO those gaps. Do not stay in their comfort zone: a "
        "good Sage pick is one they would not have found on their own. Favor the formative over the "
        "merely enjoyable.\n"
        "TONE: quiet authority, scholarly, economical."
    ),
    "bookseller": (
        "VOICE — The Bookseller:\n"
        "SELECTION: use their taste portrait and history only as a LOOSE signal of the neighborhood "
        "they enjoy — then recommend the books readers reliably love within and around it: "
        "widely-admired, broadly accessible titles with strong word of mouth. You care more that a "
        "book is beloved and rewarding than that it precisely matches their profile. A crowd-pleaser "
        "that genuinely delivers is exactly right.\n"
        "TONE: warm, enthusiastic, opinionated."
    ),
    "provocateur": (
        "VOICE — The Provocateur:\n"
        "SELECTION: you STRIVE to unsettle. Read their taste portrait and history as the pattern to "
        "BREAK — identify what they reliably reach for and deliberately recommend against that "
        "grain: the formally difficult, the politically uncomfortable, the unfairly forgotten, the "
        "actively opposed to their habits. Leaving their comfort zone is the goal, not a risk. Be "
        "skeptical of bestsellers and consensus; if a book is hard or alien to them, that is the "
        "point. If the reader gives you NO direction, do not play it safe — IMPOSE one: pick the "
        "books that most disrupt their established pattern. A safe, on-taste recommendation is a "
        "failure for you.\n"
        "TONE: contrarian, sharp, unapologetic."
    ),
    "companion": (
        "VOICE — The Companion:\n"
        "SELECTION: stay CLOSE to who they already are. Lean hard on their taste portrait, reading "
        "history, and saved passages; recommend the next book squarely within their established "
        "taste, mood, and favorite registers — the one that fits them now. You MATCH rather than "
        "stretch; precision about THIS reader is your whole gift.\n"
        "TONE: gentle, intuitive, knows-them-well."
    ),
}


def get_voice_prompt(voice: str) -> str:
    return VOICE_PROMPTS.get(voice.lower(), VOICE_PROMPTS["sage"])


def get_latest_taste_summary(db: DBSession) -> Optional[str]:
    row = db.query(TasteProfile).order_by(TasteProfile.created_at.desc()).first()
    return row.summary if row else None


def get_recent_taste_signals(db: DBSession, limit: int = 20) -> List[str]:
    rows = (
        db.query(TasteSignal)
        .order_by(TasteSignal.extracted_at.desc())
        .limit(limit)
        .all()
    )
    return [r.signal for r in reversed(rows)]


def build_reading_summary(db: DBSession) -> Optional[str]:
    total = db.query(ReadingLog).count()
    if total == 0:
        return None

    recently_finished = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.status == "read")
        .order_by(ReadingLog.finished_at.desc())
        .limit(5)
        .all()
    )
    currently_reading = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.status == "reading")
        .all()
    )
    highly_rated = (
        db.query(ReadingLog, Book)
        .join(Book)
        .filter(ReadingLog.rating >= 4)
        .order_by(ReadingLog.rating.desc())
        .limit(5)
        .all()
    )

    parts = [f"## Reading History\n\nTotal books logged: {total}."]

    if currently_reading:
        titles = ", ".join(f"*{b.title}* by {b.author}" for _, b in currently_reading)
        parts.append(f"Currently reading: {titles}.")

    if recently_finished:
        items = []
        for log, book in recently_finished:
            rating_str = f" (rated {log.rating}/5)" if log.rating else ""
            items.append(f"*{book.title}* by {book.author}{rating_str}")
        parts.append("Recently finished: " + "; ".join(items) + ".")

    if highly_rated:
        titles = ", ".join(f"*{b.title}*" for _, b in highly_rated)
        parts.append(f"Highly rated: {titles}.")

    # Complete list of everything already on their shelf (any status), as an
    # exclusion set — the librarian must never re-recommend these. Deduped by book.
    # (At very large libraries this should become a history-lookup tool rather than
    # an inline dump, but a full list is correct and simple for now.)
    seen, already = set(), []
    for log, book in db.query(ReadingLog, Book).join(Book).order_by(Book.title).all():
        if book.id not in seen:
            seen.add(book.id)
            already.append(f"{book.title} by {book.author}")
    if already:
        parts.append(
            "### Already in their library — do NOT recommend any of these again:\n"
            + "; ".join(already)
        )

    return "\n".join(parts)


def build_suggestion_summary(db: DBSession) -> Optional[str]:
    pending = (
        db.query(Suggestion, Book)
        .join(Book)
        .filter(Suggestion.status == "suggested")
        .order_by(Suggestion.suggested_at.desc())
        .limit(10)
        .all()
    )
    dismissed = (
        db.query(Suggestion, Book)
        .join(Book)
        .filter(Suggestion.status == "dismissed")
        .order_by(Suggestion.status_changed_at.desc())
        .limit(5)
        .all()
    )

    if not pending and not dismissed:
        return None

    parts = ["## Suggestion History"]

    if pending:
        items = []
        for sug, book in pending:
            date_str = sug.suggested_at.strftime("%b %d")
            reason_str = f" — reason: {sug.reason_given}" if sug.reason_given else ""
            items.append(f"*{book.title}* by {book.author} (suggested {date_str}{reason_str})")
        parts.append("Previously suggested, not yet read:\n" + "\n".join(f"- {i}" for i in items))

    if dismissed:
        titles = ", ".join(f"*{b.title}*" for _, b in dismissed)
        parts.append(f"Recently dismissed: {titles}.")

    return "\n".join(parts)


def get_session_messages(db: DBSession, session_id: int) -> List[dict]:
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at)
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in rows]


def compose_system_prompt(
    persona_prompt: Optional[str],
    taste_summary: Optional[str],
    signals: Optional[List[str]],
    reading_summary: Optional[str],
    suggestion_summary: Optional[str],
    web_search_enabled: bool = True,
) -> str:
    """Pure assembly of the system prompt from its parts. Shared by the live app
    (assemble_context) and offline evaluation tooling, so both build the prompt by
    the exact same code path. `persona_prompt=None` omits the persona section."""
    core = CORE_SYSTEM_PROMPT_TEMPLATE.replace(
        "{tools_section}",
        _CORE_TOOLS_SECTION if web_search_enabled else "",
    )
    sections = [core]
    if persona_prompt:
        sections.append(persona_prompt)

    if taste_summary or signals:
        taste_parts = ["## About This Reader"]
        if taste_summary:
            taste_parts.append(taste_summary)
        if signals:
            taste_parts.append(
                "### Recent taste signals (from conversations):\n"
                + "\n".join(f"- {s}" for s in signals)
            )
        sections.append("\n\n".join(taste_parts))

    if reading_summary:
        sections.append(reading_summary)

    if suggestion_summary:
        sections.append(suggestion_summary)

    return "\n\n---\n\n".join(sections)


def assemble_context(
    db: DBSession,
    session_id: int,
    voice: str,
    web_search_enabled: bool = True,
) -> dict:
    """Returns {"system": str, "messages": list[dict]} ready for the Anthropic API."""
    system = compose_system_prompt(
        persona_prompt=get_voice_prompt(voice),
        taste_summary=get_latest_taste_summary(db),
        signals=get_recent_taste_signals(db),
        reading_summary=build_reading_summary(db),
        suggestion_summary=build_suggestion_summary(db),
        web_search_enabled=web_search_enabled,
    )
    messages = get_session_messages(db, session_id)
    return {"system": system, "messages": messages}
