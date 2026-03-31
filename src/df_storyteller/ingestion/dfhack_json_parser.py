"""Parser for DFHack-emitted JSON event files.

DFHack Lua scripts write one JSON file per event into a watched directory.
This module validates and normalizes those files into GameEvent models.

See: https://docs.dfhack.org/en/stable/ for DFHack Lua API reference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from df_storyteller.schema.events import (
    ArtifactData,
    ArtifactEvent,
    BirthData,
    BirthEvent,
    BuildingData,
    BuildingEvent,
    CombatData,
    CombatEvent,
    DeathData,
    DeathEvent,
    EventSource,
    EventType,
    GameEvent,
    JobData,
    JobEvent,
    MigrantArrivedData,
    MigrantArrivedEvent,
    MigrationWaveData,
    MigrationWaveEvent,
    MilitaryChangeData,
    MilitaryChangeEvent,
    MoodData,
    MoodEvent,
    NobleAppointmentData,
    NobleAppointmentEvent,
    ProfessionChangeData,
    ProfessionChangeEvent,
    Season,
    SeasonChangeData,
    SeasonChangeEvent,
    StressChangeData,
    StressChangeEvent,
    UnitRef,
    Location,
)


def _parse_unit_ref(data: dict[str, Any]) -> UnitRef:
    return UnitRef(
        unit_id=data.get("unit_id", 0),
        name=data.get("name", "Unknown"),
        race=data.get("race", ""),
        profession=data.get("profession", ""),
    )


def _parse_location(data: dict[str, Any] | None) -> Location | None:
    if not data:
        return None
    return Location(x=data["x"], y=data["y"], z=data["z"])


def _parse_season(raw: str) -> Season:
    try:
        return Season(raw.lower())
    except ValueError:
        return Season.SPRING


_EVENT_PARSERS: dict[str, type] = {
    "death": DeathEvent,
    "combat": CombatEvent,
    "mood": MoodEvent,
    "birth": BirthEvent,
    "building_created": BuildingEvent,
    "building": BuildingEvent,
    "job_completed": JobEvent,
    "job": JobEvent,
    "artifact": ArtifactEvent,
    "season_change": SeasonChangeEvent,
}


def parse_dfhack_event(raw: dict[str, Any]) -> GameEvent:
    """Parse a raw DFHack JSON event dict into a typed GameEvent."""
    event_type_str = raw.get("event_type", "")
    data = raw.get("data", {})
    game_year = raw.get("game_year", 0)
    game_tick = raw.get("game_tick", 0)
    season = _parse_season(raw.get("season", "spring"))

    base_kwargs = {
        "game_year": game_year,
        "game_tick": game_tick,
        "season": season,
        "source": EventSource.DFHACK,
    }

    match event_type_str:
        case "death":
            return DeathEvent(
                **base_kwargs,
                data=DeathData(
                    victim=_parse_unit_ref(data.get("victim", data)),
                    cause=data.get("cause", "unknown"),
                    killer=_parse_unit_ref(data["killer"]) if data.get("killer") else None,
                    owner=_parse_unit_ref(data["owner"]) if data.get("owner") else None,
                    location=_parse_location(data.get("location")),
                    age=data.get("age"),
                    notable_skills=data.get("notable_skills", []),
                ),
            )

        case "combat":
            return CombatEvent(
                **base_kwargs,
                data=CombatData(
                    attacker=_parse_unit_ref(data.get("attacker", {})),
                    defender=_parse_unit_ref(data.get("defender", {})),
                    weapon=data.get("weapon", ""),
                    body_part=data.get("body_part", ""),
                    wound_type=data.get("wound_type", ""),
                    is_lethal=data.get("is_lethal", False),
                    raw_text=data.get("raw_text", ""),
                ),
            )

        case "mood":
            return MoodEvent(
                **base_kwargs,
                data=MoodData(
                    unit=_parse_unit_ref(data.get("unit", data)),
                    mood_type=data.get("mood_type", "unknown"),
                    skill_used=data.get("skill_used", ""),
                ),
            )

        case "birth":
            return BirthEvent(
                **base_kwargs,
                data=BirthData(
                    child=_parse_unit_ref(data.get("child", data)),
                    mother=_parse_unit_ref(data["mother"]) if data.get("mother") else None,
                    father=_parse_unit_ref(data["father"]) if data.get("father") else None,
                ),
            )

        case "building_created" | "building":
            return BuildingEvent(
                **base_kwargs,
                data=BuildingData(
                    building_type=data.get("building_type", ""),
                    name=data.get("name", ""),
                    builder=_parse_unit_ref(data["builder"]) if data.get("builder") else None,
                    location=_parse_location(data.get("location")),
                ),
            )

        case "job_completed" | "job":
            return JobEvent(
                **base_kwargs,
                data=JobData(
                    job_type=data.get("job_type", ""),
                    worker=_parse_unit_ref(data["worker"]) if data.get("worker") else None,
                    result=data.get("result", ""),
                ),
            )

        case "artifact":
            return ArtifactEvent(
                **base_kwargs,
                data=ArtifactData(
                    artifact_name=data.get("artifact_name", ""),
                    item_type=data.get("item_type", ""),
                    creator=_parse_unit_ref(data["creator"]) if data.get("creator") else None,
                    material=data.get("material", ""),
                    description=data.get("description", ""),
                ),
            )

        case "season_change":
            return SeasonChangeEvent(
                **base_kwargs,
                data=SeasonChangeData(
                    new_season=_parse_season(data.get("new_season", "spring")),
                    population=data.get("population", 0),
                    fortress_wealth=data.get("fortress_wealth", 0),
                    notable_events_summary=data.get("notable_events_summary", ""),
                ),
            )

        case "profession_change":
            unit_data = data.get("unit", {})
            return ProfessionChangeEvent(
                **base_kwargs,
                data=ProfessionChangeData(
                    unit=_parse_unit_ref(unit_data) if isinstance(unit_data, dict) else UnitRef(unit_id=0, name="Unknown"),
                    old_profession=data.get("old_profession", ""),
                    new_profession=data.get("new_profession", ""),
                ),
            )

        case "noble_appointment":
            unit_data = data.get("unit", {})
            positions = data.get("positions", [])
            return NobleAppointmentEvent(
                **base_kwargs,
                data=NobleAppointmentData(
                    unit=_parse_unit_ref(unit_data) if isinstance(unit_data, dict) else UnitRef(unit_id=0, name="Unknown"),
                    positions=positions if isinstance(positions, list) else [str(positions)],
                ),
            )

        case "military_change":
            unit_data = data.get("unit", {})
            return MilitaryChangeEvent(
                **base_kwargs,
                data=MilitaryChangeData(
                    unit=_parse_unit_ref(unit_data) if isinstance(unit_data, dict) else UnitRef(unit_id=0, name="Unknown"),
                    squad_name=data.get("squad_name", ""),
                    squad_id=data.get("squad_id", -1),
                ),
            )

        case "stress_change":
            unit_data = data.get("unit", {})
            return StressChangeEvent(
                **base_kwargs,
                data=StressChangeData(
                    unit=_parse_unit_ref(unit_data) if isinstance(unit_data, dict) else UnitRef(unit_id=0, name="Unknown"),
                    old_stress=data.get("old_stress", ""),
                    new_stress=data.get("new_stress", ""),
                ),
            )

        case "migrant_arrived":
            unit_data = data.get("unit", {})
            return MigrantArrivedEvent(
                **base_kwargs,
                data=MigrantArrivedData(
                    unit=_parse_unit_ref(unit_data) if isinstance(unit_data, dict) else UnitRef(unit_id=0, name="Unknown"),
                ),
            )

        case "migration_wave":
            return MigrationWaveEvent(
                **base_kwargs,
                data=MigrationWaveData(
                    new_arrivals=data.get("new_arrivals", 0),
                    total_population=data.get("total_population", 0),
                ),
            )

        case "mood_completed":
            return GameEvent(
                event_type=EventType.MOOD_COMPLETED,
                **base_kwargs,
                data=data,
            )

        case "tantrum":
            return GameEvent(
                event_type=EventType.TANTRUM,
                **base_kwargs,
                data=data,
            )

        case "skill_level_up":
            return GameEvent(
                event_type=EventType.SKILL_LEVEL_UP,
                **base_kwargs,
                data=data,
            )

        case "relationship_formed":
            return GameEvent(
                event_type=EventType.RELATIONSHIP_FORMED,
                **base_kwargs,
                data=data,
            )

        case _:
            # Unknown event type — store as generic GameEvent
            return GameEvent(
                event_type=EventType.ANNOUNCEMENT,
                **base_kwargs,
                data=data,
            )


def parse_dfhack_file(path: Path) -> GameEvent | None:
    """Parse a single DFHack JSON event file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = json.load(f)
        return parse_dfhack_event(raw)
    except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        # Log malformed files but don't crash
        import logging
        logging.getLogger(__name__).warning("Failed to parse %s: %s", path, e)
        return None
