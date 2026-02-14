# MindHome - engines/sleep.py | see version.py for version info
"""
Sleep detection, quality tracking, and smart wake-up.
Features: #4 Schlaf-Erkennung, #16 Schlafqualitaet, #25 Sanftes Wecken
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("mindhome.engines.sleep")


class SleepDetector:
    """Detects sleep/wake events from sensor data.

    Heuristics: Last activity, lights off, motion sensors inactive.
    Fallback: Light-off + inactivity > 30 min (no motion sensor needed).
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("SleepDetector started")

    def stop(self):
        self._is_running = False
        logger.info("SleepDetector stopped")

    def check(self):
        """Periodic check for sleep/wake state. Called by scheduler."""
        if not self._is_running:
            return
        # TODO: Batch 2 — Implement sleep detection logic

    def get_recent_sessions(self, user_id=None, days=7):
        """Return recent SleepSession entries."""
        # TODO: Batch 2
        return []


class WakeUpManager:
    """Smart wake-up with gradual light/cover/climate ramp.

    Reads WakeUpConfig per user, ramps devices X minutes before wake time.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("WakeUpManager started")

    def stop(self):
        self._is_running = False
        logger.info("WakeUpManager stopped")

    def check(self):
        """Check if any wake-up ramp should start. Called by scheduler."""
        if not self._is_running:
            return
        # TODO: Batch 2 — Implement wake-up ramp logic
