from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel

from ..database import get_db
from ..models import LibrarianPrompt, Session, Message

router = APIRouter(prefix="/api/librarian-prompts", tags=["librarian-prompts"])


class PromptOut(BaseModel):
    id: int
    question: str
    status: str
    generated_at: datetime

    model_config = {"from_attributes": True}


class StartResult(BaseModel):
    session_id: int


@router.get("/pending", response_model=Optional[PromptOut])
def pending(db: DBSession = Depends(get_db)):
    """Return the single pending question from the librarian, or None."""
    p = (
        db.query(LibrarianPrompt)
        .filter(LibrarianPrompt.status == "pending")
        .order_by(LibrarianPrompt.generated_at.desc())
        .first()
    )
    return p


@router.post("/{prompt_id}/start", response_model=StartResult)
def start_conversation(prompt_id: int, db: DBSession = Depends(get_db)):
    """Create a new session that opens with the librarian's question, mark the prompt as answered,
    and return the session id so the client can navigate there."""
    p = db.query(LibrarianPrompt).filter(LibrarianPrompt.id == prompt_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if p.status != "pending":
        raise HTTPException(status_code=409, detail=f"Prompt is already {p.status}")

    title = p.question.split("\n")[0][:50].rstrip()
    if len(p.question) > 50:
        title = title[:47] + "…"
    session = Session(title=title)
    db.add(session)
    db.commit()
    db.refresh(session)

    # The librarian speaks first.
    db.add(Message(session_id=session.id, role="assistant", content=p.question))
    p.status = "answered"
    p.answered_at = datetime.now(timezone.utc)
    p.session_id = session.id
    db.commit()

    return StartResult(session_id=session.id)


@router.post("/{prompt_id}/dismiss", response_model=PromptOut)
def dismiss(prompt_id: int, db: DBSession = Depends(get_db)):
    p = db.query(LibrarianPrompt).filter(LibrarianPrompt.id == prompt_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if p.status != "pending":
        raise HTTPException(status_code=409, detail=f"Prompt is already {p.status}")
    p.status = "dismissed"
    p.answered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)
    return p
