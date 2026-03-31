"""Lore API routes (JSON endpoints)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    get_map_image_cache,
    set_map_image_cache,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/lore/stats/world")
async def api_lore_stats_world():
    """World-level statistics for charts: race distribution, event timeline, event types."""
    from collections import Counter
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    # Historical figures by race (top 10 + other)
    race_counts: Counter[str] = Counter()
    for hf in legends.historical_figures.values():
        race = hf.race.replace("_", " ").title() if hf.race else "Unknown"
        race_counts[race] += 1

    top_races = race_counts.most_common(10)
    other_count = sum(race_counts.values()) - sum(c for _, c in top_races)
    race_labels = [r for r, _ in top_races]
    race_values = [c for _, c in top_races]
    if other_count > 0:
        race_labels.append("Other")
        race_values.append(other_count)

    # Events by century
    century_counts: Counter[int] = Counter()
    for evt in legends.historical_events:
        year = evt.get("year", "")
        try:
            century = int(year) // 100
            century_counts[century] += 1
        except (ValueError, TypeError):
            pass

    if century_counts:
        min_c = min(century_counts)
        max_c = max(century_counts)
        timeline_labels = [f"{c * 100}s" for c in range(min_c, max_c + 1)]
        timeline_values = [century_counts.get(c, 0) for c in range(min_c, max_c + 1)]
    else:
        timeline_labels = []
        timeline_values = []

    # Event type distribution (top 12)
    type_counts: Counter[str] = Counter()
    for evt in legends.historical_events:
        etype = evt.get("type", "unknown").replace("_", " ").replace("hf ", "").title()
        type_counts[etype] += 1

    top_types = type_counts.most_common(12)
    type_labels = [t for t, _ in top_types]
    type_values = [c for _, c in top_types]

    return {
        "race_distribution": {"labels": race_labels, "values": race_values},
        "event_timeline": {"labels": timeline_labels, "values": timeline_values},
        "event_types": {"labels": type_labels, "values": type_values},
    }


@router.get("/api/lore/stats/timeline")
async def api_lore_stats_timeline():
    """Timeline data for vis-timeline: eras, wars, conflicts, notable deaths."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    groups = [
        {"id": "eras", "content": "Eras", "order": 1},
        {"id": "wars", "content": "Wars", "order": 2},
        {"id": "conflicts", "content": "Conflicts", "order": 3},
        {"id": "deaths", "content": "Notable Deaths", "order": 4},
    ]

    items: list[dict[str, Any]] = []
    item_id = 0

    # Eras — background range items, infer end_year from next era
    sorted_eras = sorted(
        legends.historical_eras,
        key=lambda e: int(e.get("start_year", "0")),
    )
    for i, era in enumerate(sorted_eras):
        name = era.get("name", "")
        start = era.get("start_year", "")
        if not name or not start:
            continue
        end = era.get("end_year", "")
        if not end and i + 1 < len(sorted_eras):
            end = sorted_eras[i + 1].get("start_year", "")
        items.append({
            "id": item_id,
            "group": "eras",
            "content": name,
            "start": start,
            "end": end or None,
            "type": "background",
            "className": "timeline-era",
        })
        item_id += 1

    # Wars — range items
    for ec in legends.event_collections:
        if ec.get("type") != "war":
            continue
        name = ec.get("name", "Unknown War")
        start = ec.get("start_year", "")
        end = ec.get("end_year", "")
        if not start:
            continue
        ec_id = ec.get("id", "")
        has_duration = end and end != start
        items.append({
            "id": item_id,
            "group": "wars",
            "content": name,
            "start": start,
            "end": end if has_duration else None,
            "type": "range" if has_duration else "point",
            "className": "timeline-war",
            "link": f"/lore/war/{ec_id}" if ec_id else None,
            "subtype": "war",
        })
        item_id += 1

    # Conflicts — aggregate by year per subtype to avoid overwhelming the timeline
    # Named events (conquests, duels, coups, purges) are few enough to show individually.
    # Beast attacks and persecutions are aggregated by year.
    from collections import defaultdict

    individual_conflict_sources = [
        (legends.site_conquests, "site_conquest", "Conquest"),
        (legends.duels, "duel", "Duel"),
        (legends.entity_overthrown, "coup", "Coup"),
        (legends.purges, "purge", "Purge"),
    ]
    for source_list, subtype, default_name in individual_conflict_sources:
        for item in source_list:
            start = item.get("start_year", "")
            if not start:
                continue
            end = item.get("end_year", "")
            ec_id = item.get("id", "")
            has_duration = end and end != start
            items.append({
                "id": item_id,
                "group": "conflicts",
                "content": item.get("name", default_name),
                "start": start,
                "end": end if has_duration else None,
                "type": "range" if has_duration else "point",
                "className": f"timeline-{subtype}",
                "link": f"/lore/event/{ec_id}" if ec_id else None,
                "subtype": subtype,
            })
            item_id += 1

    # Beast attacks — aggregate by year with count
    beast_by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in legends.beast_attacks:
        start = item.get("start_year", "")
        if start:
            beast_by_year[start].append(item)
    for year, attacks in sorted(beast_by_year.items(), key=lambda x: int(x[0])):
        items.append({
            "id": item_id,
            "group": "conflicts",
            "content": f"{len(attacks)} beast attack{'s' if len(attacks) > 1 else ''}",
            "start": year,
            "type": "point",
            "subtype": "beast_attack",
            "count": len(attacks),
        })
        item_id += 1

    # Persecutions — aggregate by year with count
    persc_by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in legends.persecutions:
        start = item.get("start_year", "")
        if start:
            persc_by_year[start].append(item)
    for year, perscs in sorted(persc_by_year.items(), key=lambda x: int(x[0])):
        items.append({
            "id": item_id,
            "group": "conflicts",
            "content": f"{len(perscs)} persecution{'s' if len(perscs) > 1 else ''}",
            "start": year,
            "type": "point",
            "subtype": "persecution",
            "count": len(perscs),
        })
        item_id += 1

    # Notable deaths — aggregate by year with actual count
    deaths_by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for death in legends.notable_deaths:
        year = death.get("year", "")
        if year:
            deaths_by_year[year].append(death)

    for year, deaths in sorted(deaths_by_year.items(), key=lambda x: int(x[0])):
        items.append({
            "id": item_id,
            "group": "deaths",
            "content": f"{len(deaths)} notable death{'s' if len(deaths) > 1 else ''}",
            "start": year,
            "type": "point",
            "subtype": "death",
            "count": len(deaths),
        })
        item_id += 1

    return {"groups": groups, "items": items}


