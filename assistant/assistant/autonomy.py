"""
Autonomy Manager - Bestimmt was der Assistent selbststaendig tun darf.
Level 1 (Assistent) bis Level 5 (Autopilot).

Phase 10: Person-basierte Vertrauensstufen.
- 0 (Gast): Nur Licht, Klima, Medien im eigenen Raum
- 1 (Mitbewohner): Alles ausser Sicherheit
- 2 (Owner): Voller Zugriff
"""

import logging

from .config import settings, yaml_config

logger = logging.getLogger(__name__)


# Welches Level fuer welche Aktion noetig ist
ACTION_PERMISSIONS = {
    # Level 1: Assistent - nur auf Befehle reagieren
    "respond_to_command": 1,
    "execute_function_call": 1,

    # Level 2: Butler - proaktive Infos
    "proactive_info": 2,
    "morning_briefing": 2,
    "arrival_greeting": 2,
    "security_alert": 1,  # Immer, auch bei Level 1

    # Level 3: Mitbewohner - kleine Aenderungen
    "adjust_temperature_small": 3,  # +/- 1 Grad
    "adjust_light_auto": 3,
    "pause_reminder": 3,

    # Level 4: Vertrauter - Routinen anpassen
    "modify_routine": 4,
    "suggest_scene": 4,
    "learn_preferences": 4,

    # Level 5: Autopilot - Automationen erstellen
    "create_automation": 5,
    "modify_schedule": 5,
}

# Phase 10: Trust-Level Namen
TRUST_LEVEL_NAMES = {
    0: "Gast",
    1: "Mitbewohner",
    2: "Owner",
}


