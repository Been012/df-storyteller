"""In-memory event store with query capabilities."""

from __future__ import annotations

import threading
from collections import defaultdict

from df_storyteller.schema.events import EventType, GameEvent


class EventStore:
    """Thread-safe, append-only store for normalized game events."""

    def __init__(self) -> None:
        self._events: list[GameEvent] = []
        self._by_type: dict[EventType, list[int]] = defaultdict(list)
        self._by_unit: dict[int, list[int]] = defaultdict(list)
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return len(self._events)

    def add(self, event: GameEvent) -> int:
        """Add an event and return its index."""
        with self._lock:
            idx = len(self._events)
            self._events.append(event)
            self._by_type[event.event_type].append(idx)

            # Index by unit IDs found in the event data
            for unit_id in self._extract_unit_ids(event):
                self._by_unit[unit_id].append(idx)

            return idx

    def get(self, idx: int) -> GameEvent | None:
        if 0 <= idx < len(self._events):
            return self._events[idx]
        return None

    def all_events(self) -> list[GameEvent]:
        return list(self._events)

    def events_by_type(self, event_type: EventType) -> list[GameEvent]:
        indices = self._by_type.get(event_type, [])
        return [self._events[i] for i in indices]

    def events_for_unit(self, unit_id: int) -> list[GameEvent]:
        indices = self._by_unit.get(unit_id, [])
        return [self._events[i] for i in indices]

    def events_in_range(self, start_tick: int, end_tick: int, year: int | None = None) -> list[GameEvent]:
        """Return events within a game tick range, optionally filtered by year."""
        results = []
        for event in self._events:
            if year is not None and event.game_year != year:
                continue
            if start_tick <= event.game_tick <= end_tick:
                results.append(event)
        return results

    def recent_events(self, n: int = 50) -> list[GameEvent]:
        """Return the N most recent events."""
        return list(self._events[-n:])

    def events_in_season(self, year: int, season: str) -> list[GameEvent]:
        """Return all events from a specific year+season."""
        return [
            e for e in self._events
            if e.game_year == year and e.season.value == season
        ]

    @staticmethod
    def _extract_unit_ids(event: GameEvent) -> list[int]:
        """Extract unit IDs from event data for indexing."""
        ids: list[int] = []
        data = event.data

        if not isinstance(data, dict):
            # Typed data model — check common fields
            for field_name in ("victim", "attacker", "defender", "unit", "child",
                               "mother", "father", "builder", "worker", "creator"):
                ref = getattr(data, field_name, None)
                if ref and hasattr(ref, "unit_id") and ref.unit_id:
                    ids.append(ref.unit_id)
            # Also check killer
            killer = getattr(data, "killer", None)
            if killer and hasattr(killer, "unit_id") and killer.unit_id:
                ids.append(killer.unit_id)
        else:
            # Dict-based data — look for unit_id keys
            for key, value in data.items():
                if isinstance(value, dict) and "unit_id" in value:
                    if value["unit_id"]:
                        ids.append(value["unit_id"])

        return ids
