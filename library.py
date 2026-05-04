#!/usr/bin/env python3
"""
Marginalia — library management CLI.

Examples:
  python library.py log "Stoner" "John Williams" --rating 5
  python library.py log --book 3 --status reading
  python library.py books
  python library.py sugs --status suggested
  python library.py mark 7 purchased
  python library.py note 3 "Reminds me of Sebald"
  python library.py notes --book 3
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

from backend.database import init_db, SessionLocal
from backend.models import Book, ReadingLog, Note, Suggestion
from backend.book_resolver import find_or_create_book

READ_STATUSES = ["want_to_read", "reading", "read", "abandoned"]
SUG_STATUSES = ["suggested", "purchased", "reading", "read", "dismissed"]


def cmd_log(args, db):
    if args.book_id:
        book = db.query(Book).filter(Book.id == args.book_id).first()
        if not book:
            print(f"Error: book #{args.book_id} not found")
            return 1
    elif args.title and args.author:
        book = find_or_create_book(db, args.title, args.author)
    else:
        print("Error: provide <title> <author> or --book <id>")
        return 1

    now = datetime.now(timezone.utc)
    entry = ReadingLog(book_id=book.id, status=args.status, rating=args.rating)
    if args.status in ("reading", "read"):
        entry.started_at = now
    if args.status in ("read", "abandoned"):
        entry.finished_at = now

    db.add(entry)
    db.commit()
    db.refresh(entry)

    rating_str = f" — {args.rating}/5" if args.rating else ""
    print(f"Logged #{entry.id}: {book.title} by {book.author} [{args.status}{rating_str}]")


def cmd_books(args, db):
    books = db.query(Book).order_by(Book.first_seen.desc()).all()
    if not books:
        print("No books yet. Chat with the librarian or use `log` to add one.")
        return
    for book in books:
        statuses = [l.status for l in book.reading_log] or ["—"]
        year = f" ({book.pub_year})" if book.pub_year else ""
        print(f"  #{book.id:<4} {book.title}{year} — {book.author}  [{', '.join(statuses)}]")


def cmd_update(args, db):
    entry = db.query(ReadingLog).filter(ReadingLog.id == args.entry_id).first()
    if not entry:
        print(f"Error: reading log entry #{args.entry_id} not found")
        return 1
    now = datetime.now(timezone.utc)
    if args.status:
        entry.status = args.status
        if args.status in ("reading", "read") and not entry.started_at:
            entry.started_at = now
        if args.status in ("read", "abandoned") and not entry.finished_at:
            entry.finished_at = now
    if args.rating is not None:
        entry.rating = args.rating
    db.commit()
    print(f"Updated reading log #{entry.id}")


def cmd_sugs(args, db):
    q = db.query(Suggestion)
    if args.status:
        q = q.filter(Suggestion.status == args.status)
    sugs = q.order_by(Suggestion.suggested_at.desc()).all()
    if not sugs:
        print("No suggestions matching.")
        return
    for s in sugs:
        date = s.suggested_at.strftime("%b %d")
        reason = f"\n            {s.reason_given}" if s.reason_given else ""
        print(f"  #{s.id:<4} [{s.status:10}] {s.book.title} — {s.book.author} ({date}){reason}")


def cmd_mark(args, db):
    sug = db.query(Suggestion).filter(Suggestion.id == args.suggestion_id).first()
    if not sug:
        print(f"Error: suggestion #{args.suggestion_id} not found")
        return 1
    sug.status = args.status
    sug.status_changed_at = datetime.now(timezone.utc)
    db.commit()
    print(f"Suggestion #{sug.id} ({sug.book.title}) -> {args.status}")


def cmd_note(args, db):
    book = db.query(Book).filter(Book.id == args.book_id).first()
    if not book:
        print(f"Error: book #{args.book_id} not found")
        return 1
    note = Note(book_id=args.book_id, content=args.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    print(f"Note #{note.id} added to {book.title}")


def cmd_notes(args, db):
    q = db.query(Note)
    if args.book:
        q = q.filter(Note.book_id == args.book)
    notes = q.order_by(Note.created_at.desc()).all()
    if not notes:
        print("No notes.")
        return
    for n in notes:
        date = n.created_at.strftime("%Y-%m-%d")
        book = db.query(Book).filter(Book.id == n.book_id).first()
        title = book.title if book else f"book #{n.book_id}"
        print(f"  #{n.id:<4} [{date}] {title}: {n.content}")


def build_parser():
    p = argparse.ArgumentParser(description="Marginalia — library management")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("log", help="Add a book to your reading log")
    s.add_argument("title", nargs="?")
    s.add_argument("author", nargs="?")
    s.add_argument("--book", dest="book_id", type=int, help="Use existing book ID")
    s.add_argument("--status", choices=READ_STATUSES, default="read")
    s.add_argument("--rating", type=int, choices=[1, 2, 3, 4, 5])
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("books", help="List all books the system knows")
    s.set_defaults(func=cmd_books)

    s = sub.add_parser("update", help="Update a reading log entry")
    s.add_argument("entry_id", type=int)
    s.add_argument("--status", choices=READ_STATUSES)
    s.add_argument("--rating", type=int, choices=[1, 2, 3, 4, 5])
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("sugs", help="List suggestions the librarian has made")
    s.add_argument("--status", choices=SUG_STATUSES)
    s.set_defaults(func=cmd_sugs)

    s = sub.add_parser("mark", help="Update a suggestion's status")
    s.add_argument("suggestion_id", type=int)
    s.add_argument("status", choices=SUG_STATUSES)
    s.set_defaults(func=cmd_mark)

    s = sub.add_parser("note", help="Add a note to a book")
    s.add_argument("book_id", type=int)
    s.add_argument("content")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("notes", help="List notes")
    s.add_argument("--book", type=int, help="Filter by book ID")
    s.set_defaults(func=cmd_notes)

    return p


def main():
    args = build_parser().parse_args()
    init_db()
    db = SessionLocal()
    try:
        code = args.func(args, db) or 0
    finally:
        db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
