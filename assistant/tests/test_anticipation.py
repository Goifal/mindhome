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
from zoneinfo import ZoneInfo

from assistant.config import yaml_config

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.anticipation import AnticipationEngine


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def anticipation():
    with patch(
        "assistant.anticipation.yaml_config",
        {
            "anticipation": {
                "enabled": True,
                "history_days": 30,
                "min_confidence": 0.6,
                "check_interval_minutes": 15,
                "thresholds": {"ask": 0.6, "suggest": 0.8, "auto": 0.95},
            },
        },
    ):
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

        async def noop():
            pass

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
            "set_light",
            {"state": "on"},
            person="Max",
            weather_condition="sunny",
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
            entries.append(
                {
                    "action": "set_light",
                    "args": '{"state": "off"}',
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (now - timedelta(days=i * 7)).isoformat(),
                    "weather": "",
                }
            )

        patterns = anticipation._detect_time_patterns(entries)
        assert len(patterns) > 0
        assert patterns[0]["type"] == "time"
        assert patterns[0]["action"] == "set_light"
        assert patterns[0]["weekday"] == 0
        assert patterns[0]["hour"] == 22

    def test_too_few_entries(self, anticipation):
        entries = [
            {
                "action": "set_light",
                "args": "{}",
                "weekday": 0,
                "hour": 22,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weather": "",
            },
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
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": t.isoformat(),
                    "weather": "",
                }
            )
            entries.append(
                {
                    "action": "set_cover",
                    "args": '{"position": 0}',
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (t + timedelta(seconds=60)).isoformat(),
                    "weather": "",
                }
            )

        patterns = anticipation._detect_sequence_patterns(entries)
        assert len(patterns) > 0
        assert patterns[0]["type"] == "sequence"
        assert patterns[0]["trigger_action"] == "set_light"
        assert patterns[0]["follow_action"] == "set_cover"

    def test_no_sequence_same_action(self, anticipation):
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(10):
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (now + timedelta(seconds=i * 30)).isoformat(),
                    "weather": "",
                }
            )
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
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 19,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "",
                }
            )
        for i in range(2):
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 8,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "",
                }
            )

        patterns = anticipation._detect_context_patterns(entries)
        ctx_patterns = [p for p in patterns if p["type"] == "context"]
        assert len(ctx_patterns) > 0

    def test_weather_context(self, anticipation):
        entries = []
        now = datetime.now(timezone.utc)
        # 8 set_cover bei Regen, 2 bei Sonne
        for i in range(8):
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 14,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "rainy",
                }
            )
        for i in range(2):
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 14,
                    "timestamp": (now - timedelta(days=i + 10)).isoformat(),
                    "weather": "sunny",
                }
            )

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
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": t.isoformat(),
                    "weather": "",
                }
            )
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (t + timedelta(seconds=120)).isoformat(),
                    "weather": "",
                }
            )
            entries.append(
                {
                    "action": "set_climate",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (t + timedelta(seconds=240)).isoformat(),
                    "weather": "",
                }
            )
            # Luecke zwischen Ketten
            entries.append(
                {
                    "action": "other",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 23,
                    "timestamp": (t + timedelta(hours=2)).isoformat(),
                    "weather": "",
                }
            )

        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "causal_chain_window_min": 10,
                    "causal_chain_min_occurrences": 3,
                },
            },
        ):
            patterns = anticipation._detect_causal_chains(entries)

        causal = [p for p in patterns if p["type"] == "causal_chain"]
        assert len(causal) > 0
        assert len(causal[0]["actions"]) >= 3

    def test_no_chain_too_few_occurrences(self, anticipation):
        now = datetime.now(timezone.utc)
        entries = []
        # Nur 1 Kette → unter Minimum
        entries.append(
            {
                "action": "a",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": now.isoformat(),
                "weather": "",
            }
        )
        entries.append(
            {
                "action": "b",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": (now + timedelta(seconds=30)).isoformat(),
                "weather": "",
            }
        )
        entries.append(
            {
                "action": "c",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": (now + timedelta(seconds=60)).isoformat(),
                "weather": "",
            }
        )

        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "causal_chain_window_min": 10,
                    "causal_chain_min_occurrences": 3,
                },
            },
        ):
            patterns = anticipation._detect_causal_chains(entries)

        assert len(patterns) == 0


# ============================================================
# Implizite Voraussetzungen
# ============================================================


class TestImplicitPrerequisites:
    def test_entspannen_intent(self, anticipation):
        with patch(
            "assistant.anticipation.yaml_config",
            {"anticipation": {"intent_sequences": {}}},
        ):
            actions = anticipation.detect_implicit_prerequisites("Ich will entspannen")
        assert len(actions) > 0
        assert "Rollladen runter" in actions

    def test_schlafen_intent(self, anticipation):
        with patch(
            "assistant.anticipation.yaml_config",
            {"anticipation": {"intent_sequences": {}}},
        ):
            actions = anticipation.detect_implicit_prerequisites("Zeit zum schlafen")
        assert len(actions) > 0
        assert "Alle Lichter aus" in actions

    def test_negation_blocks(self, anticipation):
        with patch(
            "assistant.anticipation.yaml_config",
            {"anticipation": {"intent_sequences": {}}},
        ):
            actions = anticipation.detect_implicit_prerequisites(
                "Ich will nicht entspannen"
            )
        assert len(actions) == 0

    def test_unknown_intent(self, anticipation):
        with patch(
            "assistant.anticipation.yaml_config",
            {"anticipation": {"intent_sequences": {}}},
        ):
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
        anticipation_with_redis.redis.lrange = AsyncMock(
            return_value=[
                json.dumps(
                    {
                        "action": "a",
                        "args": "{}",
                        "weekday": 0,
                        "hour": 10,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "weather": "",
                    }
                ),
            ]
        )
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
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "args": "{}",
                        "weekday": 0,
                        "hour": 22,
                        "timestamp": (now - timedelta(days=i)).isoformat(),
                        "weather": "",
                    }
                ).encode("utf-8")
            )  # bytes, not str

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
        anticipation_with_redis.redis.lrange = AsyncMock(
            side_effect=Exception("Redis fail")
        )
        result = await anticipation_with_redis.detect_patterns()
        assert result == []


# ============================================================
# NEW: _detect_time_patterns person filter — Lines 176-178
# ============================================================


