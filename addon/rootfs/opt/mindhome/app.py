# MindHome app v0.6.2 (2026-02-10) - app.py
"""
MindHome - Main Application Entry Point
Flask backend initialization, middleware, and startup.
All API routes are in routes/ directory as Flask Blueprints.
"""

import os
import sys
import json
import signal
import logging
import threading
import time
import mimetypes
from datetime import datetime, timezone

from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from sqlalchemy import text

from version import version_string, version_info, VERSION, BUILD
from db import init_db, get_db, get_db_session, get_db_readonly
from helpers import (
    init_timezone, get_ha_timezone, local_now, rate_limit_check,
    get_setting, set_setting, get_language, is_debug_mode,
    extract_display_attributes, build_state_reason,
)
from models import (
    get_engine, get_session, init_database, run_migrations,
    Device, Domain, RoomDomainState, SystemSetting, ActionLog,
    StateHistory,
)
from ha_connection import HAConnection
from event_bus import event_bus
from task_scheduler import task_scheduler

try:
    from domains import DomainManager
except ImportError:
    DomainManager = None

from pattern_engine import EventBus as LegacyEventBus, StateLogger, PatternScheduler, PatternDetector
from automation_engine import (
    AutomationScheduler, FeedbackProcessor, AutomationExecutor,
    PhaseManager, NotificationManager, AnomalyDetector, ConflictDetector
)

# ==============================================================================
# App Configuration
# ==============================================================================

app = Flask(__name__, static_folder="static", template_folder="templates")
app.json.ensure_ascii = False
app.config['JSON_AS_ASCII'] = False
app.config['JSONIFY_MIMETYPE'] = 'application/json; charset=utf-8'
CORS(app, supports_credentials=False)

mimetypes.add_type("text/javascript", ".jsx")
mimetypes.add_type("text/javascript", ".mjs")

