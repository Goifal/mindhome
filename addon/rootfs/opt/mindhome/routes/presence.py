# MindHome - routes/presence.py | see version.py for version info
"""
MindHome API Routes - Presence
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

logger = logging.getLogger("mindhome.routes.presence")

presence_bp = Blueprint("presence", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_presence(dependencies):
    """Initialize presence routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@presence_bp.route("/api/day-phases", methods=["GET"])
def api_get_day_phases():
    session = get_db()
    try:
        phases = session.query(DayPhase).order_by(DayPhase.sort_order).all()
        return jsonify([{
            "id": p.id, "name_de": p.name_de, "name_en": p.name_en,
            "icon": p.icon, "color": p.color, "sort_order": p.sort_order,
            "start_type": p.start_type, "start_time": p.start_time,
            "sun_event": p.sun_event, "sun_offset_minutes": p.sun_offset_minutes,
            "is_active": p.is_active,
        } for p in phases])
    finally:
        session.close()


@presence_bp.route("/api/day-phases", methods=["POST"])
def api_create_day_phase():
    data = request.json or {}
    session = get_db()
    try:
        phase = DayPhase(
            name_de=data.get("name_de", "Neue Phase"), name_en=data.get("name_en", "New Phase"),
            icon=data.get("icon", "mdi:weather-sunset"), color=data.get("color", "#FFA500"),
            sort_order=data.get("sort_order", 0), start_type=data.get("start_type", "time"),
            start_time=data.get("start_time"), sun_event=data.get("sun_event"),
            sun_offset_minutes=data.get("sun_offset_minutes", 0), is_active=data.get("is_active", True),
        )
        session.add(phase)
        session.commit()
        audit_log("day_phase_create", f"Phase: {phase.name_de}")
        return jsonify({"id": phase.id, "success": True})
    finally:
        session.close()


