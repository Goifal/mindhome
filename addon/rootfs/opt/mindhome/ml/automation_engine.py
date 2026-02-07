"""
MindHome - Automation Engine (Phase 2b)
Suggestions, execution, undo, conflict detection, phase management.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import func, text, and_
from sqlalchemy.orm import sessionmaker

from models import (
    get_engine, LearnedPattern, Prediction, Device, Domain, Room,
    RoomDomainState, LearningPhase, ActionLog, NotificationLog,
    NotificationType, NotificationSetting, SystemSetting, StateHistory
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
                    pattern.updated_at = datetime.utcnow()

                    # Create prediction (suggestion entry)
                    prediction = Prediction(
                        pattern_id=pattern.id,
                        predicted_action=pattern.action_definition or {},
                        predicted_for=datetime.utcnow(),
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
            pred = session.query(Prediction).get(prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            pred.status = "confirmed"
            pred.user_response = "confirmed"
            pred.responded_at = datetime.utcnow()

            # Update pattern confidence
            pattern = session.query(LearnedPattern).get(pred.pattern_id)
            if pattern:
                pattern.confidence = min(pattern.confidence + 0.15, 1.0)
                pattern.times_confirmed += 1
                pattern.status = "active"
                pattern.updated_at = datetime.utcnow()

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
            pred = session.query(Prediction).get(prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            pred.status = "rejected"
            pred.user_response = "rejected"
            pred.responded_at = datetime.utcnow()

            # Decrease pattern confidence
            pattern = session.query(LearnedPattern).get(pred.pattern_id)
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

                pattern.updated_at = datetime.utcnow()

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
            pred = session.query(Prediction).get(prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            pred.status = "ignored"
            pred.user_response = "ignored"
            pred.responded_at = datetime.utcnow()
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
            # Find active patterns with time-based triggers
            active_patterns = session.query(LearnedPattern).filter_by(
                status="active", is_active=True
            ).all()

            now = datetime.now()

            for pattern in active_patterns:
                trigger = pattern.trigger_conditions or {}
                trigger_type = trigger.get("type")

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

            # Create execution record
            prediction = Prediction(
                pattern_id=pattern.id,
                predicted_action=action,
                predicted_for=datetime.utcnow(),
                confidence=pattern.confidence,
                status="executed",
                was_executed=True,
                previous_state={"entity_id": entity_id, "state": previous_state},
                executed_at=datetime.utcnow(),
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
            pred = session.query(Prediction).get(prediction_id)
            if not pred:
                return {"error": "Prediction not found"}

            if pred.status != "executed":
                return {"error": "Can only undo executed predictions"}

            # Check undo window
            if pred.executed_at:
                elapsed = (datetime.utcnow() - pred.executed_at).total_seconds() / 60
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
            pred.undone_at = datetime.utcnow()

            # Decrease pattern confidence slightly
            pattern = session.query(LearnedPattern).get(pred.pattern_id)
            if pattern:
                pattern.confidence = max(pattern.confidence - 0.1, 0.0)
                pattern.updated_at = datetime.utcnow()

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

        finally:
            session.close()


# ==============================================================================
# E1-E4: Phase Manager
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
                    rds.phase_started_at = datetime.utcnow()
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
            days = (datetime.utcnow() - rds.phase_started_at).days
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
            days = (datetime.utcnow() - rds.phase_started_at).days
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
            rds.phase_started_at = datetime.utcnow()
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
    """Detects unusual events based on deviation from patterns."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

    def check_recent_anomalies(self, minutes=30):
        """Check recent events for anomalies."""
        session = self.Session()
        anomalies = []
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=minutes)
            recent = session.query(StateHistory).filter(
                StateHistory.created_at >= cutoff
            ).all()

            for event in recent:
                ctx = event.context or {}
                hour = ctx.get("hour", 12)
                time_slot = ctx.get("time_slot", "")

                # Check: activity during unusual hours (night = 23-5)
                if time_slot == "night" and event.new_state == "on":
                    ha_domain = event.entity_id.split(".")[0]
                    if ha_domain in ("light", "switch"):
                        # Is this normal? Check if any pattern exists for this
                        pattern_exists = session.query(LearnedPattern).filter(
                            LearnedPattern.is_active == True,
                            LearnedPattern.pattern_data.contains(event.entity_id) if hasattr(LearnedPattern.pattern_data, 'contains') else True
                        ).first()

                        # Simple heuristic: no pattern + night activity = anomaly
                        if not pattern_exists:
                            device = session.query(Device).filter_by(
                                ha_entity_id=event.entity_id
                            ).first()
                            device_name = device.name if device else event.entity_id

                            anomalies.append({
                                "entity_id": event.entity_id,
                                "device_name": device_name,
                                "event": f"{event.old_state} → {event.new_state}",
                                "time": event.created_at.isoformat() if event.created_at else None,
                                "reason_de": f"{device_name} wurde nachts um {hour}:00 eingeschaltet",
                                "reason_en": f"{device_name} turned on at {hour}:00 during night",
                                "severity": "warning",
                            })

            return anomalies

        except Exception as e:
            logger.error(f"Anomaly check error: {e}")
            return []
        finally:
            session.close()


