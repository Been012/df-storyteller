# Web App Route Map

Complete route reference for `src/df_storyteller/web/app.py` (~6000 lines, FastAPI + Jinja2).

**Totals:** 65 routes — 20 HTML pages, 34 JSON APIs, 10 streaming endpoints, 1 WebSocket

## Pages (HTML Templates)

| Route | Function | Template | Purpose |
|-------|----------|----------|---------|
| `GET /` | `chronicle_page` | `chronicle.html` | Fortress chronicle entries with dwarf name hotlinks |
| `GET /dashboard` | `dashboard_page` | `dashboard.html` | Fortress stats: population, deaths, combat timeline charts |
| `GET /dwarves` | `dwarves_page` | `dwarves.html` | Dwarf roster ranked by importance + visitor list |
| `GET /dwarves/{unit_id}` | `dwarf_detail_page` | `dwarf_detail.html` | Character sheet: traits, skills, events, bio, relationships |
| `GET /dwarves/relationships` | `relationships_page` | `relationships.html` | Fortress-wide relationship web (vis-network graph) |
| `GET /dwarves/religion` | `religion_page` | `religion.html` | Fortress pantheon and deity worship overview |
| `GET /events` | `events_page` | `events.html` | Recent events, combat encounters, battle reports |
| `GET /gazette` | `gazette_page` | `gazette.html` | Dwarven newspaper — current and past issues |
| `GET /quests` | `quests_page` | `quests.html` | Active and completed quests |
| `GET /settings` | `settings_page` | `settings.html` | App configuration (paths, LLM provider, tokens) |
| `GET /lore` | `lore_page` | `lore.html` | World lore index: civs, wars, figures, artifacts |
| `GET /lore/figure/{hf_id}` | `lore_figure_page` | `lore_figure.html` | Historical figure detail |
| `GET /lore/civ/{entity_id}` | `lore_civ_page` | `lore_civ.html` | Civilization detail with sub-entities, leaders, wars |
| `GET /lore/site/{site_id}` | `lore_site_page` | `lore_site.html` | World site detail with structures |
| `GET /lore/artifact/{artifact_id}` | `lore_artifact_page` | `lore_artifact.html` | Artifact detail with creator, material |
| `GET /lore/war/{ec_id}` | `lore_war_page` | `lore_war.html` | War detail with battles, casualties |
| `GET /lore/event/{ec_id}` | `lore_event_collection_page` | `lore_event_collection.html` | Event collection (duel, purge, abduction, etc.) |
| `GET /lore/work/{wc_id}` | `lore_written_work_page` | `lore_written_work.html` | Written work with author, artifacts |
| `GET /lore/festival/{civ_id}/{occasion_id}` | `lore_festival_page` | `lore_festival.html` | Civilization festival with schedules |
| `GET /lore/form/{form_type}/{form_id}` | `lore_cultural_form_page` | `lore_cultural_form.html` | Cultural form (poetic, musical, dance) |
| `GET /lore/map` | `lore_map_page` | `lore_map.html` | World map visualization |

## Story Generation (LLM Required, Streaming)

All return `StreamingResponse` — text yielded word-by-word to simulate typing.

| Route | Function | Story Module | Purpose |
|-------|----------|-------------|---------|
| `POST /api/chronicle/generate` | `api_generate_chronicle` | `stories.chronicle` | Season chronicle entry |
| `POST /api/bio/{unit_id}` | `api_generate_bio` | `stories.biography` | Third-person dwarf biography |
| `POST /api/diary/{unit_id}` | `api_generate_diary` | `stories.biography` | First-person diary entry |
| `POST /api/eulogy/{unit_id}` | `api_generate_eulogy` | `stories.biography` | Death eulogy for fallen dwarf |
| `POST /api/saga/generate` | `api_generate_saga` | `stories.saga` | Epic world history narrative |
| `POST /api/gazette/generate` | `api_generate_gazette` | LLM direct | Dwarven newspaper with sections |
| `POST /api/quests/generate` | `api_generate_quests` | `stories.quest_generator` | AI-generated quests from fortress state |
| `POST /api/quests/{quest_id}/complete` | `api_complete_quest` | `stories.quest_generator` | Quest completion narrative |
| `POST /api/battle-report/{idx}` | `api_battle_report` | LLM direct | Dramatic battle/siege report |
| `POST /api/chat/summarize` | `api_summarize_chat` | LLM direct | AI summary of fortress chat log |

## Manual Writing (No LLM, Player-Written Content)

| Route | Function | Purpose |
|-------|----------|---------|
| `POST /api/chronicle/manual` | `api_chronicle_manual` | Save player-written chronicle entry |
| `POST /api/bio/{unit_id}/manual` | `api_bio_manual` | Save player-written biography |
| `POST /api/diary/{unit_id}/manual` | `api_diary_manual` | Save player-written diary entry |
| `POST /api/saga/manual` | `api_saga_manual` | Save player-written saga |
| `POST /api/gazette/manual` | `api_gazette_manual` | Save player-written gazette |

## Data APIs (JSON)

