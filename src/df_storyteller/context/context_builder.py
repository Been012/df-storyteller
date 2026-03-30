"""Assembles token-budgeted prompt context for each story generation mode.

This is the central orchestrator between raw event data and LLM prompts.
It pulls from the event store, character tracker, and world lore to build
context packages appropriate for each story mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from df_storyteller.context.character_tracker import CharacterTracker
from df_storyteller.context.event_store import EventStore
from df_storyteller.context.world_lore import WorldLore
from df_storyteller.schema.events import (
    EventType,
    GameEvent,
    MigrantArrivedData,
    MigrationWaveData,
    MilitaryChangeData,
    NobleAppointmentData,
    ProfessionChangeData,
    Season,
    StressChangeData,
)


@dataclass
class StoryContext:
    """Token-budgeted context package for LLM prompt assembly."""

    mode: str  # chronicle, biography, saga
    fortress_name: str = ""
    world_name: str = ""
    year: int = 0
    season: str = ""

    events_text: str = ""
    character_text: str = ""
    lore_text: str = ""
    previous_summary: str = ""

    estimated_tokens: int = 0


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def _format_event(event: GameEvent) -> str:
    """Format a single event as a concise text line for prompt context."""
    prefix = f"[{event.season.value.title()} {event.game_year}]"
    data = event.data

    if hasattr(data, "victim"):
        victim_name = data.victim.name if hasattr(data.victim, "name") else "Unknown"
        cause = getattr(data, "cause", "unknown")
        return f"{prefix} DEATH: {victim_name} died ({cause})"

    if hasattr(data, "attacker") and hasattr(data, "defender"):
        atk = data.attacker.name if hasattr(data.attacker, "name") else "Unknown"
        defn = data.defender.name if hasattr(data.defender, "name") else "Unknown"
        parts = [f"{prefix} COMBAT: {atk} vs {defn}"]
        if hasattr(data, "weapon") and data.weapon:
            parts.append(f"with {data.weapon}")
        if hasattr(data, "blows") and data.blows:
            parts.append(f"({len(data.blows)} blows)")
            targets = {b.body_part for b in data.blows if b.body_part}
            if targets:
                parts.append(f"targeting {', '.join(targets)}")
        if hasattr(data, "outcome") and data.outcome:
            parts.append(f"— {defn} {data.outcome}")
        if hasattr(data, "is_lethal") and data.is_lethal:
            parts.append("[LETHAL]")
        return " ".join(parts)

    if hasattr(data, "mood_type"):
        unit_name = data.unit.name if hasattr(data.unit, "name") else "Unknown"
        return f"{prefix} MOOD: {unit_name} entered a {data.mood_type} mood"

    if hasattr(data, "artifact_name"):
        creator = data.creator.name if data.creator else "Unknown"
        return f"{prefix} ARTIFACT: {creator} created {data.artifact_name}"

    if hasattr(data, "child"):
        child_name = data.child.name if hasattr(data.child, "name") else "a child"
        return f"{prefix} BIRTH: {child_name} was born"

    if hasattr(data, "new_season"):
        pop = getattr(data, "population", "?")
        return f"{prefix} SEASON: {data.new_season.value.title()} arrives (population: {pop})"

    if hasattr(data, "building_type"):
        return f"{prefix} BUILDING: {data.building_type} constructed"

    # Typed change-detection events
    def _strip_profession(name: str) -> str:
        """Strip profession suffix from name (e.g. 'Urist McName "Nick", Miner' -> 'Urist McName "Nick"')."""
        return name.rsplit(", ", 1)[0] if ", " in name else name

    if isinstance(data, ProfessionChangeData):
        return f"{prefix} TITLE: {_strip_profession(data.unit.name)} changed from {data.old_profession} to {data.new_profession}"
    if isinstance(data, NobleAppointmentData):
        return f"{prefix} APPOINTMENT: {_strip_profession(data.unit.name)} appointed as {', '.join(data.positions)}"
    if isinstance(data, MilitaryChangeData):
        return f"{prefix} MILITARY: {_strip_profession(data.unit.name)} joined {data.squad_name or 'a squad'}"
    if isinstance(data, StressChangeData):
        return f"{prefix} MOOD SHIFT: {_strip_profession(data.unit.name)} went from {data.old_stress} to {data.new_stress}"
    if isinstance(data, MigrantArrivedData):
        return f"{prefix} MIGRANT: {_strip_profession(data.unit.name)} arrived at the fortress"
    if isinstance(data, MigrationWaveData):
        return f"{prefix} MIGRANTS: {data.new_arrivals} new dwarves arrived (population: {data.total_population})"

    # Fallback for any remaining dict-based events
    if isinstance(data, dict):
        raw = data.get("raw_text", "")
        return f"{prefix} {event.event_type.value}: {raw}" if raw else f"{prefix} {event.event_type.value}"

    return f"{prefix} {event.event_type.value}"


class ContextBuilder:
    """Builds story context from event store, character tracker, and world lore."""

    def __init__(
        self,
        event_store: EventStore,
        character_tracker: CharacterTracker,
        world_lore: WorldLore,
        max_context_tokens: int = 8000,
    ) -> None:
        self.event_store = event_store
        self.character_tracker = character_tracker
        self.world_lore = world_lore
        self.max_tokens = max_context_tokens

    def build_chronicle_context(
        self,
        year: int,
        season: str,
        fortress_name: str = "",
        previous_summary: str = "",
    ) -> StoryContext:
        """Build context for a fortress chronicle entry."""
        events = self.event_store.events_in_season(year, season)
        if not events:
            events = self.event_store.recent_events(30)

        events_text = "\n".join(_format_event(e) for e in events)

        # Get notable characters involved
        character_lines = []
        seen_units: set[int] = set()
        for event in events:
            for uid in self.event_store._extract_unit_ids(event):
                if uid not in seen_units:
                    seen_units.add(uid)
                    summary = self.character_tracker.get_character_summary(uid)
                    if summary:
                        character_lines.append(summary)

        character_text = "\n\n".join(character_lines[:10])  # Cap at 10 characters

        # Add world lore for any referenced civilizations
        lore_text = ""
        if self.world_lore.is_loaded:
            # Basic world context
            lore_text = "World lore available for enrichment."

        ctx = StoryContext(
            mode="chronicle",
            fortress_name=fortress_name,
            year=year,
            season=season,
            events_text=events_text,
            character_text=character_text,
            lore_text=lore_text,
            previous_summary=previous_summary,
        )
        ctx.estimated_tokens = _estimate_tokens(
            events_text + character_text + lore_text + previous_summary
        )

        # Trim if over budget
        ctx = self._trim_to_budget(ctx)
        return ctx

    def build_biography_context(
        self,
        unit_id: int,
        fortress_name: str = "",
    ) -> StoryContext:
        """Build context for a character biography."""
        dwarf = self.character_tracker.get_dwarf(unit_id)
        if not dwarf:
            return StoryContext(mode="biography")

        events = self.character_tracker.get_events(unit_id)
        events_text = "\n".join(_format_event(e) for e in events)
        character_text = self.character_tracker.get_character_summary(unit_id)

        # Try to find matching historical figure in legends
        lore_text = ""
        if self.world_lore.is_loaded:
            matches = self.world_lore.search_figures_by_name(dwarf.name)
            for hf_id in matches[:3]:
                lore_text += self.world_lore.get_figure_biography(hf_id) + "\n"

        ctx = StoryContext(
            mode="biography",
            fortress_name=fortress_name,
            events_text=events_text,
            character_text=character_text,
            lore_text=lore_text,
        )
        ctx.estimated_tokens = _estimate_tokens(events_text + character_text + lore_text)
        return self._trim_to_budget(ctx)

    def build_saga_context(
        self,
        scope: str = "full",
        world_name: str = "",
    ) -> StoryContext:
        """Build context for an epic world history saga.

        Analyzes legends data to extract overarching themes — which races
        are dominant, who's losing wars, what the major conflicts are —
        then provides structured context for narrative generation.
        """
        if not self.world_lore.is_loaded:
            return StoryContext(mode="saga", lore_text="No legends data loaded.")

        legends = self.world_lore._legends
        if not legends:
            return StoryContext(mode="saga")

        lore_parts: list[str] = []

        # --- Analyze world themes from data ---
        themes: list[str] = []

        # Historical eras
        if legends.historical_eras:
            era_names = [e.get("name", "") for e in legends.historical_eras if e.get("name")]
            if era_names:
                lore_parts.append(f"Historical Eras: {', '.join(era_names)}")

        # Civilization power analysis
        from collections import defaultdict
        civ_wars_won: dict[str, int] = defaultdict(int)
        civ_wars_lost: dict[str, int] = defaultdict(int)
        race_battle_wins: dict[str, int] = defaultdict(int)
        race_battle_losses: dict[str, int] = defaultdict(int)
        race_deaths: dict[str, int] = defaultdict(int)
        race_civ_count: dict[str, int] = defaultdict(int)
        race_site_count: dict[str, int] = defaultdict(int)

        # Count civs per race
        for eid, civ in legends.civilizations.items():
            etype = getattr(civ, '_entity_type', '')
            if etype == 'civilization' and civ.race:
                race_civ_count[civ.race] += 1

        # Analyze battles for race dominance
        for battle in legends.battles:
            outcome = battle.get("outcome", "")
            atk_race = battle.get("attacking_squad_race", "")
            def_race = battle.get("defending_squad_race", "")
            if isinstance(atk_race, list): atk_race = atk_race[0] if atk_race else ""
            if isinstance(def_race, list): def_race = def_race[0] if def_race else ""

            if "attacker won" in outcome:
                race_battle_wins[atk_race] += 1
                race_battle_losses[def_race] += 1
            elif "defender won" in outcome:
                race_battle_wins[def_race] += 1
                race_battle_losses[atk_race] += 1

        # Count deaths by race
        for death in legends.notable_deaths:
            hfid = death.get("hfid")
            if hfid:
                try:
                    hf = legends.get_figure(int(hfid))
                    if hf and hf.race:
                        race_deaths[hf.race] += 1
                except (ValueError, TypeError):
                    pass

        # Generate theme observations
        major_races = ['DWARF', 'HUMAN', 'ELF', 'GOBLIN']
        for race in major_races:
            wins = race_battle_wins.get(race, 0)
            losses = race_battle_losses.get(race, 0)
            deaths_count = race_deaths.get(race, 0)
            readable = race.replace("_", " ").title()

            if wins + losses > 0:
                if wins > losses * 2:
                    themes.append(f"The {readable}s are a dominant military power, winning most battles they fight.")
                elif losses > wins * 2:
                    themes.append(f"The {readable}s have suffered greatly in warfare, losing far more battles than they've won.")
                elif wins > losses:
                    themes.append(f"The {readable}s hold a slight military advantage in the world's conflicts.")
                elif losses > wins:
                    themes.append(f"The {readable}s are embattled, struggling against their enemies.")

        # Beast attack analysis
        beast_attack_count = len(legends.beast_attacks)
        if beast_attack_count > 100:
            themes.append(f"The world is plagued by monster attacks — {beast_attack_count} beast attacks have been recorded.")
        elif beast_attack_count > 20:
            themes.append(f"Dangerous beasts roam the land, with {beast_attack_count} recorded attacks on settlements.")

        # Site conquest analysis
        conquest_count = len(legends.site_conquests)
        if conquest_count > 50:
            themes.append(f"The world has seen great upheaval — {conquest_count} sites have been conquered in warfare.")
        elif conquest_count > 10:
            themes.append(f"Several sites have changed hands through conquest ({conquest_count} recorded).")

        # Persecution analysis
        if legends.persecutions:
            themes.append(f"Religious and political persecution has scarred the world ({len(legends.persecutions)} recorded persecutions).")

        # Death toll
        total_notable_deaths = len(legends.notable_deaths)
        if total_notable_deaths > 1000:
            themes.append(f"Violence has claimed {total_notable_deaths} notable lives across the world's history.")

        if themes:
            lore_parts.append("## World Themes (derived from historical data)\n" + "\n".join(f"- {t}" for t in themes))

        # --- Major civilizations ---
        civ_summaries = []
        for eid, civ in legends.civilizations.items():
            etype = getattr(civ, '_entity_type', '')
            if etype != 'civilization' or not civ.name:
                continue
            if civ.race not in ('DWARF', 'HUMAN', 'ELF', 'GOBLIN', 'KOBOLD'):
                continue
            race = civ.race.replace("_", " ").title()
            wars = legends.get_wars_involving(eid)
            war_info = f", involved in {len(wars)} wars" if wars else ""
            # Get sub-entities
            sub_ents = []
            for child_id in getattr(civ, '_child_ids', []):
                child = legends.get_civilization(child_id)
                if child and child.name:
                    child_type = getattr(child, '_entity_type', '')
                    if child_type == 'religion':
                        worship_id = getattr(child, '_worship_id', None)
                        if worship_id:
                            deity = legends.get_figure(worship_id)
                            if deity and deity.spheres:
                                sub_ents.append(f"{child.name} (religion of {deity.name}, spheres: {', '.join(deity.spheres)})")
                                continue
                    if child_type in ('religion', 'guild'):
                        sub_ents.append(f"{child.name} ({child_type})")

            summary = f"{civ.name} ({race}{war_info})"
            if sub_ents:
                summary += "\n  Organizations: " + ", ".join(sub_ents[:5])
            civ_summaries.append(summary)

        if civ_summaries:
            lore_parts.append("## Major Civilizations\n" + "\n".join(civ_summaries[:15]))

        # --- Wars with details ---
        war_summaries = []
        for ec in legends.event_collections:
            if ec.get("type") != "war":
                continue
            name = ec.get("name", "")
            if not name:
                continue
            sy = ec.get("start_year", "")
            ey = ec.get("end_year", "")
            year_range = f"Year {sy}–{ey}" if sy and ey and sy != ey else f"Year {sy}" if sy else ""

            sides = []
            for role, key in [("Aggressor", "aggressor_ent_id"), ("Defender", "defender_ent_id")]:
                ids = ec.get(key, [])
                if isinstance(ids, str): ids = [ids]
                for eid_str in ids:
                    try:
                        c = legends.get_civilization(int(eid_str))
                        if c:
                            sides.append(f"{role}: {c.name} ({c.race})" if c.race else f"{role}: {c.name}")
                    except (ValueError, TypeError):
                        pass

            # Count battles in this war
            war_battles = [b for b in legends.battles if b.get("war_eventcol") == ec.get("id")]

            summary = f"{name} ({year_range})" if year_range else name
            if sides:
                summary += " — " + " vs ".join(sides)
            if war_battles:
                summary += f" ({len(war_battles)} battles)"
            war_summaries.append(summary)

        if war_summaries:
            lore_parts.append("## Wars\n" + "\n".join(war_summaries[:15]))

        # --- Player's fortress context ---
        lore_parts.append("## Your Fortress\nThe saga should connect the world's history to the player's fortress and civilization, showing how the grand sweep of history led to this moment.")

        lore_text = "\n\n".join(lore_parts)

        ctx = StoryContext(
            mode="saga",
            world_name=world_name,
            lore_text=lore_text,
        )
        ctx.estimated_tokens = _estimate_tokens(lore_text)
        return self._trim_to_budget(ctx)

    def _trim_to_budget(self, ctx: StoryContext) -> StoryContext:
        """Trim context to fit within token budget. Prioritize: events > characters > lore."""
        if ctx.estimated_tokens <= self.max_tokens:
            return ctx

        budget = self.max_tokens
        remaining = budget

        # Allocate: 50% events, 25% characters, 25% lore
        events_budget = budget // 2
        char_budget = budget // 4
        lore_budget = budget // 4

        if _estimate_tokens(ctx.events_text) > events_budget:
            # Truncate events text to budget
            char_limit = events_budget * 4
            ctx.events_text = ctx.events_text[:char_limit] + "\n[...truncated]"

        if _estimate_tokens(ctx.character_text) > char_budget:
            char_limit = char_budget * 4
            ctx.character_text = ctx.character_text[:char_limit] + "\n[...truncated]"

        if _estimate_tokens(ctx.lore_text) > lore_budget:
            char_limit = lore_budget * 4
            ctx.lore_text = ctx.lore_text[:char_limit] + "\n[...truncated]"

        ctx.estimated_tokens = _estimate_tokens(
            ctx.events_text + ctx.character_text + ctx.lore_text + ctx.previous_summary
        )
        return ctx