@presence_bp.route("/api/day-phases/<int:phase_id>", methods=["PUT"])
def api_update_day_phase(phase_id):
    data = request.json or {}
    session = get_db()
    try:
        phase = session.get(DayPhase, phase_id)
        if not phase: return jsonify({"error": "Not found"}), 404
        for key in ["name_de","name_en","icon","color","sort_order","start_type","start_time","sun_event","sun_offset_minutes","is_active"]:
            if key in data: setattr(phase, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/day-phases/<int:phase_id>", methods=["DELETE"])
def api_delete_day_phase(phase_id):
    session = get_db()
    try:
        phase = session.get(DayPhase, phase_id)
        if phase: session.delete(phase); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/day-phases/current", methods=["GET"])
def api_current_day_phase():
    try:
        from ml.pattern_engine import ContextBuilder
        builder = ContextBuilder(ha_connection, engine)
        ctx = builder.build()
        return jsonify({"day_phase": ctx.get("day_phase","unknown"), "day_phase_id": ctx.get("day_phase_id"), "time_slot": ctx.get("time_slot"), "is_dark": ctx.get("is_dark",False)})
    except Exception as e:
        return jsonify({"day_phase": "unknown", "error": str(e)})


@presence_bp.route("/api/presence-modes", methods=["GET"])
def api_get_presence_modes():
    session = get_db()
    try:
        return jsonify([{"id":m.id,"name_de":m.name_de,"name_en":m.name_en,"icon":m.icon,"color":m.color,"priority":m.priority,"buffer_minutes":m.buffer_minutes,"actions":m.actions or [],"trigger_type":m.trigger_type,"auto_config":m.auto_config,"notify_on_enter":m.notify_on_enter,"notify_on_leave":m.notify_on_leave,"is_system":m.is_system,"is_active":m.is_active} for m in session.query(PresenceMode).order_by(PresenceMode.priority.desc()).all()])
    finally:
        session.close()


@presence_bp.route("/api/presence-modes", methods=["POST"])
def api_create_presence_mode():
    data = request.json or {}
    session = get_db()
    try:
        mode = PresenceMode(name_de=data.get("name_de","Neuer Modus"), name_en=data.get("name_en","New Mode"), icon=data.get("icon","mdi:home"), color=data.get("color","#4CAF50"), priority=data.get("priority",0), buffer_minutes=data.get("buffer_minutes",5), actions=data.get("actions"), trigger_type=data.get("trigger_type","manual"), auto_config=data.get("auto_config"), is_active=data.get("is_active",True))
        session.add(mode)
        session.commit()
        return jsonify({"id": mode.id, "success": True})
    finally:
        session.close()


@presence_bp.route("/api/presence-modes/<int:mode_id>", methods=["PUT"])
def api_update_presence_mode(mode_id):
    data = request.json or {}
    session = get_db()
    try:
        mode = session.get(PresenceMode, mode_id)
        if not mode: return jsonify({"error": "Not found"}), 404
        for key in ["name_de","name_en","icon","color","priority","buffer_minutes","actions","trigger_type","auto_config","notify_on_enter","notify_on_leave","is_active"]:
            if key in data: setattr(mode, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/presence-modes/<int:mode_id>", methods=["DELETE"])
def api_delete_presence_mode(mode_id):
    session = get_db()
    try:
        mode = session.get(PresenceMode, mode_id)
        if not mode or mode.is_system: return jsonify({"error": "Cannot delete"}), 400
        session.delete(mode); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/presence-modes/current", methods=["GET"])
def api_current_presence_mode():
    try:
        return jsonify(_deps.get("automation_scheduler").presence_mgr.get_current_mode() or {"name_de":"Unbekannt","name_en":"Unknown"})
    except Exception as e:
        return jsonify({"error": str(e)})


@presence_bp.route("/api/presence-modes/<int:mode_id>/activate", methods=["POST"])
def api_activate_presence_mode(mode_id):
    try:
        return jsonify(_deps.get("automation_scheduler").presence_mgr.set_mode(mode_id, trigger="manual"))
    except Exception as e:
        return jsonify({"error": str(e)})


@presence_bp.route("/api/presence-log", methods=["GET"])
def api_presence_log():
    session = get_db()
    try:
        query = session.query(PresenceLog).order_by(PresenceLog.created_at.desc())
        total = query.count()
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        logs = query.offset(offset).limit(limit).all()
        return jsonify({
            "items": [{"id":l.id,"mode_name":l.mode_name,"user_id":l.user_id,"trigger":l.trigger,"created_at":l.created_at.isoformat() if l.created_at else None} for l in logs],
            "total": total, "offset": offset, "limit": limit, "has_more": offset + limit < total
        })
    finally:
        session.close()


@presence_bp.route("/api/person-devices", methods=["GET"])
def api_get_person_devices():
    session = get_db()
    try:
        return jsonify([{"id":d.id,"user_id":d.user_id,"entity_id":d.entity_id,"device_type":d.device_type,"timeout_minutes":d.timeout_minutes} for d in session.query(PersonDevice).filter_by(is_active=True).all()])
    finally:
        session.close()


@presence_bp.route("/api/person-devices", methods=["POST"])
def api_create_person_device():
    data = request.json or {}
    session = get_db()
    try:
        pd = PersonDevice(user_id=data["user_id"], entity_id=data["entity_id"], device_type=data.get("device_type","primary"), timeout_minutes=data.get("timeout_minutes",10))
        session.add(pd); session.commit()
        return jsonify({"id": pd.id, "success": True})
    finally:
        session.close()


@presence_bp.route("/api/person-devices/<int:pd_id>", methods=["DELETE"])
def api_delete_person_device(pd_id):
    session = get_db()
    try:
        pd = session.get(PersonDevice, pd_id)
        if pd: session.delete(pd); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/guest-devices", methods=["GET"])
def api_get_guest_devices():
    session = get_db()
    try:
        return jsonify([{"id":g.id,"mac_address":g.mac_address,"entity_id":g.entity_id,"name":g.name,"first_seen":g.first_seen.isoformat() if g.first_seen else None,"last_seen":g.last_seen.isoformat() if g.last_seen else None,"visit_count":g.visit_count,"auto_delete_days":g.auto_delete_days} for g in session.query(GuestDevice).order_by(GuestDevice.last_seen.desc()).all()])
    finally:
        session.close()


@presence_bp.route("/api/guest-devices/<int:guest_id>", methods=["PUT"])
def api_update_guest_device(guest_id):
    data = request.json or {}
    session = get_db()
    try:
        g = session.get(GuestDevice, guest_id)
        if not g: return jsonify({"error": "Not found"}), 404
        for key in ["name","auto_delete_days"]:
            if key in data: setattr(g, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/guest-devices/<int:guest_id>", methods=["DELETE"])
def api_delete_guest_device(guest_id):
    session = get_db()
    try:
        g = session.get(GuestDevice, guest_id)
        if g: session.delete(g); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@presence_bp.route("/api/sun", methods=["GET"])
def api_get_sun():
    return jsonify(_ha().get_sun_data() if hasattr(ha, 'get_sun_data') else {"error": "not available"})


@presence_bp.route("/api/presence-modes/seed-defaults", methods=["POST"])
def api_seed_default_presence_modes():
    session = get_db()
    try:
        existing = session.query(PresenceMode).count()
        if existing > 0:
            return jsonify({"message": "Already seeded", "count": existing})
        defaults = [
            {"name_de": "Zuhause", "name_en": "Home", "icon": "mdi-home", "color": "#4CAF50", "priority": 1, "is_system": True, "trigger_type": "auto"},
            {"name_de": "Abwesend", "name_en": "Away", "icon": "mdi-exit-run", "color": "#FF9800", "priority": 2, "is_system": True, "trigger_type": "auto"},
            {"name_de": "Schlaf", "name_en": "Sleep", "icon": "mdi-sleep", "color": "#3F51B5", "priority": 3, "is_system": True, "trigger_type": "auto"},
            {"name_de": "Urlaub", "name_en": "Vacation", "icon": "mdi-beach", "color": "#00BCD4", "priority": 4, "is_system": True, "trigger_type": "manual"},
        ]
        for m in defaults:
            session.add(PresenceMode(**m, is_active=True))
        session.commit()
        return jsonify({"success": True, "count": len(defaults)})
    finally:
        session.close()
    return jsonify(_ha().get_sun_state() or {"error": "unavailable"})


@presence_bp.route("/api/sun/events", methods=["GET"])
def api_get_sun_events():
    return jsonify(_ha().get_sun_events_today())


@presence_bp.route("/api/weather/current", methods=["GET"])
def api_get_weather_current():
    return jsonify(_ha().get_weather() or {"error": "unavailable"})


@presence_bp.route("/api/persons", methods=["GET"])
def api_get_persons():
    return jsonify(_ha().get_all_persons())


@presence_bp.route("/api/persons/home", methods=["GET"])
def api_get_persons_home():
    return jsonify(_ha().get_persons_home())
