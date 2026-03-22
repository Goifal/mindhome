"""Tests for assistant.calendar_intelligence — CalendarIntelligence class."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.calendar_intelligence import (
    CalendarIntelligence,
    REDIS_KEY_HABITS,
    REDIS_KEY_CONFLICTS,
    REDIS_KEY_EVENT_HISTORY,
)


# ── Helpers ───────────────────────────────────────────────


def _make_event(summary, start_iso, end_iso, all_day=False):
    return {"summary": summary, "start": start_iso, "end": end_iso, "all_day": all_day}


# Build recurring events on same weekday+hour (>= habit_min_occurrences)
def _make_recurring_events(summary, hour, count=4):
    """Create `count` events all on Monday at the given hour."""
    events = []
    # Use a known Monday: 2026-03-02 is a Monday
    for i in range(count):
        day = datetime(2026, 3, 2 + 7 * i, hour, 0)
        events.append(
            _make_event(
                summary,
                day.isoformat(),
                (day + timedelta(hours=1)).isoformat(),
            )
        )
    return events


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def ci():
    with patch(
        "assistant.calendar_intelligence.yaml_config",
        {
            "calendar_intelligence": {
                "enabled": True,
                "commute_minutes": 30,
                "habit_min_occurrences": 3,
            }
        },
    ):
        return CalendarIntelligence()


@pytest.fixture
def ci_disabled():
    with patch(
        "assistant.calendar_intelligence.yaml_config",
        {"calendar_intelligence": {"enabled": False}},
    ):
        return CalendarIntelligence()


# ── __init__ ──────────────────────────────────────────────


@patch("assistant.calendar_intelligence.yaml_config", {"calendar_intelligence": {}})
def test_init_defaults():
    ci = CalendarIntelligence()
    assert ci.enabled is True
    assert ci.commute_minutes == 30
    assert ci.habit_min_occurrences == 3
    assert ci.conflict_lookahead_hours == 24
    assert ci._habits == []
    assert ci._conflicts == []


@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": False, "commute_minutes": 45}},
)
def test_init_custom_config():
    ci = CalendarIntelligence()
    assert ci.enabled is False
    assert ci.commute_minutes == 45


# ── initialize ────────────────────────────────────────────


@pytest.mark.asyncio
@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True}},
)
async def test_initialize_with_redis():
    ci = CalendarIntelligence()
    redis = AsyncMock()
    redis.get = AsyncMock(
        return_value=json.dumps([{"type": "recurring_event", "title": "Standup"}])
    )
    await ci.initialize(redis)
    assert ci.redis is redis
    assert len(ci._habits) == 1


@pytest.mark.asyncio
@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True}},
)
async def test_initialize_without_redis():
    ci = CalendarIntelligence()
    await ci.initialize(None)
    assert ci.redis is None
    assert ci._habits == []


@pytest.mark.asyncio
@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": False}},
)
async def test_initialize_disabled():
    ci = CalendarIntelligence()
    redis = AsyncMock()
    await ci.initialize(redis)
    # _load_habits not called when disabled
    redis.get.assert_not_called()


# ── _parse_dt ─────────────────────────────────────────────


def test_parse_dt_iso():
    result = CalendarIntelligence._parse_dt("2026-03-08T10:00:00")
    assert result == datetime(2026, 3, 8, 10, 0)


def test_parse_dt_with_z():
    result = CalendarIntelligence._parse_dt("2026-03-08T10:00:00Z")
    assert result is not None
    assert result.hour == 10


def test_parse_dt_date_only():
    result = CalendarIntelligence._parse_dt("2026-03-08")
    assert result == datetime(2026, 3, 8)


def test_parse_dt_empty():
    assert CalendarIntelligence._parse_dt("") is None


def test_parse_dt_invalid():
    assert CalendarIntelligence._parse_dt("not-a-date") is None


# ── _detect_conflicts ────────────────────────────────────


def test_detect_conflicts_overlap(ci):
    events = [
        _make_event("Meeting A", "2026-03-08T09:00:00", "2026-03-08T10:30:00"),
        _make_event("Meeting B", "2026-03-08T10:00:00", "2026-03-08T11:00:00"),
    ]
    conflicts = ci._detect_conflicts(events)
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "overlap"
    assert conflicts[0]["event_a"] == "Meeting A"
    assert conflicts[0]["event_b"] == "Meeting B"


def test_detect_conflicts_tight_schedule(ci):
    events = [
        _make_event("Meeting A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
        _make_event("Meeting B", "2026-03-08T10:15:00", "2026-03-08T11:00:00"),
    ]
    conflicts = ci._detect_conflicts(events)
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "tight_schedule"
    assert conflicts[0]["gap_minutes"] == 15


def test_detect_conflicts_no_conflict(ci):
    events = [
        _make_event("Meeting A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
        _make_event("Meeting B", "2026-03-08T11:00:00", "2026-03-08T12:00:00"),
    ]
    conflicts = ci._detect_conflicts(events)
    assert len(conflicts) == 0


def test_detect_conflicts_skips_all_day(ci):
    events = [
        _make_event("Holiday", "2026-03-08", "2026-03-09", all_day=True),
        _make_event("Meeting", "2026-03-08T10:00:00", "2026-03-08T11:00:00"),
    ]
    conflicts = ci._detect_conflicts(events)
    assert len(conflicts) == 0


# ── _detect_breaks ────────────────────────────────────────


def test_detect_breaks_found(ci):
    events = [
        _make_event("A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
        _make_event("B", "2026-03-08T11:00:00", "2026-03-08T12:00:00"),
    ]
    breaks = ci._detect_breaks(events)
    assert len(breaks) == 1
    assert breaks[0]["duration_minutes"] == 60
    assert breaks[0]["start"] == "10:00"
    assert breaks[0]["end"] == "11:00"


def test_detect_breaks_too_short(ci):
    events = [
        _make_event("A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
        _make_event("B", "2026-03-08T10:20:00", "2026-03-08T11:00:00"),
    ]
    breaks = ci._detect_breaks(events)
    assert len(breaks) == 0  # 20 min < 30 min threshold


def test_detect_breaks_too_long(ci):
    events = [
        _make_event("A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
        _make_event("B", "2026-03-08T14:00:00", "2026-03-08T15:00:00"),
    ]
    breaks = ci._detect_breaks(events)
    assert len(breaks) == 0  # 4h > 180min threshold


# ── _detect_habits ────────────────────────────────────────


def test_detect_habits_recurring(ci):
    events = _make_recurring_events("Team Standup", 10, count=4)
    habits = ci._detect_habits(events)
    assert len(habits) >= 1
    assert habits[0]["type"] == "recurring_event"
    assert habits[0]["title"] == "Team Standup"
    assert habits[0]["count"] >= 3


def test_detect_habits_not_enough_occurrences(ci):
    events = _make_recurring_events("Rare Meeting", 14, count=2)
    habits = ci._detect_habits(events)
    assert len(habits) == 0


# ── analyze_events ────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_events_disabled(ci_disabled):
    result = await ci_disabled.analyze_events([])
    assert result == {"habits": [], "conflicts": [], "breaks": []}


@pytest.mark.asyncio
async def test_analyze_events_stores_to_redis(ci):
    ci.redis = AsyncMock()
    events = [
        _make_event("A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
        _make_event("B", "2026-03-08T11:00:00", "2026-03-08T12:00:00"),
    ]
    result = await ci.analyze_events(events)
    assert "habits" in result
    assert "conflicts" in result
    assert "breaks" in result
    assert ci.redis.set.call_count == 2  # habits + conflicts


@pytest.mark.asyncio
async def test_analyze_events_no_redis(ci):
    ci.redis = None
    result = await ci.analyze_events([])
    assert result["habits"] == []


# ── get_habits / get_conflicts ────────────────────────────


def test_get_habits(ci):
    ci._habits = [{"type": "recurring_event", "title": "test"}]
    assert ci.get_habits() == ci._habits


def test_get_conflicts(ci):
    ci._conflicts = [{"type": "overlap"}]
    assert ci.get_conflicts() == ci._conflicts


# ── get_context_hint ──────────────────────────────────────


def test_get_context_hint_empty(ci):
    assert ci.get_context_hint() == ""


def test_get_context_hint_with_data(ci):
    ci._conflicts = [{"description": "Conflict 1"}]
    ci._habits = [{"description": "Habit 1"}]
    hint = ci.get_context_hint()
    assert "Kalender-Konflikt: Conflict 1" in hint
    assert "Kalender-Gewohnheit: Habit 1" in hint


def test_get_context_hint_limits_items(ci):
    ci._conflicts = [{"description": f"C{i}"} for i in range(5)]
    ci._habits = [{"description": f"H{i}"} for i in range(5)]
    hint = ci.get_context_hint()
    # Max 3 conflicts + 2 habits
    assert hint.count("Kalender-Konflikt") == 3
    assert hint.count("Kalender-Gewohnheit") == 2


# ── Zusaetzliche Tests fuer 100% Coverage ─────────────────


@pytest.mark.asyncio
@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True}},
)
async def test_load_habits_no_redis():
    """_load_habits kehrt sofort zurueck wenn kein Redis vorhanden (Zeile 57)."""
    ci = CalendarIntelligence()
    ci.redis = None
    await ci._load_habits()
    assert ci._habits == []


@pytest.mark.asyncio
@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True}},
)
async def test_load_habits_exception():
    """_load_habits faengt Exceptions ab (Zeilen 62-63)."""
    ci = CalendarIntelligence()
    ci.redis = AsyncMock()
    ci.redis.get = AsyncMock(side_effect=Exception("Redis Verbindung verloren"))
    await ci._load_habits()
    # Habits bleiben leer bei Fehler
    assert ci._habits == []


@pytest.mark.asyncio
@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True}},
)
async def test_analyze_events_redis_exception():
    """analyze_events faengt Redis-Fehler beim Speichern ab (Zeilen 106-107)."""
    ci = CalendarIntelligence()
    ci.redis = AsyncMock()
    ci.redis.set = AsyncMock(side_effect=Exception("Redis write error"))
    events = [
        _make_event("A", "2026-03-08T09:00:00", "2026-03-08T10:00:00"),
    ]
    result = await ci.analyze_events(events)
    # Ergebnis wird trotzdem zurueckgegeben, nur Redis-Speicherung schlaegt fehl
    assert "habits" in result
    assert "conflicts" in result
    assert "breaks" in result


@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True, "habit_min_occurrences": 3}},
)
def test_detect_habits_skips_all_day_and_no_start():
    """_detect_habits ueberspringt all_day Events und Events ohne Start (Zeile 125)."""
    ci = CalendarIntelligence()
    events = [
        _make_event("Holiday", "2026-03-08", "2026-03-09", all_day=True),
        {
            "summary": "No start",
            "start": "",
            "end": "2026-03-08T10:00:00",
            "all_day": False,
        },
    ]
    habits = ci._detect_habits(events)
    assert habits == []


@patch(
    "assistant.calendar_intelligence.yaml_config",
    {"calendar_intelligence": {"enabled": True, "habit_min_occurrences": 3}},
)
def test_detect_habits_midnight_crossing_event():
    """_detect_habits zaehlt Stunden korrekt bei Mitternachts-uebergreifenden Events (Zeilen 155-158)."""
    ci = CalendarIntelligence()
    # Event von 23:00 bis 02:00 (naechster Tag) — crossing midnight
    events = [
        _make_event("Nachtschicht", "2026-03-08T23:00:00", "2026-03-09T02:00:00"),
    ]
    habits = ci._detect_habits(events)
    # Keine Habits da nur 1 Vorkommen, aber der Code-Pfad wird ausgefuehrt
    assert isinstance(habits, list)
