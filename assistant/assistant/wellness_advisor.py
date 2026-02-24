"""
Wellness Advisor - Jarvis kuemmert sich um den Benutzer.

Fusioniert Daten aus Activity Engine, Mood Detector und Health Monitor
zu kontextsensitiven Wellness-Hinweisen:
- PC-Pause nach langer Bildschirmarbeit
- Stress-Intervention bei erkanntem Stress
- Mahlzeiten-Erinnerung
- Late-Night-Hinweis
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)


class WellnessAdvisor:
    """Kontextsensitive Wellness-Hinweise — Jarvis kuemmert sich."""

    def __init__(self, ha_client, activity_engine, mood_detector):
        self.ha = ha_client
        self.activity = activity_engine
        self.mood = mood_detector
        self.redis: Optional[aioredis.Redis] = None
        self._notify_callback = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Konfiguration
        cfg = yaml_config.get("wellness", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_minutes", 15) * 60
        self.pc_break_minutes = cfg.get("pc_break_reminder_minutes", 120)
        self.stress_check = cfg.get("stress_check", True)
        self.meal_reminders = cfg.get("meal_reminders", True)
        self.meal_times = cfg.get("meal_times", {"lunch": 13, "dinner": 19})
        self.late_night_nudge = cfg.get("late_night_nudge", True)

        # HA-Entity-IDs fuer direkten Sensor-Check (konfigurierbar)
        entities = cfg.get("entities", {})
        self.pc_power_sensor = entities.get("pc_power", "")  # z.B. sensor.pc_power
        self.kitchen_motion_sensor = entities.get("kitchen_motion", "")
        self.hydration_check = cfg.get("hydration_reminder", True)
        self.hydration_interval_hours = cfg.get("hydration_interval_hours", 2)

    # ------------------------------------------------------------------
    # Anrede: Alle anwesenden Personen mit konfiguriertem Titel
    # ------------------------------------------------------------------

    async def _get_addressing(self) -> str:
        """Gibt die Anrede fuer alle anwesenden Personen zurueck.

        Nutzt persons.titles aus der YAML-Konfiguration (im UI einstellbar).
        Wenn niemand gefunden wird, Fallback auf primary_user-Titel oder 'Sir'.
        """
        titles = (yaml_config.get("persons") or {}).get("titles") or {}
        household = yaml_config.get("household") or {}
        primary = household.get("primary_user", "")

        # Wer ist zuhause?
        present_names = []
        if self.ha:
            try:
                states = await self.ha.get_states()
                if states:
                    for s in states:
                        eid = s.get("entity_id", "")
                        if eid.startswith("person.") and s.get("state") == "home":
                            name = s.get("attributes", {}).get(
                                "friendly_name", eid.split(".", 1)[-1]
                            )
                            present_names.append(name)
            except Exception as e:
                logger.debug("Presence-Check fuer Anrede fehlgeschlagen: %s", e)

        if not present_names:
            # Fallback: Primary User
            if primary:
                present_names = [primary]
            else:
                return "Sir"

        # Namen → Titel auflösen
        present_titles = []
        for name in present_names:
            title = titles.get(name.lower())
            if title:
                present_titles.append(title)
            else:
                present_titles.append(name)

        # Duplikate entfernen, Reihenfolge beibehalten
        seen = set()
        unique = []
        for t in present_titles:
            if t.lower() not in seen:
                seen.add(t.lower())
                unique.append(t)

        if len(unique) == 1:
            return unique[0]
        if len(unique) == 2:
            return f"{unique[0]}, {unique[1]}"
        return ", ".join(unique[:-1]) + f" und {unique[-1]}"

    async def initialize(self, redis_client=None):
        """Initialisiert den Wellness Advisor."""
        self.redis = redis_client
        if self.enabled:
            logger.info("WellnessAdvisor initialisiert (Intervall: %ds)", self.check_interval)
        else:
            logger.info("WellnessAdvisor deaktiviert")

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Wellness-Meldungen."""
        self._notify_callback = callback

    async def start(self):
        """Startet den Wellness-Loop."""
        if not self.enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._wellness_loop())

    async def stop(self):
        """Stoppt den Wellness-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _wellness_loop(self):
        """Periodischer Wellness-Check."""
        # 5 Min nach Start warten (System stabilisieren)
        await asyncio.sleep(300)

        while self._running:
            try:
                # F-061: Wellness-Checks bei aktiven Notfaellen unterdruecken
                if self.redis:
                    active_threats = await self.redis.get("mha:threat:active")
                    if active_threats:
                        logger.debug("Wellness-Checks uebersprungen: aktive Bedrohung")
                        await asyncio.sleep(self.check_interval)
                        continue

                await self._check_pc_break()
                await self._check_stress_intervention()
                await self._check_meal_time()
                await self._check_late_night()
                await self._check_hydration()
            except Exception as e:
                logger.error("Wellness-Check Fehler: %s", e)

            await asyncio.sleep(self.check_interval)

    # ------------------------------------------------------------------
    # PC-Pause-Erinnerung
    # ------------------------------------------------------------------

    async def _check_pc_break(self):
        """Wenn User seit X Minuten am PC sitzt -> Pause vorschlagen.

        Nutzt primaer den HA-PC-Power-Sensor (wenn konfiguriert),
        faellt zurueck auf Activity Engine.
        """
        if not self.redis:
            return

        user_at_pc = False

        # 1. Primaer: Echten HA-Sensor pruefen (PC-Stromverbrauch > 30W = an)
        if self.pc_power_sensor and self.ha:
            try:
                state = await self.ha.get_entity_state(self.pc_power_sensor)
                if state and state.get("state") not in ("unavailable", "unknown"):
                    power = float(state.get("state", 0))
                    user_at_pc = power > 30  # PC laeuft wenn > 30W
            except (ValueError, TypeError, Exception) as e:
                logger.debug("PC-Power-Sensor Fehler: %s", e)

        # 2. Fallback: Activity Engine
        if not user_at_pc:
            try:
                detection = await self.activity.detect_activity()
                activity = detection.get("activity", "")
                user_at_pc = activity == "focused"
            except Exception:
                return

        if not user_at_pc:
            # Nicht am PC -> Timer zuruecksetzen
            await self.redis.delete("mha:wellness:pc_start")
            return

        now = datetime.now()
        pc_start = await self.redis.get("mha:wellness:pc_start")

        if not pc_start:
            # Timer starten
            await self.redis.setex("mha:wellness:pc_start", 86400, now.isoformat())
            return

        try:
            start_dt = datetime.fromisoformat(pc_start)
        except (ValueError, TypeError):
            await self.redis.setex("mha:wellness:pc_start", 86400, now.isoformat())
            return

        minutes = (now - start_dt).total_seconds() / 60

        if minutes < self.pc_break_minutes:
            return

        # Cooldown: 1h zwischen Erinnerungen
        last = await self.redis.get("mha:wellness:last_break_reminder")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt).total_seconds() < 3600:
                    return
            except (ValueError, TypeError):
                pass

        hours = int(minutes // 60)
        mins = int(minutes % 60)

        if hours >= 1:
            time_str = f"{hours}h{mins:02d}min"
        else:
            time_str = f"{mins} Minuten"

        addressing = await self._get_addressing()
        await self._send_nudge(
            "pc_break",
            f"Du sitzt seit {time_str} am Rechner, {addressing}. "
            f"Eine kurze Pause waere nicht das Schlechteste.",
        )
        await self.redis.setex("mha:wellness:last_break_reminder", 86400, now.isoformat())
        # Timer zuruecksetzen damit nach Cooldown nicht sofort wieder feuert
        await self.redis.setex("mha:wellness:pc_start", 86400, now.isoformat())

    # ------------------------------------------------------------------
    # Stress-Intervention
    # ------------------------------------------------------------------

    async def _check_stress_intervention(self):
        """Bei erkanntem Stress sanft intervenieren."""
        if not self.stress_check or not self.redis:
            return

        mood_data = self.mood.get_current_mood()
        mood = mood_data.get("mood", "neutral")
        stress_level = mood_data.get("stress_level", 0.0)

        if mood not in ("stressed", "frustrated"):
            return

        # Nur einmal pro Stress-Episode (30 Min Cooldown)
        last = await self.redis.get("mha:wellness:last_stress_nudge")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (datetime.now() - last_dt).total_seconds() < 1800:
                    return
            except (ValueError, TypeError):
                pass

        await self.redis.setex("mha:wellness:last_stress_nudge", 86400, datetime.now().isoformat())

        addressing = await self._get_addressing()
        if stress_level >= 0.7:
            msg = f"{addressing}, der Stresspegel ist deutlich erhoert. Soll ich das Licht etwas dimmen?"
        elif mood == "frustrated":
            msg = f"Ich bemerke etwas Frustration, {addressing}. Kann ich irgendwie helfen?"
        else:
            msg = f"{addressing}, wenn ich anmerken darf — es scheint etwas stressig. Kurze Pause?"

        await self._send_nudge("stress_detected", msg)

    # ------------------------------------------------------------------
    # Mahlzeiten-Erinnerung
    # ------------------------------------------------------------------

    async def _check_meal_time(self):
        """Erinnert an Mahlzeiten wenn die uebliche Zeit ueberschritten ist."""
        if not self.meal_reminders or not self.redis:
            return

        now = datetime.now()
        hour = now.hour

        for meal, target_hour in self.meal_times.items():
            # Nur erinnern wenn 60+ Min nach der ueblichen Zeit
            if hour != (target_hour + 1) % 24:
                continue

            # Cooldown: Nur 1x pro Mahlzeit pro Tag
            key = f"mha:wellness:meal_{meal}_{now.strftime('%Y-%m-%d')}"
            if await self.redis.exists(key):
                continue

            # Pruefen ob Kueche aktiv war (= wahrscheinlich gegessen)
            kitchen_was_active = False
            if self.kitchen_motion_sensor and self.ha:
                try:
                    state = await self.ha.get_entity_state(self.kitchen_motion_sensor)
                    if state and state.get("state") == "on":
                        kitchen_was_active = True
                except Exception as e:
                    logger.debug("Kuechen-Sensor Fehler: %s", e)

            if kitchen_was_active:
                # Kueche ist gerade aktiv — User kocht/isst vermutlich
                continue

            try:
                detection = await self.activity.detect_activity()
                activity = detection.get("activity", "")
                if activity in ("away", "sleeping"):
                    continue
            except Exception as e:
                logger.debug("Activity-Check fuer Mahlzeit fehlgeschlagen: %s", e)

            await self.redis.setex(key, 86400, "1")  # 24h TTL

            meal_de = "Mittagessen" if meal == "lunch" else "Abendessen"
            addressing = await self._get_addressing()
            await self._send_nudge(
                "meal_reminder",
                f"Es ist {hour} Uhr, {addressing}. Schon {meal_de.lower()} gehabt?",
            )

    # ------------------------------------------------------------------
    # Late-Night-Hinweis
    # ------------------------------------------------------------------

    async def _check_late_night(self):
        """Nach Mitternacht: Sanfter Hinweis auf die Uhrzeit."""
        if not self.late_night_nudge or not self.redis:
            return

        hour = datetime.now().hour

        # Nur zwischen 0 und 4 Uhr
        if hour >= 5:
            return

        try:
            detection = await self.activity.detect_activity()
            activity = detection.get("activity", "")
            if activity in ("sleeping", "away"):
                return
        except Exception as e:
            logger.debug("Late-Night Activity-Check fehlgeschlagen: %s", e)
            return

        # Nur 1x pro Nacht (Redis TTL 6h)
        key = "mha:wellness:last_latenight"
        if await self.redis.exists(key):
            return

        await self.redis.setex(key, 6 * 3600, "1")

        addressing = await self._get_addressing()
        await self._send_nudge(
            "late_night",
            f"Es ist {hour} Uhr, {addressing}. Nur zur Kenntnis.",
        )

    # ------------------------------------------------------------------
    # Hydration-Erinnerung
    # ------------------------------------------------------------------

    async def _check_hydration(self):
        """Erinnerung ans Trinken alle X Stunden (nur wenn User aktiv)."""
        if not self.hydration_check or not self.redis:
            return

        hour = datetime.now().hour
        if hour < 8 or hour > 22:
            return  # Nachts nicht erinnern

        key = "mha:wellness:last_hydration"
        last = await self.redis.get(key)
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                elapsed_h = (datetime.now() - last_dt).total_seconds() / 3600
                if elapsed_h < self.hydration_interval_hours:
                    return
            except (ValueError, TypeError):
                pass

        # Nur wenn User aktiv (nicht away/sleeping)
        try:
            detection = await self.activity.detect_activity()
            activity = detection.get("activity", "")
            if activity in ("away", "sleeping"):
                return
        except Exception as e:
            logger.debug("Hydration Activity-Check fehlgeschlagen: %s", e)
            return

        await self.redis.setex(key, 86400, datetime.now().isoformat())
        addressing = await self._get_addressing()
        await self._send_nudge(
            "hydration",
            f"{addressing}, ein Glas Wasser waere jetzt keine schlechte Idee.",
        )

    # ------------------------------------------------------------------
    # Nudge senden
    # ------------------------------------------------------------------

    async def _send_nudge(self, nudge_type: str, message: str):
        """Sendet einen Wellness-Hinweis ueber den Callback."""
        if not self._notify_callback:
            logger.debug("Wellness-Nudge ohne Callback: %s", message)
            return

        try:
            await self._notify_callback(nudge_type, message)
            logger.info("Wellness [%s]: %s", nudge_type, message)
        except Exception as e:
            logger.error("Wellness-Nudge Fehler: %s", e)
