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


# ============================================================
# validate_notification
# ============================================================

from assistant.ollama_client import (  # noqa: E402
    _extract_final_answer,
    _log_ollama_metrics,
    _looks_german,
    _model_options,
    validate_notification,
)


class TestValidateNotification:
    """Tests for validate_notification() — meta-leak detection, language checks."""

    def test_empty_input(self):
        assert validate_notification("") == ""

    def test_none_input(self):
        assert validate_notification(None) is None

    def test_valid_german_notification(self):
        text = "Sir, die Temperatur ist auf 22 Grad gestiegen."
        result = validate_notification(text)
        assert result == text

    def test_strips_think_tags(self):
        text = "<think>reasoning</think>Sir, das Licht ist aus."
        result = validate_notification(text)
        assert "<think>" not in result
        assert "Sir" in result

    def test_meta_leakage_removed(self):
        """Function call names like speak, tool_call are stripped."""
        text = "speak Sir, die Temperatur ist auf 22 Grad gestiegen."
        result = validate_notification(text)
        assert "speak" not in result.split()

    def test_meta_commentary_rejected(self):
        """Text with multiple meta markers is rejected."""
        text = "Let me think about this. I need to translate the user message. The user wants to know about light."
        result = validate_notification(text)
        assert result == ""

    def test_meta_commentary_with_final_german_answer(self):
        """Meta-commentary with extractable German answer at the end."""
        text = (
            "Let me think about this. I should respond.\n"
            "The user wants a notification.\n"
            '"Sir, das Licht wurde eingeschaltet."'
        )
        result = validate_notification(text)
        if result:
            assert "Licht" in result

    def test_too_long_notification_truncated(self):
        """Notifications >300 chars — first line extracted if valid."""
        first_line = "Sir, die Temperatur ist zu hoch und das Fenster steht noch offen."
        long_text = first_line + "\n" + "x " * 200
        result = validate_notification(long_text)
        if result:
            assert result == first_line

    def test_too_long_without_valid_first_line(self):
        """Long text without valid first line returns empty."""
        long_text = "x" * 350
        result = validate_notification(long_text)
        assert result == ""

    def test_non_german_long_text_rejected(self):
        """Non-German text >50 chars is rejected."""
        text = "This is a completely English sentence that has absolutely no German words in it at all whatsoever"
        result = validate_notification(text)
        assert result == ""

    def test_short_non_german_accepted(self):
        """Short non-German text (<= 50 chars) passes."""
        text = "OK, done."
        result = validate_notification(text)
        assert result == text

    def test_tool_call_names_removed(self):
        """Various tool_call function names are stripped from text."""
        text = "set_light get_weather Sir, das Licht ist an."
        result = validate_notification(text)
        assert "set_light" not in result
        assert "get_weather" not in result
        assert "Licht" in result

    def test_all_tool_names_removed_returns_empty(self):
        """If only tool names remain, returns empty."""
        text = "tool_call speak emit"
        result = validate_notification(text)
        assert result == ""


class TestLooksGerman:
    """Tests for _looks_german helper."""

    def test_german_text(self):
        assert _looks_german("Sir, die Temperatur ist zu hoch.")

    def test_english_text(self):
        assert not _looks_german("This is completely English text without any German.")

    def test_umlaut_text(self):
        assert _looks_german("Schönes Wetter heute!")

    def test_empty_text(self):
        assert not _looks_german("")

    def test_single_german_marker_not_enough(self):
        assert not _looks_german("only sir here")

    def test_two_markers_sufficient(self):
        assert _looks_german("sir das ist gut")


