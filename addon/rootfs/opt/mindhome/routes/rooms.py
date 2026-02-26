# MindHome - routes/rooms.py | see version.py for version info
"""
MindHome API Routes - Rooms
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

logger = logging.getLogger("mindhome.routes.rooms")

rooms_bp = Blueprint("rooms", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_rooms(dependencies):
    """Initialize rooms routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@rooms_bp.route("/api/rooms", methods=["GET"])
def api_get_rooms():
    """Get all rooms with last activity info."""
    with get_db_session() as session:
        rooms = session.query(Room).filter_by(is_active=True).all()
        enabled_domains = session.query(Domain).filter_by(is_enabled=True).all()

        # Auto-sync: create missing RoomDomainState entries
        created = 0
        for r in rooms:
            existing_domain_ids = {ds.domain_id for ds in r.domain_states}
            device_domain_ids_for_room = {d.domain_id for d in r.devices}
            for domain in enabled_domains:
                if domain.id not in existing_domain_ids and domain.id in device_domain_ids_for_room:
                    session.add(RoomDomainState(
                        room_id=r.id,
                        domain_id=domain.id,
                        learning_phase=LearningPhase.OBSERVING
                    ))
                    created += 1
        if created:
            session.commit()
            # Refresh rooms to include new states
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
                    "is_paused": ds.is_paused,
                    "mode": getattr(ds, 'mode', 'global') or 'global'
                } for ds in r.domain_states if ds.domain_id in device_domain_ids]
            })
        return jsonify(result)



@rooms_bp.route("/api/rooms", methods=["POST"])
def api_create_room():
    """Create a new room."""
    data = request.json or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    with get_db_session() as session:
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



@rooms_bp.route("/api/rooms/import-from-ha", methods=["POST"])
def api_import_rooms_from_ha():
    """Import rooms from HA Areas."""
    with get_db_session() as session:
        areas = _ha().get_areas() or []
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



@rooms_bp.route("/api/rooms/<int:room_id>", methods=["PUT"])
def api_update_room(room_id):
    """Update a room."""
    data = request.json
    with get_db_session() as session:
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



@rooms_bp.route("/api/rooms/<int:room_id>", methods=["DELETE"])
def api_delete_room(room_id):
    """Delete a room."""
    with get_db_session() as session:
        room = session.get(Room, room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        room.is_active = False  # Soft delete
        session.commit()
        return jsonify({"success": True})



@rooms_bp.route("/api/rooms/<int:room_id>/privacy", methods=["PUT"])
def api_update_room_privacy(room_id):
    """Update privacy mode for a room."""
    data = request.json
    with get_db_session() as session:
        room = session.get(Room, room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        room.privacy_mode = data.get("privacy_mode", {})
        session.commit()
        return jsonify({"id": room.id, "privacy_mode": room.privacy_mode})



@rooms_bp.route("/api/room-orientations", methods=["GET"])
def api_get_room_orientations():
    with get_db_session() as session:
        return jsonify([{"id":o.id,"room_id":o.room_id,"orientation":o.orientation,"offset_minutes":o.offset_minutes} for o in session.query(RoomOrientation).all()])


@rooms_bp.route("/api/room-orientations/<int:room_id>", methods=["PUT"])
def api_set_room_orientation(room_id):
    data = request.json or {}
    with get_db_session() as session:
        existing = session.query(RoomOrientation).filter_by(room_id=room_id).first()
        if existing:
            existing.orientation = data.get("orientation", existing.orientation)
            existing.offset_minutes = data.get("offset_minutes", existing.offset_minutes)
        else:
            session.add(RoomOrientation(room_id=room_id, orientation=data.get("orientation","S"), offset_minutes=data.get("offset_minutes",0)))
        session.commit()
        return jsonify({"success": True})
