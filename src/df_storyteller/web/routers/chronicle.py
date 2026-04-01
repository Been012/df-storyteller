"""Chronicle routes."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from df_storyteller.config import AppConfig
from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
)
from df_storyteller.web.helpers import (
    build_dwarf_name_map as _build_dwarf_name_map,
    linkify_dwarf_names as _linkify_dwarf_names,
    parse_journal as _parse_journal,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def chronicle_page(request: Request):
    config = _get_config()
    _, character_tracker, _, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "chronicle", metadata)
    fortress_dir = _get_fortress_dir(config, metadata)
    entries = _parse_journal(config, metadata)

    # Show newest entries first
    entries.reverse()

    # Hotlink dwarf names in story text
    name_map = _build_dwarf_name_map(character_tracker)
    for entry in entries:
        entry["text"] = _linkify_dwarf_names(entry["text"], name_map)

    # Check if current season already has an entry
    from df_storyteller.output.journal import has_entry_for
    current_season = metadata.get("season", "")
    current_year = metadata.get("year", 0)
    already_written = has_entry_for(config, current_season, current_year, fortress_dir) if current_season and current_year else False

    # Load fortress-wide notes
    from df_storyteller.context.notes_store import load_all_notes
    all_notes = load_all_notes(config, fortress_dir)
    fortress_notes = [n for n in all_notes if n.target_type == "fortress"]

    return templates.TemplateResponse(request=request, name="chronicle.html", context={
        **ctx, "entries": entries, "dwarf_name_map": name_map,
        "current_season": current_season, "current_year": current_year,
        "already_written": already_written,
        "fortress_notes": fortress_notes,
    })


@router.post("/api/chronicle/generate")
async def api_generate_chronicle(request: Request):
    """Stream a chronicle entry."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass
    return StreamingResponse(
        _stream_chronicle(config, one_time),
        media_type="text/plain",
    )


async def _stream_chronicle(config: AppConfig, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.chronicle import prepare_chronicle
    from df_storyteller.stories.base import create_provider
    try:
        fortress_dir = _get_fortress_dir(config)
        system_prompt, user_prompt, max_tokens, temperature, save = await prepare_chronicle(
            config, None, one_time_context=one_time_context, output_dir=fortress_dir,
        )
        provider = create_provider(config)
        full_text = ""
        async for chunk in provider.stream_generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            full_text += chunk
            yield chunk
        save(full_text)
    except ValueError as e:
        logger.warning("Generation failed: %s", e)
        yield f"Error: {e}"
    except Exception:
        logger.exception("Generation failed")
        yield "Error: generation failed. Check Settings and try again."


@router.post("/api/chronicle/manual")
async def api_chronicle_manual(request: Request):
    """Save a player-written chronicle entry."""
    from df_storyteller.output.journal import append_to_journal
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    season = data.get("season", metadata.get("season", "spring"))
    year = data.get("year", metadata.get("year", 0))
    fortress_dir = _get_fortress_dir(config, metadata)

    # Mark as manual so the UI can distinguish from AI entries
    # Image references are inline in text as {{img:uuid.ext}}
    marked_text = f"<!-- source:manual -->\n{text}"
    append_to_journal(config, marked_text, int(year), season, output_dir=fortress_dir)

    return {"ok": True, "season": season, "year": int(year)}