class TestExtractFinalAnswer:
    """Tests for _extract_final_answer helper."""

    def test_extracts_quoted_german_line(self):
        text = 'Some reasoning here.\n"Sir, das Licht ist an."'
        result = _extract_final_answer(text)
        assert "Licht" in result

    def test_no_german_line_returns_empty(self):
        text = "Let me think about this.\nI should respond."
        result = _extract_final_answer(text)
        assert result == ""

    def test_skips_too_short_lines(self):
        text = "Reasoning.\nOk"
        result = _extract_final_answer(text)
        assert result == ""

    def test_skips_too_long_lines(self):
        text = "Reasoning.\n" + "a" * 260
        result = _extract_final_answer(text)
        assert result == ""

    def test_skips_lines_with_meta_markers(self):
        text = "Think.\nI need to translate this for the user."
        result = _extract_final_answer(text)
        assert result == ""


# ============================================================
# _log_ollama_metrics
# ============================================================


class TestLogOllamaMetrics:
    """Tests for _log_ollama_metrics."""

    def test_no_tokens_skips_logging(self):
        result = {"some_key": "value"}
        _log_ollama_metrics(result, "test-model")

    def test_logs_with_full_metrics(self):
        result = {
            "prompt_eval_count": 100,
            "eval_count": 50,
            "total_duration": 1_000_000_000,
            "prompt_eval_duration": 400_000_000,
            "eval_duration": 500_000_000,
            "load_duration": 100_000_000,
        }
        _log_ollama_metrics(result, "test-model", "chat")

    def test_partial_metrics(self):
        result = {
            "prompt_eval_count": 100,
            "eval_count": None,
            "total_duration": None,
        }
        _log_ollama_metrics(result, "test-model")

    def test_zero_eval_duration(self):
        result = {
            "prompt_eval_count": 100,
            "eval_count": 50,
            "total_duration": 1_000_000_000,
            "eval_duration": 0,
        }
        _log_ollama_metrics(result, "test-model")


# ============================================================
# _model_options
# ============================================================


class TestModelOptions:
    """Tests for _model_options helper."""

    def test_basic_options(self):
        opts = _model_options("test-model", 0.7, 256, 4096)
        assert "temperature" in opts
        assert "num_predict" in opts
        assert "num_ctx" in opts
        assert opts["temperature"] == 0.7
        assert opts["num_predict"] == 256
        assert opts["num_ctx"] == 4096

    def test_think_enabled_uses_think_params(self):
        opts = _model_options("test-model", 0.9, 256, 4096, think_enabled=True)
        assert "top_p" in opts

    def test_think_disabled_uses_normal_params(self):
        opts = _model_options("test-model", 0.7, 256, 4096, think_enabled=False)
        assert "top_p" in opts

    def test_flash_attn_from_config(self):
        with patch("assistant.config.yaml_config", {"ollama": {"flash_attn": True}}):
            opts = _model_options("test", 0.7, 256, 4096)
        assert opts.get("flash_attn") is True

    def test_num_gpu_from_config(self):
        with patch("assistant.config.yaml_config", {"ollama": {"num_gpu": 1}}):
            opts = _model_options("test", 0.7, 256, 4096)
        assert opts.get("num_gpu") == 1

    def test_num_gpu_empty_string_ignored(self):
        with patch("assistant.config.yaml_config", {"ollama": {"num_gpu": ""}}):
            opts = _model_options("test", 0.7, 256, 4096)
        assert "num_gpu" not in opts


# ============================================================
# OllamaClient — num_ctx_for, keep_alive, close, circuit breaker
# ============================================================


