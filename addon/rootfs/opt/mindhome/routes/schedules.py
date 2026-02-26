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
import secrets
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
        logger.error("Operation failed: %s", e)
        return jsonify({"events": [], "error": "Operation failed"}), 500



@schedules_bp.route("/api/calendar/triggers", methods=["GET"])
def api_get_calendar_triggers():
    """Get calendar-based automation triggers."""
    with get_db_session() as session:
        triggers = []
        raw = get_setting("calendar_triggers")
        if raw:
            triggers = json.loads(raw)
        return jsonify(triggers)



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
    with get_db_session() as session:
        return jsonify([{"id":c.id,"user_id":c.user_id,"name":c.name,"start_time":c.start_time,"end_time":c.end_time,"linked_to_shift":c.linked_to_shift,"linked_to_day_phase":c.linked_to_day_phase,"allow_critical":c.allow_critical,"is_active":c.is_active} for c in session.query(QuietHoursConfig).all()])


@schedules_bp.route("/api/quiet-hours", methods=["POST"])
def api_create_quiet_hours():
    data = request.json or {}
    with get_db_session() as session:
        qh = QuietHoursConfig(name=data.get("name","Nachtruhe"), start_time=data.get("start_time","22:00"), end_time=data.get("end_time","07:00"), linked_to_shift=data.get("linked_to_shift",False), allow_critical=data.get("allow_critical",True), is_active=data.get("is_active",True))
        session.add(qh); session.commit()
        return jsonify({"id": qh.id, "success": True})


@schedules_bp.route("/api/quiet-hours/<int:qh_id>", methods=["PUT"])
def api_update_quiet_hours(qh_id):
    data = request.json or {}
    with get_db_session() as session:
        qh = session.get(QuietHoursConfig, qh_id)
        if not qh: return jsonify({"error": "Not found"}), 404
        for key in ["name","start_time","end_time","linked_to_shift","linked_to_day_phase","allow_critical","is_active"]:
            if key in data: setattr(qh, key, data[key])
        session.commit()
        return jsonify({"success": True})


@schedules_bp.route("/api/quiet-hours/<int:qh_id>", methods=["DELETE"])
def api_delete_quiet_hours(qh_id):
    with get_db_session() as session:
        qh = session.get(QuietHoursConfig, qh_id)
        if qh: session.delete(qh); session.commit()
        return jsonify({"success": True})


@schedules_bp.route("/api/school-vacations", methods=["GET"])
def api_get_school_vacations():
    with get_db_session() as session:
        return jsonify([{"id":v.id,"name_de":v.name_de,"name_en":v.name_en,"start_date":v.start_date,"end_date":v.end_date,"region":v.region,"source":v.source,"is_active":v.is_active} for v in session.query(SchoolVacation).order_by(SchoolVacation.start_date).all()])


@schedules_bp.route("/api/school-vacations", methods=["POST"])
def api_create_school_vacation():
    data = request.json or {}
    with get_db_session() as session:
        sv = SchoolVacation(name_de=data.get("name_de","Ferien"), name_en=data.get("name_en","Vacation"), start_date=data["start_date"], end_date=data["end_date"], region=data.get("region","AT-NO"), source="manual")
        session.add(sv); session.commit()
        return jsonify({"id": sv.id, "success": True})


@schedules_bp.route("/api/school-vacations/<int:sv_id>", methods=["DELETE"])
def api_delete_school_vacation(sv_id):
    with get_db_session() as session:
        sv = session.get(SchoolVacation, sv_id)
        if sv: session.delete(sv); session.commit()
        return jsonify({"success": True})


@schedules_bp.route("/api/person-schedules", methods=["GET"])
def api_get_person_schedules():
    with get_db_session() as session:
        schedules = session.query(PersonSchedule).filter_by(is_active=True).all()
        return jsonify([{
            "id": s.id, "user_id": s.user_id, "schedule_type": s.schedule_type,
            "name": s.name, "time_wake": s.time_wake, "time_leave": s.time_leave,
            "time_home": s.time_home, "time_sleep": s.time_sleep,
            "weekdays": s.weekdays, "shift_data": s.shift_data,
            "valid_from": utc_iso(s.valid_from) if s.valid_from else None,
            "valid_until": utc_iso(s.valid_until) if s.valid_until else None,
        } for s in schedules])


