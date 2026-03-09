"""Tests for TTSEnhancer - Phase 9: SSML speech enhancement."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure the assistant package is importable regardless of working directory.
_ASSISTANT_DIR = str(Path(__file__).resolve().parent.parent)
if _ASSISTANT_DIR not in sys.path:
    sys.path.insert(0, _ASSISTANT_DIR)

_MOCK_CONFIG = {"tts": {}, "volume": {}}

# Pre-import the module so patch.object works reliably.
with patch.dict("sys.modules", {}):
    pass  # no-op; we import below with yaml_config patched via config module

import assistant.tts_enhancer as _tts_mod
from assistant.tts_enhancer import TTSEnhancer


@pytest.fixture
def enhancer():
    """Create a TTSEnhancer with mocked yaml_config."""
    with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
        yield TTSEnhancer()


@pytest.fixture
def enhancer_with_config():
    """Factory fixture: create TTSEnhancer with custom config dict."""
    def _make(cfg):
        with patch.object(_tts_mod, "yaml_config", cfg):
            return TTSEnhancer()
    return _make


# ------------------------------------------------------------------ #
# classify_message
# ------------------------------------------------------------------ #

class TestClassifyMessage:

    def test_warning_alarm(self, enhancer):
        assert enhancer.classify_message("Alarm im Keller!") == "warning"

    def test_warning_achtung(self, enhancer):
        assert enhancer.classify_message("Achtung, Fenster offen") == "warning"

    def test_greeting_guten_morgen(self, enhancer):
        assert enhancer.classify_message("Guten Morgen, Sir!") == "greeting"

    def test_greeting_hallo(self, enhancer):
        assert enhancer.classify_message("Hallo zusammen") == "greeting"

    def test_briefing_status(self, enhancer):
        assert enhancer.classify_message("Hier dein Status-Bericht") == "briefing"

    def test_briefing_wetter(self, enhancer):
        assert enhancer.classify_message("Das Wetter heute ist sonnig") == "briefing"

    def test_confirmation_erledigt(self, enhancer):
        assert enhancer.classify_message("Erledigt, Licht ist aus.") == "confirmation"

    def test_question_keyword(self, enhancer):
        assert enhancer.classify_message("Soll ich das Licht einschalten?") == "question"

    def test_question_mark_fallback(self, enhancer):
        assert enhancer.classify_message("Wie spät ist es?") == "question"

    def test_casual_default(self, enhancer):
        assert enhancer.classify_message("Das Licht im Flur ist an.") == "casual"

    # Negation guard
    def test_negation_keine_alarme(self, enhancer):
        """'keine Alarme' should NOT be classified as warning."""
        assert enhancer.classify_message("Es gibt keine Alarme.") != "warning"

    def test_negation_kein_fehler(self, enhancer):
        assert enhancer.classify_message("Kein Fehler gefunden.") != "warning"

    def test_negation_without_negation_is_warning(self, enhancer):
        """'Alarm ausgelöst' without negation SHOULD be warning."""
        assert enhancer.classify_message("Alarm ausgelöst!") == "warning"

    def test_negation_ohne_gefahr(self, enhancer):
        assert enhancer.classify_message("Ohne Gefahr, alles gut.") != "warning"


# ------------------------------------------------------------------ #
# enhance
# ------------------------------------------------------------------ #

class TestEnhance:

    def test_returns_dict_keys(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            result = enhancer.enhance("Hallo Welt")
        assert set(result.keys()) == {"text", "ssml", "message_type", "speed", "pitch", "volume"}

    def test_original_text_preserved(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            result = enhancer.enhance("Testtext")
        assert result["text"] == "Testtext"

    def test_auto_classifies_when_no_type(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            result = enhancer.enhance("Alarm!")
        assert result["message_type"] == "warning"

    def test_manual_message_type(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            result = enhancer.enhance("Irgendwas", message_type="briefing")
        assert result["message_type"] == "briefing"

    def test_ssml_disabled_returns_plain_text(self, enhancer):
        """With SSML disabled, ssml field should not contain SSML tags."""
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            result = enhancer.enhance("Einfacher Text")
        assert "<speak>" not in result["ssml"]

    def test_ssml_enabled_returns_ssml(self, enhancer_with_config):
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        e = enhancer_with_config(cfg)
        with patch.object(_tts_mod, "yaml_config", cfg):
            result = e.enhance("Hallo Welt")
        assert result["ssml"].startswith("<speak>")
        assert result["ssml"].endswith("</speak>")

    def test_phonetic_replacement_sir(self, enhancer):
        """Without SSML, 'Sir' should be replaced phonetically."""
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            result = enhancer.enhance("Guten Morgen, Sir.")
        assert "Sör" in result["ssml"]


# ------------------------------------------------------------------ #
# get_volume  – priority: critical > whisper > activity > time
# ------------------------------------------------------------------ #

class TestGetVolume:

    def test_critical_urgency_returns_emergency(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            vol = enhancer.get_volume(activity="sleeping", message_type="warning", urgency="critical")
        assert vol == 1.0

    def test_whisper_mode_overrides_activity(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            enhancer._whisper_mode = True
            vol = enhancer.get_volume(activity="", message_type="casual", urgency="medium")
        assert vol == 0.15

    def test_sleeping_activity(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            vol = enhancer.get_volume(activity="sleeping", message_type="casual", urgency="medium")
        assert vol == 0.2

    def test_default_volume_in_range(self, enhancer):
        """Without special conditions volume should be a float in valid range."""
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            vol = enhancer.get_volume(activity="", message_type="casual", urgency="medium")
        assert 0.0 < vol <= 1.0

    def test_critical_beats_whisper(self, enhancer):
        """Critical urgency should override whisper mode."""
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            enhancer._whisper_mode = True
            vol = enhancer.get_volume(urgency="critical")
        assert vol == 1.0


# ------------------------------------------------------------------ #
# check_whisper_command
# ------------------------------------------------------------------ #

class TestCheckWhisperCommand:

    def test_activate_psst(self, enhancer):
        assert enhancer.check_whisper_command("psst, sei leise") == "activate"
        assert enhancer._whisper_mode is True

    def test_activate_fluester(self, enhancer):
        result = enhancer.check_whisper_command("bitte flüster")
        assert result == "activate"

    def test_deactivate_normal(self, enhancer):
        enhancer._whisper_mode = True
        assert enhancer.check_whisper_command("normale lautstärke bitte") == "deactivate"
        assert enhancer._whisper_mode is False

    def test_no_command(self, enhancer):
        assert enhancer.check_whisper_command("Wie ist das Wetter?") is None

    def test_deactivate_only_when_active(self, enhancer):
        """Cancel trigger without whisper mode active returns None."""
        enhancer._whisper_mode = False
        assert enhancer.check_whisper_command("normale lautstärke") is None


# ------------------------------------------------------------------ #
# _split_sentences
# ------------------------------------------------------------------ #

class TestSplitSentences:

    def test_single_sentence(self, enhancer):
        assert enhancer._split_sentences("Hallo Welt.") == ["Hallo Welt."]

    def test_multiple_sentences(self, enhancer):
        result = enhancer._split_sentences("Satz eins. Satz zwei! Satz drei?")
        assert len(result) == 3

    def test_empty_string(self, enhancer):
        assert enhancer._split_sentences("") == []

    def test_no_punctuation(self, enhancer):
        assert enhancer._split_sentences("Kein Punkt am Ende") == ["Kein Punkt am Ende"]


# ------------------------------------------------------------------ #
# _add_warning_emphasis
# ------------------------------------------------------------------ #

class TestAddWarningEmphasis:

    def test_emphasis_tag_added(self, enhancer):
        result = enhancer._add_warning_emphasis("Es gibt einen Alarm")
        assert "<emphasis" in result
        assert "strong" in result

    def test_no_emphasis_on_normal_text(self, enhancer):
        result = enhancer._add_warning_emphasis("Alles ist gut")
        assert "<emphasis" not in result

    def test_multiple_warning_words(self, enhancer):
        result = enhancer._add_warning_emphasis("Warnung: Achtung Gefahr!")
        assert result.count("<emphasis") == 3


# ------------------------------------------------------------------ #
# enhance_narration
# ------------------------------------------------------------------ #

class TestEnhanceNarration:

    def test_basic_narration(self, enhancer):
        segments = [{"text": "Hallo Welt"}]
        result = enhancer.enhance_narration(segments)
        assert "ssml" in result
        assert "total_estimated_duration_ms" in result
        assert result["ssml"].startswith("<speak>")

    def test_pause_before(self, enhancer):
        segments = [{"text": "Wichtig", "pause_before_ms": 500}]
        result = enhancer.enhance_narration(segments)
        assert 'break time="500ms"' in result["ssml"]
        assert result["total_estimated_duration_ms"] >= 500

    def test_pause_after(self, enhancer):
        segments = [{"text": "Ende", "pause_after_ms": 300}]
        result = enhancer.enhance_narration(segments)
        assert 'break time="300ms"' in result["ssml"]

    def test_prosody_attributes(self, enhancer):
        segments = [{"text": "Schnell", "speed": 120, "pitch": "+5%", "volume": "loud"}]
        result = enhancer.enhance_narration(segments)
        assert 'rate="120%"' in result["ssml"]
        assert 'pitch="+5%"' in result["ssml"]
        assert 'volume="loud"' in result["ssml"]

    def test_emphasis_in_narration(self, enhancer):
        segments = [{"text": "Wichtig", "emphasis": "strong"}]
        result = enhancer.enhance_narration(segments)
        assert '<emphasis level="strong">' in result["ssml"]

    def test_empty_segments_skipped(self, enhancer):
        segments = [{"text": ""}, {"text": "Hallo"}]
        result = enhancer.enhance_narration(segments)
        assert "Hallo" in result["ssml"]

    def test_xml_escape_in_narration(self, enhancer):
        segments = [{"text": "A < B & C"}]
        result = enhancer.enhance_narration(segments)
        assert "&lt;" in result["ssml"]
        assert "&amp;" in result["ssml"]
