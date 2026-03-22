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
        assert (
            enhancer.classify_message("Soll ich das Licht einschalten?") == "question"
        )

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
        assert set(result.keys()) == {
            "text",
            "ssml",
            "message_type",
            "speed",
            "pitch",
            "volume",
        }

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
            vol = enhancer.get_volume(
                activity="sleeping", message_type="warning", urgency="critical"
            )
        assert vol == 1.0

    def test_whisper_mode_overrides_activity(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            enhancer._whisper_mode = True
            vol = enhancer.get_volume(
                activity="", message_type="casual", urgency="medium"
            )
        assert vol == 0.15

    def test_sleeping_activity(self, enhancer):
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            vol = enhancer.get_volume(
                activity="sleeping", message_type="casual", urgency="medium"
            )
        assert vol == 0.2

    def test_default_volume_in_range(self, enhancer):
        """Without special conditions volume should be a float in valid range."""
        with patch.object(_tts_mod, "yaml_config", _MOCK_CONFIG):
            vol = enhancer.get_volume(
                activity="", message_type="casual", urgency="medium"
            )
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
        assert (
            enhancer.check_whisper_command("normale lautstärke bitte") == "deactivate"
        )
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


# ------------------------------------------------------------------ #
# Zusaetzliche Tests fuer 100% Coverage
# ------------------------------------------------------------------ #


class TestSafeFloatInt:
    """Tests fuer _safe_float und _safe_int im __init__ — Zeilen 156-157, 162-163."""

    def test_safe_float_invalid_value(self):
        """_safe_float mit ungueltigem Wert nutzt Default (Zeilen 156-157)."""
        cfg = {"tts": {}, "volume": {"day": "not_a_number", "evening": None}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        assert e.vol_day == 0.8  # Default
        assert e.vol_evening == 0.5  # Default

    def test_safe_int_invalid_value(self):
        """_safe_int mit ungueltigem Wert nutzt Default (Zeilen 162-163)."""
        cfg = {"tts": {}, "volume": {"evening_start": "abc", "night_start": []}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        assert e.evening_start == 22  # Default
        assert e.night_start == 0  # Default


class TestEnhanceProsodyVariation:
    """Tests fuer enhance mit prosody_variation — Zeilen 249-250."""

    def test_prosody_variation_enabled(self):
        """Mit prosody_variation werden Speed/Pitch aus Maps gelesen (Zeilen 249-250)."""
        cfg = {"tts": {"prosody_variation": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            result = e.enhance("Erledigt.", message_type="confirmation")
        assert result["speed"] == 105  # confirmation speed
        assert result["pitch"] == "+5%"  # confirmation pitch


class TestGetVolumeLiveConfig:
    """Tests fuer get_volume mit Live-Config-Parsing — Zeilen 291, 295."""

    def test_get_volume_invalid_float_fallback(self):
        """_f in get_volume faengt ungueltige Floats ab (Zeile 291)."""
        cfg = {"tts": {}, "volume": {"day": "invalid", "emergency": "bad"}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            vol = e.get_volume()
        # Default-Werte werden genutzt
        assert isinstance(vol, float)

    def test_get_volume_invalid_int_fallback(self):
        """_i in get_volume faengt ungueltige Ints ab (Zeile 295)."""
        cfg = {"tts": {}, "volume": {"evening_start": "abc", "night_start": "xyz"}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            vol = e.get_volume()
        assert isinstance(vol, float)


class TestGetVolumeTimeOfDay:
    """Tests fuer Tageszeit-basierte Lautstaerke — Zeilen 325, 330, 335-336, 338."""

    def test_evening_volume(self):
        """Abend-Lautstaerke zwischen evening_start und night_start (Zeilen 325, 330)."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {},
            "volume": {"evening_start": 20, "night_start": 23, "morning_start": 7},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 21, 0)  # 21 Uhr
                vol = e.get_volume()
        assert vol == 0.5  # vol_evening Default

    def test_night_volume_over_midnight(self):
        """Nacht-Lautstaerke ueber Mitternacht (Zeilen 335-336)."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {},
            "volume": {"evening_start": 18, "night_start": 23, "morning_start": 7},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            # Test at 1:00 AM (nach Mitternacht, sollte Night sein)
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 1, 0)
                vol = e.get_volume()
        assert vol == 0.3  # vol_night Default

    def test_night_volume_non_wrapping(self):
        """Nacht-Lautstaerke ohne Mitternachts-Wrap (Zeile 338)."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {},
            "volume": {"evening_start": 22, "night_start": 2, "morning_start": 7},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 4, 0)  # 4 Uhr
                vol = e.get_volume()
        assert vol == 0.3  # vol_night


class TestGetVolumeException:
    """Tests fuer get_volume Exception-Handler — Zeilen 341-343."""

    def test_get_volume_exception_returns_fallback(self):
        """get_volume gibt 0.8 zurueck bei allgemeinem Fehler (Zeilen 341-343)."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        # yaml_config.get wirft Exception
        with patch.object(
            _tts_mod,
            "yaml_config",
            MagicMock(get=MagicMock(side_effect=Exception("config broken"))),
        ):
            vol = e.get_volume()
        assert vol == 0.8


class TestAutoNightWhisper:
    """Tests fuer _is_auto_night_whisper — Zeilen 384-391."""

    def test_auto_night_whisper_active_over_midnight(self):
        """Auto-Night-Whisper aktiv bei Nachtzeit ueber Mitternacht (Zeilen 387-388)."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {"auto_night_whisper": True},
            "volume": {"auto_whisper_start": 23, "auto_whisper_end": 6},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 2, 0)  # 2 Uhr nachts
                assert e._is_auto_night_whisper() is True

    def test_auto_night_whisper_inactive_during_day(self):
        """Auto-Night-Whisper inaktiv tagsueber (Zeile 389 false branch)."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {"auto_night_whisper": True},
            "volume": {"auto_whisper_start": 23, "auto_whisper_end": 6},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 14, 0)  # 14 Uhr
                assert e._is_auto_night_whisper() is False

    def test_auto_night_whisper_disabled(self):
        """Auto-Night-Whisper deaktiviert in Config (Zeile 383)."""
        cfg = {"tts": {"auto_night_whisper": False}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            assert e._is_auto_night_whisper() is False

    def test_auto_night_whisper_exception(self):
        """Auto-Night-Whisper faengt Exceptions ab (Zeilen 390-391)."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        with patch.object(
            _tts_mod,
            "yaml_config",
            MagicMock(get=MagicMock(side_effect=Exception("oops"))),
        ):
            assert e._is_auto_night_whisper() is False

    def test_is_whisper_mode_auto_night(self):
        """is_whisper_mode gibt True zurueck bei Auto-Night-Whisper."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {"auto_night_whisper": True},
            "volume": {"auto_whisper_start": 23, "auto_whisper_end": 6},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 1, 0)
                assert e.is_whisper_mode is True

    def test_auto_night_whisper_non_wrapping(self):
        """Auto-Night-Whisper mit start < end (kein Mitternachts-Wrap) (Zeile 389)."""
        from datetime import datetime as _dt

        cfg = {
            "tts": {"auto_night_whisper": True},
            "volume": {"auto_whisper_start": 1, "auto_whisper_end": 5},
        }
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            with patch.object(_tts_mod, "datetime") as mock_dt:
                mock_dt.now.return_value = _dt(2026, 3, 11, 3, 0)  # Innerhalb 1-5
                assert e._is_auto_night_whisper() is True


class TestGenerateSSMLCoverage:
    """Tests fuer _generate_ssml — Zeilen 408, 410, 413, 433, 442-455, 458."""

    def test_ssml_with_speed_and_pitch(self):
        """SSML mit speed != 100 und pitch != 0% generiert prosody-Tag (Zeilen 408, 410, 413, 458)."""
        cfg = {"tts": {"ssml_enabled": True, "prosody_variation": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Hallo Welt.", "warning", 85, "-10%")
        assert 'rate="85%"' in ssml
        assert 'pitch="-10%"' in ssml
        assert "<prosody" in ssml
        assert "</prosody></speak>" in ssml

    def test_ssml_greeting_first_sentence_pause(self):
        """Erster Satz bei Begruessung bekommt Pause danach (Zeilen 436-439)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml(
                "Guten Morgen. Hier dein Briefing.", "greeting", 100
            )
        assert f'break time="{e.pause_greeting}ms"' in ssml

    def test_ssml_warning_emphasis_and_pause(self):
        """Warning: Pause vor erstem Satz + Emphasis bei Warn-Woertern (Zeilen 442-445)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Warnung: Fenster offen.", "warning", 100)
        assert f'break time="{e.pause_important}ms"' in ssml
        assert "<emphasis" in ssml

    def test_ssml_briefing_pause_between_sentences(self):
        """Briefing: Pause zwischen Saetzen (Zeilen 448-449)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Satz eins. Satz zwei. Satz drei.", "briefing", 100)
        # Pause_important zwischen briefing-Saetzen (nicht vor erstem)
        assert ssml.count(f'break time="{e.pause_important}ms"') >= 1

    def test_ssml_sentence_pause_between_sentences(self):
        """Pause zwischen Saetzen bei normalem Text (Zeilen 454-455)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Erster Satz. Zweiter Satz.", "casual", 100)
        assert f'break time="{e.pause_sentence}ms"' in ssml

    def test_ssml_no_prosody_when_defaults(self):
        """Kein prosody-Tag bei speed=100 und pitch=0% (Zeile 414-415)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Einfacher Text.", "casual", 100, "0%")
        assert ssml.startswith("<speak>")
        assert ssml.endswith("</speak>")
        assert "<prosody" not in ssml

    def test_ssml_english_title_lang_wrap(self):
        """Englische Titel werden mit <lang> gewrappt im SSML (Zeilen 423-425)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Guten Morgen, Sir.", "greeting", 100)
        assert '<lang xml:lang="en-US">' in ssml

    def test_ssml_xml_escape(self):
        """Sonderzeichen werden XML-escaped (Zeile 419)."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
            ssml = e._generate_ssml("Temperatur < 5°C & Warnung.", "casual", 100)
        assert "&lt;" in ssml
        assert "&amp;" in ssml


# ============================================================
# Phase 3C: Emotionale TTS-Tiefe
# ============================================================


class TestPhase3CEmotionSSML:
    """Tests fuer Emotion-basierte SSML-Anpassung."""

    def test_emotion_ssml_map_exists(self):
        """Emotion-SSML-Map ist definiert."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        assert hasattr(e, "_EMOTION_SSML_MAP")
        assert "amuesiert" in e._EMOTION_SSML_MAP
        assert "besorgt" in e._EMOTION_SSML_MAP
        assert "stolz" in e._EMOTION_SSML_MAP

    def test_enhance_with_emotion_neutral(self):
        """Neutral → keine Aenderung."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.enhance_with_emotion("Test", "neutral")
        assert "emotion" not in result

    def test_enhance_with_emotion_amuesiert(self):
        """Amuesiert → schnellere Rate und hoeherer Pitch."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.enhance_with_emotion("Das war witzig.", "amuesiert")
        assert result.get("emotion") == "amuesiert"
        assert result.get("emotion_rate") == "108%"
        assert result.get("emotion_pitch") == "+8%"

    def test_enhance_with_emotion_besorgt(self):
        """Besorgt → langsamere Rate."""
        cfg = {"tts": {"ssml_enabled": True}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.enhance_with_emotion("Warnung.", "besorgt")
        assert result.get("emotion") == "besorgt"
        assert result.get("emotion_rate") == "90%"

    def test_enhance_with_emotion_no_ssml(self):
        """Ohne SSML → Emotion wird trotzdem nicht gesetzt."""
        cfg = {"tts": {"ssml_enabled": False}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.enhance_with_emotion("Test", "amuesiert")
        # Ohne SSML kein Emotion-Override
        assert "emotion" not in result or result.get("emotion") is None


class TestPhase3CStreaming:
    """Tests fuer Satz-Level-Streaming."""

    def test_split_for_streaming_single(self):
        """Einzelner Satz → Liste mit einem Element."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.split_for_streaming("Guten Morgen.")
        assert len(result) >= 1

    def test_split_for_streaming_multiple(self):
        """Mehrere Saetze → Liste pro Satz."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.split_for_streaming("Erster Satz. Zweiter Satz. Dritter Satz.")
        assert len(result) >= 2

    def test_split_for_streaming_empty(self):
        """Leerer Text → leere Liste."""
        cfg = {"tts": {}, "volume": {}}
        with patch.object(_tts_mod, "yaml_config", cfg):
            e = TTSEnhancer()
        result = e.split_for_streaming("")
        assert result == []
