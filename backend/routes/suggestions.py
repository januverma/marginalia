from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func
from pydantic import BaseModel

from ..database import get_db
from ..models import Suggestion, Book, ReadingLog
from ..taste_engine import refresh_in_background

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

VALID_STATUSES = {"suggested", "purchased", "reading", "read", "dismissed"}


class BookSnippet(BaseModel):
    id: int
    title: str
    author: str
    cover_url: Optional[str] = None
    pub_year: Optional[int] = None

    model_config = {"from_attributes": True}


class SuggestionOut(BaseModel):
    id: int
    book: BookSnippet
    session_id: int
    status: str
    reason_given: Optional[str]
    voice: Optional[str] = None
    suggested_at: datetime
    status_changed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class SuggestionUpdate(BaseModel):
    status: str


@router.get("", response_model=List[SuggestionOut])
def list_suggestions(
    status: Optional[str] = Query(None),
    db: DBSession = Depends(get_db),
):
    """Returns one row per book — the most recent suggestion wins."""
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {VALID_STATUSES}")

    # Latest suggestion id per book
    latest_subq = (
        db.query(Suggestion.book_id, func.max(Suggestion.id).label("latest_id"))
        .group_by(Suggestion.book_id)
        .subquery()
    )
    q = db.query(Suggestion).join(latest_subq, Suggestion.id == latest_subq.c.latest_id)
    if status:
        q = q.filter(Suggestion.status == status)
    return q.order_by(Suggestion.suggested_at.desc()).all()


@router.patch("/{suggestion_id}", response_model=SuggestionOut)
def update_suggestion(suggestion_id: int, body: SuggestionUpdate, db: DBSession = Depends(get_db)):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {VALID_STATUSES}")
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    suggestion.status = body.status
    suggestion.status_changed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.post("/{suggestion_id}/add-to-library", response_model=SuggestionOut)
def add_to_library(
    suggestion_id: int,
    background: BackgroundTasks,
    db: DBSession = Depends(get_db),
):
    """Promote a suggestion to the library: creates a want_to_read reading_log entry
    (if none exists for the book), and marks the suggestion as purchased."""
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    existing = (
        db.query(ReadingLog)
        .filter(ReadingLog.book_id == suggestion.book_id)
        .first()
    )
    if not existing:
        db.add(ReadingLog(book_id=suggestion.book_id, status="want_to_read"))

    suggestion.status = "purchased"
    suggestion.status_changed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(suggestion)
    background.add_task(refresh_in_background)
    return suggestion
