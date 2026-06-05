from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel

from ..database import get_db
from ..models import Book, ReadingLog, Note, Quote, Suggestion
from ..book_resolver import find_or_create_book, refresh_book_cover, refresh_one_cover, COVER_OPPORTUNISTIC_AFTER
from ..taste_engine import refresh_in_background

router = APIRouter(tags=["library"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class BookOut(BaseModel):
    id: int
    title: str
    author: str
    isbn: Optional[str]
    cover_url: Optional[str]
    buy_link: Optional[str]
    pub_year: Optional[int]

    model_config = {"from_attributes": True}


class BookCreate(BaseModel):
    title: str
    author: str
    pub_year: Optional[int] = None


class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    pub_year: Optional[int] = None


class ReadingLogOut(BaseModel):
    id: int
    book_id: int
    status: str
    rating: Optional[int]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ReadingLogCreate(BaseModel):
    book_id: Optional[int] = None
    title: Optional[str] = None
    author: Optional[str] = None
    pub_year: Optional[int] = None
    status: str  # want_to_read | reading | read | abandoned
    rating: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ReadingLogUpdate(BaseModel):
    status: Optional[str] = None
    rating: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class NoteOut(BaseModel):
    id: int
    book_id: int
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    book_id: int
    content: str


class QuoteOut(BaseModel):
    id: int
    book_id: int
    content: str
    page: Optional[int]
    context: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class QuoteCreate(BaseModel):
    book_id: int
    content: str
    page: Optional[int] = None
    context: Optional[str] = None


class SuggestionSnippet(BaseModel):
    id: int
    status: str
    reason_given: Optional[str]
    suggested_at: datetime

    model_config = {"from_attributes": True}


class BookDetail(BaseModel):
    id: int
    title: str
    author: str
    isbn: Optional[str]
    cover_url: Optional[str]
    buy_link: Optional[str]
    pub_year: Optional[int]
    reading_log: List[ReadingLogOut] = []
    notes: List[NoteOut] = []
    quotes: List[QuoteOut] = []
    suggestions: List[SuggestionSnippet] = []

    model_config = {"from_attributes": True}


class ShelfBook(BaseModel):
    book_id: int
    log_id: int
    title: str
    author: str
    cover_url: Optional[str]
    pub_year: Optional[int]
    rating: Optional[int]
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class LibraryOut(BaseModel):
    reading: List[ShelfBook] = []
    want_to_read: List[ShelfBook] = []
    read: List[ShelfBook] = []
    abandoned: List[ShelfBook] = []


# ── Books ─────────────────────────────────────────────────────────────────────

@router.get("/api/books", response_model=List[BookOut])
def list_books(db: DBSession = Depends(get_db)):
    return db.query(Book).order_by(Book.first_seen.desc()).all()


@router.get("/api/books/{book_id}", response_model=BookDetail)
def get_book(book_id: int, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Opportunistic: if the cover is missing and we haven't tried in the last hour,
    # kick off a background fetch. The next time the user views this book the cover
    # should be there.
    if not book.cover_url:
        last = book.last_cover_attempt_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or datetime.now(timezone.utc) - last > COVER_OPPORTUNISTIC_AFTER:
            background.add_task(refresh_one_cover, book.id)
    return book


@router.post("/api/books", response_model=BookOut, status_code=201)
def add_book(body: BookCreate, db: DBSession = Depends(get_db)):
    book = find_or_create_book(db, body.title, body.author, body.pub_year)
    db.commit()
    db.refresh(book)
    return book


@router.patch("/api/books/{book_id}", response_model=BookOut)
def update_book(book_id: int, body: BookUpdate, db: DBSession = Depends(get_db)):
    """Edit title/author/pub_year. If title or author changes, re-query Google Books
    so cover/ISBN/buy_link get refreshed (e.g. you fixed a misspelled author)."""
    from ..book_resolver import _lookup_google_books, GoogleBooksRateLimited

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    title_changed = body.title is not None and body.title.strip() != (book.title or "").strip()
    author_changed = body.author is not None and body.author.strip() != (book.author or "").strip()

    if body.title is not None:
        book.title = body.title.strip()
    if body.author is not None:
        book.author = body.author.strip()
    if body.pub_year is not None:
        book.pub_year = body.pub_year

    if title_changed or author_changed:
        try:
            enriched = _lookup_google_books(book.title, book.author)
        except GoogleBooksRateLimited:
            enriched = {}  # save the edit; sweep will re-enrich later
        if enriched.get("cover_url"):
            book.cover_url = enriched["cover_url"]
        if enriched.get("isbn"):
            book.isbn = enriched["isbn"]
        if enriched.get("buy_link"):
            book.buy_link = enriched["buy_link"]
        if body.pub_year is None and enriched.get("pub_year"):
            book.pub_year = enriched["pub_year"]

    db.commit()
    db.refresh(book)
    return book


@router.post("/api/books/refresh-covers")
def refresh_covers(db: DBSession = Depends(get_db)):
    updated = 0
    for book in db.query(Book).all():
        try:
            if refresh_book_cover(db, book):
                updated += 1
        except Exception:
            pass
    db.commit()
    return {"updated": updated, "total": db.query(Book).count()}


@router.post("/api/books/dedupe")
def dedupe_books(db: DBSession = Depends(get_db)):
    """Merge duplicate Book rows that share the same normalized title and at least one author token.
    Repoints reading_log, notes, and suggestions to the canonical book, then deletes duplicates."""
    from ..book_resolver import _author_tokens

    books = db.query(Book).order_by(Book.id).all()
    # Group by normalized title
    groups: dict = {}
    for b in books:
        key = (b.title or "").strip().lower()
        groups.setdefault(key, []).append(b)

    merged = 0
    for title_key, group in groups.items():
        if len(group) < 2:
            continue
        # Find clusters within the group sharing at least one author token
        unassigned = list(group)
        clusters: list = []
        while unassigned:
            seed = unassigned.pop(0)
            cluster = [seed]
            seed_tokens = _author_tokens(seed.author)
            remaining = []
            for b in unassigned:
                if seed_tokens & _author_tokens(b.author):
                    cluster.append(b)
                else:
                    remaining.append(b)
            unassigned = remaining
            clusters.append(cluster)

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            # Pick canonical: prefer cover_url > isbn > oldest id
            canonical = sorted(
                cluster,
                key=lambda b: (b.cover_url is None, b.isbn is None, b.id),
            )[0]
            for dup in cluster:
                if dup.id == canonical.id:
                    continue
                # Repoint all FKs
                db.query(ReadingLog).filter(ReadingLog.book_id == dup.id).update({"book_id": canonical.id})
                db.query(Note).filter(Note.book_id == dup.id).update({"book_id": canonical.id})
                db.query(Suggestion).filter(Suggestion.book_id == dup.id).update({"book_id": canonical.id})
                db.delete(dup)
                merged += 1
    db.commit()
    return {"merged": merged, "total_books": db.query(Book).count()}


# ── Library (books the user has on a shelf) ──────────────────────────────────

@router.get("/api/library", response_model=LibraryOut)
def get_library(db: DBSession = Depends(get_db)):
    """Books with at least one reading_log entry, grouped by current shelf."""
    rows = (
        db.query(ReadingLog, Book)
        .join(Book)
        .order_by(ReadingLog.id.desc())
        .all()
    )
    # Most recent log per book wins
    seen: dict = {}
    for log, book in rows:
        if book.id not in seen:
            seen[book.id] = (log, book)

    shelves: dict = {"reading": [], "want_to_read": [], "read": [], "abandoned": []}
    for log, book in seen.values():
        if log.status not in shelves:
            continue
        shelves[log.status].append(ShelfBook(
            book_id=book.id,
            log_id=log.id,
            title=book.title,
            author=book.author,
            cover_url=book.cover_url,
            pub_year=book.pub_year,
            rating=log.rating,
            status=log.status,
            started_at=log.started_at,
            finished_at=log.finished_at,
        ))
    return LibraryOut(**shelves)


# ── Reading log ───────────────────────────────────────────────────────────────

VALID_READ_STATUSES = {"want_to_read", "reading", "read", "abandoned"}


@router.get("/api/reading-log", response_model=List[ReadingLogOut])
def list_reading_log(db: DBSession = Depends(get_db)):
    return db.query(ReadingLog).order_by(ReadingLog.id.desc()).all()


@router.post("/api/reading-log", response_model=ReadingLogOut, status_code=201)
def add_reading_log(body: ReadingLogCreate, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    if body.status not in VALID_READ_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {VALID_READ_STATUSES}")

    if body.book_id:
        book = db.query(Book).filter(Book.id == body.book_id).first()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
    elif body.title and body.author:
        book = find_or_create_book(db, body.title, body.author, body.pub_year)
    else:
        raise HTTPException(status_code=422, detail="Provide book_id or title+author")

    entry = ReadingLog(
        book_id=book.id,
        status=body.status,
        rating=body.rating,
        started_at=body.started_at,
        finished_at=body.finished_at,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    background.add_task(refresh_in_background)
    return entry


@router.patch("/api/reading-log/{entry_id}", response_model=ReadingLogOut)
def update_reading_log(entry_id: int, body: ReadingLogUpdate, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    entry = db.query(ReadingLog).filter(ReadingLog.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Reading log entry not found")
    if body.status is not None:
        if body.status not in VALID_READ_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {VALID_READ_STATUSES}")
        entry.status = body.status
    if body.rating is not None:
        entry.rating = body.rating
    if body.started_at is not None:
        entry.started_at = body.started_at
    if body.finished_at is not None:
        entry.finished_at = body.finished_at
    db.commit()
    db.refresh(entry)
    background.add_task(refresh_in_background)
    return entry


# ── Notes ─────────────────────────────────────────────────────────────────────

@router.post("/api/notes", response_model=NoteOut, status_code=201)
def add_note(body: NoteCreate, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    book = db.query(Book).filter(Book.id == body.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    note = Note(book_id=body.book_id, content=body.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    background.add_task(refresh_in_background)
    return note


@router.get("/api/notes", response_model=List[NoteOut])
def list_notes(book_id: Optional[int] = Query(None), db: DBSession = Depends(get_db)):
    q = db.query(Note)
    if book_id is not None:
        q = q.filter(Note.book_id == book_id)
    return q.order_by(Note.created_at.desc()).all()


# ── Quotes / passages ────────────────────────────────────────────────────────

@router.post("/api/quotes", response_model=QuoteOut, status_code=201)
def add_quote(body: QuoteCreate, background: BackgroundTasks, db: DBSession = Depends(get_db)):
    book = db.query(Book).filter(Book.id == body.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    quote = Quote(
        book_id=body.book_id,
        content=content,
        page=body.page,
        context=(body.context or "").strip() or None,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    background.add_task(refresh_in_background)
    return quote


@router.get("/api/quotes", response_model=List[QuoteOut])
def list_quotes(book_id: Optional[int] = Query(None), db: DBSession = Depends(get_db)):
    q = db.query(Quote)
    if book_id is not None:
        q = q.filter(Quote.book_id == book_id)
    return q.order_by(Quote.created_at.desc()).all()


@router.delete("/api/quotes/{quote_id}", status_code=204)
def delete_quote(quote_id: int, db: DBSession = Depends(get_db)):
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    db.delete(quote)
    db.commit()
    return None