# ==============================================================================
# G1+G3: Notification Manager
# ==============================================================================

class NotificationManager:
    """Manages notifications for suggestions, anomalies, and events."""

    def __init__(self, engine, ha_connection):
        self.engine = engine
        self.ha = ha_connection
        self.Session = sessionmaker(bind=engine)

    def notify_suggestion(self, prediction_id, lang="de"):
        """Send notification about a new suggestion."""
        session = self.Session()
        try:
            pred = session.query(Prediction).get(prediction_id)
            if not pred:
                return

            desc = pred.description_de if lang == "de" else (pred.description_en or pred.description_de)
            title = "MindHome: Neuer Vorschlag" if lang == "de" else "MindHome: New Suggestion"
            message = desc or "MindHome hat ein neues Muster erkannt"

            # Save to notification log
            notif = NotificationLog(
                user_id=1,  # Default user
                notification_type=NotificationType.SUGGESTION,
                title=title,
                message=message,
                was_sent=False,
                was_read=False,
            )
            session.add(notif)

            # Try to send via HA notification service
            try:
                self.ha.call_service("notify", "persistent_notification", {
                    "title": title,
                    "message": message,
                })
                notif.was_sent = True
                pred.notification_sent = True
            except Exception as e:
                logger.debug(f"HA notification failed (non-critical): {e}")

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Notification error: {e}")
        finally:
            session.close()

    def notify_anomaly(self, anomaly, lang="de"):
        """Send notification about an anomaly."""
        session = self.Session()
        try:
            title = "MindHome: Ungewöhnliche Aktivität" if lang == "de" else "MindHome: Unusual Activity"
            message = anomaly.get("reason_de" if lang == "de" else "reason_en", "")

            notif = NotificationLog(
                user_id=1,
                notification_type=NotificationType.ANOMALY,
                title=title,
                message=message,
                was_sent=False,
                was_read=False,
            )
            session.add(notif)

            try:
                self.ha.call_service("notify", "persistent_notification", {
                    "title": title,
                    "message": message,
                })
                notif.was_sent = True
            except Exception:
                pass

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
        finally:
            session.close()

    def mark_read(self, notification_id):
        """Mark a notification as read."""
        session = self.Session()
        try:
            n = session.query(NotificationLog).get(notification_id)
            if n:
                n.was_read = True
                session.commit()
                return True
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
        finally:
            session.close()


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
        self._should_run = True
        self._threads = []

    def start(self):
        """Start Phase 2b background tasks."""
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

        logger.info("Automation Scheduler started (exec:1min, suggest:4h, phase:12h, anomaly:15min)")

    def stop(self):
        self._should_run = False
        logger.info("Automation Scheduler stopped")

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
                for a in anomalies:
                    self.notification_mgr.notify_anomaly(a)
            except Exception as e:
                logger.error(f"Anomaly task error: {e}")

            slept = 0
            while slept < 900 and self._should_run:  # 15 min
                time.sleep(10)
                slept += 10
