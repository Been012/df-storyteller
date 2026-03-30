# Event Lifecycle: DFHack → Story Output

How a game event travels from Dwarf Fortress through the Python backend into generated narratives and the web UI.

## Pipeline Overview

```
┌──────────────────────────────────────────┐
│ DWARF FORTRESS (DFHack Lua)              │
│  storyteller-events.lua                  │
│    eventful hooks (death, building, job) │
│    100-tick poll loop (mood, birth, etc) │
│         ↓                                │
│  JSON files → storyteller_events/        │
│               {world_folder}/            │
│               {year}_{type}_{seq}.json   │
└──────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│ PYTHON INGESTION                         │
│  ingestion/dfhack_json_parser.py         │
│    → Typed Pydantic models (8 types)     │
│    → Generic GameEvent w/ dict (6 types) │
│                                          │
│  ingestion/gamelog_parser.py             │
│    → Same event models from gamelog.txt  │
└──────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│ STORAGE & INDEXING                       │
│  context/event_store.py                  │
│    _events[]        (sequential)         │
│    _by_type{}       (EventType → [idx])  │
│    _by_unit{}       (unit_id → [idx])    │
└──────────────────────────────────────────┘
                    ↓
        ┌───────────┴───────────┐
        ↓                       ↓
┌───────────────┐     ┌─────────────────┐
│ LLM PATH      │     │ WEB DISPLAY     │
│ context_builder│     │ event_renderer  │
│ _format_event()│     │ describe_event()│
│   ↓            │     │   ↓             │
│ StoryContext   │     │ Rich text with  │
│   ↓            │     │ [[name]] links  │
│ LLM prompt     │     │   ↓             │
│   ↓            │     │ Web templates   │
│ Generated story│     └─────────────────┘
└───────────────┘
```

## Stage 1: DFHack Lua — Event Generation

### Two Detection Mechanisms

**Hook-based (instant, via eventful plugin):**
| Hook | Event Type | Trigger |
|------|-----------|---------|
| `eventful.onUnitDeath` | `death` | Any unit dies |
| `eventful.onBuildingCreatedDestroyed` | `building_created` | Building completed |
| `eventful.onJobCompleted` | `job_completed` | Artifact creation jobs |

**Poll-based (every 100 game ticks):**
| Poll Function | Event Type | Detection Method |
|--------------|-----------|-----------------|
| mood check | `mood` | `unit.mood` enum changes (fey, secretive, possessed, macabre, fell) |
| season check | `season_change` | `dfhack.world.ReadCurrentYear()`/tick math vs `last_season` |
| birth check | `birth` | New unit_id appears with `dfhack.units.getAge() == 0` |
| profession check | `profession_change` | `unit.profession` differs from `prev_professions[id]` |
| noble check | `noble_appointment` | Position string differs from `prev_nobles[id]` |
| military check | `military_change` | `unit.military.squad_id` differs from `prev_squads[id]` |
| stress check | `stress_change` | Stress category shifts by 2+ levels vs `prev_stress[id]` |
| migrant check | `migrant_arrived` | New unit_id with age > 1, after baseline established |
| pop check | `migration_wave` | Population increased by 2+ since last poll |

### Change-Detection Baselines

All baselines live on `dfhack.storyteller_state` (global table that survives script reloads):

| Baseline | Type | Seeded On |
|----------|------|-----------|
| `known_unit_ids` | `{unit_id → true}` | Start — all living citizens |
| `prev_professions` | `{unit_id → string}` | Start — current profession names |
| `prev_nobles` | `{unit_id → string}` | Start — comma-joined position names |
| `prev_squads` | `{unit_id → squad_id}` | Start — current squad or -1 |
| `prev_stress` | `{unit_id → category}` | Start — stress level 0-6 |
| `prev_population` | `number` | Start — living citizen count |
| `last_season` | `string` | Start — current season name |

### JSON Output Format

All events share this wrapper:
```json
{
  "event_type": "death",
  "game_year": 251,
  "game_tick": 48000,
  "season": "summer",
  "session_id": "1711858923",
  "data": { /* event-specific */ }
}
```

