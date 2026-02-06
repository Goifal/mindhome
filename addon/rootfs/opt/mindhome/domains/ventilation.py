"""
MindHome - Ventilation Domain Plugin
Tracks and controls ventilation/HRV systems.
"""

from .base import DomainPlugin


class VentilationDomain(DomainPlugin):
    DOMAIN_NAME = "ventilation"
    HA_DOMAINS = ["fan", "climate"]

    def on_start(self):
        self.logger.info("Ventilation domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        self.logger.debug(
            f"Ventilation {entity_id}: {new_state.get('state')} "
            f"speed={new_state.get('attributes', {}).get('percentage', '?')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
            {"key": "speed", "label_de": "Geschwindigkeit", "label_en": "Speed"},
            {"key": "mode", "label_de": "Modus", "label_en": "Mode"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        on_count = sum(1 for e in entities if e.get("state") == "on")
        return {
            "total": len(entities),
            "on": on_count,
            "off": len(entities) - on_count
        }
