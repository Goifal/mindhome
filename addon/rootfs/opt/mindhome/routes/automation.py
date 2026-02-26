# MindHome - routes/automation.py | see version.py for version info
"""
MindHome API Routes - Automation
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
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, Response, make_response, send_from_directory, redirect
from sqlalchemy import func as sa_func, text

from db import get_db_session, get_db_readonly
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
    PersonSchedule, ShiftTemplate, Holiday,
)

logger = logging.getLogger("mindhome.routes.automation")

automation_bp = Blueprint("automation", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_automation(dependencies):
    """Initialize automation routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@automation_bp.route("/api/predictions", methods=["GET"])
def api_get_predictions():
    """Get suggestions/predictions with filters."""
    with get_db_session() as session:
        lang = get_language()
        status = request.args.get("status")
        limit = request.args.get("limit", 50, type=int)

        query = session.query(Prediction).order_by(Prediction.created_at.desc())

        if status:
            query = query.filter_by(status=status)

        preds = query.limit(min(limit, 200)).all()

        return jsonify([{
            "id": p.id,
            "pattern_id": p.pattern_id,
            "description": p.description_de if lang == "de" else (p.description_en or p.description_de),
            "description_de": p.description_de,
            "description_en": p.description_en,
            "predicted_action": p.predicted_action,
            "confidence": round(p.confidence, 3),
            "status": p.status or "pending",
            "user_response": p.user_response,
            "was_executed": p.was_executed,
            "previous_state": p.previous_state,
            "executed_at": p.executed_at.isoformat() if p.executed_at else None,
            "responded_at": p.responded_at.isoformat() if p.responded_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        } for p in preds])



@automation_bp.route("/api/predictions/<int:pred_id>/confirm", methods=["POST"])
def api_confirm_prediction(pred_id):
    """Confirm a suggestion."""
    result = _deps.get("automation_scheduler").feedback.confirm_prediction(pred_id)
    return jsonify(result)



@automation_bp.route("/api/predictions/<int:pred_id>/reject", methods=["POST"])
def api_reject_prediction(pred_id):
    """Reject a suggestion."""
    result = _deps.get("automation_scheduler").feedback.reject_prediction(pred_id)
    return jsonify(result)



@automation_bp.route("/api/predictions/<int:pred_id>/ignore", methods=["POST"])
def api_ignore_prediction(pred_id):
    """Ignore / postpone a suggestion."""
    result = _deps.get("automation_scheduler").feedback.ignore_prediction(pred_id)
    return jsonify(result)



@automation_bp.route("/api/predictions/<int:pred_id>/undo", methods=["POST"])
def api_undo_prediction(pred_id):
    """Undo an executed automation."""
    result = _deps.get("automation_scheduler").executor.undo_prediction(pred_id)
    return jsonify(result)



@automation_bp.route("/api/automation/emergency-stop", methods=["POST"])
def api_automation_emergency_stop():
    """Activate/deactivate emergency stop for all automations."""
    data = request.json or {}
    active = data.get("active", True)
    _deps.get("automation_scheduler").executor.set_emergency_stop(active)

    # Also update system mode
    set_setting("system_mode", "emergency_stop" if active else "normal")

    return jsonify({"success": True, "emergency_stop": active})



@automation_bp.route("/api/automation/conflicts", methods=["GET"])
def api_get_conflicts():
    """Get detected pattern conflicts."""
    conflicts = _deps.get("automation_scheduler").conflict_det.check_conflicts()
    return jsonify(conflicts)



@automation_bp.route("/api/automation/generate-suggestions", methods=["POST"])
def api_generate_suggestions():
    """Manually trigger suggestion generation."""
    count = _deps.get("automation_scheduler").suggestion_gen.generate_suggestions()
    return jsonify({"success": True, "new_suggestions": count})



@automation_bp.route("/api/phases", methods=["GET"])
def api_get_phases():
    """Get learning phases for all room/domain combinations."""
    with get_db_session() as session:
        states = session.query(RoomDomainState).all()
        result = []
        for rds in states:
            room = session.get(Room, rds.room_id) if rds.room_id else None
            domain = session.get(Domain, rds.domain_id) if rds.domain_id else None
            result.append({
                "id": rds.id,
                "room_id": rds.room_id,
                "room_name": room.name if room else None,
                "domain_id": rds.domain_id,
                "domain_name": domain.name if domain else None,
                "learning_phase": rds.learning_phase.value if rds.learning_phase else "observing",
                "confidence_score": round(rds.confidence_score or 0, 3),
                "is_paused": rds.is_paused,
                "phase_started_at": rds.phase_started_at.isoformat() if rds.phase_started_at else None,
            })
        return jsonify(result)



