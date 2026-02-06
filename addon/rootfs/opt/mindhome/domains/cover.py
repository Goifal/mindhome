"""
MindHome - Cover Domain Plugin
Tracks and controls blinds, shutters, garage doors.
"""

from .base import DomainPlugin


class CoverDomain(DomainPlugin):
    DOMAIN_NAME = "cover"
    HA_DOMAINS = ["cover"]

    def on_start(self):
        self.logger.info("Cover domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        attrs = new_state.get("attributes", {})
        self.logger.debug(
            f"Cover {entity_id}: {new_state.get('state')} "
            f"position={attrs.get('current_position', '?')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "position", "label_de": "Position", "label_en": "Position"},
            {"key": "tilt", "label_de": "Neigung", "label_en": "Tilt"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        open_count = sum(1 for e in entities if e.get("state") == "open")
        return {
            "total": len(entities),
            "open": open_count,
            "closed": len(entities) - open_count
        }
