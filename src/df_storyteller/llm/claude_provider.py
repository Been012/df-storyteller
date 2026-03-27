"""Anthropic Claude API provider.

Uses the official anthropic SDK.
Ref: https://docs.anthropic.com/en/docs
"""

from __future__ import annotations

import os

from df_storyteller.llm.base import LLMProvider


class ClaudeProvider(LLMProvider):

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str = "") -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "No Anthropic API key found. Run 'python -m df_storyteller init' to configure, "
                "or set the ANTHROPIC_API_KEY environment variable."
            )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.8,
    ) -> str:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        message = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not message.content:
            return "[Error: Claude returned an empty response. Try again or check your prompt.]"
        return message.content[0].text

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def max_context_tokens(self) -> int:
        if "opus" in self._model:
            return 200_000
        return 200_000  # Most Claude models support 200k

    @property
    def name(self) -> str:
        return f"Claude ({self._model})"
