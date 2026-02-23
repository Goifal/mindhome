"""
Tests fuer OllamaClient — Chat, Generate, Payload-Konstruktion.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.ollama_client import OllamaClient, strip_think_tags


class TestStripThinkTags:
    """Tests fuer strip_think_tags() — schon in test_ollama_streaming.py,
    hier nur Ergaenzungen fuer Edge Cases."""

    def test_multiple_think_blocks(self):
        text = "<think>A</think>Hello <think>B</think>World"
        assert strip_think_tags(text) == "Hello World"

    def test_nested_angle_brackets(self):
        text = "<think>test <b>bold</b></think>Result"
        assert strip_think_tags(text) == "Result"


def _make_client_with_mock_session(mock_session):
    """Erzeugt einen OllamaClient dessen _get_session() die mock_session zurueckgibt."""
    client = OllamaClient()
    client._get_session = AsyncMock(return_value=mock_session)
    return client


class TestChatPayload:
    """Tests fuer chat() Payload-Konstruktion."""

    @pytest.mark.asyncio
    async def test_think_false_with_tools(self):
        """Think wird bei Tools deaktiviert."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"message": {"content": "ok"}}),
            text=AsyncMock(return_value="ok"),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
            tools=[{"type": "function", "function": {"name": "test"}}],
        )
        instance.post.assert_called_once()
        call_kwargs = instance.post.call_args
        payload = call_kwargs[1].get("json", {})
        assert payload.get("think") is False

    @pytest.mark.asyncio
    async def test_think_false_for_fast_model(self):
        """Think wird fuer fast model deaktiviert."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"message": {"content": "ok"}}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        from assistant.config import settings
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
            model=settings.model_fast,
        )
        call_kwargs = instance.post.call_args
        payload = call_kwargs[1].get("json", {})
        assert payload.get("think") is False

    @pytest.mark.asyncio
    async def test_explicit_think_overrides(self):
        """Explizites think=True ueberschreibt Auto-Logik."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"message": {"content": "ok"}}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
            think=True,
        )
        call_kwargs = instance.post.call_args
        payload = call_kwargs[1].get("json", {})
        assert payload.get("think") is True


class TestChatError:
    """Tests fuer Fehlerbehandlung."""

    @pytest.mark.asyncio
    async def test_chat_returns_error_on_non_200(self):
        mock_resp = MagicMock(
            status=500,
            text=AsyncMock(return_value="Internal Server Error"),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_returns_empty_on_error(self):
        mock_resp = MagicMock(
            status=500,
            text=AsyncMock(return_value="Error"),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.generate(prompt="test")
        assert result == ""


class TestGenerate:
    """Tests fuer generate() Methode."""

    @pytest.mark.asyncio
    async def test_generate_uses_api_generate(self):
        """generate() nutzt /api/generate statt /api/chat."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"response": "Generated text"}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.generate(prompt="Test prompt")
        assert result == "Generated text"

        # Pruefe URL enthalt /api/generate
        call_args = instance.post.call_args
        url = call_args[0][0]
        assert "/api/generate" in url

    @pytest.mark.asyncio
    async def test_generate_strips_think_tags(self):
        """generate() entfernt Think-Tags aus der Antwort."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"response": "<think>reasoning</think>Answer"}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.generate(prompt="test")
        assert result == "Answer"

    @pytest.mark.asyncio
    async def test_generate_payload_has_prompt(self):
        """generate() sendet prompt statt messages."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"response": "ok"}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        await client.generate(prompt="Mein Prompt", temperature=0.3)

        payload = instance.post.call_args[1].get("json", {})
        assert payload["prompt"] == "Mein Prompt"
        assert "messages" not in payload
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.3


class TestIsAvailable:
    """Tests fuer is_available()."""

    @pytest.mark.asyncio
    async def test_available_on_200(self):
        mock_resp = MagicMock(status=200)
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.get = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        assert await client.is_available() is True

    @pytest.mark.asyncio
    async def test_unavailable_on_error(self):
        import aiohttp
        instance = MagicMock()
        instance.get = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))

        client = _make_client_with_mock_session(instance)
        assert await client.is_available() is False
