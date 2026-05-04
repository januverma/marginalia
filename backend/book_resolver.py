from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session as DBSession

from .models import Book
from .config import GOOGLE_BOOKS_API_KEY

logger = logging.getLogger(__name__)

_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"


def _enhance_cover_url(url: Optional[str]) -> Optional[str]:
    """Upgrade Google Books thumbnail URL to a higher-resolution variant."""
    if not url:
        return url
    url = url.replace("http://", "https://")
    url = re.sub(r"zoom=\d+", "zoom=3", url)
    url = url.replace("&edge=curl", "").replace("edge=curl&", "")
    return url


def refresh_book_cover(db: DBSession, book: Book) -> bool:
    """Re-query Google Books for this title/author. Always records the attempt timestamp;
    updates cover/isbn/buy_link when found. Returns True if cover URL changed."""
    enriched = _lookup_google_books(book.title, book.author)
    book.last_cover_attempt_at = datetime.now(timezone.utc)
    changed = False
    new_url = enriched.get("cover_url")
    if new_url and new_url != book.cover_url:
        book.cover_url = new_url
        changed = True
    if enriched.get("isbn") and not book.isbn:
        book.isbn = enriched["isbn"]
    if enriched.get("buy_link") and not book.buy_link:
        book.buy_link = enriched["buy_link"]
    if enriched.get("pub_year") and not book.pub_year:
        book.pub_year = enriched["pub_year"]
    return changed


# ── Background sweep + single-book helpers ───────────────────────────────────

COVER_RETRY_AFTER = timedelta(hours=6)
COVER_OPPORTUNISTIC_AFTER = timedelta(hours=1)


def sweep_missing_covers(max_per_sweep: int = 5, retry_after: timedelta = COVER_RETRY_AFTER) -> int:
    """Find books with no cover that haven't been tried recently, and re-query Google Books.
    Limited per call to be polite; intended to run on a recurring schedule."""
    from .database import SessionLocal

    db = SessionLocal()
    updated = 0
    try:
        threshold = datetime.now(timezone.utc) - retry_after
        candidates = (
            db.query(Book)
            .filter(
                Book.cover_url.is_(None),
                ((Book.last_cover_attempt_at.is_(None)) | (Book.last_cover_attempt_at < threshold)),
            )
            .order_by(Book.last_cover_attempt_at.is_(None).desc(), Book.last_cover_attempt_at.asc())
            .limit(max_per_sweep)
            .all()
        )
        for book in candidates:
            try:
                if refresh_book_cover(db, book):
                    updated += 1
                db.commit()
            except Exception as e:
                logger.warning(f"Sweep cover refresh failed for book #{book.id}: {e}")
                db.rollback()
            time.sleep(1)  # be polite to Google Books
    finally:
        db.close()
    if updated:
        logger.info(f"Cover sweep updated {updated} book(s).")
    return updated


def refresh_one_cover(book_id: int) -> None:
    """Background-task helper: refresh a single book's cover in its own session."""
    from .database import SessionLocal

    db = SessionLocal()
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            return
        try:
            refresh_book_cover(db, book)
            db.commit()
        except Exception as e:
            logger.warning(f"Single-book cover refresh failed for #{book_id}: {e}")
            db.rollback()
    finally:
        db.close()


_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")


def _author_tokens(s: str) -> set:
    """Lowercase 3+ letter words. Ignores honorifics like 'Jr', 'Dr'."""
    return {t.lower() for t in _TOKEN_RE.findall(s or "")}


def find_or_create_book(
    db: DBSession,
    title: str,
    author: str,
    pub_year: Optional[int] = None,
) -> Book:
    """Return an existing Book record or create one, enriched via Google Books.
    Match: same title (case-insensitive, exact) AND at least one shared author word."""
    title_clean = title.strip()
    new_tokens = _author_tokens(author)

    candidates = db.query(Book).filter(Book.title.ilike(title_clean)).all()
    for c in candidates:
        if _author_tokens(c.author) & new_tokens:
            return c

    enriched = _lookup_google_books(title, author)

    book = Book(
        title=enriched.get("title", title).strip(),
        author=enriched.get("author", author).strip(),
        isbn=enriched.get("isbn"),
        cover_url=enriched.get("cover_url"),
        buy_link=enriched.get("buy_link"),
        pub_year=enriched.get("pub_year") or pub_year,
    )
    db.add(book)
    db.flush()
    return book


def _lookup_google_books(title: str, author: str) -> dict:
    try:
        params: dict = {
            "q": f'intitle:"{title}" inauthor:"{author}"',
            "maxResults": 5,
        }
        if GOOGLE_BOOKS_API_KEY:
            params["key"] = GOOGLE_BOOKS_API_KEY

        resp = httpx.get(_GOOGLE_BOOKS_URL, params=params, timeout=5.0)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}

        # Prefer the first result that has cover artwork; fall back to the first match.
        chosen = next(
            (it for it in items if it.get("volumeInfo", {}).get("imageLinks")),
            items[0],
        )
        info = chosen.get("volumeInfo", {})
        sale = chosen.get("saleInfo", {})

        isbn = None
        for ident in info.get("industryIdentifiers", []):
            if ident.get("type") == "ISBN_13":
                isbn = ident["identifier"]
                break
            if ident.get("type") == "ISBN_10" and not isbn:
                isbn = ident["identifier"]

        images = info.get("imageLinks", {})
        raw_cover = (
            images.get("extraLarge")
            or images.get("large")
            or images.get("medium")
            or images.get("thumbnail")
            or images.get("smallThumbnail")
        )
        cover_url = _enhance_cover_url(raw_cover)
        buy_link = sale.get("buyLink") or info.get("infoLink")

        pub_year = None
        m = re.match(r"(\d{4})", info.get("publishedDate", ""))
        if m:
            pub_year = int(m.group(1))

        return {
            "title": info.get("title", title),
            "author": ", ".join(info.get("authors", [author])),
            "isbn": isbn,
            "cover_url": cover_url,
            "buy_link": buy_link,
            "pub_year": pub_year,
        }
    except Exception as e:
        logger.warning(f"Google Books lookup failed for {title!r} by {author!r}: {e}")
        return {}
