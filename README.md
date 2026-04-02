# df-storyteller

A companion journal and legends browser for [Dwarf Fortress](https://store.steampowered.com/app/975370/Dwarf_Fortress/). Track your fortress, explore world history, chart relationships, map your world, and document the stories that emerge from your gameplay. Optionally use AI to help write narratives — or write everything yourself.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **[Full Documentation on the Wiki](https://github.com/Been012/df-storyteller/wiki)**

## Features

### Legends Browser
Explore your world's complete history through an interactive legends viewer — every figure, civilization, site, artifact, war, and event, all cross-linked and searchable.

- **Detail Pages** — Dedicated pages for historical figures (with family trees, intrigue plots, emotional bonds, skills, kill lists), civilizations (festivals, honors, wars, population), sites (structures, properties, events), artifacts (contents, creator), and wars/battles (factions, casualties, combatants)
- **Geography Pages** — Searchable regions, rivers, mountain peaks, and constructions with event timelines and clickable cross-references
- **World Map** — Terrain map generated from region data with Leaflet.js. Site markers by type and owner race. Roads and tunnels as toggleable polylines
- **Festival Calendar** — Named festivals with full schedules (processions, ceremonies, competitions, dances, poetry, wrestling). Dwarven calendar grid (Granite–Obsidian). Competition winners with event types
- **Intrigue & Schemes** — 7,900+ figures with active plots: assassinations, corruption networks, undead world conquest, infiltration. Actor roles, strategies, promised immortality
- **Emotional Bonds** — Love, respect, trust, loyalty, and fear scores between figures, visualized as centered bar charts
- **Family Trees** — Interactive hierarchical graphs showing parents, children, spouses, and siblings across generations
- **Charts & Statistics** — Race distribution, event timeline, per-entity activity charts, warfare networks
- **97 Event Types** — Every DF historical event rendered with human-readable descriptions and clickable entity names
- **Cultural Forms** — Searchable poetic, musical, and dance forms with full descriptions, meter, rhythm, instruments, and scales
- **Clickable Everything** — All entity references across legends pages are clickable links to their detail pages

### Fortress Journal
Track what's happening in your fortress with character sheets, event feeds, and seasonal chronicles.

- **Character Sheets** — Every dwarf with personality traits, beliefs, skills (with level badges), relationships, combat record, equipment (grouped by Weapons/Armor/Clothing), wounds, stress mood from DFHack, and pets
- **Fortress Chronicles** — Seasonal entries tracking migrations, conflicts, deaths, and changes. Write your own or generate with AI
- **Dwarf Biographies & Diaries** — Dated entries that build over time. Write in your own voice or let AI draft from personality data
- **Relationship Web** — Interactive force-directed graph of fortress connections, plus a family tree view from legends data
- **Live Event Feed** — Real-time game events captured via DFHack hooks (not gamelog parsing). Combat with full dwarf names, chat with unit IDs, 50+ report types (megabeast arrivals, marriages, masterpieces, cave collapses, deity curses)
- **Military Dashboard** — Squad roster with combat skills, top warriors leaderboard (kills, attacks, defenses), recent engagements grouped by target, combat activity charts, military event timeline
- **Fortress Dashboard** — Population over time, migration waves, milestone timeline
- **World Switcher** — Switch between fortresses showing fortress names (not folder names). Same fortress across multiple save slots appears as one entry. Retire/reclaim preserves event history via session_ids_by_site
- **In-Game Calendar** — Events display with proper dwarven calendar dates (day/month/year)
- **Fortress Gazette** — A dwarven newspaper with five sections. Newspaper-style two-column layout

### Cross-Referencing
Connect your fortress stories to the wider world history.

- **Lore Pins** — Bookmark any legends entity (figures, wars, artifacts, festivals, cultural forms) and access them from a global sidebar on every page. Press `P` to toggle
- **`[[Hotlinks]]`** — Type `[[name]]` in any chronicle, biography, or diary entry to create a clickable link to the corresponding legends page. Works for figures, sites, civilizations, artifacts, wars, written works, festivals, and cultural forms
- **View in Legends** — Jump from any fortress dwarf to their historical figure page with full legends data

### Player Agency
Shape the narrative yourself — AI is optional, not required.

- **Manual Writing Everywhere** — Write chronicles, biographies, diary entries, sagas, gazette editions, and quest resolutions without any AI
- **Dwarf Highlights** — Mark dwarves as Protagonist, Antagonist, or Watchlist
- **Player Notes** — 8 tag types (Suspicion, Fact, Theory, Rumor, Secret, Foreshadow, Mood, What If)
- **Quest System** — Create quests with category and difficulty, resolve with comments
- **Inline Editing** — Edit chronicles, quests, and gazette editions after creation

### AI Narrative Generation (Optional)
If you want AI assistance, connect an LLM provider. All generation is grounded in actual game data.

- Fortress chronicles, dwarf biographies, diary entries, death eulogies, battle reports, epic sagas, gazette editions, quest narratives
- **True streaming** — text appears token-by-token as the AI generates, not after a long wait
- Supports Ollama (free, local), Anthropic Claude, and OpenAI
- **Fine-tuning controls** — temperature, top P, repetition penalty sliders. Custom author instructions to guide tone and style (e.g. "Write like a drunken tavern bard")
- VRAM-tiered model recommendations for Ollama (4GB to 24GB+)
- AI narratives reference real dwarf personalities, events, relationships, and world history
- No AI required — every feature works in manual mode

## Screenshots

### Dwarf Portraits
Pixel-accurate portraits generated from DF's own sprite sheets. Matches in-game appearance including hair, eyes, nose, clothing with dye colors. Supports all 5 races (Dwarf, Elf, Human, Goblin, Kobold), children, and babies.

![Portrait comparison — generated vs in-game](docs/screenshots/comparison.png)

### Character Sheets
Full character sheets with generated portrait, personality traits, beliefs, skills with level badges, relationships, combat record, and equipment.

![Character sheet](docs/screenshots/character-sheet.png)

### Visitors & Traders
Race-specific portraits for visitors, traders, and diplomats. 504 creature sprites for livestock and wild animals.

![Visitors with portraits](docs/screenshots/visitors.png)

### Animals
Livestock and wild animals with creature portrait sprites from DF's sprite sheets.

![Animals with sprites](docs/screenshots/animals.png)

### Event Feed
Real-time events captured via DFHack hooks — combat, migrations, caravans, skill milestones, noble appointments. Dwarven calendar dates.

![Event feed](docs/screenshots/event_feed.png)

### Combat Log
Blow-by-blow combat narratives with grouped fights, participant summaries, and fatal blow highlights.

![Combat logs](docs/screenshots/combat-logs.png)

### Chronicle
Seasonal fortress narratives — write your own or generate with AI. Use `[[name]]` to hotlink any legends entity.

![Chronicle](docs/screenshots/Chronicle.png)

### Military Dashboard
Squad roster, top warriors leaderboard, combat activity charts, and recent engagements.

![Military dashboard](docs/screenshots/military_dashboard.png)

### Fortress Dashboard
Population timeline, migration waves, milestone events, and recent activity with portraits.

![Fortress dashboard](docs/screenshots/fort_dashboard.png)

### Legends Figure
Historical figure detail pages with family trees, intrigue plots, emotional bonds, kill lists, and cross-linked references.

![Legends figure](docs/screenshots/legends_figure.png)

### World Map
Terrain map generated from region data with Leaflet.js. Site markers by type and owner race. Roads and tunnels as toggleable polylines.

![World map](docs/screenshots/world_map.png)

### Lore Pins
Bookmark any legends entity and access from a global sidebar on every page. Reference pinned items in stories with `[[wiki links]]`.

![Lore pins](docs/screenshots/pins.png)

### DFHack Integration
One command to capture fortress data. Real-time event monitoring runs automatically.

![DFHack console](docs/screenshots/dfhack.png)

## Quick Start

**Prerequisites:** [Python 3.11+](https://www.python.org/downloads/) — during install, check **"Add Python to PATH"**.

**Install and run:**
```bash
pip install df-storyteller
df-storyteller init
df-storyteller serve
```

> **Note:** If `df-storyteller` isn't recognized as a command, use `python -m df_storyteller` instead (underscores, not dashes). This happens on some Windows installs where Python scripts aren't on the PATH.

**In DFHack console (first time per fortress):**
```
storyteller-begin
```

**Update to the latest version:**
```bash
pip install --upgrade df-storyteller
```

**Or install from source:**
```bash
git clone https://github.com/Been012/df-storyteller.git
cd df-storyteller
pip install -e .
python -m df_storyteller init
python -m df_storyteller serve
```

## Requirements

- **Dwarf Fortress** v50.x (Steam / DF Premium) — tested with v50.14
- **DFHack** v50.14-r1+ (Steam Workshop or [dfhack.org](https://dfhack.org/))
- **Python 3.11+**
- **An LLM provider** (optional — not needed for journal/legends features):
  - [Ollama](https://ollama.com/) — free, runs locally, no API key needed
  - [Anthropic Claude](https://console.anthropic.com/) — API key required
  - [OpenAI](https://platform.openai.com/) — API key required

> **Note:** This tool uses DF Premium (Steam) APIs. Classic DF (pre-Steam) is not supported.

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2
- **Frontend**: Jinja2 templates, vanilla CSS/JS (no build step), Chart.js, Leaflet.js, vis-network (CDN)
- **Legends**: Pillow (terrain map generation), dwarven calendar mapping, 97 event type renderer
- **Game integration**: DFHack Lua scripts with eventful hooks (onReport, onUnitAttack, onInventoryChange, etc.), snapshots, legends export
- **LLM** (optional): Anthropic SDK, OpenAI SDK, Ollama REST API

## Documentation

See the **[Wiki](https://github.com/Been012/df-storyteller/wiki)** for:
- [Installation & Setup](https://github.com/Been012/df-storyteller/wiki/Installation)
- [Architecture](https://github.com/Been012/df-storyteller/wiki/Architecture)
- [Configuration](https://github.com/Been012/df-storyteller/wiki/Configuration)
- [LLM Integration](https://github.com/Been012/df-storyteller/wiki/LLM-Integration)
- Feature guides for every tab

## Notes

- Designed to run **locally on your machine** (localhost). Not intended for public servers.
- **Developed and tested on Windows** with DF Premium (Steam). Should work on Mac and Linux — all code uses cross-platform libraries — but these platforms are untested. [Report issues here](https://github.com/Been012/df-storyteller/issues/new?template=bug_report.md).
- Config and stories stored at `~/.df-storyteller/`.

## License

MIT
