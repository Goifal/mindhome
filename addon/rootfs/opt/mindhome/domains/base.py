"""
MindHome - Domain Plugin Base Class v0.6.0-phase3
All domain modules inherit from this base class.
Phase 3: Context access, plugin modes (suggest/auto), settings, conflict awareness.
"""

from abc import ABC, abstractmethod
from datetime import datetime
import logging
import json

logger = logging.getLogger("mindhome.domains")


class DomainPlugin(ABC):
    """Base class for all MindHome domain plugins."""

    DOMAIN_NAME = ""
    HA_DOMAINS = []
    DEVICE_CLASSES = []
    DEFAULT_SETTINGS = {}

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.logger = logging.getLogger(f"mindhome.domains.{self.DOMAIN_NAME}")
        self._is_running = False
        self._settings_cache = None
        self._context_cache = None
        self._context_cache_time = 0

    def start(self):
        self._is_running = True
        self.logger.info(f"Domain plugin '{self.DOMAIN_NAME}' started")
        self._load_settings()
        self.on_start()

    def stop(self):
        self._is_running = False
        self.logger.info(f"Domain plugin '{self.DOMAIN_NAME}' stopped")
        self.on_stop()

    # === Abstract ===

    @abstractmethod
    def on_start(self):
        pass

    @abstractmethod
    def on_stop(self):
        pass

    @abstractmethod
    def on_state_change(self, entity_id, old_state, new_state):
        pass

    @abstractmethod
    def get_trackable_features(self):
        pass

    @abstractmethod
    def get_current_status(self, room_id=None):
        pass

    # === Phase 3: Intelligent actions ===

    def evaluate(self, context):
        """Evaluate context, return suggested actions. Override in subclass."""
        return []

    def get_plugin_actions(self):
        """Return configurable actions for this plugin."""
        return []

    # === Phase 3: Context Access ===

    def get_context(self):
        """Get current context (cached 30s)."""
        import time as _time
        now = _time.time()
        if self._context_cache and (now - self._context_cache_time) < 30:
            return self._context_cache
        try:
            from ml.pattern_engine import ContextBuilder
            builder = ContextBuilder(self.ha)
            self._context_cache = builder.build()
            self._context_cache_time = now
        except Exception:
            self._context_cache = {
                "anyone_home": self.ha.is_anyone_home(),
                "is_dark": False, "is_rainy": self.ha.is_raining(),
            }
            self._context_cache_time = now
        return self._context_cache

    def is_anyone_home(self):
        return self.get_context().get("anyone_home", False)

    def is_quiet_time(self):
        try:
            from ml.automation_engine import QuietHoursManager
            from models import get_engine
            mgr = QuietHoursManager(get_engine())
            return mgr.is_quiet_time()
        except Exception:
            return False

    def get_sun_state(self):
        return self.ha.get_sun_state()

    def get_weather(self):
        return self.ha.get_weather()

    def get_current_day_phase(self):
        return self.get_context().get("day_phase", "unknown")

    def get_current_presence_mode(self):
        return self.get_context().get("presence_mode", "unknown")

    # === Phase 3: Plugin Mode & Settings ===

    def _load_settings(self):
        self._settings_cache = dict(self.DEFAULT_SETTINGS)
        try:
            from models import PluginSetting
            session = self.get_session()
            for s in session.query(PluginSetting).filter_by(plugin_name=self.DOMAIN_NAME).all():
                self._settings_cache[s.setting_key] = s.setting_value
            session.close()
        except Exception as e:
            self.logger.warning(f"Settings load error: {e}")

    def get_setting(self, key, default=None):
        if self._settings_cache is None:
            self._load_settings()
        val = self._settings_cache.get(key, default)
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                pass
        return val

    def set_setting(self, key, value):
        try:
            from models import PluginSetting
            session = self.get_session()
            existing = session.query(PluginSetting).filter_by(
                plugin_name=self.DOMAIN_NAME, setting_key=key
            ).first()
            str_value = json.dumps(value) if not isinstance(value, str) else value
            if existing:
                existing.setting_value = str_value
            else:
                session.add(PluginSetting(
                    plugin_name=self.DOMAIN_NAME, setting_key=key, setting_value=str_value,
                ))
            session.commit()
            if self._settings_cache:
                self._settings_cache[key] = str_value
            session.close()
        except Exception as e:
            self.logger.warning(f"Setting save error: {e}")

    def is_enabled(self):
        return self.get_setting("enabled", "true") == "true"

    def get_mode(self):
        return self.get_setting("mode", "suggest")

    def is_auto_mode(self):
        return self.get_mode() == "auto"

    def execute_or_suggest(self, actions):
        """Execute (auto) or suggest (suggest mode) actions."""
        if not actions:
            return []
        results = []
        mode = self.get_mode()
        for action in actions:
            entity_id = action.get("entity_id", "")
            service = action.get("service", "")
            data = action.get("data", {})
            reason_de = action.get("reason_de", "Plugin-Aktion")
            reason_en = action.get("reason_en", "Plugin action")

            if mode == "auto" and self.is_enabled():
                try:
                    domain = entity_id.split(".")[0]
                    self.ha.call_service(domain, service, data, entity_id=entity_id)
                    self.log_action("plugin_auto",
                        {"entity_id": entity_id, "service": service, "data": data},
                        reason=reason_de)
                    results.append({"status": "executed", "entity_id": entity_id})
                    self.logger.info(f"Auto: {entity_id} -> {service} ({reason_de})")
                except Exception as e:
                    results.append({"status": "error", "entity_id": entity_id, "error": str(e)})
            else:
                self.log_action("plugin_suggest",
                    {"entity_id": entity_id, "service": service, "data": data,
                     "reason_de": reason_de, "reason_en": reason_en},
                    reason=f"Vorschlag: {reason_de}")
                results.append({"status": "suggested", "entity_id": entity_id})
                self.logger.info(f"Suggest: {entity_id} -> {service} ({reason_de})")
        return results

    # === Shared helpers ===

    def get_entities(self):
        entities = []
        for ha_domain in self.HA_DOMAINS:
            entities.extend(self.ha.get_entities_by_domain(ha_domain))
        return entities

    def get_entity_state(self, entity_id):
        return self.ha.get_state(entity_id)

    def call_service(self, domain, service, data=None, entity_id=None):
        return self.ha.call_service(domain, service, data, entity_id)

    def get_entity_history(self, entity_id, hours=24):
        from datetime import timedelta
        start = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        return self.ha.get_history(entity_id, start)

    def is_entity_tracked(self, entity_id):
        from models import Device
        session = self.get_session()
        try:
            return session.query(Device).filter_by(ha_entity_id=entity_id, is_tracked=True).first() is not None
        finally:
            session.close()

    def is_room_privacy_allowed(self, room_id, feature_key):
        from models import Room
        session = self.get_session()
        try:
            room = session.get(Room, room_id)
            if not room or not room.privacy_mode:
                return True
            return room.privacy_mode.get(feature_key, True)
        finally:
            session.close()

    def log_action(self, action_type, action_data, reason=None,
                   room_id=None, device_id=None, user_id=None, previous_state=None):
        from models import ActionLog, Domain
        session = self.get_session()
        try:
            domain = session.query(Domain).filter_by(name=self.DOMAIN_NAME).first()
            log = ActionLog(
                action_type=action_type, domain_id=domain.id if domain else None,
                room_id=room_id, device_id=device_id, user_id=user_id,
                action_data=action_data, reason=reason, previous_state=previous_state,
            )
            session.add(log)
            session.commit()
            return log.id
        finally:
            session.close()

    def send_notification(self, message, title=None, notification_type="info"):
        prefix = {"critical": "\u274c", "suggestion": "\U0001f4a1", "info": "\u2139\ufe0f"}.get(notification_type, "\u2139\ufe0f")
        full_title = f"{prefix} MindHome: {title}" if title else f"{prefix} MindHome"
        self.ha.send_notification(message, title=full_title)

    def get_room_devices(self, room_id):
        from models import Device, Domain
        session = self.get_session()
        try:
            domain = session.query(Domain).filter_by(name=self.DOMAIN_NAME).first()
            if not domain:
                return []
            return [{"id": d.id, "entity_id": d.ha_entity_id, "name": d.name}
                    for d in session.query(Device).filter_by(
                        room_id=room_id, domain_id=domain.id, is_tracked=True).all()]
        finally:
            session.close()
