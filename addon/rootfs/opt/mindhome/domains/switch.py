"""
MindHome - Switch Domain Plugin
Tracks smart plugs with/without power monitoring.
"""

from .base import DomainPlugin


class SwitchDomain(DomainPlugin):
    DOMAIN_NAME = "switch"
    HA_DOMAINS = ["switch"]

    def on_start(self):
        self.logger.info("Switch domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        self.logger.debug(f"Switch {entity_id}: {new_state.get('state')}")

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
            {"key": "power", "label_de": "Leistung", "label_en": "Power"},
            {"key": "energy", "label_de": "Verbrauch", "label_en": "Consumption"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        on_count = sum(1 for e in entities if e.get("state") == "on")
        return {
            "total": len(entities),
            "on": on_count,
            "off": len(entities) - on_count
        }
