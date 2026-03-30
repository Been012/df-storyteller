# Legends Data Model

How the two DF legends XML exports are parsed, merged, and indexed into queryable data.

## Data Sources

DF exports two XML files when you export legends:

| File | Contains | Key Data |
|------|----------|----------|
| `*-legends.xml` | Basic data | Names, descriptions, events, eras |
| `*-legends_plus.xml` | Extended data | Race, type, family links, skills, curses, positions, structures |

Both must be parsed and merged. Basic has names/descriptions/events. Plus has race/type/child IDs/worship IDs/positions/festivals.

## Core Entity Models

All defined in `schema/entities.py` as Pydantic v2 models.

### HistoricalFigure

| Field | Source | Type |
|-------|--------|------|
| `hf_id` | basic | `int` |
| `name` | basic | `str` |
| `race` | **plus** | `str` |
| `caste` | **plus** | `str` (male/female) |
| `birth_year` | basic | `int` |
| `death_year` | basic | `int \| None` |
| `associated_civ_id` | basic | `int \| None` → Civilization |
| `is_deity` | basic | `bool` |
| `hf_type` | **plus** | `str` (deity, megabeast, etc.) |
| `notable_deeds` | basic | `list[str]` |
| `spheres` | **plus** | `list[str]` (deity domains) |
| `active_interactions` | **plus** | `list[str]` (curses: vampirism, lycanthropy) |
| `skills` | **plus** | `list[dict]` ({skill, total_ip}) |
| `journey_pets` | **plus** | `list[str]` |
| `intrigue_plots` | **plus** | `list[dict]` ({type, on_hold, actors}) |
| `emotional_bonds` | **plus** | `list[dict]` ({hf_id, love, respect, trust, loyalty, fear, ...}) |
| `hf_links` | **plus** | `list[dict]` ({type, hfid}) — family/social |
| `vague_relationships` | **plus** | `list[dict]` ({type, hfid}) |
| `entity_links` | **plus** | `list[dict]` ({type, entity_id}) — positions held |
| `former_positions` | **plus** | `list[dict]` ({position_profile_id, entity_id, start/end_year}) |

### Site

| Field | Source | Type |
|-------|--------|------|
| `site_id` | basic | `int` |
| `name` | basic | `str` |
| `site_type` | basic/plus | `str` (fortress, town, dark fortress, etc.) |
| `owner_civ_id` | basic/plus | `int \| None` → Civilization |
| `coordinates` | **plus** | `tuple[int, int] \| None` |
| `structures` | **plus** | `list[dict]` ({id, name, type, deity_hf_id, entity_id}) |
| `properties` | **plus** | `list[dict]` ({id, type, owner_hfid}) |

### Artifact

| Field | Source | Type |
|-------|--------|------|
| `artifact_id` | basic | `int` |
| `name` | basic | `str` |
| `description` | basic | `str` |
| `item_type` | **plus** | `str` (weapon, armor, book, etc.) |
| `material` | **plus** | `str` (steel, adamantine, etc.) |
| `creator_hf_id` | **plus** | `int \| None` → HistoricalFigure |
| `site_id` | **plus** | `int \| None` → Site |
| `pages` | **plus** | `list[dict]` ({page_number, written_content_id}) |

### Civilization

| Field | Source | Type |
|-------|--------|------|
| `entity_id` | basic | `int` |
| `name` | basic | `str` |
| `race` | **plus** | `str` |
| `sites` | basic/plus | `list[int]` → Site IDs |
| `leader_hf_ids` | basic/plus | `list[int]` → HistoricalFigure IDs |
| `_entity_type` | **plus** | `str` — "civilization", "religion", "merchant_company", "performance_group", etc. |
| `_child_ids` | **plus** | `list[int]` → child Civilization IDs (hierarchy) |
| `_worship_id` | **plus** | `int` → HistoricalFigure (deity, for religions) |
| `_profession` | **plus** | `str` (for guilds: "weaponsmith", etc.) |
| `_entity_positions` | **plus** | `list[dict]` ({id, name, name_male, name_female}) |
| `_occasions` | **plus** | `list[dict]` (festival definitions with schedules) |
| `_honors` | **plus** | `list[dict]` (rank/honor system) |

Note: `_` prefixed fields are stored as custom attributes on the Pydantic model via `# type: ignore[attr-defined]`.

## Object Graph (ID-based relationships)

