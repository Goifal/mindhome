"""
Time Awareness - Phase 6.6: Jarvis hat ein Zeitgefuehl.

Ueberwacht wie lange Geraete laufen, zaehlt Nutzungen pro Tag,
und meldet proaktiv wenn etwas auffaellig ist:

- Ofen laeuft > 60 Min -> Hinweis
- Buegeleisen > 30 Min -> Hinweis
- Licht in leerem Raum > 30 Min -> Hinweis
- Fenster offen bei <10°C > 2h -> Hinweis
- PC ohne Pause > 6h -> Hinweis
- Kaffeemaschine: "Das ist dein dritter Kaffee heute."

Nutzt Redis fuer Tracking und wird vom ProactiveManager aufgerufen.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Redis-Key-Prefixes
KEY_DEVICE_START = "mha:time:device_start:"    # Wann ein Geraet zuletzt gestartet wurde
KEY_DEVICE_NOTIFIED = "mha:time:notified:"     # Ob schon eine Meldung gesendet wurde
KEY_COUNTER = "mha:time:counter:"              # Tages-Zaehler (z.B. Kaffee)
KEY_COUNTER_DATE = "mha:time:counter_date"     # Datum des aktuellen Zaehlers
KEY_PC_SESSION = "mha:time:pc_session_start"   # Wann die aktuelle PC-Session begonnen hat


class TimeAwareness:
    """Ueberwacht Geraete-Laufzeiten und zaehlt Nutzungen."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[redis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Konfiguration
        ta_cfg = yaml_config.get("time_awareness", {})
        self.enabled = ta_cfg.get("enabled", True)
        self.check_interval = ta_cfg.get("check_interval_minutes", 5) * 60

        thresholds = ta_cfg.get("thresholds", {})
        self.threshold_oven = thresholds.get("oven", 60)
        self.threshold_iron = thresholds.get("iron", 30)
        self.threshold_light_empty = thresholds.get("light_empty_room", 30)
        self.threshold_window_cold = thresholds.get("window_open_cold", 120)
        self.threshold_pc_no_break = thresholds.get("pc_no_break", 360)
        self.threshold_washer = thresholds.get("washer", 180)
        self.threshold_dryer = thresholds.get("dryer", 150)
        self.threshold_dishwasher = thresholds.get("dishwasher", 180)

        # Welche Zaehler aktiv sind
        counters_cfg = ta_cfg.get("counters", {})
        self.track_coffee = counters_cfg.get("coffee_machine", True)

        # Callback fuer Meldungen (wird von brain.py gesetzt)
        self._notify_callback = None

        # Alerts die noch nicht gemeldet wurden
        self._pending_alerts: list[dict] = []

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis:
            await self._reset_daily_counters_if_needed()
        logger.info("TimeAwareness initialisiert (enabled: %s)", self.enabled)

    def set_notify_callback(self, callback):
        """Setzt die Callback-Funktion fuer proaktive Meldungen."""
        self._notify_callback = callback

    async def start(self):
        """Startet den periodischen Check-Loop."""
        if not self.enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("TimeAwareness gestartet (Intervall: %ds)", self.check_interval)

    async def stop(self):
        """Stoppt den Check-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TimeAwareness gestoppt")

    # ------------------------------------------------------------------
    # Periodischer Check
    # ------------------------------------------------------------------

    async def _check_loop(self):
        """Prueft periodisch alle ueberwachten Geraete."""
        while self._running:
            try:
                await self._run_checks()
            except Exception as e:
                logger.error("TimeAwareness Check-Fehler: %s", e)
            await asyncio.sleep(self.check_interval)

    async def _run_checks(self):
        """Fuehrt alle Checks durch."""
        states = await self.ha.get_states()
        if not states:
            return

        await self._reset_daily_counters_if_needed()

        alerts = []

        # 1. Ofen / Herd
        alert = await self._check_appliance(
            states, ["switch.oven", "switch.ofen", "switch.herd", "switch.backofen"],
            self.threshold_oven, "oven",
            "Der Ofen laeuft seit {minutes} Minuten. Absichtlich?"
        )
        if alert:
            alerts.append(alert)

        # 2. Buegeleisen
        alert = await self._check_appliance(
            states, ["switch.iron", "switch.buegeleisen"],
            self.threshold_iron, "iron",
            "Das Buegeleisen laeuft seit {minutes} Minuten. Noch in Benutzung?"
        )
        if alert:
            alerts.append(alert)

        # 2b. Waschmaschine
        alert = await self._check_appliance(
            states,
            ["switch.washer", "switch.waschmaschine", "sensor.waschmaschine_status"],
            self.threshold_washer, "washer",
            "Die Waschmaschine laeuft seit {minutes} Minuten. Waesche duerfte fertig sein."
        )
        if alert:
            alerts.append(alert)

        # 2c. Trockner
        alert = await self._check_appliance(
            states,
            ["switch.dryer", "switch.trockner", "sensor.trockner_status"],
            self.threshold_dryer, "dryer",
            "Der Trockner laeuft seit {minutes} Minuten. Zeitnah ausraeumen spart Buegeln."
        )
        if alert:
            alerts.append(alert)

        # 2d. Geschirrspueler
        alert = await self._check_appliance(
            states,
            ["switch.dishwasher", "switch.geschirrspueler", "sensor.geschirrspueler_status"],
            self.threshold_dishwasher, "dishwasher",
            "Der Geschirrspueler laeuft seit {minutes} Minuten. Duerfte durchgelaufen sein."
        )
        if alert:
            alerts.append(alert)

        # 3. Licht in leerem Raum
        light_alerts = await self._check_lights_empty_rooms(states)
        alerts.extend(light_alerts)

        # 4. Fenster offen bei Kaelte
        window_alerts = await self._check_windows_cold(states)
        alerts.extend(window_alerts)

        # 4b. Heizung laeuft + Fenster offen (unabhaengig von Temperatur)
        heating_window_alerts = await self._check_heating_window_open(states)
        alerts.extend(heating_window_alerts)

        # 5. PC ohne Pause
        alert = await self._check_pc_session(states)
        if alert:
            alerts.append(alert)

        # Alerts melden
        for alert in alerts:
            await self._send_alert(alert)

    # ------------------------------------------------------------------
    # Einzelne Checks
    # ------------------------------------------------------------------

    async def _check_appliance(
        self, states: list[dict], entity_ids: list[str],
        threshold_minutes: int, device_key: str, message_template: str,
    ) -> Optional[dict]:
        """Prueft ob ein Geraet zu lange laeuft."""
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id not in entity_ids:
                continue

            if state.get("state") in ("on", "active", "heating"):
                minutes = await self._get_running_minutes(entity_id, device_key)
                if minutes and minutes >= threshold_minutes:
                    if not await self._was_notified(device_key):
                        await self._mark_notified(device_key)
                        return {
                            "type": "appliance_running",
                            "device": device_key,
                            "message": message_template.format(minutes=int(minutes)),
                            "urgency": "medium",
                        }
            else:
                # Geraet aus -> Timer zuruecksetzen
                await self._clear_device_timer(device_key)
        return None

    async def _check_lights_empty_rooms(self, states: list[dict]) -> list[dict]:
        """Prueft ob Lichter in leeren Raeumen an sind."""
        alerts = []

        # Welche Raeume haben Bewegung?
        active_rooms = set()
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("binary_sensor.motion") and state.get("state") == "on":
                # Raum-Name aus Entity-ID extrahieren
                room = entity_id.replace("binary_sensor.motion_", "").replace("binary_sensor.bewegung_", "")
                active_rooms.add(room)

        # Personen-Standorte
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("person."):
                attrs = state.get("attributes", {})
                zone = attrs.get("zone", "")
                if zone:
                    active_rooms.add(zone.lower())

        # Lichter pruefen
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("light.") or state.get("state") != "on":
                continue

            light_room = entity_id.split(".", 1)[1].split("_")[0]
            if light_room in active_rooms:
                continue

            device_key = f"light_{light_room}"
            minutes = await self._get_running_minutes(entity_id, device_key)
            if minutes and minutes >= self.threshold_light_empty:
                if not await self._was_notified(device_key):
                    await self._mark_notified(device_key)
                    friendly = state.get("attributes", {}).get("friendly_name", entity_id)
                    alerts.append({
                        "type": "light_empty_room",
                        "device": device_key,
                        "message": f"{friendly} ist seit {int(minutes)} Minuten an, aber niemand scheint dort zu sein.",
                        "urgency": "low",
                    })
        return alerts

    async def _check_windows_cold(self, states: list[dict]) -> list[dict]:
        """Prueft ob Fenster bei kaltem Wetter offen sind."""
        alerts = []

        # Aussentemperatur holen
        outside_temp = None
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("weather."):
                outside_temp = state.get("attributes", {}).get("temperature")
                break
            if "outdoor" in entity_id and "temperature" in entity_id:
                try:
                    outside_temp = float(state.get("state", 0))
                except (ValueError, TypeError):
                    pass

        if outside_temp is None or outside_temp >= 10:
            return alerts

        # Offene Fenster finden
        for state in states:
            entity_id = state.get("entity_id", "")
            if not ("window" in entity_id or "fenster" in entity_id):
                continue
            if state.get("state") != "on":
                continue

            device_key = f"window_{entity_id}"
            minutes = await self._get_running_minutes(entity_id, device_key)
            if minutes and minutes >= self.threshold_window_cold:
                if not await self._was_notified(device_key):
                    await self._mark_notified(device_key)
                    friendly = state.get("attributes", {}).get("friendly_name", entity_id)
                    alerts.append({
                        "type": "window_open_cold",
                        "device": device_key,
                        "message": f"{friendly} ist seit {int(minutes)} Minuten offen. Draussen sind es {outside_temp}°C.",
                        "urgency": "medium",
                    })
        return alerts

    async def _check_heating_window_open(self, states: list[dict]) -> list[dict]:
        """Prueft ob Heizung laeuft waehrend ein Fenster offen ist."""
        alerts = []

        # Pruefen ob irgendein Climate-Entity aktiv heizt
        heating_active = False
        heating_rooms = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("climate."):
                continue
            hvac_action = state.get("attributes", {}).get("hvac_action", "")
            hvac_mode = state.get("state", "")
            if hvac_action == "heating" or hvac_mode == "heat":
                heating_active = True
                friendly = state.get("attributes", {}).get("friendly_name", entity_id)
                heating_rooms.append(friendly)

        if not heating_active:
            return alerts

        # Offene Fenster finden
        for state in states:
            entity_id = state.get("entity_id", "")
            if not ("window" in entity_id or "fenster" in entity_id):
                continue
            if not entity_id.startswith("binary_sensor."):
                continue
            if state.get("state") != "on":
                continue

            device_key = f"heating_window_{entity_id}"
            if not await self._was_notified(device_key):
                await self._mark_notified(device_key)
                friendly = state.get("attributes", {}).get("friendly_name", entity_id)
                alerts.append({
                    "type": "heating_window_open",
                    "device": device_key,
                    "message": f"Ein Fenster ist offen ({friendly}) waehrend die Heizung laeuft.",
                    "urgency": "medium",
                })

        return alerts

    async def _check_pc_session(self, states: list[dict]) -> Optional[dict]:
        """Prueft ob der PC zu lange ohne Pause laeuft."""
        pc_sensors = yaml_config.get("activity", {}).get("entities", {}).get("pc_sensors", [])
        pc_active = False
        for state in states:
            if state.get("entity_id", "") in pc_sensors:
                if state.get("state") in ("on", "active"):
                    pc_active = True
                    break

        if not pc_active:
            # PC aus -> Session-Timer zuruecksetzen
            if self.redis:
                await self.redis.delete(KEY_PC_SESSION)
                await self.redis.delete(KEY_DEVICE_NOTIFIED + "pc_session")
            return None

        # PC laeuft -> Session-Dauer pruefen
        minutes = await self._get_running_minutes("pc", "pc_session")
        if minutes and minutes >= self.threshold_pc_no_break:
            if not await self._was_notified("pc_session"):
                await self._mark_notified("pc_session")
                hours = int(minutes / 60)
                return {
                    "type": "pc_no_break",
                    "device": "pc_session",
                    "message": f"Du sitzt seit {hours} Stunden am PC. Eine kurze Pause waere empfehlenswert.",
                    "urgency": "low",
                }
        return None

    # ------------------------------------------------------------------
    # Tages-Zaehler (z.B. Kaffee)
    # ------------------------------------------------------------------

    async def increment_counter(self, counter_name: str) -> int:
        """Erhoeht einen Tages-Zaehler und gibt den neuen Wert zurueck."""
        if not self.redis:
            return 0

        await self._reset_daily_counters_if_needed()
        key = KEY_COUNTER + counter_name
        new_val = await self.redis.incr(key)
        await self.redis.expire(key, 86400)  # 24h TTL
        return int(new_val)

    async def get_counter(self, counter_name: str) -> int:
        """Holt den aktuellen Wert eines Tages-Zaehlers."""
        if not self.redis:
            return 0
        val = await self.redis.get(KEY_COUNTER + counter_name)
        return int(val) if val else 0

    def get_counter_comment(self, counter_name: str, count: int) -> Optional[str]:
        """Gibt einen optionalen Kommentar zum Zaehlerstand zurueck."""
        if counter_name == "coffee":
            comments = {
                2: "Zweiter Kaffee. Noch im gruenen Bereich.",
                3: "Das ist Kaffee Nummer drei heute.",
                4: "Vier Kaffee. Die Bohnen sollten sich Sorgen machen.",
                5: "Fuenfter Kaffee. Ich sage nichts. Ich denke mir meinen Teil.",
            }
            if count >= 6:
                return f"Kaffee Nummer {count}. Das ist jetzt keine Empfehlung mehr."
            return comments.get(count)
        return None

    async def _reset_daily_counters_if_needed(self):
        """Setzt Tages-Zaehler zurueck wenn ein neuer Tag begonnen hat."""
        if not self.redis:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        stored_date = await self.redis.get(KEY_COUNTER_DATE)
        if stored_date and stored_date != today:
            # Neuer Tag -> alle Zaehler loeschen
            keys = []
            async for key in self.redis.scan_iter(f"{KEY_COUNTER}*"):
                keys.append(key)
            if keys:
                await self.redis.delete(*keys)
            logger.info("Tages-Zaehler zurueckgesetzt")
        await self.redis.set(KEY_COUNTER_DATE, today)

    # ------------------------------------------------------------------
    # Redis-Hilfsfunktionen
    # ------------------------------------------------------------------

    async def _get_running_minutes(self, entity_id: str, device_key: str) -> Optional[float]:
        """Gibt zurueck wie viele Minuten ein Geraet laeuft."""
        if not self.redis:
            return None

        key = KEY_DEVICE_START + device_key
        start_time = await self.redis.get(key)

        if start_time is None:
            # Erster Check -> Timer starten
            await self.redis.set(key, str(datetime.now().timestamp()))
            await self.redis.expire(key, 86400)
            return 0.0

        start_ts = float(start_time)
        elapsed_seconds = datetime.now().timestamp() - start_ts
        return elapsed_seconds / 60.0

    async def _was_notified(self, device_key: str) -> bool:
        """Prueft ob fuer dieses Geraet bereits eine Meldung gesendet wurde."""
        if not self.redis:
            return False
        return await self.redis.exists(KEY_DEVICE_NOTIFIED + device_key) > 0

    async def _mark_notified(self, device_key: str):
        """Markiert ein Geraet als gemeldet (1h Cooldown)."""
        if not self.redis:
            return
        await self.redis.set(KEY_DEVICE_NOTIFIED + device_key, "1")
        await self.redis.expire(KEY_DEVICE_NOTIFIED + device_key, 3600)

    async def _clear_device_timer(self, device_key: str):
        """Setzt Timer und Notified-Flag zurueck."""
        if not self.redis:
            return
        await self.redis.delete(KEY_DEVICE_START + device_key)
        await self.redis.delete(KEY_DEVICE_NOTIFIED + device_key)

    async def _send_alert(self, alert: dict):
        """Sendet eine Meldung ueber den Callback."""
        if self._notify_callback:
            try:
                await self._notify_callback(alert)
            except Exception as e:
                logger.error("TimeAwareness Alert-Fehler: %s", e)
        logger.info(
            "TimeAwareness Alert [%s]: %s",
            alert.get("type", "?"), alert.get("message", ""),
        )

    # ------------------------------------------------------------------
    # Kontext fuer System Prompt
    # ------------------------------------------------------------------

    async def get_context_hints(self) -> list[str]:
        """Gibt aktuelle Zeitgefuehl-Hinweise fuer den System Prompt zurueck."""
        hints = []

        if not self.redis:
            return hints

        # Kaffee-Zaehler
        if self.track_coffee:
            coffee_count = await self.get_counter("coffee")
            if coffee_count >= 2:
                hints.append(f"User hat heute {coffee_count} Kaffee getrunken")

        # PC-Session-Dauer
        pc_minutes = await self._get_running_minutes("pc", "pc_session")
        if pc_minutes and pc_minutes > 120:
            hours = pc_minutes / 60
            hints.append(f"User sitzt seit {hours:.1f}h am PC")

        return hints
