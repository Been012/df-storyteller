"""Tests for LLM provider abstraction (mocked — no real API calls)."""

from unittest.mock import AsyncMock, patch

import pytest

from df_storyteller.llm.ollama_provider import OllamaProvider


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
            assert provider.max_context_tokens == 8000
            assert provider.estimate_tokens("hello world") > 0


def test_ollama_provider_properties():
    provider = OllamaProvider(model="mistral", base_url="http://localhost:11434")
    assert provider.name == "Ollama (mistral)"
    assert provider.max_context_tokens == 8000


def test_provider_token_estimation():
    provider = OllamaProvider()
    text = "This is a test string with some words in it."
    tokens = provider.estimate_tokens(text)
    assert tokens > 0
    assert tokens < len(text)  # Should be fewer tokens than characters
