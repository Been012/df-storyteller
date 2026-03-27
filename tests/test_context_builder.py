"""Tests for context builder."""

from df_storyteller.context.character_tracker import CharacterTracker, normalize_name
from df_storyteller.context.context_builder import ContextBuilder, _format_event
from df_storyteller.context.event_store import EventStore
from df_storyteller.context.world_lore import WorldLore
from df_storyteller.schema.entities import Dwarf
from df_storyteller.schema.events import (
    DeathData,
    DeathEvent,
    EventSource,
    Season,
    SeasonChangeData,
    SeasonChangeEvent,
    UnitRef,
)


def _make_death_event(year: int = 205, season: str = "autumn") -> DeathEvent:
    return DeathEvent(
        game_year=year,
        game_tick=50000,
        season=Season(season),
        source=EventSource.DFHACK,
        data=DeathData(
            victim=UnitRef(unit_id=1, name="Urist McTest", race="DWARF", profession="Miner"),
            cause="combat",
        ),
    )


def _make_season_event(year: int = 205, season: str = "autumn") -> SeasonChangeEvent:
    return SeasonChangeEvent(
        game_year=year,
        game_tick=0,
        season=Season(season),
        source=EventSource.GAMELOG,
        data=SeasonChangeData(new_season=Season(season), population=50),
    )


def test_format_death_event():
    event = _make_death_event()
    text = _format_event(event)
    assert "DEATH" in text
    assert "Urist McTest" in text


def test_format_season_event():
    event = _make_season_event()
    text = _format_event(event)
    assert "SEASON" in text
    assert "50" in text


def test_event_store_add_and_query():
    store = EventStore()
    e1 = _make_death_event(year=205, season="autumn")
    e2 = _make_season_event(year=205, season="autumn")

    store.add(e1)
    store.add(e2)

    assert store.count == 2
    assert len(store.events_by_type(e1.event_type)) == 1
    assert len(store.events_in_season(205, "autumn")) == 2


def test_chronicle_context_builder():
    store = EventStore()
    store.add(_make_death_event())
    store.add(_make_season_event())

    builder = ContextBuilder(
        event_store=store,
        character_tracker=CharacterTracker(),
        world_lore=WorldLore(),
    )

    ctx = builder.build_chronicle_context(year=205, season="autumn")
    assert ctx.mode == "chronicle"
    assert "Urist McTest" in ctx.events_text
    assert ctx.estimated_tokens > 0


def test_biography_context_with_no_dwarf():
    builder = ContextBuilder(
        event_store=EventStore(),
        character_tracker=CharacterTracker(),
        world_lore=WorldLore(),
    )
    ctx = builder.build_biography_context(unit_id=999)
    assert ctx.mode == "biography"
    assert ctx.events_text == ""


def test_saga_context_without_legends():
    builder = ContextBuilder(
        event_store=EventStore(),
        character_tracker=CharacterTracker(),
        world_lore=WorldLore(),
    )
    ctx = builder.build_saga_context()
    assert "No legends data loaded" in ctx.lore_text


def test_context_trimming():
    store = EventStore()
    # Add many events to exceed token budget
    for i in range(200):
        store.add(_make_death_event(year=205, season="autumn"))

    builder = ContextBuilder(
        event_store=store,
        character_tracker=CharacterTracker(),
        world_lore=WorldLore(),
        max_context_tokens=500,
    )

    ctx = builder.build_chronicle_context(year=205, season="autumn")
    assert ctx.estimated_tokens <= 600  # Allow some overshoot from truncation


def test_normalize_name_strips_diacritics():
    assert normalize_name("Ürïst") == "urist"
    assert normalize_name("Mörul") == "morul"
    assert normalize_name("Äs Öddom") == "as oddom"
    assert normalize_name("Thîkut") == "thikut"
    assert normalize_name("Régel") == "regel"
    assert normalize_name("Plain Name") == "plain name"


def test_find_by_name_diacritic_insensitive():
    tracker = CharacterTracker()
    tracker.register_dwarf(Dwarf(unit_id=1, name="Ürïst Mörul", profession="Miner"))
    tracker.register_dwarf(Dwarf(unit_id=2, name="Thîkut Régel", profession="Mason"))

    # ASCII search finds diacritic names
    assert tracker.find_by_name("urist").unit_id == 1
    assert tracker.find_by_name("morul").unit_id == 1
    assert tracker.find_by_name("thikut").unit_id == 2
    assert tracker.find_by_name("regel").unit_id == 2

    # Exact diacritics still work
    assert tracker.find_by_name("Ürïst").unit_id == 1

    # No match returns None
    assert tracker.find_by_name("nobody") is None
