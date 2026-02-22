# MindHome - engines/cover_control.py | see version.py for version info
"""
Intelligent cover/shutter/blind control engine.
Features: Zeitplan, Sonnenschutz, Wetterschutz, Anwesenheitssimulation,
          Komfort-Integration, Lernfunktion, Gruppen & Szenen.
"""

import logging
import json
import math
import random
from datetime import datetime, timezone, timedelta, time as dtime

from cover_helpers import (
    is_bed_occupied as _check_bed_occupied,
    is_garage_or_gate_by_entity_id,
    is_unsafe_device_class,
    is_unsafe_cover_type,
    UNSAFE_COVER_TYPES as _UNSAFE_COVER_TYPES,
    UNSAFE_DEVICE_CLASSES as _UNSAFE_DEVICE_CLASSES,
)

logger = logging.getLogger("mindhome.engines.cover_control")

# Priority levels (higher = more important)
PRIORITY_SCHEDULE = 10
PRIORITY_ENERGY = 20
PRIORITY_COMFORT = 30
PRIORITY_WEATHER = 40
PRIORITY_SECURITY = 50


class CoverControlManager:
    """Smart cover/shutter management with multi-source automation.

    Entity Roles (via FeatureEntityAssignment, feature_key='cover_control'):
      - cover: cover.* entities (shutters, blinds, awnings)
      - sun_sensor: sensor.* (illuminance/solar sensors)
      - temp_outdoor: sensor.* (outdoor temperature)
      - temp_indoor: sensor.* (per-room indoor temperature)
      - wind_sensor: sensor.* (wind speed)
      - rain_sensor: binary_sensor.* (rain detection)
    """

    DEFAULT_CONFIG = {
        # Sonnenschutz
        "sun_protection_enabled": True,
        "sun_protection_outdoor_temp_c": 25.0,
        "sun_protection_indoor_temp_c": 24.0,
        "sun_protection_position_pct": 20,
        "sun_protection_tilt_deg": None,
        # Winter-Logik: Sonne reinlassen für passive Wärme
        "winter_solar_gain_enabled": True,
        "winter_solar_gain_below_c": 18.0,
        # Wetterschutz
        "weather_protection_enabled": True,
        "wind_threshold_kmh": 50.0,
        "storm_retract_awnings": True,
        "rain_close_roof_windows": True,
        "frost_insulation_enabled": True,
        "frost_threshold_c": 0.0,
        # Dämmerung / Privacy
        "privacy_mode_enabled": True,
        "privacy_close_at_dusk": True,
        "privacy_sun_elevation_deg": -3.0,
        # Anwesenheitssimulation
        "presence_simulation_enabled": True,
        "simulation_start_hour": 17,
        "simulation_end_hour": 23,
        "simulation_interval_min": 45,
        "simulation_variance_min": 20,
        # Komfort
        "wakeup_integration_enabled": True,
        "wakeup_open_speed_sec": 300,
        "sleep_close_enabled": True,
        "ventilation_position_pct": 50,
        # Manueller Override
        "manual_override_duration_min": 120,
        # Prioritäten (1=höchste, 5=niedrigste)
        "priority_order": ["security", "weather", "comfort", "energy", "schedule"],
        # Lernfunktion
        "learning_enabled": True,
    }

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._manual_overrides = {}  # entity_id -> override_until (datetime)
        self._last_simulation = {}  # entity_id -> last_sim_time
        self._pending_actions = {}  # entity_id -> {priority, position, source}
        self._executed_schedules = {}  # schedule_id -> last_exec_date (to prevent double-fire)

    def start(self):
        self._is_running = True
        self.event_bus.subscribe("state.changed", self._on_state_changed, priority=30)
        self.event_bus.subscribe("sleep.detected", self._on_sleep_detected, priority=30)
        self.event_bus.subscribe("sleep.wake_detected", self._on_wake_detected, priority=30)
        self.event_bus.subscribe("weather.alert_created", self._on_weather_alert, priority=80)
        self.event_bus.subscribe("presence.mode_changed", self._on_presence_changed, priority=30)
        logger.info("CoverControlManager started")

    def stop(self):
        self._is_running = False
        self._manual_overrides.clear()
        self._pending_actions.clear()
        logger.info("CoverControlManager stopped")

    # ── Config ──────────────────────────────────────────────

    def get_config(self):
        from helpers import get_setting
        config = dict(self.DEFAULT_CONFIG)
        stored = get_setting("phase5.cover_control_config")
        if stored:
            try:
                config.update(json.loads(stored))
            except (json.JSONDecodeError, TypeError):
                pass
        return config

    def set_config(self, new_config):
        from helpers import set_setting
        config = self.get_config()
        config.update(new_config)
        set_setting("phase5.cover_control_config", json.dumps(config))
        return config

    # ── Cover Status ────────────────────────────────────────

    def get_covers(self):
        """Get all configured cover entities with current status + config."""
        from models import FeatureEntityAssignment
        covers = []
        try:
            with self.get_session() as session:
                assignments = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="cover_control", role="cover", is_active=True
                ).order_by(FeatureEntityAssignment.sort_order).all()
                for a in assignments:
                    state = self.ha.get_state(a.entity_id) if self.ha else None
                    attrs = state.get("attributes", {}) if state else {}
                    cover_conf = self._get_cover_config(session, a.entity_id)
                    override = self._manual_overrides.get(a.entity_id)
                    covers.append({
                        "entity_id": a.entity_id,
                        "state": state.get("state", "unknown") if state else "unknown",
                        "position": attrs.get("current_position"),
                        "tilt": attrs.get("current_tilt_position"),
                        "name": attrs.get("friendly_name", a.entity_id),
                        "device_class": attrs.get("device_class", "shutter"),
                        "facade": cover_conf.get("facade"),
                        "floor": cover_conf.get("floor"),
                        "cover_type": cover_conf.get("cover_type", "shutter"),
                        "group_ids": cover_conf.get("group_ids", []),
                        "manual_override_until": override.isoformat() if override else None,
                    })
        except Exception as e:
            logger.error(f"Error getting covers: {e}")
        return covers

    def get_status(self):
        """Get overall cover system status."""
        covers = self.get_covers()
        config = self.get_config()
        return {
            "covers": covers,
            "total": len(covers),
            "open": sum(1 for c in covers if c["state"] == "open"),
            "closed": sum(1 for c in covers if c["state"] == "closed"),
            "overridden": sum(1 for c in covers if c["manual_override_until"]),
            "config": config,
            "is_running": self._is_running,
        }

    # ── Cover Control ───────────────────────────────────────

    def _is_garage_or_gate(self, entity_id):
        """Prueft ob ein Cover ein Garagentor/Tor ist (DARF NICHT automatisch gesteuert werden)."""
        # 1. Entity-Name Heuristik (shared helper)
        if is_garage_or_gate_by_entity_id(entity_id):
            return True
        # 2. HA device_class
        if self.ha:
            state = self.ha.get_state(entity_id)
            if state and isinstance(state, dict):
                device_class = state.get("attributes", {}).get("device_class", "")
                if is_unsafe_device_class(device_class):
                    return True
        # 3. MindHome CoverConfig cover_type
        try:
            with self.get_session() as session:
                conf = self._get_cover_config(session, entity_id)
                if is_unsafe_cover_type(conf.get("cover_type")):
                    return True
        except Exception:
            logger.warning("DB-Fehler bei Garagentor-Check fuer %s — blockiere sicherheitshalber", entity_id)
            return True  # Fail-safe: bei DB-Fehler als unsicher behandeln
        return False

    def _is_cover_enabled(self, entity_id) -> bool:
        """Prueft ob ein Cover in der UI als aktiviert markiert ist."""
        try:
            with self.get_session() as session:
                conf = self._get_cover_config(session, entity_id)
                return conf.get("enabled", True)
        except Exception:
            logger.warning("DB-Fehler bei enabled-Check fuer %s — blockiere sicherheitshalber", entity_id)
            return False  # Fail-safe: bei DB-Fehler nicht automatisieren

    def set_position(self, entity_id, position, source="manual"):
        """Set cover position (0=closed, 100=open)."""
        try:
            # Garagentor-Schutz: NIEMALS automatisch steuern
            if source != "manual" and self._is_garage_or_gate(entity_id):
                logger.warning("BLOCKED: %s is a garage/gate — refusing %s control (source: %s)",
                               entity_id, position, source)
                return False

            # Deaktivierte Covers: nur manuelle Steuerung erlaubt
            if source != "manual" and not self._is_cover_enabled(entity_id):
                logger.info("BLOCKED: %s is disabled — refusing %s control (source: %s)",
                            entity_id, position, source)
                return False

            if source == "manual":
                self._set_manual_override(entity_id)
            self.ha.call_service("cover", "set_cover_position", {
                "entity_id": entity_id,
                "position": max(0, min(100, position)),
            })
            logger.info(f"Cover {entity_id} → position {position}% (source: {source})")
            return True
        except Exception as e:
            logger.error(f"Cover set_position failed for {entity_id}: {e}")
            return False

    def set_tilt(self, entity_id, tilt, source="manual"):
        """Set cover tilt position (0-100)."""
        try:
            if source != "manual":
                # Garagentor-Schutz
                if self._is_garage_or_gate(entity_id):
                    logger.warning("BLOCKED: %s is a garage/gate — refusing tilt (source: %s)",
                                   entity_id, source)
                    return False
                # Deaktivierte Covers: nur manuelle Steuerung erlaubt
                if not self._is_cover_enabled(entity_id):
                    logger.info("BLOCKED: %s is disabled — refusing tilt (source: %s)",
                                entity_id, source)
                    return False

            if source == "manual":
                self._set_manual_override(entity_id)
            self.ha.call_service("cover", "set_cover_tilt_position", {
                "entity_id": entity_id,
                "tilt_position": max(0, min(100, tilt)),
            })
            return True
        except Exception as e:
            logger.error(f"Cover set_tilt failed for {entity_id}: {e}")
            return False

    def open_cover(self, entity_id, source="manual"):
        """Fully open a cover."""
        return self.set_position(entity_id, 100, source)

    def close_cover(self, entity_id, source="manual"):
        """Fully close a cover."""
        return self.set_position(entity_id, 0, source)

    def control_group(self, group_id, position, source="manual"):
        """Set position for all covers in a group."""
        members = self._get_group_members(group_id)
        results = []
        for entity_id in members:
            ok = self.set_position(entity_id, position, source)
            results.append({"entity_id": entity_id, "success": ok})
        return results

    def activate_scene(self, scene_id):
        """Activate a cover scene (predefined positions)."""
        from models import CoverScene
        try:
            with self.get_session() as session:
                scene = session.query(CoverScene).get(scene_id)
                if not scene or not scene.is_active:
                    return False
                positions = scene.positions or {}
                for entity_id, pos in positions.items():
                    if isinstance(pos, dict):
                        self.set_position(entity_id, pos.get("position", 100), source="scene")
                        if pos.get("tilt") is not None:
                            self.set_tilt(entity_id, pos["tilt"], source="scene")
                    else:
                        self.set_position(entity_id, pos, source="scene")
                logger.info(f"Cover scene '{scene.name}' activated ({len(positions)} covers)")
                return True
        except Exception as e:
            logger.error(f"Scene activation error: {e}")
            return False

    # ── Groups CRUD ─────────────────────────────────────────

    def get_groups(self):
        from models import CoverGroup
        groups = []
        try:
            with self.get_session() as session:
                for g in session.query(CoverGroup).filter_by(is_active=True).all():
                    groups.append({
                        "id": g.id,
                        "name": g.name,
                        "entity_ids": g.entity_ids or [],
                        "icon": g.icon,
                    })
        except Exception as e:
            logger.error(f"Error getting groups: {e}")
        return groups

    def create_group(self, name, entity_ids, icon=None):
        from models import CoverGroup
        try:
            with self.get_session() as session:
                g = CoverGroup(name=name, entity_ids=entity_ids or [], icon=icon, is_active=True)
                session.add(g)
                session.flush()
                return g.id
        except Exception as e:
            logger.error(f"Error creating group: {e}")
            return None

    def update_group(self, group_id, updates):
        from models import CoverGroup
        try:
            with self.get_session() as session:
                g = session.query(CoverGroup).get(group_id)
                if not g:
                    return False
                for key in ("name", "entity_ids", "icon", "is_active"):
                    if key in updates:
                        setattr(g, key, updates[key])
                return True
        except Exception as e:
            logger.error(f"Error updating group: {e}")
            return False

    def delete_group(self, group_id):
        from models import CoverGroup
        try:
            with self.get_session() as session:
                g = session.query(CoverGroup).get(group_id)
                if g:
                    g.is_active = False
                    return True
        except Exception as e:
            logger.error(f"Error deleting group: {e}")
        return False

    # ── Scenes CRUD ─────────────────────────────────────────

    def get_scenes(self):
        from models import CoverScene
        scenes = []
        try:
            with self.get_session() as session:
                for s in session.query(CoverScene).filter_by(is_active=True).all():
                    scenes.append({
                        "id": s.id,
                        "name": s.name,
                        "name_en": s.name_en,
                        "positions": s.positions or {},
                        "icon": s.icon,
                    })
        except Exception as e:
            logger.error(f"Error getting scenes: {e}")
        return scenes

    def create_scene(self, name, positions, name_en=None, icon=None):
        from models import CoverScene
        try:
            with self.get_session() as session:
                s = CoverScene(name=name, name_en=name_en, positions=positions or {},
                               icon=icon, is_active=True)
                session.add(s)
                session.flush()
                return s.id
        except Exception as e:
            logger.error(f"Error creating scene: {e}")
            return None

    def update_scene(self, scene_id, updates):
        from models import CoverScene
        try:
            with self.get_session() as session:
                s = session.query(CoverScene).get(scene_id)
                if not s:
                    return False
                for key in ("name", "name_en", "positions", "icon", "is_active"):
                    if key in updates:
                        setattr(s, key, updates[key])
                return True
        except Exception as e:
            logger.error(f"Error updating scene: {e}")
            return False

    def delete_scene(self, scene_id):
        from models import CoverScene
        try:
            with self.get_session() as session:
                s = session.query(CoverScene).get(scene_id)
                if s:
                    s.is_active = False
                    return True
        except Exception as e:
            logger.error(f"Error deleting scene: {e}")
        return False

    # ── Schedules CRUD ──────────────────────────────────────

    def get_schedules(self, entity_id=None, group_id=None):
        from models import CoverSchedule
        schedules = []
        try:
            with self.get_session() as session:
                q = session.query(CoverSchedule).filter_by(is_active=True)
                if entity_id:
                    q = q.filter_by(entity_id=entity_id)
                if group_id:
                    q = q.filter_by(group_id=group_id)
                for s in q.order_by(CoverSchedule.time_str).all():
                    schedules.append({
                        "id": s.id,
                        "entity_id": s.entity_id,
                        "group_id": s.group_id,
                        "time_str": s.time_str,
                        "days": s.days or [],
                        "position": s.position,
                        "tilt": s.tilt,
                        "presence_mode": s.presence_mode,
                    })
        except Exception as e:
            logger.error(f"Error getting schedules: {e}")
        return schedules

    def create_schedule(self, entity_id=None, group_id=None, time_str="08:00",
                        days=None, position=100, tilt=None, presence_mode=None):
        from models import CoverSchedule
        try:
            with self.get_session() as session:
                s = CoverSchedule(
                    entity_id=entity_id, group_id=group_id, time_str=time_str,
                    days=days or [0, 1, 2, 3, 4, 5, 6], position=position,
                    tilt=tilt, presence_mode=presence_mode, is_active=True,
                )
                session.add(s)
                session.flush()
                return s.id
        except Exception as e:
            logger.error(f"Error creating schedule: {e}")
            return None

    def update_schedule(self, schedule_id, updates):
        from models import CoverSchedule
        try:
            with self.get_session() as session:
                s = session.query(CoverSchedule).get(schedule_id)
                if not s:
                    return False
                for key in ("entity_id", "group_id", "time_str", "days",
                            "position", "tilt", "presence_mode", "is_active"):
                    if key in updates:
                        setattr(s, key, updates[key])
                return True
        except Exception as e:
            logger.error(f"Error updating schedule: {e}")
            return False

    def delete_schedule(self, schedule_id):
        from models import CoverSchedule
        try:
            with self.get_session() as session:
                s = session.query(CoverSchedule).get(schedule_id)
                if s:
                    s.is_active = False
                    return True
        except Exception as e:
            logger.error(f"Error deleting schedule: {e}")
        return False

    # ── Cover Config (facade, type, floor) ──────────────────

    def get_cover_configs(self):
        """Get facade/type/floor config for all covers."""
        from models import CoverConfig
        configs = {}
        try:
            with self.get_session() as session:
                for c in session.query(CoverConfig).all():
                    configs[c.entity_id] = {
                        "id": c.id,
                        "entity_id": c.entity_id,
                        "facade": c.facade,
                        "floor": c.floor,
                        "cover_type": c.cover_type,
                        "enabled": c.enabled if c.enabled is not None else True,
                        "group_ids": c.group_ids or [],
                    }
        except Exception as e:
            logger.error(f"Error getting cover configs: {e}")
        return configs

    def set_cover_config(self, entity_id, facade=None, floor=None,
                         cover_type=None, group_ids=None, enabled=None):
        """Set facade/type/floor/enabled config for a cover entity."""
        from models import CoverConfig
        try:
            with self.get_session() as session:
                c = session.query(CoverConfig).filter_by(entity_id=entity_id).first()
                if not c:
                    c = CoverConfig(entity_id=entity_id)
                    session.add(c)
                if facade is not None:
                    c.facade = facade
                if floor is not None:
                    c.floor = floor
                if cover_type is not None:
                    c.cover_type = cover_type
                if enabled is not None:
                    c.enabled = enabled
                if group_ids is not None:
                    c.group_ids = group_ids
                session.flush()
                return True
        except Exception as e:
            logger.error(f"Error setting cover config: {e}")
            return False

    # ── Periodic Check ──────────────────────────────────────

    def check(self):
        """Periodic check: evaluate all automation rules and apply best action."""
        if not self._is_running:
            return
        from routes.covers import is_cover_control_enabled
        if not is_cover_control_enabled():
            return

        config = self.get_config()
        now = datetime.now(timezone.utc)

        # Clean expired overrides
        self._cleanup_overrides(now)

        covers = self.get_covers()
        if not covers:
            return

        # Collect sensor data once
        sun_data = self._get_sun_data()
        weather_data = self._get_weather_data(config)
        try:
            from helpers import local_now
            local = local_now()
        except Exception:
            local = now

        for cover in covers:
            eid = cover["entity_id"]
            if self._is_overridden(eid, now):
                continue

            # Evaluate rules by priority
            action = self._evaluate_rules(cover, config, sun_data, weather_data, local)
            if action is not None:
                current_pos = cover.get("position")
                if current_pos is not None and abs(current_pos - action["position"]) >= 5:
                    self.set_position(eid, action["position"], source=action["source"])

    def check_schedules(self):
        """Check and execute due schedules. Called separately for precise timing."""
        if not self._is_running:
            return
        from routes.covers import is_cover_control_enabled
        if not is_cover_control_enabled():
            return

        try:
            from helpers import local_now
            local = local_now()
        except Exception:
            local = datetime.now(timezone.utc)

        current_time = local.strftime("%H:%M")
        prev_minute = (local - timedelta(minutes=1)).strftime("%H:%M")
        current_day = local.weekday()

        # Get current presence mode
        presence_mode = self._get_presence_mode()

        from models import CoverSchedule
        try:
            with self.get_session() as session:
                schedules = session.query(CoverSchedule).filter_by(
                    is_active=True
                ).filter(
                    CoverSchedule.time_str.in_([current_time, prev_minute])
                ).all()
                today = local.date()
                for s in schedules:
                    # Dedup: Jedes Schedule nur einmal pro Tag ausfuehren
                    if self._executed_schedules.get(s.id) == today:
                        continue
                    days = s.days or [0, 1, 2, 3, 4, 5, 6]
                    if current_day not in days:
                        continue
                    if s.presence_mode and s.presence_mode != presence_mode:
                        continue

                    self._executed_schedules[s.id] = today
                    if s.entity_id and not self._is_overridden(s.entity_id):
                        self.set_position(s.entity_id, s.position, source="schedule")
                        if s.tilt is not None:
                            self.set_tilt(s.entity_id, s.tilt, source="schedule")
                    elif s.group_id:
                        members = self._get_group_members(s.group_id)
                        for eid in members:
                            if not self._is_overridden(eid):
                                self.set_position(eid, s.position, source="schedule")
                                if s.tilt is not None:
                                    self.set_tilt(eid, s.tilt, source="schedule")
        except Exception as e:
            logger.error(f"Schedule check error: {e}")

    def check_simulation(self):
        """Presence simulation: random cover movements when away."""
        if not self._is_running:
            return
        from routes.covers import is_cover_control_enabled
        if not is_cover_control_enabled():
            return
        config = self.get_config()
        if not config.get("presence_simulation_enabled"):
            return

        presence_mode = self._get_presence_mode()
        if presence_mode not in ("away", "vacation", "extended_away"):
            return

        try:
            from helpers import local_now
            local = local_now()
        except Exception:
            local = datetime.now(timezone.utc)

        hour = local.hour
        start = config.get("simulation_start_hour", 17)
        end = config.get("simulation_end_hour", 23)
        if not (start <= hour < end):
            return

        interval = config.get("simulation_interval_min", 45)
        variance = config.get("simulation_variance_min", 20)
        now = datetime.now(timezone.utc)

        covers = self.get_covers()
        for cover in covers:
            eid = cover["entity_id"]
            last = self._last_simulation.get(eid)
            actual_interval = interval + random.randint(-variance, variance)
            if last and (now - last).total_seconds() < actual_interval * 60:
                continue

            # Randomly open or close
            new_pos = random.choice([0, 30, 70, 100])
            self.set_position(eid, new_pos, source="simulation")
            self._last_simulation[eid] = now
            logger.info(f"Presence simulation: {eid} → {new_pos}%")

    # ── Rule Evaluation ─────────────────────────────────────

    def _evaluate_rules(self, cover, config, sun_data, weather_data, local):
        """Evaluate all rules for a cover and return the highest-priority action."""
        candidates = []

        # Security: Storm/emergency
        security = self._eval_security(cover, config, weather_data)
        if security is not None:
            candidates.append({"priority": PRIORITY_SECURITY, **security})

        # Weather: Wind, rain, frost
        weather = self._eval_weather(cover, config, weather_data, sun_data)
        if weather is not None:
            candidates.append({"priority": PRIORITY_WEATHER, **weather})

        # Comfort: Sun protection, privacy, temperature
        comfort = self._eval_comfort(cover, config, sun_data, weather_data, local)
        if comfort is not None:
            candidates.append({"priority": PRIORITY_COMFORT, **comfort})

        # Energy: Solar gain, PV optimization
        energy = self._eval_energy(cover, config, sun_data, weather_data)
        if energy is not None:
            candidates.append({"priority": PRIORITY_ENERGY, **energy})

        if not candidates:
            return None

        # Return highest priority action
        candidates.sort(key=lambda x: -x["priority"])
        return candidates[0]

    def _eval_security(self, cover, config, weather_data):
        """Security rules: storm protection, emergency retraction."""
        wind = weather_data.get("wind_speed_kmh", 0)
        cover_type = cover.get("cover_type", "shutter")
        if wind > 80 and cover_type == "awning":
            return {"position": 100, "source": "security_storm"}
        return None

    def _eval_weather(self, cover, config, weather_data, sun_data):
        """Weather rules: wind, rain, frost."""
        if not config.get("weather_protection_enabled"):
            return None

        wind = weather_data.get("wind_speed_kmh", 0)
        is_raining = weather_data.get("is_raining", False)
        outdoor_temp = weather_data.get("outdoor_temp_c")
        cover_type = cover.get("cover_type", "shutter")

        # Wind: retract awnings
        wind_threshold = config.get("wind_threshold_kmh", 50)
        if wind > wind_threshold and cover_type == "awning":
            return {"position": 100, "source": "weather_wind"}

        # Rain: close roof windows
        if is_raining and cover_type == "roof_window" and config.get("rain_close_roof_windows"):
            return {"position": 0, "source": "weather_rain"}

        # Frost insulation: close at night
        if (config.get("frost_insulation_enabled") and outdoor_temp is not None
                and outdoor_temp < config.get("frost_threshold_c", 0)):
            sun_elevation = sun_data.get("elevation", 0)
            if sun_elevation < -6:  # Nighttime
                return {"position": 0, "source": "weather_frost"}

        return None

    def _eval_comfort(self, cover, config, sun_data, weather_data, local):
        """Comfort rules: sun protection, privacy, temperature coupling."""
        facade = cover.get("facade")
        sun_elevation = sun_data.get("elevation", 0)
        sun_azimuth = sun_data.get("azimuth", 180)
        outdoor_temp = weather_data.get("outdoor_temp_c")

        # Privacy: close at dusk
        if config.get("privacy_mode_enabled") and config.get("privacy_close_at_dusk"):
            threshold = config.get("privacy_sun_elevation_deg", -3)
            if sun_elevation < threshold:
                return {"position": 0, "source": "comfort_privacy"}

        # Sun protection
        if config.get("sun_protection_enabled") and sun_elevation > 5:
            temp_threshold = config.get("sun_protection_outdoor_temp_c", 25)
            if outdoor_temp is not None and outdoor_temp >= temp_threshold:
                if self._is_sun_on_facade(facade, sun_azimuth):
                    pos = config.get("sun_protection_position_pct", 20)
                    return {"position": pos, "source": "comfort_sun_protection"}

        # Winter solar gain: let sun in for passive heating
        if (config.get("winter_solar_gain_enabled") and sun_elevation > 10
                and outdoor_temp is not None
                and outdoor_temp < config.get("winter_solar_gain_below_c", 18)):
            if self._is_sun_on_facade(facade, sun_azimuth):
                return {"position": 100, "source": "comfort_solar_gain"}

        return None

    def _eval_energy(self, cover, config, sun_data, weather_data):
        """Energy rules: PV optimization, passive shading."""
        # Placeholder for PV surplus integration
        return None

    # ── Event Handlers ──────────────────────────────────────

    def _on_state_changed(self, event):
        """Detect manual cover operations for override tracking."""
        if not self._is_running:
            return
        data = event.data if hasattr(event, 'data') else (event if isinstance(event, dict) else {})
        entity_id = data.get("entity_id", "")
        if not entity_id.startswith("cover."):
            return

        # Check if this entity is assigned to us
        from models import FeatureEntityAssignment
        try:
            with self.get_session() as session:
                assigned = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="cover_control", entity_id=entity_id, is_active=True
                ).first()
                if not assigned:
                    return
        except Exception:
            return

        new_state = data.get("new_state") or {}
        context = new_state.get("context", {}) if isinstance(new_state, dict) else {}
        # If change was initiated by user (not by us), set manual override
        if context.get("user_id"):
            config = self.get_config()
            duration = config.get("manual_override_duration_min", 120)
            self._manual_overrides[entity_id] = (
                datetime.now(timezone.utc) + timedelta(minutes=duration)
            )
            logger.info(f"Manual override detected for {entity_id} ({duration}min)")

            # Learning: log manual action for pattern detection
            if config.get("learning_enabled"):
                self.event_bus.publish("cover.manual_action", {
                    "entity_id": entity_id,
                    "new_state": new_state.get("state", ""),
                    "position": new_state.get("attributes", {}).get("current_position"),
                }, source="cover_control")

    def _on_sleep_detected(self, event):
        """Close covers when sleep is detected."""
        config = self.get_config()
        if not config.get("sleep_close_enabled"):
            return
        covers = self.get_covers()
        for cover in covers:
            if not self._is_overridden(cover["entity_id"]):
                self.set_position(cover["entity_id"], 0, source="sleep")
        logger.info("Sleep detected: closing all covers")

    def _on_wake_detected(self, event):
        """Gradually open covers on wake-up (only if bed is actually empty)."""
        config = self.get_config()
        if not config.get("wakeup_integration_enabled"):
            return

        # Double-check: Bettbelegungssensoren pruefen bevor Rolladen geoeffnet werden
        # (Wake-Heuristik kann z.B. durch kurze Badezimmer-Besuche ausloesen)
        if self._is_bed_occupied():
            logger.info("Wake detected but bed still occupied — NOT opening covers")
            return

        covers = self.get_covers()
        for cover in covers:
            if not self._is_overridden(cover["entity_id"]):
                self.set_position(cover["entity_id"], 100, source="wakeup")
        logger.info("Wake detected: opening covers")

    def _is_bed_occupied(self) -> bool:
        """Prueft ob ein Bettbelegungssensor aktiv ist."""
        try:
            states = self.ha.get_states() or []
            return _check_bed_occupied(states)
        except Exception:
            return False

    def _on_weather_alert(self, event):
        """React to weather alerts (storm, hail)."""
        data = event.data if hasattr(event, 'data') else (event if isinstance(event, dict) else {})
        alert_type = data.get("alert_type", "")
        if alert_type in ("storm", "hail", "strong_wind"):
            covers = self.get_covers()
            for cover in covers:
                if cover.get("cover_type") == "awning":
                    self.set_position(cover["entity_id"], 100, source="weather_alert")
            logger.warning(f"Weather alert ({alert_type}): retracting awnings")

    def _on_presence_changed(self, event):
        """React to presence mode changes."""
        data = event.data if hasattr(event, 'data') else (event if isinstance(event, dict) else {})
        new_mode = data.get("mode", "")
        if new_mode in ("away", "vacation", "extended_away"):
            # Close for privacy/security when leaving
            covers = self.get_covers()
            for cover in covers:
                if not self._is_overridden(cover["entity_id"]):
                    self.set_position(cover["entity_id"], 0, source="presence_away")

    # ── Helpers ──────────────────────────────────────────────

    def _get_cover_config(self, session, entity_id):
        """Get per-cover config (facade, floor, type, groups, enabled)."""
        from models import CoverConfig
        try:
            c = session.query(CoverConfig).filter_by(entity_id=entity_id).first()
            if c:
                return {
                    "facade": c.facade,
                    "floor": c.floor,
                    "cover_type": c.cover_type,
                    "enabled": c.enabled if c.enabled is not None else True,
                    "group_ids": c.group_ids or [],
                }
        except Exception:
            pass
        return {}

    def _get_group_members(self, group_id):
        """Get entity_ids for a group."""
        from models import CoverGroup
        try:
            with self.get_session() as session:
                g = session.query(CoverGroup).get(group_id)
                return g.entity_ids or [] if g else []
        except Exception:
            return []

    def _set_manual_override(self, entity_id):
        config = self.get_config()
        duration = config.get("manual_override_duration_min", 120)
        self._manual_overrides[entity_id] = (
            datetime.now(timezone.utc) + timedelta(minutes=duration)
        )

    def _is_overridden(self, entity_id, now=None):
        if entity_id not in self._manual_overrides:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        return now < self._manual_overrides[entity_id]

    def _cleanup_overrides(self, now):
        expired = [eid for eid, until in self._manual_overrides.items() if now >= until]
        for eid in expired:
            del self._manual_overrides[eid]
        # Alte Schedule-Dedup-Eintraege aufräumen (aelter als heute)
        try:
            from helpers import local_now
            today = local_now().date()
        except Exception:
            today = now.date() if hasattr(now, 'date') else None
        if today:
            stale = [sid for sid, d in self._executed_schedules.items() if d < today]
            for sid in stale:
                del self._executed_schedules[sid]

    def _get_sun_data(self):
        """Get sun position from HA sun.sun entity."""
        try:
            state = self.ha.get_state("sun.sun") if self.ha else None
            if state:
                attrs = state.get("attributes", {})
                return {
                    "elevation": attrs.get("elevation", 0),
                    "azimuth": attrs.get("azimuth", 180),
                    "rising": attrs.get("rising", True),
                }
        except Exception:
            pass
        return {"elevation": 0, "azimuth": 180, "rising": True}

    def _get_weather_data(self, config):
        """Collect weather sensor readings."""
        from models import FeatureEntityAssignment
        data = {"wind_speed_kmh": 0, "is_raining": False, "outdoor_temp_c": None}
        try:
            with self.get_session() as session:
                # Wind sensor
                wind = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="cover_control", role="wind_sensor", is_active=True
                ).first()
                if wind and self.ha:
                    state = self.ha.get_state(wind.entity_id)
                    if state:
                        try:
                            data["wind_speed_kmh"] = float(state.get("state", 0))
                        except (ValueError, TypeError):
                            pass

                # Rain sensor
                rain = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="cover_control", role="rain_sensor", is_active=True
                ).first()
                if rain and self.ha:
                    state = self.ha.get_state(rain.entity_id)
                    if state:
                        data["is_raining"] = state.get("state") == "on"

                # Outdoor temperature
                temp = session.query(FeatureEntityAssignment).filter_by(
                    feature_key="cover_control", role="temp_outdoor", is_active=True
                ).first()
                if temp and self.ha:
                    state = self.ha.get_state(temp.entity_id)
                    if state:
                        try:
                            data["outdoor_temp_c"] = float(state.get("state", 0))
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            logger.error(f"Weather data error: {e}")
        return data

    def _get_presence_mode(self):
        """Get current presence mode."""
        try:
            from helpers import get_setting
            return get_setting("presence_mode") or "home"
        except Exception:
            return "home"

    @staticmethod
    def _is_sun_on_facade(facade, sun_azimuth):
        """Check if sun is hitting a specific facade based on azimuth."""
        if not facade:
            return False
        facade_ranges = {
            "N":  (315, 45),
            "NE": (0, 90),
            "E":  (45, 135),
            "SE": (90, 180),
            "S":  (135, 225),
            "SW": (180, 270),
            "W":  (225, 315),
            "NW": (270, 360),
        }
        r = facade_ranges.get(facade.upper())
        if not r:
            return False
        start, end = r
        if start < end:
            return start <= sun_azimuth < end
        else:  # Wraps around (e.g., N: 315-45)
            return sun_azimuth >= start or sun_azimuth < end
