# MindHome - engines/special_modes.py | see version.py for version info
"""
Special mode engines: Party, Cinema, Home-Office, Night Lockdown, Emergency Protocol.
Features: #7 Party, #8 Cinema, #9 Home-Office, #10 Night Lockdown, #11 Emergency Protocol
"""

import logging
import json
import threading
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("mindhome.engines.special_modes")


# ==============================================================================
# Base Class
# ==============================================================================

class SpecialModeBase:
    """Base class for all special modes.

    Provides:
      - activate / deactivate lifecycle
      - State snapshot + restore (previous entity states saved in SpecialModeLog)
      - Timeout auto-deactivation
      - EventBus integration
    """

    mode_type = None  # Overridden by subclass
    feature_flag = None  # Override if feature flag key differs from f"phase5.{mode_type}"

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._active = False
        self._active_log_id = None
        self._deactivation_timer = None

    @property
    def is_active(self):
        return self._active

    def start(self):
        """Start the mode engine. Override for event subscriptions."""
        pass

    def stop(self):
        """Stop the mode engine. Deactivate if active."""
        if self._active:
            self.deactivate(reason="shutdown")

    def get_config(self):
        """Get mode configuration from SystemSettings."""
        from helpers import get_setting
        stored = get_setting(f"phase5.{self.mode_type}_config")
        config = dict(self.DEFAULT_CONFIG)
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        """Update mode configuration."""
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting(f"phase5.{self.mode_type}_config", json.dumps(config))
        return config

    def get_status(self):
        """Get current mode status."""
        return {
            "mode_type": self.mode_type,
            "is_active": self._active,
            "active_log_id": self._active_log_id,
            "config": self.get_config(),
        }

    def activate(self, user_id=None, config_override=None, reason="manual"):
        """Activate this mode: snapshot states, apply actions, log."""
        if self._active:
            logger.warning(f"{self.mode_type} already active")
            return False

        from routes.security import is_phase5_feature_enabled
        flag_key = self.feature_flag or f"phase5.{self.mode_type}"
        if not is_phase5_feature_enabled(flag_key):
            logger.info(f"{self.mode_type} feature disabled")
            return False

        config = self.get_config()
        if config_override:
            config.update(config_override)

        # Snapshot current entity states
        previous_states = self._snapshot_entities(config)

        # Log activation
        self._active_log_id = self._log_activation(user_id, reason, previous_states)
        self._active = True

        # Apply mode-specific actions
        self._apply_actions(config)

        # Start auto-deactivation timer if configured
        timeout = config.get("auto_deactivate_min") or config.get("auto_deactivate_after_hours")
        if timeout:
            minutes = timeout if isinstance(timeout, int) else int(float(timeout) * 60)
            self._start_deactivation_timer(minutes, user_id)

        self.event_bus.publish("mode.activated", {
            "mode_type": self.mode_type,
            "user_id": user_id,
            "reason": reason,
        }, source="special_modes")

        logger.info(f"{self.mode_type} activated (user={user_id}, reason={reason})")
        return True

    def deactivate(self, user_id=None, reason="manual"):
        """Deactivate mode: restore previous states, log."""
        if not self._active:
            return False

        # Cancel timer
        if self._deactivation_timer:
            self._deactivation_timer.cancel()
            self._deactivation_timer = None

        # Restore previous entity states
        self._restore_previous_states()

        # Log deactivation
        self._log_deactivation(user_id, reason)
        self._active = False
        self._active_log_id = None

        self.event_bus.publish("mode.deactivated", {
            "mode_type": self.mode_type,
            "user_id": user_id,
            "reason": reason,
        }, source="special_modes")

        logger.info(f"{self.mode_type} deactivated (user={user_id}, reason={reason})")
        return True

    def check_timeout(self):
        """Check if mode should be auto-deactivated (called by scheduler)."""
        if not self._active or not self._active_log_id:
            return
        config = self.get_config()
        timeout_min = config.get("auto_deactivate_min")
        if not timeout_min:
            return
        try:
            from models import SpecialModeLog
            with self.get_session() as session:
                log = session.query(SpecialModeLog).get(self._active_log_id)
                if log and log.activated_at:
                    elapsed = (datetime.now(timezone.utc) - log.activated_at).total_seconds() / 60
                    if elapsed >= timeout_min:
                        self.deactivate(reason="timeout")
        except Exception as e:
            logger.error(f"Timeout check error for {self.mode_type}: {e}")

    # ── Internal Helpers ────────────────────────────────────

    def _snapshot_entities(self, config):
        """Take snapshot of all entities that will be affected."""
        from models import FeatureEntityAssignment
        states = {}
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key=self.mode_type, is_active=True
                ).all()
                for a in assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    if state:
                        states[a.entity_id] = {
                            "state": state.get("state"),
                            "attributes": state.get("attributes", {}),
                        }
        except Exception as e:
            logger.error(f"Snapshot error for {self.mode_type}: {e}")
        return states

    def _restore_previous_states(self):
        """Restore entity states from the activation log."""
        if not self._active_log_id:
            return
        try:
            from models import SpecialModeLog
            with self.get_session() as session:
                log = session.query(SpecialModeLog).get(self._active_log_id)
                if not log or not log.previous_states:
                    return
                for entity_id, prev in log.previous_states.items():
                    self._restore_single_entity(entity_id, prev)
        except Exception as e:
            logger.error(f"Restore error for {self.mode_type}: {e}")

    def _restore_single_entity(self, entity_id, previous):
        """Restore a single entity to its previous state."""
        try:
            domain = entity_id.split(".")[0]
            prev_state = previous.get("state", "")
            prev_attrs = previous.get("attributes", {})

            if domain == "light":
                if prev_state == "off":
                    self.ha.call_service("light", "turn_off", {"entity_id": entity_id})
                else:
                    svc_data = {"entity_id": entity_id}
                    if "brightness" in prev_attrs:
                        svc_data["brightness"] = prev_attrs["brightness"]
                    if "color_temp" in prev_attrs:
                        svc_data["color_temp"] = prev_attrs["color_temp"]
                    self.ha.call_service("light", "turn_on", svc_data)
            elif domain == "cover":
                pos = prev_attrs.get("current_position")
                if pos is not None:
                    self.ha.call_service("cover", "set_cover_position", {
                        "entity_id": entity_id, "position": pos
                    })
            elif domain == "climate":
                temp = prev_attrs.get("temperature")
                if temp is not None:
                    self.ha.call_service("climate", "set_temperature", {
                        "entity_id": entity_id, "temperature": temp
                    })
            elif domain == "media_player":
                if prev_state == "off":
                    self.ha.call_service("media_player", "turn_off", {"entity_id": entity_id})
                elif prev_state in ("playing", "paused", "idle"):
                    vol = prev_attrs.get("volume_level")
                    if vol is not None:
                        self.ha.call_service("media_player", "volume_set", {
                            "entity_id": entity_id, "volume_level": vol
                        })
        except Exception as e:
            logger.debug(f"Restore entity {entity_id} error: {e}")

    def _log_activation(self, user_id, reason, previous_states):
        """Write activation entry to SpecialModeLog."""
        try:
            from models import SpecialModeLog
            with self.get_session() as session:
                log = SpecialModeLog(
                    mode_type=self.mode_type,
                    activated_at=datetime.now(timezone.utc),
                    activated_by=user_id,
                    reason=reason,
                    previous_states=previous_states,
                )
                session.add(log)
                session.flush()
                return log.id
        except Exception as e:
            logger.error(f"Activation log error: {e}")
            return None

    def _log_deactivation(self, user_id, reason):
        """Update SpecialModeLog with deactivation time."""
        if not self._active_log_id:
            return
        try:
            from models import SpecialModeLog
            with self.get_session() as session:
                log = session.query(SpecialModeLog).get(self._active_log_id)
                if log:
                    log.deactivated_at = datetime.now(timezone.utc)
                    log.reason = reason
        except Exception as e:
            logger.error(f"Deactivation log error: {e}")

    def _start_deactivation_timer(self, minutes, user_id):
        """Start a timer to auto-deactivate the mode."""
        if self._deactivation_timer:
            self._deactivation_timer.cancel()
        self._deactivation_timer = threading.Timer(
            minutes * 60,
            self.deactivate,
            kwargs={"user_id": user_id, "reason": "timeout"},
        )
        self._deactivation_timer.daemon = True
        self._deactivation_timer.start()

    def _apply_actions(self, config):
        """Override in subclass: apply mode-specific entity changes."""
        pass

    def _apply_entity_actions(self, feature_key=None):
        """Apply configured actions to all assigned entities by role."""
        fk = feature_key or self.mode_type
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key=fk, is_active=True
                ).order_by(FeatureEntityAssignment.sort_order).all()
                for a in assignments:
                    role_config = a.config or {}
                    self._apply_single_entity(a.entity_id, a.role, role_config)
        except Exception as e:
            logger.error(f"Apply entity actions error for {fk}: {e}")

    def _apply_single_entity(self, entity_id, role, role_config):
        """Apply role-specific action to a single entity."""
        try:
            domain = entity_id.split(".")[0]
            if domain == "light":
                svc_data = {"entity_id": entity_id}
                if "brightness" in role_config:
                    svc_data["brightness_pct"] = role_config["brightness"]
                if "color_temp" in role_config:
                    svc_data["color_temp_kelvin"] = role_config["color_temp"]
                self.ha.call_service("light", "turn_on", svc_data)
            elif domain == "cover":
                pos = role_config.get("position")
                if pos is not None:
                    self.ha.call_service("cover", "set_cover_position", {
                        "entity_id": entity_id, "position": pos
                    })
            elif domain == "climate":
                from helpers import get_setting
                heating_mode = get_setting("heating_mode", "room_thermostat")
                if heating_mode == "heating_curve":
                    # Heizkurven-Modus: target_temp als Offset interpretieren
                    offset = role_config.get("temperature_offset", role_config.get("target_temp"))
                    if offset is not None:
                        curve_entity = get_setting("heating_curve_entity", entity_id)
                        states = self.ha.get_states() or []
                        for s in states:
                            if s.get("entity_id") == curve_entity:
                                current = s.get("attributes", {}).get("temperature")
                                if current is not None:
                                    new_temp = float(current) + float(offset)
                                    self.ha.call_service("climate", "set_temperature", {
                                        "entity_id": curve_entity, "temperature": round(new_temp, 1)
                                    })
                                break
                else:
                    temp = role_config.get("target_temp")
                    if temp is not None:
                        self.ha.call_service("climate", "set_temperature", {
                            "entity_id": entity_id, "temperature": temp
                        })
            elif domain == "media_player":
                vol = role_config.get("volume")
                if vol is not None:
                    self.ha.call_service("media_player", "volume_set", {
                        "entity_id": entity_id, "volume_level": vol
                    })
                source = role_config.get("source")
                if source:
                    self.ha.call_service("media_player", "select_source", {
                        "entity_id": entity_id, "source": source
                    })
            elif domain == "lock":
                action = role_config.get("action", "lock")
                self.ha.call_service("lock", action, {"entity_id": entity_id})
        except Exception as e:
            logger.debug(f"Apply action error for {entity_id}: {e}")


