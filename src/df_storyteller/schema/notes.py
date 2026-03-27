"""Player notes model — lets players influence story generation.

Each note has a tag that controls how the LLM uses it:
- SUSPICION: Subtext, foreshadowing, ambiguity. Never confirmed.
- FACT: Treated as confirmed truth in the narrative.
- THEORY: Narrator speculation. "Some say..." / "It is whispered..."
- RUMOR: Attributed to other dwarves as gossip.
- SECRET: Hidden truth that colors narrative without being stated openly.
- FORESHADOW: Narrative seeds for future events. Ominous hints.
- MOOD: Sets emotional tone for scenes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class NoteTag(str, Enum):
    SUSPICION = "suspicion"
    FACT = "fact"
    THEORY = "theory"
    RUMOR = "rumor"
    SECRET = "secret"
    FORESHADOW = "foreshadow"
    MOOD = "mood"


# How the LLM should handle each tag type
TAG_INSTRUCTIONS: dict[NoteTag, str] = {
    NoteTag.SUSPICION: "Weave this as subtext and foreshadowing. Do NOT confirm it directly. Describe eerie behavior, odd details, unsettling moments.",
    NoteTag.FACT: "Treat this as confirmed truth. State it directly in the narrative.",
    NoteTag.THEORY: "Present this as the narrator's speculation. Use phrases like 'Some say...', 'It is whispered that...', 'Perhaps...'",
    NoteTag.RUMOR: "Attribute this to other dwarves as gossip. 'The miners whisper...', 'Word has spread that...'",
    NoteTag.SECRET: "This is hidden knowledge. Show its consequences without stating the secret directly. Let the reader feel something is wrong.",
    NoteTag.FORESHADOW: "Plant narrative seeds for this. Use ominous hints, dark imagery, a sense of approaching doom or change.",
    NoteTag.MOOD: "Use this to set the emotional tone of scenes. Color descriptions, atmosphere, and character interactions with this feeling.",
}

# User-facing descriptions for the UI
TAG_DESCRIPTIONS: dict[NoteTag, str] = {
    NoteTag.SUSPICION: "Something you suspect but aren't sure about. The story will hint at it without confirming.",
    NoteTag.FACT: "Something you know to be true. The story will state it as fact.",
    NoteTag.THEORY: "Your personal theory. The story will present it as speculation.",
    NoteTag.RUMOR: "Something the dwarves might gossip about. Attributed to fortress rumor.",
    NoteTag.SECRET: "A hidden truth. The story shows consequences without revealing the secret directly.",
    NoteTag.FORESHADOW: "Something you want the story to build toward. Creates ominous hints.",
    NoteTag.MOOD: "Sets the emotional tone. Affects atmosphere and descriptions.",
}


class PlayerNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    tag: NoteTag
    text: str
    target_type: str = "fortress"  # "dwarf" or "fortress"
    target_id: int | None = None  # unit_id if dwarf, None if fortress
    game_year: int = 0
    game_season: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    resolved: bool = False
