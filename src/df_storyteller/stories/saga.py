"""Epic Saga / World History story generator."""

from __future__ import annotations

from df_storyteller.config import AppConfig
from df_storyteller.context.context_builder import ContextBuilder
from df_storyteller.context.loader import load_game_state
from df_storyteller.llm.prompt_templates import render_system_prompt, render_user_prompt
from df_storyteller.stories.base import create_provider


async def generate_saga(
    config: AppConfig,
    scope: str = "full",
) -> str:
    """Generate an epic world history saga from legends data."""
    provider = create_provider(config)
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    if not world_lore.is_loaded:
        return "No legends data available. Export legends from Dwarf Fortress first (use 'open-legends' in DFHack), then restart the server."

    builder = ContextBuilder(
        event_store=event_store,
        character_tracker=character_tracker,
        world_lore=world_lore,
        max_context_tokens=provider.max_context_tokens // 2,
    )

    ctx = builder.build_saga_context(
        scope=scope,
        world_name=metadata.get("fortress_name", ""),
    )

    if not ctx.lore_text.strip() or ctx.lore_text == "No legends data loaded.":
        return "No legends data available for saga generation."

    system_prompt = render_system_prompt(ctx)
    user_prompt = render_user_prompt(ctx)

    try:
        return await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.story.saga_max_tokens,
            temperature=config.llm.temperature,
        )
    except Exception as e:
        return f"[Saga generation failed: {e}. Check your LLM provider settings and try again.]"