# Logging
log_level = os.environ.get("MINDHOME_LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("mindhome")

# Ingress path
INGRESS_PATH = os.environ.get("INGRESS_PATH", "")

# Database
engine = get_engine()
init_database(engine)
run_migrations(engine)
init_db(engine)

# Ensure new system domains exist in DB (for upgrades)
try:
    from init_db import create_default_domains
    with get_db_session() as session:
        create_default_domains(session)
except Exception as e:
    logger.warning(f"Domain seed check: {e}")

# Fix: Auto-set is_controllable=False for sensor-type entities
try:
    with get_db_session() as session:
        NON_CONTROLLABLE = (
            "sensor.", "binary_sensor.", "zone.", "sun.", "weather.",
            "person.", "device_tracker.", "calendar.", "proximity."
        )
        updated = 0
        for dev in session.query(Device).filter_by(is_controllable=True).all():
            if dev.ha_entity_id and any(dev.ha_entity_id.startswith(p) for p in NON_CONTROLLABLE):
                dev.is_controllable = False
                updated += 1
        if updated:
            logger.info(f"Auto-fixed is_controllable for {updated} sensor-type devices")
except Exception as e:
    logger.warning(f"Controllable migration: {e}")

# Home Assistant connection
ha = HAConnection()

# Domain Plugin Configuration
DOMAIN_PLUGINS = {
    "light": {
        "ha_domain": "light",
        "attributes": ["brightness", "color_temp", "rgb_color", "effect"],
        "controls": [
            {"service": "toggle", "label_de": "Ein/Aus", "label_en": "Toggle"},
            {"service": "brightness", "label_de": "Helligkeit", "label_en": "Brightness"},
            {"service": "color_temp", "label_de": "Farbtemperatur", "label_en": "Color temperature"},
        ],
        "pattern_features": [
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "brightness_level", "label_de": "Helligkeitsstufe", "label_en": "Brightness level"},
            {"key": "duration", "label_de": "Dauer", "label_en": "Duration"},
        ],
        "icon": "mdi:lightbulb",
    },
    "climate": {
        "ha_domain": "climate",
        "attributes": ["current_temperature", "temperature", "hvac_action", "humidity"],
        "controls": [
            {"service": "set_temperature", "label_de": "Temperatur einstellen", "label_en": "Set temperature"},
            {"service": "set_hvac_mode", "label_de": "Modus einstellen", "label_en": "Set HVAC mode"},
        ],
        "pattern_features": [
            {"key": "target_temp", "label_de": "Zieltemperatur", "label_en": "Target temperature"},
            {"key": "schedule", "label_de": "Zeitplan", "label_en": "Schedule"},
            {"key": "comfort_profile", "label_de": "Komfortprofil", "label_en": "Comfort profile"},
        ],
        "icon": "mdi:thermostat",
    },
    "cover": {
        "ha_domain": "cover",
        "attributes": ["current_position", "current_tilt_position"],
        "controls": [
            {"service": "open", "label_de": "Öffnen", "label_en": "Open"},
            {"service": "close", "label_de": "Schließen", "label_en": "Close"},
            {"service": "set_position", "label_de": "Position einstellen", "label_en": "Set position"},
        ],
        "pattern_features": [
            {"key": "position", "label_de": "Position", "label_en": "Position"},
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "sun_based", "label_de": "Sonnenstandbasiert", "label_en": "Sun-based"},
        ],
        "icon": "mdi:window-shutter",
    },
    "switch": {
        "ha_domain": "switch",
        "attributes": ["current_power_w", "today_energy_kwh"],
        "controls": [
            {"service": "toggle", "label_de": "Ein/Aus", "label_en": "Toggle"},
        ],
        "pattern_features": [
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "duration", "label_de": "Dauer", "label_en": "Duration"},
        ],
        "icon": "mdi:toggle-switch",
    },
    "sensor": {
        "ha_domain": "sensor",
        "attributes": ["unit_of_measurement", "device_class"],
        "controls": [],
        "pattern_features": [
            {"key": "threshold", "label_de": "Schwellwert", "label_en": "Threshold"},
            {"key": "trend", "label_de": "Trend", "label_en": "Trend"},
        ],
        "icon": "mdi:eye",
    },
    "binary_sensor": {
        "ha_domain": "binary_sensor",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": [
            {"key": "trigger", "label_de": "Auslöser", "label_en": "Trigger"},
            {"key": "duration", "label_de": "Dauer", "label_en": "Duration"},
            {"key": "frequency", "label_de": "Häufigkeit", "label_en": "Frequency"},
        ],
        "icon": "mdi:checkbox-blank-circle-outline",
    },
    "media_player": {
        "ha_domain": "media_player",
        "attributes": ["media_title", "volume_level", "source"],
        "controls": [
            {"service": "toggle", "label_de": "Ein/Aus", "label_en": "Toggle"},
            {"service": "volume", "label_de": "Lautstärke", "label_en": "Volume"},
            {"service": "source", "label_de": "Quelle", "label_en": "Source"},
        ],
        "pattern_features": [
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "source_preference", "label_de": "Quellen-Präferenz", "label_en": "Source preference"},
        ],
        "icon": "mdi:speaker",
    },
    "lock": {
        "ha_domain": "lock",
        "attributes": [],
        "controls": [
            {"service": "lock", "label_de": "Abschließen", "label_en": "Lock"},
            {"service": "unlock", "label_de": "Aufschließen", "label_en": "Unlock"},
        ],
        "pattern_features": [
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "presence", "label_de": "Anwesenheit", "label_en": "Presence"},
        ],
        "icon": "mdi:lock",
    },
    "fan": {
        "ha_domain": "fan",
        "attributes": ["percentage", "preset_mode"],
        "controls": [
            {"service": "toggle", "label_de": "Ein/Aus", "label_en": "Toggle"},
            {"service": "set_percentage", "label_de": "Stufe einstellen", "label_en": "Set speed"},
        ],
        "pattern_features": [
            {"key": "temperature_based", "label_de": "Temperaturbasiert", "label_en": "Temperature-based"},
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
        ],
        "icon": "mdi:fan",
    },
    "motion": {
        "ha_domain": "binary_sensor",
        "device_class": "motion",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": [
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "frequency", "label_de": "Häufigkeit", "label_en": "Frequency"},
            {"key": "duration", "label_de": "Dauer", "label_en": "Duration"},
            {"key": "room_correlation", "label_de": "Raum-Korrelation", "label_en": "Room correlation"},
        ],
        "icon": "mdi:motion-sensor",
    },
    "presence": {
        "ha_domain": "person",
        "attributes": ["source", "gps_accuracy"],
        "controls": [],
        "pattern_features": [
            {"key": "arrival_time", "label_de": "Ankunftszeit", "label_en": "Arrival time"},
            {"key": "departure_time", "label_de": "Abfahrtszeit", "label_en": "Departure time"},
            {"key": "routine", "label_de": "Routine", "label_en": "Routine"},
            {"key": "proximity", "label_de": "Proximität", "label_en": "Proximity"},
        ],
        "icon": "mdi:account-multiple",
    },
    "door_window": {
        "ha_domain": "binary_sensor",
        "device_class": "door",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": [
            {"key": "open_duration", "label_de": "Öffnungsdauer", "label_en": "Open duration"},
            {"key": "frequency", "label_de": "Häufigkeit", "label_en": "Frequency"},
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
        ],
        "icon": "mdi:door",
    },
    "energy": {
        "ha_domain": "sensor",
        "device_class": "energy",
        "attributes": ["unit_of_measurement", "state_class"],
        "controls": [],
        "pattern_features": [
            {"key": "daily_usage", "label_de": "Tagesverbrauch", "label_en": "Daily usage"},
            {"key": "peak_hours", "label_de": "Spitzenzeiten", "label_en": "Peak hours"},
            {"key": "baseline", "label_de": "Grundlast", "label_en": "Baseline"},
        ],
        "icon": "mdi:flash",
    },
    "weather": {
        "ha_domain": "weather",
        "attributes": ["temperature", "humidity", "forecast"],
        "controls": [],
        "pattern_features": [
            {"key": "condition_correlation", "label_de": "Wetter-Korrelation", "label_en": "Condition correlation"},
        ],
        "icon": "mdi:weather-cloudy",
    },
    "bed_occupancy": {
        "ha_domain": "binary_sensor",
        "device_class": "occupancy",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": [
            {"key": "sleep_start", "label_de": "Schlafbeginn", "label_en": "Sleep start"},
            {"key": "sleep_end", "label_de": "Schlafende", "label_en": "Sleep end"},
            {"key": "duration", "label_de": "Dauer", "label_en": "Duration"},
        ],
        "icon": "mdi:bed",
    },
    "seat_occupancy": {
        "ha_domain": "binary_sensor",
        "device_class": "occupancy",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": [
            {"key": "occupied_duration", "label_de": "Belegungsdauer", "label_en": "Occupied duration"},
            {"key": "frequency", "label_de": "Häufigkeit", "label_en": "Frequency"},
        ],
        "icon": "mdi:seat",
    },
    "vacuum": {
        "ha_domain": "vacuum",
        "attributes": ["battery_level", "status"],
        "controls": [
            {"service": "start", "label_de": "Starten", "label_en": "Start"},
            {"service": "stop", "label_de": "Stoppen", "label_en": "Stop"},
            {"service": "return_to_base", "label_de": "Zur Ladestation", "label_en": "Return to base"},
        ],
        "pattern_features": [
            {"key": "schedule", "label_de": "Zeitplan", "label_en": "Schedule"},
            {"key": "presence", "label_de": "Anwesenheit", "label_en": "Presence"},
        ],
        "icon": "mdi:robot-vacuum",
    },
    "system": {
        "ha_domain": "sensor",
        "device_class": "battery",
        "attributes": ["device_class", "unit_of_measurement"],
        "controls": [],
        "pattern_features": [
            {"key": "battery_trend", "label_de": "Akku-Trend", "label_en": "Battery trend"},
            {"key": "connectivity", "label_de": "Verbindungsstatus", "label_en": "Connectivity"},
        ],
        "icon": "mdi:cellphone-link",
    },
    "motion_control": {
        "ha_domain": "switch",
        "device_class": "motion",
        "attributes": ["device_class"],
        "controls": [
            {"service": "toggle", "label_de": "Ein/Aus", "label_en": "Toggle"},
            {"service": "turn_on", "label_de": "Einschalten", "label_en": "Turn on"},
            {"service": "turn_off", "label_de": "Ausschalten", "label_en": "Turn off"},
        ],
        "pattern_features": [
            {"key": "quiet_hours", "label_de": "Ruhezeiten", "label_en": "Quiet hours"},
            {"key": "presence_based", "label_de": "Anwesenheitsbasiert", "label_en": "Presence-based"},
        ],
        "icon": "mdi:motion-sensor-off",
    },
    "humidifier": {
        "ha_domain": "humidifier",
        "attributes": ["current_humidity", "target_humidity", "mode"],
        "controls": [
            {"service": "toggle", "label_de": "Ein/Aus", "label_en": "Toggle"},
            {"service": "set_humidity", "label_de": "Feuchtigkeit einstellen", "label_en": "Set humidity"},
            {"service": "set_mode", "label_de": "Modus einstellen", "label_en": "Set mode"},
        ],
        "pattern_features": [
            {"key": "humidity_target", "label_de": "Ziel-Feuchtigkeit", "label_en": "Humidity target"},
            {"key": "time_of_day", "label_de": "Tageszeit", "label_en": "Time of day"},
            {"key": "air_quality_based", "label_de": "Luftqualitätsbasiert", "label_en": "Air quality-based"},
        ],
        "icon": "mdi:air-humidifier",
    },
    "camera": {
        "ha_domain": "camera",
        "attributes": ["brand", "model_name", "frontend_stream_type"],
        "controls": [],
        "pattern_features": [
            {"key": "presence_based", "label_de": "Anwesenheitsbasiert", "label_en": "Presence-based"},
            {"key": "recording", "label_de": "Aufnahme", "label_en": "Recording"},
        ],
        "icon": "mdi:cctv",
    },
}

