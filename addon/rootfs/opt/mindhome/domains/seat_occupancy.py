"""MindHome - Seat Occupancy Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class SeatOccupancyDomain(DomainPlugin):
    DOMAIN_NAME = "seat_occupancy"
    HA_DOMAINS = ["binary_sensor"]
    DEVICE_CLASSES = ["occupancy"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Seat occupancy domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"Seat occupancy {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "seat_occupied", "label_de": "Sitz belegt", "label_en": "Seat occupied"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        occupied = sum(1 for e in relevant if e.get("state") == "on")
        return {"total": len(relevant), "occupied": occupied, "free": len(relevant) - occupied}

    def evaluate(self, context):
        return []
