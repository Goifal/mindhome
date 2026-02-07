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
    SystemSetting, User, LearningPhase
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

    def __init__(self, ha_connection):
        self.ha = ha_connection

    def build(self):
        """Build current context snapshot."""
        now = datetime.now()
        hour = now.hour

        # Time slot
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

        ctx = {
            "time_slot": time_slot,
            "weekday": now.weekday(),  # 0=Mon, 6=Sun
            "is_weekend": now.weekday() >= 5,
            "hour": hour,
            "minute": now.minute,
            "persons_home": [],
            "sun_phase": "unknown",
            "sun_elevation": None,
            "outdoor_temp": None,
        }

        # Get person states (who is home?)
        try:
            states = self.ha.get_states() or []
            for s in states:
                eid = s.get("entity_id", "")
                state_val = s.get("state", "")

                # Person entities
                if eid.startswith("person.") and state_val == "home":
                    ctx["persons_home"].append(eid)

                # Sun entity
                if eid == "sun.sun":
                    attrs = s.get("attributes", {})
                    ctx["sun_phase"] = state_val  # "above_horizon" / "below_horizon"
                    ctx["sun_elevation"] = attrs.get("elevation")

                # Outdoor temperature (try common patterns)
                if (eid.startswith("weather.") or
                    "outdoor" in eid or "outside" in eid or "aussen" in eid or
                    "aussentemperatur" in eid):
                    attrs = s.get("attributes", {})
                    temp = attrs.get("temperature")
                    if temp is None:
                        try:
                            temp = float(state_val)
                        except (ValueError, TypeError):
                            pass
                    if temp is not None and ctx["outdoor_temp"] is None:
                        ctx["outdoor_temp"] = temp

        except Exception as e:
            logger.warning(f"Context build error: {e}")

        return ctx


# ==============================================================================
# State Logger (A1: State-Change Logger + A3: DataCollection Tracking)
# ==============================================================================

class StateLogger:
    """Logs significant state changes to state_history with context."""

    # Max events per minute (prevent DB flood from chatty devices)
    MAX_EVENTS_PER_MINUTE = 120

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        self.ha = ha_connection
        self.context_builder = ContextBuilder(ha_connection)

        # Motion sensor debounce tracking
        self._motion_last_on = {}  # entity_id -> datetime
        self._last_sensor_values = {}  # entity_id -> last_logged_value

        # Rate limiter: sliding window
        self._event_timestamps = []  # list of timestamps
        self._rate_limit_warned = False

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
            if not self._rate_limit_warned:
                logger.warning(f"Rate limit reached ({self.MAX_EVENTS_PER_MINUTE}/min), dropping events")
                self._rate_limit_warned = True
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
            logger.debug(f"Logged: {entity_id} {old_state} → {new_state}")

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

            # B1: Time-based patterns
            time_patterns = self._detect_time_patterns(session, events)

            # B2: Sequence patterns (event chains)
            sequence_patterns = self._detect_sequence_patterns(session, events)

            # B3: Correlation patterns
            correlation_patterns = self._detect_correlation_patterns(session, events)

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

        return patterns_found

    # --------------------------------------------------------------------------
    # B2: Sequence patterns (event chains)
    # --------------------------------------------------------------------------

    def _detect_sequence_patterns(self, session, events):
        """Find A→B event chains (within time window)."""
        patterns_found = []
        CHAIN_WINDOW = 300  # 5 minutes

        # Build pairs: for each event, what happened within 5 min after?
        pairs = defaultdict(int)
        pair_examples = defaultdict(list)

        for i, ev_a in enumerate(events):
            for j in range(i + 1, len(events)):
                ev_b = events[j]
                delta = (ev_b.created_at - ev_a.created_at).total_seconds()

                if delta > CHAIN_WINDOW:
                    break
                if delta < 2:  # Ignore near-simultaneous (likely same automation)
                    continue
                if ev_a.entity_id == ev_b.entity_id:
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

        # Filter: need at least 4 occurrences
        for (eid_a, state_a, eid_b, state_b), count in pairs.items():
            if count < 4:
                continue

            examples = pair_examples[(eid_a, state_a, eid_b, state_b)]
            avg_delta = sum(e["delta_seconds"] for e in examples) / len(examples)

            # Consistency check: is the delta consistent?
            deltas = [e["delta_seconds"] for e in examples]
            delta_std = (sum((d - avg_delta)**2 for d in deltas) / len(deltas))**0.5

            # Skip if timing is too variable (std > 60% of mean)
            if delta_std > avg_delta * 0.6 and avg_delta > 30:
                continue

            # Check person context consistency
            contexts_a = [e.get("context_a", {}) for e in examples if e.get("context_a")]
            common_persons = self._find_common_persons(contexts_a)

            confidence = min((count / 14) * 0.8, 0.90)
            if confidence < 0.3:
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
            desc_de = f"Wenn {name_a} {state_a_de} wird → {name_b} wird nach ~{delay_str} {state_b_de}"
            desc_en = f"When {name_a} turns {state_a} → {name_b} turns {state_b} after ~{delay_str}"

            p = self._upsert_pattern(
                session, f"{eid_a}→{eid_b}", "event_chain", pattern_data,
                confidence, trigger_conditions, action_def,
                desc_de, desc_en, dev_b
            )
            if p:
                patterns_found.append(p)

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
                    session, f"{eid_a}⇔{eid_b}", "correlation", pattern_data,
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
            status="observed",
            is_active=True,
            last_matched_at=datetime.now(timezone.utc),
            match_count=1,
        )
        session.add(pattern)
        logger.info(f"New pattern: {pattern_type} - {desc_de[:80]}... (confidence: {confidence:.2f})")
        return pattern


# ==============================================================================
# Background Scheduler (H1 + B6)
# ==============================================================================

class PatternScheduler:
    """Manages background tasks: analysis, decay, cleanup, data tracking."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
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

        logger.info("Pattern Scheduler started (analysis every 6h, storage update every 2h)")

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
