"""
Conflict Resolver - Phase 16.1: Multi-User Konfliktloesung.

Erkennt und loest Konflikte wenn mehrere Personen widersprüchliche
Befehle geben. Nutzt Trust-Levels für Priorität und bietet
LLM-basierte Mediations-Vorschläge.

Beispiel-Konflikte:
  - Person A: "Mach es wärmer" vs Person B: "Mach es kälter"
  - Person A: "Licht aus" vs Person B: "Licht an"
  - Person A: "Musik leiser" vs Person B: "Musik lauter"

Lösungsstrategien:
  1. trust_priority: Höhere Trust-Stufe gewinnt
  2. average: Kompromiss (Durchschnitt bei numerischen Werten)
  3. mediate: LLM schlägt Kompromiss vor und erklärt
"""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .config import settings, yaml_config
from .autonomy import AutonomyManager, TRUST_LEVEL_NAMES
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))


# Welche Funktionen zu welcher Konflikt-Domain gehoeren
FUNCTION_DOMAIN_MAP = {
    "set_climate": "climate",
    "set_light": "light",
    "play_media": "media",
    "set_cover": "cover",
}

# Welche Parameter bei Konflikten verglichen werden
def _get_climate_conflict_params() -> dict:
    """Liefert Konflikt-Parameter je nach Heizungsmodus (live aus Config)."""
    from .config import yaml_config as cfg
    mode = cfg.get("heating", {}).get("mode", "room_thermostat")
    if mode == "heating_curve":
        return {"key": "offset", "unit": "°C", "type": "numeric"}
    return {"key": "temperature", "unit": "°C", "type": "numeric"}


def get_conflict_parameters() -> dict:
    """Liefert Konflikt-Parameter mit aktuellem Climate-Modus."""
    return {
        "climate": _get_climate_conflict_params(),
        "light": _CONFLICT_PARAMS_STATIC["light"],
        "media": _CONFLICT_PARAMS_STATIC["media"],
        "cover": _CONFLICT_PARAMS_STATIC["cover"],
    }


