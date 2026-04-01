"""Dwarf portrait generation and serving routes."""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Appearance options for deterministic fallback generation
_SKIN_OPTIONS = ["DARK_BROWN", "BROWN", "COPPER", "PEACH", "TAN", "PALE_PINK"]
_HAIR_OPTIONS = ["BLACK", "DARK_BROWN", "BROWN", "AUBURN", "GOLD", "GRAY"]
_HAIR_LENGTHS = [60, 100, 150, 200, 250]
_BEARD_LENGTHS = [0, 50, 100, 150, 200]


def _deterministic_appearance(unit_id: int, sex: str) -> dict:
    """Generate a deterministic pseudo-random appearance from unit_id.

    Used as fallback when real appearance data isn't captured yet.
    Same unit_id always produces the same appearance.
    """
    h = int(hashlib.md5(str(unit_id).encode()).hexdigest(), 16)
    return {
        "sex": sex,
        "skin_color": _SKIN_OPTIONS[h % len(_SKIN_OPTIONS)],
        "hair_color": _HAIR_OPTIONS[(h >> 4) % len(_HAIR_OPTIONS)],
        "hair_length": _HAIR_LENGTHS[(h >> 8) % len(_HAIR_LENGTHS)],
        "beard_length": _BEARD_LENGTHS[(h >> 12) % len(_BEARD_LENGTHS)] if sex == "male" else 0,
    }


@router.get("/api/portraits/{unit_id}")
async def api_portrait(unit_id: int):
    """Generate or serve a cached dwarf portrait."""
    config = _get_config()

    df_install = config.paths.df_install
    if not df_install:
        return Response(status_code=404)

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    cache_dir = fortress_dir / "portraits"

    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return Response(status_code=404)

    # Check cache first
    portrait_path = cache_dir / f"portrait_{unit_id}.png"
    if portrait_path.exists():
        return FileResponse(portrait_path, media_type="image/png")

    # Build appearance dict — use real data if available, else deterministic fallback
    if dwarf.appearance.skin_color:
        appearance = {
            "sex": dwarf.sex,
            "skin_color": dwarf.appearance.skin_color,
            "hair_color": dwarf.appearance.hair_color or "BROWN",
            "beard_color": dwarf.appearance.beard_color if dwarf.age >= 50 else (dwarf.appearance.hair_color or "BROWN"),
            "hair_length": dwarf.appearance.hair_length or 100,
            "hair_style": dwarf.appearance.hair_style or "unkempt",
            "beard_length": dwarf.appearance.beard_length if dwarf.sex == "male" else 0,
            "beard_style": dwarf.appearance.beard_style or "unkempt",
            "head_broadness": dwarf.appearance.body_broadness,
            "age": dwarf.age,
        }
    else:
        appearance = _deterministic_appearance(unit_id, dwarf.sex)

    from df_storyteller.portraits.compositor import generate_portrait
    result = generate_portrait(df_install, unit_id, appearance, cache_dir)

    if result and result.exists():
        return FileResponse(result, media_type="image/png")

    return Response(status_code=404)
