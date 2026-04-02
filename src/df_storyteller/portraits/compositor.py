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


@lru_cache(maxsize=8)
def _load_clothes_source_row(df_install: str, race: str = "DWARF") -> list[tuple[int, int, int, int]]:
    """Load the source palette row for clothing tiles.

    Clothing tiles are drawn using cols 9-17 of row 0 from the clothes palette.
    This is the neutral gray source that gets recolored to the item's color.
    """
    race_lower = race.lower()
    palette_path = (
        Path(df_install) / "data/vanilla/vanilla_creatures_graphics/graphics/images"
        / race_lower / f"{race_lower}_clothes_palettes.png"
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

# Tile page suffix → sprite sheet filename suffix mapping.
# The tile page names in DF graphics files use "PORTRAIT_{RACE}_{SUFFIX}".
# We strip the race prefix and map the suffix to a filename pattern.
_TILE_SUFFIX_TO_FILE: dict[str, str] = {
    "BODY": "portrait_body.png",
    "HAIR": "portrait_hair.png",
    "BABY": "portrait_baby.png",
    "CHILD_BODY": "portrait_child_body.png",
    "CHILD_HAIR": "portrait_child_hair.png",
    "CHILD_CLOTHING": "portrait_child_clothing.png",
    "CLOTHING_UNDER": "portrait_clothing_under.png",
    "CLOTHING_SHIRT": "portrait_clothing_shirt.png",
    "CLOTHING_VEST": "portrait_clothing_vest.png",
    "CLOTHING_COAT": "portrait_clothing_coat.png",
    "CLOTHING_TOGA": "portrait_clothing_toga.png",
    "CLOTHING_MAIL_SHIRT": "portrait_clothing_chainmail.png",
    "CLOTHING_LEATHER": "portrait_clothing_leather.png",
    "CLOTHING_BREASTPLATE": "portrait_clothing_breastplate.png",
    "CLOTHING_CLOAK": "portrait_clothing_cloak.png",
    "CLOTHING_CAPE": "portrait_clothing_cape.png",
    "CLOTHING_VEIL_HEAD": "portrait_clothing_headveil.png",
    "CLOTHING_HOOD": "portrait_clothing_hood.png",
    "CLOTHING_VEIL_FACE": "portrait_clothing_veil.png",
    "CLOTHING_HELM": "portrait_clothing_helmet.png",
    "CLOTHING_TURBAN": "portrait_clothing_turban.png",
    "CLOTHING_SCARF_HEAD": "portrait_clothing_headscarf.png",
    "CLOTHING_MASK": "portrait_clothing_mask.png",
    "CLOTHING_CAP": "portrait_clothing_cap.png",
    "SKELETON": "portrait_skeleton.png",
    "CLOTHING_CROWN": "portrait_clothing_crown.png",
}

# Supported races with portrait graphics
PORTRAIT_RACES = {"DWARF", "ELF", "HUMAN", "GOBLIN", "KOBOLD"}

# Portrait graphics file relative to DF install
_GRAPHICS_REL = Path("data/vanilla/vanilla_creatures_graphics/graphics")


def _tile_page_to_filename(tile_page: str, race: str) -> str | None:
    """Map a tile page name to its sprite sheet filename for a given race.

    E.g. "PORTRAIT_DWARF_BODY" with race "ELF" → "elf_portrait_body.png"
    """
    # Strip the "PORTRAIT_{RACE}_" prefix to get the suffix
    for r in PORTRAIT_RACES:
        prefix = f"PORTRAIT_{r}_"
        if tile_page.startswith(prefix):
            suffix = tile_page[len(prefix):]
            filename = _TILE_SUFFIX_TO_FILE.get(suffix)
            if filename:
                return f"{race.lower()}_{filename}"
            return None
    return None


def _detect_source_palette_row(
    df_install: str,
    race_lower: str,
    palette: list[list[tuple[int, int, int, int]]],
) -> list[tuple[int, int, int, int]]:
    """Detect which palette row a race's hair tiles are drawn with.

    Checks a sample tile's pixels against each palette row and returns
    the row with the most color matches.
    """
    try:
        sheet = load_sprite_sheet(df_install, f"{race_lower}_portrait_hair.png")
        tile = crop_tile(sheet, 0, 2)  # Sample: mid-length unstyled hair
        tile_colors = set()
        for y in range(tile.height):
            for x in range(tile.width):
                px = tile.getpixel((x, y))
                if px[3] > 0 and px != (19, 18, 18, 255):
                    tile_colors.add(px)

        best_row_idx = 0
        best_matches = 0
        for i, row in enumerate(palette):
            matches = sum(1 for c in tile_colors if c in row)
            if matches > best_matches:
                best_matches = matches
                best_row_idx = i
        return palette[best_row_idx]
    except (FileNotFoundError, IndexError):
        return palette[0]


@lru_cache(maxsize=8)
def _load_rules(df_install: str, race: str = "DWARF") -> list[LayerRule]:
    """Load and cache parsed portrait layer rules for a race."""
    filename = f"graphics_creatures_portrait_{race.lower()}.txt"
    path = Path(df_install) / _GRAPHICS_REL / filename
    return parse_portrait_graphics(path)


def compose_portrait(
    df_install: str,
    appearance: DwarfAppearanceData,
    scale: int = 2,
    race: str = "DWARF",
) -> Image.Image:
    """Compose a portrait using the full condition-based evaluator.

    Args:
        df_install: Path to the DF install directory.
        appearance: Dwarf appearance data for condition matching.
        scale: Upscale factor (1 = 96px, 2 = 192px).
        race: Creature race (DWARF, ELF, HUMAN, GOBLIN, KOBOLD).

    Returns:
        RGBA PIL Image of the composed portrait.
    """
    race = race.upper()
    canvas = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))

    all_rules = _load_rules(df_install, race)
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

    # Load race-specific palettes
    race_lower = race.lower()
    try:
        body_palette = load_palette(df_install, f"{race_lower}_portrait_body_palette.png")
    except FileNotFoundError as e:
        logger.warning("Portrait body palette not found for %s: %s", race, e)
        return canvas

    # Some races (goblins, kobolds) don't have hair palettes
    try:
        hair_palette = load_palette(df_install, f"{race_lower}_portrait_hair_palette.png")
    except FileNotFoundError:
        hair_palette = body_palette  # Fallback to body palette

    source_body_row = body_palette[0]
    # Hair tiles are drawn with a specific palette row that varies per race
    # (dwarf/elf use row 0, human uses last row). Auto-detect by finding which
    # palette row's colors appear in a sample hair tile.
    source_hair_row = _detect_source_palette_row(df_install, race_lower, hair_palette)

    # Load clothes source palette for item recoloring
    try:
        source_clothes_row = _load_clothes_source_row(df_install, race)
    except FileNotFoundError:
        source_clothes_row = []

    # Evaluate conditions to get matching layers
    layers = evaluate_layers(rules, appearance)

    for layer in layers:
        filename = _tile_page_to_filename(layer.tile_page, race)
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

        race = appearance.get("race", "DWARF")
        img = compose_portrait(df_install, app_data, scale=2, race=race)
        img.save(portrait_path, "PNG")
        hash_path.write_text(appearance_hash)
        return portrait_path
    except Exception:
        logger.exception("Failed to generate portrait for unit %d", unit_id)
        return None
