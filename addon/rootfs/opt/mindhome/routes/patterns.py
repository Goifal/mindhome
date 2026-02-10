# MindHome routes/patterns v0.6.2 (2026-02-10) - routes/patterns.py
"""
MindHome API Routes - Patterns
Auto-extracted from monolithic app.py during Phase 3.5 refactoring.
"""

import os
import json
import logging
import time
import csv
import io
import hashlib
import zipfile
import shutil
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, Response, make_response, send_from_directory, redirect
from sqlalchemy import func as sa_func, text

from db import get_db_session, get_db_readonly, get_db
from helpers import (
    get_ha_timezone, local_now, utc_iso, sanitize_input, sanitize_dict,
    audit_log, is_debug_mode, set_debug_mode, get_setting, set_setting,
    get_language, localize, extract_display_attributes, build_state_reason,
)
from models import (
    get_engine, get_session, User, UserRole, Room, Domain, Device,
    RoomDomainState, LearningPhase, QuickAction, SystemSetting,
    UserPreference, NotificationSetting, NotificationType,
    NotificationPriority, NotificationChannel, DeviceMute, ActionLog,
    DataCollection, OfflineActionQueue, StateHistory, LearnedPattern,
    PatternMatchLog, Prediction, NotificationLog, PatternExclusion,
    ManualRule, AnomalySetting, DeviceGroup, AuditTrail,
    DayPhase, RoomOrientation, PersonDevice, GuestDevice,
    PresenceMode, PresenceLog, SensorGroup, SensorThreshold,
    EnergyConfig, EnergyReading, StandbyConfig, LearnedScene,
    PluginSetting, QuietHoursConfig, SchoolVacation,
    PersonSchedule, ShiftTemplate, Holiday, PatternSettings,
)

logger = logging.getLogger("mindhome.routes.patterns")

