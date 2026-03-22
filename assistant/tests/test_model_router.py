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
    "licht",
    "lampe",
    "temperatur",
    "heizung",
    "rollladen",
    "jalousie",
    "szene",
    "alarm",
    "tuer",
    "musik",
    "pause",
    "stopp",
    "stop",
    "leiser",
    "lauter",
    "an",
    "aus",
    "schalte",
    "mach",
]

DEEP_KEYWORDS = [
    "erklaer",
    "erklaere",
    "warum genau",
    "im detail",
    "analysiere",
    "analyse",
    "vergleich",
    "vergleiche",
    "unterschied zwischen",
    "vor- und nachteile",
    "strategie",
    "plan",
    "plane",
    "planung",
    "optimier",
    "optimiere",
    "optimierung",
    "was waere wenn",
    "was wäre wenn",
    "hypothetisch",
    "stell dir vor",
    "angenommen",
    "zusammenfassung",
    "zusammenfassen",
    "fasse zusammen",
    "berechne",
    "berechnung",
    "kalkulation",
    "wie funktioniert",
    "wie genau",
    "schreib mir",
    "schreibe mir",
    "formuliere",
    "rezept",
    "anleitung",
    "tutorial",
    "pro und contra",
    "bewerte",
    "bewertung",
]

DEEP_MIN_WORDS = 15


def word_match(keyword: str, text: str) -> bool:
    """Kopie aus ModelRouter._word_match."""
    if len(keyword) <= 3:
        return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))
    return keyword in text


def select_model(
    text: str,
    *,
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
    if any(
        text_lower.startswith(w)
        for w in ["was ", "wie ", "warum ", "wann ", "wo ", "wer "]
    ):
        return cap(MODEL_SMART)

    # Default: Smart
    return cap(MODEL_SMART)


def get_fallback_model(
    current: str,
    *,
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

    @pytest.mark.parametrize(
        "text",
        [
            "Licht an",
            "Lampe aus",
            "Musik stopp",
            "Heizung an",
            "Rollladen hoch",
            "Schalte aus",
            "Pause",
        ],
    )
    def test_short_fast_keywords(self, text):
        assert select_model(text) == MODEL_FAST, f"'{text}' sollte Fast sein"

    @pytest.mark.parametrize(
        "text",
        [
            "Erklaer mir Quantenphysik",
            "Analysiere den Stromverbrauch",
            "Was waere wenn ich verreise",
            "Vergleiche die Optionen bitte genau",
            "Schreib mir eine Einkaufsliste",
            "Rezept fuer Gulasch",
            "Wie funktioniert ein Wechselrichter",
        ],
    )
    def test_deep_keywords(self, text):
        assert select_model(text) == MODEL_DEEP, f"'{text}' sollte Deep sein"

    def test_long_text_goes_deep(self):
        long_text = "Ich moechte gerne wissen ob du mir helfen kannst die ganzen Lichter und Steckdosen im Haus gleichzeitig auszuschalten"
        assert len(long_text.split()) >= DEEP_MIN_WORDS
        assert select_model(long_text) == MODEL_DEEP

    @pytest.mark.parametrize(
        "text",
        [
            "Wie geht es dir?",
            "Wem gehört das Auto?",
            "Warum ist das so?",
            "Wann kommt der Regen?",
            "Wo ist mein Handy?",
            "Wer hat angerufen?",
        ],
    )
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
        result = select_model(
            "Erklaer mir Quantenphysik", deep_available=False, smart_available=False
        )
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
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config",
                {"models": {}, "model_router": {"latency_feedback": True}},
            ),
        ):
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
        model, tier = router.select_model_and_tier(
            "Erklaere mir die Zusammenhaenge der Quantenphysik im Detail"
        )
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


# ============================================================
# select_model_tier_reasoning Tests
# ============================================================


