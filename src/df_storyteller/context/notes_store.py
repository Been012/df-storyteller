"""Persistent storage for player notes."""

from __future__ import annotations

import json
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.schema.notes import PlayerNote


def _notes_path(config: AppConfig, output_dir: Path | None = None) -> Path:
    d = output_dir or Path(config.paths.output_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "player_notes.json"


def load_all_notes(config: AppConfig, output_dir: Path | None = None) -> list[PlayerNote]:
    path = _notes_path(config, output_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return [PlayerNote.model_validate(n) for n in data]
    except (json.JSONDecodeError, OSError):
        return []


def save_all_notes(config: AppConfig, notes: list[PlayerNote], output_dir: Path | None = None) -> None:
    path = _notes_path(config, output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([n.model_dump(mode="json") for n in notes], f, indent=2, default=str)


def add_note(config: AppConfig, note: PlayerNote, output_dir: Path | None = None) -> PlayerNote:
    notes = load_all_notes(config, output_dir)
    notes.append(note)
    save_all_notes(config, notes, output_dir)
    return note


def resolve_note(config: AppConfig, note_id: str, output_dir: Path | None = None) -> bool:
    notes = load_all_notes(config, output_dir)
    for note in notes:
        if note.id == note_id:
            note.resolved = not note.resolved
            save_all_notes(config, notes, output_dir)
            return True
    return False


def delete_note(config: AppConfig, note_id: str, output_dir: Path | None = None) -> bool:
    notes = load_all_notes(config, output_dir)
    original_len = len(notes)
    notes = [n for n in notes if n.id != note_id]
    if len(notes) < original_len:
        save_all_notes(config, notes, output_dir)
        return True
    return False


def get_notes_for_dwarf(config: AppConfig, unit_id: int, output_dir: Path | None = None) -> list[PlayerNote]:
    return [
        n for n in load_all_notes(config, output_dir)
        if n.target_type == "dwarf" and n.target_id == unit_id and not n.resolved
    ]


def get_fortress_notes(config: AppConfig, output_dir: Path | None = None) -> list[PlayerNote]:
    return [
        n for n in load_all_notes(config, output_dir)
        if n.target_type == "fortress" and not n.resolved
    ]


def get_all_active_notes(config: AppConfig, output_dir: Path | None = None) -> list[PlayerNote]:
    return [n for n in load_all_notes(config, output_dir) if not n.resolved]
