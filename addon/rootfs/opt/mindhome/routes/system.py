# MindHome - routes/system.py | see version.py for version info
"""
MindHome API Routes - System
Auto-extracted from monolithic app.py during Phase 3.5 refactoring.
"""

import os
import sys
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
from flask import Blueprint, request, jsonify, Response, make_response, send_from_directory, redirect, current_app
from sqlalchemy import func as sa_func, text

from version import VERSION
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

logger = logging.getLogger("mindhome.routes.system")

system_bp = Blueprint("system", __name__)

INGRESS_PATH = os.environ.get("INGRESS_PATH", "")

# Module-level dependencies (set by init function)
_deps = {}


def init_system(dependencies):
    """Initialize system routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")






@system_bp.route("/api/system/status", methods=["GET"])
def api_system_status():
    """Get system status overview."""
    session = get_db()
    try:
        tz = get_ha_timezone()
        tz_name = str(tz) if tz != timezone.utc else "UTC"
        return jsonify({
            "status": "running",
            "ha_connected": _ha().is_connected(),
            "offline_queue_size": _ha().get_offline_queue_size(),
            "system_mode": get_setting("system_mode", "normal"),
            "onboarding_completed": get_setting("onboarding_completed", "false") == "true",
            "language": get_language(),
            "theme": get_setting("theme", "dark"),
            "view_mode": get_setting("view_mode", "simple"),
            "version": VERSION,
            "timezone": tz_name,
            "local_time": local_now().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    finally:
        session.close()



@system_bp.route("/api/health", methods=["GET"])
def api_health_check():
    """Health check endpoint - HA Add-on compatible."""
    health = {"status": "healthy", "checks": {}}

    # DB check
    try:
        session = get_db()
        session.execute(text("SELECT 1"))
        session.close()
        health["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        health["checks"]["database"] = {"status": "error", "message": str(e)[:100]}
        health["status"] = "unhealthy"

    # HA connection
    health["checks"]["ha_websocket"] = {
        "status": "ok" if _ha()._ws_connected else "disconnected",
        "reconnect_attempts": _ha()._reconnect_attempts,
    }
    health["checks"]["ha_rest_api"] = {
        "status": "ok" if _ha()._is_online else "offline"
    }

    # #41 Connection stats
    health["checks"]["connection_stats"] = _ha().get_connection_stats()

    # #24 Device health summary
    try:
        device_issues = _ha().check_device_health()
        health["checks"]["devices"] = {
            "status": "warning" if device_issues else "ok",
            "issues_count": len(device_issues),
        }
    except Exception:
        health["checks"]["devices"] = {"status": "unknown"}

    # Memory usage
    try:
        import resource
        mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        health["memory_kb"] = mem
    except Exception:
        pass

    health["uptime_seconds"] = int(time.time() - _deps.get("start_time", 0)) if _deps.get("start_time", 0) else 0
    health["version"] = VERSION
    health["debug_mode"] = is_debug_mode()

    status_code = 200 if health["status"] == "healthy" else 503
    return jsonify(health), status_code



@system_bp.route("/api/system/info", methods=["GET"])
def api_system_info():
    """Get detailed system information."""
    session = get_db()
    try:
        device_count = session.query(Device).count()
        room_count = session.query(Room).filter_by(is_active=True).count()
        user_count = session.query(User).filter_by(is_active=True).count()
        domain_count = session.query(Domain).filter_by(is_enabled=True).count()
        log_count = session.query(ActionLog).count()
        observation_count = session.query(ActionLog).filter_by(action_type="observation").count()

        # DB size
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")
        db_size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        # Retention setting
        retention_days = int(get_setting("data_retention_days", "90"))

        return jsonify({
            "version": VERSION,
            "phase": "3.5 (stabilization)",
            "ha_connected": _ha().is_connected(),
            "ws_connected": _ha()._ws_connected,
            "ha_entity_count": len(_ha().get_states() or []),
            "timezone": str(get_ha_timezone()),
            "local_time": local_now().isoformat(),
            "uptime_seconds": int(time.time() - _deps.get("start_time", 0)) if _deps.get("start_time", 0) else 0,
            "device_count": device_count,
            "room_count": room_count,
            "user_count": user_count,
            "active_domains": domain_count,
            "total_log_entries": log_count,
            "total_observations": observation_count,
            "db_size_bytes": db_size_bytes,
            "db_size_mb": round(db_size_bytes / 1024 / 1024, 2),
            "data_retention_days": retention_days,
            "python_version": sys.version.split()[0],
            "ingress_path": INGRESS_PATH,
            # Phase 2a additions
            "state_history_count": session.query(StateHistory).count(),
            "pattern_count": session.query(LearnedPattern).filter_by(is_active=True).count(),
            "event_bus_subscribers": _deps.get("event_bus").subscriber_count("state_changed"),
        })
    finally:
        session.close()



@system_bp.route("/api/system/settings", methods=["GET"])
def api_get_settings():
    """Get all system settings."""
    session = get_db()
    try:
        settings = session.query(SystemSetting).all()
        return jsonify([{
            "key": s.key,
            "value": s.value,
            "description": s.description_de if get_language() == "de" else s.description_en
        } for s in settings])
    finally:
        session.close()



@system_bp.route("/api/system/settings/<key>", methods=["PUT"])
def api_update_setting(key):
    """Update a system setting."""
    data = request.json
    set_setting(key, data.get("value"))
    return jsonify({"success": True, "key": key, "value": data.get("value")})



@system_bp.route("/api/system/emergency-stop", methods=["POST"])
def api_emergency_stop():
    """Activate emergency stop - pause all automations."""
    set_setting("system_mode", "emergency_stop")

    session = get_db()
    try:
        states = session.query(RoomDomainState).all()
        for state in states:
            state.is_paused = True
        session.commit()

        logger.warning("EMERGENCY STOP ACTIVATED - All automations paused")
        return jsonify({"success": True, "mode": "emergency_stop"})
    finally:
        session.close()



@system_bp.route("/api/system/resume", methods=["POST"])
def api_resume():
    """Resume from emergency stop."""
    set_setting("system_mode", "normal")

    session = get_db()
    try:
        states = session.query(RoomDomainState).all()
        for state in states:
            state.is_paused = False
        session.commit()

        logger.info("System resumed from emergency stop")
        return jsonify({"success": True, "mode": "normal"})
    finally:
        session.close()



@system_bp.route("/api/ha/persons", methods=["GET"])
def api_ha_persons():
    """Get all person entities from HA for user assignment."""
    states = _ha().get_states() or []
    persons = []
    for s in states:
        eid = s.get("entity_id", "")
        if eid.startswith("person."):
            persons.append({
                "entity_id": eid,
                "name": s.get("attributes", {}).get("friendly_name", eid),
                "state": s.get("state", "unknown")
            })
    return jsonify({"persons": persons})



@system_bp.route("/api/quick-actions", methods=["GET"])
def api_get_quick_actions():
    """Get all quick actions."""
    session = get_db()
    try:
        actions = session.query(QuickAction).filter_by(is_active=True).order_by(
            QuickAction.sort_order
        ).all()
        lang = get_language()
        return jsonify([{
            "id": a.id,
            "name": a.name_de if lang == "de" else a.name_en,
            "icon": a.icon,
            "action_data": a.action_data,
            "is_system": a.is_system
        } for a in actions])
    finally:
        session.close()



@system_bp.route("/api/quick-actions/execute/<int:action_id>", methods=["POST"])
def api_execute_quick_action(action_id):
    """Execute a quick action."""
    session = get_db()
    try:
        action = session.get(QuickAction, action_id)
        if not action:
            return jsonify({"error": "Quick action not found"}), 404

        action_type = action.action_data.get("type")

        if action_type == "all_off":
            for entity in _ha().get_entities_by_domain("light"):
                _ha().call_service("light", "turn_off", entity_id=entity["entity_id"])
            for entity in _ha().get_entities_by_domain("switch"):
                _ha().call_service("switch", "turn_off", entity_id=entity["entity_id"])
            for entity in _ha().get_entities_by_domain("media_player"):
                _ha().call_service("media_player", "turn_off", entity_id=entity["entity_id"])

        elif action_type == "leaving_home":
            set_setting("system_mode", "away")
            for entity in _ha().get_entities_by_domain("light"):
                _ha().call_service("light", "turn_off", entity_id=entity["entity_id"])
            for entity in _ha().get_entities_by_domain("climate"):
                _ha().call_service("climate", "set_temperature",
                              {"temperature": 18}, entity_id=entity["entity_id"])

        elif action_type == "arriving_home":
            set_setting("system_mode", "normal")

        elif action_type == "guest_mode_on":
            set_setting("system_mode", "guest")

        elif action_type == "emergency_stop":
            set_setting("system_mode", "emergency_stop")
            states = session.query(RoomDomainState).all()
            for state in states:
                state.is_paused = True
            session.commit()

        log = ActionLog(
            action_type="quick_action",
            action_data={"quick_action_id": action_id, "type": action_type},
            reason=f"Quick Action: {action.name_de}"
        )
        session.add(log)
        session.commit()

        return jsonify({"success": True, "action_type": action_type})
    finally:
        session.close()



@system_bp.route("/api/quick-actions", methods=["POST"])
def api_create_quick_action():
    """Create a new custom quick action."""
    data = request.json
    session = get_db()
    try:
        max_order = session.query(sa_func.max(QuickAction.sort_order)).scalar() or 0
        qa = QuickAction(
            name_de=data.get("name", ""),
            name_en=data.get("name_en", data.get("name", "")),
            icon=data.get("icon", "mdi:flash"),
            action_data=data.get("action_data") or {"type": "custom", "entities": []},
            sort_order=max_order + 1,
            is_active=True,
            is_system=False
        )
        session.add(qa)
        session.commit()
        return jsonify({"success": True, "id": qa.id}), 201
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@system_bp.route("/api/quick-actions/<int:action_id>", methods=["PUT"])
def api_update_quick_action(action_id):
    """Update a quick action."""
    data = request.json
    session = get_db()
    try:
        qa = session.get(QuickAction, action_id)
        if not qa:
            return jsonify({"error": "Not found"}), 404
        if data.get("name"):
            qa.name_de = data["name"]
        if data.get("name_en"):
            qa.name_en = data["name_en"]
        else:
            if data.get("name"):
                qa.name_en = data["name"]
        if data.get("icon"):
            qa.icon = data["icon"]
        if data.get("action_data"):
            qa.action_data = data["action_data"]
        if "is_active" in data:
            qa.is_active = data["is_active"]
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@system_bp.route("/api/quick-actions/<int:action_id>", methods=["DELETE"])
def api_delete_quick_action(action_id):
    """Delete a quick action (only non-system)."""
    session = get_db()
    try:
        qa = session.get(QuickAction, action_id)
        if not qa:
            return jsonify({"error": "Not found"}), 404
        if qa.is_system:
            return jsonify({"error": "Cannot delete system actions"}), 403
        session.delete(qa)
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@system_bp.route("/api/data-dashboard", methods=["GET"])
def api_data_dashboard():
    """Get overview of all collected data for transparency."""
    session = get_db()
    try:
        collections = session.query(DataCollection).all()
        return jsonify([{
            "room_id": dc.room_id,
            "domain_id": dc.domain_id,
            "data_type": dc.data_type,
            "record_count": dc.record_count,
            "first_record": dc.first_record_at.isoformat() if dc.first_record_at else None,
            "last_record": dc.last_record_at.isoformat() if dc.last_record_at else None,
            "storage_size_bytes": dc.storage_size_bytes
        } for dc in collections])
    finally:
        session.close()



@system_bp.route("/api/data-dashboard/delete/<int:collection_id>", methods=["DELETE"])
def api_delete_collected_data(collection_id):
    """Delete specific collected data."""
    session = get_db()
    try:
        dc = session.get(DataCollection, collection_id)
        if not dc:
            return jsonify({"error": "Not found"}), 404
        session.delete(dc)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@system_bp.route("/api/system/translations/<lang_code>", methods=["GET"])
def api_get_translations(lang_code):
    """Get translations for a language."""
    # Whitelist language codes to prevent path traversal
    if lang_code not in ("de", "en"):
        return jsonify({"error": "Language not found"}), 404
    import json as json_lib
    lang_file = os.path.join(os.path.dirname(__file__), "translations", f"{lang_code}.json")
    try:
        with open(lang_file, "r", encoding="utf-8") as f:
            return jsonify(json_lib.load(f))
    except FileNotFoundError:
        return jsonify({"error": "Language not found"}), 404



@system_bp.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Get onboarding status."""
    return jsonify({
        "completed": get_setting("onboarding_completed", "false") == "true"
    })



