"""Tests for legends XML parser."""

from pathlib import Path

from df_storyteller.ingestion.legends_parser import parse_legends_xml

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_historical_figures():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    assert len(data.historical_figures) == 2
    assert 100 in data.historical_figures
    assert data.historical_figures[100].name == "kadol hammerlord"
    assert data.historical_figures[100].race == "DWARF"
    assert data.historical_figures[100].death_year == 150


def test_parse_sites():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    assert len(data.sites) == 2
    assert data.sites[1].name == "daggerhalls"
    assert data.sites[1].site_type == "fortress"
    assert data.sites[2].site_type == "dark fortress"


def test_parse_civilizations():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    assert len(data.civilizations) == 2
    assert data.civilizations[1].name == "the iron confederation"
    assert data.civilizations[2].race == "GOBLIN"


def test_parse_artifacts():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    assert len(data.artifacts) == 1
    assert data.artifacts[1].name == "daggerglimmer"
    assert data.artifacts[1].item_type == "short sword"


def test_parse_historical_events():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    assert len(data.historical_events) >= 1
    assert data.historical_events[0]["type"] == "hf_died"


def test_parse_event_collections():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    assert len(data.event_collections) >= 1
    war = data.event_collections[0]
    assert war["type"] == "war"
    assert war["name"] == "the war of swords"


def test_get_wars_involving():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    wars = data.get_wars_involving(1)  # Iron confederation
    assert len(wars) == 1


def test_stats():
    data = parse_legends_xml(FIXTURES / "sample_legends.xml")
    stats = data.stats()
    assert stats["historical_figures"] == 2
    assert stats["sites"] == 2
    assert stats["civilizations"] == 2
    assert stats["artifacts"] == 1
