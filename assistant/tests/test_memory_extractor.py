"""
Tests fuer Memory Extractor — LLM-basierte Fakten-Extraktion aus Gespraechen.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.memory_extractor import (
    CATEGORY_CONFIDENCE,
    _DEFAULT_MAX_LENGTH as MAX_CONVERSATION_LENGTH,
    _DEFAULT_MIN_WORDS as MIN_CONVERSATION_WORDS,
    MemoryExtractor,
)
from assistant.semantic_memory import SemanticFact


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ollama_mock():
    """OllamaClient Mock."""
    client = AsyncMock()
    client.chat = AsyncMock(return_value={
        "message": {"content": "[]"},
    })
    return client


@pytest.fixture
def semantic_mock():
    """SemanticMemory Mock."""
    sm = AsyncMock()
    sm.store_fact = AsyncMock(return_value=True)
    return sm


@pytest.fixture
def extractor(ollama_mock, semantic_mock):
    """MemoryExtractor mit gemockten Dependencies."""
    return MemoryExtractor(ollama=ollama_mock, semantic_memory=semantic_mock)


# =====================================================================
# _should_extract (Filter-Logik)
# =====================================================================


class TestShouldExtract:
    """Tests fuer die Entscheidung ob extrahiert werden soll."""

    def test_normal_conversation_should_extract(self, extractor):
        assert extractor._should_extract(
            "Ich arbeite heute von zu Hause aus am Projekt Aurora",
            "Verstanden, viel Erfolg mit Projekt Aurora.",
        ) is True

    def test_short_text_no_extract(self, extractor):
        # Weniger als MIN_CONVERSATION_WORDS
        assert extractor._should_extract("Hallo", "Hi") is False

    def test_command_only_no_extract(self, extractor):
        assert extractor._should_extract("licht an", "Erledigt.") is False
        assert extractor._should_extract("Stopp", "OK.") is False
        assert extractor._should_extract("gute nacht", "Schlaf gut.") is False
        assert extractor._should_extract("pause", "OK.") is False

    def test_command_case_insensitive(self, extractor):
        assert extractor._should_extract("Licht An", "OK.") is False
        assert extractor._should_extract("GUTEN MORGEN", "Morgen!") is False

    def test_longer_text_with_facts_should_extract(self, extractor):
        assert extractor._should_extract(
            "Meine Mutter kommt naechstes Wochenende zu Besuch und sie mag es warm",
            "Ich merke mir das. Soll ich die Heizung hochdrehen?",
        ) is True


# =====================================================================
# _format_conversation
# =====================================================================


class TestFormatConversation:
    """Tests fuer die Konversations-Formatierung."""

    def test_basic_format(self, extractor):
        result = extractor._format_conversation(
            user_text="Ich mag 21 Grad",
            assistant_response="Notiert.",
            person="Max",
            context=None,
        )
        assert "Person: Max" in result
        assert "Max: Ich mag 21 Grad" in result
        assert "Jarvis: Notiert." in result

    def test_format_with_context(self, extractor):
        result = extractor._format_conversation(
            user_text="Es ist zu kalt hier",
            assistant_response="Heizung wird hochgedreht.",
            person="Lisa",
            context={"room": "Wohnzimmer", "time": {"datetime": "2026-02-20 20:00"}},
        )
        assert "Raum: Wohnzimmer" in result
        assert "Zeit: 2026-02-20 20:00" in result
        assert "Lisa:" in result

    def test_format_unknown_person(self, extractor):
        result = extractor._format_conversation(
            user_text="Test",
            assistant_response="OK",
            person="unknown",
            context=None,
        )
        # "unknown" soll nicht als Person-Zeile erscheinen
        assert "Person: unknown" not in result

    def test_format_truncates_long_text(self, extractor):
        long_text = "A" * (MAX_CONVERSATION_LENGTH + 500)
        result = extractor._format_conversation(
            user_text=long_text,
            assistant_response="OK",
            person="Max",
            context=None,
        )
        assert len(result) <= MAX_CONVERSATION_LENGTH


# =====================================================================
# _parse_facts (LLM-Output Parsing)
# =====================================================================


class TestParseFacts:
    """Tests fuer das Parsen der LLM-Antwort."""

    def test_parse_valid_json_array(self, extractor):
        output = json.dumps([
            {"content": "Max mag 21 Grad", "category": "preference", "person": "Max"},
            {"content": "Lisa hat Laktose-Intoleranz", "category": "health", "person": "Lisa"},
        ])
        result = extractor._parse_facts(output)
        assert len(result) == 2
        assert result[0]["content"] == "Max mag 21 Grad"
        assert result[1]["category"] == "health"

    def test_parse_empty_array(self, extractor):
        result = extractor._parse_facts("[]")
        assert result == []

    def test_parse_json_with_surrounding_text(self, extractor):
        output = 'Hier sind die Fakten:\n[{"content": "Test Fakt", "category": "general", "person": "Max"}]\nDas wars.'
        result = extractor._parse_facts(output)
        assert len(result) == 1
        assert result[0]["content"] == "Test Fakt"

    def test_parse_invalid_json(self, extractor):
        result = extractor._parse_facts("Das ist kein JSON")
        assert result == []

    def test_parse_filters_empty_content(self, extractor):
        output = json.dumps([
            {"content": "Guter Fakt", "category": "general", "person": "Max"},
            {"content": "", "category": "general", "person": "Max"},
            {"category": "general", "person": "Max"},  # kein content
        ])
        result = extractor._parse_facts(output)
        assert len(result) == 1
        assert result[0]["content"] == "Guter Fakt"

    def test_parse_non_dict_items_filtered(self, extractor):
        output = json.dumps([
            {"content": "Valid", "category": "general", "person": "Max"},
            "string item",
            42,
            None,
        ])
        result = extractor._parse_facts(output)
        assert len(result) == 1

    def test_parse_not_a_list(self, extractor):
        output = json.dumps({"content": "Single object"})
        result = extractor._parse_facts(output)
        assert result == []

    def test_parse_json_with_markdown_code_block(self, extractor):
        # LLMs geben manchmal JSON in Markdown-Bloecken zurueck
        output = '```json\n[{"content": "Fakt", "category": "general", "person": "Max"}]\n```'
        result = extractor._parse_facts(output)
        assert len(result) == 1


# =====================================================================
# extract_and_store (Haupt-Methode)
# =====================================================================


class TestExtractAndStore:
    """Tests fuer den vollstaendigen Extraktions-Workflow."""

    @pytest.mark.asyncio
    async def test_extract_stores_facts(self, extractor, ollama_mock, semantic_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": json.dumps([
                {"content": "Max bevorzugt 21 Grad", "category": "preference", "person": "Max"},
                {"content": "Max arbeitet remote", "category": "work", "person": "Max"},
            ])},
        })

        result = await extractor.extract_and_store(
            user_text="Ich arbeite heute von zu Hause und haette gern 21 Grad",
            assistant_response="Heizung auf 21 Grad gestellt.",
            person="Max",
        )

        assert len(result) == 2
        assert semantic_mock.store_fact.call_count == 2
        # Pruefen dass Confidence korrekt gesetzt ist
        stored_facts = [call[0][0] for call in semantic_mock.store_fact.call_args_list]
        pref_fact = [f for f in stored_facts if f.category == "preference"][0]
        assert pref_fact.confidence == CATEGORY_CONFIDENCE["preference"]  # 0.85

    @pytest.mark.asyncio
    async def test_extract_skips_short_text(self, extractor, ollama_mock):
        result = await extractor.extract_and_store(
            user_text="Hi",
            assistant_response="Hallo!",
            person="Max",
        )
        assert result == []
        ollama_mock.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_skips_commands(self, extractor, ollama_mock):
        result = await extractor.extract_and_store(
            user_text="licht aus",
            assistant_response="Erledigt.",
            person="Max",
        )
        assert result == []
        ollama_mock.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_handles_llm_error(self, extractor, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={"error": "Model not loaded"})

        result = await extractor.extract_and_store(
            user_text="Ich habe morgen einen wichtigen Termin beim Zahnarzt",
            assistant_response="Soll ich dich morgen frueh erinnern?",
            person="Max",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_handles_llm_exception(self, extractor, ollama_mock):
        ollama_mock.chat = AsyncMock(side_effect=Exception("Connection refused"))

        result = await extractor.extract_and_store(
            user_text="Meine Mutter hat naechste Woche Geburtstag",
            assistant_response="Soll ich das notieren?",
            person="Max",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_handles_empty_response(self, extractor, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "[]"},
        })

        result = await extractor.extract_and_store(
            user_text="Wie wird das Wetter morgen in Wien?",
            assistant_response="Morgen wird es sonnig.",
            person="Max",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_skips_failed_storage(self, extractor, ollama_mock, semantic_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": json.dumps([
                {"content": "Fakt 1", "category": "general", "person": "Max"},
                {"content": "Fakt 2", "category": "general", "person": "Max"},
            ])},
        })
        # Erster store_fact klappt, zweiter nicht
        semantic_mock.store_fact = AsyncMock(side_effect=[True, False])

        result = await extractor.extract_and_store(
            user_text="Heute habe ich viel erlebt und auch neue Dinge gelernt",
            assistant_response="Klingt nach einem produktiven Tag!",
            person="Max",
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_extract_source_conversation_truncated(self, extractor, ollama_mock, semantic_mock):
        long_text = " ".join(["Wort"] * 50)  # 50 Woerter, lang genug fuer Extraktion
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": json.dumps([
                {"content": "Ein Fakt", "category": "general", "person": "Max"},
            ])},
        })

        await extractor.extract_and_store(
            user_text=long_text,
            assistant_response="OK",
            person="Max",
        )

        stored_fact = semantic_mock.store_fact.call_args[0][0]
        # source_conversation wird auf 100 Zeichen begrenzt: "User: " + text[:100]
        assert len(stored_fact.source_conversation) <= 106

    @pytest.mark.asyncio
    async def test_extract_with_context(self, extractor, ollama_mock, semantic_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": json.dumps([
                {"content": "Max ist im Buero", "category": "general", "person": "Max"},
            ])},
        })

        await extractor.extract_and_store(
            user_text="Ich bin jetzt im Buero angekommen und brauche es etwas kuehler",
            assistant_response="Klimaanlage wird eingeschaltet.",
            person="Max",
            context={"room": "Buero", "time": {"datetime": "2026-02-20 09:00"}},
        )

        # Pruefen dass LLM aufgerufen wurde
        ollama_mock.chat.assert_called_once()
        prompt = ollama_mock.chat.call_args[1]["messages"][0]["content"]
        assert "Buero" in prompt

    @pytest.mark.asyncio
    async def test_extract_uses_smart_model(self, extractor, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "[]"},
        })

        await extractor.extract_and_store(
            user_text="Ich habe eine neue Lieblings-Serie entdeckt die sehr spannend ist",
            assistant_response="Welche denn?",
            person="Max",
        )

        call_kwargs = ollama_mock.chat.call_args[1]
        # Model kommt aus settings.yaml (extraction_model), Default waere qwen3.5:9b
        assert "model" in call_kwargs
        assert call_kwargs["temperature"] == 0.1


# =====================================================================
# Category Confidence Mapping
# =====================================================================


class TestCategoryConfidence:
    """Tests fuer Confidence-Werte pro Kategorie."""

    def test_health_highest(self):
        assert CATEGORY_CONFIDENCE["health"] >= CATEGORY_CONFIDENCE["person"]
        assert CATEGORY_CONFIDENCE["health"] >= CATEGORY_CONFIDENCE["preference"]
        assert CATEGORY_CONFIDENCE["health"] >= CATEGORY_CONFIDENCE["general"]

    def test_general_lowest(self):
        for cat in CATEGORY_CONFIDENCE:
            assert CATEGORY_CONFIDENCE[cat] >= CATEGORY_CONFIDENCE["general"]

    def test_all_categories_covered(self):
        expected = ["health", "person", "preference", "habit", "work", "intent", "general"]
        for cat in expected:
            assert cat in CATEGORY_CONFIDENCE

    def test_all_values_between_0_and_1(self):
        for cat, val in CATEGORY_CONFIDENCE.items():
            assert 0.0 <= val <= 1.0, f"{cat}: {val} ausserhalb [0, 1]"

    def test_intent_lower_than_preference(self):
        # Absichten aendern sich haeufiger als Vorlieben
        assert CATEGORY_CONFIDENCE["intent"] < CATEGORY_CONFIDENCE["preference"]


# =====================================================================
# Constants
# =====================================================================


class TestConstants:
    """Tests fuer Konfigurationskonstanten."""

    def test_min_conversation_words(self):
        assert MIN_CONVERSATION_WORDS >= 3
        assert MIN_CONVERSATION_WORDS <= 10

    def test_max_conversation_length(self):
        assert MAX_CONVERSATION_LENGTH >= 500
        assert MAX_CONVERSATION_LENGTH <= 10000


# =====================================================================
# Zusaetzliche Tests fuer 100% Coverage
# =====================================================================


class TestShouldExtractCoverage:
    """Zusaetzliche Tests fuer _should_extract — fehlende Zeilen."""

    def test_empty_content_skipped(self, extractor):
        """Fakten ohne Content werden uebersprungen (Zeile 141)."""
        # Implizit getestet via extract_and_store mit leeren facts

    def test_greeting_filtered(self, extractor):
        """Gruesse und Smalltalk werden gefiltert (Zeile 186 — greetings check)."""
        assert extractor._should_extract("hallo", "Hi!") is False
        assert extractor._should_extract("wie gehts", "Gut!") is False

    def test_confirmations_filtered(self, extractor):
        """Einzelwort-Bestaetigungen werden gefiltert (Zeile 195)."""
        assert extractor._should_extract("ja", "OK.") is False
        assert extractor._should_extract("danke", "Gern!") is False
        assert extractor._should_extract("verstehe", "OK.") is False

    def test_proactive_marker_filtered(self, extractor):
        """Proaktive Meldungen werden gefiltert (Zeile 205/209)."""
        assert extractor._should_extract("[proaktiv] Status-Meldung fuer das System",
                                         "OK.") is False


class TestParseFacts_FallbackBranch:
    """Zusaetzliche Tests fuer _parse_facts — Zeilen 288-289."""

    def test_parse_facts_invalid_inner_json(self, extractor):
        """Fallback JSON-Parsing schlaegt fehl bei kaputtem innerem JSON (Zeilen 288-289)."""
        output = 'Some text [{"content": "broken json' + '] more text'
        result = extractor._parse_facts(output)
        assert result == []


class TestExtractAndStoreCoverage:
    """Zusaetzliche Tests fuer extract_and_store — fehlende Zeilen 141, 323, 327."""

    @pytest.mark.asyncio
    async def test_extract_skips_empty_content_fact(self, extractor, ollama_mock, semantic_mock):
        """Fakten mit leerem Content werden uebersprungen (Zeile 141)."""
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": json.dumps([
                {"content": "", "category": "general", "person": "Max"},
                {"content": "Guter Fakt hier drin", "category": "preference", "person": "Max"},
            ])},
        })
        result = await extractor.extract_and_store(
            user_text="Ich habe heute viel erlebt und es war wirklich interessant",
            assistant_response="Klingt spannend!",
            person="Max",
        )
        # Nur 1 Fakt gespeichert (der mit Content)
        assert len(result) == 1


class TestExtractReactionCoverage:
    """Tests fuer extract_reaction — fehlende Zeilen 323, 327, 352-353."""

    @pytest.mark.asyncio
    async def test_extract_reaction_disabled(self, extractor):
        """extract_reaction kehrt zurueck wenn emotional_memory disabled (Zeile 323)."""
        with patch("assistant.memory_extractor.yaml_config", {"emotional_memory": {"enabled": False}, "memory": {}}):
            await extractor.extract_reaction("nein", "set_climate", False, "Max", redis_client=AsyncMock())
            # Kein Fehler, kehrt einfach zurueck

    @pytest.mark.asyncio
    async def test_extract_reaction_no_redis(self, extractor):
        """extract_reaction kehrt zurueck wenn kein Redis (Zeile 327)."""
        with patch("assistant.memory_extractor.yaml_config", {"emotional_memory": {"enabled": True}, "memory": {}}):
            await extractor.extract_reaction("nein", "set_climate", False, "Max", redis_client=None)
            # Kein Fehler, kehrt einfach zurueck

    @pytest.mark.asyncio
    async def test_extract_reaction_exception(self, extractor):
        """extract_reaction faengt Exceptions ab (Zeilen 352-353)."""
        redis = AsyncMock()
        redis.lpush = AsyncMock(side_effect=Exception("Redis error"))
        with patch("assistant.memory_extractor.yaml_config", {"emotional_memory": {"enabled": True, "decay_days": 90}, "memory": {}}):
            await extractor.extract_reaction("nein", "set_climate", False, "Max", redis_client=redis)
            # Kein Fehler — Exception wird abgefangen


class TestExtractReactionPositive:
    """Tests fuer extract_reaction — positiver Pfad (Zeile 371)."""

    @pytest.mark.asyncio
    async def test_extract_reaction_positive_success(self, extractor):
        """extract_reaction speichert positive Reaktion erfolgreich."""
        redis = AsyncMock()
        with patch("assistant.memory_extractor.yaml_config", {"emotional_memory": {"enabled": True, "decay_days": 90}, "memory": {}}):
            await extractor.extract_reaction("super", "set_light", True, "Max", redis_client=redis)
            redis.lpush.assert_called_once()
            redis.ltrim.assert_called_once()
            redis.expire.assert_called_once()


class TestGetEmotionalContextCoverage:
    """Tests fuer get_emotional_context — fehlende Zeilen 400-402."""

    @pytest.mark.asyncio
    async def test_get_emotional_context_exception(self):
        """get_emotional_context faengt Exceptions ab (Zeilen 400-402)."""
        redis = AsyncMock()
        redis.lrange = AsyncMock(side_effect=Exception("Redis error"))
        with patch("assistant.memory_extractor.yaml_config", {"emotional_memory": {"enabled": True, "negative_threshold": 2}, "memory": {}}):
            result = await MemoryExtractor.get_emotional_context("set_climate", "Max", redis_client=redis)
            assert result is None

    @pytest.mark.asyncio
    async def test_detect_negative_reaction(self, extractor):
        """detect_negative_reaction erkennt negative Muster."""
        assert extractor.detect_negative_reaction("nein, lass das") is True
        assert extractor.detect_negative_reaction("super gemacht") is False