# Domain Manager (optional)
domain_manager = DomainManager(ha, lambda: get_session(engine)) if DomainManager else None

# ML Engines
legacy_event_bus = LegacyEventBus()
state_logger = StateLogger(engine, ha)
pattern_scheduler = PatternScheduler(engine, ha)
automation_scheduler = AutomationScheduler(engine, ha)

# Startup timestamp
_start_time = 0


# ==============================================================================
# State Change Handler
# ==============================================================================

# Dedup cache for state change events (#15)
# Fix #12: Added threading lock for thread safety
_recent_events = {}
_recent_events_lock = threading.Lock()
_DEDUP_WINDOW = 1.0  # seconds


def on_state_changed(event):
    """Handle real-time state change events from HA."""
    if domain_manager:
        domain_manager.on_state_change(event)

    event_data = event.get("data", {}) if event else {}
    entity_id = event_data.get("entity_id", "")
    new_state = event_data.get("new_state") or {}
    old_state = event_data.get("old_state") or {}

    # #15: Deduplicate events (same entity+state within 1 second)
    # Fix #12: Thread-safe dedup with lock
    now = time.time()
    new_val = new_state.get("state", "") if isinstance(new_state, dict) else ""
    dedup_key = f"{entity_id}:{new_val}"

    with _recent_events_lock:
        last_seen = _recent_events.get(dedup_key, 0)
        if now - last_seen < _DEDUP_WINDOW:
            return  # Skip duplicate
        _recent_events[dedup_key] = now

        # Cleanup dedup cache periodically (evict expired entries, keep max 500)
        if len(_recent_events) > 500:
            cutoff = now - _DEDUP_WINDOW * 2
            expired = [k for k, v in _recent_events.items() if v < cutoff]
            for k in expired:
                del _recent_events[k]

    # Log to state_history via pattern engine
    try:
        state_logger.log_state_change(event_data)
    except Exception as e:
        logger.debug(f"Pattern state log error: {e}")

    # Publish to legacy event bus
    legacy_event_bus.publish("state_changed", event_data)

    # Publish to new event bus
    event_bus.publish("state.changed", event_data, source="ha")

    # Real-time presence detection: trigger on person/device_tracker changes
    try:
        new_val_p = new_state.get("state", "") if isinstance(new_state, dict) else ""
        old_val_p = old_state.get("state", "") if isinstance(old_state, dict) else ""
        if (entity_id.startswith("person.") or entity_id.startswith("device_tracker.")) and new_val_p != old_val_p:
            if hasattr(automation_scheduler, 'presence_mgr'):
                threading.Thread(
                    target=automation_scheduler.presence_mgr.check_auto_transitions,
                    daemon=True,
                ).start()
                logger.info(f"Presence check triggered by {entity_id}: {old_val_p} -> {new_val_p}")
    except Exception as e:
        logger.debug(f"Presence event trigger error: {e}")

    # Log tracked device state changes
    try:
        new_val = new_state.get("state", "unknown") if isinstance(new_state, dict) else "unknown"
        old_val = old_state.get("state", "unknown") if isinstance(old_state, dict) else "unknown"
        new_attrs = new_state.get("attributes", {}) if isinstance(new_state, dict) else {}
        old_attrs = old_state.get("attributes", {}) if isinstance(old_state, dict) else {}

        if entity_id and new_val != old_val:
            log_state_change(entity_id, new_val, old_val, new_attrs, old_attrs)
    except Exception as e:
        logger.debug(f"State log error: {e}")


