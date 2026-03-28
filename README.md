# df-storyteller

A storytelling companion for [Dwarf Fortress](https://store.steampowered.com/app/975370/Dwarf_Fortress/). Captures game events, dwarf personalities, and world history through [DFHack](https://dfhack.org/), then generates AI-written narratives grounded in your actual gameplay.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **[Full Documentation on the Wiki](https://github.com/Been012/df-storyteller/wiki)**

## Features

### Narrative Generation
- **Fortress Chronicles** — Seasonal narratives tracking what's changing in your fortress
- **Dwarf Diaries** — First-person journal entries shaped by personality, beliefs, and stress
- **Character Biographies** — Dated entries that evolve as dwarves change over time
- **Death Eulogies** — Memorial narratives for fallen dwarves
- **Battle Reports** — Dramatic combat accounts written by survivors or the fortress chronicler
- **Epic Sagas** — World history narratives from legends data
- **Fortress Gazette** — A dwarven newspaper with five sections, written by the fortress's best writer

### Quest System
- **AI-Generated Quests** — Based on your actual fortress state, grounded in real DF mechanics
- **Narrative-Driven** — Quests that drive the story (character arcs, threats, faith, ambition)
- **Difficulty Tiers** — Easy, Medium, Hard, Legendary
- **Completion Narratives** — AI writes how the quest was fulfilled, feeds into future chronicles

### Visualization & Data
- **Relationship Web** — Interactive force-directed graph of fortress connections
- **Pantheon** — Deity worship chart with sphere descriptions from legends
- **Combat Log** — Blow-by-blow fight details with siege grouping
- **Chat Log** — Dwarf conversations with AI social summaries
- **Lore Browser** — Searchable world history with hover tooltips (kill counts, battle forces, relationships)
- **Live Event Feed** — Real-time game events via WebSocket

## Screenshots

### Chronicle
![Chronicle](docs/screenshots/Chronicle.png)

### Dwarves
![Dwarves](docs/screenshots/dwarves.png)

### Relationship Web
![Relationship Web](docs/screenshots/relationship_web.png)

### Pantheon
![Pantheon](docs/screenshots/Pantheon.png)

### Events
![Events](docs/screenshots/events.png)

### Lore
![Lore](docs/screenshots/legends.png)

### Quests
![Quests](docs/screenshots/quests.png)

### Gazette
![Gazette](docs/screenshots/gazette.png)

## Quick Start

```bash
# Install
git clone https://github.com/Been012/df-storyteller.git
cd df-storyteller
pip install -e ".[dev]"

# Configure (one time)
python -m df_storyteller init

# In DFHack console (first time per fortress)
storyteller-begin

# Launch web UI
python -m df_storyteller serve
```

## Requirements

- **Dwarf Fortress** (Steam / DF Premium recommended)
- **DFHack** (Steam Workshop or [dfhack.org](https://dfhack.org/))
- **Python 3.11+**
- **An LLM provider**: [Ollama](https://ollama.com/) (free, local), [Claude](https://console.anthropic.com/), or [OpenAI](https://platform.openai.com/)

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2
- **Frontend**: Jinja2 templates, vanilla CSS/JS (no build step)
- **Game integration**: DFHack Lua scripts
- **LLM**: Anthropic SDK, OpenAI SDK, Ollama REST API (with thinking model support)
- **All narratives grounded in DF mechanics** — the AI knows squad sizes, siege thresholds, temple values, what players can and cannot control

## Documentation

See the **[Wiki](https://github.com/Been012/df-storyteller/wiki)** for:
- [Installation & Setup](https://github.com/Been012/df-storyteller/wiki/Installation)
- [Architecture](https://github.com/Been012/df-storyteller/wiki/Architecture)
- [Configuration](https://github.com/Been012/df-storyteller/wiki/Configuration)
- [LLM Integration](https://github.com/Been012/df-storyteller/wiki/LLM-Integration)
- Feature guides for every tab

## License

MIT