```
HistoricalFigure
  ├── associated_civ_id ──────────→ Civilization
  ├── entity_links[].entity_id ──→ Civilization (positions held)
  ├── hf_links[].hfid ──────────→ HistoricalFigure (family)
  │     types: mother, father, child, spouse,
  │            deceased_spouse, former_spouse
  ├── emotional_bonds[].hf_id ──→ HistoricalFigure
  ├── vague_relationships[].hfid → HistoricalFigure
  ├── intrigue_plots[].actors[]
  │     ├── .hfid ──────────────→ HistoricalFigure
  │     └── .entity_id ────────→ Civilization
  └── former_positions[].entity_id → Civilization

Artifact
  ├── creator_hf_id ────────────→ HistoricalFigure
  ├── site_id ──────────────────→ Site
  └── pages[].written_content_id → written_contents list

Site
  ├── owner_civ_id ─────────────→ Civilization
  ├── structures[].deity_hf_id ─→ HistoricalFigure
  ├── structures[].entity_id ──→ Civilization
  └── properties[].owner_hfid ─→ HistoricalFigure

Civilization
  ├── sites[] ──────────────────→ [Site]
  ├── leader_hf_ids[] ─────────→ [HistoricalFigure]
  ├── _child_ids[] ────────────→ [Civilization] (sub-entities)
  └── _worship_id ─────────────→ HistoricalFigure (deity)

Event Collections (wars/battles)
  ├── aggressor_ent_id[] ──────→ [Civilization]
  └── defender_ent_id[] ───────→ [Civilization]

Historical Events (raw dicts)
  ├── hfid, hfid_1, hfid_2 ──→ HistoricalFigure
  ├── slayer_hfid ────────────→ HistoricalFigure
  └── site_id ────────────────→ Site
```

## LegendsData Container

Central class in `legends_parser.py`. Holds everything after parsing:

**Indexed entities** (dict by ID):
- `historical_figures: dict[int, HistoricalFigure]`
- `sites: dict[int, Site]`
- `civilizations: dict[int, Civilization]`
- `artifacts: dict[int, Artifact]`

**Raw collections** (list of dicts):
- `historical_events` — all events from XML
- `event_collections` — wars, battles, sieges, duels, etc.
- `historical_eras` — named time periods
- `regions` — geographic regions

**Extended data** (from legends_plus only):
- `relationships` — HF-to-HF bonds with values
- `written_contents` — books, poetry, music
- `identities` — personas/aliases
- `world_constructions` — monuments, world features
- `landmasses`, `mountain_peaks`, `rivers` — geography
- `poetic_forms`, `musical_forms`, `dance_forms` — cultural forms
- `entity_populations` — population stats by entity

**Categorized event collections** (auto-populated by `build_indexes()`):
- `battles`, `beast_attacks`, `site_conquests`, `persecutions`
- `duels`, `abductions`, `thefts`, `purges`, `entity_overthrown`
- `notable_deaths` — deaths with a slayer

## Merge Logic

In `loader.py`, both XML files are parsed in parallel, then merged:

```
legends_plus data → merged INTO → legends_basic data
```

**Rules:**
- Plus enriches basic — never overwrites non-empty basic fields
- If a figure/site/artifact exists only in plus, it's added to merged result
- Extended lists (relationships, written_contents, etc.) are copied wholesale from plus
- Cultural forms are merged by ID
- Regions are merged by ID with coordinate/evilness data

**Per-entity merge:**
- **HF**: race, caste, hf_type, hf_links, entity_links, skills, curses, bonds, plots
- **Site**: site_type, owner, structures, properties, coordinates
- **Artifact**: item_type, material, site_id, description, pages
- **Civ**: race, entity_type, child_ids, worship_id, positions, occasions, honors

## Pre-Computed Indexes

`build_indexes()` runs after parsing. Creates O(1) lookup structures:

| Index | Type | Query Method |
|-------|------|-------------|
| `_wars_by_entity` | `dict[int, list[dict]]` | `get_wars_involving(entity_id)` |
| `_event_collections_by_id` | `dict[str, dict]` | `get_event_collection(ec_id)` |
| `_hf_event_count` | `dict[int, int]` | `get_hf_event_count(hf_id)` |
| `_hf_events` | `dict[int, list[dict]]` | `get_hf_events(hf_id)` |
| `_site_event_types` | `dict[int, dict[str, int]]` | `get_site_event_types(site_id)` |
| `_hf_relationships` | `dict[int, list[dict]]` | `get_hf_relationships(hf_id)` |
| `_hf_family` | `dict[int, dict[str, list[int]]]` | `get_hf_family(hf_id)` |

**Family index** is bidirectional: if A's mother is B, B's children include A.

**HF event scan** checks fields: `hfid`, `hfid_1`, `hfid_2`, `slayer_hfid`, `group_hfid`.

## WorldLore Wrapper

`context/world_lore.py` provides a high-level narrative interface over LegendsData:

| Method | Purpose |
|--------|---------|
| `get_figure_biography(hf_id)` | Narrative summary: name, race, birth/death, civ, event count |
| `get_war_summary(war_collection)` | Readable war summary with aggressors/defenders |
| `get_civilization_history(entity_id)` | Sites controlled + wars involved |
| `get_artifact_story(artifact_id)` | Name, type, material, creator |
| `search_figures_by_name(name)` | Case/diacritic-insensitive name search |

## Character Encoding

DF writes XML with UTF-8 declaration but embeds CP437 bytes for diacritics (ö, û, â). The parser:
1. Tries UTF-8 first
2. If replacement characters (`\ufffd`) detected, re-decodes as CP437
3. Strips illegal XML 1.0 control characters
