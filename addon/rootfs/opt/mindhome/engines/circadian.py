# MindHome - engines/circadian.py | see version.py for version info
"""
Circadian lighting with dual-mode support.
Feature: #27 Zirkadiane Beleuchtung

Supports three light types:
- dim2warm: Brightness controls color temperature (e.g. Luxvenum 1800K-3000K via MDT AKD)
- tunable_white: Independent brightness + color temperature
- standard: Brightness only, no color control

Two control modes:
- mindhome: MindHome drives brightness curve entirely
- hybrid_hcl: MDT AKD HCL runs baseline, MindHome overrides for events via KNX GA
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("mindhome.engines.circadian")


class CircadianLightManager:
    """Manages circadian lighting per room based on day phase and events.

    Subscribes to sleep.detected, wake.detected, guests.arrived events for overrides.
    Uses HA transition parameter for smooth dimming.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_overrides = {}  # room_id -> override info

    def start(self):
        self._is_running = True
        self._subscribe_events()
        logger.info("CircadianLightManager started")

    def stop(self):
        self._is_running = False
        logger.info("CircadianLightManager stopped")

    def _subscribe_events(self):
        """Subscribe to relevant events for overrides."""
        self.event_bus.subscribe("sleep.detected", self._on_sleep, source_filter=None)
        self.event_bus.subscribe("wake.detected", self._on_wake, source_filter=None)
        self.event_bus.subscribe("guests.arrived", self._on_guests, source_filter=None)

    def _on_sleep(self, event):
        """Handle sleep event — apply sleep override."""
        # TODO: Batch 3

    def _on_wake(self, event):
        """Handle wake event — apply wakeup override."""
        # TODO: Batch 3

    def _on_guests(self, event):
        """Handle guest arrival — apply guest override."""
        # TODO: Batch 3

    def check(self):
        """Periodic brightness check/adjustment. Called by scheduler."""
        if not self._is_running:
            return
        # TODO: Batch 3 — Implement circadian curve tracking

    def get_status(self):
        """Return current circadian state per room."""
        # TODO: Batch 3
        return []
