"""MindHome - Media Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class MediaDomain(DomainPlugin):
    DOMAIN_NAME = "media"
    HA_DOMAINS = ["media_player"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "night_volume_pct": "30",
    }

    def on_start(self):
        self.logger.info("Media domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Media {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "playback", "label_de": "Wiedergabe", "label_en": "Playback"},
            {"key": "volume", "label_de": "Lautstaerke", "label_en": "Volume"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        playing = sum(1 for e in entities if e.get("state") == "playing")
        return {"total": len(entities), "playing": playing, "idle": len(entities) - playing}

    def get_plugin_actions(self):
        return [
            {"key": "night_volume", "label_de": "Nachtmodus Lautstaerke", "label_en": "Night mode volume", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()
        actions = []
        night_vol = float(self.get_setting("night_volume_pct", 30)) / 100

        if self.get_setting("night_volume", True):
            phase = ctx.get("day_phase", "")
            if phase in ("Nacht", "Nachtruhe", "Night"):
                for e in self.get_entities():
                    if e.get("state") == "playing":
                        vol = e.get("attributes", {}).get("volume_level", 0)
                        if vol and vol > night_vol:
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "volume_set",
                                "data": {"volume_level": night_vol},
                                "reason_de": f"Nachtmodus: {name} leiser",
                                "reason_en": f"Night mode: lower {name} volume",
                            })

        return self.execute_or_suggest(actions)
