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
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("mindhome.engines.circadian")

# Default brightness curve (percentage per hour for "mindhome" mode)
DEFAULT_BRIGHTNESS_CURVE = [
    {"time": "05:00", "pct": 10},   # dawn
    {"time": "06:00", "pct": 40},   # early morning
    {"time": "07:00", "pct": 70},   # morning
    {"time": "08:00", "pct": 90},   # mid-morning
    {"time": "09:00", "pct": 100},  # day
    {"time": "12:00", "pct": 100},  # midday
    {"time": "16:00", "pct": 100},  # afternoon
    {"time": "18:00", "pct": 80},   # late afternoon
    {"time": "19:00", "pct": 60},   # dusk
    {"time": "20:00", "pct": 40},   # evening
    {"time": "21:00", "pct": 25},   # late evening
    {"time": "22:00", "pct": 10},   # night
    {"time": "23:00", "pct": 5},    # late night
]

# Color temperature curve for tunable_white (Kelvin)
DEFAULT_CT_CURVE = [
    {"time": "05:00", "kelvin": 2200},
    {"time": "07:00", "kelvin": 3500},
    {"time": "09:00", "kelvin": 5000},
    {"time": "12:00", "kelvin": 5500},
    {"time": "16:00", "kelvin": 5000},
    {"time": "18:00", "kelvin": 3500},
    {"time": "20:00", "kelvin": 2700},
    {"time": "22:00", "kelvin": 2200},
]


def _interpolate_curve(curve, key, now_h, now_m):
    """Interpolate a value from a time-based curve."""
    now_min = now_h * 60 + now_m
    prev_entry = curve[-1]  # wrap around
    for entry in curve:
        parts = entry["time"].split(":")
        entry_min = int(parts[0]) * 60 + int(parts[1])
        if entry_min > now_min:
            # Interpolate between prev and this
            prev_parts = prev_entry["time"].split(":")
            prev_min = int(prev_parts[0]) * 60 + int(prev_parts[1])
            if prev_min > entry_min:
                prev_min -= 1440  # handle wrap
            span = entry_min - prev_min
            if span <= 0:
                return entry[key]
            elapsed = now_min - prev_min
            if elapsed < 0:
                elapsed += 1440
            ratio = elapsed / span
            return prev_entry[key] + (entry[key] - prev_entry[key]) * ratio
        prev_entry = entry
    return curve[-1][key]


