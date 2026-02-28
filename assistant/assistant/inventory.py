"""
Inventory / Vorrats-Tracking - Vorratsmanagement mit Ablaufdaten.

Phase 15.2 Erweiterung: Verwaltet Vorratsartikel mit Ablaufdatum.
Warnt bei bald ablaufenden Artikeln und fuegt automatisch
fehlende Artikel zur HA-Einkaufsliste hinzu.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class InventoryManager:
    """Verwaltet den Haushalts-Vorrat mit Ablaufdaten."""

    def __init__(self, ha_client):
        self.ha = ha_client
        self.redis: Optional[redis.Redis] = None
        self._notify_callback = None

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("Inventory Manager initialisiert")

    def set_notify_callback(self, callback):
        """Setzt Callback fuer Ablauf-Warnungen."""
        self._notify_callback = callback

    async def add_item(self, name: str, quantity: int = 1,
                       expiry_date: str = "", category: str = "sonstiges") -> dict:
        """
        Fuegt einen Vorratsartikel hinzu.

        Args:
            name: Artikelname
            quantity: Menge
            expiry_date: Ablaufdatum (YYYY-MM-DD) oder leer
            category: Kategorie (kuehlschrank, gefrier, vorrat, sonstiges)
        """
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        # F-042: UUID statt Timestamp-Suffix (verhindert Kollision bei gleicher Sekunde)
        import uuid
        item_id = f"inv_{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
        item = {
            "id": item_id,
            "name": name,
            "quantity": str(quantity),
            "expiry_date": expiry_date,
            "category": category,
            "added_at": datetime.now().isoformat(),
        }

        try:
            await self.redis.hset(f"mha:inventory:{item_id}", mapping=item)
            await self.redis.sadd("mha:inventory:all", item_id)
            await self.redis.sadd(f"mha:inventory:cat:{category}", item_id)
            logger.info("Vorrat hinzugefuegt: %s (x%d, Ablauf: %s)", name, quantity, expiry_date or "keins")
            return {"success": True, "message": f"'{name}' (x{quantity}) zum Vorrat hinzugefuegt."}
        except Exception as e:
            logger.error("Vorrat-Fehler: %s", e)
            return {"success": False, "message": f"Da gab es ein Problem: {e}"}

    async def remove_item(self, name: str) -> dict:
        """Entfernt einen Artikel aus dem Vorrat (nach Name suchen)."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        try:
            item_ids = await self.redis.smembers("mha:inventory:all")
            for item_id in item_ids:
                data = await self.redis.hgetall(f"mha:inventory:{item_id}")
                if data and data.get("name", "").lower() == name.lower():
                    category = data.get("category", "sonstiges")
                    await self.redis.delete(f"mha:inventory:{item_id}")
                    await self.redis.srem("mha:inventory:all", item_id)
                    await self.redis.srem(f"mha:inventory:cat:{category}", item_id)
                    return {"success": True, "message": f"'{name}' aus dem Vorrat entfernt."}
            return {"success": False, "message": f"'{name}' nicht im Vorrat gefunden."}
        except Exception as e:
            return {"success": False, "message": f"Da gab es ein Problem: {e}"}

    async def update_quantity(self, name: str, quantity: int) -> dict:
        """Aktualisiert die Menge eines Artikels."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        try:
            item_ids = await self.redis.smembers("mha:inventory:all")
            for item_id in item_ids:
                data = await self.redis.hgetall(f"mha:inventory:{item_id}")
                if data and data.get("name", "").lower() == name.lower():
                    if quantity <= 0:
                        return await self.remove_item(name)
                    await self.redis.hset(f"mha:inventory:{item_id}", "quantity", str(quantity))
                    return {"success": True, "message": f"'{name}' Menge auf {quantity} aktualisiert."}
            return {"success": False, "message": f"'{name}' nicht im Vorrat gefunden."}
        except Exception as e:
            return {"success": False, "message": f"Da gab es ein Problem: {e}"}

    async def list_items(self, category: str = "") -> dict:
        """Listet alle Vorratsartikel (optional nach Kategorie)."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        try:
            if category:
                item_ids = await self.redis.smembers(f"mha:inventory:cat:{category}")
            else:
                item_ids = await self.redis.smembers("mha:inventory:all")

            items = []
            for item_id in item_ids:
                data = await self.redis.hgetall(f"mha:inventory:{item_id}")
                if data:
                    items.append(data)

            if not items:
                return {"success": True, "message": "Der Vorrat ist leer."}

            # Nach Ablaufdatum sortieren (bald ablaufend zuerst)
            items.sort(key=lambda x: x.get("expiry_date") or "9999-12-31")

            lines = [f"Vorrat ({len(items)} Artikel):"]
            for item in items:
                name = item.get("name", "?")
                qty = item.get("quantity", "1")
                expiry = item.get("expiry_date", "")
                cat = item.get("category", "")
                line = f"- {name} (x{qty})"
                if expiry:
                    days_left = self._days_until(expiry)
                    if days_left is not None:
                        if days_left < 0:
                            line += f" — ABGELAUFEN seit {abs(days_left)} Tag(en)!"
                        elif days_left == 0:
                            line += " — laeuft HEUTE ab!"
                        elif days_left <= 3:
                            line += f" — laeuft in {days_left} Tag(en) ab"
                        else:
                            line += f" (bis {expiry})"
                if cat and cat != "sonstiges":
                    line += f" [{cat}]"
                lines.append(line)

            return {"success": True, "message": "\n".join(lines)}
        except Exception as e:
            return {"success": False, "message": f"Da gab es ein Problem: {e}"}

    async def check_expiring(self, days_ahead: int = 3) -> list[dict]:
        """Prueft auf bald ablaufende Artikel."""
        if not self.redis:
            return []

        try:
            item_ids = await self.redis.smembers("mha:inventory:all")
            expiring = []

            for item_id in item_ids:
                data = await self.redis.hgetall(f"mha:inventory:{item_id}")
                if not data:
                    continue

                expiry = data.get("expiry_date", "")
                if not expiry:
                    continue

                days_left = self._days_until(expiry)
                if days_left is not None and days_left <= days_ahead:
                    expiring.append({
                        "name": data.get("name", "?"),
                        "quantity": int(data.get("quantity", 1)),
                        "expiry_date": expiry,
                        "days_left": days_left,
                        "category": data.get("category", "sonstiges"),
                    })

            expiring.sort(key=lambda x: x["days_left"])
            return expiring
        except Exception as e:
            logger.error("Ablauf-Check Fehler: %s", e)
            return []

    async def auto_add_to_shopping_list(self, item_name: str) -> bool:
        """Fuegt einen Artikel automatisch zur HA-Einkaufsliste hinzu."""
        try:
            success = await self.ha.call_service(
                "shopping_list", "add_item", {"name": item_name}
            )
            if success:
                logger.info("Auto-Einkaufsliste: '%s' hinzugefuegt", item_name)
            return success
        except Exception as e:
            logger.error("Auto-Einkaufsliste Fehler: %s", e)
            return False

    @staticmethod
    def _days_until(date_str: str) -> Optional[int]:
        """Berechnet Tage bis zu einem Datum."""
        try:
            expiry = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            return (expiry - today).days
        except (ValueError, TypeError):
            return None
