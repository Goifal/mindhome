"""MindHome - Motion Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class MotionDomain(DomainPlugin):
    DOMAIN_NAME = "motion"
    HA_DOMAINS = ["binary_sensor"]
    DEVICE_CLASSES = ["motion", "occupancy"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Motion domain ready")

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
        self.logger.debug(f"Motion {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "motion_detected", "label_de": "Bewegung erkannt", "label_en": "Motion detected"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        active = sum(1 for e in relevant if e.get("state") == "on")
        return {"total": len(relevant), "active": active, "clear": len(relevant) - active}

    def evaluate(self, context):
        return []  # Motion feeds into presence detection and pattern engine
