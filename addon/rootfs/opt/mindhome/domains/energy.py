"""MindHome - Energy Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class EnergyDomain(DomainPlugin):
    DOMAIN_NAME = "energy"
    HA_DOMAINS = ["sensor"]
    DEVICE_CLASSES = ["power", "energy", "current", "voltage", "gas", "battery"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "standby_threshold_w": "5", "standby_idle_minutes": "30",
    }

    def on_start(self):
        self.logger.info("Energy domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            dc = new_state.get("attributes", {}).get("device_class", "")
            if dc not in self.DEVICE_CLASSES:
                return
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"Energy {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "power", "label_de": "Leistung (W)", "label_en": "Power (W)"},
            {"key": "energy", "label_de": "Verbrauch (kWh)", "label_en": "Consumption (kWh)"},
            {"key": "battery", "label_de": "Batterie", "label_en": "Battery"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        total_power = 0
        for e in relevant:
            if e.get("attributes", {}).get("device_class") == "power":
                try:
                    total_power += float(e.get("state", 0))
                except (ValueError, TypeError):
                    pass
        return {"total": len(relevant), "total_power_w": round(total_power, 1)}

    def evaluate(self, context):
        return []  # Energy data feeds into dashboard, standby detection runs separately
