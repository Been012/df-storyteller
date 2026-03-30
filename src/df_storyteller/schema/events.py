"""Normalized event models.

All game events from any source (DFHack JSON, gamelog, legends XML) are
normalized into these Pydantic models before entering the context layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    DEATH = "death"
    COMBAT = "combat"
    MOOD = "mood"
    BIRTH = "birth"
    BUILDING = "building"
    JOB = "job"
    ARTIFACT = "artifact"
    SEASON_CHANGE = "season_change"
    ANNOUNCEMENT = "announcement"
    PROFESSION_CHANGE = "profession_change"
    NOBLE_APPOINTMENT = "noble_appointment"
    MILITARY_CHANGE = "military_change"
    STRESS_CHANGE = "stress_change"
    MIGRANT_ARRIVED = "migrant_arrived"
    MIGRATION_WAVE = "migration_wave"


class EventSource(str, Enum):
    DFHACK = "dfhack"
    GAMELOG = "gamelog"
    LEGENDS = "legends"


class Season(str, Enum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


class Location(BaseModel):
    x: int
    y: int
    z: int


class UnitRef(BaseModel):
    """Lightweight reference to a unit involved in an event."""

    unit_id: int
    name: str
    race: str = ""
    profession: str = ""


class GameEvent(BaseModel):
    """Base event model. All source-specific events normalize to this or a subclass."""

    event_type: EventType
    game_year: int
    game_tick: int = 0
    season: Season = Season.SPRING
    source: EventSource
    timestamp: datetime = Field(default_factory=datetime.now)
    data: dict[str, Any] = Field(default_factory=dict)


# --- Typed event subclasses ---


class DeathData(BaseModel):
    victim: UnitRef
    cause: str = "unknown"
    killer: UnitRef | None = None
    location: Location | None = None
    age: int | None = None
    notable_skills: list[dict[str, str]] = Field(default_factory=list)


class DeathEvent(GameEvent):
    event_type: Literal[EventType.DEATH] = EventType.DEATH
    data: DeathData  # type: ignore[assignment]


class CombatBlow(BaseModel):
    """A single strike within a combat encounter."""
    attacker: str = ""
    defender: str = ""
    action: str = ""  # hacks, slashes, stabs, punches, etc.
    body_part: str = ""
    weapon: str = ""
    effect: str = ""  # tearing apart the muscle, fracturing the skull, etc.


class CombatData(BaseModel):
    attacker: UnitRef
    defender: UnitRef
    weapon: str = ""
    body_part: str = ""
    wound_type: str = ""
    is_lethal: bool = False
    raw_text: str = ""
    blows: list[CombatBlow] = Field(default_factory=list)
    injuries: list[str] = Field(default_factory=list)  # "An artery has been opened", etc.
    outcome: str = ""  # "gives in to pain", "falls over", "cloven asunder", ""


class CombatEvent(GameEvent):
    event_type: Literal[EventType.COMBAT] = EventType.COMBAT
    data: CombatData  # type: ignore[assignment]


class MoodData(BaseModel):
    unit: UnitRef
    mood_type: str  # fey, secretive, possessed, macabre, fell
    skill_used: str = ""


class MoodEvent(GameEvent):
    event_type: Literal[EventType.MOOD] = EventType.MOOD
    data: MoodData  # type: ignore[assignment]


class BirthData(BaseModel):
    child: UnitRef
    mother: UnitRef | None = None
    father: UnitRef | None = None


class BirthEvent(GameEvent):
    event_type: Literal[EventType.BIRTH] = EventType.BIRTH
    data: BirthData  # type: ignore[assignment]


class BuildingData(BaseModel):
    building_type: str
    name: str = ""
    builder: UnitRef | None = None
    location: Location | None = None


class BuildingEvent(GameEvent):
    event_type: Literal[EventType.BUILDING] = EventType.BUILDING
    data: BuildingData  # type: ignore[assignment]


class JobData(BaseModel):
    job_type: str
    worker: UnitRef | None = None
    result: str = ""


class JobEvent(GameEvent):
    event_type: Literal[EventType.JOB] = EventType.JOB
    data: JobData  # type: ignore[assignment]


class ArtifactData(BaseModel):
    artifact_name: str
    item_type: str = ""
    creator: UnitRef | None = None
    material: str = ""
    description: str = ""


class ArtifactEvent(GameEvent):
    event_type: Literal[EventType.ARTIFACT] = EventType.ARTIFACT
    data: ArtifactData  # type: ignore[assignment]


class SeasonChangeData(BaseModel):
    new_season: Season
    population: int = 0
    fortress_wealth: int = 0
    notable_events_summary: str = ""


class SeasonChangeEvent(GameEvent):
    event_type: Literal[EventType.SEASON_CHANGE] = EventType.SEASON_CHANGE
    data: SeasonChangeData  # type: ignore[assignment]


class ProfessionChangeData(BaseModel):
    unit: UnitRef
    old_profession: str
    new_profession: str


class ProfessionChangeEvent(GameEvent):
    event_type: Literal[EventType.PROFESSION_CHANGE] = EventType.PROFESSION_CHANGE
    data: ProfessionChangeData  # type: ignore[assignment]


class NobleAppointmentData(BaseModel):
    unit: UnitRef
    positions: list[str] = Field(default_factory=list)


class NobleAppointmentEvent(GameEvent):
    event_type: Literal[EventType.NOBLE_APPOINTMENT] = EventType.NOBLE_APPOINTMENT
    data: NobleAppointmentData  # type: ignore[assignment]


class MilitaryChangeData(BaseModel):
    unit: UnitRef
    squad_name: str = ""
    squad_id: int = -1


class MilitaryChangeEvent(GameEvent):
    event_type: Literal[EventType.MILITARY_CHANGE] = EventType.MILITARY_CHANGE
    data: MilitaryChangeData  # type: ignore[assignment]


class StressChangeData(BaseModel):
    unit: UnitRef
    old_stress: str
    new_stress: str


class StressChangeEvent(GameEvent):
    event_type: Literal[EventType.STRESS_CHANGE] = EventType.STRESS_CHANGE
    data: StressChangeData  # type: ignore[assignment]


class MigrantArrivedData(BaseModel):
    unit: UnitRef


class MigrantArrivedEvent(GameEvent):
    event_type: Literal[EventType.MIGRANT_ARRIVED] = EventType.MIGRANT_ARRIVED
    data: MigrantArrivedData  # type: ignore[assignment]


class MigrationWaveData(BaseModel):
    new_arrivals: int = 0
    total_population: int = 0


class MigrationWaveEvent(GameEvent):
    event_type: Literal[EventType.MIGRATION_WAVE] = EventType.MIGRATION_WAVE
    data: MigrationWaveData  # type: ignore[assignment]
