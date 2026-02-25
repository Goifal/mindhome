"""
Tests fuer Visitor Manager — Besucher-Management, History, Tuer-Workflows.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.visitor_manager import (
    VisitorManager,
    _DEFAULT_HISTORY_MAX,
    _DEFAULT_PENDING_TTL,
    _DEFAULT_RING_TTL,
    _KEY_EXPECTED,
    _KEY_HISTORY,
    _KEY_KNOWN,
    _KEY_LAST_RING,
    _KEY_STATS,
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ha_mock():
    """Home Assistant Client Mock."""
    mock = AsyncMock()
    mock.call_service = AsyncMock(return_value=True)
    mock.get_states = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def camera_mock():
    """CameraManager Mock."""
    mock = AsyncMock()
    mock.describe_doorbell = AsyncMock(return_value="Person vor der Tuer")
    return mock


@pytest.fixture
def redis_mock():
    """Redis Mock mit Standard-Returns."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.setex = AsyncMock()
    mock.delete = AsyncMock()
    mock.hset = AsyncMock()
    mock.hget = AsyncMock(return_value=None)
    mock.hgetall = AsyncMock(return_value={})
    mock.hdel = AsyncMock()
    mock.hincrby = AsyncMock()
    mock.lrange = AsyncMock(return_value=[])

    pipe_mock = MagicMock()
    pipe_mock.lpush = MagicMock()
    pipe_mock.ltrim = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe_mock)
    mock._pipeline = pipe_mock

    return mock


@pytest.fixture
def executor_mock():
    """FunctionExecutor Mock."""
    mock = AsyncMock()
    mock.execute = AsyncMock(return_value={"success": True, "message": "Tuer haustuer: unlock"})
    return mock


@pytest.fixture
def vm(ha_mock, camera_mock, redis_mock, executor_mock):
    """VisitorManager mit gemockten Dependencies."""
    v = VisitorManager(ha_mock, camera_mock)
    v.redis = redis_mock
    v.executor = executor_mock
    v.enabled = True
    return v


# =====================================================================
# Bekannte Besucher verwalten
# =====================================================================


class TestAddKnownVisitor:
    """Tests fuer add_known_visitor()."""

    @pytest.mark.asyncio
    async def test_add_new_visitor(self, vm, redis_mock):
        """Neuer Besucher wird angelegt."""
        result = await vm.add_known_visitor("mama", "Mama", relationship="Familie")
        assert result["success"] is True
        assert "hinzugefuegt" in result["message"]
        redis_mock.hset.assert_called_once()
        # Pruefen dass Profil korrekt gespeichert wurde
        call_args = redis_mock.hset.call_args
        assert call_args[0][0] == _KEY_KNOWN
        assert call_args[0][1] == "mama"
        stored = json.loads(call_args[0][2])
        assert stored["name"] == "Mama"
        assert stored["relationship"] == "Familie"
        assert stored["visit_count"] == 0

    @pytest.mark.asyncio
    async def test_update_existing_visitor(self, vm, redis_mock):
        """Bestehender Besucher wird aktualisiert, visit_count bleibt."""
        existing = json.dumps({
            "name": "Mama",
            "relationship": "Familie",
            "notes": "",
            "visit_count": 5,
            "last_visit": "2026-02-20T10:00:00+00:00",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        redis_mock.hget = AsyncMock(return_value=existing)

        result = await vm.add_known_visitor("mama", "Mama", notes="Mag Kaffee")
        assert result["success"] is True
        assert "aktualisiert" in result["message"]
        stored = json.loads(redis_mock.hset.call_args[0][2])
        assert stored["visit_count"] == 5
        assert stored["notes"] == "Mag Kaffee"

    @pytest.mark.asyncio
    async def test_add_without_redis(self, vm):
        """Ohne Redis -> Fehler."""
        vm.redis = None
        result = await vm.add_known_visitor("mama", "Mama")
        assert result["success"] is False


class TestRemoveKnownVisitor:
    """Tests fuer remove_known_visitor()."""

    @pytest.mark.asyncio
    async def test_remove_existing(self, vm, redis_mock):
        """Bestehender Besucher wird entfernt."""
        existing = json.dumps({"name": "Mama", "visit_count": 0})
        redis_mock.hget = AsyncMock(return_value=existing)

        result = await vm.remove_known_visitor("mama")
        assert result["success"] is True
        redis_mock.hdel.assert_called_once_with(_KEY_KNOWN, "mama")

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, vm, redis_mock):
        """Unbekannter Besucher -> Fehler."""
        redis_mock.hget = AsyncMock(return_value=None)
        result = await vm.remove_known_visitor("unbekannt")
        assert result["success"] is False


class TestListKnownVisitors:
    """Tests fuer list_known_visitors()."""

    @pytest.mark.asyncio
    async def test_list_empty(self, vm, redis_mock):
        """Leere Liste."""
        redis_mock.hgetall = AsyncMock(return_value={})
        result = await vm.list_known_visitors()
        assert result["success"] is True
        assert result["count"] == 0
        assert result["visitors"] == []

    @pytest.mark.asyncio
    async def test_list_multiple(self, vm, redis_mock):
        """Mehrere Besucher werden zurueckgegeben."""
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({"name": "Mama", "last_visit": "2026-02-20T10:00:00+00:00"}),
            "papa": json.dumps({"name": "Papa", "last_visit": "2026-02-19T10:00:00+00:00"}),
        })
        result = await vm.list_known_visitors()
        assert result["success"] is True
        assert result["count"] == 2
        # Sortiert nach last_visit (neueste zuerst)
        assert result["visitors"][0]["name"] == "Mama"
        assert result["visitors"][1]["name"] == "Papa"

    @pytest.mark.asyncio
    async def test_list_with_bytes_keys(self, vm, redis_mock):
        """Redis gibt bytes zurueck — werden korrekt decoded."""
        redis_mock.hgetall = AsyncMock(return_value={
            b"mama": json.dumps({"name": "Mama", "last_visit": None}).encode(),
        })
        result = await vm.list_known_visitors()
        assert result["success"] is True
        assert result["count"] == 1
        assert result["visitors"][0]["name"] == "Mama"
        assert result["visitors"][0]["id"] == "mama"

    @pytest.mark.asyncio
    async def test_list_skips_invalid_json(self, vm, redis_mock):
        """Ungueltige JSON-Eintraege werden uebersprungen."""
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({"name": "Mama", "last_visit": None}),
            "broken": "kein json{{{",
        })
        result = await vm.list_known_visitors()
        assert result["count"] == 1


