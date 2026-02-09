"""MindHome - Solar Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class SolarDomain(DomainPlugin):
    DOMAIN_NAME = "solar"
    HA_DOMAINS = ["sensor"]
    DEVICE_CLASSES = ["power", "energy"]
    DEFAULT_SETTINGS = {"enabled": "false", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Solar domain ready (optional)")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Solar {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "production", "label_de": "Erzeugung", "label_en": "Production"},
            {"key": "self_consumption", "label_de": "Eigenverbrauch", "label_en": "Self consumption"},
        ]

    def get_current_status(self, room_id=None):
        return {"total": 0, "production_w": 0}

    def evaluate(self, context):
        return []  # Solar optimization planned for Phase 4
