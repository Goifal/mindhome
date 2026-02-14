"""MindHome - Humidifier Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class HumidifierDomain(DomainPlugin):
    DOMAIN_NAME = "humidifier"
    HA_DOMAINS = ["humidifier"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Humidifier domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"Humidifier {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "target_humidity", "label_de": "Ziel-Luftfeuchtigkeit", "label_en": "Target humidity"},
            {"key": "current_humidity", "label_de": "Aktuelle Luftfeuchtigkeit", "label_en": "Current humidity"},
            {"key": "mode", "label_de": "Betriebsmodus", "label_en": "Operating mode"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        active = sum(1 for e in entities
                     if e.get("state") not in ("off", "unavailable", "unknown"))
        return {"total": len(entities), "active": active, "off": len(entities) - active}

    def evaluate(self, context):
        return []
