"""MindHome - Cover Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class CoverDomain(DomainPlugin):
    DOMAIN_NAME = "cover"
    HA_DOMAINS = ["cover"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "sun_elevation_threshold": "5",
    }

    def on_start(self):
        self.logger.info("Cover domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Cover {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "position", "label_de": "Position", "label_en": "Position"},
            {"key": "tilt", "label_de": "Neigung", "label_en": "Tilt"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        open_count = sum(1 for e in entities if e.get("state") == "open")
        return {"total": len(entities), "open": open_count, "closed": len(entities) - open_count}

    def get_plugin_actions(self):
        return [
            {"key": "sunset_close", "label_de": "Bei Sonnenuntergang schliessen", "label_en": "Close at sunset", "default": True},
            {"key": "sunrise_open", "label_de": "Bei Sonnenaufgang oeffnen", "label_en": "Open at sunrise", "default": True},
            {"key": "sun_shading", "label_de": "Beschattung bei Sonneneinstrahlung", "label_en": "Sun shading", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()
        actions = []
        entities = self.get_entities()
        sun = self.get_sun_state()
        threshold = float(self.get_setting("sun_elevation_threshold", 5))

        if not sun:
            return []

        elevation = sun.get("elevation", 0)

        # Sunset -> close covers
        if self.get_setting("sunset_close", True):
            if elevation < -2 and ctx.get("anyone_home"):
                for e in entities:
                    if e.get("state") == "open":
                        name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                        actions.append({
                            "entity_id": e["entity_id"], "service": "close_cover",
                            "reason_de": f"Sonnenuntergang: {name} schliessen",
                            "reason_en": f"Sunset: close {name}",
                        })

        # Sunrise -> open covers
        if self.get_setting("sunrise_open", True):
            if elevation > threshold and sun.get("rising"):
                for e in entities:
                    if e.get("state") == "closed":
                        name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                        actions.append({
                            "entity_id": e["entity_id"], "service": "open_cover",
                            "reason_de": f"Sonnenaufgang: {name} oeffnen",
                            "reason_en": f"Sunrise: open {name}",
                        })

        # High sun + warm -> partial shading
        if self.get_setting("sun_shading", True):
            if elevation > 40:
                weather = self.get_weather()
                if weather and weather.get("temperature", 0) > 25:
                    for e in entities:
                        if e.get("state") == "open":
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "set_cover_position",
                                "data": {"position": 50},
                                "reason_de": f"Beschattung: {name} halb schliessen (Sonne hoch + warm)",
                                "reason_en": f"Shading: half-close {name} (sun high + warm)",
                            })

        return self.execute_or_suggest(actions)