### Fortress Data
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/relationships` | `api_relationships` | Relationship graph JSON (nodes/edges) |
| `GET /api/relationships/family` | `api_relationships_family` | Family tree data via legends hf_link |
| `GET /api/religion` | `api_religion` | Deity-dwarf worship graph JSON |
| `GET /api/worlds` | `api_list_worlds` | Available fortress worlds + active selection |
| `POST /api/worlds/switch` | `api_switch_world` | Switch active fortress world |
| `GET /api/refresh` | `api_refresh` | Force-clear cache, redirect home |

### Player Notes
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/notes` | `api_list_notes` | List notes (filter by target type/id) |
| `POST /api/notes` | `api_create_note` | Create note with tag (Suspicion, Fact, etc.) |
| `POST /api/notes/{note_id}/resolve` | `api_resolve_note` | Mark note resolved |
| `DELETE /api/notes/{note_id}` | `api_delete_note` | Delete note |

### Dwarf Highlights
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/highlights` | `api_highlights_list` | List all highlights (badges/roles) |
| `POST /api/highlights` | `api_highlights_set` | Set/update highlight on dwarf |
| `DELETE /api/highlights/{unit_id}` | `api_highlights_remove` | Remove highlight |

### Quests (CRUD)
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/quests` | `api_list_quests` | List quests (filter by status) |
| `POST /api/quests/manual` | `api_create_manual_quest` | Create player-written quest |
| `POST /api/quests/{quest_id}/edit` | `api_edit_quest` | Edit quest title/description |
| `POST /api/quests/{quest_id}/resolve` | `api_resolve_quest` | Resolve quest with player comment |
| `POST /api/quests/{quest_id}/abandon` | `api_abandon_quest` | Mark quest abandoned |
| `POST /api/quests/{quest_id}/priority` | `api_toggle_quest_priority` | Toggle priority flag |
| `DELETE /api/quests/{quest_id}` | `api_delete_quest` | Delete quest |

### Lore Search & Tooltips
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/lore/search` | `api_lore_search` | Full-text search across all legends data |
| `GET /api/lore/detail` | `api_lore_detail` | Structured detail for hover tooltips |

### Lore Pins (Bookmarks)
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/lore/pins` | `api_list_pins` | List pinned entities |
| `POST /api/lore/pins` | `api_add_pin` | Pin entity with optional note |
| `PUT /api/lore/pins/{pin_id}` | `api_update_pin` | Update pin note |
| `DELETE /api/lore/pins/{pin_id}` | `api_remove_pin` | Remove pin |
| `DELETE /api/lore/pins/all` | `api_clear_all_pins` | Remove all pins |

### Lore Statistics & Graphs
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/lore/stats/world` | `api_lore_stats_world` | Race distribution, event timeline, event type breakdown |
| `GET /api/lore/stats/timeline` | `api_lore_stats_timeline` | vis-timeline data: eras, wars, notable deaths |
| `GET /api/lore/stats/figure/{hf_id}` | `api_lore_stats_figure` | Per-figure event timeline |
| `GET /api/lore/stats/civ/{entity_id}` | `api_lore_stats_civ` | Per-civ war stats |
| `GET /api/lore/stats/site/{site_id}` | `api_lore_stats_site` | Per-site event type distribution |
| `GET /api/lore/graph/family/{hf_id}` | `api_lore_graph_family` | Family tree (vis-network, 2 gen depth) |
| `GET /api/lore/graph/wars/{entity_id}` | `api_lore_graph_wars` | Warfare network graph (civs as nodes) |

### Map
| Route | Function | Purpose |
|-------|----------|---------|
| `GET /api/lore/map/terrain` | `api_map_terrain` | Generated terrain PNG from region data |
| `GET /api/lore/map/sites` | `api_map_sites` | Site markers + world constructions overlay |

## WebSocket

| Route | Function | Purpose |
|-------|----------|---------|
| `WS /ws/events` | `websocket_events` | Live event feed — polls for new JSON files, pushes formatted events |

## Settings

| Route | Function | Purpose |
|-------|----------|---------|
| `POST /settings` | `save_settings` | Save config (paths, LLM provider, API keys, token limits) |

## Key Module Dependencies by Feature Area

| Feature Area | Context Modules Used | Story Modules Used |
|-------------|---------------------|-------------------|
| Chronicle | loader, notes_store, character_tracker, highlights_store | chronicle |
| Dwarves | loader, character_tracker, highlights_store, narrative_formatter | biography |
| Events | loader, event_store, context_builder | — |
| Dashboard | loader, event_store, character_tracker | — |
| Gazette | loader, quest_store, context_builder | LLM direct |
| Quests | loader, quest_store | quest_generator |
| Lore (all) | loader, world_lore, event_renderer, map_generator | — |
| Notes | notes_store | — |
| Highlights | highlights_store | — |
| Lore Pins | lore_pins | — |
| Saga | loader, context_builder, world_lore | saga |

## Caching

Game state is cached with 5-minute TTL but auto-invalidates when snapshot file modification times change. The `GET /api/refresh` endpoint forces a full cache clear. Most page routes call `_get_game_state()` which returns the cached state or reloads.

Legends data is loaded lazily — only lore routes trigger the full XML parse. Other pages use `skip_legends=True`.
