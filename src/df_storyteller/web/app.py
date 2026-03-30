"""FastAPI web application for df-storyteller."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from df_storyteller.config import AppConfig, load_config, save_config
from df_storyteller.context.loader import load_game_state
from df_storyteller.context.narrative_formatter import (
    format_dwarf_narrative,
    format_fortress_context,
    _describe_physical_attr,
    _describe_mental_attr,
    _skill_level_name,
    _resolve_skill_name,
)
from df_storyteller.stories.base import create_provider

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    """Preload legends data in background at server startup so Lore tab is instant."""
    import threading

    def _bg_load():
        global _legends_preloaded
        try:
            config = _get_config()
            _load_game_state_safe(config, skip_legends=False)
            _legends_preloaded = True
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Legends preload failed: %s", e)

    threading.Thread(target=_bg_load, daemon=True).start()
    yield


app = FastAPI(title="df-storyteller", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _lore_link(entity_type: str, entity_id: int | str | None, name: str) -> str:
    """Jinja2 global: render a clickable link to a lore detail page."""
    if entity_id is None or not name:
        return name or ""
    from markupsafe import Markup
    url_map = {"figure": "figure", "civilization": "civ", "site": "site",
               "artifact": "artifact", "war": "war", "battle": "war",
               "duel": "event", "purge": "event", "beast_attack": "event",
               "abduction": "event", "theft": "event", "persecution": "event",
               "site_conquest": "event", "overthrow": "event",
               "written_work": "work", "festival": "festival",
               "form_poetic": "form", "form_musical": "form", "form_dance": "form"}
    prefix = url_map.get(entity_type)
    if prefix is None:
        # No detail page for this entity type — render as plain text
        return Markup(f'<span class="lore-link" style="cursor: default; border-bottom-style: none;">{Markup.escape(name)}</span>')
    return Markup(f'<a href="/lore/{prefix}/{entity_id}" class="lore-link">{Markup.escape(name)}</a>')


templates.env.globals["lore_link"] = _lore_link

# Hotlink cache: name -> (entity_type, entity_id) for [[name]] syntax
_hotlink_cache: dict[str, tuple[str, int | str]] | None = None


def _build_hotlink_cache() -> dict[str, tuple[str, int | str]]:
    """Build a name lookup cache from legends data for [[name]] hotlinks."""
    global _hotlink_cache
    if _hotlink_cache is not None:
        return _hotlink_cache

    cache: dict[str, tuple[str, int | str]] = {}
    try:
        config = _get_config()
        _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)
        if world_lore.is_loaded and world_lore._legends:
            legends = world_lore._legends
            # Historical figures (normalize to lowercase for matching)
            for hfid, hf in legends.historical_figures.items():
                if hf.name:
                    cache[hf.name.lower()] = ("figure", hfid)
                    # Also add first name for common short references
                    first = hf.name.split(",")[0].split(" the ")[0].strip()
                    if first and len(first) > 3 and first.lower() not in cache:
                        cache[first.lower()] = ("figure", hfid)
            # Sites
            for sid, site in legends.sites.items():
                if site.name:
                    cache[site.name.lower()] = ("site", sid)
            # Civilizations
            for eid, civ in legends.civilizations.items():
                if civ.name:
                    cache[civ.name.lower()] = ("civilization", eid)
            # Event collections (wars, battles, duels, purges, etc.)
            _ec_type_map = {"war": "war", "battle": "battle", "duel": "duel",
                            "purge": "purge", "entity overthrown": "overthrow",
                            "beast attack": "beast_attack", "abduction": "abduction",
                            "theft": "theft", "persecution": "persecution",
                            "site conquered": "site_conquest"}
            for ec in legends.event_collections:
                name = ec.get("name", "")
                ec_type = ec.get("type", "")
                ec_id = ec.get("id", "")
                mapped = _ec_type_map.get(ec_type)
                if name and ec_id and mapped:
                    cache[name.lower()] = (mapped, ec_id)
            # Artifacts
            for aid, art in legends.artifacts.items():
                if art.name:
                    cache[art.name.lower()] = ("artifact", aid)
            # Written works
            for wc in legends.written_contents:
                title = wc.get("title", "")
                wc_id = wc.get("id", "")
                if title and wc_id:
                    cache[title.lower()] = ("written_work", wc_id)
            # Cultural forms
            for form_type, forms in [("poetic", legends.poetic_forms), ("musical", legends.musical_forms), ("dance", legends.dance_forms)]:
                for f in forms:
                    name = f.get("name", "")
                    fid = f.get("id", "")
                    if name and fid:
                        cache[name.lower()] = (f"form_{form_type}", f"{form_type}/{fid}")
            # Festivals (from civ occasions)
            for civ in legends.civilizations.values():
                for occ in getattr(civ, '_occasions', []):
                    name = occ.get("name", "")
                    oid = occ.get("id", "")
                    if name:
                        cache[name.lower()] = ("festival", f"{civ.entity_id}/{oid}")
    except Exception:
        pass

    _hotlink_cache = cache
    return cache


def _hotlink_filter(text: str) -> str:
    """Jinja2 filter: convert [[name]] patterns to clickable lore links."""
    if "[[" not in text:
        return text

    cache = _build_hotlink_cache()
    if not cache:
        return text.replace("[[", "").replace("]]", "")

    import re
    from markupsafe import Markup, escape

    def replace_match(m: re.Match) -> str:
        name = m.group(1).strip()
        lookup = name.lower()
        if lookup in cache:
            entity_type, entity_id = cache[lookup]
            url_map = {"figure": "figure", "civilization": "civ", "site": "site",
                       "artifact": "artifact", "war": "war", "battle": "war",
                       "duel": "event", "purge": "event", "beast_attack": "event",
                       "abduction": "event", "theft": "event", "persecution": "event",
                       "site_conquest": "event", "overthrow": "event",
                       "written_work": "work", "festival": "festival",
                       "form_poetic": "form", "form_musical": "form", "form_dance": "form"}
            prefix = url_map.get(entity_type)
            if prefix:
                return f'<a href="/lore/{prefix}/{entity_id}" class="lore-link">{escape(name)}</a>'
            return str(escape(name))
        # Not found — render as plain text with a subtle indicator
        return f'<span style="border-bottom: 1px dashed var(--ink-faded);" title="Not found in legends">{escape(name)}</span>'

    result = re.sub(r'\[\[(.+?)\]\]', replace_match, text)
    return Markup(result)


templates.env.filters["hotlink"] = _hotlink_filter

# In-memory state
_active_world: str | None = None
_event_subscribers: list[WebSocket] = []
# Separate caches: with_legends is a superset of no_legends
_cached_no_legends: tuple | None = None   # (event_store, char_tracker, world_lore, metadata)
_cached_with_legends: tuple | None = None  # (event_store, char_tracker, world_lore, metadata)
_cache_time_no_legends: float = 0
_cache_time_with_legends: float = 0
_CACHE_TTL: float = 300  # 5 minutes
_legends_preloaded: bool = False
import threading as _threading
_legends_load_lock = _threading.Lock()


def _get_config() -> AppConfig:
    return load_config()


def _get_worlds(config: AppConfig) -> list[str]:
    """List available world subfolders, most recently active first."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return []

    def _newest_file_time(folder_name: str) -> float:
        """Get the newest file modification time inside a world folder."""
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


