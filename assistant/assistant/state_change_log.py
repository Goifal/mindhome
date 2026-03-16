"""
State Change Log — Trackt WARUM Geraete ihren Zustand aendern.

Jede State-Change wird mit Quelle geloggt:
- jarvis: JARVIS hat die Aktion ausgefuehrt (voice/chat command)
- automation: HA-Automation hat gefeuert
- user_physical: Physischer Schalter/App (manuell)
- unknown: Quelle nicht bestimmbar

Die letzten N Aenderungen werden im Ring-Buffer gehalten und
koennen dem LLM als Kontext mitgegeben werden.
"""

import json
import logging
import time
from collections import deque
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_KEY_LOG = "mha:state_change_log"
MAX_LOG_ENTRIES = 30
LOG_TTL_SECONDS = 6 * 3600  # 6 Stunden

# =========================================================================
# DEVICE DEPENDENCIES — Rollen-basiertes Matching via Entity Annotations
# =========================================================================
#
# WICHTIG: Diese Regeln steuern NICHTS. Sie geben JARVIS rein kognitives
# Verstaendnis darueber welche Geraetezustaende sich gegenseitig beeinflussen.
#
# Format:
#   "role":    Entity-Annotation-Rolle (aus entity_roles_defaults.yaml)
#   "state":   Zustand der die Regel triggert ("on", "heat", "playing", ...)
#   "affects": Betroffene Rolle ODER HA-Domain
#   "effect":  Beschreibung des Effekts
#   "hint":    Kurzer Hinweis fuer den LLM-Prompt
#   "same_room": (optional) True = Konflikt nur im selben Raum relevant
#
# Matching: Jede Entity wird ueber get_entity_annotation() ihrer Rolle
# zugeordnet. Dadurch matcht z.B. role="window_contact" ALLE Fensterkontakte
# unabhaengig von Benennung (binary_sensor.fenster_kueche, binary_sensor.wz_01, ...)
#
DEVICE_DEPENDENCIES = [

    # =====================================================================
    # 1. FENSTER / TUEREN → KLIMA / ENERGIE / SICHERHEIT
    # =====================================================================
    {
        "role": "window_contact", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Heizung/Kuehlung ineffizient bei offenem Fenster",
        "hint": "Fenster offen → Heizenergie geht verloren",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Fenster offen bei Abwesenheit → Einbruchsrisiko",
        "hint": "Fenster offen → Sicherheitsrisiko bei Abwesenheit",
        "severity": "high",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Fenster offen + Ventilator → Durchzug",
        "hint": "Fenster offen + Ventilator → Durchzug, Tueren knallen",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Fenster offen + KWL → Lueftungseffizienz sinkt",
        "hint": "Fenster offen → KWL arbeitet ineffizient, Fenster zu fuer optimale Lueftung",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Waermeverlust durch offene Tuer",
        "hint": "Tuer offen → beeinflusst Raumtemperatur",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Tuer offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Haustuer steht offen → Sicherheit pruefen",
        "severity": "high",
    },
    {
        "role": "garage_door", "state": "open",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Garagentor offen → Sicherheitsrisiko",
        "hint": "Garage offen → Sicherheit pruefen",
        "severity": "high",
    },
    {
        "role": "garage_door", "state": "open",
        "affects": "climate", "same_room": False,
        "effect": "Garagentor offen → Kaelte zieht in angrenzende Raeume",
        "hint": "Garage offen → beeinflusst angrenzende Raeume",
        "severity": "info",
    },
    {
        "role": "gate", "state": "open",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Tor offen → ungesicherter Zugang zum Grundstueck",
        "hint": "Tor offen → Grundstueck nicht gesichert",
        "severity": "high",
    },

    # =====================================================================
    # 2. ROLLLADEN / JALOUSIE / MARKISE → KLIMA / LICHT
    # =====================================================================
    {
        "role": "blinds", "state": "open",
        "affects": "climate", "same_room": True,
        "effect": "Sonneneinstrahlung erhoeht Raumtemperatur / Waermeverlust nachts",
        "hint": "Rollladen offen → beeinflusst Raumklima",
        "severity": "info",
    },
    {
        "role": "blinds", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Kein Tageslicht bei geschlossenem Rollladen",
        "hint": "Rollladen zu → Kunstlicht noetig",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "open",
        "affects": "climate", "same_room": True,
        "effect": "Sonneneinstrahlung beeinflusst Raumklima",
        "hint": "Rollladen offen → Raumklima beeinflusst",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Kein Tageslicht bei geschlossenem Rollladen",
        "hint": "Rollladen zu → Kunstlicht noetig",
        "severity": "info",
    },
    {
        "role": "awning", "state": "open",
        "affects": "climate", "same_room": False,
        "effect": "Markise ausgefahren → Beschattung aktiv, Raum kuehler",
        "hint": "Markise draussen → schuetzt vor Sonneneinstrahlung",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Vorhang zu → weniger Tageslicht",
        "hint": "Vorhang zu → Kunstlicht noetig",
        "severity": "info",
    },

    # =====================================================================
    # 3. KLIMA / HEIZUNG / KUEHLUNG → ENERGIE / FENSTER
    # =====================================================================
    {
        "role": "thermostat", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Thermostat heizt + Fenster offen → Energieverschwendung",
        "hint": "Heizung an + Fenster offen → Energie wird verschwendet",
        "severity": "high",
    },
    {
        "role": "thermostat", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Thermostat aus bei Kaelte → Frostgefahr",
        "hint": "Thermostat aus + kalt → Frostschutz beachten",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "heat",
        "affects": "notify", "same_room": False,
        "effect": "Waermepumpe nachts → Laermbelaestigung Nachbarn",
        "hint": "Waermepumpe nachts → Nachbarn koennten sich beschweren",
        "severity": "info",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Fussbodenheizung + Fenster offen → viel Energieverlust",
        "hint": "Fussbodenheizung → Fenster kurz lueften, nicht kippen",
        "severity": "high",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Heizkoerper heizt + Fenster offen → Energieverschwendung",
        "hint": "Heizkoerper an + Fenster offen → Energie geht verloren",
        "severity": "high",
    },

    # =====================================================================
    # 5. PRAESENZ / BEWEGUNG → LICHT / KLIMA / MEDIA / SICHERHEIT
    # =====================================================================
    {
        "role": "motion", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Bewegung bei aktivem Alarm → moeglicher Einbruch",
        "hint": "Bewegung bei scharfem Alarm → Einbruch-Warnung",
        "severity": "high",
    },
    {
        "role": "presence", "state": "off",
        "affects": "climate", "same_room": False,
        "effect": "Niemand zuhause → Heizung/Kuehlung unnoetig",
        "hint": "Abwesend → Energie sparen moeglich",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "light", "same_room": False,
        "effect": "Niemand zuhause → Licht unnoetig",
        "hint": "Abwesend → Licht sollte aus sein",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "media_player", "same_room": False,
        "effect": "Niemand zuhause → Medien laufen umsonst",
        "hint": "Abwesend → Medien sollten aus sein",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "outlet", "same_room": False,
        "effect": "Niemand zuhause → Standby-Geraete laufen",
        "hint": "Abwesend → Standby-Geraete ausschalten",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Raum leer → Licht unnoetig",
        "hint": "Raum leer → Licht brennt umsonst",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Raum leer → Heizung/Kuehlung unnoetig",
        "hint": "Raum leer → Energie sparen moeglich",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "media_player", "same_room": True,
        "effect": "Raum leer → Medien spielen fuer niemanden",
        "hint": "Raum leer → Medien laufen umsonst",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "fan", "same_room": True,
        "effect": "Raum leer → Ventilator unnoetig",
        "hint": "Raum leer → Ventilator laeuft umsonst",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Im Bett → Lichter sollten aus sein",
        "hint": "Bett belegt → Lichter ausschalten",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Im Bett → Medien leiser oder aus",
        "hint": "Schlafenszeit → Medien runterdrehen",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Im Bett → Schlaftemperatur einstellen (kuehler)",
        "hint": "Schlafenszeit → Temperatur fuer Schlaf anpassen",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Im Bett → Tueren sollten abgeschlossen sein",
        "hint": "Schlafenszeit → Tueren abschliessen",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Im Bett → Rolllaeden sollten zu sein",
        "hint": "Schlafenszeit → Rolllaeden schliessen",
        "severity": "info",
    },

    # =====================================================================
    # 6. SICHERHEIT — RAUCH / GAS / CO / WASSER / EINBRUCH
    # =====================================================================
    {
        "role": "smoke", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
        "severity": "critical",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Rauchmelder → alle Lichter an fuer Fluchtweg",
        "hint": "Rauch → Beleuchtung fuer Fluchtweg einschalten",
        "severity": "critical",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Rauchmelder → Rolllaeden hoch fuer Fluchtweg",
        "hint": "Rauch → Rolllaeden oeffnen fuer Fluchtweg",
        "severity": "critical",
    },
    {
        "role": "co", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Kohlenmonoxid erkannt → LEBENSGEFAHRLICH",
        "hint": "CO erkannt → SOFORT ALARM, Fenster oeffnen, Haus verlassen",
        "severity": "critical",
    },
    {
        "role": "co", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "CO erkannt → Lueftung auf Maximum",
        "hint": "CO → maximale Belueftung noetig",
        "severity": "critical",
    },
    {
        "role": "gas", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Gas erkannt → Explosionsgefahr",
        "hint": "Gas erkannt → SOFORT ALARM, kein Funke, Haus verlassen",
        "severity": "critical",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM, Hauptventil schliessen",
        "severity": "critical",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Sabotage-Kontakt ausgeloest → Geraet manipuliert",
        "hint": "Sabotage erkannt → Geraet wurde manipuliert",
        "severity": "critical",
    },
    {
        "role": "vibration", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Vibration erkannt → Einbruchsversuch moeglich",
        "hint": "Vibration an Tuer/Fenster → Einbruchsversuch?",
        "severity": "high",
    },
    {
        "role": "lock", "state": "unlocked",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Schloss offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Tuer nicht abgeschlossen → Sicherheit pruefen",
        "severity": "high",
    },
    {
        "role": "lock", "state": "unlocked",
        "affects": "notify", "same_room": False,
        "effect": "Schloss offen nachts → Warnung",
        "hint": "Tuer nachts nicht abgeschlossen → Hinweis geben",
        "severity": "info",
    },

    # =====================================================================
    # 7. ALARM → LICHT / KAMERA / BENACHRICHTIGUNG
    # =====================================================================
    {
        "role": "alarm", "state": "armed_away",
        "affects": "light", "same_room": False,
        "effect": "Alarm scharf (abwesend) → Praesenz simulieren",
        "hint": "Alarm scharf → Licht-Simulation gegen Einbruch",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "armed_away",
        "affects": "blinds", "same_room": False,
        "effect": "Alarm scharf (abwesend) → Rolllaeden als Schutz",
        "hint": "Alarm scharf → Rolllaeden runter fuer Sichtschutz",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "armed_night",
        "affects": "lock", "same_room": False,
        "effect": "Nacht-Alarm → alle Tueren abgeschlossen",
        "hint": "Nachtalarm → Schloss pruefen",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "light", "same_room": False,
        "effect": "Alarm ausgeloest → alle Lichter an zur Abschreckung",
        "hint": "ALARM AUSGELOEST → alle Lichter an",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "notify", "same_room": False,
        "effect": "Alarm ausgeloest → sofort benachrichtigen",
        "hint": "ALARM → sofortige Benachrichtigung",
        "severity": "high",
    },

    # =====================================================================
    # 8. MEDIEN / ENTERTAINMENT → LICHT / ROLLLADEN
    # =====================================================================
    {
        "role": "media_player", "state": "playing",
        "affects": "light", "same_room": True,
        "effect": "Medien spielen → Kino-Modus (Licht dimmen) sinnvoll",
        "hint": "Film/Musik laeuft → Licht anpassen",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "playing",
        "affects": "blinds", "same_room": True,
        "effect": "Medien spielen → Rollladen gegen Blendung",
        "hint": "TV/Film laeuft → Blendung durch Rollladen vermeiden",
        "severity": "info",
    },
    {
        "role": "tv", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "TV an → Licht anpassen fuer besseres Bild",
        "hint": "TV an → Licht dimmen sinnvoll",
        "severity": "info",
    },
    {
        "role": "tv", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "TV an → Blendung auf Bildschirm vermeiden",
        "hint": "TV an → Rollladen gegen Blendung",
        "severity": "info",
    },
    {
        "role": "projector", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Beamer an → Raum muss komplett dunkel sein",
        "hint": "Beamer an → alles abdunkeln noetig",
        "severity": "info",
    },
    {
        "role": "projector", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Beamer an → Rollladen komplett runter",
        "hint": "Beamer an → komplette Abdunklung noetig",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Gaming aktiv → Licht anpassen fuer Bildschirm",
        "hint": "Gaming-Modus → Licht dimmen sinnvoll",
        "severity": "info",
    },
    {
        "role": "speaker", "state": "playing",
        "affects": "window_contact", "same_room": True,
        "effect": "Musik laut + Fenster offen → Nachbarn stoeren",
        "hint": "Musik laut + Fenster offen → Laermbelaestigung moeglich",
        "severity": "info",
    },

    # =====================================================================
    # 9. HAUSHALTSGERAETE → BENACHRICHTIGUNG / SICHERHEIT / ENERGIE
    # =====================================================================
    {
        "role": "washing_machine", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Waschmaschine fertig → Waesche rausholen",
        "hint": "Waschmaschine fertig → User benachrichtigen",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Trockner fertig → Waesche rausholen",
        "hint": "Trockner fertig → User benachrichtigen",
        "severity": "info",
    },
    {
        "role": "dishwasher", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Geschirrspueler fertig → ausraeumen",
        "hint": "Geschirrspueler fertig → User benachrichtigen",
        "severity": "info",
    },
    {
        "role": "oven", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Backofen/Herd an → nicht vergessen",
        "hint": "Backofen laeuft → nicht vergessen auszumachen",
        "severity": "info",
    },
    {
        "role": "oven", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Herd an + niemand in Kueche → Brandgefahr",
        "hint": "Herd an → Brandgefahr wenn unbeaufsichtigt",
        "severity": "high",
    },
    {
        "role": "fridge", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Kuehlschrank offen → Lebensmittel verderben",
        "hint": "Kuehlschrank steht offen → sofort schliessen",
        "severity": "info",
    },
    {
        "role": "freezer", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Gefrierschrank Temperatur zu hoch → Lebensmittel tauen",
        "hint": "Gefrierschrank zu warm → Lebensmittel in Gefahr",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "motion", "same_room": True,
        "effect": "Saugroboter kann Bewegungsmelder ausloesen",
        "hint": "Saugroboter aktiv → Bewegungsmelder ignorieren",
        "severity": "high",
    },
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "alarm", "same_room": False,
        "effect": "Saugroboter loest Bewegungsmelder aus → kein Einbruch",
        "hint": "Saugroboter aktiv → Fehlalarm vermeiden",
        "severity": "high",
    },

    # =====================================================================
    # 10. WETTER → ROLLLADEN / MARKISE / FENSTER / BEWAESSERUNG
    # =====================================================================
    {
        "role": "wind_speed", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Starker Wind → Markise einfahren, Beschaedigungsgefahr",
        "hint": "Wind stark → Markise/Sonnensegel einfahren",
        "severity": "high",
    },
    {
        "role": "rain", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Regen → Dachfenster und offene Fenster pruefen",
        "hint": "Es regnet → Fenster pruefen, Dachfenster schliessen",
        "severity": "high",
    },
    {
        "role": "rain", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Regen → Markise einfahren",
        "hint": "Regen → Markise einfahren",
        "severity": "high",
    },
    {
        "role": "rain", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Regen → Bewaesserung unnoetig, Wasserverschwendung",
        "hint": "Es regnet → Bewaesserung stoppen",
        "severity": "high",
    },
    {
        "role": "rain", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Regen → Waesche draussen? Dachfenster offen?",
        "hint": "Regen → Waesche reinholen, Fenster pruefen",
        "severity": "info",
    },
    {
        "role": "uv_index", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "UV-Index hoch → Beschattung sinnvoll",
        "hint": "Starke UV-Strahlung → Rolllaeden/Jalousien als Schutz",
        "severity": "info",
    },
    {
        "role": "solar_radiation", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Beschattung aktivieren",
        "hint": "Sonne stark → Beschattung anpassen",
        "severity": "info",
    },
    {
        "role": "rain_sensor", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Regen erkannt → offene Fenster schliessen",
        "hint": "Regensensor → Fenster pruefen",
        "severity": "high",
    },

    # =====================================================================
    # 11. LUEFTUNG / DUNSTABZUG / KAMIN → FENSTER (UNTERDRUCK!)
    # =====================================================================
    {
        "role": "ventilation", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Lueftungsanlage aktiv → Fenster zu halten fuer Effizienz",
        "hint": "KWL laeuft → Fenster zu fuer optimale Lueftung",
        "severity": "info",
    },
    {
        "role": "fan", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Ventilator an → gefuehlte Temperatur sinkt",
        "hint": "Ventilator → kuehlt nicht, aber gefuehlt kuehler",
        "severity": "info",
    },

    # =====================================================================
    # 12. LUFTQUALITAET → LUEFTUNG / FENSTER / GESUNDHEIT
    # =====================================================================
    {
        "role": "co2", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "CO2-Wert hoch → dringend lueften",
        "hint": "CO2 hoch → Fenster oeffnen oder Lueftung verstaerken",
        "severity": "high",
    },
    {
        "role": "voc", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "VOC hoch → Schadstoffe in der Luft, lueften",
        "hint": "VOC hoch → Lueften, Schadstoffe in der Luft",
        "severity": "high",
    },
    {
        "role": "pm25", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Feinstaub hoch draussen → Fenster geschlossen halten",
        "hint": "Feinstaub draussen hoch → Fenster zu, Luftreiniger an",
        "severity": "high",
    },
    {
        "role": "pm10", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Grobstaub hoch → Fenster geschlossen halten",
        "hint": "Feinstaub hoch → Fenster zu lassen",
        "severity": "high",
    },
    {
        "role": "air_quality", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Luftqualitaet draussen schlecht → Fenster geschlossen",
        "hint": "Luftqualitaet draussen schlecht → Fenster zu",
        "severity": "high",
    },
    {
        "role": "dew_point", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Taupunkt erreicht → Kondenswasser, Schimmelgefahr",
        "hint": "Taupunkt → Schimmelgefahr, sofort lueften oder heizen",
        "severity": "high",
    },
    {
        "role": "humidity", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Luftfeuchtigkeit hoch → Lueftung noetig",
        "hint": "Feuchtigkeit hoch → Luefter/Fenster oeffnen",
        "severity": "info",
    },
    {
        "role": "humidity", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Hohe Feuchtigkeit → Schimmelgefahr",
        "hint": "Hohe Luftfeuchtigkeit → Lueften oder Entfeuchten",
        "severity": "high",
    },
    {
        "role": "radon", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Radon-Wert hoch → Lueftung wichtig",
        "hint": "Radon hoch → unbedingt lueften, gesundheitsgefaehrdend",
        "severity": "high",
    },

    # =====================================================================
    # 13. ENERGIE / SOLAR / BATTERIE / WALLBOX
    # =====================================================================
    {
        "role": "solar", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "PV produziert → Eigenverbrauch optimieren",
        "hint": "PV-Produktion → Geraete jetzt einschalten fuer Eigenverbrauch",
        "severity": "info",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Strom wird eingespeist → Eigenverbrauch erhoehen",
        "hint": "Einspeisung → besser selbst verbrauchen",
        "severity": "info",
    },
    {
        "role": "grid_consumption", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Netzbezug hoch → Strom wird teuer eingekauft",
        "hint": "Netzbezug hoch → Eigenverbrauch optimieren",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Wallbox laedt → sehr hoher Stromverbrauch (11-22kW)",
        "hint": "E-Auto laedt → hoher Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Wallbox + Waermepumpe gleichzeitig → moegliche Netzueberlast",
        "hint": "Wallbox + Waermepumpe → Ueberlastgefahr",
        "severity": "high",
    },
    {
        "role": "battery", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Batterie-Warnung → Geraet bald offline",
        "hint": "Batterie schwach → Batterie wechseln bevor Geraet ausfaellt",
        "severity": "info",
    },
    {
        "role": "outlet", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Smarte Steckdose an → Standby-Verbrauch moeglich",
        "hint": "Steckdose aktiv → Standby-Verbrauch pruefen",
        "severity": "info",
    },
    {
        "role": "power_meter", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Hoher Verbrauch erkannt → Geraet pruefen",
        "hint": "Ungewoehnlich hoher Verbrauch → Defekt oder vergessen?",
        "severity": "info",
    },

    # =====================================================================
    # 14. TUERKLINGEL / BRIEFKASTEN / PAKET
    # =====================================================================
    {
        "role": "doorbell", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Tuerklingel → jemand steht vor der Tuer",
        "hint": "Klingel → Besucher an der Tuer",
        "severity": "info",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Klingel nachts → Aussenlicht an",
        "hint": "Klingel → Eingangsbereich beleuchten",
        "severity": "info",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Klingel → Kamerabild anzeigen/aufnehmen",
        "hint": "Klingel → Tuerkamera aktivieren",
        "severity": "info",
    },
    {
        "role": "intercom", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Gegensprechanlage aktiv → Kamera zeigen",
        "hint": "Gegensprech → wer steht vor der Tuer?",
        "severity": "info",
    },

    # =====================================================================
    # 15. NETZWERK / CONNECTIVITY → GERAETE-AUSFALL
    # =====================================================================
    {
        "role": "router", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Router offline → alle WLAN-Geraete ohne Verbindung",
        "hint": "Router offline → Internet und WLAN-Geraete betroffen",
        "severity": "info",
    },
    {
        "role": "connectivity", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Verbindung verloren → Geraet nicht erreichbar",
        "hint": "Geraet offline → Verbindung pruefen",
        "severity": "info",
    },
    {
        "role": "server", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Server/NAS offline → Dienste nicht verfuegbar",
        "hint": "Server offline → Backups und Dienste betroffen",
        "severity": "info",
    },
    {
        "role": "nas", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "NAS offline → Backups und Medien nicht verfuegbar",
        "hint": "NAS offline → Datensicherung betroffen",
        "severity": "info",
    },

    # =====================================================================
    # 16. GARTEN / BEWAESSERUNG / POOL
    # =====================================================================
    {
        "role": "irrigation", "state": "on",
        "affects": "water_consumption", "same_room": False,
        "effect": "Bewaesserung laeuft → Wasserverbrauch",
        "hint": "Bewaesserung an → Wasserverbrauch beachten",
        "severity": "info",
    },
    {
        "role": "soil_moisture", "state": "on",
        "affects": "irrigation", "same_room": True,
        "effect": "Boden trocken → Bewaesserung noetig",
        "hint": "Boden trocken → Pflanzen brauchen Wasser",
        "severity": "info",
    },
    {
        "role": "pool", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Pool-Technik an → Stromverbrauch",
        "hint": "Pool-Pumpe/Heizung laeuft → Energieverbrauch beachten",
        "severity": "info",
    },
    {
        "role": "garden_light", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gartenbeleuchtung an → Stromverbrauch nachts",
        "hint": "Gartenlicht brennt → Lichtverschmutzung, Insekten",
        "severity": "info",
    },

    # =====================================================================
    # 17. FAHRZEUGE / GARAGE
    # =====================================================================
    {
        "role": "car", "state": "not_home",
        "affects": "garage_door", "same_room": False,
        "effect": "Auto weg + Garage offen → vergessen zu schliessen",
        "hint": "Auto weg, Garage offen → schliessen vergessen?",
        "severity": "info",
    },
    {
        "role": "car_battery", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Auto-Akku niedrig → laden sinnvoll",
        "hint": "E-Auto Akku niedrig → aufladen",
        "severity": "info",
    },

    # =====================================================================
    # 18. NOTFALL / PANIK / STURZERKENNUNG
    # =====================================================================
    {
        "role": "problem", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Geraete-Problem erkannt → Wartung noetig",
        "hint": "Problem/Stoerung → Geraet pruefen",
        "severity": "info",
    },

    # =====================================================================
    # 19. VERBRAUCH / FUELLSTAENDE
    # =====================================================================
    {
        "role": "water_consumption", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Hoher Wasserverbrauch → Leck oder Hahn vergessen?",
        "hint": "Wasserverbrauch hoch → Ursache pruefen",
        "severity": "info",
    },
    {
        "role": "gas_consumption", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gasverbrauch → Heizung/Warmwasser aktiv",
        "hint": "Gasverbrauch → Heizkosten beachten",
        "severity": "info",
    },

    # =====================================================================
    # 20. LICHT-SENSOR / HELLIGKEIT → LICHT / ROLLLADEN
    # =====================================================================
    {
        "role": "light_level", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Helligkeit → Kunstlicht anpassen",
        "hint": "Genug Tageslicht → Lampen koennen aus",
        "severity": "info",
    },
    {
        "role": "light_level", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Daemmerung/Helligkeit → Rolllaeden anpassen",
        "hint": "Lichtverhaeltnisse → Beschattung optimieren",
        "severity": "info",
    },

    # =====================================================================
    # 21. KAMERA / UEBERWACHUNG
    # =====================================================================
    {
        "role": "camera", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Kamera aktiv → gute Beleuchtung fuer Aufnahmen",
        "hint": "Kamera nimmt auf → Licht fuer besseres Bild",
        "severity": "info",
    },

    # =====================================================================
    # 22. UPDATE / WARTUNG
    # =====================================================================
    {
        "role": "update", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Update verfuegbar → Geraet aktualisieren",
        "hint": "Update verfuegbar → Firmware/Software aktualisieren",
        "severity": "info",
    },

    # =====================================================================
    # 23. LAERM / NOISE → KOMFORT
    # =====================================================================
    {
        "role": "noise", "state": "on",
        "affects": "notify", "same_room": True,
        "effect": "Laermpegel hoch → Quelle pruefen",
        "hint": "Laut im Raum → was verursacht den Laerm?",
        "severity": "info",
    },

    # =====================================================================
    # 24. PUMPE / VENTIL / MOTOR → ENERGIE / WARTUNG
    # =====================================================================
    {
        "role": "pump", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Pumpe laeuft → Dauerstromverbrauch",
        "hint": "Pumpe aktiv → Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "valve", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Ventil geschlossen → Durchfluss gestoppt",
        "hint": "Ventil zu → kein Durchfluss, gewollt?",
        "severity": "info",
    },

    # =====================================================================
    # 25. TEMPERATUR-SENSOREN → KLIMA / WARNUNG
    # =====================================================================
    {
        "role": "indoor_temp", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Raumtemperatur beeinflusst Heizung/Kuehlung",
        "hint": "Raumtemperatur → Heizung/Kuehlung anpassen",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Heizstrategie und Beschattung",
        "hint": "Aussentemperatur → beeinflusst Heizung, Beschattung, Bewaesserung",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Aussentemperatur hoch → Beschattung sinnvoll",
        "hint": "Heiss draussen → Rolllaeden/Jalousien schliessen",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Bewaesserungsbedarf",
        "hint": "Heiss → Pflanzen brauchen mehr Wasser",
        "severity": "info",
    },
    {
        "role": "water_temp", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Wassertemperatur → Legionellen-Schutz ab 60°C beachten",
        "hint": "Warmwasser-Temp → Legionellen-Risiko unter 60°C",
        "severity": "info",
    },
    {
        "role": "water_temp", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Warmwasser-Temperatur beeinflusst Boiler-Energieverbrauch",
        "hint": "Wassertemperatur → Energieverbrauch fuer Warmwasser",
        "severity": "info",
    },
    {
        "role": "soil_temp", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Bodentemperatur beeinflusst Pflanzenwachstum",
        "hint": "Bodentemperatur → Bewaesserung/Frostschutz anpassen",
        "severity": "info",
    },
    {
        "role": "pressure", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Luftdruckveraenderung → Wetterwechsel kommt",
        "hint": "Luftdruck faellt → Schlechtwetter im Anmarsch",
        "severity": "info",
    },

    # =====================================================================
    # 26. STROM-DETAILS → ENERGIE / WARNUNG
    # =====================================================================
    {
        "role": "current", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Stromstaerke ungewoehnlich hoch → Ueberlast moeglich",
        "hint": "Hohe Stromstaerke → Sicherung koennte ausloesen",
        "severity": "info",
    },
    {
        "role": "voltage", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Spannung ausserhalb Norm → Netzproblem",
        "hint": "Spannung anomal → Netzstabiliaet pruefen",
        "severity": "info",
    },
    {
        "role": "frequency", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Netzfrequenz abweichend → Netzinstabilitaet",
        "hint": "Netzfrequenz → Stabilitaet des Stromnetzes",
        "severity": "info",
    },
    {
        "role": "power_factor", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Schlechter Leistungsfaktor → ineffiziente Geraete",
        "hint": "Leistungsfaktor schlecht → Blindleistung, ineffizient",
        "severity": "info",
    },
    {
        "role": "energy", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Energieverbrauch ungewoehnlich → Ursache pruefen",
        "hint": "Energieverbrauch hoch → welches Geraet verbraucht soviel?",
        "severity": "info",
    },

    # =====================================================================
    # 27. LADEGERAETE / AKKUS → ENERGIE
    # =====================================================================
    {
        "role": "charger", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Ladegeraet aktiv → Stromverbrauch, bei Vollladung abschalten",
        "hint": "Ladegeraet → bei vollem Akku Stecker ziehen",
        "severity": "info",
    },
    {
        "role": "battery_charging", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Batterie laedt → Stromverbrauch bis voll",
        "hint": "Akku laedt → Stromverbrauch waehrend Ladung",
        "severity": "info",
    },

    # =====================================================================
    # 28. SITZ- / STUHLBELEGUNG → LICHT / KLIMA
    # =====================================================================
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Stuhl belegt → Person im Raum, Licht sinnvoll",
        "hint": "Stuhl belegt → jemand sitzt hier, Licht an lassen",
        "severity": "info",
    },
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Stuhl belegt → Raum ist besetzt, Klima halten",
        "hint": "Jemand sitzt → Raumklima beibehalten",
        "severity": "info",
    },
    {
        "role": "chair_occupancy", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Stuhl leer → Person hat Raum eventuell verlassen",
        "hint": "Stuhl leer → noch jemand im Raum?",
        "severity": "info",
    },

    # =====================================================================
    # 29. COMPUTER / DRUCKER / IT → ENERGIE
    # =====================================================================
    {
        "role": "pc", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "PC/Computer an → Stromverbrauch",
        "hint": "Computer laeuft → Stromverbrauch beachten",
        "severity": "info",
    },
    {
        "role": "pc", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "PC an → Bildschirmarbeit, Licht anpassen",
        "hint": "PC aktiv → Licht fuer Bildschirmarbeit anpassen",
        "severity": "info",
    },
    {
        "role": "pc", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "PC an → erzeugt Abwaerme im Raum",
        "hint": "Computer → Abwaerme beeinflusst Raumtemperatur",
        "severity": "info",
    },
    {
        "role": "printer", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Drucker an → Standby-Verbrauch wenn nicht genutzt",
        "hint": "Drucker an → Stromverbrauch, nach Nutzung ausschalten",
        "severity": "info",
    },
    {
        "role": "printer", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "3D-Drucker → Daempfe moeglich, Lueftung sinnvoll",
        "hint": "3D-Drucker druckt → Lueftung wegen Daempfe",
        "severity": "info",
    },

    # =====================================================================
    # 30. RECEIVER / HIFI → LAUTSTAERKE / ENERGIE
    # =====================================================================
    {
        "role": "receiver", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "AV-Receiver an → Stromverbrauch",
        "hint": "Receiver laeuft → Stromverbrauch beachten",
        "severity": "info",
    },
    {
        "role": "receiver", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "AV-Receiver an → Heimkino-Beleuchtung anpassen",
        "hint": "Receiver an → Heimkino-Modus, Licht dimmen",
        "severity": "info",
    },

    # =====================================================================
    # 31. TELEFON → BENACHRICHTIGUNG / LAUTSTAERKE
    # =====================================================================
    {
        "role": "phone", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Telefonat → Medien leiser/stumm",
        "hint": "Telefonat → Medien stumm schalten",
        "severity": "info",
    },
    {
        "role": "phone", "state": "on",
        "affects": "vacuum", "same_room": False,
        "effect": "Telefonat → Staubsauger stoeren",
        "hint": "Telefonat → Saugroboter pausieren",
        "severity": "info",
    },

    # =====================================================================
    # 32. SIRENE → WARNUNG
    # =====================================================================
    {
        "role": "siren", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Sirene aktiv → Alarm wurde ausgeloest",
        "hint": "Sirene heult → ALARM aktiv, sofort reagieren",
        "severity": "info",
    },
    {
        "role": "siren", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Sirene → Lichter an zur Orientierung/Abschreckung",
        "hint": "Sirene → alle Lichter an",
        "severity": "info",
    },

    # =====================================================================
    # 33. MOTOR / RELAY / AKTOR → ENERGIE / WARTUNG
    # =====================================================================
    {
        "role": "motor", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Motor/Antrieb aktiv → Stromverbrauch",
        "hint": "Motor laeuft → Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "relay", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Relais geschaltet → angeschlossenes Geraet aktiv",
        "hint": "Relais an → was haengt dran?",
        "severity": "info",
    },

    # =====================================================================
    # 34. SIGNAL / GESCHWINDIGKEIT / NETZWERK-QUALITAET
    # =====================================================================
    {
        "role": "signal_strength", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Signalstaerke schwach → Verbindungsprobleme moeglich",
        "hint": "Schwaches Signal → Geraet koennte ausfallen",
        "severity": "info",
    },
    {
        "role": "speedtest", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Internet-Geschwindigkeit → Streaming/Cloud betroffen",
        "hint": "Internet langsam → Streaming/Downloads beeintraechtigt",
        "severity": "info",
    },

    # =====================================================================
    # 35. WIND-RICHTUNG → BESCHATTUNG / KOMFORT
    # =====================================================================
    {
        "role": "wind_direction", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Windrichtung → Markisen-Position anpassen",
        "hint": "Windrichtung → Markise auf Windseite einfahren",
        "severity": "info",
    },
    {
        "role": "wind_direction", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Windrichtung → Fenster auf Windseite schliessen bei Sturm",
        "hint": "Wind von dieser Seite → Fenster pruefen",
        "severity": "info",
    },

    # =====================================================================
    # 36. RUNNING / STATUS → BENACHRICHTIGUNG
    # =====================================================================
    {
        "role": "running", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Geraet laeuft → Stromverbrauch aktiv",
        "hint": "Geraet in Betrieb → Energieverbrauch",
        "severity": "info",
    },
    {
        "role": "running", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Geraet gestoppt → Aufgabe fertig?",
        "hint": "Geraet fertig → Ergebnis pruefen",
        "severity": "info",
    },

    # =====================================================================
    # 37. DIMMER / FARBLICHT → STIMMUNG / ENERGIE
    # =====================================================================
    {
        "role": "dimmer", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gedimmtes Licht → reduzierter Stromverbrauch",
        "hint": "Licht gedimmt → weniger Verbrauch als volle Helligkeit",
        "severity": "info",
    },
    {
        "role": "color_light", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Farblicht an → Stromverbrauch",
        "hint": "RGB-Licht an → Stromverbrauch beachten",
        "severity": "info",
    },

    # =====================================================================
    # 38. GESCHWINDIGKEIT / ENTFERNUNG / GEWICHT → KONTEXT
    # =====================================================================
    {
        "role": "speed", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Geschwindigkeit → Bewegung erkannt",
        "hint": "Geschwindigkeit gemessen → etwas bewegt sich",
        "severity": "info",
    },
    {
        "role": "distance", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Entfernung → Annaeherung oder Entfernung",
        "hint": "Entfernung aendert sich → jemand naehert sich oder geht weg",
        "severity": "info",
    },
    {
        "role": "weight", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Gewicht gemessen → Fuellstand oder Koerpergewicht",
        "hint": "Gewicht → Fuellstand pruefen oder Gesundheitsdaten",
        "severity": "info",
    },

    # =====================================================================
    # 39. AUTO-STANDORT → SICHERHEIT / KOMFORT
    # =====================================================================
    {
        "role": "car_location", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Auto-Standort → Person unterwegs oder zuhause",
        "hint": "Auto-Position → Ankunftszeit schaetzen",
        "severity": "info",
    },
    {
        "role": "car_location", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Auto naehert sich → Haus vorheizen/kuehlen",
        "hint": "Auto auf dem Heimweg → Haus vorbereiten",
        "severity": "info",
    },

    # =====================================================================
    # 40. TIMER / ZAEHLER → BENACHRICHTIGUNG
    # =====================================================================
    {
        "role": "timer", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Timer laeuft → Erinnerung wenn abgelaufen",
        "hint": "Timer aktiv → nicht vergessen",
        "severity": "info",
    },
    {
        "role": "counter", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Zaehler → Grenzwert beobachten",
        "hint": "Zaehlerstand → Limit erreicht?",
        "severity": "info",
    },

    # =====================================================================
    # 41. SZENE / AUTOMATION → KONTEXT
    # =====================================================================
    {
        "role": "scene", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Szene aktiviert → mehrere Geraete aendern sich",
        "hint": "Szene aktiv → Geraete wurden automatisch gesetzt",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Automation aktiv → laeuft im Hintergrund",
        "hint": "Automation laeuft → Geraete werden automatisch gesteuert",
        "severity": "info",
    },

    # =====================================================================
    # 42. ADBLOCKER → NETZWERK
    # =====================================================================
    {
        "role": "adblocker", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Adblocker/DNS-Filter aus → Werbung und Tracker aktiv",
        "hint": "Adblocker deaktiviert → Netzwerk ungeschuetzt",
        "severity": "info",
    },

    # =====================================================================
    # ERGAENZUNG: Fehlende Rollen und Kreuz-Beziehungen
    # =====================================================================

    # --- Kuehlung + Fenster = Energieverschwendung (wie Heizung) ---
    {
        "role": "cooling", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Kuehlung aktiv + Fenster offen → Energieverschwendung",
        "hint": "Klimaanlage an + Fenster offen → Energie wird verschwendet",
        "severity": "high",
    },
    {
        "role": "cooling", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Kuehlung aktiv → hoher Stromverbrauch",
        "hint": "Klimaanlage laeuft → hoher Stromverbrauch",
        "severity": "info",
    },

    # --- Heizung (nicht Thermostat) + Fenster ---
    {
        "role": "heating", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Heizung aktiv + Fenster offen → Energieverschwendung",
        "hint": "Heizung an + Fenster offen → Energie wird verschwendet",
        "severity": "high",
    },
    {
        "role": "heating", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Heizung aktiv → Energieverbrauch",
        "hint": "Heizung laeuft → Energieverbrauch",
        "severity": "info",
    },

    # --- Luftreiniger + Fenster = ineffizient ---
    {
        "role": "air_purifier", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Luftreiniger aktiv + Fenster offen → Reinigung sinnlos",
        "hint": "Luftreiniger an + Fenster offen → ineffizient, Fenster zu",
        "severity": "high",
    },
    {
        "role": "air_purifier", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Luftreiniger aktiv → Stromverbrauch",
        "hint": "Luftreiniger laeuft → Stromverbrauch",
        "severity": "info",
    },

    # --- Entfeuchter + Fenster = ineffizient ---
    {
        "role": "dehumidifier", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Entfeuchter aktiv + Fenster offen → Luftfeuchtigkeit stroemt nach",
        "hint": "Entfeuchter an + Fenster offen → ineffizient, Fenster zu",
        "severity": "high",
    },
    {
        "role": "dehumidifier", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Entfeuchter an → Stromverbrauch",
        "hint": "Entfeuchter laeuft → Stromverbrauch",
        "severity": "info",
    },

    # --- Befeuchter + Fenster = ineffizient ---
    {
        "role": "humidifier", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Befeuchter aktiv + Fenster offen → Feuchtigkeit entweicht",
        "hint": "Befeuchter an + Fenster offen → ineffizient, Fenster zu",
        "severity": "high",
    },
    {
        "role": "humidifier", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Befeuchter an → Stromverbrauch",
        "hint": "Befeuchter laeuft → Stromverbrauch",
        "severity": "info",
    },

    # --- Boiler ---
    {
        "role": "boiler", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Warmwasser-Boiler heizt → hoher Energieverbrauch",
        "hint": "Boiler heizt → Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "on",
        "affects": "solar", "same_room": False,
        "effect": "Boiler heizt → bei PV-Ueberschuss ideal",
        "hint": "Boiler → bei Solarueberschuss heizen spart Geld",
        "severity": "info",
    },

    # --- Kaffeemaschine ---
    {
        "role": "coffee_machine", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Kaffeemaschine an → Kaffee wird zubereitet",
        "hint": "Kaffeemaschine laeuft → Kaffee bald fertig",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Kaffeemaschine heizt → hoher Kurzzeit-Verbrauch",
        "hint": "Kaffeemaschine → hoher Momentanverbrauch beim Aufheizen",
        "severity": "info",
    },

    # --- Frost-Schutz: Bewaesserung + Pool ---
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Frost → Bewaesserung kann Rohre beschaedigen",
        "hint": "Frost + Bewaesserung → Rohrbruchgefahr, Bewaesserung stoppen",
        "severity": "high",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "pool", "same_room": False,
        "effect": "Frost → Pool-Pumpe muss laufen gegen Frostschaden",
        "hint": "Frost + Pool → Pumpe muss laufen, Frostschaden vermeiden",
        "severity": "high",
    },

    # --- Solar → Eigenverbrauch optimieren ---
    {
        "role": "solar", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "PV produziert → E-Auto laden sinnvoll",
        "hint": "Solarueberschuss → E-Auto laden optimiert Eigenverbrauch",
        "severity": "info",
    },
    {
        "role": "solar", "state": "on",
        "affects": "washing_machine", "same_room": False,
        "effect": "PV produziert → energieintensive Geraete starten",
        "hint": "Solarueberschuss → Waschmaschine/Trockner starten",
        "severity": "info",
    },

    # --- Waermepumpe + Fenster offen ---
    {
        "role": "heat_pump", "state": "heat",
        "affects": "window_contact", "same_room": False,
        "effect": "Waermepumpe heizt + Fenster offen → teure Energieverschwendung",
        "hint": "Waermepumpe an + Fenster offen → hohe Energieverschwendung",
        "severity": "high",
    },
    {
        "role": "heat_pump", "state": "heat",
        "affects": "energy", "same_room": False,
        "effect": "Waermepumpe heizt → Stromverbrauch je nach COP",
        "hint": "Waermepumpe aktiv → Stromverbrauch",
        "severity": "info",
    },

    # --- Kamera + Alarm ---
    {
        "role": "alarm", "state": "armed_away",
        "affects": "camera", "same_room": False,
        "effect": "Alarm scharf → Kameras sollten aufzeichnen",
        "hint": "Alarm scharf (abwesend) → Kamera-Aufzeichnung pruefen",
        "severity": "info",
    },

    # --- Presence + Alarm (vergessen scharf zu stellen) ---
    {
        "role": "presence", "state": "off",
        "affects": "alarm", "same_room": False,
        "requires_state": {"disarmed"},
        "effect": "Niemand zuhause + Alarm nicht scharf → Sicherheitsluecke",
        "hint": "Alle abwesend → Alarm sollte scharf gestellt werden",
        "severity": "high",
    },

    # --- Waschmaschine/Trockner + Abwesenheit ---
    {
        "role": "washing_machine", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Waschmaschine laeuft + niemand zuhause → Wasserschaden-Risiko",
        "hint": "Waschmaschine laeuft unbeaufsichtigt → Wasserschaden moeglich",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Trockner laeuft + niemand zuhause → Brandrisiko",
        "hint": "Trockner laeuft unbeaufsichtigt → Brandgefahr moeglich",
        "severity": "info",
    },

    # --- Licht + Tageslicht-Sensor ---
    {
        "role": "light_level", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Hohe Helligkeit → Beschattung sinnvoll",
        "hint": "Starkes Tageslicht → Rollladen/Jalousie gegen Blendung",
        "severity": "info",
    },

    # =================================================================
    # SICHERHEIT / BRANDSCHUTZ — fehlende Szenarien
    # =================================================================

    # Herd/Ofen an + niemand zuhause = Brandgefahr
    {
        "role": "oven", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Herd/Ofen an + niemand zuhause → Brandgefahr",
        "hint": "Herd laeuft unbeaufsichtigt → BRANDGEFAHR",
        "severity": "critical",
    },

    # Wasserleck → Hauptventil schliessen
    {
        "role": "water_leak", "state": "on",
        "affects": "valve", "same_room": False,
        "effect": "Wasserleck → Hauptventil sofort schliessen",
        "hint": "Wasserleck erkannt → Wasserventil schliessen",
        "severity": "critical",
    },
    # Wasserleck → Waschmaschine/Spueler koennten Quelle sein
    {
        "role": "water_leak", "state": "on",
        "affects": "washing_machine", "same_room": True,
        "effect": "Wasserleck in Naehe Waschmaschine → moeglicherweise Quelle",
        "hint": "Wasserleck → Waschmaschine als Quelle pruefen",
        "severity": "high",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "dishwasher", "same_room": True,
        "effect": "Wasserleck in Naehe Spuelmaschine → moeglicherweise Quelle",
        "hint": "Wasserleck → Spuelmaschine als Quelle pruefen",
        "severity": "high",
    },

    # Rauch → Lueftung/Ventilation AUS (Feuer nicht anfachen!)
    {
        "role": "smoke", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Rauch → Lueftungsanlage aus, Feuer nicht anfachen",
        "hint": "Rauch erkannt → Lueftung sofort AUS, Feuer nicht verbreiten",
        "severity": "critical",
    },

    # Gas-Leck → KEINE Schaltaktionen (Funke!)
    {
        "role": "gas", "state": "on",
        "affects": "relay", "same_room": False,
        "effect": "Gas erkannt → keine Schaltaktionen, Funkengefahr",
        "hint": "Gas erkannt → NICHT schalten, Funkengefahr → Explosionsrisiko",
        "severity": "critical",
    },
    {
        "role": "gas", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Gas erkannt → Lueftung aus (elektrische Motoren = Funke)",
        "hint": "Gas → Lueftung AUS, elektrischer Funke = Explosionsgefahr",
        "severity": "critical",
    },

    # =================================================================
    # SICHERHEIT — Abwesenheit / Vergessen
    # =================================================================

    # Niemand zuhause + Tueren nicht abgeschlossen
    {
        "role": "presence", "state": "off",
        "affects": "lock", "same_room": False,
        "effect": "Niemand zuhause + Tueren nicht abgeschlossen → unsicher",
        "hint": "Alle weg → Tueren sollten abgeschlossen sein",
        "severity": "high",
    },
    # Niemand zuhause + Garagentor offen
    {
        "role": "presence", "state": "off",
        "affects": "garage_door", "same_room": False,
        "effect": "Niemand zuhause + Garagentor offen → vergessen zu schliessen",
        "hint": "Alle weg → Garagentor sollte geschlossen sein",
        "severity": "high",
    },
    # Niemand zuhause + Fenster offen
    {
        "role": "presence", "state": "off",
        "affects": "window_contact", "same_room": False,
        "effect": "Niemand zuhause + Fenster offen → Einbruch/Wetter-Risiko",
        "hint": "Alle weg → offene Fenster schliessen",
        "severity": "high",
    },
    # Niemand zuhause + Herd an (nochmal explizit anders herum)
    {
        "role": "presence", "state": "off",
        "affects": "oven", "same_room": False,
        "effect": "Niemand zuhause + Herd an → Brandgefahr",
        "hint": "Alle weg + Herd an → BRANDGEFAHR, sofort ausschalten",
        "severity": "critical",
    },

    # Kamera offline + Alarm scharf = blinder Fleck
    {
        "role": "camera", "state": "off",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Kamera offline bei scharfem Alarm → Sicherheitsluecke",
        "hint": "Kamera offline + Alarm scharf → blinder Fleck in Ueberwachung",
        "severity": "high",
    },

    # =================================================================
    # NETZWERK — Auswirkungen auf Smart-Home
    # =================================================================

    # Router offline → Alarm/Kameras/Automationen betroffen
    {
        "role": "router", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Router offline → Alarm-System moeglicherweise nicht erreichbar",
        "hint": "Router down → Alarmsystem pruefen, kein Remote-Zugriff",
        "severity": "high",
    },
    {
        "role": "router", "state": "off",
        "affects": "camera", "same_room": False,
        "effect": "Router offline → Kameras nicht erreichbar, keine Aufzeichnung",
        "hint": "Router down → Kameras offline, Ueberwachung unterbrochen",
        "severity": "high",
    },
    # Server/NAS offline → Kamera-Aufzeichnung / Medien
    {
        "role": "server", "state": "off",
        "affects": "camera", "same_room": False,
        "effect": "Server offline → Kamera-Aufzeichnung (NVR) gestoppt",
        "hint": "Server down → keine Kamera-Aufzeichnung moeglich",
        "severity": "high",
    },
    {
        "role": "nas", "state": "off",
        "affects": "media_player", "same_room": False,
        "effect": "NAS offline → Medienbibliothek nicht verfuegbar",
        "hint": "NAS down → Filme/Musik/Fotos nicht abrufbar",
        "severity": "info",
    },

    # =================================================================
    # KLIMA — widersprüchliche / fehlende Szenarien
    # =================================================================

    # Thermostat kuehlt + Fenster offen (nicht nur heat!)
    {
        "role": "thermostat", "state": "cool",
        "affects": "window_contact", "same_room": True,
        "effect": "Klimaanlage kuehlt + Fenster offen → Energieverschwendung",
        "hint": "Kuehlung an + Fenster offen → Energie wird verschwendet",
        "severity": "high",
    },
    # Heizung + Kuehlung gleichzeitig = gegeneinander arbeiten
    {
        "role": "heating", "state": "on",
        "affects": "cooling", "same_room": True,
        "effect": "Heizung + Kuehlung gleichzeitig → arbeiten gegeneinander",
        "hint": "Heizung UND Kuehlung laufen → Energieverschwendung, gegeneinander",
        "severity": "high",
    },
    # Waermepumpe kuehlt + Fenster offen
    {
        "role": "heat_pump", "state": "cool",
        "affects": "window_contact", "same_room": False,
        "effect": "Waermepumpe kuehlt + Fenster offen → Energieverschwendung",
        "hint": "Waermepumpe kuehlt + Fenster offen → Energie wird verschwendet",
        "severity": "high",
    },

    # Humidity niedrig + Heizung = trockene Luft
    {
        "role": "heating", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Heizung trocknet Luft aus → Luftfeuchtigkeit sinkt",
        "hint": "Heizung an → Luft wird trocken, Befeuchter oder Lueften sinnvoll",
        "severity": "info",
    },

    # =================================================================
    # WETTER — fehlende Szenarien
    # =================================================================

    # Wind → Fenster schliessen (Sturm)
    {
        "role": "wind_speed", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Starker Wind → offene Fenster koennen zuschlagen/beschaedigen",
        "hint": "Sturm → Fenster schliessen, Beschaedigungsgefahr",
        "severity": "high",
    },
    # Wind → Bewaesserung ineffizient (Sprinkler verweht)
    {
        "role": "wind_speed", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Wind → Sprinkler-Wasser verweht, Bewaesserung ineffizient",
        "hint": "Wind + Bewaesserung → Wasser verweht, spaeter bewaessern",
        "severity": "info",
    },

    # =================================================================
    # KOMFORT — fehlende Szenarien
    # =================================================================

    # Tuerklingel → Medien leiser/pausieren
    {
        "role": "doorbell", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Tuerklingel → Medien leiser damit man hoert",
        "hint": "Klingel → Medien pausieren/leiser, damit man die Tuer hoert",
        "severity": "info",
    },
    # Im Bett → Alarm scharf (Nachtmodus)
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Im Bett → Nacht-Alarm sinnvoll",
        "hint": "Schlafenszeit → Alarm auf Nachtmodus stellen",
        "severity": "info",
    },
    # Im Bett → Klingel leiser/stumm
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "doorbell", "same_room": False,
        "effect": "Im Bett → Tuerklingel sollte stumm/leiser sein",
        "hint": "Schlafenszeit → Klingel stumm schalten",
        "severity": "info",
    },
    # Projector → braucht Lueftung (wird heiss)
    {
        "role": "projector", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Beamer erzeugt Waerme → Raumtemperatur steigt",
        "hint": "Beamer an → erzeugt Abwaerme, Raum wird waermer",
        "severity": "info",
    },
    # TV an + Anwesenheit aus → vergessen auszuschalten
    {
        "role": "tv", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "TV laeuft + niemand zuhause → vergessen auszuschalten",
        "hint": "TV an + niemand zuhause → TV vergessen, ausschalten",
        "severity": "info",
    },

    # =================================================================
    # ENERGIE — fehlende Szenarien
    # =================================================================

    # EV-Charger + hoher Netzbezug → teurer Strom
    {
        "role": "ev_charger", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "E-Auto laedt vom Netz → teurer Strom statt Solar",
        "hint": "Wallbox laedt ohne Solar → teurer Netzbezug, besser bei Sonne laden",
        "severity": "info",
    },
    # Solar → Boiler aufheizen (Ueberschuss nutzen)
    {
        "role": "solar", "state": "on",
        "affects": "boiler", "same_room": False,
        "effect": "PV-Ueberschuss → Boiler aufheizen statt einspeisen",
        "hint": "Solarueberschuss → Warmwasser heizen lohnt sich",
        "severity": "info",
    },
    # Solar → Pool-Heizung
    {
        "role": "solar", "state": "on",
        "affects": "pool", "same_room": False,
        "effect": "PV-Ueberschuss → Pool heizen sinnvoll",
        "hint": "Solarueberschuss → Pool heizen statt einspeisen",
        "severity": "info",
    },
    # Batterie-Speicher niedrig + hoher Verbrauch
    {
        "role": "battery", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Hausspeicher-Batterie niedrig → bald Netzbezug noetig",
        "hint": "Batterie fast leer → energieintensive Geraete verschieben",
        "severity": "info",
    },

    # =================================================================
    # GERAETE-KETTEN / APPLIANCE-WORKFLOWS
    # =================================================================

    # Waschmaschine fertig → Trockner bereit
    {
        "role": "washing_machine", "state": "idle",
        "affects": "dryer", "same_room": False,
        "effect": "Waschmaschine fertig → Waesche in Trockner umraeumen",
        "hint": "Waschmaschine fertig → Waesche in den Trockner",
        "severity": "info",
    },

    # =================================================================
    # GARTEN — fehlende Szenarien
    # =================================================================

    # Bewaesserung + Bodenfeuchtigkeit hoch → Ueberbewässerung
    {
        "role": "irrigation", "state": "on",
        "affects": "soil_moisture", "same_room": True,
        "effect": "Bewaesserung laeuft + Boden bereits feucht → Ueberwaesserung",
        "hint": "Boden schon feucht → Bewaesserung stoppen, Pflanzenschaden",
        "severity": "high",
    },

    # =================================================================
    # FAHRZEUGE — fehlende Szenarien
    # =================================================================

    # Auto naehert sich → Garagentor, Heizung/Kuehlung vorbereiten
    {
        "role": "car_location", "state": "on",
        "affects": "garage_door", "same_room": False,
        "effect": "Auto naehert sich → Garagentor oeffnen vorbereiten",
        "hint": "Auto kommt → Garage oeffnen, Haus vorbereiten",
        "severity": "info",
    },
    # Auto zuhause + Garage offen seit langem
    {
        "role": "car", "state": "home",
        "affects": "garage_door", "same_room": False,
        "effect": "Auto zuhause + Garagentor offen → vergessen zu schliessen",
        "hint": "Auto geparkt + Garage offen → Tor schliessen",
        "severity": "info",
    },

    # =================================================================
    # SICHERHEIT — Alarm-System Interaktionen
    # =================================================================

    # Alarm scharf → Garagentor/Tor sollte zu sein
    {
        "role": "alarm", "state": "armed_away",
        "affects": "garage_door", "same_room": False,
        "effect": "Alarm scharf → Garagentor sollte geschlossen sein",
        "hint": "Alarm aktiviert + Garagentor offen → Sicherheitsluecke",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "armed_away",
        "affects": "gate", "same_room": False,
        "effect": "Alarm scharf → Tor/Einfahrt sollte geschlossen sein",
        "hint": "Alarm aktiviert + Tor offen → Einfahrt sichern",
        "severity": "high",
    },
    # Alarm scharf → Fenster zu
    {
        "role": "alarm", "state": "armed_away",
        "affects": "window_contact", "same_room": False,
        "effect": "Alarm scharf → offene Fenster sind Sicherheitsluecke",
        "hint": "Alarm aktiviert + Fenster offen → Einbruchgefahr",
        "severity": "high",
    },
    # Alarm scharf → Herd sollte aus sein
    {
        "role": "alarm", "state": "armed_away",
        "affects": "oven", "same_room": False,
        "effect": "Alarm scharf (niemand da) + Herd an → Brandgefahr",
        "hint": "Haus verlassen + Herd an → BRANDGEFAHR, Herd ausschalten",
        "severity": "critical",
    },
    # Alarm scharf → Steckdosen mit Verbrauchern pruefen
    {
        "role": "alarm", "state": "armed_away",
        "affects": "outlet", "same_room": False,
        "effect": "Alarm scharf → unbeaufsichtigte Steckdosen-Verbraucher pruefen",
        "hint": "Haus verlassen → Buegeleisen, Heizluefter etc. an Steckdosen pruefen",
        "severity": "info",
    },
    # Alarm Nachtmodus → Garagentor sollte zu sein
    {
        "role": "alarm", "state": "armed_night",
        "affects": "garage_door", "same_room": False,
        "effect": "Nacht-Alarm → Garagentor sollte geschlossen sein",
        "hint": "Nachtmodus + Garagentor offen → Garage schliessen",
        "severity": "high",
    },
    # Alarm Nachtmodus → Tor/Einfahrt zu
    {
        "role": "alarm", "state": "armed_night",
        "affects": "gate", "same_room": False,
        "effect": "Nacht-Alarm → Tor sollte geschlossen sein",
        "hint": "Nachtmodus + Tor offen → Tor schliessen",
        "severity": "high",
    },
    # Alarm Nachtmodus → Fenster Erdgeschoss (same_room=False weil global)
    {
        "role": "alarm", "state": "armed_night",
        "affects": "window_contact", "same_room": False,
        "effect": "Nacht-Alarm → Erdgeschoss-Fenster sollten zu sein",
        "hint": "Nachtmodus + Fenster offen → Erdgeschoss-Fenster schliessen",
        "severity": "info",
    },

    # =================================================================
    # LICHT — Auswirkungen auf andere Geraete
    # =================================================================

    # Licht an im Raum → Kamera-Nachtsicht deaktivieren
    {
        "role": "light", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Licht an → Kamera wechselt von Nachtsicht zu normal",
        "hint": "Licht + Kamera im Raum → Nachtsicht nicht noetig",
        "severity": "info",
    },
    # Licht an nachts draussen → Kamera-Qualitaet besser
    {
        "role": "garden_light", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Gartenbeleuchtung an → Aussen-Kameras sehen besser",
        "hint": "Gartenbeleuchtung → Kamera-Sicht verbessert",
        "severity": "info",
    },

    # =================================================================
    # KLIMA — erweiterte Szenarien
    # =================================================================

    # Kamin/Ofen an → Rauchmelder kann ansprechen (kein Fehlalarm)
    {
        "role": "oven", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "Herd/Ofen an + Rauchmelder → koennte Kochen sein, kein Brand",
        "hint": "Herd an + Rauchmelder → wahrscheinlich Kochen, kein Fehlalarm",
        "severity": "info",
    },
    # Heizung an + Fenster offen + Luftqualitaet schlecht → Lueften noetig trotz Heizung
    {
        "role": "co2", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "CO2 hoch → Lueften noetig, auch wenn Heizung laeuft",
        "hint": "CO2 hoch → kurz Stosslueften, auch bei Heizung",
        "severity": "high",
    },
    # Luftfeuchtigkeit hoch + Fenster auf → Lueften hilft (oder schadet bei Regen)
    {
        "role": "humidity", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Hohe Luftfeuchtigkeit → Fenster auf oder Entfeuchter an",
        "hint": "Luftfeuchtigkeit hoch → Lueften oder Entfeuchter nutzen",
        "severity": "info",
    },
    {
        "role": "humidity", "state": "on",
        "affects": "dehumidifier", "same_room": True,
        "effect": "Hohe Luftfeuchtigkeit → Entfeuchter sollte laufen",
        "hint": "Luftfeuchtigkeit hoch → Entfeuchter einschalten",
        "severity": "info",
    },
    # Taupunkt erreicht → Schimmelgefahr
    {
        "role": "dew_point", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Taupunkt nahe Wandtemperatur → Schimmelgefahr, belueften",
        "hint": "Taupunkt kritisch → Schimmelgefahr, Lueftung an oder Fenster auf",
        "severity": "high",
    },
    # Aussentemperatur heiss → Rollladen/Jalousie runter
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Aussentemperatur hoch → Beschattung sinnvoll",
        "hint": "Hitze draussen → Rollladen schliessen gegen Aufheizung",
        "severity": "info",
    },
    # Aussentemperatur heiss → Markise raus
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Aussentemperatur hoch → Markise ausfahren",
        "hint": "Hitze draussen → Markise ausfahren fuer Beschattung",
        "severity": "info",
    },
    # Frost → Bewaesserung AUS (Frostschaeden an Leitungen)
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "valve", "same_room": False,
        "effect": "Frost → Wasserventile/Aussenleitungen schuetzen",
        "hint": "Frost → Aussenwasser-Ventile schliessen, Leitungsschaeden verhindern",
        "severity": "high",
    },
    # Frost → Pool-Pumpe muss laufen (Frostschutz)
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "pump", "same_room": False,
        "effect": "Frost → Pool-Pumpe muss laufen, sonst Frostschaden",
        "hint": "Frost → Pool-Pumpe laufen lassen, Frostschutz",
        "severity": "high",
    },

    # =================================================================
    # ENERGIE-OPTIMIERUNG — erweitert
    # =================================================================

    # Solar-Ueberschuss → Klimaanlage/Waermepumpe vorheizen/vorkuehlen
    {
        "role": "solar", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "PV-Ueberschuss → Waermepumpe mit Solarstrom betreiben",
        "hint": "Solarueberschuss → Waermepumpe jetzt laufen lassen (thermischer Speicher)",
        "severity": "info",
    },
    {
        "role": "solar", "state": "on",
        "affects": "cooling", "same_room": False,
        "effect": "PV-Ueberschuss → Klimaanlage mit Solarstrom vorkuehlen",
        "hint": "Solarueberschuss → jetzt vorkuehlen, spart abends Netzstrom",
        "severity": "info",
    },
    {
        "role": "solar", "state": "on",
        "affects": "dishwasher", "same_room": False,
        "effect": "PV-Ueberschuss → Spuelmaschine mit Solarstrom starten",
        "hint": "Solarueberschuss → Spuelmaschine jetzt starten",
        "severity": "info",
    },
    {
        "role": "solar", "state": "on",
        "affects": "dryer", "same_room": False,
        "effect": "PV-Ueberschuss → Trockner mit Solarstrom starten",
        "hint": "Solarueberschuss → Trockner jetzt starten",
        "severity": "info",
    },

    # Netzeinspeisung hoch → Eigenverbrauch steigern
    {
        "role": "grid_feed", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Hohe Einspeisung → E-Auto laden statt einspeisen",
        "hint": "Hohe Einspeisung → Wallbox starten, Eigenverbrauch steigern",
        "severity": "info",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "washing_machine", "same_room": False,
        "effect": "Hohe Einspeisung → Waschmaschine starten statt einspeisen",
        "hint": "Hohe Einspeisung → Waschmaschine jetzt starten",
        "severity": "info",
    },

    # =================================================================
    # KOMFORT — erweitert
    # =================================================================

    # Vacuum → Presence (nicht saugen wenn Meeting/Arbeit)
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "presence", "same_room": False,
        "effect": "Staubsauger laeuft + jemand zuhause → koennte stoeren",
        "hint": "Staubsauger laeuft + jemand zuhause → stoert evtl. bei Arbeit/Meeting",
        "severity": "info",
    },
    # Vacuum → Tueren auf (damit Sauger durchkommt)
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "door_contact", "same_room": False,
        "effect": "Staubsauger saugt → Zimmertueren sollten offen sein",
        "hint": "Saugroboter saugt → Tueren offen lassen damit er durchkommt",
        "severity": "info",
    },

    # Waschmaschine/Trockner laufen + Abwesenheit → kein Problem wenn kurz
    {
        "role": "washing_machine", "state": "on",
        "affects": "water_leak", "same_room": True,
        "effect": "Waschmaschine laeuft → Wasserleck moeglich",
        "hint": "Waschmaschine laeuft → Wasserleck-Sensoren beobachten",
        "severity": "info",
    },
    {
        "role": "dishwasher", "state": "on",
        "affects": "water_leak", "same_room": True,
        "effect": "Spuelmaschine laeuft → Wasserleck moeglich",
        "hint": "Spuelmaschine laeuft → Wasserleck-Sensoren beobachten",
        "severity": "info",
    },

    # Kaffeemaschine fertig → Morgenroutine
    {
        "role": "coffee_machine", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Kaffeemaschine fertig → Kaffee ist bereit",
        "hint": "Kaffee ist fertig",
        "severity": "info",
    },

    # =================================================================
    # MULTIMEDIA — Raum-Interaktionen
    # =================================================================

    # Media Player / TV laut + Fenster offen → Nachbarn stoeren
    {
        "role": "media_player", "state": "playing",
        "affects": "window_contact", "same_room": True,
        "effect": "Medien laut + Fenster offen → Nachbarn koennten sich stoeren",
        "hint": "Medien laut + Fenster offen → Laermbelaestigung moeglich",
        "severity": "info",
    },
    # TV an → Receiver sollte auch an sein
    {
        "role": "tv", "state": "on",
        "affects": "receiver", "same_room": True,
        "effect": "TV an → AV-Receiver sollte auch an sein fuer Sound",
        "hint": "TV an → Receiver auch einschalten fuer Sound",
        "severity": "info",
    },

    # =================================================================
    # NETZWERK — erweiterte Auswirkungen
    # =================================================================

    # Router offline → Automatisierungen betroffen
    {
        "role": "router", "state": "off",
        "affects": "automation", "same_room": False,
        "effect": "Router offline → Cloud-Automatisierungen funktionieren nicht",
        "hint": "Router down → Cloud-Automatisierungen offline",
        "severity": "high",
    },
    # Router offline → Sprachassistent offline
    {
        "role": "router", "state": "off",
        "affects": "media_player", "same_room": False,
        "effect": "Router offline → Streaming/Sprachassistent nicht verfuegbar",
        "hint": "Router down → Streaming/Alexa/Google nicht erreichbar",
        "severity": "info",
    },
    # Server offline → Automatisierungen betroffen
    {
        "role": "server", "state": "off",
        "affects": "automation", "same_room": False,
        "effect": "Server offline → lokale Automatisierungen gestoppt",
        "hint": "Server down → Automatisierungen laufen nicht mehr",
        "severity": "high",
    },

    # =================================================================
    # SICHERHEIT — Nacht-Szenarien
    # =================================================================

    # Nachts Bewegung + alle im Bett → verdaechtig (bed_occupancy → motion)
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "motion", "same_room": False,
        "effect": "Alle im Bett + Bewegung erkannt → verdaechtig",
        "hint": "Alle schlafen + Bewegung → verdaechtig, Alarm pruefen",
        "severity": "high",
    },

    # =================================================================
    # ABWESENHEIT — erweiterte Prüfungen
    # =================================================================

    # Niemand zuhause + Kaffee/Buegeleisen an
    {
        "role": "presence", "state": "off",
        "affects": "coffee_machine", "same_room": False,
        "effect": "Niemand zuhause + Kaffeemaschine an → vergessen auszuschalten",
        "hint": "Alle weg + Kaffeemaschine noch an → ausschalten",
        "severity": "info",
    },
    # Niemand zuhause + TV an (von oben: tv → presence existiert, aber auch Richtung presence → tv)
    {
        "role": "presence", "state": "off",
        "affects": "tv", "same_room": False,
        "effect": "Niemand zuhause + TV laeuft → vergessen auszuschalten",
        "hint": "Alle weg + TV laeuft → TV vergessen, ausschalten",
        "severity": "info",
    },
    # Niemand zuhause + PC an
    {
        "role": "presence", "state": "off",
        "affects": "pc", "same_room": False,
        "effect": "Niemand zuhause + PC laeuft → vergessen oder gewollt",
        "hint": "Alle weg + PC laeuft → PC herunterfahren oder Standby",
        "severity": "info",
    },
    # Niemand zuhause + Ventilator/Lueftung laeuft
    {
        "role": "presence", "state": "off",
        "affects": "fan", "same_room": False,
        "effect": "Niemand zuhause + Ventilator laeuft → Energieverschwendung",
        "hint": "Alle weg + Ventilator noch an → ausschalten",
        "severity": "info",
    },
    # Niemand zuhause + Vacuum → OK, erwuenscht
    {
        "role": "presence", "state": "off",
        "affects": "vacuum", "same_room": False,
        "effect": "Niemand zuhause → perfekte Zeit fuer Staubsauger",
        "hint": "Alle weg → idealer Zeitpunkt zum Saugen",
        "severity": "info",
    },
    # Niemand zuhause + Bewässerung → OK aber prüfen
    {
        "role": "presence", "state": "off",
        "affects": "irrigation", "same_room": False,
        "effect": "Niemand zuhause + Bewaesserung → laeuft automatisch",
        "hint": "Alle weg + Bewaesserung laeuft → planmaessig, Wasserleck beobachten",
        "severity": "info",
    },
    # Ankunft (presence on) → Klima/Licht vorbereiten
    {
        "role": "presence", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Jemand kommt → Klima auf Komforttemperatur",
        "hint": "Ankunft erkannt → Heizung/Kuehlung auf Komfort stellen",
        "severity": "info",
    },
    {
        "role": "presence", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Jemand kommt → Beleuchtung einschalten wenn dunkel",
        "hint": "Ankunft erkannt → Licht an wenn dunkel draussen",
        "severity": "info",
    },

    # =================================================================
    # GERAETE-GESUNDHEIT
    # =================================================================

    # Kuehlschrank/Gefrierschrank Temperatur hoch → Lebensmittel-Risiko
    {
        "role": "fridge", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Kuehlschrank → Abwaerme erhoet Raumtemperatur",
        "hint": "Kuehlschrank-Abwaerme → Raum wird etwas waermer",
        "severity": "info",
    },

    # Drucker → Luftqualitaet (Feinstaub)
    {
        "role": "printer", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Laserdrucker → Feinstaub-Emission im Raum",
        "hint": "Laserdrucker druckt → Feinstaub, Lueften empfohlen",
        "severity": "info",
    },

    # =================================================================
    # WETTER → GERAETE — erweitert
    # =================================================================

    # Regen → Gartenbeleuchtung evtl. unnoetig
    {
        "role": "rain", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Regen → Gartenbeleuchtung evtl. unnoetig (niemand draussen)",
        "hint": "Regen → Gartenbeleuchtung ausschalten, niemand draussen",
        "severity": "info",
    },
    # Regen → Dachfenster/Velux schliessen
    {
        "role": "rain", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Regen → Dachfenster/Oberlichter schliessen",
        "hint": "Regen → Dachfenster und Oberlichter schliessen",
        "severity": "high",
    },
    # UV-Index hoch → Markise ausfahren
    {
        "role": "uv_index", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Hoher UV-Index → Markise ausfahren fuer Sonnenschutz",
        "hint": "UV-Index hoch → Markise ausfahren, Sonnenschutz",
        "severity": "info",
    },
    # UV-Index hoch → Shutter/Rollladen
    {
        "role": "uv_index", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Hoher UV-Index → Beschattung fuer Moebel/Boeden",
        "hint": "UV-Index hoch → Rollladen runter, Moebel/Boeden schuetzen",
        "severity": "info",
    },
    # Sonneneinstrahlung → Markise
    {
        "role": "solar_radiation", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Markise ausfahren",
        "hint": "Starke Sonne → Markise raus fuer Beschattung",
        "severity": "info",
    },
    # Sonneneinstrahlung → Shutter/Rollladen
    {
        "role": "solar_radiation", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Beschattung",
        "hint": "Starke Sonne → Rollladen fuer Kuehlung und Blendschutz",
        "severity": "info",
    },

    # Windrichtung → welche Seite Fenster/Markisen schliessen
    {
        "role": "wind_direction", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Windrichtung → relevante Seite fuer Beschattung/Schutz",
        "hint": "Wind aus Richtung X → windexponierte Seite schuetzen",
        "severity": "info",
    },
    {
        "role": "wind_direction", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Windrichtung → Rollladen auf der Windseite schliessen",
        "hint": "Windrichtung beachten → windexponierte Rollladen runter",
        "severity": "info",
    },

    # =================================================================
    # POOL — erweiterte Szenarien
    # =================================================================

    # Pool-Pumpe + Frost (nochmal als Trigger von pool statt outdoor_temp)
    {
        "role": "pool", "state": "on",
        "affects": "outdoor_temp", "same_room": False,
        "effect": "Pool aktiv → Aussentemperatur fuer Frostschutz beobachten",
        "hint": "Pool → bei Frost muss Pumpe laufen, Leitungsschutz",
        "severity": "info",
    },

    # =================================================================
    # SPEZIELLE SZENARIEN
    # =================================================================

    # Scene aktiviert → mehrere Geraete betroffen
    {
        "role": "scene", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Szene aktiviert → Klima passt sich an",
        "hint": "Szene gestartet → Klima/Beleuchtung werden angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Szene aktiviert → Beschattung passt sich an",
        "hint": "Szene gestartet → Rollladen/Jalousien werden angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Szene aktiviert → Medien werden angepasst",
        "hint": "Szene gestartet → Musik/Medien werden gestartet/gestoppt",
        "severity": "info",
    },

    # Gegensprechanlage → Tueroeffner/Schloss
    {
        "role": "intercom", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Gegensprechanlage aktiv → Tuer oeffnen moeglich",
        "hint": "Gegensprechanlage → Person identifiziert, Tuer oeffnen?",
        "severity": "info",
    },

    # Sirene → Alarm muss aktiv sein (sonst Fehlkonfiguration)
    {
        "role": "siren", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Sirene aktiv → Alarm-System sollte ausgeloest haben",
        "hint": "Sirene heult → Alarm pruefen, ggf. Fehlalarm bestaetigen",
        "severity": "high",
    },

    # Problem-Sensor → betroffenes Geraet pruefen
    {
        "role": "problem", "state": "on",
        "affects": "automation", "same_room": False,
        "effect": "Problem erkannt → Automatisierungen koennten betroffen sein",
        "hint": "Geraete-Problem → abhaengige Automatisierungen pruefen",
        "severity": "info",
    },

    # Connectivity → Geraete offline
    {
        "role": "connectivity", "state": "off",
        "affects": "camera", "same_room": False,
        "effect": "Verbindung verloren → Geraete/Kameras moeglicherweise offline",
        "hint": "Verbindung unterbrochen → Kamera/Geraete nicht erreichbar",
        "severity": "high",
    },
    {
        "role": "connectivity", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Verbindung verloren → Alarm-System moeglicherweise offline",
        "hint": "Verbindung unterbrochen → Alarm-System pruefen",
        "severity": "high",
    },

    # =================================================================
    # ZONE — Geografische Bereiche (Zuhause, Arbeit, Schule, ...)
    # =================================================================

    # Zone-Wechsel → Anwesenheit/Presence-Kontext
    {
        "role": "zone", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Person betritt Zone → Anwesenheits-Status aendert sich",
        "hint": "Zone betreten → Anwesenheit aktualisieren (zuhause/weg/Arbeit)",
        "severity": "info",
    },
    # Zone → Klima vorbereiten (Person naehert sich Zuhause)
    {
        "role": "zone", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Person naehert sich Zuhause-Zone → Heizung/Kuehlung vorbereiten",
        "hint": "Person naehert sich → Klima auf Komforttemperatur vorheizen/vorkuehlen",
        "severity": "info",
    },
    # Zone → Licht vorbereiten
    {
        "role": "zone", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Person naehert sich Zuhause → Beleuchtung vorbereiten",
        "hint": "Person kommt → Licht einschalten wenn dunkel",
        "severity": "info",
    },
    # Zone → Garagentor
    {
        "role": "zone", "state": "on",
        "affects": "garage_door", "same_room": False,
        "effect": "Person naehert sich → Garagentor oeffnen vorbereiten",
        "hint": "Person naehert sich → Garage oeffnen wenn Auto erkannt",
        "severity": "info",
    },
    # Zone → Alarm deaktivieren
    {
        "role": "zone", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Person betritt Zuhause-Zone → Alarm deaktivieren",
        "hint": "Person kommt nach Hause → Alarm deaktivieren",
        "severity": "info",
    },
    # Zone verlassen → Alarm scharf schalten
    {
        "role": "zone", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Letzte Person verlaesst Zuhause-Zone → Alarm aktivieren",
        "hint": "Alle weg → Alarm scharf schalten",
        "severity": "info",
    },
    # Zone verlassen → Geraete ausschalten
    {
        "role": "zone", "state": "off",
        "affects": "light", "same_room": False,
        "effect": "Alle haben Zone verlassen → Licht ausschalten",
        "hint": "Alle weg → Beleuchtung ausschalten",
        "severity": "info",
    },
    {
        "role": "zone", "state": "off",
        "affects": "climate", "same_room": False,
        "effect": "Alle haben Zone verlassen → Klima auf Abwesenheit",
        "hint": "Alle weg → Heizung/Kuehlung auf Eco-Modus",
        "severity": "info",
    },
    # Zone → Benachrichtigung (Kind kommt in Schule an)
    {
        "role": "zone", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Person betritt Zone → Benachrichtigung (z.B. Kind in Schule)",
        "hint": "Zone-Eintritt erkannt → Benachrichtigung senden",
        "severity": "info",
    },

    # =================================================================
    # BEWEGUNG — DIE haeufigste Smart-Home-Automatisierung
    # =================================================================

    # Motion → Licht einschalten
    {
        "role": "motion", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Bewegung erkannt → Licht einschalten",
        "hint": "Bewegung im Raum → Licht einschalten",
        "severity": "info",
    },
    # Motion → Kamera aufzeichnen
    {
        "role": "motion", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Bewegung erkannt → Kamera startet Aufzeichnung",
        "hint": "Bewegung → Kamera-Aufzeichnung starten",
        "severity": "info",
    },
    # Motion → Benachrichtigung (bei Abwesenheit besonders relevant)
    {
        "role": "motion", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Bewegung erkannt → Benachrichtigung sinnvoll wenn niemand da",
        "hint": "Bewegung + niemand zuhause → Benachrichtigung senden",
        "severity": "info",
    },
    # Motion → Klimaanlage/Heizung (Raum wird genutzt)
    {
        "role": "motion", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Bewegung → Raum wird genutzt, Klima auf Komfort",
        "hint": "Bewegung im Raum → Klima auf Komfort-Temperatur",
        "severity": "info",
    },
    # Motion → Musik/Medien (Raum wird betreten)
    {
        "role": "motion", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Bewegung → Person betritt Raum, Medien ggf. fortsetzen",
        "hint": "Raum betreten → Musik/Medien fortsetzen wenn gewuenscht",
        "severity": "info",
    },

    # =================================================================
    # RAUMBELEGUNG ON — Raum wird betreten/belegt
    # =================================================================

    {
        "role": "occupancy", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Raum belegt → Licht einschalten wenn dunkel",
        "hint": "Raum wird genutzt → Licht an wenn noetig",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Raum belegt → Klima auf Komfort-Temperatur",
        "hint": "Raum wird genutzt → Heizung/Kuehlung auf Komfort",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Raum belegt → Ventilator bei Bedarf einschalten",
        "hint": "Raum wird genutzt → Lueftung/Ventilator anpassen",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Raum belegt → Medien ggf. fortsetzen",
        "hint": "Raum wird genutzt → Musik/Medien bei Bedarf starten",
        "severity": "info",
    },

    # =================================================================
    # TUER/TOR/GARAGE — erweiterte Trigger
    # =================================================================

    # Tuer oeffnet → Licht
    {
        "role": "door_contact", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Tuer geoeffnet → Licht im Flur/Raum einschalten",
        "hint": "Tuer offen → Licht einschalten (Flur/Eingang)",
        "severity": "info",
    },
    # Tuer oeffnet → Kamera
    {
        "role": "door_contact", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Tuer geoeffnet → Kamera aufzeichnen",
        "hint": "Tuer geoeffnet → Kamera-Aufzeichnung starten",
        "severity": "info",
    },
    # Tuer oeffnet → Benachrichtigung
    {
        "role": "door_contact", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Tuer geoeffnet → Benachrichtigung bei Abwesenheit",
        "hint": "Tuer geoeffnet → Benachrichtigung wenn niemand zuhause",
        "severity": "info",
    },
    # Tuer oeffnet → Lock-Inkonsistenz pruefen
    {
        "role": "door_contact", "state": "on",
        "affects": "lock", "same_room": True,
        "effect": "Tuer offen → Schloss-Status sollte 'unlocked' sein",
        "hint": "Tuer offen aber Schloss zeigt gesperrt → Inkonsistenz pruefen",
        "severity": "info",
    },

    # Garagentor → Licht
    {
        "role": "garage_door", "state": "open",
        "affects": "light", "same_room": True,
        "effect": "Garagentor offen → Garagenbeleuchtung einschalten",
        "hint": "Garagentor offen → Licht in Garage an",
        "severity": "info",
    },
    # Garagentor → Kamera
    {
        "role": "garage_door", "state": "open",
        "affects": "camera", "same_room": False,
        "effect": "Garagentor offen → Kamera aufzeichnen",
        "hint": "Garagentor oeffnet → Kamera-Aufzeichnung",
        "severity": "info",
    },
    # Garagentor → Benachrichtigung
    {
        "role": "garage_door", "state": "open",
        "affects": "notify", "same_room": False,
        "effect": "Garagentor offen → Benachrichtigung",
        "hint": "Garagentor geoeffnet → Benachrichtigung senden",
        "severity": "info",
    },
    # Garagentor → EV-Charger (Auto kann jetzt laden)
    {
        "role": "garage_door", "state": "open",
        "affects": "ev_charger", "same_room": False,
        "effect": "Garagentor offen → Auto kann angeschlossen werden",
        "hint": "Garage offen → E-Auto anschliessen zum Laden",
        "severity": "info",
    },

    # Tor/Einfahrt → Kamera
    {
        "role": "gate", "state": "open",
        "affects": "camera", "same_room": False,
        "effect": "Tor offen → Kamera aufzeichnen wer kommt",
        "hint": "Tor geoeffnet → Einfahrt-Kamera aufzeichnen",
        "severity": "info",
    },
    # Tor → Licht (Einfahrtbeleuchtung)
    {
        "role": "gate", "state": "open",
        "affects": "light", "same_room": False,
        "effect": "Tor offen → Einfahrtbeleuchtung einschalten",
        "hint": "Tor offen → Einfahrt-Beleuchtung an",
        "severity": "info",
    },
    # Tor → Benachrichtigung
    {
        "role": "gate", "state": "open",
        "affects": "notify", "same_room": False,
        "effect": "Tor geoeffnet → Benachrichtigung",
        "hint": "Tor geoeffnet → Benachrichtigung senden (Besucher?)",
        "severity": "info",
    },

    # =================================================================
    # SCHLOSS — erweiterte Trigger
    # =================================================================

    # Lock aufgesperrt → Kamera (wer hat aufgesperrt?)
    {
        "role": "lock", "state": "unlocked",
        "affects": "camera", "same_room": False,
        "effect": "Schloss entriegelt → Kamera pruefen wer aufgesperrt hat",
        "hint": "Schloss entriegelt → Kamera-Aufzeichnung, Person identifizieren",
        "severity": "info",
    },
    # Lock aufgesperrt → Licht (Eingang beleuchten)
    {
        "role": "lock", "state": "unlocked",
        "affects": "light", "same_room": True,
        "effect": "Schloss entriegelt → Eingangslicht einschalten",
        "hint": "Tuer entriegelt → Eingangslicht an",
        "severity": "info",
    },
    # Lock abgesperrt → Bestätigung
    {
        "role": "lock", "state": "locked",
        "affects": "notify", "same_room": False,
        "effect": "Schloss verriegelt → Bestaetigung",
        "hint": "Tuer abgesperrt → Sicherheits-Bestaetigung",
        "severity": "info",
    },

    # =================================================================
    # ALARM — fehlende triggered-Aktionen (KRITISCH!)
    # =================================================================

    # Alarm ausgeloest → Sirene MUSS erklingen!
    {
        "role": "alarm", "state": "triggered",
        "affects": "siren", "same_room": False,
        "effect": "Alarm ausgeloest → Sirene muss erklingen",
        "hint": "ALARM AUSGELOEST → Sirene aktivieren!",
        "severity": "critical",
    },
    # Alarm ausgeloest → ALLE Tueren verriegeln
    {
        "role": "alarm", "state": "triggered",
        "affects": "lock", "same_room": False,
        "effect": "Alarm ausgeloest → alle Tueren verriegeln",
        "hint": "ALARM → alle Schloesser verriegeln, Einbrecher einschliessen",
        "severity": "high",
    },
    # Alarm ausgeloest → Kameras aufzeichnen
    {
        "role": "alarm", "state": "triggered",
        "affects": "camera", "same_room": False,
        "effect": "Alarm ausgeloest → alle Kameras aufzeichnen",
        "hint": "ALARM → alle Kameras auf Aufzeichnung, Beweissicherung",
        "severity": "high",
    },
    # Alarm ausgeloest → Garagentor schliessen
    {
        "role": "alarm", "state": "triggered",
        "affects": "garage_door", "same_room": False,
        "effect": "Alarm ausgeloest → Garagentor schliessen",
        "hint": "ALARM → Garagentor schliessen, Fluchtweg blockieren",
        "severity": "high",
    },
    # Alarm ausgeloest → Tor schliessen
    {
        "role": "alarm", "state": "triggered",
        "affects": "gate", "same_room": False,
        "effect": "Alarm ausgeloest → Tor/Einfahrt schliessen",
        "hint": "ALARM → Tor schliessen",
        "severity": "high",
    },
    # Alarm ausgeloest → Rolllaeden hoch (Sichtbarkeit fuer Nachbarn/Polizei)
    {
        "role": "alarm", "state": "triggered",
        "affects": "blinds", "same_room": False,
        "effect": "Alarm ausgeloest → Rolllaeden/Jalousien oeffnen",
        "hint": "ALARM → Beschattung oeffnen, Sichtbarkeit fuer Nachbarn/Polizei",
        "severity": "high",
    },
    # Alarm ausgeloest → Shutter hoch
    {
        "role": "alarm", "state": "triggered",
        "affects": "shutter", "same_room": False,
        "effect": "Alarm ausgeloest → Rollladen hoch fuer Sichtbarkeit",
        "hint": "ALARM → Rollladen hoch, Sichtbarkeit fuer Nachbarn",
        "severity": "high",
    },
    # Alarm deaktiviert → Benachrichtigung
    {
        "role": "alarm", "state": "disarmed",
        "affects": "notify", "same_room": False,
        "effect": "Alarm deaktiviert → Bestaetigung senden",
        "hint": "Alarm deaktiviert → Bestaetigung, wer hat deaktiviert?",
        "severity": "info",
    },
    # Alarm deaktiviert → Willkommens-Szenario
    {
        "role": "alarm", "state": "disarmed",
        "affects": "light", "same_room": False,
        "effect": "Alarm deaktiviert (Ankunft) → Willkommens-Beleuchtung",
        "hint": "Alarm deaktiviert → Licht einschalten (Willkommen)",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "disarmed",
        "affects": "climate", "same_room": False,
        "effect": "Alarm deaktiviert (Ankunft) → Klima auf Komfort",
        "hint": "Alarm deaktiviert → Heizung/Kuehlung auf Komfort-Temperatur",
        "severity": "info",
    },

    # =================================================================
    # FENSTER — erweiterte Auswirkungen
    # =================================================================

    # Fenster offen → Luftreiniger sinnlos
    {
        "role": "window_contact", "state": "on",
        "affects": "air_purifier", "same_room": True,
        "effect": "Fenster offen + Luftreiniger an → Energieverschwendung",
        "hint": "Fenster offen → Luftreiniger sinnlos, neue Luft stroemt ein",
        "severity": "high",
    },
    # Fenster offen → Befeuchter/Entfeuchter sinnlos
    {
        "role": "window_contact", "state": "on",
        "affects": "humidifier", "same_room": True,
        "effect": "Fenster offen + Befeuchter → feuchte Luft geht raus",
        "hint": "Fenster offen → Befeuchter sinnlos, Feuchtigkeit geht verloren",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "dehumidifier", "same_room": True,
        "effect": "Fenster offen + Entfeuchter → arbeitet gegen Aussenluft",
        "hint": "Fenster offen → Entfeuchter sinnlos, neue Feuchtigkeit kommt rein",
        "severity": "info",
    },
    # Fenster offen → Laerm von draussen
    {
        "role": "window_contact", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Fenster offen → Strassenlaerm kommt rein",
        "hint": "Fenster offen → Aussenlaerm im Raum, ggf. Medien lauter",
        "severity": "info",
    },
    # Fenster offen → Licht aendert sich (Tageslicht)
    {
        "role": "window_contact", "state": "on",
        "affects": "light_level", "same_room": True,
        "effect": "Fenster offen → Lichverhaeltnisse aendern sich",
        "hint": "Fenster offen → Tageslicht/Sonneneinstrahlung aendert sich",
        "severity": "info",
    },
    # Fenster offen → Energie-Verschwendung bei HVAC
    {
        "role": "window_contact", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Fenster offen + HVAC laeuft → Energieverschwendung",
        "hint": "Fenster offen + Heizung/Kuehlung → Energiekosten steigen",
        "severity": "info",
    },
    # Fenster offen → PM2.5/Feinstaub kommt rein
    {
        "role": "window_contact", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Fenster offen → Aussenluft-Qualitaet beeinflusst Innenraum",
        "hint": "Fenster offen → Luftqualitaet aendert sich (Pollen, Feinstaub)",
        "severity": "info",
    },

    # =================================================================
    # RAUMTEMPERATUR — umfassende Interaktionen
    # =================================================================

    # Raumtemperatur → Beschattung
    {
        "role": "indoor_temp", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Raumtemperatur hoch → Beschattung senken",
        "hint": "Raum zu warm → Jalousien/Rollladen schliessen gegen Sonne",
        "severity": "info",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "shutter", "same_room": True,
        "effect": "Raumtemperatur hoch → Rollladen runter",
        "hint": "Raum zu warm → Rollladen schliessen gegen Aufheizung",
        "severity": "info",
    },
    # Raumtemperatur → Fenster (Lueften)
    {
        "role": "indoor_temp", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Raumtemperatur unangenehm → Fenster zum Lueften",
        "hint": "Raum zu warm/stickig → Fenster oeffnen zum Lueften",
        "severity": "info",
    },
    # Raumtemperatur → Ventilator
    {
        "role": "indoor_temp", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Raumtemperatur hoch → Ventilator einschalten",
        "hint": "Raum zu warm → Ventilator an fuer Kuehlung",
        "severity": "info",
    },
    # Raumtemperatur → Heizung anpassen
    {
        "role": "indoor_temp", "state": "on",
        "affects": "heating", "same_room": True,
        "effect": "Raumtemperatur beeinflusst Heizungs-Regelung",
        "hint": "Raumtemperatur → Heizung anpassen (hoch=runterregeln, niedrig=hochdrehen)",
        "severity": "info",
    },
    # Raumtemperatur → Kuehlung anpassen
    {
        "role": "indoor_temp", "state": "on",
        "affects": "cooling", "same_room": True,
        "effect": "Raumtemperatur beeinflusst Kuehlungs-Regelung",
        "hint": "Raumtemperatur → Kuehlung anpassen (hoch=mehr kuehlen, ok=ausschalten)",
        "severity": "info",
    },
    # Raumtemperatur → Lueftung
    {
        "role": "indoor_temp", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Raumtemperatur → Lueftung anpassen",
        "hint": "Raumtemperatur → Lueftung fuer Waermetausch nutzen",
        "severity": "info",
    },
    # Raumtemperatur → Thermostat
    {
        "role": "indoor_temp", "state": "on",
        "affects": "thermostat", "same_room": True,
        "effect": "Ist-Temperatur beeinflusst Thermostat-Regelung",
        "hint": "Raumtemperatur → Thermostat-Soll abgleichen",
        "severity": "info",
    },

    # =================================================================
    # ENTERTAINMENT — erweiterte Interaktionen
    # =================================================================

    # TV → Klima (TV erzeugt Waerme)
    {
        "role": "tv", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Fernseher erzeugt Waerme → Raumtemperatur steigt",
        "hint": "TV an → erzeugt Abwaerme, Raum wird waermer",
        "severity": "info",
    },
    # TV → Energie
    {
        "role": "tv", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Fernseher verbraucht Strom",
        "hint": "TV an → Stromverbrauch",
        "severity": "info",
    },
    # Gaming → Klima (Gaming-PC erzeugt viel Waerme)
    {
        "role": "gaming", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Gaming-PC/Konsole erzeugt starke Waerme",
        "hint": "Gaming → PC/Konsole erzeugt viel Abwaerme, Raum wird deutlich waermer",
        "severity": "info",
    },
    # Gaming → Beschattung (Blendschutz)
    {
        "role": "gaming", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Gaming → Blendschutz am Bildschirm noetig",
        "hint": "Gaming → Jalousien/Rollladen fuer Blendschutz",
        "severity": "info",
    },
    # Gaming → Energie (hoher Verbrauch)
    {
        "role": "gaming", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gaming-PC/Konsole → hoher Stromverbrauch",
        "hint": "Gaming → hoher Stromverbrauch (300-700W)",
        "severity": "info",
    },
    # Receiver → Media Player (Audio-Routing)
    {
        "role": "receiver", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "AV-Receiver an → Audio-Ausgabe ueber Receiver",
        "hint": "Receiver an → Audio wird ueber Receiver ausgegeben",
        "severity": "info",
    },
    # Receiver → TV (sollten zusammen an sein)
    {
        "role": "receiver", "state": "on",
        "affects": "tv", "same_room": True,
        "effect": "AV-Receiver an → TV sollte auch an sein",
        "hint": "Receiver an → TV auch einschalten",
        "severity": "info",
    },
    # Media Player → Klima (Raum wird genutzt)
    {
        "role": "media_player", "state": "playing",
        "affects": "climate", "same_room": True,
        "effect": "Medien spielen → Raum wird genutzt, Klima anpassen",
        "hint": "Medien laufen → Komfort-Temperatur halten",
        "severity": "info",
    },
    # Speaker → Nachbar-Laerm (Fenster)
    {
        "role": "speaker", "state": "playing",
        "affects": "noise", "same_room": True,
        "effect": "Lautsprecher spielt → Laermpegel im Raum steigt",
        "hint": "Lautsprecher laut → Laermpegel steigt, Fenster ggf. schliessen",
        "severity": "info",
    },
    # Speaker → Bett (zu laut zum Schlafen)
    {
        "role": "speaker", "state": "playing",
        "affects": "bed_occupancy", "same_room": False,
        "effect": "Lautsprecher spielt → koennte Schlafende stoeren",
        "hint": "Lautsprecher spielt + jemand schlaeft → Lautstaerke reduzieren",
        "severity": "info",
    },

    # =================================================================
    # LAERM — Reaktionen
    # =================================================================

    # Laerm hoch → Medien leiser
    {
        "role": "noise", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Hoher Laermpegel → Medien koennten die Quelle sein",
        "hint": "Laermpegel hoch → Medien-Lautstaerke pruefen/reduzieren",
        "severity": "info",
    },
    # Laerm hoch → Fenster schliessen
    {
        "role": "noise", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Hoher Laermpegel → Fenster schliessen gegen Laerm",
        "hint": "Laerm von draussen → Fenster schliessen",
        "severity": "info",
    },
    # Laerm hoch → Speaker leiser
    {
        "role": "noise", "state": "on",
        "affects": "speaker", "same_room": True,
        "effect": "Hoher Laermpegel → Lautsprecher koennten Quelle sein",
        "hint": "Laermpegel hoch → Lautsprecher leiser stellen",
        "severity": "info",
    },

    # =================================================================
    # VIBRATION — erweiterte Erkennung
    # =================================================================

    # Vibration → Kamera (was passiert?)
    {
        "role": "vibration", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Vibration erkannt → Kamera pruefen was passiert",
        "hint": "Vibration erkannt → Kamera-Aufzeichnung pruefen",
        "severity": "info",
    },
    # Vibration → Benachrichtigung
    {
        "role": "vibration", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Vibration erkannt → ungewoehnliche Erschuetterung melden",
        "hint": "Vibration erkannt → Benachrichtigung senden",
        "severity": "info",
    },

    # =================================================================
    # NETZ/ENERGIE — erweiterte Optimierung
    # =================================================================

    # Hoher Netzbezug → EV-Charger drosseln/stoppen
    {
        "role": "grid_consumption", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Hoher Netzbezug + EV laedt → teurer Strom",
        "hint": "Hoher Netzbezug → Wallbox drosseln, spaeter bei Solar laden",
        "severity": "info",
    },
    # Hoher Netzbezug → Waschmaschine verschieben
    {
        "role": "grid_consumption", "state": "on",
        "affects": "washing_machine", "same_room": False,
        "effect": "Hoher Netzbezug → Waschmaschine spaeter starten",
        "hint": "Netzbezug hoch → Waschmaschine auf Solar-Zeiten verschieben",
        "severity": "info",
    },
    # Hoher Netzbezug → allgemein Verbraucher reduzieren
    {
        "role": "grid_consumption", "state": "on",
        "affects": "heating", "same_room": False,
        "effect": "Hoher Netzbezug → Heizung drosseln wenn moeglich",
        "hint": "Netzbezug hoch → Heizung temporaer reduzieren",
        "severity": "info",
    },
    {
        "role": "grid_consumption", "state": "on",
        "affects": "cooling", "same_room": False,
        "effect": "Hoher Netzbezug → Kuehlung drosseln wenn moeglich",
        "hint": "Netzbezug hoch → Kuehlung temporaer reduzieren",
        "severity": "info",
    },
    # Netzeinspeisung → Geraete einschalten die Strom brauchen
    {
        "role": "grid_feed", "state": "on",
        "affects": "boiler", "same_room": False,
        "effect": "Einspeisung → Boiler mit Ueberschuss heizen",
        "hint": "Einspeisung → Warmwasser-Boiler mit Ueberschuss aufheizen",
        "severity": "info",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "pool", "same_room": False,
        "effect": "Einspeisung → Pool mit Ueberschuss heizen",
        "hint": "Einspeisung → Pool-Heizung mit Ueberschuss betreiben",
        "severity": "info",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Einspeisung → Waermepumpe mit Ueberschuss betreiben",
        "hint": "Einspeisung → Waermepumpe jetzt laufen lassen (thermisch speichern)",
        "severity": "info",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "dishwasher", "same_room": False,
        "effect": "Einspeisung → Spuelmaschine mit Ueberschuss starten",
        "hint": "Einspeisung → Spuelmaschine jetzt starten (gratis Strom)",
        "severity": "info",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "dryer", "same_room": False,
        "effect": "Einspeisung → Trockner mit Ueberschuss starten",
        "hint": "Einspeisung → Trockner jetzt starten (gratis Strom)",
        "severity": "info",
    },

    # =================================================================
    # LICHT (als Trigger) — erweiterte Szenarien
    # =================================================================

    # Licht aus → Kamera braucht Nachtsicht
    {
        "role": "light", "state": "off",
        "affects": "camera", "same_room": True,
        "effect": "Licht aus → Kamera wechselt auf Nachtsicht/IR",
        "hint": "Licht aus → Kamera nutzt Nachtsicht-Modus",
        "severity": "info",
    },
    # Licht an → Energie
    {
        "role": "light", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Licht eingeschaltet → Stromverbrauch",
        "hint": "Licht an → Stromverbrauch beachten",
        "severity": "info",
    },
    # Licht an → Blinds (Kunstlicht bei offenen Jalousien nachts = Einsehbarkeit)
    {
        "role": "light", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Licht an nachts + Jalousien offen → Raum einsehbar",
        "hint": "Licht an abends → Jalousien schliessen fuer Privatsphaere",
        "severity": "info",
    },
    {
        "role": "light", "state": "on",
        "affects": "shutter", "same_room": True,
        "effect": "Licht an nachts + Rollladen offen → Raum einsehbar",
        "hint": "Licht an abends → Rollladen runter fuer Privatsphaere",
        "severity": "info",
    },
    {
        "role": "light", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Licht an nachts + Vorhaenge offen → Raum einsehbar",
        "hint": "Licht an abends → Vorhaenge zuziehen fuer Privatsphaere",
        "severity": "info",
    },

    # =================================================================
    # WETTER → GERAETE — weitere Szenarien
    # =================================================================

    # Regen → Pool abdecken
    {
        "role": "rain", "state": "on",
        "affects": "pool", "same_room": False,
        "effect": "Regen → Pool abdecken (Verschmutzung, Chemie verduennt)",
        "hint": "Regen → Pool-Abdeckung schliessen, Wasser-Chemie schuetzen",
        "severity": "info",
    },
    # Regen → Dachfenster schliessen (Shutter als Dachfenster)
    {
        "role": "rain", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Regen → Jalousien/Markisen einfahren",
        "hint": "Regen → Aussen-Jalousien einfahren, Beschaedigungsgefahr",
        "severity": "high",
    },

    # Wind → Shutter (Rollladen bei Sturm einfahren statt rausfahren)
    {
        "role": "wind_speed", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Starker Wind → Rollladen einfahren (Beschaedigungsgefahr)",
        "hint": "Sturm → Rollladen einfahren, nicht draussen lassen",
        "severity": "high",
    },
    # Wind → Blinds
    {
        "role": "wind_speed", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Starker Wind → Jalousien einfahren (Beschaedigung)",
        "hint": "Sturm → Jalousien einfahren, Lamellenbruch verhindern",
        "severity": "high",
    },

    # =================================================================
    # PRESENCE ON — Ankunft-Szenarien
    # =================================================================

    # Ankunft → Schloss entriegeln
    {
        "role": "presence", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Person kommt → Tuer entriegeln",
        "hint": "Ankunft → Tuer entriegeln fuer Bewohner",
        "severity": "info",
    },
    # Ankunft → Alarm deaktivieren
    {
        "role": "presence", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Person kommt → Alarm deaktivieren",
        "hint": "Ankunft erkannt → Alarm deaktivieren",
        "severity": "info",
    },
    # Ankunft → Medien
    {
        "role": "presence", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Person kommt → Willkommens-Musik oder Nachrichten",
        "hint": "Ankunft → Lieblingsmusik/Nachrichten abspielen",
        "severity": "info",
    },
    # Ankunft → Blinds oeffnen
    {
        "role": "presence", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Person kommt → Beschattung oeffnen bei Tageslicht",
        "hint": "Ankunft tagsueber → Rollladen/Jalousien oeffnen",
        "severity": "info",
    },

    # =================================================================
    # ABWESENHEIT — noch mehr Geraete pruefen
    # =================================================================

    # Niemand da + Heizluefter an Steckdose
    {
        "role": "presence", "state": "off",
        "affects": "heating", "same_room": False,
        "effect": "Niemand zuhause → Heizung auf Eco/Abwesenheit",
        "hint": "Alle weg → Heizung auf Absenktemperatur",
        "severity": "info",
    },
    # Niemand da + Klimaanlage
    {
        "role": "presence", "state": "off",
        "affects": "cooling", "same_room": False,
        "effect": "Niemand zuhause → Kuehlung auf Eco/Abwesenheit",
        "hint": "Alle weg → Kuehlung auf Absenktemperatur oder aus",
        "severity": "info",
    },
    # Niemand da + Ventilation
    {
        "role": "presence", "state": "off",
        "affects": "ventilation", "same_room": False,
        "effect": "Niemand zuhause → Lueftung auf Minimum",
        "hint": "Alle weg → Lueftung auf Abwesenheits-Modus",
        "severity": "info",
    },
    # Niemand da + Blinds/Shutter (Einbruchschutz)
    {
        "role": "presence", "state": "off",
        "affects": "blinds", "same_room": False,
        "effect": "Niemand zuhause → Beschattung fuer Einbruchschutz",
        "hint": "Alle weg → Rollladen runter als Einbruchschutz",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "shutter", "same_room": False,
        "effect": "Niemand zuhause → Rollladen als Einbruchschutz",
        "hint": "Alle weg → Rollladen runter als Einbruchschutz",
        "severity": "info",
    },
    # Niemand da + Wasser-Hauptventil
    {
        "role": "presence", "state": "off",
        "affects": "valve", "same_room": False,
        "effect": "Laenger weg → Wasser-Hauptventil schliessen",
        "hint": "Laenger weg (Urlaub) → Wasser-Hauptventil schliessen, Wasserschaden verhindern",
        "severity": "info",
    },
    # Niemand da + Gartenbeleuchtung
    {
        "role": "presence", "state": "off",
        "affects": "garden_light", "same_room": False,
        "effect": "Niemand zuhause → Gartenbeleuchtung aus oder Simulation",
        "hint": "Alle weg → Gartenbeleuchtung aus (oder Anwesenheits-Simulation)",
        "severity": "info",
    },
    # Niemand da + Kamera (Ueberwachung aktivieren)
    {
        "role": "presence", "state": "off",
        "affects": "camera", "same_room": False,
        "effect": "Niemand zuhause → Kameras auf Aufzeichnung",
        "hint": "Alle weg → Kameras auf Daueraufzeichnung/Bewegungserkennung",
        "severity": "info",
    },

    # =================================================================
    # BETT-SZENARIEN — erweitert
    # =================================================================

    # Im Bett → Shutter runter
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "shutter", "same_room": True,
        "effect": "Im Bett → Rollladen schliessen fuer Dunkelheit",
        "hint": "Schlafenszeit → Rollladen runter, Raum abdunkeln",
        "severity": "info",
    },
    # Im Bett → Thermostat Nacht-Temperatur
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "thermostat", "same_room": True,
        "effect": "Im Bett → Thermostat auf Nacht-Temperatur",
        "hint": "Schlafenszeit → Heizung auf Nacht-Temperatur (kuehler zum Schlafen)",
        "severity": "info",
    },
    # Im Bett → TV/PC aus
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "tv", "same_room": False,
        "effect": "Im Bett → TV sollte aus sein",
        "hint": "Schlafenszeit → TV ausschalten",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "pc", "same_room": False,
        "effect": "Im Bett → PC sollte herunterfahren",
        "hint": "Schlafenszeit → PC herunterfahren/Standby",
        "severity": "info",
    },
    # Im Bett → Ventilation leiser (kein Laerm)
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Im Bett → Lueftung auf leise/Nacht-Modus",
        "hint": "Schlafenszeit → Lueftung auf Silent/Nacht-Modus",
        "severity": "info",
    },
    # Aufstehen (bed_occupancy off) → Morgenroutine
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Aufgestanden → Licht sanft einschalten",
        "hint": "Aufgestanden → Licht langsam an (Sonnenaufgangs-Simulation)",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "Aufgestanden → Jalousien oeffnen",
        "hint": "Aufgestanden → Jalousien/Rollladen oeffnen, Tageslicht rein",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "shutter", "same_room": True,
        "effect": "Aufgestanden → Rollladen hoch",
        "hint": "Aufgestanden → Rollladen hoch, Tageslicht rein",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Aufgestanden → Klima auf Tages-Komfort",
        "hint": "Aufgestanden → Heizung/Kuehlung auf Tages-Temperatur",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "coffee_machine", "same_room": False,
        "effect": "Aufgestanden → Kaffeemaschine aufheizen",
        "hint": "Aufgestanden → Kaffeemaschine einschalten",
        "severity": "info",
    },

    # =================================================================
    # STUHL-BELEGUNG — Arbeitsplatz-Szenarien
    # =================================================================

    # Am Schreibtisch → Vakuum stoppen (Meeting/Arbeit)
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "vacuum", "same_room": True,
        "effect": "Am Schreibtisch → Staubsauger stoert bei Arbeit",
        "hint": "Am Schreibtisch → Staubsauger pausieren (Arbeit/Meeting)",
        "severity": "info",
    },
    # Am Schreibtisch → Blinds (Blendschutz Monitor)
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Am Schreibtisch → Blendschutz fuer Monitor",
        "hint": "Am Schreibtisch → Jalousien fuer Blendschutz am Monitor",
        "severity": "info",
    },

    # =================================================================
    # AUTO / FAHRZEUG — erweitert
    # =================================================================

    # Auto zuhause → EV-Charger (laden wenn Solar)
    {
        "role": "car", "state": "home",
        "affects": "ev_charger", "same_room": False,
        "effect": "Auto zuhause → kann geladen werden",
        "hint": "Auto geparkt → Wallbox starten wenn Solar verfuegbar",
        "severity": "info",
    },
    # Auto weg → Alarm scharf schalten (wenn letztes Familienmitglied)
    {
        "role": "car", "state": "not_home",
        "affects": "alarm", "same_room": False,
        "effect": "Auto weg → moeglicherweise niemand mehr zuhause",
        "hint": "Auto weg → Alarm pruefen/scharfschalten wenn alle weg",
        "severity": "info",
    },
    # Auto weg → Garagentor schliessen
    {
        "role": "car", "state": "not_home",
        "affects": "light", "same_room": False,
        "effect": "Auto weg → Garagenbeleuchtung aus",
        "hint": "Auto weg → Garage-Licht ausschalten",
        "severity": "info",
    },
    # Auto-Batterie → Solar (laden mit Ueberschuss)
    {
        "role": "car_battery", "state": "on",
        "affects": "solar", "same_room": False,
        "effect": "Auto-Batterie-Stand → Solar-Ladestrategie anpassen",
        "hint": "Auto-Batterie niedrig → bei naechstem Solar-Ueberschuss laden",
        "severity": "info",
    },
    # Auto-Batterie → Notify (Batterie niedrig)
    {
        "role": "car_battery", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Auto-Batterie niedrig → Warnung senden",
        "hint": "Auto-Batterie niedrig → an Laden erinnern",
        "severity": "info",
    },

    # =================================================================
    # KAMERA — als Trigger
    # =================================================================

    # Kamera erkennt Bewegung → Alarm/Notify
    {
        "role": "camera", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Kamera erkennt Aktivitaet → Alarm pruefen",
        "hint": "Kamera-Bewegung → Alarm-Status pruefen",
        "severity": "info",
    },
    {
        "role": "camera", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Kamera erkennt Aktivitaet → Benachrichtigung",
        "hint": "Kamera → Bewegungs-Benachrichtigung mit Bild senden",
        "severity": "info",
    },
    # Kamera → Gartenbeleuchtung (nachts Licht an bei Bewegung)
    {
        "role": "camera", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Kamera erkennt Bewegung draussen → Licht an fuer besseres Bild",
        "hint": "Kamera-Bewegung → Gartenbeleuchtung fuer bessere Aufnahmen",
        "severity": "info",
    },

    # =================================================================
    # BOILER / WARMWASSER
    # =================================================================

    # Boiler → Wassertemperatur
    {
        "role": "boiler", "state": "on",
        "affects": "water_temp", "same_room": False,
        "effect": "Boiler heizt → Wassertemperatur steigt",
        "hint": "Boiler heizt → Warmwasser wird vorbereitet",
        "severity": "info",
    },
    # Wassertemperatur → Boiler (zu niedrig → nachheizen)
    {
        "role": "water_temp", "state": "on",
        "affects": "boiler", "same_room": False,
        "effect": "Wassertemperatur niedrig → Boiler muss nachheizen",
        "hint": "Warmwasser zu kalt → Boiler nachheizen",
        "severity": "info",
    },

    # =================================================================
    # PUMPE — erweiterte Szenarien
    # =================================================================

    {
        "role": "pump", "state": "on",
        "affects": "water_consumption", "same_room": False,
        "effect": "Pumpe laeuft → Wasserverbrauch/-zirkulation",
        "hint": "Pumpe aktiv → Wasserverbrauch/-druck beobachten",
        "severity": "info",
    },
    {
        "role": "pump", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Pumpe laeuft → Geraeuschentwicklung",
        "hint": "Pumpe laeuft → Geraeusch im Raum, nachts ggf. stoerend",
        "severity": "info",
    },

    # =================================================================
    # TIMER / AUTOMATION — Interaktionen
    # =================================================================

    # Timer abgelaufen → Benachrichtigung (z.B. Waschmaschine, Kochen)
    {
        "role": "timer", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Timer abgelaufen → Erinnerung",
        "hint": "Timer fertig → Erinnerung senden (Kochen, Waschmaschine, etc.)",
        "severity": "info",
    },
    # Timer abgelaufen → Media Player (akustisches Signal)
    {
        "role": "timer", "state": "off",
        "affects": "media_player", "same_room": False,
        "effect": "Timer abgelaufen → akustisches Signal",
        "hint": "Timer fertig → Ton/Ansage abspielen",
        "severity": "info",
    },
    # Timer abgelaufen → Licht (visuelles Signal)
    {
        "role": "timer", "state": "off",
        "affects": "light", "same_room": False,
        "effect": "Timer abgelaufen → visuelles Signal",
        "hint": "Timer fertig → Licht blinken/Farbe aendern als Signal",
        "severity": "info",
    },

    # =================================================================
    # GERAETE-GESUNDHEIT / UPDATE
    # =================================================================

    # Update verfuegbar → Automation koennte betroffen sein
    {
        "role": "update", "state": "on",
        "affects": "automation", "same_room": False,
        "effect": "Update verfuegbar → nach Update Automatisierungen pruefen",
        "hint": "Update pending → nach Installation Automatisierungen testen",
        "severity": "info",
    },

    # =================================================================
    # STECKDOSEN / RELAY — erweitert
    # =================================================================

    # Steckdose an + Abwesenheit → vergessener Verbraucher
    {
        "role": "outlet", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Steckdose aktiv → Verbraucher laeuft",
        "hint": "Steckdose mit Verbrauch → Geraet laeuft, bei Abwesenheit pruefen",
        "severity": "info",
    },
    # Relay schaltet → Benachrichtigung
    {
        "role": "relay", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Relay geschaltet → Geraet wurde aktiviert",
        "hint": "Relay geschaltet → verbundenes Geraet aktiviert",
        "severity": "info",
    },

    # =================================================================
    # DIMMER / FARBLICHT — Szenarien
    # =================================================================

    # Dimmer gedimmt → Stimmungslicht / Filmabend
    {
        "role": "dimmer", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Licht gedimmt → Filmabend/Stimmung",
        "hint": "Licht gedimmt → Filmabend-Atmosphaere erkannt",
        "severity": "info",
    },
    # Dimmer gedimmt → Blinds (Abdunkelung fuer Stimmung)
    {
        "role": "dimmer", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Licht gedimmt → Beschattung fuer Stimmung",
        "hint": "Licht gedimmt → Jalousien ggf. schliessen fuer Atmosphaere",
        "severity": "info",
    },
    # Farblicht → Stimmungs-Kontext
    {
        "role": "color_light", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Farblicht aktiv → Stimmungsbeleuchtung",
        "hint": "Farblicht → Raum-Atmosphaere, Medien anpassen",
        "severity": "info",
    },

    # =================================================================
    # RAUCHMELDER — erweiterte Reaktionen
    # =================================================================

    # Rauch → Heizung AUS (koennte Brand anheizen)
    {
        "role": "smoke", "state": "on",
        "affects": "heating", "same_room": False,
        "effect": "Rauch → Heizung ausschalten, Brand nicht foerdern",
        "hint": "Rauch → Heizung AUS, Brand nicht verstaerken",
        "severity": "critical",
    },
    # Rauch → Gas-Ventil schliessen
    {
        "role": "smoke", "state": "on",
        "affects": "valve", "same_room": False,
        "effect": "Rauch → Gas-Ventil sofort schliessen",
        "hint": "Rauch → Gas abstellen, Explosionsgefahr minimieren",
        "severity": "critical",
    },
    # Rauch → Tueren entriegeln (Fluchtweg!)
    {
        "role": "smoke", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Rauch/Brand → alle Tueren entriegeln fuer Flucht",
        "hint": "BRAND → Tueren entriegeln, Fluchtweg frei machen!",
        "severity": "critical",
    },
    # Rauch → Garage oeffnen (Fluchtweg)
    {
        "role": "smoke", "state": "on",
        "affects": "garage_door", "same_room": False,
        "effect": "Rauch/Brand → Garagentor oeffnen fuer Flucht",
        "hint": "BRAND → Garagentor oeffnen als Fluchtweg",
        "severity": "critical",
    },
    # Rauch → Sirene
    {
        "role": "smoke", "state": "on",
        "affects": "siren", "same_room": False,
        "effect": "Rauch → Sirene aktivieren fuer Warnung",
        "hint": "RAUCH → Sirene aktivieren, alle warnen",
        "severity": "critical",
    },
    # Rauch → Notify (sofort alle informieren)
    {
        "role": "smoke", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Rauch → sofort alle Bewohner benachrichtigen",
        "hint": "RAUCH → sofort Push/Anruf an alle Bewohner",
        "severity": "critical",
    },

    # =================================================================
    # CO-MELDER — erweiterte Reaktionen
    # =================================================================

    # CO → Tueren/Fenster oeffnen (lueften!)
    {
        "role": "co", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "CO → Tueren entriegeln, Flucht und Lueftung",
        "hint": "CO → Tueren entriegeln, raus und lueften!",
        "severity": "critical",
    },
    # CO → Heizung AUS (koennte Quelle sein - Gastherme)
    {
        "role": "co", "state": "on",
        "affects": "heating", "same_room": False,
        "effect": "CO → Heizung aus, koennte CO-Quelle sein (Gastherme)",
        "hint": "CO → Heizung AUS, Gastherme koennte Quelle sein",
        "severity": "critical",
    },
    # CO → Boiler AUS (koennte Quelle sein)
    {
        "role": "co", "state": "on",
        "affects": "boiler", "same_room": False,
        "effect": "CO → Boiler aus, koennte CO-Quelle sein",
        "hint": "CO → Boiler AUS, Gas-Boiler koennte Quelle sein",
        "severity": "critical",
    },
    # CO → Notify
    {
        "role": "co", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "CO → sofort alle warnen",
        "hint": "CO → SOFORT alle Bewohner warnen, LEBENSGEFAHR",
        "severity": "critical",
    },
    # CO → Sirene
    {
        "role": "co", "state": "on",
        "affects": "siren", "same_room": False,
        "effect": "CO → Sirene aktivieren",
        "hint": "CO → Sirene aktivieren, alle warnen",
        "severity": "critical",
    },
    # CO → Licht (Fluchtweg beleuchten)
    {
        "role": "co", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "CO → Fluchtweg-Beleuchtung einschalten",
        "hint": "CO → alle Lichter an fuer Fluchtweg",
        "severity": "critical",
    },

    # =================================================================
    # GAS-MELDER — erweiterte Reaktionen
    # =================================================================

    # Gas → Fenster oeffnen (aber NICHT elektrisch! Manuell oeffnen)
    {
        "role": "gas", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Gas → sofort alle warnen, Haus verlassen",
        "hint": "GAS → SOFORT alle warnen, Haus verlassen, NICHT schalten!",
        "severity": "critical",
    },
    # Gas → Heizung AUS (Quelle koennte Gastherme sein)
    {
        "role": "gas", "state": "on",
        "affects": "heating", "same_room": False,
        "effect": "Gas → Heizung aus, koennte Gas-Leck-Quelle sein",
        "hint": "GAS → Heizung AUS falls sicher moeglich",
        "severity": "critical",
    },
    # Gas → Boiler AUS
    {
        "role": "gas", "state": "on",
        "affects": "boiler", "same_room": False,
        "effect": "Gas → Boiler aus, koennte Gas-Leck-Quelle sein",
        "hint": "GAS → Boiler AUS falls sicher moeglich",
        "severity": "critical",
    },
    # Gas → Licht NICHT schalten (Funke!) — bereits als relay, nochmal explizit
    {
        "role": "gas", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Gas → Licht NICHT ein/ausschalten, Funkengefahr",
        "hint": "GAS → Licht NICHT schalten! Funke = Explosionsgefahr!",
        "severity": "critical",
    },
    # Gas → Sirene
    {
        "role": "gas", "state": "on",
        "affects": "siren", "same_room": False,
        "effect": "Gas → Sirene aktivieren (wenn batteriebetrieben/sicher)",
        "hint": "GAS → Sirene aktivieren wenn sicher (batteriebetrieben)",
        "severity": "critical",
    },

    # =================================================================
    # WASSERLECK — erweiterte Reaktionen
    # =================================================================

    # Wasserleck → Pumpe stoppen
    {
        "role": "water_leak", "state": "on",
        "affects": "pump", "same_room": False,
        "effect": "Wasserleck → Pumpe stoppen, kein Wasser mehr foerdern",
        "hint": "Wasserleck → Pumpe sofort stoppen",
        "severity": "high",
    },
    # Wasserleck → Boiler pruefen
    {
        "role": "water_leak", "state": "on",
        "affects": "boiler", "same_room": True,
        "effect": "Wasserleck in Naehe Boiler → koennte Quelle sein",
        "hint": "Wasserleck → Boiler als Quelle pruefen",
        "severity": "high",
    },
    # Wasserleck → Benachrichtigung (nochmal explizit direkt)
    {
        "role": "water_leak", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Wasserleck → sofort benachrichtigen",
        "hint": "WASSERLECK → sofort Benachrichtigung an alle!",
        "severity": "high",
    },
    # Wasserleck → Heizung pruefen (Heizkoerper undicht?)
    {
        "role": "water_leak", "state": "on",
        "affects": "heating", "same_room": True,
        "effect": "Wasserleck → Heizkoerper/Fussbodenheizung als Quelle?",
        "hint": "Wasserleck → Heizung als Leck-Quelle pruefen",
        "severity": "high",
    },

    # =================================================================
    # SABOTAGE / TAMPER — erweitert
    # =================================================================

    {
        "role": "tamper", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Sabotage erkannt → Kamera-Aufzeichnung starten",
        "hint": "Sabotage erkannt → Kamera-Beweis sichern",
        "severity": "high",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Sabotage erkannt → sofort benachrichtigen",
        "hint": "Sabotage → sofort Benachrichtigung senden",
        "severity": "high",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "siren", "same_room": False,
        "effect": "Sabotage erkannt → Sirene aktivieren",
        "hint": "Sabotage erkannt → Sirene als Abschreckung",
        "severity": "high",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Sabotage erkannt → alle Lichter an",
        "hint": "Sabotage → Beleuchtung an fuer Abschreckung",
        "severity": "high",
    },

    # =================================================================
    # PROBLEM-SENSOR → erweiterte Auswirkungen
    # =================================================================

    {
        "role": "problem", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Problem bei Geraet → Kamera-Aufnahme fuer Diagnose",
        "hint": "Geraete-Problem → Kamera-Aufnahme fuer Fehlersuche",
        "severity": "info",
    },

    # =================================================================
    # GENERIC_SENSOR / GENERIC_SWITCH — Catch-All
    # =================================================================

    # Generic Sensor hat Wert → Benachrichtigung wenn ausserhalb Norm
    {
        "role": "generic_sensor", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Sensor-Wert aendert sich → pruefen ob im Normalbereich",
        "hint": "Sensor-Aenderung → Wert pruefen, ggf. benachrichtigen",
        "severity": "info",
    },
    {
        "role": "generic_sensor", "state": "on",
        "affects": "automation", "same_room": False,
        "effect": "Sensor-Wert aendert sich → Automatisierung reagieren lassen",
        "hint": "Sensor-Aenderung → abhaengige Automatisierungen pruefen",
        "severity": "info",
    },

    # Generic Switch geschaltet → Energieverbrauch + Benachrichtigung
    {
        "role": "generic_switch", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Schalter aktiviert → Verbraucher laeuft",
        "hint": "Schalter an → angeschlossener Verbraucher aktiv",
        "severity": "info",
    },
    {
        "role": "generic_switch", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Schalter aktiviert → Status-Aenderung",
        "hint": "Schalter geschaltet → Status-Aenderung melden",
        "severity": "info",
    },
    {
        "role": "generic_switch", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Schalter deaktiviert → Status-Aenderung",
        "hint": "Schalter ausgeschaltet → Status-Aenderung melden",
        "severity": "info",
    },
]



