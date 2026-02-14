# MindHome routes/presence v0.6.2 (2026-02-10) - routes/presence.py
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
        from pattern_engine import ContextBuilder
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
        # Duplikat-Check: Name darf nicht bereits existieren
        name_de = data.get("name_de", "Neuer Modus")
        existing = session.query(PresenceMode).filter_by(name_de=name_de).first()
        if existing:
            return jsonify({"error": f"Modus '{name_de}' existiert bereits"}), 409
        mode = PresenceMode(name_de=name_de, name_en=data.get("name_en","New Mode"), icon=data.get("icon","mdi:home"), color=data.get("color","#4CAF50"), priority=data.get("priority",0), buffer_minutes=data.get("buffer_minutes",5), actions=data.get("actions"), trigger_type=data.get("trigger_type","manual"), auto_config=data.get("auto_config"), notify_on_enter=data.get("notify_on_enter", False), notify_on_leave=data.get("notify_on_leave", False), is_active=data.get("is_active",True))
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
        current = _deps.get("automation_scheduler").presence_mgr.get_current_mode()
        if current:
            return jsonify(current)
        # Fallback: no log exists yet - return placeholder without auto-selecting
        return jsonify({"name_de": "Erkennung laeuft...", "name_en": "Detecting...", "icon": "mdi-crosshairs-question", "color": "#9E9E9E", "since": None, "is_default": True})
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


@presence_bp.route("/api/presence/auto-detect", methods=["POST"])
def api_presence_auto_detect():
    """#13: Auto-detect presence from person.* entities."""
    session = get_db()
    try:
        # Check manual override
        override = session.query(SystemSetting).filter_by(key="presence_manual_override").first()
        if override and override.value == "true":
            return jsonify({"skipped": True, "reason": "manual_override_active"})

        # Get all person entities from HA
        persons = _ha().get_all_persons() if _ha() else []
        home_count = sum(1 for p in persons if p.get("state") == "home")
        total = len(persons)

        # Determine target mode
        if home_count >= 1:
            target_name = "Zuhause"
        else:
            target_name = "Abwesend"

        # Find matching mode
        target_mode = session.query(PresenceMode).filter_by(name_de=target_name).first()
        if not target_mode:
            return jsonify({"error": f"Mode '{target_name}' not found"}), 404

        # Check current mode
        current = session.query(PresenceLog).order_by(PresenceLog.created_at.desc()).first()
        if current and current.mode_name == target_name:
            return jsonify({"changed": False, "mode": target_name, "home_count": home_count})

        # Switch mode: write PresenceLog with mode_id
        log_entry = PresenceLog(
            mode_id=target_mode.id,
            mode_name=target_name,
            trigger="auto_detect",
        )
        session.add(log_entry)

        # Create notification for toast
        notification = NotificationLog(
            user_id=1,
            title=f"Modus: {target_name}",
            message=f"Automatisch erkannt: {home_count}/{total} Personen zuhause",
            notification_type=NotificationType.INFO,
            was_read=False,
        )
        session.add(notification)
        session.commit()

        return jsonify({
            "changed": True,
            "mode": target_name,
            "home_count": home_count,
            "total_persons": total,
        })
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@presence_bp.route("/api/presence/manual-override", methods=["POST"])
def api_presence_manual_override():
    """#28: Set or clear manual presence override."""
    data = request.json or {}
    session = get_db()
    try:
        enabled = data.get("enabled", True)
        setting = session.query(SystemSetting).filter_by(key="presence_manual_override").first()
        if setting:
            setting.value = "true" if enabled else "false"
        else:
            session.add(SystemSetting(
                key="presence_manual_override",
                value="true" if enabled else "false",
                description_de="Manuelle Anwesenheits-Steuerung aktiv",
                description_en="Manual presence control active",
            ))
        # Store timestamp for auto-reset (4h)
        ts_setting = session.query(SystemSetting).filter_by(key="presence_manual_override_ts").first()
        ts_val = datetime.now(timezone.utc).isoformat() if enabled else ""
        if ts_setting:
            ts_setting.value = ts_val
        else:
            session.add(SystemSetting(
                key="presence_manual_override_ts",
                value=ts_val,
                description_de="Zeitpunkt der manuellen Übersteuerung",
                description_en="Manual override timestamp",
            ))
        session.commit()
        return jsonify({"success": True, "manual_override": enabled})
    finally:
        session.close()


@presence_bp.route("/api/sun", methods=["GET"])
def api_get_sun():
    return jsonify(_ha().get_sun_data() if hasattr(ha, 'get_sun_data') else {"error": "not available"})


@presence_bp.route("/api/presence-modes/seed-defaults", methods=["POST"])
def api_seed_default_presence_modes():
    session = get_db()
    try:
        defaults = [
            {"name_de": "Zuhause", "name_en": "Home", "icon": "mdi-home", "color": "#4CAF50", "priority": 10, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "first_home"}},
            {"name_de": "Besuch", "name_en": "Guests", "icon": "mdi-account-group", "color": "#9C27B0", "priority": 15, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "guests_home"}},
            {"name_de": "Schlaf", "name_en": "Sleep", "icon": "mdi-sleep", "color": "#3F51B5", "priority": 20, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "all_home", "time_range": {"start": "22:00", "end": "06:00"}}},
            {"name_de": "Abwesend", "name_en": "Away", "icon": "mdi-exit-run", "color": "#FF9800", "priority": 5, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "all_away"}},
            {"name_de": "Urlaub", "name_en": "Vacation", "icon": "mdi-beach", "color": "#00BCD4", "priority": 25, "is_system": True, "trigger_type": "manual"},
        ]
        created = 0
        updated = 0
        skipped = []
        for m in defaults:
            existing = session.query(PresenceMode).filter_by(name_de=m["name_de"]).first()
            if existing:
                # Fix existing priorities, trigger_type and auto_config
                changed = False
                if existing.priority != m["priority"]:
                    existing.priority = m["priority"]
                    changed = True
                if existing.trigger_type != m.get("trigger_type", "manual"):
                    existing.trigger_type = m.get("trigger_type", "manual")
                    changed = True
                if m.get("auto_config") and existing.auto_config != m["auto_config"]:
                    existing.auto_config = m["auto_config"]
                    changed = True
                if changed:
                    updated += 1
                    logger.info(f"Seed update: {m['name_de']} (prio={m['priority']}, trigger={m.get('trigger_type')})")
                else:
                    skipped.append(m["name_de"])
                continue
            session.add(PresenceMode(**m, is_active=True))
            created += 1
        session.commit()
        return jsonify({"success": True, "created": created, "updated": updated, "skipped": skipped})
    finally:
        session.close()


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
