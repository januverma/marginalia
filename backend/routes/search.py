from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..search import search_all

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=30), db: DBSession = Depends(get_db)):
    """Free-text search across messages, notes, and passages. Returns grouped results
    with HTML snippets containing <mark>…</mark> highlights."""
    if not q.strip():
        return {"messages": [], "notes": [], "quotes": []}
    return search_all(db.connection(), q, limit=limit)
