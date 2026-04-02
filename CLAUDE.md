# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**df-storyteller** — A web-based storytelling companion for Dwarf Fortress. Captures game data via DFHack Lua scripts, parses legends XML exports, and generates AI-written narratives grounded in actual game events, dwarf personalities, and world history. Features a fantasy-themed web UI with live event feed, character sheets, and a world lore browser.

## Build & Run

```bash
# Install in development mode
pip install -e ".[dev]"

# One-time setup (prompts for DF path, LLM provider, API key)
python -m df_storyteller init

# Launch web UI (opens browser at localhost:8000)
python -m df_storyteller serve

# CLI commands (still work alongside web UI)
python -m df_storyteller status
python -m df_storyteller dwarves --detail
python -m df_storyteller chronicle
python -m df_storyteller bio "Urist"
python -m df_storyteller saga

# In DFHack console (first time per fortress):
# storyteller-begin              # Initial snapshot + start events
# storyteller-begin --yes        # Same + export legends
# storyteller-snapshot           # Manual snapshot (events auto-start on map load)
# storyteller-events status      # Check event monitoring
# storyteller-events debug       # Manual poll + show all dwarf state

# Run tests
pytest
pytest tests/test_gamelog_parser.py -v
```

## Architecture

```
┌─────────────────────────────────────┐
│ DWARF FORTRESS (DFHack Lua)         │
│  storyteller-begin.lua              │  ← First-time setup + snapshot
│  storyteller-events.lua             │  ← Continuous event monitoring
│  storyteller-snapshot.lua           │  ← Delegates to begin --snapshot-only
│    ↓                                │
│  JSON files → storyteller_events/   │  ← Per-world subfolders
│               {world_folder}/       │
└─────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────┐
│ PYTHON BACKEND                       │
│  context/loader.py                  │  ← Loads snapshots + events + legends
│    ↓                                │     Merges sibling folders (region2 + autosave 1)
│  context/narrative_formatter.py     │  ← Interprets raw data → prose descriptions
│  context/notes_store.py             │  ← Player notes (suspicion, fact, rumor, etc.)
│    ↓                                │
│  stories/chronicle.py               │  ← Season chronicles with event context
│  stories/biography.py               │  ← Dated bio entries that track change
│  stories/saga.py                    │  ← World history from legends
│    ↓                                │
│  llm/ (Claude/OpenAI/Ollama)        │  ← LLM-agnostic provider layer
│    ↓                                │
│  web/app.py (FastAPI)               │  ← Web UI server
│  web/templates/ (Jinja2)            │  ← Fantasy parchment theme
└─────────────────────────────────────┘
```

**Dependency direction**: `ingestion → schema ← context → llm → stories ← web`. Never import from `llm/` in `ingestion/` or `schema/`.

## Portrait System

Generates pixel-accurate dwarf portraits from DF's own sprite sheets. Self-contained module at `src/df_storyteller/portraits/` — no dependencies on the rest of df_storyteller. Also published as standalone package [df-portrait-compositor](https://github.com/Been012/df-portrait-compositor).

- **5 races**: DWARF, ELF, HUMAN, GOBLIN, KOBOLD — each with race-specific sprite sheets and palettes.
- **Compositor** (`compositor.py`): Parses DF's graphics definition file, evaluates layer conditions (tissue color/length/shaping, body part modifiers, equipment, syndromes), composites matching tiles with palette recoloring.
- **Age groups**: BABY (<1), CHILD (1-12), PORTRAIT (12+) layer sets with different sprite sheets.
- **Clothing**: Dye color detection via `dye_profile.color_index`, HSV tinting at 40% saturation, quality tier tiles, material flag matching.
- **Creature sprites** (`creature_sprites.py`): 504 pre-made creature portraits (domestic, surface, underground, aquatic).
- **Key gotchas**: Male tissue layout [6,7]=HAIR not [3]=MOUSTACHE. Hair palette source row varies per race (human=row 12, others=row 0). DF graphics uses `PONY_TAILS` (plural) but tissue enum uses `PONY_TAIL`. `BP_MISSING` must be rejected or scar tiles render as "hats".
- **Unsolved**: Procedural creature portraits (demons, forgotten beasts) — `pcg_layering` enum not mapped by DFHack. Code saved in `experimental/beast_compositor.py`.

## Key Architecture Decisions

