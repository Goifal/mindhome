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
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "mha:person_prefs"
REDIS_TTL = 90 * 86400  # 90 Tage

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
        if spec and spec["type"] is float:
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
            if spec and spec["type"] is float:
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
            if spec["type"] is float:
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
