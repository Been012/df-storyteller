"""Lore index page route."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
)
from df_storyteller.web.templates_setup import templates
from df_storyteller.web.routers.lore_detail import (
    _build_sub_entities,
    _build_sub_entities_structured,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/lore", response_class=HTMLResponse)
async def lore_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config, skip_legends=False)

    ctx = _base_context(config, "lore", metadata)

    civilizations = []
    wars = []
    figures = []
    beast_attacks: list[dict] = []
    site_conquests: list[dict] = []
    persecutions: list[dict] = []
    duels: list[dict] = []
    abductions: list[dict] = []
    thefts: list[dict] = []
    purges: list[dict] = []
    overthrown: list[dict] = []
    notable_deaths: list[dict] = []
    regions_data: list[dict] = []
    player_civ_data = None

    # Get player civ ID from metadata
    player_civ_id = metadata.get("fortress_info", {}).get("civ_id", -1)

    if world_lore.is_loaded and world_lore._legends:
        legends = world_lore._legends

        # Build entity type index for finding sub-entities
        entity_types: dict[int, str] = {}
        for eid, civ in legends.civilizations.items():
            entity_types[eid] = getattr(civ, '_entity_type', '')

        # Civilizations — show actual civilizations with their guilds, religions, etc.
        for eid, civ in legends.civilizations.items():
            etype = entity_types.get(eid, '')
            if etype and etype != 'civilization':
                continue
            if not civ.name:
                continue

            details_parts = []
            sites = [legends.get_site(sid) for sid in civ.sites if legends.get_site(sid)]
            if sites:
                site_names = [f"{s.name} ({s.site_type})" for s in sites[:5]]
                details_parts.append(f"Controls: {', '.join(site_names)}")
            war_count = len(legends.get_wars_involving(eid))
            if war_count:
                details_parts.append(f"Involved in {war_count} war{'s' if war_count != 1 else ''}")

            # Find sub-entities using child IDs from the XML hierarchy
            sub_data = _build_sub_entities_structured(legends, civ)
            sub_entities = _build_sub_entities(legends, civ)

            race_display = civ.race.replace('_', ' ').title() if civ.race else ''
            civilizations.append({
                "id": eid,
                "entity_type": "civilization",
                "name": civ.name,
                "race": race_display,
                "details": ". ".join(details_parts) if details_parts else "",
                "sub_entities": sub_entities,
                "org_data": sub_data,
            })

        # Wars — all of them
        for ec in legends.event_collections:
            if ec.get("type") == "war":
                details_parts = []
                for role, key in [("Aggressor", "aggressor_ent_id"), ("Defender", "defender_ent_id")]:
                    ids = ec.get(key, [])
                    if isinstance(ids, str):
                        ids = [ids]
                    for eid_str in ids:
                        try:
                            c = legends.get_civilization(int(eid_str))
                            if c:
                                details_parts.append(f"{role}: {c.name} ({c.race})" if c.race else f"{role}: {c.name}")
                        except (ValueError, TypeError):
                            pass
                year_range = ""
                sy = ec.get("start_year", "")
                ey = ec.get("end_year", "")
                if sy and ey and sy != ey:
                    year_range = f"Year {sy}\u2013{ey}"
                elif sy:
                    year_range = f"Year {sy}"

                wars.append({
                    "id": ec.get("id", ""),
                    "entity_type": "war",
                    "name": ec.get("name", "Unknown conflict"),
                    "details": " vs ".join(details_parts) if details_parts else "",
                    "years": year_range,
                })

        # Battles — named conflicts with outcomes
        battles = []
        for battle in legends.battles:
            name = battle.get("name", "")
            outcome = battle.get("outcome", "")
            year = battle.get("start_year", "")

            # These fields can be strings or lists (multiple squads)
            def _first_str(val: Any) -> str:
                if isinstance(val, list):
                    return val[0] if val else ""
                return str(val) if val else ""

            atk_race = _first_str(battle.get("attacking_squad_race", "")).replace("_", " ").title()
            def_race = _first_str(battle.get("defending_squad_race", "")).replace("_", " ").title()
            atk_deaths = _first_str(battle.get("attacking_squad_deaths", "0"))
            def_deaths = _first_str(battle.get("defending_squad_deaths", "0"))

            details = ""
            if atk_race and def_race:
                details = f"{atk_race} vs {def_race}"
                if outcome:
                    outcome_str = outcome.replace("_", " ") if isinstance(outcome, str) else str(outcome)
                    details += f" \u2014 {outcome_str}"
                details += f" ({atk_deaths}/{def_deaths} casualties)"
            battles.append({"id": battle.get("id", ""), "entity_type": "battle", "name": name, "details": details, "year": year})

        # Beast attacks — resolve defender civ and count events
        beast_attacks = []
        for ba in legends.beast_attacks:
            name = ba.get("name", "Beast attack")
            year = ba.get("start_year", "")
            site_id = ba.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            defender_name = ""
            def_id = ba.get("defending_enid")
            if def_id and def_id != "-1":
                try:
                    c = legends.get_civilization(int(def_id))
                    if c:
                        defender_name = c.name
                except (ValueError, TypeError):
                    pass
            event_list = ba.get("event", [])
            n_events = len(event_list) if isinstance(event_list, list) else (1 if event_list else 0)
            parts = []
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            if defender_name:
                parts.append(f"against {defender_name}")
            if n_events:
                parts.append(f"{n_events} incidents")
            beast_attacks.append({"id": ba.get("id", ""), "name": name, "year": year,
                                  "site_name": site_name, "site_id": site_id,
                                  "defender_name": defender_name, "defender_id": def_id,
                                  "n_events": n_events})

        # Site conquests — resolve attacker/defender civs
        site_conquests = []
        for sc in legends.site_conquests:
            name = sc.get("name", "Site conquered")
            year = sc.get("start_year", "")
            site_id = sc.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = defender_name = ""
            atk_id = sc.get("attacking_enid")
            if atk_id and atk_id != "-1":
                try:
                    c = legends.get_civilization(int(atk_id))
                    if c:
                        attacker_name = c.name
                except (ValueError, TypeError):
                    pass
            def_id = sc.get("defending_enid")
            if def_id and def_id != "-1":
                try:
                    c = legends.get_civilization(int(def_id))
                    if c:
                        defender_name = c.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            if attacker_name and defender_name:
                parts.append(f"{attacker_name} conquered from {defender_name}")
            elif attacker_name:
                parts.append(f"by {attacker_name}")
            site_conquests.append({"id": sc.get("id", ""), "name": name, "year": year,
                                   "site_name": site_name, "site_id": site_id,
                                   "attacker_name": attacker_name, "attacker_id": atk_id,
                                   "defender_name": defender_name, "defender_id": def_id})

        # Persecutions — resolve target entity and site
        persecutions = []
        for persc in legends.persecutions:
            name = persc.get("name", "Persecution")
            year = persc.get("start_year", "")
            site_id = persc.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            target_name = ""
            target_id = persc.get("target_entity_id")
            if target_id and target_id != "-1":
                try:
                    c = legends.get_civilization(int(target_id))
                    if c:
                        target_name = c.name
                except (ValueError, TypeError):
                    pass
            event_list = persc.get("event", [])
            n_events = len(event_list) if isinstance(event_list, list) else (1 if event_list else 0)
            parts = []
            if year:
                parts.append(f"Year {year}")
            if target_name:
                parts.append(f"targeting {target_name}")
            if site_name:
                parts.append(f"at {site_name}")
            if n_events:
                parts.append(f"{n_events} incidents")
            persecutions.append({"id": persc.get("id", ""), "name": name, "year": year,
                                 "site_name": site_name, "site_id": site_id,
                                 "target_name": target_name, "target_id": target_id,
                                 "n_events": n_events})

        # Duels — resolve attacker/defender HFs
        duels = []
        for duel in legends.duels:
            year = duel.get("start_year", "")
            site_id = duel.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = defender_name = ""
            atk_id = duel.get("attacking_hfid")
            if atk_id:
                try:
                    h = legends.get_figure(int(atk_id))
                    if h:
                        attacker_name = h.name
                except (ValueError, TypeError):
                    pass
            def_id = duel.get("defending_hfid")
            if def_id:
                try:
                    h = legends.get_figure(int(def_id))
                    if h:
                        defender_name = h.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if attacker_name and defender_name:
                parts.append(f"{attacker_name} vs {defender_name}")
            if site_name:
                parts.append(f"at {site_name}")
            duels.append({"id": duel.get("id", ""), "name": duel.get("name", "Duel"), "year": year,
                          "atk_name": attacker_name, "atk_id": atk_id,
                          "def_name": defender_name, "def_id": def_id,
                          "site_name": site_name, "site_id": site_id})

        # Abductions — resolve attacker/defender civs
        abductions = []
        for abd in legends.abductions:
            year = abd.get("start_year", "")
            site_id = abd.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = defender_name = ""
            atk_id = abd.get("attacking_enid")
            if atk_id and atk_id != "-1":
                try:
                    c = legends.get_civilization(int(atk_id))
                    if c:
                        attacker_name = c.name
                except (ValueError, TypeError):
                    pass
            def_id = abd.get("defending_enid")
            if def_id and def_id != "-1":
                try:
                    c = legends.get_civilization(int(def_id))
                    if c:
                        defender_name = c.name
                except (ValueError, TypeError):
                    pass
            event_list = abd.get("event", [])
            n_events = len(event_list) if isinstance(event_list, list) else (1 if event_list else 0)
            parts = []
            if year:
                parts.append(f"Year {year}")
            if attacker_name:
                parts.append(f"by {attacker_name}")
            if defender_name:
                parts.append(f"from {defender_name}")
            if site_name:
                parts.append(f"at {site_name}")
            if n_events:
                parts.append(f"{n_events} incidents")
            abductions.append({"id": abd.get("id", ""), "name": abd.get("name", "Abduction"), "year": year,
                               "attacker_name": attacker_name, "attacker_id": atk_id,
                               "defender_name": defender_name, "defender_id": def_id,
                               "site_name": site_name, "site_id": site_id, "n_events": n_events})

        # Thefts — resolve attacker/defender civs
        thefts = []
        for theft in legends.thefts:
            year = theft.get("start_year", "")
            site_id = theft.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            attacker_name = ""
            atk_id = theft.get("attacking_enid")
            if atk_id and atk_id != "-1":
                try:
                    c = legends.get_civilization(int(atk_id))
                    if c:
                        attacker_name = c.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if attacker_name:
                parts.append(f"by {attacker_name}")
            if site_name:
                parts.append(f"at {site_name}")
            thefts.append({"id": theft.get("id", ""), "name": theft.get("name", "Theft"), "year": year,
                           "attacker_name": attacker_name, "attacker_id": atk_id,
                           "site_name": site_name, "site_id": site_id})

        # Purges — resolve site, show adjective (e.g. "Vampire")
        purges = []
        for purge in legends.purges:
            year = purge.get("start_year", "")
            site_id = purge.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            adjective = purge.get("adjective", "")
            parts = []
            if adjective:
                parts.append(f"{adjective} purge")
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            purges.append({"id": purge.get("id", ""), "name": purge.get("name", "Purge"), "year": year,
                           "adjective": adjective, "site_name": site_name, "site_id": site_id})

        # Entity overthrown
        overthrown = []
        for ov in legends.entity_overthrown:
            year = ov.get("start_year", "")
            site_id = ov.get("site_id")
            site_name = ""
            if site_id and site_id != "-1":
                try:
                    s = legends.get_site(int(site_id))
                    if s:
                        site_name = s.name
                except (ValueError, TypeError):
                    pass
            parts = []
            if year:
                parts.append(f"Year {year}")
            if site_name:
                parts.append(f"at {site_name}")
            overthrown.append({"id": ov.get("id", ""), "name": ov.get("name", "Coup"), "year": year,
                               "site_name": site_name, "site_id": site_id})

        # Notable deaths (named victims with named slayers)
        for death in legends.notable_deaths:
            victim_id = death.get("hfid")
            slayer_id = death.get("slayer_hfid")
            victim_name = slayer_name = ""
            if victim_id:
                try:
                    v = legends.get_figure(int(victim_id))
                    if v:
                        victim_name = v.name
                except (ValueError, TypeError):
                    pass
            if slayer_id:
                try:
                    s = legends.get_figure(int(slayer_id))
                    if s:
                        slayer_name = s.name
                except (ValueError, TypeError):
                    pass
            if victim_name:
                year = death.get("year", "")
                details = f"slain by {slayer_name}" if slayer_name else "died"
                if year:
                    details += f" in year {year}"
                notable_deaths.append({
                    "name": victim_name,
                    "details": details,
                    "id": victim_id,
                    "entity_type": "figure",
                })

        # Regions
        for region in legends.regions:
            name = region.get("name", "")
            rtype = region.get("type", "").replace("_", " ").title()
            if name:
                regions_data.append({"name": name, "details": rtype})

        # Historical eras
        eras = []
        for era in legends.historical_eras:
            eras.append({
                "name": era.get("name", ""),
                "start_year": era.get("start_year", ""),
            })

        # Historical figures — show notable ones ranked by event involvement
        # Uses precomputed index from build_indexes()
        ranked_hfs = sorted(
            legends.historical_figures.items(),
            key=lambda x: legends.get_hf_event_count(x[0]),
            reverse=True,
        )[:500]

        for hfid, hf in ranked_hfs:
            if not hf.name:
                continue
            details_parts = []
            race = hf.race.replace('_', ' ').title() if hf.race else ''
            if hf.birth_year and hf.birth_year > 0:
                if hf.death_year and hf.death_year > 0:
                    details_parts.append(f"Born {hf.birth_year}, died {hf.death_year}")
                else:
                    details_parts.append(f"Born {hf.birth_year}")
            evt_count = legends.get_hf_event_count(hfid)
            if evt_count > 0:
                details_parts.append(f"{evt_count} historical events")
            # Check if they have an assumed identity
            for ident in legends.identities:
                if ident.get("histfig_id") == str(hfid):
                    details_parts.append(f"known to use aliases")
                    break
            figures.append({
                "id": hfid,
                "entity_type": "figure",
                "name": hf.name,
                "race": race,
                "description": " | ".join(details_parts) if details_parts else "",
            })

    # Build extended lore sections from legends_plus data
    artifacts = []
    written_works = []
    relationships = []
    identities = []
    geography = []

    if world_lore.is_loaded and world_lore._legends:
        legends = world_lore._legends

        # Artifacts — deduplicate by name, only show named ones
        seen_artifact_names: set[str] = set()
        for aid, art in legends.artifacts.items():
            if not art.name or art.name in seen_artifact_names:
                continue
            seen_artifact_names.add(art.name)
            details_parts = []
            if art.item_type:
                details_parts.append(art.item_type.replace("_", " "))
            if art.material:
                details_parts.append(art.material)
            if art.creator_hf_id:
                holder = legends.get_figure(art.creator_hf_id)
                if holder:
                    details_parts.append(f"held by {holder.name}")
            artifacts.append({
                "id": aid,
                "entity_type": "artifact",
                "name": art.name,
                "details": " \u2014 ".join(details_parts) if details_parts else "",
            })

        # Written works (books, poems, etc.)
        for wc in legends.written_contents:
            title = wc.get("title", "Untitled")
            wc_type = wc.get("type", "").replace("_", " ").title() if wc.get("type") else ""
            # Style may have ":N" suffix (e.g. "meandering:1") — strip it
            raw_style = wc.get("style", "")
            style = raw_style.split(":")[0].strip().title() if raw_style else ""
            author_id = wc.get("author")
            author_name = ""
            if author_id:
                try:
                    author = legends.get_figure(int(author_id))
                    if author:
                        author_name = author.name
                except (ValueError, TypeError):
                    pass
            details_parts = []
            if wc_type:
                details_parts.append(wc_type)
            if style:
                details_parts.append(f"style: {style}")
            if author_name:
                details_parts.append(f"by {author_name}")
            written_works.append({
                "id": wc.get("id", ""),
                "entity_type": "written_work",
                "title": title,
                "details": " \u2014 ".join(details_parts) if details_parts else "",
            })

        # Relationships (friendships, rivalries, romances)
        # Count all relationship types but only resolve names for display limit
        # Readable relationship type labels
        _rel_type_labels = {
            "lover": "Lover", "former_lover": "Former Lover",
            "childhood_friend": "Childhood Friend", "war_buddy": "War Buddy",
            "artistic_buddy": "Artistic Companion", "scholar_buddy": "Scholar Companion",
            "athlete_buddy": "Athletic Companion", "lieutenant": "Lieutenant",
            "jealous_obsession": "Jealous Obsession",
            "jealous_relationship_grudge": "Jealous Grudge",
            "religious_persecution_grudge": "Religious Grudge",
            "persecution_grudge": "Persecution Grudge",
            "supernatural_grudge": "Supernatural Grudge",
            "grudge": "Grudge", "business_rival": "Business Rival",
            "athletic_rival": "Athletic Rival",
        }

        rel_counts: dict[str, int] = {}
        for rel in legends.relationships:
            rtype = rel.get("relationship", "unknown")
            label = _rel_type_labels.get(rtype, rtype.replace("_", " ").title())
            rel_counts[label] = rel_counts.get(label, 0) + 1

        # Show a diverse sample — pick up to 5 per type, prioritize interesting types
        RELATIONSHIP_DISPLAY_LIMIT = 30
        _interesting_types = {"grudge", "war_buddy", "lieutenant", "jealous_obsession",
                              "religious_persecution_grudge", "supernatural_grudge",
                              "business_rival", "athletic_rival", "persecution_grudge",
                              "jealous_relationship_grudge", "scholar_buddy", "artistic_buddy",
                              "athlete_buddy", "childhood_friend", "former_lover", "lover"}
        type_shown: dict[str, int] = {}
        # First pass: interesting types
        for rel in legends.relationships:
            if len(relationships) >= RELATIONSHIP_DISPLAY_LIMIT:
                break
            rtype = rel.get("relationship", "")
            if rtype not in _interesting_types:
                continue
            if type_shown.get(rtype, 0) >= 5:
                continue
            source_id = rel.get("source_hf")
            target_id = rel.get("target_hf")
            year = rel.get("year", "")
            source_name = target_name = ""
            try:
                if source_id:
                    s = legends.get_figure(int(source_id))
                    if s: source_name = s.name
                if target_id:
                    t = legends.get_figure(int(target_id))
                    if t: target_name = t.name
            except (ValueError, TypeError):
                pass
            if source_name and target_name:
                label = _rel_type_labels.get(rtype, rtype.replace("_", " ").title())
                relationships.append({
                    "id": source_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "entity_type": "figure",
                    "description": f"{source_name} \u2014 {label} \u2014 {target_name}",
                    "year": year,
                })
                type_shown[rtype] = type_shown.get(rtype, 0) + 1

        # Identities (vampires, spies, assumed identities)
        for ident in legends.identities:
            hf_id = ident.get("histfig_id")
            name = ident.get("name", "")
            hf_name = ""
            if hf_id:
                try:
                    hf = legends.get_figure(int(hf_id))
                    if hf: hf_name = hf.name
                except (ValueError, TypeError):
                    pass
            if hf_name and name:
                identities.append({
                    "id": hf_id,
                    "entity_type": "figure",
                    "real_name": hf_name,
                    "assumed_name": name,
                })

        # Geography
        for peak in legends.mountain_peaks:
            name = peak.get("name", "")
            is_volcano = peak.get("is_volcano", "")
            height = peak.get("height", "")
            details = "Volcano" if is_volcano == "1" else "Mountain"
            if height:
                details += f", height {height}"
            geography.append({"id": peak.get("id", ""), "entity_type": "geography", "name": name, "type": "peak", "details": details})

        for land in legends.landmasses:
            geography.append({"id": land.get("id", ""), "entity_type": "geography", "name": land.get("name", ""), "type": "landmass", "details": "Landmass"})

        for river in legends.rivers:
            geography.append({"name": river.get("name", ""), "type": "river", "details": "River"})

        for wc in legends.world_constructions:
            geography.append({
                "name": wc.get("name", ""),
                "type": "construction",
                "details": wc.get("type", "Construction"),
            })

    # Build player's civilization summary with its own figures and artifacts
    if world_lore.is_loaded and world_lore._legends and player_civ_id >= 0:
        legends = world_lore._legends
        pciv = legends.get_civilization(player_civ_id)
        if pciv:
            # Figures belonging to player's civ
            pciv_figures = []
            for hfid, hf in legends.historical_figures.items():
                if hf.associated_civ_id == player_civ_id and hf.name:
                    details = ""
                    if hf.birth_year and hf.birth_year > 0:
                        details = f"Born {hf.birth_year}"
                        if hf.death_year and hf.death_year > 0:
                            details += f", died {hf.death_year}"
                    race = hf.race.replace('_', ' ').title() if hf.race else ''
                    pciv_figures.append({"name": hf.name, "hf_id": hfid, "race": race, "description": details})

            # Artifacts held by player civ figures
            pciv_artifacts = []
            pciv_hf_ids = {hfid for hfid, hf in legends.historical_figures.items() if hf.associated_civ_id == player_civ_id}
            seen_names: set[str] = set()
            for aid, art in legends.artifacts.items():
                if art.creator_hf_id in pciv_hf_ids and art.name and art.name not in seen_names:
                    seen_names.add(art.name)
                    details_parts = []
                    if art.item_type:
                        details_parts.append(art.item_type.replace("_", " "))
                    if art.material:
                        details_parts.append(art.material)
                    pciv_artifacts.append({"name": art.name, "artifact_id": aid, "details": " \u2014 ".join(details_parts)})

            race_display = pciv.race.replace('_', ' ').title() if pciv.race else ''
            sub_ents = _build_sub_entities(legends, pciv)
            sub_data = _build_sub_entities_structured(legends, pciv)

            player_civ_data = {
                "id": player_civ_id,
                "name": pciv.name,
                "race": race_display,
                "details": "",
                "sub_entities": sub_ents,
                "org_data": sub_data,
                "figures": pciv_figures[:20],
                "artifacts": pciv_artifacts[:20],
            }

    # Apply sensible limits to "other" sections (search reveals all)
    # Load saved sagas
    saved_sagas = []
    try:
        fortress_dir = _get_fortress_dir(config, metadata)
        saga_path = fortress_dir / "saga.json"
        if saga_path.exists():
            import json as _json
            saved_sagas = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        pass

    return templates.TemplateResponse(request=request, name="lore.html", context={
        **ctx,
        "content_class": "content-wide",
        "lore_loaded": world_lore.is_loaded,
        "saved_sagas": saved_sagas,
        "player_civ": player_civ_data,
        "eras": eras if world_lore.is_loaded and world_lore._legends else [],
        "civilizations": civilizations[:500],
        "wars": wars[:500],
        "battles": battles[:500],
        "figures": figures[:500],
        "artifacts": artifacts[:500],
        "written_works": written_works[:500],
        "relationships": relationships[:500],
        "relationship_counts": rel_counts if world_lore.is_loaded and world_lore._legends else {},
        "identities": identities,
        "geography": geography[:500],
        "poetic_forms": world_lore._legends.poetic_forms if world_lore.is_loaded and world_lore._legends else [],
        "musical_forms": world_lore._legends.musical_forms if world_lore.is_loaded and world_lore._legends else [],
        "dance_forms": world_lore._legends.dance_forms if world_lore.is_loaded and world_lore._legends else [],
        "beast_attacks": beast_attacks[:500],
        "site_conquests": site_conquests[:500],
        "persecutions": persecutions[:500],
        "duels": duels[:500],
        "abductions": abductions[:500],
        "thefts": thefts[:500],
        "purges": purges[:500],
        "overthrown": overthrown[:500],
        "notable_deaths": notable_deaths[:500],
        "regions_data": regions_data[:500],
        # True total counts for section headers
        "total_counts": {
            "civilizations": len(civilizations),
            "wars": len(wars),
            "battles": len(battles),
            "figures": sum(1 for hf in legends.historical_figures.values() if hf.name),
            "artifacts": len(artifacts),
            "written_works": len(written_works),
            "relationships": len(relationships),
            "beast_attacks": len(beast_attacks),
            "site_conquests": len(site_conquests),
            "persecutions": len(persecutions),
            "duels": len(duels),
            "abductions": len(abductions),
            "thefts": len(thefts),
            "purges": len(purges),
            "overthrown": len(overthrown),
            "notable_deaths": len(notable_deaths),
            "regions_data": len(regions_data),
            "geography": len(geography),
        },
    })