_CONFLICT_PARAMS_STATIC = {
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
MEDIATION_PROMPT = """Du bist {assistant_name} — die KI dieses Hauses. Vorbild: J.A.R.V.I.S. aus dem MCU.
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
        self._conflict_window = int(cfg.get("conflict_window_seconds", 300))
        self._max_commands = int(cfg.get("max_commands_per_person", 20))
        self._use_trust_priority = cfg.get("use_trust_priority", True)
        self._resolution_cooldown = int(cfg.get("resolution_cooldown_seconds", 120))

        # Mediations-Config
        med_cfg = cfg.get("mediation", {})
        self._mediation_enabled = med_cfg.get("enabled", True)
        from .config import resolve_model
        self._mediation_model = resolve_model(med_cfg.get("model", ""), fallback_tier="deep")
        self._mediation_max_tokens = int(med_cfg.get("max_tokens", 256))
        self._mediation_temperature = med_cfg.get("temperature", 0.7)

        # Domain-spezifische Konfiguration
        self._domain_configs: dict[str, dict] = cfg.get("conflict_domains", {})

        # Konfigurierbare Kontext-Schwellwerte (F-090 Review)
        ctx_cfg = cfg.get("context_thresholds", {})
        self._threshold_solar_w = float(ctx_cfg.get("solar_producing_w", 100))
        self._threshold_lux = float(ctx_cfg.get("high_lux", 500))
        self._threshold_wind_kmh = float(ctx_cfg.get("high_wind_kmh", 60))
        self._threshold_energy_price = float(ctx_cfg.get("high_energy_price", 0.30))
        self._threshold_frost_c = float(ctx_cfg.get("frost_below_c", 0))
        self._weather_entity = ctx_cfg.get("weather_entity", "weather.home")

        # Konfigurierbare Regel-Toggles: einzelne Regeln deaktivierbar
        self._rules_enabled: dict[str, bool] = cfg.get("rules_enabled", {})

        # Konfigurierbare Safe-Limits (Fallback: hardcoded)
        _DEFAULT_SAFE_LIMITS = {
            "climate": {"temperature": (15.0, 28.0), "offset": (-3.0, 3.0)},
            "light": {"brightness": (0, 100)},
            "cover": {"position": (0, 100)},
            "media": {"volume": (0, 100)},
        }
        raw_limits = cfg.get("safe_limits")
        if raw_limits and isinstance(raw_limits, dict):
            self._safe_limits = {}
            for domain, params in raw_limits.items():
                self._safe_limits[domain] = {}
                for param, val in params.items():
                    if isinstance(val, list) and len(val) == 2:
                        self._safe_limits[domain][param] = (float(val[0]), float(val[1]))
                    else:
                        self._safe_limits[domain][param] = val
        else:
            self._safe_limits = _DEFAULT_SAFE_LIMITS

        # State: Letzte Befehle pro Person
        self._recent_commands: dict[str, list[dict]] = defaultdict(list)
        self._commands_lock = __import__('threading').Lock()
        # State: Letzte Konfliktloesungen (Cooldown)
        self._last_resolutions: dict[str, float] = {}
        # State: Konflikt-History
        self._conflict_history: list[dict] = []
        self._max_history = 50

        # Prediction-Config
        self._prediction_enabled = cfg.get("prediction_enabled", False)
        self._prediction_window_seconds = int(cfg.get("prediction_window_seconds", 180))

        # Validator für Kompromiss-Werte (kann später gesetzt werden)
        self._validator = None

        # Redis für Persistenz
        self._redis = None

        logger.info(
            "ConflictResolver initialisiert (enabled: %s, window: %ds, "
            "mediation: %s)",
            self.enabled, self._conflict_window, self._mediation_enabled,
        )

    def reload_config(self):
        """Lädt konfigurierbare Werte aus settings.yaml neu (Hot-Reload bei UI-Änderungen)."""
        cfg = yaml_config.get("conflict_resolution", {})
        self.enabled = cfg.get("enabled", True)
        self._conflict_window = int(cfg.get("conflict_window_seconds", 300))
        self._use_trust_priority = cfg.get("use_trust_priority", True)
        self._cooldown_seconds = int(cfg.get("resolution_cooldown_seconds", 120))

        # Kontext-Schwellwerte aktualisieren
        ctx_cfg = cfg.get("context_thresholds", {})
        self._threshold_solar_w = float(ctx_cfg.get("solar_producing_w", 100))
        self._threshold_lux = float(ctx_cfg.get("high_lux", 500))
        self._threshold_wind_kmh = float(ctx_cfg.get("high_wind_kmh", 60))
        self._threshold_energy_price = float(ctx_cfg.get("high_energy_price", 0.30))
        self._threshold_frost_c = float(ctx_cfg.get("frost_below_c", 0))
        self._weather_entity = ctx_cfg.get("weather_entity", "weather.home")

        # Regel-Toggles aktualisieren
        self._rules_enabled = cfg.get("rules_enabled", {})

        # Prediction-Config aktualisieren
        self._prediction_enabled = cfg.get("prediction_enabled", False)
        self._prediction_window_seconds = int(cfg.get("prediction_window_seconds", 180))

        logger.info("ConflictResolver config reloaded (enabled=%s, prediction=%s, rules_enabled=%d custom)",
                     self.enabled, self._prediction_enabled, len(self._rules_enabled))

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
        Zeichnet einen ausgeführten Befehl einer Person auf.

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
            "datetime": datetime.now(timezone.utc).isoformat(),
        }

        person_key = person.lower()
        with self._commands_lock:
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
        Prueft ob ein neuer Befehl mit einem kürzlichen Befehl einer
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
            return None  # Nur überwachte Domains prüfen

        # Domain-Konfiguration
        domain_cfg = self._domain_configs.get(domain, {})

        person_lower = person.lower()
        now = time.time()

        # Alle kürzlichen Befehle anderer Personen in derselben Domain prüfen
        with self._commands_lock:
            snapshot = dict(self._recent_commands)
        for other_person, commands in snapshot.items():
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

                # Resolution-Cooldown prüfen
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
                # Periodic cleanup: keep only recent resolutions
                if len(self._last_resolutions) > 200:
                    cutoff = now - 86400  # 24h
                    self._last_resolutions = {
                        k: v for k, v in self._last_resolutions.items() if v > cutoff
                    }

                # History speichern
                self._conflict_history.append(resolution)
                if len(self._conflict_history) > self._max_history:
                    self._conflict_history = self._conflict_history[-self._max_history:]
                _t = asyncio.create_task(self._save_history())
                _t.add_done_callback(
                    lambda t: logger.warning("_save_history fehlgeschlagen: %s", t.exception())
                    if t.exception() else None
                )

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
        params = get_conflict_parameters().get(domain)
        if not params:
            return None

        threshold = domain_cfg.get("threshold", 2)

        if params["type"] == "numeric":
            key = params["key"]
            val_new = args_new.get(key)
            val_existing = args_existing.get(key)

            if val_new is None or val_existing is None:
                # Kein numerischer Vergleich möglich, pruefe state
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

        # Device-Dependency-Check: Pruefen ob eine Seite Konflikte ausloest
        dep_hints_a = []
        dep_hints_b = []
        try:
            from .state_change_log import StateChangeLog
            import assistant.main as main_module
            if hasattr(main_module, "brain"):
                _states = await main_module.brain.ha.get_states() or []
                dep_hints_a = StateChangeLog.check_action_dependencies(
                    command_a.get("function", ""), command_a.get("args", {}), _states,
                )
                dep_hints_b = StateChangeLog.check_action_dependencies(
                    function_name_b, args_b, _states,
                )
        except Exception as _dep_err:
            logger.debug("Dependency-Check in ConflictResolver: %s", _dep_err)

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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Dependency-Hinweise an Resolution anfuegen
        if dep_hints_a or dep_hints_b:
            resolution["dependency_hints"] = {
                "person_a": dep_hints_a,
                "person_b": dep_hints_b,
            }
            # Wenn nur eine Seite Konflikte hat, bevorzuge die andere
            if dep_hints_a and not dep_hints_b:
                resolution["dependency_recommendation"] = person_b
            elif dep_hints_b and not dep_hints_a:
                resolution["dependency_recommendation"] = person_a

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
                        f"{'im ' + room if room else 'näher dran'}. "
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

            # F-054: Kompromiss durch Validator lassen (Limits erzwingen)
            limits = self._safe_limits.get(domain, {}).get(key)
            if limits:
                min_val, max_val = limits
                if compromise < min_val or compromise > max_val:
                    old_compromise = compromise
                    compromise = max(min_val, min(max_val, compromise))
                    logger.warning(
                        "F-054: Kompromiss %s%s geclampt auf %s%s (Limits: %s-%s)",
                        old_compromise, unit, compromise, unit, min_val, max_val,
                    )
            if hasattr(self, '_validator') and self._validator:
                test_args = {**args_b, key: compromise}
                validation = self._validator.validate(f"set_{domain}", test_args)
                if not validation.ok:
                    logger.warning(
                        "F-054: Kompromiss %s%s Validierung fehlgeschlagen: %s — verwende höher-Trust-Wert",
                        compromise, unit, validation.reason,
                    )
                    # F-054: Bei ungültigem Kompromiss den Wert des höher vertrauenswuerdigen Users nehmen
                    compromise = val_a if trust_a >= trust_b else val_b

            resolution["action"] = "use_compromise"
            resolution["compromise_value"] = compromise
            resolution["modified_args"] = {**args_b, key: compromise}
            resolution["message"] = (
                f"{person_a.title()} will {val_a}{unit}, "
                f"{person_b.title()} will {val_b}{unit}. "
                f"Ich nehme {compromise}{unit}. Diplomatie ist eine meiner Stärken."
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
            # Bei Mediation: Befehle des höheren Trust-Levels bevorzugen
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
                f"{person_a.title()} möchte {conflict_detail['key']} auf "
                f"{conflict_detail['value_existing']}{conflict_detail.get('unit', '')} setzen. "
                f"{person_b.title()} möchte {conflict_detail['key']} auf "
                f"{conflict_detail['value_new']}{conflict_detail.get('unit', '')} setzen."
            )
        else:
            desc = (
                f"{person_a.title()} möchte {conflict_detail['key']}: "
                f"{conflict_detail['value_existing']}. "
                f"{person_b.title()} möchte {conflict_detail['key']}: "
                f"{conflict_detail['value_new']}."
            )

        # Tageszeit bestimmen
        hour = datetime.now(_LOCAL_TZ).hour
        if 5 <= hour < 12:
            time_of_day = "Morgen"
        elif 12 <= hour < 18:
            time_of_day = "Nachmittag"
        elif 18 <= hour < 22:
            time_of_day = "Abend"
        else:
            time_of_day = "Nacht"

        # Wer hat höhere Trust?
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
            assistant_name=settings.assistant_name,
            higher_trust_person=higher_person,
            higher_trust_level=higher_trust,
            lower_trust_person=lower_person,
            lower_trust_level=lower_trust,
            conflict_description=desc,
            room=room or "unbekannter Raum",
            time=datetime.now(_LOCAL_TZ).strftime("%H:%M"),
            time_of_day=time_of_day,
        )

        try:
            response = await self.ollama.chat(
                model=self._mediation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._mediation_temperature,
                max_tokens=self._mediation_max_tokens,
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
        """Gibt ein deutsches Label für eine Domain zurück."""
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
            return f"die Rolladen auf {position}%" if position is not None else "die Rolladen entsprechend"
        return "es entsprechend"

    def _resolve_by_room_presence(
        self,
        person_a: str,
        person_b: str,
        room: Optional[str],
    ) -> Optional[str]:
        """Versucht bei gleicher Trust-Stufe über Raum-Naehe zu entscheiden.

        Prueft wer zuletzt im betroffenen Raum einen Befehl gegeben hat —
        wer im Raum ist, hat Vorrang.

        Returns:
            Name des Gewinners oder None (kein Entscheid möglich)
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

        return None  # Kein Entscheid möglich

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
        """Gibt die letzten Konflikte zurück."""
        return self._conflict_history[-limit:]

    def get_active_commands(self) -> dict:
        """Gibt die aktuell getrackte Befehle pro Person zurück."""
        self._cleanup_old_commands()
        return {
            person: len(cmds)
            for person, cmds in self._recent_commands.items()
        }

    def health_status(self) -> str:
        """Gibt den Health-Status zurück."""
        if not self.enabled:
            return "disabled"
        active_persons = len(self._recent_commands)
        total_conflicts = len(self._conflict_history)
        return f"active ({active_persons} personen, {total_conflicts} konflikte gesamt)"

    def get_info(self) -> dict:
        """Gibt detaillierte Infos zurück."""
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

    # ------------------------------------------------------------------
    # Phase 2B: Multi-User Conflict Prediction
    # ------------------------------------------------------------------

    async def predict_conflict(
        self,
        person: str,
        domain: str,
        room: str,
        args: dict,
    ) -> Optional[dict]:
        """Sagt voraus ob ein geplanter Befehl mit kuerzlichen Befehlen
        anderer Personen im selben Raum/Domain kollidieren wird.

        Args:
            person: Name der Person die den Befehl ausfuehren will.
            domain: Domain (z.B. "climate", "light").
            room: Raum in dem der Befehl ausgefuehrt wird.
            args: Argumente des geplanten Befehls.

        Returns:
            Warning-Dict oder None wenn kein Konflikt vorhergesagt.
        """
        cfg = yaml_config.get("conflict_resolution", {})
        if not cfg.get("prediction_enabled", False):
            return None

        if not person or not domain:
            return None

        prediction_window = int(cfg.get("prediction_window_seconds", 180))
        person_lower = person.lower()
        room_lower = room.lower() if room else ""
        now = time.time()
        params = get_conflict_parameters().get(domain)

        with self._commands_lock:
            snapshot = dict(self._recent_commands)

        for other_person, commands in snapshot.items():
            if other_person == person_lower:
                continue

            for cmd in reversed(commands):
                age = now - cmd["timestamp"]
                if age > prediction_window:
                    continue

                other_domain = FUNCTION_DOMAIN_MAP.get(cmd["function"])
                if other_domain != domain:
                    continue

                cmd_room = cmd.get("room") or cmd["args"].get("room", "")
                if room_lower and cmd_room and cmd_room.lower() != room_lower:
                    continue

                if not params:
                    continue

                contradicts = False
                if params["type"] == "numeric":
                    key = params["key"]
                    val_new = args.get(key)
                    val_existing = cmd["args"].get(key)
                    if val_new is not None and val_existing is not None:
                        try:
                            if float(val_new) != float(val_existing):
                                contradicts = True
                        except (ValueError, TypeError):
                            pass
                    for check_key in params.get("also_check", []):
                        v_new = args.get(check_key)
                        v_old = cmd["args"].get(check_key)
                        if v_new and v_old and v_new != v_old:
                            contradicts = True
                elif params["type"] == "categorical":
                    key = params["key"]
                    v_new = args.get(key)
                    v_old = cmd["args"].get(key)
                    if v_new and v_old and v_new != v_old:
                        contradicts = True

                if not contradicts:
                    continue

                time_ago = int(age)
                minutes = time_ago // 60
                if minutes >= 1:
                    time_label = f"vor {minutes} Min."
                else:
                    time_label = f"vor {time_ago} Sek."

                detail_parts = []
                if params["type"] == "numeric":
                    key = params["key"]
                    val = cmd["args"].get(key)
                    unit = params.get("unit", "")
                    if val is not None:
                        detail_parts.append(f"auf {val}{unit}")
                elif params["type"] == "categorical":
                    key = params["key"]
                    val = cmd["args"].get(key)
                    if val:
                        detail_parts.append(str(val))

                detail_str = " ".join(detail_parts)
                warning_text = (
                    f"{other_person.title()} hat {time_label} "
                    f"{detail_str} gestellt"
                ).strip()

                logger.info(
                    "Conflict prediction: %s vs %s in %s/%s (%ds ago)",
                    person_lower, other_person, domain, room or "?", time_ago,
                )

                return {
                    "warning": warning_text,
                    "person": other_person,
                    "time_ago_seconds": time_ago,
                    "their_args": cmd["args"],
                }

        return None

    # ------------------------------------------------------------------
    # Phase 2B: Predictive Logical Conflict Detection
    # ------------------------------------------------------------------

    async def predict_logical_conflict(
        self, action: str, args: dict, ha_states: list
    ) -> Optional[dict]:
        """Prueft ob eine geplante Aktion einen logischen Konflikt verursacht.

        Vergleicht die Aktion gegen bekannte Konfliktregeln und den
        aktuellen HA-State.

        Args:
            action: Name der geplanten Aktion (z.B. "set_climate").
            args: Argumente der Aktion.
            ha_states: Liste von HA-State-Dicts mit entity_id und state.

        Returns:
            Dict mit type, warning, severity, suggestion oder None.
        """
        if not self.enabled:
            return None

        if not isinstance(ha_states, list):
            return None

        # Index fuer schnellen Zugriff
        state_map: dict[str, str] = {}
        for s in ha_states:
            if not isinstance(s, dict):
                continue
            eid = s.get("entity_id", "")
            state_map[eid] = s.get("state", "")

        for rule in _LOGICAL_CONFLICT_RULES:
            if rule["action"] != action:
                continue

            ctx = rule["context"]

            # Regel deaktiviert? → überspringen
            if not self._rules_enabled.get(ctx, True):
                continue

            matched = False

            if ctx == "window_open":
                matched = any(
                    state_map.get(eid) == "on"
                    for eid in state_map
                    if eid.startswith("binary_sensor.") and "window" in eid
                )
            elif ctx == "solar_producing":
                for eid, val in state_map.items():
                    if eid.startswith("sensor.") and "solar" in eid:
                        try:
                            if float(val) > self._threshold_solar_w:
                                matched = True
                                break
                        except (ValueError, TypeError):
                            continue
            elif ctx == "high_lux":
                for eid, val in state_map.items():
                    if eid.startswith("sensor.") and "lux" in eid:
                        try:
                            if float(val) > self._threshold_lux:
                                matched = True
                                break
                        except (ValueError, TypeError):
                            continue
            elif ctx == "nobody_home":
                person_entities = [
                    eid for eid in state_map if eid.startswith("person.")
                ]
                if person_entities and all(
                    state_map.get(eid) == "not_home" for eid in person_entities
                ):
                    matched = True
            elif ctx == "cooling_and_heating":
                # Klimaanlage kuehlt waehrend Heizung heizt — nur im gleichen Bereich
                # Bereich wird aus friendly_name oder area extrahiert
                climate_actions = {}  # area_hint -> list of (eid, hvac_action)
                for eid, val in state_map.items():
                    if eid.startswith("climate."):
                        attrs = next((s.get("attributes", {}) for s in ha_states
                                      if s.get("entity_id") == eid), {})
                        hvac = attrs.get("hvac_action", val)
                        if hvac in ("cooling", "heating"):
                            # Bereich-Hint aus Entity-ID oder Area extrahieren
                            area = attrs.get("area_id", "") or eid.split(".")[-1].rsplit("_", 1)[0]
                            climate_actions.setdefault(area, []).append((eid, hvac))
                # Konflikt nur wenn im gleichen Bereich gegenläufig
                for area, devices in climate_actions.items():
                    actions_set = {hvac for _, hvac in devices}
                    if "cooling" in actions_set and "heating" in actions_set:
                        matched = True
                        break
            elif ctx == "goodnight_active":
                matched = any(
                    state_map.get(eid) == "on"
                    for eid in state_map
                    if "goodnight" in eid or "gute_nacht" in eid or "schlafmodus" in eid
                )
            elif ctx == "high_wind":
                for eid, val in state_map.items():
                    if eid.startswith("sensor.") and ("wind" in eid and "speed" in eid):
                        try:
                            if float(val) > self._threshold_wind_kmh:
                                matched = True
                                break
                        except (ValueError, TypeError):
                            continue
            elif ctx == "door_open":
                matched = any(
                    state_map.get(eid) == "on"
                    for eid in state_map
                    if eid.startswith("binary_sensor.") and ("door" in eid or "tuer" in eid)
                )
            elif ctx == "sleeping_detected":
                matched = any(
                    state_map.get(eid) == "on"
                    for eid in state_map
                    if "sleep" in eid or "schlaf" in eid or "goodnight" in eid
                    or "gute_nacht" in eid or "bett" in eid or "nachtmodus" in eid
                )
            elif ctx == "rain_detected":
                weather = state_map.get(self._weather_entity, "")
                matched = weather in ("rainy", "pouring", "lightning-rainy", "hail", "rain", "thunderstorm")
            elif ctx == "frost_detected":
                for eid, val in state_map.items():
                    if eid.startswith("sensor.") and "temperature" in eid and ("outdoor" in eid or "aussen" in eid or "außen" in eid):
                        try:
                            if float(val) < self._threshold_frost_c:
                                matched = True
                                break
                        except (ValueError, TypeError):
                            continue
            elif ctx == "high_energy_price":
                for eid, val in state_map.items():
                    if "price" in eid or "tarif" in eid or "strom" in eid:
                        try:
                            if float(val) > self._threshold_energy_price:
                                matched = True
                                break
                        except (ValueError, TypeError):
                            continue
            elif ctx == "media_playing":
                matched = any(
                    state_map.get(eid) == "playing"
                    for eid in state_map
                    if eid.startswith("media_player.")
                )
            elif ctx == "window_scheduled_open":
                # Lueften geplant: Timer oder Automation aktiv
                matched = any(
                    state_map.get(eid) == "on"
                    for eid in state_map
                    if "lueft" in eid or "ventilat" in eid
                )

            if matched:
                return {
                    "type": ctx,
                    "warning": rule["warning"],
                    "severity": rule["severity"],
                    "suggestion": self._warn_before_action(rule["warning"]),
                }

        return None

    def _warn_before_action(self, warning: str) -> str:
        """Formatiert eine Warnung als Jarvis-style Pushback.

        Args:
            warning: Die Warnmeldung.

        Returns:
            Formatierter Pushback-String im Butler-Stil.
        """
        return (
            f"Sir, ein Hinweis bevor ich fortfahre: {warning}. "
            "Soll ich trotzdem fortfahren?"
        )


# ------------------------------------------------------------------
# Logical Conflict Rules — statische Regeldefinitionen
# ------------------------------------------------------------------

_LOGICAL_CONFLICT_RULES = [
    {
        "action": "set_climate",
        "context": "window_open",
        "warning": "Fenster offen — Energieverschwendung",
        "severity": "info",
    },
    {
        "action": "set_cover",
        "context": "solar_producing",
        "warning": "Solar produziert — Rolllaeden besser offen lassen",
        "severity": "info",
    },
    {
        "action": "set_light",
        "context": "high_lux",
        "warning": "Tageslicht ausreichend",
        "severity": "low",
    },
    {
        "action": "set_climate",
        "context": "nobody_home",
        "warning": "Niemand zuhause — Eco-Modus empfohlen",
        "severity": "info",
    },
    # --- Erweiterte Konfliktregeln ---
    {
        "action": "set_climate",
        "context": "cooling_and_heating",
        "warning": "Klimaanlage und Heizung widersprechen sich — bitte Modus pruefen",
        "severity": "warning",
    },
    {
        "action": "set_light",
        "context": "goodnight_active",
        "warning": "Gute-Nacht-Routine aktiv — Licht einschalten widerspricht Schlafmodus",
        "severity": "info",
    },
    {
        "action": "set_cover",
        "context": "high_wind",
        "warning": "Starker Wind — Rolllaeden/Markisen besser geschlossen lassen",
        "severity": "warning",
    },
    {
        "action": "set_climate",
        "context": "door_open",
        "warning": "Tuer offen — Heizen/Kuehlen ineffizient",
        "severity": "info",
    },
    {
        "action": "play_media",
        "context": "sleeping_detected",
        "warning": "Schlafenszeit erkannt — Medien abspielen koennte Bewohner stoeren",
        "severity": "info",
    },
    {
        "action": "set_light",
        "context": "nobody_home",
        "warning": "Niemand zuhause — Licht einschalten unnoetig",
        "severity": "low",
    },
    {
        "action": "set_cover",
        "context": "rain_detected",
        "warning": "Regen erkannt — Markisen/Fenster besser geschlossen halten",
        "severity": "info",
    },
    {
        "action": "set_cover",
        "context": "frost_detected",
        "warning": "Frost — Rolllaeden geschlossen lassen fuer Waermedaemmung",
        "severity": "info",
    },
    {
        "action": "set_climate",
        "context": "high_energy_price",
        "warning": "Strompreis hoch — Klimatisierung vertagen oder reduzieren",
        "severity": "info",
    },
    {
        "action": "set_vacuum",
        "context": "sleeping_detected",
        "warning": "Schlafenszeit erkannt — Staubsauger koennte Bewohner stoeren",
        "severity": "info",
    },
    {
        "action": "set_light",
        "context": "media_playing",
        "warning": "Medien werden abgespielt — helles Licht koennte Filmerlebnis stoeren",
        "severity": "low",
    },
    {
        "action": "set_climate",
        "context": "window_scheduled_open",
        "warning": "Lueften geplant — Heizung vorher reduzieren spart Energie",
        "severity": "low",
    },
    # --- Neue Regeln: Schlaf, Energie, Komfort ---
    {
        "action": "set_climate",
        "context": "sleeping_detected",
        "warning": "Schlafenszeit erkannt — Temperaturänderung koennte Bewohner stoeren",
        "severity": "info",
    },
    {
        "action": "set_cover",
        "context": "media_playing",
        "warning": "Medien werden abgespielt — Rollladen oeffnen koennte Filmerlebnis stoeren",
        "severity": "low",
    },
    {
        "action": "set_vacuum",
        "context": "media_playing",
        "warning": "Medien werden abgespielt — Staubsauger koennte stoeren",
        "severity": "info",
    },
    {
        "action": "set_light",
        "context": "sleeping_detected",
        "warning": "Schlafenszeit erkannt — Licht einschalten koennte Bewohner wecken",
        "severity": "info",
    },
    {
        "action": "set_climate",
        "context": "frost_detected",
        "warning": "Frost erkannt — Kuehlen nicht sinnvoll, Heizschutz beachten",
        "severity": "warning",
    },
    {
        "action": "set_cover",
        "context": "nobody_home",
        "warning": "Niemand zuhause — Rollladen oeffnen koennte Sicherheitsrisiko sein",
        "severity": "low",
    },
]