@router.get("/api/lore/stats/figure/{hf_id}")
async def api_lore_stats_figure(hf_id: int):
    """Per-figure event timeline for charts."""
    from collections import Counter
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    events = legends.get_hf_events(hf_id)

    year_counts: Counter[int] = Counter()
    for evt in events:
        try:
            year_counts[int(evt.get("year", 0))] += 1
        except (ValueError, TypeError):
            pass

    if not year_counts:
        return {"event_timeline": {"labels": [], "values": []}}

    min_y = min(year_counts)
    max_y = max(year_counts)
    span = max_y - min_y

    # Choose bucket size based on time span
    if span > 200:
        bucket = 20
    elif span > 50:
        bucket = 10
    elif span > 20:
        bucket = 5
    else:
        bucket = 1

    if bucket > 1:
        bucketed: Counter[int] = Counter()
        for y, c in year_counts.items():
            bucketed[(y // bucket) * bucket] += c
        sorted_keys = sorted(bucketed)
        labels = [f"{k}" if bucket == 1 else f"{k}s" for k in sorted_keys]
        values = [bucketed[k] for k in sorted_keys]
    else:
        # Only show years that have events (no zero-padding)
        sorted_years = sorted(year_counts)
        labels = [str(y) for y in sorted_years]
        values = [year_counts[y] for y in sorted_years]

    return {"event_timeline": {"labels": labels, "values": values}}


@router.get("/api/lore/stats/civ/{entity_id}")
async def api_lore_stats_civ(entity_id: int):
    """Per-civ war stats for charts."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    wars = legends.get_wars_involving(entity_id)

    war_labels = []
    battle_counts = []
    for war in wars[:15]:
        name = war.get("name", "?")
        if len(name) > 30:
            name = name[:27] + "..."
        war_id = war.get("id")
        n_battles = sum(1 for b in legends.battles if b.get("war_eventcol") == war_id)
        war_labels.append(name)
        battle_counts.append(n_battles)

    return {"war_battles": {"labels": war_labels, "values": battle_counts}}


@router.get("/api/lore/stats/site/{site_id}")
async def api_lore_stats_site(site_id: int):
    """Per-site event stats for charts."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    event_types = legends.get_site_event_types(site_id)

    # Top 8 event types for doughnut
    from collections import Counter
    sorted_types = Counter(event_types).most_common(8)
    other = sum(event_types.values()) - sum(c for _, c in sorted_types)

    labels = [t.replace("_", " ").replace("hf ", "").title() for t, _ in sorted_types]
    values = [c for _, c in sorted_types]
    if other > 0:
        labels.append("Other")
        values.append(other)

    return {"event_types": {"labels": labels, "values": values}}


# ==================== Lore Graph API ====================


@router.get("/api/lore/graph/family/{hf_id}")
async def api_lore_graph_family(hf_id: int):
    """Family tree graph data for vis-network: nodes and edges up to 2 generations."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    hf = legends.get_figure(hf_id)
    if not hf:
        return JSONResponse({"error": "not_found"}, status_code=404)

    nodes: dict[int, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple[int, int, str]] = set()

    def add_node(fid: int, level: int = 0) -> None:
        if fid in nodes:
            return
        f = legends.get_figure(fid)
        if not f:
            return
        is_dead = f.death_year is not None and f.death_year > 0
        nodes[fid] = {
            "id": fid,
            "label": f.name.split(",")[0].strip() if f.name else f"#{fid}",
            "race": f.race.replace("_", " ").title() if f.race else "",
            "level": level,
            "dead": is_dead,
            "is_deity": f.is_deity,
            "is_target": fid == hf_id,
        }

    def add_edge(src: int, tgt: int, label: str) -> None:
        key = (min(src, tgt), max(src, tgt), label)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": src, "to": tgt, "label": label})

    # Start with the target figure
    add_node(hf_id, level=0)
    family = legends.get_hf_family(hf_id)

    # Parents (level -1)
    for pid in family["parents"]:
        add_node(pid, level=-1)
        add_edge(pid, hf_id, "parent")
        # Grandparents (level -2)
        gp_family = legends.get_hf_family(pid)
        for gpid in gp_family["parents"]:
            add_node(gpid, level=-2)
            add_edge(gpid, pid, "parent")

    # Spouse (same level)
    for sid in family["spouse"]:
        add_node(sid, level=0)
        add_edge(hf_id, sid, "spouse")

    # Children (level 1)
    for cid in family["children"]:
        add_node(cid, level=1)
        add_edge(hf_id, cid, "parent")
        # Grandchildren (level 2)
        gc_family = legends.get_hf_family(cid)
        for gcid in gc_family["children"]:
            add_node(gcid, level=2)
            add_edge(cid, gcid, "parent")

    # Siblings (via shared parents, same level)
    for pid in family["parents"]:
        p_family = legends.get_hf_family(pid)
        for sibling_id in p_family["children"]:
            if sibling_id != hf_id:
                add_node(sibling_id, level=0)
                add_edge(pid, sibling_id, "parent")

    return {"nodes": list(nodes.values()), "edges": edges}


@router.get("/api/lore/graph/wars/{entity_id}")
async def api_lore_graph_wars(entity_id: int):
    """Warfare network graph: civilizations as nodes, wars as edges."""
    from collections import Counter
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends
    wars = legends.get_wars_involving(entity_id)

    nodes: dict[int, dict] = {}
    edge_weights: Counter[tuple[int, int]] = Counter()

    for war in wars:
        aggressors = war.get("aggressor_ent_id", [])
        defenders = war.get("defender_ent_id", [])
        if isinstance(aggressors, str):
            aggressors = [aggressors]
        if isinstance(defenders, str):
            defenders = [defenders]

        all_ids: list[int] = []
        for eid_str in aggressors + defenders:
            try:
                eid = int(eid_str)
                if eid not in nodes:
                    c = legends.get_civilization(eid)
                    if c:
                        nodes[eid] = {
                            "id": eid,
                            "label": c.name,
                            "race": c.race.replace("_", " ").title() if c.race else "",
                            "is_target": eid == entity_id,
                        }
                all_ids.append(eid)
            except (ValueError, TypeError):
                pass

        # Create edges between aggressors and defenders
        for a_str in aggressors:
            for d_str in defenders:
                try:
                    a, d = int(a_str), int(d_str)
                    key = (min(a, d), max(a, d))
                    edge_weights[key] += 1
                except (ValueError, TypeError):
                    pass

    edges = [{"from": a, "to": b, "weight": w} for (a, b), w in edge_weights.items()]

    return {"nodes": list(nodes.values()), "edges": edges}


# ==================== World Map API ====================


@router.get("/api/lore/map/terrain")
async def api_map_terrain():
    """Return generated terrain map PNG from region coordinate data."""
    from fastapi.responses import Response

    cached = get_map_image_cache()
    if cached is not None:
        png_bytes, _, _ = cached
        return Response(content=png_bytes, media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})

    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    from df_storyteller.context.map_generator import generate_terrain_map
    result = generate_terrain_map(world_lore._legends.regions, scale=4)
    if result is None:
        return JSONResponse({"error": "No region coordinate data available. Export legends_plus from DFHack."}, status_code=404)

    set_map_image_cache(result)
    png_bytes, _, _ = result
    return Response(content=png_bytes, media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@router.get("/api/lore/map/sites")
async def api_map_sites():
    """Return site marker data for the world map."""
    cached = get_map_image_cache()

    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    # Get world size from cached map or compute from regions
    world_w = world_h = 0
    if cached:
        _, world_w, world_h = cached
    else:
        for region in legends.regions:
            coords_str = region.get("coords", "")
            if coords_str:
                for pair in coords_str.split("|"):
                    parts = pair.strip().split(",")
                    if len(parts) == 2:
                        try:
                            x, y = int(parts[0]), int(parts[1])
                            if x >= world_w:
                                world_w = x + 1
                            if y >= world_h:
                                world_h = y + 1
                        except ValueError:
                            pass

    sites = []
    for sid, site in legends.sites.items():
        if not site.coordinates:
            continue
        owner_name = ""
        owner_race = ""
        owner_civ_id = None
        if site.owner_civ_id:
            civ = legends.get_civilization(site.owner_civ_id)
            if civ:
                owner_name = civ.name
                owner_race = civ.race.replace("_", " ").title() if civ.race else ""
                owner_civ_id = civ.entity_id

        sites.append({
            "id": site.site_id,
            "name": site.name,
            "type": site.site_type,
            "x": site.coordinates[0],
            "y": site.coordinates[1],
            "owner_civ_id": owner_civ_id,
            "owner_name": owner_name,
            "owner_race": owner_race,
        })

    # World constructions (roads, tunnels) as polylines
    constructions = []
    for wc in legends.world_constructions:
        coords_str = wc.get("coords", "")
        if not coords_str:
            continue
        points = []
        for pair in coords_str.split("|"):
            pair = pair.strip()
            if not pair:
                continue
            parts = pair.split(",")
            if len(parts) == 2:
                try:
                    points.append([int(parts[0]), int(parts[1])])
                except ValueError:
                    pass
        if len(points) >= 2:
            constructions.append({
                "id": wc.get("id", ""),
                "name": wc.get("name", ""),
                "type": wc.get("type", "").replace("_", " "),
                "points": points,
            })

    # Mountain peaks as special markers
    peaks = []
    for peak in getattr(legends, "mountain_peaks", []):
        coords_str = peak.get("coords", "")
        if not coords_str:
            continue
        parts = coords_str.split(",")
        if len(parts) == 2:
            try:
                peaks.append({
                    "id": peak.get("id", ""),
                    "name": peak.get("name", "Unknown"),
                    "height": peak.get("height", ""),
                    "x": int(parts[0]),
                    "y": int(parts[1]),
                })
            except ValueError:
                pass

    return {"sites": sites, "world_size": [world_w, world_h], "constructions": constructions, "peaks": peaks}


# ==================== Lore Search API ====================


@router.get("/api/lore/search")
async def api_lore_search(q: str = ""):
    """Search across ALL legends data — returns matching items by category."""
    if not q or len(q) < 2:
        return {"results": []}

    config = _get_config()
    _, _, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return {"results": []}

    legends = world_lore._legends
    query = q.lower()
    results: list[dict] = []
    MAX_PER_CATEGORY = config.web.search_max_per_category

    # Check if any fortress dwarves match (link to character sheet)
    event_store, character_tracker, _, _ = _load_game_state_safe(config)
    for dwarf, _ in character_tracker.ranked_characters():
        from df_storyteller.context.character_tracker import normalize_name
        if query in normalize_name(dwarf.name):
            results.append({
                "category": "Fortress Dwarf",
                "name": dwarf.name,
                "detail": f"{dwarf.profession}, age {dwarf.age:.0f}",
                "link": f"/dwarves/{dwarf.unit_id}",
            })

    # Search civilizations
    count = 0
    for eid, civ in legends.civilizations.items():
        if count >= MAX_PER_CATEGORY:
            break
        if query in civ.name.lower() or query in civ.race.lower():
            race = civ.race.replace("_", " ").title() if civ.race else ""
            results.append({"category": "Civilization", "name": civ.name, "detail": race, "id": eid, "entity_type": "civilization", "link": f"/lore/civ/{eid}"})
            count += 1

    # Build set of HF IDs with assumed identities (don't reveal in search)
    hfs_with_identities: set[int] = set()
    for ident in legends.identities:
        hfid_str = ident.get("histfig_id")
        if hfid_str:
            try:
                hfs_with_identities.add(int(hfid_str))
            except (ValueError, TypeError):
                pass

    # Search historical figures — don't reveal assumed identities
    count = 0
    for hfid, hf in legends.historical_figures.items():
        if count >= MAX_PER_CATEGORY:
            break
        searchable = f"{hf.name} {hf.race} {getattr(hf, 'associated_type', '')} {' '.join(hf.spheres)}".lower()
        if query in searchable:
            race = hf.race.replace("_", " ").title() if hf.race else ""
            detail = race
            if hf.spheres:
                detail += f" — spheres: {', '.join(hf.spheres)}"
            if hf.is_deity:
                detail = "Deity — " + detail
            if hf.birth_year and hf.birth_year > 0:
                detail += f" (born {hf.birth_year}"
                if hf.death_year and hf.death_year > 0:
                    detail += f", died {hf.death_year}"
                detail += ")"
            if hfid in hfs_with_identities:
                detail += " — this figure harbors a secret..."
            results.append({"category": "Figure", "name": hf.name, "detail": detail, "id": hfid, "entity_type": "figure", "link": f"/lore/figure/{hfid}"})
            count += 1

    # Search artifacts
    count = 0
    for aid, art in legends.artifacts.items():
        if count >= MAX_PER_CATEGORY:
            break
        searchable = f"{art.name} {art.item_type} {art.material} {art.description}".lower()
        if query in searchable:
            detail_parts = []
            if art.item_type:
                detail_parts.append(art.item_type.replace("_", " "))
            if art.material:
                detail_parts.append(art.material)
            if art.creator_hf_id:
                holder = legends.get_figure(art.creator_hf_id)
                if holder:
                    detail_parts.append(f"held by {holder.name}")
            results.append({"category": "Artifact", "name": art.name, "detail": " — ".join(detail_parts), "id": aid, "entity_type": "artifact", "link": f"/lore/artifact/{aid}"})
            count += 1

    # Search sites
    count = 0
    for sid, site in legends.sites.items():
        if count >= MAX_PER_CATEGORY:
            break
        if query in site.name.lower() or query in site.site_type.lower():
            results.append({"category": "Site", "name": site.name, "detail": site.site_type, "id": sid, "entity_type": "site", "link": f"/lore/site/{sid}"})
            count += 1

    # Search written works
    count = 0
    for wc in legends.written_contents:
        if count >= MAX_PER_CATEGORY:
            break
        title = wc.get("title", "")
        wc_style = wc.get("style", "")
        searchable = f"{title} {wc_style}".lower()
        if query in searchable:
            wc_type = wc.get("type", "").replace("_", " ").title()
            author_id = wc.get("author")
            author_name = ""
            if author_id:
                try:
                    author = legends.get_figure(int(author_id))
                    if author:
                        author_name = author.name
                except (ValueError, TypeError):
                    pass
            detail = wc_type
            if author_name:
                detail += f" by {author_name}"
            results.append({"category": "Written Work", "name": title, "detail": detail, "id": wc.get("id", ""), "entity_type": "written_work"})
            count += 1

    # Search event collections (wars, battles, performances, ceremonies, etc.)
    count = 0
    for ec in legends.event_collections:
        if count >= MAX_PER_CATEGORY:
            break
        name = ec.get("name", "")
        ec_type = ec.get("type", "")
        ec_type_display = ec_type.replace("_", " ").title() if ec_type else "Event"
        # Match on name if present, or on type if query matches the type
        matched = False
        if name and query in name.lower():
            matched = True
        elif ec_type and query in ec_type.lower().replace("_", " "):
            matched = True
        if matched:
            display_name = name if name else ec_type_display
            year = ec.get("start_year", "")
            detail = f"Year {year}" if year else ""
            results.append({"category": ec_type_display, "name": display_name, "detail": detail, "id": ec.get("id", ""), "entity_type": "war"})
            count += 1

    # Search cultural forms (poetic, musical, dance)
    count = 0
    for form_type, forms in [("Poetic Form", legends.poetic_forms), ("Musical Form", legends.musical_forms), ("Dance Form", legends.dance_forms)]:
        for form in forms:
            if count >= MAX_PER_CATEGORY:
                break
            name = form.get("name", "")
            desc = form.get("description", "")
            searchable = f"{name} {desc}".lower()
            if query in searchable:
                fid = form.get("id", "")
                detail = desc[:120] if desc else ""
                entity_type = form_type.lower().replace(" ", "_")
                results.append({
                    "category": form_type,
                    "name": name,
                    "detail": detail,
                    "id": fid,
                    "entity_type": "cultural_form",
                    "link": f"/lore/form/{entity_type}/{fid}" if fid else "",
                })
                count += 1

    # Search regions
    count = 0
    for region in legends.regions:
        if count >= MAX_PER_CATEGORY:
            break
        name = region.get("name", "") if isinstance(region, dict) else getattr(region, "name", "")
        rtype = region.get("type", "") if isinstance(region, dict) else getattr(region, "type", "")
        rid = region.get("id", "") if isinstance(region, dict) else getattr(region, "id", "")
        searchable = f"{name} {rtype}".lower()
        if query in searchable:
            rtype_display = rtype.replace("_", " ").title() if rtype else ""
            results.append({"category": "Region", "name": name, "detail": rtype_display, "id": rid, "entity_type": "region", "link": f"/lore/region/{rid}"})
            count += 1

    # Search landmasses
    count = 0
    for lm in getattr(legends, "landmasses", []):
        if count >= MAX_PER_CATEGORY:
            break
        name = lm.get("name", "") if isinstance(lm, dict) else getattr(lm, "name", "")
        if name and query in name.lower():
            lm_id = lm.get("id", "") if isinstance(lm, dict) else getattr(lm, "id", "")
            results.append({"category": "Landmass", "name": name, "detail": "", "id": lm_id, "entity_type": "landmass", "link": f"/lore/landmass/{lm_id}"})
            count += 1

    # Search rivers
    count = 0
    for river in getattr(legends, "rivers", []):
        if count >= MAX_PER_CATEGORY:
            break
        name = river.get("name", "") if isinstance(river, dict) else ""
        if name and query in name.lower():
            from urllib.parse import quote
            results.append({"category": "River", "name": name, "detail": "", "entity_type": "river", "link": f"/lore/river/{quote(name)}"})
            count += 1

    # Search mountain peaks
    count = 0
    for peak in getattr(legends, "mountain_peaks", []):
        if count >= MAX_PER_CATEGORY:
            break
        name = peak.get("name", "") if isinstance(peak, dict) else ""
        pid = peak.get("id", "") if isinstance(peak, dict) else ""
        if name and query in name.lower():
            height = peak.get("height", "") if isinstance(peak, dict) else ""
            detail = f"Height: {height}" if height else ""
            results.append({"category": "Mountain Peak", "name": name, "detail": detail, "id": pid, "entity_type": "peak", "link": f"/lore/peak/{pid}"})
            count += 1

    # Search world constructions (tunnels, roads, bridges)
    count = 0
    for wc in getattr(legends, "world_constructions", []):
        if count >= MAX_PER_CATEGORY:
            break
        name = wc.get("name", "") if isinstance(wc, dict) else ""
        wc_type = wc.get("type", "") if isinstance(wc, dict) else ""
        wc_id = wc.get("id", "") if isinstance(wc, dict) else ""
        searchable = f"{name} {wc_type}".lower()
        if query in searchable:
            detail = wc_type.replace("_", " ").title() if wc_type else "Construction"
            display_name = name if name else f"{detail} #{wc_id}"
            results.append({"category": "World Construction", "name": display_name, "detail": detail, "id": wc_id, "entity_type": "construction", "link": f"/lore/construction/{wc_id}"})
            count += 1

    return {"results": results}


@router.get("/api/lore/detail")
async def api_lore_detail(entity_type: str, entity_id: str):
    """Return structured detail for a lore entity (for hover tooltips)."""
    config = _get_config()
    _, _, world_lore, _ = _load_game_state_safe(config, skip_legends=False)

    if not world_lore.is_loaded or not world_lore._legends:
        return JSONResponse({"error": "Legends not loaded"}, status_code=503)

    legends = world_lore._legends

    try:
        eid = int(entity_id)
    except (ValueError, TypeError):
        eid = 0

    if entity_type == "figure":
        hf = legends.get_figure(eid)
        if not hf:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if hf.race:
            fields.append({"label": "Race", "value": hf.race.replace("_", " ").title()})
        if hf.hf_type:
            fields.append({"label": "Type", "value": hf.hf_type.replace("_", " ").title()})
        if hf.birth_year and hf.birth_year > 0:
            born = f"Year {hf.birth_year}"
            if hf.death_year and hf.death_year > 0:
                born += f" — died Year {hf.death_year}"
            fields.append({"label": "Born", "value": born})
        if hf.spheres:
            fields.append({"label": "Spheres", "value": ", ".join(hf.spheres)})
        if hf.associated_civ_id:
            civ = legends.get_civilization(hf.associated_civ_id)
            if civ:
                fields.append({"label": "Civilization", "value": civ.name})

        # Relationships from legends (uses precomputed index)
        from collections import Counter
        hfid_str = str(eid)
        rel_summaries = []
        for rel in legends.get_hf_relationships(eid):
            if rel.get("source_hf") == hfid_str:
                other = legends.get_figure(int(rel.get("target_hf", 0)))
                if other:
                    rel_summaries.append(f"{rel.get('relationship', '?')} of {other.name}")
            elif rel.get("target_hf") == hfid_str:
                other = legends.get_figure(int(rel.get("source_hf", 0)))
                if other:
                    rel_summaries.append(f"{rel.get('relationship', '?')} of {other.name}")
        if rel_summaries:
            fields.append({"label": "Relationships", "value": "; ".join(rel_summaries[:5])})

        # Event type breakdown + kill details (uses precomputed index)
        evt_types: Counter[str] = Counter()
        kill_victims: list[tuple[str, str]] = []  # (name, race)
        kill_races: Counter[str] = Counter()
        for evt in legends.get_hf_events(eid):
            evt_types[evt.get("type", "unknown")] += 1
            # Track kills where this figure is the slayer
            if evt.get("type") == "hf died" and evt.get("slayer_hfid") == hfid_str:
                victim = legends.get_figure(int(evt.get("hfid", 0))) if evt.get("hfid") else None
                if victim:
                    kill_victims.append((victim.name, victim.race.replace("_", " ").title() if victim.race else ""))
                    kill_races[victim.race.replace("_", " ").title() if victim.race else "Unknown"] += 1
        if evt_types:
            # Only show interesting event types, skip mundane ones
            readable_map = {
                "hf died": "kills",
                "hf simple battle event": "battles",
                "hf attacked site": "site attacks",
                "hf destroyed site": "site destructions",
                "creature devoured": "devoured victims",
                "item stolen": "thefts",
                "hf wounded": "wounds inflicted",
                "hf confronted": "confrontations",
                "artifact created": "artifacts created",
                "hf new pet": "tamed creatures",
                "assume identity": "assumed identities",
                "hf razed structure": "razed structures",
            }
            # Skip boring types: state changes, job changes, entity links, travel
            summary_parts = []
            for evt_type, count in evt_types.most_common(10):
                if evt_type in readable_map:
                    summary_parts.append(f"{count} {readable_map[evt_type]}")
                if len(summary_parts) >= 4:
                    break
            total = sum(evt_types.values())
            if summary_parts:
                fields.append({"label": "Notable Events", "value": ", ".join(summary_parts)})
            else:
                fields.append({"label": "Historical Events", "value": str(total)})

        # Kill details
        if kill_victims:
            race_summary = ", ".join(f"{count} {race}" for race, count in kill_races.most_common(4))
            fields.append({"label": "Kill Count", "value": f"{len(kill_victims)} ({race_summary})"})
            notable_kills = [f"{name} ({race})" for name, race in kill_victims[:3]]
            fields.append({"label": "Notable Kills", "value": "; ".join(notable_kills)})

        if hf.notable_deeds:
            fields.append({"label": "Deeds", "value": "; ".join(hf.notable_deeds[:3])})
        return {"entity_type": "figure", "name": hf.name, "fields": fields}

    elif entity_type == "civilization":
        civ = legends.get_civilization(eid)
        if not civ:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if civ.race:
            fields.append({"label": "Race", "value": civ.race.replace("_", " ").title()})
        if civ.sites:
            site_names = []
            for sid in civ.sites[:5]:
                site = legends.get_site(sid)
                if site:
                    site_names.append(f"{site.name} ({site.site_type})" if site.site_type else site.name)
            if site_names:
                suffix = f" (+{len(civ.sites) - 5} more)" if len(civ.sites) > 5 else ""
                fields.append({"label": "Sites", "value": ", ".join(site_names) + suffix})
        wars = legends.get_wars_involving(eid)
        if wars:
            war_names = [w.get("name", "Unknown") for w in wars[:4]]
            suffix = f" (+{len(wars) - 4} more)" if len(wars) > 4 else ""
            fields.append({"label": "Wars", "value": "; ".join(war_names) + suffix})
        if civ.leader_hf_ids:
            leader_names = []
            for lid in civ.leader_hf_ids[:3]:
                lhf = legends.get_figure(lid)
                if lhf:
                    leader_names.append(lhf.name)
            if leader_names:
                fields.append({"label": "Leaders", "value": ", ".join(leader_names)})
        return {"entity_type": "civilization", "name": civ.name, "fields": fields}

    elif entity_type == "artifact":
        art = legends.get_artifact(eid)
        if not art:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if art.item_type:
            fields.append({"label": "Type", "value": art.item_type.replace("_", " ")})
        if art.material:
            fields.append({"label": "Material", "value": art.material})
        if art.creator_hf_id:
            creator = legends.get_figure(art.creator_hf_id)
            if creator:
                creator_detail = creator.name
                if creator.race:
                    creator_detail += f" ({creator.race.replace('_', ' ').title()})"
                fields.append({"label": "Creator", "value": creator_detail})
        if art.site_id:
            site = legends.get_site(art.site_id)
            if site:
                fields.append({"label": "Location", "value": f"{site.name} ({site.site_type})" if site.site_type else site.name})
        if art.description:
            fields.append({"label": "Description", "value": art.description[:300]})
        return {"entity_type": "artifact", "name": art.name, "fields": fields}

    elif entity_type == "site":
        site = legends.get_site(eid)
        if not site:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        if site.site_type:
            fields.append({"label": "Type", "value": site.site_type.replace("_", " ").title()})
        if site.owner_civ_id:
            owner = legends.get_civilization(site.owner_civ_id)
            if owner:
                race = f" ({owner.race.replace('_', ' ').title()})" if owner.race else ""
                fields.append({"label": "Owner", "value": f"{owner.name}{race}"})
        if site.coordinates:
            fields.append({"label": "Coordinates", "value": f"({site.coordinates[0]}, {site.coordinates[1]})"})
        # Notable events at this site (precomputed index)
        site_evt_types = legends.get_site_event_types(eid)
        if site_evt_types:
            interesting = {"hf died": "deaths", "hf attacked site": "attacks", "artifact created": "artifacts created",
                           "hf destroyed site": "destructions", "item stolen": "thefts", "creature devoured": "devourings"}
            parts = []
            for et, label in interesting.items():
                if et in site_evt_types:
                    parts.append(f"{site_evt_types[et]} {label}")
            if parts:
                fields.append({"label": "Notable Events", "value": ", ".join(parts[:4])})
            total = sum(site_evt_types.values())
            fields.append({"label": "Total Events", "value": str(total)})
        return {"entity_type": "site", "name": site.name, "fields": fields}

    elif entity_type in ("war", "battle"):
        ec = legends.get_event_collection(entity_id)
        if not ec:
            return JSONResponse({"error": "not_found"}, status_code=404)
        fields = []
        sy = ec.get("start_year", "")
        ey = ec.get("end_year", "")
        if sy:
            year_str = f"Year {sy}" + (f"\u2013{ey}" if ey and ey != sy else "")
            fields.append({"label": "Years", "value": year_str})
        for role, key in [("Aggressor", "aggressor_ent_id"), ("Defender", "defender_ent_id")]:
            ids = ec.get(key, [])
            if isinstance(ids, str):
                ids = [ids]
            names = []
            for eid_str in ids:
                try:
                    c = legends.get_civilization(int(eid_str))
                    if c:
                        names.append(f"{c.name} ({c.race.replace('_', ' ').title()})" if c.race else c.name)
                except (ValueError, TypeError):
                    pass
            if names:
                fields.append({"label": role, "value": ", ".join(names)})
        # For wars: list battles and total casualties
        ec_type = ec.get("type", "")
        if ec_type == "war":
            war_id = ec.get("id")
            war_battles = [b for b in legends.battles if b.get("war_eventcol") == war_id]
            if war_battles:
                battle_summaries = []
                total_atk_d = 0
                total_def_d = 0
                for b in war_battles:
                    outcome_str = b.get("outcome", "").replace("_", " ")
                    battle_summaries.append(f"{b.get('name', '?')} ({outcome_str})")
                    ad = b.get("attacking_squad_deaths", [])
                    dd = b.get("defending_squad_deaths", [])
                    if isinstance(ad, list):
                        total_atk_d += sum(int(d) for d in ad if str(d).isdigit())
                    if isinstance(dd, list):
                        total_def_d += sum(int(d) for d in dd if str(d).isdigit())
                fields.append({"label": "Battles", "value": "; ".join(battle_summaries[:5])
                               + (f" (+{len(war_battles) - 5} more)" if len(war_battles) > 5 else "")})
                if total_atk_d or total_def_d:
                    fields.append({"label": "Total Casualties", "value": f"Attackers: {total_atk_d}, Defenders: {total_def_d}"})

        # Outcome for individual battles
        outcome = ec.get("outcome", "")
        if outcome and ec_type != "war":
            fields.append({"label": "Outcome", "value": outcome.replace("_", " ").title()})
        # Site where it happened
        site_id = ec.get("site_id")
        if site_id and site_id != "-1":
            site = legends.get_site(int(site_id))
            if site:
                fields.append({"label": "Location", "value": site.name})
        # Squad composition for battles
        atk_races = ec.get("attacking_squad_race", [])
        def_races = ec.get("defending_squad_race", [])
        if isinstance(atk_races, list) and atk_races:
            from collections import Counter as RCounter
            atk_summary = RCounter(r.replace("_", " ").title() for r in atk_races)
            fields.append({"label": "Attacking Forces", "value": ", ".join(f"{c} {r}" for r, c in atk_summary.most_common(4))})
        if isinstance(def_races, list) and def_races:
            from collections import Counter as RCounter2
            def_summary = RCounter2(r.replace("_", " ").title() for r in def_races)
            fields.append({"label": "Defending Forces", "value": ", ".join(f"{c} {r}" for r, c in def_summary.most_common(4))})
        # Casualty totals
        atk_deaths = ec.get("attacking_squad_deaths", [])
        def_deaths = ec.get("defending_squad_deaths", [])
        if isinstance(atk_deaths, list):
            total_atk = sum(int(d) for d in atk_deaths if d.isdigit())
            total_def = sum(int(d) for d in def_deaths if d.isdigit()) if isinstance(def_deaths, list) else 0
            if total_atk or total_def:
                fields.append({"label": "Casualties", "value": f"Attackers: {total_atk}, Defenders: {total_def}"})
        # Notable combatants
        atk_hfids = ec.get("attacking_hfid", [])
        def_hfids = ec.get("defending_hfid", [])
        if isinstance(atk_hfids, list) and atk_hfids:
            combatant_names = []
            for hid in atk_hfids[:3]:
                h = legends.get_figure(int(hid))
                if h:
                    combatant_names.append(h.name)
            if combatant_names:
                suffix = f" (+{len(atk_hfids) - 3} more)" if len(atk_hfids) > 3 else ""
                fields.append({"label": "Notable Attackers", "value": ", ".join(combatant_names) + suffix})
        if isinstance(def_hfids, list) and def_hfids:
            combatant_names = []
            for hid in def_hfids[:3]:
                h = legends.get_figure(int(hid))
                if h:
                    combatant_names.append(h.name)
            if combatant_names:
                suffix = f" (+{len(def_hfids) - 3} more)" if len(def_hfids) > 3 else ""
                fields.append({"label": "Notable Defenders", "value": ", ".join(combatant_names) + suffix})
        return {"entity_type": entity_type, "name": ec.get("name", "Unknown"), "fields": fields}

    elif entity_type == "written_work":
        for wc in legends.written_contents:
            if str(wc.get("id", "")) == str(entity_id):
                fields = []
                wc_type = wc.get("type", "").replace("_", " ").title()
                if wc_type:
                    fields.append({"label": "Form", "value": wc_type})
                style = wc.get("style", "").split(":")[0].strip().title()
                if style:
                    fields.append({"label": "Style", "value": style})
                author_id = wc.get("author")
                if author_id:
                    try:
                        author = legends.get_figure(int(author_id))
                        if author:
                            author_detail = author.name
                            if author.race:
                                author_detail += f" ({author.race.replace('_', ' ').title()})"
                            if author.associated_civ_id:
                                aciv = legends.get_civilization(author.associated_civ_id)
                                if aciv:
                                    author_detail += f" of {aciv.name}"
                            fields.append({"label": "Author", "value": author_detail})
                    except (ValueError, TypeError):
                        pass
                pages = wc.get("page_end", "")
                if pages and pages != "1":
                    fields.append({"label": "Pages", "value": pages})
                # References to historical events/figures that inspired the work
                ref = wc.get("reference", "")
                if ref and isinstance(ref, str) and ref.strip():
                    fields.append({"label": "Reference", "value": ref.strip()[:200]})
                return {"entity_type": "written_work", "name": wc.get("title", "Untitled"), "fields": fields}
        return JSONResponse({"error": "not_found"}, status_code=404)

    elif entity_type == "geography":
        # Search across mountains, rivers, landmasses by ID string
        for peak in legends.mountain_peaks:
            if str(peak.get("id", "")) == str(entity_id):
                fields = [{"label": "Type", "value": "Mountain Peak"}]
                height = peak.get("height", "")
                if height:
                    fields.append({"label": "Height", "value": f"{height}"})
                is_volcano = peak.get("is_volcano")
                if is_volcano:
                    fields.append({"label": "Volcano", "value": "Yes"})
                coords = peak.get("coords", "")
                if coords:
                    fields.append({"label": "Coordinates", "value": coords})
                return {"entity_type": "geography", "name": peak.get("name", ""), "fields": fields}
        for land in legends.landmasses:
            if str(land.get("id", "")) == str(entity_id):
                fields = [{"label": "Type", "value": "Landmass"}]
                c1 = land.get("coord_1", "")
                c2 = land.get("coord_2", "")
                if c1 and c2:
                    fields.append({"label": "Extent", "value": f"{c1} to {c2}"})
                return {"entity_type": "geography", "name": land.get("name", ""), "fields": fields}
        # Rivers don't have IDs, skip
        return JSONResponse({"error": "not_found"}, status_code=404)

    return JSONResponse({"error": "invalid_type"}, status_code=400)


# ==================== Lore Pins API ====================


@router.get("/api/lore/pins")
async def api_list_pins():
    """List all lore pins."""
    from df_storyteller.context.lore_pins import load_pins
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    return load_pins(fortress_dir)


@router.post("/api/lore/pins")
async def api_add_pin(request: Request):
    """Add a lore pin."""
    from df_storyteller.context.lore_pins import add_pin
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    data = await request.json()
    pin = add_pin(
        fortress_dir,
        entity_type=data.get("entity_type", ""),
        entity_id=data.get("entity_id", ""),
        name=data.get("name", ""),
        note=data.get("note", ""),
    )
    return pin


@router.delete("/api/lore/pins/all")
async def api_clear_all_pins():
    """Remove all lore pins."""
    from df_storyteller.context.lore_pins import save_pins
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    save_pins(fortress_dir, [])
    return {"status": "ok"}


@router.delete("/api/lore/pins/{pin_id}")
async def api_remove_pin(pin_id: str):
    """Remove a lore pin."""
    from df_storyteller.context.lore_pins import remove_pin
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    if remove_pin(fortress_dir, pin_id):
        return {"status": "ok"}
    return JSONResponse({"error": "not_found"}, status_code=404)


@router.put("/api/lore/pins/{pin_id}")
async def api_update_pin(pin_id: str, request: Request):
    """Update a pin's note."""
    from df_storyteller.context.lore_pins import update_pin_note
    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    data = await request.json()
    if update_pin_note(fortress_dir, pin_id, data.get("note", "")):
        return {"status": "ok"}
    return JSONResponse({"error": "not_found"}, status_code=404)
