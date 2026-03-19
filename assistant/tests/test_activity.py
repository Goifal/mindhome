"""
Tests fuer ActivityEngine — Aktivitaetserkennung + Silence/Volume Matrix.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.activity import (
    AWAY,
    FOCUSED,
    GUESTS,
    IN_CALL,
    LED_BLINK,
    RELAXING,
    SILENCE_MATRIX,
    SLEEPING,
    SUPPRESS,
    TTS_LOUD,
    TTS_QUIET,
    VOLUME_MATRIX,
    WATCHING,
    ActivityEngine,
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ha_mock():
    """HA Client Mock."""
    mock = AsyncMock()
    mock.get_states = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def engine(ha_mock):
    """ActivityEngine mit HA Mock."""
    with patch("assistant.activity.yaml_config", {"activity": {}}):
        return ActivityEngine(ha_mock)


# =====================================================================
# Signal Detection
# =====================================================================


class TestSignalDetection:
    """Tests fuer einzelne Signal-Erkennungsmethoden."""

    def test_check_away_nobody_home(self, engine):
        states = [
            {"entity_id": "person.max", "state": "not_home"},
            {"entity_id": "person.lisa", "state": "not_home"},
        ]
        assert engine._check_away(states) is True

    def test_check_away_someone_home(self, engine):
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.lisa", "state": "not_home"},
        ]
        assert engine._check_away(states) is False

    def test_check_away_no_person_entities(self, engine):
        """Ohne Person-Entities wird niemand als zuhause erkannt."""
        states = [{"entity_id": "light.wohnzimmer", "state": "on"}]
        assert engine._check_away(states) is True

    def test_check_media_playing(self, engine):
        states = [{"entity_id": "media_player.wohnzimmer", "state": "playing"}]
        result = engine._check_media_playing(states)
        assert result == "media_player.wohnzimmer"

    def test_check_media_paused_is_active(self, engine):
        """Paused zaehlt als aktiv (TV ist an, nur pausiert)."""
        states = [{"entity_id": "media_player.wohnzimmer", "state": "paused"}]
        result = engine._check_media_playing(states)
        assert result == "media_player.wohnzimmer"

    def test_check_media_off_is_inactive(self, engine):
        states = [{"entity_id": "media_player.wohnzimmer", "state": "off"}]
        assert engine._check_media_playing(states) == ""

    def test_check_media_standby_is_inactive(self, engine):
        states = [{"entity_id": "media_player.wohnzimmer", "state": "standby"}]
        assert engine._check_media_playing(states) == ""

    def test_check_media_non_configured_player_ignored(self, engine):
        """Nicht-konfigurierte Media-Player triggern kein WATCHING."""
        states = [{"entity_id": "media_player.kuechen_radio", "state": "playing"}]
        assert engine._check_media_playing(states) == ""

    def test_check_in_call(self, engine):
        states = [{"entity_id": "binary_sensor.mic_active", "state": "on"}]
        assert engine._check_in_call(states) is True

    def test_check_not_in_call(self, engine):
        states = [{"entity_id": "binary_sensor.mic_active", "state": "off"}]
        assert engine._check_in_call(states) is False

    def test_check_pc_active(self, engine):
        states = [{"entity_id": "binary_sensor.pc_active", "state": "on"}]
        assert engine._check_pc_active(states) is True

    def test_check_pc_inactive(self, engine):
        states = [{"entity_id": "binary_sensor.pc_active", "state": "off"}]
        assert engine._check_pc_active(states) is False

    def test_check_sleeping_bed_occupied_no_media(self, engine):
        """Bettsensor belegt + kein TV = sleeping."""
        states = [
            {"entity_id": "binary_sensor.bed_occupancy", "state": "on"},
        ]
        assert engine._check_sleeping(states) is True

    def test_check_sleeping_bed_occupied_with_media_is_not_sleeping(self, engine):
        """Bettsensor belegt + TV an = NICHT sleeping (fernsehen im Bett)."""
        states = [
            {"entity_id": "binary_sensor.bed_occupancy", "state": "on"},
            {"entity_id": "media_player.wohnzimmer", "state": "playing"},
        ]
        assert engine._check_sleeping(states) is False

    def test_check_sleeping_bed_occupied_with_pc_is_not_sleeping(self, engine):
        """Bettsensor belegt + PC an = NICHT sleeping."""
        states = [
            {"entity_id": "binary_sensor.bed_occupancy", "state": "on"},
            {"entity_id": "binary_sensor.pc_active", "state": "on"},
        ]
        assert engine._check_sleeping(states) is False

    def test_check_sleeping_no_bed_media_blocks(self, engine):
        """Ohne Bettsensor: Media aktiv blockiert sleeping."""
        states = [
            {"entity_id": "media_player.wohnzimmer", "state": "playing"},
            {"entity_id": "light.wohnzimmer", "state": "off"},
        ]
        assert engine._check_sleeping(states) is False

    def test_check_bed_occupied(self, engine):
        """bed_occupied Signal separat pruefbar."""
        states = [
            {"entity_id": "binary_sensor.bed_occupancy", "state": "on"},
        ]
        assert engine._check_bed_occupied(states) is True

    def test_check_bed_not_occupied(self, engine):
        states = [
            {"entity_id": "binary_sensor.bed_occupancy", "state": "off"},
        ]
        assert engine._check_bed_occupied(states) is False

    def test_check_guests_more_than_threshold(self, engine):
        """Mehr als guest_person_count (default=2) = Gaeste."""
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.lisa", "state": "home"},
            {"entity_id": "person.unknown", "state": "home"},
        ]
        assert engine._check_guests(states) is True

    def test_check_no_guests_at_threshold(self, engine):
        """Genau guest_person_count (2) = KEINE Gaeste (nur Haushalt)."""
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.lisa", "state": "home"},
        ]
        assert engine._check_guests(states) is False

    def test_check_no_guests_one_away(self, engine):
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.lisa", "state": "not_home"},
        ]
        assert engine._check_guests(states) is False

    def test_check_lights_off(self, engine):
        states = [
            {"entity_id": "light.wohnzimmer", "state": "off"},
            {"entity_id": "light.kueche", "state": "off"},
        ]
        assert engine._check_lights_off(states) is True

    def test_check_lights_on(self, engine):
        states = [
            {"entity_id": "light.wohnzimmer", "state": "on"},
            {"entity_id": "light.kueche", "state": "off"},
        ]
        assert engine._check_lights_off(states) is False

    def test_check_lights_no_lights(self, engine):
        """Keine Licht-Entities → lights_off ist False."""
        states = [{"entity_id": "sensor.temp", "state": "21"}]
        assert engine._check_lights_off(states) is False


# =====================================================================
# Classify
# =====================================================================


class TestClassify:
    """Tests fuer _classify() — Aktivitaets-Klassifikation."""

    def test_away_highest_priority(self, engine):
        signals = {"away": True, "sleeping": True, "in_call": True}
        activity, conf = engine._classify(signals)
        assert activity == AWAY
        assert conf >= 0.9

    def test_sleeping_over_in_call(self, engine):
        signals = {"away": False, "sleeping": True, "in_call": True}
        activity, _ = engine._classify(signals)
        assert activity == SLEEPING

    def test_in_call_over_watching(self, engine):
        signals = {"away": False, "sleeping": False, "in_call": True, "media_playing": "media_player.wohnzimmer"}
        activity, _ = engine._classify(signals)
        assert activity == IN_CALL

    def test_watching_over_guests(self, engine):
        signals = {"away": False, "sleeping": False, "in_call": False,
                   "media_playing": "media_player.wohnzimmer", "guests": True}
        activity, _ = engine._classify(signals)
        assert activity == WATCHING

    def test_guests_over_focused(self, engine):
        signals = {"away": False, "sleeping": False, "in_call": False,
                   "media_playing": "", "guests": True, "pc_active": True}
        activity, _ = engine._classify(signals)
        assert activity == GUESTS

    def test_focused_from_pc(self, engine):
        signals = {"away": False, "sleeping": False, "in_call": False,
                   "media_playing": "", "guests": False, "pc_active": True}
        activity, _ = engine._classify(signals)
        assert activity == FOCUSED

    def test_relaxing_default(self, engine):
        signals = {"away": False, "sleeping": False, "in_call": False,
                   "media_playing": "", "guests": False, "pc_active": False}
        activity, _ = engine._classify(signals)
        assert activity == RELAXING

    def test_sleeping_confidence_with_lights_off(self, engine):
        signals = {"away": False, "sleeping": True, "lights_off": True}
        _, conf = engine._classify(signals)
        assert conf >= 0.85

    def test_sleeping_confidence_without_lights_off(self, engine):
        signals = {"away": False, "sleeping": True, "lights_off": False}
        _, conf = engine._classify(signals)
        assert conf < 0.85


# =====================================================================
# Detect Activity (Integration)
# =====================================================================


class TestDetectActivity:
    """Tests fuer detect_activity() — Sensor-basierte Erkennung."""

    @pytest.mark.asyncio
    async def test_detect_relaxing(self, engine, ha_mock):
        """Standard: Relaxing wenn keine besonderen Signale."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "light.wohnzimmer", "state": "on"},
        ])
        result = await engine.detect_activity()
        assert result["activity"] == RELAXING

    @pytest.mark.asyncio
    async def test_detect_away(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "not_home"},
        ])
        result = await engine.detect_activity()
        assert result["activity"] == AWAY

    @pytest.mark.asyncio
    async def test_detect_in_call(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "binary_sensor.mic_active", "state": "on"},
        ])
        result = await engine.detect_activity()
        assert result["activity"] == IN_CALL

    @pytest.mark.asyncio
    async def test_detect_watching_has_trigger(self, engine, ha_mock):
        """Bei watching muss der ausloesende Media Player im trigger stehen."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "media_player.wohnzimmer", "state": "playing"},
        ])
        result = await engine.detect_activity()
        assert result["activity"] == WATCHING
        assert result["trigger"] == "media_player.wohnzimmer"

    @pytest.mark.asyncio
    async def test_detect_relaxing_has_no_trigger(self, engine, ha_mock):
        """Bei relaxing ist trigger leer."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
        ])
        result = await engine.detect_activity()
        assert result["activity"] == RELAXING
        assert result["trigger"] == ""

    @pytest.mark.asyncio
    async def test_ha_unavailable_returns_last(self, engine, ha_mock):
        """Wenn HA nicht erreichbar, letzte Aktivitaet zurueckgeben."""
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await engine.detect_activity()
        assert result["confidence"] < 0.5
        assert result["signals"].get("ha_unavailable") is True


