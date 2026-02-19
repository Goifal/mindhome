# MindHome - engines/fire_water.py | see version.py for version info
"""
Fire/CO alarm response and water leak detection.
Features: #1 Rauch-/CO-Melder-Reaktion, #2 Wassermelder-Reaktion
Event-based: reacts immediately to state_changed events.
"""

import logging
import json
from datetime import datetime, timezone

logger = logging.getLogger("mindhome.engines.fire_water")


class FireResponseManager:
    """Automatic response to fire/smoke/CO alarm events.

    Subscribes to state.changed events for smoke/co binary_sensors.
    On alarm:
      - Log SecurityEvent (severity=EMERGENCY)
      - Lights 100% (escape routes)
      - Covers open (escape routes)
      - HVAC off (fire) / HVAC on (CO)
      - Notification CRITICAL to all users + emergency contacts
      - TTS announcement
      - Optional: unlock doors
    """

    DEFAULT_CONFIG = {
        "unlock_on_fire": True,
        "stop_hvac_on_fire": True,
        "start_hvac_on_co": True,
        "tts_message_fire_de": "Achtung! Feueralarm! Bitte das Gebaeude verlassen!",
        "tts_message_fire_en": "Attention! Fire alarm! Please evacuate the building!",
        "tts_message_co_de": "Achtung! CO-Alarm! Fenster oeffnen und Gebaeude verlassen!",
        "tts_message_co_en": "Attention! CO alarm! Open windows and evacuate the building!",
        "tts_volume": 100,
        "notification_users": [],
        "notify_emergency_contacts": True,
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_alarms = {}  # entity_id -> alarm_type

    def start(self):
        self._is_running = True
        self.event_bus.subscribe("state.changed", self._on_state_changed, priority=100)
        logger.info("FireResponseManager started")

    def stop(self):
        self._is_running = False
        logger.info("FireResponseManager stopped")

    def get_config(self):
        """Get fire/CO response configuration."""
        from helpers import get_setting
        config = dict(self.DEFAULT_CONFIG)
        stored = get_setting("phase5.fire_co_config")
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        """Update fire/CO response configuration."""
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting("phase5.fire_co_config", json.dumps(config))
        return config

    def get_status(self):
        """Get current sensor status for all fire/CO sensors."""
        from models import FeatureEntityAssignment
        sensors = []
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="fire_co", role="trigger", is_active=True
                ).order_by(FeatureEntityAssignment.sort_order).all()

                for a in assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    sensor_state = "unknown"
                    device_class = ""
                    if state:
                        sensor_state = state.get("state", "unknown")
                        device_class = state.get("attributes", {}).get("device_class", "")

                    alarm_active = a.entity_id in self._active_alarms
                    sensors.append({
                        "entity_id": a.entity_id,
                        "state": sensor_state,
                        "device_class": device_class,
                        "alarm_active": alarm_active,
                        "alarm_type": self._active_alarms.get(a.entity_id),
                    })
        except Exception as e:
            logger.error(f"Error getting fire/CO status: {e}")

        return {
            "sensors": sensors,
            "active_alarms": len(self._active_alarms),
            "is_running": self._is_running,
        }

    def _on_state_changed(self, event):
        """Handle state change events — check for fire/CO triggers."""
        if not self._is_running:
            return

        from routes.security import is_phase5_feature_enabled
        if not is_phase5_feature_enabled("phase5.fire_co_response"):
            return

        data = event.data if hasattr(event, 'data') else event
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state", {})
        if isinstance(new_state, dict):
            state_val = new_state.get("state", "")
            attrs = new_state.get("attributes", {})
        else:
            return

        device_class = attrs.get("device_class", "")

        # Only respond to smoke/gas/co binary_sensors
        if not entity_id.startswith("binary_sensor."):
            return
        if device_class not in ("smoke", "gas", "co", "carbon_monoxide"):
            return

        # Check if this entity is assigned to fire_co feature
        if not self._is_assigned_entity(entity_id, "fire_co", "trigger"):
            return

        if state_val == "on":
            # ALARM triggered
            alarm_type = "co" if device_class in ("gas", "co", "carbon_monoxide") else "fire"
            if entity_id not in self._active_alarms:
                self._active_alarms[entity_id] = alarm_type
                self._handle_alarm(entity_id, alarm_type)
        elif state_val == "off":
            # Alarm cleared
            if entity_id in self._active_alarms:
                self._handle_alarm_cleared(entity_id)
                del self._active_alarms[entity_id]

    def _is_assigned_entity(self, entity_id, feature_key, role):
        """Check if entity is assigned to feature with given role."""
        try:
            from models import FeatureEntityAssignment
            with self.get_session() as session:
                return session.query(FeatureEntityAssignment).filter_by(
                    feature_key=feature_key, entity_id=entity_id,
                    role=role, is_active=True
                ).first() is not None
        except Exception:
            return False

    def _handle_alarm(self, entity_id, alarm_type):
        """Execute emergency response for fire or CO alarm."""
        logger.warning(f"{'FIRE' if alarm_type == 'fire' else 'CO'} ALARM from {entity_id}")
        config = self.get_config()

        # 1. Log SecurityEvent
        self._log_security_event(
            event_type="FIRE" if alarm_type == "fire" else "CO",
            severity="EMERGENCY",
            message_de=f"{'Feueralarm' if alarm_type == 'fire' else 'CO-Alarm'} ausgeloest von {entity_id}",
            message_en=f"{'Fire alarm' if alarm_type == 'fire' else 'CO alarm'} triggered by {entity_id}",
            entity_id=entity_id,
        )

        # 2. Lights to 100% (emergency lighting)
        from helpers import get_setting
        brightness = int(get_setting("phase5.fire_co.emergency_brightness_pct", "100") or "100")
        brightness_val = int(brightness * 2.55)
        self._activate_entities("fire_co", "emergency_light", "light", "turn_on", {"brightness": brightness_val})

        # 3. Covers open (escape routes)
        self._activate_entities("fire_co", "emergency_cover", "cover", "open_cover")

        # 4. HVAC control
        if alarm_type == "fire" and config.get("stop_hvac_on_fire", True):
            self._activate_entities("fire_co", "hvac", "climate", "turn_off")
            self._activate_entities("fire_co", "hvac", "fan", "turn_off")
        elif alarm_type == "co" and config.get("start_hvac_on_co", True):
            self._activate_entities("fire_co", "hvac", "fan", "turn_on")

        # 5. Unlock doors (escape routes)
        if config.get("unlock_on_fire", True):
            self._activate_entities("fire_co", "emergency_lock", "lock", "unlock")

        # 6. TTS announcement
        lang_key = f"tts_message_{alarm_type}_de"
        tts_msg = config.get(lang_key, self.DEFAULT_CONFIG[lang_key])
        tts_volume = config.get("tts_volume", 100) / 100.0
        self._send_tts("fire_co", tts_msg, tts_volume)

        # 7. Notification
        self._send_emergency_notification(alarm_type, entity_id, config)

        # 8. Emit event for other systems (camera snapshots, emergency protocol)
        self.event_bus.publish(f"emergency.{alarm_type}", {
            "entity_id": entity_id,
            "alarm_type": alarm_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, source="fire_response")

    def _handle_alarm_cleared(self, entity_id):
        """Handle alarm being cleared."""
        alarm_type = self._active_alarms.get(entity_id, "fire")
        logger.info(f"Alarm cleared: {entity_id} (was {alarm_type})")

        self._log_security_event(
            event_type="FIRE" if alarm_type == "fire" else "CO",
            severity="INFO",
            message_de=f"{'Feueralarm' if alarm_type == 'fire' else 'CO-Alarm'} aufgehoben: {entity_id}",
            message_en=f"{'Fire alarm' if alarm_type == 'fire' else 'CO alarm'} cleared: {entity_id}",
            entity_id=entity_id,
            resolved=True,
        )

    def _activate_entities(self, feature_key, role, domain, service, data=None):
        """Activate all entities assigned with given role."""
        try:
            from models import FeatureEntityAssignment
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key=feature_key, role=role, is_active=True
                ).all()
                for a in assignments:
                    try:
                        full_service = f"{domain}.{service}"
                        service_data = {"entity_id": a.entity_id}
                        if data:
                            service_data.update(data)
                        # Merge role-specific config
                        if a.config:
                            role_config = a.config if isinstance(a.config, dict) else json.loads(a.config)
                            service_data.update(role_config)
                        self.ha.call_service(domain, service, service_data)
                        logger.info(f"Emergency action: {full_service} on {a.entity_id}")
                    except Exception as e:
                        logger.error(f"Emergency action failed for {a.entity_id}: {e}")
        except Exception as e:
            logger.error(f"Error activating entities {feature_key}/{role}: {e}")

    def _send_tts(self, feature_key, message, volume=1.0):
        """Send TTS announcement to all assigned speakers."""
        try:
            from models import FeatureEntityAssignment
            with self.get_session() as session:
                speakers = session.query(FeatureEntityAssignment).filter_by(
                    feature_key=feature_key, role="tts_speaker", is_active=True
                ).all()
                for s in speakers:
                    try:
                        self.ha.call_service("tts", "speak", {
                            "entity_id": s.entity_id,
                            "message": message,
                            "cache": False,
                        })
                    except Exception as e:
                        logger.error(f"TTS failed for {s.entity_id}: {e}")
        except Exception as e:
            logger.error(f"TTS error: {e}")

    def _send_emergency_notification(self, alarm_type, entity_id, config):
        """Send emergency notifications to configured users."""
        try:
            from models import NotificationLog, NotificationType, User, SecurityEvent
            title = "FEUERALARM!" if alarm_type == "fire" else "CO-ALARM!"
            msg = f"{'Feuer' if alarm_type == 'fire' else 'CO'}-Alarm ausgeloest von {entity_id}"

            with self.get_session() as session:
                users = session.query(User).filter_by(is_active=True).all()
                for user in users:
                    log = NotificationLog(
                        user_id=user.id,
                        notification_type=NotificationType.CRITICAL,
                        title=title,
                        message=msg,
                        was_sent=True,
                    )
                    session.add(log)

                # Send via HA notification
                try:
                    self.ha.call_service("notify", "persistent_notification", {
                        "title": title,
                        "message": msg,
                    })
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Emergency notification error: {e}")

    def _log_security_event(self, event_type, severity, message_de, message_en,
                            entity_id=None, resolved=False):
        """Log a security event to the database."""
        try:
            from models import SecurityEvent, SecurityEventType, SecuritySeverity
            with self.get_session() as session:
                evt = SecurityEvent(
                    event_type=SecurityEventType[event_type],
                    severity=SecuritySeverity[severity],
                    message_de=message_de,
                    message_en=message_en,
                    context={"entity_id": entity_id} if entity_id else None,
                )
                if resolved:
                    evt.resolved_at = datetime.now(timezone.utc)
                    evt.resolved_by = None
                session.add(evt)
        except Exception as e:
            logger.error(f"Security event log error: {e}")


