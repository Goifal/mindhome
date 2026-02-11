"""
MindHome - Home Assistant Connection v0.6.0-phase3
Handles real-time WebSocket connection and REST API calls to HA.
Features: Retry with backoff, reconnect limiter, batch events, calendar integration,
          climate validation, timezone caching, ingress token forwarding.
Phase 3: Sun tracking, day phases, presence helpers, weather data.
"""

import os
import json
import logging
import threading
import time
import queue
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, List, Dict, Any
import requests
import websocket

logger = logging.getLogger("mindhome.ha_connection")

MAX_RECONNECT_ATTEMPTS = 20
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.5
BATCH_FLUSH_INTERVAL = 2.0
BATCH_MAX_SIZE = 100


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
        self._ws = None
        self._ws_thread = None
        self._ws_connected = False
        self._ws_id = 1
        self._ws_lock = threading.Lock()
        self._event_callbacks: List[dict] = []
        self._response_handlers: Dict[int, Callable] = {}
        self._reconnect_delay = 5
        self._reconnect_attempts = 0
        self._should_run = True
        self._offline_queue: List[dict] = []
        self._is_online = False
        self._timezone: Optional[str] = None
        self._config_cache: Optional[dict] = None
        self._config_cache_time: float = 0
        self._event_queue: queue.Queue = queue.Queue()
        self._batch_thread: Optional[threading.Thread] = None
        self._batch_callbacks: List[Callable] = []
        self._stats = {
            "api_calls": 0, "api_errors": 0, "ws_messages": 0,
            "ws_reconnects": 0, "events_received": 0, "events_batched": 0, "retries": 0,
        }

    # ======================================================================
    # REST API
    # ======================================================================

    def _api_request(self, method, endpoint, data=None, retry=True):
        url = f"{self.ha_url}/api/{endpoint}"
        attempts = RETRY_MAX_ATTEMPTS if retry else 1
        for attempt in range(attempts):
            try:
                self._stats["api_calls"] += 1
                response = requests.request(method, url, headers=self.headers, json=data, timeout=10)
                response.raise_for_status()
                self._is_online = True
                return response.json() if response.text else None
            except requests.exceptions.HTTPError as e:
                self._stats["api_errors"] += 1
                status_code = e.response.status_code if e.response is not None else 0
                # Don't retry client errors (4xx) — the request is wrong, retrying won't help
                if 400 <= status_code < 500:
                    logger.error(f"HA API client error for {endpoint}: {e}")
                    self._is_online = True
                    return None
                if attempt < attempts - 1:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    self._stats["retries"] += 1
                    logger.warning(f"HA API retry {attempt+1}/{attempts} for {endpoint} in {wait:.1f}s: {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"HA API failed after {attempts} attempts: {endpoint} - {e}")
                    self._is_online = False
                    return None
            except requests.exceptions.RequestException as e:
                self._stats["api_errors"] += 1
                if attempt < attempts - 1:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    self._stats["retries"] += 1
                    logger.warning(f"HA API retry {attempt+1}/{attempts} for {endpoint} in {wait:.1f}s: {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"HA API failed after {attempts} attempts: {endpoint} - {e}")
                    self._is_online = False
                    return None

    def get_states(self):
        return self._api_request("GET", "states") or []

    def get_state(self, entity_id):
        return self._api_request("GET", f"states/{entity_id}", retry=False)

    def get_config(self):
        now = time.time()
        if self._config_cache and (now - self._config_cache_time) < 300:
            return self._config_cache
        result = self._api_request("GET", "config")
        if result:
            self._config_cache = result
            self._config_cache_time = now
        return result

    def get_services(self):
        return self._api_request("GET", "services") or []

    def get_timezone(self):
        if self._timezone:
            return self._timezone
        config = self.get_config()
        if config:
            self._timezone = config.get("time_zone", "UTC")
            return self._timezone
        return "UTC"

    def call_service(self, domain, service, data=None, entity_id=None):
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id
        if domain == "climate" and service in ("set_temperature", "set_hvac_mode"):
            payload = self._validate_climate_call(payload)
        result = self._api_request("POST", f"services/{domain}/{service}", payload)
        if result is None and not self._is_online:
            self._offline_queue.append({
                "domain": domain, "service": service,
                "data": payload, "queued_at": datetime.now(timezone.utc).isoformat()
            })
            logger.warning(f"Action queued (offline): {domain}.{service}")
        return result

    def _validate_climate_call(self, payload):
        eid = payload.get("entity_id")
        temp = payload.get("temperature")
        if not eid or temp is None:
            return payload
        try:
            state = self.get_state(eid)
            if state:
                attrs = state.get("attributes", {})
                min_t = attrs.get("min_temp", 7)
                max_t = attrs.get("max_temp", 35)
                temp = float(temp)
                if temp < min_t:
                    logger.warning(f"Climate {eid}: clamped {temp}→{min_t}°C (min)")
                    temp = min_t
                elif temp > max_t:
                    logger.warning(f"Climate {eid}: clamped {temp}→{max_t}°C (max)")
                    temp = max_t
                payload["temperature"] = temp
        except Exception as e:
            logger.warning(f"Climate validation error: {e}")
        return payload

    def get_history(self, entity_id, start_time=None, end_time=None):
        params = []
        if start_time:
            params.append(f"filter_entity_id={entity_id}")
        endpoint = f"history/period/{start_time or ''}"
        if params:
            endpoint += "?" + "&".join(params)
        return self._api_request("GET", endpoint) or []

    def get_areas(self):
        return self._ws_command("config/area_registry/list")

    def get_device_registry(self):
        return self._ws_command("config/device_registry/list")

    def get_entity_registry(self):
        return self._ws_command("config/entity_registry/list")

    def get_automations(self):
        states = self.get_states()
        return [s for s in states if s.get("entity_id", "").startswith("automation.")] if states else []

    def get_calendars(self):
        return self._api_request("GET", "calendars") or []

    def get_calendar_events(self, entity_id, start=None, end=None):
        if not start:
            start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if not end:
            end = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        try:
            result = self._api_request("GET", f"calendars/{entity_id}?start={start}&end={end}", retry=False)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    def get_upcoming_events(self, hours=24):
        calendars = self.get_calendars()
        events = []
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=hours)
        start_str = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for cal in calendars:
            eid = cal.get("entity_id", "")
            try:
                cal_events = self.get_calendar_events(eid, start_str, end_str)
                for ev in cal_events:
                    ev["calendar_entity"] = eid
                    events.append(ev)
            except Exception:
                pass
        return sorted(events, key=lambda e: e.get("start", {}).get("dateTime", ""))

    def send_notification(self, message, title=None, target=None, data=None):
        payload = {"message": message}
        if title:
            payload["title"] = title
        if data:
            payload["data"] = data
        # Strip "notify." prefix if present (service name must be without domain)
        service = target or "notify"
        if service.startswith("notify."):
            service = service[len("notify."):]
        return self.call_service("notify", service, payload)

    def announce_tts(self, message, media_player_entity=None, language=None):
        """Send TTS announcement via Home Assistant."""
        entity = media_player_entity
        if not entity:
            try:
                from helpers import get_setting
                entity = get_setting("tts_media_player")
            except Exception:
                pass
        if not entity:
            states = self.get_states()
            speakers = [s for s in states
                        if s.get("entity_id", "").startswith("media_player.")
                        and s.get("state") != "unavailable"]
            if speakers:
                entity = speakers[0]["entity_id"]
        if not entity:
            logger.warning("No media player found for TTS")
            return {"error": "No media player found for TTS"}

        lang_short = language or "de"
        lang_full = f"{lang_short}-{lang_short.upper()}" if len(lang_short) == 2 else lang_short

        # Discover available TTS entities for tts.speak (HA 2024+)
        states = self.get_states()
        tts_entities = [s["entity_id"] for s in states
                        if s.get("entity_id", "").startswith("tts.")]

        logger.info(f"TTS: speaker={entity}, tts_entities={tts_entities}, lang={lang_short}")

        # Try tts.speak with each TTS entity (HA 2024+)
        for tts_entity in tts_entities:
            # HA Cloud needs full locale (de-DE), others use short (de)
            tts_lang = lang_full if "cloud" in tts_entity else lang_short
            result = self._api_request("POST", "services/tts/speak", {
                "entity_id": tts_entity,
                "media_player_entity_id": entity,
                "message": message,
                "language": tts_lang,
            }, retry=False)
            if result is not None:
                logger.info(f"TTS: success with tts.speak entity={tts_entity}")
                return result
            logger.warning(f"TTS: tts.speak failed with entity {tts_entity}")

        # Fallback: tts.cloud_say (HA Cloud legacy)
        result = self._api_request("POST", "services/tts/cloud_say", {
            "entity_id": entity,
            "message": message,
            "language": lang_full,
        }, retry=False)
        if result is not None:
            logger.info("TTS: success with tts.cloud_say")
            return result

        # Fallback: tts.google_translate_say (legacy)
        result = self._api_request("POST", "services/tts/google_translate_say", {
            "entity_id": entity,
            "message": message,
            "language": lang_short,
        }, retry=False)
        if result is not None:
            logger.info("TTS: success with tts.google_translate_say")
            return result

        logger.warning("TTS: All TTS methods failed")
        return {"error": "All TTS methods failed"}

    def fire_event(self, event_type, event_data=None):
        return self._api_request("POST", f"events/{event_type}", event_data or {})

    # ======================================================================
    # WebSocket
    # ======================================================================

    def _next_ws_id(self):
        with self._ws_lock:
            self._ws_id += 1
            return self._ws_id

    def _ws_command(self, command_type, **kwargs):
        if not self._ws_connected:
            logger.warning("WebSocket not connected")
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
        self._event_callbacks.append({"callback": callback, "event_type": event_type})
        if self._ws_connected:
            msg = {"id": self._next_ws_id(), "type": "subscribe_events"}
            if event_type:
                msg["event_type"] = event_type
            try:
                self._ws.send(json.dumps(msg))
            except Exception:
                pass

    def _on_ws_open(self, ws):
        logger.info("WebSocket connection opened")

    def _on_ws_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            self._stats["ws_messages"] += 1

            if msg_type == "auth_required":
                ws.send(json.dumps({"type": "auth", "access_token": self.token}))

            elif msg_type == "auth_ok":
                logger.info("WebSocket authenticated")
                self._ws_connected = True
                self._is_online = True
                self._reconnect_delay = 5
                self._reconnect_attempts = 0
                try:
                    self.get_timezone()
                except Exception:
                    pass
                for cb_info in list(self._event_callbacks):
                    msg = {"id": self._next_ws_id(), "type": "subscribe_events"}
                    if cb_info.get("event_type"):
                        msg["event_type"] = cb_info["event_type"]
                    ws.send(json.dumps(msg))
                self._process_offline_queue()

            elif msg_type == "auth_invalid":
                logger.error("WebSocket auth failed!")
                self._ws_connected = False

            elif msg_type == "event":
                event = data.get("event", {})
                event_type = event.get("event_type", "")
                self._stats["events_received"] += 1
                if self._batch_callbacks:
                    self._event_queue.put(event)
                    self._stats["events_batched"] += 1
                else:
                    for cb_info in list(self._event_callbacks):
                        if cb_info["event_type"] is None or cb_info["event_type"] == event_type:
                            try:
                                cb_info["callback"](event)
                            except Exception as e:
                                logger.error(f"Event callback error: {e}")

            elif msg_type == "result":
                msg_id = data.get("id")
                handler = self._response_handlers.get(msg_id)
                if handler:
                    handler(data)

        except json.JSONDecodeError:
            logger.error(f"Invalid WS message: {message[:100]}")

    def _on_ws_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")
        self._ws_connected = False
        self._is_online = False

    def _on_ws_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
        self._ws_connected = False
        if self._should_run:
            self._reconnect_attempts += 1
            self._stats["ws_reconnects"] += 1
            if self._reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
                logger.error(f"Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) reached.")
                return
            logger.info(f"Reconnecting in {self._reconnect_delay}s "
                        f"(attempt {self._reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})...")
            time.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60)
            self._start_ws()

    def _start_ws(self):
        self._ws = websocket.WebSocketApp(
            self.ha_ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        self._ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._ws_thread.start()

    # ======================================================================
    # Event Batching (#12)
    # ======================================================================

    def register_batch_callback(self, callback: Callable):
        self._batch_callbacks.append(callback)
        if not self._batch_thread or not self._batch_thread.is_alive():
            self._batch_thread = threading.Thread(target=self._batch_worker, daemon=True)
            self._batch_thread.start()

    def _batch_worker(self):
        while self._should_run:
            batch = []
            deadline = time.time() + BATCH_FLUSH_INTERVAL
            while time.time() < deadline and len(batch) < BATCH_MAX_SIZE:
                try:
                    event = self._event_queue.get(timeout=0.5)
                    batch.append(event)
                except queue.Empty:
                    continue
            if batch:
                for cb in list(self._batch_callbacks):
                    try:
                        cb(batch)
                    except Exception as e:
                        logger.error(f"Batch callback error: {e}")

    # ======================================================================
    # Connection Management
    # ======================================================================

    def connect(self):
        logger.info("Connecting to Home Assistant...")
        states = self.get_states()
        if states is not None:
            logger.info(f"REST API connected - {len(states)} entities found")
        else:
            logger.warning("REST API not available - will retry via WebSocket")
        self._start_ws()

    def disconnect(self):
        logger.info("Disconnecting from Home Assistant...")
        self._should_run = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._batch_thread and self._batch_thread.is_alive():
            self._batch_thread.join(timeout=5)
        logger.info("Disconnected")

    def force_reconnect(self):
        self._reconnect_attempts = 0
        self._reconnect_delay = 5
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._start_ws()

    def _process_offline_queue(self):
        if not self._offline_queue:
            return
        logger.info(f"Processing {len(self._offline_queue)} queued actions...")
        q = self._offline_queue.copy()
        self._offline_queue.clear()
        for action in q:
            self.call_service(action["domain"], action["service"], action["data"])

    # ======================================================================
    # Properties & Helpers
    # ======================================================================

    @property
    def connected(self):
        return self._ws_connected and self._is_online

    def is_connected(self):
        return self._ws_connected and self._is_online

    def get_connection_stats(self):
        return {
            **self._stats,
            "ws_connected": self._ws_connected,
            "is_online": self._is_online,
            "reconnect_attempts": self._reconnect_attempts,
            "max_reconnect_attempts": MAX_RECONNECT_ATTEMPTS,
            "offline_queue_size": len(self._offline_queue),
        }

    def get_entities_by_domain(self, domain):
        states = self.get_states()
        return [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")] if states else []

    def get_offline_queue_size(self):
        return len(self._offline_queue)

    def discover_devices(self):
        states = self.get_states()
        if not states:
            return {}
        domain_mapping = {
            "light": "light", "climate": "climate", "cover": "cover",
            "person": "presence", "device_tracker": "presence",
            "media_player": "media", "binary_sensor": None, "sensor": None,
            "lock": "lock", "switch": "switch", "fan": "ventilation",
            "weather": "weather", "vacuum": "vacuum",
        }
        sensor_class_mapping = {
            "motion": "motion", "occupancy": "motion",
            "door": "door_window", "window": "door_window",
            "opening": "door_window", "garage_door": "door_window",
            "moisture": "air_quality", "humidity": "air_quality",
            "co2": "air_quality", "volatile_organic_compounds": "air_quality",
            "pm25": "air_quality", "pm10": "air_quality",
            "temperature": "climate",
            "power": "energy", "energy": "energy",
            "current": "energy", "voltage": "energy", "gas": "energy",
            "smoke": "lock", "carbon_monoxide": "lock", "battery": "energy",
        }
        discovered = {}
        for state in states:
            entity_id = state.get("entity_id", "")
            ha_domain = entity_id.split(".")[0]
            attributes = state.get("attributes", {})
            device_class = attributes.get("device_class", "")
            friendly_name = attributes.get("friendly_name", entity_id)
            md = domain_mapping.get(ha_domain)
            if md is None and ha_domain in ("binary_sensor", "sensor"):
                md = sensor_class_mapping.get(device_class)
            if md is None:
                continue
            if md not in discovered:
                discovered[md] = []
            discovered[md].append({
                "entity_id": entity_id, "friendly_name": friendly_name,
                "state": state.get("state"), "device_class": device_class,
                "attributes": attributes,
            })
        return discovered

    # ======================================================================
    # Phase 3: Sun & Day Phase Tracking
    # ======================================================================

    def get_sun_state(self):
        """Get current sun.sun state with elevation, azimuth, etc."""
        state = self.get_state("sun.sun")
        if not state:
            return None
        attrs = state.get("attributes", {})
        return {
            "state": state.get("state", "unknown"),  # "above_horizon" / "below_horizon"
            "elevation": attrs.get("elevation", 0),
            "azimuth": attrs.get("azimuth", 0),
            "rising": attrs.get("rising", False),
            "next_dawn": attrs.get("next_dawn"),
            "next_dusk": attrs.get("next_dusk"),
            "next_midnight": attrs.get("next_midnight"),
            "next_noon": attrs.get("next_noon"),
            "next_rising": attrs.get("next_rising"),
            "next_setting": attrs.get("next_setting"),
        }

    def get_sun_events_today(self):
        """Calculate today's sun events from sun.sun attributes."""
        sun = self.get_sun_state()
        if not sun:
            return {}
        return {
            "dawn": sun.get("next_dawn"),
            "sunrise": sun.get("next_rising"),
            "noon": sun.get("next_noon"),
            "sunset": sun.get("next_setting"),
            "dusk": sun.get("next_dusk"),
            "elevation": sun.get("elevation", 0),
            "azimuth": sun.get("azimuth", 0),
            "is_day": sun.get("state") == "above_horizon",
        }

    def get_current_season(self):
        """Determine astronomical season based on current month."""
        now = datetime.now(timezone.utc)
        month = now.month
        if month in (3, 4, 5):
            return "spring"
        elif month in (6, 7, 8):
            return "summer"
        elif month in (9, 10, 11):
            return "autumn"
        else:
            return "winter"

    # ======================================================================
    # Phase 3: Presence Helpers
    # ======================================================================

    def get_persons_home(self):
        """Get list of person entities that are currently 'home'."""
        states = self.get_states()
        if not states:
            return []
        persons = []
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("person.") and s.get("state") == "home":
                persons.append({
                    "entity_id": eid,
                    "name": s.get("attributes", {}).get("friendly_name", eid),
                    "state": "home",
                })
        return persons

    def get_all_persons(self):
        """Get all person entities with their state."""
        states = self.get_states()
        if not states:
            return []
        return [{
            "entity_id": s.get("entity_id"),
            "name": s.get("attributes", {}).get("friendly_name", s.get("entity_id")),
            "state": s.get("state"),
            "source": s.get("attributes", {}).get("source"),
            "latitude": s.get("attributes", {}).get("latitude"),
            "longitude": s.get("attributes", {}).get("longitude"),
        } for s in states if s.get("entity_id", "").startswith("person.")]

    def get_device_trackers(self, network_filter=None):
        """Get device_tracker entities, optionally filtered by network/source."""
        states = self.get_states()
        if not states:
            return []
        trackers = []
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("device_tracker."):
                continue
            attrs = s.get("attributes", {})
            tracker = {
                "entity_id": eid,
                "name": attrs.get("friendly_name", eid),
                "state": s.get("state"),
                "source_type": attrs.get("source_type"),
                "mac": attrs.get("mac"),
                "ip": attrs.get("ip"),
                "host_name": attrs.get("host_name"),
                "is_home": s.get("state") == "home",
            }
            if network_filter:
                # Filter by source like "router" or specific integration
                if attrs.get("source_type") != network_filter:
                    continue
            trackers.append(tracker)
        return trackers

    def is_anyone_home(self):
        """Quick check if at least one person is home."""
        try:
            return len(self.get_persons_home()) > 0
        except Exception:
            return False

    def count_persons_home(self):
        """Count how many persons are home."""
        try:
            return len(self.get_persons_home())
        except Exception:
            return 0

    # ======================================================================
    # Phase 3: Weather Helpers
    # ======================================================================

    def get_weather(self):
        """Get current weather data from first weather entity."""
        states = self.get_states()
        if not states:
            return None
        for s in states:
            if s.get("entity_id", "").startswith("weather."):
                attrs = s.get("attributes", {})
                return {
                    "entity_id": s.get("entity_id"),
                    "condition": s.get("state"),
                    "temperature": attrs.get("temperature"),
                    "humidity": attrs.get("humidity"),
                    "pressure": attrs.get("pressure"),
                    "wind_speed": attrs.get("wind_speed"),
                    "wind_bearing": attrs.get("wind_bearing"),
                    "forecast": attrs.get("forecast", [])[:5],
                }
        return None

    def is_raining(self):
        """Check if current weather indicates rain."""
        weather = self.get_weather()
        if not weather:
            return False
        rain_conditions = ("rainy", "pouring", "lightning-rainy", "hail",
                          "snowy", "snowy-rainy", "exceptional")
        return weather.get("condition", "") in rain_conditions

    # ======================================================================
    # Phase 3: Scene Helpers
    # ======================================================================

    def create_ha_scene(self, name, entities):
        """Create a scene in HA from entity states."""
        return self.call_service("scene", "create", {
            "scene_id": f"mindhome_{name.lower().replace(' ', '_')}",
            "snapshot_entities": [e["entity_id"] for e in entities] if entities else [],
        })

    def activate_ha_scene(self, scene_entity_id):
        """Activate an existing HA scene."""
        return self.call_service("scene", "turn_on", entity_id=scene_entity_id)

    def check_device_health(self):
        issues = []
        states = self.get_states()
        if not states:
            return issues
        for state in states:
            eid = state.get("entity_id", "")
            s = state.get("state", "")
            attrs = state.get("attributes", {})
            if s in ("unavailable", "unknown"):
                issues.append({
                    "entity_id": eid, "type": "unreachable",
                    "message_de": f"{attrs.get('friendly_name', eid)} ist nicht erreichbar",
                    "message_en": f"{attrs.get('friendly_name', eid)} is unreachable",
                    "severity": "warning",
                })
            battery = attrs.get("battery_level") or attrs.get("battery")
            if battery is not None:
                try:
                    if float(battery) < 15:
                        issues.append({
                            "entity_id": eid, "type": "low_battery",
                            "battery_level": float(battery),
                            "message_de": f"{attrs.get('friendly_name', eid)}: Batterie niedrig ({battery}%)",
                            "message_en": f"{attrs.get('friendly_name', eid)}: Low battery ({battery}%)",
                            "severity": "warning",
                        })
                except (ValueError, TypeError):
                    pass
        return issues
