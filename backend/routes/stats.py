from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func

from ..config import load_profile
from ..database import get_db
from ..models import Book, ReadingLog, Note, Quote, Message, Session, Suggestion

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _day_key(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.date().isoformat()


@router.get("")
def get_stats(db: DBSession = Depends(get_db)):
    status_counts = dict(
        db.query(ReadingLog.status, func.count(ReadingLog.id))
        .group_by(ReadingLog.status)
        .all()
    )

    avg_rating = (
        db.query(func.avg(ReadingLog.rating))
        .filter(ReadingLog.rating.isnot(None))
        .scalar()
    )

    total_books = db.query(Book).count()
    total_notes = db.query(Note).count()
    total_quotes = db.query(Quote).count()
    total_suggestions = db.query(Suggestion).count()

    heatmap: dict[str, int] = defaultdict(int)

    for log in db.query(ReadingLog).all():
        if log.finished_at:
            heatmap[_day_key(log.finished_at)] += 2
        if log.started_at:
            heatmap[_day_key(log.started_at)] += 1

    for note in db.query(Note).all():
        heatmap[_day_key(note.created_at)] += 1

    for quote in db.query(Quote).all():
        heatmap[_day_key(quote.created_at)] += 1

    for msg in db.query(Message).filter(Message.role == "user").all():
        heatmap[_day_key(msg.created_at)] += 1

    # earliest + latest activity
    dates = sorted(heatmap.keys())
    first_activity = dates[0] if dates else None
    last_activity = dates[-1] if dates else None

    # ── Goal progress ─────────────────────────────────────────────────────
    profile = load_profile()
    goal_year = profile.get("annual_goal_year")
    goal_target = profile.get("annual_goal_count")
    goal_progress = None
    if goal_year and goal_target and goal_target > 0:
        today = datetime.now(timezone.utc)
        days_in_year = 366 if calendar.isleap(goal_year) else 365
        if goal_year == today.year:
            days_elapsed = today.timetuple().tm_yday
        elif goal_year < today.year:
            days_elapsed = days_in_year  # past year — show final state
        else:
            days_elapsed = 0  # future year — nothing has happened yet

        completed = (
            db.query(ReadingLog)
            .filter(
                ReadingLog.status == "read",
                func.strftime("%Y", ReadingLog.finished_at) == str(goal_year),
            )
            .count()
        )
        expected = goal_target * (days_elapsed / days_in_year)
        goal_progress = {
            "year": goal_year,
            "target": goal_target,
            "completed": completed,
            "expected_by_now": round(expected, 1),
            "pace_delta": round(completed - expected, 1),
            "days_elapsed": days_elapsed,
            "days_in_year": days_in_year,
        }

    return {
        "total_books": total_books,
        "total_notes": total_notes,
        "total_quotes": total_quotes,
        "total_suggestions": total_suggestions,
        "goal_progress": goal_progress,
        "shelves": {
            "reading": status_counts.get("reading", 0),
            "read": status_counts.get("read", 0),
            "want_to_read": status_counts.get("want_to_read", 0),
            "abandoned": status_counts.get("abandoned", 0),
        },
        "avg_rating": round(float(avg_rating), 1) if avg_rating else None,
        "heatmap": dict(heatmap),
        "first_activity": first_activity,
        "last_activity": last_activity,
    }
