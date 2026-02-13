"""
MindHome - Domain Manager
Loads, registers, and orchestrates all domain plugins.
"""

import logging
from typing import Dict, Optional

from .base import DomainPlugin
from .light import LightDomain
from .climate import ClimateDomain
from .cover import CoverDomain
from .presence import PresenceDomain
from .media import MediaDomain
from .door_window import DoorWindowDomain
from .motion import MotionDomain
from .energy import EnergyDomain
from .weather import WeatherDomain
from .lock import LockDomain
from .switch import SwitchDomain
from .air_quality import AirQualityDomain
from .ventilation import VentilationDomain
from .solar import SolarDomain
from .bed_occupancy import BedOccupancyDomain
from .seat_occupancy import SeatOccupancyDomain
from .vacuum import VacuumDomain
from .system import SystemDomain
from .motion_control import MotionControlDomain
from .humidifier import HumidifierDomain
from .camera import CameraDomain

logger = logging.getLogger("mindhome.domain_manager")

# Registry: maps domain name -> plugin class
DOMAIN_REGISTRY: Dict[str, type] = {
    "light": LightDomain,
    "climate": ClimateDomain,
    "cover": CoverDomain,
    "presence": PresenceDomain,
    "media": MediaDomain,
    "door_window": DoorWindowDomain,
    "motion": MotionDomain,
    "energy": EnergyDomain,
    "weather": WeatherDomain,
    "lock": LockDomain,
    "switch": SwitchDomain,
    "air_quality": AirQualityDomain,
    "ventilation": VentilationDomain,
    "solar": SolarDomain,
    "bed_occupancy": BedOccupancyDomain,
    "seat_occupancy": SeatOccupancyDomain,
    "vacuum": VacuumDomain,
    "system": SystemDomain,
    "motion_control": MotionControlDomain,
    "humidifier": HumidifierDomain,
    "camera": CameraDomain,
}


class DomainManager:
    """Manages all domain plugins, handles event routing."""

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self._active_plugins: Dict[str, DomainPlugin] = {}
        self._all_plugins: Dict[str, DomainPlugin] = {}

        # Instantiate all plugins
        for name, plugin_class in DOMAIN_REGISTRY.items():
            try:
                plugin = plugin_class(ha_connection, db_session_factory)
                self._all_plugins[name] = plugin
            except Exception as e:
                logger.error(f"Failed to instantiate domain '{name}': {e}")

        logger.info(f"Domain Manager initialized with {len(self._all_plugins)} plugins")

    def start_enabled_domains(self):
        """Start all domains that are enabled in the database."""
        from models import Domain
        session = self.get_session()
        try:
            enabled = session.query(Domain).filter_by(is_enabled=True).all()
            enabled_names = {d.name for d in enabled}

            for name, plugin in self._all_plugins.items():
                if name in enabled_names:
                    self.start_domain(name)

            logger.info(
                f"Started {len(self._active_plugins)} of {len(self._all_plugins)} domains: "
                f"{list(self._active_plugins.keys())}"
            )
        finally:
            session.close()

    def start_domain(self, domain_name: str) -> bool:
        """Start a specific domain plugin."""
        if domain_name in self._active_plugins:
            logger.debug(f"Domain '{domain_name}' already running")
            return True

        plugin = self._all_plugins.get(domain_name)
        if not plugin:
            logger.error(f"Domain '{domain_name}' not found in registry")
            return False

        try:
            plugin.start()
            self._active_plugins[domain_name] = plugin
            return True
        except Exception as e:
            logger.error(f"Failed to start domain '{domain_name}': {e}")
            return False

    def stop_domain(self, domain_name: str) -> bool:
        """Stop a specific domain plugin."""
        plugin = self._active_plugins.pop(domain_name, None)
        if plugin:
            try:
                plugin.stop()
                return True
            except Exception as e:
                logger.error(f"Failed to stop domain '{domain_name}': {e}")
                return False
        return False

    def stop_all(self):
        """Stop all active domain plugins."""
        for name in list(self._active_plugins.keys()):
            self.stop_domain(name)
        logger.info("All domains stopped")

    def on_state_change(self, event):
        """Route state change events to the appropriate domain plugins."""
        event_data = event.get("data", {})
        entity_id = event_data.get("entity_id", "")
        old_state = event_data.get("old_state", {}) or {}
        new_state = event_data.get("new_state", {}) or {}

        if not entity_id or not new_state:
            return

        ha_domain = entity_id.split(".")[0]
        device_class = new_state.get("attributes", {}).get("device_class", "")

        # Route to matching active plugins
        for name, plugin in self._active_plugins.items():
            if ha_domain in plugin.HA_DOMAINS:
                # If plugin has specific device_classes, check match
                if plugin.DEVICE_CLASSES and device_class not in plugin.DEVICE_CLASSES:
                    continue
                try:
                    plugin.on_state_change(entity_id, old_state, new_state)
                except Exception as e:
                    logger.error(f"Error in {name}.on_state_change: {e}")

    def get_domain_status(self, domain_name: str) -> Optional[dict]:
        """Get current status from a domain plugin."""
        plugin = self._active_plugins.get(domain_name) or self._all_plugins.get(domain_name)
        if plugin:
            try:
                return plugin.get_current_status()
            except Exception as e:
                logger.error(f"Error getting status for '{domain_name}': {e}")
        return None

    def get_all_status(self) -> dict:
        """Get status from all active domains."""
        status = {}
        for name, plugin in self._active_plugins.items():
            try:
                status[name] = plugin.get_current_status()
            except Exception as e:
                logger.error(f"Error getting status for '{name}': {e}")
                status[name] = {"error": str(e)}
        return status

    def get_trackable_features(self, domain_name: str) -> list:
        """Get trackable features for a domain (for privacy settings)."""
        plugin = self._all_plugins.get(domain_name)
        if plugin:
            return plugin.get_trackable_features()
        return []

    def get_all_trackable_features(self) -> dict:
        """Get trackable features for all domains."""
        return {
            name: plugin.get_trackable_features()
            for name, plugin in self._all_plugins.items()
        }

    def is_domain_active(self, domain_name: str) -> bool:
        """Check if a domain is currently active."""
        return domain_name in self._active_plugins

    def get_active_domains(self) -> list:
        """Get list of active domain names."""
        return list(self._active_plugins.keys())

    def toggle_domain(self, domain_name: str) -> bool:
        """Toggle a domain on/off. Returns new state (True=active)."""
        if domain_name in self._active_plugins:
            self.stop_domain(domain_name)
            return False
        else:
            return self.start_domain(domain_name)