**File naming:** `{year}_{event_type}_{sequence:06d}.json`
(e.g., `251_death_000042.json`)

**Atomic writes:** Write to `.tmp` first, then `os.rename()` to `.json`.

**Directory structure:**
```
storyteller_events/
└── {world_folder}/
    ├── .session_id              ← fortress identity
    ├── processed/               ← acknowledged events
    ├── 251_death_000001.json
    ├── 251_season_change_000002.json
    └── snapshot_251_048000_1711858923.json
```

### Event-Specific Data Fields

<details>
<summary>Click to expand all event data shapes</summary>

**death:**
```
victim: {unit_id, name, race, profession, is_citizen, stress_category}
cause: "combat" | "unknown"
killer: {unit_id, name, race, profession, is_citizen, stress_category} (optional)
age: number
notable_skills: [{skill, level}]
```

**building_created:**
```
building_type: string (enum name)
name: string
location: {x, y, z}
```

**job_completed:**
```
job_type: string (enum name)
result: string
```

**mood:**
```
unit: {unit_id, name, race, profession, is_citizen, stress_category}
mood_type: "fey" | "secretive" | "possessed" | "macabre" | "fell" | "unknown"
```

**season_change:**
```
new_season: "spring" | "summer" | "autumn" | "winter"
population: number
fortress_wealth: 0
```

**birth:**
```
child: {unit_id, name, race, profession, is_citizen, stress_category}
```

**profession_change:**
```
unit: {unit_id, name, race, ...}, old_profession, new_profession
```

**noble_appointment:**
```
unit: {unit_id, name, race, ...}, positions: [string]
```

**military_change:**
```
unit: {unit_id, name, race, ...}, squad_name, squad_id
```

**stress_change:**
```
unit: {unit_id, name, race, ...}, old_stress, new_stress
```

**migrant_arrived:**
```
unit: {unit_id, name, race, ...}
```

**migration_wave:**
```
new_arrivals: number, total_population: number
```

</details>

### Snapshots (not events, but same pipeline)

**Filename:** `snapshot_{year}_{tick:06d}_{timestamp}.json`
**Triggered by:** `storyteller-begin`, season changes (auto), manual `storyteller-snapshot`

Snapshots contain the **full fortress state**: all citizens with skills, personality facets (all 50), beliefs, goals, relationships (via histfig_links), equipment, wounds, physical/mental attributes, plus buildings, visitors, animals, and fortress metadata.

Events carry only minimal unit refs (`{unit_id, name, race, profession}`). Snapshots provide the deep character data.

---

## Stage 2: Python Ingestion

### dfhack_json_parser.py

`parse_dfhack_file(path) → GameEvent`

Uses a `match` statement on `event_type`:

| Event Type | Output Model | Schema Type |
|-----------|-------------|-------------|
| `death` | `DeathEvent(DeathData)` | **Typed Pydantic** |
| `combat` | `CombatEvent(CombatData)` | **Typed Pydantic** |
| `mood` | `MoodEvent(MoodData)` | **Typed Pydantic** |
| `birth` | `BirthEvent(BirthData)` | **Typed Pydantic** |
| `building_created` / `building` | `BuildingEvent(BuildingData)` | **Typed Pydantic** |
| `job_completed` / `job` | `JobEvent(JobData)` | **Typed Pydantic** |
| `artifact` | `ArtifactEvent(ArtifactData)` | **Typed Pydantic** |
| `season_change` | `SeasonChangeEvent(SeasonChangeData)` | **Typed Pydantic** |
| `profession_change`, `noble_appointment`, `military_change`, `stress_change`, `migrant_arrived`, `migration_wave` | `GameEvent(data=dict)` | **Dict-based** |
| Unknown types | `GameEvent(data=dict)` | **Dict-based** (ANNOUNCEMENT) |

### gamelog_parser.py

`GamelogParser.parse_lines(lines) → Generator[GameEvent]`