class StateChangeLog:
    """Protokolliert Geraete-Aenderungen mit Quellen-Erkennung."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._log: deque[dict] = deque(maxlen=MAX_LOG_ENTRIES)
        # Jarvis-Marker: Entity-IDs die JARVIS gerade aendert (TTL 10s)
        self._jarvis_pending: dict[str, float] = {}

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        # Bestehende Eintraege laden
        if self.redis:
            try:
                raw = await self.redis.lrange(REDIS_KEY_LOG, 0, MAX_LOG_ENTRIES - 1)
                for entry in reversed(raw):
                    try:
                        self._log.append(json.loads(entry))
                    except (json.JSONDecodeError, TypeError):
                        pass
            except Exception as e:
                logger.debug("State-Change-Log laden fehlgeschlagen: %s", e)
        logger.info("StateChangeLog initialisiert (%d Eintraege)", len(self._log))

    def mark_jarvis_action(self, entity_id: str):
        """Markiert dass JARVIS gleich eine Aktion auf dieser Entity ausfuehrt."""
        self._jarvis_pending[entity_id] = time.time()

    def _detect_source(self, entity_id: str, new_state: dict) -> str:
        """Erkennt die Quelle einer State-Change.

        Nutzt:
        - Jarvis-Marker (mark_jarvis_action)
        - HA context.user_id (None = Automation, vorhanden = User/API)
        - HA context.parent_id (vorhanden = durch andere Automation ausgeloest)
        """
        # Jarvis-Marker pruefen (10s Fenster)
        jarvis_ts = self._jarvis_pending.pop(entity_id, None)
        if jarvis_ts and (time.time() - jarvis_ts) < 10:
            return "jarvis"

        # HA Context auswerten
        ha_context = new_state.get("context", {})
        if isinstance(ha_context, dict):
            user_id = ha_context.get("user_id")
            parent_id = ha_context.get("parent_id")

            if parent_id:
                # Durch eine andere Automation/Script ausgeloest
                return "automation"
            if user_id:
                # User-Aktion (App, Dashboard, API)
                return "user_app"
            # Kein user_id, kein parent_id → physischer Trigger oder HA-interne Automation
            return "automation"

        return "unknown"

    async def log_change(
        self, entity_id: str, old_val: str, new_val: str,
        new_state: dict, friendly_name: str = "",
    ):
        """Loggt eine State-Change mit Quellen-Erkennung."""
        source = self._detect_source(entity_id, new_state)
        name = friendly_name or new_state.get("attributes", {}).get(
            "friendly_name", entity_id
        )

        entry = {
            "entity_id": entity_id,
            "name": name,
            "old": old_val,
            "new": new_val,
            "source": source,
            "ts": time.time(),
            "time_str": time.strftime("%H:%M"),
        }

        self._log.append(entry)

        # In Redis persistieren
        if self.redis:
            try:
                await self.redis.lpush(
                    REDIS_KEY_LOG,
                    json.dumps(entry, ensure_ascii=False),
                )
                await self.redis.ltrim(REDIS_KEY_LOG, 0, MAX_LOG_ENTRIES - 1)
                await self.redis.expire(REDIS_KEY_LOG, LOG_TTL_SECONDS)
            except Exception as e:
                logger.debug("State-Change-Log Redis-Fehler: %s", e)

    def get_recent(self, n: int = 10, domain: str = "") -> list[dict]:
        """Gibt die letzten N State-Changes zurueck.

        Args:
            n: Anzahl (default 10)
            domain: Optional filtern nach Domain (light, climate, etc.)
        """
        if domain:
            filtered = [
                e for e in self._log
                if e.get("entity_id", "").startswith(f"{domain}.")
            ]
            return list(filtered)[-n:]
        return list(self._log)[-n:]

    @staticmethod
    def _get_entity_role(entity_id: str) -> str:
        """Holt die Annotation-Rolle fuer eine Entity.

        Lazy-Import um zirkulaere Imports zu vermeiden.
        Faellt auf HA-Domain zurueck wenn keine Annotation vorhanden.
        """
        try:
            from .function_calling import get_entity_annotation
            ann = get_entity_annotation(entity_id)
            if ann and ann.get("role"):
                return ann["role"]
        except Exception:
            pass
        # Fallback: HA-Domain als Pseudo-Rolle (z.B. "light", "climate")
        return entity_id.split(".")[0] if "." in entity_id else ""

    @staticmethod
    def _get_entity_room(entity_id: str) -> str:
        """Holt den Raum fuer eine Entity aus Annotations oder MindHome.

        Lazy-Import um zirkulaere Imports zu vermeiden.
        """
        try:
            from .function_calling import get_entity_annotation, _mindhome_device_rooms
            ann = get_entity_annotation(entity_id)
            if ann and ann.get("room"):
                return ann["room"].lower()
            # Fallback: MindHome Device-Room-Mapping
            if _mindhome_device_rooms and entity_id in _mindhome_device_rooms:
                return _mindhome_device_rooms[entity_id].lower()
        except Exception:
            pass
        return ""

    def detect_conflicts(self, states: dict) -> list[dict]:
        """Prueft aktuelle HA-States gegen DEVICE_DEPENDENCIES.

        Nutzt Entity-Annotation-Rollen fuer praezises Matching.
        Beruecksichtigt Raum-Zuordnung fuer same_room-Regeln.

        Args:
            states: Dict entity_id -> state-string (z.B. "on", "heat", "open")

        Returns:
            Liste aktiver Konflikte mit Hinweisen fuers LLM.
        """
        # Entity-Rollen und Raeume einmalig cachen
        entity_roles: dict[str, str] = {}
        entity_rooms: dict[str, str] = {}
        for eid in states:
            entity_roles[eid] = self._get_entity_role(eid)
            entity_rooms[eid] = self._get_entity_room(eid)

        conflicts = []
        for dep in DEVICE_DEPENDENCIES:
            cond_role = dep["role"]
            cond_state = dep["state"]
            same_room = dep.get("same_room", False)

            # Finde alle Entities die diese Rolle + State haben
            matching = [
                eid for eid, st in states.items()
                if entity_roles.get(eid) == cond_role and st == cond_state
            ]
            if not matching:
                continue

            # Betroffene Rolle/Domain
            affected = dep["affects"]
            required_states = dep.get("requires_state")

            # Pruefen ob betroffene Rolle/Domain aktiv ist
            # Matcht sowohl gegen Rollen als auch HA-Domains
            for trigger_eid in matching:
                trigger_room = entity_rooms.get(trigger_eid, "")

                affected_active = False
                for eid, val in states.items():
                    if val in ("off", "unavailable", "unknown", "idle"):
                        continue
                    eid_role = entity_roles.get(eid, "")
                    eid_domain = eid.split(".")[0] if "." in eid else ""

                    # Match gegen Rolle ODER Domain
                    if eid_role != affected and eid_domain != affected:
                        continue

                    # requires_state: Nur Konflikt wenn Entity in passendem State
                    if required_states and val not in required_states:
                        continue

                    # same_room Check
                    if same_room and trigger_room:
                        eid_room = entity_rooms.get(eid, "")
                        if eid_room and eid_room != trigger_room:
                            continue

                    affected_active = True
                    break

                conflicts.append({
                    "trigger_entity": trigger_eid,
                    "trigger_role": cond_role,
                    "trigger_state": cond_state,
                    "trigger_room": trigger_room,
                    "affected_role": affected,
                    "affected_active": affected_active,
                    "same_room": same_room,
                    "effect": dep["effect"],
                    "hint": dep["hint"],
                })
        return conflicts

    def format_conflicts_for_prompt(self, states: dict) -> str:
        """Formatiert aktive Geraete-Konflikte als LLM-Kontext.

        Args:
            states: Dict entity_id -> state-string

        Returns:
            Prompt-Sektion oder leerer String.
        """
        conflicts = self.detect_conflicts(states)
        if not conflicts:
            return ""

        # Nur Konflikte wo betroffene Domain/Rolle aktiv ist (echte Konflikte)
        active_conflicts = [c for c in conflicts if c["affected_active"]]
        if not active_conflicts:
            return ""

        # F-090: Sanitization — Room-Namen und Hints koennen aus
        # Annotations/HA stammen → Prompt-Injection verhindern
        try:
            from .context_builder import _sanitize_for_prompt
        except ImportError:
            _sanitize_for_prompt = None

        lines = []
        seen = set()
        for c in active_conflicts:
            # Raum-Info in Hinweis einbauen wenn vorhanden
            room = c.get("trigger_room", "")
            if room and _sanitize_for_prompt:
                room = _sanitize_for_prompt(room, 50, "conflict_room")
            room_info = f" [{room}]" if room else ""
            hint = c.get("hint", "")
            effect = c.get("effect", "")
            if _sanitize_for_prompt:
                hint = _sanitize_for_prompt(hint, 200, "conflict_hint")
                effect = _sanitize_for_prompt(effect, 200, "conflict_effect")
            if not hint:
                continue
            key = (c["trigger_entity"], c["affected_role"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {hint}{room_info} ({effect})")

        if not lines:
            return ""

        return (
            "\n\nAKTIVE GERAETE-KONFLIKTE (rein informativ):\n"
            + "\n".join(lines)
            + "\nWeise den User beilaeufig auf diese Konflikte hin, "
            "wenn er nach Energie, Heizung oder Raumklima fragt. "
            "WICHTIG: Diese Konflikte sind nur Hinweise — verweigere "
            "NIEMALS eine Aktion des Users wegen eines Konflikts."
        )

    @staticmethod
    def check_action_dependencies(
        action_function: str,
        action_args: dict,
        ha_states: list[dict],
    ) -> list[str]:
        """Prueft ob eine geplante Aktion Device-Dependency-Konflikte ausloest.

        Wiederverwendbare Methode fuer alle Module (action_planner, protocol_engine,
        conflict_resolver, self_automation, conditional_commands).

        Args:
            action_function: Funktionsname (z.B. "set_climate", "set_light")
            action_args: Argumente der Funktion
            ha_states: Aktuelle HA-States als Liste von State-Dicts

        Returns:
            Liste von Hinweis-Strings. Leer wenn keine Konflikte.
        """
        hints = []
        try:
            state_dict = {
                s["entity_id"]: s.get("state", "")
                for s in ha_states
                if "entity_id" in s
            }
            # Hypothetischen neuen State eintragen
            target_entity = action_args.get("entity_id", "")
            new_state_val = action_args.get("state", action_args.get("action", ""))
            if target_entity and new_state_val:
                state_dict[target_entity] = str(new_state_val).lower()

            scl = StateChangeLog.__new__(StateChangeLog)
            conflicts = scl.detect_conflicts(state_dict)

            if target_entity and conflicts:
                relevant = [
                    c for c in conflicts
                    if target_entity in c.get("entities", [])
                ]
                for c in relevant[:3]:
                    room_info = f" ({c.get('room', '')})" if c.get("room") else ""
                    hints.append(f"{c['hint']}{room_info}")
            elif not target_entity and conflicts:
                # Ohne target_entity: Domain-basiert filtern
                domain = action_function.replace("set_", "").replace("_room", "")
                relevant = [
                    c for c in conflicts
                    if domain in c.get("affected_role", "") or domain in c.get("trigger_role", "")
                ]
                for c in relevant[:3]:
                    room_info = f" ({c.get('room', '')})" if c.get("room") else ""
                    hints.append(f"{c['hint']}{room_info}")
        except Exception as e:
            logger.debug("check_action_dependencies Fehler: %s", e)
        return hints

    def format_for_prompt(self, n: int = 10) -> str:
        """Formatiert die letzten Aenderungen als LLM-Kontext.

        Returns:
            Prompt-Sektion oder leerer String.
        """
        recent = self.get_recent(n)
        if not recent:
            return ""

        # Nur Aenderungen der letzten 30 Minuten
        cutoff = time.time() - 1800
        recent = [e for e in recent if e.get("ts", 0) > cutoff]
        if not recent:
            return ""

        source_labels = {
            "jarvis": "JARVIS",
            "automation": "HA-Automation",
            "user_app": "User (App/Dashboard)",
            "user_physical": "User (physisch)",
            "unknown": "unbekannt",
        }

        lines = []
        for e in recent:
            source = source_labels.get(e.get("source", ""), e.get("source", "?"))
            name = e.get("name", e.get("entity_id", "?"))
            lines.append(
                f"- {e.get('time_str', '?')}: {name} "
                f"{e.get('old', '?')} → {e.get('new', '?')} "
                f"(Quelle: {source})"
            )

        return (
            "\n\nLETZTE GERAETE-AENDERUNGEN:\n"
            + "\n".join(lines)
            + "\nNutze diese Info um zu erklaeren warum Geraete ihren "
            "Zustand geaendert haben, wenn der User danach fragt."
        )

    @staticmethod
    def format_automations_for_prompt(automation_states: list[dict]) -> str:
        """Formatiert HA-Automationen als LLM-Kontext.

        Gibt dem LLM Wissen darueber welche Automationen existieren und
        kuerzlich ausgeloest wurden, damit es erklaeren kann warum
        Geraete ihren Zustand geaendert haben.

        Args:
            automation_states: Liste von HA-State-Dicts fuer automation.*

        Returns:
            Prompt-Sektion oder leerer String.
        """
        if not automation_states:
            return ""

        lines = []
        recently_triggered = []
        now = time.time()

        for auto in automation_states:
            entity_id = auto.get("entity_id", "")
            if not entity_id.startswith("automation."):
                continue

            attrs = auto.get("attributes", {})
            friendly = attrs.get("friendly_name", entity_id)
            state = auto.get("state", "off")
            last_triggered = attrs.get("last_triggered", "")

            # Kuerzlich ausgeloest? (letzte 30 Min)
            is_recent = False
            if last_triggered:
                try:
                    from datetime import datetime, timezone
                    if isinstance(last_triggered, str) and last_triggered:
                        # ISO-Format parsen
                        _lt = last_triggered.replace("Z", "+00:00")
                        _dt = datetime.fromisoformat(_lt)
                        _age = now - _dt.timestamp()
                        if _age < 1800:  # 30 Min
                            is_recent = True
                            recently_triggered.append(
                                f"- {friendly} (vor {int(_age // 60)} Min)"
                            )
                except (ValueError, TypeError, OSError):
                    pass

            if state == "on" and not is_recent:
                lines.append(f"- {friendly} (aktiv)")

        if not lines and not recently_triggered:
            return ""

        parts = []
        if recently_triggered:
            parts.append(
                "Kuerzlich ausgeloeste Automationen:\n"
                + "\n".join(recently_triggered)
            )
        if lines and len(lines) <= 15:
            # Nur anzeigen wenn nicht zu viele (sonst Token-Verschwendung)
            parts.append(
                "Aktive Automationen:\n"
                + "\n".join(lines)
            )

        return (
            "\n\nHA-AUTOMATIONEN:\n"
            + "\n".join(parts)
            + "\nNutze diese Info um zu erklaeren welche Automation "
            "eine Geraete-Aenderung ausgeloest haben koennte."
        )
