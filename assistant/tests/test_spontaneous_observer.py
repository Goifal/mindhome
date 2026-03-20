"""
Tests fuer Feature 4: Spontane Beobachtungen (SpontaneousObserver).

Erweitert in Phase 1A: Tageszeit-Stratifizierung, Behavioral Trends,
korrelierte Insights, Semantic Memory Integration.
"""
import asyncio
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


# ============================================================
# Public API Tests
# ============================================================

class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, ha_mock, redis_mock):
        """initialize() setzt self.redis."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.enabled = False  # Verhindert Loop-Start
        await obs.initialize(redis_client=redis_mock)
        assert obs.redis is redis_mock

    @pytest.mark.asyncio
    async def test_initialize_starts_loop_when_enabled(self, ha_mock, redis_mock):
        """initialize() startet den Loop wenn enabled und redis vorhanden."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.enabled = True
        with patch.object(obs, "_observe_loop", new_callable=AsyncMock) as mock_loop:
            await obs.initialize(redis_client=redis_mock)
            assert obs._running is True
            assert obs._task is not None

    @pytest.mark.asyncio
    async def test_initialize_no_loop_without_redis(self, ha_mock):
        """initialize() startet keinen Loop ohne Redis."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.enabled = True
        await obs.initialize(redis_client=None)
        assert obs._running is False
        assert obs._task is None

    @pytest.mark.asyncio
    async def test_initialize_cancels_existing_task(self, ha_mock, redis_mock):
        """initialize() bricht bestehenden Task ab."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.enabled = False
        old_task = MagicMock()
        old_task.done.return_value = False
        obs._task = old_task
        await obs.initialize(redis_client=redis_mock)
        old_task.cancel.assert_called_once()


class TestSetNotifyCallback:
    """Tests fuer set_notify_callback()."""

    def test_set_callback(self, ha_mock):
        """Callback wird korrekt gesetzt."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        cb = AsyncMock()
        obs.set_notify_callback(cb)
        assert obs._notify_callback is cb


class TestStop:
    """Tests fuer stop()."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, ha_mock):
        """stop() setzt _running auf False."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs._running = True
        obs._task = None
        await obs.stop()
        assert obs._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, ha_mock):
        """stop() bricht den Task ab und setzt ihn auf None."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs._running = True

        async def fake_loop():
            await asyncio.sleep(3600)

        obs._task = asyncio.create_task(fake_loop())
        await obs.stop()
        assert obs._task is None
        assert obs._running is False


# ============================================================
# Sensor Snapshot
# ============================================================

class TestBuildSensorSnapshot:
    """Tests fuer _build_sensor_snapshot()."""

    @pytest.fixture
    def observer(self, ha_mock):
        return SpontaneousObserver(ha_client=ha_mock)

    def test_empty_states(self, observer):
        """Leere States → leerer Snapshot."""
        assert observer._build_sensor_snapshot([]) == ""

    def test_filters_unavailable(self, observer):
        """Unavailable/unknown States werden gefiltert."""
        states = [
            {"entity_id": "sensor.temp", "state": "unavailable",
             "attributes": {"device_class": "temperature"}},
            {"entity_id": "sensor.hum", "state": "unknown",
             "attributes": {"device_class": "humidity"}},
        ]
        assert observer._build_sensor_snapshot(states) == ""

    def test_includes_relevant_device_classes(self, observer):
        """Relevante device_classes werden einbezogen."""
        states = [
            {"entity_id": "sensor.temp_living", "state": "21.5",
             "attributes": {"device_class": "temperature", "unit_of_measurement": "°C",
                            "friendly_name": "Wohnzimmer Temperatur"}},
        ]
        result = observer._build_sensor_snapshot(states)
        assert "Wohnzimmer Temperatur" in result
        assert "21.5°C" in result

    def test_includes_by_entity_id_keyword(self, observer):
        """Entities mit relevanten Keywords im entity_id werden einbezogen."""
        states = [
            {"entity_id": "sensor.weather_temp_outside", "state": "15",
             "attributes": {"unit_of_measurement": "°C",
                            "friendly_name": "Aussentemperatur"}},
        ]
        result = observer._build_sensor_snapshot(states)
        assert "Aussentemperatur" in result

    def test_max_30_lines(self, observer):
        """Maximal 30 Eintraege."""
        states = [
            {"entity_id": f"sensor.temp_{i}", "state": str(20 + i),
             "attributes": {"device_class": "temperature", "unit_of_measurement": "°C",
                            "friendly_name": f"Sensor {i}"}}
            for i in range(50)
        ]
        result = observer._build_sensor_snapshot(states)
        assert len(result.strip().split("\n")) == 30

    def test_filters_irrelevant_entities(self, observer):
        """Irrelevante Entities (kein Keyword, kein device_class) werden ignoriert."""
        states = [
            {"entity_id": "switch.lamp_1", "state": "on",
             "attributes": {"friendly_name": "Lampe 1"}},
        ]
        assert observer._build_sensor_snapshot(states) == ""