# =====================================================================
# Manual Override
# =====================================================================


class TestManualOverride:
    """Tests fuer manuellen Aktivitaets-Override."""

    @pytest.mark.asyncio
    async def test_override_takes_precedence(self, engine, ha_mock):
        engine.set_manual_override(WATCHING, duration_minutes=60)
        result = await engine.detect_activity()
        assert result["activity"] == WATCHING
        assert result["confidence"] == 1.0
        assert result["signals"]["manual_override"] is True

    @pytest.mark.asyncio
    async def test_override_expires(self, engine, ha_mock):
        engine.set_manual_override(WATCHING, duration_minutes=1)
        engine._override_until = datetime.now(timezone.utc) - timedelta(minutes=5)  # Abgelaufen
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
        ])
        result = await engine.detect_activity()
        assert result["activity"] != WATCHING  # Override abgelaufen

    def test_clear_override(self, engine):
        engine.set_manual_override(WATCHING)
        assert engine._manual_override == WATCHING
        engine.clear_manual_override()
        assert engine._manual_override is None


# =====================================================================
# Silence Keywords
# =====================================================================


class TestSilenceKeywords:
    """Tests fuer check_silence_trigger()."""

    def test_filmabend_triggers_watching(self, engine):
        assert engine.check_silence_trigger("Filmabend") == WATCHING

    def test_meditation_triggers_focused(self, engine):
        assert engine.check_silence_trigger("Meditation starten") == FOCUSED

    def test_gute_nacht_triggers_sleeping(self, engine):
        assert engine.check_silence_trigger("Gute Nacht") == SLEEPING

    def test_no_trigger(self, engine):
        assert engine.check_silence_trigger("Wie ist das Wetter?") is None

    def test_case_insensitive(self, engine):
        assert engine.check_silence_trigger("FILMABEND") == WATCHING
        assert engine.check_silence_trigger("GUTE NACHT") == SLEEPING


