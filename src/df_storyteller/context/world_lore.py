"""Legends-derived lore index for story context enrichment.

Provides narrative-ready summaries from parsed legends XML data.
Reference: https://docs.dfhack.org/en/stable/ — exportlegends tool
"""

from __future__ import annotations

from df_storyteller.context.character_tracker import normalize_name
from df_storyteller.ingestion.legends_parser import LegendsData


class WorldLore:
    """Searchable index into legends data for narrative context."""

    def __init__(self, legends: LegendsData | None = None) -> None:
        self._legends = legends

    @property
    def is_loaded(self) -> bool:
        return self._legends is not None

    def load(self, legends: LegendsData) -> None:
        self._legends = legends

    def get_figure_biography(self, hf_id: int) -> str:
        """Generate a narrative summary of a historical figure."""
        if not self._legends:
            return ""

        figure = self._legends.get_figure(hf_id)
        if not figure:
            return ""

        lines = [f"{figure.name} ({figure.race})"]
        lines.append(f"Born in year {figure.birth_year}")

        if figure.death_year:
            lines.append(f"Died in year {figure.death_year}")

        if figure.associated_civ_id:
            civ = self._legends.get_civilization(figure.associated_civ_id)
            if civ:
                lines.append(f"Associated with {civ.name}")

        # Find events involving this figure
        events_involving = [
            e for e in self._legends.historical_events
            if e.get("hfid") == str(hf_id)
            or e.get("hfid_1") == str(hf_id)
            or e.get("hfid_2") == str(hf_id)
        ]
        if events_involving:
            lines.append(f"Involved in {len(events_involving)} historical events")

        return "\n".join(lines)

    def get_war_summary(self, war_collection: dict) -> str:
        """Generate a narrative summary of a war event collection."""
        if not self._legends:
            return ""

        lines = [f"War: {war_collection.get('name', 'Unknown conflict')}"]

        aggressor_ids = war_collection.get("aggressor_ent_id", [])
        defender_ids = war_collection.get("defender_ent_id", [])

        if isinstance(aggressor_ids, str):
            aggressor_ids = [aggressor_ids]
        if isinstance(defender_ids, str):
            defender_ids = [defender_ids]

        for eid in aggressor_ids:
            civ = self._legends.get_civilization(int(eid))
            if civ:
                lines.append(f"Aggressor: {civ.name} ({civ.race})")

        for eid in defender_ids:
            civ = self._legends.get_civilization(int(eid))
            if civ:
                lines.append(f"Defender: {civ.name} ({civ.race})")

        return "\n".join(lines)

    def get_civilization_history(self, entity_id: int) -> str:
        """Generate a narrative summary of a civilization."""
        if not self._legends:
            return ""

        civ = self._legends.get_civilization(entity_id)
        if not civ:
            return ""

        lines = [f"{civ.name} ({civ.race})"]

        # Sites
        sites = [
            self._legends.get_site(sid)
            for sid in civ.sites
            if self._legends.get_site(sid)
        ]
        if sites:
            lines.append(f"Controls {len(sites)} sites:")
            for site in sites[:10]:
                lines.append(f"  - {site.name} ({site.site_type})")

        # Wars
        wars = self._legends.get_wars_involving(entity_id)
        if wars:
            lines.append(f"Involved in {len(wars)} wars")

        return "\n".join(lines)

    def get_artifact_story(self, artifact_id: int) -> str:
        """Generate a narrative summary of an artifact."""
        if not self._legends:
            return ""

        artifact = self._legends.get_artifact(artifact_id)
        if not artifact:
            return ""

        lines = [f"{artifact.name}"]
        if artifact.item_type:
            lines.append(f"Type: {artifact.item_type}")
        if artifact.material:
            lines.append(f"Material: {artifact.material}")

        if artifact.creator_hf_id:
            creator = self._legends.get_figure(artifact.creator_hf_id)
            if creator:
                lines.append(f"Created by {creator.name}")

        return "\n".join(lines)

    def search_figures_by_name(self, name: str) -> list[int]:
        """Find historical figure IDs matching a name (diacritic-insensitive)."""
        if not self._legends:
            return []

        query = normalize_name(name)
        return [
            hf_id for hf_id, hf in self._legends.historical_figures.items()
            if query in normalize_name(hf.name)
        ]
