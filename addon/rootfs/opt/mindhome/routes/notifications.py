# MindHome - routes/notifications.py | see version.py for version info
"""
MindHome API Routes - Notifications
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
    PersonSchedule, ShiftTemplate, Holiday,
)

logger = logging.getLogger("mindhome.routes.notifications")

notifications_bp = Blueprint("notifications", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_notifications(dependencies):
    """Initialize notifications routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@notifications_bp.route("/api/notifications", methods=["GET"])
def api_get_notifications():
    """Get notifications with pagination."""
    lang = get_language()
    unread = request.args.get("unread", "false").lower() == "true"
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    session = get_db()
    try:
        query = session.query(NotificationLog).order_by(NotificationLog.created_at.desc())
        if unread:
            query = query.filter_by(was_read=False)
        total = query.count()
        notifs = query.offset(offset).limit(limit).all()
        return jsonify({
            "items": [{
                "id": n.id,
                "type": n.notification_type.value if n.notification_type else "info",
                "title": n.title,
                "message": n.message,
                "was_sent": n.was_sent,
                "was_read": n.was_read,
                "created_at": utc_iso(n.created_at),
            } for n in notifs],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total
        })
    finally:
        session.close()



@notifications_bp.route("/api/notifications/unread-count", methods=["GET"])
def api_notifications_unread_count():
    """Get unread notification count."""
    count = _deps.get("automation_scheduler").notification_mgr.get_unread_count()
    return jsonify({"unread_count": count})



@notifications_bp.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
def api_mark_notification_read(notif_id):
    """Mark notification as read."""
    success = _deps.get("automation_scheduler").notification_mgr.mark_read(notif_id)
    return jsonify({"success": success})



@notifications_bp.route("/api/notifications/mark-all-read", methods=["POST"])
def api_mark_all_read():
    """Mark all notifications as read."""
    success = _deps.get("automation_scheduler").notification_mgr.mark_all_read()
    return jsonify({"success": success})



@notifications_bp.route("/api/notification-settings", methods=["GET"])
def api_get_notification_settings():
    """Get all notification settings for current user."""
    session = get_db()
    try:
        settings = session.query(NotificationSetting).filter_by(user_id=1).all()
        channels = session.query(NotificationChannel).all()
        mutes = session.query(DeviceMute).filter_by(user_id=1).all()
        dnd = get_setting("dnd_enabled") == "true"
        return jsonify({
            "settings": [{
                "id": s.id, "type": s.notification_type.value,
                "is_enabled": s.is_enabled,
                "priority": s.priority.value if s.priority else "medium",
                "quiet_hours_start": s.quiet_hours_start,
                "quiet_hours_end": s.quiet_hours_end,
                "push_channel": s.push_channel,
                "escalation_enabled": s.escalation_enabled,
                "escalation_minutes": s.escalation_minutes,
                "geofencing_only_away": s.geofencing_only_away,
            } for s in settings],
            "channels": [{
                "id": c.id, "service_name": c.service_name,
                "display_name": c.display_name, "channel_type": c.channel_type,
                "is_enabled": c.is_enabled,
            } for c in channels],
            "muted_devices": [{
                "id": m.id, "device_id": m.device_id, "reason": m.reason,
                "muted_until": m.muted_until.isoformat() if m.muted_until else None,
            } for m in mutes],
            "dnd_enabled": dnd,
        })
    finally:
        session.close()



@notifications_bp.route("/api/notification-settings", methods=["PUT"])
def api_update_notification_settings():
    """Update notification settings."""
    data = request.json or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400
    session = get_db()
    try:
        ntype = data.get("type")
        existing = session.query(NotificationSetting).filter_by(
            user_id=1, notification_type=NotificationType(ntype)
        ).first()
        if not existing:
            existing = NotificationSetting(user_id=1, notification_type=NotificationType(ntype))
            session.add(existing)
        for key in ["is_enabled", "quiet_hours_start", "quiet_hours_end",
                     "push_channel", "escalation_enabled", "escalation_minutes",
                     "geofencing_only_away"]:
            if key in data:
                setattr(existing, key, data[key])
        if "priority" in data:
            existing.priority = NotificationPriority(data["priority"])
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500
    finally:
        session.close()



@notifications_bp.route("/api/notification-settings/dnd", methods=["PUT"])
def api_toggle_dnd():
    """Toggle Do-Not-Disturb mode."""
    data = request.json or {}
    set_setting("dnd_enabled", "true" if data.get("enabled") else "false")
    return jsonify({"success": True, "dnd_enabled": data.get("enabled", False)})



