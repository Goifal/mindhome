# MindHome - engines/sleep.py | see version.py for version info
"""
Sleep detection, quality tracking, and smart wake-up.
Features: #4 Schlaf-Erkennung, #16 Schlafqualitaet, #25 Sanftes Wecken
"""

import logging
from datetime import datetime, timezone, timedelta

from helpers import get_setting

logger = logging.getLogger("mindhome.engines.sleep")


class SleepDetector:
    """Detects sleep/wake events from sensor data.

    Heuristics: Last activity, lights off, motion sensors inactive.
    Fallback: Light-off + inactivity > 30 min (no motion sensor needed).
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._sleep_active = {}  # user_id -> SleepSession.id

    def start(self):
        self._is_running = True
        logger.info("SleepDetector started")

    def stop(self):
        self._is_running = False
        logger.info("SleepDetector stopped")

    def check(self):
        """Periodic check for sleep/wake state. Called every 5 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import User, SleepSession, StateHistory, Room
            from helpers import get_setting
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.sleep_detection"):
                return

            with self.get_session() as session:
                now = datetime.now(timezone.utc)
                hour = now.hour

                # Only check during plausible sleep window (configurable)
                sleep_start = int(get_setting("phase4.sleep_detection.sleep_window_start", "20"))
                sleep_end = int(get_setting("phase4.sleep_detection.sleep_window_end", "11"))
                if sleep_end <= hour < sleep_start:
                    return

                users = session.query(User).all()
                for user in users:
                    uid = user.id
                    active_session = session.query(SleepSession).filter(
                        SleepSession.user_id == uid,
                        SleepSession.sleep_end.is_(None)
                    ).first()

                    if active_session:
                        # Check for wake-up: motion or light activity
                        if self._detect_wake(session, now):
                            active_session.sleep_end = now
                            duration_h = (now - active_session.sleep_start).total_seconds() / 3600
                            active_session.quality_score = self._calc_quality(
                                session, active_session.sleep_start, now, uid
                            )
                            self._sleep_active.pop(uid, None)
                            self.event_bus.emit("sleep.wake_detected", {
                                "user_id": uid,
                                "session_id": active_session.id,
                                "duration_hours": round(duration_h, 1),
                                "quality": active_session.quality_score,
                            })
                            logger.info(f"Wake detected user={uid} duration={duration_h:.1f}h quality={active_session.quality_score}")
                    else:
                        # Check for sleep onset: bedroom dark + no motion > 30 min
                        if uid not in self._sleep_active and self._detect_sleep(session, now):
                            ss = SleepSession(
                                user_id=uid,
                                sleep_start=now,
                                source="auto",
                            )
                            session.add(ss)
                            session.flush()
                            self._sleep_active[uid] = ss.id
                            self.event_bus.emit("sleep.detected", {
                                "user_id": uid,
                                "session_id": ss.id,
                            })
                            logger.info(f"Sleep detected user={uid}")
        except Exception as e:
            logger.error(f"SleepDetector check error: {e}")

    def _detect_sleep(self, session, now):
        """Heuristic: Bed occupancy sensor OR (lights off + no motion 30 min)."""
        from models import StateHistory

        # Priority 1: Bed occupancy sensor (binary_sensor with device_class=occupancy)
        try:
            states = self.ha.get_states() or []
            bed_sensors = [s for s in states
                           if s.get("entity_id", "").startswith("binary_sensor.")
                           and s.get("attributes", {}).get("device_class") == "occupancy"]
            if bed_sensors:
                # If any bed sensor is "on" (occupied), sleep detected
                occupied = any(s.get("state") == "on" for s in bed_sensors)
                if occupied:
                    logger.debug("Sleep detected via bed occupancy sensor")
                    return True
                return False  # Bed sensors exist but not occupied
        except Exception:
            pass

        # Priority 2: Fallback — no motion + lights off for 30+ min
        cutoff = now - timedelta(minutes=30)
        recent_motion = session.query(StateHistory).filter(
            StateHistory.entity_id.like("binary_sensor.%motion%"),
            StateHistory.new_state == "on",
            StateHistory.created_at > cutoff
        ).count()
        if recent_motion > 0:
            return False

        recent_lights = session.query(StateHistory).filter(
            StateHistory.entity_id.like("light.%"),
            StateHistory.new_state == "on",
            StateHistory.created_at > cutoff
        ).count()
        if recent_lights > 0:
            return False

        # Check HA: bedroom lights currently on?
        try:
            lights_on = [s for s in states if s.get("entity_id", "").startswith("light.")
                         and s.get("state") == "on"
                         and ("schlaf" in s.get("entity_id", "").lower()
                              or "bedroom" in s.get("entity_id", "").lower()
                              or "bed" in s.get("entity_id", "").lower())]
            if lights_on:
                return False
        except Exception:
            pass

        return True

    def _detect_wake(self, session, now):
        """Heuristic: Bed sensor off OR motion/lights in last 5 min."""
        # Priority 1: Bed occupancy sensor turned off (person left bed)
        try:
            states = self.ha.get_states() or []
            bed_sensors = [s for s in states
                           if s.get("entity_id", "").startswith("binary_sensor.")
                           and s.get("attributes", {}).get("device_class") == "occupancy"]
            if bed_sensors:
                all_empty = all(s.get("state") == "off" for s in bed_sensors)
                if all_empty:
                    logger.debug("Wake detected via bed occupancy sensor (all off)")
                    return True
                return False  # Still in bed
        except Exception:
            pass

        # Priority 2: Fallback — motion or lights in last 5 min
        from models import StateHistory
        cutoff = now - timedelta(minutes=5)
        recent_activity = session.query(StateHistory).filter(
            StateHistory.created_at > cutoff,
            (
                (StateHistory.entity_id.like("binary_sensor.%motion%") & (StateHistory.new_state == "on")) |
                (StateHistory.entity_id.like("light.%") & (StateHistory.new_state == "on"))
            )
        ).count()
        return recent_activity >= 2

    def _calc_quality(self, session, start, end, user_id):
        """Calculate sleep quality score 0-100."""
        from models import StateHistory
        score = 80.0  # base score
        duration_h = (end - start).total_seconds() / 3600

        # Duration factor: 7-9h optimal
        if duration_h < 5:
            score -= 25
        elif duration_h < 6:
            score -= 15
        elif duration_h < 7:
            score -= 5
        elif duration_h > 10:
            score -= 10

        # Interruptions: motion events during sleep
        interruptions = session.query(StateHistory).filter(
            StateHistory.entity_id.like("binary_sensor.%motion%"),
            StateHistory.new_state == "on",
            StateHistory.created_at > start,
            StateHistory.created_at < end
        ).count()
        score -= min(interruptions * 3, 30)

        # Temperature factor (if available)
        try:
            temp_readings = session.query(StateHistory).filter(
                StateHistory.entity_id.like("sensor.%temp%"),
                StateHistory.created_at > start,
                StateHistory.created_at < end
            ).all()
            if temp_readings:
                temps = []
                for r in temp_readings:
                    try:
                        temps.append(float(r.new_state))
                    except (ValueError, TypeError):
                        pass
                if temps:
                    avg_temp = sum(temps) / len(temps)
                    # Optimal: 16-20°C
                    if avg_temp < 14 or avg_temp > 24:
                        score -= 15
                    elif avg_temp < 16 or avg_temp > 22:
                        score -= 5
        except Exception:
            pass

        return max(0, min(100, round(score)))

    def get_recent_sessions(self, user_id=None, days=7):
        """Return recent SleepSession entries."""
        try:
            from models import SleepSession
            with self.get_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                q = session.query(SleepSession).filter(SleepSession.created_at > cutoff)
                if user_id:
                    q = q.filter(SleepSession.user_id == user_id)
                sessions = q.order_by(SleepSession.sleep_start.desc()).limit(30).all()
                return [{
                    "id": s.id,
                    "user_id": s.user_id,
                    "sleep_start": s.sleep_start.isoformat() if s.sleep_start else None,
                    "sleep_end": s.sleep_end.isoformat() if s.sleep_end else None,
                    "duration_hours": round((s.sleep_end - s.sleep_start).total_seconds() / 3600, 1) if s.sleep_end and s.sleep_start else None,
                    "quality_score": s.quality_score,
                    "source": s.source,
                    "context": s.context,
                } for s in sessions]
        except Exception as e:
            logger.error(f"get_recent_sessions error: {e}")
            return []


