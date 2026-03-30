"""Quest routes."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/quests", response_class=HTMLResponse)
async def quests_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "quests", metadata)
    fortress_dir = _get_fortress_dir(config, metadata)

    from df_storyteller.context.quest_store import load_all_quests
    from df_storyteller.schema.quests import QuestStatus
    quests = load_all_quests(config, fortress_dir)

    active = [q for q in quests if q.status == QuestStatus.ACTIVE]
    completed = [q for q in quests if q.status == QuestStatus.COMPLETED]

    # Sort: priority first, then newest first
    active.sort(key=lambda q: (not q.priority, -q.created_at.timestamp()))
    completed.sort(key=lambda q: -q.created_at.timestamp())

    return templates.TemplateResponse(request=request, name="quests.html", context={
        **ctx, "active_quests": active, "completed_quests": completed,
    })


@router.post("/api/quests/generate")
async def api_generate_quests(request: Request):
    """Generate new AI quests based on fortress state."""
    config = _get_config()
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    count = min(int(data.get("count", 3)), 10)
    category = data.get("category", "")
    difficulty = data.get("difficulty", "")

    from df_storyteller.stories.quest_generator import generate_quests
    fortress_dir = _get_fortress_dir(config)
    quests = await generate_quests(config, count=count, category=category, difficulty=difficulty, output_dir=fortress_dir)
    return [q.model_dump(mode="json") for q in quests]


@router.post("/api/quests/{quest_id}/complete")
async def api_complete_quest(quest_id: str):
    """Stream a completion narrative for a quest."""
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)

    async def _stream() -> AsyncGenerator[str, None]:
        from df_storyteller.stories.quest_generator import generate_completion_narrative
        from df_storyteller.context.quest_store import load_all_quests, save_all_quests
        from df_storyteller.schema.quests import QuestStatus

        quests = load_all_quests(config, fortress_dir)
        quest = next((q for q in quests if q.id == quest_id), None)
        if not quest:
            yield "Quest not found."
            return

        try:
            narrative = await generate_completion_narrative(config, quest, fortress_dir)
        except Exception as e:
            logger.exception("Quest completion narrative failed")
            yield f"Error: {e}" if str(e) else "Error: generation failed. Check Settings and try again."
            return

        # Save completion
        from datetime import datetime
        quest.status = QuestStatus.COMPLETED
        quest.completed_at = datetime.now()
        quest.completion_narrative = narrative
        save_all_quests(config, quests, fortress_dir)

        # Stream word by word
        words = narrative.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.02)

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/api/quests/{quest_id}/abandon")
async def api_abandon_quest(quest_id: str):
    from df_storyteller.context.quest_store import abandon_quest
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = abandon_quest(config, quest_id, fortress_dir)
    return {"ok": ok}


@router.post("/api/quests/{quest_id}/priority")
async def api_toggle_quest_priority(quest_id: str):
    from df_storyteller.context.quest_store import toggle_priority
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = toggle_priority(config, quest_id, fortress_dir)
    return {"ok": ok}


@router.delete("/api/quests/{quest_id}")
async def api_delete_quest(quest_id: str):
    from df_storyteller.context.quest_store import delete_quest
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    ok = delete_quest(config, quest_id, fortress_dir)
    return {"ok": ok}


@router.get("/api/quests")
async def api_list_quests(status: str | None = None):
    from df_storyteller.context.quest_store import load_all_quests
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    quests = load_all_quests(config, fortress_dir)
    if status:
        quests = [q for q in quests if q.status.value == status]
    return [q.model_dump(mode="json") for q in quests]


@router.post("/api/quests/manual")
async def api_create_manual_quest(request: Request):
    """Create a player-written quest."""
    from df_storyteller.context.quest_store import add_quest
    from df_storyteller.schema.quests import Quest, QuestCategory, QuestDifficulty
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    if not title or not description:
        return JSONResponse({"error": "Title and description are required"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    try:
        category = QuestCategory(data.get("category", "exploration"))
        difficulty = QuestDifficulty(data.get("difficulty", "medium"))
    except ValueError:
        category = QuestCategory.EXPLORATION
        difficulty = QuestDifficulty.MEDIUM

    quest = Quest(
        title=title,
        description=description,
        category=category,
        difficulty=difficulty,
        game_year=metadata.get("year", 0),
        game_season=metadata.get("season", "spring"),
        context_snapshot="Player-created quest",
    )
    add_quest(config, quest, fortress_dir)
    return quest.model_dump(mode="json")


@router.post("/api/quests/{quest_id}/edit")
async def api_edit_quest(quest_id: str, request: Request):
    """Edit a quest's title and description."""
    from df_storyteller.context.quest_store import load_all_quests, save_all_quests
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    if not title or not description:
        return JSONResponse({"error": "Title and description are required"}, status_code=400)

    fortress_dir = _get_fortress_dir(config)
    quests = load_all_quests(config, fortress_dir)
    for q in quests:
        if q.id == quest_id:
            q.title = title
            q.description = description
            save_all_quests(config, quests, fortress_dir)
            return {"ok": True}
    return JSONResponse({"error": "Quest not found"}, status_code=404)


@router.post("/api/quests/{quest_id}/resolve")
async def api_resolve_quest(quest_id: str, request: Request):
    """Resolve a quest with a player-written comment (no AI)."""
    from df_storyteller.context.quest_store import complete_quest
    config = _get_config()
    comment = ""
    try:
        data = await request.json()
        comment = data.get("comment", "").strip()
    except Exception:
        pass

    fortress_dir = _get_fortress_dir(config)
    ok = complete_quest(config, quest_id, comment or "Quest resolved by player.", fortress_dir)
    return {"ok": ok}
