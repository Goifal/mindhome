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
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Fenster offen bei Abwesenheit → Einbruchsrisiko",
        "hint": "Fenster offen → Sicherheitsrisiko bei Abwesenheit",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Fenster offen + Ventilator → Durchzug",
        "hint": "Fenster offen + Ventilator → Durchzug, Tueren knallen",
    },
    {
        "role": "window_contact", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Fenster offen + KWL → Lueftungseffizienz sinkt",
        "hint": "Fenster offen → KWL arbeitet ineffizient, Fenster zu fuer optimale Lueftung",
    },
    {
        "role": "door_contact", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Waermeverlust durch offene Tuer",
        "hint": "Tuer offen → beeinflusst Raumtemperatur",
    },
    {
        "role": "door_contact", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Tuer offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Haustuer steht offen → Sicherheit pruefen",
    },
    {
        "role": "garage_door", "state": "open",
        "affects": "alarm", "same_room": False,
        "effect": "Garagentor offen → Sicherheitsrisiko",
        "hint": "Garage offen → Sicherheit pruefen",
    },
    {
        "role": "garage_door", "state": "open",
        "affects": "climate", "same_room": False,
        "effect": "Garagentor offen → Kaelte zieht in angrenzende Raeume",
        "hint": "Garage offen → beeinflusst angrenzende Raeume",
    },
    {
        "role": "gate", "state": "open",
        "affects": "alarm", "same_room": False,
        "effect": "Tor offen → ungesicherter Zugang zum Grundstueck",
        "hint": "Tor offen → Grundstueck nicht gesichert",
    },

    # =====================================================================
    # 2. ROLLLADEN / JALOUSIE / MARKISE → KLIMA / LICHT
    # =====================================================================
    {
        "role": "blinds", "state": "open",
        "affects": "climate", "same_room": True,
        "effect": "Sonneneinstrahlung erhoeht Raumtemperatur / Waermeverlust nachts",
        "hint": "Rollladen offen → beeinflusst Raumklima",
    },
    {
        "role": "blinds", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Kein Tageslicht bei geschlossenem Rollladen",
        "hint": "Rollladen zu → Kunstlicht noetig",
    },
    {
        "role": "shutter", "state": "open",
        "affects": "climate", "same_room": True,
        "effect": "Sonneneinstrahlung beeinflusst Raumklima",
        "hint": "Rollladen offen → Raumklima beeinflusst",
    },
    {
        "role": "shutter", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Kein Tageslicht bei geschlossenem Rollladen",
        "hint": "Rollladen zu → Kunstlicht noetig",
    },
    {
        "role": "awning", "state": "open",
        "affects": "climate", "same_room": False,
        "effect": "Markise ausgefahren → Beschattung aktiv, Raum kuehler",
        "hint": "Markise draussen → schuetzt vor Sonneneinstrahlung",
    },
    {
        "role": "curtain", "state": "closed",
        "affects": "light", "same_room": True,
        "effect": "Vorhang zu → weniger Tageslicht",
        "hint": "Vorhang zu → Kunstlicht noetig",
    },

    # =====================================================================
    # 3. KLIMA / HEIZUNG / KUEHLUNG → ENERGIE / FENSTER
    # =====================================================================
    {
        "role": "thermostat", "state": "heat",
        "affects": "energy", "same_room": False,
        "effect": "Heizung aktiv → Energieverbrauch steigt",
        "hint": "Heizung aktiv → Energieverbrauch",
    },
    {
        "role": "thermostat", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Thermostat heizt + Fenster offen → Energieverschwendung",
        "hint": "Heizung an + Fenster offen → Energie wird verschwendet",
    },
    {
        "role": "thermostat", "state": "cool",
        "affects": "energy", "same_room": False,
        "effect": "Kuehlung aktiv → Energieverbrauch steigt",
        "hint": "Kuehlung aktiv → Stromverbrauch",
    },
    {
        "role": "thermostat", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Thermostat aus bei Kaelte → Frostgefahr",
        "hint": "Thermostat aus + kalt → Frostschutz beachten",
    },
    {
        "role": "heating", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Heizung aktiv → Energieverbrauch",
        "hint": "Heizung laeuft → Energieverbrauch",
    },
    {
        "role": "cooling", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Kuehlung aktiv → Stromverbrauch",
        "hint": "Klimaanlage laeuft → hoher Stromverbrauch",
    },
    {
        "role": "heat_pump", "state": "heat",
        "affects": "energy", "same_room": False,
        "effect": "Waermepumpe heizt → Stromverbrauch je nach COP",
        "hint": "Waermepumpe aktiv → Stromverbrauch beachten",
    },
    {
        "role": "heat_pump", "state": "heat",
        "affects": "notify", "same_room": False,
        "effect": "Waermepumpe nachts → Laermbelaestigung Nachbarn",
        "hint": "Waermepumpe nachts → Nachbarn koennten sich beschweren",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "energy", "same_room": False,
        "effect": "Fussbodenheizung aktiv → traege Regelung, vorausplanen",
        "hint": "Fussbodenheizung → reagiert langsam, braucht Stunden",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Fussbodenheizung + Fenster offen → viel Energieverlust",
        "hint": "Fussbodenheizung → Fenster kurz lueften, nicht kippen",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Heizkoerper heizt + Fenster offen → Energieverschwendung",
        "hint": "Heizkoerper an + Fenster offen → Energie geht verloren",
    },
    {
        "role": "boiler", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Warmwasser-Boiler heizt → hoher Energieverbrauch",
        "hint": "Boiler heizt → Stromverbrauch",
    },

    # =====================================================================
    # 4. LICHT → ENERGIE
    # =====================================================================
    {
        "role": "light", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Stromverbrauch durch Beleuchtung",
        "hint": "Licht an → Stromverbrauch",
    },

    # =====================================================================
    # 5. PRAESENZ / BEWEGUNG → LICHT / KLIMA / MEDIA / SICHERHEIT
    # =====================================================================
    {
        "role": "motion", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Bewegung erkannt → Licht-Automation moeglich",
        "hint": "Bewegung → Licht koennte automatisch geschaltet werden",
    },
    {
        "role": "motion", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Bewegung bei aktivem Alarm → moeglicher Einbruch",
        "hint": "Bewegung bei scharfem Alarm → Einbruch-Warnung",
    },
    {
        "role": "presence", "state": "off",
        "affects": "climate", "same_room": False,
        "effect": "Niemand zuhause → Heizung/Kuehlung unnoetig",
        "hint": "Abwesend → Energie sparen moeglich",
    },
    {
        "role": "presence", "state": "off",
        "affects": "light", "same_room": False,
        "effect": "Niemand zuhause → Licht unnoetig",
        "hint": "Abwesend → Licht sollte aus sein",
    },
    {
        "role": "presence", "state": "off",
        "affects": "media_player", "same_room": False,
        "effect": "Niemand zuhause → Medien laufen umsonst",
        "hint": "Abwesend → Medien sollten aus sein",
    },
    {
        "role": "presence", "state": "off",
        "affects": "outlet", "same_room": False,
        "effect": "Niemand zuhause → Standby-Geraete laufen",
        "hint": "Abwesend → Standby-Geraete ausschalten",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Raum leer → Licht unnoetig",
        "hint": "Raum leer → Licht brennt umsonst",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "climate", "same_room": True,
        "effect": "Raum leer → Heizung/Kuehlung unnoetig",
        "hint": "Raum leer → Energie sparen moeglich",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "media_player", "same_room": True,
        "effect": "Raum leer → Medien spielen fuer niemanden",
        "hint": "Raum leer → Medien laufen umsonst",
    },
    {
        "role": "occupancy", "state": "off",
        "affects": "fan", "same_room": True,
        "effect": "Raum leer → Ventilator unnoetig",
        "hint": "Raum leer → Ventilator laeuft umsonst",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Im Bett → Lichter sollten aus sein",
        "hint": "Bett belegt → Lichter ausschalten",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "media_player", "same_room": False,
        "effect": "Im Bett → Medien leiser oder aus",
        "hint": "Schlafenszeit → Medien runterdrehen",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Im Bett → Schlaftemperatur einstellen (kuehler)",
        "hint": "Schlafenszeit → Temperatur fuer Schlaf anpassen",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "lock", "same_room": False,
        "effect": "Im Bett → Tueren sollten abgeschlossen sein",
        "hint": "Schlafenszeit → Tueren abschliessen",
    },
    {
        "role": "bed_occupancy", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Im Bett → Rolllaeden sollten zu sein",
        "hint": "Schlafenszeit → Rolllaeden schliessen",
    },

    # =====================================================================
    # 6. SICHERHEIT — RAUCH / GAS / CO / WASSER / EINBRUCH
    # =====================================================================
    {
        "role": "smoke", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Rauchmelder → alle Lichter an fuer Fluchtweg",
        "hint": "Rauch → Beleuchtung fuer Fluchtweg einschalten",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Rauchmelder → Rolllaeden hoch fuer Fluchtweg",
        "hint": "Rauch → Rolllaeden oeffnen fuer Fluchtweg",
    },
    {
        "role": "co", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Kohlenmonoxid erkannt → LEBENSGEFAHRLICH",
        "hint": "CO erkannt → SOFORT ALARM, Fenster oeffnen, Haus verlassen",
    },
    {
        "role": "co", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "CO erkannt → Lueftung auf Maximum",
        "hint": "CO → maximale Belueftung noetig",
    },
    {
        "role": "gas", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Gas erkannt → Explosionsgefahr",
        "hint": "Gas erkannt → SOFORT ALARM, kein Funke, Haus verlassen",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM, Hauptventil schliessen",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Sabotage-Kontakt ausgeloest → Geraet manipuliert",
        "hint": "Sabotage erkannt → Geraet wurde manipuliert",
    },
    {
        "role": "vibration", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Vibration erkannt → Einbruchsversuch moeglich",
        "hint": "Vibration an Tuer/Fenster → Einbruchsversuch?",
    },
    {
        "role": "lock", "state": "unlocked",
        "affects": "alarm", "same_room": False,
        "effect": "Schloss offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Tuer nicht abgeschlossen → Sicherheit pruefen",
    },
    {
        "role": "lock", "state": "unlocked",
        "affects": "notify", "same_room": False,
        "effect": "Schloss offen nachts → Warnung",
        "hint": "Tuer nachts nicht abgeschlossen → Hinweis geben",
    },

    # =====================================================================
    # 7. ALARM → LICHT / KAMERA / BENACHRICHTIGUNG
    # =====================================================================
    {
        "role": "alarm", "state": "armed_away",
        "affects": "light", "same_room": False,
        "effect": "Alarm scharf (abwesend) → Praesenz simulieren",
        "hint": "Alarm scharf → Licht-Simulation gegen Einbruch",
    },
    {
        "role": "alarm", "state": "armed_away",
        "affects": "blinds", "same_room": False,
        "effect": "Alarm scharf (abwesend) → Rolllaeden als Schutz",
        "hint": "Alarm scharf → Rolllaeden runter fuer Sichtschutz",
    },
    {
        "role": "alarm", "state": "armed_night",
        "affects": "lock", "same_room": False,
        "effect": "Nacht-Alarm → alle Tueren abgeschlossen",
        "hint": "Nachtalarm → Schloss pruefen",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "light", "same_room": False,
        "effect": "Alarm ausgeloest → alle Lichter an zur Abschreckung",
        "hint": "ALARM AUSGELOEST → alle Lichter an",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "notify", "same_room": False,
        "effect": "Alarm ausgeloest → sofort benachrichtigen",
        "hint": "ALARM → sofortige Benachrichtigung",
    },

    # =====================================================================
    # 8. MEDIEN / ENTERTAINMENT → LICHT / ROLLLADEN
    # =====================================================================
    {
        "role": "media_player", "state": "playing",
        "affects": "light", "same_room": True,
        "effect": "Medien spielen → Kino-Modus (Licht dimmen) sinnvoll",
        "hint": "Film/Musik laeuft → Licht anpassen",
    },
    {
        "role": "media_player", "state": "playing",
        "affects": "blinds", "same_room": True,
        "effect": "Medien spielen → Rollladen gegen Blendung",
        "hint": "TV/Film laeuft → Blendung durch Rollladen vermeiden",
    },
    {
        "role": "tv", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "TV an → Licht anpassen fuer besseres Bild",
        "hint": "TV an → Licht dimmen sinnvoll",
    },
    {
        "role": "tv", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "TV an → Blendung auf Bildschirm vermeiden",
        "hint": "TV an → Rollladen gegen Blendung",
    },
    {
        "role": "projector", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Beamer an → Raum muss komplett dunkel sein",
        "hint": "Beamer an → alles abdunkeln noetig",
    },
    {
        "role": "projector", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Beamer an → Rollladen komplett runter",
        "hint": "Beamer an → komplette Abdunklung noetig",
    },
    {
        "role": "gaming", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Gaming aktiv → Licht anpassen fuer Bildschirm",
        "hint": "Gaming-Modus → Licht dimmen sinnvoll",
    },
    {
        "role": "speaker", "state": "playing",
        "affects": "window_contact", "same_room": True,
        "effect": "Musik laut + Fenster offen → Nachbarn stoeren",
        "hint": "Musik laut + Fenster offen → Laermbelaestigung moeglich",
    },

    # =====================================================================
    # 9. HAUSHALTSGERAETE → BENACHRICHTIGUNG / SICHERHEIT / ENERGIE
    # =====================================================================
    {
        "role": "washing_machine", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Waschmaschine fertig → Waesche rausholen",
        "hint": "Waschmaschine fertig → User benachrichtigen",
    },
    {
        "role": "dryer", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Trockner fertig → Waesche rausholen",
        "hint": "Trockner fertig → User benachrichtigen",
    },
    {
        "role": "dishwasher", "state": "idle",
        "affects": "notify", "same_room": False,
        "effect": "Geschirrspueler fertig → ausraeumen",
        "hint": "Geschirrspueler fertig → User benachrichtigen",
    },
    {
        "role": "oven", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Backofen/Herd an → nicht vergessen",
        "hint": "Backofen laeuft → nicht vergessen auszumachen",
    },
    {
        "role": "oven", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Herd an + niemand in Kueche → Brandgefahr",
        "hint": "Herd an → Brandgefahr wenn unbeaufsichtigt",
    },
    {
        "role": "oven", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Herd/Backofen an → hoher Stromverbrauch",
        "hint": "Herd laeuft → hoher Energieverbrauch",
    },
    {
        "role": "coffee_machine", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Kaffeemaschine an → Kaffee bald fertig",
        "hint": "Kaffeemaschine laeuft → Kaffee bald fertig",
    },
    {
        "role": "fridge", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Kuehlschrank offen → Lebensmittel verderben",
        "hint": "Kuehlschrank steht offen → sofort schliessen",
    },
    {
        "role": "freezer", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Gefrierschrank Temperatur zu hoch → Lebensmittel tauen",
        "hint": "Gefrierschrank zu warm → Lebensmittel in Gefahr",
    },
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "motion", "same_room": True,
        "effect": "Saugroboter kann Bewegungsmelder ausloesen",
        "hint": "Saugroboter aktiv → Bewegungsmelder ignorieren",
    },
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "alarm", "same_room": False,
        "effect": "Saugroboter loest Bewegungsmelder aus → kein Einbruch",
        "hint": "Saugroboter aktiv → Fehlalarm vermeiden",
    },

    # =====================================================================
    # 10. WETTER → ROLLLADEN / MARKISE / FENSTER / BEWAESSERUNG
    # =====================================================================
    {
        "role": "wind_speed", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Starker Wind → Markise einfahren, Beschaedigungsgefahr",
        "hint": "Wind stark → Markise/Sonnensegel einfahren",
    },
    {
        "role": "rain", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Regen → Dachfenster und offene Fenster pruefen",
        "hint": "Es regnet → Fenster pruefen, Dachfenster schliessen",
    },
    {
        "role": "rain", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Regen → Markise einfahren",
        "hint": "Regen → Markise einfahren",
    },
    {
        "role": "rain", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Regen → Bewaesserung unnoetig, Wasserverschwendung",
        "hint": "Es regnet → Bewaesserung stoppen",
    },
    {
        "role": "rain", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Regen → Waesche draussen? Dachfenster offen?",
        "hint": "Regen → Waesche reinholen, Fenster pruefen",
    },
    {
        "role": "uv_index", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "UV-Index hoch → Beschattung sinnvoll",
        "hint": "Starke UV-Strahlung → Rolllaeden/Jalousien als Schutz",
    },
    {
        "role": "solar_radiation", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Starke Sonneneinstrahlung → Beschattung aktivieren",
        "hint": "Sonne stark → Beschattung anpassen",
    },
    {
        "role": "rain_sensor", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Regen erkannt → offene Fenster schliessen",
        "hint": "Regensensor → Fenster pruefen",
    },

    # =====================================================================
    # 11. LUEFTUNG / DUNSTABZUG / KAMIN → FENSTER (UNTERDRUCK!)
    # =====================================================================
    {
        "role": "ventilation", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Lueftungsanlage aktiv → Fenster zu halten fuer Effizienz",
        "hint": "KWL laeuft → Fenster zu fuer optimale Lueftung",
    },
    {
        "role": "fan", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Ventilator/Luefter an → Stromverbrauch",
        "hint": "Ventilator laeuft → Stromverbrauch",
    },
    {
        "role": "fan", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Ventilator an → gefuehlte Temperatur sinkt",
        "hint": "Ventilator → kuehlt nicht, aber gefuehlt kuehler",
    },
    {
        "role": "dehumidifier", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Entfeuchter an → Stromverbrauch",
        "hint": "Entfeuchter laeuft → Stromverbrauch beachten",
    },
    {
        "role": "humidifier", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Befeuchter an → Stromverbrauch",
        "hint": "Luftbefeuchter laeuft → Stromverbrauch",
    },
    {
        "role": "air_purifier", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Luftreiniger an → Stromverbrauch",
        "hint": "Luftreiniger laeuft → Stromverbrauch beachten",
    },

    # =====================================================================
    # 12. LUFTQUALITAET → LUEFTUNG / FENSTER / GESUNDHEIT
    # =====================================================================
    {
        "role": "co2", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "CO2-Wert hoch → dringend lueften",
        "hint": "CO2 hoch → Fenster oeffnen oder Lueftung verstaerken",
    },
    {
        "role": "voc", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "VOC hoch → Schadstoffe in der Luft, lueften",
        "hint": "VOC hoch → Lueften, Schadstoffe in der Luft",
    },
    {
        "role": "pm25", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Feinstaub hoch draussen → Fenster geschlossen halten",
        "hint": "Feinstaub draussen hoch → Fenster zu, Luftreiniger an",
    },
    {
        "role": "pm10", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Grobstaub hoch → Fenster geschlossen halten",
        "hint": "Feinstaub hoch → Fenster zu lassen",
    },
    {
        "role": "air_quality", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Luftqualitaet draussen schlecht → Fenster geschlossen",
        "hint": "Luftqualitaet draussen schlecht → Fenster zu",
    },
    {
        "role": "dew_point", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Taupunkt erreicht → Kondenswasser, Schimmelgefahr",
        "hint": "Taupunkt → Schimmelgefahr, sofort lueften oder heizen",
    },
    {
        "role": "humidity", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "Luftfeuchtigkeit hoch → Lueftung noetig",
        "hint": "Feuchtigkeit hoch → Luefter/Fenster oeffnen",
    },
    {
        "role": "humidity", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Hohe Feuchtigkeit → Schimmelgefahr",
        "hint": "Hohe Luftfeuchtigkeit → Lueften oder Entfeuchten",
    },
    {
        "role": "radon", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Radon-Wert hoch → Lueftung wichtig",
        "hint": "Radon hoch → unbedingt lueften, gesundheitsgefaehrdend",
    },

    # =====================================================================
    # 13. ENERGIE / SOLAR / BATTERIE / WALLBOX
    # =====================================================================
    {
        "role": "solar", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "PV produziert → Eigenverbrauch optimieren",
        "hint": "PV-Produktion → Geraete jetzt einschalten fuer Eigenverbrauch",
    },
    {
        "role": "grid_feed", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Strom wird eingespeist → Eigenverbrauch erhoehen",
        "hint": "Einspeisung → besser selbst verbrauchen",
    },
    {
        "role": "grid_consumption", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Netzbezug hoch → Strom wird teuer eingekauft",
        "hint": "Netzbezug hoch → Eigenverbrauch optimieren",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Wallbox laedt → sehr hoher Stromverbrauch (11-22kW)",
        "hint": "E-Auto laedt → hoher Stromverbrauch",
    },
    {
        "role": "ev_charger", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Wallbox + Waermepumpe gleichzeitig → moegliche Netzueberlast",
        "hint": "Wallbox + Waermepumpe → Ueberlastgefahr",
    },
    {
        "role": "battery", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Batterie-Warnung → Geraet bald offline",
        "hint": "Batterie schwach → Batterie wechseln bevor Geraet ausfaellt",
    },
    {
        "role": "outlet", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Smarte Steckdose an → Standby-Verbrauch moeglich",
        "hint": "Steckdose aktiv → Standby-Verbrauch pruefen",
    },
    {
        "role": "power_meter", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Hoher Verbrauch erkannt → Geraet pruefen",
        "hint": "Ungewoehnlich hoher Verbrauch → Defekt oder vergessen?",
    },

    # =====================================================================
    # 14. TUERKLINGEL / BRIEFKASTEN / PAKET
    # =====================================================================
    {
        "role": "doorbell", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Tuerklingel → jemand steht vor der Tuer",
        "hint": "Klingel → Besucher an der Tuer",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Klingel nachts → Aussenlicht an",
        "hint": "Klingel → Eingangsbereich beleuchten",
    },
    {
        "role": "doorbell", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Klingel → Kamerabild anzeigen/aufnehmen",
        "hint": "Klingel → Tuerkamera aktivieren",
    },
    {
        "role": "intercom", "state": "on",
        "affects": "camera", "same_room": False,
        "effect": "Gegensprechanlage aktiv → Kamera zeigen",
        "hint": "Gegensprech → wer steht vor der Tuer?",
    },

    # =====================================================================
    # 15. NETZWERK / CONNECTIVITY → GERAETE-AUSFALL
    # =====================================================================
    {
        "role": "router", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Router offline → alle WLAN-Geraete ohne Verbindung",
        "hint": "Router offline → Internet und WLAN-Geraete betroffen",
    },
    {
        "role": "connectivity", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Verbindung verloren → Geraet nicht erreichbar",
        "hint": "Geraet offline → Verbindung pruefen",
    },
    {
        "role": "server", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Server/NAS offline → Dienste nicht verfuegbar",
        "hint": "Server offline → Backups und Dienste betroffen",
    },
    {
        "role": "nas", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "NAS offline → Backups und Medien nicht verfuegbar",
        "hint": "NAS offline → Datensicherung betroffen",
    },

    # =====================================================================
    # 16. GARTEN / BEWAESSERUNG / POOL
    # =====================================================================
    {
        "role": "irrigation", "state": "on",
        "affects": "water_consumption", "same_room": False,
        "effect": "Bewaesserung laeuft → Wasserverbrauch",
        "hint": "Bewaesserung an → Wasserverbrauch beachten",
    },
    {
        "role": "soil_moisture", "state": "on",
        "affects": "irrigation", "same_room": True,
        "effect": "Boden trocken → Bewaesserung noetig",
        "hint": "Boden trocken → Pflanzen brauchen Wasser",
    },
    {
        "role": "pool", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Pool-Technik an → Stromverbrauch",
        "hint": "Pool-Pumpe/Heizung laeuft → Energieverbrauch beachten",
    },
    {
        "role": "garden_light", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gartenbeleuchtung an → Stromverbrauch nachts",
        "hint": "Gartenlicht brennt → Lichtverschmutzung, Insekten",
    },

    # =====================================================================
    # 17. FAHRZEUGE / GARAGE
    # =====================================================================
    {
        "role": "car", "state": "not_home",
        "affects": "garage_door", "same_room": False,
        "effect": "Auto weg + Garage offen → vergessen zu schliessen",
        "hint": "Auto weg, Garage offen → schliessen vergessen?",
    },
    {
        "role": "car_battery", "state": "on",
        "affects": "ev_charger", "same_room": False,
        "effect": "Auto-Akku niedrig → laden sinnvoll",
        "hint": "E-Auto Akku niedrig → aufladen",
    },

    # =====================================================================
    # 18. NOTFALL / PANIK / STURZERKENNUNG
    # =====================================================================
    {
        "role": "problem", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Geraete-Problem erkannt → Wartung noetig",
        "hint": "Problem/Stoerung → Geraet pruefen",
    },

    # =====================================================================
    # 19. VERBRAUCH / FUELLSTAENDE
    # =====================================================================
    {
        "role": "water_consumption", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Hoher Wasserverbrauch → Leck oder Hahn vergessen?",
        "hint": "Wasserverbrauch hoch → Ursache pruefen",
    },
    {
        "role": "gas_consumption", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gasverbrauch → Heizung/Warmwasser aktiv",
        "hint": "Gasverbrauch → Heizkosten beachten",
    },

    # =====================================================================
    # 20. LICHT-SENSOR / HELLIGKEIT → LICHT / ROLLLADEN
    # =====================================================================
    {
        "role": "light_level", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Helligkeit → Kunstlicht anpassen",
        "hint": "Genug Tageslicht → Lampen koennen aus",
    },
    {
        "role": "light_level", "state": "on",
        "affects": "blinds", "same_room": True,
        "effect": "Daemmerung/Helligkeit → Rolllaeden anpassen",
        "hint": "Lichtverhaeltnisse → Beschattung optimieren",
    },

    # =====================================================================
    # 21. KAMERA / UEBERWACHUNG
    # =====================================================================
    {
        "role": "camera", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Kamera aktiv → gute Beleuchtung fuer Aufnahmen",
        "hint": "Kamera nimmt auf → Licht fuer besseres Bild",
    },

    # =====================================================================
    # 22. UPDATE / WARTUNG
    # =====================================================================
    {
        "role": "update", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Update verfuegbar → Geraet aktualisieren",
        "hint": "Update verfuegbar → Firmware/Software aktualisieren",
    },

    # =====================================================================
    # 23. LAERM / NOISE → KOMFORT
    # =====================================================================
    {
        "role": "noise", "state": "on",
        "affects": "notify", "same_room": True,
        "effect": "Laermpegel hoch → Quelle pruefen",
        "hint": "Laut im Raum → was verursacht den Laerm?",
    },

    # =====================================================================
    # 24. PUMPE / VENTIL / MOTOR → ENERGIE / WARTUNG
    # =====================================================================
    {
        "role": "pump", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Pumpe laeuft → Dauerstromverbrauch",
        "hint": "Pumpe aktiv → Stromverbrauch",
    },
    {
        "role": "valve", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Ventil geschlossen → Durchfluss gestoppt",
        "hint": "Ventil zu → kein Durchfluss, gewollt?",
    },

    # =====================================================================
    # 25. TEMPERATUR-SENSOREN → KLIMA / WARNUNG
    # =====================================================================
    {
        "role": "indoor_temp", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Raumtemperatur beeinflusst Heizung/Kuehlung",
        "hint": "Raumtemperatur → Heizung/Kuehlung anpassen",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Heizstrategie und Beschattung",
        "hint": "Aussentemperatur → beeinflusst Heizung, Beschattung, Bewaesserung",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Aussentemperatur hoch → Beschattung sinnvoll",
        "hint": "Heiss draussen → Rolllaeden/Jalousien schliessen",
    },
    {
        "role": "outdoor_temp", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Aussentemperatur beeinflusst Bewaesserungsbedarf",
        "hint": "Heiss → Pflanzen brauchen mehr Wasser",
    },
    {
        "role": "water_temp", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Wassertemperatur → Legionellen-Schutz ab 60°C beachten",
        "hint": "Warmwasser-Temp → Legionellen-Risiko unter 60°C",
    },
    {
        "role": "water_temp", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Warmwasser-Temperatur beeinflusst Boiler-Energieverbrauch",
        "hint": "Wassertemperatur → Energieverbrauch fuer Warmwasser",
    },
    {
        "role": "soil_temp", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Bodentemperatur beeinflusst Pflanzenwachstum",
        "hint": "Bodentemperatur → Bewaesserung/Frostschutz anpassen",
    },
    {
        "role": "pressure", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Luftdruckveraenderung → Wetterwechsel kommt",
        "hint": "Luftdruck faellt → Schlechtwetter im Anmarsch",
    },

    # =====================================================================
    # 26. STROM-DETAILS → ENERGIE / WARNUNG
    # =====================================================================
    {
        "role": "current", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Stromstaerke ungewoehnlich hoch → Ueberlast moeglich",
        "hint": "Hohe Stromstaerke → Sicherung koennte ausloesen",
    },
    {
        "role": "voltage", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Spannung ausserhalb Norm → Netzproblem",
        "hint": "Spannung anomal → Netzstabiliaet pruefen",
    },
    {
        "role": "frequency", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Netzfrequenz abweichend → Netzinstabilitaet",
        "hint": "Netzfrequenz → Stabilitaet des Stromnetzes",
    },
    {
        "role": "power_factor", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Schlechter Leistungsfaktor → ineffiziente Geraete",
        "hint": "Leistungsfaktor schlecht → Blindleistung, ineffizient",
    },
    {
        "role": "energy", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Energieverbrauch ungewoehnlich → Ursache pruefen",
        "hint": "Energieverbrauch hoch → welches Geraet verbraucht soviel?",
    },

    # =====================================================================
    # 27. LADEGERAETE / AKKUS → ENERGIE
    # =====================================================================
    {
        "role": "charger", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Ladegeraet aktiv → Stromverbrauch, bei Vollladung abschalten",
        "hint": "Ladegeraet → bei vollem Akku Stecker ziehen",
    },
    {
        "role": "battery_charging", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Batterie laedt → Stromverbrauch bis voll",
        "hint": "Akku laedt → Stromverbrauch waehrend Ladung",
    },

    # =====================================================================
    # 28. SITZ- / STUHLBELEGUNG → LICHT / KLIMA
    # =====================================================================
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "Stuhl belegt → Person im Raum, Licht sinnvoll",
        "hint": "Stuhl belegt → jemand sitzt hier, Licht an lassen",
    },
    {
        "role": "chair_occupancy", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Stuhl belegt → Raum ist besetzt, Klima halten",
        "hint": "Jemand sitzt → Raumklima beibehalten",
    },
    {
        "role": "chair_occupancy", "state": "off",
        "affects": "light", "same_room": True,
        "effect": "Stuhl leer → Person hat Raum eventuell verlassen",
        "hint": "Stuhl leer → noch jemand im Raum?",
    },

    # =====================================================================
    # 29. COMPUTER / DRUCKER / IT → ENERGIE
    # =====================================================================
    {
        "role": "pc", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "PC/Computer an → Stromverbrauch",
        "hint": "Computer laeuft → Stromverbrauch beachten",
    },
    {
        "role": "pc", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "PC an → Bildschirmarbeit, Licht anpassen",
        "hint": "PC aktiv → Licht fuer Bildschirmarbeit anpassen",
    },
    {
        "role": "pc", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "PC an → erzeugt Abwaerme im Raum",
        "hint": "Computer → Abwaerme beeinflusst Raumtemperatur",
    },
    {
        "role": "printer", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Drucker an → Standby-Verbrauch wenn nicht genutzt",
        "hint": "Drucker an → Stromverbrauch, nach Nutzung ausschalten",
    },
    {
        "role": "printer", "state": "on",
        "affects": "fan", "same_room": True,
        "effect": "3D-Drucker → Daempfe moeglich, Lueftung sinnvoll",
        "hint": "3D-Drucker druckt → Lueftung wegen Daempfe",
    },

    # =====================================================================
    # 30. RECEIVER / HIFI → LAUTSTAERKE / ENERGIE
    # =====================================================================
    {
        "role": "receiver", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "AV-Receiver an → Stromverbrauch",
        "hint": "Receiver laeuft → Stromverbrauch beachten",
    },
    {
        "role": "receiver", "state": "on",
        "affects": "light", "same_room": True,
        "effect": "AV-Receiver an → Heimkino-Beleuchtung anpassen",
        "hint": "Receiver an → Heimkino-Modus, Licht dimmen",
    },

    # =====================================================================
    # 31. TELEFON → BENACHRICHTIGUNG / LAUTSTAERKE
    # =====================================================================
    {
        "role": "phone", "state": "on",
        "affects": "media_player", "same_room": True,
        "effect": "Telefonat → Medien leiser/stumm",
        "hint": "Telefonat → Medien stumm schalten",
    },
    {
        "role": "phone", "state": "on",
        "affects": "vacuum", "same_room": False,
        "effect": "Telefonat → Staubsauger stoeren",
        "hint": "Telefonat → Saugroboter pausieren",
    },

    # =====================================================================
    # 32. SIRENE → WARNUNG
    # =====================================================================
    {
        "role": "siren", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Sirene aktiv → Alarm wurde ausgeloest",
        "hint": "Sirene heult → ALARM aktiv, sofort reagieren",
    },
    {
        "role": "siren", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Sirene → Lichter an zur Orientierung/Abschreckung",
        "hint": "Sirene → alle Lichter an",
    },

    # =====================================================================
    # 33. MOTOR / RELAY / AKTOR → ENERGIE / WARTUNG
    # =====================================================================
    {
        "role": "motor", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Motor/Antrieb aktiv → Stromverbrauch",
        "hint": "Motor laeuft → Stromverbrauch",
    },
    {
        "role": "relay", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Relais geschaltet → angeschlossenes Geraet aktiv",
        "hint": "Relais an → was haengt dran?",
    },

    # =====================================================================
    # 34. SIGNAL / GESCHWINDIGKEIT / NETZWERK-QUALITAET
    # =====================================================================
    {
        "role": "signal_strength", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Signalstaerke schwach → Verbindungsprobleme moeglich",
        "hint": "Schwaches Signal → Geraet koennte ausfallen",
    },
    {
        "role": "speedtest", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Internet-Geschwindigkeit → Streaming/Cloud betroffen",
        "hint": "Internet langsam → Streaming/Downloads beeintraechtigt",
    },

    # =====================================================================
    # 35. WIND-RICHTUNG → BESCHATTUNG / KOMFORT
    # =====================================================================
    {
        "role": "wind_direction", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Windrichtung → Markisen-Position anpassen",
        "hint": "Windrichtung → Markise auf Windseite einfahren",
    },
    {
        "role": "wind_direction", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Windrichtung → Fenster auf Windseite schliessen bei Sturm",
        "hint": "Wind von dieser Seite → Fenster pruefen",
    },

    # =====================================================================
    # 36. RUNNING / STATUS → BENACHRICHTIGUNG
    # =====================================================================
    {
        "role": "running", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Geraet laeuft → Stromverbrauch aktiv",
        "hint": "Geraet in Betrieb → Energieverbrauch",
    },
    {
        "role": "running", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Geraet gestoppt → Aufgabe fertig?",
        "hint": "Geraet fertig → Ergebnis pruefen",
    },

    # =====================================================================
    # 37. DIMMER / FARBLICHT → STIMMUNG / ENERGIE
    # =====================================================================
    {
        "role": "dimmer", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Gedimmtes Licht → reduzierter Stromverbrauch",
        "hint": "Licht gedimmt → weniger Verbrauch als volle Helligkeit",
    },
    {
        "role": "color_light", "state": "on",
        "affects": "energy", "same_room": False,
        "effect": "Farblicht an → Stromverbrauch",
        "hint": "RGB-Licht an → Stromverbrauch beachten",
    },

    # =====================================================================
    # 38. GESCHWINDIGKEIT / ENTFERNUNG / GEWICHT → KONTEXT
    # =====================================================================
    {
        "role": "speed", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Geschwindigkeit → Bewegung erkannt",
        "hint": "Geschwindigkeit gemessen → etwas bewegt sich",
    },
    {
        "role": "distance", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Entfernung → Annaeherung oder Entfernung",
        "hint": "Entfernung aendert sich → jemand naehert sich oder geht weg",
    },
    {
        "role": "weight", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Gewicht gemessen → Fuellstand oder Koerpergewicht",
        "hint": "Gewicht → Fuellstand pruefen oder Gesundheitsdaten",
    },

    # =====================================================================
    # 39. AUTO-STANDORT → SICHERHEIT / KOMFORT
    # =====================================================================
    {
        "role": "car_location", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Auto-Standort → Person unterwegs oder zuhause",
        "hint": "Auto-Position → Ankunftszeit schaetzen",
    },
    {
        "role": "car_location", "state": "on",
        "affects": "climate", "same_room": False,
        "effect": "Auto naehert sich → Haus vorheizen/kuehlen",
        "hint": "Auto auf dem Heimweg → Haus vorbereiten",
    },

    # =====================================================================
    # 40. TIMER / ZAEHLER → BENACHRICHTIGUNG
    # =====================================================================
    {
        "role": "timer", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Timer laeuft → Erinnerung wenn abgelaufen",
        "hint": "Timer aktiv → nicht vergessen",
    },
    {
        "role": "counter", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Zaehler → Grenzwert beobachten",
        "hint": "Zaehlerstand → Limit erreicht?",
    },

    # =====================================================================
    # 41. SZENE / AUTOMATION → KONTEXT
    # =====================================================================
    {
        "role": "scene", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Szene aktiviert → mehrere Geraete aendern sich",
        "hint": "Szene aktiv → Geraete wurden automatisch gesetzt",
    },
    {
        "role": "automation", "state": "on",
        "affects": "notify", "same_room": False,
        "effect": "Automation aktiv → laeuft im Hintergrund",
        "hint": "Automation laeuft → Geraete werden automatisch gesteuert",
    },

    # =====================================================================
    # 42. ADBLOCKER → NETZWERK
    # =====================================================================
    {
        "role": "adblocker", "state": "off",
        "affects": "notify", "same_room": False,
        "effect": "Adblocker/DNS-Filter aus → Werbung und Tracker aktiv",
        "hint": "Adblocker deaktiviert → Netzwerk ungeschuetzt",
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

        lines = []
        seen = set()
        for c in active_conflicts:
            # Raum-Info in Hinweis einbauen wenn vorhanden
            room = c.get("trigger_room", "")
            room_info = f" [{room}]" if room else ""
            key = (c["trigger_entity"], c["affected_role"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {c['hint']}{room_info} ({c['effect']})")

        return (
            "\n\nAKTIVE GERAETE-KONFLIKTE:\n"
            + "\n".join(lines)
            + "\nWeise den User beilaeufig auf diese Konflikte hin, "
            "wenn er nach Energie, Heizung oder Raumklima fragt."
        )

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
