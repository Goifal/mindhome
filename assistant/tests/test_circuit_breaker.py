"""
Comprehensive tests for the CircuitBreaker state machine.

Standalone test file — all logic is copied here to keep tests isolated
from the rest of the project.
"""

import time
from enum import Enum
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Standalone copy of the CircuitBreaker implementation
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, recovery_timeout=30.0, half_open_max_calls=1):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0
        self._half_open_calls = 0

    @property
    def state(self):
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    @property
    def is_available(self):
        s = self.state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False

    def try_acquire(self):
        s = self.state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        else:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def reset(self):
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def status(self):
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _force_open(cb: CircuitBreaker):
    """Drive the breaker to OPEN by recording enough failures."""
    for _ in range(cb.failure_threshold):
        cb.record_failure()
    assert cb._state == CircuitState.OPEN


def _force_half_open(cb: CircuitBreaker, mock_monotonic):
    """Drive the breaker to HALF_OPEN by moving time past recovery_timeout."""
    _force_open(cb)
    mock_monotonic.return_value = cb._last_failure_time + cb.recovery_timeout
    assert cb.state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# 1. Initial state is CLOSED
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("svc")
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_is_zero(self):
        cb = CircuitBreaker("svc")
        assert cb._failure_count == 0

    def test_initial_success_count_is_zero(self):
        cb = CircuitBreaker("svc")
        assert cb._success_count == 0

    def test_initial_half_open_calls_is_zero(self):
        cb = CircuitBreaker("svc")
        assert cb._half_open_calls == 0

    def test_default_parameters(self):
        cb = CircuitBreaker("svc")
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 30.0
        assert cb.half_open_max_calls == 1

    def test_custom_parameters(self):
        cb = CircuitBreaker("svc", failure_threshold=3, recovery_timeout=10.0, half_open_max_calls=2)
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 10.0
        assert cb.half_open_max_calls == 2


# ---------------------------------------------------------------------------
# 2. CLOSED -> OPEN after failure_threshold failures
# ---------------------------------------------------------------------------

class TestClosedToOpen:
    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_opens_above_threshold(self):
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(7):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_failure_count_tracks_correctly(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        cb.record_failure()
        assert cb._failure_count == 1
        cb.record_failure()
        assert cb._failure_count == 2
        cb.record_failure()
        assert cb._failure_count == 3
        assert cb._state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# 3. OPEN -> HALF_OPEN after recovery_timeout
# ---------------------------------------------------------------------------

class TestOpenToHalfOpen:
    @patch("time.monotonic")
    def test_stays_open_before_timeout(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30.0)
        mock_monotonic.return_value = 100.0
        _force_open(cb)
        # Still within the recovery window
        mock_monotonic.return_value = 100.0 + 29.9
        assert cb.state == CircuitState.OPEN

    @patch("time.monotonic")
    def test_transitions_to_half_open_at_timeout(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30.0)
        mock_monotonic.return_value = 100.0
        _force_open(cb)
        mock_monotonic.return_value = 100.0 + 30.0
        assert cb.state == CircuitState.HALF_OPEN

    @patch("time.monotonic")
    def test_transitions_to_half_open_after_timeout(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30.0)
        mock_monotonic.return_value = 100.0
        _force_open(cb)
        mock_monotonic.return_value = 100.0 + 60.0
        assert cb.state == CircuitState.HALF_OPEN

    @patch("time.monotonic")
    def test_half_open_resets_half_open_calls(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0)
        mock_monotonic.return_value = 100.0
        _force_open(cb)
        cb._half_open_calls = 5  # leftover from a previous half-open phase
        mock_monotonic.return_value = 100.0 + 10.0
        _ = cb.state  # trigger transition
        assert cb._half_open_calls == 0


# ---------------------------------------------------------------------------
# 4. HALF_OPEN -> CLOSED on success
# ---------------------------------------------------------------------------

class TestHalfOpenToClosed:
    @patch("time.monotonic")
    def test_single_success_closes_with_max_calls_1(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=1)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        cb.record_success()
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._success_count == 0

    @patch("time.monotonic")
    def test_multiple_successes_needed_with_max_calls_3(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=3)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)

        cb.record_success()
        assert cb._state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb._state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb._state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# 5. HALF_OPEN -> OPEN on failure
# ---------------------------------------------------------------------------

