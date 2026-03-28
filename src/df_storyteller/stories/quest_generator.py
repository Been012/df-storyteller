"""AI quest generation based on actual fortress state.

Generates quests that are achievable in Dwarf Fortress by examining the
current fortress data (citizens, buildings, events, religion, military)
and asking the LLM to create contextual challenges.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.context.loader import load_game_state
from df_storyteller.context.narrative_formatter import format_fortress_context, format_dwarf_narrative
from df_storyteller.schema.quests import Quest, QuestCategory, QuestDifficulty
from df_storyteller.stories.base import create_provider


QUEST_SYSTEM_PROMPT = """You are a quest designer and narrative director for Dwarf Fortress, the legendary simulation game by Bay 12 Games.
You generate quests that DRIVE THE STORY of the fortress forward — not just task lists, but narrative hooks that give the player a reason to care about what happens next.

CRITICAL RULES:
- Quests must be NARRATIVE-DRIVEN — they should create drama, tension, ambition, or purpose. Frame them as story goals, not chores. "Build a well" is a chore. "Secure fresh water before winter claims the weak" is a story.
- Every quest MUST be something the player can DIRECTLY CONTROL in vanilla Dwarf Fortress. If the game decides it (strange moods, migrant arrivals, who falls in love), the player CANNOT make it happen — do NOT suggest it.
- Use the actual names of dwarves, deities, civilizations, and places from the provided data.
- Quests should emerge from THIS fortress's current situation — its people, its conflicts, its vulnerabilities.
- Do NOT suggest quests that require modding, DFHack commands, or external tools.
- Always include a difficulty rating based on the DWARF FORTRESS MECHANICS REFERENCE below.
- Check the fortress state against mechanics (e.g. don't suggest siege survival for <80 population).

THINGS THE PLAYER CANNOT CONTROL (never make these quest objectives):
- Strange moods (random, game-triggered — player can only provide materials)
- Who migrates to the fortress (random)
- Who falls in love / marries (dwarves decide on their own)
- Weather, seasons, or time passing
- Which forgotten beast appears or what abilities it has
- Whether a vampire or werebeast arrives (random migrant event)
- Artifact properties (determined by the moody dwarf's preferences)
- Caravan timing or what traders bring

THINGS THE PLAYER CAN CONTROL (good quest objectives):
- What to build, where to build it, and how to furnish it
- Military organization: forming squads, assigning equipment, setting patrol routes
- Who gets assigned to what labor or profession
- Digging, mining, and exploration directions
- Temple/tavern/library designation and furnishing
- Trade decisions (what to sell, what to buy)
- Defensive preparations (traps, bridges, walls, fortifications)
- Which areas to seal off or open up
- Noble appointments and positions
- How to respond to threats (fight, trap, lock down)

QUEST NARRATIVE FRAMING:
- Frame quests around CHARACTER ARCS: "Kogan has grown restless in his role as peasant — assign him to a squad and forge him a weapon worthy of his ambition"
- Frame quests around THREATS: "The goblin wars rage on — fortify the entrance before the next assault"
- Frame quests around FAITH: "Osram the Aquamarine has 17 worshippers but no proper temple — build a shrine worthy of the deity of death"
- Frame quests around LEGACY: "No dwarf in this fortress has achieved legendary status — dedicate a workshop to mastering a craft"
- Frame quests around RELATIONSHIPS: "Two rival dwarves share a grudge — separate their workspaces before it escalates"
- Frame quests around SURVIVAL: "Winter approaches with no reliable water source — dig a cistern before the brooks freeze"
- Frame quests around AMBITION: "This fortress has no monument to its existence — construct a tower visible from the surface, clad in the finest stone, so all who pass know dwarves dwell here"
- Frame quests around MEMORIAL: "Three dwarves fell to the giant groundhog — build a memorial hall with engraved walls depicting their sacrifice"
- Frame quests around GRANDEUR: "The dining hall is a dirt-floored pit — transform it into a great hall with smoothed walls, masterwork tables, and a statue of your civilization's founder"
- Frame quests around CULTURE: "Your fortress has no identity yet — design a grand entrance with fortifications, a bridge, and carved walls that tell visitors who you are"

DIFFICULTY TIERS:
- easy: Any fortress can do this immediately with basic knowledge. Minimal risk. Examples: designate a meeting hall, assign labors, brew drinks, build basic furniture, smooth stone walls, create a stockpile.
- medium: Requires some fortress development, resources, or planning. Examples: train a military squad, build a temple worth 2000+, create a well system, establish a tavern, forge bronze/iron weapons.
- hard: Requires significant progression, rare resources, or surviving dangerous situations. Examples: survive a siege (needs 80+ pop), forge steel (needs flux + iron + fuel chain), trigger a strange mood, defeat a forgotten beast, build a magma forge (needs magma access).
- legendary: Endgame goals, extreme risk, or requires rare game events. Examples: breach the HFS (adamantine mining), capture a werebeast alive, build an adamantine forge, attract a king, create a 10000+ value temple complex, defeat a titan.

DWARF FORTRESS MECHANICS REFERENCE (use this to ensure quests are achievable):

MILITARY:
- Squads are created via the military screen (m key). Needs a barracks (designate from a room with beds/weapon racks).
- Training requires a barracks with training enabled. Dwarves spar to gain skill.
- Sieges only happen at 80+ population. Goblins send squads of ~20-120 soldiers.
- Forgotten beasts spawn in cavern layers. They have unique abilities (fire, webs, dust).
- A danger room uses upright weapon traps with training spears for fast military training.
- Steel requires: iron ore + flux stone (limestone/marble) + fuel (charcoal/coke). It's a multi-step process.

CONSTRUCTION:
- Dwarves can build ANYTHING tile-by-tile, like Minecraft. Walls, floors, ramps, stairs, fortifications, windows (glass), pillars, and more. Materials include stone blocks, wood, glass, metal bars, and bricks.
- MEGASTRUCTURES are a core part of DF. Players build pyramids, castles, towers, colosseums, underground cathedrals, above-ground cities, aqueducts, lighthouses, statues, monuments, defensive walls spanning the map, multi-story keeps, throne rooms, crypts, and mausoleums.
- Construction quests should be CREATIVE and THEMATIC — not just "build a workshop". Examples: "Erect a tower of obsidian above the fortress entrance as a monument to the fallen", "Build a grand mausoleum with engraved walls telling the history of every dwarf who died", "Construct a glass-roofed atrium so dwarves can see the sky underground".
- Temples are created by designating a zone as a temple and assigning a deity. Value thresholds: <2000 = Shrine, 2000+ = Temple (needs 10+ worshippers for petition), 10000+ = Temple Complex.
- Value comes from smoothed walls, engraved walls, placed furniture (especially high-quality or artifact), and flooring.
- Magma forges require building next to magma (z-level with magma flow of 4/7+). Usually found deep underground near the magma sea.
- Wells require a bucket, rope/chain, and a constructed well over a water source (cistern or aquifer).
- Bridges are built from the build menu. They can be linked to levers for drawbridge functionality.
- Players can channel, dig, and reshape terrain freely — carving rivers, creating artificial lakes, building islands, hollowing out mountains.
- Above-ground construction uses built walls/floors placed on ramps or scaffolding. Multi-story towers are common.
- Engraving walls creates art depicting fortress history — specific events, dwarves, and artifacts from the game's generated history.

RELIGIOUS:
- Each dwarf worships deities based on their civilization's pantheon.
- Temples need a zone designated as "temple" and a deity/religion assigned.
- Priests are appointed when a temple reaches sufficient value and has enough worshippers.
- Libraries need a zone with bookshelves and writing materials. Scholars will write books.
- Musical instruments can be built at a craftsdwarf workshop for temple ceremonies.

CRAFTING:
- Strange moods happen randomly to eligible dwarves (must have a skill, no mood cooldown). The dwarf claims a workshop and demands specific materials. If materials are available, they create a named artifact. If not, they go insane.
- Artifacts are always masterwork quality x3 value. They can be weapons, armor, furniture, or crafts.
- Legendary skill (level 20) is achieved through extensive practice. Legendary craftsdwarves make masterwork items regularly.
- Trade goods are sold to caravans that arrive seasonally (dwarven in autumn, elven in spring, human in summer).

EXPLORATION:
- Cavern layers are reached by mining downward. There are typically 3 layers, each with unique flora/fauna.
- The magma sea is at the deepest level, below all cavern layers.
- Adamantine is found as veins in the rock above the magma sea. Mining it risks breaching the HFS (Hell / Hidden Fun Stuff).
- Forgotten beasts can emerge from cavern breaches. They are procedurally generated megabeasts.

SOCIAL:
- Population grows through migration waves (up to 2 per year, usually spring and autumn).
- Mayor is elected at 50+ population. Barons/counts/dukes require meeting wealth/population/export thresholds.
- Taverns attract visitors (performers, mercenaries) when designated with a tavern keeper and furnished with tables/chairs.
- Guilds form when enough dwarves practice a craft. Guild halls need a designated zone.
- Dwarves marry on their own if they have positive relationships. You can encourage it with shared dining/meeting areas.

CHAOS:
- Vampires arrive disguised as migrants. They don't eat/drink/sleep and drain blood from sleeping dwarves.
- Werebeasts attack during full moons and can infect dwarves through wounds. They revert to humanoid form after.
- Tantrum spirals occur when many dwarves become unhappy simultaneously (deaths, lack of needs).
- Atom-smashing uses a raising bridge to destroy anything on it (including enemies, items, even artifacts).
- The "circus" (HFS) is breached by mining through the bottom of adamantine tubes. Extremely dangerous.

RESPONSE FORMAT:
Return ONLY a JSON array. No explanation, no markdown fences, no preamble. Each object:
[
  {
    "title": "short quest title (3-8 words)",
    "description": "2-3 sentences describing what the player should do and why it matters narratively",
    "category": "military|construction|religious|crafting|exploration|social|chaos",
    "difficulty": "easy|medium|hard|legendary",
    "hints": ["specific game mechanic hint 1", "specific hint 2"],
    "related_unit_names": ["Dwarf Name"]
  }
]"""


def _build_fortress_context(metadata: dict, character_tracker, event_store, world_lore) -> str:
    """Build a concise fortress context string for the quest generation prompt."""
    parts = [format_fortress_context(metadata)]

    # Top citizens
    ranked = character_tracker.ranked_characters()[:10]
    if ranked:
        citizen_lines = []
        for dwarf, score in ranked:
            line = f"- {dwarf.name}: {dwarf.profession}"
            if dwarf.noble_positions:
                line += f" ({', '.join(dwarf.noble_positions)})"
            if dwarf.military_squad:
                line += f" [squad: {dwarf.military_squad}]"
            top_skills = sorted(dwarf.skills, key=lambda s: s.experience, reverse=True)[:3]
            if top_skills:
                line += f" skills: {', '.join(s.name for s in top_skills)}"
            # Deity worship
            deity_rels = [r for r in dwarf.relationships if r.relationship_type == "deity"]
            if deity_rels:
                line += f" worships: {', '.join(r.target_name for r in deity_rels[:2])}"
            citizen_lines.append(line)
        parts.append("## Notable Citizens\n" + "\n".join(citizen_lines))

    # Recent events
    from df_storyteller.context.context_builder import _format_event
    recent = event_store.recent_events(20)
    if recent:
        event_lines = [_format_event(e) for e in reversed(recent[-20:])]
        parts.append("## Recent Events\n" + "\n".join(event_lines))

    # Deity/religion data from legends
    if world_lore.is_loaded and world_lore._legends:
        legends = world_lore._legends
        # Find deities worshipped by fortress citizens
        deity_names = set()
        for dwarf, _ in ranked:
            for rel in dwarf.relationships:
                if rel.relationship_type == "deity":
                    deity_names.add(rel.target_name)
        if deity_names:
            deity_info = []
            for dn in list(deity_names)[:8]:
                # Try to find spheres
                first_word = dn.split()[0].lower()
                for hf in legends.historical_figures.values():
                    if hf.is_deity and hf.name.split()[0].lower() == first_word and hf.spheres:
                        deity_info.append(f"- {dn}: spheres of {', '.join(hf.spheres)}")
                        break
                else:
                    deity_info.append(f"- {dn}")
            parts.append("## Deities Worshipped\n" + "\n".join(deity_info))

        # Active wars
        civ_id = metadata.get("fortress_info", {}).get("civ_id")
        if civ_id:
            wars = legends.get_wars_involving(civ_id)
            if wars:
                war_names = [w.get("name", "Unknown") for w in wars[:3]]
                parts.append(f"## Active Wars\nYour civilization is involved in: {', '.join(war_names)}")

    return "\n\n".join(parts)


async def generate_quests(
    config: AppConfig,
    count: int = 3,
    category: str = "",
    difficulty: str = "",
    output_dir: Path | None = None,
) -> list[Quest]:
    """Generate AI quests based on current fortress state."""
    provider = create_provider(config)

    active_world = ""
    event_store, character_tracker, world_lore, metadata = load_game_state(
        config, skip_legends=False, active_world=active_world,
    )

    fortress_context = _build_fortress_context(metadata, character_tracker, event_store, world_lore)

    # Load all quests (active + completed + abandoned) to avoid duplicates
    from df_storyteller.context.quest_store import load_all_quests
    all_quests = load_all_quests(config, output_dir)
    dedup_parts = []
    active_titles = [q.title for q in all_quests if q.status.value == "active"]
    completed_titles = [q.title for q in all_quests if q.status.value == "completed"]
    if active_titles:
        dedup_parts.append("## Active Quests (DO NOT duplicate)\n" + "\n".join(f"- {t}" for t in active_titles))
    if completed_titles:
        dedup_parts.append("## Already Completed Quests (DO NOT repeat — the fortress has already achieved these)\n" + "\n".join(f"- {t}" for t in completed_titles))
    dedup_section = "\n" + "\n\n".join(dedup_parts) if dedup_parts else ""

    category_instruction = ""
    if category:
        category_instruction += f"\nIMPORTANT: ALL quests MUST be in the '{category}' category."
    if difficulty:
        category_instruction += f"\nIMPORTANT: ALL quests MUST be '{difficulty}' difficulty."
    if category_instruction:
        category_instruction += "\n"

    user_prompt = f"""Generate {count} quests for this fortress.
{category_instruction}
{fortress_context}
{dedup_section}

Generate {count} {("'" + category + "' category " if category else "")}{("'" + difficulty + "' difficulty " if difficulty else "")}{"diverse " if not category and not difficulty else ""}achievable quests that emerge naturally from the current fortress state.
Return ONLY a JSON array, no other text."""

    try:
        response = await provider.generate(
            system_prompt=QUEST_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=config.story.quest_generation_max_tokens,
            temperature=0.9,
        )
    except Exception as e:
        raise RuntimeError(f"Quest generation failed: {e}") from e

    # Parse JSON response — handle markdown fences and preamble
    text = response.strip()
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Try to extract JSON array
    try:
        quest_data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: find first [...] block
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                quest_data = json.loads(match.group())
            except json.JSONDecodeError:
                return []
        else:
            return []

    if not isinstance(quest_data, list):
        return []

    # Build context snapshot for completion narratives later
    context_snapshot = fortress_context[:1000]  # Cap at 1000 chars

    year = metadata.get("year", 0)
    season = metadata.get("season", "")

    quests = []
    from df_storyteller.context.quest_store import add_quest
    for qd in quest_data:
        if not isinstance(qd, dict) or "title" not in qd:
            continue
        try:
            quest_category = QuestCategory(qd.get("category", "military"))
        except ValueError:
            quest_category = QuestCategory.MILITARY

        try:
            difficulty = QuestDifficulty(qd.get("difficulty", "medium"))
        except ValueError:
            difficulty = QuestDifficulty.MEDIUM

        quest = Quest(
            title=qd["title"],
            description=qd.get("description", ""),
            category=quest_category,
            difficulty=difficulty,
            hints=qd.get("hints", []),
            related_unit_names=qd.get("related_unit_names", []),
            game_year=year,
            game_season=season,
            context_snapshot=context_snapshot,
        )
        add_quest(config, quest, output_dir)
        quests.append(quest)

    return quests


async def generate_completion_narrative(
    config: AppConfig,
    quest: Quest,
    output_dir: Path | None = None,
) -> str:
    """Generate a narrative describing how a quest was fulfilled."""
    provider = create_provider(config)
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    current_context = _build_fortress_context(metadata, character_tracker, event_store, world_lore)

    system_prompt = """You are a dwarven chronicler recording the completion of a great quest.
Write a brief narrative (150-250 words) describing how this quest was fulfilled.
Use actual dwarf names and fortress details. The tone should be triumphant and
celebratory, befitting a dwarven achievement."""

    user_prompt = f"""## The Quest
Title: {quest.title}
Description: {quest.description}
Category: {quest.category.value}
Difficulty: {quest.difficulty.value}
Issued: {quest.game_season.title()} of Year {quest.game_year}

## Fortress When Quest Was Issued
{quest.context_snapshot}

## Fortress Now
{current_context}

Write a narrative of how the fortress completed this quest. Focus on what changed
between the fortress state when the quest was issued and now."""

    try:
        return await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.quest_narrative_max_tokens,
            temperature=config.llm.temperature,
        )
    except Exception as e:
        return f"[Completion narrative generation failed: {e}]"