Produces the same typed models from gamelog.txt patterns:
- Season headers → `SeasonChangeEvent`
- Death lines (8 regex patterns) → `DeathEvent`
- Mood lines → `MoodEvent`
- Artifact lines → `ArtifactEvent`
- Multi-line combat blocks → `CombatEvent` (with `CombatBlow` sub-objects)
- Everything else → `GameEvent` (ANNOUNCEMENT)

**Key difference:** Gamelog events have `unit_id=0` (no IDs in gamelog text, names only).

---

## Stage 3: Loading & Storage

### loader.py — `load_game_state()`

1. Find event directory from config
2. Scan world subfolders, group by fortress identity (same `civ_id + fortress_name + session_id`)
3. Merge sibling folders (DF renames save folders on autosave)
4. Filter events by `session_id` to skip stale data
5. Parse each JSON via `parse_dfhack_file()`
6. Add to `EventStore` + `CharacterTracker`
7. Also parse gamelog for current session

### event_store.py — In-Memory Indexed Store

Thread-safe, append-only. Three indexes:

| Index | Type | Purpose |
|-------|------|---------|
| `_events` | `list[GameEvent]` | Sequential access |
| `_by_type` | `dict[EventType, list[int]]` | "All deaths" queries |
| `_by_unit` | `dict[int, list[int]]` | "Everything about Urist" queries |

**Unit ID extraction** inspects typed fields (victim, attacker, child, etc.) and dict values for `unit_id` keys. Non-zero IDs only.

**Query methods:** `events_by_type()`, `events_for_unit()`, `events_in_season()`, `events_in_range()`, `recent_events(n)`

---

## Stage 4a: LLM Path (Story Generation)

### context_builder.py — `_format_event()`

Simple one-liner format for LLM consumption:
```
[Summer 251] DEATH: Urist McName died (drowning)
[Spring 252] BIRTH: A child was born to the fortress
[Autumn 251] PROFESSION_CHANGE: Urist changed profession
```

### context_builder.py — `build_chronicle_context()`

1. Query `event_store.events_in_season(year, season)` (fallback: `recent_events(30)`)
2. Format each event with `_format_event()`
3. Extract character summaries for event participants (cap: 10 characters)
4. Assemble `StoryContext` with events_text, character_text, lore_text
5. Trim to token budget (50% events, 25% characters, 25% lore)

### chronicle.py — `generate_chronicle()`

1. `load_game_state()` → EventStore, CharacterTracker, WorldLore, metadata
2. `build_chronicle_context()` → StoryContext
3. Enrich with: narrative dwarf descriptions, fortress setting, player notes, quests, highlights
4. Add previous chronicle summary for continuity (first 500 chars of prior entry)
5. Add civilization lore from legends if available
6. Render system + user prompts
7. LLM generates story
8. Append to journal file

---

## Stage 4b: Web Display Path

### event_renderer.py — `describe_event()` / `describe_event_linked()`

25+ handlers via `match` on `event.get("type")`. Used for **legends events** on web UI.

Resolution functions convert IDs to names:
- `_resolve_hf(legends, hfid)` → historical figure name
- `_resolve_site(legends, site_id)` → site name
- `_resolve_civ(legends, entity_id)` → civilization name
- `_resolve_artifact(legends, artifact_id)` → artifact name

**Linked mode** wraps names in `[[name]]` for clickable hotlinks in web templates.

Example outputs:
```
"Urist McName was killed by Goblin Captain Snaga at Mountainhome"
"[[Urist McName]] became Mayor of [[The Gilded Halls]]"
```

---

## Adding a New Event Type — Checklist

1. **`storyteller-events.lua`** — Add detection logic (poll function or eventful hook) + JSON writing
2. **`schema/events.py`** — Add `EventType` enum value. Optionally add typed `XxxData` + `XxxEvent` models (or leave as dict-based)
3. **`ingestion/dfhack_json_parser.py`** — Add `match` case to parse JSON into model
4. **`context/context_builder.py`** — Ensure `_format_event()` handles the new type (dict-based events get generic formatting)
5. **`context/event_renderer.py`** — Add handler if the event should appear in legends/web view (optional)
