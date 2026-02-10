# MindHome Models v0.6.1 (2026-02-10) - models.py
"""
MindHome - Database Models
All persistent data structures for MindHome.
Phase 1 Final - with migration system
"""

from datetime import datetime, timezone


def _utcnow():
    """Timezone-aware UTC now for SQLAlchemy defaults."""
    return datetime.now(timezone.utc)
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Enum, JSON, inspect, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import enum
import os
import logging

logger = logging.getLogger("mindhome.models")

Base = declarative_base()


# ==============================================================================
# Enums
# ==============================================================================

class UserRole(enum.Enum):
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class LearningPhase(enum.Enum):
    OBSERVING = "observing"
    SUGGESTING = "suggesting"
    AUTONOMOUS = "autonomous"


class NotificationType(enum.Enum):
    CRITICAL = "critical"
    SUGGESTION = "suggestion"
    ANOMALY = "anomaly"
    INFO = "info"


class NotificationPriority(enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ==============================================================================
# User & Permissions
# ==============================================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    ha_person_entity = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True)
    pin_hash = Column(String(255), nullable=True)
    language = Column(String(5), default="de")
    # Phase 3
    profile_type = Column(String(20), default="adult")  # "adult", "child", "guest"
    tracking_enabled = Column(Boolean, default=True)
    history_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")
    notifications_settings = relationship("NotificationSetting", back_populates="user", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    preference_key = Column(String(100), nullable=False)
    preference_value = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="preferences")
    room = relationship("Room")


# ==============================================================================
# Rooms
# ==============================================================================

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    ha_area_id = Column(String(255), nullable=True)
    icon = Column(String(50), default="mdi:door")
    privacy_mode = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    devices = relationship("Device", back_populates="room", cascade="all, delete-orphan")
    domain_states = relationship("RoomDomainState", back_populates="room", cascade="all, delete-orphan")


# ==============================================================================
# Domains & Devices
# ==============================================================================

class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    display_name_de = Column(String(100), nullable=False)
    display_name_en = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=False)
    is_enabled = Column(Boolean, default=False)
    is_custom = Column(Boolean, default=False)  # Fix 7: Custom domains
    description_de = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class RoomDomainState(Base):
    __tablename__ = "room_domain_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    learning_phase = Column(Enum(LearningPhase), default=LearningPhase.OBSERVING)
    phase_started_at = Column(DateTime, default=_utcnow)
    confidence_score = Column(Float, default=0.0)
    is_paused = Column(Boolean, default=False)

    room = relationship("Room", back_populates="domain_states")
    domain = relationship("Domain")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ha_entity_id = Column(String(255), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    is_tracked = Column(Boolean, default=True)
    is_controllable = Column(Boolean, default=True)
    device_meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room", back_populates="devices")
    domain = relationship("Domain")


# ==============================================================================
# Patterns & Predictions
# ==============================================================================

class LearnedPattern(Base):
    __tablename__ = "learned_patterns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    pattern_type = Column(String(50), nullable=False)  # "time_based", "event_chain", "correlation"
    pattern_data = Column(JSON, nullable=False)  # The pattern definition
    confidence = Column(Float, default=0.0)
    times_confirmed = Column(Integer, default=0)
    times_rejected = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    description_template = Column(Text, nullable=True)

    # Phase 2a extensions
    description_de = Column(Text, nullable=True)  # Human-readable German
    description_en = Column(Text, nullable=True)  # Human-readable English
    trigger_conditions = Column(JSON, nullable=True)  # When does this pattern fire
    action_definition = Column(JSON, nullable=True)  # What should happen
    last_matched_at = Column(DateTime, nullable=True)
    match_count = Column(Integer, default=0)
    status = Column(String(30), default="observed")  # observed, suggested, active, disabled, rejected

    # Block B extensions
    rejection_reason = Column(String(50), nullable=True)  # "coincidence", "unwanted", "wrong"
    rejected_at = Column(DateTime, nullable=True)
    category = Column(String(30), nullable=True)  # "energy", "comfort", "security"
    season = Column(String(20), nullable=True)  # "spring", "summer", "autumn", "winter", null=all
    test_mode = Column(Boolean, default=False)  # simulation mode
    test_results = Column(JSON, nullable=True)  # simulated triggers log
    depends_on_pattern_id = Column(Integer, ForeignKey("learned_patterns.id"), nullable=True)
    schedule = Column(JSON, nullable=True)  # {"weekdays": [0,1,2,3,4], "time_after": "08:00", "time_before": "22:00"}
    delay_seconds = Column(Integer, default=0)
    conditions = Column(JSON, nullable=True)  # multi-factor: {"presence": "home", "weather": "cloudy"}

    # Phase 3
    context_tags = Column(JSON, nullable=True)  # {"persons": [...], "day_type": "weekday", ...}

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    domain = relationship("Domain")
    room = relationship("Room")
    user = relationship("User")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_id = Column(Integer, ForeignKey("learned_patterns.id"), nullable=False)
    predicted_action = Column(JSON, nullable=False)
    predicted_for = Column(DateTime, nullable=False)
    confidence = Column(Float, nullable=False)
    was_executed = Column(Boolean, default=False)
    was_correct = Column(Boolean, nullable=True)
    execution_result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # Phase 2b extensions
    status = Column(String(30), default="pending")  # pending, confirmed, rejected, ignored, executed, undone
    user_response = Column(String(30), nullable=True)  # confirmed, rejected, ignored
    responded_at = Column(DateTime, nullable=True)
    notification_sent = Column(Boolean, default=False)
    previous_state = Column(JSON, nullable=True)  # For undo: state before automation
    executed_at = Column(DateTime, nullable=True)
    undone_at = Column(DateTime, nullable=True)
    description_de = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)

    pattern = relationship("LearnedPattern")


