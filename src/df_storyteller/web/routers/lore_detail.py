"""Lore detail page routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    base_context as _base_context,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)
router = APIRouter()


_TYPE_LABELS = {
    "migratinggroup": "migrating group",
    "nomadicgroup": "nomadic group",
    "merchantcompany": "merchant company",
    "outcast": "outcast group",
    "guild": "guild",
    "militia": "militia",
    "militaryunit": "military unit",
    "performancetroupe": "performance troupe",
    "sitegovernment": "site government",
    "religion": "religion",
}


def _build_sub_entities(legends: Any, civ: Any) -> list[str]:
    """Build a concise list of sub-entities for inline display."""
    data = _build_sub_entities_structured(legends, civ)
    result: list[str] = []
    for deity in data["deities"]:
        result.append(f'Worships {deity["name"]}' + (f' ({deity["spheres"]})' if deity["spheres"] else ''))
    for gt, count in data["group_counts"].items():
        result.append(f'{count} {gt}{"s" if count > 1 else ""}')
    for g in data["named_groups"]:
        result.append(g)
    return result


def _build_sub_entities_structured(legends: Any, civ: Any) -> dict:
    """Build structured sub-entity data for rich template rendering."""
    from collections import defaultdict, Counter

    child_ids = getattr(civ, '_child_ids', [])
    deity_groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "spheres": "", "deity_name": "", "deity_id": None})
    group_type_counts: Counter[str] = Counter()
    named_groups: list[str] = []
    guilds: list[dict] = []

    for child_id in child_ids:
        child_civ = legends.get_civilization(child_id)
        if not child_civ or not child_civ.name:
            continue
        child_type = getattr(child_civ, '_entity_type', '')
        if child_type in ('civilization', 'sitegovernment', ''):
            continue

        worship_id = getattr(child_civ, '_worship_id', None)
        profession = getattr(child_civ, '_profession', '')

        if child_type == 'religion' and worship_id:
            deity = legends.get_figure(worship_id)
            if deity:
                key = str(worship_id)
                deity_groups[key]["count"] += 1
                deity_groups[key]["deity_name"] = deity.name
                deity_groups[key]["deity_id"] = deity.hf_id
                deity_groups[key]["spheres"] = ', '.join(deity.spheres) if deity.spheres else ''
        elif child_type == 'guild':
            guilds.append({"name": child_civ.name, "profession": profession})
        elif child_type in ('nomadicgroup', 'migratinggroup', 'outcast', 'militaryunit'):
            type_label = _TYPE_LABELS.get(child_type, child_type)
            group_type_counts[type_label] += 1
        elif child_type == 'performancetroupe':
            group_type_counts["performance troupe"] += 1
        elif child_type == 'merchantcompany':
            group_type_counts["merchant company"] += 1
        else:
            type_label = _TYPE_LABELS.get(child_type, child_type.replace("_", " "))
            named_groups.append(f"{child_civ.name} ({type_label})")

    deities = sorted(deity_groups.values(), key=lambda x: x["count"], reverse=True)
    return {
        "deities": [{"name": d["deity_name"], "deity_id": d["deity_id"], "spheres": d["spheres"], "order_count": d["count"]} for d in deities],
        "guilds": guilds,
        "group_counts": dict(group_type_counts.most_common()),
        "named_groups": named_groups,
    }


def _build_figure_sidebar(legends: Any, hf: Any, hf_id: int, kills: list[dict], raw_events: list[dict]) -> dict:
    """Build sidebar data for a figure detail page using actual relationships and events."""
    related: dict[int, dict] = {}  # hf_id -> {name, hf_id, reason, priority}

    def _add(fid: int, reason: str, priority: int) -> None:
        if fid == hf_id:
            return
        f = legends.get_figure(fid)
        if not f or not f.name:
            return
        if fid not in related or related[fid]["priority"] < priority:
            related[fid] = {"name": f.name, "hf_id": f.hf_id, "reason": reason, "priority": priority}

    # 1. Family (highest priority)
    family = legends.get_hf_family(hf_id)
    for pid in family["parents"]:
        _add(pid, "parent", 10)
    for cid in family["children"]:
        _add(cid, "child", 10)
    for sid in family["spouse"]:
        _add(sid, "spouse", 10)
    # Siblings via shared parents
    for pid in family["parents"]:
        p_family = legends.get_hf_family(pid)
        for sib_id in p_family["children"]:
            _add(sib_id, "sibling", 9)

    # 2. Relationships (friends, rivals, lovers, etc.)
    hfid_str = str(hf_id)
    for rel in legends.get_hf_relationships(hf_id):
        rtype = rel.get("relationship", "")
        if rel.get("source_hf") == hfid_str:
            other_id = rel.get("target_hf")
        else:
            other_id = rel.get("source_hf")
        if other_id:
            try:
                priority = 8 if rtype in ("grudge", "jealous_obsession", "war_buddy") else 7
                _add(int(other_id), rtype.replace("_", " "), priority)
            except (ValueError, TypeError):
                pass

    # 3. Kill victims and slayer (high priority — direct interaction)
    for kill in kills:
        _add(kill["hf_id"], "killed by this figure", 9)
    # Check if this figure was killed by someone
    for evt in raw_events:
        if evt.get("type") == "hf died" and evt.get("hfid") == hfid_str and evt.get("slayer_hfid"):
            try:
                _add(int(evt["slayer_hfid"]), "killed this figure", 9)
            except (ValueError, TypeError):
                pass

    # 4. Vague relationships (acquaintance, war buddy, etc.)
    for vr in hf.vague_relationships:
        vr_hfid = vr.get("hfid")
        if vr_hfid:
            vr_type = vr.get("type", "acquaintance")
            _add(vr_hfid, vr_type, 4)

    # 5. Figures involved in shared events (battles, confrontations)
    for evt in raw_events:
        etype = evt.get("type", "")
        if etype == "hf simple battle event":
            for key in ("group_1_hfid", "group_2_hfid"):
                other = evt.get(key)
                if other and other != hfid_str:
                    try:
                        _add(int(other), "fought in battle", 5)
                    except (ValueError, TypeError):
                        pass
        elif etype == "hf wounded":
            for key in ("woundee_hfid", "wounder_hfid"):
                other = evt.get(key)
                if other and other != hfid_str:
                    try:
                        _add(int(other), "combat wound", 6)
                    except (ValueError, TypeError):
                        pass
        elif etype == "hf abducted":
            for key in ("target_hfid", "snatcher_hfid"):
                other = evt.get(key)
                if other and other != hfid_str:
                    try:
                        _add(int(other), "abduction", 6)
                    except (ValueError, TypeError):
                        pass

    # Sort by priority descending, take top 20
    sorted_related = sorted(related.values(), key=lambda r: r["priority"], reverse=True)[:20]

    # Build sidebar sites from figure's civ
    sidebar_sites: list[dict] = []
    if hf.associated_civ_id:
        for s in legends.sites.values():
            if s.owner_civ_id == hf.associated_civ_id and s.name:
                sidebar_sites.append({"name": s.name, "site_id": s.site_id})
                if len(sidebar_sites) >= 10:
                    break

    # Build sidebar civs
    sidebar_civs: list[dict] = []
    if hf.associated_civ_id:
        civ = legends.get_civilization(hf.associated_civ_id)
        if civ:
            sidebar_civs.append({"name": civ.name, "entity_id": civ.entity_id})

    # Build sidebar wars from civ
    sidebar_wars: list[dict] = []
    if hf.associated_civ_id:
        for war in legends.get_wars_involving(hf.associated_civ_id)[:8]:
            sidebar_wars.append({"name": war.get("name", "?"), "id": war.get("id", "")})

    return {
        "sidebar_figures": sorted_related[:10],
        "sidebar_civs": sidebar_civs,
        "sidebar_sites": sidebar_sites[:5],
        "sidebar_wars": sidebar_wars[:5],
        "sidebar_artifacts": [{"name": a.name, "artifact_id": a.artifact_id}
                              for a in legends.artifacts.values()
                              if a.creator_hf_id == hf_id and a.name][:5],
        "sidebar_events": [],
    }


def _build_figure_context(legends: Any, hf_id: int) -> dict | None:
    """Build template context for a historical figure detail page."""
    from collections import Counter
    from df_storyteller.context.event_renderer import describe_event_linked as describe_event
    from df_storyteller.context.narrative_formatter import _skill_level_name

    hf = legends.get_figure(hf_id)
    if not hf:
        return None

    figure = {
        "name": hf.name,
        "race": hf.race.replace("_", " ").title() if hf.race else "",
        "caste": hf.caste.replace("_", " ").title() if hf.caste else "",
        "hf_type": hf.hf_type.replace("_", " ").title() if hf.hf_type else "",
        "birth_year": hf.birth_year if hf.birth_year and hf.birth_year > 0 else None,
        "death_year": hf.death_year if hf.death_year and hf.death_year > 0 else None,
        "death_cause": "",
        "death_slayer": "",
        "death_slayer_id": None,
        "spheres": hf.spheres,
        "is_deity": hf.is_deity,
        "hf_id": hf.hf_id,
    }

    # Death details
    if hf.death_year and hf.death_year > 0:
        hfid_str_death = str(hf_id)
        for evt in legends.get_hf_events(hf_id):
            if evt.get("type") == "hf died" and evt.get("hfid") == hfid_str_death:
                cause = evt.get("cause", "").replace("_", " ")
                if cause:
                    figure["death_cause"] = cause
                slayer_hfid = evt.get("slayer_hfid")
                if slayer_hfid and slayer_hfid != "-1":
                    slayer = legends.get_figure(int(slayer_hfid))
                    if slayer:
                        figure["death_slayer"] = slayer.name
                        figure["death_slayer_id"] = slayer.hf_id
                elif evt.get("slayer_race"):
                    race = evt["slayer_race"].replace("_", " ").title()
                    caste = evt.get("slayer_caste", "").replace("_", " ").lower()
                    figure["death_slayer"] = f"a {caste} {race}".strip() if caste and caste != "default" else f"a {race}"
                break

    # Civilization
    civ_name = civ_id = None
    if hf.associated_civ_id:
        civ = legends.get_civilization(hf.associated_civ_id)
        if civ:
            civ_name = civ.name
            civ_id = civ.entity_id

    # Relationships
    hfid_str = str(hf_id)
    relationships = []
    for rel in legends.get_hf_relationships(hf_id):
        if rel.get("source_hf") == hfid_str:
            other = legends.get_figure(int(rel.get("target_hf", 0)))
            if other:
                relationships.append({"type": rel.get("relationship", "?"), "other_name": other.name, "other_id": other.hf_id})
        elif rel.get("target_hf") == hfid_str:
            other = legends.get_figure(int(rel.get("source_hf", 0)))
            if other:
                relationships.append({"type": rel.get("relationship", "?"), "other_name": other.name, "other_id": other.hf_id})

    # Events, kills, notable events summary
    raw_events = legends.get_hf_events(hf_id)
    evt_types: Counter[str] = Counter()
    kills: list[dict] = []
    for evt in raw_events:
        evt_types[evt.get("type", "unknown")] += 1
        if evt.get("type") == "hf died" and evt.get("slayer_hfid") == hfid_str:
            victim = legends.get_figure(int(evt.get("hfid", 0))) if evt.get("hfid") else None
            if victim:
                kills.append({"name": victim.name, "race": victim.race.replace("_", " ").title() if victim.race else "", "hf_id": victim.hf_id})

    readable_map = {
        "hf simple battle event": "battles",
        "hf attacked site": "site attacks", "artifact created": "artifacts created",
        "creature devoured": "devoured victims", "hf wounded": "wounds inflicted",
        "hf confronted": "confrontations", "assume identity": "assumed identities",
    }
    summary_parts = []
    # Show kills separately (only actual kills, not own death)
    if kills:
        summary_parts.append(f"{len(kills)} kill{'s' if len(kills) != 1 else ''}")
    for et, count in evt_types.most_common(10):
        if et in readable_map:
            summary_parts.append(f"{count} {readable_map[et]}")
        if len(summary_parts) >= 5:
            break

    # Artifacts created by this figure
    artifacts = []
    for aid, art in legends.artifacts.items():
        if art.creator_hf_id == hf_id and art.name:
            artifacts.append({"name": art.name, "artifact_id": art.artifact_id})

    # Entity positions held + affiliations
    entity_positions = []
    affiliations = []
    seen_affiliations: set[int] = set()
    for link in hf.entity_links:
        link_type = link.get("type", "").replace("_", " ")
        ent_id = link.get("entity_id")
        ent_name = ""
        ent_obj = None
        if ent_id:
            ent_obj = legends.get_civilization(ent_id)
            if ent_obj:
                ent_name = ent_obj.name
        if link_type and ent_name:
            entity_positions.append(f"{link_type} of {ent_name}")
        elif link_type:
            entity_positions.append(link_type)
        # Build affiliations (unique entities this figure is linked to)
        if ent_id and ent_id not in seen_affiliations and ent_name:
            seen_affiliations.add(ent_id)
            ent_type = getattr(ent_obj, '_entity_type', '') if ent_obj else ''
            ent_type_display = ent_type.replace("_", " ").title() if ent_type else ""
            affiliations.append({
                "entity_id": ent_id,
                "name": ent_name,
                "link_type": link_type,
                "entity_type": ent_type_display,
            })

    # Skills (format nicely)
    # Convert total_ip to approximate skill level
    _IP_THRESHOLDS = [0, 500, 1100, 1800, 2600, 3500, 4600, 5800, 7200, 8800, 10600, 12600, 14900, 17400, 20200, 23300]
    def _ip_to_level(ip: int) -> int:
        for lvl in range(len(_IP_THRESHOLDS) - 1, -1, -1):
            if ip >= _IP_THRESHOLDS[lvl]:
                return lvl
        return 0

    skill_strs = []
    for sk in sorted(hf.skills, key=lambda s: s.get("total_ip", 0), reverse=True)[:15]:
        skill_name = sk.get("skill", "").replace("_", " ").title()
        if skill_name:
            ip = sk.get("total_ip", 0)
            level_num = _ip_to_level(ip)
            level_name = _skill_level_name(level_num)
            skill_strs.append({"name": skill_name, "level": level_name, "level_num": level_num})

    # Active interactions (curses, secrets, powers)
    def _describe_interaction(raw: str) -> str:
        lower = raw.lower()
        if "secret_undead_res" in lower:
            return "Necromancy — can raise the dead"
        if "secret" in lower:
            return "Holds a dark secret (night creature power)"
        if "mythical" in lower:
            return "Granted a supernatural power by a deity"
        return raw.replace("_", " ").title()
    interactions = [_describe_interaction(ai) for ai in hf.active_interactions]

    # Journey pets
    pets = [p.replace("_", " ").title() for p in hf.journey_pets]

    # Intrigue plots
    intrigue_plots: list[dict] = []
    for plot in hf.intrigue_plots:
        actors_out: list[dict] = []
        for actor in plot.get("actors", []):
            actor_hfid = actor.get("hfid")
            actor_name = ""
            if actor_hfid:
                af = legends.get_figure(actor_hfid)
                if af:
                    actor_name = af.name
            actors_out.append({
                "name": actor_name,
                "hf_id": actor_hfid,
                "role": actor.get("role", "").replace("_", " "),
                "strategy": actor.get("strategy", "").replace("_", " "),
                "promised_immortality": actor.get("promised_immortality", False),
            })
        intrigue_plots.append({
            "type": plot.get("type", "").replace("_", " ").title(),
            "on_hold": plot.get("on_hold", False),
            "actors": actors_out,
        })

    # Emotional bonds (sorted by intensity)
    emotional_bonds: list[dict] = []
    for bond in hf.emotional_bonds:
        love = bond.get("love", 0)
        respect = bond.get("respect", 0)
        trust = bond.get("trust", 0)
        loyalty = bond.get("loyalty", 0)
        fear = bond.get("fear", 0)
        intensity = abs(love) + abs(respect) + abs(trust) + abs(loyalty) + abs(fear)
        if intensity == 0:
            continue
        bond_hfid = bond.get("hf_id")
        bond_name = ""
        if bond_hfid:
            bf = legends.get_figure(bond_hfid)
            if bf:
                bond_name = bf.name
        emotional_bonds.append({
            "name": bond_name,
            "hf_id": bond_hfid,
            "love": love,
            "respect": respect,
            "trust": trust,
            "loyalty": loyalty,
            "fear": fear,
            "_intensity": intensity,
        })
    emotional_bonds.sort(key=lambda b: b["_intensity"], reverse=True)

    # Former positions
    former_positions: list[dict] = []
    for fp in hf.former_positions:
        fp_eid = fp.get("entity_id")
        fp_civ_name = ""
        position_title = ""
        if fp_eid:
            fp_civ = legends.get_civilization(fp_eid)
            if fp_civ:
                fp_civ_name = fp_civ.name
                # Resolve position_profile_id to title
                ppid = fp.get("position_profile_id")
                if ppid:
                    for ep in getattr(fp_civ, '_entity_positions', []):
                        if str(ep.get("id", "")) == str(ppid):
                            position_title = ep.get("name", "") or ep.get("name_male", "") or ep.get("name_female", "")
                            break
        former_positions.append({
            "position": position_title.replace("_", " ").title() if position_title else f"Position #{fp.get('position_profile_id', '?')}",
            "civ_name": fp_civ_name,
            "civ_id": fp_eid,
            "start_year": fp.get("start_year", "?"),
            "end_year": fp.get("end_year", "?"),
        })

    # Describe events
    events_described = sorted(
        [{"year": evt.get("year", "?"), "description": describe_event(evt, legends)} for evt in raw_events],
        key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0,
    )

    return {
        "figure": figure,
        "civ_name": civ_name,
        "civ_id": civ_id,
        "relationships": relationships,
        "events": events_described,
        "kills": kills,
        "artifacts": artifacts,
        "notable_events_summary": ", ".join(summary_parts) if summary_parts else "",
        "event_count": len(raw_events),
        "deeds": hf.notable_deeds[:10] if hf.notable_deeds else [],
        "entity_positions": entity_positions,
        "affiliations": affiliations,
        "active_interactions": interactions,
        "skills": skill_strs,
        "journey_pets": pets,
        "intrigue_plots": intrigue_plots if intrigue_plots else [],
        "emotional_bonds": emotional_bonds if emotional_bonds else [],
        "former_positions": former_positions if former_positions else [],
        # Sidebar: related figures from relationships, family, kills, shared events
        **_build_figure_sidebar(legends, hf, hf_id, kills, raw_events),
        "pin_entity": {"type": "figure", "id": hf_id, "name": hf.name},
    }


def _build_festivals(legends: Any, civ: Any, entity_id: int, event_by_id: dict) -> list[dict]:
    """Build structured festival data from occasion definitions and historical events."""
    from df_storyteller.context.dwarven_calendar import format_date_range, ticks_to_date

    occasion_defs = getattr(civ, '_occasions', [])
    if not occasion_defs:
        return []

    eid_str = str(entity_id)

    # Gather all occasion events for this civ, grouped by occasion_id
    from collections import defaultdict
    occasion_events: dict[str, list[dict]] = defaultdict(list)
    for ec in legends.event_collections:
        if ec.get("type") == "occasion" and str(ec.get("civ_id", "")) == eid_str:
            occasion_events[str(ec.get("occasion_id", "0"))].append(ec)

    festivals = []
    for occ_def in occasion_defs:
        occ_id = str(occ_def.get("id", "0"))
        occ_name = occ_def.get("name", f"Festival #{occ_id}")
        events = occasion_events.get(occ_id, [])

        if not events:
            # Festival defined but never held — still show the definition
            schedules = []
            for sched in occ_def.get("schedules", []):
                stype = sched.get("type", "").replace("_", " ").title()
                features = [f.replace("_", " ") for f in sched.get("features", [])]
                item = ""
                if sched.get("item_subtype"):
                    item = sched["item_subtype"].replace("_", " ")
                elif sched.get("item_type"):
                    item = sched["item_type"].replace("_", " ")
                schedules.append({"type": stype, "features": features, "item": item})
            festivals.append({
                "name": occ_name,
                "occasion_id": occ_id,
                "date": "",
                "month": "",
                "season": "",
                "held_count": 0,
                "first_year": None,
                "last_year": None,
                "site_name": "",
                "site_id": None,
                "schedules": schedules,
                "recent_winners": [],
            })
            continue

        # Get timing from first event
        first_evt = min(events, key=lambda e: int(e.get("start_year", 9999)))
        last_evt = max(events, key=lambda e: int(e.get("start_year", 0)))
        date_str = format_date_range(first_evt.get("start_seconds72"), first_evt.get("end_seconds72"))
        date_info = ticks_to_date(first_evt.get("start_seconds72"))

        # Get site from sub-events
        site_name = ""
        site_id = None
        sub_ids = first_evt.get("eventcol", [])
        if isinstance(sub_ids, str):
            sub_ids = [sub_ids]
        if isinstance(sub_ids, list):
            for sid in sub_ids:
                sub = legends.get_event_collection(sid)
                if sub:
                    sub_evts = sub.get("event", [])
                    if not isinstance(sub_evts, list):
                        sub_evts = [sub_evts]
                    for seid in sub_evts[:1]:
                        evt = event_by_id.get(str(seid))
                        if evt and evt.get("site_id") and evt["site_id"] != "-1":
                            try:
                                s = legends.get_site(int(evt["site_id"]))
                                if s:
                                    site_name = s.name
                                    site_id = s.site_id
                            except (ValueError, TypeError):
                                pass
                    if site_name:
                        break

        # Build schedule from definitions
        schedules = []
        for sched in occ_def.get("schedules", []):
            stype = sched.get("type", "").replace("_", " ").title()
            features = [f.replace("_", " ") for f in sched.get("features", [])]
            item = ""
            if sched.get("item_subtype"):
                item = sched["item_subtype"].replace("_", " ")
            elif sched.get("item_type"):
                item = sched["item_type"].replace("_", " ")
            schedules.append({"type": stype, "features": features, "item": item})

        # Find recent competition winners
        recent_winners: list[dict] = []
        recent_events = sorted(events, key=lambda e: int(e.get("start_year", 0)), reverse=True)[:10]
        for re_evt in recent_events:
            re_sub_ids = re_evt.get("eventcol", [])
            if isinstance(re_sub_ids, str):
                re_sub_ids = [re_sub_ids]
            if not isinstance(re_sub_ids, list):
                continue
            for sid in re_sub_ids:
                sub = legends.get_event_collection(sid)
                if sub and sub.get("type") == "competition":
                    comp_evts = sub.get("event", [])
                    if not isinstance(comp_evts, list):
                        comp_evts = [comp_evts]
                    for ceid in comp_evts:
                        cevt = event_by_id.get(str(ceid))
                        if cevt and cevt.get("winner_hfid"):
                            try:
                                w = legends.get_figure(int(cevt["winner_hfid"]))
                                if w:
                                    # Find competition type from schedule definitions
                                    comp_type = "Competition"
                                    sched_id = cevt.get("schedule_id", "")
                                    for sched_def in occ_def.get("schedules", []):
                                        if str(sched_def.get("id", "")) == str(sched_id):
                                            comp_type = sched_def.get("type", "competition").replace("_", " ").title()
                                            item = sched_def.get("item_subtype", sched_def.get("item_type", ""))
                                            if item:
                                                comp_type += f" ({item.replace('_', ' ')})"
                                            break
                                    recent_winners.append({
                                        "year": re_evt.get("start_year", "?"),
                                        "name": w.name,
                                        "hf_id": w.hf_id,
                                        "comp_type": comp_type,
                                    })
                            except (ValueError, TypeError):
                                pass
                            break
                if recent_winners and recent_winners[-1].get("year") == re_evt.get("start_year"):
                    break
            if len(recent_winners) >= 5:
                break

        festivals.append({
            "name": occ_name,
            "occasion_id": occ_id,
            "date": date_str,
            "month": date_info["month"] if date_info else "",
            "season": date_info["season"] if date_info else "",
            "held_count": len(events),
            "first_year": first_evt.get("start_year"),
            "last_year": last_evt.get("start_year"),
            "site_name": site_name,
            "site_id": site_id,
            "schedules": schedules,
            "recent_winners": recent_winners,
        })

    # Filter out empty festivals (held once or never, no schedules)
    festivals = [f for f in festivals if f["held_count"] > 1 or f["schedules"]]
    # Sort by held_count descending (most active festivals first)
    festivals.sort(key=lambda f: f["held_count"], reverse=True)
    return festivals


def _build_civ_sidebar_civs(legends: Any, entity_id: int, wars: list[dict]) -> list[dict]:
    """Build sidebar civilizations: opponents from wars."""
    seen: set[int] = {entity_id}
    result: list[dict] = []
    eid_str = str(entity_id)
    for war in legends.get_wars_involving(entity_id)[:10]:
        for key in ("aggressor_ent_id", "defender_ent_id"):
            ids = war.get(key, [])
            if isinstance(ids, str):
                ids = [ids]
            for oid in ids:
                try:
                    oid_int = int(oid)
                    if oid_int not in seen:
                        seen.add(oid_int)
                        c = legends.get_civilization(oid_int)
                        if c and c.name:
                            result.append({"name": c.name, "entity_id": c.entity_id})
                except (ValueError, TypeError):
                    pass
        if len(result) >= 5:
            break
    return result


def _build_civ_sidebar_artifacts(legends: Any, entity_id: int) -> list[dict]:
    """Build sidebar artifacts: created by figures in this civ."""
    result: list[dict] = []
    civ_hf_ids = {hfid for hfid, hf in legends.historical_figures.items() if hf.associated_civ_id == entity_id}
    for aid, art in legends.artifacts.items():
        if art.creator_hf_id in civ_hf_ids and art.name:
            result.append({"name": art.name, "artifact_id": art.artifact_id})
            if len(result) >= 5:
                break
    return result


def _build_civ_context(legends: Any, entity_id: int) -> dict | None:
    """Build template context for a civilization detail page."""
    from df_storyteller.context.narrative_formatter import _skill_level_name

    civ = legends.get_civilization(entity_id)
    if not civ:
        return None

    # Sites
    sites = []
    for sid in civ.sites:
        site = legends.get_site(sid)
        if site:
            sites.append({"name": site.name, "site_type": site.site_type or "unknown", "site_id": site.site_id})

    # Wars
    wars = []
    for war in legends.get_wars_involving(entity_id):
        sy = war.get("start_year", "")
        ey = war.get("end_year", "")
        year_range = f"Year {sy}" + (f"–{ey}" if ey and ey != sy else "") if sy else ""
        wars.append({"name": war.get("name", "Unknown"), "years": year_range, "id": war.get("id", "")})

    # Leaders
    leaders = []
    for lid in civ.leader_hf_ids[:10]:
        lhf = legends.get_figure(lid)
        if lhf:
            leaders.append({"name": lhf.name, "hf_id": lhf.hf_id})

    # Sub-entities (grouped by deity to avoid massive lists)
    sub_entities = _build_sub_entities(legends, civ)

    # Notable figures belonging to this civ
    notable_figures = []
    for hfid, hf in legends.historical_figures.items():
        if hf.associated_civ_id == entity_id and hf.name:
            evt_count = legends.get_hf_event_count(hfid)
            if evt_count > 0:
                notable_figures.append({"name": hf.name, "race": hf.race.replace("_", " ").title() if hf.race else "",
                                        "hf_id": hf.hf_id, "description": f"{evt_count} events"})
    notable_figures.sort(key=lambda f: int(f["description"].split()[0]), reverse=True)

    # Count events: at civ's sites + event collections involving this civ
    event_count = 0
    for sid in civ.sites:
        site_evts = legends.get_site_event_types(sid)
        event_count += sum(site_evts.values())
    # Also count from event collections (wars, thefts, etc.)
    eid_str_for_count = str(entity_id)
    for ec in legends.event_collections:
        for key in ("attacking_enid", "defending_enid", "target_entity_id", "civ_id"):
            val = ec.get(key)
            if val:
                if isinstance(val, list) and eid_str_for_count in val:
                    ec_events = ec.get("event", [])
                    event_count += len(ec_events) if isinstance(ec_events, list) else 1
                    break
                elif str(val) == eid_str_for_count:
                    ec_events = ec.get("event", [])
                    event_count += len(ec_events) if isinstance(ec_events, list) else 1
                    break

    # Entity populations — race counts for this civ
    populations = []
    for ep in legends.entity_populations:
        if str(ep.get("civ_id", "")) == str(entity_id):
            race_str = ep.get("race", "")
            # Format is "race_name:count"
            if ":" in race_str:
                race_name, count = race_str.rsplit(":", 1)
                race_name = race_name.replace("_", " ").title()
                try:
                    populations.append({"race": race_name, "count": int(count)})
                except ValueError:
                    pass
    populations.sort(key=lambda p: p["count"], reverse=True)

    # Event collections involving this civ (thefts, abductions, beast attacks, etc.)
    from collections import Counter as _Counter
    eid_str = str(entity_id)
    civ_event_collections: list[dict] = []
    ec_type_counts: _Counter[str] = _Counter()
    # Cultural events — build structured summary instead of listing individually
    _cultural_types = {"occasion", "competition", "performance", "ceremony", "procession", "journey"}
    occasions: list[dict] = []
    event_by_id = {str(e.get("id", "")): e for e in legends.historical_events}
    for ec in legends.event_collections:
        involved = False
        for key in ("attacking_enid", "defending_enid", "target_entity_id", "civ_id"):
            val = ec.get(key)
            if val:
                if isinstance(val, list) and eid_str in val:
                    involved = True; break
                elif str(val) == eid_str:
                    involved = True; break
        if involved:
            ec_type = ec.get("type", "unknown")
            ec_type_counts[ec_type] += 1
            # Capture occasion detail for cultural section
            if ec_type == "occasion" and len(occasions) < 100:
                sub_ids = ec.get("eventcol", [])
                if isinstance(sub_ids, str): sub_ids = [sub_ids]
                sub_types: _Counter[str] = _Counter()
                if isinstance(sub_ids, list):
                    for sid in sub_ids:
                        sub = legends.get_event_collection(sid)
                        if sub:
                            sub_types[sub.get("type", "?")] += 1
                site_id = None
                site_name = ""
                # Get site from first sub-event
                if isinstance(sub_ids, list) and sub_ids:
                    sub = legends.get_event_collection(sub_ids[0])
                    if sub and sub.get("site_id") and sub["site_id"] != "-1":
                        try:
                            s = legends.get_site(int(sub["site_id"]))
                            if s:
                                site_name = s.name
                                site_id = s.site_id
                        except (ValueError, TypeError):
                            pass
                parts = [t.replace("_", " ") for t, _ in sub_types.most_common()]
                # Check for competition winner in sub-events
                comp_winner = ""
                comp_winner_id = None
                if isinstance(sub_ids, list):
                    for sid_c in sub_ids:
                        sub_c = legends.get_event_collection(sid_c)
                        if sub_c and sub_c.get("type") == "competition":
                            comp_evts = sub_c.get("event", [])
                            if not isinstance(comp_evts, list): comp_evts = [comp_evts]
                            for ceid in comp_evts:
                                cevt = event_by_id.get(str(ceid))
                                if cevt and cevt.get("winner_hfid"):
                                    try:
                                        w = legends.get_figure(int(cevt["winner_hfid"]))
                                        if w:
                                            comp_winner = w.name
                                            comp_winner_id = w.hf_id
                                    except (ValueError, TypeError):
                                        pass
                                    break
                            break
                occasions.append({
                    "year": ec.get("start_year", "?"),
                    "site_name": site_name,
                    "site_id": site_id,
                    "sub_types": ", ".join(parts) if parts else "festival",
                    "comp_winner": comp_winner,
                    "comp_winner_id": comp_winner_id,
                })
            # Only list interesting events (skip cultural noise)
            if ec_type not in _cultural_types and len(civ_event_collections) < 50:
                ec_name = ec.get("name", "")
                if not ec_name or ec_name == ec_type.replace("_", " ").title():
                    # Build a more descriptive name
                    site_id = ec.get("site_id")
                    site_name = ""
                    if site_id and site_id != "-1":
                        try:
                            s = legends.get_site(int(site_id))
                            if s: site_name = s.name
                        except (ValueError, TypeError):
                            pass
                    year = ec.get("start_year", "")
                    ec_name = ec_type.replace("_", " ").title()
                    if site_name:
                        ec_name += f" at {site_name}"
                    if year:
                        ec_name += f" (year {year})"
                civ_event_collections.append({
                    "id": ec.get("id", ""),
                    "name": ec_name,
                    "type": ec_type.replace("_", " ").title(),
                    "year": ec.get("start_year", ""),
                })

    # Format event collection type summary — separate interesting from cultural
    _interesting_summary = []
    _cultural_summary = []
    for t, c in ec_type_counts.most_common():
        label = t.replace("_", " ")
        if c > 1:
            label += "s"
        entry = f"{c} {label}"
        if t in _cultural_types:
            _cultural_summary.append(entry)
        else:
            _interesting_summary.append(entry)
    ec_summary = ", ".join(_interesting_summary)
    cultural_summary = ", ".join(_cultural_summary)

    # Honors / rank system
    _IP_THRESHOLDS_CIV = [0, 500, 1100, 1800, 2600, 3500, 4600, 5800, 7200, 8800, 10600, 12600, 14900, 17400, 20200, 23300]
    def _ip_to_level_civ(ip: int) -> int:
        for lvl in range(len(_IP_THRESHOLDS_CIV) - 1, -1, -1):
            if ip >= _IP_THRESHOLDS_CIV[lvl]:
                return lvl
        return 0

    honors: list[dict] = []
    for hon in getattr(civ, '_honors', []):
        required_skill = hon.get("required_skill", "").replace("_", " ").title()
        required_ip = hon.get("required_skill_ip_total", 0)
        required_level = _skill_level_name(_ip_to_level_civ(required_ip)) if required_ip else None
        required_battles = hon.get("required_battles")
        honors.append({
            "name": hon.get("name", "Unknown"),
            "required_skill": required_skill if required_skill else None,
            "required_level": required_level,
            "required_battles": required_battles,
            "precedence": hon.get("gives_precedence", 0),
        })
    honors.sort(key=lambda h: h["precedence"], reverse=True)

    return {
        "civ": {"name": civ.name, "race": civ.race.replace("_", " ").title() if civ.race else "", "entity_id": entity_id},
        "sites": sites,
        "wars": wars,
        "leaders": leaders,
        "sub_entities": sub_entities[:15],
        "notable_figures": notable_figures[:200],
        "event_count": event_count,
        "populations": populations,
        "civ_event_collections": civ_event_collections,
        "ec_summary": ec_summary,
        "cultural_summary": cultural_summary,
        "occasions": occasions,
        "festivals": _build_festivals(legends, civ, entity_id, event_by_id),
        "honors": honors,
        # Sidebar — diverse mix of related entities
        "sidebar_figures": ([{"name": f["name"], "hf_id": f["hf_id"]} for f in notable_figures[:5]]
                            + [{"name": l["name"], "hf_id": l["hf_id"]} for l in leaders[:5]
                               if not any(f["hf_id"] == l["hf_id"] for f in notable_figures[:5])])[:8],
        "sidebar_civs": _build_civ_sidebar_civs(legends, entity_id, wars),
        "sidebar_sites": sites[:5],
        "sidebar_wars": wars[:5],
        "sidebar_artifacts": _build_civ_sidebar_artifacts(legends, entity_id),
        "sidebar_events": [{"id": ec["id"], "name": ec["name"]} for ec in civ_event_collections[:5] if ec.get("name")],
        "pin_entity": {"type": "civilization", "id": entity_id, "name": civ.name},
    }


def _build_site_context(legends: Any, site_id: int) -> dict | None:
    """Build template context for a site detail page."""
    from df_storyteller.context.event_renderer import describe_event_linked as describe_event

    site = legends.get_site(site_id)
    if not site:
        return None

    owner_name = owner_id = None
    if site.owner_civ_id:
        owner = legends.get_civilization(site.owner_civ_id)
        if owner:
            owner_name = owner.name
            owner_id = owner.entity_id

    coords_str = f"({site.coordinates[0]}, {site.coordinates[1]})" if site.coordinates else None
    event_types = legends.get_site_event_types(site_id)
    total_events = sum(event_types.values())

    # Get actual events at this site
    site_events = []
    for evt in legends.historical_events:
        sid = evt.get("site_id")
        if sid and sid != "-1":
            try:
                if int(sid) == site_id:
                    site_events.append(evt)
            except (ValueError, TypeError):
                pass
        if len(site_events) >= 200:
            break

    events_described = sorted(
        [{"year": evt.get("year", "?"), "description": describe_event(evt, legends)} for evt in site_events],
        key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0,
    )

    # Make event type labels readable
    readable_types = {}
    for et, count in event_types.items():
        readable_types[et.replace("_", " ").replace("hf ", "").title()] = count

    # Structures at this site
    structures = []
    for struct in site.structures:
        s = {"name": struct.get("name", ""), "type": struct.get("type", "").replace("_", " ").title()}
        deity_id = struct.get("deity_hf_id")
        if deity_id:
            deity = legends.get_figure(deity_id)
            if deity:
                s["deity"] = deity.name
                s["deity_id"] = deity.hf_id
        structures.append(s)

    # Site properties (houses, workshops, etc.)
    from collections import Counter as _PropCounter
    site_properties: list[dict] = []
    prop_type_counts: _PropCounter[str] = _PropCounter()
    prop_owned_counts: _PropCounter[str] = _PropCounter()
    for prop in site.properties:
        ptype = prop.get("type", "unknown").replace("_", " ")
        prop_type_counts[ptype] += 1
        owner_hfid = prop.get("owner_hfid")
        prop_owner_name = None
        if owner_hfid:
            prop_owned_counts[ptype] += 1
            pf = legends.get_figure(owner_hfid)
            if pf:
                prop_owner_name = pf.name
        site_properties.append({
            "type": ptype,
            "owner_name": prop_owner_name,
            "owner_hf_id": owner_hfid,
        })
    # Build summary string
    summary_parts_site: list[str] = []
    for ptype, total in prop_type_counts.most_common():
        owned = prop_owned_counts.get(ptype, 0)
        label = f"{total} {ptype}{'s' if total != 1 else ''}"
        if owned > 0:
            label += f" ({owned} owned)"
        summary_parts_site.append(label)
    property_summary = ", ".join(summary_parts_site) if summary_parts_site else ""

    return {
        "site": {"name": site.name, "site_type": site.site_type.replace("_", " ").title() if site.site_type else "",
                 "site_id": site.site_id, "coordinates": coords_str},
        "owner_name": owner_name,
        "owner_id": owner_id,
        "event_types": readable_types,
        "total_events": total_events,
        "events": events_described,
        "structures": structures,
        "site_properties": site_properties if site_properties else [],
        "property_summary": property_summary,
        # Sidebar — figures who own property here, related sites, owner civ
        "sidebar_figures": [{"name": legends.get_figure(p.get("owner_hfid", 0)).name,
                             "hf_id": p["owner_hfid"]}
                            for p in site.properties
                            if p.get("owner_hfid") and legends.get_figure(p["owner_hfid"])][:5],
        "sidebar_civs": [{"name": owner_name, "entity_id": owner_id}] if owner_name else [],
        "sidebar_sites": [{"name": s.name, "site_id": s.site_id}
                          for s in legends.sites.values()
                          if s.owner_civ_id == site.owner_civ_id and s.site_id != site_id and s.name][:5] if site.owner_civ_id else [],
        "sidebar_wars": [],
        "sidebar_artifacts": [],
        "sidebar_events": [],
        "pin_entity": {"type": "site", "id": site_id, "name": site.name},
    }


def _build_artifact_context(legends: Any, artifact_id: int) -> dict | None:
    """Build template context for an artifact detail page."""
    art = legends.get_artifact(artifact_id)
    if not art:
        return None

    creator_name = creator_id = None
    if art.creator_hf_id:
        creator = legends.get_figure(art.creator_hf_id)
        if creator:
            creator_name = creator.name
            creator_id = creator.hf_id

    site_name = site_id = None
    if art.site_id:
        site = legends.get_site(art.site_id)
        if site:
            site_name = site.name
            site_id = site.site_id

    # Pages (for books)
    pages: list[dict] = []
    # Build written_content lookup by ID
    wc_by_id: dict[str, dict] = {}
    for wc in legends.written_contents:
        wc_id = str(wc.get("id", ""))
        if wc_id:
            wc_by_id[wc_id] = wc
    for page in art.pages:
        wc_id = str(page.get("written_content_id", ""))
        wc = wc_by_id.get(wc_id, {})
        wc_title = wc.get("title", "")
        wc_type = wc.get("type", "").replace("_", " ").title()
        pages.append({
            "page_number": page.get("page_number", 0),
            "title": wc_title if wc_title else f"Written Content #{wc_id}",
            "wc_type": wc_type,
            "wc_id": wc_id,
        })
    pages.sort(key=lambda p: p["page_number"])

    return {
        "artifact": {"name": art.name, "item_type": art.item_type.replace("_", " ") if art.item_type else "",
                      "material": art.material, "description": art.description, "artifact_id": art.artifact_id},
        "creator_name": creator_name,
        "creator_id": creator_id,
        "site_name": site_name,
        "site_id": site_id,
        "pages": pages,
    }


def _build_war_context(legends: Any, ec_id: str) -> dict | None:
    """Build template context for a war detail page."""
    ec = legends.get_event_collection(ec_id)
    if not ec:
        return None

    war = {
        "name": ec.get("name", "Unknown Conflict"),
        "type": ec.get("type", "conflict").replace("_", " ").title(),
        "start_year": ec.get("start_year", "?"),
        "end_year": ec.get("end_year"),
        "id": ec.get("id", ""),
    }

    # For battles, get aggressor/defender from parent war
    faction_source = ec
    if ec.get("type") == "battle" and ec.get("war_eventcol"):
        parent_war = legends.get_event_collection(ec["war_eventcol"])
        if parent_war:
            faction_source = parent_war
            war["parent_war_name"] = parent_war.get("name", "")
            war["parent_war_id"] = parent_war.get("id", "")

    def _resolve_factions(key: str) -> list[dict]:
        ids = faction_source.get(key, [])
        if isinstance(ids, str):
            ids = [ids]
        factions = []
        for eid_str in ids:
            try:
                c = legends.get_civilization(int(eid_str))
                if c:
                    factions.append({"name": c.name, "race": c.race.replace("_", " ").title() if c.race else "", "entity_id": c.entity_id})
            except (ValueError, TypeError):
                pass
        return factions

    aggressors = _resolve_factions("aggressor_ent_id")
    defenders = _resolve_factions("defender_ent_id")

    # Battles
    war_id = ec.get("id")
    war_battles = [b for b in legends.battles if b.get("war_eventcol") == war_id]
    total_atk = total_def = 0
    battles = []
    for b in war_battles:
        atk_d = b.get("attacking_squad_deaths", [])
        def_d = b.get("defending_squad_deaths", [])
        ad = sum(int(d) for d in atk_d if str(d).isdigit()) if isinstance(atk_d, list) else 0
        dd = sum(int(d) for d in def_d if str(d).isdigit()) if isinstance(def_d, list) else 0
        total_atk += ad
        total_def += dd
        battles.append({
            "name": b.get("name", "Unknown Battle"),
            "outcome": b.get("outcome", "").replace("_", " ").title() if b.get("outcome") else "",
            "year": b.get("start_year", "?"),
            "id": b.get("id", ""),
            "atk_casualties": ad,
            "def_casualties": dd,
        })

    def _resolve_combatants(key: str) -> list[dict]:
        hfids = ec.get(key, [])
        if isinstance(hfids, str):
            hfids = [hfids]
        combatants = []
        for hid in hfids[:10]:
            try:
                h = legends.get_figure(int(hid))
                if h:
                    combatants.append({"name": h.name, "hf_id": h.hf_id})
            except (ValueError, TypeError):
                pass
        return combatants

    return {
        "war": war,
        "aggressors": aggressors,
        "defenders": defenders,
        "battles": battles,
        "total_atk_casualties": total_atk,
        "total_def_casualties": total_def,
        "notable_attackers": _resolve_combatants("attacking_hfid"),
        "notable_defenders": _resolve_combatants("defending_hfid"),
    }


# ==================== Route handlers ====================


@router.get("/lore/figure/{hf_id}", response_class=HTMLResponse)
async def lore_figure_page(request: Request, hf_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_figure_context(world_lore._legends, hf_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_figure.html", context={**ctx, "content_class": "content-wide", **detail})


@router.get("/lore/civ/{entity_id}", response_class=HTMLResponse)
async def lore_civ_page(request: Request, entity_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_civ_context(world_lore._legends, entity_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_civ.html", context={**ctx, "content_class": "content-wide", **detail})


@router.get("/lore/site/{site_id}", response_class=HTMLResponse)
async def lore_site_page(request: Request, site_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_site_context(world_lore._legends, site_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_site.html", context={**ctx, "content_class": "content-wide", **detail})


@router.get("/lore/artifact/{artifact_id}", response_class=HTMLResponse)
async def lore_artifact_page(request: Request, artifact_id: int):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_artifact_context(world_lore._legends, artifact_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_artifact.html", context={**ctx, "content_class": "content-wide", **detail})


@router.get("/lore/war/{ec_id}", response_class=HTMLResponse)
async def lore_war_page(request: Request, ec_id: str):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    detail = _build_war_context(world_lore._legends, ec_id)
    if not detail:
        return RedirectResponse("/lore")

    return templates.TemplateResponse(request=request, name="lore_war.html", context={**ctx, "content_class": "content-wide", **detail})


@router.get("/lore/event/{ec_id}", response_class=HTMLResponse)
async def lore_event_collection_page(request: Request, ec_id: str):
    """Generic detail page for any event collection (duels, purges, abductions, etc.)."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    ec = legends.get_event_collection(ec_id)
    if not ec:
        return RedirectResponse("/lore")

    # If it's a war, redirect to the dedicated war page
    if ec.get("type") == "war":
        return RedirectResponse(f"/lore/war/{ec_id}")

    from df_storyteller.context.event_renderer import describe_event_linked

    # Build context
    ec_data: dict[str, Any] = {
        "name": ec.get("name", ""),
        "type": ec.get("type", "").replace("_", " ").title(),
        "adjective": ec.get("adjective", ""),
        "start_year": ec.get("start_year", "?"),
        "end_year": ec.get("end_year"),
        "site_id": None, "site_name": None,
        "attacker_name": None, "attacker_id": None,
        "defender_name": None, "defender_id": None,
        "target_name": None, "target_id": None,
        "attacking_hf_name": None, "attacking_hf_id": None,
        "defending_hf_name": None, "defending_hf_id": None,
        "parent_war": None, "parent_war_id": None,
    }

    # Resolve site
    site_id = ec.get("site_id")
    if site_id and site_id != "-1":
        try:
            site = legends.get_site(int(site_id))
            if site:
                ec_data["site_id"] = site.site_id
                ec_data["site_name"] = site.name
        except (ValueError, TypeError):
            pass

    # Resolve attacker/defender civs
    for role, key in [("attacker", "attacking_enid"), ("defender", "defending_enid")]:
        eid = ec.get(key)
        if eid and eid != "-1":
            try:
                c = legends.get_civilization(int(eid))
                if c:
                    ec_data[f"{role}_name"] = c.name
                    ec_data[f"{role}_id"] = c.entity_id
            except (ValueError, TypeError):
                pass

    # Resolve target entity (persecutions, coups)
    target_eid = ec.get("target_entity_id")
    if target_eid and target_eid != "-1":
        try:
            c = legends.get_civilization(int(target_eid))
            if c:
                ec_data["target_name"] = c.name
                ec_data["target_id"] = c.entity_id
        except (ValueError, TypeError):
            pass

    # Resolve attacker/defender HFs (duels)
    for role, key in [("attacking_hf", "attacking_hfid"), ("defending_hf", "defending_hfid")]:
        hfid = ec.get(key)
        if hfid:
            try:
                hf = legends.get_figure(int(hfid))
                if hf:
                    ec_data[f"{role}_name"] = hf.name
                    ec_data[f"{role}_id"] = hf.hf_id
            except (ValueError, TypeError):
                pass

    # Resolve parent war
    war_ec_id = ec.get("war_eventcol")
    if war_ec_id and war_ec_id != "-1":
        war_ec = legends.get_event_collection(war_ec_id)
        if war_ec:
            ec_data["parent_war"] = war_ec.get("name", "Unknown War")
            ec_data["parent_war_id"] = war_ec_id

    # Build a descriptive name if none exists
    if not ec_data["name"]:
        ec_type = ec_data["type"]
        parts = [ec_type]
        if ec_data.get("adjective"):
            parts = [f"{ec_data['adjective']} {ec_type}"]
        if ec_data.get("site_name"):
            parts.append(f"at {ec_data['site_name']}")
        if ec_data.get("attacker_name") and ec_data.get("defender_name"):
            parts.append(f"({ec_data['attacker_name']} vs {ec_data['defender_name']})")
        elif ec_data.get("attacking_hf_name") and ec_data.get("defending_hf_name"):
            parts.append(f"({ec_data['attacking_hf_name']} vs {ec_data['defending_hf_name']})")
        elif ec_data.get("target_name"):
            parts.append(f"against {ec_data['target_name']}")
        ec_data["name"] = " ".join(parts)

    # Resolve sub-events
    event_by_id = {str(e.get("id", "")): e for e in legends.historical_events}
    event_ids = ec.get("event", [])
    if not isinstance(event_ids, list):
        event_ids = [event_ids]

    events = []
    for eid in event_ids:
        evt = event_by_id.get(str(eid))
        if evt:
            events.append({
                "year": evt.get("year", "?"),
                "description": describe_event_linked(evt, legends),
            })

    return templates.TemplateResponse(request=request, name="lore_event_collection.html", context={
        **ctx, "content_class": "content-wide", "ec": ec_data, "events": events,
    })


