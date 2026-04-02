"""Compose dwarf portraits from DF sprite sheet layers.

Uses the parsed portrait graphics definitions and condition evaluator to
select the correct sprite tiles for each dwarf, then composites them
with palette recoloring using Pillow.
"""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image

from df_storyteller.portraits.evaluator import DwarfAppearanceData, SelectedLayer, evaluate_layers
from df_storyteller.portraits.graphics_parser import LayerRule, parse_portrait_graphics
from df_storyteller.portraits.tile_loader import (
    TILE_SIZE,
    crop_tile,
    load_palette,
    load_sprite_sheet,
    recolor_tile,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_clothes_source_row(df_install: str) -> list[tuple[int, int, int, int]]:
    """Load the source palette row for clothing tiles.

    Clothing tiles are drawn using cols 9-17 of row 0 from the clothes palette.
    This is the neutral gray source that gets recolored to the item's color.
    """
    palette_path = (
        Path(df_install) / "data/vanilla/vanilla_creatures_graphics/graphics/images"
        / "dwarf" / "dwarf_clothes_palettes.png"
    )
    img = Image.open(palette_path).convert("RGB")
    return [(*img.getpixel((x, 0))[:3], 255) for x in range(9, min(18, img.width))]


def _generate_clothes_target_row(
    source_row: list[tuple[int, int, int, int]],
    target_color: tuple[int, int, int],
) -> list[tuple[int, int, int, int]]:
    """Generate a target palette row by tinting the source row with the item color.

    Uses HSV: applies the target color's hue with scaled-down saturation to the
    source row's brightness structure. This produces naturally muted portrait
    tones matching DF's subdued clothing aesthetic.
    """
    from colorsys import rgb_to_hsv, hsv_to_rgb

    tr, tg, tb = target_color
    th, ts, _ = rgb_to_hsv(tr / 255, tg / 255, tb / 255)
    # Scale saturation down for the muted portrait look
    target_sat = ts * 0.4

    result = []
    for sr, sg, sb, sa in source_row:
        _, _, sv = rgb_to_hsv(sr / 255, sg / 255, sb / 255)
        r, g, b = hsv_to_rgb(th, target_sat, sv)
        result.append((int(r * 255), int(g * 255), int(b * 255), sa))
    return result

# Tile page name → sprite sheet filename
TILE_PAGE_FILES: dict[str, str] = {
    "PORTRAIT_DWARF_BODY": "dwarf_portrait_body.png",
    "PORTRAIT_DWARF_HAIR": "dwarf_portrait_hair.png",
    "PORTRAIT_DWARF_BABY": "dwarf_portrait_baby.png",
    "PORTRAIT_DWARF_CHILD_BODY": "dwarf_portrait_child_body.png",
    "PORTRAIT_DWARF_CHILD_HAIR": "dwarf_portrait_child_hair.png",
    "PORTRAIT_DWARF_CHILD_CLOTHING": "dwarf_portrait_child_clothing.png",
    "PORTRAIT_DWARF_CLOTHING_UNDER": "dwarf_portrait_clothing_under.png",
    "PORTRAIT_DWARF_CLOTHING_SHIRT": "dwarf_portrait_clothing_shirt.png",
    "PORTRAIT_DWARF_CLOTHING_VEST": "dwarf_portrait_clothing_vest.png",
    "PORTRAIT_DWARF_CLOTHING_COAT": "dwarf_portrait_clothing_coat.png",
    "PORTRAIT_DWARF_CLOTHING_TOGA": "dwarf_portrait_clothing_toga.png",
    "PORTRAIT_DWARF_CLOTHING_MAIL_SHIRT": "dwarf_portrait_clothing_chainmail.png",
    "PORTRAIT_DWARF_CLOTHING_LEATHER": "dwarf_portrait_clothing_leather.png",
    "PORTRAIT_DWARF_CLOTHING_BREASTPLATE": "dwarf_portrait_clothing_breastplate.png",
    "PORTRAIT_DWARF_CLOTHING_CLOAK": "dwarf_portrait_clothing_cloak.png",
    "PORTRAIT_DWARF_CLOTHING_CAPE": "dwarf_portrait_clothing_cape.png",
    "PORTRAIT_DWARF_CLOTHING_VEIL_HEAD": "dwarf_portrait_clothing_headveil.png",
    "PORTRAIT_DWARF_CLOTHING_HOOD": "dwarf_portrait_clothing_hood.png",
    "PORTRAIT_DWARF_CLOTHING_VEIL_FACE": "dwarf_portrait_clothing_veil.png",
    "PORTRAIT_DWARF_CLOTHING_HELM": "dwarf_portrait_clothing_helmet.png",
    "PORTRAIT_DWARF_CLOTHING_TURBAN": "dwarf_portrait_clothing_turban.png",
    "PORTRAIT_DWARF_CLOTHING_SCARF_HEAD": "dwarf_portrait_clothing_headscarf.png",
    "PORTRAIT_DWARF_CLOTHING_MASK": "dwarf_portrait_clothing_mask.png",
    "PORTRAIT_DWARF_CLOTHING_CAP": "dwarf_portrait_clothing_cap.png",
}

# Portrait graphics file relative to DF install
_GRAPHICS_REL = Path("data/vanilla/vanilla_creatures_graphics/graphics")
_GRAPHICS_FILE = "graphics_creatures_portrait_dwarf.txt"


@lru_cache(maxsize=1)
def _load_rules(df_install: str) -> list[LayerRule]:
    """Load and cache parsed portrait layer rules."""
    path = Path(df_install) / _GRAPHICS_REL / _GRAPHICS_FILE
    return parse_portrait_graphics(path)


def compose_portrait(
    df_install: str,
    appearance: DwarfAppearanceData,
    scale: int = 2,
) -> Image.Image:
    """Compose a dwarf portrait using the full condition-based evaluator.

    Args:
        df_install: Path to the DF install directory.
        appearance: Dwarf appearance data for condition matching.
        scale: Upscale factor (1 = 96px, 2 = 192px).

    Returns:
        RGBA PIL Image of the composed portrait.
    """
    canvas = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))

    all_rules = _load_rules(df_install)
    if not all_rules:
        return canvas

    # Select the correct layer set based on age
    # DF: babies (0-1), children (1-12), adults (12+)
    if appearance.age < 1:
        target_set = "BABY"
    elif appearance.age < 12:
        target_set = "CHILD"
    else:
        target_set = "PORTRAIT"
    rules = [r for r in all_rules if r.layer_set == target_set]

    try:
        body_palette = load_palette(df_install, "dwarf_portrait_body_palette.png")
        hair_palette = load_palette(df_install, "dwarf_portrait_hair_palette.png")
    except FileNotFoundError as e:
        logger.warning("Portrait palettes not found: %s", e)
        return canvas

    source_body_row = body_palette[0]
    source_hair_row = hair_palette[0]

    # Load clothes source palette for item recoloring
    try:
        source_clothes_row = _load_clothes_source_row(df_install)
    except FileNotFoundError:
        source_clothes_row = []

    # Evaluate conditions to get matching layers
    layers = evaluate_layers(rules, appearance)

    for layer in layers:
        filename = TILE_PAGE_FILES.get(layer.tile_page)
        if not filename:
            continue

        try:
            sheet = load_sprite_sheet(df_install, filename)
            tile = crop_tile(sheet, layer.tile_x, layer.tile_y)

            # Apply palette recoloring
            if layer.use_item_palette and layer.item_color and source_clothes_row:
                # Generate a tinted palette row from the item's material/dye color
                target_row = _generate_clothes_target_row(source_clothes_row, layer.item_color)
                tile = recolor_tile(tile, source_clothes_row, target_row)
            elif layer.palette_name == "BODY" and layer.palette_index < len(body_palette):
                tile = recolor_tile(tile, source_body_row, body_palette[layer.palette_index])
            elif layer.palette_name == "HAIR" and layer.palette_index < len(hair_palette):
                tile = recolor_tile(tile, source_hair_row, hair_palette[layer.palette_index])

            canvas = Image.alpha_composite(canvas, tile)
        except Exception:
            pass  # Skip tiles that fail to load (missing sprite sheets etc.)

    if scale > 1:
        canvas = canvas.resize((TILE_SIZE * scale, TILE_SIZE * scale), Image.Resampling.NEAREST)

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
        appearance: Dict with appearance keys (converted to DwarfAppearanceData).
        cache_dir: Directory to cache generated portraits.

    Returns:
        Path to the generated PNG, or None on failure.
    """
    if not cache_dir:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Hash appearance data so portraits regenerate when appearance changes
    appearance_hash = hashlib.md5(str(sorted(appearance.items())).encode()).hexdigest()[:8]
    portrait_path = cache_dir / f"portrait_{unit_id}.png"
    hash_path = cache_dir / f"portrait_{unit_id}.hash"

    if portrait_path.exists() and hash_path.exists():
        try:
            if hash_path.read_text().strip() == appearance_hash:
                return portrait_path
        except OSError:
            pass

    try:
        app_data = DwarfAppearanceData(
            sex=appearance.get("sex", "male"),
            skin_color=appearance.get("skin_color", "PEACH"),
            hair_color=appearance.get("hair_color", "BROWN"),
            beard_color=appearance.get("beard_color", ""),
            eyebrow_color=appearance.get("eyebrow_color", appearance.get("hair_color", "BROWN")),
            hair_length=appearance.get("hair_length", 100),
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

        img = compose_portrait(df_install, app_data, scale=2)
        img.save(portrait_path, "PNG")
        hash_path.write_text(appearance_hash)
        return portrait_path
    except Exception:
        logger.exception("Failed to generate portrait for unit %d", unit_id)
        return None
