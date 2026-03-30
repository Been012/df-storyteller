"""Tests for router-specific business logic.

Covers dashboard aggregation, gazette helpers, quest state transitions,
and API endpoint response shapes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from df_storyteller.config import AppConfig, PathsConfig
from df_storyteller.context.character_tracker import CharacterTracker
from df_storyteller.context.event_store import EventStore
from df_storyteller.context.world_lore import WorldLore
from df_storyteller.schema.entities import Dwarf, Skill
from df_storyteller.schema.events import (
    CombatData,
    CombatEvent,
    DeathData,
    DeathEvent,
    EventSource,
    EventType,
    GameEvent,
    MoodData,
    MoodEvent,
    Season,
    SeasonChangeData,
    SeasonChangeEvent,
    UnitRef,
)
from df_storyteller.web.app import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    import df_storyteller.web.state as st
    old = st._active_world
    st._active_world = None
    st._cached_no_legends = None
    st._cached_with_legends = None
    st._cache_time_no_legends = 0
    st._cache_time_with_legends = 0
    yield
    st._active_world = old


@pytest.fixture
def fortress_dir(tmp_path):
    d = tmp_path / "fortress"
    d.mkdir()
    return d


@pytest.fixture
def config(tmp_path, fortress_dir):
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    (event_dir / "test_world").mkdir()
    return AppConfig(paths=PathsConfig(event_dir=str(event_dir)))


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _make_metadata(**overrides):
    base = {
        "fortress_name": "TestFort", "site_name": "Site",
        "civ_name": "Civ", "biome": "grassland",
        "year": 205, "season": "spring", "population": 30,
        "visitors": [], "animals": [], "buildings": [], "fortress_info": {},
    }
    base.update(overrides)
    return base


def _make_base_context(**overrides):
    base = {
        "active_tab": "test", "worlds": ["w"], "active_world": "w",
        "fortress_name": "TestFort", "site_name": "Site",
        "civ_name": "Civ", "biome": "Grassland",
        "year": 205, "season": "Spring", "population": 30,
        "event_count": 0, "last_updated": "", "setup_step": "",
        "no_llm_mode": False,
    }
    base.update(overrides)
    return base


R = "df_storyteller.web.routers"


# ---------------------------------------------------------------------------
# Dashboard aggregation
# ---------------------------------------------------------------------------


class TestDashboard:
    """Dashboard route correctly aggregates event data."""

    def _make_event_store(self):
        es = EventStore()
        # Two seasons of data
        es.add(SeasonChangeEvent(
            game_year=205, game_tick=0, season=Season.SPRING,
            source=EventSource.DFHACK,
            data=SeasonChangeData(new_season=Season.SPRING, population=30),
        ))
        es.add(SeasonChangeEvent(
            game_year=205, game_tick=100000, season=Season.SUMMER,
            source=EventSource.DFHACK,
            data=SeasonChangeData(new_season=Season.SUMMER, population=35),
        ))
        # A death in spring
        es.add(DeathEvent(
            game_year=205, game_tick=5000, season=Season.SPRING,
            source=EventSource.DFHACK,
            data=DeathData(
                victim=UnitRef(unit_id=99, name="Fallen", race="DWARF"),
                cause="combat",
            ),
        ))
        # Combat in summer
        es.add(CombatEvent(
            game_year=205, game_tick=110000, season=Season.SUMMER,
            source=EventSource.GAMELOG,
            data=CombatData(
                attacker=UnitRef(unit_id=1, name="Urist"),
                defender=UnitRef(unit_id=50, name="Goblin"),
                is_lethal=True,
            ),
        ))
        return es

    def test_dashboard_renders_with_events(self, client, config, fortress_dir):
        es = self._make_event_store()
        metadata = _make_metadata()
        game_state = (es, CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.dashboard._get_config", return_value=config), \
             patch(f"{R}.dashboard._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.dashboard._base_context", return_value=_make_base_context()):
            resp = client.get("/dashboard")
            assert resp.status_code == 200
            assert "dashboard" in resp.text.lower() or "population" in resp.text.lower()

    def test_dashboard_empty_event_store(self, client, config, fortress_dir):
        game_state = (EventStore(), CharacterTracker(), WorldLore(), _make_metadata())
        with patch(f"{R}.dashboard._get_config", return_value=config), \
             patch(f"{R}.dashboard._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.dashboard._base_context", return_value=_make_base_context()):
            resp = client.get("/dashboard")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Gazette helpers
# ---------------------------------------------------------------------------


class TestGazetteHelpers:
    """Gazette helper functions in routers/gazette.py."""

    def test_pick_gazette_author_writing_skill(self):
        from df_storyteller.web.routers.gazette import _pick_gazette_author
        tracker = CharacterTracker()
        tracker.register_dwarf(Dwarf(
            unit_id=1, name="Scribe McWriter, Clerk", profession="Clerk",
            skills=[Skill(name="Writing", level="Expert", experience=3000)],
        ))
        tracker.register_dwarf(Dwarf(
            unit_id=2, name="Dig McDigger, Miner", profession="Miner",
            skills=[Skill(name="Mining", level="Legendary", experience=5000)],
        ))
        author, prof = _pick_gazette_author(tracker)
        # The writer should be picked over the miner
        assert "Scribe" in author

    def test_pick_gazette_author_fallback(self):
        from df_storyteller.web.routers.gazette import _pick_gazette_author
        tracker = CharacterTracker()
        tracker.register_dwarf(Dwarf(unit_id=1, name="Just Dwarf", profession="Peasant"))
        author, prof = _pick_gazette_author(tracker)
        assert author == "Just Dwarf"

    def test_pick_gazette_author_empty(self):
        from df_storyteller.web.routers.gazette import _pick_gazette_author
        author, prof = _pick_gazette_author(CharacterTracker())
        assert author == "An Anonymous Scribe"

    def test_gazette_section_length(self):
        from df_storyteller.web.routers.gazette import _gazette_section_length
        # Low token budget
        config = AppConfig(paths=PathsConfig())
        config.story.gazette_max_tokens = 500
        result = _gazette_section_length(config)
        assert "-" in result  # Should be a range like "50-80"

        # High token budget
        config.story.gazette_max_tokens = 4000
        result = _gazette_section_length(config)
        assert "-" in result


# ---------------------------------------------------------------------------
# Quest CRUD
# ---------------------------------------------------------------------------


class TestQuestCrud:
    """Quest API endpoints handle CRUD operations correctly."""

    def test_create_manual_quest(self, client, config, fortress_dir):
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.quests._get_config", return_value=config), \
             patch(f"{R}.quests._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.quests._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/quests/manual", json={
                "title": "Dig to the caverns",
                "description": "Breach the first cavern layer",
                "category": "exploration",
                "difficulty": "medium",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "Dig to the caverns"
            assert data["category"] == "exploration"

    def test_create_quest_missing_fields(self, client, config, fortress_dir):
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.quests._get_config", return_value=config), \
             patch(f"{R}.quests._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.quests._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/quests/manual", json={"title": "", "description": ""})
            assert resp.status_code == 400

    def test_quest_lifecycle(self, client, config, fortress_dir):
        """Create → list → resolve → list completed."""
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        patches = [
            patch(f"{R}.quests._get_config", return_value=config),
            patch(f"{R}.quests._load_game_state_safe", return_value=game_state),
            patch(f"{R}.quests._get_fortress_dir", return_value=fortress_dir),
        ]
        for p in patches:
            p.start()

        try:
            # Create
            resp = client.post("/api/quests/manual", json={
                "title": "Test Quest", "description": "A test",
            })
            assert resp.status_code == 200
            quest_id = resp.json()["id"]

            # List — should have 1 active
            resp = client.get("/api/quests")
            assert resp.status_code == 200
            quests = resp.json()
            assert len(quests) == 1
            assert quests[0]["status"] == "active"

            # Resolve
            resp = client.post(f"/api/quests/{quest_id}/resolve", json={"comment": "Done!"})
            assert resp.status_code == 200

            # List — should be completed
            resp = client.get("/api/quests?status=completed")
            assert resp.status_code == 200
            completed = resp.json()
            assert len(completed) == 1

            # Delete
            resp = client.delete(f"/api/quests/{quest_id}")
            assert resp.status_code == 200

            # List — should be empty
            resp = client.get("/api/quests")
            assert resp.status_code == 200
            assert len(resp.json()) == 0
        finally:
            for p in patches:
                p.stop()


# ---------------------------------------------------------------------------
# Notes CRUD
# ---------------------------------------------------------------------------


class TestNotesCrud:
    """Notes API endpoints handle CRUD correctly."""

    def test_note_lifecycle(self, client, config, fortress_dir):
        metadata = _make_metadata()

        with patch(f"{R}.notes._get_config", return_value=config), \
             patch(f"{R}.notes._load_game_state_safe",
                   return_value=(EventStore(), CharacterTracker(), WorldLore(), metadata)), \
             patch(f"{R}.notes._get_fortress_dir", return_value=fortress_dir):
            # Create
            resp = client.post("/api/notes", json={
                "tag": "suspicion",
                "text": "Something fishy about Urist",
                "target_type": "dwarf",
                "target_id": 1,
            })
            assert resp.status_code == 200
            note = resp.json()
            note_id = note["id"]
            assert note["tag"] == "suspicion"

            # List
            resp = client.get("/api/notes")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

            # Resolve
            resp = client.post(f"/api/notes/{note_id}/resolve")
            assert resp.status_code == 200

            # Delete
            resp = client.delete(f"/api/notes/{note_id}")
            assert resp.status_code == 200

            # List — empty
            resp = client.get("/api/notes")
            assert resp.status_code == 200
            assert len(resp.json()) == 0


# ---------------------------------------------------------------------------
# Highlights CRUD
# ---------------------------------------------------------------------------


class TestHighlightsCrud:
    """Highlights API endpoints."""

    def test_highlight_lifecycle(self, client, config, fortress_dir):
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.highlights._get_config", return_value=config), \
             patch(f"{R}.highlights._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.highlights._get_fortress_dir", return_value=fortress_dir):
            # Set highlight
            resp = client.post("/api/highlights", json={
                "unit_id": 1, "role": "protagonist",
            })
            assert resp.status_code == 200

            # List
            resp = client.get("/api/highlights")
            assert resp.status_code == 200
            highlights = resp.json()
            assert len(highlights) == 1
            assert highlights[0]["unit_id"] == 1

            # Remove
            resp = client.delete("/api/highlights/1")
            assert resp.status_code == 200

            # List — empty
            resp = client.get("/api/highlights")
            assert resp.status_code == 200
            assert len(resp.json()) == 0


# ---------------------------------------------------------------------------
# Chronicle manual entry
# ---------------------------------------------------------------------------


class TestChronicleManual:
    """Chronicle manual write endpoint."""

    def test_write_manual_chronicle(self, client, config, fortress_dir):
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.chronicle._get_config", return_value=config), \
             patch(f"{R}.chronicle._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.chronicle._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/chronicle/manual", json={
                "text": "The goblins came in the night.",
                "season": "autumn",
                "year": 205,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["season"] == "autumn"

            # Verify file was created
            journal = fortress_dir / "fortress_journal.md"
            assert journal.exists()
            content = journal.read_text(encoding="utf-8")
            assert "goblins came in the night" in content
            assert "source:manual" in content

    def test_write_chronicle_empty_text(self, client, config, fortress_dir):
        with patch(f"{R}.chronicle._get_config", return_value=config), \
             patch(f"{R}.chronicle._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/chronicle/manual", json={"text": ""})
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Gazette manual entry
# ---------------------------------------------------------------------------


class TestGazetteManual:
    """Gazette manual write endpoint."""

    def test_write_manual_gazette(self, client, config, fortress_dir):
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.gazette._get_config", return_value=config), \
             patch(f"{R}.gazette._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.gazette._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/gazette/manual", json={
                "herald": "The fortress prospers.",
                "military": "All quiet.",
                "gossip": "Urist likes cats.",
                "quests": "None active.",
                "obituaries": "No deaths.",
            })
            assert resp.status_code == 200

            # Verify file
            gazette_path = fortress_dir / "gazette.json"
            assert gazette_path.exists()
            data = json.loads(gazette_path.read_text())
            assert len(data) == 1
            assert data[0]["sections"]["herald"] == "The fortress prospers."
            assert data[0]["is_manual"] is True


# ---------------------------------------------------------------------------
# Stories manual entries
# ---------------------------------------------------------------------------


class TestStoriesManual:
    """Manual biography/diary/saga write endpoints."""

    def test_write_manual_saga(self, client, config, fortress_dir):
        metadata = _make_metadata()
        game_state = (EventStore(), CharacterTracker(), WorldLore(), metadata)

        with patch(f"{R}.stories._get_config", return_value=config), \
             patch(f"{R}.stories._load_game_state_safe", return_value=game_state), \
             patch(f"{R}.stories._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/saga/manual", json={
                "text": "In the age of legends, the dwarves rose.",
            })
            assert resp.status_code == 200

            saga_path = fortress_dir / "saga.json"
            assert saga_path.exists()

    def test_write_saga_empty_text(self, client, config, fortress_dir):
        with patch(f"{R}.stories._get_config", return_value=config), \
             patch(f"{R}.stories._get_fortress_dir", return_value=fortress_dir):
            resp = client.post("/api/saga/manual", json={"text": ""})
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# World switching
# ---------------------------------------------------------------------------


class TestWorldSwitch:
    """World switch endpoint."""

    def test_switch_valid_world(self, client, config):
        with patch(f"{R}.worlds._get_config", return_value=config), \
             patch(f"{R}.worlds._safe_watch_dir", return_value=Path("/valid")):
            resp = client.post("/api/worlds/switch", json={"world": "region2"})
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    def test_switch_invalid_world(self, client, config):
        with patch(f"{R}.worlds._get_config", return_value=config), \
             patch(f"{R}.worlds._safe_watch_dir", return_value=None):
            resp = client.post("/api/worlds/switch", json={"world": "../../etc"})
            assert resp.status_code == 200
            assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Settings save
# ---------------------------------------------------------------------------


class TestSettingsSave:
    """Settings save endpoint."""

    def test_save_settings_redirects(self, client, config):
        with patch(f"{R}.settings._get_config", return_value=config), \
             patch("df_storyteller.config.save_config"):
            resp = client.post("/settings", data={
                "df_install": "/path/to/df",
                "llm_provider": "claude",
                "narrative_style": "dramatic",
            }, follow_redirects=False)
            assert resp.status_code == 303
            assert "/settings" in resp.headers.get("location", "")