@schedules_bp.route("/api/person-schedules", methods=["POST"])
def api_create_person_schedule():
    data = request.json or {}
    with get_db_session() as session:
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
            logger.error("Operation failed: %s", e)
            return jsonify({"error": "Invalid request"}), 400


@schedules_bp.route("/api/person-schedules/<int:sid>", methods=["PUT"])
def api_update_person_schedule(sid):
    data = request.json or {}
    with get_db_session() as session:
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


@schedules_bp.route("/api/person-schedules/<int:sid>", methods=["DELETE"])
def api_delete_person_schedule(sid):
    with get_db_session() as session:
        s = session.get(PersonSchedule, sid)
        if s: s.is_active = False; session.commit()
        return jsonify({"success": True})


@schedules_bp.route("/api/shift-templates", methods=["GET"])
def api_get_shift_templates():
    with get_db_session() as session:
        return jsonify([{"id": t.id, "name": t.name, "short_code": t.short_code,
            "blocks": t.blocks, "color": t.color}
            for t in session.query(ShiftTemplate).filter_by(is_active=True).all()])


@schedules_bp.route("/api/shift-templates", methods=["POST"])
def api_create_shift_template():
    data = request.json or {}
    with get_db_session() as session:
        try:
            t = ShiftTemplate(name=data["name"], short_code=data.get("short_code"),
                blocks=data.get("blocks", []), color=data.get("color"))
            session.add(t); session.commit()
            return jsonify({"success": True, "id": t.id})
        except Exception as e:
            session.rollback()
            logger.error("Operation failed: %s", e)
            return jsonify({"error": "Invalid request"}), 400


@schedules_bp.route("/api/shift-templates/<int:tid>", methods=["PUT"])
def api_update_shift_template(tid):
    data = request.json or {}
    with get_db_session() as session:
        try:
            t = session.get(ShiftTemplate, tid)
            if not t: return jsonify({"error": "Not found"}), 404
            for f in ["name", "short_code", "blocks", "color"]:
                if f in data: setattr(t, f, data[f])
            session.commit()
            return jsonify({"success": True})
        except Exception as e:
            session.rollback()
            logger.error("Operation failed: %s", e)
            return jsonify({"error": "Invalid request"}), 400


@schedules_bp.route("/api/shift-templates/<int:tid>", methods=["DELETE"])
def api_delete_shift_template(tid):
    with get_db_session() as session:
        t = session.get(ShiftTemplate, tid)
        if t: t.is_active = False; session.commit()
        return jsonify({"success": True})


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
        with get_db_session() as session:
            templates = session.query(ShiftTemplate).filter_by(is_active=True).all()
            tmpl_map = {}
            for t in templates:
                tmpl_map[t.short_code.upper()] = {"id": t.id, "name": t.name, "short_code": t.short_code, "blocks": t.blocks, "color": t.color}
                tmpl_map[t.name.upper()] = tmpl_map[t.short_code.upper()]
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
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@schedules_bp.route("/api/holidays", methods=["GET"])
def api_get_holidays():
    with get_db_session() as session:
        return jsonify([{"id":h.id, "name":h.name, "date":h.date, "is_recurring":h.is_recurring,
            "region":h.region, "source":h.source, "is_active":h.is_active}
            for h in session.query(Holiday).order_by(Holiday.date).all()])


@schedules_bp.route("/api/holidays", methods=["POST"])
def api_create_holiday():
    data = request.json or {}
    with get_db_session() as session:
        h = Holiday(name=data["name"], date=data["date"], is_recurring=data.get("is_recurring", False),
            region=data.get("region", "AT"), source=data.get("source", "manual"))
        session.add(h); session.commit()
        return jsonify({"id": h.id, "success": True})


@schedules_bp.route("/api/holidays/<int:hid>", methods=["PUT"])
def api_update_holiday(hid):
    data = request.json or {}
    with get_db_session() as session:
        h = session.get(Holiday, hid)
        if not h: return jsonify({"error": "Not found"}), 404
        for f in ["name","date","is_recurring","region","source","is_active"]:
            if f in data: setattr(h, f, data[f])
        session.commit()
        return jsonify({"success": True})


