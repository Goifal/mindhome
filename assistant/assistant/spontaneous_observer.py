"""
SpontaneousObserver — Jarvis macht unaufgeforderte, interessante Bemerkungen.

Feature 4: Spontane Beobachtungen — nicht reaktiv, sondern proaktiv-interessant.
Entdeckt Trends, Rekorde, Streaks, Verhaltensaenderungen und korrelierte Insights.

Architektur:
  1. Hintergrund-Loop mit zufaelligem Intervall (1.5-3 Stunden)
  2. Prueft verschiedene Observation-Checks (Energy, Streaks, Records, Trends, etc.)
  3. Semantic Memory Integration: Beobachtungen beziehen sich auf gespeicherte Fakten
  4. Delivery via Callback → brain._handle_spontaneous → Silence Matrix → TTS
  5. Max N pro Tag mit Tageszeit-Stratifizierung, nur waehrend aktiver Stunden
  6. Behavioral Trend Detection: Erkennt Verschiebungen ueber 3-7 Tage
  7. Correlated Insights: Gruppiert verwandte Findings zu einer Beobachtung
"""

import asyncio
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from zoneinfo import ZoneInfo

from .config import yaml_config, get_person_title
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

_PREFIX = "mha:spontaneous"
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))


def _local_now() -> datetime:
    """Aktuelle Lokalzeit (Europe/Berlin oder konfiguriert)."""
    return datetime.now(_LOCAL_TZ)


