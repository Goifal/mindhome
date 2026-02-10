# MindHome - routes/scenes.py | see version.py for version info
"""
MindHome API Routes - Scenes
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

logger = logging.getLogger("mindhome.routes.scenes")

scenes_bp = Blueprint("scenes", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_scenes(dependencies):
    """Initialize scenes routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@scenes_bp.route("/api/scenes", methods=["GET"])
def api_get_scenes():
    session = get_db()
    try:
        return jsonify([{"id":s.id,"room_id":s.room_id,"name_de":s.name_de,"name_en":s.name_en,"icon":s.icon,"states":s.states or [],"frequency":s.frequency,"status":s.status,"source":s.source,"is_active":s.is_active,"last_activated":s.last_activated.isoformat() if s.last_activated else None} for s in session.query(LearnedScene).order_by(LearnedScene.frequency.desc()).all()])
    finally:
        session.close()


@scenes_bp.route("/api/scenes", methods=["POST"])
def api_create_scene():
    data = request.json or {}
    session = get_db()
    try:
        scene = LearnedScene(room_id=data.get("room_id"), name_de=data.get("name_de","Neue Szene"), name_en=data.get("name_en","New Scene"), icon=data.get("icon","mdi:palette"), states=data.get("states",[]), status="accepted", source="manual", schedule_cron=data.get("schedule_cron"), schedule_enabled=data.get("schedule_enabled", False), action_delay_seconds=data.get("action_delay_seconds", 0))
        session.add(scene); session.commit()
        audit_log("scene_create", f"Scene: {scene.name_de}")
        return jsonify({"id": scene.id, "success": True})
    finally:
        session.close()


@scenes_bp.route("/api/scenes/<int:scene_id>", methods=["PUT"])
def api_update_scene(scene_id):
    data = request.json or {}
    session = get_db()
    try:
        scene = session.get(LearnedScene, scene_id)
        if not scene: return jsonify({"error": "Not found"}), 404
        for key in ["name_de","name_en","icon","states","status","is_active","schedule_cron","schedule_enabled","action_delay_seconds"]:
            if key in data: setattr(scene, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@scenes_bp.route("/api/scenes/<int:scene_id>/activate", methods=["POST"])
def api_activate_scene(scene_id):
    session = get_db()
    try:
        scene = session.get(LearnedScene, scene_id)
        if not scene: return jsonify({"error": "Not found"}), 404
        for si in (scene.states or []):
            eid = si.get("entity_id","")
            ts = si.get("state","")
            attrs = si.get("attributes",{})
            if eid:
                domain = eid.split(".")[0]
                if ts == "on": _ha().call_service(domain, "turn_on", attrs, entity_id=eid)
                elif ts == "off": _ha().call_service(domain, "turn_off", entity_id=eid)
        scene.last_activated = datetime.now(timezone.utc)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@scenes_bp.route("/api/scenes/<int:scene_id>", methods=["DELETE"])
def api_delete_scene(scene_id):
    session = get_db()
    try:
        scene = session.get(LearnedScene, scene_id)
        if scene: session.delete(scene); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@scenes_bp.route("/api/scenes/snapshot", methods=["POST"])
def api_scene_snapshot():
    """Create scene from current room state."""
    data = request.json or {}
    room_id = data.get("room_id")
    if not room_id:
        return jsonify({"error": "room_id required"}), 400
    session = get_db()
    try:
        devices = session.query(Device).filter_by(room_id=room_id, is_active=True).all()
        states = []
        for d in devices:
            if d.entity_id:
                try:
                    st = _ha().get_state(d.entity_id)
                    if st:
                        states.append({"entity_id": d.entity_id, "state": st.get("state","off"), "attributes": st.get("attributes",{})})
                except:
                    pass
        room = session.get(Room, room_id)
        room_name = room.name if room else "Raum"
        scene = LearnedScene(
            room_id=room_id, name_de=f"Snapshot {room_name}", name_en=f"Snapshot {room_name}",
            icon="mdi:camera", states=states, status="accepted", source="snapshot"
        )
        session.add(scene); session.commit()
        return jsonify({"id": scene.id, "success": True, "device_count": len(states)})
    finally:
        session.close()


@scenes_bp.route("/api/scenes/suggestions", methods=["GET"])
def api_scene_suggestions():
    """Get scene suggestions from pattern engine."""
    session = get_db()
    try:
        # Find patterns that look like scenes (multiple devices, same time)
        patterns = session.query(LearnedPattern).filter(
            LearnedPattern.pattern_type == "scene",
            LearnedPattern.status.in_(["suggested", "active"])
        ).order_by(LearnedPattern.match_count.desc()).limit(20).all()
        suggestions = []
        for p in patterns:
            suggestions.append({
                "id": p.id, "description": p.description,
                "entities": p.entities, "match_count": p.match_count,
                "confidence": p.confidence, "status": p.status
            })
        return jsonify(suggestions)
    finally:
        session.close()
