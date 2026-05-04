"""
SQLite FTS5 search index for messages, notes, and quotes.

Each FTS5 table is independent (not content-linked) and kept in sync via
SQLAlchemy ORM events. Bulk SQL deletes bypass events, so any code path that
performs a bulk delete must also clear the FTS rows explicitly (see
routes/sessions.py for the one such case).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import event, text
from sqlalchemy.engine import Connection

from .database import engine
from .models import Message, Note, Quote

logger = logging.getLogger(__name__)


_DDL = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
        content,
        message_id UNINDEXED,
        session_id UNINDEXED,
        role UNINDEXED,
        created_at UNINDEXED
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
        content,
        note_id UNINDEXED,
        book_id UNINDEXED,
        created_at UNINDEXED
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS quotes_fts USING fts5(
        content,
        quote_id UNINDEXED,
        book_id UNINDEXED,
        page UNINDEXED,
        created_at UNINDEXED
    )""",
]


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def init_search_index() -> None:
    """Create FTS tables and backfill from source tables if empty. Idempotent."""
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))

        if conn.execute(text("SELECT COUNT(*) FROM messages_fts")).scalar() == 0:
            for row in conn.execute(text("SELECT id, content, session_id, role, created_at FROM messages")):
                conn.execute(
                    text("INSERT INTO messages_fts (content, message_id, session_id, role, created_at) "
                         "VALUES (:c, :id, :sid, :r, :ts)"),
                    {"c": row[1], "id": row[0], "sid": row[2], "r": row[3], "ts": row[4]},
                )

        if conn.execute(text("SELECT COUNT(*) FROM notes_fts")).scalar() == 0:
            for row in conn.execute(text("SELECT id, content, book_id, created_at FROM notes")):
                conn.execute(
                    text("INSERT INTO notes_fts (content, note_id, book_id, created_at) "
                         "VALUES (:c, :id, :bid, :ts)"),
                    {"c": row[1], "id": row[0], "bid": row[2], "ts": row[3]},
                )

        if conn.execute(text("SELECT COUNT(*) FROM quotes_fts")).scalar() == 0:
            for row in conn.execute(text("SELECT id, content, book_id, page, created_at FROM quotes")):
                conn.execute(
                    text("INSERT INTO quotes_fts (content, quote_id, book_id, page, created_at) "
                         "VALUES (:c, :id, :bid, :pg, :ts)"),
                    {"c": row[1], "id": row[0], "bid": row[2], "pg": row[3], "ts": row[4]},
                )


# ── ORM event listeners (sync the FTS index on insert/update/delete) ──────────

def _safe(conn: Connection, sql: str, params: dict) -> None:
    try:
        conn.execute(text(sql), params)
    except Exception as e:
        logger.warning(f"FTS sync failed: {e}")


@event.listens_for(Message, "after_insert")
def _msg_inserted(mapper, connection, target):
    _safe(connection,
          "INSERT INTO messages_fts (content, message_id, session_id, role, created_at) "
          "VALUES (:c, :id, :sid, :r, :ts)",
          {"c": target.content, "id": target.id, "sid": target.session_id,
           "r": target.role, "ts": _iso(target.created_at)})


@event.listens_for(Message, "after_update")
def _msg_updated(mapper, connection, target):
    _safe(connection, "DELETE FROM messages_fts WHERE message_id = :id", {"id": target.id})
    _safe(connection,
          "INSERT INTO messages_fts (content, message_id, session_id, role, created_at) "
          "VALUES (:c, :id, :sid, :r, :ts)",
          {"c": target.content, "id": target.id, "sid": target.session_id,
           "r": target.role, "ts": _iso(target.created_at)})


@event.listens_for(Message, "after_delete")
def _msg_deleted(mapper, connection, target):
    _safe(connection, "DELETE FROM messages_fts WHERE message_id = :id", {"id": target.id})


@event.listens_for(Note, "after_insert")
def _note_inserted(mapper, connection, target):
    _safe(connection,
          "INSERT INTO notes_fts (content, note_id, book_id, created_at) "
          "VALUES (:c, :id, :bid, :ts)",
          {"c": target.content, "id": target.id, "bid": target.book_id, "ts": _iso(target.created_at)})


