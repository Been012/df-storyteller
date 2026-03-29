"""Character Biography story generator.

Biographies are dated snapshots — each one captures who the dwarf is at that
moment in time. As the dwarf changes (gains skills, suffers trauma, gets married),
new biography entries are generated and appended, creating a living record of
their development.
"""

from __future__ import annotations

import json
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.context.context_builder import ContextBuilder
from df_storyteller.context.loader import load_game_state
from df_storyteller.context.narrative_formatter import format_dwarf_narrative, format_fortress_context
from df_storyteller.llm.prompt_templates import render_system_prompt, render_user_prompt
from df_storyteller.stories.base import create_provider


def _bio_path(config: AppConfig, unit_id: int, output_dir: Path | None = None) -> Path:
    """Path to a dwarf's biography JSON file."""
    d = output_dir or Path(config.paths.output_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"bio_{unit_id}.json"


def load_biography_history(config: AppConfig, unit_id: int, output_dir: Path | None = None) -> list[dict]:
    """Load all previous biography entries for a dwarf."""
    path = _bio_path(config, unit_id, output_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_biography_entry(config: AppConfig, unit_id: int, entry: dict, output_dir: Path | None = None) -> None:
    """Append a biography entry to the dwarf's history."""
    history = load_biography_history(config, unit_id, output_dir)
    history.append(entry)
    path = _bio_path(config, unit_id, output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


async def generate_biography(
    config: AppConfig,
    dwarf_name: str,
    one_time_context: str = "",
    output_dir: Path | None = None,
) -> str:
    """Generate a dated biography entry for a dwarf.

    Each call creates a new entry timestamped with the current game year/season.
    Previous entries are included as context so the LLM can describe how the
    dwarf has changed over time.
    """
    provider = create_provider(config)
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    dwarf = character_tracker.find_by_name(dwarf_name)
    if not dwarf:
        available = character_tracker.ranked_characters()
        if available:
            names = [d.name for d, _ in available[:10]]
            return f"Dwarf '{dwarf_name}' not found. Available dwarves:\n" + "\n".join(f"  - {n}" for n in names)
        return f"Dwarf '{dwarf_name}' not found. Take a snapshot first (run 'storyteller-begin' in DFHack)."

    builder = ContextBuilder(
        event_store=event_store,
        character_tracker=character_tracker,
        world_lore=world_lore,
        max_context_tokens=provider.max_context_tokens // 2,
    )

    ctx = builder.build_biography_context(
        unit_id=dwarf.unit_id,
        fortress_name=metadata.get("fortress_name", ""),
    )

    # Current state
    ctx.character_text = format_dwarf_narrative(dwarf)
    ctx.events_text = format_fortress_context(metadata) + "\n\n" + (ctx.events_text or "")

    # Load previous bio entries for continuity
    year = metadata.get("year", 0)
    season = metadata.get("season", "")
    previous_entries = load_biography_history(config, dwarf.unit_id, output_dir)

    previous_text = ""
    if previous_entries:
        previous_text = "PREVIOUS BIOGRAPHY ENTRIES (show how this dwarf has changed over time):\n\n"
        for entry in previous_entries[-3:]:  # Last 3 entries for context
            previous_text += f"--- {entry.get('season', '').title()} of Year {entry.get('year', '?')} ---\n"
            previous_text += entry.get("text", "") + "\n\n"

    system_prompt = render_system_prompt(
        ctx,
        character_name=dwarf.name,
        profession=dwarf.profession,
    )

    # Player notes for this dwarf + fortress
    from df_storyteller.context.notes_store import get_notes_for_dwarf, get_fortress_notes
    from df_storyteller.context.narrative_formatter import format_player_notes
    dwarf_notes = get_notes_for_dwarf(config, dwarf.unit_id, output_dir)
    fortress_notes = get_fortress_notes(config, output_dir)
    all_notes = dwarf_notes + fortress_notes
    notes_text = format_player_notes(all_notes, one_time_context=one_time_context)

    # Add highlight role context if this dwarf is highlighted
    from df_storyteller.context.highlights_store import get_highlight_for_dwarf
    dwarf_highlight = get_highlight_for_dwarf(config, dwarf.unit_id, output_dir)
    if dwarf_highlight:
        notes_text += f"\n\nThis dwarf is marked as a {dwarf_highlight.role.value.upper()} by the player. Frame the biography accordingly."

    # Quests involving this dwarf
    from df_storyteller.context.quest_store import load_all_quests
    all_quests = load_all_quests(config, output_dir)
    dwarf_quests = [q for q in all_quests if dwarf.name in " ".join(q.related_unit_names)]
    quest_text = ""
    if dwarf_quests:
        quest_lines = []
        for q in dwarf_quests[-3:]:
            status = "completed" if q.status.value == "completed" else "ongoing"
            quest_lines.append(f"- {q.title} ({status}): {q.description}")
        quest_text = "\n## Quests\n" + "\n".join(quest_lines)

    # Custom user prompt for dated biography
    user_prompt = f"""Write a short biography entry for this dwarf as of {season.title()} of Year {year}.

## Current State
{ctx.character_text}

## Setting
{ctx.events_text}

{f"## Previous Entries{chr(10)}{previous_text}" if previous_text else ""}

{notes_text}
{quest_text}

{"If previous entries exist, focus on what has CHANGED — new events, shifting mood, new skills, injuries, relationships. Do not repeat information from previous entries." if previous_text else "This is the first entry. Introduce the dwarf and their place in the fortress."}

Write 2-3 short paragraphs (150-250 words). Date the entry as "{season.title()} of Year {year}"."""

    try:
        bio_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.biography_max_tokens,
            temperature=config.llm.temperature,
        )
    except Exception as e:
        return f"[Biography generation failed: {e}. Check your LLM provider settings and try again.]"

    # Save this entry
    _save_biography_entry(config, dwarf.unit_id, {
        "year": year,
        "season": season,
        "text": bio_text,
        "profession": dwarf.profession,
        "stress_category": dwarf.stress_category,
    }, output_dir)

    return bio_text


async def generate_eulogy(
    config: AppConfig,
    dwarf_name: str,
    one_time_context: str = "",
    output_dir: Path | None = None,
) -> str:
    """Generate a death eulogy — the final biography entry for a fallen dwarf.

    Gathers the dwarf's full history, cause of death, relationships, and
    achievements to produce a memorial narrative.
    """
    from df_storyteller.context.context_builder import ContextBuilder, _format_event
    from df_storyteller.context.notes_store import get_notes_for_dwarf, get_fortress_notes
    from df_storyteller.context.narrative_formatter import format_player_notes
    from df_storyteller.schema.events import EventType

    provider = create_provider(config)
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    dwarf = character_tracker.find_by_name(dwarf_name)
    if not dwarf:
        return f"Dwarf '{dwarf_name}' not found."

    builder = ContextBuilder(
        event_store=event_store,
        character_tracker=character_tracker,
        world_lore=world_lore,
        max_context_tokens=provider.max_context_tokens // 2,
    )

    ctx = builder.build_biography_context(
        unit_id=dwarf.unit_id,
        fortress_name=metadata.get("fortress_name", ""),
    )

    ctx.character_text = format_dwarf_narrative(dwarf)
    ctx.events_text = format_fortress_context(metadata) + "\n\n" + (ctx.events_text or "")

    year = metadata.get("year", 0)
    season = metadata.get("season", "")

    # Find the death event for cause-of-death details
    death_context = ""
    dwarf_events = event_store.events_for_unit(dwarf.unit_id)
    for event in reversed(dwarf_events):
        if event.event_type == EventType.DEATH:
            death_context = f"CAUSE OF DEATH:\n{_format_event(event)}"
            if hasattr(event.data, "cause"):
                death_context += f"\nCause: {event.data.cause}"
            if hasattr(event.data, "killer") and event.data.killer:
                death_context += f"\nKiller: {event.data.killer.name}"
            if hasattr(event.data, "age") and event.data.age:
                death_context += f"\nAge at death: {event.data.age}"
            break

    # Load full biography history for the eulogy
    previous_entries = load_biography_history(config, dwarf.unit_id, output_dir)
    previous_text = ""
    if previous_entries:
        previous_text = "BIOGRAPHY HISTORY (the dwarf's life story):\n\n"
        for entry in previous_entries:
            previous_text += f"--- {entry.get('season', '').title()} of Year {entry.get('year', '?')} ---\n"
            previous_text += entry.get("text", "") + "\n\n"

    # Player notes
    dwarf_notes = get_notes_for_dwarf(config, dwarf.unit_id, output_dir)
    fortress_notes = get_fortress_notes(config, output_dir)
    notes_text = format_player_notes(dwarf_notes + fortress_notes, one_time_context=one_time_context)

    system_prompt = render_system_prompt(
        ctx,
        character_name=dwarf.name,
        profession=dwarf.profession,
    )

    user_prompt = f"""Write a death eulogy for {dwarf.name}, who has fallen in {season.title()} of Year {year}.

## The Departed
{ctx.character_text}

## Setting
{ctx.events_text}

{f"## {death_context}" if death_context else ""}

{f"## Life Story{chr(10)}{previous_text}" if previous_text else ""}

{notes_text}

Write a memorial eulogy (200-350 words) honoring this dwarf's life, achievements, and legacy. \
Reflect on who they were — their personality, their craft, their relationships, and what they meant to the fortress. \
Address how they died and what is lost with their passing. \
The tone should be solemn and reverent, befitting a dwarven memorial. \
End with a line about how the fortress remembers them."""

    try:
        eulogy_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.biography_max_tokens,
            temperature=config.llm.temperature,
        )
    except Exception as e:
        return f"[Eulogy generation failed: {e}. Check your LLM provider settings and try again.]"

    # Save as a final biography entry marked as eulogy
    _save_biography_entry(config, dwarf.unit_id, {
        "year": year,
        "season": season,
        "text": eulogy_text,
        "profession": dwarf.profession,
        "stress_category": dwarf.stress_category,
        "is_eulogy": True,
    }, output_dir)

    return eulogy_text


async def generate_diary(
    config: AppConfig,
    dwarf_name: str,
    one_time_context: str = "",
    output_dir: Path | None = None,
) -> str:
    """Generate a first-person diary entry from a dwarf's perspective.

    The entry is heavily influenced by the dwarf's personality traits, beliefs,
    stress level, and recent events. Written in first person as the dwarf.
    """
    provider = create_provider(config)
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    dwarf = character_tracker.find_by_name(dwarf_name)
    if not dwarf:
        return f"Dwarf '{dwarf_name}' not found."

    builder = ContextBuilder(
        event_store=event_store,
        character_tracker=character_tracker,
        world_lore=world_lore,
        max_context_tokens=provider.max_context_tokens // 2,
    )

    ctx = builder.build_biography_context(
        unit_id=dwarf.unit_id,
        fortress_name=metadata.get("fortress_name", ""),
    )

    ctx.character_text = format_dwarf_narrative(dwarf)
    ctx.events_text = format_fortress_context(metadata) + "\n\n" + (ctx.events_text or "")

    year = metadata.get("year", 0)
    season = metadata.get("season", "")

    # Build rich personality context for first-person voice
    personality_lines = []
    if dwarf.personality:
        for facet in dwarf.personality.facets:
            if facet.is_notable and facet.description:
                personality_lines.append(facet.description)
        for belief in dwarf.personality.notable_beliefs:
            if belief.description:
                personality_lines.append(f"Values: {belief.description}")
        for goal in dwarf.personality.goals:
            if goal.description:
                personality_lines.append(f"Dreams of: {goal.description}")
    personality_text = "\n".join(f"- {p}" for p in personality_lines) if personality_lines else "No notable personality traits."

    stress_descriptions = {
        0: "ecstatic, overjoyed, life is wonderful",
        1: "happy, content, things are going well",
        2: "fine, no complaints",
        3: "okay, nothing special",
        4: "stressed, things are wearing on them",
        5: "very unhappy, struggling to cope",
        6: "on the verge of a breakdown, barely holding it together",
    }
    mood_text = stress_descriptions.get(dwarf.stress_category, "feeling neutral")

    # Recent events involving this dwarf
    from df_storyteller.context.context_builder import _format_event
    dwarf_events = event_store.events_for_unit(dwarf.unit_id)
    recent_event_lines = [_format_event(e) for e in dwarf_events[-5:]]
    events_text = "\n".join(recent_event_lines) if recent_event_lines else "Nothing notable has happened recently."

    # Relationships
    rel_lines = []
    for rel in dwarf.relationships[:5]:
        rel_lines.append(f"{rel.relationship_type}: {rel.target_name}")
    rel_text = "\n".join(f"- {r}" for r in rel_lines) if rel_lines else "No close relationships."

    # Player notes and quests involving this dwarf
    from df_storyteller.context.notes_store import get_notes_for_dwarf
    from df_storyteller.context.narrative_formatter import format_player_notes
    notes = get_notes_for_dwarf(config, dwarf.unit_id, output_dir)
    notes_text = format_player_notes(notes, one_time_context=one_time_context)

    quest_text = ""
    from df_storyteller.context.quest_store import load_all_quests
    all_quests = load_all_quests(config, output_dir)
    dwarf_quests = [q for q in all_quests if dwarf.name in " ".join(q.related_unit_names)]
    if dwarf_quests:
        quest_lines = [f"- {q.title} ({q.status.value}): {q.description}" for q in dwarf_quests[-3:]]
        quest_text = "\n## Quests Involving This Dwarf\n" + "\n".join(quest_lines)

    # Previous diary/bio entries for continuity
    previous_entries = load_biography_history(config, dwarf.unit_id, output_dir)
    previous_text = ""
    if previous_entries:
        for entry in previous_entries[-2:]:
            entry_type = "diary" if entry.get("is_diary") else "biography"
            previous_text += f"--- Previous {entry_type} ({entry.get('season', '').title()} of Year {entry.get('year', '?')}) ---\n"
            previous_text += entry.get("text", "")[:300] + "\n\n"

    from df_storyteller.stories.df_mechanics import DF_MECHANICS_REFERENCE
    system_prompt = f"""You are writing a diary entry AS the dwarf {dwarf.name}. First person. This is their private journal.
{DF_MECHANICS_REFERENCE}

CRITICAL: Write in the VOICE of this dwarf based on their personality:
{personality_text}

Current emotional state: {mood_text}

VOICE RULES:
- If the dwarf is anxious, the writing should be nervous, fragmented, worried.
- If the dwarf is confident/brave, the writing should be bold, declarative, maybe boastful.
- If the dwarf values craftsmanship, they notice materials, quality, the feel of tools.
- If the dwarf is prone to anger, they rant, complain, hold grudges.
- If the dwarf is cheerful, they find joy in small things, joke, express warmth.
- If the dwarf is depressed, the writing is heavy, slow, fixated on loss.
- Stress level strongly affects tone: ecstatic dwarves are effusive, miserable ones are bleak.
- Use the dwarf's profession to color what they notice — a miner talks about stone, a soldier about threats.
- Keep it SHORT: 100-200 words. This is a quick journal entry, not an essay."""

    user_prompt = f"""Write a diary entry for {dwarf.name} as of {season.title()} of Year {year}.

## Who I Am
{ctx.character_text}

## My Relationships
{rel_text}

## What's Been Happening
{events_text}

## The Fortress
{ctx.events_text}

{notes_text}
{quest_text}

{f"## Previous Entries{chr(10)}{previous_text}" if previous_text else ""}

Write a first-person diary entry. Start with something like "Today..." or a thought, not "Dear diary". Be specific about real events, real people, real feelings. 100-200 words."""

    try:
        diary_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.biography_max_tokens,
            temperature=0.9,  # Higher temp for more personality variation
        )
    except Exception as e:
        return f"[Diary generation failed: {e}. Check your LLM provider settings and try again.]"

    # Save as a diary entry in the bio history
    _save_biography_entry(config, dwarf.unit_id, {
        "year": year,
        "season": season,
        "text": diary_text,
        "profession": dwarf.profession,
        "stress_category": dwarf.stress_category,
        "is_diary": True,
    }, output_dir)

    return diary_text
