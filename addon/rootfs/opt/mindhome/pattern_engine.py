# MindHome Pattern Engine v0.7.0 (2026-02-14) - pattern_engine.py
"""
MindHome - Pattern Engine (Phase 2a + Phase 3 + Phase 4 fixes)
Core intelligence: state logging, context building, pattern detection.
Phase 3: Context tags (person, day phase, shift), significance thresholds,
         sensor fusion, scene detection, holiday awareness.
Phase 4 fixes: Midnight clustering, cross-room confidence, bidirectional
         loop detection, correlation room filter, upsert confidence decay,
         unavailable/unknown filtering, automation-chain detection.
"""

import os
import json
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from sqlalchemy import func, text, and_, or_
from sqlalchemy.orm import sessionmaker

from models import (
    get_engine, StateHistory, LearnedPattern, PatternMatchLog,
    Device, Domain, Room, RoomDomainState, DataCollection,
    SystemSetting, User, LearningPhase, NotificationLog, NotificationType,
    DayPhase, SensorThreshold, SensorGroup, LearnedScene, PresenceMode,
    PresenceLog, SchoolVacation, PluginSetting, PatternSettings,
    ManualRule, ActionLog, PatternExclusion
)

logger = logging.getLogger("mindhome.pattern_engine")


# ==============================================================================
# Sampling Configuration (A4: Intelligent Sampling)
# ==============================================================================

# Minimum change thresholds per device_class / entity type
SAMPLING_THRESHOLDS = {
    "temperature":  0.5,   # only log if >= 0.5° change
    "humidity":     2.0,   # only log if >= 2% change
    "pressure":     5.0,   # only log if >= 5 hPa change
    "illuminance":  50.0,  # only log if >= 50 lux change
    "power":        5.0,   # only log if >= 5W change
    "energy":       0.1,   # only log if >= 0.1 kWh change
    "voltage":      5.0,   # only log if >= 5V change
    "current":      0.5,   # only log if >= 0.5A change
    "battery":      5.0,   # only log if >= 5% change
    "pm25":         5.0,
    "pm10":         5.0,
    "co2":          50.0,
    "signal_strength": 5.0,  # dBm
    "distance":     0.5,     # m
    "weight":       0.5,     # kg
    "gas":          10.0,    # ppm/ppb
    "nitrogen_dioxide": 5.0, # µg/m³
    "volatile_organic_compounds": 10.0,  # ppb
    "carbon_monoxide": 5.0,  # ppm
    "speed":        1.0,     # m/s or km/h
    "wind_speed":   1.0,     # m/s
    "precipitation": 0.5,    # mm
    "moisture":     2.0,     # %
    "sound_pressure": 5.0,   # dB
}

# These entity domains always log (binary on/off changes are always significant)
ALWAYS_LOG_DOMAINS = {
    "light", "switch", "lock", "cover", "climate", "fan",
    "media_player", "alarm_control_panel", "person", "device_tracker",
    "binary_sensor", "automation", "scene", "input_boolean",
    "water_heater", "vacuum", "humidifier", "valve", "siren",
    "select", "number", "input_select", "input_number",
    "camera", "remote", "button",
}

# Motion sensor debounce: only log first "on" and final "off" within window
MOTION_DEBOUNCE_SECONDS = 60


# ==============================================================================
# Context Builder (A2: Context Capture)
# ==============================================================================

class ContextBuilder:
    """Builds context dict for each state change event."""

    def __init__(self, ha_connection, engine=None):
        self.ha = ha_connection
        self.Session = None
        if engine:
            self.Session = sessionmaker(bind=engine)

    def _get_season(self, month):
        if month in (3, 4, 5): return "spring"
        if month in (6, 7, 8): return "summer"
        if month in (9, 10, 11): return "autumn"
        return "winter"

    def build(self):
        """Build current context snapshot with multi-factor context."""
        try:
            import zoneinfo
            tz_name = self.ha.get_timezone()
            tz = zoneinfo.ZoneInfo(tz_name)
            now = datetime.now(tz)
        except Exception:
            now = datetime.now()
        hour = now.hour

        if 5 <= hour < 9:
            time_slot = "morning"
        elif 9 <= hour < 12:
            time_slot = "midday"
        elif 12 <= hour < 17:
            time_slot = "afternoon"
        elif 17 <= hour < 21:
            time_slot = "evening"
        else:
            time_slot = "night"

        season = self._get_season(now.month)

        ctx = {
            "time_slot": time_slot,
            "weekday": now.weekday(),
            "is_weekend": now.weekday() >= 5,
            "hour": hour,
            "minute": now.minute,
            "season": season,
            "month": now.month,
            "persons_home": [],
            "anyone_home": False,
            "sun_phase": "unknown",
            "sun_elevation": None,
            "outdoor_temp": None,
            "indoor_temp": None,
            "humidity": None,
            "weather_condition": None,
            "wind_speed": None,
            # #27 Seasonal weighting
            "season_weight": {"spring": 0.9, "summer": 1.0, "autumn": 0.9, "winter": 0.8}.get(season, 0.9),
            # #57 Weather-adaptive fields
            "is_rainy": False,
            "is_sunny": False,
            "is_dark": False,
            # #23 Vacation mode
            "vacation_mode": False,
            # #28 Calendar context
            "has_upcoming_event": False,
            "next_event_minutes": None,
        }

        try:
            states = self.ha.get_states() or []
            for s in states:
                eid = s.get("entity_id", "")
                state_val = s.get("state", "")
                attrs = s.get("attributes", {})

                if eid.startswith("person.") and state_val == "home":
                    ctx["persons_home"].append(eid)

                if eid == "sun.sun":
                    ctx["sun_phase"] = state_val
                    ctx["sun_elevation"] = attrs.get("elevation")
                    # #57 dark detection
                    elev = attrs.get("elevation")
                    if elev is not None and elev < -6:
                        ctx["is_dark"] = True

                if eid.startswith("weather."):
                    ctx["weather_condition"] = state_val
                    if attrs.get("temperature") is not None and ctx["outdoor_temp"] is None:
                        ctx["outdoor_temp"] = attrs["temperature"]
                    if attrs.get("humidity") is not None and ctx["humidity"] is None:
                        ctx["humidity"] = attrs["humidity"]
                    if attrs.get("wind_speed") is not None:
                        ctx["wind_speed"] = attrs["wind_speed"]
                    # #57 weather flags
                    if state_val in ("rainy", "pouring", "lightning-rainy", "hail", "snowy"):
                        ctx["is_rainy"] = True
                    if state_val in ("sunny", "clear-night"):
                        ctx["is_sunny"] = True

                if ctx["outdoor_temp"] is None and (
                    "outdoor" in eid or "outside" in eid or "aussen" in eid):
                    try:
                        ctx["outdoor_temp"] = float(state_val) if state_val else None
                    except (ValueError, TypeError):
                        pass

                if eid.startswith("climate.") and ctx["indoor_temp"] is None:
                    if attrs.get("current_temperature") is not None:
                        ctx["indoor_temp"] = attrs["current_temperature"]

            ctx["anyone_home"] = len(ctx["persons_home"]) > 0

        except Exception as e:
            logger.warning(f"Context build error: {e}")

        # #28 Calendar events
        try:
            events = self.ha.get_upcoming_events(hours=2)
            if events:
                ctx["has_upcoming_event"] = True
                first_start = events[0].get("start", {}).get("dateTime")
                if first_start:
                    evt_time = datetime.fromisoformat(first_start.replace("Z", "+00:00"))
                    diff = (evt_time - datetime.now(timezone.utc)).total_seconds() / 60
                    ctx["next_event_minutes"] = max(0, int(diff))
        except Exception:
            pass

        # #23 Vacation mode check
        if self.Session:
            try:
                session = self.Session()
                vac = session.query(SystemSetting).filter_by(key="vacation_mode").first()
                if vac and vac.value == "true":
                    ctx["vacation_mode"] = True

                # Phase 3: Current day phase
                try:
                    phases = session.query(DayPhase).filter_by(is_active=True).order_by(DayPhase.sort_order).all()
                    if phases:
                        current_phase = None
                        current_minutes = hour * 60 + now.minute
                        for phase in reversed(phases):
                            if phase.start_type == "time" and phase.start_time:
                                # Fix #26: Validate time string format
                                try:
                                    parts = phase.start_time.split(":")
                                    ph, pm = int(parts[0]), int(parts[1])
                                    if not (0 <= ph <= 23 and 0 <= pm <= 59):
                                        continue
                                except (ValueError, IndexError):
                                    continue
                                phase_minutes = ph * 60 + pm
                                if current_minutes >= phase_minutes:
                                    current_phase = phase
                                    break
                        if current_phase:
                            ctx["day_phase"] = current_phase.name_de
                            ctx["day_phase_id"] = current_phase.id
                except Exception:
                    pass

                # Phase 3: Holiday check
                try:
                    today_str = now.strftime("%Y-%m-%d")
                    from models import SystemSetting
                    holidays_json = session.query(SystemSetting).filter_by(key="holidays_cache").first()
                    if holidays_json:
                        holidays = json.loads(holidays_json.value)
                        ctx["is_holiday"] = today_str in holidays
                    else:
                        ctx["is_holiday"] = False

                    # If holiday, treat as weekend for automation purposes
                    if ctx.get("is_holiday"):
                        ctx["is_weekend"] = True
                except Exception:
                    ctx["is_holiday"] = False

                # Phase 3: School vacation check
                try:
                    vacation = session.query(SchoolVacation).filter(
                        SchoolVacation.is_active == True,
                        SchoolVacation.start_date <= today_str,
                        SchoolVacation.end_date >= today_str
                    ).first()
                    ctx["is_school_vacation"] = vacation is not None
                except Exception:
                    ctx["is_school_vacation"] = False

                # Phase 3: Active presence mode
                try:
                    last_mode = session.query(PresenceLog).order_by(
                        PresenceLog.created_at.desc()
                    ).first()
                    if last_mode:
                        ctx["presence_mode"] = last_mode.mode_name
                        ctx["presence_mode_id"] = last_mode.mode_id
                except Exception:
                    pass

                # Phase 3: Shift info for persons
                try:
                    shift_setting = session.query(SystemSetting).filter_by(key="current_shift").first()
                    if shift_setting:
                        ctx["current_shift"] = shift_setting.value
                except Exception:
                    pass

                session.close()
            except Exception:
                pass

        return ctx


