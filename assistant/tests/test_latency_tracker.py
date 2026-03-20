"""Tests fuer latency_tracker — End-to-End Latenz-Monitoring."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.latency_tracker import LatencyTracker, RequestTrace, PHASES


class TestRequestTrace:
    """Tests fuer einzelne Request-Traces."""

    def test_create_trace(self):
        trace = RequestTrace(request_id="test-1")
        assert trace.request_id == "test-1"
        assert trace.start > 0
        assert trace.marks == {}

    def test_mark_phase(self):
        trace = RequestTrace(request_id="test-2")
        trace.mark("pre_classify")
        assert "pre_classify" in trace.marks
        assert trace.marks["pre_classify"] > trace.start

    def test_finish_calculates_durations(self):
        trace = RequestTrace(request_id="test-3")
        # Simuliere Zeitabstaende
        trace.marks["pre_classify"] = trace.start + 0.05  # 50ms
        trace.marks["context_gather"] = trace.start + 0.25  # 200ms nach pre_classify
        trace.marks["llm_first_token"] = trace.start + 0.75  # 500ms nach context
        trace.marks["llm_complete"] = trace.start + 2.0     # 1250ms nach first_token

        durations = trace.finish()
        assert "pre_classify" in durations
        assert "context_gather" in durations
        assert "llm_first_token" in durations
        assert "llm_complete" in durations
        assert "total" in durations

        # Pre-classify: ~50ms
        assert 40 < durations["pre_classify"] < 60
        # Context gather: ~200ms
        assert 190 < durations["context_gather"] < 210
        # LLM first token: ~500ms
        assert 490 < durations["llm_first_token"] < 510
        # LLM complete: ~1250ms
        assert 1240 < durations["llm_complete"] < 1260

    def test_finish_with_missing_phases(self):
        trace = RequestTrace(request_id="test-4")
        trace.marks["pre_classify"] = trace.start + 0.1
        # context_gather fehlt → wird uebersprungen
        trace.marks["llm_complete"] = trace.start + 1.0

        durations = trace.finish()
        assert "pre_classify" in durations
        assert "context_gather" not in durations
        assert "llm_complete" in durations
        assert "total" in durations


class TestLatencyTracker:
    """Tests fuer den Latency Tracker."""

    def test_begin_creates_trace(self):
        tracker = LatencyTracker()
        trace = tracker.begin()
        assert trace.request_id == "req-1"
        trace2 = tracker.begin()
        assert trace2.request_id == "req-2"

    def test_begin_with_custom_id(self):
        tracker = LatencyTracker()
        trace = tracker.begin("custom-id")
        assert trace.request_id == "custom-id"

    def test_record_stores_durations(self):
        tracker = LatencyTracker()
        trace = tracker.begin()
        trace.marks["pre_classify"] = trace.start + 0.1
        trace.marks["context_gather"] = trace.start + 0.3
        trace.marks["llm_first_token"] = trace.start + 0.5
        trace.marks["llm_complete"] = trace.start + 1.5

        durations = tracker.record(trace)
        # total wird aus time.monotonic() - start berechnet, kann bei schnellen Tests ~0 sein
        assert durations["total"] >= 0
        assert "pre_classify" in durations
        assert len(tracker._phase_values["total"]) == 1
        assert len(tracker._phase_values["pre_classify"]) == 1

    def test_percentile_empty(self):
        tracker = LatencyTracker()
        assert tracker.percentile("total", 50) is None

    def test_percentile_single_value(self):
        tracker = LatencyTracker()
        tracker._phase_values["total"].append(100.0)
        tracker._dirty = True
        assert tracker.percentile("total", 50) == 100.0

    def test_percentile_multiple_values(self):
        tracker = LatencyTracker(max_history=100)
        for v in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
            tracker._phase_values["total"].append(float(v))
        tracker._dirty = True

        p50 = tracker.percentile("total", 50)
        assert p50 is not None
        assert 500 <= p50 <= 600  # Median sollte ~550 sein

        p95 = tracker.percentile("total", 95)
        assert p95 is not None
        assert p95 > 900

    def test_get_stats(self):
        tracker = LatencyTracker()
        # Einfuegen von 5 Traces
        for i in range(5):
            trace = tracker.begin()
            trace.marks["pre_classify"] = trace.start + 0.05
            trace.marks["total"] = trace.start + 1.0 + i * 0.1
            tracker.record(trace)

        stats = tracker.get_stats()
        assert "pre_classify" in stats
        assert "total" in stats
        assert stats["total"]["count"] == 5
        assert "p50" in stats["total"]
        assert "p95" in stats["total"]
        assert "p99" in stats["total"]
        assert "min" in stats["total"]
        assert "max" in stats["total"]

    def test_get_summary_text(self):
        tracker = LatencyTracker()
        assert "Keine Latenz-Daten" in tracker.get_summary_text()

        trace = tracker.begin()
        trace.marks["pre_classify"] = trace.start + 0.05
        tracker.record(trace)

        summary = tracker.get_summary_text()
        assert "Latenz-Statistik" in summary
        assert "pre_classify" in summary

    def test_ring_buffer_overflow(self):
        tracker = LatencyTracker(max_history=5)
        for i in range(10):
            tracker._phase_values["total"].append(float(i * 100))

        # Deque mit maxlen=5 behaelt nur die letzten 5
        assert len(tracker._phase_values["total"]) == 5
        assert list(tracker._phase_values["total"]) == [500, 600, 700, 800, 900]

    @pytest.mark.asyncio
    async def test_flush_to_redis(self):
        tracker = LatencyTracker()
        redis_mock = AsyncMock()
        tracker.set_redis(redis_mock)

        trace = tracker.begin()
        trace.marks["pre_classify"] = trace.start + 0.05
        tracker.record(trace)

        await tracker.flush_to_redis()
        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        assert call_args[0][0] == "mha:latency:stats"
        data = json.loads(call_args[0][1])
        assert "pre_classify" in data

    @pytest.mark.asyncio
    async def test_flush_without_redis(self):
        tracker = LatencyTracker()
        # Kein Fehler wenn Redis nicht gesetzt
        await tracker.flush_to_redis()

    @pytest.mark.asyncio
    async def test_flush_redis_error_ignored(self):
        tracker = LatencyTracker()
        redis_mock = AsyncMock()
        redis_mock.set.side_effect = Exception("Redis down")
        tracker.set_redis(redis_mock)

        trace = tracker.begin()
        tracker.record(trace)

        # Fehler wird verschluckt (debug-log)
        await tracker.flush_to_redis()


# ------------------------------------------------------------------
# Phase 2C: Model Router Feedback
# ------------------------------------------------------------------


class TestPhase2CModelRouterFeedback:
    """Tests fuer automatisches Latenz-Feedback an Model Router."""

    def test_set_model_router(self):
        """Model Router kann gesetzt werden."""
        tracker = LatencyTracker()
        router_mock = MagicMock()
        tracker.set_model_router(router_mock)
        assert tracker._model_router is router_mock

    def test_record_calls_router(self):
        """record() leitet LLM-Latenz an Router weiter."""
        tracker = LatencyTracker()
        router_mock = MagicMock()
        tracker.set_model_router(router_mock)

        trace = tracker.begin()
        trace.mark("pre_classify")
        trace.mark("context_gather")
        trace.mark("llm_first_token")
        trace.mark("llm_complete")
        tracker.record(trace)

        router_mock.record_latency.assert_called_once()

    def test_record_without_router(self):
        """record() ohne Router wirft keinen Fehler."""
        tracker = LatencyTracker()
        trace = tracker.begin()
        trace.mark("llm_complete")
        tracker.record(trace)  # Kein Fehler

    def test_record_router_error_ignored(self):
        """Router-Fehler wird verschluckt."""
        tracker = LatencyTracker()
        router_mock = MagicMock()
        router_mock.record_latency.side_effect = Exception("Router error")
        tracker.set_model_router(router_mock)

        trace = tracker.begin()
        trace.mark("llm_complete")
        tracker.record(trace)  # Kein Fehler

    def test_record_uses_trace_tier_attribute(self):
        """record() should pass trace.tier to model router if set."""
        tracker = LatencyTracker()
        router_mock = MagicMock()
        tracker.set_model_router(router_mock)

        trace = tracker.begin()
        trace.tier = "fast"
        trace.mark("llm_complete")
        tracker.record(trace)

        call_args = router_mock.record_latency.call_args
        assert call_args[0][0] == "fast"

    def test_record_defaults_tier_to_smart(self):
        """If trace has no tier attribute, default to 'smart'."""
        tracker = LatencyTracker()
        router_mock = MagicMock()
        tracker.set_model_router(router_mock)

        trace = tracker.begin()
        trace.mark("llm_complete")
        tracker.record(trace)

        call_args = router_mock.record_latency.call_args
        assert call_args[0][0] == "smart"


# ------------------------------------------------------------------
# Percentile edge cases
# ------------------------------------------------------------------

class TestPercentileEdgeCases:
    """Edge case tests for percentile calculations."""

    def test_percentile_zero_returns_minimum(self):
        """p=0 should return the smallest value."""
        tracker = LatencyTracker()
        for v in [100.0, 200.0, 300.0]:
            tracker._phase_values["total"].append(v)
        tracker._dirty = True
        assert tracker.percentile("total", 0) == 100.0

    def test_percentile_100_returns_maximum(self):
        """p=100 should return the largest value."""
        tracker = LatencyTracker()
        for v in [100.0, 200.0, 300.0]:
            tracker._phase_values["total"].append(v)
        tracker._dirty = True
        assert tracker.percentile("total", 100) == 300.0

    def test_percentile_negative_returns_minimum(self):
        """p<0 should clamp to minimum."""
        tracker = LatencyTracker()
        tracker._phase_values["total"].append(42.0)
        tracker._dirty = True
        assert tracker.percentile("total", -10) == 42.0

    def test_percentile_over_100_returns_maximum(self):
        """p>100 should clamp to maximum."""
        tracker = LatencyTracker()
        tracker._phase_values["total"].append(42.0)
        tracker._dirty = True
        assert tracker.percentile("total", 150) == 42.0

    def test_percentile_unknown_phase(self):
        """Unknown phase should return None."""
        tracker = LatencyTracker()
        assert tracker.percentile("nonexistent_phase", 50) is None

    def test_percentile_two_values_interpolation(self):
        """With two values, p50 should interpolate to the midpoint."""
        tracker = LatencyTracker()
        tracker._phase_values["total"].append(100.0)
        tracker._phase_values["total"].append(200.0)
        tracker._dirty = True
        p50 = tracker.percentile("total", 50)
        assert p50 == 150.0

    def test_sorted_cache_not_rebuilt_when_clean(self):
        """_ensure_sorted should not rebuild when _dirty is False."""
        tracker = LatencyTracker()
        tracker._phase_values["total"].append(100.0)
        tracker._dirty = True
        tracker._ensure_sorted()
        assert tracker._dirty is False
        # Mutate the cache to verify it is NOT rebuilt
        tracker._sorted_cache["total"] = [999.0]
        tracker._ensure_sorted()
        assert tracker._sorted_cache["total"] == [999.0]


# ------------------------------------------------------------------
# RequestTrace edge cases
# ------------------------------------------------------------------

class TestRequestTraceEdgeCases:
    """Additional edge cases for RequestTrace."""

    def test_finish_with_no_marks(self):
        """Finishing a trace with no marks should only have 'total'."""
        trace = RequestTrace(request_id="empty")
        durations = trace.finish()
        assert "total" in durations
        assert len([k for k in durations if k != "total"]) == 0

    def test_finish_stores_in_phase_durations(self):
        """finish() should populate _phase_durations."""
        trace = RequestTrace(request_id="store")
        trace.marks["pre_classify"] = trace.start + 0.1
        durations = trace.finish()
        assert trace._phase_durations == durations

    def test_mark_overwrites_previous(self):
        """Marking the same phase twice should overwrite."""
        trace = RequestTrace(request_id="overwrite")
        trace.mark("pre_classify")
        first = trace.marks["pre_classify"]
        trace.mark("pre_classify")
        second = trace.marks["pre_classify"]
        assert second >= first

    def test_finish_total_always_non_negative(self):
        """Total duration should always be non-negative."""
        trace = RequestTrace(request_id="pos")
        durations = trace.finish()
        assert durations["total"] >= 0


# ------------------------------------------------------------------
# get_stats edge cases
# ------------------------------------------------------------------

class TestGetStatsEdgeCases:

    def test_get_stats_empty(self):
        """Empty tracker should return empty dict."""
        tracker = LatencyTracker()
        assert tracker.get_stats() == {}

    def test_get_stats_includes_min_max(self):
        """Stats should include correct min and max."""
        tracker = LatencyTracker()
        for v in [10.0, 50.0, 100.0]:
            tracker._phase_values["total"].append(v)
        tracker._dirty = True
        stats = tracker.get_stats()
        assert stats["total"]["min"] == 10.0
        assert stats["total"]["max"] == 100.0

    def test_get_summary_text_all_phases(self):
        """Summary should include all recorded phases."""
        tracker = LatencyTracker()
        trace = tracker.begin()
        trace.marks["pre_classify"] = trace.start + 0.01
        trace.marks["context_gather"] = trace.start + 0.02
        trace.marks["llm_first_token"] = trace.start + 0.03
        trace.marks["llm_complete"] = trace.start + 0.04
        trace.marks["tts_first_audio"] = trace.start + 0.05
        tracker.record(trace)
        summary = tracker.get_summary_text()
        for phase in PHASES:
            assert phase in summary
