"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMProvider(ABC):
    """Interface that all LLM backends must implement."""

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.8,
    ) -> str:
        """Generate a text completion."""
        ...

    @abstractmethod
    async def stream_generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        """Yield text chunks as they arrive from the model."""
        ...
        yield ""  # pragma: no cover — makes this a valid generator

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in a text string."""
        ...

    @property
    @abstractmethod
    def max_context_tokens(self) -> int:
        """Maximum context window size for this provider/model."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...
