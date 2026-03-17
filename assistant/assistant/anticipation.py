"""
Anticipation Engine - Pattern Detection auf Action-History.

Phase 8: Erkennt wiederkehrende Muster in User-Aktionen und
schlaegt diese proaktiv vor.

Muster-Typen:
- Zeit-Muster: "Jeden Freitag 18 Uhr -> TV an"
- Sequenz-Muster: "A -> B -> C" (immer gleiche Reihenfolge)
- Kontext-Muster: "Regen + Abend -> Rolladen runter"

Confidence-basierte Vorschlaege:
- 60-80%: Fragen "Soll ich?"
- 80-95%: Vorschlagen "Ich bereite vor?"
- 95%+ bei Level >= 4: Automatisch + informieren
"""

import asyncio
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config

logger = logging.getLogger(__name__)


class AnticipationEngine:
    """Erkennt Muster in User-Aktionen und schlaegt Aktionen vor."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None

        # Konfiguration
        cfg = yaml_config.get("anticipation", {})
        self.enabled = cfg.get("enabled", True)
        self.history_days = cfg.get("history_days") or 30
        self.min_confidence = cfg.get("min_confidence") or 0.6
        self.check_interval = (cfg.get("check_interval_minutes") or 15) * 60

        thresholds = cfg.get("thresholds", {})
        self.threshold_ask = thresholds.get("ask", 0.6)
        self.threshold_suggest = thresholds.get("suggest", 0.8)
        self.threshold_auto = thresholds.get("auto", 0.90)

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert die Engine."""
        self.redis = redis_client
        if self.enabled and self.redis:
            self._running = True
            self._task = asyncio.create_task(self._check_loop())
            logger.info("AnticipationEngine initialisiert (History: %d Tage)", self.history_days)

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Vorschlaege."""
        self._notify_callback = callback

    async def stop(self):
        """Stoppt die Engine."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Action-Logging
    # ------------------------------------------------------------------

    async def log_action(self, action: str, args: dict, person: str = "",
                         weather_condition: str = ""):
        """Loggt eine ausgefuehrte Aktion fuer Pattern-Detection.

        weather_condition wird automatisch mitgeloggt (z.B. 'rainy', 'sunny')
        fuer wetterbasierte Muster-Erkennung.
        """
        if not self.redis:
            return

        try:
            now = datetime.now()
            entry = {
                "action": action,
                "args": json.dumps(args),
                "person": person,
                "hour": now.hour,
                "weekday": now.weekday(),
                "timestamp": now.isoformat(),
                "weather": weather_condition,
            }
            entry_json = json.dumps(entry)

            # In Action-Log speichern (Rolling Window) — Pipeline: 5 Calls → 1
            day_key = f"mha:action_log:{now.strftime('%Y-%m-%d')}"
            pipe = self.redis.pipeline()
            pipe.lpush("mha:action_log", entry_json)
            pipe.ltrim("mha:action_log", 0, 999)
            pipe.expire("mha:action_log", 30 * 86400)
            pipe.lpush(day_key, entry_json)
            pipe.expire(day_key, self.history_days * 86400)
            await pipe.execute()

        except Exception as e:
            logger.error("Fehler beim Action-Logging: %s", e)

    # ------------------------------------------------------------------
    # Pattern Detection
    # ------------------------------------------------------------------

    async def detect_patterns(self, person: str = "") -> list[dict]:
        """Erkennt Muster in der Action-History.

        Args:
            person: Wenn gesetzt, nur Muster dieser Person erkennen.
                    Leerer String = alle Aktionen (Haushalt-global).
        """
        if not self.redis:
            return []

        try:
            # Alle Aktionen laden
            raw_entries = await self.redis.lrange("mha:action_log", 0, 999)
            if len(raw_entries) < 10:
                return []  # Zu wenig Daten

            entries = [json.loads(e.decode() if isinstance(e, bytes) else e) for e in raw_entries]

            patterns = []

            # 1. Zeit-Muster erkennen
            time_patterns = self._detect_time_patterns(entries, person=person)
            patterns.extend(time_patterns)

            # 2. Sequenz-Muster erkennen
            seq_patterns = self._detect_sequence_patterns(entries, person=person)
            patterns.extend(seq_patterns)

            # 3. Kontext-Muster erkennen (Wetter, Tageszeit, Anwesenheit)
            ctx_patterns = self._detect_context_patterns(entries, person=person)
            patterns.extend(ctx_patterns)

            # 4. Phase 18: Kausale Ketten erkennen (3+ Aktionen als Zusammenhang)
            causal_patterns = self._detect_causal_chains(entries, person=person)
            patterns.extend(causal_patterns)

            return patterns

        except Exception as e:
            logger.error("Fehler bei Pattern-Detection: %s", e)
            return []

    def _detect_time_patterns(self, entries: list[dict],
                              person: str = "") -> list[dict]:
        """Erkennt zeitbasierte Muster (gleiche Aktion zur gleichen Zeit).

        Neuere Aktionen werden staerker gewichtet als aeltere (Recency-Weighting).
        Eine Aktion von heute zaehlt 2x soviel wie eine von vor 30 Tagen.

        Args:
            entries: Action-Log Eintraege
            person: Wenn gesetzt, nur Muster dieser Person erkennen
        """
        patterns = []

        # Person-Filter: Nur Eintraege dieser Person (oder alle bei leerem person)
        if person:
            entries = [e for e in entries if (e.get("person", "") or "") == person]
            if len(entries) < 3:
                return []

        # Gruppiere nach Aktion + Wochentag + Stunde
        time_groups = defaultdict(list)
        for entry in entries:
            action = entry.get("action", "")
            weekday = entry.get("weekday", -1)
            hour = entry.get("hour", -1)
            key = f"{action}|{weekday}|{hour}"
            time_groups[key].append(entry)

        # Muster: Wenn eine Aktion an einem bestimmten Wochentag/Stunde
        # in > 60% der Wochen vorkommt
        now = datetime.now()
        weeks_in_data = max(1, len(entries) / 50)  # Grobe Schaetzung

        for key, group in time_groups.items():
            if len(group) < 3:
                continue

            action, weekday, hour = key.split("|")

            # Recency-Weighting: Neuere Eintraege zaehlen staerker
            weighted_count = 0.0
            for entry in group:
                try:
                    ts = datetime.fromisoformat(entry.get("timestamp", ""))
                    days_ago = (now - ts).days
                    # Gewicht: 1.0 fuer heute, 0.5 fuer vor 30 Tagen
                    weight = max(0.3, 1.0 - (days_ago / self.history_days) * 0.7)
                    weighted_count += weight
                except (ValueError, TypeError):
                    weighted_count += 0.5  # Fallback-Gewicht

            occurrences = len(group)
            confidence = min(1.0, weighted_count / max(1, weeks_in_data))

            if confidence >= self.min_confidence:
                # Typische Args ermitteln
                args_counter = Counter(e.get("args", "{}") for e in group)
                if args_counter:
                    typical_args = args_counter.most_common(1)[0][0]
                else:
                    typical_args = "{}"

                weekday_names = [
                    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
                    "Freitag", "Samstag", "Sonntag",
                ]
                wd_idx = int(weekday) if weekday.isdigit() else -1
                wd_name = weekday_names[wd_idx] if 0 <= wd_idx < len(weekday_names) else weekday

                pattern_entry = {
                    "type": "time",
                    "action": action,
                    "args": json.loads(typical_args),
                    "weekday": int(weekday),
                    "hour": int(hour),
                    "confidence": round(confidence, 2),
                    "occurrences": occurrences,
                    "description": f"Jeden {wd_name} um {hour}:00 → {action}",
                }
                if person:
                    pattern_entry["person"] = person
                patterns.append(pattern_entry)

        return patterns

    def _detect_sequence_patterns(self, entries: list[dict],
                                  person: str = "") -> list[dict]:
        """Erkennt Sequenz-Muster (A -> B innerhalb von 5 Minuten).

        Args:
            entries: Action-Log Eintraege
            person: Wenn gesetzt, nur Sequenzen dieser Person erkennen
        """
        patterns = []

        # Person-Filter
        if person:
            entries = [e for e in entries if (e.get("person", "") or "") == person]

        # Sortiere nach Timestamp (neueste zuerst in der Liste)
        sorted_entries = sorted(entries, key=lambda e: e.get("timestamp", ""))

        # Zaehle Paare (A -> B) die innerhalb von 5 Min aufeinander folgen
        pair_counts = Counter()
        pair_args = defaultdict(list)

        for i in range(len(sorted_entries) - 1):
            curr = sorted_entries[i]
            next_e = sorted_entries[i + 1]

            try:
                t1 = datetime.fromisoformat(curr.get("timestamp", ""))
                t2 = datetime.fromisoformat(next_e.get("timestamp", ""))
                diff = (t2 - t1).total_seconds()

                if 0 < diff < 300:  # Innerhalb von 5 Min
                    a = curr.get("action", "")
                    b = next_e.get("action", "")
                    if a and b and a != b:
                        pair = f"{a}|{b}"
                        pair_counts[pair] += 1
                        pair_args[pair].append(next_e.get("args", "{}"))
            except (ValueError, TypeError):
                continue

        # Muster: Wenn Paar > 5x vorkommt
        total_actions = len(sorted_entries)
        for pair, count in pair_counts.items():
            if count < 5:
                continue

            a, b = pair.split("|")
            confidence = min(1.0, count / max(1, total_actions / 10))

            if confidence >= self.min_confidence:
                args_counter = Counter(pair_args[pair])
                typical_args = args_counter.most_common(1)[0][0] if args_counter else "{}"

                pattern_entry = {
                    "type": "sequence",
                    "trigger_action": a,
                    "follow_action": b,
                    "follow_args": json.loads(typical_args),
                    "confidence": round(confidence, 2),
                    "occurrences": count,
                    "description": f"Nach {a} folgt meist {b}",
                }
                if person:
                    pattern_entry["person"] = person
                patterns.append(pattern_entry)

        return patterns

    def _detect_context_patterns(self, entries: list[dict],
                                 person: str = "") -> list[dict]:
        """Erkennt kontextbasierte Muster (Wetter, Tageszeit-Kombination).

        Sucht nach Aktionen die immer unter bestimmten Kontextbedingungen
        stattfinden, z.B. "Rolladen runter wenn Abend + Sommer".

        Args:
            entries: Action-Log Eintraege
            person: Wenn gesetzt, nur Muster dieser Person erkennen
        """
        patterns = []

        # Person-Filter
        if person:
            entries = [e for e in entries if (e.get("person", "") or "") == person]

        # Gruppiere Aktionen nach Tageszeit-Cluster (morgen/mittag/abend/nacht)
        time_clusters = {"morning": [], "afternoon": [], "evening": [], "night": []}
        for entry in entries:
            hour = entry.get("hour", 12)
            action = entry.get("action", "")
            if not action:
                continue
            if 5 <= hour < 12:
                time_clusters["morning"].append(entry)
            elif 12 <= hour < 17:
                time_clusters["afternoon"].append(entry)
            elif 17 <= hour < 22:
                time_clusters["evening"].append(entry)
            else:
                time_clusters["night"].append(entry)

        cluster_labels = {
            "morning": "morgens",
            "afternoon": "nachmittags",
            "evening": "abends",
            "night": "nachts",
        }

        # Finde Aktionen die in einem Cluster dominant sind (>70% aller Vorkommen)
        action_total = Counter(e.get("action", "") for e in entries if e.get("action"))
        for cluster_name, cluster_entries in time_clusters.items():
            if len(cluster_entries) < 5:
                continue

            cluster_actions = Counter(e.get("action", "") for e in cluster_entries)
            for action, cluster_count in cluster_actions.items():
                total = action_total.get(action, 0)
                if total < 5:
                    continue
                ratio = cluster_count / total
                if ratio >= 0.7:
                    # Typische Args
                    args_counter = Counter(
                        e.get("args", "{}") for e in cluster_entries if e.get("action") == action
                    )
                    typical_args = args_counter.most_common(1)[0][0] if args_counter else "{}"

                    ctx_entry = {
                        "type": "context",
                        "context": f"time_cluster:{cluster_name}",
                        "action": action,
                        "args": json.loads(typical_args),
                        "confidence": round(min(1.0, ratio * (cluster_count / 10)), 2),
                        "occurrences": cluster_count,
                        "description": f"{action} wird zu {ratio*100:.0f}% {cluster_labels[cluster_name]} ausgefuehrt",
                    }
                    if person:
                        ctx_entry["person"] = person
                    patterns.append(ctx_entry)

        # Wetter-basierte Muster: Aktionen die bei bestimmtem Wetter gehaeuft auftreten
        weather_groups = defaultdict(list)
        for entry in entries:
            weather = entry.get("weather", "")
            if weather:
                weather_groups[weather].append(entry)

        weather_labels = {
            "sunny": "bei Sonne",
            "partlycloudy": "bei teilw. bewoelkt",
            "cloudy": "bei Bewoelkung",
            "rainy": "bei Regen",
            "pouring": "bei starkem Regen",
            "lightning-rainy": "bei Gewitter",
            "fog": "bei Nebel",
            "snowy": "bei Schnee",
        }
        for weather_cond, w_entries in weather_groups.items():
            if len(w_entries) < 5:
                continue
            w_actions = Counter(e.get("action", "") for e in w_entries)
            for action, w_count in w_actions.items():
                total = action_total.get(action, 0)
                if total < 5:
                    continue
                ratio = w_count / total
                if ratio >= 0.6:  # 60%+ bei diesem Wetter
                    w_args_counter = Counter(
                        e.get("args", "{}") for e in w_entries if e.get("action") == action
                    )
                    typical_args = w_args_counter.most_common(1)[0][0] if w_args_counter else "{}"
                    label = weather_labels.get(weather_cond, weather_cond)
                    w_entry = {
                        "type": "context",
                        "context": f"weather:{weather_cond}",
                        "action": action,
                        "args": json.loads(typical_args),
                        "confidence": round(min(1.0, ratio * (w_count / 10)), 2),
                        "occurrences": w_count,
                        "description": f"{action} wird zu {ratio*100:.0f}% {label} ausgefuehrt",
                    }
                    if person:
                        w_entry["person"] = person
                    patterns.append(w_entry)

        return patterns

    # ------------------------------------------------------------------
    # Phase 18: Kausale Ketten-Erkennung
    # ------------------------------------------------------------------

    def _detect_causal_chains(self, entries: list[dict],
                              person: str = "") -> list[dict]:
        """Erkennt kausale Ketten: Kontext-Trigger → Multi-Step-Folge.

        Erweitert die Sequenz-Erkennung: Statt nur A→B werden Ketten aus
        3+ Aktionen erkannt die immer im gleichen Kontext auftreten.

        Zeitfenster: 10 Min (statt 5 bei Sequenzen) fuer laengere Ketten.
        Min. 3 Wiederholungen der gleichen Kette.

        Args:
            entries: Action-Log Eintraege
            person: Wenn gesetzt, nur Ketten dieser Person erkennen
        """
        causal_cfg = yaml_config.get("anticipation", {})
        window_min = causal_cfg.get("causal_chain_window_min") or 10
        min_occurrences = causal_cfg.get("causal_chain_min_occurrences") or 3
        window_sec = window_min * 60

        # Person-Filter
        if person:
            entries = [e for e in entries if (e.get("person", "") or "") == person]

        patterns = []
        sorted_entries = sorted(entries, key=lambda e: e.get("timestamp", ""))

        # Finde Cluster von 3+ Aktionen innerhalb des Zeitfensters
        chain_counter: Counter = Counter()
        chain_contexts: dict[str, list[str]] = defaultdict(list)

        i = 0
        while i < len(sorted_entries):
            cluster = [sorted_entries[i]]
            try:
                t_start = datetime.fromisoformat(sorted_entries[i].get("timestamp", ""))
            except (ValueError, TypeError):
                i += 1
                continue

            # Sammle alle Aktionen innerhalb des Zeitfensters
            j = i + 1
            while j < len(sorted_entries):
                try:
                    t_j = datetime.fromisoformat(sorted_entries[j].get("timestamp", ""))
                    if (t_j - t_start).total_seconds() <= window_sec:
                        cluster.append(sorted_entries[j])
                        j += 1
                    else:
                        break
                except (ValueError, TypeError):
                    j += 1
                    continue

            # Nur Cluster mit 3+ verschiedenen Aktionen
            if len(cluster) >= 3:
                actions = tuple(e.get("action", "") for e in cluster if e.get("action"))
                unique_actions = tuple(dict.fromkeys(actions))  # Reihenfolge erhalten, Duplikate weg
                if len(unique_actions) >= 3:
                    chain_key = "|".join(unique_actions)
                    chain_counter[chain_key] += 1
                    # Kontext der ersten Aktion als Trigger
                    ctx = cluster[0].get("weather", "") or f"hour:{cluster[0].get('hour', 0)}"
                    chain_contexts[chain_key].append(ctx)

            i = j if j > i + 1 else i + 1

        # Patterns mit min_occurrences erzeugen
        for chain_key, count in chain_counter.items():
            if count < min_occurrences:
                continue

            actions = chain_key.split("|")
            # Dominanter Kontext bestimmen
            ctx_counter = Counter(chain_contexts.get(chain_key, []))
            dominant_ctx = ctx_counter.most_common(1)[0][0] if ctx_counter else "unbekannt"

            confidence = min(1.0, count / max(1, len(sorted_entries) / 20))
            if confidence < self.min_confidence:
                continue

            desc_actions = " → ".join(actions)
            chain_entry = {
                "type": "causal_chain",
                "trigger": dominant_ctx,
                "actions": actions,
                "confidence": round(confidence, 2),
                "occurrences": count,
                "description": f"Kette ({dominant_ctx}): {desc_actions}",
            }
            if person:
                chain_entry["person"] = person
            patterns.append(chain_entry)

        return patterns

    # ------------------------------------------------------------------
    # Phase 18: Implizite Voraussetzungen
    # ------------------------------------------------------------------

    def detect_implicit_prerequisites(self, intent: str) -> list[str]:
        """Erkennt implizite Aktions-Folgen fuer abstrakte Intents.

        Wenn der User "entspannen" sagt, liefert dies die typischen
        Vorbereitungs-Aktionen aus der Konfiguration.

        Args:
            intent: Abstraktes Intent (z.B. "entspannen", "schlafen", "gaeste")

        Returns:
            Liste von Aktions-Beschreibungen oder leer
        """
        intent_cfg = yaml_config.get("anticipation", {}).get("intent_sequences", {})
        if not intent_cfg:
            # Fallback: Hardcoded Defaults
            intent_cfg = {
                "entspannen": ["Rollladen runter", "Licht dimmen", "Temperatur senken", "Ambient-Musik"],
                "arbeiten": ["Rollladen hoch", "Licht hell", "Temperatur normal"],
                "schlafen": ["Tueren verriegeln", "Alle Lichter aus", "Heizung Eco", "Alarm scharf"],
                "gaeste": ["Angenehme Beleuchtung", "Angenehme Temperatur", "Hintergrundmusik"],
            }

        # Fuzzy-Match mit Wort-Grenzen und Negations-Check
        import re
        intent_lower = intent.lower().strip()
        # Negation erkennen
        negation_patterns = ("nicht ", "kein ", "ohne ", "nie ")
        for key, actions in intent_cfg.items():
            match = re.search(rf'\b{re.escape(key)}\b', intent_lower)
            if not match:
                continue
            # Pruefen ob Negation vor dem Keyword steht
            before = intent_lower[:match.start()]
            if any(before.rstrip().endswith(neg.strip()) for neg in negation_patterns):
                continue
            return actions

        return []

    # ------------------------------------------------------------------
    # Proaktive Vorschlaege
    # ------------------------------------------------------------------

    async def get_suggestions(self, person: str = "") -> list[dict]:
        """Prueft ob gerade ein Muster zutrifft und gibt Vorschlaege zurueck.

        Args:
            person: Wenn gesetzt, nur Vorschlaege fuer diese Person.
        """
        if not self.redis:
            return []

        patterns = await self.detect_patterns(person=person)
        if not patterns:
            return []

        now = datetime.now()
        suggestions = []

        for pattern in patterns:
            if pattern["confidence"] < self.min_confidence:
                continue

            # Wurde dieser Vorschlag kuerzlich schon gemacht?
            import hashlib as _hl
            _desc = pattern.get('description', '')[:200]
            _desc_hash = _hl.sha256(_desc.encode()).hexdigest()[:16]
            pattern_key = f"mha:anticipation:suggested:{_desc_hash}"
            already_suggested = await self.redis.get(pattern_key)
            if already_suggested:
                continue

            suggestion = None

            if pattern["type"] == "time":
                # Passt der aktuelle Zeitpunkt?
                if pattern["weekday"] == now.weekday() and pattern["hour"] == now.hour:
                    suggestion = {
                        "pattern": pattern,
                        "action": pattern["action"],
                        "args": pattern["args"],
                        "confidence": pattern["confidence"],
                        "description": pattern["description"],
                    }

            elif pattern["type"] == "sequence":
                # Wurde der Trigger gerade ausgefuehrt? (letzte 5 Min)
                recent = await self.redis.lrange("mha:action_log", 0, 4)
                for entry_json in recent:
                    try:
                        entry = json.loads(entry_json)
                        ts_str = entry.get("timestamp", "")
                        if not ts_str:
                            continue
                        ts = datetime.fromisoformat(ts_str)
                        if (now - ts).total_seconds() < 300:
                            if entry.get("action") == pattern["trigger_action"]:
                                suggestion = {
                                    "pattern": pattern,
                                    "action": pattern["follow_action"],
                                    "args": pattern["follow_args"],
                                    "confidence": pattern["confidence"],
                                    "description": pattern["description"],
                                }
                    except (json.JSONDecodeError, ValueError, TypeError):
                        continue

            elif pattern["type"] == "context":
                ctx = pattern.get("context", "")
                match = False

                if ctx.startswith("time_cluster:"):
                    # Tageszeit-Cluster
                    cluster = ctx.split(":")[1]
                    hour = now.hour
                    current_cluster = (
                        "morning" if 5 <= hour < 12
                        else "afternoon" if 12 <= hour < 17
                        else "evening" if 17 <= hour < 22
                        else "night"
                    )
                    match = (cluster == current_cluster)

                elif ctx.startswith("weather:"):
                    # Wetter-Kontext: Aktuelles Wetter pruefen
                    pattern_weather = ctx.split(":")[1]
                    current_weather = await self._get_current_weather()
                    match = (current_weather == pattern_weather)

                if match:
                    suggestion = {
                        "pattern": pattern,
                        "action": pattern["action"],
                        "args": pattern["args"],
                        "confidence": pattern["confidence"],
                        "description": pattern["description"],
                    }

            if suggestion:
                # Bestimme Delivery-Modus
                conf = suggestion["confidence"]
                if conf >= self.threshold_auto:
                    suggestion["mode"] = "auto"
                elif conf >= self.threshold_suggest:
                    suggestion["mode"] = "suggest"
                else:
                    suggestion["mode"] = "ask"

                # Device-Dependency-Check: Vorschlag validieren
                try:
                    from .state_change_log import StateChangeLog
                    import assistant.main as main_module
                    if hasattr(main_module, "brain"):
                        _states = await main_module.brain.ha.get_states() or []
                        _fn = suggestion.get("function", "")
                        _args = suggestion.get("args", {})
                        _dep_hints = StateChangeLog.check_action_dependencies(_fn, _args, _states)
                        if _dep_hints:
                            suggestion["dependency_warnings"] = _dep_hints
                            # Modus herabstufen: auto→suggest, suggest→ask
                            if suggestion["mode"] == "auto":
                                suggestion["mode"] = "suggest"
                            elif suggestion["mode"] == "suggest":
                                suggestion["mode"] = "ask"
                except Exception:
                    pass

                suggestions.append(suggestion)

                # Cooldown setzen (1 Stunde)
                await self.redis.setex(pattern_key, 3600, "1")

        return suggestions

    async def _get_current_weather(self) -> str:
        """Holt aktuelle Wetter-Condition fuer Pattern-Matching."""
        try:
            if self.redis:
                cached = await self.redis.get("mha:weather:current_condition")
                if cached:
                    return cached.decode("utf-8", errors="ignore") if isinstance(cached, bytes) else str(cached)
        except Exception as e:
            logger.debug("Weather cache retrieval failed: %s", e)
        return ""

    async def record_feedback(self, pattern_description: str, accepted: bool):
        """Passt Confidence basierend auf User-Feedback an.

        Abgelehnte Vorschlaege erhoehen den Cooldown exponentiell:
        1x abgelehnt = 2h, 2x = 4h, 3x = 8h, 4x+ = 24h.
        Akzeptierte Vorschlaege senken den Cooldown zurueck.
        """
        if not self.redis:
            return

        key = f"mha:anticipation:feedback:{pattern_description}"
        try:
            data = await self.redis.get(key)
            if data:
                feedback = json.loads(data)
            else:
                feedback = {"accepted": 0, "rejected": 0}

            if accepted:
                feedback["accepted"] += 1
                # Cooldown zuruecksetzen bei Akzeptanz
                feedback["rejected"] = max(0, feedback["rejected"] - 1)
            else:
                feedback["rejected"] += 1
                # Exponentieller Cooldown bei Ablehnung
                rejections = feedback["rejected"]
                cooldown_hours = min(24, 2 ** rejections)
                cooldown_key = f"mha:anticipation:suggested:{pattern_description}"
                await self.redis.setex(cooldown_key, cooldown_hours * 3600, "1")
                logger.info(
                    "Anticipation: '%s' abgelehnt (%dx) -> Cooldown %dh",
                    pattern_description, rejections, cooldown_hours,
                )

            await self.redis.setex(key, 30 * 86400, json.dumps(feedback))
        except Exception as e:
            logger.error("Fehler bei Anticipation-Feedback: %s", e)

    # ------------------------------------------------------------------
    # Feature: Predictive Pre-Execution (Auto-Execute bei Idle)
    # ------------------------------------------------------------------

    def __init_pre_execution_state(self):
        """Lazy-Init fuer Pre-Execution Tracking-State."""
        if not hasattr(self, "_pre_executed"):
            # {pattern_hash: datetime} — Cooldown-Tracking
            self._pre_executed: dict[str, datetime] = {}

    async def auto_execute_ready_patterns(self, brain):
        """Fuehrt Muster mit hoher Confidence automatisch aus (Idle-Pre-Execution).

        Bedingungen:
        - Confidence >= 0.95
        - Aktueller Kontext (Zeit, Wochentag, Wetter) passt
        - Autonomy-Level >= 3
        - Pattern wurde nicht in den letzten 30 Min bereits ausgefuehrt (Cooldown)

        Args:
            brain: Brain-Instanz mit task_registry und autonomy
        """
        self.__init_pre_execution_state()

        # Autonomy-Level pruefen (brain.autonomy.level oder Fallback)
        autonomy_level = getattr(getattr(brain, "autonomy", None), "level", 0)
        if autonomy_level < 3:
            logger.debug("Auto-Execute uebersprungen: Autonomy-Level %d < 3", autonomy_level)
            return

        patterns = await self.detect_patterns()
        if not patterns:
            return

        now = datetime.now()
        current_weather = await self._get_current_weather()

        # Abgelaufene Cooldowns entfernen (aelter als 30 Min)
        expired = [k for k, ts in self._pre_executed.items() if (now - ts).total_seconds() > 1800]
        for k in expired:
            del self._pre_executed[k]

        for pattern in patterns:
            if pattern["confidence"] < 0.95:
                continue

            # Kontext-Match pruefen: Zeit, Wochentag, Wetter
            if not self._pattern_matches_current_context(pattern, now, current_weather):
                continue

            # Cooldown-Check (30 Min)
            import hashlib as _hl
            p_desc = pattern.get("description", "")[:200]
            p_hash = _hl.sha256(p_desc.encode()).hexdigest()[:16]

            if p_hash in self._pre_executed:
                logger.debug("Auto-Execute Cooldown aktiv fuer: %s", p_desc)
                continue

            # Aktion bestimmen
            action = pattern.get("action") or pattern.get("follow_action", "")
            args = pattern.get("args") or pattern.get("follow_args", {})
            if not action:
                continue

            # Task erstellen und ausfuehren
            try:
                task_registry = getattr(brain, "_task_registry", None) or getattr(brain, "task_registry", None)
                if task_registry is None:
                    logger.warning("Auto-Execute: Kein task_registry auf brain gefunden")
                    return

                # Coroutine fuer die Ausfuehrung bauen
                async def _execute_action(a=action, ar=args):
                    """Wrapper fuer pre-executed Pattern-Aktion."""
                    if hasattr(brain, "execute_action"):
                        await brain.execute_action(a, ar)
                    elif hasattr(brain, "ha") and hasattr(brain.ha, "call_service"):
                        await brain.ha.call_service(a, **ar if isinstance(ar, dict) else {})

                task_registry.create_task(
                    _execute_action(),
                    name=f"anticipation:pre_exec:{action}",
                )

                # Cooldown setzen
                self._pre_executed[p_hash] = now

                logger.info(
                    "Auto-Execute: '%s' ausgefuehrt (Confidence: %.0f%%, Autonomy: %d)",
                    p_desc, pattern["confidence"] * 100, autonomy_level,
                )

            except Exception as e:
                logger.error("Auto-Execute fehlgeschlagen fuer '%s': %s", p_desc, e)

    def _pattern_matches_current_context(self, pattern: dict, now: datetime,
                                         current_weather: str) -> bool:
        """Prueft ob ein Pattern zum aktuellen Kontext (Zeit, Wochentag, Wetter) passt.

        Args:
            pattern: Das erkannte Muster
            now: Aktuelle Zeit
            current_weather: Aktuelle Wetter-Condition
        """
        p_type = pattern.get("type", "")

        if p_type == "time":
            # Wochentag und Stunde muessen passen
            return (pattern.get("weekday") == now.weekday()
                    and pattern.get("hour") == now.hour)

        elif p_type == "context":
            ctx = pattern.get("context", "")
            if ctx.startswith("time_cluster:"):
                cluster = ctx.split(":")[1]
                hour = now.hour
                current_cluster = (
                    "morning" if 5 <= hour < 12
                    else "afternoon" if 12 <= hour < 17
                    else "evening" if 17 <= hour < 22
                    else "night"
                )
                return cluster == current_cluster
            elif ctx.startswith("weather:"):
                pattern_weather = ctx.split(":")[1]
                return current_weather == pattern_weather

        elif p_type == "causal_chain":
            # Kausale Ketten: Trigger-Kontext pruefen
            trigger = pattern.get("trigger", "")
            if trigger.startswith("hour:"):
                try:
                    return int(trigger.split(":")[1]) == now.hour
                except (ValueError, IndexError):
                    pass
            elif trigger and current_weather:
                return trigger == current_weather

        # Sequenz-Muster: kein zeitbasierter Kontext, nicht auto-ausfuehrbar
        return False

    # ------------------------------------------------------------------
    # Feature: Habit Drift Detection
    # ------------------------------------------------------------------

    async def detect_habit_drift(self) -> list[dict]:
        """Erkennt Veraenderungen in Gewohnheiten (Drift) ueber die letzten 14 Tage.

        Vergleicht Muster der letzten 7 Tage mit den vorherigen 7 Tagen.
        Erkennt:
        - Neue Muster (tauchen auf)
        - Verschwundene Muster (fallen weg)
        - Zeitverschiebungen > 30 Min

        Returns:
            Liste von Drift-Beschreibungen mit type, action, message etc.
        """
        if not self.redis:
            return []

        try:
            now = datetime.now()
            # Alle Eintraege laden
            raw_entries = await self.redis.lrange("mha:action_log", 0, 999)
            if len(raw_entries) < 10:
                return []

            entries = [json.loads(e.decode() if isinstance(e, bytes) else e) for e in raw_entries]

            # In zwei Zeitraeume aufteilen
            recent_start = now - timedelta(days=7)
            previous_start = now - timedelta(days=14)

            recent_entries = []
            previous_entries = []

            for entry in entries:
                try:
                    ts = datetime.fromisoformat(entry.get("timestamp", ""))
                except (ValueError, TypeError):
                    continue
                if ts >= recent_start:
                    recent_entries.append(entry)
                elif ts >= previous_start:
                    previous_entries.append(entry)

            if not previous_entries:
                return []  # Zu wenig historische Daten

            drifts: list[dict] = []

            # --- Aktionen und deren Haeufigkeit/Zeitpunkte aggregieren ---
            recent_actions = self._aggregate_action_stats(recent_entries)
            previous_actions = self._aggregate_action_stats(previous_entries)

            all_actions = set(recent_actions.keys()) | set(previous_actions.keys())

            for action in all_actions:
                r_stats = recent_actions.get(action)
                p_stats = previous_actions.get(action)

                # Verschwundene Muster: War vorher da, jetzt nicht mehr
                if p_stats and not r_stats:
                    drifts.append({
                        "type": "disappeared",
                        "action": action,
                        "old_count": p_stats["count"],
                        "message": f"Du machst seit einer Woche kein {action} mehr",
                    })
                    continue

                # Neue Muster: Jetzt da, vorher nicht
                if r_stats and not p_stats:
                    drifts.append({
                        "type": "new",
                        "action": action,
                        "new_count": r_stats["count"],
                        "message": f"Neu seit einer Woche: {action} ({r_stats['count']}x)",
                    })
                    continue

                # Zeitverschiebung: Durchschnittszeit vergleichen
                if r_stats and p_stats:
                    r_avg_hour = r_stats["avg_hour"]
                    p_avg_hour = p_stats["avg_hour"]

                    # Differenz in Minuten (Stunden als Float)
                    diff_minutes = abs(r_avg_hour - p_avg_hour) * 60

                    # Zirkulaere Differenz beruecksichtigen (23:00 vs 01:00 = 2h)
                    diff_minutes_alt = (24 * 60) - diff_minutes
                    diff_minutes = min(diff_minutes, diff_minutes_alt)

                    if diff_minutes > 30:
                        old_h = int(p_avg_hour)
                        old_m = int((p_avg_hour - old_h) * 60)
                        new_h = int(r_avg_hour)
                        new_m = int((r_avg_hour - new_h) * 60)
                        old_time = f"{old_h:02d}:{old_m:02d}"
                        new_time = f"{new_h:02d}:{new_m:02d}"

                        # Richtung bestimmen
                        if r_avg_hour > p_avg_hour:
                            direction = "spaeter"
                        else:
                            direction = "frueher"

                        drifts.append({
                            "type": "time_shift",
                            "action": action,
                            "old_time": old_time,
                            "new_time": new_time,
                            "shift_minutes": round(diff_minutes),
                            "message": f"Du gehst seit einer Woche {direction} ins Bett"
                            if "schlaf" in action.lower() or "light" in action.lower()
                            else f"{action} hat sich um {round(diff_minutes)} Min verschoben ({old_time} → {new_time})",
                        })

            return drifts

        except Exception as e:
            logger.error("Fehler bei Habit-Drift-Detection: %s", e)
            return []

    @staticmethod
    def _aggregate_action_stats(entries: list[dict]) -> dict[str, dict]:
        """Aggregiert Aktions-Statistiken: Haeufigkeit und Durchschnittszeit.

        Returns:
            {action: {"count": int, "avg_hour": float}} — avg_hour als Dezimal (z.B. 22.5 = 22:30)
        """
        action_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "hours": []})

        for entry in entries:
            action = entry.get("action", "")
            if not action:
                continue
            hour = entry.get("hour", 0)
            # Feinere Zeit aus Timestamp extrahieren
            try:
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                precise_hour = ts.hour + ts.minute / 60.0
            except (ValueError, TypeError):
                precise_hour = float(hour)

            action_data[action]["count"] += 1
            action_data[action]["hours"].append(precise_hour)

        # Durchschnittliche Stunde berechnen
        result = {}
        for action, data in action_data.items():
            if data["count"] < 2:
                continue  # Einzelereignisse ignorieren
            avg_hour = sum(data["hours"]) / len(data["hours"])
            result[action] = {"count": data["count"], "avg_hour": avg_hour}

        return result

    # ------------------------------------------------------------------
    # Hintergrund-Loop
    # ------------------------------------------------------------------

    async def _check_loop(self):
        """Prueft periodisch auf zutreffende Muster."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)

                # Quiet Hours: Pattern-Detection komplett ueberspringen.
                # Spart CPU und vermeidet Log-Spam (Suggestions werden eh unterdrueckt).
                from .config import yaml_config
                from datetime import datetime
                quiet_cfg = yaml_config.get("ambient_presence", {})
                quiet_start = int(quiet_cfg.get("quiet_start", 22))
                quiet_end = int(quiet_cfg.get("quiet_end", 7))
                hour = datetime.now().hour
                if quiet_start > quiet_end:
                    is_quiet = hour >= quiet_start or hour < quiet_end
                else:
                    is_quiet = quiet_start <= hour < quiet_end
                if is_quiet:
                    continue

                suggestions = await self.get_suggestions()
                for suggestion in suggestions:
                    if self._notify_callback:
                        await self._notify_callback(suggestion)
                    logger.info(
                        "Anticipation-Vorschlag [%s]: %s (Confidence: %.0f%%)",
                        suggestion["mode"],
                        suggestion["description"],
                        suggestion["confidence"] * 100,
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fehler im Anticipation-Loop: %s", e)
                await asyncio.sleep(60)

    async def check_routine_deviation(self, persons_away: list[str]) -> list[dict]:
        """Prueft ob Personen ungewoehnlich spaet abwesend sind.

        Analysiert die Action-History nach 'person_arrived'-Events und berechnet
        die durchschnittliche Ankunftszeit. Wenn eine Person >90 Min spaeter als
        ueblich noch nicht da ist, wird eine Deviation gemeldet.

        Args:
            persons_away: Liste der aktuell abwesenden Personen

        Returns:
            Liste von Deviations: [{"person": str, "expected_time": str, "delay_minutes": int}]
        """
        if not self.redis or not persons_away:
            return []

        deviations = []
        now = datetime.now()

        # Nur zwischen 17:00 und 22:00 pruefen
        if not (17 <= now.hour <= 22):
            return []

        try:
            raw_entries = await self.redis.lrange("mha:action_log", 0, 999)
            entries = [json.loads(e.decode() if isinstance(e, bytes) else e) for e in raw_entries]

            for person in persons_away:
                # Alle Ankunfts-Events dieser Person sammeln
                arrival_hours = []
                for entry in entries:
                    if entry.get("action") == "person_arrived" and entry.get("person") == person:
                        ts_str = entry.get("timestamp", "")
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str)
                                arrival_hours.append(ts.hour + ts.minute / 60.0)
                            except (ValueError, TypeError):
                                continue

                if len(arrival_hours) < 3:
                    continue  # Nicht genug Daten

                avg_hour = sum(arrival_hours) / len(arrival_hours)
                # Standardabweichung
                variance = sum((h - avg_hour) ** 2 for h in arrival_hours) / len(arrival_hours)
                std_dev = variance ** 0.5

                # Erwartete Ankunftszeit + Toleranz (max 90 Min nach Durchschnitt)
                expected_hour = avg_hour + max(std_dev, 0.5)  # Mindestens 30 Min Toleranz
                current_hour = now.hour + now.minute / 60.0

                delay_minutes = int((current_hour - expected_hour) * 60)
                if delay_minutes >= 90:
                    expected_time = f"{int(avg_hour)}:{int((avg_hour % 1) * 60):02d}"
                    deviations.append({
                        "person": person,
                        "expected_time": expected_time,
                        "delay_minutes": delay_minutes,
                    })

        except Exception as e:
            logger.debug("Routine-Deviation Fehler: %s", e)

        return deviations
