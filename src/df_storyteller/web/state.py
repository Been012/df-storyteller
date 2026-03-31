"""Shared mutable state and cache logic for the web application.

All module-level globals, caches, and accessor functions live here.
Routers import from this module — never from app.py.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from df_storyteller.config import AppConfig, load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mutable state
# ---------------------------------------------------------------------------

_active_world: str | None = None
_event_subscribers: list[WebSocket] = []

# Separate caches: with_legends is a superset of no_legends
_cached_no_legends: tuple | None = None   # (event_store, char_tracker, world_lore, metadata)
_cached_with_legends: tuple | None = None
_cache_time_no_legends: float = 0
_cache_time_with_legends: float = 0
_CACHE_TTL_DEFAULT: float = 300  # fallback if config not yet loaded

_legends_preloaded: bool = False
_legends_load_lock = threading.Lock()

# Hotlink cache: name -> (entity_type, entity_id) for [[name]] syntax
_hotlink_cache: dict[str, tuple[str, int | str]] | None = None

# Map image cache
_map_image_cache: tuple[bytes, int, int] | None = None

# Constants
SEASON_ORDER_MAP = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def get_config() -> AppConfig:
    return load_config()


# ---------------------------------------------------------------------------
# World management
# ---------------------------------------------------------------------------


def get_worlds(config: AppConfig) -> list[str]:
    """List available world subfolders, most recently active first."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return []

    def _newest_file_time(folder_name: str) -> float:
        folder = base / folder_name
        files = list(folder.glob("*.json"))
        if files:
            return max(f.stat().st_mtime for f in files)
        return folder.stat().st_mtime

    return sorted(
        [d.name for d in base.iterdir() if d.is_dir() and d.name != "processed"],
        key=_newest_file_time,
        reverse=True,
    )


def safe_watch_dir(config: AppConfig, world: str) -> Path | None:
    """Build a watch directory path and validate it stays within the event dir."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not world:
        return None
    candidate = (base / world).resolve()
    if not candidate.is_relative_to(base.resolve()):
        return None
    return candidate


def get_active_world(config: AppConfig) -> str:
    global _active_world
    if _active_world:
        return _active_world
    worlds = get_worlds(config)
    return worlds[0] if worlds else ""


def set_active_world(world: str) -> None:
    global _active_world
    _active_world = world


# ---------------------------------------------------------------------------
# Event subscribers (WebSocket)
# ---------------------------------------------------------------------------


def get_event_subscribers() -> list[WebSocket]:
    return _event_subscribers


def add_event_subscriber(ws: WebSocket) -> None:
    _event_subscribers.append(ws)


def remove_event_subscriber(ws: WebSocket) -> None:
    if ws in _event_subscribers:
        _event_subscribers.remove(ws)


# ---------------------------------------------------------------------------
# Game state caching
# ---------------------------------------------------------------------------


def _empty_state():
    from df_storyteller.context.event_store import EventStore
    from df_storyteller.context.character_tracker import CharacterTracker
    from df_storyteller.context.world_lore import WorldLore
    empty_meta: dict[str, Any] = {
        "fortress_name": "", "site_name": "", "civ_name": "", "biome": "",
        "year": 0, "season": "", "population": 0,
        "visitors": [], "animals": [], "buildings": [], "fortress_info": {},
    }
    return EventStore(), CharacterTracker(), WorldLore(), empty_meta


def _get_newest_snapshot_time(config: AppConfig) -> float:
    """Get modification time of the newest data file (snapshot or event)."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return 0
    world_dirs = [d for d in base.iterdir() if d.is_dir() and d.name != "processed"]
    if not world_dirs:
        return 0
    world_dir = max(world_dirs, key=lambda d: d.stat().st_mtime)
    all_json = list(world_dir.glob("*.json"))
    if not all_json:
        return 0
    return max(f.stat().st_mtime for f in all_json)


