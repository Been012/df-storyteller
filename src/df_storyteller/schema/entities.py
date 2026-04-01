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


class DwarfAppearance(BaseModel):
    """Appearance data for portrait generation."""

    skin_color: str = ""     # DF color name (e.g. "PEACH", "DARK_BROWN")
    hair_color: str = ""     # DF color name (e.g. "BLACK", "AUBURN")
    beard_color: str = ""    # DF color name for beard (may differ from hair)
    hair_length: int = 0     # DF tissue length units
    hair_style: str = ""     # "unkempt" / "shaped"
    hair_curly: int = 0      # Curliness value (0-200+)
    beard_length: int = 0    # Facial hair length
    beard_style: str = ""    # "unkempt" / "shaped"
    body_broadness: int = 100  # Head broadness (0-200, <100=thin, >=100=broad)


class Dwarf(BaseModel):
    """A living fortress citizen tracked for narrative purposes."""

    unit_id: int
    hist_figure_id: int = -1  # Links to historical figure in legends
    name: str
    profession: str = ""
    race: str = "DWARF"
    sex: str = "unknown"
    age: float = 0.0
    skills: list[Skill] = Field(default_factory=list)
    stress_category: int = 3  # 0=ecstatic, 6=on the edge
    happiness: int = 0  # Actual happiness value (more granular than stress_category)
    relationships: list[Relationship] = Field(default_factory=list)
    event_ids: list[int] = Field(default_factory=list)
    birth_year: int = 0
    is_alive: bool = True
    assigned_labors: list[str] = Field(default_factory=list)
    personality: Personality = Field(default_factory=Personality)
    noble_positions: list[str] = Field(default_factory=list)
    military_squad: str = ""
    current_job: str = ""
    equipment: list[str | dict] = Field(default_factory=list)  # str (legacy) or {description, mode}
    wounds: list[str | dict] = Field(default_factory=list)  # str (legacy) or {body_part, is_permanent, wound_type}
    pets: list[dict] = Field(default_factory=list)  # [{name, race, is_alive}]
    physical_attributes: dict[str, int] = Field(default_factory=dict)
    mental_attributes: dict[str, int] = Field(default_factory=dict)
    is_vampire: bool = False
    is_werebeast: bool = False
    assumed_identity: str = ""  # Non-empty if unit is using a fake name
    appearance: DwarfAppearance = Field(default_factory=DwarfAppearance)


class Animal(BaseModel):
    """A tracked animal in the fortress (pet, livestock, or wild)."""

    unit_id: int = 0
    name: str = ""
    race: str = ""
    profession: str = ""
    age: float = 0.0
    sex: str = "unknown"
    is_alive: bool = True
    is_pet: bool = False
    available_for_adoption: bool = False
    owner_id: int = -1
    owner_name: str = ""
    category: str = ""  # "pet", "war", "hunting", "adoptable", "tame", "wild"
    traits: list[str] = Field(default_factory=list)  # e.g. "sickly", "very strong"


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
    hf_links: list[dict] = Field(default_factory=list)  # [{type, hfid}] — family: child, mother, father, spouse
    active_interactions: list[str] = Field(default_factory=list)  # curses: vampirism, lycanthropy
    skills: list[dict] = Field(default_factory=list)  # [{skill, total_ip}]
    journey_pets: list[str] = Field(default_factory=list)
    intrigue_plots: list[dict] = Field(default_factory=list)  # [{type, on_hold, actors}]
    emotional_bonds: list[dict] = Field(default_factory=list)  # [{hf_id, love, respect, trust, loyalty, fear}]
    vague_relationships: list[dict] = Field(default_factory=list)  # [{type, hfid}]
    former_positions: list[dict] = Field(default_factory=list)  # [{position_profile_id, entity_id, start_year, end_year}]


class Artifact(BaseModel):
    artifact_id: int
    name: str
    item_type: str = ""
    material: str = ""
    creator_hf_id: int | None = None
    site_id: int | None = None
    description: str = ""
    pages: list[dict] = Field(default_factory=list)  # [{page_number, written_content_id}]


class Site(BaseModel):
    site_id: int
    name: str
    site_type: str = ""  # fortress, town, dark fortress, etc.
    owner_civ_id: int | None = None
    coordinates: tuple[int, int] | None = None
    events: list[int] = Field(default_factory=list)
    structures: list[dict] = Field(default_factory=list)  # [{id, name, type, deity_hf_id, entity_id}]
    properties: list[dict] = Field(default_factory=list)  # [{id, type, owner_hfid}]


class Civilization(BaseModel):
    entity_id: int
    name: str
    race: str = ""
    sites: list[int] = Field(default_factory=list)
    wars: list[int] = Field(default_factory=list)
    leader_hf_ids: list[int] = Field(default_factory=list)
