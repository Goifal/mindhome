"""
Function Calling - Definiert und fuehrt Funktionen aus die der Assistent nutzen kann.
MindHome Assistant ruft ueber diese Funktionen Home Assistant Aktionen aus.

Phase 10: Room-aware TTS, Person Messaging, Trust-Level Pre-Check.
"""

import logging
import re
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
    return "Temperatur in einem Raum aendern. Fuer 'waermer' verwende adjust='warmer', fuer 'kaelter' verwende adjust='cooler' (aendert um 1°C)."


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
                "description": "Zieltemperatur in Grad Celsius (optional bei adjust='warmer'/'cooler')",
            },
            "adjust": {
                "type": "string",
                "enum": ["warmer", "cooler"],
                "description": "Relative Anpassung: 'warmer' = +1°C, 'cooler' = -1°C. Wenn gesetzt, wird temperature ignoriert.",
            },
            "mode": {
                "type": "string",
                "enum": ["heat", "cool", "auto", "off"],
                "description": "Heizmodus (optional)",
            },
        },
        "required": ["room"],
    }


# Ollama Tool-Definitionen (Qwen 2.5 Function Calling Format)
# ASSISTANT_TOOLS wird als Funktion gebaut, damit set_climate
# bei jedem Aufruf den aktuellen heating.mode aus yaml_config liest.
_ASSISTANT_TOOLS_STATIC = [
    {
        "type": "function",
        "function": {
            "name": "set_light",
            "description": "Licht in einem Raum ein-/ausschalten oder dimmen. Fuer 'heller' verwende state='brighter', fuer 'dunkler' verwende state='dimmer'. Diese passen die Helligkeit relativ um 15% an.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname (z.B. wohnzimmer, schlafzimmer, buero)",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["on", "off", "brighter", "dimmer"],
                        "description": "Ein, aus, heller (+15%) oder dunkler (-15%)",
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Helligkeit 0-100 Prozent (optional, nur bei state='on')",
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
            "description": "Rollladen oder Jalousie steuern. NIEMALS fuer Garagentore verwenden! Fuer 'ein bisschen runter/hoch' verwende adjust='down' oder adjust='up' (aendert um 20%).",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname",
                    },
                    "position": {
                        "type": "integer",
                        "description": "Position 0 (zu) bis 100 (offen). Optional bei adjust.",
                    },
                    "adjust": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Relative Anpassung: 'up' = +20% (offener), 'down' = -20% (weiter zu). Wenn gesetzt, wird position ignoriert.",
                    },
                },
                "required": ["room"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "Musik oder Medien steuern: abspielen, pausieren, stoppen, Lautstaerke aendern. Fuer 'leiser' verwende action='volume_down', fuer 'lauter' verwende action='volume_up'. Fuer eine bestimmte Lautstaerke verwende action='volume' mit volume-Parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname (z.B. 'Wohnzimmer', 'Manuel Buero')",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "stop", "next", "previous", "volume", "volume_up", "volume_down"],
                        "description": "Medien-Aktion. 'volume' = Lautstaerke auf Wert setzen, 'volume_up' = lauter (+10%), 'volume_down' = leiser (-10%)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Suchanfrage fuer Musik (z.B. 'Jazz', 'Beethoven', 'Chill Playlist')",
                    },
                    "media_type": {
                        "type": "string",
                        "enum": ["music", "podcast", "audiobook", "playlist", "channel"],
                        "description": "Art des Mediums (Standard: music)",
                    },
                    "volume": {
                        "type": "number",
                        "description": "Lautstaerke 0-100 (Prozent). Nur bei action='volume'. Z.B. 20 fuer 20%, 50 fuer 50%",
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
            "description": "Status einer Home Assistant Entity abfragen. Funktioniert mit allen Entity-Typen: sensor.*, switch.*, light.*, climate.*, weather.* (z.B. weather.forecast_home fuer Wetterdaten), lock.*, media_player.*, binary_sensor.*, person.* etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity-ID (z.B. sensor.temperatur_buero, weather.forecast_home, switch.steckdose_kueche)",
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
    # --- Neue Features: Timer, Broadcast, Kamera, Conditionals, Energie, Web-Suche ---
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Setzt einen allgemeinen Timer/Erinnerung. Z.B. 'Erinnere mich in 30 Minuten an die Waesche' oder 'In 20 Minuten Licht aus'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Dauer in Minuten (1-1440)",
                    },
                    "label": {
                        "type": "string",
                        "description": "Bezeichnung des Timers (z.B. 'Waesche', 'Pizza', 'Anruf')",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum in dem die Timer-Benachrichtigung erfolgen soll",
                    },
                    "action_on_expire": {
                        "type": "object",
                        "description": "Optionale Aktion bei Ablauf. Format: {\"function\": \"set_light\", \"args\": {\"room\": \"kueche\", \"state\": \"off\"}}",
                    },
                },
                "required": ["duration_minutes", "label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_timer",
            "description": "Bricht einen laufenden Timer ab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "Bezeichnung des Timers zum Abbrechen (z.B. 'Waesche')",
                    },
                },
                "required": ["label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timer_status",
            "description": "Zeigt den Status aller aktiven Timer an. 'Wie lange noch?' oder 'Welche Timer laufen?'",
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
            "name": "set_reminder",
            "description": "Setzt eine Erinnerung fuer eine bestimmte Uhrzeit. Z.B. 'Erinnere mich um 15 Uhr an den Anruf' oder 'Um 18:30 Abendessen kochen'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "Uhrzeit im Format HH:MM (z.B. '15:00', '06:30')",
                    },
                    "label": {
                        "type": "string",
                        "description": "Woran erinnert werden soll (z.B. 'Anruf bei Mama', 'Medikamente nehmen')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum im Format YYYY-MM-DD. Wenn leer, wird heute oder morgen automatisch gewaehlt.",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum fuer die TTS-Benachrichtigung",
                    },
                },
                "required": ["time", "label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_wakeup_alarm",
            "description": "Stellt einen Wecker fuer eine bestimmte Uhrzeit. Z.B. 'Weck mich um 6:30' oder 'Stell einen Wecker fuer 7 Uhr'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "Weckzeit im Format HH:MM (z.B. '06:30', '07:00')",
                    },
                    "label": {
                        "type": "string",
                        "description": "Bezeichnung des Weckers (Standard: 'Wecker')",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum in dem geweckt werden soll (fuer Licht + TTS)",
                    },
                    "repeat": {
                        "type": "string",
                        "enum": ["", "daily", "weekdays", "weekends"],
                        "description": "Wiederholung: leer=einmalig, 'daily'=taeglich, 'weekdays'=Mo-Fr, 'weekends'=Sa-So",
                    },
                },
                "required": ["time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_alarm",
            "description": "Loescht einen Wecker. Z.B. 'Loesch den Wecker' oder 'Wecker aus'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "Bezeichnung des Weckers zum Loeschen",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alarms",
            "description": "Zeigt alle aktiven Wecker an. 'Welche Wecker habe ich?' oder 'Wecker Status'.",
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
            "name": "broadcast",
            "description": "Sendet eine Durchsage an ALLE Lautsprecher im Haus. Fuer Ankuendigungen wie 'Essen ist fertig!' oder 'Bitte alle runterkommen.'",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Die Durchsage-Nachricht",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_camera_view",
            "description": "Holt und beschreibt ein Kamera-Bild. Z.B. 'Wer ist an der Tuer?' oder 'Zeig mir die Garage'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_name": {
                        "type": "string",
                        "description": "Name oder Raum der Kamera (z.B. 'haustuer', 'garage', 'garten')",
                    },
                },
                "required": ["camera_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_conditional",
            "description": "Erstellt einen temporaeren bedingten Befehl: 'Wenn X passiert, dann Y'. Z.B. 'Wenn es regnet, Rolladen runter' oder 'Wenn Papa ankommt, sag ihm Bescheid'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trigger_type": {
                        "type": "string",
                        "enum": ["state_change", "person_arrives", "person_leaves", "state_attribute"],
                        "description": "Art des Triggers",
                    },
                    "trigger_value": {
                        "type": "string",
                        "description": "Trigger-Wert. Bei state_change: 'entity_id:state' (z.B. 'sensor.regen:on'). Bei person_arrives/leaves: Name (z.B. 'papa'). Bei state_attribute: 'entity_id|attribut|operator|wert' (pipe-getrennt, z.B. 'sensor.aussen|temperature|>|25')",
                    },
                    "action_function": {
                        "type": "string",
                        "description": "Auszufuehrende Funktion (z.B. 'set_cover', 'send_notification', 'set_light')",
                    },
                    "action_args": {
                        "type": "object",
                        "description": "Argumente fuer die Aktion",
                    },
                    "label": {
                        "type": "string",
                        "description": "Beschreibung (z.B. 'Rolladen bei Regen runter')",
                    },
                    "ttl_hours": {
                        "type": "integer",
                        "description": "Gueltigkeitsdauer in Stunden (default 24, max 168)",
                    },
                    "one_shot": {
                        "type": "boolean",
                        "description": "Nur einmal ausfuehren (default true)",
                    },
                },
                "required": ["trigger_type", "trigger_value", "action_function", "action_args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_conditionals",
            "description": "Zeigt alle aktiven bedingten Befehle (Wenn-Dann-Regeln) an.",
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
            "name": "get_energy_report",
            "description": "Zeigt einen Energie-Bericht mit Strompreis, Solar-Ertrag, Verbrauch und Empfehlungen.",
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
            "name": "web_search",
            "description": "Sucht im Internet nach Informationen. Nur fuer Wissensfragen die nicht aus dem Gedaechtnis beantwortet werden koennen. Z.B. 'Was ist die Hauptstadt von Australien?' oder 'Aktuelle Nachrichten'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Die Suchanfrage",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_security_score",
            "description": "Zeigt den aktuellen Sicherheits-Score des Hauses (0-100). Prueft offene Tueren, Fenster, Schloesser, Rauchmelder und Wassersensoren. Nutze dies wenn der User nach Sicherheit, Haus-Status oder offenen Tueren/Fenstern fragt.",
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
            "name": "get_room_climate",
            "description": "Zeigt Raumklima-Daten: CO2, Luftfeuchtigkeit, Temperatur und Gesundheitsbewertung. Nutze dies wenn der User nach Raumklima, Luftqualitaet oder Raumgesundheit fragt.",
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
            "name": "get_active_intents",
            "description": "Zeigt alle gemerkten Vorhaben und Termine die aus Gespraechen erkannt wurden. Z.B. 'Eltern kommen am Wochenende'. Nutze dies wenn der User nach anstehenden Plaenen oder 'was steht an?' fragt.",
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
            "name": "get_wellness_status",
            "description": "Zeigt den Wellness-Status des Users: PC-Nutzungsdauer, Stress-Level, letzte Mahlzeit, Hydration. Nutze dies wenn der User fragt wie es ihm geht, ob er eine Pause braucht oder nach seinem Wohlbefinden fragt.",
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
            "name": "get_device_health",
            "description": "Zeigt den Geraete-Gesundheitsstatus: Anomalien, inaktive Sensoren, HVAC-Effizienz. Nutze dies wenn der User nach Hardware-Problemen, Geraete-Status oder Sensor-Zustand fragt.",
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
            "name": "get_learned_patterns",
            "description": "Zeigt erkannte Verhaltensmuster: Welche manuellen Aktionen der User regelmaessig wiederholt. Z.B. 'Jeden Abend Licht aus um 22:30'. Nutze dies wenn der User fragt was Jarvis gelernt hat oder welche Muster erkannt wurden.",
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
            "name": "describe_doorbell",
            "description": "Beschreibt wer oder was gerade vor der Haustuer steht (via Tuerkamera). Nutze dies wenn der User fragt 'Wer ist an der Tuer?', 'Wer hat geklingelt?' oder 'Was ist vor der Tuer?'.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
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

    # Whitelist erlaubter Tool-Funktionsnamen (verhindert Zugriff auf interne Methoden)
    _ALLOWED_FUNCTIONS = frozenset({
        "set_light", "set_light_all", "set_climate", "set_climate_curve",
        "set_climate_room", "activate_scene", "set_cover", "set_cover_all",
        "call_service", "play_media", "transfer_playback", "set_alarm",
        "lock_door", "send_notification", "send_message_to_person",
        "play_sound", "get_entity_state", "get_calendar_events",
        "create_calendar_event", "delete_calendar_event",
        "reschedule_calendar_event", "set_presence_mode", "edit_config",
        "manage_shopping_list", "list_capabilities", "create_automation",
        "confirm_automation", "list_jarvis_automations",
        "delete_jarvis_automation", "manage_inventory",
        "set_timer", "cancel_timer", "get_timer_status",
        "set_reminder", "set_wakeup_alarm", "cancel_alarm", "get_alarms",
        "broadcast",
        "get_camera_view", "create_conditional", "list_conditionals",
        "get_energy_report", "web_search", "get_security_score",
        "get_room_climate", "get_active_intents", "get_wellness_status",
        "get_device_health", "get_learned_patterns", "describe_doorbell",
    })

    async def execute(self, function_name: str, arguments: dict) -> dict:
        """
        Fuehrt eine Funktion aus.

        Args:
            function_name: Name der Funktion
            arguments: Parameter als Dict

        Returns:
            Ergebnis-Dict mit success und message
        """
        if function_name not in self._ALLOWED_FUNCTIONS:
            return {"success": False, "message": f"Unbekannte Funktion: {function_name}"}
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

        # Relative Helligkeit: brighter/dimmer
        if state in ("brighter", "dimmer"):
            current_brightness = 50  # Fallback
            ha_state = await self.ha.get_state(entity_id)
            if ha_state and ha_state.get("state") == "on":
                attrs = ha_state.get("attributes", {})
                # HA gibt brightness als 0-255 zurueck
                raw = attrs.get("brightness", 128)
                current_brightness = round(raw / 255 * 100)
            step = 15
            new_brightness = current_brightness + step if state == "brighter" else current_brightness - step
            new_brightness = max(5, min(100, new_brightness))
            service_data = {"entity_id": entity_id, "brightness_pct": new_brightness}
            success = await self.ha.call_service("light", "turn_on", service_data)
            direction = "heller" if state == "brighter" else "dunkler"
            return {"success": success, "message": f"Licht {room} {direction} auf {new_brightness}%"}

        service_data = {"entity_id": entity_id}
        if "brightness" in args and state == "on":
            service_data["brightness_pct"] = args["brightness"]
        # Phase 9: Transition-Parameter (sanftes Dimmen) — muss int/float sein
        if "transition" in args:
            try:
                service_data["transition"] = int(args["transition"])
            except (ValueError, TypeError):
                # LLM schickt manchmal "smooth" statt Zahl — Default 2s
                service_data["transition"] = 2
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
        try:
            offset = float(args.get("offset", 0))
        except (ValueError, TypeError):
            return {"success": False, "message": f"Ungueltiger Offset: {args.get('offset')}"}
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
        """Raumthermostat-Modus: Temperatur pro Raum setzen."""
        room = args["room"]
        entity_id = await self._find_entity("climate", room)
        if not entity_id:
            return {"success": False, "message": f"Kein Thermostat in '{room}' gefunden"}

        # Relative Anpassung: warmer/cooler
        adjust = args.get("adjust")
        if adjust in ("warmer", "cooler"):
            ha_state = await self.ha.get_state(entity_id)
            current_temp = 21.0  # Fallback
            if ha_state:
                attrs = ha_state.get("attributes", {})
                current_temp = float(attrs.get("temperature", 21.0))
            step = 1.0
            temp = current_temp + step if adjust == "warmer" else current_temp - step
            # Sicherheitsgrenzen
            security = yaml_config.get("security", {}).get("climate_limits", {})
            temp = max(security.get("min", 5), min(security.get("max", 30), temp))
        elif "temperature" in args:
            temp = args["temperature"]
        else:
            return {"success": False, "message": "Keine Temperatur angegeben"}

        service_data = {"entity_id": entity_id, "temperature": temp}
        if "mode" in args:
            service_data["hvac_mode"] = args["mode"]

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        direction = ""
        if adjust == "warmer":
            direction = "waermer auf "
        elif adjust == "cooler":
            direction = "kaelter auf "
        return {"success": success, "message": f"{room} {direction}{temp}°C"}

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

        entity_id = await self._find_entity("cover", room)

        # Relative Anpassung: up/down
        adjust = args.get("adjust")
        if adjust in ("up", "down"):
            if not entity_id:
                return {"success": False, "message": f"Kein Rollladen in '{room}' gefunden"}
            current_position = 50  # Fallback
            ha_state = await self.ha.get_state(entity_id)
            if ha_state:
                attrs = ha_state.get("attributes", {})
                current_position = int(attrs.get("current_position", 50))
            step = 20
            position = current_position + step if adjust == "up" else current_position - step
            position = max(0, min(100, position))
        elif "position" in args:
            try:
                position = max(0, min(100, int(args["position"])))
            except (ValueError, TypeError):
                return {"success": False, "message": f"Ungueltige Position: {args.get('position')}"}
        else:
            return {"success": False, "message": "Keine Position angegeben"}

        # Sonderfall: "all" -> alle Rolllaeden schalten
        if room.lower() == "all":
            return await self._exec_set_cover_all(position)

        if not entity_id:
            return {"success": False, "message": f"Kein Rollladen in '{room}' gefunden"}

        # Sicherheitscheck: Garagentore duerfen nicht ueber set_cover gesteuert werden
        states = await self.ha.get_states()
        entity_state = next((s for s in (states or []) if s.get("entity_id") == entity_id), {})
        if not await self._is_safe_cover(entity_id, entity_state):
            return {"success": False, "message": f"'{room}' ist ein Garagentor/Tor — das darf aus Sicherheitsgruenden nicht automatisch gesteuert werden."}

        success = await self.ha.call_service(
            "cover", "set_cover_position",
            {"entity_id": entity_id, "position": position},
        )
        direction = ""
        if adjust == "up":
            direction = "hoch auf "
        elif adjust == "down":
            direction = "runter auf "
        return {"success": success, "message": f"Rollladen {room} {direction}{position}%"}

    # Garagentore und andere gefaehrliche Cover-Typen NIEMALS automatisch steuern
    _EXCLUDED_COVER_CLASSES = {"garage_door", "gate", "door"}

    async def _is_safe_cover(self, entity_id: str, state: dict) -> bool:
        """Prueft ob ein Cover sicher automatisch gesteuert werden darf.

        Filtert Garagentore und als inaktiv markierte Covers aus.
        """
        attrs = state.get("attributes", {})
        device_class = attrs.get("device_class", "")

        # 1. HA device_class pruefen (garage_door, gate, door)
        if device_class in self._EXCLUDED_COVER_CLASSES:
            return False

        # 2. Entity-ID Heuristik (garage, tor, gate) — Word-Boundary fuer 'tor'
        #    damit 'motor', 'monitor' etc. nicht faelschlich matchen
        eid_lower = entity_id.lower()
        if "garage" in eid_lower or "gate" in eid_lower:
            return False
        if re.search(r'(?:^|[_.\s])tor(?:$|[_.\s])', eid_lower):
            return False

        # 3. Lokale CoverConfig pruefen (cover_type + enabled)
        try:
            from .cover_config import load_cover_configs
            configs = load_cover_configs()
            if configs and isinstance(configs, dict):
                conf = configs.get(entity_id, {})
                # Typ-Check: Garagentore/Tore sind unsicher
                if conf.get("cover_type") in self._EXCLUDED_COVER_CLASSES:
                    return False
                # Enabled-Check: Deaktivierte Covers werden nicht gesteuert
                if conf.get("enabled") is False:
                    return False
        except Exception as e:
            # Fail-safe: Bei CoverConfig-Fehler blockieren statt durchlassen
            logger.warning("CoverConfig laden fehlgeschlagen fuer %s: %s — blockiere sicherheitshalber", entity_id, e)
            return False

        return True

    async def _exec_set_cover_all(self, position: int) -> dict:
        """Alle Rolllaeden auf eine Position setzen (Garagentore ausgeschlossen)."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Ich kann gerade nicht auf die Geraete zugreifen. Versuch es bitte gleich nochmal."}

        count = 0
        skipped = []
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
                continue

            if not await self._is_safe_cover(eid, s):
                friendly = s.get("attributes", {}).get("friendly_name", eid)
                skipped.append(friendly)
                logger.info("Cover uebersprungen (Sicherheitsfilter): %s", eid)
                continue

            await self.ha.call_service(
                "cover", "set_cover_position",
                {"entity_id": eid, "position": position},
            )
            count += 1

        msg = f"Alle Rolllaeden auf {position}% ({count} geschaltet)"
        if skipped:
            msg += f". Uebersprungen (Garagentor/Tor): {', '.join(skipped)}"

        return {"success": True, "message": msg}

    # Erlaubte Service-Data Keys fuer _exec_call_service (Whitelist)
    _CALL_SERVICE_ALLOWED_KEYS = frozenset({
        "brightness", "brightness_pct", "color_temp", "rgb_color", "hs_color",
        "temperature", "target_temp_high", "target_temp_low", "hvac_mode",
        "position", "tilt_position",
        "volume_level", "media_content_id", "media_content_type", "source",
        "message", "title", "data",
        "option", "value", "code",
    })

    async def _exec_call_service(self, args: dict) -> dict:
        """Generischer HA Service-Aufruf (fuer Routinen wie Guest WiFi)."""
        domain = args.get("domain", "")
        service = args.get("service", "")
        entity_id = args.get("entity_id", "")
        if not domain or not service:
            return {"success": False, "message": "domain und service erforderlich"}

        # Sicherheitscheck: Cover-Services fuer Garagentore blockieren
        # Bypass-sicher: Prueft ALLE Domains wenn entity_id ein Cover ist
        is_cover_entity = entity_id.startswith("cover.")
        is_cover_domain = domain == "cover"

        if is_cover_domain and not entity_id:
            # Cover-Domain ohne entity_id blockieren — koennte alle Cover betreffen
            return {"success": False, "message": "cover-Service ohne entity_id nicht erlaubt (Sicherheitssperre)."}

        if is_cover_entity or is_cover_domain:
            states = await self.ha.get_states()
            entity_state = next((s for s in (states or []) if s.get("entity_id") == entity_id), {})
            if not await self._is_safe_cover(entity_id, entity_state):
                return {"success": False, "message": f"Sicherheitssperre: '{entity_id}' ist ein Garagentor/Tor und darf nicht automatisch gesteuert werden."}

        service_data = {"entity_id": entity_id} if entity_id else {}
        # Nur erlaubte Service-Data Keys uebernehmen (Whitelist)
        for k, v in args.items():
            if k in self._CALL_SERVICE_ALLOWED_KEYS:
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
        media_type = args.get("media_type", "music")
        if query and action == "play":
            success = await self.ha.call_service(
                "media_player", "play_media",
                {
                    "entity_id": entity_id,
                    "media_content_id": query,
                    "media_content_type": media_type,
                },
            )
            return {"success": success, "message": f"Suche '{query}' wird abgespielt"}

        # Volume-Steuerung (absolut und relativ)
        if action in ("volume", "volume_up", "volume_down"):
            if action == "volume":
                volume_pct = args.get("volume")
                if volume_pct is None:
                    return {"success": False, "message": "Keine Lautstaerke angegeben"}
            else:
                # Relative Steuerung: aktuelle Lautstaerke holen und anpassen
                state = await self.ha.get_state(entity_id)
                current = 0.5
                if state and "attributes" in state:
                    current = state["attributes"].get("volume_level", 0.5)
                step = 0.1  # ±10%
                new_level = current + step if action == "volume_up" else current - step
                volume_pct = max(0, min(100, round(new_level * 100)))

            volume_level = max(0.0, min(1.0, float(volume_pct) / 100.0))
            success = await self.ha.call_service(
                "media_player", "volume_set",
                {"entity_id": entity_id, "volume_level": volume_level},
            )
            direction = "lauter" if action == "volume_up" else "leiser" if action == "volume_down" else ""
            msg = f"Lautstaerke {direction} auf {int(volume_pct)}%" if direction else f"Lautstaerke auf {int(volume_pct)}%"
            return {"success": success, "message": msg}

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
            # Fallback: media_title aus bereits geladenem State als Suche nutzen
            media_title = attrs.get("media_title", "")
            if media_title:
                success = await self.ha.call_service(
                    "media_player", "play_media",
                    {
                        "entity_id": to_entity,
                        "media_content_id": media_title,
                        "media_content_type": media_content_type or "music",
                    },
                )
            else:
                return {
                    "success": False,
                    "message": f"Kein uebertragbarer Inhalt in '{from_room}' gefunden (weder Content-ID noch Titel)",
                }

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

            # Alexa/Echo: Keine Audio-Dateien, stattdessen notify.alexa_media
            alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
            if speaker_entity and speaker_entity in alexa_speakers:
                svc_name = "alexa_media_" + speaker_entity.replace("media_player.", "", 1)
                success = await self.ha.call_service(
                    "notify", svc_name,
                    {"message": message, "data": {"type": "tts"}},
                )
            elif tts_entity and speaker_entity:
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker_entity,
                        "message": message,
                    },
                )
            elif speaker_entity:
                # Fallback: Legacy TTS Service
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": speaker_entity,
                        "message": message,
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

            if speaker:
                alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
                if speaker in alexa_speakers:
                    svc_name = "alexa_media_" + speaker.replace("media_player.", "", 1)
                    success = await self.ha.call_service(
                        "notify", svc_name,
                        {"message": message, "data": {"type": "tts"}},
                    )
                elif tts_entity:
                    success = await self.ha.call_service(
                        "tts", "speak",
                        {
                            "entity_id": tts_entity,
                            "media_player_entity_id": speaker,
                            "message": message,
                        },
                    )
                else:
                    success = False
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
            # Termin mit Uhrzeit — ISO8601-Format fuer HA
            service_data["start_date_time"] = f"{date_str}T{start_time}:00"
            if end_time:
                service_data["end_date_time"] = f"{date_str}T{end_time}:00"
            else:
                # Standard: +1 Stunde
                try:
                    start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
                    end_dt = start_dt + timedelta(hours=1)
                    service_data["end_date_time"] = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    service_data["end_date_time"] = f"{date_str}T{start_time}:00"
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
                # HA gibt start/end als ISO-String oder als Dict mit date/dateTime zurueck
                evt_start = target_event.get("start", start)
                evt_end = target_event.get("end", end)
                if isinstance(evt_start, dict):
                    evt_start = evt_start.get("dateTime", evt_start.get("date", start))
                if isinstance(evt_end, dict):
                    evt_end = evt_end.get("dateTime", evt_end.get("date", end))
                success = await self.ha.call_service(
                    "calendar", "delete_event",
                    {
                        "entity_id": calendar_entity,
                        "start_date_time": evt_start,
                        "end_date_time": evt_end,
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
        """Phase 11.3: Kalender-Termin verschieben (Delete + Re-Create).

        Atomisch: Wenn Create fehlschlaegt, wird der alte Termin wiederhergestellt.
        """
        title = args["title"]
        old_date = args["old_date"]
        new_date = args["new_date"]
        new_start = args.get("new_start_time", "")
        new_end = args.get("new_end_time", "")

        # Alten Termin finden um Start/End fuer Rollback zu merken
        old_start_time = args.get("old_start_time", "")
        old_end_time = args.get("old_end_time", "")

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

        # 3. Rollback: Alten Termin wiederherstellen
        logger.warning("Reschedule-Rollback: Stelle alten Termin '%s' am %s wieder her", title, old_date)
        rollback_result = await self._exec_create_calendar_event({
            "title": title,
            "date": old_date,
            "start_time": old_start_time,
            "end_time": old_end_time,
        })
        if rollback_result.get("success"):
            return {
                "success": False,
                "message": f"Neuer Termin konnte nicht erstellt werden. Alter Termin '{title}' am {old_date} wiederhergestellt.",
            }
        return {
            "success": False,
            "message": f"ACHTUNG: Alter Termin geloescht, neuer konnte nicht erstellt werden, Rollback fehlgeschlagen. Termin '{title}' manuell erstellen!",
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
        """Phase 10.1: Findet einen TTS-Speaker in einem bestimmten Raum.

        Sucht zuerst in der Konfiguration (room_speakers),
        dann per Entity-Name-Matching (nur echte Speaker, keine TVs).
        """
        # 1. Konfiguriertes Mapping pruefen
        room_speakers = yaml_config.get("multi_room", {}).get("room_speakers", {})
        room_lower = room.lower().replace(" ", "_")
        for cfg_room, entity_id in (room_speakers or {}).items():
            if cfg_room.lower() == room_lower:
                return entity_id

        # 2. Entity-Name-Matching (nur echte Speaker, keine TVs/Receiver)
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})
            if room_lower in entity_id.lower() and self._is_tts_speaker(entity_id, attributes):
                return entity_id
        return None

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

    # Entities die KEINE TTS-Speaker sind (TVs, Receiver, Streaming-Boxen)
    # Hinweis: Alexa/Echo nicht mehr ausgeschlossen — wird ueber
    # sounds.alexa_speakers Config behandelt (notify statt Audio)
    _EXCLUDED_SPEAKER_PATTERNS = (
        "tv", "fernseher", "television", "fire_tv", "firetv", "apple_tv",
        "appletv", "chromecast", "roku", "shield", "receiver", "avr",
        "denon", "marantz", "yamaha_receiver", "onkyo", "pioneer",
        "soundbar", "xbox", "playstation", "ps5", "ps4", "nintendo",
        "kodi", "plex", "emby", "jellyfin", "vlc", "mpd",
    )

    def _is_tts_speaker(self, entity_id: str, attributes: dict = None) -> bool:
        """Prueft ob ein media_player ein TTS-faehiger Speaker ist (kein TV etc.)."""
        if not entity_id.startswith("media_player."):
            return False
        entity_lower = entity_id.lower()
        for pattern in self._EXCLUDED_SPEAKER_PATTERNS:
            if pattern in entity_lower:
                return False
        if attributes:
            device_class = (attributes.get("device_class") or "").lower()
            if device_class in ("tv", "receiver"):
                return False
        return True

    async def _find_tts_speaker(self) -> Optional[str]:
        """Findet einen TTS-faehigen Speaker (kein TV/Receiver)."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})
            if self._is_tts_speaker(entity_id, attributes):
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

    @staticmethod
    def _normalize_name(text: str) -> str:
        """Normalisiert Umlaute und Sonderzeichen fuer Entity-Matching."""
        n = text.lower()
        # Unicode-Umlaute zuerst
        n = n.replace("ü", "u").replace("ä", "a").replace("ö", "o").replace("ß", "ss")
        # Dann ASCII-Digraphen
        n = n.replace("ue", "u").replace("ae", "a").replace("oe", "o")
        return n.replace(" ", "_")

    async def _find_entity(self, domain: str, search: str) -> Optional[str]:
        """Findet eine Entity anhand von Domain und Suchbegriff.

        1. MindHome Device-DB (schnell, gezielt nach Domain + Raum)
        2. Fallback: Alle HA-States durchsuchen
        """
        if not search:
            return None

        # MindHome Device-Search (schnell, DB-basiert)
        try:
            devices = await self.ha.search_devices(domain=domain, room=search)
            if devices:
                return devices[0]["ha_entity_id"]
        except Exception as e:
            logger.debug("MindHome device search failed, using HA fallback: %s", e)

        # Fallback: Alle HA-States durchsuchen
        states = await self.ha.get_states()
        if not states:
            return None

        search_norm = self._normalize_name(search)

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(f"{domain}."):
                continue

            # Entity-ID Match (normalisiert)
            name = entity_id.split(".", 1)[1]
            if search_norm in self._normalize_name(name):
                return entity_id

            # Friendly name Match (normalisiert)
            friendly = state.get("attributes", {}).get("friendly_name", "")
            if friendly and search_norm in self._normalize_name(friendly):
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

    # ------------------------------------------------------------------
    # Neue Features: Timer, Broadcast, Kamera, Conditionals, Energie, Web
    # ------------------------------------------------------------------

    async def _exec_set_timer(self, args: dict) -> dict:
        """Setzt einen allgemeinen Timer."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.timer_manager.create_timer(
            duration_minutes=args["duration_minutes"],
            label=args.get("label", ""),
            room=args.get("room", ""),
            person=args.get("person", ""),
            action_on_expire=args.get("action_on_expire"),
        )

    async def _exec_cancel_timer(self, args: dict) -> dict:
        """Bricht einen Timer ab."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.timer_manager.cancel_timer(label=args.get("label", ""))

    async def _exec_get_timer_status(self, args: dict) -> dict:
        """Zeigt Timer-Status an."""
        import assistant.main as main_module
        brain = main_module.brain
        return brain.timer_manager.get_status()

    async def _exec_set_reminder(self, args: dict) -> dict:
        """Setzt eine Erinnerung fuer eine bestimmte Uhrzeit."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.timer_manager.create_reminder(
            time_str=args["time"],
            label=args["label"],
            date_str=args.get("date", ""),
            room=args.get("room", ""),
            person=args.get("person", ""),
        )

    async def _exec_set_wakeup_alarm(self, args: dict) -> dict:
        """Stellt einen Wecker."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.timer_manager.set_wakeup_alarm(
            time_str=args["time"],
            label=args.get("label", "Wecker"),
            room=args.get("room", ""),
            repeat=args.get("repeat", ""),
        )

    async def _exec_cancel_alarm(self, args: dict) -> dict:
        """Loescht einen Wecker."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.timer_manager.cancel_alarm(
            label=args.get("label", ""),
        )

    async def _exec_get_alarms(self, args: dict) -> dict:
        """Zeigt alle aktiven Wecker an."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.timer_manager.get_alarms()

    async def _exec_broadcast(self, args: dict) -> dict:
        """Sendet eine Durchsage an alle Lautsprecher."""
        message = args.get("message", "")
        if not message:
            return {"success": False, "message": "Keine Nachricht angegeben."}

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Keine Verbindung zu Home Assistant."}

        # Alle Media-Player mit TTS-Faehigkeit finden
        speakers = []
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("media_player."):
                speakers.append(eid)

        if not speakers:
            return {"success": False, "message": "Keine Lautsprecher gefunden."}

        # TTS an alle Speaker senden
        count = 0
        tts_entity = yaml_config.get("tts", {}).get("entity", "tts.piper")
        alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
        for speaker in speakers:
            try:
                if speaker in alexa_speakers:
                    svc_name = "alexa_media_" + speaker.replace("media_player.", "", 1)
                    await self.ha.call_service(
                        "notify", svc_name,
                        {"message": message, "data": {"type": "tts"}},
                    )
                else:
                    await self.ha.call_service("tts", "speak", {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker,
                        "message": message,
                    })
                count += 1
            except Exception as e:
                logger.debug("Broadcast an %s fehlgeschlagen: %s", speaker, e)

        return {
            "success": count > 0,
            "message": f"Durchsage an {count} Lautsprecher gesendet: \"{message}\"",
        }

    async def _exec_get_camera_view(self, args: dict) -> dict:
        """Holt und beschreibt ein Kamera-Bild."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.camera_manager.get_camera_view(
            camera_name=args.get("camera_name", ""),
        )

    async def _exec_create_conditional(self, args: dict) -> dict:
        """Erstellt einen bedingten Befehl."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.conditional_commands.create_conditional(
            trigger_type=args["trigger_type"],
            trigger_value=args["trigger_value"],
            action_function=args["action_function"],
            action_args=args.get("action_args", {}),
            label=args.get("label", ""),
            ttl_hours=args.get("ttl_hours", 24),
            one_shot=args.get("one_shot", True),
        )

    async def _exec_list_conditionals(self, args: dict) -> dict:
        """Listet bedingte Befehle auf."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.conditional_commands.list_conditionals()

    async def _exec_get_energy_report(self, args: dict) -> dict:
        """Zeigt Energie-Bericht an."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.energy_optimizer.get_energy_report()

    async def _exec_web_search(self, args: dict) -> dict:
        """Fuehrt eine Web-Suche durch."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.web_search.search(query=args.get("query", ""))

    async def _exec_get_security_score(self, args: dict) -> dict:
        """Gibt den aktuellen Sicherheits-Score zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            result = await brain.threat_assessment.get_security_score()
            details = result.get("details", [])
            return {
                "success": True,
                "score": result["score"],
                "level": result["level"],
                "details": ", ".join(details) if details else "Alles in Ordnung",
            }
        except Exception as e:
            return {"success": False, "message": f"Sicherheits-Check fehlgeschlagen: {e}"}

    async def _exec_get_room_climate(self, args: dict) -> dict:
        """Gibt Raumklima-Daten zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            result = await brain.health_monitor.get_status()
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "message": f"Raumklima-Check fehlgeschlagen: {e}"}

    async def _exec_get_active_intents(self, args: dict) -> dict:
        """Gibt aktive Vorhaben/Intents zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            intents = await brain.intent_tracker.get_active_intents()
            if not intents:
                return {"success": True, "message": "Keine anstehenden Vorhaben gemerkt.", "intents": []}
            summaries = []
            for intent in intents:
                summaries.append({
                    "intent": intent.get("intent", ""),
                    "deadline": intent.get("deadline", ""),
                    "person": intent.get("person", ""),
                    "reminder": intent.get("reminder_text", ""),
                })
            return {"success": True, "count": len(summaries), "intents": summaries}
        except Exception as e:
            return {"success": False, "message": f"Intent-Abfrage fehlgeschlagen: {e}"}

    async def _exec_get_wellness_status(self, args: dict) -> dict:
        """Gibt den Wellness-Status des Users zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            status = {}

            # Mood/Stress
            mood_data = brain.mood.get_current_mood()
            status["mood"] = mood_data.get("mood", "neutral")
            status["stress_level"] = mood_data.get("stress_level", 0.0)

            # PC-Nutzungsdauer aus Redis
            if brain.memory.redis:
                pc_start = await brain.memory.redis.get("mha:wellness:pc_start")
                if pc_start:
                    from datetime import datetime
                    try:
                        start_dt = datetime.fromisoformat(pc_start)
                        minutes = (datetime.now() - start_dt).total_seconds() / 60
                        status["pc_minutes"] = round(minutes)
                    except (ValueError, TypeError):
                        pass

                last_hydration = await brain.memory.redis.get("mha:wellness:last_hydration")
                if last_hydration:
                    status["last_hydration"] = last_hydration

            # Aktivitaet
            try:
                detection = await brain.activity.detect_activity()
                status["activity"] = detection.get("activity", "unknown")
            except Exception:
                pass

            return {"success": True, "message": str(status), **status}
        except Exception as e:
            return {"success": False, "message": f"Wellness-Check fehlgeschlagen: {e}"}

    async def _exec_get_device_health(self, args: dict) -> dict:
        """Gibt den Geraete-Gesundheitsstatus zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            status = await brain.device_health.get_status()
            # Aktuelle Anomalien pruefen
            alerts = await brain.device_health.check_all()
            alert_msgs = [a.get("message", "") for a in alerts[:5]] if alerts else []
            return {
                "success": True,
                "message": f"{len(alerts)} Anomalie(n)" if alerts else "Alle Geraete normal",
                "alerts": alert_msgs,
                **status,
            }
        except Exception as e:
            return {"success": False, "message": f"Geraete-Check fehlgeschlagen: {e}"}

    async def _exec_get_learned_patterns(self, args: dict) -> dict:
        """Gibt erkannte Verhaltensmuster zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            patterns = await brain.learning_observer.get_learned_patterns()
            if not patterns:
                return {"success": True, "message": "Noch keine Muster erkannt.", "patterns": []}
            summaries = []
            for p in patterns:
                summaries.append({
                    "action": p.get("action", ""),
                    "time": p.get("time_slot", ""),
                    "count": p.get("count", 0),
                    "weekday": p.get("weekday", -1),
                })
            return {
                "success": True,
                "count": len(summaries),
                "message": f"{len(summaries)} Muster erkannt",
                "patterns": summaries,
            }
        except Exception as e:
            return {"success": False, "message": f"Muster-Abfrage fehlgeschlagen: {e}"}

    async def _exec_describe_doorbell(self, args: dict) -> dict:
        """Beschreibt was die Tuerkamera zeigt."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            description = await brain.camera_manager.describe_doorbell()
            if description:
                return {"success": True, "message": description}
            return {
                "success": False,
                "message": "Tuerkamera nicht verfuegbar oder kein Bild erhalten.",
            }
        except Exception as e:
            return {"success": False, "message": f"Tuerkamera-Abfrage fehlgeschlagen: {e}"}
