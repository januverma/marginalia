from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel

from ..database import get_db
from ..models import Session, Message, Suggestion, TasteSignal

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: Optional[str] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionSummary(BaseModel):
    id: int
    title: Optional[str]
    created_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    id: int
    title: Optional[str]
    created_at: datetime
    messages: List[MessageOut] = []

    model_config = {"from_attributes": True}


@router.post("", response_model=SessionDetail, status_code=201)
def create_session(body: Optional[SessionCreate] = None, db: DBSession = Depends(get_db)):
    title = body.title if body else None
    session = Session(title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=List[SessionSummary])
def list_sessions(db: DBSession = Depends(get_db)):
    sessions = db.query(Session).order_by(Session.created_at.desc()).all()
    return [
        SessionSummary(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            message_count=len(s.messages),
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: int, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: DBSession = Depends(get_db)):
    from sqlalchemy import text as _text
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Cascade: messages, taste_signals, and any "suggested" rows tied to this session.
    # Keep purchased/reading/read suggestions because the book is in the user's library.
    # Bulk SQL delete bypasses ORM events, so clear FTS rows explicitly first.
    db.execute(_text("DELETE FROM messages_fts WHERE session_id = :sid"), {"sid": session_id})
    db.query(Message).filter(Message.session_id == session_id).delete()
    db.query(TasteSignal).filter(TasteSignal.session_id == session_id).delete()
    db.query(Suggestion).filter(
        Suggestion.session_id == session_id,
        Suggestion.status.in_(("suggested", "dismissed")),
    ).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return None
