"""Shared utilities for story generators."""

from __future__ import annotations

from df_storyteller.config import AppConfig
from df_storyteller.llm.base import LLMProvider
from df_storyteller.llm.claude_provider import ClaudeProvider
from df_storyteller.llm.ollama_provider import OllamaProvider
from df_storyteller.llm.openai_provider import OpenAIProvider


def create_provider(config: AppConfig) -> LLMProvider:
    """Create the LLM provider from config, passing API key from config."""
    api_key = config.llm.api_key

    top_p = config.llm.top_p
    rep_penalty = config.llm.repetition_penalty

    match config.llm.provider:
        case "claude":
            return ClaudeProvider(
                model=config.llm.model or "claude-sonnet-4-20250514",
                api_key=api_key,
                top_p=top_p,
            )
        case "openai":
            return OpenAIProvider(
                model=config.llm.model or "gpt-4o",
                api_key=api_key,
                top_p=top_p,
                frequency_penalty=rep_penalty - 1.0 if rep_penalty > 1.0 else 0.0,
            )
        case "ollama":
            return OllamaProvider(
                model=config.llm.ollama.model,
                base_url=config.llm.ollama.base_url,
                num_ctx=config.llm.ollama.num_ctx,
                top_p=top_p,
                repeat_penalty=rep_penalty,
            )
        case _:
            raise ValueError(f"Unknown LLM provider: {config.llm.provider}")
