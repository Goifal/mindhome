"""
Autonomy Manager - Bestimmt was der Assistent selbststaendig tun darf.
Level 1 (Assistent) bis Level 5 (Autopilot).

Phase 10: Person-basierte Vertrauensstufen.
- 0 (Gast): Nur Licht, Klima, Medien im eigenen Raum
- 1 (Mitbewohner): Alles ausser Sicherheit
- 2 (Owner): Voller Zugriff

Autonomy Evolution: Dynamische Level-Anpassung basierend auf
Interaktions-Statistiken und Akzeptanzrate.

Domain-spezifische Autonomie: Unterschiedliche Autonomie-Level pro Bereich.
Z.B. Level 4 bei Klima, Level 2 bei Sicherheit.
"""

import logging
from datetime import datetime, timezone

from .config import settings, yaml_config

logger = logging.getLogger(__name__)


# Domaenen fuer domain-spezifische Autonomie
AUTONOMY_DOMAINS = {
    "climate": "Klima & Heizung",
    "light": "Licht & Beleuchtung",
    "media": "Medien & Musik",
    "cover": "Rolllaeden & Abdeckungen",
    "security": "Sicherheit & Schliessung",
    "automation": "Automationen & Routinen",
    "notification": "Benachrichtigungen & Briefings",
}

