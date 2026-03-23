"""
Family Manager - Familien-Profile und personalisierte Erfahrung.

Verwaltet strukturierte Familien-Profile die ueber die einfache
Speaker-Recognition und Person-Preferences hinausgehen.

Features:
- Strukturierte Familien-Beziehungen (Partner, Kind, Eltern, etc.)
- Personalisiertes Morgen-Briefing pro Person
- Altersgerechte Kommunikation (Kind vs. Erwachsener)
- Familien-Gruppennachrichten
- Persoenliche Interessen und Vorlieben
- Begruessung basierend auf Person und Tageszeit

Redis Keys:
- mha:family:member:{person}     - Profil-Daten (Hash)
- mha:family:members             - Set aller Familienmitglieder
- mha:family:groups:{group}      - Nachrichtengruppen (Set)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title

logger = logging.getLogger(__name__)

_cfg = yaml_config.get("family", {})

_RELATIONSHIP_TYPES = frozenset(
    {
        "partner",
        "spouse",
        "child",
        "parent",
        "sibling",
        "grandparent",
        "grandchild",
        "roommate",
        "friend",
        "other",
    }
)

_AGE_GROUPS = {
    "child": (0, 12),
    "teen": (13, 17),
    "adult": (18, 200),
}

_COMMUNICATION_STYLES = {
    "child": {
        "greeting_prefix": "Hey",
        "formality": "informal",
        "emoji_level": "high",
        "vocabulary": "simple",
    },
    "teen": {
        "greeting_prefix": "Hi",
        "formality": "casual",
        "emoji_level": "medium",
        "vocabulary": "normal",
    },
    "adult": {
        "greeting_prefix": "",  # Wird vom Persoenlichkeits-System bestimmt
        "formality": "butler",
        "emoji_level": "none",
        "vocabulary": "full",
    },
}


class FamilyManager:
    """Verwaltet Familien-Profile und personalisierte Interaktionen."""

    def __init__(self, ha_client):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None
        self._notify_callback = None

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client

        # Lade initiale Profile aus settings.yaml
        await self._load_profiles_from_config()
        logger.info("FamilyManager initialisiert")

    def set_notify_callback(self, callback):
        """Setzt Callback fuer Gruppen-Nachrichten."""
        self._notify_callback = callback

    # ------------------------------------------------------------------
    # Profil-Verwaltung
    # ------------------------------------------------------------------

    async def add_member(
        self,
        name: str,
        relationship: str = "other",
        birth_year: int = 0,
        interests: str = "",
        ha_person_entity: str = "",
        notification_target: str = "",
    ) -> dict:
        """Fuegt ein Familienmitglied hinzu oder aktualisiert es."""
        if not name:
            return {"success": False, "message": "Kein Name angegeben."}

        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        name_key = name.lower().strip()
        relationship = relationship.lower()
        if relationship not in _RELATIONSHIP_TYPES:
            relationship = "other"

        profile = {
            "name": name.strip(),
            "name_key": name_key,
            "relationship": relationship,
            "birth_year": str(birth_year) if birth_year else "",
            "interests": interests,
            "ha_person_entity": ha_person_entity or f"person.{name_key}",
            "notification_target": notification_target,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.redis.hset(f"mha:family:member:{name_key}", mapping=profile)
        await self.redis.sadd("mha:family:members", name_key)

        return {
            "success": True,
            "message": f"{name} als {relationship} zur Familie hinzugefuegt.",
        }

    async def update_member(self, name: str, **kwargs) -> dict:
        """Aktualisiert einzelne Felder eines Familienmitglieds."""
        if not name or not self.redis:
            return {"success": False, "message": "Name oder Redis fehlt."}

        name_key = name.lower().strip()
        exists = await self.redis.exists(f"mha:family:member:{name_key}")
        if not exists:
            return {
                "success": False,
                "message": f"{name} ist kein bekanntes Familienmitglied.",
            }

        updates = {}
        for key, value in kwargs.items():
            if value is not None and key in {
                "relationship",
                "birth_year",
                "interests",
                "ha_person_entity",
                "notification_target",
            }:
                updates[key] = str(value)

        if updates:
            await self.redis.hset(f"mha:family:member:{name_key}", mapping=updates)

        return {"success": True, "message": f"Profil von {name} aktualisiert."}

    async def get_member(self, name: str) -> Optional[dict]:
        """Gibt das Profil eines Familienmitglieds zurueck."""
        if not self.redis:
            return None

        name_key = name.lower().strip()
        data = await self.redis.hgetall(f"mha:family:member:{name_key}")
        if not data:
            return None

        return _decode_redis_hash(data)

    async def get_all_members(self) -> list[dict]:
        """Gibt alle Familien-Profile zurueck."""
        if not self.redis:
            return []

        members = await self.redis.smembers("mha:family:members")
        if not members:
            return []

        results = []
        pipe = self.redis.pipeline()
        names = []
        for m in members:
            name = m if isinstance(m, str) else m.decode()
            names.append(name)
            pipe.hgetall(f"mha:family:member:{name}")
        all_data = await pipe.execute()

        for name, data in zip(names, all_data):
            if data:
                results.append(_decode_redis_hash(data))

        return sorted(results, key=lambda m: m.get("name", ""))

    async def remove_member(self, name: str) -> dict:
        """Entfernt ein Familienmitglied."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        name_key = name.lower().strip()
        existed = await self.redis.delete(f"mha:family:member:{name_key}")
        await self.redis.srem("mha:family:members", name_key)

        if existed:
            return {"success": True, "message": f"{name} aus Familie entfernt."}
        return {"success": False, "message": f"{name} nicht gefunden."}

    # ------------------------------------------------------------------
    # Personalisierung
    # ------------------------------------------------------------------

    async def get_age_group(self, name: str) -> str:
        """Bestimmt die Altersgruppe eines Familienmitglieds."""
        profile = await self.get_member(name)
        if not profile or not profile.get("birth_year"):
            return "adult"

        try:
            birth_year = int(profile["birth_year"])
            age = datetime.now(timezone.utc).year - birth_year

            for group, (min_age, max_age) in _AGE_GROUPS.items():
                if min_age <= age <= max_age:
                    return group
            return "adult"
        except (ValueError, TypeError):
            return "adult"

    async def get_communication_style(self, name: str) -> dict:
        """Gibt den Kommunikationsstil fuer eine Person zurueck."""
        age_group = await self.get_age_group(name)
        style = _COMMUNICATION_STYLES.get(age_group, _COMMUNICATION_STYLES["adult"])
        return dict(style)  # Kopie zurueckgeben

    async def get_personalized_greeting(self, name: str) -> str:
        """Erstellt eine personalisierte Begruessung."""
        profile = await self.get_member(name)
        if not profile:
            # Fallback: Nutze get_person_title aus config
            title = get_person_title(name)
            return f"Hallo {title}"

        age_group = await self.get_age_group(name)
        display_name = profile.get("name", name).title()
        relationship = profile.get("relationship", "")

        now = datetime.now(timezone.utc)
        hour = now.hour

        if age_group == "child":
            if hour < 12:
                return f"Guten Morgen, {display_name}!"
            elif hour < 18:
                return f"Hey {display_name}!"
            else:
                return f"Guten Abend, {display_name}!"
        else:
            # Standard Butler-Stil - wird vom Persoenlichkeits-System uebersteuert
            title = get_person_title(name)
            return f"{title}"

    async def get_context_for_person(self, name: str) -> dict:
        """Liefert Kontext-Informationen fuer personalisierte LLM-Antworten."""
        profile = await self.get_member(name)
        if not profile:
            return {}

        age_group = await self.get_age_group(name)
        style = await self.get_communication_style(name)

        context = {
            "person_name": profile.get("name", name),
            "relationship": profile.get("relationship", ""),
            "age_group": age_group,
            "interests": profile.get("interests", ""),
            "communication_style": style,
        }

        return context

    # ------------------------------------------------------------------
    # Gruppen-Nachrichten
    # ------------------------------------------------------------------

    async def send_family_message(
        self,
        message: str,
        group: str = "all",
        exclude: Optional[list[str]] = None,
    ) -> dict:
        """Sendet eine Nachricht an die Familie oder eine Gruppe.

        Args:
            message: Die Nachricht
            group: 'all' oder Gruppenname
            exclude: Liste von Personen die ausgenommen werden sollen
        """
        if not self._notify_callback:
            return {
                "success": False,
                "message": "Benachrichtigungs-System nicht verfuegbar.",
            }

        exclude_set = {n.lower() for n in (exclude or [])}

        if group == "all":
            members = await self.get_all_members()
        else:
            members = await self._get_group_members(group)

        if not members:
            return {"success": False, "message": "Keine Empfaenger gefunden."}

        sent_count = 0
        for member in members:
            name_key = member.get("name_key", member.get("name", "").lower())
            if name_key in exclude_set:
                continue

            try:
                await self._notify_callback(
                    message=message,
                    person=member.get("name", name_key),
                    priority="medium",
                )
                sent_count += 1
            except Exception as e:
                logger.warning(
                    "Fehler beim Senden an %s: %s",
                    member.get("name", "?"),
                    e,
                )

        return {
            "success": sent_count > 0,
            "message": f"Nachricht an {sent_count} Familienmitglied(er) gesendet.",
        }

    async def create_group(self, group_name: str, members: list[str]) -> dict:
        """Erstellt eine Nachrichtengruppe."""
        if not self.redis or not group_name or not members:
            return {
                "success": False,
                "message": "Gruppenname und Mitglieder erforderlich.",
            }

        key = f"mha:family:groups:{group_name.lower()}"
        for m in members:
            await self.redis.sadd(key, m.lower().strip())

        return {
            "success": True,
            "message": f"Gruppe '{group_name}' mit {len(members)} Mitgliedern erstellt.",
        }

    async def _get_group_members(self, group: str) -> list[dict]:
        """Laedt die Mitglieder einer Gruppe."""
        if not self.redis:
            return []

        key = f"mha:family:groups:{group.lower()}"
        member_names = await self.redis.smembers(key)
        if not member_names:
            return []

        results = []
        for name in member_names:
            name_str = name if isinstance(name, str) else name.decode()
            profile = await self.get_member(name_str)
            if profile:
                results.append(profile)

        return results

    # ------------------------------------------------------------------
    # Briefing-Integration
    # ------------------------------------------------------------------

    async def get_personalized_briefing_context(self, person: str) -> dict:
        """Liefert personalisierten Kontext fuers Morgen-Briefing."""
        profile = await self.get_member(person)
        if not profile:
            return {"person": person, "style": "default"}

        age_group = await self.get_age_group(person)
        interests = profile.get("interests", "")

        context = {
            "person": profile.get("name", person),
            "age_group": age_group,
            "interests": interests,
            "relationship": profile.get("relationship", ""),
        }

        if age_group == "child":
            context["style"] = "kind"  # Einfache Sprache, freundlich
            context["briefing_hint"] = (
                "Halte das Briefing kurz, einfach und freundlich. "
                "Erwaehne Schule/Freizeit statt Arbeit."
            )
        elif age_group == "teen":
            context["style"] = "jugendlich"
            context["briefing_hint"] = (
                "Lockerer Ton, nicht zu foermlich. Relevante Infos fuer Jugendliche."
            )
        else:
            context["style"] = "butler"
            context["briefing_hint"] = ""

        return context

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    async def _load_profiles_from_config(self):
        """Laedt initiale Profile aus settings.yaml 'persons' Sektion."""
        if not self.redis:
            return

        persons = yaml_config.get("persons", {})
        for name, config in persons.items():
            name_key = name.lower().strip()

            # Nur erstellen wenn noch nicht vorhanden
            exists = await self.redis.exists(f"mha:family:member:{name_key}")
            if exists:
                continue

            profile = {
                "name": name.strip(),
                "name_key": name_key,
                "relationship": config.get("relationship", "other"),
                "birth_year": str(config.get("birth_year", "")),
                "interests": config.get("interests", ""),
                "ha_person_entity": config.get("ha_entity", f"person.{name_key}"),
                "notification_target": config.get("notification_target", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            await self.redis.hset(f"mha:family:member:{name_key}", mapping=profile)
            await self.redis.sadd("mha:family:members", name_key)
            logger.info("Familienprofil aus Config geladen: %s", name)

    def get_context_hints(self) -> list[str]:
        """Gibt Kontext-Hints fuer den Context Builder zurueck."""
        return [
            "FamilyManager aktiv: Familien-Profile, Gruppen-Nachrichten, "
            "personalisierte Kommunikation verfuegbar"
        ]

    async def shutdown(self):
        """Cleanup."""
        pass


def _decode_redis_hash(data: dict) -> dict:
    """Dekodiert Redis-Hash bytes zu strings."""
    decoded = {}
    for k, v in data.items():
        key = k if isinstance(k, str) else k.decode()
        val = v if isinstance(v, str) else v.decode()
        decoded[key] = val
    return decoded
