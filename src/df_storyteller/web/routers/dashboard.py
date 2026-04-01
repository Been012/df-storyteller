"""Dashboard routes."""
from __future__ import annotations

import re
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
    SEASON_ORDER_MAP,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
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

    # Fortress wealth over time from season_change events
    wealth_series: list[dict] = []
    for e in event_store.events_by_type(ET.SEASON_CHANGE):
        data = e.data
        wealth = data.get("fortress_wealth", 0) if isinstance(data, dict) else getattr(data, "fortress_wealth", 0)
        if wealth and wealth > 0:
            wealth_series.append({
                "label": f"{e.season.value.title()} Y{e.game_year}",
                "value": wealth,
                "_sort": _season_sort_key(e.game_year, e.season.value),
            })
    wealth_series.sort(key=lambda x: x["_sort"])
    for w in wealth_series:
        del w["_sort"]

    # Active mandates
    from df_storyteller.schema.events import MandateData
    mandates = []
    for e in event_store.events_by_type(ET.MANDATE):
        d = e.data
        if isinstance(d, MandateData):
            mandates.append({
                "issuer": d.issuer.name if d.issuer else "Unknown",
                "type": d.mandate_type.replace("_", " ").title(),
                "item": d.item_type or d.material or "various",
                "season": e.season.value.title(),
                "year": e.game_year,
            })

    # Recent crimes
    from df_storyteller.schema.events import CrimeData
    crimes = []
    for e in event_store.events_by_type(ET.CRIME):
        d = e.data
        if isinstance(d, CrimeData):
            crimes.append({
                "type": d.crime_type.replace("_", " ").title(),
                "victim": d.victim.name if d.victim else "unknown",
                "suspect": d.suspect.name if d.suspect else "unknown",
                "suspect_id": d.suspect.unit_id if d.suspect else 0,
                "season": e.season.value.title(),
                "year": e.game_year,
            })

    # Siege history
    from df_storyteller.schema.events import SiegeData
    sieges = []
    for e in event_store.events_by_type(ET.SIEGE):
        d = e.data
        if isinstance(d, SiegeData):
            sieges.append({
                "status": d.status,
                "invader_count": d.invader_count,
                "invader_race": d.invader_race.replace("_", " ").title() if d.invader_race else "Unknown",
                "civilization": d.civilization or "unknown force",
                "season": e.season.value.title(),
                "year": e.game_year,
            })

    # Caravan visits
    from df_storyteller.schema.events import CaravanData
    caravans = []
    for e in event_store.events_by_type(ET.CARAVAN):
        d = e.data
        if isinstance(d, CaravanData):
            caravans.append({
                "type": d.caravan_type.title(),
                "civilization": d.civilization or "unknown",
                "season": e.season.value.title(),
                "year": e.game_year,
            })

    # Artifacts from snapshot
    artifacts = []
    for a in metadata.get("artifacts", []):
        artifacts.append({
            "artifact_id": a.get("artifact_id", 0) if isinstance(a, dict) else getattr(a, "artifact_id", 0),
            "name": a.get("name", "") if isinstance(a, dict) else getattr(a, "name", ""),
            "item_type": a.get("item_type", "") if isinstance(a, dict) else getattr(a, "item_type", ""),
            "material": a.get("material", "") if isinstance(a, dict) else getattr(a, "material", ""),
            "creator_name": a.get("creator_name", "") if isinstance(a, dict) else getattr(a, "creator_name", ""),
        })

    # Peak population from season data
    peak_pop = 0
    for e in event_store.events_by_type(ET.SEASON_CHANGE):
        d = e.data
        pp = d.get("peak_population", 0) if isinstance(d, dict) else getattr(d, "peak_population", 0)
        if pp > peak_pop:
            peak_pop = pp

    # --- New dashboard enrichment ---

    # Recent events (last 8 non-equipment, non-chat)
    from df_storyteller.context.context_builder import _format_event as _fmt_event
    skip_types = {ET.CHAT}
    recent_events = []
    all_events = sorted(event_store.all_events(), key=lambda e: (e.game_year, SEASON_ORDER_MAP.get(e.season.value, 0), e.game_tick), reverse=True)
    for e in all_events:
        if e.event_type in skip_types:
            continue
        desc = re.sub(r"^\[.*?\]\s*", "", _fmt_event(e))
        if "equipped" in desc.lower() or "unequipped" in desc.lower():
            continue
        recent_events.append({
            "type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
            "season": e.season.value.title(),
            "year": e.game_year,
            "description": desc[:150],
        })
        if len(recent_events) >= 8:
            break

    # Notable citizens (highlighted dwarves)
    from df_storyteller.context.highlights_store import load_all_highlights
    fortress_dir = _get_fortress_dir(config, metadata)
    highlights = load_all_highlights(config, fortress_dir)
    notable_citizens = []
    for h in highlights:
        dwarf = character_tracker.get_dwarf(h.unit_id)
        if dwarf:
            notable_citizens.append({
                "unit_id": h.unit_id,
                "name": dwarf.name,
                "profession": dwarf.profession,
                "role": h.role.value,
            })

    # Mood distribution
    _MOOD_LABELS = {0: "haggard", 1: "very stressed", 2: "stressed", 3: "content", 4: "pleased", 5: "very happy", 6: "ecstatic"}
    mood_counts: dict[str, int] = {}
    for d in character_tracker._characters.values():
        cat = d.stress_category if isinstance(d.stress_category, int) else 3
        label = _MOOD_LABELS.get(cat, "content")
        mood_counts[label] = mood_counts.get(label, 0) + 1

    # Top skills across all dwarves
    top_skills = []
    for d in character_tracker._characters.values():
        for s in d.skills:
            level_num = int(s.level) if str(s.level).isdigit() else 0
            if level_num >= 4:  # Only show notable skills
                top_skills.append({
                    "dwarf_name": d.name.split(",")[0],  # Drop profession suffix
                    "unit_id": d.unit_id,
                    "skill": s.name.replace("_", " ").title(),
                    "level_num": level_num,
                })
    top_skills.sort(key=lambda x: x["level_num"], reverse=True)
    top_skills = top_skills[:6]

    # Latest chronicle excerpt
    from df_storyteller.web.helpers import parse_journal
    journal_entries = parse_journal(config, metadata)
    latest_chronicle = None
    if journal_entries:
        last = journal_entries[-1]
        raw = last.get("raw_text", "")
        # Strip inline image references for the excerpt
        clean = re.sub(r"\{\{img:[0-9a-f]{32}\.\w+\}\}", "", raw).strip()
        excerpt = clean[:200]
        if excerpt:
            latest_chronicle = {
                "header": last.get("header", ""),
                "excerpt": excerpt + ("..." if len(clean) > 200 else ""),
            }

    dashboard = {
        "summary": {
            "population": metadata.get("population", 0),
            "peak_population": peak_pop,
            "years_active": years_active,
            "total_deaths": len(event_store.events_by_type(ET.DEATH)),
            "total_artifacts": len(event_store.events_by_type(ET.ARTIFACT)) + len(artifacts),
            "total_combats": len(event_store.events_by_type(ET.COMBAT)),
            "total_sieges": len([s for s in sieges if s["status"] == "started"]),
        },
        "population_series": population_series,
        "wealth_series": wealth_series,
        "deaths_series": deaths_series,
        "combat_series": combat_series,
        "migration_series": migration_series,
        "milestones": milestones,
        "mandates": mandates,
        "crimes": crimes,
        "sieges": sieges,
        "caravans": caravans,
        "artifacts": artifacts,
        "recent_events": recent_events,
        "notable_citizens": notable_citizens,
        "mood_counts": mood_counts,
        "top_skills": top_skills,
        "latest_chronicle": latest_chronicle,
    }

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        **ctx, "content_class": "content-wide", "dashboard": dashboard,
    })