@schedules_bp.route("/api/holidays/<int:hid>", methods=["DELETE"])
def api_delete_holiday(hid):
    with get_db_session() as session:
        h = session.get(Holiday, hid)
        if h: session.delete(h); session.commit()
        return jsonify({"success": True})


@schedules_bp.route("/api/holidays/seed-defaults", methods=["POST"])
def api_seed_default_holidays():
    """Seed Austrian holidays."""
    with get_db_session() as session:
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


# ==============================================================================
# Calendar Sync: iCal Export + HA Calendar Integration
# ==============================================================================

def _ical_escape(text):
    """Escape text for iCal format."""
    if not text:
        return ""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold_line(line):
    """Fold long iCal lines at 75 octets per RFC 5545."""
    result = []
    while len(line.encode("utf-8")) > 75:
        # Find a safe split point
        cut = 75
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        result.append(line[:cut])
        line = " " + line[cut:]
    result.append(line)
    return "\r\n".join(result)


@schedules_bp.route("/api/calendar/export-token", methods=["GET"])
def api_get_export_token():
    """Get the current iCal export token (creates one if none exists)."""
    token = get_setting("calendar_export_token")
    if not token:
        token = secrets.token_urlsafe(32)
        set_setting("calendar_export_token", token)
    return jsonify({"token": token})


@schedules_bp.route("/api/calendar/export-token", methods=["POST"])
def api_regenerate_export_token():
    """Regenerate the iCal export token (invalidates old URLs)."""
    token = secrets.token_urlsafe(32)
    set_setting("calendar_export_token", token)
    audit_log("calendar_token_regenerated", {})
    return jsonify({"token": token})


@schedules_bp.route("/api/calendar/export-settings", methods=["GET"])
def api_get_export_settings():
    """Get calendar export settings."""
    days = get_setting("calendar_export_days")
    return jsonify({"export_days": int(days) if days else 90})


@schedules_bp.route("/api/calendar/export-settings", methods=["PUT"])
def api_update_export_settings():
    """Update calendar export settings."""
    data = request.json or {}
    days = max(7, min(365, int(data.get("export_days", 90))))
    set_setting("calendar_export_days", str(days))
    audit_log("calendar_export_settings", {"export_days": days})
    return jsonify({"success": True, "export_days": days})


