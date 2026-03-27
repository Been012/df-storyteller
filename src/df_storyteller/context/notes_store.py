"""Persistent storage for player notes."""

from __future__ import annotations

import json
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.schema.notes import PlayerNote


def _notes_path(config: AppConfig) -> Path:
    output_dir = Path(config.paths.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "player_notes.json"


def load_all_notes(config: AppConfig) -> list[PlayerNote]:
    path = _notes_path(config)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return [PlayerNote.model_validate(n) for n in data]
    except (json.JSONDecodeError, OSError):
        return []


def save_all_notes(config: AppConfig, notes: list[PlayerNote]) -> None:
    path = _notes_path(config)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([n.model_dump(mode="json") for n in notes], f, indent=2, default=str)


def add_note(config: AppConfig, note: PlayerNote) -> PlayerNote:
    notes = load_all_notes(config)
    notes.append(note)
    save_all_notes(config, notes)
    return note


def resolve_note(config: AppConfig, note_id: str) -> bool:
    notes = load_all_notes(config)
    for note in notes:
        if note.id == note_id:
            note.resolved = not note.resolved
            save_all_notes(config, notes)
            return True
    return False


def delete_note(config: AppConfig, note_id: str) -> bool:
    notes = load_all_notes(config)
    original_len = len(notes)
    notes = [n for n in notes if n.id != note_id]
    if len(notes) < original_len:
        save_all_notes(config, notes)
        return True
    return False


def get_notes_for_dwarf(config: AppConfig, unit_id: int) -> list[PlayerNote]:
    return [
        n for n in load_all_notes(config)
        if n.target_type == "dwarf" and n.target_id == unit_id and not n.resolved
    ]


def get_fortress_notes(config: AppConfig) -> list[PlayerNote]:
    return [
        n for n in load_all_notes(config)
        if n.target_type == "fortress" and not n.resolved
    ]


def get_all_active_notes(config: AppConfig) -> list[PlayerNote]:
    return [n for n in load_all_notes(config) if not n.resolved]
