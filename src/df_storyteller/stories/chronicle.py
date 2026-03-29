"""Fortress Chronicle story generator."""

from __future__ import annotations

from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.context.context_builder import ContextBuilder
from df_storyteller.context.loader import load_game_state
from df_storyteller.context.narrative_formatter import format_dwarf_narrative, format_fortress_context
from df_storyteller.llm.prompt_templates import render_system_prompt, render_user_prompt
from df_storyteller.stories.base import create_provider


async def generate_chronicle(
    config: AppConfig,
    season_spec: str | None = None,
    one_time_context: str = "",
    output_dir: Path | None = None,
) -> str:
    """Generate a fortress chronicle entry from all available game data."""
    provider = create_provider(config)
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    year = metadata["year"]
    season = metadata["season"]
    if season_spec:
        parts = season_spec.lower().split()
        if len(parts) == 2:
            season = parts[0]
            year = int(parts[1])
        elif len(parts) == 1:
            try:
                year = int(parts[0])
            except ValueError:
                season = parts[0]

    builder = ContextBuilder(
        event_store=event_store,
        character_tracker=character_tracker,
        world_lore=world_lore,
        max_context_tokens=provider.max_context_tokens // 2,
    )

    ctx = builder.build_chronicle_context(
        year=year,
        season=season,
        fortress_name=metadata.get("fortress_name", ""),
    )

    # Build narrative-ready character descriptions
    char_lines = [format_dwarf_narrative(dwarf) for dwarf, _ in character_tracker.ranked_characters()]
    ctx.character_text = "\n\n".join(char_lines) if char_lines else ctx.character_text

    # Build fortress setting context
    fortress_context = format_fortress_context(metadata)

    # Include captured events from the event store for this season
    from df_storyteller.context.context_builder import _format_event
    season_events = event_store.events_in_season(year, season)
    if season_events:
        event_lines = [_format_event(e) for e in season_events]
        events_section = "## Events This Season\n" + "\n".join(event_lines)
    else:
        events_section = ""

    # Combine: fortress context + captured events + any existing context
    parts = [fortress_context]
    if events_section:
        parts.append(events_section)
    if ctx.events_text.strip():
        parts.append(ctx.events_text)
    ctx.events_text = "\n\n".join(p for p in parts if p)
    ctx.year = year
    ctx.season = season

    # Load previous chronicle for narrative continuity
    from df_storyteller.output.journal import _journal_path
    journal_path = _journal_path(config, output_dir)
    if journal_path.exists():
        import re as _re
        journal_text = journal_path.read_text(encoding="utf-8", errors="replace")
        # Find the most recent entry that isn't the current season
        entries = _re.split(r"\n---\n", journal_text)
        for entry in reversed(entries):
            entry = entry.strip()
            if not entry or entry.startswith("# Fortress Journal"):
                continue
            header_match = _re.match(r"##\s+([^\n]+)", entry)
            if header_match:
                header = header_match.group(1)
                # Skip if it's the same season we're writing for
                if season.lower() in header.lower() and str(year) in header:
                    continue
                # Use first 500 chars as summary of previous entry
                body = entry[header_match.end():].strip()[:500]
                if body:
                    ctx.previous_summary = f"Previous chronicle ({header}):\n{body}"
                break

    # Add world lore summary if available
    if world_lore.is_loaded and not ctx.lore_text.strip():
        # Get civilization history for narrative background
        legends = world_lore._legends
        if legends and metadata.get("fortress_info", {}).get("civ_id", -1) >= 0:
            civ_history = world_lore.get_civilization_history(metadata["fortress_info"]["civ_id"])
            if civ_history:
                ctx.lore_text = civ_history

    ctx.fortress_name = metadata.get("fortress_name", "")

    # Add player notes to context
    from df_storyteller.context.notes_store import get_all_active_notes
    from df_storyteller.context.narrative_formatter import format_player_notes
    notes = get_all_active_notes(config, output_dir)
    notes_text = format_player_notes(notes, one_time_context=one_time_context)
    if notes_text:
        ctx.lore_text = (ctx.lore_text + "\n\n" + notes_text).strip()

    # Add recently completed quests as narrative context
    from df_storyteller.context.quest_store import get_completed_quests
    completed = get_completed_quests(config, output_dir)
    if completed:
        # Include quests completed this year or last year for narrative continuity
        recent_quests = [q for q in completed if q.game_year >= year - 1]
        if recent_quests:
            quest_lines = []
            for q in recent_quests[-5:]:  # Last 5 completed quests
                line = f"- [{q.category.value.title()}] {q.title}: {q.description}"
                if q.completion_narrative:
                    line += f" (Completed: {q.completion_narrative[:150]}...)" if len(q.completion_narrative) > 150 else f" (Completed: {q.completion_narrative})"
                quest_lines.append(line)
            quest_context = "COMPLETED QUESTS (weave these achievements into the chronicle):\n" + "\n".join(quest_lines)
            ctx.lore_text = (ctx.lore_text + "\n\n" + quest_context).strip()

    # Add active quests as ongoing storylines
    from df_storyteller.context.quest_store import get_active_quests
    active = get_active_quests(config, output_dir)
    if active:
        active_lines = [f"- [{q.category.value.title()}] {q.title}: {q.description}" for q in active[:5]]
        active_context = "ACTIVE QUESTS (reference these as ongoing ambitions or challenges):\n" + "\n".join(active_lines)
        ctx.lore_text = (ctx.lore_text + "\n\n" + active_context).strip()

    # Add player-highlighted dwarves for narrative focus
    from df_storyteller.context.highlights_store import load_all_highlights
    highlights = load_all_highlights(config, output_dir)
    if highlights:
        highlight_lines = [f"- {h.name}: {h.role.value.upper()}" for h in highlights]
        highlights_text = "PLAYER-HIGHLIGHTED DWARVES (give these characters more narrative focus):\n" + "\n".join(highlight_lines)
        ctx.lore_text = (ctx.lore_text + "\n\n" + highlights_text).strip()

    system_prompt = render_system_prompt(ctx)
    user_prompt = render_user_prompt(ctx)

    try:
        story = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.chronicle_max_tokens,
            temperature=config.llm.temperature,
        )
    except Exception as e:
        return f"[Chronicle generation failed: {e}. Check your LLM provider settings and try again.]"

    from df_storyteller.output.journal import append_to_journal
    append_to_journal(config, story, year, season, output_dir)

    return story
