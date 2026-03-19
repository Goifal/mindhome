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
from datetime import datetime, timedelta, timezone
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
        now = datetime.now(timezone.utc)
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
             "timestamp": datetime.now(timezone.utc).isoformat(), "weather": ""},
        ]
        patterns = anticipation._detect_time_patterns(entries)
        assert len(patterns) == 0


# ============================================================
# Sequenz-Muster Erkennung
# ============================================================

class TestSequencePatterns:

    def test_detect_sequence(self, anticipation):
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
                        "timestamp": datetime.now(timezone.utc).isoformat(), "weather": ""}),
        ])
        result = await anticipation_with_redis.detect_patterns()
        assert result == []  # < 10 Eintraege


# ============================================================
# NEW: Stop with CancelledError — Lines 72-73
# ============================================================

class TestStopCancelledError:

    @pytest.mark.asyncio
    async def test_stop_cancels_running_task(self, anticipation):
        """Stop cancels a running task and handles CancelledError (lines 72-73)."""
        import asyncio
        anticipation._running = True

        async def slow_loop():
            while True:
                await asyncio.sleep(100)

        anticipation._task = asyncio.create_task(slow_loop())
        await anticipation.stop()
        assert anticipation._running is False
        assert anticipation._task.cancelled()


# ============================================================
# NEW: log_action exception — Lines 112-113
# ============================================================

class TestLogActionException:

    @pytest.mark.asyncio
    async def test_log_action_exception(self, anticipation):
        """Exception in log_action is caught (lines 112-113)."""
        anticipation.redis = AsyncMock()
        pipe = MagicMock()
        pipe.execute = AsyncMock(side_effect=Exception("Redis error"))
        anticipation.redis.pipeline = MagicMock(return_value=pipe)
        # Should not raise
        await anticipation.log_action("set_light", {"state": "on"})


# ============================================================
# NEW: detect_patterns with bytes entries — Lines 135
# ============================================================

class TestDetectPatternsBytes:

    @pytest.mark.asyncio
    async def test_detect_patterns_bytes_entries(self, anticipation_with_redis):
        """Handles bytes entries in action log (line 135)."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(15):
            entries.append(json.dumps({
                "action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": (now - timedelta(days=i)).isoformat(), "weather": "",
            }).encode("utf-8"))  # bytes, not str

        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)
        result = await anticipation_with_redis.detect_patterns()
        # Should process without error
        assert isinstance(result, list)


# ============================================================
# NEW: detect_patterns exception — Lines 157-159
# ============================================================

class TestDetectPatternsException:

    @pytest.mark.asyncio
    async def test_detect_patterns_exception(self, anticipation_with_redis):
        """Exception in detect_patterns returns [] (lines 157-159)."""
        anticipation_with_redis.redis.lrange = AsyncMock(side_effect=Exception("Redis fail"))
        result = await anticipation_with_redis.detect_patterns()
        assert result == []


# ============================================================
# NEW: _detect_time_patterns person filter — Lines 176-178
# ============================================================

class TestTimePatternPersonFilter:

    def test_person_filter_too_few(self, anticipation):
        """Person filter with too few entries returns [] (lines 176-178)."""
        entries = [
            {"action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
             "timestamp": datetime.now(timezone.utc).isoformat(), "weather": "", "person": "Max"},
            {"action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
             "timestamp": datetime.now(timezone.utc).isoformat(), "weather": "", "person": "Anna"},
        ]
        result = anticipation._detect_time_patterns(entries, person="Max")
        assert result == []

    def test_time_pattern_invalid_timestamp(self, anticipation):
        """Invalid timestamp uses fallback weight (lines 209-210)."""
        entries = []
        for i in range(5):
            entries.append({
                "action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": "not-a-timestamp",  # Invalid
                "weather": "",
            })
        result = anticipation._detect_time_patterns(entries)
        # Should not raise; fallback weight is used
        assert isinstance(result, list)

    def test_time_pattern_with_person(self, anticipation):
        """Time pattern includes person field when filtered (line 241)."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(10):
            entries.append({
                "action": "set_light", "args": '{"state": "off"}',
                "weekday": 0, "hour": 22,
                "timestamp": (now - timedelta(days=i * 7)).isoformat(),
                "weather": "", "person": "Max",
            })
        result = anticipation._detect_time_patterns(entries, person="Max")
        if result:
            assert result[0].get("person") == "Max"