# Mapping: Aktion -> Domaene
ACTION_DOMAIN_MAP = {
    "adjust_temperature_small": "climate",
    "adjust_light_auto": "light",
    "suggest_scene": "light",
    "modify_routine": "automation",
    "create_automation": "automation",
    "modify_schedule": "automation",
    "proactive_info": "notification",
    "morning_briefing": "notification",
    "arrival_greeting": "notification",
    "security_alert": "security",
    "pause_reminder": "notification",
    "learn_preferences": "automation",
}

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
        self._default_trust = int(trust_cfg.get("default", 0))
        raw_persons = trust_cfg.get("persons", {}) or {}
        self._person_trust: dict[str, int] = {
            name: int(level) for name, level in raw_persons.items()
        }
        self._guest_actions = set(trust_cfg.get("guest_allowed_actions", [
            "set_light", "set_climate", "play_media", "get_entity_state", "play_sound",
            "get_house_status", "get_room_climate",
        ]))
        self._security_actions = set(trust_cfg.get("security_actions", [
            "lock_door", "arm_security_system", "set_presence_mode",
        ]))

        # Konfigurierbare Action-Permissions und Evolution-Criteria
        auto_cfg = yaml_config.get("autonomy", {})
        self._action_permissions = {k: int(v) for k, v in (auto_cfg.get("action_permissions") or ACTION_PERMISSIONS).items()}
        raw_evo = auto_cfg.get("evolution_criteria")
        if raw_evo:
            self._evolution_criteria = {int(k): v for k, v in raw_evo.items()}
        else:
            self._evolution_criteria = dict(self._EVOLUTION_CRITERIA)

        # Domain-spezifische Autonomie-Level
        self._domain_levels_enabled = auto_cfg.get("domain_levels_enabled", False)
        raw_domain = auto_cfg.get("domain_levels", {})
        self._domain_levels: dict[str, int] = {
            d: int(l) for d, l in raw_domain.items() if d in AUTONOMY_DOMAINS
        }

    def can_act(self, action_type: str, domain: str = "") -> bool:
        """
        Prueft ob der Assistent diese Aktion ausfuehren darf.

        Nutzt domain-spezifische Level falls aktiviert und konfiguriert.

        Args:
            action_type: Art der Aktion (z.B. "proactive_info")
            domain: Optionale Domaene (z.B. "climate", "light")

        Returns:
            True wenn erlaubt
        """
        required_level = self._action_permissions.get(action_type, 5)
        effective_level = self._get_effective_level(action_type, domain)
        allowed = effective_level >= required_level
        if not allowed:
            logger.debug(
                "Aktion '%s' braucht Level %d, effektiv: %d (Domaene: %s)",
                action_type, required_level, effective_level, domain or "global",
            )
        return allowed

    def _get_effective_level(self, action_type: str = "", domain: str = "") -> int:
        """Bestimmt das effektive Autonomie-Level unter Beruecksichtigung von Domaenen.

        Args:
            action_type: Aktion (fuer automatische Domaenen-Erkennung)
            domain: Explizite Domaene (hat Vorrang)

        Returns:
            Effektives Level (1-5)
        """
        if not self._domain_levels_enabled or not self._domain_levels:
            return self.level

        # Domaene bestimmen: explizit oder aus Action-Mapping
        resolved_domain = domain or ACTION_DOMAIN_MAP.get(action_type, "")
        if resolved_domain and resolved_domain in self._domain_levels:
            return self._domain_levels[resolved_domain]

        return self.level

    def set_level(self, level: int) -> bool:
        """Setzt ein neues Autonomie-Level (1-5)."""
        if 1 <= level <= 5:
            old = self.level
            self.level = level
            logger.info("Autonomie-Level: %d -> %d", old, level)
            return True
        return False

    # Level-Namen (auch von aussen nutzbar)
    LEVEL_NAMES = {
        1: "Assistent",
        2: "Butler",
        3: "Mitbewohner",
        4: "Vertrauter",
        5: "Autopilot",
    }

    def get_level_info(self) -> dict:
        """Gibt Info ueber das aktuelle Level zurueck."""
        descriptions = {
            1: "Reagiert nur auf direkte Befehle",
            2: "Proaktive Infos (Briefing, Warnungen)",
            3: "Darf kleine Aenderungen selbst machen (Licht, Temp +/-1)",
            4: "Darf Routinen anpassen, Szenen vorschlagen",
            5: "Darf neue Automationen erstellen (mit Bestaetigung)",
        }
        info = {
            "level": self.level,
            "name": self.LEVEL_NAMES.get(self.level, "Unbekannt"),
            "description": descriptions.get(self.level, ""),
            "allowed_actions": [
                action for action, req in self._action_permissions.items()
                if self.level >= req
            ],
            "domain_levels_enabled": self._domain_levels_enabled,
        }
        if self._domain_levels_enabled and self._domain_levels:
            info["domain_levels"] = {
                d: {
                    "level": l,
                    "name": self.LEVEL_NAMES.get(l, "?"),
                    "domain_name": AUTONOMY_DOMAINS.get(d, d),
                }
                for d, l in self._domain_levels.items()
            }
        return info

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
                "reason": "Fuer Sicherheitsaktionen wird eine hoehere Autorisierung benoetigt.",
            }

        # Gast: Nur erlaubte Aktionen + Raum-Scoping
        if trust == 0:
            if function_name not in self._guest_actions:
                return {
                    "allowed": False,
                    "trust_level": trust,
                    "trust_name": trust_name,
                    "reason": "Ich fuerchte, diese Funktion steht Gaesten nicht zur Verfuegung.",
                }
            # Raum-Scoping: Gast darf nur in zugewiesenen Raeumen handeln
            if room:
                allowed_rooms = self._get_allowed_rooms(person)
                if allowed_rooms and room.lower() not in allowed_rooms:
                    return {
                        "allowed": False,
                        "trust_level": trust,
                        "trust_name": trust_name,
                        "reason": f"Ich fuerchte, der Zugriff ist auf folgende Raeume beschraenkt: {', '.join(allowed_rooms)}.",
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

    # ------------------------------------------------------------------
    # Autonomy Evolution: Dynamische Level-Anpassung
    # ------------------------------------------------------------------

    _redis = None
    _REDIS_KEY_STATS = "mha:autonomy:stats"
    _REDIS_KEY_LAST_EVAL = "mha:autonomy:last_eval"

    # Kriterien pro Level-Aufstieg (min_days, min_interactions, min_acceptance_rate)
    _EVOLUTION_CRITERIA = {
        2: {"min_days": 30, "min_interactions": 200, "min_acceptance": 0.7},
        3: {"min_days": 90, "min_interactions": 500, "min_acceptance": 0.8},
        4: {"min_days": 180, "min_interactions": 1000, "min_acceptance": 0.85},
        # Level 5 (Autopilot) nur manuell — zu kritisch fuer automatischen Aufstieg
    }

    def set_redis(self, redis_client):
        """Verbindet den Redis-Client fuer Statistik-Tracking."""
        self._redis = redis_client

    async def track_interaction(self, action_type: str, accepted: bool):
        """Trackt eine Interaktion fuer die Evolution-Bewertung.

        Args:
            action_type: Art der Aktion (z.B. "proactive_info", "execute_function_call")
            accepted: True wenn der User die Aktion akzeptiert/positiv bewertet hat
        """
        if not self._redis:
            return
        try:
            key = self._REDIS_KEY_STATS
            await self._redis.hincrby(key, "total", 1)
            if accepted:
                await self._redis.hincrby(key, "accepted", 1)
            else:
                await self._redis.hincrby(key, "rejected", 1)
            await self._redis.hincrby(key, f"type:{action_type}", 1)
        except Exception as e:
            logger.debug("Evolution-Tracking Fehler: %s", e)

    async def evaluate_evolution(self) -> dict | None:
        """Prueft ob ein Level-Aufstieg moeglich ist.

        Wird woechentlich aus dem Brain aufgerufen.
        Returns:
            Dict mit Vorschlag wenn Aufstieg moeglich, sonst None.
        """
        if not self._redis:
            return None

        # Max-Level aus Config respektieren
        evolution_cfg = yaml_config.get("autonomy", {}).get("evolution", {})
        if not evolution_cfg.get("enabled", True):
            return None
        max_level = evolution_cfg.get("max_level", 3)

        next_level = self.level + 1
        if next_level > max_level or next_level > 4:
            return None  # Level 5 nur manuell

        criteria = self._evolution_criteria.get(next_level)
        if not criteria:
            return None

        try:
            # Statistiken aus Redis laden
            raw_stats = await self._redis.hgetall(self._REDIS_KEY_STATS)
            if not raw_stats:
                return None
            stats = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw_stats.items()}

            total = int(stats.get("total", 0) or 0)
            accepted = int(stats.get("accepted", 0) or 0)
            rejected = int(stats.get("rejected", 0) or 0)

            # System-Uptime aus Redis (gesetzt beim Start)
            first_start = await self._redis.get("mha:first_start")
            if first_start:
                try:
                    start_date = datetime.fromisoformat(first_start.decode() if isinstance(first_start, bytes) else first_start)
                    days_active = (datetime.now(timezone.utc) - start_date).days
                except (ValueError, TypeError):
                    days_active = 0
            else:
                days_active = 0
                # Ersten Start merken
                await self._redis.set(
                    "mha:first_start",
                    datetime.now(timezone.utc).isoformat(),
                )

            # Akzeptanzrate berechnen
            acceptance_rate = accepted / max(1, total)

            # Kriterien pruefen
            meets_days = days_active >= criteria["min_days"]
            meets_interactions = total >= criteria["min_interactions"]
            meets_acceptance = acceptance_rate >= criteria["min_acceptance"]

            result = {
                "current_level": self.level,
                "proposed_level": next_level,
                "days_active": days_active,
                "total_interactions": total,
                "acceptance_rate": round(acceptance_rate, 3),
                "criteria": criteria,
                "meets_days": meets_days,
                "meets_interactions": meets_interactions,
                "meets_acceptance": meets_acceptance,
                "ready": meets_days and meets_interactions and meets_acceptance,
            }

            if result["ready"]:
                logger.info(
                    "Autonomy Evolution bereit: Level %d -> %d "
                    "(Tage: %d, Interaktionen: %d, Akzeptanz: %.1f%%)",
                    self.level, next_level, days_active, total,
                    acceptance_rate * 100,
                )

            return result

        except Exception as e:
            logger.error("Evolution-Bewertung Fehler: %s", e)
            return None

    async def apply_evolution(self) -> bool:
        """Wendet einen Level-Aufstieg an (nach User-Bestaetigung).

        Returns:
            True wenn erfolgreich.
        """
        eval_result = await self.evaluate_evolution()
        if not eval_result or not eval_result.get("ready"):
            return False

        new_level = eval_result["proposed_level"]
        if self.set_level(new_level):
            # Statistiken zuruecksetzen fuer naechste Periode
            if self._redis:
                await self._redis.delete(self._REDIS_KEY_STATS)
                await self._redis.set(
                    self._REDIS_KEY_LAST_EVAL,
                    datetime.now(timezone.utc).isoformat(),
                )
            logger.info("Autonomy Evolution angewendet: Level %d", new_level)
            return True
        return False

    def get_evolution_info(self) -> dict:
        """Gibt Info ueber den Evolution-Status zurueck (synchron, fuer API)."""
        evolution_cfg = yaml_config.get("autonomy", {}).get("evolution", {})
        next_level = self.level + 1
        criteria = self._evolution_criteria.get(next_level, {})
        return {
            "enabled": evolution_cfg.get("enabled", True),
            "max_level": evolution_cfg.get("max_level", 3),
            "current_level": self.level,
            "next_level": next_level if next_level <= 4 else None,
            "criteria": criteria,
        }
