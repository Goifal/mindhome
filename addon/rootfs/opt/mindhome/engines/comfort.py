# MindHome - engines/comfort.py | see version.py for version info
"""
Comfort scoring, ventilation reminders, and screen time monitoring.
Features: #10 Komfort-Score, #17 Raumklima-Ampel, #18 Lueftungserinnerung, #19 Bildschirmzeit
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("mindhome.engines.comfort")


class ComfortCalculator:
    """Calculates comfort score per room from sensor data.

    Factors: Temperature (20-23C ideal), humidity (40-60%), CO2 (<1000ppm), light.
    Missing sensors get neutral score (50/100) — graceful degradation.
    """

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self._is_running = False
        self._cached_scores = {}  # room_id -> score dict

    def start(self):
        self._is_running = True
        logger.info("ComfortCalculator started")

    def stop(self):
        self._is_running = False
        logger.info("ComfortCalculator stopped")

    def calculate(self):
        """Calculate comfort scores for all rooms. Called every 15 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import Room, Device, ComfortScore
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.comfort_score"):
                return

            with self.get_session() as session:
                rooms = session.query(Room).filter(Room.is_active == True).all()
                states = self.ha.get_states() or []
                state_map = {s.get("entity_id"): s for s in states}

                for room in rooms:
                    devices = session.query(Device).filter(
                        Device.room_id == room.id,
                        Device.is_tracked == True
                    ).all()
                    entity_ids = {d.ha_entity_id for d in devices}

                    factors = {}
                    weights = {}

                    # Temperature factor (weight 35%)
                    temp_score = self._score_temperature(state_map, entity_ids)
                    if temp_score is not None:
                        factors["temp"] = temp_score
                        weights["temp"] = 0.35
                    else:
                        factors["temp"] = 50
                        weights["temp"] = 0.15

                    # Humidity factor (weight 25%)
                    hum_score = self._score_humidity(state_map, entity_ids)
                    if hum_score is not None:
                        factors["humidity"] = hum_score
                        weights["humidity"] = 0.25
                    else:
                        factors["humidity"] = 50
                        weights["humidity"] = 0.10

                    # CO2 factor (weight 25%)
                    co2_score = self._score_co2(state_map, entity_ids)
                    if co2_score is not None:
                        factors["co2"] = co2_score
                        weights["co2"] = 0.25
                    else:
                        factors["co2"] = 50
                        weights["co2"] = 0.10

                    # Light factor (weight 15%)
                    light_score = self._score_light(state_map, entity_ids)
                    if light_score is not None:
                        factors["light"] = light_score
                        weights["light"] = 0.15
                    else:
                        factors["light"] = 50
                        weights["light"] = 0.05

                    # Weighted average
                    total_weight = sum(weights.values())
                    if total_weight > 0:
                        score = sum(factors[k] * weights[k] for k in factors) / total_weight
                    else:
                        score = 50.0

                    score = max(0, min(100, round(score)))

                    # Store in DB
                    cs = ComfortScore(
                        room_id=room.id,
                        score=score,
                        factors=factors,
                    )
                    session.add(cs)

                    self._cached_scores[room.id] = {
                        "room_id": room.id,
                        "room_name": room.name,
                        "score": score,
                        "factors": factors,
                        "traffic_light": self._traffic_light(score),
                        "factor_lights": {
                            k: self._traffic_light(v) for k, v in factors.items()
                        },
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

                logger.info(f"Comfort scores calculated for {len(rooms)} rooms")
        except Exception as e:
            logger.error(f"ComfortCalculator calculate error: {e}")

    def _score_temperature(self, state_map, entity_ids):
        """Score temperature 0-100. Optimal: 20-23°C."""
        for eid in entity_ids:
            if "temp" in eid.lower() and eid.startswith("sensor."):
                s = state_map.get(eid)
                if s:
                    try:
                        temp = float(s.get("state", ""))
                        if 20 <= temp <= 23:
                            return 100
                        elif 18 <= temp < 20:
                            return 80 - (20 - temp) * 10
                        elif 23 < temp <= 25:
                            return 80 - (temp - 23) * 10
                        elif 16 <= temp < 18:
                            return 40
                        elif 25 < temp <= 28:
                            return 40
                        else:
                            return max(0, 20 - abs(temp - 21.5) * 2)
                    except (ValueError, TypeError):
                        pass
        # Try HA climate entities for room
        for eid in entity_ids:
            if eid.startswith("climate."):
                s = state_map.get(eid)
                if s:
                    try:
                        temp = float(s.get("attributes", {}).get("current_temperature", ""))
                        if 20 <= temp <= 23:
                            return 100
                        elif 18 <= temp <= 25:
                            return 70
                        else:
                            return 30
                    except (ValueError, TypeError):
                        pass
        return None

    def _score_humidity(self, state_map, entity_ids):
        """Score humidity 0-100. Optimal: 40-60%."""
        for eid in entity_ids:
            if "humid" in eid.lower() and eid.startswith("sensor."):
                s = state_map.get(eid)
                if s:
                    try:
                        hum = float(s.get("state", ""))
                        if 40 <= hum <= 60:
                            return 100
                        elif 30 <= hum < 40:
                            return 70
                        elif 60 < hum <= 70:
                            return 70
                        elif 20 <= hum < 30:
                            return 40
                        elif 70 < hum <= 80:
                            return 40
                        else:
                            return 10
                    except (ValueError, TypeError):
                        pass
        return None

    def _score_co2(self, state_map, entity_ids):
        """Score CO2 0-100. Optimal: <800ppm."""
        for eid in entity_ids:
            if "co2" in eid.lower() and eid.startswith("sensor."):
                s = state_map.get(eid)
                if s:
                    try:
                        co2 = float(s.get("state", ""))
                        if co2 < 600:
                            return 100
                        elif co2 < 800:
                            return 90
                        elif co2 < 1000:
                            return 70
                        elif co2 < 1200:
                            return 50
                        elif co2 < 1500:
                            return 30
                        else:
                            return 10
                    except (ValueError, TypeError):
                        pass
        return None

    def _score_light(self, state_map, entity_ids):
        """Score light 0-100 based on illuminance sensor."""
        for eid in entity_ids:
            if ("lux" in eid.lower() or "illumin" in eid.lower()) and eid.startswith("sensor."):
                s = state_map.get(eid)
                if s:
                    try:
                        lux = float(s.get("state", ""))
                        if 300 <= lux <= 500:
                            return 100
                        elif 200 <= lux < 300 or 500 < lux <= 750:
                            return 80
                        elif 100 <= lux < 200:
                            return 60
                        elif lux < 100:
                            return 40
                        else:
                            return 50
                    except (ValueError, TypeError):
                        pass
        return None

    @staticmethod
    def _traffic_light(score):
        """Return traffic light color for a score."""
        if score >= 80:
            return "green"
        elif score >= 50:
            return "yellow"
        return "red"

    def get_scores(self):
        """Return current comfort scores per room."""
        if self._cached_scores:
            return list(self._cached_scores.values())
        # Fallback: load last scores from DB
        try:
            from models import ComfortScore, Room
            with self.get_session() as session:
                rooms = session.query(Room).filter(Room.is_active == True).all()
                result = []
                for room in rooms:
                    cs = session.query(ComfortScore).filter(
                        ComfortScore.room_id == room.id
                    ).order_by(ComfortScore.created_at.desc()).first()
                    if cs:
                        score = cs.score
                        factors = cs.factors or {}
                        result.append({
                            "room_id": room.id,
                            "room_name": room.name,
                            "score": score,
                            "factors": factors,
                            "traffic_light": self._traffic_light(score),
                            "factor_lights": {
                                k: self._traffic_light(v) for k, v in factors.items()
                            },
                            "updated_at": cs.created_at.isoformat() if cs.created_at else None,
                        })
                return result
        except Exception as e:
            logger.error(f"get_scores error: {e}")
            return []

    def get_history(self, room_id, days=7):
        """Return comfort score history for a room."""
        try:
            from models import ComfortScore
            with self.get_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                scores = session.query(ComfortScore).filter(
                    ComfortScore.room_id == room_id,
                    ComfortScore.created_at > cutoff
                ).order_by(ComfortScore.created_at).all()
                return [{
                    "score": s.score,
                    "factors": s.factors,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                } for s in scores]
        except Exception as e:
            logger.error(f"get_history error: {e}")
            return []

    def get_traffic_lights(self):
        """Return traffic light status per room (#17 Raumklima-Ampel)."""
        scores = self.get_scores()
        return [{
            "room_id": s["room_id"],
            "room_name": s["room_name"],
            "overall": s["traffic_light"],
            "score": s["score"],
            "factors": s.get("factor_lights", {}),
        } for s in scores]


class VentilationMonitor:
    """Monitors air quality and sends ventilation reminders.

    Checks: CO2 > threshold OR last ventilation > interval.
    Tracks window openings as 'ventilated' events.
    Fallback: Timer-based reminders when no CO2 sensor present.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._cached_status = {}  # room_id -> status dict
        self._reminded = {}  # room_id -> last reminder time

    def start(self):
        self._is_running = True
        logger.info("VentilationMonitor started")

    def stop(self):
        self._is_running = False
        logger.info("VentilationMonitor stopped")

    def check(self):
        """Check ventilation status for all rooms. Called every 10 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import Room, Device, VentilationReminder
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.ventilation_reminder"):
                return

            with self.get_session() as session:
                rooms = session.query(Room).filter(Room.is_active == True).all()
                states = self.ha.get_states() or []
                state_map = {s.get("entity_id"): s for s in states}
                now = datetime.now(timezone.utc)

                for room in rooms:
                    devices = session.query(Device).filter(
                        Device.room_id == room.id,
                        Device.is_tracked == True
                    ).all()
                    entity_ids = {d.ha_entity_id for d in devices}

                    # Get or create VentilationReminder config
                    vr = session.query(VentilationReminder).filter(
                        VentilationReminder.room_id == room.id
                    ).first()
                    if not vr:
                        vr = VentilationReminder(room_id=room.id)
                        session.add(vr)
                        session.flush()

                    if not vr.is_active:
                        continue

                    # Check window contact sensors for ventilation tracking
                    window_open = False
                    for eid in entity_ids:
                        if eid.startswith("binary_sensor.") and ("fenster" in eid.lower() or "window" in eid.lower()):
                            s = state_map.get(eid)
                            if s and s.get("state") == "on":
                                window_open = True
                                break

                    # If window is open now, mark as ventilated
                    if window_open:
                        vr.last_ventilated = now
                        self._cached_status[room.id] = {
                            "room_id": room.id,
                            "room_name": room.name,
                            "status": "ventilating",
                            "window_open": True,
                            "co2_ppm": None,
                            "needs_ventilation": False,
                            "last_ventilated": now.isoformat(),
                            "reminder_sent": False,
                        }
                        self._reminded.pop(room.id, None)
                        continue

                    # Check CO2 level
                    co2_ppm = None
                    for eid in entity_ids:
                        if "co2" in eid.lower() and eid.startswith("sensor."):
                            s = state_map.get(eid)
                            if s:
                                try:
                                    co2_ppm = float(s.get("state", ""))
                                except (ValueError, TypeError):
                                    pass

                    # Determine if ventilation needed
                    needs_ventilation = False
                    reason = None

                    if co2_ppm is not None and co2_ppm > vr.co2_threshold:
                        needs_ventilation = True
                        reason = f"CO2 {int(co2_ppm)} ppm > {vr.co2_threshold} ppm"
                    elif vr.last_ventilated:
                        mins_since = (now - vr.last_ventilated).total_seconds() / 60
                        if mins_since > vr.reminder_interval_min:
                            needs_ventilation = True
                            reason = f"Letzte Lueftung vor {int(mins_since)} Min"
                    else:
                        # Never ventilated tracked
                        needs_ventilation = True
                        reason = "Noch keine Lueftung erfasst"

                    # Send reminder (max once per 30 min per room)
                    reminder_sent = False
                    if needs_ventilation:
                        last_remind = self._reminded.get(room.id)
                        if not last_remind or (now - last_remind).total_seconds() > 1800:
                            self._reminded[room.id] = now
                            reminder_sent = True
                            self.event_bus.emit("ventilation.reminder", {
                                "room_id": room.id,
                                "room_name": room.name,
                                "reason": reason,
                                "co2_ppm": co2_ppm,
                            })
                            logger.info(f"Ventilation reminder: {room.name} — {reason}")

                    self._cached_status[room.id] = {
                        "room_id": room.id,
                        "room_name": room.name,
                        "status": "needs_ventilation" if needs_ventilation else "ok",
                        "window_open": False,
                        "co2_ppm": int(co2_ppm) if co2_ppm is not None else None,
                        "co2_threshold": vr.co2_threshold,
                        "needs_ventilation": needs_ventilation,
                        "reason": reason if needs_ventilation else None,
                        "last_ventilated": vr.last_ventilated.isoformat() if vr.last_ventilated else None,
                        "reminder_interval_min": vr.reminder_interval_min,
                        "reminder_sent": reminder_sent,
                    }

        except Exception as e:
            logger.error(f"VentilationMonitor check error: {e}")

    def get_status(self):
        """Return ventilation status per room."""
        if self._cached_status:
            return list(self._cached_status.values())
        # Fallback from DB
        try:
            from models import Room, VentilationReminder
            with self.get_session() as session:
                rooms = session.query(Room).filter(Room.is_active == True).all()
                result = []
                for room in rooms:
                    vr = session.query(VentilationReminder).filter(
                        VentilationReminder.room_id == room.id
                    ).first()
                    result.append({
                        "room_id": room.id,
                        "room_name": room.name,
                        "status": "unknown",
                        "window_open": False,
                        "co2_ppm": None,
                        "needs_ventilation": False,
                        "last_ventilated": vr.last_ventilated.isoformat() if vr and vr.last_ventilated else None,
                        "reminder_interval_min": vr.reminder_interval_min if vr else 120,
                        "co2_threshold": vr.co2_threshold if vr else 1000,
                    })
                return result
        except Exception as e:
            logger.error(f"get_status error: {e}")
            return []

    def update_config(self, room_id, data):
        """Update ventilation config for a room."""
        try:
            from models import VentilationReminder
            with self.get_session() as session:
                vr = session.query(VentilationReminder).filter(
                    VentilationReminder.room_id == room_id
                ).first()
                if not vr:
                    return {"error": "Room not found"}
                for key in ["reminder_interval_min", "co2_threshold", "is_active"]:
                    if key in data:
                        setattr(vr, key, data[key])
                return {"success": True}
        except Exception as e:
            logger.error(f"update_config error: {e}")
            return {"error": str(e)}


class ScreenTimeMonitor:
    """Tracks media player usage and sends reminders after configured limits.

    Monitors media_player entities, counts active time, notifies per user config.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_sessions = {}  # entity_id -> start_time
        self._today_minutes = {}  # entity_id -> accumulated minutes today
        self._last_reminder = {}  # user_id -> last reminder time
        self._last_reset_date = None

    def start(self):
        self._is_running = True
        logger.info("ScreenTimeMonitor started")

    def stop(self):
        self._is_running = False
        logger.info("ScreenTimeMonitor stopped")

    def check(self):
        """Check screen time for all configured entities. Called every 5 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import ScreenTimeConfig
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.screen_time"):
                return

            now = datetime.now(timezone.utc)

            # Reset daily counters
            today = now.date()
            if self._last_reset_date != today:
                self._today_minutes.clear()
                self._last_reminder.clear()
                self._last_reset_date = today

            states = self.ha.get_states() or []
            state_map = {s.get("entity_id"): s for s in states}

            with self.get_session() as session:
                configs = session.query(ScreenTimeConfig).filter(
                    ScreenTimeConfig.is_active == True
                ).all()

                for cfg in configs:
                    monitored = cfg.entity_ids or []
                    if not monitored:
                        # Auto-discover media_player entities
                        monitored = [eid for eid in state_map if eid.startswith("media_player.")]

                    for eid in monitored:
                        s = state_map.get(eid)
                        if not s:
                            continue

                        is_active = s.get("state") in ("playing", "on", "paused")

                        if is_active:
                            if eid not in self._active_sessions:
                                self._active_sessions[eid] = now
                            else:
                                # Accumulate time
                                elapsed = (now - self._active_sessions[eid]).total_seconds() / 60
                                self._today_minutes[eid] = self._today_minutes.get(eid, 0) + elapsed
                                self._active_sessions[eid] = now
                        else:
                            if eid in self._active_sessions:
                                elapsed = (now - self._active_sessions[eid]).total_seconds() / 60
                                self._today_minutes[eid] = self._today_minutes.get(eid, 0) + elapsed
                                del self._active_sessions[eid]

                    # Check if user exceeded limit
                    total_mins = sum(self._today_minutes.get(eid, 0) for eid in monitored)
                    if total_mins >= cfg.daily_limit_min:
                        last_r = self._last_reminder.get(cfg.user_id)
                        interval = cfg.reminder_interval_min or 60
                        if not last_r or (now - last_r).total_seconds() > interval * 60:
                            self._last_reminder[cfg.user_id] = now
                            self.event_bus.emit("screen_time.limit_reached", {
                                "user_id": cfg.user_id,
                                "total_minutes": round(total_mins),
                                "limit_minutes": cfg.daily_limit_min,
                            })
                            logger.info(f"Screen time limit: User {cfg.user_id} at {round(total_mins)} min (limit {cfg.daily_limit_min})")

        except Exception as e:
            logger.error(f"ScreenTimeMonitor check error: {e}")

    def get_usage(self, user_id=None):
        """Return current screen time data."""
        try:
            from models import ScreenTimeConfig
            with self.get_session() as session:
                query = session.query(ScreenTimeConfig).filter(ScreenTimeConfig.is_active == True)
                if user_id:
                    query = query.filter(ScreenTimeConfig.user_id == user_id)
                configs = query.all()

                results = []
                for cfg in configs:
                    monitored = cfg.entity_ids or []
                    sessions = []
                    total = 0
                    for eid in monitored:
                        mins = round(self._today_minutes.get(eid, 0))
                        total += mins
                        is_active = eid in self._active_sessions
                        sessions.append({
                            "entity_id": eid,
                            "minutes_today": mins,
                            "is_active": is_active,
                        })

                    # Also check auto-discovered
                    if not monitored:
                        states = self.ha.get_states() or []
                        for s in states:
                            eid = s.get("entity_id", "")
                            if eid.startswith("media_player."):
                                mins = round(self._today_minutes.get(eid, 0))
                                total += mins
                                sessions.append({
                                    "entity_id": eid,
                                    "minutes_today": mins,
                                    "is_active": eid in self._active_sessions,
                                })

                    results.append({
                        "user_id": cfg.user_id,
                        "today_minutes": round(total),
                        "daily_limit_min": cfg.daily_limit_min,
                        "remaining_minutes": max(0, cfg.daily_limit_min - round(total)),
                        "sessions": sessions,
                    })

                return results if results else [{"today_minutes": 0, "sessions": [], "daily_limit_min": 180}]

        except Exception as e:
            logger.error(f"get_usage error: {e}")
            return [{"today_minutes": 0, "sessions": []}]

    def get_config(self, user_id=None):
        """Return screen time configs."""
        try:
            from models import ScreenTimeConfig
            with self.get_session() as session:
                query = session.query(ScreenTimeConfig)
                if user_id:
                    query = query.filter(ScreenTimeConfig.user_id == user_id)
                configs = query.all()
                return [{
                    "id": c.id,
                    "user_id": c.user_id,
                    "entity_ids": c.entity_ids,
                    "daily_limit_min": c.daily_limit_min,
                    "reminder_interval_min": c.reminder_interval_min,
                    "is_active": c.is_active,
                } for c in configs]
        except Exception as e:
            logger.error(f"get_config error: {e}")
            return []