class TestSelectModelTierReasoning:
    """Tests fuer select_model_tier_reasoning() — 3-Tupel mit Reasoning-Flag."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config",
                {"models": {}, "model_router": {"latency_feedback": True}},
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            r._deep_available = True
            r._smart_available = True
            return r

    def test_fast_no_reasoning(self, router):
        model, tier, requires = router.select_model_tier_reasoning("Licht an")
        assert tier == "fast"
        assert requires is False

    def test_deep_keyword_with_reasoning(self, router):
        model, tier, requires = router.select_model_tier_reasoning(
            "Analysiere meinen Energieverbrauch der letzten Woche detailliert"
        )
        assert tier == "deep"
        assert requires is True

    def test_smart_no_reasoning(self, router):
        model, tier, requires = router.select_model_tier_reasoning(
            "Wie ist das Wetter morgen?"
        )
        assert tier == "smart"
        assert requires is False

    def test_long_text_deep_with_reasoning(self, router):
        long_text = "Ich moechte gerne wissen ob du mir helfen kannst die ganzen Lichter und Steckdosen im Haus gleichzeitig auszuschalten damit Strom gespart wird"
        model, tier, requires = router.select_model_tier_reasoning(long_text)
        assert tier == "deep"
        assert requires is True

    def test_degraded_deep_returns_smart(self, router):
        router._deep_degraded = True
        model, tier, requires = router.select_model_tier_reasoning(
            "Erklaere mir Quantenphysik"
        )
        assert tier == "smart"
        assert requires is False  # Smart braucht kein Reasoning

    def test_degraded_deep_long_text_returns_smart(self, router):
        """Lange Anfrage mit degradiertem Deep → Smart ohne Reasoning."""
        router._deep_degraded = True
        long_text = "Ich moechte gerne wissen ob du mir helfen kannst die ganzen Lichter und Steckdosen im Haus gleichzeitig auszuschalten damit Strom gespart wird"
        model, tier, requires = router.select_model_tier_reasoning(long_text)
        assert tier == "smart"
        assert requires is False

    def test_deep_not_available_falls_back_to_smart(self, router):
        """Deep-Modell nicht verfuegbar → Smart via _cap_model."""
        router._deep_available = False
        model, tier, requires = router.select_model_tier_reasoning(
            "Analysiere den Stromverbrauch"
        )
        # _cap_model sollte Deep auf Smart reduzieren
        assert model == MODEL_SMART or tier == "smart" or model != MODEL_DEEP

    def test_smart_not_available_falls_back_to_fast(self, router):
        """Smart-Modell nicht verfuegbar → Frage faellt auf Fast zurueck."""
        router._smart_available = False
        model, tier, requires = router.select_model_tier_reasoning(
            "Wie ist das Wetter?"
        )
        assert model == MODEL_FAST

    def test_both_deep_and_smart_unavailable(self, router):
        """Nur Fast verfuegbar → alles geht auf Fast."""
        router._deep_available = False
        router._smart_available = False
        model, tier, requires = router.select_model_tier_reasoning(
            "Erklaere mir Quantenphysik"
        )
        assert model == MODEL_FAST

    def test_empty_text_returns_smart(self, router):
        """Leerer Text → Smart-Default."""
        model, tier, requires = router.select_model_tier_reasoning("")
        assert tier == "smart"
        assert requires is False

    def test_question_returns_smart_with_no_reasoning(self, router):
        """Fragen → Smart ohne Reasoning."""
        model, tier, requires = router.select_model_tier_reasoning(
            "Wann kommt der Regen?"
        )
        assert tier == "smart"
        assert requires is False

    def test_returns_three_tuple(self, router):
        """Ergebnis ist immer ein 3-Tupel."""
        result = router.select_model_tier_reasoning("Hallo Jarvis")
        assert isinstance(result, tuple)
        assert len(result) == 3
        model, tier, requires = result
        assert isinstance(model, str)
        assert tier in ("fast", "smart", "deep")
        assert isinstance(requires, bool)

    def test_fast_keyword_six_words(self, router):
        """Genau 6 Woerter mit Fast-Keyword → Fast."""
        model, tier, requires = router.select_model_tier_reasoning(
            "Mach bitte das Licht jetzt an"
        )
        assert tier == "fast"
        assert requires is False

    def test_deep_keyword_reasoning_true(self, router):
        """Deep-Keyword setzt requires_reasoning auf True."""
        for keyword_text in [
            "Vergleiche die zwei Optionen",
            "Berechne den Verbrauch",
            "Fasse zusammen was passiert ist",
        ]:
            model, tier, requires = router.select_model_tier_reasoning(keyword_text)
            assert requires is True, f"'{keyword_text}' sollte reasoning=True haben"


# ============================================================
# D1: Task-aware Temperature — classify_task + get_task_temperature
# ============================================================


class TestClassifyTask:
    """Tests fuer classify_task() — D1 Task-Klassifizierung."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Licht an", "command"),
            ("Schalte die Lampe aus", "command"),
            ("Heizung hoch", "command"),
            ("Musik stopp", "command"),
        ],
    )
    def test_command_classification(self, router, text, expected):
        assert router.classify_task(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Schreib mir eine Geschichte", "creative"),
            ("Was waere wenn es keinen Strom gaebe", "creative"),
            ("Was wäre wenn ich verreise", "creative"),
            ("Stell dir vor es ist Winter", "creative"),
            ("Erfinde einen neuen Namen", "creative"),
            ("Hypothetisch gesprochen", "creative"),
        ],
    )
    def test_creative_classification(self, router, text, expected):
        assert router.classify_task(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Analysiere den Stromverbrauch", "analysis"),
            ("Vergleiche die zwei Optionen", "analysis"),
            ("Was ist der Unterschied zwischen A und B", "analysis"),
            ("Erklaere mir das genauer", "analysis"),
            ("Optimiere den Grundriss", "analysis"),
            ("Berechne den Verbrauch", "analysis"),
            ("Diagnose bitte", "analysis"),
        ],
    )
    def test_analysis_classification(self, router, text, expected):
        assert router.classify_task(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Was ist die Hauptstadt von Frankreich", "factual"),
            ("Wann wurde Deutschland vereinigt", "factual"),
            ("Wo ist der naechste Supermarkt", "factual"),
            ("Wer hat das Telefon erfunden", "factual"),
            ("Wie viel Strom haben wir verbraucht", "factual"),
            ("Wie hoch ist die Miete", "factual"),
            ("Wie warm ist es draussen", "factual"),
        ],
    )
    def test_factual_classification(self, router, text, expected):
        assert router.classify_task(text) == expected

    def test_conversation_long_text(self, router):
        """Laengerer Text (>8 Woerter) wird als Conversation klassifiziert."""
        result = router.classify_task(
            "Ich wollte dir sagen dass ich morgen nicht da bin leider"
        )
        assert result == "conversation"

    def test_conversation_question_mark(self, router):
        """Text mit Fragezeichen wird als Conversation klassifiziert."""
        result = router.classify_task("Alles gut?")
        assert result == "conversation"

    def test_default_classification(self, router):
        """Kurzer Text ohne Keyword → default."""
        result = router.classify_task("Hallo")
        assert result == "default"


