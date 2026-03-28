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


def test_parse_detailed_combat():
    """Test DF Premium detailed combat with weapon and effects."""
    parser = GamelogParser()
    events = parser.parse_file(FIXTURES / "combat_gamelog.txt")
    combat_events = [e for e in events if e.event_type == EventType.COMBAT]
    assert len(combat_events) >= 1

    combat = combat_events[0]
    assert "militia commander" in combat.data.attacker.name.lower()
    assert "giant groundhog" in combat.data.defender.name.lower()
    assert combat.data.weapon == "copper battle axe"
    assert len(combat.data.blows) > 0
    assert combat.data.blows[0].action == "hacks"
    assert combat.data.blows[0].weapon == "copper battle axe"
    assert len(combat.data.injuries) > 0
    assert combat.data.is_lethal  # cloven asunder


def test_combat_blow_details():
    """Test that individual blows capture body part and effect."""
    parser = GamelogParser()
    lines = [
        "The militia commander hacks the giant groundhog in the right front paw with his (copper battle axe), tearing apart the muscle!",
        "An artery has been opened by the attack and many nerves have been severed!",
        "",
    ]
    events = list(parser.parse_lines(lines))
    combat_events = [e for e in events if e.event_type == EventType.COMBAT]
    assert len(combat_events) == 1
    blow = combat_events[0].data.blows[0]
    assert blow.body_part == "right front paw"
    assert "tearing apart the muscle" in blow.effect
    assert len(combat_events[0].data.injuries) == 1


def test_combat_outcome_tracking():
    """Test that combat outcomes (falls over, gives in) are captured."""
    parser = GamelogParser()
    lines = [
        "The militia commander hacks the giant groundhog in the left rear paw with his (copper battle axe), tearing apart the muscle!",
        "The giant groundhog falls over.",
        "The militia commander hacks the giant groundhog in the head with his (copper battle axe), tearing apart the muscle!",
        "The giant groundhog gives in to pain.",
        "",
    ]
    events = list(parser.parse_lines(lines))
    combat_events = [e for e in events if e.event_type == EventType.COMBAT]
    assert len(combat_events) == 1
    assert combat_events[0].data.outcome == "gives in to pain"