def _safe_watch_dir(config: AppConfig, world: str) -> Path | None:
    """Build a watch directory path and validate it stays within the event dir."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not world:
        return None
    candidate = (base / world).resolve()
    if not candidate.is_relative_to(base.resolve()):
        return None
    return candidate


def _get_active_world(config: AppConfig) -> str:
    global _active_world
    if _active_world:
        return _active_world
    worlds = _get_worlds(config)
    return worlds[0] if worlds else ""


def _empty_state():
    from df_storyteller.context.event_store import EventStore
    from df_storyteller.context.character_tracker import CharacterTracker
    from df_storyteller.context.world_lore import WorldLore
    empty_meta = {
        "fortress_name": "", "site_name": "", "civ_name": "", "biome": "",
        "year": 0, "season": "", "population": 0,
        "visitors": [], "animals": [], "buildings": [], "fortress_info": {},
    }
    return EventStore(), CharacterTracker(), WorldLore(), empty_meta


def _get_newest_snapshot_time(config: AppConfig) -> float:
    """Get modification time of the newest data file (snapshot or event).

    Checks both snapshot files and event JSON files so the cache
    invalidates when new events arrive, not just on new snapshots.
    """
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return 0
    world_dirs = [d for d in base.iterdir() if d.is_dir() and d.name != "processed"]
    if not world_dirs:
        return 0
    world_dir = max(world_dirs, key=lambda d: d.stat().st_mtime)
    # Check all JSON files (snapshots + events) for the newest modification
    all_json = list(world_dir.glob("*.json"))
    if not all_json:
        return 0
    return max(f.stat().st_mtime for f in all_json)


def _load_game_state_safe(config: AppConfig, skip_legends: bool = True):
    """Load game state with caching.

    Auto-invalidates when a new snapshot is detected.
    skip_legends=True (default) makes page loads fast by not parsing XML.
    Only set skip_legends=False for Lore tab and story generation.

    Uses separate caches for legends/no-legends so navigating between
    pages doesn't force an expensive XML reparse. A with_legends cache
    can serve no_legends requests (it's a superset).
    """
    import time
    global _cached_no_legends, _cached_with_legends
    global _cache_time_no_legends, _cache_time_with_legends

    now = time.time()
    newest = _get_newest_snapshot_time(config)

    # Try to serve from the with_legends cache first (superset of no_legends)
    if _cached_with_legends and (now - _cache_time_with_legends) < _CACHE_TTL:
        if newest <= _cache_time_with_legends:
            return _cached_with_legends

    # If legends not needed, try the no_legends cache
    if skip_legends and _cached_no_legends and (now - _cache_time_no_legends) < _CACHE_TTL:
        if newest <= _cache_time_no_legends:
            return _cached_no_legends

    # For legends loads, use a lock to prevent duplicate parsing
    # (e.g., background preload + lore page request racing)
    if not skip_legends:
        with _legends_load_lock:
            # Re-check cache inside lock — preload may have finished while we waited
            if _cached_with_legends and (now - _cache_time_with_legends) < _CACHE_TTL:
                if newest <= _cache_time_with_legends:
                    return _cached_with_legends
            try:
                active_world = _get_active_world(config)
                result = load_game_state(config, skip_legends=False, active_world=active_world)
                _cached_with_legends = result
                _cache_time_with_legends = time.time()
                return result
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Failed to load game state: %s", e)
                return _empty_state()

    try:
        active_world = _get_active_world(config)
        result = load_game_state(config, skip_legends=True, active_world=active_world)
        _cached_no_legends = result
        _cache_time_no_legends = now
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load game state: %s", e)
        return _empty_state()


def _invalidate_cache():
    """Clear the cache (call when world switches or settings change)."""
    global _cached_no_legends, _cached_with_legends
    global _cache_time_no_legends, _cache_time_with_legends
    global _map_image_cache
    _cached_no_legends = None
    _cached_with_legends = None
    _cache_time_no_legends = 0
    _cache_time_with_legends = 0
    _map_image_cache = None
    global _hotlink_cache
    _hotlink_cache = None


def _get_fortress_dir(config: AppConfig, metadata: dict | None = None) -> Path:
    """Get the per-fortress output directory for the active fortress."""
    from df_storyteller.context.loader import get_fortress_output_dir
    if metadata is None:
        _, _, _, metadata = _load_game_state_safe(config)
    return get_fortress_output_dir(config, metadata)


def _base_context(config: AppConfig, active_tab: str, metadata: dict | None = None) -> dict:
    """Common template context for all pages."""
    worlds = _get_worlds(config)
    active_world = _get_active_world(config)

    if metadata is None:
        _, _, _, metadata = _load_game_state_safe(config)

    # Count events across all world folders for the status bar
    event_dir_base = Path(config.paths.event_dir) if config.paths.event_dir else None
    event_count = 0
    if event_dir_base and event_dir_base.exists():
        for wd in event_dir_base.iterdir():
            if wd.is_dir() and wd.name != "processed":
                event_count += len([f for f in wd.glob("*.json") if not f.name.startswith("snapshot_")])

    # Last updated timestamp
    import time as _time
    last_updated = ""
    _latest_cache_time = max(_cache_time_no_legends, _cache_time_with_legends)
    if _latest_cache_time > 0:
        age = int(_time.time() - _latest_cache_time)
        if age < 60:
            last_updated = f"{age}s ago"
        elif age < 3600:
            last_updated = f"{age // 60}m ago"
        else:
            last_updated = f"{age // 3600}h ago"

    # Determine setup state for guidance
    has_config = bool(config.paths.df_install)
    has_data = bool(metadata.get("fortress_name"))
    has_llm = bool(config.llm.provider)

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


def _linkify_dwarf_names(text: str, dwarf_map: dict[str, int]) -> str:
    """Replace dwarf names in text with links to their character sheets.

    dwarf_map: {name_fragment: unit_id} — maps various name forms to unit IDs.
    Longest names are matched first to avoid partial matches.
    Only replaces names that aren't already inside an <a> tag.
    """
    if not dwarf_map:
        return text

    # Sort by length descending so longer names match first
    sorted_names = sorted(dwarf_map.keys(), key=len, reverse=True)

    for name in sorted_names:
        if name not in text:
            continue
        unit_id = dwarf_map[name]
        link = f'<a href="/dwarves/{unit_id}" class="dwarf-link">{name}</a>'
        # Only replace occurrences that aren't already inside a link
        # Split on existing <a...>...</a> tags, only replace in non-tag parts
        parts = re.split(r'(<a\b[^>]*>.*?</a>)', text)
        for i, part in enumerate(parts):
            if not part.startswith('<a '):
                parts[i] = part.replace(name, link)
        text = "".join(parts)

    return text


def _build_dwarf_name_map(character_tracker) -> dict[str, int]:
    """Build a map of all name variations to unit IDs for hotlinking.

    For a dwarf named 'Ezum Rabmebzuth "Glowoars", Miner':
    - Full name: 'Ezum Rabmebzuth "Glowoars", Miner'
    - Without profession: 'Ezum Rabmebzuth "Glowoars"'
    - First + last: 'Ezum Rabmebzuth'
    - Nickname: 'Glowoars'
    - First name: 'Ezum'
    """
    name_map: dict[str, int] = {}
    for dwarf, _ in character_tracker.ranked_characters():
        full = dwarf.name
        uid = dwarf.unit_id

        # Full name (may include profession suffix)
        name_map[full] = uid

        # Strip profession suffix (everything after last comma)
        if ", " in full:
            without_prof = full.rsplit(", ", 1)[0]
            name_map[without_prof] = uid

        # Extract parts: "FirstName LastName "Nickname""
        # or just "FirstName LastName"
        base = without_prof if ", " in full else full
        nickname_match = re.search(r'"([^"]+)"', base)
        if nickname_match:
            nickname = nickname_match.group(1)
            if len(nickname) > 2:
                name_map[nickname] = uid
            # Name without nickname
            without_nick = re.sub(r'\s*"[^"]*"', '', base).strip()
            if without_nick:
                name_map[without_nick] = uid
                # First name only (if at least 3 chars to avoid false matches)
                first = without_nick.split()[0]
                if len(first) >= 3:
                    name_map[first] = uid
        else:
            # No nickname — use first name
            parts = base.split()
            if parts and len(parts[0]) >= 3:
                name_map[parts[0]] = uid

    return name_map


def _markdown_to_html(text: str) -> str:
    """Basic markdown to HTML conversion for story text."""
    lines = text.split("\n")
    html_lines = []
    in_paragraph = False

    for line in lines:
        stripped = line.strip()

        # Headers from LLM output — render as styled subheadings, not full h2/h3
        if stripped.startswith("### "):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(f'<p class="story-heading">{stripped[4:]}</p>')
            continue
        if stripped.startswith("## "):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(f'<p class="story-heading">{stripped[3:]}</p>')
            continue
        if stripped.startswith("# "):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(f'<p class="story-heading story-title">{stripped[2:]}</p>')
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            html_lines.append("<hr>")
            continue

        # Empty line = paragraph break
        if not stripped:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            continue

        # Bold: **text**
        stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
        # Italic: *text*
        stripped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", stripped)

        if not in_paragraph:
            html_lines.append("<p>")
            in_paragraph = True

        html_lines.append(stripped + " ")

    if in_paragraph:
        html_lines.append("</p>")

    return "\n".join(html_lines)


def _parse_journal(config: AppConfig, metadata: dict | None = None) -> list[dict]:
    """Parse the fortress journal markdown into entries."""
    fortress_dir = _get_fortress_dir(config, metadata)
    journal_path = fortress_dir / "fortress_journal.md"
    if not journal_path.exists():
        return []

    text = journal_path.read_text(encoding="utf-8", errors="replace")
    entries = []

    # Split on the --- dividers and ## headers
    parts = re.split(r"\n---\n", text)
    for part in parts:
        part = part.strip()
        if not part or part.startswith("# Fortress Journal"):
            continue

        header = ""
        body = part
        header_match = re.match(r"##\s+([^\n]+)\n\n(.*)", part, re.DOTALL)
        if header_match:
            header = header_match.group(1)
            body = header_match.group(2)

        if body.strip():
            # Strip manual marker for display, but track it
            raw_body = body.strip()
            is_manual = raw_body.startswith("<!-- source:manual -->")
            if is_manual:
                raw_body = raw_body.replace("<!-- source:manual -->", "").strip()

            # Parse season/year from header for editing
            season_match = re.match(r"(\w+) of Year (\d+)", header)
            entry_season = season_match.group(1).lower() if season_match else ""
            entry_year = int(season_match.group(2)) if season_match else 0

            entries.append({
                "header": header,
                "text": _markdown_to_html(raw_body),
                "raw_text": raw_body,
                "season": entry_season,
                "year": entry_year,
                "is_manual": is_manual,
            })

    return entries


# ==================== Page Routes ====================


@app.get("/", response_class=HTMLResponse)
async def chronicle_page(request: Request):
    config = _get_config()
    _, character_tracker, _, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "chronicle", metadata)
    fortress_dir = _get_fortress_dir(config, metadata)
    entries = _parse_journal(config, metadata)

    # Show newest entries first
    entries.reverse()

    # Hotlink dwarf names in story text
    name_map = _build_dwarf_name_map(character_tracker)
    for entry in entries:
        entry["text"] = _linkify_dwarf_names(entry["text"], name_map)

    # Check if current season already has an entry
    from df_storyteller.output.journal import has_entry_for
    current_season = metadata.get("season", "")
    current_year = metadata.get("year", 0)
    already_written = has_entry_for(config, current_season, current_year, fortress_dir) if current_season and current_year else False

    # Load fortress-wide notes
    from df_storyteller.context.notes_store import load_all_notes
    all_notes = load_all_notes(config, fortress_dir)
    fortress_notes = [n for n in all_notes if n.target_type == "fortress"]

    return templates.TemplateResponse(request=request, name="chronicle.html", context={
        **ctx, "entries": entries, "dwarf_name_map": name_map,
        "current_season": current_season, "current_year": current_year,
        "already_written": already_written,
        "fortress_notes": fortress_notes,
    })


@app.get("/dwarves", response_class=HTMLResponse)
async def dwarves_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    ranked = character_tracker.ranked_characters()

    # Load highlights for badge display
    from df_storyteller.context.highlights_store import load_all_highlights
    fortress_dir = _get_fortress_dir(config, metadata)
    highlights_map = {h.unit_id: h.role.value for h in load_all_highlights(config, output_dir=fortress_dir)}

    dwarves = []
    for dwarf, score in ranked:
        notable_traits = ""
        if dwarf.personality and dwarf.personality.notable_facets:
            traits = [f.description for f in dwarf.personality.notable_facets[:3] if f.description]
            notable_traits = "; ".join(traits)

        dwarves.append({
            "unit_id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "age": dwarf.age,
            "noble_positions": dwarf.noble_positions,
            "notable_traits": notable_traits,
            "highlight_role": highlights_map.get(dwarf.unit_id, ""),
        })

    # Build visitors list from metadata
    visitors = []
    for v in metadata.get("visitors", []):
        name = v.get("name", "Unknown")
        hfid = v.get("hist_figure_id")
        visitors.append({
            "name": name,
            "profession": v.get("profession", ""),
            "race": v.get("race", "").replace("_", " ").title(),
            "age": v.get("age", 0),
            "role": v.get("role", "visitor"),
            "hfid": hfid if hfid and hfid > 0 else None,
        })

    return templates.TemplateResponse(request=request, name="dwarves.html", context={
        **ctx, "content_class": "content-wide", "dwarves": dwarves, "visitors": visitors,
    })


@app.get("/dwarves/relationships", response_class=HTMLResponse)
async def relationships_page(request: Request):
    """Fortress-wide relationship web visualization."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    return templates.TemplateResponse(request=request, name="relationships.html", context=ctx)


@app.get("/dwarves/religion", response_class=HTMLResponse)
async def religion_page(request: Request):
    """Fortress pantheon — deity worship overview."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    return templates.TemplateResponse(request=request, name="religion.html", context=ctx)


@app.get("/api/religion")
async def api_religion():
    """Return religion graph data as JSON — deities and their worshippers."""
    config = _get_config()
    # Load with legends to get deity sphere data
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ranked = character_tracker.ranked_characters()

    deities: dict[str, dict] = {}  # deity name -> {id, name, worshippers: []}
    dwarf_nodes = []

    for dwarf, score in ranked:
        dwarf_nodes.append({
            "id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
        })
        for rel in dwarf.relationships:
            if rel.relationship_type == "deity":
                deity_name = rel.target_name
                if deity_name not in deities:
                    deities[deity_name] = {
                        "id": f"deity_{rel.target_unit_id}",
                        "name": deity_name,
                        "worshippers": [],
                    }
                deities[deity_name]["worshippers"].append(dwarf.unit_id)

    # Build nodes and edges
    nodes = []
    edges = []

    # Look up deity spheres from legends data.
    # Legends uses dwarven-language names ("avuz", "inod") while the snapshot
    # has English translated names ("Avuz", "Inod the Defensive Sanctum").
    # Build lookup by all name words so "avuz" matches "Avuz" and
    # "inod" matches "Inod the Defensive Sanctum".
    _legend_deities: list[tuple[str, list[str]]] = []  # [(name, spheres)]
    if world_lore.is_loaded and world_lore._legends:
        for hf in world_lore._legends.historical_figures.values():
            if (hf.is_deity or hf.hf_type == "deity") and hf.spheres:
                _legend_deities.append((hf.name.lower(), hf.spheres))

    def _find_deity_spheres(deity_name: str) -> list[str]:
        dn = deity_name.lower()
        first_word = dn.split()[0] if dn else ""
        for legend_name, legend_spheres in _legend_deities:
            # Exact first word match (most reliable)
            legend_first = legend_name.split()[0] if legend_name else ""
            if first_word and legend_first == first_word:
                return legend_spheres
        for legend_name, legend_spheres in _legend_deities:
            # Full legend name appears in the snapshot deity name
            if legend_name and legend_name in dn:
                return legend_spheres
        return []

    # Deity nodes
    for deity in deities.values():
        spheres = _find_deity_spheres(deity["name"])
        nodes.append({
            "id": deity["id"],
            "name": deity["name"],
            "type": "deity",
            "worshipper_count": len(deity["worshippers"]),
            "spheres": spheres,
        })
        for dwarf_id in deity["worshippers"]:
            edges.append({
                "source": str(dwarf_id),
                "target": deity["id"],
                "type": "worship",
            })

    # Dwarf nodes
    for d in dwarf_nodes:
        # Only include dwarves that worship at least one deity
        has_worship = any(d["id"] in deity["worshippers"] for deity in deities.values())
        if has_worship:
            nodes.append({
                "id": str(d["id"]),
                "name": d["name"],
                "type": "dwarf",
                "profession": d["profession"],
                "is_alive": d["is_alive"],
            })

    return {"nodes": nodes, "edges": edges, "deity_count": len(deities)}


@app.get("/api/relationships")
async def api_relationships():
    """Return relationship graph data as JSON for the visualization."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ranked = character_tracker.ranked_characters()

    nodes = []
    edges = []
    dwarf_ids = {dwarf.unit_id for dwarf, _ in ranked}

    for dwarf, score in ranked:
        nodes.append({
            "id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
            "score": round(score, 1),
        })
        for rel in dwarf.relationships:
            if rel.target_unit_id in dwarf_ids:
                edges.append({
                    "source": dwarf.unit_id,
                    "target": rel.target_unit_id,
                    "type": rel.relationship_type,
                })

    # Infer sibling relationships from shared parents
    parent_to_children: dict[int, list[int]] = {}
    for dwarf, _ in ranked:
        for rel in dwarf.relationships:
            if rel.relationship_type in ("mother", "father") and rel.target_unit_id in dwarf_ids:
                parent_to_children.setdefault(rel.target_unit_id, []).append(dwarf.unit_id)
    for parent_id, children in parent_to_children.items():
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                edges.append({
                    "source": children[i],
                    "target": children[j],
                    "type": "sibling",
                })

    # Deduplicate symmetric edges — keep most specific type
    seen: set[tuple[int, int]] = set()
    unique_edges = []
    for edge in edges:
        pair = (min(edge["source"], edge["target"]), max(edge["source"], edge["target"]))
        if pair not in seen:
            seen.add(pair)
            unique_edges.append(edge)

    return {"nodes": nodes, "edges": unique_edges}


@app.get("/api/relationships/family")
async def api_relationships_family():
    """Return family tree data for fortress dwarves using legends hf_link data."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ranked = character_tracker.ranked_characters()

    if not world_lore.is_loaded or not world_lore._legends:
        return {"nodes": [], "edges": [], "error": "Legends data required for family trees"}

    legends = world_lore._legends
    nodes = []
    edges = []
    seen_edges: set[tuple[int, int, str]] = set()

    # Map unit_id -> hist_figure_id for fortress dwarves
    unit_to_hf: dict[int, int] = {}
    hf_to_unit: dict[int, int] = {}
    for dwarf, score in ranked:
        if dwarf.hist_figure_id and dwarf.hist_figure_id > 0:
            unit_to_hf[dwarf.unit_id] = dwarf.hist_figure_id
            hf_to_unit[dwarf.hist_figure_id] = dwarf.unit_id

    # Build nodes from fortress dwarves
    for dwarf, score in ranked:
        hfid = unit_to_hf.get(dwarf.unit_id)
        family = legends.get_hf_family(hfid) if hfid else {"parents": [], "children": [], "spouse": []}
        # Count family connections within the fortress
        fortress_family = sum(1 for p in family["parents"] if p in hf_to_unit) + \
                          sum(1 for c in family["children"] if c in hf_to_unit) + \
                          sum(1 for s in family["spouse"] if s in hf_to_unit)
        nodes.append({
            "id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
            "has_family": fortress_family > 0,
        })

        if not hfid:
            continue

        # Add family edges (only between fortress dwarves)
        for parent_hf in family["parents"]:
            if parent_hf in hf_to_unit:
                key = (min(dwarf.unit_id, hf_to_unit[parent_hf]), max(dwarf.unit_id, hf_to_unit[parent_hf]), "parent")
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"source": hf_to_unit[parent_hf], "target": dwarf.unit_id, "type": "parent"})

        for spouse_hf in family["spouse"]:
            if spouse_hf in hf_to_unit:
                key = (min(dwarf.unit_id, hf_to_unit[spouse_hf]), max(dwarf.unit_id, hf_to_unit[spouse_hf]), "spouse")
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"source": dwarf.unit_id, "target": hf_to_unit[spouse_hf], "type": "spouse"})

    return {"nodes": nodes, "edges": edges}


@app.get("/dwarves/{unit_id}", response_class=HTMLResponse)
async def dwarf_detail_page(request: Request, unit_id: int):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    dwarf = character_tracker.get_dwarf(unit_id)

    if not dwarf:
        return RedirectResponse("/dwarves")

    # Build template-friendly dwarf data
    stress_descs = {0: "ecstatic", 1: "happy", 2: "content", 3: "fine", 4: "stressed", 5: "very unhappy", 6: "breaking down"}

    personality_traits = []
    if dwarf.personality:
        for f in dwarf.personality.notable_facets:
            if f.description:
                personality_traits.append(f.description)

    beliefs = []
    if dwarf.personality:
        for b in dwarf.personality.notable_beliefs:
            if b.description:
                beliefs.append(b.description)

    goals = []
    if dwarf.personality:
        for g in dwarf.personality.goals:
            if g.description:
                goals.append(g.description)

    physical_attrs = []
    for attr, value in dwarf.physical_attributes.items():
        desc = _describe_physical_attr(attr, value)
        if desc:
            physical_attrs.append(desc)

    mental_attrs = []
    for attr, value in dwarf.mental_attributes.items():
        desc = _describe_mental_attr(attr, value)
        if desc:
            mental_attrs.append(desc)

    skills = []
    if dwarf.skills:
        # Sort by level descending, then experience descending
        all_skills = sorted(dwarf.skills, key=lambda s: (int(s.level) if str(s.level).isdigit() else 0, s.experience), reverse=True)
        for s in all_skills:
            level_num = int(s.level) if str(s.level).isdigit() else 0
            level_name = _skill_level_name(level_num)
            skill_name = _resolve_skill_name(s.name)
            skills.append({"name": skill_name, "level": level_name, "level_num": level_num})

    relationships = [
        {"type": r.relationship_type, "name": r.target_name}
        for r in dwarf.relationships
    ]

    # Load highlight for this dwarf
    from df_storyteller.context.highlights_store import get_highlight_for_dwarf
    fortress_dir = _get_fortress_dir(config, metadata)
    dwarf_highlight = get_highlight_for_dwarf(config, unit_id, output_dir=fortress_dir)

    dwarf_data = {
        "unit_id": dwarf.unit_id,
        "hist_figure_id": dwarf.hist_figure_id if dwarf.hist_figure_id > 0 else None,
        "name": dwarf.name,
        "profession": dwarf.profession,
        "age": dwarf.age,
        "noble_positions": dwarf.noble_positions,
        "military_squad": dwarf.military_squad,
        "stress_desc": stress_descs.get(dwarf.stress_category) if dwarf.stress_category not in (2, 3) else "",
        "personality_traits": personality_traits,
        "beliefs": beliefs,
        "goals": goals,
        "physical_attrs": physical_attrs,
        "mental_attrs": mental_attrs,
        "skills": skills,
        "relationships": relationships,
        "equipment": dwarf.equipment,
        "wounds": dwarf.wounds,
        "pets": dwarf.pets,
        "is_alive": dwarf.is_alive,
        "highlight_role": dwarf_highlight.role.value if dwarf_highlight else "",
    }

    # Load events for this dwarf
    from df_storyteller.context.context_builder import _format_event
    dwarf_events = event_store.events_for_unit(unit_id)
    dwarf_data["events"] = [
        {
            "season": e.season.value.title(),
            "year": e.game_year,
            "type": e.event_type.value.replace("_", " ").title(),
            "description": re.sub(r"^\[.*?\]\s*", "", _format_event(e)),
        }
        for e in reversed(dwarf_events[-20:])
    ]

    # Build timeline: all events grouped by (year, season) in chronological order
    _TIMELINE_ICONS = {
        "combat": "sword", "death": "skull", "mood": "star", "artifact": "gem",
        "birth": "baby", "migrant_arrived": "footsteps", "profession_change": "scroll",
        "noble_appointment": "crown", "stress_change": "heart", "military_change": "shield",
        "building": "hammer", "season_change": "calendar",
    }
    from collections import defaultdict as _defaultdict
    _timeline_grouped: dict[tuple[int, str], list[dict]] = _defaultdict(list)
    for e in dwarf_events:
        desc = re.sub(r"^\[.*?\]\s*", "", _format_event(e))
        desc = re.sub(r"^[A-Za-z_ ]+:\s", "", desc)
        if not desc.strip():
            continue
        _timeline_grouped[(e.game_year, e.season.value)].append({
            "type": e.event_type.value.replace("_", " ").title(),
            "icon": _TIMELINE_ICONS.get(e.event_type.value, "circle"),
            "description": desc,
        })
    dwarf_data["timeline_events"] = [
        {"year": year, "season": season.title(), "events": evts}
        for (year, season), evts in sorted(
            _timeline_grouped.items(),
            key=lambda x: (x[0][0], SEASON_ORDER_MAP.get(x[0][1], 0)),
        )
    ]

    # Combat highlights for this dwarf
    from df_storyteller.schema.events import EventType as ET
    combat_highlights = []
    for e in reversed(dwarf_events):
        if e.event_type != ET.COMBAT:
            continue
        d = e.data
        is_attacker = hasattr(d, "attacker") and d.attacker.unit_id == unit_id
        opponent = d.defender.name if is_attacker else d.attacker.name if hasattr(d, "attacker") else "Unknown"
        combat_highlights.append({
            "role": "attacker" if is_attacker else "defender",
            "opponent": opponent,
            "weapon": getattr(d, "weapon", ""),
            "blow_count": len(d.blows) if hasattr(d, "blows") else 0,
            "injuries": getattr(d, "injuries", []),
            "outcome": getattr(d, "outcome", ""),
            "is_lethal": getattr(d, "is_lethal", False),
            "season": e.season.value.title(),
            "year": e.game_year,
            "body_parts": list({b.body_part for b in d.blows if b.body_part}) if hasattr(d, "blows") else [],
        })
        if len(combat_highlights) >= 10:
            break
    dwarf_data["combat_highlights"] = combat_highlights

    # Load biography history (dated entries) with name hotlinks
    fortress_dir = _get_fortress_dir(config, metadata)
    from df_storyteller.stories.biography import load_biography_history
    bio_history = load_biography_history(config, dwarf.unit_id, fortress_dir)
    name_map = _build_dwarf_name_map(character_tracker)
    for entry in bio_history:
        if entry.get("text"):
            entry["text"] = _linkify_dwarf_names(
                entry["text"].replace("\n", "<br>"), name_map
            )
    dwarf_data["bio_entries"] = [e for e in bio_history if not e.get("is_diary")]
    dwarf_data["diary_entries"] = [e for e in bio_history if e.get("is_diary")]
    dwarf_data["has_eulogy"] = any(e.get("is_eulogy") for e in bio_history)

    # Load notes for this dwarf
    from df_storyteller.context.notes_store import get_notes_for_dwarf
    from df_storyteller.schema.notes import TAG_DESCRIPTIONS
    dwarf_notes = get_notes_for_dwarf(config, unit_id, fortress_dir)
    # Include resolved notes too for display
    from df_storyteller.context.notes_store import load_all_notes
    all_dwarf_notes = [
        n for n in load_all_notes(config, fortress_dir)
        if n.target_type == "dwarf" and n.target_id == unit_id
    ]

    return templates.TemplateResponse(request=request, name="dwarf_detail.html", context={
        **ctx, "dwarf": dwarf_data, "notes": all_dwarf_notes, "tag_descriptions": TAG_DESCRIPTIONS,
    })


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "events", metadata)

    from df_storyteller.context.context_builder import _format_event
    SEASON_ORDER = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
    events = []
    for event in event_store.recent_events(200):
        desc = _format_event(event)
        # Strip the [Season Year] prefix and type label — the UI shows those separately
        desc = re.sub(r"^\[.*?\]\s*", "", desc)
        desc = re.sub(r"^[A-Za-z_ ]+:\s", "", desc)
        # Skip empty, session markers, and gamelog announcements (duplicated by DFHack events)
        if not desc.strip():
            continue
        if "Loading Fortress" in desc or "Starting New Outpost" in desc or "STARTING NEW GAME" in desc:
            continue
        if event.event_type.value == "announcement":
            continue
        events.append({
            "type": event.event_type.value,
            "year": event.game_year,
            "season": event.season.value,
            "_sort": (event.game_year, SEASON_ORDER.get(event.season.value, 0), event.game_tick),
            "description": desc,
        })

    # Sort by year/season/tick descending (newest first), then remove sort key
    events.sort(key=lambda e: e["_sort"], reverse=True)
    events = events[:100]  # Limit after sorting
    for event in events:
        del event["_sort"]

    # Build detailed combat encounters, grouped into engagements
    # Consecutive combat events (close in tick) are grouped as a single battle/siege
    from df_storyteller.schema.events import EventType as ET

    def _build_encounter(event):
        d = event.data
        blows = []
        if hasattr(d, "blows"):
            for b in d.blows:
                blows.append({"action": b.action, "body_part": b.body_part, "weapon": b.weapon, "effect": b.effect})
        raw_lines = d.raw_text.split("\n") if hasattr(d, "raw_text") and d.raw_text else []
        return {
            "attacker": d.attacker.name if hasattr(d, "attacker") else "Unknown",
            "defender": d.defender.name if hasattr(d, "defender") else "Unknown",
            "weapon": getattr(d, "weapon", ""),
            "blows": blows,
            "raw_lines": raw_lines,
            "outcome": getattr(d, "outcome", ""),
            "is_lethal": getattr(d, "is_lethal", False),
            "season": event.season.value,
            "year": event.game_year,
            "tick": event.game_tick,
        }

    # Collect all combat events in chronological order
    all_combat = []
    for event in event_store.recent_events(200):
        if event.event_type == ET.COMBAT:
            all_combat.append(event)

    # Group consecutive combat events by tick proximity (within 500 ticks = ~same engagement)
    TICK_THRESHOLD = 500
    engagement_groups: list[list] = []
    current_group: list = []
    for event in all_combat:
        if current_group and abs(event.game_tick - current_group[-1].game_tick) > TICK_THRESHOLD:
            engagement_groups.append(current_group)
            current_group = []
        current_group.append(event)
    if current_group:
        engagement_groups.append(current_group)

    # Build combat_encounters: grouped engagements (newest first)
    combat_encounters = []
    for group in reversed(engagement_groups):
        fights = [_build_encounter(e) for e in group]
        if len(fights) == 1:
            # Solo fight — render as before
            combat_encounters.append(fights[0])
        else:
            # Multi-fight engagement — create a grouped entry
            participants = set()
            total_blows = 0
            any_lethal = False
            all_raw_lines = []
            for f in fights:
                participants.add(f["attacker"])
                participants.add(f["defender"])
                total_blows += len(f["blows"])
                if f["is_lethal"]:
                    any_lethal = True
                all_raw_lines.extend(f["raw_lines"])

            casualties = [f for f in fights if f["is_lethal"]]
            combat_encounters.append({
                "is_engagement": True,
                "fight_count": len(fights),
                "fights": fights,
                "participants": sorted(participants),
                "total_blows": total_blows,
                "is_lethal": any_lethal,
                "casualties": len(casualties),
                "season": fights[0]["season"],
                "year": fights[0]["year"],
                "raw_lines": all_raw_lines,
            })
        if len(combat_encounters) >= 20:
            break

    # Extract conversation lines from the gamelog for the chat log
    chat_lines = []
    gamelog_path = Path(config.paths.gamelog) if config.paths.gamelog else None
    if gamelog_path and gamelog_path.exists():
        from df_storyteller.context.loader import _read_current_session_gamelog
        # Conversation pattern: "Name, Profession: I talked to..."
        chat_pattern = re.compile(r'^(.+?),\s*(.+?):\s+(.+)$')
        for line in _read_current_session_gamelog(gamelog_path):
            m = chat_pattern.match(line)
            if m:
                name = m.group(1)
                profession = m.group(2)
                message = m.group(3)
                # Skip lines that are actually cancellation messages
                if message.startswith("cancels "):
                    continue
                chat_lines.append({
                    "name": name,
                    "profession": profession,
                    "message": message,
                })

    # Load saved battle reports — split into engagement reports (shown in section) and solo (shown inline)
    saved_battle_reports = []
    solo_reports_by_index: dict[int, dict] = {}
    try:
        fortress_dir = _get_fortress_dir(config, metadata)
        reports_path = fortress_dir / "battle_reports.json"
        if reports_path.exists():
            import json as _json
            all_reports = _json.loads(reports_path.read_text(encoding="utf-8", errors="replace"))
            for r in all_reports:
                if r.get("is_engagement"):
                    saved_battle_reports.append(r)
                else:
                    idx = r.get("encounter_index")
                    if idx is not None:
                        solo_reports_by_index[idx] = r
    except (ValueError, OSError):
        pass

    return templates.TemplateResponse(request=request, name="events.html", context={
        **ctx, "content_class": "content-wide", "events": events, "combat_encounters": combat_encounters, "chat_lines": chat_lines,
        "saved_battle_reports": saved_battle_reports, "solo_reports": solo_reports_by_index,
    })


@app.post("/api/chat/summarize")
async def api_summarize_chat(request: Request):
    """Use AI to summarize the fortress chat log."""
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)

    gamelog_path = Path(config.paths.gamelog) if config.paths.gamelog else None
    if not gamelog_path or not gamelog_path.exists():
        return StreamingResponse(iter(["No gamelog found."]), media_type="text/plain")

    from df_storyteller.context.loader import _read_current_session_gamelog
    chat_pattern = re.compile(r'^(.+?),\s*(.+?):\s+(.+)$')
    chat_text = ""
    for line in _read_current_session_gamelog(gamelog_path):
        m = chat_pattern.match(line)
        if m and not m.group(3).startswith("cancels "):
            chat_text += f"{m.group(1)}: {m.group(3)}\n"

    if not chat_text.strip():
        return StreamingResponse(iter(["No conversations found in the current session."]), media_type="text/plain")

    fortress_name = metadata.get("fortress_name", "the fortress")
    season = metadata.get("season", "").title()
    year = metadata.get("year", 0)

    from df_storyteller.stories.base import create_provider
    provider = create_provider(config)

    async def _stream():
        try:
            result = await provider.generate(
                system_prompt="You are a dwarven chronicler summarizing the social life of a fortress. Write in a warm, narrative tone befitting a fantasy chronicle. Focus on relationships, emotions, conflicts, and notable interactions.",
                user_prompt=f"""Summarize the social happenings in {fortress_name} during {season} of Year {year} based on these dwarf conversations and thoughts:

{chat_text}

Write 2-3 paragraphs summarizing the social mood, notable relationships, tensions, and daily life. Mention specific dwarves by name. Note any new friendships, family bonds, grievances, or emotional states that stand out.""",
                max_tokens=config.story.chat_summary_max_tokens,
                temperature=config.llm.temperature,
            )
            words = result.split(" ")
            for i, word in enumerate(words):
                yield word + (" " if i < len(words) - 1 else "")
                await asyncio.sleep(0.02)
        except Exception as e:
            logger.exception("Chat summary generation failed")
            yield f"Error: {e}" if str(e) else "Error: generation failed. Check Settings and try again."

    return StreamingResponse(_stream(), media_type="text/plain")


def _build_outcome_summary(group: list, title_to_dwarf: dict, ranked: list) -> str:
    """Build a specific outcome summary stating who died and who survived."""
    killed = []
    survived = []
    for event in group:
        d = event.data
        if getattr(d, "is_lethal", False):
            defender_name = d.defender.name if hasattr(d, "defender") else "Unknown"
            # Resolve to real name if it's a title
            real_dwarf = title_to_dwarf.get(defender_name.lower())
            if real_dwarf:
                defender_name = real_dwarf.name.split(",")[0].strip()
            killed.append(defender_name)

            attacker_name = d.attacker.name if hasattr(d, "attacker") else "Unknown"
            real_atk = title_to_dwarf.get(attacker_name.lower())
            if real_atk:
                attacker_name = real_atk.name.split(",")[0].strip()
            survived.append(attacker_name)
        else:
            for attr in ("attacker", "defender"):
                name = getattr(d, attr, None)
                if name and hasattr(name, "name"):
                    real = title_to_dwarf.get(name.name.lower())
                    resolved = real.name.split(",")[0].strip() if real else name.name
                    if resolved not in survived and resolved not in killed:
                        survived.append(resolved)

    parts = []
    if killed:
        parts.append(f"KILLED: {', '.join(set(killed))}")
    if survived:
        parts.append(f"SURVIVED: {', '.join(set(survived))}")
    if not killed:
        parts.append("No fatalities — all combatants survived.")
    return "\n".join(parts)


@app.post("/api/battle-report/{encounter_index}")
async def api_battle_report(encounter_index: int):
    """Generate a dramatic battle/siege report for a combat encounter or engagement."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)

    # Rebuild the same engagement groups as the events page
    from df_storyteller.schema.events import EventType as ET
    TICK_THRESHOLD = 500
    all_combat = [e for e in event_store.recent_events(200) if e.event_type == ET.COMBAT]

    engagement_groups: list[list] = []
    current_group: list = []
    for event in all_combat:
        if current_group and abs(event.game_tick - current_group[-1].game_tick) > TICK_THRESHOLD:
            engagement_groups.append(current_group)
            current_group = []
        current_group.append(event)
    if current_group:
        engagement_groups.append(current_group)

    # Reverse to match the template order (newest first)
    engagement_groups.reverse()

    if encounter_index >= len(engagement_groups):
        return StreamingResponse(iter(["Combat encounter not found."]), media_type="text/plain")

    group = engagement_groups[encounter_index]
    is_siege = len(group) > 1

    # Build combined combat text
    all_raw = []
    participants = set()
    any_lethal = False
    for event in group:
        d = event.data
        if hasattr(d, "raw_text") and d.raw_text:
            all_raw.append(d.raw_text)
        if hasattr(d, "attacker"):
            participants.add(d.attacker.name)
        if hasattr(d, "defender"):
            participants.add(d.defender.name)
        if getattr(d, "is_lethal", False):
            any_lethal = True

    combined_raw = "\n---\n".join(all_raw)
    season = group[0].season.value.title()
    year = group[0].game_year

    # Pick the author: combatant if alive, else best writer/social dwarf, else mysterious figure
    author_name = ""
    author_context = ""

    # Build a mapping of gamelog titles/professions to actual dwarf names
    # The gamelog uses titles like "militia commander" not actual names
    ranked = character_tracker.ranked_characters()
    name_mappings: list[str] = []
    title_to_dwarf: dict[str, object] = {}
    for dwarf, _ in ranked:
        short_name = dwarf.name.split(",")[0].strip()
        # Map profession to name
        if dwarf.profession:
            prof_lower = dwarf.profession.lower()
            title_to_dwarf[prof_lower] = dwarf
            name_mappings.append(f"'{dwarf.profession}' = {short_name}")
        # Map noble positions
        for pos in dwarf.noble_positions:
            title_to_dwarf[pos.lower()] = dwarf
            name_mappings.append(f"'{pos}' = {short_name}")
        # Map military squad role
        if dwarf.military_squad:
            title_to_dwarf[dwarf.military_squad.lower()] = dwarf

    # Check if any fortress dwarf was a combatant and survived
    combatant_author = None
    for p in participants:
        p_lower = p.lower()
        # Check against titles/professions
        if p_lower in title_to_dwarf:
            dwarf = title_to_dwarf[p_lower]
            if dwarf.is_alive:
                combatant_author = dwarf
                break
        # Check against actual names
        for dwarf, _ in ranked:
            if p_lower in dwarf.name.lower():
                if dwarf.is_alive:
                    combatant_author = dwarf
                    break
        if combatant_author:
            break

    if combatant_author:
        author_name = combatant_author.name.split(",")[0].strip()
        author_context = f"Written by {author_name}, who fought in this battle. Write from their FIRST-PERSON perspective ('I swung my axe...', 'I felt the impact...'). You ARE {author_name}."
    else:
        # Find best writer/social dwarf
        best_writer = None
        best_score = -1
        for dwarf, _ in ranked:
            if not dwarf.is_alive:
                continue
            for skill in dwarf.skills:
                if skill.name.lower() in ("writing", "prose", "poetry", "social awareness", "persuasion", "conversation"):
                    if skill.experience > best_score:
                        best_score = skill.experience
                        best_writer = dwarf

        if best_writer:
            author_name = best_writer.name.split(",")[0].strip()
            author_context = f"Written by {author_name}, the fortress chronicler. They didn't fight but recorded the battle from witness accounts."
        elif any(d.is_alive for d, _ in ranked):
            # Any living dwarf as fallback
            for dwarf, _ in ranked:
                if dwarf.is_alive:
                    author_name = dwarf.name.split(",")[0].strip()
                    author_context = f"Written by {author_name}, a witness to the battle."
                    break
        else:
            author_name = "A Mysterious Figure"
            author_context = "No survivors remain to tell this tale. Written by a mysterious figure — perhaps a ghost, a passing traveler, or the fortress itself remembering."

    fortress_dir = _get_fortress_dir(config, metadata)

    async def _stream() -> AsyncGenerator[str, None]:
        from df_storyteller.stories.base import create_provider
        from df_storyteller.stories.df_mechanics import DF_MECHANICS_COMPACT
        provider = create_provider(config)

        fortress_name = metadata.get("fortress_name", "the fortress")

        if is_siege:
            system_prompt = f"""You are writing a dramatic siege/battle report.
{author_context}
This was a major engagement with {len(group)} separate fights. Write a sweeping narrative
covering the full battle — the chaos, the individual duels, the turning points.
Reference actual weapons, injuries, and combatants from the data.
Keep it to 200-400 words. Sign off with the author's name at the end.
{DF_MECHANICS_COMPACT}"""
        else:
            system_prompt = f"""You are writing a dramatic battle report.
{author_context}
Write vivid, specific prose based on the actual blow-by-blow combat data provided.
Reference the actual weapons, body parts, injuries, and outcome from the fight.
The tone should be intense and gripping.
Keep it to 150-250 words. Sign off with the author's name at the end.
{DF_MECHANICS_COMPACT}"""

        name_map_text = ""
        if name_mappings:
            name_map_text = "\n## Name Key (the gamelog uses titles, these are the real names)\n" + "\n".join(name_mappings)

        user_prompt = f"""Write a {'siege report' if is_siege else 'battle report'} for {fortress_name}, {season} of Year {year}.

## Combatants
{', '.join(sorted(participants))}
{'This engagement involved ' + str(len(group)) + ' separate fights.' if is_siege else ''}
{name_map_text}

## Combat Details
{combined_raw}

## Result
{_build_outcome_summary(group, title_to_dwarf, ranked)}

IMPORTANT: Use the REAL NAMES from the Name Key above, not titles like "militia commander". Write a dramatic narrative using the actual combat details. Be ACCURATE about who died and who survived — do not invent casualties."""

        try:
            result = await provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=config.story.biography_max_tokens,
                temperature=0.85,
            )

            # Save the battle report persistently
            try:
                import json as _json
                reports_path = fortress_dir / "battle_reports.json"
                existing = []
                if reports_path.exists():
                    try:
                        existing = _json.loads(reports_path.read_text(encoding="utf-8", errors="replace"))
                    except (ValueError, OSError):
                        existing = []
                from datetime import datetime as _dt
                new_report = {
                    "text": result,
                    "author": author_name,
                    "year": year,
                    "season": season,
                    "participants": sorted(participants),
                    "fight_count": len(group),
                    "is_lethal": any_lethal,
                    "is_siege": is_siege,
                    "is_engagement": len(group) > 1,
                    "encounter_index": encounter_index,
                    "generated_at": _dt.now().isoformat(),
                }
                # Replace existing report for same encounter, or append
                replaced = False
                for i, r in enumerate(existing):
                    if r.get("encounter_index") == encounter_index:
                        existing[i] = new_report
                        replaced = True
                        break
                if not replaced:
                    existing.append(new_report)
                reports_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                logger.warning("Failed to save battle report to disk")

            words = result.split(" ")
            for i, word in enumerate(words):
                yield word + (" " if i < len(words) - 1 else "")
                await asyncio.sleep(0.02)
        except Exception as e:
            logger.exception("Battle report generation failed")
            yield f"Error: {e}" if str(e) else "Error: generation failed. Check Settings and try again."

    return StreamingResponse(_stream(), media_type="text/plain")


