# MindHome - routes/health.py | see version.py for version info
"""
MindHome API Routes - Health & Phase 4 Features
Phase 4 health endpoints + feature flag management.
"""

import logging
from flask import Blueprint, request, jsonify

from helpers import get_setting, set_setting

logger = logging.getLogger("mindhome.routes.health")

health_bp = Blueprint("health", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_health(dependencies):
    """Initialize health routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _event_bus():
    return _deps.get("event_bus")


# ──────────────────────────────────────────────
# Phase 4 Feature Flags
# ──────────────────────────────────────────────

# Feature definitions: key -> {default, requires (sensor hint)}
PHASE4_FEATURES = {
    "phase4.sleep_detection":      {"default": "auto", "requires": "motion_sensor_bedroom"},
    "phase4.sleep_quality":        {"default": "auto", "requires": "temp_or_co2_sensor"},
    "phase4.smart_wakeup":         {"default": "auto", "requires": "dimmable_light_bedroom"},
    "phase4.energy_optimization":  {"default": "auto", "requires": "power_sensors"},
    "phase4.pv_management":        {"default": "auto", "requires": "solar_sensors"},
    "phase4.standby_killer":       {"default": "auto", "requires": "power_sensors_devices"},
    "phase4.energy_forecast":      {"default": "auto", "requires": "energy_readings_history"},
    "phase4.comfort_score":        {"default": "auto", "requires": "temp_or_humidity_or_co2"},
    "phase4.ventilation_reminder": {"default": "auto", "requires": "co2_or_window_contact"},
    "phase4.circadian_lighting":   {"default": "auto", "requires": "dimmable_lights"},
    "phase4.weather_alerts":       {"default": "auto", "requires": "weather_entity"},
    "phase4.screen_time":          {"default": "auto", "requires": "media_player_entity"},
    "phase4.mood_estimate":        {"default": "auto", "requires": "multiple_active_domains"},
    "phase4.room_transitions":     {"default": "auto", "requires": "motion_sensors_multi_room"},
    "phase4.visit_preparation":    {"default": "true", "requires": None},
    "phase4.vacation_detection":   {"default": "auto", "requires": "person_tracking"},
    "phase4.habit_drift":          {"default": "auto", "requires": "pattern_data_30d"},
    "phase4.adaptive_timing":      {"default": "true", "requires": None},
    "phase4.calendar_integration": {"default": "auto", "requires": "calendar_entity"},
    "phase4.health_dashboard":     {"default": "true", "requires": None},
}


def _resolve_feature_status(stored_value):
    """Resolve actual enabled/disabled status for a feature.

    Values: 'true' (always on), 'false' (always off), 'auto' (check sensors).
    Auto-detect returns True for now — actual sensor detection added per batch.
    """
    if stored_value == "true":
        return True
    if stored_value == "false":
        return False
    # auto — default to True (sensor detection added per feature batch)
    return True


@health_bp.route("/api/system/phase4-features", methods=["GET"])
def api_get_phase4_features():
    """List all Phase 4 features with their status and requirements."""
    features = []
    for key, fdef in PHASE4_FEATURES.items():
        stored = get_setting(key, fdef["default"])
        enabled = _resolve_feature_status(stored)
        features.append({
            "key": key,
            "value": stored,
            "enabled": enabled,
            "requires": fdef["requires"],
            "default": fdef["default"],
        })
    return jsonify(features)


@health_bp.route("/api/system/phase4-features/<path:key>", methods=["PUT"])
def api_set_phase4_feature(key):
    """Enable/disable a Phase 4 feature. Body: {"value": "true"|"false"|"auto"}"""
    if key not in PHASE4_FEATURES:
        return jsonify({"error": "Unknown feature key"}), 404

    data = request.json or {}
    value = data.get("value", "auto")
    if value not in ("true", "false", "auto"):
        return jsonify({"error": "Value must be 'true', 'false', or 'auto'"}), 400

    set_setting(key, value)
    fdef = PHASE4_FEATURES[key]
    enabled = _resolve_feature_status(value)
    return jsonify({"key": key, "value": value, "enabled": enabled, "success": True})


def is_feature_enabled(feature_key):
    """Check if a Phase 4 feature is enabled. For use by engines/scheduler."""
    fdef = PHASE4_FEATURES.get(feature_key)
    if not fdef:
        return False
    stored = get_setting(feature_key, fdef["default"])
    return _resolve_feature_status(stored)


# ──────────────────────────────────────────────
# Batch 2: Sleep Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/sleep", methods=["GET"])
def api_get_sleep_data():
    """Get recent sleep sessions."""
    detector = _deps.get("sleep_detector")
    if not detector:
        return jsonify([])
    days = request.args.get("days", 7, type=int)
    user_id = request.args.get("user_id", type=int)
    return jsonify(detector.get_recent_sessions(user_id=user_id, days=days))


@health_bp.route("/api/health/sleep-quality", methods=["GET"])
def api_get_sleep_quality():
    """Get sleep quality trend (last N days)."""
    detector = _deps.get("sleep_detector")
    if not detector:
        return jsonify({"sessions": [], "avg_quality": None, "avg_duration": None})
    days = request.args.get("days", 14, type=int)
    sessions = detector.get_recent_sessions(days=days)
    completed = [s for s in sessions if s.get("quality_score") is not None and s.get("duration_hours")]
    avg_quality = round(sum(s["quality_score"] for s in completed) / len(completed), 1) if completed else None
    avg_duration = round(sum(s["duration_hours"] for s in completed) / len(completed), 1) if completed else None
    return jsonify({
        "sessions": sessions,
        "avg_quality": avg_quality,
        "avg_duration": avg_duration,
        "total_nights": len(completed),
    })


# ──────────────────────────────────────────────
# Batch 2: Wake-Up Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/wakeup", methods=["GET"])
def api_get_wakeup_configs():
    """Get all wake-up configurations."""
    manager = _deps.get("wakeup_manager")
    if not manager:
        return jsonify([])
    user_id = request.args.get("user_id", type=int)
    return jsonify(manager.get_configs(user_id=user_id))


@health_bp.route("/api/health/wakeup", methods=["POST"])
def api_create_wakeup_config():
    """Create a new wake-up configuration."""
    from db import get_db
    from models import WakeUpConfig
    data = request.json or {}
    session = get_db()
    try:
        cfg = WakeUpConfig(
            user_id=data.get("user_id"),
            enabled=data.get("enabled", True),
            wake_time=data.get("wake_time"),
            linked_to_schedule=data.get("linked_to_schedule", True),
            light_entity=data.get("light_entity"),
            climate_entity=data.get("climate_entity"),
            cover_entity=data.get("cover_entity"),
            ramp_minutes=data.get("ramp_minutes", 20),
        )
        session.add(cfg)
        session.commit()
        return jsonify({"id": cfg.id, "success": True})
    finally:
        session.close()


@health_bp.route("/api/health/wakeup/<int:config_id>", methods=["PUT"])
def api_update_wakeup_config(config_id):
    """Update a wake-up configuration."""
    from db import get_db
    from models import WakeUpConfig
    data = request.json or {}
    session = get_db()
    try:
        cfg = session.get(WakeUpConfig, config_id)
        if not cfg:
            return jsonify({"error": "Not found"}), 404
        for key in ["enabled", "wake_time", "linked_to_schedule", "light_entity",
                     "climate_entity", "cover_entity", "ramp_minutes", "is_active"]:
            if key in data:
                setattr(cfg, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@health_bp.route("/api/health/wakeup/<int:config_id>", methods=["DELETE"])
def api_delete_wakeup_config(config_id):
    """Delete a wake-up configuration."""
    from db import get_db
    from models import WakeUpConfig
    session = get_db()
    try:
        cfg = session.get(WakeUpConfig, config_id)
        if cfg:
            session.delete(cfg)
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


# ──────────────────────────────────────────────
# Batch 2: Routines Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/routines", methods=["GET"])
def api_get_routines():
    """Get detected routines."""
    engine = _deps.get("routine_engine")
    if not engine:
        return jsonify([])
    return jsonify(engine.get_routines())


@health_bp.route("/api/health/routines/<routine_id>/activate", methods=["POST"])
def api_activate_routine(routine_id):
    """Manually activate a routine."""
    engine = _deps.get("routine_engine")
    if not engine:
        return jsonify({"error": "Not available"}), 503
    result = engine.activate_routine(routine_id)
    return jsonify(result)


@health_bp.route("/api/health/room-transitions", methods=["GET"])
def api_get_room_transitions():
    """Get detected room transition patterns."""
    engine = _deps.get("routine_engine")
    if not engine:
        return jsonify([])
    return jsonify(engine.detect_room_transitions())


# ──────────────────────────────────────────────
# Batch 2: Visit Preparation Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/visit-preparations", methods=["GET"])
def api_get_visit_preparations():
    """Get all visit preparation templates."""
    manager = _deps.get("visit_manager")
    if not manager:
        return jsonify([])
    return jsonify(manager.get_preparations())


@health_bp.route("/api/health/visit-preparations", methods=["POST"])
def api_create_visit_preparation():
    """Create a new visit preparation."""
    from db import get_db
    from models import VisitPreparation
    data = request.json or {}
    session = get_db()
    try:
        prep = VisitPreparation(
            name=data.get("name", "Besuch"),
            guest_count=data.get("guest_count", 1),
            preparation_actions=data.get("preparation_actions", []),
            auto_trigger=data.get("auto_trigger", False),
            trigger_config=data.get("trigger_config"),
        )
        session.add(prep)
        session.commit()
        return jsonify({"id": prep.id, "success": True})
    finally:
        session.close()


@health_bp.route("/api/health/visit-preparations/<int:prep_id>", methods=["PUT"])
def api_update_visit_preparation(prep_id):
    """Update a visit preparation."""
    from db import get_db
    from models import VisitPreparation
    data = request.json or {}
    session = get_db()
    try:
        prep = session.get(VisitPreparation, prep_id)
        if not prep:
            return jsonify({"error": "Not found"}), 404
        for key in ["name", "guest_count", "preparation_actions", "auto_trigger", "trigger_config", "is_active"]:
            if key in data:
                setattr(prep, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@health_bp.route("/api/health/visit-preparations/<int:prep_id>", methods=["DELETE"])
def api_delete_visit_preparation(prep_id):
    """Delete a visit preparation."""
    from db import get_db
    from models import VisitPreparation
    session = get_db()
    try:
        prep = session.get(VisitPreparation, prep_id)
        if prep:
            session.delete(prep)
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@health_bp.route("/api/health/visit-preparations/<int:prep_id>/activate", methods=["POST"])
def api_activate_visit_preparation(prep_id):
    """Activate a visit preparation (execute actions)."""
    manager = _deps.get("visit_manager")
    if not manager:
        return jsonify({"error": "Not available"}), 503
    result = manager.activate(prep_id)
    return jsonify(result)


# ──────────────────────────────────────────────
# Batch 2: Vacation Detection Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/vacation-status", methods=["GET"])
def api_get_vacation_status():
    """Get vacation detection status."""
    detector = _deps.get("vacation_detector")
    if not detector:
        return jsonify({"vacation_active": False, "away_since": None, "hours_away": 0})
    return jsonify(detector.get_status())


# ──────────────────────────────────────────────
# Batch 3: Comfort Score & Climate Traffic Light
# ──────────────────────────────────────────────

@health_bp.route("/api/health/comfort", methods=["GET"])
def api_get_comfort_scores():
    """Get current comfort scores per room."""
    calculator = _deps.get("comfort_calculator")
    if not calculator:
        return jsonify([])
    return jsonify(calculator.get_scores())


@health_bp.route("/api/health/comfort/<int:room_id>/history", methods=["GET"])
def api_get_comfort_history(room_id):
    """Get comfort score history for a room."""
    calculator = _deps.get("comfort_calculator")
    if not calculator:
        return jsonify([])
    days = request.args.get("days", 7, type=int)
    return jsonify(calculator.get_history(room_id, days=days))


@health_bp.route("/api/health/climate-traffic-light", methods=["GET"])
def api_get_climate_traffic_light():
    """Get traffic light status per room (green/yellow/red)."""
    calculator = _deps.get("comfort_calculator")
    if not calculator:
        return jsonify([])
    return jsonify(calculator.get_traffic_lights())


# ──────────────────────────────────────────────
# Batch 3: Ventilation Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/ventilation", methods=["GET"])
def api_get_ventilation_status():
    """Get ventilation status per room."""
    monitor = _deps.get("ventilation_monitor")
    if not monitor:
        return jsonify([])
    return jsonify(monitor.get_status())


@health_bp.route("/api/health/ventilation/<int:room_id>", methods=["PUT"])
def api_update_ventilation_config(room_id):
    """Update ventilation config for a room."""
    monitor = _deps.get("ventilation_monitor")
    if not monitor:
        return jsonify({"error": "Not available"}), 503
    data = request.json or {}
    result = monitor.update_config(room_id, data)
    return jsonify(result)


# ──────────────────────────────────────────────
# Batch 3: Circadian Lighting Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/circadian", methods=["GET"])
def api_get_circadian_configs():
    """Get all circadian lighting configurations."""
    manager = _deps.get("circadian_manager")
    if not manager:
        return jsonify([])
    return jsonify(manager.get_configs())


@health_bp.route("/api/health/circadian/status", methods=["GET"])
def api_get_circadian_status():
    """Get current circadian state per room."""
    manager = _deps.get("circadian_manager")
    if not manager:
        return jsonify([])
    return jsonify(manager.get_status())


@health_bp.route("/api/health/circadian", methods=["POST"])
def api_create_circadian_config():
    """Create a new circadian lighting configuration."""
    from db import get_db
    from models import CircadianConfig
    data = request.json or {}
    session = get_db()
    try:
        cfg = CircadianConfig(
            room_id=data.get("room_id"),
            enabled=data.get("enabled", True),
            control_mode=data.get("control_mode", "mindhome"),
            light_type=data.get("light_type", "dim2warm"),
            brightness_curve=data.get("brightness_curve"),
            hcl_pause_ga=data.get("hcl_pause_ga"),
            hcl_resume_ga=data.get("hcl_resume_ga"),
            override_sleep=data.get("override_sleep", 10),
            override_wakeup=data.get("override_wakeup", 70),
            override_guests=data.get("override_guests", 90),
            override_transition_sec=data.get("override_transition_sec", 300),
        )
        session.add(cfg)
        session.commit()
        return jsonify({"id": cfg.id, "success": True})
    finally:
        session.close()


@health_bp.route("/api/health/circadian/<int:config_id>", methods=["PUT"])
def api_update_circadian_config(config_id):
    """Update a circadian lighting configuration."""
    from db import get_db
    from models import CircadianConfig
    data = request.json or {}
    session = get_db()
    try:
        cfg = session.get(CircadianConfig, config_id)
        if not cfg:
            return jsonify({"error": "Not found"}), 404
        for key in ["enabled", "control_mode", "light_type", "brightness_curve",
                     "hcl_pause_ga", "hcl_resume_ga", "override_sleep",
                     "override_wakeup", "override_guests", "override_transition_sec"]:
            if key in data:
                setattr(cfg, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@health_bp.route("/api/health/circadian/<int:config_id>", methods=["DELETE"])
def api_delete_circadian_config(config_id):
    """Delete a circadian lighting configuration."""
    from db import get_db
    from models import CircadianConfig
    session = get_db()
    try:
        cfg = session.get(CircadianConfig, config_id)
        if cfg:
            session.delete(cfg)
            session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


# ──────────────────────────────────────────────
# Batch 3: Weather Alerts Endpoints
# ──────────────────────────────────────────────

@health_bp.route("/api/health/weather-alerts", methods=["GET"])
def api_get_weather_alerts():
    """Get active weather alerts."""
    manager = _deps.get("weather_alert_manager")
    if not manager:
        return jsonify([])
    return jsonify(manager.get_active_alerts())


# ──────────────────────────────────────────────
# Batch 4: Mood, Screen Time, Drift, Adaptive
# ──────────────────────────────────────────────

@health_bp.route("/api/health/mood-estimate", methods=["GET"])
def api_get_mood_estimate():
    """Get current household mood estimate (#15)."""
    estimator = _deps.get("mood_estimator")
    if not estimator:
        return jsonify({"mood": "unknown", "confidence": 0})
    return jsonify(estimator.estimate())


@health_bp.route("/api/health/screen-time", methods=["GET"])
def api_get_screen_time():
    """Get current screen time data (#19)."""
    monitor = _deps.get("screen_time_monitor")
    if not monitor:
        return jsonify([])
    user_id = request.args.get("user_id", type=int)
    return jsonify(monitor.get_usage(user_id))


@health_bp.route("/api/health/screen-time/config", methods=["GET"])
def api_get_screen_time_config():
    """Get screen time configurations."""
    monitor = _deps.get("screen_time_monitor")
    if not monitor:
        return jsonify([])
    return jsonify(monitor.get_config())


@health_bp.route("/api/health/screen-time/config", methods=["POST"])
def api_create_screen_time_config():
    """Create screen time config for a user."""
    from db import get_db
    from models import ScreenTimeConfig
    data = request.json or {}
    session = get_db()
    try:
        cfg = ScreenTimeConfig(
            user_id=data.get("user_id", 1),
            entity_ids=data.get("entity_ids"),
            daily_limit_min=data.get("daily_limit_min", 180),
            reminder_interval_min=data.get("reminder_interval_min", 60),
            is_active=data.get("is_active", True),
        )
        session.add(cfg)
        session.commit()
        return jsonify({"id": cfg.id, "success": True})
    finally:
        session.close()


@health_bp.route("/api/health/screen-time/config/<int:config_id>", methods=["PUT"])
def api_update_screen_time_config(config_id):
    """Update screen time config."""
    from db import get_db
    from models import ScreenTimeConfig
    data = request.json or {}
    session = get_db()
    try:
        cfg = session.get(ScreenTimeConfig, config_id)
        if not cfg:
            return jsonify({"error": "Not found"}), 404
        for key in ["entity_ids", "daily_limit_min", "reminder_interval_min", "is_active"]:
            if key in data:
                setattr(cfg, key, data[key])
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()


@health_bp.route("/api/patterns/drift", methods=["GET"])
def api_get_habit_drift():
    """Get detected habit drifts (#12)."""
    detector = _deps.get("habit_drift_detector")
    if not detector:
        return jsonify([])
    return jsonify(detector.get_drifts())


@health_bp.route("/api/health/adaptive-timing", methods=["GET"])
def api_get_adaptive_timing():
    """Get patterns with adaptive timing data (#11)."""
    manager = _deps.get("adaptive_timing_manager")
    if not manager:
        return jsonify([])
    return jsonify(manager.get_adaptations())


@health_bp.route("/api/system/seasonal-tips", methods=["GET"])
def api_get_seasonal_tips():
    """Get seasonal recommendations (#13)."""
    advisor = _deps.get("seasonal_advisor")
    if not advisor:
        return jsonify({"season": "unknown", "tips": []})
    lang = request.args.get("lang", "de")
    return jsonify(advisor.get_tips(lang))


@health_bp.route("/api/system/calendar-events", methods=["GET"])
def api_get_calendar_events():
    """Get upcoming calendar events (#14)."""
    cal = _deps.get("calendar_integration")
    if not cal:
        return jsonify([])
    hours = request.args.get("hours", 24, type=int)
    return jsonify(cal.get_events(hours))


@health_bp.route("/api/system/calendar-entities", methods=["GET"])
def api_get_calendar_entities():
    """List available HA calendar entities."""
    cal = _deps.get("calendar_integration")
    if not cal:
        return jsonify([])
    return jsonify(cal.get_calendar_entities())


# ──────────────────────────────────────────────
# Health Dashboard (Batch 5 — stub endpoints)
# ──────────────────────────────────────────────

@health_bp.route("/api/health/dashboard", methods=["GET"])
def api_health_dashboard():
    """Aggregated health dashboard data."""
    # TODO: Batch 5 — Aggregate all health data
    return jsonify({
        "sleep": None,
        "comfort": None,
        "climate": None,
        "ventilation": None,
        "screen_time": None,
        "mood": None,
    })