@notifications_bp.route("/api/notification-settings/mute-device", methods=["POST"])
def api_mute_device():
    """Mute notifications for a specific device."""
    data = request.json or {}
    if "device_id" not in data:
        return jsonify({"error": "device_id required"}), 400
    session = get_db()
    try:
        mute = DeviceMute(
            device_id=data["device_id"], user_id=1,
            reason=data.get("reason"), muted_until=None
        )
        session.add(mute)
        session.commit()
        return jsonify({"success": True, "id": mute.id})
    except Exception as e:
        session.rollback()
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500
    finally:
        session.close()



@notifications_bp.route("/api/notification-settings/unmute-device/<int:mute_id>", methods=["DELETE"])
def api_unmute_device(mute_id):
    """Unmute a device."""
    session = get_db()
    try:
        mute = session.get(DeviceMute, mute_id)
        if mute:
            session.delete(mute)
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@notifications_bp.route("/api/notification-settings/discover-channels", methods=["POST"])
def api_discover_notification_channels():
    """Discover available HA notification services."""
    session = get_db()
    try:
        services = _ha().get_services()
        found = 0
        for svc in services:
            if svc.get("domain") == "notify":
                for name in svc.get("services", {}).keys():
                    svc_name = f"notify.{name}"
                    existing = session.query(NotificationChannel).filter_by(service_name=svc_name).first()
                    if not existing:
                        ch_type = "push" if "mobile" in name else "persistent" if "persistent" in name else "other"
                        channel = NotificationChannel(
                            service_name=svc_name,
                            display_name=name.replace("_", " ").title(),
                            channel_type=ch_type
                        )
                        session.add(channel)
                        found += 1
        session.commit()
        return jsonify({"success": True, "found": found})
    except Exception as e:
        session.rollback()
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500
    finally:
        session.close()



@notifications_bp.route("/api/notification-stats", methods=["GET"])
def api_notification_stats():
    """Get notification statistics for current month."""
    session = get_db()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        total = session.query(sa_func.count(NotificationLog.id)).filter(
            NotificationLog.created_at >= cutoff
        ).scalar() or 0
        read = session.query(sa_func.count(NotificationLog.id)).filter(
            NotificationLog.created_at >= cutoff, NotificationLog.was_read == True
        ).scalar() or 0
        sent = session.query(sa_func.count(NotificationLog.id)).filter(
            NotificationLog.created_at >= cutoff, NotificationLog.was_sent == True
        ).scalar() or 0
        return jsonify({"total": total, "read": read, "unread": total - read, "sent": sent, "pushed": sent, "period_days": 30})
    finally:
        session.close()



@notifications_bp.route("/api/test-notification", methods=["POST"])
def api_test_notification():
    """Send a test push notification to a specific channel."""
    data = request.get_json() or {}
    target = data.get("target", "notify")
    message = data.get("message", "MindHome Test Notification")
    title = data.get("title", "MindHome Test")
    result = _ha().send_notification(message, title=title, target=target)
    audit_log("test_notification", {"target": target})
    return jsonify({"success": result is not None, "target": target})



@notifications_bp.route("/api/notification-settings/test-channel/<int:channel_id>", methods=["POST"])
def api_test_channel(channel_id):
    """Send a test notification via a specific channel."""
    session = get_db()
    try:
        channel = session.get(NotificationChannel, channel_id)
        if not channel:
            return jsonify({"error": "Channel not found"}), 404
        result = _ha().send_notification(
            "MindHome Test Notification",
            title="MindHome Test",
            target=channel.service_name
        )
        return jsonify({"success": result is not None, "channel": channel.service_name})
    finally:
        session.close()



