"""Tests for LLM provider abstraction (mocked — no real API calls)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from df_storyteller.llm.ollama_provider import OllamaProvider
from df_storyteller.llm.claude_provider import ClaudeProvider
from df_storyteller.llm.openai_provider import OpenAIProvider


@pytest.mark.asyncio
async def test_ollama_provider_generate():
    provider = OllamaProvider(model="llama3")

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"content": "A tale of a brave dwarf..."}
    }
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        with patch("httpx.AsyncClient.__aenter__", return_value=AsyncMock(post=AsyncMock(return_value=mock_response))):
            # Direct test of the provider interface
            assert provider.name == "Ollama (llama3)"
            assert provider.max_context_tokens == 32768
            assert provider.estimate_tokens("hello world") > 0


def test_ollama_provider_properties():
    provider = OllamaProvider(model="mistral", base_url="http://localhost:11434")
    assert provider.name == "Ollama (mistral)"
    assert provider.max_context_tokens == 32768


def test_provider_token_estimation():
    provider = OllamaProvider()
    text = "This is a test string with some words in it."
    tokens = provider.estimate_tokens(text)
    assert tokens > 0
    assert tokens < len(text)  # Should be fewer tokens than characters


# ---------------------------------------------------------------------------
# stream_generate() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claude_stream_generate():
    """Claude stream_generate yields text chunks via Anthropic streaming."""
    provider = ClaudeProvider(model="claude-sonnet-4-20250514", api_key="test-key")

    # Mock the streaming async context manager
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.text_stream = _async_iter(["Hello", " world", "!"])
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream_ctx

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        chunks = []
        async for chunk in provider.stream_generate("system", "user"):
            chunks.append(chunk)
        assert chunks == ["Hello", " world", "!"]
        assert "".join(chunks) == "Hello world!"


@pytest.mark.asyncio
async def test_openai_stream_generate():
    """OpenAI stream_generate yields text chunks via streaming API."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    # Create mock chunks
    def _make_chunk(content):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        return chunk

    mock_chunks = [_make_chunk("Hello"), _make_chunk(" world"), _make_chunk("!")]
    mock_stream = _async_iter(mock_chunks)

    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_stream

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        chunks = []
        async for chunk in provider.stream_generate("system", "user"):
            chunks.append(chunk)
        assert "".join(chunks) == "Hello world!"


@pytest.mark.asyncio
async def test_openai_stream_skips_empty_deltas():
    """OpenAI stream should skip chunks with no content (e.g. role-only chunks)."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    def _make_chunk(content):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        return chunk

    # Include a None content chunk (happens at stream start)
    mock_chunks = [_make_chunk(None), _make_chunk("Hello"), _make_chunk(None), _make_chunk("!")]
    mock_stream = _async_iter(mock_chunks)

    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_stream

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        chunks = []
        async for chunk in provider.stream_generate("system", "user"):
            chunks.append(chunk)
        assert chunks == ["Hello", "!"]


# ---------------------------------------------------------------------------
# Helper: async iterator from list
# ---------------------------------------------------------------------------


class _async_iter:
    """Turn a list into an async iterator for mocking streaming responses."""
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