# ==================== Dashboard ====================


SEASON_ORDER_MAP = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    config = _get_config()
    event_store, character_tracker, _, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dashboard", metadata)

    from df_storyteller.schema.events import EventType as ET

    # Build time series data grouped by (year, season)
    def _season_sort_key(year: int, season: str) -> tuple[int, int]:
        return (year, SEASON_ORDER_MAP.get(season, 0))

    # Population from season_change events
    population_series: list[dict] = []
    for e in event_store.events_by_type(ET.SEASON_CHANGE):
        data = e.data
        pop = getattr(data, "population", 0) if not isinstance(data, dict) else data.get("population", 0)
        if pop > 0:
            population_series.append({
                "label": f"{e.season.value.title()} Y{e.game_year}",
                "value": pop,
                "_sort": _season_sort_key(e.game_year, e.season.value),
            })
    population_series.sort(key=lambda x: x["_sort"])
    for p in population_series:
        del p["_sort"]

    # Group events by season for deaths, combat, migration
    def _count_by_season(event_type: ET) -> list[dict]:
        from collections import Counter
        counts: Counter[tuple[int, str]] = Counter()
        for e in event_store.events_by_type(event_type):
            counts[(e.game_year, e.season.value)] += 1
        # Build sorted series with all seasons that have any events
        result = []
        for (year, season), count in sorted(counts.items(), key=lambda x: _season_sort_key(*x[0])):
            result.append({"label": f"{season.title()} Y{year}", "value": count})
        return result

    deaths_series = _count_by_season(ET.DEATH)
    combat_series = _count_by_season(ET.COMBAT)

    # Migration: combine MIGRANT_ARRIVED and MIGRATION_WAVE
    from collections import Counter
    migration_counts: Counter[tuple[int, str]] = Counter()
    for e in event_store.events_by_type(ET.MIGRANT_ARRIVED):
        migration_counts[(e.game_year, e.season.value)] += 1
    for e in event_store.events_by_type(ET.MIGRATION_WAVE):
        data = e.data
        count = data.get("count", 1) if isinstance(data, dict) else getattr(data, "count", 1)
        migration_counts[(e.game_year, e.season.value)] += count
    migration_series = [
        {"label": f"{s.title()} Y{y}", "value": c}
        for (y, s), c in sorted(migration_counts.items(), key=lambda x: _season_sort_key(*x[0]))
    ]

    # Milestones: first event of each notable type
    milestones: list[dict] = []
    milestone_types = {
        ET.DEATH: "First death",
        ET.ARTIFACT: "First artifact",
        ET.MOOD: "First strange mood",
        ET.COMBAT: "First combat",
    }
    for etype, label in milestone_types.items():
        events = event_store.events_by_type(etype)
        if events:
            first = min(events, key=lambda e: _season_sort_key(e.game_year, e.season.value))
            from df_storyteller.context.context_builder import _format_event
            desc = re.sub(r"^\[.*?\]\s*", "", _format_event(first))
            milestones.append({
                "label": label,
                "description": desc[:120],
                "season": first.season.value.title(),
                "year": first.game_year,
            })
    milestones.sort(key=lambda m: _season_sort_key(m["year"], m["season"].lower()))

    # Summary stats — use season_change events for fortress age (these are fortress-specific)
    season_years = [e.game_year for e in event_store.events_by_type(ET.SEASON_CHANGE) if e.game_year > 0]
    if season_years:
        years_active = max(season_years) - min(season_years) + 1
    else:
        years_active = 1 if metadata.get("year", 0) > 0 else 0

    dashboard = {
        "summary": {
            "population": metadata.get("population", 0),
            "years_active": years_active,
            "total_deaths": len(event_store.events_by_type(ET.DEATH)),
            "total_artifacts": len(event_store.events_by_type(ET.ARTIFACT)),
            "total_combats": len(event_store.events_by_type(ET.COMBAT)),
        },
        "population_series": population_series,
        "deaths_series": deaths_series,
        "combat_series": combat_series,
        "migration_series": migration_series,
        "milestones": milestones,
    }

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        **ctx, "content_class": "content-wide", "dashboard": dashboard,
    })


_TYPE_LABELS = {
    "migratinggroup": "migrating group",
    "nomadicgroup": "nomadic group",
    "merchantcompany": "merchant company",
    "outcast": "outcast group",
    "guild": "guild",
    "militia": "militia",
    "militaryunit": "military unit",
    "performancetroupe": "performance troupe",
    "sitegovernment": "site government",
    "religion": "religion",
}


def _build_sub_entities(legends: Any, civ: Any) -> list[str]:
    """Build a concise list of sub-entities for inline display."""
    data = _build_sub_entities_structured(legends, civ)
    result: list[str] = []
    for deity in data["deities"]:
        result.append(f'Worships {deity["name"]}' + (f' ({deity["spheres"]})' if deity["spheres"] else ''))
    for gt, count in data["group_counts"].items():
        result.append(f'{count} {gt}{"s" if count > 1 else ""}')
    for g in data["named_groups"]:
        result.append(g)
    return result


def _build_sub_entities_structured(legends: Any, civ: Any) -> dict:
    """Build structured sub-entity data for rich template rendering."""
    from collections import defaultdict, Counter

    child_ids = getattr(civ, '_child_ids', [])
    deity_groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "spheres": "", "deity_name": "", "deity_id": None})
    group_type_counts: Counter[str] = Counter()
    named_groups: list[str] = []
    guilds: list[dict] = []

    for child_id in child_ids:
        child_civ = legends.get_civilization(child_id)
        if not child_civ or not child_civ.name:
            continue
        child_type = getattr(child_civ, '_entity_type', '')
        if child_type in ('civilization', 'sitegovernment', ''):
            continue

        worship_id = getattr(child_civ, '_worship_id', None)
        profession = getattr(child_civ, '_profession', '')

        if child_type == 'religion' and worship_id:
            deity = legends.get_figure(worship_id)
            if deity:
                key = str(worship_id)
                deity_groups[key]["count"] += 1
                deity_groups[key]["deity_name"] = deity.name
                deity_groups[key]["deity_id"] = deity.hf_id
                deity_groups[key]["spheres"] = ', '.join(deity.spheres) if deity.spheres else ''
        elif child_type == 'guild':
            guilds.append({"name": child_civ.name, "profession": profession})
        elif child_type in ('nomadicgroup', 'migratinggroup', 'outcast', 'militaryunit'):
            type_label = _TYPE_LABELS.get(child_type, child_type)
            group_type_counts[type_label] += 1
        elif child_type == 'performancetroupe':
            group_type_counts["performance troupe"] += 1
        elif child_type == 'merchantcompany':
            group_type_counts["merchant company"] += 1
        else:
            type_label = _TYPE_LABELS.get(child_type, child_type.replace("_", " "))
            named_groups.append(f"{child_civ.name} ({type_label})")

    deities = sorted(deity_groups.values(), key=lambda x: x["count"], reverse=True)
    return {
        "deities": [{"name": d["deity_name"], "deity_id": d["deity_id"], "spheres": d["spheres"], "order_count": d["count"]} for d in deities],
        "guilds": guilds,
        "group_counts": dict(group_type_counts.most_common()),
        "named_groups": named_groups,
    }


@app.get("/lore", response_class=HTMLResponse)
async def lore_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)

    ctx = _base_context(config, "lore", metadata)

    civilizations = []
    wars = []
    figures = []
    beast_attacks: list[dict] = []
    site_conquests: list[dict] = []
    persecutions: list[dict] = []
    duels: list[dict] = []
    abductions: list[dict] = []
    thefts: list[dict] = []
    purges: list[dict] = []
    overthrown: list[dict] = []
    notable_deaths: list[dict] = []
    regions_data: list[dict] = []
    player_civ_data = None

    # Get player civ ID from metadata
    player_civ_id = metadata.get("fortress_info", {}).get("civ_id", -1)

    if world_lore.is_loaded and world_lore._legends:
        legends = world_lore._legends

        # Build entity type index for finding sub-entities
        entity_types: dict[int, str] = {}
        for eid, civ in legends.civilizations.items():
            entity_types[eid] = getattr(civ, '_entity_type', '')

        # Civilizations — show actual civilizations with their guilds, religions, etc.
        for eid, civ in legends.civilizations.items():
            etype = entity_types.get(eid, '')
            if etype and etype != 'civilization':
                continue
            if not civ.name:
                continue

            details_parts = []
            sites = [legends.get_site(sid) for sid in civ.sites if legends.get_site(sid)]
            if sites:
                site_names = [f"{s.name} ({s.site_type})" for s in sites[:5]]
                details_parts.append(f"Controls: {', '.join(site_names)}")
            war_count = len(legends.get_wars_involving(eid))
            if war_count:
                details_parts.append(f"Involved in {war_count} war{'s' if war_count != 1 else ''}")

            # Find sub-entities using child IDs from the XML hierarchy
            sub_data = _build_sub_entities_structured(legends, civ)
            sub_entities = _build_sub_entities(legends, civ)

            race_display = civ.race.replace('_', ' ').title() if civ.race else ''
            civilizations.append({
                "id": eid,
                "entity_type": "civilization",
                "name": civ.name,
                "race": race_display,
                "details": ". ".join(details_parts) if details_parts else "",
                "sub_entities": sub_entities,
                "org_data": sub_data,
            })

        # Wars — all of them
        for ec in legends.event_collections:
            if ec.get("type") == "war":
                details_parts = []
                for role, key in [("Aggressor", "aggressor_ent_id"), ("Defender", "defender_ent_id")]:
                    ids = ec.get(key, [])
                    if isinstance(ids, str):
                        ids = [ids]
                    for eid_str in ids:
                        try:
                            c = legends.get_civilization(int(eid_str))
                            if c:
                                details_parts.append(f"{role}: {c.name} ({c.race})" if c.race else f"{role}: {c.name}")
                        except (ValueError, TypeError):
                            pass
                year_range = ""
                sy = ec.get("start_year", "")
                ey = ec.get("end_year", "")
                if sy and ey and sy != ey:
                    year_range = f"Year {sy}–{ey}"
                elif sy:
                    year_range = f"Year {sy}"

                wars.append({
                    "id": ec.get("id", ""),
                    "entity_type": "war",
                    "name": ec.get("name", "Unknown conflict"),
                    "details": " vs ".join(details_parts) if details_parts else "",
                    "years": year_range,
                })

        # Battles — named conflicts with outcomes
        battles = []
        for battle in legends.battles:
            name = battle.get("name", "")
            outcome = battle.get("outcome", "")
            year = battle.get("start_year", "")

            # These fields can be strings or lists (multiple squads)
            def _first_str(val: Any) -> str:
                if isinstance(val, list):
                    return val[0] if val else ""
                return str(val) if val else ""

            atk_race = _first_str(battle.get("attacking_squad_race", "")).replace("_", " ").title()
            def_race = _first_str(battle.get("defending_squad_race", "")).replace("_", " ").title()
            atk_deaths = _first_str(battle.get("attacking_squad_deaths", "0"))
            def_deaths = _first_str(battle.get("defending_squad_deaths", "0"))

            details = ""
            if atk_race and def_race:
                details = f"{atk_race} vs {def_race}"
                if outcome:
                    outcome_str = outcome.replace("_", " ") if isinstance(outcome, str) else str(outcome)
                    details += f" — {outcome_str}"
                details += f" ({atk_deaths}/{def_deaths} casualties)"
            battles.append({"id": battle.get("id", ""), "entity_type": "battle", "name": name, "details": details, "year": year})

        # Beast attacks — resolve defender civ and count events
        beast_attacks = []
        for ba in legends.beast_attacks:
            name = ba.get("name", "Beast attack")
            year = ba.get("start_year", "")
            site_id = ba.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            defender_name = ""
            def_id = ba.get("defending_enid")
            if def_id and def_id != "-1":
                try:
                    c = legends.get_civilization(int(def_id))
                    if c:
                        defender_name = c.name
                except (ValueError, TypeError):
                    pass
            event_list = ba.get("event", [])
            n_events = len(event_list) if isinstance(event_list, list) else (1 if event_list else 0)
            parts = []
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            if defender_name:
                parts.append(f"against {defender_name}")
            if n_events:
                parts.append(f"{n_events} incidents")
            beast_attacks.append({"id": ba.get("id", ""), "name": name, "year": year,
                                  "site_name": site_name, "site_id": site_id,
                                  "defender_name": defender_name, "defender_id": def_id,
                                  "n_events": n_events})

        # Site conquests — resolve attacker/defender civs
        site_conquests = []
        for sc in legends.site_conquests:
            name = sc.get("name", "Site conquered")
            year = sc.get("start_year", "")
            site_id = sc.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = defender_name = ""
            atk_id = sc.get("attacking_enid")
            if atk_id and atk_id != "-1":
                try:
                    c = legends.get_civilization(int(atk_id))
                    if c:
                        attacker_name = c.name
                except (ValueError, TypeError):
                    pass
            def_id = sc.get("defending_enid")
            if def_id and def_id != "-1":
                try:
                    c = legends.get_civilization(int(def_id))
                    if c:
                        defender_name = c.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            if attacker_name and defender_name:
                parts.append(f"{attacker_name} conquered from {defender_name}")
            elif attacker_name:
                parts.append(f"by {attacker_name}")
            site_conquests.append({"id": sc.get("id", ""), "name": name, "year": year,
                                   "site_name": site_name, "site_id": site_id,
                                   "attacker_name": attacker_name, "attacker_id": atk_id,
                                   "defender_name": defender_name, "defender_id": def_id})

        # Persecutions — resolve target entity and site
        persecutions = []
        for persc in legends.persecutions:
            name = persc.get("name", "Persecution")
            year = persc.get("start_year", "")
            site_id = persc.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            target_name = ""
            target_id = persc.get("target_entity_id")
            if target_id and target_id != "-1":
                try:
                    c = legends.get_civilization(int(target_id))
                    if c:
                        target_name = c.name
                except (ValueError, TypeError):
                    pass
            event_list = persc.get("event", [])
            n_events = len(event_list) if isinstance(event_list, list) else (1 if event_list else 0)
            parts = []
            if year:
                parts.append(f"Year {year}")
            if target_name:
                parts.append(f"targeting {target_name}")
            if site_name:
                parts.append(f"at {site_name}")
            if n_events:
                parts.append(f"{n_events} incidents")
            persecutions.append({"id": persc.get("id", ""), "name": name, "year": year,
                                 "site_name": site_name, "site_id": site_id,
                                 "target_name": target_name, "target_id": target_id,
                                 "n_events": n_events})

        # Duels — resolve attacker/defender HFs
        duels = []
        for duel in legends.duels:
            year = duel.get("start_year", "")
            site_id = duel.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = defender_name = ""
            atk_id = duel.get("attacking_hfid")
            if atk_id:
                try:
                    h = legends.get_figure(int(atk_id))
                    if h:
                        attacker_name = h.name
                except (ValueError, TypeError):
                    pass
            def_id = duel.get("defending_hfid")
            if def_id:
                try:
                    h = legends.get_figure(int(def_id))
                    if h:
                        defender_name = h.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if attacker_name and defender_name:
                parts.append(f"{attacker_name} vs {defender_name}")
            if site_name:
                parts.append(f"at {site_name}")
            duels.append({"id": duel.get("id", ""), "name": duel.get("name", "Duel"), "year": year,
                          "atk_name": attacker_name, "atk_id": atk_id,
                          "def_name": defender_name, "def_id": def_id,
                          "site_name": site_name, "site_id": site_id})

        # Abductions — resolve attacker/defender civs
        abductions = []
        for abd in legends.abductions:
            year = abd.get("start_year", "")
            site_id = abd.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = defender_name = ""
            atk_id = abd.get("attacking_enid")
            if atk_id and atk_id != "-1":
                try:
                    c = legends.get_civilization(int(atk_id))
                    if c:
                        attacker_name = c.name
                except (ValueError, TypeError):
                    pass
            def_id = abd.get("defending_enid")
            if def_id and def_id != "-1":
                try:
                    c = legends.get_civilization(int(def_id))
                    if c:
                        defender_name = c.name
                except (ValueError, TypeError):
                    pass
            event_list = abd.get("event", [])
            n_events = len(event_list) if isinstance(event_list, list) else (1 if event_list else 0)
            parts = []
            if year:
                parts.append(f"Year {year}")
            if attacker_name:
                parts.append(f"by {attacker_name}")
            if defender_name:
                parts.append(f"from {defender_name}")
            if site_name:
                parts.append(f"at {site_name}")
            if n_events:
                parts.append(f"{n_events} incidents")
            abductions.append({"id": abd.get("id", ""), "name": abd.get("name", "Abduction"), "year": year,
                               "attacker_name": attacker_name, "attacker_id": atk_id,
                               "defender_name": defender_name, "defender_id": def_id,
                               "site_name": site_name, "site_id": site_id, "n_events": n_events})

        # Thefts — resolve attacker/defender civs
        thefts = []
        for theft in legends.thefts:
            year = theft.get("start_year", "")
            site_id = theft.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = ""
            atk_id = theft.get("attacking_enid")
            if atk_id and atk_id != "-1":
                try:
                    c = legends.get_civilization(int(atk_id))
                    if c:
                        attacker_name = c.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if attacker_name:
                parts.append(f"by {attacker_name}")
            if site_name:
                parts.append(f"at {site_name}")
            thefts.append({"id": theft.get("id", ""), "name": theft.get("name", "Theft"), "year": year,
                           "attacker_name": attacker_name, "attacker_id": atk_id,
                           "site_name": site_name, "site_id": site_id})

        # Purges — resolve site, show adjective (e.g. "Vampire")
        purges = []
        for purge in legends.purges:
            year = purge.get("start_year", "")
            site_id = purge.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            adjective = purge.get("adjective", "")
            parts = []
            if adjective:
                parts.append(f"{adjective} purge")
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            purges.append({"id": purge.get("id", ""), "name": purge.get("name", "Purge"), "year": year,
                           "adjective": adjective, "site_name": site_name, "site_id": site_id})

        # Entity overthrown
        overthrown = []
        for ov in legends.entity_overthrown:
            year = ov.get("start_year", "")
            site_id = ov.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            overthrown.append({"id": ov.get("id", ""), "name": ov.get("name", "Coup"), "year": year,
                               "site_name": site_name, "site_id": site_id})

        # Notable deaths (named victims with named slayers)
        for death in legends.notable_deaths:
            victim_id = death.get("hfid")
            slayer_id = death.get("slayer_hfid")
            victim_name = slayer_name = ""
            if victim_id:
                try:
                    v = legends.get_figure(int(victim_id))
                    if v:
                        victim_name = v.name
                except (ValueError, TypeError):
                    pass
            if slayer_id:
                try:
                    s = legends.get_figure(int(slayer_id))
                    if s:
                        slayer_name = s.name
                except (ValueError, TypeError):
                    pass
            if victim_name:
                year = death.get("year", "")
                details = f"slain by {slayer_name}" if slayer_name else "died"
                if year:
                    details += f" in year {year}"
                notable_deaths.append({
                    "name": victim_name,
                    "details": details,
                    "id": victim_id,
                    "entity_type": "figure",
                })

        # Regions
        for region in legends.regions:
            name = region.get("name", "")
            rtype = region.get("type", "").replace("_", " ").title()
            if name:
                regions_data.append({"name": name, "details": rtype})

        # Historical eras
        eras = []
        for era in legends.historical_eras:
            eras.append({
                "name": era.get("name", ""),
                "start_year": era.get("start_year", ""),
            })

        # Historical figures — show notable ones ranked by event involvement
        # Uses precomputed index from build_indexes()
        ranked_hfs = sorted(
            legends.historical_figures.items(),
            key=lambda x: legends.get_hf_event_count(x[0]),
            reverse=True,
        )[:500]

        for hfid, hf in ranked_hfs:
            if not hf.name:
                continue
            details_parts = []
            race = hf.race.replace('_', ' ').title() if hf.race else ''
            if hf.birth_year and hf.birth_year > 0:
                if hf.death_year and hf.death_year > 0:
                    details_parts.append(f"Born {hf.birth_year}, died {hf.death_year}")
                else:
                    details_parts.append(f"Born {hf.birth_year}")
            evt_count = legends.get_hf_event_count(hfid)
            if evt_count > 0:
                details_parts.append(f"{evt_count} historical events")
            # Check if they have an assumed identity
            for ident in legends.identities:
                if ident.get("histfig_id") == str(hfid):
                    details_parts.append(f"known to use aliases")
                    break
            figures.append({
                "id": hfid,
                "entity_type": "figure",
                "name": hf.name,
                "race": race,
                "description": " | ".join(details_parts) if details_parts else "",
            })

    # Build extended lore sections from legends_plus data
    artifacts = []
    written_works = []
    relationships = []
    identities = []
    geography = []

    if world_lore.is_loaded and world_lore._legends:
        legends = world_lore._legends

        # Artifacts — deduplicate by name, only show named ones
        seen_artifact_names: set[str] = set()
        for aid, art in legends.artifacts.items():
            if not art.name or art.name in seen_artifact_names:
                continue
            seen_artifact_names.add(art.name)
            details_parts = []
            if art.item_type:
                details_parts.append(art.item_type.replace("_", " "))
            if art.material:
                details_parts.append(art.material)
            if art.creator_hf_id:
                holder = legends.get_figure(art.creator_hf_id)
                if holder:
                    details_parts.append(f"held by {holder.name}")
            artifacts.append({
                "id": aid,
                "entity_type": "artifact",
                "name": art.name,
                "details": " — ".join(details_parts) if details_parts else "",
            })

        # Written works (books, poems, etc.)
        for wc in legends.written_contents:
            title = wc.get("title", "Untitled")
            wc_type = wc.get("type", "").replace("_", " ").title() if wc.get("type") else ""
            # Style may have ":N" suffix (e.g. "meandering:1") — strip it
            raw_style = wc.get("style", "")
            style = raw_style.split(":")[0].strip().title() if raw_style else ""
            author_id = wc.get("author")
            author_name = ""
            if author_id:
                try:
                    author = legends.get_figure(int(author_id))
                    if author:
                        author_name = author.name
                except (ValueError, TypeError):
                    pass
            details_parts = []
            if wc_type:
                details_parts.append(wc_type)
            if style:
                details_parts.append(f"style: {style}")
            if author_name:
                details_parts.append(f"by {author_name}")
            written_works.append({
                "id": wc.get("id", ""),
                "entity_type": "written_work",
                "title": title,
                "details": " — ".join(details_parts) if details_parts else "",
            })

        # Relationships (friendships, rivalries, romances)
        # Count all relationship types but only resolve names for display limit
        # Readable relationship type labels
        _rel_type_labels = {
            "lover": "Lover", "former_lover": "Former Lover",
            "childhood_friend": "Childhood Friend", "war_buddy": "War Buddy",
            "artistic_buddy": "Artistic Companion", "scholar_buddy": "Scholar Companion",
            "athlete_buddy": "Athletic Companion", "lieutenant": "Lieutenant",
            "jealous_obsession": "Jealous Obsession",
            "jealous_relationship_grudge": "Jealous Grudge",
            "religious_persecution_grudge": "Religious Grudge",
            "persecution_grudge": "Persecution Grudge",
            "supernatural_grudge": "Supernatural Grudge",
            "grudge": "Grudge", "business_rival": "Business Rival",
            "athletic_rival": "Athletic Rival",
        }

        rel_counts: dict[str, int] = {}
        for rel in legends.relationships:
            rtype = rel.get("relationship", "unknown")
            label = _rel_type_labels.get(rtype, rtype.replace("_", " ").title())
            rel_counts[label] = rel_counts.get(label, 0) + 1

        # Show a diverse sample — pick up to 5 per type, prioritize interesting types
        RELATIONSHIP_DISPLAY_LIMIT = 30
        _interesting_types = {"grudge", "war_buddy", "lieutenant", "jealous_obsession",
                              "religious_persecution_grudge", "supernatural_grudge",
                              "business_rival", "athletic_rival", "persecution_grudge",
                              "jealous_relationship_grudge", "scholar_buddy", "artistic_buddy",
                              "athlete_buddy", "childhood_friend", "former_lover", "lover"}
        type_shown: dict[str, int] = {}
        # First pass: interesting types
        for rel in legends.relationships:
            if len(relationships) >= RELATIONSHIP_DISPLAY_LIMIT:
                break
            rtype = rel.get("relationship", "")
            if rtype not in _interesting_types:
                continue
            if type_shown.get(rtype, 0) >= 5:
                continue
            source_id = rel.get("source_hf")
            target_id = rel.get("target_hf")
            year = rel.get("year", "")
            source_name = target_name = ""
            try:
                if source_id:
                    s = legends.get_figure(int(source_id))
                    if s: source_name = s.name
                if target_id:
                    t = legends.get_figure(int(target_id))
                    if t: target_name = t.name
            except (ValueError, TypeError):
                pass
            if source_name and target_name:
                label = _rel_type_labels.get(rtype, rtype.replace("_", " ").title())
                relationships.append({
                    "id": source_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "entity_type": "figure",
                    "description": f"{source_name} — {label} — {target_name}",
                    "year": year,
                })
                type_shown[rtype] = type_shown.get(rtype, 0) + 1

        # Identities (vampires, spies, assumed identities)
        for ident in legends.identities:
            hf_id = ident.get("histfig_id")
            name = ident.get("name", "")
            hf_name = ""
            if hf_id:
                try:
                    hf = legends.get_figure(int(hf_id))
                    if hf: hf_name = hf.name
                except (ValueError, TypeError):
                    pass
            if hf_name and name:
                identities.append({
                    "id": hf_id,
                    "entity_type": "figure",
                    "real_name": hf_name,
                    "assumed_name": name,
                })

        # Geography
        for peak in legends.mountain_peaks:
            name = peak.get("name", "")
            is_volcano = peak.get("is_volcano", "")
            height = peak.get("height", "")
            details = "Volcano" if is_volcano == "1" else "Mountain"
            if height:
                details += f", height {height}"
            geography.append({"id": peak.get("id", ""), "entity_type": "geography", "name": name, "type": "peak", "details": details})

        for land in legends.landmasses:
            geography.append({"id": land.get("id", ""), "entity_type": "geography", "name": land.get("name", ""), "type": "landmass", "details": "Landmass"})

        for river in legends.rivers:
            geography.append({"name": river.get("name", ""), "type": "river", "details": "River"})

        for wc in legends.world_constructions:
            geography.append({
                "name": wc.get("name", ""),
                "type": "construction",
                "details": wc.get("type", "Construction"),
            })

    # Build player's civilization summary with its own figures and artifacts
    if world_lore.is_loaded and world_lore._legends and player_civ_id >= 0:
        legends = world_lore._legends
        pciv = legends.get_civilization(player_civ_id)
        if pciv:
            # Figures belonging to player's civ
            pciv_figures = []
            for hfid, hf in legends.historical_figures.items():
                if hf.associated_civ_id == player_civ_id and hf.name:
                    details = ""
                    if hf.birth_year and hf.birth_year > 0:
                        details = f"Born {hf.birth_year}"
                        if hf.death_year and hf.death_year > 0:
                            details += f", died {hf.death_year}"
                    race = hf.race.replace('_', ' ').title() if hf.race else ''
                    pciv_figures.append({"name": hf.name, "hf_id": hfid, "race": race, "description": details})

            # Artifacts held by player civ figures
            pciv_artifacts = []
            pciv_hf_ids = {hfid for hfid, hf in legends.historical_figures.items() if hf.associated_civ_id == player_civ_id}
            seen_names: set[str] = set()
            for aid, art in legends.artifacts.items():
                if art.creator_hf_id in pciv_hf_ids and art.name and art.name not in seen_names:
                    seen_names.add(art.name)
                    details_parts = []
                    if art.item_type:
                        details_parts.append(art.item_type.replace("_", " "))
                    if art.material:
                        details_parts.append(art.material)
                    pciv_artifacts.append({"name": art.name, "artifact_id": aid, "details": " — ".join(details_parts)})

            race_display = pciv.race.replace('_', ' ').title() if pciv.race else ''
            sub_ents = _build_sub_entities(legends, pciv)
            sub_data = _build_sub_entities_structured(legends, pciv)

            player_civ_data = {
                "id": player_civ_id,
                "name": pciv.name,
                "race": race_display,
                "details": "",
                "sub_entities": sub_ents,
                "org_data": sub_data,
                "figures": pciv_figures[:20],
                "artifacts": pciv_artifacts[:20],
            }

    # Apply sensible limits to "other" sections (search reveals all)
    # Load saved sagas
    saved_sagas = []
    try:
        fortress_dir = _get_fortress_dir(config, metadata)
        saga_path = fortress_dir / "saga.json"
        if saga_path.exists():
            import json as _json
            saved_sagas = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        pass

    return templates.TemplateResponse(request=request, name="lore.html", context={
        **ctx,
        "content_class": "content-wide",
        "lore_loaded": world_lore.is_loaded,
        "saved_sagas": saved_sagas,
        "player_civ": player_civ_data,
        "eras": eras if world_lore.is_loaded and world_lore._legends else [],
        "civilizations": civilizations[:500],
        "wars": wars[:500],
        "battles": battles[:500],
        "figures": figures[:500],
        "artifacts": artifacts[:500],
        "written_works": written_works[:500],
        "relationships": relationships[:500],
        "relationship_counts": rel_counts if world_lore.is_loaded and world_lore._legends else {},
        "identities": identities,
        "geography": geography[:500],
        "poetic_forms": world_lore._legends.poetic_forms if world_lore.is_loaded and world_lore._legends else [],
        "musical_forms": world_lore._legends.musical_forms if world_lore.is_loaded and world_lore._legends else [],
        "dance_forms": world_lore._legends.dance_forms if world_lore.is_loaded and world_lore._legends else [],
        "beast_attacks": beast_attacks[:500],
        "site_conquests": site_conquests[:500],
        "persecutions": persecutions[:500],
        "duels": duels[:500],
        "abductions": abductions[:500],
        "thefts": thefts[:500],
        "purges": purges[:500],
        "overthrown": overthrown[:500],
        "notable_deaths": notable_deaths[:500],
        "regions_data": regions_data[:500],
        # True total counts for section headers
        "total_counts": {
            "civilizations": len(civilizations),
            "wars": len(wars),
            "battles": len(battles),
            "figures": sum(1 for hf in legends.historical_figures.values() if hf.name),
            "artifacts": len(artifacts),
            "written_works": len(written_works),
            "relationships": len(relationships),
            "beast_attacks": len(beast_attacks),
            "site_conquests": len(site_conquests),
            "persecutions": len(persecutions),
            "duels": len(duels),
            "abductions": len(abductions),
            "thefts": len(thefts),
            "purges": len(purges),
            "overthrown": len(overthrown),
            "notable_deaths": len(notable_deaths),
            "regions_data": len(regions_data),
            "geography": len(geography),
        },
    })


