# Player-Facing Feature Inventory

What each web UI tab does, what requires LLM, and what works in no-LLM mode.

## Navigation Tabs

Chronicle | Dwarves | Events | Dashboard | Legends | Quests | Gazette | Settings

Status bar always shows: fortress name, site name, civilization, biome, year/season, population, event count.

---

## Chronicle (`/`)

The main storytelling page — seasonal fortress narrative entries.

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| Read chronicle entries with season/year headers | No | Full access |
| Write manual chronicle entry (with `[[name]]` linking) | No | Default open |
| Edit existing entries | No | Full access |
| Add fortress-wide notes (Mood, Fact, Foreshadow, Rumor, Theory, What If) | No | Full access |
| Resolve/delete notes | No | Full access |
| Generate chronicle entry with AI (optional context field) | **Yes** | Hidden |
| Rewrite existing season entry with AI | **Yes** | Hidden |

---

## Dwarves (`/dwarves`)

Dwarf roster ranked by importance + visitor list.

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| Browse all dwarves with profession, skills, stress | No | Full access |
| View visitor list | No | Full access |
| Click through to character sheets | No | Full access |

### Dwarf Detail (`/dwarves/{unit_id}`)

Full character sheet with tabs: Notes | Biography | Diary | Timeline

**Always available (read-only):**
- Personality traits, values/beliefs, dreams
- Physical/mental attributes, skills with level indicators
- Relationships, pets (alive/deceased), equipment, wounds
- Combat highlights (weapon, blow count, body parts, outcome, lethality)
- Event history timeline

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| Add notes (Suspicion, Fact, Theory, Rumor, Secret, Foreshadow, Mood, What If) | No | Full access |
| Resolve/delete notes | No | Full access |
| Write manual biography entry | No | Default open |
| Write manual diary entry | No | Default open |
| Edit existing bio/diary entries | No | Full access |
| Set highlight role (Protagonist / Antagonist / Watchlist) | No | Full access |
| Generate biography with AI | **Yes** | Hidden |
| Generate diary entry with AI | **Yes** | Hidden |
| Generate eulogy (deceased only) | **Yes** | Hidden |

### Relationships (`/dwarves/relationships`)

Interactive vis-network graph showing fortress-wide relationships (family, friends, grudges, lovers). Includes family tree view using legends hf_link data. Read-only, no LLM.

### Religion (`/dwarves/religion`)

Fortress pantheon showing which deities are worshipped by which dwarves. Interactive graph. Read-only, no LLM.

---

## Events (`/events`)

Recent fortress events with live WebSocket feed.

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| View event feed (live via WebSocket) | No | Full access |
| Filter by type (Deaths, Combat, Moods, Artifacts, Seasons, Buildings, Role Changes, etc.) | No | Full access |
| Expand combat details (blow-by-blow, color-coded) | No | Full access |
| View grouped siege/engagement encounters | No | Full access |
| View chat log (dwarf name, profession, message) | No | Full access |
| Generate battle/siege report | **Yes** | Hidden |
| Summarize chat log with AI | **Yes** | Hidden |

---

## Dashboard (`/dashboard`)

Fortress statistics and charts. **Entirely read-only, no LLM needed.**

- Population, Years Active, Deaths, Artifacts, Combats (stat cards)
- Population Over Time chart
- Deaths Per Season chart
- Combat Activity chart
- Migration Waves chart
- Notable Firsts (milestones)

---

## Legends / Lore (`/lore`)

World history browser powered by legends XML export. **Entirely read-only, no LLM needed.**

### Index Page
- Browse civilizations, wars, historical figures, artifacts
- Full-text search across all legends data
- Pin/bookmark entities with notes (keyboard shortcut: P)
- Pinned lore sidebar accessible from any page

### Detail Pages
| Page | Route | Content |
|------|-------|---------|
| Historical Figure | `/lore/figure/{id}` | Bio, family tree graph, event timeline, positions, skills, emotional bonds, intrigue plots |
| Civilization | `/lore/civ/{id}` | Leaders, wars, sites, sub-entities (religions, guilds), festivals, honors, positions |
| Site | `/lore/site/{id}` | Type, owner, structures, properties, event type distribution |
| Artifact | `/lore/artifact/{id}` | Creator, material, description, book pages |
| War | `/lore/war/{id}` | Aggressors/defenders, battles, casualties |
| Event Collection | `/lore/event/{id}` | Duels, purges, abductions, etc. with sub-events |
| Written Work | `/lore/work/{id}` | Author, artifact copies |
| Festival | `/lore/festival/{civ_id}/{id}` | Schedules, features |
| Cultural Form | `/lore/form/{type}/{id}` | Poetic, musical, dance forms |
| World Map | `/lore/map` | Generated terrain map with site markers overlay |

### Stats & Graph APIs
- World stats: race distribution, event timeline, event type breakdown
- Per-entity stats: figure timelines, civ war stats, site event types
- Family tree graphs (vis-network, 2 generation depth)
- Warfare network graphs (civs as nodes, wars as edges)
- World timeline (vis-timeline: eras, wars, notable deaths)

---

## Quests (`/quests`)

Quest system for player-driven objectives.

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| Create manual quest (title, description, category, difficulty) | No | Full access |
| Edit quest title/description | No | Full access |
| Resolve quest with player comment | No | Full access |
| Abandon quest | No | Full access |
| Toggle quest priority (star) | No | Full access |
| Delete completed quests | No | Full access |
| View completed quest history | No | Full access |
| Generate AI quests (count/category/difficulty filters) | **Yes** | Hidden |
| Generate quest completion narrative | **Yes** | Hidden |

---

## Gazette (`/gazette`)

Dwarven newspaper with 5 sections.

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| Write manual gazette (Herald, Military Dispatches, Quarry Gossip, Quest Board, Obituaries) | No | Default form |
| Edit published gazette | No | Full access |
| View past gazettes | No | Full access |
| Generate full gazette with AI | **Yes** | Hidden |
| Rewrite existing gazette with AI | **Yes** | Hidden |

---

## Saga

Epic world history narrative (accessed from chronicle page or API).

| Action | LLM Required | No-LLM Mode |
|--------|-------------|-------------|
| Write manual saga entry | No | Full access |
| Generate saga with AI | **Yes** | Hidden |

---

## Settings (`/settings`)

App configuration page.

- DF path, event directory
- LLM provider selection (Claude / OpenAI / Ollama / None)
- API key, model name, temperature
- Token limits
- No-LLM mode toggle
- Active world selection

---

## Summary

| Feature | Works Without LLM | LLM Adds |
|---------|------------------|----------|
| Chronicle | Manual entries + notes | AI-generated seasonal narratives |
| Dwarf Bios | Manual entries + notes | AI biographies, diaries, eulogies |
| Events | Full event feed + combat details | Battle/siege reports, chat summaries |
| Dashboard | All charts and stats | Nothing |
| Legends/Lore | Full world history browser | Nothing |
| Quests | Manual CRUD | AI quest generation + completion narratives |
| Gazette | Manual 5-section newspaper | AI-generated editions |
| Saga | Manual entries | AI world history narrative |
| Relationships | Full graph | Nothing |
| Religion | Full pantheon view | Nothing |

**10 routes require LLM** (chronicle, bio, diary, eulogy, saga, gazette, quest gen, quest complete, battle report, chat summarize). All have manual alternatives except eulogy, battle reports, and chat summarize — those are LLM-only features that are simply hidden in no-LLM mode.