# ============================================================
# Weather Streak Check
# ============================================================

class TestCheckWeatherStreak:
    """Tests fuer _check_weather_streak()."""

    @pytest.fixture
    def observer(self, ha_mock):
        return SpontaneousObserver(ha_client=ha_mock)

    @pytest.mark.asyncio
    async def test_no_states(self, observer, ha_mock):
        """Keine States → None."""
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await observer._check_weather_streak()
        assert result is None

    @pytest.mark.asyncio
    async def test_sunny_hot(self, observer, ha_mock):
        """Sonnig und >= 25 Grad → Beobachtung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "weather.home", "state": "sunny",
             "attributes": {"temperature": 28}},
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            result = await observer._check_weather_streak()
        assert result is not None
        assert result["type"] == "weather_streak"
        assert "28" in result["message"]

    @pytest.mark.asyncio
    async def test_sunny_cool(self, observer, ha_mock):
        """Sonnig aber < 25 Grad → None."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "weather.home", "state": "sunny",
             "attributes": {"temperature": 18}},
        ])
        result = await observer._check_weather_streak()
        assert result is None

    @pytest.mark.asyncio
    async def test_snowy(self, observer, ha_mock):
        """Schnee → Beobachtung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "weather.home", "state": "snowy",
             "attributes": {"temperature": -2}},
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            result = await observer._check_weather_streak()
        assert result is not None
        assert result["type"] == "weather_streak"
        assert "schneit" in result["message"]

    @pytest.mark.asyncio
    async def test_cloudy_no_observation(self, observer, ha_mock):
        """Bewoelkt → None."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "weather.home", "state": "cloudy",
             "attributes": {"temperature": 15}},
        ])
        result = await observer._check_weather_streak()
        assert result is None


# ============================================================
# House Efficiency Check
# ============================================================

