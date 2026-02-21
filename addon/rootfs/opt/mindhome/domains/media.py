"""MindHome - Media Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class MediaDomain(DomainPlugin):
    DOMAIN_NAME = "media"
    HA_DOMAINS = ["media_player"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "night_volume_pct": "30",
    }

    # Receiver/TVs die NICHT automatisch leiser gestellt werden sollen.
    # Diese werden vom User manuell gesteuert und verwalten ihre
    # eigene Lautstaerke (z.B. Onkyo ueber IR/HDMI-CEC).
    _VOLUME_EXCLUDE_PATTERNS = (
        "tv", "fernseher", "television", "fire_tv", "firetv", "apple_tv",
        "appletv", "receiver", "avr", "denon", "marantz", "yamaha_receiver",
        "onkyo", "pioneer", "soundbar",
        "xbox", "playstation", "ps5", "ps4", "nintendo",
    )

    def _is_auto_volume_target(self, entity_id, attributes=None):
        """Prueft ob ein media_player automatisch leiser gestellt werden darf.

        Receiver, TVs und andere manuell gesteuerte Geraete werden ausgeschlossen.
        """
        entity_lower = entity_id.lower()
        for pattern in self._VOLUME_EXCLUDE_PATTERNS:
            if pattern in entity_lower:
                return False
        if attributes:
            friendly = (attributes.get("friendly_name") or "").lower()
            for pattern in self._VOLUME_EXCLUDE_PATTERNS:
                if pattern in friendly:
                    return False
            device_class = (attributes.get("device_class") or "").lower()
            if device_class in ("tv", "receiver"):
                return False
        return True

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
                        attrs = e.get("attributes", {})
                        # Receiver/TVs nicht automatisch leiser stellen
                        if not self._is_auto_volume_target(e["entity_id"], attrs):
                            continue
                        vol = attrs.get("volume_level", 0)
                        if vol and vol > night_vol:
                            name = attrs.get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "volume_set",
                                "data": {"volume_level": night_vol},
                                "reason_de": f"Nachtmodus: {name} leiser",
                                "reason_en": f"Night mode: lower {name} volume",
                            })

        return self.execute_or_suggest(actions)
