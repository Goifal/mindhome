"""
Meal Planner - Essensplanung die Cooking, Shopping und Inventory verbindet.

Erstellt Wochenplaene basierend auf:
- Vorhandenen Vorraeten (Inventory)
- Gespeicherten Vorlieben & Allergien (Semantic Memory)
- Vergangenen Mahlzeiten (History)
- Einkaufsmustern (Smart Shopping)

Features:
- Wochenplan erstellen (LLM-gestuetzt)
- "Was koennen wir mit dem kochen was wir haben?"
- Fehlende Zutaten automatisch auf Einkaufsliste
- Mahlzeiten-Historie fuehren
- Ernaehrungsbalance beruecksichtigen

Redis Keys:
- mha:meals:plan:{week_key}      - Wochenplan (Hash)
- mha:meals:history               - Mahlzeiten-Historie (Sorted Set)
- mha:meals:entry:{meal_id}       - Einzelne Mahlzeit (Hash)
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

_cfg = yaml_config.get("meal_planner", {})
_ENABLED = _cfg.get("enabled", True)
_DEFAULT_PORTIONS = _cfg.get("default_portions", 2)
_HISTORY_MAX_ENTRIES = _cfg.get("history_max_entries", 100)
_PLAN_TTL_DAYS = _cfg.get("plan_ttl_days", 14)

_MEAL_TYPES = frozenset({"fruehstueck", "mittagessen", "abendessen", "snack"})
_WEEKDAYS_DE = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]


class MealPlanner:
    """Essensplanung mit Integration von Cooking, Shopping und Inventory."""

    def __init__(self, ollama_client):
        self.ollama = ollama_client
        self.redis: Optional[aioredis.Redis] = None
        self.inventory = None
        self.smart_shopping = None
        self.semantic_memory = None
        self.ha = None
        self.model_router = None

    def set_model_router(self, router):
        """Setzt den ModelRouter fuer LLM-Tier-Auswahl."""
        self.model_router = router

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("MealPlanner initialisiert")

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    async def suggest_from_inventory(self, portions: int = 0) -> dict:
        """Schlaegt Gerichte vor basierend auf vorhandenen Vorraeten.

        'Was koennen wir mit dem kochen was wir haben?'
        """
        if not self.inventory:
            return {
                "success": False,
                "message": "Inventar-System nicht verfuegbar.",
            }

        portions = portions or _DEFAULT_PORTIONS

        # Vorraete laden
        inv_result = await self.inventory.list_items()
        items = inv_result.get("items", [])
        if not items:
            return {
                "success": True,
                "message": "Keine Vorraete gespeichert. "
                "Fuege zuerst Artikel zum Inventar hinzu.",
            }

        # Items die bald ablaufen priorisieren
        item_names = []
        priority_items = []
        for item in items:
            name = item.get("name", "")
            if name:
                item_names.append(name)
                expiry = item.get("expiry_date", "")
                if expiry:
                    try:
                        exp_date = datetime.strptime(expiry, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                        days_left = (
                            exp_date.date() - datetime.now(timezone.utc).date()
                        ).days
                        if days_left <= 3:
                            priority_items.append(
                                f"{name} (laeuft in {days_left} Tagen ab!)"
                            )
                    except ValueError:
                        pass

        # Vorlieben und Allergien laden
        dietary_info = await self._get_dietary_info()

        # LLM fragen
        prompt = self._build_suggestion_prompt(
            item_names, priority_items, dietary_info, portions
        )

        try:
            response = await self.ollama.generate(
                prompt=prompt,
                model=self._get_model("smart"),
                max_tokens=800,
            )
            return {
                "success": True,
                "message": response.strip(),
            }
        except Exception as e:
            logger.error("LLM-Fehler bei Essensvorschlag: %s", e)
            return {
                "success": False,
                "message": "Konnte keine Vorschlaege generieren.",
            }

    async def create_weekly_plan(
        self, preferences: str = "", portions: int = 0
    ) -> dict:
        """Erstellt einen Wochenplan.

        Args:
            preferences: Optionale Wuensche ("viel Gemuese", "keine Pasta", etc.)
            portions: Anzahl Portionen
        """
        portions = portions or _DEFAULT_PORTIONS

        # Kontext sammeln
        dietary_info = await self._get_dietary_info()
        recent_meals = await self._get_recent_meals(14)  # Letzte 2 Wochen
        inventory_items = await self._get_inventory_items()

        prompt = self._build_plan_prompt(
            dietary_info, recent_meals, inventory_items, preferences, portions
        )

        try:
            response = await self.ollama.generate(
                prompt=prompt,
                model=self._get_model("deep"),
                max_tokens=1500,
            )

            # Plan speichern
            if self.redis:
                now = datetime.now(timezone.utc)
                week_key = now.strftime("%Y-W%V")
                plan_data = {
                    "content": response.strip(),
                    "portions": str(portions),
                    "preferences": preferences,
                    "created_at": now.isoformat(),
                }
                await self.redis.hset(f"mha:meals:plan:{week_key}", mapping=plan_data)
                await self.redis.expire(
                    f"mha:meals:plan:{week_key}", _PLAN_TTL_DAYS * 86400
                )

            return {"success": True, "message": response.strip()}
        except Exception as e:
            logger.error("LLM-Fehler bei Wochenplan: %s", e)
            return {
                "success": False,
                "message": "Konnte keinen Wochenplan erstellen.",
            }

    async def log_meal(
        self,
        meal: str,
        meal_type: str = "abendessen",
        portions: int = 0,
        rating: int = 0,
    ) -> dict:
        """Protokolliert eine Mahlzeit.

        Args:
            meal: Was wurde gegessen
            meal_type: fruehstueck, mittagessen, abendessen, snack
            portions: Wie viele Portionen
            rating: 1-5 Bewertung (0 = keine)
        """
        if not meal:
            return {"success": False, "message": "Keine Mahlzeit angegeben."}

        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        meal_type = (
            meal_type.lower() if meal_type.lower() in _MEAL_TYPES else "abendessen"
        )

        meal_id = f"meal_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)

        entry = {
            "id": meal_id,
            "meal": meal.strip(),
            "meal_type": meal_type,
            "portions": str(portions or _DEFAULT_PORTIONS),
            "rating": str(max(0, min(5, rating))),
            "date": now.strftime("%Y-%m-%d"),
            "created_at": now.isoformat(),
        }

        await self.redis.hset(f"mha:meals:entry:{meal_id}", mapping=entry)
        await self.redis.zadd("mha:meals:history", {meal_id: now.timestamp()})

        # Limit einhalten
        total = await self.redis.zcard("mha:meals:history")
        if total > _HISTORY_MAX_ENTRIES:
            oldest = await self.redis.zrange(
                "mha:meals:history", 0, total - _HISTORY_MAX_ENTRIES - 1
            )
            for old_id in oldest:
                old_str = old_id if isinstance(old_id, str) else old_id.decode()
                await self.redis.delete(f"mha:meals:entry:{old_str}")
                await self.redis.zrem("mha:meals:history", old_str)

        rating_hint = (
            f" (Bewertung: {'★' * rating}{'☆' * (5 - rating)})" if rating else ""
        )
        return {
            "success": True,
            "message": f"Mahlzeit '{meal}' protokolliert{rating_hint}.",
        }

    async def get_meal_history(self, days: int = 7) -> dict:
        """Zeigt die Mahlzeiten-Historie der letzten X Tage."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        meal_ids = await self.redis.zrangebyscore(
            "mha:meals:history",
            cutoff.timestamp(),
            "+inf",
        )

        if not meal_ids:
            return {
                "success": True,
                "message": f"Keine Mahlzeiten in den letzten {days} Tagen protokolliert.",
            }

        pipe = self.redis.pipeline()
        ids_list = []
        for mid in meal_ids:
            mid_str = mid if isinstance(mid, str) else mid.decode()
            ids_list.append(mid_str)
            pipe.hgetall(f"mha:meals:entry:{mid_str}")
        results = await pipe.execute()

        meals = []
        for mid, data in zip(ids_list, results):
            if data:
                decoded = _decode_hash(data)
                meals.append(decoded)

        meals.sort(key=lambda m: m.get("created_at", ""), reverse=True)

        lines = []
        current_date = ""
        for m in meals:
            date = m.get("date", "?")
            if date != current_date:
                current_date = date
                lines.append(f"\n{date}:")
            meal_type = m.get("meal_type", "")
            meal_name = m.get("meal", "?")
            rating = int(m.get("rating", "0"))
            rating_str = f" {'★' * rating}" if rating > 0 else ""
            lines.append(f"  {meal_type}: {meal_name}{rating_str}")

        return {
            "success": True,
            "message": f"Mahlzeiten (letzte {days} Tage):" + "\n".join(lines),
        }

    async def add_missing_to_shopping(self, recipe_ingredients: list[str]) -> dict:
        """Fuegt fehlende Zutaten zur Einkaufsliste hinzu.

        Prueft gegen Inventar was bereits vorhanden ist.
        """
        if not recipe_ingredients:
            return {"success": False, "message": "Keine Zutaten angegeben."}

        # Was ist bereits im Inventar?
        available = set()
        if self.inventory:
            inv_result = await self.inventory.list_items()
            for item in inv_result.get("items", []):
                available.add(item.get("name", "").lower())

        # Fehlende Zutaten ermitteln
        missing = []
        for ingredient in recipe_ingredients:
            ingredient_clean = ingredient.strip().lower()
            if ingredient_clean and ingredient_clean not in available:
                missing.append(ingredient.strip())

        if not missing:
            return {
                "success": True,
                "message": "Alle Zutaten sind bereits vorhanden!",
            }

        # Auf Einkaufsliste setzen via HA
        added = []
        if self.ha:
            for item in missing:
                success = await self.ha.call_service(
                    "shopping_list", "add_item", {"name": item}
                )
                if success:
                    added.append(item)

        if added:
            return {
                "success": True,
                "message": f"{len(added)} fehlende Zutat(en) auf die Einkaufsliste gesetzt: "
                + ", ".join(added),
            }

        return {
            "success": False,
            "message": "Konnte Zutaten nicht zur Einkaufsliste hinzufuegen.",
        }

    async def get_current_plan(self) -> dict:
        """Gibt den aktuellen Wochenplan zurueck."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        now = datetime.now(timezone.utc)
        week_key = now.strftime("%Y-W%V")

        data = await self.redis.hgetall(f"mha:meals:plan:{week_key}")
        if not data:
            return {
                "success": True,
                "message": "Kein Wochenplan fuer diese Woche vorhanden. "
                "Soll ich einen erstellen?",
            }

        decoded = _decode_hash(data)
        return {
            "success": True,
            "message": decoded.get("content", "Plan nicht lesbar."),
        }

    def get_context_hints(self) -> list[str]:
        """Kontext-Hints fuer Context Builder."""
        return [
            "MealPlanner aktiv: Essensplanung, Wochenplaene, Mahlzeiten-Historie, "
            "Zutatenpruefung gegen Inventar"
        ]

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------

    def _get_model(self, tier: str) -> str:
        """Holt das konfigurierte Modell fuer eine Tier-Stufe."""
        if self.model_router:
            return getattr(
                self.model_router,
                f"model_{tier}",
                self.model_router.model_smart,
            )
        from .config import settings

        tier_map = {
            "fast": settings.model_fast,
            "smart": settings.model_smart,
            "deep": settings.model_deep,
        }
        return tier_map.get(tier, settings.model_smart)

    async def _get_dietary_info(self) -> str:
        """Laedt Ernaehrungsinfos aus Semantic Memory."""
        if not self.semantic_memory:
            return ""

        try:
            # Gesundheitsfakten (Allergien, Unvertraeglichkeiten)
            health_facts = await self.semantic_memory.query_facts(
                category="health", limit=10
            )
            # Vorlieben
            pref_facts = await self.semantic_memory.query_facts(
                category="preference", limit=10
            )

            info_parts = []
            for fact in health_facts or []:
                content = fact.get("content", "")
                if content:
                    info_parts.append(f"Gesundheit: {content}")

            for fact in pref_facts or []:
                content = fact.get("content", "")
                if content and any(
                    kw in content.lower()
                    for kw in [
                        "essen",
                        "kochen",
                        "gericht",
                        "mag",
                        "liebling",
                        "allergi",
                    ]
                ):
                    info_parts.append(f"Vorliebe: {content}")

            return "\n".join(info_parts) if info_parts else ""
        except Exception as e:
            logger.debug("Dietary info Fehler: %s", e)
            return ""

    async def _get_recent_meals(self, days: int) -> list[str]:
        """Laedt letzte Mahlzeiten als Strings."""
        if not self.redis:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        meal_ids = await self.redis.zrangebyscore(
            "mha:meals:history",
            cutoff.timestamp(),
            "+inf",
        )

        if not meal_ids:
            return []

        meals = []
        pipe = self.redis.pipeline()
        for mid in meal_ids:
            mid_str = mid if isinstance(mid, str) else mid.decode()
            pipe.hget(f"mha:meals:entry:{mid_str}", "meal")
        results = await pipe.execute()

        for r in results:
            if r:
                meal_str = r if isinstance(r, str) else r.decode()
                meals.append(meal_str)

        return meals

    async def _get_inventory_items(self) -> list[str]:
        """Laedt Inventar-Artikel als Namen."""
        if not self.inventory:
            return []

        try:
            result = await self.inventory.list_items()
            return [
                item.get("name", "")
                for item in result.get("items", [])
                if item.get("name")
            ]
        except Exception:
            return []

    def _build_suggestion_prompt(
        self,
        items: list[str],
        priority_items: list[str],
        dietary_info: str,
        portions: int,
    ) -> str:
        """Baut den LLM-Prompt fuer Essensvorschlaege."""
        prompt = (
            f"Du bist ein Kochberater. Schlage 3 einfache Gerichte vor, "
            f"die man mit folgenden Zutaten kochen kann ({portions} Portionen).\n\n"
            f"Vorhandene Zutaten: {', '.join(items)}\n"
        )
        if priority_items:
            prompt += (
                f"\nPRIORITAET - Diese Zutaten bald verbrauchen: "
                f"{', '.join(priority_items)}\n"
            )
        if dietary_info:
            prompt += f"\nErnaehrungshinweise:\n{dietary_info}\n"

        prompt += (
            "\nFormat: Nummerierte Liste mit Gerichtname und kurzer Zubereitungsinfo. "
            "Antworte auf Deutsch, kurz und praktisch."
        )
        return prompt

    def _build_plan_prompt(
        self,
        dietary_info: str,
        recent_meals: list[str],
        inventory: list[str],
        preferences: str,
        portions: int,
    ) -> str:
        """Baut den LLM-Prompt fuer den Wochenplan."""
        prompt = (
            f"Erstelle einen Wochenplan fuer Abendessen (Montag bis Sonntag, "
            f"{portions} Portionen).\n"
        )

        if dietary_info:
            prompt += f"\nErnaehrungshinweise:\n{dietary_info}\n"

        if recent_meals:
            prompt += (
                f"\nLetzte Gerichte (nicht wiederholen): "
                f"{', '.join(recent_meals[-10:])}\n"
            )

        if inventory:
            prompt += (
                f"\nVorhandene Zutaten (bevorzugt verwenden): "
                f"{', '.join(inventory[:20])}\n"
            )

        if preferences:
            prompt += f"\nBesondere Wuensche: {preferences}\n"

        prompt += (
            "\nFormat:\n"
            "Montag: Gericht - kurze Beschreibung\n"
            "Dienstag: ...\n"
            "...\n\n"
            "Am Ende: Liste der einzukaufenden Zutaten.\n"
            "Antworte auf Deutsch, praktisch und abwechslungsreich."
        )
        return prompt

    async def shutdown(self):
        """Cleanup."""
        pass

    async def stop(self):
        """Alias fuer shutdown (Brain-Kompatibilitaet)."""
        await self.shutdown()


def _decode_hash(data: dict) -> dict:
    """Dekodiert Redis-Hash bytes zu strings."""
    decoded = {}
    for k, v in data.items():
        key = k if isinstance(k, str) else k.decode()
        val = v if isinstance(v, str) else v.decode()
        decoded[key] = val
    return decoded
