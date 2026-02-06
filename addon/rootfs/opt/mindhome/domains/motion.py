"""
MindHome - Motion Domain Plugin
Tracks motion/occupancy sensors.
"""

from .base import DomainPlugin


class MotionDomain(DomainPlugin):
    DOMAIN_NAME = "motion"
    HA_DOMAINS = ["binary_sensor"]
    DEVICE_CLASSES = ["motion", "occupancy"]

    def on_start(self):
        self.logger.info("Motion domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        device_class = new_state.get("attributes", {}).get("device_class", "")
        if device_class not in self.DEVICE_CLASSES:
            return

        self.logger.debug(f"Motion {entity_id}: {new_state.get('state')}")

    def get_trackable_features(self):
        return [
            {"key": "motion_events", "label_de": "Bewegungsereignisse", "label_en": "Motion Events"},
            {"key": "room_activity", "label_de": "Raumaktivität", "label_en": "Room Activity"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        active = sum(1 for e in relevant if e.get("state") == "on")
        return {
            "total": len(relevant),
            "active": active,
            "inactive": len(relevant) - active
        }
