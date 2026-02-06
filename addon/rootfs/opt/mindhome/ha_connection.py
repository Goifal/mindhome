"""
MindHome - Home Assistant Connection
Handles real-time WebSocket connection and REST API calls to HA.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Callable
import requests
import websocket

logger = logging.getLogger("mindhome.ha_connection")


class HAConnection:
    """Manages connection to Home Assistant via WebSocket and REST API."""

    def __init__(self):
        self.ha_url = os.environ.get("HA_URL", "http://supervisor/core")
        self.ha_ws_url = os.environ.get("HA_WS_URL", "ws://supervisor/core/websocket")
        self.token = os.environ.get("HA_TOKEN", "")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # WebSocket state
        self._ws = None
        self._ws_thread = None
        self._ws_connected = False
        self._ws_id = 1
        self._event_callbacks = []
        self._response_handlers = {}
        self._reconnect_delay = 5
        self._should_run = True

        # Offline queue
        self._offline_queue = []
        self._is_online = False

    # ==========================================================================
    # REST API Methods
    # ==========================================================================

    def _api_request(self, method, endpoint, data=None):
        """Make a REST API request to HA."""
        url = f"{self.ha_url}/api/{endpoint}"
        try:
            response = requests.request(
                method, url, headers=self.headers, json=data, timeout=10
            )
            response.raise_for_status()
            self._is_online = True
            return response.json() if response.text else None
        except requests.exceptions.RequestException as e:
            logger.error(f"HA API request failed: {e}")
            self._is_online = False
            return None

    def get_states(self):
        """Get all entity states from HA."""
        return self._api_request("GET", "states") or []

    def get_state(self, entity_id):
        """Get state of a specific entity."""
        return self._api_request("GET", f"states/{entity_id}")

    def call_service(self, domain, service, data=None, entity_id=None):
        """Call a HA service (e.g., turn on light)."""
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id

        result = self._api_request("POST", f"services/{domain}/{service}", payload)

        if result is None and not self._is_online:
            # Queue for offline fallback
            self._offline_queue.append({
                "domain": domain,
                "service": service,
                "data": payload,
                "queued_at": datetime.utcnow().isoformat()
            })
            logger.warning(f"Action queued (offline): {domain}.{service}")

        return result

    def get_history(self, entity_id, start_time=None, end_time=None):
        """Get entity history."""
        params = []
        if start_time:
            params.append(f"filter_entity_id={entity_id}")
        endpoint = f"history/period/{start_time or ''}"
        if params:
            endpoint += "?" + "&".join(params)
        return self._api_request("GET", endpoint) or []

    def get_areas(self):
        """Get all areas (rooms) from HA via WebSocket."""
        # Areas are only available via WebSocket
        return self._ws_command("config/area_registry/list")

    def get_device_registry(self):
        """Get all devices from HA via WebSocket."""
        return self._ws_command("config/device_registry/list")

    def get_entity_registry(self):
        """Get all entities from HA via WebSocket."""
        return self._ws_command("config/entity_registry/list")

    def get_automations(self):
        """Get all automations from HA."""
        states = self.get_states()
        if states:
            return [s for s in states if s.get("entity_id", "").startswith("automation.")]
        return []

    def get_calendars(self):
        """Get all calendar entities."""
        return self._api_request("GET", "calendars") or []

    def send_notification(self, message, title=None, target=None, data=None):
        """Send a notification via HA notify service."""
        payload = {"message": message}
        if title:
            payload["title"] = title
        if data:
            payload["data"] = data

        service_target = target or "notify"
        return self.call_service("notify", service_target, payload)

    def fire_event(self, event_type, event_data=None):
        """Fire a custom event in HA."""
        return self._api_request("POST", f"events/{event_type}", event_data or {})

    # ==========================================================================
    # WebSocket Methods (Real-time Events)
    # ==========================================================================

    def _next_ws_id(self):
        """Get next WebSocket message ID."""
        self._ws_id += 1
        return self._ws_id

    def _ws_command(self, command_type, **kwargs):
        """Send a WebSocket command and wait for response."""
        if not self._ws_connected:
            logger.warning("WebSocket not connected, cannot send command")
            return None

        msg_id = self._next_ws_id()
        msg = {"id": msg_id, "type": command_type}
        msg.update(kwargs)

        result_event = threading.Event()
        result_data = [None]

        def handler(response):
            result_data[0] = response.get("result")
            result_event.set()

        self._response_handlers[msg_id] = handler

        try:
            self._ws.send(json.dumps(msg))
            result_event.wait(timeout=10)
            return result_data[0]
        except Exception as e:
            logger.error(f"WebSocket command failed: {e}")
            return None
        finally:
            self._response_handlers.pop(msg_id, None)

    def subscribe_events(self, callback: Callable, event_type: Optional[str] = None):
        """Subscribe to HA events via WebSocket."""
        self._event_callbacks.append({
            "callback": callback,
            "event_type": event_type
        })

        if self._ws_connected:
            msg = {
                "id": self._next_ws_id(),
                "type": "subscribe_events"
            }
            if event_type:
                msg["event_type"] = event_type
            self._ws.send(json.dumps(msg))

    def _on_ws_open(self, ws):
        """Handle WebSocket connection opened."""
        logger.info("WebSocket connection opened")

    def _on_ws_message(self, ws, message):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "auth_required":
                # Send authentication
                ws.send(json.dumps({
                    "type": "auth",
                    "access_token": self.token
                }))

            elif msg_type == "auth_ok":
                logger.info("WebSocket authenticated successfully")
                self._ws_connected = True
                self._is_online = True
                self._reconnect_delay = 5

                # Subscribe to all state changes
                for cb_info in self._event_callbacks:
                    msg = {
                        "id": self._next_ws_id(),
                        "type": "subscribe_events"
                    }
                    if cb_info.get("event_type"):
                        msg["event_type"] = cb_info["event_type"]
                    ws.send(json.dumps(msg))

                # Process offline queue
                self._process_offline_queue()

            elif msg_type == "auth_invalid":
                logger.error("WebSocket authentication failed!")
                self._ws_connected = False

            elif msg_type == "event":
                # Dispatch event to callbacks
                event = data.get("event", {})
                event_type = event.get("event_type", "")

                for cb_info in self._event_callbacks:
                    if cb_info["event_type"] is None or cb_info["event_type"] == event_type:
                        try:
                            cb_info["callback"](event)
                        except Exception as e:
                            logger.error(f"Event callback error: {e}")

            elif msg_type == "result":
                # Handle command responses
                msg_id = data.get("id")
                handler = self._response_handlers.get(msg_id)
                if handler:
                    handler(data)

        except json.JSONDecodeError:
            logger.error(f"Invalid WebSocket message: {message[:100]}")

    def _on_ws_error(self, ws, error):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
        self._ws_connected = False
        self._is_online = False

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection closed."""
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
        self._ws_connected = False

        # Auto-reconnect
        if self._should_run:
            logger.info(f"Reconnecting in {self._reconnect_delay} seconds...")
            time.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60)
            self._start_ws()

    def _start_ws(self):
        """Start WebSocket connection in background thread."""
        self._ws = websocket.WebSocketApp(
            self.ha_ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        self._ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._ws_thread.start()

    def connect(self):
        """Start connection to Home Assistant (WebSocket + verify REST API)."""
        logger.info("Connecting to Home Assistant...")

        # Verify REST API
        states = self.get_states()
        if states is not None:
            logger.info(f"REST API connected - {len(states)} entities found")
        else:
            logger.warning("REST API not available - will retry via WebSocket")

        # Start WebSocket
        self._start_ws()

    def disconnect(self):
        """Close all connections."""
        self._should_run = False
        if self._ws:
            self._ws.close()
        logger.info("Disconnected from Home Assistant")

    def _process_offline_queue(self):
        """Process queued actions after reconnection."""
        if not self._offline_queue:
            return

        logger.info(f"Processing {len(self._offline_queue)} queued actions...")
        queue = self._offline_queue.copy()
        self._offline_queue.clear()

        for action in queue:
            self.call_service(
                action["domain"],
                action["service"],
                action["data"]
            )
            logger.info(f"Executed queued action: {action['domain']}.{action['service']}")

    # ==========================================================================
    # Helper Methods
    # ==========================================================================

    def is_connected(self):
        """Check if connected to HA."""
        return self._ws_connected and self._is_online

    def get_entities_by_domain(self, domain):
        """Get all entities for a specific HA domain."""
        states = self.get_states()
        if states:
            return [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        return []

    def discover_devices(self):
        """Discover all available devices grouped by domain type."""
        states = self.get_states()
        if not states:
            return {}

        # Map HA domains to MindHome domains
        domain_mapping = {
            "light": "light",
            "climate": "climate",
            "cover": "cover",
            "person": "presence",
            "device_tracker": "presence",
            "media_player": "media",
            "binary_sensor": None,  # Needs sub-classification
            "sensor": None,  # Needs sub-classification
            "lock": "lock",
            "switch": "switch",
            "fan": "ventilation",
            "weather": "weather",
            "automation": None,  # Special handling
            "calendar": None,  # Special handling
        }

        # Sub-classify binary_sensor and sensor by device_class
        sensor_class_mapping = {
            "motion": "motion",
            "occupancy": "motion",
            "door": "door_window",
            "window": "door_window",
            "opening": "door_window",
            "garage_door": "door_window",
            "moisture": "air_quality",
            "humidity": "air_quality",
            "co2": "air_quality",
            "volatile_organic_compounds": "air_quality",
            "pm25": "air_quality",
            "pm10": "air_quality",
            "temperature": "climate",
            "power": "energy",
            "energy": "energy",
            "current": "energy",
            "voltage": "energy",
            "gas": "energy",
            "smoke": "lock",  # Security domain
            "carbon_monoxide": "lock",
        }

        discovered = {}

        for state in states:
            entity_id = state.get("entity_id", "")
            ha_domain = entity_id.split(".")[0]
            attributes = state.get("attributes", {})
            device_class = attributes.get("device_class", "")
            friendly_name = attributes.get("friendly_name", entity_id)

            # Determine MindHome domain
            mindhome_domain = domain_mapping.get(ha_domain)

            if mindhome_domain is None and ha_domain in ("binary_sensor", "sensor"):
                mindhome_domain = sensor_class_mapping.get(device_class)

            if mindhome_domain is None:
                continue

            if mindhome_domain not in discovered:
                discovered[mindhome_domain] = []

            discovered[mindhome_domain].append({
                "entity_id": entity_id,
                "friendly_name": friendly_name,
                "state": state.get("state"),
                "device_class": device_class,
                "attributes": attributes,
            })

        return discovered

    def get_offline_queue_size(self):
        """Get number of queued offline actions."""
        return len(self._offline_queue)
