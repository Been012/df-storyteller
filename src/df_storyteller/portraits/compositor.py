"""Compose dwarf portraits from DF sprite sheet layers.

Replicates DF Premium's layered portrait system: body + hair + beard composited
based on dwarf appearance data (sex, skin color, hair color/length/style).

Each portrait is 96x96 pixels, assembled from multiple transparent PNG layers.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from df_storyteller.portraits.tile_loader import (
    TILE_SIZE,
    crop_tile,
    load_palette,
    load_sprite_sheet,
    recolor_tile,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color name → palette index mappings (from graphics_creatures_portrait_dwarf.txt)
# ---------------------------------------------------------------------------

# Skin color → body palette row (0-3 for normal skin tones)
SKIN_COLOR_TO_PALETTE: dict[str, int] = {}
_SKIN_GROUPS = [
    (0, ["BURNT_UMBER", "DARK_BROWN"]),
    (1, ["BROWN", "CINNAMON", "COPPER", "DARK_TAN", "PALE_BROWN", "RAW_UMBER", "SEPIA"]),
    (2, ["DARK_PEACH", "ECRU", "PALE_CHESTNUT", "PEACH", "TAN", "TAUPE_SANDY"]),
    (3, ["PALE_PINK", "PINK", "TAUPE_PALE"]),
]
for idx, colors in _SKIN_GROUPS:
    for c in colors:
        SKIN_COLOR_TO_PALETTE[c] = idx

# Hair color → hair palette row
HAIR_COLOR_TO_PALETTE: dict[str, int] = {}
_HAIR_GROUPS = [
    (0, ["BLACK", "CHARCOAL"]),
    (1, ["AMBER", "AUBURN", "BURNT_SIENNA", "DARK_CHESTNUT", "LIGHT_BROWN", "OCHRE",
         "PALE_BROWN", "SEPIA", "TAUPE_DARK", "TAUPE_GRAY", "TAUPE_MEDIUM"]),
    (2, ["BROWN", "BURNT_UMBER", "CHOCOLATE", "DARK_BROWN"]),
    (3, ["CHESTNUT", "CINNAMON", "COPPER", "MAHOGANY", "PUMPKIN", "RAW_UMBER", "RUSSET"]),
    (5, ["GRAY"]),
    (9, ["BUFF", "DARK_TAN", "ECRU", "FLAX", "GOLD", "GOLDEN_YELLOW", "GOLDENROD",
         "PALE_CHESTNUT", "SAFFRON", "TAN", "TAUPE_PALE", "TAUPE_SANDY"]),
    (11, ["WHITE"]),
]
for idx, colors in _HAIR_GROUPS:
    for c in colors:
        if c not in HAIR_COLOR_TO_PALETTE:
            HAIR_COLOR_TO_PALETTE[c] = idx

# ---------------------------------------------------------------------------
# Body tile layout (from graphics_creatures_portrait_dwarf.txt analysis)
#
# Body sheet (16x12 tiles, 96px each):
#   Col 0: Torso        (M row 0, F row 6)
#   Col 1: Left arm     (M row 0, F row 6)
#   Col 2: Right arm    (M row 0, F row 6)
#   Col 3: Head THICK   (M row 0, F row 6)  — broadness >= 100
#          Head THIN    (M row 3, F row 9)  — broadness 0-99
#   Col 4: Ears THICK   (M row 0, F row 6)
#          Ears THIN    (M row 3, F row 9)
#   Col 5: Mouth        (M rows 0-5, F rows 6-11) — 6 random variants
#   Col 6: Eyes         (M row 0, F row 6)
#   Col 7: Eyebrows     (M rows 0-5, F rows 6-11) — variants
#   Col 14: Nose        (M rows 0-2, F rows 6-8) — 3 random variants
# ---------------------------------------------------------------------------

# Hair sheet (6x16 tiles):
#   Col 0-1: Straight hair (col 0 = variant 1, col 1 = variant 2)
#   Col 2-3: Curly hair variants
#   Col 4:   Beard
#   Col 5:   Eyebrow detail
#
#   Rows by style:
#     0: Stubble           4: Short combed      8: Mid braided      12: Long double braids
#     1: Short unkempt     5: Mid combed        9: Long braided     13: Short pony tail
#     2: Mid unkempt       6: Long combed      10: Short dbl braids 14: Mid pony tail
#     3: Long unkempt      7: Short braided    11: Mid dbl braids   15: Long pony tail

# Hair length tiers
_LENGTH_TIERS = [(50, 0), (100, 1), (200, 2), (999999, 3)]  # (threshold, offset)

# Style name → row offset in hair sheet
# Each style has 4 lengths: short/mid/long mapped to rows
_HAIR_STYLE_ROWS = {
    "unkempt":       [0, 1, 2, 3],    # stubble, short, mid, long unkempt
    "combed":        [0, 4, 5, 6],     # stubble, short, mid, long combed
    "braided":       [0, 7, 8, 9],     # stubble, short, mid, long braided
    "double_braids": [0, 10, 11, 12],  # stubble, short, mid, long double braids
    "pony_tail":     [0, 13, 14, 15],  # stubble, short, mid, long pony tail
    "shaved":        [0, 0, 0, 0],     # always stubble/bald
    "thinning":      [0, 0, 1, 1],     # age-thinned
    "shaped":        [0, 4, 5, 6],     # generic shaped = combed
    "clean_shaven":  [0, 0, 0, 0],     # clean-shaven = bald
}


def _length_tier(length: int) -> int:
    """Map hair/beard length to tier index (0=stubble, 1=short, 2=mid, 3=long)."""
    for threshold, tier in _LENGTH_TIERS:
        if length < threshold:
            return tier
    return 3


def _hair_row(length: int, style: str) -> int:
    """Get the hair sheet row for a given length and style."""
    tier = _length_tier(length)
    rows = _HAIR_STYLE_ROWS.get(style, _HAIR_STYLE_ROWS["unkempt"])
    return rows[tier]


def compose_portrait(
    df_install: str,
    sex: str = "male",
    skin_color: str = "PEACH",
    hair_color: str = "BROWN",
    beard_color: str = "",
    hair_length: int = 100,
    hair_style: str = "unkempt",
    beard_length: int = 100,
    beard_style: str = "unkempt",
    head_broadness: int = 100,
    mouth_variant: int = 0,
    nose_variant: int = 0,
    brow_variant: int = 0,
    age: float = 0,
    scale: int = 1,
) -> Image.Image:
    """Compose a dwarf portrait from sprite sheet layers.

    Args:
        df_install: Path to the DF install directory.
        sex: "male" or "female".
        skin_color: DF color name for skin.
        hair_color: DF color name for hair.
        beard_color: DF color name for beard (defaults to hair_color).
        hair_length: Hair length in DF tissue units.
        hair_style: "unkempt", "combed", "braided", "double_braids", "pony_tail".
        beard_length: Beard length (males only).
        beard_style: Same options as hair_style.
        head_broadness: 0-200 scale, <100 = thin face, >=100 = broad face.
        mouth_variant: 0-5, random mouth shape.
        nose_variant: 0-2, random nose shape.
        brow_variant: 0-5, eyebrow variant.
        age: Dwarf age in years.
        scale: Upscale factor (1 = 96px, 2 = 192px, etc.).

    Returns:
        RGBA PIL Image of the composed portrait.
    """
    canvas = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))

    try:
        body_sheet = load_sprite_sheet(df_install, "dwarf_portrait_body.png")
        hair_sheet = load_sprite_sheet(df_install, "dwarf_portrait_hair.png")
        body_palette = load_palette(df_install, "dwarf_portrait_body_palette.png")
        hair_palette = load_palette(df_install, "dwarf_portrait_hair_palette.png")
    except FileNotFoundError as e:
        logger.warning("Portrait sprites not found: %s", e)
        return canvas

    is_female = sex == "female"
    skin_idx = SKIN_COLOR_TO_PALETTE.get(skin_color, 2)
    hair_idx = HAIR_COLOR_TO_PALETTE.get(hair_color, 2)
    beard_palette_idx = HAIR_COLOR_TO_PALETTE.get(beard_color or hair_color, hair_idx)

    source_body_row = body_palette[0]
    target_body_row = body_palette[skin_idx]
    source_hair_row = hair_palette[0]
    target_hair_row = hair_palette[hair_idx]
    target_beard_row = hair_palette[beard_palette_idx]

    # Row offsets for male vs female
    base_row = 6 if is_female else 0
    # Thin vs thick head: thin = base+3, thick = base+0
    head_row = base_row + (3 if head_broadness < 100 else 0)

    def _body_layer(tx: int, ty: int) -> None:
        """Composite a body tile with skin palette recoloring."""
        tile = crop_tile(body_sheet, tx, ty)
        tile = recolor_tile(tile, source_body_row, target_body_row)
        nonlocal canvas
        canvas = Image.alpha_composite(canvas, tile)

    # --- Layer 1: Torso ---
    _body_layer(0, base_row)

    # --- Layer 2: Left arm ---
    _body_layer(1, base_row)

    # --- Layer 3: Right arm ---
    _body_layer(2, base_row)

    # --- Layer 4: Head (thick or thin based on broadness) ---
    _body_layer(3, head_row)

    # --- Layer 5: Ears (matches head shape) ---
    _body_layer(4, head_row)

    # --- Layer 6: Mouth (variant 0-5) ---
    mouth_row = base_row + (mouth_variant % 6)
    _body_layer(5, mouth_row)

    # --- Layer 7: Eyes ---
    _body_layer(6, base_row)

    # --- Layer 8: Eyebrows ---
    brow_row = base_row + (brow_variant % 6)
    _body_layer(7, brow_row)

    # --- Layer 9: Nose (variant 0-2) ---
    nose_row = base_row + (nose_variant % 3)
    # Nose tiles are at column 14 for rows that have content
    _body_layer(14, nose_row)

    # --- Layer 10: Beard (males only, before hair so hair overlaps) ---
    if not is_female and beard_length > 10:
        beard_row = _hair_row(beard_length, beard_style)
        beard_tile = crop_tile(hair_sheet, 4, beard_row)
        beard_tile = recolor_tile(beard_tile, source_hair_row, target_beard_row)
        canvas = Image.alpha_composite(canvas, beard_tile)

    # --- Layer 11: Head hair (skip if bald/shaved) ---
    if hair_length > 10:
        # Use column 0 for straight, 2 for curly (we don't have curl data mapped yet)
        hair_col = 0
        hair_row = _hair_row(hair_length, hair_style)
        hair_tile = crop_tile(hair_sheet, hair_col, hair_row)
        hair_tile = recolor_tile(hair_tile, source_hair_row, target_hair_row)
        canvas = Image.alpha_composite(canvas, hair_tile)

    # --- Scale up with pixel-art nearest-neighbor ---
    if scale > 1:
        new_size = (TILE_SIZE * scale, TILE_SIZE * scale)
        canvas = canvas.resize(new_size, Image.Resampling.NEAREST)

    return canvas


def generate_portrait(
    df_install: str,
    unit_id: int,
    appearance: dict,
    cache_dir: Path | None = None,
) -> Path | None:
    """Generate and cache a portrait PNG for a dwarf.

    Args:
        df_install: Path to DF install directory.
        unit_id: Dwarf unit ID.
        appearance: Dict with appearance keys.
        cache_dir: Directory to cache generated portraits.

    Returns:
        Path to the generated PNG, or None on failure.
    """
    if not cache_dir:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = cache_dir / f"portrait_{unit_id}.png"

    if portrait_path.exists():
        return portrait_path

    try:
        # Deterministic variants from unit_id for mouth/nose/brow
        import hashlib
        h = int(hashlib.md5(str(unit_id).encode()).hexdigest(), 16)

        img = compose_portrait(
            df_install=df_install,
            sex=appearance.get("sex", "male"),
            skin_color=appearance.get("skin_color", "PEACH"),
            hair_color=appearance.get("hair_color", "BROWN"),
            beard_color=appearance.get("beard_color", ""),
            hair_length=appearance.get("hair_length", 100),
            hair_style=appearance.get("hair_style", "unkempt"),
            beard_length=appearance.get("beard_length", 100 if appearance.get("sex") == "male" else 0),
            beard_style=appearance.get("beard_style", "unkempt"),
            head_broadness=appearance.get("head_broadness", 100),
            mouth_variant=h % 6,
            nose_variant=(h >> 4) % 3,
            brow_variant=(h >> 8) % 6,
            age=appearance.get("age", 0),
            scale=2,
        )
        img.save(portrait_path, "PNG")
        return portrait_path
    except Exception:
        logger.exception("Failed to generate portrait for unit %d", unit_id)
        return None
