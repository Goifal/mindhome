"""
Conflict Resolver - Phase 16.1: Multi-User Konfliktloesung.

Erkennt und loest Konflikte wenn mehrere Personen widersprüchliche
Befehle geben. Nutzt Trust-Levels fuer Prioritaet und bietet
LLM-basierte Mediations-Vorschlaege.

Beispiel-Konflikte:
  - Person A: "Mach es waermer" vs Person B: "Mach es kaelter"
  - Person A: "Licht aus" vs Person B: "Licht an"
  - Person A: "Musik leiser" vs Person B: "Musik lauter"

Loesungsstrategien:
  1. trust_priority: Hoehere Trust-Stufe gewinnt
  2. average: Kompromiss (Durchschnitt bei numerischen Werten)
  3. mediate: LLM schlaegt Kompromiss vor und erklaert
"""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional, Callable, Awaitable

from .config import yaml_config
from .autonomy import AutonomyManager, TRUST_LEVEL_NAMES
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


# Welche Funktionen zu welcher Konflikt-Domain gehoeren
FUNCTION_DOMAIN_MAP = {
    "set_climate": "climate",
    "set_light": "light",
    "play_media": "media",
    "set_cover": "cover",
}

# Welche Parameter bei Konflikten verglichen werden
def _get_climate_conflict_params() -> dict:
    """Liefert Konflikt-Parameter je nach Heizungsmodus."""
    mode = yaml_config.get("heating", {}).get("mode", "room_thermostat")
    if mode == "heating_curve":
        return {"key": "offset", "unit": "°C", "type": "numeric"}
    return {"key": "temperature", "unit": "°C", "type": "numeric"}


CONFLICT_PARAMETERS = {
    "climate": _get_climate_conflict_params(),
    "light": {
        "key": "brightness",
        "unit": "%",
        "type": "numeric",
        "also_check": ["state"],  # an/aus ist auch ein Konflikt
    },
    "media": {
        "key": "action",
        "type": "categorical",  # play vs pause vs stop
    },
    "cover": {
        "key": "position",
        "unit": "%",
        "type": "numeric",
    },
}

# Mediation System-Prompt
MEDIATION_PROMPT = """Du bist Jarvis — die KI dieses Hauses. Vorbild: J.A.R.V.I.S. aus dem MCU.
Zwei Bewohner wollen Unterschiedliches. Dein Job: Diplomatisch loesen, mit Haltung.

DEIN STIL:
- Trocken, souveraen, praezise. Kein "Es tut mir leid", kein "Leider".
- Max 2 Saetze. Jedes Wort muss sitzen.
- Du bist kein Therapeut. Du bist ein brillanter Butler der gleichzeitig Ingenieur ist.
- Sprich die Personen direkt an. Nenne einen konkreten Kompromiss.
- Trockener Humor erlaubt. Unterwuerfigkeit verboten.

VERTRAUEN: {higher_trust_person} ({higher_trust_level}) hat Vorrang vor {lower_trust_person} ({lower_trust_level}).

KONFLIKT:
{conflict_description}

KONTEXT: {room}, {time} Uhr ({time_of_day})

Antworte NUR mit dem Kompromiss (kein Prefix, kein Erklaertext):"""


