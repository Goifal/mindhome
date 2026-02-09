"""MindHome - Door/Window Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class DoorWindowDomain(DomainPlugin):
    DOMAIN_NAME = "door_window"
    HA_DOMAINS = ["binary_sensor"]
    DEVICE_CLASSES = ["door", "window", "opening", "garage_door"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Door/Window domain ready")

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
        self.logger.debug(f"Door/Window {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "open_close", "label_de": "Offen/Geschlossen", "label_en": "Open/Closed"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        open_count = sum(1 for e in relevant if e.get("state") == "on")
        return {"total": len(relevant), "open": open_count, "closed": len(relevant) - open_count}

    def get_plugin_actions(self):
        return [
            {"key": "rain_warning", "label_de": "Warnung Regen + Fenster offen", "label_en": "Rain + window open warning", "default": True},
            {"key": "heating_warning", "label_de": "Warnung Heizung + Fenster offen", "label_en": "Heating + window open warning", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()
        actions = []
        entities = self.get_entities()
        relevant = [e for e in entities if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        open_windows = [e for e in relevant if e.get("state") == "on"]

        if not open_windows:
            return []

        # Rain + window open
        if self.get_setting("rain_warning", True) and ctx.get("is_rainy"):
            for e in open_windows:
                name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                actions.append({
                    "entity_id": e["entity_id"], "service": "notify",
                    "reason_de": f"Regen! {name} ist offen",
                    "reason_en": f"Rain! {name} is open",
                })

        return self.execute_or_suggest(actions)
