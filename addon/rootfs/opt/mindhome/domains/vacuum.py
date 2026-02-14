"""MindHome - Vacuum/Robot Vacuum Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class VacuumDomain(DomainPlugin):
    DOMAIN_NAME = "vacuum"
    HA_DOMAINS = ["vacuum"]
    DEVICE_CLASSES = []
    DEFAULT_SETTINGS = {
        "enabled": "true",
        "mode": "suggest",
        "clean_when_away": "true",
    }

    def on_start(self):
        self.logger.info("Vacuum domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            state = new_state.get("state", "")
            battery = new_state.get("attributes", {}).get("battery_level")
        else:
            state = new_state
            battery = None
        self.logger.debug(f"Vacuum {entity_id}: -> {state} (battery={battery})")

    def get_trackable_features(self):
        return [
            {"key": "cleaning_active", "label_de": "Reinigung aktiv", "label_en": "Cleaning active"},
            {"key": "battery_level", "label_de": "Akkustand", "label_en": "Battery level"},
            {"key": "clean_when_away", "label_de": "Reinigung bei Abwesenheit", "label_en": "Clean when away"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        cleaning = sum(1 for e in entities if e.get("state") == "cleaning")
        docked = sum(1 for e in entities if e.get("state") == "docked")
        returning = sum(1 for e in entities if e.get("state") == "returning")
        return {
            "total": len(entities),
            "cleaning": cleaning,
            "docked": docked,
            "returning": returning,
        }

    def evaluate(self, context):
        if not self.is_enabled() or not self.get_setting("clean_when_away", "true") == "true":
            return []
        if context.get("anyone_home", True):
            return []

        actions = []
        for entity in self.get_entities():
            eid = entity.get("entity_id", "")
            state = entity.get("state", "")
            if state == "docked" and self.is_entity_tracked(eid):
                actions.append({
                    "entity_id": eid,
                    "service": "start",
                    "data": {},
                    "reason_de": "Niemand zuhause - Saugroboter starten",
                    "reason_en": "Nobody home - start robot vacuum",
                })
        return actions
