"""
MindHome - Database Models
All persistent data structures for MindHome.
Phase 1 Final - with migration system
"""

from datetime import datetime
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


class LearningPhase(enum.Enum):
    OBSERVING = "observing"
    SUGGESTING = "suggesting"
    AUTONOMOUS = "autonomous"


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
    ha_person_entity = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True)
    pin_hash = Column(String(255), nullable=True)
    language = Column(String(5), default="de")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")
    notifications_settings = relationship("NotificationSetting", back_populates="user", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    preference_key = Column(String(100), nullable=False)
    preference_value = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)


class RoomDomainState(Base):
    __tablename__ = "room_domain_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    learning_phase = Column(Enum(LearningPhase), default=LearningPhase.OBSERVING)
    phase_started_at = Column(DateTime, default=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    pattern_type = Column(String(50), nullable=False)
    pattern_data = Column(JSON, nullable=False)
    confidence = Column(Float, default=0.0)
    times_confirmed = Column(Integer, default=0)
    times_rejected = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    description_template = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    quiet_hours_allow_critical = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    action_data = Column(JSON, nullable=False)
    sort_order = Column(Integer, default=0)
    is_system = Column(Boolean, default=False)
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
    __tablename__ = "data_collection"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    data_type = Column(String(100), nullable=False)
    record_count = Column(Integer, default=0)
    first_record_at = Column(DateTime, nullable=True)
    last_record_at = Column(DateTime, nullable=True)
    storage_size_bytes = Column(Integer, default=0)

    room = relationship("Room")
    domain = relationship("Domain")


# ==============================================================================
# Database Initialization
# ==============================================================================

def get_engine(db_path=None):
    """Create database engine."""
    if db_path is None:
        db_path = os.environ.get("MINDHOME_DB_PATH", "/data/mindhome/db/mindhome.db")

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

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
    # Future migrations go here:
    # {
    #     "version": 2,
    #     "description": "Add new_field to some_table",
    #     "sql": ["ALTER TABLE some_table ADD COLUMN new_field TEXT"]
    # },
]


def run_migrations(engine):
    """Run pending database migrations safely."""
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Ensure system_settings table exists (for tracking migration version)
        Base.metadata.create_all(engine)

        # Get current migration version
        current_version = 0
        try:
            result = session.execute(
                text("SELECT value FROM system_settings WHERE key = 'db_migration_version'")
            ).fetchone()
            if result:
                current_version = int(result[0])
        except Exception:
            pass

        # Run pending migrations
        for migration in MIGRATIONS:
            if migration["version"] <= current_version:
                continue

            logger.info(f"Running migration v{migration['version']}: {migration['description']}")

            for sql in migration["sql"]:
                try:
                    session.execute(text(sql))
                    logger.info(f"  SQL OK: {sql[:80]}...")
                except Exception as e:
                    # Column might already exist (e.g. from fresh install)
                    if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                        logger.info(f"  Already exists, skipping: {sql[:60]}")
                    else:
                        logger.warning(f"  Migration SQL warning: {e}")

            # Update version
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

        logger.info(f"Database at migration version {max(m['version'] for m in MIGRATIONS) if MIGRATIONS else 0}")

    except Exception as e:
        logger.error(f"Migration error: {e}")
        try:
            session.rollback()
        except:
            pass
    finally:
        session.close()
