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
        "requires_state": {"armed_away", "armed_night"},
    },
    {
        "role": "fridge", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Kuehlschrank offen/warm → Lebensmittel verderben",
        "hint": "Kuehlschrank: Tuer zu lange offen oder Temperatur zu hoch → sofort pruefen",
        "severity": "info",
    },
    {
        "role": "freezer", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Gefrierschrank Tuer offen/Temperatur zu hoch → Lebensmittel tauen",
        "hint": "Gefrierschrank: Tuer offen oder zu warm → Lebensmittel in Gefahr!",
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
        "requires_state": {"armed_away", "armed_night"},
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
        "effect": "Aussentemperatur beeinflusst Bewaesserung: Hitze=mehr, Frost=stoppen",
        "hint": "Hitze → mehr giessen. Frost → Bewaesserung AUS, Rohrbruchgefahr!",
        "severity": "high",
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
    # (outdoor_temp → irrigation: Duplikat entfernt, Frost+Hitze oben zusammengefuehrt)
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

    # (light_level → blinds: Duplikat entfernt, existiert bereits oben)

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

    # #################################################################
    # PARITAETS-REGELN: Curtain = Blinds = Shutter (gleiche Funktion!)
    # Curtain hatte nur 1 Trigger, Blinds 20 — das muss gleich sein
    # #################################################################

    # --- Curtain: alle Trigger die Blinds hat, aber Curtain fehlt ---
    {
        "role": "alarm", "state": "armed_away",
        "affects": "curtain", "same_room": False,
        "effect": "Alarm scharf → Vorhaenge schliessen (Sichtschutz)",
        "hint": "Alarm aktiviert → Vorhaenge zuziehen",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "curtain", "same_room": False,
        "effect": "Alarm ausgeloest → Vorhaenge oeffnen fuer Sichtbarkeit",
        "hint": "ALARM → Vorhaenge oeffnen, Sichtbarkeit fuer Nachbarn",
        "severity": "high",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Im Bett → Vorhaenge zuziehen fuer Dunkelheit",
        "hint": "Schlafenszeit → Vorhaenge zuziehen, Raum abdunkeln",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "curtain", "same_room": True,
        "effect": "Aufgestanden → Vorhaenge oeffnen",
        "hint": "Aufgestanden → Vorhaenge oeffnen, Tageslicht rein",
        "severity": "info",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Raumtemperatur hoch → Vorhaenge gegen Sonneneinstrahlung",
        "hint": "Raum zu warm → Vorhaenge zuziehen gegen Sonne",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "playing",
        "affects": "curtain", "same_room": True,
        "effect": "Medien spielen → Vorhaenge fuer Filmabend",
        "hint": "Film/Medien → Vorhaenge zuziehen fuer Atmosphaere",
        "severity": "info",
    },
    {
        "role": "tv", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "TV an → Vorhaenge gegen Blendung",
        "hint": "TV an → Vorhaenge zuziehen gegen Spiegelungen",
        "severity": "info",
    },
    {
        "role": "projector", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Beamer an → Vorhaenge MUESSEN zu fuer Bild",
        "hint": "Beamer an → Vorhaenge zuziehen, sonst kein gutes Bild",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Gaming → Vorhaenge gegen Blendung",
        "hint": "Gaming → Vorhaenge fuer Blendschutz am Monitor",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "curtain", "same_room": False,
        "effect": "Niemand zuhause → Vorhaenge als Sichtschutz",
        "hint": "Alle weg → Vorhaenge zuziehen als Einbruchschutz",
        "severity": "info",
    },
    {
        "role": "presence", "state": "on",
        "affects": "curtain", "same_room": False,
        "effect": "Ankunft → Vorhaenge oeffnen bei Tageslicht",
        "hint": "Ankunft → Vorhaenge oeffnen wenn Tag",
        "severity": "info",
    },
    {
        "role": "light_level", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Hohe Helligkeit → Vorhaenge als Blendschutz",
        "hint": "Starkes Licht → Vorhaenge zuziehen fuer Blendschutz",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "curtain", "same_room": False,
        "effect": "Szene aktiviert → Vorhaenge werden angepasst",
        "hint": "Szene → Vorhaenge anpassen",
        "severity": "info",
    },
    {
        "role": "uv_index", "state": "on",
        "affects": "curtain", "same_room": False,
        "effect": "Hoher UV-Index → Vorhaenge fuer Moebel-/Bodenschutz",
        "hint": "UV-Index hoch → Vorhaenge zuziehen, Moebel/Boeden schuetzen",
        "severity": "info",
    },
    {
        "role": "solar_radiation", "state": "on",
        "affects": "curtain", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Vorhaenge zuziehen",
        "hint": "Starke Sonne → Vorhaenge gegen Aufheizung und Blendung",
        "severity": "info",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "curtain", "same_room": False,
        "effect": "Rauch → Vorhaenge oeffnen fuer Fluchtweg-Sicht",
        "hint": "RAUCH → Vorhaenge oeffnen, Fluchtweg sichtbar machen",
        "severity": "critical",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "curtain", "same_room": False,
        "effect": "Aussentemperatur hoch → Vorhaenge gegen Waerme",
        "hint": "Hitze draussen → Vorhaenge zuziehen gegen Aufheizung",
        "severity": "info",
    },
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Am Schreibtisch → Vorhaenge als Blendschutz",
        "hint": "Am Schreibtisch → Vorhaenge fuer Monitor-Blendschutz",
        "severity": "info",
    },

    # #################################################################
    # PARITAETS-REGELN: floor_heating / radiator = heating
    # Diese werden wie eigenstaendige Heizungen behandelt
    # #################################################################

    # --- floor_heating: muss gleiche Affected-Regeln haben wie heating ---
    {
        "role": "presence", "state": "off",
        "affects": "floor_heating", "same_room": False,
        "effect": "Niemand zuhause → Fussbodenheizung auf Absenkung",
        "hint": "Alle weg → Fussbodenheizung auf Absenktemperatur",
        "severity": "info",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "floor_heating", "same_room": True,
        "effect": "Raumtemperatur → Fussbodenheizung anpassen",
        "hint": "Raumtemperatur → Fussbodenheizung hoch/runterregeln",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "floor_heating", "same_room": True,
        "effect": "Im Bett → Fussbodenheizung auf Nacht-Temperatur",
        "hint": "Schlafenszeit → Fussbodenheizung auf Nacht-Modus",
        "severity": "info",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "floor_heating", "same_room": False,
        "effect": "Rauch → Fussbodenheizung aus",
        "hint": "Rauch → Fussbodenheizung AUS",
        "severity": "critical",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "floor_heating", "same_room": True,
        "effect": "Wasserleck → Fussbodenheizung als Quelle pruefen",
        "hint": "Wasserleck → Fussbodenheizung koennte undicht sein",
        "severity": "high",
    },

    # --- radiator: gleiche Affected-Regeln ---
    {
        "role": "presence", "state": "off",
        "affects": "radiator", "same_room": False,
        "effect": "Niemand zuhause → Heizkoerper auf Absenkung",
        "hint": "Alle weg → Heizkoerper auf Absenktemperatur",
        "severity": "info",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "radiator", "same_room": True,
        "effect": "Raumtemperatur → Heizkoerper anpassen",
        "hint": "Raumtemperatur → Heizkoerper-Ventil anpassen",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "radiator", "same_room": True,
        "effect": "Im Bett → Heizkoerper auf Nacht-Temperatur",
        "hint": "Schlafenszeit → Heizkoerper auf Nacht-Modus",
        "severity": "info",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "radiator", "same_room": True,
        "effect": "Wasserleck → Heizkoerper als Quelle pruefen",
        "hint": "Wasserleck → Heizkoerper koennte undicht sein",
        "severity": "high",
    },

    # #################################################################
    # DIMMER / COLOR_LIGHT — als Affected (bisher 0!)
    # #################################################################

    {
        "role": "media_player", "state": "playing",
        "affects": "dimmer", "same_room": True,
        "effect": "Medien spielen → Licht dimmen fuer Atmosphaere",
        "hint": "Film/Medien → Licht dimmen",
        "severity": "info",
    },
    {
        "role": "tv", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "TV an → Licht dimmen",
        "hint": "TV an → Dimmer runter fuer besseres Bild",
        "severity": "info",
    },
    {
        "role": "projector", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "Beamer an → Licht dimmen oder aus",
        "hint": "Beamer → Dimmer ganz runter fuer optimales Bild",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "Im Bett → Licht dimmen fuer Schlaf",
        "hint": "Schlafenszeit → Dimmer langsam auf 0",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "dimmer", "same_room": True,
        "effect": "Aufgestanden → Licht langsam heller",
        "hint": "Aufgestanden → Dimmer langsam hoch (Sonnenaufgangs-Simulation)",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "dimmer", "same_room": False,
        "effect": "Szene aktiviert → Dimmer-Level anpassen",
        "hint": "Szene → Dimmer auf Szenen-Level",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "dimmer", "same_room": False,
        "effect": "Alarm → alle Lichter auf Maximum",
        "hint": "ALARM → Dimmer auf Maximum, volle Helligkeit",
        "severity": "high",
    },
    {
        "role": "presence", "state": "off",
        "affects": "dimmer", "same_room": False,
        "effect": "Niemand zuhause → Dimmer aus",
        "hint": "Alle weg → alle Dimmer ausschalten",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "dimmer", "same_room": True,
        "effect": "Raum leer → Dimmer ausschalten",
        "hint": "Niemand im Raum → Dimmer aus",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "Raum belegt → Dimmer einschalten",
        "hint": "Raum wird genutzt → Dimmer auf angenehmes Level",
        "severity": "info",
    },
    {
        "role": "motion", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "Bewegung → Dimmer einschalten",
        "hint": "Bewegung im Raum → Dimmer an",
        "severity": "info",
    },

    # --- color_light ---
    {
        "role": "scene", "state": "on",
        "affects": "color_light", "same_room": False,
        "effect": "Szene aktiviert → Farblicht anpassen",
        "hint": "Szene → Farblicht auf Szenen-Farbe/Helligkeit",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "color_light", "same_room": False,
        "effect": "Alarm → Farblicht rot als Warnung",
        "hint": "ALARM → Farblicht auf ROT, visuelle Warnung",
        "severity": "high",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "color_light", "same_room": True,
        "effect": "Im Bett → Farblicht warm/dunkel oder aus",
        "hint": "Schlafenszeit → Farblicht warm/gedimmt oder aus",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "playing",
        "affects": "color_light", "same_room": True,
        "effect": "Medien → Farblicht als Ambilight/Stimmung",
        "hint": "Film/Medien → Farblicht als Ambilight passend zum Inhalt",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "color_light", "same_room": False,
        "effect": "Niemand zuhause → Farblicht aus",
        "hint": "Alle weg → Farblicht ausschalten",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "color_light", "same_room": True,
        "effect": "Raum leer → Farblicht aus",
        "hint": "Niemand im Raum → Farblicht aus",
        "severity": "info",
    },
    {
        "role": "motion", "state": "on",
        "affects": "color_light", "same_room": True,
        "effect": "Bewegung → Farblicht einschalten",
        "hint": "Bewegung im Raum → Farblicht an",
        "severity": "info",
    },

    # #################################################################
    # GARDEN_LIGHT — erweiterte Trigger (bisher nur 3)
    # #################################################################

    {
        "role": "motion", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Bewegung draussen → Gartenbeleuchtung einschalten",
        "hint": "Bewegung im Garten → Gartenbeleuchtung an (Sicherheit)",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "garden_light", "same_room": False,
        "effect": "Alarm → Gartenbeleuchtung an fuer Abschreckung",
        "hint": "ALARM → Gartenbeleuchtung an, Einbrecher abschrecken",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "armed_away",
        "affects": "garden_light", "same_room": False,
        "effect": "Alarm scharf → Gartenbeleuchtung als Anwesenheits-Simulation",
        "hint": "Alarm scharf → Gartenbeleuchtung zeitgesteuert als Simulation",
        "severity": "info",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Klingel → Eingangsbeleuchtung einschalten",
        "hint": "Klingel → Aussenbeleuchtung an fuer Besucher",
        "severity": "info",
    },
    {
        "role": "light_level", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Lichtsensor dunkel → Gartenbeleuchtung an",
        "hint": "Daemmerung → Gartenbeleuchtung einschalten",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Schlafenszeit → Gartenbeleuchtung aus (Energiesparen)",
        "hint": "Alle schlafen → Gartenbeleuchtung aus",
        "severity": "info",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Sabotage → Gartenbeleuchtung an fuer Abschreckung",
        "hint": "Sabotage → Gartenbeleuchtung an, Einbrecher abschrecken",
        "severity": "high",
    },

    # #################################################################
    # PROJECTOR — als Affected (bisher 0)
    # #################################################################

    {
        "role": "light_level", "state": "on",
        "affects": "projector", "same_room": True,
        "effect": "Hohe Helligkeit im Raum → Beamer-Bild schlecht",
        "hint": "Zu hell fuer Beamer → Beschattung schliessen",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "projector", "same_room": False,
        "effect": "Niemand zuhause → Beamer ausschalten",
        "hint": "Alle weg → Beamer ausschalten",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "projector", "same_room": False,
        "effect": "Schlafenszeit → Beamer aus",
        "hint": "Schlafenszeit → Beamer ausschalten",
        "severity": "info",
    },

    # #################################################################
    # FEHLENDE GERAETE-INTERAKTIONEN
    # #################################################################

    # Doorbell → TV (Kamerabild auf TV anzeigen)
    {
        "role": "doorbell", "state": "on",
        "affects": "tv", "same_room": False,
        "effect": "Klingel → Kamerabild auf TV anzeigen",
        "hint": "Klingel → Tuerkamera-Bild auf dem Fernseher anzeigen",
        "severity": "info",
    },

    # Doorbell → Intercom (Gegensprechanlage aktivieren)
    {
        "role": "doorbell", "state": "on",
        "affects": "intercom", "same_room": False,
        "effect": "Klingel → Gegensprechanlage aktivieren",
        "hint": "Klingel → Gegensprechanlage oeffnen, mit Besucher sprechen",
        "severity": "info",
    },

    # Intercom → Media Player (Medien pausieren waehrend Gespraech)
    {
        "role": "intercom", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Gegensprechanlage aktiv → Medien pausieren",
        "hint": "Gegensprechanlage → Medien leiser/pausieren",
        "severity": "info",
    },

    # Oven → Ventilation (Dunstabzug einschalten beim Kochen!)
    {
        "role": "oven", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Herd/Ofen an → Dunstabzug/Lueftung einschalten",
        "hint": "Kochen → Dunstabzug einschalten fuer Daempfe/Geruche",
        "severity": "info",
    },
    # Oven → Fenster (Lueften nach dem Kochen)
    {
        "role": "oven", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Herd an → nach dem Kochen lueften",
        "hint": "Kochen → Fenster fuer Lueftung nach dem Kochen",
        "severity": "info",
    },

    # Dryer → Humidity (Trockner erhoet Luftfeuchtigkeit im Raum)
    {
        "role": "dryer", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Trockner laeuft → Luftfeuchtigkeit im Raum steigt",
        "hint": "Trockner → Luftfeuchtigkeit steigt, ggf. lueften",
        "severity": "info",
    },
    # Dryer → Climate (Trockner erzeugt Waerme)
    {
        "role": "dryer", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Trockner erzeugt Waerme und Feuchtigkeit",
        "hint": "Trockner → Raum wird waermer und feuchter",
        "severity": "info",
    },
    # Dryer → Noise (Trockner ist laut)
    {
        "role": "dryer", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Trockner laeuft → Laerm",
        "hint": "Trockner → lautes Geraeusch im Raum",
        "severity": "info",
    },

    # Washing Machine → Noise
    {
        "role": "washing_machine", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Waschmaschine laeuft → Laerm (besonders Schleudern)",
        "hint": "Waschmaschine → Laerm, besonders beim Schleudern",
        "severity": "info",
    },

    # Dishwasher → Humidity
    {
        "role": "dishwasher", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Spuelmaschine → Dampf erhoet Luftfeuchtigkeit",
        "hint": "Spuelmaschine → Dampf, Luftfeuchtigkeit steigt",
        "severity": "info",
    },
    # Dishwasher → Noise
    {
        "role": "dishwasher", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Spuelmaschine laeuft → Geraeusch",
        "hint": "Spuelmaschine → Geraeusch im Raum",
        "severity": "info",
    },

    # Vacuum → Noise (Sauger ist LAUT)
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "noise", "same_room": True,
        "effect": "Staubsauger saugt → starker Laerm",
        "hint": "Staubsauger → laut, Meeting/Telefonat stoert",
        "severity": "info",
    },
    # Vacuum → Bed Occupancy (nicht saugen wenn jemand schlaeft)
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "bed_occupancy", "same_room": False,
        "effect": "Staubsauger + jemand schlaeft → stoerend",
        "hint": "Staubsauger → stoert Schlafende, erst nach dem Aufstehen",
        "severity": "info",
    },

    # Heat Pump → Noise (Waermepumpe kann laut sein - Nachbarn!)
    {
        "role": "heat_pump", "state": "heat",
        "affects": "noise", "same_room": False,
        "effect": "Waermepumpe laeuft → Aussengeraet-Laerm",
        "hint": "Waermepumpe → Aussengeraet laut, nachts Nachbarschaft-Ruhe beachten",
        "severity": "info",
    },

    # Air Purifier → Noise (Luftreiniger kann laut sein)
    {
        "role": "air_purifier", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Luftreiniger laeuft → Geraeusch im Raum",
        "hint": "Luftreiniger → Geraeusch, nachts auf Silent-Modus",
        "severity": "info",
    },
    # Air Purifier → Bed (nachts leise)
    {
        "role": "air_purifier", "state": "on",
        "affects": "bed_occupancy", "same_room": True,
        "effect": "Luftreiniger + Schlafen → Silent-Modus",
        "hint": "Schlafenszeit → Luftreiniger auf Silent-Modus",
        "severity": "info",
    },

    # Fan → Noise (Ventilator erzeugt Geraeusch)
    {
        "role": "fan", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Ventilator laeuft → Geraeusch",
        "hint": "Ventilator → Geraeusch im Raum",
        "severity": "info",
    },
    # Fan → Bed (nachts leise)
    {
        "role": "fan", "state": "on",
        "affects": "bed_occupancy", "same_room": True,
        "effect": "Ventilator + Schlafen → leise Stufe",
        "hint": "Schlafenszeit → Ventilator auf niedrigste Stufe",
        "severity": "info",
    },

    # Router offline → NAS nicht erreichbar
    {
        "role": "router", "state": "off",
        "affects": "nas", "same_room": False,
        "effect": "Router offline → NAS ueber Netzwerk nicht erreichbar",
        "hint": "Router down → NAS nicht erreichbar, Backups unterbrochen",
        "severity": "high",
    },

    # Awning → Presence (bei Abwesenheit einfahren)
    {
        "role": "presence", "state": "off",
        "affects": "awning", "same_room": False,
        "effect": "Niemand zuhause → Markise einfahren (Wetter-Risiko)",
        "hint": "Alle weg → Markise einfahren, Sturmschaden verhindern",
        "severity": "info",
    },

    # PC → Fan (PC erzeugt Waerme → Ventilator hilft)
    {
        "role": "pc", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "PC laeuft → Waermeentwicklung, Ventilator sinnvoll",
        "hint": "PC an → Raum wird waermer, Ventilator einschalten",
        "severity": "info",
    },
    # PC → Noise
    {
        "role": "pc", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "PC laeuft → Luefter-Geraeusch",
        "hint": "PC → Luefter-Geraeusch im Raum",
        "severity": "info",
    },

    # Server → Climate (Serverraum braucht Kuehlung!)
    {
        "role": "server", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Server laeuft → erzeugt Waerme, Kuehlung noetig",
        "hint": "Server an → Raum-Kuehlung sicherstellen",
        "severity": "info",
    },

    # NAS → Energy
    {
        "role": "nas", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "NAS laeuft → Stromverbrauch",
        "hint": "NAS an → Dauerstromverbraucher",
        "severity": "info",
    },

    # Irrigation → Energy (Pumpe braucht Strom)
    {
        "role": "irrigation", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Bewaesserung → Pumpe verbraucht Strom",
        "hint": "Bewaesserung → Strom fuer Pumpe/Ventile",
        "severity": "info",
    },

    # Doorbell → Lock (Tuer oeffnen fuer erwarteten Besucher)
    {
        "role": "doorbell", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Klingel → Tuer ggf. oeffnen fuer Besucher",
        "hint": "Klingel → Tuer fuer erwarteten Besucher entriegeln",
        "severity": "info",
    },

    # Smoke → PC/Server herunterfahren (Datenverlust verhindern)
    {
        "role": "smoke", "state": "on",
        "affects": "pc", "same_room": False,
        "effect": "Rauch → PC herunterfahren, Datenverlust minimieren",
        "hint": "RAUCH → PC/Server sicher herunterfahren",
        "severity": "high",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "server", "same_room": False,
        "effect": "Rauch → Server herunterfahren, Datenverlust verhindern",
        "hint": "RAUCH → Server sicher herunterfahren, Backups schuetzen",
        "severity": "high",
    },

    # Water Leak → Fussbodenheizung (erhoehtes Risiko bei Leck)
    {
        "role": "water_leak", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Wasserleck → Bewaesserung stoppen als Vorsicht",
        "hint": "Wasserleck → Bewaesserung sofort stoppen, koennte Quelle sein",
        "severity": "high",
    },

    # Boiler → Climate (Warmwasser-Bereitung erzeugt Abwaerme)
    {
        "role": "boiler", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Boiler heizt → Waerme-Abstrahlung in den Raum",
        "hint": "Boiler → erzeugt Abwaerme im Heizungsraum",
        "severity": "info",
    },

    # Coffee Machine → Energy
    {
        "role": "coffee_machine", "state": "on",
        "affects": "water_consumption", "same_room": False,
        "effect": "Kaffeemaschine verbraucht Wasser",
        "hint": "Kaffeemaschine → Wasserverbrauch beachten, Tank nachfuellen",
        "severity": "info",
    },

    # Siren → Media Player (Medien stoppen bei Alarm)
    {
        "role": "siren", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Sirene heult → Medien sofort stoppen",
        "hint": "Sirene → Medien stoppen, Sirene muss gehoert werden",
        "severity": "high",
    },

    # Siren → Speaker (Lautsprecher-Durchsage)
    {
        "role": "siren", "state": "on",
        "affects": "speaker", "same_room": False,
        "effect": "Sirene → Lautsprecher fuer Evakuierungs-Durchsage",
        "hint": "Sirene → Lautsprecher fuer Warn-Durchsage nutzen",
        "severity": "high",
    },

    # Alarm armed → vacuum stoppen (Bewegungsmelder Fehlalarm!)
    {
        "role": "alarm", "state": "armed_away",
        "affects": "vacuum", "same_room": False,
        "effect": "Alarm scharf → Staubsauger stoppen (loest Bewegungsmelder aus!)",
        "hint": "Alarm scharf → Saugroboter stoppen, loest sonst Alarm aus",
        "severity": "high",
    },
    {
        "role": "alarm", "state": "armed_night",
        "affects": "vacuum", "same_room": False,
        "effect": "Nacht-Alarm → Staubsauger stoppen",
        "hint": "Nacht-Alarm → Saugroboter stoppen, loest sonst Alarm aus",
        "severity": "high",
    },

    # Presence off → Receiver aus
    {
        "role": "presence", "state": "off",
        "affects": "receiver", "same_room": False,
        "effect": "Niemand zuhause → AV-Receiver ausschalten",
        "hint": "Alle weg → Receiver ausschalten (Standby-Verbrauch)",
        "severity": "info",
    },
    # Presence off → Gaming aus
    {
        "role": "presence", "state": "off",
        "affects": "gaming", "same_room": False,
        "effect": "Niemand zuhause → Spielkonsole aus",
        "hint": "Alle weg → Gaming-Konsole/PC ausschalten",
        "severity": "info",
    },
    # (presence off → projector: Duplikat entfernt, existiert oben)
    # Presence off → Speaker aus
    {
        "role": "presence", "state": "off",
        "affects": "speaker", "same_room": False,
        "effect": "Niemand zuhause → Lautsprecher ausschalten",
        "hint": "Alle weg → Lautsprecher aus",
        "severity": "info",
    },
    # Presence off → Air Purifier (Eco oder aus)
    {
        "role": "presence", "state": "off",
        "affects": "air_purifier", "same_room": False,
        "effect": "Niemand zuhause → Luftreiniger auf Eco/Aus",
        "hint": "Alle weg → Luftreiniger auf Eco oder aus",
        "severity": "info",
    },
    # Presence off → Dehumidifier
    {
        "role": "presence", "state": "off",
        "affects": "dehumidifier", "same_room": False,
        "effect": "Niemand zuhause → Entfeuchter weiter laufen lassen (Schimmel!)",
        "hint": "Alle weg → Entfeuchter NICHT ausschalten, Schimmelschutz!",
        "severity": "info",
    },
    # Presence off → Humidifier aus
    {
        "role": "presence", "state": "off",
        "affects": "humidifier", "same_room": False,
        "effect": "Niemand zuhause → Befeuchter aus",
        "hint": "Alle weg → Befeuchter ausschalten",
        "severity": "info",
    },
    # Presence off → Boiler (Warmwasser reduzieren)
    {
        "role": "presence", "state": "off",
        "affects": "boiler", "same_room": False,
        "effect": "Niemand zuhause → Warmwasser-Temperatur absenken",
        "hint": "Alle weg → Boiler auf Absenkung, spart Energie",
        "severity": "info",
    },

    # Occupancy off → erweitert
    {
        "role": "occupancy", "state": "off",
        "affects": "outlet", "same_room": True,
        "effect": "Raum leer → Standby-Steckdosen aus",
        "hint": "Niemand im Raum → Standby-Steckdosen abschalten",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "Raum leer → Beschattung neutral stellen",
        "hint": "Niemand im Raum → Beschattung auf Energieoptimierung",
        "severity": "info",
    },
    {
        "role": "occupancy", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Raum belegt → Beschattung fuer Komfort",
        "hint": "Raum wird genutzt → Beschattung fuer Blendschutz/Komfort",
        "severity": "info",
    },

    # Licht-Level (Daemmerung) → Gartenbeleuchtung, Aussenbeleuchtung
    {
        "role": "light_level", "state": "on",
        "affects": "shutter", "same_room": True,
        "effect": "Lichtverhaeltnisse aendern sich → Rollladen anpassen",
        "hint": "Lichtsensor → Rollladen nach Tageslicht anpassen",
        "severity": "info",
    },

    # Solar Radiation → Cooling (Sonne heizt auf → Kuehlung noetig)
    {
        "role": "solar_radiation", "state": "on",
        "affects": "cooling", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Kuehlung noetig",
        "hint": "Starke Sonne → Raeume heizen sich auf, Kuehlung starten",
        "severity": "info",
    },
    {
        "role": "solar_radiation", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Klima-Anpassung",
        "hint": "Starke Sonne → Klimaanlage gegensteuern",
        "severity": "info",
    },

    # Outdoor Temp → Thermostat (Aussentemperatur beeinflusst Heiz-Bedarf)
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "thermostat", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Heiz-/Kuehlbedarf",
        "hint": "Aussentemperatur → Thermostat-Soll anpassen",
        "severity": "info",
    },
    # Outdoor Temp → Heat Pump (Effizienz abhaengig von Aussentemp)
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Waermepumpen-Effizienz",
        "hint": "Aussentemperatur → Waermepumpen-Leistung anpassen",
        "severity": "info",
    },
    # Outdoor Temp → Window (Lueften nur sinnvoll wenn draussen kuehler/waermer)
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Aussentemperatur → Lueften sinnvoll oder nicht",
        "hint": "Aussentemperatur → Lueften nur wenn draussen angenehmer als drinnen",
        "severity": "info",
    },
    # Outdoor Temp → Ventilation
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Lueftungs-Strategie",
        "hint": "Aussentemperatur → Lueftung: Bypass wenn draussen kuehler",
        "severity": "info",
    },
    # Outdoor Temp → Garden Light (Frost → Wegbeleuchtung wegen Glaette)
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Frost → Gartenbeleuchtung fuer Sicherheit auf Wegen",
        "hint": "Frost → Gartenbeleuchtung an fuer Glaette-Erkennung",
        "severity": "info",
    },

    # Humidity → Ventilation (hohe Luftfeuchtigkeit → belueften)
    {
        "role": "humidity", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Hohe Luftfeuchtigkeit → Lueftung fuer Abtransport",
        "hint": "Luftfeuchtigkeit hoch → Lueftung einschalten",
        "severity": "info",
    },

    # CO2 → Notify (CO2 zu hoch → warnen)
    {
        "role": "co2", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "CO2-Wert hoch → Bewohner informieren",
        "hint": "CO2 zu hoch → Lueften empfohlen, Konzentration sinkt",
        "severity": "info",
    },

    # VOC → Window (fluechtige Stoffe → lueften)
    {
        "role": "voc", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "VOC hoch → Lueften noetig",
        "hint": "VOC/fluechtige Stoffe hoch → Fenster oeffnen, lueften",
        "severity": "high",
    },
    {
        "role": "voc", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "VOC hoch → Bewohner warnen",
        "hint": "VOC zu hoch → Lueften empfohlen",
        "severity": "info",
    },

    # Radon → Notify
    {
        "role": "radon", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Radon-Wert hoch → Gesundheitswarnung",
        "hint": "Radon zu hoch → Lueften, laenger nicht im Keller aufhalten",
        "severity": "high",
    },
    {
        "role": "radon", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Radon hoch → Fenster oeffnen",
        "hint": "Radon → Kellerfenster oeffnen zum Lueften",
        "severity": "high",
    },

    # PM2.5 / PM10 → Notify, Ventilation, Air Purifier
    {
        "role": "pm25", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Feinstaub PM2.5 hoch → Gesundheitswarnung",
        "hint": "Feinstaub hoch → Fenster schliessen, Luftreiniger an",
        "severity": "info",
    },
    {
        "role": "pm25", "state": "on",
        "affects": "air_purifier", "same_room": True,
        "effect": "Feinstaub PM2.5 hoch → Luftreiniger einschalten",
        "hint": "Feinstaub → Luftreiniger auf hohe Stufe",
        "severity": "info",
    },
    {
        "role": "pm10", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Feinstaub PM10 hoch → Warnung",
        "hint": "Feinstaub PM10 hoch → Fenster zu, Luftreiniger an",
        "severity": "info",
    },
    {
        "role": "pm10", "state": "on",
        "affects": "air_purifier", "same_room": True,
        "effect": "Feinstaub PM10 hoch → Luftreiniger einschalten",
        "hint": "Feinstaub → Luftreiniger einschalten",
        "severity": "info",
    },
    {
        "role": "air_quality", "state": "on",
        "affects": "air_purifier", "same_room": True,
        "effect": "Luftqualitaet schlecht → Luftreiniger einschalten",
        "hint": "Schlechte Luft → Luftreiniger auf hohe Stufe",
        "severity": "info",
    },
    {
        "role": "air_quality", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Luftqualitaet schlecht → Lueftung anpassen",
        "hint": "Schlechte Luft → Lueftung auf Frischluft-Modus",
        "severity": "info",
    },
    {
        "role": "air_quality", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Luftqualitaet schlecht → Bewohner informieren",
        "hint": "Luftqualitaet schlecht → Lueften oder Luftreiniger",
        "severity": "info",
    },

    # Pressure → Climate (Luftdruckabfall = Wetterumschwung)
    {
        "role": "pressure", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Luftdruck-Aenderung → Wetterumschwung, Klima anpassen",
        "hint": "Luftdruck faellt → Wetter wird schlechter, vorsorglich handeln",
        "severity": "info",
    },
    {
        "role": "pressure", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Starker Luftdruckabfall → Sturm moeglich, Fenster schliessen",
        "hint": "Luftdruck faellt stark → Sturm moeglich, Fenster sichern",
        "severity": "info",
    },

    # #################################################################
    # LETZTE LUECKEN — systematisch geschlossen
    # #################################################################

    # === indoor_temp: wird von VIELEN Geraeten beeinflusst ===
    # (bisher nur fridge!)
    {
        "role": "heating", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Heizung an → Raumtemperatur steigt",
        "hint": "Heizung laeuft → Raumtemperatur steigt",
        "severity": "info",
    },
    {
        "role": "cooling", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Kuehlung an → Raumtemperatur sinkt",
        "hint": "Kuehlung laeuft → Raumtemperatur sinkt",
        "severity": "info",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Fussbodenheizung heizt → Raumtemperatur steigt",
        "hint": "Fussbodenheizung → Raumtemperatur steigt (langsam, traege)",
        "severity": "info",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Heizkoerper heizt → Raumtemperatur steigt",
        "hint": "Heizkoerper → Raumtemperatur steigt",
        "severity": "info",
    },
    {
        "role": "thermostat", "state": "heat",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Thermostat heizt → Raumtemperatur steigt zum Soll",
        "hint": "Thermostat heizt → Temperatur steigt Richtung Soll-Wert",
        "severity": "info",
    },
    {
        "role": "thermostat", "state": "cool",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Thermostat kuehlt → Raumtemperatur sinkt zum Soll",
        "hint": "Thermostat kuehlt → Temperatur sinkt Richtung Soll-Wert",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Fenster offen → Aussenluft beeinflusst Raumtemperatur",
        "hint": "Fenster offen → Raumtemperatur naehert sich Aussentemperatur",
        "severity": "info",
    },
    {
        "role": "oven", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Herd/Ofen an → Kueche wird waermer",
        "hint": "Kochen → Kueche heizt sich auf",
        "severity": "info",
    },
    {
        "role": "pc", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "PC laeuft → Abwaerme erhoet Raumtemperatur",
        "hint": "PC → Raum wird waermer durch Abwaerme",
        "severity": "info",
    },
    {
        "role": "server", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Server → starke Waerme-Entwicklung im Raum",
        "hint": "Server → Raum heizt sich auf, Kuehlung sicherstellen",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Trockner → Abwaerme erhoet Raumtemperatur",
        "hint": "Trockner → Raum wird waermer",
        "severity": "info",
    },
    {
        "role": "solar_radiation", "state": "on",
        "affects": "indoor_temp", "same_room": False,
        "effect": "Sonneneinstrahlung → Raeume heizen sich auf",
        "hint": "Starke Sonne → Raeume werden waermer (Suedseite besonders)",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "indoor_temp", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Innentemperatur",
        "hint": "Aussentemperatur → wirkt auf Innentemperatur (besonders bei schlechter Daemmung)",
        "severity": "info",
    },
    {
        "role": "blinds", "state": "open",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Jalousien offen → Sonneneinstrahlung heizt Raum auf",
        "hint": "Jalousien offen bei Sonne → Raum heizt sich auf",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "open",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Rollladen offen → Sonne kann Raum aufheizen",
        "hint": "Rollladen offen → Sonneneinstrahlung heizt Raum auf",
        "severity": "info",
    },

    # === soil_moisture: Regen beeinflusst Bodenfeuchtigkeit! ===
    {
        "role": "rain", "state": "on",
        "affects": "soil_moisture", "same_room": False,
        "effect": "Regen → Bodenfeuchtigkeit steigt natuerlich",
        "hint": "Regen → Boden wird feucht, Bewaesserung unnoetig",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "soil_moisture", "same_room": False,
        "effect": "Hitze → Boden trocknet schneller aus",
        "hint": "Hitze → Boden trocknet aus, oefter bewaessern",
        "severity": "info",
    },
    {
        "role": "wind_speed", "state": "on",
        "affects": "soil_moisture", "same_room": False,
        "effect": "Wind → Boden trocknet schneller",
        "hint": "Wind → Verdunstung steigt, Boden trocknet",
        "severity": "info",
    },

    # === grid_consumption: wird von Grossverbrauchern beeinflusst ===
    {
        "role": "heat_pump", "state": "heat",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Waermepumpe laeuft → Netzbezug steigt",
        "hint": "Waermepumpe → hoher Netzbezug (2-5 kW)",
        "severity": "info",
    },
    {
        "role": "oven", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Herd/Ofen an → Netzbezug steigt stark",
        "hint": "Herd/Ofen → hoher Netzbezug (2-4 kW)",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Trockner laeuft → Netzbezug steigt",
        "hint": "Trockner → hoher Netzbezug (2-3 kW)",
        "severity": "info",
    },
    {
        "role": "washing_machine", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Waschmaschine laeuft → Netzbezug steigt",
        "hint": "Waschmaschine → Netzbezug (0.5-2 kW)",
        "severity": "info",
    },
    {
        "role": "dishwasher", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Spuelmaschine laeuft → Netzbezug steigt",
        "hint": "Spuelmaschine → Netzbezug (1-2 kW)",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Boiler heizt → Netzbezug steigt",
        "hint": "Boiler → hoher Netzbezug wenn elektrisch (2-6 kW)",
        "severity": "info",
    },
    {
        "role": "solar", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Solar erzeugt → Netzbezug sinkt/wird negativ",
        "hint": "Solar → Netzbezug sinkt, Eigenverbrauch steigt",
        "severity": "info",
    },

    # === air_quality: wird von vielen Quellen beeinflusst ===
    {
        "role": "oven", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Kochen → Luftqualitaet sinkt (Daempfe, Fett, Gerueche)",
        "hint": "Kochen → Luftqualitaet sinkt, Dunstabzug/Lueften noetig",
        "severity": "info",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Rauch → Luftqualitaet drastisch verschlechtert",
        "hint": "Rauch → Luftqualitaet katastrophal",
        "severity": "high",
    },
    {
        "role": "co", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "CO → Luftqualitaet lebensgefaehrlich",
        "hint": "CO → Luftqualitaet lebensgefaehrlich!",
        "severity": "critical",
    },
    {
        "role": "voc", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "VOC hoch → Luftqualitaet verschlechtert",
        "hint": "VOC → Luftqualitaet sinkt (Farben, Klebstoffe, Reiniger)",
        "severity": "info",
    },
    {
        "role": "ventilation", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Lueftung an → Luftqualitaet verbessert sich",
        "hint": "Lueftung → Luftqualitaet steigt durch Frischluft",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Luftreiniger an → Luftqualitaet verbessert sich",
        "hint": "Luftreiniger → Luftqualitaet steigt (Feinstaub, Pollen)",
        "severity": "info",
    },

    # === smoke: kann von mehreren Quellen ausgeloest werden ===
    {
        "role": "dryer", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "Trockner laeuft → Flusen koennen Rauch ausloesen",
        "hint": "Trockner + Rauch → Flusensieb pruefen, Brandgefahr!",
        "severity": "high",
    },
    {
        "role": "heating", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "Heizung laeuft → bei Defekt Rauch moeglich",
        "hint": "Heizung + Rauch → Heizungsdefekt? Sofort ausschalten",
        "severity": "high",
    },

    # === water_temp: wird von mehreren Quellen beeinflusst ===
    {
        "role": "solar", "state": "on",
        "affects": "water_temp", "same_room": False,
        "effect": "Solarthermie → Wassertemperatur steigt",
        "hint": "Solar → Warmwasser wird durch Sonne aufgeheizt",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "heat",
        "affects": "water_temp", "same_room": False,
        "effect": "Waermepumpe → Wassertemperatur steigt",
        "hint": "Waermepumpe → Warmwasser wird aufbereitet",
        "severity": "info",
    },

    # === gate: braucht mehr Trigger (wie garage_door) ===
    {
        "role": "presence", "state": "off",
        "affects": "gate", "same_room": False,
        "effect": "Niemand zuhause → Tor sollte geschlossen sein",
        "hint": "Alle weg → Tor schliessen",
        "severity": "high",
    },
    {
        "role": "car", "state": "not_home",
        "affects": "gate", "same_room": False,
        "effect": "Auto weg → Tor/Einfahrt schliessen",
        "hint": "Auto weg → Tor schliessen",
        "severity": "info",
    },
    {
        "role": "car", "state": "home",
        "affects": "gate", "same_room": False,
        "effect": "Auto kommt → Tor oeffnen",
        "hint": "Auto naehert sich → Einfahrtstor oeffnen",
        "severity": "info",
    },
    {
        "role": "car_location", "state": "on",
        "affects": "gate", "same_room": False,
        "effect": "Auto naehert sich → Tor oeffnen vorbereiten",
        "hint": "Auto naehert sich → Einfahrtstor oeffnen",
        "severity": "info",
    },
    {
        "role": "zone", "state": "on",
        "affects": "gate", "same_room": False,
        "effect": "Person naehert sich → Tor oeffnen",
        "hint": "Person kommt → Tor/Einfahrt oeffnen",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "gate", "same_room": False,
        "effect": "Schlafenszeit → Tor sollte geschlossen sein",
        "hint": "Alle schlafen → Tor schliessen",
        "severity": "info",
    },

    # === door_contact: mehr Trigger (Sicherheit/Komfort) ===
    {
        "role": "alarm", "state": "triggered",
        "affects": "door_contact", "same_room": False,
        "effect": "Alarm → alle Tueren pruefen",
        "hint": "ALARM → Tuer-Status pruefen, Eindringling?",
        "severity": "high",
    },
    {
        "role": "presence", "state": "off",
        "affects": "door_contact", "same_room": False,
        "effect": "Niemand zuhause → Tueren sollten geschlossen sein",
        "hint": "Alle weg → offene Tueren pruefen",
        "severity": "info",
    },
    {
        "role": "rain", "state": "on",
        "affects": "door_contact", "same_room": False,
        "effect": "Regen → offene Tueren (Terrasse/Balkon) schliessen",
        "hint": "Regen → Terrassen-/Balkontuer schliessen",
        "severity": "info",
    },
    {
        "role": "wind_speed", "state": "on",
        "affects": "door_contact", "same_room": False,
        "effect": "Starker Wind → Tueren koennen zuschlagen",
        "hint": "Sturm → Tueren sichern, Zuschlag-Gefahr",
        "severity": "info",
    },

    # === doorbell: mehr Trigger ===
    {
        "role": "motion", "state": "on",
        "affects": "doorbell", "same_room": True,
        "effect": "Bewegung am Eingang → Person naehert sich",
        "hint": "Bewegung am Eingang → Besucher kommt, Klingel erwartet",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "doorbell", "same_room": False,
        "effect": "Niemand zuhause → Klingel-Benachrichtigung wichtiger",
        "hint": "Alle weg + Klingel → Benachrichtigung besonders wichtig (Paket?)",
        "severity": "info",
    },

    # === server: mehr Trigger ===
    {
        "role": "router", "state": "off",
        "affects": "server", "same_room": False,
        "effect": "Router offline → Server nicht erreichbar",
        "hint": "Router down → Server ueber Netzwerk nicht erreichbar",
        "severity": "high",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "server", "same_room": True,
        "effect": "Wasserleck im Serverraum → Hardware-Gefahr",
        "hint": "Wasserleck + Server → Server-Hardware in Gefahr!",
        "severity": "high",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "server", "same_room": True,
        "effect": "Raumtemperatur hoch + Server → Ueberhitzungsgefahr",
        "hint": "Server-Raum zu warm → Kuehlung pruefen, Ueberhitzung!",
        "severity": "high",
    },

    # === motion: mehr Trigger ===
    {
        "role": "alarm", "state": "armed_away",
        "affects": "motion", "same_room": False,
        "effect": "Alarm scharf → Bewegung = Einbruch!",
        "hint": "Alarm scharf + Bewegung → moeglicherweise Einbruch!",
        "severity": "high",
    },
    {
        "role": "presence", "state": "off",
        "affects": "motion", "same_room": False,
        "effect": "Niemand zuhause + Bewegung → verdaechtig",
        "hint": "Alle weg + Bewegung → verdaechtig, pruefen!",
        "severity": "high",
    },

    # === receiver: mehr Trigger ===
    {
        "role": "alarm", "state": "triggered",
        "affects": "receiver", "same_room": False,
        "effect": "Alarm → Receiver ausschalten",
        "hint": "ALARM → Receiver aus, nicht ablenken lassen",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "receiver", "same_room": False,
        "effect": "Schlafenszeit → Receiver ausschalten",
        "hint": "Schlafenszeit → Receiver ausschalten",
        "severity": "info",
    },

    # === gaming: mehr Trigger ===
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "gaming", "same_room": False,
        "effect": "Schlafenszeit → Gaming beenden",
        "hint": "Schlafenszeit → Konsole/PC ausschalten",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "armed_away",
        "affects": "gaming", "same_room": False,
        "effect": "Alarm scharf → Gaming sollte aus sein",
        "hint": "Alle weg → Gaming-Geraete aus",
        "severity": "info",
    },

    # === oven: mehr Trigger ===
    {
        "role": "timer", "state": "off",
        "affects": "oven", "same_room": False,
        "effect": "Timer abgelaufen → Herd/Ofen pruefen (Essen fertig?)",
        "hint": "Koch-Timer abgelaufen → Herd/Ofen pruefen, Essen fertig!",
        "severity": "info",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "oven", "same_room": True,
        "effect": "Rauch → Herd/Ofen pruefen ob er die Quelle ist",
        "hint": "Rauch + Herd an → Essen angebrannt? Herd ausschalten!",
        "severity": "high",
    },

    # === coffee_machine: mehr Trigger ===
    {
        "role": "timer", "state": "off",
        "affects": "coffee_machine", "same_room": False,
        "effect": "Timer → Kaffeemaschine einschalten",
        "hint": "Kaffee-Timer → Kaffeemaschine starten",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "disarmed",
        "affects": "coffee_machine", "same_room": False,
        "effect": "Alarm deaktiviert (Ankunft) → Kaffeemaschine starten",
        "hint": "Ankunft → Kaffeemaschine aufheizen lassen",
        "severity": "info",
    },

    # === humidifier: mehr Trigger ===
    {
        "role": "humidity", "state": "on",
        "affects": "humidifier", "same_room": True,
        "effect": "Luftfeuchtigkeit niedrig → Befeuchter einschalten",
        "hint": "Luftfeuchtigkeit zu niedrig → Befeuchter einschalten",
        "severity": "info",
    },
    {
        "role": "heating", "state": "on",
        "affects": "humidifier", "same_room": True,
        "effect": "Heizung trocknet Luft → Befeuchter sinnvoll",
        "hint": "Heizung trocknet Luft → Befeuchter einschalten",
        "severity": "info",
    },

    # === scene: als Affected (wird aktiviert durch Trigger) ===
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "scene", "same_room": False,
        "effect": "Im Bett → Gute-Nacht-Szene aktivieren",
        "hint": "Schlafenszeit → Gute-Nacht-Szene starten",
        "severity": "info",
    },
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "scene", "same_room": False,
        "effect": "Aufgestanden → Morgen-Szene aktivieren",
        "hint": "Aufgestanden → Morgen-Szene starten",
        "severity": "info",
    },
    {
        "role": "presence", "state": "on",
        "affects": "scene", "same_room": False,
        "effect": "Ankunft → Willkommens-Szene aktivieren",
        "hint": "Ankunft → Willkommens-Szene starten",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "scene", "same_room": False,
        "effect": "Alle weg → Abwesenheits-Szene aktivieren",
        "hint": "Alle weg → Abwesenheits-Szene (Eco, Sicherheit)",
        "severity": "info",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "scene", "same_room": False,
        "effect": "Alarm → Alarm-Szene aktivieren (alles an, Lockdown)",
        "hint": "ALARM → Alarm-Szene: alle Lichter an, Kameras an, Lockdown",
        "severity": "high",
    },

    # === freezer/fridge: Problem-Erkennung ===
    {
        "role": "problem", "state": "on",
        "affects": "freezer", "same_room": True,
        "effect": "Problem → Gefrierschrank pruefen (Kompressor?)",
        "hint": "Geraete-Problem → Gefrierschrank-Temperatur pruefen!",
        "severity": "high",
    },
    {
        "role": "problem", "state": "on",
        "affects": "fridge", "same_room": True,
        "effect": "Problem → Kuehlschrank pruefen (Kompressor?)",
        "hint": "Geraete-Problem → Kuehlschrank-Temperatur pruefen!",
        "severity": "high",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "freezer", "same_room": True,
        "effect": "Raumtemperatur hoch → Gefrierschrank arbeitet haerter",
        "hint": "Raum zu warm → Gefrierschrank muss mehr kuehlen",
        "severity": "info",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "fridge", "same_room": True,
        "effect": "Raumtemperatur hoch → Kuehlschrank arbeitet haerter",
        "hint": "Raum zu warm → Kuehlschrank muss mehr kuehlen, Energieverbrauch steigt",
        "severity": "info",
    },

    # === pump: mehr Trigger ===
    {
        "role": "irrigation", "state": "on",
        "affects": "pump", "same_room": False,
        "effect": "Bewaesserung → Pumpe laeuft",
        "hint": "Bewaesserung gestartet → Pumpe laeuft",
        "severity": "info",
    },
    {
        "role": "pool", "state": "on",
        "affects": "pump", "same_room": False,
        "effect": "Pool aktiv → Pumpe fuer Umwaelzung/Filterung",
        "hint": "Pool → Pumpe laeuft fuer Wasserumwaelzung",
        "severity": "info",
    },

    # === water_leak: mehr Verursacher ===
    {
        "role": "boiler", "state": "on",
        "affects": "water_leak", "same_room": True,
        "effect": "Boiler aktiv → Leck moeglich (Druckventil, Korrosion)",
        "hint": "Boiler + Wasserleck → Boiler als Quelle pruefen",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "on",
        "affects": "water_leak", "same_room": False,
        "effect": "Bewaesserung laeuft → Leck in Leitung moeglich",
        "hint": "Bewaesserung + Wasserleck → Leitung/Ventil pruefen",
        "severity": "info",
    },
    {
        "role": "pool", "state": "on",
        "affects": "water_leak", "same_room": False,
        "effect": "Pool-System → Leck moeglich",
        "hint": "Pool + Wasserleck → Pool-Leitungen pruefen",
        "severity": "info",
    },

    # === solar: wird von Wetter beeinflusst ===
    {
        "role": "solar_radiation", "state": "on",
        "affects": "solar", "same_room": False,
        "effect": "Sonneneinstrahlung → Solar-Ertrag steigt/faellt",
        "hint": "Sonneneinstrahlung → PV-Ertrag aendert sich",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "solar", "same_room": False,
        "effect": "Aussentemperatur → PV-Effizienz (hoch=schlechter)",
        "hint": "Hitze → PV-Module werden ineffizienter",
        "severity": "info",
    },

    # === light_level: wird von Beschattung beeinflusst ===
    {
        "role": "blinds", "state": "closed",
        "affects": "light_level", "same_room": True,
        "effect": "Jalousien geschlossen → weniger Licht im Raum",
        "hint": "Jalousien zu → Raum wird dunkler, Kunstlicht noetig",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "closed",
        "affects": "light_level", "same_room": True,
        "effect": "Rollladen geschlossen → Raum wird dunkel",
        "hint": "Rollladen zu → kein Tageslicht, Kunstlicht an",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "closed",
        "affects": "light_level", "same_room": True,
        "effect": "Vorhaenge geschlossen → weniger Licht",
        "hint": "Vorhaenge zu → Raum wird dunkler",
        "severity": "info",
    },
    {
        "role": "solar_radiation", "state": "on",
        "affects": "light_level", "same_room": False,
        "effect": "Sonneneinstrahlung → Lichtverhaeltnisse aendern sich",
        "hint": "Sonneneinstrahlung → Raeume werden heller",
        "severity": "info",
    },

    # === outdoor_temp: Kontext-Quellen ===
    {
        "role": "solar_radiation", "state": "on",
        "affects": "outdoor_temp", "same_room": False,
        "effect": "Sonneneinstrahlung → Aussentemperatur steigt",
        "hint": "Starke Sonne → Aussentemperatur steigt",
        "severity": "info",
    },
    {
        "role": "wind_speed", "state": "on",
        "affects": "outdoor_temp", "same_room": False,
        "effect": "Wind → gefuehlte Aussentemperatur sinkt (Windchill)",
        "hint": "Wind → Windchill, fuehlt sich kaelter an",
        "severity": "info",
    },

    # === phone: mehr Trigger (Telefon als Kontext) ===
    {
        "role": "phone", "state": "on",
        "affects": "tv", "same_room": True,
        "effect": "Telefonat → TV leiser fuer Gespraech",
        "hint": "Telefon klingelt → TV leiser stellen",
        "severity": "info",
    },
    {
        "role": "phone", "state": "on",
        "affects": "speaker", "same_room": True,
        "effect": "Telefonat → Lautsprecher leiser",
        "hint": "Telefon klingelt → Lautsprecher leiser",
        "severity": "info",
    },
    {
        "role": "phone", "state": "on",
        "affects": "doorbell", "same_room": False,
        "effect": "Im Telefonat → Klingel-Lautstaerke anpassen",
        "hint": "Im Telefonat → Klingel ggf. stumm schalten",
        "severity": "info",
    },

    # === router: als Affected (Stromausfall, Problem) ===
    {
        "role": "problem", "state": "on",
        "affects": "router", "same_room": True,
        "effect": "Problem → Router pruefen (Netzwerk-Ausfall?)",
        "hint": "Netzwerk-Problem → Router neustarten?",
        "severity": "info",
    },

    # (fridge/freezer → notify: Duplikat entfernt, existiert bereits oben)

    # === NAS als Affected ===
    {
        "role": "problem", "state": "on",
        "affects": "nas", "same_room": True,
        "effect": "Problem → NAS pruefen (Festplatte defekt?)",
        "hint": "NAS-Problem → Festplatten-Status pruefen!",
        "severity": "high",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "nas", "same_room": True,
        "effect": "Wasserleck + NAS → Hardware in Gefahr",
        "hint": "Wasserleck → NAS in Gefahr, Datenverlust!",
        "severity": "high",
    },
    {
        "role": "indoor_temp", "state": "on",
        "affects": "nas", "same_room": True,
        "effect": "Raumtemperatur hoch → NAS Ueberhitzungsgefahr",
        "hint": "Raum zu warm → NAS-Temperatur pruefen",
        "severity": "info",
    },

    # === Charger (Ladegeraet) als Affected ===
    {
        "role": "solar", "state": "on",
        "affects": "charger", "same_room": False,
        "effect": "Solar → Geraete mit Solarstrom laden",
        "hint": "Solarueberschuss → Geraete jetzt laden (gratis Strom)",
        "severity": "info",
    },

    # === Motor als Affected ===
    {
        "role": "problem", "state": "on",
        "affects": "motor", "same_room": True,
        "effect": "Problem → Motor pruefen (Blockierung?)",
        "hint": "Motor-Problem → Blockierung/Ueberlast pruefen",
        "severity": "info",
    },

    # === Intercom: Alarm-Kontext ===
    {
        "role": "alarm", "state": "triggered",
        "affects": "intercom", "same_room": False,
        "effect": "Alarm → Gegensprechanlage fuer Kommunikation mit Polizei",
        "hint": "ALARM → Gegensprechanlage bereit fuer Polizei/Sicherheitsdienst",
        "severity": "info",
    },

    # === Relay: mehr Trigger ===
    {
        "role": "smoke", "state": "on",
        "affects": "relay", "same_room": False,
        "effect": "Rauch → Relay NICHT schalten (Funke!)",
        "hint": "Rauch → Relays NICHT schalten",
        "severity": "high",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "relay", "same_room": True,
        "effect": "Wasserleck → Relay ausschalten (Kurzschluss!)",
        "hint": "Wasserleck → Relays in Naehe abschalten, Kurzschluss-Gefahr",
        "severity": "high",
    },

    # =================================================================
    # INVERSE-STATE REGELN — Was passiert wenn Geraete AUS/ZU gehen
    # =================================================================

    # -----------------------------------------------------------------
    # FENSTER / TUER / TOR / GARAGE — geschlossen
    # -----------------------------------------------------------------
    {
        "role": "window_contact", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Fenster geschlossen → Heizung/Kuehlung arbeitet wieder effizient",
        "hint": "Fenster zu → Klimaanlage/Heizung kann normal arbeiten",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "energy", "same_room": True,
        "effect": "Fenster geschlossen → Energieverschwendung beendet",
        "hint": "Fenster zu → kein Energieverlust mehr durch offenes Fenster",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Fenster geschlossen → Raumtemperatur stabilisiert sich",
        "hint": "Fenster zu → Temperatur normalisiert sich",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Fenster geschlossen → Sicherheitsluecke geschlossen",
        "hint": "Fenster zu → Alarm-Zone wiederhergestellt",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "air_purifier", "same_room": True,
        "effect": "Fenster geschlossen → Luftreiniger arbeitet effizient",
        "hint": "Fenster zu → Luftreiniger muss nicht gegen Aussenluft kaempfen",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "Fenster geschlossen → Luftqualitaet wird kontrolliert",
        "hint": "Fenster zu → kein Einfluss von Aussenluft mehr",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "ventilation", "same_room": True,
        "effect": "Fenster geschlossen → Lueftungsanlage kann uebernehmen",
        "hint": "Fenster zu → Lueftungsanlage arbeitet effizient",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "humidifier", "same_room": True,
        "effect": "Fenster geschlossen → Luftbefeuchter arbeitet effizient",
        "hint": "Fenster zu → Luftfeuchtigkeit bleibt stabil",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "dehumidifier", "same_room": True,
        "effect": "Fenster geschlossen → Entfeuchter arbeitet effizient",
        "hint": "Fenster zu → keine feuchte Aussenluft mehr",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "fan", "same_room": True,
        "effect": "Fenster geschlossen → Ventilator reicht ggf. nicht mehr",
        "hint": "Fenster zu → Ventilator statt Durchzug, ggf. Klima einschalten",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Fenster geschlossen → Aussenlaerm gedaemmt",
        "hint": "Fenster zu → weniger Laerm von draussen",
        "severity": "info",
    },
    {
        "role": "window_contact", "state": "off",
        "affects": "light_level", "same_room": True,
        "effect": "Fenster geschlossen → Lichteinfall nur noch durch Glas",
        "hint": "Fenster zu → Lichtverhaeltnisse aendern sich leicht",
        "severity": "info",
    },
    # Door contact closed
    {
        "role": "door_contact", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Tuer geschlossen → Sicherheitszone wiederhergestellt",
        "hint": "Tuer zu → Alarm-Zone intakt",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Tuer geschlossen → Klimazone abgeschlossen",
        "hint": "Tuer zu → Raum klimatisch isoliert",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Tuer geschlossen → Licht im Raum unabhaengig",
        "hint": "Tuer zu → Raumlicht separat steuerbar",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "off",
        "affects": "lock", "same_room": False,
        "effect": "Tuer geschlossen → kann verriegelt werden",
        "hint": "Tuer zu → Schloss kann verriegelt werden",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "off",
        "affects": "camera", "same_room": False,
        "effect": "Tuer geschlossen → Kamera-Ueberwachung normal",
        "hint": "Tuer zu → kein Durchgangsverkehr mehr",
        "severity": "info",
    },
    {
        "role": "door_contact", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Tuer geschlossen → Benachrichtigung dass geschlossen",
        "hint": "Tuer zu → Info: Tuer wurde geschlossen",
        "severity": "info",
    },
    # Garage door closed
    {
        "role": "garage_door", "state": "closed",
        "affects": "alarm", "same_room": False,
        "effect": "Garagentor geschlossen → Sicherheit wiederhergestellt",
        "hint": "Garage zu → Alarm-Zone intakt",
        "severity": "info",
    },
    {
        "role": "garage_door", "state": "closed",
        "affects": "climate", "same_room": True,
        "effect": "Garagentor geschlossen → kein Waermeverlust mehr",
        "hint": "Garage zu → Temperatur stabilisiert sich",
        "severity": "info",
    },
    {
        "role": "garage_door", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Garagentor geschlossen → Garagenlicht ggf. ausschalten",
        "hint": "Garage zu → Licht kann aus",
        "severity": "info",
    },
    {
        "role": "garage_door", "state": "closed",
        "affects": "camera", "same_room": False,
        "effect": "Garagentor geschlossen → Kamera-Ueberwachung normal",
        "hint": "Garage zu → kein offener Zugang mehr",
        "severity": "info",
    },
    {
        "role": "garage_door", "state": "closed",
        "affects": "ev_charger", "same_room": True,
        "effect": "Garagentor geschlossen → E-Auto sicher am Laden",
        "hint": "Garage zu → Ladevorgang geschuetzt",
        "severity": "info",
    },
    {
        "role": "garage_door", "state": "closed",
        "affects": "notify", "same_room": False,
        "effect": "Garagentor geschlossen → Info",
        "hint": "Garagentor wurde geschlossen",
        "severity": "info",
    },
    # Gate closed
    {
        "role": "gate", "state": "closed",
        "affects": "alarm", "same_room": False,
        "effect": "Tor geschlossen → Grundstueck gesichert",
        "hint": "Tor zu → Zugang gesichert",
        "severity": "info",
    },
    {
        "role": "gate", "state": "closed",
        "affects": "camera", "same_room": False,
        "effect": "Tor geschlossen → Kamera normal",
        "hint": "Tor zu → kein Durchgangsverkehr",
        "severity": "info",
    },
    {
        "role": "gate", "state": "closed",
        "affects": "light", "same_room": False,
        "effect": "Tor geschlossen → Einfahrtslicht kann aus",
        "hint": "Tor zu → Aussenbeleuchtung ggf. ausschalten",
        "severity": "info",
    },
    {
        "role": "gate", "state": "closed",
        "affects": "notify", "same_room": False,
        "effect": "Tor geschlossen → Info",
        "hint": "Tor wurde geschlossen",
        "severity": "info",
    },
    # Curtain open
    {
        "role": "curtain", "state": "open",
        "affects": "light", "same_room": True,
        "effect": "Vorhang offen → Tageslicht kommt rein",
        "hint": "Vorhang offen → mehr Tageslicht, ggf. Licht ausschalten",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "open",
        "affects": "light_level", "same_room": True,
        "effect": "Vorhang offen → Helligkeit steigt",
        "hint": "Vorhang offen → mehr Licht im Raum",
        "severity": "info",
    },
    # Awning closed
    {
        "role": "awning", "state": "closed",
        "affects": "climate", "same_room": True,
        "effect": "Markise eingefahren → Sonneneinstrahlung wieder direkt",
        "hint": "Markise eingefahren → Sonne scheint direkt, ggf. Rollladen runter",
        "severity": "info",
    },

    # -----------------------------------------------------------------
    # KLIMA / HEIZUNG / KUEHLUNG — ausgeschaltet
    # -----------------------------------------------------------------
    {
        "role": "heating", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Heizung aus → Raumtemperatur sinkt",
        "hint": "Heizung aus → Temperatur faellt, ggf. warm anziehen",
        "severity": "info",
    },
    {
        "role": "heating", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Heizung aus → Energieverbrauch sinkt",
        "hint": "Heizung aus → Energie wird gespart",
        "severity": "info",
    },
    {
        "role": "heating", "state": "off",
        "affects": "cooling", "same_room": True,
        "effect": "Heizung aus → kein Konflikt mehr mit Kuehlung",
        "hint": "Heizung aus → Kuehlung kann ungestoert arbeiten",
        "severity": "info",
    },
    {
        "role": "heating", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Heizung aus → Fenster oeffnen kein Energieproblem",
        "hint": "Heizung aus → Lueften ohne Energieverlust",
        "severity": "info",
    },
    {
        "role": "heating", "state": "off",
        "affects": "humidity", "same_room": True,
        "effect": "Heizung aus → Luft trocknet nicht mehr aus",
        "hint": "Heizung aus → Luftfeuchtigkeit steigt evtl.",
        "severity": "info",
    },
    {
        "role": "heating", "state": "off",
        "affects": "humidifier", "same_room": True,
        "effect": "Heizung aus → Luftbefeuchter weniger noetig",
        "hint": "Heizung aus → Luft trocknet nicht, Befeuchter ggf. ausschalten",
        "severity": "info",
    },
    {
        "role": "heating", "state": "off",
        "affects": "smoke", "same_room": True,
        "effect": "Heizung aus → kein Verbrennungsrisiko mehr",
        "hint": "Heizung aus → Rauchmelder-Fehlalarme durch Heizung ausgeschlossen",
        "severity": "info",
    },
    # Cooling off
    {
        "role": "cooling", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Kuehlung aus → Raumtemperatur steigt",
        "hint": "Kuehlung aus → Temperatur steigt, ggf. Fenster oeffnen",
        "severity": "info",
    },
    {
        "role": "cooling", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Kuehlung aus → Energieverbrauch sinkt",
        "hint": "Kuehlung aus → Energie wird gespart",
        "severity": "info",
    },
    {
        "role": "cooling", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Kuehlung aus → Fenster oeffnen moeglich",
        "hint": "Kuehlung aus → Fenster oeffnen ohne Energieverlust",
        "severity": "info",
    },
    # Ventilation off
    {
        "role": "ventilation", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "Lueftung aus → Luftqualitaet wird nicht mehr aktiv verbessert",
        "hint": "Lueftung aus → ggf. Fenster oeffnen fuer frische Luft",
        "severity": "info",
    },
    {
        "role": "ventilation", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Lueftung aus → manuelles Lueften noetig",
        "hint": "Lueftung aus → Fenster oeffnen fuer Luftaustausch",
        "severity": "info",
    },
    # Fan off
    {
        "role": "fan", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Ventilator aus → Luftzirkulation gestoppt",
        "hint": "Ventilator aus → kein Windchill-Effekt mehr",
        "severity": "info",
    },
    {
        "role": "fan", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Ventilator aus → Laerm beendet",
        "hint": "Ventilator aus → ruhiger im Raum",
        "severity": "info",
    },
    {
        "role": "fan", "state": "off",
        "affects": "bed_occupancy", "same_room": True,
        "effect": "Ventilator aus → kein stoerend Geraeusch beim Schlafen",
        "hint": "Ventilator aus → Schlafumgebung ruhiger",
        "severity": "info",
    },
    # Humidifier off
    {
        "role": "humidifier", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Luftbefeuchter aus → Energie gespart",
        "hint": "Luftbefeuchter aus → kein Stromverbrauch mehr",
        "severity": "info",
    },
    {
        "role": "humidifier", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Luftbefeuchter aus → Fenster oeffnen moeglich ohne Effizienzverlust",
        "hint": "Luftbefeuchter aus → Lueften kein Problem",
        "severity": "info",
    },
    # Dehumidifier off
    {
        "role": "dehumidifier", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Entfeuchter aus → Energie gespart",
        "hint": "Entfeuchter aus → kein Stromverbrauch mehr",
        "severity": "info",
    },
    {
        "role": "dehumidifier", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Entfeuchter aus → Fenster oeffnen moeglich",
        "hint": "Entfeuchter aus → Lueften kein Problem",
        "severity": "info",
    },
    # Boiler off
    {
        "role": "boiler", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Boiler aus → Energieverbrauch sinkt",
        "hint": "Boiler aus → kein Strom/Gas-Verbrauch",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Boiler aus → Netzbezug sinkt",
        "hint": "Boiler aus → weniger Strom aus dem Netz",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "off",
        "affects": "water_temp", "same_room": False,
        "effect": "Boiler aus → Warmwasser kuehlt ab",
        "hint": "Boiler aus → kein warmes Wasser nach Vorrat",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Boiler aus → Heizungsunterstuetzung endet",
        "hint": "Boiler aus → kein Beitrag zur Raumheizung",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "off",
        "affects": "solar", "same_room": False,
        "effect": "Boiler aus → Solar-Ueberschuss frei",
        "hint": "Boiler aus → Solarstrom steht fuer anderes zur Verfuegung",
        "severity": "info",
    },
    {
        "role": "boiler", "state": "off",
        "affects": "water_leak", "same_room": True,
        "effect": "Boiler aus → Wasserleck-Risiko reduziert",
        "hint": "Boiler aus → weniger Druck, Leckrisiko sinkt",
        "severity": "info",
    },
    # Air purifier off
    {
        "role": "air_purifier", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "Luftreiniger aus → Luftqualitaet wird nicht mehr aktiv verbessert",
        "hint": "Luftreiniger aus → Luft wird nicht mehr gefiltert",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Luftreiniger aus → Energie gespart",
        "hint": "Luftreiniger aus → kein Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Luftreiniger aus → Laerm beendet",
        "hint": "Luftreiniger aus → ruhiger im Raum",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "off",
        "affects": "bed_occupancy", "same_room": True,
        "effect": "Luftreiniger aus → Schlafumgebung ruhiger",
        "hint": "Luftreiniger aus → kein Geraeusch beim Schlafen",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Luftreiniger aus → Fenster oeffnen fuer frische Luft",
        "hint": "Luftreiniger aus → manuell lueften",
        "severity": "info",
    },

    # -----------------------------------------------------------------
    # MEDIEN / ENTERTAINMENT — ausgeschaltet
    # -----------------------------------------------------------------
    {
        "role": "tv", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "TV aus → Raumbeleuchtung wieder normal",
        "hint": "TV aus → Licht kann wieder aufgedreht werden",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "dimmer", "same_room": True,
        "effect": "TV aus → Dimmer kann auf normal",
        "hint": "TV aus → Dimmer wieder auf normale Helligkeit",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "TV aus → Rollladen koennen wieder hoch",
        "hint": "TV aus → Rollladen oeffnen, Tageslicht rein",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "curtain", "same_room": True,
        "effect": "TV aus → Vorhaenge koennen wieder auf",
        "hint": "TV aus → Vorhaenge oeffnen",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "TV aus → weniger Abwaerme im Raum",
        "hint": "TV aus → Raum kuehl sich leicht ab",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "TV aus → Energieverbrauch sinkt",
        "hint": "TV aus → Strom gespart",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "receiver", "same_room": True,
        "effect": "TV aus → Receiver kann auch ausgeschaltet werden",
        "hint": "TV aus → Receiver ggf. auch ausschalten",
        "severity": "info",
    },
    {
        "role": "tv", "state": "off",
        "affects": "presence", "same_room": False,
        "effect": "TV aus → weniger Anzeichen fuer Anwesenheit",
        "hint": "TV aus → kein Anwesenheitssignal durch TV",
        "severity": "info",
    },
    # Projector off
    {
        "role": "projector", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Projektor aus → Licht kann wieder an",
        "hint": "Projektor aus → Raumbeleuchtung wieder normal",
        "severity": "info",
    },
    {
        "role": "projector", "state": "off",
        "affects": "dimmer", "same_room": True,
        "effect": "Projektor aus → Dimmer kann auf normal",
        "hint": "Projektor aus → normale Helligkeit",
        "severity": "info",
    },
    {
        "role": "projector", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "Projektor aus → Rollladen koennen hoch",
        "hint": "Projektor aus → Tageslicht wieder rein",
        "severity": "info",
    },
    {
        "role": "projector", "state": "off",
        "affects": "curtain", "same_room": True,
        "effect": "Projektor aus → Vorhaenge koennen oeffnen",
        "hint": "Projektor aus → Vorhaenge auf",
        "severity": "info",
    },
    {
        "role": "projector", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Projektor aus → weniger Abwaerme",
        "hint": "Projektor aus → Raum kuehlt sich ab",
        "severity": "info",
    },
    # Gaming off
    {
        "role": "gaming", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Gaming aus → Licht wieder normal",
        "hint": "Gaming vorbei → Licht aufdrehen",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "Gaming aus → Rollladen koennen hoch",
        "hint": "Gaming vorbei → Tageslicht rein",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "off",
        "affects": "curtain", "same_room": True,
        "effect": "Gaming aus → Vorhaenge oeffnen",
        "hint": "Gaming vorbei → Vorhaenge auf",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Gaming aus → weniger Abwaerme",
        "hint": "Gaming aus → Raum kuehlt sich ab",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Gaming aus → Energieverbrauch sinkt",
        "hint": "Gaming aus → Strom gespart",
        "severity": "info",
    },
    # Receiver off
    {
        "role": "receiver", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Receiver aus → Energie gespart",
        "hint": "Receiver aus → kein Standby-Verbrauch",
        "severity": "info",
    },
    {
        "role": "receiver", "state": "off",
        "affects": "tv", "same_room": True,
        "effect": "Receiver aus → TV hat kein Signal",
        "hint": "Receiver aus → TV ggf. auch ausschalten",
        "severity": "info",
    },
    {
        "role": "receiver", "state": "off",
        "affects": "media_player", "same_room": True,
        "effect": "Receiver aus → Medienwiedergabe stoppt",
        "hint": "Receiver aus → kein Audio/Video mehr",
        "severity": "info",
    },
    {
        "role": "receiver", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Receiver aus → Kino-Modus beendet",
        "hint": "Receiver aus → Licht kann wieder normal",
        "severity": "info",
    },
    # Media player paused/idle
    {
        "role": "media_player", "state": "paused",
        "affects": "light", "same_room": True,
        "effect": "Wiedergabe pausiert → Licht kann angepasst werden",
        "hint": "Pause → Licht ggf. heller fuer Pause",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "paused",
        "affects": "dimmer", "same_room": True,
        "effect": "Wiedergabe pausiert → Dimmer heller",
        "hint": "Pause → Dimmer hoch fuer Pause",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "paused",
        "affects": "color_light", "same_room": True,
        "effect": "Wiedergabe pausiert → Ambientebeleuchtung anpassen",
        "hint": "Pause → Farbliche Beleuchtung auf Pause-Modus",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "paused",
        "affects": "blinds", "same_room": True,
        "effect": "Wiedergabe pausiert → Rollladen ggf. oeffnen",
        "hint": "Pause → Tageslicht fuer Pause",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "paused",
        "affects": "curtain", "same_room": True,
        "effect": "Wiedergabe pausiert → Vorhaenge ggf. oeffnen",
        "hint": "Pause → Vorhaenge auf fuer Pause",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "paused",
        "affects": "climate", "same_room": True,
        "effect": "Wiedergabe pausiert → Klimaanpassung moeglich",
        "hint": "Pause → Klima anpassen wenn noetig",
        "severity": "info",
    },
    {
        "role": "media_player", "state": "paused",
        "affects": "window_contact", "same_room": True,
        "effect": "Wiedergabe pausiert → Fenster oeffnen moeglich",
        "hint": "Pause → Lueften moeglich ohne Stoerung",
        "severity": "info",
    },
    # Speaker paused
    {
        "role": "speaker", "state": "paused",
        "affects": "noise", "same_room": True,
        "effect": "Lautsprecher pausiert → Laerm beendet",
        "hint": "Lautsprecher Pause → ruhig im Raum",
        "severity": "info",
    },
    {
        "role": "speaker", "state": "paused",
        "affects": "bed_occupancy", "same_room": True,
        "effect": "Lautsprecher pausiert → Schlaf nicht gestoert",
        "hint": "Lautsprecher Pause → Ruhe zum Schlafen",
        "severity": "info",
    },
    {
        "role": "speaker", "state": "paused",
        "affects": "window_contact", "same_room": True,
        "effect": "Lautsprecher pausiert → Fenster oeffnen ohne Laerm nach draussen",
        "hint": "Lautsprecher Pause → Lueften ohne Nachbarn zu stoeren",
        "severity": "info",
    },
    # PC off
    {
        "role": "pc", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "PC aus → Arbeitslicht ggf. nicht mehr noetig",
        "hint": "PC aus → Schreibtischlampe kann aus",
        "severity": "info",
    },
    {
        "role": "pc", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "PC aus → weniger Abwaerme im Raum",
        "hint": "PC aus → Raum kuehlt sich ab",
        "severity": "info",
    },
    {
        "role": "pc", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "PC aus → Energieverbrauch sinkt",
        "hint": "PC aus → Strom gespart",
        "severity": "info",
    },
    {
        "role": "pc", "state": "off",
        "affects": "fan", "same_room": True,
        "effect": "PC aus → Kuehlung per Ventilator ggf. nicht mehr noetig",
        "hint": "PC aus → weniger Abwaerme, Ventilator ggf. aus",
        "severity": "info",
    },
    {
        "role": "pc", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "PC aus → Raumtemperatur sinkt leicht",
        "hint": "PC aus → weniger Waerme im Raum",
        "severity": "info",
    },
    {
        "role": "pc", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "PC aus → Lueftergeraeusch endet",
        "hint": "PC aus → ruhiger im Raum",
        "severity": "info",
    },
    # Dimmer off
    {
        "role": "dimmer", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "Dimmer aus → Tageslicht noetig",
        "hint": "Dimmer aus → Rollladen oeffnen fuer Licht",
        "severity": "info",
    },
    {
        "role": "dimmer", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Dimmer aus → Energie gespart",
        "hint": "Dimmer aus → kein Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "dimmer", "state": "off",
        "affects": "media_player", "same_room": True,
        "effect": "Dimmer aus → Kino-Atmosphaere moeglich",
        "hint": "Dimmer aus → ideal fuer Film/Serie",
        "severity": "info",
    },
    # Color light off
    {
        "role": "color_light", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Farblicht aus → Energie gespart",
        "hint": "Farblicht aus → kein Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "color_light", "state": "off",
        "affects": "media_player", "same_room": True,
        "effect": "Farblicht aus → Ambilight-Modus beendet",
        "hint": "Farblicht aus → kein Ambiente-Effekt mehr",
        "severity": "info",
    },

    # -----------------------------------------------------------------
    # HAUSHALTSGERAETE — ausgeschaltet / fertig
    # -----------------------------------------------------------------
    {
        "role": "oven", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Herd/Ofen aus → Info dass ausgeschaltet",
        "hint": "Herd aus → Entwarnung, kein Brandrisiko mehr",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Herd aus → Brandgefahr beendet",
        "hint": "Herd aus → kein Brandrisiko mehr",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "ventilation", "same_room": True,
        "effect": "Herd aus → Dunstabzug kann aus",
        "hint": "Kochen vorbei → Dunstabzug noch kurz laufen lassen, dann aus",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "window_contact", "same_room": True,
        "effect": "Herd aus → Lueften nach dem Kochen",
        "hint": "Kochen vorbei → kurz lueften fuer frische Luft",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "Herd aus → Luftqualitaet erholt sich",
        "hint": "Kochen vorbei → Luft wird besser",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Herd aus → Kueche kuehlt sich ab",
        "hint": "Kochen vorbei → Raumtemperatur sinkt",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Herd aus → Netzbezug sinkt deutlich",
        "hint": "Herd aus → 2-4 kW weniger Netzbezug",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "smoke", "same_room": True,
        "effect": "Herd aus → Rauchmelder-Fehlalarm durch Kochen vorbei",
        "hint": "Kochen vorbei → Rauchmelder normal",
        "severity": "info",
    },
    {
        "role": "oven", "state": "off",
        "affects": "presence", "same_room": False,
        "effect": "Herd aus → kein Brandrisiko bei Abwesenheit",
        "hint": "Herd aus → sicher das Haus zu verlassen",
        "severity": "info",
    },
    # Vacuum docked
    {
        "role": "vacuum", "state": "docked",
        "affects": "motion", "same_room": False,
        "effect": "Saugroboter in Station → keine Fehl-Bewegung mehr",
        "hint": "Saugroboter fertig → Bewegungsmelder wieder verlaesslich",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "docked",
        "affects": "alarm", "same_room": False,
        "effect": "Saugroboter in Station → kein Fehlalarm-Risiko",
        "hint": "Saugroboter fertig → Alarm kann scharf gestellt werden",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "docked",
        "affects": "noise", "same_room": False,
        "effect": "Saugroboter fertig → Laerm beendet",
        "hint": "Saugroboter fertig → ruhig im Haus",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "docked",
        "affects": "bed_occupancy", "same_room": False,
        "effect": "Saugroboter fertig → kein Laerm mehr beim Schlafen",
        "hint": "Saugroboter fertig → Schlaf nicht mehr gestoert",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "docked",
        "affects": "door_contact", "same_room": False,
        "effect": "Saugroboter fertig → Tueren koennen wieder geschlossen werden",
        "hint": "Saugroboter fertig → Zimmertueren wieder zu",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "docked",
        "affects": "presence", "same_room": False,
        "effect": "Saugroboter fertig → kein stoerend Laerm mehr",
        "hint": "Saugroboter fertig → Meeting/Telefonat nicht mehr gestoert",
        "severity": "info",
    },
    # Dishwasher off
    {
        "role": "dishwasher", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Spuelmaschine fertig → Laerm beendet",
        "hint": "Spuelmaschine fertig → ruhig in der Kueche",
        "severity": "info",
    },
    {
        "role": "dishwasher", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Spuelmaschine fertig → Netzbezug sinkt",
        "hint": "Spuelmaschine fertig → weniger Strom",
        "severity": "info",
    },
    {
        "role": "dishwasher", "state": "off",
        "affects": "humidity", "same_room": True,
        "effect": "Spuelmaschine fertig → Dampf beim Oeffnen",
        "hint": "Spuelmaschine fertig → Tuer oeffnen = viel Dampf, ggf. lueften",
        "severity": "info",
    },
    {
        "role": "dishwasher", "state": "off",
        "affects": "water_leak", "same_room": True,
        "effect": "Spuelmaschine fertig → Wasserleck-Risiko sinkt",
        "hint": "Spuelmaschine fertig → kein Wasserdruck mehr",
        "severity": "info",
    },
    # Washing machine off
    {
        "role": "washing_machine", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Waschmaschine fertig → Laerm beendet",
        "hint": "Waschmaschine fertig → ruhig",
        "severity": "info",
    },
    {
        "role": "washing_machine", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Waschmaschine fertig → Netzbezug sinkt",
        "hint": "Waschmaschine fertig → weniger Strom",
        "severity": "info",
    },
    {
        "role": "washing_machine", "state": "off",
        "affects": "water_leak", "same_room": True,
        "effect": "Waschmaschine fertig → Wasserleck-Risiko sinkt",
        "hint": "Waschmaschine fertig → kein Wasserdruck mehr",
        "severity": "info",
    },
    {
        "role": "washing_machine", "state": "off",
        "affects": "presence", "same_room": False,
        "effect": "Waschmaschine fertig → kann entladen werden",
        "hint": "Waschmaschine fertig → Waesche rausnehmen, sonst muffig",
        "severity": "info",
    },
    # Dryer off
    {
        "role": "dryer", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Trockner fertig → Laerm beendet",
        "hint": "Trockner fertig → ruhig",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Trockner fertig → Netzbezug sinkt deutlich",
        "hint": "Trockner fertig → viel weniger Strom",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "off",
        "affects": "humidity", "same_room": True,
        "effect": "Trockner fertig → Luftfeuchtigkeit normalisiert sich",
        "hint": "Trockner fertig → Feuchte sinkt",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Trockner fertig → Abwaerme endet",
        "hint": "Trockner fertig → Raum kuehlt ab",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Trockner fertig → kein Klimaeinfluss mehr",
        "hint": "Trockner fertig → Raumklima normalisiert sich",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "off",
        "affects": "smoke", "same_room": True,
        "effect": "Trockner fertig → Ueberhitzungsrisiko beendet",
        "hint": "Trockner fertig → kein Brandrisiko mehr",
        "severity": "info",
    },
    {
        "role": "dryer", "state": "off",
        "affects": "presence", "same_room": False,
        "effect": "Trockner fertig → Waesche kann raus",
        "hint": "Trockner fertig → Waesche rausnehmen",
        "severity": "info",
    },
    # Coffee machine off
    {
        "role": "coffee_machine", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Kaffeemaschine aus → Energie gespart",
        "hint": "Kaffeemaschine aus → kein Standby-Verbrauch",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "off",
        "affects": "water_consumption", "same_room": False,
        "effect": "Kaffeemaschine aus → kein Wasserverbrauch mehr",
        "hint": "Kaffeemaschine aus → Wasser gespart",
        "severity": "info",
    },
    # Irrigation off
    {
        "role": "irrigation", "state": "off",
        "affects": "water_consumption", "same_room": False,
        "effect": "Bewaesserung aus → Wasserverbrauch sinkt",
        "hint": "Bewaesserung gestoppt → Wasser gespart",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Bewaesserung aus → Pumpenenergie gespart",
        "hint": "Bewaesserung aus → kein Stromverbrauch mehr",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "off",
        "affects": "pump", "same_room": False,
        "effect": "Bewaesserung aus → Pumpe kann stoppen",
        "hint": "Bewaesserung aus → Pumpe aus",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "off",
        "affects": "soil_moisture", "same_room": False,
        "effect": "Bewaesserung aus → Boden trocknet",
        "hint": "Bewaesserung gestoppt → Bodenfeuchte sinkt langsam",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "off",
        "affects": "water_leak", "same_room": False,
        "effect": "Bewaesserung aus → Leckrisiko sinkt",
        "hint": "Bewaesserung aus → kein Wasserdruck mehr",
        "severity": "info",
    },
    # Pump off
    {
        "role": "pump", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Pumpe aus → Energie gespart",
        "hint": "Pumpe aus → kein Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "pump", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "Pumpe aus → Laerm beendet",
        "hint": "Pumpe aus → ruhig",
        "severity": "info",
    },
    {
        "role": "pump", "state": "off",
        "affects": "water_consumption", "same_room": False,
        "effect": "Pumpe aus → kein Wasserfluss mehr",
        "hint": "Pumpe aus → Wasser gespart",
        "severity": "info",
    },
    # Pool off
    {
        "role": "pool", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Pool-Technik aus → Energie gespart",
        "hint": "Pool aus → kein Stromverbrauch (Pumpe/Heizung)",
        "severity": "info",
    },
    {
        "role": "pool", "state": "off",
        "affects": "pump", "same_room": False,
        "effect": "Pool aus → Pumpe gestoppt",
        "hint": "Pool aus → Umwaelzpumpe aus",
        "severity": "info",
    },
    {
        "role": "pool", "state": "off",
        "affects": "water_leak", "same_room": False,
        "effect": "Pool aus → weniger Leckrisiko",
        "hint": "Pool aus → kein Wasserdruck",
        "severity": "info",
    },
    {
        "role": "pool", "state": "off",
        "affects": "outdoor_temp", "same_room": False,
        "effect": "Pool aus → Wassertemperatur sinkt",
        "hint": "Pool-Heizung aus → Wasser kuehlt ab",
        "severity": "info",
    },
    # Printer off
    {
        "role": "printer", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Drucker aus → Standby-Verbrauch beendet",
        "hint": "Drucker aus → Strom gespart",
        "severity": "info",
    },
    {
        "role": "printer", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "Drucker aus → kein Feinstaub/Ozon mehr",
        "hint": "Drucker aus → Luft wird besser",
        "severity": "info",
    },
    {
        "role": "printer", "state": "off",
        "affects": "fan", "same_room": True,
        "effect": "Drucker aus → Kuehlung nicht mehr noetig",
        "hint": "Drucker aus → Ventilator ggf. ausschalten",
        "severity": "info",
    },
    # EV charger off
    {
        "role": "ev_charger", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Wallbox aus → Energieverbrauch sinkt stark",
        "hint": "Laden beendet → viel weniger Strom",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Wallbox aus → Netzbezug sinkt stark",
        "hint": "Laden beendet → deutlich weniger Netzbezug",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "off",
        "affects": "heat_pump", "same_room": False,
        "effect": "Wallbox aus → Waermepumpe kann wieder volle Leistung",
        "hint": "Laden beendet → Strom fuer Waermepumpe verfuegbar",
        "severity": "info",
    },

    # -----------------------------------------------------------------
    # SONSTIGE — aus / ein
    # -----------------------------------------------------------------
    {
        "role": "outlet", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Steckdose aus → Geraet stromlos",
        "hint": "Steckdose aus → kein Standby-Verbrauch",
        "severity": "info",
    },
    {
        "role": "outlet", "state": "off",
        "affects": "presence", "same_room": False,
        "effect": "Steckdose aus → Anwesenheitssimulation beendet",
        "hint": "Steckdose aus → kein Anwesenheitssignal mehr",
        "severity": "info",
    },
    {
        "role": "relay", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Relay aus → angeschlossenes Geraet stromlos",
        "hint": "Relay aus → Geraet ausgeschaltet, Strom gespart",
        "severity": "info",
    },
    {
        "role": "relay", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Relay aus → Geraet wurde abgeschaltet",
        "hint": "Relay aus → Info: angeschlossenes Geraet ist aus",
        "severity": "info",
    },
    {
        "role": "motor", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Motor aus → Energie gespart",
        "hint": "Motor aus → kein Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "charger", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Ladegeraet aus → Laden beendet",
        "hint": "Ladegeraet aus → kein Stromverbrauch mehr",
        "severity": "info",
    },
    {
        "role": "garden_light", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Gartenbeleuchtung aus → Energie gespart",
        "hint": "Gartenlicht aus → Strom gespart",
        "severity": "info",
    },
    {
        "role": "garden_light", "state": "off",
        "affects": "camera", "same_room": False,
        "effect": "Gartenbeleuchtung aus → Kamera auf Nachtsicht",
        "hint": "Gartenlicht aus → Kamera wechselt auf IR/Nachtsicht",
        "severity": "info",
    },
    # Router on (inverse of off)
    {
        "role": "router", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Router online → Alarmsystem wieder erreichbar",
        "hint": "Router online → Fernzugriff auf Alarm wiederhergestellt",
        "severity": "info",
    },
    {
        "role": "router", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Router online → Kameras wieder erreichbar",
        "hint": "Router online → Kamera-Streams verfuegbar",
        "severity": "info",
    },
    {
        "role": "router", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Router online → Streaming wieder moeglich",
        "hint": "Router online → Medien-Streaming verfuegbar",
        "severity": "info",
    },
    {
        "role": "router", "state": "on",
        "affects": "automation", "same_room": False,
        "effect": "Router online → Automationen wieder aktiv",
        "hint": "Router online → alle Automationen funktionieren wieder",
        "severity": "info",
    },
    {
        "role": "router", "state": "on",
        "affects": "nas", "same_room": False,
        "effect": "Router online → NAS wieder erreichbar",
        "hint": "Router online → Netzwerkspeicher verfuegbar",
        "severity": "info",
    },
    {
        "role": "router", "state": "on",
        "affects": "server", "same_room": False,
        "effect": "Router online → Server wieder erreichbar",
        "hint": "Router online → Server-Dienste verfuegbar",
        "severity": "info",
    },
    {
        "role": "router", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Router online → Benachrichtigungen wieder moeglich",
        "hint": "Router online → Push-Nachrichten funktionieren wieder",
        "severity": "info",
    },
    # Valve on (inverse of off)
    {
        "role": "valve", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Ventil offen → Wasser/Gas fliesst",
        "hint": "Ventil offen → Medium fliesst",
        "severity": "info",
    },

    # -----------------------------------------------------------------
    # FEHLENDE AFFECTS-TARGETS — Rollen die bisher nie Ziel waren
    # -----------------------------------------------------------------
    # Solar → Grid Feed (Einspeisung)
    {
        "role": "solar", "state": "on",
        "affects": "grid_feed", "same_room": False,
        "effect": "Solaranlage produziert → Ueberschuss wird eingespeist",
        "hint": "Solar produziert → Netzeinspeisung steigt wenn kein Eigenverbrauch",
        "severity": "info",
    },
    {
        "role": "battery", "state": "on",
        "affects": "grid_feed", "same_room": False,
        "effect": "Batterie voll + Solar → Einspeisung ins Netz",
        "hint": "Batterie voll → Ueberschuss geht ins Netz",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "grid_feed", "same_room": False,
        "effect": "E-Auto laedt → weniger Einspeisung ins Netz",
        "hint": "Wallbox aktiv → Eigenverbrauch statt Einspeisung",
        "severity": "info",
    },
    # Motion → Occupancy
    {
        "role": "motion", "state": "on",
        "affects": "occupancy", "same_room": True,
        "effect": "Bewegung erkannt → Raum ist belegt",
        "hint": "Bewegung → Raum besetzt",
        "severity": "info",
    },
    # Presence → Occupancy
    {
        "role": "presence", "state": "on",
        "affects": "occupancy", "same_room": False,
        "effect": "Person anwesend → Haus ist belegt",
        "hint": "Anwesenheit → Haus bewohnt",
        "severity": "info",
    },
    {
        "role": "presence", "state": "off",
        "affects": "occupancy", "same_room": False,
        "effect": "Alle abwesend → Haus ist leer",
        "hint": "Abwesenheit → Haus unbewohnt",
        "severity": "info",
    },
    # Router off → Printer (Netzwerkdrucker offline)
    {
        "role": "router", "state": "off",
        "affects": "printer", "same_room": False,
        "effect": "Router offline → Netzwerkdrucker nicht erreichbar",
        "hint": "Router down → Drucker nicht verfuegbar",
        "severity": "info",
    },
    # Router on → Printer
    {
        "role": "router", "state": "on",
        "affects": "printer", "same_room": False,
        "effect": "Router online → Netzwerkdrucker verfuegbar",
        "hint": "Router online → Drucker erreichbar",
        "severity": "info",
    },

    # =================================================================
    # LETZTE LUECKEN — fehlende Kreuz-Beziehungen
    # =================================================================

    # Waermepumpe → Netzbezug / Raumtemperatur
    {
        "role": "heat_pump", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Waermepumpe an → Netzbezug steigt deutlich",
        "hint": "Waermepumpe aktiv → hoher Stromverbrauch (2-5 kW)",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "off",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Waermepumpe aus → Netzbezug sinkt deutlich",
        "hint": "Waermepumpe aus → deutlich weniger Strom",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "on",
        "affects": "indoor_temp", "same_room": False,
        "effect": "Waermepumpe an → Raumtemperatur wird geregelt",
        "hint": "Waermepumpe aktiv → heizt oder kuehlt je nach Modus",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "off",
        "affects": "indoor_temp", "same_room": False,
        "effect": "Waermepumpe aus → Temperaturregelung stoppt",
        "hint": "Waermepumpe aus → Temperatur driftet ohne Regelung",
        "severity": "info",
    },

    # Fussbodenheizung / Radiator off → Temperatur / Energie
    {
        "role": "floor_heating", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Fussbodenheizung aus → Boden und Raum kuehlen ab",
        "hint": "Fussbodenheizung aus → Temperatur sinkt langsam (traege)",
        "severity": "info",
    },
    {
        "role": "floor_heating", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Fussbodenheizung aus → Energie gespart",
        "hint": "Fussbodenheizung aus → kein Energieverbrauch",
        "severity": "info",
    },
    {
        "role": "radiator", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Heizkoerper aus → Raum kuehlt ab",
        "hint": "Heizkoerper aus → Temperatur sinkt",
        "severity": "info",
    },
    {
        "role": "radiator", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Heizkoerper aus → Energie gespart",
        "hint": "Heizkoerper aus → kein Energieverbrauch",
        "severity": "info",
    },

    # Thermostat → Heizung / Kuehlung
    {
        "role": "thermostat", "state": "on",
        "affects": "heating", "same_room": True,
        "effect": "Thermostat aktiv → Heizung wird gesteuert",
        "hint": "Thermostat regelt → Heizung folgt Solltemperatur",
        "severity": "info",
    },
    {
        "role": "thermostat", "state": "on",
        "affects": "cooling", "same_room": True,
        "effect": "Thermostat aktiv → Kuehlung wird gesteuert",
        "hint": "Thermostat regelt → Kuehlung folgt Solltemperatur",
        "severity": "info",
    },
    {
        "role": "thermostat", "state": "off",
        "affects": "heating", "same_room": True,
        "effect": "Thermostat aus → Heizung ohne Regelung",
        "hint": "Thermostat aus → Heizung laeuft ungeregelt oder stoppt",
        "severity": "info",
    },
    {
        "role": "thermostat", "state": "off",
        "affects": "cooling", "same_room": True,
        "effect": "Thermostat aus → Kuehlung ohne Regelung",
        "hint": "Thermostat aus → Kuehlung laeuft ungeregelt oder stoppt",
        "severity": "info",
    },

    # Schloss verriegelt → Alarm / Notify
    {
        "role": "lock", "state": "locked",
        "affects": "alarm", "same_room": False,
        "effect": "Schloss verriegelt → Sicherheit erhoet",
        "hint": "Schloss zu → Alarm kann scharf gestellt werden",
        "severity": "info",
    },

    # Gas-Leck → Gasventil schliessen
    {
        "role": "gas", "state": "on",
        "affects": "valve", "same_room": False,
        "effect": "Gas erkannt → Gasventil SOFORT schliessen",
        "hint": "Gas-Leck → Hauptventil sofort zu, Explosionsgefahr!",
        "severity": "critical",
    },

    # Auto zuhause → Licht
    {
        "role": "car", "state": "home",
        "affects": "light", "same_room": False,
        "effect": "Auto kommt an → Einfahrt/Garage beleuchten",
        "hint": "Auto zuhause → Willkommenslicht einschalten",
        "severity": "info",
    },

    # NAS off → Server / Media
    {
        "role": "nas", "state": "off",
        "affects": "server", "same_room": False,
        "effect": "NAS offline → Server hat keinen Netzwerkspeicher",
        "hint": "NAS offline → Backups/Daten nicht verfuegbar fuer Server",
        "severity": "info",
    },

    # Intercom → Speaker (leiser/pausieren)
    {
        "role": "intercom", "state": "on",
        "affects": "speaker", "same_room": True,
        "effect": "Gegensprechanlage aktiv → Lautsprecher stoert",
        "hint": "Intercom → Lautsprecher pausieren/leiser fuer Gespraech",
        "severity": "info",
    },

    # Solar → Batterie laden
    {
        "role": "solar", "state": "on",
        "affects": "battery_charging", "same_room": False,
        "effect": "Solaranlage produziert → Batterie laden",
        "hint": "Solar aktiv → Ueberschuss in Batterie speichern",
        "severity": "info",
    },

    # Lichtsensor → Dimmer
    {
        "role": "light_level", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "Helligkeit hoch → Dimmer runterregeln",
        "hint": "Viel Tageslicht → Dimmer runter, Strom sparen",
        "severity": "info",
    },

    # Stuhlbelegung off → Klima
    {
        "role": "chair_occupancy", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Stuhl leer → Raum evtl. ungenutzt",
        "hint": "Arbeitsplatz verlassen → Klima ggf. absenken",
        "severity": "info",
    },

    # Bett verlassen → Thermostat
    {
        "role": "bed_occupancy", "state": "off",
        "affects": "thermostat", "same_room": True,
        "effect": "Aufgestanden → Thermostat auf Tagestemperatur",
        "hint": "Bett verlassen → Heizung kann auf Tagestemperatur hochfahren",
        "severity": "info",
    },

    # =================================================================
    # PHYSIKALISCHE EFFEKTE — Waerme, Laerm, Strom, Feuchtigkeit, Luft
    # =================================================================

    # --- Abwaerme → indoor_temp ---
    {
        "role": "dishwasher", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Spuelmaschine an → Kueche wird waermer (Heisswasser/Trocknung)",
        "hint": "Spuelmaschine → leichte Erwaermung der Kueche",
        "severity": "info",
    },
    {
        "role": "washing_machine", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Waschmaschine an → leichte Erwaermung im Waschraum",
        "hint": "Waschmaschine → Raum wird minimal waermer",
        "severity": "info",
    },
    {
        "role": "nas", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "NAS an → leichte Abwaerme",
        "hint": "NAS → Raum wird minimal waermer",
        "severity": "info",
    },
    {
        "role": "projector", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Projektor an → starke Abwaerme",
        "hint": "Projektor → Raum wird deutlich waermer (Lampe/Laser)",
        "severity": "info",
    },
    {
        "role": "gaming", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Gaming-Konsole an → Abwaerme",
        "hint": "Konsole → Raum wird waermer (GPU/CPU Hitze)",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Kaffeemaschine an → leichte Erwaermung",
        "hint": "Kaffeemaschine → Kueche wird etwas waermer",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Wallbox laedt → Abwaerme in Garage",
        "hint": "Wallbox aktiv → Garage wird waermer",
        "severity": "info",
    },

    # --- Laerm / noise ---
    {
        "role": "siren", "state": "on",
        "affects": "noise", "same_room": False,
        "effect": "Sirene heult → extremer Laerm",
        "hint": "Sirene → sehr laut, im ganzen Haus hoerbar",
        "severity": "info",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "noise", "same_room": False,
        "effect": "Tuerklingel → Geraeusch im Haus",
        "hint": "Klingel → Ton/Melodie im Haus",
        "severity": "info",
    },
    {
        "role": "intercom", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Gegensprechanlage → Geraeusch",
        "hint": "Intercom aktiv → Stimmen/Ton hoerbar",
        "severity": "info",
    },
    {
        "role": "garage_door", "state": "open",
        "affects": "noise", "same_room": True,
        "effect": "Garagentor oeffnet → Motor-Geraeusch",
        "hint": "Garagentor → Motorlaerm beim Oeffnen/Schliessen",
        "severity": "info",
    },
    {
        "role": "gate", "state": "open",
        "affects": "noise", "same_room": False,
        "effect": "Tor oeffnet → Motor-Geraeusch",
        "hint": "Tor → Motorlaerm beim Oeffnen/Schliessen",
        "severity": "info",
    },
    {
        "role": "motor", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Motor an → Laerm",
        "hint": "Motor laeuft → Geraeusch im Raum",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Kaffeemaschine → Mahlwerk/Bruehgeraeusch",
        "hint": "Kaffee wird gemacht → laut (Mahlwerk, Dampf)",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Wallbox laedt → leises Summen",
        "hint": "Wallbox aktiv → leises Summen/Lueftergeraeusch",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "on",
        "affects": "noise", "same_room": False,
        "effect": "Bewaesserung an → Wasser-/Pumpengeraeusch",
        "hint": "Bewaesserung → Wassergeraeusch im Garten",
        "severity": "info",
    },

    # --- Netzbezug / grid_consumption ---
    {
        "role": "heating", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Heizung an → Netzbezug steigt (Elektroheizung/Waermepumpe)",
        "hint": "Heizung → erhoeter Netzbezug",
        "severity": "info",
    },
    {
        "role": "cooling", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Kuehlung an → Netzbezug steigt",
        "hint": "Klimaanlage → hoher Netzbezug (1-3 kW)",
        "severity": "info",
    },
    {
        "role": "pool", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Pool-Technik an → Netzbezug steigt",
        "hint": "Pool-Pumpe/Heizung → erhoeter Netzbezug",
        "severity": "info",
    },
    {
        "role": "pump", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Pumpe an → Netzbezug steigt",
        "hint": "Pumpe → Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Luftreiniger an → Netzbezug steigt leicht",
        "hint": "Luftreiniger → moderater Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "pc", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "PC an → Netzbezug steigt",
        "hint": "PC → Stromverbrauch (100-500W je nach Last)",
        "severity": "info",
    },
    {
        "role": "server", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Server an → Netzbezug steigt",
        "hint": "Server → permanenter Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Kaffeemaschine an → Netzbezug steigt kurzzeitig",
        "hint": "Kaffeemaschine → hoher Verbrauch beim Aufheizen (1-2 kW)",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Bewaesserung an → Netzbezug durch Pumpe",
        "hint": "Bewaesserung → Pumpen-Stromverbrauch",
        "severity": "info",
    },

    # --- Feuchtigkeit / humidity ---
    {
        "role": "oven", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Herd/Ofen an → Dampf beim Kochen",
        "hint": "Kochen → Luftfeuchtigkeit steigt (Dampf, kochendes Wasser)",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Kaffeemaschine → Dampf",
        "hint": "Kaffee → leichter Dampf, Feuchtigkeit steigt minimal",
        "severity": "info",
    },
    {
        "role": "pool", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Pool-Heizung an → Verdunstung steigt",
        "hint": "Pool beheizt → Luftfeuchtigkeit steigt (Indoor-Pool)",
        "severity": "info",
    },
    {
        "role": "air_purifier", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Luftreiniger → beeinflusst ggf. Luftfeuchtigkeit",
        "hint": "Luftreiniger → manche Modelle befeuchten/entfeuchten",
        "severity": "info",
    },
    {
        "role": "irrigation", "state": "on",
        "affects": "humidity", "same_room": False,
        "effect": "Bewaesserung an → Luftfeuchtigkeit draussen steigt",
        "hint": "Bewaesserung → feuchte Luft im Garten/Gewaechshaus",
        "severity": "info",
    },

    # --- Luftqualitaet / air_quality ---
    {
        "role": "gas", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Gas erkannt → Luftqualitaet gefaehrlich",
        "hint": "Gas-Leck → Luft kontaminiert, SOFORT lueften und raus!",
        "severity": "critical",
    },
    {
        "role": "heating", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Heizung an → trocknet Luft aus",
        "hint": "Heizung → Luft wird trocken, Luftqualitaet sinkt",
        "severity": "info",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Kaffeemaschine → Kaffee-Geruche",
        "hint": "Kaffee → angenehmer Geruch, aber Dampf/Partikel",
        "severity": "info",
    },
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "air_quality", "same_room": True,
        "effect": "Staubsauger → wirbelt Staub auf",
        "hint": "Staubsauger → kurzzeitig mehr Staub in der Luft",
        "severity": "info",
    },

    # --- Energie (allgemein) ---
    {
        "role": "server", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Server an → permanenter Energieverbrauch",
        "hint": "Server → laeuft 24/7, konstanter Verbrauch",
        "severity": "info",
    },
    {
        "role": "camera", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Kamera an → Energieverbrauch",
        "hint": "Kamera → kleiner aber permanenter Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Tuerklingel → Energieverbrauch (Smart-Klingel)",
        "hint": "Smart-Klingel → kleiner permanenter Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "intercom", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gegensprechanlage → Energieverbrauch",
        "hint": "Intercom → kleiner Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "lock", "state": "unlocked",
        "affects": "energy", "same_room": False,
        "effect": "Smart-Lock → Energieverbrauch (Batterie/Strom)",
        "hint": "Smart-Lock → verbraucht Batterie/Strom bei Betaetigung",
        "severity": "info",
    },
    {
        "role": "thermostat", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Thermostat aktiv → steuert Energieverbrauch der Heizung/Kuehlung",
        "hint": "Thermostat → regelt indirekt den Energieverbrauch",
        "severity": "info",
    },
    {
        "role": "siren", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Sirene an → Energieverbrauch",
        "hint": "Sirene → Stromverbrauch waehrend Alarm",
        "severity": "info",
    },

    # =================================================================
    # SICHERHEITSKETTEN — Rauch/CO/Gas/Wasser → Fluchtweg/Warnung
    # =================================================================
    # Rauch → Rollladen/Shutter hoch (Fluchtweg!)
    {
        "role": "smoke", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Rauch → Rollladen HOCH fuer Fluchtwege",
        "hint": "BRAND → alle Rollladen hoch, Fluchtwege freimachen!",
        "severity": "critical",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "speaker", "same_room": False,
        "effect": "Rauch → Warndurchsage ueber Lautsprecher",
        "hint": "BRAND → Lautsprecher-Durchsage: Feueralarm!",
        "severity": "critical",
    },
    # CO → Rollladen hoch + Durchsage
    {
        "role": "co", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "CO erkannt → Rollladen HOCH fuer Flucht/Lueftung",
        "hint": "CO → Rollladen hoch, Fenster oeffnen, RAUS!",
        "severity": "critical",
    },
    {
        "role": "co", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "CO erkannt → Rollladen HOCH fuer Flucht/Lueftung",
        "hint": "CO → alle Rollladen hoch, Fluchtwege frei!",
        "severity": "critical",
    },
    {
        "role": "co", "state": "on",
        "affects": "speaker", "same_room": False,
        "effect": "CO erkannt → Warndurchsage",
        "hint": "CO → Lautsprecher-Durchsage: CO-Alarm, Haus verlassen!",
        "severity": "critical",
    },
    # Gas → Rollladen hoch + Schloss auf + Durchsage + Lueftung
    {
        "role": "gas", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Gas erkannt → Tueren entriegeln fuer Flucht",
        "hint": "GAS → Tueren sofort entriegeln, Fluchtweg!",
        "severity": "critical",
    },
    {
        "role": "gas", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Gas erkannt → Rollladen hoch fuer Flucht/Lueftung",
        "hint": "GAS → Rollladen hoch, Lueftung maximieren!",
        "severity": "critical",
    },
    {
        "role": "gas", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Gas erkannt → Rollladen hoch fuer Flucht/Lueftung",
        "hint": "GAS → alle Rollladen hoch!",
        "severity": "critical",
    },
    {
        "role": "gas", "state": "on",
        "affects": "speaker", "same_room": False,
        "effect": "Gas erkannt → Warndurchsage",
        "hint": "GAS → Durchsage: Gas-Alarm, kein Feuer/Funke, sofort raus!",
        "severity": "critical",
    },
    # Wasserleck → Sirene + Schloss + Pumpe + Geraete stoppen
    {
        "role": "water_leak", "state": "on",
        "affects": "siren", "same_room": False,
        "effect": "Wasserleck → Sirene/Warnung aktivieren",
        "hint": "Wasserleck → akustische Warnung",
        "severity": "high",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Wasserleck → ggf. Zugang fuer Handwerker",
        "hint": "Wasserleck → Tuer ggf. oeffnen fuer Notdienst",
        "severity": "info",
    },
    # Sabotage → Kamera + Sirene + Licht
    {
        "role": "tamper", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Sabotage erkannt → Kamera-Aufnahme starten",
        "hint": "Sabotage → alle Kameras aufnehmen lassen",
        "severity": "high",
    },
    # Vibration → Kamera + Licht
    {
        "role": "vibration", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Vibration → Kamera pruefen",
        "hint": "Vibration an Tuer/Fenster → Kamera auf Bereich richten",
        "severity": "info",
    },
    {
        "role": "vibration", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Vibration → Licht an (Abschreckung)",
        "hint": "Vibration → Aussenbeleuchtung einschalten",
        "severity": "info",
    },
    # Sirene → Kamera + Lock + Rollladen + Garage
    {
        "role": "siren", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Sirene aktiv → Kameras aufnehmen",
        "hint": "Alarm → alle Kameras aufnehmen lassen",
        "severity": "high",
    },
    {
        "role": "siren", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Sirene aktiv → Tueren verriegeln",
        "hint": "Alarm → alle Tueren abschliessen",
        "severity": "high",
    },
    {
        "role": "siren", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Sirene aktiv → Rollladen runter (Einbruchschutz)",
        "hint": "Alarm → Rollladen runter, Zugang erschweren",
        "severity": "high",
    },
    {
        "role": "siren", "state": "on",
        "affects": "shutter", "same_room": False,
        "effect": "Sirene aktiv → Rollladen runter (Einbruchschutz)",
        "hint": "Alarm → Rollladen/Shutter schliessen",
        "severity": "high",
    },
    {
        "role": "siren", "state": "on",
        "affects": "garage_door", "same_room": False,
        "effect": "Sirene aktiv → Garagentor schliessen",
        "hint": "Alarm → Garage sofort schliessen",
        "severity": "high",
    },

    # =================================================================
    # WAERMEPUMPE / HEIZKOERPER / FUSSBODENHEIZUNG — erweitert
    # =================================================================
    {
        "role": "heat_pump", "state": "on",
        "affects": "noise", "same_room": False,
        "effect": "Waermepumpe an → Aussengeraet macht Laerm",
        "hint": "Waermepumpe → Kompressor-Laerm, ggf. Nachbarn beachten",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Waermepumpe an → hoher Energieverbrauch",
        "hint": "Waermepumpe → 2-5 kW Stromverbrauch",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "on",
        "affects": "humidity", "same_room": False,
        "effect": "Waermepumpe an → beeinflusst Luftfeuchtigkeit",
        "hint": "Waermepumpe → trocknet Luft beim Heizen",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Waermepumpe an → zentrale Klimaregelung aktiv",
        "hint": "Waermepumpe → heizt oder kuehlt das Haus zentral",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "on",
        "affects": "water_temp", "same_room": False,
        "effect": "Waermepumpe an → Warmwasser wird aufbereitet",
        "hint": "Waermepumpe → Warmwasser-Temperatur steigt",
        "severity": "info",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "climate", "same_room": True,
        "effect": "Fussbodenheizung an → Raumklima wird beeinflusst",
        "hint": "Fussbodenheizung → traege aber gleichmaessige Waerme",
        "severity": "info",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "humidity", "same_room": True,
        "effect": "Fussbodenheizung an → trocknet Luft leicht",
        "hint": "Fussbodenheizung → Luftfeuchtigkeit sinkt",
        "severity": "info",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "climate", "same_room": True,
        "effect": "Heizkoerper an → Raumklima aendert sich",
        "hint": "Heizkoerper → schnelle punktuelle Waerme",
        "severity": "info",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "humidity", "same_room": True,
        "effect": "Heizkoerper an → trocknet Luft aus",
        "hint": "Heizkoerper → Luftfeuchtigkeit sinkt, ggf. Befeuchter noetig",
        "severity": "info",
    },

    # =================================================================
    # ROLLLADEN / JALOUSIE / MARKISE — Energie / Laerm / Temperatur
    # =================================================================
    {
        "role": "blinds", "state": "closed",
        "affects": "energy", "same_room": True,
        "effect": "Rollladen zu → Waermeisolierung verbessert",
        "hint": "Rollladen zu → weniger Heiz-/Kuehlverlust durch Fenster",
        "severity": "info",
    },
    {
        "role": "blinds", "state": "closed",
        "affects": "noise", "same_room": True,
        "effect": "Rollladen zu → Laermdaemmung verbessert",
        "hint": "Rollladen zu → weniger Aussenlaerm",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "closed",
        "affects": "energy", "same_room": True,
        "effect": "Rollladen/Shutter zu → Waermeisolierung verbessert",
        "hint": "Rollladen zu → Energieeinsparung bei Heizung/Kuehlung",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "closed",
        "affects": "noise", "same_room": True,
        "effect": "Rollladen/Shutter zu → Laermdaemmung",
        "hint": "Rollladen zu → deutlich leiser im Raum",
        "severity": "info",
    },
    {
        "role": "awning", "state": "open",
        "affects": "light_level", "same_room": True,
        "effect": "Markise ausgefahren → weniger Sonneneinstrahlung",
        "hint": "Markise → Beschattung, weniger Blendung",
        "severity": "info",
    },
    {
        "role": "awning", "state": "open",
        "affects": "energy", "same_room": True,
        "effect": "Markise ausgefahren → Kuehlung wird entlastet",
        "hint": "Markise → weniger Sonnenhitze, Klima spart Energie",
        "severity": "info",
    },

    # =================================================================
    # WETTER → erweiterte Geraete-Beziehungen
    # =================================================================
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "heating", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Heizbedarf",
        "hint": "Kalt draussen → Heizung muss mehr arbeiten",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "cooling", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Kuehlbedarf",
        "hint": "Heiss draussen → Kuehlung muss mehr arbeiten",
        "severity": "info",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Kaelte beeinflusst E-Auto-Laden",
        "hint": "Frost → Batterie laedt langsamer, Vorkonditionierung noetig",
        "severity": "info",
    },
    {
        "role": "rain", "state": "on",
        "affects": "garage_door", "same_room": False,
        "effect": "Regen → Garagentor schliessen",
        "hint": "Regen → Garage schliessen gegen Naesse",
        "severity": "info",
    },
    {
        "role": "rain", "state": "on",
        "affects": "gate", "same_room": False,
        "effect": "Regen → Tor schliessen",
        "hint": "Regen → Tor zu, Einfahrt schuetzen",
        "severity": "info",
    },
    {
        "role": "wind_speed", "state": "on",
        "affects": "garage_door", "same_room": False,
        "effect": "Starker Wind → Garagentor sichern",
        "hint": "Sturm → Garagentor schliessen",
        "severity": "info",
    },
    {
        "role": "wind_speed", "state": "on",
        "affects": "gate", "same_room": False,
        "effect": "Starker Wind → Tor sichern",
        "hint": "Sturm → Tor schliessen gegen Windschaden",
        "severity": "info",
    },
    {
        "role": "dew_point", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Taupunkt erreicht → Kondensation an Fenstern",
        "hint": "Taupunkt → Fenster besser zu, sonst Kondenswasser/Schimmel",
        "severity": "info",
    },
    {
        "role": "soil_moisture", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Bodenfeuchte beeinflusst Bewaesserung",
        "hint": "Boden feucht genug → Bewaesserung nicht noetig",
        "severity": "info",
    },
    {
        "role": "water_temp", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Wassertemperatur beeinflusst Waermepumpe",
        "hint": "Warmwasser-Temperatur → Waermepumpe regelt nach",
        "severity": "info",
    },

    # =================================================================
    # SCENE / TIMER / AUTOMATION → Geraete-Steuerung
    # =================================================================
    {
        "role": "scene", "state": "on",
        "affects": "shutter", "same_room": True,
        "effect": "Szene aktiviert → Rollladen werden gesteuert",
        "hint": "Szene → Rollladen-Position wird angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "tv", "same_room": True,
        "effect": "Szene aktiviert → TV wird gesteuert",
        "hint": "Szene → TV an/aus je nach Szene",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "speaker", "same_room": True,
        "effect": "Szene aktiviert → Lautsprecher wird gesteuert",
        "hint": "Szene → Musik/Lautstaerke angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Szene aktiviert → Ventilator wird gesteuert",
        "hint": "Szene → Ventilator an/aus",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "color_light", "same_room": True,
        "effect": "Szene aktiviert → Farblichter werden gesetzt",
        "hint": "Szene → Ambiente-Beleuchtung angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "dimmer", "same_room": True,
        "effect": "Szene aktiviert → Dimmer wird gesetzt",
        "hint": "Szene → Helligkeit angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "heating", "same_room": True,
        "effect": "Szene aktiviert → Heizung wird angepasst",
        "hint": "Szene → Heizung auf Szene-Temperatur",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "cooling", "same_room": True,
        "effect": "Szene aktiviert → Kuehlung wird angepasst",
        "hint": "Szene → Kuehlung auf Szene-Temperatur",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Szene aktiviert → Medien werden gesteuert",
        "hint": "Szene → Medienwiedergabe angepasst",
        "severity": "info",
    },
    {
        "role": "scene", "state": "on",
        "affects": "curtain", "same_room": True,
        "effect": "Szene aktiviert → Vorhaenge werden gesteuert",
        "hint": "Szene → Vorhaenge auf/zu je nach Szene",
        "severity": "info",
    },
    # Timer → Geraete
    {
        "role": "timer", "state": "off",
        "affects": "heating", "same_room": True,
        "effect": "Timer abgelaufen → Heizung anpassen",
        "hint": "Timer → Heizung ein/ausschalten nach Zeitplan",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "cooling", "same_room": True,
        "effect": "Timer abgelaufen → Kuehlung anpassen",
        "hint": "Timer → Kuehlung nach Zeitplan",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "irrigation", "same_room": False,
        "effect": "Timer abgelaufen → Bewaesserung starten/stoppen",
        "hint": "Timer → Bewaesserung nach Zeitplan",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "blinds", "same_room": True,
        "effect": "Timer abgelaufen → Rollladen anpassen",
        "hint": "Timer → Rollladen nach Zeitplan hoch/runter",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "shutter", "same_room": True,
        "effect": "Timer abgelaufen → Rollladen/Shutter anpassen",
        "hint": "Timer → Rollladen nach Zeitplan",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "ev_charger", "same_room": False,
        "effect": "Timer abgelaufen → Laden starten/stoppen",
        "hint": "Timer → E-Auto nach Stromtarif-Zeitplan laden",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "boiler", "same_room": False,
        "effect": "Timer abgelaufen → Boiler an/aus",
        "hint": "Timer → Boiler nach Zeitplan steuern",
        "severity": "info",
    },
    {
        "role": "timer", "state": "off",
        "affects": "ventilation", "same_room": True,
        "effect": "Timer abgelaufen → Lueftung anpassen",
        "hint": "Timer → Lueftung nach Zeitplan",
        "severity": "info",
    },
    # Automation → Geraete
    {
        "role": "automation", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Automation aktiv → steuert Licht",
        "hint": "Automation → Licht wird automatisch gesteuert",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Automation aktiv → steuert Klima",
        "hint": "Automation → Klima wird automatisch geregelt",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Automation aktiv → steuert Rollladen",
        "hint": "Automation → Rollladen automatisch",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Automation aktiv → steuert Alarm",
        "hint": "Automation → Alarm wird automatisch scharf/unscharf",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Automation aktiv → steuert Schloss",
        "hint": "Automation → Tuerschloss automatisch",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Automation aktiv → steuert Kameras",
        "hint": "Automation → Kamera-Aufnahme automatisch",
        "severity": "info",
    },
    {
        "role": "automation", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Automation aktiv → steuert Bewaesserung",
        "hint": "Automation → Bewaesserung automatisch nach Plan",
        "severity": "info",
    },

    # =================================================================
    # TÜRKLINGEL / INTERCOM / TELEFON — Interaktionen
    # =================================================================
    {
        "role": "intercom", "state": "on",
        "affects": "door_contact", "same_room": False,
        "effect": "Intercom → Tuer wird evtl. geoeffnet",
        "hint": "Intercom-Oeffnung → Tuer geht auf",
        "severity": "info",
    },
    {
        "role": "phone", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Telefonat → Laerm reduzieren",
        "hint": "Telefonat → alle Laermquellen leiser/aus",
        "severity": "info",
    },

    # =================================================================
    # WEITERE FEHLENDE BEZIEHUNGEN
    # =================================================================
    # Batterie niedrig → Warnung
    {
        "role": "battery", "state": "on",
        "affects": "lock", "same_room": True,
        "effect": "Batterie niedrig → Smart-Lock Batterie pruefen",
        "hint": "Batterie fast leer → Schloss-Batterie tauschen bevor es ausfaellt!",
        "severity": "high",
        "exclude_entity_patterns": ["klingel", "doorbell", "turklingel"],
    },
    {
        "role": "battery", "state": "on",
        "affects": "camera", "same_room": True,
        "effect": "Batterie niedrig → Kamera-Batterie pruefen",
        "hint": "Batterie fast leer → Kamera-Akku laden/tauschen!",
        "severity": "high",
        "exclude_entity_patterns": ["klingel", "doorbell", "turklingel"],
    },
    # Schloss → Anwesenheit
    {
        "role": "lock", "state": "unlocked",
        "affects": "presence", "same_room": False,
        "effect": "Schloss entriegelt → jemand kommt/geht",
        "hint": "Tuer wird aufgeschlossen → Anwesenheit pruefen",
        "severity": "info",
    },
    # Licht → Energie / Waerme
    {
        "role": "light", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Licht an → erzeugt leichte Waerme",
        "hint": "Licht → minimale Abwaerme (bei Gluehbirnen mehr)",
        "severity": "info",
    },
    # Licht → Kamera (bessere Sicht)
    # Bett → Telefon
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "phone", "same_room": True,
        "effect": "Im Bett → Telefon auf Nachtmodus",
        "hint": "Schlafenszeit → Telefon auf leise/DND",
        "severity": "info",
    },
    # Stuhl → PC / Ventilator / Energie
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "pc", "same_room": True,
        "effect": "Am Schreibtisch → PC relevant",
        "hint": "Arbeitsplatz besetzt → PC/Monitor bereit",
        "severity": "info",
    },
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Am Schreibtisch → Ventilator sinnvoll",
        "hint": "Arbeitsplatz besetzt → Ventilator an bei Waerme",
        "severity": "info",
    },
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Arbeitsplatz besetzt → Energieverbrauch steigt",
        "hint": "Arbeiten → PC, Monitor, Licht = mehr Strom",
        "severity": "info",
    },
    # Connectivity → Automation / Media
    {
        "role": "connectivity", "state": "off",
        "affects": "automation", "same_room": False,
        "effect": "Verbindung weg → Automationen offline",
        "hint": "Verbindung unterbrochen → Cloud-Automationen funktionieren nicht",
        "severity": "high",
    },
    {
        "role": "connectivity", "state": "off",
        "affects": "media_player", "same_room": False,
        "effect": "Verbindung weg → Streaming unterbrochen",
        "hint": "Verbindung weg → kein Streaming, nur lokale Medien",
        "severity": "info",
    },
    # Auto-Standort → Licht / Alarm
    {
        "role": "car_location", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Auto naehert sich → Willkommenslicht",
        "hint": "Auto kommt nach Hause → Einfahrt/Eingang beleuchten",
        "severity": "info",
    },
    {
        "role": "car_location", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Auto-Standort → Alarm anpassen",
        "hint": "Auto zuhause/weg → Alarm entsprechend scharf/unscharf",
        "severity": "info",
    },
    # EV Charger → Solar-Eigenverbrauch
    {
        "role": "ev_charger", "state": "on",
        "affects": "solar", "same_room": False,
        "effect": "Wallbox laedt → Solar-Eigenverbrauch steigt",
        "hint": "E-Auto laden → nutzt Solarstrom optimal",
        "severity": "info",
    },
    # Car battery → EV Charger
    # Running → Energy
    # Update → Automation
    # Problem → Automation

    # ============================================================
    # 43. MAEHROBOTER / ROBOT MOWER
    # ============================================================
    # Robot Mower ON → Bewegungsmelder (Fehlalarme)
    {
        "role": "robot_mower", "state": "on",
        "affects": "motion", "same_room": False,
        "effect": "Maehroboter aktiv → Bewegungsmelder kann ausloesen",
        "hint": "Maehroboter faehrt im Garten → Bewegungsmelder-Alarme ignorieren",
        "severity": "high",
    },
    # Robot Mower ON → Alarm (Fehlausloesung)
    {
        "role": "robot_mower", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Maehroboter aktiv → Alarm koennte ausloesen",
        "hint": "Maehroboter bewegt sich → Alarm-Fehlausloesung moeglich wenn scharf",
        "severity": "critical",
    },
    # Robot Mower ON → Laerm/Geraeusch
    {
        "role": "robot_mower", "state": "on",
        "affects": "noise", "same_room": False,
        "effect": "Maehroboter aktiv → Geraeuschpegel steigt",
        "hint": "Maehroboter laeuft → Laerm im Garten beachten (Ruhezeiten)",
        "severity": "info",
    },
    # Robot Mower ON → Regen (stoppen bei Regen)
    {
        "role": "robot_mower", "state": "on",
        "affects": "rain", "same_room": False,
        "effect": "Maehroboter aktiv → bei Regen zurueck zur Station",
        "hint": "Maehroboter maehen bei Regen → Rasen wird beschaedigt, zurueckrufen",
        "severity": "high",
    },
    # Rain → Robot Mower (inverse: Regen stoppt Maeher)
    {
        "role": "rain", "state": "on",
        "affects": "robot_mower", "same_room": False,
        "effect": "Regen erkannt → Maehroboter sollte stoppen",
        "hint": "Regen → Maehroboter zurueck zur Ladestation schicken",
        "severity": "high",
    },
    # Robot Mower ON → Energie
    {
        "role": "robot_mower", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Maehroboter laedt → Stromverbrauch steigt",
        "hint": "Maehroboter an Ladestation → erhoehter Energieverbrauch",
        "severity": "info",
    },
    # Robot Mower ON → Schlaf (nicht mähen wenn geschlafen wird)
    {
        "role": "robot_mower", "state": "on",
        "affects": "bed_occupancy", "same_room": False,
        "effect": "Maehroboter aktiv → Schlaf koennte gestoert werden",
        "hint": "Maehroboter laeuft → wenn jemand schlaeft, Laerm vermeiden",
        "severity": "high",
    },
    # Robot Mower ON → Gartenbeleuchtung
    {
        "role": "robot_mower", "state": "on",
        "affects": "garden_light", "same_room": False,
        "effect": "Maehroboter aktiv → Gartenbeleuchtung beachten",
        "hint": "Maehroboter unterwegs → Gartenlichter koennen Sensoren verwirren",
        "severity": "info",
    },
    # Robot Mower ON → Bewaesserung (nicht gleichzeitig)
    {
        "role": "robot_mower", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Maehroboter aktiv → Bewaesserung pausieren",
        "hint": "Maehroboter maehen → Bewaesserung gleichzeitig vermeiden",
        "severity": "high",
    },
    # Irrigation ON → Robot Mower (inverse)
    {
        "role": "irrigation", "state": "on",
        "affects": "robot_mower", "same_room": False,
        "effect": "Bewaesserung aktiv → Maehroboter nicht starten",
        "hint": "Rasen wird bewaessert → Maehroboter warten lassen bis trocken",
        "severity": "high",
    },
    # Robot Mower OFF/Docked → Bewegungsmelder wieder normal
    {
        "role": "robot_mower", "state": "off",
        "affects": "motion", "same_room": False,
        "effect": "Maehroboter in Station → Bewegungsmelder wieder zuverlaessig",
        "hint": "Maehroboter geparkt → Garten-Bewegungsmelder normal auswerten",
        "severity": "info",
    },
    # Robot Mower OFF → Alarm wieder normal
    {
        "role": "robot_mower", "state": "off",
        "affects": "alarm", "same_room": False,
        "effect": "Maehroboter in Station → Alarm wieder zuverlaessig",
        "hint": "Maehroboter geparkt → Alarm-System wieder normal",
        "severity": "info",
    },
    # Robot Mower OFF → Bewaesserung freigeben
    {
        "role": "robot_mower", "state": "off",
        "affects": "irrigation", "same_room": False,
        "effect": "Maehroboter in Station → Bewaesserung wieder moeglich",
        "hint": "Maehroboter fertig → Bewaesserung kann starten",
        "severity": "info",
    },

    # ============================================================
    # 44. KAMIN / FIREPLACE
    # ============================================================
    # Fireplace ON → Rauchmelder (kann ausloesen)
    {
        "role": "fireplace", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "Kamin brennt → Rauchmelder koennte ausloesen",
        "hint": "Kamin/Ofen an → Rauchmelder-Empfindlichkeit im Raum beachten",
        "severity": "critical",
    },
    # Fireplace ON → CO-Melder (Vergiftungsgefahr!)
    {
        "role": "fireplace", "state": "on",
        "affects": "co", "same_room": True,
        "effect": "Kamin brennt → CO-Werte ueberwachen!",
        "hint": "Kamin/Ofen aktiv → CO-Melder MUSS aktiv sein, Vergiftungsgefahr!",
        "severity": "critical",
    },
    # Fireplace ON → Lueftung/Abzug (Kaminzug braucht Frischluft)
    {
        "role": "fireplace", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Kamin brennt → Lueftung beachten (Kaminzug)",
        "hint": "Kamin aktiv → Dunstabzug AUS (stoert Kaminzug!), Zuluft sichern",
        "severity": "critical",
    },
    # Fireplace ON → Fenster (Frischluftzufuhr)
    {
        "role": "fireplace", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "Kamin brennt → Fenster fuer Frischluftzufuhr",
        "hint": "Kamin/Ofen aktiv → Fenster leicht oeffnen fuer Frischluftzufuhr",
        "severity": "high",
    },
    # Fireplace ON → Heizung (Raumtemperatur steigt)
    {
        "role": "fireplace", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Kamin brennt → Raum wird gewaermt",
        "hint": "Kamin/Ofen heizt → Heizung/Thermostat im Raum reduzieren",
        "severity": "high",
    },
    # Fireplace ON → Raumtemperatur
    {
        "role": "fireplace", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Kamin brennt → Temperatur steigt stark",
        "hint": "Kamin aktiv → Raumtemperatur steigt deutlich, Thermostat anpassen",
        "severity": "high",
    },
    # Fireplace ON → Luftqualitaet
    {
        "role": "fireplace", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "Kamin brennt → Feinstaub/Partikel im Raum",
        "hint": "Kamin/Ofen aktiv → Luftqualitaet verschlechtert sich, lueften",
        "severity": "high",
    },
    # Fireplace ON → Energie (Holz/Gas statt Strom)
    {
        "role": "fireplace", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Kamin brennt → alternative Heizquelle aktiv",
        "hint": "Kamin heizt → Stromheizung reduzierbar, Energiemix beachten",
        "severity": "info",
    },
    # Fireplace ON → Alarm
    {
        "role": "fireplace", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Kamin brennt → Brandmelder koennte ausloesen",
        "hint": "Kamin aktiv → Rauch-/Brandmelder Fehlalarme moeglich",
        "severity": "high",
    },
    # Fireplace ON → Presence (nie unbeaufsichtigt)
    {
        "role": "fireplace", "state": "on",
        "affects": "presence", "same_room": True,
        "effect": "Kamin brennt → nicht unbeaufsichtigt lassen!",
        "hint": "Kamin/Ofen aktiv → jemand MUSS im Haus sein, Brandgefahr!",
        "severity": "critical",
    },
    # Fireplace OFF → Raumtemperatur sinkt
    {
        "role": "fireplace", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Kamin aus → Temperatur sinkt langsam",
        "hint": "Kamin erloschen → Raum kuehlt ab, Heizung wieder hochfahren",
        "severity": "info",
    },
    # Fireplace OFF → Luftqualitaet erholt sich
    {
        "role": "fireplace", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "Kamin aus → Luftqualitaet verbessert sich",
        "hint": "Kamin erloschen → gut lueften, Feinstaub abtransportieren",
        "severity": "info",
    },
    # Fireplace OFF → Rauchmelder normal
    {
        "role": "fireplace", "state": "off",
        "affects": "smoke", "same_room": True,
        "effect": "Kamin aus → Rauchmelder wieder normal",
        "hint": "Kamin erloschen → Rauchmelder wieder zuverlaessig",
        "severity": "info",
    },
    # Fireplace OFF → Lueftung normal
    {
        "role": "fireplace", "state": "off",
        "affects": "ventilation", "same_room": True,
        "effect": "Kamin aus → Lueftung wieder normal betreibbar",
        "hint": "Kamin erloschen → Dunstabzug/Lueftung wieder nutzbar",
        "severity": "info",
    },
    # Fireplace ON → Radiator/Heating (Parity)
    {
        "role": "fireplace", "state": "on",
        "affects": "radiator", "same_room": True,
        "effect": "Kamin brennt → Heizkoerper runterdrehen",
        "hint": "Kamin heizt den Raum → Heizkoerper reduzieren spart Energie",
        "severity": "high",
    },
    {
        "role": "fireplace", "state": "on",
        "affects": "floor_heating", "same_room": True,
        "effect": "Kamin brennt → Fussbodenheizung reduzieren",
        "hint": "Kamin heizt → Fussbodenheizung im Raum drosseln",
        "severity": "high",
    },
    {
        "role": "fireplace", "state": "on",
        "affects": "heating", "same_room": True,
        "effect": "Kamin brennt → Heizung reduzieren",
        "hint": "Kamin heizt → Heizung im Raum runterregeln",
        "severity": "high",
    },

    # ============================================================
    # 45. SAUNA
    # ============================================================
    # Sauna ON → Energie (6-10 kW!)
    {
        "role": "sauna", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Sauna an → extremer Stromverbrauch (6-10 kW!)",
        "hint": "Sauna heizt auf → 6-10 kW Verbrauch! Andere Grossverbraucher verschieben",
        "severity": "critical",
    },
    # Sauna ON → Netzverbrauch
    {
        "role": "sauna", "state": "on",
        "affects": "grid_consumption", "same_room": False,
        "effect": "Sauna an → Netzverbrauch steigt massiv",
        "hint": "Sauna → massiver Netzstrom-Verbrauch, ideal bei Solarueberschuss starten",
        "severity": "high",
    },
    # Sauna ON → Raumtemperatur (Umgebung heizt mit)
    {
        "role": "sauna", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Sauna an → Umgebungstemperatur steigt",
        "hint": "Sauna heizt → benachbarter Raum wird waermer, Thermostat anpassen",
        "severity": "high",
    },
    # Sauna ON → Klima/Thermostat
    {
        "role": "sauna", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Sauna an → Klima im Raum anpassen",
        "hint": "Sauna aktiv → Thermostat im Saunaraum anpassen",
        "severity": "high",
    },
    # Sauna ON → Luftfeuchtigkeit (extrem hoch)
    {
        "role": "sauna", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Sauna an → Luftfeuchtigkeit steigt extrem",
        "hint": "Sauna aktiv → Luftfeuchtigkeit extrem hoch, nach Sitzung lueften!",
        "severity": "high",
    },
    # Sauna ON → Lueftung (danach wichtig)
    {
        "role": "sauna", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "Sauna an → Lueftung nach Sitzung wichtig",
        "hint": "Sauna laeuft → nach dem Saunagang gut lueften, Schimmelgefahr",
        "severity": "high",
    },
    # Sauna ON → Rauchmelder (Dampf kann ausloesen)
    {
        "role": "sauna", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "Sauna an → Dampf kann Rauchmelder ausloesen",
        "hint": "Sauna/Dampf → Rauchmelder-Fehlalarm moeglich",
        "severity": "high",
    },
    # Sauna ON → Wasserverbrauch (Aufguss)
    {
        "role": "sauna", "state": "on",
        "affects": "water_consumption", "same_room": False,
        "effect": "Sauna an → Wasserverbrauch fuer Aufguss/Abkuehlung",
        "hint": "Sauna aktiv → Wasserverbrauch durch Aufguss und Dusche beachten",
        "severity": "info",
    },
    # Sauna ON → Licht (Saunabeleuchtung)
    {
        "role": "sauna", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Sauna an → Saunabeleuchtung einschalten",
        "hint": "Sauna aktiv → gedimmtes Saunalicht einschalten, Entspannung",
        "severity": "info",
    },
    # Sauna ON → Presence (nie unbeaufsichtigt)
    {
        "role": "sauna", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Sauna an → jemand muss im Haus sein",
        "hint": "Sauna laeuft → Person MUSS im Haus sein, Gesundheitsrisiko!",
        "severity": "critical",
    },
    # Sauna OFF → Energie normalisiert
    {
        "role": "sauna", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Sauna aus → Stromverbrauch sinkt deutlich",
        "hint": "Sauna beendet → 6-10 kW weniger Verbrauch",
        "severity": "info",
    },
    # Sauna OFF → Lueftung starten
    {
        "role": "sauna", "state": "off",
        "affects": "ventilation", "same_room": True,
        "effect": "Sauna aus → jetzt lueften!",
        "hint": "Sauna beendet → Lueftung einschalten, Feuchtigkeit abfuehren",
        "severity": "high",
    },
    # Sauna OFF → Raumtemperatur sinkt
    {
        "role": "sauna", "state": "off",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Sauna aus → Umgebungstemperatur normalisiert sich",
        "hint": "Sauna beendet → Raumtemperatur sinkt wieder auf Normal",
        "severity": "info",
    },

    # ============================================================
    # 46. AQUARIUM
    # ============================================================
    # Aquarium ON → Energie (Dauerbetrieb: Pumpe, Heizung, Licht)
    {
        "role": "aquarium", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Aquarium aktiv → konstanter Stromverbrauch",
        "hint": "Aquarium-Equipment (Pumpe/Heizung/Licht) → dauerhafter Grundverbrauch",
        "severity": "info",
    },
    # Aquarium ON → Wasserleck (Risiko)
    {
        "role": "aquarium", "state": "on",
        "affects": "water_leak", "same_room": True,
        "effect": "Aquarium aktiv → Wasserleck-Risiko",
        "hint": "Aquarium im Raum → Wassersensor ist kritisch wichtig!",
        "severity": "critical",
    },
    # Water Leak → Aquarium (bidirektional)
    {
        "role": "water_leak", "state": "on",
        "affects": "aquarium", "same_room": True,
        "effect": "Wasserleck erkannt → Aquarium pruefen!",
        "hint": "Wasserleck im Aquarium-Raum → sofort Aquarium und Schlaeuche pruefen!",
        "severity": "critical",
    },
    # Aquarium ON → Raumtemperatur (Aquarienheizung waermt mit)
    {
        "role": "aquarium", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "Aquarium → leichte Erwaermung des Raums",
        "hint": "Aquarium-Heizung → Raum wird minimal waermer, Thermostat beachten",
        "severity": "info",
    },
    # Aquarium ON → Luftfeuchtigkeit (Verdunstung)
    {
        "role": "aquarium", "state": "on",
        "affects": "humidity", "same_room": True,
        "effect": "Aquarium → Verdunstung erhoeht Luftfeuchtigkeit",
        "hint": "Aquarium offen → Luftfeuchtigkeit steigt, gut lueften",
        "severity": "info",
    },
    # Aquarium ON → Geraeusch (Pumpe/Filter)
    {
        "role": "aquarium", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "Aquarium-Pumpe → Grundgeraeusch im Raum",
        "hint": "Aquarium-Filter/Pumpe → Hintergrundgeraeusch beachten",
        "severity": "info",
    },
    # Aquarium Problem → Notify (Fische in Gefahr!)
    {
        "role": "aquarium", "state": "problem",
        "affects": "notify", "same_room": False,
        "effect": "Aquarium-Problem → Fische in Gefahr!",
        "hint": "Aquarium Stoerung → SOFORT pruefen! Fische koennten sterben!",
        "severity": "critical",
    },
    # Aquarium OFF → Notify (Ausfall ist kritisch!)
    {
        "role": "aquarium", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Aquarium aus → KRITISCH! Pumpe/Heizung ausgefallen!",
        "hint": "Aquarium-Equipment AUS → Lebensbedrohlich fuer Fische! Sofort handeln!",
        "severity": "critical",
    },
    # Aquarium ON → Wassertemperatur
    {
        "role": "aquarium", "state": "on",
        "affects": "water_temp", "same_room": True,
        "effect": "Aquarium → Wassertemperatur muss stabil bleiben",
        "hint": "Aquarium aktiv → Wassertemperatur ueberwachen (24-26°C typisch)",
        "severity": "high",
    },
    # Indoor Temp → Aquarium (Raumtemperatur beeinflusst Wassertemp)
    {
        "role": "indoor_temp", "state": "on",
        "affects": "aquarium", "same_room": True,
        "effect": "Raumtemperatur-Aenderung → Aquarium-Wassertemp beachten",
        "hint": "Raumtemperatur aendert sich → Aquarium-Heizung muss kompensieren",
        "severity": "info",
    },

    # ============================================================
    # 47. 3D-DRUCKER / 3D PRINTER
    # ============================================================
    # 3D Printer ON → Luftqualitaet (VOC/Feinstaub!)
    {
        "role": "3d_printer", "state": "on",
        "affects": "air_quality", "same_room": True,
        "effect": "3D-Drucker druckt → VOC und Feinstaub!",
        "hint": "3D-Drucker aktiv → VOC/Partikel freigesetzt! Lueftung MUSS laufen!",
        "severity": "critical",
    },
    # 3D Printer ON → Lueftung (MUSS laufen!)
    {
        "role": "3d_printer", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "3D-Drucker druckt → Lueftung erforderlich",
        "hint": "3D-Drucker aktiv → Absaugung/Lueftung einschalten, VOC gefaehrlich!",
        "severity": "critical",
    },
    # 3D Printer ON → Fenster (Lueftung sicherstellen)
    {
        "role": "3d_printer", "state": "on",
        "affects": "window_contact", "same_room": True,
        "effect": "3D-Drucker druckt → Fenster fuer Frischluft",
        "hint": "3D-Drucker laeuft → Fenster oeffnen fuer Frischluft (VOC!)",
        "severity": "high",
    },
    # 3D Printer ON → Energie
    {
        "role": "3d_printer", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "3D-Drucker druckt → Stromverbrauch steigt",
        "hint": "3D-Drucker aktiv → 200-500W Verbrauch fuer Stunden",
        "severity": "info",
    },
    # 3D Printer ON → Laerm
    {
        "role": "3d_printer", "state": "on",
        "affects": "noise", "same_room": True,
        "effect": "3D-Drucker druckt → Geraeuschpegel steigt",
        "hint": "3D-Drucker laeuft → Motoren/Luefter verursachen Laerm",
        "severity": "info",
    },
    # 3D Printer ON → Rauchmelder (Brandgefahr!)
    {
        "role": "3d_printer", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "3D-Drucker druckt → Brandrisiko bei Fehlfunktion",
        "hint": "3D-Drucker aktiv → Rauchmelder MUSS aktiv sein, Brandgefahr!",
        "severity": "critical",
    },
    # 3D Printer ON → Raumtemperatur
    {
        "role": "3d_printer", "state": "on",
        "affects": "indoor_temp", "same_room": True,
        "effect": "3D-Drucker druckt → Raum wird waermer",
        "hint": "3D-Drucker Heizbett/Hotend → Raum heizt sich auf (bis +3°C)",
        "severity": "info",
    },
    # 3D Printer ON → Presence (Brandrisiko unbeaufsichtigt!)
    {
        "role": "3d_printer", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "3D-Drucker druckt → nicht lange unbeaufsichtigt lassen",
        "hint": "3D-Drucker laeuft → Brandgefahr! Regelmaessig kontrollieren!",
        "severity": "high",
    },
    # 3D Printer ON → Luefter/Fan
    {
        "role": "3d_printer", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "3D-Drucker druckt → Raumluefter einschalten",
        "hint": "3D-Drucker aktiv → Luefter fuer Abluft nutzen (VOC-Reduktion)",
        "severity": "high",
    },
    # 3D Printer OFF → Energie normal
    {
        "role": "3d_printer", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "3D-Drucker fertig → Stromverbrauch sinkt",
        "hint": "3D-Druck beendet → Energieverbrauch normalisiert",
        "severity": "info",
    },
    # 3D Printer OFF → Luftqualitaet erholt sich
    {
        "role": "3d_printer", "state": "off",
        "affects": "air_quality", "same_room": True,
        "effect": "3D-Drucker aus → Luftqualitaet verbessert sich",
        "hint": "3D-Druck beendet → weiter lueften bis VOC-Werte normal",
        "severity": "info",
    },
    # 3D Printer OFF → Geraeusch normal
    {
        "role": "3d_printer", "state": "off",
        "affects": "noise", "same_room": True,
        "effect": "3D-Drucker aus → Geraeuschpegel sinkt",
        "hint": "3D-Druck beendet → Raum wieder leise",
        "severity": "info",
    },

    # ============================================================
    # 48. HEIZDECKE / ELECTRIC BLANKET
    # ============================================================
    # Electric Blanket ON → Bettbelegung
    {
        "role": "electric_blanket", "state": "on",
        "affects": "bed_occupancy", "same_room": True,
        "effect": "Heizdecke an → Bett wird vorgewaermt",
        "hint": "Heizdecke aktiv → Bett wird vorgeheizt, Schlafkomfort verbessert",
        "severity": "info",
    },
    # Electric Blanket ON → Energie
    {
        "role": "electric_blanket", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Heizdecke an → Stromverbrauch steigt",
        "hint": "Heizdecke aktiv → 50-200W Verbrauch",
        "severity": "info",
    },
    # Electric Blanket ON → Presence (Brandgefahr unbeaufsichtigt!)
    {
        "role": "electric_blanket", "state": "on",
        "affects": "presence", "same_room": False,
        "effect": "Heizdecke an → nicht unbeaufsichtigt lassen!",
        "hint": "Heizdecke laeuft → Brandgefahr! Nach 30min automatisch abschalten!",
        "severity": "high",
    },
    # Electric Blanket ON → Rauchmelder (Brandgefahr)
    {
        "role": "electric_blanket", "state": "on",
        "affects": "smoke", "same_room": True,
        "effect": "Heizdecke an → Brandrisiko bei Fehlfunktion",
        "hint": "Heizdecke aktiv → Rauchmelder muss funktionieren, Brandgefahr!",
        "severity": "high",
    },
    # Electric Blanket ON → Klima/Thermostat
    {
        "role": "electric_blanket", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Heizdecke an → Raumheizung kann reduziert werden",
        "hint": "Heizdecke waermt Bett → Schlafzimmer-Heizung absenken moeglich",
        "severity": "info",
    },
    # Electric Blanket ON → Heizung (Parity)
    {
        "role": "electric_blanket", "state": "on",
        "affects": "radiator", "same_room": True,
        "effect": "Heizdecke an → Heizkoerper reduzieren",
        "hint": "Heizdecke waermt → Heizkoerper im Schlafzimmer runterdrehen",
        "severity": "info",
    },
    {
        "role": "electric_blanket", "state": "on",
        "affects": "floor_heating", "same_room": True,
        "effect": "Heizdecke an → Fussbodenheizung reduzieren",
        "hint": "Heizdecke waermt → Fussbodenheizung nachts reduzierbar",
        "severity": "info",
    },
    {
        "role": "electric_blanket", "state": "on",
        "affects": "heating", "same_room": True,
        "effect": "Heizdecke an → Heizung reduzieren",
        "hint": "Heizdecke waermt → Heizung im Schlafzimmer drosseln",
        "severity": "info",
    },
    # Electric Blanket ON → Notify (Abschalt-Erinnerung)
    {
        "role": "electric_blanket", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Heizdecke an → Abschalt-Erinnerung setzen",
        "hint": "Heizdecke laeuft → nach 30-60min Erinnerung zum Abschalten senden!",
        "severity": "high",
    },
    # Electric Blanket OFF → Energie normal
    {
        "role": "electric_blanket", "state": "off",
        "affects": "energy", "same_room": False,
        "effect": "Heizdecke aus → Stromverbrauch sinkt",
        "hint": "Heizdecke ausgeschaltet → Energieverbrauch normalisiert",
        "severity": "info",
    },

    # =================================================================
    # 48. KWL (LUEFTUNGSANLAGE) ALS HEIZ-/KUEHLSYSTEM
    # =================================================================
    # Viele KWL-Anlagen (z.B. Zehnder, Vallox, Helios) koennen ueber
    # Waermetauscher, Nachheizregister oder Sole-EWT aktiv heizen und kuehlen.
    # Diese Abhaengigkeiten fehlen wenn KWL nur als "Lueftung" betrachtet wird.

    # --- KWL HEIZT → Fenster offen = Energieverschwendung ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "window_contact", "same_room": False,
        "effect": "KWL heizt ueber Nachheizregister + Fenster offen → Waerme geht verloren",
        "hint": "KWL heizt → Fenster offen = teure Heizenergie geht raus!",
        "severity": "high",
    },
    # --- KWL KUEHLT → Fenster offen = Energieverschwendung ---
    {
        "role": "ventilation", "state": "cool",
        "affects": "window_contact", "same_room": False,
        "effect": "KWL kuehlt + Fenster offen → kuehle Luft entweicht",
        "hint": "KWL kuehlt → Fenster offen = Kuehlenergie wird verschwendet!",
        "severity": "high",
    },

    # --- KWL HEIZT → Energie ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "energy", "same_room": False,
        "effect": "KWL im Heizmodus → erhoehter Energieverbrauch (Nachheizregister/WP)",
        "hint": "KWL heizt → Stromverbrauch steigt durch Nachheizregister",
        "severity": "info",
    },
    # --- KWL KUEHLT → Energie ---
    {
        "role": "ventilation", "state": "cool",
        "affects": "energy", "same_room": False,
        "effect": "KWL im Kuehlmodus → erhoehter Energieverbrauch",
        "hint": "KWL kuehlt → Stromverbrauch steigt",
        "severity": "info",
    },

    # --- KWL HEIZT + separate Kuehlung = gegeneinander ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "cooling", "same_room": False,
        "effect": "KWL heizt + Klimaanlage kuehlt → arbeiten gegeneinander",
        "hint": "KWL heizt UND Kuehlung laeuft → Energieverschwendung, gegeneinander!",
        "severity": "high",
    },
    # --- KWL KUEHLT + separate Heizung = gegeneinander ---
    {
        "role": "ventilation", "state": "cool",
        "affects": "heating", "same_room": False,
        "effect": "KWL kuehlt + Heizung heizt → arbeiten gegeneinander",
        "hint": "KWL kuehlt UND Heizung laeuft → Energieverschwendung, gegeneinander!",
        "severity": "high",
    },
    # --- KWL KUEHLT + Heizkoerper = gegeneinander ---
    {
        "role": "ventilation", "state": "cool",
        "affects": "radiator", "same_room": False,
        "effect": "KWL kuehlt + Heizkoerper an → arbeiten gegeneinander",
        "hint": "KWL kuehlt UND Heizkoerper an → widerspricht sich!",
        "severity": "high",
    },
    # --- KWL KUEHLT + Fussbodenheizung = gegeneinander ---
    {
        "role": "ventilation", "state": "cool",
        "affects": "floor_heating", "same_room": False,
        "effect": "KWL kuehlt + Fussbodenheizung an → arbeiten gegeneinander",
        "hint": "KWL kuehlt UND Fussbodenheizung heizt → widerspricht sich!",
        "severity": "high",
    },
    # --- KWL HEIZT + Fussbodenheizung = doppelt ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "floor_heating", "same_room": False,
        "effect": "KWL heizt + Fussbodenheizung heizt → ggf. doppelt",
        "hint": "KWL heizt + Fussbodenheizung → doppelte Heizung, Temperatur pruefen",
        "severity": "info",
    },
    # --- KWL HEIZT + Heizkoerper = doppelt ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "radiator", "same_room": False,
        "effect": "KWL heizt + Heizkoerper an → doppelte Heizquelle",
        "hint": "KWL heizt + Heizkoerper → ggf. Heizkoerper runterdrehen",
        "severity": "info",
    },

    # --- KWL HEIZT/KUEHLT → Raumtemperatur ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "indoor_temp", "same_room": False,
        "effect": "KWL heizt → Raumtemperatur steigt ueber Zuluft",
        "hint": "KWL im Heizmodus → Raumtemperatur steigt (ueber warme Zuluft)",
        "severity": "info",
    },
    {
        "role": "ventilation", "state": "cool",
        "affects": "indoor_temp", "same_room": False,
        "effect": "KWL kuehlt → Raumtemperatur sinkt ueber Zuluft",
        "hint": "KWL im Kuehlmodus → Raumtemperatur sinkt (ueber kuehle Zuluft)",
        "severity": "info",
    },

    # --- KWL KUEHLT → Luftfeuchtigkeit / Taupunkt ---
    {
        "role": "ventilation", "state": "cool",
        "affects": "humidity", "same_room": False,
        "effect": "KWL kuehlt → Kondensation moeglich, Luftfeuchtigkeit aendert sich",
        "hint": "KWL kuehlt → Kondensat im Geraet moeglich, Ablauf pruefen",
        "severity": "info",
    },
    {
        "role": "ventilation", "state": "cool",
        "affects": "dew_point", "same_room": False,
        "effect": "KWL kuehlt Zuluft → Taupunkt-Unterschreitung am Auslass moeglich",
        "hint": "KWL Kuehlung → Taupunkt beachten, Kondenswasser an Auslaessen!",
        "severity": "high",
    },

    # --- KWL HEIZT → Luftfeuchtigkeit sinkt ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "humidity", "same_room": False,
        "effect": "KWL heizt Zuluft → trocknet Raumluft aus",
        "hint": "KWL heizt → Luft wird trockener, ggf. Befeuchter noetig",
        "severity": "info",
    },

    # --- KWL HEIZT/KUEHLT → Thermostat (Sollwert-Konflikt) ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "thermostat", "same_room": False,
        "effect": "KWL heizt → Thermostat sieht erhoehte Temperatur, regelt runter",
        "hint": "KWL heizt → Thermostat ggf. runterregeln, Raumthermostat beachten",
        "severity": "info",
    },
    {
        "role": "ventilation", "state": "cool",
        "affects": "thermostat", "same_room": False,
        "effect": "KWL kuehlt → Thermostat sieht niedrigere Temperatur, koennte hochregeln",
        "hint": "KWL kuehlt → Thermostat koennte Heizung anfordern, Regelkonflikte moeglich!",
        "severity": "high",
    },

    # --- KWL HEIZT/KUEHLT + Solar-Ueberschuss ---
    {
        "role": "solar", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "PV-Ueberschuss → KWL Heiz-/Kuehlbetrieb mit Solar betreiben",
        "hint": "Solarueberschuss → KWL Nachheizregister/Kuehlung jetzt nutzen",
        "severity": "info",
    },

    # --- KWL HEIZT/KUEHLT + Waermepumpe ---
    {
        "role": "ventilation", "state": "heat",
        "affects": "heat_pump", "same_room": False,
        "effect": "KWL heizt ueber WP-Anbindung → Waermepumpe liefert Vorlauf",
        "hint": "KWL Heizmodus → Waermepumpe wird als Waermequelle genutzt",
        "severity": "info",
    },
    {
        "role": "ventilation", "state": "cool",
        "affects": "heat_pump", "same_room": False,
        "effect": "KWL kuehlt ueber WP-Anbindung → Waermepumpe im Kuehlbetrieb",
        "hint": "KWL Kuehlmodus → Waermepumpe liefert Kuehlung, Energieverbrauch steigt",
        "severity": "info",
    },

    # --- Heizung/Kuehlung → KWL (inverse: andere Systeme beeinflussen KWL) ---
    {
        "role": "heating", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Heizung laeuft → KWL-Waermerueckgewinnung effektiver",
        "hint": "Heizung an → KWL-WRG nutzt Abluft-Waerme, Effizienz steigt",
        "severity": "info",
    },
    {
        "role": "cooling", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Kuehlung laeuft → KWL sollte nicht gegenheizenl",
        "hint": "Klimaanlage kuehlt → KWL-Nachheizregister muss aus sein!",
        "severity": "info",
    },

    # =================================================================
    # 49. BESCHATTUNG → SOLAR-PV-ERTRAG (Verschattung von Panels)
    # =================================================================

    # Blinds/Jalousie geschlossen → PV-Ertrag kann sinken (Dachfenster-Rollladen)
    {
        "role": "blinds", "state": "closed",
        "affects": "solar", "same_room": False,
        "effect": "Beschattung aktiv → kann PV-Panels verschatten, Ertrag sinkt",
        "hint": "Rollladen/Jalousie zu → PV-Ertrag pruefen, Panels moeglicherweise verschattet",
        "severity": "info",
    },
    {
        "role": "shutter", "state": "closed",
        "affects": "solar", "same_room": False,
        "effect": "Rollladen geschlossen → kann PV-Panels verschatten",
        "hint": "Rollladen zu → PV-Ertrag pruefen, Panels koennten verschattet sein",
        "severity": "info",
    },
    {
        "role": "awning", "state": "open",
        "affects": "solar", "same_room": False,
        "effect": "Markise ausgefahren → kann PV-Panels auf Dach/Terrasse verschatten",
        "hint": "Markise draussen → PV-Ertrag sinkt moeglicherweise durch Verschattung",
        "severity": "info",
    },

    # =================================================================
    # 50. WAERMEPUMPE ↔ FUSSBODENHEIZUNG (direkte Interaktion)
    # =================================================================

    # Waermepumpe → Fussbodenheizung (Vorlauftemperatur)
    {
        "role": "heat_pump", "state": "heat",
        "affects": "floor_heating", "same_room": False,
        "effect": "Waermepumpe heizt → Vorlauftemperatur fuer Fussbodenheizung",
        "hint": "Waermepumpe → steuert Fussbodenheizung ueber Vorlauftemperatur",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "off",
        "affects": "floor_heating", "same_room": False,
        "effect": "Waermepumpe aus → Fussbodenheizung wird kalt (traege, erst nach Stunden)",
        "hint": "Waermepumpe aus → Fussbodenheizung kuehlt langsam ab, Puffer nutzen",
        "severity": "info",
    },
    # Fussbodenheizung → Waermepumpe (Ruecklauftemperatur)
    {
        "role": "floor_heating", "state": "heat",
        "affects": "heat_pump", "same_room": False,
        "effect": "Fussbodenheizung aktiv → Waermepumpe muss Vorlauf liefern",
        "hint": "Fussbodenheizung heizt → Waermepumpe-Effizienz (COP) beachten",
        "severity": "info",
    },

    # =================================================================
    # 51. VORHANG → KLIMA / ENERGIE (Isolation, Kaeltebruecke)
    # =================================================================

    {
        "role": "curtain", "state": "closed",
        "affects": "climate", "same_room": True,
        "effect": "Vorhang zu → isoliert Fenster, weniger Waermeverlust",
        "hint": "Vorhang zu → isoliert gegen Kaelte am Fenster, weniger Heizenergie noetig",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "closed",
        "affects": "energy", "same_room": True,
        "effect": "Vorhang zu → zusaetzliche Isolation, Energieeinsparung",
        "hint": "Vorhang zu → Heiz-/Kuehlverlust reduziert durch Fenster-Isolation",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "closed",
        "affects": "heating", "same_room": True,
        "effect": "Vorhang zu → weniger Heizenergie noetig (Kaeltebruecke reduziert)",
        "hint": "Vorhang vor Fenster → Heizkoerper braucht weniger Leistung",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "closed",
        "affects": "cooling", "same_room": True,
        "effect": "Vorhang zu → weniger Sonneneinstrahlung, Kuehlung entlastet",
        "hint": "Vorhang zu → Sonnenhitze wird geblockt, Klimaanlage arbeitet weniger",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "open",
        "affects": "climate", "same_room": True,
        "effect": "Vorhang offen → Fenster-Kaeltebruecke aktiv, Waermeverlust hoeher",
        "hint": "Vorhang offen → Fenster strahlt Kaelte/Waerme ab, Klima beeinflusst",
        "severity": "info",
    },
    {
        "role": "curtain", "state": "open",
        "affects": "solar", "same_room": False,
        "effect": "Vorhang offen → keine Verschattung, PV-Ertrag nicht beeinflusst",
        "hint": "Vorhang offen → maximales Tageslicht und PV-Ertrag (keine Verschattung)",
        "severity": "info",
    },

    # =================================================================
    # 52. FUSSBODENHEIZUNG + KUEHLUNG = GEGENEINANDER
    # =================================================================

    {
        "role": "floor_heating", "state": "heat",
        "affects": "cooling", "same_room": True,
        "effect": "Fussbodenheizung + Kuehlung gleichzeitig → arbeiten gegeneinander",
        "hint": "Fussbodenheizung UND Kuehlung → Energieverschwendung, gegeneinander!",
        "severity": "high",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "cooling", "same_room": True,
        "effect": "Heizkoerper + Kuehlung gleichzeitig → arbeiten gegeneinander",
        "hint": "Heizkoerper UND Klimaanlage → Energieverschwendung, gegeneinander!",
        "severity": "high",
    },

    # =================================================================
    # 53. SAUNA / WALLBOX / WAERMEPUMPE — NETZUEBERLAST-KOMBINATIONEN
    # =================================================================

    {
        "role": "sauna", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Sauna (6-10kW) + Wallbox (11-22kW) → extreme Netzlast!",
        "hint": "Sauna + Wallbox gleichzeitig → Ueberlastgefahr, Sicherung koennte fliegen!",
        "severity": "high",
    },
    {
        "role": "sauna", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Sauna (6-10kW) + Waermepumpe (2-5kW) → hohe Gesamtlast",
        "hint": "Sauna + Waermepumpe gleichzeitig → hohe Netzlast, Tarif-Spitze beachten",
        "severity": "info",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "sauna", "same_room": False,
        "effect": "Wallbox laedt → Sauna starten = extreme Netzlast",
        "hint": "Wallbox + Sauna → Ueberlastgefahr, nacheinander statt gleichzeitig!",
        "severity": "high",
    },

    # =================================================================
    # 54. DUNSTABZUG / LUEFTUNG ↔ KAMIN (Unterdruck-Gefahr)
    # =================================================================
    # (fireplace → ventilation existiert bereits, aber fan → fireplace fehlt)

    {
        "role": "fan", "state": "on",
        "affects": "fireplace", "same_room": True,
        "effect": "Abluft-Ventilator + Kamin → Unterdruck zieht Rauch ins Haus",
        "hint": "Ventilator/Dunstabzug an + Kamin → GEFAHR, Rauch wird ins Haus gezogen!",
        "severity": "critical",
    },
    {
        "role": "ventilation", "state": "on",
        "affects": "fireplace", "same_room": False,
        "effect": "Lueftungsanlage + Kamin → Unterdruck stoert Kaminzug",
        "hint": "KWL/Lueftung an + Kamin → Unterdruck, Rauch und CO koennen ins Haus!",
        "severity": "critical",
    },

    # =================================================================
    # 55. AQUARIUM ↔ STROMAUSFALL / NETZWERK
    # =================================================================

    {
        "role": "aquarium", "state": "on",
        "affects": "connectivity", "same_room": False,
        "effect": "Aquarium → bei Stromausfall/Offline sterben Fische",
        "hint": "Aquarium → Strom-/Netzwerk-Unterbrechung kritisch fuer Fische!",
        "severity": "high",
    },
    {
        "role": "connectivity", "state": "off",
        "affects": "aquarium", "same_room": False,
        "effect": "Verbindung verloren → Aquarium-Steuerung moeglicherweise offline",
        "hint": "Netzwerk offline → Aquarium-Filter/Heizung/Licht pruefen!",
        "severity": "high",
    },

    # =================================================================
    # 56. HEIZDECKE + ABWESENHEIT (Brandgefahr — inverse Richtung)
    # =================================================================

    {
        "role": "presence", "state": "off",
        "affects": "electric_blanket", "same_room": False,
        "effect": "Alle weg + Heizdecke an → Brandgefahr",
        "hint": "Alle weg + Heizdecke noch an → AUSSCHALTEN, Brandgefahr!",
        "severity": "critical",
    },

    # =================================================================
    # 59. WAERMEPUMPE KUEHLEN → FUSSBODENHEIZUNG (Kuehlbetrieb)
    # =================================================================

    {
        "role": "heat_pump", "state": "cool",
        "affects": "floor_heating", "same_room": False,
        "effect": "Waermepumpe kuehlt → Fussbodenheizung wird zur Flaechenkuehlung",
        "hint": "Waermepumpe kuehlt → Fussbodenheizung als Flaechenkuehlung, Taupunkt beachten!",
        "severity": "info",
    },
    {
        "role": "heat_pump", "state": "cool",
        "affects": "humidity", "same_room": False,
        "effect": "Waermepumpe kuehlt via Fussboden → Kondensation/Taupunkt-Gefahr",
        "hint": "Flaechenkuehlung via Fussboden → Taupunkt beachten, Kondenswasser vermeiden!",
        "severity": "high",
    },

    # =================================================================
    # 60. CURTAIN ↔ KAMERA (Privatsphaere / Sicht)
    # =================================================================

    {
        "role": "curtain", "state": "open",
        "affects": "camera", "same_room": True,
        "effect": "Vorhang offen → Raum von aussen einsehbar, Kamera sieht mehr",
        "hint": "Vorhang offen → Aussen-Kamera sieht durch Fenster, Innen-Privatsphaere beachten",
        "severity": "info",
    },

    # =================================================================
    # 61. WALLBOX + WAERMEPUMPE + SAUNA — Dreifach-Ueberlast
    # =================================================================

    {
        "role": "heat_pump", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Waermepumpe + Wallbox gleichzeitig → hohe Netzlast",
        "hint": "Waermepumpe + Wallbox → Netzlast hoch, Tarif-Spitze beachten",
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
                    "severity": dep.get("severity", "info"),
                })
        return conflicts

    # Severity-Rangfolge fuer Sortierung (niedrigerer Wert = hoehere Prioritaet)
    _SEVERITY_ORDER = {"critical": 0, "high": 1, "info": 2}
    # Maximale Anzahl Konflikte im Prompt (critical immer dabei)
    _MAX_CONFLICTS = 12
    # Generische Loesungsvorschlaege basierend auf Trigger-Rolle
    _RESOLUTIONS = {
        "window_contact": "Fenster schliessen",
        "door_contact": "Tuer schliessen",
        "smoke": "Raum lueften, Quelle pruefen",
        "co_detector": "Sofort lueften, Gebaeude verlassen",
        "gas_detector": "Gas abstellen, lueften, Gebaeude verlassen",
        "water_leak": "Wasserzufuhr pruefen",
        "motion": "Bewegungsmelder pruefen",
        "presence": "Anwesenheit pruefen",
    }

    def format_conflicts_for_prompt(self, states: dict) -> str:
        """Formatiert aktive Geraete-Konflikte als LLM-Kontext.

        Optimierungen gegenueber der Basisversion:
        1. Severity-Sortierung: critical → high → info
        2. Semantische Gruppierung: gleicher Hint aus mehreren Raeumen
           wird zu einer Zeile mit Raum-Liste zusammengefasst
        3. Max-Limit: Maximal _MAX_CONFLICTS Eintraege, critical immer
           enthalten, Rest nach Severity aufgefuellt

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

        # --- Schritt 1: Deduplizierung (trigger_entity + affected_role) ---
        seen_entity_keys: set[tuple[str, str]] = set()
        deduped: list[dict] = []
        for c in active_conflicts:
            key = (c["trigger_entity"], c["affected_role"])
            if key in seen_entity_keys:
                continue
            seen_entity_keys.add(key)
            deduped.append(c)

        # --- Schritt 2: Severity-Sortierung ---
        sev_order = self._SEVERITY_ORDER
        deduped.sort(key=lambda c: sev_order.get(c.get("severity", "info"), 2))

        # --- Schritt 3: Semantische Gruppierung ---
        # Gleicher Hint + gleicher Effect → Raeume zusammenfassen
        # Key: (hint, effect, severity) → {"rooms": [...], "trigger_role": str}
        from collections import OrderedDict
        grouped: OrderedDict[tuple[str, str, str], dict] = OrderedDict()
        for c in deduped:
            hint = c.get("hint", "")
            effect = c.get("effect", "")
            severity = c.get("severity", "info")
            if _sanitize_for_prompt:
                hint = _sanitize_for_prompt(hint, 200, "conflict_hint")
                effect = _sanitize_for_prompt(effect, 200, "conflict_effect")
            if not hint:
                continue
            room = c.get("trigger_room", "")
            if room and _sanitize_for_prompt:
                room = _sanitize_for_prompt(room, 50, "conflict_room")
            group_key = (hint, effect, severity)
            if group_key not in grouped:
                grouped[group_key] = {
                    "rooms": [],
                    "trigger_role": c.get("trigger_role", ""),
                    "affected_role": c.get("affected_role", ""),
                }
            if room and room not in grouped[group_key]["rooms"]:
                grouped[group_key]["rooms"].append(room)

        if not grouped:
            return ""

        # --- Schritt 4: Max-Limit mit Critical-Garantie ---
        all_entries = list(grouped.items())
        # Critical immer dabei
        critical_entries = [
            e for e in all_entries if e[0][2] == "critical"
        ]
        other_entries = [
            e for e in all_entries if e[0][2] != "critical"
        ]
        # Auffuellen bis _MAX_CONFLICTS (critical zuerst, dann Rest)
        max_other = max(0, self._MAX_CONFLICTS - len(critical_entries))
        selected = critical_entries + other_entries[:max_other]

        # --- Schritt 5: Formatierung mit Loesungsvorschlaegen ---
        lines: list[str] = []
        for (hint, effect, severity), group_data in selected:
            rooms = group_data["rooms"]
            trigger_role = group_data["trigger_role"]
            if rooms:
                room_info = f" [{', '.join(rooms)}]"
            else:
                room_info = ""
            sev_prefix = ""
            if severity == "critical":
                sev_prefix = "KRITISCH: "
            elif severity == "high":
                sev_prefix = "WICHTIG: "
            resolution = self._RESOLUTIONS.get(trigger_role, "")
            res_info = f" → Loesung: {resolution}" if resolution else ""
            lines.append(f"- {sev_prefix}{hint}{room_info} ({effect}){res_info}")

        if not lines:
            return ""

        return (
            "\n\nAKTIVE GERAETE-KONFLIKTE:\n"
            + "\n".join(lines)
            + "\nErwaehne relevante Konflikte PROAKTIV wenn der User "
            "eine betroffene Aktion ausfuehrt oder ein betroffenes "
            "Geraet anspricht — nicht erst wenn er explizit fragt. "
            "Bei KRITISCH-Konflikten IMMER sofort erwaehnen. "
            "Halte es kurz und sachlich (1 Satz). "
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

            # Nur aktive Konflikte (betroffenes Geraet ist aktiv)
            active = [c for c in conflicts if c.get("affected_active")]

            if target_entity and active:
                # Relevante Konflikte: target ist Trigger ODER betroffene Rolle
                target_role = StateChangeLog._get_entity_role(target_entity)
                relevant = [
                    c for c in active
                    if c["trigger_entity"] == target_entity
                    or c.get("affected_role") == target_role
                ]
                # Severity-Sortierung: critical zuerst
                _sev = {"critical": 0, "high": 1, "info": 2}
                relevant.sort(key=lambda c: _sev.get(c.get("severity", "info"), 2))
                for c in relevant[:3]:
                    room_info = f" ({c.get('trigger_room', '')})" if c.get("trigger_room") else ""
                    sev = c.get("severity", "info")
                    prefix = "KRITISCH: " if sev == "critical" else "WICHTIG: " if sev == "high" else ""
                    hints.append(f"{prefix}{c['hint']}{room_info}")
            elif not target_entity and active:
                # Ohne target_entity: Domain-basiert filtern
                domain = action_function.replace("set_", "").replace("_room", "")
                relevant = [
                    c for c in active
                    if domain in c.get("affected_role", "") or domain in c.get("trigger_role", "")
                ]
                _sev = {"critical": 0, "high": 1, "info": 2}
                relevant.sort(key=lambda c: _sev.get(c.get("severity", "info"), 2))
                for c in relevant[:3]:
                    room_info = f" ({c.get('trigger_room', '')})" if c.get("trigger_room") else ""
                    sev = c.get("severity", "info")
                    prefix = "KRITISCH: " if sev == "critical" else "WICHTIG: " if sev == "high" else ""
                    hints.append(f"{prefix}{c['hint']}{room_info}")
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
