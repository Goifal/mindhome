# MindHome - routes/security.py | see version.py for version info
"""
MindHome API Routes - Security & Special Modes (Phase 5)
15th Flask Blueprint: security dashboard, access control, cameras,
geo-fencing, special modes, emergency protocol, entity management.
"""

import logging
import json
from flask import Blueprint, request, jsonify

from helpers import get_setting, set_setting

logger = logging.getLogger("mindhome.routes.security")

security_bp = Blueprint("security", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_security(dependencies):
    """Initialize security routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _get_session():
    from db import get_db_session
    return get_db_session()


# ==============================================================================
# Phase 5 Feature Flags
# ==============================================================================

PHASE5_FEATURES = {
    "phase5.fire_co_response":    {"default": "auto", "requires": "smoke_co_sensor"},
    "phase5.water_leak_response": {"default": "auto", "requires": "moisture_sensor"},
    "phase5.camera_snapshots":    {"default": "auto", "requires": "camera_entity"},
    "phase5.access_control":      {"default": "auto", "requires": "lock_entity"},
    "phase5.geo_fencing":         {"default": "auto", "requires": "gps_tracker"},
    "phase5.security_dashboard":  {"default": "true", "requires": None},
    "phase5.party_mode":          {"default": "true", "requires": None},
    "phase5.cinema_mode":         {"default": "auto", "requires": "media_player_entity"},
    "phase5.home_office_mode":    {"default": "true", "requires": None},
    "phase5.night_lockdown":      {"default": "true", "requires": None},
    "phase5.emergency_protocol":  {"default": "true", "requires": None},
}


def is_phase5_feature_enabled(key):
    """Check if a Phase 5 feature is enabled.

    Returns True if:
      - Explicitly set to 'true'
      - Set to 'auto' (default) — auto-detect based on available entities
    Returns False if explicitly set to 'false'.
    """
    stored = get_setting(key)
    if stored == "false":
        return False
    if stored == "true":
        return True
    # auto or not set: default to enabled
    feature_def = PHASE5_FEATURES.get(key, {})
    default = feature_def.get("default", "true")
    return default != "false"


@security_bp.route("/api/system/phase5-features", methods=["GET"])
def get_phase5_features():
    """Get all Phase 5 feature flags with status."""
    result = {}
    for key, meta in PHASE5_FEATURES.items():
        stored = get_setting(key)
        result[key] = {
            "enabled": is_phase5_feature_enabled(key),
            "value": stored or meta["default"],
            "default": meta["default"],
            "requires": meta["requires"],
        }
    return jsonify(result)


@security_bp.route("/api/system/phase5-features/<key>", methods=["PUT"])
def set_phase5_feature(key):
    """Enable/disable a Phase 5 feature."""
    if key not in PHASE5_FEATURES:
        return jsonify({"error": "Unknown feature key"}), 404
    data = request.get_json(silent=True) or {}
    value = data.get("value", "true")
    if value not in ("true", "false", "auto"):
        return jsonify({"error": "Value must be true, false, or auto"}), 400
    old_value = get_setting(key) or PHASE5_FEATURES[key]["default"]
    set_setting(key, value)
    # Log security event
    _log_security_change("FEATURE_TOGGLED", key, f"{old_value} → {value}")
    return jsonify({"key": key, "value": value, "enabled": is_phase5_feature_enabled(key)})


# ==============================================================================
# Security Change Logging
# ==============================================================================

def _log_security_change(event_type_str, target, detail_text):
    """Log a security-relevant change as SecurityEvent."""
    try:
        from models import SecurityEvent, SecurityEventType, SecuritySeverity
        etype = SecurityEventType(event_type_str.lower())
        with _get_session() as session:
            evt = SecurityEvent(
                event_type=etype,
                severity=SecuritySeverity.INFO,
                message_de=f"{target}: {detail_text}",
                message_en=f"{target}: {detail_text}",
                context={"target": target, "detail": detail_text},
            )
            session.add(evt)
    except Exception as e:
        logger.warning(f"Could not log security change: {e}")


# ==============================================================================
# Generic Entity Management API
# ==============================================================================

@security_bp.route("/api/security/entities/<feature_key>", methods=["GET"])
def get_entities(feature_key):
    """Get all entity assignments for a feature."""
    from models import FeatureEntityAssignment
    try:
        with _get_session() as session:
            assignments = session.query(FeatureEntityAssignment).filter_by(
                feature_key=feature_key
            ).order_by(FeatureEntityAssignment.sort_order).all()
            result = []
            for a in assignments:
                state = _ha().get_state(a.entity_id) if _ha() else None
                result.append({
                    "id": a.id,
                    "feature_key": a.feature_key,
                    "entity_id": a.entity_id,
                    "role": a.role,
                    "config": a.config,
                    "sort_order": a.sort_order,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "state": state.get("state", "unknown") if state else "unknown",
                    "name": state.get("attributes", {}).get("friendly_name", a.entity_id) if state else a.entity_id,
                })
            return jsonify(result)
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/entities/<feature_key>", methods=["POST"])
def add_entity(feature_key):
    """Add an entity assignment to a feature."""
    from models import FeatureEntityAssignment
    data = request.get_json(silent=True) or {}
    entity_id = data.get("entity_id")
    role = data.get("role")
    if not entity_id or not role:
        return jsonify({"error": "entity_id and role are required"}), 400
    try:
        with _get_session() as session:
            a = FeatureEntityAssignment(
                feature_key=feature_key,
                entity_id=entity_id,
                role=role,
                config=data.get("config"),
                sort_order=data.get("sort_order", 0),
                is_active=True,
            )
            session.add(a)
            session.flush()
            _log_security_change("ENTITY_ASSIGNED", feature_key, f"{entity_id} ({role})")
            return jsonify({"id": a.id, "entity_id": entity_id, "role": role}), 201
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/entities/<feature_key>/<int:assignment_id>", methods=["PUT"])
def update_entity(feature_key, assignment_id):
    """Update an entity assignment."""
    from models import FeatureEntityAssignment
    data = request.get_json(silent=True) or {}
    try:
        with _get_session() as session:
            a = session.query(FeatureEntityAssignment).get(assignment_id)
            if not a or a.feature_key != feature_key:
                return jsonify({"error": "Not found"}), 404
            for key in ("role", "config", "sort_order", "is_active"):
                if key in data:
                    setattr(a, key, data[key])
            return jsonify({"ok": True})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/entities/<feature_key>/<int:assignment_id>", methods=["DELETE"])
def delete_entity(feature_key, assignment_id):
    """Remove an entity assignment."""
    from models import FeatureEntityAssignment
    try:
        with _get_session() as session:
            a = session.query(FeatureEntityAssignment).get(assignment_id)
            if not a or a.feature_key != feature_key:
                return jsonify({"error": "Not found"}), 404
            eid = a.entity_id
            role = a.role
            session.delete(a)
            _log_security_change("ENTITY_REMOVED", feature_key, f"{eid} ({role})")
            return jsonify({"ok": True})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/entities/<feature_key>/auto-detect", methods=["POST"])
def auto_detect_entities(feature_key):
    """Suggest entities for a feature based on HA state (not auto-save)."""
    suggestions = []
    ha = _ha()
    if not ha:
        return jsonify(suggestions)

    # Domain hints per feature_key
    # "device_classes" is a special filter key (not a role) for binary_sensor features
    DOMAIN_HINTS = {
        "fire_co":        {"trigger": ["binary_sensor"], "device_classes": ["smoke", "gas", "co"],
                           "emergency_light": ["light"], "emergency_cover": ["cover"],
                           "hvac": ["climate", "fan"], "emergency_lock": ["lock"], "tts_speaker": ["media_player"]},
        "water_leak":     {"trigger": ["binary_sensor"], "device_classes": ["moisture"],
                           "valve": ["valve", "switch"], "heating": ["climate"], "tts_speaker": ["media_player"]},
        "camera":         {"snapshot_camera": ["camera"]},
        "access":         {"lock": ["lock"]},
        "geofence":       {"person": ["person", "device_tracker"]},
        "party":          {"light": ["light"], "media": ["media_player"], "climate": ["climate"]},
        "cinema":         {"light": ["light"], "cover": ["cover"], "media": ["media_player"], "climate": ["climate"]},
        "home_office":    {"light": ["light"], "climate": ["climate"], "motion": ["binary_sensor"], "tts_speaker": ["media_player"]},
        "night_lockdown": {"lock": ["lock"], "motion": ["binary_sensor"], "night_light": ["light"],
                           "media": ["media_player"], "climate": ["climate"], "window_sensor": ["binary_sensor"]},
        "emergency":      {"siren": ["siren"], "light": ["light"], "lock": ["lock"],
                           "tts_speaker": ["media_player"], "cover": ["cover"], "hvac": ["climate"]},
    }

    hints = DOMAIN_HINTS.get(feature_key, {})
    device_classes_filter = hints.get("device_classes", [])
    try:
        all_states = ha.get_states() or []
        for role, domains in hints.items():
            if role == "device_classes":
                continue  # Skip metadata key
            for state_obj in all_states:
                eid = state_obj.get("entity_id", "")
                domain = eid.split(".")[0]
                if domain in domains:
                    attrs = state_obj.get("attributes", {})
                    dc = attrs.get("device_class", "")
                    if device_classes_filter and dc not in device_classes_filter:
                        continue
                    suggestions.append({
                        "entity_id": eid,
                        "role": role,
                        "name": attrs.get("friendly_name", eid),
                        "device_class": dc,
                    })
    except Exception as e:
        logger.error(f"Auto-detect error: {e}")

    return jsonify(suggestions)


# ==============================================================================
# Fire/CO Endpoints (#1)
# ==============================================================================

@security_bp.route("/api/security/fire-co/status", methods=["GET"])
def fire_co_status():
    mgr = _deps.get("fire_response_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_status())


@security_bp.route("/api/security/fire-co/config", methods=["GET"])
def fire_co_config_get():
    mgr = _deps.get("fire_response_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_config())


@security_bp.route("/api/security/fire-co/config", methods=["PUT"])
def fire_co_config_set():
    mgr = _deps.get("fire_response_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(mgr.set_config(data))


# ==============================================================================
# Water Leak Endpoints (#2)
# ==============================================================================

@security_bp.route("/api/security/water-leak/status", methods=["GET"])
def water_leak_status():
    mgr = _deps.get("water_leak_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_status())


@security_bp.route("/api/security/water-leak/config", methods=["GET"])
def water_leak_config_get():
    mgr = _deps.get("water_leak_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_config())


@security_bp.route("/api/security/water-leak/config", methods=["PUT"])
def water_leak_config_set():
    mgr = _deps.get("water_leak_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(mgr.set_config(data))


# ==============================================================================
# Camera Endpoints (#3)
# ==============================================================================

@security_bp.route("/api/security/cameras", methods=["GET"])
def cameras_list():
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_cameras())


@security_bp.route("/api/security/cameras/snapshots", methods=["GET"])
def camera_snapshots():
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    limit = max(1, min(500, request.args.get("limit", 50, type=int)))
    offset = max(0, request.args.get("offset", 0, type=int))
    return jsonify(mgr.get_snapshots(limit=limit, offset=offset))


@security_bp.route("/api/security/cameras/snapshots/<int:event_id>", methods=["GET"])
def camera_snapshot_get(event_id):
    """Get a single snapshot by security event ID."""
    from flask import send_file
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    from models import SecurityEvent
    try:
        with _get_session() as session:
            evt = session.query(SecurityEvent).get(event_id)
            if not evt or not evt.snapshot_path:
                return jsonify({"error": "Snapshot not found"}), 404
            import os
            SNAPSHOT_DIR = "/data/mindhome/snapshots"
            if not os.path.exists(evt.snapshot_path):
                return jsonify({"error": "Snapshot file missing"}), 404
            real_path = os.path.realpath(evt.snapshot_path)
            if not real_path.startswith(SNAPSHOT_DIR):
                return jsonify({"error": "Invalid snapshot path"}), 403
            return send_file(real_path, mimetype="image/jpeg")
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/cameras/snapshots/<int:event_id>", methods=["DELETE"])
def camera_snapshot_delete(event_id):
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    ok = mgr.delete_snapshot(event_id)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/cameras/<path:entity_id>/snapshot", methods=["POST"])
def camera_take_snapshot(entity_id):
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    path = mgr.take_snapshot(entity_id)
    if path:
        return jsonify({"ok": True, "path": path})
    return jsonify({"error": "Snapshot failed"}), 500


@security_bp.route("/api/security/cameras/config", methods=["GET"])
def camera_config_get():
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_config())


@security_bp.route("/api/security/cameras/config", methods=["PUT"])
def camera_config_set():
    mgr = _deps.get("camera_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(mgr.set_config(data))


# ==============================================================================
# Access Control Endpoints (#4)
# ==============================================================================

@security_bp.route("/api/security/access/locks", methods=["GET"])
def access_locks():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_locks())


@security_bp.route("/api/security/access/locks/<path:entity_id>/lock", methods=["POST"])
def access_lock(entity_id):
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    ok = mgr.lock(entity_id)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/access/locks/<path:entity_id>/unlock", methods=["POST"])
def access_unlock(entity_id):
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    ok = mgr.unlock(entity_id)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/access/lock-all", methods=["POST"])
def access_lock_all():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    results = mgr.lock_all()
    return jsonify(results)


@security_bp.route("/api/security/access/codes", methods=["GET"])
def access_codes_list():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_codes())


@security_bp.route("/api/security/access/codes", methods=["POST"])
def access_code_create():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    code = data.get("code")
    if not name or not code:
        return jsonify({"error": "name and code are required"}), 400
    code_id = mgr.create_code(
        name=name, code=code,
        user_id=data.get("user_id"),
        lock_entity_ids=data.get("lock_entity_ids"),
        valid_from=data.get("valid_from"),
        valid_until=data.get("valid_until"),
        is_temporary=data.get("is_temporary", False),
        max_uses=data.get("max_uses"),
    )
    if code_id:
        return jsonify({"id": code_id}), 201
    return jsonify({"error": "Creation failed"}), 500


@security_bp.route("/api/security/access/codes/<int:code_id>", methods=["PUT"])
def access_code_update(code_id):
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = mgr.update_code(code_id, data)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/access/codes/<int:code_id>", methods=["DELETE"])
def access_code_delete(code_id):
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    ok = mgr.delete_code(code_id)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/access/log", methods=["GET"])
def access_log():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    limit = max(1, min(500, request.args.get("limit", 50, type=int)))
    offset = max(0, request.args.get("offset", 0, type=int))
    entity_id = request.args.get("entity_id")
    return jsonify(mgr.get_log(limit=limit, offset=offset, entity_id=entity_id))


@security_bp.route("/api/security/access/config", methods=["GET"])
def access_config_get():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_config())


@security_bp.route("/api/security/access/config", methods=["PUT"])
def access_config_set():
    mgr = _deps.get("access_control_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(mgr.set_config(data))


# ==============================================================================
# Geo-Fencing Endpoints (#5)
# ==============================================================================

@security_bp.route("/api/security/geofence/zones", methods=["GET"])
def geofence_zones_list():
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_zones())


@security_bp.route("/api/security/geofence/zones", methods=["POST"])
def geofence_zone_create():
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    required = ("name", "latitude", "longitude", "radius_m")
    if not all(data.get(k) for k in required):
        return jsonify({"error": f"{', '.join(required)} are required"}), 400
    zone_id = mgr.create_zone(
        name=data["name"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        radius_m=data["radius_m"],
        user_id=data.get("user_id"),
        action_on_enter=data.get("action_on_enter"),
        action_on_leave=data.get("action_on_leave"),
    )
    if zone_id:
        return jsonify({"id": zone_id}), 201
    return jsonify({"error": "Creation failed"}), 500


@security_bp.route("/api/security/geofence/zones/<int:zone_id>", methods=["PUT"])
def geofence_zone_update(zone_id):
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = mgr.update_zone(zone_id, data)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/geofence/zones/<int:zone_id>", methods=["DELETE"])
def geofence_zone_delete(zone_id):
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    ok = mgr.delete_zone(zone_id)
    return jsonify({"ok": ok})


@security_bp.route("/api/security/geofence/status", methods=["GET"])
def geofence_status():
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_status())


@security_bp.route("/api/security/geofence/config", methods=["GET"])
def geofence_config_get():
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    return jsonify(mgr.get_config())


@security_bp.route("/api/security/geofence/config", methods=["PUT"])
def geofence_config_set():
    mgr = _deps.get("geofence_manager")
    if not mgr:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(mgr.set_config(data))


# ==============================================================================
# Special Modes Endpoints (#7-#11)
# ==============================================================================

def _mode_engine(mode_type):
    """Get the mode engine by type."""
    mapping = {
        "party": "party_mode",
        "cinema": "cinema_mode",
        "home-office": "home_office_mode",
        "night-lockdown": "night_lockdown",
        "emergency": "emergency_protocol",
    }
    key = mapping.get(mode_type)
    return _deps.get(key) if key else None


@security_bp.route("/api/security/modes/<mode_type>/activate", methods=["POST"])
def mode_activate(mode_type):
    engine = _mode_engine(mode_type)
    if not engine:
        return jsonify({"error": f"Unknown mode: {mode_type}"}), 404
    data = request.get_json(silent=True) or {}
    ok = engine.activate(
        user_id=data.get("user_id"),
        config_override=data.get("config"),
        reason=data.get("reason", "manual"),
    )
    return jsonify({"ok": ok, "is_active": engine.is_active})


@security_bp.route("/api/security/modes/<mode_type>/deactivate", methods=["POST"])
def mode_deactivate(mode_type):
    engine = _mode_engine(mode_type)
    if not engine:
        return jsonify({"error": f"Unknown mode: {mode_type}"}), 404
    data = request.get_json(silent=True) or {}
    ok = engine.deactivate(
        user_id=data.get("user_id"),
        reason=data.get("reason", "manual"),
    )
    return jsonify({"ok": ok, "is_active": engine.is_active})


@security_bp.route("/api/security/modes/<mode_type>/status", methods=["GET"])
def mode_status(mode_type):
    engine = _mode_engine(mode_type)
    if not engine:
        return jsonify({"error": f"Unknown mode: {mode_type}"}), 404
    return jsonify(engine.get_status())


@security_bp.route("/api/security/modes/<mode_type>/config", methods=["GET"])
def mode_config_get(mode_type):
    engine = _mode_engine(mode_type)
    if not engine:
        return jsonify({"error": f"Unknown mode: {mode_type}"}), 404
    return jsonify(engine.get_config())


@security_bp.route("/api/security/modes/<mode_type>/config", methods=["PUT"])
def mode_config_set(mode_type):
    engine = _mode_engine(mode_type)
    if not engine:
        return jsonify({"error": f"Unknown mode: {mode_type}"}), 404
    data = request.get_json(silent=True) or {}
    return jsonify(engine.set_config(data))


# ==============================================================================
# Emergency Protocol Endpoints (#11)
# ==============================================================================

@security_bp.route("/api/security/emergency/trigger", methods=["POST"])
def emergency_trigger():
    engine = _deps.get("emergency_protocol")
    if not engine:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = engine.trigger(
        emergency_type=data.get("type", "panic"),
        source=data.get("source", "manual"),
        user_id=data.get("user_id"),
    )
    return jsonify({"ok": ok, "is_active": engine.is_active})


@security_bp.route("/api/security/emergency/cancel", methods=["POST"])
def emergency_cancel():
    engine = _deps.get("emergency_protocol")
    if not engine:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = engine.cancel(pin=data.get("pin"), user_id=data.get("user_id"))
    if not ok:
        return jsonify({"error": "Cancel failed (wrong PIN or not active)"}), 403
    return jsonify({"ok": True})


@security_bp.route("/api/security/emergency/status", methods=["GET"])
def emergency_status():
    engine = _deps.get("emergency_protocol")
    if not engine:
        return jsonify({"error": "Not available"}), 503
    return jsonify(engine.get_status())


@security_bp.route("/api/security/emergency/config", methods=["GET"])
def emergency_config_get():
    engine = _deps.get("emergency_protocol")
    if not engine:
        return jsonify({"error": "Not available"}), 503
    return jsonify(engine.get_config())


@security_bp.route("/api/security/emergency/config", methods=["PUT"])
def emergency_config_set():
    engine = _deps.get("emergency_protocol")
    if not engine:
        return jsonify({"error": "Not available"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(engine.set_config(data))


@security_bp.route("/api/security/emergency/contacts", methods=["GET"])
def emergency_contacts_list():
    from models import EmergencyContact
    try:
        with _get_session() as session:
            contacts = session.query(EmergencyContact).filter_by(is_active=True).order_by(
                EmergencyContact.priority
            ).all()
            return jsonify([{
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "notify_method": c.notify_method,
                "priority": c.priority,
                "is_active": c.is_active,
            } for c in contacts])
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/emergency/contacts", methods=["POST"])
def emergency_contact_create():
    from models import EmergencyContact
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    try:
        with _get_session() as session:
            c = EmergencyContact(
                name=data["name"],
                phone=data.get("phone"),
                email=data.get("email"),
                notify_method=data.get("notify_method", "push"),
                priority=data.get("priority", 0),
                is_active=True,
            )
            session.add(c)
            session.flush()
            return jsonify({"id": c.id}), 201
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/emergency/contacts/<int:contact_id>", methods=["PUT"])
def emergency_contact_update(contact_id):
    from models import EmergencyContact
    data = request.get_json(silent=True) or {}
    try:
        with _get_session() as session:
            c = session.query(EmergencyContact).get(contact_id)
            if not c:
                return jsonify({"error": "Not found"}), 404
            for key in ("name", "phone", "email", "notify_method", "priority", "is_active"):
                if key in data:
                    setattr(c, key, data[key])
            return jsonify({"ok": True})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/emergency/contacts/<int:contact_id>", methods=["DELETE"])
def emergency_contact_delete(contact_id):
    from models import EmergencyContact
    try:
        with _get_session() as session:
            c = session.query(EmergencyContact).get(contact_id)
            if not c:
                return jsonify({"error": "Not found"}), 404
            c.is_active = False
            return jsonify({"ok": True})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


# ==============================================================================
# Security Dashboard (#6)
# ==============================================================================

@security_bp.route("/api/security/dashboard", methods=["GET"])
def security_dashboard():
    """Aggregated security overview."""
    if not is_phase5_feature_enabled("phase5.security_dashboard"):
        return jsonify({"error": "Feature disabled"}), 403

    dashboard = {
        "alarm_status": None,
        "locks": [],
        "cameras": [],
        "fire_co_status": None,
        "water_leak_status": None,
        "geofence_persons": [],
        "active_modes": [],
        "recent_events": [],
    }

    # Alarm panel (read-only)
    ha = _ha()
    if ha:
        try:
            states = ha.get_states() or []
            for s in states:
                if s.get("entity_id", "").startswith("alarm_control_panel."):
                    dashboard["alarm_status"] = {
                        "entity_id": s["entity_id"],
                        "state": s.get("state"),
                        "name": s.get("attributes", {}).get("friendly_name"),
                    }
                    break
        except Exception:
            pass

    # Locks
    mgr = _deps.get("access_control_manager")
    if mgr:
        dashboard["locks"] = mgr.get_locks()

    # Cameras
    mgr = _deps.get("camera_manager")
    if mgr:
        dashboard["cameras"] = mgr.get_cameras()

    # Fire/CO
    mgr = _deps.get("fire_response_manager")
    if mgr:
        dashboard["fire_co_status"] = mgr.get_status()

    # Water leak
    mgr = _deps.get("water_leak_manager")
    if mgr:
        dashboard["water_leak_status"] = mgr.get_status()

    # Geofence
    mgr = _deps.get("geofence_manager")
    if mgr:
        dashboard["geofence_persons"] = mgr.get_status()

    # Active modes
    for mode_key in ("party_mode", "cinema_mode", "home_office_mode", "night_lockdown", "emergency_protocol"):
        engine = _deps.get(mode_key)
        if engine and engine.is_active:
            dashboard["active_modes"].append(engine.get_status())

    # Recent events
    try:
        from models import SecurityEvent
        with _get_session() as session:
            events = session.query(SecurityEvent).order_by(
                SecurityEvent.timestamp.desc()
            ).limit(20).all()
            for evt in events:
                dashboard["recent_events"].append({
                    "id": evt.id,
                    "event_type": evt.event_type.value if evt.event_type else None,
                    "severity": evt.severity.value if evt.severity else None,
                    "message_de": evt.message_de,
                    "message_en": evt.message_en,
                    "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
                })
    except Exception:
        pass

    return jsonify(dashboard)


@security_bp.route("/api/security/events", methods=["GET"])
def security_events():
    """Get security event log (paginated, filterable)."""
    from models import SecurityEvent
    limit = max(1, min(500, request.args.get("limit", 50, type=int)))
    offset = max(0, request.args.get("offset", 0, type=int))
    event_type = request.args.get("type")

    try:
        with _get_session() as session:
            q = session.query(SecurityEvent).order_by(SecurityEvent.timestamp.desc())
            if event_type:
                from models import SecurityEventType
                try:
                    event_type_enum = SecurityEventType(event_type)
                    q = q.filter(SecurityEvent.event_type == event_type_enum)
                except ValueError:
                    q = q.filter(SecurityEvent.event_type == event_type)
            events = q.offset(offset).limit(limit).all()
            return jsonify([{
                "id": evt.id,
                "event_type": evt.event_type.value if evt.event_type else None,
                "severity": evt.severity.value if evt.severity else None,
                "device_id": evt.device_id,
                "room_id": evt.room_id,
                "message_de": evt.message_de,
                "message_en": evt.message_en,
                "resolved_at": evt.resolved_at.isoformat() if evt.resolved_at else None,
                "resolved_by": evt.resolved_by,
                "snapshot_path": evt.snapshot_path,
                "context": evt.context,
                "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
            } for evt in events])
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@security_bp.route("/api/security/events/stats", methods=["GET"])
def security_event_stats():
    """Get security event statistics."""
    from models import SecurityEvent
    from sqlalchemy import func
    try:
        with _get_session() as session:
            total = session.query(func.count(SecurityEvent.id)).scalar() or 0
            by_type = {}
            for row in session.query(
                SecurityEvent.event_type, func.count(SecurityEvent.id)
            ).group_by(SecurityEvent.event_type).all():
                by_type[row[0].value if row[0] else "unknown"] = row[1]
            return jsonify({"total": total, "by_type": by_type})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500
