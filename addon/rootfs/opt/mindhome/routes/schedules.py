# MindHome - routes/schedules.py | see version.py for version info
"""
MindHome API Routes - Schedules
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

logger = logging.getLogger("mindhome.routes.schedules")

schedules_bp = Blueprint("schedules", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_schedules(dependencies):
    """Initialize schedules routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@schedules_bp.route("/api/calendar/upcoming", methods=["GET"])
def api_upcoming_events():
    """Get upcoming calendar events from HA."""
    try:
        hours = int(request.args.get("hours", 24))
        events = _ha().get_upcoming_events(hours=hours)
        return jsonify({"events": events})
    except Exception as e:
        logger.warning(f"Calendar events error: {e}")
        return jsonify({"events": [], "error": str(e)})



@schedules_bp.route("/api/calendar/triggers", methods=["GET"])
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



@schedules_bp.route("/api/calendar/triggers", methods=["POST"])
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



@schedules_bp.route("/api/calendar/triggers/<trigger_id>", methods=["DELETE"])
def api_delete_calendar_trigger(trigger_id):
    """Delete a calendar trigger."""
    triggers = json.loads(get_setting("calendar_triggers") or "[]")
    triggers = [t for t in triggers if t.get("id") != trigger_id]
    set_setting("calendar_triggers", json.dumps(triggers))
    return jsonify({"success": True})



@schedules_bp.route("/api/calendar-triggers", methods=["GET"])
def api_get_calendar_triggers_alias():
    return api_get_calendar_triggers()



@schedules_bp.route("/api/calendar-triggers", methods=["PUT"])
def api_update_calendar_triggers_alias():
    """Bulk update calendar triggers."""
    data = request.json
    set_setting("calendar_triggers", json.dumps(data.get("triggers", [])))
    return jsonify({"success": True})



@schedules_bp.route("/api/quiet-hours", methods=["GET"])
def api_get_quiet_hours():
    session = get_db()
    try:
        return jsonify([{"id":c.id,"user_id":c.user_id,"name":c.name,"start_time":c.start_time,"end_time":c.end_time,"linked_to_shift":c.linked_to_shift,"linked_to_day_phase":c.linked_to_day_phase,"allow_critical":c.allow_critical,"is_active":c.is_active} for c in session.query(QuietHoursConfig).all()])
    finally:
        session.close()


@schedules_bp.route("/api/quiet-hours", methods=["POST"])
def api_create_quiet_hours():
    data = request.json or {}
    session = get_db()
    try:
        qh = QuietHoursConfig(name=data.get("name","Nachtruhe"), start_time=data.get("start_time","22:00"), end_time=data.get("end_time","07:00"), linked_to_shift=data.get("linked_to_shift",False), allow_critical=data.get("allow_critical",True), is_active=data.get("is_active",True))
        session.add(qh); session.commit()
        return jsonify({"id": qh.id, "success": True})
    finally:
        session.close()


