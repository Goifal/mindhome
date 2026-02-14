"""MindHome - System Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class SystemDomain(DomainPlugin):
    DOMAIN_NAME = "system"
    HA_DOMAINS = ["sensor", "binary_sensor"]
    DEVICE_CLASSES = [
        "battery", "connectivity", "plug", "power",
        "data_size", "data_rate", "frequency",
        "signal_strength", "timestamp",
    ]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("System domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"System {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "battery_level", "label_de": "Akkustand", "label_en": "Battery level"},
            {"key": "connectivity", "label_de": "Verbindungsstatus", "label_en": "Connectivity status"},
            {"key": "system_load", "label_de": "Systemauslastung", "label_en": "System load"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        online = sum(1 for e in relevant
                     if e.get("state") not in ("unavailable", "unknown", "off"))
        return {"total": len(relevant), "online": online, "offline": len(relevant) - online}

    def evaluate(self, context):
        return []
