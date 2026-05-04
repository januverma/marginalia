from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel

from ..database import get_db
from ..config import load_profile, save_profile
from ..models import TasteProfile
from ..context_assembler import VOICE_PROMPTS
from ..taste_engine import generate_taste_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileOut(BaseModel):
    name: str
    voice: str
    web_search_enabled: bool = True
    annual_goal_year: Optional[int] = None
    annual_goal_count: Optional[int] = None
    taste_summary: Optional[str] = None
    taste_generated_at: Optional[datetime] = None
    taste_constellation: Optional[Any] = None  # {themes: [...], connections: [...]}
    taste_delta: Optional[str] = None  # what's shifted vs the prior portrait
    taste_delta_since: Optional[datetime] = None  # when the prior portrait was generated


class ProfileUpdate(BaseModel):
    voice: Optional[str] = None
    name: Optional[str] = None
    web_search_enabled: Optional[bool] = None
    annual_goal_year: Optional[int] = None
    annual_goal_count: Optional[int] = None


def _current(db: DBSession) -> ProfileOut:
    profile = load_profile()
    taste = db.query(TasteProfile).order_by(TasteProfile.created_at.desc()).first()

    constellation = None
    if taste and taste.structured:
        try:
            constellation = json.loads(taste.structured)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Stored taste.structured is not valid JSON")

    # When did the prior portrait we compared against come from?
    delta_since = None
    if taste and taste.delta_summary:
        prior = (
            db.query(TasteProfile)
            .filter(TasteProfile.id != taste.id)
            .order_by(TasteProfile.created_at.desc())
            .first()
        )
        delta_since = prior.created_at if prior else None

    return ProfileOut(
        name=profile.get("name", "Reader"),
        voice=profile.get("voice", "sage"),
        web_search_enabled=profile.get("web_search_enabled", True),
        annual_goal_year=profile.get("annual_goal_year"),
        annual_goal_count=profile.get("annual_goal_count"),
        taste_summary=taste.summary if taste else None,
        taste_generated_at=taste.created_at if taste else None,
        taste_constellation=constellation,
        taste_delta=taste.delta_summary if taste else None,
        taste_delta_since=delta_since,
    )


@router.get("", response_model=ProfileOut)
def get_profile(db: DBSession = Depends(get_db)):
    return _current(db)


@router.patch("", response_model=ProfileOut)
def update_profile(body: ProfileUpdate, db: DBSession = Depends(get_db)):
    profile = load_profile()
    if body.voice is not None:
        if body.voice not in VOICE_PROMPTS:
            raise HTTPException(
                status_code=422,
                detail=f"voice must be one of {list(VOICE_PROMPTS.keys())}",
            )
        profile["voice"] = body.voice
    if body.name is not None:
        profile["name"] = body.name
    if body.web_search_enabled is not None:
        profile["web_search_enabled"] = body.web_search_enabled
    if body.annual_goal_year is not None:
        profile["annual_goal_year"] = body.annual_goal_year
    if body.annual_goal_count is not None:
        # 0 means "clear the goal"
        if body.annual_goal_count <= 0:
            profile.pop("annual_goal_count", None)
            profile.pop("annual_goal_year", None)
        else:
            profile["annual_goal_count"] = body.annual_goal_count
    save_profile(profile)
    return _current(db)


@router.post("/refresh-taste", response_model=ProfileOut)
def refresh_taste(db: DBSession = Depends(get_db)):
    generate_taste_profile(db)
    return _current(db)
