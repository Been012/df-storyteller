"""Tests for DFHack JSON event parser."""

import json
from pathlib import Path

from df_storyteller.ingestion.dfhack_json_parser import parse_dfhack_event, parse_dfhack_file
from df_storyteller.schema.events import DeathEvent, EventSource, EventType

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_death_event():
    with open(FIXTURES / "sample_dfhack_event.json") as f:
        raw = json.load(f)

    event = parse_dfhack_event(raw)
    assert isinstance(event, DeathEvent)
    assert event.event_type == EventType.DEATH
    assert event.source == EventSource.DFHACK
    assert event.game_year == 205
    assert event.data.victim.name == "Urist McStonecutter"
    assert event.data.killer.name == "Nguslu"
    assert event.data.cause == "combat"


def test_parse_death_event_file():
    event = parse_dfhack_file(FIXTURES / "sample_dfhack_event.json")
    assert event is not None
    assert event.event_type == EventType.DEATH


def test_parse_unknown_event_type():
    raw = {
        "event_type": "unknown_future_event",
        "game_year": 100,
        "game_tick": 0,
        "season": "spring",
        "data": {"info": "test"},
    }
    event = parse_dfhack_event(raw)
    assert event.event_type == EventType.ANNOUNCEMENT  # Falls back to announcement


def test_parse_combat_event():
    raw = {
        "event_type": "combat",
        "game_year": 205,
        "game_tick": 50000,
        "season": "summer",
        "data": {
            "attacker": {"unit_id": 1, "name": "Urist", "race": "DWARF", "profession": "Axedwarf"},
            "defender": {"unit_id": 2, "name": "Nguslu", "race": "GOBLIN", "profession": "Lasher"},
            "weapon": "battle axe",
            "body_part": "upper body",
            "is_lethal": False,
        },
    }
    event = parse_dfhack_event(raw)
    assert event.event_type == EventType.COMBAT
    assert event.data.attacker.name == "Urist"
    assert event.data.defender.name == "Nguslu"


def test_parse_mood_event():
    raw = {
        "event_type": "mood",
        "game_year": 205,
        "game_tick": 30000,
        "season": "autumn",
        "data": {
            "unit": {"unit_id": 5, "name": "Aban Regularseal", "race": "DWARF", "profession": "Mason"},
            "mood_type": "fey",
        },
    }
    event = parse_dfhack_event(raw)
    assert event.event_type == EventType.MOOD
    assert event.data.mood_type == "fey"


def test_parse_malformed_file_returns_none():
    # Non-existent file
    result = parse_dfhack_file(Path("/nonexistent/path.json"))
    assert result is None
