# MindHome - routes/covers.py | see version.py for version info
"""
MindHome API Routes - Cover / Shutter Control (Phase 5)
16th Flask Blueprint: cover status, groups, scenes, schedules,
per-cover config, automation settings, manual control.
"""

import logging
import json
from flask import Blueprint, request, jsonify

from helpers import get_setting, set_setting

logger = logging.getLogger("mindhome.routes.covers")

covers_bp = Blueprint("covers", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_covers(dependencies):
    """Initialize cover routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _mgr():
    """Get CoverControlManager instance."""
    return _deps.get("cover_control_manager")


def _get_session():
    from db import get_db_session
    return get_db_session()


def is_cover_control_enabled():
    """Check if cover control feature is enabled."""
    stored = get_setting("phase5.cover_control")
    if stored == "false":
        return False
    return True


# ==============================================================================
# Status & Overview
# ==============================================================================

@covers_bp.route("/api/covers/status", methods=["GET"])
def get_cover_status():
    """Get full cover system status."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    if not is_cover_control_enabled():
        return jsonify({"enabled": False, "covers": []}), 200
    return jsonify(mgr.get_status()), 200


@covers_bp.route("/api/covers", methods=["GET"])
def get_covers():
    """Get all configured cover entities with state."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    return jsonify(mgr.get_covers()), 200


# ==============================================================================
# Manual Control
# ==============================================================================

@covers_bp.route("/api/covers/<path:entity_id>/position", methods=["POST"])
def set_cover_position(entity_id):
    """Set cover position (0=closed, 100=open)."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    position = data.get("position")
    if position is None:
        return jsonify({"error": "position required"}), 400
    try:
        position = int(position)
    except (ValueError, TypeError):
        return jsonify({"error": "position must be integer 0-100"}), 400
    ok = mgr.set_position(entity_id, position, source="manual")
    return jsonify({"success": ok}), 200 if ok else 500


@covers_bp.route("/api/covers/<path:entity_id>/tilt", methods=["POST"])
def set_cover_tilt(entity_id):
    """Set cover tilt position (0-100)."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    tilt = data.get("tilt")
    if tilt is None:
        return jsonify({"error": "tilt required"}), 400
    try:
        tilt = int(tilt)
    except (ValueError, TypeError):
        return jsonify({"error": "tilt must be integer 0-100"}), 400
    ok = mgr.set_tilt(entity_id, tilt, source="manual")
    return jsonify({"success": ok}), 200 if ok else 500


@covers_bp.route("/api/covers/<path:entity_id>/open", methods=["POST"])
def open_cover(entity_id):
    """Fully open a cover."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    ok = mgr.open_cover(entity_id, source="manual")
    return jsonify({"success": ok}), 200 if ok else 500


@covers_bp.route("/api/covers/<path:entity_id>/close", methods=["POST"])
def close_cover(entity_id):
    """Fully close a cover."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    ok = mgr.close_cover(entity_id, source="manual")
    return jsonify({"success": ok}), 200 if ok else 500


# ==============================================================================
# Cover Config (per-entity: facade, floor, type)
# ==============================================================================

@covers_bp.route("/api/covers/configs", methods=["GET"])
def get_cover_configs():
    """Get all per-cover configs."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    return jsonify(mgr.get_cover_configs()), 200


@covers_bp.route("/api/covers/<path:entity_id>/config", methods=["PUT"])
def set_cover_config(entity_id):
    """Set per-cover config (facade, floor, cover_type, group_ids)."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = mgr.set_cover_config(
        entity_id,
        facade=data.get("facade"),
        floor=data.get("floor"),
        cover_type=data.get("cover_type"),
        group_ids=data.get("group_ids"),
    )
    return jsonify({"success": ok}), 200 if ok else 500


# ==============================================================================
# Groups CRUD
# ==============================================================================

@covers_bp.route("/api/covers/groups", methods=["GET"])
def get_groups():
    """Get all cover groups."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    return jsonify(mgr.get_groups()), 200


@covers_bp.route("/api/covers/groups", methods=["POST"])
def create_group():
    """Create a new cover group."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    group_id = mgr.create_group(
        name=name,
        entity_ids=data.get("entity_ids", []),
        icon=data.get("icon"),
    )
    if group_id:
        return jsonify({"id": group_id}), 201
    return jsonify({"error": "Failed to create group"}), 500


@covers_bp.route("/api/covers/groups/<int:group_id>", methods=["PUT"])
def update_group(group_id):
    """Update a cover group."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = mgr.update_group(group_id, data)
    return jsonify({"success": ok}), 200 if ok else 404


@covers_bp.route("/api/covers/groups/<int:group_id>", methods=["DELETE"])
def delete_group(group_id):
    """Delete (soft) a cover group."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    ok = mgr.delete_group(group_id)
    return jsonify({"success": ok}), 200 if ok else 404


@covers_bp.route("/api/covers/groups/<int:group_id>/control", methods=["POST"])
def control_group(group_id):
    """Set position for all covers in a group."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    position = data.get("position")
    if position is None:
        return jsonify({"error": "position required"}), 400
    try:
        position = int(position)
    except (ValueError, TypeError):
        return jsonify({"error": "position must be integer 0-100"}), 400
    results = mgr.control_group(group_id, position, source="manual")
    return jsonify({"results": results}), 200


# ==============================================================================
# Scenes CRUD
# ==============================================================================

@covers_bp.route("/api/covers/scenes", methods=["GET"])
def get_scenes():
    """Get all cover scenes."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    return jsonify(mgr.get_scenes()), 200


@covers_bp.route("/api/covers/scenes", methods=["POST"])
def create_scene():
    """Create a new cover scene."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    scene_id = mgr.create_scene(
        name=name,
        positions=data.get("positions", {}),
        name_en=data.get("name_en"),
        icon=data.get("icon"),
    )
    if scene_id:
        return jsonify({"id": scene_id}), 201
    return jsonify({"error": "Failed to create scene"}), 500