# ==============================================================================
# State Logger (A1: State-Change Logger + A3: DataCollection Tracking)
# ==============================================================================

class StateLogger:
    """Logs significant state changes to state_history with context."""

    # Max events per minute (prevent DB flood from chatty devices)
    MAX_EVENTS_PER_MINUTE = 600

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        self.ha = ha_connection
        self.context_builder = ContextBuilder(ha_connection, engine)

        # Motion sensor debounce tracking
        self._motion_last_on = {}  # entity_id -> datetime
        self._last_sensor_values = {}  # entity_id -> last_logged_value
        self._last_sensor_times = {}  # entity_id -> last_logged_timestamp

        # Rate limiter: sliding window
        self._event_timestamps = []  # list of timestamps
        self._rate_limit_warned = False
        self._rate_limit_warn_time = None

        # Phase 3: Custom sensor thresholds cache
        self._custom_thresholds = {}  # entity_id -> SensorThreshold
        self._thresholds_loaded = False

    def should_log(self, entity_id, old_state, new_state, attributes):
        """A4: Intelligent sampling - decide if this state change is worth logging."""
        ha_domain = entity_id.split(".")[0]

        # Always log for important domains (binary state changes)
        if ha_domain in ALWAYS_LOG_DOMAINS:
            # Skip if state didn't actually change
            if old_state == new_state:
                return False

            # Motion sensor debounce (on + off)
            device_class = attributes.get("device_class", "")
            if ha_domain == "binary_sensor" and device_class in ("motion", "occupancy"):
                now = datetime.now()
                if new_state == "on":
                    last_on = self._motion_last_on.get(entity_id)
                    if last_on and (now - last_on).total_seconds() < MOTION_DEBOUNCE_SECONDS:
                        return False
                    self._motion_last_on[entity_id] = now
                elif new_state == "off":
                    if not hasattr(self, '_motion_last_off'):
                        self._motion_last_off = {}
                    last_off = self._motion_last_off.get(entity_id)
                    if last_off and (now - last_off).total_seconds() < MOTION_DEBOUNCE_SECONDS:
                        return False
                    self._motion_last_off[entity_id] = now
            return True

        # For sensors: check threshold
        if ha_domain == "sensor":
            device_class = attributes.get("device_class", "")

            # Phase 3: Load custom thresholds if not loaded
            if not self._thresholds_loaded:
                try:
                    session = self.Session()
                    for st in session.query(SensorThreshold).all():
                        if st.entity_id:
                            self._custom_thresholds[st.entity_id] = st
                        else:
                            self._custom_thresholds["__global__"] = st
                    session.close()
                    self._thresholds_loaded = True
                except Exception:
                    pass

            # Phase 3: Check custom threshold first, then default
            custom = self._custom_thresholds.get(entity_id) or self._custom_thresholds.get("__global__")
            threshold = SAMPLING_THRESHOLDS.get(device_class)

            if custom:
                # Min interval check
                now_ts = time.time()
                last_ts = self._last_sensor_times.get(entity_id, 0)
                min_interval = custom.min_interval_seconds or 60
                if (now_ts - last_ts) < min_interval:
                    return False

                try:
                    new_val = float(new_state)
                    last_val = self._last_sensor_values.get(entity_id)

                    if last_val is not None:
                        abs_change = abs(new_val - last_val)
                        # Check absolute threshold
                        if custom.min_change_absolute is not None:
                            if abs_change < custom.min_change_absolute:
                                return False
                        # Check percent threshold
                        elif custom.min_change_percent and last_val != 0:
                            pct_change = (abs_change / abs(last_val)) * 100
                            if pct_change < custom.min_change_percent:
                                return False

                    self._last_sensor_values[entity_id] = new_val
                    self._last_sensor_times[entity_id] = now_ts
                    return True
                except (ValueError, TypeError):
                    return False

            elif threshold is not None:
                try:
                    new_val = float(new_state)
                    last_val = self._last_sensor_values.get(entity_id)

                    if last_val is not None and abs(new_val - last_val) < threshold:
                        return False

                    self._last_sensor_values[entity_id] = new_val
                    return True
                except (ValueError, TypeError):
                    return False

            # Unknown sensor type: log with conservative fallback threshold
            try:
                new_val = float(new_state.get("state", ""))
                old_val = self._last_sensor_values.get(entity_id)
                if old_val is not None and abs(new_val - old_val) < 10.0:
                    return False
                self._last_sensor_values[entity_id] = new_val
                return True
            except (ValueError, TypeError):
                # Non-numeric sensor: log state text changes
                old_text = old_state.get("state", "") if isinstance(old_state, dict) else ""
                new_text = new_state.get("state", "") if isinstance(new_state, dict) else ""
                return old_text != new_text

        # Unknown domains: log if state actually changed
        old_text = old_state.get("state", "") if isinstance(old_state, dict) else ""
        new_text = new_state.get("state", "") if isinstance(new_state, dict) else ""
        return old_text != new_text

    def log_state_change(self, event_data):
        """Process a state_changed event from HA and log if significant."""
        entity_id = event_data.get("entity_id", "")
        new_state_obj = event_data.get("new_state", {})
        old_state_obj = event_data.get("old_state", {})

        if not new_state_obj or not entity_id:
            return

        # Rate limit check
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=60)
        self._event_timestamps = [t for t in self._event_timestamps if t > cutoff]
        if len(self._event_timestamps) >= self.MAX_EVENTS_PER_MINUTE:
            if not self._rate_limit_warned or (self._rate_limit_warn_time and (now - self._rate_limit_warn_time).total_seconds() > 300):
                logger.warning(f"Rate limit reached ({self.MAX_EVENTS_PER_MINUTE}/min), dropping events")
                self._rate_limit_warned = True
                self._rate_limit_warn_time = now
            return
        self._rate_limit_warned = False

        old_state = old_state_obj.get("state") if old_state_obj else None
        new_state = new_state_obj.get("state", "")
        new_attrs = new_state_obj.get("attributes", {})

        # Check if we should log this
        if not self.should_log(entity_id, old_state, new_state, new_attrs):
            return

        session = self.Session()
        try:
            # Find device_id in our DB - ONLY log devices assigned in MindHome
            device = session.query(Device).filter_by(ha_entity_id=entity_id).first()
            if not device:
                session.close()
                return  # Skip: device not imported into MindHome

            device_id = device.id
            device_room_id = device.room_id
            device_domain_id = device.domain_id

            # Build context
            ctx = self.context_builder.build()

            # Extract relevant attributes only (not full HA attribute dump)
            old_attrs_slim = self._slim_attributes(old_state_obj.get("attributes", {})) if old_state_obj else None
            new_attrs_slim = self._slim_attributes(new_attrs)

            # Use no_autoflush to prevent premature flush when querying DataCollection
            with session.no_autoflush:
                # Create state history entry
                entry = StateHistory(
                    device_id=device_id,
                    entity_id=entity_id,
                    old_state=old_state,
                    new_state=new_state,
                    old_attributes=old_attrs_slim,
                    new_attributes=new_attrs_slim,
                    context=ctx,
                )
                session.add(entry)

                # A3: Update DataCollection tracking
                if device_room_id and device_domain_id:
                    self._update_data_collection(session, device_room_id, device_domain_id)

            session.commit()
            self._event_timestamps.append(now)
            logger.debug(f"Logged: {entity_id} {old_state} → {new_state}")

        except Exception as e:
            session.rollback()
            logger.error(f"State log error: {e}")
        finally:
            session.close()

        # B.4: Check manual rules in separate session to avoid SQLite lock contention
        try:
            session2 = self.Session()
            try:
                self._check_manual_rules(session2, entity_id, new_state, ctx)
            except Exception as e:
                session2.rollback()
                logger.warning(f"Manual rule check error: {e}")
            finally:
                session2.close()
        except Exception:
            pass

    def _slim_attributes(self, attrs):
        """Keep only relevant attributes for learning, not full HA dump."""
        if not attrs:
            return None
        keep_keys = {
            "brightness", "color_temp", "rgb_color", "hs_color",
            "temperature", "current_temperature", "target_temp_high", "target_temp_low",
            "hvac_mode", "fan_mode", "swing_mode", "preset_mode",
            "current_position", "current_tilt_position",
            "media_content_type", "media_title", "source",
            "device_class", "unit_of_measurement",
            "is_volume_muted", "volume_level",
        }
        result = {}
        for k in keep_keys:
            if k in attrs:
                result[k] = attrs[k]
        return result if result else None

    def _update_data_collection(self, session, room_id, domain_id):
        """A3: Update DataCollection tracking for transparency dashboard."""
        try:
            dc = session.query(DataCollection).filter_by(
                room_id=room_id,
                domain_id=domain_id,
                data_type="state_changes"
            ).first()

            now = datetime.now(timezone.utc)
            if dc:
                dc.record_count += 1
                dc.last_record_at = now
            else:
                dc = DataCollection(
                    room_id=room_id,
                    domain_id=domain_id,
                    data_type="state_changes",
                    record_count=1,
                    first_record_at=now,
                    last_record_at=now,
                    storage_size_bytes=0,
                )
                session.add(dc)
        except Exception as e:
            logger.warning(f"DataCollection update error: {e}")

    def _check_manual_rules(self, session, entity_id, new_state, ctx):
        """B.4: Check and execute manual rules matching this state change."""
        try:
            from models import ManualRule, ActionLog
            rules = session.query(ManualRule).filter_by(
                trigger_entity=entity_id, is_active=True
            ).all()

            for rule in rules:
                # Check trigger state match
                ts = rule.trigger_state
                if ts and ts != new_state:
                    # Support numeric comparisons like ">25"
                    if ts.startswith(">") or ts.startswith("<"):
                        try:
                            val = float(new_state)
                            threshold = float(ts[1:])
                            if ts.startswith(">") and val <= threshold:
                                continue
                            if ts.startswith("<") and val >= threshold:
                                continue
                        except (ValueError, TypeError):
                            continue
                    else:
                        continue

                # Check conditions (weekday, time)
                conds = rule.conditions or {}
                if "weekdays" in conds and ctx.get("weekday") not in conds["weekdays"]:
                    continue
                if "time_after" in conds:
                    try:
                        h, m = map(int, conds["time_after"].split(":")[:2])
                        if ctx["hour"] < h or (ctx["hour"] == h and ctx["minute"] < m):
                            continue
                    except (ValueError, TypeError):
                        logger.warning(f"Manual rule '{rule.name}': invalid time_after format '{conds['time_after']}'")
                if "time_before" in conds:
                    try:
                        h, m = map(int, conds["time_before"].split(":")[:2])
                        if ctx["hour"] > h or (ctx["hour"] == h and ctx["minute"] > m):
                            continue
                    except (ValueError, TypeError):
                        logger.warning(f"Manual rule '{rule.name}': invalid time_before format '{conds['time_before']}'")

                if conds.get("only_home") and not ctx.get("anyone_home"):
                    continue

                # Execute with optional delay
                delay = rule.delay_seconds or 0
                if delay > 0:
                    import threading
                    def delayed_exec(r=rule):
                        try:
                            domain = r.action_entity.split(".")[0]
                            self.ha.call_service(domain, r.action_service,
                                r.action_data or {}, entity_id=r.action_entity)
                        except Exception as ex:
                            logger.error(f"Manual rule delayed exec error: {ex}")
                    threading.Timer(delay, delayed_exec).start()
                    logger.info(f"Manual rule '{rule.name}' scheduled in {delay}s")
                else:
                    domain = rule.action_entity.split(".")[0]
                    self.ha.call_service(domain, rule.action_service,
                        rule.action_data or {}, entity_id=rule.action_entity)
                    logger.info(f"Manual rule '{rule.name}' executed")

                # Update stats
                rule.execution_count = (rule.execution_count or 0) + 1
                rule.last_executed_at = datetime.now(timezone.utc)

                # Log
                log = ActionLog(
                    action_type="quick_action",
                    action_data={"rule_id": rule.id, "type": "manual_rule"},
                    reason=f"Regel: {rule.name}"
                )
                session.add(log)

            session.commit()
        except Exception as e:
            logger.warning(f"Manual rule check error: {e}")