@schedules_bp.route("/api/calendar/export.ics", methods=["GET"])
def api_export_ical():
    """Export MindHome calendar as iCal feed (shifts, holidays, vacations)."""
    # Token validation
    expected_token = get_setting("calendar_export_token")
    provided_token = request.args.get("token", "")
    if not expected_token or provided_token != expected_token:
        return "Unauthorized – invalid or missing token", 403

    with get_db_session() as session:
        try:
            from helpers import get_ha_timezone
            local_tz = get_ha_timezone()
            now = datetime.now(local_tz)
            lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//MindHome//Calendar Export//DE",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
                "X-WR-CALNAME:MindHome",
                "X-WR-TIMEZONE:Europe/Vienna",
            ]

            # --- Holidays ---
            holidays = session.query(Holiday).filter_by(is_active=True).all()
            current_year = now.year
            for h in holidays:
                date_str = h.date
                if h.is_recurring and len(date_str) == 5:
                    # MM-DD format -> generate for current year and next year
                    for year in [current_year, current_year + 1]:
                        dt = f"{year}-{date_str}"
                        uid = f"holiday-{h.id}-{year}@mindhome"
                        lines.extend([
                            "BEGIN:VEVENT",
                            f"UID:{uid}",
                            f"DTSTART;VALUE=DATE:{dt.replace('-', '')}",
                            f"DTEND;VALUE=DATE:{dt.replace('-', '')}",
                            f"SUMMARY:{_ical_escape(h.name)}",
                            "CATEGORIES:Feiertag",
                            "TRANSP:TRANSPARENT",
                            f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                            "END:VEVENT",
                        ])
                elif len(date_str) == 10:
                    uid = f"holiday-{h.id}@mindhome"
                    lines.extend([
                        "BEGIN:VEVENT",
                        f"UID:{uid}",
                        f"DTSTART;VALUE=DATE:{date_str.replace('-', '')}",
                        f"DTEND;VALUE=DATE:{date_str.replace('-', '')}",
                        f"SUMMARY:{_ical_escape(h.name)}",
                        "CATEGORIES:Feiertag",
                        "TRANSP:TRANSPARENT",
                        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                        "END:VEVENT",
                    ])

            # --- School Vacations ---
            vacations = session.query(SchoolVacation).filter_by(is_active=True).all()
            for v in vacations:
                uid = f"vacation-{v.id}@mindhome"
                name = v.name_de or v.name_en or "Ferien"
                # end_date in iCal is exclusive, so add 1 day
                try:
                    end_dt = datetime.strptime(v.end_date, "%Y-%m-%d") + timedelta(days=1)
                    end_str = end_dt.strftime("%Y%m%d")
                except (ValueError, TypeError):
                    end_str = v.end_date.replace("-", "") if v.end_date else ""
                lines.extend([
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTART;VALUE=DATE:{v.start_date.replace('-', '')}",
                    f"DTEND;VALUE=DATE:{end_str}",
                    f"SUMMARY:{_ical_escape(name)}",
                    "CATEGORIES:Ferien",
                    "TRANSP:TRANSPARENT",
                    f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                    "END:VEVENT",
                ])

            # --- Shift Schedules ---
            schedules = session.query(PersonSchedule).filter_by(is_active=True).all()
            templates = {t.short_code: t for t in session.query(ShiftTemplate).filter_by(is_active=True).all()}
            users = {u.id: u.name for u in session.query(User).filter_by(is_active=True).all()}

            for sched in schedules:
                if sched.schedule_type != "shift" or not sched.shift_data:
                    continue
                sd = sched.shift_data if isinstance(sched.shift_data, dict) else {}
                pattern = sd.get("rotation_pattern", [])
                rotation_start = sd.get("rotation_start")
                if not pattern or not rotation_start:
                    continue
                try:
                    start_dt = datetime.strptime(rotation_start, "%Y-%m-%d").replace(tzinfo=local_tz)
                except (ValueError, TypeError):
                    continue
                # Generate shift events for configurable days from now
                export_days_raw = get_setting("calendar_export_days")
                export_days = int(export_days_raw) if export_days_raw else 90
                user_name = users.get(sched.user_id, "")
                for day_offset in range(export_days):
                    day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
                    diff = (day - start_dt).days
                    if diff < 0:
                        continue
                    idx = diff % len(pattern)
                    code = pattern[idx]
                    tmpl = templates.get(code)
                    if not tmpl or code.upper() in ("X", "F", "-", "FREI"):
                        continue  # Skip free days
                    day_str = day.strftime("%Y%m%d")
                    uid = f"shift-{sched.id}-{day_str}@mindhome"
                    summary = f"{tmpl.name}" + (f" ({user_name})" if user_name else "")
                    # Use blocks for start/end times if available
                    blocks = tmpl.blocks if isinstance(tmpl.blocks, list) and tmpl.blocks else []
                    if blocks:
                        block_start = blocks[0].get("start", "06:00")
                        block_end = blocks[-1].get("end", "14:00")
                        lines.extend([
                            "BEGIN:VEVENT",
                            f"UID:{uid}",
                            f"DTSTART:{day_str}T{block_start.replace(':', '')}00",
                            f"DTEND:{day_str}T{block_end.replace(':', '')}00",
                            _fold_line(f"SUMMARY:{_ical_escape(summary)}"),
                            "CATEGORIES:Schicht",
                            f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                            "END:VEVENT",
                        ])
                    else:
                        lines.extend([
                            "BEGIN:VEVENT",
                            f"UID:{uid}",
                            f"DTSTART;VALUE=DATE:{day_str}",
                            f"DTEND;VALUE=DATE:{day_str}",
                            _fold_line(f"SUMMARY:{_ical_escape(summary)}"),
                            "CATEGORIES:Schicht",
                            f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                            "END:VEVENT",
                        ])

            # --- Weekday / Homeoffice Schedules ---
            weekday_scheds = [s for s in schedules if s.schedule_type in ("weekday", "homeoffice", "weekend") and s.weekdays]
            day_names_de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
            for sched in weekday_scheds:
                user_name = users.get(sched.user_id, "")
                type_label = {"weekday": "Arbeit", "homeoffice": "Homeoffice", "weekend": "Wochenende"}.get(sched.schedule_type, sched.schedule_type)
                wdays = sched.weekdays if isinstance(sched.weekdays, list) else []
                # iCal BYDAY mapping: MO=0, TU=1, WE=2, TH=3, FR=4, SA=5, SU=6
                ical_days = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
                byday = ",".join(ical_days[d] for d in wdays if 0 <= d <= 6)
                if not byday:
                    continue
                summary = f"{type_label}" + (f" ({user_name})" if user_name else "")
                time_leave = sched.time_leave or "08:00"
                time_home = sched.time_home or "17:00"
                uid = f"schedule-{sched.id}@mindhome"
                start_date = now.strftime("%Y%m%d")
                lines.extend([
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTART:{start_date}T{time_leave.replace(':', '')}00",
                    f"DTEND:{start_date}T{time_home.replace(':', '')}00",
                    f"RRULE:FREQ=WEEKLY;BYDAY={byday}",
                    _fold_line(f"SUMMARY:{_ical_escape(summary)}"),
                    f"CATEGORIES:{type_label}",
                    f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                    "END:VEVENT",
                ])

            lines.append("END:VCALENDAR")

            ical_content = "\r\n".join(lines) + "\r\n"
            response = make_response(ical_content)
            response.headers["Content-Type"] = "text/calendar; charset=utf-8"
            response.headers["Content-Disposition"] = "attachment; filename=mindhome.ics"
            response.headers["Cache-Control"] = "public, max-age=3600"
            response.headers["ETag"] = hashlib.md5(ical_content.encode()).hexdigest()
            return response
        except Exception as e:
            logger.error("iCal export error: %s", e)
            return jsonify({"error": "Operation failed"}), 500


