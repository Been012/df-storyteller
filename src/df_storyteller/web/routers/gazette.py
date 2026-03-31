"""Gazette routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from df_storyteller.config import AppConfig
from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
    base_context as _base_context,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _pick_gazette_author(character_tracker) -> tuple[str, str]:
    """Pick the best author for the gazette from fortress citizens.

    Priority: highest writing/poetry/prose skill, then social skills, then any dwarf.
    Returns (author_name, author_profession).
    """
    ranked = character_tracker.ranked_characters()
    writing_keywords = {"writing", "prose", "poetry", "record keeping"}
    social_keywords = {"persuasion", "conversation", "social awareness", "flattery"}

    best = None
    best_score = -1

    for dwarf, _ in ranked:
        if not dwarf.is_alive:
            continue
        for skill in dwarf.skills:
            name_lower = skill.name.lower()
            if name_lower in writing_keywords:
                score = skill.experience + 1000  # Writing skills preferred
            elif name_lower in social_keywords:
                score = skill.experience + 500
            else:
                continue
            if score > best_score:
                best_score = score
                best = dwarf

    if best:
        return best.name.split(",")[0].strip(), best.profession

    # Fallback: any living dwarf
    for dwarf, _ in ranked:
        if dwarf.is_alive:
            return dwarf.name.split(",")[0].strip(), dwarf.profession

    return "An Anonymous Scribe", ""


def _gazette_section_length(config: AppConfig) -> str:
    """Calculate target word count per gazette section based on token budget."""
    tokens = config.story.gazette_max_tokens
    # ~5 sections, ~0.75 words per token
    words_per_section = int((tokens * 0.75) / 5)
    if words_per_section < 80:
        return "50-80"
    elif words_per_section < 150:
        return "80-150"
    elif words_per_section < 300:
        return "150-300"
    else:
        return "300-500"


@router.get("/gazette", response_class=HTMLResponse)
async def gazette_page(request: Request):
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "gazette", metadata)
    fortress_dir = _get_fortress_dir(config, metadata)

    # Load gazette data
    gazette = None
    past_gazettes = []
    try:
        import json as _json
        gazette_path = fortress_dir / "gazette.json"
        if gazette_path.exists():
            all_gazettes = _json.loads(gazette_path.read_text(encoding="utf-8", errors="replace"))
            current_year = metadata.get("year", 0)
            current_season = metadata.get("season", "")
            for g in all_gazettes:
                if g.get("year") == current_year and g.get("season") == current_season:
                    gazette = g
                else:
                    past_gazettes.append(g)
    except (ValueError, OSError):
        pass

    # Sort past gazettes newest first
    past_gazettes.sort(key=lambda g: (g.get("year", 0), {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}.get(g.get("season", ""), 0)), reverse=True)

    return templates.TemplateResponse(request=request, name="gazette.html", context={
        **ctx, "gazette": gazette, "past_gazettes": past_gazettes,
    })


@router.post("/api/gazette/generate")
async def api_generate_gazette():
    """Generate a fortress gazette — dwarven newspaper with multiple sections."""
    config = _get_config()
    event_store, character_tracker, world_lore, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)

    author_name, author_prof = _pick_gazette_author(character_tracker)
    fortress_name = metadata.get("fortress_name", "the fortress")
    year = metadata.get("year", 0)
    season = metadata.get("season", "")
    population = metadata.get("population", 0)

    # Gather context for each section
    from df_storyteller.context.context_builder import _format_event
    from df_storyteller.context.narrative_formatter import format_fortress_context

    # Herald: fortress events summary
    recent_events = event_store.recent_events(30)
    event_lines = [_format_event(e) for e in reversed(recent_events[-30:])]
    fortress_context = format_fortress_context(metadata)

    # Military: combat encounters
    from df_storyteller.schema.events import EventType as ET
    combat_text = ""
    combat_events = [e for e in recent_events if e.event_type == ET.COMBAT]
    if combat_events:
        combat_lines = []
        for e in combat_events:
            d = e.data
            atk = d.attacker.name if hasattr(d, "attacker") else "?"
            defn = d.defender.name if hasattr(d, "defender") else "?"
            outcome = getattr(d, "outcome", "")
            lethal = " [FATAL]" if getattr(d, "is_lethal", False) else ""
            combat_lines.append(f"- {atk} vs {defn}: {outcome}{lethal}")
        combat_text = "\n".join(combat_lines)

    # Gossip: chat events from DFHack onReport hook
    from df_storyteller.schema.events import EventType as _ChatET
    chat_lines_raw = []
    for event in event_store.events_by_type(_ChatET.CHAT):
        d = event.data
        if isinstance(d, dict):
            unit = d.get("unit", {})
            name = unit.get("name", "Unknown") if isinstance(unit, dict) else "Unknown"
            msg = d.get("message", "")
            if msg:
                chat_lines_raw.append(f"{name}: {msg}")
    chat_text = "\n".join(chat_lines_raw[:50])

    # Quests
    from df_storyteller.context.quest_store import get_active_quests, get_completed_quests
    active_quests = get_active_quests(config, fortress_dir)
    completed_quests = get_completed_quests(config, fortress_dir)
    quest_lines = []
    for q in completed_quests[-3:]:
        quest_lines.append(f"- COMPLETED: {q.title} — {q.description}")
    for q in active_quests[:5]:
        quest_lines.append(f"- ONGOING: {q.title} — {q.description}")
    quest_text = "\n".join(quest_lines)

    # Deaths this season
    death_events = [e for e in recent_events if e.event_type == ET.DEATH]
    death_lines = []
    for e in death_events:
        d = e.data
        if hasattr(d, "victim"):
            death_lines.append(f"- {d.victim.name} ({getattr(d, 'cause', 'unknown')})")
    death_text = "\n".join(death_lines)

    # Author personality for voice
    author_dwarf = None
    for dwarf, _ in character_tracker.ranked_characters():
        short = dwarf.name.split(",")[0].strip()
        if short == author_name:
            author_dwarf = dwarf
            break

    personality_text = ""
    if author_dwarf and author_dwarf.personality:
        traits = [f.description for f in author_dwarf.personality.facets if f.is_notable and f.description]
        if traits:
            personality_text = f"Author personality: {'; '.join(traits[:5])}"

    # Generate all sections with one LLM call
    from df_storyteller.stories.base import create_provider
    from df_storyteller.stories.df_mechanics import DF_MECHANICS_COMPACT
    provider = create_provider(config)

    system_prompt = f"""You are {author_name}, a {author_prof or 'dwarf'} at {fortress_name}, writing this season's edition of the fortress gazette — a dwarven newspaper.
{personality_text}

