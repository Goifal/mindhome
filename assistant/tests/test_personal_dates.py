"""Tests fuer PersonalDatesManager - Geburtstags-/Jahrestags-Automatik."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from assistant.personal_dates import PersonalDatesManager, _format_date_type


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.smembers = AsyncMock(return_value=set())
    mock.exists = AsyncMock(return_value=0)
    mock.set = AsyncMock()

    pipe = MagicMock()
    pipe.hgetall = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe)

    return mock


@pytest.fixture
def pd_mgr(redis_mock):
    pdm = PersonalDatesManager()
    pdm.redis = redis_mock
    return pdm


@pytest.mark.asyncio
async def test_get_upcoming_empty(pd_mgr):
    result = await pd_mgr.get_upcoming_dates(30)
    assert result == []


@pytest.mark.asyncio
async def test_get_upcoming_with_dates(pd_mgr, redis_mock):
    now = datetime.now(timezone.utc)
    today_mm_dd = now.strftime("%m-%d")

    redis_mock.smembers = AsyncMock(return_value={"fact_123"})
    pipe = MagicMock()
    pipe.hgetall = MagicMock()
    pipe.execute = AsyncMock(
        return_value=[
            {
                "person": "lisa",
                "date_type": "birthday",
                "date_mm_dd": today_mm_dd,
                "date_year": "1990",
                "content": "Lisas Geburtstag",
            }
        ]
    )
    redis_mock.pipeline = MagicMock(return_value=pipe)

    result = await pd_mgr.get_upcoming_dates(7)
    assert len(result) >= 1
    assert result[0]["person"] == "lisa"


@pytest.mark.asyncio
async def test_get_briefing_section_empty(pd_mgr):
    section = await pd_mgr.get_briefing_section()
    assert section == ""


@pytest.mark.asyncio
async def test_get_person_dates_empty(pd_mgr, redis_mock):
    result = await pd_mgr.get_person_dates("max")
    assert result == []


def test_format_date_type():
    assert _format_date_type("birthday") == "Geburtstag"
    assert _format_date_type("anniversary") == "Jahrestag"
    assert _format_date_type("wedding") == "Hochzeitstag"
    assert _format_date_type("", "Namenstag") == "Namenstag"
    assert _format_date_type("unknown_type") == "unknown_type"


@pytest.mark.asyncio
async def test_check_and_notify_no_callback(pd_mgr):
    """Ohne Callback sollte nichts passieren."""
    await pd_mgr.check_and_notify()  # Kein Fehler


def test_format_reminder():
    pdm = PersonalDatesManager()
    entry = {
        "person": "lisa",
        "date_type": "birthday",
        "label": "",
        "year": "1990",
        "days_until": 0,
    }
    msg = pdm._format_reminder(entry)
    assert "Heute" in msg
    assert "Lisa" in msg

    entry["days_until"] = 1
    msg = pdm._format_reminder(entry)
    assert "Morgen" in msg

    entry["days_until"] = 5
    msg = pdm._format_reminder(entry)
    assert "5 Tagen" in msg