# =====================================================================
# Erwartete Besucher
# =====================================================================


class TestExpectVisitor:
    """Tests fuer expect_visitor()."""

    @pytest.mark.asyncio
    async def test_expect_new_visitor(self, vm, redis_mock):
        """Neuer erwarteter Besucher wird angelegt."""
        result = await vm.expect_visitor("mama", name="Mama", expected_time="15:00")
        assert result["success"] is True
        assert "erwartet" in result["message"]
        assert "15:00" in result["message"]
        # Sowohl in expected als auch in known gespeichert
        assert redis_mock.hset.call_count == 2  # known + expected

    @pytest.mark.asyncio
    async def test_expect_without_name(self, vm, redis_mock):
        """Besucher erwarten ohne Name — kein known-Eintrag."""
        result = await vm.expect_visitor("lieferant")
        assert result["success"] is True
        # Nur expected gespeichert, kein known (da name leer)
        assert redis_mock.hset.call_count == 1

    @pytest.mark.asyncio
    async def test_expect_with_auto_unlock(self, vm, redis_mock):
        """Erwarteter Besucher mit auto_unlock."""
        result = await vm.expect_visitor("mama", name="Mama", auto_unlock=True)
        assert result["success"] is True
        assert "automatisch geoeffnet" in result["message"]

    @pytest.mark.asyncio
    async def test_cancel_expected(self, vm, redis_mock):
        """Erwartung aufheben."""
        result = await vm.cancel_expected("mama")
        assert result["success"] is True
        redis_mock.hdel.assert_called_once_with(_KEY_EXPECTED, "mama")

    @pytest.mark.asyncio
    async def test_get_expected_visitors(self, vm, redis_mock):
        """Erwartete Besucher abrufen."""
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({"name": "Mama", "expected_time": "15:00", "auto_unlock": False}),
        })
        result = await vm.get_expected_visitors()
        assert len(result) == 1
        assert result[0]["name"] == "Mama"
        assert result[0]["id"] == "mama"


# =====================================================================
# Doorbell Handling
# =====================================================================


