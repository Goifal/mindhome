"""
MindHome - Climate Domain Plugin
Tracks and controls thermostats, heating, AC.
"""

from .base import DomainPlugin


class ClimateDomain(DomainPlugin):
    DOMAIN_NAME = "climate"
    HA_DOMAINS = ["climate"]

    def on_start(self):
        self.logger.info("Climate domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        attrs = new_state.get("attributes", {})
        self.logger.debug(
            f"Climate {entity_id}: mode={new_state.get('state')} "
            f"current={attrs.get('current_temperature')} "
            f"target={attrs.get('temperature')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "mode", "label_de": "Betriebsmodus", "label_en": "Operating Mode"},
            {"key": "temperature", "label_de": "Zieltemperatur", "label_en": "Target Temperature"},
            {"key": "current_temp", "label_de": "Aktuelle Temperatur", "label_en": "Current Temperature"},
            {"key": "humidity", "label_de": "Luftfeuchtigkeit", "label_en": "Humidity"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        heating = sum(1 for e in entities if e.get("state") == "heat")
        cooling = sum(1 for e in entities if e.get("state") == "cool")
        return {
            "total": len(entities),
            "heating": heating,
            "cooling": cooling,
            "off": len(entities) - heating - cooling
        }