class AutonomyManager:
    """Verwaltet das Autonomie-Level des Assistenten und Trust-Levels pro Person."""

    def __init__(self):
        self.level = settings.autonomy_level

        # Phase 10: Trust-Level Konfiguration laden
        trust_cfg = yaml_config.get("trust_levels", {})
        self._default_trust = trust_cfg.get("default", 0)
        self._person_trust: dict[str, int] = trust_cfg.get("persons", {}) or {}
        self._guest_actions = set(trust_cfg.get("guest_allowed_actions", [
            "set_light", "set_climate", "play_media", "get_entity_state", "play_sound",
        ]))
        self._security_actions = set(trust_cfg.get("security_actions", [
            "lock_door", "set_alarm", "set_presence_mode",
        ]))

    def can_act(self, action_type: str) -> bool:
        """
        Prueft ob der Assistent diese Aktion ausfuehren darf.

        Args:
            action_type: Art der Aktion (z.B. "proactive_info")

        Returns:
            True wenn erlaubt
        """
        required_level = ACTION_PERMISSIONS.get(action_type, 5)
        allowed = self.level >= required_level
        if not allowed:
            logger.debug(
                "Aktion '%s' braucht Level %d, aktuell: %d",
                action_type, required_level, self.level,
            )
        return allowed

    def set_level(self, level: int) -> bool:
        """Setzt ein neues Autonomie-Level (1-5)."""
        if 1 <= level <= 5:
            old = self.level
            self.level = level
            logger.info("Autonomie-Level: %d -> %d", old, level)
            return True
        return False

    def get_level_info(self) -> dict:
        """Gibt Info ueber das aktuelle Level zurueck."""
        names = {
            1: "Assistent",
            2: "Butler",
            3: "Mitbewohner",
            4: "Vertrauter",
            5: "Autopilot",
        }
        descriptions = {
            1: "Reagiert nur auf direkte Befehle",
            2: "Proaktive Infos (Briefing, Warnungen)",
            3: "Darf kleine Aenderungen selbst machen (Licht, Temp +/-1)",
            4: "Darf Routinen anpassen, Szenen vorschlagen",
            5: "Darf neue Automationen erstellen (mit Bestaetigung)",
        }
        return {
            "level": self.level,
            "name": names.get(self.level, "Unbekannt"),
            "description": descriptions.get(self.level, ""),
            "allowed_actions": [
                action for action, req in ACTION_PERMISSIONS.items()
                if self.level >= req
            ],
        }

    # ------------------------------------------------------------------
    # Phase 10: Person-basierte Vertrauensstufen
    # ------------------------------------------------------------------

    def get_trust_level(self, person: str) -> int:
        """Gibt das Trust-Level einer Person zurueck.

        Args:
            person: Name der Person (case-insensitive)

        Returns:
            Trust-Level: 0 (Gast), 1 (Mitbewohner), 2 (Owner)
        """
        if not person:
            return self._default_trust

        person_lower = person.lower()

        # Hauptbenutzer ist immer Owner
        if person_lower == settings.user_name.lower():
            return 2

        # Konfigurierte Trust-Levels
        for name, level in self._person_trust.items():
            if name.lower() == person_lower:
                return level

        return self._default_trust

    def can_person_act(self, person: str, function_name: str, room: str = "") -> dict:
        """Prueft ob eine Person eine bestimmte Funktion ausfuehren darf.

        Args:
            person: Name der Person
            function_name: Name der Funktion (z.B. "lock_door")
            room: Raum in dem die Aktion ausgefuehrt wird (fuer Raum-Scoping)

        Returns:
            Dict mit:
                allowed: bool
                trust_level: int
                trust_name: str
                reason: str (wenn nicht erlaubt)
        """
        trust = self.get_trust_level(person)
        trust_name = TRUST_LEVEL_NAMES.get(trust, "Unbekannt")

        # Owner darf alles
        if trust >= 2:
            return {
                "allowed": True,
                "trust_level": trust,
                "trust_name": trust_name,
            }

        # Sicherheits-Aktionen nur fuer Owner
        if function_name in self._security_actions:
            return {
                "allowed": False,
                "trust_level": trust,
                "trust_name": trust_name,
                "reason": f"Sicherheitsfunktion '{function_name}' erfordert Owner-Berechtigung",
            }

        # Gast: Nur erlaubte Aktionen + Raum-Scoping
        if trust == 0:
            if function_name not in self._guest_actions:
                return {
                    "allowed": False,
                    "trust_level": trust,
                    "trust_name": trust_name,
                    "reason": f"Gaeste duerfen '{function_name}' nicht ausfuehren",
                }
            # Raum-Scoping: Gast darf nur in zugewiesenen Raeumen handeln
            if room:
                allowed_rooms = self._get_allowed_rooms(person)
                if allowed_rooms and room.lower() not in allowed_rooms:
                    return {
                        "allowed": False,
                        "trust_level": trust,
                        "trust_name": trust_name,
                        "reason": f"Zugriff nur in: {', '.join(allowed_rooms)}",
                    }
            return {
                "allowed": True,
                "trust_level": trust,
                "trust_name": trust_name,
            }

        # Mitbewohner: Alles ausser Sicherheit (schon oben geprueft)
        return {
            "allowed": True,
            "trust_level": trust,
            "trust_name": trust_name,
        }

    def _get_allowed_rooms(self, person: str) -> list[str]:
        """Gibt die erlaubten Raeume fuer eine Person zurueck (Raum-Scoping).

        Konfiguriert in settings.yaml unter trust_levels.room_restrictions.
        Leere Liste = keine Einschraenkung.
        """
        rooms_cfg = yaml_config.get("trust_levels", {}).get("room_restrictions", {})
        rooms = rooms_cfg.get(person.lower(), [])
        return [r.lower() for r in rooms]

    def get_trust_info(self) -> dict:
        """Gibt Info ueber alle Trust-Konfigurationen zurueck."""
        persons = {}
        for name, level in self._person_trust.items():
            persons[name] = {
                "level": level,
                "name": TRUST_LEVEL_NAMES.get(level, "Unbekannt"),
            }

        return {
            "default_trust": self._default_trust,
            "default_name": TRUST_LEVEL_NAMES.get(self._default_trust, "Unbekannt"),
            "persons": persons,
            "guest_actions": list(self._guest_actions),
            "security_actions": list(self._security_actions),
        }
