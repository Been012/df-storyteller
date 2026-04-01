"""Parse DF's portrait graphics definition files into structured layer rules.

Reads ``graphics_creatures_portrait_dwarf.txt`` and produces a list of
:class:`LayerRule` objects that can be evaluated against a dwarf's appearance
data to determine which sprite tiles to composite.

File format overview::

    [LAYER_SET:PORTRAIT]          # Age group (BABY, CHILD, or PORTRAIT=adult)
    [LS_PALETTE:BODY]             # Palette definition
    [LAYER_GROUP]                 # Group with optional group-level condition
    [LG_CONDITION_BP:...]         #   Group-level body part condition
        [BP_PRESENT]
    [LAYER:NAME:TILE_PAGE:X:Y]   # A single sprite layer
        [CONDITION_CASTE:MALE]    #   Conditions (AND logic — all must match)
        [CONDITION_TISSUE_LAYER:BY_CATEGORY:PART:TISSUE]
            [TISSUE_MAY_HAVE_COLOR:COLOR1:COLOR2]
            [TISSUE_MIN_LENGTH:N]
            [TISSUE_MAX_LENGTH:N]
            [TISSUE_NOT_SHAPED]
            [TISSUE_MAY_HAVE_SHAPING:STYLE]
            [TISSUE_SWAP:IF_MIN_CURLY:N:PAGE:X:Y]
        [CONDITION_BP:BY_CATEGORY:PART]
            [BP_APPEARANCE_MODIFIER_RANGE:MOD:MIN:MAX]
            [BP_PRESENT]
        [CONDITION_ITEM_WORN:BY_CATEGORY:SLOT:TYPE:SUBTYPE...]
        [CONDITION_RANDOM_PART_INDEX:NAME:INDEX:TOTAL]
        [CONDITION_SYN_CLASS:CLASS]
        [CONDITION_GHOST]
        [CONDITION_MATERIAL_FLAG:FLAG]
        [CONDITION_MATERIAL_TYPE:TYPE]
        [SHUT_OFF_IF_ITEM_PRESENT:BY_CATEGORY:SLOT:TYPE:SUBTYPE...]
        [USE_PALETTE:NAME:INDEX]
        [USE_STANDARD_PALETTE_FROM_ITEM]
    [END_LAYER_GROUP]
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TissueCondition:
    """Sub-conditions within a CONDITION_TISSUE_LAYER block."""

    body_part_category: str = ""    # e.g. "HEAD", "ALL", "CHEEK"
    tissue_type: str = ""           # e.g. "HAIR", "SKIN", "EYEBROW"
    may_have_colors: list[str] = field(default_factory=list)
    min_length: int | None = None
    max_length: int | None = None
    not_shaped: bool = False
    may_have_shaping: str = ""      # e.g. "NEATLY_COMBED", "BRAIDED"
    min_density: int | None = None
    max_density: int | None = None
    # Curly swap: if curliness >= threshold, use alternate tile
    swap_curly_threshold: int | None = None
    swap_tile_page: str = ""
    swap_tile_x: int = 0
    swap_tile_y: int = 0


@dataclass
class BPCondition:
    """Body part condition (CONDITION_BP)."""

    body_part_category: str = ""    # e.g. "HEAD"
    bp_present: bool = False
    modifier_type: str = ""         # e.g. "BROADNESS"
    modifier_min: int | None = None
    modifier_max: int | None = None


@dataclass
class ItemCondition:
    """Equipment/item worn condition."""

    slot: str = ""          # e.g. "BODY_UPPER", "HEAD"
    item_type: str = ""     # e.g. "ARMOR", "HELM"
    item_subtypes: list[str] = field(default_factory=list)  # e.g. ["ITEM_ARMOR_SHIRT"]


@dataclass
class LayerRule:
    """A single portrait layer with its conditions and tile reference."""

    name: str = ""
    tile_page: str = ""
    tile_x: int = 0
    tile_y: int = 0

    # Layer set context
    layer_set: str = ""     # "BABY", "CHILD", "PORTRAIT"

    # Group-level conditions (from LAYER_GROUP / LG_CONDITION_BP)
    group_bp_token: str = ""
    group_bp_present: bool = False

    # Layer-level conditions (all must match = AND logic)
    caste: str = ""                     # "MALE", "FEMALE", or "" (any)
    syn_class: str = ""                 # "ZOMBIE", "NECROMANCER", etc.
    is_ghost: bool = False
    tissue_conditions: list[TissueCondition] = field(default_factory=list)
    bp_conditions: list[BPCondition] = field(default_factory=list)
    item_conditions: list[ItemCondition] = field(default_factory=list)
    random_part_name: str = ""
    random_part_index: int = 0
    random_part_total: int = 0
    material_flag: str = ""
    material_type: str = ""

    # Shut-off conditions (if item is present, hide this layer)
    shut_off_items: list[ItemCondition] = field(default_factory=list)

    # Palette
    palette_name: str = ""      # "BODY" or "HAIR"
    palette_index: int = 0
    use_standard_palette_from_item: bool = False


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"\[([^\]]+)\]")


def _parse_tag(line: str) -> list[str] | None:
    """Extract the first [TAG:ARG1:ARG2:...] from a line."""
    m = _TAG_RE.search(line.strip())
    if m:
        return m.group(1).split(":")
    return None


def parse_portrait_graphics(filepath: str | Path) -> list[LayerRule]:
    """Parse a portrait graphics definition file into LayerRule objects.

    Only parses the adult ``[LAYER_SET:PORTRAIT]`` section.
    """
    path = Path(filepath)
    if not path.exists():
        logger.warning("Portrait graphics file not found: %s", path)
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    rules: list[LayerRule] = []
    current_layer_set = ""
    current_group_bp_token = ""
    current_group_bp_present = False
    current_layer: LayerRule | None = None
    current_tissue: TissueCondition | None = None
    current_bp: BPCondition | None = None
    in_target_set = False

    for line in lines:
        tag = _parse_tag(line)
        if not tag:
            continue

        cmd = tag[0]

        # Track LAYER_SET
        if cmd == "LAYER_SET":
            current_layer_set = tag[1] if len(tag) > 1 else ""
            in_target_set = current_layer_set == "PORTRAIT"
            continue

        # Only parse the adult PORTRAIT set
        if not in_target_set:
            continue

        # LAYER_GROUP management
        if cmd == "LAYER_GROUP":
            current_group_bp_token = ""
            current_group_bp_present = False
            _flush_layer(current_layer, rules)
            current_layer = None
            current_tissue = None
            current_bp = None
            continue

        if cmd == "END_LAYER_GROUP":
            _flush_layer(current_layer, rules)
            current_layer = None
            current_tissue = None
            current_bp = None
            current_group_bp_token = ""
            current_group_bp_present = False
            continue

        if cmd == "LG_CONDITION_BP":
            # e.g. LG_CONDITION_BP:BY_TOKEN:UB
            if len(tag) >= 3:
                current_group_bp_token = tag[2]
            continue

        if cmd == "BP_PRESENT" and current_layer is None:
            # Group-level BP_PRESENT
            current_group_bp_present = True
            continue

        # New LAYER definition
        if cmd == "LAYER":
            _flush_layer(current_layer, rules)
            current_tissue = None
            current_bp = None
            # LAYER:NAME:TILE_PAGE:X:Y
            current_layer = LayerRule(
                name=tag[1] if len(tag) > 1 else "",
                tile_page=tag[2] if len(tag) > 2 else "",
                tile_x=int(tag[3]) if len(tag) > 3 else 0,
                tile_y=int(tag[4]) if len(tag) > 4 else 0,
                layer_set=current_layer_set,
                group_bp_token=current_group_bp_token,
                group_bp_present=current_group_bp_present,
            )
            continue

        if current_layer is None:
            continue

        # Layer-level conditions
        if cmd == "CONDITION_CASTE":
            current_layer.caste = tag[1] if len(tag) > 1 else ""
            continue

        if cmd == "CONDITION_SYN_CLASS":
            current_layer.syn_class = tag[1] if len(tag) > 1 else ""
            continue

        if cmd == "CONDITION_GHOST":
            current_layer.is_ghost = True
            continue

        if cmd == "CONDITION_TISSUE_LAYER":
            # e.g. CONDITION_TISSUE_LAYER:BY_CATEGORY:HEAD:HAIR
            current_tissue = TissueCondition(
                body_part_category=tag[2] if len(tag) > 2 else "",
                tissue_type=tag[3] if len(tag) > 3 else "",
            )
            current_layer.tissue_conditions.append(current_tissue)
            current_bp = None
            continue

        if cmd == "CONDITION_BP":
            # e.g. CONDITION_BP:BY_CATEGORY:HEAD
            current_bp = BPCondition(
                body_part_category=tag[2] if len(tag) > 2 else "",
            )
            current_layer.bp_conditions.append(current_bp)
            current_tissue = None
            continue

        if cmd == "CONDITION_ITEM_WORN":
            # e.g. CONDITION_ITEM_WORN:BY_CATEGORY:BODY_UPPER:ARMOR:ITEM_ARMOR_SHIRT:ITEM_ARMOR_DRESS
            ic = ItemCondition(
                slot=tag[2] if len(tag) > 2 else "",
                item_type=tag[3] if len(tag) > 3 else "",
                item_subtypes=tag[4:] if len(tag) > 4 else [],
            )
            current_layer.item_conditions.append(ic)
            continue

        if cmd == "CONDITION_RANDOM_PART_INDEX":
            # e.g. CONDITION_RANDOM_PART_INDEX:SHIRT:1:5
            current_layer.random_part_name = tag[1] if len(tag) > 1 else ""
            current_layer.random_part_index = int(tag[2]) if len(tag) > 2 else 0
            current_layer.random_part_total = int(tag[3]) if len(tag) > 3 else 0
            continue

        if cmd == "CONDITION_MATERIAL_FLAG":
            current_layer.material_flag = tag[1] if len(tag) > 1 else ""
            continue

        if cmd == "CONDITION_MATERIAL_TYPE":
            current_layer.material_type = tag[1] if len(tag) > 1 else ""
            continue

        # Tissue sub-conditions
        if current_tissue is not None:
            if cmd == "TISSUE_MAY_HAVE_COLOR":
                current_tissue.may_have_colors = tag[1:]
                continue
            if cmd == "TISSUE_MIN_LENGTH":
                current_tissue.min_length = int(tag[1]) if len(tag) > 1 else 0
                continue
            if cmd == "TISSUE_MAX_LENGTH":
                current_tissue.max_length = int(tag[1]) if len(tag) > 1 else 0
                continue
            if cmd == "TISSUE_NOT_SHAPED":
                current_tissue.not_shaped = True
                continue
            if cmd == "TISSUE_MAY_HAVE_SHAPING":
                current_tissue.may_have_shaping = tag[1] if len(tag) > 1 else ""
                continue
            if cmd == "TISSUE_MIN_DENSITY":
                current_tissue.min_density = int(tag[1]) if len(tag) > 1 else 0
                continue
            if cmd == "TISSUE_MAX_DENSITY":
                current_tissue.max_density = int(tag[1]) if len(tag) > 1 else 0
                continue
            if cmd == "TISSUE_SWAP":
                # TISSUE_SWAP:IF_MIN_CURLY:150:PORTRAIT_DWARF_HAIR:2:7
                if len(tag) >= 6 and tag[1] == "IF_MIN_CURLY":
                    current_tissue.swap_curly_threshold = int(tag[2])
                    current_tissue.swap_tile_page = tag[3]
                    current_tissue.swap_tile_x = int(tag[4])
                    current_tissue.swap_tile_y = int(tag[5])
                continue

        # BP sub-conditions
        if current_bp is not None:
            if cmd == "BP_PRESENT":
                current_bp.bp_present = True
                continue
            if cmd == "BP_APPEARANCE_MODIFIER_RANGE":
                # BP_APPEARANCE_MODIFIER_RANGE:BROADNESS:0:99
                current_bp.modifier_type = tag[1] if len(tag) > 1 else ""
                current_bp.modifier_min = int(tag[2]) if len(tag) > 2 else None
                current_bp.modifier_max = int(tag[3]) if len(tag) > 3 else None
                continue

        # Shut-off conditions
        if cmd == "SHUT_OFF_IF_ITEM_PRESENT":
            # SHUT_OFF_IF_ITEM_PRESENT:BY_CATEGORY:HEAD:HELM:ITEM_HELM_HELM:...
            ic = ItemCondition(
                slot=tag[2] if len(tag) > 2 else "",
                item_type=tag[3] if len(tag) > 3 else "",
                item_subtypes=tag[4:] if len(tag) > 4 else [],
            )
            current_layer.shut_off_items.append(ic)
            continue

        # Palette
        if cmd == "USE_PALETTE":
            current_layer.palette_name = tag[1] if len(tag) > 1 else ""
            current_layer.palette_index = int(tag[2]) if len(tag) > 2 else 0
            continue

        if cmd == "USE_STANDARD_PALETTE_FROM_ITEM":
            current_layer.use_standard_palette_from_item = True
            continue

    # Flush last layer
    _flush_layer(current_layer, rules)

    logger.info("Parsed %d portrait layer rules from %s", len(rules), path.name)
    return rules


def _flush_layer(layer: LayerRule | None, rules: list[LayerRule]) -> None:
    """Add a completed layer to the rules list."""
    if layer is not None and layer.tile_page:
        rules.append(layer)
