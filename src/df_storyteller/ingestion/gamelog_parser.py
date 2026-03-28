"""Parser for Dwarf Fortress gamelog.txt.

Tail-follows the gamelog and classifies lines into normalized GameEvent models.
Multi-line combat reports are grouped into single CombatEvent instances.

Reference: gamelog.txt is written by DF during play and contains combat reports,
announcements, seasonal changes, moods, artifact creation, and misc messages.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Generator

from df_storyteller.schema.events import (
    ArtifactData,
    ArtifactEvent,
    CombatBlow,
    CombatData,
    CombatEvent,
    DeathData,
    DeathEvent,
    EventSource,
    GameEvent,
    EventType,
    MoodData,
    MoodEvent,
    Season,
    SeasonChangeData,
    SeasonChangeEvent,
    UnitRef,
)

# --- Line classification patterns ---

SEASON_PATTERN = re.compile(
    r"^(?:Early |Mid-|Late )?(Spring|Summer|Autumn|Winter) has (arrived|come)\b",
    re.IGNORECASE,
)

DEATH_PATTERNS = [
    re.compile(r"^(.+) has been struck down\.$"),
    re.compile(r"^(.+) has been found dead\.$"),
    re.compile(r"^(.+) has died (?:of|after|in) (.+)\.$"),
    re.compile(r"^(.+) has bled to death\.$"),
    re.compile(r"^(.+) has suffocated\.$"),
    re.compile(r"^(.+) has starved to death\.$"),
    re.compile(r"^(.+) has died of thirst\.$"),
    re.compile(r"^(.+) has drowned\.$"),
]

MOOD_PATTERN = re.compile(
    r"^(.+) is taken by a (fey|secretive|possessed|macabre|fell) mood!$"
)

ARTIFACT_PATTERN = re.compile(
    r'^(.+) has created (.+), a (.+)!$'
)

# Combat lines: DF Premium format "The militia commander hacks the giant groundhog in the right front paw with his (copper battle axe), tearing apart the muscle!"
COMBAT_DETAILED_PATTERN = re.compile(
    r"^(?:The )?(.+?) (hacks|slashes|stabs|strikes|punches|kicks|bites|scratches|bashes|gores|charges at)"
    r" (?:the )?(.+?) in the (.+?) with (?:his|her|its) \((.+?)\)(?:, (.+))?[!.]$",
    re.IGNORECASE,
)

# Simpler combat: "The X strikes The Y in the Z!"
COMBAT_STRIKE_PATTERN = re.compile(
    r"^(?:The )?(.+?) (strikes|punches|kicks|bites|scratches|stabs|slashes|bashes|gores|hacks)"
    r" (?:The |the )?(.+?) in the (.+?)(?:with .+)?[!.]$",
    re.IGNORECASE,
)

COMBAT_WOUND_PATTERN = re.compile(
    r"^(?:The |A )(.+?) (?:has been |is )(bruised|torn|fractured|broken|severed|mangled|crushed|opened|cut)",
    re.IGNORECASE,
)

COMBAT_INJURY_PATTERN = re.compile(
    r"^(?:An? .+ has been (?:opened|severed|torn|bruised)|A tendon .+ has been|The force .+|A sensory nerve|A motor nerve)",
    re.IGNORECASE,
)

COMBAT_OUTCOME_PATTERN = re.compile(
    r"^(?:The )?(.+?) (falls over|gives in to pain|has been knocked unconscious|collapses)",
    re.IGNORECASE,
)

CANCEL_PATTERN = re.compile(r"^(.+) cancels (.+): (.+)\.$")


def _season_from_str(s: str) -> Season:
    return Season(s.lower())


def _make_unit_ref(name: str) -> UnitRef:
    """Create a minimal UnitRef from a gamelog name string."""
    return UnitRef(unit_id=0, name=name.strip())


class GamelogParser:
    """Stateful parser for gamelog.txt lines.

    Accumulates multi-line combat blocks and emits GameEvent objects.
    """

    def __init__(self) -> None:
        self._combat_lines: list[str] = []
        self._current_year: int = 0
        self._current_season: Season = Season.SPRING
        self._line_count: int = 0

    def set_year(self, year: int) -> None:
        self._current_year = year

    def set_season(self, season: Season) -> None:
        self._current_season = season

    def parse_file(self, path: Path) -> list[GameEvent]:
        """Parse an entire gamelog.txt file and return all events."""
        events: list[GameEvent] = []
        if not path.exists():
            return events
        with open(path, encoding="cp437", errors="replace") as f:
            for event in self.parse_lines(f):
                events.append(event)
        return events

    def parse_lines(self, lines: Generator[str, None, None] | list[str]) -> Generator[GameEvent, None, None]:
        """Parse lines yielding GameEvent objects."""
        for line in lines:
            line = line.rstrip("\n\r")
            if not line.strip():
                # Blank line may terminate a combat block
                yield from self._flush_combat()
                continue

            self._line_count += 1

            # Try each pattern in priority order
            event = self._try_season(line)
            if event:
                yield from self._flush_combat()
                yield event
                continue

            event = self._try_death(line)
            if event:
                yield from self._flush_combat()
                yield event
                continue

            event = self._try_mood(line)
            if event:
                yield from self._flush_combat()
                yield event
                continue

            event = self._try_artifact(line)
            if event:
                yield from self._flush_combat()
                yield event
                continue

            # Combat lines accumulate
            if self._is_combat_line(line):
                self._combat_lines.append(line)
                continue

            # Non-combat, non-empty line flushes combat block
            yield from self._flush_combat()

            # Generic announcement
            yield GameEvent(
                event_type=EventType.ANNOUNCEMENT,
                game_year=self._current_year,
                game_tick=0,
                season=self._current_season,
                source=EventSource.GAMELOG,
                data={"raw_text": line},
            )

        # Flush remaining combat at end
        yield from self._flush_combat()

    def _try_season(self, line: str) -> SeasonChangeEvent | None:
        m = SEASON_PATTERN.match(line)
        if not m:
            return None
        season = _season_from_str(m.group(1))
        self._current_season = season
        return SeasonChangeEvent(
            game_year=self._current_year,
            season=season,
            source=EventSource.GAMELOG,
            data=SeasonChangeData(new_season=season),
        )

    def _try_death(self, line: str) -> DeathEvent | None:
        for pattern in DEATH_PATTERNS:
            m = pattern.match(line)
            if m:
                victim_name = m.group(1)
                cause = m.group(2) if m.lastindex and m.lastindex >= 2 else "unknown"
                return DeathEvent(
                    game_year=self._current_year,
                    season=self._current_season,
                    source=EventSource.GAMELOG,
                    data=DeathData(
                        victim=_make_unit_ref(victim_name),
                        cause=cause,
                    ),
                )
        return None

    def _try_mood(self, line: str) -> MoodEvent | None:
        m = MOOD_PATTERN.match(line)
        if not m:
            return None
        return MoodEvent(
            game_year=self._current_year,
            season=self._current_season,
            source=EventSource.GAMELOG,
            data=MoodData(
                unit=_make_unit_ref(m.group(1)),
                mood_type=m.group(2),
            ),
        )

    def _try_artifact(self, line: str) -> ArtifactEvent | None:
        m = ARTIFACT_PATTERN.match(line)
        if not m:
            return None
        return ArtifactEvent(
            game_year=self._current_year,
            season=self._current_season,
            source=EventSource.GAMELOG,
            data=ArtifactData(
                artifact_name=m.group(2),
                item_type=m.group(3),
                creator=_make_unit_ref(m.group(1)),
            ),
        )

    def _is_combat_line(self, line: str) -> bool:
        if COMBAT_DETAILED_PATTERN.match(line):
            return True
        if COMBAT_STRIKE_PATTERN.match(line):
            return True
        if COMBAT_WOUND_PATTERN.match(line):
            return True
        if COMBAT_INJURY_PATTERN.match(line):
            return True
        if COMBAT_OUTCOME_PATTERN.match(line):
            return True
        lower = line.lower()
        if line.startswith("The ") and any(
            w in lower
            for w in [
                "strikes", "misses", "charges", "blocks", "dodges",
                "counterattack", "latch", "shakes", "collaps",
                "gives in", "is no longer", "cloven asunder",
                "sails off", "flies off", "injured part",
            ]
        ):
            return True
        # Injury follow-ups that don't start with "The"
        if lower.startswith(("an artery", "a tendon", "a sensory", "a motor", "many nerves")):
            return True
        return False

    def _flush_combat(self) -> Generator[CombatEvent, None, None]:
        if not self._combat_lines:
            return

        raw_text = "\n".join(self._combat_lines)
        attacker = ""
        defender = ""
        weapon = ""
        body_part = ""
        blows: list[CombatBlow] = []
        injuries: list[str] = []
        outcome = ""

        for line in self._combat_lines:
            # Try detailed pattern first (DF Premium with weapon)
            m = COMBAT_DETAILED_PATTERN.match(line)
            if m:
                blow_attacker = m.group(1)
                action = m.group(2)
                blow_defender = m.group(3)
                blow_body_part = m.group(4)
                blow_weapon = m.group(5)
                effect = m.group(6) or ""
                if not attacker:
                    attacker = blow_attacker
                    defender = blow_defender
                    weapon = blow_weapon
                    body_part = blow_body_part
                blows.append(CombatBlow(
                    attacker=blow_attacker, defender=blow_defender,
                    action=action, body_part=blow_body_part,
                    weapon=blow_weapon, effect=effect,
                ))
                continue

            # Try simple strike pattern
            m = COMBAT_STRIKE_PATTERN.match(line)
            if m:
                blow_attacker = m.group(1)
                action = m.group(2)
                blow_defender = m.group(3)
                blow_body_part = m.group(4)
                if not attacker:
                    attacker = blow_attacker
                    defender = blow_defender
                    body_part = blow_body_part
                blows.append(CombatBlow(
                    attacker=blow_attacker, defender=blow_defender,
                    action=action, body_part=blow_body_part,
                ))
                continue

            # Injuries
            if COMBAT_INJURY_PATTERN.match(line) or COMBAT_WOUND_PATTERN.match(line):
                injuries.append(line.strip())
                continue

            # Outcome
            m = COMBAT_OUTCOME_PATTERN.match(line)
            if m:
                outcome = m.group(2)
                continue

            if "cloven asunder" in line.lower() or "sails off" in line.lower():
                outcome = "severed"

        is_lethal = any(
            "struck down" in l.lower()
            or "has been killed" in l.lower()
            or "cloven asunder" in l.lower()
            for l in self._combat_lines
        )

        yield CombatEvent(
            game_year=self._current_year,
            season=self._current_season,
            source=EventSource.GAMELOG,
            data=CombatData(
                attacker=_make_unit_ref(attacker or "Unknown"),
                defender=_make_unit_ref(defender or "Unknown"),
                weapon=weapon,
                body_part=body_part,
                is_lethal=is_lethal,
                raw_text=raw_text,
                blows=blows,
                injuries=injuries,
                outcome=outcome,
            ),
        )
        self._combat_lines = []


def tail_gamelog(path: Path, parser: GamelogParser) -> Generator[GameEvent, None, None]:
    """Tail-follow a gamelog.txt file, yielding new events as they appear."""
    import time

    if not path.exists():
        return

    with open(path, encoding="cp437", errors="replace") as f:
        # Seek to end
        f.seek(0, 2)

        while True:
            line = f.readline()
            if line:
                yield from parser.parse_lines([line])
            else:
                time.sleep(0.5)
