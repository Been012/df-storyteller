"""Dwarf roster, detail, relationships, and religion routes."""
from __future__ import annotations

import re
import logging
from collections import defaultdict as _defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from df_storyteller.context.narrative_formatter import (
    format_dwarf_narrative,
    _describe_physical_attr,
    _describe_mental_attr,
    _skill_level_name,
    _resolve_skill_name,
)
from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
    SEASON_ORDER_MAP,
)
from df_storyteller.web.templates_setup import templates
from df_storyteller.web.helpers import (
    build_dwarf_name_map as _build_dwarf_name_map,
    linkify_dwarf_names as _linkify_dwarf_names,
    markdown_to_html as _markdown_to_html,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dwarves", response_class=HTMLResponse)
async def dwarves_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    ranked = character_tracker.ranked_characters()

    # Load highlights for badge display
    from df_storyteller.context.highlights_store import load_all_highlights
    from df_storyteller.schema.events import EventType as ET, CrimeData
    fortress_dir = _get_fortress_dir(config, metadata)
    highlights_map = {h.unit_id: h.role.value for h in load_all_highlights(config, output_dir=fortress_dir)}

    # Auto-detect suspicious dwarves from crime events (don't override manual highlights)
    for crime_event in event_store.events_by_type(ET.CRIME):
        data = crime_event.data
        if isinstance(data, CrimeData) and data.suspect and data.suspect.unit_id:
            uid = data.suspect.unit_id
            if uid not in highlights_map:
                highlights_map[uid] = "suspicious"

    dwarves = []
    for dwarf, score in ranked:
        notable_traits = ""
        if dwarf.personality and dwarf.personality.notable_facets:
            traits = [f.description for f in dwarf.personality.notable_facets[:3] if f.description]
            notable_traits = "; ".join(traits)

        # Permanent injuries from wound data
        permanent_injuries = []
        for w in dwarf.wounds:
            if isinstance(w, dict) and w.get("is_permanent"):
                permanent_injuries.append(f"{w.get('wound_type', 'injured')} {w.get('body_part', '')}")

        # Mood description from stress_category (DFHack getStressCategory)
        # 0=haggard, 1=very stressed, 2=stressed, 3=content, 4=pleased, 5=very happy, 6=ecstatic
        _STRESS_DESCS = {
            0: "haggard",
            1: "very stressed",
            2: "stressed",
            3: "content",
            4: "pleased",
            5: "very happy",
            6: "ecstatic",
        }
        stress_cat = dwarf.stress_category if isinstance(dwarf.stress_category, int) else 3
        happiness_desc = _STRESS_DESCS.get(stress_cat, "content")

        dwarves.append({
            "unit_id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "age": dwarf.age,
            "sex": dwarf.sex,
            "noble_positions": dwarf.noble_positions,
            "notable_traits": notable_traits,
            "highlight_role": highlights_map.get(dwarf.unit_id, ""),
            "happiness_desc": happiness_desc,
            "permanent_injuries": permanent_injuries,
            "is_alive": dwarf.is_alive,
        })

    # Build visitors and traders lists from metadata
    visitors = []
    traders = []
    for v in metadata.get("visitors", []):
        name = v.get("name", "Unknown")
        hfid = v.get("hist_figure_id")
        prof = v.get("profession", "")
        entry = {
            "name": name,
            "profession": prof,
            "race": v.get("race", "").replace("_", " ").title(),
            "age": v.get("age", 0),
            "role": v.get("role", "visitor"),
            "hfid": hfid if hfid and hfid > 0 else None,
            "civ_name": v.get("civ_name", ""),
        }
        # Separate merchants/traders from regular visitors
        prof_lower = prof.lower()
        if "merchant" in prof_lower or "trader" in prof_lower or "caravan" in prof_lower:
            traders.append(entry)
        else:
            visitors.append(entry)

    # Build animals grouped into accordion sections
    def _animal_dict(a) -> dict:
        return {
            "name": getattr(a, "name", ""),
            "race": getattr(a, "race", "").replace("_", " ").title(),
            "profession": getattr(a, "profession", ""),
            "age": getattr(a, "age", 0),
            "sex": getattr(a, "sex", ""),
            "owner_name": getattr(a, "owner_name", ""),
            "category": getattr(a, "category", "wild"),
            "traits": getattr(a, "traits", []),
        }

    pets_owned: list[dict] = []       # actual pets with owners
    pets_adoptable: list[dict] = []   # available for adoption, no owner yet
    livestock: list[dict] = []        # tame animals (inc. war/hunting trained)
    wild_animals: list[dict] = []     # wild/untamed
    for a in metadata.get("animals", []):
        cat = getattr(a, "category", "wild")
        if cat == "pet":
            pets_owned.append(_animal_dict(a))
        elif cat == "adoptable":
            pets_adoptable.append(_animal_dict(a))
        elif cat in ("war", "hunting", "tame"):
            livestock.append(_animal_dict(a))
        else:
            wild_animals.append(_animal_dict(a))

    total_animals = len(pets_owned) + len(pets_adoptable) + len(livestock) + len(wild_animals)

    return templates.TemplateResponse(request=request, name="dwarves.html", context={
        **ctx, "content_class": "content-wide", "dwarves": dwarves, "visitors": visitors, "traders": traders,
        "pets_owned": pets_owned, "pets_adoptable": pets_adoptable,
        "livestock": livestock, "wild_animals": wild_animals,
        "total_animals": total_animals,
    })


@router.get("/dwarves/relationships", response_class=HTMLResponse)
async def relationships_page(request: Request):
    """Fortress-wide relationship web visualization."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    return templates.TemplateResponse(request=request, name="relationships.html", context=ctx)


@router.get("/dwarves/religion", response_class=HTMLResponse)
async def religion_page(request: Request):
    """Fortress pantheon — deity worship overview."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    return templates.TemplateResponse(request=request, name="religion.html", context=ctx)


@router.get("/api/religion")
async def api_religion():
    """Return religion graph data as JSON — deities and their worshippers."""
    config = _get_config()
    # Load with legends to get deity sphere data
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ranked = character_tracker.ranked_characters()

    deities: dict[str, dict] = {}  # deity name -> {id, name, worshippers: []}
    dwarf_nodes = []

    for dwarf, score in ranked:
        dwarf_nodes.append({
            "id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
        })
        for rel in dwarf.relationships:
            if rel.relationship_type == "deity":
                deity_name = rel.target_name
                if deity_name not in deities:
                    deities[deity_name] = {
                        "id": f"deity_{rel.target_unit_id}",
                        "name": deity_name,
                        "worshippers": [],
                    }
                deities[deity_name]["worshippers"].append(dwarf.unit_id)

    # Build nodes and edges
    nodes = []
    edges = []

    # Look up deity spheres from legends data.
    # Legends uses dwarven-language names ("avuz", "inod") while the snapshot
    # has English translated names ("Avuz", "Inod the Defensive Sanctum").
    # Build lookup by all name words so "avuz" matches "Avuz" and
    # "inod" matches "Inod the Defensive Sanctum".
    _legend_deities: list[tuple[str, list[str]]] = []  # [(name, spheres)]
    if world_lore.is_loaded and world_lore._legends:
        for hf in world_lore._legends.historical_figures.values():
            if (hf.is_deity or hf.hf_type == "deity") and hf.spheres:
                _legend_deities.append((hf.name.lower(), hf.spheres))

    def _find_deity_spheres(deity_name: str) -> list[str]:
        dn = deity_name.lower()
        first_word = dn.split()[0] if dn else ""
        for legend_name, legend_spheres in _legend_deities:
            # Exact first word match (most reliable)
            legend_first = legend_name.split()[0] if legend_name else ""
            if first_word and legend_first == first_word:
                return legend_spheres
        for legend_name, legend_spheres in _legend_deities:
            # Full legend name appears in the snapshot deity name
            if legend_name and legend_name in dn:
                return legend_spheres
        return []

    # Deity nodes
    for deity in deities.values():
        spheres = _find_deity_spheres(deity["name"])
        nodes.append({
            "id": deity["id"],
            "name": deity["name"],
            "type": "deity",
            "worshipper_count": len(deity["worshippers"]),
            "spheres": spheres,
        })
        for dwarf_id in deity["worshippers"]:
            edges.append({
                "source": str(dwarf_id),
                "target": deity["id"],
                "type": "worship",
            })

    # Dwarf nodes
    for d in dwarf_nodes:
        # Only include dwarves that worship at least one deity
        has_worship = any(d["id"] in deity["worshippers"] for deity in deities.values())
        if has_worship:
            nodes.append({
                "id": str(d["id"]),
                "name": d["name"],
                "type": "dwarf",
                "profession": d["profession"],
                "is_alive": d["is_alive"],
            })

    return {"nodes": nodes, "edges": edges, "deity_count": len(deities)}


@router.get("/api/relationships")
async def api_relationships():
    """Return relationship graph data as JSON for the visualization."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ranked = character_tracker.ranked_characters()

    nodes = []
    edges = []
    dwarf_ids = {dwarf.unit_id for dwarf, _ in ranked}

    for dwarf, score in ranked:
        nodes.append({
            "id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
            "score": round(score, 1),
        })
        for rel in dwarf.relationships:
            if rel.target_unit_id in dwarf_ids:
                edges.append({
                    "source": dwarf.unit_id,
                    "target": rel.target_unit_id,
                    "type": rel.relationship_type,
                })

    # Infer sibling relationships from shared parents
    parent_to_children: dict[int, list[int]] = {}
    for dwarf, _ in ranked:
        for rel in dwarf.relationships:
            if rel.relationship_type in ("mother", "father") and rel.target_unit_id in dwarf_ids:
                parent_to_children.setdefault(rel.target_unit_id, []).append(dwarf.unit_id)
    for parent_id, children in parent_to_children.items():
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                edges.append({
                    "source": children[i],
                    "target": children[j],
                    "type": "sibling",
                })

    # Deduplicate symmetric edges — keep most specific type
    seen: set[tuple[int, int]] = set()
    unique_edges = []
    for edge in edges:
        pair = (min(edge["source"], edge["target"]), max(edge["source"], edge["target"]))
        if pair not in seen:
            seen.add(pair)
            unique_edges.append(edge)

    return {"nodes": nodes, "edges": unique_edges}


@router.get("/api/relationships/family")
async def api_relationships_family():
    """Return family tree data for fortress dwarves using legends hf_link data."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ranked = character_tracker.ranked_characters()

    if not world_lore.is_loaded or not world_lore._legends:
        return {"nodes": [], "edges": [], "error": "Legends data required for family trees"}

    legends = world_lore._legends
    nodes = []
    edges = []
    seen_edges: set[tuple[int, int, str]] = set()

    # Map unit_id -> hist_figure_id for fortress dwarves
    unit_to_hf: dict[int, int] = {}
    hf_to_unit: dict[int, int] = {}
    for dwarf, score in ranked:
        if dwarf.hist_figure_id and dwarf.hist_figure_id > 0:
            unit_to_hf[dwarf.unit_id] = dwarf.hist_figure_id
            hf_to_unit[dwarf.hist_figure_id] = dwarf.unit_id

    # Build nodes from fortress dwarves
    for dwarf, score in ranked:
        hfid = unit_to_hf.get(dwarf.unit_id)
        family = legends.get_hf_family(hfid) if hfid else {"parents": [], "children": [], "spouse": []}
        # Count family connections within the fortress
        fortress_family = sum(1 for p in family["parents"] if p in hf_to_unit) + \
                          sum(1 for c in family["children"] if c in hf_to_unit) + \
                          sum(1 for s in family["spouse"] if s in hf_to_unit)
        nodes.append({
            "id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
            "has_family": fortress_family > 0,
        })

        if not hfid:
            continue

        # Add family edges (only between fortress dwarves)
        for parent_hf in family["parents"]:
            if parent_hf in hf_to_unit:
                key = (min(dwarf.unit_id, hf_to_unit[parent_hf]), max(dwarf.unit_id, hf_to_unit[parent_hf]), "parent")
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"source": hf_to_unit[parent_hf], "target": dwarf.unit_id, "type": "parent"})

        for spouse_hf in family["spouse"]:
            if spouse_hf in hf_to_unit:
                key = (min(dwarf.unit_id, hf_to_unit[spouse_hf]), max(dwarf.unit_id, hf_to_unit[spouse_hf]), "spouse")
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"source": dwarf.unit_id, "target": hf_to_unit[spouse_hf], "type": "spouse"})

    return {"nodes": nodes, "edges": edges}


