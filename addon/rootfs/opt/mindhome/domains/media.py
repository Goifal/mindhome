"""
MindHome - Media Domain Plugin
Tracks TV, speakers, media players.
"""

from .base import DomainPlugin


class MediaDomain(DomainPlugin):
    DOMAIN_NAME = "media"
    HA_DOMAINS = ["media_player"]

    def on_start(self):
        self.logger.info("Media domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        self.logger.debug(
            f"Media {entity_id}: {new_state.get('state')} "
            f"source={new_state.get('attributes', {}).get('source', '?')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
            {"key": "source", "label_de": "Quelle", "label_en": "Source"},
            {"key": "volume", "label_de": "Lautstärke", "label_en": "Volume"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        playing = sum(1 for e in entities if e.get("state") in ("playing", "on"))
        return {
            "total": len(entities),
            "playing": playing,
            "idle": len(entities) - playing
        }
