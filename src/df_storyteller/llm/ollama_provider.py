"""Ollama (local models) provider via REST API."""

from __future__ import annotations

from df_storyteller.llm.base import LLMProvider


class OllamaProvider(LLMProvider):

    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434") -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.8,
    ) -> str:
        import asyncio
        import httpx

        # Use sync httpx in a thread — async httpx has compatibility issues
        # with some Ollama versions (connection drops)
        def _sync_request() -> str:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data.get("message", {}).get("content", "")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_request)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def max_context_tokens(self) -> int:
        return 8_000  # Conservative default for local models

    @property
    def name(self) -> str:
        return f"Ollama ({self._model})"
