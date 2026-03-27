"""FastAPI web application for df-storyteller."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
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

app = FastAPI(title="df-storyteller")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory state
_active_world: str | None = None
_event_subscribers: list[WebSocket] = []
_cached_state: tuple | None = None  # (cache_key, (event_store, char_tracker, world_lore, metadata))
_cache_time: float = 0
_CACHE_TTL: float = 300  # 5 minutes
_legends_preloaded: bool = False


def _get_config() -> AppConfig:
    return load_config()


@app.on_event("startup")
async def preload_legends():
    """Preload legends data in background at server startup so Lore tab is instant."""
    import threading

    def _bg_load():
        global _legends_preloaded
        import logging
        log = logging.getLogger(__name__)
        log.info("Preloading legends data in background...")
        try:
            config = _get_config()
            _load_game_state_safe(config, skip_legends=False)
            _legends_preloaded = True
            log.info("Legends data preloaded successfully.")
        except Exception as e:
            log.warning("Legends preload failed: %s", e)

    threading.Thread(target=_bg_load, daemon=True).start()


def _get_worlds(config: AppConfig) -> list[str]:
    """List available world subfolders."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return []
    return sorted(
        [d.name for d in base.iterdir() if d.is_dir() and d.name != "processed"],
        key=lambda n: (Path(config.paths.event_dir) / n).stat().st_mtime,
        reverse=True,
    )


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
    """Get modification time of the newest snapshot file."""
    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return 0
    world_dirs = [d for d in base.iterdir() if d.is_dir() and d.name != "processed"]
    if not world_dirs:
        return 0
    world_dir = max(world_dirs, key=lambda d: d.stat().st_mtime)
    snapshots = list(world_dir.glob("snapshot_*.json"))
    if not snapshots:
        return 0
    return max(s.stat().st_mtime for s in snapshots)


def _load_game_state_safe(config: AppConfig, skip_legends: bool = True):
    """Load game state with caching.

    Auto-invalidates when a new snapshot is detected.
    skip_legends=True (default) makes page loads fast by not parsing XML.
    Only set skip_legends=False for Lore tab and story generation.
    """
    import time
    global _cached_state, _cache_time

    cache_key = "with_legends" if not skip_legends else "no_legends"

    now = time.time()
    cache_valid = (
        _cached_state
        and _cached_state[0] == cache_key
        and (now - _cache_time) < _CACHE_TTL
    )

    # Auto-invalidate if a newer snapshot exists than when we cached
    if cache_valid:
        newest = _get_newest_snapshot_time(config)
        if newest > _cache_time:
            cache_valid = False

    if cache_valid:
        return _cached_state[1]

    try:
        result = load_game_state(config, skip_legends=skip_legends)
        _cached_state = (cache_key, result)
        _cache_time = now
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load game state: %s", e)
        return _empty_state()


def _invalidate_cache():
    """Clear the cache (call when world switches or settings change)."""
    global _cached_state, _cache_time
    _cached_state = None
    _cache_time = 0


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
    if _cache_time > 0:
        age = int(_time.time() - _cache_time)
        if age < 60:
            last_updated = f"{age}s ago"
        elif age < 3600:
            last_updated = f"{age // 60}m ago"
        else:
            last_updated = f"{age // 3600}h ago"

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
    }


def _linkify_dwarf_names(text: str, dwarf_map: dict[str, int]) -> str:
    """Replace dwarf names in text with links to their character sheets.

    dwarf_map: {name_fragment: unit_id} — maps various name forms to unit IDs.
    Longest names are matched first to avoid partial matches.
    """
    if not dwarf_map:
        return text

    # Sort by length descending so longer names match first
    # (e.g. "Atir Agamost" matches before "Atir")
    sorted_names = sorted(dwarf_map.keys(), key=len, reverse=True)

    for name in sorted_names:
        if name not in text:
            continue
        unit_id = dwarf_map[name]
        link = f'<a href="/dwarves/{unit_id}" class="dwarf-link">{name}</a>'
        text = text.replace(name, link)

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


def _parse_journal(config: AppConfig) -> list[dict]:
    """Parse the fortress journal markdown into entries."""
    journal_path = Path(config.paths.output_dir) / "fortress_journal.md"
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
            entries.append({
                "header": header,
                "text": _markdown_to_html(body),
            })

    return entries


# ==================== Page Routes ====================


