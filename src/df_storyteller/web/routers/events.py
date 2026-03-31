"""Event feed, battle reports, and chat summary routes."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_gamelog_path(config) -> Path | None:
    """Resolve gamelog path from config, falling back to df_install/gamelog.txt."""
    if config.paths.gamelog:
        return Path(config.paths.gamelog)
    if config.paths.df_install:
        candidate = Path(config.paths.df_install) / "gamelog.txt"
        if candidate.exists():
            return candidate
    return None


def _build_outcome_summary(group: list, title_to_dwarf: dict, ranked: list) -> str:
    """Build a specific outcome summary stating who died and who survived."""
    killed = []
    survived = []
    for event in group:
        d = event.data
        if getattr(d, "is_lethal", False):
            defender_name = d.defender.name if hasattr(d, "defender") else "Unknown"
            # Resolve to real name if it's a title
            real_dwarf = title_to_dwarf.get(defender_name.lower())
            if real_dwarf:
                defender_name = real_dwarf.name.split(",")[0].strip()
            killed.append(defender_name)

            attacker_name = d.attacker.name if hasattr(d, "attacker") else "Unknown"
            real_atk = title_to_dwarf.get(attacker_name.lower())
            if real_atk:
                attacker_name = real_atk.name.split(",")[0].strip()
            survived.append(attacker_name)
        else:
            for attr in ("attacker", "defender"):
                name = getattr(d, attr, None)
                if name and hasattr(name, "name"):
                    real = title_to_dwarf.get(name.name.lower())
                    resolved = real.name.split(",")[0].strip() if real else name.name
                    if resolved not in survived and resolved not in killed:
                        survived.append(resolved)

    parts = []
    if killed:
        parts.append(f"KILLED: {', '.join(set(killed))}")
    if survived:
        parts.append(f"SURVIVED: {', '.join(set(survived))}")
    if not killed:
        parts.append("No fatalities — all combatants survived.")
    return "\n".join(parts)


@router.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "events", metadata)

    from df_storyteller.context.context_builder import _format_event
    SEASON_ORDER = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
    events = []
    for event in event_store.recent_events(200):
        desc = _format_event(event)
        # Strip the [Season Year] prefix and type label — the UI shows those separately
        desc = re.sub(r"^\[.*?\]\s*", "", desc)
        desc = re.sub(r"^[A-Za-z_ ]+:\s", "", desc)
        # Skip empty, session markers, and gamelog announcements (duplicated by DFHack events)
        if not desc.strip():
            continue
        if "Loading Fortress" in desc or "Starting New Outpost" in desc or "STARTING NEW GAME" in desc:
            continue
        if event.event_type.value == "announcement":
            continue
        if event.event_type.value == "combat":
            continue
        events.append({
            "type": event.event_type.value,
            "year": event.game_year,
            "season": event.season.value,
            "_sort": (event.game_year, SEASON_ORDER.get(event.season.value, 0), event.game_tick),
            "description": desc,
        })

    # Sort by year/season/tick descending (newest first), then remove sort key
    events.sort(key=lambda e: e["_sort"], reverse=True)
    events = events[:100]  # Limit after sorting
    for event in events:
        del event["_sort"]

    # Build detailed combat encounters, grouped into engagements
    # Consecutive combat events (close in tick) are grouped as a single battle/siege
    from df_storyteller.schema.events import EventType as ET

    def _collapse_repeats(lines: list[str]) -> list[str]:
        """Collapse consecutive duplicate lines into 'line x3' format like DF does."""
        if not lines:
            return lines
        result = []
        prev = lines[0]
        count = 1
        for line in lines[1:]:
            if line == prev:
                count += 1
            else:
                result.append(f"{prev} x{count}" if count > 1 else prev)
                prev = line
                count = 1
        result.append(f"{prev} x{count}" if count > 1 else prev)
        return result

    def _build_encounter(event):
        d = event.data
        blows = []
        if hasattr(d, "blows"):
            for b in d.blows:
                blows.append({"action": b.action, "body_part": b.body_part, "weapon": b.weapon, "effect": b.effect})
        raw_lines = d.raw_text.split("\n") if hasattr(d, "raw_text") and d.raw_text else []
        raw_lines = _collapse_repeats(raw_lines)
        return {
            "attacker": d.attacker.name if hasattr(d, "attacker") else "Unknown",
            "defender": d.defender.name if hasattr(d, "defender") else "Unknown",
            "weapon": getattr(d, "weapon", ""),
            "blows": blows,
            "raw_lines": raw_lines,
            "outcome": getattr(d, "outcome", ""),
            "is_lethal": getattr(d, "is_lethal", False),
            "season": event.season.value,
            "year": event.game_year,
            "tick": event.game_tick,
        }

    # Collect all combat events in chronological order
    all_combat = []
    for event in event_store.recent_events(200):
        if event.event_type == ET.COMBAT:
            all_combat.append(event)

    # Group consecutive combat events by tick proximity (within 500 ticks = ~same engagement)
    TICK_THRESHOLD = config.web.combat_tick_threshold
    engagement_groups: list[list] = []
    current_group: list = []
    for event in all_combat:
        if current_group and abs(event.game_tick - current_group[-1].game_tick) > TICK_THRESHOLD:
            engagement_groups.append(current_group)
            current_group = []
        current_group.append(event)
    if current_group:
        engagement_groups.append(current_group)

    # Build combat_encounters: grouped engagements (newest first)
    combat_encounters = []
    for group in reversed(engagement_groups):
        fights = [_build_encounter(e) for e in group]
        if len(fights) == 1:
            # Solo fight — render as before
            combat_encounters.append(fights[0])
        else:
            # Multi-fight engagement — create a grouped entry
            participants = set()
            total_blows = 0
            any_lethal = False
            all_raw_lines = []
            for f in fights:
                participants.add(f["attacker"])
                participants.add(f["defender"])
                total_blows += len(f["blows"])
                if f["is_lethal"]:
                    any_lethal = True
                all_raw_lines.extend(f["raw_lines"])

            casualties = [f for f in fights if f["is_lethal"]]
            combat_encounters.append({
                "is_engagement": True,
                "fight_count": len(fights),
                "fights": fights,
                "participants": sorted(participants),
                "total_blows": total_blows,
                "is_lethal": any_lethal,
                "casualties": len(casualties),
                "season": fights[0]["season"],
                "year": fights[0]["year"],
                "raw_lines": all_raw_lines,
            })
        if len(combat_encounters) >= 20:
            break

    # Extract conversation lines from the gamelog for the chat log
    chat_lines = []
    gamelog_path = _resolve_gamelog_path(config)
    if gamelog_path and gamelog_path.exists():
        from df_storyteller.context.loader import _read_current_session_gamelog
        # Conversation pattern: "Name, Profession: I talked to..."
        chat_pattern = re.compile(r'^(.+?),\s*(.+?):\s+(.+)$')
        for line in _read_current_session_gamelog(gamelog_path):
            m = chat_pattern.match(line)
            if m:
                name = m.group(1)
                profession = m.group(2)
                message = m.group(3)
                # Skip lines that are actually cancellation messages
                if message.startswith("cancels "):
                    continue
                chat_lines.append({
                    "name": name,
                    "profession": profession,
                    "message": message,
                })

    # Load saved battle reports — split into engagement reports (shown in section) and solo (shown inline)
    saved_battle_reports = []
    solo_reports_by_index: dict[int, dict] = {}
    try:
        fortress_dir = _get_fortress_dir(config, metadata)
        reports_path = fortress_dir / "battle_reports.json"
        if reports_path.exists():
            import json as _json
            all_reports = _json.loads(reports_path.read_text(encoding="utf-8", errors="replace"))
            for r in all_reports:
                if r.get("is_engagement"):
                    saved_battle_reports.append(r)
                else:
                    idx = r.get("encounter_index")
                    if idx is not None:
                        solo_reports_by_index[idx] = r
    except (ValueError, OSError):
        pass

    # Load saved chat summaries
    saved_chat_summaries: list[dict] = []
    try:
        fortress_dir = _get_fortress_dir(config, metadata)
        summaries_path = fortress_dir / "chat_summaries.json"
        if summaries_path.exists():
            saved_chat_summaries = json.loads(summaries_path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        pass

    return templates.TemplateResponse(request=request, name="events.html", context={
        **ctx, "content_class": "content-wide", "events": events, "combat_encounters": combat_encounters, "chat_lines": chat_lines,
        "saved_battle_reports": saved_battle_reports, "solo_reports": solo_reports_by_index,
        "saved_chat_summaries": saved_chat_summaries,
    })


@router.post("/api/chat/summarize")
async def api_summarize_chat(request: Request):
    """Use AI to summarize the fortress chat log."""
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)

    gamelog_path = _resolve_gamelog_path(config)
    if not gamelog_path or not gamelog_path.exists():
        return StreamingResponse(iter(["No gamelog found."]), media_type="text/plain")

    from df_storyteller.context.loader import _read_current_session_gamelog
    chat_pattern = re.compile(r'^(.+?),\s*(.+?):\s+(.+)$')
    chat_text = ""
    for line in _read_current_session_gamelog(gamelog_path):
        m = chat_pattern.match(line)
        if m and not m.group(3).startswith("cancels "):
            chat_text += f"{m.group(1)}: {m.group(3)}\n"

    if not chat_text.strip():
        return StreamingResponse(iter(["No conversations found in the current session."]), media_type="text/plain")

    fortress_name = metadata.get("fortress_name", "the fortress")
    season = metadata.get("season", "").title()
    year = metadata.get("year", 0)

    from df_storyteller.stories.base import create_provider
    provider = create_provider(config)

    fortress_dir = _get_fortress_dir(config, metadata)

    async def _stream():
        try:
            full_text = ""
            async for chunk in provider.stream_generate(
                system_prompt="You are a dwarven chronicler summarizing the social life of a fortress. Write in a warm, narrative tone befitting a fantasy chronicle. Focus on relationships, emotions, conflicts, and notable interactions.",
                user_prompt=f"""Summarize the social happenings in {fortress_name} during {season} of Year {year} based on these dwarf conversations and thoughts:

