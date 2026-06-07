from __future__ import annotations

import json
from typing import Generator, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel
import anthropic

from ..database import get_db, SessionLocal
from ..models import Session, Message, Suggestion
from ..config import ANTHROPIC_API_KEY, CHAT_MODEL, load_profile
from ..context_assembler import assemble_context
from ..suggestion_parser import parse_suggestions
from ..book_resolver import find_or_create_book
from ..taste_engine import extract_signals, save_signals, refresh_if_needed

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

MODEL = CHAT_MODEL
MAX_TOKENS = 2048

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
}


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    session_id: int
    reply: str
    suggestions_tracked: int


class JsonBlockStripper:
    """
    Tracks accumulated tokens and returns only the prose portion, withholding
    the trailing ```json [...] ``` tracking block from the live stream.
    """

    MARKER = "```json"

    def __init__(self) -> None:
        self.accumulated = ""
        self.emitted = 0
        self.block_reached = False

    def feed(self, chunk: str) -> str:
        self.accumulated += chunk
        if self.block_reached:
            return ""

        idx = self.accumulated.find(self.MARKER, self.emitted)
        if idx >= 0:
            end = idx
            while end > self.emitted and self.accumulated[end - 1] in " \n\t":
                end -= 1
            safe = self.accumulated[self.emitted : end]
            self.emitted = len(self.accumulated)
            self.block_reached = True
            return safe

        # Keep a tail buffer in case we're partway through the marker
        tail = len(self.MARKER) - 1
        safe_end = max(self.emitted, len(self.accumulated) - tail)
        safe = self.accumulated[self.emitted : safe_end]
        self.emitted = safe_end
        return safe

    def flush(self) -> str:
        if self.block_reached:
            return ""
        safe = self.accumulated[self.emitted :]
        self.emitted = len(self.accumulated)
        return safe


def _maybe_autotitle(db: DBSession, session: Session, first_user_msg: str) -> None:
    if session.title:
        return
    title = first_user_msg.strip().replace("\n", " ")
    if len(title) > 50:
        title = title[:47] + "…"
    session.title = title or None
    db.commit()


def _persist_response(
    db: DBSession,
    session_id: int,
    raw_reply: str,
    voice: Optional[str] = None,
) -> Tuple[str, int]:
    clean, books = parse_suggestions(raw_reply)
    db.add(Message(session_id=session_id, role="assistant", content=clean))
    for b in books:
        title = (b.get("title") or "").strip()
        author = (b.get("author") or "").strip()
        if not title or not author:
            continue
        book = find_or_create_book(db, title, author, b.get("pub_year"))
        # Skip if a suggested-status row already exists for this book in this session
        existing = (
            db.query(Suggestion)
            .filter(
                Suggestion.book_id == book.id,
                Suggestion.session_id == session_id,
                Suggestion.status == "suggested",
            )
            .first()
        )
        if existing:
            continue
        db.add(Suggestion(
            book_id=book.id,
            session_id=session_id,
            reason_given=(b.get("reason") or "").strip() or None,
            voice=voice,
        ))
    db.commit()
    return clean, len(books)


@router.post("/{session_id}", response_model=ChatResponse)
def send_message(session_id: int, body: ChatRequest, db: DBSession = Depends(get_db)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    is_first_message = len(session.messages) == 0
    db.add(Message(session_id=session_id, role="user", content=body.message))
    db.commit()
    if is_first_message:
        _maybe_autotitle(db, session, body.message)

    profile = load_profile()
    web_search = profile.get("web_search_enabled", True)
    ctx = assemble_context(db, session_id, profile.get("voice", "sage"), web_search_enabled=web_search)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=ctx["system"],
        messages=ctx["messages"],
        tools=[WEB_SEARCH_TOOL] if web_search else [],
    )

    # Concatenate any text blocks (the response may contain tool_use blocks too)
    raw_text = "".join(
        getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"
    )
    clean, tracked = _persist_response(db, session_id, raw_text, voice=profile.get("voice", "sage"))
    return ChatResponse(session_id=session_id, reply=clean, suggestions_tracked=tracked)


def _sse(event_type: str, **payload) -> str:
    payload["type"] = event_type
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/{session_id}/stream")
def stream_message(session_id: int, body: ChatRequest):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    def generator() -> Generator[str, None, None]:
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session:
                yield _sse("error", message="Session not found")
                return

            is_first_message = len(session.messages) == 0
            db.add(Message(session_id=session_id, role="user", content=body.message))
            db.commit()
            if is_first_message:
                _maybe_autotitle(db, session, body.message)
                yield _sse("title", title=session.title)

            profile = load_profile()
            web_search = profile.get("web_search_enabled", True)
            ctx = assemble_context(db, session_id, profile.get("voice", "sage"), web_search_enabled=web_search)

            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            stripper = JsonBlockStripper()

            stream_kwargs = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": ctx["system"],
                "messages": ctx["messages"],
            }
            if web_search:
                stream_kwargs["tools"] = [WEB_SEARCH_TOOL]

            with client.messages.stream(**stream_kwargs) as stream:
                searching = False
                for event in stream:
                    et = getattr(event, "type", None)

                    if et == "content_block_start":
                        cb = getattr(event, "content_block", None)
                        cb_type = getattr(cb, "type", None) if cb else None
                        if cb_type == "server_tool_use" and getattr(cb, "name", "") == "web_search":
                            searching = True
                            yield _sse("status", message="Searching the web…")
                        elif cb_type == "text" and searching:
                            searching = False
                            yield _sse("status", message="")

                    elif et == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        dtype = getattr(delta, "type", None) if delta else None
                        if dtype == "text_delta":
                            text = getattr(delta, "text", "") or ""
                            if text:
                                safe = stripper.feed(text)
                                if safe:
                                    yield _sse("delta", text=safe)

            tail = stripper.flush()
            if tail:
                yield _sse("delta", text=tail)

            clean, tracked = _persist_response(db, session_id, stripper.accumulated, voice=profile.get("voice", "sage"))
            yield _sse("done", tracked=tracked, clean=clean)

            # Post-processing: extract signals, refresh taste profile if warranted.
            # Runs after `done` so the user isn't blocked on these calls.
            try:
                signals = extract_signals(body.message)
                if signals:
                    save_signals(db, session_id, signals)
                refresh_if_needed(db, min_delta=1 if signals else 2)
            except Exception as e:
                logger.warning(f"Post-chat taste processing failed: {e}")
        except Exception as e:
            yield _sse("error", message=str(e))
        finally:
            db.close()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