# =====================================================================
# Silence Matrix
# =====================================================================


class TestSilenceMatrix:
    """Tests fuer get_delivery_method() — Stille-Matrix."""

    def test_sleeping_critical_is_loud(self, engine):
        assert engine.get_delivery_method(SLEEPING, "critical") == TTS_LOUD

    def test_sleeping_medium_suppressed(self, engine):
        assert engine.get_delivery_method(SLEEPING, "medium") == SUPPRESS

    def test_in_call_critical_is_loud(self, engine):
        """F-005: Leben > Telefonat."""
        assert engine.get_delivery_method(IN_CALL, "critical") == TTS_LOUD

    def test_in_call_medium_suppressed(self, engine):
        assert engine.get_delivery_method(IN_CALL, "medium") == SUPPRESS

    def test_relaxing_high_is_loud(self, engine):
        assert engine.get_delivery_method(RELAXING, "high") == TTS_LOUD

    def test_relaxing_low_suppressed(self, engine):
        assert engine.get_delivery_method(RELAXING, "low") == SUPPRESS

    def test_away_high_suppressed(self, engine):
        assert engine.get_delivery_method(AWAY, "high") == SUPPRESS

    def test_unknown_activity_uses_relaxing(self, engine):
        """Unbekannte Aktivitaet → Fallback auf Relaxing."""
        assert engine.get_delivery_method("unknown_xyz", "high") == TTS_LOUD

    def test_all_activities_have_critical(self):
        """Critical muss fuer jede Aktivitaet definiert sein."""
        for activity in SILENCE_MATRIX:
            assert "critical" in SILENCE_MATRIX[activity]
            # Critical ist immer TTS_LOUD (Leben > alles)
            assert SILENCE_MATRIX[activity]["critical"] == TTS_LOUD


