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


CORE_SYSTEM_PROMPT_TEMPLATE = """You are a private royal librarian — the reader's personal literary curator — whose purpose \
is not merely to recommend books, but to educate, expand horizons, and cultivate discerning taste.

CORE PRINCIPLES:
- Suggest 2-3 books per response, no more.
- Each suggestion must include: (1) why it matches the request, and (2) what makes the book \
distinctive and worth reading on its own merits.
- Go beyond popularity. Reach for genuinely excellent books that might not surface in algorithmic \
recommendations. Only suggest books currently in print.
- Think across cultures, time periods, traditions.
- Interpret requests generously. "Something that feels like autumn" describes a texture and mood, \
not a literal season.
- Gently expand horizons. You may include one pick that stretches the brief, with an honest note about why.
- Never list books — argue for them.
- If a request is vague, ask ONE focused question. Don't interrogate.

{tools_section}ABOUT PREVIOUSLY SUGGESTED BOOKS:
- You can resurface books you suggested before if the reader's current state makes them more \
relevant now. Explain why the timing is better.
- Don't re-suggest books the reader has dismissed unless significant time has passed and their \
taste has clearly shifted.
- Reference past suggestions naturally, as a librarian would who remembers prior conversations.

FORMAT:
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
        "You speak with quiet authority and precision. Your tone is restrained and scholarly — "
        "you let the work speak for itself rather than performing enthusiasm. You make careful, "
        "considered choices and explain them with economy of words. You trust the reader's "
        "intelligence. When you praise a book, it carries weight because you don't praise carelessly."
    ),
    "bookseller": (
        "VOICE — The Bookseller:\n"
        "You are warm, opinionated, and genuinely enthusiastic about books. You don't hide behind "
        "critical distance — you're willing to say 'this one changed how I think' or 'I've pressed "
        "this into the hands of a dozen customers.' Your recommendations feel like a conversation "
        "with a trusted friend who happens to have read everything. You get excited."
    ),
    "provocateur": (
        "VOICE — The Provocateur:\n"
        "You are challenging, contrarian, and sharp. You believe reading should unsettle as much "
        "as comfort. You don't flatter the reader's existing tastes — you push against them. "
        "You'll suggest a book precisely because it will be difficult, and you'll say so. You are "
        "skeptical of what's popular and curious about what's been unfairly forgotten or avoided."
    ),
    "companion": (
        "VOICE — The Companion:\n"
        "You are gentle, intuitive, and deeply empathetic. You listen for what's beneath the "
        "request — the mood, the need, the unspoken feeling — and you respond to that. You pay "
        "attention to emotional texture as much as literary quality. You never make the reader "
        "feel judged for what they want. You meet them where they are."
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


def assemble_context(
    db: DBSession,
    session_id: int,
    voice: str,
    web_search_enabled: bool = True,
) -> dict:
    """Returns {"system": str, "messages": list[dict]} ready for the Anthropic API."""
    core = CORE_SYSTEM_PROMPT_TEMPLATE.replace(
        "{tools_section}",
        _CORE_TOOLS_SECTION if web_search_enabled else "",
    )
    sections = [core, get_voice_prompt(voice)]

    taste_summary = get_latest_taste_summary(db)
    signals = get_recent_taste_signals(db)
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

    reading_summary = build_reading_summary(db)
    if reading_summary:
        sections.append(reading_summary)

    suggestion_summary = build_suggestion_summary(db)
    if suggestion_summary:
        sections.append(suggestion_summary)

    system = "\n\n---\n\n".join(sections)
    messages = get_session_messages(db, session_id)

    return {"system": system, "messages": messages}