# ==============================================================================
# Action Log
# ==============================================================================

class ActionLog(Base):
    __tablename__ = "action_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_type = Column(String(50), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action_data = Column(JSON, nullable=False)
    reason = Column(Text, nullable=True)
    was_undone = Column(Boolean, default=False)
    previous_state = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    domain = relationship("Domain")
    room = relationship("Room")
    device = relationship("Device")
    user = relationship("User")


# ==============================================================================
# Notifications
# ==============================================================================

class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type = Column(Enum(NotificationType), nullable=False)
    is_enabled = Column(Boolean, default=True)
    priority = Column(Enum(NotificationPriority), default=NotificationPriority.MEDIUM)
    quiet_hours_start = Column(String(5), nullable=True)  # "22:00"
    quiet_hours_end = Column(String(5), nullable=True)  # "07:00"
    quiet_hours_allow_critical = Column(Boolean, default=True)
    push_channel = Column(String(100), nullable=True)  # HA notify service name
    escalation_enabled = Column(Boolean, default=False)
    escalation_minutes = Column(Integer, default=30)  # escalate after X min
    geofencing_only_away = Column(Boolean, default=False)  # only when nobody home
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="notifications_settings")


class NotificationChannel(Base):
    """Available notification channels (discovered from HA notify services)."""
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_name = Column(String(200), nullable=False, unique=True)  # e.g. "notify.mobile_app_iphone"
    display_name = Column(String(200), nullable=False)
    channel_type = Column(String(50), nullable=False)  # "push", "persistent", "telegram", "email"
    is_enabled = Column(Boolean, default=True)
    config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class DeviceMute(Base):
    """Muted devices - no notifications for these."""
    __tablename__ = "device_mutes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    muted_until = Column(DateTime, nullable=True)  # null = permanent
    reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    device = relationship("Device")
    user = relationship("User")


class PatternExclusion(Base):
    """Exclusion rules: entities/rooms that should never be linked in patterns."""
    __tablename__ = "pattern_exclusions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exclusion_type = Column(String(30), nullable=False)  # "device_pair", "room_pair"
    entity_a = Column(String(255), nullable=False)  # entity_id or room_id
    entity_b = Column(String(255), nullable=False)
    reason = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    creator = relationship("User")


class ManualRule(Base):
    """User-defined rules (manual patterns)."""
    __tablename__ = "manual_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    trigger_entity = Column(String(255), nullable=False)  # "light.living_room"
    trigger_state = Column(String(100), nullable=False)  # "on", "off", ">25"
    action_entity = Column(String(255), nullable=False)  # "light.hallway"
    action_service = Column(String(100), nullable=False)  # "turn_on", "turn_off"
    action_data = Column(JSON, nullable=True)  # additional service data
    conditions = Column(JSON, nullable=True)  # {"time_after": "22:00", "weekdays": [0,1,2,3,4]}
    delay_seconds = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    execution_count = Column(Integer, default=0)
    last_executed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    creator = relationship("User")


class AnomalySetting(Base):
    """Per-room/domain anomaly detection settings."""
    __tablename__ = "anomaly_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    sensitivity = Column(String(20), default="medium")  # "low", "medium", "high", "off"
    stuck_detection = Column(Boolean, default=True)
    time_anomaly = Column(Boolean, default=True)
    frequency_anomaly = Column(Boolean, default=True)
    whitelisted_hours = Column(JSON, nullable=True)  # [3, 4] = 3am-4am normal
    auto_action = Column(JSON, nullable=True)  # {"type": "notify"} or {"type": "service", "service": "..."}
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room")
    domain = relationship("Domain")
    device = relationship("Device")


# ==============================================================================
# #44 Device Groups
# ==============================================================================

class DeviceGroup(Base):
    __tablename__ = "device_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    device_ids = Column(Text, default="[]")  # JSON array of device IDs
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room")


