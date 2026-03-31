"""Epic Saga / World History story generator."""

from __future__ import annotations

import json as _json
import logging
from collections.abc import Callable
from datetime import datetime as _dt
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.context.context_builder import ContextBuilder
from df_storyteller.context.loader import load_game_state
from df_storyteller.llm.prompt_templates import render_system_prompt, render_user_prompt
from df_storyteller.stories.base import create_provider

logger = logging.getLogger(__name__)


async def prepare_saga(
    config: AppConfig,
    scope: str = "full",
    output_dir: Path | None = None,
) -> tuple[str, str, int, float, Callable[[str], None]] | str:
    """Prepare prompts for saga generation.

    Returns (system_prompt, user_prompt, max_tokens, temperature, save_fn)
    or an error string if legends data is not available.
    """
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

    ctx.author_instructions = config.story.author_instructions
    system_prompt = render_system_prompt(ctx)
    user_prompt = render_user_prompt(ctx)

    # Capture metadata for save callback
    _year = metadata.get("year", 0)
    _season = metadata.get("season", "")

    def save(text: str) -> None:
        try:
            from df_storyteller.web.state import get_fortress_dir as _get_fortress_dir
            saga_dir = output_dir or _get_fortress_dir(config, metadata)
            saga_path = saga_dir / "saga.json"
            existing: list[dict] = []
            if saga_path.exists():
                try:
                    existing = _json.loads(saga_path.read_text(encoding="utf-8", errors="replace"))
                except (ValueError, OSError):
                    existing = []
            existing.append({
                "text": text,
                "year": _year,
                "season": _season,
                "generated_at": _dt.now().isoformat(),
            })
            saga_path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.warning("Failed to save saga to disk")

    return system_prompt, user_prompt, config.story.saga_max_tokens, config.llm.temperature, save


async def generate_saga(
    config: AppConfig,
    scope: str = "full",
    output_dir: Path | None = None,
) -> str:
    """Generate an epic world history saga from legends data."""
    result = await prepare_saga(config, scope, output_dir)
    if isinstance(result, str):
        return result

    system_prompt, user_prompt, max_tokens, temperature, save = result
    provider = create_provider(config)

    try:
        saga_text = await provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        return f"[Saga generation failed: {e}. Check your LLM provider settings and try again.]"

    save(saga_text)
    return saga_text