# ==============================================================================
# Pattern Detector (B1-B3: Time, Sequence, Correlation patterns)
# ==============================================================================

class PatternDetector:
    """Analyzes state_history to find recurring patterns."""

    # Fix #11: Mutex to prevent concurrent analysis runs
    _analysis_lock = threading.Lock()

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        self._device_cache = {}

    def run_full_analysis(self):
        """B6: Run complete pattern analysis (called by scheduler).

        v0.7.0: Added mutex lock, exclusion passthrough to detectors,
        unavailable/unknown event filtering, cross-room correlation integration.
        """
        # Fix #11: Prevent concurrent analysis runs
        if not self._analysis_lock.acquire(blocking=False):
            logger.warning("Pattern analysis already running, skipping")
            return
        try:
            self._run_full_analysis_inner()
        finally:
            self._analysis_lock.release()

    def _run_full_analysis_inner(self):
        """Inner analysis method (runs under lock)."""
        logger.info("Starting pattern analysis...")

        # Fix #18: Clear upsert caches from previous run
        for attr in list(vars(self)):
            if attr.startswith("_upsert_cache_"):
                delattr(self, attr)
        self._device_cache = {}

        # Phase 1: Read events into memory, then close read session immediately
        # to avoid holding SQLite locks during long-running analysis
        read_session = self.Session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            events = read_session.query(StateHistory).filter(
                StateHistory.created_at >= cutoff,
                StateHistory.device_id.isnot(None)
            ).order_by(StateHistory.created_at.asc()).all()

            if len(events) < 20:
                logger.info(f"Only {len(events)} events, need at least 20 for analysis")
                return

            # Detach events from session so they can be used after close
            for ev in events:
                read_session.expunge(ev)

            from models import PatternExclusion
            exclusions = read_session.query(PatternExclusion).all()
            excluded_pairs = set()
            for e in exclusions:
                excluded_pairs.add((e.entity_a, e.entity_b))
                excluded_pairs.add((e.entity_b, e.entity_a))

            # Filter out entities from disabled domains (global toggle)
            disabled_domain_ids = {d.id for d in read_session.query(Domain).filter_by(is_enabled=False).all()}
            disabled_entities = set()
            if disabled_domain_ids:
                disabled_devs = read_session.query(Device).filter(
                    Device.domain_id.in_(disabled_domain_ids)
                ).all()
                disabled_entities = {d.ha_entity_id for d in disabled_devs}

            # Also filter entities where ALL room-domain modes are "off"
            # (domain is on globally but disabled in every room where it has devices)
            from models import RoomDomainState
            off_room_domains = read_session.query(RoomDomainState).filter(
                RoomDomainState.mode == "off"
            ).all()
            off_rd_pairs = {(rds.room_id, rds.domain_id) for rds in off_room_domains}
            if off_rd_pairs:
                all_devices = read_session.query(Device).filter(
                    Device.is_tracked == True,
                    Device.room_id.isnot(None),
                    Device.domain_id.isnot(None),
                ).all()
                for dev in all_devices:
                    if (dev.room_id, dev.domain_id) in off_rd_pairs:
                        disabled_entities.add(dev.ha_entity_id)
        finally:
            read_session.close()

        # Remove events from disabled domains/room-modes before analysis
        if disabled_entities:
            before_count = len(events)
            events = [ev for ev in events if ev.entity_id not in disabled_entities]
            filtered = before_count - len(events)
            if filtered:
                logger.info(f"Filtered {filtered} events from disabled domains/rooms")

        # Fix #7: Filter out events with invalid HA states (unavailable, unknown)
        before_count = len(events)
        events = [ev for ev in events if ev.new_state not in self._INVALID_STATES]
        invalid_filtered = before_count - len(events)
        if invalid_filtered:
            logger.info(f"Filtered {invalid_filtered} events with invalid states (unavailable/unknown)")

        logger.info(f"Analyzing {len(events)} events from last 14 days")

        # Phase 2: Run analysis and write results in a separate session
        session = self.Session()
        try:
            # B1: Time-based patterns
            time_patterns = self._detect_time_patterns(session, events)

            # B2: Sequence patterns (event chains)
            # Fix #10: Pass exclusions directly to detectors for immediate effect
            sequence_patterns = self._detect_sequence_patterns(session, events, excluded_pairs)

            # B3: Correlation patterns (with exclusions)
            correlation_patterns = self._detect_correlation_patterns(session, events, excluded_pairs)

            # Fix #24: Cross-room correlations → create insight patterns
            cross_room_patterns = []
            try:
                cross_room = self.detect_cross_room_correlations(session)
                logger.info(f"Cross-room correlations: {len(cross_room)} room pairs found")
                for cr in cross_room:
                    ra = cr["room_a"]
                    rb = cr["room_b"]
                    count = cr["co_occurrence_count"]
                    confidence = min(count / 100, 0.85)  # 100+ co-occurrences = max confidence
                    pattern_data = {
                        "condition_entity": f"room:{ra['id']}",
                        "correlated_entity": f"room:{rb['id']}",
                        "condition_state": "active",
                        "correlated_state": "active",
                        "room_a_name": ra["name"],
                        "room_b_name": rb["name"],
                        "co_occurrence_count": count,
                        "subtype": "cross_room",
                        "same_room": False,
                    }
                    trigger_conditions = {"type": "room_activity", "room_id": ra["id"]}
                    action_def = {"type": "room_activity", "room_id": rb["id"]}
                    desc_de = f"Aktivitaet in {ra['name']} und {rb['name']} korrelieren ({count}x gleichzeitig)"
                    desc_en = f"Activity in {ra['name']} and {rb['name']} correlate ({count}x simultaneous)"
                    p = self._upsert_pattern(
                        session, f"room:{ra['id']}↔room:{rb['id']}", "correlation",
                        pattern_data, confidence, trigger_conditions, action_def,
                        desc_de, desc_en, None
                    )
                    if p:
                        cross_room_patterns.append(p)
            except Exception as e:
                logger.warning(f"Cross-room correlation error: {e}")

            # B7: Domain-specific confidence boost
            self._apply_domain_scoring(session)

            # B.9: Seasonal tagging
            now = datetime.now()
            month = now.month
            season = "spring" if month in (3,4,5) else "summer" if month in (6,7,8) else "autumn" if month in (9,10,11) else "winter"
            for p in session.query(LearnedPattern).filter(
                LearnedPattern.season == None, LearnedPattern.is_active == True
            ).all():
                # Check if pattern only occurs in current season
                matches = session.query(PatternMatchLog).filter_by(pattern_id=p.id).all()
                if len(matches) >= 5:
                    match_months = [m.matched_at.month for m in matches if m.matched_at]
                    season_months = {"spring": [3,4,5], "summer": [6,7,8], "autumn": [9,10,11], "winter": [12,1,2]}
                    for s_name, s_months in season_months.items():
                        if all(m in s_months for m in match_months):
                            p.season = s_name
                            break

            # B5: Decay now handled solely by apply_confidence_decay (scheduler, every 12h)

            total = len(time_patterns) + len(sequence_patterns) + len(correlation_patterns) + len(cross_room_patterns)
            logger.info(
                f"Analysis complete: {len(time_patterns)} time, "
                f"{len(sequence_patterns)} sequence, "
                f"{len(correlation_patterns)} correlation, "
                f"{len(cross_room_patterns)} cross-room patterns"
            )

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Pattern analysis error: {e}")
        finally:
            session.close()

    def _apply_domain_scoring(self, session):
        """B.7: Boost confidence based on domain-specific features."""
        try:
            patterns = session.query(LearnedPattern).filter_by(is_active=True).all()
            for p in patterns:
                pd = p.pattern_data or {}
                entity = pd.get("entity_id", "")
                ha_domain = entity.split(".")[0] if entity else ""

                boost = 0.0
                # Light: boost if brightness pattern at consistent times
                if ha_domain == "light" and p.pattern_type == "time_based":
                    if pd.get("attributes", {}).get("brightness"):
                        boost += 0.05  # brightness-aware patterns more reliable
                # Climate: boost if temp patterns correlate with season
                elif ha_domain == "climate":
                    if p.season:
                        boost += 0.08  # seasonal climate patterns very reliable
                # Cover: boost if correlated with sun
                elif ha_domain == "cover":
                    ctx = pd.get("typical_context", {})
                    if ctx.get("sun_elevation") is not None:
                        boost += 0.06  # sun-correlated cover patterns
                # Binary sensor: boost for high-frequency patterns
                elif ha_domain == "binary_sensor":
                    if p.match_count and p.match_count > 20:
                        boost += 0.04

                if boost > 0:
                    p.confidence = min(1.0, (p.confidence or 0) + boost)
        except Exception as e:
            logger.warning(f"Domain scoring error: {e}")

    def apply_confidence_decay(self, session):
        """Unified confidence decay (v0.6.4).

        Algorithm: Grace period 2 days, then 1%/week for 14 days,
        then max 10%/day after 16 days. Deactivate at < 0.1.
        Called by scheduler every 12h but applies decay only once per calendar day.
        """
        try:
            now = datetime.now(timezone.utc)
            today = now.date()
            patterns = session.query(LearnedPattern).filter(
                LearnedPattern.is_active == True,
                LearnedPattern.confidence > 0.1
            ).all()

            decayed_count = 0
            for p in patterns:
                # Only apply decay once per calendar day (stored in pattern_data)
                pdata = p.pattern_data if isinstance(p.pattern_data, dict) else {}
                last_decay_str = pdata.get("_last_decay_date")
                if last_decay_str:
                    try:
                        if datetime.fromisoformat(last_decay_str).date() == today:
                            continue
                    except (ValueError, TypeError):
                        pass

                last_active = p.last_matched_at or p.created_at
                if last_active and last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)
                days_inactive = (now - last_active).days if last_active else 0

                if days_inactive <= 2:
                    continue  # Grace period

                if days_inactive <= 16:  # 2 + 14 days: gentle decay
                    decay = 0.01 * ((days_inactive - 2) / 7)
                else:  # After 16 days: aggressive decay, capped at 10%/day
                    gentle_decay = 0.01 * 2  # 2 weeks of gentle
                    aggressive_days = days_inactive - 16
                    decay = min(gentle_decay + 0.05 * aggressive_days, 0.10)

                old_conf = p.confidence
                p.confidence = max(0.0, p.confidence - decay)

                # Track last decay date
                if p.pattern_data is None:
                    p.pattern_data = {}
                if isinstance(p.pattern_data, dict):
                    p.pattern_data["_last_decay_date"] = today.isoformat()

                if p.confidence < 0.1:
                    p.is_active = False
                    p.status = "disabled"
                    logger.info(f"Pattern {p.id} deactivated (confidence {p.confidence:.2f})")

                if decay > 0:
                    decayed_count += 1
                    logger.debug(f"Pattern {p.id} decay: {old_conf:.2f} → {p.confidence:.2f} ({days_inactive}d inactive)")

            session.commit()
            if decayed_count:
                logger.info(f"Confidence decay applied to {decayed_count} patterns")
        except Exception as e:
            logger.warning(f"Confidence decay error: {e}")

    @staticmethod
    def explain_confidence(pattern):
        """#51: Explain why a pattern has its confidence level."""
        p = pattern
        factors = []
        conf = p.confidence or 0

        # Match count factor
        mc = p.match_count or 0
        if mc >= 20:
            factors.append({"factor": "high_matches", "detail": f"{mc} matches", "impact": "+high"})
        elif mc >= 5:
            factors.append({"factor": "moderate_matches", "detail": f"{mc} matches", "impact": "+medium"})
        else:
            factors.append({"factor": "few_matches", "detail": f"{mc} matches", "impact": "low"})

        # Staleness
        if p.last_matched_at:
            days = (datetime.now(timezone.utc) - p.last_matched_at).days
            if days > 14:
                factors.append({"factor": "stale", "detail": f"last match {days}d ago", "impact": "-decay"})
            else:
                factors.append({"factor": "recent", "detail": f"matched {days}d ago", "impact": "+fresh"})

        # Season
        if p.season:
            factors.append({"factor": "seasonal", "detail": f"season: {p.season}", "impact": "+specific"})

        # Time consistency
        pd = p.pattern_data or {}
        tw = pd.get("time_window_min", 60)
        if tw <= 15:
            factors.append({"factor": "precise_time", "detail": f"±{tw}min window", "impact": "+precise"})

        return {
            "confidence": conf,
            "confidence_pct": f"{conf:.0%}",
            "factors": factors,
            "summary_de": f"Vertrauen {conf:.0%}: {mc} Treffer" + (f", zuletzt vor {days}d" if p.last_matched_at else ""),
            "summary_en": f"Confidence {conf:.0%}: {mc} matches" + (f", last {days}d ago" if p.last_matched_at else ""),
        }

    def detect_cross_room_correlations(self, session):
        """#56: Detect patterns across rooms (e.g. kitchen→dining room).

        Fix #17: Pre-fetches all devices to avoid N+1 query explosion.
        Previously did one DB query per event per window (~20k queries).
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            history = session.query(StateHistory).filter(
                StateHistory.created_at > cutoff
            ).order_by(StateHistory.created_at).all()

            # Fix #17: Pre-fetch ALL device→room mappings in one query
            all_devices = session.query(Device).filter(
                Device.room_id.isnot(None)
            ).all()
            entity_room_map = {d.ha_entity_id: d.room_id for d in all_devices}

            # Group by 60-second windows
            windows = {}
            for h in history:
                wk = int(h.created_at.timestamp() // 60)
                if wk not in windows:
                    windows[wk] = []
                windows[wk].append(h)

            # Find cross-room pairs
            correlations = []
            pair_counter = Counter()
            for wk, events in windows.items():
                rooms = set()
                for e in events:
                    room_id = entity_room_map.get(e.entity_id)
                    if room_id:
                        rooms.add(room_id)
                if len(rooms) >= 2:
                    for r1 in rooms:
                        for r2 in rooms:
                            if r1 < r2:
                                pair_counter[(r1, r2)] += 1

            for (r1, r2), count in pair_counter.most_common(5):
                if count >= 5:
                    room1 = session.get(Room, r1)
                    room2 = session.get(Room, r2)
                    if room1 and room2:
                        correlations.append({
                            "room_a": {"id": r1, "name": room1.name},
                            "room_b": {"id": r2, "name": room2.name},
                            "co_occurrence_count": count,
                        })

            return correlations
        except Exception as e:
            logger.warning(f"Cross-room correlation error: {e}")
            return []

    # --------------------------------------------------------------------------
    # B1: Time-based patterns
    # --------------------------------------------------------------------------
    def _detect_time_patterns(self, session, events):
        """Find recurring actions at similar times."""
        patterns_found = []

        # Sensors are read-only: their values are consequences of other actions,
        # not actionable automations. Skip them for time-based pattern detection.
        NON_ACTIONABLE_PREFIXES = (
            "sensor.", "binary_sensor.", "sun.", "weather.",
            "zone.", "person.", "device_tracker.", "calendar.", "proximity.",
        )

        # Group events by (entity_id, new_state)
        groups = defaultdict(list)
        actionable_count = 0
        no_context_count = 0
        for ev in events:
            # Skip non-actionable entities (sensors, etc.) - they can't be controlled
            if ev.entity_id and ev.entity_id.startswith(NON_ACTIONABLE_PREFIXES):
                continue
            actionable_count += 1
            key = (ev.entity_id, ev.new_state)
            if ev.context:
                groups[key].append({
                    "hour": ev.context.get("hour", 0),
                    "minute": ev.context.get("minute", 0),
                    "weekday": ev.context.get("weekday", 0),
                    "is_weekend": ev.context.get("is_weekend", False),
                    "persons_home": ev.context.get("persons_home", []),
                    "sun_elevation": ev.context.get("sun_elevation"),
                    "created_at": ev.created_at,
                })
            else:
                no_context_count += 1

        eligible_groups = {k: v for k, v in groups.items() if len(v) >= 4}
        logger.info(
            f"Time patterns: {actionable_count} actionable events "
            f"(of {len(events)} total, {no_context_count} without context), "
            f"{len(groups)} entity/state groups, {len(eligible_groups)} with >=4 occurrences"
        )

        small_cluster_count = 0
        low_confidence_count = 0
        skipped_rejected_count = 0

        for (entity_id, new_state), occurrences in groups.items():
            if len(occurrences) < 4:
                continue

            # Cluster by time of day (within 30min window)
            time_clusters = self._cluster_by_time(occurrences)

            for cluster in time_clusters:
                if len(cluster) < 3:
                    small_cluster_count += 1
                    continue

                # Calculate average time
                avg_hour, avg_minute = self._average_time(cluster)

                # Check weekday pattern
                weekdays = [o["weekday"] for o in cluster]
                wd_counter = Counter(weekdays)
                is_weekday_only = all(wd < 5 for wd in weekdays)
                is_weekend_only = all(wd >= 5 for wd in weekdays)

                # Check person pattern (multi-user context)
                person_sets = [frozenset(o.get("persons_home", [])) for o in cluster]
                common_persons = set.intersection(*[set(ps) for ps in person_sets]) if person_sets else set()

                # Calculate consistency (how many of the last 14 days had this?)
                days_with_event = len(set(o["created_at"].date() for o in cluster))
                # expected_days: realistic expectations (people miss days, are away, etc.)
                expected_days = 10 if is_weekday_only else (4 if is_weekend_only else 10)
                consistency = min(days_with_event / max(expected_days, 1), 1.0)

                # Confidence = weighted average of frequency and consistency
                # Old formula: (cluster/14) * consistency was too punishing (effectively squaring)
                # Example: 6 events on 6 days → old: 0.18 (blocked), new: 0.51 (detected)
                frequency = len(cluster) / 14
                confidence = min(frequency * 0.5 + consistency * 0.5, 0.95)

                if confidence < 0.3:
                    low_confidence_count += 1
                    continue

                # Check sun-relative timing
                sun_elevations = [o.get("sun_elevation") for o in cluster if o.get("sun_elevation") is not None]
                sun_relative = None
                if sun_elevations and len(sun_elevations) >= len(cluster) * 0.7:
                    avg_sun = sum(sun_elevations) / len(sun_elevations)
                    sun_std = (sum((s - avg_sun)**2 for s in sun_elevations) / len(sun_elevations))**0.5
                    # If sun elevation is more consistent than time, use sun-relative
                    if sun_std < 5.0:
                        sun_relative = round(avg_sun, 1)

                # Build pattern data
                pattern_data = {
                    "entity_id": entity_id,
                    "target_state": new_state,
                    "avg_hour": avg_hour,
                    "avg_minute": avg_minute,
                    "time_window_min": 15,
                    "weekday_filter": "weekdays" if is_weekday_only else ("weekends" if is_weekend_only else "all"),
                    "occurrence_count": len(cluster),
                    "days_observed": days_with_event,
                    "sun_relative_elevation": sun_relative,
                }

                trigger_conditions = {
                    "type": "time",
                    "hour": avg_hour,
                    "minute": avg_minute,
                    "window_min": 15,
                }
                if is_weekday_only:
                    trigger_conditions["weekdays_only"] = True
                elif is_weekend_only:
                    trigger_conditions["weekends_only"] = True
                if common_persons:
                    trigger_conditions["requires_persons"] = list(common_persons)
                    pattern_data["requires_persons"] = list(common_persons)

                action_def = {
                    "entity_id": entity_id,
                    "target_state": new_state,
                }

                # Build descriptions
                device = session.query(Device).filter_by(ha_entity_id=entity_id).first()
                device_name = device.name if device else entity_id
                time_str = f"{avg_hour:02d}:{avg_minute:02d}"
                day_str_de = "werktags" if is_weekday_only else ("am Wochenende" if is_weekend_only else "täglich")
                day_str_en = "on weekdays" if is_weekday_only else ("on weekends" if is_weekend_only else "daily")
                state_de = "eingeschaltet" if new_state == "on" else ("ausgeschaltet" if new_state == "off" else new_state)
                state_en = "turned on" if new_state == "on" else ("turned off" if new_state == "off" else new_state)

                desc_de = f"{device_name} wird {day_str_de} um ca. {time_str} {state_de}"
                desc_en = f"{device_name} is {state_en} {day_str_en} around {time_str}"

                if common_persons:
                    person_names = ", ".join(p.replace("person.", "") for p in common_persons)
                    desc_de += f" (wenn {person_names} zuhause)"
                    desc_en += f" (when {person_names} home)"

                # Store or update pattern
                p = self._upsert_pattern(
                    session, entity_id, "time_based", pattern_data,
                    confidence, trigger_conditions, action_def,
                    desc_de, desc_en, device
                )
                if p:
                    patterns_found.append(p)
                else:
                    skipped_rejected_count += 1
                    logger.debug(f"Time pattern skipped (rejected/disabled): {entity_id} -> {new_state} at {avg_hour:02d}:{avg_minute:02d}")

        logger.info(
            f"Time patterns: {len(patterns_found)} created/updated, "
            f"{small_cluster_count} small clusters (<3), "
            f"{low_confidence_count} low confidence (<0.3), "
            f"{skipped_rejected_count} rejected/disabled"
        )
        return patterns_found

    # --------------------------------------------------------------------------
    # B2: Sequence patterns (event chains)
    # --------------------------------------------------------------------------

    # HA domains that produce purely numeric/measurement data - not useful
    # as automation triggers or actions in sequence patterns
    _SENSOR_ONLY_DOMAINS = frozenset({"sensor", "weather", "number"})

    # HA domains that can actually be controlled (valid as action side of a pattern)
    _ACTIONABLE_DOMAINS = frozenset({
        "light", "switch", "cover", "climate", "fan", "media_player",
        "lock", "vacuum", "humidifier", "water_heater", "valve",
        "input_boolean", "input_number", "input_select", "scene", "script",
    })

    def _is_same_domain_sensor_pair(self, entity_a, entity_b):
        """Check if both entities are sensor-only domains (no actionable patterns)."""
        domain_a = entity_a.split(".")[0]
        domain_b = entity_b.split(".")[0]
        return domain_a in self._SENSOR_ONLY_DOMAINS and domain_b in self._SENSOR_ONLY_DOMAINS

    # HA states that indicate errors, not real device activity
    _INVALID_STATES = frozenset({"unavailable", "unknown", "none", ""})

    def _detect_sequence_patterns(self, session, events, excluded_pairs=None):
        """Find A→B event chains (within time window).

        v0.7.0 fixes: cross-room confidence formula, bidirectional loop
        detection, unavailable/unknown filtering, automation-chain detection,
        timing consistency as confidence factor, minimum absolute timing
        tolerance, increased example cap, pre-fetched device names.
        """
        patterns_found = []
        excluded_pairs = excluded_pairs or set()
        CHAIN_WINDOW = self._get_pattern_setting(session, "chain_window_seconds", 120)

        # Pre-build entity→room_id AND entity→name lookup (avoid N+1 queries)
        all_entity_ids = {ev.entity_id for ev in events}
        entity_room_map = {}
        entity_name_map = {}
        if all_entity_ids:
            devs = session.query(Device).filter(
                Device.ha_entity_id.in_(all_entity_ids)
            ).all()
            entity_room_map = {d.ha_entity_id: d.room_id for d in devs}
            entity_name_map = {d.ha_entity_id: d.name for d in devs}
            self._device_cache = {d.ha_entity_id: d for d in devs}

        # Build pairs: for each event, what happened within the time window after?
        pairs = defaultdict(int)
        pair_examples = defaultdict(list)

        for i, ev_a in enumerate(events):
            # Fix #7: Skip invalid HA states (unavailable, unknown)
            if ev_a.new_state in self._INVALID_STATES:
                continue

            for j in range(i + 1, len(events)):
                ev_b = events[j]
                delta = (ev_b.created_at - ev_a.created_at).total_seconds()

                if delta > CHAIN_WINDOW:
                    break
                if delta < 2:  # Ignore near-simultaneous (likely same automation)
                    continue
                if ev_a.entity_id == ev_b.entity_id:
                    continue
                # Fix #7: Skip invalid states on B side too
                if ev_b.new_state in self._INVALID_STATES:
                    continue
                # Skip sensor→sensor pairs (numeric correlations, not actionable)
                if self._is_same_domain_sensor_pair(ev_a.entity_id, ev_b.entity_id):
                    continue
                # Action side must be controllable (sensor as action makes no sense)
                if ev_b.entity_id.split(".")[0] not in self._ACTIONABLE_DOMAINS:
                    continue
                # Fix #10: Skip excluded entity pairs
                if (ev_a.entity_id, ev_b.entity_id) in excluded_pairs:
                    continue

                # Fix #22: Skip if B was triggered by an HA automation
                ctx_b = ev_b.context if isinstance(ev_b.context, dict) else {}
                context_id = ctx_b.get("context_id", "")
                if isinstance(context_id, str) and context_id.startswith("automation."):
                    continue

                key = (
                    ev_a.entity_id, ev_a.new_state,
                    ev_b.entity_id, ev_b.new_state
                )
                pairs[key] += 1
                # Fix #19: Increase example cap from 20 to 50 for better statistics
                if len(pair_examples[key]) < 50:
                    pair_examples[key].append({
                        "delta_seconds": delta,
                        "context_a": ev_a.context,
                        "context_b": ev_b.context,
                    })

        # Filter: need minimum occurrences — higher threshold for cross-room pairs
        min_seq_count = self._get_pattern_setting(session, "min_sequence_count", 7)
        min_seq_count_cross = self._get_pattern_setting(session, "min_sequence_count_cross_room", 20)
        min_confidence_base = self._get_pattern_setting(session, "min_confidence", 0.45)
        min_confidence_cross = self._get_pattern_setting(session, "min_confidence_cross_room", 0.65)
        cross_room_filtered = 0

        # Fix #6: Collect accepted patterns to detect bidirectional loops
        accepted_pairs = set()

        for (eid_a, state_a, eid_b, state_b), count in pairs.items():
            # Determine if same room or cross-room
            room_a = entity_room_map.get(eid_a)
            room_b = entity_room_map.get(eid_b)
            same_room = (room_a is not None and room_b is not None and room_a == room_b)

            # Apply room-aware thresholds
            effective_min_count = min_seq_count if same_room else min_seq_count_cross
            effective_min_conf = min_confidence_base if same_room else min_confidence_cross

            if count < effective_min_count:
                if not same_room and count >= min_seq_count:
                    cross_room_filtered += 1
                continue

            # Fix #6: Skip reverse direction if forward already accepted
            reverse_key = (eid_b, state_b, eid_a, state_a)
            if reverse_key in accepted_pairs:
                logger.debug(f"Skipping reverse pattern {eid_b}→{eid_a} (forward exists)")
                continue

            examples = pair_examples[(eid_a, state_a, eid_b, state_b)]
            avg_delta = sum(e["delta_seconds"] for e in examples) / len(examples)

            # Consistency check: is the delta consistent?
            deltas = [e["delta_seconds"] for e in examples]
            delta_std = (sum((d - avg_delta)**2 for d in deltas) / len(deltas))**0.5

            # Fix #21: Minimum absolute tolerance for short delays
            # A 3s avg with 2s std is normal for motion→light patterns
            max_variation = 0.6 if same_room else 0.4
            min_abs_tolerance = 5.0  # seconds — always allow at least 5s std
            timing_threshold = max(avg_delta * max_variation, min_abs_tolerance)
            if delta_std > timing_threshold:
                if not same_room:
                    cross_room_filtered += 1
                continue

            # Check person context consistency
            contexts_a = [e.get("context_a", {}) for e in examples if e.get("context_a")]
            common_persons = self._find_common_persons(contexts_a)

            # Fix #1: Separate confidence formula for same-room vs cross-room
            # Same-room: count/min_count scales 0..1, then * 0.8, capped at 0.90
            # Cross-room: use same base formula (count/min_count) so min_count
            # threshold is effective (not double-penalized)
            base_ratio = min(count / effective_min_count, 2.0)  # cap at 2x
            confidence = min(base_ratio * 0.5, 0.90)

            # Fix #20: Timing consistency bonus — tight timing = more confidence
            if avg_delta > 0:
                timing_consistency = max(0, 1.0 - (delta_std / max(avg_delta, 1.0)))
                confidence = min(confidence + timing_consistency * 0.15, 0.90)

            if confidence < effective_min_conf:
                continue

            # Fix #6: Track accepted pair
            accepted_pairs.add((eid_a, state_a, eid_b, state_b))

            pattern_data = {
                "trigger_entity": eid_a,
                "trigger_state": state_a,
                "action_entity": eid_b,
                "action_state": state_b,
                "avg_delay_seconds": round(avg_delta, 1),
                "delay_std": round(delta_std, 1),
                "occurrence_count": count,
                "same_room": same_room,
            }
            if common_persons:
                pattern_data["requires_persons"] = list(common_persons)

            trigger_conditions = {
                "type": "event",
                "trigger_entity": eid_a,
                "trigger_state": state_a,
                "delay_seconds": round(avg_delta),
            }
            if common_persons:
                trigger_conditions["requires_persons"] = list(common_persons)

            action_def = {
                "entity_id": eid_b,
                "target_state": state_b,
            }

            # Fix #16: Use pre-fetched name map instead of DB queries
            name_a = entity_name_map.get(eid_a, eid_a)
            name_b = entity_name_map.get(eid_b, eid_b)
            state_a_de = "eingeschaltet" if state_a == "on" else ("ausgeschaltet" if state_a == "off" else state_a)
            state_b_de = "eingeschaltet" if state_b == "on" else ("ausgeschaltet" if state_b == "off" else state_b)

            delay_str = f"{int(avg_delta)}s" if avg_delta < 60 else f"{int(avg_delta/60)} Min"
            desc_de = f"Wenn {name_a} {state_a_de} wird → {name_b} wird nach ~{delay_str} {state_b_de}"
            desc_en = f"When {name_a} turns {state_a} → {name_b} turns {state_b} after ~{delay_str}"

            dev_b = self._device_cache.get(eid_b)
            p = self._upsert_pattern(
                session, f"{eid_a}→{eid_b}", "event_chain", pattern_data,
                confidence, trigger_conditions, action_def,
                desc_de, desc_en, dev_b
            )
            if p:
                patterns_found.append(p)

        if cross_room_filtered:
            logger.info(f"Filtered {cross_room_filtered} weak cross-room patterns")

        return patterns_found

    # --------------------------------------------------------------------------
    # B3: Correlation patterns
    # --------------------------------------------------------------------------

    def _detect_correlation_patterns(self, session, events, excluded_pairs=None):
        """Find state correlations (when X is Y, Z is usually W).

        v0.7.0 fixes: room-aware filtering (same thresholds as sequence
        patterns), entity_states time-based cleanup, unavailable/unknown
        filtering, pre-fetched device names, exclusion support.
        """
        patterns_found = []
        excluded_pairs = excluded_pairs or set()

        # Fix #8: Pre-build entity→room_id and name lookup
        all_entity_ids = {ev.entity_id for ev in events}
        entity_room_map = {}
        entity_name_map = {}
        if all_entity_ids:
            devs = session.query(Device).filter(
                Device.ha_entity_id.in_(all_entity_ids)
            ).all()
            entity_room_map = {d.ha_entity_id: d.room_id for d in devs}
            entity_name_map = {d.ha_entity_id: d.name for d in devs}
            if not hasattr(self, '_device_cache'):
                self._device_cache = {}
            self._device_cache.update({d.ha_entity_id: d for d in devs})

        # Build state snapshots: for each entity, when it changes,
        # what are the states of other entities?
        entity_states = {}  # current known state per entity
        entity_last_seen = {}  # Fix #9: track when state was last updated

        cooccurrences = defaultdict(lambda: defaultdict(int))
        # cooccurrences[(entity_a, state_a)][(entity_b, state_b)] = count

        # Fix #9: Max staleness for correlated states (8 hours)
        # Many entities (person, lights, climate) hold state for hours.
        # 2h was too aggressive and filtered out most legitimate correlations.
        MAX_STATE_AGE_SECONDS = 28800

        for ev in events:
            # Fix #7: Skip invalid states
            if ev.new_state in self._INVALID_STATES:
                continue

            entity_states[ev.entity_id] = ev.new_state
            entity_last_seen[ev.entity_id] = ev.created_at

            # Only check correlations for "important" state changes
            ha_domain = ev.entity_id.split(".")[0]
            if ha_domain not in {"person", "binary_sensor", "sun", "switch", "light", "cover", "climate", "input_boolean"} and ev.entity_id != "sun.sun":
                continue

            # Record what other entities are doing when this event happens
            for other_eid, other_state in entity_states.items():
                if other_eid == ev.entity_id:
                    continue
                other_domain = other_eid.split(".")[0]
                if other_domain in {"sensor", "weather"}:
                    continue  # Skip numeric sensors
                # Fix #7: Skip invalid states in correlated entities
                if other_state in self._INVALID_STATES:
                    continue
                # Fix #10: Skip excluded pairs
                if (ev.entity_id, other_eid) in excluded_pairs:
                    continue

                # Fix #9: Only correlate with recently-seen states
                other_last = entity_last_seen.get(other_eid)
                if other_last:
                    age = (ev.created_at - other_last).total_seconds()
                    if age > MAX_STATE_AGE_SECONDS:
                        continue

                cooccurrences[(ev.entity_id, ev.new_state)][(other_eid, other_state)] += 1

        # Find strong correlations
        # Fix #8: Room-aware thresholds for correlations
        # v0.7.14: Relaxed from 0.7/0.8 to 0.55/0.7 — 22k pairs failed at old thresholds
        min_corr_count_same = 4
        min_corr_count_cross = 7
        min_corr_ratio_same = 0.55
        min_corr_ratio_cross = 0.7

        total_pairs = len(cooccurrences)
        pairs_too_few = 0
        pairs_below_threshold = 0
        pairs_low_confidence = 0
        near_miss_count = 0

        logger.info(f"Correlation patterns: {total_pairs} trigger entity/state combinations found")

        for (eid_a, state_a), targets in cooccurrences.items():
            total = sum(targets.values())
            if total < 5:
                pairs_too_few += 1
                continue

            for (eid_b, state_b), count in targets.items():
                ratio = count / total

                # Fix #8: Apply room-aware filtering
                room_a = entity_room_map.get(eid_a)
                room_b = entity_room_map.get(eid_b)
                same_room = (room_a is not None and room_b is not None and room_a == room_b)

                min_count = min_corr_count_same if same_room else min_corr_count_cross
                min_ratio = min_corr_ratio_same if same_room else min_corr_ratio_cross

                if ratio < min_ratio or count < min_count:
                    pairs_below_threshold += 1
                    # Log near-misses (within 80% of thresholds) for diagnosis
                    if near_miss_count < 5 and ratio >= min_ratio * 0.8 and count >= min_count * 0.8:
                        near_miss_count += 1
                        loc = "same-room" if same_room else "cross-room"
                        logger.debug(
                            f"Correlation near-miss ({loc}): {eid_a}={state_a} → {eid_b}={state_b} "
                            f"ratio={ratio:.2f} (need {min_ratio}), count={count} (need {min_count})"
                        )
                    continue

                confidence = min(ratio * (count / 14), 0.85)
                min_conf = 0.3 if same_room else 0.5
                if confidence < min_conf:
                    pairs_low_confidence += 1
                    continue

                pattern_data = {
                    "condition_entity": eid_a,
                    "condition_state": state_a,
                    "correlated_entity": eid_b,
                    "correlated_state": state_b,
                    "correlation_ratio": round(ratio, 3),
                    "occurrence_count": count,
                    "total_observations": total,
                    "same_room": same_room,
                }

                trigger_conditions = {
                    "type": "state",
                    "condition_entity": eid_a,
                    "condition_state": state_a,
                }

                action_def = {
                    "entity_id": eid_b,
                    "target_state": state_b,
                }

                # Fix #16: Use pre-fetched names
                name_a = entity_name_map.get(eid_a, eid_a)
                name_b = entity_name_map.get(eid_b, eid_b)

                desc_de = f"Wenn {name_a} = {state_a}, ist {name_b} meist {state_b} ({int(ratio*100)}%)"
                desc_en = f"When {name_a} = {state_a}, {name_b} is usually {state_b} ({int(ratio*100)}%)"

                dev_b = self._device_cache.get(eid_b)
                p = self._upsert_pattern(
                    session, f"{eid_a}↔{eid_b}", "correlation", pattern_data,
                    confidence, trigger_conditions, action_def,
                    desc_de, desc_en, dev_b
                )
                if p:
                    patterns_found.append(p)

        logger.info(
            f"Correlation patterns: {len(patterns_found)} created/updated, "
            f"{pairs_too_few} triggers with <5 observations, "
            f"{pairs_below_threshold} below ratio/count threshold, "
            f"{pairs_low_confidence} low confidence"
        )
        return patterns_found

    # --------------------------------------------------------------------------
    # B5: Pattern Decay
    # --------------------------------------------------------------------------

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _get_pattern_setting(self, session, key, default):
        """Read a setting from PatternSettings table, with fallback to default."""
        try:
            ps = session.query(PatternSettings).filter_by(key=key).first()
            if ps:
                return type(default)(ps.value)
        except Exception:
            pass
        return default

    def _cluster_by_time(self, occurrences, window_minutes=30):
        """Cluster events by time of day (ignoring date).

        Fix #2: Handles midnight wrap-around correctly.
        Events at 23:50 and 00:10 are now recognized as 20 minutes apart.
        """
        # Convert to minutes since midnight
        minutes_list = []
        for o in occurrences:
            m = o["hour"] * 60 + o["minute"]
            minutes_list.append((m, o))

        minutes_list.sort(key=lambda x: x[0])

        if not minutes_list:
            return []

        clusters = []
        current_cluster = [minutes_list[0]]

        for i in range(1, len(minutes_list)):
            if minutes_list[i][0] - current_cluster[-1][0] <= window_minutes:
                current_cluster.append(minutes_list[i])
            else:
                clusters.append([o for _, o in current_cluster])
                current_cluster = [minutes_list[i]]

        clusters.append([o for _, o in current_cluster])

        # Fix #2: Check if first and last cluster wrap around midnight
        if len(clusters) >= 2:
            first_cluster_min = min(o["hour"] * 60 + o["minute"] for o in clusters[0])
            last_cluster_max = max(o["hour"] * 60 + o["minute"] for o in clusters[-1])
            # Distance across midnight: (1440 - last) + first
            midnight_gap = (1440 - last_cluster_max) + first_cluster_min
            if midnight_gap <= window_minutes:
                # Merge first and last cluster
                merged = clusters[-1] + clusters[0]
                clusters = [merged] + clusters[1:-1]

        return clusters

    def _average_time(self, cluster):
        """Calculate average hour:minute from cluster.

        Fix #3: Uses circular averaging to handle midnight wrap-around.
        Events at 23:50 and 00:10 correctly average to ~00:00, not 12:00.
        """
        # Use circular mean via sin/cos to handle midnight wrap
        sin_sum = 0.0
        cos_sum = 0.0
        for o in cluster:
            minutes = o["hour"] * 60 + o["minute"]
            angle = (minutes / 1440.0) * 2 * math.pi  # Convert to radians
            sin_sum += math.sin(angle)
            cos_sum += math.cos(angle)

        avg_angle = math.atan2(sin_sum / len(cluster), cos_sum / len(cluster))
        if avg_angle < 0:
            avg_angle += 2 * math.pi
        avg_min = (avg_angle / (2 * math.pi)) * 1440.0
        return int(avg_min // 60) % 24, int(avg_min % 60)

    def _find_common_persons(self, contexts):
        """Find persons present in most contexts (>70%)."""
        if not contexts:
            return set()
        person_counts = defaultdict(int)
        for ctx in contexts:
            for p in ctx.get("persons_home", []):
                person_counts[p] += 1
        threshold = len(contexts) * 0.7
        return {p for p, c in person_counts.items() if c >= threshold}

    def _build_context_tags(self, pattern_data, pattern_type):
        """Phase 3: Build context tags for a pattern."""
        tags = {}
        if pattern_data.get("requires_persons"):
            tags["persons"] = pattern_data["requires_persons"]
        if pattern_data.get("weekday_filter"):
            tags["day_type"] = pattern_data["weekday_filter"]
        if pattern_data.get("sun_relative_elevation") is not None:
            tags["sun_relative"] = True
        return tags if tags else None

    def detect_scenes(self, session):
        """Phase 3: Detect recurring room state combinations as scenes."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            rooms = session.query(Room).filter_by(is_active=True).all()

            for room in rooms:
                devices = session.query(Device).filter_by(room_id=room.id, is_tracked=True).all()
                if len(devices) < 2:
                    continue

                entity_ids = [d.ha_entity_id for d in devices]

                # Group state snapshots by 5-minute windows
                snapshots = defaultdict(dict)
                for eid in entity_ids:
                    events = session.query(StateHistory).filter(
                        StateHistory.entity_id == eid,
                        StateHistory.created_at >= cutoff,
                    ).all()
                    for ev in events:
                        window_key = int(ev.created_at.timestamp() // 300)
                        snapshots[window_key][eid] = ev.new_state

                # Find recurring combinations (at least 2 devices active)
                state_combos = Counter()
                for wk, states in snapshots.items():
                    if len(states) < 2:
                        continue
                    key = tuple(sorted(states.items()))
                    state_combos[key] += 1

                # Create scenes from frequent combos
                for combo, count in state_combos.most_common(5):
                    if count < 3:
                        continue

                    states_dict = dict(combo)
                    states_list = [{"entity_id": eid, "state": st} for eid, st in states_dict.items()]

                    # Check if similar scene already exists
                    existing = session.query(LearnedScene).filter_by(
                        room_id=room.id, is_active=True
                    ).all()

                    is_duplicate = False
                    for ex in existing:
                        ex_eids = {s["entity_id"]: s["state"] for s in (ex.states or [])}
                        if ex_eids == states_dict:
                            ex.frequency = count
                            ex.last_detected = datetime.now(timezone.utc)
                            is_duplicate = True
                            break

                    if not is_duplicate and len(states_list) >= 2:
                        # Generate name based on dominant states
                        on_count = sum(1 for s in states_list if s["state"] == "on")
                        total = len(states_list)
                        if on_count == total:
                            name_de, name_en = f"{room.name} - Alles an", f"{room.name} - All on"
                        elif on_count == 0:
                            name_de, name_en = f"{room.name} - Alles aus", f"{room.name} - All off"
                        else:
                            name_de = f"{room.name} - Szene ({on_count}/{total})"
                            name_en = f"{room.name} - Scene ({on_count}/{total})"

                        scene = LearnedScene(
                            room_id=room.id,
                            name_de=name_de,
                            name_en=name_en,
                            states=states_list,
                            frequency=count,
                            status="detected",
                            source="auto",
                            last_detected=datetime.now(timezone.utc),
                        )
                        session.add(scene)
                        logger.info(f"New scene detected: {name_de} (frequency: {count})")

            session.commit()
        except Exception as e:
            logger.warning(f"Scene detection error: {e}")

    def _upsert_pattern(self, session, key_hint, pattern_type, pattern_data,
                        confidence, trigger_conditions, action_def,
                        desc_de, desc_en, device=None):
        """Create or update a pattern. Avoid duplicates.
        Also checks rejected/disabled patterns to prevent re-creation.

        Fix #18: Uses per-session cache to avoid repeated full-table queries.
        """
        # Fix #18: Cache existing patterns per type per session
        cache_key = f"_upsert_cache_{pattern_type}"
        if not hasattr(self, cache_key):
            cached = session.query(LearnedPattern).filter(
                LearnedPattern.pattern_type == pattern_type,
                or_(LearnedPattern.is_active == True, LearnedPattern.status.in_(["rejected", "disabled"])),
            ).all()
            setattr(self, cache_key, cached)
        existing_all = getattr(self, cache_key)

        # Find existing by type + entity combination
        # Include rejected/disabled patterns so they don't get re-created
        if pattern_type == "time_based":
            existing = existing_all
            for ep in existing:
                if (ep.pattern_data and
                    ep.pattern_data.get("entity_id") == pattern_data.get("entity_id") and
                    ep.pattern_data.get("target_state") == pattern_data.get("target_state") and
                    abs(ep.pattern_data.get("avg_hour", -1) - pattern_data.get("avg_hour", -2)) <= 0.5):
                    # Skip rejected/disabled patterns — don't recreate or update
                    if ep.status in ("rejected", "disabled"):
                        logger.debug(f"Skipping {ep.status} pattern {ep.id}: {ep.description_de}")
                        return None
                    # Update existing active pattern
                    ep.pattern_data = pattern_data
                    # Fix #4: Allow confidence to decrease (weighted average)
                    # Old behavior: max() meant confidence never dropped
                    ep.confidence = ep.confidence * 0.3 + confidence * 0.7
                    ep.trigger_conditions = trigger_conditions
                    ep.action_definition = action_def
                    ep.description_de = desc_de
                    ep.description_en = desc_en
                    ep.last_matched_at = datetime.now(timezone.utc)
                    ep.match_count += 1
                    ep.updated_at = datetime.now(timezone.utc)
                    ep.context_tags = self._build_context_tags(pattern_data, pattern_type)
                    return ep

        elif pattern_type == "event_chain":
            existing = existing_all
            for ep in existing:
                if (ep.pattern_data and
                    ep.pattern_data.get("trigger_entity") == pattern_data.get("trigger_entity") and
                    ep.pattern_data.get("action_entity") == pattern_data.get("action_entity") and
                    ep.pattern_data.get("trigger_state") == pattern_data.get("trigger_state") and
                    ep.pattern_data.get("action_state") == pattern_data.get("action_state")):
                    if ep.status in ("rejected", "disabled"):
                        logger.debug(f"Skipping {ep.status} pattern {ep.id}: {ep.description_de}")
                        return None
                    ep.pattern_data = pattern_data
                    # Fix #4: Allow confidence to decrease (weighted average)
                    # Old behavior: max() meant confidence never dropped
                    ep.confidence = ep.confidence * 0.3 + confidence * 0.7
                    ep.trigger_conditions = trigger_conditions
                    ep.action_definition = action_def
                    ep.description_de = desc_de
                    ep.description_en = desc_en
                    ep.last_matched_at = datetime.now(timezone.utc)
                    ep.match_count += 1
                    ep.updated_at = datetime.now(timezone.utc)
                    ep.context_tags = self._build_context_tags(pattern_data, pattern_type)
                    return ep

        elif pattern_type == "correlation":
            existing = existing_all
            for ep in existing:
                if (ep.pattern_data and
                    ep.pattern_data.get("condition_entity") == pattern_data.get("condition_entity") and
                    ep.pattern_data.get("correlated_entity") == pattern_data.get("correlated_entity") and
                    ep.pattern_data.get("condition_state") == pattern_data.get("condition_state") and
                    ep.pattern_data.get("correlated_state") == pattern_data.get("correlated_state")):
                    if ep.status in ("rejected", "disabled"):
                        logger.debug(f"Skipping {ep.status} pattern {ep.id}: {ep.description_de}")
                        return None
                    ep.pattern_data = pattern_data
                    # Fix #4: Allow confidence to decrease (weighted average)
                    # Old behavior: max() meant confidence never dropped
                    ep.confidence = ep.confidence * 0.3 + confidence * 0.7
                    ep.trigger_conditions = trigger_conditions
                    ep.action_definition = action_def
                    ep.description_de = desc_de
                    ep.description_en = desc_en
                    ep.last_matched_at = datetime.now(timezone.utc)
                    ep.match_count += 1
                    ep.updated_at = datetime.now(timezone.utc)
                    ep.context_tags = self._build_context_tags(pattern_data, pattern_type)
                    return ep

        # Create new pattern
        domain_id = None
        room_id = None
        if device:
            domain_id = device.domain_id
            room_id = device.room_id

        # Determine initial status: non-actionable entity patterns are "insight" (lower priority)
        initial_status = "observed"
        NON_ACTIONABLE = ("sensor.", "binary_sensor.", "sun.", "weather.", "zone.", "person.", "device_tracker.", "calendar.", "proximity.")
        if pattern_type == "time_based":
            # Time-based patterns for read-only entities are purely informational
            eid = pattern_data.get("entity_id", "")
            if any(eid.startswith(p) for p in NON_ACTIONABLE):
                initial_status = "insight"
        elif pattern_type == "event_chain":
            trigger_eid = pattern_data.get("trigger_entity", "")
            action_eid = pattern_data.get("action_entity", "")
            trigger_is_sensor = any(trigger_eid.startswith(p) for p in NON_ACTIONABLE)
            action_is_sensor = any(action_eid.startswith(p) for p in NON_ACTIONABLE)
            if trigger_is_sensor and action_is_sensor:
                initial_status = "insight"
        elif pattern_type == "correlation":
            cond_eid = pattern_data.get("condition_entity", "")
            corr_eid = pattern_data.get("correlated_entity", "")
            cond_is_sensor = any(cond_eid.startswith(p) for p in NON_ACTIONABLE)
            corr_is_sensor = any(corr_eid.startswith(p) for p in NON_ACTIONABLE)
            if cond_is_sensor and corr_is_sensor:
                initial_status = "insight"

        pattern = LearnedPattern(
            domain_id=domain_id or 1,
            room_id=room_id,
            pattern_type=pattern_type,
            pattern_data=pattern_data,
            confidence=confidence,
            trigger_conditions=trigger_conditions,
            action_definition=action_def,
            description_de=desc_de,
            description_en=desc_en,
            status=initial_status,
            is_active=True,
            last_matched_at=datetime.now(timezone.utc),
            match_count=1,
            # Phase 3: Context tags
            context_tags=self._build_context_tags(pattern_data, pattern_type),
        )
        session.add(pattern)
        # Fix #18: Add to cache so subsequent upsert calls see it
        cache_key = f"_upsert_cache_{pattern_type}"
        if hasattr(self, cache_key):
            getattr(self, cache_key).append(pattern)
        logger.info(f"New pattern: {pattern_type} - {desc_de[:80]}... (confidence: {confidence:.2f})")

        # First-time detection notification
        try:
            notification = NotificationLog(
                user_id=1,  # system notification
                notification_type=NotificationType.INFO,
                title=f"Neues Muster erkannt: {desc_de[:60]}",
                message=f"MindHome hat erstmals ein {pattern_type}-Muster erkannt. Confidence: {confidence:.0%}",
            )
            session.add(notification)
        except Exception as e:
            logger.debug(f"Could not create first-time notification: {e}")

        return pattern


# ==============================================================================
# Background Scheduler (H1 + B6)
# ==============================================================================

class PatternScheduler:
    """Manages background tasks: analysis, decay, cleanup, data tracking."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        self.ha = ha_connection
        self.detector = PatternDetector(engine)
        self.state_logger = StateLogger(engine, ha_connection)
        self._should_run = True
        self._threads = []

    def start(self):
        """Start all background tasks."""
        logger.info("Starting Pattern Scheduler...")

        # Analysis task: every 6 hours
        t1 = threading.Thread(target=self._run_periodic,
                              args=(self.detector.run_full_analysis, 6 * 3600, "pattern_analysis"),
                              daemon=True)
        t1.start()
        self._threads.append(t1)

        # Data collection size update: every 2 hours
        t2 = threading.Thread(target=self._run_periodic,
                              args=(self._update_storage_sizes, 2 * 3600, "storage_update"),
                              daemon=True)
        t2.start()
        self._threads.append(t2)

        # #22 Confidence decay: every 12 hours
        t3 = threading.Thread(target=self._run_periodic,
                              args=(self._run_confidence_decay, 12 * 3600, "confidence_decay"),
                              daemon=True)
        t3.start()
        self._threads.append(t3)

        # Phase 3: Scene detection: every 8 hours
        t4 = threading.Thread(target=self._run_periodic,
                              args=(self._run_scene_detection, 8 * 3600, "scene_detection"),
                              daemon=True)
        t4.start()
        self._threads.append(t4)

        logger.info("Pattern Scheduler started (analysis:6h, storage:2h, decay:12h, scenes:8h)")

    def stop(self):
        """Stop all background tasks."""
        self._should_run = False
        logger.info("Pattern Scheduler stopped")

    def _run_periodic(self, task_func, interval_seconds, task_name):
        """Run a task periodically with error handling."""
        # Initial delay: wait 60s after startup
        initial_delay = 60
        waited = 0
        while waited < initial_delay and self._should_run:
            time.sleep(5)
            waited += 5

        while self._should_run:
            try:
                logger.debug(f"Running scheduled task: {task_name}")
                task_func()
            except Exception as e:
                logger.error(f"Scheduled task {task_name} error: {e}")

            # Sleep in small increments so we can stop quickly
            slept = 0
            while slept < interval_seconds and self._should_run:
                time.sleep(10)
                slept += 10

    def _run_confidence_decay(self):
        """#22: Run confidence decay on stale patterns."""
        try:
            Session = self.Session if hasattr(self, 'Session') else sessionmaker(bind=self.engine)
            session = Session()
        except Exception as e:
            logger.warning(f"Confidence decay session error: {e}")
            return
        try:
            self.detector.apply_confidence_decay(session)
        except Exception as e:
            logger.warning(f"Confidence decay error: {e}")
        finally:
            session.close()

    def _update_storage_sizes(self):
        """Update storage_size_bytes in DataCollection entries."""
        Session = sessionmaker(bind=self.engine)
        session = Session()
        try:
            # Get DB file size
            db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")
            if os.path.exists(db_path):
                total_size = os.path.getsize(db_path)
            else:
                total_size = 0

            # Use no_autoflush: queries in the loop would otherwise trigger
            # a premature flush of pending updates, hitting SQLite locks
            with session.no_autoflush:
                # Count events per room/domain and estimate size
                counts = session.query(
                    StateHistory.device_id,
                    func.count(StateHistory.id).label("cnt")
                ).group_by(StateHistory.device_id).all()

                total_events = sum(c.cnt for c in counts)
                if total_events == 0:
                    return

                for row in counts:
                    if not row.device_id:
                        continue
                    device = session.get(Device, row.device_id)
                    if not device or not device.room_id:
                        continue

                    dc = session.query(DataCollection).filter_by(
                        room_id=device.room_id,
                        domain_id=device.domain_id,
                        data_type="state_changes"
                    ).first()

                    if dc:
                        # Proportional size estimate
                        dc.storage_size_bytes = int(total_size * (row.cnt / total_events))
                        dc.record_count = row.cnt

            session.commit()

        except Exception as e:
            session.rollback()
            logger.warning(f"Storage size update error: {e}")
        finally:
            session.close()

    def trigger_analysis_now(self):
        """Manually trigger pattern analysis (for API).
        Uses the same mutex-protected run_full_analysis."""
        t = threading.Thread(target=self.detector.run_full_analysis, daemon=True)
        t.start()
        return True

    def _run_scene_detection(self):
        """Phase 3: Run scene detection."""
        try:
            session = self.Session()
            self.detector.detect_scenes(session)
            session.close()
        except Exception as e:
            logger.warning(f"Scene detection scheduler error: {e}")


# ==============================================================================
# Event Bus (H2: Decouple state changes from handlers)
# ==============================================================================

class EventBus:
    """Simple event bus for decoupling HA events from handlers."""

    def __init__(self):
        self._handlers = defaultdict(list)

    def subscribe(self, event_type, handler):
        """Subscribe a handler to an event type."""
        self._handlers[event_type].append(handler)
        logger.debug(f"EventBus: subscribed {handler.__name__} to '{event_type}'")

    def publish(self, event_type, data):
        """Publish an event to all subscribers."""
        for handler in self._handlers.get(event_type, []):
            try:
                handler(data)
            except Exception as e:
                logger.error(f"EventBus handler error ({handler.__name__}): {e}")

    def subscriber_count(self, event_type):
        """Get number of subscribers for an event type."""
        return len(self._handlers.get(event_type, []))
