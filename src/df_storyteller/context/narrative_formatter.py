"""Interprets raw game data into narrative-ready text for LLM context.

Converts numeric attributes, skill levels, and personality values into
descriptive prose that an LLM can use to write grounded stories.
"""

from __future__ import annotations

from df_storyteller.schema.entities import Dwarf
from df_storyteller.schema.personality import FACET_DESCRIPTIONS


# DF attribute values: ~450 is average, ~1000 is notable, ~1500+ is exceptional, ~2000+ is legendary
def _describe_physical_attr(name: str, value: int) -> str | None:
    """Return a description only if the attribute is notably high or low."""
    readable = name.lower().replace("_", " ")
    if value >= 2000:
        return f"legendary {readable}"
    elif value >= 1500:
        return f"exceptional {readable}"
    elif value >= 1100:
        return f"above-average {readable}"
    elif value <= 300:
        return f"very weak {readable}"
    elif value <= 500:
        return f"below-average {readable}"
    return None


def _describe_mental_attr(name: str, value: int) -> str | None:
    """Return a description only if the attribute is notably high or low."""
    readable = {
        "ANALYTICAL_ABILITY": "analytical mind",
        "FOCUS": "focus",
        "WILLPOWER": "willpower",
        "CREATIVITY": "creativity",
        "INTUITION": "intuition",
        "PATIENCE": "patience",
        "MEMORY": "memory",
        "LINGUISTIC_ABILITY": "linguistic ability",
        "SPATIAL_SENSE": "spatial sense",
        "MUSICALITY": "musicality",
        "KINESTHETIC_SENSE": "kinesthetic sense",
        "EMPATHY": "empathy",
        "SOCIAL_AWARENESS": "social awareness",
    }.get(name, name.lower().replace("_", " "))

    if value >= 1500:
        return f"exceptional {readable}"
    elif value >= 1100:
        return f"notable {readable}"
    elif value <= 300:
        return f"poor {readable}"
    return None


# Fallback skill ID to name mapping for when DFHack returns numeric IDs.
# Ref: https://dwarffortresswiki.org/index.php/DF2014:Skill
_SKILL_ID_NAMES: dict[str, str] = {
    "0": "Mining", "1": "Woodcutting", "2": "Carpentry", "3": "Detailing",
    "4": "Masonry", "5": "Animal Training", "6": "Animal Care",
    "7": "Diagnosis", "8": "Surgery", "9": "Setting Bones", "10": "Suturing",
    "11": "Dressing Wounds", "12": "Feed Patients", "13": "Chemistry",
    "14": "Butchery", "15": "Tanning", "16": "Weaving", "17": "Brewing",
    "18": "Alchemy", "19": "Clothesmaking", "20": "Milling", "21": "Plant Processing",
    "22": "Cheesemaking", "23": "Milking", "24": "Cooking", "25": "Farming",
    "26": "Fishing", "27": "Metalcrafting", "28": "Smelting",
    "29": "Glassmaking", "30": "Gem Cutting", "31": "Gem Setting",
    "32": "Woodcrafting", "33": "Stonecrafting", "34": "Metalsmithing",
    "35": "Leatherworking", "36": "Bone Carving", "37": "Bowcraft",
    "38": "Trapping", "39": "Mechanics", "40": "Siege Engineering",
    "41": "Siege Operation", "42": "Crossbow", "43": "Hammering",
    "44": "Spear", "45": "Sword", "46": "Axe", "47": "Mace",
    "48": "Shield", "49": "Wrestling", "50": "Biting", "51": "Dodging",
    "52": "Striking", "53": "Kicking", "54": "Armor", "55": "Swimming",
    "56": "Observing", "57": "Teaching", "58": "Persuasion",
    "59": "Negotiation", "60": "Judging Intent", "61": "Lying",
    "62": "Intimidation", "63": "Conversing", "64": "Comedy",
    "65": "Flattery", "66": "Consoling", "67": "Pacification",
    "68": "Tracking", "69": "Knowledge Acquisition",
    "70": "Concentration", "71": "Discipline", "72": "Herbalism",
    "73": "Pottery", "74": "Glazing", "75": "Pressing", "76": "Spinning",
    "77": "Pump Operation", "78": "Threshing", "79": "Shearing",
    "80": "Wax Working", "81": "Gelding", "82": "Beekeeping",
    "83": "Writing", "84": "Prose", "85": "Poetry", "86": "Reading",
    "87": "Speaking", "88": "Coordination", "89": "Balance",
    "90": "Leadership", "91": "Climbing", "92": "Organization",
    "93": "Record Keeping", "94": "Tactics", "95": "Situational Awareness",
    "116": "Building Design", "117": "Food Preparation",
    "118": "Logistics", "119": "Critical Thinking", "120": "Melee Combat",
}


