"""Entity models for dwarves, artifacts, civilizations, and historical figures."""

from __future__ import annotations

from pydantic import BaseModel, Field

from df_storyteller.schema.personality import Personality


class Skill(BaseModel):
    name: str
    level: str  # e.g. "Legendary", "Grand Master", "Proficient"
    experience: int = 0


class Relationship(BaseModel):
    target_unit_id: int
    target_name: str
    relationship_type: str  # friend, grudge, lover, spouse, parent, child, etc.


class Dwarf(BaseModel):
    """A living fortress citizen tracked for narrative purposes."""

    unit_id: int
    hist_figure_id: int = -1  # Links to historical figure in legends
    name: str
    profession: str = ""
    race: str = "DWARF"
    age: float = 0.0
    skills: list[Skill] = Field(default_factory=list)
    stress_category: int = 3  # 0=ecstatic, 6=on the edge
    relationships: list[Relationship] = Field(default_factory=list)
    event_ids: list[int] = Field(default_factory=list)
    birth_year: int = 0
    is_alive: bool = True
    assigned_labors: list[str] = Field(default_factory=list)
    personality: Personality = Field(default_factory=Personality)
    noble_positions: list[str] = Field(default_factory=list)
    military_squad: str = ""
    current_job: str = ""
    equipment: list[str] = Field(default_factory=list)
    wounds: list[str] = Field(default_factory=list)
    physical_attributes: dict[str, int] = Field(default_factory=dict)
    mental_attributes: dict[str, int] = Field(default_factory=dict)


class HistoricalFigure(BaseModel):
    """A figure from legends mode / world history."""

    hf_id: int
    name: str
    race: str = ""
    caste: str = ""  # male, female
    birth_year: int = 0
    death_year: int | None = None
    associated_civ_id: int | None = None
    notable_deeds: list[str] = Field(default_factory=list)
    spheres: list[str] = Field(default_factory=list)  # deity domains: death, wealth, nature, etc.
    is_deity: bool = False
    hf_type: str = ""  # deity, megabeast, historical figure, etc.
    entity_links: list[dict] = Field(default_factory=list)  # [{type, entity_id, position}]
    active_interactions: list[str] = Field(default_factory=list)  # curses: vampirism, lycanthropy
    skills: list[dict] = Field(default_factory=list)  # [{skill, total_ip}]
    journey_pets: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    artifact_id: int
    name: str
    item_type: str = ""
    material: str = ""
    creator_hf_id: int | None = None
    site_id: int | None = None
    description: str = ""


class Site(BaseModel):
    site_id: int
    name: str
    site_type: str = ""  # fortress, town, dark fortress, etc.
    owner_civ_id: int | None = None
    coordinates: tuple[int, int] | None = None
    events: list[int] = Field(default_factory=list)
    structures: list[dict] = Field(default_factory=list)  # [{id, name, type, deity_hf_id, entity_id}]


class Civilization(BaseModel):
    entity_id: int
    name: str
    race: str = ""
    sites: list[int] = Field(default_factory=list)
    wars: list[int] = Field(default_factory=list)
    leader_hf_ids: list[int] = Field(default_factory=list)
