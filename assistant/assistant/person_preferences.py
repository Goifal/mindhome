"""
Per-Person Preferences Store — Zentraler Speicher fuer persoenliche Vorlieben.

Speichert und liefert Default-Einstellungen pro Person (Helligkeit, Temperatur,
Lautstaerke, etc.), die bei jedem Befehl automatisch als Kontext bereitgestellt
werden, wenn keine expliziten Werte angegeben wurden.

Redis-Keys:
    mha:person_prefs:{person_lower}  (HASH)
        default_brightness: "60"
        default_temperature: "21.5"
        default_volume: "30"
        preferred_color_temp: "warm"
        ...

Quellen:
    1. Explizite Korrekturen (CorrectionMemory Regeln)
    2. Statische Config (person_profiles in settings.yaml)
    3. Gelerntes Verhalten (LearningObserver Patterns)
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "mha:person_prefs"
REDIS_TTL = 90 * 86400  # 90 Tage
HISTORY_KEY_PREFIX = "mha:person_prefs_history"
HISTORY_TTL = 180 * 86400  # 180 Tage History
HISTORY_MAX_ENTRIES = 100  # Max Snapshots pro Person+Key

# Bekannte Preference-Keys mit Typ und Grenzen
KNOWN_PREFERENCES = {
    "default_brightness": {"type": float, "min": 0, "max": 100, "unit": "%"},
    "default_temperature": {"type": float, "min": 15, "max": 28, "unit": "°C"},
    "default_volume": {"type": float, "min": 0, "max": 100, "unit": "%"},
    "preferred_color_temp": {"type": str, "values": ["warm", "neutral", "cool", "kalt"]},
    "preferred_music_genre": {"type": str},
    "morning_brightness": {"type": float, "min": 0, "max": 100, "unit": "%"},
    "evening_brightness": {"type": float, "min": 0, "max": 100, "unit": "%"},
    "sleep_temperature": {"type": float, "min": 15, "max": 25, "unit": "°C"},
}


class PersonPreferences:
    """Zentraler Speicher fuer Per-Person Defaults."""

    def __init__(self, redis_client):
        self.redis = redis_client

    def _key(self, person: str) -> str:
        return f"{REDIS_KEY_PREFIX}:{person.lower().strip()}"

    async def get(self, person: str, key: str, default=None):
        """Einzelne Praeferenz lesen."""
        if not person or not self.redis:
            return default
        val = await self.redis.hget(self._key(person), key)
        if val is None:
            return default
        spec = KNOWN_PREFERENCES.get(key)
        if spec and spec["type"] == float:
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        return val

    async def get_all(self, person: str) -> dict:
        """Alle Praeferenzen einer Person lesen."""
        if not person or not self.redis:
            return {}
        raw = await self.redis.hgetall(self._key(person))
        result = {}
        for k, v in raw.items():
            spec = KNOWN_PREFERENCES.get(k)
            if spec and spec["type"] == float:
                try:
                    result[k] = float(v)
                except (ValueError, TypeError):
                    result[k] = v
            else:
                result[k] = v
        return result

    async def set(self, person: str, key: str, value) -> bool:
        """Einzelne Praeferenz setzen (mit Validierung)."""
        if not person or not self.redis:
            return False
        spec = KNOWN_PREFERENCES.get(key)
        if spec:
            if spec["type"] == float:
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    logger.warning("PersonPrefs: Ungueltiger Wert fuer %s: %s", key, value)
                    return False
                if "min" in spec and value < spec["min"]:
                    value = spec["min"]
                if "max" in spec and value > spec["max"]:
                    value = spec["max"]
            elif "values" in spec and value not in spec["values"]:
                logger.warning("PersonPrefs: Ungueltiger Wert fuer %s: %s (erlaubt: %s)",
                               key, value, spec["values"])
                return False
        await self.redis.hset(self._key(person), key, str(value))
        await self.redis.expire(self._key(person), REDIS_TTL)

        # Preference Evolution: Numerische Aenderungen historisch tracken
        spec = KNOWN_PREFERENCES.get(key)
        if spec and spec["type"] == float:
            await self._record_history(person, key, float(value))

        logger.info("PersonPrefs: %s.%s = %s", person, key, value)
        return True

    async def set_many(self, person: str, prefs: dict) -> int:
        """Mehrere Praeferenzen auf einmal setzen."""
        count = 0
        for k, v in prefs.items():
            if await self.set(person, k, v):
                count += 1
        return count

    async def learn_from_correction(self, person: str, action: str,
                                     original_args: dict, corrected_args: dict):
        """Lernt Praeferenzen aus Korrekturen.

        Wenn ein User z.B. immer die Helligkeit von 50 auf 70 korrigiert,
        wird default_brightness=70 gespeichert.
        """
        if not person:
            return

        mapping = {
            "set_light": {
                "brightness": "default_brightness",
                "color_temp": "preferred_color_temp",
            },
            "set_climate": {
                "temperature": "default_temperature",
            },
            "play_media": {
                "volume": "default_volume",
            },
        }

        action_map = mapping.get(action, {})
        for param, pref_key in action_map.items():
            if param in corrected_args and corrected_args[param] != original_args.get(param):
                await self.set(person, pref_key, corrected_args[param])
                logger.info(
                    "PersonPrefs: Gelernt aus Korrektur: %s bevorzugt %s=%s",
                    person, pref_key, corrected_args[param],
                )

    async def get_context_hint(self, person: str) -> str:
        """Erzeugt einen Kontext-Hinweis fuer den LLM-Prompt."""
        prefs = await self.get_all(person)
        if not prefs:
            return ""
        parts = []
        for k, v in prefs.items():
            spec = KNOWN_PREFERENCES.get(k, {})
            unit = spec.get("unit", "")
            label = k.replace("_", " ").replace("default ", "").title()
            parts.append(f"{label}: {v}{unit}")
        return f"Persoenliche Praeferenzen von {person}: {', '.join(parts)}"

    # ------------------------------------------------------------------
    # Preference Evolution: Historische Trend-Erkennung
    # ------------------------------------------------------------------

    def _history_key(self, person: str, pref_key: str) -> str:
        return f"{HISTORY_KEY_PREFIX}:{person.lower().strip()}:{pref_key}"

    async def _record_history(self, person: str, key: str, value: float):
        """Speichert einen historischen Snapshot einer Praeferenz-Aenderung."""
        if not self.redis:
            return
        try:
            entry = json.dumps({
                "value": round(value, 2),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            hk = self._history_key(person, key)
            await self.redis.lpush(hk, entry)
            await self.redis.ltrim(hk, 0, HISTORY_MAX_ENTRIES - 1)
            await self.redis.expire(hk, HISTORY_TTL)
        except Exception as e:
            logger.debug("PersonPrefs History-Write fehlgeschlagen: %s", e)

    async def get_preference_trend(self, person: str, key: str) -> Optional[dict]:
        """Erkennt Praeferenz-Trends ueber die letzten Monate.

        Returns:
            Dict mit direction ('rising'/'falling'/'stable'), change_pct,
            first_value, latest_value, span_days. Oder None.
        """
        if not self.redis or not person:
            return None
        try:
            hk = self._history_key(person, key)
            raw = await self.redis.lrange(hk, 0, HISTORY_MAX_ENTRIES - 1)
            if not raw or len(raw) < 3:
                return None

            entries = []
            for r in raw:
                try:
                    entry = json.loads(r)
                    entries.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue

            if len(entries) < 3:
                return None

            # Chronologisch sortieren (aelteste zuerst)
            entries.reverse()

            first_val = entries[0]["value"]
            latest_val = entries[-1]["value"]

            # Zeitspanne berechnen
            try:
                first_ts = datetime.fromisoformat(entries[0]["ts"])
                latest_ts = datetime.fromisoformat(entries[-1]["ts"])
                span_days = max(1, (latest_ts - first_ts).days)
            except (ValueError, TypeError):
                span_days = 1

            if first_val == 0:
                return None

            change_pct = ((latest_val - first_val) / abs(first_val)) * 100

            # Trend bestimmen: >5% Aenderung = signifikant
            if change_pct > 5:
                direction = "rising"
            elif change_pct < -5:
                direction = "falling"
            else:
                direction = "stable"

            return {
                "direction": direction,
                "change_pct": round(change_pct, 1),
                "first_value": first_val,
                "latest_value": latest_val,
                "span_days": span_days,
                "data_points": len(entries),
            }
        except Exception as e:
            logger.debug("PersonPrefs Trend-Erkennung fehlgeschlagen: %s", e)
            return None

    async def get_all_trends(self, person: str) -> dict:
        """Gibt Trends fuer alle numerischen Praeferenzen einer Person zurueck."""
        trends = {}
        for key, spec in KNOWN_PREFERENCES.items():
            if spec["type"] == float:
                trend = await self.get_preference_trend(person, key)
                if trend and trend["direction"] != "stable":
                    trends[key] = trend
        return trends
