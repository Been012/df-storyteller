"""Tests for the hotlink filter and lore_link Jinja2 global.

The hotlink filter converts [[name]] patterns to clickable lore links.
The lore_link global renders entity links in templates.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from df_storyteller.web.templates_setup import _hotlink_filter, _lore_link, _build_hotlink_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_hotlink_cache():
    """Ensure hotlink cache is fresh for each test."""
    import df_storyteller.web.state as st
    st._hotlink_cache = None
    yield
    st._hotlink_cache = None


@pytest.fixture
def hotlink_cache():
    """Pre-built hotlink cache for testing without legends data."""
    return {
        "urist mcgrandmaster": ("figure", 42),
        "urist": ("figure", 42),
        "mountainhome": ("site", 7),
        "the iron realm": ("civilization", 3),
        "the axe of fire": ("artifact", 15),
        "the great war": ("war", 100),
        "the saga of loss": ("written_work", 55),
        "spring dance": ("form_dance", "dance/12"),
        "harvest festival": ("festival", "3/5"),
    }


# ---------------------------------------------------------------------------
# lore_link tests
# ---------------------------------------------------------------------------


class TestLoreLink:
    """Jinja2 global: lore_link(entity_type, entity_id, name)."""

    def test_figure_link(self):
        result = _lore_link("figure", 42, "Urist")
        assert 'href="/lore/figure/42"' in result
        assert "Urist" in result
        assert "lore-link" in result

    def test_civilization_link(self):
        result = _lore_link("civilization", 3, "The Iron Realm")
        assert 'href="/lore/civ/3"' in result

    def test_site_link(self):
        result = _lore_link("site", 7, "Mountainhome")
        assert 'href="/lore/site/7"' in result

    def test_artifact_link(self):
        result = _lore_link("artifact", 15, "The Axe of Fire")
        assert 'href="/lore/artifact/15"' in result

    def test_war_link(self):
        result = _lore_link("war", 100, "The Great War")
        assert 'href="/lore/war/100"' in result

    def test_event_collection_types(self):
        for etype in ("duel", "purge", "beast_attack", "abduction", "theft", "persecution", "site_conquest", "overthrow"):
            result = _lore_link(etype, 1, "Event")
            assert 'href="/lore/event/1"' in result

    def test_written_work_link(self):
        result = _lore_link("written_work", 55, "The Saga")
        assert 'href="/lore/work/55"' in result

    def test_festival_link(self):
        result = _lore_link("festival", "3/5", "Harvest Fest")
        assert 'href="/lore/festival/3/5"' in result

    def test_form_links(self):
        result = _lore_link("form_poetic", "poetic/1", "Ode")
        assert 'href="/lore/form/poetic/1"' in result

    def test_none_id_returns_name(self):
        result = _lore_link("figure", None, "Urist")
        assert result == "Urist"

    def test_empty_name_returns_empty(self):
        result = _lore_link("figure", 42, "")
        assert result == ""

    def test_unknown_type_renders_plain(self):
        result = _lore_link("unknown_entity_type", 1, "Something")
        assert "<a " not in result
        assert "Something" in result
        assert "lore-link" in result  # Still styled, just not clickable

    def test_xss_in_name_escaped(self):
        result = _lore_link("figure", 42, '<script>alert("xss")</script>')
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ---------------------------------------------------------------------------
# hotlink filter tests
# ---------------------------------------------------------------------------


class TestHotlinkFilter:
    """Jinja2 filter: converts [[name]] → clickable lore links."""

    def test_no_brackets_returns_unchanged(self):
        text = "Just some normal text"
        assert _hotlink_filter(text) == text

    def test_with_empty_cache_strips_brackets(self):
        import df_storyteller.web.state as st
        st._hotlink_cache = {}  # Empty cache (not None — None would trigger rebuild)
        # Empty cache means no matches possible — brackets stripped
        result = _hotlink_filter("Hello [[Urist]]")
        assert "[[" not in result
        assert "]]" not in result

    def test_known_figure_becomes_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("The hero [[Urist McGrandmaster]] arrived.")
        assert 'href="/lore/figure/42"' in result
        assert "Urist McGrandmaster" in result
        assert "[[" not in result

    def test_known_site_becomes_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("They traveled to [[Mountainhome]].")
        assert 'href="/lore/site/7"' in result

    def test_known_civilization_becomes_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("Members of [[The Iron Realm]].")
        assert 'href="/lore/civ/3"' in result

    def test_known_artifact_becomes_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("Wielding [[The Axe of Fire]].")
        assert 'href="/lore/artifact/15"' in result

    def test_unknown_name_shows_indicator(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("The mysterious [[Zogbert the Unknown]].")
        assert "[[" not in result
        assert "Not found in legends" in result
        assert "border-bottom" in result  # Dashed underline indicator

    def test_case_insensitive_matching(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("[[MOUNTAINHOME]] is great.")
        assert 'href="/lore/site/7"' in result

    def test_multiple_names_in_text(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("[[Urist]] went to [[Mountainhome]].")
        assert 'href="/lore/figure/42"' in result
        assert 'href="/lore/site/7"' in result

    def test_xss_in_name_escaped(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter('[[<script>alert("xss")</script>]]')
        assert "<script>" not in result

    def test_nested_brackets_handled(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        # Non-greedy regex should match the first closing ]]
        result = _hotlink_filter("[[Urist]] and [[Mountainhome]]")
        assert result.count("lore-link") == 2

    def test_written_work_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("Read [[The Saga of Loss]].")
        assert 'href="/lore/work/55"' in result

    def test_festival_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("During [[Harvest Festival]].")
        assert 'href="/lore/festival/3/5"' in result

    def test_cultural_form_link(self, hotlink_cache):
        import df_storyteller.web.state as st
        st.set_hotlink_cache(hotlink_cache)

        result = _hotlink_filter("Performed the [[Spring Dance]].")
        assert 'href="/lore/form/dance/12"' in result


# ---------------------------------------------------------------------------
# hotlink cache building
# ---------------------------------------------------------------------------


class TestBuildHotlinkCache:
    """Cache is built correctly from legends data."""

    def test_cache_returns_existing(self):
        import df_storyteller.web.state as st
        existing = {"test": ("figure", 1)}
        st.set_hotlink_cache(existing)

        result = _build_hotlink_cache()
        assert result is existing

    def test_cache_built_from_legends(self):
        from df_storyteller.ingestion.legends_parser import LegendsData
        from df_storyteller.schema.entities import HistoricalFigure, Site, Civilization, Artifact
        from df_storyteller.context.world_lore import WorldLore

        legends = LegendsData()
        legends.historical_figures = {
            1: HistoricalFigure(hf_id=1, name="Urist McHero"),
            2: HistoricalFigure(hf_id=2, name="Goblin the Destroyer"),
        }
        legends.sites = {10: Site(site_id=10, name="Mountainhome")}
        legends.civilizations = {5: Civilization(entity_id=5, name="The Dwarven Realm")}
        legends.artifacts = {20: Artifact(artifact_id=20, name="The Golden Pick")}
        legends.event_collections = [
            {"id": "100", "type": "war", "name": "The Great War"},
        ]
        legends.written_contents = [
            {"id": "55", "title": "The Book of Grudges"},
        ]

        world_lore = WorldLore()
        world_lore.load(legends)

        config_mock = type("Cfg", (), {"paths": type("P", (), {"event_dir": ""})()})()

        with patch("df_storyteller.web.state.get_config", return_value=config_mock), \
             patch("df_storyteller.web.state.load_game_state_safe",
                   return_value=(None, None, world_lore, {})):
            cache = _build_hotlink_cache()

        assert cache["urist mchero"] == ("figure", 1)
        assert cache["mountainhome"] == ("site", 10)
        assert cache["the dwarven realm"] == ("civilization", 5)
        assert cache["the golden pick"] == ("artifact", 20)
        assert cache["the great war"] == ("war", "100")
        assert cache["the book of grudges"] == ("written_work", "55")

        # First-name abbreviations are indexed (part before comma or " the ", if >3 chars)
        # "Urist McHero" → first = "Urist McHero" (no comma, no " the ")
        # "Goblin the Destroyer" → first = "Goblin" (split on " the ")
        assert cache["goblin"] == ("figure", 2)
