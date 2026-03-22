"""
ProactiveSequencePlanner — Multi-Step-Planung bei Kontext-Aenderungen.

Phase 18: MCU-Upgrade — Jarvis plant voraus bei:
- Person-Ankunft: Unlock → Licht → Klima → Willkommen
- Wetter-Aenderung: Fenster → Rollladen → Heizung anpassen
- Gaeste-Event: Vorbereitung → Licht → Musik → Tuer

Safety: Security-Aktionen (unlock, alarm) IMMER mit Bestaetigung,
egal welches Autonomie-Level.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Redis-Key-Prefix
_PREFIX = "mha:proactive_planner"


class ProactiveSequencePlanner:
    """Plant Multi-Step-Aktionen bei grossen Kontext-Aenderungen."""

    def __init__(self, ha, anticipation=None):
        """
        Args:
            ha: HomeAssistantClient-Instanz
            anticipation: AnticipationEngine fuer gelernte Ketten (optional)
        """
        self.ha = ha
        self.anticipation = anticipation
        self.redis: Optional[aioredis.Redis] = None

        cfg = yaml_config.get("proactive_planner", {})
        self.enabled = cfg.get("enabled", True)
        self.min_autonomy_for_auto = cfg.get("min_autonomy_for_auto", 4)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert den Planner mit Redis-Verbindung."""
        self.redis = redis_client
        if self.enabled:
            logger.info("ProactiveSequencePlanner initialisiert")

    async def plan_from_context_change(
        self,
        trigger: str,
        context: dict,
        autonomy_level: int = 2,
    ) -> Optional[dict]:
        """Erstellt einen Aktionsplan bei Kontext-Aenderung.

        Args:
            trigger: Art der Aenderung (person_arrived, weather_changed, calendar_event_soon)
            context: Aktueller Kontext-Dict
            autonomy_level: Aktuelles Autonomie-Level (1-5)

        Returns:
            Plan-Dict mit 'actions', 'message', 'needs_confirmation' oder None
        """
        if not self.enabled:
            return None

        # Cooldown pruefen (max 1 Plan pro 30 Min pro Trigger-Typ)
        if self.redis:
            cooldown_key = f"{_PREFIX}:cooldown:{trigger}"
            try:
                if await self.redis.exists(cooldown_key):
                    return None
            except Exception as e:
                logger.debug("Cooldown check failed: %s", e)

        plan = None

        if trigger == "person_arrived":
            person = context.get("person", {}).get("name", "")
            plan = await self._plan_arrival_sequence(person, context)
        elif trigger == "weather_changed":
            plan = await self._plan_weather_sequence(context)
        elif trigger == "calendar_event_soon":
            plan = await self._plan_guest_sequence(context)
        # F5: Erweiterte Trigger
        elif trigger == "person_left":
            plan = await self._plan_departure_sequence(context)
        elif trigger == "energy_price_changed":
            plan = await self._plan_energy_sequence(context)
        elif trigger == "bedtime_approaching":
            plan = await self._plan_bedtime_sequence(context)

        # Brücke: Gelernte Causal Chains aus anticipation.py einbeziehen
        if self.anticipation and plan:
            try:
                learned_actions = await self._enrich_plan_from_patterns(
                    plan,
                    trigger,
                    context,
                )
                if learned_actions:
                    plan["actions"].extend(learned_actions)
                    plan["message"] += " (inkl. gelernter Muster)"
            except Exception as e:
                logger.debug("Anticipation-Enrichment fehlgeschlagen: %s", e)

        if not plan:
            return None

        # Cooldown setzen
        if self.redis:
            try:
                await self.redis.setex(cooldown_key, 1800, "1")  # 30 Min
            except Exception as e:
                logger.debug("Cooldown set failed: %s", e)

        # Autonomie-Level bestimmt ob Auto-Ausfuehrung oder Frage
        auto_execute = autonomy_level >= self.min_autonomy_for_auto
        # Safety: Security-Aktionen NIE automatisch
        has_security_action = any(
            a.get("type") in ("unlock_door", "arm_security", "lock_door")
            for a in plan.get("actions", [])
        )
        if has_security_action:
            auto_execute = False

        plan["needs_confirmation"] = not auto_execute
        return plan

    async def _plan_arrival_sequence(
        self, person: str, context: dict
    ) -> Optional[dict]:
        """Person kommt nach Hause: Licht → Klima → Willkommen."""
        title = get_person_title(person)
        hour = datetime.now(_LOCAL_TZ).hour

        actions = []

        # Licht einschalten (wenn dunkel)
        if hour >= 17 or hour < 7:
            actions.append(
                {
                    "type": "set_light",
                    "args": {"state": "on", "brightness": 70},
                    "description": "Willkommens-Beleuchtung",
                }
            )

        # Klima anpassen (wenn Eco-Modus aktiv)
        house = context.get("house", {})
        climate = house.get("climate", [])
        eco_active = any(
            c.get("preset_mode") == "eco" or c.get("hvac_mode") == "off"
            for c in climate
            if isinstance(c, dict)
        )
        if eco_active:
            actions.append(
                {
                    "type": "set_climate",
                    "args": {"preset_mode": "home"},
                    "description": "Heizung auf Home-Modus",
                }
            )

        if not actions:
            return None

        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "person_arrived",
            "person": person,
            "actions": actions,
            "message": f"{title} kommt nach Hause. Soll ich {actions_desc}?",
            "auto_message": self._build_narrative(actions, person, "person_arrived"),
        }

    async def _plan_weather_sequence(self, context: dict) -> Optional[dict]:
        """Wetter aendert sich signifikant: Fenster/Rollladen/Heizung anpassen."""
        weather = context.get("weather", {})
        house = context.get("house", {})
        condition = str(weather.get("condition", "")).lower()
        open_windows = house.get("open_windows", [])

        actions = []
        title = get_person_title()

        # Regen/Sturm + Fenster offen
        rain_conditions = {"rainy", "pouring", "lightning-rainy", "lightning", "hail"}
        if condition in rain_conditions and open_windows:
            actions.append(
                {
                    "type": "notify",
                    "args": {
                        "message": f"Fenster {', '.join(open_windows[:3])} bei {condition} offen"
                    },
                    "description": f"Fenster-Warnung ({condition})",
                }
            )

        # Starker Regen → Rollladen-Schutz vorschlagen
        if condition in ("pouring", "hail", "lightning-rainy"):
            actions.append(
                {
                    "type": "set_cover",
                    "args": {"position": 0},
                    "description": "Rollladen als Schutz runterfahren",
                }
            )

        if not actions:
            return None

        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "weather_changed",
            "actions": actions,
            "message": f"{title}, Wetter aendert sich ({condition}). Soll ich {actions_desc}?",
            "auto_message": self._build_narrative(actions, "", "weather_changed"),
        }

    async def _plan_guest_sequence(self, context: dict) -> Optional[dict]:
        """Gaeste erwartet: Licht → Musik → Check."""
        title = get_person_title()

        actions = []
        hour = datetime.now(_LOCAL_TZ).hour

        # Angenehme Beleuchtung
        if hour >= 16 or hour < 8:
            actions.append(
                {
                    "type": "set_light",
                    "args": {"brightness": 80, "color_temp": "warm"},
                    "description": "Angenehme Beleuchtung",
                }
            )

        # Hintergrundmusik (immer bei Gaeste-Event)
        actions.append(
            {
                "type": "play_media",
                "args": {"content_type": "ambient"},
                "description": "Hintergrundmusik",
            }
        )

        if not actions:
            return None

        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "calendar_event_soon",
            "actions": actions,
            "message": f"{title}, Gaeste kommen bald. Soll ich {actions_desc} vorbereiten?",
            "auto_message": self._build_narrative(actions, "", "calendar_event_soon"),
        }

    async def _plan_departure_sequence(self, context: dict) -> Optional[dict]:
        """Person verlässt das Haus: Eco-Modus → Lichter aus → Sicherheit."""
        actions = []
        house = context.get("house", {})

        # Lichter ausschalten
        lights = house.get("lights_on", [])
        if lights:
            actions.append(
                {
                    "type": "set_light",
                    "args": {"state": "off"},
                    "description": "Alle Lichter ausschalten",
                }
            )

        # Offene Fenster schliessen
        open_windows = house.get("open_windows", [])
        if open_windows:
            actions.append(
                {
                    "type": "notify",
                    "args": {
                        "message": f"Noch offene Fenster: {', '.join(open_windows[:3])}"
                    },
                    "description": f"Fenster-Warnung ({len(open_windows)} offen)",
                }
            )

        # Medien stoppen
        active_media = house.get("media_playing", [])
        if active_media:
            actions.append(
                {
                    "type": "media_stop",
                    "args": {},
                    "description": "Laufende Medien stoppen",
                }
            )

        # Klima auf Eco
        actions.append(
            {
                "type": "set_climate",
                "args": {"preset_mode": "eco"},
                "description": "Heizung auf Eco-Modus",
            }
        )

        if not actions:
            return None

        title = get_person_title()
        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "person_left",
            "actions": actions,
            "message": f"{title} geht. Soll ich {actions_desc}?",
            "auto_message": self._build_narrative(actions, "", "person_left"),
        }

    async def _plan_energy_sequence(self, context: dict) -> Optional[dict]:
        """Strompreis aendert sich: Geraete verschieben oder starten."""
        energy = context.get("energy", {})
        price = energy.get("current_price")
        if not price:
            return None

        actions = []
        if price < energy.get("low_threshold", 0.15):
            actions.append(
                {
                    "type": "notify",
                    "args": {"message": f"Strom guenstig ({price:.1f} ct/kWh)"},
                    "description": "Guenstiger Strom — energieintensive Geraete starten",
                }
            )

        elif price > energy.get("high_threshold", 0.35):
            # Teurer Strom — verschiebbare Lasten pausieren
            actions.append(
                {
                    "type": "notify",
                    "args": {
                        "message": f"Strom teuer ({price:.2f} EUR/kWh) — verschiebbare Geraete pausieren empfohlen"
                    },
                    "description": "Strompreis-Warnung — Lasten verschieben",
                }
            )

        if not actions:
            return None

        return {
            "trigger": "energy_price_changed",
            "actions": actions,
            "message": actions[0]["description"],
            "auto_message": self._build_narrative(actions, "", "energy_price_changed"),
        }

    async def _plan_bedtime_sequence(self, context: dict) -> Optional[dict]:
        """Schlafenszeit naht: Lichter dimmen → Medien stoppen → Tuer pruefen."""
        actions = []

        actions.append(
            {
                "type": "set_light",
                "args": {"brightness": 20, "color_temp": "warmest"},
                "description": "Lichter dimmen",
            }
        )

        house = context.get("house", {})
        open_doors = house.get("open_doors", [])
        if open_doors:
            actions.append(
                {
                    "type": "notify",
                    "args": {
                        "message": f"Noch offene Tueren: {', '.join(open_doors[:3])}"
                    },
                    "description": "Offene Tueren melden",
                }
            )

        # Offene Fenster melden
        open_windows = house.get("open_windows", [])
        if open_windows:
            actions.append(
                {
                    "type": "notify",
                    "args": {
                        "message": f"Noch offene Fenster: {', '.join(open_windows[:3])}"
                    },
                    "description": "Offene Fenster vor dem Schlafengehen",
                }
            )

        # Medien stoppen
        active_media = house.get("media_playing", [])
        if active_media:
            actions.append(
                {
                    "type": "media_stop",
                    "args": {},
                    "description": "Laufende Medien stoppen",
                }
            )

        title = get_person_title()
        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "bedtime_approaching",
            "actions": actions,
            "message": f"Gute Nacht, {title}. Soll ich {actions_desc}?",
            "auto_message": self._build_narrative(actions, "", "bedtime"),
        }

    # ------------------------------------------------------------------
    # Narrative Builder — natuerliche Sprachausgabe fuer Sequenzen
    # ------------------------------------------------------------------

    # Verb-Mapping: Action-Type → deutscher Satzanfang
    _ACTION_VERBS: dict[str, str] = {
        "set_light": "schalte die Beleuchtung",
        "set_climate": "stelle die Heizung",
        "set_cover": "fahre die Rollaeden",
        "play_media": "starte die Musik",
        "media_stop": "stoppe die laufenden Medien",
        "notify": "",  # Benachrichtigungen separat
        "lock": "sichere die Schloeser",
    }

    def _build_narrative(
        self, actions: list[dict], person: str = "", trigger: str = ""
    ) -> str:
        """Baut eine natuerliche deutsche Narration fuer eine Multi-Step Sequenz.

        Verwandelt eine Liste von Aktionen in einen flüssigen Satz den
        Jarvis sprechen wuerde.

        Args:
            actions: Liste von Action-Dicts mit type, args, description
            person: Person fuer personalisierten Titel
            trigger: Trigger-Typ fuer kontextbezogenes Intro

        Returns:
            Natuerlicher deutscher Satz, z.B.
            "Sehr wohl, Sir. Ich schalte die Beleuchtung ein,
             stelle die Heizung auf Home-Modus und fahre die Rollaeden runter."
        """
        title = get_person_title(person)

        # Intro je nach Trigger
        intros = {
            "person_arrived": f"Willkommen zurueck, {title}.",
            "person_left": f"Abwesenheitsmodus aktiviert, {title}.",
            "weather_changed": f"Wetter-Anpassung, {title}.",
            "calendar_event_soon": f"Gaeste-Vorbereitung, {title}.",
            "bedtime": f"Gute Nacht, {title}.",
            "energy_price_changed": f"Energieoptimierung, {title}.",
        }
        intro = intros.get(trigger, f"Sehr wohl, {title}.")

        # Aktionen in Satzteile umwandeln (notify-Aktionen separat)
        parts = []
        notifications = []

        for action in actions:
            action_type = action.get("type", "")
            desc = action.get("description", "")

            if action_type == "notify":
                notifications.append(desc)
                continue

            verb = self._ACTION_VERBS.get(action_type, "")
            if verb:
                # Spezifische Args auswerten
                args = action.get("args", {})
                if action_type == "set_light":
                    if args.get("state") == "off":
                        parts.append("schalte die Lichter aus")
                    elif args.get("brightness"):
                        parts.append(f"dimme das Licht auf {args['brightness']}%")
                    else:
                        parts.append("schalte die Beleuchtung ein")
                elif action_type == "set_climate":
                    preset = args.get("preset_mode", "")
                    if preset:
                        parts.append(f"stelle die Heizung auf {preset.title()}-Modus")
                    else:
                        parts.append(desc.lower())
                elif action_type == "set_cover":
                    pos = args.get("position")
                    if pos == 0:
                        parts.append("fahre die Rollaeden runter")
                    elif pos == 100:
                        parts.append("fahre die Rollaeden hoch")
                    else:
                        parts.append(desc.lower())
                else:
                    parts.append(verb)
            elif desc:
                parts.append(desc.lower())

        if not parts:
            # Nur Benachrichtigungen — kein "erledigt" noetig
            if notifications:
                return f"{intro} Hinweis: {'; '.join(notifications)}."
            return f"{intro} {', '.join(a.get('description', '') for a in actions)}."

        # Natuerliche Verkettung: "A, B und C"
        if len(parts) == 1:
            actions_text = parts[0]
        elif len(parts) == 2:
            actions_text = f"{parts[0]} und {parts[1]}"
        else:
            actions_text = ", ".join(parts[:-1]) + f" und {parts[-1]}"

        narrative = f"{intro} Ich {actions_text}."

        # Notifications als Hinweis anhaengen
        if notifications:
            narrative += f" Hinweis: {'; '.join(notifications)}."

        return narrative

    async def _enrich_plan_from_patterns(
        self,
        plan: dict,
        trigger: str,
        context: dict,
    ) -> list[dict]:
        """Reichert einen Plan mit gelernten Mustern aus anticipation.py an.

        Sucht passende Causal Chains die zum Trigger und Kontext passen
        und fuegt sie als zusaetzliche Aktionen hinzu.
        """
        if not self.anticipation or not hasattr(self.anticipation, "detect_patterns"):
            return []

        person = context.get("person", {}).get("name", "")
        patterns = await self.anticipation.detect_patterns(person=person)

        # Nur Causal Chains mit hoher Confidence nutzen
        learned_actions = []
        existing_functions = {a.get("function") for a in plan.get("actions", [])}

        for pattern in patterns:
            if pattern.get("type") != "causal_chain":
                continue
            if pattern.get("confidence", 0) < 0.8:
                continue

            # Aktionen aus der Chain die noch nicht im Plan sind
            chain_actions = pattern.get("chain_actions", [])
            for chain_action in chain_actions:
                func_name = chain_action.get("action", "")
                if func_name and func_name not in existing_functions:
                    learned_actions.append(
                        {
                            "function": func_name,
                            "args": chain_action.get("args", {}),
                            "type": "learned_pattern",
                            "confidence": pattern["confidence"],
                        }
                    )
                    existing_functions.add(func_name)

        return learned_actions[:5]  # Max 5 zusaetzliche Aktionen

    async def get_status(self) -> dict:
        """Gibt den Status des Planners zurueck."""
        status = {
            "enabled": self.enabled,
            "min_autonomy_for_auto": self.min_autonomy_for_auto,
        }

        if self.redis:
            try:
                cursor = 0
                active_cooldowns = 0
                while True:
                    cursor, keys = await self.redis.scan(
                        cursor,
                        match=f"{_PREFIX}:cooldown:*",
                        count=50,
                    )
                    active_cooldowns += len(keys)
                    if cursor == 0:
                        break
                status["active_cooldowns"] = active_cooldowns
            except Exception as e:
                logger.warning("Cooldown scan failed: %s", e)
                status["active_cooldowns"] = -1

        return status