class TestNumCtxFor:
    """Tests for num_ctx_for() tier-based context window selection."""

    def test_fast_tier(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_fast": 1024}}):
            assert client.num_ctx_for("any-model", tier="fast") == 1024

    def test_deep_tier(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_deep": 16384}}):
            assert client.num_ctx_for("any-model", tier="deep") == 16384

    def test_smart_tier(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_smart": 8192}}):
            assert client.num_ctx_for("any-model", tier="smart") == 8192

    def test_notify_tier(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_notify": 1500}}):
            assert client.num_ctx_for("any-model", tier="notify") == 1500

    def test_notify_tier_fallback_to_fast(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_fast": 2048}}):
            assert client.num_ctx_for("any-model", tier="notify") == 2048

    def test_default_no_config(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {}):
            ctx = client.num_ctx_for("some-model")
        assert ctx == OllamaClient._DEFAULT_NUM_CTX

    def test_fast_model_name_matching(self):
        client = OllamaClient()
        from assistant.config import settings
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_fast": 1024}}):
            with patch.object(settings, "model_fast", "fast-model"):
                with patch.object(settings, "model_smart", "smart-model"):
                    ctx = client.num_ctx_for("fast-model")
        assert ctx == 1024


class TestKeepAlive:
    """Tests for keep_alive property."""

    def test_string_value(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"keep_alive": "10m"}}):
            assert client.keep_alive == "10m"

    def test_int_value(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"keep_alive": -1}}):
            assert client.keep_alive == -1

    def test_zero_value(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"keep_alive": 0}}):
            assert client.keep_alive == 0

    def test_default_value(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {}}):
            assert client.keep_alive == "5m"

    def test_no_ollama_config(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {}):
            assert client.keep_alive == "5m"


class TestNumCtxProperty:
    """Tests for the num_ctx property (smart tier shortcut)."""

    def test_reads_smart_ctx(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx_smart": 6000}}):
            assert client.num_ctx == 6000

    def test_fallback_to_num_ctx(self):
        client = OllamaClient()
        with patch("assistant.config.yaml_config", {"ollama": {"num_ctx": 3000}}):
            assert client.num_ctx == 3000


class TestClose:
    """Tests for close() method."""

    @pytest.mark.asyncio
    async def test_close_open_session(self):
        client = OllamaClient()
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        client._session = mock_session
        await client.close()
        mock_session.close.assert_called_once()
        assert client._session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self):
        client = OllamaClient()
        await client.close()

    @pytest.mark.asyncio
    async def test_close_already_closed_session(self):
        client = OllamaClient()
        mock_session = MagicMock()
        mock_session.closed = True
        client._session = mock_session
        await client.close()


class TestGetTimeout:
    """Tests for _get_timeout."""

    def test_fast_model(self):
        from assistant.constants import LLM_TIMEOUT_FAST
        client = OllamaClient()
        from assistant.config import settings
        assert client._get_timeout(settings.model_fast) == LLM_TIMEOUT_FAST

    def test_deep_model(self):
        from assistant.constants import LLM_TIMEOUT_DEEP
        client = OllamaClient()
        from assistant.config import settings
        assert client._get_timeout(settings.model_deep) == LLM_TIMEOUT_DEEP

    def test_smart_model_default(self):
        from assistant.constants import LLM_TIMEOUT_SMART
        client = OllamaClient()
        assert client._get_timeout("unknown-model") == LLM_TIMEOUT_SMART

    def test_notify_model(self):
        from assistant.constants import LLM_TIMEOUT_FAST
        client = OllamaClient()
        from assistant.config import settings
        assert client._get_timeout(settings.model_notify) == LLM_TIMEOUT_FAST


class TestChatCircuitBreaker:
    """Tests for circuit breaker interaction."""

    @pytest.mark.asyncio
    async def test_chat_circuit_open_returns_error(self):
        client = OllamaClient()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = False
            result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert "error" in result
        assert "Circuit" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_circuit_open_returns_empty(self):
        client = OllamaClient()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = False
            result = await client.generate(prompt="test")
        assert result == ""