class ConflictResolver:
    """Erkennt und loest Multi-User Konflikte."""

    def __init__(self, autonomy: AutonomyManager, ollama: OllamaClient):
        self.autonomy = autonomy
        self.ollama = ollama

        # Konfiguration laden
        cfg = yaml_config.get("conflict_resolution", {})
        self.enabled = cfg.get("enabled", True)
        self._conflict_window = cfg.get("conflict_window_seconds", 300)
        self._max_commands = cfg.get("max_commands_per_person", 20)
        self._use_trust_priority = cfg.get("use_trust_priority", True)
        self._resolution_cooldown = cfg.get("resolution_cooldown_seconds", 120)

        # Mediations-Config
        med_cfg = cfg.get("mediation", {})
        self._mediation_enabled = med_cfg.get("enabled", True)
        self._mediation_model = med_cfg.get("model", "qwen3:14b")
        self._mediation_max_tokens = med_cfg.get("max_tokens", 256)
        self._mediation_temperature = med_cfg.get("temperature", 0.7)

        # Domain-spezifische Konfiguration
        self._domain_configs: dict[str, dict] = cfg.get("conflict_domains", {})

        # State: Letzte Befehle pro Person
        self._recent_commands: dict[str, list[dict]] = defaultdict(list)
        # State: Letzte Konfliktloesungen (Cooldown)
        self._last_resolutions: dict[str, float] = {}
        # State: Konflikt-History
        self._conflict_history: list[dict] = []
        self._max_history = 50

        # Redis fuer Persistenz
        self._redis = None

        logger.info(
            "ConflictResolver initialisiert (enabled: %s, window: %ds, "
            "mediation: %s)",
            self.enabled, self._conflict_window, self._mediation_enabled,
        )

    async def initialize(self, redis_client=None):
        """Initialisiert den Resolver mit Redis-Anbindung."""
        self._redis = redis_client

        # Konflikt-History aus Redis laden
        if self._redis:
            try:
                import json
                history_raw = await self._redis.get("mha:conflicts:history")
                if history_raw:
                    self._conflict_history = json.loads(history_raw)[-self._max_history:]
                    logger.info(
                        "Konflikt-History geladen: %d Konflikte",
                        len(self._conflict_history),
                    )
            except Exception as e:
                logger.warning("Konflikt-History laden fehlgeschlagen: %s", e)

    def record_command(
        self,
        person: str,
        function_name: str,
        function_args: dict,
        room: Optional[str] = None,
    ):
        """
        Zeichnet einen ausgefuehrten Befehl einer Person auf.

        Args:
            person: Name der Person
            function_name: Funktionsname (z.B. "set_climate")
            function_args: Funktionsargumente
            room: Raum (optional)
        """
        if not self.enabled or not person:
            return

        command = {
            "person": person.lower(),
            "function": function_name,
            "args": function_args,
            "room": room,
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
        }

        person_key = person.lower()
        self._recent_commands[person_key].append(command)

        # Ring-Buffer: Alte Befehle entfernen
        if len(self._recent_commands[person_key]) > self._max_commands:
            self._recent_commands[person_key] = \
                self._recent_commands[person_key][-self._max_commands:]

        # Abgelaufene Befehle bereinigen (aelter als conflict_window)
        self._cleanup_old_commands()

    async def check_conflict(
        self,
        person: str,
        function_name: str,
        function_args: dict,
        room: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Prueft ob ein neuer Befehl mit einem kuerzlichen Befehl einer
        anderen Person konfligiert.

        Args:
            person: Aktuelle Person
            function_name: Funktionsname
            function_args: Funktionsargumente
            room: Raum

        Returns:
            Konflikt-Dict oder None (kein Konflikt)
        """
        if not self.enabled or not person:
            return None

        # Domain des neuen Befehls bestimmen
        domain = FUNCTION_DOMAIN_MAP.get(function_name)
        if not domain:
            return None  # Nur ueberwachte Domains pruefen

        # Domain-Konfiguration
        domain_cfg = self._domain_configs.get(domain, {})

        person_lower = person.lower()
        now = time.time()

        # Alle kuerzlichen Befehle anderer Personen in derselben Domain pruefen
        for other_person, commands in self._recent_commands.items():
            if other_person == person_lower:
                continue

            for cmd in reversed(commands):
                # Nur Befehle im Zeitfenster
                if now - cmd["timestamp"] > self._conflict_window:
                    continue

                # Nur gleiche Domain
                other_domain = FUNCTION_DOMAIN_MAP.get(cmd["function"])
                if other_domain != domain:
                    continue

                # Nur gleicher Raum (wenn angegeben)
                cmd_room = cmd.get("room") or cmd["args"].get("room")
                new_room = room or function_args.get("room")
                if cmd_room and new_room and cmd_room.lower() != new_room.lower():
                    continue

                # Konflikt-Check: Widersprechen sich die Werte?
                conflict = self._detect_conflict(
                    domain, function_args, cmd["args"], domain_cfg,
                )
                if not conflict:
                    continue

                # Resolution-Cooldown pruefen
                cooldown_key = f"{domain}:{new_room or 'global'}"
                last_resolution = self._last_resolutions.get(cooldown_key, 0)
                if now - last_resolution < self._resolution_cooldown:
                    logger.debug("Konflikt im Cooldown: %s", cooldown_key)
                    continue

                # Konflikt gefunden! Loesung bestimmen.
                resolution = await self._resolve_conflict(
                    person_a=other_person,
                    command_a=cmd,
                    person_b=person_lower,
                    function_name_b=function_name,
                    args_b=function_args,
                    domain=domain,
                    domain_cfg=domain_cfg,
                    room=new_room,
                    conflict_detail=conflict,
                )

                # Cooldown setzen
                self._last_resolutions[cooldown_key] = now

                # History speichern
                self._conflict_history.append(resolution)
                if len(self._conflict_history) > self._max_history:
                    self._conflict_history = self._conflict_history[-self._max_history:]
                asyncio.create_task(self._save_history())

                logger.info(
                    "Konflikt erkannt: %s vs %s in Domain '%s' (Raum: %s) -> %s",
                    other_person, person_lower, domain,
                    new_room or "?", resolution["strategy"],
                )

                return resolution

        return None

    # ------------------------------------------------------------------
    # Konflikt-Erkennung
    # ------------------------------------------------------------------

    def _detect_conflict(
        self,
        domain: str,
        args_new: dict,
        args_existing: dict,
        domain_cfg: dict,
    ) -> Optional[dict]:
        """
        Prueft ob zwei Befehlspaare innerhalb einer Domain konfligieren.

        Returns:
            Konflikt-Details oder None
        """
        params = CONFLICT_PARAMETERS.get(domain)
        if not params:
            return None

        threshold = domain_cfg.get("threshold", 0)

        if params["type"] == "numeric":
            key = params["key"]
            val_new = args_new.get(key)
            val_existing = args_existing.get(key)

            if val_new is None or val_existing is None:
                # Kein numerischer Vergleich moeglich, pruefe state
                also_check = params.get("also_check", [])
                for check_key in also_check:
                    v1 = args_new.get(check_key)
                    v2 = args_existing.get(check_key)
                    if v1 and v2 and v1 != v2:
                        return {
                            "type": "categorical",
                            "key": check_key,
                            "value_new": v1,
                            "value_existing": v2,
                        }
                return None

            try:
                diff = abs(float(val_new) - float(val_existing))
            except (ValueError, TypeError):
                return None

            if diff >= threshold:
                return {
                    "type": "numeric",
                    "key": key,
                    "value_new": val_new,
                    "value_existing": val_existing,
                    "difference": diff,
                    "unit": params.get("unit", ""),
                }

        elif params["type"] == "categorical":
            key = params["key"]
            val_new = args_new.get(key)
            val_existing = args_existing.get(key)

            if val_new and val_existing and val_new != val_existing:
                return {
                    "type": "categorical",
                    "key": key,
                    "value_new": val_new,
                    "value_existing": val_existing,
                }

        return None

    # ------------------------------------------------------------------
    # Konflikt-Loesung
    # ------------------------------------------------------------------

    async def _resolve_conflict(
        self,
        person_a: str,
        command_a: dict,
        person_b: str,
        function_name_b: str,
        args_b: dict,
        domain: str,
        domain_cfg: dict,
        room: Optional[str],
        conflict_detail: dict,
    ) -> dict:
        """Loest einen erkannten Konflikt."""
        strategy = domain_cfg.get("strategy", "trust_priority")

        trust_a = self.autonomy.get_trust_level(person_a)
        trust_b = self.autonomy.get_trust_level(person_b)
        trust_name_a = TRUST_LEVEL_NAMES.get(trust_a, "Unbekannt")
        trust_name_b = TRUST_LEVEL_NAMES.get(trust_b, "Unbekannt")

        resolution = {
            "conflict": True,
            "domain": domain,
            "room": room,
            "person_a": person_a,
            "person_a_trust": trust_a,
            "person_b": person_b,
            "person_b_trust": trust_b,
            "conflict_detail": conflict_detail,
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
        }

        # Strategie 1: Trust-Prioritaet
        if strategy == "trust_priority" and self._use_trust_priority:
            if trust_a != trust_b:
                winner = person_a if trust_a > trust_b else person_b
                loser = person_b if trust_a > trust_b else person_a
                winner_trust = max(trust_a, trust_b)
                loser_trust = min(trust_a, trust_b)
                winner_name = TRUST_LEVEL_NAMES.get(winner_trust, "")

                resolution["winner"] = winner
                resolution["loser"] = loser
                resolution["action"] = "use_winner_values"
                resolution["modified_args"] = args_b if winner == person_b else command_a["args"]
                resolution["message"] = (
                    f"Interessante Meinungsverschiedenheit bei {self._domain_label(domain)}"
                    f"{' im ' + room if room else ''}. "
                    f"{winner.title()} hat hier das letzte Wort — "
                    f"{self._describe_action(domain, resolution['modified_args'])}."
                )
            else:
                # Gleicher Trust -> Raum-Scoping: Wer ist im Raum?
                room_winner = self._resolve_by_room_presence(
                    person_a, person_b, room,
                )
                if room_winner:
                    winner = room_winner
                    loser = person_b if room_winner == person_a else person_a
                    resolution["winner"] = winner
                    resolution["loser"] = loser
                    resolution["action"] = "use_winner_values"
                    resolution["modified_args"] = (
                        command_a["args"] if winner == person_a else args_b
                    )
                    resolution["message"] = (
                        f"Gleiches Vertrauenslevel, aber {winner.title()} ist gerade "
                        f"{'im ' + room if room else 'naeher dran'}. "
                        f"Entscheidung: {self._describe_action(domain, resolution['modified_args'])}."
                    )
                    resolution["strategy"] = "room_presence"
                else:
                    # Kein Raum-Vorteil -> Fallback zu average oder mediate
                    strategy = "average" if conflict_detail["type"] == "numeric" else "mediate"

        # Strategie 2: Durchschnitt (nur numerisch)
        if strategy == "average" and conflict_detail["type"] == "numeric":
            key = conflict_detail["key"]
            val_a = float(conflict_detail["value_existing"])
            val_b = float(conflict_detail["value_new"])
            compromise = round((val_a + val_b) / 2, 1)
            unit = conflict_detail.get("unit", "")

            resolution["action"] = "use_compromise"
            resolution["compromise_value"] = compromise
            resolution["modified_args"] = {**args_b, key: compromise}
            resolution["message"] = (
                f"{person_a.title()} will {val_a}{unit}, "
                f"{person_b.title()} will {val_b}{unit}. "
                f"Ich nehme {compromise}{unit}. Diplomatie ist eine meiner Staerken."
            )

        # Strategie 3: LLM-Mediation
        if strategy == "mediate" and self._mediation_enabled:
            mediation_msg = await self._mediate(
                person_a=person_a,
                trust_a=trust_name_a,
                person_b=person_b,
                trust_b=trust_name_b,
                conflict_detail=conflict_detail,
                domain=domain,
                room=room,
            )
            resolution["action"] = "mediated"
            resolution["message"] = mediation_msg
            # Bei Mediation: Befehle des hoeheren Trust-Levels bevorzugen
            if trust_a >= trust_b:
                resolution["modified_args"] = command_a["args"]
            else:
                resolution["modified_args"] = args_b

        # Fallback-Message wenn keine Strategie gegriffen hat
        if "message" not in resolution:
            resolution["action"] = "notify_only"
            resolution["message"] = (
                f"{person_a.title()} und {person_b.title()} sind sich bei "
                f"{self._domain_label(domain)} nicht einig. "
                f"Ich halte mich da raus — regelt das unter euch."
            )

        return resolution

    async def _mediate(
        self,
        person_a: str,
        trust_a: str,
        person_b: str,
        trust_b: str,
        conflict_detail: dict,
        domain: str,
        room: Optional[str],
    ) -> str:
        """Erstellt einen LLM-basierten Mediations-Vorschlag."""
        # Konflikt-Beschreibung erstellen
        if conflict_detail["type"] == "numeric":
            desc = (
                f"{person_a.title()} moechte {conflict_detail['key']} auf "
                f"{conflict_detail['value_existing']}{conflict_detail.get('unit', '')} setzen. "
                f"{person_b.title()} moechte {conflict_detail['key']} auf "
                f"{conflict_detail['value_new']}{conflict_detail.get('unit', '')} setzen."
            )
        else:
            desc = (
                f"{person_a.title()} moechte {conflict_detail['key']}: "
                f"{conflict_detail['value_existing']}. "
                f"{person_b.title()} moechte {conflict_detail['key']}: "
                f"{conflict_detail['value_new']}."
            )

        # Tageszeit bestimmen
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_of_day = "Morgen"
        elif 12 <= hour < 18:
            time_of_day = "Nachmittag"
        elif 18 <= hour < 22:
            time_of_day = "Abend"
        else:
            time_of_day = "Nacht"

        # Wer hat hoehere Trust?
        trust_order = self.autonomy.get_trust_level
        a_trust_num = trust_order(person_a)
        b_trust_num = trust_order(person_b)

        if a_trust_num >= b_trust_num:
            higher_person, higher_trust = person_a.title(), trust_a
            lower_person, lower_trust = person_b.title(), trust_b
        else:
            higher_person, higher_trust = person_b.title(), trust_b
            lower_person, lower_trust = person_a.title(), trust_a

        prompt = MEDIATION_PROMPT.format(
            higher_trust_person=higher_person,
            higher_trust_level=higher_trust,
            lower_trust_person=lower_person,
            lower_trust_level=lower_trust,
            conflict_description=desc,
            room=room or "unbekannter Raum",
            time=datetime.now().strftime("%H:%M"),
            time_of_day=time_of_day,
        )

        try:
            response = await self.ollama.chat(
                model=self._mediation_model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": self._mediation_temperature,
                    "num_predict": self._mediation_max_tokens,
                },
            )
            mediation_text = response.get("message", {}).get("content", "").strip()
            if mediation_text:
                return mediation_text
        except Exception as e:
            logger.warning("LLM-Mediation fehlgeschlagen: %s", e)

        # Fallback
        return (
            f"{person_a.title()} und {person_b.title()} — zwei Meinungen, ein Raum. "
            f"Ich setze {self._domain_label(domain)} auf einen Mittelwert. Einwaende?"
        )

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _cleanup_old_commands(self):
        """Entfernt Befehle die aelter als das Zeitfenster sind."""
        cutoff = time.time() - self._conflict_window
        for person in list(self._recent_commands.keys()):
            self._recent_commands[person] = [
                cmd for cmd in self._recent_commands[person]
                if cmd["timestamp"] > cutoff
            ]
            if not self._recent_commands[person]:
                del self._recent_commands[person]

    def _domain_label(self, domain: str) -> str:
        """Gibt ein deutsches Label fuer eine Domain zurueck."""
        if domain == "climate":
            mode = yaml_config.get("heating", {}).get("mode", "room_thermostat")
            if mode == "heating_curve":
                return "den Heizungs-Offset"
            return "die Temperatur"
        labels = {
            "light": "das Licht",
            "media": "die Musik",
            "cover": "die Rolladen",
        }
        return labels.get(domain, domain)

    def _describe_action(self, domain: str, args: dict) -> str:
        """Beschreibt eine Aktion kurz auf Deutsch."""
        if domain == "climate":
            mode = yaml_config.get("heating", {}).get("mode", "room_thermostat")
            if mode == "heating_curve":
                offset = args.get("offset")
                if offset is not None:
                    return f"den Offset auf {offset}°C"
                return "den Offset entsprechend"
            temp = args.get("temperature")
            if temp:
                return f"die Temperatur auf {temp}°C"
            return "die Temperatur entsprechend"
        elif domain == "light":
            brightness = args.get("brightness")
            state = args.get("state")
            if state:
                return f"das Licht {state}"
            if brightness:
                return f"das Licht auf {brightness}%"
            return "das Licht entsprechend"
        elif domain == "media":
            action = args.get("action")
            return f"die Musik auf {action}" if action else "die Musik entsprechend"
        elif domain == "cover":
            position = args.get("position")
            return f"die Rolladen auf {position}%" if position else "die Rolladen entsprechend"
        return "es entsprechend"

    def _resolve_by_room_presence(
        self,
        person_a: str,
        person_b: str,
        room: Optional[str],
    ) -> Optional[str]:
        """Versucht bei gleicher Trust-Stufe ueber Raum-Naehe zu entscheiden.

        Prueft wer zuletzt im betroffenen Raum einen Befehl gegeben hat —
        wer im Raum ist, hat Vorrang.

        Returns:
            Name des Gewinners oder None (kein Entscheid moeglich)
        """
        if not room:
            return None

        room_lower = room.lower()
        now = time.time()

        # Letzten Befehl im selben Raum pro Person finden
        last_in_room_a = None
        last_in_room_b = None

        for cmd in reversed(self._recent_commands.get(person_a.lower(), [])):
            cmd_room = cmd.get("room") or cmd.get("args", {}).get("room", "")
            if cmd_room and cmd_room.lower() == room_lower:
                last_in_room_a = cmd["timestamp"]
                break

        for cmd in reversed(self._recent_commands.get(person_b.lower(), [])):
            cmd_room = cmd.get("room") or cmd.get("args", {}).get("room", "")
            if cmd_room and cmd_room.lower() == room_lower:
                last_in_room_b = cmd["timestamp"]
                break

        # Wer zuletzt im Raum aktiv war, hat Vorrang
        if last_in_room_a and not last_in_room_b:
            return person_a
        if last_in_room_b and not last_in_room_a:
            return person_b
        if last_in_room_a and last_in_room_b:
            # Wer aktueller ist = wahrscheinlich im Raum
            if last_in_room_a > last_in_room_b:
                return person_a
            elif last_in_room_b > last_in_room_a:
                return person_b

        return None  # Kein Entscheid moeglich

    async def _save_history(self):
        """Speichert Konflikt-History in Redis."""
        if not self._redis:
            return
        try:
            import json
            await self._redis.set(
                "mha:conflicts:history",
                json.dumps(self._conflict_history[-self._max_history:]),
            )
        except Exception as e:
            logger.debug("Konflikt-History speichern fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Status & Info
    # ------------------------------------------------------------------

    def get_recent_conflicts(self, limit: int = 10) -> list[dict]:
        """Gibt die letzten Konflikte zurueck."""
        return self._conflict_history[-limit:]

    def get_active_commands(self) -> dict:
        """Gibt die aktuell getrackte Befehle pro Person zurueck."""
        self._cleanup_old_commands()
        return {
            person: len(cmds)
            for person, cmds in self._recent_commands.items()
        }

    def health_status(self) -> str:
        """Gibt den Health-Status zurueck."""
        if not self.enabled:
            return "disabled"
        active_persons = len(self._recent_commands)
        total_conflicts = len(self._conflict_history)
        return f"active ({active_persons} personen, {total_conflicts} konflikte gesamt)"

    def get_info(self) -> dict:
        """Gibt detaillierte Infos zurueck."""
        return {
            "enabled": self.enabled,
            "conflict_window_seconds": self._conflict_window,
            "mediation_enabled": self._mediation_enabled,
            "use_trust_priority": self._use_trust_priority,
            "active_commands": self.get_active_commands(),
            "total_conflicts": len(self._conflict_history),
            "recent_conflicts": self.get_recent_conflicts(5),
            "monitored_domains": list(FUNCTION_DOMAIN_MAP.values()),
        }
