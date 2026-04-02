"""Dwarf portrait generation and serving routes."""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

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


# Map Lua style names to DF graphics condition shaping names
# Note: DF tissue enum uses PONY_TAIL but graphics file checks PONY_TAILS
_STYLE_MAP = {
    "combed": "NEATLY_COMBED", "braided": "BRAIDED",
    "double_braids": "DOUBLE_BRAIDS", "pony_tail": "PONY_TAILS",
    "shaved": "", "thinning": "", "unkempt": "",
}


def _build_appearance_dict(dwarf) -> dict:
    """Build an appearance dict from a Dwarf model for portrait generation."""
    if dwarf.appearance.skin_color:
        hair_shaping = _STYLE_MAP.get(dwarf.appearance.hair_style, "")
        beard_shaping = _STYLE_MAP.get(dwarf.appearance.beard_style, "")
        return {
            "sex": dwarf.sex,
            "skin_color": dwarf.appearance.skin_color,
            "hair_color": dwarf.appearance.hair_color or "BROWN",
            "beard_color": dwarf.appearance.beard_color or (dwarf.appearance.hair_color or "BROWN"),
            "eyebrow_color": dwarf.appearance.eyebrow_color or dwarf.appearance.hair_color or "BROWN",
            "hair_length": dwarf.appearance.hair_length,
            "hair_shaping": hair_shaping,
            "hair_curly": dwarf.appearance.hair_curly,
            "beard_length": dwarf.appearance.beard_length if dwarf.sex == "male" else 0,
            "beard_shaping": beard_shaping,
            "head_broadness": dwarf.appearance.body_broadness,
            "eye_round_vs_narrow": dwarf.appearance.eye_round_vs_narrow,
            "eye_deep_set": dwarf.appearance.eye_deep_set,
            "eyebrow_density": dwarf.appearance.eyebrow_density,
            "nose_upturned": dwarf.appearance.nose_upturned,
            "nose_length": dwarf.appearance.nose_length,
            "nose_broadness": dwarf.appearance.nose_broadness,
            "is_vampire": dwarf.is_vampire,
            "age": dwarf.age,
            "equipment": [
                item for item in dwarf.equipment
                if isinstance(item, dict) and item.get("slot")
            ],
            "race": dwarf.race,
        }
    return _deterministic_appearance(dwarf.unit_id, dwarf.sex)