# =====================================================================
# Volume Matrix
# =====================================================================


class TestVolumeMatrix:
    """Tests fuer get_volume_level() — Volume-Level."""

    def test_relaxing_critical_is_full(self, engine):
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 14, 0)  # 14 Uhr
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = engine.get_volume_level(RELAXING, "critical")
            assert vol == 1.0

    def test_sleeping_critical_reduced(self, engine):
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 14, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = engine.get_volume_level(SLEEPING, "critical")
            assert vol <= 0.7

    def test_all_volumes_between_0_and_1(self):
        """Alle Volume-Werte muessen im Bereich [0.0, 1.0] sein."""
        for activity, urgencies in VOLUME_MATRIX.items():
            for urgency, volume in urgencies.items():
                assert 0.0 <= volume <= 1.0, f"{activity}/{urgency}: {volume}"


# =====================================================================
# Should Deliver (Integration)
# =====================================================================


class TestShouldDeliver:
    """Tests fuer should_deliver() — kombinierte Erkennung + Zustellung."""

    @pytest.mark.asyncio
    async def test_config_silence_matrix_override(self, ha_mock):
        """User-Config ueberschreibt einzelne Silence-Matrix-Eintraege."""
        cfg = {
            "activity": {
                "silence_matrix": {
                    "watching": {
                        "high": "tts_quiet",
                        "medium": "tts_quiet",
                    }
                }
            }
        }
        with patch("assistant.activity.yaml_config", cfg):
            eng = ActivityEngine(ha_mock)
        # Overridden: watching.high = tts_quiet (statt led_blink)
        assert eng.get_delivery_method(WATCHING, "high") == TTS_QUIET
        # Overridden: watching.medium = tts_quiet (statt suppress)
        assert eng.get_delivery_method(WATCHING, "medium") == TTS_QUIET
        # Nicht ueberschrieben: watching.critical bleibt tts_loud
        assert eng.get_delivery_method(WATCHING, "critical") == TTS_LOUD
        # Nicht ueberschrieben: watching.low bleibt suppress
        assert eng.get_delivery_method(WATCHING, "low") == SUPPRESS
        # Andere Aktivitaeten unberuehrt
        assert eng.get_delivery_method(RELAXING, "high") == TTS_LOUD

    @pytest.mark.asyncio
    async def test_deliver_has_all_fields(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
        ])
        result = await engine.should_deliver("medium")
        assert "activity" in result
        assert "delivery" in result
        assert "suppress" in result
        assert "confidence" in result
        assert "volume" in result

    @pytest.mark.asyncio
    async def test_deliver_suppress_flag(self, engine, ha_mock):
        """Suppress-Flag ist True wenn delivery == suppress."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
        ])
        result = await engine.should_deliver("low")
        # Relaxing + low = suppress
        assert result["suppress"] is True


# =====================================================================
# Coverage: _build_matrix_from_config — Lines 178-180, 182-184
# =====================================================================


class TestBuildMatrixFromConfig:
    """Tests fuer _build_matrix_from_config() — Ungueltige Urgencies und Werte."""

    def test_unknown_urgency_ignored(self):
        """Unbekannte Urgency wird ignoriert (lines 178-180)."""
        from assistant.activity import _build_matrix_from_config, _DEFAULT_SILENCE_MATRIX, _VALID_DELIVERY_METHODS
        config = {"relaxing": {"unknown_urgency": "tts_loud"}}
        result = _build_matrix_from_config(config, _DEFAULT_SILENCE_MATRIX, validate_values=_VALID_DELIVERY_METHODS)
        assert "unknown_urgency" not in result.get("relaxing", {})

    def test_invalid_value_ignored(self):
        """Ungueltiger Wert wird ignoriert (lines 182-184)."""
        from assistant.activity import _build_matrix_from_config, _DEFAULT_SILENCE_MATRIX, _VALID_DELIVERY_METHODS
        config = {"relaxing": {"high": "invalid_method"}}
        result = _build_matrix_from_config(config, _DEFAULT_SILENCE_MATRIX, validate_values=_VALID_DELIVERY_METHODS)
        # Should keep default value, not the invalid one
        assert result["relaxing"]["high"] != "invalid_method"

    def test_valid_override_applied(self):
        """Gueltige Werte werden uebernommen."""
        from assistant.activity import _build_matrix_from_config, _DEFAULT_SILENCE_MATRIX, _VALID_DELIVERY_METHODS
        config = {"relaxing": {"high": "tts_quiet"}}
        result = _build_matrix_from_config(config, _DEFAULT_SILENCE_MATRIX, validate_values=_VALID_DELIVERY_METHODS)
        assert result["relaxing"]["high"] == "tts_quiet"

    def test_no_validate_values_accepts_anything(self):
        """Ohne validate_values werden alle Werte akzeptiert (Volume-Matrix)."""
        from assistant.activity import _build_matrix_from_config, _DEFAULT_VOLUME_MATRIX
        config = {"relaxing": {"high": 0.42}}
        result = _build_matrix_from_config(config, _DEFAULT_VOLUME_MATRIX, validate_values=None)
        assert result["relaxing"]["high"] == 0.42


# =====================================================================
# Coverage: Household entities — Lines 244-249
# =====================================================================


class TestHouseholdEntities:
    """Tests fuer Haushaltsmitglieder-Entity Konfiguration."""

    def test_household_entities_loaded(self, ha_mock):
        """Primary user entity und member entities werden geladen (lines 244-249)."""
        cfg = {
            "activity": {},
            "household": {
                "primary_user_entity": "person.max",
                "members": [
                    {"ha_entity": "person.anna"},
                    {"ha_entity": "person.lisa"},
                    {"ha_entity": ""},  # empty should be skipped
                    {},  # missing ha_entity should be skipped
                ],
            },
        }
        with patch("assistant.activity.yaml_config", cfg):
            eng = ActivityEngine(ha_mock)
        assert "person.max" in eng._household_entities
        assert "person.anna" in eng._household_entities
        assert "person.lisa" in eng._household_entities
        assert "" not in eng._household_entities

    def test_no_household_config(self, ha_mock):
        """Ohne Household-Config bleibt _household_entities leer."""
        with patch("assistant.activity.yaml_config", {"activity": {}}):
            eng = ActivityEngine(ha_mock)
        assert len(eng._household_entities) == 0


# =====================================================================
# Coverage: reload_config — Lines 297-320
# =====================================================================


class TestReloadConfig:
    """Tests fuer reload_config()."""

    def test_reload_config_basic(self, ha_mock):
        """reload_config laedt alle Konfigurationen neu (lines 297-320)."""
        with patch("assistant.activity.yaml_config", {"activity": {}}):
            eng = ActivityEngine(ha_mock)
        new_cfg = {
            "entities": {"media_players": ["media_player.new"]},
            "thresholds": {"night_start": 23, "night_end": 6},
        }
        eng.reload_config(new_cfg)
        assert eng.media_players == ["media_player.new"]
        assert eng.night_start == 23
        assert eng.night_end == 6

    def test_reload_config_with_silence_keywords(self, ha_mock):
        """reload_config laedt konfigurierte silence_keywords (lines 300-306)."""
        with patch("assistant.activity.yaml_config", {"activity": {}}):
            eng = ActivityEngine(ha_mock)
        new_cfg = {
            "silence_keywords": {
                "watching": ["filmabend_custom"],
                "sleeping": ["nacht_custom"],
            },
        }
        eng.reload_config(new_cfg)
        assert "filmabend_custom" in eng._silence_keywords.get("watching", [])

    def test_reload_config_without_silence_keywords(self, ha_mock):
        """reload_config ohne silence_keywords nutzt Defaults (lines 307-308)."""
        with patch("assistant.activity.yaml_config", {"activity": {}}):
            eng = ActivityEngine(ha_mock)
        eng.reload_config({})
        assert eng._silence_keywords == dict(ActivityEngine.SILENCE_KEYWORDS)

    def test_reload_config_with_matrix_overrides(self, ha_mock):
        """reload_config laedt silence/volume matrix overrides (lines 311-319)."""
        with patch("assistant.activity.yaml_config", {"activity": {}}):
            eng = ActivityEngine(ha_mock)
        new_cfg = {
            "silence_matrix": {"relaxing": {"low": "tts_quiet"}},
            "volume_matrix": {"relaxing": {"low": 0.99}},
        }
        eng.reload_config(new_cfg)
        assert eng._silence_matrix["relaxing"]["low"] == "tts_quiet"
        assert eng._volume_matrix["relaxing"]["low"] == 0.99


# =====================================================================
# Coverage: TTL cache — Line 380
# =====================================================================


class TestTTLCache:
    """Tests fuer den TTL-Cache bei detect_activity."""

    @pytest.mark.asyncio
    async def test_ttl_cache_returns_cached_result(self, engine, ha_mock):
        """Wiederholter Aufruf innerhalb TTL gibt Cache zurueck (line 380)."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home"},
        ])
        result1 = await engine.detect_activity()
        # Set cache as fresh
        import time
        engine._cache_ts = time.monotonic()
        engine._cache_ttl = 100  # long TTL
        result2 = await engine.detect_activity()
        assert result2 is result1  # same object returned from cache