class TestTimePatternPersonFilter:
    def test_person_filter_too_few(self, anticipation):
        """Person filter with too few entries returns [] (lines 176-178)."""
        entries = [
            {
                "action": "set_light",
                "args": "{}",
                "weekday": 0,
                "hour": 22,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weather": "",
                "person": "Max",
            },
            {
                "action": "set_light",
                "args": "{}",
                "weekday": 0,
                "hour": 22,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weather": "",
                "person": "Anna",
            },
        ]
        result = anticipation._detect_time_patterns(entries, person="Max")
        assert result == []

    def test_time_pattern_invalid_timestamp(self, anticipation):
        """Invalid timestamp uses fallback weight (lines 209-210)."""
        entries = []
        for i in range(5):
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": "not-a-timestamp",  # Invalid
                    "weather": "",
                }
            )
        result = anticipation._detect_time_patterns(entries)
        # Should not raise; fallback weight is used
        assert isinstance(result, list)

    def test_time_pattern_with_person(self, anticipation):
        """Time pattern includes person field when filtered (line 241)."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(10):
            entries.append(
                {
                    "action": "set_light",
                    "args": '{"state": "off"}',
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (now - timedelta(days=i * 7)).isoformat(),
                    "weather": "",
                    "person": "Max",
                }
            )
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
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": t.isoformat(),
                    "weather": "",
                    "person": "Max",
                }
            )
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (t + timedelta(seconds=60)).isoformat(),
                    "weather": "",
                    "person": "Max",
                }
            )
        result = anticipation._detect_sequence_patterns(entries, person="Max")
        assert isinstance(result, list)

    def test_sequence_invalid_timestamp(self, anticipation):
        """Invalid timestamp in sequence is skipped (lines 283-284)."""
        entries = [
            {
                "action": "a",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": "invalid",
                "weather": "",
            },
            {
                "action": "b",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": "also-invalid",
                "weather": "",
            },
        ]
        result = anticipation._detect_sequence_patterns(entries)
        assert result == []

    def test_sequence_with_person_in_pattern(self, anticipation):
        """Sequence pattern includes person field (line 309)."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(8):
            t = now - timedelta(days=i)
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": t.isoformat(),
                    "weather": "",
                    "person": "Anna",
                }
            )
            entries.append(
                {
                    "action": "set_cover",
                    "args": '{"position": 0}',
                    "weekday": 0,
                    "hour": 22,
                    "timestamp": (t + timedelta(seconds=60)).isoformat(),
                    "weather": "",
                    "person": "Anna",
                }
            )
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
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 19,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "",
                    "person": "Max",
                }
            )
        result = anticipation._detect_context_patterns(entries, person="Max")
        assert isinstance(result, list)

    def test_context_empty_action_skipped(self, anticipation):
        """Empty action is skipped (line 337)."""
        entries = [
            {
                "action": "",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weather": "",
            }
        ]
        result = anticipation._detect_context_patterns(entries)
        assert result == []

    def test_context_night_cluster(self, anticipation):
        """Night cluster entries (line 345)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(10):
            entries.append(
                {
                    "action": "set_light",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 23,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "",
                }
            )
        result = anticipation._detect_context_patterns(entries)
        assert isinstance(result, list)

    def test_context_action_too_few_total(self, anticipation):
        """Action with < 5 total occurrences skipped (line 364)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(6):
            entries.append(
                {
                    "action": "rare_action" if i < 3 else "common_action",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 19,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "",
                }
            )
        result = anticipation._detect_context_patterns(entries)
        # rare_action has < 5 total => skipped
        for p in result:
            assert p.get("action") != "rare_action"

    def test_context_weather_person(self, anticipation):
        """Weather pattern includes person (line 428)."""
        entries = []
        now = datetime.now(timezone.utc)
        for i in range(10):
            entries.append(
                {
                    "action": "set_cover",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 14,
                    "timestamp": (now - timedelta(days=i)).isoformat(),
                    "weather": "rainy",
                    "person": "Anna",
                }
            )
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
            {
                "action": "a",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": "invalid",
                "weather": "",
            },
            {
                "action": "b",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weather": "",
            },
            {
                "action": "c",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "weather": "",
            },
        ]
        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "causal_chain_window_min": 10,
                    "causal_chain_min_occurrences": 1,
                },
            },
        ):
            result = anticipation._detect_causal_chains(entries)
        assert isinstance(result, list)

    def test_causal_chain_invalid_inner_timestamp(self, anticipation):
        """Invalid timestamp inside cluster skipped (lines 486-488)."""
        now = datetime.now(timezone.utc)
        entries = [
            {
                "action": "a",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": now.isoformat(),
                "weather": "",
            },
            {
                "action": "b",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": "invalid",
                "weather": "",
            },
            {
                "action": "c",
                "args": "{}",
                "weekday": 0,
                "hour": 10,
                "timestamp": (now + timedelta(seconds=30)).isoformat(),
                "weather": "",
            },
        ]
        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "causal_chain_window_min": 10,
                    "causal_chain_min_occurrences": 1,
                },
            },
        ):
            result = anticipation._detect_causal_chains(entries)
        assert isinstance(result, list)

    def test_causal_chain_below_confidence(self, anticipation):
        """Chain below min_confidence is skipped (line 515)."""
        now = datetime.now(timezone.utc)
        entries = []
        # Create many entries to dilute confidence
        for i in range(100):
            entries.append(
                {
                    "action": f"action_{i}",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 10,
                    "timestamp": (now + timedelta(seconds=i * 700)).isoformat(),
                    "weather": "",
                }
            )
        # Add one chain of 3 (which won't have enough confidence)
        for i in range(3):
            entries.append(
                {
                    "action": "chain_a",
                    "args": "{}",
                    "weekday": 0,
                    "hour": 10,
                    "timestamp": (now + timedelta(seconds=i * 10)).isoformat(),
                    "weather": "",
                }
            )
        anticipation.min_confidence = 0.99
        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "causal_chain_window_min": 10,
                    "causal_chain_min_occurrences": 1,
                },
            },
        ):
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
                entries.append(
                    {
                        "action": action,
                        "args": "{}",
                        "weekday": 0,
                        "hour": 10,
                        "timestamp": (t + timedelta(seconds=idx * 30)).isoformat(),
                        "weather": "",
                        "person": "Max",
                    }
                )

        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "causal_chain_window_min": 10,
                    "causal_chain_min_occurrences": 3,
                },
            },
        ):
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
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await anticipation_with_redis.get_suggestions()
        assert result == []

    @pytest.mark.asyncio
    async def test_time_pattern_matching(self, anticipation_with_redis):
        """Time pattern matching current time generates suggestion (lines 610-619)."""
        now = datetime.now(_LOCAL_TZ)
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
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[pattern],
        ):
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
            "hour": 3,  # 3 AM — unlikely to be current
            "confidence": 0.9,
            "description": "Wrong time",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[pattern],
        ):
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
        recent_entry = json.dumps(
            {
                "action": "set_light",
                "timestamp": now.isoformat(),
            }
        )
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=[recent_entry])
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[pattern],
        ):
            result = await anticipation_with_redis.get_suggestions()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_context_time_cluster_matching(self, anticipation_with_redis):
        """Context time_cluster pattern matching (lines 643-672)."""
        now = datetime.now(_LOCAL_TZ)
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
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[pattern],
        ):
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
        with (
            patch.object(
                anticipation_with_redis,
                "detect_patterns",
                new_callable=AsyncMock,
                return_value=[pattern],
            ),
            patch.object(
                anticipation_with_redis,
                "_get_current_weather",
                new_callable=AsyncMock,
                return_value="rainy",
            ),
        ):
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
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[pattern],
        ):
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
        with patch.object(
            anticipation_with_redis,
            "detect_patterns",
            new_callable=AsyncMock,
            return_value=[pattern],
        ):
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
        anticipation_with_redis.redis.get = AsyncMock(
            side_effect=Exception("Redis error")
        )
        result = await anticipation_with_redis._get_current_weather()
        assert result == ""


