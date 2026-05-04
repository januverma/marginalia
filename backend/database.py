from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401 — ensures models are registered
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    # Search index + ORM event listeners (importing the module wires the events)
    from . import search  # noqa: F401
    search.init_search_index()


def _run_migrations() -> None:
    """Idempotent column-adds for existing SQLite databases."""
    additions = [
        ("taste_profile", "structured", "TEXT"),
        ("taste_profile", "delta_summary", "TEXT"),
        ("suggestions", "voice", "VARCHAR(20)"),
        ("books", "last_cover_attempt_at", "DATETIME"),
    ]
    with engine.begin() as conn:
        for table, col, coltype in additions:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {r[1] for r in rows}
            if col not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
