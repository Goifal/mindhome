"""
Smart Shopping - Intelligente Einkaufsliste mit Verbrauchsprognose.

Features:
- Verbrauchsmuster-Erkennung: Wie oft wird ein Artikel verbraucht?
- Proaktive Erinnerung: "Milch wird bald alle sein"
- Rezept-Integration: "Koche Lasagne" -> fehlende Zutaten auf Liste
- Kontext-Trigger: Einkaufsliste erwaehnen beim Verlassen
- Wochentag-Muster: "Samstags kaufst du meistens ein"

Nutzt bestehende HA Shopping List + Inventory Manager.
Verbrauchshistorie wird in Redis gespeichert.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config
from .constants import (
    SHOPPING_MIN_PURCHASES,
    SHOPPING_REMINDER_DAYS_BEFORE,
    SHOPPING_REMINDER_COOLDOWN_H,
    SHOPPING_CONSUMPTION_MAX_ENTRIES,
    SHOPPING_CONSUMPTION_TTL,
    SHOPPING_CONFIDENCE_DATAPOINTS,
    SHOPPING_LOW_STOCK_THRESHOLD,
)
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Redis Keys
_KEY_CONSUMPTION = "mha:shopping:consumption:"       # + item_name_lower
_KEY_PREDICTIONS = "mha:shopping:predictions"         # Hash
_KEY_SHOPPING_DAYS = "mha:shopping:shopping_days"     # Hash (weekday -> count)
_KEY_LAST_REMINDER = "mha:shopping:last_reminder:"    # + item_name_lower

# Defaults (aus constants.py)
_DEFAULT_MIN_PURCHASES = SHOPPING_MIN_PURCHASES
_DEFAULT_REMINDER_DAYS_BEFORE = SHOPPING_REMINDER_DAYS_BEFORE
_DEFAULT_REMINDER_COOLDOWN_H = SHOPPING_REMINDER_COOLDOWN_H


class SmartShopping:
    """Intelligente Einkaufslistenverwaltung mit Verbrauchsprognose."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None
        self._notify_callback = None

        # Konfiguration
        cfg = yaml_config.get("smart_shopping", {})
        self.enabled = cfg.get("enabled", True)
        self.min_purchases = cfg.get("min_purchases", _DEFAULT_MIN_PURCHASES)
        self.reminder_days_before = cfg.get("reminder_days_before", _DEFAULT_REMINDER_DAYS_BEFORE)
        self.reminder_cooldown_hours = cfg.get("reminder_cooldown_hours", _DEFAULT_REMINDER_COOLDOWN_H)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("SmartShopping initialisiert (enabled: %s)", self.enabled)

    def set_notify_callback(self, callback):
        """Setzt Callback fuer proaktive Einkaufs-Erinnerungen."""
        self._notify_callback = callback

    # ------------------------------------------------------------------
    # Verbrauchsprotokoll: Trackt wann Artikel gekauft/verbraucht werden
    # ------------------------------------------------------------------

    async def record_purchase(self, item_name: str, quantity: int = 1) -> dict:
        """Protokolliert einen Einkauf (z.B. wenn Artikel von Liste abgehakt wird).

        Speichert Timestamp + Menge in Redis fuer spaetere Prognose.
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "SmartShopping nicht verfuegbar"}

        key = _KEY_CONSUMPTION + item_name.lower().replace(" ", "_")
        now = datetime.now()
        entry = json.dumps({
            "date": now.isoformat(),
            "quantity": quantity,
        })

        try:
            await self.redis.rpush(key, entry)
            # Max N Eintraege pro Artikel (aelteste entfernen)
            await self.redis.ltrim(key, -SHOPPING_CONSUMPTION_MAX_ENTRIES, -1)
            await self.redis.expire(key, SHOPPING_CONSUMPTION_TTL)

            # Einkaufstag protokollieren (fuer Wochentag-Muster)
            weekday = str(now.weekday())  # 0=Mo, 6=So
            await self.redis.hincrby(_KEY_SHOPPING_DAYS, weekday, 1)
            await self.redis.expire(_KEY_SHOPPING_DAYS, SHOPPING_CONSUMPTION_TTL)

            # Prognose aktualisieren
            prediction = await self._calculate_prediction(item_name)
            if prediction:
                await self.redis.hset(
                    _KEY_PREDICTIONS,
                    item_name.lower(),
                    json.dumps(prediction),
                )

            logger.info("Einkauf protokolliert: %s (x%d)", item_name, quantity)
            return {"success": True, "message": f"'{item_name}' protokolliert."}
        except Exception as e:
            logger.error("Einkaufs-Protokollierung fehlgeschlagen: %s", e)
            return {"success": False, "message": str(e)}

    async def _calculate_prediction(self, item_name: str) -> Optional[dict]:
        """Berechnet den durchschnittlichen Verbrauchszyklus eines Artikels.

        Returns:
            Dict mit avg_days (Durchschnitt Tage zwischen Kaeufen),
            next_expected (naechster erwarteter Kauftermin),
            confidence (0-1 basierend auf Datenmenge).
        """
        if not self.redis:
            return None

        key = _KEY_CONSUMPTION + item_name.lower().replace(" ", "_")
        try:
            raw_entries = await self.redis.lrange(key, 0, -1)
            if not raw_entries or len(raw_entries) < self.min_purchases:
                return None

            dates = []
            for raw in raw_entries:
                entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                dates.append(datetime.fromisoformat(entry["date"]))

            dates.sort()

            # Intervalle zwischen Kaeufen berechnen
            intervals = []
            for i in range(1, len(dates)):
                delta = (dates[i] - dates[i - 1]).days
                if delta > 0:  # Gleicher Tag = Bulk-Kauf, nicht zaehlen
                    intervals.append(delta)

            if not intervals:
                return None

            avg_days = sum(intervals) / len(intervals)
            last_purchase = dates[-1]
            next_expected = last_purchase + timedelta(days=avg_days)

            # Confidence: mehr Datenpunkte = hoeher, max bei 10+
            confidence = min(1.0, len(intervals) / SHOPPING_CONFIDENCE_DATAPOINTS)

            return {
                "item": item_name,
                "avg_days": round(avg_days, 1),
                "last_purchase": last_purchase.isoformat(),
                "next_expected": next_expected.isoformat(),
                "confidence": round(confidence, 2),
                "data_points": len(intervals),
            }
        except Exception as e:
            logger.debug("Prognose-Berechnung fehlgeschlagen fuer '%s': %s", item_name, e)
            return None

    # ------------------------------------------------------------------
    # Prognose-Abfragen
    # ------------------------------------------------------------------

    async def get_predictions(self) -> list[dict]:
        """Gibt alle Verbrauchsprognosen zurueck, sortiert nach naechstem Kaufdatum."""
        if not self.redis or not self.enabled:
            return []

        try:
            raw = await self.redis.hgetall(_KEY_PREDICTIONS)
            predictions = []
            for key, val in raw.items():
                key = key.decode() if isinstance(key, bytes) else key
                val_str = val.decode() if isinstance(val, bytes) else val
                pred = json.loads(val_str)
                predictions.append(pred)

            # Sortiert nach naechstem erwarteten Kauf
            predictions.sort(
                key=lambda p: p.get("next_expected", "9999-12-31")
            )
            return predictions
        except Exception as e:
            logger.debug("Prognosen laden fehlgeschlagen: %s", e)
            return []

    async def get_items_running_low(self) -> list[dict]:
        """Gibt Artikel zurueck die bald nachgekauft werden muessen.

        Prueft ob next_expected innerhalb von reminder_days_before Tagen liegt.
        """
        predictions = await self.get_predictions()
        if not predictions:
            return []

        now = datetime.now()
        threshold = now + timedelta(days=self.reminder_days_before)
        running_low = []

        for pred in predictions:
            try:
                next_date = datetime.fromisoformat(pred["next_expected"])
                if next_date <= threshold and pred.get("confidence", 0) >= SHOPPING_LOW_STOCK_THRESHOLD:
                    days_until = (next_date - now).days
                    running_low.append({
                        **pred,
                        "days_until": days_until,
                        "urgency": "high" if days_until <= 0 else "medium",
                    })
            except (ValueError, KeyError):
                continue

        return running_low

    async def check_and_notify(self) -> list[str]:
        """Prueft ob Artikel bald aufgebraucht sind und sendet Erinnerungen.

        Wird periodisch vom Proactive Manager aufgerufen.
        Returns: Liste der erinnerten Artikel.
        """
        if not self.enabled or not self._notify_callback:
            return []

        running_low = await self.get_items_running_low()
        notified = []

        for item in running_low:
            item_name = item.get("item", "")
            if not item_name:
                continue

            # Cooldown pruefen (nicht zu oft erinnern)
            if await self._check_reminder_cooldown(item_name):
                continue

            days = item.get("days_until", 0)
            if days <= 0:
                msg = f"{item_name} muesste laut Verbrauchsmuster nachgekauft werden."
            else:
                msg = f"{item_name} wird in ca. {days} Tag(en) aufgebraucht sein."

            try:
                await self._notify_callback(
                    "shopping_reminder",
                    "low",  # Urgency
                    {"message": msg, "item": item_name},
                )
                await self._set_reminder_cooldown(item_name)
                notified.append(item_name)
            except Exception as e:
                logger.debug("Shopping-Erinnerung fehlgeschlagen fuer '%s': %s", item_name, e)

        return notified

    async def _check_reminder_cooldown(self, item_name: str) -> bool:
        """True wenn fuer diesen Artikel kuerzlich schon erinnert wurde."""
        if not self.redis:
            return False
        key = _KEY_LAST_REMINDER + item_name.lower().replace(" ", "_")
        return await self.redis.exists(key) > 0

    async def _set_reminder_cooldown(self, item_name: str):
        """Setzt den Cooldown fuer einen Artikel."""
        if not self.redis:
            return
        key = _KEY_LAST_REMINDER + item_name.lower().replace(" ", "_")
        await self.redis.setex(key, self.reminder_cooldown_hours * 3600, "1")

    # ------------------------------------------------------------------
    # Rezept-Integration: Fehlende Zutaten auf Einkaufsliste
    # ------------------------------------------------------------------

    async def add_missing_ingredients(self, ingredients: list[str]) -> dict:
        """Prueft welche Zutaten auf der Einkaufsliste fehlen und fuegt sie hinzu.

        Args:
            ingredients: Liste von Zutatennamen aus einem Rezept.

        Returns:
            Dict mit added (hinzugefuegt) und already_on_list (schon drauf).
        """
        if not ingredients:
            return {"added": [], "already_on_list": [], "message": "Keine Zutaten angegeben."}

        # Aktuelle Einkaufsliste holen
        try:
            current_items = await self.ha.api_get("/api/shopping_list")
        except Exception as e:
            logger.debug("Einkaufsliste laden fehlgeschlagen: %s", e)
            current_items = []

        current_names = set()
        if current_items and isinstance(current_items, list):
            for item in current_items:
                if not item.get("complete", False):
                    current_names.add(item.get("name", "").lower())

        added = []
        already = []

        for ingredient in ingredients:
            clean = ingredient.strip()
            if not clean:
                continue

            if clean.lower() in current_names:
                already.append(clean)
            else:
                try:
                    await self.ha.call_service(
                        "shopping_list", "add_item", {"name": clean}
                    )
                    added.append(clean)
                except Exception as e:
                    logger.debug("Zutat '%s' konnte nicht hinzugefuegt werden: %s", clean, e)

        # Ergebnis-Nachricht
        parts = []
        if added:
            parts.append(f"{len(added)} Zutat(en) auf die Einkaufsliste: {', '.join(added)}")
        if already:
            parts.append(f"Bereits auf der Liste: {', '.join(already)}")
        if not added and not already:
            parts.append("Keine Zutaten hinzugefuegt.")

        return {
            "added": added,
            "already_on_list": already,
            "message": ". ".join(parts),
        }

    # ------------------------------------------------------------------
    # Einkaufstag-Muster: Wann wird typischerweise eingekauft?
    # ------------------------------------------------------------------

    async def get_shopping_day_pattern(self) -> Optional[dict]:
        """Gibt das Einkaufstag-Muster zurueck.

        Returns:
            Dict mit preferred_day (haeufigster Wochentag),
            day_counts (Anzahl pro Wochentag).
        """
        if not self.redis:
            return None

        try:
            raw = await self.redis.hgetall(_KEY_SHOPPING_DAYS)
            if not raw:
                return None

            day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                         "Freitag", "Samstag", "Sonntag"]
            counts = {}
            for key, val in raw.items():
                k = key.decode() if isinstance(key, bytes) else key
                v = int(val.decode() if isinstance(val, bytes) else val)
                idx = int(k)
                if 0 <= idx <= 6:
                    counts[day_names[idx]] = v

            if not counts:
                return None

            preferred = max(counts, key=counts.get)
            return {
                "preferred_day": preferred,
                "day_counts": counts,
                "total_trips": sum(counts.values()),
            }
        except Exception as e:
            logger.debug("Einkaufstag-Muster fehlgeschlagen: %s", e)
            return None

    # ------------------------------------------------------------------
    # Zusammenfassung fuer Context Builder / Proactive
    # ------------------------------------------------------------------

    async def get_shopping_context(self) -> str:
        """Gibt eine kompakte Zusammenfassung fuer den LLM-Kontext zurueck."""
        parts = []

        # Offene Einkaufsliste
        try:
            items = await self.ha.api_get("/api/shopping_list")
            if items and isinstance(items, list):
                open_items = [i["name"] for i in items if not i.get("complete")]
                if open_items:
                    parts.append(f"Einkaufsliste ({len(open_items)}): {', '.join(open_items[:10])}")
        except Exception as e:
            logger.debug("Unhandled: %s", e)
        # Bald aufgebrauchte Artikel
        running_low = await self.get_items_running_low()
        if running_low:
            low_names = [f"{r['item']} (ca. {r['days_until']}d)" for r in running_low[:5]]
            parts.append(f"Bald aufgebraucht: {', '.join(low_names)}")

        # Einkaufstag-Muster
        pattern = await self.get_shopping_day_pattern()
        if pattern:
            parts.append(f"Ueblicher Einkaufstag: {pattern['preferred_day']}")

        return " | ".join(parts) if parts else ""