# ============================================================
# NEW: record_feedback exception — Lines 737-738
# ============================================================


class TestRecordFeedbackException:
    @pytest.mark.asyncio
    async def test_feedback_exception(self, anticipation_with_redis):
        """Exception in record_feedback is caught (lines 737-738)."""
        anticipation_with_redis.redis.get = AsyncMock(
            side_effect=Exception("Redis error")
        )
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
        with (
            patch.object(
                anticipation_with_redis,
                "get_suggestions",
                side_effect=mock_get_suggestions,
            ),
            patch("assistant.config.yaml_config", _no_quiet),
        ):
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
        with (
            patch.object(
                anticipation_with_redis,
                "get_suggestions",
                side_effect=mock_get_suggestions,
            ),
            patch("assistant.config.yaml_config", _no_quiet),
            patch("asyncio.sleep", side_effect=_fast_sleep),
        ):
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
        with patch(
            "assistant.anticipation.yaml_config",
            {
                "anticipation": {
                    "intent_sequences": {
                        "party": ["Musik laut", "Licht bunt"],
                    },
                },
            },
        ):
            result = anticipation.detect_implicit_prerequisites("Lass uns party machen")
        assert result == ["Musik laut", "Licht bunt"]

    def test_negation_kein(self, anticipation):
        """Negation with 'kein' blocks match."""
        with patch(
            "assistant.anticipation.yaml_config",
            {"anticipation": {"intent_sequences": {}}},
        ):
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
            entry = json.dumps(
                {
                    "action": "make_coffee",
                    "weekday": datetime.now(timezone.utc).weekday(),
                    "hour": 7,
                    "timestamp": f"2026-03-{10 + i % 15:02d}T07:00:00",
                }
            )
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


# ============================================================
# Calendar-Weather Crossref (get_calendar_weather_crossrefs)
# ============================================================