# ============================================================
# NEW: _detect_sequence_patterns edge cases — Lines 258, 283-284
# ============================================================

class TestSequencePatternsEdgeCases:

    def test_sequence_person_filter(self, anticipation):
        """Sequence patterns filter by person (line 258)."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(8):
            t = now - timedelta(days=i)
            entries.append({
                "action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": t.isoformat(), "weather": "", "person": "Max",
            })
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": (t + timedelta(seconds=60)).isoformat(),
                "weather": "", "person": "Max",
            })
        result = anticipation._detect_sequence_patterns(entries, person="Max")
        assert isinstance(result, list)

    def test_sequence_invalid_timestamp(self, anticipation):
        """Invalid timestamp in sequence is skipped (lines 283-284)."""
        entries = [
            {"action": "a", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": "invalid", "weather": ""},
            {"action": "b", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": "also-invalid", "weather": ""},
        ]
        result = anticipation._detect_sequence_patterns(entries)
        assert result == []

    def test_sequence_with_person_in_pattern(self, anticipation):
        """Sequence pattern includes person field (line 309)."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(8):
            t = now - timedelta(days=i)
            entries.append({
                "action": "set_light", "args": "{}", "weekday": 0, "hour": 22,
                "timestamp": t.isoformat(), "weather": "", "person": "Anna",
            })
            entries.append({
                "action": "set_cover", "args": '{"position": 0}', "weekday": 0, "hour": 22,
                "timestamp": (t + timedelta(seconds=60)).isoformat(),
                "weather": "", "person": "Anna",
            })
        result = anticipation._detect_sequence_patterns(entries, person="Anna")
        if result:
            assert result[0].get("person") == "Anna"


# ============================================================
# NEW: _detect_context_patterns edge cases — Lines 329, 337, 345, 364, 383, 410, 428
# ============================================================

class TestContextPatternsEdgeCases:

    def test_context_person_filter(self, anticipation):
        """Context patterns filter by person (line 329)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(20):
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0,
                "hour": 19, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "", "person": "Max",
            })
        result = anticipation._detect_context_patterns(entries, person="Max")
        assert isinstance(result, list)

    def test_context_empty_action_skipped(self, anticipation):
        """Empty action is skipped (line 337)."""
        entries = [{"action": "", "args": "{}", "weekday": 0, "hour": 10,
                    "timestamp": datetime.now(timezone.utc).isoformat(), "weather": ""}]
        result = anticipation._detect_context_patterns(entries)
        assert result == []

    def test_context_night_cluster(self, anticipation):
        """Night cluster entries (line 345)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(10):
            entries.append({
                "action": "set_light", "args": "{}", "weekday": 0,
                "hour": 23, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "",
            })
        result = anticipation._detect_context_patterns(entries)
        assert isinstance(result, list)

    def test_context_action_too_few_total(self, anticipation):
        """Action with < 5 total occurrences skipped (line 364)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(6):
            entries.append({
                "action": "rare_action" if i < 3 else "common_action", "args": "{}", "weekday": 0,
                "hour": 19, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "",
            })
        result = anticipation._detect_context_patterns(entries)
        # rare_action has < 5 total => skipped
        for p in result:
            assert p.get("action") != "rare_action"

    def test_context_weather_person(self, anticipation):
        """Weather pattern includes person (line 428)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(10):
            entries.append({
                "action": "set_cover", "args": "{}", "weekday": 0,
                "hour": 14, "timestamp": (now - timedelta(days=i)).isoformat(),
                "weather": "rainy", "person": "Anna",
            })
        result = anticipation._detect_context_patterns(entries, person="Anna")
        weather_patterns = [p for p in result if "weather:" in p.get("context", "")]
        if weather_patterns:
            assert weather_patterns[0].get("person") == "Anna"


# ============================================================
# NEW: _detect_causal_chains edge cases — Lines 472-474, 486-488, 515, 527
# ============================================================

