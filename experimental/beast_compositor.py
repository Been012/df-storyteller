"""Compose procedural beast portraits from DF's beast sprite sheets.

For procedurally generated creatures (demons, forgotten beasts) that don't
have pre-made portrait sprites, this module composites a portrait from the
overworld beast tiles (96x64) and upscales to portrait size (96x96).

Uses body part counts and features to select the correct beast body type
and attachment sprites, then applies per-layer color tinting.
"""
from __future__ import annotations

import logging
import re
from colorsys import hsv_to_rgb, rgb_to_hsv
from functools import lru_cache
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# Tile size for beast sprites (32x32 per cell, rectangles are 3x2 = 96x64)
_CELL = 32
_RECT_W = 3 * _CELL  # 96
_RECT_H = 2 * _CELL  # 64

_GRAPHICS_REL = Path("data/vanilla/vanilla_creatures_graphics/graphics")
_IMAGES_REL = _GRAPHICS_REL / "images"

# Sprite sheet files
_SHEETS = {
    "BEASTS": "beasts.png",
    "BEASTS_DECORATIONS": "beasts_decorations.png",
    "BEASTS_ORGANICS": "beasts_organics.png",
}


@lru_cache(maxsize=1)
def _parse_beast_tiles(df_install: str) -> dict[str, tuple[str, int, int]]:
    """Parse TILE_GRAPHICS_RECTANGLE entries from beast graphics files.

    Returns: {name: (sheet_file, pixel_x, pixel_y)}
    """
    tiles: dict[str, tuple[str, int, int]] = {}
    base = Path(df_install) / _GRAPHICS_REL

    for filename in ["graphics_beasts.txt", "graphics_beasts_small.txt"]:
        path = base / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r"\[TILE_GRAPHICS_RECTANGLE:(\w+):(\d+):(\d+):(\d+):(\d+):(\w+)\]", text
        ):
            sheet, tx, ty, tw, th, name = m.groups()
            sheet_file = _SHEETS.get(sheet)
            if sheet_file:
                tiles[name] = (sheet_file, int(tx) * _CELL, int(ty) * _CELL)

    logger.info("Parsed %d beast tile definitions", len(tiles))
    return tiles


def _crop_beast_rect(df_install: str, sheet_file: str, px: int, py: int) -> Image.Image:
    """Crop a 96x64 rectangle from a beast sprite sheet."""
    path = Path(df_install) / _IMAGES_REL / sheet_file
    sheet = Image.open(path).convert("RGBA")
    return sheet.crop((px, py, px + _RECT_W, py + _RECT_H))


# DF's classic 16-color palette → RGB
_DF_PALETTE: dict[int, tuple[int, int, int]] = {
    # Normal (bright=0)
    0: (0, 0, 0),         # BLACK
    1: (0, 0, 170),       # BLUE
    2: (0, 170, 0),       # GREEN
    3: (0, 170, 170),     # CYAN (light blue)
    4: (170, 0, 0),       # RED
    5: (170, 0, 170),     # MAGENTA
    6: (170, 85, 0),      # BROWN
    7: (170, 170, 170),   # LIGHT_GRAY
}
_DF_PALETTE_BRIGHT: dict[int, tuple[int, int, int]] = {
    # Bright (bright=1)
    0: (85, 85, 85),      # DARK_GRAY
    1: (85, 85, 255),     # LIGHT_BLUE
    2: (85, 255, 85),     # LIGHT_GREEN
    3: (85, 255, 255),    # LIGHT_CYAN
    4: (255, 85, 85),     # LIGHT_RED
    5: (255, 85, 255),    # LIGHT_MAGENTA
    6: (255, 255, 85),    # YELLOW
    7: (255, 255, 255),   # WHITE
}


def _df_color_to_rgb(fg: int, bright: int = 0) -> tuple[int, int, int]:
    """Convert a DF 16-color palette index to RGB."""
    if bright:
        return _DF_PALETTE_BRIGHT.get(fg, (170, 170, 170))
    return _DF_PALETTE.get(fg, (170, 170, 170))


