"""OpenAI API provider."""

from __future__ import annotations

import os

from df_storyteller.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):

    def __init__(self, model: str = "gpt-4o", api_key: str = "") -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "No OpenAI API key found. Run 'python -m df_storyteller init' to configure, "
                "or set the OPENAI_API_KEY environment variable."
            )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.8,
    ) -> str:
        from openai import AsyncOpenAI, AuthenticationError, APIConnectionError, RateLimitError

        try:
            client = AsyncOpenAI(api_key=self._api_key)
            response = await client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            if not response.choices:
                return "[OpenAI returned an empty response. Try again or check your prompt.]"
            return response.choices[0].message.content or ""
        except AuthenticationError:
            raise ValueError(
                "Invalid OpenAI API key. Check your key in Settings or run 'python -m df_storyteller init'."
            )
        except RateLimitError:
            raise ValueError(
                "OpenAI rate limit reached. Wait a moment and try again."
            )
        except APIConnectionError:
            raise ValueError(
                "Cannot connect to the OpenAI API. Check your internet connection."
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "context_length" in err_msg or "max_tokens" in err_msg or "too many tokens" in err_msg:
                raise ValueError(
                    "Prompt too large for this OpenAI model's context window. "
                    "Try reducing token limits in Settings, or generate shorter content."
                )
            raise

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def max_context_tokens(self) -> int:
        return 128_000

    @property
    def name(self) -> str:
        return f"OpenAI ({self._model})"
