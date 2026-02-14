# MindHome ML/automation_engine v0.7.0 (2026-02-14) - ml/automation_engine.py
"""
MindHome - Automation Engine (Phase 2b + Phase 3)
Suggestions, execution, undo, conflict detection, phase management.
Phase 3: Presence modes, plugin conflicts, quiet hours, holiday awareness.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from sqlalchemy import func, text, and_
from sqlalchemy.orm import sessionmaker

from models import (
    get_engine, LearnedPattern, Prediction, Device, Domain, Room,
    RoomDomainState, LearningPhase, ActionLog, NotificationLog,
    NotificationType, NotificationSetting, SystemSetting, StateHistory,
    PresenceMode, PresenceLog, PluginSetting, QuietHoursConfig,
    LearnedScene, DayPhase, PatternSettings, AnomalySetting,
    PersonDevice, GuestDevice,
)

logger = logging.getLogger("mindhome.automation_engine")


# ==============================================================================
# Configuration
# ==============================================================================

# E4: Safety thresholds - critical domains need higher confidence
DOMAIN_THRESHOLDS = {
    "lock":                 {"suggest": 0.85, "auto": 0.95},
    "alarm_control_panel":  {"suggest": 0.85, "auto": 0.95},
    "climate":              {"suggest": 0.6,  "auto": 0.85},
    "cover":                {"suggest": 0.5,  "auto": 0.8},
    "light":                {"suggest": 0.5,  "auto": 0.75},
    "switch":               {"suggest": 0.5,  "auto": 0.75},
    "fan":                  {"suggest": 0.5,  "auto": 0.75},
    "media_player":         {"suggest": 0.5,  "auto": 0.75},
    "_default":             {"suggest": 0.5,  "auto": 0.8},
}

# D5: Time window for execution tolerance
EXECUTION_TIME_WINDOW_MIN = 10

# D3: Undo window
UNDO_WINDOW_MINUTES = 30

# Anomaly: how many standard deviations counts as anomaly
ANOMALY_THRESHOLD_HOURS = 2  # e.g. light on at 3 AM when pattern says never


# ==============================================================================
# C1: Suggestion Generator
# ==============================================================================

class SuggestionGenerator:
    """Creates suggestions from high-confidence observed patterns."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def generate_suggestions(self):
        """Check observed patterns and promote to suggestions if ready."""
        session = self.Session()
        try:
            # Find patterns that are 'observed' with high enough confidence
            patterns = session.query(LearnedPattern).filter_by(
                status="observed", is_active=True
            ).all()

            count = 0
            for pattern in patterns:
                ha_domain = self._get_ha_domain(pattern)
                thresholds = DOMAIN_THRESHOLDS.get(ha_domain, DOMAIN_THRESHOLDS["_default"])

                if pattern.confidence >= thresholds["suggest"]:
                    # Check phase: room/domain must be at least SUGGESTING
                    if not self._check_phase_allows(session, pattern, LearningPhase.SUGGESTING):
                        continue

                    # Don't re-suggest patterns rejected 3+ times
                    if pattern.times_rejected >= 3:
                        continue

                    # Promote to suggested
                    pattern.status = "suggested"
                    pattern.updated_at = datetime.now(timezone.utc)

                    # Create prediction (suggestion entry)
                    prediction = Prediction(
                        pattern_id=pattern.id,
                        predicted_action=pattern.action_definition or {},
                        predicted_for=datetime.now(timezone.utc),
                        confidence=pattern.confidence,
                        status="pending",
                        description_de=pattern.description_de,
                        description_en=pattern.description_en,
                    )
                    session.add(prediction)
                    count += 1

                    logger.info(f"New suggestion from pattern {pattern.id}: {pattern.description_de or pattern.pattern_type}")

            session.commit()
            if count > 0:
                logger.info(f"Generated {count} new suggestions")
            return count

        except Exception as e:
            session.rollback()
            logger.error(f"Suggestion generation error: {e}")
            return 0
        finally:
            session.close()

    def _get_ha_domain(self, pattern):
        """Extract HA domain from pattern data."""
        action = pattern.action_definition or {}
        entity_id = action.get("entity_id", "")
        return entity_id.split(".")[0] if entity_id else "_default"

    def _check_phase_allows(self, session, pattern, min_phase):
        """Check if the room/domain learning phase allows this action."""
        if not pattern.room_id or not pattern.domain_id:
            return True  # No room/domain = allow

        rds = session.query(RoomDomainState).filter_by(
            room_id=pattern.room_id,
            domain_id=pattern.domain_id
        ).first()

        if not rds:
            return False

        if rds.is_paused:
            return False

        phase_order = {
            LearningPhase.OBSERVING: 0,
            LearningPhase.SUGGESTING: 1,
            LearningPhase.AUTONOMOUS: 2,
        }
        current = phase_order.get(rds.learning_phase, 0)
        required = phase_order.get(min_phase, 1)
        return current >= required


# ==============================================================================
# C4: Feedback Processor
# ==============================================================================

