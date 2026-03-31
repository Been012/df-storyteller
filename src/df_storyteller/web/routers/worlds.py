"""World management and WebSocket event routes."""
from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    get_worlds as _get_worlds,
    get_active_world as _get_active_world,
    set_active_world as _set_active_world,
    safe_watch_dir as _safe_watch_dir,
    invalidate_cache as _invalidate_cache,
    add_event_subscriber,
    remove_event_subscriber,
)

router = APIRouter()


@router.get("/api/worlds")
async def api_list_worlds():
    config = _get_config()
    return {"worlds": _get_worlds(config), "active": _get_active_world(config)}


@router.post("/api/worlds/switch")
async def api_switch_world(request: Request):
    data = await request.json()
    world = data.get("world", "")
    config = _get_config()
    if world and _safe_watch_dir(config, world) is None:
        return {"ok": False, "error": "Invalid world name"}
    _set_active_world(world)
    _invalidate_cache()
    return {"ok": True, "active": world}


@router.get("/api/refresh")
async def api_refresh():
    """Force-clear the cache and redirect back."""
    _invalidate_cache()
    return RedirectResponse("/", status_code=303)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Live event feed via WebSocket. Polls for new JSON files in the event dir."""
    await websocket.accept()
    add_event_subscriber(websocket)
    try:
        config = _get_config()
        active_world = _get_active_world(config)
        watch_dir = _safe_watch_dir(config, active_world)

        # Send initial status
        if watch_dir and watch_dir.exists():
            await websocket.send_json({"type": "status", "description": f"Watching {active_world} for events..."})
        else:
            await websocket.send_json({"type": "status", "description": "No event directory found. Run storyteller-begin in DFHack."})

        seen_files: set[str] = set()
        if watch_dir and watch_dir.exists():
            seen_files = {f.name for f in watch_dir.glob("*.json")}

        while True:
            # Check for client disconnect by trying to receive with timeout
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except asyncio.TimeoutError:
                pass  # Normal — no message from client, just keep polling

            if not watch_dir or not watch_dir.exists():
                continue

            current_files = {f.name for f in watch_dir.glob("*.json")}
            new_files = current_files - seen_files
            seen_files = current_files

            for fname in sorted(new_files):
                if fname.startswith("snapshot_") or fname.startswith("delta_"):
                    continue
                fpath = watch_dir / fname
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        data = json.load(f)
                    from df_storyteller.ingestion.dfhack_json_parser import parse_dfhack_event
                    from df_storyteller.context.context_builder import _format_event
                    event = parse_dfhack_event(data)
                    desc = _format_event(event)
                    desc = re.sub(r"^\[.*?\]\s*", "", desc)
                    date_label = event.season.value.title()
                    if event.month_name and event.day:
                        date_label = f"{event.day} {event.month_name}"
                    # Use report sub-type for display
                    display_type = event.event_type.value
                    if display_type == "report":
                        raw = data.get("data", {})
                        display_type = raw.get("report_type", "report") if isinstance(raw, dict) else "report"
                    await websocket.send_json({
                        "type": display_type,
                        "year": event.game_year,
                        "season": event.season.value,
                        "date_label": date_label,
                        "description": desc,
                    })
                except Exception:
                    pass

    except (WebSocketDisconnect, Exception):
        remove_event_subscriber(websocket)