class SpontaneousObserver:
    """Macht unaufgeforderte, interessante Beobachtungen."""

    # Tageszeit-Slots: (Start, End) → max Beobachtungen in diesem Slot
    _TIME_SLOTS = {
        "morning": (6, 10, 2),  # Morgens: max 2
        "daytime": (10, 18, 3),  # Tagsüber: max 3
        "evening": (18, 22, 1),  # Abends: max 1
    }

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        activity_engine=None,
        ollama_client=None,
        semantic_memory=None,
        insight_engine=None,
    ):
        self.ha = ha_client
        self.activity = activity_engine
        self._ollama = ollama_client
        self.semantic_memory = semantic_memory
        self.insight_engine = insight_engine
        self.redis: Optional[aioredis.Redis] = None
        self._notify_callback = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # History der letzten Beobachtungen (fuer Dashboard-Widget)
        from collections import deque

        self._observation_history: deque = deque(maxlen=20)

        cfg = yaml_config.get("spontaneous", {})
        self.enabled = cfg.get("enabled", True)
        self.max_per_day = cfg.get("max_per_day", 5)
        self.min_interval_hours = cfg.get("min_interval_hours", 1.5)
        self.active_hours = cfg.get("active_hours", {"start": 8, "end": 22})
        self._trend_detection = cfg.get("trend_detection", True)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis und startet den Beobachtungs-Loop."""
        self.redis = redis_client
        if self._task and not self._task.done():
            self._task.cancel()
        if self.enabled and self.redis:
            self._running = True
            self._task = asyncio.create_task(self._observe_loop())
            self._task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
        logger.info("SpontaneousObserver initialisiert (enabled: %s)", self.enabled)

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Beobachtungen."""
        self._notify_callback = callback

    async def _get_title_for_present(self) -> str:
        """Gibt die korrekte Anrede fuer die anwesenden Personen zurueck."""
        try:
            states = await self.ha.get_states()
            if states:
                persons = []
                for s in states:
                    if (
                        s.get("entity_id", "").startswith("person.")
                        and s.get("state") == "home"
                    ):
                        pname = s.get("attributes", {}).get("friendly_name", "")
                        if pname:
                            persons.append(pname)
                if len(persons) == 1:
                    return get_person_title(persons[0])
                elif len(persons) > 1:
                    titles = []
                    for p in persons:
                        t = get_person_title(p)
                        if t not in titles:
                            titles.append(t)
                    return ", ".join(titles)
        except Exception as e:
            logger.debug("Person titles retrieval failed: %s", e)
        return get_person_title()

    async def stop(self):
        """Stoppt den Beobachtungs-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _observe_loop(self):
        """Hintergrund-Loop mit zufaelligem Intervall und Tageszeit-Stratifizierung."""
        # Initiales Warten (30-60 Min nach Start)
        await asyncio.sleep(random.randint(1800, 3600))

        while self._running:
            try:
                if not self._within_active_hours():
                    await asyncio.sleep(1800)
                    continue

                if await self._daily_count() >= self.max_per_day:
                    await asyncio.sleep(3600)
                    continue

                # Tageszeit-Stratifizierung: max pro Slot pruefen
                if await self._slot_limit_reached():
                    await asyncio.sleep(1800)
                    continue

                observation = await self._find_interesting_observation()
                if observation and self._notify_callback:
                    await self._notify_callback(observation)
                    # Dashboard-History: Beobachtung fuer Widget speichern
                    self._observation_history.append(
                        {
                            "text": observation.get("message", ""),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "type": observation.get("type", "observation"),
                        }
                    )
                    await self._increment_daily_count()
                    await self._increment_slot_count()
                    logger.info(
                        "Spontane Beobachtung geliefert: %s",
                        observation.get("type", "?"),
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("SpontaneousObserver Loop Fehler: %s", e)

            # Zufaellige Wartezeit: min_interval_hours bis 2x min_interval_hours
            wait_min = self.min_interval_hours * 3600
            wait_max = self.min_interval_hours * 2 * 3600
            await asyncio.sleep(random.uniform(wait_min, wait_max))

    def _within_active_hours(self) -> bool:
        """Prueft ob aktuell innerhalb der aktiven Stunden."""
        hour = _local_now().hour
        start = self.active_hours.get("start", 8)
        end = self.active_hours.get("end", 22)
        return start <= hour < end

    async def _daily_count(self) -> int:
        """Gibt die Anzahl der heutigen Beobachtungen zurueck."""
        if not self.redis:
            return 0  # Ohne Redis: kein Tracking, aber nicht blockieren
        key = f"{_PREFIX}:daily_count:{_local_now().strftime('%Y-%m-%d')}"
        count = await self.redis.get(key)
        return int(count) if count else 0

    async def _increment_daily_count(self):
        """Erhoeht den Tages-Zaehler."""
        if not self.redis:
            return
        key = f"{_PREFIX}:daily_count:{_local_now().strftime('%Y-%m-%d')}"
        await self.redis.incr(key)
        await self.redis.expire(key, 48 * 3600)

    async def _on_cooldown(self, obs_type: str) -> bool:
        """Prueft ob ein Observation-Typ auf Cooldown ist."""
        if not self.redis:
            return False  # Ohne Redis: kein Cooldown-Tracking, aber nicht blockieren
        key = f"{_PREFIX}:cooldown:{obs_type}"
        return bool(await self.redis.get(key))

    async def _set_cooldown(self, obs_type: str, seconds: int):
        """Setzt einen Cooldown fuer einen Observation-Typ."""
        if not self.redis:
            return
        key = f"{_PREFIX}:cooldown:{obs_type}"
        await self.redis.setex(key, seconds, "1")

    def _current_slot(self) -> Optional[str]:
        """Gibt den aktuellen Tageszeit-Slot zurueck."""
        hour = _local_now().hour
        for name, (start, end, _max) in self._TIME_SLOTS.items():
            if start <= hour < end:
                return name
        return None

    async def _slot_limit_reached(self) -> bool:
        """Prueft ob das Limit fuer den aktuellen Tageszeit-Slot erreicht ist."""
        if not self.redis:
            return False
        slot = self._current_slot()
        if not slot:
            return False
        _, _, max_count = self._TIME_SLOTS[slot]
        key = f"{_PREFIX}:slot_count:{_local_now().strftime('%Y-%m-%d')}:{slot}"
        count = await self.redis.get(key)
        return int(count) >= max_count if count else False

    async def _increment_slot_count(self):
        """Erhoeht den Slot-Zaehler."""
        if not self.redis:
            return
        slot = self._current_slot()
        if not slot:
            return
        key = f"{_PREFIX}:slot_count:{_local_now().strftime('%Y-%m-%d')}:{slot}"
        await self.redis.incr(key)
        await self.redis.expire(key, 48 * 3600)

    # ------------------------------------------------------------------
    # Behavioral Trend Detection
    # ------------------------------------------------------------------

    async def _check_behavioral_trends(self) -> Optional[dict]:
        """Erkennt Verhaltens-Trends ueber 3-7 Tage aus Action-Logs.

        Beispiele:
        - 'Ihr Kaffee verschiebt sich taeglich 3 Min nach hinten'
        - 'Sie gehen seit 4 Tagen frueher schlafen'
        """
        if not self.redis or not self._trend_detection:
            return None

        try:
            # Cache pruefen (1x pro Tag analysieren)
            cache_key = f"{_PREFIX}:trend_cache:{_local_now().strftime('%Y-%m-%d')}"
            cached = await self.redis.get(cache_key)
            if cached:
                return None  # Heute schon analysiert

            # Letzte 7 Tage Action-Logs laden
            now = _local_now()
            daily_actions: dict[str, list[dict]] = {}
            for days_ago in range(7):
                day = now - timedelta(days=days_ago)
                day_key = f"mha:action_log:{day.strftime('%Y-%m-%d')}"
                raw_list = await self.redis.lrange(day_key, 0, 200)
                if raw_list:
                    entries = []
                    for raw in raw_list:
                        try:
                            entry = json.loads(
                                raw.decode(errors="replace")
                                if isinstance(raw, bytes)
                                else raw
                            )
                            entries.append(entry)
                        except (json.JSONDecodeError, AttributeError):
                            continue
                    daily_actions[day.strftime("%Y-%m-%d")] = entries

            if len(daily_actions) < 3:
                await self.redis.setex(cache_key, 48 * 3600, "no_data")
                return None

            # Suche nach Zeitverschiebungen: Gleiche Action, aber Uhrzeit verschiebt sich
            action_times: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for date_str, entries in daily_actions.items():
                for entry in entries:
                    action = entry.get("action", "")
                    hour = entry.get("hour")
                    if action and hour is not None:
                        action_times[action].append((date_str, int(hour)))

            trends = []
            for action, day_hours in action_times.items():
                if len(day_hours) < 3:
                    continue
                # Sortiere nach Datum
                sorted_dh = sorted(day_hours, key=lambda x: x[0])
                hours = [h for _, h in sorted_dh]
                # Pruefe auf monotonen Trend (steigend oder fallend)
                diffs = [hours[i + 1] - hours[i] for i in range(len(hours) - 1)]
                if not diffs:
                    continue
                avg_diff = sum(diffs) / len(diffs)
                if abs(avg_diff) >= 0.3 and all(d * avg_diff > 0 for d in diffs[-2:]):
                    direction = "spaeter" if avg_diff > 0 else "frueher"
                    trends.append(
                        {
                            "action": action,
                            "direction": direction,
                            "avg_shift_min": abs(avg_diff * 60),
                            "days": len(day_hours),
                        }
                    )

            # Cache setzen
            await self.redis.setex(cache_key, 48 * 3600, json.dumps(trends[:3]))

            if trends:
                best = trends[0]
                title = await self._get_title_for_present()
                action_name = best["action"].replace("_", " ").title()
                return {
                    "message": (
                        f"{title}, mir ist ein Trend aufgefallen: '{action_name}' verschiebt sich "
                        f"seit {best['days']} Tagen um ca. {best['avg_shift_min']:.0f} Minuten "
                        f"nach {best['direction']}."
                    ),
                    "type": "behavioral_trend",
                    "urgency": "low",
                }

        except Exception as e:
            logger.debug("Behavioral trend detection failed: %s", e)
        return None

    # ------------------------------------------------------------------
    # Correlated Insights
    # ------------------------------------------------------------------

    async def _check_correlated_insights(self) -> Optional[dict]:
        """Gruppiert verwandte Findings zu einer zusammenhaengenden Beobachtung.

        Beispiel: 'Die Heizungseffizienz im Schlafzimmer ist gesunken,
        und gleichzeitig ist die Fenster-Dichtung undicht.'
        """
        if not self.insight_engine:
            return None

        try:
            # Insight Engine nach aktuellen Findings fragen
            findings = []
            if hasattr(self.insight_engine, "get_recent_insights"):
                findings = await self.insight_engine.get_recent_insights(limit=5)
            elif hasattr(self.insight_engine, "run_checks_now"):
                findings = await self.insight_engine.run_checks_now()

            if not findings or len(findings) < 2:
                return None

            # Korrelierte Insights finden: Gleicher Raum oder gleiche Domaene
            correlated = []
            for i, f1 in enumerate(findings):
                for f2 in findings[i + 1 :]:
                    room1 = f1.get("room", "")
                    room2 = f2.get("room", "")
                    domain1 = f1.get("domain", "")
                    domain2 = f2.get("domain", "")
                    if (room1 and room1 == room2) or (domain1 and domain1 == domain2):
                        correlated.append((f1, f2))

            if not correlated:
                return None

            pair = correlated[0]
            title = await self._get_title_for_present()
            text1 = pair[0].get("text", pair[0].get("message", ""))
            text2 = pair[1].get("text", pair[1].get("message", ""))

            return {
                "message": (
                    f"{title}, zwei zusammenhaengende Beobachtungen: "
                    f"{text1} Gleichzeitig: {text2}"
                ),
                "type": "correlated_insight",
                "urgency": "low",
            }

        except Exception as e:
            logger.debug("Correlated insights check failed: %s", e)
        return None

    # ------------------------------------------------------------------
    # Semantic Memory Enhanced Observation
    # ------------------------------------------------------------------

    async def _enrich_with_semantic_memory(self, observation_text: str) -> str:
        """Reichert eine Beobachtung mit Fakten aus dem semantischen Gedaechtnis an."""
        if not self.semantic_memory:
            return observation_text

        try:
            # 1. Relevante Fakten suchen
            # search_facts ist die Standardmethode der SemanticMemory
            facts = await self.semantic_memory.search_facts(observation_text, limit=3)

            # 2. Relevante vergangene Gespraeche suchen
            conversations = []
            conv_method = getattr(
                self.semantic_memory, "get_relevant_conversations", None
            )
            if conv_method:
                try:
                    conversations = await conv_method(observation_text, limit=2)
                except Exception:
                    pass

            # 3. Beste Insider-Referenz waehlen
            insider_ref = None
            for fact in facts or []:
                content = fact.get("content", "")
                relevance = fact.get("relevance", 0)
                category = fact.get("category", "")
                if relevance >= 0.7 and category in (
                    "habit",
                    "preference",
                    "conversation_topic",
                ):
                    insider_ref = content
                    break

            if not insider_ref:
                for conv in conversations or []:
                    content = conv.get("content", "")
                    if content and len(content) > 10:
                        insider_ref = content
                        break

            if insider_ref:
                return (
                    f"{observation_text}\n[INSIDER-KONTEXT fuer Jarvis: {insider_ref}]"
                )

        except Exception as e:
            logger.debug("Semantic memory enrichment failed: %s", e)
        return observation_text

    async def _find_interesting_observation(self) -> Optional[dict]:
        """Sucht nach einer interessanten Beobachtung."""
        cfg = yaml_config.get("spontaneous", {})
        checks_cfg = cfg.get("checks", {})

        # Check-Level Dedup: Domains die InsightEngine kuerzlich geprueft hat
        # ueberspringen, um Duplikate zu vermeiden.
        _ie_domains: set[str] = set()
        if self.insight_engine and hasattr(
            self.insight_engine, "get_recently_checked_domains"
        ):
            try:
                _ie_domains = await self.insight_engine.get_recently_checked_domains()
            except Exception:
                pass

        checks = []
        if checks_cfg.get("energy_comparison", True) and "energy" not in _ie_domains:
            checks.append(self._check_energy_comparison)
        if checks_cfg.get("streak", True) and "weather" not in _ie_domains:
            checks.append(self._check_weather_streak)
        if checks_cfg.get("usage_record", True):
            checks.append(self._check_usage_record)
        if checks_cfg.get("device_milestone", True):
            checks.append(self._check_device_milestone)
        if checks_cfg.get("house_efficiency", True):
            checks.append(self._check_house_efficiency)

        # Behavioral Trends & Correlated Insights
        if self._trend_detection:
            checks.append(self._check_behavioral_trends)
        if self.insight_engine:
            checks.append(self._check_correlated_insights)

        # Deklarative Tools als zusaetzliche Checks
        decl_cfg = yaml_config.get("declarative_tools", {})
        if decl_cfg.get("enabled", True) and decl_cfg.get("use_in_spontaneous", True):
            checks.append(self._check_declarative_tools)

        random.shuffle(checks)

        for check in checks:
            try:
                result = await check()
                if result and not await self._on_cooldown(result["type"]):
                    await self._set_cooldown(result["type"], 24 * 3600)
                    return result
            except Exception as e:
                logger.debug("Spontaneous Check Fehler: %s", e)
                continue

        # LLM-Observation als Fallback wenn keine hardcoded Checks etwas fanden
        if self._ollama and not await self._on_cooldown("llm_observation"):
            try:
                result = await self._check_llm_observation()
                if result:
                    await self._set_cooldown("llm_observation", 24 * 3600)
                    return result
            except Exception as e:
                logger.debug("LLM Observation Fehler: %s", e)

        return None

    # ------------------------------------------------------------------
    # LLM-basierte Beobachtung
    # ------------------------------------------------------------------

    def _build_sensor_snapshot(self, states: list[dict]) -> str:
        """Baut kompakten Sensor-Snapshot fuer LLM-Prompt."""
        lines = []
        _RELEVANT = {
            "temperature",
            "humidity",
            "energy",
            "power",
            "illuminance",
            "co2",
            "battery",
        }
        for s in states:
            eid = s.get("entity_id", "")
            state_val = s.get("state", "")
            if state_val in ("unavailable", "unknown", ""):
                continue
            attrs = s.get("attributes", {})
            device_class = attrs.get("device_class", "")
            unit = attrs.get("unit_of_measurement", "")
            if device_class in _RELEVANT or any(
                k in eid for k in ("temp", "humid", "energy", "power", "weather")
            ):
                name = attrs.get("friendly_name", eid)
                lines.append(f"{name}: {state_val}{unit}")
                if len(lines) >= 30:
                    break
        return "\n".join(lines)

    async def _check_llm_observation(self) -> Optional[dict]:
        """LLM analysiert Sensor-Daten und findet nicht-offensichtliche Beobachtungen."""
        if not self._ollama:
            return None

        try:
            states = await self.ha.get_states()
            if not states:
                return None

            snapshot = self._build_sensor_snapshot(states)
            if not snapshot:
                return None

            # Kontext anreichern: Zeit + Wochentag + Aktivitaet
            now = _local_now()
            _DAY_NAMES = {
                0: "Montag",
                1: "Dienstag",
                2: "Mittwoch",
                3: "Donnerstag",
                4: "Freitag",
                5: "Samstag",
                6: "Sonntag",
            }
            _hour = now.hour
            if 5 <= _hour < 10:
                _tod = "Morgen"
            elif 10 <= _hour < 17:
                _tod = "Nachmittag"
            elif 17 <= _hour < 22:
                _tod = "Abend"
            else:
                _tod = "Nacht"
            day_name = _DAY_NAMES.get(now.weekday(), "")

            activity_hint = ""
            if self.activity:
                try:
                    act_result = await self.activity.detect_activity()
                    act = act_result.get("activity", "")
                    if act and act != "unknown":
                        _ACT_DE = {
                            "relaxing": "entspannt",
                            "focused": "arbeitet",
                            "sleeping": "schlaeft",
                            "away": "abwesend",
                            "cooking": "kocht",
                            "watching": "schaut fern",
                            "guests": "hat Besuch",
                        }
                        activity_hint = f"\nAktivitaet: {_ACT_DE.get(act, act)}"
                except Exception as e:
                    logger.debug("Aktivitaetserkennung fehlgeschlagen: %s", e)

            prompt = (
                "Du bist ein Smart-Home-Assistent. Hier sind aktuelle Hausdaten:\n\n"
                f"Zeitpunkt: {_tod}, {day_name} {now.strftime('%H:%M')}"
                f"{activity_hint}\n\n"
                f"{snapshot}\n\n"
                "Nenne EINE interessante, nicht offensichtliche Beobachtung in 1-2 Saetzen auf Deutsch. "
                "Beruecksichtige den zeitlichen Kontext (was ist fuer diese Uhrzeit/Wochentag ungewoehnlich?). "
                "Sei spezifisch und nuetzlich. "
                "Wenn ein INSIDER-KONTEXT gegeben ist, baue ihn beilaeufig ein "
                "(z.B. 'wie letztes Mal', 'das kennen wir ja schon', 'wieder das alte Spiel'). "
                "Antworte NUR mit der Beobachtung, ohne Einleitung."
            )
            response = await self._ollama.generate(prompt, max_tokens=300)
            if response and len(response.strip()) > 20:
                enriched_text = await self._enrich_with_semantic_memory(
                    response.strip()
                )
                return {
                    "type": "llm_observation",
                    "message": enriched_text,
                    "category": "insight",
                }
        except Exception as e:
            logger.debug("LLM Observation fehlgeschlagen: %s", e)
        return None

    # ------------------------------------------------------------------
    # Observation Checks
    # ------------------------------------------------------------------

    async def _check_energy_comparison(self) -> Optional[dict]:
        """Vergleicht Energie-Verbrauch mit Vorwoche."""
        if not self.redis:
            return None

        try:
            # Heutige und letzte Wochen-Daten per mget aus Redis
            from datetime import timedelta

            now_ts = _local_now()
            today_key = f"mha:energy:daily:{now_ts.strftime('%Y-%m-%d')}"
            week_ago = now_ts - timedelta(days=7)
            week_key = f"mha:energy:daily:{week_ago.strftime('%Y-%m-%d')}"
            today_val, week_val = await self.redis.mget([today_key, week_key])
            if not today_val:
                return None

            if not week_val:
                return None

            try:
                today_data = json.loads(today_val)
            except (json.JSONDecodeError, ValueError):
                today_data = {"consumption_wh": float(today_val)}
            today_kwh = float(today_data.get("consumption_wh", 0))
            try:
                week_data = json.loads(week_val)
            except (json.JSONDecodeError, ValueError):
                week_data = {"consumption_wh": float(week_val)}
            week_kwh = float(week_data.get("consumption_wh", 0))

            if week_kwh <= 0:
                return None

            diff_pct = ((today_kwh - week_kwh) / week_kwh) * 100

            if abs(diff_pct) >= 15:
                title = await self._get_title_for_present()

                # Device-Dependency-Kontext: Erklaerung fuer Abweichung
                _dep_context = ""
                try:
                    from .state_change_log import StateChangeLog
                    import assistant.main as main_module

                    if hasattr(main_module, "brain"):
                        _states = await main_module.brain.ha.get_states() or []
                        _state_dict = {
                            s["entity_id"]: s.get("state", "")
                            for s in _states
                            if "entity_id" in s
                        }
                        _scl = StateChangeLog.__new__(StateChangeLog)
                        _conflicts = _scl.detect_conflicts(_state_dict)
                        _energy = [
                            c
                            for c in _conflicts
                            if c.get("affected_active")
                            and any(
                                kw in c.get("effect", "").lower()
                                for kw in ["heiz", "kuehl", "energie", "ineffizient"]
                            )
                        ]
                        if _energy and diff_pct > 0:
                            _dep_context = (
                                f" Moeglicherweise weil: {_energy[0].get('hint', '')}."
                            )
                except Exception as e:
                    logger.debug("Energie-Abhaengigkeitskontext fehlgeschlagen: %s", e)

                if diff_pct > 0:
                    message = (
                        f"{title}, der Energieverbrauch liegt heute {diff_pct:.0f}% "
                        f"ueber dem gleichen Tag letzte Woche.{_dep_context}"
                    )
                else:
                    message = (
                        f"{title}, heute verbrauchen wir {abs(diff_pct):.0f}% weniger "
                        f"Energie als letzte Woche um diese Zeit. Gut so."
                    )
                return {
                    "message": message,
                    "type": "energy_comparison",
                    "urgency": "low",
                }
        except (ValueError, TypeError) as e:
            logger.debug("Energy comparison parse error: %s", e)
        return None

    async def _check_weather_streak(self) -> Optional[dict]:
        """Prueft auf Wetter-Streaks (z.B. X Tage Sonne in Folge)."""
        try:
            states = await self.ha.get_states()
            if not states:
                return None

            for state in states:
                if state.get("entity_id", "").startswith("weather."):
                    condition = state.get("state", "")
                    temp = state.get("attributes", {}).get("temperature")

                    if condition == "sunny" and temp:
                        try:
                            temp_f = float(temp)
                            if temp_f >= 25:
                                title = await self._get_title_for_present()
                                return {
                                    "message": (
                                        f"{title}, es hat draussen {temp_f:.0f} Grad "
                                        f"bei strahlendem Sonnenschein. "
                                        f"Vielleicht ein guter Moment fuer frische Luft."
                                    ),
                                    "type": "weather_streak",
                                    "urgency": "low",
                                }
                        except (ValueError, TypeError) as e:
                            logger.debug("Weather temp parse error: %s", e)

                    if condition in ("snowy", "snowy-rainy"):
                        title = await self._get_title_for_present()
                        return {
                            "message": (
                                f"{title}, es schneit draussen. "
                                f"Falls die Rolllaeden noch oben sind, waere das "
                                f"zumindest ein schoener Anblick."
                            ),
                            "type": "weather_streak",
                            "urgency": "low",
                        }
                    break
        except Exception as e:
            logger.debug("Weather streak detection failed: %s", e)
        return None

    async def _check_usage_record(self) -> Optional[dict]:
        """Prueft ob ein Nutzungs-Rekord erreicht wurde."""
        if not self.redis:
            return None

        try:
            # Anzahl manueller Aktionen heute
            from .learning_observer import KEY_MANUAL_ACTIONS

            actions_raw = await self.redis.lrange(KEY_MANUAL_ACTIONS, 0, 499)
            if not actions_raw:
                return None

            today = _local_now().strftime("%Y-%m-%d")
            today_count = 0
            for raw in actions_raw:
                try:
                    entry = json.loads(
                        raw.decode(errors="replace") if isinstance(raw, bytes) else raw
                    )
                    if entry.get("timestamp", "").startswith(today):
                        today_count += 1
                except (json.JSONDecodeError, AttributeError):
                    continue

            # Record pruefen
            record_key = f"{_PREFIX}:record:daily_actions"
            prev_record = await self.redis.get(record_key)
            prev_record = int(prev_record) if prev_record else 0

            if today_count > prev_record and today_count >= 10:
                await self.redis.setex(record_key, 90 * 86400, str(today_count))
                title = await self._get_title_for_present()
                return {
                    "message": (
                        f"{title}, heute wurden bereits {today_count} Geraete "
                        f"manuell geschaltet — neuer Rekord. Offenbar ein aktiver Tag."
                    ),
                    "type": "usage_record",
                    "urgency": "low",
                }
        except Exception as e:
            logger.debug("Device usage record detection failed: %s", e)
        return None

    async def _check_device_milestone(self) -> Optional[dict]:
        """Prueft auf Geraete-Meilensteine (z.B. Waschmaschine X-mal diese Woche)."""
        if not self.redis:
            return None

        try:
            from .learning_observer import KEY_MANUAL_ACTIONS

            actions_raw = await self.redis.lrange(KEY_MANUAL_ACTIONS, 0, 499)
            if not actions_raw:
                return None

            # Zaehle Aktionen pro Entity diese Woche
            from datetime import timedelta

            week_start = _local_now() - timedelta(days=7)
            week_start_str = week_start.isoformat()

            entity_counts: dict[str, int] = {}
            for raw in actions_raw:
                try:
                    entry = json.loads(
                        raw.decode(errors="replace") if isinstance(raw, bytes) else raw
                    )
                    ts = entry.get("timestamp", "")
                    if ts >= week_start_str:
                        eid = entry.get("entity_id", "")
                        if eid:
                            entity_counts[eid] = entity_counts.get(eid, 0) + 1
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not entity_counts:
                return None

            # Hoechste Nutzung finden
            top_entity = max(entity_counts, key=entity_counts.get)
            top_count = entity_counts[top_entity]

            if top_count >= 7:
                friendly = top_entity.split(".", 1)[-1].replace("_", " ").title()
                title = await self._get_title_for_present()
                return {
                    "message": (
                        f"{title}, {friendly} wurde diese Woche bereits "
                        f"{top_count} Mal betaetigt. Das meistgenutzte Geraet."
                    ),
                    "type": "device_milestone",
                    "urgency": "low",
                }
        except Exception as e:
            logger.debug("Device milestone detection failed: %s", e)
        return None

    async def _check_house_efficiency(self) -> Optional[dict]:
        """Analysiert die Haus-Effizienz und macht eine smarte Beobachtung.

        MCU-JARVIS-Feature: 'Sir, mir ist aufgefallen, dass das Haus heute
        besonders effizient laeuft — 18% weniger Heiz-Zyklen als ueblich.'
        """
        try:
            states = await self.ha.get_states()
            if not states:
                return None

            # Zaehle aktive Geraete vs. anwesende Personen
            lights_on = 0
            heating_active = 0
            persons_home = 0

            for s in states:
                eid = s.get("entity_id", "")
                state = s.get("state", "")

                if eid.startswith("light.") and state == "on":
                    lights_on += 1
                elif eid.startswith("climate."):
                    hvac = s.get("attributes", {}).get("hvac_action", "")
                    if hvac in ("heating", "cooling"):
                        heating_active += 1
                elif eid.startswith("person.") and state == "home":
                    persons_home += 1

            title = await self._get_title_for_present()

            # Niemand da aber alles laeuft
            if persons_home == 0 and (lights_on > 2 or heating_active > 2):
                return {
                    "message": (
                        f"{title}, das Haus verbraucht gerade Ressourcen "
                        f"({lights_on} Lichter, {heating_active} Heizungen) "
                        f"fuer eine leere Wohnung. Nur so als Beobachtung."
                    ),
                    "type": "house_efficiency",
                    "urgency": "low",
                }

            # Alles optimiert (positives Feedback)
            if persons_home > 0 and lights_on <= 1 and heating_active <= 1:
                hour = _local_now().hour
                if 10 <= hour <= 20:
                    return {
                        "message": (
                            f"{title}, das Haus laeuft heute bemerkenswert effizient. "
                            f"Nur {lights_on} Licht und {heating_active} Heizung{'en' if heating_active != 1 else ''} aktiv. "
                            f"Vorbildlich."
                        ),
                        "type": "house_efficiency",
                        "urgency": "low",
                    }

        except Exception as e:
            logger.debug("House efficiency insight failed: %s", e)
        return None

    async def _check_declarative_tools(self) -> Optional[dict]:
        """Fuehrt deklarierte Analyse-Tools aus und meldet interessante Ergebnisse.

        Durchlaeuft alle vom User definierten Tools und prueft ob ein Ergebnis
        erwaehnenswert ist (Schwellwerte ueberschritten, Trends erkannt etc.).
        """
        try:
            from .declarative_tools import DeclarativeToolExecutor, get_registry

            registry = get_registry()
            tools = registry.list_tools()
            if not tools:
                return None

            executor = DeclarativeToolExecutor(self.ha)
            random.shuffle(tools)

            for tool in tools[:5]:  # Max 5 Tools pro Durchlauf
                tool_name = tool.get("name", "")
                tool_type = tool.get("type", "")
                cooldown_key = f"decl_tool_{tool_name}"

                if await self._on_cooldown(cooldown_key):
                    continue

                result = await executor.execute(tool_name)
                if not result.get("success"):
                    continue

                # Pruefen ob Ergebnis erwaehnenswert ist
                interesting = self._is_tool_result_interesting(tool_type, result)
                if not interesting:
                    continue

                title = await self._get_title_for_present()
                tool_msg = result.get("message", "")
                # Erste Zeile (Beschreibung) entfernen — Jarvis formuliert selbst
                lines = tool_msg.split("\n")
                data_lines = (
                    "\n".join(lines[1:]).strip() if len(lines) > 1 else tool_msg
                )

                message = (
                    f"{title}, mir ist bei einer Routine-Analyse aufgefallen: "
                    f"{data_lines}"
                )

                await self._set_cooldown(cooldown_key, 24 * 3600)
                return {
                    "message": message,
                    "type": f"decl_tool_{tool_name}",
                    "urgency": "low",
                }

        except Exception as e:
            logger.debug("Declarative Tools Check Fehler: %s", e)
        return None

    @staticmethod
    def _is_tool_result_interesting(tool_type: str, result: dict) -> bool:
        """Entscheidet ob ein Tool-Ergebnis erwaehnenswert ist."""
        if tool_type == "threshold_monitor":
            return not result.get("in_range", True)

        if tool_type == "trend_analyzer":
            trend = result.get("trend", "stabil")
            diff = abs(result.get("trend_diff", 0))
            return trend != "stabil" and diff > 1.0

        if tool_type == "entity_comparison":
            val = result.get("result", 0)
            return abs(val) > 0 and abs(val) > 0.5

        if tool_type == "entity_aggregator":
            values = result.get("values", {})
            if len(values) >= 2:
                vals = list(values.values())
                spread = max(vals) - min(vals)
                return spread > 3.0  # Signifikante Abweichung
            return False

        if tool_type == "event_counter":
            return result.get("count", 0) >= 5

        if tool_type == "state_duration":
            # Interessant wenn > 30% oder < 5% der Gesamtzeit
            pct = result.get("percentage", 0)
            return pct > 30 or (pct < 5 and result.get("duration_hours", 0) > 0)

        if tool_type == "time_comparison":
            # Interessant wenn > 15% Aenderung
            pct_change = abs(result.get("pct_change", 0))
            return pct_change > 15

        # multi_entity_formula, schedule_checker: immer erwaehnenswert
        return True