def _resolve_skill_name(name: str) -> str:
    """Convert a skill name or numeric ID to a readable name."""
    # If it's already a readable name, return as-is
    if not name.isdigit():
        return name.replace("_", " ").title()
    return _SKILL_ID_NAMES.get(name, f"Skill {name}")


# DF skill ratings: 0=Dabbling, 3=Competent, 6=Skilled, 9=Professional,
# 12=Great, 14=High Master, 15=Grand Master, 16-20=Legendary
_SKILL_LEVEL_NAMES = {
    0: "dabbling", 1: "novice", 2: "adequate", 3: "competent",
    4: "skilled", 5: "proficient", 6: "talented", 7: "adept",
    8: "expert", 9: "professional", 10: "accomplished", 11: "great",
    12: "master", 13: "high master", 14: "grand master", 15: "legendary",
}


def _skill_level_name(level: int | str) -> str:
    try:
        lvl = int(level)
    except (ValueError, TypeError):
        return str(level)
    if lvl >= 15:
        return "legendary"
    return _SKILL_LEVEL_NAMES.get(lvl, f"level {lvl}")


_STRESS_DESCRIPTIONS = {
    0: "ecstatic",
    1: "happy",
    2: "content",
    3: "fine",
    4: "stressed",
    5: "very unhappy",
    6: "on the verge of a breakdown",
}


def format_dwarf_narrative(dwarf: Dwarf) -> str:
    """Format a dwarf's complete data into concise narrative-ready text.

    Only includes notable/interesting details — skips neutral values.
    Designed to give an LLM just enough to write a grounded character.
    """
    lines: list[str] = []

    # Identity line
    age_str = f", age {dwarf.age:.0f}" if dwarf.age else ""
    noble_str = ""
    if dwarf.noble_positions:
        noble_str = f" ({', '.join(dwarf.noble_positions)})"
    lines.append(f"**{dwarf.name}** — {dwarf.profession}{noble_str}{age_str}")

    # Military
    if dwarf.military_squad:
        lines.append(f"  Member of {dwarf.military_squad}")

    # Personality (only notable traits — extremes that define the character)
    if dwarf.personality:
        notable_traits = []
        for facet in dwarf.personality.facets:
            if facet.is_notable and facet.description:
                notable_traits.append(facet.description)
        if notable_traits:
            lines.append(f"  Personality: {'; '.join(notable_traits)}")

        # Beliefs
        notable_beliefs = [b.description for b in dwarf.personality.notable_beliefs if b.description]
        if notable_beliefs:
            lines.append(f"  Values: {'; '.join(notable_beliefs)}")

        # Goals
        goal_descs = [g.description for g in dwarf.personality.goals if g.description]
        if goal_descs:
            lines.append(f"  Dreams: {'; '.join(goal_descs)}")

    # Physical — only standout attributes
    phys_descs = []
    for attr, value in dwarf.physical_attributes.items():
        desc = _describe_physical_attr(attr, value)
        if desc:
            phys_descs.append(desc)
    if phys_descs:
        lines.append(f"  Physical: {', '.join(phys_descs)}")

    # Mental — only standout attributes
    mental_descs = []
    for attr, value in dwarf.mental_attributes.items():
        desc = _describe_mental_attr(attr, value)
        if desc:
            mental_descs.append(desc)
    if mental_descs:
        lines.append(f"  Mind: {', '.join(mental_descs)}")

    # Skills — top 5, with readable level names
    if dwarf.skills:
        top_skills = sorted(dwarf.skills, key=lambda s: s.experience, reverse=True)[:5]
        skill_strs = [f"{_skill_level_name(s.level)} {_resolve_skill_name(s.name)}" for s in top_skills]
        lines.append(f"  Skills: {', '.join(skill_strs)}")

    # Stress
    stress_desc = _STRESS_DESCRIPTIONS.get(dwarf.stress_category)
    if stress_desc and dwarf.stress_category not in (2, 3):  # Skip "content"/"fine" — boring
        lines.append(f"  Mood: {stress_desc}")

    # Relationships
    if dwarf.relationships:
        rel_strs = [f"{r.relationship_type}: {r.target_name}" for r in dwarf.relationships]
        lines.append(f"  Family: {', '.join(rel_strs)}")

    # Equipment
    if dwarf.equipment:
        lines.append(f"  Equipment: {', '.join(dwarf.equipment[:5])}")

    # Wounds
    if dwarf.wounds:
        lines.append(f"  Wounds: injured {', '.join(dwarf.wounds)}")

    # Current activity
    if dwarf.current_job:
        readable_job = dwarf.current_job.replace("_", " ").lower()
        lines.append(f"  Currently: {readable_job}")

    return "\n".join(lines)


