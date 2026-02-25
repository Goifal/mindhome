"""
Visitor Manager - Besucher-Management fuer MindHome Jarvis.

Features:
- Bekannte Besucher-Datenbank in Redis
- Klingel-Event → Kamera → Beschreibung → Identifikation → Benachrichtigung
- "Lass ihn rein"-Workflow (Owner-Trust erforderlich)
- Besucher-History (letzte Besuche, Haeufigkeit)
- Erwartete Besucher (Kalender-Integration)
- Automatischer Gaeste-Modus bei Besucher-Ankunft
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Redis Key Prefixes
_KEY_PREFIX = "mha:visitor"
_KEY_KNOWN = f"{_KEY_PREFIX}:known"               # Hash: person_id -> JSON(profile)
_KEY_HISTORY = f"{_KEY_PREFIX}:history"            # List: letzte Besuche (max 100)
_KEY_LAST_RING = f"{_KEY_PREFIX}:last_ring"        # String: Letzte Klingel-Info (TTL 10min)
_KEY_EXPECTED = f"{_KEY_PREFIX}:expected"           # Hash: person_id -> JSON(expected_info)
_KEY_PENDING = f"{_KEY_PREFIX}:pending_entry"       # String: Pending "lass rein" (TTL 5min)
_KEY_STATS = f"{_KEY_PREFIX}:stats"                # Hash: Statistiken

# Defaults
_DEFAULT_HISTORY_MAX = 100
_DEFAULT_RING_TTL = 600          # 10 Minuten
_DEFAULT_PENDING_TTL = 300       # 5 Minuten


class VisitorManager:
    """Verwaltet Besucher-Erkennung, -History und Tuer-Workflows."""

    def __init__(self, ha_client, camera_manager):
        self.ha = ha_client
        self.camera = camera_manager
        self.redis = None
        self._notify_callback = None
        self.executor = None

        # Config
        cfg = yaml_config.get("visitor_management", {})
        self.enabled = cfg.get("enabled", True)
        self.auto_guest_mode = cfg.get("auto_guest_mode", False)
        self.ring_cooldown_seconds = cfg.get("ring_cooldown_seconds", 30)
        self.history_max = cfg.get("history_max", _DEFAULT_HISTORY_MAX)
        self._last_ring_time = 0.0

    async def initialize(self, redis_client):
        """Initialisiert Redis-Verbindung."""
        self.redis = redis_client
        logger.info("VisitorManager initialisiert (enabled=%s)", self.enabled)

    def set_notify_callback(self, callback):
        """Setzt Callback fuer proaktive Benachrichtigungen."""
        self._notify_callback = callback

    def set_executor(self, executor):
        """Setzt FunctionExecutor fuer Tuer-Aktionen."""
        self.executor = executor

    # ------------------------------------------------------------------
    # Bekannte Besucher verwalten
    # ------------------------------------------------------------------

    async def add_known_visitor(self, person_id: str, name: str,
                                relationship: str = "",
                                notes: str = "") -> dict:
        """Fuegt einen bekannten Besucher hinzu oder aktualisiert ihn.

        Args:
            person_id: Eindeutige ID (z.B. "mama", "handwerker_mueller")
            name: Anzeigename ("Mama", "Herr Mueller")
            relationship: Beziehung ("Familie", "Freund", "Handwerker")
            notes: Zusaetzliche Notizen

        Returns:
            Dict mit success und message
        """
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        profile = {
            "name": name,
            "relationship": relationship,
            "notes": notes,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "visit_count": 0,
            "last_visit": None,
        }

        # Bestehenden Besucher aktualisieren (visit_count beibehalten)
        existing = await self._get_known_visitor(person_id)
        if existing:
            profile["visit_count"] = existing.get("visit_count", 0)
            profile["last_visit"] = existing.get("last_visit")
            profile["created_at"] = existing.get("created_at", profile["created_at"])

        await self.redis.hset(_KEY_KNOWN, person_id, json.dumps(profile))
        action = "aktualisiert" if existing else "hinzugefuegt"
        return {"success": True, "message": f"Besucher '{name}' {action}."}

    async def remove_known_visitor(self, person_id: str) -> dict:
        """Entfernt einen bekannten Besucher."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        existing = await self._get_known_visitor(person_id)
        if not existing:
            return {"success": False, "message": f"Besucher '{person_id}' nicht gefunden."}

        await self.redis.hdel(_KEY_KNOWN, person_id)
        return {"success": True, "message": f"Besucher '{existing['name']}' entfernt."}

    async def list_known_visitors(self) -> dict:
        """Listet alle bekannten Besucher auf."""
        if not self.redis:
            return {"success": False, "visitors": [], "message": "Redis nicht verfuegbar"}

        raw = await self.redis.hgetall(_KEY_KNOWN)
        visitors = []
        for pid, data in raw.items():
            try:
                key = pid.decode() if isinstance(pid, bytes) else pid
                val = data.decode() if isinstance(data, bytes) else data
                profile = json.loads(val)
                profile["id"] = key
                visitors.append(profile)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Nach letztem Besuch sortieren (neueste zuerst)
        visitors.sort(
            key=lambda v: v.get("last_visit") or "",
            reverse=True,
        )
        return {"success": True, "visitors": visitors, "count": len(visitors)}

    async def _get_known_visitor(self, person_id: str) -> Optional[dict]:
        """Holt ein bekanntes Besucher-Profil."""
        if not self.redis:
            return None
        raw = await self.redis.hget(_KEY_KNOWN, person_id)
        if not raw:
            return None
        try:
            val = raw.decode() if isinstance(raw, bytes) else raw
            return json.loads(val)
        except (json.JSONDecodeError, AttributeError):
            return None

    # ------------------------------------------------------------------
    # Erwartete Besucher
    # ------------------------------------------------------------------

    async def expect_visitor(self, person_id: str, name: str = "",
                             expected_time: str = "",
                             auto_unlock: bool = False,
                             notes: str = "") -> dict:
        """Markiert einen Besucher als erwartet.

        Args:
            person_id: ID des Besuchers (wird ggf. zu known hinzugefuegt)
            name: Name (falls neuer Besucher)
            expected_time: Erwartete Ankunftszeit (z.B. "15:00", "nachmittags")
            auto_unlock: Automatisch Tuer oeffnen bei Klingel
            notes: Zusaetzliche Info

        Returns:
            Dict mit success und message
        """
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        # Besucher ggf. als known anlegen
        if name:
            existing = await self._get_known_visitor(person_id)
            if not existing:
                await self.add_known_visitor(person_id, name)

        info = {
            "name": name or person_id,
            "expected_time": expected_time,
            "auto_unlock": auto_unlock,
            "notes": notes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.hset(_KEY_EXPECTED, person_id, json.dumps(info))
        # TTL auf den ganzen Hash ist nicht ideal — einzelne Eintraege verfallen nicht.
        # Aber erwartete Besucher werden manuell oder taeglich bereinigt.

        msg = f"Besucher '{info['name']}' wird erwartet"
        if expected_time:
            msg += f" um {expected_time}"
        msg += "."
        if auto_unlock:
            msg += " Tuer wird automatisch geoeffnet."
        return {"success": True, "message": msg}

    async def cancel_expected(self, person_id: str) -> dict:
        """Entfernt einen erwarteten Besucher."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}
        await self.redis.hdel(_KEY_EXPECTED, person_id)
        return {"success": True, "message": f"Erwartung fuer '{person_id}' aufgehoben."}

    async def get_expected_visitors(self) -> list[dict]:
        """Gibt alle erwarteten Besucher zurueck."""
        if not self.redis:
            return []
        raw = await self.redis.hgetall(_KEY_EXPECTED)
        result = []
        for pid, data in raw.items():
            try:
                key = pid.decode() if isinstance(pid, bytes) else pid
                val = data.decode() if isinstance(data, bytes) else data
                info = json.loads(val)
                info["id"] = key
                result.append(info)
            except (json.JSONDecodeError, AttributeError):
                continue
        return result

    async def _is_visitor_expected(self, person_id: str = "") -> Optional[dict]:
        """Prueft ob ein bestimmter oder irgendein Besucher erwartet wird."""
        if not self.redis:
            return None
        if person_id:
            raw = await self.redis.hget(_KEY_EXPECTED, person_id)
            if raw:
                val = raw.decode() if isinstance(raw, bytes) else raw
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return None
        return None

    # ------------------------------------------------------------------
    # Klingel-Event Verarbeitung
    # ------------------------------------------------------------------

    async def handle_doorbell(self, camera_description: str = "") -> dict:
        """Verarbeitet ein Klingel-Event mit Besucher-Kontext.

        Wird von ProactiveManager aufgerufen wenn die Klingel laeutet.

        Args:
            camera_description: Beschreibung der Tuerkamera (vom Vision-LLM)

        Returns:
            Dict mit Besucher-Info, Empfehlung und ggf. auto-unlock Status
        """
        now = time.time()

        # Cooldown pruefen (verhindert Doppel-Klingeln)
        if now - self._last_ring_time < self.ring_cooldown_seconds:
            return {"handled": False, "reason": "cooldown"}
        self._last_ring_time = now

        result = {
            "handled": True,
            "camera_description": camera_description,
            "expected": False,
            "known_visitor": None,
            "auto_unlocked": False,
            "recommendation": "",
        }

        # Erwartete Besucher pruefen
        expected = await self.get_expected_visitors()
        if expected:
            result["expected"] = True
            result["expected_visitors"] = expected

            # Auto-Unlock wenn ein erwarteter Besucher auto_unlock=True hat
            for ev in expected:
                if ev.get("auto_unlock"):
                    unlock_result = await self._auto_unlock_door()
                    result["auto_unlocked"] = unlock_result
                    if unlock_result:
                        # Besuch protokollieren
                        await self._record_visit(
                            ev.get("id", ""),
                            ev.get("name", "Erwartet"),
                            camera_description,
                            auto_unlocked=True,
                        )
                        # Erwartung aufheben
                        await self.cancel_expected(ev.get("id", ""))
                    break

        # Letzte Klingel-Info in Redis speichern (fuer "lass rein" Kontext)
        ring_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "camera_description": camera_description,
            "expected": result["expected"],
        }
        if self.redis:
            await self.redis.setex(
                _KEY_LAST_RING,
                _DEFAULT_RING_TTL,
                json.dumps(ring_info),
            )

        # Empfehlung formulieren
        if result["auto_unlocked"]:
            result["recommendation"] = "Tuer wurde automatisch geoeffnet (erwarteter Besuch)."
        elif result["expected"]:
            names = [e.get("name", "?") for e in expected]
            result["recommendation"] = f"Erwarteter Besuch: {', '.join(names)}."
        else:
            result["recommendation"] = ""

        return result

    async def grant_entry(self, door: str = "haustuer") -> dict:
        """'Lass ihn/sie rein' — Tuer entriegeln nach Klingel-Event.

        Prueft ob kuerzlich geklingelt wurde (Kontext vorhanden).

        Args:
            door: Tuer die entriegelt werden soll

        Returns:
            Dict mit success und message
        """
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        # Pruefen ob kuerzlich geklingelt wurde
        ring_data = await self.redis.get(_KEY_LAST_RING)
        if not ring_data:
            return {
                "success": False,
                "message": "Kein aktuelles Klingel-Event. Niemand wartet an der Tuer.",
            }

        # Tuer entriegeln
        unlock_result = await self._unlock_door(door)
        if not unlock_result:
            return {"success": False, "message": f"Tuer '{door}' konnte nicht entriegelt werden."}

        # Ring-Kontext laden fuer History
        try:
            val = ring_data.decode() if isinstance(ring_data, bytes) else ring_data
            ring_info = json.loads(val)
        except (json.JSONDecodeError, AttributeError):
            ring_info = {}

        # Besuch protokollieren
        await self._record_visit(
            person_id="unknown",
            name="Besucher",
            camera_description=ring_info.get("camera_description", ""),
            auto_unlocked=False,
        )

        # Ring-Kontext loeschen
        await self.redis.delete(_KEY_LAST_RING)

        desc = ring_info.get("camera_description", "")
        msg = "Tuer ist offen."
        if desc:
            msg = f"Tuer ist offen. ({desc})"
        return {"success": True, "message": msg}

    # ------------------------------------------------------------------
    # Besucher-History
    # ------------------------------------------------------------------

    async def _record_visit(self, person_id: str, name: str,
                            camera_description: str = "",
                            auto_unlocked: bool = False):
        """Protokolliert einen Besuch in der History."""
        if not self.redis:
            return

        visit = {
            "person_id": person_id,
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "camera_description": camera_description[:200] if camera_description else "",
            "auto_unlocked": auto_unlocked,
        }

        # In History-Liste pushen (FIFO, max _DEFAULT_HISTORY_MAX)
        pipe = self.redis.pipeline()
        pipe.lpush(_KEY_HISTORY, json.dumps(visit))
        pipe.ltrim(_KEY_HISTORY, 0, self.history_max - 1)
        await pipe.execute()

        # Known Visitor aktualisieren (visit_count + last_visit)
        if person_id and person_id != "unknown":
            profile = await self._get_known_visitor(person_id)
            if profile:
                profile["visit_count"] = profile.get("visit_count", 0) + 1
                profile["last_visit"] = visit["timestamp"]
                await self.redis.hset(_KEY_KNOWN, person_id, json.dumps(profile))

        # Stats aktualisieren
        await self.redis.hincrby(_KEY_STATS, "total_visits", 1)

    async def get_visit_history(self, limit: int = 20) -> dict:
        """Gibt die letzten Besuche zurueck.

        Args:
            limit: Maximale Anzahl (default 20)

        Returns:
            Dict mit visits-Liste und count
        """
        if not self.redis:
            return {"success": False, "visits": [], "message": "Redis nicht verfuegbar"}

        limit = min(limit, self.history_max)
        raw_list = await self.redis.lrange(_KEY_HISTORY, 0, limit - 1)

        visits = []
        for raw in raw_list:
            try:
                val = raw.decode() if isinstance(raw, bytes) else raw
                visits.append(json.loads(val))
            except (json.JSONDecodeError, AttributeError):
                continue

        return {"success": True, "visits": visits, "count": len(visits)}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self) -> dict:
        """Gibt den aktuellen Besucher-Status zurueck."""
        expected = await self.get_expected_visitors()
        known = await self.list_known_visitors()

        # Letzte Klingel pruefen
        last_ring = None
        if self.redis:
            raw = await self.redis.get(_KEY_LAST_RING)
            if raw:
                try:
                    val = raw.decode() if isinstance(raw, bytes) else raw
                    last_ring = json.loads(val)
                except (json.JSONDecodeError, AttributeError):
                    pass

        # Stats
        stats = {}
        if self.redis:
            raw_stats = await self.redis.hgetall(_KEY_STATS)
            for k, v in raw_stats.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                stats[key] = val

        return {
            "enabled": self.enabled,
            "expected_visitors": expected,
            "known_visitor_count": known.get("count", 0),
            "last_ring": last_ring,
            "auto_guest_mode": self.auto_guest_mode,
            "total_visits": int(stats.get("total_visits", 0)),
        }

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    async def _auto_unlock_door(self) -> bool:
        """Entriegelt die Haustuer automatisch (fuer erwartete Besucher)."""
        return await self._unlock_door("haustuer")

    async def _unlock_door(self, door: str = "haustuer") -> bool:
        """Entriegelt eine Tuer via FunctionExecutor."""
        if not self.executor:
            logger.warning("VisitorManager: Kein Executor gesetzt, Tuer kann nicht entriegelt werden")
            return False
        try:
            result = await self.executor.execute("lock_door", {"door": door, "action": "unlock"})
            return result.get("success", False)
        except Exception as e:
            logger.error("VisitorManager: Tuer-Entriegelung fehlgeschlagen: %s", e)
            return False
