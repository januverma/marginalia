from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    isbn: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    buy_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pub_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_cover_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    suggestions: Mapped[List[Suggestion]] = relationship(back_populates="book")
    reading_log: Mapped[List[ReadingLog]] = relationship(back_populates="book")
    notes: Mapped[List[Note]] = relationship(back_populates="book")
    quotes: Mapped[List[Quote]] = relationship(back_populates="book")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    messages: Mapped[List[Message]] = relationship(
        back_populates="session", order_by="Message.created_at"
    )
    suggestions: Mapped[List[Suggestion]] = relationship(back_populates="session")
    taste_signals: Mapped[List[TasteSignal]] = relationship(back_populates="session")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped[Session] = relationship(back_populates="messages")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    # suggested | purchased | reading | read | dismissed
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    reason_given: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # persona at time of suggestion
    suggested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    book: Mapped[Book] = relationship(back_populates="suggestions")
    session: Mapped[Session] = relationship(back_populates="suggestions")


class ReadingLog(Base):
    __tablename__ = "reading_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    # want_to_read | reading | read | abandoned
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    book: Mapped[Book] = relationship(back_populates="reading_log")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    book: Mapped[Book] = relationship(back_populates="notes")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    book: Mapped[Book] = relationship(back_populates="quotes")


class TasteProfile(Base):
    __tablename__ = "taste_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    generated_from: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON snapshot
    structured: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {themes, connections}
    delta_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # what shifted vs prior portrait
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class TasteSignal(Base):
    __tablename__ = "taste_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped[Session] = relationship(back_populates="taste_signals")


class LibrarianPrompt(Base):
    """A question the librarian wants to ask the reader, generated after a meaningful taste shift."""
    __tablename__ = "librarian_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | answered | dismissed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"), nullable=True)
