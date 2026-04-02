"""Evaluate parsed portrait layer rules against dwarf appearance data.

Given a list of :class:`LayerRule` from the parser and a dwarf's appearance
dict, selects the matching layers in render order and returns them as
tile references ready for compositing.

The evaluator implements DF's "first match wins" logic: layers in the file
are tested in order, and the first layer in each group whose conditions
all match is selected. Multiple groups can each contribute one layer.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from df_storyteller.portraits.graphics_parser import (
    BPCondition,
    ItemCondition,
    LayerRule,
    TissueCondition,
)

logger = logging.getLogger(__name__)


@dataclass
class DwarfAppearanceData:
    """Appearance data used for condition evaluation.

    All fields are optional — missing data is treated as "no match"
    for conditions that require it, allowing partial data to still
    produce a portrait (just with fewer layers).
    """

    sex: str = "male"                   # "male" or "female"
    skin_color: str = ""                # DF color name (e.g. "PEACH")
    hair_color: str = ""                # DF color name
    beard_color: str = ""               # DF color name
    eyebrow_color: str = ""             # DF color name (usually same as hair)
    hair_length: int = 0                # Tissue length units
    hair_shaping: str = ""              # "NEATLY_COMBED", "BRAIDED", etc. or "" for unshaped
    hair_curly: int = 0                 # Curliness value (0-200+)
    beard_length: int = 0
    beard_shaping: str = ""
    beard_curly: int = 0
    sideburn_length: int = 0
    sideburn_shaping: str = ""
    mustache_length: int = 0
    mustache_shaping: str = ""
    head_broadness: int = 100           # 0-200, affects thin vs broad head
    eye_round_vs_narrow: int = 100      # 0-99=narrow, 100+=round
    eye_deep_set: int = 100             # 101-200=deep-set
    eyebrow_density: int = 100          # 50-90=sparse, 110-150=dense
    nose_upturned: int = 100            # 101-200=upturned
    nose_length: int = 100              # 101-200=long
    nose_broadness: int = 100           # 0-99=narrow, 101-200=wide
    is_vampire: bool = False
    is_zombie: bool = False
    is_necromancer: bool = False
    is_ghost: bool = False
    is_werebeast: bool = False
    body_parts_present: set[str] = field(default_factory=lambda: {
        "UB", "HD", "R_EAR", "L_EAR", "NOSE", "MOUTH",
    })
    # Equipment: list of dicts with {slot, item_type, item_subtype, material_flags}
    equipment: list[dict] = field(default_factory=list)
    # Deterministic random seed (from unit_id)
    random_seed: int = 0
    age: float = 0


@dataclass
class SelectedLayer:
    """A layer selected for rendering."""

    tile_page: str
    tile_x: int
    tile_y: int
    palette_name: str = ""
    palette_index: int = 0
    use_item_palette: bool = False
    item_color: tuple[int, int, int] | None = None  # RGB from material for item palette


def _get_tissue_data(appearance: DwarfAppearanceData, body_part: str, tissue_type: str) -> dict:
    """Get tissue-specific data for condition matching.

    Maps body_part + tissue_type to the appropriate appearance fields.
    """
    tissue = tissue_type.upper()
    part = body_part.upper()

    if tissue == "SKIN" or tissue == "HIDE":
        return {
            "color": appearance.skin_color,
            "length": 0,
            "shaping": "",
            "curly": 0,
        }

    if tissue == "HAIR":
        if part in ("HEAD", "ALL"):
            return {
                "color": appearance.hair_color,
                "length": appearance.hair_length,
                "shaping": appearance.hair_shaping,
                "curly": appearance.hair_curly,
            }
        if part in ("CHEEK", "R_CHEEK", "L_CHEEK", "CHIN"):
            return {
                "color": appearance.beard_color or appearance.hair_color,
                "length": appearance.beard_length,
                "shaping": appearance.beard_shaping,
                "curly": appearance.beard_curly,
            }
        # Sideburns or generic
        return {
            "color": appearance.hair_color,
            "length": appearance.sideburn_length,
            "shaping": appearance.sideburn_shaping,
            "curly": 0,
        }

    # Beard/chin whiskers — same data as facial hair
    if tissue in ("CHIN_WHISKERS", "CHEEK_WHISKERS", "MOUSTACHE_WHISKERS"):
        return {
            "color": appearance.beard_color or appearance.hair_color,
            "length": appearance.beard_length,
            "shaping": appearance.beard_shaping,
            "curly": appearance.beard_curly,
        }

    if tissue == "EYEBROW":
        return {
            "color": appearance.eyebrow_color or appearance.hair_color,
            "length": 0,
            "shaping": "",
            "curly": 0,
            "density": appearance.eyebrow_density,
        }

    if tissue == "MOUSTACHE":
        return {
            "color": appearance.hair_color,
            "length": appearance.mustache_length,
            "shaping": appearance.mustache_shaping,
            "curly": 0,
        }

    # Default
    return {"color": "", "length": 0, "shaping": "", "curly": 0}


def _match_tissue(tc: TissueCondition, appearance: DwarfAppearanceData) -> bool:
    """Check if a tissue condition matches."""
    tissue_data = _get_tissue_data(appearance, tc.body_part_category, tc.tissue_type)

    # Color check
    if tc.may_have_colors:
        if tissue_data["color"] not in tc.may_have_colors:
            return False

    # Length checks
    if tc.min_length is not None:
        if tissue_data["length"] < tc.min_length:
            return False
    if tc.max_length is not None:
        if tissue_data["length"] > tc.max_length:
            return False

    # Shaping checks
    if tc.not_shaped:
        if tissue_data["shaping"]:
            return False  # Has shaping but rule requires unshaped
    if tc.may_have_shaping:
        if tissue_data["shaping"] != tc.may_have_shaping:
            return False

    # Density checks
    density = tissue_data.get("density")
    if density is not None:
        if tc.min_density is not None and density < tc.min_density:
            return False
        if tc.max_density is not None and density > tc.max_density:
            return False

    return True


def _match_bp(bp: BPCondition, appearance: DwarfAppearanceData) -> bool:
    """Check if a body part condition matches."""
    # BP_MISSING: only matches if the body part is actually missing (injuries).
    # Assume all parts are present for healthy dwarves — reject BP_MISSING conditions.
    if bp.bp_missing:
        return False

    if bp.bp_present:
        if bp.body_part_category and bp.body_part_category not in appearance.body_parts_present:
            # Check by category name (HEAD -> HD token might differ)
            pass  # Be permissive — assume present unless we know it's missing

    if bp.modifier_type:
        # Map body_part_category + modifier_type to the correct appearance value
        cat = bp.body_part_category.upper() if bp.body_part_category else ""
        mod = bp.modifier_type.upper()

        if mod == "BROADNESS" and cat in ("HEAD", ""):
            val = appearance.head_broadness
        elif mod == "ROUND_VS_NARROW" and cat == "EYE":
            val = appearance.eye_round_vs_narrow
        elif mod == "DEEP_SET" and cat == "EYE":
            val = appearance.eye_deep_set
        elif mod == "UPTURNED" and cat == "NOSE":
            val = appearance.nose_upturned
        elif mod == "LENGTH" and cat == "NOSE":
            val = appearance.nose_length
        elif mod == "BROADNESS" and cat == "NOSE":
            val = appearance.nose_broadness
        else:
            return True  # Unknown modifier — be permissive

        if bp.modifier_min is not None and val < bp.modifier_min:
            return False
        if bp.modifier_max is not None and val > bp.modifier_max:
            return False

    return True


def _match_item_worn(ic: ItemCondition, equipment: list[dict]) -> bool:
    """Check if a specific item is worn."""
    for item in equipment:
        if ic.slot and item.get("slot", "") != ic.slot:
            continue
        if ic.item_type and item.get("item_type", "") != ic.item_type:
            continue
        if ic.item_subtypes:
            item_sub = item.get("item_subtype", "")
            if item_sub not in ic.item_subtypes:
                continue
        return True
    return False


def _find_matching_item(rule: LayerRule, equipment: list[dict]) -> dict | None:
    """Find the first equipment item matching any of the rule's item conditions."""
    for ic in rule.item_conditions:
        for item in equipment:
            if ic.slot and item.get("slot", "") != ic.slot:
                continue
            if ic.item_type and item.get("item_type", "") != ic.item_type:
                continue
            if ic.item_subtypes:
                if item.get("item_subtype", "") not in ic.item_subtypes:
                    continue
            return item
    return None


