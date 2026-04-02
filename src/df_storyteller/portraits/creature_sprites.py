"""Load creature portrait sprites from DF's sprite sheets.

Parses creature portrait graphics files to map creature IDs to tile
positions on portrait sprite sheets (96x96 tiles).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image

from df_storyteller.portraits.tile_loader import TILE_SIZE

logger = logging.getLogger(__name__)

# Tile page name → sprite sheet filename (portraits directory)
_CREATURE_TILE_PAGES: dict[str, str] = {
    "PORTRAIT_CREATURE_DOMESTIC": "creature_domestic_portrait.png",
    "PORTRAIT_CREATURE_SURFACE": "creature_surface_portrait.png",
    "PORTRAIT_CREATURE_SURFACE_SMALL": "creature_surface_small_portrait.png",
    "PORTRAIT_CREATURE_ANIMAL_PEOPLE": "animal_people_portrait.png",
    "PORTRAIT_CREATURE": "creature_portrait.png",
    "OGRES_PORTRAIT": "ogres_portrait.png",
}

# Graphics definition files to parse
_GRAPHICS_FILES = [
    "graphics_creatures_portraits_domestic.txt",
    "graphics_creatures_portraits_surface.txt",
    "graphics_creatures_portraits_surface_small.txt",
    "graphics_creatures_portraits.txt",
    "graphics_creatures_portraits_aquatic.txt",
    "graphics_creatures_portraits_animal_people.txt",
]

_GRAPHICS_REL = Path("data/vanilla/vanilla_creatures_graphics/graphics")
_PORTRAITS_REL = Path("data/vanilla/vanilla_creatures_graphics/graphics/images/portraits")

_TAG_RE = re.compile(r"\[([^\]]+)\]")


def _parse_tag(line: str) -> list[str] | None:
    m = _TAG_RE.search(line.strip())
    if m:
        return m.group(1).split(":")
    return None


@lru_cache(maxsize=1)
def _load_creature_map(df_install: str) -> dict[str, tuple[str, int, int]]:
    """Parse all creature portrait graphics files into a creature_id → (tile_page, x, y) map.

    Returns the DEFAULT adult portrait tile for each creature. Caste-specific
    graphics (e.g. male/female peacock) use 'CREATURE_ID:CASTE' as the key.
    """
    creature_map: dict[str, tuple[str, int, int]] = {}
    base = Path(df_install) / _GRAPHICS_REL

    for filename in _GRAPHICS_FILES:
        path = base / filename
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        current_creature = ""
        current_caste = ""
        in_portrait = False

        for line in text.split("\n"):
            tag = _parse_tag(line)
            if not tag:
                continue

            cmd = tag[0]

            if cmd == "CREATURE_GRAPHICS":
                current_creature = tag[1] if len(tag) > 1 else ""
                current_caste = ""
                in_portrait = False
                continue

            if cmd == "CREATURE_CASTE_GRAPHICS":
                current_creature = tag[1] if len(tag) > 1 else ""
                current_caste = tag[2] if len(tag) > 2 else ""
                in_portrait = False
                continue

            if cmd == "LAYER_SET":
                # [LAYER_SET:PORTRAIT] or [LAYER_SET:CHILD:PORTRAIT]
                age_group = tag[1] if len(tag) > 1 else ""
                in_portrait = age_group == "PORTRAIT"
                continue

            if cmd == "LAYER" and in_portrait and current_creature:
                # [LAYER:MAIN:PORTRAIT_CREATURE_DOMESTIC:0:0]
                tile_page = tag[2] if len(tag) > 2 else ""
                tile_x = int(tag[3]) if len(tag) > 3 else 0
                tile_y = int(tag[4]) if len(tag) > 4 else 0

                if tile_page in _CREATURE_TILE_PAGES:
                    key = f"{current_creature}:{current_caste}" if current_caste else current_creature
                    creature_map[key] = (tile_page, tile_x, tile_y)
                continue

    logger.info("Loaded %d creature portrait mappings", len(creature_map))
    return creature_map


def get_creature_portrait(
    df_install: str,
    creature_id: str,
    caste: str = "",
    scale: int = 2,
) -> Image.Image | None:
    """Get a creature's portrait sprite.

    Args:
        df_install: Path to DF install directory.
        creature_id: DF creature ID (e.g. "DOG", "CAT", "YAK").
        caste: Optional caste (e.g. "MALE", "FEMALE") for dimorphic species.
        scale: Upscale factor (1=96px, 2=192px).

    Returns:
        RGBA PIL Image, or None if no portrait found.
    """
    creature_map = _load_creature_map(df_install)

    # Try caste-specific first, then generic
    key = f"{creature_id}:{caste}" if caste else creature_id
    entry = creature_map.get(key)
    if not entry and caste:
        entry = creature_map.get(creature_id)
    if not entry:
        return None

    tile_page, tile_x, tile_y = entry
    filename = _CREATURE_TILE_PAGES.get(tile_page)
    if not filename:
        return None

    try:
        sheet_path = Path(df_install) / _PORTRAITS_REL / filename
        if not sheet_path.exists():
            return None
        sheet = Image.open(sheet_path).convert("RGBA")
        x0 = tile_x * TILE_SIZE
        y0 = tile_y * TILE_SIZE
        tile = sheet.crop((x0, y0, x0 + TILE_SIZE, y0 + TILE_SIZE))

        if scale > 1:
            tile = tile.resize(
                (TILE_SIZE * scale, TILE_SIZE * scale),
                Image.Resampling.NEAREST,
            )
        return tile
    except Exception:
        logger.exception("Failed to load creature portrait for %s", creature_id)
        return None


def list_available_creatures(df_install: str) -> list[str]:
    """List all creature IDs that have portrait sprites."""
    return sorted(_load_creature_map(df_install).keys())