def log_state_change(entity_id, new_val, old_val, new_attrs, old_attrs):
    """Log a device state change to the action log."""
    try:
        with get_db_session() as session:
            device = session.query(Device).filter_by(ha_entity_id=entity_id).first()
            if not device or not device.is_tracked:
                return

            new_display = extract_display_attributes(entity_id, new_attrs)
            old_display = extract_display_attributes(entity_id, old_attrs)
            reason = build_state_reason(device.name, old_val, new_val, new_display)

            log = ActionLog(
                action_type="observation",
                domain_id=device.domain_id,
                room_id=device.room_id,
                device_id=device.id,
                action_data={
                    "entity_id": entity_id,
                    "old_state": old_val,
                    "new_state": new_val,
                    "new_attributes": new_display,
                    "old_attributes": old_display,
                },
                reason=reason,
                previous_state={"state": old_val, "attributes": old_display},
            )
            session.add(log)
    except Exception as e:
        logger.debug(f"Log state change error: {e}")


# ==============================================================================
# Middleware
# ==============================================================================

@app.before_request
def before_request_middleware():
    """Rate limiting + ingress token check."""
    if request.path.startswith("/static") or request.path == "/":
        return None
    if request.path.startswith("/api/"):
        ip = request.remote_addr or "unknown"
        if not rate_limit_check(ip):
            return jsonify({"error": "Rate limit exceeded"}), 429
    return None


