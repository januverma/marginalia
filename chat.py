#!/usr/bin/env python3
"""
Terminal chat loop for the Marginalia.
Run: python chat.py
Optionally resume a session: python chat.py --session 3
"""
import sys
import argparse
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.database import init_db, SessionLocal
from backend.models import Session as ChatSession, Message, Suggestion
from backend.config import load_profile, ANTHROPIC_API_KEY
from backend.context_assembler import assemble_context
from backend.suggestion_parser import parse_suggestions
from backend.book_resolver import find_or_create_book
import anthropic


def wrap(text: str, width: int = 80) -> str:
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if line.strip() == "":
            wrapped.append("")
        else:
            wrapped.extend(textwrap.wrap(line, width=width) or [""])
    return "\n".join(wrapped)


def print_reply(reply: str, tracked: int) -> None:
    print()
    print("─" * 80)
    print(wrap(reply))
    print("─" * 80)
    if tracked:
        print(f"  [{tracked} book{'s' if tracked != 1 else ''} tracked]")
    print()


def process_response(db, session_id: int, raw_reply: str):
    clean, books = parse_suggestions(raw_reply)

    db.add(Message(session_id=session_id, role="assistant", content=clean))

    for b in books:
        title = b.get("title", "").strip()
        author = b.get("author", "").strip()
        if not title or not author:
            continue
        book = find_or_create_book(db, title, author, b.get("pub_year"))
        db.add(Suggestion(
            book_id=book.id,
            session_id=session_id,
            reason_given=b.get("reason", "").strip() or None,
        ))

    db.commit()
    return clean, len(books)


def main():
    parser = argparse.ArgumentParser(description="Marginalia — terminal chat")
    parser.add_argument("--session", type=int, help="Resume an existing session by ID")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not set. Add it to .env")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    profile = load_profile()

    voice = profile.get("voice", "sage")
    name = profile.get("name", "Reader")

    if args.session:
        session = db.query(ChatSession).filter(ChatSession.id == args.session).first()
        if not session:
            print(f"Session {args.session} not found.")
            sys.exit(1)
        msg_count = len(session.messages)
        print(f"\nResuming session #{session.id} ({msg_count} messages).")
    else:
        session = ChatSession(title=None)
        db.add(session)
        db.commit()
        db.refresh(session)
        print(f"\nNew session #{session.id} started.")

    print(f"Voice: {voice.title()} | Type 'quit' or Ctrl-C to exit.\n")
    print("=" * 80)
    print(f"  Marginalia — welcome, {name}.")
    print("=" * 80)
    print()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        db.add(Message(session_id=session.id, role="user", content=user_input))
        db.commit()

        web_search = profile.get("web_search_enabled", True)
        ctx = assemble_context(db, session.id, voice, web_search_enabled=web_search)

        print("\nThinking...", end="\r")

        kwargs = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 2048,
            "system": ctx["system"],
            "messages": ctx["messages"],
        }
        if web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]

        response = client.messages.create(**kwargs)

        print(" " * 20, end="\r")
        # Response may include tool_use blocks alongside text — concat text only.
        raw_text = "".join(
            getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"
        )
        clean, tracked = process_response(db, session.id, raw_text)
        print_reply(clean, tracked)


if __name__ == "__main__":
    main()
