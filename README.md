# df-storyteller

A storytelling companion for [Dwarf Fortress](https://store.steampowered.com/app/975370/Dwarf_Fortress/). Captures game events, dwarf personalities, and world history through [DFHack](https://dfhack.org/), then generates AI-written narratives grounded in your actual gameplay.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## What It Does

- **Fortress Chronicles** — Seasonal narratives that track what's changing in your fortress. Role assignments, migrations, conflicts, moods — each entry builds on the last.
- **Character Biographies** — Dated entries that evolve as your dwarves do. A miner who becomes militia commander, gets injured in a siege, and falls into depression gets a biography that reflects that arc.
- **Epic Sagas** — World history narratives drawn from legends data. Analyzes battle outcomes, civilization power dynamics, beast attacks, and religious conflicts to identify overarching themes.
- **Live Event Feed** — Real-time tracking of game events via WebSocket.
- **World Lore Browser** — Searchable database of civilizations, wars, battles, artifacts, historical figures, assumed identities, written works, and cultural forms from your world.
- **Player Notes** — Influence stories with your own observations. Tag notes as Suspicion, Fact, Theory, Rumor, Secret, Foreshadow, or Mood — each tag controls how the LLM uses the information.

## Screenshots

*Coming soon*

## Requirements

- **Dwarf Fortress** (Steam or classic)
- **DFHack** (Steam Workshop or [dfhack.org](https://dfhack.org/))
- **Python 3.11+**
- **An LLM provider** (one of):
  - [Ollama](https://ollama.com/) — free, runs locally, no API key needed
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

For richer narratives with world lore, use DFHack's `open-legends` command in-game to export your world's history. This provides civilization data, wars, historical figures, artifacts, and more.

### 4. Launch the web UI

```bash
python -m df_storyteller serve
```

Opens your browser at `http://localhost:8000` with the full storytelling interface.

## Web UI

The interface uses a fantasy parchment theme with five tabs:

| Tab | Description |
|-----|-------------|
| **Chronicle** | Seasonal journal. Generate entries that reference actual events. Fortress-wide player notes. |
| **Dwarves** | Character sheets with personality traits, skills, attributes. Player notes per dwarf. Dated biography timeline. |
| **Events** | Live feed of game events — role changes, migrations, deaths, season changes. Grouped by season. |
| **Lore** | Searchable world history — civilizations with religions/guilds, wars with battle details, historical figures, artifacts, assumed identities, cultural forms with full descriptions. |
| **Settings** | LLM provider, API key, story length controls. |

### Features

- **Dwarf name hotlinks** — Names in stories link to character sheets
- **Cross-reference search** — Search any name across all lore data
- **Player notes** — 7 tag types (Suspicion, Fact, Theory, Rumor, Secret, Foreshadow, Mood) that influence how the LLM writes
- **Assumed identity spoiler protection** — Hidden identities (vampires, spies) are collapsed with a warning
- **Auto-snapshots** — Dwarf data refreshes every season change
- **Multi-world support** — Each world gets its own data folder, merged across save names

## How It Works

```
Dwarf Fortress (DFHack Lua)
  storyteller-begin.lua      → Initial snapshot + start events
  storyteller-events.lua     → Polls for changes every ~2 seconds of game time
     ↓
  JSON files in storyteller_events/{world}/
     ↓
Python Backend (FastAPI)
  loader.py                  → Merges snapshots + events + legends
  narrative_formatter.py     → Interprets raw data into prose descriptions
  notes_store.py             → Player notes with tag system
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
| Relationships (spouse, family) | DFHack (`unit.relations`) |
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

### Legends data parsed

Both `*-legends.xml` and `*-legends_plus.xml` are loaded and merged:

- Civilizations with race, type, child entities (religions, guilds)
- Historical figures with spheres (deities), birth/death years
- Wars with named battles, attacker/defender races, casualties, outcomes
- Artifacts with type, material, holders
- Assumed identities (vampires, spies)
- Written works (poems, compositions) with authors
- Relationships between figures
- Geographic features (mountains, rivers, landmasses)
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
narrative_style = "dramatic"
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (33 tests)
pytest -v

# Run specific test
pytest tests/test_gamelog_parser.py::test_parse_death_announcement -v
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2
- **Frontend**: Jinja2 templates, vanilla CSS/JS (no build step)
- **Game integration**: DFHack Lua scripts
- **LLM**: Anthropic SDK, OpenAI SDK, Ollama REST API
- **Data**: XML parsing (iterparse), JSON file-based IPC

## Known Limitations

- Legends XML map exports (BMP) are broken in current DF Steam version
- `dfhack.units.getGoalType()` returns empty in some DF versions
- Gamelog parsing is built but disabled (contains cross-world data)
- True LLM streaming not yet implemented (simulated word-by-word)
- Web app routes don't have automated tests yet

## License

MIT