@router.get("/dwarves/{unit_id}", response_class=HTMLResponse)
async def dwarf_detail_page(request: Request, unit_id: int):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "dwarves", metadata)
    dwarf = character_tracker.get_dwarf(unit_id)

    if not dwarf:
        return RedirectResponse("/dwarves")

    # Build template-friendly dwarf data
    stress_descs = {0: "ecstatic", 1: "happy", 2: "content", 3: "fine", 4: "stressed", 5: "very unhappy", 6: "breaking down"}

    personality_traits = []
    if dwarf.personality:
        for f in dwarf.personality.notable_facets:
            if f.description:
                personality_traits.append(f.description)

    beliefs = []
    if dwarf.personality:
        for b in dwarf.personality.notable_beliefs:
            if b.description:
                beliefs.append(b.description)

    goals = []
    if dwarf.personality:
        for g in dwarf.personality.goals:
            if g.description:
                goals.append(g.description)

    physical_attrs = []
    for attr, value in dwarf.physical_attributes.items():
        desc = _describe_physical_attr(attr, value)
        if desc:
            physical_attrs.append(desc)

    mental_attrs = []
    for attr, value in dwarf.mental_attributes.items():
        desc = _describe_mental_attr(attr, value)
        if desc:
            mental_attrs.append(desc)

    skills = []
    if dwarf.skills:
        # Sort by level descending, then experience descending
        all_skills = sorted(dwarf.skills, key=lambda s: (int(s.level) if str(s.level).isdigit() else 0, s.experience), reverse=True)
        for s in all_skills:
            level_num = int(s.level) if str(s.level).isdigit() else 0
            level_name = _skill_level_name(level_num)
            skill_name = _resolve_skill_name(s.name)
            skills.append({"name": skill_name, "level": level_name, "level_num": level_num})

    relationships = [
        {"type": r.relationship_type, "name": r.target_name}
        for r in dwarf.relationships
    ]

    # Load highlight for this dwarf
    from df_storyteller.context.highlights_store import get_highlight_for_dwarf
    fortress_dir = _get_fortress_dir(config, metadata)
    dwarf_highlight = get_highlight_for_dwarf(config, unit_id, output_dir=fortress_dir)

    # Mood description from stress_category
    _STRESS_DESCS_DETAIL = {
        0: "haggard",
        1: "very stressed",
        2: "stressed",
        3: "content",
        4: "pleased",
        5: "very happy",
        6: "ecstatic",
    }
    stress_cat = dwarf.stress_category if isinstance(dwarf.stress_category, int) else 3
    happiness_desc = _STRESS_DESCS_DETAIL.get(stress_cat, "content")

    dwarf_data = {
        "unit_id": dwarf.unit_id,
        "hist_figure_id": dwarf.hist_figure_id if dwarf.hist_figure_id > 0 else None,
        "name": dwarf.name,
        "profession": dwarf.profession,
        "sex": dwarf.sex,
        "age": dwarf.age,
        "noble_positions": dwarf.noble_positions,
        "military_squad": dwarf.military_squad,
        "stress_desc": happiness_desc if stress_cat in (0, 1, 2) else "",
        "happiness_desc": happiness_desc,
        "personality_traits": personality_traits,
        "beliefs": beliefs,
        "goals": goals,
        "physical_attrs": physical_attrs,
        "mental_attrs": mental_attrs,
        "skills": skills,
        "relationships": relationships,
        "equipment": dwarf.equipment,
        "wounds": dwarf.wounds,
        "pets": dwarf.pets,
        "is_alive": dwarf.is_alive,
        "highlight_role": dwarf_highlight.role.value if dwarf_highlight else "",
    }

    # Load events for this dwarf
    from df_storyteller.context.context_builder import _format_event
    dwarf_events = event_store.events_for_unit(unit_id)
    dwarf_data["events"] = [
        {
            "season": e.season.value.title(),
            "year": e.game_year,
            "type": e.event_type.value.replace("_", " ").title(),
            "description": re.sub(r"^\[.*?\]\s*", "", _format_event(e)),
        }
        for e in reversed(dwarf_events[-20:])
    ]

    # Build timeline: all events grouped by (year, season) in chronological order
    _TIMELINE_ICONS = {
        "combat": "sword", "death": "skull", "mood": "star", "artifact": "gem",
        "birth": "baby", "migrant_arrived": "footsteps", "profession_change": "scroll",
        "noble_appointment": "crown", "stress_change": "heart", "military_change": "shield",
        "building": "hammer", "season_change": "calendar",
    }
    _timeline_grouped: dict[tuple[int, str], list[dict]] = _defaultdict(list)
    for e in dwarf_events:
        desc = re.sub(r"^\[.*?\]\s*", "", _format_event(e))
        desc = re.sub(r"^[A-Za-z_ ]+:\s", "", desc)
        if not desc.strip():
            continue
        _timeline_grouped[(e.game_year, e.season.value)].append({
            "type": e.event_type.value.replace("_", " ").title(),
            "icon": _TIMELINE_ICONS.get(e.event_type.value, "circle"),
            "description": desc,
        })
    dwarf_data["timeline_events"] = [
        {"year": year, "season": season.title(), "events": evts}
        for (year, season), evts in sorted(
            _timeline_grouped.items(),
            key=lambda x: (x[0][0], SEASON_ORDER_MAP.get(x[0][1], 0)),
        )
    ]

    # Combat highlights for this dwarf
    from df_storyteller.schema.events import EventType as ET
    combat_highlights = []
    for e in reversed(dwarf_events):
        if e.event_type != ET.COMBAT:
            continue
        d = e.data
        is_attacker = hasattr(d, "attacker") and d.attacker.unit_id == unit_id
        opponent = d.defender.name if is_attacker else d.attacker.name if hasattr(d, "attacker") else "Unknown"
        combat_highlights.append({
            "role": "attacker" if is_attacker else "defender",
            "opponent": opponent,
            "weapon": getattr(d, "weapon", ""),
            "blow_count": getattr(d, "blow_count", 0) or (len(d.blows) if hasattr(d, "blows") else 0),
            "injuries": getattr(d, "injuries", []),
            "outcome": getattr(d, "outcome", ""),
            "is_lethal": getattr(d, "is_lethal", False),
            "season": e.season.value.title(),
            "year": e.game_year,
            "body_parts": list({b.body_part for b in d.blows if b.body_part}) if hasattr(d, "blows") else [],
        })
        if len(combat_highlights) >= 10:
            break
    dwarf_data["combat_highlights"] = combat_highlights

    # Load biography history (dated entries) with name hotlinks
    fortress_dir = _get_fortress_dir(config, metadata)
    from df_storyteller.stories.biography import load_biography_history
    bio_history = load_biography_history(config, dwarf.unit_id, fortress_dir)
    name_map = _build_dwarf_name_map(character_tracker)
    for entry in bio_history:
        if entry.get("text"):
            entry["text"] = _linkify_dwarf_names(
                entry["text"].replace("\n", "<br>"), name_map
            )
    dwarf_data["bio_entries"] = [e for e in bio_history if not e.get("is_diary")]
    dwarf_data["diary_entries"] = [e for e in bio_history if e.get("is_diary")]
    dwarf_data["has_eulogy"] = any(e.get("is_eulogy") for e in bio_history)

    # Load notes for this dwarf
    from df_storyteller.context.notes_store import get_notes_for_dwarf
    from df_storyteller.schema.notes import TAG_DESCRIPTIONS
    dwarf_notes = get_notes_for_dwarf(config, unit_id, fortress_dir)
    # Include resolved notes too for display
    from df_storyteller.context.notes_store import load_all_notes
    all_dwarf_notes = [
        n for n in load_all_notes(config, fortress_dir)
        if n.target_type == "dwarf" and n.target_id == unit_id
    ]

    return templates.TemplateResponse(request=request, name="dwarf_detail.html", context={
        **ctx, "content_class": "content-wide", "dwarf": dwarf_data, "notes": all_dwarf_notes, "tag_descriptions": TAG_DESCRIPTIONS,
    })