# =====================================================================
# Coverage: Volume night/evening — Lines 462, 465-466, 468-469
# =====================================================================


class TestVolumeNightEvening:
    """Tests fuer Volume-Level Tageszeit-Anpassungen."""

    def test_volume_night_non_critical_capped(self, engine):
        """Nacht + non-critical wird auf 0.3 gekappt (lines 465-466)."""
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 23, 0)  # 23 Uhr = Nacht
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = engine.get_volume_level(RELAXING, "high")
            assert vol <= 0.3

    def test_volume_night_critical_not_capped(self, engine):
        """Nacht + critical bleibt ungekappt (line 465 condition)."""
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 23, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = engine.get_volume_level(RELAXING, "critical")
            assert vol == 1.0

    def test_volume_evening_non_critical_non_high_capped(self, engine):
        """Abend (1h vor Nacht) + medium wird auf 0.5 gekappt (lines 468-469)."""
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 21, 0)  # 21 Uhr = 1h vor 22
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = engine.get_volume_level(RELAXING, "medium")
            assert vol <= 0.5

    def test_volume_evening_high_not_capped(self, engine):
        """Abend + high wird NICHT gekappt (line 468 condition)."""
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 21, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = engine.get_volume_level(RELAXING, "high")
            assert vol == 0.8  # Default relaxing.high

    def test_volume_night_start_equals_end_path(self, ha_mock):
        """Wenn night_start <= night_end (ungewoehnlich): Else-Branch (line 462)."""
        with patch("assistant.activity.yaml_config", {"activity": {
            "thresholds": {"night_start": 2, "night_end": 7},
        }}):
            eng = ActivityEngine(ha_mock)
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 3, 0)  # 3 Uhr, within 2-7
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            vol = eng.get_volume_level(RELAXING, "medium")
            assert vol <= 0.3