class FeedbackProcessor:
    """Processes user responses to suggestions (confirm/reject)."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def confirm_prediction(self, prediction_id):
        """User confirmed a suggestion."""
        session = self.Session()
        try:
            pred = session.get(Prediction, prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            pred.status = "confirmed"
            pred.user_response = "confirmed"
            pred.responded_at = datetime.now(timezone.utc)

            # Update pattern confidence
            pattern = session.get(LearnedPattern, pred.pattern_id)
            if pattern:
                pattern.confidence = min(pattern.confidence + 0.15, 1.0)
                pattern.times_confirmed += 1
                pattern.status = "active"
                pattern.updated_at = datetime.now(timezone.utc)

            session.commit()
            logger.info(f"Prediction {prediction_id} confirmed → pattern {pred.pattern_id} activated")
            return {"success": True, "status": "confirmed"}

        except Exception as e:
            session.rollback()
            logger.error(f"Confirm error: {e}")
            return {"error": str(e)}
        finally:
            session.close()

    def reject_prediction(self, prediction_id):
        """User rejected a suggestion."""
        session = self.Session()
        try:
            pred = session.get(Prediction, prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            pred.status = "rejected"
            pred.user_response = "rejected"
            pred.responded_at = datetime.now(timezone.utc)

            # Decrease pattern confidence
            pattern = session.get(LearnedPattern, pred.pattern_id)
            if pattern:
                pattern.confidence = max(pattern.confidence - 0.2, 0.0)
                pattern.times_rejected += 1

                # Deactivate if rejected 3+ times
                if pattern.times_rejected >= 3:
                    pattern.is_active = False
                    pattern.status = "disabled"
                    logger.info(f"Pattern {pattern.id} disabled after 3 rejections")
                else:
                    pattern.status = "observed"  # Back to observing

                pattern.updated_at = datetime.now(timezone.utc)

            session.commit()
            logger.info(f"Prediction {prediction_id} rejected → confidence decreased")
            return {"success": True, "status": "rejected"}

        except Exception as e:
            session.rollback()
            logger.error(f"Reject error: {e}")
            return {"error": str(e)}
        finally:
            session.close()

    def ignore_prediction(self, prediction_id):
        """User chose 'later' / ignored."""
        session = self.Session()
        try:
            pred = session.get(Prediction, prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            pred.status = "ignored"
            pred.user_response = "ignored"
            pred.responded_at = datetime.now(timezone.utc)
            session.commit()
            return {"success": True, "status": "ignored"}
        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()


# ==============================================================================
# D1-D5: Automation Executor
# ==============================================================================

class AutomationExecutor:
    """Executes confirmed automations via HA service calls."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.ha = ha_connection
        self.Session = sessionmaker(bind=engine)
        self._emergency_stop = False

    def set_emergency_stop(self, active):
        """Emergency stop: halt all automations."""
        self._emergency_stop = active
        logger.warning(f"Emergency stop {'ACTIVATED' if active else 'deactivated'}")

    def check_and_execute(self):
        """D1+D5: Check active patterns and execute if conditions match."""
        if self._emergency_stop:
            return

        session = self.Session()
        try:
            # #23 Vacation mode check
            vac = session.execute(
                text("SELECT value FROM system_settings WHERE key='vacation_mode'")
            ).fetchone()
            is_vacation = vac and vac[0] == "true"

            # #55 Absence simulation check
            simulate = False
            if is_vacation:
                sim = session.execute(
                    text("SELECT value FROM system_settings WHERE key='vacation_simulate'")
                ).fetchone()
                simulate = sim and sim[0] == "true"

            active_patterns = session.query(LearnedPattern).filter_by(
                status="active", is_active=True
            ).all()

            # Fix #10: Load exclusions for runtime filtering
            from models import PatternExclusion
            exclusions = session.query(PatternExclusion).all()
            excluded_pairs = set()
            for exc in exclusions:
                excluded_pairs.add((exc.entity_a, exc.entity_b))
                excluded_pairs.add((exc.entity_b, exc.entity_a))

            now = datetime.now(timezone.utc)

            for pattern in active_patterns:
                trigger = pattern.trigger_conditions or {}
                trigger_type = trigger.get("type")

                # Fix #5: Check confidence against domain-specific thresholds
                action = pattern.action_definition or {}
                entity_id = action.get("entity_id", "")
                ha_domain = entity_id.split(".")[0] if entity_id else "_default"
                thresholds = DOMAIN_THRESHOLDS.get(ha_domain, DOMAIN_THRESHOLDS["_default"])
                if pattern.confidence < thresholds["auto"]:
                    logger.debug(
                        f"Pattern {pattern.id}: confidence {pattern.confidence:.2f} "
                        f"< threshold {thresholds['auto']} for {ha_domain}, skipping"
                    )
                    continue

                # Fix #10: Check exclusions at runtime (not just at analysis time)
                trigger_entity = trigger.get("trigger_entity") or trigger.get("condition_entity", "")
                action_entity = entity_id
                if (trigger_entity, action_entity) in excluded_pairs:
                    logger.debug(f"Pattern {pattern.id}: excluded pair {trigger_entity} <-> {action_entity}")
                    continue

                # #23 Skip non-essential automations in vacation mode
                # but #55 allow light toggles if simulation is on
                if is_vacation and not simulate:
                    continue
                if is_vacation and simulate:
                    if not entity_id.startswith("light."):
                        continue

                if trigger_type == "time":
                    self._check_time_trigger(session, pattern, trigger, now)

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Automation check error: {e}")
        finally:
            session.close()

    def _check_time_trigger(self, session, pattern, trigger, now):
        """D5: Time-window based execution check."""
        target_hour = trigger.get("hour", -1)
        target_minute = trigger.get("minute", 0)
        window = trigger.get("window_min", EXECUTION_TIME_WINDOW_MIN)

        # Check weekday filter
        if trigger.get("weekdays_only") and now.weekday() >= 5:
            return
        if trigger.get("weekends_only") and now.weekday() < 5:
            return

        # Check if within time window
        target_minutes = target_hour * 60 + target_minute
        current_minutes = now.hour * 60 + now.minute
        diff = abs(current_minutes - target_minutes)

        if diff > window:
            return

        # Check person requirements
        required_persons = trigger.get("requires_persons", [])
        if required_persons:
            states = self.ha.get_states() or []
            home_persons = [s["entity_id"] for s in states
                          if s.get("entity_id", "").startswith("person.") and s.get("state") == "home"]
            if not all(p in home_persons for p in required_persons):
                return

        # Check if already executed today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        already_executed = session.query(Prediction).filter(
            Prediction.pattern_id == pattern.id,
            Prediction.status == "executed",
            Prediction.executed_at >= today_start
        ).first()

        if already_executed:
            return

        # D5: Check if user already did this action manually within the window
        action = pattern.action_definition or {}
        entity_id = action.get("entity_id")
        target_state = action.get("target_state")

        if entity_id and target_state:
            recent_manual = session.query(StateHistory).filter(
                StateHistory.entity_id == entity_id,
                StateHistory.new_state == target_state,
                StateHistory.created_at >= now - timedelta(minutes=window)
            ).first()

            if recent_manual:
                logger.debug(f"Pattern {pattern.id}: user already did this manually, skipping")
                return

        # D4: Validate current state
        if entity_id:
            current = self._get_current_state(entity_id)
            if current == target_state:
                logger.debug(f"Pattern {pattern.id}: {entity_id} already in state {target_state}")
                return

        # Execute!
        self._execute_action(session, pattern, action)

    def _execute_action(self, session, pattern, action):
        """D2: Execute action via HA service call."""
        entity_id = action.get("entity_id")
        target_state = action.get("target_state")

        if not entity_id or not target_state:
            return

        # D3: Save current state for undo
        previous_state = self._get_current_state(entity_id)

        # D4: Check device reachability
        if previous_state == "unavailable":
            logger.warning(f"Device {entity_id} unavailable, skipping automation")
            return

        # Check room privacy
        device = session.query(Device).filter_by(ha_entity_id=entity_id).first()
        if device and device.room_id:
            room = session.get(Room, device.room_id)
            if room and room.privacy_mode:
                domain = session.get(Domain, device.domain_id) if device.domain_id else None
                if domain and room.privacy_mode.get(domain.name) is False:
                    logger.debug(f"Privacy blocks automation for {entity_id}")
                    return

        # Execute via HA
        ha_domain = entity_id.split(".")[0]
        service = "turn_on" if target_state == "on" else "turn_off"

        # Special handling for covers/climate
        if ha_domain == "cover":
            service = "open_cover" if target_state in ("on", "open") else "close_cover"
        elif ha_domain == "climate":
            service = "set_hvac_mode"

        try:
            service_data = {"entity_id": entity_id}
            if ha_domain == "climate" and target_state not in ("on", "off"):
                service_data["hvac_mode"] = target_state

            self.ha.call_service(ha_domain, service, service_data)

            # Update pattern's last_matched_at on execution
            pattern.last_matched_at = datetime.now(timezone.utc)

            # Create execution record
            prediction = Prediction(
                pattern_id=pattern.id,
                predicted_action=action,
                predicted_for=datetime.now(timezone.utc),
                confidence=pattern.confidence,
                status="executed",
                was_executed=True,
                previous_state={"entity_id": entity_id, "state": previous_state},
                executed_at=datetime.now(timezone.utc),
                description_de=pattern.description_de,
                description_en=pattern.description_en,
            )
            session.add(prediction)

            # Log to action log
            log = ActionLog(
                action_type="automation",
                domain_id=pattern.domain_id,
                room_id=pattern.room_id,
                device_id=device.id if device else None,
                action_data={
                    "entity_id": entity_id,
                    "service": f"{ha_domain}.{service}",
                    "target_state": target_state,
                    "previous_state": previous_state,
                    "pattern_id": pattern.id,
                    "confidence": pattern.confidence,
                },
                reason=f"Automation: {pattern.description_de or pattern.pattern_type}",
            )
            session.add(log)

            logger.info(f"Executed: {entity_id} → {target_state} (pattern {pattern.id}, confidence {pattern.confidence:.2f})")

        except Exception as e:
            logger.error(f"Execution failed for {entity_id}: {e}")

    def undo_prediction(self, prediction_id):
        """D3: Undo an executed automation."""
        session = self.Session()
        try:
            pred = session.get(Prediction, prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            if pred.status != "executed":
                return {"error": "Can only undo executed predictions"}

            # Check undo window
            if pred.executed_at:
                elapsed = (datetime.now(timezone.utc) - pred.executed_at).total_seconds() / 60
                if elapsed > UNDO_WINDOW_MINUTES:
                    return {"error": f"Undo window expired ({UNDO_WINDOW_MINUTES} min)"}

            # Restore previous state
            prev = pred.previous_state
            if not prev or "entity_id" not in prev:
                return {"error": "No previous state saved"}

            entity_id = prev["entity_id"]
            restore_state = prev["state"]

            if restore_state and restore_state not in ("unavailable", "unknown"):
                ha_domain = entity_id.split(".")[0]
                service = "turn_on" if restore_state == "on" else "turn_off"

                if ha_domain == "cover":
                    service = "open_cover" if restore_state in ("on", "open") else "close_cover"

                self.ha.call_service(ha_domain, service, {"entity_id": entity_id})

            pred.status = "undone"
            pred.undone_at = datetime.now(timezone.utc)

            # #53: Learn from undo - reduce confidence more if repeated
            pattern = session.get(LearnedPattern, pred.pattern_id)
            if pattern:
                # Count how many times this pattern has been undone
                undo_count = session.query(Prediction).filter(
                    Prediction.pattern_id == pattern.id,
                    Prediction.status == "undone"
                ).count()
                # First undo: -0.1, second: -0.15, third+: -0.2
                decay = min(0.2, 0.1 + (undo_count * 0.05))
                pattern.confidence = max(0.0, pattern.confidence - decay)
                pattern.updated_at = datetime.now(timezone.utc)
                logger.info(f"Pattern {pattern.id} confidence -{decay:.2f} (undo #{undo_count+1})")

                # If confidence drops below 0.15, deactivate
                if pattern.confidence < 0.15:
                    pattern.is_active = False
                    pattern.status = "rejected"
                    pattern.rejection_reason = "auto_deactivated_by_undos"
                    logger.info(f"Pattern {pattern.id} auto-deactivated after {undo_count+1} undos")

            session.commit()
            logger.info(f"Undone prediction {prediction_id}: {entity_id} → {restore_state}")
            return {"success": True, "restored_state": restore_state}

        except Exception as e:
            session.rollback()
            logger.error(f"Undo error: {e}")
            return {"error": str(e)}
        finally:
            session.close()

    def _get_current_state(self, entity_id):
        """Get current state of an entity from HA."""
        try:
            states = self.ha.get_states() or []
            for s in states:
                if s.get("entity_id") == entity_id:
                    return s.get("state", "unknown")
        except Exception:
            pass
        return "unknown"


# ==============================================================================
# Conflict Detector
# ==============================================================================

class ConflictDetector:
    """Detects conflicting patterns/automations."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def check_conflicts(self):
        """Find active patterns that conflict with each other."""
        session = self.Session()
        try:
            active = session.query(LearnedPattern).filter_by(
                status="active", is_active=True
            ).all()

            conflicts = []
            for i, p1 in enumerate(active):
                a1 = p1.action_definition or {}
                e1 = a1.get("entity_id")
                if not e1:
                    continue

                for p2 in active[i+1:]:
                    a2 = p2.action_definition or {}
                    e2 = a2.get("entity_id")

                    if e1 != e2:
                        continue

                    # Same entity, different target states
                    s1 = a1.get("target_state")
                    s2 = a2.get("target_state")
                    if s1 == s2:
                        continue

                    # Check if they could fire at similar times
                    t1 = p1.trigger_conditions or {}
                    t2 = p2.trigger_conditions or {}

                    if t1.get("type") == "time" and t2.get("type") == "time":
                        h1, m1 = t1.get("hour", -1), t1.get("minute", 0)
                        h2, m2 = t2.get("hour", -1), t2.get("minute", 0)
                        diff = abs((h1 * 60 + m1) - (h2 * 60 + m2))
                        if diff <= 30:
                            conflicts.append({
                                "pattern_a": p1.id,
                                "pattern_b": p2.id,
                                "entity": e1,
                                "state_a": s1,
                                "state_b": s2,
                                "type": "time_overlap",
                                "resolution": "higher_confidence",
                                "winner": p1.id if p1.confidence >= p2.confidence else p2.id,
                            })

            return conflicts

        except Exception as e:
            logger.error(f"Conflict check error: {e}")
            return []
        finally:
            session.close()
# ==============================================================================

class PhaseManager:
    """Manages learning phase transitions per room/domain."""

    # E1: Thresholds for phase transitions
    OBSERVE_TO_SUGGEST = {
        "min_days": 7,
        "min_events": 50,
        "min_patterns": 2,
        "min_avg_confidence": 0.4,
    }
    SUGGEST_TO_AUTONOMOUS = {
        "min_days": 14,
        "min_confirmed": 3,
        "min_avg_confidence": 0.7,
    }

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def check_transitions(self):
        """E1: Check all room/domain states for phase transitions."""
        session = self.Session()
        try:
            states = session.query(RoomDomainState).filter_by(is_paused=False).all()
            transitions = 0

            for rds in states:
                current = rds.learning_phase
                new_phase = self._evaluate_phase(session, rds)

                if new_phase and new_phase != current:
                    old_name = current.value if current else "none"
                    rds.learning_phase = new_phase
                    rds.phase_started_at = datetime.now(timezone.utc)
                    transitions += 1

                    room = session.get(Room, rds.room_id)
                    domain = session.get(Domain, rds.domain_id)
                    room_name = room.name if room else f"Room {rds.room_id}"
                    domain_name = domain.name if domain else f"Domain {rds.domain_id}"

                    logger.info(f"Phase transition: {room_name}/{domain_name} {old_name} → {new_phase.value}")

            session.commit()
            if transitions:
                logger.info(f"{transitions} phase transitions completed")
            return transitions

        except Exception as e:
            session.rollback()
            logger.error(f"Phase check error: {e}")
            return 0
        finally:
            session.close()

    def _evaluate_phase(self, session, rds):
        """Evaluate if a room/domain should transition to next phase."""
        current = rds.learning_phase

        if current == LearningPhase.OBSERVING:
            return self._check_observe_to_suggest(session, rds)
        elif current == LearningPhase.SUGGESTING:
            return self._check_suggest_to_autonomous(session, rds)
        return None

    def _check_observe_to_suggest(self, session, rds):
        """Can we move from observing to suggesting?"""
        t = self.OBSERVE_TO_SUGGEST

        # Days since phase started
        if rds.phase_started_at:
            days = (datetime.utcnow().replace(tzinfo=None) - rds.phase_started_at.replace(tzinfo=None)).days
            if days < t["min_days"]:
                return None

        # Count events for this room/domain
        devices = session.query(Device).filter_by(
            room_id=rds.room_id, domain_id=rds.domain_id
        ).all()
        device_ids = [d.id for d in devices]

        if not device_ids:
            return None

        event_count = session.query(func.count(StateHistory.id)).filter(
            StateHistory.device_id.in_(device_ids)
        ).scalar() or 0

        if event_count < t["min_events"]:
            return None

        # Count patterns
        pattern_count = session.query(func.count(LearnedPattern.id)).filter_by(
            room_id=rds.room_id, domain_id=rds.domain_id, is_active=True
        ).scalar() or 0

        if pattern_count < t["min_patterns"]:
            return None

        # Avg confidence
        avg_conf = session.query(func.avg(LearnedPattern.confidence)).filter_by(
            room_id=rds.room_id, domain_id=rds.domain_id, is_active=True
        ).scalar() or 0.0

        if avg_conf < t["min_avg_confidence"]:
            return None

        # Update confidence score
        rds.confidence_score = avg_conf
        return LearningPhase.SUGGESTING

    def _check_suggest_to_autonomous(self, session, rds):
        """Can we move from suggesting to autonomous?"""
        t = self.SUGGEST_TO_AUTONOMOUS

        if rds.phase_started_at:
            days = (datetime.utcnow().replace(tzinfo=None) - rds.phase_started_at.replace(tzinfo=None)).days
            if days < t["min_days"]:
                return None

        # Count confirmed patterns
        confirmed = session.query(func.count(LearnedPattern.id)).filter_by(
            room_id=rds.room_id, domain_id=rds.domain_id,
            status="active", is_active=True
        ).scalar() or 0

        if confirmed < t["min_confirmed"]:
            return None

        # Avg confidence of active patterns
        avg_conf = session.query(func.avg(LearnedPattern.confidence)).filter_by(
            room_id=rds.room_id, domain_id=rds.domain_id,
            status="active", is_active=True
        ).scalar() or 0.0

        if avg_conf < t["min_avg_confidence"]:
            return None

        rds.confidence_score = avg_conf
        return LearningPhase.AUTONOMOUS

    def set_phase_manual(self, room_id, domain_id, phase_str):
        """Manual phase override by user."""
        session = self.Session()
        try:
            phase_map = {
                "observing": LearningPhase.OBSERVING,
                "suggesting": LearningPhase.SUGGESTING,
                "autonomous": LearningPhase.AUTONOMOUS,
            }
            phase = phase_map.get(phase_str)
            if not phase:
                return {"error": f"Invalid phase: {phase_str}"}

            rds = session.query(RoomDomainState).filter_by(
                room_id=room_id, domain_id=domain_id
            ).first()

            if not rds:
                return {"error": "Room/domain state not found"}

            rds.learning_phase = phase
            rds.phase_started_at = datetime.now(timezone.utc)
            session.commit()

            return {"success": True, "phase": phase.value}

        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()

    def set_paused(self, room_id, domain_id, paused):
        """Pause/unpause learning for a room/domain."""
        session = self.Session()
        try:
            rds = session.query(RoomDomainState).filter_by(
                room_id=room_id, domain_id=domain_id
            ).first()
            if not rds:
                return {"error": "Not found"}
            rds.is_paused = paused
            session.commit()
            return {"success": True, "is_paused": paused}
        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()


# ==============================================================================
# G2: Simple Anomaly Detector
# ==============================================================================

class AnomalyDetector:
    """Detects unusual events using statistical baselines and heuristics."""

    # Entities we've already reported (avoid spam)
    _reported = set()

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def _get_pattern_setting(self, session, key, default):
        """Read a setting from PatternSettings table."""
        try:
            ps = session.query(PatternSettings).filter_by(key=key).first()
            if ps:
                return type(default)(ps.value)
        except Exception:
            pass
        return default

    def check_recent_anomalies(self, minutes=30):
        """Check recent events for anomalies using multiple detection methods."""
        session = self.Session()
        anomalies = []
        try:
            # Load exclusion settings
            try:
                from helpers import get_setting
                domain_exceptions = json.loads(get_setting("anomaly_domain_exceptions") or "[]")
                device_whitelist = json.loads(get_setting("anomaly_device_whitelist") or "[]")
            except Exception:
                domain_exceptions = []
                device_whitelist = []

            # Load per-device anomaly settings
            device_settings = {}
            try:
                for ds in session.query(AnomalySetting).all():
                    if ds.device_id:
                        device_settings[ds.device_id] = ds
            except Exception:
                pass

            cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
            recent = session.query(StateHistory).filter(
                StateHistory.created_at >= cutoff,
                StateHistory.device_id.isnot(None)
            ).all()

            for event in recent:
                # Skip already reported (reset every hour)
                report_key = f"{event.entity_id}:{event.new_state}:{event.created_at.hour if event.created_at else 0}"
                if report_key in self._reported:
                    continue

                # Skip whitelisted entities
                if event.entity_id in device_whitelist:
                    continue

                # Skip excluded domains
                ha_domain = event.entity_id.split(".")[0] if event.entity_id else ""
                if ha_domain in domain_exceptions:
                    continue

                # Skip sensor domain entirely for frequency checks (power meters etc.)
                if ha_domain == "sensor":
                    continue

                # Check per-device settings
                if event.device_id and event.device_id in device_settings:
                    ds = device_settings[event.device_id]
                    if not ds.frequency_anomaly and not ds.time_anomaly:
                        continue

                anomaly = None

                # Method 1: Unusual time of day (statistical)
                anomaly = anomaly or self._check_unusual_time(session, event)

                # Method 2: Unusual frequency (too many changes)
                anomaly = anomaly or self._check_unusual_frequency(session, event)

                if anomaly:
                    self._reported.add(report_key)
                    anomalies.append(anomaly)

            # Method 3: Stuck devices (no change for unusually long time)
            anomalies.extend(self._check_stuck_devices(session))

            # LRU cleanup: remove oldest half when exceeding 200
            if len(self._reported) > 200:
                to_remove = list(self._reported)[:100]
                for key in to_remove:
                    self._reported.discard(key)

            return anomalies

        except Exception as e:
            logger.error(f"Anomaly check error: {e}")
            return []
        finally:
            session.close()

    def _check_unusual_time(self, session, event):
        """Detect activity at unusual hours based on entity history."""
        ctx = event.context or {}
        hour = ctx.get("hour", 12)
        time_slot = ctx.get("time_slot", "")
        ha_domain = event.entity_id.split(".")[0]

        # Only check binary state devices
        if ha_domain not in ("light", "switch", "cover", "lock") or event.new_state not in ("on", "off", "open", "unlocked"):
            return None

        # Get historical hours for this entity+state
        history = session.query(StateHistory.context).filter(
            StateHistory.entity_id == event.entity_id,
            StateHistory.new_state == event.new_state,
            StateHistory.created_at >= datetime.now(timezone.utc) - timedelta(days=14),
        ).all()

        if len(history) < 5:
            # Not enough data for a baseline, use simple night check
            if time_slot == "night" and event.new_state in ("on", "unlocked", "open"):
                return self._build_anomaly(session, event, hour,
                    f"wurde nachts um {hour}:00 aktiviert (keine Basisdaten)",
                    f"activated at {hour}:00 during night (no baseline)")
            return None

        # Calculate statistical baseline
        historical_hours = []
        for h in history:
            if h[0] and isinstance(h[0], dict):
                historical_hours.append(h[0].get("hour", 12))

        if not historical_hours:
            return None

        # Calculate mean and standard deviation
        mean_hour = sum(historical_hours) / len(historical_hours)
        variance = sum((h - mean_hour) ** 2 for h in historical_hours) / len(historical_hours)
        std_dev = max(variance ** 0.5, 1.0)  # min 1 hour std

        # Circular distance (23:00 and 01:00 are 2 hours apart, not 22)
        diff = min(abs(hour - mean_hour), 24 - abs(hour - mean_hour))

        # More than 2.5 standard deviations = anomaly
        if diff > std_dev * 2.5 and diff > 3:
            return self._build_anomaly(session, event, hour,
                f"um {hour}:00 Uhr aktiviert (normalerweise ~{int(mean_hour)}:00 ±{int(std_dev)}h)",
                f"activated at {hour}:00 (usually ~{int(mean_hour)}:00 ±{int(std_dev)}h)")

        return None

    def _check_unusual_frequency(self, session, event):
        """Detect devices toggling too frequently (possible fault or tampering)."""
        # Count changes in last 10 minutes
        recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        change_count = session.query(func.count(StateHistory.id)).filter(
            StateHistory.entity_id == event.entity_id,
            StateHistory.created_at >= recent_cutoff
        ).scalar() or 0

        ha_domain = event.entity_id.split(".")[0] if event.entity_id else ""

        # Person entities: higher threshold due to GPS jitter (configurable)
        if ha_domain in ("person", "device_tracker"):
            threshold = self._get_pattern_setting(session, "anomaly_person_threshold", 50)
            if change_count >= threshold:
                return self._build_anomaly(session, event, None,
                    f"hat sich {change_count}x in 10 Min geändert (GPS-Jitter?)",
                    f"changed {change_count} times in 10 min (GPS jitter?)",
                    severity="info")
            return None

        # Climate/heatpump: configurable sensitivity
        if ha_domain == "climate":
            sensitivity = self._get_pattern_setting(session, "anomaly_heatpump_sensitivity", "low")
            threshold_map = {"low": 30, "medium": 15, "high": 10}
            threshold = threshold_map.get(sensitivity, 30)
            if change_count >= threshold:
                return self._build_anomaly(session, event, None,
                    f"hat sich {change_count}x in 10 Min geändert",
                    f"changed {change_count} times in 10 min",
                    severity="warning")
            return None

        if change_count >= 10:
            return self._build_anomaly(session, event, None,
                f"hat sich {change_count}x in 10 Minuten geändert (mögliche Störung)",
                f"changed {change_count} times in 10 minutes (possible fault)",
                severity="critical")

        return None

    def _check_stuck_devices(self, session):
        """Detect devices that haven't changed state for unusually long."""
        anomalies = []
        threshold = datetime.now(timezone.utc) - timedelta(hours=12)

        # Check lights (on), covers (open), climate (heating) stuck for >12h
        stuck_checks = [
            ("light.%", "on", "eingeschaltet", "on"),
            ("cover.%", "open", "offen", "open"),
            ("climate.%", "heat", "im Heizbetrieb", "heating"),
        ]

        seen_entities = set()
        for entity_pattern, stuck_state, reason_de_word, reason_en_word in stuck_checks:
            stuck_events = session.query(StateHistory).filter(
                StateHistory.entity_id.like(entity_pattern),
                StateHistory.new_state == stuck_state,
                StateHistory.created_at <= threshold,
            ).order_by(StateHistory.created_at.desc()).all()

            for event in stuck_events:
                if event.entity_id in seen_entities:
                    continue
                seen_entities.add(event.entity_id)

                # Check if there was a newer event (state changed since)
                newer = session.query(StateHistory).filter(
                    StateHistory.entity_id == event.entity_id,
                    StateHistory.created_at > event.created_at
                ).first()

                if not newer:
                    report_key = f"stuck:{event.entity_id}"
                    if report_key not in self._reported:
                        hours = int((datetime.now(timezone.utc) - event.created_at).total_seconds() / 3600) if event.created_at else 0
                        device = session.query(Device).filter_by(ha_entity_id=event.entity_id).first()
                        device_name = device.name if device else event.entity_id

                        anomalies.append({
                            "entity_id": event.entity_id,
                            "device_name": device_name,
                            "event": f"{stuck_state} seit {hours}h",
                            "time": event.created_at.isoformat() if event.created_at else None,
                            "reason_de": f"{device_name} ist seit {hours} Stunden {reason_de_word}",
                            "reason_en": f"{device_name} has been {reason_en_word} for {hours} hours",
                            "severity": "info",
                        })
                        self._reported.add(report_key)

        return anomalies

    def _build_anomaly(self, session, event, hour, reason_de, reason_en, severity="warning"):
        """Build an anomaly dict."""
        device = session.query(Device).filter_by(ha_entity_id=event.entity_id).first()
        device_name = device.name if device else event.entity_id
        return {
            "entity_id": event.entity_id,
            "device_name": device_name,
            "event": f"{event.old_state} → {event.new_state}",
            "time": event.created_at.isoformat() if event.created_at else None,
            "reason_de": f"{device_name} {reason_de}",
            "reason_en": f"{device_name} {reason_en}",
            "severity": severity,
        }

    def detect_time_clusters(self, session, entity_id=None, days=14):
        """#54: Detect natural time clusters (routines) from state history."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = session.query(StateHistory).filter(StateHistory.created_at > cutoff)
        if entity_id:
            query = query.filter(StateHistory.entity_id == entity_id)
        history = query.all()

        # Group by hour
        hour_counts = defaultdict(int)
        for h in history:
            hour_counts[h.created_at.hour] += 1

        # Find clusters (peaks in activity)
        clusters = []
        cluster_names = {
            (5, 9): {"de": "Morgenroutine", "en": "Morning routine"},
            (11, 14): {"de": "Mittagszeit", "en": "Lunchtime"},
            (17, 20): {"de": "Feierabend", "en": "Evening routine"},
            (21, 24): {"de": "Schlafenszeit", "en": "Bedtime"},
        }
        for (start_h, end_h), names in cluster_names.items():
            total = sum(hour_counts.get(h, 0) for h in range(start_h, end_h))
            if total >= 10:
                peak_hour = max(range(start_h, end_h), key=lambda h: hour_counts.get(h, 0))
                clusters.append({
                    "name_de": names["de"],
                    "name_en": names["en"],
                    "start_hour": start_h,
                    "end_hour": end_h,
                    "peak_hour": peak_hour,
                    "event_count": total,
                })
        return clusters

    def detect_guest_activity(self, session):
        """#58: Detect unusual device activity that might indicate guests."""
        try:
            # Compare last 24h activity to 7-day average
            now = datetime.now(timezone.utc)
            day_ago = now - timedelta(hours=24)
            week_ago = now - timedelta(days=7)

            recent = session.query(func.count(StateHistory.id)).filter(
                StateHistory.created_at > day_ago).scalar() or 0
            weekly_avg = (session.query(func.count(StateHistory.id)).filter(
                StateHistory.created_at > week_ago).scalar() or 0) / 7

            if weekly_avg > 0 and recent > weekly_avg * 1.5:
                return {
                    "guest_likely": True,
                    "recent_events": recent,
                    "daily_average": round(weekly_avg),
                    "ratio": round(recent / weekly_avg, 1),
                    "message_de": f"Ungewöhnlich hohe Aktivität: {recent} Events (Ö {weekly_avg:.0f})",
                    "message_en": f"Unusually high activity: {recent} events (avg {weekly_avg:.0f})",
                }
            return {"guest_likely": False, "recent_events": recent, "daily_average": round(weekly_avg)}
        except Exception:
            return {"guest_likely": False}


# ==============================================================================
# G1+G3: Notification Manager
# ==============================================================================

class NotificationManager:
    """Manages notifications for suggestions, anomalies, and events."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.ha = ha_connection
        self.Session = sessionmaker(bind=engine)

    def _send_via_push(self, session, title, message):
        """Send notification via configured push channel with fallback to persistent_notification."""
        import json as _json
        from helpers import get_setting
        sent = False

        # Load person-channel assignments: {user_id: [channel_id, ...]}
        person_channels = {}
        try:
            raw = get_setting("notif_person_channels")
            if raw:
                person_channels = _json.loads(raw)
        except Exception:
            pass

        # Load available channels for resolving channel_id → service_name
        channels_by_id = {}
        try:
            from models import NotificationChannel
            for ch in session.query(NotificationChannel).filter_by(is_enabled=True).all():
                channels_by_id[ch.id] = ch.service_name
        except Exception:
            pass

        # Try push_channel from NotificationSettings for all non-guest users
        try:
            from models import User, UserRole
            settings = session.query(NotificationSetting).join(User).filter(
                NotificationSetting.push_channel.isnot(None),
                NotificationSetting.is_enabled == True,
                User.role != UserRole.GUEST,
                User.is_active == True,
            ).all()
            for setting in settings:
                user_id_str = str(setting.user_id)
                assigned = person_channels.get(user_id_str)

                if assigned and channels_by_id:
                    # Person has specific channel assignments → only send to those
                    for ch_id in assigned:
                        svc = channels_by_id.get(ch_id)
                        if svc:
                            try:
                                self.ha.call_service("notify", svc.replace("notify.", ""), {
                                    "title": title, "message": message,
                                })
                                sent = True
                            except Exception as e:
                                logger.debug(f"Push to {svc} for user {user_id_str} failed: {e}")
                else:
                    # No specific assignment → use legacy push_channel
                    channel = setting.push_channel
                    if channel:
                        try:
                            self.ha.call_service("notify", channel, {
                                "title": title, "message": message,
                            })
                            sent = True
                        except Exception as e:
                            logger.debug(f"Push to {channel} failed: {e}")
        except Exception as e:
            logger.debug(f"Push channel query error: {e}")

        # Fallback: always send to persistent_notification
        try:
            self.ha.call_service("notify", "persistent_notification", {
                "title": title,
                "message": message,
            })
            sent = True
        except Exception as e:
            logger.debug(f"Persistent notification failed: {e}")

        # TTS: send to assigned room speakers if configured and enabled
        try:
            tts_enabled = _json.loads(get_setting("notif_tts_enabled") or "true")
            if not tts_enabled:
                logger.debug("TTS globally disabled, skipping")
            else:
                tts_raw = get_setting("notif_tts_room_assignments")
                if tts_raw:
                    tts_assignments = _json.loads(tts_raw)
                    # tts_assignments: {entity_id: room_id}
                    motion_mode = _json.loads(get_setting("notif_tts_motion_mode") or '{"enabled": false}')

                    # Filter out individually disabled speakers
                    disabled_speakers = _json.loads(get_setting("notif_tts_disabled_speakers") or "[]")

                    if motion_mode.get("enabled"):
                        # Only announce on speaker in room with last motion
                        target_speakers = self._get_motion_tts_speakers(tts_assignments, motion_mode)
                    else:
                        target_speakers = list(tts_assignments.keys())

                    target_speakers = [s for s in target_speakers if s not in disabled_speakers]

                    for entity_id in target_speakers:
                        try:
                            self.ha.announce_tts(message, media_player_entity=entity_id)
                        except Exception as e:
                            logger.debug(f"TTS to {entity_id} failed: {e}")
        except Exception:
            pass

        return sent

    def _get_motion_tts_speakers(self, tts_assignments, motion_mode):
        """Find TTS speakers in the room with the most recent motion."""
        try:
            timeout_min = motion_mode.get("timeout_min", 30)
            fallback_all = motion_mode.get("fallback_all", False)

            # Build reverse map: room_id → [speaker_entity_ids]
            room_speakers = {}
            for entity_id, room_id in tts_assignments.items():
                rid = str(room_id)
                if rid not in room_speakers:
                    room_speakers[rid] = []
                room_speakers[rid].append(entity_id)

            # Find motion sensors with room assignments
            session = self.Session()
            try:
                motion_devices = session.query(Device).filter(
                    Device.ha_entity_id.like("binary_sensor.%"),
                    Device.room_id.isnot(None),
                ).all()

                states = self.ha.get_states() or []
                state_map = {s["entity_id"]: s for s in states}

                # Find room with most recent motion
                latest_room_id = None
                latest_time = ""
                now = datetime.now(timezone.utc)

                for dev in motion_devices:
                    s = state_map.get(dev.ha_entity_id, {})
                    device_class = s.get("attributes", {}).get("device_class", "")
                    if device_class not in ("motion", "occupancy"):
                        continue
                    last_changed = s.get("last_changed", "")
                    if not last_changed:
                        continue

                    # Check timeout
                    try:
                        changed_dt = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
                        if (now - changed_dt).total_seconds() > timeout_min * 60:
                            continue
                    except (ValueError, TypeError):
                        pass

                    if last_changed > latest_time:
                        latest_time = last_changed
                        latest_room_id = str(dev.room_id)
            finally:
                session.close()

            if latest_room_id and latest_room_id in room_speakers:
                logger.info(f"TTS motion mode: announcing in room {latest_room_id}")
                return room_speakers[latest_room_id]

            # Fallback
            if fallback_all:
                logger.info("TTS motion mode: no recent motion, fallback to all speakers")
                return list(tts_assignments.keys())

            logger.info("TTS motion mode: no recent motion, no fallback - skipping TTS")
            return []
        except Exception as e:
            logger.warning(f"TTS motion mode error: {e}, falling back to all speakers")
            return list(tts_assignments.keys())

    def notify_suggestion(self, prediction_id, lang="de"):
        """Send notification about a new suggestion."""
        session = self.Session()
        try:
            pred = session.get(Prediction, prediction_id)
            if not pred:
                return

            desc = pred.description_de if lang == "de" else (pred.description_en or pred.description_de)
            title = "MindHome: Neuer Vorschlag" if lang == "de" else "MindHome: New Suggestion"
            message = desc or "MindHome hat ein neues Muster erkannt"

            # Save to notification log
            notif = NotificationLog(
                user_id=1,
                notification_type=NotificationType.SUGGESTION,
                title=title,
                message=message,
                was_sent=False,
                was_read=False,
            )
            session.add(notif)

            # Send via push channel + persistent notification
            notif.was_sent = self._send_via_push(session, title, message)
            pred.notification_sent = notif.was_sent

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Notification error: {e}")
        finally:
            session.close()

    def notify_anomaly(self, anomaly, lang="de"):
        """Send notification about an anomaly. Deduplicate by entity within 24h."""
        session = self.Session()
        try:
            entity_id = anomaly.get("entity_id", "")
            title = "MindHome: Ungewöhnliche Aktivität" if lang == "de" else "MindHome: Unusual Activity"
            message = anomaly.get("reason_de" if lang == "de" else "reason_en", "")

            # Dedup: check if we already notified about this entity in last 24h
            if entity_id:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                existing = session.query(NotificationLog).filter(
                    NotificationLog.notification_type == NotificationType.ANOMALY,
                    NotificationLog.message.contains(entity_id),
                    NotificationLog.created_at >= cutoff
                ).first()
                if existing:
                    return  # Already notified recently

            notif = NotificationLog(
                user_id=1,
                notification_type=NotificationType.ANOMALY,
                title=title,
                message=f"{message} [{entity_id}]" if entity_id else message,
                was_sent=False,
                was_read=False,
            )
            session.add(notif)

            notif.was_sent = self._send_via_push(session, title, message)

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Anomaly notification error: {e}")
        finally:
            session.close()

    def get_notifications(self, limit=50, unread_only=False):
        """Get recent notifications."""
        session = self.Session()
        try:
            query = session.query(NotificationLog).order_by(
                NotificationLog.created_at.desc()
            )
            if unread_only:
                query = query.filter_by(was_read=False)
            return query.limit(limit).all()
        except Exception as e:
            logger.error(f"Get notifications error: {e}")
            return []
        finally:
            session.close()

    def mark_read(self, notification_id):
        """Mark a notification as read."""
        session = self.Session()
        try:
            n = session.get(NotificationLog, notification_id)
            if n:
                n.was_read = True
                session.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Mark read error: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    def mark_all_read(self):
        """Mark all notifications as read."""
        session = self.Session()
        try:
            session.query(NotificationLog).filter_by(
                was_read=False
            ).update({"was_read": True})
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    def get_unread_count(self):
        """Get count of unread notifications."""
        session = self.Session()
        try:
            return session.query(func.count(NotificationLog.id)).filter_by(
                was_read=False
            ).scalar() or 0
        except Exception as e:
            logger.error(f"Unread count error: {e}")
            return 0
        finally:
            session.close()


# ==============================================================================
# Phase 3: Presence Mode Manager
# ==============================================================================

class PresenceModeManager:
    """Manages presence modes and transitions."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.ha = ha_connection
        self.Session = sessionmaker(bind=engine)
        self._current_mode = None
        self._last_mode_change = None
        # Initialize _current_mode from DB
        try:
            session = self.Session()
            last = session.query(PresenceLog).order_by(PresenceLog.created_at.desc()).first()
            if last and last.mode_id:
                self._current_mode = last.mode_id
            session.close()
        except Exception:
            pass

    def get_current_mode(self):
        """Get current active presence mode."""
        session = self.Session()
        try:
            # Search recent PresenceLogs for a valid mode
            recent_logs = session.query(PresenceLog).order_by(PresenceLog.created_at.desc()).limit(10).all()
            for log_entry in recent_logs:
                mode = None
                if log_entry.mode_id:
                    mode = session.get(PresenceMode, log_entry.mode_id)
                elif log_entry.mode_name:
                    # Fallback: lookup by name (for auto_detect logs without mode_id)
                    mode = session.query(PresenceMode).filter_by(name_de=log_entry.mode_name).first()
                    if mode and not log_entry.mode_id:
                        # Back-fill mode_id for future lookups
                        log_entry.mode_id = mode.id
                        try:
                            session.commit()
                        except Exception:
                            session.rollback()
                if mode:
                    return {
                        "id": mode.id, "name_de": mode.name_de, "name_en": mode.name_en,
                        "icon": mode.icon, "color": mode.color, "since": log_entry.created_at.isoformat(),
                    }
            return None
        finally:
            session.close()

    def set_mode(self, mode_id, user_id=None, trigger="manual"):
        """Activate a presence mode and execute its actions."""
        # Skip if already in this mode
        if self._current_mode == mode_id:
            session = self.Session()
            try:
                mode = session.get(PresenceMode, mode_id)
                return {"success": True, "mode": mode.name_de if mode else "?", "already_active": True}
            finally:
                session.close()

        session = self.Session()
        try:
            mode = session.get(PresenceMode, mode_id)
            if not mode:
                return {"error": "Mode not found"}

            # Log the transition
            log = PresenceLog(
                mode_id=mode.id, mode_name=mode.name_de,
                user_id=user_id, trigger=trigger,
            )
            session.add(log)

            # Execute mode actions
            actions = mode.actions or []
            for action in actions:
                try:
                    entity_id = action.get("entity_id", "")
                    service = action.get("service", "")
                    if entity_id and service:
                        domain = entity_id.split(".")[0]
                        data = {**action.get("data", {}), "entity_id": entity_id}
                        self.ha.call_service(domain, service, data)
                except Exception as e:
                    logger.warning(f"Mode action error: {e}")

            session.commit()
            self._current_mode = mode.id
            logger.info(f"Presence mode: {mode.name_de} (trigger: {trigger})")
            return {"success": True, "mode": mode.name_de}
        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()

    def check_auto_transitions(self):
        """Check if presence mode should change based on person states and PersonDevice entities."""
        # Debounce: skip if last mode change was < 30 seconds ago
        now = datetime.now(timezone.utc)
        if hasattr(self, '_last_mode_change') and self._last_mode_change:
            elapsed = (now - self._last_mode_change).total_seconds()
            if elapsed < 30:
                return

        session = self.Session()
        try:
            # Check manual override
            override = session.query(SystemSetting).filter_by(key="presence_manual_override").first()
            if override and override.value == "true":
                # Auto-reset manual override after 4 hours
                override_ts = session.query(SystemSetting).filter_by(key="presence_manual_override_ts").first()
                if override_ts:
                    try:
                        ts = datetime.fromisoformat(override_ts.value)
                        if (now - ts).total_seconds() > 4 * 3600:
                            override.value = "false"
                            session.commit()
                            logger.info("Manual presence override auto-reset after 4h")
                        else:
                            return  # Manual override still active
                    except (ValueError, TypeError):
                        return
                else:
                    return  # No timestamp, skip

            # Primary: HA person entities
            all_persons = self.ha.get_all_persons()

            # Safety: skip if HA API is unreachable (don't false-switch to "Abwesend")
            if all_persons is None or len(all_persons) == 0:
                all_states_check = self.ha.get_states()
                if not all_states_check:
                    logger.debug("Presence check skipped: HA API unreachable")
                    return

            persons_home = self.ha.get_persons_home()
            persons_home_set = set(p.get("entity_id", "") for p in persons_home)

            # Secondary: PersonDevice device_tracker entities (complements HA persons)
            person_devices = session.query(PersonDevice).filter_by(is_active=True).all()
            all_states = self.ha.get_states() or []
            state_map = {s["entity_id"]: s.get("state", "") for s in all_states}

            for pd in person_devices:
                tracker_state = state_map.get(pd.entity_id, "")
                if tracker_state == "home":
                    persons_home_set.add(pd.entity_id)

            # GuestDevice: count guests with 'home' state
            guest_devices = session.query(GuestDevice).all()
            guests_home = 0
            for gd in guest_devices:
                if gd.entity_id and state_map.get(gd.entity_id, "") == "home":
                    guests_home += 1
                    # Update last_seen and visit_count
                    if gd.last_seen is None or (now - gd.last_seen).total_seconds() > 3600:
                        gd.visit_count = (gd.visit_count or 0) + 1
                    gd.last_seen = now

            anyone_home = len(persons_home_set) > 0 or guests_home > 0
            all_home = all_persons and all(p["state"] == "home" for p in all_persons)

            # Evaluate auto modes - highest priority first
            modes = session.query(PresenceMode).filter_by(
                is_active=True, trigger_type="auto"
            ).order_by(PresenceMode.priority.desc()).all()

            # Find the best matching mode
            target_mode = None
            for mode in modes:
                config = mode.auto_config or {}
                condition = config.get("condition")

                # Time range check (e.g. Schlaf only between 22:00-06:00)
                time_range = config.get("time_range")
                if time_range and not self._in_time_range(time_range):
                    continue

                matched = False
                if condition == "guests_home" and guests_home > 0:
                    matched = True
                elif condition == "all_home" and all_home:
                    matched = True
                elif condition == "first_home" and anyone_home:
                    matched = True
                elif condition == "all_away" and not anyone_home:
                    matched = True

                if matched:
                    target_mode = mode
                    break  # Highest priority wins

            if target_mode and self._current_mode != target_mode.id:
                self.set_mode(target_mode.id, trigger="auto")
                self._last_mode_change = now

            session.commit()  # Save GuestDevice updates
        except Exception as e:
            logger.warning(f"Presence auto-transition error: {e}")
            session.rollback()
        finally:
            session.close()

    def _in_time_range(self, time_range):
        """Check if current local time is within a time range like {'start': '22:00', 'end': '06:00'}."""
        try:
            from helpers import local_now
            now = local_now()
            current_minutes = now.hour * 60 + now.minute
            start_parts = time_range.get("start", "00:00").split(":")
            end_parts = time_range.get("end", "23:59").split(":")
            start_min = int(start_parts[0]) * 60 + int(start_parts[1])
            end_min = int(end_parts[0]) * 60 + int(end_parts[1])

            if start_min <= end_min:
                # Same-day range (e.g. 08:00-18:00)
                return start_min <= current_minutes <= end_min
            else:
                # Overnight range (e.g. 22:00-06:00)
                return current_minutes >= start_min or current_minutes <= end_min
        except Exception:
            return True


# ==============================================================================
# Phase 3: Plugin Conflict Detector
# ==============================================================================

class PluginConflictDetector:
    """Detects conflicts between domain plugin actions."""

    CONFLICT_RULES = [
        # (domain_a, state_a, domain_b, state_b, message_de, message_en)
        ("climate", "heating", "door_window", "open",
         "Heizung laeuft aber Fenster ist offen",
         "Heating is on but window is open"),
        ("climate", "cooling", "door_window", "open",
         "Klimaanlage laeuft aber Fenster ist offen",
         "AC is on but window is open"),
        ("cover", "closed", "ventilation", "boost",
         "Rollos geschlossen aber Lueftung auf Boost",
         "Covers closed but ventilation on boost"),
    ]

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.ha = ha_connection
        self.Session = sessionmaker(bind=engine)

    def check_conflicts(self):
        """Check for active plugin conflicts based on current HA states."""
        conflicts = []
        try:
            states = self.ha.get_states() or []
            state_map = {s["entity_id"]: s for s in states}

            session = self.Session()
            devices = session.query(Device).filter(Device.room_id.isnot(None)).all()

            # Group devices by room
            room_devices = defaultdict(list)
            for d in devices:
                room_devices[d.room_id].append(d)

            for room_id, devs in room_devices.items():
                # Check each conflict rule
                for rule in self.CONFLICT_RULES:
                    domain_a, check_a, domain_b, check_b, msg_de, msg_en = rule

                    has_a = False
                    has_b = False

                    for d in devs:
                        domain = session.get(Domain, d.domain_id)
                        if not domain:
                            continue
                        ha_state = state_map.get(d.ha_entity_id, {})
                        state_val = ha_state.get("state", "")
                        attrs = ha_state.get("attributes", {})

                        if domain.name == domain_a:
                            if check_a == "heating" and attrs.get("hvac_action") == "heating":
                                has_a = True
                            elif check_a == "cooling" and attrs.get("hvac_action") == "cooling":
                                has_a = True

                        if domain.name == domain_b:
                            if check_b == "open" and state_val == "on":
                                has_b = True

                    if has_a and has_b:
                        room = session.get(Room, room_id)
                        conflicts.append({
                            "room_id": room_id,
                            "room_name": room.name if room else f"Room {room_id}",
                            "message_de": msg_de,
                            "message_en": msg_en,
                            "severity": "warning",
                        })

            session.close()
        except Exception as e:
            logger.warning(f"Plugin conflict check error: {e}")

        return conflicts


# ==============================================================================
# Phase 3: Quiet Hours Manager
# ==============================================================================

class QuietHoursManager:
    """Check if current time is within quiet hours."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def is_quiet_time(self, user_id=None):
        """Check if we're currently in quiet hours."""
        session = self.Session()
        try:
            configs = session.query(QuietHoursConfig).filter_by(is_active=True).all()
            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            current_weekday = now.weekday()  # 0=Mon, 6=Sun

            for config in configs:
                if config.user_id and config.user_id != user_id:
                    continue

                # Check weekday restrictions if configured
                weekdays = getattr(config, 'weekdays', None)
                if weekdays and current_weekday not in weekdays:
                    # For overnight crossing: also check if we started yesterday
                    pass  # Will be checked below

                try:
                    start_h, start_m = map(int, config.start_time.split(":")[:2])
                    end_h, end_m = map(int, config.end_time.split(":")[:2])
                except (ValueError, TypeError):
                    continue
                start_min = start_h * 60 + start_m
                end_min = end_h * 60 + end_m

                if start_min > end_min:  # overnight (e.g. 22:00-07:00)
                    if current_minutes >= start_min:
                        # We're in the evening part — check today's weekday
                        if weekdays and current_weekday not in weekdays:
                            continue
                        return True
                    elif current_minutes < end_min:
                        # We're in the morning part after midnight — check yesterday's weekday
                        yesterday = (current_weekday - 1) % 7
                        if weekdays and yesterday not in weekdays:
                            continue
                        return True
                else:
                    if start_min <= current_minutes < end_min:
                        if weekdays and current_weekday not in weekdays:
                            continue
                        return True

            return False
        finally:
            session.close()

    def should_allow(self, notification_type="info"):
        """Check if a notification should be sent during quiet hours."""
        if not self.is_quiet_time():
            return True
        # Critical notifications always go through
        if notification_type in ("critical", "emergency"):
            return True
        return False


# ==============================================================================
# Phase 2b Scheduler (extends PatternScheduler)
# ==============================================================================

class AutomationScheduler:
    """Background scheduler for Phase 2b: suggestions, execution, phases."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.ha = ha_connection
        self.suggestion_gen = SuggestionGenerator(engine)
        self.executor = AutomationExecutor(engine, ha_connection)
        self.phase_mgr = PhaseManager(engine)
        self.anomaly_det = AnomalyDetector(engine)
        self.notification_mgr = NotificationManager(engine, ha_connection)
        self.conflict_det = ConflictDetector(engine)
        self.feedback = FeedbackProcessor(engine)
        # Phase 3
        self.presence_mgr = PresenceModeManager(engine, ha_connection)
        self.plugin_conflict_det = PluginConflictDetector(engine, ha_connection)
        self.quiet_hours_mgr = QuietHoursManager(engine)
        self._should_run = True
        self._threads = []

    def start(self):
        """Start Phase 2b + Phase 3 background tasks."""
        logger.info("Starting Automation Scheduler...")

        # Automation check: every 1 minute
        t1 = threading.Thread(target=self._run_periodic,
                              args=(self.executor.check_and_execute, 60, "automation_check"),
                              daemon=True)
        t1.start()
        self._threads.append(t1)

        # Suggestion generation: every 4 hours
        t2 = threading.Thread(target=self._run_periodic,
                              args=(self.suggestion_gen.generate_suggestions, 4 * 3600, "suggestion_gen"),
                              daemon=True)
        t2.start()
        self._threads.append(t2)

        # Phase transitions: every 12 hours
        t3 = threading.Thread(target=self._run_periodic,
                              args=(self.phase_mgr.check_transitions, 12 * 3600, "phase_check"),
                              daemon=True)
        t3.start()
        self._threads.append(t3)

        # Anomaly check: every 15 minutes
        t4 = threading.Thread(target=self._anomaly_task, daemon=True)
        t4.start()
        self._threads.append(t4)

        # Phase 3: Presence mode check: every 60 seconds (fallback to event-based)
        t6 = threading.Thread(target=self._run_periodic,
                              args=(self.presence_mgr.check_auto_transitions, 60, "presence_check"),
                              daemon=True)
        t6.start()
        self._threads.append(t6)

        # Phase 3: Plugin conflict check: every 5 minutes
        t7 = threading.Thread(target=self._run_periodic,
                              args=(self._plugin_conflict_task, 300, "plugin_conflicts"),
                              daemon=True)
        t7.start()
        self._threads.append(t7)

        # Calendar trigger check: every 5 minutes
        t8 = threading.Thread(target=self._run_periodic,
                              args=(self._calendar_trigger_task, 300, "calendar_triggers"),
                              daemon=True)
        t8.start()
        self._threads.append(t8)

        # Shift-to-calendar sync: every 6 hours
        t9 = threading.Thread(target=self._run_periodic,
                              args=(self._shift_calendar_sync_task, 6 * 3600, "shift_cal_sync"),
                              daemon=True)
        t9.start()
        self._threads.append(t9)

        logger.info("Automation Scheduler started (exec:1min, suggest:4h, phase:12h, anomaly:15min, presence:2min, conflicts:5min, cal-triggers:5min, shift-sync:6h)")

        # #40 Watchdog: monitor thread health every 5 min
        t5 = threading.Thread(target=self._watchdog_task, daemon=True)
        t5.start()
        self._threads.append(t5)

    def stop(self):
        self._should_run = False
        logger.info("Automation Scheduler stopped")

    def _watchdog_task(self):
        """#40: Monitor thread health, restart dead threads."""
        time.sleep(300)  # first check after 5min
        while self._should_run:
            alive = sum(1 for t in self._threads if t.is_alive())
            total = len(self._threads)
            if alive < total:
                logger.warning(f"Watchdog: {total - alive}/{total} threads dead")
            time.sleep(300)

    def _calendar_trigger_task(self):
        """Check calendar triggers against upcoming HA calendar events."""
        try:
            from helpers import get_setting
            import json as _json

            raw = get_setting("calendar_triggers")
            if not raw:
                return
            triggers = _json.loads(raw)
            active_triggers = [t for t in triggers if t.get("is_active", True)]
            if not active_triggers:
                return

            # Get events from synced HA calendars for next 24 hours
            synced_raw = get_setting("calendar_synced_sources") or "[]"
            synced_ids = _json.loads(synced_raw)
            if not synced_ids:
                return

            now = datetime.now(timezone.utc)
            start = now.isoformat()
            end = (now + timedelta(hours=1)).isoformat()

            events = []
            for eid in synced_ids:
                try:
                    cal_events = self.ha.get_calendar_events(eid, start, end)
                    events.extend(cal_events)
                except Exception:
                    pass

            # Match triggers to events
            for trigger in active_triggers:
                keyword = (trigger.get("keyword", "")).lower()
                entity_id = trigger.get("entity_id")
                service = trigger.get("service", "turn_on")
                if not keyword or not entity_id:
                    continue

                for ev in events:
                    summary = (ev.get("summary", "") or "").lower()
                    if keyword in summary:
                        # Execute the trigger action
                        try:
                            domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
                            self.ha.call_service(domain, service, {"entity_id": entity_id})
                            logger.info(f"Calendar trigger fired: '{keyword}' → {entity_id}.{service}")
                        except Exception as e:
                            logger.warning(f"Calendar trigger exec error: {e}")
                        break  # One match per trigger per cycle

        except Exception as e:
            logger.debug(f"Calendar trigger check error: {e}")

    def _shift_calendar_sync_task(self, full_resync=False):
        """Sync shift schedules to a configured HA calendar entity.

        Reconciliation approach: reads actual HA calendar, compares with expected
        shifts, deletes obsolete/duplicate events, creates missing ones.
        Identifies own events via '[MH]' tag in summary (description not returned by HA API).
        """
        try:
            from helpers import get_setting, set_setting, get_ha_timezone
            from db import get_db
            from models import PersonSchedule, ShiftTemplate, User

            config_raw = get_setting("shift_calendar_sync")
            if not config_raw:
                return
            import json as _json
            config = _json.loads(config_raw)
            if not config.get("enabled"):
                return
            target_calendar = config.get("calendar_entity", "")
            sync_days = config.get("sync_days", 30)
            if not target_calendar:
                return

            MH_TAG = "[MH]"  # Marker in summary to identify MindHome events

            # Use HA's local timezone for correct date calculations
            local_tz = get_ha_timezone()
            now = datetime.now(local_tz)

            # --- Step 1: Build expected events from current shift schedules ---
            session = get_db()
            try:
                schedules = session.query(PersonSchedule).filter_by(
                    is_active=True, schedule_type="shift").all()
                templates = {t.short_code: t for t in
                             session.query(ShiftTemplate).filter_by(is_active=True).all()}
                users = {u.id: u.name for u in
                         session.query(User).filter_by(is_active=True).all()}
            finally:
                session.close()

            # expected_events: key = "YYYY-MM-DD|summary_without_tag" → event details
            expected_events = {}

            for sched in schedules:
                sd = sched.shift_data if isinstance(sched.shift_data, dict) else {}
                pattern = sd.get("rotation_pattern", [])
                rotation_start = sd.get("rotation_start")
                if not pattern or not rotation_start:
                    continue
                try:
                    start_dt = datetime.strptime(rotation_start, "%Y-%m-%d").replace(tzinfo=local_tz)
                except (ValueError, TypeError):
                    continue

                user_name = users.get(sched.user_id, "")

                for day_offset in range(sync_days):
                    day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
                    diff = (day - start_dt).days
                    if diff < 0:
                        continue
                    idx = diff % len(pattern)
                    code = pattern[idx]
                    tmpl = templates.get(code)
                    # Skip free/off codes (X, F, -, FREI, and variants like "X (M)")
                    code_base = code.split("(")[0].strip().upper()
                    if not tmpl or code_base in ("X", "F", "-", "FREI", "OFF", "AUS"):
                        continue

                    day_str = day.strftime("%Y-%m-%d")
                    base_summary = f"{tmpl.name}" + (f" ({user_name})" if user_name else "")
                    blocks = tmpl.blocks if isinstance(tmpl.blocks, list) and tmpl.blocks else []
                    start_time = ""
                    end_time = ""
                    if blocks:
                        start_time = blocks[0].get("start", "") or ""
                        end_time = blocks[-1].get("end", "") or ""
                    if start_time and end_time:
                        ev_start = f"{day_str}T{start_time}:00"
                        ev_end = f"{day_str}T{end_time}:00"
                    else:
                        # All-day event for shifts without specific times
                        ev_start = day_str
                        ev_end = (day + timedelta(days=1)).strftime("%Y-%m-%d")

                    key = f"{day_str}|{base_summary}"
                    expected_events[key] = {
                        "summary": f"{base_summary} {MH_TAG}",
                        "start": ev_start, "end": ev_end,
                        "description": f"MindHome Schicht: {code}",
                    }

            # --- Step 2: Read ALL events from HA calendar in sync range ---
            query_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT00:00:00.000Z")
            query_end = (now + timedelta(days=sync_days + 1)).strftime("%Y-%m-%dT23:59:59.000Z")
            try:
                existing = self.ha.get_calendar_events(target_calendar, query_start, query_end)
            except Exception as e:
                logger.warning(f"Shift sync: failed to read calendar: {e}")
                existing = []

            # Build map: identify MindHome events by [MH] tag in summary
            # Also detect old events without [MH] tag but with "MindHome Schicht:" description
            existing_mh = {}  # key → [ha_uid, ...]
            for ev in existing:
                ev_uid = ev.get("uid")
                if not ev_uid:
                    continue
                ev_summary = (ev.get("summary") or "").strip()
                ev_desc = (ev.get("description") or "").strip()

                is_mh_event = False
                if MH_TAG in ev_summary:
                    is_mh_event = True
                elif ev_desc.startswith("MindHome Schicht:"):
                    is_mh_event = True  # Legacy event without [MH] tag

                if not is_mh_event:
                    continue

                ev_start = ev.get("start", {})
                ev_date = ev_start.get("date") or (ev_start.get("dateTime", "")[:10])
                # Strip [MH] tag for matching
                base = ev_summary.replace(MH_TAG, "").strip()
                key = f"{ev_date}|{base}"
                if key not in existing_mh:
                    existing_mh[key] = []
                existing_mh[key].append(ev_uid)

            # --- Step 3: Delete events that shouldn't exist + duplicates ---
            # Note: delete_event only works on local calendars, not Google Calendar
            deleted = 0
            is_local_calendar = not any(
                uid.endswith("@google.com") for uids in existing_mh.values() for uid in uids
            )
            if is_local_calendar:
                for key, ha_uids in existing_mh.items():
                    if key in expected_events:
                        for dup_uid in ha_uids[1:]:
                            try:
                                self.ha.delete_calendar_event(target_calendar, dup_uid)
                                deleted += 1
                            except Exception as e:
                                logger.debug(f"Shift sync dedup error: {e}")
                    else:
                        for ha_uid in ha_uids:
                            try:
                                self.ha.delete_calendar_event(target_calendar, ha_uid)
                                deleted += 1
                            except Exception as e:
                                logger.debug(f"Shift sync delete error: {e}")
            else:
                logger.debug(f"Shift sync: skipping delete on remote calendar {target_calendar}")

            # --- Step 4: Create missing events ---
            created = 0
            for key, ev_data in expected_events.items():
                if key in existing_mh and len(existing_mh[key]) >= 1:
                    continue  # Already exists in HA
                try:
                    self.ha.create_calendar_event(
                        entity_id=target_calendar,
                        summary=ev_data["summary"],
                        start=ev_data["start"],
                        end=ev_data["end"],
                        description=ev_data["description"],
                    )
                    created += 1
                except Exception as e:
                    logger.debug(f"Shift sync create error: {e}")

            if created > 0 or deleted > 0:
                logger.info(f"Shift calendar sync: +{created} -{deleted} in {target_calendar}")

        except Exception as e:
            logger.warning(f"Shift calendar sync error: {e}")

    def _run_periodic(self, task_func, interval_seconds, task_name):
        """Run a task periodically."""
        # Initial delay: 120s after startup
        waited = 0
        while waited < 120 and self._should_run:
            time.sleep(5)
            waited += 5

        while self._should_run:
            try:
                task_func()
            except Exception as e:
                logger.error(f"Task {task_name} error: {e}")

            slept = 0
            while slept < interval_seconds and self._should_run:
                time.sleep(10)
                slept += 10

    def _anomaly_task(self):
        """Run anomaly detection periodically."""
        waited = 0
        while waited < 180 and self._should_run:
            time.sleep(5)
            waited += 5

        while self._should_run:
            try:
                anomalies = self.anomaly_det.check_recent_anomalies(minutes=15)
                # Limit to max 5 notifications per cycle to avoid spam
                for a in anomalies[:5]:
                    self.notification_mgr.notify_anomaly(a)
                if len(anomalies) > 5:
                    logger.info(f"Anomaly check: {len(anomalies)} found, notified first 5")
            except Exception as e:
                logger.error(f"Anomaly task error: {e}")

            slept = 0
            while slept < 900 and self._should_run:  # 15 min
                time.sleep(10)
                slept += 10

    def _plugin_conflict_task(self):
        """Phase 3: Check for plugin conflicts."""
        try:
            conflicts = self.plugin_conflict_det.check_conflicts()
            for c in conflicts[:3]:
                if not self.quiet_hours_mgr.is_quiet_time():
                    self.notification_mgr.notify_anomaly({
                        "entity_id": "",
                        "reason_de": c["message_de"],
                        "reason_en": c["message_en"],
                        "type": "plugin_conflict",
                    })
        except Exception as e:
            logger.warning(f"Plugin conflict task error: {e}")
