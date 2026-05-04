import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import init_db
from .book_resolver import sweep_missing_covers
from .routes import chat, sessions, library, suggestions, profile, stats, search, prompts

logger = logging.getLogger(__name__)
COVER_SWEEP_INTERVAL_S = 20 * 60  # 20 minutes

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


async def _cover_sweep_loop():
    """Periodically retry Google Books for any book that's still missing a cover."""
    await asyncio.sleep(30)  # let the app finish starting before the first sweep
    while True:
        try:
            await asyncio.to_thread(sweep_missing_covers)
        except Exception as e:
            logger.warning(f"Cover sweep iteration failed: {e}")
        await asyncio.sleep(COVER_SWEEP_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sweep_task = asyncio.create_task(_cover_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="Marginalia", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(library.router)
app.include_router(suggestions.router)
app.include_router(profile.router)
app.include_router(stats.router)
app.include_router(search.router)
app.include_router(prompts.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Static assets + page routes — no-cache headers so JS/CSS updates land immediately
class _NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


app.mount("/static", _NoCacheStatic(directory=FRONTEND_DIR / "static"), name="static")


def _page(name: str) -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / name,
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/")
def page_chat():
    return _page("index.html")


@app.get("/library")
def page_library():
    return _page("library.html")


@app.get("/suggestions")
def page_suggestions():
    return _page("suggestions.html")


@app.get("/taste")
def page_taste():
    return _page("taste.html")