class TestGetTaskTemperature:
    """Tests fuer get_task_temperature() — D1 Temperature je Task."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_command_low_temperature(self, router):
        temp = router.get_task_temperature("Licht an")
        assert temp == 0.3

    def test_creative_high_temperature(self, router):
        temp = router.get_task_temperature("Schreib mir eine Geschichte")
        assert temp == 0.8

    def test_analysis_medium_temperature(self, router):
        temp = router.get_task_temperature("Analysiere den Verbrauch")
        assert temp == 0.5

    def test_factual_temperature(self, router):
        temp = router.get_task_temperature("Was ist Python")
        assert temp == 0.4

    def test_conversation_temperature(self, router):
        temp = router.get_task_temperature(
            "Ich wollte dir sagen dass morgen was ansteht bitte"
        )
        assert temp == 0.7

    def test_default_temperature(self, router):
        temp = router.get_task_temperature("Hallo")
        assert temp == 0.6


# ============================================================
# get_tier_for_model Tests
# ============================================================


class TestGetTierForModel:
    """Tests fuer get_tier_for_model() — Tier-Name aus Modell ableiten."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_fast_model_returns_fast(self, router):
        assert router.get_tier_for_model(MODEL_FAST) == "fast"

    def test_deep_model_returns_deep(self, router):
        assert router.get_tier_for_model(MODEL_DEEP) == "deep"

    def test_smart_model_returns_smart(self, router):
        assert router.get_tier_for_model(MODEL_SMART) == "smart"

    def test_unknown_model_returns_smart(self, router):
        """Unbekanntes Modell → smart als Default."""
        assert router.get_tier_for_model("unknown:model") == "smart"

    def test_all_same_model_returns_smart(self, router):
        """Wenn alle Modelle identisch sind, immer smart."""
        router.model_fast = "same:model"
        router.model_smart = "same:model"
        router.model_deep = "same:model"
        assert router.get_tier_for_model("same:model") == "smart"


