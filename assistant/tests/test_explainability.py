"""Tests for assistant.explainability module."""

import json
import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from assistant.explainability import ExplainabilityEngine


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.expire = AsyncMock()
    r.set = AsyncMock()
    return r


@pytest.fixture
def engine():
    with patch("assistant.explainability.yaml_config", {"explainability": {"enabled": True, "max_history": 50, "detail_level": "normal", "auto_explain": False}}):
        return ExplainabilityEngine()


# ------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_with_redis(engine, mock_redis):
    await engine.initialize(mock_redis)
    assert engine.redis is mock_redis
    mock_redis.lrange.assert_called_once()


@pytest.mark.asyncio
async def test_initialize_loads_decisions(engine, mock_redis):
    decisions = [
        json.dumps({"action": "Licht an", "reason": "Befehl", "domain": "light"}),
        json.dumps({"action": "Heizung hoch", "reason": "Kalt", "domain": "climate"}),
    ]
    mock_redis.lrange.return_value = decisions
    await engine.initialize(mock_redis)
    assert len(engine._decisions) == 2


@pytest.mark.asyncio
async def test_initialize_no_redis(engine):
    await engine.initialize(None)
    assert engine.redis is None


# ------------------------------------------------------------------
# log_decision
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_decision_basic(engine, mock_redis):
    engine.redis = mock_redis
    await engine.log_decision("Licht an", "Befehl", trigger="user_command", domain="light")
    assert len(engine._decisions) == 1
    assert engine._decisions[0]["action"] == "Licht an"
    mock_redis.lpush.assert_called_once()
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_log_decision_with_context(engine, mock_redis):
    engine.redis = mock_redis
    ctx = {"room": "Wohnzimmer", "sensor_values": {"temp": 22}, "irrelevant_key": "ignored"}
    await engine.log_decision("Heizung", "Kalt", context=ctx, domain="climate")
    decision = engine._decisions[0]
    assert "room" in decision["context"]
    assert "sensor_values" in decision["context"]
    assert "irrelevant_key" not in decision["context"]


@pytest.mark.asyncio
async def test_log_decision_disabled(engine):
    engine.enabled = False
    await engine.log_decision("Test", "Test")
    assert len(engine._decisions) == 0


@pytest.mark.asyncio
async def test_log_decision_no_redis(engine):
    engine.redis = None
    await engine.log_decision("Test", "Reason", trigger="user_command")
    assert len(engine._decisions) == 1  # still added to memory


@pytest.mark.asyncio
async def test_log_decision_confidence(engine, mock_redis):
    engine.redis = mock_redis
    await engine.log_decision("Test", "Reason", confidence=0.756)
    assert engine._decisions[0]["confidence"] == 0.76


@pytest.mark.asyncio
async def test_log_decision_minimal_detail(engine, mock_redis):
    engine.redis = mock_redis
    engine.detail_level = "minimal"
    ctx = {"room": "Wohnzimmer"}
    await engine.log_decision("Test", "Reason", context=ctx)
    assert "context" not in engine._decisions[0]


# ------------------------------------------------------------------
# explain_last
# ------------------------------------------------------------------


def test_explain_last_empty(engine):
    assert engine.explain_last() == []


def test_explain_last_one(engine):
    engine._decisions.append({"action": "A", "reason": "R"})
    result = engine.explain_last(1)
    assert len(result) == 1
    assert result[0]["action"] == "A"


def test_explain_last_multiple(engine):
    for i in range(5):
        engine._decisions.append({"action": f"A{i}", "reason": f"R{i}"})
    result = engine.explain_last(3)
    assert len(result) == 3
    assert result[-1]["action"] == "A4"


# ------------------------------------------------------------------
# explain_by_domain
# ------------------------------------------------------------------


def test_explain_by_domain(engine):
    engine._decisions.append({"action": "Licht", "domain": "light"})
    engine._decisions.append({"action": "Heizung", "domain": "climate"})
    engine._decisions.append({"action": "Lampe", "domain": "light"})
    result = engine.explain_by_domain("light")
    assert len(result) == 2


