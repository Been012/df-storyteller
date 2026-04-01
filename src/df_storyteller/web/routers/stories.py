"""Story generation routes (biography, eulogy, diary, saga)."""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime as _dt
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from df_storyteller.config import AppConfig
from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _stream_with_save(
    config: AppConfig,
    prepare_fn,
    *args,
) -> AsyncGenerator[str, None]:
    """Generic true-streaming helper: prepare prompts, stream from LLM, save result."""
    from df_storyteller.stories.base import create_provider

    try:
        result = await prepare_fn(config, *args)
        if isinstance(result, str):
            yield result
            return

        system_prompt, user_prompt, max_tokens, temperature, save = result
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


# ==================== Biography ====================


@router.post("/api/bio/{unit_id}")
async def api_generate_bio(unit_id: int, request: Request):
    """Stream a biography."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass

    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return StreamingResponse(iter(["Dwarf not found."]), media_type="text/plain")

    from df_storyteller.stories.biography import prepare_biography
    fortress_dir = _get_fortress_dir(config, metadata)

    return StreamingResponse(
        _stream_with_save(config, prepare_biography, dwarf.name, one_time, fortress_dir),
        media_type="text/plain",
    )


@router.post("/api/bio/{unit_id}/manual")
async def api_bio_manual(unit_id: int, request: Request):
    """Save a player-written biography entry."""
    from df_storyteller.stories.biography import _save_biography_entry
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    fortress_dir = _get_fortress_dir(config, metadata)

    entry = {
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "text": text,
        "profession": dwarf.profession if dwarf else "",
        "stress_category": dwarf.stress_category if dwarf else 0,
        "is_manual": True,
    }
    if data.get("is_diary"):
        entry["is_diary"] = True
    if data.get("images"):
        entry["images"] = data["images"]

    _save_biography_entry(config, unit_id, entry, output_dir=fortress_dir)
    return {"ok": True}


# ==================== Eulogy ====================


@router.post("/api/eulogy/{unit_id}")
async def api_generate_eulogy(unit_id: int, request: Request):
    """Stream a death eulogy for a fallen dwarf."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass

    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return StreamingResponse(iter(["Dwarf not found."]), media_type="text/plain")

    from df_storyteller.stories.biography import prepare_eulogy
    fortress_dir = _get_fortress_dir(config, metadata)

    return StreamingResponse(
        _stream_with_save(config, prepare_eulogy, dwarf.name, one_time, fortress_dir),
        media_type="text/plain",
    )


# ==================== Diary ====================


@router.post("/api/diary/{unit_id}")
async def api_generate_diary(unit_id: int, request: Request):
    """Stream a first-person diary entry for a dwarf."""
    config = _get_config()
    one_time = ""
    try:
        data = await request.json()
        one_time = data.get("context", "")
    except Exception:
        pass

    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return StreamingResponse(iter(["Dwarf not found."]), media_type="text/plain")

    from df_storyteller.stories.biography import prepare_diary
    fortress_dir = _get_fortress_dir(config, metadata)

    return StreamingResponse(
        _stream_with_save(config, prepare_diary, dwarf.name, one_time, fortress_dir),
        media_type="text/plain",
    )


@router.post("/api/diary/{unit_id}/manual")
async def api_diary_manual(unit_id: int, request: Request):
    """Save a player-written diary entry."""
    from df_storyteller.stories.biography import _save_biography_entry
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    fortress_dir = _get_fortress_dir(config, metadata)

    entry = {
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "text": text,
        "profession": dwarf.profession if dwarf else "",
        "stress_category": dwarf.stress_category if dwarf else 0,
        "is_diary": True,
        "is_manual": True,
    }
    if data.get("images"):
        entry["images"] = data["images"]
    _save_biography_entry(config, unit_id, entry, output_dir=fortress_dir)
    return {"ok": True}


# ==================== Saga ====================


@router.post("/api/saga/generate")
async def api_generate_saga():
    """Stream a saga."""
    config = _get_config()
    from df_storyteller.stories.saga import prepare_saga
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    return StreamingResponse(
        _stream_with_save(config, prepare_saga, "full", fortress_dir),
        media_type="text/plain",
    )


@router.post("/api/saga/manual")
async def api_saga_manual(request: Request):
    """Save a player-written saga entry."""
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    saga_path = fortress_dir / "saga.json"

    existing = []
    if saga_path.exists():
        try:
            existing = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            pass

    saga_entry: dict = {
        "text": text,
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "is_manual": True,
    }
    if data.get("images"):
        saga_entry["images"] = data["images"]
    existing.append(saga_entry)
    saga_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}