class TestHalfOpenToOpen:
    @patch("time.monotonic")
    def test_single_failure_reopens(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        mock_monotonic.return_value = 200.0  # advance time for new failure timestamp
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    @patch("time.monotonic")
    def test_failure_after_some_successes_reopens(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=3)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        cb.record_success()
        cb.record_success()
        mock_monotonic.return_value = 200.0
        cb.record_failure()
        assert cb._state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# 6. try_acquire in each state
# ---------------------------------------------------------------------------

class TestTryAcquire:
    def test_acquire_closed_returns_true(self):
        cb = CircuitBreaker("svc")
        assert cb.try_acquire() is True

    def test_acquire_open_returns_false(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        _force_open(cb)
        # Directly check _state to avoid time-based transition
        assert cb._state == CircuitState.OPEN
        # Patch time to keep it open
        with patch("time.monotonic", return_value=cb._last_failure_time + 1.0):
            assert cb.try_acquire() is False

    @patch("time.monotonic")
    def test_acquire_half_open_first_call_returns_true(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=1)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        assert cb.try_acquire() is True

    @patch("time.monotonic")
    def test_acquire_half_open_exceeds_max_calls_returns_false(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=1)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        cb.try_acquire()  # uses up the one allowed call
        assert cb.try_acquire() is False

    @patch("time.monotonic")
    def test_acquire_increments_half_open_calls(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=3)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        assert cb._half_open_calls == 0
        cb.try_acquire()
        assert cb._half_open_calls == 1
        cb.try_acquire()
        assert cb._half_open_calls == 2
        cb.try_acquire()
        assert cb._half_open_calls == 3
        assert cb.try_acquire() is False


# ---------------------------------------------------------------------------
# 7. is_available in each state
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_available_when_closed(self):
        cb = CircuitBreaker("svc")
        assert cb.is_available is True

    def test_not_available_when_open(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        _force_open(cb)
        with patch("time.monotonic", return_value=cb._last_failure_time + 1.0):
            assert cb.is_available is False

    @patch("time.monotonic")
    def test_available_when_half_open_under_limit(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=2)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        assert cb.is_available is True

    @patch("time.monotonic")
    def test_not_available_when_half_open_at_limit(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=1)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        cb._half_open_calls = 1
        assert cb.is_available is False


# ---------------------------------------------------------------------------
# 8. record_success decrements failure_count in CLOSED state
# ---------------------------------------------------------------------------

class TestRecordSuccessInClosed:
    def test_decrements_failure_count(self):
        cb = CircuitBreaker("svc", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 3
        cb.record_success()
        assert cb._failure_count == 2
        cb.record_success()
        assert cb._failure_count == 1

    def test_does_not_go_below_zero(self):
        cb = CircuitBreaker("svc")
        cb.record_success()
        assert cb._failure_count == 0
        cb.record_success()
        assert cb._failure_count == 0

    def test_success_does_not_change_state_from_closed(self):
        cb = CircuitBreaker("svc")
        cb.record_success()
        assert cb._state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# 9. reset works
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_from_open(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        _force_open(cb)
        cb.reset()
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._success_count == 0
        assert cb._half_open_calls == 0

    @patch("time.monotonic")
    def test_reset_from_half_open(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        cb.reset()
        assert cb._state == CircuitState.CLOSED

    def test_reset_from_closed_is_idempotent(self):
        cb = CircuitBreaker("svc")
        cb.reset()
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_reset_clears_all_counters(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        _force_open(cb)
        cb._success_count = 5
        cb._half_open_calls = 3
        cb.reset()
        assert cb._failure_count == 0
        assert cb._success_count == 0
        assert cb._half_open_calls == 0


# ---------------------------------------------------------------------------
# 10. status() returns correct dict
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_closed(self):
        cb = CircuitBreaker("my-service", failure_threshold=5, recovery_timeout=30.0)
        s = cb.status()
        assert s == {
            "name": "my-service",
            "state": "closed",
            "failure_count": 0,
            "failure_threshold": 5,
            "recovery_timeout": 30.0,
        }

    def test_status_open(self):
        cb = CircuitBreaker("api", failure_threshold=2, recovery_timeout=15.0)
        _force_open(cb)
        with patch("time.monotonic", return_value=cb._last_failure_time + 1.0):
            s = cb.status()
        assert s["state"] == "open"
        assert s["failure_count"] == 2
        assert s["name"] == "api"

    @patch("time.monotonic")
    def test_status_half_open(self, mock_monotonic):
        cb = CircuitBreaker("db", failure_threshold=2, recovery_timeout=10.0)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        s = cb.status()
        assert s["state"] == "half_open"

    def test_status_contains_all_keys(self):
        cb = CircuitBreaker("svc")
        expected_keys = {"name", "state", "failure_count", "failure_threshold", "recovery_timeout"}
        assert set(cb.status().keys()) == expected_keys


# ---------------------------------------------------------------------------
# 11. Half-open max calls limit
# ---------------------------------------------------------------------------

class TestHalfOpenMaxCalls:
    @patch("time.monotonic")
    def test_max_calls_2(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=2)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)

        assert cb.try_acquire() is True
        assert cb.try_acquire() is True
        assert cb.try_acquire() is False

    @patch("time.monotonic")
    def test_max_calls_respected_by_is_available(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=2)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)

        assert cb.is_available is True
        cb.try_acquire()
        assert cb.is_available is True
        cb.try_acquire()
        assert cb.is_available is False

    @patch("time.monotonic")
    def test_needs_all_successes_to_close(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=3)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)

        cb.record_success()
        assert cb._state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb._state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb._state == CircuitState.CLOSED

    @patch("time.monotonic")
    def test_half_open_calls_reset_on_reentry(self, mock_monotonic):
        """After going OPEN -> HALF_OPEN -> OPEN -> HALF_OPEN, the call counter resets."""
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=10.0, half_open_max_calls=1)
        mock_monotonic.return_value = 100.0
        _force_half_open(cb, mock_monotonic)
        cb.try_acquire()
        assert cb._half_open_calls == 1

        # Fail back to OPEN
        mock_monotonic.return_value = 200.0
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

        # Wait for recovery again
        mock_monotonic.return_value = 200.0 + 10.0
        assert cb.state == CircuitState.HALF_OPEN
        assert cb._half_open_calls == 0
        assert cb.try_acquire() is True


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_threshold_of_one(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    @patch("time.monotonic")
    def test_threshold_of_one_full_cycle(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=5.0, half_open_max_calls=1)
        mock_monotonic.return_value = 0.0
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

        mock_monotonic.return_value = 5.0
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb._state == CircuitState.CLOSED

    def test_multiple_resets(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        _force_open(cb)
        cb.reset()
        cb.reset()
        cb.reset()
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_reset_then_failures_again(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        _force_open(cb)
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    @patch("time.monotonic")
    def test_rapid_open_half_open_cycles(self, mock_monotonic):
        """Cycle CLOSED -> OPEN -> HALF_OPEN -> OPEN -> HALF_OPEN -> CLOSED."""
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=10.0, half_open_max_calls=1)

        # CLOSED -> OPEN
        mock_monotonic.return_value = 0.0
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

        # OPEN -> HALF_OPEN
        mock_monotonic.return_value = 10.0
        assert cb.state == CircuitState.HALF_OPEN

        # HALF_OPEN -> OPEN (failure)
        mock_monotonic.return_value = 11.0
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

        # OPEN -> HALF_OPEN again
        mock_monotonic.return_value = 21.0
        assert cb.state == CircuitState.HALF_OPEN

        # HALF_OPEN -> CLOSED (success)
        cb.record_success()
        assert cb._state == CircuitState.CLOSED

    def test_success_in_open_state_decrements_count(self):
        """record_success in OPEN state (accessed via _state, bypassing timeout) still decrements."""
        cb = CircuitBreaker("svc", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 3
        # Force to OPEN without hitting threshold to test decrement
        cb._state = CircuitState.OPEN
        cb.record_success()
        # In OPEN state, the else branch runs -> decrement
        assert cb._failure_count == 2

    def test_name_preserved(self):
        cb = CircuitBreaker("my-special-service")
        assert cb.name == "my-special-service"
        assert cb.status()["name"] == "my-special-service"

    @patch("time.monotonic")
    def test_last_failure_time_updated_on_each_failure(self, mock_monotonic):
        cb = CircuitBreaker("svc", failure_threshold=5)
        mock_monotonic.return_value = 10.0
        cb.record_failure()
        assert cb._last_failure_time == 10.0
        mock_monotonic.return_value = 20.0
        cb.record_failure()
        assert cb._last_failure_time == 20.0

    @patch("time.monotonic")
    def test_recovery_timeout_zero(self, mock_monotonic):
        """With a zero recovery timeout, OPEN immediately becomes HALF_OPEN."""
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=0.0, half_open_max_calls=1)
        mock_monotonic.return_value = 100.0
        cb.record_failure()
        assert cb._state == CircuitState.OPEN
        # Any call to .state should transition immediately
        assert cb.state == CircuitState.HALF_OPEN

    def test_large_failure_threshold(self):
        cb = CircuitBreaker("svc", failure_threshold=1000)
        for _ in range(999):
            cb.record_failure()
        assert cb._state == CircuitState.CLOSED
        cb.record_failure()
        assert cb._state == CircuitState.OPEN
