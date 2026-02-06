"""
MindHome - Domain Plugin Base Class
All domain modules inherit from this base class.
"""

from abc import ABC, abstractmethod
from datetime import datetime
import logging

logger = logging.getLogger("mindhome.domains")


class DomainPlugin(ABC):
    """Base class for all MindHome domain plugins."""

    # Override in subclass
    DOMAIN_NAME = ""
    HA_DOMAINS = []  # HA entity domains this plugin handles
    DEVICE_CLASSES = []  # Optional: specific device_classes to match

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.logger = logging.getLogger(f"mindhome.domains.{self.DOMAIN_NAME}")
        self._is_running = False

    def start(self):
        """Start the domain plugin."""
        self._is_running = True
        self.logger.info(f"Domain plugin '{self.DOMAIN_NAME}' started")
        self.on_start()

    def stop(self):
        """Stop the domain plugin."""
        self._is_running = False
        self.logger.info(f"Domain plugin '{self.DOMAIN_NAME}' stopped")
        self.on_stop()

    # ==========================================================================
    # Abstract methods - must be implemented by each domain
    # ==========================================================================

    @abstractmethod
    def on_start(self):
        """Called when plugin starts. Set up subscriptions, initial state."""
        pass

    @abstractmethod
    def on_stop(self):
        """Called when plugin stops. Clean up resources."""
        pass

    @abstractmethod
    def on_state_change(self, entity_id, old_state, new_state):
        """Called when a tracked entity changes state."""
        pass

    @abstractmethod
    def get_trackable_features(self):
        """Return list of features this domain can track.
        Used for privacy settings per room.

        Returns:
            list of dict: [{"key": "brightness", "label_de": "Helligkeit", "label_en": "Brightness"}]
        """
        pass

    @abstractmethod
    def get_current_status(self, room_id=None):
        """Get current status summary for dashboard.

        Returns:
            dict with status info for display
        """
        pass

    # ==========================================================================
    # Shared helper methods
    # ==========================================================================

    def get_entities(self):
        """Get all HA entities that belong to this domain."""
        entities = []
        for ha_domain in self.HA_DOMAINS:
            entities.extend(self.ha.get_entities_by_domain(ha_domain))
        return entities

    def get_entity_state(self, entity_id):
        """Get current state of a specific entity."""
        return self.ha.get_state(entity_id)

    def call_service(self, domain, service, data=None, entity_id=None):
        """Call a HA service."""
        return self.ha.call_service(domain, service, data, entity_id)

    def get_entity_history(self, entity_id, hours=24):
        """Get entity history for the last N hours."""
        from datetime import timedelta
        start = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        return self.ha.get_history(entity_id, start)

    def is_entity_tracked(self, entity_id):
        """Check if an entity is tracked in MindHome."""
        from models import Device
        session = self.get_session()
        try:
            device = session.query(Device).filter_by(
                ha_entity_id=entity_id, is_tracked=True
            ).first()
            return device is not None
        finally:
            session.close()

    def is_room_privacy_allowed(self, room_id, feature_key):
        """Check if tracking this feature is allowed by privacy settings."""
        from models import Room
        session = self.get_session()
        try:
            room = session.query(Room).get(room_id)
            if not room or not room.privacy_mode:
                return True  # No restrictions = allowed
            return room.privacy_mode.get(feature_key, True)
        finally:
            session.close()

    def log_action(self, action_type, action_data, reason=None,
                   room_id=None, device_id=None, user_id=None, previous_state=None):
        """Log an action to the action log."""
        from models import ActionLog, Domain
        session = self.get_session()
        try:
            domain = session.query(Domain).filter_by(name=self.DOMAIN_NAME).first()
            log = ActionLog(
                action_type=action_type,
                domain_id=domain.id if domain else None,
                room_id=room_id,
                device_id=device_id,
                user_id=user_id,
                action_data=action_data,
                reason=reason,
                previous_state=previous_state
            )
            session.add(log)
            session.commit()
            return log.id
        finally:
            session.close()

    def send_notification(self, message, title=None, notification_type="info"):
        """Send a notification through HA."""
        prefix = {
            "critical": "🔴",
            "suggestion": "💡",
            "info": "ℹ️"
        }.get(notification_type, "ℹ️")

        full_title = f"{prefix} MindHome: {title}" if title else f"{prefix} MindHome"
        self.ha.send_notification(message, title=full_title)