# ==================== Lore Detail Pages ====================


def _build_figure_sidebar(legends: Any, hf: Any, hf_id: int, kills: list[dict], raw_events: list[dict]) -> dict:
    """Build sidebar data for a figure detail page using actual relationships and events."""
    related: dict[int, dict] = {}  # hf_id -> {name, hf_id, reason, priority}

    def _add(fid: int, reason: str, priority: int) -> None:
        if fid == hf_id:
            return
        f = legends.get_figure(fid)
        if not f or not f.name:
            return
        if fid not in related or related[fid]["priority"] < priority:
            related[fid] = {"name": f.name, "hf_id": f.hf_id, "reason": reason, "priority": priority}

    # 1. Family (highest priority)
    family = legends.get_hf_family(hf_id)
    for pid in family["parents"]:
        _add(pid, "parent", 10)
    for cid in family["children"]:
        _add(cid, "child", 10)
    for sid in family["spouse"]:
        _add(sid, "spouse", 10)
    # Siblings via shared parents
    for pid in family["parents"]:
        p_family = legends.get_hf_family(pid)
        for sib_id in p_family["children"]:
            _add(sib_id, "sibling", 9)

    # 2. Relationships (friends, rivals, lovers, etc.)
    hfid_str = str(hf_id)
    for rel in legends.get_hf_relationships(hf_id):
        rtype = rel.get("relationship", "")
        if rel.get("source_hf") == hfid_str:
            other_id = rel.get("target_hf")
        else:
            other_id = rel.get("source_hf")
        if other_id:
            try:
                priority = 8 if rtype in ("grudge", "jealous_obsession", "war_buddy") else 7
                _add(int(other_id), rtype.replace("_", " "), priority)
            except (ValueError, TypeError):
                pass

    # 3. Kill victims and slayer (high priority — direct interaction)
    for kill in kills:
        _add(kill["hf_id"], "killed by this figure", 9)
    # Check if this figure was killed by someone
    for evt in raw_events:
        if evt.get("type") == "hf died" and evt.get("hfid") == hfid_str and evt.get("slayer_hfid"):
            try:
                _add(int(evt["slayer_hfid"]), "killed this figure", 9)
            except (ValueError, TypeError):
                pass

    # 4. Vague relationships (acquaintance, war buddy, etc.)
    for vr in hf.vague_relationships:
        vr_hfid = vr.get("hfid")
        if vr_hfid:
            vr_type = vr.get("type", "acquaintance")
            _add(vr_hfid, vr_type, 4)

    # 5. Figures involved in shared events (battles, confrontations)
    for evt in raw_events:
        etype = evt.get("type", "")
        if etype == "hf simple battle event":
            for key in ("group_1_hfid", "group_2_hfid"):
                other = evt.get(key)
                if other and other != hfid_str:
                    try:
                        _add(int(other), "fought in battle", 5)
                    except (ValueError, TypeError):
                        pass
        elif etype == "hf wounded":
            for key in ("woundee_hfid", "wounder_hfid"):
                other = evt.get(key)
                if other and other != hfid_str:
                    try:
                        _add(int(other), "combat wound", 6)
                    except (ValueError, TypeError):
                        pass
        elif etype == "hf abducted":
            for key in ("target_hfid", "snatcher_hfid"):
                other = evt.get(key)
                if other and other != hfid_str:
                    try:
                        _add(int(other), "abduction", 6)
                    except (ValueError, TypeError):
                        pass

    # Sort by priority descending, take top 20
    sorted_related = sorted(related.values(), key=lambda r: r["priority"], reverse=True)[:20]

    # Build sidebar sites from figure's civ
    sidebar_sites: list[dict] = []
    if hf.associated_civ_id:
        for s in legends.sites.values():
            if s.owner_civ_id == hf.associated_civ_id and s.name:
                sidebar_sites.append({"name": s.name, "site_id": s.site_id})
                if len(sidebar_sites) >= 10:
                    break

    # Build sidebar civs
    sidebar_civs: list[dict] = []
    if hf.associated_civ_id:
        civ = legends.get_civilization(hf.associated_civ_id)
        if civ:
            sidebar_civs.append({"name": civ.name, "entity_id": civ.entity_id})

    # Build sidebar wars from civ
    sidebar_wars: list[dict] = []
    if hf.associated_civ_id:
        for war in legends.get_wars_involving(hf.associated_civ_id)[:8]:
            sidebar_wars.append({"name": war.get("name", "?"), "id": war.get("id", "")})

    return {
        "sidebar_figures": sorted_related[:10],
        "sidebar_civs": sidebar_civs,
        "sidebar_sites": sidebar_sites[:5],
        "sidebar_wars": sidebar_wars[:5],
        "sidebar_artifacts": [{"name": a.name, "artifact_id": a.artifact_id}
                              for a in legends.artifacts.values()
                              if a.creator_hf_id == hf_id and a.name][:5],
        "sidebar_events": [],
    }


def _build_figure_context(legends: Any, hf_id: int) -> dict | None:
    """Build template context for a historical figure detail page."""
    from collections import Counter
    from df_storyteller.context.event_renderer import describe_event_linked as describe_event

    hf = legends.get_figure(hf_id)
    if not hf:
        return None

    figure = {
        "name": hf.name,
        "race": hf.race.replace("_", " ").title() if hf.race else "",
        "caste": hf.caste.replace("_", " ").title() if hf.caste else "",
        "hf_type": hf.hf_type.replace("_", " ").title() if hf.hf_type else "",
        "birth_year": hf.birth_year if hf.birth_year and hf.birth_year > 0 else None,
        "death_year": hf.death_year if hf.death_year and hf.death_year > 0 else None,
        "death_cause": "",
        "death_slayer": "",
        "death_slayer_id": None,
        "spheres": hf.spheres,
        "is_deity": hf.is_deity,
        "hf_id": hf.hf_id,
    }

    # Death details
    if hf.death_year and hf.death_year > 0:
        hfid_str_death = str(hf_id)
        for evt in legends.get_hf_events(hf_id):
            if evt.get("type") == "hf died" and evt.get("hfid") == hfid_str_death:
                cause = evt.get("cause", "").replace("_", " ")
                if cause:
                    figure["death_cause"] = cause
                slayer_hfid = evt.get("slayer_hfid")
                if slayer_hfid and slayer_hfid != "-1":
                    slayer = legends.get_figure(int(slayer_hfid))
                    if slayer:
                        figure["death_slayer"] = slayer.name
                        figure["death_slayer_id"] = slayer.hf_id
                elif evt.get("slayer_race"):
                    race = evt["slayer_race"].replace("_", " ").title()
                    caste = evt.get("slayer_caste", "").replace("_", " ").lower()
                    figure["death_slayer"] = f"a {caste} {race}".strip() if caste and caste != "default" else f"a {race}"
                break

    # Civilization
    civ_name = civ_id = None
    if hf.associated_civ_id:
        civ = legends.get_civilization(hf.associated_civ_id)
        if civ:
            civ_name = civ.name
            civ_id = civ.entity_id

    # Relationships
    hfid_str = str(hf_id)
    relationships = []
    for rel in legends.get_hf_relationships(hf_id):
        if rel.get("source_hf") == hfid_str:
            other = legends.get_figure(int(rel.get("target_hf", 0)))
            if other:
                relationships.append({"type": rel.get("relationship", "?"), "other_name": other.name, "other_id": other.hf_id})
        elif rel.get("target_hf") == hfid_str:
            other = legends.get_figure(int(rel.get("source_hf", 0)))
            if other:
                relationships.append({"type": rel.get("relationship", "?"), "other_name": other.name, "other_id": other.hf_id})

    # Events, kills, notable events summary
    raw_events = legends.get_hf_events(hf_id)
    evt_types: Counter[str] = Counter()
    kills: list[dict] = []
    for evt in raw_events:
        evt_types[evt.get("type", "unknown")] += 1
        if evt.get("type") == "hf died" and evt.get("slayer_hfid") == hfid_str:
            victim = legends.get_figure(int(evt.get("hfid", 0))) if evt.get("hfid") else None
            if victim:
                kills.append({"name": victim.name, "race": victim.race.replace("_", " ").title() if victim.race else "", "hf_id": victim.hf_id})

    readable_map = {
        "hf died": "kills", "hf simple battle event": "battles",
        "hf attacked site": "site attacks", "artifact created": "artifacts created",
        "creature devoured": "devoured victims", "hf wounded": "wounds inflicted",
        "hf confronted": "confrontations", "assume identity": "assumed identities",
    }
    summary_parts = []
    for et, count in evt_types.most_common(10):
        if et in readable_map:
            summary_parts.append(f"{count} {readable_map[et]}")
        if len(summary_parts) >= 5:
            break

    # Artifacts created by this figure
    artifacts = []
    for aid, art in legends.artifacts.items():
        if art.creator_hf_id == hf_id and art.name:
            artifacts.append({"name": art.name, "artifact_id": art.artifact_id})

    # Entity positions held
    entity_positions = []
    for link in hf.entity_links:
        link_type = link.get("type", "").replace("_", " ")
        ent_id = link.get("entity_id")
        ent_name = ""
        if ent_id:
            ent = legends.get_civilization(ent_id)
            if ent:
                ent_name = ent.name
        if link_type and ent_name:
            entity_positions.append(f"{link_type} of {ent_name}")
        elif link_type:
            entity_positions.append(link_type)

    # Skills (format nicely)
    # Convert total_ip to approximate skill level
    _IP_THRESHOLDS = [0, 500, 1100, 1800, 2600, 3500, 4600, 5800, 7200, 8800, 10600, 12600, 14900, 17400, 20200, 23300]
    def _ip_to_level(ip: int) -> int:
        for lvl in range(len(_IP_THRESHOLDS) - 1, -1, -1):
            if ip >= _IP_THRESHOLDS[lvl]:
                return lvl
        return 0

    skill_strs = []
    for sk in sorted(hf.skills, key=lambda s: s.get("total_ip", 0), reverse=True)[:15]:
        skill_name = sk.get("skill", "").replace("_", " ").title()
        if skill_name:
            ip = sk.get("total_ip", 0)
            level_num = _ip_to_level(ip)
            level_name = _skill_level_name(level_num)
            skill_strs.append({"name": skill_name, "level": level_name, "level_num": level_num})

    # Active interactions (curses)
    interactions = [ai.replace("_", " ").title() for ai in hf.active_interactions]

    # Journey pets
    pets = [p.replace("_", " ").title() for p in hf.journey_pets]

    # Intrigue plots
    intrigue_plots: list[dict] = []
    for plot in hf.intrigue_plots:
        actors_out: list[dict] = []
        for actor in plot.get("actors", []):
            actor_hfid = actor.get("hfid")
            actor_name = ""
            if actor_hfid:
                af = legends.get_figure(actor_hfid)
                if af:
                    actor_name = af.name
            actors_out.append({
                "name": actor_name,
                "hf_id": actor_hfid,
                "role": actor.get("role", "").replace("_", " "),
                "strategy": actor.get("strategy", "").replace("_", " "),
                "promised_immortality": actor.get("promised_immortality", False),
            })
        intrigue_plots.append({
            "type": plot.get("type", "").replace("_", " ").title(),
            "on_hold": plot.get("on_hold", False),
            "actors": actors_out,
        })

    # Emotional bonds (sorted by intensity)
    emotional_bonds: list[dict] = []
    for bond in hf.emotional_bonds:
        love = bond.get("love", 0)
        respect = bond.get("respect", 0)
        trust = bond.get("trust", 0)
        loyalty = bond.get("loyalty", 0)
        fear = bond.get("fear", 0)
        intensity = abs(love) + abs(respect) + abs(trust) + abs(loyalty) + abs(fear)
        if intensity == 0:
            continue
        bond_hfid = bond.get("hf_id")
        bond_name = ""
        if bond_hfid:
            bf = legends.get_figure(bond_hfid)
            if bf:
                bond_name = bf.name
        emotional_bonds.append({
            "name": bond_name,
            "hf_id": bond_hfid,
            "love": love,
            "respect": respect,
            "trust": trust,
            "loyalty": loyalty,
            "fear": fear,
            "_intensity": intensity,
        })
    emotional_bonds.sort(key=lambda b: b["_intensity"], reverse=True)

    # Former positions
    former_positions: list[dict] = []
    for fp in hf.former_positions:
        fp_eid = fp.get("entity_id")
        fp_civ_name = ""
        position_title = ""
        if fp_eid:
            fp_civ = legends.get_civilization(fp_eid)
            if fp_civ:
                fp_civ_name = fp_civ.name
                # Resolve position_profile_id to title
                ppid = fp.get("position_profile_id")
                if ppid:
                    for ep in getattr(fp_civ, '_entity_positions', []):
                        if str(ep.get("id", "")) == str(ppid):
                            position_title = ep.get("name", "") or ep.get("name_male", "") or ep.get("name_female", "")
                            break
        former_positions.append({
            "position": position_title.replace("_", " ").title() if position_title else f"Position #{fp.get('position_profile_id', '?')}",
            "civ_name": fp_civ_name,
            "civ_id": fp_eid,
            "start_year": fp.get("start_year", "?"),
            "end_year": fp.get("end_year", "?"),
        })

    # Describe events
    events_described = sorted(
        [{"year": evt.get("year", "?"), "description": describe_event(evt, legends)} for evt in raw_events],
        key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0,
    )

    return {
        "figure": figure,
        "civ_name": civ_name,
        "civ_id": civ_id,
        "relationships": relationships,
        "events": events_described,
        "kills": kills,
        "artifacts": artifacts,
        "notable_events_summary": ", ".join(summary_parts) if summary_parts else "",
        "event_count": len(raw_events),
        "deeds": hf.notable_deeds[:10] if hf.notable_deeds else [],
        "entity_positions": entity_positions,
        "active_interactions": interactions,
        "skills": skill_strs,
        "journey_pets": pets,
        "intrigue_plots": intrigue_plots if intrigue_plots else [],
        "emotional_bonds": emotional_bonds if emotional_bonds else [],
        "former_positions": former_positions if former_positions else [],
        # Sidebar: related figures from relationships, family, kills, shared events
        **_build_figure_sidebar(legends, hf, hf_id, kills, raw_events),
        "pin_entity": {"type": "figure", "id": hf_id, "name": hf.name},
    }


