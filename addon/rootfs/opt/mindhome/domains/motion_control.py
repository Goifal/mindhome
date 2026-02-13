"""MindHome - Motion Sensor Control Domain Plugin (Phase 3)

Unlike the read-only 'motion' domain, this domain manages
controllable motion sensors (enable/disable, sensitivity).
Covers Zigbee/Z-Wave motion sensors exposed as switch or
binary_sensor with controllable attributes.
"""
from .base import DomainPlugin


class MotionControlDomain(DomainPlugin):
    DOMAIN_NAME = "motion_control"
    HA_DOMAINS = ["switch", "binary_sensor"]
    DEVICE_CLASSES = ["motion"]
    DEFAULT_SETTINGS = {
        "enabled": "true",
        "mode": "suggest",
        "disable_when_home": "false",
        "quiet_hours_off": "true",
    }

    def on_start(self):
        self.logger.info("Motion control domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"Motion control {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "sensor_enabled", "label_de": "Sensor aktiv", "label_en": "Sensor enabled"},
            {"key": "sensitivity", "label_de": "Empfindlichkeit", "label_en": "Sensitivity"},
            {"key": "quiet_hours_control", "label_de": "Ruhezeiten-Steuerung", "label_en": "Quiet hours control"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        enabled = sum(1 for e in relevant if e.get("state") == "on")
        return {"total": len(relevant), "enabled": enabled, "disabled": len(relevant) - enabled}

    def get_plugin_actions(self):
        return [
            {"key": "enable_all", "label_de": "Alle Melder aktivieren", "label_en": "Enable all sensors",
             "service": "turn_on"},
            {"key": "disable_all", "label_de": "Alle Melder deaktivieren", "label_en": "Disable all sensors",
             "service": "turn_off"},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []

        actions = []

        # Quiet hours: disable motion sensors to avoid false triggers
        if self.get_setting("quiet_hours_off", "true") == "true" and self.is_quiet_time():
            for entity in self.get_entities():
                eid = entity.get("entity_id", "")
                dc = entity.get("attributes", {}).get("device_class", "")
                state = entity.get("state", "")
                if dc in self.DEVICE_CLASSES and state == "on" and self.is_entity_tracked(eid):
                    ha_domain = eid.split(".")[0]
                    if ha_domain == "switch":
                        actions.append({
                            "entity_id": eid,
                            "service": "turn_off",
                            "data": {},
                            "reason_de": "Ruhezeit - Bewegungsmelder deaktivieren",
                            "reason_en": "Quiet hours - disable motion sensor",
                        })

        return actions
