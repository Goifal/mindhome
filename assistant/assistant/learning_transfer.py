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

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

REDIS_KEY_PREFERENCES = "mha:learning_transfer:preferences"
REDIS_KEY_TRANSFERS = "mha:learning_transfer:transfers"
REDIS_KEY_NOTIFY_COUNT = "mha:learning_transfer:notify_count"

# Max notifications per day to avoid spamming
MAX_TRANSFER_NOTIFICATIONS_PER_DAY = 2

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

        self.notify_user = cfg.get("notify_user", True)

        # Raum-Gruppen: konfigurierbar oder Default
        self._room_groups = cfg.get("room_groups") or dict(DEFAULT_ROOM_GROUPS)

        # Gemerkte Praeferenzen pro Raum und Domaene
        # Format: {"{room}:{domain}": [{attribute: value, count: N, last_seen: ts}]}
        self._preferences: dict[str, list[dict]] = {}
        self._pending_transfers: deque[dict] = deque(maxlen=100)
        self._lock = asyncio.Lock()

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_preferences()
        logger.info(
            "LearningTransfer initialisiert (enabled: %s, domains: %s)",
            self.enabled,
            self.domains_enabled,
        )

    async def _load_preferences(self):
        """Laedt gespeicherte Praeferenzen aus Redis."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(REDIS_KEY_PREFERENCES)
            if raw:
                self._preferences = json.loads(raw)
        except Exception as e:
            logger.warning("Preferences laden fehlgeschlagen: %s", e)

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
            logger.warning("Preferences speichern fehlgeschlagen: %s", e)

    async def observe_action(
        self,
        room: str,
        domain: str,
        attributes: dict,
        person: str = "",
        reason: str = "",
    ):
        """Beobachtet eine manuelle Aktion und merkt sich die Praeferenz.

        Args:
            room: Raum (z.B. "wohnzimmer")
            domain: Domaene (z.B. "light", "climate")
            attributes: Gesetzte Werte (z.B. {"brightness": 180, "color_temp": 400})
            person: Wer die Aktion ausgefuehrt hat
            reason: Optionaler Grund fuer die Aktion (z.B. "task_lighting",
                "ambiance", "energy_saving"). Ermoeglicht intelligenteres
                Transfer-Learning: Werte werden nur in Raeume mit aehnlichem
                Nutzungszweck uebertragen.
        """
        if not self.enabled or domain not in self.domains_enabled:
            return

        key = f"{room.lower()}:{domain}"
        transferable = TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
        filtered = {
            k: v for k, v in attributes.items() if k in transferable and v is not None
        }

        if not filtered:
            return

        async with self._lock:
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
                _new_pref = {
                    **filtered,
                    "count": 1,
                    "last_seen": time.time(),
                    "person": person,
                }
                if reason:
                    _new_pref["reason"] = reason[:100]
                prefs.append(_new_pref)

            # Max 20 Praeferenzen pro Raum+Domaene
            self._preferences[key] = sorted(
                prefs, key=lambda p: p.get("count", 0), reverse=True
            )[:20]

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
            if (
                target_prefs
                and target_prefs[0].get("count", 0) >= self.min_observations
            ):
                continue

            transferable_attrs = {
                k: v
                for k, v in dominant_pref.items()
                if k in TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
            }

            if transferable_attrs:
                # Device-Dependency-Check: Transfer nur wenn Raeume kompatibel
                _skip_transfer = False
                try:
                    from .state_change_log import StateChangeLog
                    import assistant.main as main_module

                    if hasattr(main_module, "brain") and domain == "climate":
                        _states = await main_module.brain.ha.get_states() or []
                        # Pruefen ob Zielraum offene Fenster hat (Klima-Transfer sinnlos)
                        for s in _states:
                            _eid = s.get("entity_id", "")
                            if (
                                StateChangeLog._get_entity_role(_eid)
                                == "window_contact"
                                and s.get("state") == "on"
                                and StateChangeLog._get_entity_room(_eid)
                                == target_room.lower()
                            ):
                                _skip_transfer = True
                                logger.debug(
                                    "Transfer %s->%s (%s) uebersprungen: Fenster offen in Zielraum",
                                    source_room,
                                    target_room,
                                    domain,
                                )
                                break
                except Exception as e:
                    logger.debug(
                        "Fenster-Status Pruefung fuer Transfer fehlgeschlagen: %s", e
                    )
                if _skip_transfer:
                    continue

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
                async with self._lock:
                    if not any(
                        t["source_room"] == source_room
                        and t["target_room"] == target_room
                        and t["domain"] == domain
                        for t in self._pending_transfers
                    ):
                        self._pending_transfers.append(transfer)
                        logger.info(
                            "Transfer-Vorschlag: %s -> %s (%s: %s)",
                            source_room,
                            target_room,
                            domain,
                            transferable_attrs,
                        )
                        # Notify user about the transfer (rate-limited)
                        if self.notify_user:
                            await self._emit_transfer_notification(transfer)

    async def _can_notify_today(self) -> bool:
        """Prueft ob heute noch Transfer-Benachrichtigungen gesendet werden duerfen.

        Begrenzt auf MAX_TRANSFER_NOTIFICATIONS_PER_DAY pro Tag um Spam zu vermeiden.
        """
        if not self.redis:
            return False
        try:
            today_key = f"{REDIS_KEY_NOTIFY_COUNT}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            count_raw = await self.redis.get(today_key)
            count = int(count_raw) if count_raw else 0
            return count < MAX_TRANSFER_NOTIFICATIONS_PER_DAY
        except Exception as e:
            logger.warning("Transfer-Notify-Counter Pruefung fehlgeschlagen: %s", e)
            return False

    async def _increment_notify_count(self):
        """Erhoeht den taeglichen Benachrichtigungszaehler."""
        if not self.redis:
            return
        try:
            today_key = f"{REDIS_KEY_NOTIFY_COUNT}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            await self.redis.incr(today_key)
            await self.redis.expire(today_key, 86400 * 2)  # 2 Tage TTL
        except Exception as e:
            logger.warning("Transfer-Notify-Counter Inkrement fehlgeschlagen: %s", e)

    async def _emit_transfer_notification(self, transfer: dict):
        """Sendet eine proaktive Benachrichtigung ueber einen Transfer-Vorschlag.

        Nutzt das proaktive System (brain._proactive._notify) falls verfuegbar,
        ansonsten wird ein strukturierter Log-Eintrag erzeugt.

        Args:
            transfer: Transfer-Dict mit source_room, target_room, domain, attributes
        """
        if not await self._can_notify_today():
            logger.debug(
                "Transfer-Notification unterdrueckt (Tageslimit erreicht): %s -> %s",
                transfer["source_room"],
                transfer["target_room"],
            )
            return

        domain_desc = TRANSFERABLE_DOMAINS.get(transfer["domain"], {}).get(
            "description", transfer["domain"]
        )
        attrs_str = ", ".join(
            f"{k}={v}" for k, v in transfer.get("attributes", {}).items()
        )
        message = (
            f"Ich habe deine {domain_desc} Praeferenz vom {transfer['source_room'].capitalize()} "
            f"auch auf {transfer['target_room'].capitalize()} uebertragen ({attrs_str})."
        )

        notified = False
        try:
            import assistant.main as main_module

            brain = getattr(main_module, "brain", None)
            proactive = getattr(brain, "_proactive", None) if brain else None
            if proactive and hasattr(proactive, "_notify"):
                await proactive._notify(
                    "learning_transfer",
                    "low",
                    {"message": message, "transfer": transfer},
                )
                notified = True
        except Exception as e:
            logger.warning("Proaktive Transfer-Notification fehlgeschlagen: %s", e)

        if not notified:
            logger.info("Transfer-Notification (kein proaktives System): %s", message)

        await self._increment_notify_count()

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
        for t in list(self._pending_transfers)[:2]:
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
                        k: v
                        for k, v in top.items()
                        if k not in ("count", "last_seen", "person")
                    },
                    "observations": top.get("count", 0),
                }
        return summary

    # ------------------------------------------------------------------
    # Phase 6B: Erweiterte Transfer-Methoden
    # ------------------------------------------------------------------

    async def transfer_with_person_filter(
        self, source_room: str, target_room: str, person: str = ""
    ) -> dict:
        """Uebertraegt nur Praeferenzen die zur angegebenen Person passen.

        Args:
            source_room: Quellraum
            target_room: Zielraum
            person: Person deren Praeferenzen uebertragen werden sollen

        Returns:
            Dict mit transferred (list) und skipped (int) Feldern.
        """
        transferred = []
        skipped = 0

        for domain in self.domains_enabled:
            source_key = f"{source_room.lower()}:{domain}"
            prefs = self._preferences.get(source_key, [])

            for pref in prefs:
                pref_person = pref.get("person", "")
                if person and pref_person and pref_person.lower() != person.lower():
                    skipped += 1
                    continue
                if pref.get("count", 0) < self.min_observations:
                    continue

                transferable_attrs = {
                    k: v
                    for k, v in pref.items()
                    if k in TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
                }
                if transferable_attrs:
                    transferred.append(
                        {
                            "domain": domain,
                            "attributes": transferable_attrs,
                            "person": pref_person,
                        }
                    )

        return {"transferred": transferred, "skipped": skipped}

    async def transfer_with_temporal_filter(
        self, source_room: str, target_room: str, hour: int = -1
    ) -> dict:
        """Uebertraegt nur Praeferenzen die zur Tageszeit passen.

        Teilt den Tag in Bloecke: Morgen (5-11), Nachmittag (12-17), Abend (18-4).
        Nutzt die konfigurierte Timezone aus settings.yaml (Default: Europe/Berlin).

        Args:
            source_room: Quellraum
            target_room: Zielraum
            hour: Stunde (0-23), -1 fuer aktuelle Stunde (Lokalzeit)

        Returns:
            Dict mit transferred (list) und time_block (str) Feldern.
        """
        from datetime import datetime as _dt, timezone as _tz
        from zoneinfo import ZoneInfo

        tz_name = yaml_config.get("timezone", "Europe/Berlin")
        try:
            local_tz = ZoneInfo(tz_name)
        except Exception as e:
            logger.debug(
                "Zeitzone '%s' nicht verfuegbar, Fallback auf Europe/Berlin: %s",
                tz_name,
                e,
            )
            local_tz = ZoneInfo("Europe/Berlin")

        if hour < 0:
            hour = _dt.now(tz=local_tz).hour

        if 5 <= hour <= 11:
            time_block = "morning"
        elif 12 <= hour <= 17:
            time_block = "afternoon"
        else:
            time_block = "evening"

        transferred = []
        for domain in self.domains_enabled:
            source_key = f"{source_room.lower()}:{domain}"
            prefs = self._preferences.get(source_key, [])

            for pref in prefs:
                last_seen = pref.get("last_seen", 0)
                if last_seen <= 0:
                    continue
                pref_hour = _dt.fromtimestamp(last_seen, tz=local_tz).hour
                if 5 <= pref_hour <= 11:
                    pref_block = "morning"
                elif 12 <= pref_hour <= 17:
                    pref_block = "afternoon"
                else:
                    pref_block = "evening"

                if pref_block != time_block:
                    continue
                if pref.get("count", 0) < self.min_observations:
                    continue

                transferable_attrs = {
                    k: v
                    for k, v in pref.items()
                    if k in TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
                }
                if transferable_attrs:
                    transferred.append(
                        {"domain": domain, "attributes": transferable_attrs}
                    )

        return {"transferred": transferred, "time_block": time_block}

    async def suggest_transfers(self, room: str, domain: str) -> list:
        """Returns transfer suggestions for a given room and domain.

        Callable from brain.py to get actionable transfer suggestions.

        Args:
            room: Target room (e.g. "esszimmer")
            domain: Domain (e.g. "light", "climate")

        Returns:
            List of dicts with source_room, target_room, domain, attributes, confidence.
        """
        if not self.enabled:
            return []

        room_lower = room.lower()
        suggestions = []

        # Check pending transfers for this room/domain
        for t in list(self._pending_transfers):
            if t["target_room"] == room_lower and t["domain"] == domain:
                suggestions.append(t)

        if suggestions:
            return suggestions

        # No pending transfers — proactively check similar rooms
        similar_rooms = self._find_similar_rooms(room)
        for source_room in similar_rooms:
            source_key = f"{source_room}:{domain}"
            prefs = self._preferences.get(source_key, [])
            if not prefs:
                continue

            dominant = prefs[0]
            if dominant.get("count", 0) < self.min_observations:
                continue

            # Target room should not have strong preferences already
            target_key = f"{room_lower}:{domain}"
            target_prefs = self._preferences.get(target_key, [])
            if (
                target_prefs
                and target_prefs[0].get("count", 0) >= self.min_observations
            ):
                continue

            transferable_attrs = {
                k: v
                for k, v in dominant.items()
                if k in TRANSFERABLE_DOMAINS.get(domain, {}).get("attributes", [])
            }
            if not transferable_attrs:
                continue

            confidence = min(
                self.transfer_confidence,
                0.5 + dominant.get("count", 0) * 0.05,
            )
            suggestions.append(
                {
                    "source_room": source_room,
                    "target_room": room_lower,
                    "domain": domain,
                    "attributes": transferable_attrs,
                    "confidence": round(confidence, 2),
                    "source_count": dominant.get("count", 0),
                }
            )

        return suggestions

    async def learn_from_failure(
        self, room: str, domain: str, action: str, person: str = ""
    ) -> None:
        """Speichert inverse Regeln aus abgelehnten/fehlgeschlagenen Aktionen.

        Wenn eine Aktion abgelehnt wird, wird ein negativer Eintrag gespeichert,
        damit die Praeferenz kuenftig nicht mehr vorgeschlagen wird.

        Args:
            room: Raum
            domain: Domaene
            action: Die abgelehnte Aktion (z.B. "brightness=255")
            person: Person die abgelehnt hat
        """
        if not self.enabled:
            return

        key = f"{room.lower()}:{domain}:failures"
        async with self._lock:
            if key not in self._preferences:
                self._preferences[key] = []

            self._preferences[key].append(
                {
                    "action": action,
                    "person": person,
                    "timestamp": time.time(),
                    "count": 1,
                }
            )
            # Max 10 Failure-Eintraege pro Raum+Domaene
            self._preferences[key] = self._preferences[key][-10:]

            await self._save_preferences()

        logger.info(
            "Failure gelernt: %s in %s/%s (Person: %s)",
            action,
            room,
            domain,
            person or "unbekannt",
        )