class WakeUpManager:
    """Smart wake-up with gradual light/cover/climate ramp.

    Reads WakeUpConfig per user, ramps devices X minutes before wake time.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_ramps = {}  # config_id -> progress (0.0 - 1.0)

    def start(self):
        self._is_running = True
        logger.info("WakeUpManager started")

    def stop(self):
        self._is_running = False
        self._active_ramps.clear()
        logger.info("WakeUpManager stopped")

    def check(self):
        """Check if any wake-up ramp should start. Called every 5 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import WakeUpConfig, PersonSchedule
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.smart_wakeup"):
                return

            with self.get_session() as session:
                now = datetime.now(timezone.utc)
                configs = session.query(WakeUpConfig).filter(
                    WakeUpConfig.enabled == True,
                    WakeUpConfig.is_active == True
                ).all()

                for cfg in configs:
                    wake_time_str = cfg.wake_time
                    # If linked to schedule, get from PersonSchedule
                    if cfg.linked_to_schedule:
                        ps = session.query(PersonSchedule).filter(
                            PersonSchedule.user_id == cfg.user_id
                        ).first()
                        if ps and ps.time_wake:
                            wake_time_str = ps.time_wake

                    if not wake_time_str:
                        continue

                    # Parse wake time (HH:MM)
                    try:
                        parts = wake_time_str.split(":")
                        wake_h, wake_m = int(parts[0]), int(parts[1])
                    except (ValueError, IndexError):
                        continue

                    # Calculate ramp start
                    ramp_min = cfg.ramp_minutes or 20
                    today = now.replace(hour=wake_h, minute=wake_m, second=0, microsecond=0)
                    ramp_start = today - timedelta(minutes=ramp_min)

                    # Check if we're in the ramp window
                    if ramp_start <= now <= today:
                        elapsed = (now - ramp_start).total_seconds() / 60
                        progress = min(elapsed / ramp_min, 1.0)

                        # Execute ramp
                        self._execute_ramp(cfg, progress)
                    elif now > today and cfg.id in self._active_ramps:
                        # Ramp complete, clean up
                        del self._active_ramps[cfg.id]
        except Exception as e:
            logger.error(f"WakeUpManager check error: {e}")

    def _execute_ramp(self, cfg, progress):
        """Execute wake-up ramp at given progress (0.0 to 1.0)."""
        prev = self._active_ramps.get(cfg.id, -1)
        if progress <= prev:
            return  # Already at this step or beyond
        self._active_ramps[cfg.id] = progress

        try:
            # Light: gradual brightness 0% -> 100%
            if cfg.light_entity:
                brightness = int(progress * 255)
                if brightness > 0:
                    transition = int(get_setting("phase4.smart_wakeup.light_transition_sec", "60"))
                    self.ha.call_service("light", "turn_on", {
                        "entity_id": cfg.light_entity,
                        "brightness": brightness,
                        "transition": transition,
                    })
                    logger.debug(f"WakeUp light {cfg.light_entity} brightness={brightness} ({progress:.0%})")

            # Cover: stepwise opening
            if cfg.cover_entity:
                position = int(progress * 100)
                if position > 0:
                    self.ha.call_service("cover", "set_cover_position", {
                        "entity_id": cfg.cover_entity,
                        "position": position,
                    })
                    logger.debug(f"WakeUp cover {cfg.cover_entity} position={position}%")

            # Climate: gradual temperature raise
            if cfg.climate_entity and progress >= 0.3:
                heating_mode = get_setting("heating_mode", "room_thermostat")
                if heating_mode == "heating_curve":
                    # Heizkurven-Modus: Offset von night_offset (-2) nach 0 rampen
                    night_offset = float(get_setting("heating_curve_night_offset", "-2"))
                    target_offset = night_offset + (progress * abs(night_offset))  # z.B. -2 -> 0
                    target_offset = min(target_offset, 0)  # Nicht ueber 0 hinaus
                    curve_entity = get_setting("heating_curve_entity", cfg.climate_entity)
                    # Aktuellen Sollwert lesen und Offset anwenden
                    states = self.ha.get_states() or []
                    for s in states:
                        if s.get("entity_id") == curve_entity:
                            current = s.get("attributes", {}).get("temperature")
                            if current is not None:
                                base_temp = float(current) - night_offset  # Basis-Temp zurueckrechnen
                                new_temp = base_temp + target_offset
                                self.ha.call_service("climate", "set_temperature", {
                                    "entity_id": curve_entity,
                                    "temperature": round(new_temp, 1),
                                })
                                logger.debug(f"WakeUp climate curve {curve_entity} offset={target_offset:.1f}")
                            break
                else:
                    # Raumthermostat-Modus: Absolute Temperatur 18 -> 21°C
                    target_temp = 18 + (progress * 3)  # 18 -> 21°C
                    self.ha.call_service("climate", "set_temperature", {
                        "entity_id": cfg.climate_entity,
                        "temperature": round(target_temp, 1),
                    })
                    logger.debug(f"WakeUp climate {cfg.climate_entity} temp={target_temp:.1f}")

            if progress >= 1.0:
                self.event_bus.emit("sleep.wakeup_complete", {"user_id": cfg.user_id, "config_id": cfg.id})
                logger.info(f"WakeUp complete for user={cfg.user_id}")

        except Exception as e:
            logger.error(f"WakeUp ramp error config={cfg.id}: {e}")

    def get_configs(self, user_id=None):
        """Return all WakeUpConfig entries."""
        try:
            from models import WakeUpConfig
            with self.get_session() as session:
                q = session.query(WakeUpConfig)
                if user_id:
                    q = q.filter(WakeUpConfig.user_id == user_id)
                configs = q.all()
                return [{
                    "id": c.id,
                    "user_id": c.user_id,
                    "enabled": c.enabled,
                    "wake_time": c.wake_time,
                    "linked_to_schedule": c.linked_to_schedule,
                    "light_entity": c.light_entity,
                    "climate_entity": c.climate_entity,
                    "cover_entity": c.cover_entity,
                    "ramp_minutes": c.ramp_minutes,
                    "is_active": c.is_active,
                } for c in configs]
        except Exception as e:
            logger.error(f"get_configs error: {e}")
            return []
