"""
MindHome - Database Models
All persistent data structures for MindHome.
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Enum, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import enum
import os

Base = declarative_base()


# ==============================================================================
# Enums
# ==============================================================================

class UserRole(enum.Enum):
    ADMIN = "admin"
    USER = "user"


class LearningPhase(enum.Enum):
    OBSERVING = "observing"       # Phase 1: Only collecting data
    SUGGESTING = "suggesting"     # Phase 2: Making suggestions, waiting for confirmation
    AUTONOMOUS = "autonomous"     # Phase 3: Acting independently


class NotificationType(enum.Enum):
    CRITICAL = "critical"
    SUGGESTION = "suggestion"
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
    ha_person_entity = Column(String(255), nullable=True)  # e.g. person.john
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True)
    pin_hash = Column(String(255), nullable=True)  # Optional PIN for admin access
    language = Column(String(5), default="de")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")
    notifications_settings = relationship("NotificationSetting", back_populates="user", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)  # null = global preference
    preference_key = Column(String(100), nullable=False)  # e.g. "temperature", "brightness"
    preference_value = Column(String(255), nullable=False)  # e.g. "21", "60"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="preferences")
    room = relationship("Room")


# ==============================================================================
# Rooms
# ==============================================================================

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    ha_area_id = Column(String(255), nullable=True)  # HA Area ID
    icon = Column(String(50), default="mdi:door")
    privacy_mode = Column(JSON, default=dict)  # {"motion": false, "energy": true, ...}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    devices = relationship("Device", back_populates="room", cascade="all, delete-orphan")
    domain_states = relationship("RoomDomainState", back_populates="room", cascade="all, delete-orphan")


# ==============================================================================
# Domains & Devices
# ==============================================================================

class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)  # e.g. "light", "climate"
    display_name_de = Column(String(100), nullable=False)
    display_name_en = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=False)
    is_enabled = Column(Boolean, default=False)
    description_de = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RoomDomainState(Base):
    """Learning phase state per room per domain."""
    __tablename__ = "room_domain_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    learning_phase = Column(Enum(LearningPhase), default=LearningPhase.OBSERVING)
    phase_started_at = Column(DateTime, default=datetime.utcnow)
    confidence_score = Column(Float, default=0.0)  # 0.0 - 1.0
    is_paused = Column(Boolean, default=False)  # Manual override / Not-Aus

    # Relationships
    room = relationship("Room", back_populates="domain_states")
    domain = relationship("Domain")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ha_entity_id = Column(String(255), nullable=False, unique=True)  # e.g. light.living_room
    name = Column(String(200), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    is_tracked = Column(Boolean, default=True)  # Whether MindHome tracks this device
    is_controllable = Column(Boolean, default=True)  # Whether MindHome can control this device
    device_meta = Column(JSON, default=dict)  # Extra metadata from HA
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
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
    pattern_data = Column(JSON, nullable=False)  # The actual pattern definition
    confidence = Column(Float, default=0.0)
    times_confirmed = Column(Integer, default=0)
    times_rejected = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    description_template = Column(Text, nullable=True)  # Template for human-readable explanation
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    domain = relationship("Domain")
    room = relationship("Room")
    user = relationship("User")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_id = Column(Integer, ForeignKey("learned_patterns.id"), nullable=False)
    predicted_action = Column(JSON, nullable=False)  # What MindHome wants to do
    predicted_for = Column(DateTime, nullable=False)  # When should it happen
    confidence = Column(Float, nullable=False)
    was_executed = Column(Boolean, default=False)
    was_correct = Column(Boolean, nullable=True)  # null = not yet verified
    execution_result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    pattern = relationship("LearnedPattern")


# ==============================================================================
# Action Log
# ==============================================================================

class ActionLog(Base):
    __tablename__ = "action_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_type = Column(String(50), nullable=False)  # "automation", "suggestion", "anomaly", "first_time"
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action_data = Column(JSON, nullable=False)  # What happened
    reason = Column(Text, nullable=True)  # WHY it happened (for context notifications)
    was_undone = Column(Boolean, default=False)  # Undo tracking
    previous_state = Column(JSON, nullable=True)  # State before action (for undo)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
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
    quiet_hours_start = Column(String(5), nullable=True)  # "22:00"
    quiet_hours_end = Column(String(5), nullable=True)  # "07:00"
    quiet_hours_allow_critical = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="notifications_settings")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type = Column(Enum(NotificationType), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    was_sent = Column(Boolean, default=False)
    was_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ==============================================================================
# Quick Actions
# ==============================================================================

class QuickAction(Base):
    __tablename__ = "quick_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_de = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=False)
    action_data = Column(JSON, nullable=False)  # List of actions to execute
    sort_order = Column(Integer, default=0)
    is_system = Column(Boolean, default=False)  # System actions like "All off", "I'm leaving"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==============================================================================
# Offline Fallback Queue
# ==============================================================================

class OfflineActionQueue(Base):
    __tablename__ = "offline_action_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_data = Column(JSON, nullable=False)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)
    was_executed = Column(Boolean, default=False)


# ==============================================================================
# Data Privacy Tracking
# ==============================================================================

class DataCollection(Base):
    """Tracks what data MindHome collects per room/domain for transparency."""
    __tablename__ = "data_collection"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    data_type = Column(String(100), nullable=False)  # e.g. "motion_events", "temperature_readings"
    record_count = Column(Integer, default=0)
    first_record_at = Column(DateTime, nullable=True)
    last_record_at = Column(DateTime, nullable=True)
    storage_size_bytes = Column(Integer, default=0)

    # Relationships
    room = relationship("Room")
    domain = relationship("Domain")


# ==============================================================================
# Database Initialization
# ==============================================================================

def get_engine(db_path=None):
    """Create database engine."""
    if db_path is None:
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")
    return create_engine(f"sqlite:///{db_path}", echo=False)


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
