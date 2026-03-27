"""Tests for gamelog.txt parser."""

from pathlib import Path

from df_storyteller.ingestion.gamelog_parser import GamelogParser
from df_storyteller.schema.events import EventType

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_season_change():
    parser = GamelogParser()
    events = list(parser.parse_lines(["Early Spring has arrived on the calendar."]))
    assert len(events) == 1
    assert events[0].event_type == EventType.SEASON_CHANGE


def test_parse_death_announcement():
    parser = GamelogParser()
    events = list(parser.parse_lines(["Urist McStonecutter, Miner has been found dead."]))
    assert len(events) == 1
    assert events[0].event_type == EventType.DEATH
    assert events[0].data.victim.name == "Urist McStonecutter, Miner"


def test_parse_mood():
    parser = GamelogParser()
    events = list(parser.parse_lines(["Aban Regularseal is taken by a fey mood!"]))
    assert len(events) == 1
    assert events[0].event_type == EventType.MOOD
    assert events[0].data.mood_type == "fey"


def test_parse_artifact_creation():
    parser = GamelogParser()
    events = list(parser.parse_lines(
        ["Rakust Craftbeard has created Daggerglimmer, a bismuth bronze short sword!"]
    ))
    assert len(events) == 1
    assert events[0].event_type == EventType.ARTIFACT
    assert events[0].data.artifact_name == "Daggerglimmer"
    assert events[0].data.item_type == "bismuth bronze short sword"


def test_parse_combat_block():
    parser = GamelogParser()
    lines = [
        "The Stray Dog (Tame) strikes The Goblin Lasher in the upper body with his left front paw!",
        "The Goblin Lasher misses The Stray Dog (Tame)!",
        "",  # blank line terminates combat block
    ]
    events = list(parser.parse_lines(lines))
    combat_events = [e for e in events if e.event_type == EventType.COMBAT]
    assert len(combat_events) == 1
    assert "Stray Dog" in combat_events[0].data.attacker.name


def test_parse_full_sample_file():
    parser = GamelogParser()
    events = parser.parse_file(FIXTURES / "sample_gamelog.txt")
    assert len(events) > 0

    event_types = {e.event_type for e in events}
    assert EventType.SEASON_CHANGE in event_types
    assert EventType.DEATH in event_types
    assert EventType.MOOD in event_types
    assert EventType.ARTIFACT in event_types


def test_season_tracking():
    parser = GamelogParser()
    events = list(parser.parse_lines([
        "Early Spring has arrived on the calendar.",
        "Urist McStonecutter, Miner has been found dead.",
    ]))
    death = [e for e in events if e.event_type == EventType.DEATH][0]
    assert death.season.value == "spring"
