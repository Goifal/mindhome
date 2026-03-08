"""
Learning Transfer - Uebertraegt Praeferenzen zwischen aehnlichen Kontexten.

Quick Win: Wenn der User warmes Licht in der Kueche mag,
wird das auch fuer das Esszimmer vorgeschlagen.

Domaenen:
- Licht: Helligkeit, Farbtemperatur zwischen Raeumen uebertragen
- Klima: Temperatur-Praeferenzen zwischen aehnlichen Raeumen
- Medien: Lautstaerke-Praeferenzen zwischen Geraeten

Konfigurierbar in der Jarvis Assistant UI.
"""

import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

REDIS_KEY_PREFERENCES = "mha:learning_transfer:preferences"
REDIS_KEY_TRANSFERS = "mha:learning_transfer:transfers"

# Aehnliche Raeume (Default-Gruppen)
DEFAULT_ROOM_GROUPS = {
    "wohnbereich": ["wohnzimmer", "esszimmer", "kueche"],
    "schlafbereich": ["schlafzimmer", "gaestezimmer", "kinderzimmer"],
    "nassbereich": ["bad", "badezimmer", "gaeste_wc", "waschkueche"],
    "arbeitsbereich": ["buero", "arbeitszimmer", "homeoffice"],
    "aussen": ["terrasse", "balkon", "garten", "garage"],
}

# Uebertragbare Praeferenz-Typen
TRANSFERABLE_DOMAINS = {
    "light": {
        "attributes": ["brightness", "color_temp", "color_mode"],
        "description": "Licht-Praeferenzen (Helligkeit, Farbtemperatur)",
    },
    "climate": {
        "attributes": ["temperature", "hvac_mode"],
        "description": "Klima-Praeferenzen (Temperatur, Modus)",
    },
    "media": {
        "attributes": ["volume_level", "source"],
        "description": "Medien-Präferenzen (Lautstärke)",
    },
}


