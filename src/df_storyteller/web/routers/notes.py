"""Notes API routes."""
from __future__ import annotations

from fastapi import APIRouter, Request

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
)

router = APIRouter()


@router.get("/api/notes")
async def api_list_notes(target_type: str | None = None, target_id: int | None = None):
    from df_storyteller.context.notes_store import load_all_notes
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    notes = load_all_notes(config, fortress_dir)
    if target_type:
        notes = [n for n in notes if n.target_type == target_type]
    if target_id is not None:
        notes = [n for n in notes if n.target_id == target_id]
    return [n.model_dump(mode="json") for n in notes]


@router.post("/api/notes")
async def api_create_note(request: Request):
    from df_storyteller.context.notes_store import add_note
    from df_storyteller.schema.notes import PlayerNote, NoteTag
    config = _get_config()
    data = await request.json()

    # Get current game time from latest snapshot metadata
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    note = PlayerNote(
        tag=NoteTag(data["tag"]),
        text=data["text"],
        target_type=data.get("target_type", "fortress"),
        target_id=data.get("target_id"),
        game_year=metadata.get("year", 0),
        game_season=metadata.get("season", ""),
    )
    add_note(config, note, fortress_dir)
    return note.model_dump(mode="json")


@router.post("/api/notes/{note_id}/resolve")
async def api_resolve_note(note_id: str):
    from df_storyteller.context.notes_store import resolve_note
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = resolve_note(config, note_id, fortress_dir)
    return {"ok": ok}


@router.delete("/api/notes/{note_id}")
async def api_delete_note(note_id: str):
    from df_storyteller.context.notes_store import delete_note
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = delete_note(config, note_id, fortress_dir)
    return {"ok": ok}
