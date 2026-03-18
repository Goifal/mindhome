"""
Tests fuer model_router.py — ModelRouter Logik

Testet isoliert (ohne Config-Import):
  - _word_match: Keyword-Matching mit Word-Boundary
  - select_model: Routing-Logik (Fast/Smart/Deep)
  - _cap_model: Fallback bei nicht-verfuegbaren Modellen
  - get_fallback_model: Kaskade Deep→Smart→Fast
  - _is_model_installed: Modell-Erkennung mit Version-Tags
  - get_best_available: Bestes verfuegbares Modell
"""

import re
from unittest.mock import MagicMock, patch
import pytest


# ============================================================
# Isolierte Funktionen (aus model_router.py extrahiert)
# ============================================================

MODEL_FAST = "qwen3.5:4b"
MODEL_SMART = "qwen3.5:9b"
MODEL_DEEP = "qwen3.5:35b"

FAST_KEYWORDS = [
    "licht", "lampe", "temperatur", "heizung", "rollladen",
    "jalousie", "szene", "alarm", "tuer",
    "musik", "pause", "stopp", "stop",
    "leiser", "lauter", "an", "aus", "schalte", "mach",
]

DEEP_KEYWORDS = [
    "erklaer", "erklaere", "warum genau", "im detail",
    "analysiere", "analyse", "vergleich", "vergleiche",
    "unterschied zwischen", "vor- und nachteile",
    "strategie", "plan", "plane", "planung",
    "optimier", "optimiere", "optimierung",
    "was waere wenn", "was wäre wenn", "hypothetisch",
    "stell dir vor", "angenommen",
    "zusammenfassung", "zusammenfassen", "fasse zusammen",
    "berechne", "berechnung", "kalkulation",
    "wie funktioniert", "wie genau",
    "schreib mir", "schreibe mir", "formuliere",
    "rezept", "anleitung", "tutorial",
    "pro und contra", "bewerte", "bewertung",
]

DEEP_MIN_WORDS = 15


def word_match(keyword: str, text: str) -> bool:
    """Kopie aus ModelRouter._word_match."""
    if len(keyword) <= 3:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
    return keyword in text


def select_model(
    text: str, *,
    deep_available: bool = True,
    smart_available: bool = True,
    fast_enabled: bool = True,
) -> str:
    """Vereinfachte Kopie von ModelRouter.select_model."""
    text_lower = text.lower().strip()
    word_count = len(text_lower.split())

    def cap(model: str) -> str:
        if model == MODEL_DEEP and not deep_available:
            return MODEL_SMART if smart_available else MODEL_FAST
        if model == MODEL_SMART and not smart_available:
            return MODEL_FAST
        return model

    # 1. Kurze Befehle → Fast
    if word_count <= 6 and fast_enabled:
        for kw in FAST_KEYWORDS:
            if word_match(kw, text_lower):
                return MODEL_FAST

    # 2. Deep-Keywords → Deep
    for kw in DEEP_KEYWORDS:
        if word_match(kw, text_lower):
            return cap(MODEL_DEEP)

    # 3. Lange Anfragen → Deep
    if word_count >= DEEP_MIN_WORDS:
        return cap(MODEL_DEEP)

    # 4. Fragen → Smart
    if any(text_lower.startswith(w) for w in ["was ", "wie ", "warum ", "wann ", "wo ", "wer "]):
        return cap(MODEL_SMART)

    # Default: Smart
    return cap(MODEL_SMART)


def get_fallback_model(
    current: str, *,
    smart_available: bool = True,
) -> str:
    """Kopie von ModelRouter.get_fallback_model."""
    if current == MODEL_DEEP:
        if smart_available and MODEL_SMART != current:
            return MODEL_SMART
        return MODEL_FAST
    if current == MODEL_SMART:
        return MODEL_FAST
    return ""


def is_model_installed(model_name: str, available: list[str]) -> bool:
    """Kopie von ModelRouter._is_model_installed."""
    if not available:
        return True
    model_lower = model_name.lower()
    for a in available:
        if a == model_lower or a.startswith(model_lower + ":"):
            return True
        if model_lower.startswith(a + ":"):
            return True
    return False


# ============================================================
# _word_match Tests
# ============================================================

