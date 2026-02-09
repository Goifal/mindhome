"""MindHome - Switch Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class SwitchDomain(DomainPlugin):
    DOMAIN_NAME = "switch"
    HA_DOMAINS = ["switch"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "standby_kill_hours": "4",
    }

    def on_start(self):
        self.logger.info("Switch domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Switch {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        on_count = sum(1 for e in entities if e.get("state") == "on")
        return {"total": len(entities), "on": on_count, "off": len(entities) - on_count}

    def get_plugin_actions(self):
        return [
            {"key": "standby_kill", "label_de": "Standby-Killer (aus wenn idle)", "label_en": "Standby killer (off when idle)", "default": False},
        ]

    def evaluate(self, context):
        return []  # Standby detection runs via energy dashboard
