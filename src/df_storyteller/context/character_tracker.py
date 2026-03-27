"""Per-dwarf event accumulation and narrative importance tracking."""

from __future__ import annotations

import unicodedata
from collections import defaultdict

from df_storyteller.schema.entities import Dwarf
from df_storyteller.schema.events import EventType, GameEvent


def normalize_name(name: str) -> str:
    """Strip diacritics and normalize for fuzzy matching.

    Dwarf Fortress uses characters like ö, ï, é, ä, û in names.
    This converts them to their ASCII equivalents (o, i, e, a, u)
    so users can search without needing special characters.
    """
    # Decompose unicode (e.g. ö -> o + combining diaeresis)
    decomposed = unicodedata.normalize("NFD", name)
    # Strip combining marks (accents, diaeresis, etc.)
    ascii_name = "".join(
        ch for ch in decomposed
        if unicodedata.category(ch) != "Mn"
    )
    return ascii_name.lower()


# Weight multipliers for narrative importance scoring
EVENT_WEIGHTS: dict[EventType, float] = {
    EventType.DEATH: 10.0,
    EventType.COMBAT: 3.0,
    EventType.MOOD: 5.0,
    EventType.ARTIFACT: 8.0,
    EventType.BIRTH: 2.0,
    EventType.BUILDING: 1.0,
    EventType.JOB: 0.5,
    EventType.SEASON_CHANGE: 0.0,
    EventType.ANNOUNCEMENT: 0.5,
}


class CharacterTracker:
    """Tracks events per dwarf and computes narrative importance."""

    def __init__(self) -> None:
        self._characters: dict[int, Dwarf] = {}
        self._events_by_unit: dict[int, list[GameEvent]] = defaultdict(list)

    def register_dwarf(self, dwarf: Dwarf) -> None:
        self._characters[dwarf.unit_id] = dwarf

    def add_event(self, unit_id: int, event: GameEvent) -> None:
        self._events_by_unit[unit_id].append(event)

    def get_events(self, unit_id: int) -> list[GameEvent]:
        return self._events_by_unit.get(unit_id, [])

    def get_dwarf(self, unit_id: int) -> Dwarf | None:
        return self._characters.get(unit_id)

    def find_by_name(self, name: str) -> Dwarf | None:
        """Find a dwarf by name (case-insensitive, diacritic-insensitive partial match).

        Handles DF's special characters (ö, ï, é, ä, û, etc.) so users
        can type plain ASCII like "Urist" to match "Ürïst".
        """
        query = normalize_name(name)
        for dwarf in self._characters.values():
            if query in normalize_name(dwarf.name):
                return dwarf
        return None

    def narrative_importance(self, unit_id: int) -> float:
        """Compute narrative importance score for a dwarf."""
        events = self._events_by_unit.get(unit_id, [])
        score = 0.0
        for event in events:
            score += EVENT_WEIGHTS.get(event.event_type, 0.5)
        return score

    def ranked_characters(self) -> list[tuple[Dwarf, float]]:
        """Return all tracked characters ranked by narrative importance."""
        ranked = []
        for unit_id, dwarf in self._characters.items():
            score = self.narrative_importance(unit_id)
            ranked.append((dwarf, score))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def get_character_summary(self, unit_id: int) -> str:
        """Build a text summary of a dwarf's story so far."""
        dwarf = self._characters.get(unit_id)
        if not dwarf:
            return ""

        events = self._events_by_unit.get(unit_id, [])
        lines = [f"{dwarf.name}, {dwarf.profession}"]

        # Personality summary (only notable traits)
        if dwarf.personality and dwarf.personality.facets:
            personality_text = dwarf.personality.narrative_summary()
            if personality_text and personality_text != "An unremarkable personality.":
                lines.append(personality_text)

        if dwarf.skills:
            top_skills = sorted(dwarf.skills, key=lambda s: s.experience, reverse=True)[:5]
            skills_str = ", ".join(f"{s.name} ({s.level})" for s in top_skills)
            lines.append(f"Skills: {skills_str}")

        lines.append(f"Events: {len(events)} recorded")
        for event in events[-10:]:  # Last 10 events
            lines.append(f"  - [{event.season.value} {event.game_year}] {event.event_type.value}")

        return "\n".join(lines)