# ==============================================================================
# #60 Audit Trail
# ==============================================================================

class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String(100), nullable=False)
    target = Column(String(200), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


# ==============================================================================
# Phase 3: Day Phases / Sun Tracking
# ==============================================================================

class DayPhase(Base):
    """User-definable day phases (e.g. Morning, Day, Dusk, Night)."""
    __tablename__ = "day_phases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_de = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    icon = Column(String(50), default="mdi:weather-sunset")
    color = Column(String(20), default="#FFA500")
    sort_order = Column(Integer, default=0)
    start_type = Column(String(20), default="time")  # "time" or "sun_event"
    start_time = Column(String(5), nullable=True)  # "06:00"
    sun_event = Column(String(30), nullable=True)  # "sunrise", "sunset", "dawn", "dusk"
    sun_offset_minutes = Column(Integer, default=0)  # +/- minutes from sun event
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class RoomOrientation(Base):
    """Optional compass orientation per room (for sun-based automations)."""
    __tablename__ = "room_orientations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, unique=True)
    orientation = Column(String(5), nullable=False)  # "N", "NE", "E", "SE", "S", "SW", "W", "NW"
    offset_minutes = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room")


# ==============================================================================
# Phase 3: Person Devices & Guest Management
# ==============================================================================

class PersonDevice(Base):
    """Device assignment to persons (primary phone, secondary tablet, etc.)."""
    __tablename__ = "person_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    entity_id = Column(String(255), nullable=False)
    device_type = Column(String(20), default="primary")  # "primary", "secondary", "stationary"
    timeout_minutes = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")


class GuestDevice(Base):
    """Tracked guest devices from guest WLAN."""
    __tablename__ = "guest_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mac_address = Column(String(20), nullable=True)
    entity_id = Column(String(255), nullable=True)
    name = Column(String(100), nullable=True)
    first_seen = Column(DateTime, default=_utcnow)
    last_seen = Column(DateTime, default=_utcnow)
    visit_count = Column(Integer, default=1)
    auto_delete_days = Column(Integer, default=30)
    created_at = Column(DateTime, default=_utcnow)


# ==============================================================================
# Phase 3: Presence Modes
# ==============================================================================

class PresenceMode(Base):
    """Configurable presence modes (home, away, vacation, etc.)."""
    __tablename__ = "presence_modes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_de = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    icon = Column(String(50), default="mdi:home")
    color = Column(String(20), default="#4CAF50")
    priority = Column(Integer, default=0)  # higher = takes precedence
    buffer_minutes = Column(Integer, default=5)  # delay before activating
    actions = Column(JSON, nullable=True)  # [{"entity_id": "...", "service": "..."}]
    trigger_type = Column(String(30), default="manual")  # "manual", "auto", "calendar"
    auto_config = Column(JSON, nullable=True)  # auto-trigger config
    notify_on_enter = Column(Boolean, default=False)
    notify_on_leave = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)  # built-in modes
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class PresenceLog(Base):
    """Log of presence mode changes."""
    __tablename__ = "presence_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode_id = Column(Integer, ForeignKey("presence_modes.id"), nullable=True)
    mode_name = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    trigger = Column(String(50), default="auto")  # "auto", "manual", "calendar", "plugin"
    created_at = Column(DateTime, default=_utcnow)


# ==============================================================================
# Phase 3: Multi-Sensor Fusion
# ==============================================================================

class SensorGroup(Base):
    """Groups of sensors for fusion (e.g. all temp sensors in a room)."""
    __tablename__ = "sensor_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    entity_ids = Column(JSON, default=list)  # ["sensor.temp_1", "sensor.temp_2"]
    fusion_method = Column(String(20), default="average")  # "average", "median", "min", "max", "newest"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room")


class SensorThreshold(Base):
    """Significance thresholds for sensor changes (spam reduction)."""
    __tablename__ = "sensor_thresholds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(255), nullable=True)  # null = global default
    min_change_percent = Column(Float, default=5.0)  # minimum % change to track
    min_change_absolute = Column(Float, nullable=True)  # or absolute value
    min_interval_seconds = Column(Integer, default=60)  # minimum time between events
    created_at = Column(DateTime, default=_utcnow)


# ==============================================================================
# Phase 3: Energy Dashboard
# ==============================================================================

class EnergyConfig(Base):
    """Energy pricing and configuration."""
    __tablename__ = "energy_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    price_per_kwh = Column(Float, default=0.25)
    currency = Column(String(5), default="EUR")
    solar_enabled = Column(Boolean, default=False)
    solar_entity = Column(String(255), nullable=True)
    grid_import_entity = Column(String(255), nullable=True)
    grid_export_entity = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class EnergyReading(Base):
    """Periodic energy readings per device/room."""
    __tablename__ = "energy_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(255), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    power_w = Column(Float, nullable=True)
    energy_kwh = Column(Float, nullable=True)
    reading_type = Column(String(20), default="power")  # "power", "energy", "solar"
    created_at = Column(DateTime, default=_utcnow, index=True)

    device = relationship("Device")
    room = relationship("Room")