def _match_random(rule: LayerRule, seed: int) -> bool:
    """Check CONDITION_RANDOM_PART_INDEX."""
    if not rule.random_part_name:
        return True  # No random condition

    # Generate a deterministic random index from seed + part name
    h = int(hashlib.md5(f"{seed}:{rule.random_part_name}".encode()).hexdigest(), 16)
    chosen = (h % rule.random_part_total) + 1  # 1-indexed
    return chosen == rule.random_part_index


def _match_syn_class(rule: LayerRule, appearance: DwarfAppearanceData) -> bool:
    """Check CONDITION_SYN_CLASS."""
    if not rule.syn_class:
        return True

    syn = rule.syn_class.upper()
    if syn == "ZOMBIE" and appearance.is_zombie:
        return True
    if syn == "NECROMANCER" and appearance.is_necromancer:
        return True
    if syn in ("VAMPCURSE", "VAMPIRE") and appearance.is_vampire:
        return True
    if syn == "RAISED_UNDEAD":
        return False  # Assume living dwarves
    if syn == "DISTURBED_DEAD":
        return False
    if syn == "GHOUL":
        return False
    return False


def _is_shut_off(rule: LayerRule, equipment: list[dict]) -> bool:
    """Check if any SHUT_OFF_IF_ITEM_PRESENT condition triggers."""
    for ic in rule.shut_off_items:
        if _match_item_worn(ic, equipment):
            return True
    return False


