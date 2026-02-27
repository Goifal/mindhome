"""
Error Pattern Analysis - Erkennt wiederkehrende Fehlermuster.

Trackt Fehler nach Typ (timeout, service_unavailable, entity_not_found).
Wenn gleiches Muster 3+ mal in 1h: proaktive Mitigation (z.B. Fallback-Model).

Sicherheit: Rein beobachtend. Mitigations aendern nur Laufzeit-Routing (nicht persistent).
TTL 24h = Auto-Reset. Keine neuen HA-Rechte.
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Bekannte Fehler-Typen
ERROR_TYPES = ("timeout", "service_unavailable", "entity_not_found",
               "bad_params", "model_overloaded")

# Mitigation-Typen
MITIGATION_USE_FALLBACK = "use_fallback"
MITIGATION_WARN_USER = "warn_user"
MITIGATION_SKIP_ENTITY = "skip_entity"


class ErrorPatternTracker:
    """Trackt wiederkehrende Fehler und schlaegt Mitigations vor."""

    def __init__(self):
        self.redis = None
        self.enabled = False
        self._cfg = yaml_config.get("error_patterns", {})
        self._min_occurrences = self._cfg.get("min_occurrences_for_mitigation", 3)
        self._mitigation_ttl_hours = self._cfg.get("mitigation_ttl_hours", 1)

    async def initialize(self, redis_client):
        """Initialisiert mit Redis Client."""
        self.redis = redis_client
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info("ErrorPatternTracker initialisiert (enabled=%s)", self.enabled)

    async def record_error(self, error_type: str, action_type: str = "",
                           model: str = "", context: str = ""):
        """Speichert einen Fehler und prueft auf Muster."""
        if not self.enabled or not self.redis:
            return

        if error_type not in ERROR_TYPES:
            error_type = "unknown"

        now = time.time()
        entry = json.dumps({
            "error_type": error_type,
            "action_type": action_type,
            "model": model,
            "context": context[:200] if context else "",
            "timestamp": datetime.now().isoformat(),
            "ts": now,
        }, ensure_ascii=False)

        # In Recent-Liste speichern
        await self.redis.lpush("mha:errors:recent", entry)
        await self.redis.ltrim("mha:errors:recent", 0, 199)
        await self.redis.expire("mha:errors:recent", 30 * 86400)

        # Pattern-Counter erhoehen (stuendlich)
        hour_key = datetime.now().strftime("%Y-%m-%d-%H")
        pattern_key = f"mha:errors:pattern:{error_type}:{action_type}:{hour_key}"
        count = await self.redis.incr(pattern_key)
        await self.redis.expire(pattern_key, 7200)  # 2h TTL

        # Model-spezifischer Counter
        if model:
            model_key = f"mha:errors:pattern:{error_type}:model:{model}:{hour_key}"
            model_count = await self.redis.incr(model_key)
            await self.redis.expire(model_key, 7200)
        else:
            model_count = 0

        # Mitigation aktivieren wenn Schwelle erreicht
        if count >= self._min_occurrences or model_count >= self._min_occurrences:
            await self._activate_mitigation(error_type, action_type, model, int(count))

        logger.debug("Error recorded: %s/%s (count this hour: %s)", error_type, action_type, count)

    async def get_mitigation(self, action_type: str = "",
                             model: str = "") -> Optional[dict]:
        """Prueft ob eine aktive Mitigation existiert."""
        if not self.enabled or not self.redis:
            return None

        # Model-spezifische Mitigation pruefen
        if model:
            key = f"mha:errors:mitigation:model:{model}"
            raw = await self.redis.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass

        # Action-spezifische Mitigation
        if action_type:
            key = f"mha:errors:mitigation:{action_type}"
            raw = await self.redis.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass

        return None

    async def get_stats(self) -> dict:
        """Statistiken fuer Self-Report."""
        if not self.redis:
            return {}

        # Recent errors zaehlen nach Typ
        raw = await self.redis.lrange("mha:errors:recent", 0, 199)
        type_counts = {}
        recent_24h = 0
        now = time.time()

        for item in raw:
            try:
                entry = json.loads(item)
                et = entry.get("error_type", "unknown")
                type_counts[et] = type_counts.get(et, 0) + 1
                ts = entry.get("ts", 0)
                if now - ts < 86400:
                    recent_24h += 1
            except (json.JSONDecodeError, KeyError):
                continue

        # Aktive Mitigations zaehlen
        active_mitigations = 0
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match="mha:errors:mitigation:*", count=20
            )
            active_mitigations += len(keys)
            if cursor == 0:
                break

        return {
            "total_recent": len(raw),
            "last_24h": recent_24h,
            "by_type": type_counts,
            "active_mitigations": active_mitigations,
        }

    # --- Private Methoden ---

    async def _activate_mitigation(self, error_type: str, action_type: str,
                                   model: str, count: int):
        """Aktiviert eine temporaere Mitigation."""
        if not self.redis:
            return

        ttl = self._mitigation_ttl_hours * 3600

        if error_type == "timeout" and model:
            mitigation = {
                "type": MITIGATION_USE_FALLBACK,
                "reason": f"{count}x timeout fuer {model} in letzter Stunde",
                "original_model": model,
                "activated_at": datetime.now().isoformat(),
            }
            key = f"mha:errors:mitigation:model:{model}"
            await self.redis.setex(key, ttl, json.dumps(mitigation, ensure_ascii=False))
            logger.info("Mitigation aktiviert: use_fallback fuer %s (TTL: %dh, Grund: %dx timeout)",
                        model, self._mitigation_ttl_hours, count)

        elif error_type == "service_unavailable" and action_type:
            mitigation = {
                "type": MITIGATION_WARN_USER,
                "reason": f"{count}x service_unavailable fuer {action_type}",
                "action_type": action_type,
                "activated_at": datetime.now().isoformat(),
            }
            key = f"mha:errors:mitigation:{action_type}"
            await self.redis.setex(key, ttl, json.dumps(mitigation, ensure_ascii=False))
            logger.info("Mitigation aktiviert: warn_user fuer %s (TTL: %dh)",
                        action_type, self._mitigation_ttl_hours)

        elif error_type == "entity_not_found" and action_type:
            mitigation = {
                "type": MITIGATION_SKIP_ENTITY,
                "reason": f"{count}x entity_not_found bei {action_type}",
                "action_type": action_type,
                "activated_at": datetime.now().isoformat(),
            }
            key = f"mha:errors:mitigation:{action_type}"
            await self.redis.setex(key, ttl, json.dumps(mitigation, ensure_ascii=False))
            logger.info("Mitigation aktiviert: skip_entity fuer %s", action_type)
