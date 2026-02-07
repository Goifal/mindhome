"""
MindHome - Main Application
Flask backend serving the API and frontend.
Phase 1 Final - Teil A Backend
"""

import os
import sys
import json
import signal
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

from models import (
    get_engine, get_session, init_database, run_migrations,
    User, UserRole, Room, Domain, Device, RoomDomainState,
    LearningPhase, QuickAction, SystemSetting, UserPreference,
    NotificationSetting, NotificationType, ActionLog,
    DataCollection, OfflineActionQueue,
    StateHistory, LearnedPattern, PatternMatchLog
)
from ha_connection import HAConnection
from domains import DomainManager
from ml.pattern_engine import EventBus, StateLogger, PatternScheduler, PatternDetector

# ==============================================================================
# App Configuration
# ==============================================================================

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

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

# Home Assistant connection
ha = HAConnection()

# Domain Manager
domain_manager = DomainManager(ha, lambda: get_session(engine))

# Phase 2a: Pattern Engine
event_bus = EventBus()
state_logger = StateLogger(engine, ha)
pattern_scheduler = PatternScheduler(engine, ha)

# Cleanup timer
_cleanup_timer = None


# ==============================================================================
# Event Handlers
# ==============================================================================

def on_state_changed(event):
    """Handle real-time state change events from HA."""
    # Route to domain plugins
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
    reason = f"{device_name}: {old_val} → {new_val}"

    details = []
    if "brightness_pct" in new_display_attrs:
        details.append(f"{new_display_attrs['brightness_pct']}%")
    if "position_pct" in new_display_attrs:
        details.append(f"Position {new_display_attrs['position_pct']}%")
    if "target_temp" in new_display_attrs:
        details.append(f"{new_display_attrs['target_temp']}°C")
    if "current_temp" in new_display_attrs:
        details.append(f"Ist: {new_display_attrs['current_temp']}°C")

    if details:
        reason += f" ({', '.join(details)})"

    return reason


# ==============================================================================
# API Routes - System
# ==============================================================================

@app.route("/api/system/status", methods=["GET"])
def api_system_status():
    """Get system status overview."""
    session = get_db()
    try:
        return jsonify({
            "status": "running",
            "ha_connected": ha.is_connected(),
            "offline_queue_size": ha.get_offline_queue_size(),
            "system_mode": get_setting("system_mode", "normal"),
            "onboarding_completed": get_setting("onboarding_completed", "false") == "true",
            "language": get_language(),
            "theme": get_setting("theme", "dark"),
            "view_mode": get_setting("view_mode", "simple"),
            "version": "0.2.0",
            "timestamp": datetime.utcnow().isoformat()
        })
    finally:
        session.close()


