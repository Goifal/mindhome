# MindHome - engines/comfort.py | see version.py for version info
"""
Comfort scoring, ventilation reminders, and screen time monitoring.
Features: #10 Komfort-Score, #18 Lueftungserinnerung, #19 Bildschirmzeit
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("mindhome.engines.comfort")


class ComfortCalculator:
    """Calculates comfort score per room from sensor data.

    Factors: Temperature (20-23C ideal), humidity (40-60%), CO2 (<1000ppm), light.
    Missing sensors get neutral score (50/100) — graceful degradation.
    """

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("ComfortCalculator started")

    def stop(self):
        self._is_running = False
        logger.info("ComfortCalculator stopped")

    def calculate(self):
        """Calculate comfort scores for all rooms. Called by scheduler."""
        if not self._is_running:
            return
        # TODO: Batch 3 — Implement scoring algorithm

    def get_scores(self):
        """Return current comfort scores per room."""
        # TODO: Batch 3
        return []

    def get_history(self, room_id, days=7):
        """Return comfort score history for a room."""
        # TODO: Batch 3
        return []


class VentilationMonitor:
    """Monitors air quality and sends ventilation reminders.

    Checks: CO2 > threshold OR last ventilation > interval.
    Tracks window openings as 'ventilated' events.
    Fallback: Timer-based reminders when no CO2 sensor present.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("VentilationMonitor started")

    def stop(self):
        self._is_running = False
        logger.info("VentilationMonitor stopped")

    def check(self):
        """Check ventilation status for all rooms. Called by scheduler."""
        if not self._is_running:
            return
        # TODO: Batch 3 — Implement ventilation monitoring

    def get_status(self):
        """Return ventilation status per room."""
        # TODO: Batch 3
        return []


class ScreenTimeMonitor:
    """Tracks media player usage and sends reminders after configured limits.

    Monitors media_player entities, counts active time, notifies per user config.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_sessions = {}  # entity_id -> start_time

    def start(self):
        self._is_running = True
        logger.info("ScreenTimeMonitor started")

    def stop(self):
        self._is_running = False
        logger.info("ScreenTimeMonitor stopped")

    def check(self):
        """Check screen time for all configured entities. Called by scheduler."""
        if not self._is_running:
            return
        # TODO: Batch 4 — Implement screen time tracking

    def get_usage(self, user_id=None):
        """Return current screen time data."""
        # TODO: Batch 4
        return {"today_minutes": 0, "sessions": []}