# ==============================================================================
# #7 Party Mode
# ==============================================================================

class PartyMode(SpecialModeBase):
    mode_type = "party"
    feature_flag = "phase5.party_mode"

    DEFAULT_CONFIG = {
        "light_scene": "party",
        "temperature_offset": -1.0,
        "volume_threshold": 70,
        "volume_warning_after": "22:00",
        "auto_deactivate_min": 240,
        "cleanup_mode_enabled": True,
        "cleanup_duration_min": 30,
        "quiet_hours_override": True,
        "auto_trigger_enabled": False,
        "media_playlist": None,
        "media_volume": 0.5,
    }

    def _apply_actions(self, config):
        self._apply_entity_actions()
        logger.info("Party mode actions applied")


# ==============================================================================
# #8 Cinema Mode
# ==============================================================================

class CinemaMode(SpecialModeBase):
    mode_type = "cinema"
    feature_flag = "phase5.cinema_mode"

    DEFAULT_CONFIG = {
        "dim_brightness": 5,
        "pause_brightness": 30,
        "transition_sec": 3,
        "close_covers": True,
        "dnd_enabled": True,
        "dnd_exceptions": ["critical", "emergency"],
        "climate_quiet_mode": False,
        "auto_trigger_enabled": False,
        "auto_deactivate_pause_min": 5,
        "room_id": None,
    }

    def start(self):
        """Subscribe to media_player state changes for pause detection."""
        self.event_bus.subscribe("state.changed", self._on_media_state, priority=30)

    def stop(self):
        if self._active:
            self.deactivate(reason="shutdown")

    def _apply_actions(self, config):
        self._apply_entity_actions()
        # Close covers if configured
        if config.get("close_covers"):
            from models import FeatureEntityAssignment
            try:
                with self.get_session() as session:
                    covers = session.query(FeatureEntityAssignment).filter_by(
                        feature_key="cinema", role="cover", is_active=True
                    ).all()
                    for c in covers:
                        self.ha.call_service("cover", "close_cover", {"entity_id": c.entity_id})
            except Exception:
                pass
        logger.info("Cinema mode actions applied")

    def _on_media_state(self, event):
        """Handle media player pause/resume for lighting adjustments."""
        if not self._active:
            return
        data = event.data if hasattr(event, 'data') else (event if isinstance(event, dict) else {})
        entity_id = data.get("entity_id", "")
        if not entity_id.startswith("media_player."):
            return
        new_state = data.get("new_state") or {}
        new_val = new_state.get("state", "") if isinstance(new_state, dict) else ""
        config = self.get_config()
        # Adjust lights on pause/resume
        if new_val == "paused":
            self._set_lights_brightness(config.get("pause_brightness", 30))
        elif new_val == "playing":
            self._set_lights_brightness(config.get("dim_brightness", 5))

    def _set_lights_brightness(self, brightness):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                lights = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="cinema", role="light", is_active=True
                ).all()
                for l in lights:
                    self.ha.call_service("light", "turn_on", {
                        "entity_id": l.entity_id,
                        "brightness_pct": brightness,
                        "transition": self.get_config().get("transition_sec", 3),
                    })
        except Exception as e:
            logger.debug(f"Cinema light adjust error: {e}")