# Fix 16: Health-Check Endpoint
@app.route("/api/health", methods=["GET"])
def api_health_check():
    """Health check endpoint for monitoring."""
    health = {
        "status": "healthy",
        "checks": {}
    }

    # Check DB
    try:
        session = get_db()
        session.execute("SELECT 1")
        session.close()
        health["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        health["checks"]["database"] = {"status": "error", "message": str(e)}
        health["status"] = "unhealthy"

    # Check HA connection
    health["checks"]["ha_websocket"] = {
        "status": "ok" if ha._ws_connected else "disconnected",
        "reconnect_attempts": getattr(ha, '_reconnect_count', 0)
    }
    health["checks"]["ha_rest_api"] = {
        "status": "ok" if ha._is_online else "offline"
    }

    # Uptime
    health["uptime_seconds"] = int(time.time() - _start_time) if '_start_time' in dir() else 0
    health["version"] = "0.2.0"

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
            "version": "0.2.0",
            "phase": "2a",
            "ha_connected": ha.is_connected(),
            "ws_connected": ha._ws_connected,
            "ha_entity_count": len(ha.get_states() or []),
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
        domain = session.query(Domain).get(domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        if not getattr(domain, 'is_custom', False):
            return jsonify({"error": "Cannot edit system domains"}), 400

        if "display_name_de" in data:
            domain.display_name_de = data["display_name_de"]
        if "display_name_en" in data:
            domain.display_name_en = data["display_name_en"]
        if "icon" in data:
            domain.icon = data["icon"]
        if "description_de" in data:
            domain.description_de = data["description_de"]
        if "description_en" in data:
            domain.description_en = data["description_en"]

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
        domain = session.query(Domain).get(domain_id)
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
        domain = session.query(Domain).get(domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        domain.is_enabled = not domain.is_enabled
        session.commit()

        if domain.is_enabled:
            domain_manager.start_domain(domain.name)
        else:
            domain_manager.stop_domain(domain.name)

        return jsonify({"id": domain.id, "is_enabled": domain.is_enabled})
    finally:
        session.close()


@app.route("/api/domains/status", methods=["GET"])
def api_domain_status():
    """Get live status from all active domain plugins."""
    return jsonify(domain_manager.get_all_status())


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
                "last_activity": last_log.created_at.isoformat() if last_log else None,
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
        room = session.query(Room).get(room_id)
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
        room = session.query(Room).get(room_id)
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
        room = session.query(Room).get(room_id)
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
        device = session.query(Device).get(device_id)
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
        updates = data.get("updates", {})

        if not device_ids:
            return jsonify({"error": "No devices selected"}), 400

        updated = 0
        for did in device_ids:
            device = session.query(Device).get(did)
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
            device = session.query(Device).get(did)
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
        device = session.query(Device).get(device_id)
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

                device = Device(
                    ha_entity_id=entity_id,
                    name=friendly_name,
                    domain_id=domain.id,
                    room_id=room_id,
                    device_meta=attributes
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
            "message": f"{imported_count} importiert, {skipped_count} übersprungen (bereits vorhanden)"
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

        device = Device(
            ha_entity_id=entity_id,
            name=friendly_name,
            domain_id=domain_id,
            room_id=room_id,
            device_meta=attrs
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
        user = session.query(User).get(user_id)
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
        user = session.query(User).get(user_id)
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
        action = session.query(QuickAction).get(action_id)
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
        dc = session.query(DataCollection).get(collection_id)
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
            "created_at": log.created_at.isoformat()
        } for log in logs])
    finally:
        session.close()


@app.route("/api/action-log/<int:log_id>/undo", methods=["POST"])
def api_undo_action(log_id):
    """Undo a specific action."""
    session = get_db()
    try:
        log = session.query(ActionLog).get(log_id)
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
            "collected_at": log.created_at.isoformat()
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

@app.route(f"{INGRESS_PATH}/api/patterns", methods=["GET"])
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

        # Default: only active
        if not status_filter:
            query = query.filter_by(is_active=True)

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
            "last_matched_at": p.last_matched_at.isoformat() if p.last_matched_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        } for p in patterns])
    finally:
        session.close()


@app.route(f"{INGRESS_PATH}/api/patterns/<int:pattern_id>", methods=["PUT"])
def api_update_pattern(pattern_id):
    """Update pattern status (activate/deactivate/disable)."""
    data = request.json
    session = get_db()
    try:
        pattern = session.query(LearnedPattern).get(pattern_id)
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

        pattern.updated_at = datetime.utcnow()
        session.commit()
        return jsonify({"success": True, "id": pattern.id, "status": pattern.status})
    finally:
        session.close()


@app.route(f"{INGRESS_PATH}/api/patterns/<int:pattern_id>", methods=["DELETE"])
def api_delete_pattern(pattern_id):
    """Delete a pattern permanently."""
    session = get_db()
    try:
        pattern = session.query(LearnedPattern).get(pattern_id)
        if not pattern:
            return jsonify({"error": "Pattern not found"}), 404

        # Delete match logs first
        session.query(PatternMatchLog).filter_by(pattern_id=pattern_id).delete()
        session.delete(pattern)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@app.route(f"{INGRESS_PATH}/api/patterns/analyze", methods=["POST"])
def api_trigger_analysis():
    """Manually trigger pattern analysis."""
    pattern_scheduler.trigger_analysis_now()
    return jsonify({"success": True, "message": "Analysis started in background"})


# ==============================================================================
# Phase 2a: State History API
# ==============================================================================

@app.route(f"{INGRESS_PATH}/api/state-history", methods=["GET"])
def api_get_state_history():
    """Get state history events with filters."""
    session = get_db()
    try:
        entity_id = request.args.get("entity_id")
        device_id = request.args.get("device_id", type=int)
        hours = request.args.get("hours", 24, type=int)
        limit = request.args.get("limit", 200, type=int)

        cutoff = datetime.utcnow() - timedelta(hours=hours)
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