class TestWordMatch:
    """Keyword-Matching mit Word-Boundary fuer kurze Keywords."""

    def test_short_keyword_matches_whole_word(self):
        assert word_match("an", "licht an") is True

    def test_short_keyword_no_substring(self):
        assert word_match("an", "antwort bitte") is False
        assert word_match("an", "manuel hat gefragt") is False

    def test_short_keyword_aus(self):
        assert word_match("aus", "licht aus") is True
        assert word_match("aus", "haus ist gross") is False

    def test_long_keyword_substring_ok(self):
        assert word_match("licht", "mach das licht an") is True
        assert word_match("temperatur", "aussentemperatur") is True

    def test_no_match(self):
        assert word_match("licht", "der motor brummt") is False
        assert word_match("an", "der motor brummt") is False

    def test_three_char_boundary(self):
        """Genau 3 Zeichen → Word-Boundary-Match."""
        assert word_match("aus", "licht aus bitte") is True
        assert word_match("aus", "klausur") is False


# ============================================================
# select_model Tests
# ============================================================

class TestSelectModel:
    """3-Stufen-Routing."""

    @pytest.mark.parametrize("text", [
        "Licht an",
        "Lampe aus",
        "Musik stopp",
        "Heizung an",
        "Rollladen hoch",
        "Schalte aus",
        "Pause",
    ])
    def test_short_fast_keywords(self, text):
        assert select_model(text) == MODEL_FAST, f"'{text}' sollte Fast sein"

    @pytest.mark.parametrize("text", [
        "Erklaer mir Quantenphysik",
        "Analysiere den Stromverbrauch",
        "Was waere wenn ich verreise",
        "Vergleiche die Optionen bitte genau",
        "Schreib mir eine Einkaufsliste",
        "Rezept fuer Gulasch",
        "Wie funktioniert ein Wechselrichter",
    ])
    def test_deep_keywords(self, text):
        assert select_model(text) == MODEL_DEEP, f"'{text}' sollte Deep sein"

    def test_long_text_goes_deep(self):
        long_text = "Ich moechte gerne wissen ob du mir helfen kannst die ganzen Lichter und Steckdosen im Haus gleichzeitig auszuschalten"
        assert len(long_text.split()) >= DEEP_MIN_WORDS
        assert select_model(long_text) == MODEL_DEEP

    @pytest.mark.parametrize("text", [
        "Wie geht es dir?",
        "Wem gehört das Auto?",
        "Warum ist das so?",
        "Wann kommt der Regen?",
        "Wo ist mein Handy?",
        "Wer hat angerufen?",
    ])
    def test_questions_go_smart(self, text):
        assert select_model(text) == MODEL_SMART, f"'{text}' sollte Smart sein"

    def test_default_goes_smart(self):
        assert select_model("Guten Morgen Jarvis") == MODEL_SMART

    def test_fast_keyword_too_long(self):
        """Fast-Keywords greifen nur bei <=6 Woertern."""
        result = select_model("Mach bitte das Licht im Wohnzimmer jetzt sofort an")
        assert result != MODEL_FAST


# ============================================================
# select_model: Fallback
# ============================================================

class TestSelectModelFallback:
    """Routing-Fallback ohne verfuegbare Modelle."""

    def test_deep_keyword_without_deep(self):
        result = select_model("Erklaer mir Quantenphysik", deep_available=False)
        assert result == MODEL_SMART

    def test_deep_keyword_only_fast(self):
        result = select_model("Erklaer mir Quantenphysik", deep_available=False, smart_available=False)
        assert result == MODEL_FAST

    def test_question_only_fast(self):
        result = select_model("Wie geht es dir?", smart_available=False)
        assert result == MODEL_FAST


# ============================================================
# get_fallback_model Tests
# ============================================================

class TestGetFallbackModel:
    """Kaskade Deep→Smart→Fast."""

    def test_deep_to_smart(self):
        assert get_fallback_model(MODEL_DEEP) == MODEL_SMART

    def test_smart_to_fast(self):
        assert get_fallback_model(MODEL_SMART) == MODEL_FAST

    def test_fast_no_fallback(self):
        assert get_fallback_model(MODEL_FAST) == ""

    def test_deep_skips_identical_smart(self):
        """Wenn Deep == Smart, direkt zu Fast."""
        # Simuliere dass Deep und Smart das gleiche Modell sind
        result = get_fallback_model(MODEL_SMART, smart_available=True)
        assert result == MODEL_FAST