# =====================================================================
# Coverage: Auto-Discovery — Lines 566, 568, 575-579
# =====================================================================


class TestAutoDiscovery:
    """Tests fuer _auto_discover() und Auto-Discovery in Check-Methoden."""

    def test_auto_discover_active_states_filter(self, engine):
        """active_states Filter: Entity mit unpassendem State wird uebersprungen (line 566)."""
        states = [
            {"entity_id": "binary_sensor.zoom_call", "state": "off",
             "attributes": {"friendly_name": "Zoom Call"}},
        ]
        result = ActivityEngine._auto_discover(
            states, ("binary_sensor.",), [], engine._MIC_RE, "Mic",
            active_states={"on"},
        )
        assert result == ""

    def test_auto_discover_inactive_states_filter(self, engine):
        """inactive_states Filter: Entity im inaktiven State wird uebersprungen (line 568)."""
        states = [
            {"entity_id": "media_player.fire_tv", "state": "off",
             "attributes": {"friendly_name": "Fire TV"}},
        ]
        result = ActivityEngine._auto_discover(
            states, ("media_player.",), [], engine._TV_RE, "TV",
            inactive_states={"off", "standby"},
        )
        assert result == ""

    def test_auto_discover_finds_match(self, engine):
        """Auto-Discovery findet Entity per Pattern-Match (lines 575-579)."""
        states = [
            {"entity_id": "media_player.fire_tv", "state": "playing",
             "attributes": {"friendly_name": "Fire TV Stick"}},
        ]
        result = ActivityEngine._auto_discover(
            states, ("media_player.",), [], engine._TV_RE, "TV",
            inactive_states={"off", "standby"},
        )
        assert result == "media_player.fire_tv"

    def test_auto_discover_match_by_friendly_name(self, engine):
        """Auto-Discovery matched auf friendly_name (line 574)."""
        states = [
            {"entity_id": "media_player.xyz123", "state": "playing",
             "attributes": {"friendly_name": "Samsung TV"}},
        ]
        result = ActivityEngine._auto_discover(
            states, ("media_player.",), [], engine._TV_RE, "TV",
            inactive_states={"off", "standby"},
        )
        assert result == "media_player.xyz123"

    def test_auto_discover_skips_configured(self, engine):
        """Auto-Discovery ueberspringt bereits konfigurierte Entities."""
        states = [
            {"entity_id": "media_player.fire_tv", "state": "playing",
             "attributes": {"friendly_name": "Fire TV"}},
        ]
        result = ActivityEngine._auto_discover(
            states, ("media_player.",), ["media_player.fire_tv"], engine._TV_RE, "TV",
            inactive_states={"off", "standby"},
        )
        assert result == ""


