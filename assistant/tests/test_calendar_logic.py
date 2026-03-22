"""
Tests for CalendarIntelligence pure functions.

All logic is copied as standalone functions to keep tests fully isolated
from the rest of the project.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Standalone copies of the functions under test
# ---------------------------------------------------------------------------


def parse_dt(dt_str):
    if not dt_str:
        return None
    try:
        if "T" in dt_str:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def detect_habits(events, habit_min_occurrences=3):
    habits = []
    time_slots = defaultdict(list)
    for ev in events:
        start = parse_dt(ev.get("start", ""))
        if not start or ev.get("all_day"):
            continue
        slot_key = f"{start.strftime('%A')}_{start.hour:02d}"
        time_slots[slot_key].append(ev.get("summary", ""))
    for slot_key, summaries in time_slots.items():
        counts = Counter(summaries)
        for title, count in counts.items():
            if count >= habit_min_occurrences and title:
                day, hour = slot_key.split("_")
                habits.append(
                    {
                        "type": "recurring_event",
                        "title": title,
                        "day": day,
                        "hour": int(hour),
                        "count": count,
                    }
                )
    return habits


def detect_conflicts(events, commute_minutes=30):
    conflicts = []
    timed_events = []
    for ev in events:
        start = parse_dt(ev.get("start", ""))
        end = parse_dt(ev.get("end", ""))
        if start and end and not ev.get("all_day"):
            timed_events.append(
                {
                    "start": start,
                    "end": end,
                    "summary": ev.get("summary", ""),
                }
            )
    timed_events.sort(key=lambda e: e["start"])
    for i in range(len(timed_events) - 1):
        curr = timed_events[i]
        nxt = timed_events[i + 1]
        gap = (nxt["start"] - curr["end"]).total_seconds() / 60
        if gap < 0:
            conflicts.append(
                {
                    "type": "overlap",
                    "event_a": curr["summary"],
                    "event_b": nxt["summary"],
                    "gap_minutes": round(gap),
                }
            )
        elif 0 < gap < commute_minutes:
            conflicts.append(
                {
                    "type": "tight_schedule",
                    "event_a": curr["summary"],
                    "event_b": nxt["summary"],
                    "gap_minutes": round(gap),
                }
            )
    return conflicts


def detect_breaks(events):
    breaks = []
    timed_events = []
    for ev in events:
        start = parse_dt(ev.get("start", ""))
        end = parse_dt(ev.get("end", ""))
        if start and end and not ev.get("all_day"):
            timed_events.append({"start": start, "end": end})
    timed_events.sort(key=lambda e: e["start"])
    for i in range(len(timed_events) - 1):
        curr_end = timed_events[i]["end"]
        next_start = timed_events[i + 1]["start"]
        gap = (next_start - curr_end).total_seconds() / 60
        if 30 <= gap <= 180:
            breaks.append(
                {
                    "start": curr_end.strftime("%H:%M"),
                    "end": next_start.strftime("%H:%M"),
                    "duration_minutes": round(gap),
                }
            )
    return breaks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(summary, start, end, all_day=False):
    """Build a minimal event dict."""
    ev = {"summary": summary, "start": start, "end": end}
    if all_day:
        ev["all_day"] = True
    return ev


# A fixed Monday for deterministic day-of-week assertions.
_MONDAY = "2026-03-09"  # a Monday


def _monday_time(hour, minute=0):
    """Return an ISO datetime string on the reference Monday."""
    return f"{_MONDAY}T{hour:02d}:{minute:02d}:00"


# ---------------------------------------------------------------------------
# parse_dt tests
# ---------------------------------------------------------------------------


class TestParseDt:
    @pytest.mark.parametrize(
        "input_str, expected_year, expected_month",
        [
            ("2026-03-08T10:00:00", 2026, 3),
            ("2026-12-25T23:59:59", 2026, 12),
        ],
    )
    def test_iso_with_t(self, input_str, expected_year, expected_month):
        result = parse_dt(input_str)
        assert result is not None
        assert result.year == expected_year
        assert result.month == expected_month

    def test_iso_with_timezone_offset(self):
        result = parse_dt("2026-03-08T10:00:00+02:00")
        assert result is not None
        assert result.hour == 10
        assert result.utcoffset() == timedelta(hours=2)

    def test_iso_with_z_suffix(self):
        result = parse_dt("2026-03-08T10:00:00Z")
        assert result is not None
        assert result.utcoffset() == timedelta(0)
        assert result.hour == 10

    def test_date_only_without_t(self):
        result = parse_dt("2026-03-08")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 8

    @pytest.mark.parametrize(
        "input_str",
        [
            "",
            None,
        ],
    )
    def test_empty_or_none_returns_none(self, input_str):
        assert parse_dt(input_str) is None

    @pytest.mark.parametrize(
        "input_str",
        [
            "not-a-date",
            "2026/03/08",
            "13-13-2026",
            "abc123",
            "2026-13-01T00:00:00",
        ],
    )
    def test_invalid_strings_return_none(self, input_str):
        assert parse_dt(input_str) is None

    def test_non_string_type_returns_none(self):
        assert parse_dt(12345) is None


# ---------------------------------------------------------------------------
# detect_habits tests
# ---------------------------------------------------------------------------


class TestDetectHabits:
    def test_recurring_event_at_threshold(self):
        """Three identical events on the same weekday+hour are detected."""
        events = [
            _make_event("Standup", _monday_time(9), _monday_time(9, 30)),
            _make_event("Standup", _monday_time(9), _monday_time(9, 30)),
            _make_event("Standup", _monday_time(9), _monday_time(9, 30)),
        ]
        habits = detect_habits(events)
        assert len(habits) == 1
        h = habits[0]
        assert h["type"] == "recurring_event"
        assert h["title"] == "Standup"
        assert h["day"] == "Monday"
        assert h["hour"] == 9
        assert h["count"] == 3

    def test_above_threshold(self):
        """Five occurrences should still produce exactly one habit entry."""
        events = [
            _make_event("Yoga", _monday_time(7), _monday_time(8)) for _ in range(5)
        ]
        habits = detect_habits(events)
        assert len(habits) == 1
        assert habits[0]["count"] == 5

    def test_below_threshold_not_detected(self):
        """Only two occurrences should not be flagged as a habit."""
        events = [
            _make_event("Coffee", _monday_time(8), _monday_time(8, 15)),
            _make_event("Coffee", _monday_time(8), _monday_time(8, 15)),
        ]
        habits = detect_habits(events)
        assert habits == []

    def test_custom_threshold(self):
        """Lowering habit_min_occurrences to 2 should detect two events."""
        events = [
            _make_event("Walk", _monday_time(12), _monday_time(12, 30)),
            _make_event("Walk", _monday_time(12), _monday_time(12, 30)),
        ]
        habits = detect_habits(events, habit_min_occurrences=2)
        assert len(habits) == 1
        assert habits[0]["count"] == 2

    def test_all_day_events_excluded(self):
        """All-day events should be ignored."""
        events = [
            _make_event("Holiday", _monday_time(0), _monday_time(23, 59), all_day=True)
            for _ in range(5)
        ]
        habits = detect_habits(events)
        assert habits == []

    def test_empty_summary_excluded(self):
        """Events with empty string summary should not become habits."""
        events = [_make_event("", _monday_time(10), _monday_time(11)) for _ in range(4)]
        habits = detect_habits(events)
        assert habits == []

    def test_different_days_not_grouped(self):
        """Same title but different weekdays should be separate slots."""
        tuesday = "2026-03-10"  # Tuesday
        events = [
            _make_event("Sync", _monday_time(9), _monday_time(9, 30)),
            _make_event("Sync", _monday_time(9), _monday_time(9, 30)),
            _make_event("Sync", f"{tuesday}T09:00:00", f"{tuesday}T09:30:00"),
        ]
        habits = detect_habits(events)
        assert habits == []

    def test_different_hours_not_grouped(self):
        """Same title on the same day but different hours are separate."""
        events = [
            _make_event("Review", _monday_time(9), _monday_time(10)),
            _make_event("Review", _monday_time(9), _monday_time(10)),
            _make_event("Review", _monday_time(14), _monday_time(15)),
        ]
        habits = detect_habits(events)
        assert habits == []

    def test_empty_events_list(self):
        assert detect_habits([]) == []

    def test_multiple_habits_detected(self):
        """Two distinct recurring patterns should yield two habits."""
        events = [
            _make_event("Standup", _monday_time(9), _monday_time(9, 30))
            for _ in range(3)
        ] + [_make_event("Lunch", _monday_time(12), _monday_time(13)) for _ in range(3)]
        habits = detect_habits(events)
        assert len(habits) == 2
        titles = {h["title"] for h in habits}
        assert titles == {"Standup", "Lunch"}


# ---------------------------------------------------------------------------
# detect_conflicts tests
# ---------------------------------------------------------------------------


class TestDetectConflicts:
    def test_overlapping_events(self):
        """Event B starts before event A ends -> overlap."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10, 30)),
            _make_event("B", _monday_time(10), _monday_time(11)),
        ]
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c["type"] == "overlap"
        assert c["event_a"] == "A"
        assert c["event_b"] == "B"
        assert c["gap_minutes"] == -30

    def test_tight_schedule(self):
        """15-minute gap with default 30-min commute -> tight schedule."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10, 15), _monday_time(11)),
        ]
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "tight_schedule"
        assert conflicts[0]["gap_minutes"] == 15

    def test_sufficient_gap_no_conflict(self):
        """A gap of exactly 30 minutes should NOT be flagged (< commute, not <=)."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10, 30), _monday_time(11)),
        ]
        conflicts = detect_conflicts(events)
        assert conflicts == []

    def test_zero_gap_no_conflict(self):
        """Back-to-back events (gap == 0) should not be flagged (condition is gap < 0 or 0 < gap < commute)."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10), _monday_time(11)),
        ]
        conflicts = detect_conflicts(events)
        assert conflicts == []

    def test_single_event_no_conflict(self):
        events = [_make_event("Solo", _monday_time(9), _monday_time(10))]
        conflicts = detect_conflicts(events)
        assert conflicts == []

    def test_empty_events(self):
        assert detect_conflicts([]) == []

    def test_all_day_events_excluded(self):
        events = [
            _make_event("Holiday", _monday_time(0), _monday_time(23, 59), all_day=True),
            _make_event("Meeting", _monday_time(9), _monday_time(10)),
        ]
        conflicts = detect_conflicts(events)
        assert conflicts == []

    def test_unsorted_input(self):
        """Events provided in reverse order should still be sorted and analysed correctly."""
        events = [
            _make_event("B", _monday_time(10), _monday_time(11)),
            _make_event("A", _monday_time(9), _monday_time(10, 30)),
        ]
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "overlap"
        assert conflicts[0]["event_a"] == "A"
        assert conflicts[0]["event_b"] == "B"

    def test_custom_commute_minutes(self):
        """A 20-min gap is fine with default 30 min but tight with 25-min commute."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10, 20), _monday_time(11)),
        ]
        # 20-min gap, default commute=30 -> tight
        assert len(detect_conflicts(events, commute_minutes=30)) == 1
        # 20-min gap, commute=15 -> no conflict
        assert len(detect_conflicts(events, commute_minutes=15)) == 0

    def test_multiple_conflicts(self):
        """Three consecutive events with two overlaps."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10, 15)),
            _make_event("B", _monday_time(10), _monday_time(11, 15)),
            _make_event("C", _monday_time(11), _monday_time(12)),
        ]
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 2
        assert all(c["type"] == "overlap" for c in conflicts)

    def test_missing_start_or_end_excluded(self):
        """Events with missing start or end are silently ignored."""
        events = [
            {"summary": "NoEnd", "start": _monday_time(9)},
            {"summary": "NoStart", "end": _monday_time(10)},
            _make_event("OK", _monday_time(11), _monday_time(12)),
        ]
        conflicts = detect_conflicts(events)
        assert conflicts == []


# ---------------------------------------------------------------------------
# detect_breaks tests
# ---------------------------------------------------------------------------


class TestDetectBreaks:
    def test_break_detected_at_lower_bound(self):
        """A 30-minute gap is the minimum break (30 <= gap)."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10, 30), _monday_time(11)),
        ]
        breaks = detect_breaks(events)
        assert len(breaks) == 1
        assert breaks[0]["start"] == "10:00"
        assert breaks[0]["end"] == "10:30"
        assert breaks[0]["duration_minutes"] == 30

    def test_break_detected_at_upper_bound(self):
        """A 180-minute gap is the maximum break (gap <= 180)."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(13), _monday_time(14)),
        ]
        breaks = detect_breaks(events)
        assert len(breaks) == 1
        assert breaks[0]["duration_minutes"] == 180

    def test_gap_too_short(self):
        """A 29-minute gap should not be reported as a break."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10, 29), _monday_time(11)),
        ]
        breaks = detect_breaks(events)
        assert breaks == []

    def test_gap_too_long(self):
        """A 181-minute gap should not be reported as a break."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(13, 1), _monday_time(14)),
        ]
        breaks = detect_breaks(events)
        assert breaks == []

    def test_no_events(self):
        assert detect_breaks([]) == []

    def test_single_event(self):
        events = [_make_event("Solo", _monday_time(9), _monday_time(10))]
        assert detect_breaks(events) == []

    def test_all_day_events_excluded(self):
        events = [
            _make_event("Holiday", _monday_time(0), _monday_time(23, 59), all_day=True),
            _make_event("Meeting", _monday_time(14), _monday_time(15)),
        ]
        breaks = detect_breaks(events)
        assert breaks == []

    def test_multiple_breaks(self):
        """Two valid gaps between three events."""
        events = [
            _make_event("A", _monday_time(8), _monday_time(9)),
            _make_event("B", _monday_time(10), _monday_time(11)),  # 60 min gap before
            _make_event("C", _monday_time(12), _monday_time(13)),  # 60 min gap before
        ]
        breaks = detect_breaks(events)
        assert len(breaks) == 2
        assert breaks[0]["duration_minutes"] == 60
        assert breaks[1]["duration_minutes"] == 60

    def test_back_to_back_no_break(self):
        """Zero gap should not count as a break."""
        events = [
            _make_event("A", _monday_time(9), _monday_time(10)),
            _make_event("B", _monday_time(10), _monday_time(11)),
        ]
        breaks = detect_breaks(events)
        assert breaks == []

    def test_unsorted_input(self):
        """Events provided out of order should still yield correct breaks."""
        events = [
            _make_event("B", _monday_time(11), _monday_time(12)),
            _make_event("A", _monday_time(9), _monday_time(10)),
        ]
        breaks = detect_breaks(events)
        assert len(breaks) == 1
        assert breaks[0]["start"] == "10:00"
        assert breaks[0]["end"] == "11:00"
        assert breaks[0]["duration_minutes"] == 60

    @pytest.mark.parametrize(
        "gap_minutes, expected_count",
        [
            (29, 0),
            (30, 1),
            (90, 1),
            (180, 1),
            (181, 0),
        ],
    )
    def test_boundary_gaps(self, gap_minutes, expected_count):
        """Parametrized boundary check for break detection window."""
        end_a = 10 * 60  # event A ends at 10:00
        start_b = end_a + gap_minutes
        end_b = start_b + 30
        events = [
            _make_event("A", _monday_time(9), _monday_time(end_a // 60, end_a % 60)),
            _make_event(
                "B",
                _monday_time(start_b // 60, start_b % 60),
                _monday_time(end_b // 60, end_b % 60),
            ),
        ]
        breaks = detect_breaks(events)
        assert len(breaks) == expected_count
