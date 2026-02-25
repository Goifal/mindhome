"""
Tests fuer Feature 4: Spontane Beobachtungen (SpontaneousObserver).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from assistant.spontaneous_observer import SpontaneousObserver


class TestActiveHours:
    """Tests fuer _within_active_hours()."""

    @pytest.fixture
    def observer(self, ha_mock):
        """SpontaneousObserver mit Mocks."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.active_start = 8
        obs.active_end = 22
        return obs

    def test_within_active_hours(self, observer):
        """Innerhalb aktiver Stunden (z.B. 14 Uhr)."""
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 14, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert observer._within_active_hours() is True

    def test_outside_active_hours_early(self, observer):
        """Vor aktiven Stunden (z.B. 5 Uhr)."""
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 5, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert observer._within_active_hours() is False

    def test_outside_active_hours_late(self, observer):
        """Nach aktiven Stunden (z.B. 23 Uhr)."""
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 23, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert observer._within_active_hours() is False


class TestDailyLimit:
    """Tests fuer Daily-Count Logik."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        obs.max_per_day = 2
        return obs

    @pytest.mark.asyncio
    async def test_daily_count_zero(self, observer):
        """Bei Count 0: unter dem Limit."""
        observer.redis.get = AsyncMock(return_value=None)
        count = await observer._daily_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_daily_count_increments(self, observer):
        """Increment zaehlt hoch."""
        observer.redis.get = AsyncMock(return_value=b"1")
        count = await observer._daily_count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_increment_daily_count(self, observer):
        """Increment setzt Counter korrekt."""
        await observer._increment_daily_count()
        observer.redis.incr.assert_called()


class TestCooldown:
    """Tests fuer Cooldown-Logik."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        return obs

    @pytest.mark.asyncio
    async def test_on_cooldown(self, observer):
        """Typ auf Cooldown → True."""
        observer.redis.get = AsyncMock(return_value=b"1")
        result = await observer._on_cooldown("energy_comparison")
        assert result is True

    @pytest.mark.asyncio
    async def test_not_on_cooldown(self, observer):
        """Typ nicht auf Cooldown → False."""
        observer.redis.get = AsyncMock(return_value=None)
        result = await observer._on_cooldown("energy_comparison")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_cooldown(self, observer):
        """Cooldown wird mit TTL gesetzt."""
        await observer._set_cooldown("energy_comparison", 86400)
        observer.redis.setex.assert_called()


class TestTitleForPresent:
    """Tests fuer _get_title_for_present()."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        return obs

    @pytest.mark.asyncio
    async def test_one_person_home(self, observer, ha_mock):
        """Eine Person zuhause → deren Titel."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "person.max",
                "state": "home",
                "attributes": {"friendly_name": "Max"},
            },
        ])
        with patch("assistant.spontaneous_observer.get_person_title") as mock_title:
            mock_title.return_value = "Sir"
            result = await observer._get_title_for_present()
            mock_title.assert_called_with("Max")
            assert result == "Sir"

    @pytest.mark.asyncio
    async def test_two_persons_home(self, observer, ha_mock):
        """Zwei Personen zuhause → beide Titel."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "person.max",
                "state": "home",
                "attributes": {"friendly_name": "Max"},
            },
            {
                "entity_id": "person.anna",
                "state": "home",
                "attributes": {"friendly_name": "Anna"},
            },
        ])
        with patch("assistant.spontaneous_observer.get_person_title") as mock_title:
            mock_title.side_effect = lambda n: "Sir" if n == "Max" else "Ma'am"
            result = await observer._get_title_for_present()
            assert "Sir" in result
            assert "Ma'am" in result

    @pytest.mark.asyncio
    async def test_nobody_home_fallback(self, observer, ha_mock):
        """Niemand zuhause → Fallback."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "person.max",
                "state": "not_home",
                "attributes": {"friendly_name": "Max"},
            },
        ])
        with patch("assistant.spontaneous_observer.get_person_title") as mock_title:
            mock_title.return_value = "Sir"
            result = await observer._get_title_for_present()
            assert result == "Sir"