patterns_bp = Blueprint("patterns", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_patterns(dependencies):
    """Initialize patterns routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@patterns_bp.route("/api/patterns", methods=["GET"])
def api_get_patterns():
    """Get all learned patterns with optional filters."""
    session = get_db()
    try:
        lang = get_language()
        status_filter = request.args.get("status")
        pattern_type = request.args.get("type")
        room_id = request.args.get("room_id", type=int)
        domain_id = request.args.get("domain_id", type=int)

        query = session.query(LearnedPattern).order_by(LearnedPattern.confidence.desc())

        if status_filter:
            query = query.filter_by(status=status_filter)
        if pattern_type:
            query = query.filter_by(pattern_type=pattern_type)
        if room_id:
            query = query.filter_by(room_id=room_id)
        if domain_id:
            query = query.filter_by(domain_id=domain_id)

        # Default: only active, exclude insights unless explicitly requested
        if not status_filter:
            query = query.filter_by(is_active=True).filter(LearnedPattern.status != 'insight')

        total = query.count()
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        patterns = query.offset(offset).limit(limit).all()

        return jsonify({
            "items": [{
                "id": p.id,
                "pattern_type": p.pattern_type,
                "description": p.description_de if lang == "de" else (p.description_en or p.description_de),
                "description_de": p.description_de,
                "description_en": p.description_en,
                "confidence": round(p.confidence, 3),
                "status": p.status or "observed",
                "is_active": p.is_active,
                "match_count": p.match_count or 0,
                "times_confirmed": p.times_confirmed,
                "times_rejected": p.times_rejected,
                "domain_id": p.domain_id,
                "room_id": p.room_id,
                "user_id": p.user_id,
                "trigger_conditions": p.trigger_conditions,
                "action_definition": p.action_definition,
                "pattern_data": p.pattern_data,
                "last_matched_at": utc_iso(p.last_matched_at),
                "created_at": utc_iso(p.created_at),
                "updated_at": utc_iso(p.updated_at),
            } for p in patterns],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total
        })
    finally:
        session.close()



@patterns_bp.route("/api/patterns/<int:pattern_id>", methods=["PUT"])
def api_update_pattern(pattern_id):
    """Update pattern status (activate/deactivate/disable)."""
    data = request.json
    session = get_db()
    try:
        pattern = session.get(LearnedPattern, pattern_id)
        if not pattern:
            return jsonify({"error": "Pattern not found"}), 404

        if "is_active" in data:
            pattern.is_active = data["is_active"]
        if "status" in data and data["status"] in ("observed", "suggested", "active", "disabled"):
            pattern.status = data["status"]
            if data["status"] == "disabled":
                pattern.is_active = False
            elif data["status"] in ("observed", "suggested", "active"):
                pattern.is_active = True

        pattern.updated_at = datetime.now(timezone.utc)
        session.commit()
        return jsonify({"success": True, "id": pattern.id, "status": pattern.status})
    finally:
        session.close()



@patterns_bp.route("/api/patterns/<int:pattern_id>", methods=["DELETE"])
def api_delete_pattern(pattern_id):
    """Delete a pattern permanently."""
    session = get_db()
    try:
        pattern = session.get(LearnedPattern, pattern_id)
        if not pattern:
            return jsonify({"error": "Pattern not found"}), 404

        # Delete match logs first
        session.query(PatternMatchLog).filter_by(pattern_id=pattern_id).delete()
        session.delete(pattern)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@patterns_bp.route("/api/patterns/analyze", methods=["POST"])
def api_trigger_analysis():
    """Manually trigger pattern analysis."""
    _deps.get("pattern_scheduler").trigger_analysis_now()
    return jsonify({"success": True, "message": "Analysis started in background"})



@patterns_bp.route("/api/patterns/reclassify-insights", methods=["POST"])
def api_reclassify_insights():
    """Reclassify existing sensor→sensor patterns as 'insight'."""
    session = get_db()
    try:
        NON_ACTIONABLE = ("sensor.", "binary_sensor.", "sun.", "weather.", "zone.", "person.", "device_tracker.", "calendar.", "proximity.")
        patterns = session.query(LearnedPattern).filter(
            LearnedPattern.status == "observed",
            LearnedPattern.is_active == True
        ).all()
        reclassified = 0
        for p in patterns:
            pd = p.pattern_data or {}
            is_sensor_pair = False
            if p.pattern_type == "event_chain":
                t_eid = pd.get("trigger_entity", "")
                a_eid = pd.get("action_entity", "")
                if (any(t_eid.startswith(x) for x in NON_ACTIONABLE) and
                    any(a_eid.startswith(x) for x in NON_ACTIONABLE)):
                    is_sensor_pair = True
            elif p.pattern_type == "correlation":
                c_eid = pd.get("condition_entity", "")
                r_eid = pd.get("correlated_entity", "")
                if (any(c_eid.startswith(x) for x in NON_ACTIONABLE) and
                    any(r_eid.startswith(x) for x in NON_ACTIONABLE)):
                    is_sensor_pair = True
            if is_sensor_pair:
                p.status = "insight"
                reclassified += 1
        session.commit()
        return jsonify({"success": True, "reclassified": reclassified})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@patterns_bp.route("/api/state-history", methods=["GET"])
def api_get_state_history():
    """Get state history events with filters."""
    session = get_db()
    try:
        entity_id = request.args.get("entity_id")
        device_id = request.args.get("device_id", type=int)
        hours = request.args.get("hours", 24, type=int)
        limit = request.args.get("limit", 200, type=int)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = session.query(StateHistory).filter(
            StateHistory.created_at >= cutoff
        ).order_by(StateHistory.created_at.desc())

        if entity_id:
            query = query.filter_by(entity_id=entity_id)
        if device_id:
            query = query.filter_by(device_id=device_id)

        events = query.limit(min(limit, 1000)).all()

        return jsonify([{
            "id": e.id,
            "entity_id": e.entity_id,
            "device_id": e.device_id,
            "old_state": e.old_state,
            "new_state": e.new_state,
            "new_attributes": e.new_attributes,
            "context": e.context,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events])
    finally:
        session.close()



@patterns_bp.route("/api/state-history/count", methods=["GET"])
def api_state_history_count():
    """Get total event count and date range."""
    session = get_db()
    try:

        total = session.query(sa_func.count(StateHistory.id)).scalar() or 0
        oldest = session.query(sa_func.min(StateHistory.created_at)).scalar()
        newest = session.query(sa_func.max(StateHistory.created_at)).scalar()

        return jsonify({
            "total_events": total,
            "oldest_event": oldest.isoformat() if oldest else None,
            "newest_event": newest.isoformat() if newest else None,
        })
    finally:
        session.close()



@patterns_bp.route("/api/stats/learning", methods=["GET"])
def api_learning_stats():
    """Get learning progress statistics for dashboard."""
    session = get_db()
    try:


        # Event counts
        total_events = session.query(sa_func.count(StateHistory.id)).scalar() or 0
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        events_today = session.query(sa_func.count(StateHistory.id)).filter(
            StateHistory.created_at >= today_start
        ).scalar() or 0

        # Pattern counts
        total_patterns = session.query(sa_func.count(LearnedPattern.id)).filter_by(is_active=True).scalar() or 0
        patterns_by_type = {}
        for ptype in ["time_based", "event_chain", "correlation"]:
            patterns_by_type[ptype] = session.query(sa_func.count(LearnedPattern.id)).filter_by(
                pattern_type=ptype, is_active=True
            ).scalar() or 0

        patterns_by_status = {}
        for status in ["observed", "suggested", "active", "disabled"]:
            patterns_by_status[status] = session.query(sa_func.count(LearnedPattern.id)).filter_by(
                status=status
            ).scalar() or 0

        # Average confidence
        avg_confidence = session.query(sa_func.avg(LearnedPattern.confidence)).filter_by(
            is_active=True
        ).scalar() or 0.0

        # Top patterns (highest confidence)
        lang = get_language()
        top_patterns = session.query(LearnedPattern).filter_by(
            is_active=True
        ).order_by(LearnedPattern.confidence.desc()).limit(5).all()

        # Room/Domain learning phases
        room_domain_states = session.query(RoomDomainState).all()
        phases = {"observing": 0, "suggesting": 0, "autonomous": 0}
        for rds in room_domain_states:
            phase_val = rds.learning_phase.value if rds.learning_phase else "observing"
            phases[phase_val] = phases.get(phase_val, 0) + 1

        # Events per domain (from DataCollection)
        data_collections = session.query(DataCollection).filter_by(data_type="state_changes").all()
        events_by_domain = {}
        for dc in data_collections:
            domain = session.get(Domain, dc.domain_id)
            dname = domain.name if domain else str(dc.domain_id)
            events_by_domain[dname] = events_by_domain.get(dname, 0) + dc.record_count

        # Days of data collected
        oldest = session.query(sa_func.min(StateHistory.created_at)).scalar()
        if oldest and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        days_collecting = (datetime.now(timezone.utc) - oldest).days if oldest else 0

        return jsonify({
            "total_events": total_events,
            "events_today": events_today,
            "days_collecting": days_collecting,
            "total_patterns": total_patterns,
            "patterns_by_type": patterns_by_type,
            "patterns_by_status": patterns_by_status,
            "avg_confidence": round(avg_confidence, 3),
            "learning_phases": phases,
            "events_by_domain": events_by_domain,
            "top_patterns": [{
                "id": p.id,
                "description": p.description_de if lang == "de" else (p.description_en or p.description_de),
                "confidence": round(p.confidence, 3),
                "pattern_type": p.pattern_type,
                "match_count": p.match_count or 0,
            } for p in top_patterns],
            "learning_speed": get_setting("learning_speed") or "normal",
        })
    finally:
        session.close()



@patterns_bp.route("/api/patterns/reject/<int:pattern_id>", methods=["PUT"])
def api_reject_pattern(pattern_id):
    """Reject a pattern and archive it with reason."""
    data = request.json
    session = get_db()
    try:
        pattern = session.get(LearnedPattern, pattern_id)
        if not pattern:
            return jsonify({"error": "Not found"}), 404
        pattern.status = "rejected"
        pattern.is_active = False
        pattern.rejection_reason = data.get("reason", "unwanted")
        pattern.rejected_at = datetime.now(timezone.utc)
        pattern.times_rejected = (pattern.times_rejected or 0) + 1
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@patterns_bp.route("/api/patterns/reactivate/<int:pattern_id>", methods=["PUT"])
def api_reactivate_pattern(pattern_id):
    """Reactivate a rejected pattern."""
    session = get_db()
    try:
        pattern = session.get(LearnedPattern, pattern_id)
        if not pattern:
            return jsonify({"error": "Not found"}), 404
        pattern.status = "suggested"
        pattern.is_active = True
        pattern.rejection_reason = None
        pattern.rejected_at = None
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@patterns_bp.route("/api/patterns/rejected", methods=["GET"])
def api_get_rejected_patterns():
    """Get all rejected patterns with pagination."""
    session = get_db()
    try:
        query = session.query(LearnedPattern).filter_by(status="rejected").order_by(
            LearnedPattern.rejected_at.desc()
        )
        total = query.count()
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        patterns = query.offset(offset).limit(limit).all()
        lang = get_language()
        return jsonify({
            "items": [{
                "id": p.id, "pattern_type": p.pattern_type,
                "description": p.description_de if lang == "de" else p.description_en,
                "confidence": p.confidence, "rejection_reason": p.rejection_reason,
                "rejected_at": p.rejected_at.isoformat() if p.rejected_at else None,
                "category": p.category,
            } for p in patterns],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total
        })
    finally:
        session.close()



@patterns_bp.route("/api/patterns/test-mode/<int:pattern_id>", methods=["PUT"])
def api_pattern_test_mode(pattern_id):
    """Toggle test/simulation mode for a pattern."""
    data = request.json
    session = get_db()
    try:
        pattern = session.get(LearnedPattern, pattern_id)
        if not pattern:
            return jsonify({"error": "Not found"}), 404
        pattern.test_mode = data.get("enabled", True)
        if pattern.test_mode:
            pattern.test_results = []
        session.commit()
        return jsonify({"success": True, "test_mode": pattern.test_mode})
    finally:
        session.close()



@patterns_bp.route("/api/pattern-exclusions", methods=["GET"])
def api_get_exclusions():
    """Get all pattern exclusions."""
    session = get_db()
    try:
        exclusions = session.query(PatternExclusion).all()
        return jsonify([{
            "id": e.id, "type": e.exclusion_type,
            "entity_a": e.entity_a, "entity_b": e.entity_b,
            "reason": e.reason,
        } for e in exclusions])
    finally:
        session.close()



@patterns_bp.route("/api/pattern-exclusions", methods=["POST"])
def api_create_exclusion():
    """Create a pattern exclusion rule."""
    data = request.json
    session = get_db()
    try:
        excl = PatternExclusion(
            exclusion_type=data.get("type", "device_pair"),
            entity_a=data["entity_a"], entity_b=data["entity_b"],
            reason=data.get("reason"), created_by=1
        )
        session.add(excl)
        session.commit()
        return jsonify({"success": True, "id": excl.id}), 201
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@patterns_bp.route("/api/pattern-exclusions/<int:excl_id>", methods=["DELETE"])
def api_delete_exclusion(excl_id):
    """Delete a pattern exclusion."""
    session = get_db()
    try:
        excl = session.get(PatternExclusion, excl_id)
        if excl:
            session.delete(excl)
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@patterns_bp.route("/api/manual-rules", methods=["GET"])
def api_get_manual_rules():
    """Get all manual rules."""
    session = get_db()
    try:
        rules = session.query(ManualRule).order_by(ManualRule.created_at.desc()).all()
        return jsonify([{
            "id": r.id, "name": r.name,
            "trigger_entity": r.trigger_entity, "trigger_state": r.trigger_state,
            "action_entity": r.action_entity, "action_service": r.action_service,
            "action_data": r.action_data, "conditions": r.conditions,
            "delay_seconds": r.delay_seconds, "is_active": r.is_active,
            "execution_count": r.execution_count,
            "last_executed_at": r.last_executed_at.isoformat() if r.last_executed_at else None,
        } for r in rules])
    finally:
        session.close()



@patterns_bp.route("/api/manual-rules", methods=["POST"])
def api_create_manual_rule():
    """Create a manual rule."""
    data = request.json
    session = get_db()
    try:
        rule = ManualRule(
            name=data.get("name", "Rule"),
            trigger_entity=data["trigger_entity"],
            trigger_state=data["trigger_state"],
            action_entity=data["action_entity"],
            action_service=data.get("action_service", "turn_on"),
            action_data=data.get("action_data"),
            conditions=data.get("conditions"),
            delay_seconds=data.get("delay_seconds", 0),
            is_active=True, created_by=1
        )
        session.add(rule)
        session.commit()
        return jsonify({"success": True, "id": rule.id}), 201
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@patterns_bp.route("/api/manual-rules/<int:rule_id>", methods=["PUT"])
def api_update_manual_rule(rule_id):
    """Update a manual rule."""
    data = request.json
    session = get_db()
    try:
        rule = session.get(ManualRule, rule_id)
        if not rule:
            return jsonify({"error": "Not found"}), 404
        for key in ["name", "trigger_entity", "trigger_state", "action_entity",
                     "action_service", "action_data", "conditions", "delay_seconds", "is_active"]:
            if key in data:
                setattr(rule, key, data[key])
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@patterns_bp.route("/api/manual-rules/<int:rule_id>", methods=["DELETE"])
def api_delete_manual_rule(rule_id):
    """Delete a manual rule."""
    session = get_db()
    try:
        rule = session.get(ManualRule, rule_id)
        if rule:
            session.delete(rule)
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@patterns_bp.route("/api/patterns/conflicts", methods=["GET"])
def api_pattern_conflicts():
    """Detect conflicting patterns."""
    session = get_db()
    try:
        active = session.query(LearnedPattern).filter_by(is_active=True).all()
        conflicts = []
        for i, p1 in enumerate(active):
            for p2 in active[i+1:]:
                pd1 = p1.pattern_data or {}
                pd2 = p2.pattern_data or {}
                # Same entity, different target state, overlapping time
                e1 = pd1.get("entity_id") or (p1.action_definition or {}).get("entity_id")
                e2 = pd2.get("entity_id") or (p2.action_definition or {}).get("entity_id")
                if e1 and e1 == e2:
                    t1 = (p1.action_definition or {}).get("target_state")
                    t2 = (p2.action_definition or {}).get("target_state")
                    if t1 and t2 and t1 != t2:
                        h1 = pd1.get("avg_hour")
                        h2 = pd2.get("avg_hour")
                        if h1 is not None and h2 is not None and abs(h1 - h2) < 1:
                            conflicts.append({
                                "pattern_a": {"id": p1.id, "desc": p1.description_de, "target": t1, "hour": h1},
                                "pattern_b": {"id": p2.id, "desc": p2.description_de, "target": t2, "hour": h2},
                                "entity": e1,
                                "message_de": f"Konflikt: {e1} soll um ~{h1:.0f}h sowohl '{t1}' als auch '{t2}' sein",
                                "message_en": f"Conflict: {e1} at ~{h1:.0f}h targets both '{t1}' and '{t2}'",
                            })
        return jsonify({"conflicts": conflicts, "total": len(conflicts)})
    except Exception as e:
        logger.error(f"Pattern conflict detection error: {e}")
        return jsonify({"conflicts": [], "total": 0, "error": str(e)})
    finally:
        session.close()


@patterns_bp.route("/api/patterns/scenes", methods=["GET"])
def api_detect_scenes():
    """Detect groups of devices that are often switched together → suggest scenes."""
    session = get_db()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        history = session.query(StateHistory).filter(
            StateHistory.created_at > cutoff
        ).order_by(StateHistory.created_at).all()

        # Group state changes by 30-second windows
        windows = defaultdict(list)
        for h in history:
            window_key = int(h.created_at.timestamp() // 30)
            windows[window_key].append(h.entity_id)

        # Find entity groups that appear together >= 5 times
        pair_counts = defaultdict(int)
        for entities in windows.values():
            unique = sorted(set(entities))
            if 2 <= len(unique) <= 6:
                key = tuple(unique)
                pair_counts[key] += 1

        scenes = []
        for entities, count in sorted(pair_counts.items(), key=lambda x: -x[1]):
            if count >= 5:
                scenes.append({
                    "entities": list(entities),
                    "count": count,
                    "message_de": f"{len(entities)} Geräte werden oft zusammen geschaltet ({count}×)",
                    "message_en": f"{len(entities)} devices are often switched together ({count}×)",
                })
            if len(scenes) >= 10:
                break

        return jsonify({"scenes": scenes})
    except Exception as e:
        logger.error(f"Scene detection error: {e}")
        return jsonify({"scenes": [], "error": str(e)})
    finally:
        session.close()


# ==============================================================================
# Pattern Settings API (v0.6.1)
# ==============================================================================

PATTERN_SETTINGS_DEFAULTS = {
    "chain_window_seconds": {"value": "120", "category": "thresholds", "description_de": "Zeitfenster für Sequenz-Erkennung (Sekunden)", "description_en": "Time window for sequence detection (seconds)"},
    "min_sequence_count": {"value": "7", "category": "thresholds", "description_de": "Minimum Vorkommen für Sequenz-Muster", "description_en": "Minimum occurrences for sequence patterns"},
    "min_confidence": {"value": "0.45", "category": "thresholds", "description_de": "Minimale Confidence für Muster", "description_en": "Minimum confidence for patterns"},
    "learning_speed": {"value": "normal", "category": "general", "description_de": "Lerngeschwindigkeit (cautious/normal/aggressive)", "description_en": "Learning speed (cautious/normal/aggressive)"},
    "anomaly_person_threshold": {"value": "50", "category": "anomaly", "description_de": "Anomalie-Schwelle für Personen (GPS-Jitter)", "description_en": "Anomaly threshold for persons (GPS jitter)"},
    "anomaly_heatpump_sensitivity": {"value": "low", "category": "anomaly", "description_de": "Empfindlichkeit für Wärmepumpen-Anomalien (low/medium/high)", "description_en": "Heatpump anomaly sensitivity (low/medium/high)"},
}

LEARNING_SPEED_PRESETS = {
    "cautious": {"min_confidence": "0.60", "min_sequence_count": "10", "chain_window_seconds": "90"},
    "normal": {"min_confidence": "0.45", "min_sequence_count": "7", "chain_window_seconds": "120"},
    "aggressive": {"min_confidence": "0.30", "min_sequence_count": "4", "chain_window_seconds": "180"},
}


@patterns_bp.route("/api/pattern-settings", methods=["GET"])
def api_get_pattern_settings():
    """#25: Get all pattern settings with defaults for missing keys."""
    session = get_db()
    try:
        existing = {ps.key: ps for ps in session.query(PatternSettings).all()}
        result = {}
        for key, defaults in PATTERN_SETTINGS_DEFAULTS.items():
            if key in existing:
                ps = existing[key]
                result[key] = {
                    "value": ps.value,
                    "category": ps.category or defaults["category"],
                    "description_de": ps.description_de or defaults["description_de"],
                    "description_en": ps.description_en or defaults["description_en"],
                }
            else:
                result[key] = defaults.copy()

        # #37: _meta with is_custom and active_preset
        current_vals = {k: result[k]["value"] for k in result}
        active_preset = None
        is_custom = True
        for preset_name, preset_vals in LEARNING_SPEED_PRESETS.items():
            if all(current_vals.get(k) == v for k, v in preset_vals.items()):
                active_preset = preset_name
                is_custom = False
                break

        return jsonify({
            "settings": result,
            "_meta": {
                "is_custom": is_custom,
                "active_preset": active_preset,
            }
        })
    finally:
        session.close()


@patterns_bp.route("/api/pattern-settings", methods=["PUT"])
def api_update_pattern_settings():
    """#25: Update pattern settings."""
    data = request.json or {}
    session = get_db()
    try:
        updated = []
        for key, value in data.items():
            if key.startswith("_"):
                continue
            ps = session.query(PatternSettings).filter_by(key=key).first()
            if ps:
                ps.value = str(value)
            else:
                defaults = PATTERN_SETTINGS_DEFAULTS.get(key, {})
                ps = PatternSettings(
                    key=key,
                    value=str(value),
                    category=defaults.get("category", "general"),
                    description_de=defaults.get("description_de"),
                    description_en=defaults.get("description_en"),
                )
                session.add(ps)
            updated.append(key)
        session.commit()
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@patterns_bp.route("/api/pattern-settings/preset/<name>", methods=["POST"])
def api_apply_preset(name):
    """#32: Apply a learning speed preset."""
    if name not in LEARNING_SPEED_PRESETS:
        return jsonify({"error": f"Unknown preset: {name}", "available": list(LEARNING_SPEED_PRESETS.keys())}), 400

    preset = LEARNING_SPEED_PRESETS[name]
    session = get_db()
    try:
        for key, value in preset.items():
            ps = session.query(PatternSettings).filter_by(key=key).first()
            if ps:
                ps.value = value
            else:
                defaults = PATTERN_SETTINGS_DEFAULTS.get(key, {})
                ps = PatternSettings(
                    key=key, value=value,
                    category=defaults.get("category", "thresholds"),
                    description_de=defaults.get("description_de"),
                    description_en=defaults.get("description_en"),
                )
                session.add(ps)

        # Also set learning_speed key
        ls = session.query(PatternSettings).filter_by(key="learning_speed").first()
        if ls:
            ls.value = name
        else:
            session.add(PatternSettings(key="learning_speed", value=name, category="general"))

        session.commit()
        return jsonify({"success": True, "preset": name, "values": preset})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@patterns_bp.route("/api/stats/learning-days", methods=["GET"])
def api_learning_days():
    """#2: Calculate days of data from oldest StateHistory entry."""
    session = get_db()
    try:
        oldest = session.query(sa_func.min(StateHistory.created_at)).scalar()
        total = session.query(sa_func.count(StateHistory.id)).scalar() or 0
        if oldest:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - oldest).days
        else:
            days = 0
        return jsonify({"days": days, "total_events": total})
    finally:
        session.close()
