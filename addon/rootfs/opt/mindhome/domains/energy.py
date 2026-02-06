"""
MindHome - Energy Domain Plugin
Tracks power consumption and energy monitoring.
"""

from .base import DomainPlugin


class EnergyDomain(DomainPlugin):
    DOMAIN_NAME = "energy"
    HA_DOMAINS = ["sensor"]
    DEVICE_CLASSES = ["power", "energy", "current", "voltage", "gas"]

    def on_start(self):
        self.logger.info("Energy domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        device_class = new_state.get("attributes", {}).get("device_class", "")
        if device_class not in self.DEVICE_CLASSES:
            return

        self.logger.debug(
            f"Energy {entity_id}: {new_state.get('state')} "
            f"{new_state.get('attributes', {}).get('unit_of_measurement', '')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "power", "label_de": "Leistung (W)", "label_en": "Power (W)"},
            {"key": "energy", "label_de": "Energie (kWh)", "label_en": "Energy (kWh)"},
            {"key": "voltage", "label_de": "Spannung (V)", "label_en": "Voltage (V)"},
            {"key": "current", "label_de": "Strom (A)", "label_en": "Current (A)"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        return {
            "total": len(relevant),
            "sensors": len(relevant)
        }
