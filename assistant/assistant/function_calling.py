"""
Function Calling - Definiert und fuehrt Funktionen aus die der Assistent nutzen kann.
MindHome Assistant ruft ueber diese Funktionen Home Assistant Aktionen aus.

Phase 10: Room-aware TTS, Person Messaging, Trust-Level Pre-Check.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import settings, yaml_config
from .config_versioning import ConfigVersioning
from .ha_client import HomeAssistantClient

# Config-Pfade fuer Phase 13.1 (Whitelist — nur diese darf Jarvis aendern)
_CONFIG_DIR = Path(__file__).parent.parent / "config"
_EDITABLE_CONFIGS = {
    "easter_eggs": _CONFIG_DIR / "easter_eggs.yaml",
    "opinion_rules": _CONFIG_DIR / "opinion_rules.yaml",
    "room_profiles": _CONFIG_DIR / "room_profiles.yaml",
}

logger = logging.getLogger(__name__)


def _get_heating_mode() -> str:
    """Liefert den konfigurierten Heizungsmodus."""
    return yaml_config.get("heating", {}).get("mode", "room_thermostat")


def _get_climate_tool_description() -> str:
    """Dynamische Tool-Beschreibung je nach Heizungsmodus."""
    if _get_heating_mode() == "heating_curve":
        return (
            "Heizung steuern: Vorlauftemperatur-Offset zur Heizkurve anpassen. "
            "Positiver Offset = waermer, negativer Offset = kaelter."
        )
    return "Temperatur in einem Raum aendern"


def _get_climate_tool_parameters() -> dict:
    """Dynamische Tool-Parameter je nach Heizungsmodus."""
    if _get_heating_mode() == "heating_curve":
        heating = yaml_config.get("heating", {})
        omin = heating.get("curve_offset_min", -5)
        omax = heating.get("curve_offset_max", 5)
        return {
            "type": "object",
            "properties": {
                "offset": {
                    "type": "number",
                    "description": f"Offset zur Heizkurve in Grad Celsius ({omin} bis {omax})",
                },
                "mode": {
                    "type": "string",
                    "enum": ["heat", "cool", "auto", "off"],
                    "description": "Heizmodus (optional)",
                },
            },
            "required": ["offset"],
        }
    return {
        "type": "object",
        "properties": {
            "room": {
                "type": "string",
                "description": "Raumname",
            },
            "temperature": {
                "type": "number",
                "description": "Zieltemperatur in Grad Celsius",
            },
            "mode": {
                "type": "string",
                "enum": ["heat", "cool", "auto", "off"],
                "description": "Heizmodus (optional)",
            },
        },
        "required": ["room", "temperature"],
    }


# Ollama Tool-Definitionen (Qwen 2.5 Function Calling Format)
# ASSISTANT_TOOLS wird als Funktion gebaut, damit set_climate
# bei jedem Aufruf den aktuellen heating.mode aus yaml_config liest.
_ASSISTANT_TOOLS_STATIC = [
    {
        "type": "function",
        "function": {
            "name": "set_light",
            "description": "Licht in einem Raum ein-/ausschalten oder dimmen",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname (z.B. wohnzimmer, schlafzimmer, buero)",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["on", "off"],
                        "description": "Ein oder aus",
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Helligkeit 0-100 Prozent (optional)",
                    },
                    "transition": {
                        "type": "integer",
                        "description": "Uebergangsdauer in Sekunden (optional, fuer sanftes Dimmen)",
                    },
                    "color_temp": {
                        "type": "string",
                        "enum": ["warm", "neutral", "cold"],
                        "description": "Farbtemperatur: warm (2700K), neutral (4000K), cold (6500K)",
                    },
                },
                "required": ["room", "state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_climate",
            "description": _get_climate_tool_description(),
            "parameters": _get_climate_tool_parameters(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "activate_scene",
            "description": "Eine Szene aktivieren (z.B. filmabend, gute_nacht, gemuetlich)",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {
                        "type": "string",
                        "description": "Name der Szene",
                    },
                },
                "required": ["scene"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_cover",
            "description": "Rollladen oder Jalousie steuern",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname",
                    },
                    "position": {
                        "type": "integer",
                        "description": "Position 0 (zu) bis 100 (offen)",
                    },
                },
                "required": ["room", "position"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "Musik oder Medien steuern, optional mit Suchanfrage",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "stop", "next", "previous"],
                        "description": "Medien-Aktion",
                    },
                    "query": {
                        "type": "string",
                        "description": "Suchanfrage fuer Musik (z.B. 'Jazz', 'Beethoven', 'Chill Playlist')",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_alarm",
            "description": "Alarmanlage steuern",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["arm_home", "arm_away", "disarm"],
                        "description": "Alarm-Modus",
                    },
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_door",
            "description": "Tuer ver- oder entriegeln",
            "parameters": {
                "type": "object",
                "properties": {
                    "door": {
                        "type": "string",
                        "description": "Name der Tuer",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["lock", "unlock"],
                        "description": "Verriegeln oder entriegeln",
                    },
                },
                "required": ["door", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": "Benachrichtigung senden (optional gezielt in einen Raum)",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Nachricht",
                    },
                    "target": {
                        "type": "string",
                        "enum": ["phone", "speaker", "dashboard"],
                        "description": "Ziel der Benachrichtigung",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum fuer TTS-Ausgabe (optional, nur bei target=speaker)",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_sound",
            "description": "Einen Sound-Effekt abspielen (z.B. Chime, Ping, Alert)",
            "parameters": {
                "type": "object",
                "properties": {
                    "sound": {
                        "type": "string",
                        "enum": [
                            "listening", "confirmed", "warning",
                            "alarm", "doorbell", "greeting",
                            "error", "goodnight",
                        ],
                        "description": "Sound-Event Name",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum in dem der Sound abgespielt werden soll (optional)",
                    },
                },
                "required": ["sound"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_state",
            "description": "Status einer Home Assistant Entity abfragen (z.B. Sensor, Schalter, Thermostat)",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity-ID (z.B. sensor.temperatur_buero, switch.steckdose_kueche)",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message_to_person",
            "description": "Nachricht an eine bestimmte Person senden (TTS in deren Raum oder Push)",
            "parameters": {
                "type": "object",
                "properties": {
                    "person": {
                        "type": "string",
                        "description": "Name der Person (z.B. Lisa, Max)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Die Nachricht",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Dringlichkeit (optional, default: medium)",
                    },
                },
                "required": ["person", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_playback",
            "description": "Musik-Wiedergabe von einem Raum in einen anderen uebertragen",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_room": {
                        "type": "string",
                        "description": "Quell-Raum (wo die Musik gerade laeuft)",
                    },
                    "to_room": {
                        "type": "string",
                        "description": "Ziel-Raum (wohin die Musik soll)",
                    },
                },
                "required": ["to_room"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "Kalender-Termine abrufen (heute, morgen oder bestimmtes Datum)",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeframe": {
                        "type": "string",
                        "enum": ["today", "tomorrow", "week"],
                        "description": "Zeitraum: heute, morgen oder diese Woche",
                    },
                },
                "required": ["timeframe"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Einen neuen Kalender-Termin erstellen",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel des Termins",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum im Format YYYY-MM-DD",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Startzeit im Format HH:MM (optional, ganztaegig wenn leer)",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Endzeit im Format HH:MM (optional, +1h wenn leer)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschreibung (optional)",
                    },
                },
                "required": ["title", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": "Einen Kalender-Termin loeschen",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel des Termins (oder Teil davon)",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum des Termins im Format YYYY-MM-DD",
                    },
                },
                "required": ["title", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_calendar_event",
            "description": "Einen Kalender-Termin verschieben (neues Datum/Uhrzeit)",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel des bestehenden Termins",
                    },
                    "old_date": {
                        "type": "string",
                        "description": "Bisheriges Datum im Format YYYY-MM-DD",
                    },
                    "new_date": {
                        "type": "string",
                        "description": "Neues Datum im Format YYYY-MM-DD",
                    },
                    "new_start_time": {
                        "type": "string",
                        "description": "Neue Startzeit HH:MM (optional)",
                    },
                    "new_end_time": {
                        "type": "string",
                        "description": "Neue Endzeit HH:MM (optional)",
                    },
                },
                "required": ["title", "old_date", "new_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_presence_mode",
            "description": "Anwesenheitsmodus des Hauses setzen",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["home", "away", "sleep", "vacation"],
                        "description": "Anwesenheitsmodus",
                    },
                },
                "required": ["mode"],
            },
        },
    },
    # --- Phase 13.1: Config-Selbstmodifikation ---
    {
        "type": "function",
        "function": {
            "name": "edit_config",
            "description": "Eigene Konfiguration anpassen (Easter Eggs, Meinungen, Raum-Profile). Nutze dies um dich selbst zu verbessern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "config_file": {
                        "type": "string",
                        "enum": ["easter_eggs", "opinion_rules", "room_profiles"],
                        "description": "Welche Konfiguration aendern (easter_eggs, opinion_rules, room_profiles)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "update"],
                        "description": "Aktion: hinzufuegen, entfernen oder aktualisieren",
                    },
                    "key": {
                        "type": "string",
                        "description": "Schluessel/Name des Eintrags (z.B. 'star_wars' fuer Easter Egg, 'high_temp' fuer Opinion)",
                    },
                    "data": {
                        "type": "object",
                        "description": "Die Daten des Eintrags (z.B. {trigger: 'möge die macht', response: 'Immer, Sir.', enabled: true})",
                    },
                },
                "required": ["config_file", "action", "key"],
            },
        },
    },
    # --- Phase 15.2: Einkaufsliste ---
    {
        "type": "function",
        "function": {
            "name": "manage_shopping_list",
            "description": "Einkaufsliste verwalten (Artikel hinzufuegen, anzeigen, abhaken, entfernen)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "complete", "clear_completed"],
                        "description": "Aktion: hinzufuegen, auflisten, abhaken, abgehakte entfernen",
                    },
                    "item": {
                        "type": "string",
                        "description": "Artikelname (fuer add/complete)",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # --- Phase 15.2: Vorrats-Tracking ---
    {
        "type": "function",
        "function": {
            "name": "manage_inventory",
            "description": "Vorratsmanagement: Artikel mit Ablaufdatum hinzufuegen, entfernen, auflisten, Menge aendern. Warnt bei bald ablaufenden Artikeln.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "list", "update_quantity", "check_expiring"],
                        "description": "Aktion: hinzufuegen, entfernen, auflisten, Menge aendern, Ablauf pruefen",
                    },
                    "item": {
                        "type": "string",
                        "description": "Artikelname",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Menge (Default: 1)",
                    },
                    "expiry_date": {
                        "type": "string",
                        "description": "Ablaufdatum im Format YYYY-MM-DD (optional)",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["kuehlschrank", "gefrier", "vorrat", "sonstiges"],
                        "description": "Lagerort/Kategorie",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # --- Phase 16.2: Was kann Jarvis? ---
    {
        "type": "function",
        "function": {
            "name": "list_capabilities",
            "description": "Zeigt was der Assistent alles kann. Nutze dies wenn der User fragt was du kannst.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # --- Phase 13.2: Self Automation ---
    {
        "type": "function",
        "function": {
            "name": "create_automation",
            "description": "Erstellt eine neue Home Assistant Automation aus natuerlicher Sprache. Der User beschreibt was passieren soll, Jarvis generiert die Automation und fragt nach Bestaetigung.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Natuerlichsprachliche Beschreibung der Automation (z.B. 'Wenn ich nach Hause komme, mach das Licht an')",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_automation",
            "description": "Bestaetigt eine vorgeschlagene Automation und aktiviert sie in Home Assistant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pending_id": {
                        "type": "string",
                        "description": "ID der ausstehenden Automation (wird bei create_automation zurueckgegeben)",
                    },
                },
                "required": ["pending_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_jarvis_automations",
            "description": "Zeigt alle von Jarvis erstellten Automationen an.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_jarvis_automation",
            "description": "Loescht eine von Jarvis erstellte Automation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {
                        "type": "string",
                        "description": "ID der Automation (z.B. jarvis_abc12345_20260218)",
                    },
                },
                "required": ["automation_id"],
            },
        },
    },
]


def get_assistant_tools() -> list:
    """Liefert Tool-Definitionen mit aktuellem Climate-Schema.

    Climate-Tool wird bei jedem Aufruf neu gebaut, damit
    Aenderungen am Heizungsmodus (room_thermostat vs heating_curve)
    sofort wirksam werden — ohne Neustart.
    """
    tools = []
    for tool in _ASSISTANT_TOOLS_STATIC:
        if tool.get("function", {}).get("name") == "set_climate":
            tools.append({
                "type": "function",
                "function": {
                    "name": "set_climate",
                    "description": _get_climate_tool_description(),
                    "parameters": _get_climate_tool_parameters(),
                },
            })
        else:
            tools.append(tool)
    return tools


# ASSISTANT_TOOLS: Immer die dynamische Version verwenden
ASSISTANT_TOOLS = get_assistant_tools()


class FunctionExecutor:
    """Fuehrt Function Calls des Assistenten aus."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self._entity_cache: dict[str, list[dict]] = {}
        self._config_versioning: Optional[ConfigVersioning] = None

    def set_config_versioning(self, versioning: ConfigVersioning):
        """Setzt ConfigVersioning fuer Backup-vor-Schreiben."""
        self._config_versioning = versioning

    async def execute(self, function_name: str, arguments: dict) -> dict:
        """
        Fuehrt eine Funktion aus.

        Args:
            function_name: Name der Funktion
            arguments: Parameter als Dict

        Returns:
            Ergebnis-Dict mit success und message
        """
        handler = getattr(self, f"_exec_{function_name}", None)
        if not handler:
            return {"success": False, "message": f"Unbekannte Funktion: {function_name}"}

        try:
            return await handler(arguments)
        except Exception as e:
            logger.error("Fehler bei %s: %s", function_name, e)
            return {"success": False, "message": f"Fehler: {e}"}

    async def _exec_set_light(self, args: dict) -> dict:
        room = args["room"]
        state = args["state"]

        # Sonderfall: "all" -> alle Lichter schalten
        if room.lower() == "all":
            return await self._exec_set_light_all(args, state)

        entity_id = await self._find_entity("light", room)
        if not entity_id:
            return {"success": False, "message": f"Kein Licht in '{room}' gefunden"}

        service_data = {"entity_id": entity_id}
        if "brightness" in args and state == "on":
            service_data["brightness_pct"] = args["brightness"]
        # Phase 9: Transition-Parameter (sanftes Dimmen)
        if "transition" in args:
            service_data["transition"] = args["transition"]
        # Foundation F.4: Farbtemperatur (warm/neutral/cold)
        _COLOR_TEMP_MAP = {"warm": 2700, "neutral": 4000, "cold": 6500}
        if "color_temp" in args and state == "on":
            kelvin = _COLOR_TEMP_MAP.get(args["color_temp"], 4000)
            service_data["color_temp_kelvin"] = kelvin

        service = "turn_on" if state == "on" else "turn_off"
        success = await self.ha.call_service("light", service, service_data)
        extras = []
        if "transition" in args:
            extras.append(f"Transition: {args['transition']}s")
        if "color_temp" in args:
            extras.append(f"Farbtemperatur: {args['color_temp']}")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        return {"success": success, "message": f"Licht {room} {state}{extra_str}"}

    async def _exec_set_light_all(self, args: dict, state: str) -> dict:
        """Alle Lichter ein- oder ausschalten."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Ich kann gerade nicht auf die Geraete zugreifen. Versuch es bitte gleich nochmal."}

        service = "turn_on" if state == "on" else "turn_off"
        count = 0
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light.") and s.get("state") != state:
                service_data = {"entity_id": eid}
                if "brightness" in args and state == "on":
                    service_data["brightness_pct"] = args["brightness"]
                await self.ha.call_service("light", service, service_data)
                count += 1

        return {"success": True, "message": f"Alle Lichter {state} ({count} geschaltet)"}

    async def _exec_set_climate(self, args: dict) -> dict:
        heating = yaml_config.get("heating", {})
        mode = heating.get("mode", "room_thermostat")

        if mode == "heating_curve":
            return await self._exec_set_climate_curve(args, heating)
        return await self._exec_set_climate_room(args)

    async def _exec_set_climate_curve(self, args: dict, heating: dict) -> dict:
        """Heizkurven-Modus: Offset auf zentrales Entity setzen."""
        offset = args.get("offset", 0)
        entity_id = heating.get("curve_entity", "")
        if not entity_id:
            return {"success": False, "message": "Kein Heizungs-Entity konfiguriert (heating.curve_entity)"}

        # Aktuellen Zustand holen um Basis-Temperatur zu ermitteln
        states = await self.ha.get_states()
        current_state = None
        for s in (states or []):
            if s.get("entity_id") == entity_id:
                current_state = s
                break

        if not current_state:
            return {"success": False, "message": f"Entity {entity_id} nicht gefunden"}

        # Basis-Temperatur der Heizkurve (vom Regler geliefert)
        attrs = current_state.get("attributes", {})
        base_temp = attrs.get("temperature")
        if base_temp is None:
            return {"success": False, "message": f"Ich kann die aktuelle Temperatur von {entity_id} gerade nicht abrufen."}

        # Offset-Grenzen aus Config erzwingen
        offset_min = heating.get("curve_offset_min", -5)
        offset_max = heating.get("curve_offset_max", 5)
        offset = max(offset_min, min(offset_max, offset))

        # Offset wird absolut zur Basis-Temperatur gesetzt (nicht kumulativ)
        new_temp = float(base_temp) + offset

        service_data = {"entity_id": entity_id, "temperature": new_temp}
        if "mode" in args:
            service_data["hvac_mode"] = args["mode"]

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        sign = "+" if offset >= 0 else ""
        return {"success": success, "message": f"Heizung: Offset {sign}{offset}°C (Vorlauf {new_temp}°C)"}

    async def _exec_set_climate_room(self, args: dict) -> dict:
        """Raumthermostat-Modus: Temperatur pro Raum setzen (wie bisher)."""
        room = args["room"]
        temp = args["temperature"]
        entity_id = await self._find_entity("climate", room)
        if not entity_id:
            return {"success": False, "message": f"Kein Thermostat in '{room}' gefunden"}

        service_data = {"entity_id": entity_id, "temperature": temp}
        if "mode" in args:
            service_data["hvac_mode"] = args["mode"]

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        return {"success": success, "message": f"{room} auf {temp}°C"}

    async def _exec_activate_scene(self, args: dict) -> dict:
        scene = args["scene"]
        entity_id = await self._find_entity("scene", scene)
        if not entity_id:
            # Versuche direkt mit scene.name
            entity_id = f"scene.{scene}"

        success = await self.ha.call_service(
            "scene", "turn_on", {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Szene '{scene}' aktiviert"}

    async def _exec_set_cover(self, args: dict) -> dict:
        room = args["room"]
        position = args["position"]

        # Sonderfall: "all" -> alle Rolllaeden schalten
        if room.lower() == "all":
            return await self._exec_set_cover_all(position)

        entity_id = await self._find_entity("cover", room)
        if not entity_id:
            return {"success": False, "message": f"Kein Rollladen in '{room}' gefunden"}

        success = await self.ha.call_service(
            "cover", "set_cover_position",
            {"entity_id": entity_id, "position": position},
        )
        return {"success": success, "message": f"Rollladen {room} auf {position}%"}

    async def _exec_set_cover_all(self, position: int) -> dict:
        """Alle Rolllaeden auf eine Position setzen."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Ich kann gerade nicht auf die Geraete zugreifen. Versuch es bitte gleich nochmal."}

        count = 0
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("cover."):
                await self.ha.call_service(
                    "cover", "set_cover_position",
                    {"entity_id": eid, "position": position},
                )
                count += 1

        return {"success": True, "message": f"Alle Rolllaeden auf {position}% ({count} geschaltet)"}

    async def _exec_call_service(self, args: dict) -> dict:
        """Generischer HA Service-Aufruf (fuer Routinen wie Guest WiFi)."""
        domain = args.get("domain", "")
        service = args.get("service", "")
        entity_id = args.get("entity_id", "")
        if not domain or not service:
            return {"success": False, "message": "domain und service erforderlich"}
        service_data = {"entity_id": entity_id} if entity_id else {}
        # Weitere Service-Daten aus args uebernehmen
        for k, v in args.items():
            if k not in ("domain", "service", "entity_id"):
                service_data[k] = v
        success = await self.ha.call_service(domain, service, service_data)
        return {"success": success, "message": f"{domain}.{service} ausgefuehrt"}

    async def _exec_play_media(self, args: dict) -> dict:
        action = args["action"]
        room = args.get("room")
        entity_id = await self._find_entity("media_player", room) if room else None

        if not entity_id:
            # Ersten aktiven Player nehmen
            states = await self.ha.get_states()
            for s in (states or []):
                if s.get("entity_id", "").startswith("media_player."):
                    entity_id = s["entity_id"]
                    break

        if not entity_id:
            return {"success": False, "message": "Kein Media Player gefunden"}

        # Foundation F.5: Musik-Suche via query
        query = args.get("query")
        if query and action == "play":
            success = await self.ha.call_service(
                "media_player", "play_media",
                {
                    "entity_id": entity_id,
                    "media_content_id": query,
                    "media_content_type": "music",
                },
            )
            return {"success": success, "message": f"Suche '{query}' wird abgespielt"}

        service_map = {
            "play": "media_play",
            "pause": "media_pause",
            "stop": "media_stop",
            "next": "media_next_track",
            "previous": "media_previous_track",
        }
        service = service_map.get(action, "media_play")
        success = await self.ha.call_service(
            "media_player", service, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Medien: {action}"}

    async def _exec_transfer_playback(self, args: dict) -> dict:
        """Phase 10.1: Uebertraegt Musik-Wiedergabe von einem Raum zum anderen."""
        from_room = args.get("from_room")
        to_room = args["to_room"]

        to_entity = await self._find_entity("media_player", to_room)
        if not to_entity:
            return {"success": False, "message": f"Kein Media Player in '{to_room}' gefunden"}

        # Quell-Player finden (explizit oder aktiven suchen)
        from_entity = None
        if from_room:
            from_entity = await self._find_entity("media_player", from_room)
        else:
            # Aktiven Player finden
            states = await self.ha.get_states()
            for s in (states or []):
                eid = s.get("entity_id", "")
                if eid.startswith("media_player.") and s.get("state") == "playing":
                    from_entity = eid
                    from_room = s.get("attributes", {}).get("friendly_name", eid)
                    break

        if not from_entity:
            return {"success": False, "message": "Keine aktive Wiedergabe gefunden"}

        if from_entity == to_entity:
            return {"success": True, "message": "Musik laeuft bereits in diesem Raum"}

        # Aktuellen Zustand vom Quell-Player holen
        states = await self.ha.get_states()
        source_state = None
        for s in (states or []):
            if s.get("entity_id") == from_entity:
                source_state = s
                break

        if not source_state or source_state.get("state") != "playing":
            return {"success": False, "message": f"In '{from_room}' laeuft nichts"}

        attrs = source_state.get("attributes", {})
        media_content_id = attrs.get("media_content_id", "")
        media_content_type = attrs.get("media_content_type", "music")
        volume = attrs.get("volume_level", 0.5)

        # 1. Volume auf Ziel-Player setzen
        await self.ha.call_service(
            "media_player", "volume_set",
            {"entity_id": to_entity, "volume_level": volume},
        )

        # 2. Wiedergabe auf Ziel-Player starten
        success = False
        if media_content_id:
            success = await self.ha.call_service(
                "media_player", "play_media",
                {
                    "entity_id": to_entity,
                    "media_content_id": media_content_id,
                    "media_content_type": media_content_type,
                },
            )
        else:
            # Fallback: Join/Unjoin wenn kein Content-ID (z.B. Gruppen-Streaming)
            success = await self.ha.call_service(
                "media_player", "join",
                {"entity_id": from_entity, "group_members": [to_entity]},
            )

        # 3. Quell-Player stoppen
        if success:
            await self.ha.call_service(
                "media_player", "media_stop",
                {"entity_id": from_entity},
            )

        return {
            "success": success,
            "message": f"Musik von {from_room} nach {to_room} uebertragen" if success
                       else f"Transfer nach {to_room} fehlgeschlagen",
        }

    async def _exec_set_alarm(self, args: dict) -> dict:
        mode = args["mode"]
        states = await self.ha.get_states()
        entity_id = None
        for s in (states or []):
            if s.get("entity_id", "").startswith("alarm_control_panel."):
                entity_id = s["entity_id"]
                break

        if not entity_id:
            return {"success": False, "message": "Keine Alarmanlage gefunden"}

        service_map = {
            "arm_home": "alarm_arm_home",
            "arm_away": "alarm_arm_away",
            "disarm": "alarm_disarm",
        }
        service = service_map.get(mode, mode)
        success = await self.ha.call_service(
            "alarm_control_panel", service, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Alarm: {mode}"}

    async def _exec_lock_door(self, args: dict) -> dict:
        door = args["door"]
        action = args["action"]
        entity_id = await self._find_entity("lock", door)
        if not entity_id:
            return {"success": False, "message": f"Kein Schloss '{door}' gefunden"}

        success = await self.ha.call_service(
            "lock", action, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Tuer {door}: {action}"}

    async def _exec_send_notification(self, args: dict) -> dict:
        message = args["message"]
        target = args.get("target", "phone")
        volume = args.get("volume")  # Phase 9: Optional volume (0.0-1.0)
        room = args.get("room")  # Phase 10: Optional room for TTS routing

        if target == "phone":
            success = await self.ha.call_service(
                "notify", "notify", {"message": message}
            )
        elif target == "speaker":
            # TTS ueber Piper (Wyoming): tts.speak mit TTS-Entity + Media-Player
            tts_entity = await self._find_tts_entity()

            # Phase 10: Room-aware Speaker-Auswahl
            if room:
                speaker_entity = await self._find_speaker_in_room(room)
            else:
                speaker_entity = await self._find_tts_speaker()

            # Phase 9: Volume setzen vor TTS
            if speaker_entity and volume is not None:
                await self.ha.call_service(
                    "media_player", "volume_set",
                    {"entity_id": speaker_entity, "volume_level": volume},
                )

            if tts_entity and speaker_entity:
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker_entity,
                        "message": message,
                        "language": "de",
                    },
                )
            elif speaker_entity:
                # Fallback: Legacy TTS Service
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": speaker_entity,
                        "message": message,
                        "language": "de",
                    },
                )
            else:
                # Letzter Fallback: persistent_notification
                success = await self.ha.call_service(
                    "persistent_notification", "create", {"message": message}
                )
        else:
            success = await self.ha.call_service(
                "persistent_notification", "create", {"message": message}
            )
        room_info = f" (Raum: {room})" if room else ""
        return {"success": success, "message": f"Benachrichtigung gesendet{room_info}"}

    async def _exec_send_message_to_person(self, args: dict) -> dict:
        """Phase 10.2: Sendet eine Nachricht an eine bestimmte Person.

        Routing-Logik:
        1. Person zu Hause → TTS im Raum der Person
        2. Person weg → Push-Notification auf Handy
        """
        person = args["person"]
        message = args["message"]
        person_lower = person.lower()

        # Person-Profil laden
        person_profiles = yaml_config.get("person_profiles", {}).get("profiles", {})
        profile = person_profiles.get(person_lower, {})

        # Pruefen ob Person zuhause ist
        states = await self.ha.get_states()
        person_home = False
        for state in (states or []):
            if state.get("entity_id", "").startswith("person."):
                name = state.get("attributes", {}).get("friendly_name", "")
                if name.lower() == person_lower and state.get("state") == "home":
                    person_home = True
                    break

        if person_home:
            # TTS im Raum der Person
            preferred_room = profile.get("preferred_room")
            tts_entity = await self._find_tts_entity()

            speaker = None
            if preferred_room:
                speaker = await self._find_speaker_in_room(preferred_room)
            if not speaker:
                speaker = await self._find_tts_speaker()

            if tts_entity and speaker:
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker,
                        "message": message,
                        "language": "de",
                    },
                )
                room_info = f" im {preferred_room}" if preferred_room else ""
                return {
                    "success": success,
                    "message": f"Nachricht an {person} per TTS{room_info} gesendet",
                    "delivery": "tts",
                }

        # Person nicht zuhause oder kein Speaker → Push
        notify_service = profile.get("notify_service", "notify.notify")
        # Service-Name extrahieren (z.B. "notify.max_phone" → domain="notify", service="max_phone")
        parts = notify_service.split(".", 1)
        if len(parts) == 2:
            success = await self.ha.call_service(
                parts[0], parts[1], {"message": message, "title": f"Nachricht von {settings.assistant_name}"}
            )
        else:
            success = await self.ha.call_service(
                "notify", "notify", {"message": message}
            )

        return {
            "success": success,
            "message": f"Push-Nachricht an {person} gesendet",
            "delivery": "push",
        }

    async def _exec_play_sound(self, args: dict) -> dict:
        """Phase 9: Spielt einen Sound-Effekt ab."""
        sound = args["sound"]
        room = args.get("room")

        speaker_entity = None
        if room:
            speaker_entity = await self._find_entity("media_player", room)
        if not speaker_entity:
            speaker_entity = await self._find_tts_speaker()

        if not speaker_entity:
            return {"success": False, "message": "Kein Speaker gefunden"}

        # Sound als TTS-Chime abspielen (oder Media-File wenn vorhanden)
        # Kurze TTS-Nachricht als Ersatz fuer Sound-Files
        sound_texts = {
            "listening": ".",
            "confirmed": ".",
            "warning": "Achtung.",
            "alarm": "Alarm!",
            "doorbell": "Es klingelt.",
            "greeting": ".",
            "error": "Fehler.",
            "goodnight": ".",
        }

        text = sound_texts.get(sound, ".")
        if text == ".":
            # Minimaler Sound — nur Volume-Ping
            return {"success": True, "message": f"Sound '{sound}' gespielt"}

        tts_entity = await self._find_tts_entity()
        if tts_entity:
            success = await self.ha.call_service(
                "tts", "speak",
                {
                    "entity_id": tts_entity,
                    "media_player_entity_id": speaker_entity,
                    "message": text,
                    "language": "de",
                },
            )
        else:
            success = False

        return {"success": success, "message": f"Sound '{sound}' gespielt"}

    async def _exec_get_entity_state(self, args: dict) -> dict:
        entity_id = args["entity_id"]
        state = await self.ha.get_state(entity_id)
        if not state:
            return {"success": False, "message": f"Entity '{entity_id}' nicht gefunden"}

        current = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        friendly_name = attrs.get("friendly_name", entity_id)
        unit = attrs.get("unit_of_measurement", "")

        display = f"{friendly_name}: {current}"
        if unit:
            display += f" {unit}"

        return {"success": True, "message": display, "state": current, "attributes": attrs}

    async def _exec_get_calendar_events(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termine abrufen via HA Calendar Entity."""
        from datetime import datetime, timedelta

        timeframe = args.get("timeframe", "today")
        now = datetime.now()

        if timeframe == "today":
            start = now.replace(hour=0, minute=0, second=0)
            end = now.replace(hour=23, minute=59, second=59)
        elif timeframe == "tomorrow":
            tomorrow = now + timedelta(days=1)
            start = tomorrow.replace(hour=0, minute=0, second=0)
            end = tomorrow.replace(hour=23, minute=59, second=59)
        else:  # week
            start = now.replace(hour=0, minute=0, second=0)
            end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59)

        # Kalender-Entity finden
        states = await self.ha.get_states()
        calendar_entity = None
        for s in (states or []):
            eid = s.get("entity_id", "")
            if eid.startswith("calendar."):
                calendar_entity = eid
                break

        if not calendar_entity:
            return {"success": False, "message": "Kein Kalender in Home Assistant gefunden"}

        # HA Calendar Service: get_events
        try:
            result = await self.ha.call_service_with_response(
                "calendar", "get_events",
                {
                    "entity_id": calendar_entity,
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
            )

            events = []
            if isinstance(result, dict):
                # Response-Format: {entity_id: {"events": [...]}}
                for entity_data in result.values():
                    if isinstance(entity_data, dict):
                        events.extend(entity_data.get("events", []))
                    elif isinstance(entity_data, list):
                        events.extend(entity_data)

            if not events:
                label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(timeframe, timeframe)
                return {"success": True, "message": f"Keine Termine {label}."}

            lines = []
            for ev in events[:10]:
                summary = ev.get("summary", "Kein Titel")
                ev_start = ev.get("start", "")
                ev_end = ev.get("end", "")
                # Zeit formatieren
                if "T" in str(ev_start):
                    try:
                        dt = datetime.fromisoformat(str(ev_start).replace("Z", "+00:00"))
                        time_str = dt.strftime("%H:%M")
                    except (ValueError, TypeError):
                        time_str = str(ev_start)
                else:
                    time_str = "ganztaegig"
                lines.append(f"{time_str}: {summary}")

            return {
                "success": True,
                "message": "\n".join(lines),
                "events": events[:10],
            }
        except Exception as e:
            logger.error("Kalender-Abfrage fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Kalender-Fehler: {e}"}

    async def _exec_create_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Neuen Kalender-Termin erstellen via HA."""
        from datetime import datetime, timedelta

        title = args["title"]
        date_str = args["date"]
        start_time = args.get("start_time", "")
        end_time = args.get("end_time", "")
        description = args.get("description", "")

        # Kalender-Entity finden
        states = await self.ha.get_states()
        calendar_entity = None
        for s in (states or []):
            eid = s.get("entity_id", "")
            if eid.startswith("calendar."):
                calendar_entity = eid
                break

        if not calendar_entity:
            return {"success": False, "message": "Kein Kalender in Home Assistant gefunden"}

        service_data = {
            "entity_id": calendar_entity,
            "summary": title,
        }

        if start_time:
            # Termin mit Uhrzeit
            service_data["start_date_time"] = f"{date_str} {start_time}:00"
            if end_time:
                service_data["end_date_time"] = f"{date_str} {end_time}:00"
            else:
                # Standard: +1 Stunde
                try:
                    start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
                    end_dt = start_dt + timedelta(hours=1)
                    service_data["end_date_time"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    service_data["end_date_time"] = f"{date_str} {start_time}:00"
        else:
            # Ganztaegiger Termin
            service_data["start_date"] = date_str
            try:
                end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
                service_data["end_date"] = end_date.strftime("%Y-%m-%d")
            except ValueError:
                service_data["end_date"] = date_str

        if description:
            service_data["description"] = description

        success = await self.ha.call_service(
            "calendar", "create_event", service_data
        )

        time_info = f" um {start_time}" if start_time else " (ganztaegig)"
        return {
            "success": success,
            "message": f"Termin '{title}' am {date_str}{time_info} erstellt" if success
                       else f"Termin konnte nicht erstellt werden",
        }

    async def _exec_delete_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termin loeschen.

        Sucht den Termin per Titel+Datum und loescht ihn via calendar.delete_event.
        """
        from datetime import datetime, timedelta

        title = args["title"]
        date_str = args["date"]

        # Kalender-Entity finden
        states = await self.ha.get_states()
        calendar_entity = None
        for s in (states or []):
            if s.get("entity_id", "").startswith("calendar."):
                calendar_entity = s.get("entity_id")
                break

        if not calendar_entity:
            return {"success": False, "message": "Kein Kalender in Home Assistant gefunden"}

        # Events fuer den Tag abrufen um das richtige Event zu finden
        try:
            start = f"{date_str}T00:00:00"
            end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            end = end_date.strftime("%Y-%m-%dT00:00:00")

            result = await self.ha.call_service_with_response(
                "calendar", "get_events",
                {"entity_id": calendar_entity, "start_date_time": start, "end_date_time": end},
            )

            # Event per Titel suchen
            events = []
            if isinstance(result, dict):
                for key, val in result.items():
                    if isinstance(val, dict):
                        events = val.get("events", [])
                        break

            target_event = None
            title_lower = title.lower()
            for event in events:
                if title_lower in event.get("summary", "").lower():
                    target_event = event
                    break

            if not target_event:
                return {"success": False, "message": f"Termin '{title}' am {date_str} nicht gefunden"}

            # Event loeschen
            uid = target_event.get("uid", "")
            if uid:
                success = await self.ha.call_service(
                    "calendar", "delete_event",
                    {"entity_id": calendar_entity, "uid": uid},
                )
            else:
                # Fallback: Ohne UID loeschen (Startzeit nutzen)
                success = await self.ha.call_service(
                    "calendar", "delete_event",
                    {
                        "entity_id": calendar_entity,
                        "start_date_time": target_event.get("start", {}).get("dateTime", start),
                        "end_date_time": target_event.get("end", {}).get("dateTime", end),
                        "summary": target_event.get("summary", title),
                    },
                )

            return {
                "success": success,
                "message": f"Termin '{title}' am {date_str} geloescht" if success
                           else "Termin konnte nicht geloescht werden",
            }
        except Exception as e:
            logger.error("Kalender-Delete Fehler: %s", e)
            return {"success": False, "message": f"Fehler: {e}"}

    async def _exec_reschedule_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termin verschieben (Delete + Re-Create)."""
        title = args["title"]
        old_date = args["old_date"]
        new_date = args["new_date"]
        new_start = args.get("new_start_time", "")
        new_end = args.get("new_end_time", "")

        # 1. Alten Termin loeschen
        delete_result = await self._exec_delete_calendar_event({
            "title": title,
            "date": old_date,
        })

        if not delete_result.get("success"):
            return {
                "success": False,
                "message": f"Verschieben fehlgeschlagen: {delete_result.get('message', '')}",
            }

        # 2. Neuen Termin erstellen
        create_result = await self._exec_create_calendar_event({
            "title": title,
            "date": new_date,
            "start_time": new_start,
            "end_time": new_end,
        })

        if create_result.get("success"):
            return {
                "success": True,
                "message": f"Termin '{title}' verschoben von {old_date} nach {new_date}",
            }
        return {
            "success": False,
            "message": f"Alter Termin geloescht, aber neuer konnte nicht erstellt werden",
        }

    async def _exec_set_presence_mode(self, args: dict) -> dict:
        mode = args["mode"]

        # Versuche input_select fuer Anwesenheitsmodus zu finden
        states = await self.ha.get_states()
        entity_id = None
        for s in (states or []):
            eid = s.get("entity_id", "")
            if eid.startswith("input_select.") and any(
                kw in eid for kw in ("presence", "anwesenheit", "presence_mode")
            ):
                entity_id = eid
                break

        if entity_id:
            success = await self.ha.call_service(
                "input_select", "select_option",
                {"entity_id": entity_id, "option": mode},
            )
            return {"success": success, "message": f"Anwesenheit: {mode}"}

        # Fallback: HA Event ueber REST API feuern
        success = await self.ha.fire_event(
            "mindhome_presence_mode", {"mode": mode}
        )
        if not success:
            # Letzter Fallback: Direkter Service-Call
            success = await self.ha.call_service(
                "input_boolean", "turn_on" if mode == "home" else "turn_off",
                {"entity_id": "input_boolean.zu_hause"},
            )
        return {"success": success, "message": f"Anwesenheit: {mode}"}

    async def _find_speaker_in_room(self, room: str) -> Optional[str]:
        """Phase 10.1: Findet einen Speaker in einem bestimmten Raum.

        Sucht zuerst in der Konfiguration (room_speakers),
        dann per Entity-Name-Matching.
        """
        # 1. Konfiguriertes Mapping pruefen
        room_speakers = yaml_config.get("multi_room", {}).get("room_speakers", {})
        room_lower = room.lower().replace(" ", "_")
        for cfg_room, entity_id in (room_speakers or {}).items():
            if cfg_room.lower() == room_lower:
                return entity_id

        # 2. Entity-Name-Matching
        return await self._find_entity("media_player", room)

    async def _find_tts_entity(self) -> Optional[str]:
        """Findet die Piper TTS-Entity (tts.piper o.ae.)."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("tts.") and "piper" in entity_id:
                return entity_id
        # Fallback: Erste TTS-Entity
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("tts."):
                return entity_id
        return None

    async def _find_tts_speaker(self) -> Optional[str]:
        """Findet einen Media-Player der als TTS-Speaker genutzt werden kann."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("media_player."):
                return entity_id
        return None

    # ------------------------------------------------------------------
    # Phase 13.1: Config-Selbstmodifikation
    # ------------------------------------------------------------------

    async def _exec_edit_config(self, args: dict) -> dict:
        """Phase 13.1: Jarvis passt eigene Config-Dateien an (Whitelist-geschuetzt).

        SICHERHEIT:
        - NUR easter_eggs.yaml, opinion_rules.yaml, room_profiles.yaml (Whitelist)
        - settings.yaml ist NICHT editierbar (nicht in _EDITABLE_CONFIGS)
        - Snapshot vor jeder Aenderung (Rollback jederzeit moeglich)
        - yaml.safe_dump() verhindert Code-Injection
        """
        config_file = args["config_file"]
        action = args["action"]
        key = args["key"]
        data = args.get("data", {})

        yaml_path = _EDITABLE_CONFIGS.get(config_file)
        if not yaml_path:
            return {"success": False, "message": f"Config '{config_file}' ist nicht editierbar"}

        try:
            # Snapshot vor Aenderung (Rollback-Sicherheitsnetz)
            if self._config_versioning and self._config_versioning.is_enabled():
                await self._config_versioning.create_snapshot(
                    config_file, yaml_path,
                    reason=f"edit_config:{action}:{key}",
                    changed_by="jarvis",
                )

            # Config laden
            if yaml_path.exists():
                with open(yaml_path) as f:
                    config = yaml.safe_load(f) or {}
            else:
                config = {}

            # Aktion ausfuehren
            if action == "add":
                if not data:
                    return {"success": False, "message": "Keine Daten zum Hinzufuegen angegeben"}
                if key in config:
                    return {"success": False, "message": f"'{key}' existiert bereits. Nutze 'update' stattdessen."}
                config[key] = data
                msg = f"'{key}' zu {config_file} hinzugefuegt"
            elif action == "update":
                if key not in config:
                    return {"success": False, "message": f"'{key}' nicht in {config_file} gefunden"}
                if isinstance(config[key], dict) and isinstance(data, dict):
                    config[key].update(data)
                else:
                    config[key] = data
                msg = f"'{key}' in {config_file} aktualisiert"
            elif action == "remove":
                if key not in config:
                    return {"success": False, "message": f"'{key}' nicht in {config_file} gefunden"}
                del config[key]
                msg = f"'{key}' aus {config_file} entfernt"
            else:
                return {"success": False, "message": f"Unbekannte Aktion: {action}"}

            # Zurueckschreiben
            with open(yaml_path, "w") as f:
                yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            logger.info("Config-Selbstmodifikation: %s (%s -> %s)", config_file, action, key)
            return {"success": True, "message": msg}

        except Exception as e:
            logger.error("Config-Edit fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Fehler: {e}"}

    # ------------------------------------------------------------------
    # Phase 15.2: Einkaufsliste (via HA Shopping List oder lokal)
    # ------------------------------------------------------------------

    async def _exec_manage_shopping_list(self, args: dict) -> dict:
        """Phase 15.2: Einkaufsliste verwalten ueber Home Assistant."""
        action = args["action"]
        item = args.get("item", "")

        if action == "add":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben"}
            success = await self.ha.call_service(
                "shopping_list", "add_item", {"name": item}
            )
            return {"success": success, "message": f"'{item}' auf die Einkaufsliste gesetzt" if success
                    else "Einkaufsliste nicht verfuegbar"}

        elif action == "list":
            # Shopping List ueber HA API abrufen
            try:
                items = await self.ha.api_get("/api/shopping_list")
                if not items:
                    return {"success": True, "message": "Die Einkaufsliste ist leer."}
                open_items = [i["name"] for i in items if not i.get("complete")]
                done_items = [i["name"] for i in items if i.get("complete")]
                parts = []
                if open_items:
                    parts.append("Einkaufsliste:\n" + "\n".join(f"- {i}" for i in open_items))
                if done_items:
                    parts.append(f"Erledigt: {', '.join(done_items)}")
                if not open_items and not done_items:
                    return {"success": True, "message": "Die Einkaufsliste ist leer."}
                return {"success": True, "message": "\n".join(parts)}
            except Exception:
                return {"success": False, "message": "Einkaufsliste nicht verfuegbar"}

        elif action == "complete":
            if not item:
                return {"success": False, "message": "Kein Artikel zum Abhaken angegeben"}
            success = await self.ha.call_service(
                "shopping_list", "complete_item", {"name": item}
            )
            return {"success": success, "message": f"'{item}' abgehakt" if success
                    else "Artikel nicht gefunden"}

        elif action == "clear_completed":
            success = await self.ha.call_service(
                "shopping_list", "complete_all", {}
            )
            return {"success": success, "message": "Abgehakte Artikel entfernt" if success
                    else "Fehler beim Aufraumen"}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Phase 16.2: Capabilities — Was kann Jarvis?
    # ------------------------------------------------------------------

    async def _exec_list_capabilities(self, args: dict) -> dict:
        """Phase 16.2: Listet alle Faehigkeiten des Assistenten."""
        capabilities = {
            "smart_home": [
                "Licht steuern (an/aus/dimmen, pro Raum)",
                "Heizung/Klima regeln (Temperatur, Modus)",
                "Rolllaeden steuern",
                "Szenen aktivieren (Filmabend, Gute Nacht, etc.)",
                "Alarmanlage steuern",
                "Tueren ver-/entriegeln",
                "Anwesenheitsmodus setzen (Home/Away/Sleep/Vacation)",
            ],
            "medien": [
                "Musik abspielen/pausieren/stoppen",
                "Naechster/vorheriger Titel",
                "Musik zwischen Raeumen uebertragen",
                "Sound-Effekte abspielen",
            ],
            "kommunikation": [
                "Nachrichten an Personen senden (TTS oder Push)",
                "Benachrichtigungen (Handy, Speaker, Dashboard)",
                "Proaktive Meldungen (Alarm, Tuerklingel, Waschmaschine, etc.)",
            ],
            "gedaechtnis": [
                "'Merk dir X' — Fakten speichern",
                "'Was weisst du ueber X?' — Wissen abrufen",
                "'Vergiss X' — Fakten loeschen",
                "Automatische Fakten-Extraktion aus Gespraechen",
                "Langzeit-Erinnerungen und Tages-Zusammenfassungen",
            ],
            "wissen": [
                "Allgemeine Wissensfragen beantworten",
                "Kalender-Termine anzeigen und erstellen",
                "'Was waere wenn'-Simulationen",
                "Wissensdatenbank (Dokumente, RAG)",
                "Kochen mit Schritt-fuer-Schritt-Anleitung + Timer",
            ],
            "haushalt": [
                "Einkaufsliste verwalten (hinzufuegen, anzeigen, abhaken)",
                "Vorrats-Tracking mit Ablaufdaten (Kuehlschrank, Gefrier, Vorrat)",
                "Raumklima-Monitor (CO2, Feuchte, Temperatur, Trink-Erinnerung)",
                "Zeitgefuehl (Ofen zu lange an, PC-Pause, etc.)",
                "Wartungs-Erinnerungen (Rauchmelder, Filter, etc.)",
                "System-Diagnostik (Sensoren, Batterien, Netzwerk)",
            ],
            "persoenlichkeit": [
                "Anpassbarer Sarkasmus-Level (1-5)",
                "Eigene Meinungen zu Aktionen",
                "Easter Eggs (z.B. 'Ich bin Iron Man')",
                "Running Gags und Selbstironie",
                "Charakter-Entwicklung (wird vertrauter mit der Zeit)",
                "Stimmungserkennung und emotionale Reaktionen",
            ],
            "sicherheit": [
                "Gaeste-Modus (versteckt persoenliche Infos)",
                "Vertrauensstufen pro Person (Gast/Mitbewohner/Owner)",
                "PIN-geschuetztes Dashboard",
                "Nacht-Routinen mit Sicherheits-Check",
            ],
            "selbstverbesserung": [
                "Korrektur-Lernen ('Nein, ich meinte...')",
                "Eigene Config anpassen (Easter Eggs, Meinungen, Raeume)",
                "Feedback-basierte Optimierung proaktiver Meldungen",
            ],
            "automationen": [
                "Automationen aus natuerlicher Sprache erstellen ('Wenn ich nach Hause komme, Licht an')",
                "Sicherheits-Whitelist (nur erlaubte Services)",
                "Vorschau + Bestaetigung vor Aktivierung",
                "Jarvis-Automationen auflisten und loeschen",
                "Kill-Switch: Alle Jarvis-Automationen deaktivieren",
            ],
        }

        lines = ["Das kann ich fuer dich tun:\n"]
        for category, items in capabilities.items():
            label = category.replace("_", " ").title()
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"  - {item}")
            lines.append("")

        return {"success": True, "message": "\n".join(lines)}

    # ------------------------------------------------------------------
    # Phase 13.2: Self Automation
    # ------------------------------------------------------------------

    async def _exec_create_automation(self, args: dict) -> dict:
        """Phase 13.2: Erstellt eine Automation aus natuerlicher Sprache."""
        import assistant.main as main_module
        brain = main_module.brain
        self_auto = brain.self_automation

        description = args.get("description", "")
        if not description:
            return {"success": False, "message": "Keine Beschreibung angegeben."}

        return await self_auto.generate_automation(description)

    async def _exec_confirm_automation(self, args: dict) -> dict:
        """Phase 13.2: Bestaetigt eine ausstehende Automation."""
        import assistant.main as main_module
        brain = main_module.brain
        self_auto = brain.self_automation

        pending_id = args.get("pending_id", "")
        if not pending_id:
            return {"success": False, "message": "Keine Pending-ID angegeben."}

        return await self_auto.confirm_automation(pending_id)

    async def _exec_list_jarvis_automations(self, args: dict) -> dict:
        """Phase 13.2: Listet alle Jarvis-Automationen auf."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.self_automation.list_jarvis_automations()

    async def _exec_delete_jarvis_automation(self, args: dict) -> dict:
        """Phase 13.2: Loescht eine Jarvis-Automation."""
        import assistant.main as main_module
        brain = main_module.brain

        automation_id = args.get("automation_id", "")
        if not automation_id:
            return {"success": False, "message": "Keine Automation-ID angegeben."}

        return await brain.self_automation.delete_jarvis_automation(automation_id)

    async def _find_entity(self, domain: str, search: str) -> Optional[str]:
        """Findet eine Entity anhand von Domain und Suchbegriff."""
        if not search:
            return None

        states = await self.ha.get_states()
        if not states:
            return None

        search_lower = search.lower().replace(" ", "_").replace("ue", "u").replace("ae", "a").replace("oe", "o")

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(f"{domain}."):
                continue

            # Exakter Match
            name = entity_id.split(".", 1)[1]
            if search_lower in name:
                return entity_id

            # Friendly name Match
            friendly = state.get("attributes", {}).get("friendly_name", "").lower()
            if search.lower() in friendly:
                return entity_id

        return None

    # ------------------------------------------------------------------
    # Phase 15.2: Vorrats-Tracking
    # ------------------------------------------------------------------

    async def _exec_manage_inventory(self, args: dict) -> dict:
        """Verwaltet den Vorrat."""
        # Inventory Manager aus dem brain holen
        from .brain import AssistantBrain
        import assistant.main as main_module
        brain = main_module.brain
        inventory = brain.inventory

        action = args["action"]
        item = args.get("item", "")
        quantity = args.get("quantity", 1)
        expiry = args.get("expiry_date", "")
        category = args.get("category", "sonstiges")

        if action == "add":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.add_item(item, quantity, expiry, category)

        elif action == "remove":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.remove_item(item)

        elif action == "list":
            return await inventory.list_items(category if category != "sonstiges" else "")

        elif action == "update_quantity":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.update_quantity(item, quantity)

        elif action == "check_expiring":
            expiring = await inventory.check_expiring(days_ahead=3)
            if not expiring:
                return {"success": True, "message": "Keine Artikel laufen in den naechsten 3 Tagen ab."}
            lines = [f"{len(expiring)} Artikel laufen bald ab:"]
            for item_data in expiring:
                days = item_data["days_left"]
                if days < 0:
                    lines.append(f"- {item_data['name']}: ABGELAUFEN seit {abs(days)} Tag(en)!")
                elif days == 0:
                    lines.append(f"- {item_data['name']}: laeuft HEUTE ab!")
                else:
                    lines.append(f"- {item_data['name']}: noch {days} Tag(e)")
            return {"success": True, "message": "\n".join(lines)}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}
