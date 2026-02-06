"""
MindHome - Door/Window Domain Plugin
Tracks contact sensors on doors and windows.
"""

from .base import DomainPlugin


class DoorWindowDomain(DomainPlugin):
    DOMAIN_NAME = "door_window"
    HA_DOMAINS = ["binary_sensor"]
    DEVICE_CLASSES = ["door", "window", "opening", "garage_door"]

    def on_start(self):
        self.logger.info("Door/Window domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        device_class = new_state.get("attributes", {}).get("device_class", "")
        if device_class not in self.DEVICE_CLASSES:
            return

        name = new_state.get("attributes", {}).get("friendly_name", entity_id)
        state = new_state.get("state", "")
        self.logger.debug(f"Door/Window {name}: {state}")

    def get_trackable_features(self):
        return [
            {"key": "open_close", "label_de": "Offen/Geschlossen", "label_en": "Open/Closed"},
            {"key": "duration", "label_de": "Öffnungsdauer", "label_en": "Open Duration"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        open_count = sum(1 for e in relevant if e.get("state") == "on")
        return {
            "total": len(relevant),
            "open": open_count,
            "closed": len(relevant) - open_count
        }
