"""Persistent storage for dwarf highlights (protagonist, antagonist, watchlist)."""

from __future__ import annotations

import json
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.schema.highlights import DwarfHighlight


def _highlights_path(config: AppConfig, output_dir: Path | None = None) -> Path:
    d = output_dir or Path(config.paths.output_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "highlights.json"


def load_all_highlights(config: AppConfig, output_dir: Path | None = None) -> list[DwarfHighlight]:
    path = _highlights_path(config, output_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return [DwarfHighlight.model_validate(h) for h in data]
    except (json.JSONDecodeError, OSError):
        return []


def _save_all(config: AppConfig, highlights: list[DwarfHighlight], output_dir: Path | None = None) -> None:
    path = _highlights_path(config, output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([h.model_dump(mode="json") for h in highlights], f, indent=2)


def set_highlight(config: AppConfig, highlight: DwarfHighlight, output_dir: Path | None = None) -> None:
    """Upsert a highlight — one per dwarf."""
    highlights = load_all_highlights(config, output_dir)
    highlights = [h for h in highlights if h.unit_id != highlight.unit_id]
    highlights.append(highlight)
    _save_all(config, highlights, output_dir)


def remove_highlight(config: AppConfig, unit_id: int, output_dir: Path | None = None) -> bool:
    highlights = load_all_highlights(config, output_dir)
    original_len = len(highlights)
    highlights = [h for h in highlights if h.unit_id != unit_id]
    if len(highlights) < original_len:
        _save_all(config, highlights, output_dir)
        return True
    return False


def get_highlight_for_dwarf(config: AppConfig, unit_id: int, output_dir: Path | None = None) -> DwarfHighlight | None:
    for h in load_all_highlights(config, output_dir):
        if h.unit_id == unit_id:
            return h
    return None