{chat_text}

Write 2-3 paragraphs summarizing the social mood, notable relationships, tensions, and daily life. Mention specific dwarves by name. Note any new friendships, family bonds, grievances, or emotional states that stand out.""",
                max_tokens=config.story.chat_summary_max_tokens,
                temperature=config.llm.temperature,
            ):
                full_text += chunk
                yield chunk

            # Save summary to disk
            try:
                summaries_path = fortress_dir / "chat_summaries.json"
                existing: list[dict] = []
                if summaries_path.exists():
                    existing = json.loads(summaries_path.read_text(encoding="utf-8", errors="replace"))
                from datetime import datetime as _dt
                existing.append({
                    "text": full_text,
                    "season": season,
                    "year": year,
                    "generated_at": _dt.now().isoformat(),
                })
                summaries_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                logger.warning("Failed to save chat summary to disk")
        except ValueError as e:
            logger.warning("Chat summary generation failed: %s", e)
            yield f"Error: {e}"
        except Exception:
            logger.exception("Chat summary generation failed")
            yield "Error: generation failed. Check Settings and try again."

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/api/battle-report/{encounter_index}")
async def api_battle_report(encounter_index: int):
    """Generate a dramatic battle/siege report for a combat encounter or engagement."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)

    # Rebuild the same engagement groups as the events page
    from df_storyteller.schema.events import EventType as ET
    TICK_THRESHOLD = config.web.combat_tick_threshold
    all_combat = [e for e in event_store.recent_events(200) if e.event_type == ET.COMBAT]

    engagement_groups: list[list] = []
    current_group: list = []
    for event in all_combat:
        if current_group and abs(event.game_tick - current_group[-1].game_tick) > TICK_THRESHOLD:
            engagement_groups.append(current_group)
            current_group = []
        current_group.append(event)
    if current_group:
        engagement_groups.append(current_group)

    # Reverse to match the template order (newest first)
    engagement_groups.reverse()

    if encounter_index >= len(engagement_groups):
        return StreamingResponse(iter(["Combat encounter not found."]), media_type="text/plain")

    group = engagement_groups[encounter_index]
    is_siege = len(group) > 1

    # Build combined combat text and collect combatant unit_ids directly
    all_raw = []
    participants = set()
    combatant_unit_ids: list[int] = []  # ordered — first combatant preferred as author
    any_lethal = False
    for event in group:
        d = event.data
        if hasattr(d, "raw_text") and d.raw_text:
            all_raw.append(d.raw_text)
        if hasattr(d, "attacker"):
            participants.add(d.attacker.name)
            if d.attacker.unit_id and d.attacker.unit_id not in combatant_unit_ids:
                combatant_unit_ids.append(d.attacker.unit_id)
        if hasattr(d, "defender"):
            participants.add(d.defender.name)
            if d.defender.unit_id and d.defender.unit_id not in combatant_unit_ids:
                combatant_unit_ids.append(d.defender.unit_id)
        if getattr(d, "is_lethal", False):
            any_lethal = True

    combined_raw = "\n---\n".join(all_raw)
    season = group[0].season.value.title()
    year = group[0].game_year

    # Pick the author: combatant if alive, else best writer/social dwarf, else mysterious figure
    author_name = ""
    author_context = ""

    ranked = character_tracker.ranked_characters()
    name_mappings: list[str] = []
    for dwarf, _ in ranked:
        short_name = dwarf.name.split(",")[0].strip()
        if dwarf.profession:
            name_mappings.append(f"'{dwarf.profession}' = {short_name}")
        for pos in dwarf.noble_positions:
            name_mappings.append(f"'{pos}' = {short_name}")

    # Prefer actual combatants as author (first combatant who's alive wins)
    combatant_author = None
    characters = character_tracker._characters
    for uid in combatant_unit_ids:
        dwarf = characters.get(uid)
        if dwarf and dwarf.is_alive:
            combatant_author = dwarf
            break

    if combatant_author:
        author_name = combatant_author.name.split(",")[0].strip()
        author_context = f"Written by {author_name}, who fought in this battle. Write from their FIRST-PERSON perspective ('I swung my axe...', 'I felt the impact...'). You ARE {author_name}."
    else:
        # Find best writer/social dwarf
        best_writer = None
        best_score = -1
        for dwarf, _ in ranked:
            if not dwarf.is_alive:
                continue
            for skill in dwarf.skills:
                if skill.name.lower() in ("writing", "prose", "poetry", "social awareness", "persuasion", "conversation"):
                    if skill.experience > best_score:
                        best_score = skill.experience
                        best_writer = dwarf

        if best_writer:
            author_name = best_writer.name.split(",")[0].strip()
            author_context = f"Written by {author_name}, the fortress chronicler. They didn't fight but recorded the battle from witness accounts."
        elif any(d.is_alive for d, _ in ranked):
            # Any living dwarf as fallback
            for dwarf, _ in ranked:
                if dwarf.is_alive:
                    author_name = dwarf.name.split(",")[0].strip()
                    author_context = f"Written by {author_name}, a witness to the battle."
                    break
        else:
            author_name = "A Mysterious Figure"
            author_context = "No survivors remain to tell this tale. Written by a mysterious figure — perhaps a ghost, a passing traveler, or the fortress itself remembering."

    fortress_dir = _get_fortress_dir(config, metadata)

    async def _stream() -> AsyncGenerator[str, None]:
        from df_storyteller.stories.base import create_provider
        from df_storyteller.stories.df_mechanics import DF_MECHANICS_COMPACT
        provider = create_provider(config)

        fortress_name = metadata.get("fortress_name", "the fortress")

        if is_siege:
            system_prompt = f"""You are writing a dramatic siege/battle report.
{author_context}
This was a major engagement with {len(group)} separate fights. Write a sweeping narrative
covering the full battle — the chaos, the individual duels, the turning points.
Reference actual weapons, injuries, and combatants from the data.
Keep it to 200-400 words. Sign off with the author's name at the end.
{DF_MECHANICS_COMPACT}"""
        else:
            system_prompt = f"""You are writing a dramatic battle report.
{author_context}
Write vivid, specific prose based on the actual blow-by-blow combat data provided.
Reference the actual weapons, body parts, injuries, and outcome from the fight.
The tone should be intense and gripping.
Keep it to 150-250 words. Sign off with the author's name at the end.
{DF_MECHANICS_COMPACT}"""

        name_map_text = ""
        if name_mappings:
            name_map_text = "\n## Name Key (the gamelog uses titles, these are the real names)\n" + "\n".join(name_mappings)

        user_prompt = f"""Write a {'siege report' if is_siege else 'battle report'} for {fortress_name}, {season} of Year {year}.

## Combatants
{', '.join(sorted(participants))}
{'This engagement involved ' + str(len(group)) + ' separate fights.' if is_siege else ''}
{name_map_text}

## Combat Details
{combined_raw}

## Result
{_build_outcome_summary(group, title_to_dwarf, ranked)}

IMPORTANT: Use the REAL NAMES from the Name Key above, not titles like "militia commander". Write a dramatic narrative using the actual combat details. Be ACCURATE about who died and who survived — do not invent casualties."""

        try:
            full_text = ""
            async for chunk in provider.stream_generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=config.story.biography_max_tokens,
                temperature=0.85,
            ):
                full_text += chunk
                yield chunk

            # Save the battle report persistently
            try:
                import json as _json
                reports_path = fortress_dir / "battle_reports.json"
                existing = []
                if reports_path.exists():
                    try:
                        existing = _json.loads(reports_path.read_text(encoding="utf-8", errors="replace"))
                    except (ValueError, OSError):
                        existing = []
                from datetime import datetime as _dt
                new_report = {
                    "text": full_text,
                    "author": author_name,
                    "year": year,
                    "season": season,
                    "participants": sorted(participants),
                    "fight_count": len(group),
                    "is_lethal": any_lethal,
                    "is_siege": is_siege,
                    "is_engagement": len(group) > 1,
                    "encounter_index": encounter_index,
                    "generated_at": _dt.now().isoformat(),
                }
                replaced = False
                for i, r in enumerate(existing):
                    if r.get("encounter_index") == encounter_index:
                        existing[i] = new_report
                        replaced = True
                        break
                if not replaced:
                    existing.append(new_report)
                reports_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                logger.warning("Failed to save battle report to disk")
        except Exception as e:
            logger.exception("Battle report generation failed")
            yield f"Error: {e}" if str(e) else "Error: generation failed. Check Settings and try again."

    return StreamingResponse(_stream(), media_type="text/plain")