@schedules_bp.route("/api/calendar/ha-sources", methods=["GET"])
def api_get_ha_calendar_sources():
    """List all HA calendar entities with their sync status."""
    try:
        ha = _ha()
        ha_calendars = ha.get_calendars() if ha else []
        synced_raw = get_setting("calendar_synced_sources") or "[]"
        synced_ids = json.loads(synced_raw)
        result = []
        for cal in (ha_calendars or []):
            eid = cal.get("entity_id", "")
            result.append({
                "entity_id": eid,
                "name": cal.get("name", eid),
                "synced": eid in synced_ids,
            })
        return jsonify({"sources": result, "synced_ids": synced_ids})
    except Exception as e:
        logger.warning(f"HA calendar sources error: {e}")
        # Fallback: return synced IDs from settings even if HA is offline
        synced_raw = get_setting("calendar_synced_sources") or "[]"
        synced_ids = json.loads(synced_raw)
        return jsonify({"sources": [{"entity_id": eid, "name": eid, "synced": True} for eid in synced_ids], "synced_ids": synced_ids, "ha_offline": True})


@schedules_bp.route("/api/calendar/ha-sources", methods=["PUT"])
def api_update_ha_calendar_sources():
    """Update which HA calendars are synced into MindHome."""
    data = request.json or {}
    synced_ids = data.get("synced_ids", [])
    set_setting("calendar_synced_sources", json.dumps(synced_ids))
    audit_log("calendar_sync_update", {"synced_ids": synced_ids})
    return jsonify({"success": True, "synced_ids": synced_ids})


