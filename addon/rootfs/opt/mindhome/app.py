# MindHome - app.py | see version.py for version info
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

from ml.pattern_engine import EventBus as LegacyEventBus, StateLogger, PatternScheduler, PatternDetector
from ml.automation_engine import (
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
CORS(app)

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
        "controls": ["toggle", "brightness", "color_temp"],
        "pattern_features": ["time_of_day", "brightness_level", "duration"],
        "icon": "mdi:lightbulb",
    },
    "climate": {
        "ha_domain": "climate",
        "attributes": ["current_temperature", "temperature", "hvac_action", "humidity"],
        "controls": ["set_temperature", "set_hvac_mode"],
        "pattern_features": ["target_temp", "schedule", "comfort_profile"],
        "icon": "mdi:thermostat",
    },
    "cover": {
        "ha_domain": "cover",
        "attributes": ["current_position", "current_tilt_position"],
        "controls": ["open", "close", "set_position"],
        "pattern_features": ["position", "time_of_day", "sun_based"],
        "icon": "mdi:window-shutter",
    },
    "switch": {
        "ha_domain": "switch",
        "attributes": ["current_power_w", "today_energy_kwh"],
        "controls": ["toggle"],
        "pattern_features": ["time_of_day", "duration"],
        "icon": "mdi:toggle-switch",
    },
    "sensor": {
        "ha_domain": "sensor",
        "attributes": ["unit_of_measurement", "device_class"],
        "controls": [],
        "pattern_features": ["threshold", "trend"],
        "icon": "mdi:eye",
    },
    "binary_sensor": {
        "ha_domain": "binary_sensor",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": ["trigger", "duration", "frequency"],
        "icon": "mdi:checkbox-blank-circle-outline",
    },
    "media_player": {
        "ha_domain": "media_player",
        "attributes": ["media_title", "volume_level", "source"],
        "controls": ["toggle", "volume", "source"],
        "pattern_features": ["time_of_day", "source_preference"],
        "icon": "mdi:speaker",
    },
    "lock": {
        "ha_domain": "lock",
        "attributes": [],
        "controls": ["lock", "unlock"],
        "pattern_features": ["time_of_day", "presence"],
        "icon": "mdi:lock",
    },
    "vacuum": {
        "ha_domain": "vacuum",
        "attributes": ["battery_level", "status"],
        "controls": ["start", "stop", "return_to_base"],
        "pattern_features": ["schedule", "presence"],
        "icon": "mdi:robot-vacuum",
    },
    "fan": {
        "ha_domain": "fan",
        "attributes": ["percentage", "preset_mode"],
        "controls": ["toggle", "set_percentage"],
        "pattern_features": ["temperature_based", "time_of_day"],
        "icon": "mdi:fan",
    },
    "motion": {
        "ha_domain": "binary_sensor",
        "device_class": "motion",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": ["time_of_day", "frequency", "duration", "room_correlation"],
        "icon": "mdi:motion-sensor",
    },
    "presence": {
        "ha_domain": "person",
        "attributes": ["source", "gps_accuracy"],
        "controls": [],
        "pattern_features": ["arrival_time", "departure_time", "routine"],
        "icon": "mdi:account-multiple",
    },
    "door_window": {
        "ha_domain": "binary_sensor",
        "device_class": "door",
        "attributes": ["device_class"],
        "controls": [],
        "pattern_features": ["open_duration", "frequency", "time_of_day"],
        "icon": "mdi:door",
    },
    "energy": {
        "ha_domain": "sensor",
        "device_class": "energy",
        "attributes": ["unit_of_measurement", "state_class"],
        "controls": [],
        "pattern_features": ["daily_usage", "peak_hours", "baseline"],
        "icon": "mdi:flash",
    },
    "weather": {
        "ha_domain": "weather",
        "attributes": ["temperature", "humidity", "forecast"],
        "controls": [],
        "pattern_features": ["condition_correlation"],
        "icon": "mdi:weather-cloudy",
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

def on_state_changed(event):
    """Handle real-time state change events from HA."""
    if domain_manager:
        domain_manager.on_state_change(event)

    event_data = event.get("data", {}) if event else {}
    entity_id = event_data.get("entity_id", "")
    new_state = event_data.get("new_state") or {}
    old_state = event_data.get("old_state") or {}

    # Log to state_history via pattern engine
    try:
        state_logger.log_state_change(event_data)
    except Exception as e:
        logger.debug(f"Pattern state log error: {e}")

    # Publish to legacy event bus
    legacy_event_bus.publish("state_changed", event_data)

    # Publish to new event bus
    event_bus.publish("state.changed", event_data, source="ha")

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
    return jsonify({"error": "Internal server error", "message": str(error)[:200]}), 500


@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return redirect("/")


@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Unhandled exception: {type(error).__name__}: {error}")
    if request.path.startswith("/api/"):
        return jsonify({"error": type(error).__name__, "message": str(error)[:200]}), 500
    return redirect("/")


# ==============================================================================
# Register Blueprints
# ==============================================================================

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

    # Start task scheduler
    task_scheduler.start()
    logger.info("  ✅ Task Scheduler started")

    logger.info(f"MindHome {vi['full']} started successfully!")

    # Start Flask
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    start_app()
