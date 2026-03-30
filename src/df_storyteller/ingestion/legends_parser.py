"""SAX streaming parser for DFHack exportlegends XML.

Legends XML exports can exceed 500MB, so we use iterparse (pull-style SAX)
to stream through the file without loading the full DOM into memory.

Reference: https://docs.dfhack.org/en/stable/ — exportlegends tool
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import iterparse

from df_storyteller.schema.entities import (
    Artifact,
    Civilization,
    HistoricalFigure,
    Site,
)

logger = logging.getLogger(__name__)


class LegendsData:
    """Indexed legends data built from a streaming parse of the XML export."""

    def __init__(self) -> None:
        self.historical_figures: dict[int, HistoricalFigure] = {}
        self.sites: dict[int, Site] = {}
        self.civilizations: dict[int, Civilization] = {}
        self.artifacts: dict[int, Artifact] = {}
        self.historical_events: list[dict[str, Any]] = []
        self.event_collections: list[dict[str, Any]] = []
        # Extended data from legends_plus
        self.relationships: list[dict[str, Any]] = []
        self.written_contents: list[dict[str, Any]] = []
        self.identities: list[dict[str, Any]] = []
        self.world_constructions: list[dict[str, Any]] = []
        self.landmasses: list[dict[str, Any]] = []
        self.mountain_peaks: list[dict[str, Any]] = []
        self.rivers: list[dict[str, Any]] = []
        self.poetic_forms: list[dict[str, Any]] = []
        self.musical_forms: list[dict[str, Any]] = []
        self.dance_forms: list[dict[str, Any]] = []
        self.entity_populations: list[dict[str, Any]] = []
        # Additional data for LLM context (not all shown on Lore page)
        self.regions: list[dict[str, Any]] = []
        self.historical_eras: list[dict[str, Any]] = []
        self.battles: list[dict[str, Any]] = []      # Extracted from event_collections
        self.beast_attacks: list[dict[str, Any]] = [] # Extracted from event_collections
        self.site_conquests: list[dict[str, Any]] = [] # Extracted from event_collections
        self.persecutions: list[dict[str, Any]] = []  # Extracted from event_collections
        self.notable_deaths: list[dict[str, Any]] = [] # Extracted from historical_events
        self.duels: list[dict[str, Any]] = []          # Extracted from event_collections
        self.abductions: list[dict[str, Any]] = []     # Extracted from event_collections
        self.thefts: list[dict[str, Any]] = []         # Extracted from event_collections
        self.purges: list[dict[str, Any]] = []         # Extracted from event_collections
        self.entity_overthrown: list[dict[str, Any]] = [] # Extracted from event_collections

    def get_figure(self, hf_id: int) -> HistoricalFigure | None:
        return self.historical_figures.get(hf_id)

    def get_site(self, site_id: int) -> Site | None:
        return self.sites.get(site_id)

    def get_civilization(self, entity_id: int) -> Civilization | None:
        return self.civilizations.get(entity_id)

    def get_artifact(self, artifact_id: int) -> Artifact | None:
        return self.artifacts.get(artifact_id)

    def get_wars_involving(self, entity_id: int) -> list[dict[str, Any]]:
        """Return war event collections involving a given civilization."""
        # Use precomputed index if available
        if hasattr(self, '_wars_by_entity'):
            return self._wars_by_entity.get(entity_id, [])
        # Fallback to scan
        wars = []
        for ec in self.event_collections:
            if ec.get("type") == "war":
                aggressors = ec.get("aggressor_ent_id", [])
                defenders = ec.get("defender_ent_id", [])
                if not isinstance(aggressors, list):
                    aggressors = [aggressors]
                if not isinstance(defenders, list):
                    defenders = [defenders]
                str_id = str(entity_id)
                if str_id in aggressors or str_id in defenders:
                    wars.append(ec)
        return wars

    def build_indexes(self) -> None:
        """Pre-compute indexes for fast lookups. Call after all data is loaded."""
        from collections import defaultdict

        # War index: entity_id -> [war event collections]
        self._wars_by_entity: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for ec in self.event_collections:
            if ec.get("type") == "war":
                for key in ("aggressor_ent_id", "defender_ent_id"):
                    ids = ec.get(key, [])
                    if not isinstance(ids, list):
                        ids = [ids]
                    for eid_str in ids:
                        try:
                            self._wars_by_entity[int(eid_str)].append(ec)
                        except (ValueError, TypeError):
                            pass

        # Event collection index by ID (for war/battle detail lookups)
        self._event_collections_by_id: dict[str, dict[str, Any]] = {}
        for ec in self.event_collections:
            ec_id = ec.get("id", "")
            if ec_id:
                self._event_collections_by_id[str(ec_id)] = ec

        # HF event involvement count + per-HF event lists
        self._hf_event_count: dict[int, int] = defaultdict(int)
        self._hf_events: dict[int, list[dict[str, Any]]] = defaultdict(list)
        # Site event index: site_id -> Counter of event types
        self._site_event_types: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for evt in self.historical_events:
            for key in ("hfid", "hfid_1", "hfid_2", "slayer_hfid", "group_hfid"):
                hfid_str = evt.get(key)
                if hfid_str:
                    try:
                        hfid_int = int(hfid_str)
                        self._hf_event_count[hfid_int] += 1
                        self._hf_events[hfid_int].append(evt)
                    except (ValueError, TypeError):
                        pass
            site_id_str = evt.get("site_id")
            if site_id_str and site_id_str != "-1":
                try:
                    self._site_event_types[int(site_id_str)][evt.get("type", "unknown")] += 1
                except (ValueError, TypeError):
                    pass

        # HF relationship index: hf_id -> [relationships where they are source or target]
        self._hf_relationships: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for rel in self.relationships:
            for key in ("source_hf", "target_hf"):
                hfid_str = rel.get(key)
                if hfid_str:
                    try:
                        self._hf_relationships[int(hfid_str)].append(rel)
                    except (ValueError, TypeError):
                        pass

        # Family relationship index: hf_id -> {"parents": [ids], "children": [ids], "spouse": [ids]}
        # Built from hf_links on historical figures (the authoritative source for family data)
        self._hf_family: dict[int, dict[str, list[int]]] = defaultdict(lambda: {"parents": [], "children": [], "spouse": []})
        for hfid, hf in self.historical_figures.items():
            for link in hf.hf_links:
                ltype = link.get("type", "").lower().replace(" ", "_")
                other_id = link.get("hfid")
                if other_id is None:
                    continue
                if ltype in ("mother", "father"):
                    # This HF's mother/father is other_id
                    if other_id not in self._hf_family[hfid]["parents"]:
                        self._hf_family[hfid]["parents"].append(other_id)
                    if hfid not in self._hf_family[other_id]["children"]:
                        self._hf_family[other_id]["children"].append(hfid)
                elif ltype == "child":
                    # This HF's child is other_id
                    if other_id not in self._hf_family[hfid]["children"]:
                        self._hf_family[hfid]["children"].append(other_id)
                    if hfid not in self._hf_family[other_id]["parents"]:
                        self._hf_family[other_id]["parents"].append(hfid)
                elif ltype in ("spouse", "deceased_spouse", "former_spouse"):
                    if other_id not in self._hf_family[hfid]["spouse"]:
                        self._hf_family[hfid]["spouse"].append(other_id)
                    if hfid not in self._hf_family[other_id]["spouse"]:
                        self._hf_family[other_id]["spouse"].append(hfid)

    def get_event_collection(self, ec_id: int | str) -> dict[str, Any] | None:
        """Get an event collection (war, battle, siege) by ID."""
        if hasattr(self, '_event_collections_by_id'):
            return self._event_collections_by_id.get(str(ec_id))
        for ec in self.event_collections:
            if ec.get("id") == str(ec_id):
                return ec
        return None

    def get_site_event_types(self, site_id: int) -> dict[str, int]:
        """Get event type counts for a site."""
        if hasattr(self, '_site_event_types'):
            return dict(self._site_event_types.get(site_id, {}))
        return {}

    def get_hf_event_count(self, hf_id: int) -> int:
        """Get number of historical events involving a figure."""
        if hasattr(self, '_hf_event_count'):
            return self._hf_event_count.get(hf_id, 0)
        return 0

    def get_hf_events(self, hf_id: int) -> list[dict[str, Any]]:
        """Get all historical events involving a figure. Uses precomputed index."""
        if hasattr(self, '_hf_events'):
            return self._hf_events.get(hf_id, [])
        return []

    def get_hf_relationships(self, hf_id: int) -> list[dict[str, Any]]:
        """Get all relationships involving a figure. Uses precomputed index."""
        if hasattr(self, '_hf_relationships'):
            return self._hf_relationships.get(hf_id, [])
        return []

    def get_hf_family(self, hf_id: int) -> dict[str, list[int]]:
        """Get family connections: parents, children, spouse. Uses precomputed index."""
        if hasattr(self, '_hf_family'):
            return self._hf_family.get(hf_id, {"parents": [], "children": [], "spouse": []})
        return {"parents": [], "children": [], "spouse": []}

    def stats(self) -> dict[str, int]:
        return {
            "historical_figures": len(self.historical_figures),
            "sites": len(self.sites),
            "civilizations": len(self.civilizations),
            "artifacts": len(self.artifacts),
            "events": len(self.historical_events),
            "event_collections": len(self.event_collections),
            "relationships": len(self.relationships),
            "written_contents": len(self.written_contents),
            "identities": len(self.identities),
            "world_constructions": len(self.world_constructions),
            "mountain_peaks": len(self.mountain_peaks),
            "rivers": len(self.rivers),
        }


def _text(elem: Any, tag: str, default: str = "") -> str:
    child = elem.find(tag)
    return child.text if child is not None and child.text else default


def _int(elem: Any, tag: str, default: int = 0) -> int:
    text = _text(elem, tag)
    if text and text != "-1":
        try:
            return int(text)
        except ValueError:
            pass
    return default


def _int_or_none(elem: Any, tag: str) -> int | None:
    text = _text(elem, tag)
    if text and text != "-1":
        try:
            return int(text)
        except ValueError:
            pass
    return None


def _parse_historical_figure(elem: Any) -> HistoricalFigure:
    # Collect all sphere tags (deities can have multiple)
    spheres = [s.text for s in elem.findall("sphere") if s.text]
    is_deity = elem.find("deity") is not None

    # Figure type (deity, megabeast, historical figure, etc.)
    hf_type = _text(elem, "type")
    if not hf_type:
        hf_type = _text(elem, "hf_type")
    if not hf_type and is_deity:
        hf_type = "deity"

    # Notable deeds / goals
    notable_deeds: list[str] = []
    for goal in elem.findall("goal"):
        if goal.text:
            notable_deeds.append(goal.text.replace("_", " "))
    for deed in elem.findall("achievement"):
        if deed.text:
            notable_deeds.append(deed.text.replace("_", " "))

    # HF links (family: child, mother, father, spouse, lover, deity, etc.)
    hf_links = []
    for link in elem.findall("hf_link"):
        link_data: dict[str, Any] = {}
        lt = link.find("link_type")
        if lt is not None and lt.text:
            link_data["type"] = lt.text
        hfid_el = link.find("hfid")
        if hfid_el is not None and hfid_el.text:
            link_data["hfid"] = int(hfid_el.text)
        if link_data:
            hf_links.append(link_data)

    # Entity links (positions held in civilizations)
    entity_links = []
    for link in elem.findall("entity_link"):
        link_data: dict[str, Any] = {}
        lt = link.find("link_type")
        if lt is not None and lt.text:
            link_data["type"] = lt.text
        eid = link.find("entity_id")
        if eid is not None and eid.text:
            link_data["entity_id"] = int(eid.text)
        if link_data:
            entity_links.append(link_data)

    # Active interactions (curses like vampirism, necromancy)
    active_interactions = [ai.text for ai in elem.findall("active_interaction") if ai.text]

    # Skills
    skills = []
    for sk in elem.findall("hf_skill"):
        skill_data: dict[str, Any] = {}
        sn = sk.find("skill")
        if sn is not None and sn.text:
            skill_data["skill"] = sn.text
        tip = sk.find("total_ip")
        if tip is not None and tip.text:
            skill_data["total_ip"] = int(tip.text)
        if skill_data:
            skills.append(skill_data)

    # Journey pets
    journey_pets = [jp.text for jp in elem.findall("journey_pet") if jp.text]

    # Intrigue plots
    intrigue_plots = []
    for plot in elem.findall("intrigue_plot"):
        plot_data: dict[str, Any] = {"type": _text(plot, "type")}
        if plot.find("on_hold") is not None:
            plot_data["on_hold"] = True
        actors = []
        for actor in plot.findall("intrigue_actor"):
            actor_data: dict[str, Any] = {}
            a_hfid = actor.find("hfid")
            if a_hfid is not None and a_hfid.text:
                actor_data["hfid"] = int(a_hfid.text)
            a_eid = actor.find("entity_id")
            if a_eid is not None and a_eid.text:
                actor_data["entity_id"] = int(a_eid.text)
            a_role = actor.find("role")
            if a_role is not None and a_role.text:
                actor_data["role"] = a_role.text
            a_strat = actor.find("strategy")
            if a_strat is not None and a_strat.text:
                actor_data["strategy"] = a_strat.text
            if actor.find("promised_actor_immortality") is not None:
                actor_data["promised_immortality"] = True
            if actor_data:
                actors.append(actor_data)
        if actors:
            plot_data["actors"] = actors
        if plot_data.get("type"):
            intrigue_plots.append(plot_data)

    # Emotional bonds (love, respect, trust, loyalty, fear toward other HFs)
    emotional_bonds = []
    for bond_hfid in elem.findall("hf_id"):
        if bond_hfid.text:
            # The love/respect/trust/loyalty/fear tags follow the hf_id
            bond: dict[str, Any] = {"hf_id": int(bond_hfid.text)}
            # These sibling elements follow hf_id in sequence
            nxt = bond_hfid
            for field in ("love", "respect", "trust", "loyalty", "fear"):
                nxt = nxt.getnext() if hasattr(nxt, 'getnext') else None
                # Fallback: search in parent
            for field in ("love", "respect", "trust", "loyalty", "fear"):
                val = elem.find(field)
                # Can't reliably get positional siblings with ElementTree — skip for now
            emotional_bonds.append(bond)
    # Parse from <relationship_profile_hf_visual> containers
    emotional_bonds = []
    for rp in elem.findall("relationship_profile_hf_visual"):
        rp_hfid = rp.find("hf_id")
        if rp_hfid is not None and rp_hfid.text:
            emotional_bonds.append({
                "hf_id": int(rp_hfid.text),
                "love": _int(rp, "love"),
                "respect": _int(rp, "respect"),
                "trust": _int(rp, "trust"),
                "loyalty": _int(rp, "loyalty"),
                "fear": _int(rp, "fear"),
                "meet_count": _int(rp, "meet_count"),
                "last_meet_year": _int(rp, "last_meet_year"),
            })

    # Vague relationships
    vague_relationships = []
    for vr in elem.findall("vague_relationship"):
        vr_hfid = vr.find("hfid")
        if vr_hfid is not None and vr_hfid.text:
            # The relationship type is the first child element (before hfid)
            vr_type = ""
            for child in vr:
                if child.tag != "hfid" and child.tag not in ("local_id",):
                    vr_type = child.tag
                    break
            vague_relationships.append({"type": vr_type.replace("_", " "), "hfid": int(vr_hfid.text)})

    # Former positions
    former_positions = []
    for fp in elem.findall("entity_former_position_link"):
        fp_data: dict[str, Any] = {}
        fp_ppid = fp.find("position_profile_id")
        if fp_ppid is not None and fp_ppid.text:
            fp_data["position_profile_id"] = fp_ppid.text
        fp_eid = fp.find("entity_id")
        if fp_eid is not None and fp_eid.text:
            fp_data["entity_id"] = int(fp_eid.text)
        fp_sy = fp.find("start_year")
        if fp_sy is not None and fp_sy.text:
            fp_data["start_year"] = fp_sy.text
        fp_ey = fp.find("end_year")
        if fp_ey is not None and fp_ey.text:
            fp_data["end_year"] = fp_ey.text
        if fp_data:
            former_positions.append(fp_data)

    return HistoricalFigure(
        hf_id=_int(elem, "id"),
        name=_text(elem, "name"),
        race=_text(elem, "race"),
        caste=_text(elem, "caste"),
        birth_year=_int(elem, "birth_year"),
        death_year=_int_or_none(elem, "death_year"),
        associated_civ_id=_int_or_none(elem, "entity_id"),
        spheres=spheres,
        is_deity=is_deity,
        hf_type=hf_type,
        notable_deeds=notable_deeds,
        hf_links=hf_links,
        entity_links=entity_links,
        active_interactions=active_interactions,
        skills=skills,
        journey_pets=journey_pets,
        intrigue_plots=intrigue_plots,
        emotional_bonds=emotional_bonds,
        vague_relationships=vague_relationships,
        former_positions=former_positions,
    )


def _parse_site(elem: Any) -> Site:
    # Parse structures at this site
    structures = []
    for struct in elem.findall("structure"):
        struct_data: dict[str, Any] = {}
        sid = struct.find("id")
        if sid is not None and sid.text:
            struct_data["id"] = int(sid.text)
        sname = struct.find("name")
        if sname is not None and sname.text:
            struct_data["name"] = sname.text
        stype = struct.find("type")
        if stype is not None and stype.text:
            struct_data["type"] = stype.text
        deity = struct.find("deity")
        if deity is not None and deity.text:
            struct_data["deity_hf_id"] = int(deity.text)
        eid = struct.find("entity_id")
        if eid is not None and eid.text:
            struct_data["entity_id"] = int(eid.text)
        if struct_data:
            structures.append(struct_data)

    coords = None
    coord_elem = elem.find("coords")
    if coord_elem is not None and coord_elem.text:
        parts = coord_elem.text.split(",")
        if len(parts) == 2:
            try:
                coords = (int(parts[0]), int(parts[1]))
            except ValueError:
                pass

    # Site properties (houses, workshops, etc.) — inside <site_properties> container
    properties = []
    props_container = elem.find("site_properties")
    prop_source = props_container if props_container is not None else elem
    for sp in prop_source.findall("site_property"):
        prop: dict[str, Any] = {}
        sp_id = sp.find("id")
        if sp_id is not None and sp_id.text:
            prop["id"] = sp_id.text
        sp_type = sp.find("type")
        if sp_type is not None and sp_type.text:
            prop["type"] = sp_type.text
        sp_owner = sp.find("owner_hfid")
        if sp_owner is not None and sp_owner.text and sp_owner.text != "-1":
            prop["owner_hfid"] = int(sp_owner.text)
        if prop:
            properties.append(prop)

    # Owner civilization
    owner_civ_id = _int_or_none(elem, "cur_owner_id")
    if owner_civ_id is None:
        owner_civ_id = _int_or_none(elem, "civ_id")

    return Site(
        site_id=_int(elem, "id"),
        name=_text(elem, "name"),
        site_type=_text(elem, "type"),
        owner_civ_id=owner_civ_id,
        structures=structures,
        coordinates=coords,
        properties=properties,
    )


def _parse_entity(elem: Any) -> Civilization:
    # Extract histfig_ids for leaders and site links
    leader_hf_ids = []
    for ep in elem.findall("entity_position_assignment"):
        hfid = ep.find("histfig")
        if hfid is not None and hfid.text:
            try:
                leader_hf_ids.append(int(hfid.text))
            except ValueError:
                pass

    # Extract controlled sites
    sites: list[int] = []
    for sl in elem.findall("entity_link"):
        link_type = sl.find("type")
        target = sl.find("target")
        if link_type is not None and target is not None and target.text:
            if link_type.text in ("SITE_GOV", "SITE_LINK"):
                try:
                    sites.append(int(target.text))
                except ValueError:
                    pass

    # Extract entity positions (monarch, general, etc.) — needed to resolve position_id in events
    entity_positions: list[dict[str, Any]] = []
    for ep in elem.findall("entity_position"):
        pos_data: dict[str, Any] = {}
        pid = ep.find("id")
        if pid is not None and pid.text:
            pos_data["id"] = pid.text
        pname = ep.find("name")
        if pname is not None and pname.text:
            pos_data["name"] = pname.text
        pname_m = ep.find("name_male")
        if pname_m is not None and pname_m.text:
            pos_data["name_male"] = pname_m.text
        pname_f = ep.find("name_female")
        if pname_f is not None and pname_f.text:
            pos_data["name_female"] = pname_f.text
        if pos_data:
            entity_positions.append(pos_data)

    # Extract occasion definitions (festivals with schedules)
    occasions: list[dict[str, Any]] = []
    for occ in elem.findall("occasion"):
        occ_data: dict[str, Any] = {}
        oid = occ.find("id")
        if oid is not None and oid.text:
            occ_data["id"] = oid.text
        oname = occ.find("name")
        if oname is not None and oname.text:
            occ_data["name"] = oname.text
        # Parse schedules (activities within the festival)
        schedules: list[dict[str, Any]] = []
        for sched in occ.findall("schedule"):
            sched_data: dict[str, Any] = {}
            sid = sched.find("id")
            if sid is not None and sid.text:
                sched_data["id"] = sid.text
            stype = sched.find("type")
            if stype is not None and stype.text:
                sched_data["type"] = stype.text
            # Item type for competitions
            itype = sched.find("item_type")
            if itype is not None and itype.text:
                sched_data["item_type"] = itype.text
            isub = sched.find("item_subtype")
            if isub is not None and isub.text:
                sched_data["item_subtype"] = isub.text
            # Features (costumes, incense, banners, etc.)
            features: list[str] = []
            for feat in sched.findall("feature"):
                ftype = feat.find("type")
                if ftype is not None and ftype.text:
                    features.append(ftype.text)
            if features:
                sched_data["features"] = features
            if sched_data:
                schedules.append(sched_data)
        if schedules:
            occ_data["schedules"] = schedules
        if occ_data:
            occasions.append(occ_data)

    civ = Civilization(
        entity_id=_int(elem, "id"),
        name=_text(elem, "name"),
        race=_text(elem, "race"),
        leader_hf_ids=leader_hf_ids,
        sites=sites,
    )
    # Store extended metadata
    civ._entity_type = _text(elem, "type")  # type: ignore[attr-defined]
    civ._child_ids = [int(c.text) for c in elem.findall("child") if c.text]  # type: ignore[attr-defined]
    civ._worship_id = _int_or_none(elem, "worship_id")  # type: ignore[attr-defined] — deity HF for religions
    civ._profession = _text(elem, "profession")  # type: ignore[attr-defined] — craft focus for guilds
    civ._entity_positions = entity_positions  # type: ignore[attr-defined] — position titles (monarch, general, etc.)
    civ._occasions = occasions  # type: ignore[attr-defined] — festival definitions with schedules
    # Honors / rank system
    honors: list[dict[str, Any]] = []
    for hon in elem.findall("honor"):
        hon_data: dict[str, Any] = {}
        h_id = hon.find("id")
        if h_id is not None and h_id.text:
            hon_data["id"] = h_id.text
        h_name = hon.find("name")
        if h_name is not None and h_name.text:
            hon_data["name"] = h_name.text
        h_prec = hon.find("gives_precedence")
        if h_prec is not None and h_prec.text:
            hon_data["gives_precedence"] = int(h_prec.text)
        h_skill = hon.find("required_skill")
        if h_skill is not None and h_skill.text:
            hon_data["required_skill"] = h_skill.text
        h_ip = hon.find("required_skill_ip_total")
        if h_ip is not None and h_ip.text:
            hon_data["required_skill_ip_total"] = int(h_ip.text)
        h_bat = hon.find("required_battles")
        if h_bat is not None and h_bat.text:
            hon_data["required_battles"] = int(h_bat.text)
        if hon_data:
            honors.append(hon_data)
    civ._honors = honors  # type: ignore[attr-defined]
    return civ


def _parse_artifact(elem: Any) -> Artifact:
    # Artifact name can be in <name>, or nested in <item><name_string>
    name = _text(elem, "name")
    if not name:
        item_elem = elem.find("item")
        if item_elem is not None:
            name = _text(item_elem, "name_string")
    holder = _int_or_none(elem, "holder_hfid")
    # Description can be in <item><description> or top-level <description>
    description = _text(elem, "description")
    if not description:
        item_elem = elem.find("item")
        if item_elem is not None:
            description = _text(item_elem, "description")
    # Pages (for books — page_number + page_written_content_id inside <item>)
    pages = []
    item_elem = elem.find("item")
    if item_elem is not None:
        page_nums = [e.text for e in item_elem.findall("page_number") if e.text]
        page_wc_ids = [e.text for e in item_elem.findall("page_written_content_id") if e.text]
        for i, pn in enumerate(page_nums):
            wc_id = page_wc_ids[i] if i < len(page_wc_ids) else ""
            if pn and wc_id:
                pages.append({"page_number": int(pn), "written_content_id": wc_id})

    return Artifact(
        artifact_id=_int(elem, "id"),
        name=name,
        item_type=_text(elem, "item_type"),
        material=_text(elem, "mat"),
        creator_hf_id=holder,
        site_id=_int_or_none(elem, "site_id"),
        description=description,
        pages=pages,
    )


def _parse_historical_event(elem: Any) -> dict[str, Any]:
    event: dict[str, Any] = {}
    for child in elem:
        if child.text:
            event[child.tag] = child.text
    return event


def _parse_event_collection(elem: Any) -> dict[str, Any]:
    collection: dict[str, Any] = {}
    list_fields: dict[str, list[str]] = {}

    for child in elem:
        if child.tag in collection or child.tag in list_fields:
            # Multiple children with same tag → convert to list
            if child.tag not in list_fields:
                list_fields[child.tag] = [collection.pop(child.tag)]
            list_fields[child.tag].append(child.text or "")
        else:
            collection[child.tag] = child.text or ""

    collection.update(list_fields)
    return collection


# Section tag → (parser function, attribute name on LegendsData, key field)
_SECTION_MAP = {
    "historical_figures": ("historical_figure", _parse_historical_figure, "historical_figures", "hf_id"),
    "sites": ("site", _parse_site, "sites", "site_id"),
    "entities": ("entity", _parse_entity, "civilizations", "entity_id"),
    "artifacts": ("artifact", _parse_artifact, "artifacts", "artifact_id"),
}


def parse_legends_xml(path: str | Path) -> LegendsData:
    """Stream-parse a legends XML export and return indexed data.

    Uses iterparse to avoid loading the full DOM — safe for 500MB+ files.
    """
    path = Path(path)
    data = LegendsData()
    current_section: str | None = None
    depth = 0

    logger.info("Parsing legends XML: %s", path)

    # DF writes XML with a UTF-8 declaration but embeds CP437-encoded bytes
    # for special characters (ö, ü, â, etc.). Strategy:
    # 1. Try UTF-8 first — if no replacement chars, it's clean
    # 2. If we get replacements, re-decode as CP437 to preserve diacritics
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        # Has replacement chars — CP437 bytes present. Re-decode.
        # Strip the XML declaration first (it says UTF-8 but lies)
        text = raw.decode("cp437")
        # Fix the XML declaration to match actual encoding
        text = re.sub(r'<\?xml[^?]*\?>', '<?xml version="1.0"?>', text)
    # Remove characters illegal in XML 1.0 (anything below 0x20 except tab/newline/return)
    text = re.sub(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]", "", text)
    source = io.StringIO(text)

    for event, elem in iterparse(source, events=("start", "end")):
        if event == "start":
            depth += 1
            # Detect top-level sections (depth 2 = direct child of root)
            if depth == 2:
                current_section = elem.tag
            continue

        # event == "end"
        depth -= 1

        if depth == 1:
            # Leaving a section
            current_section = None
            elem.clear()
            continue

        if depth != 2 or current_section is None:
            continue

        # Parse items within known sections
        if current_section in _SECTION_MAP:
            item_tag, parser_fn, attr_name, key_field = _SECTION_MAP[current_section]
            if elem.tag == item_tag:
                obj = parser_fn(elem)
                getattr(data, attr_name)[getattr(obj, key_field)] = obj
                elem.clear()

        elif current_section == "historical_events" and elem.tag == "historical_event":
            data.historical_events.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "historical_event_collections" and elem.tag == "historical_event_collection":
            data.event_collections.append(_parse_event_collection(elem))
            elem.clear()

        elif current_section == "regions" and elem.tag == "region":
            data.regions.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "historical_eras" and elem.tag == "historical_era":
            data.historical_eras.append(_parse_historical_event(elem))
            elem.clear()

        # Extended sections from legends_plus — all use generic dict parsing
        elif current_section == "historical_event_relationships" and elem.tag == "historical_event_relationship":
            data.relationships.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "written_contents" and elem.tag == "written_content":
            data.written_contents.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "identities" and elem.tag == "identity":
            data.identities.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "world_constructions" and elem.tag == "world_construction":
            data.world_constructions.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "landmasses" and elem.tag == "landmass":
            data.landmasses.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "mountain_peaks" and elem.tag == "mountain_peak":
            data.mountain_peaks.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "rivers" and elem.tag == "river":
            data.rivers.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "poetic_forms" and elem.tag == "poetic_form":
            data.poetic_forms.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "musical_forms" and elem.tag == "musical_form":
            data.musical_forms.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "dance_forms" and elem.tag == "dance_form":
            data.dance_forms.append(_parse_historical_event(elem))
            elem.clear()

        elif current_section == "entity_populations" and elem.tag == "entity_population":
            data.entity_populations.append(_parse_historical_event(elem))
            elem.clear()

    # Post-process: categorize event collections into typed lists
    for ec in data.event_collections:
        ec_type = ec.get("type", "")
        if ec_type == "battle":
            data.battles.append(ec)
        elif ec_type == "beast attack":
            data.beast_attacks.append(ec)
        elif ec_type == "site conquered":
            data.site_conquests.append(ec)
        elif ec_type == "persecution":
            data.persecutions.append(ec)
        elif ec_type == "duel":
            data.duels.append(ec)
        elif ec_type == "abduction":
            data.abductions.append(ec)
        elif ec_type == "theft":
            data.thefts.append(ec)
        elif ec_type == "purge":
            data.purges.append(ec)
        elif ec_type == "entity overthrown":
            data.entity_overthrown.append(ec)

    # Extract notable deaths (with slayer info)
    for evt in data.historical_events:
        if evt.get("type") == "hf died" and evt.get("slayer_hfid"):
            data.notable_deaths.append(evt)

    # Build indexes for fast lookups
    data.build_indexes()

    logger.info("Legends parsed: %s", data.stats())
    return data


def load_legends(path: str) -> dict[str, int]:
    """Load legends XML and return stats. Called by CLI."""
    data = parse_legends_xml(path)
    return data.stats()