@app.get("/", response_class=HTMLResponse)
async def chronicle_page(request: Request):
    config = _get_config()
    _, character_tracker, _, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "chronicle", metadata)
    entries = _parse_journal(config)

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
    already_written = has_entry_for(config, current_season, current_year) if current_season and current_year else False

    # Load fortress-wide notes
    from df_storyteller.context.notes_store import load_all_notes
    all_notes = load_all_notes(config)
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
        })

    return templates.TemplateResponse(request=request, name="dwarves.html", context={
        **ctx, "dwarves": dwarves,
    })


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
        top = sorted(dwarf.skills, key=lambda s: s.experience, reverse=True)[:8]
        for s in top:
            skills.append(f"{_skill_level_name(s.level)} {_resolve_skill_name(s.name)}")

    relationships = [
        {"type": r.relationship_type, "name": r.target_name}
        for r in dwarf.relationships
    ]

    dwarf_data = {
        "unit_id": dwarf.unit_id,
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

    # Load biography history (dated entries) with name hotlinks
    from df_storyteller.stories.biography import load_biography_history
    bio_history = load_biography_history(config, dwarf.unit_id)
    name_map = _build_dwarf_name_map(character_tracker)
    for entry in bio_history:
        if entry.get("text"):
            entry["text"] = _linkify_dwarf_names(
                entry["text"].replace("\n", "<br>"), name_map
            )
    dwarf_data["bio_entries"] = bio_history

    # Load notes for this dwarf
    from df_storyteller.context.notes_store import get_notes_for_dwarf
    from df_storyteller.schema.notes import TAG_DESCRIPTIONS
    dwarf_notes = get_notes_for_dwarf(config, unit_id)
    # Include resolved notes too for display
    from df_storyteller.context.notes_store import load_all_notes
    all_dwarf_notes = [
        n for n in load_all_notes(config)
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
    events = []
    for event in reversed(event_store.recent_events(100)):
        desc = _format_event(event)
        # Strip the [Season Year] prefix — the UI shows that separately
        desc = re.sub(r"^\[.*?\]\s*", "", desc)
        events.append({
            "type": event.event_type.value,
            "year": event.game_year,
            "season": event.season.value,
            "description": desc,
        })

    # Linkify dwarf names in event descriptions
    name_map = _build_dwarf_name_map(character_tracker)
    for event in events:
        event["description"] = _linkify_dwarf_names(event["description"], name_map)

    return templates.TemplateResponse(request=request, name="events.html", context={
        **ctx, "events": events,
    })


@app.get("/lore", response_class=HTMLResponse)
async def lore_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    civilizations = []
    wars = []
    figures = []
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
            sub_entities = []
            child_ids = getattr(civ, '_child_ids', [])
            for child_id in child_ids:
                child_civ = legends.get_civilization(child_id)
                if child_civ and child_civ.name:
                    child_type = getattr(child_civ, '_entity_type', '')
                    if child_type not in ('civilization', 'sitegovernment', ''):
                        # Enrich with deity/profession details
                        detail = f"{child_civ.name} ({child_type}"
                        worship_id = getattr(child_civ, '_worship_id', None)
                        profession = getattr(child_civ, '_profession', '')
                        if worship_id:
                            deity = legends.get_figure(worship_id)
                            if deity:
                                spheres = ', '.join(deity.spheres) if deity.spheres else ''
                                detail += f" — deity: {deity.name}"
                                if spheres:
                                    detail += f", spheres: {spheres}"
                        if profession:
                            detail += f" — {profession}"
                        detail += ")"
                        sub_entities.append(detail)

            race_display = civ.race.replace('_', ' ').title() if civ.race else ''
            civilizations.append({
                "name": civ.name,
                "race": race_display,
                "details": ". ".join(details_parts) if details_parts else "",
                "sub_entities": sub_entities,
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
                    "name": ec.get("name", "Unknown conflict"),
                    "details": " vs ".join(details_parts) if details_parts else "",
                    "years": year_range,
                })

        # Battles — named conflicts with outcomes
        battles = []
        for battle in legends.battles[:30]:
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
            battles.append({"name": name, "details": details, "year": year})

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
        )[:50]

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
                "title": title,
                "details": " — ".join(details_parts) if details_parts else "",
            })

        # Relationships (friendships, rivalries, romances)
        rel_counts: dict[str, int] = {}
        for rel in legends.relationships:
            rtype = rel.get("relationship", "unknown")
            rel_counts[rtype] = rel_counts.get(rtype, 0) + 1
        # Show sample relationships
        for rel in legends.relationships:
            source_id = rel.get("source_hf")
            target_id = rel.get("target_hf")
            rtype = rel.get("relationship", "")
            year = rel.get("year", "")
            source_name = ""
            target_name = ""
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
                relationships.append({
                    "description": f"{source_name} — {rtype} — {target_name}",
                    "year": year,
                })

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
            geography.append({"name": name, "type": "peak", "details": details})

        for land in legends.landmasses:
            geography.append({"name": land.get("name", ""), "type": "landmass", "details": "Landmass"})

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
                    pciv_figures.append({"name": hf.name, "race": race, "description": details})

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
                    pciv_artifacts.append({"name": art.name, "details": " — ".join(details_parts)})

            race_display = pciv.race.replace('_', ' ').title() if pciv.race else ''
            sub_ents = []
            for child_id in getattr(pciv, '_child_ids', []):
                child_civ = legends.get_civilization(child_id)
                if child_civ and child_civ.name:
                    child_type = getattr(child_civ, '_entity_type', '')
                    if child_type not in ('civilization', 'sitegovernment', ''):
                        detail = f"{child_civ.name} ({child_type}"
                        worship_id = getattr(child_civ, '_worship_id', None)
                        profession = getattr(child_civ, '_profession', '')
                        if worship_id:
                            deity = legends.get_figure(worship_id)
                            if deity:
                                spheres = ', '.join(deity.spheres) if deity.spheres else ''
                                detail += f" — deity: {deity.name}"
                                if spheres:
                                    detail += f", spheres: {spheres}"
                        if profession:
                            detail += f" — {profession}"
                        detail += ")"
                        sub_ents.append(detail)

            player_civ_data = {
                "name": pciv.name,
                "race": race_display,
                "details": "",
                "sub_entities": sub_ents[:15],
                "figures": pciv_figures[:20],
                "artifacts": pciv_artifacts[:20],
            }

    # Apply sensible limits to "other" sections (search reveals all)
    return templates.TemplateResponse(request=request, name="lore.html", context={
        **ctx,
        "lore_loaded": world_lore.is_loaded,
        "player_civ": player_civ_data,
        "eras": eras if world_lore.is_loaded and world_lore._legends else [],
        "civilizations": civilizations[:20],
        "wars": wars[:20],
        "battles": battles,
        "figures": figures[:30],
        "artifacts": artifacts[:30],
        "written_works": written_works[:30],
        "relationships": relationships[:30],
        "relationship_counts": rel_counts if world_lore.is_loaded and world_lore._legends else {},
        "identities": identities,
        "geography": geography[:15],
        "poetic_forms": world_lore._legends.poetic_forms if world_lore.is_loaded and world_lore._legends else [],
        "musical_forms": world_lore._legends.musical_forms if world_lore.is_loaded and world_lore._legends else [],
        "dance_forms": world_lore._legends.dance_forms if world_lore.is_loaded and world_lore._legends else [],
    })


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
    config.llm.provider = form.get("llm_provider", config.llm.provider)
    if form.get("api_key"):
        config.llm.api_key = form["api_key"]
    config.story.narrative_style = form.get("narrative_style", config.story.narrative_style)
    for field in ("chronicle_max_tokens", "biography_max_tokens", "saga_max_tokens"):
        try:
            val = form.get(field)
            if val:
                setattr(config.story, field, int(val))
        except (ValueError, AttributeError):
            pass

    save_config(config)
    _invalidate_cache()
    return RedirectResponse("/settings?saved=true", status_code=303)


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
            results.append({"category": "Civilization", "name": civ.name, "detail": race})
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
            results.append({"category": "Figure", "name": hf.name, "detail": detail})
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
            results.append({"category": "Artifact", "name": art.name, "detail": " — ".join(detail_parts)})
            count += 1

    # Search sites
    count = 0
    for sid, site in legends.sites.items():
        if count >= MAX_PER_CATEGORY:
            break
        if query in site.name.lower() or query in site.site_type.lower():
            results.append({"category": "Site", "name": site.name, "detail": site.site_type})
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
            results.append({"category": "Written Work", "name": title, "detail": detail})
            count += 1

    # Search wars/battles
    count = 0
    for ec in legends.event_collections:
        if count >= MAX_PER_CATEGORY:
            break
        name = ec.get("name", "")
        if name and query in name.lower():
            ec_type = ec.get("type", "").replace("_", " ").title()
            results.append({"category": ec_type, "name": name, "detail": ""})
            count += 1

    return {"results": results}