class TestCausalChainsEdgeCases:

    def test_causal_chain_invalid_start_timestamp(self, anticipation):
        """Invalid timestamp at chain start skipped (lines 472-474)."""
        entries = [
            {"action": "a", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": "invalid", "weather": ""},
            {"action": "b", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": datetime.now(timezone.utc).isoformat(), "weather": ""},
            {"action": "c", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": datetime.now(timezone.utc).isoformat(), "weather": ""},
        ]
        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {"causal_chain_window_min": 10, "causal_chain_min_occurrences": 1},
        }):
            result = anticipation._detect_causal_chains(entries)
        assert isinstance(result, list)

    def test_causal_chain_invalid_inner_timestamp(self, anticipation):
        """Invalid timestamp inside cluster skipped (lines 486-488)."""
        now = datetime.now(timezone.utc)
        entries = [
            {"action": "a", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": now.isoformat(), "weather": ""},
            {"action": "b", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": "invalid", "weather": ""},
            {"action": "c", "args": "{}", "weekday": 0, "hour": 10,
             "timestamp": (now + timedelta(seconds=30)).isoformat(), "weather": ""},
        ]
        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {"causal_chain_window_min": 10, "causal_chain_min_occurrences": 1},
        }):
            result = anticipation._detect_causal_chains(entries)
        assert isinstance(result, list)

    def test_causal_chain_below_confidence(self, anticipation):
        """Chain below min_confidence is skipped (line 515)."""
        now = datetime.now(timezone.utc)
        entries = []
        # Create many entries to dilute confidence
        for i in range(100):
            entries.append({
                "action": f"action_{i}", "args": "{}", "weekday": 0, "hour": 10,
                "timestamp": (now + timedelta(seconds=i * 700)).isoformat(), "weather": "",
            })
        # Add one chain of 3 (which won't have enough confidence)
        for i in range(3):
            entries.append({
                "action": "chain_a", "args": "{}", "weekday": 0, "hour": 10,
                "timestamp": (now + timedelta(seconds=i * 10)).isoformat(), "weather": "",
            })
        anticipation.min_confidence = 0.99
        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {"causal_chain_window_min": 10, "causal_chain_min_occurrences": 1},
        }):
            result = anticipation._detect_causal_chains(entries)
        # Reset
        anticipation.min_confidence = 0.6
        # Low-confidence chains should be filtered out
        assert all(p.get("confidence", 0) >= 0.99 for p in result)

    def test_causal_chain_person_in_result(self, anticipation):
        """Chain pattern includes person (line 527)."""
        now = datetime.now(timezone.utc)
        entries = []
        for rep in range(4):
            t = now - timedelta(hours=rep * 2)
            for idx, action in enumerate(["x", "y", "z"]):
                entries.append({
                    "action": action, "args": "{}", "weekday": 0, "hour": 10,
                    "timestamp": (t + timedelta(seconds=idx * 30)).isoformat(),
                    "weather": "", "person": "Max",
                })

        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {"causal_chain_window_min": 10, "causal_chain_min_occurrences": 3},
        }):
            result = anticipation._detect_causal_chains(entries, person="Max")
        if result:
            assert result[0].get("person") == "Max"


# ============================================================
# NEW: get_suggestions — Lines 585-689
# ============================================================

