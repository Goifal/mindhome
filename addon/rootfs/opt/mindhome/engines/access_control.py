# MindHome - engines/access_control.py | see version.py for version info
"""
Access control and geo-fencing engines.
Features: #4 Zutrittskontrolle, #5 Geo-Fencing
"""

import logging
import json
import hashlib
import math
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("mindhome.engines.access_control")


class AccessControlManager:
    """Smart lock management, access codes, and access logging.

    Subscribes to state.changed events for lock.* entities.
    - Code management (permanent, temporary, one-time)
    - Lock/unlock single or all locks
    - Auto-lock after timeout
    - Jammed detection + notification
    - Unknown access detection → camera snapshot trigger
    """

    DEFAULT_CONFIG = {
        "auto_lock_enabled": True,
        "auto_lock_delay_min": 5,
        "jammed_notification": True,
        "unknown_access_notification": True,
        "unknown_access_snapshot": True,
        "person_match_window_min": 2,
        "notification_users": [],
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._auto_lock_timers = {}  # entity_id -> unlock_time

    def start(self):
        self._is_running = True
        self.event_bus.subscribe("state.changed", self._on_state_changed, priority=40)
        logger.info("AccessControlManager started")

    def stop(self):
        self._is_running = False
        self._auto_lock_timers.clear()
        logger.info("AccessControlManager stopped")

    # ── Config ──────────────────────────────────────────────

    def get_config(self):
        from helpers import get_setting
        config = dict(self.DEFAULT_CONFIG)
        stored = get_setting("phase5.access_config")
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting("phase5.access_config", json.dumps(config))
        return config

    # ── Lock Operations ─────────────────────────────────────

    def get_locks(self):
        """Get all configured lock entities with current status."""
        from models import FeatureEntityAssignment
        locks = []
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="access", role="lock", is_active=True
                ).order_by(FeatureEntityAssignment.sort_order).all()
                for a in assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    attrs = state.get("attributes", {}) if state else {}
                    locks.append({
                        "entity_id": a.entity_id,
                        "state": state.get("state", "unknown") if state else "unknown",
                        "name": attrs.get("friendly_name", a.entity_id),
                        "battery_level": attrs.get("battery_level"),
                    })
        except Exception as e:
            logger.error(f"Error getting locks: {e}")
        return locks

    def lock(self, entity_id):
        """Lock a single lock."""
        try:
            self.ha.call_service("lock", "lock", {"entity_id": entity_id})
            self._log_access(entity_id, "lock", "remote")
            return True
        except Exception as e:
            logger.error(f"Lock failed for {entity_id}: {e}")
            return False

    def unlock(self, entity_id):
        """Unlock a single lock."""
        try:
            self.ha.call_service("lock", "unlock", {"entity_id": entity_id})
            self._log_access(entity_id, "unlock", "remote")
            # Start auto-lock timer
            config = self.get_config()
            if config.get("auto_lock_enabled"):
                self._auto_lock_timers[entity_id] = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.error(f"Unlock failed for {entity_id}: {e}")
            return False

    def lock_all(self):
        """Lock all configured locks."""
        locks = self.get_locks()
        results = []
        for lock_info in locks:
            ok = self.lock(lock_info["entity_id"])
            results.append({"entity_id": lock_info["entity_id"], "success": ok})
        return results

    # ── Access Codes ────────────────────────────────────────

    def get_codes(self):
        """Get all access codes (without plaintext)."""
        from models import AccessCode, User
        codes = []
        try:
            with self.get_session() as session:
                for code in session.query(AccessCode).filter_by(is_active=True).all():
                    user = session.query(User).get(code.user_id) if code.user_id else None
                    codes.append({
                        "id": code.id,
                        "name": code.name,
                        "user_id": code.user_id,
                        "user_name": user.name if user else None,
                        "lock_entity_ids": code.lock_entity_ids or [],
                        "valid_from": code.valid_from.isoformat() if code.valid_from else None,
                        "valid_until": code.valid_until.isoformat() if code.valid_until else None,
                        "is_temporary": code.is_temporary,
                        "max_uses": code.max_uses,
                        "use_count": code.use_count,
                        "is_active": code.is_active,
                    })
        except Exception as e:
            logger.error(f"Error getting codes: {e}")
        return codes

    def create_code(self, name, code, user_id=None, lock_entity_ids=None,
                    valid_from=None, valid_until=None, is_temporary=False, max_uses=None):
        """Create a new access code (stored hashed)."""
        from models import AccessCode
        try:
            code_hash = hashlib.sha256(code.encode()).hexdigest()
            with self.get_session() as session:
                ac = AccessCode(
                    name=name,
                    code_hash=code_hash,
                    user_id=user_id,
                    lock_entity_ids=lock_entity_ids or [],
                    valid_from=valid_from,
                    valid_until=valid_until,
                    is_temporary=is_temporary,
                    max_uses=max_uses,
                    use_count=0,
                    is_active=True,
                )
                session.add(ac)
                session.flush()
                return ac.id
        except Exception as e:
            logger.error(f"Error creating code: {e}")
            return None

    def update_code(self, code_id, updates):
        """Update an access code."""
        from models import AccessCode
        try:
            with self.get_session() as session:
                ac = session.query(AccessCode).get(code_id)
                if not ac:
                    return False
                for key in ("name", "user_id", "lock_entity_ids", "valid_from",
                            "valid_until", "is_temporary", "max_uses", "is_active"):
                    if key in updates:
                        setattr(ac, key, updates[key])
                if "code" in updates:
                    ac.code_hash = hashlib.sha256(updates["code"].encode()).hexdigest()
                return True
        except Exception as e:
            logger.error(f"Error updating code: {e}")
            return False

    def delete_code(self, code_id):
        """Deactivate an access code."""
        from models import AccessCode
        try:
            with self.get_session() as session:
                ac = session.query(AccessCode).get(code_id)
                if ac:
                    ac.is_active = False
                    return True
        except Exception as e:
            logger.error(f"Error deleting code: {e}")
        return False

    # ── Access Log ──────────────────────────────────────────

    def get_log(self, limit=50, offset=0, entity_id=None):
        """Get access log entries (paginated)."""
        from models import AccessLog
        entries = []
        try:
            with self.get_session() as session:
                q = session.query(AccessLog).order_by(AccessLog.timestamp.desc())
                if entity_id:
                    q = q.filter_by(lock_entity_id=entity_id)
                for log in q.offset(offset).limit(limit).all():
                    entries.append({
                        "id": log.id,
                        "lock_entity_id": log.lock_entity_id,
                        "user_id": log.user_id,
                        "access_code_id": log.access_code_id,
                        "action": log.action,
                        "method": log.method,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    })
        except Exception as e:
            logger.error(f"Error getting access log: {e}")
        return entries

    # ── Auto-Lock Check ─────────────────────────────────────

    def check_auto_lock(self):
        """Check and execute auto-lock for unlocked locks past timeout."""
        if not self._is_running:
            return
        config = self.get_config()
        if not config.get("auto_lock_enabled"):
            return

        delay = timedelta(minutes=config.get("auto_lock_delay_min", 5))
        now = datetime.now(timezone.utc)
        expired = []

        for entity_id, unlock_time in list(self._auto_lock_timers.items()):
            if now - unlock_time >= delay:
                state = self.ha.get_state(entity_id) if self.ha else None
                if state and state.get("state") == "unlocked":
                    try:
                        self.ha.call_service("lock", "lock", {"entity_id": entity_id})
                        self._log_access(entity_id, "lock", "auto")
                        logger.info(f"Auto-locked {entity_id}")
                    except Exception as e:
                        logger.error(f"Auto-lock failed for {entity_id}: {e}")
                expired.append(entity_id)

        for eid in expired:
            self._auto_lock_timers.pop(eid, None)

    # ── Event Handler ───────────────────────────────────────

    def _on_state_changed(self, event):
        """Handle state changes for lock entities."""
        if not self._is_running:
            return
        from routes.security import is_phase5_feature_enabled
        if not is_phase5_feature_enabled("phase5.access_control"):
            return

        data = event if isinstance(event, dict) else (event.data if hasattr(event, 'data') else {})
        entity_id = data.get("entity_id", "")
        if not entity_id.startswith("lock."):
            return

        new_state = data.get("new_state") or {}
        old_state = data.get("old_state") or {}
        new_val = new_state.get("state", "") if isinstance(new_state, dict) else ""
        old_val = old_state.get("state", "") if isinstance(old_state, dict) else ""

        if new_val == old_val:
            return

        # Check if this entity is assigned to us
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                assigned = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="access", entity_id=entity_id, is_active=True
                ).first()
                if not assigned:
                    return
        except Exception:
            return

        config = self.get_config()

        if new_val == "locked":
            self._log_access(entity_id, "lock", "unknown")
            self.event_bus.publish("access.locked", {"entity_id": entity_id}, source="access_control")

        elif new_val == "unlocked":
            # Try to match to a person
            user_id = self._try_match_person(entity_id, config)
            method = "code" if user_id else "unknown"
            self._log_access(entity_id, "unlock", method, user_id=user_id)
            self.event_bus.publish("access.unlocked", {
                "entity_id": entity_id, "user_id": user_id
            }, source="access_control")

            # Unknown access → notification + snapshot
            if not user_id and config.get("unknown_access_notification"):
                self.event_bus.publish("access.unknown", {
                    "entity_id": entity_id
                }, source="access_control")

            # Start auto-lock timer
            if config.get("auto_lock_enabled"):
                self._auto_lock_timers[entity_id] = datetime.now(timezone.utc)

        elif new_val == "jammed":
            self._log_access(entity_id, "jammed", "auto")
            self.event_bus.publish("access.jammed", {"entity_id": entity_id}, source="access_control")
            if config.get("jammed_notification"):
                self._notify_jammed(entity_id)

    def _try_match_person(self, entity_id, config):
        """Try to match an unlock event to a person via recent arrival."""
        window = config.get("person_match_window_min", 2)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window)
        try:
            from models import PresenceLog
            with self.get_session() as session:
                recent = session.query(PresenceLog).filter(
                    PresenceLog.created_at >= cutoff,
                    PresenceLog.mode_name == "home",
                ).order_by(PresenceLog.created_at.desc()).first()
                if recent:
                    return recent.user_id
        except Exception:
            pass
        return None

    def _log_access(self, entity_id, action, method, user_id=None, code_id=None):
        """Write an entry to the access log."""
        try:
            from models import AccessLog
            with self.get_session() as session:
                session.add(AccessLog(
                    lock_entity_id=entity_id,
                    user_id=user_id,
                    access_code_id=code_id,
                    action=action,
                    method=method,
                ))
        except Exception as e:
            logger.error(f"Access log write error: {e}")

    def _notify_jammed(self, entity_id):
        """Send notification for jammed lock."""
        try:
            from models import SecurityEvent, SecurityEventType, SecuritySeverity
            with self.get_session() as session:
                session.add(SecurityEvent(
                    event_type=SecurityEventType.ACCESS_JAMMED,
                    severity=SecuritySeverity.CRITICAL,
                    message_de=f"Schloss blockiert: {entity_id}",
                    message_en=f"Lock jammed: {entity_id}",
                    context={"entity_id": entity_id},
                ))
        except Exception as e:
            logger.error(f"Jammed notification error: {e}")


