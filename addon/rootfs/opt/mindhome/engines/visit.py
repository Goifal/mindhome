# MindHome - engines/visit.py | see version.py for version info
"""
Visit preparation management and vacation detection.
Features: #22 Besuchs-Vorbereitung, #29 Automatische Urlaubserkennung
"""

import logging
from datetime import datetime, timezone, timedelta

from helpers import get_setting

logger = logging.getLogger("mindhome.engines.visit")


class VisitPreparationManager:
    """Manages visit preparation templates and their execution.

    Templates define actions like: set living room to 22C, lights to 80%, music on.
    Can be triggered manually, by calendar, or by guest device detection.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("VisitPreparationManager started")

    def stop(self):
        self._is_running = False
        logger.info("VisitPreparationManager stopped")

    def activate(self, preparation_id):
        """Activate a visit preparation by ID — execute all actions."""
        try:
            from models import VisitPreparation
            with self.get_session() as session:
                prep = session.get(VisitPreparation, preparation_id)
                if not prep:
                    return {"error": "Preparation not found"}

                actions = prep.preparation_actions or []
                executed = 0
                for action in actions:
                    entity_id = action.get("entity_id")
                    service = action.get("service")
                    data = action.get("data", {})
                    if not entity_id or not service:
                        continue
                    try:
                        domain = entity_id.split(".")[0]
                        service_data = {"entity_id": entity_id, **data}
                        self.ha.call_service(domain, service, service_data)
                        executed += 1
                    except Exception as e:
                        logger.error(f"Visit action error {entity_id}/{service}: {e}")

                self.event_bus.publish("visit.preparation_activated", {
                    "preparation_id": preparation_id,
                    "name": prep.name,
                    "actions_executed": executed,
                })
                logger.info(f"Visit preparation '{prep.name}' activated: {executed}/{len(actions)} actions")
                return {"success": True, "actions_executed": executed, "total_actions": len(actions)}
        except Exception as e:
            logger.error(f"activate error: {e}")
            return {"error": str(e)}

    def get_preparations(self):
        """Return list of configured visit preparations."""
        try:
            from models import VisitPreparation
            with self.get_session() as session:
                preps = session.query(VisitPreparation).order_by(VisitPreparation.name).all()
                return [{
                    "id": p.id,
                    "name": p.name,
                    "guest_count": p.guest_count,
                    "preparation_actions": p.preparation_actions or [],
                    "auto_trigger": p.auto_trigger,
                    "trigger_config": p.trigger_config,
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                } for p in preps]
        except Exception as e:
            logger.error(f"get_preparations error: {e}")
            return []

    def check_triggers(self):
        """Check if any auto-triggered preparations should activate.
        Called periodically by scheduler.
        """
        if not self._is_running:
            return
        try:
            from models import VisitPreparation
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.visit_preparation"):
                return

            with self.get_session() as session:
                auto_preps = session.query(VisitPreparation).filter(
                    VisitPreparation.auto_trigger == True,
                    VisitPreparation.is_active == True
                ).all()

                for prep in auto_preps:
                    cfg = prep.trigger_config or {}
                    trigger_type = cfg.get("type")

                    if trigger_type == "device":
                        # Check if guest device is home
                        entity = cfg.get("entity")
                        if entity:
                            try:
                                state = self.ha.get_state(entity)
                                if state and state.get("state") == "home":
                                    self.activate(prep.id)
                            except Exception:
                                pass
        except Exception as e:
            logger.error(f"check_triggers error: {e}")


class VacationDetector:
    """Detects multi-day absence and auto-activates vacation mode (#29).

    Logic: All persons away > 24h -> vacation mode
    Optional: Presence simulation (random light on/off during vacation)
    Auto-deactivates on return.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._away_since = None  # timestamp when all went away

    def start(self):
        self._is_running = True
        logger.info("VacationDetector started")

    def stop(self):
        self._is_running = False
        logger.info("VacationDetector stopped")

    def check(self):
        """Check presence status for vacation detection. Called every 10 min."""
        if not self._is_running:
            return
        try:
            from routes.health import is_feature_enabled
            from helpers import get_setting, set_setting

            if not is_feature_enabled("phase4.vacation_detection"):
                return

            # Check if anyone is home via HA person entities
            all_away = True
            try:
                states = self.ha.get_states() or []
                persons = [s for s in states if s.get("entity_id", "").startswith("person.")]
                for p in persons:
                    if p.get("state") == "home":
                        all_away = False
                        break
                if not persons:
                    return  # No person entities, skip
            except Exception:
                return

            now = datetime.now(timezone.utc)
            vacation_active = get_setting("vacation_mode") == "true"

            if all_away:
                if not self._away_since:
                    self._away_since = now
                    logger.debug("All persons away, tracking start")

                hours_away = (now - self._away_since).total_seconds() / 3600

                # Activate vacation after 24h away
                if hours_away >= 24 and not vacation_active:
                    set_setting("vacation_mode", "true")
                    self.event_bus.publish("vacation.auto_activated", {
                        "away_hours": round(hours_away, 1),
                    })
                    logger.info(f"Vacation mode auto-activated (away {hours_away:.0f}h)")

                # Presence simulation during vacation
                if vacation_active and hours_away > 24:
                    self._presence_simulation()
            else:
                # Someone is home
                if self._away_since:
                    self._away_since = None

                # Auto-deactivate vacation on return
                if vacation_active and get_setting("vacation_auto_activated") == "true":
                    set_setting("vacation_mode", "false")
                    set_setting("vacation_auto_activated", "false")
                    self.event_bus.publish("vacation.auto_deactivated", {})
                    logger.info("Vacation mode auto-deactivated (person returned)")

        except Exception as e:
            logger.error(f"VacationDetector check error: {e}")

    def _presence_simulation(self):
        """Simulate presence by toggling lights randomly during vacation."""
        import random
        now = datetime.now(timezone.utc)
        hour = now.hour

        sim_start = int(get_setting("phase4.vacation_detection.sim_start_hour", "18"))
        sim_end = int(get_setting("phase4.vacation_detection.sim_end_hour", "23"))
        sim_brightness_min = int(get_setting("phase4.vacation_detection.sim_brightness_min", "80"))
        sim_brightness_max = int(get_setting("phase4.vacation_detection.sim_brightness_max", "200"))

        # Only simulate during configured hours
        if hour < sim_start or hour >= sim_end:
            return

        # 10% chance per check (every 10 min) -> ~1x per ~100 min
        if random.random() > 0.1:
            return

        try:
            states = self.ha.get_states() or []
            lights = [s for s in states if s.get("entity_id", "").startswith("light.")
                      and "wohn" in s.get("entity_id", "").lower() or "living" in s.get("entity_id", "").lower()]
            if lights:
                target = random.choice(lights)
                eid = target["entity_id"]
                if target.get("state") == "on":
                    self.ha.call_service("light", "turn_off", {"entity_id": eid})
                else:
                    self.ha.call_service("light", "turn_on", {"entity_id": eid, "brightness": random.randint(sim_brightness_min, sim_brightness_max)})
                logger.debug(f"Presence simulation: toggled {eid}")
        except Exception as e:
            logger.debug(f"Presence simulation error: {e}")

    def get_status(self):
        """Return current vacation detection status."""
        from helpers import get_setting
        return {
            "vacation_active": get_setting("vacation_mode") == "true",
            "auto_activated": get_setting("vacation_auto_activated") == "true",
            "away_since": self._away_since.isoformat() if self._away_since else None,
            "hours_away": round((datetime.now(timezone.utc) - self._away_since).total_seconds() / 3600, 1) if self._away_since else 0,
        }