class TestHandleDoorbell:
    """Tests fuer handle_doorbell()."""

    @pytest.mark.asyncio
    async def test_basic_doorbell(self, vm, redis_mock):
        """Einfaches Klingel-Event wird verarbeitet."""
        result = await vm.handle_doorbell(camera_description="Person in blauem Mantel")
        assert result["handled"] is True
        assert result["camera_description"] == "Person in blauem Mantel"
        assert result["auto_unlocked"] is False
        # Ring-Info in Redis gespeichert
        redis_mock.setex.assert_called_once()
        key = redis_mock.setex.call_args[0][0]
        assert key == _KEY_LAST_RING

    @pytest.mark.asyncio
    async def test_doorbell_cooldown(self, vm):
        """Zweites Klingeln innerhalb des Cooldowns wird ignoriert."""
        vm._last_ring_time = time.time()  # Gerade erst geklingelt
        result = await vm.handle_doorbell("Person")
        assert result["handled"] is False
        assert result["reason"] == "cooldown"

    @pytest.mark.asyncio
    async def test_doorbell_after_cooldown(self, vm, redis_mock):
        """Nach Ablauf des Cooldowns wird verarbeitet."""
        vm._last_ring_time = time.time() - 60  # Vor 60 Sekunden
        vm.ring_cooldown_seconds = 30
        result = await vm.handle_doorbell("Person")
        assert result["handled"] is True

    @pytest.mark.asyncio
    async def test_doorbell_with_expected_visitor(self, vm, redis_mock):
        """Klingel mit erwartetem Besucher."""
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({
                "name": "Mama",
                "expected_time": "15:00",
                "auto_unlock": False,
                "notes": "",
            }),
        })
        result = await vm.handle_doorbell("Aeltere Dame vor der Tuer")
        assert result["handled"] is True
        assert result["expected"] is True
        assert result["auto_unlocked"] is False

    @pytest.mark.asyncio
    async def test_doorbell_auto_unlock(self, vm, redis_mock, executor_mock):
        """Erwarteter Besucher mit auto_unlock -> Tuer oeffnet automatisch."""
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({
                "id": "mama",
                "name": "Mama",
                "expected_time": "15:00",
                "auto_unlock": True,
                "notes": "",
            }),
        })
        result = await vm.handle_doorbell("Aeltere Dame")
        assert result["handled"] is True
        assert result["auto_unlocked"] is True
        executor_mock.execute.assert_called_once_with(
            "lock_door", {"door": "haustuer", "action": "unlock"}
        )

    @pytest.mark.asyncio
    async def test_doorbell_auto_unlock_failure(self, vm, redis_mock, executor_mock):
        """Auto-Unlock fehlgeschlagen -> auto_unlocked=False."""
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({
                "id": "mama",
                "name": "Mama",
                "auto_unlock": True,
            }),
        })
        executor_mock.execute = AsyncMock(return_value={"success": False, "message": "Schloss nicht gefunden"})
        result = await vm.handle_doorbell("Person")
        assert result["handled"] is True
        assert result["auto_unlocked"] is False

    @pytest.mark.asyncio
    async def test_doorbell_without_camera(self, vm, redis_mock):
        """Klingel ohne Kamera-Beschreibung."""
        result = await vm.handle_doorbell("")
        assert result["handled"] is True
        assert result["camera_description"] == ""


# =====================================================================
# Grant Entry ("Lass ihn rein")
# =====================================================================


