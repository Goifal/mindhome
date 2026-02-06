"""
MindHome - Solar PV Domain Plugin
Tracks photovoltaic generation, self-consumption, feed-in.
"""

from .base import DomainPlugin


class SolarDomain(DomainPlugin):
    DOMAIN_NAME = "solar"
    HA_DOMAINS = ["sensor"]
    DEVICE_CLASSES = ["power", "energy"]

    def on_start(self):
        self.logger.info("Solar PV domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        self.logger.debug(
            f"Solar {entity_id}: {new_state.get('state')} "
            f"{new_state.get('attributes', {}).get('unit_of_measurement', '')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "generation", "label_de": "Erzeugung", "label_en": "Generation"},
            {"key": "self_consumption", "label_de": "Eigenverbrauch", "label_en": "Self Consumption"},
            {"key": "feed_in", "label_de": "Einspeisung", "label_en": "Feed-in"},
            {"key": "battery", "label_de": "Batteriestand", "label_en": "Battery Level"},
        ]

    def get_current_status(self, room_id=None):
        return {
            "total": 0,
            "note": "PV integration ready - activate when available"
        }
