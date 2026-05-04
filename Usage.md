# Usage

## Setup

```bash
cp .env.example .env
# edit .env — add your ANTHROPIC_API_KEY

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Start a conversation

```bash
python chat.py
```

Resume a previous session by ID:

```bash
python chat.py --session 3
```

## Change voice

Edit `profile.json` and set `voice` to one of: `sage`, `bookseller`, `provocateur`, `companion`. Takes effect on next run.

## Manage your library

```bash
# Log a book you've read (resolves against Google Books if possible)
python library.py log "Stoner" "John Williams" --rating 5

# Log a book by existing ID (e.g. one the librarian suggested)
python library.py log --book 3 --status reading

# See every book the system knows about
python library.py books

# See all pending suggestions
python library.py sugs
python library.py sugs --status dismissed

# Update a suggestion's status
python library.py mark 7 purchased   # or: reading, read, dismissed

# Update a reading log entry
python library.py update 2 --status read --rating 4

# Write a note about a book
python library.py note 3 "The prose reminded me of Sebald"
python library.py notes --book 3
```

Anything you log here is folded into the context on the next chat — the librarian starts referencing what you've actually read.

## Inspect the database

All books Claude has ever suggested:

```bash
sqlite3 curator.db "SELECT b.title, b.author, s.status, s.reason_given FROM books b JOIN suggestions s ON s.book_id = b.id;"
```

All sessions:

```bash
sqlite3 curator.db "SELECT id, title, created_at FROM sessions;"
```

Full message history for a session:

```bash
sqlite3 curator.db "SELECT role, content FROM messages WHERE session_id = 1 ORDER BY created_at;"
```

## Run the web app

```bash
uvicorn backend.main:app --reload
```

Then open:
- `http://localhost:8000/` — chat (with voice switcher)
- `http://localhost:8000/library` — your reading log + notes
- `http://localhost:8000/suggestions` — suggestion inbox (update status)
- `http://localhost:8000/taste` — taste profile (placeholder until Phase 3)

API docs: `http://localhost:8000/docs`.