@app.errorhandler(500)
def handle_500(error):
    logger.error(f"Unhandled 500 error: {error}")
    return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return redirect("/")


@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Unhandled exception: {type(error).__name__}: {error}")
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return redirect("/")


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ==============================================================================
# Register Blueprints
# ==============================================================================

# Phase 4 Batch 1: Energy engines
from engines.energy import EnergyOptimizer, StandbyMonitor, EnergyForecaster
energy_optimizer = EnergyOptimizer(ha, get_db_session)
standby_monitor = StandbyMonitor(ha, get_db_session, event_bus)
energy_forecaster = EnergyForecaster(ha, get_db_session)

# Phase 4 Batch 2: Sleep, Routines, Visit, Vacation engines
from engines.sleep import SleepDetector, WakeUpManager
from engines.routines import RoutineEngine
from engines.visit import VisitPreparationManager, VacationDetector
sleep_detector = SleepDetector(ha, get_db_session, event_bus)
wakeup_manager = WakeUpManager(ha, get_db_session, event_bus)
routine_engine = RoutineEngine(ha, get_db_session, event_bus)
visit_manager = VisitPreparationManager(ha, get_db_session, event_bus)
vacation_detector = VacationDetector(ha, get_db_session, event_bus)

# Phase 4 Batch 3: Comfort, Ventilation, Circadian, Weather engines
from engines.comfort import ComfortCalculator, VentilationMonitor
from engines.circadian import CircadianLightManager
from engines.weather_alerts import WeatherAlertManager
comfort_calculator = ComfortCalculator(ha, get_db_session)
ventilation_monitor = VentilationMonitor(ha, get_db_session, event_bus)
circadian_manager = CircadianLightManager(ha, get_db_session, event_bus)
weather_alert_manager = WeatherAlertManager(ha, get_db_session, event_bus)

# Phase 4 Batch 4: KI, Kalender & UX engines
from engines.comfort import ScreenTimeMonitor
from engines.routines import MoodEstimator
from engines.adaptive import HabitDriftDetector, AdaptiveTimingManager, GradualTransitioner, SeasonalAdvisor, CalendarIntegration
from engines.health_dashboard import HealthAggregator
mood_estimator = MoodEstimator(ha, get_db_session)
screen_time_monitor = ScreenTimeMonitor(ha, get_db_session, event_bus)
habit_drift_detector = HabitDriftDetector(ha, get_db_session, event_bus)
adaptive_timing_manager = AdaptiveTimingManager(ha, get_db_session, event_bus)
gradual_transitioner = GradualTransitioner(ha)
seasonal_advisor = SeasonalAdvisor(ha)
calendar_integration = CalendarIntegration(ha)

# Phase 4 Batch 5: Health Dashboard Aggregator
health_aggregator = HealthAggregator(ha, get_db_session, event_bus, engines={
    "sleep_detector": sleep_detector,
    "comfort_calculator": comfort_calculator,
    "ventilation_monitor": ventilation_monitor,
    "screen_time_monitor": screen_time_monitor,
    "mood_estimator": mood_estimator,
    "weather_alert_manager": weather_alert_manager,
    "energy_optimizer": energy_optimizer,
})

# Phase 5: Security & Special Modes engines
from engines.fire_water import FireResponseManager, WaterLeakManager
from engines.camera_security import SecurityCameraManager
from engines.access_control import AccessControlManager, GeoFenceManager
from engines.special_modes import PartyMode, CinemaMode, HomeOfficeMode, NightLockdown, EmergencyProtocol

fire_response_manager = FireResponseManager(ha, get_db_session, event_bus)
water_leak_manager = WaterLeakManager(ha, get_db_session, event_bus)
camera_manager = SecurityCameraManager(ha, get_db_session, event_bus)
access_control_manager = AccessControlManager(ha, get_db_session, event_bus)
geofence_manager = GeoFenceManager(ha, get_db_session, event_bus)
party_mode = PartyMode(ha, get_db_session, event_bus)
cinema_mode = CinemaMode(ha, get_db_session, event_bus)
home_office_mode = HomeOfficeMode(ha, get_db_session, event_bus)
night_lockdown = NightLockdown(ha, get_db_session, event_bus)
emergency_protocol = EmergencyProtocol(ha, get_db_session, event_bus)