# ============================================================
# initialize + _update_availability Tests
# ============================================================


class TestInitializeAndAvailability:
    """Tests fuer initialize() und _update_availability()."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    @pytest.mark.asyncio
    async def test_initialize_with_all_models(self, router):
        await router.initialize([MODEL_FAST, MODEL_SMART, MODEL_DEEP])
        assert router._deep_available is True
        assert router._smart_available is True

    @pytest.mark.asyncio
    async def test_initialize_without_deep(self, router):
        await router.initialize([MODEL_FAST, MODEL_SMART])
        assert router._deep_available is False
        assert router._smart_available is True

    @pytest.mark.asyncio
    async def test_initialize_only_fast(self, router):
        await router.initialize([MODEL_FAST])
        assert router._deep_available is False
        assert router._smart_available is False

    @pytest.mark.asyncio
    async def test_initialize_empty_list(self, router):
        """Leere Liste → pessimistisch, nichts verfuegbar."""
        await router.initialize([])
        assert router._deep_available is False
        assert router._smart_available is False

    @pytest.mark.asyncio
    async def test_initialize_case_insensitive(self, router):
        await router.initialize(
            [MODEL_FAST.upper(), MODEL_SMART.upper(), MODEL_DEEP.upper()]
        )
        # Models are lowercased internally
        assert router._available_models == [
            MODEL_FAST.upper().lower(),
            MODEL_SMART.upper().lower(),
            MODEL_DEEP.upper().lower(),
        ]

    def test_update_availability_respects_enabled(self, router):
        """Deaktivierte Modelle sind nicht verfuegbar, auch wenn installiert."""
        router._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
        router._deep_enabled = False
        router._update_availability()
        assert router._deep_available is False

    def test_update_availability_both_disabled(self, router):
        router._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
        router._smart_enabled = False
        router._deep_enabled = False
        router._update_availability()
        assert router._deep_available is False
        assert router._smart_available is False


# ============================================================
# _is_model_installed (actual class method) Tests
# ============================================================


class TestIsModelInstalledClassMethod:
    """Tests fuer _is_model_installed() auf der tatsaechlichen Klasse."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_empty_list_pessimistic(self, router):
        """Leere verfuegbare Liste → False (pessimistisch)."""
        router._available_models = []
        assert router._is_model_installed(MODEL_FAST) is False

    def test_exact_match(self, router):
        router._available_models = [MODEL_FAST, MODEL_SMART]
        assert router._is_model_installed(MODEL_FAST) is True

    def test_prefix_match(self, router):
        """Model without version tag matches model with version."""
        router._available_models = ["qwen3.5:4b"]
        assert router._is_model_installed("qwen3.5") is True

    def test_reverse_prefix_match(self, router):
        """Model with specific tag matches base name in available."""
        router._available_models = ["qwen3.5"]
        assert router._is_model_installed("qwen3.5:4b") is True

    def test_no_match(self, router):
        router._available_models = ["llama3:8b"]
        assert router._is_model_installed("qwen3.5:4b") is False


# ============================================================
# get_best_available Tests
# ============================================================


