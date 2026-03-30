"""Highlights API routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
)

router = APIRouter()


@router.get("/api/highlights")
async def api_highlights_list():
    """List all dwarf highlights."""
    from df_storyteller.context.highlights_store import load_all_highlights
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    highlights = load_all_highlights(config, output_dir=fortress_dir)
    return [h.model_dump() for h in highlights]


@router.post("/api/highlights")
async def api_highlights_set(request: Request):
    """Set or update a highlight on a dwarf."""
    from df_storyteller.context.highlights_store import set_highlight
    from df_storyteller.schema.highlights import DwarfHighlight
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    try:
        highlight = DwarfHighlight.model_validate(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    set_highlight(config, highlight, output_dir=fortress_dir)
    return {"ok": True}


@router.delete("/api/highlights/{unit_id}")
async def api_highlights_remove(unit_id: int):
    """Remove a highlight from a dwarf."""
    from df_storyteller.context.highlights_store import remove_highlight
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    removed = remove_highlight(config, unit_id, output_dir=fortress_dir)
    if not removed:
        return JSONResponse({"error": "No highlight found"}, status_code=404)
    return {"ok": True}
