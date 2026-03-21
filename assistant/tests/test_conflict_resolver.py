"""
Tests fuer ConflictResolver — Konflikterkennung, Recording, Labels,
Konfliktloesung, Prediction, Room-Presence, Redis-Persistenz.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.conflict_resolver import (
    ConflictResolver,
    FUNCTION_DOMAIN_MAP,
    get_conflict_parameters,
    _LOGICAL_CONFLICT_RULES,
)


@pytest.fixture
def resolver():
    autonomy = MagicMock()
    autonomy.get_trust_level = MagicMock(return_value=3)
    ollama = AsyncMock()
    r = ConflictResolver(autonomy, ollama)
    r.enabled = True
    return r


class TestRecordCommand:
    """Tests fuer record_command()."""

    def test_records_command(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 100}, "wohnzimmer")
        assert len(resolver._recent_commands["max"]) == 1
        cmd = resolver._recent_commands["max"][0]
        assert cmd["person"] == "max"
        assert cmd["function"] == "set_light"
        assert cmd["args"]["brightness"] == 100
        assert cmd["room"] == "wohnzimmer"

    def test_multiple_commands_same_person(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 50})
        resolver.record_command("Max", "set_light", {"brightness": 100})
        assert len(resolver._recent_commands["max"]) == 2

    def test_different_persons(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 50})
        resolver.record_command("Anna", "set_light", {"brightness": 100})
        assert len(resolver._recent_commands["max"]) == 1
        assert len(resolver._recent_commands["anna"]) == 1

    def test_disabled_no_record(self, resolver):
        resolver.enabled = False
        resolver.record_command("Max", "set_light", {"brightness": 50})
        assert len(resolver._recent_commands) == 0

    def test_empty_person_no_record(self, resolver):
        resolver.record_command("", "set_light", {"brightness": 50})
        assert len(resolver._recent_commands) == 0

    def test_ring_buffer_limit(self, resolver):
        resolver._max_commands = 3
        for i in range(5):
            resolver.record_command("Max", "set_light", {"brightness": i * 10})
        assert len(resolver._recent_commands["max"]) == 3


class TestDetectConflict:
    """Tests fuer _detect_conflict()."""

    def test_numeric_conflict(self, resolver):
        result = resolver._detect_conflict(
            "climate",
            {"temperature": 25},
            {"temperature": 19},
            {"threshold": 3},
        )
        assert result is not None
        assert result["type"] == "numeric"
        assert result["difference"] == 6

    def test_numeric_no_conflict_within_threshold(self, resolver):
        result = resolver._detect_conflict(
            "climate",
            {"temperature": 21},
            {"temperature": 22},
            {"threshold": 3},
        )
        assert result is None

    def test_categorical_conflict(self, resolver):
        result = resolver._detect_conflict(
            "light",
            {"state": "on"},
            {"state": "off"},
            {},
        )
        assert result is not None
        assert result["type"] == "categorical"

    def test_categorical_no_conflict_same(self, resolver):
        result = resolver._detect_conflict(
            "light",
            {"state": "on"},
            {"state": "on"},
            {},
        )
        assert result is None


class TestCheckConflict:
    """Tests fuer check_conflict()."""

    @pytest.mark.asyncio
    async def test_no_conflict_same_person(self, resolver):
        resolver.record_command("Max", "set_light", {"state": "on"})
        result = await resolver.check_conflict("Max", "set_light", {"state": "off"})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_conflict_disabled(self, resolver):
        resolver.enabled = False
        result = await resolver.check_conflict("Max", "set_light", {"state": "on"})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_conflict_unknown_function(self, resolver):
        resolver.record_command("Anna", "play_sound", {"sound": "chime"})
        result = await resolver.check_conflict("Max", "play_sound", {"sound": "ding"})
        # play_sound ist keine ueberwachte Domain
        assert result is None


class TestDomainLabel:
    """Tests fuer _domain_label()."""

    def test_light(self, resolver):
        assert resolver._domain_label("light") == "das Licht"

    def test_media(self, resolver):
        assert resolver._domain_label("media") == "die Musik"

    def test_cover(self, resolver):
        assert resolver._domain_label("cover") == "die Rolladen"

    def test_unknown(self, resolver):
        assert resolver._domain_label("xyz") == "xyz"


class TestDescribeAction:
    """Tests fuer _describe_action()."""

    def test_climate_temperature(self, resolver):
        result = resolver._describe_action("climate", {"temperature": 22})
        assert "22" in result
        assert "°C" in result

    def test_light_state(self, resolver):
        result = resolver._describe_action("light", {"state": "on"})
        assert "on" in result

    def test_light_brightness(self, resolver):
        result = resolver._describe_action("light", {"brightness": 80})
        assert "80" in result

    def test_cover_position(self, resolver):
        result = resolver._describe_action("cover", {"position": 50})
        assert "50" in result

    def test_unknown_domain(self, resolver):
        result = resolver._describe_action("xyz", {})
        assert "entsprechend" in result


class TestHealthStatus:
    """Tests fuer health_status()."""

    def test_enabled_status(self, resolver):
        status = resolver.health_status()
        assert isinstance(status, str)

    def test_disabled_status(self, resolver):
        resolver.enabled = False
        status = resolver.health_status()
        assert "disabled" in status.lower()

    def test_status_includes_person_count(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 50})
        resolver.record_command("Anna", "set_light", {"brightness": 80})
        status = resolver.health_status()
        assert "2 personen" in status


class TestCheckConflictWithResolution:
    """Tests fuer check_conflict() mit tatsaechlicher Konfliktloesung."""

    @pytest.fixture
    def resolver_with_trust(self):
        """Resolver mit konfigurierten Trust-Levels."""
        autonomy = MagicMock()
        # Max hat Trust 5 (Owner), Anna hat Trust 3 (Resident)
        autonomy.get_trust_level = MagicMock(
            side_effect=lambda p: {"max": 5, "anna": 3}.get(p, 1)
        )
        ollama = AsyncMock()
        r = ConflictResolver(autonomy, ollama)
        r.enabled = True
        return r

    @pytest.mark.asyncio
    async def test_trust_priority_higher_wins(self, resolver_with_trust):
        """Hoehere Trust-Stufe gewinnt bei trust_priority Strategie."""
        resolver = resolver_with_trust
        # Override domain config to use trust_priority for light
        resolver._domain_configs["light"] = {"threshold": 10, "strategy": "trust_priority"}
        resolver.record_command("Anna", "set_light", {"brightness": 10}, "wohnzimmer")
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_light", {"brightness": 90}, "wohnzimmer"
            )
        assert result is not None
        assert result["conflict"] is True
        assert result["winner"] == "max"
        assert result["loser"] == "anna"
        assert result["strategy"] == "trust_priority"
        assert result["domain"] == "light"

    @pytest.mark.asyncio
    async def test_same_trust_falls_to_average(self, resolver):
        """Gleicher Trust-Level bei numerischem Konflikt → average Strategie."""
        # Beide haben Trust 3 (Default im resolver Fixture)
        resolver.record_command("Anna", "set_climate", {"temperature": 19}, "wohnzimmer")
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_climate", {"temperature": 25}, "wohnzimmer"
            )
        assert result is not None
        assert result["action"] == "use_compromise"
        assert result["compromise_value"] == 22.0  # (19+25)/2

    @pytest.mark.asyncio
    async def test_conflict_different_rooms_no_conflict(self, resolver):
        """Befehle in verschiedenen Raeumen loesen keinen Konflikt aus."""
        resolver.record_command("Anna", "set_climate", {"temperature": 19}, "schlafzimmer")
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_climate", {"temperature": 25}, "wohnzimmer"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_conflict_cooldown(self, resolver):
        """Konflikte im Cooldown werden uebersprungen."""
        resolver.record_command("Anna", "set_climate", {"temperature": 19}, "wohnzimmer")
        # Cooldown fuer diesen Domain:Raum setzen
        resolver._last_resolutions["climate:wohnzimmer"] = time.time()
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_climate", {"temperature": 25}, "wohnzimmer"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_command_no_conflict(self, resolver):
        """Befehle ausserhalb des Zeitfensters loesen keinen Konflikt aus."""
        resolver.record_command("Anna", "set_climate", {"temperature": 19}, "wohnzimmer")
        # Timestamp auf weit in der Vergangenheit setzen
        resolver._recent_commands["anna"][0]["timestamp"] = time.time() - 600
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_climate", {"temperature": 25}, "wohnzimmer"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_categorical_conflict_media(self, resolver):
        """Kategorischer Konflikt bei Media (play vs stop)."""
        resolver.record_command("Anna", "play_media", {"action": "play"}, "wohnzimmer")
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "play_media", {"action": "stop"}, "wohnzimmer"
            )
        assert result is not None
        assert result["conflict_detail"]["type"] == "categorical"

    @pytest.mark.asyncio
    async def test_no_conflict_empty_person(self, resolver):
        """Leerer Personenname liefert keinen Konflikt."""
        result = await resolver.check_conflict("", "set_light", {"brightness": 50})
        assert result is None

    @pytest.mark.asyncio
    async def test_conflict_history_appended(self, resolver):
        """Konflikt wird in History gespeichert."""
        resolver.record_command("Anna", "set_climate", {"temperature": 19}, "wohnzimmer")
        assert len(resolver._conflict_history) == 0
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_climate", {"temperature": 25}, "wohnzimmer"
            )
        assert result is not None
        assert len(resolver._conflict_history) == 1


class TestResolveByRoomPresence:
    """Tests fuer _resolve_by_room_presence()."""

    def test_no_room_returns_none(self, resolver):
        result = resolver._resolve_by_room_presence("max", "anna", None)
        assert result is None

    def test_person_a_in_room_wins(self, resolver):
        """Person A hat zuletzt im Raum agiert → gewinnt."""
        resolver._recent_commands["max"] = [
            {"room": "wohnzimmer", "timestamp": time.time(), "args": {}},
        ]
        resolver._recent_commands["anna"] = [
            {"room": "kueche", "timestamp": time.time(), "args": {}},
        ]
        result = resolver._resolve_by_room_presence("max", "anna", "wohnzimmer")
        assert result == "max"

    def test_person_b_in_room_wins(self, resolver):
        """Person B hat zuletzt im Raum agiert → gewinnt."""
        resolver._recent_commands["max"] = [
            {"room": "kueche", "timestamp": time.time(), "args": {}},
        ]
        resolver._recent_commands["anna"] = [
            {"room": "wohnzimmer", "timestamp": time.time(), "args": {}},
        ]
        result = resolver._resolve_by_room_presence("max", "anna", "wohnzimmer")
        assert result == "anna"

    def test_both_in_room_more_recent_wins(self, resolver):
        """Beide im Raum, aktuellerer Befehl gewinnt."""
        resolver._recent_commands["max"] = [
            {"room": "wohnzimmer", "timestamp": time.time() - 60, "args": {}},
        ]
        resolver._recent_commands["anna"] = [
            {"room": "wohnzimmer", "timestamp": time.time(), "args": {}},
        ]
        result = resolver._resolve_by_room_presence("max", "anna", "wohnzimmer")
        assert result == "anna"

    def test_neither_in_room_returns_none(self, resolver):
        """Keine Person im Raum → kein Entscheid."""
        resolver._recent_commands["max"] = [
            {"room": "kueche", "timestamp": time.time(), "args": {}},
        ]
        resolver._recent_commands["anna"] = [
            {"room": "bad", "timestamp": time.time(), "args": {}},
        ]
        result = resolver._resolve_by_room_presence("max", "anna", "wohnzimmer")
        assert result is None

    def test_no_commands_returns_none(self, resolver):
        """Keine aufgezeichneten Befehle → kein Entscheid."""
        result = resolver._resolve_by_room_presence("max", "anna", "wohnzimmer")
        assert result is None


class TestPredictConflict:
    """Tests fuer predict_logical_conflict() — logische Konflikterkennung."""

    @pytest.mark.asyncio
    async def test_window_open_climate_conflict(self, resolver):
        """Heizung setzen bei offenem Fenster → Warnung."""
        ha_states = [
            {"entity_id": "binary_sensor.wohnzimmer_window", "state": "on"},
        ]
        result = await resolver.predict_logical_conflict("set_climate", {}, ha_states)
        assert result is not None
        assert result["type"] == "window_open"
        assert result["severity"] == "info"

    @pytest.mark.asyncio
    async def test_no_window_open_no_conflict(self, resolver):
        """Heizung setzen bei geschlossenem Fenster → kein Konflikt."""
        ha_states = [
            {"entity_id": "binary_sensor.wohnzimmer_window", "state": "off"},
        ]
        result = await resolver.predict_logical_conflict("set_climate", {}, ha_states)
        assert result is None

    @pytest.mark.asyncio
    async def test_solar_producing_cover_conflict(self, resolver):
        """Rolllaeden schliessen bei Solar-Produktion → Warnung."""
        ha_states = [
            {"entity_id": "sensor.solar_power", "state": "500"},
        ]
        result = await resolver.predict_logical_conflict("set_cover", {}, ha_states)
        assert result is not None
        assert result["type"] == "solar_producing"

    @pytest.mark.asyncio
    async def test_solar_low_no_conflict(self, resolver):
        """Rolllaeden schliessen bei niedriger Solar-Produktion → kein Konflikt."""
        ha_states = [
            {"entity_id": "sensor.solar_power", "state": "50"},
        ]
        result = await resolver.predict_logical_conflict("set_cover", {}, ha_states)
        assert result is None

    @pytest.mark.asyncio
    async def test_high_lux_light_conflict(self, resolver):
        """Licht einschalten bei hoher Lux → Warnung."""
        ha_states = [
            {"entity_id": "sensor.outdoor_lux", "state": "800"},
        ]
        result = await resolver.predict_logical_conflict("set_light", {}, ha_states)
        assert result is not None
        assert result["type"] == "high_lux"
        assert result["severity"] == "low"

    @pytest.mark.asyncio
    async def test_nobody_home_climate_conflict(self, resolver):
        """Heizung bei leerem Haus → Warnung."""
        ha_states = [
            {"entity_id": "person.max", "state": "not_home"},
            {"entity_id": "person.anna", "state": "not_home"},
        ]
        result = await resolver.predict_logical_conflict("set_climate", {}, ha_states)
        # window_open rule matches first if no window sensor, but nobody_home should match
        # With these states there is no window sensor "on", so window_open does not match.
        # nobody_home should match.
        assert result is not None
        assert result["type"] == "nobody_home"

    @pytest.mark.asyncio
    async def test_someone_home_no_nobody_conflict(self, resolver):
        """Mindestens eine Person zuhause → kein 'nobody_home' Konflikt."""
        ha_states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "person.anna", "state": "not_home"},
        ]
        result = await resolver.predict_logical_conflict("set_climate", {}, ha_states)
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, resolver):
        """Deaktivierter Resolver liefert keine Prediction."""
        resolver.enabled = False
        ha_states = [
            {"entity_id": "binary_sensor.wohnzimmer_window", "state": "on"},
        ]
        result = await resolver.predict_logical_conflict("set_climate", {}, ha_states)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_states_no_conflict(self, resolver):
        """Leere HA-States loesen keinen Konflikt aus."""
        result = await resolver.predict_logical_conflict("set_climate", {}, [])
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_action_no_conflict(self, resolver):
        """Unbekannte Aktion loest keinen Konflikt aus."""
        ha_states = [
            {"entity_id": "binary_sensor.wohnzimmer_window", "state": "on"},
        ]
        result = await resolver.predict_logical_conflict("unknown_action", {}, ha_states)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_numeric_solar_value_ignored(self, resolver):
        """Nicht-numerischer Solar-Wert wird uebersprungen."""
        ha_states = [
            {"entity_id": "sensor.solar_power", "state": "unavailable"},
        ]
        result = await resolver.predict_logical_conflict("set_cover", {}, ha_states)
        assert result is None


class TestInitialize:
    """Tests fuer initialize() mit Redis."""

    @pytest.mark.asyncio
    async def test_initialize_with_redis_loads_history(self, resolver):
        """Initialisierung laedt History aus Redis."""
        redis = AsyncMock()
        history = [{"conflict": True, "domain": "climate"}]
        redis.get = AsyncMock(return_value=json.dumps(history))
        await resolver.initialize(redis)
        assert resolver._redis is redis
        assert len(resolver._conflict_history) == 1

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, resolver):
        """Initialisierung ohne Redis funktioniert."""
        await resolver.initialize(None)
        assert resolver._redis is None
        assert resolver._conflict_history == []

    @pytest.mark.asyncio
    async def test_initialize_redis_error_handled(self, resolver):
        """Redis-Fehler bei Initialisierung wird abgefangen."""
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        await resolver.initialize(redis)
        # Sollte nicht abstuerzen, History bleibt leer
        assert resolver._conflict_history == []

    @pytest.mark.asyncio
    async def test_initialize_truncates_large_history(self, resolver):
        """Zu grosse History wird auf max_history begrenzt."""
        redis = AsyncMock()
        history = [{"conflict": True, "i": i} for i in range(100)]
        redis.get = AsyncMock(return_value=json.dumps(history))
        await resolver.initialize(redis)
        assert len(resolver._conflict_history) <= resolver._max_history


class TestSaveHistory:
    """Tests fuer _save_history()."""

    @pytest.mark.asyncio
    async def test_save_history_to_redis(self, resolver):
        """History wird nach Redis geschrieben."""
        redis = AsyncMock()
        resolver._redis = redis
        resolver._conflict_history = [{"conflict": True}]
        await resolver._save_history()
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == "mha:conflicts:history"

    @pytest.mark.asyncio
    async def test_save_history_no_redis(self, resolver):
        """Ohne Redis wird nichts gespeichert (kein Fehler)."""
        resolver._redis = None
        resolver._conflict_history = [{"conflict": True}]
        await resolver._save_history()  # Sollte nicht abstuerzen

    @pytest.mark.asyncio
    async def test_save_history_redis_error_handled(self, resolver):
        """Redis-Fehler beim Speichern wird abgefangen."""
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        resolver._redis = redis
        resolver._conflict_history = [{"conflict": True}]
        await resolver._save_history()  # Sollte nicht abstuerzen


class TestGetInfo:
    """Tests fuer get_info() und get_recent_conflicts()."""

    def test_get_info_structure(self, resolver):
        """get_info liefert erwartete Schluessel."""
        info = resolver.get_info()
        assert "enabled" in info
        assert "conflict_window_seconds" in info
        assert "mediation_enabled" in info
        assert "active_commands" in info
        assert "total_conflicts" in info
        assert "recent_conflicts" in info
        assert "monitored_domains" in info

    def test_get_info_monitored_domains(self, resolver):
        """Ueberwachte Domains enthalten die erwarteten Werte."""
        info = resolver.get_info()
        assert "climate" in info["monitored_domains"]
        assert "light" in info["monitored_domains"]

    def test_get_recent_conflicts_empty(self, resolver):
        """Leere History liefert leere Liste."""
        assert resolver.get_recent_conflicts() == []

    def test_get_recent_conflicts_respects_limit(self, resolver):
        """Limit begrenzt die Ergebnisse."""
        resolver._conflict_history = [{"i": i} for i in range(20)]
        result = resolver.get_recent_conflicts(limit=5)
        assert len(result) == 5

    def test_get_active_commands(self, resolver):
        """get_active_commands liefert Anzahl pro Person."""
        resolver.record_command("Max", "set_light", {"brightness": 50})
        resolver.record_command("Max", "set_light", {"brightness": 80})
        resolver.record_command("Anna", "set_light", {"brightness": 30})
        active = resolver.get_active_commands()
        assert active["max"] == 2
        assert active["anna"] == 1


class TestCleanupOldCommands:
    """Tests fuer _cleanup_old_commands()."""

    def test_removes_expired_commands(self, resolver):
        """Abgelaufene Befehle werden entfernt."""
        resolver._conflict_window = 60
        resolver._recent_commands["max"] = [
            {"timestamp": time.time() - 120, "person": "max",
             "function": "set_light", "args": {}, "room": None,
             "datetime": ""},
            {"timestamp": time.time(), "person": "max",
             "function": "set_light", "args": {}, "room": None,
             "datetime": ""},
        ]
        resolver._cleanup_old_commands()
        assert len(resolver._recent_commands["max"]) == 1

    def test_removes_empty_person_entries(self, resolver):
        """Personen ohne aktive Befehle werden entfernt."""
        resolver._conflict_window = 60
        resolver._recent_commands["max"] = [
            {"timestamp": time.time() - 120, "person": "max",
             "function": "set_light", "args": {}, "room": None,
             "datetime": ""},
        ]
        resolver._cleanup_old_commands()
        assert "max" not in resolver._recent_commands


class TestDetectConflictEdgeCases:
    """Erweiterte Tests fuer _detect_conflict() Edge Cases."""

    def test_unknown_domain_returns_none(self, resolver):
        """Unbekannte Domain liefert keinen Konflikt."""
        result = resolver._detect_conflict(
            "unknown_domain", {"key": 1}, {"key": 2}, {}
        )
        assert result is None

    def test_numeric_missing_values_checks_also_check(self, resolver):
        """Bei fehlenden numerischen Werten wird also_check geprueft."""
        # Light hat also_check: ["state"]
        result = resolver._detect_conflict(
            "light",
            {"state": "on"},  # Kein brightness
            {"state": "off"},  # Kein brightness
            {},
        )
        assert result is not None
        assert result["type"] == "categorical"
        assert result["key"] == "state"

    def test_numeric_non_numeric_values_returns_none(self, resolver):
        """Nicht-numerische Werte bei numerischem Vergleich → None."""
        result = resolver._detect_conflict(
            "climate",
            {"temperature": "warm"},
            {"temperature": "kalt"},
            {"threshold": 2},
        )
        assert result is None

    def test_numeric_exact_threshold_no_conflict(self, resolver):
        """Exakt am Threshold → kein Konflikt (>= noetig)."""
        # Default threshold is 2 (from domain_cfg.get("threshold", 2))
        result = resolver._detect_conflict(
            "climate",
            {"temperature": 20},
            {"temperature": 22},
            {"threshold": 3},
        )
        # diff=2 < threshold=3 → kein Konflikt
        assert result is None

    def test_numeric_at_threshold_is_conflict(self, resolver):
        """Differenz genau gleich Threshold → Konflikt (>= check)."""
        result = resolver._detect_conflict(
            "climate",
            {"temperature": 20},
            {"temperature": 23},
            {"threshold": 3},
        )
        # diff=3 >= threshold=3 → Konflikt
        assert result is not None

    def test_cover_numeric_conflict(self, resolver):
        """Numerischer Konflikt bei Rolllaeden (Position)."""
        result = resolver._detect_conflict(
            "cover",
            {"position": 100},
            {"position": 0},
            {"threshold": 2},
        )
        assert result is not None
        assert result["type"] == "numeric"
        assert result["difference"] == 100

    def test_media_categorical_same_action_no_conflict(self, resolver):
        """Gleiche Media-Aktion → kein Konflikt."""
        result = resolver._detect_conflict(
            "media",
            {"action": "play"},
            {"action": "play"},
            {},
        )
        assert result is None

    def test_categorical_none_values_no_conflict(self, resolver):
        """None-Werte bei kategorischem Vergleich → kein Konflikt."""
        result = resolver._detect_conflict(
            "media",
            {"action": None},
            {"action": "play"},
            {},
        )
        assert result is None


class TestWarnBeforeAction:
    """Tests fuer _warn_before_action()."""

    def test_formats_warning(self, resolver):
        result = resolver._warn_before_action("Fenster offen")
        assert "Fenster offen" in result
        assert "Sir" in result
        assert "fortfahren" in result

    def test_returns_string(self, resolver):
        result = resolver._warn_before_action("")
        assert isinstance(result, str)


class TestGetConflictParameters:
    """Tests fuer get_conflict_parameters() und Modul-Konstanten."""

    def test_all_domains_present(self):
        params = get_conflict_parameters()
        assert "climate" in params
        assert "light" in params
        assert "media" in params
        assert "cover" in params

    def test_climate_has_numeric_type(self):
        params = get_conflict_parameters()
        assert params["climate"]["type"] == "numeric"

    def test_media_has_categorical_type(self):
        params = get_conflict_parameters()
        assert params["media"]["type"] == "categorical"

    def test_function_domain_map_covers_monitored_functions(self):
        assert "set_climate" in FUNCTION_DOMAIN_MAP
        assert "set_light" in FUNCTION_DOMAIN_MAP
        assert "play_media" in FUNCTION_DOMAIN_MAP
        assert "set_cover" in FUNCTION_DOMAIN_MAP

    def test_logical_conflict_rules_non_empty(self):
        assert len(_LOGICAL_CONFLICT_RULES) >= 4
        for rule in _LOGICAL_CONFLICT_RULES:
            assert "action" in rule
            assert "context" in rule
            assert "warning" in rule
            assert "severity" in rule


class TestMedation:
    """Tests fuer _mediate() LLM-basierte Mediation."""

    @pytest.mark.asyncio
    async def test_mediate_returns_llm_response(self, resolver):
        """Erfolgreiche LLM-Mediation liefert Text."""
        resolver.ollama.chat = AsyncMock(return_value={
            "message": {"content": "Max bekommt 22 Grad, Anna eine Decke."}
        })
        result = await resolver._mediate(
            person_a="max", trust_a="Owner",
            person_b="anna", trust_b="Resident",
            conflict_detail={
                "type": "numeric", "key": "temperature",
                "value_existing": 19, "value_new": 25, "unit": "°C",
            },
            domain="climate", room="wohnzimmer",
        )
        assert "Max" in result or "22" in result or "Decke" in result

    @pytest.mark.asyncio
    async def test_mediate_llm_failure_returns_fallback(self, resolver):
        """LLM-Fehler liefert Fallback-Text."""
        resolver.ollama.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        result = await resolver._mediate(
            person_a="max", trust_a="Owner",
            person_b="anna", trust_b="Resident",
            conflict_detail={
                "type": "categorical", "key": "action",
                "value_existing": "play", "value_new": "stop",
            },
            domain="media", room="wohnzimmer",
        )
        assert "Max" in result
        assert "Anna" in result

    @pytest.mark.asyncio
    async def test_mediate_empty_response_returns_fallback(self, resolver):
        """Leere LLM-Antwort liefert Fallback-Text."""
        resolver.ollama.chat = AsyncMock(return_value={
            "message": {"content": ""}
        })
        result = await resolver._mediate(
            person_a="max", trust_a="Owner",
            person_b="anna", trust_b="Resident",
            conflict_detail={
                "type": "numeric", "key": "temperature",
                "value_existing": 20, "value_new": 24, "unit": "°C",
            },
            domain="climate", room=None,
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestCompromiseValidation:
    """Tests fuer Kompromiss-Wert-Validierung und Safe-Limits."""

    @pytest.mark.asyncio
    async def test_compromise_clamped_to_safe_limits(self, resolver):
        """Kompromiss ausserhalb der Safe-Limits wird geclampt."""
        resolver._safe_limits = {
            "climate": {"temperature": (18.0, 24.0)},
        }
        resolver.record_command(
            "Anna", "set_climate", {"temperature": 10}, "wohnzimmer"
        )
        mock_main = MagicMock()
        mock_main.brain = None
        with patch.dict("sys.modules", {"assistant.main": mock_main}):
            result = await resolver.check_conflict(
                "Max", "set_climate", {"temperature": 14}, "wohnzimmer"
            )
        # (10+14)/2 = 12 → geclampt auf 18.0 (Minimum)
        assert result is not None
        if result.get("compromise_value") is not None:
            assert result["compromise_value"] >= 18.0