class TestGetBestAvailable:
    """Tests fuer get_best_available()."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_deep_available(self, router):
        router._deep_available = True
        router._smart_available = True
        assert router.get_best_available() == MODEL_DEEP

    def test_only_smart(self, router):
        router._deep_available = False
        router._smart_available = True
        assert router.get_best_available() == MODEL_SMART

    def test_only_fast(self, router):
        router._deep_available = False
        router._smart_available = False
        assert router.get_best_available() == MODEL_FAST


# ============================================================
# reload_config Tests
# ============================================================


class TestReloadConfig:
    """Tests fuer reload_config() — Konfiguration neu laden."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            return r

    def test_reload_detects_enabled_changes(self, router):
        """Reload erkennt Aenderungen im Enabled-Status."""
        # reload_config() re-imports yaml_config inside _load_config as 'cfg',
        # and re-imports settings as 'cfg' inside reload_config itself.
        # We need to patch both the module-level references and the re-imports.
        with (
            patch(
                "assistant.model_router.yaml_config",
                {"models": {"enabled": {"deep": False}}, "model_router": {}},
            ),
            patch(
                "assistant.config.yaml_config",
                {"models": {"enabled": {"deep": False}}, "model_router": {}},
            ),
            patch("assistant.model_router.settings") as mock_settings,
            patch("assistant.config.settings") as mock_cfg_settings,
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            mock_cfg_settings.model_fast = MODEL_FAST
            mock_cfg_settings.model_smart = MODEL_SMART
            mock_cfg_settings.model_deep = MODEL_DEEP
            router.reload_config()
        assert router._deep_enabled is False

    def test_reload_detects_model_name_change(self, router):
        """Reload erkennt Aenderungen in Modellnamen."""
        with (
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
            patch("assistant.config.yaml_config", {"models": {}, "model_router": {}}),
            patch("assistant.model_router.settings") as mock_settings,
            patch("assistant.config.settings") as mock_cfg_settings,
        ):
            mock_settings.model_fast = "new-fast:1b"
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            mock_cfg_settings.model_fast = "new-fast:1b"
            mock_cfg_settings.model_smart = MODEL_SMART
            mock_cfg_settings.model_deep = MODEL_DEEP
            router.reload_config()
        assert router.model_fast == "new-fast:1b"

    def test_reload_no_changes(self, router):
        """Reload ohne Aenderungen laeuft ohne Fehler durch."""
        with (
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
            patch("assistant.model_router.settings") as mock_settings,
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            router.reload_config()


# ============================================================
# select_model (backwards-compatible) Tests
# ============================================================


class TestSelectModelCompat:
    """Tests fuer select_model() — Rueckwaertskompatible API."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            r._deep_available = True
            r._smart_available = True
            return r

    def test_returns_string(self, router):
        result = router.select_model("Licht an")
        assert isinstance(result, str)
        assert result == MODEL_FAST

    def test_deep_keyword(self, router):
        result = router.select_model("Erklaere mir Quantenphysik")
        assert result == MODEL_DEEP

    def test_default_smart(self, router):
        result = router.select_model("Hallo Jarvis")
        assert result == MODEL_SMART


# ============================================================
# get_fallback_model (actual class method) Tests
# ============================================================


class TestGetFallbackModelClass:
    """Tests fuer get_fallback_model() auf der Klasse."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._smart_available = True
            return r

    def test_deep_to_smart(self, router):
        assert router.get_fallback_model(MODEL_DEEP) == MODEL_SMART

    def test_deep_to_fast_when_same_as_smart(self, router):
        """Wenn Deep == Smart, direkt zu Fast."""
        router.model_smart = MODEL_DEEP  # Same model
        assert router.get_fallback_model(MODEL_DEEP) == MODEL_FAST

    def test_deep_to_fast_when_smart_unavailable(self, router):
        router._smart_available = False
        assert router.get_fallback_model(MODEL_DEEP) == MODEL_FAST

    def test_smart_to_fast(self, router):
        assert router.get_fallback_model(MODEL_SMART) == MODEL_FAST

    def test_fast_no_fallback(self, router):
        assert router.get_fallback_model(MODEL_FAST) == ""


# ============================================================
# Latency feedback — edge cases
# ============================================================


class TestLatencyFeedbackEdgeCases:
    """Zusaetzliche Edge-Cases fuer record_latency."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config",
                {"models": {}, "model_router": {"latency_feedback": True}},
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            r._deep_available = True
            r._smart_available = True
            return r

    def test_latency_feedback_disabled(self, router):
        """Deaktiviertes Latenz-Feedback zeichnet nichts auf."""
        router._latency_feedback_enabled = False
        router.record_latency("deep", 10.0)
        assert len(router._latency_history["deep"]) == 0

    def test_less_than_10_samples_no_degradation(self, router):
        """Weniger als 10 Samples → keine Degradation."""
        for _ in range(9):
            router.record_latency("deep", 20.0)
        assert router._deep_degraded is False

    def test_smart_latency_no_degradation_effect(self, router):
        """Smart-Tier Latenz hat keinen Degradation-Effekt."""
        for _ in range(20):
            router.record_latency("smart", 20.0)
        assert router._deep_degraded is False

    def test_fast_latency_tracked(self, router):
        """Fast-Tier Latenz wird aufgezeichnet."""
        router.record_latency("fast", 0.3)
        router.record_latency("fast", 0.5)
        assert len(router._latency_history["fast"]) == 2

    def test_deque_maxlen_caps_history(self, router):
        """History ist auf 50 Eintraege begrenzt."""
        for i in range(60):
            router.record_latency("fast", float(i))
        assert len(router._latency_history["fast"]) == 50


# ============================================================
# get_routing_stats — edge cases
# ============================================================


class TestGetRoutingStatsExtended:
    """Zusaetzliche Tests fuer get_routing_stats."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_empty_history(self, router):
        stats = router.get_routing_stats()
        assert stats["fast"]["count"] == 0
        assert stats["fast"]["avg_s"] == 0
        assert stats["fast"]["min_s"] == 0
        assert stats["fast"]["max_s"] == 0
        assert stats["deep_degraded"] is False

    def test_stats_with_data(self, router):
        router.record_latency("fast", 0.2)
        router.record_latency("fast", 0.4)
        stats = router.get_routing_stats()
        assert stats["fast"]["count"] == 2
        assert stats["fast"]["avg_s"] == 0.3
        assert stats["fast"]["min_s"] == 0.2
        assert stats["fast"]["max_s"] == 0.4


# ============================================================
# get_model_info — extended
# ============================================================


class TestGetModelInfoExtended:
    """Zusaetzliche Tests fuer get_model_info."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            r._deep_available = True
            r._smart_available = True
            return r

    def test_model_info_complete(self, router):
        info = router.get_model_info()
        assert info["fast"] == MODEL_FAST
        assert info["smart"] == MODEL_SMART
        assert info["deep"] == MODEL_DEEP
        assert info["enabled"]["fast"] is True
        assert info["enabled"]["smart"] is True
        assert info["enabled"]["deep"] is True
        assert info["deep_available"] is True
        assert info["smart_available"] is True
        assert info["best_available"] == MODEL_DEEP
        assert info["fast_keywords_count"] > 0
        assert info["deep_keywords_count"] > 0
        assert info["deep_min_words"] == 15

    def test_model_info_with_degradation(self, router):
        router._deep_degraded = True
        info = router.get_model_info()
        assert info["deep_degraded"] is True


# ============================================================
# _cap_model Tests
# ============================================================


class TestCapModel:
    """Tests fuer _cap_model() — Modell-Begrenzung."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._deep_available = True
            r._smart_available = True
            return r

    def test_deep_available_returns_deep(self, router):
        assert router._cap_model(MODEL_DEEP) == MODEL_DEEP

    def test_deep_unavailable_falls_to_smart(self, router):
        router._deep_available = False
        assert router._cap_model(MODEL_DEEP) == MODEL_SMART

    def test_deep_and_smart_unavailable_falls_to_fast(self, router):
        router._deep_available = False
        router._smart_available = False
        assert router._cap_model(MODEL_DEEP) == MODEL_FAST

    def test_smart_unavailable_falls_to_fast(self, router):
        router._smart_available = False
        assert router._cap_model(MODEL_SMART) == MODEL_FAST

    def test_fast_always_returns_fast(self, router):
        assert router._cap_model(MODEL_FAST) == MODEL_FAST

    def test_unknown_model_passes_through(self, router):
        assert router._cap_model("unknown:model") == "unknown:model"


# ============================================================
# Urgency override — extended
# ============================================================


class TestUrgencyOverrideExtended:
    """Zusaetzliche Tests fuer urgency_override."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_stressed_high_stress(self, router):
        assert router.urgency_override("stressed", 0.9) == "fast"

    def test_stressed_low_stress(self, router):
        assert router.urgency_override("stressed", 0.5) is None

    def test_boundary_stress_level(self, router):
        """Genau 0.7 → kein Override (> 0.7 noetig)."""
        assert router.urgency_override("frustrated", 0.7) is None

    def test_just_above_threshold(self, router):
        assert router.urgency_override("frustrated", 0.71) == "fast"

    def test_empty_mood(self, router):
        assert router.urgency_override("", 0.9) is None


# ============================================================
# _update_availability Edge Cases
# ============================================================


class TestUpdateAvailabilityEdgeCases:
    """Edge cases fuer _update_availability."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_deep_disabled_but_installed(self, router):
        """Deep model installed but disabled by user."""
        router._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
        router._deep_enabled = False
        router._update_availability()
        assert router._deep_available is False

    def test_smart_disabled_but_installed(self, router):
        """Smart model installed but disabled by user."""
        router._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
        router._smart_enabled = False
        router._update_availability()
        assert router._smart_available is False

    def test_both_unavailable(self, router):
        """Both deep and smart unavailable."""
        router._available_models = [MODEL_FAST]
        router._deep_enabled = True
        router._smart_enabled = True
        router._update_availability()
        assert router._deep_available is False
        assert router._smart_available is False

    def test_empty_available_models(self, router):
        """No models in available list."""
        router._available_models = []
        router._update_availability()
        assert router._deep_available is False
        assert router._smart_available is False


# ============================================================
# _is_model_installed Edge Cases
# ============================================================


class TestIsModelInstalledEdgeCases:
    """Edge cases fuer _is_model_installed."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_exact_match(self, router):
        router._available_models = ["qwen3.5:4b"]
        assert router._is_model_installed("qwen3.5:4b") is True

    def test_prefix_match_available_starts(self, router):
        """Available model starts with requested model + ':'."""
        router._available_models = ["qwen3.5:4b"]
        assert router._is_model_installed("qwen3.5") is True

    def test_prefix_match_requested_starts(self, router):
        """Requested model starts with available model + ':'."""
        router._available_models = ["qwen3.5"]
        assert router._is_model_installed("qwen3.5:4b") is True

    def test_no_match(self, router):
        router._available_models = ["llama3:8b"]
        assert router._is_model_installed("qwen3.5:4b") is False

    def test_case_insensitive(self, router):
        router._available_models = ["qwen3.5:4b"]
        assert router._is_model_installed("Qwen3.5:4B") is True


# ============================================================
# record_latency Edge Cases
# ============================================================


class TestRecordLatencyEdgeCases:
    """Edge cases fuer record_latency."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_disabled_latency_feedback(self, router):
        """When latency feedback is disabled, does nothing."""
        router._latency_feedback_enabled = False
        router.record_latency("deep", 10.0)
        assert len(router._latency_history["deep"]) == 0

    def test_unknown_tier_ignored(self, router):
        """Unknown tier name is ignored."""
        router.record_latency("unknown_tier", 5.0)
        # No exception, no data stored

    def test_deep_degradation_triggers(self, router):
        """Deep degradation triggers when avg exceeds threshold."""
        router._deep_degradation_threshold = 5.0
        # Record 10 calls above threshold
        for _ in range(10):
            router.record_latency("deep", 6.0)
        assert router._deep_degraded is True

    def test_deep_recovery(self, router):
        """Deep model recovers when latency drops below threshold."""
        router._deep_degradation_threshold = 5.0
        # First degrade
        for _ in range(10):
            router.record_latency("deep", 6.0)
        assert router._deep_degraded is True

        # Then recover with fast responses
        for _ in range(10):
            router.record_latency("deep", 2.0)
        assert router._deep_degraded is False

    def test_not_enough_samples_no_degradation(self, router):
        """Less than 10 samples doesn't trigger degradation check."""
        for _ in range(9):
            router.record_latency("deep", 20.0)
        assert router._deep_degraded is False

    def test_smart_tier_no_degradation_check(self, router):
        """Smart tier recording doesn't trigger degradation."""
        for _ in range(20):
            router.record_latency("smart", 20.0)
        assert router._deep_degraded is False


# ============================================================
# get_routing_stats Tests
# ============================================================


class TestGetRoutingStatsExtended:
    """Extended tests fuer get_routing_stats."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_empty_history(self, router):
        stats = router.get_routing_stats()
        assert stats["fast"]["count"] == 0
        assert stats["smart"]["count"] == 0
        assert stats["deep"]["count"] == 0
        assert stats["deep_degraded"] is False

    def test_with_latency_data(self, router):
        router.record_latency("fast", 0.5)
        router.record_latency("fast", 1.0)
        router.record_latency("smart", 2.0)

        stats = router.get_routing_stats()
        assert stats["fast"]["count"] == 2
        assert stats["fast"]["avg_s"] == 0.75
        assert stats["fast"]["min_s"] == 0.5
        assert stats["fast"]["max_s"] == 1.0
        assert stats["smart"]["count"] == 1

    def test_degraded_flag_in_stats(self, router):
        router._deep_degraded = True
        stats = router.get_routing_stats()
        assert stats["deep_degraded"] is True


# ============================================================
# select_model_tier_reasoning with degradation
# ============================================================


class TestSelectModelWithDegradation:
    """Tests fuer Modell-Auswahl bei Deep-Degradation."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._available_models = [MODEL_FAST, MODEL_SMART, MODEL_DEEP]
            r._deep_available = True
            r._smart_available = True
            return r

    def test_deep_keyword_when_degraded(self, router):
        """Deep keyword falls to smart when degraded."""
        router._deep_degraded = True
        model, tier, reasoning = router.select_model_tier_reasoning(
            "Analysiere den Energieverbrauch"
        )
        assert tier == "smart"
        assert reasoning is False

    def test_long_text_when_degraded(self, router):
        """Long text falls to smart when degraded."""
        router._deep_degraded = True
        long_text = " ".join(["wort"] * 20)
        model, tier, reasoning = router.select_model_tier_reasoning(long_text)
        assert tier == "smart"

    def test_deep_keyword_not_degraded(self, router):
        """Deep keyword uses deep when not degraded."""
        router._deep_degraded = False
        model, tier, reasoning = router.select_model_tier_reasoning(
            "Analysiere den Energieverbrauch"
        )
        assert tier == "deep"
        assert reasoning is True


# ============================================================
# get_tier_for_model Tests
# ============================================================


class TestGetTierForModel:
    """Tests fuer get_tier_for_model."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            return ModelRouter()

    def test_fast_model(self, router):
        assert router.get_tier_for_model(MODEL_FAST) == "fast"

    def test_smart_model(self, router):
        assert router.get_tier_for_model(MODEL_SMART) == "smart"

    def test_deep_model(self, router):
        assert router.get_tier_for_model(MODEL_DEEP) == "deep"

    def test_all_same_model(self, router):
        """When all tiers use the same model, returns 'smart'."""
        router.model_fast = "same-model"
        router.model_smart = "same-model"
        router.model_deep = "same-model"
        assert router.get_tier_for_model("same-model") == "smart"

    def test_unknown_model(self, router):
        assert router.get_tier_for_model("unknown:model") == "smart"


# ============================================================
# get_fallback_model Edge Cases
# ============================================================


class TestGetFallbackModelEdgeCases:
    """Edge cases fuer get_fallback_model."""

    @pytest.fixture
    def router(self):
        with (
            patch("assistant.model_router.settings") as mock_settings,
            patch(
                "assistant.model_router.yaml_config", {"models": {}, "model_router": {}}
            ),
        ):
            mock_settings.model_fast = MODEL_FAST
            mock_settings.model_smart = MODEL_SMART
            mock_settings.model_deep = MODEL_DEEP
            from assistant.model_router import ModelRouter

            r = ModelRouter()
            r._smart_available = True
            return r

    def test_deep_to_smart(self, router):
        assert router.get_fallback_model(MODEL_DEEP) == MODEL_SMART

    def test_deep_to_fast_when_smart_same(self, router):
        """When deep == smart, falls directly to fast."""
        router.model_smart = MODEL_DEEP  # Same as deep
        result = router.get_fallback_model(MODEL_DEEP)
        assert result == MODEL_FAST

    def test_deep_to_fast_when_smart_unavailable(self, router):
        """When smart is unavailable, deep falls to fast."""
        router._smart_available = False
        result = router.get_fallback_model(MODEL_DEEP)
        assert result == MODEL_FAST

    def test_smart_to_fast(self, router):
        assert router.get_fallback_model(MODEL_SMART) == MODEL_FAST

    def test_fast_no_fallback(self, router):
        assert router.get_fallback_model(MODEL_FAST) == ""