# ==============================================================================
# Geo-Fencing
# ==============================================================================

class GeoFenceManager:
    """Location-based automation using device_tracker/person entities.

    - Zone management (home, custom zones)
    - Enter/leave detection with hysteresis
    - Presence mode integration
    - Privacy: no GPS coordinates stored, only zone events
    """

    DEFAULT_CONFIG = {
        "check_interval_sec": 60,
        "hysteresis_m": 50,
        "all_away_action": {"presence_mode": "away"},
        "first_home_action": {"presence_mode": "home"},
        "log_zone_events": True,
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._person_zones = {}  # person_entity_id -> last_zone_id (or None)
        self._all_away_published = False  # State guard to prevent repeated all_away events
        self._all_away_since = None  # timestamp when all-away first detected (for debounce)

    def start(self):
        self._is_running = True
        logger.info("GeoFenceManager started")

    def stop(self):
        self._is_running = False
        self._person_zones.clear()
        logger.info("GeoFenceManager stopped")

    # ── Config ──────────────────────────────────────────────

    def get_config(self):
        from helpers import get_setting
        config = dict(self.DEFAULT_CONFIG)
        stored = get_setting("phase5.geofence_config")
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting("phase5.geofence_config", json.dumps(config))
        return config

    # ── Zone CRUD ───────────────────────────────────────────

    def get_zones(self):
        """Get all geo-fence zones."""
        from models import GeoFence
        zones = []
        try:
            with self.get_session() as session:
                for z in session.query(GeoFence).filter_by(is_active=True).all():
                    zones.append({
                        "id": z.id,
                        "name": z.name,
                        "latitude": z.latitude,
                        "longitude": z.longitude,
                        "radius_m": z.radius_m,
                        "user_id": z.user_id,
                        "action_on_enter": z.action_on_enter or {},
                        "action_on_leave": z.action_on_leave or {},
                        "is_active": z.is_active,
                    })
        except Exception as e:
            logger.error(f"Error getting zones: {e}")
        return zones

    def create_zone(self, name, latitude, longitude, radius_m,
                    user_id=None, action_on_enter=None, action_on_leave=None):
        """Create a new geo-fence zone."""
        from models import GeoFence
        try:
            with self.get_session() as session:
                z = GeoFence(
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    radius_m=radius_m,
                    user_id=user_id,
                    action_on_enter=action_on_enter or {},
                    action_on_leave=action_on_leave or {},
                    is_active=True,
                )
                session.add(z)
                session.flush()
                return z.id
        except Exception as e:
            logger.error(f"Error creating zone: {e}")
            return None

    def update_zone(self, zone_id, updates):
        """Update a geo-fence zone."""
        from models import GeoFence
        try:
            with self.get_session() as session:
                z = session.query(GeoFence).get(zone_id)
                if not z:
                    return False
                for key in ("name", "latitude", "longitude", "radius_m",
                            "user_id", "action_on_enter", "action_on_leave", "is_active"):
                    if key in updates:
                        setattr(z, key, updates[key])
                return True
        except Exception as e:
            logger.error(f"Error updating zone: {e}")
            return False

    def delete_zone(self, zone_id):
        """Deactivate a geo-fence zone."""
        from models import GeoFence
        try:
            with self.get_session() as session:
                z = session.query(GeoFence).get(zone_id)
                if z:
                    z.is_active = False
                    return True
        except Exception as e:
            logger.error(f"Error deleting zone: {e}")
        return False

    # ── Status ──────────────────────────────────────────────

    def get_status(self):
        """Get current person locations relative to zones."""
        from models import FeatureEntityAssignment
        persons = []
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="geofence", role="person", is_active=True
                ).all()
                zones = self.get_zones()
                for a in assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    attrs = state.get("attributes", {}) if state else {}
                    lat = attrs.get("latitude")
                    lon = attrs.get("longitude")
                    current_zone = None
                    if lat is not None and lon is not None:
                        current_zone = self._find_zone(lat, lon, zones)
                    persons.append({
                        "entity_id": a.entity_id,
                        "name": attrs.get("friendly_name", a.entity_id),
                        "zone": current_zone,
                        "ha_state": state.get("state", "unknown") if state else "unknown",
                    })
        except Exception as e:
            logger.error(f"Error getting geofence status: {e}")
        return persons

    # ── Periodic Check ──────────────────────────────────────

    def check(self):
        """Periodic check: detect zone enter/leave events."""
        if not self._is_running:
            return
        from routes.security import is_phase5_feature_enabled
        if not is_phase5_feature_enabled("phase5.geo_fencing"):
            return

        from models import FeatureEntityAssignment
        config = self.get_config()
        zones = self.get_zones()
        hysteresis = config.get("hysteresis_m", 50)

        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="geofence", role="person", is_active=True
                ).all()

            for a in assignments:
                state = self.ha.get_state(a.entity_id) if self.ha else None
                if not state:
                    continue
                attrs = state.get("attributes", {})
                lat = attrs.get("latitude")
                lon = attrs.get("longitude")
                if lat is None or lon is None:
                    continue

                current_zone = self._find_zone(lat, lon, zones, hysteresis)
                prev_zone = self._person_zones.get(a.entity_id)

                if current_zone != prev_zone:
                    self._person_zones[a.entity_id] = current_zone
                    if prev_zone is not None:
                        self._on_zone_leave(a.entity_id, prev_zone, config)
                    if current_zone is not None:
                        self._on_zone_enter(a.entity_id, current_zone, config)

            # Check if all persons are away from "home" zone
            self._check_all_away(config, zones)

        except Exception as e:
            logger.error(f"Geofence check error: {e}")

    # ── Internal ────────────────────────────────────────────

    def _find_zone(self, lat, lon, zones, hysteresis=0):
        """Find which zone a coordinate is in (closest match within radius)."""
        for z in zones:
            dist = self._haversine(lat, lon, z["latitude"], z["longitude"])
            if dist <= z["radius_m"] + hysteresis:
                return z["id"]
        return None

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Calculate distance in meters between two GPS coordinates."""
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _on_zone_enter(self, entity_id, zone_id, config):
        """Handle zone enter event."""
        zones = {z["id"]: z for z in self.get_zones()}
        zone = zones.get(zone_id)
        if not zone:
            return
        logger.info(f"Geofence: {entity_id} entered zone '{zone['name']}'")
        self.event_bus.publish("geofence.enter", {
            "entity_id": entity_id,
            "zone_id": zone_id,
            "zone_name": zone["name"],
        }, source="geofence")
        # Execute zone enter actions
        actions = zone.get("action_on_enter", {})
        if actions.get("presence_mode"):
            self.event_bus.publish("presence.request_mode", {
                "mode": actions["presence_mode"],
                "source": "geofence",
            }, source="geofence")

    def _on_zone_leave(self, entity_id, zone_id, config):
        """Handle zone leave event."""
        zones = {z["id"]: z for z in self.get_zones()}
        zone = zones.get(zone_id)
        if not zone:
            return
        logger.info(f"Geofence: {entity_id} left zone '{zone['name']}'")
        self.event_bus.publish("geofence.leave", {
            "entity_id": entity_id,
            "zone_id": zone_id,
            "zone_name": zone["name"],
        }, source="geofence")
        actions = zone.get("action_on_leave", {})
        if actions.get("presence_mode"):
            self.event_bus.publish("presence.request_mode", {
                "mode": actions["presence_mode"],
                "source": "geofence",
            }, source="geofence")

    def _check_all_away(self, config, zones):
        """If all tracked persons are outside all zones → trigger all_away_action.
        Uses state guard to prevent repeated events every check cycle."""
        if not self._person_zones:
            return
        all_away = all(z is None for z in self._person_zones.values())
        if all_away and not self._all_away_published:
            from helpers import get_setting
            debounce_sec = int(get_setting("phase5.geofence.all_away_debounce_sec", "0") or "0")
            now = datetime.now(timezone.utc)
            if debounce_sec > 0:
                if self._all_away_since is None:
                    self._all_away_since = now
                    logger.debug(f"Geofence: all-away debounce started ({debounce_sec}s)")
                    return
                elapsed = (now - self._all_away_since).total_seconds()
                if elapsed < debounce_sec:
                    return
            self._all_away_published = True
            self._all_away_since = None
            action = config.get("all_away_action", {})
            if action.get("presence_mode"):
                self.event_bus.publish("presence.request_mode", {
                    "mode": action["presence_mode"],
                    "source": "geofence_all_away",
                }, source="geofence")
            logger.info("Geofence: all persons away")
        elif not all_away and self._all_away_published:
            # First person returned home
            self._all_away_published = False
            self._all_away_since = None
            action = config.get("first_home_action", {})
            if action.get("presence_mode"):
                self.event_bus.publish("presence.request_mode", {
                    "mode": action["presence_mode"],
                    "source": "geofence_first_home",
                }, source="geofence")
            logger.info("Geofence: first person returned home")
        elif not all_away:
            self._all_away_published = False
            self._all_away_since = None
