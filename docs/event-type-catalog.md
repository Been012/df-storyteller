# Event Type Catalog

Complete catalog of all event types across the three sources: DFHack Lua, gamelog, and legends XML.

## Fortress Events (DFHack + Gamelog)

These events come from the running fortress. Used for chronicles, biographies, and the events page.

### Typed Pydantic Models (full schema in `schema/events.py`)

| EventType Enum | Source(s) | Pydantic Model | Key Data Fields |
|---------------|-----------|---------------|-----------------|
| `DEATH` | DFHack hook + gamelog | `DeathEvent(DeathData)` | victim: UnitRef, cause, killer: UnitRef?, age, notable_skills |
| `COMBAT` | DFHack hook + gamelog | `CombatEvent(CombatData)` | attacker: UnitRef, defender: UnitRef, weapon, body_part, is_lethal, blows: [CombatBlow], raw_text |
| `MOOD` | DFHack poll + gamelog | `MoodEvent(MoodData)` | unit: UnitRef, mood_type (fey/secretive/possessed/macabre/fell) |
| `BIRTH` | DFHack poll | `BirthEvent(BirthData)` | child: UnitRef, mother?: UnitRef, father?: UnitRef |
| `BUILDING` | DFHack hook | `BuildingEvent(BuildingData)` | building_type, name, builder?: UnitRef, location?: Location |
| `JOB` | DFHack hook | `JobEvent(JobData)` | job_type, worker?: UnitRef, result |
| `ARTIFACT` | DFHack hook + gamelog | `ArtifactEvent(ArtifactData)` | artifact_name, item_type, creator?: UnitRef, material, description |
| `SEASON_CHANGE` | DFHack poll + gamelog | `SeasonChangeEvent(SeasonChangeData)` | new_season: Season, population, fortress_wealth |

### Dict-Based Events (stored as `GameEvent` with `data: dict`)

| EventType Enum | Source | Dict Fields |
|---------------|--------|-------------|
| `PROFESSION_CHANGE` | DFHack poll | unit, old_profession, new_profession |
| `NOBLE_APPOINTMENT` | DFHack poll | unit, positions: [string] |
| `MILITARY_CHANGE` | DFHack poll | unit, squad_name, squad_id |
| `STRESS_CHANGE` | DFHack poll | unit, old_stress, new_stress |
| `MIGRANT_ARRIVED` | DFHack poll | unit |
| `MIGRATION_WAVE` | DFHack poll | new_arrivals, total_population |
| `ANNOUNCEMENT` | gamelog (fallback) | raw_text (any unrecognized gamelog line) |

### Detection Methods

| Method | Events | How |
|--------|--------|-----|
| **eventful hooks** (instant) | death, building_created, job_completed | DFHack plugin callbacks |
| **100-tick poll** (periodic) | mood, season_change, birth, profession_change, noble_appointment, military_change, stress_change, migrant_arrived, migration_wave | Compare current state vs baselines |
| **gamelog regex** | death (8 patterns), mood, artifact, season_change, combat (multi-line blocks) | Parse gamelog.txt |

### Common Fields (all fortress events)

```
event_type: EventType enum
game_year: int
game_tick: int
season: Season enum
source: EventSource (DFHACK or GAMELOG)
timestamp: datetime
data: typed model or dict
```

**Note:** Gamelog events have `unit_id=0` (no IDs available in text, only names).

---

## Legends Events (XML)

These come from DF's legends export. Used for the Lore tab and world history. Stored as raw dicts in `LegendsData.historical_events`. Rendered by `event_renderer.py` (73 explicit handlers + default fallback).

### Event Renderer Catalog

Grouped by category. Each row shows the type string matched and the output format.

#### Deaths & Combat

| Type String | Output Format |
|-------------|--------------|
| `hf died` | "{victim} was killed by {slayer} at {site}" / "{victim} died ({cause})" |
| `hf simple battle event` | "{hf1} fought {hf2} at {site}" |
| `hf wounded` | "{attacker} wounded {victim} ({body_part}) at {site}" |
| `creature devoured` | "{eater} devoured {victim} at {site}" |
| `body abused` | "The body of {hf} was {abuse_type} at {site}" |
| `change hf body state` | "The remains of {hf} became {state} at {site}" |
| `field battle` | "{attacker_civ} fought {defender_civ} in a field battle" |

#### Sites & Structures

