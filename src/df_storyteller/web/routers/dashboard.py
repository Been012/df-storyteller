"""Dashboard routes."""
from __future__ import annotations

import re
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
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
