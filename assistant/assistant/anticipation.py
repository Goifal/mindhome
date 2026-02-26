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
        self.history_days = cfg.get("history_days", 30)
        self.min_confidence = cfg.get("min_confidence", 0.6)
        self.check_interval = cfg.get("check_interval_minutes", 15) * 60

        thresholds = cfg.get("thresholds", {})
        self.threshold_ask = thresholds.get("ask", 0.6)
        self.threshold_suggest = thresholds.get("suggest", 0.8)
        self.threshold_auto = thresholds.get("auto", 0.95)

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

    async def log_action(self, action: str, args: dict, person: str = ""):
        """Loggt eine ausgefuehrte Aktion fuer Pattern-Detection."""
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

    async def detect_patterns(self) -> list[dict]:
        """Erkennt Muster in der Action-History."""
        if not self.redis:
            return []

        try:
            # Alle Aktionen laden
            raw_entries = await self.redis.lrange("mha:action_log", 0, 999)
            if len(raw_entries) < 10:
                return []  # Zu wenig Daten

            entries = [json.loads(e) for e in raw_entries]

            patterns = []

            # 1. Zeit-Muster erkennen
            time_patterns = self._detect_time_patterns(entries)
            patterns.extend(time_patterns)

            # 2. Sequenz-Muster erkennen
            seq_patterns = self._detect_sequence_patterns(entries)
            patterns.extend(seq_patterns)

            # 3. Kontext-Muster erkennen (Wetter, Tageszeit, Anwesenheit)
            ctx_patterns = self._detect_context_patterns(entries)
            patterns.extend(ctx_patterns)

            return patterns

        except Exception as e:
            logger.error("Fehler bei Pattern-Detection: %s", e)
            return []

    def _detect_time_patterns(self, entries: list[dict]) -> list[dict]:
        """Erkennt zeitbasierte Muster (gleiche Aktion zur gleichen Zeit).

        Neuere Aktionen werden staerker gewichtet als aeltere (Recency-Weighting).
        Eine Aktion von heute zaehlt 2x soviel wie eine von vor 30 Tagen.
        """
        patterns = []

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
                typical_args = args_counter.most_common(1)[0][0] if args_counter else "{}"

                weekday_names = [
                    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
                    "Freitag", "Samstag", "Sonntag",
                ]
                wd_idx = int(weekday) if weekday.isdigit() else -1
                wd_name = weekday_names[wd_idx] if 0 <= wd_idx < len(weekday_names) else weekday

                patterns.append({
                    "type": "time",
                    "action": action,
                    "args": json.loads(typical_args),
                    "weekday": int(weekday),
                    "hour": int(hour),
                    "confidence": round(confidence, 2),
                    "occurrences": occurrences,
                    "description": f"Jeden {wd_name} um {hour}:00 → {action}",
                })

        return patterns

    def _detect_sequence_patterns(self, entries: list[dict]) -> list[dict]:
        """Erkennt Sequenz-Muster (A -> B innerhalb von 5 Minuten)."""
        patterns = []

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

                patterns.append({
                    "type": "sequence",
                    "trigger_action": a,
                    "follow_action": b,
                    "follow_args": json.loads(typical_args),
                    "confidence": round(confidence, 2),
                    "occurrences": count,
                    "description": f"Nach {a} folgt meist {b}",
                })

        return patterns

    def _detect_context_patterns(self, entries: list[dict]) -> list[dict]:
        """Erkennt kontextbasierte Muster (Wetter, Tageszeit-Kombination).

        Sucht nach Aktionen die immer unter bestimmten Kontextbedingungen
        stattfinden, z.B. "Rolladen runter wenn Abend + Sommer".
        """
        patterns = []

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

                    patterns.append({
                        "type": "context",
                        "context": f"time_cluster:{cluster_name}",
                        "action": action,
                        "args": json.loads(typical_args),
                        "confidence": round(min(1.0, ratio * (cluster_count / 10)), 2),
                        "occurrences": cluster_count,
                        "description": f"{action} wird zu {ratio*100:.0f}% {cluster_labels[cluster_name]} ausgefuehrt",
                    })

        return patterns

    # ------------------------------------------------------------------
    # Proaktive Vorschlaege
    # ------------------------------------------------------------------

    async def get_suggestions(self) -> list[dict]:
        """Prueft ob gerade ein Muster zutrifft und gibt Vorschlaege zurueck."""
        if not self.redis:
            return []

        patterns = await self.detect_patterns()
        if not patterns:
            return []

        now = datetime.now()
        suggestions = []

        for pattern in patterns:
            if pattern["confidence"] < self.min_confidence:
                continue

            # Wurde dieser Vorschlag kuerzlich schon gemacht?
            pattern_key = f"mha:anticipation:suggested:{pattern.get('description', '')}"
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
                # Kontext-Muster: Passt der aktuelle Tageszeit-Cluster?
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
                    if cluster == current_cluster:
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

                suggestions.append(suggestion)

                # Cooldown setzen (1 Stunde)
                await self.redis.setex(pattern_key, 3600, "1")

        return suggestions

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
    # Hintergrund-Loop
    # ------------------------------------------------------------------

    async def _check_loop(self):
        """Prueft periodisch auf zutreffende Muster."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)

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
