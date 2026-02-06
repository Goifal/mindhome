"""
MindHome - Light Domain Plugin
Tracks and controls all light entities.
"""

from .base import DomainPlugin


class LightDomain(DomainPlugin):
    DOMAIN_NAME = "light"
    HA_DOMAINS = ["light"]

    def on_start(self):
        self.logger.info("Light domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        state = new_state.get("state", "")
        attrs = new_state.get("attributes", {})

        self.logger.debug(
            f"Light {entity_id}: {old_state.get('state', '?')} -> {state} "
            f"(brightness: {attrs.get('brightness', '?')})"
        )

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
            {"key": "brightness", "label_de": "Helligkeit", "label_en": "Brightness"},
            {"key": "color_temp", "label_de": "Farbtemperatur", "label_en": "Color Temperature"},
            {"key": "color", "label_de": "Farbe", "label_en": "Color"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        on_count = sum(1 for e in entities if e.get("state") == "on")
        return {
            "total": len(entities),
            "on": on_count,
            "off": len(entities) - on_count
        }