def _find_visitor(config, unit_id: int):
    """Find a visitor/trader unit in the latest snapshot data."""
    import json
    from pathlib import Path
    from df_storyteller.context.loader import _load_appearance

    base = Path(config.paths.event_dir) if config.paths.event_dir else None
    if not base or not base.exists():
        return None

    # Find the most recent snapshot
    snapshots = sorted(base.rglob("snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for snap_path in snapshots[:3]:
        try:
            data = json.loads(snap_path.read_text(encoding="utf-8", errors="replace"))
            for visitor in data.get("data", {}).get("visitors", []):
                if visitor.get("unit_id") == unit_id:
                    from df_storyteller.schema.entities import Dwarf
                    appearance = _load_appearance(visitor)
                    return Dwarf(
                        unit_id=unit_id,
                        name=visitor.get("name", ""),
                        race=visitor.get("race", "DWARF"),
                        sex=visitor.get("sex", "unknown"),
                        age=visitor.get("age", 0),
                        appearance=appearance,
                        equipment=visitor.get("equipment", []),
                        is_vampire=visitor.get("is_vampire", False),
                    )
        except (json.JSONDecodeError, OSError):
            continue
    return None


@router.get("/api/portraits/{unit_id}")
async def api_portrait(unit_id: int):
    """Generate or serve a cached portrait for any unit (citizen, visitor, trader)."""
    config = _get_config()

    df_install = config.paths.df_install
    if not df_install:
        return Response(status_code=404)

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    cache_dir = fortress_dir / "portraits"

    # Try fortress citizens first, then visitors/traders
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        dwarf = _find_visitor(config, unit_id)
    if not dwarf:
        return Response(status_code=404)

    # Check cache first
    portrait_path = cache_dir / f"portrait_{unit_id}.png"
    if portrait_path.exists():
        return FileResponse(portrait_path, media_type="image/png")

    appearance = _build_appearance_dict(dwarf)

    from df_storyteller.portraits.compositor import generate_portrait, PORTRAIT_RACES
    # Only generate condition-based portraits for supported races
    if appearance.get("race", "DWARF").upper() not in PORTRAIT_RACES:
        return Response(status_code=404)
    result = generate_portrait(df_install, unit_id, appearance, cache_dir)

    if result and result.exists():
        return FileResponse(result, media_type="image/png")

    return Response(status_code=404)


@router.get("/api/creature-sprite/{creature_id}")
async def api_creature_sprite(creature_id: str, caste: str = ""):
    """Serve a creature's portrait sprite from DF's sprite sheets."""
    config = _get_config()
    df_install = config.paths.df_install
    if not df_install:
        return Response(status_code=404)

    from df_storyteller.portraits.creature_sprites import get_creature_portrait
    img = get_creature_portrait(df_install, creature_id.upper(), caste.upper() if caste else "", scale=2)
    if not img:
        return Response(status_code=404)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/api/portraits/{unit_id}/debug")
async def api_portrait_debug(unit_id: int):
    """Debug: show appearance data and selected layers for a dwarf."""
    config = _get_config()
    df_install = config.paths.df_install
    if not df_install:
        return JSONResponse({"error": "no df_install"})

    _, character_tracker, _, metadata = _load_game_state_safe(config)
    dwarf = character_tracker.get_dwarf(unit_id)
    if not dwarf:
        return JSONResponse({"error": "dwarf not found"})

    _STYLE_MAP = {
        "combed": "NEATLY_COMBED", "braided": "BRAIDED",
        "double_braids": "DOUBLE_BRAIDS", "pony_tail": "PONY_TAILS",
        "shaved": "", "thinning": "", "unkempt": "",
    }

    if dwarf.appearance.skin_color:
        hair_shaping = _STYLE_MAP.get(dwarf.appearance.hair_style, "")
        beard_shaping = _STYLE_MAP.get(dwarf.appearance.beard_style, "")
        appearance = {
            "sex": dwarf.sex,
            "skin_color": dwarf.appearance.skin_color,
            "hair_color": dwarf.appearance.hair_color or "BROWN",
            "beard_color": dwarf.appearance.beard_color or (dwarf.appearance.hair_color or "BROWN"),
            "eyebrow_color": dwarf.appearance.eyebrow_color or dwarf.appearance.hair_color or "BROWN",
            "hair_length": dwarf.appearance.hair_length,
            "hair_shaping": hair_shaping,
            "hair_curly": dwarf.appearance.hair_curly,
            "beard_length": dwarf.appearance.beard_length if dwarf.sex == "male" else 0,
            "beard_shaping": beard_shaping,
            "head_broadness": dwarf.appearance.body_broadness,
            "eye_round_vs_narrow": dwarf.appearance.eye_round_vs_narrow,
            "eye_deep_set": dwarf.appearance.eye_deep_set,
            "eyebrow_density": dwarf.appearance.eyebrow_density,
            "nose_upturned": dwarf.appearance.nose_upturned,
            "nose_length": dwarf.appearance.nose_length,
            "nose_broadness": dwarf.appearance.nose_broadness,
            "is_vampire": dwarf.is_vampire,
            "age": dwarf.age,
            "equipment": [
                item for item in dwarf.equipment
                if isinstance(item, dict) and item.get("slot")
            ],
        }
    else:
        appearance = _deterministic_appearance(unit_id, dwarf.sex)

    from df_storyteller.portraits.compositor import _load_rules
    from df_storyteller.portraits.evaluator import DwarfAppearanceData, evaluate_layers, _matches

    app_data = DwarfAppearanceData(
        sex=appearance.get("sex", "male"),
        skin_color=appearance.get("skin_color", ""),
        hair_color=appearance.get("hair_color", ""),
        beard_color=appearance.get("beard_color", ""),
        eyebrow_color=appearance.get("eyebrow_color", ""),
        hair_length=appearance.get("hair_length", 0),
        hair_shaping=appearance.get("hair_shaping", ""),
        hair_curly=appearance.get("hair_curly", 0),
        beard_length=appearance.get("beard_length", 0),
        beard_shaping=appearance.get("beard_shaping", ""),
        head_broadness=appearance.get("head_broadness", 100),
        eye_round_vs_narrow=appearance.get("eye_round_vs_narrow", 100),
        eye_deep_set=appearance.get("eye_deep_set", 100),
        eyebrow_density=appearance.get("eyebrow_density", 100),
        nose_upturned=appearance.get("nose_upturned", 100),
        nose_length=appearance.get("nose_length", 100),
        nose_broadness=appearance.get("nose_broadness", 100),
        is_vampire=appearance.get("is_vampire", False),
        equipment=appearance.get("equipment", []),
        random_seed=unit_id,
        age=appearance.get("age", 0),
    )

    rules = _load_rules(df_install)

    # Replay evaluator logic to get matched rules with names
    matched_rules = []
    matched_groups: set[int] = set()
    for rule in rules:
        if rule.group_id in matched_groups:
            continue
        if _matches(rule, app_data):
            matched_groups.add(rule.group_id)
            matched_rules.append(rule)

    layer_info = []
    for rule in matched_rules:
        info: dict = {
            "name": rule.name,
            "tile_page": rule.tile_page,
            "tile_xy": [rule.tile_x, rule.tile_y],
            "group_id": rule.group_id,
        }
        if rule.caste:
            info["caste"] = rule.caste
        if rule.palette_name:
            info["palette"] = f"{rule.palette_name}:{rule.palette_index}"
        conditions = []
        for tc in rule.tissue_conditions:
            tc_info = f"{tc.body_part_category}:{tc.tissue_type}"
            if tc.may_have_colors:
                tc_info += f" colors={tc.may_have_colors}"
            if tc.min_length is not None:
                tc_info += f" min_len={tc.min_length}"
            if tc.max_length is not None:
                tc_info += f" max_len={tc.max_length}"
            if tc.not_shaped:
                tc_info += " NOT_SHAPED"
            if tc.may_have_shaping:
                tc_info += f" shaping={tc.may_have_shaping}"
            if tc.min_density is not None:
                tc_info += f" min_dens={tc.min_density}"
            if tc.max_density is not None:
                tc_info += f" max_dens={tc.max_density}"
            conditions.append(tc_info)
        for bp in rule.bp_conditions:
            bp_info = f"BP:{bp.body_part_category}"
            if bp.modifier_type:
                bp_info += f" {bp.modifier_type}={bp.modifier_min}-{bp.modifier_max}"
            conditions.append(bp_info)
        if rule.random_part_name:
            conditions.append(f"RANDOM:{rule.random_part_name}:{rule.random_part_index}/{rule.random_part_total}")
        if conditions:
            info["conditions"] = conditions
        layer_info.append(info)

    return JSONResponse({
        "dwarf": dwarf.name,
        "appearance_input": appearance,
        "selected_layers": layer_info,
    })
