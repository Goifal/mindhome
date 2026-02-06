"""
MindHome - Lock & Security Domain Plugin
Tracks door locks, alarm systems, smoke/CO detectors.
"""

from .base import DomainPlugin


class LockDomain(DomainPlugin):
    DOMAIN_NAME = "lock"
    HA_DOMAINS = ["lock", "alarm_control_panel", "binary_sensor"]
    DEVICE_CLASSES = ["smoke", "carbon_monoxide", "gas", "safety"]

    def on_start(self):
        self.logger.info("Lock/Security domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        ha_domain = entity_id.split(".")[0]
        state = new_state.get("state", "")
        name = new_state.get("attributes", {}).get("friendly_name", entity_id)

        # Critical: smoke/CO detection
        device_class = new_state.get("attributes", {}).get("device_class", "")
        if device_class in ("smoke", "carbon_monoxide", "gas") and state == "on":
            self.send_notification(
                f"ALARM: {name} ausgelöst!",
                title="Sicherheitswarnung",
                notification_type="critical"
            )

        self.logger.debug(f"Security {entity_id}: {state}")

    def get_trackable_features(self):
        return [
            {"key": "lock_state", "label_de": "Schloss-Status", "label_en": "Lock State"},
            {"key": "alarm_state", "label_de": "Alarm-Status", "label_en": "Alarm State"},
            {"key": "smoke", "label_de": "Rauchmelder", "label_en": "Smoke Detector"},
        ]

    def get_current_status(self, room_id=None):
        locks = self.ha.get_entities_by_domain("lock")
        locked = sum(1 for e in locks if e.get("state") == "locked")
        return {
            "total_locks": len(locks),
            "locked": locked,
            "unlocked": len(locks) - locked
        }