@notifications_bp.route("/api/notification-settings/channel/<int:channel_id>", methods=["PUT"])
def api_update_channel(channel_id):
    """Update a notification channel (enable/disable)."""
    data = request.json or {}
    session = get_db()
    try:
        channel = session.get(NotificationChannel, channel_id)
        if not channel:
            return jsonify({"error": "Channel not found"}), 404
        if "is_enabled" in data:
            channel.is_enabled = data["is_enabled"]
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@notifications_bp.route("/api/notification-settings/extended", methods=["GET"])
def api_get_extended_notification_settings():
    """Get full extended notification configuration (18 features)."""
    return jsonify({
        # Zeitsteuerung
        "quiet_hours": json.loads(get_setting("notif_quiet_hours") or '{"enabled": true, "start": "22:00", "end": "07:00", "weekday_only": false, "weekend_start": "23:00", "weekend_end": "09:00", "extra_windows": []}'),
        "weekday_rules": json.loads(get_setting("notif_weekday_rules") or '{"enabled": false, "rules": {}}'),
        "vacation_coupling": json.loads(get_setting("notif_vacation_coupling") or '{"enabled": false, "only_critical": true}'),
        # Eskalation
        "escalation": json.loads(get_setting("notif_escalation") or '{"enabled": false, "chain": [{"type": "push", "delay_min": 0}, {"type": "tts", "delay_min": 5}]}'),
        "repeat_rules": json.loads(get_setting("notif_repeat_rules") or '{"enabled": false, "repeat_after_min": 10, "max_repeats": 3}'),
        "confirmation_required": json.loads(get_setting("notif_confirmation") or '{"enabled": false, "types": ["critical"]}'),
        "fallback_channels": json.loads(get_setting("notif_fallback") or '{"enabled": false, "chain": ["push", "tts", "persistent"]}'),
        # Routing
        "type_channels": json.loads(get_setting("notif_type_channels") or '{}'),
        "person_channels": json.loads(get_setting("notif_person_channels") or '{}'),
        # Darstellung
        "type_sounds": json.loads(get_setting("notif_type_sounds") or '{"anomaly": true, "suggestion": false, "critical": true, "info": false}'),
        "templates": json.loads(get_setting("notif_templates") or '{}'),
        # Spam-Schutz
        "grouping": json.loads(get_setting("notif_grouping") or '{"enabled": true, "window_min": 5}'),
        "rate_limits": json.loads(get_setting("notif_rate_limits") or '{"anomaly": 10, "suggestion": 5, "critical": 0, "info": 20}'),
        # Sicherheit
        "critical_override": json.loads(get_setting("notif_critical_override") or '{"enabled": true}'),
        # Debug
        "test_mode": json.loads(get_setting("notif_test_mode") or '{"enabled": false, "until": null}'),
        # Zusammenfassung
        "digest": json.loads(get_setting("notif_digest") or '{"enabled": false, "frequency": "daily", "time": "08:00"}'),
        # Spezial
        "battery_threshold": int(get_setting("notif_battery_threshold") or "20"),
        "device_thresholds": json.loads(get_setting("notif_device_thresholds") or '{}'),
        # TTS
        "tts_room_assignments": json.loads(get_setting("notif_tts_room_assignments") or '{}'),
        "tts_enabled": json.loads(get_setting("notif_tts_enabled") or 'true'),
        "tts_motion_mode": json.loads(get_setting("notif_tts_motion_mode") or '{"enabled": false, "fallback_all": false, "timeout_min": 30}'),
        "tts_disabled_speakers": json.loads(get_setting("notif_tts_disabled_speakers") or '[]'),
    })



@notifications_bp.route("/api/notification-settings/extended", methods=["PUT"])
def api_update_extended_notification_settings():
    """Update extended notification settings."""
    data = request.json
    setting_keys = [
        "quiet_hours", "weekday_rules", "vacation_coupling",
        "escalation", "repeat_rules", "confirmation_required", "fallback_channels",
        "type_channels", "person_channels",
        "type_sounds", "templates",
        "grouping", "rate_limits",
        "critical_override", "test_mode", "digest",
        "device_thresholds", "tts_room_assignments",
        "tts_enabled", "tts_motion_mode", "tts_disabled_speakers",
    ]
    for key in setting_keys:
        if key in data:
            set_setting(f"notif_{key}", json.dumps(data[key]))
    if "battery_threshold" in data:
        set_setting("notif_battery_threshold", str(data["battery_threshold"]))
    return jsonify({"success": True})



@notifications_bp.route("/api/notification-settings/scan-channels", methods=["POST"])
def api_scan_notification_channels():
    """Auto-detect available notification services from HA."""
    session = get_db()
    try:
        services = _ha().get_services() or {}
        channels = []
        # get_services() may return list or dict depending on HA version
        if isinstance(services, list):
            svc_dict = {}
            for svc in services:
                if isinstance(svc, dict):
                    domain = svc.get("domain", "")
                    svc_dict[domain] = list(svc.get("services", {}).keys()) if isinstance(svc.get("services"), dict) else []
            services = svc_dict
        for svc_domain, svc_list in services.items():
            if "notify" in svc_domain or svc_domain == "notify":
                for svc_name in svc_list:
                    full_name = f"{svc_domain}.{svc_name}" if svc_domain != "notify" else f"notify.{svc_name}"
                    existing = session.query(NotificationChannel).filter_by(service_name=full_name).first()
                    if not existing:
                        ch = NotificationChannel(service_name=full_name, display_name=svc_name.replace("_", " ").title(), channel_type="push", is_enabled=True)
                        session.add(ch)
                        channels.append(full_name)
        session.commit()
        return jsonify({"success": True, "found": len(channels), "channels": channels})
    except Exception as e:
        session.rollback()
        logger.error("Operation failed: %s", e)
        return jsonify({"success": False, "error": "Operation failed", "found": 0, "channels": []}), 500
    finally:
        session.close()