def _build_festivals(legends: Any, civ: Any, entity_id: int, event_by_id: dict) -> list[dict]:
    """Build structured festival data from occasion definitions and historical events."""
    from df_storyteller.context.dwarven_calendar import format_date_range, ticks_to_date

    occasion_defs = getattr(civ, '_occasions', [])
    if not occasion_defs:
        return []

    eid_str = str(entity_id)

    # Gather all occasion events for this civ, grouped by occasion_id
    from collections import defaultdict
    occasion_events: dict[str, list[dict]] = defaultdict(list)
    for ec in legends.event_collections:
        if ec.get("type") == "occasion" and str(ec.get("civ_id", "")) == eid_str:
            occasion_events[str(ec.get("occasion_id", "0"))].append(ec)

    festivals = []
    for occ_def in occasion_defs:
        occ_id = str(occ_def.get("id", "0"))
        occ_name = occ_def.get("name", f"Festival #{occ_id}")
        events = occasion_events.get(occ_id, [])

        if not events:
            # Festival defined but never held — still show the definition
            schedules = []
            for sched in occ_def.get("schedules", []):
                stype = sched.get("type", "").replace("_", " ").title()
                features = [f.replace("_", " ") for f in sched.get("features", [])]
                item = ""
                if sched.get("item_subtype"):
                    item = sched["item_subtype"].replace("_", " ")
                elif sched.get("item_type"):
                    item = sched["item_type"].replace("_", " ")
                schedules.append({"type": stype, "features": features, "item": item})
            festivals.append({
                "name": occ_name,
                "occasion_id": occ_id,
                "date": "",
                "month": "",
                "season": "",
                "held_count": 0,
                "first_year": None,
                "last_year": None,
                "site_name": "",
                "site_id": None,
                "schedules": schedules,
                "recent_winners": [],
            })
            continue

        # Get timing from first event
        first_evt = min(events, key=lambda e: int(e.get("start_year", 9999)))
        last_evt = max(events, key=lambda e: int(e.get("start_year", 0)))
        date_str = format_date_range(first_evt.get("start_seconds72"), first_evt.get("end_seconds72"))
        date_info = ticks_to_date(first_evt.get("start_seconds72"))

        # Get site from sub-events
        site_name = ""
        site_id = None
        sub_ids = first_evt.get("eventcol", [])
        if isinstance(sub_ids, str):
            sub_ids = [sub_ids]
        if isinstance(sub_ids, list):
            for sid in sub_ids:
                sub = legends.get_event_collection(sid)
                if sub:
                    sub_evts = sub.get("event", [])
                    if not isinstance(sub_evts, list):
                        sub_evts = [sub_evts]
                    for seid in sub_evts[:1]:
                        evt = event_by_id.get(str(seid))
                        if evt and evt.get("site_id") and evt["site_id"] != "-1":
                            try:
                                s = legends.get_site(int(evt["site_id"]))
                                if s:
                                    site_name = s.name
                                    site_id = s.site_id
                            except (ValueError, TypeError):
                                pass
                    if site_name:
                        break

        # Build schedule from definitions
        schedules = []
        for sched in occ_def.get("schedules", []):
            stype = sched.get("type", "").replace("_", " ").title()
            features = [f.replace("_", " ") for f in sched.get("features", [])]
            item = ""
            if sched.get("item_subtype"):
                item = sched["item_subtype"].replace("_", " ")
            elif sched.get("item_type"):
                item = sched["item_type"].replace("_", " ")
            schedules.append({"type": stype, "features": features, "item": item})

        # Find recent competition winners
        recent_winners: list[dict] = []
        recent_events = sorted(events, key=lambda e: int(e.get("start_year", 0)), reverse=True)[:10]
        for re_evt in recent_events:
            re_sub_ids = re_evt.get("eventcol", [])
            if isinstance(re_sub_ids, str):
                re_sub_ids = [re_sub_ids]
            if not isinstance(re_sub_ids, list):
                continue
            for sid in re_sub_ids:
                sub = legends.get_event_collection(sid)
                if sub and sub.get("type") == "competition":
                    comp_evts = sub.get("event", [])
                    if not isinstance(comp_evts, list):
                        comp_evts = [comp_evts]
                    for ceid in comp_evts:
                        cevt = event_by_id.get(str(ceid))
                        if cevt and cevt.get("winner_hfid"):
                            try:
                                w = legends.get_figure(int(cevt["winner_hfid"]))
                                if w:
                                    # Find competition type from schedule definitions
                                    comp_type = "Competition"
                                    sched_id = cevt.get("schedule_id", "")
                                    for sched_def in occ_def.get("schedules", []):
                                        if str(sched_def.get("id", "")) == str(sched_id):
                                            comp_type = sched_def.get("type", "competition").replace("_", " ").title()
                                            item = sched_def.get("item_subtype", sched_def.get("item_type", ""))
                                            if item:
                                                comp_type += f" ({item.replace('_', ' ')})"
                                            break
                                    recent_winners.append({
                                        "year": re_evt.get("start_year", "?"),
                                        "name": w.name,
                                        "hf_id": w.hf_id,
                                        "comp_type": comp_type,
                                    })
                            except (ValueError, TypeError):
                                pass
                            break
                if recent_winners and recent_winners[-1].get("year") == re_evt.get("start_year"):
                    break
            if len(recent_winners) >= 5:
                break

        festivals.append({
            "name": occ_name,
            "occasion_id": occ_id,
            "date": date_str,
            "month": date_info["month"] if date_info else "",
            "season": date_info["season"] if date_info else "",
            "held_count": len(events),
            "first_year": first_evt.get("start_year"),
            "last_year": last_evt.get("start_year"),
            "site_name": site_name,
            "site_id": site_id,
            "schedules": schedules,
            "recent_winners": recent_winners,
        })

    # Filter out empty festivals (held once or never, no schedules)
    festivals = [f for f in festivals if f["held_count"] > 1 or f["schedules"]]
    # Sort by held_count descending (most active festivals first)
    festivals.sort(key=lambda f: f["held_count"], reverse=True)
    return festivals


def _build_civ_sidebar_civs(legends: Any, entity_id: int, wars: list[dict]) -> list[dict]:
    """Build sidebar civilizations: opponents from wars."""
    seen: set[int] = {entity_id}
    result: list[dict] = []
    eid_str = str(entity_id)
    for war in legends.get_wars_involving(entity_id)[:10]:
        for key in ("aggressor_ent_id", "defender_ent_id"):
            ids = war.get(key, [])
            if isinstance(ids, str):
                ids = [ids]
            for oid in ids:
                try:
                    oid_int = int(oid)
                    if oid_int not in seen:
                        seen.add(oid_int)
                        c = legends.get_civilization(oid_int)
                        if c and c.name:
                            result.append({"name": c.name, "entity_id": c.entity_id})
                except (ValueError, TypeError):
                    pass
        if len(result) >= 5:
            break
    return result


def _build_civ_sidebar_artifacts(legends: Any, entity_id: int) -> list[dict]:
    """Build sidebar artifacts: created by figures in this civ."""
    result: list[dict] = []
    civ_hf_ids = {hfid for hfid, hf in legends.historical_figures.items() if hf.associated_civ_id == entity_id}
    for aid, art in legends.artifacts.items():
        if art.creator_hf_id in civ_hf_ids and art.name:
            result.append({"name": art.name, "artifact_id": art.artifact_id})
            if len(result) >= 5:
                break
    return result


def _build_civ_context(legends: Any, entity_id: int) -> dict | None:
    """Build template context for a civilization detail page."""
    civ = legends.get_civilization(entity_id)
    if not civ:
        return None

    # Sites
    sites = []
    for sid in civ.sites:
        site = legends.get_site(sid)
        if site:
            sites.append({"name": site.name, "site_type": site.site_type or "unknown", "site_id": site.site_id})

    # Wars
    wars = []
    for war in legends.get_wars_involving(entity_id):
        sy = war.get("start_year", "")
        ey = war.get("end_year", "")
        year_range = f"Year {sy}" + (f"–{ey}" if ey and ey != sy else "") if sy else ""
        wars.append({"name": war.get("name", "Unknown"), "years": year_range, "id": war.get("id", "")})

    # Leaders
    leaders = []
    for lid in civ.leader_hf_ids[:10]:
        lhf = legends.get_figure(lid)
        if lhf:
            leaders.append({"name": lhf.name, "hf_id": lhf.hf_id})

    # Sub-entities (grouped by deity to avoid massive lists)
    sub_entities = _build_sub_entities(legends, civ)

    # Notable figures belonging to this civ
    notable_figures = []
    for hfid, hf in legends.historical_figures.items():
        if hf.associated_civ_id == entity_id and hf.name:
            evt_count = legends.get_hf_event_count(hfid)
            if evt_count > 0:
                notable_figures.append({"name": hf.name, "race": hf.race.replace("_", " ").title() if hf.race else "",
                                        "hf_id": hf.hf_id, "description": f"{evt_count} events"})
    notable_figures.sort(key=lambda f: int(f["description"].split()[0]), reverse=True)

    # Count events: at civ's sites + event collections involving this civ
    event_count = 0
    for sid in civ.sites:
        site_evts = legends.get_site_event_types(sid)
        event_count += sum(site_evts.values())
    # Also count from event collections (wars, thefts, etc.)
    eid_str_for_count = str(entity_id)
    for ec in legends.event_collections:
        for key in ("attacking_enid", "defending_enid", "target_entity_id", "civ_id"):
            val = ec.get(key)
            if val:
                if isinstance(val, list) and eid_str_for_count in val:
                    ec_events = ec.get("event", [])
                    event_count += len(ec_events) if isinstance(ec_events, list) else 1
                    break
                elif str(val) == eid_str_for_count:
                    ec_events = ec.get("event", [])
                    event_count += len(ec_events) if isinstance(ec_events, list) else 1
                    break

    # Entity populations — race counts for this civ
    populations = []
    for ep in legends.entity_populations:
        if str(ep.get("civ_id", "")) == str(entity_id):
            race_str = ep.get("race", "")
            # Format is "race_name:count"
            if ":" in race_str:
                race_name, count = race_str.rsplit(":", 1)
                race_name = race_name.replace("_", " ").title()
                try:
                    populations.append({"race": race_name, "count": int(count)})
                except ValueError:
                    pass
    populations.sort(key=lambda p: p["count"], reverse=True)

    # Event collections involving this civ (thefts, abductions, beast attacks, etc.)
    from collections import Counter as _Counter
    eid_str = str(entity_id)
    civ_event_collections: list[dict] = []
    ec_type_counts: _Counter[str] = _Counter()
    # Cultural events — build structured summary instead of listing individually
    _cultural_types = {"occasion", "competition", "performance", "ceremony", "procession", "journey"}
    occasions: list[dict] = []
    event_by_id = {str(e.get("id", "")): e for e in legends.historical_events}
    for ec in legends.event_collections:
        involved = False
        for key in ("attacking_enid", "defending_enid", "target_entity_id", "civ_id"):
            val = ec.get(key)
            if val:
                if isinstance(val, list) and eid_str in val:
                    involved = True; break
                elif str(val) == eid_str:
                    involved = True; break
        if involved:
            ec_type = ec.get("type", "unknown")
            ec_type_counts[ec_type] += 1
            # Capture occasion detail for cultural section
            if ec_type == "occasion" and len(occasions) < 100:
                sub_ids = ec.get("eventcol", [])
                if isinstance(sub_ids, str): sub_ids = [sub_ids]
                sub_types: _Counter[str] = _Counter()
                if isinstance(sub_ids, list):
                    for sid in sub_ids:
                        sub = legends.get_event_collection(sid)
                        if sub:
                            sub_types[sub.get("type", "?")] += 1
                site_id = None
                site_name = ""
                # Get site from first sub-event
                if isinstance(sub_ids, list) and sub_ids:
                    sub = legends.get_event_collection(sub_ids[0])
                    if sub and sub.get("site_id") and sub["site_id"] != "-1":
                        try:
                            s = legends.get_site(int(sub["site_id"]))
                            if s:
                                site_name = s.name
                                site_id = s.site_id
                        except (ValueError, TypeError):
                            pass
                parts = [t.replace("_", " ") for t, _ in sub_types.most_common()]
                # Check for competition winner in sub-events
                comp_winner = ""
                comp_winner_id = None
                if isinstance(sub_ids, list):
                    for sid_c in sub_ids:
                        sub_c = legends.get_event_collection(sid_c)
                        if sub_c and sub_c.get("type") == "competition":
                            comp_evts = sub_c.get("event", [])
                            if not isinstance(comp_evts, list): comp_evts = [comp_evts]
                            for ceid in comp_evts:
                                cevt = event_by_id.get(str(ceid))
                                if cevt and cevt.get("winner_hfid"):
                                    try:
                                        w = legends.get_figure(int(cevt["winner_hfid"]))
                                        if w:
                                            comp_winner = w.name
                                            comp_winner_id = w.hf_id
                                    except (ValueError, TypeError):
                                        pass
                                    break
                            break
                occasions.append({
                    "year": ec.get("start_year", "?"),
                    "site_name": site_name,
                    "site_id": site_id,
                    "sub_types": ", ".join(parts) if parts else "festival",
                    "comp_winner": comp_winner,
                    "comp_winner_id": comp_winner_id,
                })
            # Only list interesting events (skip cultural noise)
            if ec_type not in _cultural_types and len(civ_event_collections) < 50:
                ec_name = ec.get("name", "")
                if not ec_name or ec_name == ec_type.replace("_", " ").title():
                    # Build a more descriptive name
                    site_id = ec.get("site_id")
                    site_name = ""
                    if site_id and site_id != "-1":
                        try:
                            s = legends.get_site(int(site_id))
                            if s: site_name = s.name
                        except (ValueError, TypeError):
                            pass
                    year = ec.get("start_year", "")
                    ec_name = ec_type.replace("_", " ").title()
                    if site_name:
                        ec_name += f" at {site_name}"
                    if year:
                        ec_name += f" (year {year})"
                civ_event_collections.append({
                    "id": ec.get("id", ""),
                    "name": ec_name,
                    "type": ec_type.replace("_", " ").title(),
                    "year": ec.get("start_year", ""),
                })

    # Format event collection type summary — separate interesting from cultural
    _interesting_summary = []
    _cultural_summary = []
    for t, c in ec_type_counts.most_common():
        label = t.replace("_", " ")
        if c > 1:
            label += "s"
        entry = f"{c} {label}"
        if t in _cultural_types:
            _cultural_summary.append(entry)
        else:
            _interesting_summary.append(entry)
    ec_summary = ", ".join(_interesting_summary)
    cultural_summary = ", ".join(_cultural_summary)

    # Honors / rank system
    _IP_THRESHOLDS_CIV = [0, 500, 1100, 1800, 2600, 3500, 4600, 5800, 7200, 8800, 10600, 12600, 14900, 17400, 20200, 23300]
    def _ip_to_level_civ(ip: int) -> int:
        for lvl in range(len(_IP_THRESHOLDS_CIV) - 1, -1, -1):
            if ip >= _IP_THRESHOLDS_CIV[lvl]:
                return lvl
        return 0

    honors: list[dict] = []
    for hon in getattr(civ, '_honors', []):
        required_skill = hon.get("required_skill", "").replace("_", " ").title()
        required_ip = hon.get("required_skill_ip_total", 0)
        required_level = _skill_level_name(_ip_to_level_civ(required_ip)) if required_ip else None
        required_battles = hon.get("required_battles")
        honors.append({
            "name": hon.get("name", "Unknown"),
            "required_skill": required_skill if required_skill else None,
            "required_level": required_level,
            "required_battles": required_battles,
            "precedence": hon.get("gives_precedence", 0),
        })
    honors.sort(key=lambda h: h["precedence"], reverse=True)

    return {
        "civ": {"name": civ.name, "race": civ.race.replace("_", " ").title() if civ.race else "", "entity_id": entity_id},
        "sites": sites,
        "wars": wars,
        "leaders": leaders,
        "sub_entities": sub_entities[:15],
        "notable_figures": notable_figures[:200],
        "event_count": event_count,
        "populations": populations,
        "civ_event_collections": civ_event_collections,
        "ec_summary": ec_summary,
        "cultural_summary": cultural_summary,
        "occasions": occasions,
        "festivals": _build_festivals(legends, civ, entity_id, event_by_id),
        "honors": honors,
        # Sidebar — diverse mix of related entities
        "sidebar_figures": ([{"name": f["name"], "hf_id": f["hf_id"]} for f in notable_figures[:5]]
                            + [{"name": l["name"], "hf_id": l["hf_id"]} for l in leaders[:5]
                               if not any(f["hf_id"] == l["hf_id"] for f in notable_figures[:5])])[:8],
        "sidebar_civs": _build_civ_sidebar_civs(legends, entity_id, wars),
        "sidebar_sites": sites[:5],
        "sidebar_wars": wars[:5],
        "sidebar_artifacts": _build_civ_sidebar_artifacts(legends, entity_id),
        "sidebar_events": [{"id": ec["id"], "name": ec["name"]} for ec in civ_event_collections[:5] if ec.get("name")],
        "pin_entity": {"type": "civilization", "id": entity_id, "name": civ.name},
    }


def _build_site_context(legends: Any, site_id: int) -> dict | None:
    """Build template context for a site detail page."""
    from df_storyteller.context.event_renderer import describe_event_linked as describe_event

    site = legends.get_site(site_id)
    if not site:
        return None

    owner_name = owner_id = None
    if site.owner_civ_id:
        owner = legends.get_civilization(site.owner_civ_id)
        if owner:
            owner_name = owner.name
            owner_id = owner.entity_id

    coords_str = f"({site.coordinates[0]}, {site.coordinates[1]})" if site.coordinates else None
    event_types = legends.get_site_event_types(site_id)
    total_events = sum(event_types.values())

    # Get actual events at this site
    site_events = []
    for evt in legends.historical_events:
        sid = evt.get("site_id")
        if sid and sid != "-1":
            try:
                if int(sid) == site_id:
                    site_events.append(evt)
            except (ValueError, TypeError):
                pass
        if len(site_events) >= 200:
            break

    events_described = sorted(
        [{"year": evt.get("year", "?"), "description": describe_event(evt, legends)} for evt in site_events],
        key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0,
    )

    # Make event type labels readable
    readable_types = {}
    for et, count in event_types.items():
        readable_types[et.replace("_", " ").replace("hf ", "").title()] = count

    # Structures at this site
    structures = []
    for struct in site.structures:
        s = {"name": struct.get("name", ""), "type": struct.get("type", "").replace("_", " ").title()}
        deity_id = struct.get("deity_hf_id")
        if deity_id:
            deity = legends.get_figure(deity_id)
            if deity:
                s["deity"] = deity.name
                s["deity_id"] = deity.hf_id
        structures.append(s)

    # Site properties (houses, workshops, etc.)
    from collections import Counter as _PropCounter
    site_properties: list[dict] = []
    prop_type_counts: _PropCounter[str] = _PropCounter()
    prop_owned_counts: _PropCounter[str] = _PropCounter()
    for prop in site.properties:
        ptype = prop.get("type", "unknown").replace("_", " ")
        prop_type_counts[ptype] += 1
        owner_hfid = prop.get("owner_hfid")
        prop_owner_name = None
        if owner_hfid:
            prop_owned_counts[ptype] += 1
            pf = legends.get_figure(owner_hfid)
            if pf:
                prop_owner_name = pf.name
        site_properties.append({
            "type": ptype,
            "owner_name": prop_owner_name,
            "owner_hf_id": owner_hfid,
        })
    # Build summary string
    summary_parts_site: list[str] = []
    for ptype, total in prop_type_counts.most_common():
        owned = prop_owned_counts.get(ptype, 0)
        label = f"{total} {ptype}{'s' if total != 1 else ''}"
        if owned > 0:
            label += f" ({owned} owned)"
        summary_parts_site.append(label)
    property_summary = ", ".join(summary_parts_site) if summary_parts_site else ""

    return {
        "site": {"name": site.name, "site_type": site.site_type.replace("_", " ").title() if site.site_type else "",
                 "site_id": site.site_id, "coordinates": coords_str},
        "owner_name": owner_name,
        "owner_id": owner_id,
        "event_types": readable_types,
        "total_events": total_events,
        "events": events_described,
        "structures": structures,
        "site_properties": site_properties if site_properties else [],
        "property_summary": property_summary,
        # Sidebar: other sites from same owner
        # Sidebar — figures who own property here, related sites, owner civ
        "sidebar_figures": [{"name": legends.get_figure(p.get("owner_hfid", 0)).name,
                             "hf_id": p["owner_hfid"]}
                            for p in site.properties
                            if p.get("owner_hfid") and legends.get_figure(p["owner_hfid"])][:5],
        "sidebar_civs": [{"name": owner_name, "entity_id": owner_id}] if owner_name else [],
        "sidebar_sites": [{"name": s.name, "site_id": s.site_id}
                          for s in legends.sites.values()
                          if s.owner_civ_id == site.owner_civ_id and s.site_id != site_id and s.name][:5] if site.owner_civ_id else [],
        "sidebar_wars": [],
        "sidebar_artifacts": [],
        "sidebar_events": [],
        "pin_entity": {"type": "site", "id": site_id, "name": site.name},
    }


def _build_artifact_context(legends: Any, artifact_id: int) -> dict | None:
    """Build template context for an artifact detail page."""
    art = legends.get_artifact(artifact_id)
    if not art:
        return None

    creator_name = creator_id = None
    if art.creator_hf_id:
        creator = legends.get_figure(art.creator_hf_id)
        if creator:
            creator_name = creator.name
            creator_id = creator.hf_id

    site_name = site_id = None
    if art.site_id:
        site = legends.get_site(art.site_id)
        if site:
            site_name = site.name
            site_id = site.site_id

    # Pages (for books)
    pages: list[dict] = []
    # Build written_content lookup by ID
    wc_by_id: dict[str, dict] = {}
    for wc in legends.written_contents:
        wc_id = str(wc.get("id", ""))
        if wc_id:
            wc_by_id[wc_id] = wc
    for page in art.pages:
        wc_id = str(page.get("written_content_id", ""))
        wc = wc_by_id.get(wc_id, {})
        wc_title = wc.get("title", "")
        wc_type = wc.get("type", "").replace("_", " ").title()
        pages.append({
            "page_number": page.get("page_number", 0),
            "title": wc_title if wc_title else f"Written Content #{wc_id}",
            "wc_type": wc_type,
            "wc_id": wc_id,
        })
    pages.sort(key=lambda p: p["page_number"])

    return {
        "artifact": {"name": art.name, "item_type": art.item_type.replace("_", " ") if art.item_type else "",
                      "material": art.material, "description": art.description, "artifact_id": art.artifact_id},
        "creator_name": creator_name,
        "creator_id": creator_id,
        "site_name": site_name,
        "site_id": site_id,
        "pages": pages,
    }