@automation_bp.route("/api/phases/<int:room_id>/<int:domain_id>", methods=["PUT"])
def api_set_phase(room_id, domain_id):
    """Manually set learning phase for a room/domain."""
    data = request.json or {}
    if "phase" in data:
        result = _deps.get("automation_scheduler").phase_mgr.set_phase_manual(room_id, domain_id, data["phase"])
        return jsonify(result)
    if "is_paused" in data:
        result = _deps.get("automation_scheduler").phase_mgr.set_paused(room_id, domain_id, data["is_paused"])
        return jsonify(result)
    return jsonify({"error": "Provide 'phase' or 'is_paused'"}), 400



@automation_bp.route("/api/phases/<int:room_id>/<int:domain_id>/mode", methods=["PUT"])
def api_set_room_domain_mode(room_id, domain_id):
    """Set the mode override for a domain in a specific room."""
    data = request.json or {}
    mode = data.get("mode", "global")
    if mode not in ("global", "suggest", "auto", "off"):
        return jsonify({"error": "Invalid mode. Use: global, suggest, auto, off"}), 400

    with get_db_session() as session:
        ds = session.query(RoomDomainState).filter_by(room_id=room_id, domain_id=domain_id).first()
        if not ds:
            return jsonify({"error": "Room/Domain combination not found"}), 404
        ds.mode = mode
        session.commit()
        return jsonify({"room_id": room_id, "domain_id": domain_id, "mode": mode})



@automation_bp.route("/api/automation/anomalies", methods=["GET"])
def api_get_anomalies():
    """Get recent anomalies."""
    anomalies = _deps.get("automation_scheduler").anomaly_det.check_recent_anomalies(minutes=60)
    return jsonify(anomalies)



@automation_bp.route("/api/anomaly-settings", methods=["GET"])
def api_get_anomaly_settings():
    """Get anomaly detection settings."""
    with get_db_session() as session:
        settings = session.query(AnomalySetting).all()
        return jsonify([{
            "id": s.id, "room_id": s.room_id, "domain_id": s.domain_id,
            "device_id": s.device_id, "sensitivity": s.sensitivity,
            "stuck_detection": s.stuck_detection, "time_anomaly": s.time_anomaly,
            "frequency_anomaly": s.frequency_anomaly,
            "whitelisted_hours": s.whitelisted_hours,
            "auto_action": s.auto_action,
        } for s in settings])



@automation_bp.route("/api/anomaly-settings", methods=["POST"])
def api_create_anomaly_setting():
    """Create or update anomaly setting."""
    data = request.json
    with get_db_session() as session:
        try:
            setting = AnomalySetting(
                room_id=data.get("room_id"), domain_id=data.get("domain_id"),
                device_id=data.get("device_id"),
                sensitivity=data.get("sensitivity", "medium"),
                stuck_detection=data.get("stuck_detection", True),
                time_anomaly=data.get("time_anomaly", True),
                frequency_anomaly=data.get("frequency_anomaly", True),
                whitelisted_hours=data.get("whitelisted_hours"),
                auto_action=data.get("auto_action"),
            )
            session.add(setting)
            session.commit()
            return jsonify({"success": True, "id": setting.id}), 201
        except Exception as e:
            session.rollback()
            logger.error("Operation failed: %s", e)
            return jsonify({"error": "Operation failed"}), 500



@automation_bp.route("/api/phases/<int:room_id>/<int:domain_id>/progress", methods=["GET"])
def api_phase_progress(room_id, domain_id):
    """Get learning phase progress details."""
    with get_db_session() as session:
        rds = session.query(RoomDomainState).filter_by(room_id=room_id, domain_id=domain_id).first()
        if not rds:
            return jsonify({"error": "Not found"}), 404

        # Count events and patterns for this room+domain
        event_count = session.query(sa_func.count(StateHistory.id)).join(Device).filter(
            Device.room_id == room_id, Device.domain_id == domain_id
        ).scalar() or 0

        pattern_count = session.query(sa_func.count(LearnedPattern.id)).filter_by(
            room_id=room_id, domain_id=domain_id
        ).scalar() or 0

        active_patterns = session.query(sa_func.count(LearnedPattern.id)).filter_by(
            room_id=room_id, domain_id=domain_id, status="active"
        ).scalar() or 0

        # Progress calculation
        phase = rds.learning_phase.value if rds.learning_phase else "observing"
        if phase == "observing":
            needed = 100  # events needed
            progress = min(100, int(event_count / needed * 100))
            next_phase = "suggesting"
        elif phase == "suggesting":
            needed = 5  # confirmed patterns needed
            progress = min(100, int(active_patterns / needed * 100))
            next_phase = "autonomous"
        else:
            progress = 100
            next_phase = None

        speed = get_setting("learning_speed") or "normal"

        return jsonify({
            "phase": phase, "confidence": rds.confidence_score,
            "is_paused": rds.is_paused, "progress_percent": progress,
            "events_collected": event_count, "patterns_found": pattern_count,
            "patterns_active": active_patterns, "next_phase": next_phase,
            "learning_speed": speed,
        })



