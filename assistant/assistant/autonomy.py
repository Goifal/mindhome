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
from zoneinfo import ZoneInfo

from .config import settings, yaml_config

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))


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
    "set_light": "light",
    "set_cover": "cover",
    "set_climate": "climate",
    "play_media": "media",
    "get_active_intents": "notification",
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
    "set_light": 3,  # Licht schalten (Anticipation)
    "set_cover": 3,  # Rolllaeden steuern (Anticipation)
    "set_climate": 3,  # Klima steuern (Anticipation)
    "play_media": 3,  # Medien abspielen (Anticipation)
    "get_active_intents": 2,  # Intents abfragen (nur Info)
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
        # Level aus yaml_config lesen (UI-konfigurierbar), Fallback auf .env Default
        auto_cfg = yaml_config.get("autonomy", {}) or {}
        self.level = int(auto_cfg.get("level") or settings.autonomy_level)

        # Phase 10: Trust-Level Konfiguration laden
        trust_cfg = yaml_config.get("trust_levels", {}) or {}
        self._default_trust = int(trust_cfg.get("default") or 0)
        raw_persons = trust_cfg.get("persons", {}) or {}
        self._person_trust: dict[str, int] = {
            name: int(level) for name, level in raw_persons.items()
        }
        self._guest_actions = set(
            trust_cfg.get(
                "guest_allowed_actions",
                [
                    "set_light",
                    "set_climate",
                    "play_media",
                    "get_entity_state",
                    "play_sound",
                    "get_house_status",
                    "get_room_climate",
                ],
            )
        )
        self._security_actions = set(
            trust_cfg.get(
                "security_actions",
                [
                    "lock_door",
                    "unlock_door",
                    "arm_security_system",
                    "disarm_alarm",
                    "set_presence_mode",
                ],
            )
        )

        # Konfigurierbare Action-Permissions und Evolution-Criteria
        auto_cfg = yaml_config.get("autonomy", {})
        # Defaults als Basis, Config-Werte ueberschreiben einzelne Keys
        _merged_perms = dict(ACTION_PERMISSIONS)
        _cfg_perms = auto_cfg.get("action_permissions")
        if _cfg_perms:
            _merged_perms.update({k: int(v) for k, v in _cfg_perms.items()})
        self._action_permissions = _merged_perms
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

        # Outcome Tracker Integration (gesetzt via set_outcome_tracker)
        self._outcome_tracker = None

        # Emergency escalation state (#40)
        self._emergency_escalation: dict | None = None

        # Temporal autonomy config (#42)
        temporal_cfg = auto_cfg.get("temporal", {}) or {}
        self._temporal_enabled = temporal_cfg.get("enabled", False) or False
        self._temporal_night_start = int(temporal_cfg.get("night_start_hour") or 22)
        self._temporal_night_end = int(temporal_cfg.get("night_end_hour") or 6)
        self._temporal_night_offset = int(
            temporal_cfg.get("night_offset")
            if temporal_cfg.get("night_offset") is not None
            else -1
        )
        self._temporal_day_offset = int(temporal_cfg.get("day_offset") or 0)

        # De-escalation config (#41)
        deesc_cfg = auto_cfg.get("deescalation", {}) or {}
        self._deescalation_enabled = deesc_cfg.get("enabled", False) or False
        self._deescalation_min_acceptance = float(
            deesc_cfg.get("min_acceptance_rate") or 0.5
        )
        self._deescalation_eval_days = int(deesc_cfg.get("evaluation_days") or 14)

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
                action_type,
                required_level,
                effective_level,
                domain or "global",
            )
        return allowed

    def get_effective_level(self, domain: str = None) -> int:
        """Bestimmt das effektive Autonomie-Level mit temporalem Offset und Emergency.

        Prueft in dieser Reihenfolge:
        1. Aktive Emergency-Eskalation → Level 5
        2. Domain-spezifisches Level (falls aktiviert)
        3. Globales Level + temporaler Offset (Nachtabsenkung)

        Args:
            domain: Optionale Domaene (z.B. "climate", "light")

        Returns:
            Effektives Level (1-5)
        """
        return self._get_effective_level(domain=domain or "")

    def _get_temporal_offset(self) -> int:
        """Berechnet den temporalen Offset basierend auf der Tageszeit."""
        if not self._temporal_enabled:
            return 0
        hour = datetime.now(_LOCAL_TZ).hour
        if self._temporal_night_start > self._temporal_night_end:
            is_night = (
                hour >= self._temporal_night_start or hour < self._temporal_night_end
            )
        else:
            is_night = self._temporal_night_start <= hour < self._temporal_night_end
        return self._temporal_night_offset if is_night else self._temporal_day_offset

    def _get_effective_level(self, action_type: str = "", domain: str = "") -> int:
        """Bestimmt das effektive Autonomie-Level unter Beruecksichtigung von Domaenen.

        Args:
            action_type: Aktion (fuer automatische Domaenen-Erkennung)
            domain: Explizite Domaene (hat Vorrang)

        Returns:
            Effektives Level (1-5)
        """
        if self._is_emergency_active():
            return 5

        resolved_domain = domain or ACTION_DOMAIN_MAP.get(action_type, "")

        if self._domain_levels_enabled and self._domain_levels:
            if resolved_domain and resolved_domain in self._domain_levels:
                base_level = self._domain_levels[resolved_domain]
            else:
                base_level = self.level
        else:
            base_level = self.level

        offset = self._get_temporal_offset()
        return max(1, min(5, base_level + offset))

    def set_level(self, level: int) -> bool:
        """Setzt ein neues Autonomie-Level (1-5).

        Respektiert max_level aus der Config — Werte darueber werden abgelehnt.
        """
        if not (1 <= level <= 5):
            return False

        # max_level aus Config respektieren (gleiche Quelle wie evaluate_evolution)
        evolution_cfg = yaml_config.get("autonomy", {}).get("evolution", {})
        max_level = evolution_cfg.get("max_level", 5)
        if level > max_level:
            logger.warning(
                "Autonomie-Level %d abgelehnt — max_level ist %d", level, max_level
            )
            return False

        old = self.level
        self.level = level
        logger.info("Autonomie-Level: %d -> %d", old, level)
        return True

    # Level-Namen (auch von aussen nutzbar)
    LEVEL_NAMES = {
        1: "Assistent",
        2: "Butler",
        3: "Mitbewohner",
        4: "Vertrauter",
        5: "Autopilot",
    }

    # ------------------------------------------------------------------
    # Harte Sicherheitsgrenzen (Safety Caps)
    # ------------------------------------------------------------------

    SAFETY_CAPS = {
        "max_temperature_change": 3,  # Max +/- Grad pro Aktion
        "min_temperature": 14,  # Absolutes Minimum (Celsius)
        "max_temperature": 30,  # Absolutes Maximum (Celsius)
        "max_actions_per_minute": 10,  # Rate-Limit pro Person
        "max_actions_per_hour": 100,  # Rate-Limit pro Person
        "max_automation_creations_per_day": 5,
        "max_brightness": 100,  # Prozent
    }

    def can_execute(
        self,
        person: str,
        action_type: str,
        function_name: str = "",
        domain: str = "",
        room: str = "",
    ) -> dict:
        """Kombinierte Pruefung: Autonomie-Level UND Person-Trust.

        Prueft beide Hierarchien (Assistant-Autonomie + Person-Vertrauen)
        in einem Aufruf und gibt ein einheitliches Ergebnis zurueck.

        Args:
            person: Name der Person
            action_type: Art der Aktion (z.B. "proactive_info", "execute_function_call")
            function_name: Konkrete Funktion (z.B. "lock_door")
            domain: Optionale Domaene (z.B. "climate")
            room: Raum fuer Raum-Scoping

        Returns:
            Dict mit allowed, autonomy_ok, trust_ok, reason
        """
        # 1. Autonomie-Level pruefen
        autonomy_ok = self.can_act(action_type, domain)

        # 2. Person-Trust pruefen
        trust_result = self.can_person_act(person, function_name, room)
        trust_ok = trust_result["allowed"]

        allowed = autonomy_ok and trust_ok

        result = {
            "allowed": allowed,
            "autonomy_ok": autonomy_ok,
            "autonomy_level": self._get_effective_level(action_type, domain),
            "trust_ok": trust_ok,
            "trust_level": trust_result["trust_level"],
            "trust_name": trust_result.get("trust_name", ""),
        }

        if not allowed:
            reasons = []
            if not autonomy_ok:
                required = self._action_permissions.get(action_type, 5)
                effective = self._get_effective_level(action_type, domain)
                detail_parts = [
                    f"Autonomie-Level {effective} reicht nicht fuer "
                    f"'{action_type}' (benoetigt: {required})",
                ]
                if effective != self.level:
                    offset_info = []
                    if self._temporal_enabled:
                        t_offset = self._get_temporal_offset()
                        if t_offset != 0:
                            offset_info.append(
                                f"Temporal-Offset {t_offset:+d} aktiv "
                                f"(Nacht {self._temporal_night_start}-"
                                f"{self._temporal_night_end} Uhr)"
                            )
                    resolved = domain or ACTION_DOMAIN_MAP.get(action_type, "")
                    if (
                        self._domain_levels_enabled
                        and resolved
                        and resolved in self._domain_levels
                    ):
                        offset_info.append(
                            f"Domain-Level '{resolved}' = "
                            f"{self._domain_levels[resolved]}"
                        )
                    if offset_info:
                        detail_parts.append(
                            f"Global: {self.level}, reduziert durch: "
                            + ", ".join(offset_info)
                        )
                reasons.extend(detail_parts)
            if not trust_ok:
                reasons.append(trust_result.get("reason", "Trust-Check fehlgeschlagen"))
            result["reason"] = "; ".join(reasons)

        return result

    def check_safety_caps(self, function_name: str, args: dict) -> dict:
        """Prueft harte Sicherheitsgrenzen unabhaengig von Level/Trust.

        Diese Grenzen koennen NICHT ueberschrieben werden — auch nicht vom Owner.

        Args:
            function_name: Name der Funktion
            args: Funktions-Argumente

        Returns:
            Dict mit allowed und ggf. reason
        """
        caps = self.SAFETY_CAPS

        # Temperatur-Grenzen
        if function_name in ("set_temperature", "set_climate", "adjust_temperature"):
            temp = args.get("temperature")
            if temp is not None:
                try:
                    temp = float(temp)
                    if temp != temp:  # NaN check (math.isnan equivalent)
                        raise ValueError("NaN")
                except (ValueError, TypeError):
                    return {"allowed": False, "reason": "Ungueltige Temperaturangabe."}
                if temp < caps["min_temperature"]:
                    return {
                        "allowed": False,
                        "reason": f"Temperatur {temp}°C liegt unter dem Minimum von {caps['min_temperature']}°C.",
                    }
                if temp > caps["max_temperature"]:
                    return {
                        "allowed": False,
                        "reason": f"Temperatur {temp}°C ueberschreitet das Maximum von {caps['max_temperature']}°C.",
                    }

        # Helligkeit-Grenzen
        if function_name in ("set_light", "set_brightness"):
            brightness = args.get("brightness")
            if brightness is not None:
                try:
                    brightness = int(brightness)
                except (ValueError, TypeError):
                    pass
                else:
                    if brightness < 0 or brightness > caps["max_brightness"]:
                        return {
                            "allowed": False,
                            "reason": f"Helligkeit muss zwischen 0 und {caps['max_brightness']}% liegen.",
                        }

        return {"allowed": True}

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
                action
                for action, req in self._action_permissions.items()
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
            person: Name der Person (case-insensitive).
                    Leerer String = Gast (default_trust).
                    "global" = Owner-Kontext (fuer interne Aufrufe).

        Returns:
            Trust-Level: 0 (Gast), 1 (Mitbewohner), 2 (Owner)
        """
        if not person:
            return self._default_trust

        if person.lower() == "global":
            # Expliziter globaler Kontext (interne Aufrufe):
            return 2

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
    # Emergency Autonomy Escalation (#40)
    # ------------------------------------------------------------------

    def escalate_for_emergency(self, duration_minutes: int = 15) -> None:
        """Temporaer auf Level 5 eskalieren fuer Notfaelle.

        Args:
            duration_minutes: Dauer der Eskalation in Minuten.
                              Wird durch Config begrenzt.
        """
        threat_cfg = yaml_config.get("threat_assessment", {})
        max_duration = int(threat_cfg.get("emergency_boost_duration_min", 30))
        duration_minutes = max(1, min(duration_minutes, max_duration))

        self._emergency_escalation = {
            "activated_at": datetime.now(timezone.utc),
            "duration_minutes": duration_minutes,
        }
        logger.warning(
            "Emergency-Eskalation aktiviert: Level 5 fuer %d Minuten",
            duration_minutes,
        )

    def clear_emergency_escalation(self) -> None:
        """Beendet die Emergency-Eskalation manuell."""
        if self._emergency_escalation:
            logger.info("Emergency-Eskalation manuell beendet")
        self._emergency_escalation = None

    def _is_emergency_active(self) -> bool:
        """Prueft ob eine Emergency-Eskalation aktiv ist."""
        if not self._emergency_escalation:
            return False
        activated_at = self._emergency_escalation["activated_at"]
        duration = self._emergency_escalation["duration_minutes"]
        elapsed = (datetime.now(timezone.utc) - activated_at).total_seconds() / 60
        if elapsed >= duration:
            logger.info("Emergency-Eskalation abgelaufen nach %.1f Minuten", elapsed)
            self._emergency_escalation = None
            return False
        return True

    # ------------------------------------------------------------------
    # De-Escalation (#41)
    # ------------------------------------------------------------------

    async def check_deescalation(self) -> dict | None:
        """Prueft ob eine Level-Reduktion vorgeschlagen werden sollte.

        Basiert auf der Akzeptanzrate der letzten evaluation_days.
        Reduziert NIEMALS automatisch — gibt nur einen Vorschlag zurueck.

        Returns:
            Dict mit Vorschlag oder None.
        """
        if not self._deescalation_enabled:
            return None
        if self.level <= 1:
            return None
        if not self._redis:
            return None

        try:
            raw_stats = await self._redis.hgetall(self._REDIS_KEY_STATS)
            if not raw_stats:
                return None
            stats = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in raw_stats.items()
            }
            total = int(stats.get("total", 0) or 0)
            accepted = int(stats.get("accepted", 0) or 0)

            if total < 10:
                return None

            acceptance_rate = accepted / max(1, total)

            if acceptance_rate < self._deescalation_min_acceptance:
                proposed_level = self.level - 1
                logger.info(
                    "De-Eskalation vorgeschlagen: Level %d -> %d "
                    "(Akzeptanz: %.1f%% < %.1f%%)",
                    self.level,
                    proposed_level,
                    acceptance_rate * 100,
                    self._deescalation_min_acceptance * 100,
                )
                return {
                    "current_level": self.level,
                    "proposed_level": proposed_level,
                    "acceptance_rate": round(acceptance_rate, 3),
                    "threshold": self._deescalation_min_acceptance,
                    "evaluation_days": self._deescalation_eval_days,
                    "total_interactions": total,
                }
            return None

        except Exception as e:
            logger.warning("De-Eskalation Pruefung fehlgeschlagen: %s", e)
            return None

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

    def set_outcome_tracker(self, tracker):
        """Verbindet den Outcome-Tracker fuer Evolution-Feedback.

        Outcome-Scores fliessen als zusaetzliches Signal in die
        Evolution-Bewertung ein (max +5% Boost auf Akzeptanzrate).
        """
        self._outcome_tracker = tracker

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
            return None  # Level 5 nur manuell (Sicherheitsgrenze)

        criteria = self._evolution_criteria.get(next_level)
        if not criteria:
            return None

        try:
            # Statistiken aus Redis laden
            raw_stats = await self._redis.hgetall(self._REDIS_KEY_STATS)
            if not raw_stats:
                return None
            stats = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in raw_stats.items()
            }

            total = int(stats.get("total", 0) or 0)
            accepted = int(stats.get("accepted", 0) or 0)
            rejected = int(stats.get("rejected", 0) or 0)

            # System-Uptime aus Redis (gesetzt beim Start)
            first_start = await self._redis.get("mha:first_start")
            if first_start:
                try:
                    start_date = datetime.fromisoformat(
                        first_start.decode()
                        if isinstance(first_start, bytes)
                        else first_start
                    )
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

            # Outcome-Tracker Integration: Durchschnittliche Erfolgsrate
            # aller Aktionstypen als zusaetzliches Signal einbeziehen.
            # Outcome-Scores (0-1) fliessen gewichtet in die Akzeptanzrate ein.
            outcome_boost = 0.0
            outcome_score_avg = None
            if self._outcome_tracker:
                try:
                    all_scores = await self._outcome_tracker.get_all_scores()
                    if all_scores:
                        outcome_score_avg = sum(all_scores.values()) / len(all_scores)
                        # Boost: Wenn Outcome-Score > 0.7, erhoehe Akzeptanzrate leicht
                        # Max +5% Boost (verhindert Gaming)
                        if outcome_score_avg > 0.7:
                            outcome_boost = min(0.05, (outcome_score_avg - 0.7) * 0.167)
                except Exception as e:
                    logger.debug("Outcome-Score fuer Evolution nicht verfuegbar: %s", e)

            effective_acceptance = min(1.0, acceptance_rate + outcome_boost)

            # Kriterien pruefen
            meets_days = days_active >= criteria["min_days"]
            meets_interactions = total >= criteria["min_interactions"]
            meets_acceptance = effective_acceptance >= criteria["min_acceptance"]

            result = {
                "current_level": self.level,
                "proposed_level": next_level,
                "days_active": days_active,
                "total_interactions": total,
                "acceptance_rate": round(acceptance_rate, 3),
                "effective_acceptance_rate": round(effective_acceptance, 3),
                "outcome_score_avg": round(outcome_score_avg, 3)
                if outcome_score_avg is not None
                else None,
                "outcome_boost": round(outcome_boost, 3),
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
                    self.level,
                    next_level,
                    days_active,
                    total,
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