def _build_war_context(legends: Any, ec_id: str) -> dict | None:
    """Build template context for a war detail page."""
    ec = legends.get_event_collection(ec_id)
    if not ec:
        return None

    war = {
        "name": ec.get("name", "Unknown Conflict"),
        "type": ec.get("type", "conflict").replace("_", " ").title(),
        "start_year": ec.get("start_year", "?"),
        "end_year": ec.get("end_year"),
        "id": ec.get("id", ""),
    }

    # For battles, get aggressor/defender from parent war
    faction_source = ec
    if ec.get("type") == "battle" and ec.get("war_eventcol"):
        parent_war = legends.get_event_collection(ec["war_eventcol"])
        if parent_war:
            faction_source = parent_war
            war["parent_war_name"] = parent_war.get("name", "")
            war["parent_war_id"] = parent_war.get("id", "")

    def _resolve_factions(key: str) -> list[dict]:
        ids = faction_source.get(key, [])
        if isinstance(ids, str):
            ids = [ids]
        factions = []
        for eid_str in ids:
            try:
                c = legends.get_civilization(int(eid_str))
                if c:
                    factions.append({"name": c.name, "race": c.race.replace("_", " ").title() if c.race else "", "entity_id": c.entity_id})
            except (ValueError, TypeError):
                pass
        return factions

    aggressors = _resolve_factions("aggressor_ent_id")
    defenders = _resolve_factions("defender_ent_id")

    # Battles
    war_id = ec.get("id")
    war_battles = [b for b in legends.battles if b.get("war_eventcol") == war_id]
    total_atk = total_def = 0
    battles = []
    for b in war_battles:
        atk_d = b.get("attacking_squad_deaths", [])
        def_d = b.get("defending_squad_deaths", [])
        ad = sum(int(d) for d in atk_d if str(d).isdigit()) if isinstance(atk_d, list) else 0
        dd = sum(int(d) for d in def_d if str(d).isdigit()) if isinstance(def_d, list) else 0
        total_atk += ad
        total_def += dd
        battles.append({
            "name": b.get("name", "Unknown Battle"),
            "outcome": b.get("outcome", "").replace("_", " ").title() if b.get("outcome") else "",
            "year": b.get("start_year", "?"),
            "id": b.get("id", ""),
            "atk_casualties": ad,
            "def_casualties": dd,
        })

    def _resolve_combatants(key: str) -> list[dict]:
        hfids = ec.get(key, [])
        if isinstance(hfids, str):
            hfids = [hfids]
        combatants = []
        for hid in hfids[:10]:
            try:
                h = legends.get_figure(int(hid))
                if h:
                    combatants.append({"name": h.name, "hf_id": h.hf_id})
            except (ValueError, TypeError):
                pass
        return combatants

    return {
        "war": war,
        "aggressors": aggressors,
        "defenders": defenders,
        "battles": battles,
        "total_atk_casualties": total_atk,
        "total_def_casualties": total_def,
        "notable_attackers": _resolve_combatants("attacking_hfid"),
        "notable_defenders": _resolve_combatants("defending_hfid"),
    }


