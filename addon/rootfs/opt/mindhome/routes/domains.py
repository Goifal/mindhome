# MindHome - routes/domains.py | see version.py for version info
"""
MindHome API Routes - Domains
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

logger = logging.getLogger("mindhome.routes.domains")

domains_bp = Blueprint("domains", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_domains(dependencies):
    """Initialize domains routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    return _deps.get("ha")


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@domains_bp.route("/api/domains", methods=["GET"])
def api_get_domains():
    """Get all available domains."""
    session = get_db()
    try:
        domains = session.query(Domain).all()
        lang = get_language()
        return jsonify([{
            "id": d.id,
            "name": d.name,
            "display_name": d.display_name_de if lang == "de" else d.display_name_en,
            "icon": d.icon,
            "is_enabled": d.is_enabled,
            "is_custom": d.is_custom if hasattr(d, 'is_custom') else False,
            "description": d.description_de if lang == "de" else d.description_en
        } for d in domains])
    finally:
        session.close()



@domains_bp.route("/api/domains", methods=["POST"])
def api_create_domain():
    """Create a custom domain."""
    data = request.json
    session = get_db()
    try:
        name = data.get("name", "").strip().lower().replace(" ", "_")
        if not name:
            return jsonify({"error": "Name is required"}), 400

        existing = session.query(Domain).filter_by(name=name).first()
        if existing:
            return jsonify({"error": "Domain already exists"}), 400

        domain = Domain(
            name=name,
            display_name_de=data.get("display_name_de", data.get("name", name)),
            display_name_en=data.get("display_name_en", data.get("name", name)),
            icon=data.get("icon", "mdi:puzzle"),
            is_enabled=True,
            is_custom=True,
            description_de=data.get("description_de", ""),
            description_en=data.get("description_en", "")
        )
        session.add(domain)
        session.commit()
        return jsonify({"id": domain.id, "name": domain.name}), 201
    finally:
        session.close()



@domains_bp.route("/api/domains/<int:domain_id>", methods=["PUT"])
def api_update_domain(domain_id):
    """Update a domain. System domains: only icon editable. Custom domains: all fields."""
    data = request.json
    session = get_db()
    try:
        domain = session.get(Domain, domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404

        is_custom = getattr(domain, 'is_custom', False)

        # Icon is editable for ALL domains
        if "icon" in data:
            domain.icon = data["icon"]

        # Other fields only for custom domains
        if is_custom:
            if "display_name_de" in data:
                domain.display_name_de = data["display_name_de"]
            if "display_name_en" in data:
                domain.display_name_en = data["display_name_en"]
            if "name_de" in data:
                domain.display_name_de = data["name_de"]
                if not domain.display_name_en:
                    domain.display_name_en = data["name_de"]
            if "description_de" in data:
                domain.description_de = data["description_de"]
            if "description_en" in data:
                domain.description_en = data["description_en"]
            if "description" in data:
                domain.description_de = data["description"]
                if not domain.description_en:
                    domain.description_en = data["description"]
            if "keywords" in data:
                domain.keywords = data["keywords"]

        session.commit()
        return jsonify({"id": domain.id, "name": domain.name})
    finally:
        session.close()



@domains_bp.route("/api/domains/<int:domain_id>", methods=["DELETE"])
def api_delete_domain(domain_id):
    """Delete a custom domain."""
    session = get_db()
    try:
        domain = session.get(Domain, domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        if not getattr(domain, 'is_custom', False):
            return jsonify({"error": "Cannot delete system domains"}), 400

        # Move devices to unassigned
        devices = session.query(Device).filter_by(domain_id=domain_id).all()
        default_domain = session.query(Domain).filter_by(name="switch").first()
        for d in devices:
            d.domain_id = default_domain.id if default_domain else 1

        # Remove room domain states
        session.query(RoomDomainState).filter_by(domain_id=domain_id).delete()

        session.delete(domain)
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()



@domains_bp.route("/api/domains/<int:domain_id>/toggle", methods=["POST"])
def api_toggle_domain(domain_id):
    """Enable or disable a domain."""
    session = get_db()
    try:
        domain = session.get(Domain, domain_id)
        if not domain:
            return jsonify({"error": "Domain not found"}), 404
        domain.is_enabled = not domain.is_enabled
        session.commit()

        if domain.is_enabled:
            if _domain_manager(): _domain_manager().start_domain(domain.name)
        else:
            if _domain_manager(): _domain_manager().stop_domain(domain.name)

        return jsonify({"id": domain.id, "is_enabled": domain.is_enabled})
    finally:
        session.close()



@domains_bp.route("/api/domains/status", methods=["GET"])
def api_domain_status():
    """Get live status from all active domain plugins."""
    return jsonify(_domain_manager().get_all_status())



@domains_bp.route("/api/domains/capabilities", methods=["GET"])
def api_domain_capabilities():
    """Get per-domain capabilities for frontend display."""
    return jsonify(_deps.get("domain_plugins", {}))



@domains_bp.route("/api/domains/<domain_name>/features", methods=["GET"])
def api_domain_features(domain_name):
    """Get trackable features for a domain (for privacy settings)."""
    features = _domain_manager().get_trackable_features(domain_name)
    return jsonify({"domain": domain_name, "features": features})



@domains_bp.route("/api/plugin-settings", methods=["GET"])
def api_get_plugin_settings():
    """Get plugin settings: DEFAULT_SETTINGS merged with DB overrides."""
    session = get_db()
    try:
        plugin_name = request.args.get("plugin")

        # Start with DEFAULT_SETTINGS from all domain plugins
        result = {}
        dm = _domain_manager()
        if dm:
            plugins = dm._all_plugins
            for name, plugin in plugins.items():
                if plugin_name and name != plugin_name:
                    continue
                if hasattr(plugin, 'DEFAULT_SETTINGS') and plugin.DEFAULT_SETTINGS:
                    result[name] = dict(plugin.DEFAULT_SETTINGS)

        # Override with DB values
        query = session.query(PluginSetting)
        if plugin_name:
            query = query.filter_by(plugin_name=plugin_name)
        for s in query.all():
            if s.plugin_name not in result:
                result[s.plugin_name] = {}
            result[s.plugin_name][s.setting_key] = s.setting_value

        return jsonify(result)
    finally:
        session.close()


@domains_bp.route("/api/plugin-settings/<plugin_name>", methods=["PUT"])
def api_update_plugin_settings(plugin_name):
    data = request.json or {}
    session = get_db()
    try:
        for key, value in data.items():
            existing = session.query(PluginSetting).filter_by(plugin_name=plugin_name, setting_key=key).first()
            str_val = json.dumps(value) if not isinstance(value, str) else value
            if existing: existing.setting_value = str_val
            else: session.add(PluginSetting(plugin_name=plugin_name, setting_key=key, setting_value=str_val))
        session.commit()
        return jsonify({"success": True})
    finally:
        session.close()
