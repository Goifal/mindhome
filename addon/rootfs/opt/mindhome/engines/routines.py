# MindHome - engines/routines.py | see version.py for version info
"""
Routine detection/execution and mood estimation.
Features: #5 Morgenroutine, #6 Raumuebergaenge, #15 Stimmungserkennung
"""

import logging
import time as _time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger("mindhome.engines.routines")


class RoutineEngine:
    """Detects and executes coordinated action sequences (routines).

    Clusters patterns by time window (e.g. 5-9 AM for morning routine).
    Executes as coordinated sequence with delays between steps.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._cached_routines = []
        self._last_detect = None

    def start(self):
        self._is_running = True
        logger.info("RoutineEngine started")

    def stop(self):
        self._is_running = False
        logger.info("RoutineEngine stopped")

    def detect_routines(self):
        """Detect routine sequences from pattern data. Called daily."""
        if not self._is_running:
            return []
        try:
            from models import LearnedPattern
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.room_transitions"):
                return self._cached_routines

            with self.get_session() as session:
                # Get accepted/active patterns with time info
                patterns = session.query(LearnedPattern).filter(
                    LearnedPattern.is_active == True,
                    LearnedPattern.status == "accepted",
                    LearnedPattern.confidence >= 0.5
                ).all()

                if not patterns:
                    return []

                # Group by time window
                time_groups = {
                    "morning": [],    # 05:00 - 09:00
                    "daytime": [],    # 09:00 - 17:00
                    "evening": [],    # 17:00 - 22:00
                    "night": [],      # 22:00 - 05:00
                }

                for p in patterns:
                    ctx = p.context_tags or {}
                    time_str = ctx.get("time_of_day") or ctx.get("hour")
                    hour = None
                    if time_str:
                        try:
                            hour = int(str(time_str).split(":")[0]) if ":" in str(time_str) else int(time_str)
                        except (ValueError, TypeError):
                            pass

                    if hour is None and p.last_matched_at:
                        hour = p.last_matched_at.hour

                    if hour is None:
                        continue

                    if 5 <= hour < 9:
                        time_groups["morning"].append(p)
                    elif 9 <= hour < 17:
                        time_groups["daytime"].append(p)
                    elif 17 <= hour < 22:
                        time_groups["evening"].append(p)
                    else:
                        time_groups["night"].append(p)

                routines = []
                for period, pats in time_groups.items():
                    if len(pats) < 2:
                        continue

                    # Sort by typical occurrence time
                    pats.sort(key=lambda p: (p.context_tags or {}).get("hour", "12:00"))

                    steps = []
                    for p in pats[:8]:  # max 8 steps per routine
                        steps.append({
                            "pattern_id": p.id,
                            "entity_id": p.entity_id,
                            "domain": p.domain_id,
                            "room_id": p.room_id,
                            "action": p.trigger_state or p.action_taken,
                            "confidence": round(p.confidence, 2),
                        })

                    routines.append({
                        "id": f"routine_{period}",
                        "name_de": {"morning": "Morgenroutine", "daytime": "Tagesroutine",
                                    "evening": "Abendroutine", "night": "Nachtroutine"}[period],
                        "name_en": {"morning": "Morning Routine", "daytime": "Day Routine",
                                    "evening": "Evening Routine", "night": "Night Routine"}[period],
                        "period": period,
                        "step_count": len(steps),
                        "steps": steps,
                        "avg_confidence": round(sum(s["confidence"] for s in steps) / len(steps), 2) if steps else 0,
                    })

                self._cached_routines = routines
                self._last_detect = datetime.now(timezone.utc)
                logger.info(f"Detected {len(routines)} routines ({', '.join(r['period'] for r in routines)})")
                return routines
        except Exception as e:
            logger.error(f"detect_routines error: {e}")
            return self._cached_routines

    def activate_routine(self, routine_id):
        """Manually trigger a routine — execute steps with delays."""
        routine = next((r for r in self._cached_routines if r["id"] == routine_id), None)
        if not routine:
            return {"error": "Routine not found"}

        activated = []
        for step in routine["steps"]:
            entity = step.get("entity_id")
            action = step.get("action")
            if not entity or not action:
                continue
            try:
                domain = entity.split(".")[0]
                if action in ("on", "turn_on"):
                    self.ha.call_service(domain, "turn_on", {"entity_id": entity})
                elif action in ("off", "turn_off"):
                    self.ha.call_service(domain, "turn_off", {"entity_id": entity})
                activated.append(entity)
                _time.sleep(1)  # 1s delay between steps
            except Exception as e:
                logger.error(f"Routine step error {entity}: {e}")

        self.event_bus.emit("routine.activated", {
            "routine_id": routine_id,
            "steps_executed": len(activated),
        })
        logger.info(f"Routine '{routine_id}' activated: {len(activated)} steps")
        return {"success": True, "steps_executed": len(activated)}

    def get_routines(self):
        """Return list of detected routines."""
        return self._cached_routines

    def detect_room_transitions(self):
        """Detect room transition patterns from motion/activity data (#6)."""
        try:
            from models import StateHistory, Room, Device
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.room_transitions"):
                return []

            with self.get_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                # Get motion events grouped by room
                motion_events = session.query(StateHistory).filter(
                    StateHistory.entity_id.like("binary_sensor.%motion%"),
                    StateHistory.new_state == "on",
                    StateHistory.created_at > cutoff
                ).order_by(StateHistory.created_at).all()

                if len(motion_events) < 10:
                    return []

                # Map entities to rooms
                devices = {d.entity_id: d.room_id for d in session.query(Device).filter(Device.room_id.isnot(None)).all()}
                rooms = {r.id: (r.name_de or r.name_en or f"Room {r.id}") for r in session.query(Room).all()}

                # Build transition pairs
                transitions = defaultdict(int)
                prev_room = None
                prev_time = None

                for ev in motion_events:
                    room_id = devices.get(ev.entity_id)
                    if not room_id:
                        continue
                    if prev_room and prev_room != room_id:
                        if prev_time and (ev.created_at - prev_time).total_seconds() < 600:  # within 10 min
                            key = (prev_room, room_id)
                            transitions[key] += 1
                    prev_room = room_id
                    prev_time = ev.created_at

                # Build results
                results = []
                for (from_room, to_room), count in sorted(transitions.items(), key=lambda x: -x[1]):
                    if count < 3:  # min 3 occurrences
                        continue
                    results.append({
                        "from_room_id": from_room,
                        "from_room_name": rooms.get(from_room, f"#{from_room}"),
                        "to_room_id": to_room,
                        "to_room_name": rooms.get(to_room, f"#{to_room}"),
                        "count": count,
                    })

                return results[:20]  # top 20
        except Exception as e:
            logger.error(f"detect_room_transitions error: {e}")
            return []


class MoodEstimator:
    """Estimates household mood from device usage patterns.

    Rule-based, no ML. Heuristics from media, light, activity levels.
    House-level only, no personal profiling.
    """

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self._is_running = False
        self._cached_mood = {"mood": "unknown", "confidence": 0}

    def start(self):
        self._is_running = True
        logger.info("MoodEstimator started")

    def stop(self):
        self._is_running = False
        logger.info("MoodEstimator stopped")

    def estimate(self):
        """Estimate current household mood from device states."""
        if not self._is_running:
            return self._cached_mood
        try:
            from routes.health import is_feature_enabled
            if not is_feature_enabled("phase4.mood_estimate"):
                return {"mood": "unknown", "confidence": 0}

            states = self.ha.get_states() or []
            state_map = {s.get("entity_id", ""): s for s in states}

            # Count active devices by category
            media_active = 0
            lights_on = 0
            lights_dim = 0  # brightness < 40%
            motion_recent = 0
            climate_active = 0

            for eid, s in state_map.items():
                st = s.get("state", "")
                attrs = s.get("attributes", {})

                if eid.startswith("media_player.") and st in ("playing", "on"):
                    media_active += 1

                if eid.startswith("light.") and st == "on":
                    lights_on += 1
                    brightness = attrs.get("brightness", 255)
                    if brightness < 102:  # < 40%
                        lights_dim += 1

                if eid.startswith("binary_sensor.") and attrs.get("device_class") == "motion" and st == "on":
                    motion_recent += 1

                if eid.startswith("climate.") and st not in ("off", "unavailable"):
                    climate_active += 1

            # Determine mood via heuristics
            mood = "neutral"
            confidence = 0.3
            indicators = []

            # Relaxed: media playing + dim lights + little motion
            if media_active > 0 and lights_dim > 0 and motion_recent <= 1:
                mood = "relaxed"
                confidence = 0.7
                indicators = ["media_active", "dim_lights", "low_motion"]

            # Active: lots of motion + many lights on
            elif motion_recent >= 3 and lights_on >= 3:
                mood = "active"
                confidence = 0.7
                indicators = ["high_motion", "many_lights"]

            # Cozy: media + warm lights, no high motion
            elif media_active > 0 and lights_on >= 2 and motion_recent <= 2:
                mood = "cozy"
                confidence = 0.6
                indicators = ["media_active", "warm_lights"]

            # Quiet: few lights, no media, low motion
            elif lights_on <= 1 and media_active == 0 and motion_recent <= 1:
                mood = "quiet"
                confidence = 0.6
                indicators = ["few_lights", "no_media", "low_motion"]

            # Away: no lights, no motion, no media
            elif lights_on == 0 and motion_recent == 0 and media_active == 0:
                mood = "away"
                confidence = 0.8
                indicators = ["no_activity"]

            # Focused: lights on but no media, moderate motion
            elif lights_on >= 2 and media_active == 0 and 1 <= motion_recent <= 2:
                mood = "focused"
                confidence = 0.5
                indicators = ["lights_no_media", "moderate_motion"]

            self._cached_mood = {
                "mood": mood,
                "confidence": round(confidence, 2),
                "indicators": indicators,
                "stats": {
                    "media_active": media_active,
                    "lights_on": lights_on,
                    "lights_dim": lights_dim,
                    "motion_recent": motion_recent,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            return self._cached_mood

        except Exception as e:
            logger.error(f"MoodEstimator error: {e}")
            return self._cached_mood
