"""
Wellness Advisor - Jarvis kuemmert sich um den Benutzer.

Fusioniert Daten aus Activity Engine, Mood Detector und Health Monitor
zu kontextsensitiven Wellness-Hinweisen:
- PC-Pause nach langer Bildschirmarbeit
- Stress-Intervention bei erkanntem Stress
- Mahlzeiten-Erinnerung
- Late-Night-Hinweis mit Kalender-Vorschau
- Hydration-Erinnerung
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title

logger = logging.getLogger(__name__)


async def _safe_redis(redis_client, method: str, *args, **kwargs):
    """Redis-Operation mit Fehlerbehandlung — gibt None bei Fehler zurueck."""
    try:
        return await getattr(redis_client, method)(*args, **kwargs)
    except Exception as e:
        logger.debug("Redis %s fehlgeschlagen: %s", method, e)
        return None


class WellnessAdvisor:
    """Kontextsensitive Wellness-Hinweise — Jarvis kuemmert sich."""

    def __init__(self, ha_client, activity_engine, mood_detector):
        self.ha = ha_client
        self.activity = activity_engine
        self.mood = mood_detector
        self.executor = None  # Phase 17.4: FunctionExecutor fuer Ambient Actions
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
                return get_person_title()

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

    def reload_config(self, cfg: dict):
        """Hot-Reload der WellnessAdvisor-Konfiguration."""
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_minutes", 15) * 60
        self.pc_break_minutes = cfg.get("pc_break_reminder_minutes", 120)
        self.stress_check = cfg.get("stress_check", True)
        self.meal_reminders = cfg.get("meal_reminders", True)
        self.meal_times = cfg.get("meal_times", {"lunch": 13, "dinner": 19})
        self.late_night_nudge = cfg.get("late_night_nudge", True)
        entities = cfg.get("entities", {})
        self.pc_power_sensor = entities.get("pc_power", "")
        self.kitchen_motion_sensor = entities.get("kitchen_motion", "")
        self.hydration_check = cfg.get("hydration_reminder", True)
        self.hydration_interval_hours = cfg.get("hydration_interval_hours", 2)
        logger.info("WellnessAdvisor Config reloaded (enabled=%s, interval=%ds)",
                     self.enabled, self.check_interval)

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
                await self._check_mood_ambient_actions()
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
                state = await self.ha.get_state(self.pc_power_sensor)
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
            await _safe_redis(self.redis, "delete", "mha:wellness:pc_start")
            return

        now = datetime.now()
        pc_start = await self.redis.get("mha:wellness:pc_start")

        if not pc_start:
            # Timer starten
            await _safe_redis(self.redis, "setex", "mha:wellness:pc_start", 86400, now.isoformat())
            return

        try:
            # Fix: Redis gibt bytes zurueck — decode vor fromisoformat
            pc_start_str = pc_start.decode() if isinstance(pc_start, bytes) else pc_start
            start_dt = datetime.fromisoformat(pc_start_str)
        except (ValueError, TypeError):
            await _safe_redis(self.redis, "setex", "mha:wellness:pc_start", 86400, now.isoformat())
            return

        minutes = (now - start_dt).total_seconds() / 60

        if minutes < self.pc_break_minutes:
            return

        # Cooldown: 1h zwischen Erinnerungen
        last = await self.redis.get("mha:wellness:last_break_reminder")
        if last:
            try:
                # Fix: Redis bytes decode
                last_str = last.decode() if isinstance(last, bytes) else last
                last_dt = datetime.fromisoformat(last_str)
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
        mood_data = self.mood.get_current_mood()
        mood = mood_data.get("mood", "neutral")

        # Mood-abhaengige Nachrichten: Bei Stress direkter, bei Muedigkeit sanfter
        if mood == "stressed" and hours >= 2:
            msg = random.choice([
                f"{addressing}, {time_str} am Rechner bei diesem Stresspegel. Kurze Pause — nicht optional.",
                f"{time_str} durchgehend, {addressing}. Fuenf Minuten Fenster auf, Augen zu. Ich pass hier auf.",
            ])
            urgency = "medium"
        elif mood == "tired":
            msg = random.choice([
                f"{addressing}, {time_str} am Rechner. Vielleicht reicht es fuer heute.",
                f"Seit {time_str} am Bildschirm, {addressing}. Morgen ist auch ein Tag.",
            ])
            urgency = "medium"
        elif hours >= 3:
            msg = random.choice([
                f"{time_str} am Rechner, {addressing}. Ich mache mir langsam Gedanken.",
                f"{addressing}, {time_str} ohne Pause. Darf ich anmerken — das ist ambitioniert.",
            ])
            urgency = "low"
        else:
            msg = random.choice([
                f"Du sitzt seit {time_str} am Rechner, {addressing}. Eine kurze Pause waere nicht das Schlechteste.",
                f"{time_str} Bildschirmzeit, {addressing}. Kurz aufstehen — ich halte die Stellung.",
                f"{addressing}, {time_str} durchgehend. Ein Glas Wasser und fuenf Minuten stehen.",
            ])
            urgency = "low"

        await self._send_nudge("pc_break", msg, urgency=urgency)
        await _safe_redis(self.redis, "setex", "mha:wellness:last_break_reminder", 86400, now.isoformat())
        # Timer zuruecksetzen damit nach Cooldown nicht sofort wieder feuert
        await _safe_redis(self.redis, "setex", "mha:wellness:pc_start", 86400, now.isoformat())

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
        mood_trend = self.mood.get_mood_trend()

        if mood not in ("stressed", "frustrated"):
            return

        # Bei sich verschlechterndem Trend kuerzerer Cooldown (15 statt 30 Min)
        cooldown_sec = 900 if mood_trend == "declining" else 1800

        # Nur einmal pro Stress-Episode
        last = await self.redis.get("mha:wellness:last_stress_nudge")
        if last:
            try:
                # Fix: Redis bytes decode
                last_str = last.decode() if isinstance(last, bytes) else last
                last_dt = datetime.fromisoformat(last_str)
                if (datetime.now() - last_dt).total_seconds() < cooldown_sec:
                    return
            except (ValueError, TypeError):
                pass

        await _safe_redis(self.redis, "setex", "mha:wellness:last_stress_nudge", 86400, datetime.now().isoformat())

        # Trend-Eskalation: Bei "declining" deutlichere Nachricht
        trend_hint = ""
        if mood_trend == "declining":
            trend_hint = "Ich sehe eine absteigende Tendenz. "

        addressing = await self._get_addressing()
        hour = datetime.now().hour

        if stress_level >= 0.7:
            # Hoher Stress: Konkreter Aktionsvorschlag
            if hour >= 20:
                msg = f"{addressing}, deutlich erhoehter Stress um {hour} Uhr. {trend_hint}Soll ich das Licht dimmen und Feierabend einlaeuten?"
            else:
                msg = random.choice([
                    f"{addressing}, der Stresspegel ist deutlich erhoert. {trend_hint}Licht auf 40%, fuenf Minuten — ich manage den Rest.",
                    f"Das Stresslevel ist hoch, {addressing}. {trend_hint}Soll ich das Licht runterfahren und fuer fuenf Minuten Ruhe sorgen?",
                ])
            urgency = "medium"
        elif mood == "frustrated":
            msg = random.choice([
                f"Läuft nicht rund, {addressing}. {trend_hint}Sag mir was du brauchst — ich kümmer mich.",
                f"{addressing}, ich merk das. {trend_hint}Kurz durchatmen — ich halte die Stellung.",
            ])
            urgency = "low"
        else:
            msg = random.choice([
                f"{addressing}, wenn ich anmerken darf — es scheint etwas stressig. {trend_hint}Kurze Pause?",
                f"Viel auf einmal heute, {addressing}. {trend_hint}Fuenf Minuten vom Bildschirm wuerden helfen.",
            ])
            urgency = "low"

        await self._send_nudge("stress_detected", msg, urgency=urgency)

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
                    state = await self.ha.get_state(self.kitchen_motion_sensor)
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

            await _safe_redis(self.redis, "setex", key, 86400, "1")  # 24h TTL

            meal_de = "Mittagessen" if meal == "lunch" else "Abendessen"
            addressing = await self._get_addressing()

            # Mood-abhaengig: Bei Stress kuerzer, bei guter Laune lockerer
            mood_data = self.mood.get_current_mood()
            mood = mood_data.get("mood", "neutral")

            if mood == "stressed":
                msg = f"{addressing}, {hour} Uhr. {meal_de.capitalize()}?"
            elif mood == "good":
                msg = random.choice([
                    f"Es ist {hour} Uhr, {addressing}. Wie sieht's mit {meal_de.lower()} aus?",
                    f"{addressing}, {hour} Uhr. Dein Magen wird sich ueber {meal_de.lower()} freuen.",
                ])
            else:
                msg = random.choice([
                    f"Es ist {hour} Uhr, {addressing}. Schon {meal_de.lower()} gehabt?",
                    f"{addressing}, nur zur Erinnerung — {hour} Uhr, {meal_de.lower()} steht an.",
                ])

            await self._send_nudge("meal_reminder", msg)

    # ------------------------------------------------------------------
    # Late-Night-Hinweis
    # ------------------------------------------------------------------

    async def _check_late_night(self):
        """Nach Mitternacht: Sanfter Hinweis auf die Uhrzeit + Kalender-Vorschau.

        Phase 17.4: Kalender-aware — wenn morgen frueh ein Termin ist,
        wird das erwaehnt. Jarvis kuemmert sich.
        """
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

        await _safe_redis(self.redis, "setex", key, 6 * 3600, "1")

        # Phase 17.4: Late-Night Pattern Tracking
        # Speichert Tage an denen der User nach Mitternacht wach war
        consecutive_nights = await self._track_late_night_pattern()

        addressing = await self._get_addressing()

        # Kalender-Vorschau: Erster Termin morgen
        tomorrow_hint = await self._get_tomorrow_first_appointment()

        # Mood-abhaengige Nachricht
        mood_data = self.mood.get_current_mood()
        mood = mood_data.get("mood", "neutral")

        # Pattern-Eskalation: Mehrere Naechte hintereinander
        pattern_hint = ""
        if consecutive_nights >= 3:
            pattern_hint = f"Das ist die {consecutive_nights}. Nacht in Folge. "
        elif consecutive_nights == 2:
            pattern_hint = "Gestern auch schon spaet. "

        if tomorrow_hint and mood == "stressed":
            msg = (
                f"{addressing}, {hour} Uhr. {pattern_hint}{tomorrow_hint} "
                f"Vielleicht solltest du Schluss machen."
            )
            urgency = "medium"
        elif consecutive_nights >= 3:
            msg = (
                f"{addressing}, es ist {hour} Uhr. {pattern_hint}"
                f"Ich mache mir langsam ernsthaft Gedanken."
            )
            urgency = "medium"
        elif tomorrow_hint:
            msg = (
                f"Es ist {hour} Uhr, {addressing}. {pattern_hint}{tomorrow_hint} "
                f"Nur als freundliche Erinnerung."
            )
            urgency = "low"
        elif hour >= 2:
            msg = random.choice([
                f"{addressing}, es ist {hour} Uhr. {pattern_hint}Darf ich den Feierabend vorschlagen?",
                f"{hour} Uhr, {addressing}. {pattern_hint}Das Bett wartet — ich hab hier alles im Griff.",
            ])
            urgency = "low"
        else:
            msg = f"Es ist {hour} Uhr, {addressing}. {pattern_hint}Nur zur Kenntnis."
            urgency = "low"

        await self._send_nudge("late_night", msg, urgency=urgency)

    async def _get_tomorrow_first_appointment(self) -> str:
        """Holt den ersten Termin von morgen aus HA-Kalender-Entities.

        Returns:
            String wie 'Morgen um 8 Uhr: Blutabnahme.' oder '' wenn nichts ansteht.
        """
        if not self.ha:
            return ""

        try:
            states = await self.ha.get_states()
            if not states:
                return ""

            for state in states:
                eid = state.get("entity_id", "")
                if not eid.startswith("calendar."):
                    continue

                attrs = state.get("attributes", {})
                message = attrs.get("message", "")
                start_time = attrs.get("start_time", "")

                if not message or not start_time:
                    continue

                # Pruefen ob der Termin morgen ist
                try:
                    # HA liefert start_time als "2026-03-04 08:00:00"
                    from datetime import timedelta
                    tomorrow = (datetime.now() + timedelta(days=1)).date()
                    event_dt = datetime.fromisoformat(start_time)
                    if event_dt.date() == tomorrow:
                        event_hour = event_dt.strftime("%H:%M")
                        if event_dt.hour < 12:
                            return f"Morgen um {event_hour} steht '{message}' an."
                        else:
                            return f"Morgen Nachmittag: {message} um {event_hour}."
                except (ValueError, TypeError):
                    continue

        except Exception as e:
            logger.debug("Kalender-Check fuer Late-Night fehlgeschlagen: %s", e)

        return ""

    async def _track_late_night_pattern(self) -> int:
        """Trackt Late-Night-Muster ueber Redis und gibt aufeinanderfolgende Naechte zurueck.

        Speichert Datumsstempel fuer jede Nacht in der der User nach
        Mitternacht noch wach war. Zaehlt aufeinanderfolgende Naechte.

        Returns:
            Anzahl aufeinanderfolgender Late-Night-Naechte (inkl. heute).
        """
        if not self.redis:
            return 1

        try:
            from datetime import timedelta

            today = datetime.now().date().isoformat()
            key = "mha:wellness:latenight_dates"

            # Heute hinzufuegen (Set — kein Duplikat)
            await _safe_redis(self.redis, "sadd", key, today)
            await _safe_redis(self.redis, "expire", key, 30 * 86400)  # 30 Tage aufbewahren

            # Aufeinanderfolgende Naechte zaehlen (rueckwaerts von heute)
            consecutive = 1
            check_date = datetime.now().date()
            for _ in range(14):  # Max 14 Tage zurueck
                check_date = check_date - timedelta(days=1)
                is_member = await self.redis.sismember(key, check_date.isoformat())
                if is_member:
                    consecutive += 1
                else:
                    break

            if consecutive > 1:
                logger.info("Late-Night Pattern: %d aufeinanderfolgende Naechte", consecutive)

            return consecutive

        except Exception as e:
            logger.debug("Late-Night Pattern Tracking Fehler: %s", e)
            return 1

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
                # Fix: Redis bytes decode
                last_str = last.decode() if isinstance(last, bytes) else last
                last_dt = datetime.fromisoformat(last_str)
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

        await _safe_redis(self.redis, "setex", key, 86400, datetime.now().isoformat())
        addressing = await self._get_addressing()

        mood_data = self.mood.get_current_mood()
        mood = mood_data.get("mood", "neutral")

        if mood == "stressed":
            msg = f"{addressing}. Wasser."
        else:
            msg = random.choice([
                f"{addressing}, ein Glas Wasser waere jetzt keine schlechte Idee.",
                f"Kurze Erinnerung, {addressing} — trinken nicht vergessen.",
                f"{addressing}, Hydration. Dein Koerper wird es dir danken.",
            ])

        await self._send_nudge("hydration", msg)

    # ------------------------------------------------------------------
    # Mood-Ambient-Actions: Jarvis handelt, nicht nur reden
    # ------------------------------------------------------------------

    async def _check_mood_ambient_actions(self):
        """Fuehrt stimmungsbasierte Ambient-Aktionen aus.

        Phase 17.4: Jarvis dimmt bei Stress das Licht, senkt bei
        Muedigkeit die Musik-Lautstaerke — ohne gefragt zu werden.
        Nutzt mood_detector.execute_suggested_actions() die bisher
        nur geloggt aber nie aufgerufen wurde.
        """
        if not self.executor or not self.redis:
            return

        mood_data = self.mood.get_current_mood()
        mood = mood_data.get("mood", "neutral")

        # Nur bei negativen Stimmungen handeln
        if mood in ("neutral", "good"):
            return

        # Cooldown: Max 1x pro 30 Minuten ambient actions ausfuehren
        key = "mha:wellness:last_ambient_action"
        last = await self.redis.get(key)
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (datetime.now() - last_dt).total_seconds() < 1800:
                    return
            except (ValueError, TypeError):
                pass

        # Mood-Aktionen ausfuehren (Szenen, Licht dimmen)
        try:
            executed = await self.mood.execute_suggested_actions(self.executor)
        except Exception as e:
            logger.warning("Mood-Ambient-Action Fehler: %s", e)
            return

        if not executed:
            return

        await _safe_redis(self.redis, "setex", key, 86400, datetime.now().isoformat())

        # Jarvis meldet was er getan hat — beilaeufig
        addressing = await self._get_addressing()
        action_names = [a.get("action", "") for a in executed]

        if "light.dimmen" in action_names and "media_player.volume_down" in action_names:
            msg = f"Licht gedimmt, Musik leiser, {addressing}. Schien mir angemessen."
        elif "light.dimmen" in action_names:
            msg = f"Ich hab das Licht etwas gedimmt, {addressing}. Schien mir angemessen."
        elif "media_player.volume_down" in action_names:
            msg = f"Musik etwas leiser, {addressing}."
        elif any(a.startswith("scene.") for a in action_names):
            msg = f"{addressing}, ich hab die Stimmung etwas angepasst."
        else:
            msg = f"Kleine Anpassung vorgenommen, {addressing}."

        await self._send_nudge("ambient_action", msg)
        logger.info("Mood-Ambient: %d Aktionen ausgefuehrt: %s", len(executed), action_names)

    # ------------------------------------------------------------------
    # Nudge senden
    # ------------------------------------------------------------------

    async def _send_nudge(self, nudge_type: str, message: str, urgency: str = "low"):
        """Sendet einen Wellness-Hinweis ueber den Callback.

        Args:
            nudge_type: Art des Nudge (pc_break, stress_detected, etc.)
            message: Die Nachricht
            urgency: Priority-Level (low, medium, high) — beeinflusst ob
                     der Nudge bei Quiet Hours / Schlaf durchkommt.
        """
        if not self._notify_callback:
            logger.debug("Wellness-Nudge ohne Callback: %s", message)
            return

        try:
            await self._notify_callback(nudge_type, message, urgency)
            logger.info("Wellness [%s/%s]: %s", nudge_type, urgency, message)
        except Exception as e:
            logger.error("Wellness-Nudge Fehler: %s", e)