def _tint_sprite_rgb(sprite: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    """Tint a beast sprite using an RGB color via HSV."""
    tr, tg, tb = rgb
    th, ts, _ = rgb_to_hsv(tr / 255, tg / 255, tb / 255)

    result = sprite.copy()
    pixels = result.load()
    for y in range(result.height):
        for x in range(result.width):
            pr, pg, pb, pa = pixels[x, y]
            if pa == 0:
                continue
            _, _, sv = rgb_to_hsv(pr / 255, pg / 255, pb / 255)
            r, g, b = hsv_to_rgb(th, ts * 0.8, sv)
            pixels[x, y] = (int(r * 255), int(g * 255), int(b * 255), pa)
    return result


def _tint_sprite(sprite: Image.Image, color_name: str) -> Image.Image:
    """Tint a beast sprite using a DF color name via HSV."""
    # Common DF color name → approximate RGB
    _COLORS: dict[str, tuple[int, int, int]] = {
        "BLACK": (30, 30, 30), "GRAY": (128, 128, 128), "WHITE": (240, 240, 240),
        "RED": (200, 50, 50), "CRIMSON": (180, 30, 30), "SCARLET": (220, 40, 40),
        "BROWN": (150, 75, 0), "TAN": (210, 180, 140), "CINNAMON": (210, 105, 30),
        "AMBER": (255, 191, 0), "GOLD": (255, 215, 0), "YELLOW": (255, 255, 0),
        "LIME": (0, 255, 0), "GREEN": (0, 180, 0), "DARK_GREEN": (0, 100, 0),
        "EMERALD": (80, 200, 120), "TEAL": (0, 128, 128), "CYAN": (0, 255, 255),
        "BLUE": (50, 50, 200), "DARK_BLUE": (0, 0, 139), "LIGHT_BLUE": (100, 149, 237),
        "PURPLE": (128, 0, 128), "VIOLET": (148, 0, 211), "MAGENTA": (255, 0, 255),
        "PINK": (255, 182, 193), "MAUVE": (224, 176, 255),
        "ORANGE": (255, 165, 0), "PEACH": (255, 218, 185),
        "TAUPE": (72, 60, 50), "CHARCOAL": (54, 69, 79),
        "RUST": (183, 65, 14), "COPPER": (184, 115, 51),
    }
    rgb = _COLORS.get(color_name.upper())
    if not rgb:
        return sprite  # Unknown color, return as-is

    tr, tg, tb = rgb
    th, ts, _ = rgb_to_hsv(tr / 255, tg / 255, tb / 255)

    result = sprite.copy()
    pixels = result.load()
    for y in range(result.height):
        for x in range(result.width):
            pr, pg, pb, pa = pixels[x, y]
            if pa == 0:
                continue
            _, _, sv = rgb_to_hsv(pr / 255, pg / 255, pb / 255)
            r, g, b = hsv_to_rgb(th, ts * 0.7, sv)
            pixels[x, y] = (int(r * 255), int(g * 255), int(b * 255), pa)
    return result


def _determine_body_type(beast_data: dict) -> str:
    """Determine the beast sprite body type from body part categories.

    Uses the full set of body part categories (not just leg/arm counts)
    for accurate mapping. Key discriminators:
    - ANTENNA → INSECT
    - MANDIBLE + STINGER → SCORPION
    - ARM_UPPER/ARM_LOWER → HUMANOID
    - Single BODY (not BODY_UPPER/BODY_LOWER) with few parts → AMORPHOUS/WORM
    - LEG_FRONT/LEG_REAR → natural QUADRUPED
    """
    categories = set(beast_data.get("categories", {}).keys()) if isinstance(beast_data.get("categories"), dict) else set()
    features = set(beast_data.get("features", []))
    legs = beast_data.get("legs", 0)
    arms = beast_data.get("arms", 0)
    wings = beast_data.get("wings", 0)
    total_parts = beast_data.get("total_parts", 0)

    # 1. ANTENNA → INSECT (unique identifier)
    if "ANTENNA" in categories or "ANTENNA" in features:
        return "INSECT"

    # 2. MANDIBLE + STINGER → SCORPION
    if ("MANDIBLE" in categories or "MANDIBLE" in features) and \
       ("STINGER" in categories or "STINGER" in features):
        return "SCORPION"

    # 3. Has arms → HUMANOID (or HUMANOID_ARMLESS variant)
    if "ARM_UPPER" in categories or "ARM_LOWER" in categories:
        return "HUMANOID"

    # 4. Single BODY (not split upper/lower) with few parts → AMORPHOUS or WORM
    has_split_body = "BODY_UPPER" in categories or "BODY_LOWER" in categories
    if not has_split_body:
        if total_parts <= 7:
            if wings > 0:
                return "WORM_LONG"  # Worm with wings (like Leech Monster)
            return "AMORPHOUS"
        if total_parts <= 12:
            return "WORM_SHORT"

    # 5. MANDIBLE without stinger → INSECT
    if "MANDIBLE" in categories or "MANDIBLE" in features:
        return "INSECT"

    # 6. 8+ legs → SPIDER
    if legs >= 8:
        return "SPIDER"

    # 7. 6 legs → INSECT
    if legs == 6:
        return "INSECT"

    # 8. 4 legs with STINGER → SCORPION
    if legs == 4 and ("STINGER" in categories or "STINGER" in features):
        return "SCORPION"

    # 9. 4 legs → QUADRUPED (bulky vs slinky based on body size)
    if legs >= 4:
        body_size = beast_data.get("body_size", 100000)
        if body_size < 50000:
            return "QUADRUPED_SLINKY"
        return "QUADRUPED_BULKY"

    # 10. 2 legs, no arms → BIPEDAL_DINOSAUR
    if legs == 2:
        return "BIPEDAL_DINOSAUR"

    # 11. No legs, has body → WORM or AMORPHOUS
    if "TAIL" in features or "TAIL" in categories:
        return "SNAKE"

    return "AMORPHOUS"


def _determine_eye_type(beast_data: dict) -> str:
    """Map eye count to eye sprite suffix."""
    eyes = beast_data.get("eyes", 2)
    if eyes <= 1:
        return "EYE_ONE"
    elif eyes == 2:
        return "EYE_TWO"
    return "EYE_THREE"


def compose_beast_portrait(
    df_install: str,
    beast_data: dict,
    scale: int = 2,
) -> Image.Image | None:
    """Compose a portrait for a procedurally generated beast.

    Args:
        df_install: Path to DF install.
        beast_data: Dict with legs, arms, wings, eyes, features, layer_colors.
        scale: Upscale factor.

    Returns:
        RGBA Image (96*scale x 96*scale) or None on failure.
    """
    tiles = _parse_beast_tiles(df_install)
    if not tiles:
        return None

    body_type = _determine_body_type(beast_data)
    eye_type = _determine_eye_type(beast_data)
    features = set(beast_data.get("features", []))
    colors = beast_data.get("layer_colors", [])
    wings = beast_data.get("wings", 0)

    # Determine wing type if present
    wing_type = ""
    if wings > 0:
        wing_type = "WINGS_BAT"  # Default; could be LACY or FEATHERED

    # Build layer list in compositing order (back → front)
    layer_names = []

    # 1. Shell (behind body)
    if "SHELL" in features:
        name = f"BEAST_{body_type}_SHELL_FRONT"
        if name in tiles:
            layer_names.append(name)

    # 2. Wings back
    if wing_type:
        name = f"BEAST_{body_type}_{wing_type}_BACK"
        if name in tiles:
            layer_names.append(name)

    # 3. Mandibles back
    if "MANDIBLE" in features:
        name = f"BEAST_{body_type}_MANDIBLES_BACK"
        if name in tiles:
            layer_names.append(name)

    # 4. Base body
    base_name = f"BEAST_{body_type}"
    if base_name in tiles:
        layer_names.append(base_name)

    # 5. Eyes
    eye_name = f"BEAST_{body_type}_{eye_type}"
    if eye_name in tiles:
        layer_names.append(eye_name)

    # 6. Mandibles front
    if "MANDIBLE" in features:
        name = f"BEAST_{body_type}_MANDIBLES_FRONT"
        if name in tiles:
            layer_names.append(name)

    # 7. Wings front
    if wing_type:
        name = f"BEAST_{body_type}_{wing_type}_FRONT"
        if name in tiles:
            layer_names.append(name)

    # 8. Horns
    if "HORN" in features:
        name = f"BEAST_{body_type}_HORN"
        if name in tiles:
            layer_names.append(name)

    # 9. Trunk
    if "TRUNK" in features:
        name = f"BEAST_{body_type}_TRUNK"
        if name in tiles:
            layer_names.append(name)

    # 10. Antennae
    if "ANTENNA" in features:
        name = f"BEAST_{body_type}_ANTENNAE"
        if name in tiles:
            layer_names.append(name)

    # 11. Tail
    if "TAIL" in features:
        # Try numbered tails
        for suffix in ["TAIL_ONE", "TAIL_TWO", "TAIL"]:
            name = f"BEAST_{body_type}_{suffix}"
            if name in tiles:
                layer_names.append(name)
                break

    if not layer_names:
        return None

    # Determine base body color from DF's 16-color palette
    base_fg = beast_data.get("base_color_fg", 7)
    base_bright = beast_data.get("base_color_bright", 0)
    base_rgb = _df_color_to_rgb(base_fg, base_bright)

    # Composite layers onto canvas (96x64 base, center vertically in 96x96)
    canvas = Image.new("RGBA", (_RECT_W, _RECT_W), (0, 0, 0, 0))  # 96x96
    y_offset = (_RECT_W - _RECT_H) // 2  # Center 64px in 96px vertically

    for i, layer_name in enumerate(layer_names):
        sheet_file, px, py = tiles[layer_name]
        try:
            sprite = _crop_beast_rect(df_install, sheet_file, px, py)

            # Apply base creature color to all layers
            sprite = _tint_sprite_rgb(sprite, base_rgb)

            canvas.paste(sprite, (0, y_offset), sprite)
        except Exception:
            logger.debug("Failed to load beast tile %s", layer_name)
            continue

    if scale > 1:
        canvas = canvas.resize(
            (_RECT_W * scale, _RECT_W * scale), Image.Resampling.NEAREST
        )

    return canvas
