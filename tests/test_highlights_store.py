"""Tests for dwarf highlight CRUD operations."""

from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.context.highlights_store import (
    get_highlight_for_dwarf,
    load_all_highlights,
    remove_highlight,
    set_highlight,
)
from df_storyteller.schema.highlights import DwarfHighlight, DwarfRole


def _config(tmp_path: Path) -> AppConfig:
    config = AppConfig()
    config.paths.output_dir = str(tmp_path)
    return config


def test_empty_highlights(tmp_path: Path):
    config = _config(tmp_path)
    assert load_all_highlights(config) == []


def test_set_and_load_highlight(tmp_path: Path):
    config = _config(tmp_path)
    h = DwarfHighlight(unit_id=42, name="Urist", role=DwarfRole.PROTAGONIST)
    set_highlight(config, h)

    highlights = load_all_highlights(config)
    assert len(highlights) == 1
    assert highlights[0].unit_id == 42
    assert highlights[0].name == "Urist"
    assert highlights[0].role == DwarfRole.PROTAGONIST


def test_upsert_replaces_existing(tmp_path: Path):
    config = _config(tmp_path)
    set_highlight(config, DwarfHighlight(unit_id=42, name="Urist", role=DwarfRole.PROTAGONIST))
    set_highlight(config, DwarfHighlight(unit_id=42, name="Urist", role=DwarfRole.ANTAGONIST))

    highlights = load_all_highlights(config)
    assert len(highlights) == 1
    assert highlights[0].role == DwarfRole.ANTAGONIST


def test_multiple_dwarves(tmp_path: Path):
    config = _config(tmp_path)
    set_highlight(config, DwarfHighlight(unit_id=1, name="Urist", role=DwarfRole.PROTAGONIST))
    set_highlight(config, DwarfHighlight(unit_id=2, name="Olin", role=DwarfRole.WATCHLIST))

    highlights = load_all_highlights(config)
    assert len(highlights) == 2


def test_remove_highlight(tmp_path: Path):
    config = _config(tmp_path)
    set_highlight(config, DwarfHighlight(unit_id=42, name="Urist", role=DwarfRole.PROTAGONIST))
    assert remove_highlight(config, 42) is True
    assert load_all_highlights(config) == []


def test_remove_nonexistent(tmp_path: Path):
    config = _config(tmp_path)
    assert remove_highlight(config, 999) is False


def test_get_highlight_for_dwarf(tmp_path: Path):
    config = _config(tmp_path)
    set_highlight(config, DwarfHighlight(unit_id=42, name="Urist", role=DwarfRole.PROTAGONIST))

    h = get_highlight_for_dwarf(config, 42)
    assert h is not None
    assert h.role == DwarfRole.PROTAGONIST

    assert get_highlight_for_dwarf(config, 999) is None
