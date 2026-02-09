"""MindHome - Ventilation Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class VentilationDomain(DomainPlugin):
    DOMAIN_NAME = "ventilation"
    HA_DOMAINS = ["fan"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "co2_boost_threshold": "1200",
    }

    def on_start(self):
        self.logger.info("Ventilation domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Ventilation {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
            {"key": "speed", "label_de": "Geschwindigkeit", "label_en": "Speed"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        on_count = sum(1 for e in entities if e.get("state") == "on")
        return {"total": len(entities), "on": on_count, "off": len(entities) - on_count}

    def get_plugin_actions(self):
        return [
            {"key": "co2_boost", "label_de": "Boost bei hohem CO2", "label_en": "Boost on high CO2", "default": True},
        ]

    def evaluate(self, context):
        return []  # CO2 detection triggers via air_quality plugin