@schedules_bp.route("/api/quiet-hours/<int:qh_id>", methods=["PUT"])
def api_update_quiet_hours(qh_id):
    data = request.json or {}
    session = get_db()
    try:
        qh = session.get(QuietHoursConfig, qh_id)
        if not qh: return jsonify({"error": "Not found"}), 404
        for key in ["name","start_time","end_time","linked_to_shift","linked_to_day_phase","allow_critical","is_active"]:
            if key in data: setattr(qh, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/quiet-hours/<int:qh_id>", methods=["DELETE"])
def api_delete_quiet_hours(qh_id):
    session = get_db()
    try:
        qh = session.get(QuietHoursConfig, qh_id)
        if qh: session.delete(qh); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/school-vacations", methods=["GET"])
def api_get_school_vacations():
    session = get_db()
    try:
        return jsonify([{"id":v.id,"name_de":v.name_de,"name_en":v.name_en,"start_date":v.start_date,"end_date":v.end_date,"region":v.region,"source":v.source,"is_active":v.is_active} for v in session.query(SchoolVacation).order_by(SchoolVacation.start_date).all()])
    finally:
        session.close()


@schedules_bp.route("/api/school-vacations", methods=["POST"])
def api_create_school_vacation():
    data = request.json or {}
    session = get_db()
    try:
        sv = SchoolVacation(name_de=data.get("name_de","Ferien"), name_en=data.get("name_en","Vacation"), start_date=data["start_date"], end_date=data["end_date"], region=data.get("region","AT-NO"), source="manual")
        session.add(sv); session.commit()
        return jsonify({"id": sv.id, "success": True})
    finally:
        session.close()


@schedules_bp.route("/api/school-vacations/<int:sv_id>", methods=["DELETE"])
def api_delete_school_vacation(sv_id):
    session = get_db()
    try:
        sv = session.get(SchoolVacation, sv_id)
        if sv: session.delete(sv); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/person-schedules", methods=["GET"])
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


@schedules_bp.route("/api/person-schedules", methods=["POST"])
def api_create_person_schedule():
    data = request.json or {}
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
        session.add(schedule); session.commit()
        audit_log("create_schedule", {"user_id": data["user_id"], "type": data.get("schedule_type")})
        return jsonify({"success": True, "id": schedule.id})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()


@schedules_bp.route("/api/person-schedules/<int:sid>", methods=["PUT"])
def api_update_person_schedule(sid):
    data = request.json or {}
    session = get_db()
    try:
        s = session.get(PersonSchedule, sid)
        if not s: return jsonify({"error": "Not found"}), 404
        for f in ["schedule_type","name","time_wake","time_leave","time_home","time_sleep","weekdays","shift_data"]:
            if f in data: setattr(s, f, data[f])
        if "valid_from" in data:
            s.valid_from = datetime.fromisoformat(data["valid_from"]) if data["valid_from"] else None
        if "valid_until" in data:
            s.valid_until = datetime.fromisoformat(data["valid_until"]) if data["valid_until"] else None
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/person-schedules/<int:sid>", methods=["DELETE"])
def api_delete_person_schedule(sid):
    session = get_db()
    try:
        s = session.get(PersonSchedule, sid)
        if s: s.is_active = False; session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/shift-templates", methods=["GET"])
def api_get_shift_templates():
    session = get_db()
    try:
        return jsonify([{"id": t.id, "name": t.name, "short_code": t.short_code,
            "blocks": t.blocks, "color": t.color}
            for t in session.query(ShiftTemplate).filter_by(is_active=True).all()])
    finally:
        session.close()


@schedules_bp.route("/api/shift-templates", methods=["POST"])
def api_create_shift_template():
    data = request.json or {}
    session = get_db()
    try:
        t = ShiftTemplate(name=data["name"], short_code=data.get("short_code"),
            blocks=data.get("blocks", []), color=data.get("color"))
        session.add(t); session.commit()
        return jsonify({"success": True, "id": t.id})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()


@schedules_bp.route("/api/shift-templates/<int:tid>", methods=["PUT"])
def api_update_shift_template(tid):
    data = request.json or {}
    session = get_db()
    try:
        t = session.get(ShiftTemplate, tid)
        if not t: return jsonify({"error": "Not found"}), 404
        for f in ["name", "short_code", "blocks", "color"]:
            if f in data: setattr(t, f, data[f])
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        session.close()


@schedules_bp.route("/api/shift-templates/<int:tid>", methods=["DELETE"])
def api_delete_shift_template(tid):
    session = get_db()
    try:
        t = session.get(ShiftTemplate, tid)
        if t: t.is_active = False; session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/shift-plan/import", methods=["POST"])
def api_import_shift_plan():
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
            return jsonify({"error": "PDF-Bibliothek fehlt. Bitte Container neu bauen."}), 500
        finally:
            import os; os.unlink(tmp_path)
        if not text.strip():
            return jsonify({"error": "Kein Text im PDF gefunden"}), 400
        # Parse shift entries
        entries = []
        lines = text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line: continue
            # Try to extract date and shift type patterns
            import re
            # Common pattern: DD.MM.YYYY or DD.MM. followed by shift code
            date_match = re.findall(r'(\d{1,2}\.\d{1,2}\.(?:\d{4})?)\s+(.+)', line)
            if date_match:
                for dm in date_match:
                    entries.append({"date": dm[0].strip(), "raw": dm[1].strip()})
        # Match with known shift templates
        session = get_db()
        try:
            templates = session.query(ShiftTemplate).filter_by(is_active=True).all()
            tmpl_map = {}
            for t in templates:
                tmpl_map[t.short_code.upper()] = {"id": t.id, "name": t.name, "short_code": t.short_code, "blocks": t.blocks, "color": t.color}
                tmpl_map[t.name.upper()] = tmpl_map[t.short_code.upper()]
        finally:
            session.close()
        parsed = []
        unmatched = set()
        for e in entries:
            raw_upper = e["raw"].upper().strip()
            matched = None
            for code, tmpl in tmpl_map.items():
                if code and raw_upper.startswith(code):
                    matched = tmpl; break
            if matched:
                parsed.append({"date": e["date"], "shift": matched, "raw": e["raw"]})
            else:
                parsed.append({"date": e["date"], "shift": None, "raw": e["raw"]})
                unmatched.add(e["raw"].strip())
        return jsonify({"entries": parsed, "unmatched_types": list(unmatched), "total_lines": len(lines), "parsed_count": len(parsed)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@schedules_bp.route("/api/holidays", methods=["GET"])
def api_get_holidays():
    session = get_db()
    try:
        return jsonify([{"id":h.id, "name":h.name, "date":h.date, "is_recurring":h.is_recurring,
            "region":h.region, "source":h.source, "is_active":h.is_active}
            for h in session.query(Holiday).order_by(Holiday.date).all()])
    finally:
        session.close()


@schedules_bp.route("/api/holidays", methods=["POST"])
def api_create_holiday():
    data = request.json or {}
    session = get_db()
    try:
        h = Holiday(name=data["name"], date=data["date"], is_recurring=data.get("is_recurring", False),
            region=data.get("region", "AT"), source=data.get("source", "manual"))
        session.add(h); session.commit()
        return jsonify({"id": h.id, "success": True})
    finally:
        session.close()


@schedules_bp.route("/api/holidays/<int:hid>", methods=["PUT"])
def api_update_holiday(hid):
    data = request.json or {}
    session = get_db()
    try:
        h = session.get(Holiday, hid)
        if not h: return jsonify({"error": "Not found"}), 404
        for f in ["name","date","is_recurring","region","source","is_active"]:
            if f in data: setattr(h, f, data[f])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/holidays/<int:hid>", methods=["DELETE"])
def api_delete_holiday(hid):
    session = get_db()
    try:
        h = session.get(Holiday, hid)
        if h: session.delete(h); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@schedules_bp.route("/api/holidays/seed-defaults", methods=["POST"])
def api_seed_default_holidays():
    """Seed Austrian holidays."""
    session = get_db()
    try:
        existing = session.query(Holiday).filter_by(source="builtin").count()
        if existing > 0:
            return jsonify({"message": "Already seeded", "count": existing})
        defaults = [
            ("Neujahr", "01-01"), ("Heilige Drei Koenige", "01-06"),
            ("Staatsfeiertag", "05-01"), ("Christi Himmelfahrt", "05-29"),
            ("Pfingstmontag", "06-09"), ("Fronleichnam", "06-19"),
            ("Mariä Himmelfahrt", "08-15"), ("Nationalfeiertag", "10-26"),
            ("Allerheiligen", "11-01"), ("Mariä Empfaengnis", "12-08"),
            ("Christtag", "12-25"), ("Stefanitag", "12-26"),
        ]
        for name, date in defaults:
            session.add(Holiday(name=name, date=date, is_recurring=True, region="AT", source="builtin"))
        session.commit()
        return jsonify({"success": True, "count": len(defaults)})
    finally:
        session.close()