def test_explain_by_domain_empty(engine):
    assert engine.explain_by_domain("light") == []


# ------------------------------------------------------------------
# explain_by_action
# ------------------------------------------------------------------


def test_explain_by_action(engine):
    engine._decisions.append({"action": "Licht Wohnzimmer an", "reason": "Befehl"})
    engine._decisions.append({"action": "Heizung hoch", "reason": "Kalt"})
    result = engine.explain_by_action("licht")
    assert len(result) == 1
    assert "Licht" in result[0]["action"]


def test_explain_by_action_in_reason(engine):
    engine._decisions.append({"action": "Something", "reason": "wegen Licht-Sensor"})
    result = engine.explain_by_action("licht")
    assert len(result) == 1


# ------------------------------------------------------------------
# format_explanation
# ------------------------------------------------------------------


def test_format_explanation_basic(engine):
    decision = {"action": "Licht an", "reason": "Befehl", "trigger": "user_command", "time_str": "14:30:00", "confidence": 1.0}
    text = engine.format_explanation(decision)
    assert "Licht an" in text
    assert "auf deinen Befehl" in text
    assert "14:30:00" in text


def test_format_explanation_verbose_low_confidence(engine):
    engine.detail_level = "verbose"
    decision = {"action": "Test", "reason": "Muster", "trigger": "anticipation", "time_str": "10:00", "confidence": 0.7}
    text = engine.format_explanation(decision)
    assert "Konfidenz" in text
    assert "70%" in text


def test_format_explanation_unknown_trigger(engine):
    decision = {"action": "X", "reason": "Y", "trigger": "custom_trigger", "time_str": "", "confidence": 1.0}
    text = engine.format_explanation(decision)
    assert "X" in text


# ------------------------------------------------------------------
# get_explanation_prompt_hint
# ------------------------------------------------------------------


def test_prompt_hint_disabled(engine):
    engine.enabled = False
    assert engine.get_explanation_prompt_hint() == ""


def test_prompt_hint_no_auto_explain(engine):
    engine.auto_explain = False
    assert engine.get_explanation_prompt_hint() == ""


def test_prompt_hint_with_recent_decision(engine):
    engine.auto_explain = True
    engine._decisions.append({"action": "Licht an", "reason": "Abend", "timestamp": time.time()})
    hint = engine.get_explanation_prompt_hint()
    assert "Licht an" in hint


def test_prompt_hint_stale_decision(engine):
    engine.auto_explain = True
    engine._decisions.append({"action": "Old", "reason": "R", "timestamp": time.time() - 400})
    assert engine.get_explanation_prompt_hint() == ""


# ------------------------------------------------------------------
# get_stats
# ------------------------------------------------------------------


def test_get_stats_empty(engine):
    stats = engine.get_stats()
    assert stats["total"] == 0
    assert stats["domains"] == {}
    assert stats["triggers"] == {}


def test_get_stats_with_data(engine):
    engine._decisions.append({"action": "A", "domain": "light", "trigger": "user_command"})
    engine._decisions.append({"action": "B", "domain": "light", "trigger": "automation"})
    engine._decisions.append({"action": "C", "domain": "climate", "trigger": "user_command"})
    stats = engine.get_stats()
    assert stats["total"] == 3
    assert stats["domains"]["light"] == 2
    assert stats["triggers"]["user_command"] == 2


# ------------------------------------------------------------------
# Phase 1C: Kontrafaktische Erklaerungen
# ------------------------------------------------------------------