class WaterLeakManager:
    """Automatic response to water leak / moisture sensor events.

    Subscribes to state.changed events for moisture binary_sensors.
    On detection:
      - Log SecurityEvent (severity=CRITICAL)
      - Close main water valve (if configured)
      - Notification CRITICAL to admins
      - Identify affected room
      - Optional: shut off heating in room (frost protection!)
    """

    DEFAULT_CONFIG = {
        "auto_shutoff": True,
        "frost_protection_temp": 5.0,
        "shutoff_heating_on_leak": True,
        "notification_users": [],
        "tts_enabled": False,
        "tts_message_de": "Achtung! Wasserleck erkannt!",
        "tts_message_en": "Attention! Water leak detected!",
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._active_leaks = {}  # entity_id -> timestamp

    def start(self):
        self._is_running = True
        self.event_bus.subscribe("state.changed", self._on_state_changed, priority=99)
        logger.info("WaterLeakManager started")

    def stop(self):
        self._is_running = False
        logger.info("WaterLeakManager stopped")

    def get_config(self):
        """Get water leak response configuration."""
        from helpers import get_setting
        config = dict(self.DEFAULT_CONFIG)
        stored = get_setting("phase5.water_leak_config")
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        """Update water leak response configuration."""
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting("phase5.water_leak_config", json.dumps(config))
        return config

    def get_status(self):
        """Get current moisture sensor + valve status."""
        from models import FeatureEntityAssignment
        sensors = []
        valves = []
        try:
            with self.get_session() as session:
                # Moisture sensors
                sensor_assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="water_leak", role="trigger", is_active=True
                ).order_by(FeatureEntityAssignment.sort_order).all()
                for a in sensor_assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    sensors.append({
                        "entity_id": a.entity_id,
                        "state": state.get("state", "unknown") if state else "unknown",
                        "leak_active": a.entity_id in self._active_leaks,
                    })

                # Valves
                valve_assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="water_leak", role="valve", is_active=True
                ).all()
                for a in valve_assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    valves.append({
                        "entity_id": a.entity_id,
                        "state": state.get("state", "unknown") if state else "unknown",
                    })
        except Exception as e:
            logger.error(f"Error getting water leak status: {e}")

        return {
            "sensors": sensors,
            "valves": valves,
            "active_leaks": len(self._active_leaks),
            "is_running": self._is_running,
        }

    def _on_state_changed(self, event):
        """Handle state change events — check for water leak triggers."""
        if not self._is_running:
            return

        from routes.security import is_phase5_feature_enabled
        if not is_phase5_feature_enabled("phase5.water_leak_response"):
            return

        data = event.data if hasattr(event, 'data') else event
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state", {})
        if isinstance(new_state, dict):
            state_val = new_state.get("state", "")
            attrs = new_state.get("attributes", {})
        else:
            return

        device_class = attrs.get("device_class", "")

        if not entity_id.startswith("binary_sensor."):
            return
        if device_class != "moisture":
            return
        if not self._is_assigned_entity(entity_id, "water_leak", "trigger"):
            return

        if state_val == "on":
            if entity_id not in self._active_leaks:
                self._active_leaks[entity_id] = datetime.now(timezone.utc).isoformat()
                self._handle_leak(entity_id)
        elif state_val == "off":
            if entity_id in self._active_leaks:
                self._handle_leak_cleared(entity_id)
                del self._active_leaks[entity_id]

    def _is_assigned_entity(self, entity_id, feature_key, role):
        """Check if entity is assigned to feature."""
        try:
            from models import FeatureEntityAssignment
            with self.get_session() as session:
                return session.query(FeatureEntityAssignment).filter_by(
                    feature_key=feature_key, entity_id=entity_id,
                    role=role, is_active=True
                ).first() is not None
        except Exception:
            return False

    def _handle_leak(self, entity_id):
        """Execute water leak response actions."""
        logger.warning(f"WATER LEAK detected: {entity_id}")
        config = self.get_config()

        # 1. Log SecurityEvent
        try:
            from models import SecurityEvent, SecurityEventType, SecuritySeverity
            with self.get_session() as session:
                evt = SecurityEvent(
                    event_type=SecurityEventType.WATER_LEAK,
                    severity=SecuritySeverity.CRITICAL,
                    message_de=f"Wasserleck erkannt: {entity_id}",
                    message_en=f"Water leak detected: {entity_id}",
                    context={"entity_id": entity_id},
                )
                session.add(evt)
        except Exception as e:
            logger.error(f"Security event log error: {e}")

        # 2. Close water valve
        if config.get("auto_shutoff", True):
            self._activate_valve_close()

        # 3. Shut off heating in affected room (with frost protection)
        if config.get("shutoff_heating_on_leak", True):
            self._shutoff_heating(entity_id, config.get("frost_protection_temp", 5.0))

        # 4. Notification
        self._send_leak_notification(entity_id)

        # 5. TTS (optional)
        if config.get("tts_enabled", False):
            tts_msg = config.get("tts_message_de", self.DEFAULT_CONFIG["tts_message_de"])
            try:
                from models import FeatureEntityAssignment
                with self.get_session() as session:
                    speakers = session.query(FeatureEntityAssignment).filter_by(
                        feature_key="water_leak", role="tts_speaker", is_active=True
                    ).all()
                    for s in speakers:
                        try:
                            self.ha.call_service("tts", "speak", {
                                "entity_id": s.entity_id,
                                "message": tts_msg,
                            })
                        except Exception:
                            pass
            except Exception:
                pass

        # 6. Emit event
        self.event_bus.publish("emergency.water_leak", {
            "entity_id": entity_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, source="water_leak")

    def _handle_leak_cleared(self, entity_id):
        """Handle leak being cleared."""
        logger.info(f"Water leak cleared: {entity_id}")
        try:
            from models import SecurityEvent, SecurityEventType, SecuritySeverity
            with self.get_session() as session:
                evt = SecurityEvent(
                    event_type=SecurityEventType.WATER_LEAK,
                    severity=SecuritySeverity.INFO,
                    message_de=f"Wasserleck aufgehoben: {entity_id}",
                    message_en=f"Water leak cleared: {entity_id}",
                    context={"entity_id": entity_id},
                    resolved_at=datetime.now(timezone.utc),
                    resolved_by=None,
                )
                session.add(evt)
        except Exception as e:
            logger.error(f"Security event log error: {e}")

    def _activate_valve_close(self):
        """Close all assigned water valves."""
        try:
            from models import FeatureEntityAssignment
            with self.get_session() as session:
                valves = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="water_leak", role="valve", is_active=True
                ).all()
                for v in valves:
                    try:
                        domain = v.entity_id.split(".")[0]
                        service = "close_valve" if domain == "valve" else "turn_off"
                        self.ha.call_service(domain, service, {"entity_id": v.entity_id})
                        logger.info(f"Water valve closed: {v.entity_id}")
                    except Exception as e:
                        logger.error(f"Valve close failed for {v.entity_id}: {e}")
        except Exception as e:
            logger.error(f"Valve activation error: {e}")

    def _shutoff_heating(self, leak_entity_id, frost_temp):
        """Shut off heating in the room where the leak was detected."""
        try:
            from models import FeatureEntityAssignment, Device
            from helpers import get_setting
            heating_mode = get_setting("heating_mode", "room_thermostat")

            with self.get_session() as session:
                # Find room of leak sensor
                leak_device = session.query(Device).filter_by(ha_entity_id=leak_entity_id).first()
                if not leak_device or not leak_device.room_id:
                    return

                if heating_mode == "heating_curve":
                    # Heizkurven-Modus: Offset auf Minimum setzen
                    curve_entity = get_setting("heating_curve_entity", "")
                    offset_min = float(get_setting("heating_curve_offset_min", "-5"))
                    if curve_entity:
                        try:
                            states = self.ha.get_states() or []
                            for s in states:
                                if s.get("entity_id") == curve_entity:
                                    current = s.get("attributes", {}).get("temperature")
                                    if current is not None:
                                        base_temp = float(current)
                                        new_temp = base_temp + offset_min
                                        self.ha.call_service("climate", "set_temperature", {
                                            "entity_id": curve_entity,
                                            "temperature": round(new_temp, 1),
                                        })
                                        logger.info(f"Heating curve set to min offset ({offset_min}): {curve_entity}")
                                    break
                        except Exception as e:
                            logger.error(f"Heating curve shutoff failed: {e}")
                else:
                    # Raumthermostat-Modus: Frostschutz-Temperatur setzen
                    heating = session.query(FeatureEntityAssignment).filter_by(
                        feature_key="water_leak", role="heating", is_active=True
                    ).all()
                    for h in heating:
                        try:
                            self.ha.call_service("climate", "set_temperature", {
                                "entity_id": h.entity_id,
                                "temperature": frost_temp,
                            })
                            logger.info(f"Heating set to frost protection ({frost_temp}C): {h.entity_id}")
                        except Exception as e:
                            logger.error(f"Heating shutoff failed for {h.entity_id}: {e}")
        except Exception as e:
            logger.error(f"Heating shutoff error: {e}")

    def _send_leak_notification(self, entity_id):
        """Send water leak notifications."""
        try:
            from models import NotificationLog, NotificationType, User
            with self.get_session() as session:
                admins = session.query(User).filter_by(is_active=True).all()
                for user in admins:
                    log = NotificationLog(
                        user_id=user.id,
                        notification_type=NotificationType.CRITICAL,
                        title="WASSERLECK!",
                        message=f"Wasserleck erkannt: {entity_id}. Ventil wurde geschlossen.",
                        was_sent=True,
                    )
                    session.add(log)
                try:
                    self.ha.call_service("notify", "persistent_notification", {
                        "title": "WASSERLECK!",
                        "message": f"Wasserleck erkannt: {entity_id}",
                    })
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Leak notification error: {e}")
