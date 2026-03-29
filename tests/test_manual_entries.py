"""Tests for manual writing features (no-LLM mode)."""

from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.output.journal import append_to_journal, has_entry_for
from df_storyteller.stories.biography import load_biography_history, _save_biography_entry


def _config(tmp_path: Path) -> AppConfig:
    config = AppConfig()
    config.paths.output_dir = str(tmp_path)
    return config


def test_manual_chronicle_with_marker(tmp_path: Path):
    config = _config(tmp_path)
    text = "<!-- source:manual -->\nThe dwarves dug deep this season."
    append_to_journal(config, text, 150, "spring", output_dir=tmp_path)

    assert has_entry_for(config, "spring", 150, output_dir=tmp_path)
    journal = (tmp_path / "fortress_journal.md").read_text()
    assert "<!-- source:manual -->" in journal
    assert "The dwarves dug deep this season." in journal


def test_manual_chronicle_replaces_existing(tmp_path: Path):
    config = _config(tmp_path)
    append_to_journal(config, "First entry", 150, "spring", output_dir=tmp_path)
    append_to_journal(config, "<!-- source:manual -->\nReplacement entry", 150, "spring", output_dir=tmp_path)

    journal = (tmp_path / "fortress_journal.md").read_text()
    assert "First entry" not in journal
    assert "Replacement entry" in journal


def test_manual_biography_entry(tmp_path: Path):
    config = _config(tmp_path)
    _save_biography_entry(config, 42, {
        "year": 150,
        "season": "spring",
        "text": "A brave dwarf who loves mining.",
        "profession": "Miner",
        "stress_category": 2,
        "is_manual": True,
    }, output_dir=tmp_path)

    history = load_biography_history(config, 42, output_dir=tmp_path)
    assert len(history) == 1
    assert history[0]["text"] == "A brave dwarf who loves mining."
    assert history[0]["is_manual"] is True


def test_manual_diary_entry(tmp_path: Path):
    config = _config(tmp_path)
    _save_biography_entry(config, 42, {
        "year": 150,
        "season": "spring",
        "text": "Today I struck adamantine!",
        "is_diary": True,
        "is_manual": True,
    }, output_dir=tmp_path)

    history = load_biography_history(config, 42, output_dir=tmp_path)
    assert len(history) == 1
    assert history[0]["is_diary"] is True
    assert history[0]["is_manual"] is True


def test_no_llm_mode_config():
    config = AppConfig()
    assert config.story.no_llm_mode is False
    config.story.no_llm_mode = True
    assert config.story.no_llm_mode is True