| Type String | Output Format |
|-------------|--------------|
| `hf attacked site` | "{hf} attacked {site} ({target_civ})" |
| `hf destroyed site` | "{hf} destroyed {site}" |
| `attacked site` | "{attacker_civ} attacked {site} ({defender_civ})" |
| `plundered site` | "{attacker_civ} plundered {site}" |
| `site taken over` | "{attacker_civ} took over {site}" |
| `reclaim site` | "{civ} reclaimed {site}" |
| `created site` | "{civ} founded {site}" |
| `destroyed site` | "{civ} destroyed {site} ({defender_civ})" |
| `hf razed structure` | "{hf} razed a structure at {site}" |
| `created structure` | "{civ} built a structure in {site}" |
| `razed structure` | "{civ} razed a structure in {site}" |
| `modified building` | "A building was modified at {site}" |
| `replaced structure` | "A structure was replaced at {site}" |
| `created world construction` | "{civ} built {name}" |
| `new site leader` | "{hf} became the leader of {site}" |
| `site dispute` | "A dispute arose over {site} ({dispute_type})" |

#### Political & Social

| Type String | Output Format |
|-------------|--------------|
| `add hf entity link` | "{hf} became {position} of {civ}" / "joined" / "imprisoned by" / "enslaved by" |
| `remove hf entity link` | "{hf} was removed as {position} of {civ}" / "left" / "freed from" |
| `add hf hf link` | "{hf1} became {link_type} of {hf2}" |
| `remove hf hf link` | "{hf1} is no longer {link_type} of {hf2}" |
| `add hf site link` | "{hf} became {link_type} of {site}" |
| `remove hf site link` | "{hf} is no longer {link_type} of {site}" |
| `entity created` | "{civ} was founded" |
| `entity dissolved` | "{civ} was dissolved" |
| `entity incorporated` | "{target} was incorporated into {joiner}" |
| `entity relocate` | "{civ} relocated to {site}" |
| `entity overthrown` | "{civ} was overthrown at {site}" |
| `entity primary criminals` | "{civ} became the primary criminals of {site}" |
| `entity alliance formed` | "An alliance was formed" |
| `regionpop incorporated into entity` | "A population was incorporated into {civ}" |
| `create entity position` | "The position of {position} was created in {civ}" |
| `entity breach feature layer` | "{civ} breached a feature layer at {site}" |
| `insurrection started` | "An insurrection started against {civ} in {site}" |

#### Intrigue & Reputation

| Type String | Output Format |
|-------------|--------------|
| `hfs formed reputation relationship` | "{hf1} gained a reputation as {rep} with {hf2}" |
| `hfs formed intrigue relationship` | "{hf1} {action} {hf2}" |
| `hf relationship denied` | "{hf1} was denied a {relationship} with {hf2} ({reason})" |
| `hf convicted` | "{hf} was convicted of {crime} by {civ}" |
| `entity persecuted` | "{persecutor_civ} persecuted {target_civ} at {site}" |
| `failed intrigue corruption` | "{corruptor} failed to corrupt {target}" |
| `failed frame attempt` | "{framer} failed to frame {target} for {crime}" |
| `hf enslaved` | "{hf} was enslaved" |
| `hf interrogated` | "{target} was interrogated by {interrogator}" |

#### State Changes & Travel

| Type String | Output Format |
|-------------|--------------|
| `change hf state` | "{hf} entered a {mood} mood" / "settled" / "began wandering" / "became a refugee" |
| `change hf job` | "{hf} changed profession from {old} to {new}" |
| `changed creature type` | "{hf} was transformed from {old_race} to {new_race}" |
| `assume identity` | "{hf} assumed the identity of {identity_name}" |
| `hf travel` | "{hf} traveled" |
| `hf abducted` | "{target} was abducted by {snatcher}" |
| `hf revived` | "{hf} was raised from the dead" |
| `hf confronted` | "{hf} was confronted ({situation})" |
| `hf reunion` | "{hf1} was reunited with {hf2}" |

#### Artifacts

| Type String | Output Format |
|-------------|--------------|
| `artifact created` | "{hf} created {artifact_name}" |
| `artifact found` / `artifact recovered` | "{hf} found/recovered {artifact_name}" |
| `artifact given` | "{giver} gave {artifact_name} to {receiver}" |
| `artifact lost` / `artifact destroyed` | "{artifact_name} was lost/destroyed" |
| `artifact stored` | "{hf} stored {artifact_name}" |
| `artifact possessed` | "{hf} claimed {artifact_name}" |
| `artifact copied` | "{artifact_name} was copied" |
| `artifact claim formed` | "{hf} formed a {claim} claim on {artifact_name}" |
| `hf viewed artifact` | "{hf} viewed {artifact_name}" |