@router.get("/lore/work/{wc_id}", response_class=HTMLResponse)
async def lore_written_work_page(request: Request, wc_id: str):
    """Detail page for a written work."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    wc = None
    for w in legends.written_contents:
        if str(w.get("id", "")) == str(wc_id):
            wc = w
            break
    if not wc:
        return RedirectResponse("/lore")

    # Resolve author
    author_name = author_id = author_civ = author_civ_id = None
    author_raw = wc.get("author")
    if author_raw:
        try:
            hf = legends.get_figure(int(author_raw))
            if hf:
                author_name = hf.name
                author_id = hf.hf_id
                if hf.associated_civ_id:
                    c = legends.get_civilization(hf.associated_civ_id)
                    if c:
                        author_civ = c.name
                        author_civ_id = c.entity_id
        except (ValueError, TypeError):
            pass

    # Find artifacts containing this work
    artifacts = []
    for aid, art in legends.artifacts.items():
        for page in art.pages:
            if str(page.get("written_content_id", "")) == str(wc_id):
                artifacts.append({"name": art.name, "artifact_id": art.artifact_id})
                break

    work = {
        "title": wc.get("title", "Untitled"),
        "form": wc.get("type", "").replace("_", " ").title() if wc.get("type") else "",
        "style": wc.get("style", "").split(":")[0].strip().title() if wc.get("style") else "",
        "page_count": wc.get("page_end", ""),
        "reference": wc.get("reference", "").strip() if wc.get("reference") else "",
        "author_name": author_name,
        "author_id": author_id,
        "author_civ": author_civ,
        "author_civ_id": author_civ_id,
        "artifacts": artifacts,
    }

    return templates.TemplateResponse(request=request, name="lore_written_work.html", context={
        **ctx, "content_class": "content-wide", "work": work,
    })


@router.get("/lore/festival/{civ_id}/{occasion_id}", response_class=HTMLResponse)
async def lore_festival_page(request: Request, civ_id: int, occasion_id: str):
    """Detail page for a civilization's festival."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    civ = legends.get_civilization(civ_id)
    if not civ:
        return RedirectResponse("/lore")

    event_by_id = {str(e.get("id", "")): e for e in legends.historical_events}
    festivals = _build_festivals(legends, civ, civ_id, event_by_id)

    festival = None
    for f in festivals:
        if str(f.get("occasion_id", "")) == str(occasion_id):
            festival = f
            break
    if not festival:
        return RedirectResponse(f"/lore/civ/{civ_id}")

    festival["civ_name"] = civ.name
    festival["civ_id"] = civ_id

    return templates.TemplateResponse(request=request, name="lore_festival.html", context={
        **ctx, "content_class": "content-wide", "festival": festival,
    })