@system_bp.route("/api/onboarding/complete", methods=["POST"])
def api_onboarding_complete():
    """Mark onboarding as complete."""
    set_setting("onboarding_completed", "true")
    return jsonify({"success": True})



@system_bp.route("/api/action-log", methods=["GET"])
def api_get_action_log():
    """Get action log with time filters and pagination."""
    session = get_db()
    try:
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        action_type = request.args.get("type")

        # Fix 2: Time period filter
        period = request.args.get("period", "all")
        now = datetime.now(timezone.utc)

        query = session.query(ActionLog).order_by(ActionLog.created_at.desc())

        if action_type:
            query = query.filter_by(action_type=action_type)

        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(ActionLog.created_at >= start)
        elif period == "week" or period == "7d":
            start = now - timedelta(days=7)
            query = query.filter(ActionLog.created_at >= start)
        elif period == "month" or period == "30d":
            start = now - timedelta(days=30)
            query = query.filter(ActionLog.created_at >= start)
        # "all" = no date filter

        total = query.count()
        logs = query.offset(offset).limit(limit).all()

        return jsonify({
            "items": [{
                "id": log.id,
                "action_type": log.action_type,
                "domain_id": log.domain_id,
                "room_id": log.room_id,
                "device_id": log.device_id,
                "action_data": log.action_data,
                "reason": log.reason,
                "was_undone": log.was_undone,
                "created_at": utc_iso(log.created_at)
            } for log in logs],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total
        })
    finally:
        session.close()



@system_bp.route("/api/action-log/<int:log_id>/undo", methods=["POST"])
def api_undo_action(log_id):
    """Undo a specific action."""
    session = get_db()
    try:
        log = session.get(ActionLog, log_id)
        if not log:
            return jsonify({"error": "Action not found"}), 404
        if log.was_undone:
            return jsonify({"error": "Action already undone"}), 400
        if not log.previous_state:
            return jsonify({"error": "No previous state available"}), 400

        prev = log.previous_state
        if "entity_id" in prev and "state" in prev:
            domain = prev["entity_id"].split(".")[0]
            if prev["state"] == "on":
                _ha().call_service(domain, "turn_on", entity_id=prev["entity_id"])
            elif prev["state"] == "off":
                _ha().call_service(domain, "turn_off", entity_id=prev["entity_id"])

        log.was_undone = True
        session.commit()

        return jsonify({"success": True})
    finally:
        session.close()