def load_game_state_safe(config: AppConfig, skip_legends: bool = True):
    """Load game state with caching.

    Auto-invalidates when a new snapshot is detected.
    skip_legends=True (default) makes page loads fast by not parsing XML.
    Only set skip_legends=False for Lore tab and story generation.

    Uses separate caches for legends/no-legends so navigating between
    pages doesn't force an expensive XML reparse. A with_legends cache
    can serve no_legends requests (it's a superset).
    """
    from df_storyteller.context.loader import load_game_state

    global _cached_no_legends, _cached_with_legends
    global _cache_time_no_legends, _cache_time_with_legends

    now = time.time()
    newest = _get_newest_snapshot_time(config)
    cache_ttl = config.web.cache_ttl_seconds

    # Try to serve from the with_legends cache first (superset of no_legends)
    if _cached_with_legends and (now - _cache_time_with_legends) < cache_ttl:
        if newest <= _cache_time_with_legends:
            return _cached_with_legends

    # If legends not needed, try the no_legends cache
    if skip_legends and _cached_no_legends and (now - _cache_time_no_legends) < cache_ttl:
        if newest <= _cache_time_no_legends:
            return _cached_no_legends

    # For legends loads, use a lock to prevent duplicate parsing
    if not skip_legends:
        with _legends_load_lock:
            # Re-check cache inside lock
            if _cached_with_legends and (now - _cache_time_with_legends) < cache_ttl:
                if newest <= _cache_time_with_legends:
                    return _cached_with_legends
            try:
                active_world = get_active_world(config)
                result = load_game_state(config, skip_legends=False, active_world=active_world)
                _cached_with_legends = result
                _cache_time_with_legends = time.time()
                return result
            except Exception as e:
                logger.warning("Failed to load game state: %s", e)
                return _empty_state()

    try:
        active_world = get_active_world(config)
        result = load_game_state(config, skip_legends=True, active_world=active_world)
        _cached_no_legends = result
        _cache_time_no_legends = now
        return result
    except Exception as e:
        logger.warning("Failed to load game state: %s", e)
        return _empty_state()


def invalidate_cache() -> None:
    """Clear the cache (call when world switches or settings change)."""
    global _cached_no_legends, _cached_with_legends
    global _cache_time_no_legends, _cache_time_with_legends
    global _map_image_cache, _hotlink_cache
    _cached_no_legends = None
    _cached_with_legends = None
    _cache_time_no_legends = 0
    _cache_time_with_legends = 0
    _map_image_cache = None
    _hotlink_cache = None


def get_fortress_dir(config: AppConfig, metadata: dict | None = None) -> Path:
    """Get the per-fortress output directory for the active fortress."""
    from df_storyteller.context.loader import get_fortress_output_dir
    if metadata is None:
        _, _, _, metadata = load_game_state_safe(config)
    return get_fortress_output_dir(config, metadata)


# ---------------------------------------------------------------------------
# Legends preload state
# ---------------------------------------------------------------------------


def is_legends_preloaded() -> bool:
    return _legends_preloaded


def set_legends_preloaded(value: bool) -> None:
    global _legends_preloaded
    _legends_preloaded = value


# ---------------------------------------------------------------------------
# Hotlink cache accessors
# ---------------------------------------------------------------------------


def get_hotlink_cache() -> dict[str, tuple[str, int | str]] | None:
    return _hotlink_cache


def set_hotlink_cache(cache: dict[str, tuple[str, int | str]]) -> None:
    global _hotlink_cache
    _hotlink_cache = cache


# ---------------------------------------------------------------------------
# Map image cache accessors
# ---------------------------------------------------------------------------


def get_map_image_cache() -> tuple[bytes, int, int] | None:
    return _map_image_cache


def set_map_image_cache(value: tuple[bytes, int, int]) -> None:
    global _map_image_cache
    _map_image_cache = value


# ---------------------------------------------------------------------------
# Base template context
# ---------------------------------------------------------------------------


def base_context(config: AppConfig, active_tab: str, metadata: dict | None = None) -> dict:
    """Common template context for all pages."""
    worlds = get_worlds(config)
    active_world = get_active_world(config)

    if metadata is None:
        _, _, _, metadata = load_game_state_safe(config)

    # Count events across all world folders for the status bar
    event_dir_base = Path(config.paths.event_dir) if config.paths.event_dir else None
    event_count = 0
    if event_dir_base and event_dir_base.exists():
        for wd in event_dir_base.iterdir():
            if wd.is_dir() and wd.name != "processed":
                event_count += len([f for f in wd.glob("*.json") if not f.name.startswith("snapshot_")])

    # Last updated timestamp
    last_updated = ""
    _latest_cache_time = max(_cache_time_no_legends, _cache_time_with_legends)
    if _latest_cache_time > 0:
        age = int(time.time() - _latest_cache_time)
        if age < 60:
            last_updated = f"{age}s ago"
        elif age < 3600:
            last_updated = f"{age // 60}m ago"
        else:
            last_updated = f"{age // 3600}h ago"

    # Determine setup state for guidance
    has_config = bool(config.paths.df_install)
    has_data = bool(metadata.get("fortress_name"))

    setup_step = ""
    if not has_config:
        setup_step = "no_config"
    elif not has_data:
        setup_step = "no_data"

    return {
        "active_tab": active_tab,
        "worlds": worlds,
        "active_world": active_world,
        "fortress_name": metadata.get("fortress_name", ""),
        "site_name": metadata.get("site_name", ""),
        "civ_name": metadata.get("civ_name", ""),
        "biome": metadata.get("biome", "").replace("_", " ").title(),
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "").title(),
        "population": metadata.get("population", 0),
        "event_count": event_count,
        "last_updated": last_updated,
        "setup_step": setup_step,
        "no_llm_mode": config.story.no_llm_mode,
    }