@router.get("/lore/form/{form_type}/{form_id}", response_class=HTMLResponse)
async def lore_cultural_form_page(request: Request, form_type: str, form_id: str):
    """Detail page for a cultural form (poetic, musical, dance)."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)

    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")

    legends = world_lore._legends
    form_lists = {"poetic": legends.poetic_forms, "musical": legends.musical_forms, "dance": legends.dance_forms}
    forms = form_lists.get(form_type, [])

    form_data = None
    for f in forms:
        if str(f.get("id", "")) == str(form_id):
            form_data = f
            break
    if not form_data:
        return RedirectResponse("/lore")

    form = {
        "name": form_data.get("name", "Unknown"),
        "form_type": f"{form_type.title()} Form",
        "description": form_data.get("description", ""),
    }

    return templates.TemplateResponse(request=request, name="lore_cultural_form.html", context={
        **ctx, "content_class": "content-wide", "form": form,
    })


@router.get("/lore/region/{region_id}", response_class=HTMLResponse)
async def lore_region_page(request: Request, region_id: str):
    """Detail page for a geographic region."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")
    legends = world_lore._legends
    for region in legends.regions:
        if str(region.get("id", "")) == str(region_id):
            fields = []
            if region.get("type"):
                fields.append(("Type", region["type"].replace("_", " ").title()))
            if region.get("evilness"):
                fields.append(("Evilness", region["evilness"].replace("_", " ").title()))
            # coords used for event matching, not displayed

            # Find events in this region via subregion_id
            from df_storyteller.context.event_renderer import describe_event_linked as _describe_evt
            region_events: list[dict] = []
            for evt in legends.historical_events:
                if str(evt.get("subregion_id", "")) == str(region_id):
                    region_events.append({"year": evt.get("year", "?"), "description": _describe_evt(evt, legends)})
                    if len(region_events) >= 100:
                        break
            region_events.sort(key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0)

            desc = f"{len(region_events)} events recorded in this region." if region_events else "No recorded events in this region."

            return templates.TemplateResponse(request=request, name="lore_geography.html", context={
                **ctx, "content_class": "content-wide",
                "geo": {"name": region.get("name", "Unknown"), "geo_type": "Region", "fields": fields, "description": desc, "events": region_events},
            })
    return RedirectResponse("/lore")


