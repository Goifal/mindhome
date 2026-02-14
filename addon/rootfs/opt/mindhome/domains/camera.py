"""MindHome - Camera Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class CameraDomain(DomainPlugin):
    DOMAIN_NAME = "camera"
    HA_DOMAINS = ["camera"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Camera domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"Camera {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "recording", "label_de": "Aufnahme", "label_en": "Recording"},
            {"key": "motion_detected", "label_de": "Bewegung erkannt", "label_en": "Motion detected"},
            {"key": "streaming", "label_de": "Live-Stream", "label_en": "Live stream"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        streaming = sum(1 for e in entities if e.get("state") == "streaming")
        idle = sum(1 for e in entities if e.get("state") == "idle")
        return {
            "total": len(entities),
            "streaming": streaming,
            "idle": idle,
            "offline": len(entities) - streaming - idle,
        }

    def evaluate(self, context):
        return []