@app.get("/lore/figure/{hf_id}", response_class=HTMLResponse)
async def lore_figure_page(request: Request, hf_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_figure_context(world_lore._legends, hf_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_figure.html", context={**ctx, "content_class": "content-wide", **detail})


@app.get("/lore/civ/{entity_id}", response_class=HTMLResponse)
async def lore_civ_page(request: Request, entity_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_civ_context(world_lore._legends, entity_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_civ.html", context={**ctx, "content_class": "content-wide", **detail})


@app.get("/lore/site/{site_id}", response_class=HTMLResponse)
async def lore_site_page(request: Request, site_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_site_context(world_lore._legends, site_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_site.html", context={**ctx, "content_class": "content-wide", **detail})


@app.get("/lore/artifact/{artifact_id}", response_class=HTMLResponse)
async def lore_artifact_page(request: Request, artifact_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_artifact_context(world_lore._legends, artifact_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_artifact.html", context={**ctx, "content_class": "content-wide", **detail})


@app.get("/lore/war/{ec_id}", response_class=HTMLResponse)
async def lore_war_page(request: Request, ec_id: str):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_war_context(world_lore._legends, ec_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_war.html", context={**ctx, "content_class": "content-wide", **detail})


@app.get("/lore/event/{ec_id}", response_class=HTMLResponse)
async def lore_event_collection_page(request: Request, ec_id: str):
    """Generic detail page for any event collection (duels, purges, abductions, etc.)."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    ec = legends.get_event_collection(ec_id)
    if not ec:
        return RedirectResponse("/lore")

    # If it's a war, redirect to the dedicated war page
    if ec.get("type") == "war":
        return RedirectResponse(f"/lore/war/{ec_id}")

    from df_storyteller.context.event_renderer import describe_event_linked

    # Build context
    ec_data: dict[str, Any] = {
        "name": ec.get("name", ""),
        "type": ec.get("type", "").replace("_", " ").title(),
        "adjective": ec.get("adjective", ""),
        "start_year": ec.get("start_year", "?"),
        "end_year": ec.get("end_year"),
        "site_id": None, "site_name": None,
        "attacker_name": None, "attacker_id": None,
        "defender_name": None, "defender_id": None,
        "target_name": None, "target_id": None,
        "attacking_hf_name": None, "attacking_hf_id": None,
        "defending_hf_name": None, "defending_hf_id": None,
        "parent_war": None, "parent_war_id": None,
    }

    # Resolve site
    site_id = ec.get("site_id")
    if site_id and site_id != "-1":
        try:
            site = legends.get_site(int(site_id))
            if site:
                ec_data["site_id"] = site.site_id
                ec_data["site_name"] = site.name
        except (ValueError, TypeError):
            pass

    # Resolve attacker/defender civs
    for role, key in [("attacker", "attacking_enid"), ("defender", "defending_enid")]:
        eid = ec.get(key)
        if eid and eid != "-1":
            try:
                c = legends.get_civilization(int(eid))
                if c:
                    ec_data[f"{role}_name"] = c.name
                    ec_data[f"{role}_id"] = c.entity_id
            except (ValueError, TypeError):
                pass

    # Resolve target entity (persecutions, coups)
    target_eid = ec.get("target_entity_id")
    if target_eid and target_eid != "-1":
        try:
            c = legends.get_civilization(int(target_eid))
            if c:
                ec_data["target_name"] = c.name
                ec_data["target_id"] = c.entity_id
        except (ValueError, TypeError):
            pass

    # Resolve attacker/defender HFs (duels)
    for role, key in [("attacking_hf", "attacking_hfid"), ("defending_hf", "defending_hfid")]:
        hfid = ec.get(key)
        if hfid:
            try:
                hf = legends.get_figure(int(hfid))
                if hf:
                    ec_data[f"{role}_name"] = hf.name
                    ec_data[f"{role}_id"] = hf.hf_id
            except (ValueError, TypeError):
                pass

    # Resolve parent war
    war_ec_id = ec.get("war_eventcol")
    if war_ec_id and war_ec_id != "-1":
        war_ec = legends.get_event_collection(war_ec_id)
        if war_ec:
            ec_data["parent_war"] = war_ec.get("name", "Unknown War")
            ec_data["parent_war_id"] = war_ec_id

    # Build a descriptive name if none exists
    if not ec_data["name"]:
        ec_type = ec_data["type"]
        parts = [ec_type]
        if ec_data.get("adjective"):
            parts = [f"{ec_data['adjective']} {ec_type}"]
        if ec_data.get("site_name"):
            parts.append(f"at {ec_data['site_name']}")
        if ec_data.get("attacker_name") and ec_data.get("defender_name"):
            parts.append(f"({ec_data['attacker_name']} vs {ec_data['defender_name']})")
        elif ec_data.get("attacking_hf_name") and ec_data.get("defending_hf_name"):
            parts.append(f"({ec_data['attacking_hf_name']} vs {ec_data['defending_hf_name']})")
        elif ec_data.get("target_name"):
            parts.append(f"against {ec_data['target_name']}")
        ec_data["name"] = " ".join(parts)

    # Resolve sub-events
    event_by_id = {str(e.get("id", "")): e for e in legends.historical_events}
    event_ids = ec.get("event", [])
    if not isinstance(event_ids, list):
        event_ids = [event_ids]

    events = []
    for eid in event_ids:
        evt = event_by_id.get(str(eid))
        if evt:
            events.append({
                "year": evt.get("year", "?"),
                "description": describe_event_linked(evt, legends),
            })

    return templates.TemplateResponse(request=request, name="lore_event_collection.html", context={
        **ctx, "content_class": "content-wide", "ec": ec_data, "events": events,
    })


@app.get("/lore/work/{wc_id}", response_class=HTMLResponse)
async def lore_written_work_page(request: Request, wc_id: str):
    """Detail page for a written work."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    wc = None
    for w in legends.written_contents:
        if str(w.get("id", "")) == str(wc_id):
            wc = w
            break
    if not wc:
        return RedirectResponse("/lore")

    # Resolve author
    author_name = author_id = author_civ = author_civ_id = None
    author_raw = wc.get("author")
    if author_raw:
        try:
            hf = legends.get_figure(int(author_raw))
            if hf:
                author_name = hf.name
                author_id = hf.hf_id
                if hf.associated_civ_id:
                    c = legends.get_civilization(hf.associated_civ_id)
                    if c:
                        author_civ = c.name
                        author_civ_id = c.entity_id
        except (ValueError, TypeError):
            pass

    # Find artifacts containing this work
    artifacts = []
    for aid, art in legends.artifacts.items():
        for page in art.pages:
            if str(page.get("written_content_id", "")) == str(wc_id):
                artifacts.append({"name": art.name, "artifact_id": art.artifact_id})
                break

    work = {
        "title": wc.get("title", "Untitled"),
        "form": wc.get("type", "").replace("_", " ").title() if wc.get("type") else "",
        "style": wc.get("style", "").split(":")[0].strip().title() if wc.get("style") else "",
        "page_count": wc.get("page_end", ""),
        "reference": wc.get("reference", "").strip() if wc.get("reference") else "",
        "author_name": author_name,
        "author_id": author_id,
        "author_civ": author_civ,
        "author_civ_id": author_civ_id,
        "artifacts": artifacts,
    }

    return templates.TemplateResponse(request=request, name="lore_written_work.html", context={
        **ctx, "content_class": "content-wide", "work": work,
    })


@app.get("/lore/festival/{civ_id}/{occasion_id}", response_class=HTMLResponse)
async def lore_festival_page(request: Request, civ_id: int, occasion_id: str):
    """Detail page for a civilization's festival."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    civ = legends.get_civilization(civ_id)
    if not civ:
        return RedirectResponse("/lore")

    event_by_id = {str(e.get("id", "")): e for e in legends.historical_events}
    festivals = _build_festivals(legends, civ, civ_id, event_by_id)

    festival = None
    for f in festivals:
        if str(f.get("occasion_id", "")) == str(occasion_id):
            festival = f
            break
    if not festival:
        return RedirectResponse(f"/lore/civ/{civ_id}")

    festival["civ_name"] = civ.name
    festival["civ_id"] = civ_id

    return templates.TemplateResponse(request=request, name="lore_festival.html", context={
        **ctx, "content_class": "content-wide", "festival": festival,
    })


@app.get("/lore/form/{form_type}/{form_id}", response_class=HTMLResponse)
async def lore_cultural_form_page(request: Request, form_type: str, form_id: str):
    """Detail page for a cultural form (poetic, musical, dance)."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    form_lists = {"poetic": legends.poetic_forms, "musical": legends.musical_forms, "dance": legends.dance_forms}
    forms = form_lists.get(form_type, [])

    form_data = None
    for f in forms:
        if str(f.get("id", "")) == str(form_id):
            form_data = f
            break
    if not form_data:
        return RedirectResponse("/lore")

    form = {
        "name": form_data.get("name", "Unknown"),
        "form_type": f"{form_type.title()} Form",
        "description": form_data.get("description", ""),
    }

    return templates.TemplateResponse(request=request, name="lore_cultural_form.html", context={
        **ctx, "content_class": "content-wide", "form": form,
    })


# ==================== Lore Stats API ====================


@app.get("/api/lore/stats/world")
async def api_lore_stats_world():
    """World-level statistics for charts: race distribution, event timeline, event types."""
    from collections import Counter
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    # Historical figures by race (top 10 + other)
    race_counts: Counter[str] = Counter()
    for hf in legends.historical_figures.values():
        race = hf.race.replace("_", " ").title() if hf.race else "Unknown"
        race_counts[race] += 1

    top_races = race_counts.most_common(10)
    other_count = sum(race_counts.values()) - sum(c for _, c in top_races)
    race_labels = [r for r, _ in top_races]
    race_values = [c for _, c in top_races]
    if other_count > 0:
        race_labels.append("Other")
        race_values.append(other_count)

    # Events by century
    century_counts: Counter[int] = Counter()
    for evt in legends.historical_events:
        year = evt.get("year", "")
        try:
            century = int(year) // 100
            century_counts[century] += 1
        except (ValueError, TypeError):
            pass

    if century_counts:
        min_c = min(century_counts)
        max_c = max(century_counts)
        timeline_labels = [f"{c * 100}s" for c in range(min_c, max_c + 1)]
        timeline_values = [century_counts.get(c, 0) for c in range(min_c, max_c + 1)]
    else:
        timeline_labels = []
        timeline_values = []

    # Event type distribution (top 12)
    type_counts: Counter[str] = Counter()
    for evt in legends.historical_events:
        etype = evt.get("type", "unknown").replace("_", " ").replace("hf ", "").title()
        type_counts[etype] += 1

    top_types = type_counts.most_common(12)
    type_labels = [t for t, _ in top_types]
    type_values = [c for _, c in top_types]

    return {
        "race_distribution": {"labels": race_labels, "values": race_values},
        "event_timeline": {"labels": timeline_labels, "values": timeline_values},
        "event_types": {"labels": type_labels, "values": type_values},
    }


@app.get("/api/lore/stats/figure/{hf_id}")
async def api_lore_stats_figure(hf_id: int):
    """Per-figure event timeline for charts."""
    from collections import Counter
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    events = legends.get_hf_events(hf_id)

    year_counts: Counter[int] = Counter()
    for evt in events:
        try:
            year_counts[int(evt.get("year", 0))] += 1
        except (ValueError, TypeError):
            pass

    if not year_counts:
        return {"event_timeline": {"labels": [], "values": []}}

    min_y = min(year_counts)
    max_y = max(year_counts)
    span = max_y - min_y

    # Choose bucket size based on time span
    if span > 200:
        bucket = 20
    elif span > 50:
        bucket = 10
    elif span > 20:
        bucket = 5
    else:
        bucket = 1

    if bucket > 1:
        bucketed: Counter[int] = Counter()
        for y, c in year_counts.items():
            bucketed[(y // bucket) * bucket] += c
        sorted_keys = sorted(bucketed)
        labels = [f"{k}" if bucket == 1 else f"{k}s" for k in sorted_keys]
        values = [bucketed[k] for k in sorted_keys]
    else:
        # Only show years that have events (no zero-padding)
        sorted_years = sorted(year_counts)
        labels = [str(y) for y in sorted_years]
        values = [year_counts[y] for y in sorted_years]

    return {"event_timeline": {"labels": labels, "values": values}}


@app.get("/api/lore/stats/civ/{entity_id}")
async def api_lore_stats_civ(entity_id: int):
    """Per-civ war stats for charts."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    wars = legends.get_wars_involving(entity_id)

    war_labels = []
    battle_counts = []
    for war in wars[:15]:
        name = war.get("name", "?")
        if len(name) > 30:
            name = name[:27] + "..."
        war_id = war.get("id")
        n_battles = sum(1 for b in legends.battles if b.get("war_eventcol") == war_id)
        war_labels.append(name)
        battle_counts.append(n_battles)

    return {"war_battles": {"labels": war_labels, "values": battle_counts}}


@app.get("/api/lore/stats/site/{site_id}")
async def api_lore_stats_site(site_id: int):
    """Per-site event stats for charts."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    event_types = legends.get_site_event_types(site_id)

    # Top 8 event types for doughnut
    from collections import Counter
    sorted_types = Counter(event_types).most_common(8)
    other = sum(event_types.values()) - sum(c for _, c in sorted_types)

    labels = [t.replace("_", " ").replace("hf ", "").title() for t, _ in sorted_types]
    values = [c for _, c in sorted_types]
    if other > 0:
        labels.append("Other")
        values.append(other)

    return {"event_types": {"labels": labels, "values": values}}


# ==================== Lore Graph API ====================


@app.get("/api/lore/graph/family/{hf_id}")
async def api_lore_graph_family(hf_id: int):
    """Family tree graph data for vis-network: nodes and edges up to 2 generations."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    hf = legends.get_figure(hf_id)
    if not hf:
        return JSONResponse({"error": "not_found"}, status_code=404)

    nodes: dict[int, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple[int, int, str]] = set()

    def add_node(fid: int, level: int = 0) -> None:
        if fid in nodes:
            return
        f = legends.get_figure(fid)
        if not f:
            return
        is_dead = f.death_year is not None and f.death_year > 0
        nodes[fid] = {
            "id": fid,
            "label": f.name.split(",")[0].strip() if f.name else f"#{fid}",
            "race": f.race.replace("_", " ").title() if f.race else "",
            "level": level,
            "dead": is_dead,
            "is_deity": f.is_deity,
            "is_target": fid == hf_id,
        }

    def add_edge(src: int, tgt: int, label: str) -> None:
        key = (min(src, tgt), max(src, tgt), label)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": src, "to": tgt, "label": label})

    # Start with the target figure
    add_node(hf_id, level=0)
    family = legends.get_hf_family(hf_id)

    # Parents (level -1)
    for pid in family["parents"]:
        add_node(pid, level=-1)
        add_edge(pid, hf_id, "parent")
        # Grandparents (level -2)
        gp_family = legends.get_hf_family(pid)
        for gpid in gp_family["parents"]:
            add_node(gpid, level=-2)
            add_edge(gpid, pid, "parent")

    # Spouse (same level)
    for sid in family["spouse"]:
        add_node(sid, level=0)
        add_edge(hf_id, sid, "spouse")

    # Children (level 1)
    for cid in family["children"]:
        add_node(cid, level=1)
        add_edge(hf_id, cid, "parent")
        # Grandchildren (level 2)
        gc_family = legends.get_hf_family(cid)
        for gcid in gc_family["children"]:
            add_node(gcid, level=2)
            add_edge(cid, gcid, "parent")

    # Siblings (via shared parents, same level)
    for pid in family["parents"]:
        p_family = legends.get_hf_family(pid)
        for sibling_id in p_family["children"]:
            if sibling_id != hf_id:
                add_node(sibling_id, level=0)
                add_edge(pid, sibling_id, "parent")

    return {"nodes": list(nodes.values()), "edges": edges}


@app.get("/api/lore/graph/wars/{entity_id}")
async def api_lore_graph_wars(entity_id: int):
    """Warfare network graph: civilizations as nodes, wars as edges."""
    from collections import Counter
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    wars = legends.get_wars_involving(entity_id)

    nodes: dict[int, dict] = {}
    edge_weights: Counter[tuple[int, int]] = Counter()

    for war in wars:
        aggressors = war.get("aggressor_ent_id", [])
        defenders = war.get("defender_ent_id", [])
        if isinstance(aggressors, str):
            aggressors = [aggressors]
        if isinstance(defenders, str):
            defenders = [defenders]

        all_ids: list[int] = []
        for eid_str in aggressors + defenders:
            try:
                eid = int(eid_str)
                if eid not in nodes:
                    c = legends.get_civilization(eid)
                    if c:
                        nodes[eid] = {
                            "id": eid,
                            "label": c.name,
                            "race": c.race.replace("_", " ").title() if c.race else "",
                            "is_target": eid == entity_id,
                        }
                all_ids.append(eid)
            except (ValueError, TypeError):
                pass

        # Create edges between aggressors and defenders
        for a_str in aggressors:
            for d_str in defenders:
                try:
                    a, d = int(a_str), int(d_str)
                    key = (min(a, d), max(a, d))
                    edge_weights[key] += 1
                except (ValueError, TypeError):
                    pass

    edges = [{"from": a, "to": b, "weight": w} for (a, b), w in edge_weights.items()]

    return {"nodes": list(nodes.values()), "edges": edges}


# ==================== World Map ====================

_map_image_cache: tuple[bytes, int, int] | None = None


@app.get("/lore/map", response_class=HTMLResponse)
async def lore_map_page(request: Request):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    return templates.TemplateResponse(request=request, name="lore_map.html", context={
        **ctx,
        "content_class": "content-wide",
        "lore_loaded": world_lore.is_loaded,
    })


@app.get("/api/lore/map/terrain")
async def api_map_terrain():
    """Return generated terrain map PNG from region coordinate data."""
    from fastapi.responses import Response
    global _map_image_cache

    if _map_image_cache is not None:
        png_bytes, _, _ = _map_image_cache
        return Response(content=png_bytes, media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})

    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    from df_storyteller.context.map_generator import generate_terrain_map
    result = generate_terrain_map(world_lore._legends.regions, scale=4)
    if result is None:
        return JSONResponse({"error": "No region coordinate data available. Export legends_plus from DFHack."}, status_code=404)

    _map_image_cache = result
    png_bytes, _, _ = result
    return Response(content=png_bytes, media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@app.get("/api/lore/map/sites")
async def api_map_sites():
    """Return site marker data for the world map."""
    global _map_image_cache

    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    # Get world size from cached map or compute from regions
    world_w = world_h = 0
    if _map_image_cache:
        _, world_w, world_h = _map_image_cache
    else:
        for region in legends.regions:
            coords_str = region.get("coords", "")
            if coords_str:
                for pair in coords_str.split("|"):
                    parts = pair.strip().split(",")
                    if len(parts) == 2:
                        try:
                            x, y = int(parts[0]), int(parts[1])
                            if x >= world_w:
                                world_w = x + 1
                            if y >= world_h:
                                world_h = y + 1
                        except ValueError:
                            pass

    sites = []
    for sid, site in legends.sites.items():
        if not site.coordinates:
            continue
        owner_name = ""
        owner_race = ""
        owner_civ_id = None
        if site.owner_civ_id:
            civ = legends.get_civilization(site.owner_civ_id)
            if civ:
                owner_name = civ.name
                owner_race = civ.race.replace("_", " ").title() if civ.race else ""
                owner_civ_id = civ.entity_id

        sites.append({
            "id": site.site_id,
            "name": site.name,
            "type": site.site_type,
            "x": site.coordinates[0],
            "y": site.coordinates[1],
            "owner_civ_id": owner_civ_id,
            "owner_name": owner_name,
            "owner_race": owner_race,
        })

    # World constructions (roads, tunnels) as polylines
    constructions = []
    for wc in legends.world_constructions:
        coords_str = wc.get("coords", "")
        if not coords_str:
            continue
        points = []
        for pair in coords_str.split("|"):
            pair = pair.strip()
            if not pair:
                continue
            parts = pair.split(",")
            if len(parts) == 2:
                try:
                    points.append([int(parts[0]), int(parts[1])])
                except ValueError:
                    pass
        if len(points) >= 2:
            constructions.append({
                "name": wc.get("name", ""),
                "type": wc.get("type", "").replace("_", " "),
                "points": points,
            })

    return {"sites": sites, "world_size": [world_w, world_h], "constructions": constructions}


# ==================== Gazette ====================


def _pick_gazette_author(character_tracker) -> tuple[str, str]:
    """Pick the best author for the gazette from fortress citizens.

    Priority: highest writing/poetry/prose skill, then social skills, then any dwarf.
    Returns (author_name, author_profession).
    """
    ranked = character_tracker.ranked_characters()
    writing_keywords = {"writing", "prose", "poetry", "record keeping"}
    social_keywords = {"persuasion", "conversation", "social awareness", "flattery"}

    best = None
    best_score = -1

    for dwarf, _ in ranked:
        if not dwarf.is_alive:
            continue
        for skill in dwarf.skills:
            name_lower = skill.name.lower()
            if name_lower in writing_keywords:
                score = skill.experience + 1000  # Writing skills preferred
            elif name_lower in social_keywords:
                score = skill.experience + 500
            else:
                continue
            if score > best_score:
                best_score = score
                best = dwarf

    if best:
        return best.name.split(",")[0].strip(), best.profession

    # Fallback: any living dwarf
    for dwarf, _ in ranked:
        if dwarf.is_alive:
            return dwarf.name.split(",")[0].strip(), dwarf.profession

    return "An Anonymous Scribe", ""


def _gazette_section_length(config: AppConfig) -> str:
    """Calculate target word count per gazette section based on token budget."""
    tokens = config.story.gazette_max_tokens
    # ~5 sections, ~0.75 words per token
    words_per_section = int((tokens * 0.75) / 5)
    if words_per_section < 80:
        return "50-80"
    elif words_per_section < 150:
        return "80-150"
    elif words_per_section < 300:
        return "150-300"
    else:
        return "300-500"


@app.get("/gazette", response_class=HTMLResponse)
async def gazette_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "gazette", metadata)
    fortress_dir = _get_fortress_dir(config, metadata)

    # Load gazette data
    gazette = None
    past_gazettes = []
    try:
        import json as _json
        gazette_path = fortress_dir / "gazette.json"
        if gazette_path.exists():
            all_gazettes = _json.loads(gazette_path.read_text(encoding="utf-8", errors="replace"))
            current_year = metadata.get("year", 0)
            current_season = metadata.get("season", "")
            for g in all_gazettes:
                if g.get("year") == current_year and g.get("season") == current_season:
                    gazette = g
                else:
                    past_gazettes.append(g)
    except (ValueError, OSError):
        pass

    # Sort past gazettes newest first
    past_gazettes.sort(key=lambda g: (g.get("year", 0), {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}.get(g.get("season", ""), 0)), reverse=True)

    return templates.TemplateResponse(request=request, name="gazette.html", context={
        **ctx, "gazette": gazette, "past_gazettes": past_gazettes,
    })


@app.post("/api/gazette/generate")
async def api_generate_gazette():
    """Generate a fortress gazette — dwarven newspaper with multiple sections."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    author_name, author_prof = _pick_gazette_author(character_tracker)
    fortress_name = metadata.get("fortress_name", "the fortress")
    year = metadata.get("year", 0)
    season = metadata.get("season", "")
    population = metadata.get("population", 0)

    # Gather context for each section
    from df_storyteller.context.context_builder import _format_event
    from df_storyteller.context.narrative_formatter import format_fortress_context

    # Herald: fortress events summary
    recent_events = event_store.recent_events(30)
    event_lines = [_format_event(e) for e in reversed(recent_events[-30:])]
    fortress_context = format_fortress_context(metadata)

    # Military: combat encounters
    from df_storyteller.schema.events import EventType as ET
    combat_text = ""
    combat_events = [e for e in recent_events if e.event_type == ET.COMBAT]
    if combat_events:
        combat_lines = []
        for e in combat_events:
            d = e.data
            atk = d.attacker.name if hasattr(d, "attacker") else "?"
            defn = d.defender.name if hasattr(d, "defender") else "?"
            outcome = getattr(d, "outcome", "")
            lethal = " [FATAL]" if getattr(d, "is_lethal", False) else ""
            combat_lines.append(f"- {atk} vs {defn}: {outcome}{lethal}")
        combat_text = "\n".join(combat_lines)

    # Gossip: chat log conversations
    chat_text = ""
    gamelog_path = Path(config.paths.gamelog) if config.paths.gamelog else None
    if gamelog_path and gamelog_path.exists():
        from df_storyteller.context.loader import _read_current_session_gamelog
        chat_pattern = re.compile(r'^(.+?),\s*(.+?):\s+(.+)$')
        chat_lines_raw = []
        for line in _read_current_session_gamelog(gamelog_path):
            m = chat_pattern.match(line)
            if m and not m.group(3).startswith("cancels "):
                chat_lines_raw.append(f"{m.group(1)}: {m.group(3)}")
        chat_text = "\n".join(chat_lines_raw[:50])

    # Quests
    from df_storyteller.context.quest_store import get_active_quests, get_completed_quests
    active_quests = get_active_quests(config, fortress_dir)
    completed_quests = get_completed_quests(config, fortress_dir)
    quest_lines = []
    for q in completed_quests[-3:]:
        quest_lines.append(f"- COMPLETED: {q.title} — {q.description}")
    for q in active_quests[:5]:
        quest_lines.append(f"- ONGOING: {q.title} — {q.description}")
    quest_text = "\n".join(quest_lines)

    # Deaths this season
    death_events = [e for e in recent_events if e.event_type == ET.DEATH]
    death_lines = []
    for e in death_events:
        d = e.data
        if hasattr(d, "victim"):
            death_lines.append(f"- {d.victim.name} ({getattr(d, 'cause', 'unknown')})")
    death_text = "\n".join(death_lines)

    # Author personality for voice
    author_dwarf = None
    for dwarf, _ in character_tracker.ranked_characters():
        short = dwarf.name.split(",")[0].strip()
        if short == author_name:
            author_dwarf = dwarf
            break

    personality_text = ""
    if author_dwarf and author_dwarf.personality:
        traits = [f.description for f in author_dwarf.personality.facets if f.is_notable and f.description]
        if traits:
            personality_text = f"Author personality: {'; '.join(traits[:5])}"

    # Generate all sections with one LLM call
    from df_storyteller.stories.base import create_provider
    from df_storyteller.stories.df_mechanics import DF_MECHANICS_COMPACT
    provider = create_provider(config)

    system_prompt = f"""You are {author_name}, a {author_prof or 'dwarf'} at {fortress_name}, writing this season's edition of the fortress gazette — a dwarven newspaper.
{personality_text}

Write in character as {author_name}. Your personality should color the writing — if you're grumpy, be sarcastic. If cheerful, be enthusiastic. If scholarly, be precise.

You must write EXACTLY these sections, each preceded by its header on its own line:

HERALD:
(2-3 paragraphs summarizing what happened at the fortress this season. Major events, changes, arrivals.)

MILITARY:
(1-2 paragraphs about combat, defense, military readiness. Skip if no combat occurred — write "All quiet on the ramparts." instead.)

GOSSIP:
(1-2 paragraphs of social gossip — who's talking to who, new friendships, complaints, drama. Written as rumor and hearsay.)

QUESTS:
(1-2 paragraphs about quest progress — what the fortress is working toward, what was achieved.)

OBITUARIES:
(Brief memorial for any who died this season. Skip if no deaths — write "No lives were lost this season, praise the gods." instead.)

Target length per section: {_gazette_section_length(config)} words. Write as a dwarven newspaper — witty, opinionated, in-character.
{DF_MECHANICS_COMPACT}"""

    user_prompt = f"""Write the gazette for {fortress_name}, {season.title()} of Year {year}. Population: {population}.

## Fortress State
{fortress_context}

## Recent Events
{chr(10).join(event_lines[-15:])}

## Combat This Season
{combat_text or 'No combat occurred.'}

## Social Chatter
{chat_text or 'The fortress was quiet — no notable conversations.'}

## Quest Activity
{quest_text or 'No active quests.'}

## Deaths This Season
{death_text or 'No deaths.'}

Write the full gazette now with all 5 section headers (HERALD:, MILITARY:, GOSSIP:, QUESTS:, OBITUARIES:)."""

    try:
        result = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.gazette_max_tokens,
            temperature=0.9,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Parse sections from the response
    sections = {"herald": "", "military": "", "gossip": "", "quests": "", "obituaries": ""}
    current_section = None
    current_lines: list[str] = []

    for line in result.split("\n"):
        line_upper = line.strip().upper().rstrip(":")
        if line_upper in ("HERALD", "THE FORTRESS HERALD"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "herald"
            current_lines = []
        elif line_upper in ("MILITARY", "MILITARY DISPATCHES"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "military"
            current_lines = []
        elif line_upper in ("GOSSIP", "QUARRY GOSSIP"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "gossip"
            current_lines = []
        elif line_upper in ("QUESTS", "QUEST BOARD"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "quests"
            current_lines = []
        elif line_upper in ("OBITUARIES", "OBITUARY"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "obituaries"
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    # If parsing failed (no sections found), put everything in herald
    if not any(sections.values()):
        sections["herald"] = result.strip()

    # Save gazette
    try:
        import json as _json
        from datetime import datetime as _dt
        gazette_path = fortress_dir / "gazette.json"
        existing = []
        if gazette_path.exists():
            try:
                existing = _json.loads(gazette_path.read_text(encoding="utf-8", errors="replace"))
            except (ValueError, OSError):
                existing = []
        # Replace existing for same season/year
        gazette_entry = {
            "year": year,
            "season": season,
            "author": author_name,
            "author_profession": author_prof,
            "sections": sections,
            "generated_at": _dt.now().isoformat(),
        }
        replaced = False
        for i, g in enumerate(existing):
            if g.get("year") == year and g.get("season") == season:
                existing[i] = gazette_entry
                replaced = True
                break
        if not replaced:
            existing.append(gazette_entry)
        gazette_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("Failed to save gazette to disk")

    return {"ok": True}


# ==================== Quests ====================


@app.get("/quests", response_class=HTMLResponse)
async def quests_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "quests", metadata)
    fortress_dir = _get_fortress_dir(config, metadata)

    from df_storyteller.context.quest_store import load_all_quests
    from df_storyteller.schema.quests import QuestStatus
    quests = load_all_quests(config, fortress_dir)

    active = [q for q in quests if q.status == QuestStatus.ACTIVE]
    completed = [q for q in quests if q.status == QuestStatus.COMPLETED]

    # Sort: priority first, then newest first
    active.sort(key=lambda q: (not q.priority, -q.created_at.timestamp()))
    completed.sort(key=lambda q: -q.created_at.timestamp())

    return templates.TemplateResponse(request=request, name="quests.html", context={
        **ctx, "active_quests": active, "completed_quests": completed,
    })


@app.post("/api/quests/generate")
async def api_generate_quests(request: Request):
    """Generate new AI quests based on fortress state."""
    config = _get_config()
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    count = min(int(data.get("count", 3)), 10)
    category = data.get("category", "")
    difficulty = data.get("difficulty", "")

    from df_storyteller.stories.quest_generator import generate_quests
    fortress_dir = _get_fortress_dir(config)
    quests = await generate_quests(config, count=count, category=category, difficulty=difficulty, output_dir=fortress_dir)
    return [q.model_dump(mode="json") for q in quests]


@app.post("/api/quests/{quest_id}/complete")
async def api_complete_quest(quest_id: str):
    """Stream a completion narrative for a quest."""
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)

    async def _stream() -> AsyncGenerator[str, None]:
        from df_storyteller.stories.quest_generator import generate_completion_narrative
        from df_storyteller.context.quest_store import load_all_quests, save_all_quests
        from df_storyteller.schema.quests import QuestStatus

        quests = load_all_quests(config, fortress_dir)
        quest = next((q for q in quests if q.id == quest_id), None)
        if not quest:
            yield "Quest not found."
            return

        try:
            narrative = await generate_completion_narrative(config, quest, fortress_dir)
        except Exception as e:
            logger.exception("Quest completion narrative failed")
            yield f"Error: {e}" if str(e) else "Error: generation failed. Check Settings and try again."
            return

        # Save completion
        from datetime import datetime
        quest.status = QuestStatus.COMPLETED
        quest.completed_at = datetime.now()
        quest.completion_narrative = narrative
        save_all_quests(config, quests, fortress_dir)

        # Stream word by word
        words = narrative.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)

    return StreamingResponse(_stream(), media_type="text/plain")


@app.post("/api/quests/{quest_id}/abandon")
async def api_abandon_quest(quest_id: str):
    from df_storyteller.context.quest_store import abandon_quest
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = abandon_quest(config, quest_id, fortress_dir)
    return {"ok": ok}


@app.post("/api/quests/{quest_id}/priority")
async def api_toggle_quest_priority(quest_id: str):
    from df_storyteller.context.quest_store import toggle_priority
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = toggle_priority(config, quest_id, fortress_dir)
    return {"ok": ok}


@app.delete("/api/quests/{quest_id}")
async def api_delete_quest(quest_id: str):
    from df_storyteller.context.quest_store import delete_quest
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = delete_quest(config, quest_id, fortress_dir)
    return {"ok": ok}


@app.get("/api/quests")
async def api_list_quests(status: str | None = None):
    from df_storyteller.context.quest_store import load_all_quests
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    quests = load_all_quests(config, fortress_dir)
    if status:
        quests = [q for q in quests if q.status.value == status]
    return [q.model_dump(mode="json") for q in quests]


@app.post("/api/quests/manual")
async def api_create_manual_quest(request: Request):
    """Create a player-written quest."""
    from df_storyteller.context.quest_store import add_quest
    from df_storyteller.schema.quests import Quest, QuestCategory, QuestDifficulty
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    if not title or not description:
        return JSONResponse({"error": "Title and description are required"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    try:
        category = QuestCategory(data.get("category", "exploration"))
        difficulty = QuestDifficulty(data.get("difficulty", "medium"))
    except ValueError:
        category = QuestCategory.EXPLORATION
        difficulty = QuestDifficulty.MEDIUM

    quest = Quest(
        title=title,
        description=description,
        category=category,
        difficulty=difficulty,
        game_year=metadata.get("year", 0),
        game_season=metadata.get("season", "spring"),
        context_snapshot="Player-created quest",
    )
    add_quest(config, quest, fortress_dir)
    return quest.model_dump(mode="json")


@app.post("/api/quests/{quest_id}/edit")
async def api_edit_quest(quest_id: str, request: Request):
    """Edit a quest's title and description."""
    from df_storyteller.context.quest_store import load_all_quests, save_all_quests
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    if not title or not description:
        return JSONResponse({"error": "Title and description are required"}, status_code=400)

    fortress_dir = _get_fortress_dir(config)
    quests = load_all_quests(config, fortress_dir)
    for q in quests:
        if q.id == quest_id:
            q.title = title
            q.description = description
            save_all_quests(config, quests, fortress_dir)
            return {"ok": True}
    return JSONResponse({"error": "Quest not found"}, status_code=404)


@app.post("/api/quests/{quest_id}/resolve")
async def api_resolve_quest(quest_id: str, request: Request):
    """Resolve a quest with a player-written comment (no AI)."""
    from df_storyteller.context.quest_store import complete_quest
    config = _get_config()
    comment = ""
    try:
        data = await request.json()
        comment = data.get("comment", "").strip()
    except Exception:
        pass

    fortress_dir = _get_fortress_dir(config)
    ok = complete_quest(config, quest_id, comment or "Quest resolved by player.", fortress_dir)
    return {"ok": ok}


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    config = _get_config()
    ctx = _base_context(config, "settings", None)

    # Find which legends file is loaded
    legends_file = ""
    if config.paths.df_install:
        df_dir = Path(config.paths.df_install)
        candidates = sorted(
            [f for f in df_dir.glob("*-legends.xml") if "legends_plus" not in f.name],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if candidates:
            legends_file = candidates[0].name

    return templates.TemplateResponse(request=request, name="settings.html", context={
        **ctx, "config": config, "saved": saved, "legends_file": legends_file,
    })


@app.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    config = _get_config()

    config.paths.df_install = form.get("df_install", config.paths.df_install)
    config.story.no_llm_mode = form.get("no_llm_mode") == "true"
    config.llm.provider = form.get("llm_provider", config.llm.provider)
    if form.get("api_key"):
        config.llm.api_key = form["api_key"]
    config.story.narrative_style = form.get("narrative_style", config.story.narrative_style)
    for field in ("chronicle_max_tokens", "biography_max_tokens", "saga_max_tokens", "chat_summary_max_tokens", "gazette_max_tokens", "quest_generation_max_tokens", "quest_narrative_max_tokens"):
        try:
            val = form.get(field)
            if val:
                setattr(config.story, field, int(val))
        except (ValueError, AttributeError):
            pass

    save_config(config)
    _invalidate_cache()
    return RedirectResponse("/settings?saved=true", status_code=303)


# ==================== Highlights API ====================


@app.get("/api/highlights")
async def api_highlights_list():
    """List all dwarf highlights."""
    from df_storyteller.context.highlights_store import load_all_highlights
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    highlights = load_all_highlights(config, output_dir=fortress_dir)
    return [h.model_dump() for h in highlights]


@app.post("/api/highlights")
async def api_highlights_set(request: Request):
    """Set or update a highlight on a dwarf."""
    from df_storyteller.context.highlights_store import set_highlight
    from df_storyteller.schema.highlights import DwarfHighlight
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    try:
        highlight = DwarfHighlight.model_validate(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    set_highlight(config, highlight, output_dir=fortress_dir)
    return {"ok": True}


@app.delete("/api/highlights/{unit_id}")
async def api_highlights_remove(unit_id: int):
    """Remove a highlight from a dwarf."""
    from df_storyteller.context.highlights_store import remove_highlight
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    removed = remove_highlight(config, unit_id, output_dir=fortress_dir)
    if not removed:
        return JSONResponse({"error": "No highlight found"}, status_code=404)
    return {"ok": True}


# ==================== Refresh ====================

@app.get("/api/refresh")
async def api_refresh():
    """Force-clear the cache and redirect back."""
    _invalidate_cache()
    return RedirectResponse("/", status_code=303)


# ==================== Lore Search API ====================


@app.get("/api/lore/search")
async def api_lore_search(q: str = ""):
    """Search across ALL legends data — returns matching items by category."""
    if not q or len(q) < 2:
        return {"results": []}

    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return {"results": []}

    legends = world_lore._legends
    query = q.lower()
    results: list[dict] = []
    MAX_PER_CATEGORY = 20

    # Check if any fortress dwarves match (link to character sheet)
    event_store, character_tracker, _, _ = _load_game_state_safe(config)
    for dwarf, _ in character_tracker.ranked_characters():
        from df_storyteller.context.character_tracker import normalize_name
        if query in normalize_name(dwarf.name):
            results.append({
                "category": "Fortress Dwarf",
                "name": dwarf.name,
                "detail": f"{dwarf.profession}, age {dwarf.age:.0f}",
                "link": f"/dwarves/{dwarf.unit_id}",
            })

    # Search civilizations
    count = 0
    for eid, civ in legends.civilizations.items():
        if count >= MAX_PER_CATEGORY:
            break
        if query in civ.name.lower() or query in civ.race.lower():
            race = civ.race.replace("_", " ").title() if civ.race else ""
            results.append({"category": "Civilization", "name": civ.name, "detail": race, "id": eid, "entity_type": "civilization", "link": f"/lore/civ/{eid}"})
            count += 1

    # Build set of HF IDs with assumed identities (don't reveal in search)
    hfs_with_identities: set[int] = set()
    for ident in legends.identities:
        hfid_str = ident.get("histfig_id")
        if hfid_str:
            try:
                hfs_with_identities.add(int(hfid_str))
            except (ValueError, TypeError):
                pass

    # Search historical figures — don't reveal assumed identities
    count = 0
    for hfid, hf in legends.historical_figures.items():
        if count >= MAX_PER_CATEGORY:
            break
        if query in hf.name.lower() or query in hf.race.lower():
            race = hf.race.replace("_", " ").title() if hf.race else ""
            detail = race
            if hf.spheres:
                detail += f" — spheres: {', '.join(hf.spheres)}"
            if hf.is_deity:
                detail = "Deity — " + detail
            if hf.birth_year and hf.birth_year > 0:
                detail += f" (born {hf.birth_year}"
                if hf.death_year and hf.death_year > 0:
                    detail += f", died {hf.death_year}"
                detail += ")"
            if hfid in hfs_with_identities:
                detail += " — this figure harbors a secret..."
            results.append({"category": "Figure", "name": hf.name, "detail": detail, "id": hfid, "entity_type": "figure", "link": f"/lore/figure/{hfid}"})
            count += 1

    # Search artifacts
    count = 0
    for aid, art in legends.artifacts.items():
        if count >= MAX_PER_CATEGORY:
            break
        searchable = f"{art.name} {art.item_type} {art.material}".lower()
        if query in searchable:
            detail_parts = []
            if art.item_type:
                detail_parts.append(art.item_type.replace("_", " "))
            if art.material:
                detail_parts.append(art.material)
            if art.creator_hf_id:
                holder = legends.get_figure(art.creator_hf_id)
                if holder:
                    detail_parts.append(f"held by {holder.name}")
            results.append({"category": "Artifact", "name": art.name, "detail": " — ".join(detail_parts), "id": aid, "entity_type": "artifact", "link": f"/lore/artifact/{aid}"})
            count += 1

    # Search sites
    count = 0
    for sid, site in legends.sites.items():
        if count >= MAX_PER_CATEGORY:
            break
        if query in site.name.lower() or query in site.site_type.lower():
            results.append({"category": "Site", "name": site.name, "detail": site.site_type, "id": sid, "entity_type": "site", "link": f"/lore/site/{sid}"})
            count += 1

    # Search written works
    count = 0
    for wc in legends.written_contents:
        if count >= MAX_PER_CATEGORY:
            break
        title = wc.get("title", "")
        if query in title.lower():
            wc_type = wc.get("type", "").replace("_", " ").title()
            author_id = wc.get("author")
            author_name = ""
            if author_id:
                try:
                    author = legends.get_figure(int(author_id))
                    if author:
                        author_name = author.name
                except (ValueError, TypeError):
                    pass
            detail = wc_type
            if author_name:
                detail += f" by {author_name}"
            results.append({"category": "Written Work", "name": title, "detail": detail, "id": wc.get("id", ""), "entity_type": "written_work"})
            count += 1

    # Search wars/battles
    count = 0
    for ec in legends.event_collections:
        if count >= MAX_PER_CATEGORY:
            break
        name = ec.get("name", "")
        if name and query in name.lower():
            ec_type = ec.get("type", "").replace("_", " ").title()
            results.append({"category": ec_type, "name": name, "detail": "", "id": ec.get("id", ""), "entity_type": "war"})
            count += 1

    return {"results": results}


@app.get("/api/lore/detail")
async def api_lore_detail(entity_type: str, entity_id: str):
    """Return structured detail for a lore entity (for hover tooltips)."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    try:
        eid = int(entity_id)
    except (ValueError, TypeError):
        eid = 0

    if entity_type == "figure":
        hf = legends.get_figure(eid)
        if not hf:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if hf.race:
            fields.append({"label": "Race", "value": hf.race.replace("_", " ").title()})
        if hf.hf_type:
            fields.append({"label": "Type", "value": hf.hf_type.replace("_", " ").title()})
        if hf.birth_year and hf.birth_year > 0:
            born = f"Year {hf.birth_year}"
            if hf.death_year and hf.death_year > 0:
                born += f" — died Year {hf.death_year}"
            fields.append({"label": "Born", "value": born})
        if hf.spheres:
            fields.append({"label": "Spheres", "value": ", ".join(hf.spheres)})
        if hf.associated_civ_id:
            civ = legends.get_civilization(hf.associated_civ_id)
            if civ:
                fields.append({"label": "Civilization", "value": civ.name})

        # Relationships from legends (uses precomputed index)
        from collections import Counter
        hfid_str = str(eid)
        rel_summaries = []
        for rel in legends.get_hf_relationships(eid):
            if rel.get("source_hf") == hfid_str:
                other = legends.get_figure(int(rel.get("target_hf", 0)))
                if other:
                    rel_summaries.append(f"{rel.get('relationship', '?')} of {other.name}")
            elif rel.get("target_hf") == hfid_str:
                other = legends.get_figure(int(rel.get("source_hf", 0)))
                if other:
                    rel_summaries.append(f"{rel.get('relationship', '?')} of {other.name}")
        if rel_summaries:
            fields.append({"label": "Relationships", "value": "; ".join(rel_summaries[:5])})

        # Event type breakdown + kill details (uses precomputed index)
        evt_types: Counter[str] = Counter()
        kill_victims: list[tuple[str, str]] = []  # (name, race)
        kill_races: Counter[str] = Counter()
        for evt in legends.get_hf_events(eid):
            evt_types[evt.get("type", "unknown")] += 1
            # Track kills where this figure is the slayer
            if evt.get("type") == "hf died" and evt.get("slayer_hfid") == hfid_str:
                victim = legends.get_figure(int(evt.get("hfid", 0))) if evt.get("hfid") else None
                if victim:
                    kill_victims.append((victim.name, victim.race.replace("_", " ").title() if victim.race else ""))
                    kill_races[victim.race.replace("_", " ").title() if victim.race else "Unknown"] += 1
        if evt_types:
            # Only show interesting event types, skip mundane ones
            readable_map = {
                "hf died": "kills",
                "hf simple battle event": "battles",
                "hf attacked site": "site attacks",
                "hf destroyed site": "site destructions",
                "creature devoured": "devoured victims",
                "item stolen": "thefts",
                "hf wounded": "wounds inflicted",
                "hf confronted": "confrontations",
                "artifact created": "artifacts created",
                "hf new pet": "tamed creatures",
                "assume identity": "assumed identities",
                "hf razed structure": "razed structures",
            }
            # Skip boring types: state changes, job changes, entity links, travel
            summary_parts = []
            for evt_type, count in evt_types.most_common(10):
                if evt_type in readable_map:
                    summary_parts.append(f"{count} {readable_map[evt_type]}")
                if len(summary_parts) >= 4:
                    break
            total = sum(evt_types.values())
            if summary_parts:
                fields.append({"label": "Notable Events", "value": ", ".join(summary_parts)})
            else:
                fields.append({"label": "Historical Events", "value": str(total)})

        # Kill details
        if kill_victims:
            race_summary = ", ".join(f"{count} {race}" for race, count in kill_races.most_common(4))
            fields.append({"label": "Kill Count", "value": f"{len(kill_victims)} ({race_summary})"})
            notable_kills = [f"{name} ({race})" for name, race in kill_victims[:3]]
            fields.append({"label": "Notable Kills", "value": "; ".join(notable_kills)})

        if hf.notable_deeds:
            fields.append({"label": "Deeds", "value": "; ".join(hf.notable_deeds[:3])})
        return {"entity_type": "figure", "name": hf.name, "fields": fields}

    elif entity_type == "civilization":
        civ = legends.get_civilization(eid)
        if not civ:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if civ.race:
            fields.append({"label": "Race", "value": civ.race.replace("_", " ").title()})
        if civ.sites:
            site_names = []
            for sid in civ.sites[:5]:
                site = legends.get_site(sid)
                if site:
                    site_names.append(f"{site.name} ({site.site_type})" if site.site_type else site.name)
            if site_names:
                suffix = f" (+{len(civ.sites) - 5} more)" if len(civ.sites) > 5 else ""
                fields.append({"label": "Sites", "value": ", ".join(site_names) + suffix})
        wars = legends.get_wars_involving(eid)
        if wars:
            war_names = [w.get("name", "Unknown") for w in wars[:4]]
            suffix = f" (+{len(wars) - 4} more)" if len(wars) > 4 else ""
            fields.append({"label": "Wars", "value": "; ".join(war_names) + suffix})
        if civ.leader_hf_ids:
            leader_names = []
            for lid in civ.leader_hf_ids[:3]:
                lhf = legends.get_figure(lid)
                if lhf:
                    leader_names.append(lhf.name)
            if leader_names:
                fields.append({"label": "Leaders", "value": ", ".join(leader_names)})
        return {"entity_type": "civilization", "name": civ.name, "fields": fields}

    elif entity_type == "artifact":
        art = legends.get_artifact(eid)
        if not art:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if art.item_type:
            fields.append({"label": "Type", "value": art.item_type.replace("_", " ")})
        if art.material:
            fields.append({"label": "Material", "value": art.material})
        if art.creator_hf_id:
            creator = legends.get_figure(art.creator_hf_id)
            if creator:
                creator_detail = creator.name
                if creator.race:
                    creator_detail += f" ({creator.race.replace('_', ' ').title()})"
                fields.append({"label": "Creator", "value": creator_detail})
        if art.site_id:
            site = legends.get_site(art.site_id)
            if site:
                fields.append({"label": "Location", "value": f"{site.name} ({site.site_type})" if site.site_type else site.name})
        if art.description:
            fields.append({"label": "Description", "value": art.description[:300]})
        return {"entity_type": "artifact", "name": art.name, "fields": fields}

    elif entity_type == "site":
        site = legends.get_site(eid)
        if not site:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if site.site_type:
            fields.append({"label": "Type", "value": site.site_type.replace("_", " ").title()})
        if site.owner_civ_id:
            owner = legends.get_civilization(site.owner_civ_id)
            if owner:
                race = f" ({owner.race.replace('_', ' ').title()})" if owner.race else ""
                fields.append({"label": "Owner", "value": f"{owner.name}{race}"})
        if site.coordinates:
            fields.append({"label": "Coordinates", "value": f"({site.coordinates[0]}, {site.coordinates[1]})"})
        # Notable events at this site (precomputed index)
        site_evt_types = legends.get_site_event_types(eid)
        if site_evt_types:
            interesting = {"hf died": "deaths", "hf attacked site": "attacks", "artifact created": "artifacts created",
                           "hf destroyed site": "destructions", "item stolen": "thefts", "creature devoured": "devourings"}
            parts = []
            for et, label in interesting.items():
                if et in site_evt_types:
                    parts.append(f"{site_evt_types[et]} {label}")
            if parts:
                fields.append({"label": "Notable Events", "value": ", ".join(parts[:4])})
            total = sum(site_evt_types.values())
            fields.append({"label": "Total Events", "value": str(total)})
        return {"entity_type": "site", "name": site.name, "fields": fields}

    elif entity_type in ("war", "battle"):
        ec = legends.get_event_collection(entity_id)
        if not ec:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        sy = ec.get("start_year", "")
        ey = ec.get("end_year", "")
        if sy:
            year_str = f"Year {sy}" + (f"–{ey}" if ey and ey != sy else "")
            fields.append({"label": "Years", "value": year_str})
        for role, key in [("Aggressor", "aggressor_ent_id"), ("Defender", "defender_ent_id")]:
            ids = ec.get(key, [])
            if isinstance(ids, str):
                ids = [ids]
            names = []
            for eid_str in ids:
                try:
                    c = legends.get_civilization(int(eid_str))
                    if c:
                        names.append(f"{c.name} ({c.race.replace('_', ' ').title()})" if c.race else c.name)
                except (ValueError, TypeError):
                    pass
            if names:
                fields.append({"label": role, "value": ", ".join(names)})
        # For wars: list battles and total casualties
        ec_type = ec.get("type", "")
        if ec_type == "war":
            war_id = ec.get("id")
            war_battles = [b for b in legends.battles if b.get("war_eventcol") == war_id]
            if war_battles:
                battle_summaries = []
                total_atk_d = 0
                total_def_d = 0
                for b in war_battles:
                    outcome_str = b.get("outcome", "").replace("_", " ")
                    battle_summaries.append(f"{b.get('name', '?')} ({outcome_str})")
                    ad = b.get("attacking_squad_deaths", [])
                    dd = b.get("defending_squad_deaths", [])
                    if isinstance(ad, list):
                        total_atk_d += sum(int(d) for d in ad if str(d).isdigit())
                    if isinstance(dd, list):
                        total_def_d += sum(int(d) for d in dd if str(d).isdigit())
                fields.append({"label": "Battles", "value": "; ".join(battle_summaries[:5])
                               + (f" (+{len(war_battles) - 5} more)" if len(war_battles) > 5 else "")})
                if total_atk_d or total_def_d:
                    fields.append({"label": "Total Casualties", "value": f"Attackers: {total_atk_d}, Defenders: {total_def_d}"})

        # Outcome for individual battles
        outcome = ec.get("outcome", "")
        if outcome and ec_type != "war":
            fields.append({"label": "Outcome", "value": outcome.replace("_", " ").title()})
        # Site where it happened
        site_id = ec.get("site_id")
        if site_id and site_id != "-1":
            site = legends.get_site(int(site_id))
            if site:
                fields.append({"label": "Location", "value": site.name})
        # Squad composition for battles
        atk_races = ec.get("attacking_squad_race", [])
        def_races = ec.get("defending_squad_race", [])
        if isinstance(atk_races, list) and atk_races:
            from collections import Counter as RCounter
            atk_summary = RCounter(r.replace("_", " ").title() for r in atk_races)
            fields.append({"label": "Attacking Forces", "value": ", ".join(f"{c} {r}" for r, c in atk_summary.most_common(4))})
        if isinstance(def_races, list) and def_races:
            from collections import Counter as RCounter2
            def_summary = RCounter2(r.replace("_", " ").title() for r in def_races)
            fields.append({"label": "Defending Forces", "value": ", ".join(f"{c} {r}" for r, c in def_summary.most_common(4))})
        # Casualty totals
        atk_deaths = ec.get("attacking_squad_deaths", [])
        def_deaths = ec.get("defending_squad_deaths", [])
        if isinstance(atk_deaths, list):
            total_atk = sum(int(d) for d in atk_deaths if d.isdigit())
            total_def = sum(int(d) for d in def_deaths if d.isdigit()) if isinstance(def_deaths, list) else 0
            if total_atk or total_def:
                fields.append({"label": "Casualties", "value": f"Attackers: {total_atk}, Defenders: {total_def}"})
        # Notable combatants
        atk_hfids = ec.get("attacking_hfid", [])
        def_hfids = ec.get("defending_hfid", [])
        if isinstance(atk_hfids, list) and atk_hfids:
            combatant_names = []
            for hid in atk_hfids[:3]:
                h = legends.get_figure(int(hid))
                if h:
                    combatant_names.append(h.name)
            if combatant_names:
                suffix = f" (+{len(atk_hfids) - 3} more)" if len(atk_hfids) > 3 else ""
                fields.append({"label": "Notable Attackers", "value": ", ".join(combatant_names) + suffix})
        if isinstance(def_hfids, list) and def_hfids:
            combatant_names = []
            for hid in def_hfids[:3]:
                h = legends.get_figure(int(hid))
                if h:
                    combatant_names.append(h.name)
            if combatant_names:
                suffix = f" (+{len(def_hfids) - 3} more)" if len(def_hfids) > 3 else ""
                fields.append({"label": "Notable Defenders", "value": ", ".join(combatant_names) + suffix})
        return {"entity_type": entity_type, "name": ec.get("name", "Unknown"), "fields": fields}

    elif entity_type == "written_work":
        for wc in legends.written_contents:
            if str(wc.get("id", "")) == str(entity_id):
                fields = []
                wc_type = wc.get("type", "").replace("_", " ").title()
                if wc_type:
                    fields.append({"label": "Form", "value": wc_type})
                style = wc.get("style", "").split(":")[0].strip().title()
                if style:
                    fields.append({"label": "Style", "value": style})
                author_id = wc.get("author")
                if author_id:
                    try:
                        author = legends.get_figure(int(author_id))
                        if author:
                            author_detail = author.name
                            if author.race:
                                author_detail += f" ({author.race.replace('_', ' ').title()})"
                            if author.associated_civ_id:
                                aciv = legends.get_civilization(author.associated_civ_id)
                                if aciv:
                                    author_detail += f" of {aciv.name}"
                            fields.append({"label": "Author", "value": author_detail})
                    except (ValueError, TypeError):
                        pass
                pages = wc.get("page_end", "")
                if pages and pages != "1":
                    fields.append({"label": "Pages", "value": pages})
                # References to historical events/figures that inspired the work
                ref = wc.get("reference", "")
                if ref and isinstance(ref, str) and ref.strip():
                    fields.append({"label": "Reference", "value": ref.strip()[:200]})
                return {"entity_type": "written_work", "name": wc.get("title", "Untitled"), "fields": fields}
        return JSONResponse({"error": "not_found"}, status_code=404)

    elif entity_type == "geography":
        # Search across mountains, rivers, landmasses by ID string
        for peak in legends.mountain_peaks:
            if str(peak.get("id", "")) == str(entity_id):
                fields = [{"label": "Type", "value": "Mountain Peak"}]
                height = peak.get("height", "")
                if height:
                    fields.append({"label": "Height", "value": f"{height}"})
                is_volcano = peak.get("is_volcano")
                if is_volcano:
                    fields.append({"label": "Volcano", "value": "Yes"})
                coords = peak.get("coords", "")
                if coords:
                    fields.append({"label": "Coordinates", "value": coords})
                return {"entity_type": "geography", "name": peak.get("name", ""), "fields": fields}
        for land in legends.landmasses:
            if str(land.get("id", "")) == str(entity_id):
                fields = [{"label": "Type", "value": "Landmass"}]
                c1 = land.get("coord_1", "")
                c2 = land.get("coord_2", "")
                if c1 and c2:
                    fields.append({"label": "Extent", "value": f"{c1} to {c2}"})
                return {"entity_type": "geography", "name": land.get("name", ""), "fields": fields}
        # Rivers don't have IDs, skip
        return JSONResponse({"error": "not_found"}, status_code=404)

    return JSONResponse({"error": "invalid_type"}, status_code=400)


# ==================== Lore Pins API ====================


@app.get("/api/lore/pins")
async def api_list_pins():
    """List all lore pins."""
    from df_storyteller.context.lore_pins import load_pins
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    return load_pins(fortress_dir)


@app.post("/api/lore/pins")
async def api_add_pin(request: Request):
    """Add a lore pin."""
    from df_storyteller.context.lore_pins import add_pin
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    data = await request.json()
    pin = add_pin(
        fortress_dir,
        entity_type=data.get("entity_type", ""),
        entity_id=data.get("entity_id", ""),
        name=data.get("name", ""),
        note=data.get("note", ""),
    )
    return pin


@app.delete("/api/lore/pins/all")
async def api_clear_all_pins():
    """Remove all lore pins."""
    from df_storyteller.context.lore_pins import save_pins
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    save_pins(fortress_dir, [])
    return {"status": "ok"}


@app.delete("/api/lore/pins/{pin_id}")
async def api_remove_pin(pin_id: str):
    """Remove a lore pin."""
    from df_storyteller.context.lore_pins import remove_pin
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    if remove_pin(fortress_dir, pin_id):
        return {"status": "ok"}
    return JSONResponse({"error": "not_found"}, status_code=404)


@app.put("/api/lore/pins/{pin_id}")
async def api_update_pin(pin_id: str, request: Request):
    """Update a pin's note."""
    from df_storyteller.context.lore_pins import update_pin_note
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    data = await request.json()
    if update_pin_note(fortress_dir, pin_id, data.get("note", "")):
        return {"status": "ok"}
    return JSONResponse({"error": "not_found"}, status_code=404)


# ==================== Notes API ====================


@app.get("/api/notes")
async def api_list_notes(target_type: str | None = None, target_id: int | None = None):
    from df_storyteller.context.notes_store import load_all_notes
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    notes = load_all_notes(config, fortress_dir)
    if target_type:
        notes = [n for n in notes if n.target_type == target_type]
    if target_id is not None:
        notes = [n for n in notes if n.target_id == target_id]
    return [n.model_dump(mode="json") for n in notes]


@app.post("/api/notes")
async def api_create_note(request: Request):
    from df_storyteller.context.notes_store import add_note
    from df_storyteller.schema.notes import PlayerNote, NoteTag
    config = _get_config()
    data = await request.json()

    # Get current game time from latest snapshot metadata
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    note = PlayerNote(
        tag=NoteTag(data["tag"]),
        text=data["text"],
        target_type=data.get("target_type", "fortress"),
        target_id=data.get("target_id"),
        game_year=metadata.get("year", 0),
        game_season=metadata.get("season", ""),
    )
    add_note(config, note, fortress_dir)
    return note.model_dump(mode="json")


@app.post("/api/notes/{note_id}/resolve")
async def api_resolve_note(note_id: str):
    from df_storyteller.context.notes_store import resolve_note
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = resolve_note(config, note_id, fortress_dir)
    return {"ok": ok}


@app.delete("/api/notes/{note_id}")
async def api_delete_note(note_id: str):
    from df_storyteller.context.notes_store import delete_note
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = delete_note(config, note_id, fortress_dir)
    return {"ok": ok}


# ==================== Story Generation API ====================


@app.post("/api/chronicle/generate")
async def api_generate_chronicle(request: Request):
    """Stream a chronicle entry."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass
    return StreamingResponse(
        _stream_chronicle(config, one_time),
        media_type="text/plain",
    )


async def _stream_chronicle(config: AppConfig, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.chronicle import generate_chronicle
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_chronicle(config, None, one_time_context=one_time_context, output_dir=fortress_dir)
        # Simulate streaming by yielding in chunks
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Generation failed")
        yield "Error: generation failed. Check server logs for details."


# ==================== Manual Writing APIs ====================


@app.post("/api/chronicle/manual")
async def api_chronicle_manual(request: Request):
    """Save a player-written chronicle entry."""
    from df_storyteller.output.journal import append_to_journal
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    season = data.get("season", metadata.get("season", "spring"))
    year = data.get("year", metadata.get("year", 0))
    fortress_dir = _get_fortress_dir(config, metadata)

    # Mark as manual so the UI can distinguish from AI entries
    marked_text = f"<!-- source:manual -->\n{text}"
    append_to_journal(config, marked_text, int(year), season, output_dir=fortress_dir)

    return {"ok": True, "season": season, "year": int(year)}


@app.post("/api/bio/{unit_id}/manual")
async def api_bio_manual(unit_id: int, request: Request):
    """Save a player-written biography entry."""
    from df_storyteller.stories.biography import _save_biography_entry
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    fortress_dir = _get_fortress_dir(config, metadata)

    entry = {
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "text": text,
        "profession": dwarf.profession if dwarf else "",
        "stress_category": dwarf.stress_category if dwarf else 0,
        "is_manual": True,
    }
    if data.get("is_diary"):
        entry["is_diary"] = True

    _save_biography_entry(config, unit_id, entry, output_dir=fortress_dir)
    return {"ok": True}


@app.post("/api/diary/{unit_id}/manual")
async def api_diary_manual(unit_id: int, request: Request):
    """Save a player-written diary entry."""
    from df_storyteller.stories.biography import _save_biography_entry
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    fortress_dir = _get_fortress_dir(config, metadata)

    _save_biography_entry(config, unit_id, {
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "text": text,
        "profession": dwarf.profession if dwarf else "",
        "stress_category": dwarf.stress_category if dwarf else 0,
        "is_diary": True,
        "is_manual": True,
    }, output_dir=fortress_dir)
    return {"ok": True}


@app.post("/api/saga/manual")
async def api_saga_manual(request: Request):
    """Save a player-written saga entry."""
    import json as _json
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    saga_path = fortress_dir / "saga.json"

    existing = []
    if saga_path.exists():
        try:
            existing = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            pass

    existing.append({
        "text": text,
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "is_manual": True,
    })
    saga_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@app.post("/api/gazette/manual")
async def api_gazette_manual(request: Request):
    """Save a player-written gazette."""
    import json as _json
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    gazette_path = fortress_dir / "gazette.json"

    season = metadata.get("season", "spring")
    year = metadata.get("year", 0)

    gazette = {
        "season": season,
        "year": year,
        "author": "The Player",
        "sections": {
            "herald": data.get("herald", ""),
            "military": data.get("military", ""),
            "gossip": data.get("gossip", ""),
            "quests": data.get("quests", ""),
            "obituaries": data.get("obituaries", ""),
        },
        "is_manual": True,
    }

    # Load existing gazettes and append/replace for this season
    existing = []
    if gazette_path.exists():
        try:
            existing = _json.loads(gazette_path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            pass

    # Replace gazette for same season/year if exists
    existing = [g for g in existing if not (g.get("season") == season and g.get("year") == year)]
    existing.append(gazette)
    gazette_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@app.post("/api/bio/{unit_id}")
async def api_generate_bio(unit_id: int, request: Request):
    """Stream a biography."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass

    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return StreamingResponse(iter(["Dwarf not found."]), media_type="text/plain")

    return StreamingResponse(
        _stream_bio(config, dwarf.name, one_time),
        media_type="text/plain",
    )


async def _stream_bio(config: AppConfig, dwarf_name: str, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.biography import generate_biography
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_biography(config, dwarf_name, one_time_context=one_time_context, output_dir=fortress_dir)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Generation failed")
        yield "Error: generation failed. Check server logs for details."


@app.post("/api/eulogy/{unit_id}")
async def api_generate_eulogy(unit_id: int, request: Request):
    """Stream a death eulogy for a fallen dwarf."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass

    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return StreamingResponse(iter(["Dwarf not found."]), media_type="text/plain")

    return StreamingResponse(
        _stream_eulogy(config, dwarf.name, one_time),
        media_type="text/plain",
    )


async def _stream_eulogy(config: AppConfig, dwarf_name: str, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.biography import generate_eulogy
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_eulogy(config, dwarf_name, one_time_context=one_time_context, output_dir=fortress_dir)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Eulogy generation failed")
        yield "Error: generation failed. Check server logs for details."


@app.post("/api/diary/{unit_id}")
async def api_generate_diary(unit_id: int, request: Request):
    """Stream a first-person diary entry for a dwarf."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass

    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return StreamingResponse(iter(["Dwarf not found."]), media_type="text/plain")

    return StreamingResponse(
        _stream_diary(config, dwarf.name, one_time),
        media_type="text/plain",
    )


async def _stream_diary(config: AppConfig, dwarf_name: str, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.biography import generate_diary
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_diary(config, dwarf_name, one_time_context=one_time_context, output_dir=fortress_dir)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Diary generation failed")
        yield "Error: generation failed. Check server logs for details."


@app.post("/api/saga/generate")
async def api_generate_saga():
    """Stream a saga."""
    config = _get_config()
    return StreamingResponse(
        _stream_saga(config),
        media_type="text/plain",
    )


async def _stream_saga(config: AppConfig) -> AsyncGenerator[str, None]:
    from df_storyteller.stories.saga import generate_saga
    try:
        result = await generate_saga(config, "full")

        # Save saga to per-fortress directory
        try:
            _, _, _, metadata = _load_game_state_safe(config)
            fortress_dir = _get_fortress_dir(config, metadata)
            import json as _json
            saga_path = fortress_dir / "saga.json"
            existing = []
            if saga_path.exists():
                try:
                    existing = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
                except (ValueError, OSError):
                    existing = []
            from datetime import datetime as _dt
            existing.append({
                "text": result,
                "year": metadata.get("year", 0),
                "season": metadata.get("season", ""),
                "generated_at": _dt.now().isoformat(),
            })
            saga_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.warning("Failed to save saga to disk")

        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Generation failed")
        yield "Error: generation failed. Check server logs for details."


@app.get("/api/worlds")
async def api_list_worlds():
    config = _get_config()
    return {"worlds": _get_worlds(config), "active": _get_active_world(config)}


@app.post("/api/worlds/switch")
async def api_switch_world(request: Request):
    global _active_world
    data = await request.json()
    world = data.get("world", "")
    config = _get_config()
    if world and _safe_watch_dir(config, world) is None:
        return {"ok": False, "error": "Invalid world name"}
    _active_world = world
    _invalidate_cache()
    return {"ok": True, "active": _active_world}


# ==================== WebSocket ====================


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Live event feed via WebSocket. Polls for new JSON files in the event dir."""
    await websocket.accept()
    _event_subscribers.append(websocket)
    try:
        config = _get_config()
        active_world = _get_active_world(config)
        watch_dir = _safe_watch_dir(config, active_world)

        # Send initial status
        if watch_dir and watch_dir.exists():
            await websocket.send_json({"type": "status", "description": f"Watching {active_world} for events..."})
        else:
            await websocket.send_json({"type": "status", "description": "No event directory found. Run storyteller-begin in DFHack."})

        seen_files: set[str] = set()
        if watch_dir and watch_dir.exists():
            seen_files = {f.name for f in watch_dir.glob("*.json")}

        while True:
            # Check for client disconnect by trying to receive with timeout
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except asyncio.TimeoutError:
                pass  # Normal — no message from client, just keep polling

            if not watch_dir or not watch_dir.exists():
                continue

            current_files = {f.name for f in watch_dir.glob("*.json")}
            new_files = current_files - seen_files
            seen_files = current_files

            for fname in sorted(new_files):
                if fname.startswith("snapshot_"):
                    continue
                fpath = watch_dir / fname
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        data = json.load(f)
                    from df_storyteller.ingestion.dfhack_json_parser import parse_dfhack_event
                    from df_storyteller.context.context_builder import _format_event
                    event = parse_dfhack_event(data)
                    desc = _format_event(event)
                    desc = re.sub(r"^\[.*?\]\s*", "", desc)
                    await websocket.send_json({
                        "type": event.event_type.value,
                        "year": event.game_year,
                        "season": event.season.value,
                        "description": desc,
                    })
                except Exception:
                    pass

    except (WebSocketDisconnect, Exception):
        if websocket in _event_subscribers:
            _event_subscribers.remove(websocket)


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