class TestCounterfactualExplanations:
    """Tests fuer kontrafaktische Erklaerungen (Phase 1C)."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "normal", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    def test_counterfactual_rules_exist(self):
        from assistant.explainability import _COUNTERFACTUAL_RULES
        assert len(_COUNTERFACTUAL_RULES) > 0
        assert ("climate", "window_open") in _COUNTERFACTUAL_RULES
        assert ("light", "empty_room") in _COUNTERFACTUAL_RULES
        assert ("cover", "wind_warning") in _COUNTERFACTUAL_RULES

    def test_build_counterfactual_climate_window(self, eng):
        """Fenster offen + Klima → Heizkosten-Warnung."""
        result = eng._build_counterfactual(
            "climate",
            {"rule": "window open check", "sensor_values": {"cost": "0.50"}},
        )
        assert result is not None
        assert "Heizkosten" in result or "Eingreifen" in result

    def test_build_counterfactual_light_empty_room(self, eng):
        """Leerer Raum + Licht → Stromverbrauch-Warnung."""
        result = eng._build_counterfactual(
            "light",
            {"room_empty": True, "sensor_values": {"power": "60"}},
        )
        assert result is not None
        assert "Stromverbrauch" in result or "Eingreifen" in result

    def test_build_counterfactual_cover_wind(self, eng):
        """Wind-Warnung + Cover → Beschaedigungswarnung."""
        result = eng._build_counterfactual(
            "cover",
            {"rule": "wind warning", "sensor_values": {"wind_speed": "80"}},
        )
        assert result is not None
        assert "Eingreifen" in result

    def test_build_counterfactual_no_match(self, eng):
        """Keine passende Regel → None."""
        result = eng._build_counterfactual("media", {})
        assert result is None

    def test_build_counterfactual_no_domain(self, eng):
        """Leere Domain → None."""
        result = eng._build_counterfactual("", {"rule": "test"})
        assert result is None

    def test_build_counterfactual_no_context(self, eng):
        """Leerer Kontext → None."""
        result = eng._build_counterfactual("climate", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_log_decision_explicit_alternatives(self, eng, mock_redis):
        """Explizite alternative_outcomes werden gespeichert."""
        eng.redis = mock_redis
        await eng.log_decision(
            "Heizung gedrosselt", "Fenster offen", domain="climate",
            alternative_outcomes=["2€ Heizkosten verschwendet"],
        )
        assert len(eng._decisions) == 1
        d = eng._decisions[0]
        assert "alternative_outcomes" in d
        assert "2€" in d["alternative_outcomes"][0]

    @pytest.mark.asyncio
    async def test_log_decision_auto_counterfactual(self, eng, mock_redis):
        """Ohne explizite Alternativen wird automatisch generiert."""
        eng.redis = mock_redis
        await eng.log_decision(
            "Licht aus", "Raum leer", domain="light",
            context={"room_empty": True, "sensor_values": {"power": "60"}},
        )
        d = eng._decisions[0]
        assert "alternative_outcomes" in d

    def test_prompt_hint_includes_counterfactual(self, eng):
        """Prompt-Hint sollte kontrafaktische Daten enthalten."""
        eng.auto_explain = True
        eng._decisions.append({
            "action": "Heizung gedrosselt", "reason": "Fenster offen",
            "timestamp": time.time(),
            "alternative_outcomes": ["Heizkosten verschwendet"],
        })
        hint = eng.get_explanation_prompt_hint()
        assert "Heizkosten verschwendet" in hint

    def test_prompt_hint_without_counterfactual(self, eng):
        """Prompt-Hint ohne Counterfactual funktioniert trotzdem."""
        eng.auto_explain = True
        eng._decisions.append({
            "action": "Licht an", "reason": "User-Befehl",
            "timestamp": time.time(),
        })
        hint = eng.get_explanation_prompt_hint()
        assert "Licht an" in hint


# ------------------------------------------------------------------
# format_explanation_llm
# ------------------------------------------------------------------


class TestFormatExplanationLLM:
    """Tests for LLM-based explanation formatting."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "normal", "auto_explain": False,
                               "llm_explanations": True}
        }):
            return ExplainabilityEngine()

    @pytest.mark.asyncio
    async def test_llm_explanation_success(self, eng):
        """LLM returns a valid explanation."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "Ich habe das Licht eingeschaltet, da es dunkel wurde, Sir."}
        })
        eng.set_ollama(ollama)
        decision = {"action": "Licht an", "reason": "Dunkelheit", "trigger": "sensor",
                     "time_str": "20:30", "confidence": 0.9}
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"llm_explanations": True}
        }):
            mock_settings = MagicMock()
            mock_settings.model_fast = "fast-model"
            with patch("assistant.config.settings", mock_settings):
                with patch("assistant.config.get_person_title", return_value="Sir"):
                    result = await eng.format_explanation_llm(decision)
        assert "Licht" in result
        assert len(result) > 10

    @pytest.mark.asyncio
    async def test_llm_explanation_fallback_no_ollama(self, eng):
        """Falls back to template when no ollama client is set."""
        eng._ollama = None
        decision = {"action": "Licht an", "reason": "Befehl", "trigger": "user_command",
                     "time_str": "14:00", "confidence": 1.0}
        result = await eng.format_explanation_llm(decision)
        assert "Licht an" in result
        assert "ausgefuehrt" in result  # Template format

    @pytest.mark.asyncio
    async def test_llm_explanation_fallback_disabled(self, eng):
        """Falls back to template when llm_explanations is disabled."""
        ollama = AsyncMock()
        eng.set_ollama(ollama)
        decision = {"action": "Test", "reason": "R", "trigger": "", "time_str": "", "confidence": 1.0}
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"llm_explanations": False}
        }):
            result = await eng.format_explanation_llm(decision)
        assert "ausgefuehrt" in result
        ollama.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_explanation_fallback_on_exception(self, eng):
        """Falls back to template when LLM throws an exception."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        eng.set_ollama(ollama)
        decision = {"action": "Heizung", "reason": "Kalt", "trigger": "automation",
                     "time_str": "08:00", "confidence": 0.85}
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"llm_explanations": True}
        }):
            mock_settings = MagicMock()
            mock_settings.model_fast = "fast-model"
            with patch("assistant.config.settings", mock_settings):
                with patch("assistant.config.get_person_title", return_value="Sir"):
                    result = await eng.format_explanation_llm(decision)
        assert "Heizung" in result
        assert "ausgefuehrt" in result

    @pytest.mark.asyncio
    async def test_llm_explanation_strips_think_blocks(self, eng):
        """LLM response with <think> blocks gets stripped."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "<think>reasoning here</think>Das Licht wurde wegen Dunkelheit aktiviert, Sir."}
        })
        eng.set_ollama(ollama)
        decision = {"action": "Licht an", "reason": "Dunkel", "trigger": "sensor",
                     "time_str": "21:00", "confidence": 0.95}
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"llm_explanations": True}
        }):
            mock_settings = MagicMock()
            mock_settings.model_fast = "fast-model"
            with patch("assistant.config.settings", mock_settings):
                with patch("assistant.config.get_person_title", return_value="Sir"):
                    result = await eng.format_explanation_llm(decision)
        assert "<think>" not in result
        assert "Licht" in result or "Dunkelheit" in result

    @pytest.mark.asyncio
    async def test_llm_explanation_short_response_falls_back(self, eng):
        """LLM response too short (<= 10 chars) falls back to template."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "OK."}
        })
        eng.set_ollama(ollama)
        decision = {"action": "Test", "reason": "R", "trigger": "user_command",
                     "time_str": "", "confidence": 1.0}
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"llm_explanations": True}
        }):
            mock_settings = MagicMock()
            mock_settings.model_fast = "fast-model"
            with patch("assistant.config.settings", mock_settings):
                with patch("assistant.config.get_person_title", return_value="Sir"):
                    result = await eng.format_explanation_llm(decision)
        assert "ausgefuehrt" in result