class CircadianLightManager:
    """Manages circadian lighting per room based on day phase and events.

    Subscribes to sleep.detected, sleep.wake_detected, visit.preparation_activated events for overrides.
    Uses HA transition parameter for smooth dimming.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_overrides = {}  # room_id -> {"type": str, "brightness_pct": int, "until": datetime}
        self._cached_status = {}  # room_id -> status dict

    def start(self):
        self._is_running = True
        self._subscribe_events()
        logger.info("CircadianLightManager started")

    def stop(self):
        self._is_running = False
        self._active_overrides.clear()
        logger.info("CircadianLightManager stopped")

    def _subscribe_events(self):
        """Subscribe to relevant events for overrides."""
        self.event_bus.subscribe("sleep.detected", self._on_sleep, source_filter=None)
        self.event_bus.subscribe("sleep.wake_detected", self._on_wake, source_filter=None)
        self.event_bus.subscribe("visit.preparation_activated", self._on_guests, source_filter=None)

    def _on_sleep(self, event):
        """Handle sleep event — apply sleep override to all circadian rooms."""
        if not self._is_running:
            return
        try:
            from models import CircadianConfig
            with self.get_session() as session:
                configs = session.query(CircadianConfig).filter(
                    CircadianConfig.enabled == True
                ).all()
                for cfg in configs:
                    self._active_overrides[cfg.room_id] = {
                        "type": "sleep",
                        "brightness_pct": cfg.override_sleep or 10,
                        "transition_sec": cfg.override_transition_sec or 300,
                        "until": None,  # until wake
                    }
                    self._apply_brightness(cfg, cfg.override_sleep or 10, cfg.override_transition_sec or 300)
            logger.info(f"Circadian sleep override applied to {len(configs)} rooms")
        except Exception as e:
            logger.error(f"Circadian _on_sleep error: {e}")

    def _on_wake(self, event):
        """Handle wake event — apply wakeup override, then resume curve."""
        if not self._is_running:
            return
        try:
            from models import CircadianConfig
            with self.get_session() as session:
                configs = session.query(CircadianConfig).filter(
                    CircadianConfig.enabled == True
                ).all()
                now = datetime.now(timezone.utc)
                for cfg in configs:
                    self._active_overrides[cfg.room_id] = {
                        "type": "wakeup",
                        "brightness_pct": cfg.override_wakeup or 70,
                        "transition_sec": cfg.override_transition_sec or 300,
                        "until": now + timedelta(minutes=30),  # override for 30 min, then resume curve
                    }
                    self._apply_brightness(cfg, cfg.override_wakeup or 70, cfg.override_transition_sec or 300)
            logger.info("Circadian wakeup override applied")
        except Exception as e:
            logger.error(f"Circadian _on_wake error: {e}")

    def _on_guests(self, event):
        """Handle guest arrival — apply guest override."""
        if not self._is_running:
            return
        try:
            from models import CircadianConfig
            with self.get_session() as session:
                configs = session.query(CircadianConfig).filter(
                    CircadianConfig.enabled == True
                ).all()
                now = datetime.now(timezone.utc)
                for cfg in configs:
                    self._active_overrides[cfg.room_id] = {
                        "type": "guests",
                        "brightness_pct": cfg.override_guests or 90,
                        "transition_sec": cfg.override_transition_sec or 300,
                        "until": now + timedelta(hours=3),  # guest override for 3h
                    }
                    self._apply_brightness(cfg, cfg.override_guests or 90, cfg.override_transition_sec or 300)
            logger.info("Circadian guest override applied")
        except Exception as e:
            logger.error(f"Circadian _on_guests error: {e}")

    def check(self):
        """Periodic brightness check/adjustment. Called every 15 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import CircadianConfig, Room, Device
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.circadian_lighting"):
                return

            with self.get_session() as session:
                configs = session.query(CircadianConfig).filter(
                    CircadianConfig.enabled == True
                ).all()
                now = datetime.now(timezone.utc)

                for cfg in configs:
                    room = session.query(Room).get(cfg.room_id)
                    room_name = room.name if room else f"Room {cfg.room_id}"

                    # Check if override is active
                    override = self._active_overrides.get(cfg.room_id)
                    if override:
                        if override.get("until") and now > override["until"]:
                            # Override expired, remove and resume curve
                            del self._active_overrides[cfg.room_id]
                            logger.debug(f"Circadian override expired for room {room_name}")
                        else:
                            # Override still active, skip curve
                            self._cached_status[cfg.room_id] = {
                                "room_id": cfg.room_id,
                                "room_name": room_name,
                                "mode": cfg.control_mode,
                                "light_type": cfg.light_type,
                                "override_active": True,
                                "override_type": override["type"],
                                "brightness_pct": override["brightness_pct"],
                                "curve_pct": None,
                            }
                            continue

                    if cfg.control_mode == "mindhome":
                        # MindHome drives the curve
                        curve = cfg.brightness_curve or DEFAULT_BRIGHTNESS_CURVE
                        target_pct = _interpolate_curve(curve, "pct", now.hour, now.minute)
                        target_pct = max(0, min(100, round(target_pct)))

                        self._apply_brightness(cfg, target_pct, transition_sec=60)

                        ct_kelvin = None
                        if cfg.light_type == "tunable_white":
                            ct_kelvin = round(_interpolate_curve(DEFAULT_CT_CURVE, "kelvin", now.hour, now.minute))
                            self._apply_color_temp(cfg, ct_kelvin)

                        self._cached_status[cfg.room_id] = {
                            "room_id": cfg.room_id,
                            "room_name": room_name,
                            "mode": "mindhome",
                            "light_type": cfg.light_type,
                            "override_active": False,
                            "override_type": None,
                            "brightness_pct": target_pct,
                            "color_temp_kelvin": ct_kelvin,
                            "curve_pct": target_pct,
                        }

                    elif cfg.control_mode == "hybrid_hcl":
                        # MDT AKD HCL runs baseline, MindHome only observes
                        # (overrides handled above via events)
                        self._cached_status[cfg.room_id] = {
                            "room_id": cfg.room_id,
                            "room_name": room_name,
                            "mode": "hybrid_hcl",
                            "light_type": cfg.light_type,
                            "override_active": False,
                            "override_type": None,
                            "brightness_pct": None,
                            "hcl_active": True,
                        }

                logger.debug(f"Circadian check done for {len(configs)} rooms")
        except Exception as e:
            logger.error(f"CircadianLightManager check error: {e}")

    def _apply_brightness(self, cfg, brightness_pct, transition_sec=60):
        """Apply brightness to a room's lights."""
        try:
            from models import Device
            with self.get_session() as session:
                lights = session.query(Device).filter(
                    Device.room_id == cfg.room_id,
                    Device.ha_entity_id.like("light.%"),
                    Device.is_tracked == True
                ).all()

                brightness_val = int(brightness_pct * 255 / 100)
                for light in lights:
                    try:
                        if brightness_val > 0:
                            self.ha.call_service("light", "turn_on", {
                                "entity_id": light.ha_entity_id,
                                "brightness": brightness_val,
                                "transition": transition_sec,
                            })
                        else:
                            self.ha.call_service("light", "turn_off", {
                                "entity_id": light.ha_entity_id,
                                "transition": transition_sec,
                            })
                    except Exception as e:
                        logger.debug(f"Circadian light control error {light.ha_entity_id}: {e}")
        except Exception as e:
            logger.error(f"_apply_brightness error: {e}")

    def _apply_color_temp(self, cfg, kelvin):
        """Apply color temperature to tunable_white lights."""
        try:
            from models import Device
            with self.get_session() as session:
                lights = session.query(Device).filter(
                    Device.room_id == cfg.room_id,
                    Device.ha_entity_id.like("light.%"),
                    Device.is_tracked == True
                ).all()

                for light in lights:
                    try:
                        self.ha.call_service("light", "turn_on", {
                            "entity_id": light.ha_entity_id,
                            "color_temp_kelvin": kelvin,
                            "transition": 60,
                        })
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"_apply_color_temp error: {e}")

    def get_status(self):
        """Return current circadian state per room."""
        if self._cached_status:
            return list(self._cached_status.values())
        # Fallback: return configs without live data
        try:
            from models import CircadianConfig, Room
            with self.get_session() as session:
                configs = session.query(CircadianConfig).filter(
                    CircadianConfig.enabled == True
                ).all()
                result = []
                for cfg in configs:
                    room = session.query(Room).get(cfg.room_id)
                    result.append({
                        "room_id": cfg.room_id,
                        "room_name": room.name if room else f"Room {cfg.room_id}",
                        "mode": cfg.control_mode,
                        "light_type": cfg.light_type,
                        "override_active": False,
                        "override_type": None,
                        "brightness_pct": None,
                    })
                return result
        except Exception as e:
            logger.error(f"get_status error: {e}")
            return []

    def get_configs(self):
        """Return all circadian configs."""
        try:
            from models import CircadianConfig, Room
            with self.get_session() as session:
                configs = session.query(CircadianConfig).all()
                return [{
                    "id": c.id,
                    "room_id": c.room_id,
                    "room_name": session.query(Room).get(c.room_id).name if session.query(Room).get(c.room_id) else None,
                    "enabled": c.enabled,
                    "control_mode": c.control_mode,
                    "light_type": c.light_type,
                    "brightness_curve": c.brightness_curve,
                    "hcl_pause_ga": c.hcl_pause_ga,
                    "hcl_resume_ga": c.hcl_resume_ga,
                    "override_sleep": c.override_sleep,
                    "override_wakeup": c.override_wakeup,
                    "override_guests": c.override_guests,
                    "override_transition_sec": c.override_transition_sec,
                } for c in configs]
        except Exception as e:
            logger.error(f"get_configs error: {e}")
            return []
