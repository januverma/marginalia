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


# ── Model selection per role ──────────────────────────────────────────────────
# All three are overridable via env vars. Defaults reflect cost/quality tradeoffs:
#   - chat is per-turn and streamed → keep Sonnet for snappy UX and lower cost
#   - "deep" work (portrait, delta, librarian-initiated questions) is rare and
#     where quality matters most → default to Opus
#   - signal extraction runs after every user turn → keep Haiku (cheap, fast)
CHAT_MODEL = os.getenv("MARGINALIA_CHAT_MODEL", "claude-sonnet-4-6")
DEEP_MODEL = os.getenv("MARGINALIA_DEEP_MODEL", "claude-opus-4-7")
SIGNAL_MODEL = os.getenv("MARGINALIA_SIGNAL_MODEL", "claude-haiku-4-5-20251001")
DATABASE_URL = f"sqlite:///{ROOT / 'curator.db'}"


def load_profile() -> dict:
    path = ROOT / "profile.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"name": "Reader", "voice": "sage"}


def save_profile(data: dict) -> None:
    path = ROOT / "profile.json"
    path.write_text(json.dumps(data, indent=2))
