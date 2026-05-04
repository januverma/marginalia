import os
import json
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

def _sanitize_key(raw: str) -> str:
    """Drop empty / commented / placeholder values from .env."""
    val = (raw or "").strip()
    if not val or val.startswith("#") or " " in val or val.startswith("sk-ant-..."):
        return ""
    return val


ANTHROPIC_API_KEY = _sanitize_key(os.getenv("ANTHROPIC_API_KEY", ""))
GOOGLE_BOOKS_API_KEY = _sanitize_key(os.getenv("GOOGLE_BOOKS_API_KEY", ""))
DATABASE_URL = f"sqlite:///{ROOT / 'curator.db'}"


def load_profile() -> dict:
    path = ROOT / "profile.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"name": "Reader", "voice": "sage"}


def save_profile(data: dict) -> None:
    path = ROOT / "profile.json"
    path.write_text(json.dumps(data, indent=2))
