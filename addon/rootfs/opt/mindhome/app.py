"""
MindHome - Main Application
Flask backend serving the API and frontend.
"""

import os
import sys
import json
import logging
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

from models import (
    get_engine, get_session, init_database,
    User, UserRole, Room, Domain, Device, RoomDomainState,
    LearningPhase, QuickAction, SystemSetting, UserPreference,
    NotificationSetting, NotificationType, ActionLog,
    DataCollection, OfflineActionQueue
)
from ha_connection import HAConnection
from domains import DomainManager

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

# Home Assistant connection
ha = HAConnection()

# Domain Manager
domain_manager = DomainManager(ha, lambda: get_session(engine))


# ==============================================================================
# Event Handlers
# ==============================================================================

def on_state_changed(event):
    """Handle real-time state change events from HA."""
    # Route to domain plugins
    domain_manager.on_state_change(event)

    event_data = event.get("data", {})
    entity_id = event_data.get("entity_id", "")
    new_state = event_data.get("new_state", {})
    logger.debug(f"State changed: {entity_id} -> {new_state.get('state')}")


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
            "version": "0.1.0",
            "timestamp": datetime.utcnow().isoformat()
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
        # Pause all room domain states
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
            "description": d.description_de if lang == "de" else d.description_en
        } for d in domains])
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

        # Start/stop the domain plugin
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
    """Get all rooms."""
    session = get_db()
    try:
        rooms = session.query(Room).filter_by(is_active=True).all()
        return jsonify([{
            "id": r.id,
            "name": r.name,
            "ha_area_id": r.ha_area_id,
            "icon": r.icon,
            "privacy_mode": r.privacy_mode,
            "device_count": len(r.devices),
            "domain_states": [{
                "domain_id": ds.domain_id,
                "learning_phase": ds.learning_phase.value,
                "confidence_score": ds.confidence_score,
                "is_paused": ds.is_paused
            } for ds in r.domain_states]
        } for r in rooms])
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
    """Get all tracked devices."""
    session = get_db()
    try:
        devices = session.query(Device).all()
        return jsonify([{
            "id": d.id,
            "ha_entity_id": d.ha_entity_id,
            "name": d.name,
            "domain_id": d.domain_id,
            "room_id": d.room_id,
            "is_tracked": d.is_tracked,
            "is_controllable": d.is_controllable
        } for d in devices])
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

        session.commit()
        return jsonify({"id": device.id, "name": device.name})
    finally:
        session.close()


# ==============================================================================
# API Routes - Discovery (Onboarding)
# ==============================================================================

@app.route("/api/discover", methods=["GET"])
def api_discover_devices():
    """Discover all HA devices grouped by MindHome domain."""
    discovered = ha.discover_devices()

    # Count per domain
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
    """Import discovered devices into MindHome."""
    data = request.json
    session = get_db()
    try:
        imported_count = 0

        for domain_name, entities in data.get("domains", {}).items():
            # Get MindHome domain
            domain = session.query(Domain).filter_by(name=domain_name).first()
            if not domain:
                continue

            # Enable domain
            domain.is_enabled = True

            for entity_info in entities:
                # Check if already exists
                existing = session.query(Device).filter_by(
                    ha_entity_id=entity_info["entity_id"]
                ).first()

                if not existing:
                    device = Device(
                        ha_entity_id=entity_info["entity_id"],
                        name=entity_info.get("friendly_name", entity_info["entity_id"]),
                        domain_id=domain.id,
                        room_id=entity_info.get("room_id"),
                        device_meta=entity_info.get("attributes", {})
                    )
                    session.add(device)
                    imported_count += 1

        session.commit()
        return jsonify({"success": True, "imported": imported_count})
    finally:
        session.close()


@app.route("/api/discover/areas", methods=["GET"])
def api_discover_areas():
    """Get areas (rooms) from HA."""
    areas = ha.get_areas()
    return jsonify({"areas": areas or []})


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

        # Create default notification settings
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
            # Turn off all lights, switches, media
            for entity in ha.get_entities_by_domain("light"):
                ha.call_service("light", "turn_off", entity_id=entity["entity_id"])
            for entity in ha.get_entities_by_domain("switch"):
                ha.call_service("switch", "turn_off", entity_id=entity["entity_id"])
            for entity in ha.get_entities_by_domain("media_player"):
                ha.call_service("media_player", "turn_off", entity_id=entity["entity_id"])

        elif action_type == "leaving_home":
            set_setting("system_mode", "away")
            # Turn off lights, lower heating, activate security
            for entity in ha.get_entities_by_domain("light"):
                ha.call_service("light", "turn_off", entity_id=entity["entity_id"])
            for entity in ha.get_entities_by_domain("climate"):
                ha.call_service("climate", "set_temperature",
                              {"temperature": 18}, entity_id=entity["entity_id"])

        elif action_type == "arriving_home":
            set_setting("system_mode", "normal")
            # Will be enhanced in Phase 2 with learned preferences

        elif action_type == "guest_mode_on":
            set_setting("system_mode", "guest")

        elif action_type == "emergency_stop":
            set_setting("system_mode", "emergency_stop")
            states = session.query(RoomDomainState).all()
            for state in states:
                state.is_paused = True
            session.commit()

        # Log action
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
# API Routes - Action Log
# ==============================================================================

@app.route("/api/action-log", methods=["GET"])
def api_get_action_log():
    """Get action log with optional filters."""
    session = get_db()
    try:
        limit = request.args.get("limit", 50, type=int)
        action_type = request.args.get("type")

        query = session.query(ActionLog).order_by(ActionLog.created_at.desc())

        if action_type:
            query = query.filter_by(action_type=action_type)

        logs = query.limit(limit).all()

        return jsonify([{
            "id": log.id,
            "action_type": log.action_type,
            "domain_id": log.domain_id,
            "room_id": log.room_id,
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

        # Restore previous state
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
# Frontend Serving
# ==============================================================================

@app.route("/frontend")
@app.route("/frontend/")
@app.route("/frontend/<path:path>")
def serve_frontend(path="index.html"):
    """Serve the React frontend."""
    if path and os.path.exists(os.path.join(app.static_folder, "frontend", path)):
        return send_from_directory(os.path.join(app.static_folder, "frontend"), path)
    return send_from_directory(os.path.join(app.static_folder, "frontend"), "index.html")


@app.route("/")
def root_redirect():
    """Redirect root to frontend."""
    return redirect("/frontend/")


# ==============================================================================
# Startup
# ==============================================================================

def start_app():
    """Initialize and start MindHome."""
    logger.info("=" * 60)
    logger.info("MindHome - Smart Home AI")
    logger.info(f"Version: 0.1.0")
    logger.info(f"Language: {get_language()}")
    logger.info(f"Log Level: {log_level}")
    logger.info(f"Ingress Path: {INGRESS_PATH}")
    logger.info("=" * 60)

    # Connect to Home Assistant
    ha.connect()

    # Subscribe to state changes (real-time via WebSocket)
    ha.subscribe_events(on_state_changed, "state_changed")

    # Start enabled domain plugins
    domain_manager.start_enabled_domains()

    logger.info("MindHome started successfully!")

    # Start Flask
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    start_app()