class LearningTransfer:
    """Uebertraegt gelernte Praeferenzen auf aehnliche Kontexte."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None

        cfg = yaml_config.get("learning_transfer", {})
        self.enabled = cfg.get("enabled", True)
        self.auto_suggest = cfg.get("auto_suggest", True)
        self.min_observations = cfg.get("min_observations", 3)
        self.transfer_confidence = cfg.get("transfer_confidence", 0.7)
        self.domains_enabled = cfg.get("domains", ["light", "climate", "media"])

        # Raum-Gruppen: konfigurierbar oder Default
        self._room_groups = cfg.get("room_groups") or dict(DEFAULT_ROOM_GROUPS)

        # Gemerkte Praeferenzen pro Raum und Domaene
        # Format: {"{room}:{domain}": [{attribute: value, count: N, last_seen: ts}]}
        self._preferences: dict[str, list[dict]] = {}
        self._pending_transfers: list[dict] = []

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_preferences()
        logger.info("LearningTransfer initialisiert (enabled: %s, domains: %s)",
                     self.enabled, self.domains_enabled)

    async def _load_preferences(self):
        """Laedt gespeicherte Praeferenzen aus Redis."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(REDIS_KEY_PREFERENCES)
            if raw:
                self._preferences = json.loads(raw)
        except Exception as e:
            logger.debug("Preferences laden fehlgeschlagen: %s", e)

    async def _save_preferences(self):
        """Speichert Praeferenzen in Redis."""
        if not self.redis:
            return
        try:
            await self.redis.set(
                REDIS_KEY_PREFERENCES,
                json.dumps(self._preferences, ensure_ascii=False),
                ex=86400 * 90,  # 90 Tage
            )
        except Exception as e:
            logger.debug("Preferences speichern fehlgeschlagen: %s", e)

    async def observe_action(
        self,
        room: str,
        domain: str,
        attributes: dict,
        person: str = "",
    ):
        """Beobachtet eine manuelle Aktion und merkt sich die Praeferenz.

        Args:
            room: Raum (z.B. "wohnzimmer")
            domain: Domaene (z.B. "light", "climate")
            attributes: Gesetzte Werte (z.B. {"brightness": 180, "color_temp": 400})
            person: Wer die Aktion ausgefuehrt hat
        """
        if not self.enabled or domain not in self.domains_enabled:
            return

        key = f"{room.lower()}:{domain}"
        transferable = TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
        filtered = {k: v for k, v in attributes.items() if k in transferable and v is not None}

        if not filtered:
            return

        if key not in self._preferences:
            self._preferences[key] = []

        # Existierende Praeferenz aktualisieren oder neue anlegen
        prefs = self._preferences[key]
        updated = False
        for pref in prefs:
            # Gleiche Attribute? -> Count erhoehen
            if all(pref.get(k) == v for k, v in filtered.items()):
                pref["count"] = pref.get("count", 1) + 1
                pref["last_seen"] = time.time()
                pref["person"] = person
                updated = True
                break

        if not updated:
            prefs.append({
                **filtered,
                "count": 1,
                "last_seen": time.time(),
                "person": person,
            })

        # Max 20 Praeferenzen pro Raum+Domaene
        self._preferences[key] = sorted(prefs, key=lambda p: p.get("count", 0), reverse=True)[:20]

        await self._save_preferences()

        # Transfer-Vorschlaege generieren
        if self.auto_suggest:
            await self._check_transfers(room, domain, filtered)

    async def _check_transfers(self, source_room: str, domain: str, attributes: dict):
        """Prueft ob Praeferenzen auf aehnliche Raeume uebertragen werden koennen."""
        source_key = f"{source_room.lower()}:{domain}"
        prefs = self._preferences.get(source_key, [])

        # Nur uebertragen wenn genug Beobachtungen
        dominant_pref = prefs[0] if prefs else None
        if not dominant_pref or dominant_pref.get("count", 0) < self.min_observations:
            return

        # Aehnliche Raeume finden
        similar_rooms = self._find_similar_rooms(source_room)
        if not similar_rooms:
            return

        for target_room in similar_rooms:
            target_key = f"{target_room}:{domain}"
            target_prefs = self._preferences.get(target_key, [])

            # Nur vorschlagen wenn der Zielraum noch keine starke Praeferenz hat
            if target_prefs and target_prefs[0].get("count", 0) >= self.min_observations:
                continue

            transferable_attrs = {
                k: v for k, v in dominant_pref.items()
                if k in TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
            }

            if transferable_attrs:
                transfer = {
                    "source_room": source_room,
                    "target_room": target_room,
                    "domain": domain,
                    "attributes": transferable_attrs,
                    "confidence": self.transfer_confidence,
                    "source_count": dominant_pref.get("count", 0),
                    "timestamp": time.time(),
                }

                # Duplikat-Check
                if not any(
                    t["source_room"] == source_room
                    and t["target_room"] == target_room
                    and t["domain"] == domain
                    for t in self._pending_transfers
                ):
                    self._pending_transfers.append(transfer)
                    logger.info(
                        "Transfer-Vorschlag: %s -> %s (%s: %s)",
                        source_room, target_room, domain, transferable_attrs,
                    )

    def _find_similar_rooms(self, room: str) -> list[str]:
        """Findet Raeume in der gleichen Gruppe."""
        room_lower = room.lower()
        for group_name, rooms in self._room_groups.items():
            rooms_lower = [r.lower() for r in rooms]
            if room_lower in rooms_lower:
                return [r for r in rooms_lower if r != room_lower]
        return []

    def get_pending_transfers(self) -> list[dict]:
        """Gibt ausstehende Transfer-Vorschlaege zurueck."""
        return self._pending_transfers

    def clear_pending_transfers(self):
        """Loescht alle ausstehenden Vorschlaege."""
        self._pending_transfers.clear()

    def get_transfer_suggestion(self, room: str, domain: str) -> Optional[dict]:
        """Gibt einen Transfer-Vorschlag fuer einen bestimmten Raum zurueck.

        Args:
            room: Zielraum
            domain: Domaene

        Returns:
            Transfer-Dict oder None
        """
        room_lower = room.lower()
        for t in self._pending_transfers:
            if t["target_room"] == room_lower and t["domain"] == domain:
                return t
        return None

    def get_context_hint(self, room: str = "") -> str:
        """Gibt Kontext-Hinweis fuer den LLM-Prompt zurueck."""
        if not self.enabled or not self._pending_transfers:
            return ""

        hints = []
        for t in self._pending_transfers[:2]:
            if not room or t["target_room"] == room.lower():
                attrs = ", ".join(f"{k}={v}" for k, v in t["attributes"].items())
                hints.append(
                    f"Praeferenz-Transfer moeglich: {t['source_room']} -> {t['target_room']} "
                    f"({t['domain']}: {attrs})"
                )

        return " ".join(hints)

    def get_preferences_summary(self) -> dict:
        """Gibt eine Zusammenfassung aller gelernten Praeferenzen zurueck."""
        summary = {}
        for key, prefs in self._preferences.items():
            room, domain = key.split(":", 1)
            if prefs:
                top = prefs[0]
                summary[key] = {
                    "room": room,
                    "domain": domain,
                    "top_preference": {
                        k: v for k, v in top.items()
                        if k not in ("count", "last_seen", "person")
                    },
                    "observations": top.get("count", 0),
                }
        return summary