@router.get("/lore/landmass/{landmass_id}", response_class=HTMLResponse)
async def lore_landmass_page(request: Request, landmass_id: str):
    """Detail page for a landmass."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")
    for lm in world_lore._legends.landmasses:
        if str(lm.get("id", "")) == str(landmass_id):
            fields = []
            return templates.TemplateResponse(request=request, name="lore_geography.html", context={
                **ctx, "content_class": "content-wide",
                "geo": {"name": lm.get("name", "Unknown"), "geo_type": "Landmass", "fields": fields, "description": ""},
            })
    return RedirectResponse("/lore")


@router.get("/lore/river/{river_name}", response_class=HTMLResponse)
async def lore_river_page(request: Request, river_name: str):
    """Detail page for a river."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")
    for river in getattr(world_lore._legends, "rivers", []):
        if river.get("name", "").lower() == river_name.lower():
            fields = []
            if river.get("end_pos"):
                fields.append(("Empties at", river["end_pos"]))
            return templates.TemplateResponse(request=request, name="lore_geography.html", context={
                **ctx, "content_class": "content-wide",
                "geo": {"name": river.get("name", "Unknown"), "geo_type": "River", "fields": fields, "description": ""},
            })
    return RedirectResponse("/lore")


@router.get("/lore/peak/{peak_id}", response_class=HTMLResponse)
async def lore_peak_page(request: Request, peak_id: str):
    """Detail page for a mountain peak."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")
    legends = world_lore._legends
    for peak in getattr(legends, "mountain_peaks", []):
        if str(peak.get("id", "")) == str(peak_id):
            fields = []
            if peak.get("height"):
                fields.append(("Height", f"{peak['height']}"))
            # coords used for event matching, not displayed

            # Find events at this peak's coordinates
            from df_storyteller.context.event_renderer import describe_event_linked as _describe_evt
            peak_events: list[dict] = []
            peak_coords = peak.get("coords", "")
            if peak_coords:
                for evt in legends.historical_events:
                    if evt.get("coords") == peak_coords:
                        peak_events.append({"year": evt.get("year", "?"), "description": _describe_evt(evt, legends)})
                        if len(peak_events) >= 50:
                            break
                # Also check event collections
                for ec in legends.event_collections:
                    if ec.get("coords") == peak_coords:
                        ec_name = ec.get("name", "")
                        ec_type = ec.get("type", "").replace("_", " ").title()
                        label = f"{ec_type}: {ec_name}" if ec_name else ec_type
                        peak_events.append({"year": ec.get("start_year", "?"), "description": label})

            peak_events.sort(key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0)
            desc = f"{len(peak_events)} events recorded at this peak." if peak_events else ""

            return templates.TemplateResponse(request=request, name="lore_geography.html", context={
                **ctx, "content_class": "content-wide",
                "geo": {"name": peak.get("name", "Unknown"), "geo_type": "Mountain Peak", "fields": fields, "description": desc, "events": peak_events},
            })
    return RedirectResponse("/lore")


@router.get("/lore/construction/{construction_id}", response_class=HTMLResponse)
async def lore_construction_page(request: Request, construction_id: str):
    """Detail page for a world construction (tunnel, road, bridge)."""
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    if not world_lore.is_loaded or not world_lore._legends:
        return RedirectResponse("/lore")
    for wc in getattr(world_lore._legends, "world_constructions", []):
        if str(wc.get("id", "")) == str(construction_id):
            fields = []
            wc_type = wc.get("type", "")
            if wc_type:
                fields.append(("Type", wc_type.replace("_", " ").title()))
            # coords used for event matching, not displayed
            # Check for additional fields that may be present
            if wc.get("site_id_1") or wc.get("site_id_2"):
                legends = world_lore._legends
                for key in ("site_id_1", "site_id_2"):
                    sid = wc.get(key)
                    if sid:
                        try:
                            site = legends.get_site(int(sid))
                            if site:
                                label = "From Site" if key == "site_id_1" else "To Site"
                                fields.append((label, site.name))
                        except (ValueError, TypeError):
                            pass
            # Find events that occurred on this construction's tiles
            legends = world_lore._legends
            coord_set: set[str] = set()
            for pair in wc.get("coords", "").split("|"):
                pair = pair.strip()
                if "," in pair:
                    coord_set.add(pair)

            from df_storyteller.context.event_renderer import describe_event_linked as _describe_evt
            road_events: list[dict] = []
            if coord_set:
                # Event collections (battles, beast attacks, thefts, etc.)
                # Build event ID lookup for enriching collections
                _evt_by_id: dict[str, dict] = {}
                for _evt in legends.historical_events:
                    _evt_by_id[str(_evt.get("id", ""))] = _evt

                for ec in legends.event_collections:
                    ec_coords = ec.get("coords", "")
                    if ec_coords and ec_coords in coord_set:
                        ec_name = ec.get("name", "")
                        ec_type = ec.get("type", "").replace("_", " ").title()

                        # Enrich: resolve participants from sub-events
                        details: list[str] = []
                        event_ids = ec.get("event", [])
                        if event_ids and not ec_name:
                            participants: set[str] = set()
                            for eid in event_ids[:20]:
                                sub = _evt_by_id.get(str(eid))
                                if not sub:
                                    continue
                                for field in ("hfid", "slayer_hfid", "group_1_hfid", "group_2_hfid", "snatcher_hfid", "attacker_hfid"):
                                    hfid = sub.get(field)
                                    if hfid and str(hfid) != "-1":
                                        hf = legends.get_figure(int(hfid))
                                        if hf:
                                            participants.add(f"[[{hf.name}]]")
                            if participants:
                                details.append(", ".join(sorted(participants)[:4]))
                            # Site context
                            site_id = ec.get("site_id")
                            if site_id:
                                site = legends.get_site(int(site_id))
                                if site:
                                    details.append(f"at [[{site.name}]]")

                        if ec_name:
                            label = f"{ec_type}: {ec_name}"
                        elif details:
                            label = f"{ec_type} involving {' '.join(details)}"
                        else:
                            label = ec_type
                        road_events.append({"year": ec.get("start_year", "?"), "description": label})

                # Historical events at road tiles
                for evt in legends.historical_events:
                    if evt.get("coords") and evt["coords"] in coord_set:
                        road_events.append({"year": evt.get("year", "?"), "description": _describe_evt(evt, legends)})
                        if len(road_events) >= 100:
                            break

            road_events.sort(key=lambda e: int(e["year"]) if str(e["year"]).lstrip("-").isdigit() else 0)

            name = wc.get("name", "") or f"Construction #{construction_id}"
            description = ""
            if road_events:
                description = f"{len(road_events)} events recorded along this route."
            else:
                description = "No recorded events along this route."

            return templates.TemplateResponse(request=request, name="lore_geography.html", context={
                **ctx, "content_class": "content-wide",
                "geo": {
                    "name": name,
                    "geo_type": "World Construction",
                    "fields": fields,
                    "description": description,
                    "events": road_events,
                },
            })
    return RedirectResponse("/lore")


@router.get("/lore/map", response_class=HTMLResponse)
async def lore_map_page(request: Request):
    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)
    ctx = _base_context(config, "lore", metadata)
    return templates.TemplateResponse(request=request, name="lore_map.html", context={
        **ctx,
        "content_class": "content-wide",
        "lore_loaded": world_lore.is_loaded,
    })