# Phase 5: Cover Control
from engines.cover_control import CoverControlManager
cover_control_manager = CoverControlManager(ha, get_db_session, event_bus)

dependencies = {
    "ha": ha,
    "engine": engine,
    "domain_manager": domain_manager,
    "event_bus": legacy_event_bus,
    "new_event_bus": event_bus,
    "state_logger": state_logger,
    "pattern_scheduler": pattern_scheduler,
    "automation_scheduler": automation_scheduler,
    "domain_plugins": DOMAIN_PLUGINS,
    "start_time": 0,
    "log_state_change": log_state_change,
    "energy_optimizer": energy_optimizer,
    "standby_monitor": standby_monitor,
    "energy_forecaster": energy_forecaster,
    "sleep_detector": sleep_detector,
    "wakeup_manager": wakeup_manager,
    "routine_engine": routine_engine,
    "visit_manager": visit_manager,
    "vacation_detector": vacation_detector,
    "comfort_calculator": comfort_calculator,
    "ventilation_monitor": ventilation_monitor,
    "circadian_manager": circadian_manager,
    "weather_alert_manager": weather_alert_manager,
    "mood_estimator": mood_estimator,
    "screen_time_monitor": screen_time_monitor,
    "habit_drift_detector": habit_drift_detector,
    "adaptive_timing_manager": adaptive_timing_manager,
    "gradual_transitioner": gradual_transitioner,
    "seasonal_advisor": seasonal_advisor,
    "calendar_integration": calendar_integration,
    "health_aggregator": health_aggregator,
    # Phase 5
    "fire_response_manager": fire_response_manager,
    "water_leak_manager": water_leak_manager,
    "camera_manager": camera_manager,
    "access_control_manager": access_control_manager,
    "geofence_manager": geofence_manager,
    "party_mode": party_mode,
    "cinema_mode": cinema_mode,
    "home_office_mode": home_office_mode,
    "night_lockdown": night_lockdown,
    "emergency_protocol": emergency_protocol,
    "cover_control_manager": cover_control_manager,
}

from routes import register_blueprints
register_blueprints(app, dependencies)


# ==============================================================================
# Graceful Shutdown
# ==============================================================================

def graceful_shutdown(signum=None, frame=None):
    """Clean shutdown handler."""
    logger.info("Shutdown signal received - cleaning up...")

    for name, sched in [("pattern_scheduler", pattern_scheduler), ("automation_scheduler", automation_scheduler)]:
        try:
            sched.stop()
            logger.info(f"{name} stopped")
        except Exception as e:
            logger.error(f"Error stopping {name}: {e}")

    task_scheduler.stop()

    # Stop Phase 4 + Phase 5 engines
    for eng_name, eng in [("energy_optimizer", energy_optimizer),
                          ("standby_monitor", standby_monitor),
                          ("energy_forecaster", energy_forecaster),
                          ("sleep_detector", sleep_detector),
                          ("wakeup_manager", wakeup_manager),
                          ("routine_engine", routine_engine),
                          ("visit_manager", visit_manager),
                          ("vacation_detector", vacation_detector),
                          ("comfort_calculator", comfort_calculator),
                          ("ventilation_monitor", ventilation_monitor),
                          ("circadian_manager", circadian_manager),
                          ("weather_alert_manager", weather_alert_manager),
                          ("mood_estimator", mood_estimator),
                          ("screen_time_monitor", screen_time_monitor),
                          ("habit_drift_detector", habit_drift_detector),
                          ("adaptive_timing_manager", adaptive_timing_manager),
                          ("gradual_transitioner", gradual_transitioner),
                          ("health_aggregator", health_aggregator),
                          # Phase 5
                          ("fire_response_manager", fire_response_manager),
                          ("water_leak_manager", water_leak_manager),
                          ("camera_manager", camera_manager),
                          ("access_control_manager", access_control_manager),
                          ("geofence_manager", geofence_manager),
                          ("party_mode", party_mode),
                          ("cinema_mode", cinema_mode),
                          ("home_office_mode", home_office_mode),
                          ("night_lockdown", night_lockdown),
                          ("emergency_protocol", emergency_protocol),
                          ("cover_control_manager", cover_control_manager)]:
        try:
            eng.stop()
        except Exception:
            pass

    if domain_manager:
        try:
            domain_manager.stop_all()
        except Exception:
            pass

    try:
        ha.disconnect()
    except Exception:
        pass

    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:
        pass

    try:
        engine.dispose()
    except Exception:
        pass

    logger.info("MindHome shutdown complete")
    sys.exit(0)