# ------------------------------------------------------------------
# get_auto_explanation
# ------------------------------------------------------------------


class TestGetAutoExplanation:
    """Tests for automatic explanations on high-impact domains."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "normal", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    @pytest.mark.parametrize("domain", ["security", "climate", "lock", "alarm"])
    def test_high_impact_domains_return_explanation(self, eng, domain):
        """High-impact domains always get an auto-explanation."""
        result = eng.get_auto_explanation("turn_off", domain=domain)
        assert result is not None
        assert domain in result

    @pytest.mark.parametrize("domain", ["light", "media", "cover", ""])
    def test_non_critical_domains_return_none(self, eng, domain):
        """Non-critical domains return None."""
        result = eng.get_auto_explanation("turn_on", domain=domain)
        assert result is None

    def test_auto_explanation_includes_action_type(self, eng):
        """Auto explanation contains the action type."""
        result = eng.get_auto_explanation("emergency_lock", domain="security")
        assert "emergency_lock" in result


# ------------------------------------------------------------------
# _build_counterfactual extended edge cases
# ------------------------------------------------------------------


class TestBuildCounterfactualExtended:
    """Extended edge case tests for counterfactual generation."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "normal", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    def test_high_temperature_climate(self, eng):
        """High temperature triggers counterfactual for climate."""
        result = eng._build_counterfactual(
            "climate",
            {"sensor_values": {"temperature": "28"}},
        )
        assert result is not None
        assert "Eingreifen" in result

    def test_temperature_below_threshold_no_match(self, eng):
        """Temperature at or below 26 does not trigger high_temp."""
        result = eng._build_counterfactual(
            "climate",
            {"sensor_values": {"temperature": "25"}},
        )
        assert result is None

    def test_night_unlocked_lock_domain(self, eng):
        """Night + lock domain triggers night_unlocked counterfactual."""
        result = eng._build_counterfactual(
            "lock",
            {"rule": "nacht check", "sensor_values": {}},
        )
        # "nacht" triggers night_unlocked, and (lock, night_unlocked) rule exists
        assert result is not None
        assert "offen" in result or "Eingreifen" in result

    def test_alarm_triggered(self, eng):
        """Alarm context triggers security counterfactual."""
        result = eng._build_counterfactual(
            "security",
            {"rule": "alarm triggered", "sensor_values": {}},
        )
        assert result is not None
        assert "Benachrichtigung" in result

    def test_rain_warning_cover(self, eng):
        """Rain warning + cover triggers counterfactual."""
        result = eng._build_counterfactual(
            "cover",
            {"rule": "rain warning", "sensor_values": {}},
        )
        assert result is not None
        assert "nass" in result or "Eingreifen" in result

    def test_daylight_light(self, eng):
        """Daylight context + light triggers counterfactual."""
        result = eng._build_counterfactual(
            "light",
            {"rule": "daylight detected", "sensor_values": {}},
        )
        assert result is not None
        assert "Tageslicht" in result or "Eingreifen" in result

    def test_door_unlocked_security(self, eng):
        """Door unlocked at night triggers lock counterfactual."""
        result = eng._build_counterfactual(
            "lock",
            {"rule": "nacht check", "sensor_values": {}},
        )
        assert result is not None

    def test_template_format_with_invalid_values(self, eng):
        """Template formatting handles missing sensor values gracefully via defaults."""
        result = eng._build_counterfactual(
            "climate",
            {"rule": "window offen", "sensor_values": {}},
        )
        # Should still produce output using default values
        assert result is not None

    def test_temperature_invalid_value_ignored(self, eng):
        """Invalid temperature value does not cause error."""
        result = eng._build_counterfactual(
            "climate",
            {"sensor_values": {"temperature": "not_a_number"}},
        )
        # Should return None since invalid temp won't add high_temp key
        # and no other context matches
        assert result is None

    def test_fenster_german_keyword(self, eng):
        """German 'fenster' keyword also triggers window_open."""
        result = eng._build_counterfactual(
            "climate",
            {"rule": "Fenster offen check", "sensor_values": {"cost": "0.75"}},
        )
        assert result is not None
        assert "Heizkosten" in result


