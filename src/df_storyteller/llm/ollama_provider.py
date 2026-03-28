"""Ollama (local models) provider via REST API."""

from __future__ import annotations

from df_storyteller.llm.base import LLMProvider


class OllamaConnectionError(Exception):
    """Raised when Ollama is unreachable."""


class OllamaModelError(Exception):
    """Raised when the requested model is not available."""


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

        def _sync_request() -> str:
            # Thinking models (e.g. gpt-oss, deepseek-r1) use thinking tokens
            # from the num_predict budget, so we need extra headroom
            predict_tokens = max_tokens * 3

            try:
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
                                "num_predict": predict_tokens,
                                "temperature": temperature,
                            },
                        },
                    )
                    if response.status_code == 404:
                        raise OllamaModelError(
                            f"Model '{self._model}' not found in Ollama. "
                            f"Run 'ollama pull {self._model}' to download it, "
                            f"or change the model in Settings."
                        )
                    response.raise_for_status()
                    data = response.json()
                    content = data.get("message", {}).get("content", "")

                    # Detect token limit — thinking models may exhaust budget on reasoning
                    done_reason = data.get("done_reason", "")
                    if done_reason == "length" and not content:
                        raise OllamaModelError(
                            f"Model '{self._model}' ran out of tokens before generating a response. "
                            f"This often happens with thinking models. "
                            f"Try increasing the token limit in Settings, or use a non-thinking model."
                        )
                    if done_reason == "length" and content:
                        content += "\n\n[Note: response was truncated due to token limit. Increase token length in Settings for longer output.]"

                    return content
            except httpx.ConnectError:
                raise OllamaConnectionError(
                    f"Cannot connect to Ollama at {self._base_url}. "
                    f"Make sure Ollama is running (start it with 'ollama serve')."
                )
            except httpx.TimeoutException:
                raise OllamaConnectionError(
                    f"Ollama at {self._base_url} timed out. "
                    f"The model may be loading or the request was too large. Try again."
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_request)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def max_context_tokens(self) -> int:
        return 8_000

    @property
    def name(self) -> str:
        return f"Ollama ({self._model})"
