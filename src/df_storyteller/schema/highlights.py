"""Dwarf highlight system — lets players mark dwarves with narrative roles.

Highlights are persistent role assignments (protagonist, antagonist, watchlist)
that influence both the UI display and AI generation priorities.
Unlike notes, highlights are one-per-dwarf with upsert semantics.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class DwarfRole(str, Enum):
    PROTAGONIST = "protagonist"
    ANTAGONIST = "antagonist"
    WATCHLIST = "watchlist"


class DwarfHighlight(BaseModel):
    unit_id: int
    name: str = ""
    role: DwarfRole
