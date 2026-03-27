"""World and fortress state models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from df_storyteller.schema.entities import Dwarf
from df_storyteller.schema.events import Season


class MilitarySquad(BaseModel):
    squad_id: int
    name: str
    member_ids: list[int] = Field(default_factory=list)


class FortressState(BaseModel):
    """Snapshot of the current fortress."""

    name: str = ""
    population: int = 0
    year: int = 0
    season: Season = Season.SPRING
    wealth: int = 0
    citizens: list[Dwarf] = Field(default_factory=list)
    military_squads: list[MilitarySquad] = Field(default_factory=list)
    notable_buildings: list[str] = Field(default_factory=list)


class WorldState(BaseModel):
    """Top-level world metadata, primarily from legends data."""

    world_name: str = ""
    world_name_english: str = ""
    current_year: int = 0
    civilizations_count: int = 0
    historical_figures_count: int = 0
    sites_count: int = 0
    artifacts_count: int = 0
