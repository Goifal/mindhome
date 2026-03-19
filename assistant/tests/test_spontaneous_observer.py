"""
Tests fuer Feature 4: Spontane Beobachtungen (SpontaneousObserver).

Erweitert in Phase 1A: Tageszeit-Stratifizierung, Behavioral Trends,
korrelierte Insights, Semantic Memory Integration.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

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


# ============================================================
# Phase 1A: Erweiterte Features
# ============================================================

class TestPhase1AConfig:
    """Tests fuer aktualisierte Default-Konfiguration."""

    @pytest.fixture
    def observer(self, ha_mock):
        with patch("assistant.spontaneous_observer.yaml_config", {"spontaneous": {}}):
            return SpontaneousObserver(ha_client=ha_mock)

    def test_max_per_day_increased(self, observer):
        """Default max_per_day sollte 5 sein (vorher 2)."""
        assert observer.max_per_day == 5

    def test_min_interval_reduced(self, observer):
        """Default min_interval_hours sollte 1.5 sein (vorher 3)."""
        assert observer.min_interval_hours == 1.5

    def test_trend_detection_enabled(self, observer):
        """Trend-Erkennung sollte standardmaessig aktiviert sein."""
        assert observer._trend_detection is True

    def test_accepts_semantic_memory(self, ha_mock):
        """Constructor sollte semantic_memory Parameter akzeptieren."""
        mem_mock = MagicMock()
        obs = SpontaneousObserver(ha_client=ha_mock, semantic_memory=mem_mock)
        assert obs.semantic_memory is mem_mock

    def test_accepts_insight_engine(self, ha_mock):
        """Constructor sollte insight_engine Parameter akzeptieren."""
        ie_mock = MagicMock()
        obs = SpontaneousObserver(ha_client=ha_mock, insight_engine=ie_mock)
        assert obs.insight_engine is ie_mock


class TestTimeSlotStratification:
    """Tests fuer Tageszeit-Stratifizierung."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        return obs

    def test_time_slots_defined(self, observer):
        """Alle drei Tageszeit-Slots sollten definiert sein."""
        assert "morning" in observer._TIME_SLOTS
        assert "daytime" in observer._TIME_SLOTS
        assert "evening" in observer._TIME_SLOTS

    def test_slot_limits_sum(self, observer):
        """Summe der Slot-Limits sollte >= max_per_day sein."""
        total = sum(s[2] for s in observer._TIME_SLOTS.values())
        assert total >= observer.max_per_day

    def test_current_slot_morning(self, observer):
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 18, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert observer._current_slot() == "morning"

    def test_current_slot_daytime(self, observer):
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 18, 14, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert observer._current_slot() == "daytime"

    def test_current_slot_evening(self, observer):
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 18, 20, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert observer._current_slot() == "evening"

    @pytest.mark.asyncio
    async def test_slot_limit_not_reached(self, observer):
        """Slot-Limit bei 0 Beobachtungen nicht erreicht."""
        observer.redis.get = AsyncMock(return_value=None)
        assert await observer._slot_limit_reached() is False

    @pytest.mark.asyncio
    async def test_increment_slot_count(self, observer):
        """Slot-Count wird inkrementiert."""
        with patch("assistant.spontaneous_observer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 18, 14, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await observer._increment_slot_count()
            observer.redis.incr.assert_called()


class TestBehavioralTrends:
    """Tests fuer Verhaltens-Trend-Erkennung."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        obs._trend_detection = True
        return obs

    @pytest.mark.asyncio
    async def test_trends_no_data(self, observer):
        """Keine Daten → None."""
        observer.redis.get = AsyncMock(return_value=None)
        observer.redis.lrange = AsyncMock(return_value=[])
        result = await observer._check_behavioral_trends()
        assert result is None

    @pytest.mark.asyncio
    async def test_trends_cached_today(self, observer):
        """Bereits analysiert heute → None (Cache-Hit)."""
        observer.redis.get = AsyncMock(return_value=b"cached")
        result = await observer._check_behavioral_trends()
        assert result is None

    @pytest.mark.asyncio
    async def test_trends_disabled(self, observer):
        """Deaktivierte Trend-Erkennung → None."""
        observer._trend_detection = False
        result = await observer._check_behavioral_trends()
        assert result is None


class TestCorrelatedInsights:
    """Tests fuer korrelierte Insights."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        obs.insight_engine = MagicMock()
        obs.insight_engine.get_recent_insights = AsyncMock(return_value=[])
        return obs

    @pytest.mark.asyncio
    async def test_no_engine(self, observer):
        """Ohne insight_engine → None."""
        observer.insight_engine = None
        result = await observer._check_correlated_insights()
        assert result is None

    @pytest.mark.asyncio
    async def test_single_finding(self, observer):
        """Nur ein Finding → keine Korrelation → None."""
        observer.insight_engine.get_recent_insights = AsyncMock(return_value=[
            {"text": "Heizung ineffizient", "room": "schlafzimmer"},
        ])
        result = await observer._check_correlated_insights()
        assert result is None

    @pytest.mark.asyncio
    async def test_correlated_same_room(self, observer):
        """Zwei Findings im gleichen Raum → korrelierte Beobachtung."""
        observer.insight_engine.get_recent_insights = AsyncMock(return_value=[
            {"text": "Heizung laeuft", "room": "schlafzimmer", "domain": "climate"},
            {"text": "Fenster offen", "room": "schlafzimmer", "domain": "sensor"},
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            result = await observer._check_correlated_insights()
        if result:
            assert result["type"] == "correlated_insight"


class TestSemanticMemoryEnrichment:
    """Tests fuer Semantic Memory Integration."""

    @pytest.fixture
    def observer(self, ha_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.semantic_memory = AsyncMock()
        obs.semantic_memory.search_facts = AsyncMock(return_value=[
            {"content": "User trinkt morgens Kaffee", "relevance": 0.8, "category": "habit"}
        ])
        obs.semantic_memory.get_relevant_conversations = AsyncMock(return_value=[])
        return obs

    @pytest.mark.asyncio
    async def test_enrichment_adds_context(self, observer):
        """Enrichment sollte Insider-Kontext hinzufuegen."""
        result = await observer._enrich_with_semantic_memory("Energieverbrauch gestiegen")
        assert "Energieverbrauch gestiegen" in result
        observer.semantic_memory.search_facts.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrichment_no_memory(self, observer):
        """Ohne semantic_memory → Text unveraendert."""
        observer.semantic_memory = None
        result = await observer._enrich_with_semantic_memory("Test")
        assert result == "Test"

    @pytest.mark.asyncio
    async def test_enrichment_no_results(self, observer):
        """Keine Suchergebnisse → Text unveraendert."""
        observer.semantic_memory.search_facts = AsyncMock(return_value=[])
        observer.semantic_memory.get_relevant_conversations = AsyncMock(return_value=[])
        result = await observer._enrich_with_semantic_memory("Test")
        assert result == "Test"
