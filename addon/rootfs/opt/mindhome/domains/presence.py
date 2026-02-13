"""MindHome - Presence Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class PresenceDomain(DomainPlugin):
    DOMAIN_NAME = "presence"
    HA_DOMAINS = ["person", "device_tracker", "proximity"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Presence domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Presence {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "home_away", "label_de": "Zuhause/Weg", "label_en": "Home/Away"},
            {"key": "location", "label_de": "Standort", "label_en": "Location"},
            {"key": "proximity", "label_de": "Entfernung/Proximität", "label_en": "Proximity/Distance"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        persons = [e for e in entities if not e.get("entity_id", "").startswith("proximity.")]
        home = sum(1 for e in persons if e.get("state") == "home")
        proximity_entities = [e for e in entities if e.get("entity_id", "").startswith("proximity.")]
        return {
            "total": len(persons),
            "home": home,
            "away": len(persons) - home,
            "proximity_sensors": len(proximity_entities),
        }

    def evaluate(self, context):
        return []  # Presence triggers are handled by PresenceModeManager