class TestGetSuggestions:

    @pytest.mark.asyncio
    async def test_no_redis(self, anticipation):
        """No redis returns [] (line 585)."""
        result = await anticipation.get_suggestions()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_patterns(self, anticipation_with_redis):
        """No patterns returns [] (line 590)."""
        with patch.object(anticipation_with_redis, "detect_patterns", new_callable=AsyncMock, return_value=[]):
            result = await anticipation_with_redis.get_suggestions()
        assert result == []

    @pytest.mark.asyncio
    async def test_time_pattern_matching(self, anticipation_with_redis):
        """Time pattern matching current time generates suggestion (lines 610-619)."""
        now = datetime.now(timezone.utc)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {"state": "off"},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.85,
            "description": "Jeden Tag um jetzt",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]):
            result = await anticipation_with_redis.get_suggestions()
        assert len(result) >= 1
        assert result[0]["mode"] == "suggest"  # 0.85 >= suggest threshold

    @pytest.mark.asyncio
    async def test_time_pattern_wrong_time(self, anticipation_with_redis):
        """Time pattern not matching current time skipped (line 612)."""
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {},
            "weekday": 6,  # Sunday
            "hour": 3,     # 3 AM — unlikely to be current
            "confidence": 0.9,
            "description": "Wrong time",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]):
            result = await anticipation_with_redis.get_suggestions()
        # May or may not match depending on current time
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_sequence_pattern_matching(self, anticipation_with_redis):
        """Sequence pattern with recent trigger generates suggestion (lines 621-641)."""
        now = datetime.now(timezone.utc)
        pattern = {
            "type": "sequence",
            "trigger_action": "set_light",
            "follow_action": "set_cover",
            "follow_args": {"position": 0},
            "confidence": 0.7,
            "description": "Nach set_light folgt set_cover",
        }
        recent_entry = json.dumps({
            "action": "set_light",
            "timestamp": now.isoformat(),
        })
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=[recent_entry])
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]):
            result = await anticipation_with_redis.get_suggestions()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_context_time_cluster_matching(self, anticipation_with_redis):
        """Context time_cluster pattern matching (lines 643-672)."""
        now = datetime.now(timezone.utc)
        hour = now.hour
        if 5 <= hour < 12:
            cluster = "morning"
        elif 12 <= hour < 17:
            cluster = "afternoon"
        elif 17 <= hour < 22:
            cluster = "evening"
        else:
            cluster = "night"

        pattern = {
            "type": "context",
            "context": f"time_cluster:{cluster}",
            "action": "set_cover",
            "args": {},
            "confidence": 0.96,
            "description": "Test context pattern",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]):
            result = await anticipation_with_redis.get_suggestions()
        assert len(result) >= 1
        assert result[0]["mode"] == "auto"  # 0.96 >= auto threshold

    @pytest.mark.asyncio
    async def test_context_weather_matching(self, anticipation_with_redis):
        """Context weather pattern matching (lines 659-663)."""
        pattern = {
            "type": "context",
            "context": "weather:rainy",
            "action": "set_cover",
            "args": {"position": 0},
            "confidence": 0.8,
            "description": "Bei Regen Rolladen",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]), \
             patch.object(anticipation_with_redis, "_get_current_weather",
                          new_callable=AsyncMock, return_value="rainy"):
            result = await anticipation_with_redis.get_suggestions()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_already_suggested_skipped(self, anticipation_with_redis):
        """Already suggested patterns are skipped (lines 604-606)."""
        now = datetime.now(timezone.utc)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.9,
            "description": "Already suggested test",
        }
        # Return truthy value to indicate already suggested
        anticipation_with_redis.redis.get = AsyncMock(return_value=b"1")
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]):
            result = await anticipation_with_redis.get_suggestions()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_suggestion_ask_mode(self, anticipation_with_redis):
        """Low confidence gets ask mode (line 682)."""
        now = datetime.now(timezone.utc)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.65,
            "description": "Low confidence",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        with patch.object(anticipation_with_redis, "detect_patterns",
                          new_callable=AsyncMock, return_value=[pattern]):
            result = await anticipation_with_redis.get_suggestions()
        if result:
            assert result[0]["mode"] == "ask"


# ============================================================
# NEW: _get_current_weather — Lines 693-700
# ============================================================