@schedules_bp.route("/api/calendar/synced-events", methods=["GET"])
def api_get_synced_calendar_events():
    """Get events from synced HA calendars for a date range."""
    try:
        synced_raw = get_setting("calendar_synced_sources") or "[]"
        synced_ids = json.loads(synced_raw)
        if not synced_ids:
            return jsonify({"events": []})

        start = request.args.get("start")
        end = request.args.get("end")
        if not start:
            start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00.000Z")
        if not end:
            end = (datetime.now(timezone.utc) + timedelta(days=31)).strftime("%Y-%m-%dT23:59:59.000Z")

        events = []
        for eid in synced_ids:
            try:
                cal_events = _ha().get_calendar_events(eid, start, end)
                for ev in cal_events:
                    ev["calendar_entity"] = eid
                    # Normalize date fields
                    ev_start = ev.get("start", {})
                    ev_end = ev.get("end", {})
                    events.append({
                        "summary": ev.get("summary", ""),
                        "description": ev.get("description", ""),
                        "start": ev_start.get("dateTime") or ev_start.get("date", ""),
                        "end": ev_end.get("dateTime") or ev_end.get("date", ""),
                        "all_day": "date" in ev_start and "dateTime" not in ev_start,
                        "calendar_entity": eid,
                        "location": ev.get("location", ""),
                        "uid": ev.get("uid", ""),
                    })
            except Exception as e:
                logger.debug(f"Error fetching events from {eid}: {e}")

        events.sort(key=lambda e: e.get("start", ""))
        return jsonify({"events": events})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"events": [], "error": "Operation failed"}), 500


@schedules_bp.route("/api/calendar/events", methods=["POST"])
def api_create_calendar_event():
    """Create a new event on a HA calendar (Google Calendar, CalDAV, etc.)."""
    data = request.json or {}
    summary = sanitize_input(data.get("summary", "")).strip()
    entity_id = data.get("entity_id", "").strip()
    if not summary or not entity_id:
        return jsonify({"error": "summary and entity_id required"}), 400
    start = data.get("start", "").strip()
    end = data.get("end", "").strip()
    if not start or not end:
        return jsonify({"error": "start and end required"}), 400
    description = sanitize_input(data.get("description", "")) if data.get("description") else None
    location = sanitize_input(data.get("location", "")) if data.get("location") else None
    try:
        ha = _ha()
        result = ha.create_calendar_event(
            entity_id=entity_id, summary=summary,
            start=start, end=end,
            description=description, location=location,
        )
        audit_log("calendar_event_create", {"entity_id": entity_id, "summary": summary})
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@schedules_bp.route("/api/calendar/events", methods=["DELETE"])
def api_delete_calendar_event():
    """Delete an event from a HA calendar."""
    data = request.json or {}
    entity_id = data.get("entity_id", "").strip()
    uid = data.get("uid", "").strip()
    if not entity_id or not uid:
        return jsonify({"error": "entity_id and uid required"}), 400
    try:
        ha = _ha()
        result = ha.delete_calendar_event(entity_id=entity_id, uid=uid)
        audit_log("calendar_event_delete", {"entity_id": entity_id, "uid": uid})
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"error": "Operation failed"}), 500


@schedules_bp.route("/api/calendar/shift-sync", methods=["GET"])
def api_get_shift_sync_config():
    """Get shift-to-calendar sync configuration."""
    raw = get_setting("shift_calendar_sync")
    if raw:
        config = json.loads(raw)
    else:
        config = {"enabled": False, "calendar_entity": "", "sync_days": 30}
    return jsonify(config)


@schedules_bp.route("/api/calendar/shift-sync", methods=["PUT"])
def api_update_shift_sync_config():
    """Update shift-to-calendar sync configuration."""
    data = request.json or {}
    config = {
        "enabled": bool(data.get("enabled", False)),
        "calendar_entity": data.get("calendar_entity", "").strip(),
        "sync_days": min(max(int(data.get("sync_days", 30)), 7), 90),
    }
    set_setting("shift_calendar_sync", json.dumps(config))
    audit_log("shift_sync_config_update", config)
    return jsonify({"success": True, **config})


@schedules_bp.route("/api/calendar/shift-sync/run", methods=["POST"])
def api_run_shift_sync_now():
    """Trigger an immediate full shift-to-calendar resync (delete + recreate)."""
    scheduler = _deps.get("automation_scheduler")
    if scheduler:
        try:
            scheduler._shift_calendar_sync_task(full_resync=True)
            return jsonify({"success": True, "message": "Full resync completed"})
        except Exception as e:
            logger.error("Operation failed: %s", e)
            return jsonify({"error": "Operation failed"}), 500
    return jsonify({"error": "Scheduler not available"}), 503