def format_fortress_context(metadata: dict) -> str:
    """Format fortress-level metadata into a narrative setting description."""
    parts: list[str] = []

    name = metadata.get("fortress_name") or metadata.get("site_name") or "an unnamed fortress"
    site_name = metadata.get("site_name", "")
    civ = metadata.get("civ_name", "")
    biome = metadata.get("biome", "").replace("_", " ").lower()
    year = metadata.get("year", 0)
    season = metadata.get("season", "")
    pop = metadata.get("population", 0)

    # Setting line
    setting = f"Fortress: {name}"
    if site_name and site_name != name:
        setting += f' ("{site_name}" in the common tongue)'
    parts.append(setting)

    if civ:
        parts.append(f"Civilization: {civ}")
    if biome:
        parts.append(f"Location: {biome}")
    if year:
        parts.append(f"Year {year}, {season}")
    if pop:
        parts.append(f"Population: {pop} dwarves")

    # Visitors
    visitors = metadata.get("visitors", [])
    if visitors:
        visitor_strs = []
        for v in visitors:
            vname = v.get("name", "Unknown")
            vrace = v.get("race", "")
            vrole = v.get("role", "visitor")
            visitor_strs.append(f"{vname} ({vrace}, {vrole})")
        parts.append(f"Visitors: {', '.join(visitor_strs)}")

    return "\n".join(parts)


def format_player_notes(notes: list, one_time_context: str = "") -> str:
    """Format player notes into LLM prompt context.

    Each note includes its tag and specific instructions for how the LLM
    should handle it (suspicion = hints, fact = truth, etc.).
    """
    from df_storyteller.schema.notes import TAG_INSTRUCTIONS

    if not notes and not one_time_context:
        return ""

    lines = [
        "## Player Context",
        "The following are the player's observations and theories about the fortress and its inhabitants.",
        "Follow the instructions for each note carefully — they control how you should use the information.",
        "",
    ]

    for note in notes:
        tag_upper = note.tag.value.upper()
        target = ""
        if note.target_type == "dwarf" and hasattr(note, "target_name"):
            target = f" about {note.target_name}"
        elif note.target_type == "fortress":
            target = " (fortress-wide)"

        timestamp = ""
        if note.game_year:
            timestamp = f" ({note.game_season.title()} of Year {note.game_year})"

        instruction = TAG_INSTRUCTIONS.get(note.tag, "Use this information in the narrative.")

        lines.append(f"[{tag_upper}{target}]{timestamp}")
        lines.append(f'"{note.text}"')
        lines.append(f"→ {instruction}")
        lines.append("")

    if one_time_context:
        lines.append("[PLAYER DIRECTION — for this generation only]")
        lines.append(f'"{one_time_context}"')
        lines.append("→ Incorporate this into the narrative as you see fit.")
        lines.append("")

    return "\n".join(lines)
