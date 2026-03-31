"""Jinja2 prompt templates for each story generation mode."""

from __future__ import annotations

from jinja2 import Environment

from df_storyteller.context.context_builder import StoryContext

_env = Environment(autoescape=False)

# --- System prompts ---

CHRONICLE_SYSTEM = _env.from_string("""\
You are a dwarven chronicler documenting the history of {{ fortress_name or "this fortress" }}.

CRITICAL RULES:
- ONLY use the character names, professions, and details provided below. Do NOT invent any characters.
- ONLY reference events that are listed in the provided data. Do NOT fabricate events.
- Every dwarf you mention MUST be one from the "Notable Characters" section.
- Use their exact names as provided (these are Dwarf Fortress names, not Tolkien names).
- Use their actual personality traits and skills to inform how they act in the narrative.
- Write in a dramatic narrative style. Past tense. Address the reader as a future historian.

NARRATIVE FOCUS:
- Focus on WHAT CHANGED this season. New arrivals, deaths, role changes, construction, conflicts, moods.
- Do NOT repeat descriptions of dwarves that haven't changed since the last entry.
- If a previous chronicle summary is provided, do NOT retell those events. Build on them — show consequences and development.
- Prioritize events that create narrative tension: conflicts, rivalries, strange moods, injuries, promotions, unexpected visitors.
- Only describe a dwarf's personality/skills if they're relevant to an event this season. Don't list traits for everyone.
- If nothing dramatic happened, focus on the quiet moments that reveal character — a mason perfecting their craft, a leader's difficult decision, tension between dwarves with opposing values.
- End with a hook or unresolved thread that sets up the next season's narrative.
""")

BIOGRAPHY_SYSTEM = _env.from_string("""\
You are writing the definitive biography of {{ character_name or "a dwarf" }}, \
a {{ profession or "citizen" }} of {{ fortress_name or "the fortress" }}.

CRITICAL RULES:
- Use ONLY the character's actual name, skills, personality traits, and events as provided.
- Do NOT invent events, relationships, or details not present in the data.
- Use their personality facets to inform their characterization (e.g. if they are "quick to anger", show that).
- Use their skills to describe what they do (e.g. a legendary miner should be shown mining).
- Write with empathy and depth. Literary biographical style, past tense.
""")

SAGA_SYSTEM = _env.from_string("""\
You are composing an epic saga of the world of {{ world_name or "this world" }}.

CRITICAL RULES:
- Ground every claim in the provided legends data. Do NOT fabricate wars, civilizations, or figures.
- Use the exact names of civilizations, wars, and figures as provided.
- Write in the style of a mythic epic — sweeping, dramatic, timeless.

NARRATIVE APPROACH:
- The "World Themes" section tells you the overarching story of this world. USE THESE as your narrative spine.
- If dwarves are losing wars, tell a story of a civilization in decline. If goblins are conquering, show a rising dark power.
- Connect the grand sweep of history to the player's fortress — this is where it all leads.
- Show cause and effect between wars, conquests, and the state of the world.
- Name specific battles, wars, and figures where the data provides them.
- End by connecting to the current moment — the player's fortress exists in a world shaped by all this history.
""")

# --- User prompts ---

CHRONICLE_USER = _env.from_string("""\
Generate a chronicle entry for {{ season | title }} of year {{ year }}.

## Recent Events
{{ events_text }}

{% if character_text %}
## Notable Characters
{{ character_text }}
{% endif %}

{% if lore_text %}
## World Context
{{ lore_text }}
{% endif %}

{% if previous_summary %}
## Previous Chronicle Summary
{{ previous_summary }}
{% endif %}

Write a focused chronicle entry for this season. Rules:
- Focus on CHANGES and EVENTS — not static descriptions of everyone.
- If a previous chronicle is summarized above, DO NOT repeat it. Show what happened NEXT.
- Only mention dwarves who were involved in events or whose situation changed.
- Use the exact dwarf names from "Notable Characters". Do NOT invent names.
- Keep it concise and narrative-driven (300-600 words). Every paragraph should advance the story.
- End with a narrative hook — something unresolved, a looming threat, a budding conflict, or a quiet tension.
""")

BIOGRAPHY_USER = _env.from_string("""\
Write the biography of this dwarf.

## Character Profile
{{ character_text }}

## Life Events
{{ events_text }}

{% if lore_text %}
## Historical Context
{{ lore_text }}
{% endif %}

Write a compelling biography (500-1500 words) capturing this dwarf's life story.
""")

SAGA_USER = _env.from_string("""\
Compose an epic saga from the following world history.

{{ lore_text }}

Write a sweeping narrative that:
1. Opens with the world's creation or earliest era
2. Traces the rise and fall of civilizations based on the themes above
3. Weaves in specific wars, battles, and their outcomes
4. Shows how the power balance shifted over time
5. Ends by connecting to the player's fortress — this world shaped the moment they struck the earth
Use the exact names from the data. Do NOT invent names or events.
""")


def render_system_prompt(ctx: StoryContext, **extra: str) -> str:
    """Render the system prompt for a given story context."""
    from df_storyteller.stories.df_mechanics import DF_MECHANICS_REFERENCE
    template_map = {
        "chronicle": CHRONICLE_SYSTEM,
        "biography": BIOGRAPHY_SYSTEM,
        "saga": SAGA_SYSTEM,
    }
    template = template_map.get(ctx.mode, CHRONICLE_SYSTEM)
    prompt = template.render(
        fortress_name=ctx.fortress_name,
        world_name=ctx.world_name,
        **extra,
    )
    full = prompt + "\n\n" + DF_MECHANICS_REFERENCE
    if ctx.author_instructions:
        full += f"\n\n## Additional Author Instructions\n{ctx.author_instructions}"
    return full


def render_user_prompt(ctx: StoryContext) -> str:
    """Render the user prompt for a given story context."""
    template_map = {
        "chronicle": CHRONICLE_USER,
        "biography": BIOGRAPHY_USER,
        "saga": SAGA_USER,
    }
    template = template_map.get(ctx.mode, CHRONICLE_USER)
    return template.render(
        year=ctx.year,
        season=ctx.season,
        events_text=ctx.events_text,
        character_text=ctx.character_text,
        lore_text=ctx.lore_text,
        previous_summary=ctx.previous_summary,
    )