# ==============================================================================
# #9 Home-Office Mode
# ==============================================================================

class HomeOfficeMode(SpecialModeBase):
    mode_type = "home_office"
    feature_flag = "phase5.home_office_mode"

    DEFAULT_CONFIG = {
        "room_id": None,
        "focus_brightness": 85,
        "focus_color_temp": 5000,
        "comfort_temp": 21.5,
        "dnd_enabled": True,
        "dnd_exceptions": ["critical", "emergency"],
        "circadian_override": True,
        "break_reminder_enabled": True,
        "break_reminder_interval_min": 50,
        "break_reminder_message_de": "Zeit für eine Pause! Steh auf und beweg dich.",
        "break_reminder_message_en": "Time for a break! Get up and stretch.",
        "dnd_tts_enabled": False,
        "dnd_tts_message_de": "Bitte nicht stören, Home-Office aktiv.",
        "dnd_tts_message_en": "Please do not disturb, home office is active.",
        "auto_trigger_enabled": False,
        "auto_trigger_calendar_keywords": ["Home Office", "Homeoffice", "WFH"],
        "auto_deactivate_after_hours": 9.0,
    }

    def _apply_actions(self, config):
        self._apply_entity_actions()
        logger.info("Home-Office mode actions applied")


# ==============================================================================
# #10 Night Lockdown
# ==============================================================================

