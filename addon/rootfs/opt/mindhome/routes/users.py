# MindHome - routes/users.py | see version.py for version info
"""
MindHome API Routes - Users
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

logger = logging.getLogger("mindhome.routes.users")

users_bp = Blueprint("users", __name__)

# Module-level dependencies (set by init function)
_deps = {}


def init_users(dependencies):
    """Initialize users routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _ha():
    ha = _deps.get("ha")
    if ha is None:
        raise RuntimeError("HAConnection not initialized")
    return ha


def _engine():
    return _deps.get("engine")


def _domain_manager():
    return _deps.get("domain_manager")



@users_bp.route("/api/users", methods=["GET"])
def api_get_users():
    """Get all users."""
    with get_db_session() as session:
        users = session.query(User).filter_by(is_active=True).all()
        return jsonify([{
            "id": u.id,
            "name": u.name,
            "role": u.role.value,
            "ha_person_entity": u.ha_person_entity,
            "language": u.language,
            "created_at": u.created_at.isoformat()
        } for u in users])



@users_bp.route("/api/users", methods=["POST"])
def api_create_user():
    """Create a new user."""
    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"error": "Name ist erforderlich"}), 400
    with get_db_session() as session:
        try:
            role = UserRole(data.get("role", "user"))
        except ValueError:
            return jsonify({"error": f"Ungueltiger Rolle: {data.get('role')}"}), 400
        user = User(
            name=data["name"],
            role=role,
            ha_person_entity=data.get("ha_person_entity"),
            language=data.get("language", get_language())
        )
        session.add(user)
        session.commit()

        for ntype in NotificationType:
            ns = NotificationSetting(
                user_id=user.id,
                notification_type=ntype,
                is_enabled=True,
                quiet_hours_start="22:00",
                quiet_hours_end="07:00",
                quiet_hours_allow_critical=True
            )
            session.add(ns)
        session.commit()

        return jsonify({"id": user.id, "name": user.name}), 201



@users_bp.route("/api/users/<int:user_id>", methods=["PUT"])
def api_update_user(user_id):
    """Update a user."""
    data = request.json or {}
    with get_db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        if "name" in data:
            user.name = data["name"]
        if "role" in data:
            try:
                user.role = UserRole(data["role"])
            except ValueError:
                return jsonify({"error": f"Ungueltiger Rolle: {data['role']}"}), 400
        if "ha_person_entity" in data:
            user.ha_person_entity = data["ha_person_entity"]
        if "language" in data:
            user.language = data["language"]

        session.commit()
        return jsonify({"id": user.id, "name": user.name})



@users_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    """Delete a user (soft delete)."""
    with get_db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        user.is_active = False
        session.commit()
        return jsonify({"success": True})

