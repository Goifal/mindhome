# MindHome - routes/devices.py | see version.py for version info
"""
MindHome API Routes - Devices
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

logger = logging.getLogger("mindhome.routes.devices")

devices_bp = Blueprint("devices", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_devices(dependencies):
    """Initialize devices routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")


def _cleanup_device_references(session, device_id):
    """Remove or nullify all foreign key references to a device before deletion."""
    # Nullable FKs: set to NULL (preserve historical data)
    session.query(ActionLog).filter(ActionLog.device_id == device_id).update(
        {"device_id": None}, synchronize_session=False
    )
    session.query(AnomalySetting).filter(AnomalySetting.device_id == device_id).update(
        {"device_id": None}, synchronize_session=False
    )
    session.query(EnergyReading).filter(EnergyReading.device_id == device_id).update(
        {"device_id": None}, synchronize_session=False
    )
    session.query(StandbyConfig).filter(StandbyConfig.device_id == device_id).update(
        {"device_id": None}, synchronize_session=False
    )
    session.query(StateHistory).filter(StateHistory.device_id == device_id).update(
        {"device_id": None}, synchronize_session=False
    )
    # Non-nullable FK: must delete
    session.query(DeviceMute).filter(DeviceMute.device_id == device_id).delete(
        synchronize_session=False
    )


@devices_bp.route("/api/devices", methods=["GET"])
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
                state = _ha().get_state(d.ha_entity_id)
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



@devices_bp.route("/api/devices/<int:device_id>", methods=["PUT"])
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



@devices_bp.route("/api/devices/bulk", methods=["PUT"])
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



@devices_bp.route("/api/devices/bulk", methods=["DELETE"])
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
                _cleanup_device_references(session, did)
                session.delete(device)
                deleted += 1

        session.commit()
        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        session.rollback()
        logger.error(f"Bulk delete error: {e}")
        return jsonify({"error": "Fehler beim Loeschen"}), 500
    finally:
        session.close()



@devices_bp.route("/api/devices/<int:device_id>", methods=["DELETE"])
def api_delete_device(device_id):
    """Delete a device."""
    session = get_db()
    try:
        device = session.get(Device, device_id)
        if not device:
            return jsonify({"error": "Device not found"}), 404
        _cleanup_device_references(session, device_id)
        session.delete(device)
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        logger.error(f"Delete device {device_id} error: {e}")
        return jsonify({"error": "Fehler beim Loeschen"}), 500
    finally:
        session.close()



@devices_bp.route("/api/discover", methods=["GET"])
def api_discover_devices():
    """Discover all HA devices grouped by MindHome domain."""
    discovered = _ha().discover_devices()

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
        "ha_connected": _ha().is_connected()
    })



@devices_bp.route("/api/discover/import", methods=["POST"])
def api_import_discovered():
    """Import selected discovered devices into MindHome."""
    data = request.json
    session = get_db()
    try:
        imported_count = 0
        skipped_count = 0
        selected_ids = data.get("selected_entities", [])

        # Fix 21: Get HA entity registry for area assignments
        entity_registry = _ha().get_entity_registry() or []
        device_registry = _ha().get_device_registry() or []

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
            "message": f"{imported_count} importiert, {skipped_count} übersprungen (bereits vorhanden)"
        })
    finally:
        session.close()



@devices_bp.route("/api/discover/all-entities", methods=["GET"])
def api_get_all_ha_entities():
    """Get all HA entities for manual device search."""
    states = _ha().get_states() or []
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



@devices_bp.route("/api/devices/manual-add", methods=["POST"])
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
        state = _ha().get_state(entity_id)
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



@devices_bp.route("/api/discover/areas", methods=["GET"])
def api_discover_areas():
    """Get areas (rooms) from HA."""
    areas = _ha().get_areas()
    return jsonify({"areas": areas or []})