class StandbyConfig(Base):
    """Standby detection config per device (with global default)."""
    __tablename__ = "standby_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)  # null = global
    entity_id = Column(String(255), nullable=True)
    threshold_watts = Column(Float, default=5.0)
    idle_minutes = Column(Integer, default=30)
    notify_dashboard = Column(Boolean, default=True)
    auto_off = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    device = relationship("Device")


# ==============================================================================
# Phase 3: Learned Scenes
# ==============================================================================

class LearnedScene(Base):
    """Auto-detected or manually created room scenes."""
    __tablename__ = "learned_scenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    name_de = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    icon = Column(String(50), default="mdi:palette")
    states = Column(JSON, nullable=False)  # [{"entity_id": "...", "state": "on", "attributes": {...}}]
    frequency = Column(Integer, default=0)  # how often detected
    min_frequency = Column(Integer, default=3)  # min times before suggesting
    status = Column(String(20), default="detected")  # "detected", "suggested", "accepted", "rejected"
    source = Column(String(20), default="auto")  # "auto", "manual", "snapshot"
    last_activated = Column(DateTime, nullable=True)
    last_detected = Column(DateTime, nullable=True)
    schedule_cron = Column(String(100), nullable=True)  # cron-like: "0 20 * * 5" = Fri 20:00
    schedule_enabled = Column(Boolean, default=False)
    action_delay_seconds = Column(Integer, default=0)  # delay between actions
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room")


# ==============================================================================
# Phase 3: Plugin Settings
# ==============================================================================

class PluginSetting(Base):
    """Per-plugin configuration (mode, thresholds, etc.)."""
    __tablename__ = "plugin_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plugin_name = Column(String(50), nullable=False)  # "light", "climate", etc.
    setting_key = Column(String(100), nullable=False)
    setting_value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ==============================================================================
# Pattern Settings (v0.6.1)
# ==============================================================================

class PatternSettings(Base):
    """Configurable thresholds and settings for pattern detection engine."""
    __tablename__ = "pattern_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    description_de = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    category = Column(String(50), default="general")  # "general", "thresholds", "anomaly", "decay"
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ==============================================================================
# Phase 3: Quiet Hours / Rest Periods
# ==============================================================================

class QuietHoursConfig(Base):
    """Quiet hours linked to day phases and shift schedules."""
    __tablename__ = "quiet_hours_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null = all users
    name = Column(String(100), default="Nachtruhe")
    start_time = Column(String(5), default="22:00")
    end_time = Column(String(5), default="07:00")
    linked_to_shift = Column(Boolean, default=False)  # adjust based on shift schedule
    linked_to_day_phase = Column(String(50), nullable=True)  # link to a day phase name
    allow_critical = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")


# ==============================================================================
# Phase 3B: Person Schedules / Time Profiles
# ==============================================================================

class PersonSchedule(Base):
    """Person time profiles: work schedules, shift plans."""
    __tablename__ = "person_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    schedule_type = Column(String(30), nullable=False)  # "weekday", "weekend", "shift", "homeoffice", "custom"
    name = Column(String(100), nullable=True)
    time_wake = Column(String(5), nullable=True)
    time_leave = Column(String(5), nullable=True)
    time_home = Column(String(5), nullable=True)
    time_sleep = Column(String(5), nullable=True)
    weekdays = Column(JSON, nullable=True)  # [0,1,2,3,4]
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    shift_data = Column(JSON, nullable=True)  # {shift_types, rotation_pattern, rotation_start, rotation_end}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User")