### DFHack Data Bridge
- **File-based communication** between DF and Python. Lua writes JSON files, Python reads them. No direct RPC — simpler and more reliable.
- **Per-world subfolders** under `storyteller_events/`. The folder name comes from `dfhack.world.ReadWorldFolder()` which can change between loads (e.g. `region2` vs `autosave 1`). The Python loader merges folders with matching fortress identity (same `civ_id` + `fortress_name`).
- **Auto-start via `onMapLoad.init`** — event monitoring begins when any fortress loads. Auto-snapshot on season change.
- **Global state in Lua** via `dfhack.storyteller_state` — local variables don't persist across script reinvocations in DFHack. All state (enabled, sequence, baselines) must be stored on this global table.
- **DFHack eventful hooks** (replaced gamelog parsing) — the primary event source is now DFHack's `eventful` plugin hooks, not gamelog.txt regex. Hooks used: `onReport` (chat, combat text, 50+ report categories), `onUnitAttack` (combat with full attacker/defender names), `onItemCreated` (artifacts), `onInvasion` (sieges), `onUnitNewActive` (migrants, invaders), `onSyndrome` (werebeast curses, syndromes), `onInventoryChange` (equipment changes), `onInteraction` (magic/abilities). Each hook requires `eventful.enableEvent(eventType, 0)` to be called before it will fire.
- **Autosave resilience** — event monitor dynamically updates `state.output_dir` when `ReadWorldFolder()` changes (e.g. `waa` → `autosave 1` → `autosave 2`). All runtime functions read from `state.output_dir`, not the local `output_dir` variable. No hooks are cleared, no state is lost. The web UI auto-switches to the newest folder with the same fortress identity.
- **Migrant pre-seeding** — when a dwarf is first seen in `poll_changes()`, ALL state (relationships, profession, stress) is pre-seeded and detection is skipped for that poll cycle via `goto continue`. This prevents migrants' existing bonds from triggering as "new" events.
- **Combat report buffering** — `onReport` can fire before `onUnitAttack` for the same blow. Orphaned combat reports are buffered in `state.orphan_combat_reports` and retroactively attached when `onUnitAttack` fires.
- **Adventure mode guard** — all hooks and polls check `df.global.gamemode == df.game_mode.DWARF` before processing to avoid crashes in adventure mode or legends mode.

### Session Identity
- **`.session_info` file** written per world folder with `site_id`, `civ_id`, `fortress_name`, `world_name`. Used to merge data across world folder renames (e.g. `region2` vs `autosave 1`).
- **`session_ids_by_site`** — the Python loader uses `site_id` as the primary key for matching fortress sessions across different folder names.
- **World switcher** in the web UI shows fortress names derived from session identity, not raw folder names.

### Legends Data
- **Two XML files**: `*-legends.xml` (basic — has names, events, descriptions) and `*-legends_plus.xml` (extended — has race, type, child entities, worship IDs, professions). Both must be parsed and merged.
- **CP437 encoding** — DF writes XML with a UTF-8 declaration but embeds CP437 bytes for diacritics (ö, û, â). Parser tries UTF-8 first, falls back to CP437 if replacement chars detected.
- **Pre-computed indexes** via `LegendsData.build_indexes()` — war lookups and HF event counts are O(1) dict access, not O(n) scans.
- **Background preload** at server startup so the Lore tab loads instantly.

### Web UI
- **FastAPI + Jinja2 + vanilla JS** — no npm/build step. Fantasy parchment CSS theme.
- **Game state caching** with auto-invalidation when new snapshots appear. 5-minute TTL, but checks snapshot file modification times.
- **Legends data loaded lazily** — `skip_legends=True` for most pages, only the Lore tab loads the full XML.
- **True LLM streaming** — All providers implement `stream_generate()` with real token-by-token streaming. Story routes use `prepare_*()` functions to build prompts, then stream via `provider.stream_generate()` with a post-generation save callback. No simulated word-by-word delays.
- **Gamelog auto-detection** — Falls back to `{df_install}/gamelog.txt` when `config.paths.gamelog` is empty. Note: gamelog is now a secondary/fallback source; primary event capture uses DFHack eventful hooks.

### Story Generation
- **Chronicles**: One per season, replaceable. Include captured events + fortress context + player notes + previous chronicle summary for continuity. Focus on changes, not static descriptions.
- **Biographies**: Dated entries that stack over time. Each entry sees previous entries and focuses on what changed. Saved to `stories/bio_{unit_id}.json`.
- **Player notes**: 7 tag types (Suspicion, Fact, Theory, Rumor, Secret, Foreshadow, Mood) with per-tag LLM instructions. Per-dwarf and fortress-wide. Stored in `stories/player_notes.json`.
- **Name hotlinking**: Dwarf names in stories are clickable links to character sheets. Diacritics handled via `normalize_name()` for ASCII-insensitive matching.

## DF Version Compatibility

**Target: DF Premium (Steam release).** Always verify DFHack APIs against the Steam version, not classic DF.