@system_bp.route("/api/data-collections", methods=["GET"])
def api_get_data_collections():
    """Get recent tracked data (observations from ActionLog) with time filter."""
    session = get_db()
    try:
        limit = request.args.get("limit", 200, type=int)

        # Fix 2: Time period filter
        period = request.args.get("period", "all")
        now = datetime.now(timezone.utc)

        query = session.query(ActionLog).filter_by(
            action_type="observation"
        ).order_by(ActionLog.created_at.desc())

        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(ActionLog.created_at >= start)
        elif period == "week":
            start = now - timedelta(days=7)
            query = query.filter(ActionLog.created_at >= start)
        elif period == "month":
            start = now - timedelta(days=30)
            query = query.filter(ActionLog.created_at >= start)

        logs = query.limit(limit).all()
        return jsonify([{
            "id": log.id,
            "domain_id": log.domain_id,
            "device_id": log.device_id,
            "data_type": "state_change",
            "data_value": log.action_data or {},
            "collected_at": utc_iso(log.created_at)
        } for log in logs])
    finally:
        session.close()



@system_bp.route("/api/system/retention", methods=["GET"])
def api_get_retention():
    """Get data retention settings."""
    days = int(get_setting("data_retention_days", "90"))
    session = get_db()
    try:
        total = session.query(ActionLog).count()
        observations = session.query(ActionLog).filter_by(action_type="observation").count()
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        return jsonify({
            "retention_days": days,
            "total_entries": total,
            "observation_entries": observations,
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / 1024 / 1024, 2)
        })
    finally:
        session.close()



@system_bp.route("/api/system/retention", methods=["PUT"])
def api_set_retention():
    """Update data retention settings."""
    data = request.json
    days = data.get("retention_days", 90)
    if days < 7:
        days = 7  # Minimum 7 days
    if days > 365:
        days = 365
    set_setting("data_retention_days", str(days))
    return jsonify({"success": True, "retention_days": days})



@system_bp.route("/api/system/cleanup", methods=["POST"])
def api_manual_cleanup():
    """Manually trigger data cleanup."""
    deleted = run_cleanup()
    return jsonify({"success": True, "deleted_entries": deleted})



@system_bp.route("/")
def serve_index():
    """Serve index.html with app.jsx inlined to avoid Ingress XHR issues."""
    frontend_dir = os.path.join(current_app.static_folder, "frontend")
    index_path = os.path.join(frontend_dir, "index.html")
    jsx_path = os.path.join(frontend_dir, "app.jsx")

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        with open(jsx_path, "r", encoding="utf-8") as f:
            jsx_code = f.read()

        logger.info(f"Serving frontend: app.jsx has {len(jsx_code.splitlines())} lines, first line: {jsx_code.splitlines()[0][:60] if jsx_code else 'EMPTY'}")

        # Ensure UTF-8 meta charset exists
        if '<meta charset' not in html.lower():
            html = html.replace('<head>', '<head>\n    <meta charset="utf-8">', 1)

        # Inject app.jsx as a hidden text/plain script that our manual Babel code reads
        jsx_block = '<script type="text/plain" id="app-jsx-source">\n' + jsx_code + '\n</script>'

        # Must insert BEFORE the script that calls Babel.transform
        # Replace the opening <script> + marker with: jsx_block + new <script> + marker
        open_marker = "<script>\n        logStep('App wird kompiliert...');"
        if open_marker in html:
            html = html.replace(
                open_marker,
                jsx_block + "\n    <script>\n        logStep('App wird kompiliert...');"
            )
        else:
            # Fallback: insert before </body>
            html = html.replace('</body>', jsx_block + '\n</body>')

        return html, 200, {"Content-Type": "text/html; charset=utf-8"}
    except FileNotFoundError as e:
        logger.error(f"Frontend file not found: {e}")
        return f"<h1>Frontend Error</h1><p>File not found: {e}</p>", 500


