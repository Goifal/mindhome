"""
Tests fuer AnticipationEngine — Pattern Detection auf Action-History.

Testet:
- Zeit-Muster Erkennung
- Sequenz-Muster Erkennung
- Kontext-Muster Erkennung
- Kausale Ketten (Phase 18)
- Implizite Voraussetzungen
- Action-Logging
- Feedback-System
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.anticipation import AnticipationEngine


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def anticipation():
    with patch("assistant.anticipation.yaml_config", {
        "anticipation": {
            "enabled": True,
            "history_days": 30,
            "min_confidence": 0.6,
            "check_interval_minutes": 15,
            "thresholds": {"ask": 0.6, "suggest": 0.8, "auto": 0.95},
        },
    }):
        engine = AnticipationEngine()
    return engine


@pytest.fixture
def anticipation_with_redis(anticipation, redis_mock):
    anticipation.redis = redis_mock
    return anticipation


# ============================================================
# Initialisierung
# ============================================================

class TestAnticipationInit:

    def test_default_config(self, anticipation):
        assert anticipation.enabled is True
        assert anticipation.history_days == 30
        assert anticipation.min_confidence == 0.6

    @pytest.mark.asyncio
    async def test_initialize(self, anticipation, redis_mock):
        await anticipation.initialize(redis_client=redis_mock)
        assert anticipation.redis is redis_mock
        assert anticipation._running is True

    @pytest.mark.asyncio
    async def test_stop(self, anticipation):
        import asyncio
        anticipation._running = True
        async def noop(): pass
        task = asyncio.ensure_future(noop())
        await task
        anticipation._task = task
        await anticipation.stop()
        assert anticipation._running is False

    def test_set_notify_callback(self, anticipation):
        cb = AsyncMock()
        anticipation.set_notify_callback(cb)
        assert anticipation._notify_callback is cb


# ============================================================
# Action Logging
# ============================================================

class TestActionLogging:

    @pytest.mark.asyncio
    async def test_log_action(self, anticipation_with_redis):
        await anticipation_with_redis.log_action(
            "set_light", {"state": "on"}, person="Max", weather_condition="sunny",
        )
        pipe = anticipation_with_redis.redis._pipeline
        pipe.lpush.assert_called()
        pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_action_no_redis(self, anticipation):
        # Sollte nicht crashen
        await anticipation.log_action("set_light", {})


# ============================================================
# Zeit-Muster Erkennung
# ============================================================

class TestTimePatterns:

    def test_detect_time_pattern(self, anticipation):
        now = datetime.now()
        entries = []
        # 10 gleiche Aktionen am gleichen Wochentag/Stunde
        for i in range(10):
            entries.append({
                "action": "set_light",
                "args": '{"state": "off"}',
                "weekday": 0,
                "hour": 22,
                "timestamp": (now - timedelta(days=i * 7)).isoformat(),
                "weather": "",
            })

        patterns = anticipation._detect_time_patterns(entries)
        assert len(patterns) > 0
        assert patterns[0]["type"] == "time"
        assert patterns[0]["action"] == "set_light"
        assert patterns[0]["weekday"] == 0
        assert patterns[0]["hour"] == 22

    def test_too_few_entries(self, anticipation):
        entries = [
            {"action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
             "timestamp": datetime.now().isoformat(), "weather": ""},
        ]
        patterns = anticipation._detect_time_patterns(entries)
        assert len(patterns) == 0


# ============================================================
# Sequenz-Muster Erkennung
# ============================================================

class TestSequencePatterns:

    def test_detect_sequence(self, anticipation):
        now = datetime.now()
        entries = []
        # 8 Paare von set_light → set_cover innerhalb 2 Min
        for i in range(8):
            t = now - timedelta(days=i)
            entries.append({
                "action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": t.isoformat(), "weather": "",
            })
            entries.append({
                "action": "set_cover", "args": '{"position": 0}', "weekday": 0, "hour": 22,
                "timestamp": (t + timedelta(seconds=60)).isoformat(), "weather": "",
            })

        patterns = anticipation._detect_sequence_patterns(entries)
        assert len(patterns) > 0
        assert patterns[0]["type"] == "sequence"
        assert patterns[0]["trigger_action"] == "set_light"
        assert patterns[0]["follow_action"] == "set_cover"

    def test_no_sequence_same_action(self, anticipation):
        now = datetime.now()
        entries = []
        for i in range(10):
            entries.append({
                "action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": (now + timedelta(seconds=i * 30)).isoformat(), "weather": "",
            })
        patterns = anticipation._detect_sequence_patterns(entries)
        assert len(patterns) == 0  # Gleiche Aktion wird ignoriert


# ============================================================
# Kontext-Muster Erkennung
# ============================================================

class TestContextPatterns:

    def test_detect_evening_cluster(self, anticipation):
        entries = []
        now = datetime.now()
        # 15 set_cover Aktionen abends, 2 morgens
        for i in range(15):
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0,
                "hour": 19, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "",
            })
        for i in range(2):
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0,
                "hour": 8, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "",
            })

        patterns = anticipation._detect_context_patterns(entries)
        ctx_patterns = [p for p in patterns if p["type"] == "context"]
        assert len(ctx_patterns) > 0

    def test_weather_context(self, anticipation):
        entries = []
        now = datetime.now()
        # 8 set_cover bei Regen, 2 bei Sonne
        for i in range(8):
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0,
                "hour": 14, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "rainy",
            })
        for i in range(2):
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0,
                "hour": 14, "timestamp": (now - timedelta(days=i + 10)).isoformat(),
                "weather": "sunny",
            })

        patterns = anticipation._detect_context_patterns(entries)
        weather_patterns = [p for p in patterns if "weather:" in p.get("context", "")]
        assert len(weather_patterns) > 0


# ============================================================
# Kausale Ketten (Phase 18)
# ============================================================

class TestCausalChains:

    def test_detect_chain_3_actions(self, anticipation):
        now = datetime.now()
        entries = []
        # 4 gleiche Ketten: set_light → set_cover → set_climate innerhalb 5 Min
        for i in range(4):
            t = now - timedelta(days=i)
            entries.append({"action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                            "timestamp": t.isoformat(), "weather": ""})
            entries.append({"action": "set_cover", "args": "{}", "weekday": 0, "hour": 22,
                            "timestamp": (t + timedelta(seconds=120)).isoformat(), "weather": ""})
            entries.append({"action": "set_climate", "args": "{}", "weekday": 0, "hour": 22,
                            "timestamp": (t + timedelta(seconds=240)).isoformat(), "weather": ""})
            # Luecke zwischen Ketten
            entries.append({"action": "other", "args": "{}", "weekday": 0, "hour": 23,
                            "timestamp": (t + timedelta(hours=2)).isoformat(), "weather": ""})

        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {"causal_chain_window_min": 10, "causal_chain_min_occurrences": 3},
        }):
            patterns = anticipation._detect_causal_chains(entries)

        causal = [p for p in patterns if p["type"] == "causal_chain"]
        assert len(causal) > 0
        assert len(causal[0]["actions"]) >= 3

    def test_no_chain_too_few_occurrences(self, anticipation):
        now = datetime.now()
        entries = []
        # Nur 1 Kette → unter Minimum
        entries.append({"action": "a", "args": "{}", "weekday": 0, "hour": 10,
                        "timestamp": now.isoformat(), "weather": ""})
        entries.append({"action": "b", "args": "{}", "weekday": 0, "hour": 10,
                        "timestamp": (now + timedelta(seconds=30)).isoformat(), "weather": ""})
        entries.append({"action": "c", "args": "{}", "weekday": 0, "hour": 10,
                        "timestamp": (now + timedelta(seconds=60)).isoformat(), "weather": ""})

        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {"causal_chain_window_min": 10, "causal_chain_min_occurrences": 3},
        }):
            patterns = anticipation._detect_causal_chains(entries)

        assert len(patterns) == 0


# ============================================================
# Implizite Voraussetzungen
# ============================================================

class TestImplicitPrerequisites:

    def test_entspannen_intent(self, anticipation):
        with patch("assistant.anticipation.yaml_config", {"anticipation": {"intent_sequences": {}}}):
            actions = anticipation.detect_implicit_prerequisites("Ich will entspannen")
        assert len(actions) > 0
        assert "Rollladen runter" in actions

    def test_schlafen_intent(self, anticipation):
        with patch("assistant.anticipation.yaml_config", {"anticipation": {"intent_sequences": {}}}):
            actions = anticipation.detect_implicit_prerequisites("Zeit zum schlafen")
        assert len(actions) > 0
        assert "Alle Lichter aus" in actions

    def test_negation_blocks(self, anticipation):
        with patch("assistant.anticipation.yaml_config", {"anticipation": {"intent_sequences": {}}}):
            actions = anticipation.detect_implicit_prerequisites("Ich will nicht entspannen")
        assert len(actions) == 0

    def test_unknown_intent(self, anticipation):
        with patch("assistant.anticipation.yaml_config", {"anticipation": {"intent_sequences": {}}}):
            actions = anticipation.detect_implicit_prerequisites("Pizza bestellen")
        assert len(actions) == 0


# ============================================================
# Feedback
# ============================================================

class TestFeedback:

    @pytest.mark.asyncio
    async def test_accept_feedback(self, anticipation_with_redis):
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)

        await anticipation_with_redis.record_feedback("Muster X", accepted=True)
        anticipation_with_redis.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_reject_feedback_increases_cooldown(self, anticipation_with_redis):
        anticipation_with_redis.redis.get = AsyncMock(
            return_value=json.dumps({"accepted": 0, "rejected": 1}),
        )

        await anticipation_with_redis.record_feedback("Muster Y", accepted=False)
        # Sollte setex 2x aufrufen: Cooldown + Feedback-Speicher
        assert anticipation_with_redis.redis.setex.call_count >= 2

    @pytest.mark.asyncio
    async def test_no_redis(self, anticipation):
        # Sollte nicht crashen
        await anticipation.record_feedback("Muster Z", accepted=True)


# ============================================================
# Pattern Detection (Integration)
# ============================================================

class TestDetectPatterns:

    @pytest.mark.asyncio
    async def test_no_redis(self, anticipation):
        result = await anticipation.detect_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_too_few_entries(self, anticipation_with_redis):
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=[
            json.dumps({"action": "a", "args": "{}", "weekday": 0, "hour": 10,
                        "timestamp": datetime.now().isoformat(), "weather": ""}),
        ])
        result = await anticipation_with_redis.detect_patterns()
        assert result == []  # < 10 Eintraege
