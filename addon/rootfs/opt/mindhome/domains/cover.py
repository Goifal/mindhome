"""MindHome - Cover Domain Plugin (Phase 3)"""
import re

from .base import DomainPlugin

# Unsichere Cover-Typen: Garagentore, Tore, Tueren
_UNSAFE_DEVICE_CLASSES = {"garage_door", "gate", "door"}
_UNSAFE_COVER_TYPES = {"garage_door", "gate", "door"}


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
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()
        actions = []
        entities = self.get_entities()
        sun = self.get_sun_state()
        threshold = float(self.get_setting("sun_elevation_threshold", 5))

        if not sun:
            return []

        # Unsichere Covers (Garagentore, deaktivierte) herausfiltern
        safe_entities = [e for e in entities if self._is_safe_for_automation(e)]

        elevation = sun.get("elevation", 0)

        # Sunset -> close covers
        if self.get_setting("sunset_close", True):
            if elevation < -2 and ctx.get("anyone_home"):
                for e in safe_entities:
                    if e.get("state") == "open":
                        name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                        actions.append({
                            "entity_id": e["entity_id"], "service": "close_cover",
                            "reason_de": f"Sonnenuntergang: {name} schliessen",
                            "reason_en": f"Sunset: close {name}",
                        })

        # Sunrise -> open covers (only if no one is in bed)
        if self.get_setting("sunrise_open", True):
            if elevation > threshold and sun.get("rising"):
                # Bettbelegung pruefen: Nicht oeffnen wenn jemand schlaeft
                bed_occupied = self._is_bed_occupied()
                if bed_occupied:
                    self.logger.info("Sunrise: Rolladen NICHT geoeffnet — Bett belegt")
                else:
                    for e in safe_entities:
                        if e.get("state") == "closed":
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "open_cover",
                                "reason_de": f"Sonnenaufgang: {name} oeffnen",
                                "reason_en": f"Sunrise: open {name}",
                            })

        # High sun + warm -> partial shading
        if self.get_setting("sun_shading", True):
            if elevation > 40:
                weather = self.get_weather()
                if weather and weather.get("temperature", 0) > 25:
                    for e in safe_entities:
                        if e.get("state") == "open":
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "set_cover_position",
                                "data": {"position": 50},
                                "reason_de": f"Beschattung: {name} halb schliessen (Sonne hoch + warm)",
                                "reason_en": f"Shading: half-close {name} (sun high + warm)",
                            })

        return self.execute_or_suggest(actions)

    def _is_safe_for_automation(self, entity) -> bool:
        """Prueft ob ein Cover sicher automatisch gesteuert werden darf.

        Filtert Garagentore (device_class, entity_id, CoverConfig) und
        deaktivierte Covers heraus.
        """
        entity_id = entity.get("entity_id", "")
        attrs = entity.get("attributes", {})
        device_class = attrs.get("device_class", "")

        # 1. HA device_class (garage_door, gate, door)
        if device_class in _UNSAFE_DEVICE_CLASSES:
            return False

        # 2. Entity-ID Heuristik — Word-Boundary fuer 'tor'
        eid_lower = entity_id.lower()
        if "garage" in eid_lower or "gate" in eid_lower:
            return False
        if re.search(r'(?:^|[_.])tor(?:$|[_.])', eid_lower):
            return False

        # 3. CoverConfig aus DB: cover_type + enabled
        try:
            from models import CoverConfig
            from db import get_db_session
            with get_db_session() as session:
                conf = session.query(CoverConfig).filter_by(entity_id=entity_id).first()
                if conf:
                    if conf.cover_type in _UNSAFE_COVER_TYPES:
                        return False
                    if conf.enabled is not None and not conf.enabled:
                        return False
        except Exception:
            self.logger.warning("DB-Fehler bei Safety-Check fuer %s — blockiere sicherheitshalber", entity_id)
            return False  # Fail-safe: bei DB-Fehler nicht automatisieren

        return True

    def _is_bed_occupied(self) -> bool:
        """Prueft ob ein Bettbelegungssensor aktiv ist (jemand schlaeft)."""
        try:
            states = self.ha.get_states() or []
            bed_sensors = [
                s for s in states
                if s.get("entity_id", "").startswith("binary_sensor.")
                and s.get("attributes", {}).get("device_class") == "occupancy"
                and any(kw in s.get("entity_id", "").lower()
                        for kw in ("bett", "bed", "matratze", "mattress"))
            ]
            if not bed_sensors:
                # Fallback: Alle Occupancy-Sensoren in Schlafzimmern
                bed_sensors = [
                    s for s in states
                    if s.get("entity_id", "").startswith("binary_sensor.")
                    and s.get("attributes", {}).get("device_class") == "occupancy"
                    and any(kw in s.get("entity_id", "").lower()
                            for kw in ("schlafzimmer", "bedroom"))
                ]
            if bed_sensors:
                return any(s.get("state") == "on" for s in bed_sensors)
        except Exception:
            pass
        return False
