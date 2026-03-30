"""Tests for shared infrastructure: state.py, helpers.py, templates_setup.py.

These modules were extracted from app.py and are used by all routers.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from df_storyteller.config import AppConfig, PathsConfig


# ---------------------------------------------------------------------------
# state.py tests
# ---------------------------------------------------------------------------


class TestStateCache:
    """Cache management in state.py."""

    def setup_method(self):
        import df_storyteller.web.state as st
        self._st = st
        # Reset all caches
        st._active_world = None
        st._cached_no_legends = None
        st._cached_with_legends = None
        st._cache_time_no_legends = 0
        st._cache_time_with_legends = 0
        st._hotlink_cache = None
        st._map_image_cache = None

    def test_invalidate_cache_clears_everything(self):
        st = self._st
        st._cached_no_legends = ("fake",)
        st._cached_with_legends = ("fake",)
        st._cache_time_no_legends = 100.0
        st._cache_time_with_legends = 100.0
        st._hotlink_cache = {"test": ("figure", 1)}
        st._map_image_cache = (b"png", 10, 10)

        st.invalidate_cache()

        assert st._cached_no_legends is None
        assert st._cached_with_legends is None
        assert st._cache_time_no_legends == 0
        assert st._cache_time_with_legends == 0
        assert st._hotlink_cache is None
        assert st._map_image_cache is None

    def test_active_world_get_set(self):
        st = self._st
        config = AppConfig(paths=PathsConfig(event_dir="/nonexistent"))

        assert st.get_active_world(config) == ""

        st.set_active_world("region2")
        assert st.get_active_world(config) == "region2"

        st.set_active_world("")
        # Empty string is falsy so it falls through to world list
        assert st._active_world == ""

    def test_event_subscriber_management(self):
        st = self._st
        mock_ws = MagicMock()

        st.add_event_subscriber(mock_ws)
        assert mock_ws in st.get_event_subscribers()

        st.remove_event_subscriber(mock_ws)
        assert mock_ws not in st.get_event_subscribers()

    def test_remove_nonexistent_subscriber_no_error(self):
        st = self._st
        mock_ws = MagicMock()
        # Should not raise
        st.remove_event_subscriber(mock_ws)

    def test_map_image_cache_accessors(self):
        st = self._st
        assert st.get_map_image_cache() is None

        st.set_map_image_cache((b"png_bytes", 100, 100))
        cached = st.get_map_image_cache()
        assert cached is not None
        assert cached[0] == b"png_bytes"
        assert cached[1] == 100

    def test_hotlink_cache_accessors(self):
        st = self._st
        assert st.get_hotlink_cache() is None

        cache = {"urist": ("figure", 42)}
        st.set_hotlink_cache(cache)
        assert st.get_hotlink_cache() == cache


class TestStateWorlds:
    """World listing and validation in state.py."""

    def test_get_worlds_empty_dir(self, tmp_path):
        config = AppConfig(paths=PathsConfig(event_dir=str(tmp_path)))
        from df_storyteller.web.state import get_worlds
        assert get_worlds(config) == []

    def test_get_worlds_with_worlds(self, tmp_path):
        (tmp_path / "region1").mkdir()
        (tmp_path / "region2").mkdir()
        config = AppConfig(paths=PathsConfig(event_dir=str(tmp_path)))
        from df_storyteller.web.state import get_worlds
        worlds = get_worlds(config)
        assert len(worlds) == 2
        assert "region1" in worlds
        assert "region2" in worlds

    def test_get_worlds_excludes_processed(self, tmp_path):
        (tmp_path / "region1").mkdir()
        (tmp_path / "processed").mkdir()
        config = AppConfig(paths=PathsConfig(event_dir=str(tmp_path)))
        from df_storyteller.web.state import get_worlds
        worlds = get_worlds(config)
        assert "processed" not in worlds

    def test_safe_watch_dir_rejects_traversal(self, tmp_path):
        (tmp_path / "region1").mkdir()
        config = AppConfig(paths=PathsConfig(event_dir=str(tmp_path)))
        from df_storyteller.web.state import safe_watch_dir
        assert safe_watch_dir(config, "../../etc") is None

    def test_safe_watch_dir_accepts_valid(self, tmp_path):
        (tmp_path / "region1").mkdir()
        config = AppConfig(paths=PathsConfig(event_dir=str(tmp_path)))
        from df_storyteller.web.state import safe_watch_dir
        result = safe_watch_dir(config, "region1")
        assert result is not None
        assert result.name == "region1"

    def test_safe_watch_dir_empty_world(self, tmp_path):
        config = AppConfig(paths=PathsConfig(event_dir=str(tmp_path)))
        from df_storyteller.web.state import safe_watch_dir
        assert safe_watch_dir(config, "") is None

    def test_safe_watch_dir_no_event_dir(self):
        config = AppConfig(paths=PathsConfig())
        from df_storyteller.web.state import safe_watch_dir
        assert safe_watch_dir(config, "region1") is None


class TestBaseContext:
    """Base template context builder in state.py."""

    def test_base_context_minimal(self, tmp_path):
        config = AppConfig(paths=PathsConfig(
            df_install=str(tmp_path), event_dir=str(tmp_path),
        ))
        metadata = {
            "fortress_name": "TestFort", "site_name": "Site",
            "civ_name": "Civ", "biome": "temperate_grassland",
            "year": 100, "season": "spring", "population": 10,
        }
        from df_storyteller.web.state import base_context
        ctx = base_context(config, "chronicle", metadata)

        assert ctx["active_tab"] == "chronicle"
        assert ctx["fortress_name"] == "TestFort"
        assert ctx["biome"] == "Temperate Grassland"
        assert ctx["season"] == "Spring"
        assert ctx["population"] == 10
        assert ctx["setup_step"] == ""

    def test_base_context_no_config(self):
        config = AppConfig(paths=PathsConfig())
        metadata = {"fortress_name": "", "year": 0, "season": "", "population": 0}
        from df_storyteller.web.state import base_context
        ctx = base_context(config, "settings", metadata)

        assert ctx["setup_step"] == "no_config"

    def test_base_context_no_data(self, tmp_path):
        config = AppConfig(paths=PathsConfig(df_install=str(tmp_path)))
        metadata = {"fortress_name": "", "year": 0, "season": "", "population": 0}
        from df_storyteller.web.state import base_context
        ctx = base_context(config, "settings", metadata)

        assert ctx["setup_step"] == "no_data"


# ---------------------------------------------------------------------------
# helpers.py tests
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    """Markdown conversion in helpers.py."""

    def test_heading_levels(self):
        from df_storyteller.web.helpers import markdown_to_html
        assert 'story-title' in markdown_to_html("# Title")
        assert 'story-heading' in markdown_to_html("## Heading")
        assert 'story-heading' in markdown_to_html("### Subheading")

    def test_bold_and_italic(self):
        from df_storyteller.web.helpers import markdown_to_html
        result = markdown_to_html("This is **bold** and *italic* text.")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_horizontal_rules(self):
        from df_storyteller.web.helpers import markdown_to_html
        assert "<hr>" in markdown_to_html("---")
        assert "<hr>" in markdown_to_html("***")
        assert "<hr>" in markdown_to_html("___")

    def test_paragraphs(self):
        from df_storyteller.web.helpers import markdown_to_html
        result = markdown_to_html("First paragraph.\n\nSecond paragraph.")
        assert result.count("<p>") == 2
        assert result.count("</p>") == 2

    def test_empty_input(self):
        from df_storyteller.web.helpers import markdown_to_html
        result = markdown_to_html("")
        assert result.strip() == ""

    def test_single_line(self):
        from df_storyteller.web.helpers import markdown_to_html
        result = markdown_to_html("Just a line.")
        assert "<p>" in result
        assert "Just a line." in result


class TestDwarfNameMap:
    """Dwarf name mapping in helpers.py."""

    def test_builds_name_variations(self):
        from df_storyteller.web.helpers import build_dwarf_name_map
        from df_storyteller.context.character_tracker import CharacterTracker
        from df_storyteller.schema.entities import Dwarf

        tracker = CharacterTracker()
        tracker.register_dwarf(Dwarf(
            unit_id=1,
            name='Urist McTestington "Sparkle", Miner',
            profession="Miner",
        ))

        name_map = build_dwarf_name_map(tracker)

        # Full name
        assert 1 in name_map.values()
        # Without profession
        assert 'Urist McTestington "Sparkle"' in name_map
        # Nickname
        assert "Sparkle" in name_map
        # Without nickname
        assert "Urist McTestington" in name_map
        # First name
        assert "Urist" in name_map

    def test_short_names_excluded(self):
        from df_storyteller.web.helpers import build_dwarf_name_map
        from df_storyteller.context.character_tracker import CharacterTracker
        from df_storyteller.schema.entities import Dwarf

        tracker = CharacterTracker()
        tracker.register_dwarf(Dwarf(unit_id=1, name="Ab Cd", profession="Miner"))

        name_map = build_dwarf_name_map(tracker)
        # "Ab" is only 2 chars — should not be in map
        assert "Ab" not in name_map

    def test_empty_tracker(self):
        from df_storyteller.web.helpers import build_dwarf_name_map
        from df_storyteller.context.character_tracker import CharacterTracker

        name_map = build_dwarf_name_map(CharacterTracker())
        assert name_map == {}


class TestLinkifyDwarfNames:
    """Name linking in helpers.py."""

    def test_replaces_name_with_link(self):
        from df_storyteller.web.helpers import linkify_dwarf_names
        result = linkify_dwarf_names("Urist did something.", {"Urist": 42})
        assert '<a href="/dwarves/42"' in result
        assert "Urist" in result

    def test_does_not_double_link(self):
        from df_storyteller.web.helpers import linkify_dwarf_names
        text = '<a href="/dwarves/42" class="dwarf-link">Urist</a> said hello to Urist.'
        result = linkify_dwarf_names(text, {"Urist": 42})
        # The second occurrence should be linked, but the first should not be re-linked
        assert result.count('href="/dwarves/42"') == 2

    def test_empty_map_returns_unchanged(self):
        from df_storyteller.web.helpers import linkify_dwarf_names
        assert linkify_dwarf_names("hello world", {}) == "hello world"

    def test_longer_names_matched_first(self):
        from df_storyteller.web.helpers import linkify_dwarf_names
        result = linkify_dwarf_names("Urist McName arrived.", {"Urist McName": 1, "Urist": 2})
        # "Urist McName" should match as unit 1, not split as "Urist" unit 2
        assert 'href="/dwarves/1"' in result


class TestParseJournal:
    """Journal parsing in helpers.py."""

    def test_parse_empty_journal(self, tmp_path):
        from df_storyteller.web.helpers import parse_journal
        config = AppConfig(paths=PathsConfig())
        with patch("df_storyteller.web.helpers.get_fortress_dir", return_value=tmp_path):
            entries = parse_journal(config)
        assert entries == []

    def test_parse_journal_with_entries(self, tmp_path):
        from df_storyteller.web.helpers import parse_journal
        journal = tmp_path / "fortress_journal.md"
        journal.write_text(
            "# Fortress Journal\n\n---\n\n"
            "## Spring of Year 205\n\n"
            "The dwarves arrived at the mountain.\n\n---\n\n"
            "## Summer of Year 205\n\n"
            "A goblin siege!\n",
            encoding="utf-8",
        )
        config = AppConfig(paths=PathsConfig())
        with patch("df_storyteller.web.helpers.get_fortress_dir", return_value=tmp_path):
            entries = parse_journal(config)
        assert len(entries) == 2
        assert entries[0]["season"] == "spring"
        assert entries[0]["year"] == 205
        assert entries[1]["season"] == "summer"

    def test_parse_journal_manual_marker(self, tmp_path):
        from df_storyteller.web.helpers import parse_journal
        journal = tmp_path / "fortress_journal.md"
        journal.write_text(
            "# Fortress Journal\n\n---\n\n"
            "## Spring of Year 205\n\n"
            "<!-- source:manual -->\nPlayer written text.\n",
            encoding="utf-8",
        )
        config = AppConfig(paths=PathsConfig())
        with patch("df_storyteller.web.helpers.get_fortress_dir", return_value=tmp_path):
            entries = parse_journal(config)
        assert len(entries) == 1
        assert entries[0]["is_manual"] is True
        assert "source:manual" not in entries[0]["raw_text"]