# ==================== Notes API ====================


@app.get("/api/notes")
async def api_list_notes(target_type: str | None = None, target_id: int | None = None):
    from df_storyteller.context.notes_store import load_all_notes
    config = _get_config()
    notes = load_all_notes(config)
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

    note = PlayerNote(
        tag=NoteTag(data["tag"]),
        text=data["text"],
        target_type=data.get("target_type", "fortress"),
        target_id=data.get("target_id"),
        game_year=metadata.get("year", 0),
        game_season=metadata.get("season", ""),
    )
    add_note(config, note)
    return note.model_dump(mode="json")


@app.post("/api/notes/{note_id}/resolve")
async def api_resolve_note(note_id: str):
    from df_storyteller.context.notes_store import resolve_note
    config = _get_config()
    ok = resolve_note(config, note_id)
    return {"ok": ok}


@app.delete("/api/notes/{note_id}")
async def api_delete_note(note_id: str):
    from df_storyteller.context.notes_store import delete_note
    config = _get_config()
    ok = delete_note(config, note_id)
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
        result = await generate_chronicle(config, None, one_time_context=one_time_context)
        # Simulate streaming by yielding in chunks
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        yield f"Error: {e}"


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
        result = await generate_biography(config, dwarf_name, one_time_context=one_time_context)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        yield f"Error: {e}"


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
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        yield f"Error: {e}"


@app.get("/api/worlds")
async def api_list_worlds():
    config = _get_config()
    return {"worlds": _get_worlds(config), "active": _get_active_world(config)}


@app.post("/api/worlds/switch")
async def api_switch_world(request: Request):
    global _active_world
    data = await request.json()
    _active_world = data.get("world", "")
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
        event_dir = Path(config.paths.event_dir) if config.paths.event_dir else None
        active_world = _get_active_world(config)
        watch_dir = event_dir / active_world if event_dir and active_world else None

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
