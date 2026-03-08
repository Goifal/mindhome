"""MindHome - Cover Domain Plugin (Phase 3)"""
from .base import DomainPlugin
from cover_helpers import (
    is_bed_occupied as _check_bed_occupied,
    is_garage_or_gate_by_entity_id,
    is_unsafe_device_class,
    is_unsafe_cover_type,
    UNSAFE_DEVICE_CLASSES as _UNSAFE_DEVICE_CLASSES,
    UNSAFE_COVER_TYPES as _UNSAFE_COVER_TYPES,
)


class CoverDomain(DomainPlugin):
    DOMAIN_NAME = "cover"
    HA_DOMAINS = ["cover"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "sun_elevation_threshold": "5",
    }

    def on_start(self):
        self.logger.info("Cover domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Cover {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "position", "label_de": "Position", "label_en": "Position"},
            {"key": "tilt", "label_de": "Neigung", "label_en": "Tilt"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        open_count = sum(1 for e in entities if e.get("state") == "open")
        return {"total": len(entities), "open": open_count, "closed": len(entities) - open_count}

    def get_plugin_actions(self):
        return [
            {"key": "sunset_close", "label_de": "Bei Sonnenuntergang schliessen", "label_en": "Close at sunset", "default": True},
            {"key": "sunrise_open", "label_de": "Bei Sonnenaufgang oeffnen", "label_en": "Open at sunrise", "default": True},
            {"key": "sun_shading", "label_de": "Beschattung bei Sonneneinstrahlung", "label_en": "Sun shading", "default": True},
        ]

    def evaluate(self, context):
        """Cover automation is handled by Assistant proactive engine.
        Domain plugin only reports status."""
        return []

    def _is_safe_for_automation(self, entity) -> bool:
        """Prueft ob ein Cover sicher automatisch gesteuert werden darf.

        Filtert Garagentore (device_class, entity_id, CoverConfig) und
        deaktivierte Covers heraus.
        """
        entity_id = entity.get("entity_id", "")
        attrs = entity.get("attributes", {})
        device_class = attrs.get("device_class", "")

        # 1. HA device_class (garage_door, gate, door)
        if is_unsafe_device_class(device_class):
            return False

        # 2. Entity-ID Heuristik (shared helper)
        if is_garage_or_gate_by_entity_id(entity_id):
            return False

        # 3. CoverConfig aus DB: cover_type + enabled
        try:
            from models import CoverConfig
            from db import get_db_session
            with get_db_session() as session:
                conf = session.query(CoverConfig).filter_by(entity_id=entity_id).first()
                if conf:
                    if is_unsafe_cover_type(conf.cover_type):
                        return False
                    if conf.enabled is not None and not conf.enabled:
                        return False
        except Exception:
            self.logger.warning("DB-Fehler bei Safety-Check fuer %s — blockiere sicherheitshalber", entity_id)
            return False  # Fail-safe: bei DB-Fehler nicht automatisieren

        return True

    def _is_bed_occupied(self) -> bool:
        """Prueft ob ein Bettbelegungssensor aktiv ist (jemand schlaeft).

        Fail-safe: bei Fehler True zurueckgeben (lieber nicht oeffnen).
        """
        try:
            states = self.ha.get_states() or []
            return _check_bed_occupied(states)
        except Exception:
            self.logger.warning("Bettbelegung konnte nicht geprueft werden — fail-safe: belegt")
            return True
