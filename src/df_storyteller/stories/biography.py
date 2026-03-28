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


def _bio_path(config: AppConfig, unit_id: int) -> Path:
    """Path to a dwarf's biography JSON file."""
    output_dir = Path(config.paths.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"bio_{unit_id}.json"


def load_biography_history(config: AppConfig, unit_id: int) -> list[dict]:
    """Load all previous biography entries for a dwarf."""
    path = _bio_path(config, unit_id)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_biography_entry(config: AppConfig, unit_id: int, entry: dict) -> None:
    """Append a biography entry to the dwarf's history."""
    history = load_biography_history(config, unit_id)
    history.append(entry)
    path = _bio_path(config, unit_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


async def generate_biography(
    config: AppConfig,
    dwarf_name: str,
    one_time_context: str = "",
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
    previous_entries = load_biography_history(config, dwarf.unit_id)

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
    dwarf_notes = get_notes_for_dwarf(config, dwarf.unit_id)
    fortress_notes = get_fortress_notes(config)
    all_notes = dwarf_notes + fortress_notes
    notes_text = format_player_notes(all_notes, one_time_context=one_time_context)

    # Custom user prompt for dated biography
    user_prompt = f"""Write a short biography entry for this dwarf as of {season.title()} of Year {year}.

## Current State
{ctx.character_text}

## Setting
{ctx.events_text}

{f"## Previous Entries{chr(10)}{previous_text}" if previous_text else ""}

{notes_text}

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
    })

    return bio_text


async def generate_eulogy(
    config: AppConfig,
    dwarf_name: str,
    one_time_context: str = "",
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
    previous_entries = load_biography_history(config, dwarf.unit_id)
    previous_text = ""
    if previous_entries:
        previous_text = "BIOGRAPHY HISTORY (the dwarf's life story):\n\n"
        for entry in previous_entries:
            previous_text += f"--- {entry.get('season', '').title()} of Year {entry.get('year', '?')} ---\n"
            previous_text += entry.get("text", "") + "\n\n"

    # Player notes
    dwarf_notes = get_notes_for_dwarf(config, dwarf.unit_id)
    fortress_notes = get_fortress_notes(config)
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
    })

    return eulogy_text