@system_bp.route("/api/system/hot-update", methods=["POST"])
def hot_update_frontend():
    """Hot-update frontend file (app.jsx) without rebuild. Only available in debug mode."""
    if get_setting("debug_mode") != "true":
        return jsonify({"error": "Hot-update only available in debug mode"}), 403
    data = request.json
    if not data or "content" not in data or "filename" not in data:
        return jsonify({"error": "need content and filename"}), 400
    filename = data["filename"]
    if filename not in ("app.jsx", "index.html"):
        return jsonify({"error": "only app.jsx and index.html allowed"}), 400
    filepath = os.path.join(current_app.static_folder, "frontend", filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(data["content"])
        logger.info(f"Hot-updated {filename} ({len(data['content'])} chars)")
        return jsonify({"success": True, "size": len(data["content"])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@system_bp.route("/<path:path>")
def serve_frontend(path):
    """Serve the React frontend files."""
    # Skip API routes
    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    # Strip frontend/ prefix if present (to avoid double-nesting)
    if path.startswith("frontend/"):
        path = path[len("frontend/"):]
    if path and os.path.exists(os.path.join(current_app.static_folder, "frontend", path)):
        response = send_from_directory(os.path.join(current_app.static_folder, "frontend"), path)
        # Fix MIME type for .jsx files (Babel XHR needs text/javascript)
        if path.endswith(".jsx"):
            response.headers["Content-Type"] = "text/javascript; charset=utf-8"
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    return send_from_directory(os.path.join(current_app.static_folder, "frontend"), "index.html")



@system_bp.route("/api/validate-config", methods=["GET"])
def api_validate_config():
    """Validate MindHome configuration - find issues."""
    session = get_db()
    try:
        issues = []
        # Devices without room
        orphan_devices = session.query(Device).filter(Device.room_id == None, Device.is_tracked == True).count()
        if orphan_devices > 0:
            issues.append({"type": "warning", "key": "orphan_devices",
                "message_de": f"{orphan_devices} überwachte Geräte ohne Raum-Zuweisung",
                "message_en": f"{orphan_devices} tracked devices without room assignment"})

        # Rooms without devices
        for room in session.query(Room).filter_by(is_active=True).all():
            dev_count = session.query(Device).filter_by(room_id=room.id).count()
            if dev_count == 0:
                issues.append({"type": "info", "key": "empty_room",
                    "message_de": f"Raum '{room.name}' hat keine Geräte",
                    "message_en": f"Room '{room.name}' has no devices"})

        # Domains enabled but no devices
        for domain in session.query(Domain).filter_by(is_enabled=True).all():
            dev_count = session.query(Device).filter_by(domain_id=domain.id, is_tracked=True).count()
            if dev_count == 0:
                issues.append({"type": "info", "key": "empty_domain",
                    "message_de": f"Domain '{domain.display_name_de}' aktiv aber keine Geräte zugewiesen",
                    "message_en": f"Domain '{domain.display_name_en}' active but no devices assigned"})

        # HA connection
        if not _ha().connected:
            issues.append({"type": "error", "key": "ha_disconnected",
                "message_de": "Home Assistant nicht verbunden",
                "message_en": "Home Assistant not connected"})

        return jsonify({"valid": len([i for i in issues if i["type"] == "error"]) == 0, "issues": issues})
    finally:
        session.close()



@system_bp.route("/api/report/weekly", methods=["GET"])
def api_weekly_report():
    """Generate a weekly summary report."""
    session = get_db()
    try:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        # Events this week
        events_count = session.query(sa_func.count(StateHistory.id)).filter(
            StateHistory.created_at >= week_ago
        ).scalar() or 0

        # New patterns
        new_patterns = session.query(sa_func.count(LearnedPattern.id)).filter(
            LearnedPattern.created_at >= week_ago
        ).scalar() or 0

        # Active patterns
        active_patterns = session.query(sa_func.count(LearnedPattern.id)).filter(
            LearnedPattern.status == "active", LearnedPattern.is_active == True
        ).scalar() or 0

        # Automations executed
        automations = session.query(sa_func.count(ActionLog.id)).filter(
            ActionLog.action_type == "automation",
            ActionLog.created_at >= week_ago
        ).scalar() or 0

        # Automations undone
        undone = session.query(sa_func.count(ActionLog.id)).filter(
            ActionLog.action_type == "automation",
            ActionLog.was_undone == True,
            ActionLog.created_at >= week_ago
        ).scalar() or 0

        # Anomalies
        anomalies = session.query(sa_func.count(NotificationLog.id)).filter(
            NotificationLog.notification_type == NotificationType.ANOMALY,
            NotificationLog.created_at >= week_ago
        ).scalar() or 0

        # Success rate
        success_rate = round((1 - undone / max(automations, 1)) * 100, 1)

        # Energy estimate: each automation that turns off a light saves ~0.06 kWh
        # This is a rough estimate
        off_automations = session.query(sa_func.count(ActionLog.id)).filter(
            ActionLog.action_type == "automation",
            ActionLog.created_at >= week_ago,
            ActionLog.action_data.contains('"new_state": "off"')
        ).scalar() or 0
        energy_saved_kwh = round(off_automations * 0.06, 2)

        # Learning progress per room
        room_progress = []
        rooms = session.query(Room).filter_by(is_active=True).all()
        for room in rooms:
            states = session.query(RoomDomainState).filter_by(room_id=room.id).all()
            phases = [s.learning_phase.value if s.learning_phase else "observing" for s in states]
            most_advanced = "autonomous" if "autonomous" in phases else "suggesting" if "suggesting" in phases else "observing"
            room_progress.append({"room": room.name, "phase": most_advanced})

        lang = get_language()
        return jsonify({
            "period": {"from": week_ago.isoformat(), "to": now.isoformat()},
            "events_collected": events_count,
            "new_patterns": new_patterns,
            "active_patterns": active_patterns,
            "automations_executed": automations,
            "automations_undone": undone,
            "success_rate": success_rate,
            "anomalies_detected": anomalies,
            "energy_saved_kwh": energy_saved_kwh,
            "room_progress": room_progress,
        })
    finally:
        session.close()



@system_bp.route("/api/backup/export", methods=["GET"])
def api_backup_export():
    """Export MindHome data as JSON. mode=standard|full|custom, include_history=true|false"""
    mode = request.args.get("mode", "standard")
    history_days = request.args.get("history_days", 90, type=int)
    include_history = request.args.get("include_history", "false").lower() == "true"
    session = get_db()
    try:
        backup = {
            "version": VERSION,
            "export_mode": mode,
            "include_history": include_history,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "rooms": [], "devices": [], "users": [], "domains": [],
            "room_domain_states": [], "settings": [], "quick_actions": [],
            "action_log": [], "user_preferences": [],
            "patterns": [], "pattern_exclusions": [], "manual_rules": [],
            "anomaly_settings": [], "notification_settings": [],
            "notification_channels": [], "device_mutes": [],
            "device_groups": [], "calendar_triggers": [],
        }
        for r in session.query(Room).all():
            backup["rooms"].append({"id": r.id, "name": r.name, "ha_area_id": r.ha_area_id,
                "icon": r.icon, "privacy_mode": r.privacy_mode, "is_active": r.is_active})
        for d in session.query(Device).all():
            backup["devices"].append({"id": d.id, "ha_entity_id": d.ha_entity_id, "name": d.name,
                "domain_id": d.domain_id, "room_id": d.room_id,
                "is_tracked": d.is_tracked, "is_controllable": d.is_controllable, "device_meta": d.device_meta})
        for u in session.query(User).all():
            backup["users"].append({"id": u.id, "name": u.name, "ha_person_entity": u.ha_person_entity,
                "role": u.role.value if u.role else "user", "language": u.language})
        for d in session.query(Domain).all():
            backup["domains"].append({"id": d.id, "name": d.name, "is_enabled": d.is_enabled,
                "is_custom": getattr(d, 'is_custom', False),
                "display_name_de": d.display_name_de, "display_name_en": d.display_name_en,
                "icon": d.icon, "description_de": d.description_de, "description_en": d.description_en})
        for rds in session.query(RoomDomainState).all():
            backup["room_domain_states"].append({"room_id": rds.room_id, "domain_id": rds.domain_id,
                "learning_phase": rds.learning_phase.value if rds.learning_phase else "observing",
                "confidence_score": rds.confidence_score, "is_paused": rds.is_paused})
        for s in session.query(SystemSetting).all():
            backup["settings"].append({"key": s.key, "value": s.value})
        for log in session.query(ActionLog).order_by(ActionLog.created_at.desc()).limit(500).all():
            backup["action_log"].append({"action_type": log.action_type, "domain_id": log.domain_id,
                "room_id": log.room_id, "device_id": log.device_id,
                "action_data": log.action_data, "reason": log.reason,
                "was_undone": log.was_undone, "created_at": log.created_at.isoformat()})
        for up in session.query(UserPreference).all():
            backup["user_preferences"].append({"user_id": up.user_id, "room_id": up.room_id,
                "preference_key": up.preference_key, "preference_value": up.preference_value})
        # Patterns
        for p in session.query(LearnedPattern).all():
            backup["patterns"].append({"id": p.id, "pattern_type": p.pattern_type,
                "description_de": p.description_de, "description_en": p.description_en,
                "confidence": p.confidence, "status": p.status, "is_active": p.is_active,
                "room_id": p.room_id, "domain_id": p.domain_id,
                "trigger_conditions": p.trigger_conditions, "action_definition": p.action_definition,
                "pattern_data": p.pattern_data, "match_count": p.match_count,
                "test_mode": p.test_mode, "created_at": utc_iso(p.created_at)})
        # Pattern exclusions
        for pe in session.query(PatternExclusion).all():
            backup["pattern_exclusions"].append({"id": pe.id, "exclusion_type": pe.exclusion_type,
                "entity_a": pe.entity_a, "entity_b": pe.entity_b, "reason": pe.reason})
        # Manual rules
        for mr in session.query(ManualRule).all():
            backup["manual_rules"].append({"id": mr.id, "name": mr.name,
                "trigger_entity": mr.trigger_entity, "trigger_state": mr.trigger_state,
                "action_entity": mr.action_entity, "action_service": mr.action_service,
                "is_active": mr.is_active})
        # Anomaly settings
        for asetting in session.query(AnomalySetting).all():
            backup["anomaly_settings"].append({"id": asetting.id, "room_id": asetting.room_id,
                "domain_id": asetting.domain_id, "device_id": asetting.device_id,
                "sensitivity": asetting.sensitivity, "stuck_detection": asetting.stuck_detection,
                "time_anomaly": asetting.time_anomaly, "frequency_anomaly": asetting.frequency_anomaly,
                "whitelisted_hours": asetting.whitelisted_hours, "auto_action": asetting.auto_action})
        # Notification settings
        for ns in session.query(NotificationSetting).all():
            backup["notification_settings"].append({"notification_type": ns.notification_type.value if ns.notification_type else None,
                "is_enabled": ns.is_enabled, "priority": ns.priority.value if ns.priority else "medium",
                "push_channel": ns.push_channel})
        # Notification channels
        for nc in session.query(NotificationChannel).all():
            backup["notification_channels"].append({"id": nc.id, "name": nc.display_name,
                "service_name": nc.service_name, "channel_type": nc.channel_type,
                "is_enabled": nc.is_enabled})
        # Device mutes
        for dm in session.query(DeviceMute).all():
            backup["device_mutes"].append({"id": dm.id, "device_id": dm.device_id,
                "muted_until": utc_iso(dm.muted_until) if dm.muted_until else None,
                "reason": dm.reason})
        # Device groups
        for g in session.query(DeviceGroup).all():
            backup["device_groups"].append({"id": g.id, "name": g.name,
                "room_id": g.room_id, "device_ids": g.device_ids, "is_active": g.is_active})
        # Quick actions
        backup["quick_actions"] = []
        for qa in session.query(QuickAction).all():
            backup["quick_actions"].append({"id": qa.id, "name_de": qa.name_de, "name_en": qa.name_en, "icon": qa.icon,
                "action_data": qa.action_data,
                "sort_order": qa.sort_order, "is_active": qa.is_active})

        # Full/Custom mode: include historical data ONLY if requested
        if mode in ("full", "custom") and include_history:
            cutoff = datetime.now(timezone.utc) - timedelta(days=history_days)

            # State History (limited by days)
            backup["state_history"] = []
            for sh in session.query(StateHistory).filter(StateHistory.created_at >= cutoff).order_by(StateHistory.created_at.desc()).all():
                backup["state_history"].append({"device_id": sh.device_id, "entity_id": sh.entity_id,
                    "old_state": sh.old_state, "new_state": sh.new_state,
                    "old_attributes": sh.old_attributes, "new_attributes": sh.new_attributes,
                    "context": sh.context, "created_at": utc_iso(sh.created_at)})

            # Predictions
            backup["predictions"] = []
            for p in session.query(Prediction).all():
                backup["predictions"].append({"id": p.id, "pattern_id": p.pattern_id,
                    "predicted_action": p.predicted_action, "confidence": p.confidence,
                    "status": p.status, "user_response": p.user_response,
                    "description_de": p.description_de, "description_en": p.description_en,
                    "created_at": utc_iso(p.created_at)})

            # Notification Log
            backup["notification_log"] = []
            for nl in session.query(NotificationLog).filter(NotificationLog.created_at >= cutoff).all():
                backup["notification_log"].append({"id": nl.id,
                    "notification_type": nl.notification_type.value if nl.notification_type else None, "title": nl.title,
                    "message": nl.message, "was_read": nl.was_read,
                    "created_at": utc_iso(nl.created_at)})

            # Audit Trail
            backup["audit_trail"] = []
            for at in session.query(AuditTrail).filter(AuditTrail.created_at >= cutoff).all():
                backup["audit_trail"].append({"action": at.action, "target": at.target,
                    "details": at.details, "created_at": utc_iso(at.created_at)})

            # Action Log (all, not just 500)
            backup["action_log"] = []
            for log in session.query(ActionLog).filter(ActionLog.created_at >= cutoff).order_by(ActionLog.created_at.desc()).all():
                backup["action_log"].append({"action_type": log.action_type, "domain_id": log.domain_id,
                    "room_id": log.room_id, "device_id": log.device_id,
                    "action_data": log.action_data, "reason": log.reason,
                    "was_undone": log.was_undone, "created_at": log.created_at.isoformat()})

            # Pattern Match Log
            backup["pattern_match_log"] = []
            for pm in session.query(PatternMatchLog).filter(PatternMatchLog.matched_at >= cutoff).all():
                backup["pattern_match_log"].append({"pattern_id": pm.pattern_id,
                    "matched_at": utc_iso(pm.matched_at), "context": pm.context})

            # Data Collection
            backup["data_collection"] = []
            for dc in session.query(DataCollection).filter(DataCollection.created_at >= cutoff).all():
                backup["data_collection"].append({"domain_id": dc.domain_id,
                    "data_type": dc.data_type, "storage_size_bytes": dc.storage_size_bytes,
                    "created_at": utc_iso(dc.created_at)})

            # Offline Action Queue
            backup["offline_queue"] = []
            for oq in session.query(OfflineActionQueue).all():
                backup["offline_queue"].append({
                    "action_data": oq.action_data, "priority": oq.priority,
                    "was_executed": oq.was_executed,
                    "created_at": utc_iso(oq.created_at)})

        # Calendar Triggers (always, they're config)
        backup["calendar_triggers"] = json.loads(get_setting("calendar_triggers") or "[]")

        # Summary for import preview
        backup["_summary"] = {
            "rooms": len(backup.get("rooms", [])),
            "devices": len(backup.get("devices", [])),
            "users": len(backup.get("users", [])),
            "patterns": len(backup.get("patterns", [])),
            "settings": len(backup.get("settings", [])),
            "state_history": len(backup.get("state_history", [])),
            "action_log": len(backup.get("action_log", [])),
            "include_history": include_history,
        }

        return jsonify(backup)
    finally:
        session.close()



@system_bp.route("/api/backup/import", methods=["POST"])
def api_backup_import():
    """Import MindHome configuration from JSON backup. Handles large files gracefully."""
    # Support both JSON body and file upload
    if request.content_type and 'multipart/form-data' in request.content_type:
        file = request.files.get('file')
        if not file:
            return jsonify({"error": "No file uploaded"}), 400
        try:
            raw = file.read()
            if len(raw) > 200 * 1024 * 1024:  # 200MB hard limit
                return jsonify({"error": "Backup too large (max 200MB)"}), 413
            data = json.loads(raw)
        except Exception as e:
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
    else:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None

    if not data or "version" not in data:
        return jsonify({"error": "Invalid backup file"}), 400

    # Skip history tables on import to prevent memory issues
    skip_history = request.args.get("skip_history", "true").lower() == "true"
    history_tables = ["state_history", "action_log", "notification_log",
                      "audit_trail", "pattern_match_log", "data_collection", "offline_queue"]

    session = get_db()
    try:
        # Restore domains
        for d_data in data.get("domains", []):
            try:
                domain = session.query(Domain).filter_by(name=d_data.get("name")).first()
                if domain:
                    domain.is_enabled = d_data.get("is_enabled", False)
                elif d_data.get("is_custom"):
                    domain = Domain(
                        name=d_data["name"],
                        display_name_de=d_data.get("display_name_de", d_data["name"]),
                        display_name_en=d_data.get("display_name_en", d_data["name"]),
                        icon=d_data.get("icon", "mdi:puzzle"),
                        is_enabled=d_data.get("is_enabled", True),
                        is_custom=True,
                        description_de=d_data.get("description_de", ""),
                        description_en=d_data.get("description_en", "")
                    )
                    session.add(domain)
            except Exception as e:
                logger.warning(f"Domain import error: {e}")

        session.flush()

        # Restore rooms
        room_id_map = {}
        for r_data in data.get("rooms", []):
            try:
                existing = session.query(Room).filter_by(name=r_data.get("name")).first()
                if existing:
                    existing.icon = r_data.get("icon", "mdi:door")
                    existing.privacy_mode = r_data.get("privacy_mode") or {}
                    room_id_map[r_data.get("id", 0)] = existing.id
                else:
                    room = Room(
                        name=r_data.get("name", "Room"),
                        ha_area_id=r_data.get("ha_area_id"),
                        icon=r_data.get("icon", "mdi:door"),
                        privacy_mode=r_data.get("privacy_mode") or {},
                        is_active=r_data.get("is_active", True)
                    )
                    session.add(room)
                    session.flush()
                    room_id_map[r_data.get("id", 0)] = room.id
            except Exception as e:
                logger.warning(f"Room import error: {e}")

        session.flush()

        # Restore devices
        for dev_data in data.get("devices", []):
            try:
                entity_id = dev_data.get("ha_entity_id")
                if not entity_id:
                    continue
                existing = session.query(Device).filter_by(ha_entity_id=entity_id).first()
                new_room_id = room_id_map.get(dev_data.get("room_id"))
                if existing:
                    existing.name = dev_data.get("name", existing.name)
                    existing.room_id = new_room_id
                    if dev_data.get("domain_id"):
                        existing.domain_id = dev_data["domain_id"]
                    existing.is_tracked = dev_data.get("is_tracked", True)
                    existing.is_controllable = dev_data.get("is_controllable", True)
                else:
                    device = Device(
                        ha_entity_id=entity_id,
                        name=dev_data.get("name", entity_id),
                        domain_id=dev_data.get("domain_id") or 1,
                        room_id=new_room_id,
                        is_tracked=dev_data.get("is_tracked", True),
                        is_controllable=dev_data.get("is_controllable", True),
                        device_meta=dev_data.get("device_meta") or {}
                    )
                    session.add(device)
            except Exception as e:
                logger.warning(f"Device import error: {e}")

        session.flush()

        # Restore users
        for u_data in data.get("users", []):
            try:
                uname = u_data.get("name")
                if not uname:
                    continue
                existing = session.query(User).filter_by(name=uname).first()
                role_str = u_data.get("role", "user")
                try:
                    role_enum = UserRole(role_str) if isinstance(role_str, str) else role_str
                except (ValueError, KeyError):
                    role_enum = UserRole.USER

                if existing:
                    existing.ha_person_entity = u_data.get("ha_person_entity")
                    existing.role = role_enum
                else:
                    user = User(
                        name=uname,
                        ha_person_entity=u_data.get("ha_person_entity"),
                        role=role_enum,
                        language=u_data.get("language", "de")
                    )
                    session.add(user)
            except Exception as e:
                logger.warning(f"User import error: {e}")

        session.commit()

        for s_data in data.get("settings", []):
            try:
                if s_data.get("key"):
                    set_setting(s_data["key"], s_data.get("value", ""))
            except Exception as e:
                logger.warning(f"Setting import error: {e}")

        # Restore room_domain_states (learning phases)
        session2 = get_db()
        try:
            for rds_data in data.get("room_domain_states", []):
                try:
                    old_room_id = rds_data.get("room_id")
                    new_room_id = room_id_map.get(old_room_id, old_room_id)
                    domain_id = rds_data.get("domain_id")
                    if not new_room_id or not domain_id:
                        continue
                    existing = session2.query(RoomDomainState).filter_by(
                        room_id=new_room_id, domain_id=domain_id
                    ).first()
                    phase_str = rds_data.get("learning_phase", "observing")
                    try:
                        phase_enum = LearningPhase(phase_str)
                    except (ValueError, KeyError):
                        phase_enum = LearningPhase.OBSERVING
                    if existing:
                        existing.learning_phase = phase_enum
                        existing.confidence_score = rds_data.get("confidence_score", 0.0)
                        existing.is_paused = rds_data.get("is_paused", False)
                    else:
                        rds = RoomDomainState(
                            room_id=new_room_id,
                            domain_id=domain_id,
                            learning_phase=phase_enum,
                            confidence_score=rds_data.get("confidence_score", 0.0),
                            is_paused=rds_data.get("is_paused", False)
                        )
                        session2.add(rds)
                except Exception as e:
                    logger.warning(f"RoomDomainState import error: {e}")

            # Restore quick_actions
            for qa_data in data.get("quick_actions", []):
                try:
                    qa_name = qa_data.get("name_de") or qa_data.get("name", "")
                    existing = session2.query(QuickAction).filter_by(
                        name_de=qa_name
                    ).first() if qa_name else None
                    if not existing and qa_name:
                        qa = QuickAction(
                            name_de=qa_data.get("name_de", qa_name),
                            name_en=qa_data.get("name_en", qa_name),
                            icon=qa_data.get("icon", "mdi:flash"),
                            action_data=qa_data.get("action_data") or {},
                            sort_order=qa_data.get("sort_order", 0),
                            is_active=qa_data.get("is_active", True)
                        )
                        session2.add(qa)
                except Exception as e:
                    logger.warning(f"QuickAction import error: {e}")

            # Restore user_preferences
            for up_data in data.get("user_preferences", []):
                try:
                    existing = session2.query(UserPreference).filter_by(
                        user_id=up_data.get("user_id", 1),
                        room_id=up_data.get("room_id"),
                        preference_key=up_data.get("preference_key")
                    ).first()
                    if existing:
                        existing.preference_value = up_data.get("preference_value")
                    elif up_data.get("preference_key"):
                        pref = UserPreference(
                            user_id=up_data.get("user_id", 1),
                            room_id=up_data.get("room_id"),
                            preference_key=up_data["preference_key"],
                            preference_value=up_data.get("preference_value")
                        )
                        session2.add(pref)
                except Exception as e:
                    logger.warning(f"UserPreference import error: {e}")

            session2.commit()
        except Exception as e:
            session2.rollback()
            logger.warning(f"Phase 2 import error: {e}")
        finally:
            session2.close()

        set_setting("onboarding_completed", "true")

        logger.info(f"Backup imported: {len(data.get('rooms',[]))} rooms, {len(data.get('devices',[]))} devices")
        return jsonify({"success": True, "imported": {
            "rooms": len(data.get("rooms", [])),
            "devices": len(data.get("devices", [])),
            "users": len(data.get("users", []))
        }})
    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        logger.error(f"Backup import failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()



@system_bp.route("/api/device-health", methods=["GET"])
def api_device_health():
    """Check all devices for health issues (battery, unreachable)."""
    try:
        issues = _ha().check_device_health()
        return jsonify({"issues": issues, "total": len(issues)})
    except Exception as e:
        logger.error(f"Device health check error: {e}")
        return jsonify({"issues": [], "total": 0, "error": str(e)})



@system_bp.route("/api/system/debug", methods=["GET"])
def api_get_debug():
    """Get debug mode status."""
    try:
        return jsonify({"debug_mode": is_debug_mode()})
    except Exception as e:
        return jsonify({"debug_mode": False, "error": str(e)})


@system_bp.route("/api/system/debug", methods=["PUT"])
def api_toggle_debug():
    """Toggle debug mode."""
    try:
        new_mode = not is_debug_mode()
        set_debug_mode(new_mode)
        level = logging.DEBUG if new_mode else logging.INFO
        logging.getLogger("mindhome").setLevel(level)
        audit_log("debug_mode_toggle", {"enabled": new_mode})
        return jsonify({"debug_mode": new_mode})
    except Exception as e:
        return jsonify({"debug_mode": False, "error": str(e)}), 500



@system_bp.route("/api/system/frontend-error", methods=["POST"])
def api_frontend_error():
    """Log frontend errors for debugging."""
    try:
        data = request.get_json() or {}
        logger.error(f"Frontend error: {data.get('error', 'unknown')} | {data.get('stack', '')[:200]}")
        return jsonify({"logged": True})
    except Exception:
        return jsonify({"logged": False})



@system_bp.route("/api/system/vacation-mode", methods=["GET"])
def api_get_vacation_mode():
    """Get vacation mode status."""
    try:
        return jsonify({
            "enabled": get_setting("vacation_mode", "false") == "true",
            "started_at": get_setting("vacation_started_at"),
            "simulate_presence": get_setting("vacation_simulate", "true") == "true",
        })
    except Exception as e:
        return jsonify({"enabled": False, "error": str(e)})


@system_bp.route("/api/system/vacation-mode", methods=["PUT"])
def api_toggle_vacation_mode():
    """Toggle vacation mode (#23 + #55)."""
    try:
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
        set_setting("vacation_mode", "true" if enabled else "false")
        if enabled:
            set_setting("vacation_started_at", datetime.now(timezone.utc).isoformat())
        else:
            set_setting("vacation_started_at", "")
        set_setting("vacation_simulate", "true" if data.get("simulate_presence", True) else "false")
        audit_log("vacation_mode", {"enabled": enabled})
        return jsonify({"enabled": enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@system_bp.route("/api/export/<data_type>", methods=["GET"])
def api_export_data(data_type):
    """Export data as CSV or JSON."""
    fmt = request.args.get("format", "json")
    session = get_db()
    try:
        if data_type == "patterns":
            items = session.query(LearnedPattern).filter_by(is_active=True).all()
            data = [{"id": p.id, "type": p.pattern_type, "confidence": p.confidence,
                      "status": p.status, "match_count": p.match_count,
                      "description": p.description_de, "created": str(p.created_at)} for p in items]
        elif data_type == "history":
            limit = int(request.args.get("limit", 1000))
            items = session.query(StateHistory).order_by(StateHistory.created_at.desc()).limit(limit).all()
            data = [{"entity_id": h.entity_id, "old_state": h.old_state,
                      "new_state": h.new_state, "created": str(h.created_at)} for h in items]
        elif data_type == "automations":
            items = session.query(ActionLog).filter(
                ActionLog.action_type.in_(["automation_executed", "automation_undone"])
            ).order_by(ActionLog.created_at.desc()).limit(500).all()
            data = [{"type": a.action_type, "device_id": a.device_id,
                      "action_data": a.action_data,
                      "reason": a.reason, "was_undone": a.was_undone,
                      "created": str(a.created_at)} for a in items]
        else:
            return jsonify({"error": "Unknown data type"}), 400

        if fmt == "csv" and data:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
            resp = make_response(output.getvalue())
            resp.headers["Content-Type"] = "text/csv"
            resp.headers["Content-Disposition"] = f"attachment; filename=mindhome_{data_type}.csv"
            return resp

        return jsonify({"data": data, "count": len(data)})
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({"error": str(e), "data": []})
    finally:
        session.close()


@system_bp.route("/api/system/diagnose", methods=["GET"])
def api_diagnose():
    """Generate diagnostic info (no passwords/tokens)."""
    session = get_db()
    try:
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")
        diag = {
            "version": VERSION,
            "python": sys.version.split()[0],
            "uptime_seconds": int(time.time() - _deps.get("start_time", 0)) if _deps.get("start_time", 0) else 0,
            "ha_connected": _ha().is_connected(),
            "connection_stats": _ha().get_connection_stats(),
            "db_size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
            "table_counts": {
                "devices": session.query(Device).count(),
                "rooms": session.query(Room).count(),
                "patterns": session.query(LearnedPattern).count(),
                "state_history": session.query(StateHistory).count(),
                "action_log": session.query(ActionLog).count(),
                "notifications": session.query(NotificationLog).count(),
            },
            "timezone": str(get_ha_timezone()),
            "ha_entities": len(_ha().get_states() or []),
            "debug_mode": is_debug_mode(),
            "vacation_mode": get_setting("vacation_mode", "false"),
            "device_health_issues": len(_ha().check_device_health()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return jsonify(diag)
    except Exception as e:
        logger.error(f"Diagnose error: {e}")
        return jsonify({"error": str(e), "version": VERSION})
    finally:
        session.close()


@system_bp.route("/api/system/check-update", methods=["GET"])
def api_check_update():
    """Check if a newer version is available."""
    try:
        current = VERSION
        return jsonify({
            "current_version": current,
            "update_available": False,
            "message": "Update check requires network access to GitHub.",
        })
    except Exception as e:
        return jsonify({"current_version": VERSION, "error": str(e)})



@system_bp.route("/api/device-groups", methods=["GET"])
def api_get_device_groups():
    """Get all device groups (saved + suggested)."""
    session = get_db()
    try:
        # Saved groups
        saved = session.query(DeviceGroup).all()
        saved_groups = [{
            "id": g.id, "name": g.name, "room_id": g.room_id,
            "device_ids": json.loads(g.device_ids or "[]"),
            "is_active": g.is_active,
            "room_name": g.room.name if g.room else None,
            "created_at": utc_iso(g.created_at),
        } for g in saved]

        # Auto-suggested groups
        rooms = session.query(Room).filter_by(is_active=True).all()
        suggestions = []
        saved_device_sets = {frozenset(json.loads(g.device_ids or "[]")) for g in saved}
        for room in rooms:
            devices = session.query(Device).filter_by(room_id=room.id, is_tracked=True).all()
            by_domain = defaultdict(list)
            for d in devices:
                domain = session.get(Domain, d.domain_id) if d.domain_id else None
                dname = domain.name if domain else "other"
                by_domain[dname].append({"id": d.id, "name": d.name, "entity_id": d.ha_entity_id})
            for domain_name, devs in by_domain.items():
                if len(devs) >= 2:
                    dev_ids = frozenset(d["id"] for d in devs)
                    if dev_ids not in saved_device_sets:
                        suggestions.append({
                            "room": room.name, "room_id": room.id,
                            "domain": domain_name, "devices": devs,
                            "suggested_name": f"{room.name} {domain_name.title()}",
                        })
        return jsonify({"groups": saved_groups, "suggestions": suggestions})
    except Exception as e:
        logger.error(f"Device groups error: {e}")
        return jsonify({"groups": [], "suggestions": [], "error": str(e)})
    finally:
        session.close()



@system_bp.route("/api/device-groups", methods=["POST"])
def api_create_device_group():
    """Create a new device group."""
    data = request.json
    session = get_db()
    try:
        group = DeviceGroup(
            name=data.get("name", "New Group"),
            room_id=data.get("room_id"),
            device_ids=json.dumps(data.get("device_ids", [])),
            is_active=True,
        )
        session.add(group)
        session.commit()
        audit_log("device_group_create", {"name": group.name, "id": group.id})
        return jsonify({"success": True, "id": group.id})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()



@system_bp.route("/api/device-groups/<int:group_id>", methods=["PUT"])
def api_update_device_group(group_id):
    """Update a device group."""
    data = request.json
    session = get_db()
    try:
        group = session.get(DeviceGroup, group_id)
        if not group:
            return jsonify({"error": "Not found"}), 404
        if "name" in data:
            group.name = data["name"]
        if "device_ids" in data:
            group.device_ids = json.dumps(data["device_ids"])
        if "is_active" in data:
            group.is_active = data["is_active"]
        session.commit()
        audit_log("device_group_update", {"id": group_id})
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()



@system_bp.route("/api/device-groups/<int:group_id>", methods=["DELETE"])
def api_delete_device_group(group_id):
    """Delete a device group."""
    session = get_db()
    try:
        group = session.get(DeviceGroup, group_id)
        if group:
            session.delete(group)
            session.commit()
            audit_log("device_group_delete", {"id": group_id})
        return jsonify({"success": True})
    finally:
        session.close()



@system_bp.route("/api/device-groups/<int:group_id>/execute", methods=["POST"])
def api_execute_device_group(group_id):
    """Execute an action on all devices in a group."""
    data = request.json
    service = data.get("service", "toggle")
    session = get_db()
    try:
        group = session.get(DeviceGroup, group_id)
        if not group:
            return jsonify({"error": "Not found"}), 404
        device_ids = json.loads(group.device_ids or "[]")
        results = []
        for did in device_ids:
            device = session.get(Device, did)
            if device and device.ha_entity_id:
                domain_part = device.ha_entity_id.split(".")[0]
                result = _ha().call_service(domain_part, service, {"entity_id": device.ha_entity_id})
                results.append({"entity_id": device.ha_entity_id, "success": result is not None})
        audit_log("device_group_execute", {"group_id": group_id, "service": service, "count": len(results)})
        return jsonify({"success": True, "results": results})
    finally:
        session.close()



@system_bp.route("/api/audit-trail", methods=["GET"])
def api_get_audit_trail():
    """Get audit trail entries."""
    session = get_db()
    try:
        limit = request.args.get("limit", 100, type=int)
        entries = session.query(AuditTrail).order_by(AuditTrail.created_at.desc()).limit(limit).all()
        return jsonify([{
            "id": e.id, "user_id": e.user_id, "action": e.action,
            "target": e.target, "details": e.details,
            "ip_address": e.ip_address, "created_at": utc_iso(e.created_at),
        } for e in entries])
    finally:
        session.close()



_watchdog_status = {"last_check": None, "ha_alive": False, "db_alive": False, "issues": []}


@system_bp.route("/api/system/watchdog", methods=["GET"])
def api_watchdog():
    """Get watchdog status - runs live check."""
    global _watchdog_status
    issues = []
    ha_alive = _ha().is_connected() if _ha() else False
    if not ha_alive:
        issues.append("HA WebSocket disconnected")
    db_alive = False
    try:
        session = get_db()
        session.execute(text("SELECT 1"))
        db_alive = True
        session.close()
    except Exception:
        issues.append("Database unreachable")
    try:
        stat = os.statvfs("/data" if os.path.exists("/data") else "/")
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        if free_gb < 0.5:
            issues.append(f"Low disk space: {free_gb:.1f} GB")
    except Exception:
        pass
    _watchdog_status = {
        "last_check": datetime.now(timezone.utc).isoformat(),
        "ha_alive": ha_alive, "db_alive": db_alive,
        "issues": issues, "healthy": len(issues) == 0,
    }
    return jsonify(_watchdog_status)



@system_bp.route("/api/system/self-test", methods=["GET"])
def api_self_test():
    """Run self-test and return results."""
    results = []
    try:
        session = get_db()
        session.execute(text("SELECT 1"))
        session.close()
        results.append({"test": "database", "status": "ok"})
    except Exception as e:
        results.append({"test": "database", "status": "fail", "error": str(e)})
    try:
        connected = _ha().is_connected() if _ha() else False
        results.append({"test": "ha_connection", "status": "ok" if connected else "warn", "connected": connected})
    except Exception as e:
        results.append({"test": "ha_connection", "status": "fail", "error": str(e)})
    try:
        session = get_db()
        for table in ["devices", "rooms", "domains", "users", "learned_patterns", "state_history"]:
            session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        session.close()
        results.append({"test": "tables", "status": "ok"})
    except Exception as e:
        results.append({"test": "tables", "status": "fail", "error": str(e)})
    try:
        session = get_db()
        session.execute(text("INSERT INTO system_settings (key, value) VALUES ('_selftest', 'ok') ON CONFLICT(key) DO UPDATE SET value='ok'"))
        session.commit()
        session.execute(text("DELETE FROM system_settings WHERE key='_selftest'"))
        session.commit()
        session.close()
        results.append({"test": "db_write", "status": "ok"})
    except Exception as e:
        results.append({"test": "db_write", "status": "fail", "error": str(e)})
    all_ok = all(r["status"] == "ok" for r in results)
    return jsonify({"passed": all_ok, "tests": results})



@system_bp.route("/api/offline-queue", methods=["GET"])
def api_get_offline_queue():
    """Get pending offline actions."""
    session = get_db()
    try:
        items = session.query(OfflineActionQueue).filter_by(was_executed=False).order_by(OfflineActionQueue.priority.desc()).all()
        return jsonify([{
            "id": i.id, "action_data": i.action_data, "priority": i.priority,
            "created_at": utc_iso(i.created_at),
        } for i in items])
    finally:
        session.close()



@system_bp.route("/api/offline-queue", methods=["POST"])
def api_add_offline_action():
    """Queue an action for when HA comes back online."""
    data = request.json
    session = get_db()
    try:
        item = OfflineActionQueue(
            action_data=data.get("action_data", {}),
            priority=data.get("priority", 0),
        )
        session.add(item)
        session.commit()
        return jsonify({"success": True, "id": item.id})
    finally:
        session.close()



@system_bp.route("/api/tts/announce", methods=["POST"])
def api_tts_announce():
    """Send a TTS announcement via HA."""
    data = request.json
    message = data.get("message", "")
    entity = data.get("entity_id")
    if not message:
        return jsonify({"error": "No message"}), 400
    result = _ha().announce_tts(message, media_player_entity=entity)
    audit_log("tts_announce", {"message": message[:50], "entity": entity})
    return jsonify({"success": result is not None})



@system_bp.route("/api/tts/devices", methods=["GET"])
def api_tts_devices():
    """Get available media players for TTS."""
    states = _ha().get_states() or []
    players = [{"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
               for s in states if s["entity_id"].startswith("media_player.")]
    return jsonify(players)



@system_bp.route("/api/ha/entities", methods=["GET"])
def api_get_ha_entities():
    """Get HA entities filtered by domain."""
    domain_filter = request.args.get("domain")
    all_states = _ha().get_states() or []
    entities = []
    for s in all_states:
        eid = s.get("entity_id", "")
        if domain_filter and not eid.startswith(domain_filter + "."):
            continue
        entities.append({
            "entity_id": eid,
            "name": s.get("attributes", {}).get("friendly_name", eid),
            "state": s.get("state")
        })
    return jsonify({"entities": entities})



@system_bp.route("/api/context", methods=["GET"])
def api_get_context():
    try:
        from ml.pattern_engine import ContextBuilder
        builder = ContextBuilder(ha_connection, engine)
        return jsonify(builder.build())
    except Exception as e:
        return jsonify({"error": str(e)})


@system_bp.route("/api/plugins/evaluate", methods=["POST"])
def api_evaluate_plugins():
    results = {}
    try:
        if _domain_manager():
            from ml.pattern_engine import ContextBuilder
            builder = ContextBuilder(ha_connection, engine)
            ctx = builder.build()
            for name, plugin in _domain_manager().plugins.items():
                try:
                    results[name] = plugin.evaluate(ctx) or []
                except Exception as e:
                    results[name] = {"error": str(e)}
    except Exception as e:
        return jsonify({"error": str(e)})
    return jsonify(results)