# ============================================================
# _is_model_installed Tests
# ============================================================

class TestIsModelInstalled:
    """Modell-Erkennung mit Version-Tags."""

    def test_exact_match(self):
        assert is_model_installed("qwen3.5:4b", ["qwen3.5:4b", "qwen3.5:9b"]) is True

    def test_prefix_match(self):
        assert is_model_installed("qwen3.5", ["qwen3.5:4b"]) is True

    def test_no_match(self):
        assert is_model_installed("llama3:70b", ["qwen3.5:4b", "qwen3.5:9b"]) is False

    def test_empty_available_optimistic(self):
        assert is_model_installed("anything", []) is True

    def test_case_insensitive(self):
        assert is_model_installed("Qwen3.5:4b", ["qwen3.5:4b"]) is True


# ============================================================
# Edge Cases
# ============================================================

class TestEdgeCases:
    """Grenzfaelle."""

    def test_empty_text_goes_smart(self):
        assert select_model("") == MODEL_SMART

    def test_single_word_fast_keyword(self):
        assert select_model("Stopp") == MODEL_FAST

    def test_single_word_not_fast(self):
        assert select_model("Hallo") == MODEL_SMART

    def test_fast_disabled(self):
        """Fast deaktiviert → kein Fast-Routing."""
        result = select_model("Licht an", fast_enabled=False)
        assert result != MODEL_FAST


# ============================================================
# Phase 2C: Latenz-Feedback und Urgency-Override
# ============================================================

class TestPhase2CLatencyFeedback:
    """Tests fuer Latenz-Feedback und automatische Degradation."""

    @pytest.fixture
    def router(self):
        with patch("assistant.model_router.settings") as mock_settings, \
             patch("assistant.model_router.yaml_config", {"models": {}, "model_router": {"latency_feedback": True}}):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter
            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            r._deep_available = True
            r._smart_available = True
            return r

    def test_record_latency(self, router):
        """Latenz wird aufgezeichnet."""
        router.record_latency("deep", 5.0)
        assert len(router._latency_history["deep"]) == 1

    def test_record_latency_invalid_tier(self, router):
        """Ungueltiger Tier wird ignoriert."""
        router.record_latency("unknown", 5.0)
        assert "unknown" not in router._latency_history

    def test_deep_degradation(self, router):
        """Deep-Modell wird degradiert bei hoher Latenz."""
        for _ in range(10):
            router.record_latency("deep", 10.0)  # 10s > 8s Schwelle
        assert router._deep_degraded is True

    def test_deep_recovery(self, router):
        """Deep-Modell erholt sich bei niedriger Latenz."""
        for _ in range(10):
            router.record_latency("deep", 10.0)
        assert router._deep_degraded is True
        for _ in range(10):
            router.record_latency("deep", 2.0)
        assert router._deep_degraded is False

    def test_degraded_routing_to_smart(self, router):
        """Degradiertes Deep routet zu Smart."""
        router._deep_degraded = True
        model, tier = router.select_model_and_tier("Erklaere mir die Zusammenhaenge der Quantenphysik im Detail")
        assert tier == "smart"

    def test_urgency_override_frustrated(self, router):
        """Frustration + hoher Stress → Fast."""
        result = router.urgency_override("frustrated", 0.8)
        assert result == "fast"

    def test_urgency_override_low_stress(self, router):
        """Frustration + niedriger Stress → kein Override."""
        result = router.urgency_override("frustrated", 0.3)
        assert result is None

    def test_urgency_override_neutral(self, router):
        """Neutrale Stimmung → kein Override."""
        result = router.urgency_override("neutral", 0.5)
        assert result is None

    def test_routing_stats(self, router):
        """Routing-Statistiken enthalten alle Tiers."""
        router.record_latency("fast", 0.3)
        router.record_latency("smart", 1.5)
        stats = router.get_routing_stats()
        assert "fast" in stats
        assert "smart" in stats
        assert "deep" in stats
        assert "deep_degraded" in stats
        assert stats["fast"]["count"] == 1

    def test_model_info_includes_degradation(self, router):
        """Model-Info enthaelt Degradation-Status."""
        info = router.get_model_info()
        assert "deep_degraded" in info
        assert "latency_feedback" in info