@app.route(f"{INGRESS_PATH}/api/state-history/count", methods=["GET"])
def api_state_history_count():
    """Get total event count and date range."""
    session = get_db()
    try:
        from sqlalchemy import func as sa_func
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

@app.route(f"{INGRESS_PATH}/api/stats/learning", methods=["GET"])
def api_learning_stats():
    """Get learning progress statistics for dashboard."""
    session = get_db()
    try:
        from sqlalchemy import func as sa_func

        # Event counts
        total_events = session.query(sa_func.count(StateHistory.id)).scalar() or 0
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
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
            domain = session.query(Domain).get(dc.domain_id)
            dname = domain.name if domain else str(dc.domain_id)
            events_by_domain[dname] = events_by_domain.get(dname, 0) + dc.record_count

        # Days of data collected
        oldest = session.query(sa_func.min(StateHistory.created_at)).scalar()
        days_collecting = (datetime.utcnow() - oldest).days if oldest else 0

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
        })
    finally:
        session.close()


# ==============================================================================
# Frontend Serving
# ==============================================================================

@app.route("/")
def serve_index():
    """Serve index.html for root path."""
    return send_from_directory(os.path.join(app.static_folder, "frontend"), "index.html")

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
        return send_from_directory(os.path.join(app.static_folder, "frontend"), path)
    return send_from_directory(os.path.join(app.static_folder, "frontend"), "index.html")


# ==============================================================================
# Backup / Restore
# ==============================================================================

@app.route("/api/backup/export", methods=["GET"])
def api_backup_export():
    """Export all MindHome configuration as JSON."""
    session = get_db()
    try:
        backup = {
            "version": "0.2.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "rooms": [], "devices": [], "users": [], "domains": [],
            "room_domain_states": [], "settings": [], "quick_actions": [],
            "action_log": [], "user_preferences": []
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
# State Change Logging
# ==============================================================================

def log_state_change(entity_id, new_state, old_state, new_attrs=None, old_attrs=None):
    """Log state changes to action_log for tracked devices. Fix 1 + Fix 18."""
    session = get_db()
    try:
        device = session.query(Device).filter_by(ha_entity_id=entity_id).first()
        if not device or not device.is_tracked:
            return

        # Fix 18: Enforce privacy mode
        if device.room_id:
            room = session.query(Room).get(device.room_id)
            if room and room.privacy_mode:
                # Get domain name
                domain = session.query(Domain).get(device.domain_id)
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
    """Handle shutdown signals gracefully."""
    logger.info("Shutdown signal received - cleaning up...")

    # Phase 2a: Stop pattern scheduler
    try:
        pattern_scheduler.stop()
        logger.info("Pattern scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping pattern scheduler: {e}")

    # Disconnect HA
    try:
        ha.disconnect()
        logger.info("HA connection closed")
    except Exception as e:
        logger.error(f"Error disconnecting HA: {e}")

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
    """Initialize and start MindHome."""
    global _start_time
    _start_time = time.time()

    logger.info("=" * 60)
    logger.info("MindHome - Smart Home AI")
    logger.info(f"Version: 0.2.0 (Phase 2a)")
    logger.info(f"Language: {get_language()}")
    logger.info(f"Log Level: {log_level}")
    logger.info(f"Ingress Path: {INGRESS_PATH}")
    logger.info("=" * 60)

    # Fix 28: Register shutdown handlers
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    # Set default retention if not set
    if not get_setting("data_retention_days"):
        set_setting("data_retention_days", "90")

    # Connect to Home Assistant
    ha.connect()

    # Subscribe to state changes (real-time via WebSocket)
    ha.subscribe_events(on_state_changed, "state_changed")

    # Start enabled domain plugins
    domain_manager.start_enabled_domains()

    # Phase 2a: Start pattern scheduler (analysis, decay, storage tracking)
    pattern_scheduler.start()
    logger.info("Pattern Engine started (analysis every 6h)")

    # Fix 3: Start cleanup scheduler
    schedule_cleanup()

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
