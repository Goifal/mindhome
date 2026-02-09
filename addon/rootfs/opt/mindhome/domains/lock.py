"""MindHome - Lock Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class LockDomain(DomainPlugin):
    DOMAIN_NAME = "lock"
    HA_DOMAINS = ["lock", "binary_sensor"]
    DEVICE_CLASSES = ["lock", "smoke", "carbon_monoxide", "gas"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Lock domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            dc = new_state.get("attributes", {}).get("device_class", "")
            state = new_state.get("state", "")
            if dc in ("smoke", "carbon_monoxide", "gas") and state == "on":
                name = new_state.get("attributes", {}).get("friendly_name", entity_id)
                self.logger.warning(f"ALARM: {name} ({dc}) triggered!")
                self.send_notification(
                    f"ALARM: {name} hat ausgeloest! ({dc})",
                    title="Sicherheitsalarm",
                    notification_type="critical",
                )
        else:
            state = new_state
        self.logger.debug(f"Lock {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "locked_unlocked", "label_de": "Gesperrt/Offen", "label_en": "Locked/Unlocked"},
            {"key": "smoke", "label_de": "Rauchmelder", "label_en": "Smoke detector"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        locks = [e for e in entities if e.get("entity_id", "").startswith("lock.")]
        locked = sum(1 for e in locks if e.get("state") == "locked")
        return {"total": len(locks), "locked": locked, "unlocked": len(locks) - locked}

    def get_plugin_actions(self):
        return [
            {"key": "auto_lock_away", "label_de": "Auto-Lock bei Abwesenheit", "label_en": "Auto-lock when away", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()
        actions = []

        if self.get_setting("auto_lock_away", True):
            if not ctx.get("anyone_home"):
                entities = self.get_entities()
                locks = [e for e in entities if e.get("entity_id", "").startswith("lock.")]
                for e in locks:
                    if e.get("state") == "unlocked":
                        name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                        actions.append({
                            "entity_id": e["entity_id"], "service": "lock",
                            "reason_de": f"Niemand zuhause: {name} absperren",
                            "reason_en": f"Nobody home: lock {name}",
                        })

        return self.execute_or_suggest(actions)