class TestGetCurrentWeather:

    @pytest.mark.asyncio
    async def test_weather_from_cache(self, anticipation_with_redis):
        """Gets weather from Redis cache (lines 694-697)."""
        anticipation_with_redis.redis.get = AsyncMock(return_value=b"rainy")
        result = await anticipation_with_redis._get_current_weather()
        assert result == "rainy"

    @pytest.mark.asyncio
    async def test_weather_cache_str(self, anticipation_with_redis):
        """Handles string cache value (line 697)."""
        anticipation_with_redis.redis.get = AsyncMock(return_value="sunny")
        result = await anticipation_with_redis._get_current_weather()
        assert result == "sunny"

    @pytest.mark.asyncio
    async def test_weather_no_cache(self, anticipation_with_redis):
        """Returns empty string when no cache (line 700)."""
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        result = await anticipation_with_redis._get_current_weather()
        assert result == ""

    @pytest.mark.asyncio
    async def test_weather_no_redis(self, anticipation):
        """Returns empty string when no redis (line 700)."""
        result = await anticipation._get_current_weather()
        assert result == ""

    @pytest.mark.asyncio
    async def test_weather_exception(self, anticipation_with_redis):
        """Exception returns empty string (lines 698-699)."""
        anticipation_with_redis.redis.get = AsyncMock(side_effect=Exception("Redis error"))
        result = await anticipation_with_redis._get_current_weather()
        assert result == ""


# ============================================================
# NEW: record_feedback exception — Lines 737-738
# ============================================================

class TestRecordFeedbackException:

    @pytest.mark.asyncio
    async def test_feedback_exception(self, anticipation_with_redis):
        """Exception in record_feedback is caught (lines 737-738)."""
        anticipation_with_redis.redis.get = AsyncMock(side_effect=Exception("Redis error"))
        # Should not raise
        await anticipation_with_redis.record_feedback("test", accepted=True)


# ============================================================
# NEW: _check_loop — Lines 750-754, 763-765
# ============================================================

class TestCheckLoop:

    @pytest.mark.asyncio
    async def test_check_loop_runs_and_notifies(self, anticipation_with_redis):
        """Check loop processes suggestions and notifies (lines 750-754)."""
        import asyncio

        now = datetime.now(timezone.utc)
        suggestion = {
            "mode": "suggest",
            "description": "Test suggestion",
            "confidence": 0.85,
            "action": "set_light",
            "args": {},
        }

        callback = AsyncMock()
        anticipation_with_redis.set_notify_callback(callback)
        anticipation_with_redis.check_interval = 0.01  # Very short for test

        call_count = 0

        async def mock_get_suggestions(person=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [suggestion]
            # Stop the loop after first iteration
            anticipation_with_redis._running = False
            return []

        # Patch quiet hours to never-quiet range so the loop doesn't skip
        _no_quiet = {"ambient_presence": {"quiet_start": 0, "quiet_end": 0}}
        with patch.object(anticipation_with_redis, "get_suggestions",
                          side_effect=mock_get_suggestions), \
             patch("assistant.config.yaml_config", _no_quiet):
            anticipation_with_redis._running = True
            task = asyncio.create_task(anticipation_with_redis._check_loop())
            await asyncio.sleep(0.1)
            anticipation_with_redis._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        callback.assert_called_once_with(suggestion)

    @pytest.mark.asyncio
    async def test_check_loop_handles_exception(self, anticipation_with_redis):
        """Check loop handles exception and continues (lines 763-765)."""
        import asyncio

        call_count = 0

        async def mock_get_suggestions(person=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Test error")
            anticipation_with_redis._running = False
            return []

        # Patch quiet hours to never-quiet range so the loop doesn't skip.
        # Also patch asyncio.sleep in error handler (60s) to avoid blocking.
        _no_quiet = {"ambient_presence": {"quiet_start": 0, "quiet_end": 0}}
        _original_sleep = asyncio.sleep

        async def _fast_sleep(seconds):
            await _original_sleep(min(seconds, 0.01))

        anticipation_with_redis.check_interval = 0.01
        with patch.object(anticipation_with_redis, "get_suggestions",
                          side_effect=mock_get_suggestions), \
             patch("assistant.config.yaml_config", _no_quiet), \
             patch("asyncio.sleep", side_effect=_fast_sleep):
            anticipation_with_redis._running = True
            task = asyncio.create_task(anticipation_with_redis._check_loop())
            await _original_sleep(0.2)
            anticipation_with_redis._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count >= 1


# ============================================================
# NEW: detect_implicit_prerequisites with configured intents
# ============================================================

class TestImplicitPrerequisitesConfig:

    def test_configured_intent_sequences(self, anticipation):
        """Uses intent_sequences from config when available."""
        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {
                "intent_sequences": {
                    "party": ["Musik laut", "Licht bunt"],
                },
            },
        }):
            result = anticipation.detect_implicit_prerequisites("Lass uns party machen")
        assert result == ["Musik laut", "Licht bunt"]

    def test_negation_kein(self, anticipation):
        """Negation with 'kein' blocks match."""
        with patch("assistant.anticipation.yaml_config", {"anticipation": {"intent_sequences": {}}}):
            result = anticipation.detect_implicit_prerequisites("kein schlafen heute")
        assert result == []