@automation_bp.route("/api/phases/speed", methods=["PUT"])
def api_set_learning_speed():
    """Set global learning speed."""
    data = request.json
    speed = data.get("speed", "normal")  # "conservative", "normal", "aggressive"
    set_setting("learning_speed", speed)
    return jsonify({"success": True, "speed": speed})



@automation_bp.route("/api/phases/<int:room_id>/<int:domain_id>/reset", methods=["POST"])
def api_reset_phase(room_id, domain_id):
    """Reset learning for a room+domain - delete patterns and restart."""
    with get_db_session() as session:
        try:
            # Reset phase
            rds = session.query(RoomDomainState).filter_by(room_id=room_id, domain_id=domain_id).first()
            if rds:
                rds.learning_phase = LearningPhase.OBSERVING
                rds.confidence_score = 0.0

            # Delete patterns for this room+domain
            session.query(LearnedPattern).filter_by(room_id=room_id, domain_id=domain_id).delete()
            session.commit()

            lang = get_language()
            return jsonify({"success": True,
                "message": "Lernphase zurückgesetzt" if lang == "de" else "Learning phase reset"})
        except Exception as e:
            session.rollback()
            logger.error("Operation failed: %s", e)
            return jsonify({"error": "Operation failed"}), 500



@automation_bp.route("/api/anomaly-settings/extended", methods=["GET"])
def api_get_extended_anomaly_settings():
    """Get full anomaly detection configuration."""
    return jsonify({
        # Empfindlichkeit
        "global_sensitivity": get_setting("anomaly_sensitivity") or "medium",
        "domain_sensitivity": json.loads(get_setting("anomaly_domain_sensitivity") or '{}'),
        "device_sensitivity": json.loads(get_setting("anomaly_device_sensitivity") or '{}'),
        # Erkennungs-Typen
        "detection_types": json.loads(get_setting("anomaly_detection_types") or '{"frequency": true, "time": true, "value": true, "offline": true, "stuck": true, "pattern_deviation": false}'),
        "frequency_threshold": json.loads(get_setting("anomaly_freq_threshold") or '{"count": 20, "window_min": 5}'),
        "value_deviation_pct": int(get_setting("anomaly_value_deviation") or "30"),
        "offline_timeout_min": int(get_setting("anomaly_offline_timeout") or "60"),
        "stuck_timeout_hours": int(get_setting("anomaly_stuck_timeout") or "12"),
        # Ausnahmen
        "device_whitelist": json.loads(get_setting("anomaly_device_whitelist") or '[]'),
        "domain_exceptions": json.loads(get_setting("anomaly_domain_exceptions") or '[]'),
        "time_exceptions": json.loads(get_setting("anomaly_time_exceptions") or '[]'),
        "paused_until": get_setting("anomaly_paused_until"),
        # Reaktionen
        "reactions": json.loads(get_setting("anomaly_reactions") or '{"low": "log", "medium": "push", "high": "push_tts", "critical": "push_tts_action"}'),
        "auto_actions": json.loads(get_setting("anomaly_auto_actions") or '{}'),
        "reaction_delay_min": int(get_setting("anomaly_reaction_delay") or "0"),
        # Lernphase
        "learning_mode": json.loads(get_setting("anomaly_learning_mode") or '{"enabled": false, "days_remaining": 0}'),
        "seasonal_adjustment": json.loads(get_setting("anomaly_seasonal") or '{"enabled": true}'),
        # Schwellwerte
        "battery_threshold": int(get_setting("anomaly_battery_threshold") or "20"),
        "temperature_limits": json.loads(get_setting("anomaly_temp_limits") or '{}'),
        "power_limits": json.loads(get_setting("anomaly_power_limits") or '{}'),
        "humidity_limits": json.loads(get_setting("anomaly_humidity_limits") or '{}'),
    })



