# MindHome Pattern Engine v0.5.2-phase3B (2026-02-08) - pattern_engine.py
"""
MindHome - Pattern Engine (Phase 2a)
Core intelligence: state logging, context building, pattern detection.
Runs as background service with scheduled analysis.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from sqlalchemy import func, text, and_, or_
from sqlalchemy.orm import sessionmaker

from models import (
    get_engine, StateHistory, LearnedPattern, PatternMatchLog,
    Device, Domain, Room, RoomDomainState, DataCollection,
    SystemSetting, User, LearningPhase, NotificationLog, NotificationType
)

logger = logging.getLogger("mindhome.pattern_engine")


# ==============================================================================
# Sampling Configuration (A4: Intelligent Sampling)
# ==============================================================================

# Minimum change thresholds per device_class / entity type
SAMPLING_THRESHOLDS = {
    "temperature":  0.5,   # only log if >= 0.5\u00b0 change
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
}

# These entity domains always log (binary on/off changes are always significant)
ALWAYS_LOG_DOMAINS = {
    "light", "switch", "lock", "cover", "climate", "fan",
    "media_player", "alarm_control_panel", "person", "device_tracker",
    "binary_sensor", "automation", "scene", "input_boolean",
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
            # #57 - dark detection
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
                    # #57 - dark detection
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
                    # #57 - dark detection
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
    MAX_EVENTS_PER_MINUTE = 300

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        self.ha = ha_connection
        self.context_builder = ContextBuilder(ha_connection, engine)

        # Motion sensor debounce tracking
        self._motion_last_on = {}  # entity_id -> datetime
        self._last_sensor_values = {}  # entity_id -> last_logged_value

        # Rate limiter: sliding window
        self._event_timestamps = []  # list of timestamps
        self._rate_limit_warned = False
        self._rate_limit_warn_time = None

    def should_log(self, entity_id, old_state, new_state, attributes):
        """A4: Intelligent sampling - decide if this state change is worth logging."""
        ha_domain = entity_id.split(".")[0]

        # Always log for important domains (binary state changes)
        if ha_domain in ALWAYS_LOG_DOMAINS:
            # Skip if state didn't actually change
            if old_state == new_state:
                return False

            # Motion sensor debounce
            device_class = attributes.get("device_class", "")
            if ha_domain == "binary_sensor" and device_class in ("motion", "occupancy"):
                if new_state == "on":
                    last_on = self._motion_last_on.get(entity_id)
                    now = datetime.now()
                    if last_on and (now - last_on).total_seconds() < MOTION_DEBOUNCE_SECONDS:
                        return False
                    self._motion_last_on[entity_id] = now
                # Always log motion "off" (end of presence)
            return True

        # For sensors: check threshold
        if ha_domain == "sensor":
            device_class = attributes.get("device_class", "")
            threshold = SAMPLING_THRESHOLDS.get(device_class)

            if threshold is not None:
                try:
                    new_val = float(new_state)
                    last_val = self._last_sensor_values.get(entity_id)

                    if last_val is not None and abs(new_val - last_val) < threshold:
                        return False

                    self._last_sensor_values[entity_id] = new_val
                    return True
                except (ValueError, TypeError):
                    return False

            # Unknown sensor type: don't log (too noisy)
            return False

        # Skip unknown domains
        return False

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

            # Build context
            ctx = self.context_builder.build()

            # Extract relevant attributes only (not full HA attribute dump)
            old_attrs_slim = self._slim_attributes(old_state_obj.get("attributes", {})) if old_state_obj else None
            new_attrs_slim = self._slim_attributes(new_attrs)

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
            if device and device.domain_id and device.room_id:
                self._update_data_collection(session, device)

            session.commit()
            self._event_timestamps.append(now)
            logger.debug(f"Logged: {entity_id} {old_state} \u2192 {new_state}")

            # B.4: Check manual rules
            self._check_manual_rules(session, entity_id, new_state, ctx)

        except Exception as e:
            session.rollback()
            logger.error(f"State log error: {e}")
        finally:
            session.close()

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

    def _update_data_collection(self, session, device):
        """A3: Update DataCollection tracking for transparency dashboard."""
        try:
            dc = session.query(DataCollection).filter_by(
                room_id=device.room_id,
                domain_id=device.domain_id,
                data_type="state_changes"
            ).first()

            now = datetime.now(timezone.utc)
            if dc:
                dc.record_count += 1
                dc.last_record_at = now
            else:
                dc = DataCollection(
                    room_id=device.room_id,
                    domain_id=device.domain_id,
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
                    h, m = map(int, conds["time_after"].split(":"))
                    if ctx["hour"] < h or (ctx["hour"] == h and ctx["minute"] < m):
                        continue
                if "time_before" in conds:
                    h, m = map(int, conds["time_before"].split(":"))
                    if ctx["hour"] > h or (ctx["hour"] == h and ctx["minute"] > m):
                        continue
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

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def run_full_analysis(self):
        """B6: Run complete pattern analysis (called by scheduler)."""
        logger.info("Starting pattern analysis...")
        session = self.Session()
        try:
            # Only analyze last 14 days of data, only MindHome-assigned devices
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            events = session.query(StateHistory).filter(
                StateHistory.created_at >= cutoff,
                StateHistory.device_id.isnot(None)
            ).order_by(StateHistory.created_at.asc()).all()

            if len(events) < 20:
                logger.info(f"Only {len(events)} events, need at least 20 for analysis")
                return

            logger.info(f"Analyzing {len(events)} events from last 14 days")

            # Load exclusions to filter patterns
            from models import PatternExclusion
            exclusions = session.query(PatternExclusion).all()
            excluded_pairs = set()
            for e in exclusions:
                excluded_pairs.add((e.entity_a, e.entity_b))
                excluded_pairs.add((e.entity_b, e.entity_a))

            # B1: Time-based patterns
            time_patterns = self._detect_time_patterns(session, events)

            # B2: Sequence patterns (event chains)
            sequence_patterns = self._detect_sequence_patterns(session, events)

            # B3: Correlation patterns (filter by exclusions)
            correlation_patterns = self._detect_correlation_patterns(session, events)

            # Filter out excluded pairs from correlation patterns
            for p in correlation_patterns:
                pd = p.pattern_data or {}
                ea = pd.get("entity_a", "")
                eb = pd.get("entity_b", "")
                if (ea, eb) in excluded_pairs:
                    p.is_active = False
                    p.status = "disabled"
                    logger.info(f"Pattern {p.id} disabled: excluded pair {ea} <-> {eb}")

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

            # B5: Apply decay to existing patterns
            self._apply_decay(session)

            total = len(time_patterns) + len(sequence_patterns) + len(correlation_patterns)
            logger.info(
                f"Analysis complete: {len(time_patterns)} time, "
                f"{len(sequence_patterns)} sequence, "
                f"{len(correlation_patterns)} correlation patterns"
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

    def _apply_domain_scoring(self, session):
        """B.7: Boost confidence based on domain-specific features."""
        try:
            patterns = session.query(LearnedPattern).filter_by(is_active=True).all()
            for p in patterns:
                pd = p.pattern_data or {}
                entity = pd.get("entity_id", "")
                ha_domain = entity.split(".")[0] if entity else ""

                boost = 0.0
                if ha_domain == "light" and p.pattern_type == "time_based":
                    if pd.get("attributes", {}).get("brightness"):
                        boost += 0.05
                elif ha_domain == "climate":
                    if p.season:
                        boost += 0.08
                elif ha_domain == "cover":
                    ctx = pd.get("typical_context", {})
                    if ctx.get("sun_elevation") is not None:
                        boost += 0.06
                elif ha_domain == "binary_sensor":
                    if p.match_count and p.match_count > 20:
                        boost += 0.04

                if boost > 0:
                    p.confidence = min(1.0, (p.confidence or 0) + boost)
        except Exception as e:
            logger.warning(f"Domain scoring error: {e}")

    def apply_confidence_decay(self, session):
        """#22: Decay confidence of patterns not matched recently."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            stale = session.query(LearnedPattern).filter(
                LearnedPattern.is_active == True,
                LearnedPattern.last_matched_at < cutoff,
                LearnedPattern.confidence > 0.1
            ).all()

            for p in stale:
                days_stale = (datetime.now(timezone.utc) - p.last_matched_at).days
                decay = 0.01 * (days_stale // 7)  # lose 1% per week of inactivity
                old_conf = p.confidence
                p.confidence = max(0.1, p.confidence - decay)
                if decay > 0:
                    logger.debug(f"Pattern {p.id} confidence decay: {old_conf:.2f} \u2192 {p.confidence:.2f} (stale {days_stale}d)")

            session.commit()
            if stale:
                logger.info(f"Confidence decay applied to {len(stale)} stale patterns")
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
            factors.append({"factor": "precise_time", "detail": f"\u00b1{tw}min window", "impact": "+precise"})

        return {
            "confidence": conf,
            "confidence_pct": f"{conf:.0%}",
            "factors": factors,
            "summary_de": f"Vertrauen {conf:.0%}: {mc} Treffer" + (f", zuletzt vor {days}d" if p.last_matched_at else ""),
            "summary_en": f"Confidence {conf:.0%}: {mc} matches" + (f", last {days}d ago" if p.last_matched_at else ""),
        }

    def detect_cross_room_correlations(self, session):
        """#56: Detect patterns across rooms (e.g. kitchen\u2192dining room)."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            history = session.query(StateHistory).filter(
                StateHistory.created_at > cutoff
            ).order_by(StateHistory.created_at).all()

            # Group by 60-second windows
            windows = {}
            for h in history:
                wk = int(h.created_at.timestamp() // 60)
                if wk not in windows:
                    windows[wk] = []
                windows[wk].append(h)

            # Find cross-room pairs
            correlations = []
            from collections import Counter
            pair_counter = Counter()
            for wk, events in windows.items():
                rooms = set()
                for e in events:
                    device = session.query(Device).filter_by(ha_entity_id=e.entity_id).first()
                    if device and device.room_id:
                        rooms.add(device.room_id)
                if len(rooms) >= 2:
                    for r1 in rooms:
                        for r2 in rooms:
                            if r1 < r2:
                                pair_counter[(r1, r2)] += 1

            for (r1, r2), count in pair_counter.most_common(5):
                if count >= 5:
                    room1 = session.query(Room).get(r1)
                    room2 = session.query(Room).get(r2)
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

        # Group events by (entity_id, new_state)
        groups = defaultdict(list)
        for ev in events:
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

        for (entity_id, new_state), occurrences in groups.items():
            if len(occurrences) < 4:
                continue

            # Cluster by time of day (within 30min window)
            time_clusters = self._cluster_by_time(occurrences)

            for cluster in time_clusters:
                if len(cluster) < 3:
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
                expected_days = 10 if is_weekday_only else (4 if is_weekend_only else 14)
                consistency = min(days_with_event / max(expected_days, 1), 1.0)

                # Confidence = frequency * consistency
                confidence = min((len(cluster) / 14) * consistency, 0.95)

                if confidence < 0.3:
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
                day_str_de = "werktags" if is_weekday_only else ("am Wochenende" if is_weekend_only else "t\u00e4glich")
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

        return patterns_found

    # --------------------------------------------------------------------------
    # B2: Sequence patterns (event chains)
    # --------------------------------------------------------------------------

    def _detect_sequence_patterns(self, session, events):
        """Find A\u2192B event chains (within time window)."""
        patterns_found = []
        CHAIN_WINDOW = 300  # 5 minutes
        MAX_NEW_PATTERNS = 20  # Rate limit: max new patterns per cycle

        def is_ignored_pair(eid_a, eid_b):
            """Check if this entity pair should be ignored."""
            a_is_sensor = eid_a.startswith("sensor.")
            b_is_sensor = eid_b.startswith("sensor.")
            if a_is_sensor and b_is_sensor:
                return True
            motion_prefixes = ("binary_sensor.motion", "binary_sensor.occupancy",
                             "binary_sensor.bewegung", "binary_sensor.prasenz")
            a_is_motion = any(eid_a.startswith(p) for p in motion_prefixes)
            b_is_motion = any(eid_b.startswith(p) for p in motion_prefixes)
            if a_is_motion and b_is_motion:
                return True
            return False

        pairs = defaultdict(int)
        pair_examples = defaultdict(list)

        for i, ev_a in enumerate(events):
            for j in range(i + 1, len(events)):
                ev_b = events[j]
                delta = (ev_b.created_at - ev_a.created_at).total_seconds()

                if delta > CHAIN_WINDOW:
                    break
                if delta < 2:
                    continue
                if ev_a.entity_id == ev_b.entity_id:
                    continue
                if is_ignored_pair(ev_a.entity_id, ev_b.entity_id):
                    continue

                key = (
                    ev_a.entity_id, ev_a.new_state,
                    ev_b.entity_id, ev_b.new_state
                )
                pairs[key] += 1
                if len(pair_examples[key]) < 20:
                    pair_examples[key].append({
                        "delta_seconds": delta,
                        "context_a": ev_a.context,
                        "context_b": ev_b.context,
                    })

        new_pattern_count = 0
        for (eid_a, state_a, eid_b, state_b), count in pairs.items():
            if count < 4:
                continue
            if new_pattern_count >= MAX_NEW_PATTERNS:
                break

            examples = pair_examples[(eid_a, state_a, eid_b, state_b)]
            avg_delta = sum(e["delta_seconds"] for e in examples) / len(examples)

            deltas = [e["delta_seconds"] for e in examples]
            delta_std = (sum((d - avg_delta)**2 for d in deltas) / len(deltas))**0.5

            if delta_std > avg_delta * 0.6 and avg_delta > 30:
                continue

            contexts_a = [e.get("context_a", {}) for e in examples if e.get("context_a")]
            common_persons = self._find_common_persons(contexts_a)

            confidence = min((count / 14) * 0.8, 0.90)
            if confidence < 0.55:
                continue

            pattern_data = {
                "trigger_entity": eid_a,
                "trigger_state": state_a,
                "action_entity": eid_b,
                "action_state": state_b,
                "avg_delay_seconds": round(avg_delta, 1),
                "delay_std": round(delta_std, 1),
                "occurrence_count": count,
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

            dev_a = session.query(Device).filter_by(ha_entity_id=eid_a).first()
            dev_b = session.query(Device).filter_by(ha_entity_id=eid_b).first()
            name_a = dev_a.name if dev_a else eid_a
            name_b = dev_b.name if dev_b else eid_b
            state_a_de = "eingeschaltet" if state_a == "on" else ("ausgeschaltet" if state_a == "off" else state_a)
            state_b_de = "eingeschaltet" if state_b == "on" else ("ausgeschaltet" if state_b == "off" else state_b)

            delay_str = f"{int(avg_delta)}s" if avg_delta < 60 else f"{int(avg_delta/60)} Min"
            desc_de = f"Wenn {name_a} {state_a_de} wird \u2192 {name_b} wird nach ~{delay_str} {state_b_de}"
            desc_en = f"When {name_a} turns {state_a} \u2192 {state_b} after ~{delay_str}"

            p = self._upsert_pattern(
                session, f"{eid_a}\u2192{eid_b}", "event_chain", pattern_data,
                confidence, trigger_conditions, action_def,
                desc_de, desc_en, dev_b
            )
            if p:
                patterns_found.append(p)
                new_pattern_count += 1

        return patterns_found

    # --------------------------------------------------------------------------
    # B3: Correlation patterns
    # --------------------------------------------------------------------------

    def _detect_correlation_patterns(self, session, events):
        """Find state correlations (when X is Y, Z is usually W)."""
        patterns_found = []

        # Build state snapshots: for each entity, when it changes,
        # what are the states of other entities?
        entity_states = {}  # current known state per entity

        cooccurrences = defaultdict(lambda: defaultdict(int))
        # cooccurrences[(entity_a, state_a)][(entity_b, state_b)] = count

        for ev in events:
            entity_states[ev.entity_id] = ev.new_state

            # Only check correlations for "important" state changes
            ha_domain = ev.entity_id.split(".")[0]
            if ha_domain not in {"person", "binary_sensor", "sun"} and ev.entity_id != "sun.sun":
                continue

            # Record what other entities are doing when this event happens
            for other_eid, other_state in entity_states.items():
                if other_eid == ev.entity_id:
                    continue
                other_domain = other_eid.split(".")[0]
                if other_domain in {"sensor", "weather"}:
                    continue  # Skip numeric sensors

                cooccurrences[(ev.entity_id, ev.new_state)][(other_eid, other_state)] += 1

        # Find strong correlations
        for (eid_a, state_a), targets in cooccurrences.items():
            total = sum(targets.values())
            if total < 5:
                continue

            for (eid_b, state_b), count in targets.items():
                ratio = count / total
                if ratio < 0.7 or count < 4:
                    continue

                confidence = min(ratio * (count / 14), 0.85)
                if confidence < 0.3:
                    continue

                pattern_data = {
                    "condition_entity": eid_a,
                    "condition_state": state_a,
                    "correlated_entity": eid_b,
                    "correlated_state": state_b,
                    "correlation_ratio": round(ratio, 3),
                    "occurrence_count": count,
                    "total_observations": total,
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

                dev_a = session.query(Device).filter_by(ha_entity_id=eid_a).first()
                dev_b = session.query(Device).filter_by(ha_entity_id=eid_b).first()
                name_a = dev_a.name if dev_a else eid_a
                name_b = dev_b.name if dev_b else eid_b

                desc_de = f"Wenn {name_a} = {state_a}, ist {name_b} meist {state_b} ({int(ratio*100)}%)"
                desc_en = f"When {name_a} = {state_a}, {name_b} is usually {state_b} ({int(ratio*100)}%)"

                p = self._upsert_pattern(
                    session, f"{eid_a}\u2192{corr_eid}", "correlation", pattern_data,
                    confidence, trigger_conditions, action_def,
                    desc_de, desc_en, dev_b
                )
                if p:
                    patterns_found.append(p)

        return patterns_found

    # --------------------------------------------------------------------------
    # B5: Pattern Decay
    # --------------------------------------------------------------------------

    def _apply_decay(self, session):
        """Reduce confidence of patterns that haven't matched recently."""
        DECAY_PER_DAY = 0.05
        DEACTIVATE_THRESHOLD = 0.1

        patterns = session.query(LearnedPattern).filter_by(is_active=True).all()
        now = datetime.now(timezone.utc)

        for p in patterns:
            if p.last_matched_at:
                days_inactive = (now - p.last_matched_at).days
            else:
                days_inactive = (now - p.created_at).days

            if days_inactive > 2:  # Grace period: 2 days
                decay = DECAY_PER_DAY * (days_inactive - 2)
                p.confidence = max(p.confidence - decay, 0.0)

                if p.confidence < DEACTIVATE_THRESHOLD:
                    p.is_active = False
                    p.status = "disabled"
                    logger.info(f"Pattern {p.id} deactivated (confidence {p.confidence:.2f})")

        logger.debug(f"Decay applied to {len(patterns)} patterns")

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _cluster_by_time(self, occurrences, window_minutes=30):
        """Cluster events by time of day (ignoring date)."""
        # Convert to minutes since midnight
        minutes_list = []
        for o in occurrences:
            m = o["hour"] * 60 + o["minute"]
            minutes_list.append((m, o))

        minutes_list.sort(key=lambda x: x[0])
        clusters = []
        current_cluster = [minutes_list[0]]

        for i in range(1, len(minutes_list)):
            if minutes_list[i][0] - current_cluster[-1][0] <= window_minutes:
                current_cluster.append(minutes_list[i])
            else:
                clusters.append([o for _, o in current_cluster])
                current_cluster = [minutes_list[i]]

        clusters.append([o for _, o in current_cluster])
        return clusters

    def _average_time(self, cluster):
        """Calculate average hour:minute from cluster."""
        total_min = sum(o["hour"] * 60 + o["minute"] for o in cluster)
        avg_min = total_min / len(cluster)
        return int(avg_min // 60), int(avg_min % 60)

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

    def _upsert_pattern(self, session, key_hint, pattern_type, pattern_data,
                        confidence, trigger_conditions, action_def,
                        desc_de, desc_en, device=None):
        """Create or update a pattern. Avoid duplicates."""
        # Find existing by type + entity combination
        if pattern_type == "time_based":
            existing = session.query(LearnedPattern).filter_by(
                pattern_type=pattern_type,
                is_active=True,
            ).all()
            for ep in existing:
                if (ep.pattern_data and
                    ep.pattern_data.get("entity_id") == pattern_data.get("entity_id") and
                    ep.pattern_data.get("target_state") == pattern_data.get("target_state") and
                    abs(ep.pattern_data.get("avg_hour", -1) - pattern_data.get("avg_hour", -2)) <= 1):
                    # Update existing
                    ep.pattern_data = pattern_data
                    ep.confidence = max(ep.confidence, confidence)
                    ep.trigger_conditions = trigger_conditions
                    ep.action_definition = action_def
                    ep.description_de = desc_de
                    ep.description_en = desc_en
                    ep.last_matched_at = datetime.now(timezone.utc)
                    ep.match_count += 1
                    ep.updated_at = datetime.now(timezone.utc)
                    return ep

        elif pattern_type == "event_chain":
            existing = session.query(LearnedPattern).filter_by(
                pattern_type=pattern_type,
                is_active=True,
            ).all()
            for ep in existing:
                if (ep.pattern_data and
                    ep.pattern_data.get("trigger_entity") == pattern_data.get("trigger_entity") and
                    ep.pattern_data.get("action_entity") == pattern_data.get("action_entity")):
                    ep.pattern_data = pattern_data
                    ep.confidence = max(ep.confidence, confidence)
                    ep.trigger_conditions = trigger_conditions
                    ep.action_definition = action_def
                    ep.description_de = desc_de
                    ep.description_en = desc_en
                    ep.last_matched_at = datetime.now(timezone.utc)
                    ep.match_count += 1
                    ep.updated_at = datetime.now(timezone.utc)
                    return ep

        elif pattern_type == "correlation":
            existing = session.query(LearnedPattern).filter_by(
                pattern_type=pattern_type,
                is_active=True,
            ).all()
            for ep in existing:
                if (ep.pattern_data and
                    ep.pattern_data.get("condition_entity") == pattern_data.get("condition_entity") and
                    ep.pattern_data.get("correlated_entity") == pattern_data.get("correlated_entity")):
                    ep.pattern_data = pattern_data
                    ep.confidence = max(ep.confidence, confidence)
                    ep.trigger_conditions = trigger_conditions
                    ep.action_definition = action_def
                    ep.description_de = desc_de
                    ep.description_en = desc_en
                    ep.last_matched_at = datetime.now(timezone.utc)
                    ep.match_count += 1
                    ep.updated_at = datetime.now(timezone.utc)
                    return ep

        # Create new pattern
        domain_id = None
        room_id = None
        if device:
            domain_id = device.domain_id
            room_id = device.room_id

        # Determine initial status: sensor\u2192sensor patterns are "insight" (lower priority)
        initial_status = "observed"
        NON_ACTIONABLE = ("sensor.", "binary_sensor.", "sun.", "weather.", "zone.", "person.", "device_tracker.", "calendar.", "proximity.")
        if pattern_type == "event_chain":
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
        )
        session.add(pattern)
        logger.info(f"New pattern: {pattern_type} - {desc_de[:80]}... (confidence: {confidence:.2f})")

        # First-time detection notification
        try:
            notification = NotificationLog(
                notification_type=NotificationType.INFO,
                title_de=f"Neues Muster erkannt: {desc_de[:60]}",
                title_en=f"New pattern detected: {desc_en[:60]}",
                message_de=f"MindHome hat erstmals ein {pattern_type}-Muster erkannt. Confidence: {confidence:.0%}",
                message_en=f"MindHome detected a {pattern_type} pattern for the first time. Confidence: {confidence:.0%}",
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

        logger.info("Pattern Scheduler started (analysis:6h, storage:2h, decay:12h)")

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
        """Manually trigger pattern analysis (for API)."""
        t = threading.Thread(target=self.detector.run_full_analysis, daemon=True)
        t.start()
        return True


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