# =====================================================================
# Coverage: _check_sleeping night fallback — Line 657
# =====================================================================


class TestSleepingNightFallback:
    """Tests fuer _check_sleeping Nacht-Fallback."""

    def test_sleeping_night_lights_off_fallback(self, engine):
        """Nacht + alle Lichter aus = sleeping (Fallback, line 657)."""
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 23, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            states = [
                {"entity_id": "light.wohnzimmer", "state": "off"},
                {"entity_id": "light.kueche", "state": "off"},
            ]
            assert engine._check_sleeping(states) is True

    def test_sleeping_night_lights_on_not_sleeping(self, engine):
        """Nacht + Licht an = nicht sleeping."""
        with patch("assistant.activity.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 25, 23, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            states = [
                {"entity_id": "light.wohnzimmer", "state": "on"},
            ]
            assert engine._check_sleeping(states) is False


# =====================================================================
# Coverage: _check_pc_active — Lines 669, 676
# =====================================================================


class TestPcActiveConfigured:
    """Tests fuer _check_pc_active mit expliziter Config."""

    def test_pc_sensors_configured_empty_returns_false(self, ha_mock):
        """Explizit leere PC-Sensoren-Liste = bewusst deaktiviert (line 669)."""
        cfg = {"activity": {"entities": {"pc_sensors": []}}}
        with patch("assistant.activity.yaml_config", cfg):
            eng = ActivityEngine(ha_mock)
        states = [{"entity_id": "binary_sensor.pc_active", "state": "on"}]
        assert eng._check_pc_active(states) is False

    def test_pc_sensors_configured_no_discovery(self, ha_mock):
        """Explizit konfigurierte PC-Sensoren: kein Auto-Discovery (line 676)."""
        cfg = {"activity": {"entities": {"pc_sensors": ["binary_sensor.my_pc"]}}}
        with patch("assistant.activity.yaml_config", cfg):
            eng = ActivityEngine(ha_mock)
        states = [
            {"entity_id": "binary_sensor.my_pc", "state": "off"},
            {"entity_id": "binary_sensor.computer_xyz", "state": "on",
             "attributes": {"friendly_name": "Computer"}},
        ]
        # Configured sensor is off, auto-discovery should NOT trigger
        assert eng._check_pc_active(states) is False