These things vary between DF versions and have caused bugs:
- `unit.relations.spouse_id` / `mother_id` / `father_id` don't exist in DF Premium — use `histfig_links` on the historical figure (`df.historical_figure.find(unit.hist_figure_id).histfig_links`) for all relationships (family, friends, grudges, lovers). Fallback: `unit.relationship_ids.Spouse` (capitalized enum).
- `unit.age` doesn't exist — use `dfhack.units.getAge(unit)` instead
- `unit.flags1.dead` doesn't exist — use `dfhack.units.isAlive(unit)`
- `os.execute()` is sandboxed — use `dfhack.filesystem.mkdir_recursive()`
- `eventful.onTick` doesn't exist — use `dfhack.timeout(ticks, 'ticks', callback)` for polling
- `eventful.enableEvent(TICK, ...)` is rejected — TICK is explicitly excluded
- `isCitizen()` may not match all fortress dwarves — use race check + `isFortControlled()` as fallback
- `reqscript()` doesn't work with hyphens — inline all config, don't use shared modules
- `dfhack.units.getReadableName()` returns CP437 — wrap with `dfhack.df2utf()`
- `dfhack.TranslateName` may not exist — use `dfhack.translation.translateName()` with fallback
- `df.job_skill(id)` as function call fails — use `df.job_skill.attrs[id].caption` or `df.job_skill[id]`

## Strict Rules

### DFHack Documentation
- **Always reference DFHack docs** at https://docs.dfhack.org/en/stable/ when writing or modifying Lua scripts.
- Key DFHack Lua modules: `dfhack.units`, `dfhack.world`, `dfhack.translation`, `dfhack.military`, `eventful` plugin, `json` module, `dfhack.filesystem`.
- When adding new event types, verify the DFHack API supports the required hooks/data access before implementing.

### DFHack Lua Scripts
- **State must use `dfhack.storyteller_state` global** — local variables reset on each script invocation.
- Use DFHack's `json.encode()` for serialization (`local json = require('json')`).
- Wrap all callbacks in `pcall` for error resilience.
- Write files atomically: write to `.tmp`, then `os.rename()` to `.json`.
- Always use `dfhack.df2utf()` on names from `getReadableName()`.
- Entity metadata (`_entity_type`, `_child_ids`, `_worship_id`, `_profession`) is stored as custom attributes on Pydantic models via `# type: ignore[attr-defined]`.

### Python Code
- Python 3.11+ required. Use modern syntax (match statements, `X | Y` unions, etc.).
- All data models use **Pydantic v2** with strict validation.
- Type hints on all function signatures.
- Async for LLM calls. Ollama uses sync `httpx.Client` in a thread executor (async httpx has compatibility issues).
- No bare `except` clauses — always catch specific exceptions.
- All file reads of DF-generated content must use `encoding="utf-8", errors="replace"`.

### Event Schema Consistency
- New event types must be added in **both** `storyteller-events.lua` AND `schema/events.py` AND `dfhack_json_parser.py` (match statement).
- Change-detection events (profession_change, noble_appointment, etc.) are stored as dict data, not typed Pydantic models.
- The `context_builder._format_event()` function must handle both typed and dict-based event data.

### Legends XML Parsing
- Parser reads full file into memory (necessary for CP437 fallback encoding). Not true streaming despite using iterparse.
- Both `*-legends.xml` and `*-legends_plus.xml` must be loaded and merged. Basic has names/descriptions/events, plus has race/type/child IDs/worship IDs.
- Cultural form descriptions are in basic legends only. Names are in plus only. Merge by ID.
- Call `build_indexes()` after parsing for O(1) lookups.

### Config
- Config stored at `~/.df-storyteller/config.toml`. Stories/notes at `~/.df-storyteller/stories/`.
- `output_dir` must be absolute path (relative paths cause data loss depending on CWD).
- Old configs without new fields get Pydantic defaults silently.
- API keys stored in config file, fallback to environment variables.
- LLM tuning params: `temperature`, `top_p`, `repetition_penalty` on `LLMConfig`. Ollama-specific: `num_ctx` (context window, default 32768 — Ollama's own default of 2048 is too small).
- `story.author_instructions` — free-text appended to all story system prompts via `StoryContext.author_instructions`.

### Testing
- All parsers have tests with fixture files in `tests/fixtures/`.
- LLM provider tests use mocked responses — never call real APIs in tests.
- No test requires a running Dwarf Fortress instance.
- Web app routes tested via `test_route_smoke.py` (page loads) and `test_router_logic.py` (API behaviour).
- Security tests in `test_web_security.py` — patch `prepare_*` functions (not `generate_*`) since routes now use the prepare/stream pattern.
