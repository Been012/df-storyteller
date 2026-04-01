"""FastAPI web application for df-storyteller.

All routes live in ``routers/``. This file handles app creation,
lifespan, static mounts, and router registration.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    set_legends_preloaded,
)

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"


@asynccontextmanager
async def lifespan(the_app: FastAPI):
    """Preload legends data in background at server startup."""
    def _bg_load():
        try:
            config = _get_config()
            _load_game_state_safe(config, skip_legends=False)
            set_legends_preloaded(True)
        except Exception as e:
            logger.warning("Legends preload failed: %s", e)

    threading.Thread(target=_bg_load, daemon=True).start()
    yield


app = FastAPI(title="df-storyteller", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Import templates_setup to register Jinja2 globals/filters before any request
import df_storyteller.web.templates_setup  # noqa: F401, E402

# Register routers
from df_storyteller.web.routers import (  # noqa: E402
    settings, highlights, notes, worlds,
    dashboard, quests, chronicle, stories, gazette,
    dwarves, events, military,
    lore_index, lore_detail, lore_api,
    images,
    portraits,
)

app.include_router(settings.router)
app.include_router(highlights.router)
app.include_router(notes.router)
app.include_router(worlds.router)
app.include_router(dashboard.router)
app.include_router(quests.router)
app.include_router(chronicle.router)
app.include_router(stories.router)
app.include_router(gazette.router)
app.include_router(dwarves.router)
app.include_router(military.router)
app.include_router(events.router)
app.include_router(lore_index.router)
app.include_router(lore_detail.router)
app.include_router(lore_api.router)
app.include_router(images.router)
app.include_router(portraits.router)


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