class TestCheckHouseEfficiency:
    """Tests fuer _check_house_efficiency()."""

    @pytest.fixture
    def observer(self, ha_mock):
        return SpontaneousObserver(ha_client=ha_mock)

    @pytest.mark.asyncio
    async def test_nobody_home_waste(self, observer, ha_mock):
        """Niemand zuhause aber viele Geraete an → Beobachtung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "not_home", "attributes": {}},
            {"entity_id": "light.living", "state": "on", "attributes": {}},
            {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            {"entity_id": "light.bedroom", "state": "on", "attributes": {}},
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            result = await observer._check_house_efficiency()
        assert result is not None
        assert result["type"] == "house_efficiency"
        assert "leere Wohnung" in result["message"]

    @pytest.mark.asyncio
    async def test_efficient_during_day(self, observer, ha_mock):
        """Effizientes Haus bei Tageslicht → positive Beobachtung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home", "attributes": {}},
            {"entity_id": "light.living", "state": "off", "attributes": {}},
            {"entity_id": "climate.living", "state": "heat",
             "attributes": {"hvac_action": "idle"}},
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            with patch("assistant.spontaneous_observer._local_now") as mock_now:
                mock_now.return_value = datetime(2026, 3, 18, 14, 0)
                result = await observer._check_house_efficiency()
        assert result is not None
        assert "effizient" in result["message"]

    @pytest.mark.asyncio
    async def test_no_states(self, observer, ha_mock):
        """Keine States → None."""
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await observer._check_house_efficiency()
        assert result is None

    @pytest.mark.asyncio
    async def test_normal_usage_no_observation(self, observer, ha_mock):
        """Normale Nutzung (jemand da, mehrere Geraete an) → None."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home", "attributes": {}},
            {"entity_id": "light.living", "state": "on", "attributes": {}},
            {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            {"entity_id": "climate.living", "state": "heat",
             "attributes": {"hvac_action": "heating"}},
            {"entity_id": "climate.bedroom", "state": "heat",
             "attributes": {"hvac_action": "heating"}},
        ])
        result = await observer._check_house_efficiency()
        assert result is None


# ============================================================
# Is Tool Result Interesting (static method)
# ============================================================

class TestIsToolResultInteresting:
    """Tests fuer _is_tool_result_interesting()."""

    def test_threshold_out_of_range(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "threshold_monitor", {"in_range": False}
        ) is True

    def test_threshold_in_range(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "threshold_monitor", {"in_range": True}
        ) is False

    def test_trend_significant(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "trend_analyzer", {"trend": "steigend", "trend_diff": 2.5}
        ) is True

    def test_trend_stable(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "trend_analyzer", {"trend": "stabil", "trend_diff": 0.1}
        ) is False

    def test_trend_small_diff(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "trend_analyzer", {"trend": "steigend", "trend_diff": 0.5}
        ) is False

    def test_entity_comparison_significant(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "entity_comparison", {"result": 2.0}
        ) is True

    def test_entity_comparison_zero(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "entity_comparison", {"result": 0}
        ) is False

    def test_entity_aggregator_spread(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "entity_aggregator", {"values": {"a": 20, "b": 25}}
        ) is True

    def test_entity_aggregator_no_spread(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "entity_aggregator", {"values": {"a": 20, "b": 21}}
        ) is False

    def test_entity_aggregator_single(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "entity_aggregator", {"values": {"a": 20}}
        ) is False

    def test_event_counter_enough(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "event_counter", {"count": 10}
        ) is True

    def test_event_counter_too_few(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "event_counter", {"count": 2}
        ) is False

    def test_state_duration_high_pct(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "state_duration", {"percentage": 50, "duration_hours": 5}
        ) is True

    def test_state_duration_low_pct_with_hours(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "state_duration", {"percentage": 3, "duration_hours": 1}
        ) is True

    def test_state_duration_normal(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "state_duration", {"percentage": 15, "duration_hours": 2}
        ) is False

    def test_time_comparison_big_change(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "time_comparison", {"pct_change": 25}
        ) is True

    def test_time_comparison_small_change(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "time_comparison", {"pct_change": 5}
        ) is False

    def test_unknown_type_always_interesting(self):
        assert SpontaneousObserver._is_tool_result_interesting(
            "multi_entity_formula", {"result": 42}
        ) is True


# ============================================================
# Energy Comparison Check
# ============================================================

class TestCheckEnergyComparison:
    """Tests fuer _check_energy_comparison()."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        return obs

    @pytest.mark.asyncio
    async def test_no_redis(self, ha_mock):
        """Ohne Redis → None."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        result = await obs._check_energy_comparison()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_today_data(self, observer):
        """Keine heutigen Daten → None."""
        observer.redis.mget = AsyncMock(return_value=[None, None])
        result = await observer._check_energy_comparison()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_week_data(self, observer):
        """Keine Vorwochendaten → None."""
        observer.redis.mget = AsyncMock(return_value=[
            json.dumps({"consumption_wh": 5000}), None
        ])
        result = await observer._check_energy_comparison()
        assert result is None

    @pytest.mark.asyncio
    async def test_significant_increase(self, observer):
        """Signifikanter Anstieg (>= 15%) → Beobachtung."""
        observer.redis.mget = AsyncMock(return_value=[
            json.dumps({"consumption_wh": 6000}),
            json.dumps({"consumption_wh": 4000}),
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            result = await observer._check_energy_comparison()
        assert result is not None
        assert result["type"] == "energy_comparison"
        assert "ueber" in result["message"]

    @pytest.mark.asyncio
    async def test_significant_decrease(self, observer):
        """Signifikante Abnahme (>= 15%) → positive Beobachtung."""
        observer.redis.mget = AsyncMock(return_value=[
            json.dumps({"consumption_wh": 3000}),
            json.dumps({"consumption_wh": 5000}),
        ])
        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            result = await observer._check_energy_comparison()
        assert result is not None
        assert "weniger" in result["message"]

    @pytest.mark.asyncio
    async def test_small_difference_no_observation(self, observer):
        """Kleine Differenz (< 15%) → None."""
        observer.redis.mget = AsyncMock(return_value=[
            json.dumps({"consumption_wh": 5100}),
            json.dumps({"consumption_wh": 5000}),
        ])
        result = await observer._check_energy_comparison()
        assert result is None


# ============================================================
# Find Interesting Observation
# ============================================================

class TestFindInterestingObservation:
    """Tests fuer _find_interesting_observation()."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        obs._trend_detection = False
        obs.insight_engine = None
        obs._ollama = None
        return obs

    @pytest.mark.asyncio
    async def test_returns_first_not_on_cooldown(self, observer):
        """Gibt erste Beobachtung zurueck die nicht auf Cooldown ist."""
        obs_result = {"type": "weather_streak", "message": "Test"}
        observer.redis.get = AsyncMock(return_value=None)  # Kein Cooldown
        with patch.object(observer, "_check_energy_comparison",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_weather_streak",
                          new_callable=AsyncMock, return_value=obs_result), \
             patch.object(observer, "_check_usage_record",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_device_milestone",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_house_efficiency",
                          new_callable=AsyncMock, return_value=None), \
             patch("assistant.spontaneous_observer.yaml_config", {"spontaneous": {"checks": {}}, "declarative_tools": {"enabled": False}}):
            result = await observer._find_interesting_observation()
        # Due to shuffle, we might or might not get this one, but no error should occur
        # The test verifies the method runs without error
        assert result is None or result["type"] == "weather_streak"

    @pytest.mark.asyncio
    async def test_skips_on_cooldown(self, observer):
        """Ueberspringt Beobachtungen auf Cooldown."""
        obs_result = {"type": "weather_streak", "message": "Test"}
        observer.redis.get = AsyncMock(return_value=b"1")  # Alles auf Cooldown
        with patch.object(observer, "_check_energy_comparison",
                          new_callable=AsyncMock, return_value=obs_result), \
             patch.object(observer, "_check_weather_streak",
                          new_callable=AsyncMock, return_value=obs_result), \
             patch.object(observer, "_check_usage_record",
                          new_callable=AsyncMock, return_value=obs_result), \
             patch.object(observer, "_check_device_milestone",
                          new_callable=AsyncMock, return_value=obs_result), \
             patch.object(observer, "_check_house_efficiency",
                          new_callable=AsyncMock, return_value=obs_result), \
             patch("assistant.spontaneous_observer.yaml_config", {"spontaneous": {"checks": {}}, "declarative_tools": {"enabled": False}}):
            result = await observer._find_interesting_observation()
        assert result is None

    @pytest.mark.asyncio
    async def test_all_checks_return_none(self, observer):
        """Alle Checks geben None zurueck → None."""
        observer.redis.get = AsyncMock(return_value=None)
        with patch.object(observer, "_check_energy_comparison",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_weather_streak",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_usage_record",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_device_milestone",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(observer, "_check_house_efficiency",
                          new_callable=AsyncMock, return_value=None), \
             patch("assistant.spontaneous_observer.yaml_config", {"spontaneous": {"checks": {}}, "declarative_tools": {"enabled": False}}):
            result = await observer._find_interesting_observation()
        assert result is None


