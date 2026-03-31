"""Smoke tests for all page routes.

Verifies every HTML page route returns 200 with mock game state.
Catches broken imports, missing template variables, and registration errors.
"""

from __future__ import annotations

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
    DeathData,
    DeathEvent,
    EventSource,
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
def event_dir(tmp_path):
    (tmp_path / "test_world").mkdir()
    return tmp_path


@pytest.fixture
def fortress_dir(tmp_path):
    d = tmp_path / "fortress_output"
    d.mkdir()
    return d


@pytest.fixture
def config(event_dir, fortress_dir):
    return AppConfig(paths=PathsConfig(event_dir=str(event_dir)))


@pytest.fixture
def metadata():
    return {
        "fortress_name": "Smoketest Hold",
        "site_name": "The Bastion",
        "civ_name": "The Iron Realm",
        "biome": "temperate_grassland",
        "year": 205,
        "season": "spring",
        "population": 42,
        "visitors": [],
        "animals": [],
        "buildings": [],
        "fortress_info": {"civ_id": 1},
    }


@pytest.fixture
def dwarf():
    return Dwarf(
        unit_id=1,
        name='Urist McTestington "Sparkle", Miner',
        profession="Miner",
        race="DWARF",
        age=37,
        skills=[Skill(name="Mining", level="Legendary", experience=5000)],
        stress_category=2,
        is_alive=True,
    )


@pytest.fixture
def tracker(dwarf):
    ct = CharacterTracker()
    ct.register_dwarf(dwarf)
    return ct


@pytest.fixture
def event_store():
    es = EventStore()
    es.add(SeasonChangeEvent(
        game_year=205, game_tick=0, season=Season.SPRING,
        source=EventSource.DFHACK,
        data=SeasonChangeData(new_season=Season.SPRING, population=42),
    ))
    es.add(DeathEvent(
        game_year=205, game_tick=5000, season=Season.SPRING,
        source=EventSource.DFHACK,
        data=DeathData(
            victim=UnitRef(unit_id=99, name="Fallen Dwarf", race="DWARF", profession="Peasant"),
            cause="combat",
        ),
    ))
    return es


@pytest.fixture
def game_state(event_store, tracker, metadata):
    return (event_store, tracker, WorldLore(), metadata)


def _patch_all(router_module: str, config, game_state, fortress_dir):
    """Return a combined context manager patching config, game state, and fortress dir.

    Only patches attributes that the router actually imports.
    """
    import importlib
    from contextlib import ExitStack

    mod = importlib.import_module(router_module)
    stack = ExitStack()

    base_ctx = {
        "active_tab": "test", "worlds": ["test_world"], "active_world": "test_world",
        "fortress_name": "Smoketest Hold", "site_name": "The Bastion",
        "civ_name": "The Iron Realm", "biome": "Temperate Grassland",
        "year": 205, "season": "Spring", "population": 42,
        "event_count": 2, "last_updated": "1s ago",
        "setup_step": "", "no_llm_mode": False,
    }

    if hasattr(mod, "_get_config"):
        stack.enter_context(patch(f"{router_module}._get_config", return_value=config))
    if hasattr(mod, "_load_game_state_safe"):
        stack.enter_context(patch(f"{router_module}._load_game_state_safe", return_value=game_state))
    if hasattr(mod, "_base_context"):
        stack.enter_context(patch(f"{router_module}._base_context", return_value=base_ctx))
    if hasattr(mod, "_get_fortress_dir"):
        stack.enter_context(patch(f"{router_module}._get_fortress_dir", return_value=fortress_dir))
    return stack


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Page Smoke Tests
# ---------------------------------------------------------------------------

R = "df_storyteller.web.routers"


class TestPageRoutes:
    """Every HTML page route should return 200 with mock game state."""

    def test_chronicle_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.chronicle", config, game_state, fortress_dir):
            resp = client.get("/")
            assert resp.status_code == 200
            assert "Smoketest Hold" in resp.text or "chronicle" in resp.text.lower()

    def test_dwarves_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dwarves", config, game_state, fortress_dir):
            resp = client.get("/dwarves")
            assert resp.status_code == 200

    def test_dwarf_detail_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dwarves", config, game_state, fortress_dir):
            resp = client.get("/dwarves/1")
            assert resp.status_code == 200
            assert "Urist" in resp.text

    def test_dwarf_detail_not_found(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dwarves", config, game_state, fortress_dir):
            resp = client.get("/dwarves/9999")
            # Should redirect or show error, not 500
            assert resp.status_code < 500

    def test_relationships_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dwarves", config, game_state, fortress_dir):
            resp = client.get("/dwarves/relationships")
            assert resp.status_code == 200

    def test_religion_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dwarves", config, game_state, fortress_dir):
            resp = client.get("/dwarves/religion")
            assert resp.status_code == 200

    def test_events_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.events", config, game_state, fortress_dir):
            resp = client.get("/events")
            assert resp.status_code == 200

    def test_dashboard_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dashboard", config, game_state, fortress_dir):
            resp = client.get("/dashboard")
            assert resp.status_code == 200

    def test_gazette_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.gazette", config, game_state, fortress_dir):
            resp = client.get("/gazette")
            assert resp.status_code == 200

    def test_quests_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.quests", config, game_state, fortress_dir):
            resp = client.get("/quests")
            assert resp.status_code == 200

    def test_settings_page(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.settings", config, game_state, fortress_dir):
            resp = client.get("/settings")
            assert resp.status_code == 200

    def test_lore_page_no_legends(self, client, config, game_state, fortress_dir):
        # Without legends loaded, lore page renders with empty data sections.
        with _patch_all(f"{R}.lore_index", config, game_state, fortress_dir):
            resp = client.get("/lore")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API Smoke Tests
# ---------------------------------------------------------------------------


class TestApiRoutes:
    """JSON API routes should return valid responses with mock data."""

    def test_api_worlds(self, client, config):
        with patch(f"{R}.worlds._get_config", return_value=config), \
             patch(f"{R}.worlds._get_worlds", return_value=["test_world"]), \
             patch(f"{R}.worlds._get_active_world", return_value="test_world"):
            resp = client.get("/api/worlds")
            assert resp.status_code == 200
            data = resp.json()
            assert "worlds" in data
            assert "active" in data

    def test_api_highlights_empty(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.highlights", config, game_state, fortress_dir):
            resp = client.get("/api/highlights")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_api_notes_empty(self, client, config, fortress_dir):
        with patch(f"{R}.notes._get_config", return_value=config), \
             patch(f"{R}.notes._get_fortress_dir", return_value=fortress_dir):
            resp = client.get("/api/notes")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_api_quests_empty(self, client, config, fortress_dir):
        with patch(f"{R}.quests._get_config", return_value=config), \
             patch(f"{R}.quests._get_fortress_dir", return_value=fortress_dir):
            resp = client.get("/api/quests")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_api_relationships(self, client, config, game_state, fortress_dir):
        with _patch_all(f"{R}.dwarves", config, game_state, fortress_dir):
            resp = client.get("/api/relationships")
            assert resp.status_code == 200
            data = resp.json()
            assert "nodes" in data
            assert "edges" in data

    def test_api_refresh(self, client):
        resp = client.get("/api/refresh", follow_redirects=False)
        assert resp.status_code == 303