class NightLockdown(SpecialModeBase):
    mode_type = "night_lockdown"

    DEFAULT_CONFIG = {
        "night_temp": 18.0,
        "night_light_brightness": 5,
        "night_light_color_temp": 2700,
        "lock_doors": True,
        "turn_off_media": True,
        "window_check_enabled": True,
        "window_check_notify_only": True,
        "motion_alerts_enabled": True,
        "motion_alert_rooms": [],
        "motion_alert_notification_target": None,
        "alarm_panel_enabled": False,
        "alarm_panel_entity": None,
        "auto_trigger_enabled": True,
        "auto_trigger_time": "23:00",
        "auto_deactivate_min": None,
    }

    def start(self):
        """Subscribe to sleep detection for auto-activation."""
        self.event_bus.subscribe("sleep.detected", self._on_sleep_detected, priority=30)
        self.event_bus.subscribe("wake.detected", self._on_wake_detected, priority=30)
        if self.get_config().get("motion_alerts_enabled"):
            self.event_bus.subscribe("state.changed", self._on_motion, priority=20)

    def stop(self):
        if self._active:
            self.deactivate(reason="shutdown")

    def _apply_actions(self, config):
        self._apply_entity_actions()

        # Lock doors
        if config.get("lock_doors"):
            from models import FeatureEntityAssignment
            try:
                with self.get_session() as session:
                    locks = session.query(FeatureEntityAssignment).filter_by(
                        feature_key="night_lockdown", role="lock", is_active=True
                    ).all()
                    for l in locks:
                        self.ha.call_service("lock", "lock", {"entity_id": l.entity_id})
            except Exception:
                pass

        # Turn off media
        if config.get("turn_off_media"):
            from models import FeatureEntityAssignment
            try:
                with self.get_session() as session:
                    media = session.query(FeatureEntityAssignment).filter_by(
                        feature_key="night_lockdown", role="media", is_active=True
                    ).all()
                    for m in media:
                        self.ha.call_service("media_player", "turn_off", {"entity_id": m.entity_id})
            except Exception:
                pass

        # Window check
        if config.get("window_check_enabled"):
            self._check_open_windows(config)

        # Alarm panel
        if config.get("alarm_panel_enabled") and config.get("alarm_panel_entity"):
            try:
                self.ha.call_service("alarm_control_panel", "alarm_arm_night", {
                    "entity_id": config["alarm_panel_entity"]
                })
            except Exception as e:
                logger.debug(f"Alarm panel set error: {e}")

        logger.info("Night lockdown actions applied")

    def _check_open_windows(self, config):
        """Check for open windows and notify."""
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                sensors = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="night_lockdown", role="window_sensor", is_active=True
                ).all()
                open_windows = []
                for s in sensors:
                    state = self.ha.get_state(s.entity_id) if self.ha else None
                    if state and state.get("state") == "on":
                        name = state.get("attributes", {}).get("friendly_name", s.entity_id)
                        open_windows.append(name)
                if open_windows:
                    names = ", ".join(open_windows)
                    logger.info(f"Night lockdown: open windows detected: {names}")
                    self.event_bus.publish("night.window_open", {
                        "windows": open_windows,
                    }, source="night_lockdown")
        except Exception as e:
            logger.debug(f"Window check error: {e}")

    def _on_sleep_detected(self, event):
        """Auto-activate on sleep detection."""
        config = self.get_config()
        if config.get("auto_trigger_enabled") and not self._active:
            self.activate(reason="sleep_detected")

    def _on_wake_detected(self, event):
        """Auto-deactivate on wake detection."""
        if self._active:
            self.deactivate(reason="wake_detected")

    def _on_motion(self, event):
        """Alert on motion during night lockdown in monitored rooms."""
        if not self._active:
            return
        config = self.get_config()
        if not config.get("motion_alerts_enabled"):
            return
        data = event.data if hasattr(event, 'data') else (event if isinstance(event, dict) else {})
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state") or {}
        new_val = new_state.get("state", "") if isinstance(new_state, dict) else ""
        if new_val != "on":
            return
        attrs = new_state.get("attributes", {}) if isinstance(new_state, dict) else {}
        if attrs.get("device_class") != "motion":
            return
        # Check if this motion sensor is in a monitored room
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                assigned = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="night_lockdown", entity_id=entity_id,
                    role="motion", is_active=True
                ).first()
                if assigned:
                    logger.info(f"Night lockdown: motion detected on {entity_id}")
                    self.event_bus.publish("night.motion_alert", {
                        "entity_id": entity_id,
                    }, source="night_lockdown")
        except Exception:
            pass