def _matches(rule: LayerRule, appearance: DwarfAppearanceData) -> bool:
    """Check if ALL conditions on a layer rule match the dwarf's appearance."""

    # Syn class / ghost (these are exclusive — zombie rules only match zombies)
    if rule.syn_class:
        if not _match_syn_class(rule, appearance):
            return False
    elif rule.is_ghost:
        if not appearance.is_ghost:
            return False
    else:
        # Normal (non-undead) rules should NOT match undead dwarves
        # But living dwarves should match rules without syn_class
        pass

    # Caste
    if rule.caste:
        if rule.caste.upper() != appearance.sex.upper():
            return False

    # Tissue conditions (all must match)
    for tc in rule.tissue_conditions:
        if not _match_tissue(tc, appearance):
            return False

    # BP conditions
    for bp in rule.bp_conditions:
        if not _match_bp(bp, appearance):
            return False

    # Item worn conditions
    for ic in rule.item_conditions:
        if not _match_item_worn(ic, appearance.equipment):
            return False

    # Material conditions (apply to the worn item that matched item_conditions)
    if rule.material_flag or rule.material_type:
        matched_item = _find_matching_item(rule, appearance.equipment)
        if matched_item:
            if rule.material_flag:
                item_flags = matched_item.get("material_flags", [])
                # material_flag can be "FLAG1:FLAG2" (colon-separated, ALL must match)
                for flag in rule.material_flag.split(":"):
                    if flag not in item_flags:
                        return False
            if rule.material_type:
                if matched_item.get("material_type", "") != rule.material_type:
                    return False
        else:
            return False  # Material condition but no matching item

    # Item quality check (0=ordinary through 5=masterwork, -1=any)
    if rule.item_quality >= 0:
        matched_item = matched_item if (rule.material_flag or rule.material_type) else _find_matching_item(rule, appearance.equipment)
        if matched_item:
            if matched_item.get("quality", 0) != rule.item_quality:
                return False
        else:
            return False

    # Random part index
    if not _match_random(rule, appearance.random_seed):
        return False

    # Shut-off check
    if _is_shut_off(rule, appearance.equipment):
        return False

    return True


def evaluate_layers(
    rules: list[LayerRule],
    appearance: DwarfAppearanceData,
) -> list[SelectedLayer]:
    """Evaluate all layer rules and return matching layers in render order.

    DF uses "first match wins" within each LAYER_GROUP — layers in the
    same group are mutually exclusive alternatives (e.g. different skin
    tones, head shapes). Only the first matching layer per group is selected.
    Different groups can each contribute a layer (e.g. body group + arm group).
    """
    selected: list[SelectedLayer] = []
    matched_groups: set[int] = set()

    for rule in rules:
        # Skip if we already matched a layer in this group
        if rule.group_id in matched_groups:
            continue

        if _matches(rule, appearance):
            # Mark this group as matched
            matched_groups.add(rule.group_id)

            # Check for curly swap on tissue conditions
            tile_page = rule.tile_page
            tile_x = rule.tile_x
            tile_y = rule.tile_y

            for tc in rule.tissue_conditions:
                if tc.swap_curly_threshold is not None:
                    tissue_data = _get_tissue_data(
                        appearance, tc.body_part_category, tc.tissue_type
                    )
                    if tissue_data["curly"] >= tc.swap_curly_threshold:
                        tile_page = tc.swap_tile_page
                        tile_x = tc.swap_tile_x
                        tile_y = tc.swap_tile_y

            # Get material color for item palette recoloring
            item_color = None
            if rule.use_standard_palette_from_item:
                matched_item = _find_matching_item(rule, appearance.equipment)
                if matched_item and matched_item.get("material_color"):
                    mc = matched_item["material_color"]
                    item_color = (mc[0], mc[1], mc[2])

            selected.append(SelectedLayer(
                tile_page=tile_page,
                tile_x=tile_x,
                tile_y=tile_y,
                palette_name=rule.palette_name,
                palette_index=rule.palette_index,
                use_item_palette=rule.use_standard_palette_from_item,
                item_color=item_color,
            ))

    return selected
