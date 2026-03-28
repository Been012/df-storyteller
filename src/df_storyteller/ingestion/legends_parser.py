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

        # HF event involvement count
        self._hf_event_count: dict[int, int] = defaultdict(int)
        # Site event index: site_id -> Counter of event types
        self._site_event_types: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for evt in self.historical_events:
            for key in ("hfid", "hfid_1", "hfid_2", "slayer_hfid", "group_hfid"):
                hfid_str = evt.get(key)
                if hfid_str:
                    try:
                        self._hf_event_count[int(hfid_str)] += 1
                    except (ValueError, TypeError):
                        pass
            site_id_str = evt.get("site_id")
            if site_id_str and site_id_str != "-1":
                try:
                    self._site_event_types[int(site_id_str)][evt.get("type", "unknown")] += 1
                except (ValueError, TypeError):
                    pass

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
    return HistoricalFigure(
        hf_id=_int(elem, "id"),
        name=_text(elem, "name"),
        race=_text(elem, "race"),
        birth_year=_int(elem, "birth_year"),
        death_year=_int_or_none(elem, "death_year"),
        associated_civ_id=_int_or_none(elem, "entity_id"),
        spheres=spheres,
        is_deity=is_deity,
    )


def _parse_site(elem: Any) -> Site:
    return Site(
        site_id=_int(elem, "id"),
        name=_text(elem, "name"),
        site_type=_text(elem, "type"),
    )


def _parse_entity(elem: Any) -> Civilization:
    civ = Civilization(
        entity_id=_int(elem, "id"),
        name=_text(elem, "name"),
        race=_text(elem, "race"),
    )
    # Store extended metadata
    civ._entity_type = _text(elem, "type")  # type: ignore[attr-defined]
    civ._child_ids = [int(c.text) for c in elem.findall("child") if c.text]  # type: ignore[attr-defined]
    civ._worship_id = _int_or_none(elem, "worship_id")  # type: ignore[attr-defined] — deity HF for religions
    civ._profession = _text(elem, "profession")  # type: ignore[attr-defined] — craft focus for guilds
    return civ


def _parse_artifact(elem: Any) -> Artifact:
    # Artifact name can be in <name>, or nested in <item><name_string>
    name = _text(elem, "name")
    if not name:
        item_elem = elem.find("item")
        if item_elem is not None:
            name = _text(item_elem, "name_string")
    holder = _int_or_none(elem, "holder_hfid")
    return Artifact(
        artifact_id=_int(elem, "id"),
        name=name,
        item_type=_text(elem, "item_type"),
        material=_text(elem, "mat"),
        creator_hf_id=holder,
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