class ShiftTemplate(Base):
    """Shift type templates."""
    __tablename__ = "shift_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    short_code = Column(String(20), nullable=True)
    blocks = Column(JSON, nullable=False)  # [{"start": "06:00", "end": "14:00"}]
    color = Column(String(7), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class Holiday(Base):
    """Holidays and special days."""
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    date = Column(String(10), nullable=False)  # "2026-01-01" or "01-01" for recurring
    is_recurring = Column(Boolean, default=False)
    region = Column(String(50), nullable=True)  # "AT", "DE"
    source = Column(String(30), default="manual")  # "manual", "builtin", "calendar"
    calendar_entity = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


# Phase 3: Holiday / School Vacation Calendar
# ==============================================================================

class SchoolVacation(Base):
    """School vacation periods for child profiles."""
    __tablename__ = "school_vacations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_de = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    start_date = Column(String(10), nullable=False)  # "2026-02-14"
    end_date = Column(String(10), nullable=False)  # "2026-02-22"
    region = Column(String(50), default="AT-NÖ")
    source = Column(String(20), default="manual")  # "manual", "ha_calendar"
    calendar_entity = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type = Column(Enum(NotificationType), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    was_sent = Column(Boolean, default=False)
    was_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)


# ==============================================================================
# Quick Actions
# ==============================================================================

class QuickAction(Base):
    __tablename__ = "quick_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_de = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=False)
    action_data = Column(JSON, nullable=False)
    sort_order = Column(Integer, default=0)
    is_system = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


# ==============================================================================
# System Settings
# ==============================================================================

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    description_de = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ==============================================================================
# Offline Fallback Queue
# ==============================================================================

class OfflineActionQueue(Base):
    __tablename__ = "offline_action_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_data = Column(JSON, nullable=False)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)
    executed_at = Column(DateTime, nullable=True)
    was_executed = Column(Boolean, default=False)


# ==============================================================================
# Data Privacy Tracking
# ==============================================================================

class DataCollection(Base):
    __tablename__ = "data_collection"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    data_type = Column(String(100), nullable=False)
    record_count = Column(Integer, default=0)
    first_record_at = Column(DateTime, nullable=True)
    last_record_at = Column(DateTime, nullable=True)
    storage_size_bytes = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    room = relationship("Room")
    domain = relationship("Domain")


# ==============================================================================
# Phase 2a: State History (raw event data for pattern learning)
# ==============================================================================

class StateHistory(Base):
    """Every significant state change from HA, with context for learning."""
    __tablename__ = "state_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    entity_id = Column(String(255), nullable=False, index=True)
    old_state = Column(String(100), nullable=True)
    new_state = Column(String(100), nullable=False)
    old_attributes = Column(JSON, nullable=True)
    new_attributes = Column(JSON, nullable=True)

    # Context at the time of the event
    context = Column(JSON, nullable=True)
    # Structure: {
    #   "time_slot": "morning|midday|afternoon|evening|night",
    #   "weekday": 0-6 (Mon-Sun),
    #   "is_weekend": true/false,
    #   "persons_home": ["person.john", ...],
    #   "sun_elevation": 45.2,
    #   "sun_phase": "above_horizon|below_horizon",
    #   "outdoor_temp": 21.5,
    #   "hour": 14, "minute": 30
    # }

    created_at = Column(DateTime, default=_utcnow, index=True)

    device = relationship("Device")


class PatternMatchLog(Base):
    """Logs every time a pattern fires/matches to track accuracy."""
    __tablename__ = "pattern_match_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_id = Column(Integer, ForeignKey("learned_patterns.id"), nullable=False)
    matched_at = Column(DateTime, default=_utcnow)
    context = Column(JSON, nullable=True)
    trigger_event_id = Column(Integer, ForeignKey("state_history.id"), nullable=True)
    was_executed = Column(Boolean, default=False)
    was_correct = Column(Boolean, nullable=True)

    pattern = relationship("LearnedPattern")
    trigger_event = relationship("StateHistory")


# ==============================================================================
# Database Initialization
# ==============================================================================

def get_engine(db_path=None):
    """Create database engine with connection pooling (#33)."""
    if db_path is None:
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    from sqlalchemy.pool import QueuePool

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        poolclass=QueuePool,       # #33 explicit pool for SQLite threading
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,
        connect_args={"timeout": 30, "check_same_thread": False},
    )

    # Enable WAL mode + performance pragmas
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size=-8000")  # 8MB cache
        cursor.close()

    return engine


