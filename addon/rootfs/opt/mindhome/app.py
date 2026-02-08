# MindHome Backend v0.5.2-phase3B-fix3 (2026-02-09 01:00) - app.py - BUILD:20260209-0100
"""
MindHome - Main Application
Flask backend serving the API and frontend.
Version 0.5.0 - Phase 1+2 Complete + 68 Improvements
"""

import os
import sys
import json
import signal
import logging
import threading
import time
import csv
import io
import re
import hashlib
import zipfile
import shutil
from datetime import datetime, timezone, timedelta
from functools import wraps
from collections import defaultdict

from flask import Flask, request, jsonify, send_from_directory, redirect, Response, make_response
from flask_cors import CORS
from sqlalchemy import func as sa_func, text

from models import (
    get_engine, get_session, init_database, run_migrations,
    User, UserRole, Room, Domain, Device, RoomDomainState,
    LearningPhase, QuickAction, SystemSetting, UserPreference,
    PersonSchedule, ShiftTemplate, Holiday,
    NotificationSetting, NotificationType, NotificationPriority,
    NotificationChannel, DeviceMute, ActionLog,
    DataCollection, OfflineActionQueue,
    StateHistory, LearnedPattern, PatternMatchLog,
    Prediction, NotificationLog,
    PatternExclusion, ManualRule, AnomalySetting,
    DeviceGroup, AuditTrail
)
from ha_connection import HAConnection
try:
    from domains import DomainManager
except ImportError:
    DomainManager = None
    logging.getLogger("mindhome").warning("Domain plugins not found, running without domain manager")
from ml.pattern_engine import EventBus, StateLogger, PatternScheduler, PatternDetector
from ml.automation_engine import (
    AutomationScheduler, FeedbackProcessor, AutomationExecutor,
    PhaseManager, NotificationManager, AnomalyDetector, ConflictDetector
)

# ==============================================================================
# App Configuration
# ==============================================================================

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# Register MIME types for frontend files
import mimetypes
mimetypes.add_type("text/javascript", ".jsx")
mimetypes.add_type("text/javascript", ".mjs")