# ==============================================================================
# #11 Emergency Protocol
# ==============================================================================

class EmergencyProtocol(SpecialModeBase):
    mode_type = "emergency"
    feature_flag = "phase5.emergency_protocol"

    DEFAULT_CONFIG = {
        "escalation_step1_delay_sec": 30,
        "escalation_step2_delay_sec": 60,
        "escalation_step3_delay_sec": 300,
        "siren_duration_sec": 300,
        "tts_volume": 100,
        "tts_message_fire_de": "Achtung! Feueralarm! Bitte das Gebäude sofort verlassen!",
        "tts_message_fire_en": "Attention! Fire alarm! Please evacuate the building immediately!",
        "tts_message_medical_de": "Medizinischer Notfall! Hilfe ist unterwegs.",
        "tts_message_medical_en": "Medical emergency! Help is on the way.",
        "tts_message_panic_de": "Alarm! Alarm!",
        "tts_message_panic_en": "Alarm! Alarm!",
        "cancel_requires_pin": True,
        "notify_emergency_contacts": True,
        "fire_actions": {"lights": True, "covers": "open", "hvac": "off", "locks": "unlock"},
        "medical_actions": {"lights": True, "locks": "unlock_front"},
        "panic_actions": {"lights": True, "siren": True, "locks": "lock"},
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        super().__init__(ha_connection, db_session_factory, event_bus)
        self._emergency_type = None
        self._escalation_timers = []

    def start(self):
        self.event_bus.subscribe("emergency.*", self._on_emergency_event, priority=10)
        logger.info("EmergencyProtocol started")

    def stop(self):
        self._cancel_escalation()
        if self._active:
            self.deactivate(reason="shutdown")
        logger.info("EmergencyProtocol stopped")

    def trigger(self, emergency_type="panic", source="manual", user_id=None):
        """Trigger emergency protocol with escalation chain."""
        from routes.security import is_phase5_feature_enabled
        if not is_phase5_feature_enabled("phase5.emergency_protocol"):
            return False

        self._emergency_type = emergency_type
        config = self.get_config()

        # Activate mode (snapshot + log)
        self.activate(user_id=user_id, reason=f"emergency_{emergency_type}")

        # Step 1: Immediate actions
        self._execute_immediate_actions(emergency_type, config)

        # Step 2-4: Escalation chain via timers
        self._start_escalation(config)

        # Log security event
        self._log_emergency_event(emergency_type, source)

        return True

    def cancel(self, pin=None, user_id=None):
        """Cancel active emergency."""
        if not self._active:
            return False

        config = self.get_config()
        if config.get("cancel_requires_pin") and pin:
            # Verify PIN against user
            if not self._verify_pin(pin, user_id):
                return False

        self._cancel_escalation()
        self.deactivate(user_id=user_id, reason="cancelled")
        self._emergency_type = None
        return True

    def get_status(self):
        status = super().get_status()
        status["emergency_type"] = self._emergency_type
        return status

    # ── Internal ────────────────────────────────────────────

    def _on_emergency_event(self, event):
        """React to emergency events from other engines (e.g., fire_water)."""
        if self._active:
            return  # Already in emergency mode
        event_type = event.event_type if hasattr(event, 'event_type') else ""
        data = event.data if hasattr(event, 'data') else (event if isinstance(event, dict) else {})
        alarm_type = data.get("alarm_type", "")
        # Only react to actual alarm events, not our own escalation events
        if event_type in ("emergency.notify_users", "emergency.notify_contacts"):
            return
        if alarm_type == "fire" or event_type == "emergency.fire":
            self.trigger("fire", source="fire_water")
        elif alarm_type == "co" or event_type == "emergency.co":
            self.trigger("co", source="fire_water")
        elif event_type == "emergency.water_leak":
            self.trigger("panic", source="water_leak")

    def _execute_immediate_actions(self, emergency_type, config):
        """Execute type-specific immediate actions."""
        actions = config.get(f"{emergency_type}_actions", {})

        # Lights on
        if actions.get("lights"):
            self._all_lights_on()

        # Covers
        cover_action = actions.get("covers")
        if cover_action == "open":
            self._all_covers_open()

        # HVAC
        hvac_action = actions.get("hvac")
        if hvac_action == "off":
            self._all_hvac_off()

        # Locks
        lock_action = actions.get("locks")
        if lock_action == "unlock":
            self._all_locks_unlock()
        elif lock_action == "lock":
            self._all_locks_lock()

        # Siren
        if actions.get("siren"):
            self._activate_siren(config)

        # TTS
        lang_key = f"tts_message_{emergency_type}_de"
        message = config.get(lang_key, "Alarm!")
        self._tts_announce(message, config)

    def _start_escalation(self, config):
        """Start escalation chain with timed steps."""
        self._cancel_escalation()

        # Step 2: Push notification to all users
        t1 = threading.Timer(
            config.get("escalation_step1_delay_sec", 30),
            self._escalation_step_notify_users,
        )
        t1.daemon = True
        t1.start()
        self._escalation_timers.append(t1)

        # Step 3: Notify emergency contacts
        if config.get("notify_emergency_contacts"):
            t2 = threading.Timer(
                config.get("escalation_step2_delay_sec", 60),
                self._escalation_step_notify_contacts,
            )
            t2.daemon = True
            t2.start()
            self._escalation_timers.append(t2)

            # Step 4: Second notification to contacts
            t3 = threading.Timer(
                config.get("escalation_step3_delay_sec", 300),
                self._escalation_step_notify_contacts,
            )
            t3.daemon = True
            t3.start()
            self._escalation_timers.append(t3)

    def _cancel_escalation(self):
        for t in self._escalation_timers:
            t.cancel()
        self._escalation_timers.clear()

    def _escalation_step_notify_users(self):
        """Escalation: notify all users via push."""
        logger.info("Emergency escalation: notifying all users")
        self.event_bus.publish("emergency.notify_users", {
            "type": self._emergency_type,
        }, source="emergency_protocol")

    def _escalation_step_notify_contacts(self):
        """Escalation: notify emergency contacts from DB."""
        logger.info("Emergency escalation: notifying emergency contacts")
        try:
            from models import EmergencyContact, NotificationLog, NotificationType
            with self.get_session() as session:
                contacts = session.query(EmergencyContact).filter_by(
                    is_active=True
                ).order_by(EmergencyContact.priority).all()
                for contact in contacts:
                    session.add(NotificationLog(
                        notification_type=NotificationType.CRITICAL,
                        title="NOTFALL / EMERGENCY",
                        message=f"Emergency ({self._emergency_type}). Contact: {contact.name}, Phone: {contact.phone or 'N/A'}",
                        was_sent=True,
                        user_id=contact.user_id if hasattr(contact, 'user_id') else 1,
                    ))
                    try:
                        self.ha.call_service("notify", "persistent_notification", {
                            "title": f"NOTFALL: {contact.name}",
                            "message": f"Emergency type: {self._emergency_type}. Contact {contact.name} at {contact.phone or contact.email or 'N/A'}",
                        })
                    except Exception:
                        pass
                logger.info(f"Notified {len(contacts)} emergency contacts")
        except Exception as e:
            logger.error(f"Emergency contact notification error: {e}")
        self.event_bus.publish("emergency.notify_contacts", {
            "type": self._emergency_type,
        }, source="emergency_protocol")

    def _all_lights_on(self):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                lights = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="light", is_active=True
                ).all()
                for l in lights:
                    self.ha.call_service("light", "turn_on", {
                        "entity_id": l.entity_id, "brightness_pct": 100
                    })
        except Exception as e:
            logger.error(f"Emergency lights error: {e}")

    def _all_covers_open(self):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                covers = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="cover", is_active=True
                ).all()
                for c in covers:
                    self.ha.call_service("cover", "open_cover", {"entity_id": c.entity_id})
        except Exception as e:
            logger.error(f"Emergency covers error: {e}")

    def _all_hvac_off(self):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                hvacs = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="hvac", is_active=True
                ).all()
                for h in hvacs:
                    self.ha.call_service("climate", "turn_off", {"entity_id": h.entity_id})
        except Exception as e:
            logger.error(f"Emergency HVAC error: {e}")

    def _all_locks_unlock(self):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                locks = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="lock", is_active=True
                ).all()
                for l in locks:
                    self.ha.call_service("lock", "unlock", {"entity_id": l.entity_id})
        except Exception as e:
            logger.error(f"Emergency locks unlock error: {e}")

    def _all_locks_lock(self):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                locks = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="lock", is_active=True
                ).all()
                for l in locks:
                    self.ha.call_service("lock", "lock", {"entity_id": l.entity_id})
        except Exception as e:
            logger.error(f"Emergency locks lock error: {e}")

    def _activate_siren(self, config):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                sirens = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="siren", is_active=True
                ).all()
                for s in sirens:
                    self.ha.call_service("siren", "turn_on", {
                        "entity_id": s.entity_id,
                        "duration": config.get("siren_duration_sec", 300),
                    })
        except Exception as e:
            logger.error(f"Siren activation error: {e}")

    def _tts_announce(self, message, config):
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                speakers = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="emergency", role="tts_speaker", is_active=True
                ).all()
                vol = config.get("tts_volume", 100) / 100.0
                for s in speakers:
                    try:
                        self.ha.call_service("media_player", "volume_set", {
                            "entity_id": s.entity_id, "volume_level": vol
                        })
                    except Exception:
                        pass
                    self.ha.call_service("tts", "speak", {
                        "entity_id": s.entity_id, "message": message
                    })
        except Exception as e:
            logger.error(f"TTS announce error: {e}")

    def _log_emergency_event(self, emergency_type, source):
        try:
            from models import SecurityEvent, SecurityEventType, SecuritySeverity
            etype = SecurityEventType.EMERGENCY
            if emergency_type == "fire":
                etype = SecurityEventType.FIRE
            elif emergency_type == "panic":
                etype = SecurityEventType.PANIC
            with self.get_session() as session:
                session.add(SecurityEvent(
                    event_type=etype,
                    severity=SecuritySeverity.EMERGENCY,
                    message_de=f"Notfall-Protokoll ausgelöst: {emergency_type}",
                    message_en=f"Emergency protocol triggered: {emergency_type}",
                    context={"type": emergency_type, "source": source},
                ))
        except Exception as e:
            logger.error(f"Emergency event log error: {e}")

    def _verify_pin(self, pin, user_id):
        """Verify user PIN for emergency cancellation."""
        if not user_id or not pin:
            return False
        try:
            from models import User
            with self.get_session() as session:
                user = session.query(User).get(user_id)
                if user and hasattr(user, 'pin_hash') and user.pin_hash:
                    import hashlib
                    return user.pin_hash == hashlib.sha256(str(pin).encode()).hexdigest()
        except Exception:
            pass
        return False
