"""
Tests fuer OllamaClient — Chat, Generate, Payload-Konstruktion.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.ollama_client import OllamaClient, strip_think_tags, extract_thinking


class TestExtractThinking:
    """Tests fuer extract_thinking() — Think-Content extrahieren statt verwerfen."""

    def test_no_think_tags(self):
        cleaned, thinking = extract_thinking("Hello World")
        assert cleaned == "Hello World"
        assert thinking == ""

    def test_single_think_block(self):
        text = "<think>Ich denke nach...</think>Die Antwort ist 42."
        cleaned, thinking = extract_thinking(text)
        assert cleaned == "Die Antwort ist 42."
        assert "Ich denke nach" in thinking

    def test_multiple_think_blocks(self):
        text = "<think>Erstens</think>Hallo <think>Zweitens</think>Welt"
        cleaned, thinking = extract_thinking(text)
        assert cleaned == "Hallo Welt"
        assert "Erstens" in thinking
        assert "Zweitens" in thinking

    def test_empty_think_block(self):
        cleaned, thinking = extract_thinking("<think></think>Ergebnis")
        assert cleaned == "Ergebnis"
        assert thinking == ""

    def test_none_input(self):
        cleaned, thinking = extract_thinking(None)
        assert cleaned is None
        assert thinking == ""

    def test_empty_string(self):
        cleaned, thinking = extract_thinking("")
        assert cleaned == ""
        assert thinking == ""

    def test_only_think_block_returns_original(self):
        text = "<think>Nur Gedanken</think>"
        cleaned, thinking = extract_thinking(text)
        assert "Nur Gedanken" in thinking


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
        """Think wird bei Tools deaktiviert (wenn Modell Think+Tools nicht unterstuetzt)."""
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

        # Modell-Profil mocken: supports_think_with_tools=False
        from assistant.config import ModelProfile
        no_think_tools_profile = ModelProfile(supports_think_with_tools=False)
        with patch("assistant.config.get_model_profile", return_value=no_think_tools_profile):
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


# ============================================================
# Chat — Thinking Field
# ============================================================

class TestChatThinkingField:
    """Tests fuer das 'thinking' Feld in chat() Ergebnissen bei Think-Tags."""

    @pytest.mark.asyncio
    async def test_chat_returns_thinking_field(self):
        """chat() extrahiert Think-Content in result['thinking']."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={
                "message": {"content": "<think>reasoning here</think>Answer"},
            }),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert result["thinking"] == "reasoning here"
        assert result["message"]["content"] == "Answer"

    @pytest.mark.asyncio
    async def test_chat_no_thinking_without_tags(self):
        """Kein 'thinking' Feld wenn keine Think-Tags vorhanden."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={
                "message": {"content": "Normal answer"},
            }),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert "thinking" not in result

    @pytest.mark.asyncio
    async def test_chat_thinking_field_empty_think(self):
        """Leerer Think-Block wird nicht als 'thinking' gespeichert."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={
                "message": {"content": "<think></think>Text"},
            }),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert "thinking" not in result


# ============================================================
# Stream Chat — Thinking Collection
# ============================================================

class TestStreamChatThinking:
    """Tests fuer stream_chat's _thinking_parts Sammlung."""

    @pytest.mark.asyncio
    async def test_stream_collects_thinking(self):
        """stream_chat sammelt Think-Content in _last_stream_thinking."""
        import json as _json

        chunks = [
            {"message": {"content": "<think>"}, "done": False},
            {"message": {"content": "step1"}, "done": False},
            {"message": {"content": "</think>"}, "done": False},
            {"message": {"content": "Answer"}, "done": True},
        ]

        async def make_stream_content():
            for chunk in chunks:
                yield _json.dumps(chunk).encode() + b"\n"

        mock_resp = MagicMock(status=200)
        mock_resp.content = make_stream_content()
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)

        collected = []
        async for chunk in client.stream_chat(
            messages=[{"role": "user", "content": "test"}],
        ):
            collected.append(chunk)

        assert any("Answer" in c for c in collected)
        assert "step1" in client._last_stream_thinking

    @pytest.mark.asyncio
    async def test_stream_no_thinking_stored(self):
        """Ohne Think-Tags bleibt _last_stream_thinking leer."""
        import json as _json

        chunks = [
            {"message": {"content": "Hello"}, "done": False},
            {"message": {"content": " World"}, "done": True},
        ]

        async def make_stream_content():
            for chunk in chunks:
                yield _json.dumps(chunk).encode() + b"\n"

        mock_resp = MagicMock(status=200)
        mock_resp.content = make_stream_content()
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)

        collected = []
        async for chunk in client.stream_chat(
            messages=[{"role": "user", "content": "test"}],
        ):
            collected.append(chunk)

        assert client._last_stream_thinking == ""


# ============================================================
# Generate — Uses extract_thinking
# ============================================================

class TestGenerateUsesExtractThinking:
    """Tests fuer generate() — Thinking wird gestrippt."""

    @pytest.mark.asyncio
    async def test_generate_uses_extract_thinking(self):
        """generate() entfernt Think-Tags via extract_thinking."""
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"response": "<think>thought</think>Result"}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)

        client = _make_client_with_mock_session(instance)
        result = await client.generate(prompt="test")
        assert result == "Result"