# Logging
log_level = os.environ.get("MINDHOME_LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("mindhome")

# Ingress path
INGRESS_PATH = os.environ.get("INGRESS_PATH", "")

# Database
engine = get_engine()
init_database(engine)
run_migrations(engine)  # Fix 29: DB migration system

# Fix: Auto-set is_controllable=False for sensor-type entities
try:
    _mig_session = get_session(engine)
    NON_CONTROLLABLE = ("sensor.", "binary_sensor.", "zone.", "sun.", "weather.", "person.", "device_tracker.", "calendar.", "proximity.")
    _updated = 0
    for dev in _mig_session.query(Device).filter_by(is_controllable=True).all():
        if dev.ha_entity_id and any(dev.ha_entity_id.startswith(p) for p in NON_CONTROLLABLE):
            dev.is_controllable = False
            _updated += 1
    if _updated:
        _mig_session.commit()
        logger.info(f"Auto-fixed is_controllable for {_updated} sensor-type devices")
    _mig_session.close()
except Exception as _e:
    logger.warning(f"Controllable migration: {_e}")

# Home Assistant connection
ha = HAConnection()

# Timezone: sync from HA
import zoneinfo
_ha_tz = None

def get_ha_timezone():
    """Get HA timezone as zoneinfo object, cached."""
    global _ha_tz
    if _ha_tz:
        return _ha_tz
    try:
        tz_name = ha.get_timezone()
        _ha_tz = zoneinfo.ZoneInfo(tz_name)
        logger.info(f"Using HA timezone: {tz_name}")
    except Exception as e:
        logger.warning(f"Could not get HA timezone: {e}, falling back to UTC")
        _ha_tz = timezone.utc
    return _ha_tz

def local_now():
    """Get current time in HA's timezone."""
    tz = get_ha_timezone()
    return datetime.now(tz)


def utc_iso(dt):
    """Convert datetime to ISO string with Z suffix for UTC. Handles None."""
    if dt is None:
        return None
    s = dt.isoformat()
    if not dt.tzinfo and not s.endswith('Z'):
        s += 'Z'
    return s


# ==============================================================================
# #3 Rate Limiting
# ==============================================================================
_rate_limit_data = defaultdict(list)
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 120

def rate_limit_check():
    """Check if current request exceeds rate limit."""
    ip = request.remote_addr or "unknown"
    now = time.time()
    _rate_limit_data[ip] = [t for t in _rate_limit_data[ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limit_data[ip]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit_data[ip].append(now)
    return True


# ==============================================================================
# #14 Input Sanitization
# ==============================================================================
_SANITIZE_RE = re.compile(r'[<>]')

def sanitize_input(value, max_length=500):
    """Sanitize user input - strip angle brackets, limit length."""
    if not isinstance(value, str):
        return value
    return _SANITIZE_RE.sub('', value.strip()[:max_length])

def sanitize_dict(data, keys=None):
    """Sanitize string values in a dict."""
    if not isinstance(data, dict):
        return data
    return {k: (sanitize_input(v) if isinstance(v, str) and (not keys or k in keys) else v) for k, v in data.items()}


# ==============================================================================
# #60 Audit Log helper
# ==============================================================================
def audit_log(action, details=None, user_id=None):
    """Log an audit trail entry."""
    try:
        session = get_db()
        entry = ActionLog(
            action_type="audit", device_name="system",
            old_value=action,
            new_value=json.dumps(details)[:500] if details else None,
            reason=f"user:{user_id}" if user_id else "system",
        )
        session.add(entry)
        session.commit()
        session.close()
    except Exception:
        pass


# ==============================================================================
# #42 Debug Mode
# ==============================================================================
_debug_mode = False

def is_debug_mode():
    global _debug_mode
    return _debug_mode


# Domain Manager (optional - depends on domain plugins package)
domain_manager = DomainManager(ha, lambda: get_session(engine)) if DomainManager else None

# Domain Plugin Configuration - defines capabilities per domain
DOMAIN_PLUGINS = {
    "light": {
        "ha_domain": "light",
        "attributes": ["brightness", "color_temp", "rgb_color", "effect"],
        "controls": ["toggle", "brightness", "color_temp"],
        "pattern_features": ["time_of_day", "brightness_level", "duration"],
        "icon": "mdi:lightbulb",
    },
    "climate": {
        "ha_domain": "climate",
        "attributes": ["current_temperature", "temperature", "hvac_action", "humidity"],
        "controls": ["set_temperature", "set_hvac_mode"],
        "pattern_features": ["target_temp", "schedule", "comfort_profile"],
        "icon": "mdi:thermostat",
    },
    "cover": {
        "ha_domain": "cover",
        "attributes": ["current_position", "current_tilt_position"],
        "controls": ["open", "close", "set_position"],
        "pattern_features": ["position", "time_of_day", "sun_based"],
        "icon": "mdi:window-shutter",
    },
    "switch": {
        "ha_domain": "switch",
        "attributes": ["current_power_w", "today_energy_kwh"],
        "controls": ["toggle"],
        "pattern_features": ["time_of_day", "duration"],
        "icon": "mdi:toggle-switch",
    },
    "sensor": {
        "ha_domain": "sensor",
        "attributes": ["unit_of_measurement", "device_class"],
        "controls": [],
        "pattern_features": ["threshold", "trend"],
        "icon": "mdi:eye",
    },
    "binary_sensor": {
        "ha_domain": "binary_sensor",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": ["trigger", "duration", "frequency"],
        "icon": "mdi:checkbox-blank-circle-outline",
    },
    "media_player": {
        "ha_domain": "media_player",
        "attributes": ["media_title", "volume_level", "source"],
        "controls": ["toggle", "volume", "source"],
        "pattern_features": ["time_of_day", "source_preference"],
        "icon": "mdi:speaker",
    },
    "lock": {
        "ha_domain": "lock",
        "attributes": [],
        "controls": ["lock", "unlock"],
        "pattern_features": ["time_of_day", "presence"],
        "icon": "mdi:lock",
    },
    "vacuum": {
        "ha_domain": "vacuum",
        "attributes": ["battery_level", "status"],
        "controls": ["start", "stop", "return_to_base"],
        "pattern_features": ["schedule", "presence"],
        "icon": "mdi:robot-vacuum",
    },
    "fan": {
        "ha_domain": "fan",
        "attributes": ["percentage", "preset_mode"],
        "controls": ["toggle", "set_percentage"],
        "pattern_features": ["temperature_based", "time_of_day"],
        "icon": "mdi:fan",
    },
    "motion": {
        "ha_domain": "binary_sensor",
        "device_class": "motion",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": ["time_of_day", "frequency", "duration", "room_correlation"],
        "icon": "mdi:motion-sensor",
    },
    "presence": {
        "ha_domain": "person",
        "attributes": ["source", "gps_accuracy"],
        "controls": [],
        "pattern_features": ["arrival_time", "departure_time", "routine"],
        "icon": "mdi:account-multiple",
    },
    "door_window": {
        "ha_domain": "binary_sensor",
        "device_class": "door",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": ["open_duration", "frequency", "time_of_day"],
        "icon": "mdi:door",
    },
    "energy": {
        "ha_domain": "sensor",
        "device_class": "energy",
        "attributes": ["unit_of_measurement", "state_class"],
        "controls": [],
        "pattern_features": ["daily_usage", "peak_hours", "baseline"],
        "icon": "mdi:flash",
    },
    "weather": {
        "ha_domain": "weather",
        "attributes": ["temperature", "humidity", "forecast"],
        "controls": [],
        "pattern_features": ["condition_correlation"],
        "icon": "mdi:weather-cloudy",
    },
}

# Phase 2a: Pattern Engine
event_bus = EventBus()
state_logger = StateLogger(engine, ha)
pattern_scheduler = PatternScheduler(engine, ha)

# Phase 2b: Automation Engine
automation_scheduler = AutomationScheduler(engine, ha)

# Cleanup timer
_cleanup_timer = None


# ==============================================================================
# Event Handlers
# ==============================================================================

def on_state_changed(event):
    """Handle real-time state change events from HA."""
    # Route to domain plugins (if available)
    if domain_manager:
        domain_manager.on_state_change(event)

    event_data = event.get("data", {}) if event else {}
    entity_id = event_data.get("entity_id", "")
    new_state = event_data.get("new_state") or {}
    old_state = event_data.get("old_state") or {}
    logger.debug(f"State changed: {entity_id} -> {new_state.get('state', '?')}")

    # Phase 2a: Log to state_history via pattern engine
    try:
        state_logger.log_state_change(event_data)
    except Exception as e:
        logger.debug(f"Pattern state log error: {e}")

    # Phase 2a: Publish to event bus for other subscribers
    event_bus.publish("state_changed", event_data)

    # Log tracked device state changes to DB
    try:
        new_val = new_state.get("state", "unknown") if isinstance(new_state, dict) else "unknown"
        old_val = old_state.get("state", "unknown") if isinstance(old_state, dict) else "unknown"

        # Fix 1: Extract attributes (brightness, position, temperature etc.)
        new_attrs = new_state.get("attributes", {}) if isinstance(new_state, dict) else {}
        old_attrs = old_state.get("attributes", {}) if isinstance(old_state, dict) else {}

        if entity_id and new_val != old_val:
            log_state_change(entity_id, new_val, old_val, new_attrs, old_attrs)
    except Exception as e:
        logger.debug(f"State log error: {e}")


# ==============================================================================
# Helpers
# ==============================================================================

def get_db():
    """Get a new database session."""
    return get_session(engine)


def get_setting(key, default=None):
    """Get a system setting value."""
    session = get_db()
    try:
        setting = session.query(SystemSetting).filter_by(key=key).first()
        return setting.value if setting else default
    finally:
        session.close()


def set_setting(key, value):
    """Set a system setting value."""
    session = get_db()
    try:
        setting = session.query(SystemSetting).filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = SystemSetting(key=key, value=str(value))
            session.add(setting)
        session.commit()
    finally:
        session.close()


def get_language():
    """Get current language setting."""
    return os.environ.get("MINDHOME_LANGUAGE", "de")


def localize(de_text, en_text):
    """Return text in current language."""
    return de_text if get_language() == "de" else en_text


def extract_display_attributes(entity_id, attrs):
    """Fix 1: Extract human-readable attributes from HA state attributes."""
    result = {}
    ha_domain = entity_id.split(".")[0] if entity_id else ""

    # Brightness (lights) - HA sends 0-255, convert to %
    if "brightness" in attrs and attrs["brightness"] is not None:
        try:
            result["brightness_pct"] = round(int(attrs["brightness"]) / 255 * 100)
        except (ValueError, TypeError):
            pass

    # Color temperature
    if "color_temp_kelvin" in attrs:
        result["color_temp_kelvin"] = attrs["color_temp_kelvin"]
    elif "color_temp" in attrs:
        result["color_temp"] = attrs["color_temp"]

    # Cover/Roller position (0-100%)
    if "current_position" in attrs:
        result["position_pct"] = attrs["current_position"]

    # Climate
    if "temperature" in attrs:
        result["target_temp"] = attrs["temperature"]
    if "current_temperature" in attrs:
        result["current_temp"] = attrs["current_temperature"]
    if "hvac_mode" in attrs or "hvac_action" in attrs:
        result["hvac_mode"] = attrs.get("hvac_mode")
        result["hvac_action"] = attrs.get("hvac_action")
    if "humidity" in attrs:
        result["humidity"] = attrs["humidity"]

    # Power/Energy (smart plugs)
    for key in ["current_power_w", "power", "current", "voltage",
                "total_energy_kwh", "energy", "total_increasing"]:
        if key in attrs and attrs[key] is not None:
            result[key] = attrs[key]

    # Air quality
    for key in ["co2", "voc", "pm25", "pm10", "aqi"]:
        if key in attrs and attrs[key] is not None:
            result[key] = attrs[key]

    # Unit of measurement (for sensors etc.)
    if "unit_of_measurement" in attrs and attrs["unit_of_measurement"]:
        result["unit"] = attrs["unit_of_measurement"]

    return result


def build_state_reason(device_name, old_val, new_val, new_display_attrs):
    """Build a human-readable reason string including attributes."""
    reason = f"{device_name}: {old_val} â†’ {new_val}"

    details = []
    if "brightness_pct" in new_display_attrs:
        details.append(f"{new_display_attrs['brightness_pct']}%")
    if "position_pct" in new_display_attrs:
        details.append(f"Position {new_display_attrs['position_pct']}%")
    if "target_temp" in new_display_attrs:
        details.append(f"{new_display_attrs['target_temp']}Â°C")
    if "current_temp" in new_display_attrs:
        details.append(f"Ist: {new_display_attrs['current_temp']}Â°C")

    if details:
        reason += f" ({', '.join(details)})"

    return reason


# ==============================================================================
# Middleware (#3 Rate Limiting, #13 CSRF Token)
# ==============================================================================

@app.before_request
def before_request_middleware():
    """Rate limiting + ingress token check."""
    if request.path.startswith("/static") or request.path == "/":
        return None
    if request.path.startswith("/api/") and not rate_limit_check():
        return jsonify({"error": "Rate limit exceeded"}), 429
    return None


# Global error handlers - catch ALL unhandled exceptions
@app.errorhandler(500)
def handle_500(error):
    """Catch unhandled server errors and return JSON."""
    logger.error(f"Unhandled 500 error: {error}")
    return jsonify({"error": "Internal server error", "message": str(error)[:200]}), 500

@app.errorhandler(404)
def handle_404(error):
    """Handle 404 errors."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return redirect("/")

@app.errorhandler(Exception)
def handle_exception(error):
    """Catch-all for any unhandled exception in API routes."""
    logger.error(f"Unhandled exception: {type(error).__name__}: {error}")
    if request.path.startswith("/api/"):
        return jsonify({"error": type(error).__name__, "message": str(error)[:200]}), 500
    return redirect("/")


# ==============================================================================
# API Routes - System
# ==============================================================================

@app.route("/api/system/status", methods=["GET"])
def api_system_status():
    """Get system status overview."""
    session = get_db()
    try:
        tz = get_ha_timezone()
        tz_name = str(tz) if tz != timezone.utc else "UTC"
        return jsonify({
            "status": "running",
            "ha_connected": ha.is_connected(),
            "offline_queue_size": ha.get_offline_queue_size(),
            "system_mode": get_setting("system_mode", "normal"),
            "onboarding_completed": get_setting("onboarding_completed", "false") == "true",
            "language": get_language(),
            "theme": get_setting("theme", "dark"),
            "view_mode": get_setting("view_mode", "simple"),
            "version": "0.5.0",
            "timezone": tz_name,
            "local_time": local_now().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    finally:
        session.close()


# #1 Healthcheck for HA Add-on
@app.route("/api/health", methods=["GET"])
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
        "status": "ok" if ha._ws_connected else "disconnected",
        "reconnect_attempts": ha._reconnect_attempts,
    }
    health["checks"]["ha_rest_api"] = {
        "status": "ok" if ha._is_online else "offline"
    }

    # #41 Connection stats
    health["checks"]["connection_stats"] = ha.get_connection_stats()

    # #24 Device health summary
    try:
        device_issues = ha.check_device_health()
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

    health["uptime_seconds"] = int(time.time() - _start_time) if _start_time else 0
    health["version"] = "0.5.0"
    health["debug_mode"] = is_debug_mode()

    status_code = 200 if health["status"] == "healthy" else 503
    return jsonify(health), status_code


# Fix 25: System Info
@app.route("/api/system/info", methods=["GET"])
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
            "version": "0.5.0",
            "phase": "2 (complete)",
            "ha_connected": ha.is_connected(),
            "ws_connected": ha._ws_connected,
            "ha_entity_count": len(ha.get_states() or []),
            "timezone": str(get_ha_timezone()),
            "local_time": local_now().isoformat(),
            "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
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
            "event_bus_subscribers": event_bus.subscriber_count("state_changed"),
        })
    finally:
        session.close()


@app.route("/api/system/settings", methods=["GET"])
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


@app.route("/api/system/settings/<key>", methods=["PUT"])
def api_update_setting(key):
    """Update a system setting."""
    data = request.json
    set_setting(key, data.get("value"))
    return jsonify({"success": True, "key": key, "value": data.get("value")})


@app.route("/api/system/emergency-stop", methods=["POST"])
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


@app.route("/api/system/resume", methods=["POST"])
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


# ==============================================================================
# API Routes - Domains
# ==============================================================================

@app.route("/api/domains", methods=["GET"])
def api_get_domains():
    """Get all available domains."""
    session = get_db()
    try:
        domains = session.query(Domain).all()
        lang = get_language()
        return jsonify([{
            "id": d.id,
            "name": d.name,
            "display_name": d.display_name_de if lang == "de" else d.display_name_en,
            "icon": d.icon,
            "is_enabled": d.is_enabled,
            "is_custom": d.is_custom if hasattr(d, 'is_custom') else False,
            "description": d.description_de if lang == "de" else d.description_en
        } for d in domains])
    finally:
        session.close()


# Fix 7: Custom Domains - Create
@app.route("/api/domains", methods=["POST"])
def api_create_domain():
    """Create a custom domain."""
    data = request.json
    session = get_db()
    try:
        name = data.get("name", "").strip().lower().replace(" ", "_")
        if not name:
            return jsonify({"error": "Name is required"}), 400

        existing = session.query(Domain).filter_by(name=name).first()
        if existing:
            return jsonify({"error": "Domain already exists"}), 400

        domain = Domain(
            name=name,
            display_name_de=data.get("display_name_de", data.get("name", name)),
            display_name_en=data.get("display_name_en", data.get("name", name)),
            icon=data.get("icon", "mdi:puzzle"),
            is_enabled=True,
            is_custom=True,
            description_de=data.get("description_de", ""),
            description_en=data.get("description_en", "")
        )
        session.add(domain)
        session.commit()
        return jsonify({"id": domain.id, "name": domain.name}), 201
    finally:
        session.close()


# Fix 7: Custom Domains - Update
@app.route("/api/domains/<int:domain_id>", methods=["PUT"])
def api_update_domain(domain_id):
    """Update a custom domain."""
    data = request.json
    session = get_db()
    try:
        domain = session.get(Domain, domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        if not getattr(domain, 'is_custom', False):
            return jsonify({"error": "Cannot edit system domains"}), 400

        if "display_name_de" in data:
            domain.display_name_de = data["display_name_de"]
        if "display_name_en" in data:
            domain.display_name_en = data["display_name_en"]
        if "name_de" in data:
            domain.display_name_de = data["name_de"]
            if not domain.display_name_en:
                domain.display_name_en = data["name_de"]
        if "icon" in data:
            domain.icon = data["icon"]
        if "description_de" in data:
            domain.description_de = data["description_de"]
        if "description_en" in data:
            domain.description_en = data["description_en"]
        if "description" in data:
            domain.description_de = data["description"]
            if not domain.description_en:
                domain.description_en = data["description"]
        if "keywords" in data:
            domain.keywords = data["keywords"]

        session.commit()
        return jsonify({"id": domain.id, "name": domain.name})
    finally:
        session.close()


# Fix 7: Custom Domains - Delete
@app.route("/api/domains/<int:domain_id>", methods=["DELETE"])
def api_delete_domain(domain_id):
    """Delete a custom domain."""
    session = get_db()
    try:
        domain = session.get(Domain, domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        if not getattr(domain, 'is_custom', False):
            return jsonify({"error": "Cannot delete system domains"}), 400

        # Move devices to unassigned
        devices = session.query(Device).filter_by(domain_id=domain_id).all()
        default_domain = session.query(Domain).filter_by(name="switch").first()
        for d in devices:
            d.domain_id = default_domain.id if default_domain else 1

        # Remove room domain states
        session.query(RoomDomainState).filter_by(domain_id=domain_id).delete()

        session.delete(domain)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@app.route("/api/domains/<int:domain_id>/toggle", methods=["POST"])
def api_toggle_domain(domain_id):
    """Enable or disable a domain."""
    session = get_db()
    try:
        domain = session.get(Domain, domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        domain.is_enabled = not domain.is_enabled
        session.commit()

        if domain.is_enabled:
            if domain_manager: domain_manager.start_domain(domain.name)
        else:
            if domain_manager: domain_manager.stop_domain(domain.name)

        return jsonify({"id": domain.id, "is_enabled": domain.is_enabled})
    finally:
        session.close()


@app.route("/api/domains/status", methods=["GET"])
def api_domain_status():
    """Get live status from all active domain plugins."""
    return jsonify(domain_manager.get_all_status())


@app.route("/api/domains/capabilities", methods=["GET"])
def api_domain_capabilities():
    """Get per-domain capabilities for frontend display."""
    return jsonify(DOMAIN_PLUGINS)


@app.route("/api/domains/<domain_name>/features", methods=["GET"])
def api_domain_features(domain_name):
    """Get trackable features for a domain (for privacy settings)."""
    features = domain_manager.get_trackable_features(domain_name)
    return jsonify({"domain": domain_name, "features": features})


# ==============================================================================
# API Routes - Rooms
# ==============================================================================

@app.route("/api/rooms", methods=["GET"])
def api_get_rooms():
    """Get all rooms with last activity info."""
    session = get_db()
    try:
        rooms = session.query(Room).filter_by(is_active=True).all()
        result = []
        for r in rooms:
            # Fix 13: Get last activity for this room
            last_log = session.query(ActionLog).filter(
                ActionLog.room_id == r.id,
                ActionLog.action_type == "observation"
            ).order_by(ActionLog.created_at.desc()).first()

            # Fix 6: Only include domain_states for domains that have devices in this room
            device_domain_ids = set(d.domain_id for d in r.devices)

            result.append({
                "id": r.id,
                "name": r.name,
                "ha_area_id": r.ha_area_id,
                "icon": r.icon,
                "privacy_mode": r.privacy_mode,
                "device_count": len(r.devices),
                "last_activity": utc_iso(last_log.created_at) if last_log else None,
                "domain_states": [{
                    "domain_id": ds.domain_id,
                    "learning_phase": ds.learning_phase.value,
                    "confidence_score": ds.confidence_score,
                    "is_paused": ds.is_paused
                } for ds in r.domain_states if ds.domain_id in device_domain_ids]
            })
        return jsonify(result)
    finally:
        session.close()


@app.route("/api/rooms", methods=["POST"])
def api_create_room():
    """Create a new room."""
    data = request.json
    session = get_db()
    try:
        room = Room(
            name=data["name"],
            ha_area_id=data.get("ha_area_id"),
            icon=data.get("icon", "mdi:door"),
            privacy_mode=data.get("privacy_mode", {})
        )
        session.add(room)
        session.commit()

        # Create domain states for all enabled domains
        enabled_domains = session.query(Domain).filter_by(is_enabled=True).all()
        for domain in enabled_domains:
            state = RoomDomainState(
                room_id=room.id,
                domain_id=domain.id,
                learning_phase=LearningPhase.OBSERVING
            )
            session.add(state)
        session.commit()

        return jsonify({"id": room.id, "name": room.name}), 201
    finally:
        session.close()


# Fix 9: Import rooms from HA Areas
@app.route("/api/rooms/import-from-ha", methods=["POST"])
def api_import_rooms_from_ha():
    """Import rooms from HA Areas."""
    session = get_db()
    try:
        areas = ha.get_areas() or []
        if not areas:
            return jsonify({"error": "No areas found in HA", "imported": 0}), 200

        imported = 0
        skipped = 0

        for area in areas:
            area_id = area.get("area_id", "")
            area_name = area.get("name", "")
            if not area_name:
                continue

            # Check if room already exists (by ha_area_id or name)
            existing = session.query(Room).filter(
                (Room.ha_area_id == area_id) | (Room.name == area_name)
            ).first()

            if existing:
                # Update ha_area_id if missing
                if not existing.ha_area_id:
                    existing.ha_area_id = area_id
                skipped += 1
                continue

            room = Room(
                name=area_name,
                ha_area_id=area_id,
                icon=area.get("icon") or "mdi:door",
                privacy_mode={}
            )
            session.add(room)
            session.flush()

            # Create domain states
            enabled_domains = session.query(Domain).filter_by(is_enabled=True).all()
            for domain in enabled_domains:
                state = RoomDomainState(
                    room_id=room.id,
                    domain_id=domain.id,
                    learning_phase=LearningPhase.OBSERVING
                )
                session.add(state)

            imported += 1

        session.commit()
        return jsonify({"success": True, "imported": imported, "skipped": skipped})
    finally:
        session.close()


@app.route("/api/rooms/<int:room_id>", methods=["PUT"])
def api_update_room(room_id):
    """Update a room."""
    data = request.json
    session = get_db()
    try:
        room = session.get(Room, room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404

        if "name" in data:
            room.name = data["name"]
        if "icon" in data:
            room.icon = data["icon"]
        if "privacy_mode" in data:
            room.privacy_mode = data["privacy_mode"]

        session.commit()
        return jsonify({"id": room.id, "name": room.name})
    finally:
        session.close()


@app.route("/api/rooms/<int:room_id>", methods=["DELETE"])
def api_delete_room(room_id):
    """Delete a room."""
    session = get_db()
    try:
        room = session.get(Room, room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        room.is_active = False  # Soft delete
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@app.route("/api/rooms/<int:room_id>/privacy", methods=["PUT"])
def api_update_room_privacy(room_id):
    """Update privacy mode for a room."""
    data = request.json
    session = get_db()
    try:
        room = session.get(Room, room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        room.privacy_mode = data.get("privacy_mode", {})
        session.commit()
        return jsonify({"id": room.id, "privacy_mode": room.privacy_mode})
    finally:
        session.close()


# ==============================================================================
# API Routes - Devices
# ==============================================================================

@app.route("/api/devices", methods=["GET"])
def api_get_devices():
    """Get all tracked devices with live status."""
    session = get_db()
    try:
        devices = session.query(Device).all()
        result = []
        for d in devices:
            dev_data = {
                "id": d.id,
                "ha_entity_id": d.ha_entity_id,
                "name": d.name,
                "domain_id": d.domain_id,
                "room_id": d.room_id,
                "is_tracked": d.is_tracked,
                "is_controllable": d.is_controllable
            }

            # Fix 14: Include live state from HA
            try:
                state = ha.get_state(d.ha_entity_id)
                if state:
                    dev_data["live_state"] = state.get("state", "unknown")
                    attrs = state.get("attributes", {})
                    dev_data["live_attributes"] = extract_display_attributes(
                        d.ha_entity_id, attrs
                    )
                else:
                    dev_data["live_state"] = "unavailable"
                    dev_data["live_attributes"] = {}
            except Exception:
                dev_data["live_state"] = "unknown"
                dev_data["live_attributes"] = {}

            result.append(dev_data)
        return jsonify(result)
    finally:
        session.close()


@app.route("/api/devices/<int:device_id>", methods=["PUT"])
def api_update_device(device_id):
    """Update device settings."""
    data = request.json
    session = get_db()
    try:
        device = session.get(Device, device_id)
        if not device:
            return jsonify({"error": "Device not found"}), 404

        if "room_id" in data:
            device.room_id = data["room_id"]
        if "is_tracked" in data:
            device.is_tracked = data["is_tracked"]
        if "is_controllable" in data:
            device.is_controllable = data["is_controllable"]
        if "name" in data:
            device.name = data["name"]
        if "domain_id" in data:
            device.domain_id = data["domain_id"]

        session.commit()
        return jsonify({"id": device.id, "name": device.name})
    finally:
        session.close()


# Fix 24: Bulk actions for devices
@app.route("/api/devices/bulk", methods=["PUT"])
def api_bulk_update_devices():
    """Bulk update multiple devices at once."""
    data = request.json
    session = get_db()
    try:
        device_ids = data.get("device_ids", [])
        # Support both flat and nested format
        updates = data.get("updates", {})
        if not updates:
            updates = {k: v for k, v in data.items() if k != "device_ids"}

        if not device_ids:
            return jsonify({"error": "No devices selected"}), 400

        updated = 0
        for did in device_ids:
            device = session.get(Device, did)
            if not device:
                continue
            if "room_id" in updates:
                device.room_id = updates["room_id"]
            if "domain_id" in updates:
                device.domain_id = updates["domain_id"]
            if "is_tracked" in updates:
                device.is_tracked = updates["is_tracked"]
            if "is_controllable" in updates:
                device.is_controllable = updates["is_controllable"]
            updated += 1

        session.commit()
        return jsonify({"success": True, "updated": updated})
    finally:
        session.close()


# Fix 24: Bulk delete devices
@app.route("/api/devices/bulk", methods=["DELETE"])
def api_bulk_delete_devices():
    """Bulk delete multiple devices."""
    data = request.json
    session = get_db()
    try:
        device_ids = data.get("device_ids", [])
        if not device_ids:
            return jsonify({"error": "No devices selected"}), 400

        deleted = 0
        for did in device_ids:
            device = session.get(Device, did)
            if device:
                session.delete(device)
                deleted += 1

        session.commit()
        return jsonify({"success": True, "deleted": deleted})
    finally:
        session.close()


@app.route("/api/devices/<int:device_id>", methods=["DELETE"])
def api_delete_device(device_id):
    """Delete a device."""
    session = get_db()
    try:
        device = session.get(Device, device_id)
        if not device:
            return jsonify({"error": "Device not found"}), 404
        session.delete(device)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


# ==============================================================================
# API Routes - Discovery (Onboarding)
# ==============================================================================

@app.route("/api/discover", methods=["GET"])
def api_discover_devices():
    """Discover all HA devices grouped by MindHome domain."""
    discovered = ha.discover_devices()

    # Fix 20: Filter out invalid entities
    for domain_name in list(discovered.keys()):
        entities = discovered[domain_name]
        filtered = []
        for entity in entities:
            state_val = entity.get("state", "")
            # Skip permanently unavailable/unknown entities
            if state_val in ("unavailable", "unknown", None, ""):
                continue
            filtered.append(entity)
        discovered[domain_name] = filtered

    summary = {}
    for domain_name, entities in discovered.items():
        summary[domain_name] = {
            "count": len(entities),
            "entities": entities
        }

    return jsonify({
        "domains": summary,
        "total_entities": sum(len(e) for e in discovered.values()),
        "ha_connected": ha.is_connected()
    })


@app.route("/api/discover/import", methods=["POST"])
def api_import_discovered():
    """Import selected discovered devices into MindHome."""
    data = request.json
    session = get_db()
    try:
        imported_count = 0
        skipped_count = 0
        selected_ids = data.get("selected_entities", [])

        # Fix 21: Get HA entity registry for area assignments
        entity_registry = ha.get_entity_registry() or []
        device_registry = ha.get_device_registry() or []

        # Build lookup: entity_id -> area_id
        # First: device_id -> area_id from device registry
        device_area_map = {}
        for dev in device_registry:
            dev_id = dev.get("id", "")
            area_id = dev.get("area_id", "")
            if dev_id and area_id:
                device_area_map[dev_id] = area_id

        # Then: entity_id -> area_id (entity area takes priority, else device area)
        entity_area_map = {}
        for ent in entity_registry:
            eid = ent.get("entity_id", "")
            area = ent.get("area_id") or device_area_map.get(ent.get("device_id", ""))
            if eid and area:
                entity_area_map[eid] = area

        # Build area_id -> room_id lookup
        area_room_map = {}
        rooms = session.query(Room).filter(Room.ha_area_id.isnot(None)).all()
        for room in rooms:
            if room.ha_area_id:
                area_room_map[room.ha_area_id] = room.id

        for domain_name, domain_data in data.get("domains", {}).items():
            domain = session.query(Domain).filter_by(name=domain_name).first()
            if not domain:
                continue

            if isinstance(domain_data, dict):
                entities = domain_data.get("entities", [])
            elif isinstance(domain_data, list):
                entities = domain_data
            else:
                continue

            has_imported = False
            for entity_info in entities:
                if isinstance(entity_info, str):
                    entity_id = entity_info
                    friendly_name = entity_info
                    attributes = {}
                elif isinstance(entity_info, dict):
                    entity_id = entity_info.get("entity_id", "")
                    friendly_name = entity_info.get("friendly_name", entity_id)
                    attributes = entity_info.get("attributes", {})
                else:
                    continue

                if selected_ids and entity_id not in selected_ids:
                    continue

                # Fix 19: Duplicate protection
                existing = session.query(Device).filter_by(ha_entity_id=entity_id).first()
                if existing:
                    skipped_count += 1
                    continue

                # Fix 21: Auto-assign room via HA Area
                room_id = None
                area_id = entity_area_map.get(entity_id)
                if area_id:
                    room_id = area_room_map.get(area_id)

                # Auto-detect controllability
                ha_domain = entity_id.split(".")[0]
                non_controllable = {"sensor", "binary_sensor", "zone", "sun", "weather", "person", "device_tracker", "calendar", "proximity"}

                device = Device(
                    ha_entity_id=entity_id,
                    name=friendly_name,
                    domain_id=domain.id,
                    room_id=room_id,
                    device_meta=attributes,
                    is_controllable=ha_domain not in non_controllable
                )
                session.add(device)
                imported_count += 1
                has_imported = True

            if has_imported:
                domain.is_enabled = True

        session.commit()
        return jsonify({
            "success": True,
            "imported": imported_count,
            "skipped": skipped_count,
            "message": f"{imported_count} importiert, {skipped_count} Ã¼bersprungen (bereits vorhanden)"
        })
    finally:
        session.close()


# Fix 5: Manual device search - get ALL HA entities
@app.route("/api/discover/all-entities", methods=["GET"])
def api_get_all_ha_entities():
    """Get all HA entities for manual device search."""
    states = ha.get_states() or []
    session = get_db()
    try:
        # Get already imported entity IDs
        imported_ids = set(
            d.ha_entity_id for d in session.query(Device.ha_entity_id).all()
        )

        entities = []
        for s in states:
            eid = s.get("entity_id", "")
            state_val = s.get("state", "")
            attrs = s.get("attributes", {})

            # Fix 20: Mark invalid entities
            is_valid = state_val not in ("unavailable", "unknown", None, "")

            entities.append({
                "entity_id": eid,
                "friendly_name": attrs.get("friendly_name", eid),
                "state": state_val,
                "domain": eid.split(".")[0],
                "device_class": attrs.get("device_class", ""),
                "is_imported": eid in imported_ids,
                "is_valid": is_valid
            })

        return jsonify({"entities": entities, "total": len(entities)})
    finally:
        session.close()


# Fix 5: Manual device add
@app.route("/api/devices/manual-add", methods=["POST"])
def api_manual_add_device():
    """Manually add a device by entity ID."""
    data = request.json
    session = get_db()
    try:
        entity_id = data.get("entity_id", "").strip()
        if not entity_id:
            return jsonify({"error": "Entity ID is required"}), 400

        # Fix 19: Duplicate protection
        existing = session.query(Device).filter_by(ha_entity_id=entity_id).first()
        if existing:
            return jsonify({"error": "Device already exists", "device_id": existing.id}), 409

        # Get current state from HA
        state = ha.get_state(entity_id)
        if not state:
            return jsonify({"error": "Entity not found in Home Assistant"}), 404

        attrs = state.get("attributes", {})
        friendly_name = data.get("name") or attrs.get("friendly_name", entity_id)
        domain_id = data.get("domain_id")
        room_id = data.get("room_id")

        # Auto-detect domain if not provided
        if not domain_id:
            ha_domain = entity_id.split(".")[0]
            domain_mapping = {
                "light": "light", "climate": "climate", "cover": "cover",
                "person": "presence", "device_tracker": "presence",
                "media_player": "media", "lock": "lock", "switch": "switch",
                "fan": "ventilation", "weather": "weather"
            }
            mapped_name = domain_mapping.get(ha_domain, "switch")
            domain = session.query(Domain).filter_by(name=mapped_name).first()
            domain_id = domain.id if domain else 1

        # Auto-detect controllability from entity type
        ha_domain = entity_id.split(".")[0]
        non_controllable = {"sensor", "binary_sensor", "zone", "sun", "weather", "person", "device_tracker", "calendar", "proximity"}
        is_controllable = ha_domain not in non_controllable

        device = Device(
            ha_entity_id=entity_id,
            name=friendly_name,
            domain_id=domain_id,
            room_id=room_id,
            device_meta=attrs,
            is_controllable=is_controllable
        )
        session.add(device)
        session.commit()

        return jsonify({"success": True, "id": device.id, "name": device.name}), 201
    finally:
        session.close()


@app.route("/api/discover/areas", methods=["GET"])
def api_discover_areas():
    """Get areas (rooms) from HA."""
    areas = ha.get_areas()
    return jsonify({"areas": areas or []})


@app.route("/api/ha/persons", methods=["GET"])
def api_ha_persons():
    """Get all person entities from HA for user assignment."""
    states = ha.get_states() or []
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


# ==============================================================================
# API Routes - Users
# ==============================================================================

@app.route("/api/users", methods=["GET"])
def api_get_users():
    """Get all users."""
    session = get_db()
    try:
        users = session.query(User).filter_by(is_active=True).all()
        return jsonify([{
            "id": u.id,
            "name": u.name,
            "role": u.role.value,
            "ha_person_entity": u.ha_person_entity,
            "language": u.language,
            "created_at": u.created_at.isoformat()
        } for u in users])
    finally:
        session.close()


@app.route("/api/users", methods=["POST"])
def api_create_user():
    """Create a new user."""
    data = request.json
    session = get_db()
    try:
        user = User(
            name=data["name"],
            role=UserRole(data.get("role", "user")),
            ha_person_entity=data.get("ha_person_entity"),
            language=data.get("language", get_language())
        )
        session.add(user)
        session.commit()

        for ntype in NotificationType:
            ns = NotificationSetting(
                user_id=user.id,
                notification_type=ntype,
                is_enabled=True,
                quiet_hours_start="22:00",
                quiet_hours_end="07:00",
                quiet_hours_allow_critical=True
            )
            session.add(ns)
        session.commit()

        return jsonify({"id": user.id, "name": user.name}), 201
    finally:
        session.close()


@app.route("/api/users/<int:user_id>", methods=["PUT"])
def api_update_user(user_id):
    """Update a user."""
    data = request.json
    session = get_db()
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        if "name" in data:
            user.name = data["name"]
        if "role" in data:
            user.role = UserRole(data["role"])
        if "ha_person_entity" in data:
            user.ha_person_entity = data["ha_person_entity"]
        if "language" in data:
            user.language = data["language"]

        session.commit()
        return jsonify({"id": user.id, "name": user.name})
    finally:
        session.close()


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    """Delete a user (soft delete)."""
    session = get_db()
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        user.is_active = False
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


# ==============================================================================
# API Routes - Quick Actions
# ==============================================================================

@app.route("/api/quick-actions", methods=["GET"])
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


@app.route("/api/quick-actions/execute/<int:action_id>", methods=["POST"])
def api_execute_quick_action(action_id):
    """Execute a quick action."""
    session = get_db()
    try:
        action = session.get(QuickAction, action_id)
        if not action:
            return jsonify({"error": "Quick action not found"}), 404

        action_type = action.action_data.get("type")

        if action_type == "all_off":
            for entity in ha.get_entities_by_domain("light"):
                ha.call_service("light", "turn_off", entity_id=entity["entity_id"])
            for entity in ha.get_entities_by_domain("switch"):
                ha.call_service("switch", "turn_off", entity_id=entity["entity_id"])
            for entity in ha.get_entities_by_domain("media_player"):
                ha.call_service("media_player", "turn_off", entity_id=entity["entity_id"])

        elif action_type == "leaving_home":
            set_setting("system_mode", "away")
            for entity in ha.get_entities_by_domain("light"):
                ha.call_service("light", "turn_off", entity_id=entity["entity_id"])
            for entity in ha.get_entities_by_domain("climate"):
                ha.call_service("climate", "set_temperature",
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


@app.route("/api/quick-actions", methods=["POST"])
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


@app.route("/api/quick-actions/<int:action_id>", methods=["PUT"])
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


@app.route("/api/quick-actions/<int:action_id>", methods=["DELETE"])
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


# ==============================================================================
# API Routes - Data Dashboard (Privacy/Transparency)
# ==============================================================================

@app.route("/api/data-dashboard", methods=["GET"])
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


@app.route("/api/data-dashboard/delete/<int:collection_id>", methods=["DELETE"])
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


# ==============================================================================
# API Routes - Translations
# ==============================================================================

@app.route("/api/system/translations/<lang_code>", methods=["GET"])
def api_get_translations(lang_code):
    """Get translations for a language."""
    import json as json_lib
    lang_file = os.path.join(os.path.dirname(__file__), "translations", f"{lang_code}.json")
    try:
        with open(lang_file, "r", encoding="utf-8") as f:
            return jsonify(json_lib.load(f))
    except FileNotFoundError:
        return jsonify({"error": "Language not found"}), 404


# ==============================================================================
# API Routes - Onboarding
# ==============================================================================

@app.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Get onboarding status."""
    return jsonify({
        "completed": get_setting("onboarding_completed", "false") == "true"
    })


@app.route("/api/onboarding/complete", methods=["POST"])
def api_onboarding_complete():
    """Mark onboarding as complete."""
    set_setting("onboarding_completed", "true")
    return jsonify({"success": True})


# ==============================================================================
# API Routes - Action Log (with time filters)
# ==============================================================================

@app.route("/api/action-log", methods=["GET"])
def api_get_action_log():
    """Get action log with time filters."""
    session = get_db()
    try:
        limit = request.args.get("limit", 200, type=int)
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
        elif period == "week":
            start = now - timedelta(days=7)
            query = query.filter(ActionLog.created_at >= start)
        elif period == "month":
            start = now - timedelta(days=30)
            query = query.filter(ActionLog.created_at >= start)
        # "all" = no date filter

        logs = query.limit(limit).all()

        return jsonify([{
            "id": log.id,
            "action_type": log.action_type,
            "domain_id": log.domain_id,
            "room_id": log.room_id,
            "device_id": log.device_id,
            "action_data": log.action_data,
            "reason": log.reason,
            "was_undone": log.was_undone,
            "created_at": utc_iso(log.created_at)
        } for log in logs])
    finally:
        session.close()


@app.route("/api/action-log/<int:log_id>/undo", methods=["POST"])
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
                ha.call_service(domain, "turn_on", entity_id=prev["entity_id"])
            elif prev["state"] == "off":
                ha.call_service(domain, "turn_off", entity_id=prev["entity_id"])

        log.was_undone = True
        session.commit()

        return jsonify({"success": True})
    finally:
        session.close()


# ==============================================================================
# API Routes - Data Collections (with time filters)
# ==============================================================================

@app.route("/api/data-collections", methods=["GET"])
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


# ==============================================================================
# API Routes - Data Retention / Cleanup
# ==============================================================================

# Fix 3: Auto-Cleanup settings
@app.route("/api/system/retention", methods=["GET"])
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


@app.route("/api/system/retention", methods=["PUT"])
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


@app.route("/api/system/cleanup", methods=["POST"])
def api_manual_cleanup():
    """Manually trigger data cleanup."""
    deleted = run_cleanup()
    return jsonify({"success": True, "deleted_entries": deleted})


# ==============================================================================
# Phase 2a: Pattern API Endpoints
# ==============================================================================

@app.route("/api/patterns", methods=["GET"])
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

        patterns = query.limit(200).all()

        return jsonify([{
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
        } for p in patterns])
    finally:
        session.close()


@app.route("/api/patterns/<int:pattern_id>", methods=["PUT"])
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


@app.route("/api/patterns/<int:pattern_id>", methods=["DELETE"])
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


@app.route("/api/patterns/analyze", methods=["POST"])
def api_trigger_analysis():
    """Manually trigger pattern analysis."""
    pattern_scheduler.trigger_analysis_now()
    return jsonify({"success": True, "message": "Analysis started in background"})


@app.route("/api/patterns/reclassify-insights", methods=["POST"])
def api_reclassify_insights():
    """Reclassify existing sensorâ†’sensor patterns as 'insight'."""
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


# ==============================================================================
# Phase 2a: State History API
# ==============================================================================

@app.route("/api/state-history", methods=["GET"])
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


@app.route("/api/state-history/count", methods=["GET"])
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


# ==============================================================================
# Phase 2a: Learning Stats API
# ==============================================================================

@app.route("/api/stats/learning", methods=["GET"])
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


# ==============================================================================
# Phase 2b: Predictions / Suggestions API
# ==============================================================================

@app.route("/api/predictions", methods=["GET"])
def api_get_predictions():
    """Get suggestions/predictions with filters."""
    session = get_db()
    try:
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
    finally:
        session.close()


@app.route("/api/predictions/<int:pred_id>/confirm", methods=["POST"])
def api_confirm_prediction(pred_id):
    """Confirm a suggestion."""
    result = automation_scheduler.feedback.confirm_prediction(pred_id)
    return jsonify(result)


@app.route("/api/predictions/<int:pred_id>/reject", methods=["POST"])
def api_reject_prediction(pred_id):
    """Reject a suggestion."""
    result = automation_scheduler.feedback.reject_prediction(pred_id)
    return jsonify(result)


@app.route("/api/predictions/<int:pred_id>/ignore", methods=["POST"])
def api_ignore_prediction(pred_id):
    """Ignore / postpone a suggestion."""
    result = automation_scheduler.feedback.ignore_prediction(pred_id)
    return jsonify(result)


@app.route("/api/predictions/<int:pred_id>/undo", methods=["POST"])
def api_undo_prediction(pred_id):
    """Undo an executed automation."""
    result = automation_scheduler.executor.undo_prediction(pred_id)
    return jsonify(result)


# ==============================================================================
# Phase 2b: Automation API
# ==============================================================================

@app.route("/api/automation/emergency-stop", methods=["POST"])
def api_automation_emergency_stop():
    """Activate/deactivate emergency stop for all automations."""
    data = request.json or {}
    active = data.get("active", True)
    automation_scheduler.executor.set_emergency_stop(active)

    # Also update system mode
    set_setting("system_mode", "emergency_stop" if active else "normal")

    return jsonify({"success": True, "emergency_stop": active})


@app.route("/api/automation/conflicts", methods=["GET"])
def api_get_conflicts():
    """Get detected pattern conflicts."""
    conflicts = automation_scheduler.conflict_det.check_conflicts()
    return jsonify(conflicts)


@app.route("/api/automation/generate-suggestions", methods=["POST"])
def api_generate_suggestions():
    """Manually trigger suggestion generation."""
    count = automation_scheduler.suggestion_gen.generate_suggestions()
    return jsonify({"success": True, "new_suggestions": count})


# ==============================================================================
# Phase 2b: Phase Management API
# ==============================================================================

@app.route("/api/phases", methods=["GET"])
def api_get_phases():
    """Get learning phases for all room/domain combinations."""
    session = get_db()
    try:
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
    finally:
        session.close()


@app.route("/api/phases/<int:room_id>/<int:domain_id>", methods=["PUT"])
def api_set_phase(room_id, domain_id):
    """Manually set learning phase for a room/domain."""
    data = request.json or {}
    if "phase" in data:
        result = automation_scheduler.phase_mgr.set_phase_manual(room_id, domain_id, data["phase"])
        return jsonify(result)
    if "is_paused" in data:
        result = automation_scheduler.phase_mgr.set_paused(room_id, domain_id, data["is_paused"])
        return jsonify(result)
    return jsonify({"error": "Provide 'phase' or 'is_paused'"}), 400


# ==============================================================================
# Phase 2b: Notifications API
# ==============================================================================

@app.route("/api/notifications", methods=["GET"])
def api_get_notifications():
    """Get notifications."""
    lang = get_language()
    unread = request.args.get("unread", "false").lower() == "true"
    limit = request.args.get("limit", 50, type=int)

    notifs = automation_scheduler.notification_mgr.get_notifications(limit, unread)
    return jsonify([{
        "id": n.id,
        "type": n.notification_type.value if n.notification_type else "info",
        "title": n.title,
        "message": n.message,
        "was_sent": n.was_sent,
        "was_read": n.was_read,
        "created_at": utc_iso(n.created_at),
    } for n in notifs])


@app.route("/api/notifications/unread-count", methods=["GET"])
def api_notifications_unread_count():
    """Get unread notification count."""
    count = automation_scheduler.notification_mgr.get_unread_count()
    return jsonify({"unread_count": count})


@app.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
def api_mark_notification_read(notif_id):
    """Mark notification as read."""
    success = automation_scheduler.notification_mgr.mark_read(notif_id)
    return jsonify({"success": success})


@app.route("/api/notifications/mark-all-read", methods=["POST"])
def api_mark_all_read():
    """Mark all notifications as read."""
    success = automation_scheduler.notification_mgr.mark_all_read()
    return jsonify({"success": success})


@app.route("/api/automation/anomalies", methods=["GET"])
def api_get_anomalies():
    """Get recent anomalies."""
    anomalies = automation_scheduler.anomaly_det.check_recent_anomalies(minutes=60)
    return jsonify(anomalies)


# ==============================================================================
# Frontend Serving
# ==============================================================================

@app.route("/")
def serve_index():
    """Serve index.html with app.jsx inlined to avoid Ingress XHR issues."""
    frontend_dir = os.path.join(app.static_folder, "frontend")
    index_path = os.path.join(frontend_dir, "index.html")
    jsx_path = os.path.join(frontend_dir, "app.jsx")

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        with open(jsx_path, "r", encoding="utf-8") as f:
            jsx_code = f.read()

        logger.info(f"Serving frontend: app.jsx has {len(jsx_code.splitlines())} lines, first line: {jsx_code.splitlines()[0][:60] if jsx_code else 'EMPTY'}")

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

@app.route("/api/system/hot-update", methods=["POST"])
def hot_update_frontend():
    """Hot-update frontend file (app.jsx) without rebuild."""
    data = request.json
    if not data or "content" not in data or "filename" not in data:
        return jsonify({"error": "need content and filename"}), 400
    filename = data["filename"]
    if filename not in ("app.jsx", "index.html"):
        return jsonify({"error": "only app.jsx and index.html allowed"}), 400
    filepath = os.path.join(app.static_folder, "frontend", filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(data["content"])
        logger.info(f"Hot-updated {filename} ({len(data['content'])} chars)")
        return jsonify({"success": True, "size": len(data["content"])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the React frontend files."""
    # Skip API routes
    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    # Strip frontend/ prefix if present (to avoid double-nesting)
    if path.startswith("frontend/"):
        path = path[len("frontend/"):]
    if path and os.path.exists(os.path.join(app.static_folder, "frontend", path)):
        response = send_from_directory(os.path.join(app.static_folder, "frontend"), path)
        # Fix MIME type for .jsx files (Babel XHR needs text/javascript)
        if path.endswith(".jsx"):
            response.headers["Content-Type"] = "text/javascript; charset=utf-8"
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    return send_from_directory(os.path.join(app.static_folder, "frontend"), "index.html")


# ==============================================================================
# ==============================================================================
# Block B: Notification Settings (complete)
# ==============================================================================

@app.route("/api/notification-settings", methods=["GET"])
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


@app.route("/api/notification-settings", methods=["PUT"])
def api_update_notification_settings():
    """Update notification settings."""
    data = request.json
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
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/notification-settings/dnd", methods=["PUT"])
def api_toggle_dnd():
    """Toggle Do-Not-Disturb mode."""
    data = request.json
    set_setting("dnd_enabled", "true" if data.get("enabled") else "false")
    return jsonify({"success": True, "dnd_enabled": data.get("enabled", False)})


@app.route("/api/notification-settings/mute-device", methods=["POST"])
def api_mute_device():
    """Mute notifications for a specific device."""
    data = request.json
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
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/notification-settings/unmute-device/<int:mute_id>", methods=["DELETE"])
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


@app.route("/api/notification-settings/discover-channels", methods=["POST"])
@app.route("/api/notification-settings/scan-channels", methods=["POST"])
def api_discover_notification_channels():
    """Discover available HA notification services."""
    session = get_db()
    try:
        services = ha.get_services()
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
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/notification-stats", methods=["GET"])
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


@app.route("/api/notification-settings/channel/<int:cid>", methods=["PUT"])
def api_update_notification_channel(cid):
    """Update a notification channel (enable/disable)."""
    data = request.get_json() or {}
    session = Session()
    try:
        ch = session.query(NotificationChannel).get(cid)
        if not ch:
            return jsonify({"error": "Channel not found"}), 404
        if "is_enabled" in data:
            ch.is_enabled = data["is_enabled"]
        if "display_name" in data:
            ch.display_name = data["display_name"]
        session.commit()
        return jsonify({"success": True, "id": ch.id, "is_enabled": ch.is_enabled})
    finally:
        session.close()


@app.route("/api/notification-settings/test-channel/<int:cid>", methods=["POST"])
def api_test_notification_channel(cid):
    """Send a test notification to a specific channel."""
    session = Session()
    try:
        ch = session.query(NotificationChannel).get(cid)
        if not ch:
            return jsonify({"error": "Channel not found"}), 404
        result = ha.send_notification("MindHome Test", title="Test", target=ch.service_name)
        return jsonify({"success": result is not None})
    finally:
        session.close()


@app.route("/api/test-notification", methods=["POST"])
def api_test_notification():
    """Send a test push notification to a specific channel."""
    data = request.get_json() or {}
    target = data.get("target", "notify")
    message = data.get("message", "MindHome Test Notification")
    title = data.get("title", "MindHome Test")
    result = ha.send_notification(message, title=title, target=target)
    audit_log("test_notification", {"target": target})
    return jsonify({"success": result is not None, "target": target})


# ==============================================================================
# Block B: Pattern Management (exclusions, rejections, manual rules)
# ==============================================================================

@app.route("/api/patterns/reject/<int:pattern_id>", methods=["PUT"])
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


@app.route("/api/patterns/reactivate/<int:pattern_id>", methods=["PUT"])
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


@app.route("/api/patterns/rejected", methods=["GET"])
def api_get_rejected_patterns():
    """Get all rejected patterns."""
    session = get_db()
    try:
        patterns = session.query(LearnedPattern).filter_by(status="rejected").order_by(
            LearnedPattern.rejected_at.desc()
        ).all()
        lang = get_language()
        return jsonify([{
            "id": p.id, "pattern_type": p.pattern_type,
            "description": p.description_de if lang == "de" else p.description_en,
            "confidence": p.confidence, "rejection_reason": p.rejection_reason,
            "rejected_at": p.rejected_at.isoformat() if p.rejected_at else None,
            "category": p.category,
        } for p in patterns])
    finally:
        session.close()


@app.route("/api/patterns/test-mode/<int:pattern_id>", methods=["PUT"])
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


@app.route("/api/pattern-exclusions", methods=["GET"])
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


@app.route("/api/pattern-exclusions", methods=["POST"])
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


@app.route("/api/pattern-exclusions/<int:excl_id>", methods=["DELETE"])
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


@app.route("/api/manual-rules", methods=["GET"])
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


@app.route("/api/manual-rules", methods=["POST"])
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


@app.route("/api/manual-rules/<int:rule_id>", methods=["PUT"])
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


@app.route("/api/manual-rules/<int:rule_id>", methods=["DELETE"])
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


# ==============================================================================
# Block B: Anomaly Settings
# ==============================================================================

@app.route("/api/anomaly-settings", methods=["GET"])
def api_get_anomaly_settings():
    """Get anomaly detection settings."""
    session = get_db()
    try:
        settings = session.query(AnomalySetting).all()
        return jsonify([{
            "id": s.id, "room_id": s.room_id, "domain_id": s.domain_id,
            "device_id": s.device_id, "sensitivity": s.sensitivity,
            "stuck_detection": s.stuck_detection, "time_anomaly": s.time_anomaly,
            "frequency_anomaly": s.frequency_anomaly,
            "whitelisted_hours": s.whitelisted_hours,
            "auto_action": s.auto_action,
        } for s in settings])
    finally:
        session.close()


@app.route("/api/anomaly-settings", methods=["POST"])
def api_create_anomaly_setting():
    """Create or update anomaly setting."""
    data = request.json
    session = get_db()
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
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ==============================================================================
# Block B: Validation & Learning Phase extensions
# ==============================================================================

@app.route("/api/validate-config", methods=["GET"])
def api_validate_config():
    """Validate MindHome configuration - find issues."""
    session = get_db()
    try:
        issues = []
        # Devices without room
        orphan_devices = session.query(Device).filter(Device.room_id == None, Device.is_tracked == True).count()
        if orphan_devices > 0:
            issues.append({"type": "warning", "key": "orphan_devices",
                "message_de": f"{orphan_devices} Ã¼berwachte GerÃ¤te ohne Raum-Zuweisung",
                "message_en": f"{orphan_devices} tracked devices without room assignment"})

        # Rooms without devices
        for room in session.query(Room).filter_by(is_active=True).all():
            dev_count = session.query(Device).filter_by(room_id=room.id).count()
            if dev_count == 0:
                issues.append({"type": "info", "key": "empty_room",
                    "message_de": f"Raum '{room.name}' hat keine GerÃ¤te",
                    "message_en": f"Room '{room.name}' has no devices"})

        # Domains enabled but no devices
        for domain in session.query(Domain).filter_by(is_enabled=True).all():
            dev_count = session.query(Device).filter_by(domain_id=domain.id, is_tracked=True).count()
            if dev_count == 0:
                issues.append({"type": "info", "key": "empty_domain",
                    "message_de": f"Domain '{domain.display_name_de}' aktiv aber keine GerÃ¤te zugewiesen",
                    "message_en": f"Domain '{domain.display_name_en}' active but no devices assigned"})

        # HA connection
        if not ha.connected:
            issues.append({"type": "error", "key": "ha_disconnected",
                "message_de": "Home Assistant nicht verbunden",
                "message_en": "Home Assistant not connected"})

        return jsonify({"valid": len([i for i in issues if i["type"] == "error"]) == 0, "issues": issues})
    finally:
        session.close()


@app.route("/api/phases/<int:room_id>/<int:domain_id>/progress", methods=["GET"])
def api_phase_progress(room_id, domain_id):
    """Get learning phase progress details."""
    session = get_db()
    try:
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
    finally:
        session.close()


@app.route("/api/phases/speed", methods=["PUT"])
def api_set_learning_speed():
    """Set global learning speed."""
    data = request.json
    speed = data.get("speed", "normal")  # "conservative", "normal", "aggressive"
    set_setting("learning_speed", speed)
    return jsonify({"success": True, "speed": speed})


@app.route("/api/phases/<int:room_id>/<int:domain_id>/reset", methods=["POST"])
def api_reset_phase(room_id, domain_id):
    """Reset learning for a room+domain - delete patterns and restart."""
    session = get_db()
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
            "message": "Lernphase zurÃ¼ckgesetzt" if lang == "de" else "Learning phase reset"})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ==============================================================================
# Block B.9: Weekly Report & Energy Estimate
# ==============================================================================

@app.route("/api/report/weekly", methods=["GET"])
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


# ==============================================================================
# Backup / Restore
# ==============================================================================

@app.route("/api/backup/export", methods=["GET"])
def api_backup_export():
    """Export MindHome data as JSON. mode=standard|full|custom"""
    mode = request.args.get("mode", "standard")
    history_days = request.args.get("history_days", 90, type=int)
    session = get_db()
    try:
        backup = {
            "version": "0.5.0",
            "export_mode": mode,
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
            backup["notification_settings"].append({
                "user_id": ns.user_id,
                "notification_type": ns.notification_type.value if hasattr(ns.notification_type, 'value') else str(ns.notification_type),
                "is_enabled": ns.is_enabled,
                "priority": ns.priority.value if hasattr(ns.priority, 'value') else str(ns.priority) if ns.priority else "medium",
                "push_channel": getattr(ns, 'push_channel', None),
                "quiet_hours_start": ns.quiet_hours_start,
                "quiet_hours_end": ns.quiet_hours_end,
                "escalation_enabled": getattr(ns, 'escalation_enabled', False),
            })
        # Notification channels
        for nc in session.query(NotificationChannel).all():
            backup["notification_channels"].append({"id": nc.id,
                "service_name": nc.service_name, "display_name": nc.display_name,
                "channel_type": nc.channel_type, "is_enabled": nc.is_enabled})
        # Device mutes
        for dm in session.query(DeviceMute).all():
            backup["device_mutes"].append({"id": dm.id, "device_id": dm.device_id,
                "user_id": dm.user_id,
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

        # Full/Custom mode: include historical data
        if mode in ("full", "custom", "standard"):
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
                    "notification_type": nl.notification_type, "title": nl.title,
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
            for dc in session.query(DataCollection).all():
                backup["data_collection"].append({"room_id": dc.room_id, "domain_id": dc.domain_id,
                    "data_type": dc.data_type, "record_count": dc.record_count,
                    "storage_size_bytes": dc.storage_size_bytes,
                    "first_record_at": utc_iso(dc.first_record_at) if dc.first_record_at else None,
                    "last_record_at": utc_iso(dc.last_record_at) if dc.last_record_at else None})

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
        }

        return jsonify(backup)
    finally:
        session.close()


@app.route("/api/backup/import", methods=["POST"])
def api_backup_import():
    """Import MindHome configuration from JSON backup."""
    data = request.json
    if not data or "version" not in data:
        return jsonify({"error": "Invalid backup file"}), 400
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
        except:
            pass
        logger.error(f"Backup import failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ==============================================================================
# New v0.5.0 API Endpoints
# ==============================================================================

# #24 Device Health Check
@app.route("/api/device-health", methods=["GET"])
def api_device_health():
    """Check all devices for health issues (battery, unreachable)."""
    try:
        issues = ha.check_device_health()
        return jsonify({"issues": issues, "total": len(issues)})
    except Exception as e:
        logger.error(f"Device health check error: {e}")
        return jsonify({"issues": [], "total": 0, "error": str(e)})


# #42 Debug Mode
@app.route("/api/system/debug", methods=["GET"])
def api_get_debug():
    """Get debug mode status."""
    try:
        return jsonify({"debug_mode": is_debug_mode()})
    except Exception as e:
        return jsonify({"debug_mode": False, "error": str(e)})

@app.route("/api/system/debug", methods=["PUT"])
def api_toggle_debug():
    """Toggle debug mode."""
    try:
        global _debug_mode
        _debug_mode = not _debug_mode
        level = logging.DEBUG if _debug_mode else logging.INFO
        logging.getLogger("mindhome").setLevel(level)
        audit_log("debug_mode_toggle", {"enabled": _debug_mode})
        return jsonify({"debug_mode": _debug_mode})
    except Exception as e:
        return jsonify({"debug_mode": False, "error": str(e)}), 500


# #38 Frontend Error Reporting
@app.route("/api/system/frontend-error", methods=["POST"])
def api_frontend_error():
    """Log frontend errors for debugging."""
    try:
        data = request.get_json() or {}
        logger.error(f"Frontend error: {data.get('error', 'unknown')} | {data.get('stack', '')[:200]}")
        return jsonify({"logged": True})
    except Exception:
        return jsonify({"logged": False})


# #23 Vacation Mode
@app.route("/api/system/vacation-mode", methods=["GET"])
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

@app.route("/api/system/vacation-mode", methods=["PUT"])
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


# #28 Calendar Events
@app.route("/api/calendar/upcoming", methods=["GET"])
def api_upcoming_events():
    """Get upcoming calendar events from HA."""
    try:
        hours = int(request.args.get("hours", 24))
        events = ha.get_upcoming_events(hours=hours)
        return jsonify({"events": events})
    except Exception as e:
        logger.warning(f"Calendar events error: {e}")
        return jsonify({"events": [], "error": str(e)})


# #26 Pattern Conflict Detection
@app.route("/api/patterns/conflicts", methods=["GET"])
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
@app.route("/api/patterns/scenes", methods=["GET"])
def api_detect_scenes():
    """Detect groups of devices that are often switched together â†’ suggest scenes."""
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
                    "message_de": f"{len(entities)} GerÃ¤te werden oft zusammen geschaltet ({count}Ã—)",
                    "message_en": f"{len(entities)} devices are often switched together ({count}Ã—)",
                })
            if len(scenes) >= 10:
                break

        return jsonify({"scenes": scenes})
    except Exception as e:
        logger.error(f"Scene detection error: {e}")
        return jsonify({"scenes": [], "error": str(e)})
    finally:
        session.close()
@app.route("/api/energy/summary", methods=["GET"])
def api_energy_summary():
    """Get energy usage summary from tracked power sensors."""
    session = get_db()
    try:
        days = int(request.args.get("days", 7))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Find energy-related state history
        energy_entities = session.query(StateHistory.entity_id).filter(
            StateHistory.entity_id.like("sensor.%energy%") |
            StateHistory.entity_id.like("sensor.%power%"),
            StateHistory.created_at > cutoff
        ).distinct().all()

        entity_ids = [e[0] for e in energy_entities]
        summary = {"entities": [], "total_entries": 0, "days": days}

        for eid in entity_ids[:20]:
            count = session.query(sa_func.count(StateHistory.id)).filter(
                StateHistory.entity_id == eid,
                StateHistory.created_at > cutoff
            ).scalar()
            summary["entities"].append({"entity_id": eid, "data_points": count})
            summary["total_entries"] += count

        # Automation energy savings estimate
        auto_count = session.query(sa_func.count(ActionLog.id)).filter(
            ActionLog.action_type == "automation_executed",
            ActionLog.created_at > cutoff,
            ActionLog.new_value.like("%off%")
        ).scalar() or 0
        summary["automations_off_count"] = auto_count
        summary["estimated_kwh_saved"] = round(auto_count * 0.06, 2)

        return jsonify(summary)
    except Exception as e:
        logger.error(f"Energy summary error: {e}")
        return jsonify({"error": str(e), "entities": []})
    finally:
        session.close()
@app.route("/api/export/<data_type>", methods=["GET"])
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
            data = [{"type": a.action_type, "device": a.device_name,
                      "old": a.old_value, "new": a.new_value,
                      "reason": a.reason, "created": str(a.created_at)} for a in items]
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
@app.route("/api/system/diagnose", methods=["GET"])
def api_diagnose():
    """Generate diagnostic info (no passwords/tokens)."""
    session = get_db()
    try:
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")
        diag = {
            "version": "0.5.0",
            "python": sys.version.split()[0],
            "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
            "ha_connected": ha.is_connected(),
            "connection_stats": ha.get_connection_stats(),
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
            "ha_entities": len(ha.get_states() or []),
            "debug_mode": is_debug_mode(),
            "vacation_mode": get_setting("vacation_mode", "false"),
            "device_health_issues": len(ha.check_device_health()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return jsonify(diag)
    except Exception as e:
        logger.error(f"Diagnose error: {e}")
        return jsonify({"error": str(e), "version": "0.5.0"})
    finally:
        session.close()
@app.route("/api/system/check-update", methods=["GET"])
def api_check_update():
    """Check if a newer version is available."""
    try:
        current = "0.5.0"
        return jsonify({
            "current_version": current,
            "update_available": False,
            "message": "Update check requires network access to GitHub.",
        })
    except Exception as e:
        return jsonify({"current_version": "0.5.0", "error": str(e)})


# #44 Device Groups - FULL CRUD
@app.route("/api/device-groups", methods=["GET"])
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


@app.route("/api/device-groups", methods=["POST"])
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


@app.route("/api/device-groups/<int:group_id>", methods=["PUT"])
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


@app.route("/api/device-groups/<int:group_id>", methods=["DELETE"])
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


@app.route("/api/device-groups/<int:group_id>/execute", methods=["POST"])
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
                result = ha.call_service(domain_part, service, {"entity_id": device.ha_entity_id})
                results.append({"entity_id": device.ha_entity_id, "success": result is not None})
        audit_log("device_group_execute", {"group_id": group_id, "service": service, "count": len(results)})
        return jsonify({"success": True, "results": results})
    finally:
        session.close()


# ==============================================================================
# #60 Audit Trail - FULL API
# ==============================================================================

@app.route("/api/audit-trail", methods=["GET"])
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


def write_audit(action, target=None, details=None):
    """Write an audit trail entry."""
    session = get_db()
    try:
        entry = AuditTrail(
            action=action, target=target,
            details=json.dumps(details) if isinstance(details, dict) else details,
            ip_address=request.remote_addr if request else None,
        )
        session.add(entry)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Audit write error: {e}")
    finally:
        session.close()


# ==============================================================================
# #40 Watchdog Timer
# ==============================================================================

_watchdog_status = {"last_check": None, "ha_alive": False, "db_alive": False, "issues": []}


def _watchdog_loop():
    """Periodic system health check every 60 seconds."""
    global _watchdog_status
    while True:
        issues = []
        # Check HA connection
        ha_alive = ha.is_connected() if ha else False
        if not ha_alive:
            issues.append("HA WebSocket disconnected")
        # Check DB
        db_alive = False
        try:
            session = get_db()
            session.execute(text("SELECT 1"))
            db_alive = True
            session.close()
        except Exception:
            issues.append("Database unreachable")
        # Check disk space
        try:
            stat = os.statvfs("/data" if os.path.exists("/data") else "/")
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            if free_gb < 0.5:
                issues.append(f"Low disk space: {free_gb:.1f} GB")
        except Exception:
            pass
        # Check memory
        try:
            import resource
            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            if mem_mb > 500:
                issues.append(f"High memory usage: {mem_mb:.0f} MB")
        except Exception:
            pass

        _watchdog_status = {
            "last_check": datetime.now(timezone.utc).isoformat(),
            "ha_alive": ha_alive, "db_alive": db_alive,
            "issues": issues, "healthy": len(issues) == 0,
        }
        time.sleep(60)


@app.route("/api/system/watchdog", methods=["GET"])
def api_watchdog():
    """Get watchdog status."""
    return jsonify(_watchdog_status)


# ==============================================================================
# #10 Startup Self-Test
# ==============================================================================

def run_startup_self_test():
    """Run startup checks and return results."""
    results = []
    # Test DB
    try:
        session = get_db()
        session.execute(text("SELECT 1"))
        session.close()
        results.append({"test": "database", "status": "ok"})
    except Exception as e:
        results.append({"test": "database", "status": "fail", "error": str(e)})
    # Test HA
    try:
        connected = ha.is_connected() if ha else False
        results.append({"test": "ha_connection", "status": "ok" if connected else "warn", "connected": connected})
    except Exception as e:
        results.append({"test": "ha_connection", "status": "fail", "error": str(e)})
    # Test tables exist
    try:
        session = get_db()
        for table in ["devices", "rooms", "domains", "users", "learned_patterns", "state_history"]:
            session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        session.close()
        results.append({"test": "tables", "status": "ok"})
    except Exception as e:
        results.append({"test": "tables", "status": "fail", "error": str(e)})
    # Test write
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
    logger.info(f"Self-test: {'PASSED' if all_ok else 'ISSUES FOUND'} - {results}")
    return {"passed": all_ok, "tests": results}


@app.route("/api/system/self-test", methods=["GET"])
def api_self_test():
    """Run self-test and return results."""
    return jsonify(run_startup_self_test())


# ==============================================================================
# #15b Offline Action Queue
# ==============================================================================

@app.route("/api/offline-queue", methods=["GET"])
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


@app.route("/api/offline-queue", methods=["POST"])
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


def process_offline_queue():
    """Process queued actions when HA reconnects."""
    if not ha or not ha.is_connected():
        return 0
    session = get_db()
    try:
        items = session.query(OfflineActionQueue).filter_by(was_executed=False).order_by(OfflineActionQueue.priority.desc()).all()
        executed = 0
        for item in items:
            try:
                ad = item.action_data or {}
                domain = ad.get("domain", "homeassistant")
                service = ad.get("service", "toggle")
                entity_id = ad.get("entity_id")
                if entity_id:
                    ha.call_service(domain, service, {"entity_id": entity_id})
                item.was_executed = True
                item.executed_at = datetime.now(timezone.utc)
                executed += 1
            except Exception as e:
                logger.error(f"Offline queue exec error: {e}")
        session.commit()
        if executed:
            logger.info(f"Processed {executed} offline queued actions")
        return executed
    finally:
        session.close()


# ==============================================================================
# #30 TTS Announcements
# ==============================================================================

@app.route("/api/tts/announce", methods=["POST"])
def api_tts_announce():
    """Send a TTS announcement via HA."""
    data = request.json
    message = data.get("message", "")
    entity = data.get("entity_id")
    tts_service = data.get("tts_service") or get_setting("tts_service")
    if not message:
        return jsonify({"error": "No message"}), 400
    result = ha.announce_tts(message, media_player_entity=entity, tts_service=tts_service)
    audit_log("tts_announce", {"message": message[:50], "entity": entity, "tts_service": tts_service})
    return jsonify({"success": result is not None})


@app.route("/api/tts/services", methods=["GET"])
def api_tts_services():
    """Get available TTS services from HA."""
    try:
        services = ha.get_services()
        tts_services = []
        for svc in services:
            if svc.get("domain") == "tts":
                for name in svc.get("services", {}).keys():
                    tts_services.append({"service": f"tts.{name}", "name": name.replace("_", " ").title()})
        current = get_setting("tts_service")
        return jsonify({"services": tts_services, "current": current})
    except Exception as e:
        return jsonify({"services": [], "error": str(e)})


@app.route("/api/tts/service", methods=["PUT"])
def api_set_tts_service():
    """Set preferred TTS service."""
    data = request.get_json() or {}
    service = data.get("service", "")
    set_setting("tts_service", service)
    return jsonify({"success": True, "service": service})


@app.route("/api/tts/devices", methods=["GET"])
def api_tts_devices():
    """Get available media players for TTS."""
    states = ha.get_states() or []
    players = [{"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
               for s in states if s["entity_id"].startswith("media_player.")]
    return jsonify(players)


# ==============================================================================
# ==============================================================================
# #28b Calendar Automation Triggers
# ==============================================================================

@app.route("/api/calendar/triggers", methods=["GET"])
def api_get_calendar_triggers():
    """Get calendar-based automation triggers."""
    session = get_db()
    try:
        triggers = []
        raw = get_setting("calendar_triggers")
        if raw:
            triggers = json.loads(raw)
        return jsonify(triggers)
    finally:
        session.close()


@app.route("/api/calendar/triggers", methods=["POST"])
def api_create_calendar_trigger():
    """Create a calendar-based automation trigger."""
    data = request.json
    triggers = json.loads(get_setting("calendar_triggers") or "[]")
    trigger = {
        "id": str(int(time.time() * 1000)),
        "keyword": data.get("keyword", ""),
        "action": data.get("action", ""),
        "entity_id": data.get("entity_id"),
        "service": data.get("service", "turn_on"),
        "is_active": True,
    }
    triggers.append(trigger)
    set_setting("calendar_triggers", json.dumps(triggers))
    audit_log("calendar_trigger_create", trigger)
    return jsonify({"success": True, "trigger": trigger})


@app.route("/api/calendar/triggers/<trigger_id>", methods=["DELETE"])
def api_delete_calendar_trigger(trigger_id):
    """Delete a calendar trigger."""
    triggers = json.loads(get_setting("calendar_triggers") or "[]")
    triggers = [t for t in triggers if t.get("id") != trigger_id]
    set_setting("calendar_triggers", json.dumps(triggers))
    return jsonify({"success": True})


# Alias endpoints with hyphen
@app.route("/api/calendar-triggers", methods=["GET"])
def api_get_calendar_triggers_alias():
    return api_get_calendar_triggers()


@app.route("/api/calendar-triggers", methods=["PUT"])
def api_update_calendar_triggers_alias():
    """Bulk update calendar triggers."""
    data = request.json
    set_setting("calendar_triggers", json.dumps(data.get("triggers", [])))
    return jsonify({"success": True})


# Also need an entities endpoint filtered by domain
@app.route("/api/ha/entities", methods=["GET"])
def api_get_ha_entities():
    """Get HA entities filtered by domain."""
    domain_filter = request.args.get("domain")
    all_states = ha.get_states() or []
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


# ==============================================================================
# #12b Extended Notification Settings
# ==============================================================================

@app.route("/api/notification-settings/extended", methods=["GET"])
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
    })


@app.route("/api/notification-settings/extended", methods=["PUT"])
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
        "device_thresholds",
    ]
    for key in setting_keys:
        if key in data:
            set_setting(f"notif_{key}", json.dumps(data[key]))
    if "battery_threshold" in data:
        set_setting("notif_battery_threshold", str(data["battery_threshold"]))
    return jsonify({"success": True})


# ==============================================================================
# Anomaly Settings Extended (27 features - advanced mode only)
# ==============================================================================

@app.route("/api/anomaly-settings/extended", methods=["GET"])
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


@app.route("/api/anomaly-settings/extended", methods=["PUT"])
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


@app.route("/api/anomaly-settings/pause", methods=["POST"])
def api_pause_anomaly():
    """Temporarily pause anomaly detection."""
    data = request.json
    hours = data.get("hours", 1)
    until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    set_setting("anomaly_paused_until", until)
    return jsonify({"success": True, "paused_until": until})


@app.route("/api/anomaly-settings/reset-baseline", methods=["POST"])
def api_reset_anomaly_baseline():
    """Reset anomaly baseline - system re-learns what's normal."""
    set_setting("anomaly_learning_mode", json.dumps({"enabled": True, "days_remaining": 7, "started_at": datetime.now(timezone.utc).isoformat()}))
    return jsonify({"success": True, "message": "Baseline reset, learning for 7 days"})


@app.route("/api/anomaly-settings/stats", methods=["GET"])
def api_anomaly_stats():
    """Get anomaly statistics for dashboard."""
    session = get_db()
    try:
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
    finally:
        session.close()


@app.route("/api/anomaly-settings/device/<int:device_id>", methods=["GET"])
def api_get_device_anomaly_config(device_id):
    """Get anomaly config for a specific device."""
    config = json.loads(get_setting(f"anomaly_device_{device_id}") or "null")
    if not config:
        config = {"sensitivity": "inherit", "enabled": True, "detection_types": {},
                  "thresholds": {}, "reaction": "inherit", "whitelisted": False}
    return jsonify(config)


@app.route("/api/anomaly-settings/device/<int:device_id>", methods=["PUT"])
def api_update_device_anomaly_config(device_id):
    """Update anomaly config for a specific device."""
    data = request.json
    current = json.loads(get_setting(f"anomaly_device_{device_id}") or "{}")
    current.update(data)
    set_setting(f"anomaly_device_{device_id}", json.dumps(current))
    return jsonify({"success": True})


@app.route("/api/anomaly-settings/devices", methods=["GET"])
def api_get_all_device_anomaly_configs():
    """Get all device-specific anomaly configs."""
    session = get_db()
    try:
        configs = {}
        settings = session.query(SystemSetting).filter(
            SystemSetting.key.like("anomaly_device_%")
        ).all()
        for s in settings:
            device_id = s.key.replace("anomaly_device_", "")
            try:
                configs[device_id] = json.loads(s.value)
            except:
                pass
        return jsonify(configs)
    finally:
        session.close()


# State Change Logging
# ==============================================================================

def log_state_change(entity_id, new_state, old_state, new_attrs=None, old_attrs=None):
    """Log state changes to action_log for tracked devices. Fix 1 + Fix 18 + Phase3B dedup."""
    session = get_db()
    try:
        device = session.query(Device).filter_by(ha_entity_id=entity_id).first()
        if not device or not device.is_tracked:
            return

        # Phase 3B: Deduplicate - check if same entity+state was logged in last 3 seconds
        from sqlalchemy import and_
        recent_cutoff = datetime.now(timezone.utc) - timedelta(seconds=3)
        existing = session.query(ActionLog).filter(
            and_(
                ActionLog.device_id == device.id,
                ActionLog.created_at >= recent_cutoff,
                ActionLog.action_type == "observation"
            )
        ).first()
        if existing:
            ex_data = existing.action_data or {}
            if ex_data.get("new_state") == new_state and ex_data.get("old_state") == old_state:
                return  # Skip duplicate

        # Fix 18: Enforce privacy mode
        if device.room_id:
            room = session.get(Room, device.room_id)
            if room and room.privacy_mode:
                # Get domain name
                domain = session.get(Domain, device.domain_id)
                domain_name = domain.name if domain else ""

                # Check if this domain is blocked in privacy mode
                if room.privacy_mode.get(domain_name) is False:
                    logger.debug(f"Privacy: Skipping {entity_id} in {room.name} (domain {domain_name} blocked)")
                    return

                # Check specific features
                device_class = (new_attrs or {}).get("device_class", "")
                if room.privacy_mode.get(device_class) is False:
                    logger.debug(f"Privacy: Skipping {entity_id} in {room.name} (feature {device_class} blocked)")
                    return

        # Fix 1: Extract display attributes
        new_display = extract_display_attributes(entity_id, new_attrs or {})
        old_display = extract_display_attributes(entity_id, old_attrs or {})

        reason = build_state_reason(device.name, old_state, new_state, new_display)

        action_log = ActionLog(
            action_type="observation",
            domain_id=device.domain_id,
            room_id=device.room_id,
            device_id=device.id,
            action_data={
                "entity_id": entity_id,
                "old_state": old_state,
                "new_state": new_state,
                "new_attributes": new_display,
                "old_attributes": old_display,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            reason=reason
        )
        session.add(action_log)
        session.commit()
    except Exception as e:
        logger.debug(f"Data collection error: {e}")
        try:
            session.rollback()
        except:
            pass
    finally:
        session.close()


# ==============================================================================
# Fix 3: Auto-Cleanup System
# ==============================================================================

def run_cleanup():
    """Delete old entries based on retention setting."""
    retention_days = int(get_setting("data_retention_days", "90"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    session = get_db()
    try:
        # Clean action log observations
        deleted_obs = session.query(ActionLog).filter(
            ActionLog.created_at < cutoff,
            ActionLog.action_type == "observation"
        ).delete(synchronize_session=False)

        # Phase 2a: Clean state_history
        deleted_hist = session.query(StateHistory).filter(
            StateHistory.created_at < cutoff
        ).delete(synchronize_session=False)

        # Phase 2a: Clean pattern_match_log
        deleted_matches = session.query(PatternMatchLog).filter(
            PatternMatchLog.matched_at < cutoff
        ).delete(synchronize_session=False)

        session.commit()
        total = deleted_obs + deleted_hist + deleted_matches
        if total > 0:
            logger.info(
                f"Cleanup: Deleted {deleted_obs} observations, "
                f"{deleted_hist} state history, "
                f"{deleted_matches} pattern matches "
                f"(older than {retention_days} days)"
            )

        # #6 Auto-Vacuum SQLite
        try:
            session.execute(text("VACUUM"))
            logger.info("SQLite VACUUM completed")
        except Exception as e:
            logger.debug(f"VACUUM skipped: {e}")

        return total
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        try:
            session.rollback()
        except:
            pass
        return 0
    finally:
        session.close()


def schedule_cleanup():
    """Schedule daily cleanup at 3:00 AM."""
    global _cleanup_timer

    def _cleanup_loop():
        while True:
            now = datetime.now()
            # Next 3:00 AM
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info(f"Next cleanup scheduled in {wait_seconds/3600:.1f} hours")
            time.sleep(wait_seconds)
            try:
                run_cleanup()
            except Exception as e:
                logger.error(f"Scheduled cleanup failed: {e}")

    _cleanup_timer = threading.Thread(target=_cleanup_loop, daemon=True)
    _cleanup_timer.start()


# ==============================================================================
# Fix 28: Graceful Shutdown
# ==============================================================================

_start_time = None

def graceful_shutdown(signum, frame):
    """Handle shutdown signals gracefully. (#2)"""
    logger.info("Shutdown signal received - cleaning up...")

    # Stop schedulers
    for name, sched in [("pattern_scheduler", pattern_scheduler), ("automation_scheduler", automation_scheduler)]:
        try:
            sched.stop()
            logger.info(f"{name} stopped")
        except Exception as e:
            logger.error(f"Error stopping {name}: {e}")

    # Stop domain manager
    if domain_manager:
        try:
            domain_manager.stop_all()
            logger.info("Domain manager stopped")
        except Exception:
            pass

    # Disconnect HA (flushes event queue)
    try:
        ha.disconnect()
        logger.info("HA connection closed")
    except Exception as e:
        logger.error(f"Error disconnecting HA: {e}")

    # Final DB vacuum
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        logger.info("WAL checkpoint completed")
    except Exception:
        pass

    # Close DB connections
    try:
        engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing DB: {e}")

    logger.info("MindHome shutdown complete")
    sys.exit(0)


# ==============================================================================
# Startup
# ==============================================================================

def start_app():
    """Initialize and start MindHome. (#10 Self-Test)"""
    global _start_time
    _start_time = time.time()

    logger.info("=" * 60)
    logger.info("MindHome - Smart Home AI")
    logger.info(f"Version: 0.5.0 (Phase 1+2 Complete + Improvements)")
    logger.info(f"Language: {get_language()}")
    logger.info(f"Log Level: {log_level}")
    logger.info(f"Ingress Path: {INGRESS_PATH}")
    logger.info("=" * 60)

    # #10 Startup Self-Test
    logger.info("Running startup self-test...")
    try:
        session = get_db()
        session.execute(text("SELECT 1"))
        session.close()
        logger.info("  âœ… Database OK")
    except Exception as e:
        logger.error(f"  âŒ Database FAILED: {e}")

    # Register shutdown handlers (#2)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    # Set defaults
    if not get_setting("data_retention_days"):
        set_setting("data_retention_days", "90")

    # Connect to Home Assistant
    ha.connect()

    # Check timezone
    try:
        tz = get_ha_timezone()
        logger.info(f"  âœ… Timezone: {tz}")
    except Exception:
        logger.warning("  âš ï¸ Timezone fallback to UTC")

    # Subscribe to state changes
    ha.subscribe_events(on_state_changed, "state_changed")

    # Start domain plugins (if available)
    if domain_manager:
        try:
            # Auto-enable all domains if none are enabled yet
            _dm_session = get_session(engine)
            try:
                enabled_count = _dm_session.query(Domain).filter_by(is_enabled=True).count()
                if enabled_count == 0:
                    all_domains = _dm_session.query(Domain).all()
                    for d in all_domains:
                        d.is_enabled = True
                    _dm_session.commit()
                    logger.info(f"Auto-enabled {len(all_domains)} domains (first start)")
            finally:
                _dm_session.close()
            domain_manager.start_enabled_domains()
        except Exception as e:
            logger.warning(f"Domain manager start error: {e}")

    # Start ML engines
    pattern_scheduler.start()
    logger.info("  âœ… Pattern Engine started")

    automation_scheduler.start()
    logger.info("  âœ… Automation Engine started")

    # Start cleanup scheduler
    schedule_cleanup()

    # Start watchdog thread (#40)
    watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True)
    watchdog_thread.start()
    logger.info("  âœ… Watchdog started")

    # Run startup self-test (#10)
    test_results = run_startup_self_test()
    if not test_results["passed"]:
        logger.warning(f"Self-test issues: {test_results}")

    # Run cleanup once on startup
    try:
        run_cleanup()
    except Exception:
        pass

    logger.info("MindHome started successfully!")

    # Start Flask
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    start_app()


# ==============================================================================
# Phase 3B: Person Schedules / Time Profiles
# ==============================================================================

@app.route("/api/person-schedules", methods=["GET"])
def api_get_person_schedules():
    session = get_db()
    try:
        schedules = session.query(PersonSchedule).filter_by(is_active=True).all()
        return jsonify([{
            "id": s.id, "user_id": s.user_id, "schedule_type": s.schedule_type,
            "name": s.name, "time_wake": s.time_wake, "time_leave": s.time_leave,
            "time_home": s.time_home, "time_sleep": s.time_sleep,
            "weekdays": s.weekdays, "shift_data": s.shift_data,
            "valid_from": utc_iso(s.valid_from) if s.valid_from else None,
            "valid_until": utc_iso(s.valid_until) if s.valid_until else None,
        } for s in schedules])
    finally:
        session.close()

@app.route("/api/person-schedules", methods=["POST"])
def api_create_person_schedule():
    data = request.json
    session = get_db()
    try:
        schedule = PersonSchedule(
            user_id=data["user_id"], schedule_type=data.get("schedule_type", "weekday"),
            name=data.get("name"), time_wake=data.get("time_wake"),
            time_leave=data.get("time_leave"), time_home=data.get("time_home"),
            time_sleep=data.get("time_sleep"), weekdays=data.get("weekdays"),
            shift_data=data.get("shift_data"),
        )
        if data.get("valid_from"):
            schedule.valid_from = datetime.fromisoformat(data["valid_from"])
        if data.get("valid_until"):
            schedule.valid_until = datetime.fromisoformat(data["valid_until"])
        session.add(schedule)
        session.commit()
        audit_log("create_schedule", {"user_id": data["user_id"], "type": data.get("schedule_type")})
        return jsonify({"success": True, "id": schedule.id})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()

@app.route("/api/person-schedules/<int:sid>", methods=["PUT"])
def api_update_person_schedule(sid):
    data = request.json
    session = get_db()
    try:
        s = session.get(PersonSchedule, sid)
        if not s:
            return jsonify({"error": "Not found"}), 404
        for f in ["schedule_type","name","time_wake","time_leave","time_home","time_sleep","weekdays","shift_data"]:
            if f in data:
                setattr(s, f, data[f])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()

@app.route("/api/person-schedules/<int:sid>", methods=["DELETE"])
def api_delete_person_schedule(sid):
    session = get_db()
    try:
        s = session.get(PersonSchedule, sid)
        if s:
            s.is_active = False
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()

# ==============================================================================
# Phase 3B: Shift Templates
# ==============================================================================

@app.route("/api/shift-templates", methods=["GET"])
def api_get_shift_templates():
    session = get_db()
    try:
        return jsonify([{"id": t.id, "name": t.name, "short_code": t.short_code,
            "blocks": t.blocks, "color": t.color}
            for t in session.query(ShiftTemplate).filter_by(is_active=True).all()])
    finally:
        session.close()

@app.route("/api/shift-templates", methods=["POST"])
def api_create_shift_template():
    data = request.json
    session = get_db()
    try:
        t = ShiftTemplate(name=data["name"], short_code=data.get("short_code"),
            blocks=data.get("blocks", []), color=data.get("color"))
        session.add(t)
        session.commit()
        return jsonify({"success": True, "id": t.id})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()

@app.route("/api/shift-templates/<int:tid>", methods=["DELETE"])
def api_delete_shift_template(tid):
    session = get_db()
    try:
        t = session.get(ShiftTemplate, tid)
        if t:
            t.is_active = False
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()

# ==============================================================================
# Phase 3B: Shift Plan PDF Import
# ==============================================================================

@app.route("/api/shift-plan/import", methods=["POST"])
def api_import_shift_plan():
    """Import shift plan from PDF. Parses the confirmed schedule format."""
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    try:
        import tempfile as _tf
        with _tf.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except ImportError:
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(tmp_path)
                for page in reader.pages:
                    text += (page.extract_text() or "") + "\n"
            except ImportError:
                import os; os.unlink(tmp_path)
                return jsonify({"error": "PDF-Bibliothek fehlt (pdfplumber oder PyPDF2)"}), 500
        import os; os.unlink(tmp_path)
        if not text.strip():
            return jsonify({"error": "Kein Text im PDF gefunden"}), 400
        parsed = _parse_shift_plan(text)
        return jsonify({"success": True, "raw_text": text[:3000], "parsed": parsed})
    except Exception as e:
        logger.error(f"Shift plan import error: {e}")
        return jsonify({"error": str(e)}), 500


def _parse_shift_plan(text):
    """Parse confirmed shift plan PDF into structured entries.
    
    Tested against real PDFs. Handles multi-line records.
    Fehlzeiten (Urlaub, Zeitausgleich, Krank) override Dienstplan column.
    """
    import re
    raw_lines = text.strip().split("\n")
    
    person_name = None
    pm = re.search(r"von\s+(\S+)\s+(\S+)\s+best", text)
    if pm:
        person_name = f"{pm.group(2)} {pm.group(1)}"
    month_year = None
    my = re.search(r"Dienstplan\s+f.{1,3}r\s+(\w+)\s+(\d{4})", text)
    if my:
        month_year = f"{my.group(1)} {my.group(2)}"

    date_re = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
    time_re = re.compile(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})")
    
    fehlzeiten_kw = {
        "urlaub": ("urlaub", "Urlaub"),
        "zeitausgleich": ("zeitausgleich", "Zeitausgleich"),
        "krank": ("krank", "Krank"),
    }
    
    clean = []
    for line in raw_lines:
        s = line.strip()
        if not s or s.startswith("Datum ") or s.startswith("Seite") or "best\u00e4tigt" in s or "Dienstplan f" in s:
            continue
        clean.append(s)
    
    consumed = set()
    entries = []
    first_name = (person_name or "").split()[0] if person_name else ""
    
    i = 0
    while i < len(clean):
        if i in consumed:
            i += 1
            continue
        
        line = clean[i]
        line_lower = line.lower()
        has_date = bool(date_re.search(line))
        shift_keywords = ["fr\u00fch", "abenddienst", "mittagsdienst", "tagdienst", "dienstfrei", "urlaub", "zeitausgleich", "krank"]
        has_shift = any(kw in line_lower for kw in shift_keywords)
        
        if has_shift and not has_date:
            record_lines = [line]
            consumed.add(i)
            j = i + 1
            date_found = False
            while j < len(clean) and j not in consumed:
                if date_re.search(clean[j]):
                    record_lines.append(clean[j])
                    consumed.add(j)
                    date_found = True
                    j += 1
                    break
                j += 1
            if date_found:
                while j < len(clean) and j not in consumed:
                    nxt = clean[j]
                    nxt_lower = nxt.lower()
                    if date_re.search(nxt):
                        break
                    if any(nxt_lower.startswith(kw) for kw in ["fr\u00fch", "tag", "dienst"]):
                        break
                    record_lines.append(nxt)
                    consumed.add(j)
                    j += 1
                    break
            merged = " ".join(record_lines)
            i = j if date_found else i + 1
            
        elif has_date and has_shift:
            merged = line
            consumed.add(i)
            i += 1
        elif has_date and not has_shift:
            consumed.add(i)
            i += 1
            continue
        else:
            consumed.add(i)
            i += 1
            continue
        
        dm = date_re.search(merged)
        if not dm:
            continue
        day, month, year = dm.groups()
        date_str = f"{year}-{month}-{day}"
        ml = merged.lower()
        
        # Check Fehlzeiten FIRST (overrides Dienstplan)
        fehlzeit_type = None
        fehlzeit_label = None
        for fkw, (ftype, flabel) in fehlzeiten_kw.items():
            if fkw in ml:
                fehlzeit_type = ftype
                fehlzeit_label = flabel
                break
        
        # Determine shift type from Dienstplan column
        dienstplan_type = "unknown"; dienstplan_label = "Unbekannt"
        if "dienstfrei" in ml:
            dienstplan_type = "dienstfrei"; dienstplan_label = "Dienstfrei"
        elif "fr\u00fch" in ml and "abenddienst" in ml:
            dienstplan_type = "frueh_abend"; dienstplan_label = "Fr\u00fch- + Abenddienst"
        elif "fr\u00fch" in ml and "mittagsdienst" in ml:
            dienstplan_type = "frueh_mittag"; dienstplan_label = "Fr\u00fch- + Mittagsdienst"
        elif "tagdienst" in ml:
            dienstplan_type = "tagdienst"; dienstplan_label = "Tagdienst"
        elif "fr\u00fch" in ml:
            dienstplan_type = "frueh"; dienstplan_label = "Fr\u00fch"
        
        # Fehlzeiten override
        if fehlzeit_type:
            shift_type = fehlzeit_type
            shift_label = fehlzeit_label
        else:
            shift_type = dienstplan_type
            shift_label = dienstplan_label
        
        # Extract time blocks (only if no Fehlzeit)
        all_times = time_re.findall(merged)
        blocks = []
        
        if fehlzeit_type or shift_type == "dienstfrei":
            pass
        elif shift_type in ("frueh_abend", "frueh_mittag"):
            if len(all_times) >= 4:
                blocks = [
                    {"start": all_times[1][0], "end": all_times[1][1]},
                    {"start": all_times[3][0], "end": all_times[3][1]},
                ]
            elif len(all_times) == 2:
                blocks = [
                    {"start": all_times[0][0], "end": all_times[0][1]},
                    {"start": all_times[1][0], "end": all_times[1][1]},
                ]
        else:
            if len(all_times) >= 2:
                blocks = [{"start": all_times[1][0], "end": all_times[1][1]}]
            elif len(all_times) == 1:
                blocks = [{"start": all_times[0][0], "end": all_times[0][1]}]
        
        # Build calendar events
        calendar_events = []
        if fehlzeit_type:
            calendar_events = [{"label": f"{fehlzeit_label} - {first_name}", "all_day": True}]
        elif shift_type == "frueh_abend" and len(blocks) == 2:
            calendar_events = [
                {"label": f"Fr\u00fchdienst - {first_name}", "start": blocks[0]["start"], "end": blocks[0]["end"]},
                {"label": f"Abenddienst - {first_name}", "start": blocks[1]["start"], "end": blocks[1]["end"]},
            ]
        elif shift_type == "frueh_mittag" and len(blocks) == 2:
            calendar_events = [
                {"label": f"Fr\u00fchdienst - {first_name}", "start": blocks[0]["start"], "end": blocks[0]["end"]},
                {"label": f"Mittagsdienst - {first_name}", "start": blocks[1]["start"], "end": blocks[1]["end"]},
            ]
        elif shift_type == "tagdienst" and blocks:
            calendar_events = [{"label": f"Tagdienst - {first_name}", "start": blocks[0]["start"], "end": blocks[0]["end"]}]
        elif shift_type == "frueh" and blocks:
            calendar_events = [{"label": f"Fr\u00fchdienst - {first_name}", "start": blocks[0]["start"], "end": blocks[0]["end"]}]
        elif shift_type == "dienstfrei":
            calendar_events = [{"label": f"Dienstfrei - {first_name}", "all_day": True}]
        
        entries.append({
            "date": date_str, "shift_type": shift_type, "shift_label": shift_label,
            "blocks": blocks, "calendar_events": calendar_events,
            "fehlzeit": fehlzeit_label,
        })
    
    return {
        "person_name": person_name, "month_year": month_year,
        "entries": entries, "parsed_count": len(entries),
        "work_days": len([e for e in entries if e["shift_type"] not in ("dienstfrei", "urlaub", "zeitausgleich", "krank")]),
        "off_days": len([e for e in entries if e["shift_type"] in ("dienstfrei", "urlaub", "zeitausgleich", "krank")]),
    }



@app.route("/api/shift-plan/apply", methods=["POST"])
def api_apply_shift_plan():
    """Apply parsed shift plan: save schedule + create calendar events."""
    data = request.json
    user_id = data.get("user_id")
    entries = data.get("entries", [])
    calendar_entity = data.get("calendar_entity")
    person_name = data.get("person_name", "")
    session = get_db()
    try:
        # If no user_id given but person_name available, try to match
        if not user_id and person_name:
            # Try matching by name parts
            parts = person_name.lower().split()
            for u in session.query(User).all():
                uname = u.name.lower()
                if any(p in uname for p in parts):
                    user_id = u.id
                    break

        if not user_id:
            return jsonify({"error": "Kein Benutzer zugeordnet"}), 400

        # Get person name for calendar labels
        user = session.get(User, user_id)
        label_name = person_name or (user.name if user else "")
        # Use first name only for calendar labels
        first_name = label_name.split()[0] if label_name else ""

        # If no calendar_entity given, try to get from user settings
        if not calendar_entity and user:
            # Check if user has a calendar entity configured
            pref = session.query(UserPreference).filter_by(
                user_id=user_id, preference_key="calendar_entity"
            ).first()
            if pref:
                calendar_entity = pref.preference_value

        # Save schedule to DB
        month_year = data.get("month_year", datetime.now().strftime("%m.%Y"))
        schedule = PersonSchedule(
            user_id=user_id,
            schedule_type="shift",
            name=f"Schichtplan {month_year} - {first_name}",
            shift_data=entries,
        )
        dates = [e["date"] for e in entries if e.get("date")]
        if dates:
            schedule.valid_from = datetime.fromisoformat(min(dates))
            schedule.valid_until = datetime.fromisoformat(max(dates))
        session.add(schedule)
        session.commit()

        # Create calendar events
        created = 0
        errors = 0
        if calendar_entity:
            for entry in entries:
                cal_events = entry.get("calendar_events", [])
                for cev in cal_events:
                    try:
                        if cev.get("all_day"):
                            # All-day event (Dienstfrei, Urlaub, ZA)
                            ha.call_service("calendar", "create_event", {
                                "entity_id": calendar_entity,
                                "summary": f"{cev['label']} - {first_name}",
                                "start_date": entry["date"],
                                "end_date": entry["date"],
                            })
                        else:
                            # Timed event
                            ha.call_service("calendar", "create_event", {
                                "entity_id": calendar_entity,
                                "summary": f"{cev['label']} - {first_name}",
                                "start_date_time": f"{entry['date']}T{cev['start']}:00",
                                "end_date_time": f"{entry['date']}T{cev['end']}:00",
                            })
                        created += 1
                    except Exception as e:
                        logger.warning(f"Calendar event error for {entry['date']}: {e}")
                        errors += 1

        audit_log("import_shift_plan", {
            "user_id": user_id, "person": first_name,
            "entries": len(entries), "calendar_events": created, "errors": errors
        })
        return jsonify({
            "success": True,
            "schedule_id": schedule.id,
            "calendar_events_created": created,
            "calendar_errors": errors,
            "matched_user": user.name if user else None,
        })
    except Exception as e:
        session.rollback()
        logger.error(f"Shift plan apply error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/users/<int:user_id>/calendar-entity", methods=["PUT"])
def api_set_user_calendar_entity(user_id):
    """Set the HA calendar entity for a user (for shift plan sync)."""
    data = request.json
    calendar_entity = data.get("calendar_entity", "")
    session = get_db()
    try:
        pref = session.query(UserPreference).filter_by(
            user_id=user_id, preference_key="calendar_entity"
        ).first()
        if pref:
            pref.preference_value = calendar_entity
        else:
            pref = UserPreference(
                user_id=user_id, preference_key="calendar_entity",
                preference_value=calendar_entity
            )
            session.add(pref)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@app.route("/api/ha/calendars", methods=["GET"])
def api_get_ha_calendars():
    """Get available HA calendar entities."""
    states = ha.get_states() or []
    calendars = [{"entity_id": s["entity_id"],
                  "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
                 for s in states if s["entity_id"].startswith("calendar.")]
    return jsonify(calendars)

# ==============================================================================
# Phase 3B: Holidays
# ==============================================================================

BUILTIN_HOLIDAYS_AT = [
    {"name": "Neujahr", "date": "01-01", "recurring": True, "region": "AT"},
    {"name": "Hl. Drei K\u00f6nige", "date": "01-06", "recurring": True, "region": "AT"},
    {"name": "Staatsfeiertag", "date": "05-01", "recurring": True, "region": "AT"},
    {"name": "Mari\u00e4 Himmelfahrt", "date": "08-15", "recurring": True, "region": "AT"},
    {"name": "Nationalfeiertag", "date": "10-26", "recurring": True, "region": "AT"},
    {"name": "Allerheiligen", "date": "11-01", "recurring": True, "region": "AT"},
    {"name": "Mari\u00e4 Empf\u00e4ngnis", "date": "12-08", "recurring": True, "region": "AT"},
    {"name": "Christtag", "date": "12-25", "recurring": True, "region": "AT"},
    {"name": "Stefanitag", "date": "12-26", "recurring": True, "region": "AT"},
    {"name": "Hl. Leopold (N\u00d6)", "date": "11-15", "recurring": True, "region": "AT-3"},
]

def _compute_easter(year):
    a = year % 19; b = year // 100; c = year % 100
    d = b // 4; e = b % 4; f = (b + 8) // 25
    g = (b - f + 1) // 3; h = (19*a + b - d - g + 15) % 30
    i = c // 4; k = c % 4; l = (32 + 2*e + 2*i - h - k) % 7
    m = (a + 11*h + 22*l) // 451
    month = (h + l - 7*m + 114) // 31
    day = ((h + l - 7*m + 114) % 31) + 1
    from datetime import date as _date
    return _date(year, month, day)

def get_holidays_for_year(year):
    from datetime import date as _date, timedelta as _td
    holidays = []
    for h in BUILTIN_HOLIDAYS_AT:
        if h["recurring"] and h["date"]:
            m, d = h["date"].split("-")
            holidays.append({"name": h["name"], "date": f"{year}-{h['date']}", "region": h["region"]})
    easter = _compute_easter(year)
    holidays.append({"name": "Ostermontag", "date": str(easter + _td(days=1)), "region": "AT"})
    holidays.append({"name": "Christi Himmelfahrt", "date": str(easter + _td(days=39)), "region": "AT"})
    holidays.append({"name": "Pfingstmontag", "date": str(easter + _td(days=50)), "region": "AT"})
    holidays.append({"name": "Fronleichnam", "date": str(easter + _td(days=60)), "region": "AT"})
    return holidays

@app.route("/api/holidays", methods=["GET"])
def api_get_holidays():
    year = request.args.get("year", datetime.now().year, type=int)
    session = get_db()
    try:
        builtin = get_holidays_for_year(year)
        custom = session.query(Holiday).filter_by(is_active=True).all()
        custom_list = [{"id": h.id, "name": h.name, "date": h.date, "region": h.region,
            "source": h.source, "is_recurring": h.is_recurring} for h in custom]
        # HA holiday integration
        ha_holidays = []
        ha_cal = request.args.get("calendar_entity", "")
        if ha_cal:
            try:
                events = ha.call_service("calendar", "get_events", {
                    "entity_id": ha_cal,
                    "start_date_time": f"{year}-01-01T00:00:00",
                    "end_date_time": f"{year}-12-31T23:59:59",
                }, return_response=True)
                if events and ha_cal in events:
                    for ev in events[ha_cal].get("events", []):
                        ha_holidays.append({
                            "name": ev.get("summary", ""),
                            "date": ev.get("start", {}).get("date", ev.get("start", "")),
                            "source": "ha_integration",
                        })
            except Exception as e:
                logger.warning(f"HA holiday calendar error: {e}")
        return jsonify({"builtin": builtin, "custom": custom_list, "ha_holidays": ha_holidays, "year": year})
    finally:
        session.close()

@app.route("/api/holidays", methods=["POST"])
def api_create_holiday():
    data = request.json
    session = get_db()
    try:
        h = Holiday(name=data["name"], date=data["date"],
            is_recurring=data.get("is_recurring", False),
            region=data.get("region"), source="manual")
        session.add(h)
        session.commit()
        return jsonify({"success": True, "id": h.id})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()

@app.route("/api/holidays/<int:hid>", methods=["DELETE"])
def api_delete_holiday(hid):
    session = get_db()
    try:
        h = session.get(Holiday, hid)
        if h:
            h.is_active = False
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()

@app.route("/api/holidays/is-today", methods=["GET"])
def api_is_today_holiday():
    """Check if today is a holiday. Used by pattern engine for schedule decisions."""
    now = datetime.now()
    holidays = get_holidays_for_year(now.year)
    today_str = now.strftime("%Y-%m-%d")
    for h in holidays:
        if h["date"] == today_str:
            return jsonify({"is_holiday": True, "holiday": h})
    return jsonify({"is_holiday": False})

@app.route("/api/holidays/init-builtin", methods=["POST"])
def api_init_builtin_holidays():
    """Initialize builtin Austrian holidays in DB."""
    session = get_db()
    try:
        added = 0
        for h in BUILTIN_HOLIDAYS_AT:
            existing = session.query(Holiday).filter_by(name=h["name"], source="builtin").first()
            if not existing:
                session.add(Holiday(name=h["name"], date=h["date"],
                    is_recurring=h["recurring"], region=h["region"], source="builtin"))
                added += 1
        session.commit()
        return jsonify({"success": True, "added": added})
    finally:
        session.close()


@app.route("/api/ha/holiday-calendars", methods=["GET"])
def api_get_ha_holiday_calendars():
    """Get HA calendar entities from the holiday integration."""
    states = ha.get_states() or []
    # Holiday integration creates calendar.* entities with device_class or specific patterns
    calendars = []
    for s in states:
        eid = s.get("entity_id", "")
        attrs = s.get("attributes", {})
        if eid.startswith("calendar."):
            # Holiday integration calendars typically have country names
            name = attrs.get("friendly_name", eid)
            calendars.append({"entity_id": eid, "name": name})
    return jsonify(calendars)
