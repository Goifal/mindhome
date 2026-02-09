"""MindHome - Light Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class LightDomain(DomainPlugin):
    DOMAIN_NAME = "light"
    HA_DOMAINS = ["light"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "dim_brightness_pct": "20", "dusk_brightness_pct": "80",
    }

    def on_start(self):
        self.logger.info("Light domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Light {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "on_off", "label_de": "Ein/Aus", "label_en": "On/Off"},
            {"key": "brightness", "label_de": "Helligkeit", "label_en": "Brightness"},
            {"key": "color_temp", "label_de": "Farbtemperatur", "label_en": "Color Temperature"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        on_count = sum(1 for e in entities if e.get("state") == "on")
        return {"total": len(entities), "on": on_count, "off": len(entities) - on_count}

    def get_plugin_actions(self):
        return [
            {"key": "auto_on_dusk", "label_de": "Bei Daemmerung einschalten", "label_en": "Turn on at dusk", "default": True},
            {"key": "auto_off_away", "label_de": "Bei Abwesenheit ausschalten", "label_en": "Turn off when away", "default": True},
            {"key": "night_dim", "label_de": "Nachtmodus dimmen", "label_en": "Night mode dim", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()
        actions = []
        entities = self.get_entities()
        dim_pct = int(self.get_setting("dim_brightness_pct", 20))
        dusk_pct = int(self.get_setting("dusk_brightness_pct", 80))

        # Dusk + someone home -> lights on
        if self.get_setting("auto_on_dusk", True):
            if ctx.get("is_dark") and ctx.get("anyone_home"):
                for e in entities:
                    if e.get("state") == "off":
                        name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                        actions.append({
                            "entity_id": e["entity_id"], "service": "turn_on",
                            "data": {"brightness_pct": dusk_pct},
                            "reason_de": f"Daemmerung: {name} einschalten",
                            "reason_en": f"Dusk: turn on {name}",
                        })

        # Nobody home -> lights off
        if self.get_setting("auto_off_away", True):
            if not ctx.get("anyone_home"):
                for e in entities:
                    if e.get("state") == "on":
                        name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                        actions.append({
                            "entity_id": e["entity_id"], "service": "turn_off",
                            "reason_de": f"Niemand zuhause: {name} ausschalten",
                            "reason_en": f"Nobody home: turn off {name}",
                        })

        # Night mode -> dim
        if self.get_setting("night_dim", True):
            phase = ctx.get("day_phase", "")
            if phase in ("Nacht", "Nachtruhe", "Night"):
                for e in entities:
                    if e.get("state") == "on":
                        brightness = e.get("attributes", {}).get("brightness", 255)
                        if brightness and brightness > 50:
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "turn_on",
                                "data": {"brightness_pct": dim_pct},
                                "reason_de": f"Nachtmodus: {name} dimmen",
                                "reason_en": f"Night mode: dim {name}",
                            })

        return self.execute_or_suggest(actions)
