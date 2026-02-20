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


class TestChatPayload:
    """Tests fuer chat() Payload-Konstruktion."""

    @pytest.mark.asyncio
    async def test_think_false_with_tools(self):
        """Think wird bei Tools deaktiviert."""
        client = OllamaClient()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"message": {"content": "ok"}})

        captured_payload = {}

        async def fake_post(url, json=None, timeout=None):
            captured_payload.update(json)
            return mock_resp

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            # Mock post mit Capture
            captured = {}

            async def capture_post(url, **kwargs):
                captured.update(kwargs.get("json", {}))
                resp = AsyncMock()
                resp.status = 200
                resp.json = AsyncMock(return_value={"message": {"content": "ok"}})
                return resp

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                json=AsyncMock(return_value={"message": {"content": "ok"}}),
                text=AsyncMock(return_value="ok"),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

            result = await client.chat(
                messages=[{"role": "user", "content": "test"}],
                tools=[{"type": "function", "function": {"name": "test"}}],
            )
            # Pruefe dass post aufgerufen wurde
            instance.post.assert_called_once()
            call_kwargs = instance.post.call_args
            payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
            # Payload sollte think=False bei Tools haben
            if payload:
                assert payload.get("think") is False

    @pytest.mark.asyncio
    async def test_think_false_for_fast_model(self):
        """Think wird fuer fast model deaktiviert."""
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                json=AsyncMock(return_value={"message": {"content": "ok"}}),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

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
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                json=AsyncMock(return_value={"message": {"content": "ok"}}),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

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
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=500,
                text=AsyncMock(return_value="Internal Server Error"),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

            result = await client.chat(
                messages=[{"role": "user", "content": "test"}],
            )
            assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_returns_empty_on_error(self):
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=500,
                text=AsyncMock(return_value="Error"),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

            result = await client.generate(prompt="test")
            assert result == ""


class TestGenerate:
    """Tests fuer generate() Methode."""

    @pytest.mark.asyncio
    async def test_generate_uses_api_generate(self):
        """generate() nutzt /api/generate statt /api/chat."""
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                json=AsyncMock(return_value={"response": "Generated text"}),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

            result = await client.generate(prompt="Test prompt")
            assert result == "Generated text"

            # Pruefe URL enthalt /api/generate
            call_args = instance.post.call_args
            url = call_args[0][0]
            assert "/api/generate" in url

    @pytest.mark.asyncio
    async def test_generate_strips_think_tags(self):
        """generate() entfernt Think-Tags aus der Antwort."""
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                json=AsyncMock(return_value={"response": "<think>reasoning</think>Answer"}),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

            result = await client.generate(prompt="test")
            assert result == "Answer"

    @pytest.mark.asyncio
    async def test_generate_payload_has_prompt(self):
        """generate() sendet prompt statt messages."""
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                json=AsyncMock(return_value={"response": "ok"}),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.post = MagicMock(return_value=cm)

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
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            instance = AsyncMock()
            MockSession.return_value.__aenter__ = AsyncMock(return_value=instance)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(status=200))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.get = MagicMock(return_value=cm)

            assert await client.is_available() is True

    @pytest.mark.asyncio
    async def test_unavailable_on_error(self):
        client = OllamaClient()

        with patch("aiohttp.ClientSession") as MockSession:
            import aiohttp
            MockSession.return_value.__aenter__ = AsyncMock(
                side_effect=aiohttp.ClientError("Connection refused")
            )
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

            assert await client.is_available() is False
