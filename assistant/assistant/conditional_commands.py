"""
Conditional Commands - Temporaere Wenn-Dann-Befehle.

Features:
- "Wenn es regnet, Rolladen runter" -> temporaerer Event-Listener
- "Falls Papa anruft, sag ihm ich bin gleich da"
- Redis-basiert mit TTL (default 24h)
- Einmalig (one_shot) oder dauerhaft
- Unterschied zu self_automation.py: temporaer, kein YAML in HA

Wird von proactive.py bei jedem state_changed Event geprueft.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis Keys
KEY_PREFIX = "mha:conditional:"
KEY_INDEX = "mha:conditional:index"


class ConditionalCommands:
    """Verwaltet temporaere bedingte Befehle."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._action_callback = None

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis:
            count = await self.redis.scard(KEY_INDEX)
            logger.info("ConditionalCommands initialisiert (%s aktive Conditionals)", count or 0)

    def set_action_callback(self, callback):
        """Setzt den Callback fuer Aktions-Ausfuehrung."""
        self._action_callback = callback

    async def create_conditional(
        self,
        trigger_type: str,
        trigger_value: str,
        action_function: str,
        action_args: dict,
        label: str = "",
        ttl_hours: int = 24,
        one_shot: bool = True,
        person: str = "",
    ) -> dict:
        """Erstellt einen neuen bedingten Befehl.

        Args:
            trigger_type: Art des Triggers
                - "state_change": Entity wechselt in bestimmten State
                - "state_attribute": Entity-Attribut erreicht Wert
                - "person_arrives": Person kommt nach Hause
                - "person_leaves": Person verlaesst das Haus
            trigger_value: Wert des Triggers (z.B. "sensor.regen:on", "person.papa:home")
            action_function: Auszufuehrende Funktion (z.B. "set_cover")
            action_args: Argumente fuer die Funktion
            label: Beschreibung des Conditionals
            ttl_hours: Gueltigkeitsdauer in Stunden (1-168, default 24)
            one_shot: Nur einmal ausfuehren, dann loeschen
            person: Person die den Befehl erstellt hat

        Returns:
            Ergebnis-Dict
        """
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        ttl_hours = max(1, min(168, ttl_hours))  # 1h bis 7 Tage
        cond_id = str(uuid.uuid4())[:8]

        if not label:
            label = f"Wenn {trigger_value} dann {action_function}"

        conditional = {
            "id": cond_id,
            "trigger_type": trigger_type,
            "trigger_value": trigger_value,
            "action_function": action_function,
            "action_args": action_args,
            "label": label,
            "one_shot": one_shot,
            "person": person,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "executed_count": 0,
        }

        key = f"{KEY_PREFIX}{cond_id}"
        ttl_seconds = ttl_hours * 3600

        await self.redis.setex(key, ttl_seconds, json.dumps(conditional))
        await self.redis.sadd(KEY_INDEX, cond_id)

        time_str = f"{ttl_hours} Stunde{'n' if ttl_hours > 1 else ''}"
        shot_str = "einmalig" if one_shot else "dauerhaft"

        return {
            "success": True,
            "message": f"Bedingung '{label}' erstellt ({shot_str}, gueltig fuer {time_str}).",
            "conditional_id": cond_id,
        }

    async def check_event(self, entity_id: str, new_state: str, old_state: str = "",
                          attributes: dict = None) -> list[dict]:
        """Prueft ob ein Event eine Bedingung ausloest.

        Wird von proactive.py bei jedem state_changed aufgerufen.

        Returns:
            Liste der ausgefuehrten Aktionen.
        """
        if not self.redis:
            return []

        executed = []
        cond_ids = await self.redis.smembers(KEY_INDEX)
        if not cond_ids:
            return []

        for cond_id in cond_ids:
            if isinstance(cond_id, bytes):
                cond_id = cond_id.decode()

            key = f"{KEY_PREFIX}{cond_id}"
            raw = await self.redis.get(key)
            if not raw:
                await self.redis.srem(KEY_INDEX, cond_id)
                continue

            if isinstance(raw, bytes):
                raw = raw.decode()
            cond = json.loads(raw)

            match = self._check_trigger_match(
                cond, entity_id, new_state, old_state, attributes or {}
            )

            if match:
                logger.info("Conditional Match: '%s' (ID: %s)", cond["label"], cond_id)

                # Aktion ausfuehren
                if self._action_callback:
                    try:
                        result = await self._action_callback(
                            cond["action_function"], cond["action_args"]
                        )
                        executed.append({
                            "conditional_id": cond_id,
                            "label": cond["label"],
                            "action": cond["action_function"],
                            "result": result,
                        })
                    except Exception as e:
                        logger.error("Conditional Action fehlgeschlagen: %s", e)

                # Zaehler erhoehen
                cond["executed_count"] = cond.get("executed_count", 0) + 1

                # one_shot: nach Ausfuehrung loeschen
                if cond.get("one_shot", True):
                    await self.redis.delete(key)
                    await self.redis.srem(KEY_INDEX, cond_id)
                    logger.info("One-Shot Conditional entfernt: %s", cond_id)
                else:
                    # Zaehler aktualisieren, TTL beibehalten
                    ttl = await self.redis.ttl(key)
                    if ttl > 0:
                        await self.redis.setex(key, ttl, json.dumps(cond))

        return executed

    def _check_trigger_match(self, cond: dict, entity_id: str, new_state: str,
                             old_state: str, attributes: dict) -> bool:
        """Prueft ob ein Trigger matcht."""
        trigger_type = cond.get("trigger_type", "")
        trigger_value = cond.get("trigger_value", "")

        if trigger_type == "state_change":
            # Format: "entity_id:target_state" oder nur "entity_id" (jeder Wechsel)
            parts = trigger_value.split(":", 1)
            target_entity = parts[0]
            target_state = parts[1] if len(parts) > 1 else None

            if entity_id != target_entity and not entity_id.endswith(target_entity):
                return False
            if target_state and new_state != target_state:
                return False
            if not target_state and new_state == old_state:
                return False
            return True

        elif trigger_type == "person_arrives":
            # person.name wechselt zu "home"
            if not entity_id.startswith("person."):
                return False
            person_name = trigger_value.lower()
            entity_name = entity_id.split(".", 1)[1].lower()
            if person_name not in entity_name:
                return False
            return new_state == "home" and old_state != "home"

        elif trigger_type == "person_leaves":
            if not entity_id.startswith("person."):
                return False
            person_name = trigger_value.lower()
            entity_name = entity_id.split(".", 1)[1].lower()
            if person_name not in entity_name:
                return False
            return old_state == "home" and new_state != "home"

        elif trigger_type == "state_attribute":
            # Format: "entity_id:attribute:operator:value"
            parts = trigger_value.split(":", 3)
            if len(parts) < 4:
                return False
            target_entity, attr_name, operator, target_val = parts
            if entity_id != target_entity:
                return False
            attr_val = attributes.get(attr_name)
            if attr_val is None:
                return False
            try:
                attr_num = float(attr_val)
                target_num = float(target_val)
                if operator == ">" and attr_num > target_num:
                    return True
                if operator == "<" and attr_num < target_num:
                    return True
                if operator == "=" and attr_num == target_num:
                    return True
            except (ValueError, TypeError):
                if operator == "=" and str(attr_val) == target_val:
                    return True

        return False

    async def list_conditionals(self) -> dict:
        """Listet alle aktiven Conditionals auf."""
        if not self.redis:
            return {"success": True, "message": "Keine bedingten Befehle aktiv."}

        cond_ids = await self.redis.smembers(KEY_INDEX)
        if not cond_ids:
            return {"success": True, "message": "Keine bedingten Befehle aktiv."}

        lines = ["Aktive bedingte Befehle:"]
        for cond_id in cond_ids:
            if isinstance(cond_id, bytes):
                cond_id = cond_id.decode()

            key = f"{KEY_PREFIX}{cond_id}"
            raw = await self.redis.get(key)
            if not raw:
                await self.redis.srem(KEY_INDEX, cond_id)
                continue

            if isinstance(raw, bytes):
                raw = raw.decode()
            cond = json.loads(raw)

            ttl = await self.redis.ttl(key)
            ttl_hours = max(0, ttl // 3600) if ttl > 0 else 0
            shot = "einmalig" if cond.get("one_shot") else "dauerhaft"
            lines.append(f"  - {cond['label']} ({shot}, noch {ttl_hours}h gueltig)")

        return {"success": True, "message": "\n".join(lines)}

    async def delete_conditional(self, cond_id: str) -> dict:
        """Loescht einen bedingten Befehl."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        key = f"{KEY_PREFIX}{cond_id}"
        existed = await self.redis.delete(key)
        await self.redis.srem(KEY_INDEX, cond_id)

        if existed:
            return {"success": True, "message": f"Bedingung {cond_id} geloescht."}
        return {"success": False, "message": f"Bedingung {cond_id} nicht gefunden."}
