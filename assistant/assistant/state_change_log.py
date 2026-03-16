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

# Geraete-Abhaengigkeiten: Welche Zustaende sich gegenseitig beeinflussen
# Prefix-Match: "binary_sensor.fenster" matcht auch "binary_sensor.fenster_kueche"
#
# WICHTIG: Diese Regeln steuern NICHTS. Sie geben JARVIS rein kognitives
# Verstaendnis darueber welche Geraetezustaende sich gegenseitig beeinflussen,
# damit er dem User intelligente Hinweise geben kann.
DEVICE_DEPENDENCIES = [

    # =====================================================================
    # 1. FENSTER / TUEREN → KLIMA / ENERGIE / SICHERHEIT
    # =====================================================================
    {
        "condition": ("binary_sensor.fenster", "on"),
        "affects": "climate",
        "effect": "Heizung/Kuehlung ineffizient bei offenem Fenster",
        "hint": "Fenster offen → Heizenergie geht verloren",
    },
    {
        "condition": ("binary_sensor.window", "on"),
        "affects": "climate",
        "effect": "Heizung/Kuehlung ineffizient bei offenem Fenster",
        "hint": "Fenster offen → Heizenergie geht verloren",
    },
    {
        "condition": ("binary_sensor.dachfenster", "on"),
        "affects": "climate",
        "effect": "Dachfenster offen → starker Waermeverlust nach oben",
        "hint": "Dachfenster offen → Warme Luft steigt und entweicht",
    },
    {
        "condition": ("binary_sensor.velux", "on"),
        "affects": "climate",
        "effect": "Dachfenster offen → starker Waermeverlust nach oben",
        "hint": "Dachfenster offen → Warme Luft steigt und entweicht",
    },
    {
        "condition": ("binary_sensor.dachfenster", "on"),
        "affects": "alarm_control_panel",
        "effect": "Dachfenster offen → Regen kann reinlaufen",
        "hint": "Dachfenster offen → bei Regen Wasserschaden moeglich",
    },
    {
        "condition": ("binary_sensor.kellerfenster", "on"),
        "affects": "climate",
        "effect": "Kellerfenster offen → Feuchtigkeit kann eindringen",
        "hint": "Kellerfenster offen → Schimmelgefahr im Keller",
    },
    {
        "condition": ("binary_sensor.tuer", "on"),
        "affects": "climate",
        "effect": "Waermeverlust durch offene Tuer",
        "hint": "Tuer offen → beeinflusst Raumtemperatur",
    },
    {
        "condition": ("binary_sensor.door", "on"),
        "affects": "climate",
        "effect": "Waermeverlust durch offene Tuer",
        "hint": "Tuer offen → beeinflusst Raumtemperatur",
    },
    {
        "condition": ("binary_sensor.balkontuer", "on"),
        "affects": "climate",
        "effect": "Balkontuer offen → grosser Waermeverlust",
        "hint": "Balkontuer offen → grosse Oeffnung, viel Energieverlust",
    },
    {
        "condition": ("binary_sensor.balkon", "on"),
        "affects": "climate",
        "effect": "Balkontuer offen → grosser Waermeverlust",
        "hint": "Balkontuer offen → grosse Oeffnung, viel Energieverlust",
    },
    {
        "condition": ("binary_sensor.terrassen", "on"),
        "affects": "climate",
        "effect": "Terrassentuer offen → grosser Waermeverlust",
        "hint": "Terrassentuer offen → grosse Oeffnung, viel Energieverlust",
    },
    {
        "condition": ("binary_sensor.patio", "on"),
        "affects": "climate",
        "effect": "Terrassentuer offen → grosser Waermeverlust",
        "hint": "Terrassentuer offen → grosse Oeffnung, viel Energieverlust",
    },
    {
        "condition": ("binary_sensor.haustuer", "on"),
        "affects": "alarm_control_panel",
        "effect": "Haustuer offen → Sicherheitsrisiko",
        "hint": "Haustuer steht offen → Sicherheit pruefen",
    },
    {
        "condition": ("binary_sensor.front_door", "on"),
        "affects": "alarm_control_panel",
        "effect": "Haustuer offen → Sicherheitsrisiko",
        "hint": "Haustuer steht offen → Sicherheit pruefen",
    },
    {
        "condition": ("binary_sensor.haustuer", "on"),
        "affects": "climate",
        "effect": "Haustuer offen → Waermeverlust im Eingangsbereich",
        "hint": "Haustuer offen → kalte Luft zieht rein",
    },
    {
        "condition": ("binary_sensor.fenster", "on"),
        "affects": "alarm_control_panel",
        "effect": "Fenster offen bei Abwesenheit → Einbruchsrisiko",
        "hint": "Fenster offen → Sicherheitsrisiko bei Abwesenheit",
    },

    # =====================================================================
    # 2. ROLLLADEN / JALOUSIE / MARKISE → KLIMA / LICHT
    # =====================================================================
    {
        "condition": ("cover.", "open"),
        "affects": "climate",
        "effect": "Sonneneinstrahlung erhoeht Raumtemperatur / Waermeverlust nachts",
        "hint": "Rollladen offen → beeinflusst Raumklima",
    },
    {
        "condition": ("cover.", "closed"),
        "affects": "light",
        "effect": "Kein Tageslicht bei geschlossenem Rollladen",
        "hint": "Rollladen zu → Kunstlicht noetig",
    },
    {
        "condition": ("cover.markise", "open"),
        "affects": "climate",
        "effect": "Markise ausgefahren → Beschattung aktiv, Raum kuehler",
        "hint": "Markise draussen → schuetzt vor Sonneneinstrahlung",
    },
    {
        "condition": ("cover.awning", "open"),
        "affects": "climate",
        "effect": "Markise ausgefahren → Beschattung aktiv, Raum kuehler",
        "hint": "Markise draussen → schuetzt vor Sonneneinstrahlung",
    },
    {
        "condition": ("cover.jalousie", "closed"),
        "affects": "light",
        "effect": "Jalousie geschlossen → kein Tageslicht",
        "hint": "Jalousie zu → Kunstlicht noetig",
    },
    {
        "condition": ("cover.jalousie", "open"),
        "affects": "climate",
        "effect": "Jalousie offen → Sonneneinstrahlung moeglich",
        "hint": "Jalousie offen → Sonneneinstrahlung beeinflusst Raumklima",
    },

    # =====================================================================
    # 3. KLIMA / HEIZUNG / KUEHLUNG → ENERGIE
    # =====================================================================
    {
        "condition": ("climate.", "heat"),
        "affects": "energy",
        "effect": "Hoher Energieverbrauch durch aktive Heizung",
        "hint": "Heizung aktiv → Energieverbrauch steigt",
    },
    {
        "condition": ("climate.", "cool"),
        "affects": "energy",
        "effect": "Hoher Energieverbrauch durch aktive Kuehlung",
        "hint": "Kuehlung aktiv → Energieverbrauch steigt",
    },
    {
        "condition": ("climate.", "heat_cool"),
        "affects": "energy",
        "effect": "Hoher Energieverbrauch durch aktive Klimaanlage",
        "hint": "Klimaanlage aktiv → Energieverbrauch steigt",
    },
    {
        "condition": ("climate.", "dry"),
        "affects": "energy",
        "effect": "Entfeuchtungsmodus aktiv → Stromverbrauch",
        "hint": "Entfeuchtung laeuft → Stromverbrauch",
    },
    {
        "condition": ("climate.", "fan_only"),
        "affects": "energy",
        "effect": "Ventilator-Modus → moderater Stromverbrauch",
        "hint": "Ventilator laeuft → Stromverbrauch",
    },
    {
        "condition": ("switch.infrarot", "on"),
        "affects": "energy",
        "effect": "Infrarotheizung an → sehr hoher Stromverbrauch",
        "hint": "Infrarotheizung an → hoher Stromverbrauch",
    },
    {
        "condition": ("switch.heizluefter", "on"),
        "affects": "energy",
        "effect": "Heizluefter an → extrem hoher Stromverbrauch (1500-2000W)",
        "hint": "Heizluefter an → Stromfresser laeuft",
    },
    {
        "condition": ("switch.radiator", "on"),
        "affects": "energy",
        "effect": "Elektro-Heizkoerper an → hoher Stromverbrauch",
        "hint": "Elektro-Heizung an → hoher Stromverbrauch",
    },

    # =====================================================================
    # 4. LICHT → ENERGIE
    # =====================================================================
    {
        "condition": ("light.", "on"),
        "affects": "energy",
        "effect": "Stromverbrauch durch Beleuchtung",
        "hint": "Licht an → Stromverbrauch",
    },

    # =====================================================================
    # 5. PRAESENZ / BEWEGUNG → LICHT / KLIMA / MEDIA / SICHERHEIT
    # =====================================================================
    {
        "condition": ("binary_sensor.motion", "on"),
        "affects": "light",
        "effect": "Bewegung erkannt → Licht koennte automatisch geschaltet werden",
        "hint": "Bewegung → Licht-Automation moeglich",
    },
    {
        "condition": ("binary_sensor.bewegung", "on"),
        "affects": "light",
        "effect": "Bewegung erkannt → Licht koennte automatisch geschaltet werden",
        "hint": "Bewegung → Licht-Automation moeglich",
    },
    {
        "condition": ("binary_sensor.motion", "on"),
        "affects": "alarm_control_panel",
        "effect": "Bewegung erkannt bei aktivem Alarm → moeglicher Einbruch",
        "hint": "Bewegung bei scharfem Alarm → Einbruch-Warnung",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "climate",
        "effect": "Niemand zuhause → Heizung/Kuehlung unnoetig",
        "hint": "Abwesend → Energie sparen moeglich",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "light",
        "effect": "Niemand zuhause → Licht unnoetig",
        "hint": "Abwesend → Licht sollte aus sein",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "media_player",
        "effect": "Niemand zuhause → Medien unnoetig",
        "hint": "Abwesend → Medien sollten aus sein",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "switch",
        "effect": "Niemand zuhause → unnoetige Geraete laufen",
        "hint": "Abwesend → Standby-Geraete ausschalten",
    },
    {
        "condition": ("binary_sensor.occupancy", "off"),
        "affects": "light",
        "effect": "Raum leer → Licht unnoetig",
        "hint": "Raum leer → Licht verschwenden",
    },
    {
        "condition": ("binary_sensor.occupancy", "off"),
        "affects": "climate",
        "effect": "Raum leer → Heizung/Kuehlung unnoetig",
        "hint": "Raum leer → Energie sparen moeglich",
    },
    {
        "condition": ("binary_sensor.occupancy", "off"),
        "affects": "media_player",
        "effect": "Raum leer → Medien spielen fuer niemanden",
        "hint": "Raum leer → Medien laufen umsonst",
    },
    {
        "condition": ("binary_sensor.occupancy", "off"),
        "affects": "fan",
        "effect": "Raum leer → Ventilator unnoetig",
        "hint": "Raum leer → Ventilator laeuft umsonst",
    },

    # =====================================================================
    # 6. PERSON HOME/AWAY → SICHERHEIT / ENERGIE / KOMFORT
    # =====================================================================
    {
        "condition": ("person.", "not_home"),
        "affects": "light",
        "effect": "Person nicht zuhause → Licht brennt unnoetig",
        "hint": "Niemand da → Licht sollte aus sein",
    },
    {
        "condition": ("person.", "not_home"),
        "affects": "climate",
        "effect": "Person nicht zuhause → Energie-Verschwendung",
        "hint": "Niemand da → Heizung runterdrehen",
    },
    {
        "condition": ("person.", "not_home"),
        "affects": "media_player",
        "effect": "Person nicht zuhause → Medien laufen umsonst",
        "hint": "Niemand da → Medien sollten aus sein",
    },
    {
        "condition": ("person.", "not_home"),
        "affects": "alarm_control_panel",
        "effect": "Niemand zuhause → Alarm sollte scharf sein",
        "hint": "Alle weg → Alarm aktivieren sinnvoll",
    },
    {
        "condition": ("person.", "not_home"),
        "affects": "lock",
        "effect": "Niemand zuhause → Tueren sollten abgeschlossen sein",
        "hint": "Alle weg → Schloss pruefen",
    },
    {
        "condition": ("person.", "not_home"),
        "affects": "cover",
        "effect": "Niemand zuhause → Rolllaeden als Einbruchschutz",
        "hint": "Alle weg → Rolllaeden runter fuer Sicherheit",
    },
    {
        "condition": ("person.", "home"),
        "affects": "alarm_control_panel",
        "effect": "Person kommt nach Hause → Alarm deaktivieren",
        "hint": "Person da → Alarm entschaerfen",
    },

    # =====================================================================
    # 7. SICHERHEIT — RAUCH / GAS / CO / WASSER / EINBRUCH
    # =====================================================================
    {
        "condition": ("binary_sensor.smoke", "on"),
        "affects": "alarm_control_panel",
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
    },
    {
        "condition": ("binary_sensor.rauch", "on"),
        "affects": "alarm_control_panel",
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
    },
    {
        "condition": ("binary_sensor.smoke", "on"),
        "affects": "light",
        "effect": "Rauchmelder → alle Lichter an fuer Fluchtweg",
        "hint": "Rauch → Beleuchtung fuer Fluchtweg einschalten",
    },
    {
        "condition": ("binary_sensor.smoke", "on"),
        "affects": "cover",
        "effect": "Rauchmelder → Rolllaeden hoch fuer Fluchtweg",
        "hint": "Rauch → Rolllaeden oeffnen fuer Fluchtweg",
    },
    {
        "condition": ("binary_sensor.co", "on"),
        "affects": "alarm_control_panel",
        "effect": "Kohlenmonoxid erkannt → LEBENSGEFAHRLICH",
        "hint": "CO erkannt → SOFORT ALARM, Fenster oeffnen, Haus verlassen",
    },
    {
        "condition": ("binary_sensor.carbon_monoxide", "on"),
        "affects": "alarm_control_panel",
        "effect": "Kohlenmonoxid erkannt → LEBENSGEFAHRLICH",
        "hint": "CO erkannt → SOFORT ALARM, Fenster oeffnen, Haus verlassen",
    },
    {
        "condition": ("binary_sensor.co", "on"),
        "affects": "climate",
        "effect": "CO erkannt → Lueftung auf Maximum, Fenster oeffnen",
        "hint": "CO → maximale Belueftung noetig",
    },
    {
        "condition": ("binary_sensor.gas", "on"),
        "affects": "alarm_control_panel",
        "effect": "Gas erkannt → Explosionsgefahr",
        "hint": "Gas erkannt → SOFORT ALARM, kein Funke, Haus verlassen",
    },
    {
        "condition": ("binary_sensor.methane", "on"),
        "affects": "alarm_control_panel",
        "effect": "Methan/Gas erkannt → Explosionsgefahr",
        "hint": "Gas erkannt → SOFORT ALARM",
    },
    {
        "condition": ("binary_sensor.water_leak", "on"),
        "affects": "alarm_control_panel",
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM",
    },
    {
        "condition": ("binary_sensor.leck", "on"),
        "affects": "alarm_control_panel",
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM",
    },
    {
        "condition": ("binary_sensor.moisture", "on"),
        "affects": "alarm_control_panel",
        "effect": "Nasse erkannt → moeglicherweise Wasserschaden",
        "hint": "Feuchtigkeit/Naesse → Leck pruefen",
    },
    {
        "condition": ("binary_sensor.glasbruch", "on"),
        "affects": "alarm_control_panel",
        "effect": "Glasbruch erkannt → moeglicher Einbruch",
        "hint": "Glasbruch → ALARM, moeglicher Einbruch",
    },
    {
        "condition": ("binary_sensor.glass", "on"),
        "affects": "alarm_control_panel",
        "effect": "Glasbruch erkannt → moeglicher Einbruch",
        "hint": "Glasbruch → ALARM, moeglicher Einbruch",
    },
    {
        "condition": ("binary_sensor.vibration", "on"),
        "affects": "alarm_control_panel",
        "effect": "Vibration erkannt → Einbruchsversuch moeglich",
        "hint": "Vibration an Tuer/Fenster → Einbruchsversuch?",
    },
    {
        "condition": ("binary_sensor.tamper", "on"),
        "affects": "alarm_control_panel",
        "effect": "Sabotage-Kontakt ausgeloest → Manipulation",
        "hint": "Sabotage erkannt → Geraet wurde manipuliert",
    },
    {
        "condition": ("binary_sensor.sabotage", "on"),
        "affects": "alarm_control_panel",
        "effect": "Sabotage-Kontakt ausgeloest → Manipulation",
        "hint": "Sabotage erkannt → Geraet wurde manipuliert",
    },

    # =====================================================================
    # 8. MEDIEN / ENTERTAINMENT → LICHT / LAUTSTAERKE / ROLLLADEN
    # =====================================================================
    {
        "condition": ("media_player.", "playing"),
        "affects": "light",
        "effect": "Medien spielen → Kino-Modus (Licht dimmen) sinnvoll",
        "hint": "Film/Musik laeuft → Licht anpassen",
    },
    {
        "condition": ("media_player.", "playing"),
        "affects": "cover",
        "effect": "Medien spielen → Rollladen gegen Blendung",
        "hint": "TV/Film laeuft → Blendung durch Rollladen vermeiden",
    },
    {
        "condition": ("switch.tv", "on"),
        "affects": "light",
        "effect": "TV an → Licht anpassen fuer besseres Bild",
        "hint": "TV an → Licht dimmen sinnvoll",
    },
    {
        "condition": ("switch.tv", "on"),
        "affects": "cover",
        "effect": "TV an → Blendung auf Bildschirm vermeiden",
        "hint": "TV an → Rollladen gegen Blendung",
    },
    {
        "condition": ("switch.beamer", "on"),
        "affects": "light",
        "effect": "Beamer an → Raum muss komplett dunkel sein",
        "hint": "Beamer an → alles abdunkeln noetig",
    },
    {
        "condition": ("switch.beamer", "on"),
        "affects": "cover",
        "effect": "Beamer an → Rollladen komplett runter",
        "hint": "Beamer an → komplette Abdunklung noetig",
    },
    {
        "condition": ("switch.projector", "on"),
        "affects": "light",
        "effect": "Beamer an → Raum muss komplett dunkel sein",
        "hint": "Beamer an → alles abdunkeln noetig",
    },
    {
        "condition": ("switch.gaming", "on"),
        "affects": "light",
        "effect": "Gaming-PC an → Licht anpassen fuer Bildschirm",
        "hint": "Gaming-Modus → Licht dimmen sinnvoll",
    },
    {
        "condition": ("media_player.", "playing"),
        "affects": "notify",
        "effect": "Musik/Medien laufen + Fenster offen → Nachbarn stoeren",
        "hint": "Medien laut + Fenster offen → Laermbelaestigung moeglich",
    },

    # =====================================================================
    # 9. HAUSHALTSGERAETE → BENACHRICHTIGUNG / SICHERHEIT
    # =====================================================================
    {
        "condition": ("sensor.wasch", "idle"),
        "affects": "notify",
        "effect": "Waschmaschine fertig → Waesche rausholen",
        "hint": "Waschmaschine fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.washer", "idle"),
        "affects": "notify",
        "effect": "Waschmaschine fertig → Waesche rausholen",
        "hint": "Waschmaschine fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.trockner", "idle"),
        "affects": "notify",
        "effect": "Trockner fertig → Waesche rausholen",
        "hint": "Trockner fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.dryer", "idle"),
        "affects": "notify",
        "effect": "Trockner fertig → Waesche rausholen",
        "hint": "Trockner fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.geschirr", "idle"),
        "affects": "notify",
        "effect": "Geschirrspueler fertig → ausraeumen",
        "hint": "Geschirrspueler fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.dishwasher", "idle"),
        "affects": "notify",
        "effect": "Geschirrspueler fertig → ausraeumen",
        "hint": "Geschirrspueler fertig → User benachrichtigen",
    },
    {
        "condition": ("switch.backofen", "on"),
        "affects": "notify",
        "effect": "Backofen an → nicht vergessen",
        "hint": "Backofen laeuft → nicht vergessen auszumachen",
    },
    {
        "condition": ("switch.oven", "on"),
        "affects": "notify",
        "effect": "Backofen an → nicht vergessen",
        "hint": "Backofen laeuft → nicht vergessen auszumachen",
    },
    {
        "condition": ("switch.herd", "on"),
        "affects": "alarm_control_panel",
        "effect": "Herd an + niemand in Kueche → Brandgefahr",
        "hint": "Herd an → Brandgefahr wenn unbeaufsichtigt",
    },
    {
        "condition": ("switch.stove", "on"),
        "affects": "alarm_control_panel",
        "effect": "Herd an + niemand in Kueche → Brandgefahr",
        "hint": "Herd an → Brandgefahr wenn unbeaufsichtigt",
    },
    {
        "condition": ("switch.herd", "on"),
        "affects": "energy",
        "effect": "Herd an → hoher Stromverbrauch",
        "hint": "Herd laeuft → hoher Energieverbrauch",
    },
    {
        "condition": ("switch.kaffeemaschine", "on"),
        "affects": "notify",
        "effect": "Kaffeemaschine an → Kaffee fertig?",
        "hint": "Kaffeemaschine laeuft → Kaffee bald fertig",
    },
    {
        "condition": ("switch.coffee", "on"),
        "affects": "notify",
        "effect": "Kaffeemaschine an → Kaffee fertig?",
        "hint": "Kaffeemaschine laeuft → Kaffee bald fertig",
    },
    {
        "condition": ("binary_sensor.kuehlschrank", "on"),
        "affects": "notify",
        "effect": "Kuehlschrank offen → Lebensmittel verderben, Energieverlust",
        "hint": "Kuehlschrank steht offen → sofort schliessen",
    },
    {
        "condition": ("binary_sensor.fridge", "on"),
        "affects": "notify",
        "effect": "Kuehlschrank offen → Lebensmittel verderben, Energieverlust",
        "hint": "Kuehlschrank steht offen → sofort schliessen",
    },
    {
        "condition": ("sensor.freezer_temp", "on"),
        "affects": "notify",
        "effect": "Gefrierschrank Temperatur zu hoch → Lebensmittel tauen auf",
        "hint": "Gefrierschrank zu warm → Lebensmittel in Gefahr",
    },
    {
        "condition": ("sensor.gefrier", "on"),
        "affects": "notify",
        "effect": "Gefrierschrank Temperatur zu hoch → Lebensmittel tauen auf",
        "hint": "Gefrierschrank zu warm → Lebensmittel in Gefahr",
    },
    {
        "condition": ("switch.buegel", "on"),
        "affects": "alarm_control_panel",
        "effect": "Buegeleisen an → Brandgefahr wenn unbeaufsichtigt",
        "hint": "Buegeleisen an → nicht unbeaufsichtigt lassen",
    },
    {
        "condition": ("switch.iron", "on"),
        "affects": "alarm_control_panel",
        "effect": "Buegeleisen an → Brandgefahr wenn unbeaufsichtigt",
        "hint": "Buegeleisen an → nicht unbeaufsichtigt lassen",
    },

    # =====================================================================
    # 10. STAUBSAUGER / MAEHROBOTER → PRAESENZ / HAUSTIERE
    # =====================================================================
    {
        "condition": ("vacuum.", "cleaning"),
        "affects": "binary_sensor",
        "effect": "Staubsauger kann Bewegungsmelder ausloesen",
        "hint": "Saugroboter aktiv → Bewegungsmelder ignorieren",
    },
    {
        "condition": ("vacuum.", "cleaning"),
        "affects": "alarm_control_panel",
        "effect": "Saugroboter loest Bewegungsmelder aus → kein Einbruch",
        "hint": "Saugroboter aktiv → Fehlalarm vermeiden",
    },
    {
        "condition": ("vacuum.", "cleaning"),
        "affects": "notify",
        "effect": "Saugroboter laeuft → Haustiere koennten gestresst sein",
        "hint": "Saugroboter aktiv → Haustiere beachten",
    },
    {
        "condition": ("sensor.maeh", "mowing"),
        "affects": "notify",
        "effect": "Maehroboter aktiv → nicht in Garten gehen",
        "hint": "Maehroboter maewht → Vorsicht im Garten",
    },
    {
        "condition": ("sensor.mower", "mowing"),
        "affects": "notify",
        "effect": "Maehroboter aktiv → nicht in Garten gehen",
        "hint": "Maehroboter maewht → Vorsicht im Garten",
    },

    # =====================================================================
    # 11. TEMPERATUR / FROST / HITZE → KLIMA / BEWAESSERUNG
    # =====================================================================
    {
        "condition": ("binary_sensor.cold", "on"),
        "affects": "climate",
        "effect": "Frost-Warnung → Heizung sicherstellen",
        "hint": "Frost → Heizung muss laufen",
    },
    {
        "condition": ("binary_sensor.frost", "on"),
        "affects": "climate",
        "effect": "Frost erkannt → Heizung Frostschutz aktivieren",
        "hint": "Frost → Rohre und Heizung schuetzen",
    },
    {
        "condition": ("binary_sensor.frost", "on"),
        "affects": "switch",
        "effect": "Frost → Aussenbewaesserung abstellen",
        "hint": "Frost → Bewaesserung aus, Rohrbruchgefahr",
    },
    {
        "condition": ("binary_sensor.heat", "on"),
        "affects": "climate",
        "effect": "Hitze-Warnung → Kuehlung/Rollladen",
        "hint": "Hitze → Kuehlung oder Beschattung noetig",
    },
    {
        "condition": ("binary_sensor.heat", "on"),
        "affects": "cover",
        "effect": "Hitze → Rollladen/Jalousie als Sonnenschutz",
        "hint": "Hitze → Beschattung aktivieren",
    },
    {
        "condition": ("binary_sensor.heat", "on"),
        "affects": "fan",
        "effect": "Hitze → Ventilator sinnvoll",
        "hint": "Hitze → Ventilator einschalten",
    },

    # =====================================================================
    # 12. FEUCHTIGKEIT → KLIMA / LUEFTUNG / SCHIMMEL
    # =====================================================================
    {
        "condition": ("binary_sensor.moisture", "on"),
        "affects": "climate",
        "effect": "Hohe Feuchtigkeit → Lueften oder Entfeuchten",
        "hint": "Hohe Luftfeuchtigkeit → Schimmelgefahr",
    },
    {
        "condition": ("binary_sensor.feucht", "on"),
        "affects": "climate",
        "effect": "Hohe Feuchtigkeit → Lueften oder Entfeuchten",
        "hint": "Hohe Luftfeuchtigkeit → Schimmelgefahr",
    },
    {
        "condition": ("binary_sensor.moisture", "on"),
        "affects": "fan",
        "effect": "Hohe Feuchtigkeit → Bad-Luefter einschalten",
        "hint": "Feuchtigkeit hoch → Luefter an",
    },
    {
        "condition": ("sensor.humidity", "on"),
        "affects": "fan",
        "effect": "Luftfeuchtigkeit hoch → Lueftung noetig",
        "hint": "Feuchtigkeit hoch → Luefter/Fenster",
    },

    # =====================================================================
    # 13. SCHLOSS / GARAGE → SICHERHEIT
    # =====================================================================
    {
        "condition": ("lock.", "unlocked"),
        "affects": "alarm_control_panel",
        "effect": "Schloss offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Tuer nicht abgeschlossen → Sicherheit pruefen",
    },
    {
        "condition": ("lock.", "unlocked"),
        "affects": "notify",
        "effect": "Schloss offen nachts → Warnung",
        "hint": "Tuer nachts nicht abgeschlossen → Hinweis geben",
    },
    {
        "condition": ("cover.garage", "open"),
        "affects": "alarm_control_panel",
        "effect": "Garagentor offen → Sicherheitsrisiko",
        "hint": "Garage offen → Sicherheit pruefen",
    },
    {
        "condition": ("cover.garage", "open"),
        "affects": "climate",
        "effect": "Garagentor offen → Kaelte zieht in angrenzende Raeume",
        "hint": "Garage offen → beeinflusst angrenzende Raeume",
    },

    # =====================================================================
    # 14. WETTER → ROLLLADEN / MARKISE / FENSTER / BEWAESSERUNG
    # =====================================================================
    {
        "condition": ("sensor.wind_speed", "on"),
        "affects": "cover",
        "effect": "Starker Wind → Markise einfahren, Beschaedigungsgefahr",
        "hint": "Wind stark → Markise/Sonnensegel einfahren",
    },
    {
        "condition": ("binary_sensor.wind", "on"),
        "affects": "cover",
        "effect": "Windwarnung → Markise und Aussenjalousien einfahren",
        "hint": "Sturm → alle Aussenbeschattungen einfahren",
    },
    {
        "condition": ("binary_sensor.rain", "on"),
        "affects": "binary_sensor",
        "effect": "Regen → Dachfenster und offene Fenster pruefen",
        "hint": "Es regnet → Fenster pruefen, Dachfenster schliessen",
    },
    {
        "condition": ("binary_sensor.regen", "on"),
        "affects": "binary_sensor",
        "effect": "Regen → Fenster und Dachfenster pruefen",
        "hint": "Es regnet → offene Fenster schliessen",
    },
    {
        "condition": ("binary_sensor.rain", "on"),
        "affects": "cover",
        "effect": "Regen → Markise einfahren",
        "hint": "Regen → Markise einfahren",
    },
    {
        "condition": ("binary_sensor.rain", "on"),
        "affects": "switch",
        "effect": "Regen → Bewaesserung unnoetig",
        "hint": "Es regnet → Bewaesserung stoppen, Wasserverschwendung",
    },
    {
        "condition": ("binary_sensor.rain", "on"),
        "affects": "notify",
        "effect": "Regen → Waesche draussen? Dachfenster offen?",
        "hint": "Regen → Waesche reinholen, Fenster pruefen",
    },
    {
        "condition": ("sensor.uv_index", "on"),
        "affects": "cover",
        "effect": "UV-Index hoch → Beschattung sinnvoll",
        "hint": "Starke UV-Strahlung → Rolllaeden/Jalousien als Schutz",
    },
    {
        "condition": ("binary_sensor.lightning", "on"),
        "affects": "switch",
        "effect": "Gewitter → empfindliche Elektronik schuetzen",
        "hint": "Gewitter → Stecker ziehen bei empfindlichen Geraeten",
    },
    {
        "condition": ("binary_sensor.blitz", "on"),
        "affects": "switch",
        "effect": "Gewitter → empfindliche Elektronik schuetzen",
        "hint": "Gewitter → Ueberspannungsschutz beachten",
    },
    {
        "condition": ("binary_sensor.hagel", "on"),
        "affects": "cover",
        "effect": "Hagel → Markise einfahren, Jalousien schliessen",
        "hint": "Hagel → alles schuetzen, Markise rein",
    },
    {
        "condition": ("binary_sensor.hail", "on"),
        "affects": "cover",
        "effect": "Hagel → Markise einfahren, Jalousien schliessen",
        "hint": "Hagel → alles schuetzen, Markise rein",
    },
    {
        "condition": ("binary_sensor.schnee", "on"),
        "affects": "climate",
        "effect": "Schnee/Eis → Einfahrt-Heizung aktivieren",
        "hint": "Schnee → Einfahrt/Gehweg-Heizung pruefen",
    },
    {
        "condition": ("binary_sensor.snow", "on"),
        "affects": "climate",
        "effect": "Schnee/Eis → Einfahrt-Heizung aktivieren",
        "hint": "Schnee → Einfahrt/Gehweg-Heizung pruefen",
    },

    # =====================================================================
    # 15. DUNSTABZUG / LUEFTUNG / KAMIN → FENSTER (UNTERDRUCK!)
    # =====================================================================
    {
        "condition": ("switch.dunstabzug", "on"),
        "affects": "binary_sensor",
        "effect": "Dunstabzug (Abluft) an → Fenster muss offen sein wegen Unterdruck",
        "hint": "Dunstabzug an → Fenster oeffnen! Unterdruck-Gefahr",
    },
    {
        "condition": ("switch.abzug", "on"),
        "affects": "binary_sensor",
        "effect": "Dunstabzug (Abluft) an → Zuluft noetig",
        "hint": "Abzugshaube an → Fenster oeffnen fuer Zuluft",
    },
    {
        "condition": ("switch.hood", "on"),
        "affects": "binary_sensor",
        "effect": "Range hood on → need fresh air supply",
        "hint": "Dunstabzug an → Fenster oeffnen wegen Unterdruck",
    },
    {
        "condition": ("switch.exhaust", "on"),
        "affects": "binary_sensor",
        "effect": "Abluft an → Zuluft noetig, Unterdruck vermeiden",
        "hint": "Abluft laeuft → Fenster oeffnen",
    },
    {
        "condition": ("switch.kamin", "on"),
        "affects": "binary_sensor",
        "effect": "Kamin/Ofen an → Fenster fuer Zuluft noetig",
        "hint": "Kamin an → Zuluft sicherstellen, Erstickungsgefahr",
    },
    {
        "condition": ("switch.fireplace", "on"),
        "affects": "binary_sensor",
        "effect": "Kamin an → Zuluft noetig",
        "hint": "Kamin an → Fenster fuer Zuluft oeffnen",
    },
    {
        "condition": ("switch.kamin", "on"),
        "affects": "alarm_control_panel",
        "effect": "Kamin an → Rauchmelder koennte ausloesen",
        "hint": "Kamin an → Rauchmelder in der Naehe koennten reagieren",
    },
    {
        "condition": ("switch.kamin", "on"),
        "affects": "climate",
        "effect": "Kamin an → Raumtemperatur steigt stark",
        "hint": "Kamin an → Heizung runterdrehen, Kamin heizt mit",
    },
    {
        "condition": ("climate.lueftung", "on"),
        "affects": "binary_sensor",
        "effect": "Kontrollierte Wohnraumlueftung aktiv → Fenster zu halten",
        "hint": "KWL laeuft → Fenster zu fuer optimale Lueftung",
    },
    {
        "condition": ("fan.lueftung", "on"),
        "affects": "binary_sensor",
        "effect": "Lueftungsanlage aktiv → Fenster zu halten fuer Effizienz",
        "hint": "Lueftung aktiv → Fenster zu lassen",
    },

    # =====================================================================
    # 16. SCHLAF / BETT / WECKER → KOMFORT
    # =====================================================================
    {
        "condition": ("binary_sensor.bett", "on"),
        "affects": "light",
        "effect": "Im Bett → Lichter sollten aus sein",
        "hint": "Bett belegt → Lichter ausschalten",
    },
    {
        "condition": ("binary_sensor.bed", "on"),
        "affects": "light",
        "effect": "Im Bett → Lichter sollten aus sein",
        "hint": "Bett belegt → Lichter ausschalten",
    },
    {
        "condition": ("binary_sensor.bett", "on"),
        "affects": "media_player",
        "effect": "Im Bett → Medien leiser oder aus",
        "hint": "Schlafenszeit → Medien runterdrehen",
    },
    {
        "condition": ("binary_sensor.bett", "on"),
        "affects": "climate",
        "effect": "Im Bett → Schlaftemperatur einstellen (kuehler)",
        "hint": "Schlafenszeit → Temperatur fuer Schlaf anpassen",
    },
    {
        "condition": ("binary_sensor.bett", "on"),
        "affects": "cover",
        "effect": "Im Bett → Rolllaeden sollten zu sein",
        "hint": "Schlafenszeit → Rolllaeden schliessen",
    },
    {
        "condition": ("binary_sensor.bett", "on"),
        "affects": "lock",
        "effect": "Im Bett → Tueren sollten abgeschlossen sein",
        "hint": "Schlafenszeit → Tueren abschliessen",
    },
    {
        "condition": ("input_boolean.sleep", "on"),
        "affects": "light",
        "effect": "Schlafmodus aktiv → alles aus",
        "hint": "Schlafmodus → alle Lichter aus",
    },
    {
        "condition": ("input_boolean.schlaf", "on"),
        "affects": "light",
        "effect": "Schlafmodus aktiv → alles aus",
        "hint": "Schlafmodus → alle Lichter aus",
    },
    {
        "condition": ("input_boolean.sleep", "on"),
        "affects": "media_player",
        "effect": "Schlafmodus → Medien aus",
        "hint": "Schlafmodus → alle Medien stoppen",
    },
    {
        "condition": ("sensor.wecker", "on"),
        "affects": "cover",
        "effect": "Wecker klingelt → Rolllaeden oeffnen",
        "hint": "Wecker → Rolllaeden hoch, Tag beginnt",
    },
    {
        "condition": ("sensor.alarm_clock", "on"),
        "affects": "cover",
        "effect": "Wecker klingelt → Rolllaeden oeffnen",
        "hint": "Wecker → Rolllaeden hoch, Tag beginnt",
    },
    {
        "condition": ("sensor.wecker", "on"),
        "affects": "light",
        "effect": "Wecker klingelt → sanftes Aufwachlicht",
        "hint": "Wecker → Licht langsam hochfahren",
    },
    {
        "condition": ("binary_sensor.baby", "on"),
        "affects": "media_player",
        "effect": "Baby-Monitor aktiv → Lautstaerke reduzieren",
        "hint": "Baby schlaeft → leise sein, Medien runter",
    },
    {
        "condition": ("binary_sensor.baby_monitor", "on"),
        "affects": "media_player",
        "effect": "Baby-Monitor aktiv → Lautstaerke reduzieren",
        "hint": "Baby schlaeft → Medien leiser",
    },

    # =====================================================================
    # 17. ALARM / SICHERHEITSSYSTEM → LICHT / KAMERA / SIRENE
    # =====================================================================
    {
        "condition": ("alarm_control_panel.", "armed_away"),
        "affects": "light",
        "effect": "Alarm scharf (abwesend) → Praesenz simulieren",
        "hint": "Alarm scharf → Licht-Simulation gegen Einbruch",
    },
    {
        "condition": ("alarm_control_panel.", "armed_away"),
        "affects": "cover",
        "effect": "Alarm scharf (abwesend) → Rolllaeden als Schutz",
        "hint": "Alarm scharf → Rolllaeden runter fuer Sichtschutz",
    },
    {
        "condition": ("alarm_control_panel.", "armed_night"),
        "affects": "light",
        "effect": "Nacht-Alarm → Nachtlicht/Orientierung",
        "hint": "Nachtalarm aktiv → nur Orientierungslicht",
    },
    {
        "condition": ("alarm_control_panel.", "armed_night"),
        "affects": "lock",
        "effect": "Nacht-Alarm → alle Tueren abgeschlossen",
        "hint": "Nachtalarm → Schloss pruefen",
    },
    {
        "condition": ("alarm_control_panel.", "triggered"),
        "affects": "light",
        "effect": "Alarm ausgeloest → alle Lichter an",
        "hint": "ALARM AUSGELOEST → alle Lichter an zur Abschreckung",
    },
    {
        "condition": ("alarm_control_panel.", "triggered"),
        "affects": "notify",
        "effect": "Alarm ausgeloest → sofort benachrichtigen",
        "hint": "ALARM → sofortige Benachrichtigung",
    },

    # =====================================================================
    # 18. WALLBOX / E-AUTO → ENERGIE / PV
    # =====================================================================
    {
        "condition": ("sensor.wallbox", "charging"),
        "affects": "energy",
        "effect": "E-Auto laedt → sehr hoher Stromverbrauch (11-22kW)",
        "hint": "Wallbox laedt → hoher Stromverbrauch",
    },
    {
        "condition": ("sensor.charger", "charging"),
        "affects": "energy",
        "effect": "E-Auto laedt → sehr hoher Stromverbrauch",
        "hint": "E-Auto laedt → hoher Stromverbrauch",
    },
    {
        "condition": ("sensor.wallbox", "charging"),
        "affects": "climate",
        "effect": "Wallbox + Waermepumpe gleichzeitig → moegliche Ueberlast",
        "hint": "Wallbox laedt → Netzueberlast moeglich mit Waermepumpe",
    },
    {
        "condition": ("binary_sensor.ev_connected", "on"),
        "affects": "energy",
        "effect": "E-Auto angeschlossen → PV-Ueberschussladen moeglich",
        "hint": "E-Auto angesteckt → bei PV-Ueberschuss laden",
    },

    # =====================================================================
    # 19. SOLAR / PV / BATTERIE → ENERGIE / GERAETE
    # =====================================================================
    {
        "condition": ("sensor.solar", "on"),
        "affects": "energy",
        "effect": "PV produziert → Eigenverbrauch optimieren",
        "hint": "Sonne scheint, PV produziert → Geraete jetzt laufen lassen",
    },
    {
        "condition": ("sensor.pv", "on"),
        "affects": "energy",
        "effect": "PV-Anlage produziert → Eigenverbrauch optimieren",
        "hint": "PV-Produktion → Geraete jetzt einschalten",
    },
    {
        "condition": ("sensor.battery_level", "on"),
        "affects": "energy",
        "effect": "Hausspeicher-Status beeinflusst Energiestrategie",
        "hint": "Batteriestand → Lade-/Entladestrategie anpassen",
    },
    {
        "condition": ("sensor.grid_export", "on"),
        "affects": "energy",
        "effect": "Strom wird ins Netz eingespeist → Eigenverbrauch erhoehen",
        "hint": "Einspeisung → besser selbst verbrauchen",
    },

    # =====================================================================
    # 20. BEWAESSERUNG / GARTEN → WETTER / WASSER
    # =====================================================================
    {
        "condition": ("switch.bewaesserung", "on"),
        "affects": "notify",
        "effect": "Bewaesserung laeuft → Wasserverbrauch",
        "hint": "Bewaesserung an → Wasserverbrauch beachten",
    },
    {
        "condition": ("switch.irrigation", "on"),
        "affects": "notify",
        "effect": "Bewaesserung laeuft → Wasserverbrauch",
        "hint": "Bewaesserung an → Wasserverbrauch beachten",
    },
    {
        "condition": ("switch.sprinkler", "on"),
        "affects": "notify",
        "effect": "Sprinkler laeuft → nicht in Garten gehen",
        "hint": "Sprinkler aktiv → Achtung nass",
    },

    # =====================================================================
    # 21. POOL / WHIRLPOOL → TEMPERATUR / ENERGIE
    # =====================================================================
    {
        "condition": ("switch.pool_pump", "on"),
        "affects": "energy",
        "effect": "Pool-Pumpe an → Stromverbrauch",
        "hint": "Pool-Pumpe laeuft → Stromverbrauch beachten",
    },
    {
        "condition": ("switch.pool_heizung", "on"),
        "affects": "energy",
        "effect": "Pool-Heizung an → sehr hoher Energieverbrauch",
        "hint": "Pool wird geheizt → hoher Energieverbrauch",
    },
    {
        "condition": ("switch.whirlpool", "on"),
        "affects": "energy",
        "effect": "Whirlpool/Jacuzzi an → hoher Stromverbrauch",
        "hint": "Whirlpool laeuft → Energieverbrauch beachten",
    },
    {
        "condition": ("cover.pool", "open"),
        "affects": "energy",
        "effect": "Poolabdeckung offen + Nacht → Waermeverlust",
        "hint": "Pool offen nachts → Waerme geht verloren",
    },

    # =====================================================================
    # 22. TUERKLINGEL / GEGENSPRECH → KAMERA / LICHT
    # =====================================================================
    {
        "condition": ("binary_sensor.doorbell", "on"),
        "affects": "notify",
        "effect": "Tuerklingel → jemand steht vor der Tuer",
        "hint": "Klingel → Besucher an der Tuer",
    },
    {
        "condition": ("binary_sensor.klingel", "on"),
        "affects": "notify",
        "effect": "Tuerklingel → jemand steht vor der Tuer",
        "hint": "Klingel → Besucher an der Tuer",
    },
    {
        "condition": ("binary_sensor.doorbell", "on"),
        "affects": "light",
        "effect": "Klingel nachts → Aussenlicht an",
        "hint": "Klingel → Eingangsbereich beleuchten",
    },
    {
        "condition": ("binary_sensor.doorbell", "on"),
        "affects": "camera",
        "effect": "Klingel → Kamerabild anzeigen/aufnehmen",
        "hint": "Klingel → Tuerkamera aktivieren",
    },
    {
        "condition": ("binary_sensor.paketbox", "on"),
        "affects": "notify",
        "effect": "Paketbox geoeffnet → Paket eingeworfen",
        "hint": "Paketbox → Paket wurde geliefert",
    },
    {
        "condition": ("binary_sensor.mailbox", "on"),
        "affects": "notify",
        "effect": "Briefkasten geoeffnet → Post da",
        "hint": "Briefkasten → Post eingeworfen",
    },
    {
        "condition": ("binary_sensor.briefkasten", "on"),
        "affects": "notify",
        "effect": "Briefkasten geoeffnet → Post da",
        "hint": "Briefkasten → Post wurde eingeworfen",
    },

    # =====================================================================
    # 23. BATTERIEN / AKKUS → WARTUNG / AUSFALL
    # =====================================================================
    {
        "condition": ("binary_sensor.battery_low", "on"),
        "affects": "notify",
        "effect": "Batterie niedrig → Geraet bald offline",
        "hint": "Batterie schwach → Batterie wechseln bevor Geraet ausfaellt",
    },
    {
        "condition": ("binary_sensor.low_battery", "on"),
        "affects": "notify",
        "effect": "Batterie niedrig → Geraet funktioniert bald nicht mehr",
        "hint": "Batterie fast leer → zeitnah wechseln",
    },
    {
        "condition": ("binary_sensor.batterie", "on"),
        "affects": "notify",
        "effect": "Batterie-Warnung → Geraet bald offline",
        "hint": "Batterie-Warnung → Batterie tauschen",
    },

    # =====================================================================
    # 24. NETZWERK / CONNECTIVITY → GERAETE-AUSFALL
    # =====================================================================
    {
        "condition": ("binary_sensor.router", "off"),
        "affects": "notify",
        "effect": "Router offline → alle WLAN-Geraete ohne Verbindung",
        "hint": "Router offline → Internet und WLAN-Geraete betroffen",
    },
    {
        "condition": ("binary_sensor.internet", "off"),
        "affects": "notify",
        "effect": "Internet ausgefallen → Cloud-Dienste nicht erreichbar",
        "hint": "Kein Internet → Cloud-Geraete funktionieren nicht",
    },
    {
        "condition": ("binary_sensor.zigbee", "off"),
        "affects": "notify",
        "effect": "Zigbee-Coordinator offline → alle Zigbee-Geraete betroffen",
        "hint": "Zigbee offline → Sensoren und Aktoren ausgefallen",
    },
    {
        "condition": ("binary_sensor.zwave", "off"),
        "affects": "notify",
        "effect": "Z-Wave Stick offline → alle Z-Wave Geraete betroffen",
        "hint": "Z-Wave offline → Geraete reagieren nicht",
    },
    {
        "condition": ("binary_sensor.repeater", "off"),
        "affects": "notify",
        "effect": "WLAN-Repeater offline → entfernte Geraete ohne Verbindung",
        "hint": "Repeater offline → WLAN-Geraete in Reichweite betroffen",
    },
    {
        "condition": ("binary_sensor.hue_bridge", "off"),
        "affects": "light",
        "effect": "Hue Bridge offline → alle Hue-Lampen nicht steuerbar",
        "hint": "Hue Bridge offline → Philips Hue Lichter reagieren nicht",
    },
    {
        "condition": ("binary_sensor.bridge", "off"),
        "affects": "notify",
        "effect": "Smart Home Bridge offline → angeschlossene Geraete betroffen",
        "hint": "Bridge offline → verbundene Geraete reagieren nicht",
    },

    # =====================================================================
    # 25. HAUSTIERE → TUEREN / KLIMA / FUTTER
    # =====================================================================
    {
        "condition": ("binary_sensor.katzenklappe", "on"),
        "affects": "climate",
        "effect": "Katzenklappe offen → Waermeverlust",
        "hint": "Katzenklappe offen → Zugluft und Waermeverlust",
    },
    {
        "condition": ("binary_sensor.pet_door", "on"),
        "affects": "climate",
        "effect": "Tiertuer offen → Waermeverlust",
        "hint": "Haustiertuer offen → Energie geht verloren",
    },
    {
        "condition": ("sensor.futter", "on"),
        "affects": "notify",
        "effect": "Futternapf leer → Tier fuettern",
        "hint": "Futter leer → Haustier fuettern",
    },
    {
        "condition": ("sensor.pet_feeder", "on"),
        "affects": "notify",
        "effect": "Futterspender leer → nachfuellen",
        "hint": "Futterspender → nachfuellen noetig",
    },

    # =====================================================================
    # 26. AQUARIUM / TERRARIUM → TEMPERATUR / LICHT / PUMPE
    # =====================================================================
    {
        "condition": ("switch.aquarium_heizung", "off"),
        "affects": "notify",
        "effect": "Aquarium-Heizung aus → Fische in Gefahr",
        "hint": "Aquarium-Heizung aus → Wassertemperatur sinkt, Fische gefaehrdet",
    },
    {
        "condition": ("switch.aquarium_filter", "off"),
        "affects": "notify",
        "effect": "Aquarium-Filter aus → Wasserqualitaet verschlechtert sich",
        "hint": "Aquarium-Filter aus → Wasser wird schlecht, sofort pruefen",
    },
    {
        "condition": ("switch.aquarium_licht", "off"),
        "affects": "notify",
        "effect": "Aquarium-Licht aus → Pflanzen brauchen Licht",
        "hint": "Aquarium-Licht aus → Pflanzenwachstum gestroert",
    },
    {
        "condition": ("switch.terrarium", "off"),
        "affects": "notify",
        "effect": "Terrarium-Technik aus → Tier-Wohlbefinden gefaehrdet",
        "hint": "Terrarium aus → Temperatur/UV-Licht pruefen",
    },

    # =====================================================================
    # 27. SERVER / NAS / TECHNIK → TEMPERATUR / STROM
    # =====================================================================
    {
        "condition": ("sensor.server_temp", "on"),
        "affects": "climate",
        "effect": "Serverraum zu warm → Kuehlung noetig",
        "hint": "Server-Temperatur hoch → Kuehlung verstaerken",
    },
    {
        "condition": ("binary_sensor.nas", "off"),
        "affects": "notify",
        "effect": "NAS offline → Backups und Medien nicht verfuegbar",
        "hint": "NAS offline → Datensicherung betroffen",
    },
    {
        "condition": ("sensor.usv", "on"),
        "affects": "notify",
        "effect": "USV auf Batterie → Stromausfall erkannt",
        "hint": "USV-Batterie aktiv → Strom ist ausgefallen",
    },
    {
        "condition": ("sensor.ups", "on"),
        "affects": "notify",
        "effect": "USV auf Batterie → Stromausfall",
        "hint": "USV aktiv → Stromausfall erkannt",
    },
    {
        "condition": ("binary_sensor.usv_battery_low", "on"),
        "affects": "notify",
        "effect": "USV Batterie niedrig → Server bald ohne Strom",
        "hint": "USV-Batterie fast leer → Server herunterfahren",
    },

    # =====================================================================
    # 28. 3D-DRUCKER / WERKSTATT → LUEFTUNG / SICHERHEIT
    # =====================================================================
    {
        "condition": ("switch.3d_drucker", "on"),
        "affects": "fan",
        "effect": "3D-Drucker an → Daempfe, Lueftung noetig",
        "hint": "3D-Drucker druckt → Lueftung einschalten wegen Daempfe",
    },
    {
        "condition": ("switch.3d_printer", "on"),
        "affects": "fan",
        "effect": "3D-Drucker an → Lueftung fuer Daempfe",
        "hint": "3D-Drucker → Abluft/Lueftung einschalten",
    },
    {
        "condition": ("sensor.3d_drucker", "idle"),
        "affects": "notify",
        "effect": "3D-Druck fertig → Teil entnehmen",
        "hint": "3D-Druck fertig → Druckteil entnehmen",
    },
    {
        "condition": ("sensor.3d_printer", "idle"),
        "affects": "notify",
        "effect": "3D-Druck fertig → Teil entnehmen",
        "hint": "3D-Druck fertig → Druckteil entnehmen",
    },
    {
        "condition": ("switch.loetstation", "on"),
        "affects": "fan",
        "effect": "Loetstation an → Abzug noetig wegen Daempfe",
        "hint": "Loetstation an → Loetdampf-Absaugung einschalten",
    },
    {
        "condition": ("switch.soldering", "on"),
        "affects": "fan",
        "effect": "Loetstation an → Lueftung fuer Loetdaempfe",
        "hint": "Loetstation → Absaugung einschalten",
    },
    {
        "condition": ("switch.laser", "on"),
        "affects": "fan",
        "effect": "Lasercutter an → starke Abluft noetig",
        "hint": "Laser laeuft → Abluft zwingend noetig",
    },

    # =====================================================================
    # 29. BADEZIMMER → FEUCHTIGKEIT / LUEFTUNG / SCHIMMEL
    # =====================================================================
    {
        "condition": ("binary_sensor.dusche", "on"),
        "affects": "fan",
        "effect": "Dusche benutzt → Bad-Luefter einschalten",
        "hint": "Dusche laeuft → Luefter an gegen Feuchtigkeit",
    },
    {
        "condition": ("binary_sensor.shower", "on"),
        "affects": "fan",
        "effect": "Dusche benutzt → Bad-Luefter einschalten",
        "hint": "Dusche laeuft → Luefter an gegen Feuchtigkeit",
    },
    {
        "condition": ("binary_sensor.badewanne", "on"),
        "affects": "fan",
        "effect": "Badewanne benutzt → Feuchtigkeit steigt stark",
        "hint": "Bad wird genommen → Luefter/Fenster oeffnen",
    },
    {
        "condition": ("switch.handtuch", "on"),
        "affects": "energy",
        "effect": "Handtuchheizung an → Stromverbrauch",
        "hint": "Handtuchheizung laeuft → Stromverbrauch beachten",
    },
    {
        "condition": ("switch.towel", "on"),
        "affects": "energy",
        "effect": "Handtuchheizung an → Stromverbrauch",
        "hint": "Handtuchtrockner an → Stromverbrauch",
    },

    # =====================================================================
    # 30. LUFTQUALITAET → LUEFTUNG / FENSTER / GESUNDHEIT
    # =====================================================================
    {
        "condition": ("sensor.co2", "on"),
        "affects": "climate",
        "effect": "CO2-Wert hoch → dringend lueften",
        "hint": "CO2 hoch → Fenster oeffnen, Luft ist verbraucht",
    },
    {
        "condition": ("sensor.carbon_dioxide", "on"),
        "affects": "climate",
        "effect": "CO2 hoch → Lueftung noetig",
        "hint": "CO2 hoch → Frischluftzufuhr noetig",
    },
    {
        "condition": ("sensor.voc", "on"),
        "affects": "climate",
        "effect": "VOC hoch → Schadstoffe in der Luft, lueften",
        "hint": "VOC hoch → Lueften, Schadstoffe in der Luft",
    },
    {
        "condition": ("sensor.pm25", "on"),
        "affects": "binary_sensor",
        "effect": "Feinstaub hoch draussen → Fenster geschlossen halten",
        "hint": "Feinstaub draussen hoch → Fenster zu lassen",
    },
    {
        "condition": ("sensor.feinstaub", "on"),
        "affects": "binary_sensor",
        "effect": "Feinstaub hoch → Fenster geschlossen halten",
        "hint": "Feinstaub hoch → Fenster zu, Luftreiniger an",
    },
    {
        "condition": ("sensor.pollen", "on"),
        "affects": "binary_sensor",
        "effect": "Pollenflug hoch → Fenster zu fuer Allergiker",
        "hint": "Pollenflug → Fenster geschlossen halten",
    },
    {
        "condition": ("sensor.aqi", "on"),
        "affects": "binary_sensor",
        "effect": "Luftqualitaetsindex schlecht → Fenster geschlossen",
        "hint": "Luftqualitaet draussen schlecht → Fenster zu",
    },
    {
        "condition": ("switch.luftreiniger", "on"),
        "affects": "energy",
        "effect": "Luftreiniger an → Stromverbrauch",
        "hint": "Luftreiniger laeuft → Stromverbrauch",
    },
    {
        "condition": ("switch.air_purifier", "on"),
        "affects": "energy",
        "effect": "Luftreiniger an → Stromverbrauch",
        "hint": "Luftreiniger laeuft → Stromverbrauch beachten",
    },

    # =====================================================================
    # 31. STROMAUSFALL / USV → KRITISCHE SYSTEME
    # =====================================================================
    {
        "condition": ("binary_sensor.power_outage", "on"),
        "affects": "notify",
        "effect": "Stromausfall → nur kritische Systeme betreiben",
        "hint": "Stromausfall → Kuehlung, Sicherheit priorisieren",
    },
    {
        "condition": ("binary_sensor.stromausfall", "on"),
        "affects": "notify",
        "effect": "Stromausfall erkannt → Notbetrieb",
        "hint": "Strom weg → USV/Generator, kritische Geraete pruefen",
    },
    {
        "condition": ("switch.generator", "on"),
        "affects": "notify",
        "effect": "Generator laeuft → Stromausfall, Notstrom aktiv",
        "hint": "Generator laeuft → Stromausfall wird ueberbrueckt",
    },
    {
        "condition": ("switch.notstrom", "on"),
        "affects": "energy",
        "effect": "Notstromversorgung aktiv → nur noetige Geraete betreiben",
        "hint": "Notstrom → unnoetige Verbraucher abschalten",
    },

    # =====================================================================
    # 32. SAUNA → ENERGIE / SICHERHEIT / LUEFTUNG
    # =====================================================================
    {
        "condition": ("switch.sauna", "on"),
        "affects": "energy",
        "effect": "Sauna an → sehr hoher Energieverbrauch (6-9kW)",
        "hint": "Sauna heizt → extrem hoher Stromverbrauch",
    },
    {
        "condition": ("switch.sauna", "on"),
        "affects": "notify",
        "effect": "Sauna an → nicht vergessen, Timer beachten",
        "hint": "Sauna laeuft → nicht vergessen auszumachen",
    },
    {
        "condition": ("switch.sauna", "on"),
        "affects": "fan",
        "effect": "Sauna an → danach Lueftung noetig",
        "hint": "Sauna → nach Benutzung gut lueften",
    },

    # =====================================================================
    # 33. WAERMEPUMPE → ENERGIE / KLIMA / LAUTSTAERKE
    # =====================================================================
    {
        "condition": ("climate.waermepumpe", "heat"),
        "affects": "energy",
        "effect": "Waermepumpe heizt → Stromverbrauch je nach COP",
        "hint": "Waermepumpe aktiv → Stromverbrauch beachten",
    },
    {
        "condition": ("climate.heat_pump", "heat"),
        "affects": "energy",
        "effect": "Waermepumpe heizt → Stromverbrauch",
        "hint": "Waermepumpe laeuft → Energieverbrauch",
    },
    {
        "condition": ("climate.waermepumpe", "heat"),
        "affects": "notify",
        "effect": "Waermepumpe nachts → Laermbelaestigung Nachbarn moeglich",
        "hint": "Waermepumpe nachts → Nachbarn koennten sich beschweren",
    },
    {
        "condition": ("binary_sensor.defrost", "on"),
        "affects": "energy",
        "effect": "Waermepumpe im Abtaumodus → kurzzeitig ineffizient",
        "hint": "Waermepumpe taut ab → normal bei Frost, kurz ineffizient",
    },

    # =====================================================================
    # 34. SMARTE STECKDOSEN → ENERGIE / STANDBY
    # =====================================================================
    {
        "condition": ("switch.steckdose", "on"),
        "affects": "energy",
        "effect": "Smarte Steckdose an → Geraet verbraucht Strom",
        "hint": "Steckdose aktiv → Verbrauch beachten",
    },
    {
        "condition": ("switch.plug", "on"),
        "affects": "energy",
        "effect": "Smarte Steckdose an → Standby-Verbrauch moeglich",
        "hint": "Steckdose an → Standby-Verbrauch pruefen",
    },

    # =====================================================================
    # 35. MUELL / ABFALL → BENACHRICHTIGUNG
    # =====================================================================
    {
        "condition": ("sensor.muell", "on"),
        "affects": "notify",
        "effect": "Muellabfuhr morgen → Tonne rausstellen",
        "hint": "Muellabfuhr → Tonnen rausstellen nicht vergessen",
    },
    {
        "condition": ("sensor.waste", "on"),
        "affects": "notify",
        "effect": "Muellabfuhr → Tonnen rausstellen",
        "hint": "Abfuhr morgen → Tonnen raus",
    },
    {
        "condition": ("sensor.gelber_sack", "on"),
        "affects": "notify",
        "effect": "Gelber Sack Abholung → rausstellen",
        "hint": "Gelber Sack → morgen Abholung",
    },
    {
        "condition": ("sensor.papier", "on"),
        "affects": "notify",
        "effect": "Papiertonne Abholung → rausstellen",
        "hint": "Papiertonne → morgen Abholung",
    },
    {
        "condition": ("sensor.bio", "on"),
        "affects": "notify",
        "effect": "Biotonne Abholung → rausstellen",
        "hint": "Biotonne → morgen Abholung",
    },

    # =====================================================================
    # 36. VENTILATOR / LUEFTER → ENERGIE / KOMFORT
    # =====================================================================
    {
        "condition": ("fan.", "on"),
        "affects": "energy",
        "effect": "Ventilator an → Stromverbrauch",
        "hint": "Ventilator laeuft → Stromverbrauch",
    },
    {
        "condition": ("fan.", "on"),
        "affects": "climate",
        "effect": "Ventilator an → gefuehlte Temperatur sinkt",
        "hint": "Ventilator → kuehlt nicht, aber gefuehlt kuehler",
    },

    # =====================================================================
    # 37. AUSSENBEWEGUNG / EINFAHRT → LICHT / KAMERA
    # =====================================================================
    {
        "condition": ("binary_sensor.einfahrt", "on"),
        "affects": "light",
        "effect": "Bewegung Einfahrt → Aussenbeleuchtung",
        "hint": "Bewegung in Einfahrt → Licht einschalten",
    },
    {
        "condition": ("binary_sensor.driveway", "on"),
        "affects": "light",
        "effect": "Bewegung Einfahrt → Aussenbeleuchtung",
        "hint": "Bewegung Einfahrt → Aussenlicht an",
    },
    {
        "condition": ("binary_sensor.einfahrt", "on"),
        "affects": "camera",
        "effect": "Bewegung Einfahrt → Kamera aufnehmen",
        "hint": "Bewegung Einfahrt → Kamera pruefen",
    },
    {
        "condition": ("binary_sensor.garten", "on"),
        "affects": "light",
        "effect": "Bewegung im Garten → Gartenbeleuchtung",
        "hint": "Bewegung Garten → Aussenlicht an",
    },
    {
        "condition": ("binary_sensor.garden", "on"),
        "affects": "light",
        "effect": "Bewegung Garten → Gartenbeleuchtung",
        "hint": "Bewegung Garten nachts → Licht einschalten",
    },

    # =====================================================================
    # 38. RASENMAEHROBOTER → WETTER / GARTEN
    # =====================================================================
    {
        "condition": ("sensor.maehroboter", "mowing"),
        "affects": "notify",
        "effect": "Maehroboter faehrt → Vorsicht Kinder/Haustiere",
        "hint": "Maehroboter aktiv → Kinder und Haustiere fernhalten",
    },
    {
        "condition": ("sensor.lawn_mower", "mowing"),
        "affects": "notify",
        "effect": "Rasenmaehroboter aktiv → Vorsicht im Garten",
        "hint": "Maehroboter → Vorsicht im Garten",
    },

    # =====================================================================
    # 39. WASSER-HAUPTVENTIL → SICHERHEIT
    # =====================================================================
    {
        "condition": ("switch.wasser_hauptventil", "off"),
        "affects": "notify",
        "effect": "Wasser-Hauptventil zu → kein Wasser im Haus",
        "hint": "Wasser abgedreht → Wasserhahn funktioniert nicht",
    },
    {
        "condition": ("switch.water_main", "off"),
        "affects": "notify",
        "effect": "Wasser-Hauptventil geschlossen → kein Wasser",
        "hint": "Wasser abgedreht → kein Wasser im Haus",
    },
    {
        "condition": ("switch.wasser_hauptventil", "off"),
        "affects": "climate",
        "effect": "Wasser abgedreht → Heizung ohne Wasser problematisch",
        "hint": "Wasser aus → Heizungsanlage pruefen",
    },

    # =====================================================================
    # 40. ELEKTROAUTO / GARAGE → SICHERHEIT / KOMFORT
    # =====================================================================
    {
        "condition": ("cover.garage", "open"),
        "affects": "notify",
        "effect": "Garage offen + Nacht → vergessen zu schliessen?",
        "hint": "Garage nachts offen → vergessen?",
    },
    {
        "condition": ("binary_sensor.car", "not_home"),
        "affects": "cover",
        "effect": "Auto weg + Garage offen → vergessen zu schliessen",
        "hint": "Auto weg, Garage offen → schliessen vergessen?",
    },

    # =====================================================================
    # 41. DURCHZUG / RAUM-WECHSELWIRKUNGEN
    # =====================================================================
    {
        "condition": ("binary_sensor.fenster", "on"),
        "affects": "fan",
        "effect": "Fenster offen + Ventilator → Durchzug entsteht",
        "hint": "Fenster offen + Ventilator → starker Durchzug, Tueren koennen zuschlagen",
    },
    {
        "condition": ("binary_sensor.window", "on"),
        "affects": "fan",
        "effect": "Fenster offen + Ventilator → Durchzug",
        "hint": "Fenster offen + Ventilator → Durchzug entsteht",
    },
    {
        "condition": ("binary_sensor.fenster", "on"),
        "affects": "notify",
        "effect": "Mehrere Fenster offen → Durchzug im ganzen Haus",
        "hint": "Mehrere Fenster offen → Durchzug, Tueren knallen",
    },
    {
        "condition": ("binary_sensor.tuer", "on"),
        "affects": "climate",
        "effect": "Zimmertuer offen → Temperatur gleicht sich zwischen Raeumen an",
        "hint": "Tuer offen → Raumtemperaturen mischen sich",
    },

    # =====================================================================
    # 42. TEICHPUMPE / BRUNNEN / WASSERSPIEL
    # =====================================================================
    {
        "condition": ("switch.teichpumpe", "on"),
        "affects": "energy",
        "effect": "Teichpumpe an → Dauerstromverbrauch",
        "hint": "Teichpumpe laeuft → Stromverbrauch beachten",
    },
    {
        "condition": ("switch.pond_pump", "on"),
        "affects": "energy",
        "effect": "Teichpumpe an → Dauerstromverbrauch",
        "hint": "Teichpumpe laeuft → dauerhafter Stromverbrauch",
    },
    {
        "condition": ("switch.teichpumpe", "off"),
        "affects": "notify",
        "effect": "Teichpumpe aus → Wasserqualitaet verschlechtert sich",
        "hint": "Teichpumpe aus → Fische brauchen Sauerstoff",
    },
    {
        "condition": ("switch.brunnen", "on"),
        "affects": "energy",
        "effect": "Brunnen/Wasserspiel an → Stromverbrauch",
        "hint": "Brunnen laeuft → Stromverbrauch",
    },
    {
        "condition": ("switch.fountain", "on"),
        "affects": "energy",
        "effect": "Brunnen/Wasserspiel an → Stromverbrauch",
        "hint": "Wasserspiel laeuft → Stromverbrauch",
    },
    {
        "condition": ("switch.brunnen", "on"),
        "affects": "notify",
        "effect": "Brunnen bei Frost → Einfrieren, Beschaedigung",
        "hint": "Brunnen bei Frost → kann einfrieren und kaputtgehen",
    },

    # =====================================================================
    # 43. ZISTERNE / REGENWASSER / WASSERENTHAERTUNG
    # =====================================================================
    {
        "condition": ("sensor.zisterne", "on"),
        "affects": "switch",
        "effect": "Zisterne leer → Bewaesserung auf Leitungswasser umschalten",
        "hint": "Zisterne leer → kein Regenwasser mehr, Leitungswasser noetig",
    },
    {
        "condition": ("sensor.cistern", "on"),
        "affects": "switch",
        "effect": "Zisterne-Fuellstand → Bewaesserungsstrategie anpassen",
        "hint": "Zisterne Fuellstand → Wassernutzung optimieren",
    },
    {
        "condition": ("sensor.zisterne", "on"),
        "affects": "notify",
        "effect": "Zisterne voll → bei Regen laeuft sie ueber",
        "hint": "Zisterne voll → Ueberlauf bei weiterem Regen",
    },
    {
        "condition": ("sensor.wasserenthaertung", "on"),
        "affects": "notify",
        "effect": "Wasserenthaertung → Salz nachfuellen?",
        "hint": "Wasserenthaertung → Salzstand pruefen",
    },
    {
        "condition": ("sensor.water_softener", "on"),
        "affects": "notify",
        "effect": "Wasserenthaertung → Regeneriersalz pruefen",
        "hint": "Enthaerter → Salz bald nachfuellen",
    },
    {
        "condition": ("switch.osmose", "on"),
        "affects": "energy",
        "effect": "Osmoseanlage an → Strom- und Wasserverbrauch",
        "hint": "Osmoseanlage laeuft → Wasser- und Stromverbrauch",
    },

    # =====================================================================
    # 44. OUTDOOR-KUECHE / GRILL / TERRASSE
    # =====================================================================
    {
        "condition": ("switch.grill", "on"),
        "affects": "alarm_control_panel",
        "effect": "Grill an → Brandgefahr bei Wind",
        "hint": "Grill an → Vorsicht bei Wind, Brandgefahr",
    },
    {
        "condition": ("switch.grill", "on"),
        "affects": "notify",
        "effect": "Grill an → nicht unbeaufsichtigt lassen",
        "hint": "Grill laeuft → nicht vergessen",
    },
    {
        "condition": ("switch.outdoor_kueche", "on"),
        "affects": "energy",
        "effect": "Outdoor-Kueche an → Stromverbrauch",
        "hint": "Aussenkueche aktiv → Stromverbrauch",
    },
    {
        "condition": ("switch.terrassenheizung", "on"),
        "affects": "energy",
        "effect": "Terrassenheizung an → hoher Energieverbrauch",
        "hint": "Terrassenheizung → hoher Gas-/Stromverbrauch",
    },
    {
        "condition": ("switch.patio_heater", "on"),
        "affects": "energy",
        "effect": "Terrassenheizung an → hoher Energieverbrauch",
        "hint": "Terrassenheizer → Energieverschwendung bei Wind",
    },
    {
        "condition": ("light.terrasse", "on"),
        "affects": "notify",
        "effect": "Terrassenbeleuchtung an → Insekten anlocken",
        "hint": "Terrassenlicht an → zieht Insekten an im Sommer",
    },
    {
        "condition": ("light.aussen", "on"),
        "affects": "notify",
        "effect": "Aussenbeleuchtung an → Lichtverschmutzung, Nachbarn, Insekten",
        "hint": "Aussenlicht an → Lichtverschmutzung beachten",
    },
    {
        "condition": ("light.outdoor", "on"),
        "affects": "energy",
        "effect": "Aussenbeleuchtung an → Stromverbrauch die ganze Nacht",
        "hint": "Aussenlicht brennt → Strom die ganze Nacht?",
    },

    # =====================================================================
    # 45. BODENFEUCHTESENSOR / PFLANZENSENSOR
    # =====================================================================
    {
        "condition": ("sensor.bodenfeucht", "on"),
        "affects": "switch",
        "effect": "Boden trocken → Bewaesserung noetig",
        "hint": "Boden trocken → Pflanzen brauchen Wasser",
    },
    {
        "condition": ("sensor.soil_moisture", "on"),
        "affects": "switch",
        "effect": "Bodenfeuchtigkeit → Bewaesserung steuern",
        "hint": "Bodenfeuchte → Bewaesserung anpassen",
    },
    {
        "condition": ("sensor.plant", "on"),
        "affects": "notify",
        "effect": "Pflanzensensor → Pflanze braucht Aufmerksamkeit",
        "hint": "Pflanze → Wasser/Licht/Duenger noetig",
    },
    {
        "condition": ("sensor.pflanze", "on"),
        "affects": "notify",
        "effect": "Pflanzensensor → Pflanze braucht Pflege",
        "hint": "Pflanze meldet sich → giessen oder duengen",
    },

    # =====================================================================
    # 46. SMART SPEAKER / DISPLAY → LAUTSTAERKE / KONTEXT
    # =====================================================================
    {
        "condition": ("media_player.echo", "playing"),
        "affects": "notify",
        "effect": "Smart Speaker spielt → Sprachbefehle schwer erkennbar",
        "hint": "Musik laeuft auf Speaker → Spracherkennung eingeschraenkt",
    },
    {
        "condition": ("media_player.google", "playing"),
        "affects": "notify",
        "effect": "Smart Speaker spielt → Sprachbefehle schwer erkennbar",
        "hint": "Google Speaker spielt → Spracherkennung beeintraechtigt",
    },
    {
        "condition": ("media_player.sonos", "playing"),
        "affects": "notify",
        "effect": "Sonos spielt → Lautstaerke beachten nachts",
        "hint": "Sonos laeuft → Nachbarn bei offenen Fenstern?",
    },

    # =====================================================================
    # 47. AUFZUG / TREPPENHAUS
    # =====================================================================
    {
        "condition": ("sensor.aufzug", "on"),
        "affects": "energy",
        "effect": "Aufzug faehrt → kurzzeitig hoher Stromverbrauch",
        "hint": "Aufzug aktiv → kurzer Stromstoss",
    },
    {
        "condition": ("sensor.elevator", "on"),
        "affects": "energy",
        "effect": "Aufzug aktiv → Stromverbrauch",
        "hint": "Aufzug → Energieverbrauch",
    },
    {
        "condition": ("light.treppenhaus", "on"),
        "affects": "energy",
        "effect": "Treppenhauslicht an → oft vergessen auszuschalten",
        "hint": "Treppenlicht brennt → automatisch ausschalten?",
    },
    {
        "condition": ("light.staircase", "on"),
        "affects": "energy",
        "effect": "Treppenlicht an → laeuft oft unnoetig",
        "hint": "Treppenlicht → Timer oder Bewegungsmelder sinnvoll",
    },

    # =====================================================================
    # 48. LADESTATIONEN / AKKUS (HANDY/LAPTOP/WERKZEUG)
    # =====================================================================
    {
        "condition": ("sensor.phone_battery", "on"),
        "affects": "notify",
        "effect": "Handy-Akku niedrig → aufladen",
        "hint": "Handy Akku niedrig → ans Ladekabel",
    },
    {
        "condition": ("sensor.tablet_battery", "on"),
        "affects": "notify",
        "effect": "Tablet-Akku niedrig → aufladen",
        "hint": "Tablet Akku niedrig → laden",
    },
    {
        "condition": ("switch.ladestation", "on"),
        "affects": "energy",
        "effect": "Ladestation aktiv → Stromverbrauch",
        "hint": "Ladestation laedt → Stromverbrauch",
    },
    {
        "condition": ("switch.charger", "on"),
        "affects": "energy",
        "effect": "Ladegeraet aktiv → Stromverbrauch, bei Vollladung abschalten",
        "hint": "Ladegeraet → bei vollem Akku Stecker ziehen",
    },

    # =====================================================================
    # 49. SMART MIRROR / DISPLAY-HUB
    # =====================================================================
    {
        "condition": ("switch.smart_mirror", "on"),
        "affects": "energy",
        "effect": "Smart Mirror an → Dauerstromverbrauch",
        "hint": "Smart Mirror → laeuft den ganzen Tag, Strom sparen nachts",
    },
    {
        "condition": ("switch.display", "on"),
        "affects": "energy",
        "effect": "Info-Display an → Stromverbrauch",
        "hint": "Display laeuft → nachts ausschalten sinnvoll",
    },

    # =====================================================================
    # 50. WAESCHESTAENDER / TROCKNEN
    # =====================================================================
    {
        "condition": ("binary_sensor.waeschestaender", "on"),
        "affects": "climate",
        "effect": "Waesche trocknet drinnen → Luftfeuchtigkeit steigt",
        "hint": "Waesche drinnen → Feuchtigkeit steigt, lueften oder entfeuchten",
    },
    {
        "condition": ("binary_sensor.laundry_rack", "on"),
        "affects": "climate",
        "effect": "Waesche trocknet drinnen → Feuchtigkeit steigt",
        "hint": "Waesche im Raum → Luftfeuchtigkeit steigt, Schimmelgefahr",
    },
    {
        "condition": ("binary_sensor.waeschestaender", "on"),
        "affects": "fan",
        "effect": "Waesche drinnen → Luefter oder Entfeuchter einschalten",
        "hint": "Waesche trocknet → Entfeuchtung sinnvoll",
    },

    # =====================================================================
    # 51. GAESTEZIMMER / GAESTEMODUS
    # =====================================================================
    {
        "condition": ("input_boolean.gaeste", "on"),
        "affects": "climate",
        "effect": "Gaeste da → Gaestezimmer heizen/kuehlen",
        "hint": "Gaestemodus → Gaestezimmer auf Komforttemperatur",
    },
    {
        "condition": ("input_boolean.guest", "on"),
        "affects": "climate",
        "effect": "Gaeste da → zusaetzliche Raeume temperieren",
        "hint": "Gaestemodus → Gaestezimmer vorbereiten",
    },
    {
        "condition": ("input_boolean.gaeste", "on"),
        "affects": "light",
        "effect": "Gaeste da → Orientierungslicht nachts",
        "hint": "Gaestemodus → Nachtlicht fuer Gaeste sinnvoll",
    },
    {
        "condition": ("input_boolean.gaeste", "on"),
        "affects": "notify",
        "effect": "Gaeste da → WLAN-Zugangsdaten bereitstellen",
        "hint": "Gaestemodus → Gaeste-WLAN aktiviert?",
    },

    # =====================================================================
    # 52. URLAUBS- / ABWESENHEITSMODUS
    # =====================================================================
    {
        "condition": ("input_boolean.urlaub", "on"),
        "affects": "climate",
        "effect": "Urlaubsmodus → Heizung auf Minimum/Frostschutz",
        "hint": "Urlaub → Heizung runter, nur Frostschutz",
    },
    {
        "condition": ("input_boolean.vacation", "on"),
        "affects": "climate",
        "effect": "Urlaubsmodus → Heizung minimal",
        "hint": "Urlaub → Energiesparmodus aktivieren",
    },
    {
        "condition": ("input_boolean.urlaub", "on"),
        "affects": "light",
        "effect": "Urlaubsmodus → Anwesenheitssimulation",
        "hint": "Urlaub → Lichter simulieren Anwesenheit",
    },
    {
        "condition": ("input_boolean.urlaub", "on"),
        "affects": "cover",
        "effect": "Urlaubsmodus → Rolllaeden automatisch offen/zu",
        "hint": "Urlaub → Rolllaeden simulieren normalen Tagesablauf",
    },
    {
        "condition": ("input_boolean.urlaub", "on"),
        "affects": "switch",
        "effect": "Urlaubsmodus → alle unnoetige Geraete aus",
        "hint": "Urlaub → Standby-Geraete ausschalten, Strom sparen",
    },
    {
        "condition": ("input_boolean.urlaub", "on"),
        "affects": "alarm_control_panel",
        "effect": "Urlaubsmodus → Alarm durchgehend scharf",
        "hint": "Urlaub → Alarm muss permanent aktiv sein",
    },

    # =====================================================================
    # 53. SONNENEINSTRAHLUNG / BESCHATTUNG / BLENDUNG
    # =====================================================================
    {
        "condition": ("sensor.solar_radiation", "on"),
        "affects": "cover",
        "effect": "Starke Sonneneinstrahlung → Beschattung aktivieren",
        "hint": "Sonne stark → Rolllaeden/Jalousien teilweise schliessen",
    },
    {
        "condition": ("sensor.sonneneinstrahlung", "on"),
        "affects": "cover",
        "effect": "Sonneneinstrahlung hoch → automatische Beschattung",
        "hint": "Sonne blendet → Beschattung anpassen",
    },
    {
        "condition": ("sensor.illuminance", "on"),
        "affects": "light",
        "effect": "Helligkeit aussen hoch → Kunstlicht unnoetig",
        "hint": "Hell draussen → Kunstlicht ausschalten",
    },
    {
        "condition": ("sensor.helligkeit", "on"),
        "affects": "light",
        "effect": "Ausreichend Tageslicht → Lampen aus",
        "hint": "Genug Tageslicht → Lampen koennen aus",
    },
    {
        "condition": ("sensor.illuminance", "on"),
        "affects": "cover",
        "effect": "Daemmerung → Rolllaeden schliessen",
        "hint": "Wird dunkel → Rolllaeden runter fuer Sichtschutz",
    },

    # =====================================================================
    # 54. KINDERZIMMER / KINDERSICHERHEIT
    # =====================================================================
    {
        "condition": ("binary_sensor.kinder", "on"),
        "affects": "notify",
        "effect": "Kind ist wach / Bewegung im Kinderzimmer",
        "hint": "Kind wach → Babyfon/Kinderzimmer beobachten",
    },
    {
        "condition": ("binary_sensor.child", "on"),
        "affects": "notify",
        "effect": "Kind-Sensor → Kind ist aktiv",
        "hint": "Kind wach → Eltern informieren",
    },
    {
        "condition": ("binary_sensor.kinder", "on"),
        "affects": "media_player",
        "effect": "Kind schlaeft → Lautstaerke im Haus reduzieren",
        "hint": "Kind schlaeft → leise sein",
    },
    {
        "condition": ("switch.kindersicherung", "off"),
        "affects": "alarm_control_panel",
        "effect": "Kindersicherung deaktiviert → Gefahr fuer Kinder",
        "hint": "Kindersicherung aus → sofort aktivieren",
    },
    {
        "condition": ("switch.child_lock", "off"),
        "affects": "alarm_control_panel",
        "effect": "Kindersicherung aus → Kinder in Gefahr",
        "hint": "Kindersicherung deaktiviert → pruefen",
    },

    # =====================================================================
    # 55. HOMEOFFICE / ARBEITSZIMMER
    # =====================================================================
    {
        "condition": ("input_boolean.homeoffice", "on"),
        "affects": "climate",
        "effect": "Homeoffice aktiv → Buero auf Komforttemperatur",
        "hint": "Homeoffice → Buero-Temperatur angenehm halten",
    },
    {
        "condition": ("input_boolean.homeoffice", "on"),
        "affects": "light",
        "effect": "Homeoffice → Arbeitslicht mit guter Farbtemperatur",
        "hint": "Homeoffice → Tageslicht-Farbtemperatur fuer Konzentration",
    },
    {
        "condition": ("input_boolean.homeoffice", "on"),
        "affects": "notify",
        "effect": "Homeoffice → Meeting-Modus, Klingel leiser?",
        "hint": "Homeoffice → Stoerungen minimieren, Klingel stumm?",
    },
    {
        "condition": ("binary_sensor.webcam", "on"),
        "affects": "light",
        "effect": "Webcam aktiv → gute Beleuchtung fuer Videokonferenz",
        "hint": "Videocall → Licht im Gesicht fuer gutes Bild",
    },
    {
        "condition": ("binary_sensor.webcam", "on"),
        "affects": "notify",
        "effect": "Videokonferenz → Hintergrundgeraeusche vermeiden",
        "hint": "Videocall → leise sein, Staubsauger/Musik aus",
    },
    {
        "condition": ("input_boolean.meeting", "on"),
        "affects": "media_player",
        "effect": "Meeting aktiv → alle Medien stumm",
        "hint": "Meeting → Musik/TV aus",
    },
    {
        "condition": ("input_boolean.meeting", "on"),
        "affects": "vacuum",
        "effect": "Meeting aktiv → Saugroboter nicht starten",
        "hint": "Meeting → Staubsauger aus, zu laut",
    },

    # =====================================================================
    # 56. RAUMDUFT / AROMA / LUFTERFRISCHER
    # =====================================================================
    {
        "condition": ("switch.diffuser", "on"),
        "affects": "energy",
        "effect": "Aroma-Diffuser an → Stromverbrauch",
        "hint": "Diffuser laeuft → Stromverbrauch",
    },
    {
        "condition": ("switch.duft", "on"),
        "affects": "notify",
        "effect": "Raumduft aktiv → bei Gaesten/Allergikern beachten",
        "hint": "Duft aktiv → Allergiker beachten",
    },

    # =====================================================================
    # 57. ELEKTROZAUN / GARTENTOR / SCHRANKE
    # =====================================================================
    {
        "condition": ("cover.gartentor", "open"),
        "affects": "alarm_control_panel",
        "effect": "Gartentor offen → ungesicherter Zugang",
        "hint": "Gartentor offen → Grundstueck nicht gesichert",
    },
    {
        "condition": ("cover.gate", "open"),
        "affects": "alarm_control_panel",
        "effect": "Tor offen → ungesicherter Zugang",
        "hint": "Tor offen → Sicherheit pruefen",
    },
    {
        "condition": ("cover.schranke", "open"),
        "affects": "notify",
        "effect": "Schranke offen → Zufahrt frei",
        "hint": "Schranke offen → wer kommt?",
    },
    {
        "condition": ("switch.elektrozaun", "off"),
        "affects": "alarm_control_panel",
        "effect": "Elektrozaun aus → Grundstueck nicht gesichert",
        "hint": "Elektrozaun deaktiviert → Sicherheit reduziert",
    },

    # =====================================================================
    # 58. WASSERVERBRAUCH / DURCHFLUSS
    # =====================================================================
    {
        "condition": ("sensor.water_consumption", "on"),
        "affects": "notify",
        "effect": "Ungewoehnlich hoher Wasserverbrauch → Leck moeglich",
        "hint": "Wasserverbrauch hoch → Leck oder Hahn offen vergessen?",
    },
    {
        "condition": ("sensor.wasserverbrauch", "on"),
        "affects": "notify",
        "effect": "Hoher Wasserverbrauch → Ursache pruefen",
        "hint": "Viel Wasser verbraucht → Leck oder vergessener Hahn?",
    },
    {
        "condition": ("sensor.durchfluss", "on"),
        "affects": "alarm_control_panel",
        "effect": "Durchfluss bei Abwesenheit → moeglicherweise Leck",
        "hint": "Wasser fliesst aber niemand da → Leck?",
    },

    # =====================================================================
    # 59. HEIZOEL / PELLET / GAS-TANK
    # =====================================================================
    {
        "condition": ("sensor.heizoel", "on"),
        "affects": "notify",
        "effect": "Heizoel-Fuellstand niedrig → nachbestellen",
        "hint": "Heizoel wird knapp → rechtzeitig bestellen",
    },
    {
        "condition": ("sensor.oil_level", "on"),
        "affects": "notify",
        "effect": "Oel-Fuellstand → rechtzeitig nachbestellen",
        "hint": "Heizoel → Bestellzeitpunkt beachten",
    },
    {
        "condition": ("sensor.pellet", "on"),
        "affects": "notify",
        "effect": "Pellet-Vorrat → rechtzeitig nachfuellen",
        "hint": "Pellets werden knapp → nachbestellen",
    },
    {
        "condition": ("sensor.gastank", "on"),
        "affects": "notify",
        "effect": "Gas-Tank Fuellstand niedrig → nachfuellen lassen",
        "hint": "Gastank wird leer → Gaslieferung bestellen",
    },
    {
        "condition": ("sensor.gas_tank", "on"),
        "affects": "notify",
        "effect": "Gas-Tank Fuellstand → rechtzeitig auffuellen",
        "hint": "Gastank niedrig → Lieferung organisieren",
    },

    # =====================================================================
    # 60. PHOTOVOLTAIK DETAILS / WECHSELRICHTER
    # =====================================================================
    {
        "condition": ("sensor.inverter", "on"),
        "affects": "energy",
        "effect": "Wechselrichter-Status beeinflusst PV-Produktion",
        "hint": "Wechselrichter → PV-Anlage Status pruefen",
    },
    {
        "condition": ("sensor.wechselrichter", "on"),
        "affects": "energy",
        "effect": "Wechselrichter → PV-Produktion und Eigenverbrauch",
        "hint": "PV-Wechselrichter → Produktionsleistung beachten",
    },
    {
        "condition": ("binary_sensor.inverter", "off"),
        "affects": "notify",
        "effect": "Wechselrichter offline → PV-Anlage produziert nicht",
        "hint": "Wechselrichter ausgefallen → PV-Anlage steht still",
    },
    {
        "condition": ("sensor.grid_power", "on"),
        "affects": "energy",
        "effect": "Netzbezug → Strom wird teuer eingekauft",
        "hint": "Netzbezug hoch → Eigenverbrauch optimieren",
    },

    # =====================================================================
    # 61. GESUNDHEIT / WELLNESS / FITNESS
    # =====================================================================
    {
        "condition": ("sensor.blutdruck", "on"),
        "affects": "notify",
        "effect": "Blutdruck gemessen → Wert beachten",
        "hint": "Blutdruckmessung → Werte im Blick behalten",
    },
    {
        "condition": ("sensor.blood_pressure", "on"),
        "affects": "notify",
        "effect": "Blutdruck → Gesundheitsdaten tracken",
        "hint": "Blutdruckwert → aufmerksam bleiben",
    },
    {
        "condition": ("sensor.waage", "on"),
        "affects": "notify",
        "effect": "Koerperwaage → Gewicht getrackt",
        "hint": "Gewicht gemessen → Trend beobachten",
    },
    {
        "condition": ("sensor.scale", "on"),
        "affects": "notify",
        "effect": "Koerperwaage → Gewichtsdaten",
        "hint": "Gewicht → Gesundheitstracking",
    },
    {
        "condition": ("switch.laufband", "on"),
        "affects": "energy",
        "effect": "Laufband an → Stromverbrauch",
        "hint": "Laufband laeuft → Stromverbrauch beachten",
    },
    {
        "condition": ("switch.treadmill", "on"),
        "affects": "energy",
        "effect": "Laufband/Fitnessgeraet → Stromverbrauch",
        "hint": "Fitnessgeraet an → Strom",
    },

    # =====================================================================
    # 62. KUEHLKETTE / MEDIKAMENTE
    # =====================================================================
    {
        "condition": ("sensor.medikamenten_kuehl", "on"),
        "affects": "notify",
        "effect": "Medikamenten-Kuehlschrank Temperatur → kritisch fuer Medikamente",
        "hint": "Medikamenten-Kuehlung → Temperatur muss stimmen",
    },
    {
        "condition": ("sensor.medicine_fridge", "on"),
        "affects": "notify",
        "effect": "Medikamenten-Kuehlschrank → Temperatur ueberwachen",
        "hint": "Medikamente → Kuehlung sicherstellen",
    },

    # =====================================================================
    # 63. GEWAECHSHAUS → TEMPERATUR / BEWAESSERUNG / LUEFTUNG
    # =====================================================================
    {
        "condition": ("sensor.gewaechshaus_temp", "on"),
        "affects": "climate",
        "effect": "Gewaechshaus-Temperatur → Belueftung oder Heizung",
        "hint": "Gewaechshaus → Temperatur regulieren fuer Pflanzen",
    },
    {
        "condition": ("sensor.greenhouse_temp", "on"),
        "affects": "climate",
        "effect": "Gewaechshaus → Temperatur fuer Pflanzen optimieren",
        "hint": "Gewaechshaus → Heizung/Lueftung anpassen",
    },
    {
        "condition": ("switch.gewaechshaus_heizung", "on"),
        "affects": "energy",
        "effect": "Gewaechshaus-Heizung → Energieverbrauch",
        "hint": "Gewaechshaus wird geheizt → Energieverbrauch",
    },
    {
        "condition": ("switch.gewaechshaus_lueftung", "on"),
        "affects": "climate",
        "effect": "Gewaechshaus-Lueftung → Temperatur und Feuchtigkeit regulieren",
        "hint": "Gewaechshaus Luefter → Klima regulieren",
    },
    {
        "condition": ("binary_sensor.gewaechshaus_fenster", "on"),
        "affects": "climate",
        "effect": "Gewaechshaus Fenster offen → Temperatur sinkt",
        "hint": "Gewaechshaus offen → Frost kann Pflanzen schaeden",
    },

    # =====================================================================
    # 64. TIEFGARAGE / PARKHAUS / STELLPLATZ
    # =====================================================================
    {
        "condition": ("binary_sensor.tiefgarage", "on"),
        "affects": "fan",
        "effect": "Bewegung in Tiefgarage → CO-Abzug sicherstellen",
        "hint": "Auto in Tiefgarage → Abgasabzug pruefen",
    },
    {
        "condition": ("sensor.tiefgarage_co", "on"),
        "affects": "fan",
        "effect": "CO in Tiefgarage → Lueftung auf Maximum",
        "hint": "Abgase in Tiefgarage → Lueftung verstaerken",
    },
    {
        "condition": ("binary_sensor.stellplatz", "on"),
        "affects": "notify",
        "effect": "Stellplatz belegt/frei → Parkinfo",
        "hint": "Stellplatz → Parkinformation",
    },

    # =====================================================================
    # 65. SCHIMMELWARNUNG / TAUPUNKT
    # =====================================================================
    {
        "condition": ("sensor.taupunkt", "on"),
        "affects": "climate",
        "effect": "Taupunkt erreicht → Kondenswasser, Schimmelgefahr",
        "hint": "Taupunkt → Schimmelgefahr, sofort lueften oder heizen",
    },
    {
        "condition": ("sensor.dew_point", "on"),
        "affects": "climate",
        "effect": "Taupunkt-Warnung → Kondensation an Waenden moeglich",
        "hint": "Taupunkt → Lueften und Heizen gegen Schimmel",
    },
    {
        "condition": ("binary_sensor.mold", "on"),
        "affects": "climate",
        "effect": "Schimmelrisiko hoch → Raumklima verbessern",
        "hint": "Schimmelrisiko → Temperatur hoch, Feuchtigkeit runter",
    },
    {
        "condition": ("binary_sensor.schimmel", "on"),
        "affects": "climate",
        "effect": "Schimmelwarnung → sofort handeln",
        "hint": "Schimmelgefahr → lueften, heizen, entfeuchten",
    },

    # =====================================================================
    # 66. WASSERDRUCK / HEIZUNGSDRUCK
    # =====================================================================
    {
        "condition": ("sensor.heizungsdruck", "on"),
        "affects": "notify",
        "effect": "Heizungsdruck zu niedrig → Wasser nachfuellen",
        "hint": "Heizungsdruck niedrig → Heizung nachfuellen",
    },
    {
        "condition": ("sensor.heating_pressure", "on"),
        "affects": "notify",
        "effect": "Heizungsdruck → System pruefen",
        "hint": "Heizungsdruck → Wasser nachfuellen noetig?",
    },
    {
        "condition": ("sensor.wasserdruck", "on"),
        "affects": "notify",
        "effect": "Wasserdruck anomal → Rohrproblem moeglich",
        "hint": "Wasserdruck ungewoehnlich → Leck oder Rohrproblem?",
    },

    # =====================================================================
    # 67. WARMWASSER / BOILER / DURCHLAUFERHITZER
    # =====================================================================
    {
        "condition": ("switch.boiler", "on"),
        "affects": "energy",
        "effect": "Boiler heizt → hoher Energieverbrauch",
        "hint": "Warmwasser-Boiler heizt → Stromverbrauch",
    },
    {
        "condition": ("switch.durchlauferhitzer", "on"),
        "affects": "energy",
        "effect": "Durchlauferhitzer an → sehr hoher Momentanverbrauch",
        "hint": "Durchlauferhitzer → kurzfristig hoher Stromverbrauch",
    },
    {
        "condition": ("sensor.warmwasser_temp", "on"),
        "affects": "notify",
        "effect": "Warmwasser-Temperatur → Legionellen-Schutz beachten",
        "hint": "Warmwasser → bei <60°C Legionellen-Risiko",
    },
    {
        "condition": ("sensor.hot_water_temp", "on"),
        "affects": "notify",
        "effect": "Warmwasser-Temperatur → Hygiene sicherstellen",
        "hint": "Warmwasser-Temp → Legionellen-Schutz ab 60°C",
    },

    # =====================================================================
    # 68. FUSSBODENHEIZUNG → TRAEGHEIT / ENERGIE
    # =====================================================================
    {
        "condition": ("climate.fussbodenheizung", "heat"),
        "affects": "energy",
        "effect": "Fussbodenheizung aktiv → traege Regelung, vorausplanen",
        "hint": "Fussbodenheizung → reagiert langsam, frueh einschalten",
    },
    {
        "condition": ("climate.floor_heating", "heat"),
        "affects": "energy",
        "effect": "Fussbodenheizung heizt → langsame Reaktion beachten",
        "hint": "Fussbodenheizung → braucht Stunden zum Aufheizen",
    },
    {
        "condition": ("climate.fussbodenheizung", "heat"),
        "affects": "binary_sensor",
        "effect": "Fussbodenheizung + Fenster lange offen → viel Energieverlust",
        "hint": "Fussbodenheizung → Fenster kurz lueften, nicht kippen",
    },

    # =====================================================================
    # 69. SMARTE VENTILE / HEIZKOERPER-THERMOSTATE
    # =====================================================================
    {
        "condition": ("climate.thermostat", "heat"),
        "affects": "binary_sensor",
        "effect": "Thermostat heizt → Fenster offen ist Energieverschwendung",
        "hint": "Thermostat heizt + Fenster offen → Energie wird verschwendet",
    },
    {
        "condition": ("climate.heizkoerper", "heat"),
        "affects": "energy",
        "effect": "Heizkoerper-Thermostat aktiv → Energieverbrauch",
        "hint": "Heizkoerper heizt → Energieverbrauch beachten",
    },
    {
        "condition": ("climate.thermostat", "off"),
        "affects": "notify",
        "effect": "Thermostat aus bei Kaelte → Frostgefahr",
        "hint": "Thermostat aus + kalt → Frostschutz beachten",
    },

    # =====================================================================
    # 70. NOTRUF / PANIKKNOPF / MEDIZINISCHER ALARM
    # =====================================================================
    {
        "condition": ("binary_sensor.panik", "on"),
        "affects": "alarm_control_panel",
        "effect": "Panikknopf gedrueckt → sofortige Hilfe noetig",
        "hint": "PANIKKNOPF → sofort reagieren, Hilfe rufen",
    },
    {
        "condition": ("binary_sensor.panic", "on"),
        "affects": "alarm_control_panel",
        "effect": "Panic button pressed → immediate help needed",
        "hint": "PANIK → sofortige Reaktion noetig",
    },
    {
        "condition": ("binary_sensor.notfall", "on"),
        "affects": "notify",
        "effect": "Notfall-Sensor → medizinischer Notfall moeglich",
        "hint": "NOTFALL → sofort pruefen und helfen",
    },
    {
        "condition": ("binary_sensor.emergency", "on"),
        "affects": "notify",
        "effect": "Emergency sensor triggered → immediate attention",
        "hint": "NOTFALL → sofortige Aufmerksamkeit",
    },
    {
        "condition": ("binary_sensor.sturz", "on"),
        "affects": "notify",
        "effect": "Sturzerkennung → Person gestuerzt, Hilfe noetig",
        "hint": "Sturz erkannt → sofort nach Person sehen",
    },
    {
        "condition": ("binary_sensor.fall", "on"),
        "affects": "notify",
        "effect": "Fall detection → person needs help",
        "hint": "Sturz → sofortige Hilfe, Person pruefen",
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

    def detect_conflicts(self, states: dict) -> list[dict]:
        """Prueft aktuelle HA-States gegen DEVICE_DEPENDENCIES.

        Args:
            states: Dict entity_id → state-string (z.B. "on", "heat", "open")

        Returns:
            Liste aktiver Konflikte mit Hinweisen fuers LLM.
        """
        conflicts = []
        for dep in DEVICE_DEPENDENCIES:
            cond_entity, cond_state = dep["condition"]

            # Prefix-Match: "binary_sensor.fenster" matcht "binary_sensor.fenster_kueche"
            matching = [
                eid for eid, st in states.items()
                if eid.startswith(cond_entity) and st == cond_state
            ]
            if not matching:
                continue

            # Pruefen ob betroffene Domain aktiv ist
            affected_domain = dep["affects"]
            affected_active = any(
                eid.startswith(f"{affected_domain}.")
                and val not in ("off", "unavailable", "unknown", "idle")
                for eid, val in states.items()
            )

            for eid in matching:
                conflicts.append({
                    "trigger_entity": eid,
                    "trigger_state": cond_state,
                    "affected_domain": affected_domain,
                    "affected_active": affected_active,
                    "effect": dep["effect"],
                    "hint": dep["hint"],
                })
        return conflicts

    def format_conflicts_for_prompt(self, states: dict) -> str:
        """Formatiert aktive Geraete-Konflikte als LLM-Kontext.

        Args:
            states: Dict entity_id → state-string

        Returns:
            Prompt-Sektion oder leerer String.
        """
        conflicts = self.detect_conflicts(states)
        if not conflicts:
            return ""

        # Nur Konflikte wo betroffene Domain aktiv ist (echte Konflikte)
        active_conflicts = [c for c in conflicts if c["affected_active"]]
        if not active_conflicts:
            return ""

        lines = []
        seen = set()
        for c in active_conflicts:
            key = (c["trigger_entity"], c["affected_domain"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {c['hint']} ({c['effect']})")

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