class TestChatTimeoutAndClientError:
    """Tests for timeout and connection error handling in chat."""

    @pytest.mark.asyncio
    async def test_chat_timeout(self):
        import asyncio as _asyncio
        instance = MagicMock()
        instance.post = MagicMock(side_effect=_asyncio.TimeoutError())
        client = _make_client_with_mock_session(instance)
        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert "error" in result
        assert "Timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_chat_client_error(self):
        import aiohttp
        instance = MagicMock()
        instance.post = MagicMock(side_effect=aiohttp.ClientError("refused"))
        client = _make_client_with_mock_session(instance)
        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_timeout(self):
        import asyncio as _asyncio
        instance = MagicMock()
        instance.post = MagicMock(side_effect=_asyncio.TimeoutError())
        client = _make_client_with_mock_session(instance)
        result = await client.generate(prompt="test")
        assert result == ""

    @pytest.mark.asyncio
    async def test_generate_client_error(self):
        import aiohttp
        instance = MagicMock()
        instance.post = MagicMock(side_effect=aiohttp.ClientError("refused"))
        client = _make_client_with_mock_session(instance)
        result = await client.generate(prompt="test")
        assert result == ""


class TestChatOllamaErrorInBody:
    """Tests for Ollama returning 200 with error in body."""

    @pytest.mark.asyncio
    async def test_chat_200_with_error_field(self):
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"error": "model not found"}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)
        client = _make_client_with_mock_session(instance)
        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert "error" in result
        assert result["error"] == "model not found"


class TestListModels:
    """Tests for list_models."""

    @pytest.mark.asyncio
    async def test_list_models_success(self):
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={
                "models": [{"name": "qwen:4b"}, {"name": "llama:7b"}],
            }),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.get = MagicMock(return_value=cm)
        client = _make_client_with_mock_session(instance)
        models = await client.list_models()
        assert models == ["qwen:4b", "llama:7b"]

    @pytest.mark.asyncio
    async def test_list_models_error_returns_empty(self):
        import aiohttp
        instance = MagicMock()
        instance.get = MagicMock(side_effect=aiohttp.ClientError("fail"))
        client = _make_client_with_mock_session(instance)
        models = await client.list_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_timeout_returns_empty(self):
        import asyncio as _asyncio
        instance = MagicMock()
        instance.get = MagicMock(side_effect=_asyncio.TimeoutError())
        client = _make_client_with_mock_session(instance)
        models = await client.list_models()
        assert models == []


class TestChatThinkControl:
    """Tests for think_control settings in chat()."""

    def _make_chat_client(self, response_content="ok"):
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"message": {"content": response_content}}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)
        client = _make_client_with_mock_session(instance)
        return client, instance

    @pytest.mark.asyncio
    async def test_think_off_config(self):
        client, instance = self._make_chat_client()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            with patch("assistant.config.yaml_config",
                        {"latency_optimization": {"think_control": "off"}}):
                await client.chat(messages=[{"role": "user", "content": "test"}])
        payload = instance.post.call_args[1]["json"]
        assert payload.get("think") is False

    @pytest.mark.asyncio
    async def test_think_on_config(self):
        client, instance = self._make_chat_client()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            with patch("assistant.config.yaml_config",
                        {"latency_optimization": {"think_control": "on"}}):
                await client.chat(messages=[{"role": "user", "content": "test"}])
        payload = instance.post.call_args[1]["json"]
        assert payload.get("think") is True

    @pytest.mark.asyncio
    async def test_think_smart_off_with_smart_tier(self):
        client, instance = self._make_chat_client()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            with patch("assistant.config.yaml_config",
                        {"latency_optimization": {"think_control": "smart_off"}}):
                await client.chat(
                    messages=[{"role": "user", "content": "test"}],
                    tier="smart",
                )
        payload = instance.post.call_args[1]["json"]
        assert payload.get("think") is False


