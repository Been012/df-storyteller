"""Ollama (local models) provider via REST API."""

from __future__ import annotations

from typing import AsyncGenerator

from df_storyteller.llm.base import LLMProvider


class OllamaConnectionError(Exception):
    """Raised when Ollama is unreachable."""


class OllamaModelError(Exception):
    """Raised when the requested model is not available."""


class OllamaProvider(LLMProvider):

    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434", num_ctx: int = 32768, top_p: float = 1.0, repeat_penalty: float = 1.0) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._num_ctx = num_ctx
        self._top_p = top_p
        self._repeat_penalty = repeat_penalty

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
                                "num_ctx": self._num_ctx,
                                "temperature": temperature,
                                "top_p": self._top_p,
                                "repeat_penalty": self._repeat_penalty,
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

    async def stream_generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        import asyncio
        import json
        import httpx
        import queue

        predict_tokens = max_tokens * 3
        chunk_queue: queue.Queue[str | None] = queue.Queue()
        error_holder: list[Exception] = []

        def _sync_stream() -> None:
            try:
                with httpx.Client(timeout=300.0) as client:
                    with client.stream(
                        "POST",
                        f"{self._base_url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "stream": True,
                            "options": {
                                "num_predict": predict_tokens,
                                "num_ctx": self._num_ctx,
                                "temperature": temperature,
                                "top_p": self._top_p,
                                "repeat_penalty": self._repeat_penalty,
                            },
                        },
                    ) as response:
                        if response.status_code == 404:
                            raise OllamaModelError(
                                f"Model '{self._model}' not found in Ollama. "
                                f"Run 'ollama pull {self._model}' to download it, "
                                f"or change the model in Settings."
                            )
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if not line:
                                continue
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                chunk_queue.put(content)
            except httpx.ConnectError:
                error_holder.append(OllamaConnectionError(
                    f"Cannot connect to Ollama at {self._base_url}. "
                    f"Make sure Ollama is running (start it with 'ollama serve')."
                ))
            except httpx.TimeoutException:
                error_holder.append(OllamaConnectionError(
                    f"Ollama at {self._base_url} timed out. "
                    f"The model may be loading or the request was too large. Try again."
                ))
            except (OllamaModelError, OllamaConnectionError) as e:
                error_holder.append(e)
            finally:
                chunk_queue.put(None)  # Sentinel

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _sync_stream)

        while True:
            try:
                chunk = chunk_queue.get(timeout=0.1)
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if chunk is None:
                break
            yield chunk

        if error_holder:
            raise error_holder[0]

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def max_context_tokens(self) -> int:
        return self._num_ctx

    @property
    def name(self) -> str:
        return f"Ollama ({self._model})"