@automation_bp.route("/api/anomaly-settings/extended", methods=["PUT"])
def api_update_extended_anomaly_settings():
    """Update extended anomaly settings."""
    data = request.json
    string_settings = ["global_sensitivity", "paused_until"]
    int_settings = ["value_deviation_pct", "offline_timeout_min", "stuck_timeout_hours", "reaction_delay_min", "battery_threshold"]
    json_settings = [
        "domain_sensitivity", "device_sensitivity", "detection_types",
        "frequency_threshold", "device_whitelist", "domain_exceptions",
        "time_exceptions", "reactions", "auto_actions", "learning_mode",
        "seasonal_adjustment", "temperature_limits", "power_limits",
        "humidity_limits",
    ]
    for key in string_settings:
        if key in data:
            set_setting(f"anomaly_{key}", str(data[key]) if data[key] else None)
    for key in int_settings:
        if key in data:
            set_setting(f"anomaly_{key}", str(int(data[key])))
    for key in json_settings:
        if key in data:
            set_setting(f"anomaly_{key}", json.dumps(data[key]))
    return jsonify({"success": True})



@automation_bp.route("/api/anomaly-settings/pause", methods=["POST"])
def api_pause_anomaly():
    """Temporarily pause anomaly detection."""
    data = request.json
    hours = data.get("hours", 1)
    until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    set_setting("anomaly_paused_until", until)
    return jsonify({"success": True, "paused_until": until})



@automation_bp.route("/api/anomaly-settings/reset-baseline", methods=["POST"])
def api_reset_anomaly_baseline():
    """Reset anomaly baseline - system re-learns what's normal."""
    set_setting("anomaly_learning_mode", json.dumps({"enabled": True, "days_remaining": 7, "started_at": datetime.now(timezone.utc).isoformat()}))
    return jsonify({"success": True, "message": "Baseline reset, learning for 7 days"})



@automation_bp.route("/api/anomaly-settings/stats", methods=["GET"])
def api_anomaly_stats():
    """Get anomaly statistics for dashboard."""
    with get_db_session() as session:
        cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
        logs = session.query(ActionLog).filter(
            ActionLog.action_type == "anomaly_detected",
            ActionLog.created_at >= cutoff_30d
        ).all()

        total = len(logs)
        by_device = {}
        by_type = {}
        by_week = {}
        for log in logs:
            ad = log.action_data or {}
            dev_name = ad.get("device_name", "Unknown")
            atype = ad.get("anomaly_type", "unknown")
            week = log.created_at.strftime("%Y-W%W") if log.created_at else "?"
            by_device[dev_name] = by_device.get(dev_name, 0) + 1
            by_type[atype] = by_type.get(atype, 0) + 1
            by_week[week] = by_week.get(week, 0) + 1

        top_devices = sorted(by_device.items(), key=lambda x: x[1], reverse=True)[:10]
        return jsonify({
            "total_30d": total,
            "by_type": by_type,
            "top_devices": [{"name": d[0], "count": d[1]} for d in top_devices],
            "trend": [{"week": w, "count": c} for w, c in sorted(by_week.items())],
        })



@automation_bp.route("/api/anomaly-settings/device/<int:device_id>", methods=["GET"])
def api_get_device_anomaly_config(device_id):
    """Get anomaly config for a specific device."""
    config = json.loads(get_setting(f"anomaly_device_{device_id}") or "null")
    if not config:
        config = {"sensitivity": "inherit", "enabled": True, "detection_types": {},
                  "thresholds": {}, "reaction": "inherit", "whitelisted": False}
    return jsonify(config)



@automation_bp.route("/api/anomaly-settings/device/<int:device_id>", methods=["PUT"])
def api_update_device_anomaly_config(device_id):
    """Update anomaly config for a specific device."""
    data = request.json
    current = json.loads(get_setting(f"anomaly_device_{device_id}") or "{}")
    current.update(data)
    set_setting(f"anomaly_device_{device_id}", json.dumps(current))
    return jsonify({"success": True})



@automation_bp.route("/api/anomaly-settings/devices", methods=["GET"])
def api_get_all_device_anomaly_configs():
    """Get all device-specific anomaly configs."""
    with get_db_session() as session:
        configs = {}
        settings = session.query(SystemSetting).filter(
            SystemSetting.key.like("anomaly_device_%")
        ).all()
        for s in settings:
            device_id = s.key.replace("anomaly_device_", "")
            try:
                configs[device_id] = json.loads(s.value)
            except Exception:
                pass
        return jsonify(configs)