class TestChatFormatParameter:
    """Tests for the format parameter in chat()."""

    def _make_chat_client(self, response_content="ok"):
        mock_resp = MagicMock(
            status=200,
            json=AsyncMock(return_value={"message": {"content": response_content}}),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)
        client = _make_client_with_mock_session(instance)
        return client, instance

    @pytest.mark.asyncio
    async def test_explicit_format_without_tools(self):
        client, instance = self._make_chat_client()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            await client.chat(
                messages=[{"role": "user", "content": "test"}],
                format="json",
            )
        payload = instance.post.call_args[1]["json"]
        assert payload.get("format") == "json"

    @pytest.mark.asyncio
    async def test_tools_with_json_mode_disabled(self):
        client, instance = self._make_chat_client()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            with patch("assistant.config.yaml_config",
                        {"json_mode_tools": {"enabled": False}}):
                await client.chat(
                    messages=[{"role": "user", "content": "test"}],
                    tools=[{"type": "function", "function": {"name": "t"}}],
                )
        payload = instance.post.call_args[1]["json"]
        assert "format" not in payload

    @pytest.mark.asyncio
    async def test_tools_with_explicit_format(self):
        client, instance = self._make_chat_client()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            await client.chat(
                messages=[{"role": "user", "content": "test"}],
                tools=[{"type": "function", "function": {"name": "t"}}],
                format="custom",
            )
        payload = instance.post.call_args[1]["json"]
        assert payload.get("format") == "custom"


class TestStreamChatErrors:
    """Tests for stream_chat error paths."""

    @pytest.mark.asyncio
    async def test_stream_circuit_open(self):
        client = OllamaClient()
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = False
            chunks = []
            async for c in client.stream_chat(
                messages=[{"role": "user", "content": "test"}],
            ):
                chunks.append(c)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_stream_http_error(self):
        mock_resp = MagicMock(
            status=500,
            text=AsyncMock(return_value="Server Error"),
        )
        cm = AsyncMock(__aenter__=AsyncMock(return_value=mock_resp),
                       __aexit__=AsyncMock(return_value=False))
        instance = MagicMock()
        instance.post = MagicMock(return_value=cm)
        client = _make_client_with_mock_session(instance)
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            chunks = []
            async for c in client.stream_chat(
                messages=[{"role": "user", "content": "test"}],
            ):
                chunks.append(c)
        assert "[STREAM_ERROR]" in chunks

    @pytest.mark.asyncio
    async def test_stream_timeout(self):
        import asyncio as _asyncio
        instance = MagicMock()
        instance.post = MagicMock(side_effect=_asyncio.TimeoutError())
        client = _make_client_with_mock_session(instance)
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            chunks = []
            async for c in client.stream_chat(
                messages=[{"role": "user", "content": "test"}],
            ):
                chunks.append(c)
        assert "[STREAM_TIMEOUT]" in chunks

    @pytest.mark.asyncio
    async def test_stream_client_error(self):
        import aiohttp
        instance = MagicMock()
        instance.post = MagicMock(side_effect=aiohttp.ClientError("refused"))
        client = _make_client_with_mock_session(instance)
        with patch("assistant.ollama_client.ollama_breaker") as breaker:
            breaker.is_available = True
            chunks = []
            async for c in client.stream_chat(
                messages=[{"role": "user", "content": "test"}],
            ):
                chunks.append(c)
        assert "[STREAM_ERROR]" in chunks


class TestGetSession:
    """Tests for _get_session lazy initialization."""

    @pytest.mark.asyncio
    async def test_creates_session_on_first_call(self):
        client = OllamaClient()
        assert client._session is None
        with patch("assistant.ollama_client.aiohttp.ClientSession") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.closed = False
            mock_cls.return_value = mock_instance
            session = await client._get_session()
        assert session is mock_instance

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self):
        client = OllamaClient()
        mock_session = MagicMock()
        mock_session.closed = False
        client._session = mock_session
        session = await client._get_session()
        assert session is mock_session

    @pytest.mark.asyncio
    async def test_recreates_closed_session(self):
        client = OllamaClient()
        old_session = MagicMock()
        old_session.closed = True
        client._session = old_session
        with patch("assistant.ollama_client.aiohttp.ClientSession") as mock_cls:
            new_session = MagicMock()
            new_session.closed = False
            mock_cls.return_value = new_session
            session = await client._get_session()
        assert session is new_session
