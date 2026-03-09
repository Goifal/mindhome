"""Tests for assistant.explainability module."""

import json
import time
import pytest
from unittest.mock import patch, AsyncMock

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