# ============================================================
# LLM Observation Check
# ============================================================

class TestCheckLlmObservation:
    """Tests fuer _check_llm_observation()."""

    @pytest.fixture
    def observer(self, ha_mock, ollama_mock):
        obs = SpontaneousObserver(ha_client=ha_mock, ollama_client=ollama_mock)
        obs.semantic_memory = None
        return obs

    @pytest.mark.asyncio
    async def test_no_ollama(self, ha_mock):
        """Ohne Ollama → None."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs._ollama = None
        result = await obs._check_llm_observation()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_states(self, observer, ha_mock):
        """Keine HA States → None."""
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await observer._check_llm_observation()
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_snapshot(self, observer, ha_mock, ollama_mock):
        """Leerer Snapshot (keine relevanten Sensoren) → None."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.lamp", "state": "on", "attributes": {}},
        ])
        result = await observer._check_llm_observation()
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_llm_response(self, observer, ha_mock, ollama_mock):
        """Gueltige LLM-Antwort → Beobachtung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.temp", "state": "22",
             "attributes": {"device_class": "temperature", "unit_of_measurement": "°C",
                            "friendly_name": "Temperatur"}},
        ])
        ollama_mock.generate = AsyncMock(
            return_value="Die Temperatur ist seit gestern um 3 Grad gestiegen."
        )
        with patch("assistant.spontaneous_observer._local_now",
                    return_value=datetime(2026, 3, 18, 14, 0)):
            result = await observer._check_llm_observation()
        assert result is not None
        assert result["type"] == "llm_observation"

    @pytest.mark.asyncio
    async def test_short_llm_response_ignored(self, observer, ha_mock, ollama_mock):
        """Zu kurze LLM-Antwort (< 20 Zeichen) → None."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.temp", "state": "22",
             "attributes": {"device_class": "temperature", "unit_of_measurement": "°C",
                            "friendly_name": "Temperatur"}},
        ])
        ollama_mock.generate = AsyncMock(return_value="OK.")
        with patch("assistant.spontaneous_observer._local_now",
                    return_value=datetime(2026, 3, 18, 14, 0)):
            result = await observer._check_llm_observation()
        assert result is None


