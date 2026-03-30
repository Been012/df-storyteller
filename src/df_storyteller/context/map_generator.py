"""Generate terrain map PNG from DF legends region data."""

from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# Region type -> RGB color (fantasy map palette)
REGION_COLORS: dict[str, tuple[int, int, int]] = {
    "Ocean": (54, 100, 139),
    "Lake": (72, 133, 181),
    "Forest": (34, 100, 34),
    "Mountains": (139, 137, 137),
    "Hills": (160, 140, 100),
    "Desert": (210, 180, 110),
    "Grassland": (124, 170, 80),
    "Wetland": (80, 120, 100),
    "Tundra": (180, 195, 210),
    "Glacier": (220, 230, 240),
}
DEFAULT_COLOR = (128, 128, 128)


def generate_terrain_map(
    regions: list[dict[str, Any]], scale: int = 4
) -> tuple[bytes, int, int] | None:
    """Generate a terrain map PNG from region coordinate data.

    Args:
        regions: List of region dicts with keys: id, name, type, coords, evilness.
                 `type` comes from basic legends, `coords` from legends_plus
                 (pipe-separated "x,y|x,y|..." tile coordinates).
        scale: Pixels per world tile. 4 = 4x4 pixels per tile.

    Returns:
        (png_bytes, world_width, world_height) or None if no coord data available.
    """
    # Build region_id -> type and region_id -> coords mappings
    region_types: dict[str, str] = {}
    region_coords: dict[str, list[tuple[int, int]]] = {}

    for region in regions:
        rid = str(region.get("id", ""))
        rtype = region.get("type", "")
        coords_str = region.get("coords", "")

        if rtype:
            region_types[rid] = rtype
        if coords_str:
            tiles = []
            for pair in coords_str.split("|"):
                parts = pair.strip().split(",")
                if len(parts) == 2:
                    try:
                        tiles.append((int(parts[0]), int(parts[1])))
                    except ValueError:
                        pass
            if tiles:
                region_coords[rid] = tiles

    if not region_coords:
        logger.warning("No region coordinate data available for map generation")
        return None

    # Discover world dimensions
    max_x = max_y = 0
    for tiles in region_coords.values():
        for x, y in tiles:
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y

    world_w = max_x + 1
    world_h = max_y + 1
    logger.info("Generating terrain map: %dx%d tiles at %dx scale", world_w, world_h, scale)

    # Create image at 1:1 scale first (one pixel per tile)
    img = Image.new("RGB", (world_w, world_h), DEFAULT_COLOR)
    pixels = img.load()

    # Paint each tile by region type
    for rid, tiles in region_coords.items():
        rtype = region_types.get(rid, "")
        color = REGION_COLORS.get(rtype, DEFAULT_COLOR)
        # Slight per-region color variation for visual differentiation
        rid_hash = hash(rid) % 15 - 7  # -7 to +7
        color = (
            max(0, min(255, color[0] + rid_hash)),
            max(0, min(255, color[1] + rid_hash)),
            max(0, min(255, color[2] + rid_hash)),
        )
        for x, y in tiles:
            if 0 <= x < world_w and 0 <= y < world_h:
                pixels[x, y] = color

    # Scale up with nearest-neighbor for crisp pixel art
    if scale > 1:
        img = img.resize((world_w * scale, world_h * scale), Image.NEAREST)

    # Export as PNG
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), world_w, world_h