Write in character as {author_name}. Your personality should color the writing — if you're grumpy, be sarcastic. If cheerful, be enthusiastic. If scholarly, be precise.

You must write EXACTLY these sections, each preceded by its header on its own line:

HERALD:
(2-3 paragraphs summarizing what happened at the fortress this season. Major events, changes, arrivals.)

MILITARY:
(1-2 paragraphs about combat, defense, military readiness. Skip if no combat occurred — write "All quiet on the ramparts." instead.)

GOSSIP:
(1-2 paragraphs of social gossip — who's talking to who, new friendships, complaints, drama. Written as rumor and hearsay.)

QUESTS:
(1-2 paragraphs about quest progress — what the fortress is working toward, what was achieved.)

OBITUARIES:
(Brief memorial for any who died this season. Skip if no deaths — write "No lives were lost this season, praise the gods." instead.)

Target length per section: {_gazette_section_length(config)} words. Write as a dwarven newspaper — witty, opinionated, in-character.
{DF_MECHANICS_COMPACT}"""

    user_prompt = f"""Write the gazette for {fortress_name}, {season.title()} of Year {year}. Population: {population}.

## Fortress State
{fortress_context}

## Recent Events
{chr(10).join(event_lines[-15:])}

## Combat This Season
{combat_text or 'No combat occurred.'}

## Social Chatter
{chat_text or 'The fortress was quiet — no notable conversations.'}

## Quest Activity
{quest_text or 'No active quests.'}

## Deaths This Season
{death_text or 'No deaths.'}

Write the full gazette now with all 5 section headers (HERALD:, MILITARY:, GOSSIP:, QUESTS:, OBITUARIES:)."""

    try:
        result = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.gazette_max_tokens,
            temperature=0.9,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Parse sections from the response
    sections = {"herald": "", "military": "", "gossip": "", "quests": "", "obituaries": ""}
    current_section = None
    current_lines: list[str] = []

    for line in result.split("\n"):
        # Strip markdown bold (**), heading markers (#), dashes, and colons
        line_upper = line.strip().strip("*#-").strip().upper().rstrip(":")
        if line_upper in ("HERALD", "THE FORTRESS HERALD"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "herald"
            current_lines = []
        elif line_upper in ("MILITARY", "MILITARY DISPATCHES"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "military"
            current_lines = []
        elif line_upper in ("GOSSIP", "QUARRY GOSSIP"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "gossip"
            current_lines = []
        elif line_upper in ("QUESTS", "QUEST BOARD"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "quests"
            current_lines = []
        elif line_upper in ("OBITUARIES", "OBITUARY"):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = "obituaries"
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    # If parsing failed (no sections found), put everything in herald
    if not any(sections.values()):
        sections["herald"] = result.strip()

    # Save gazette
    try:
        import json as _json
        from datetime import datetime as _dt
        gazette_path = fortress_dir / "gazette.json"
        existing = []
        if gazette_path.exists():
            try:
                existing = _json.loads(gazette_path.read_text(encoding="utf-8", errors="replace"))
            except (ValueError, OSError):
                existing = []
        # Replace existing for same season/year
        gazette_entry = {
            "year": year,
            "season": season,
            "author": author_name,
            "author_profession": author_prof,
            "sections": sections,
            "generated_at": _dt.now().isoformat(),
        }
        replaced = False
        for i, g in enumerate(existing):
            if g.get("year") == year and g.get("season") == season:
                existing[i] = gazette_entry
                replaced = True
                break
        if not replaced:
            existing.append(gazette_entry)
        gazette_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("Failed to save gazette to disk")

    return {"ok": True}


@router.post("/api/gazette/manual")
async def api_gazette_manual(request: Request):
    """Save a player-written gazette."""
    import json as _json
    config = _get_config()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    gazette_path = fortress_dir / "gazette.json"

    season = metadata.get("season", "spring")
    year = metadata.get("year", 0)

    gazette = {
        "season": season,
        "year": year,
        "author": "The Player",
        "sections": {
            "herald": data.get("herald", ""),
            "military": data.get("military", ""),
            "gossip": data.get("gossip", ""),
            "quests": data.get("quests", ""),
            "obituaries": data.get("obituaries", ""),
        },
        "is_manual": True,
    }

    # Load existing gazettes and append/replace for this season
    existing = []
    if gazette_path.exists():
        try:
            existing = _json.loads(gazette_path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            pass

    # Replace gazette for same season/year if exists
    existing = [g for g in existing if not (g.get("season") == season and g.get("year") == year)]
    existing.append(gazette)
    gazette_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}
