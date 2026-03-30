"""Story generation routes (biography, eulogy, diary, saga)."""
from __future__ import annotations

import asyncio
import logging
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

    return StreamingResponse(
        _stream_bio(config, dwarf.name, one_time),
        media_type="text/plain",
    )


async def _stream_bio(config: AppConfig, dwarf_name: str, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.biography import generate_biography
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_biography(config, dwarf_name, one_time_context=one_time_context, output_dir=fortress_dir)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Generation failed")
        yield "Error: generation failed. Check server logs for details."


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

    return StreamingResponse(
        _stream_eulogy(config, dwarf.name, one_time),
        media_type="text/plain",
    )


async def _stream_eulogy(config: AppConfig, dwarf_name: str, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.biography import generate_eulogy
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_eulogy(config, dwarf_name, one_time_context=one_time_context, output_dir=fortress_dir)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Eulogy generation failed")
        yield "Error: generation failed. Check server logs for details."


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

    return StreamingResponse(
        _stream_diary(config, dwarf.name, one_time),
        media_type="text/plain",
    )


async def _stream_diary(config: AppConfig, dwarf_name: str, one_time_context: str = "") -> AsyncGenerator[str, None]:
    from df_storyteller.stories.biography import generate_diary
    try:
        fortress_dir = _get_fortress_dir(config)
        result = await generate_diary(config, dwarf_name, one_time_context=one_time_context, output_dir=fortress_dir)
        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Diary generation failed")
        yield "Error: generation failed. Check server logs for details."


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

    _save_biography_entry(config, unit_id, {
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "text": text,
        "profession": dwarf.profession if dwarf else "",
        "stress_category": dwarf.stress_category if dwarf else 0,
        "is_diary": True,
        "is_manual": True,
    }, output_dir=fortress_dir)
    return {"ok": True}


# ==================== Saga ====================


@router.post("/api/saga/generate")
async def api_generate_saga():
    """Stream a saga."""
    config = _get_config()
    return StreamingResponse(
        _stream_saga(config),
        media_type="text/plain",
    )


async def _stream_saga(config: AppConfig) -> AsyncGenerator[str, None]:
    from df_storyteller.stories.saga import generate_saga
    try:
        result = await generate_saga(config, "full")

        # Save saga to per-fortress directory
        try:
            _, _, _, metadata = _load_game_state_safe(config)
            fortress_dir = _get_fortress_dir(config, metadata)
            import json as _json
            saga_path = fortress_dir / "saga.json"
            existing = []
            if saga_path.exists():
                try:
                    existing = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
                except (ValueError, OSError):
                    existing = []
            from datetime import datetime as _dt
            existing.append({
                "text": result,
                "year": metadata.get("year", 0),
                "season": metadata.get("season", ""),
                "generated_at": _dt.now().isoformat(),
            })
            saga_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.warning("Failed to save saga to disk")

        words = result.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)
    except Exception as e:
        logger.exception("Generation failed")
        yield "Error: generation failed. Check server logs for details."


@router.post("/api/saga/manual")
async def api_saga_manual(request: Request):
    """Save a player-written saga entry."""
    import json as _json
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

    existing.append({
        "text": text,
        "year": metadata.get("year", 0),
        "season": metadata.get("season", "spring"),
        "is_manual": True,
    })
    saga_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}