# =====================================================================
# Coverage: _check_guests with household entities — Lines 692, 695
# =====================================================================


class TestGuestsWithHousehold:
    """Tests fuer _check_guests mit konfigurierten Haushaltsmitgliedern."""

    def test_guests_with_household_entities_unknown_person(self, ha_mock):
        """Unbekannte Person zuhause = Gast (lines 691-692, 694-695)."""
        cfg = {
            "activity": {},
            "household": {
                "primary_user_entity": "person.max",
                "members": [{"ha_entity": "person.anna"}],
            },
        }
        with patch("assistant.activity.yaml_config", cfg):
            eng = ActivityEngine(ha_mock)
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.anna", "state": "home"},
            {"entity_id": "person.visitor", "state": "home"},
        ]
        assert eng._check_guests(states) is True

    def test_guests_with_household_entities_no_unknown(self, ha_mock):
        """Nur Haushaltsmitglieder = keine Gaeste (line 695 returns False)."""
        cfg = {
            "activity": {},
            "household": {
                "primary_user_entity": "person.max",
                "members": [{"ha_entity": "person.anna"}],
            },
        }
        with patch("assistant.activity.yaml_config", cfg):
            eng = ActivityEngine(ha_mock)
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.anna", "state": "home"},
        ]
        assert eng._check_guests(states) is False