# ------------------------------------------------------------------
# Deque max_history behavior
# ------------------------------------------------------------------


class TestDequeMaxHistory:
    """Tests for max_history limit on the decision deque."""

    @pytest.fixture
    def eng_small(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 3,
                               "detail_level": "normal", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    @pytest.mark.asyncio
    async def test_deque_evicts_oldest(self, eng_small):
        """When max_history is reached, oldest decisions are evicted."""
        for i in range(5):
            await eng_small.log_decision(f"Action {i}", f"Reason {i}", domain="light")
        assert len(eng_small._decisions) == 3
        actions = [d["action"] for d in eng_small._decisions]
        assert "Action 0" not in actions
        assert "Action 1" not in actions
        assert "Action 4" in actions


# ------------------------------------------------------------------
# Redis error handling
# ------------------------------------------------------------------


class TestRedisErrorHandling:
    """Tests for graceful degradation on Redis errors."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "normal", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    @pytest.mark.asyncio
    async def test_log_decision_redis_error_still_stores_in_memory(self, eng):
        """Redis error during log_decision should not prevent in-memory storage."""
        redis = AsyncMock()
        redis.lpush = AsyncMock(side_effect=ConnectionError("Redis down"))
        eng.redis = redis
        await eng.log_decision("Test", "Reason", trigger="user_command")
        assert len(eng._decisions) == 1

    @pytest.mark.asyncio
    async def test_load_decisions_redis_error(self, eng):
        """Redis error during _load_decisions is handled gracefully."""
        redis = AsyncMock()
        redis.lrange = AsyncMock(side_effect=ConnectionError("Redis down"))
        eng.redis = redis
        await eng._load_decisions()
        assert len(eng._decisions) == 0

    @pytest.mark.asyncio
    async def test_load_decisions_invalid_json(self, eng):
        """Invalid JSON entries are skipped during load."""
        redis = AsyncMock()
        redis.lrange = AsyncMock(return_value=[
            b"not json",
            json.dumps({"action": "Valid", "reason": "R"}).encode(),
        ])
        eng.redis = redis
        await eng._load_decisions()
        assert len(eng._decisions) == 1
        assert eng._decisions[0]["action"] == "Valid"


# ------------------------------------------------------------------
# set_ollama
# ------------------------------------------------------------------


class TestSetOllama:
    """Tests for the set_ollama method."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "normal", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    def test_set_ollama_stores_client(self, eng):
        """set_ollama stores the ollama client."""
        assert eng._ollama is None
        mock_ollama = AsyncMock()
        eng.set_ollama(mock_ollama)
        assert eng._ollama is mock_ollama


# ------------------------------------------------------------------
# log_decision with alternative_outcomes edge cases
# ------------------------------------------------------------------


class TestLogDecisionAlternatives:
    """Edge cases for alternative_outcomes in log_decision."""

    @pytest.fixture
    def eng(self):
        with patch("assistant.explainability.yaml_config", {
            "explainability": {"enabled": True, "max_history": 50,
                               "detail_level": "verbose", "auto_explain": False}
        }):
            return ExplainabilityEngine()

    @pytest.mark.asyncio
    async def test_verbose_detail_includes_all_context_keys(self, eng, mock_redis):
        """Verbose mode includes allowed context keys."""
        eng.redis = mock_redis
        ctx = {
            "room": "Wohnzimmer",
            "sensor_values": {"temp": 22},
            "mood": "neutral",
            "autonomy_level": 3,
            "weather": "sunny",
            "calendar_event": "meeting",
            "rule": "custom_rule",
            "pattern": "morning",
            "secret_data": "should_be_excluded",
        }
        await eng.log_decision("Test", "Reason", context=ctx, domain="light")
        d = eng._decisions[0]
        assert "room" in d["context"]
        assert "mood" in d["context"]
        assert "weather" in d["context"]
        assert "secret_data" not in d["context"]

    @pytest.mark.asyncio
    async def test_multiple_alternative_outcomes(self, eng, mock_redis):
        """Multiple alternative outcomes are stored."""
        eng.redis = mock_redis
        outcomes = ["Outcome A", "Outcome B", "Outcome C"]
        await eng.log_decision("Action", "Reason", alternative_outcomes=outcomes, domain="light")
        d = eng._decisions[0]
        assert len(d["alternative_outcomes"]) == 3

    @pytest.mark.asyncio
    async def test_default_trigger_is_unknown(self, eng, mock_redis):
        """Default trigger is 'unknown' when not provided."""
        eng.redis = mock_redis
        await eng.log_decision("Action", "Reason")
        assert eng._decisions[0]["trigger"] == "unknown"