class TestGrantEntry:
    """Tests fuer grant_entry()."""

    @pytest.mark.asyncio
    async def test_grant_entry_success(self, vm, redis_mock, executor_mock):
        """Tuer wird nach Klingel-Event geoeffnet."""
        ring_info = json.dumps({
            "timestamp": "2026-02-25T10:00:00+00:00",
            "camera_description": "Paketbote vor der Tuer",
            "expected": False,
        })
        redis_mock.get = AsyncMock(return_value=ring_info)

        result = await vm.grant_entry()
        assert result["success"] is True
        assert "offen" in result["message"]
        assert "Paketbote" in result["message"]
        executor_mock.execute.assert_called_once_with(
            "lock_door", {"door": "haustuer", "action": "unlock"}
        )
        # Ring-Kontext wird geloescht
        redis_mock.delete.assert_called_once_with(_KEY_LAST_RING)

    @pytest.mark.asyncio
    async def test_grant_entry_no_ring(self, vm, redis_mock):
        """Ohne vorheriges Klingel-Event -> Fehler."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await vm.grant_entry()
        assert result["success"] is False
        assert "Kein aktuelles Klingel-Event" in result["message"]

    @pytest.mark.asyncio
    async def test_grant_entry_custom_door(self, vm, redis_mock, executor_mock):
        """Andere Tuer als Haustuer."""
        ring_info = json.dumps({"timestamp": "now", "camera_description": ""})
        redis_mock.get = AsyncMock(return_value=ring_info)

        result = await vm.grant_entry(door="garage")
        assert result["success"] is True
        executor_mock.execute.assert_called_once_with(
            "lock_door", {"door": "garage", "action": "unlock"}
        )

    @pytest.mark.asyncio
    async def test_grant_entry_unlock_fails(self, vm, redis_mock, executor_mock):
        """Tuer-Entriegelung fehlgeschlagen."""
        ring_info = json.dumps({"timestamp": "now", "camera_description": ""})
        redis_mock.get = AsyncMock(return_value=ring_info)
        executor_mock.execute = AsyncMock(return_value={"success": False})

        result = await vm.grant_entry()
        assert result["success"] is False
        assert "konnte nicht entriegelt" in result["message"]


# =====================================================================
# Visit History
# =====================================================================


class TestVisitHistory:
    """Tests fuer _record_visit() und get_visit_history()."""

    @pytest.mark.asyncio
    async def test_record_visit(self, vm, redis_mock):
        """Besuch wird in History geschrieben."""
        await vm._record_visit("mama", "Mama", camera_description="Aeltere Dame")
        pipe = redis_mock._pipeline
        pipe.lpush.assert_called_once()
        pipe.ltrim.assert_called_once()
        # Stats aktualisiert
        redis_mock.hincrby.assert_called_once_with(_KEY_STATS, "total_visits", 1)

    @pytest.mark.asyncio
    async def test_record_visit_updates_known_visitor(self, vm, redis_mock):
        """Besuch aktualisiert visit_count des bekannten Besuchers."""
        existing = json.dumps({"name": "Mama", "visit_count": 3, "last_visit": None})
        redis_mock.hget = AsyncMock(return_value=existing)

        await vm._record_visit("mama", "Mama")
        # hset wurde aufgerufen um Profil zu aktualisieren
        stored = json.loads(redis_mock.hset.call_args[0][2])
        assert stored["visit_count"] == 4
        assert stored["last_visit"] is not None

    @pytest.mark.asyncio
    async def test_record_visit_unknown_person(self, vm, redis_mock):
        """Besuch von unbekannter Person — kein known-Update."""
        await vm._record_visit("unknown", "Besucher")
        # hget nicht aufgerufen (unknown wird uebersprungen)
        redis_mock.hget.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_history_empty(self, vm, redis_mock):
        """Leere History."""
        redis_mock.lrange = AsyncMock(return_value=[])
        result = await vm.get_visit_history()
        assert result["success"] is True
        assert result["count"] == 0
        assert result["visits"] == []

    @pytest.mark.asyncio
    async def test_get_history_with_entries(self, vm, redis_mock):
        """History mit Eintraegen."""
        visits = [
            json.dumps({"person_id": "mama", "name": "Mama", "timestamp": "2026-02-25T10:00:00+00:00"}),
            json.dumps({"person_id": "papa", "name": "Papa", "timestamp": "2026-02-24T10:00:00+00:00"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=visits)
        result = await vm.get_visit_history(limit=10)
        assert result["count"] == 2
        assert result["visits"][0]["name"] == "Mama"

    @pytest.mark.asyncio
    async def test_get_history_limit_capped(self, vm, redis_mock):
        """Limit wird auf history_max begrenzt."""
        redis_mock.lrange = AsyncMock(return_value=[])
        await vm.get_visit_history(limit=9999)
        # lrange wurde mit history_max aufgerufen
        call_args = redis_mock.lrange.call_args[0]
        assert call_args[2] <= vm.history_max - 1


# =====================================================================
# Status
# =====================================================================


class TestGetStatus:
    """Tests fuer get_status()."""

    @pytest.mark.asyncio
    async def test_basic_status(self, vm, redis_mock):
        """Status ohne Daten."""
        redis_mock.hgetall = AsyncMock(return_value={})
        redis_mock.get = AsyncMock(return_value=None)

        result = await vm.get_status()
        assert result["enabled"] is True
        assert result["expected_visitors"] == []
        assert result["known_visitor_count"] == 0
        assert result["last_ring"] is None
        assert result["total_visits"] == 0

    @pytest.mark.asyncio
    async def test_status_with_last_ring(self, vm, redis_mock):
        """Status mit aktuellem Klingel-Event."""
        ring_info = json.dumps({"timestamp": "2026-02-25T10:00:00+00:00", "camera_description": "Person"})
        # Erster hgetall fuer expected, zweiter fuer known, dritter fuer stats
        redis_mock.hgetall = AsyncMock(side_effect=[
            {},  # expected
            {},  # known
            {},  # stats
        ])
        redis_mock.get = AsyncMock(return_value=ring_info)

        result = await vm.get_status()
        assert result["last_ring"] is not None
        assert result["last_ring"]["camera_description"] == "Person"


# =====================================================================
# Interne Hilfsmethoden
# =====================================================================


class TestUnlockDoor:
    """Tests fuer _unlock_door()."""

    @pytest.mark.asyncio
    async def test_unlock_success(self, vm, executor_mock):
        """Tuer wird erfolgreich entriegelt."""
        result = await vm._unlock_door("haustuer")
        assert result is True
        executor_mock.execute.assert_called_once_with(
            "lock_door", {"door": "haustuer", "action": "unlock"}
        )

    @pytest.mark.asyncio
    async def test_unlock_failure(self, vm, executor_mock):
        """Entriegelung fehlgeschlagen."""
        executor_mock.execute = AsyncMock(return_value={"success": False})
        result = await vm._unlock_door("haustuer")
        assert result is False

    @pytest.mark.asyncio
    async def test_unlock_without_executor(self, vm):
        """Ohne Executor -> False."""
        vm.executor = None
        result = await vm._unlock_door("haustuer")
        assert result is False

    @pytest.mark.asyncio
    async def test_unlock_exception(self, vm, executor_mock):
        """Exception bei Entriegelung -> False."""
        executor_mock.execute = AsyncMock(side_effect=Exception("Connection lost"))
        result = await vm._unlock_door("haustuer")
        assert result is False


# =====================================================================
# Konfiguration & Initialisierung
# =====================================================================


class TestInitialization:
    """Tests fuer Initialisierung und Config."""

    @pytest.mark.asyncio
    async def test_initialize(self, ha_mock, camera_mock):
        """Initialisierung setzt Redis."""
        vm = VisitorManager(ha_mock, camera_mock)
        redis = AsyncMock()
        await vm.initialize(redis)
        assert vm.redis is redis

    def test_default_config(self, ha_mock, camera_mock):
        """Standard-Konfiguration."""
        with patch("assistant.visitor_manager.yaml_config", {"visitor_management": {}}):
            vm = VisitorManager(ha_mock, camera_mock)
            assert vm.enabled is True
            assert vm.auto_guest_mode is False
            assert vm.ring_cooldown_seconds == 30
            assert vm.history_max == _DEFAULT_HISTORY_MAX

    def test_custom_config(self, ha_mock, camera_mock):
        """Benutzerdefinierte Konfiguration."""
        cfg = {
            "visitor_management": {
                "enabled": False,
                "auto_guest_mode": True,
                "ring_cooldown_seconds": 60,
                "history_max": 200,
            }
        }
        with patch("assistant.visitor_manager.yaml_config", cfg):
            vm = VisitorManager(ha_mock, camera_mock)
            assert vm.enabled is False
            assert vm.auto_guest_mode is True
            assert vm.ring_cooldown_seconds == 60
            assert vm.history_max == 200

    def test_set_notify_callback(self, vm):
        """Callback wird gesetzt."""
        cb = AsyncMock()
        vm.set_notify_callback(cb)
        assert vm._notify_callback is cb

    def test_set_executor(self, vm):
        """Executor wird gesetzt."""
        ex = AsyncMock()
        vm.set_executor(ex)
        assert vm.executor is ex


# =====================================================================
# Redis Key Constants
# =====================================================================


class TestConstants:
    """Tests fuer Konstanten."""

    def test_key_prefixes(self):
        assert _KEY_KNOWN.startswith("mha:visitor")
        assert _KEY_HISTORY.startswith("mha:visitor")
        assert _KEY_LAST_RING.startswith("mha:visitor")
        assert _KEY_EXPECTED.startswith("mha:visitor")
        assert _KEY_STATS.startswith("mha:visitor")

    def test_defaults(self):
        assert _DEFAULT_HISTORY_MAX >= 50
        assert _DEFAULT_RING_TTL >= 60
        assert _DEFAULT_PENDING_TTL >= 60
