"""Security tests for the web application.

Validates fixes for:
- Path traversal in world switching (CodeQL #4–#9)
- Information exposure through exceptions (CodeQL #1–#3)
- XSS via innerHTML / incomplete escaping (CodeQL #10–#11)
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Stub out missing modules so app.py can be imported without them installed.
_STUB_MODULES = [
    "df_storyteller.stories",
    "df_storyteller.stories.base",
    "df_storyteller.stories.chronicle",
    "df_storyteller.stories.biography",
    "df_storyteller.stories.saga",
]
for _mod_name in _STUB_MODULES:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        if _mod_name == "df_storyteller.stories.base":
            _stub.create_provider = MagicMock()  # type: ignore[attr-defined]
        sys.modules[_mod_name] = _stub

from fastapi.testclient import TestClient

from df_storyteller.config import AppConfig, PathsConfig
from df_storyteller.web.app import app
from df_storyteller.web.state import safe_watch_dir as _safe_watch_dir


@pytest.fixture(autouse=True)
def _reset_app_state():
    """Reset global app state between tests."""
    import df_storyteller.web.state as state_mod
    old = state_mod._active_world
    state_mod._active_world = None
    state_mod._cached_no_legends = None
    state_mod._cached_with_legends = None
    state_mod._cache_time_no_legends = 0
    state_mod._cache_time_with_legends = 0
    yield
    state_mod._active_world = old


@pytest.fixture
def event_dir(tmp_path):
    """Create a temp event directory with a valid world subfolder."""
    world = tmp_path / "my_world"
    world.mkdir()
    return tmp_path


@pytest.fixture
def config(event_dir):
    return AppConfig(paths=PathsConfig(event_dir=str(event_dir)))


@pytest.fixture
def client(config):
    with patch("df_storyteller.web.app._get_config", return_value=config):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ==================== Path traversal (CodeQL #4–#9) ====================


class TestPathTraversal:
    """Ensure world names with path traversal sequences are rejected."""

    def test_safe_watch_dir_rejects_parent_traversal(self, config):
        assert _safe_watch_dir(config, "../../etc") is None

    def test_safe_watch_dir_rejects_absolute_path(self, config):
        assert _safe_watch_dir(config, "/etc/passwd") is None

    def test_safe_watch_dir_rejects_dot_segments(self, config):
        assert _safe_watch_dir(config, "my_world/../../etc") is None

    def test_safe_watch_dir_accepts_valid_world(self, config):
        result = _safe_watch_dir(config, "my_world")
        assert result is not None
        assert result.name == "my_world"

    def test_safe_watch_dir_returns_none_for_empty(self, config):
        assert _safe_watch_dir(config, "") is None

    def test_switch_world_rejects_traversal(self, client):
        resp = client.post("/api/worlds/switch", json={"world": "../../etc"})
        data = resp.json()
        assert data["ok"] is False
        assert "Invalid" in data.get("error", "")

    def test_switch_world_accepts_valid(self, client):
        resp = client.post("/api/worlds/switch", json={"world": "my_world"})
        data = resp.json()
        assert data["ok"] is True
        assert data["active"] == "my_world"

    def test_switch_world_accepts_empty(self, client):
        """Switching to empty string resets the active world."""
        resp = client.post("/api/worlds/switch", json={"world": ""})
        data = resp.json()
        assert data["ok"] is True


# ==================== Exception exposure (CodeQL #1–#3) ====================


class TestExceptionExposure:
    """Ensure internal error details are never sent to the client."""

    SECRET = "/super/secret/internal/path/config.toml"

    def test_chronicle_hides_exception_details(self, client):
        with patch(
            "df_storyteller.stories.chronicle.generate_chronicle",
            side_effect=RuntimeError(self.SECRET),
            create=True,
        ):
            resp = client.post("/api/chronicle/generate")
            assert self.SECRET not in resp.text
            assert "generation failed" in resp.text.lower()

    def test_saga_hides_exception_details(self, client):
        with patch(
            "df_storyteller.stories.saga.generate_saga",
            side_effect=RuntimeError(self.SECRET),
            create=True,
        ):
            resp = client.post("/api/saga/generate")
            assert self.SECRET not in resp.text
            assert "generation failed" in resp.text.lower()

    def test_bio_hides_exception_details(self, client):
        """Bio endpoint requires a valid dwarf — mock the tracker too."""
        mock_dwarf = MagicMock()
        mock_dwarf.name = "Urist"
        mock_tracker = MagicMock()
        mock_tracker.get_dwarf.return_value = mock_dwarf

        with patch(
            "df_storyteller.web.routers.stories._load_game_state_safe",
            return_value=(MagicMock(), mock_tracker, MagicMock(), {}),
        ), patch(
            "df_storyteller.stories.biography.generate_biography",
            side_effect=RuntimeError(self.SECRET),
            create=True,
        ):
            resp = client.post("/api/bio/1")
            assert self.SECRET not in resp.text
            assert "generation failed" in resp.text.lower()

    def test_bio_dwarf_not_found(self, client):
        """Non-existent dwarf should return a clean message, not a traceback."""
        mock_tracker = MagicMock()
        mock_tracker.get_dwarf.return_value = None

        with patch(
            "df_storyteller.web.routers.stories._load_game_state_safe",
            return_value=(MagicMock(), mock_tracker, MagicMock(), {}),
        ):
            resp = client.post("/api/bio/99999")
            assert resp.status_code == 200
            assert "not found" in resp.text.lower()


# ==================== Template XSS checks (CodeQL #10–#11) ====================


class TestTemplateXSS:
    """Verify templates use safe DOM APIs instead of innerHTML."""

    def test_events_template_uses_textcontent(self):
        """The events template JS should use textContent, not innerHTML for cards."""
        template = Path(__file__).resolve().parent.parent / "src/df_storyteller/web/templates/events.html"
        content = template.read_text()
        assert "card.innerHTML" not in content, "events.html still uses innerHTML for event cards"
        assert "textContent" in content

    def test_events_template_no_safe_filter(self):
        """Jinja | safe filter should not be used on event descriptions."""
        template = Path(__file__).resolve().parent.parent / "src/df_storyteller/web/templates/events.html"
        content = template.read_text()
        assert "| safe" not in content, "events.html still uses | safe on descriptions"

    def test_lore_template_uses_createelement(self):
        """The lore search results should use createElement, not innerHTML."""
        template = Path(__file__).resolve().parent.parent / "src/df_storyteller/web/templates/lore.html"
        content = template.read_text()
        assert "searchResults.innerHTML" not in content, "lore.html still uses innerHTML for search results"
        assert "createElement" in content

    def test_lore_template_no_inline_onclick(self):
        """Search result links should use addEventListener, not inline onclick."""
        template = Path(__file__).resolve().parent.parent / "src/df_storyteller/web/templates/lore.html"
        content = template.read_text()
        assert "onclick=\"searchLore" not in content, "lore.html still uses inline onclick for search links"