@covers_bp.route("/api/covers/scenes/<int:scene_id>", methods=["PUT"])
def update_scene(scene_id):
    """Update a cover scene."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = mgr.update_scene(scene_id, data)
    return jsonify({"success": ok}), 200 if ok else 404


@covers_bp.route("/api/covers/scenes/<int:scene_id>", methods=["DELETE"])
def delete_scene(scene_id):
    """Delete (soft) a cover scene."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    ok = mgr.delete_scene(scene_id)
    return jsonify({"success": ok}), 200 if ok else 404


@covers_bp.route("/api/covers/scenes/<int:scene_id>/activate", methods=["POST"])
def activate_scene(scene_id):
    """Activate a cover scene."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    ok = mgr.activate_scene(scene_id)
    return jsonify({"success": ok}), 200 if ok else 404


# ==============================================================================
# Schedules CRUD
# ==============================================================================

@covers_bp.route("/api/covers/schedules", methods=["GET"])
def get_schedules():
    """Get all cover schedules."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    entity_id = request.args.get("entity_id")
    group_id = request.args.get("group_id", type=int)
    return jsonify(mgr.get_schedules(entity_id=entity_id, group_id=group_id)), 200


@covers_bp.route("/api/covers/schedules", methods=["POST"])
def create_schedule():
    """Create a new cover schedule."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    time_str = data.get("time_str")
    if not time_str:
        return jsonify({"error": "time_str required"}), 400
    schedule_id = mgr.create_schedule(
        entity_id=data.get("entity_id"),
        group_id=data.get("group_id"),
        time_str=time_str,
        days=data.get("days"),
        position=data.get("position", 100),
        tilt=data.get("tilt"),
        presence_mode=data.get("presence_mode"),
    )
    if schedule_id:
        return jsonify({"id": schedule_id}), 201
    return jsonify({"error": "Failed to create schedule"}), 500


@covers_bp.route("/api/covers/schedules/<int:schedule_id>", methods=["PUT"])
def update_schedule(schedule_id):
    """Update a cover schedule."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    ok = mgr.update_schedule(schedule_id, data)
    return jsonify({"success": ok}), 200 if ok else 404


@covers_bp.route("/api/covers/schedules/<int:schedule_id>", methods=["DELETE"])
def delete_schedule(schedule_id):
    """Delete (soft) a cover schedule."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    ok = mgr.delete_schedule(schedule_id)
    return jsonify({"success": ok}), 200 if ok else 404


# ==============================================================================
# Automation Settings
# ==============================================================================

@covers_bp.route("/api/covers/settings", methods=["GET"])
def get_cover_settings():
    """Get cover automation settings."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    return jsonify(mgr.get_config()), 200


@covers_bp.route("/api/covers/settings", methods=["PUT"])
def update_cover_settings():
    """Update cover automation settings."""
    mgr = _mgr()
    if not mgr:
        return jsonify({"error": "Cover control not available"}), 503
    data = request.get_json(silent=True) or {}
    config = mgr.set_config(data)
    return jsonify(config), 200