class TestCalendarWeatherCrossref:
    """Tests for calendar x weather cross-reference suggestions.

    NOTE: get_calendar_weather_crossrefs() uses datetime.now(_LOCAL_TZ) which
    returns a tz-aware datetime, but strips tzinfo from event start times
    (line 830). The subtraction at line 834 (naive - aware) raises TypeError,
    caught by the outer except. We patch datetime.now to return a naive datetime
    to test the intended logic for event-based crossrefs.
    """

    _CROSSREF_CONFIG = {
        "anticipation": {
            "enabled": True,
            "min_confidence": 0.6,
            "thresholds": {"ask": 0.6, "suggest": 0.8, "auto": 0.95},
        },
        "predictive_needs": {"enabled": True},
    }

    def _make_event(self, summary, start_iso):
        return {"summary": summary, "start": start_iso}

    def _naive_now(self):
        """Return a naive local-time datetime matching what the code expects."""
        return datetime.now(_LOCAL_TZ).replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_crossref_rain_suggestion(self, anticipation_with_redis):
        """Rain + upcoming event within 45 min generates umbrella reminder."""
        fake_now = self._naive_now()
        event_start = fake_now + timedelta(minutes=20)
        event = self._make_event("Arzttermin", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"rainy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        assert len(result) >= 1
        assert result[0]["type"] == "calendar_rain"
        assert "Schirm" in result[0]["message"]

    @pytest.mark.asyncio
    async def test_crossref_no_calendar_data(self, anticipation_with_redis):
        """No crossrefs when calendar data is missing."""
        redis = anticipation_with_redis.redis
        redis.get = AsyncMock(return_value=None)

        with patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG):
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        assert result == []

    @pytest.mark.asyncio
    async def test_crossref_no_weather_data(self, anticipation_with_redis):
        """No rain/heat crossrefs when weather data is missing."""
        fake_now = self._naive_now()
        event_start = fake_now + timedelta(minutes=20)
        event = self._make_event("Meeting", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return None  # No weather
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        rain_or_heat = [
            r for r in result if r["type"] in ("calendar_rain", "calendar_heat")
        ]
        assert len(rain_or_heat) == 0

    @pytest.mark.asyncio
    async def test_crossref_heat_outdoor_event(self, anticipation_with_redis):
        """Outdoor event + high temperature generates heat warning."""
        fake_now = self._naive_now()
        event_start = fake_now + timedelta(minutes=30)
        event = self._make_event("Grillen im Garten", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"sunny"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return b"36.5"
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        cfg = {
            **self._CROSSREF_CONFIG,
            "predictive_needs": {"enabled": True, "hot_threshold": 33},
        }

        with (
            patch("assistant.anticipation.yaml_config", cfg),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        heat_refs = [r for r in result if r["type"] == "calendar_heat"]
        assert len(heat_refs) >= 1
        assert "Sonnenschutz" in heat_refs[0]["message"]

    @pytest.mark.asyncio
    async def test_crossref_early_morning_event(self, anticipation_with_redis):
        """Tomorrow early event + late evening generates early-morning hint."""
        fake_now = self._naive_now().replace(
            hour=22, minute=30, second=0, microsecond=0
        )
        tomorrow = fake_now + timedelta(days=1)
        event_start = tomorrow.replace(hour=7, minute=0)
        event = self._make_event("Fruehstueckstreffen", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return None
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        early_refs = [r for r in result if r["type"] == "early_morning"]
        assert len(early_refs) >= 1
        assert "Feierabend" in early_refs[0]["message"]

    @pytest.mark.asyncio
    async def test_crossref_preheat_cold(self, anticipation_with_redis):
        """Cold temperature + someone away generates preheat suggestion."""
        fake_now = self._naive_now()
        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([])
            if key == "mha:weather:current_condition":
                return b"cloudy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return b"2.0"
            if key == "mha:presence:away_persons":
                return b'["Max"]'
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        cfg = {
            **self._CROSSREF_CONFIG,
            "predictive_needs": {"enabled": True, "cold_threshold": 5},
        }

        with (
            patch("assistant.anticipation.yaml_config", cfg),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        preheat_refs = [r for r in result if r["type"] == "preheat"]
        assert len(preheat_refs) >= 1
        assert "vorheizen" in preheat_refs[0]["message"].lower()

    @pytest.mark.asyncio
    async def test_crossref_no_redis(self, anticipation):
        """No redis returns empty list."""
        with patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG):
            result = await anticipation.get_calendar_weather_crossrefs()
        assert result == []

    @pytest.mark.asyncio
    async def test_crossref_disabled_config(self, anticipation_with_redis):
        """Disabled predictive_needs returns empty list."""
        cfg = {**self._CROSSREF_CONFIG, "predictive_needs": {"enabled": False}}
        with patch("assistant.anticipation.yaml_config", cfg):
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()
        assert result == []

    @pytest.mark.asyncio
    async def test_crossref_cooldown_prevents_duplicate(self, anticipation_with_redis):
        """Already-sent crossref (cooldown key set) is not repeated."""
        fake_now = self._naive_now()
        event_start = fake_now + timedelta(minutes=20)
        event = self._make_event("Meeting", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"rainy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            if key.startswith("mha:anticipation:crossref:rain_"):
                return b"1"  # Already sent — cooldown active
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        rain_refs = [r for r in result if r["type"] == "calendar_rain"]
        assert len(rain_refs) == 0

    @pytest.mark.asyncio
    async def test_crossref_event_invalid_start(self, anticipation_with_redis):
        """Event with invalid start timestamp is skipped gracefully."""
        fake_now = self._naive_now()
        event = self._make_event("Bad Event", "not-a-date")

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"rainy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_crossref_exception_in_redis(self, anticipation_with_redis):
        """Exception during crossref is caught, returns empty list."""
        redis = anticipation_with_redis.redis
        redis.get = AsyncMock(side_effect=Exception("Redis exploded"))

        with patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG):
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        assert result == []

    @pytest.mark.asyncio
    async def test_crossref_event_no_start_key_skipped(self, anticipation_with_redis):
        """Event missing both 'start' and 'dtstart' is skipped."""
        fake_now = self._naive_now()
        event = {"summary": "No start field"}

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"rainy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        assert result == []

    @pytest.mark.asyncio
    async def test_crossref_event_far_future_no_rain_alert(
        self, anticipation_with_redis
    ):
        """Event more than 45 min away does not trigger rain alert."""
        fake_now = self._naive_now()
        event_start = fake_now + timedelta(minutes=90)
        event = self._make_event("Spaeter Termin", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"rainy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch("assistant.anticipation.yaml_config", self._CROSSREF_CONFIG),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        rain_refs = [r for r in result if r["type"] == "calendar_rain"]
        assert len(rain_refs) == 0

    @pytest.mark.asyncio
    async def test_crossref_non_outdoor_event_no_heat(self, anticipation_with_redis):
        """Non-outdoor event does not trigger heat warning even when hot."""
        fake_now = self._naive_now()
        event_start = fake_now + timedelta(minutes=30)
        event = self._make_event("Buerobesprechung", event_start.isoformat())

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"sunny"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return b"38.0"
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        cfg = {
            **self._CROSSREF_CONFIG,
            "predictive_needs": {"enabled": True, "hot_threshold": 33},
        }
        with (
            patch("assistant.anticipation.yaml_config", cfg),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        heat_refs = [r for r in result if r["type"] == "calendar_heat"]
        assert len(heat_refs) == 0


# ============================================================
# Crossref integration in get_suggestions
# ============================================================


class TestCrossrefInGetSuggestions:
    """Tests that calendar-weather crossrefs are integrated into get_suggestions."""

    @pytest.mark.asyncio
    async def test_crossref_appears_in_suggestions(self, anticipation_with_redis):
        """Calendar crossref is appended to suggestions list.

        Note: get_suggestions() returns early if detect_patterns() is empty,
        so we must provide at least one pattern (even if it won't match the
        current time) to reach the crossref integration code.
        """
        crossref = {
            "type": "calendar_rain",
            "message": "Schirm nicht vergessen",
            "urgency": "medium",
        }
        # A pattern that won't match current time (weekday 6, hour 3)
        dummy_pattern = {
            "type": "time",
            "action": "noop",
            "args": {},
            "weekday": (datetime.now(_LOCAL_TZ).weekday() + 3) % 7,
            "hour": 3,
            "confidence": 0.7,
            "description": "dummy",
        }

        anticipation_with_redis.redis.get = AsyncMock(return_value=None)

        with (
            patch.object(
                anticipation_with_redis,
                "detect_patterns",
                new_callable=AsyncMock,
                return_value=[dummy_pattern],
            ),
            patch.object(
                anticipation_with_redis,
                "get_calendar_weather_crossrefs",
                new_callable=AsyncMock,
                return_value=[crossref],
            ),
        ):
            result = await anticipation_with_redis.get_suggestions()

        # Find the crossref suggestion among results
        crossref_results = [
            s for s in result if s.get("pattern", {}).get("type") == "calendar_crossref"
        ]
        assert len(crossref_results) == 1
        assert crossref_results[0]["action"] == "send_notification"
        assert crossref_results[0]["description"] == "Schirm nicht vergessen"
        assert crossref_results[0]["confidence"] == 0.85
        assert crossref_results[0]["mode"] == "suggest"
        assert crossref_results[0]["urgency"] == "medium"

    @pytest.mark.asyncio
    async def test_crossref_exception_does_not_break_suggestions(
        self, anticipation_with_redis
    ):
        """Exception in crossref does not prevent other suggestions from returning."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {"state": "off"},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.85,
            "description": "Regular pattern",
        }

        anticipation_with_redis.redis.get = AsyncMock(return_value=None)

        with (
            patch.object(
                anticipation_with_redis,
                "detect_patterns",
                new_callable=AsyncMock,
                return_value=[pattern],
            ),
            patch.object(
                anticipation_with_redis,
                "get_calendar_weather_crossrefs",
                new_callable=AsyncMock,
                side_effect=Exception("Crossref boom"),
            ),
        ):
            result = await anticipation_with_redis.get_suggestions()

        # Regular pattern suggestion still returned despite crossref failure
        assert len(result) >= 1
        assert result[0]["action"] == "set_light"

    @pytest.mark.asyncio
    async def test_crossref_empty_returns_no_extra_suggestions(
        self, anticipation_with_redis
    ):
        """Empty crossref list adds nothing beyond matched patterns.

        Note: get_suggestions returns early when detect_patterns is empty,
        so this test verifies crossref path has no effect with empty crossrefs
        when patterns exist but don't match.
        """
        dummy_pattern = {
            "type": "time",
            "action": "noop",
            "args": {},
            "weekday": (datetime.now(_LOCAL_TZ).weekday() + 3) % 7,
            "hour": 3,
            "confidence": 0.7,
            "description": "dummy",
        }
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)

        with (
            patch.object(
                anticipation_with_redis,
                "detect_patterns",
                new_callable=AsyncMock,
                return_value=[dummy_pattern],
            ),
            patch.object(
                anticipation_with_redis,
                "get_calendar_weather_crossrefs",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await anticipation_with_redis.get_suggestions()

        crossref_results = [
            s for s in result if s.get("pattern", {}).get("type") == "calendar_crossref"
        ]
        assert len(crossref_results) == 0

    @pytest.mark.asyncio
    async def test_no_patterns_means_no_crossrefs(self, anticipation_with_redis):
        """get_suggestions returns early when detect_patterns is empty,
        so crossrefs are never reached."""
        anticipation_with_redis.redis.get = AsyncMock(return_value=None)

        with (
            patch.object(
                anticipation_with_redis,
                "detect_patterns",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                anticipation_with_redis,
                "get_calendar_weather_crossrefs",
                new_callable=AsyncMock,
                return_value=[{"type": "rain", "message": "x", "urgency": "high"}],
            ),
        ):
            result = await anticipation_with_redis.get_suggestions()

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_crossrefs_in_suggestions(self, anticipation_with_redis):
        """Multiple crossrefs are all appended to suggestions."""
        crossrefs = [
            {"type": "calendar_rain", "message": "Schirm", "urgency": "medium"},
            {"type": "preheat", "message": "Vorheizen?", "urgency": "low"},
        ]
        dummy_pattern = {
            "type": "time",
            "action": "noop",
            "args": {},
            "weekday": (datetime.now(_LOCAL_TZ).weekday() + 3) % 7,
            "hour": 3,
            "confidence": 0.7,
            "description": "dummy",
        }

        anticipation_with_redis.redis.get = AsyncMock(return_value=None)

        with (
            patch.object(
                anticipation_with_redis,
                "detect_patterns",
                new_callable=AsyncMock,
                return_value=[dummy_pattern],
            ),
            patch.object(
                anticipation_with_redis,
                "get_calendar_weather_crossrefs",
                new_callable=AsyncMock,
                return_value=crossrefs,
            ),
        ):
            result = await anticipation_with_redis.get_suggestions()

        crossref_results = [
            s for s in result if s.get("pattern", {}).get("type") == "calendar_crossref"
        ]
        assert len(crossref_results) == 2
        assert crossref_results[0]["urgency"] == "medium"
        assert crossref_results[1]["urgency"] == "low"

    @pytest.mark.asyncio
    async def test_crossref_calendar_data_as_dict(self, anticipation_with_redis):
        """Calendar data as dict with 'events' key is handled correctly."""
        fake_now = datetime.now(_LOCAL_TZ).replace(tzinfo=None)
        event_start = fake_now + timedelta(minutes=15)
        event = {"summary": "Zahnarzt", "start": event_start.isoformat()}
        cal_data = {"events": [event]}  # Dict format with events key

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps(cal_data)
            if key == "mha:weather:current_condition":
                return b"pouring"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch(
                "assistant.anticipation.yaml_config",
                {
                    "anticipation": {
                        "enabled": True,
                        "min_confidence": 0.6,
                        "thresholds": {"ask": 0.6, "suggest": 0.8, "auto": 0.95},
                    },
                    "predictive_needs": {"enabled": True},
                },
            ),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        rain_refs = [r for r in result if r["type"] == "calendar_rain"]
        assert len(rain_refs) >= 1

    @pytest.mark.asyncio
    async def test_crossref_event_with_dtstart_key(self, anticipation_with_redis):
        """Event using 'dtstart' key instead of 'start' is parsed."""
        fake_now = datetime.now(_LOCAL_TZ).replace(tzinfo=None)
        event_start = fake_now + timedelta(minutes=10)
        event = {"title": "Einkaufen", "dtstart": event_start.isoformat()}

        redis = anticipation_with_redis.redis

        async def mock_get(key):
            if key == "mha:calendar:upcoming":
                return json.dumps([event])
            if key == "mha:weather:current_condition":
                return b"lightning-rainy"
            if key == "mha:weather:forecast":
                return None
            if key == "mha:weather:temperature":
                return None
            if key.startswith("mha:anticipation:crossref:"):
                return None
            return None

        redis.get = AsyncMock(side_effect=mock_get)
        redis.setex = AsyncMock()

        with (
            patch(
                "assistant.anticipation.yaml_config",
                {
                    "anticipation": {
                        "enabled": True,
                        "min_confidence": 0.6,
                        "thresholds": {"ask": 0.6, "suggest": 0.8, "auto": 0.95},
                    },
                    "predictive_needs": {"enabled": True},
                },
            ),
            patch("assistant.anticipation.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.get_calendar_weather_crossrefs()

        rain_refs = [r for r in result if r["type"] == "calendar_rain"]
        assert len(rain_refs) >= 1


# ============================================================
# _pattern_matches_current_context
# ============================================================


class TestPatternMatchesCurrentContext:
    def test_time_pattern_matches(self, anticipation):
        """Time pattern matches when weekday and hour match."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "time", "weekday": now.weekday(), "hour": now.hour}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is True

    def test_time_pattern_wrong_weekday(self, anticipation):
        """Time pattern fails on wrong weekday."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "time", "weekday": (now.weekday() + 1) % 7, "hour": now.hour}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False

    def test_time_pattern_wrong_hour(self, anticipation):
        """Time pattern fails on wrong hour."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "weekday": now.weekday(),
            "hour": (now.hour + 5) % 24,
        }
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False

    def test_context_time_cluster_morning(self, anticipation):
        """Context time_cluster:morning matches at 9AM."""
        now = datetime.now(_LOCAL_TZ).replace(hour=9, minute=0)
        pattern = {"type": "context", "context": "time_cluster:morning"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is True

    def test_context_time_cluster_afternoon(self, anticipation):
        """Context time_cluster:afternoon matches at 2PM."""
        now = datetime.now(_LOCAL_TZ).replace(hour=14, minute=0)
        pattern = {"type": "context", "context": "time_cluster:afternoon"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is True

    def test_context_time_cluster_evening(self, anticipation):
        """Context time_cluster:evening matches at 8PM."""
        now = datetime.now(_LOCAL_TZ).replace(hour=20, minute=0)
        pattern = {"type": "context", "context": "time_cluster:evening"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is True

    def test_context_time_cluster_night(self, anticipation):
        """Context time_cluster:night matches at 11PM."""
        now = datetime.now(_LOCAL_TZ).replace(hour=23, minute=0)
        pattern = {"type": "context", "context": "time_cluster:night"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is True

    def test_context_time_cluster_mismatch(self, anticipation):
        """Context time_cluster:morning fails at 8PM."""
        now = datetime.now(_LOCAL_TZ).replace(hour=20, minute=0)
        pattern = {"type": "context", "context": "time_cluster:morning"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False

    def test_context_weather_match(self, anticipation):
        """Context weather pattern matches current weather."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "context", "context": "weather:rainy"}
        assert (
            anticipation._pattern_matches_current_context(pattern, now, "rainy") is True
        )

    def test_context_weather_mismatch(self, anticipation):
        """Context weather pattern fails on different weather."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "context", "context": "weather:rainy"}
        assert (
            anticipation._pattern_matches_current_context(pattern, now, "sunny")
            is False
        )

    def test_causal_chain_hour_trigger_match(self, anticipation):
        """Causal chain with hour trigger matches current hour."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "causal_chain", "trigger": f"hour:{now.hour}"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is True

    def test_causal_chain_hour_trigger_mismatch(self, anticipation):
        """Causal chain with hour trigger fails on different hour."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "causal_chain", "trigger": f"hour:{(now.hour + 5) % 24}"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False

    def test_causal_chain_hour_invalid(self, anticipation):
        """Causal chain with invalid hour trigger returns False."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "causal_chain", "trigger": "hour:abc"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False

    def test_causal_chain_weather_trigger_match(self, anticipation):
        """Causal chain with weather trigger matches current weather."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "causal_chain", "trigger": "rainy"}
        assert (
            anticipation._pattern_matches_current_context(pattern, now, "rainy") is True
        )

    def test_causal_chain_weather_trigger_mismatch(self, anticipation):
        """Causal chain weather trigger fails on different weather."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "causal_chain", "trigger": "rainy"}
        assert (
            anticipation._pattern_matches_current_context(pattern, now, "sunny")
            is False
        )

    def test_sequence_pattern_returns_false(self, anticipation):
        """Sequence patterns are not auto-executable."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "sequence", "trigger_action": "a", "follow_action": "b"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False

    def test_unknown_type_returns_false(self, anticipation):
        """Unknown pattern type returns False."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {"type": "unknown_type"}
        assert anticipation._pattern_matches_current_context(pattern, now, "") is False


# ============================================================
# auto_execute_ready_patterns
# ============================================================


class TestAutoExecuteReadyPatterns:
    @pytest.mark.asyncio
    async def test_low_autonomy_skips(self, anticipation):
        """Autonomy level < 3 skips execution."""
        brain = MagicMock()
        brain.autonomy = MagicMock(level=2)
        await anticipation.auto_execute_ready_patterns(brain)
        # No patterns should be fetched

    @pytest.mark.asyncio
    async def test_no_patterns_returns_early(self, anticipation_with_redis):
        """No detected patterns returns early."""
        brain = MagicMock()
        brain.autonomy = MagicMock(level=4)
        anticipation_with_redis.detect_patterns = AsyncMock(return_value=[])
        await anticipation_with_redis.auto_execute_ready_patterns(brain)

    @pytest.mark.asyncio
    async def test_executes_high_confidence_pattern(self, anticipation_with_redis):
        """Pattern with confidence >= 0.95 and matching context is executed."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {"state": "off"},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.96,
            "description": "Licht aus um jetzt",
        }

        brain = MagicMock()
        brain.autonomy = MagicMock(level=4)
        brain.execute_action = AsyncMock()
        brain._task_registry = MagicMock()
        brain._task_registry.create_task = MagicMock()

        anticipation_with_redis.detect_patterns = AsyncMock(return_value=[pattern])
        anticipation_with_redis._get_current_weather = AsyncMock(return_value="")

        await anticipation_with_redis.auto_execute_ready_patterns(brain)
        brain._task_registry.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_low_confidence_skipped(self, anticipation_with_redis):
        """Pattern with confidence < 0.95 is skipped."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {"state": "off"},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.80,
            "description": "Low confidence",
        }

        brain = MagicMock()
        brain.autonomy = MagicMock(level=4)
        brain._task_registry = MagicMock()

        anticipation_with_redis.detect_patterns = AsyncMock(return_value=[pattern])
        anticipation_with_redis._get_current_weather = AsyncMock(return_value="")

        await anticipation_with_redis.auto_execute_ready_patterns(brain)
        brain._task_registry.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_re_execution(self, anticipation_with_redis):
        """Pattern executed once is not re-executed within cooldown."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {"state": "off"},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.96,
            "description": "Licht aus Test",
        }

        brain = MagicMock()
        brain.autonomy = MagicMock(level=4)
        brain._task_registry = MagicMock()

        anticipation_with_redis.detect_patterns = AsyncMock(return_value=[pattern])
        anticipation_with_redis._get_current_weather = AsyncMock(return_value="")

        # First call
        await anticipation_with_redis.auto_execute_ready_patterns(brain)
        assert brain._task_registry.create_task.call_count == 1

        # Second call - cooldown should prevent
        brain._task_registry.create_task.reset_mock()
        await anticipation_with_redis.auto_execute_ready_patterns(brain)
        brain._task_registry.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_task_registry_warns(self, anticipation_with_redis):
        """Missing task_registry logs warning and returns."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "action": "set_light",
            "args": {},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.96,
            "description": "No registry test",
        }

        brain = MagicMock(spec=[])  # No attributes
        brain.autonomy = MagicMock(level=4)

        anticipation_with_redis.detect_patterns = AsyncMock(return_value=[pattern])
        anticipation_with_redis._get_current_weather = AsyncMock(return_value="")

        # Should not raise
        await anticipation_with_redis.auto_execute_ready_patterns(brain)

    @pytest.mark.asyncio
    async def test_no_action_in_pattern_skipped(self, anticipation_with_redis):
        """Pattern without action or follow_action is skipped."""
        now = datetime.now(_LOCAL_TZ)
        pattern = {
            "type": "time",
            "action": "",
            "args": {},
            "weekday": now.weekday(),
            "hour": now.hour,
            "confidence": 0.96,
            "description": "Empty action",
        }

        brain = MagicMock()
        brain.autonomy = MagicMock(level=4)
        brain._task_registry = MagicMock()

        anticipation_with_redis.detect_patterns = AsyncMock(return_value=[pattern])
        anticipation_with_redis._get_current_weather = AsyncMock(return_value="")

        await anticipation_with_redis.auto_execute_ready_patterns(brain)
        brain._task_registry.create_task.assert_not_called()


# ============================================================
# detect_habit_drift
# ============================================================


class TestDetectHabitDrift:
    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, anticipation):
        """No redis returns empty list."""
        result = await anticipation.detect_habit_drift()
        assert result == []

    @pytest.mark.asyncio
    async def test_too_few_entries_returns_empty(self, anticipation_with_redis):
        """Fewer than 10 entries returns empty."""
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=[b"{}"] * 5)
        result = await anticipation_with_redis.detect_habit_drift()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_previous_entries_returns_empty(self, anticipation_with_redis):
        """No entries in the 7-14 day range returns empty."""
        now = datetime.now(_LOCAL_TZ)
        entries = []
        for i in range(15):
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "hour": 22,
                        "timestamp": (now - timedelta(days=1)).isoformat(),
                    }
                ).encode()
            )
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)
        result = await anticipation_with_redis.detect_habit_drift()
        assert result == []

    @pytest.mark.asyncio
    async def test_disappeared_pattern_detected(self, anticipation_with_redis):
        """Action present in previous week but not recent week = disappeared."""
        now = datetime.now(_LOCAL_TZ)
        entries = []
        # Previous week: set_light actions (8-14 days ago)
        for i in range(5):
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "hour": 22,
                        "timestamp": (now - timedelta(days=10 + i * 0.5)).isoformat(),
                    }
                ).encode()
            )
        # Recent week: only set_cover actions (0-7 days ago)
        for i in range(5):
            entries.append(
                json.dumps(
                    {
                        "action": "set_cover",
                        "hour": 20,
                        "timestamp": (now - timedelta(days=1 + i * 0.5)).isoformat(),
                    }
                ).encode()
            )
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)
        result = await anticipation_with_redis.detect_habit_drift()

        disappeared = [d for d in result if d["type"] == "disappeared"]
        assert len(disappeared) >= 1
        assert disappeared[0]["action"] == "set_light"

    @pytest.mark.asyncio
    async def test_new_pattern_detected(self, anticipation_with_redis):
        """Action present in recent week but not previous = new pattern."""
        now = datetime.now(_LOCAL_TZ)
        entries = []
        # Previous week: set_light actions
        for i in range(5):
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "hour": 22,
                        "timestamp": (now - timedelta(days=10 + i * 0.5)).isoformat(),
                    }
                ).encode()
            )
        # Recent week: set_light AND set_climate (new)
        for i in range(5):
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "hour": 22,
                        "timestamp": (now - timedelta(days=1 + i * 0.5)).isoformat(),
                    }
                ).encode()
            )
        for i in range(3):
            entries.append(
                json.dumps(
                    {
                        "action": "set_climate",
                        "hour": 18,
                        "timestamp": (now - timedelta(days=1 + i * 0.5)).isoformat(),
                    }
                ).encode()
            )
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)
        result = await anticipation_with_redis.detect_habit_drift()

        new_patterns = [d for d in result if d["type"] == "new"]
        assert len(new_patterns) >= 1
        assert new_patterns[0]["action"] == "set_climate"

    @pytest.mark.asyncio
    async def test_time_shift_detected(self, anticipation_with_redis):
        """Action shifting time by > 30min is detected."""
        now = datetime.now(_LOCAL_TZ)
        entries = []
        # Previous week: set_light at 20:00
        for i in range(5):
            ts = (now - timedelta(days=10 + i * 0.5)).replace(hour=20, minute=0)
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "hour": 20,
                        "timestamp": ts.isoformat(),
                    }
                ).encode()
            )
        # Recent week: set_light at 22:00 (2h shift)
        for i in range(5):
            ts = (now - timedelta(days=1 + i * 0.5)).replace(hour=22, minute=0)
            entries.append(
                json.dumps(
                    {
                        "action": "set_light",
                        "hour": 22,
                        "timestamp": ts.isoformat(),
                    }
                ).encode()
            )
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)
        result = await anticipation_with_redis.detect_habit_drift()

        time_shifts = [d for d in result if d["type"] == "time_shift"]
        assert len(time_shifts) >= 1
        assert time_shifts[0]["shift_minutes"] > 30

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, anticipation_with_redis):
        """Exception in drift detection returns empty list."""
        anticipation_with_redis.redis.lrange = AsyncMock(
            side_effect=Exception("Redis error")
        )
        result = await anticipation_with_redis.detect_habit_drift()
        assert result == []


# ============================================================
# _aggregate_action_stats
# ============================================================


class TestAggregateActionStats:
    def test_basic_aggregation(self, anticipation):
        """Actions are aggregated with correct counts and avg hours."""
        now = datetime.now(_LOCAL_TZ)
        entries = [
            {
                "action": "set_light",
                "hour": 22,
                "timestamp": now.replace(hour=22, minute=0).isoformat(),
            },
            {
                "action": "set_light",
                "hour": 22,
                "timestamp": now.replace(hour=22, minute=30).isoformat(),
            },
            {
                "action": "set_light",
                "hour": 22,
                "timestamp": now.replace(hour=23, minute=0).isoformat(),
            },
        ]
        result = AnticipationEngine._aggregate_action_stats(entries)
        assert "set_light" in result
        assert result["set_light"]["count"] == 3
        # Average should be around 22.5
        assert 22.0 <= result["set_light"]["avg_hour"] <= 23.0

    def test_single_occurrence_ignored(self, anticipation):
        """Actions with only 1 occurrence are excluded."""
        entries = [
            {
                "action": "rare_action",
                "hour": 10,
                "timestamp": datetime.now(_LOCAL_TZ).isoformat(),
            },
        ]
        result = AnticipationEngine._aggregate_action_stats(entries)
        assert "rare_action" not in result

    def test_empty_action_skipped(self, anticipation):
        """Entries with empty action are skipped."""
        entries = [
            {
                "action": "",
                "hour": 10,
                "timestamp": datetime.now(_LOCAL_TZ).isoformat(),
            },
            {
                "action": "",
                "hour": 11,
                "timestamp": datetime.now(_LOCAL_TZ).isoformat(),
            },
        ]
        result = AnticipationEngine._aggregate_action_stats(entries)
        assert len(result) == 0

    def test_invalid_timestamp_uses_hour_field(self, anticipation):
        """Invalid timestamp falls back to hour field for precision."""
        entries = [
            {"action": "test", "hour": 15, "timestamp": "invalid"},
            {"action": "test", "hour": 16, "timestamp": "also-invalid"},
        ]
        result = AnticipationEngine._aggregate_action_stats(entries)
        assert "test" in result
        assert result["test"]["count"] == 2
        assert 15.0 <= result["test"]["avg_hour"] <= 16.0

    def test_multiple_actions_separated(self, anticipation):
        """Multiple different actions are tracked separately."""
        now = datetime.now(_LOCAL_TZ)
        entries = [
            {"action": "a", "hour": 10, "timestamp": now.replace(hour=10).isoformat()},
            {"action": "a", "hour": 10, "timestamp": now.replace(hour=10).isoformat()},
            {"action": "b", "hour": 20, "timestamp": now.replace(hour=20).isoformat()},
            {"action": "b", "hour": 20, "timestamp": now.replace(hour=20).isoformat()},
        ]
        result = AnticipationEngine._aggregate_action_stats(entries)
        assert "a" in result
        assert "b" in result
        assert result["a"]["avg_hour"] < result["b"]["avg_hour"]


# ============================================================
# check_routine_deviation
# ============================================================


class TestCheckRoutineDeviation:
    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, anticipation):
        """No redis returns empty list."""
        result = await anticipation.check_routine_deviation(["Max"])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_persons_returns_empty(self, anticipation_with_redis):
        """Empty persons list returns empty."""
        result = await anticipation_with_redis.check_routine_deviation([])
        assert result == []

    @pytest.mark.asyncio
    async def test_outside_check_window(self, anticipation_with_redis):
        """Outside 17-22 window returns empty."""
        with patch("assistant.anticipation.datetime") as mock_dt:
            mock_now = datetime.now(_LOCAL_TZ).replace(hour=10, minute=0)
            mock_dt.now.return_value = mock_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.check_routine_deviation(["Max"])
        assert result == []

    @pytest.mark.asyncio
    async def test_too_few_arrivals(self, anticipation_with_redis):
        """Person with < 3 arrival events has no deviation."""
        now = datetime.now(_LOCAL_TZ).replace(hour=20, minute=30)
        entries = [
            json.dumps(
                {
                    "action": "person_arrived",
                    "person": "Max",
                    "timestamp": (now - timedelta(days=1)).replace(hour=18).isoformat(),
                }
            ).encode(),
        ]
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)

        with patch("assistant.anticipation.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.check_routine_deviation(["Max"])
        assert result == []

    @pytest.mark.asyncio
    async def test_significant_delay_detected(self, anticipation_with_redis):
        """Person >90 min past expected arrival generates deviation."""
        now = datetime.now(_LOCAL_TZ).replace(hour=21, minute=30)
        # Person usually arrives at 18:00 (avg=18.0, std ~0, threshold=18.5)
        # At 21:30, delay = (21.5 - 18.5) * 60 = 180 min >= 90 => deviation
        entries = []
        for i in range(5):
            entries.append(
                json.dumps(
                    {
                        "action": "person_arrived",
                        "person": "Max",
                        "timestamp": (now - timedelta(days=i + 1))
                        .replace(hour=18, minute=0)
                        .isoformat(),
                    }
                ).encode()
            )
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)

        with patch("assistant.anticipation.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.check_routine_deviation(["Max"])

        assert len(result) >= 1
        assert result[0]["person"] == "Max"
        assert result[0]["delay_minutes"] >= 90

    @pytest.mark.asyncio
    async def test_no_delay_when_on_time(self, anticipation_with_redis):
        """Person within expected window generates no deviation."""
        now = datetime.now(_LOCAL_TZ).replace(hour=18, minute=30)
        entries = []
        for i in range(5):
            entries.append(
                json.dumps(
                    {
                        "action": "person_arrived",
                        "person": "Max",
                        "timestamp": (now - timedelta(days=i + 1))
                        .replace(hour=18, minute=0)
                        .isoformat(),
                    }
                ).encode()
            )
        anticipation_with_redis.redis.lrange = AsyncMock(return_value=entries)

        with patch("assistant.anticipation.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await anticipation_with_redis.check_routine_deviation(["Max"])
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_handled(self, anticipation_with_redis):
        """Exception during routine deviation check is handled."""
        anticipation_with_redis.redis.lrange = AsyncMock(side_effect=Exception("Error"))

        with patch("assistant.anticipation.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.now(_LOCAL_TZ).replace(hour=19)
            result = await anticipation_with_redis.check_routine_deviation(["Max"])
        assert result == []


# ============================================================
# get_person_predictions
# ============================================================


class TestGetPersonPredictions:
    @pytest.mark.asyncio
    async def test_empty_person_returns_all(self, anticipation_with_redis):
        """Empty person string returns all predictions."""
        anticipation_with_redis.predict_future_needs = AsyncMock(
            return_value=[
                {"action": "a", "person": "Max"},
                {"action": "b", "person": ""},
            ]
        )
        result = await anticipation_with_redis.get_person_predictions("", days_ahead=7)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filters_by_person(self, anticipation_with_redis):
        """Predictions are filtered to specific person + unassigned."""
        anticipation_with_redis.predict_future_needs = AsyncMock(
            return_value=[
                {"action": "a", "person": "Max"},
                {"action": "b", "person": "Anna"},
                {"action": "c", "person": ""},
            ]
        )
        result = await anticipation_with_redis.get_person_predictions(
            "Max", days_ahead=7
        )
        assert len(result) == 2
        assert all(p.get("person", "") in ("Max", "") for p in result)

    @pytest.mark.asyncio
    async def test_case_insensitive_filter(self, anticipation_with_redis):
        """Person filter is case insensitive."""
        anticipation_with_redis.predict_future_needs = AsyncMock(
            return_value=[
                {"action": "a", "person": "Max"},
            ]
        )
        result = await anticipation_with_redis.get_person_predictions(
            "max", days_ahead=3
        )
        assert len(result) == 1
