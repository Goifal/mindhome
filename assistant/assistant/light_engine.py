"""
Light Engine - Ultimative Lichtsteuerung fuer MindHome.

Praesenzmelder:
- Motion → Licht an (adaptiv, circadian-aware)
- Nachts: Nacht-Pfadlicht statt volle Helligkeit
- Auto-Off bei leerem Raum (delegiert an time_awareness)

Bettsensoren:
- Bett belegt nachts → Sleep-Mode (alle Lichter langsam aus)
- Bett leer morgens → Aufwach-Licht (graduell)
- Bett leer nachts → Nacht-Pfadlicht in Flur/Bad

Lux-Adaptive:
- Lichtsensor → Helligkeit an Tageslicht anpassen

Automatik:
- Daemmerung → Auto-On (wenn jemand zuhause)
- Niemand zuhause → Auto-Off
- Night-Dimming → Nach 21h Lichter sanft runterfahren

Manual Override:
- Nach manueller Bedienung X Minuten kein Auto-Eingriff
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .config import yaml_config, get_room_profiles
from .ha_client import HomeAssistantClient
from .function_calling import FunctionExecutor

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))


async def _safe_redis(redis_client, method: str, *args, **kwargs):
    """Redis-Operation mit Fehlerbehandlung — gibt None bei Fehler zurueck."""
    try:
        return await getattr(redis_client, method)(*args, **kwargs)
    except Exception as e:
        logger.debug("Redis %s fehlgeschlagen: %s", method, e)
        return None


# Redis-Key Prefixe
_R_OVERRIDE = "mha:light:override:"  # {entity_id} → TTL
_R_DUSK = "mha:light:dusk_triggered"  # Tages-Flag
_R_WEATHER_BOOST = "mha:light:weather_boost"  # Aktiver Wetter-Boost
_R_AWAY_OFF = "mha:light:away_off"  # Schon-abgeschaltet Flag
_R_NIGHT_DIM = "mha:light:night_dim:"  # {entity_id} → gesetzt wenn gedimmt
_R_SLEEP = "mha:light:sleep_active"  # Schlafmodus aktiv
_R_PATHLIGHT = "mha:light:pathlight:"  # {entity_id} → TTL fuer Auto-Off


class LightEngine:
    """Zentrale Licht-Engine: Praesenz, Bett, Lux, Daemmerung, Override."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis = None
        self.mood = None  # MoodDetector — fuer stimmungsadaptive Beleuchtung
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._room_lux: dict[str, float] = {}

    async def initialize(self, redis_client=None):
        """Initialisiert Redis-Verbindung."""
        self.redis = redis_client
        logger.info(
            "LightEngine initialisiert (Redis: %s)", "ja" if redis_client else "nein"
        )

    async def start(self):
        """Startet den periodischen Check-Loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._check_loop())
        logger.info("LightEngine gestartet")

    async def stop(self):
        """Stoppt den Check-Loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LightEngine gestoppt")

    # ── Periodischer Check (alle 60s) ──────────────────────────────────

    async def _check_loop(self):
        """Periodischer Check fuer Daemmerung, Abwesenheit, Night-Dimming."""
        await asyncio.sleep(30)  # Startup-Delay
        while self._running:
            try:
                cfg = yaml_config.get("lighting", {})
                if not cfg.get("enabled", True):
                    await asyncio.sleep(60)
                    continue

                states = await self.ha.get_states()
                if not states:
                    await asyncio.sleep(60)
                    continue

                # Daemmerung → Auto-On
                if cfg.get("auto_on_dusk"):
                    await self._check_dusk_auto_on(cfg, states)

                # Abwesenheit → Auto-Off
                if cfg.get("auto_off_away"):
                    await self._check_away_auto_off(cfg, states)

                # Night-Dimming
                if cfg.get("night_dimming"):
                    await self._check_night_dimming(cfg, states)

                # Nacht-Pfadlicht Auto-Off
                await self._check_pathlight_timeout(cfg)

                # Lux-Adaptive
                lux_cfg = cfg.get("lux_adaptive", {})
                if lux_cfg.get("enabled"):
                    await self._check_lux_adaptive(cfg, states)

                # Wetter-Boost (Bewoelkung/Regen → heller)
                wb_cfg = cfg.get("weather_boost", {})
                if wb_cfg.get("enabled"):
                    await self._check_weather_boost(cfg, states)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("LightEngine check_loop Fehler: %s", e, exc_info=True)

            await asyncio.sleep(60)

    # ── Motion Handler ─────────────────────────────────────────────────

    async def on_motion(self, entity_id: str, room: str):
        """Motion erkannt → Licht an (wenn Praesenz-Steuerung aktiv)."""
        cfg = yaml_config.get("lighting", {})
        if not cfg.get("enabled", True):
            return

        pc = cfg.get("presence_control", {})
        if not pc.get("enabled", True) or not pc.get("auto_on_motion", True):
            return

        # Raum-Profil pruefen: presence_auto_on?
        profiles = get_room_profiles()
        room_cfg = profiles.get("rooms", {}).get(room, {})
        if not room_cfg.get("presence_auto_on", True):
            return

        lights = self._get_room_lights(room, room_cfg)
        if not lights:
            return

        # Schlafmodus aktiv? → Nicht einschalten (ausser Pfadlicht)
        if self.redis and await self.redis.get(_R_SLEEP):
            # Nacht-Pfadlicht statt normales Licht
            if pc.get("night_path_light") and room_cfg.get("night_path_light"):
                await self._apply_night_path_light(room, lights, pc)
            return

        # Nacht? → Pfadlicht statt volle Helligkeit
        if self._is_night(pc) and pc.get("night_path_light"):
            if room_cfg.get("night_path_light"):
                await self._apply_night_path_light(room, lights, pc)
                return

        # Tags/Abends: Adaptives Licht einschalten
        for light_id in lights:
            # Manual Override pruefen
            if await self.is_manual_override_active(light_id):
                continue

            # Bereits an? → Nicht nochmal setzen
            ha_state = await self.ha.get_state(light_id)
            if ha_state and ha_state.get("state") == "on":
                continue

            brightness = FunctionExecutor.get_adaptive_brightness(room, light_id)

            # Mood-Awareness: Bei Stress gedaempfter, bei Muedigkeit minimal
            if self.mood:
                try:
                    mood_data = self.mood.get_current_mood()
                    mood = mood_data.get("mood", "neutral")
                    if mood == "stressed":
                        brightness = min(brightness, 50)  # Max 50% bei Stress
                    elif mood == "tired":
                        brightness = min(brightness, 30)  # Max 30% bei Muedigkeit
                except Exception as e:
                    logger.debug("Mood data retrieval failed: %s", e)

            service_data = {"entity_id": light_id, "brightness_pct": brightness}
            transition = cfg.get("default_transition")
            if transition:
                try:
                    service_data["transition"] = int(transition)
                except (ValueError, TypeError):
                    pass
            await self.ha.call_service("light", "turn_on", service_data)
            logger.info(
                "Praesenz-Licht: %s an (%d%%) in %s", light_id, brightness, room
            )

    async def on_motion_clear(self, entity_id: str, room: str):
        """Motion weg → Wird von time_awareness Auto-Off gehandelt."""
        pass

    # ── Bed Sensor Handler ─────────────────────────────────────────────

    async def on_bed_occupied(self, entity_id: str, room: str):
        """Bett belegt → Sleep-Mode aktivieren."""
        cfg = yaml_config.get("lighting", {})
        bed_cfg = cfg.get("bed_sensors", {})
        if not bed_cfg.get("enabled", True):
            return

        # Nur nach sleep_start_hour
        now = datetime.now(_LOCAL_TZ)
        start_hour = bed_cfg.get("sleep_start_hour", 21)
        if now.hour < start_hour and now.hour >= 6:
            logger.debug(
                "Bett belegt, aber vor Schlafzeit (%d < %d)", now.hour, start_hour
            )
            return

        logger.info("Bettsensor: Bett belegt in %s → Sleep-Mode", room)

        # Sleep-Flag setzen (12h TTL)
        if self.redis:
            await _safe_redis(self.redis, "set", _R_SLEEP, "1", ex=43200)

        # Sleep-Mode: Alle Lichter langsam aus
        if bed_cfg.get("sleep_mode", True):
            await self._apply_sleep_mode(cfg, bed_cfg)

    async def on_bed_clear(self, entity_id: str, room: str):
        """Bett leer → Aufwach-Licht oder Nacht-Pfadlicht."""
        cfg = yaml_config.get("lighting", {})
        bed_cfg = cfg.get("bed_sensors", {})
        if not bed_cfg.get("enabled", True):
            return

        logger.info("Bettsensor: Bett leer in %s", room)

        # Sleep-Flag loeschen
        if self.redis:
            await _safe_redis(self.redis, "delete", _R_SLEEP)

        now = datetime.now(_LOCAL_TZ)
        pc = cfg.get("presence_control", {})

        # Morgen-Fenster? → Aufwach-Licht
        wake_start = bed_cfg.get("wakeup_window_start", 5)
        wake_end = bed_cfg.get("wakeup_window_end", 9)
        if bed_cfg.get("wakeup_light") and wake_start <= now.hour < wake_end:
            await self._apply_wakeup_light(room, cfg, bed_cfg)
            return

        # Nachts? → Pfadlicht in konfigurierten Raeumen
        if self._is_night(pc) and pc.get("night_path_light"):
            profiles = get_room_profiles()
            rooms = profiles.get("rooms", {})
            for r_name, r_cfg in rooms.items():
                if r_cfg.get("night_path_light"):
                    r_lights = self._get_room_lights(r_name, r_cfg)
                    if r_lights:
                        await self._apply_night_path_light(r_name, r_lights, pc)

    # ── Lux Sensor Handler ─────────────────────────────────────────────

    async def on_lux_change(self, entity_id: str, room: str, lux_value: float):
        """Lux-Sensor Aenderung → Wert speichern (wird im periodic_check verarbeitet)."""
        self._room_lux[room] = lux_value

    # ── Dusk Auto-On ───────────────────────────────────────────────────

    async def _check_dusk_auto_on(self, cfg: dict, states: list[dict]):
        """Sonnenuntergang + jemand zuhause → Lichter an.

        Bug 3 Fix: Wenn Daemmerung bereits ausgeloest wurde, aber alle
        Lichter aus sind und jemand zuhause ist, wird erneut ausgeloest.
        Das deckt den Fall ab, dass jemand NACH der Daemmerung heimkommt.
        """
        # Einmal pro Tag (ausser: alle Lichter aus + jemand da)
        if self.redis:
            already = await self.redis.get(_R_DUSK)
            if already:
                # Re-Check: Sind trotz Daemmerung alle Lichter aus + jemand zuhause?
                if self._anyone_home(states):
                    any_on = any(
                        s.get("entity_id", "").startswith("light.")
                        and s.get("state") == "on"
                        for s in states
                    )
                    if not any_on:
                        logger.info(
                            "Daemmerung: Alle Lichter aus trotz Praesenz → Re-Trigger"
                        )
                        # Weiter zur normalen Logik (Flag nicht pruefen)
                    else:
                        return
                else:
                    return

        # sun.sun Elevation pruefen
        threshold = cfg.get("dusk_sun_elevation", -2)
        sun_elevation = None
        for s in states:
            if s.get("entity_id") == "sun.sun":
                attrs = s.get("attributes", {})
                sun_elevation = attrs.get("elevation")
                break

        # Wetter-Boost: Bei Bewoelkung frueher einschalten (hoehere Schwelle)
        wb_cfg = cfg.get("weather_boost", {})
        if wb_cfg.get("enabled") and wb_cfg.get("dusk_earlier_on_cloudy", True):
            weather_condition = self._get_weather_condition(states, wb_cfg)
            cloud_conditions = {
                "cloudy",
                "partlycloudy",
                "rainy",
                "pouring",
                "fog",
                "hail",
                "lightning-rainy",
            }
            if weather_condition in cloud_conditions:
                offset = wb_cfg.get("dusk_cloud_elevation_offset", 3)
                threshold += offset
                logger.debug(
                    "Dusk-Schwelle wegen %s angehoben: %.1f°",
                    weather_condition,
                    threshold,
                )

        if sun_elevation is None or sun_elevation > threshold:
            return

        # Jemand zuhause?
        if not self._anyone_home(states):
            return

        # Tages-Flag setzen (24h TTL)
        if self.redis:
            await _safe_redis(self.redis, "set", _R_DUSK, "1", ex=86400)

        logger.info("Daemmerung erkannt (Elevation %.1f°) → Auto-On", sun_elevation)

        only_occupied = cfg.get("dusk_only_occupied_rooms", True)
        profiles = get_room_profiles()
        rooms = profiles.get("rooms", {})

        # Aktive Raeume bestimmen (mit Motion in letzten 30 Min)
        active_rooms = set()
        if only_occupied:
            motion_sensors = (
                yaml_config.get("multi_room", {}).get("room_motion_sensors") or {}
            )
            for s in states:
                eid = s.get("entity_id", "")
                if eid in motion_sensors.values() and s.get("state") == "on":
                    for rn, sid in motion_sensors.items():
                        if sid == eid:
                            active_rooms.add(rn.lower())

        transition = cfg.get("default_transition", 2)
        for room_name, room_cfg in rooms.items():
            if only_occupied and room_name.lower() not in active_rooms:
                continue

            lights = self._get_room_lights(room_name, room_cfg)
            for light_id in lights:
                if await self.is_manual_override_active(light_id):
                    continue
                # Schon an? → Nicht nochmal
                ha_state = await self.ha.get_state(light_id)
                if ha_state and ha_state.get("state") == "on":
                    continue
                brightness = FunctionExecutor.get_adaptive_brightness(
                    room_name, light_id
                )
                data = {"entity_id": light_id, "brightness_pct": brightness}
                try:
                    data["transition"] = int(transition)
                except (ValueError, TypeError):
                    pass
                await self.ha.call_service("light", "turn_on", data)
                logger.info("Daemmerungs-Licht: %s an (%d%%)", light_id, brightness)

    # ── Away Auto-Off ──────────────────────────────────────────────────

    async def _check_away_auto_off(self, cfg: dict, states: list[dict]):
        """Niemand zuhause → alle Lichter aus."""
        if self._anyone_home(states):
            # Jemand ist da → Flag zuruecksetzen
            if self.redis:
                await _safe_redis(self.redis, "delete", _R_AWAY_OFF)
            return

        # Schon ausgeschaltet?
        if self.redis:
            already = await self.redis.get(_R_AWAY_OFF)
            if already:
                return
            await _safe_redis(self.redis, "set", _R_AWAY_OFF, "1", ex=7200)

        logger.info("Niemand zuhause → alle Lichter aus")
        transition = cfg.get("default_transition", 2)
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light.") and s.get("state") == "on":
                data = {"entity_id": eid}
                try:
                    data["transition"] = int(transition)
                except (ValueError, TypeError):
                    pass
                await self.ha.call_service("light", "turn_off", data)

    # ── Night Dimming ──────────────────────────────────────────────────

    async def _check_night_dimming(self, cfg: dict, states: list[dict]):
        """Nach Startzeit: Lichter die heller als night_brightness sind, dimmen."""
        now = datetime.now(_LOCAL_TZ)
        start_hour = cfg.get("night_dimming_start_hour", 21)

        # Nur zwischen start_hour und 06:00
        if not (now.hour >= start_hour or now.hour < 6):
            # Tagsüber: Night-Dim Flags zuruecksetzen
            if self.redis and now.hour == 12:
                cursor = b"0"
                while True:
                    cursor, _keys = await self.redis.scan(
                        cursor, match=f"{_R_NIGHT_DIM}*", count=100
                    )
                    for k in _keys:
                        await _safe_redis(self.redis, "delete", k)
                    if cursor == b"0" or cursor == 0:
                        break
            return

        transition = cfg.get("night_dimming_transition", 300)
        profiles = get_room_profiles()
        rooms = profiles.get("rooms", {})

        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("light.") or s.get("state") != "on":
                continue

            # Schon gedimmt?
            if self.redis:
                already = await self.redis.get(f"{_R_NIGHT_DIM}{eid}")
                if already:
                    continue

            # Aktuelle Helligkeit pruefen
            attrs = s.get("attributes", {})
            current_bri = attrs.get("brightness")
            if current_bri is None:
                continue
            current_pct = round(current_bri / 255 * 100)

            # Raum und Night-Brightness ermitteln
            room_name = self._find_room_for_light(eid, rooms)
            room_cfg = rooms.get(room_name, {}) if room_name else {}
            night_bri = room_cfg.get("night_brightness", 20)

            # Per-Lampe Night Override
            per_light = room_cfg.get("light_brightness", {}).get(eid)
            if per_light and isinstance(per_light, dict):
                night_bri = per_light.get("night", night_bri)

            if current_pct <= night_bri + 5:
                continue  # Schon dunkel genug

            # Override pruefen
            if await self.is_manual_override_active(eid):
                continue

            # Dimmen
            data = {"entity_id": eid, "brightness_pct": night_bri}
            try:
                data["transition"] = int(transition)
            except (ValueError, TypeError):
                pass
            await self.ha.call_service("light", "turn_on", data)
            logger.info(
                "Night-Dimming: %s %d%% → %d%% (Transition %ds)",
                eid,
                current_pct,
                night_bri,
                transition,
            )

            # Flag setzen (12h TTL)
            if self.redis:
                await _safe_redis(
                    self.redis, "set", f"{_R_NIGHT_DIM}{eid}", "1", ex=43200
                )

    # ── Sleep Mode ─────────────────────────────────────────────────────

    async def _apply_sleep_mode(self, cfg: dict, bed_cfg: dict):
        """Alle Lichter im Haus langsam ausschalten."""
        transition = bed_cfg.get("sleep_dim_transition", 300)
        states = await self.ha.get_states()
        if not states:
            return

        count = 0
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light.") and s.get("state") == "on":
                data = {"entity_id": eid}
                try:
                    data["transition"] = int(transition)
                except (ValueError, TypeError):
                    pass
                await self.ha.call_service("light", "turn_off", data)
                count += 1

        logger.info(
            "Sleep-Mode: %d Lichter ausgeschaltet (Transition %ds)", count, transition
        )

    # ── Night Path Light ───────────────────────────────────────────────

    async def _apply_night_path_light(self, room: str, lights: list[str], pc: dict):
        """Sehr dimmes Orientierungslicht einschalten."""
        brightness = pc.get("night_path_brightness", 5)
        timeout_min = pc.get("night_path_timeout_minutes", 5)

        for light_id in lights:
            data = {
                "entity_id": light_id,
                "brightness_pct": brightness,
                "transition": 2,
            }
            await self.ha.call_service("light", "turn_on", data)
            logger.info(
                "Nacht-Pfadlicht: %s an (%d%%) in %s", light_id, brightness, room
            )

            # TTL fuer Auto-Off setzen
            if self.redis:
                await _safe_redis(
                    self.redis,
                    "set",
                    f"{_R_PATHLIGHT}{light_id}",
                    room,
                    ex=timeout_min * 60,
                )

    async def _check_pathlight_timeout(self, cfg: dict):
        """Prueft abgelaufene Pfadlichter und schaltet sie aus."""
        if not self.redis:
            return

        # Alle Pathlight-Keys mit kurzer Restlaufzeit finden
        keys = []
        cursor = b"0"
        while True:
            cursor, _batch = await self.redis.scan(
                cursor, match=f"{_R_PATHLIGHT}*", count=100
            )
            keys.extend(_batch)
            if cursor == b"0" or cursor == 0:
                break
        for key in keys:
            ttl = await _safe_redis(self.redis, "ttl", key)
            if ttl is None:
                ttl = -2
            if (
                ttl < 1
            ):  # -2 = key not found, -1 = no expiry (shouldn't happen), 0 = about to expire
                # Key ist abgelaufen → Licht ausschalten
                entity_id = key.decode() if isinstance(key, bytes) else key
                entity_id = entity_id.replace(_R_PATHLIGHT, "")
                transition = cfg.get("default_transition", 2)
                data = {"entity_id": entity_id}
                try:
                    data["transition"] = int(transition)
                except (ValueError, TypeError):
                    pass
                await self.ha.call_service("light", "turn_off", data)
                logger.info("Pfadlicht-Timeout: %s aus", entity_id)

    # ── Wakeup Light ───────────────────────────────────────────────────

    async def _apply_wakeup_light(self, room: str, cfg: dict, bed_cfg: dict):
        """Graduelles Aufhellen beim Aufwachen."""
        brightness = bed_cfg.get("wakeup_brightness", 40)
        transition = bed_cfg.get("wakeup_transition", 120)

        profiles = get_room_profiles()
        room_cfg = profiles.get("rooms", {}).get(room, {})
        lights = self._get_room_lights(room, room_cfg)

        if not lights:
            return

        for light_id in lights:
            data = {
                "entity_id": light_id,
                "brightness_pct": brightness,
                "transition": transition,
            }
            await self.ha.call_service("light", "turn_on", data)
            logger.info(
                "Aufwach-Licht: %s → %d%% in %ds", light_id, brightness, transition
            )

    # ── Lux Adaptive ───────────────────────────────────────────────────

    async def _is_weather_boost_active(self) -> bool:
        """Prueft ob Weather-Boost gerade aktiv ist."""
        if not self.redis:
            return False
        val = await _safe_redis(self.redis, "get", _R_WEATHER_BOOST)
        return bool(val)

    async def _check_lux_adaptive(self, cfg: dict, states: list[dict]):
        """Helligkeit an Tageslicht anpassen.

        WICHTIG: Wird uebersprungen wenn Weather-Boost aktiv ist,
        da sonst die beiden sich gegenseitig bekaempfen.
        """
        lux_cfg = cfg.get("lux_adaptive", {})
        if not lux_cfg.get("enabled"):
            return

        # Bug 2: Nicht mit Weather-Boost kaempfen
        if await self._is_weather_boost_active():
            return

        target_lux = lux_cfg.get("target_lux", 400)
        min_bri = lux_cfg.get("min_brightness_pct", 10)
        max_bri = lux_cfg.get("max_brightness_pct", 100)
        profiles = get_room_profiles()
        rooms = profiles.get("rooms", {})

        for room_name, room_cfg in rooms.items():
            lux_sensor = room_cfg.get("lux_sensor", "")
            if not lux_sensor:
                continue

            # Aktuellen Lux-Wert aus Cache oder States holen
            current_lux = self._room_lux.get(room_name)
            if current_lux is None:
                for s in states:
                    if s.get("entity_id") == lux_sensor:
                        try:
                            current_lux = float(s.get("state", 0))
                        except (ValueError, TypeError):
                            continue
                        break

            if current_lux is None:
                continue

            # Nur anpassen wenn Licht an ist
            lights = self._get_room_lights(room_name, room_cfg)
            for light_id in lights:
                ha_state = await self.ha.get_state(light_id)
                if not ha_state or ha_state.get("state") != "on":
                    continue

                if await self.is_manual_override_active(light_id):
                    continue

                # Berechnung: Je mehr Tageslicht, desto weniger Kunstlicht
                if not target_lux:
                    continue
                ratio = min(1.0, current_lux / target_lux)
                target_bri = int(max_bri * (1.0 - ratio))
                target_bri = max(min_bri, min(max_bri, target_bri))

                # Aktuelle Helligkeit pruefen (nur anpassen wenn Differenz > 10%)
                attrs = ha_state.get("attributes", {})
                current_bri_raw = attrs.get("brightness", 128)
                current_pct = round(current_bri_raw / 255 * 100)
                if abs(current_pct - target_bri) < 10:
                    continue

                data = {
                    "entity_id": light_id,
                    "brightness_pct": target_bri,
                    "transition": 5,
                }
                await self.ha.call_service("light", "turn_on", data)
                logger.info(
                    "Lux-Adaptiv: %s %d%% → %d%% (Lux: %.0f/%d)",
                    light_id,
                    current_pct,
                    target_bri,
                    current_lux,
                    target_lux,
                )

    # ── Weather Boost ─────────────────────────────────────────────────

    @staticmethod
    def _get_weather_condition(states: list[dict], wb_cfg: dict) -> str:
        """Liest die aktuelle Wetterbedingung aus der konfigurierten weather-Entity."""
        configured = wb_cfg.get("weather_entity", "")
        # Gleiche Logik wie Cover-Automatik: konfiguriert > forecast_home > erste
        entity = None
        for s in states:
            eid = s.get("entity_id", "")
            if configured and eid == configured:
                entity = s
                break
            if not configured and eid == "weather.forecast_home":
                entity = s
                break
            if eid.startswith("weather.") and not entity:
                entity = s
        return (entity.get("state") or "").lower() if entity else ""

    async def _check_weather_boost(self, cfg: dict, states: list[dict]):
        """Bei Bewoelkung/Regen: Helligkeit der eingeschalteten Lichter erhoehen.

        Idee: An einem trueben Tag reicht das Tageslicht oft nicht,
        aber die Daemmerung ist noch nicht erreicht. Dann werden
        eingeschaltete Lichter um X% heller geschaltet.
        """
        wb_cfg = cfg.get("weather_boost", {})
        if not wb_cfg.get("enabled"):
            return

        # Feature 7: Nur tagsueber aktiv — nach Night-Dimming-Start kein Boost
        now = datetime.now(_LOCAL_TZ)
        night_start = cfg.get("night_dimming_start_hour", 21)
        night_end = cfg.get("presence_control", {}).get("night_end_hour", 6)
        if now.hour >= night_start or now.hour < night_end:
            # Nachts: Falls Boost noch aktiv war, sauber aufloesen
            if self.redis:
                prev = await _safe_redis(self.redis, "get", _R_WEATHER_BOOST)
                if prev:
                    await _safe_redis(self.redis, "delete", _R_WEATHER_BOOST)
                    logger.info(
                        "Wetter-Boost deaktiviert (Nachtmodus ab %d Uhr)", night_start
                    )
            return

        condition = self._get_weather_condition(states, wb_cfg)
        if not condition:
            return

        # Welcher Boost gilt?
        rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy"}
        cloud_conditions = {"cloudy", "fog"}
        boost_pct = 0
        if condition in rain_conditions:
            boost_pct = wb_cfg.get("rain_boost_pct", 25)
        elif condition in cloud_conditions:
            boost_pct = wb_cfg.get("cloud_boost_pct", 15)

        # Boost-Status tracken (Redis): Nur aendern wenn Status wechselt
        was_boosting = False
        if self.redis:
            prev = await _safe_redis(self.redis, "get", _R_WEATHER_BOOST)
            was_boosting = bool(prev)

        if boost_pct == 0:
            # Kein Boost noetig — wenn vorher aktiv war, Helligkeit zuruecksetzen
            if was_boosting and self.redis:
                await _safe_redis(self.redis, "delete", _R_WEATHER_BOOST)
                await self._restore_adaptive_brightness(cfg)
                logger.info(
                    "Wetter-Boost aufgehoben + Helligkeit zurueckgesetzt (Wetter: %s)",
                    condition,
                )
            return

        if was_boosting:
            # Boost laeuft schon — TTL erneuern, aber Lichter nicht nochmal anpassen
            if self.redis:
                await _safe_redis(
                    self.redis, "set", _R_WEATHER_BOOST, condition, ex=900
                )
            return

        # Neuen Boost aktivieren
        if self.redis:
            await _safe_redis(self.redis, "set", _R_WEATHER_BOOST, condition, ex=900)

        profiles = get_room_profiles()
        rooms = profiles.get("rooms", {})
        boosted = 0

        for room_name, room_cfg in rooms.items():
            lights = self._get_room_lights(room_name, room_cfg)
            for light_id in lights:
                ha_state = await self.ha.get_state(light_id)
                if not ha_state or ha_state.get("state") != "on":
                    continue
                if await self.is_manual_override_active(light_id):
                    continue

                attrs = ha_state.get("attributes", {})
                current_bri_raw = attrs.get("brightness", 0)
                current_pct = round(current_bri_raw / 255 * 100)
                new_pct = min(100, current_pct + boost_pct)
                if new_pct <= current_pct:
                    continue

                await self.ha.call_service(
                    "light",
                    "turn_on",
                    {
                        "entity_id": light_id,
                        "brightness_pct": new_pct,
                        "transition": 5,
                    },
                )
                boosted += 1

        if boosted > 0:
            logger.info(
                "Wetter-Boost: %d Lichter +%d%% (Wetter: %s)",
                boosted,
                boost_pct,
                condition,
            )

    # ── Cover-Licht Koordination ─────────────────────────────────────

    async def on_cover_position_change(
        self, entity_id: str, position: int, reason: str = ""
    ):
        """Reagiert auf Cover-Positionsaenderung → Licht anpassen.

        Wenn ein Cover schliesst (Sonnenschutz, Wetter), wird es im Raum
        dunkler → Licht heller. Wenn es oeffnet, wird Tageslicht mehr
        → Licht kann gedimmt werden.

        Trigger kommt von proactive._auto_cover_action().
        """
        cfg = yaml_config.get("lighting", {})
        if not cfg.get("enabled", True):
            return

        # Nur reagieren wenn Lux-Adaptiv NICHT aktiv ist (sonst uebernimmt der Lux-Sensor)
        lux_cfg = cfg.get("lux_adaptive", {})
        if lux_cfg.get("enabled"):
            return  # Lux-Sensor reagiert schneller und genauer

        # Raum fuer das Cover finden
        profiles = get_room_profiles()
        rooms = profiles.get("rooms", {})
        cover_room = None
        for room_name, room_cfg in rooms.items():
            covers = room_cfg.get("cover_entities", [])
            if entity_id in covers:
                cover_room = room_name
                break

        if not cover_room:
            # Fallback: Raumnamen aus Entity extrahieren
            parts = entity_id.replace("cover.", "").split("_")
            for room_name in rooms:
                if room_name.lower() in entity_id.lower():
                    cover_room = room_name
                    break

        if not cover_room:
            return

        room_cfg = rooms.get(cover_room, {})
        lights = self._get_room_lights(cover_room, room_cfg)
        if not lights:
            return

        # Cover schliesst (Position < 50%) → Raum wird dunkler → Licht anpassen
        for light_id in lights:
            ha_state = await self.ha.get_state(light_id)
            if not ha_state or ha_state.get("state") != "on":
                continue
            if await self.is_manual_override_active(light_id):
                continue

            attrs = ha_state.get("attributes", {})
            current_pct = round(attrs.get("brightness", 128) / 255 * 100)
            target = FunctionExecutor.get_adaptive_brightness(cover_room, light_id)

            # Cover schliesst → Licht muss heller (Tageslicht blockiert)
            if position < 30 and current_pct < target:
                await self.ha.call_service(
                    "light",
                    "turn_on",
                    {
                        "entity_id": light_id,
                        "brightness_pct": target,
                        "transition": 10,
                    },
                )
                logger.info(
                    "Cover-Licht: %s → %d%% (Cover %s auf %d%%)",
                    light_id,
                    target,
                    entity_id,
                    position,
                )

    async def _restore_adaptive_brightness(self, cfg: dict):
        """Setzt alle eingeschalteten Lichter auf ihre adaptive Helligkeit zurueck.

        Wird aufgerufen wenn Weather-Boost endet (Wetter klart auf).
        """
        profiles = get_room_profiles()
        rooms = profiles.get("rooms", {})
        restored = 0
        for room_name, room_cfg in rooms.items():
            lights = self._get_room_lights(room_name, room_cfg)
            for light_id in lights:
                ha_state = await self.ha.get_state(light_id)
                if not ha_state or ha_state.get("state") != "on":
                    continue
                if await self.is_manual_override_active(light_id):
                    continue
                target = FunctionExecutor.get_adaptive_brightness(room_name, light_id)
                attrs = ha_state.get("attributes", {})
                current_pct = round(attrs.get("brightness", 128) / 255 * 100)
                if abs(current_pct - target) < 5:
                    continue
                await self.ha.call_service(
                    "light",
                    "turn_on",
                    {
                        "entity_id": light_id,
                        "brightness_pct": target,
                        "transition": 10,
                    },
                )
                restored += 1
        if restored > 0:
            logger.info(
                "Brightness Restore: %d Lichter auf adaptive Helligkeit", restored
            )

    # ── Manual Override ────────────────────────────────────────────────

    async def record_manual_override(self, entity_id: str):
        """Markiert entity als manuell gesteuert (TTL-basiert).

        Liest manual_override_minutes aus lighting.presence_control.
        Fallback: cover_automation.manual_override_hours * 60 (fuer einheitliche Steuerung).
        """
        if not self.redis:
            return
        cfg = yaml_config.get("lighting", {}).get("presence_control", {})
        ttl_min = cfg.get("manual_override_minutes", None)
        if ttl_min is None:
            # Fallback: Cover-Setting (in Stunden) umrechnen
            cover_hours = (
                yaml_config.get("seasonal_actions", {})
                .get("cover_automation", {})
                .get("manual_override_hours", 2)
            )
            ttl_min = int(cover_hours * 60)
        await _safe_redis(
            self.redis, "set", f"{_R_OVERRIDE}{entity_id}", "1", ex=ttl_min * 60
        )
        logger.debug("Manual Override: %s fuer %d Min", entity_id, ttl_min)

    async def is_manual_override_active(self, entity_id: str) -> bool:
        """Prueft ob Override noch aktiv."""
        if not self.redis:
            return False
        val = await self.redis.get(f"{_R_OVERRIDE}{entity_id}")
        return val is not None

    # ── Helper ─────────────────────────────────────────────────────────

    def _get_room_lights(self, room: str, room_cfg: dict = None) -> list[str]:
        """Light-Entities fuer einen Raum aus room_profiles."""
        if room_cfg is None:
            profiles = get_room_profiles()
            room_cfg = profiles.get("rooms", {}).get(room, {})
        lights = room_cfg.get("light_entities", [])
        if isinstance(lights, list):
            return [l for l in lights if l]
        return []

    def _is_night(self, pc: dict = None) -> bool:
        """Prueft ob aktuell Nacht ist (konfigurierbar)."""
        if pc is None:
            pc = yaml_config.get("lighting", {}).get("presence_control", {})
        now_h = datetime.now(_LOCAL_TZ).hour
        start = pc.get("night_start_hour", 22)
        end = pc.get("night_end_hour", 6)
        if start > end:
            return now_h >= start or now_h < end
        return start <= now_h < end

    def _is_morning_window(self) -> bool:
        """Prueft ob aktuell Morgen-Fenster (Aufwach-Zeit)."""
        bed_cfg = yaml_config.get("lighting", {}).get("bed_sensors", {})
        now_h = datetime.now(_LOCAL_TZ).hour
        start = bed_cfg.get("wakeup_window_start", 5)
        end = bed_cfg.get("wakeup_window_end", 9)
        return start <= now_h < end

    @staticmethod
    def _anyone_home(states: list[dict]) -> bool:
        """Prueft ob mindestens eine Person zuhause ist."""
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("person.") and s.get("state") == "home":
                return True
        return False

    def _find_room_for_light(self, entity_id: str, rooms: dict) -> Optional[str]:
        """Findet den Raum in dem ein Licht zugeordnet ist."""
        for room_name, room_cfg in rooms.items():
            lights = room_cfg.get("light_entities", [])
            if isinstance(lights, list) and entity_id in lights:
                return room_name
        return None