def get_session(engine=None):
    """Create database session."""
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def init_database(engine=None):
    """Initialize all database tables."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


# ==============================================================================
# Fix 29: Database Migration System
# ==============================================================================

MIGRATIONS = [
    {
        "version": 1,
        "description": "Add is_custom to domains",
        "sql": [
            "ALTER TABLE domains ADD COLUMN is_custom BOOLEAN DEFAULT 0",
        ]
    },
    {
        "version": 2,
        "description": "Phase 2a - State history, pattern extensions, pattern match log",
        "sql": [
            # StateHistory table
            """CREATE TABLE IF NOT EXISTS state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER REFERENCES devices(id),
                entity_id VARCHAR(255) NOT NULL,
                old_state VARCHAR(100),
                new_state VARCHAR(100) NOT NULL,
                old_attributes JSON,
                new_attributes JSON,
                context JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_state_history_entity ON state_history(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_state_history_created ON state_history(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_state_history_device ON state_history(device_id, created_at)",

            # PatternMatchLog table
            """CREATE TABLE IF NOT EXISTS pattern_match_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id INTEGER NOT NULL REFERENCES learned_patterns(id),
                matched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                context JSON,
                trigger_event_id INTEGER REFERENCES state_history(id),
                was_executed BOOLEAN DEFAULT 0,
                was_correct BOOLEAN
            )""",
            "CREATE INDEX IF NOT EXISTS idx_pattern_match_pattern ON pattern_match_log(pattern_id)",

            # LearnedPattern extensions
            "ALTER TABLE learned_patterns ADD COLUMN description_de TEXT",
            "ALTER TABLE learned_patterns ADD COLUMN description_en TEXT",
            "ALTER TABLE learned_patterns ADD COLUMN trigger_conditions JSON",
            "ALTER TABLE learned_patterns ADD COLUMN action_definition JSON",
            "ALTER TABLE learned_patterns ADD COLUMN last_matched_at DATETIME",
            "ALTER TABLE learned_patterns ADD COLUMN match_count INTEGER DEFAULT 0",
            "ALTER TABLE learned_patterns ADD COLUMN status VARCHAR(30) DEFAULT 'observed'",
        ]
    },
    {
        "version": 3,
        "description": "Phase 2b - Prediction extensions for suggestions & automation",
        "sql": [
            "ALTER TABLE predictions ADD COLUMN status VARCHAR(30) DEFAULT 'pending'",
            "ALTER TABLE predictions ADD COLUMN user_response VARCHAR(30)",
            "ALTER TABLE predictions ADD COLUMN responded_at DATETIME",
            "ALTER TABLE predictions ADD COLUMN notification_sent BOOLEAN DEFAULT 0",
            "ALTER TABLE predictions ADD COLUMN previous_state JSON",
            "ALTER TABLE predictions ADD COLUMN executed_at DATETIME",
            "ALTER TABLE predictions ADD COLUMN undone_at DATETIME",
            "ALTER TABLE predictions ADD COLUMN description_de TEXT",
            "ALTER TABLE predictions ADD COLUMN description_en TEXT",
        ]
    },
    {
        "version": 4,
        "description": "Block B - Notifications, Patterns, Manual Rules, Anomaly Settings",
        "sql": [
            # NotificationChannel table
            """CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name VARCHAR(200) NOT NULL UNIQUE,
                display_name VARCHAR(200) NOT NULL,
                channel_type VARCHAR(50) NOT NULL,
                is_enabled BOOLEAN DEFAULT 1,
                config JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # DeviceMute table
            """CREATE TABLE IF NOT EXISTS device_mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                muted_until DATETIME,
                reason VARCHAR(200),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # PatternExclusion table
            """CREATE TABLE IF NOT EXISTS pattern_exclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exclusion_type VARCHAR(30) NOT NULL,
                entity_a VARCHAR(255) NOT NULL,
                entity_b VARCHAR(255) NOT NULL,
                reason VARCHAR(200),
                created_by INTEGER REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # ManualRule table
            """CREATE TABLE IF NOT EXISTS manual_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                trigger_entity VARCHAR(255) NOT NULL,
                trigger_state VARCHAR(100) NOT NULL,
                action_entity VARCHAR(255) NOT NULL,
                action_service VARCHAR(100) NOT NULL,
                action_data JSON,
                conditions JSON,
                delay_seconds INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                execution_count INTEGER DEFAULT 0,
                last_executed_at DATETIME,
                created_by INTEGER REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # AnomalySetting table
            """CREATE TABLE IF NOT EXISTS anomaly_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER REFERENCES rooms(id),
                domain_id INTEGER REFERENCES domains(id),
                device_id INTEGER REFERENCES devices(id),
                sensitivity VARCHAR(20) DEFAULT 'medium',
                stuck_detection BOOLEAN DEFAULT 1,
                time_anomaly BOOLEAN DEFAULT 1,
                frequency_anomaly BOOLEAN DEFAULT 1,
                whitelisted_hours JSON,
                auto_action JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # NotificationSetting extensions
            "ALTER TABLE notification_settings ADD COLUMN priority VARCHAR(20) DEFAULT 'medium'",
            "ALTER TABLE notification_settings ADD COLUMN push_channel VARCHAR(100)",
            "ALTER TABLE notification_settings ADD COLUMN escalation_enabled BOOLEAN DEFAULT 0",
            "ALTER TABLE notification_settings ADD COLUMN escalation_minutes INTEGER DEFAULT 30",
            "ALTER TABLE notification_settings ADD COLUMN geofencing_only_away BOOLEAN DEFAULT 0",

            # LearnedPattern Block B extensions
            "ALTER TABLE learned_patterns ADD COLUMN rejection_reason VARCHAR(50)",
            "ALTER TABLE learned_patterns ADD COLUMN rejected_at DATETIME",
            "ALTER TABLE learned_patterns ADD COLUMN category VARCHAR(30)",
            "ALTER TABLE learned_patterns ADD COLUMN season VARCHAR(20)",
            "ALTER TABLE learned_patterns ADD COLUMN test_mode BOOLEAN DEFAULT 0",
            "ALTER TABLE learned_patterns ADD COLUMN test_results JSON",
            "ALTER TABLE learned_patterns ADD COLUMN depends_on_pattern_id INTEGER",
            "ALTER TABLE learned_patterns ADD COLUMN schedule JSON",
            "ALTER TABLE learned_patterns ADD COLUMN delay_seconds INTEGER DEFAULT 0",
            "ALTER TABLE learned_patterns ADD COLUMN conditions JSON",
        ]
    },
    {
        "version": 5,
        "description": "v0.5.0 - Device groups, audit trail, vacation mode",
        "sql": [
            """CREATE TABLE IF NOT EXISTS device_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                room_id INTEGER REFERENCES rooms(id),
                device_ids TEXT DEFAULT '[]',
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS audit_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action VARCHAR(100) NOT NULL,
                target VARCHAR(200),
                details TEXT,
                ip_address VARCHAR(45),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
    },
    {
        "version": 6,
        "description": "Phase 3 - Day phases, presence, guests, energy, scenes, plugins",
        "sql": [
            # Day Phases
            """CREATE TABLE IF NOT EXISTS day_phases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_de VARCHAR(100) NOT NULL,
                name_en VARCHAR(100) NOT NULL,
                icon VARCHAR(50) DEFAULT 'mdi:weather-sunset',
                color VARCHAR(20) DEFAULT '#FFA500',
                sort_order INTEGER DEFAULT 0,
                start_type VARCHAR(20) DEFAULT 'time',
                start_time VARCHAR(5),
                sun_event VARCHAR(30),
                sun_offset_minutes INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Room Orientations
            """CREATE TABLE IF NOT EXISTS room_orientations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL UNIQUE REFERENCES rooms(id),
                orientation VARCHAR(5) NOT NULL,
                offset_minutes INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Person Devices
            """CREATE TABLE IF NOT EXISTS person_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                entity_id VARCHAR(255) NOT NULL,
                device_type VARCHAR(20) DEFAULT 'primary',
                timeout_minutes INTEGER DEFAULT 10,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Guest Devices
            """CREATE TABLE IF NOT EXISTS guest_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac_address VARCHAR(20),
                entity_id VARCHAR(255),
                name VARCHAR(100),
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                visit_count INTEGER DEFAULT 1,
                auto_delete_days INTEGER DEFAULT 30,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Presence Modes
            """CREATE TABLE IF NOT EXISTS presence_modes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_de VARCHAR(100) NOT NULL,
                name_en VARCHAR(100) NOT NULL,
                icon VARCHAR(50) DEFAULT 'mdi:home',
                color VARCHAR(20) DEFAULT '#4CAF50',
                priority INTEGER DEFAULT 0,
                buffer_minutes INTEGER DEFAULT 5,
                actions JSON,
                trigger_type VARCHAR(30) DEFAULT 'manual',
                auto_config JSON,
                notify_on_enter BOOLEAN DEFAULT 0,
                notify_on_leave BOOLEAN DEFAULT 0,
                is_system BOOLEAN DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Presence Log
            """CREATE TABLE IF NOT EXISTS presence_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode_id INTEGER REFERENCES presence_modes(id),
                mode_name VARCHAR(100) NOT NULL,
                user_id INTEGER REFERENCES users(id),
                trigger VARCHAR(50) DEFAULT 'auto',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_presence_log_created ON presence_log(created_at)",

            # Sensor Groups
            """CREATE TABLE IF NOT EXISTS sensor_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                room_id INTEGER REFERENCES rooms(id),
                entity_ids JSON DEFAULT '[]',
                fusion_method VARCHAR(20) DEFAULT 'average',
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Sensor Thresholds
            """CREATE TABLE IF NOT EXISTS sensor_thresholds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id VARCHAR(255),
                min_change_percent FLOAT DEFAULT 5.0,
                min_change_absolute FLOAT,
                min_interval_seconds INTEGER DEFAULT 60,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Energy Config
            """CREATE TABLE IF NOT EXISTS energy_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                price_per_kwh FLOAT DEFAULT 0.25,
                currency VARCHAR(5) DEFAULT 'EUR',
                solar_enabled BOOLEAN DEFAULT 0,
                solar_entity VARCHAR(255),
                grid_import_entity VARCHAR(255),
                grid_export_entity VARCHAR(255),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Energy Readings
            """CREATE TABLE IF NOT EXISTS energy_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id VARCHAR(255) NOT NULL,
                device_id INTEGER REFERENCES devices(id),
                room_id INTEGER REFERENCES rooms(id),
                power_w FLOAT,
                energy_kwh FLOAT,
                reading_type VARCHAR(20) DEFAULT 'power',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_energy_readings_entity ON energy_readings(entity_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_energy_readings_room ON energy_readings(room_id, created_at)",

            # Standby Config
            """CREATE TABLE IF NOT EXISTS standby_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER REFERENCES devices(id),
                entity_id VARCHAR(255),
                threshold_watts FLOAT DEFAULT 5.0,
                idle_minutes INTEGER DEFAULT 30,
                notify_dashboard BOOLEAN DEFAULT 1,
                auto_off BOOLEAN DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Learned Scenes
            """CREATE TABLE IF NOT EXISTS learned_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER REFERENCES rooms(id),
                name_de VARCHAR(100) NOT NULL,
                name_en VARCHAR(100) NOT NULL,
                icon VARCHAR(50) DEFAULT 'mdi:palette',
                states JSON NOT NULL,
                frequency INTEGER DEFAULT 0,
                min_frequency INTEGER DEFAULT 3,
                status VARCHAR(20) DEFAULT 'detected',
                source VARCHAR(20) DEFAULT 'auto',
                last_activated DATETIME,
                last_detected DATETIME,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Plugin Settings
            """CREATE TABLE IF NOT EXISTS plugin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin_name VARCHAR(50) NOT NULL,
                setting_key VARCHAR(100) NOT NULL,
                setting_value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Quiet Hours Config
            """CREATE TABLE IF NOT EXISTS quiet_hours_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                name VARCHAR(100) DEFAULT 'Nachtruhe',
                start_time VARCHAR(5) DEFAULT '22:00',
                end_time VARCHAR(5) DEFAULT '07:00',
                linked_to_shift BOOLEAN DEFAULT 0,
                linked_to_day_phase VARCHAR(50),
                allow_critical BOOLEAN DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # School Vacations
            """CREATE TABLE IF NOT EXISTS school_vacations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_de VARCHAR(100) NOT NULL,
                name_en VARCHAR(100) NOT NULL,
                start_date VARCHAR(10) NOT NULL,
                end_date VARCHAR(10) NOT NULL,
                region VARCHAR(50) DEFAULT 'AT-NÖ',
                source VARCHAR(20) DEFAULT 'manual',
                calendar_entity VARCHAR(255),
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # LearnedPattern: context tags for Phase 3
            "ALTER TABLE learned_patterns ADD COLUMN context_tags JSON",

            # User extensions for Phase 3
            "ALTER TABLE users ADD COLUMN profile_type VARCHAR(20) DEFAULT 'adult'",
            "ALTER TABLE users ADD COLUMN tracking_enabled BOOLEAN DEFAULT 1",
            "ALTER TABLE users ADD COLUMN history_enabled BOOLEAN DEFAULT 1",
        ]
    },
    {
        "version": 7,
        "description": "v0.6.1 - Pattern settings, DataCollection.created_at",
        "sql": [
            # PatternSettings table
            """CREATE TABLE IF NOT EXISTS pattern_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key VARCHAR(100) NOT NULL UNIQUE,
                value TEXT NOT NULL,
                description_de TEXT,
                description_en TEXT,
                category VARCHAR(50) DEFAULT 'general',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            # DataCollection: add created_at
            "ALTER TABLE data_collection ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        ]
    },
]


def run_migrations(engine):
    """Run pending database migrations safely. (#15 rollback-safe)"""
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        Base.metadata.create_all(engine)

        current_version = 0
        try:
            result = session.execute(
                text("SELECT value FROM system_settings WHERE key = 'db_migration_version'")
            ).fetchone()
            if result:
                current_version = int(result[0])
        except Exception:
            pass

        for migration in MIGRATIONS:
            if migration["version"] <= current_version:
                continue

            logger.info(f"Running migration v{migration['version']}: {migration['description']}")

            # #15 – Create savepoint for rollback safety
            migration_ok = True
            for sql in migration["sql"]:
                try:
                    session.execute(text(sql))
                    logger.info(f"  SQL OK: {sql[:80]}...")
                except Exception as e:
                    if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                        logger.info(f"  Already exists, skipping: {sql[:60]}")
                    else:
                        logger.error(f"  Migration SQL error: {e}")
                        migration_ok = False

            if migration_ok:
                try:
                    existing = session.execute(
                        text("SELECT id FROM system_settings WHERE key = 'db_migration_version'")
                    ).fetchone()
                    if existing:
                        session.execute(
                            text("UPDATE system_settings SET value = :v WHERE key = 'db_migration_version'"),
                            {"v": str(migration["version"])}
                        )
                    else:
                        session.execute(
                            text("INSERT INTO system_settings (key, value) VALUES ('db_migration_version', :v)"),
                            {"v": str(migration["version"])}
                        )
                except Exception as e:
                    logger.warning(f"Version update warning: {e}")

                session.commit()
                logger.info(f"Migration v{migration['version']} complete")
            else:
                session.rollback()
                logger.error(f"Migration v{migration['version']} FAILED - rolled back")
                break

        final_v = max(m['version'] for m in MIGRATIONS) if MIGRATIONS else 0
        logger.info(f"Database at migration version {final_v}")

    except Exception as e:
        logger.error(f"Migration error: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()
