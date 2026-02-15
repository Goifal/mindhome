# MindHome - engines/camera_security.py | see version.py for version info
"""
Camera snapshots on security events.
Feature: #3 Kamera-Snapshots bei Sicherheitsereignissen
"""

import os
import logging
import json
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("mindhome.engines.camera_security")

SNAPSHOT_DIR = "/config/mindhome/snapshots"


class SecurityCameraManager:
    """Automatic camera snapshots on security events.

    Listens to emergency.* and access.unknown events.
    Takes snapshots from all configured cameras and stores them locally.
    """

    DEFAULT_CONFIG = {
        "snapshot_on_events": ["fire", "co", "panic", "access_unknown", "water_leak"],
        "retention_days": 30,
        "max_snapshots_per_event": 5,
        "attach_to_notification": True,
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    def start(self):
        self._is_running = True
        self.event_bus.subscribe("emergency.*", self._on_emergency, priority=50)
        self.event_bus.subscribe("access.unknown", self._on_emergency, priority=50)
        logger.info("SecurityCameraManager started")

    def stop(self):
        self._is_running = False
        logger.info("SecurityCameraManager stopped")

    def get_config(self):
        """Get camera snapshot configuration."""
        from helpers import get_setting
        config = dict(self.DEFAULT_CONFIG)
        stored = get_setting("phase5.camera_config")
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        """Update camera snapshot configuration."""
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting("phase5.camera_config", json.dumps(config))
        return config

    def get_cameras(self):
        """Get list of configured cameras with status."""
        from models import FeatureEntityAssignment
        cameras = []
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="camera", role="snapshot_camera", is_active=True
                ).order_by(FeatureEntityAssignment.sort_order).all()
                for a in assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    cameras.append({
                        "entity_id": a.entity_id,
                        "state": state.get("state", "unknown") if state else "unknown",
                        "name": state.get("attributes", {}).get("friendly_name", a.entity_id) if state else a.entity_id,
                    })
        except Exception as e:
            logger.error(f"Error getting cameras: {e}")
        return cameras

    def get_snapshots(self, limit=50, offset=0):
        """Get snapshot gallery (paginated)."""
        from models import SecurityEvent
        snapshots = []
        try:
            with self.get_session() as session:
                events = session.query(SecurityEvent).filter(
                    SecurityEvent.snapshot_path.isnot(None)
                ).order_by(SecurityEvent.timestamp.desc()).offset(offset).limit(limit).all()
                for evt in events:
                    snapshots.append({
                        "id": evt.id,
                        "event_type": evt.event_type.value if evt.event_type else None,
                        "severity": evt.severity.value if evt.severity else None,
                        "snapshot_path": evt.snapshot_path,
                        "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
                        "message_de": evt.message_de,
                        "message_en": evt.message_en,
                    })
        except Exception as e:
            logger.error(f"Error getting snapshots: {e}")
        return snapshots

    def take_snapshot(self, entity_id):
        """Take a manual snapshot from a specific camera."""
        return self._capture_snapshot(entity_id, "manual")

    def delete_snapshot(self, event_id):
        """Delete a snapshot by security event ID."""
        try:
            from models import SecurityEvent
            with self.get_session() as session:
                evt = session.query(SecurityEvent).get(event_id)
                if evt and evt.snapshot_path:
                    try:
                        if os.path.exists(evt.snapshot_path):
                            os.remove(evt.snapshot_path)
                    except OSError:
                        pass
                    evt.snapshot_path = None
                    return True
        except Exception as e:
            logger.error(f"Error deleting snapshot: {e}")
        return False

    def cleanup_old_snapshots(self):
        """Remove snapshots older than retention period. Called by data_retention task."""
        config = self.get_config()
        retention_days = config.get("retention_days", 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        try:
            from models import SecurityEvent
            with self.get_session() as session:
                old_events = session.query(SecurityEvent).filter(
                    SecurityEvent.snapshot_path.isnot(None),
                    SecurityEvent.timestamp < cutoff
                ).all()
                removed = 0
                for evt in old_events:
                    try:
                        if evt.snapshot_path and os.path.exists(evt.snapshot_path):
                            os.remove(evt.snapshot_path)
                            removed += 1
                    except OSError:
                        pass
                    evt.snapshot_path = None
                if removed:
                    logger.info(f"Cleaned up {removed} old snapshots (retention={retention_days}d)")
        except Exception as e:
            logger.error(f"Snapshot cleanup error: {e}")

    def _on_emergency(self, event):
        """Handle emergency events — take camera snapshots."""
        if not self._is_running:
            return

        from routes.security import is_phase5_feature_enabled
        if not is_phase5_feature_enabled("phase5.camera_snapshots"):
            return

        config = self.get_config()
        event_type = event.event_type if hasattr(event, 'event_type') else "unknown"
        data = event.data if hasattr(event, 'data') else {}

        # Check if this event type triggers snapshots
        allowed_events = config.get("snapshot_on_events", self.DEFAULT_CONFIG["snapshot_on_events"])
        # Map event types: emergency.fire -> fire, access.unknown -> access_unknown
        short_type = event_type.replace("emergency.", "").replace("access.", "access_")
        if short_type not in allowed_events:
            return

        max_snapshots = config.get("max_snapshots_per_event", 5)
        cameras = self.get_cameras()
        snapshot_paths = []

        for cam in cameras[:max_snapshots]:
            path = self._capture_snapshot(cam["entity_id"], short_type)
            if path:
                snapshot_paths.append(path)

        if snapshot_paths:
            logger.info(f"Captured {len(snapshot_paths)} snapshots for {event_type}")
            # Link first snapshot to the security event if possible
            self._link_snapshot_to_event(data, snapshot_paths[0])

    def _capture_snapshot(self, entity_id, reason="event"):
        """Capture a single snapshot from a camera entity."""
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            cam_name = entity_id.replace("camera.", "").replace(".", "_")
            filename = f"{ts}_{cam_name}_{reason}.jpg"
            filepath = os.path.join(SNAPSHOT_DIR, filename)

            self.ha.call_service("camera", "snapshot", {
                "entity_id": entity_id,
                "filename": filepath,
            })
            logger.info(f"Snapshot captured: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Snapshot capture failed for {entity_id}: {e}")
            return None

    def _link_snapshot_to_event(self, event_data, snapshot_path):
        """Link a snapshot path to the most recent matching security event."""
        try:
            from models import SecurityEvent
            with self.get_session() as session:
                recent = session.query(SecurityEvent).order_by(
                    SecurityEvent.id.desc()
                ).first()
                if recent and not recent.snapshot_path:
                    recent.snapshot_path = snapshot_path
        except Exception as e:
            logger.error(f"Snapshot link error: {e}")