@event.listens_for(Note, "after_update")
def _note_updated(mapper, connection, target):
    _safe(connection, "DELETE FROM notes_fts WHERE note_id = :id", {"id": target.id})
    _safe(connection,
          "INSERT INTO notes_fts (content, note_id, book_id, created_at) "
          "VALUES (:c, :id, :bid, :ts)",
          {"c": target.content, "id": target.id, "bid": target.book_id, "ts": _iso(target.created_at)})


@event.listens_for(Note, "after_delete")
def _note_deleted(mapper, connection, target):
    _safe(connection, "DELETE FROM notes_fts WHERE note_id = :id", {"id": target.id})


@event.listens_for(Quote, "after_insert")
def _quote_inserted(mapper, connection, target):
    _safe(connection,
          "INSERT INTO quotes_fts (content, quote_id, book_id, page, created_at) "
          "VALUES (:c, :id, :bid, :pg, :ts)",
          {"c": target.content, "id": target.id, "bid": target.book_id,
           "pg": target.page, "ts": _iso(target.created_at)})


@event.listens_for(Quote, "after_update")
def _quote_updated(mapper, connection, target):
    _safe(connection, "DELETE FROM quotes_fts WHERE quote_id = :id", {"id": target.id})
    _safe(connection,
          "INSERT INTO quotes_fts (content, quote_id, book_id, page, created_at) "
          "VALUES (:c, :id, :bid, :pg, :ts)",
          {"c": target.content, "id": target.id, "bid": target.book_id,
           "pg": target.page, "ts": _iso(target.created_at)})


@event.listens_for(Quote, "after_delete")
def _quote_deleted(mapper, connection, target):
    _safe(connection, "DELETE FROM quotes_fts WHERE quote_id = :id", {"id": target.id})


# ── Query helpers ─────────────────────────────────────────────────────────────

def _fts_query(q: str) -> str:
    """Sanitize a free-text query for FTS5 — stripping operators, prefix-matching each token."""
    tokens = [t for t in (w.strip() for w in q.replace('"', "").replace("'", "").split()) if t]
    if not tokens:
        return ""
    # Each token becomes a prefix match; AND between tokens (the default).
    return " ".join(f'"{t}"*' for t in tokens)


def search_all(conn: Connection, q: str, limit: int = 8) -> dict:
    fq = _fts_query(q)
    if not fq:
        return {"messages": [], "notes": [], "quotes": []}

    msg_rows = conn.execute(text(
        "SELECT message_id, session_id, role, created_at, "
        "snippet(messages_fts, 0, '<mark>', '</mark>', '…', 12) AS sn "
        "FROM messages_fts WHERE messages_fts MATCH :q ORDER BY rank LIMIT :limit"
    ), {"q": fq, "limit": limit}).fetchall()

    note_rows = conn.execute(text(
        "SELECT n.note_id, n.book_id, n.created_at, "
        "snippet(notes_fts, 0, '<mark>', '</mark>', '…', 12) AS sn, "
        "b.title AS book_title "
        "FROM notes_fts n LEFT JOIN books b ON b.id = n.book_id "
        "WHERE notes_fts MATCH :q ORDER BY rank LIMIT :limit"
    ), {"q": fq, "limit": limit}).fetchall()

    quote_rows = conn.execute(text(
        "SELECT q.quote_id, q.book_id, q.page, q.created_at, "
        "snippet(quotes_fts, 0, '<mark>', '</mark>', '…', 12) AS sn, "
        "b.title AS book_title "
        "FROM quotes_fts q LEFT JOIN books b ON b.id = q.book_id "
        "WHERE quotes_fts MATCH :q ORDER BY rank LIMIT :limit"
    ), {"q": fq, "limit": limit}).fetchall()

    return {
        "messages": [
            {"id": r[0], "session_id": r[1], "role": r[2], "created_at": r[3], "snippet": r[4]}
            for r in msg_rows
        ],
        "notes": [
            {"id": r[0], "book_id": r[1], "created_at": r[2], "snippet": r[3], "book_title": r[4]}
            for r in note_rows
        ],
        "quotes": [
            {"id": r[0], "book_id": r[1], "page": r[2], "created_at": r[3], "snippet": r[4], "book_title": r[5]}
            for r in quote_rows
        ],
    }
