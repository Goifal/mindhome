# MindHome - routes/energy.py | see version.py for version info
"""
MindHome API Routes - Energy
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

logger = logging.getLogger("mindhome.routes.energy")

energy_bp = Blueprint("energy", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_energy(dependencies):
    """Initialize energy routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@energy_bp.route("/api/energy/summary", methods=["GET"])
def api_energy_summary():
    """Get energy usage summary from tracked power sensors."""
    session = get_db()
    try:
        days = int(request.args.get("days", 7))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Find energy-related state history
        energy_entities = session.query(StateHistory.entity_id).filter(
            StateHistory.entity_id.like("sensor.%energy%") |
            StateHistory.entity_id.like("sensor.%power%"),
            StateHistory.created_at > cutoff
        ).distinct().all()

        entity_ids = [e[0] for e in energy_entities]
        summary = {"entities": [], "total_entries": 0, "days": days}

        for eid in entity_ids[:20]:
            count = session.query(sa_func.count(StateHistory.id)).filter(
                StateHistory.entity_id == eid,
                StateHistory.created_at > cutoff
            ).scalar()
            summary["entities"].append({"entity_id": eid, "data_points": count})
            summary["total_entries"] += count

        # Automation energy savings estimate
        auto_count = session.query(sa_func.count(ActionLog.id)).filter(
            ActionLog.action_type == "automation_executed",
            ActionLog.created_at > cutoff,
            ActionLog.reason.like("%off%")
        ).scalar() or 0
        summary["automations_off_count"] = auto_count
        summary["estimated_kwh_saved"] = round(auto_count * 0.06, 2)

        return jsonify(summary)
    except Exception as e:
        logger.error(f"Energy summary error: {e}")
        return jsonify({"error": str(e), "entities": []})
    finally:
        session.close()


@energy_bp.route("/api/sensor-groups", methods=["GET"])
def api_get_sensor_groups():
    session = get_db()
    try:
        return jsonify([{"id":g.id,"name":g.name,"room_id":g.room_id,"entity_ids":g.entity_ids or [],"fusion_method":g.fusion_method,"is_active":g.is_active} for g in session.query(SensorGroup).all()])
    finally:
        session.close()


@energy_bp.route("/api/sensor-groups", methods=["POST"])
def api_create_sensor_group():
    data = request.json or {}
    session = get_db()
    try:
        sg = SensorGroup(name=data.get("name","Gruppe"), room_id=data.get("room_id"), entity_ids=data.get("entity_ids",[]), fusion_method=data.get("fusion_method","average"))
        session.add(sg); session.commit()
        return jsonify({"id": sg.id, "success": True})
    finally:
        session.close()


@energy_bp.route("/api/sensor-groups/<int:group_id>", methods=["DELETE"])
def api_delete_sensor_group(group_id):
    session = get_db()
    try:
        sg = session.get(SensorGroup, group_id)
        if sg: session.delete(sg); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@energy_bp.route("/api/sensor-thresholds", methods=["GET"])
def api_get_sensor_thresholds():
    session = get_db()
    try:
        return jsonify([{"id":t.id,"entity_id":t.entity_id,"min_change_percent":t.min_change_percent,"min_change_absolute":t.min_change_absolute,"min_interval_seconds":t.min_interval_seconds} for t in session.query(SensorThreshold).all()])
    finally:
        session.close()


@energy_bp.route("/api/sensor-thresholds", methods=["POST"])
def api_create_sensor_threshold():
    data = request.json or {}
    session = get_db()
    try:
        st = SensorThreshold(entity_id=data.get("entity_id"), min_change_percent=data.get("min_change_percent",5.0), min_change_absolute=data.get("min_change_absolute"), min_interval_seconds=data.get("min_interval_seconds",60))
        session.add(st); session.commit()
        return jsonify({"id": st.id, "success": True})
    finally:
        session.close()