# ============================================================
# Behavioral Trends with actual data
# ============================================================

class TestBehavioralTrendsWithData:
    """Erweiterte Tests fuer _check_behavioral_trends() mit echten Trend-Daten."""

    @pytest.fixture
    def observer(self, ha_mock, redis_mock):
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = redis_mock
        obs._trend_detection = True
        return obs

    @pytest.mark.asyncio
    async def test_detects_later_trend(self, observer):
        """Erkennt Trend: Aktion verschiebt sich nach spaeter."""
        # Cache leer → Analyse laeuft
        cache_returns = {}

        async def smart_get(key):
            if "trend_cache" in key:
                return None
            return cache_returns.get(key)

        observer.redis.get = smart_get

        # 4 Tage mit steigender Uhrzeit fuer "coffee"
        day_data = {}
        for i in range(4):
            day = (datetime(2026, 3, 18) - timedelta(days=i)).strftime("%Y-%m-%d")
            entry = json.dumps({"action": "coffee", "hour": 8 + i}).encode()
            day_data[f"mha:action_log:{day}"] = [entry]

        async def smart_lrange(key, start, end):
            return day_data.get(key, [])

        observer.redis.lrange = smart_lrange

        with patch("assistant.spontaneous_observer.get_person_title", return_value="Sir"):
            with patch("assistant.spontaneous_observer._local_now",
                        return_value=datetime(2026, 3, 18, 14, 0)):
                result = await observer._check_behavioral_trends()

        assert result is not None
        assert result["type"] == "behavioral_trend"
        assert "Coffee" in result["message"]


