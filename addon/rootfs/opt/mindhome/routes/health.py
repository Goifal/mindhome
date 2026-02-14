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
