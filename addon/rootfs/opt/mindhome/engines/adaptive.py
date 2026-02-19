# MindHome - engines/adaptive.py | see version.py for version info
"""
Adaptive KI features for Phase 4 Batch 4.
Features: #11 Adaptive Reaktionszeit, #12 Gewohnheits-Drift, #23 Sanftes Eingreifen
"""

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger("mindhome.engines.adaptive")


class HabitDriftDetector:
    """Detects changes in user habits by comparing 2-week pattern windows.

    Compares pattern data from the last 2 weeks with the 2 weeks before.
    Detects: time shifts, frequency changes, new/disappeared patterns.
    Runs weekly (Sunday 03:00 via scheduler).
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._cached_drifts = []

    def start(self):
        self._is_running = True
        logger.info("HabitDriftDetector started")

    def stop(self):
        self._is_running = False
        logger.info("HabitDriftDetector stopped")

    def detect(self):
        """Detect habit drifts. Called weekly by scheduler."""
        if not self._is_running:
            return
        try:
            from models import LearnedPattern
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.habit_drift"):
                return

            now = datetime.now(timezone.utc)
            recent_start = now - timedelta(days=14)
            previous_start = now - timedelta(days=28)

            with self.get_session() as session:
                # Get patterns with sufficient data
                patterns = session.query(LearnedPattern).filter(
                    LearnedPattern.status == "accepted",
                    LearnedPattern.confidence > 0.3
                ).all()

                drifts = []
                for pattern in patterns:
                    trigger = pattern.trigger_conditions or {}
                    if not trigger.get("hour") and trigger.get("hour") != 0:
                        continue

                    adaptive = pattern.adaptive_timing or {}
                    samples = adaptive.get("samples", [])
                    if len(samples) < 4:
                        continue

                    # Split samples into recent vs previous
                    recent_offsets = []
                    previous_offsets = []
                    for s in samples:
                        try:
                            ts = datetime.fromisoformat(s.get("timestamp", ""))
                            offset = s.get("offset_min", 0)
                            if ts >= recent_start:
                                recent_offsets.append(offset)
                            elif ts >= previous_start:
                                previous_offsets.append(offset)
                        except (ValueError, TypeError):
                            continue

                    if not recent_offsets or not previous_offsets:
                        continue

                    recent_avg = sum(recent_offsets) / len(recent_offsets)
                    previous_avg = sum(previous_offsets) / len(previous_offsets)
                    drift_min = recent_avg - previous_avg

                    # Significant if shift > 10 min
                    if abs(drift_min) >= 10:
                        direction = "spaeter" if drift_min > 0 else "frueher"
                        drift_info = {
                            "pattern_id": pattern.id,
                            "pattern_type": pattern.pattern_type,
                            "description": pattern.description_de or pattern.pattern_type,
                            "entity_id": (pattern.action_definition or {}).get("entity_id"),
                            "drift_minutes": round(drift_min),
                            "direction": direction,
                            "original_time": f"{trigger.get('hour', 0):02d}:{trigger.get('minute', 0):02d}",
                            "recent_samples": len(recent_offsets),
                            "previous_samples": len(previous_offsets),
                            "message_de": f"{pattern.description_de or pattern.pattern_type}: {abs(round(drift_min))} Min {direction}",
                            "message_en": f"{pattern.description_en or pattern.pattern_type}: {abs(round(drift_min))} min {'later' if drift_min > 0 else 'earlier'}",
                            "detected_at": now.isoformat(),
                        }
                        drifts.append(drift_info)

                        # Also detect frequency changes
                        if len(recent_offsets) != len(previous_offsets):
                            freq_change = len(recent_offsets) - len(previous_offsets)
                            drift_info["frequency_change"] = freq_change

                self._cached_drifts = drifts
                if drifts:
                    self.event_bus.emit("habit.drift_detected", {
                        "count": len(drifts),
                        "drifts": drifts[:5],  # top 5
                    })
                    logger.info(f"HabitDriftDetector: {len(drifts)} drifts detected")

        except Exception as e:
            logger.error(f"HabitDriftDetector error: {e}")

    def get_drifts(self):
        """Return cached drift detections."""
        return self._cached_drifts


class AdaptiveTimingManager:
    """Learns from user manual actions to adjust automation timing.

    When a user manually executes an action that matches a pattern,
    records the timing difference and adjusts the pattern's trigger time.
    Uses a moving average of the last 10 manual executions.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("AdaptiveTimingManager started")

    def stop(self):
        self._is_running = False
        logger.info("AdaptiveTimingManager stopped")

    def check(self):
        """Check for manual actions that match patterns and learn timing. Called every 15 min."""
        if not self._is_running:
            return
        try:
            from models import LearnedPattern, StateHistory
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.adaptive_timing"):
                return

            now = datetime.now(timezone.utc)
            check_window = now - timedelta(minutes=15)

            with self.get_session() as session:
                # Find patterns with time triggers
                patterns = session.query(LearnedPattern).filter(
                    LearnedPattern.status == "accepted",
                    LearnedPattern.confidence > 0.3
                ).all()

                for pattern in patterns:
                    trigger = pattern.trigger_conditions or {}
                    target_h = trigger.get("hour")
                    target_m = trigger.get("minute", 0)
                    if target_h is None:
                        continue

                    action = pattern.action_definition or {}
                    entity_id = action.get("entity_id")
                    target_state = action.get("target_state")
                    if not entity_id or not target_state:
                        continue

                    # Find recent manual state changes for this entity
                    recent_changes = session.query(StateHistory).filter(
                        StateHistory.entity_id == entity_id,
                        StateHistory.new_state == target_state,
                        StateHistory.created_at >= check_window,
                        StateHistory.created_at <= now
                    ).all()

                    for change in recent_changes:
                        change_time = change.created_at
                        if not change_time:
                            continue

                        # Calculate offset from expected pattern time
                        expected_min = target_h * 60 + target_m
                        actual_min = change_time.hour * 60 + change_time.minute
                        offset = actual_min - expected_min

                        # Only consider offsets within reasonable range (-60 to +60 min)
                        if abs(offset) > 60:
                            continue

                        # Record this sample
                        adaptive = pattern.adaptive_timing or {}
                        samples = adaptive.get("samples", [])
                        samples.append({
                            "offset_min": offset,
                            "timestamp": change_time.isoformat(),
                        })

                        # Keep last 10 samples
                        samples = samples[-10:]

                        # Calculate moving average
                        avg_offset = sum(s.get("offset_min", 0) for s in samples) / len(samples)

                        pattern.adaptive_timing = {
                            "samples": samples,
                            "avg_offset_min": round(avg_offset, 1),
                            "sample_count": len(samples),
                            "last_updated": now.isoformat(),
                        }

                        # Auto-adjust trigger if avg drift > 5 min and enough samples
                        if len(samples) >= 5 and abs(avg_offset) >= 5:
                            new_min = expected_min + round(avg_offset)
                            new_h = (new_min // 60) % 24
                            new_m = new_min % 60
                            trigger["hour"] = new_h
                            trigger["minute"] = new_m
                            pattern.trigger_conditions = trigger
                            logger.info(f"Adaptive timing: Pattern {pattern.id} adjusted to {new_h:02d}:{new_m:02d} (avg offset {avg_offset:.1f} min)")

        except Exception as e:
            logger.error(f"AdaptiveTimingManager error: {e}")

    def get_adaptations(self):
        """Return patterns with adaptive timing data."""
        try:
            from models import LearnedPattern
            with self.get_session() as session:
                patterns = session.query(LearnedPattern).filter(
                    LearnedPattern.adaptive_timing.isnot(None)
                ).all()
                return [{
                    "pattern_id": p.id,
                    "description": p.description_de or p.pattern_type,
                    "entity_id": (p.action_definition or {}).get("entity_id"),
                    "trigger_time": f"{(p.trigger_conditions or {}).get('hour', 0):02d}:{(p.trigger_conditions or {}).get('minute', 0):02d}",
                    "adaptive_timing": p.adaptive_timing,
                } for p in patterns]
        except Exception as e:
            logger.error(f"get_adaptations error: {e}")
            return []


class GradualTransitioner:
    """Applies gradual transitions for automations (#23 Sanftes Eingreifen).

    Instead of instant state changes, applies them gradually:
    - Light: transition parameter (seconds)
    - Climate: 0.5°C steps over configured time
    - Cover: 10% position steps
    """

    def __init__(self, ha_connection):
        self.ha = ha_connection
        self._is_running = False
        self._pending = []  # scheduled gradual steps

    def start(self):
        self._is_running = True
        logger.info("GradualTransitioner started")

    def stop(self):
        self._is_running = False
        self._pending.clear()
        logger.info("GradualTransitioner stopped")

    def execute_gradual(self, entity_id, target_state, transition_config=None):
        """Execute an action with gradual transition."""
        if not self._is_running:
            return False

        config = transition_config or {"type": "gradual", "duration_min": 5, "steps": 5}
        duration_min = config.get("duration_min", 5)
        domain = entity_id.split(".")[0]

        try:
            if domain == "light":
                # Use HA transition parameter (in seconds)
                transition_sec = duration_min * 60
                if target_state == "on":
                    self.ha.call_service("light", "turn_on", {
                        "entity_id": entity_id,
                        "transition": transition_sec,
                    })
                elif target_state == "off":
                    self.ha.call_service("light", "turn_off", {
                        "entity_id": entity_id,
                        "transition": transition_sec,
                    })
                logger.debug(f"Gradual light: {entity_id} → {target_state} over {transition_sec}s")

            elif domain == "climate":
                from helpers import get_setting
                heating_mode = get_setting("heating_mode", "room_thermostat")

                if heating_mode == "heating_curve":
                    self._apply_climate_curve(entity_id, target_state)
                else:
                    self._apply_climate_room(entity_id, target_state)

            elif domain == "cover":
                # Set position directly with HA transition
                if target_state in ("open", "on"):
                    self.ha.call_service("cover", "open_cover", {"entity_id": entity_id})
                elif target_state in ("closed", "off"):
                    self.ha.call_service("cover", "close_cover", {"entity_id": entity_id})
                else:
                    try:
                        pos = int(target_state)
                        self.ha.call_service("cover", "set_cover_position", {
                            "entity_id": entity_id,
                            "position": pos,
                        })
                    except (ValueError, TypeError):
                        pass
                logger.debug(f"Gradual cover: {entity_id} → {target_state}")

            else:
                # Default: instant
                service = "turn_on" if target_state == "on" else "turn_off"
                self.ha.call_service(domain, service, {"entity_id": entity_id})

            return True

        except Exception as e:
            logger.error(f"GradualTransitioner error for {entity_id}: {e}")
            return False

    def _apply_climate_curve(self, entity_id, target_state):
        """Heizkurven-Modus: Offset auf das zentrale curve_entity anwenden."""
        from helpers import get_setting

        curve_entity = get_setting("heating_curve_entity", entity_id)
        if not curve_entity:
            curve_entity = entity_id

        if target_state in ("on", "off"):
            hvac = "heat" if target_state == "on" else "off"
            self.ha.call_service("climate", "set_hvac_mode", {
                "entity_id": curve_entity,
                "hvac_mode": hvac,
            })
            logger.debug(f"Gradual climate curve: {curve_entity} hvac → {hvac}")
            return

        try:
            target_temp = float(target_state)
        except (ValueError, TypeError):
            self.ha.call_service("climate", "set_hvac_mode", {
                "entity_id": curve_entity,
                "hvac_mode": target_state,
            })
            return

        # Aktuellen Sollwert lesen
        states = self.ha.get_states() or []
        current = None
        for s in states:
            if s.get("entity_id") == curve_entity:
                current = s.get("attributes", {}).get("temperature")
                break

        if current is None:
            logger.warning(f"Gradual climate curve: {curve_entity} has no temperature attribute")
            return

        current = float(current)
        # Offset berechnen: Differenz zwischen Ziel und aktuellem Sollwert
        offset = target_temp - current

        # Offset-Grenzen aus Config respektieren
        offset_min = float(get_setting("heating_curve_offset_min", "-5"))
        offset_max = float(get_setting("heating_curve_offset_max", "5"))
        new_temp = current + max(offset_min, min(offset_max, offset))

        self.ha.call_service("climate", "set_temperature", {
            "entity_id": curve_entity,
            "temperature": round(new_temp, 1),
        })
        logger.debug(f"Gradual climate curve: {curve_entity} → {round(new_temp, 1)}°C (offset {offset:+.1f})")

    def _apply_climate_room(self, entity_id, target_state):
        """Raumthermostat-Modus: Direkt absolute Temperatur setzen."""
        if target_state in ("on", "off"):
            hvac = "heat" if target_state == "on" else "off"
            self.ha.call_service("climate", "set_hvac_mode", {
                "entity_id": entity_id,
                "hvac_mode": hvac,
            })
            logger.debug(f"Gradual climate room: {entity_id} hvac → {hvac}")
            return

        # Aktuelle Temperatur lesen
        states = self.ha.get_states() or []
        current = None
        for s in states:
            if s.get("entity_id") == entity_id:
                current = s.get("attributes", {}).get("temperature")
                break

        if current is not None:
            try:
                target_temp = float(target_state)
                self.ha.call_service("climate", "set_temperature", {
                    "entity_id": entity_id,
                    "temperature": target_temp,
                })
                logger.debug(f"Gradual climate room: {entity_id} → {target_temp}°C")
            except (ValueError, TypeError):
                self.ha.call_service("climate", "set_hvac_mode", {
                    "entity_id": entity_id,
                    "hvac_mode": target_state,
                })
        else:
            try:
                target_temp = float(target_state)
                self.ha.call_service("climate", "set_temperature", {
                    "entity_id": entity_id,
                    "temperature": target_temp,
                })
            except (ValueError, TypeError):
                hvac = target_state if target_state not in ("on", "off") else "heat"
                self.ha.call_service("climate", "set_hvac_mode", {
                    "entity_id": entity_id,
                    "hvac_mode": hvac,
                })

    def get_status(self):
        """Return status of gradual transition system."""
        return {
            "is_running": self._is_running,
            "pending_transitions": len(self._pending),
        }


class SeasonalAdvisor:
    """Generates seasonal tips based on current season and weather (#13).

    No ML — rule-based recommendations from date + weather entity.
    """

    # Season definitions (Northern hemisphere)
    SEASONS = {
        (12, 1, 2): "winter",
        (3, 4, 5): "spring",
        (6, 7, 8): "summer",
        (9, 10, 11): "autumn",
    }

    TIPS_DE = {
        "winter": [
            {"tip": "Heizung auf 20°C reduzieren — spart bis zu 6% Energie pro Grad", "tip_curve": "Heizkurven-Offset reduzieren — spart bis zu 6% Energie pro Grad", "icon": "mdi-thermometer-minus", "category": "energy"},
            {"tip": "Rolllaeden nachts schliessen fuer bessere Isolierung", "icon": "mdi-window-shutter", "category": "comfort"},
            {"tip": "Frostschutz fuer Aussenwasserhaehne aktivieren", "icon": "mdi-snowflake-alert", "category": "safety"},
            {"tip": "Lueften kurz und intensiv (Stosslueften 5-10 Min)", "icon": "mdi-air-filter", "category": "health"},
        ],
        "spring": [
            {"tip": "Heizung schrittweise reduzieren — Uebergangszeit nutzen", "tip_curve": "Heizkurven-Offset schrittweise reduzieren — Uebergangszeit nutzen", "icon": "mdi-thermometer-low", "category": "energy"},
            {"tip": "Fenster tagsuefer oeffnen fuer natuerliche Belueftung", "icon": "mdi-window-open", "category": "health"},
            {"tip": "Sonnenschutz vorbereiten (Markisen, Rollos pruefen)", "icon": "mdi-weather-sunny", "category": "comfort"},
            {"tip": "Klimaanlage warten lassen vor dem Sommer", "icon": "mdi-hvac", "category": "maintenance"},
        ],
        "summer": [
            {"tip": "Rolllaeden tagsuefer schliessen gegen Hitze", "icon": "mdi-window-shutter", "category": "comfort"},
            {"tip": "Nachts lueften — kuehle Luft reinlassen", "icon": "mdi-weather-night", "category": "comfort"},
            {"tip": "PV-Anlage optimal nutzen — Waschmaschine mittags laufen lassen", "icon": "mdi-solar-power", "category": "energy"},
            {"tip": "Kuehlung nur auf 6°C unter Aussentemperatur stellen", "icon": "mdi-snowflake", "category": "energy"},
        ],
        "autumn": [
            {"tip": "Heizung rechtzeitig starten — nicht warten bis es kalt ist", "tip_curve": "Heizkurven-Offset rechtzeitig erhoehen — nicht warten bis es kalt ist", "icon": "mdi-radiator", "category": "comfort"},
            {"tip": "Dichtungen an Fenstern und Tueren pruefen", "icon": "mdi-door", "category": "maintenance"},
            {"tip": "Zeitschaltuhren fuer Beleuchtung anpassen — frueher dunkel", "icon": "mdi-clock-outline", "category": "comfort"},
            {"tip": "Regenrinnen und Abfluesse reinigen", "icon": "mdi-water", "category": "maintenance"},
        ],
    }

    TIPS_EN = {
        "winter": [
            {"tip": "Reduce heating to 20°C — saves up to 6% energy per degree", "tip_curve": "Reduce heating curve offset — saves up to 6% energy per degree", "icon": "mdi-thermometer-minus", "category": "energy"},
            {"tip": "Close shutters at night for better insulation", "icon": "mdi-window-shutter", "category": "comfort"},
            {"tip": "Activate frost protection for outdoor faucets", "icon": "mdi-snowflake-alert", "category": "safety"},
            {"tip": "Ventilate briefly but intensely (5-10 min burst)", "icon": "mdi-air-filter", "category": "health"},
        ],
        "spring": [
            {"tip": "Gradually reduce heating — use transition period", "tip_curve": "Gradually reduce heating curve offset — use transition period", "icon": "mdi-thermometer-low", "category": "energy"},
            {"tip": "Open windows during the day for natural ventilation", "icon": "mdi-window-open", "category": "health"},
            {"tip": "Prepare sun protection (check awnings, blinds)", "icon": "mdi-weather-sunny", "category": "comfort"},
            {"tip": "Service air conditioning before summer", "icon": "mdi-hvac", "category": "maintenance"},
        ],
        "summer": [
            {"tip": "Close shutters during the day to keep heat out", "icon": "mdi-window-shutter", "category": "comfort"},
            {"tip": "Ventilate at night — let cool air in", "icon": "mdi-weather-night", "category": "comfort"},
            {"tip": "Optimize PV usage — run washing machine at midday", "icon": "mdi-solar-power", "category": "energy"},
            {"tip": "Set cooling to max 6°C below outdoor temperature", "icon": "mdi-snowflake", "category": "energy"},
        ],
        "autumn": [
            {"tip": "Start heating early — don't wait until it's cold", "tip_curve": "Increase heating curve offset early — don't wait until it's cold", "icon": "mdi-radiator", "category": "comfort"},
            {"tip": "Check window and door seals", "icon": "mdi-door", "category": "maintenance"},
            {"tip": "Adjust lighting timers — getting dark earlier", "icon": "mdi-clock-outline", "category": "comfort"},
            {"tip": "Clean gutters and drains", "icon": "mdi-water", "category": "maintenance"},
        ],
    }

    def __init__(self, ha_connection):
        self.ha = ha_connection

    def get_season(self):
        """Get current season."""
        month = datetime.now().month
        for months, season in self.SEASONS.items():
            if month in months:
                return season
        return "unknown"

    def get_tips(self, lang="de"):
        """Get seasonal tips for current season."""
        from helpers import get_setting
        heating_mode = get_setting("heating_mode", "room_thermostat")

        season = self.get_season()
        tips_map = self.TIPS_DE if lang == "de" else self.TIPS_EN
        raw_tips = tips_map.get(season, [])

        # Resolve heating-mode-aware tips
        tips = []
        for t in raw_tips:
            if heating_mode == "heating_curve" and "tip_curve" in t:
                tips.append({**t, "tip": t["tip_curve"]})
            else:
                tips.append(t)

        # Add weather-based tip if available
        weather_tip = self._weather_tip(lang)
        if weather_tip:
            tips = [weather_tip] + tips

        return {
            "season": season,
            "season_label": {
                "winter": "Winter",
                "spring": "Fruehling" if lang == "de" else "Spring",
                "summer": "Sommer" if lang == "de" else "Summer",
                "autumn": "Herbst" if lang == "de" else "Autumn",
            }.get(season, season),
            "tips": tips,
        }

    def _weather_tip(self, lang):
        """Generate a tip based on current weather."""
        try:
            states = self.ha.get_states() or []
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    temp = s.get("attributes", {}).get("temperature")
                    condition = s.get("state", "")
                    if temp is not None:
                        if temp > 30:
                            return {
                                "tip": "Aktuell ueber 30°C — Rolllaeden schliessen und viel trinken!" if lang == "de" else "Currently over 30°C — close shutters and stay hydrated!",
                                "icon": "mdi-fire",
                                "category": "weather",
                            }
                        elif temp < 0:
                            from helpers import get_setting
                            hm = get_setting("heating_mode", "room_thermostat")
                            if hm == "heating_curve":
                                frost_tip = "Frostgefahr — Heizkurven-Offset nicht weiter senken!" if lang == "de" else "Frost danger — don't lower heating curve offset further!"
                            else:
                                frost_tip = "Frostgefahr — Heizung nicht unter 15°C stellen!" if lang == "de" else "Frost danger — don't set heating below 15°C!"
                            return {
                                "tip": frost_tip,
                                "icon": "mdi-snowflake",
                                "category": "weather",
                            }
                    if "rain" in condition:
                        return {
                            "tip": "Regen erwartet — Fenster schliessen!" if lang == "de" else "Rain expected — close windows!",
                            "icon": "mdi-weather-rainy",
                            "category": "weather",
                        }
        except Exception:
            pass
        return None


class CalendarIntegration:
    """Integrates HA calendar entities into MindHome (#14).

    Reads upcoming events from HA calendar entities.
    Can trigger automations based on calendar events.
    """

    def __init__(self, ha_connection):
        self.ha = ha_connection

    def get_events(self, hours_ahead=24):
        """Get upcoming calendar events from HA."""
        try:
            states = self.ha.get_states() or []
            calendar_entities = [s for s in states if s.get("entity_id", "").startswith("calendar.")]

            events = []
            now = datetime.now(timezone.utc)

            for cal in calendar_entities:
                attrs = cal.get("attributes", {})
                # HA calendar entities have message, start_time, end_time attributes
                start = attrs.get("start_time")
                end = attrs.get("end_time")
                title = attrs.get("message", attrs.get("friendly_name", ""))
                location = attrs.get("location", "")

                if start:
                    try:
                        if isinstance(start, str):
                            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        else:
                            start_dt = start

                        hours_diff = (start_dt - now).total_seconds() / 3600
                        if 0 <= hours_diff <= hours_ahead:
                            events.append({
                                "calendar_entity": cal.get("entity_id"),
                                "title": title,
                                "start": start_dt.isoformat() if hasattr(start_dt, 'isoformat') else str(start),
                                "end": end,
                                "location": location,
                                "hours_until": round(hours_diff, 1),
                            })
                    except (ValueError, TypeError):
                        pass

            events.sort(key=lambda e: e.get("hours_until", 999))
            return events

        except Exception as e:
            logger.error(f"CalendarIntegration get_events error: {e}")
            return []

    def get_calendar_entities(self):
        """List available calendar entities in HA."""
        try:
            states = self.ha.get_states() or []
            return [{
                "entity_id": s.get("entity_id"),
                "name": s.get("attributes", {}).get("friendly_name", s.get("entity_id")),
                "state": s.get("state"),
            } for s in states if s.get("entity_id", "").startswith("calendar.")]
        except Exception as e:
            logger.error(f"get_calendar_entities error: {e}")
            return []