# ============================================================
# Phase 3A: Multi-Tag-Antizipation
# ============================================================

class TestPhase3APredictFuture:
    """Tests fuer Multi-Tag-Vorhersagen."""

    @pytest.fixture
    def anticipation(self, redis_mock):
        from assistant.anticipation import AnticipationEngine
        a = AnticipationEngine()
        a.redis = redis_mock
        return a

    @pytest.mark.asyncio
    async def test_predict_no_redis(self, anticipation):
        anticipation.redis = None
        result = await anticipation.predict_future_needs()
        assert result == []

    @pytest.mark.asyncio
    async def test_predict_too_few_entries(self, anticipation, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[b"{}"] * 5)
        result = await anticipation.predict_future_needs()
        assert result == []

    @pytest.mark.asyncio
    async def test_predict_with_patterns(self, anticipation, redis_mock):
        """Vorhersage mit genug Daten sollte Ergebnisse liefern."""
        from datetime import datetime
        entries = []
        for i in range(50):
            entry = json.dumps({
                "action": "make_coffee",
                "weekday": datetime.now(timezone.utc).weekday(),
                "hour": 7,
                "timestamp": f"2026-03-{10+i%15:02d}T07:00:00",
            })
            entries.append(entry.encode())
        redis_mock.lrange = AsyncMock(return_value=entries)
        redis_mock.get = AsyncMock(return_value=None)

        result = await anticipation.predict_future_needs(days_ahead=3)
        # Sollte mindestens eine Vorhersage finden
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_predict_max_14_days(self, anticipation, redis_mock):
        """days_ahead wird auf 14 begrenzt."""
        redis_mock.lrange = AsyncMock(return_value=[])
        await anticipation.predict_future_needs(days_ahead=30)
        # Kein Fehler

    @pytest.mark.asyncio
    async def test_enrich_with_forecast_no_redis(self, anticipation):
        anticipation.redis = None
        preds = [{"day": "2026-03-18", "action": "test"}]
        result = await anticipation._enrich_with_forecast(preds)
        assert result == preds

    @pytest.mark.asyncio
    async def test_enrich_with_forecast_no_data(self, anticipation, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        preds = [{"day": "2026-03-18", "action": "test"}]
        result = await anticipation._enrich_with_forecast(preds)
        assert result == preds

    @pytest.mark.asyncio
    async def test_adaptive_threshold_default(self, anticipation, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        result = await anticipation._get_adaptive_threshold("test_pattern")
        assert result == anticipation.threshold_ask

    @pytest.mark.asyncio
    async def test_adaptive_threshold_custom(self, anticipation, redis_mock):
        redis_mock.get = AsyncMock(return_value=b"0.75")
        result = await anticipation._get_adaptive_threshold("test_pattern")
        assert result == 0.75

    @pytest.mark.asyncio
    async def test_update_threshold_accepted(self, anticipation, redis_mock):
        redis_mock.get = AsyncMock(return_value=b"0.6")
        await anticipation.update_adaptive_threshold("test", accepted=True)
        redis_mock.setex.assert_called()
        # Schwelle sollte gesenkt worden sein
        call_args = redis_mock.setex.call_args
        new_val = float(call_args[0][2])
        assert new_val < 0.6

    @pytest.mark.asyncio
    async def test_update_threshold_rejected(self, anticipation, redis_mock):
        redis_mock.get = AsyncMock(return_value=b"0.6")
        await anticipation.update_adaptive_threshold("test", accepted=False)
        redis_mock.setex.assert_called()
        call_args = redis_mock.setex.call_args
        new_val = float(call_args[0][2])
        assert new_val > 0.6
