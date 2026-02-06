"""
MindHome - Presence Domain Plugin
Tracks who is home via person/device_tracker entities.
"""

from .base import DomainPlugin


class PresenceDomain(DomainPlugin):
    DOMAIN_NAME = "presence"
    HA_DOMAINS = ["person", "device_tracker"]

    def on_start(self):
        self.logger.info("Presence domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        old = old_state.get("state", "")
        new = new_state.get("state", "")

        if old != new:
            name = new_state.get("attributes", {}).get("friendly_name", entity_id)
            if new == "home":
                self.logger.info(f"{name} arrived home")
            elif old == "home":
                self.logger.info(f"{name} left home")

    def get_trackable_features(self):
        return [
            {"key": "home_away", "label_de": "Zuhause/Weg", "label_en": "Home/Away"},
            {"key": "arrival_time", "label_de": "Ankunftszeit", "label_en": "Arrival Time"},
            {"key": "departure_time", "label_de": "Abfahrtszeit", "label_en": "Departure Time"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        home = [e for e in entities if e.get("state") == "home"]
        away = [e for e in entities if e.get("state") != "home"]
        return {
            "total": len(entities),
            "home": len(home),
            "away": len(away),
            "home_names": [e.get("attributes", {}).get("friendly_name", "") for e in home]
        }