@energy_bp.route("/api/sensor-thresholds/<int:tid>", methods=["DELETE"])
def api_delete_sensor_threshold(tid):
    session = get_db()
    try:
        st = session.get(SensorThreshold, tid)
        if st: session.delete(st); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@energy_bp.route("/api/energy/config", methods=["GET"])
def api_get_energy_config():
    session = get_db()
    try:
        cfg = session.query(EnergyConfig).first()
        if not cfg: return jsonify({"price_per_kwh":0.25,"currency":"EUR","solar_enabled":False})
        return jsonify({"id":cfg.id,"price_per_kwh":cfg.price_per_kwh,"currency":cfg.currency,"solar_enabled":cfg.solar_enabled,"solar_entity":cfg.solar_entity,"grid_import_entity":cfg.grid_import_entity,"grid_export_entity":cfg.grid_export_entity})
    finally:
        session.close()


@energy_bp.route("/api/energy/config", methods=["PUT"])
def api_update_energy_config():
    data = request.json or {}
    session = get_db()
    try:
        cfg = session.query(EnergyConfig).first()
        if not cfg: cfg = EnergyConfig(); session.add(cfg)
        for key in ["price_per_kwh","currency","solar_enabled","solar_entity","grid_import_entity","grid_export_entity"]:
            if key in data: setattr(cfg, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@energy_bp.route("/api/energy/readings", methods=["GET"])
def api_get_energy_readings():
    session = get_db()
    try:
        hours = request.args.get("hours", 24, type=int)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        readings = session.query(EnergyReading).filter(EnergyReading.created_at >= cutoff).order_by(EnergyReading.created_at.desc()).limit(500).all()
        return jsonify([{"id":r.id,"entity_id":r.entity_id,"device_id":r.device_id,"room_id":r.room_id,"power_w":r.power_w,"energy_kwh":r.energy_kwh,"reading_type":r.reading_type,"created_at":r.created_at.isoformat() if r.created_at else None} for r in readings])
    finally:
        session.close()


@energy_bp.route("/api/energy/standby-config", methods=["GET"])
def api_get_standby_configs():
    session = get_db()
    try:
        return jsonify([{"id":c.id,"device_id":c.device_id,"entity_id":c.entity_id,"threshold_watts":c.threshold_watts,"idle_minutes":c.idle_minutes,"notify_dashboard":c.notify_dashboard,"auto_off":c.auto_off,"is_active":c.is_active} for c in session.query(StandbyConfig).all()])
    finally:
        session.close()


@energy_bp.route("/api/energy/standby-config", methods=["POST"])
def api_create_standby_config():
    data = request.json or {}
    session = get_db()
    try:
        sc = StandbyConfig(device_id=data.get("device_id"), entity_id=data.get("entity_id"), threshold_watts=data.get("threshold_watts",5.0), idle_minutes=data.get("idle_minutes",30), auto_off=data.get("auto_off",False))
        session.add(sc); session.commit()
        return jsonify({"id": sc.id, "success": True})
    finally:
        session.close()


@energy_bp.route("/api/energy/standby-config/<int:sc_id>", methods=["PUT"])
def api_update_standby_config(sc_id):
    data = request.json or {}
    session = get_db()
    try:
        sc = session.get(StandbyConfig, sc_id)
        if not sc: return jsonify({"error": "Not found"}), 404
        for key in ["threshold_watts","idle_minutes","notify_dashboard","auto_off","is_active"]:
            if key in data: setattr(sc, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@energy_bp.route("/api/energy/standby-config/<int:sc_id>", methods=["DELETE"])
def api_delete_standby_config(sc_id):
    session = get_db()
    try:
        sc = session.get(StandbyConfig, sc_id)
        if sc: session.delete(sc); session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@energy_bp.route("/api/energy/discover-sensors", methods=["GET"])
def api_discover_energy_sensors():
    """Auto-discover energy/power sensors from HA."""
    try:
        all_states = _ha().get_states() or []
        sensors = []
        for s in all_states:
            eid = s.get("entity_id","")
            attrs = s.get("attributes",{})
            unit = attrs.get("unit_of_measurement","")
            device_class = attrs.get("device_class","")
            if device_class in ("energy","power") or unit in ("W","kW","Wh","kWh","mW"):
                sensors.append({
                    "entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                    "state": s.get("state"),
                    "unit": unit,
                    "device_class": device_class,
                })
        return jsonify(sensors)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@energy_bp.route("/api/energy/stats", methods=["GET"])
def api_energy_stats():
    """Get energy stats: today, week, month costs."""
    session = get_db()
    try:
        cfg = session.query(EnergyConfig).first()
        price = cfg.price_per_kwh if cfg else 0.25
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)
        def sum_kwh(since):
            readings = session.query(EnergyReading).filter(EnergyReading.created_at >= since).all()
            return sum(r.energy_kwh or 0 for r in readings)
        today_kwh = sum_kwh(today_start)
        week_kwh = sum_kwh(week_start)
        month_kwh = sum_kwh(month_start)
        return jsonify({
            "today": {"kwh": round(today_kwh, 2), "cost": round(today_kwh * price, 2)},
            "week": {"kwh": round(week_kwh, 2), "cost": round(week_kwh * price, 2)},
            "month": {"kwh": round(month_kwh, 2), "cost": round(month_kwh * price, 2)},
            "price_per_kwh": price, "currency": cfg.currency if cfg else "EUR"
        })
    finally:
        session.close()


# ==============================================================================
# Phase 4 Batch 1 — Energy Optimization, PV, Standby, Forecast
# ==============================================================================

@energy_bp.route("/api/energy/optimization", methods=["GET"])
def api_energy_optimization():
    """Get energy optimization recommendations (#1)."""
    optimizer = _deps.get("energy_optimizer")
    if not optimizer:
        return jsonify({"recommendations": [], "last_analysis": None})
    return jsonify({
        "recommendations": optimizer.get_recommendations(),
        "last_analysis": optimizer._last_analysis.isoformat() if optimizer._last_analysis else None,
    })


@energy_bp.route("/api/energy/savings", methods=["GET"])
def api_energy_savings():
    """Get estimated energy savings (#1)."""
    optimizer = _deps.get("energy_optimizer")
    if not optimizer:
        return jsonify({"estimated_monthly_eur": 0, "potential_kwh": 0})
    return jsonify(optimizer.get_savings_estimate())


@energy_bp.route("/api/energy/forecast", methods=["GET"])
def api_energy_forecast():
    """Get energy forecast for next N days (#26)."""
    forecaster = _deps.get("energy_forecaster")
    if not forecaster:
        return jsonify([])
    days = request.args.get("days", 7, type=int)
    return jsonify(forecaster.get_forecast(days=days))


@energy_bp.route("/api/energy/pv-status", methods=["GET"])
def api_pv_status():
    """Get current PV production/consumption/surplus (#2)."""
    optimizer = _deps.get("energy_optimizer")
    if not optimizer:
        return jsonify({"error": "Not available"}), 503
    status = optimizer.get_pv_status()
    if not status:
        return jsonify({"error": "PV not configured or feature disabled"}), 404
    return jsonify(status)


@energy_bp.route("/api/energy/pv-priorities", methods=["PUT"])
def api_set_pv_priorities():
    """Set PV load management priorities (#2)."""
    data = request.json or {}
    session = get_db()
    try:
        cfg = session.query(EnergyConfig).first()
        if not cfg:
            cfg = EnergyConfig()
            session.add(cfg)
        if "enabled" in data:
            cfg.pv_load_management = data["enabled"]
        if "priority_entities" in data:
            cfg.pv_priority_entities = data["priority_entities"]
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@energy_bp.route("/api/energy/standby-status", methods=["GET"])
def api_standby_status():
    """Get current standby devices (#3)."""
    monitor = _deps.get("standby_monitor")
    if not monitor:
        return jsonify([])
    return jsonify(monitor.get_standby_status())
