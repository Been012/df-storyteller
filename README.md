# df-storyteller

A storytelling companion for [Dwarf Fortress](https://store.steampowered.com/app/975370/Dwarf_Fortress/). Captures game events, dwarf personalities, and world history through [DFHack](https://dfhack.org/), then generates AI-written narratives grounded in your actual gameplay.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## What It Does

### Narrative Generation
- **Fortress Chronicles** — Seasonal narratives that track what's changing in your fortress. Role assignments, migrations, conflicts, moods — each entry builds on the last.
- **Character Biographies** — Dated entries that evolve as your dwarves do. A miner who becomes militia commander, gets injured in a siege, and falls into depression gets a biography that reflects that arc.
- **Dwarf Diary Entries** — First-person journal entries written in the dwarf's voice. Personality traits, beliefs, and stress level heavily influence the tone — an anxious mason writes differently than a confident warrior.
- **Death Eulogies** — When a dwarf dies, generate a memorial eulogy reflecting their life, achievements, and legacy. Appears in their biography timeline.
- **Epic Sagas** — World history narratives drawn from legends data. Saved persistently per fortress.
- **Battle Reports** — Dramatic narratives of combat encounters written by the combatant (first-person if they survived), the fortress chronicler, or a mysterious figure if no one survived. Persistent and rewritable.
- **Fortress Gazette** — A dwarven newspaper written by the fortress's best writer. Sections: The Fortress Herald, Military Dispatches, Quarry Gossip, Quest Board, and Obituaries. Newspaper-style layout with columns and masthead.

### Quest System
- **AI-Generated Quests** — Quests generated from your actual fortress state (citizens, buildings, events, religion, military, legends). Grounded in real DF mechanics — the AI knows squad sizes, siege thresholds, temple values, and what the player can and cannot control.
- **Narrative-Driven** — Quests drive the story forward with character arcs, threats, faith, legacy, and ambition — not just task lists.
- **Difficulty Tiers** — Easy, Medium, Hard, Legendary — based on actual DF progression requirements.
- **Category Filters** — Military, Construction, Religious, Crafting, Exploration, Social, Chaos.
- **Quest Completion Narratives** — When you complete a quest, AI generates a fulfillment story. Completed quests feed into future chronicles for narrative continuity.

### Data & Visualization
- **Live Event Feed** — Real-time tracking of game events via WebSocket.
- **Combat Log** — Blow-by-blow accounts of fights parsed from the gamelog. Consecutive fights grouped into siege/battle engagements. Collapsible with color-coded strikes, injuries, and outcomes.
- **Chat Log** — Dwarf conversation and sentiment tracking with AI-powered social life summaries.
- **Relationship Web** — Interactive force-directed graph showing family, friend, and rival connections across the fortress. Hover tooltips, drag, zoom, focus.
- **Pantheon** — Bar chart of deity worship across the fortress. Deity spheres from legends data. Click to expand worshipper lists.
- **World Lore Browser** — Searchable database of civilizations, wars, battles, artifacts, historical figures, assumed identities, written works, and cultural forms. Hover tooltips with rich detail (kill counts, battle forces, artifact descriptions, relationship networks).
- **Player Notes** — 8 tag types (Suspicion, Fact, Theory, Rumor, Secret, Foreshadow, Mood, What If) that influence how the LLM writes.

### Fortress Management
- **Multi-Fortress Support** — Each fortress gets isolated story storage (chronicles, bios, diaries, quests, gazette, notes, battle reports). Switch via the world dropdown.
- **Tabbed Character Sheets** — Notes, Biography, and Diary as separate tabs on each dwarf's page.
- **Combat Record** — Per-dwarf combat highlights on character sheets.

## Screenshots

*Coming soon — add screenshots to `docs/screenshots/`*

## Requirements

- **Dwarf Fortress** (Steam / DF Premium recommended)
- **DFHack** (Steam Workshop or [dfhack.org](https://dfhack.org/))
- **Python 3.11+**
- **An LLM provider** (one of):
  - [Ollama](https://ollama.com/) — free, runs locally, no API key needed (supports thinking models like gpt-oss, deepseek-r1)
  - [Anthropic Claude](https://console.anthropic.com/) — API key required
  - [OpenAI](https://platform.openai.com/) — API key required

## Installation

```bash
git clone https://github.com/Been012/df-storyteller.git
cd df-storyteller
pip install -e ".[dev]"
```

## Setup

### 1. Configure (one time)

```bash
python -m df_storyteller init
```

This prompts for your DF installation path, LLM provider, and API key. It also deploys DFHack scripts and sets up auto-start.

### 2. First fortress

Launch Dwarf Fortress, embark, then in the DFHack console:

```
storyteller-begin
```

This takes an initial snapshot of your dwarves and starts event monitoring. You only need to do this once per fortress — after that, events auto-start when you load a save.

### 3. Export world history (optional but recommended)

For richer narratives with world lore, use DFHack's `open-legends` command in-game to export your world's history. This provides civilization data, wars, historical figures, artifacts, deity spheres, and more.

### 4. Launch the web UI

```bash
python -m df_storyteller serve
```

Opens your browser at `http://localhost:8000` with the full storytelling interface.

## Web UI

The interface uses a fantasy parchment theme with eight tabs:

| Tab | Description |
|-----|-------------|
| **Chronicle** | Seasonal journal. Generate entries that reference actual events. Fortress-wide player notes. Auto-reloads after generation. |
| **Dwarves** | Character sheets with tabbed Notes/Biography/Diary. Combat record. Relationship Web and Pantheon sub-pages. Death eulogies. |
| **Events** | Live feed of game events. Combat Log with collapsible blow-by-blow and battle reports. Saved Battle Reports section for sieges. Chat Log with AI social summaries. |
| **Lore** | Searchable world history with hover tooltips showing rich detail (kill counts, relationships, battle forces, deity spheres). Epic Saga generation with persistence. |
| **Quests** | AI-generated quest board with category/difficulty filters. Narrative-driven quests grounded in DF mechanics. Completion narratives. |
| **Gazette** | Dwarven newspaper with five sections. Written by the fortress's best writer in their personality voice. Newspaper-style two-column layout. |
| **Settings** | LLM provider, API key, token length controls for all generation types. |

### Key Features

- **DF Mechanics Grounding** — All AI generation includes a comprehensive Dwarf Fortress mechanics reference (military, construction, crafting, diplomacy, missions, trade, sieges, necromancers, megabeasts) ensuring narratives are accurate to the game.
- **Dwarf name hotlinks** — Names in stories link to character sheets
- **Cross-reference search** — Search any name across all lore data
- **Lore hover tooltips** — Rich detail on hover for figures, civilizations, wars, artifacts, sites, written works
- **What If story hooks** — Player-authored hypothetical scenarios woven into chronicles
- **Assumed identity spoiler protection** — Hidden identities (vampires, spies) collapsed with a warning
- **Auto-snapshots** — Dwarf data refreshes every season change
- **Persistent stories** — Chronicles, biographies, diaries, sagas, battle reports, quests, and gazettes all saved per-fortress

## How It Works

```
Dwarf Fortress (DFHack Lua)
  storyteller-begin.lua      → Initial snapshot + start events
  storyteller-events.lua     → Polls for changes every ~2 seconds of game time
     ↓
  JSON files in storyteller_events/{world}/
     ↓
Python Backend (FastAPI)
  loader.py                  → Merges snapshots + events + legends + gamelog
  narrative_formatter.py     → Interprets raw data into prose descriptions
  df_mechanics.py            → DF mechanics reference for LLM grounding
  notes_store.py             → Player notes with tag system
  quest_store.py             → AI quest persistence
     ↓
  LLM Provider               → Claude / OpenAI / Ollama
     ↓
  Web UI (Jinja2 + vanilla JS)
```

### Data captured per dwarf

| Data | Source |
|------|--------|
| Name, profession, age | DFHack snapshot |
| 50 personality facets | DFHack (`soul.personality.traits`) |
| Beliefs and values | DFHack (`soul.personality.values`) |
| Physical attributes (strength, agility, etc.) | DFHack (`unit.body.physical_attrs`) |
| Mental attributes (creativity, focus, etc.) | DFHack (`soul.mental_attrs`) |
| Skills with readable names | DFHack (`soul.skills`) |
| Noble positions | DFHack (`getNoblePositions`) |
| Military squad | DFHack (`unit.military`) |
| Relationships (spouse, family, friends, grudges, deities) | DFHack (`histfig_links` on historical figures) |
| Equipment, wounds, stress | DFHack |
| Role changes, appointments | Event monitoring (polled) |

### Events detected

- Profession/role changes
- Noble appointments
- Military squad changes
- Stress level shifts (significant changes only)
- Migrant arrivals
- Season changes (triggers auto-snapshot)
- Deaths, building construction, job completion (via DFHack eventful plugin)
- Detailed combat (blow-by-blow from gamelog with weapon, injuries, outcomes)
- Dwarf conversations and sentiments (from gamelog conversation announcements)

### Legends data parsed

Both `*-legends.xml` and `*-legends_plus.xml` are loaded and merged:

- Civilizations with race, type, child entities (religions, guilds)
- Historical figures with spheres (deities), birth/death years, kill counts
- Wars with named battles, attacker/defender races, casualties, outcomes
- Artifacts with type, material, holders
- Sites with type, owner, event history
- Assumed identities (vampires, spies)
- Written works (poems, compositions) with authors
- Relationships between figures
- Geographic features (mountains with height/volcano status, rivers, landmasses)
- Cultural forms (poetry, music, dance) with full prose descriptions
- Beast attacks, site conquests, persecutions

## CLI Commands

```bash
python -m df_storyteller init          # One-time setup
python -m df_storyteller serve         # Launch web UI
python -m df_storyteller status        # Show data summary
python -m df_storyteller dwarves       # List dwarves (--detail for full info)
python -m df_storyteller chronicle     # Generate chronicle (CLI)
python -m df_storyteller bio "name"    # Generate biography (CLI)
python -m df_storyteller saga          # Generate world saga (CLI)
python -m df_storyteller deploy        # Re-deploy DFHack scripts
python -m df_storyteller config show   # View configuration
python -m df_storyteller config set KEY VALUE  # Set config value
```

## DFHack Commands

```
storyteller-begin              # First-time fortress setup
storyteller-begin --yes        # Setup + export legends
storyteller-begin --snapshot-only  # Just take a snapshot
storyteller-snapshot           # Take a snapshot (alias)
storyteller-events start       # Start event monitoring
storyteller-events stop        # Stop event monitoring
storyteller-events status      # Check monitoring status
storyteller-events debug       # Manual poll + show all dwarf state
```

## Configuration

Config is stored at `~/.df-storyteller/config.toml`:

```toml
[paths]
df_install = "C:\\path\\to\\Dwarf Fortress"

[llm]
provider = "ollama"  # claude | openai | ollama
api_key = ""         # For claude/openai

[llm.ollama]
base_url = "http://localhost:11434"
model = "llama3"

[story]
chronicle_max_tokens = 4096
biography_max_tokens = 1024
saga_max_tokens = 4096
chat_summary_max_tokens = 2048
gazette_max_tokens = 4096
quest_generation_max_tokens = 2048
quest_narrative_max_tokens = 1024
narrative_style = "dramatic"
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (52 tests)
pytest -v

# Run specific test
pytest tests/test_gamelog_parser.py::test_parse_death_announcement -v
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2
- **Frontend**: Jinja2 templates, vanilla CSS/JS (no build step)
- **Game integration**: DFHack Lua scripts
- **LLM**: Anthropic SDK, OpenAI SDK, Ollama REST API (with thinking model support)
- **Data**: XML parsing (iterparse), JSON file-based IPC, per-fortress storage

## Known Limitations

- Legends XML map exports (BMP) are broken in current DF Steam version
- `dfhack.units.getGoalType()` returns empty in some DF versions
- True LLM streaming not yet implemented (simulated word-by-word)
- Web app routes don't have automated tests yet
- Gamelog combat/chat parsing only covers the current session (since last fortress load)
- Deity sphere matching between legends and snapshot uses name-based heuristics (not all deities match)

## License

MIT