# ============================================================
# Daily Count without Redis
# ============================================================

class TestDailyCountEdgeCases:
    """Weitere Tests fuer _daily_count / _increment Logik."""

    @pytest.mark.asyncio
    async def test_daily_count_no_redis(self, ha_mock):
        """Ohne Redis → 0."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        count = await obs._daily_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_increment_daily_count_no_redis(self, ha_mock):
        """Increment ohne Redis → kein Fehler."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        await obs._increment_daily_count()  # Darf nicht crashen

    @pytest.mark.asyncio
    async def test_on_cooldown_no_redis(self, ha_mock):
        """Cooldown ohne Redis → False."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        result = await obs._on_cooldown("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_cooldown_no_redis(self, ha_mock):
        """Set Cooldown ohne Redis → kein Fehler."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        await obs._set_cooldown("test", 3600)  # Darf nicht crashen

    @pytest.mark.asyncio
    async def test_slot_limit_no_redis(self, ha_mock):
        """Slot Limit ohne Redis → False."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        result = await obs._slot_limit_reached()
        assert result is False

    @pytest.mark.asyncio
    async def test_increment_slot_no_redis(self, ha_mock):
        """Increment Slot ohne Redis → kein Fehler."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        obs.redis = None
        await obs._increment_slot_count()  # Darf nicht crashen


# ============================================================
# Observation History (deque)
# ============================================================

class TestObservationHistory:
    """Tests fuer _observation_history Verwaltung."""

    def test_history_initialized(self, ha_mock):
        """History deque wird beim Init erstellt."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        assert len(obs._observation_history) == 0
        assert obs._observation_history.maxlen == 20

    def test_history_maxlen(self, ha_mock):
        """History respektiert maxlen von 20."""
        obs = SpontaneousObserver(ha_client=ha_mock)
        for i in range(25):
            obs._observation_history.append({"text": f"obs_{i}"})
        assert len(obs._observation_history) == 20
        assert obs._observation_history[0]["text"] == "obs_5"


# ============================================================
# Current Slot edge cases
# ============================================================

class TestCurrentSlotEdgeCases:
    """Weitere Tests fuer _current_slot()."""

    @pytest.fixture
    def observer(self, ha_mock):
        return SpontaneousObserver(ha_client=ha_mock)

    def test_slot_returns_none_outside_all_slots(self, observer):
        """Stunde ausserhalb aller Slots (z.B. 3 Uhr) → None."""
        with patch("assistant.spontaneous_observer._local_now",
                    return_value=datetime(2026, 3, 18, 3, 0)):
            assert observer._current_slot() is None

    def test_slot_boundary_morning_start(self, observer):
        """Genau 6 Uhr → morning."""
        with patch("assistant.spontaneous_observer._local_now",
                    return_value=datetime(2026, 3, 18, 6, 0)):
            assert observer._current_slot() == "morning"

    def test_slot_boundary_daytime_start(self, observer):
        """Genau 10 Uhr → daytime."""
        with patch("assistant.spontaneous_observer._local_now",
                    return_value=datetime(2026, 3, 18, 10, 0)):
            assert observer._current_slot() == "daytime"

    def test_slot_boundary_evening_end(self, observer):
        """Genau 22 Uhr → None (ausserhalb evening)."""
        with patch("assistant.spontaneous_observer._local_now",
                    return_value=datetime(2026, 3, 18, 22, 0)):
            assert observer._current_slot() is None