@covers_bp.route("/api/covers/feature-flag", methods=["GET"])
def get_cover_feature_flag():
    """Get cover control feature flag state."""
    enabled = is_cover_control_enabled()
    return jsonify({"enabled": enabled, "key": "phase5.cover_control"}), 200


@covers_bp.route("/api/covers/feature-flag", methods=["PUT"])
def set_cover_feature_flag():
    """Enable/disable cover control."""
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)
    set_setting("phase5.cover_control", "true" if enabled else "false")
    return jsonify({"enabled": enabled}), 200


# ==============================================================================
# Entity Assignment (cover_control entities)
# ==============================================================================

@covers_bp.route("/api/covers/entities", methods=["GET"])
def get_cover_entities():
    """Get all entities assigned to cover_control feature."""
    from models import FeatureEntityAssignment
    try:
        with _get_session() as session:
            assignments = session.query(FeatureEntityAssignment).filter_by(
                feature_key="cover_control", is_active=True
            ).order_by(FeatureEntityAssignment.sort_order).all()
            result = []
            for a in assignments:
                result.append({
                    "id": a.id,
                    "entity_id": a.entity_id,
                    "role": a.role,
                    "config": a.config,
                    "sort_order": a.sort_order,
                })
            return jsonify(result), 200
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@covers_bp.route("/api/covers/entities", methods=["POST"])
def add_cover_entity():
    """Assign an entity to cover_control feature."""
    from models import FeatureEntityAssignment
    data = request.get_json(silent=True) or {}
    entity_id = data.get("entity_id")
    role = data.get("role", "cover")
    if not entity_id:
        return jsonify({"error": "entity_id required"}), 400
    try:
        with _get_session() as session:
            existing = session.query(FeatureEntityAssignment).filter_by(
                feature_key="cover_control", entity_id=entity_id, role=role
            ).first()
            if existing:
                existing.is_active = True
                existing.config = data.get("config")
                return jsonify({"id": existing.id, "reactivated": True}), 200
            a = FeatureEntityAssignment(
                feature_key="cover_control",
                entity_id=entity_id,
                role=role,
                config=data.get("config"),
                sort_order=data.get("sort_order", 0),
                is_active=True,
            )
            session.add(a)
            session.flush()
            return jsonify({"id": a.id}), 201
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@covers_bp.route("/api/covers/entities/<int:assignment_id>", methods=["DELETE"])
def remove_cover_entity(assignment_id):
    """Remove (soft-delete) an entity from cover_control feature."""
    from models import FeatureEntityAssignment
    try:
        with _get_session() as session:
            a = session.query(FeatureEntityAssignment).get(assignment_id)
            if not a or a.feature_key != "cover_control":
                return jsonify({"error": "Not found"}), 404
            a.is_active = False
            return jsonify({"success": True}), 200
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


# ==============================================================================
# Auto-detect available cover entities from HA
# ==============================================================================

@covers_bp.route("/api/covers/discover", methods=["GET"])
def discover_covers():
    """Discover available cover entities from Home Assistant."""
    ha = _deps.get("ha")
    if not ha:
        return jsonify({"error": "HA not connected"}), 503

    try:
        states = ha.get_states() or []
        covers = []
        sensors = []

        for s in states:
            eid = s.get("entity_id", "")
            attrs = s.get("attributes", {})
            friendly = attrs.get("friendly_name", eid)
            device_class = attrs.get("device_class", "")

            if eid.startswith("cover."):
                covers.append({
                    "entity_id": eid,
                    "name": friendly,
                    "device_class": device_class or "shutter",
                    "state": s.get("state"),
                    "suggested_role": "cover",
                })
            elif eid.startswith("sensor."):
                if device_class == "illuminance":
                    sensors.append({
                        "entity_id": eid, "name": friendly,
                        "suggested_role": "sun_sensor",
                    })
                elif device_class == "temperature":
                    role = "temp_outdoor" if "out" in eid.lower() or "außen" in friendly.lower() else "temp_indoor"
                    sensors.append({
                        "entity_id": eid, "name": friendly,
                        "suggested_role": role,
                    })
                elif device_class == "wind_speed":
                    sensors.append({
                        "entity_id": eid, "name": friendly,
                        "suggested_role": "wind_sensor",
                    })
            elif eid.startswith("binary_sensor."):
                if device_class == "moisture" or "rain" in eid.lower() or "regen" in friendly.lower():
                    sensors.append({
                        "entity_id": eid, "name": friendly,
                        "suggested_role": "rain_sensor",
                    })

        return jsonify({"covers": covers, "sensors": sensors}), 200
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500
