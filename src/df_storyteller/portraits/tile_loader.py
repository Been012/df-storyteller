"""Load portrait sprite sheets and palettes from the DF install directory."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# All portrait tiles are 96x96
TILE_SIZE = 96

# Relative path within DF install to portrait images
_PORTRAIT_REL = Path("data/vanilla/vanilla_creatures_graphics/graphics/images/portraits")


def _portraits_dir(df_install: str) -> Path:
    """Resolve the portraits directory from the DF install path."""
    p = Path(df_install) / _PORTRAIT_REL
    if not p.exists():
        raise FileNotFoundError(f"Portrait images not found at {p}")
    return p


@lru_cache(maxsize=32)
def load_sprite_sheet(df_install: str, filename: str) -> Image.Image:
    """Load a sprite sheet PNG and convert to RGBA."""
    path = _portraits_dir(df_install) / filename
    if not path.exists():
        raise FileNotFoundError(f"Sprite sheet not found: {path}")
    return Image.open(path).convert("RGBA")


@lru_cache(maxsize=4)
def load_palette(df_install: str, filename: str) -> list[list[tuple[int, int, int, int]]]:
    """Load a palette PNG and return as list of rows, each row a list of RGBA tuples."""
    path = _portraits_dir(df_install) / filename
    if not path.exists():
        raise FileNotFoundError(f"Palette not found: {path}")
    img = Image.open(path).convert("RGBA")
    rows = []
    for y in range(img.height):
        row = [img.getpixel((x, y)) for x in range(img.width)]
        rows.append(row)
    return rows


def crop_tile(sheet: Image.Image, tx: int, ty: int) -> Image.Image:
    """Crop a single 96x96 tile from a sprite sheet at grid position (tx, ty)."""
    x0 = tx * TILE_SIZE
    y0 = ty * TILE_SIZE
    return sheet.crop((x0, y0, x0 + TILE_SIZE, y0 + TILE_SIZE))


def recolor_tile(tile: Image.Image, source_palette_row: list[tuple], target_palette_row: list[tuple]) -> Image.Image:
    """Recolor a tile by swapping source palette colors with target palette colors.

    DF sprites are pre-colored with palette row 0 (the default). To change
    skin/hair color, we map each pixel from the source row's colors to the
    corresponding target row's colors.
    """
    if source_palette_row == target_palette_row:
        return tile.copy()

    # Build color mapping: source RGBA -> target RGBA
    color_map: dict[tuple, tuple] = {}
    for src, tgt in zip(source_palette_row, target_palette_row):
        color_map[src] = tgt

    result = tile.copy()
    pixels = result.load()
    if pixels is None:
        return result

    for y in range(result.height):
        for x in range(result.width):
            px = pixels[x, y]
            if px[3] > 0 and px in color_map:
                pixels[x, y] = color_map[px]

    return result