#### Knowledge & Culture

| Type String | Output Format |
|-------------|--------------|
| `hf learns secret` | "{hf} learned the secrets of {secret}" |
| `hf gains secret goal` | "{hf} gained the secret goal of {goal}" |
| `knowledge discovered` | "{hf} discovered knowledge of {knowledge}" |
| `masterpiece created item` | "{hf} created a masterwork {desc}" |
| `written content composed` | "{hf} composed a written work" |
| `musical form created` | "{hf} created a new musical form" |
| `poetic form created` | "{hf} created a new poetic form" |
| `dance form created` | "{hf} created a new dance form" |
| `building profile acquired` | "{hf} acquired a building profile" |

#### Activities & Interactions

| Type String | Output Format |
|-------------|--------------|
| `hf does interaction` | "{doer} {interaction_action} {target}" |
| `hf new pet` | "{hf} tamed {pet}" |
| `hf preach` | "{hf} preached {topic} for {civ}" |
| `hf prayed inside structure` | "{hf} prayed inside a structure" |
| `hf profaned structure` | "{hf} profaned a structure" |
| `hf disturbed structure` | "{hf} disturbed a structure" |
| `hf performed horrible experiments` | "{hf} performed horrible experiments" |
| `hf recruited unit type for entity` | "{hf} recruited {unit_type} for {civ}" |
| `hf equipment purchase` | "{hf} purchased equipment" |
| `item stolen` | "{thief} stole an item from {site}" |
| `add hf entity honor` | "{hf} was honored by {civ}" |

#### Diplomacy & Events

| Type String | Output Format |
|-------------|--------------|
| `peace accepted` | "Peace was accepted" |
| `peace rejected` | "Peace was rejected" |
| `agreement formed` | "An agreement was formed" |
| `competition` | "A competition was held by {civ} — won by {winner}" |
| `ceremony` | "A ceremony was held by {civ}" |
| `performance` | "A performance was held by {civ}" |
| `procession` | "A procession was held by {civ}" |
| `trade` | "Trade occurred" |
| `gamble` | "{hf} gambled" |
| `holy city declaration` | "{civ} declared {site} a holy city" |

#### Default Fallback

Any unmatched type string → `"{formatted_type}: {hf} at {site}"` (auto-formatted type name with title case)

---

## Adding a New Event Type — Files to Touch

### New Fortress Event (DFHack-sourced)

| # | File | What to Add |
|---|------|-------------|
| 1 | `dfhack_scripts/storyteller-events.lua` | Detection logic (poll function or eventful hook) + JSON write |
| 2 | `schema/events.py` | `EventType` enum value. Optionally: typed `XxxData` + `XxxEvent` models |
| 3 | `ingestion/dfhack_json_parser.py` | `match` case to parse JSON → model |
| 4 | `context/context_builder.py` | Handle in `_format_event()` if special formatting needed |

### New Legends Event (renderer only)

| # | File | What to Add |
|---|------|-------------|
| 1 | `context/event_renderer.py` | `match` case in `describe_event()` with output template |

### Resolution Helper Functions (event_renderer.py)

| Function | Purpose | Returns |
|----------|---------|---------|
| `_resolve_hf(legends, hfid)` | HF ID → name | `str` (name or "someone") |
| `_resolve_site(legends, site_id)` | Site ID → name | `str` (name or "a site") |
| `_resolve_civ(legends, entity_id)` | Entity ID → name | `str` (name or "a group") |
| `_resolve_artifact(legends, artifact_id)` | Artifact ID → name | `str` (name or "an artifact") |
| `_resolve_position(legends, entity_id, position_profile_id)` | Position ID → title | `str` (title or None) |
| `_at_site(legends, event)` | Extract site context | `str` (" at {site}" or "") |
| `_wrap(text)` | Wrap in `[[text]]` when linked mode active | `str` |

### Two Rendering Paths

Events are rendered differently depending on context:

| Path | Function | Format | Used For |
|------|----------|--------|----------|
| **LLM context** | `context_builder._format_event()` | `[Season Year] TYPE: details` | Chronicle/bio prompt building |
| **Web display** | `event_renderer.describe_event()` | Rich prose with name resolution | Lore tab, event pages |
| **Web linked** | `event_renderer.describe_event_linked()` | Same + `[[name]]` hotlinks | Clickable entity names in templates |