# ==============================================================================
# Startup
# ==============================================================================

def start_app():
    """Initialize and start MindHome."""
    global _start_time
    _start_time = time.time()
    dependencies["start_time"] = _start_time

    vi = version_info()
    logger.info("=" * 60)
    logger.info("MindHome - Smart Home AI")
    logger.info(f"Version: {vi['full']}")
    logger.info(f"Codename: {vi['codename']}")
    logger.info(f"Language: {get_language()}")
    logger.info(f"Log Level: {log_level}")
    logger.info(f"Ingress Path: {INGRESS_PATH}")
    logger.info("=" * 60)

    # Startup self-test
    logger.info("Running startup self-test...")
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
        logger.info("  ✅ Database OK")
    except Exception as e:
        logger.error(f"  ❌ Database FAILED: {e}")

    # Shutdown handlers
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    # Defaults
    if not get_setting("data_retention_days"):
        set_setting("data_retention_days", "90")

    # Connect to Home Assistant
    ha.connect()
    init_timezone(ha)

    # Subscribe to state changes
    ha.subscribe_events(on_state_changed, "state_changed")

    # Start domain plugins
    if domain_manager:
        try:
            with get_db_session() as session:
                enabled_count = session.query(Domain).filter_by(is_enabled=True).count()
                if enabled_count == 0:
                    for d in session.query(Domain).all():
                        d.is_enabled = True
                    logger.info("Auto-enabled all domains (first start)")
            domain_manager.start_enabled_domains()
        except Exception as e:
            logger.warning(f"Domain manager start error: {e}")

    # Start ML engines
    pattern_scheduler.start()
    logger.info("  ✅ Pattern Engine started")

    automation_scheduler.start()
    logger.info("  ✅ Automation Engine started")

    # Register cleanup + DB maintenance tasks
    from routes.system import run_cleanup, run_db_maintenance
    task_scheduler.register("db_cleanup", run_cleanup,
                            interval_seconds=24 * 3600,  # daily
                            run_immediately=False)
    task_scheduler.register("db_maintenance", run_db_maintenance,
                            interval_seconds=7 * 24 * 3600,  # weekly
                            run_immediately=False)

    # Register Phase 4 tasks
    from engines.data_retention import run_data_retention
    task_scheduler.register("data_retention", run_data_retention, interval_seconds=3600)

    # Phase 4 Batch 1: Energy scheduler tasks
    def run_energy_check():
        """5-min check: standby detection + PV surplus management."""
        standby_monitor.check()
        energy_optimizer.check_pv_surplus()

    def run_daily_batch():
        """Daily batch: energy analysis + forecast generation."""
        energy_optimizer.daily_analysis()
        energy_forecaster.daily_forecast()

    energy_optimizer.start()
    standby_monitor.start()
    energy_forecaster.start()

    task_scheduler.register("energy_check", run_energy_check,
                            interval_seconds=5 * 60,  # 5 min
                            run_immediately=False)
    task_scheduler.register("daily_batch", run_daily_batch,
                            interval_seconds=24 * 3600,  # daily
                            run_immediately=False)

    # Phase 4 Batch 2: Sleep, Routines, Visit, Vacation scheduler tasks
    sleep_detector.start()
    wakeup_manager.start()
    routine_engine.start()
    visit_manager.start()
    vacation_detector.start()

    def run_sleep_check():
        """5-min check: sleep detection + wake-up ramp."""
        sleep_detector.check()
        wakeup_manager.check()

    def run_visit_vacation_check():
        """10-min check: visit triggers + vacation detection."""
        visit_manager.check_triggers()
        vacation_detector.check()

    def run_routine_detect():
        """Daily: detect routine sequences from patterns."""
        routine_engine.detect_routines()

    task_scheduler.register("sleep_check", run_sleep_check,
                            interval_seconds=5 * 60,  # 5 min
                            run_immediately=False)
    task_scheduler.register("visit_vacation_check", run_visit_vacation_check,
                            interval_seconds=10 * 60,  # 10 min
                            run_immediately=False)
    task_scheduler.register("routine_detect", run_routine_detect,
                            interval_seconds=24 * 3600,  # daily
                            run_immediately=False)

    # Phase 4 Batch 3: Comfort, Ventilation, Circadian, Weather scheduler tasks
    comfort_calculator.start()
    ventilation_monitor.start()
    circadian_manager.start()
    weather_alert_manager.start()

    def run_comfort_check():
        """15-min check: comfort scoring + circadian lighting."""
        comfort_calculator.calculate()
        circadian_manager.check()

    def run_ventilation_check():
        """10-min check: ventilation monitoring."""
        ventilation_monitor.check()

    def run_weather_check():
        """30-min check: weather forecast alerts."""
        weather_alert_manager.check()

    task_scheduler.register("comfort_check", run_comfort_check,
                            interval_seconds=15 * 60,  # 15 min
                            run_immediately=False)
    task_scheduler.register("ventilation_check", run_ventilation_check,
                            interval_seconds=10 * 60,  # 10 min
                            run_immediately=False)
    task_scheduler.register("weather_check", run_weather_check,
                            interval_seconds=30 * 60,  # 30 min
                            run_immediately=False)

    # Phase 4 Batch 4: KI, Kalender & UX scheduler tasks
    mood_estimator.start()
    screen_time_monitor.start()
    habit_drift_detector.start()
    adaptive_timing_manager.start()
    gradual_transitioner.start()

    def run_screen_time_check():
        """5-min check: screen time tracking + mood estimate."""
        screen_time_monitor.check()
        mood_estimator.estimate()

    def run_adaptive_check():
        """15-min check: adaptive timing learning."""
        adaptive_timing_manager.check()

    def run_weekly_drift():
        """Weekly: detect habit drifts."""
        habit_drift_detector.detect()

    task_scheduler.register("screen_time_check", run_screen_time_check,
                            interval_seconds=5 * 60,  # 5 min
                            run_immediately=False)
    task_scheduler.register("adaptive_check", run_adaptive_check,
                            interval_seconds=15 * 60,  # 15 min
                            run_immediately=False)
    task_scheduler.register("weekly_drift", run_weekly_drift,
                            interval_seconds=7 * 24 * 3600,  # weekly
                            run_immediately=False)

    # Phase 4 Batch 5: Health Dashboard scheduler
    health_aggregator.start()

    def run_health_aggregate():
        """Hourly: aggregate health dashboard data + store metrics."""
        health_aggregator.aggregate()

    task_scheduler.register("health_aggregate", run_health_aggregate,
                            interval_seconds=60 * 60,  # 1 hour
                            run_immediately=False)

    # Phase 5: Security & Special Modes
    fire_response_manager.start()
    water_leak_manager.start()
    camera_manager.start()
    access_control_manager.start()
    geofence_manager.start()
    party_mode.start()
    cinema_mode.start()
    home_office_mode.start()
    night_lockdown.start()
    emergency_protocol.start()

    def run_geofence_check():
        """60s check: geo-fence zone enter/leave detection."""
        geofence_manager.check()

    def run_access_autolock():
        """60s check: auto-lock expired unlocked doors."""
        access_control_manager.check_auto_lock()

    def run_special_mode_timeout():
        """5-min check: auto-deactivate expired special modes."""
        for mode in (party_mode, cinema_mode, home_office_mode, night_lockdown):
            mode.check_timeout()

    def run_camera_cleanup():
        """Daily: remove old snapshots (retention policy)."""
        camera_manager.cleanup_old_snapshots()

    task_scheduler.register("geofence_check", run_geofence_check,
                            interval_seconds=60,
                            run_immediately=False)
    task_scheduler.register("access_autolock", run_access_autolock,
                            interval_seconds=60,
                            run_immediately=False)
    task_scheduler.register("special_mode_timeout", run_special_mode_timeout,
                            interval_seconds=5 * 60,
                            run_immediately=False)
    task_scheduler.register("camera_cleanup", run_camera_cleanup,
                            interval_seconds=24 * 3600,
                            run_immediately=False)

    # Phase 5: Cover Control
    cover_control_manager.start()

    def run_cover_check():
        """5-min check: cover automation rules (sun, weather, comfort)."""
        cover_control_manager.check()

    def run_cover_schedules():
        """1-min check: time-based cover schedules."""
        cover_control_manager.check_schedules()

    def run_cover_simulation():
        """15-min check: presence simulation for covers."""
        cover_control_manager.check_simulation()

    task_scheduler.register("cover_check", run_cover_check,
                            interval_seconds=5 * 60,
                            run_immediately=False)
    task_scheduler.register("cover_schedules", run_cover_schedules,
                            interval_seconds=60,
                            run_immediately=False)
    task_scheduler.register("cover_simulation", run_cover_simulation,
                            interval_seconds=15 * 60,
                            run_immediately=False)

    # Start task scheduler
    task_scheduler.start()
    logger.info("  ✅ Task Scheduler started (cleanup:24h, maintenance:7d, energy:5m, sleep:5m, visit:10m, comfort:15m, ventilation:10m, weather:30m, screen:5m, adaptive:15m, drift:7d, health:1h)")

    logger.info(f"MindHome {vi['full']} started successfully!")

    # Start Flask
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    start_app()
