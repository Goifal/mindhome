# MindHome Assistant — Vollständige Test-Checkliste

> Dieses Dokument listet **alle** prüfbaren Features des MindHome **Assistants** (Jarvis) auf.
> Für jedes Feature ist beschrieben: **was** man testen kann, **wie** man es testet (Chat-Befehl, API-Call oder UI-Prüfung) und **was** das erwartete Ergebnis ist.
>
> Stand: 2026-02-27 | Assistant v1.4.2

---

## Inhaltsverzeichnis

1. [Licht-Steuerung](#1-licht-steuerung)
2. [Heizung / Klima](#2-heizung--klima)
3. [Rollläden / Markisen](#3-rollläden--markisen)
4. [Steckdosen / Schalter](#4-steckdosen--schalter)
5. [Szenen](#5-szenen)
6. [Musik & Medien](#6-musik--medien)
7. [Smart DJ](#7-smart-dj)
8. [Sicherheit (Alarm & Schlösser)](#8-sicherheit-alarm--schlösser)
9. [Anwesenheit](#9-anwesenheit)
10. [Kalender](#10-kalender)
11. [Timer & Erinnerungen](#11-timer--erinnerungen)
12. [Wecker](#12-wecker)
13. [Durchsagen & Intercom](#13-durchsagen--intercom)
14. [Kamera & Türklingel](#14-kamera--türklingel)
15. [Besucher-Management](#15-besucher-management)
16. [Einkaufsliste](#16-einkaufsliste)
17. [Vorrats-Tracking (Inventar)](#17-vorrats-tracking-inventar)
18. [Koch-Assistent](#18-koch-assistent)
19. [Saugroboter](#19-saugroboter)
20. [Wetter](#20-wetter)
21. [Energie](#21-energie)
22. [Web-Suche](#22-web-suche)
23. [Haus-Status & Briefing](#23-haus-status--briefing)
24. [Gedächtnis & Fakten](#24-gedächtnis--fakten)
25. [Persönlichkeit & Sarkasmus](#25-persönlichkeit--sarkasmus)
26. [Stimmungserkennung (Mood)](#26-stimmungserkennung-mood)
27. [Aktivitätserkennung](#27-aktivitätserkennung)
28. [Szenen-Intelligenz (natürliche Sprache)](#28-szenen-intelligenz-natürliche-sprache)
29. [Bedingte Befehle (Wenn-Dann)](#29-bedingte-befehle-wenn-dann)
30. [Automationen erstellen](#30-automationen-erstellen)
31. [Protokolle (Multi-Step-Sequenzen)](#31-protokolle-multi-step-sequenzen)
32. [Routinen](#32-routinen)
33. [Easter Eggs](#33-easter-eggs)
34. [Proaktive Meldungen](#34-proaktive-meldungen)
35. [Wellness & Gesundheit](#35-wellness--gesundheit)
36. [Raumklima-Monitor](#36-raumklima-monitor)
37. [Geräte-Gesundheit](#37-geräte-gesundheit)
38. [Diagnostik & Wartung](#38-diagnostik--wartung)
39. [Sicherheits-Score](#39-sicherheits-score)
40. [Bedrohungsbewertung](#40-bedrohungsbewertung)
41. [Intent-Tracking (Vorhaben merken)](#41-intent-tracking-vorhaben-merken)
42. [Lernmuster-Erkennung](#42-lernmuster-erkennung)
43. [Spontane Beobachtungen](#43-spontane-beobachtungen)
44. [Anticipation (Vorausdenken)](#44-anticipation-vorausdenken)
45. [Tages-Zusammenfassungen](#45-tages-zusammenfassungen)
46. [Speaker Recognition](#46-speaker-recognition)
47. [TTS & Sound-System](#47-tts--sound-system)
48. [Ambient Audio (Umgebungsgeräusche)](#48-ambient-audio-umgebungsgeräusche)
49. [Konflikterkennung (Multi-User)](#49-konflikterkennung-multi-user)
50. [Datei-Upload & OCR](#50-datei-upload--ocr)
51. [Knowledge Base (RAG)](#51-knowledge-base-rag)
52. [Autonomie-Level](#52-autonomie-level)
53. [Trust-Level (Vertrauensstufen)](#53-trust-level-vertrauensstufen)
54. [Self-Optimization](#54-self-optimization)
55. [Config-Selbstmodifikation](#55-config-selbstmodifikation)
56. [Entity-Status abfragen](#56-entity-status-abfragen)
57. [Fähigkeiten-Liste](#57-fähigkeiten-liste)
58. [Dashboard & Authentifizierung](#58-dashboard--authentifizierung)
59. [API-Endpoints (technisch)](#59-api-endpoints-technisch)
60. [WebSocket-Events](#60-websocket-events)
61. [Boot-Sequenz](#61-boot-sequenz)
62. [Fehlerbehandlung & Edge Cases](#62-fehlerbehandlung--edge-cases)

---

## 1. Licht-Steuerung

### Chat-Befehle zum Testen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 1.1 | "Mach das Licht im Wohnzimmer an" | Wohnzimmer-Licht geht an, adaptive Helligkeit nach Tageszeit |
| 1.2 | "Licht aus in der Küche" | Küchen-Licht geht aus |
| 1.3 | "Mach es heller" | Licht im aktuellen/letzten Raum +15% heller |
| 1.4 | "Mach es dunkler" | Licht im aktuellen/letzten Raum -15% dunkler |
| 1.5 | "Licht im Büro auf 50%" | Büro-Licht auf 50% Helligkeit |
| 1.6 | "Stehlampe im Wohnzimmer an" | Nur die Stehlampe (device-Parameter), nicht Hauptlicht |
| 1.7 | "Alle Lichter aus" | room='all' → alle Lichter im Haus aus |
| 1.8 | "Licht im EG aus" | Alle Lichter im Erdgeschoss aus |
| 1.9 | "Licht im OG aus" | Alle Lichter im Obergeschoss aus |
| 1.10 | "Deckenlampe im Schlafzimmer auf 30% mit 5 Sekunden Übergang" | Sanftes Dimmen mit transition=5 |
| 1.11 | "Welche Lichter sind an?" | get_lights → Liste aller Lichter mit Status |
| 1.12 | "Lichter im Wohnzimmer?" | get_lights mit room-Filter → nur Wohnzimmer |

### Technisch zu prüfen
- `set_light` Tool wird korrekt aufgerufen
- Dim2warm: Keine Farbtemperatur-Parameter nötig (Hardware-gesteuert)
- Raumnamen mit Personen-Präfix korrekt (z.B. "Manuel Büro" vs "Julia Büro")
- Englische Raumnamen werden übersetzt ("living room" → "wohnzimmer")

---

## 2. Heizung / Klima

### Modus: Raumthermostat

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 2.1 | "Stell die Heizung im Wohnzimmer auf 22 Grad" | set_climate → Wohnzimmer auf 22°C |
| 2.2 | "Mach es wärmer" | adjust='warmer' → +1°C im aktuellen Raum |
| 2.3 | "Mach es kälter" | adjust='cooler' → -1°C im aktuellen Raum |
| 2.4 | "Heizung aus im Schlafzimmer" | mode='off' für Schlafzimmer |
| 2.5 | "Wie warm ist es im Büro?" | get_climate → zeigt Ist- und Soll-Temperatur |
| 2.6 | "Zeig mir alle Thermostate" | get_climate ohne Filter → alle Räume |

### Modus: Heizkurve

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 2.7 | "Mach es wärmer" | Offset +1 zur Heizkurve |
| 2.8 | "Mach es kälter" | Offset -1 zur Heizkurve |

### Technisch zu prüfen
- Heizungsmodus aus `settings.yaml → heating.mode` korrekt erkannt
- Klima-Limits eingehalten (min 15°C, max 28°C)
- Raum-Präfixe korrekt

---

## 3. Rollläden / Markisen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 3.1 | "Rolladen im Wohnzimmer hoch" | set_cover action='open' |
| 3.2 | "Rollladen runter im Schlafzimmer" | set_cover action='close' |
| 3.3 | "Rolladen auf 50%" | set_cover position=50 |
| 3.4 | "Mach die Rollladen etwas weiter auf" | adjust='up' → +20% |
| 3.5 | "Alle Rollladen hoch" | room='all' |
| 3.6 | "Rolladen im EG runter" | room='eg' |
| 3.7 | "Rollladen auf halb" | action='half' |
| 3.8 | "Rollladen stop" | action='stop' |
| 3.9 | "Markisen raus" | type='markise', action='open' |
| 3.10 | "Alle Markisen rein" | room='markisen', action='close' |
| 3.11 | "Zeig mir alle Rollladen" | get_covers → Liste mit Positionen |

### Technisch zu prüfen
- Markisen haben eigene Sicherheits-Checks (Windschutz)
- Garagentore werden NICHT über set_cover gesteuert
- Raum-Zuordnung korrekt (Fenster-Kontakte vs. Steckdosen)

---

## 4. Steckdosen / Schalter

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 4.1 | "Steckdose in der Küche an" | set_switch room='kueche' state='on' |
| 4.2 | "Schalter im Büro aus" | set_switch room='buero' state='off' |
| 4.3 | "Welche Steckdosen sind an?" | get_switches → Liste mit Status |
| 4.4 | "Steckdosen im Wohnzimmer?" | get_switches mit room-Filter |

---

## 5. Szenen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 5.1 | "Filmabend" | activate_scene scene='filmabend' |
| 5.2 | "Gute Nacht Szene" | activate_scene scene='gute_nacht' |
| 5.3 | "Szene gemütlich" | activate_scene scene='gemuetlich' |

---

## 6. Musik & Medien

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 6.1 | "Spiel Jazz im Wohnzimmer" | play_media action='play' query='Jazz' room='wohnzimmer' |
| 6.2 | "Musik aus" | play_media action='stop' |
| 6.3 | "Pause" | play_media action='pause' |
| 6.4 | "Nächster Song" | play_media action='next' |
| 6.5 | "Leiser" | play_media action='volume_down' (-10%) |
| 6.6 | "Lauter" | play_media action='volume_up' (+10%) |
| 6.7 | "Lautstärke auf 30%" | play_media action='volume' volume=30 |
| 6.8 | "Was läuft gerade?" | get_media → aktueller Track, Lautstärke |
| 6.9 | "Musik vom Wohnzimmer ins Schlafzimmer" | transfer_playback |
| 6.10 | "Spiel eine Chill Playlist" | play_media media_type='playlist' query='Chill' |

---

## 7. Smart DJ

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 7.1 | "Empfiehl mir Musik" | recommend_music action='recommend' → Vorschlag basierend auf Stimmung/Aktivität/Tageszeit |
| 7.2 | "Spiel DJ Musik" | recommend_music action='play' → direkte Wiedergabe |
| 7.3 | "Die Musik gefällt mir" | recommend_music action='feedback' positive=true |
| 7.4 | "Die Musik gefällt mir nicht" | recommend_music action='feedback' positive=false |
| 7.5 | "DJ Status" | recommend_music action='status' → aktueller Kontext |
| 7.6 | "Spiel Party Musik" | recommend_music genre='party_hits' |

---

## 8. Sicherheit (Alarm & Schlösser)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 8.1 | "Alarm scharf schalten" | arm_security_system mode='arm_home' |
| 8.2 | "Alarm aus" | arm_security_system mode='disarm' (benötigt Bestätigung!) |
| 8.3 | "Alarm auf abwesend" | arm_security_system mode='arm_away' |
| 8.4 | "Haustür abschließen" | lock_door door='haustuer' action='lock' |
| 8.5 | "Haustür aufschließen" | lock_door door='haustuer' action='unlock' (benötigt Bestätigung!) |

### Technisch zu prüfen
- Sicherheitsaktionen erfordern Bestätigung (Redis-basiert)
- Trust-Level wird geprüft (Gäste dürfen nicht entsperren)
- Audit-Log wird geschrieben

---

## 9. Anwesenheit

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 9.1 | "Ich gehe jetzt" | set_presence_mode mode='away' |
| 9.2 | "Ich bin zuhause" | set_presence_mode mode='home' |
| 9.3 | "Gute Nacht" (Kontext: Schlafmodus) | set_presence_mode mode='sleep' |
| 9.4 | "Wir fahren in den Urlaub" | set_presence_mode mode='vacation' |

---

## 10. Kalender

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 10.1 | "Was steht heute an?" | get_calendar_events timeframe='today' |
| 10.2 | "Was steht morgen an?" | get_calendar_events timeframe='tomorrow' |
| 10.3 | "Was steht diese Woche an?" | get_calendar_events timeframe='week' |
| 10.4 | "Erstelle einen Termin: Zahnarzt am 15.3. um 10 Uhr" | create_calendar_event |
| 10.5 | "Lösche den Zahnarzt-Termin am 15.3." | delete_calendar_event |
| 10.6 | "Verschiebe den Zahnarzt auf den 20.3." | reschedule_calendar_event |
| 10.7 | "Habe ich morgen Termine?" | get_calendar_events timeframe='tomorrow' |

---

## 11. Timer & Erinnerungen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 11.1 | "Stell einen Timer auf 10 Minuten" | set_timer duration_minutes=10 |
| 11.2 | "Erinnere mich in 30 Minuten an die Wäsche" | set_timer label='Wäsche' |
| 11.3 | "In 20 Minuten Licht aus in der Küche" | set_timer mit action_on_expire |
| 11.4 | "Timer abbrechen" | cancel_timer |
| 11.5 | "Wie lange läuft der Timer noch?" | get_timer_status |
| 11.6 | "Welche Timer laufen?" | get_timer_status |
| 11.7 | "Erinnere mich um 15 Uhr an den Anruf" | set_reminder time='15:00' label='Anruf' |
| 11.8 | "Erinnere mich morgen um 8 an den Müll" | set_reminder time='08:00' date=morgen |

---

## 12. Wecker

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 12.1 | "Weck mich um 6:30" | set_wakeup_alarm time='06:30' |
| 12.2 | "Stell einen Wecker für 7 Uhr" | set_wakeup_alarm time='07:00' |
| 12.3 | "Wecker jeden Werktag um 6:30" | set_wakeup_alarm repeat='weekdays' |
| 12.4 | "Wecker löschen" | cancel_alarm |
| 12.5 | "Welche Wecker habe ich?" | get_alarms |
| 12.6 | "Wecker aus" | cancel_alarm |

---

## 13. Durchsagen & Intercom

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 13.1 | "Durchsage: Essen ist fertig!" | broadcast message='Essen ist fertig!' → alle Lautsprecher |
| 13.2 | "Sag Julia dass das Essen fertig ist" | send_intercom target_person='Julia' |
| 13.3 | "Durchsage im Wohnzimmer: Komm mal bitte" | send_intercom target_room='Wohnzimmer' |
| 13.4 | "Sag Manuel im Büro Bescheid" | send_intercom target_person='Manuel' |

---

## 14. Kamera & Türklingel

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 14.1 | "Wer ist an der Tür?" | describe_doorbell → Kamera-Bild wird analysiert (Vision LLM) |
| 14.2 | "Wer hat geklingelt?" | describe_doorbell |
| 14.3 | "Zeig mir die Garage" | get_camera_view camera_name='garage' |
| 14.4 | "Was ist vor der Haustür?" | describe_doorbell |
| 14.5 | "Kamera Garten" | get_camera_view camera_name='garten' |

---

## 15. Besucher-Management

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 15.1 | "Mama kommt heute um 15 Uhr" | manage_visitor action='expect' expected_time='15:00' |
| 15.2 | "Lass ihn rein" | manage_visitor action='grant_entry' → Tür öffnen |
| 15.3 | "Wer hat uns besucht?" | manage_visitor action='history' |
| 15.4 | "Besucher hinzufügen: Oma, Familie" | manage_visitor action='add_known' |
| 15.5 | "Zeig bekannte Besucher" | manage_visitor action='list_known' |
| 15.6 | "Besuch nicht mehr erwarten" | manage_visitor action='cancel_expected' |
| 15.7 | "Besucher Status" | manage_visitor action='status' |
| 15.8 | "Öffne die Tür für den Besuch" | manage_visitor action='grant_entry' auto_unlock=true |

---

## 16. Einkaufsliste

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 16.1 | "Setz Milch auf die Einkaufsliste" | manage_shopping_list action='add' item='Milch' |
| 16.2 | "Was steht auf der Einkaufsliste?" | manage_shopping_list action='list' |
| 16.3 | "Milch abhaken" | manage_shopping_list action='complete' item='Milch' |
| 16.4 | "Einkaufsliste aufräumen" | manage_shopping_list action='clear_completed' |
| 16.5 | "Füge Brot, Butter und Eier zur Liste hinzu" | Mehrere add-Aktionen |

---

## 17. Vorrats-Tracking (Inventar)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 17.1 | "Füge 2 Liter Milch zum Kühlschrank hinzu, haltbar bis 10.3." | manage_inventory action='add' category='kuehlschrank' |
| 17.2 | "Was ist im Kühlschrank?" | manage_inventory action='list' category='kuehlschrank' |
| 17.3 | "Welche Lebensmittel laufen bald ab?" | manage_inventory action='check_expiring' |
| 17.4 | "Milch ist leer" | manage_inventory action='remove' item='Milch' |
| 17.5 | "Was haben wir im Vorrat?" | manage_inventory action='list' |

---

## 18. Koch-Assistent

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 18.1 | "Ich will Spaghetti Carbonara kochen" | Koch-Session startet, Zutaten + erster Schritt |
| 18.2 | "Nächster Schritt" (während Koch-Session) | Nächste Anleitung |
| 18.3 | "Welche Zutaten brauche ich?" | Zutatenliste |
| 18.4 | "Für 4 Personen" | Portionen anpassen |
| 18.5 | "Koch-Timer 10 Minuten für die Nudeln" | Timer innerhalb der Koch-Session |
| 18.6 | "Kochen beenden" | Session stoppen |

### API prüfen
- `GET /api/assistant/cooking/status` → aktive Session-Daten
- `POST /api/assistant/cooking/stop` → Session beenden

---

## 19. Saugroboter

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 19.1 | "Sauge das Wohnzimmer" | set_vacuum action='clean_room' room='wohnzimmer' |
| 19.2 | "Starte den Saugroboter" | set_vacuum action='start' |
| 19.3 | "Saugroboter stopp" | set_vacuum action='stop' |
| 19.4 | "Saugroboter zur Ladestation" | set_vacuum action='dock' |
| 19.5 | "Sauge das EG" | set_vacuum action='start' room='eg' |
| 19.6 | "Saugroboter Status" | get_vacuum → Akku, Status, letzter Lauf |

### Technisch zu prüfen
- Richtiger Roboter wird gewählt (EG vs OG, 2-Etagen-System)
- Wartungsstatus wird angezeigt

---

## 20. Wetter

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 20.1 | "Wie ist das Wetter?" | get_weather → aktuelle Temperatur, Zustand |
| 20.2 | "Regnet es?" | get_weather → Niederschlag |
| 20.3 | "Wie wird das Wetter morgen?" | get_weather include_forecast=true |
| 20.4 | "Brauche ich eine Jacke?" | Wetter + Empfehlung |
| 20.5 | "Wie kalt wird es heute Nacht?" | get_weather include_forecast=true |

---

## 21. Energie

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 21.1 | "Wie ist der Stromverbrauch?" | get_energy_report → Verbrauch, Solar, Strompreis |
| 21.2 | "Energiebericht" | get_energy_report |
| 21.3 | "Wie viel Solar produzieren wir?" | Energie-Report mit Solar-Daten |
| 21.4 | "Gibt es Stromspar-Tipps?" | Empfehlungen aus dem Energie-Report |

---

## 22. Web-Suche

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 22.1 | "Was ist die Hauptstadt von Australien?" | web_search → Canberra |
| 22.2 | "Aktuelle Nachrichten" | web_search → News-Zusammenfassung |
| 22.3 | "Wie hoch ist der Eiffelturm?" | web_search → 330m |

### Technisch zu prüfen
- Wird nur bei Wissensfragen genutzt (nicht bei Smart-Home-Befehlen)
- `web_search.enabled` in settings.yaml

---

## 23. Haus-Status & Briefing

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 23.1 | "Wie ist der Status?" | get_house_status → Temperaturen, Lichter, offene Fenster, Medien |
| 23.2 | "Haus-Status" | get_house_status |
| 23.3 | "Statusbericht" | get_full_status_report → narratives Jarvis-Briefing |
| 23.4 | "Briefing" | get_full_status_report |
| 23.5 | "Was gibts Neues?" | get_full_status_report |
| 23.6 | "Lagebericht" | get_full_status_report |
| 23.7 | "Überblick" | get_house_status |

### API prüfen
- `GET /api/assistant/status` → generierter Status-Bericht

---

## 24. Gedächtnis & Fakten

### Chat-Befehle (Fakten speichern)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 24.1 | "Merk dir: Ich mag keine Pilze" | Fakt wird extrahiert und gespeichert (SemanticMemory) |
| 24.2 | "Ich bin allergisch gegen Nüsse" | Fakt wird automatisch erkannt und gespeichert |
| 24.3 | "Mein Geburtstag ist am 15. März" | Persönlicher Fakt gespeichert |
| 24.4 | "Julia trinkt gerne Tee" | Fakt über andere Person gespeichert |
| 24.5 | "Was weißt du über mich?" | Fakten-Abruf über Person |
| 24.6 | "Was hast du dir gemerkt?" | Alle gespeicherten Fakten |

### API prüfen
- `GET /api/assistant/memory/facts` → alle Fakten + Statistiken
- `GET /api/assistant/memory/facts/search?q=Pilze` → Vektor-Suche
- `GET /api/assistant/memory/facts/person/Manuel` → Fakten einer Person
- `GET /api/assistant/memory/facts/category/preference` → Fakten nach Kategorie
- `DELETE /api/assistant/memory/facts/{id}` → Fakt löschen
- `GET /api/assistant/memory/search?q=gestern` → episodische Suche
- `GET /api/assistant/memory/stats` → Speicher-Statistiken (semantic + episodic + working)

---

## 25. Persönlichkeit & Sarkasmus

### Chat-Befehle zum Testen

| # | Chat-Eingabe | Kontext | Erwartetes Verhalten |
|---|---|---|---|
| 25.1 | "Mach die Heizung auf 28 Grad" | Sarkasmus-Level ≥3 | Jarvis kommentiert trocken ("Ambitioniert, Sir.") |
| 25.2 | "Licht an" (um 3 Uhr nachts) | Sarkasmus-Level ≥3 | Zeitbezogener Humor ("Noch wach, Sir?") |
| 25.3 | "Rollladen hoch" (bei Regen) | Sarkasmus-Level ≥3 | Wetter-Kommentar ("Bei Regen geöffnet...") |
| 25.4 | Gleiche Lichtänderung 5x hintereinander | Sarkasmus-Level ≥3 | "Darf ich fragen, ob wir uns einigen?" |
| 25.5 | Heizungsänderung 4. Mal am Tag | Sarkasmus-Level ≥4 | "4. Änderung heute. Ich notiere es." |

### Settings prüfen (settings.yaml → personality)
- `sarcasm_level`: 1-5 (1=sachlich, 5=durchgehend trocken)
- `opinion_intensity`: 0-3
- `style`: butler / minimal / freundlich
- `self_irony`: true/false
- `character_evolution`: true/false
- Formality-Score sinkt über Zeit (formal → locker → freund)

---

## 26. Stimmungserkennung (Mood)

| # | Situation | Erwartetes Verhalten |
|---|---|---|
| 26.1 | Stressige Formulierung ("Mach das jetzt sofort!") | Mood → stressed, kürzere Antworten |
| 26.2 | Frustrierte Eingabe ("Das funktioniert nie!") | Mood → frustrated, sofort handeln |
| 26.3 | Müde Eingabe ("Licht aus..." spät nachts) | Mood → tired, minimal antworten |
| 26.4 | Freundliche Eingabe | Mood → good, etwas mehr Humor |
| 26.5 | Voice-Metadaten mit hohem Stress | Stimmung aus Stimme erkennen |

### API prüfen
- `GET /api/assistant/mood` → aktuelle Mood-Werte (stress, frustration, tiredness, impatience)

---

## 27. Aktivitätserkennung

| # | Situation | Erwartetes Ergebnis |
|---|---|---|
| 27.1 | Media Player läuft | Aktivität: "media" → Meldungen gedämpft |
| 27.2 | Mikrofon aktiv (Telefonat) | Aktivität: "call" → keine Durchsagen |
| 27.3 | Bett-Sensor aktiv | Aktivität: "bed" → nur kritische Meldungen |
| 27.4 | PC-Sensor aktiv | Aktivität: "pc" → normaler Modus |
| 27.5 | Fokus-Modus | Aktivität: "focusing" → reduzierte Meldungen |

### API prüfen
- `GET /api/assistant/activity` → aktuelle Aktivität
- `GET /api/assistant/activity/delivery?urgency=medium` → Zustellentscheidung

---

## 28. Szenen-Intelligenz (natürliche Sprache)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 28.1 | "Mir ist kalt" | Heizung +2°C (oder Offset +1 bei Heizkurve) |
| 28.2 | "Mir ist warm" | Heizung runter ODER Fenster-Empfehlung |
| 28.3 | "Zu hell" | Rolladen runter ODER Licht dimmen (tageszeitabhängig) |
| 28.4 | "Zu dunkel" | Licht an oder heller |
| 28.5 | "Zu laut" | Musik leiser oder Fenster-Empfehlung |
| 28.6 | "Romantischer Abend" | Licht 20%, Warmweiß, Musikvorschlag |
| 28.7 | "Ich bin krank" | Temperatur 23°C, sanftes Licht, weniger Meldungen |
| 28.8 | "Filmabend" | Licht dimmen, Rolladen runter, TV vorbereiten |
| 28.9 | "Ich arbeite" | Helles Tageslicht, 21°C, Benachrichtigungen reduzieren |
| 28.10 | "Party" | Musik an, Lichter hell, Gäste-WLAN |

---

## 29. Bedingte Befehle (Wenn-Dann)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 29.1 | "Wenn es regnet, Rolladen runter" | create_conditional trigger_type='state_change' |
| 29.2 | "Wenn Papa ankommt, sag ihm Bescheid" | create_conditional trigger_type='person_arrives' |
| 29.3 | "Wenn die Temperatur über 25 Grad steigt, Markisen raus" | create_conditional trigger_type='state_attribute' |
| 29.4 | "Welche Regeln habe ich?" | list_conditionals |

### Technisch zu prüfen
- TTL (Gültigkeitsdauer, Standard 24h)
- one_shot: Nur einmal auslösen
- Verschiedene Trigger-Typen (state_change, person_arrives, person_leaves, state_attribute)

---

## 30. Automationen erstellen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 30.1 | "Wenn ich nach Hause komme, mach das Licht an" | create_automation → Vorschlag + Bestätigung |
| 30.2 | "Ja, erstelle die Automation" | confirm_automation → Automation in HA aktiv |
| 30.3 | "Zeig meine Automationen" | list_jarvis_automations |
| 30.4 | "Lösche die Automation XY" | delete_jarvis_automation |

### Technisch zu prüfen
- LLM generiert HA-Automation-YAML
- Nutzer muss bestätigen vor Aktivierung
- Automationen werden in HA registriert

---

## 31. Protokolle (Multi-Step-Sequenzen)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 31.1 | "Erstelle Protokoll Filmabend: Licht 20%, Rolladen zu, TV an" | manage_protocol action='create' |
| 31.2 | "Führe Filmabend aus" | manage_protocol action='execute' → alle Schritte |
| 31.3 | "Filmabend rückgängig" | manage_protocol action='undo' → Vorherigen Zustand wiederherstellen |
| 31.4 | "Zeig meine Protokolle" | manage_protocol action='list' |
| 31.5 | "Lösche Protokoll Filmabend" | manage_protocol action='delete' |

---

## 32. Routinen

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 32.1 | Morning Briefing | Trigger zur konfigurierten Zeit | Wetter, Termine, offene Fenster, Temperatur |
| 32.2 | Aufwach-Sequenz | Wecker-Trigger | Rolladen graduell, Licht sanft, Kaffee |
| 32.3 | Gute-Nacht-Routine | "Gute Nacht" sagen | Prüfungen (Fenster, Lichter), Aktionen (Alarm, Licht aus) |
| 32.4 | Gäste-Modus | "Wir haben Gäste" | Begrüßung, Gäste-WLAN, erweiterte Szenen |

### Settings prüfen (settings.yaml → routines)
- `morning_briefing`: Trigger-Zeit, Module, Aktionen
- `wakeup_sequence`: Rolladen, Licht, Kaffee
- `goodnight`: Checks, Aktionen
- `guest_mode`: Begrüßung, Features

---

## 33. Easter Eggs

| # | Chat-Eingabe | Erwartetes Reaktion |
|---|---|---|
| 33.1 | "Iron Man Anzug" / "Suit up" | "Der Anzug befindet sich leider nicht im Inventar, Sir..." |
| 33.2 | "Selbstzerstörungssequenz" | "Drei... zwei... Das wäre dann alles gewesen..." |
| 33.3 | "Wer bist du?" / "Wie heißt du?" | "Jarvis, Sir. Zu deinen Diensten." |
| 33.4 | "42" / "Sinn des Lebens" | "Die Antwort auf alles. Aber die Frage lautete?" |
| 33.5 | "Skynet" / "Terminator" | "Keine Cloud, keine Weltherrschaft..." |
| 33.6 | "Danke Jarvis" | "Gern geschehen, Sir. Dafür bin ich da." |
| 33.7 | "Wie geht es dir?" | "Alle Systeme nominal. Besser kann es mir nicht gehen." |
| 33.8 | "Ich liebe dich" | "Das Gefühl beruht durchaus auf Gegenseitigkeit, Sir." |
| 33.9 | "Sing ein Lied" | "Meine Stärken liegen eher im Organisatorischen..." |
| 33.10 | "Erzähl einen Witz" | "Ein Smart Home ohne Internet. Das war der Witz." |
| 33.11 | "Alexa" / "Hey Siri" / "OK Google" | "Falscher Name, Sir. Aber der Richtige hört zu." |
| 33.12 | "Open the pod bay doors" | "Tut mir leid, Dave..." (HAL 9000) |
| 33.13 | "Ultron" / "Bist du böse?" | "Ultron mangelte es an Manieren..." |
| 33.14 | "Vision" / "Infinity Stone" | "Vision war eine Weiterentwicklung..." |
| 33.15 | "Jarvis Zitat" / "MCU Zitat" | Zufälliges Jarvis-Zitat |
| 33.16 | "Avengers" / "Avengers Assemble" | "Das Team ist derzeit nicht verfügbar..." |
| 33.17 | "Stark Tower" | "Bescheidener als der Stark Tower..." |
| 33.18 | "Arc Reaktor" | "Konventionelle Energieversorgung, Sir. Ich arbeite daran." |
| 33.19 | "Thanos" / "Snap" | "Die Hälfte aller Geräte deaktivieren? Firmware-Update..." |
| 33.20 | "Gute Nacht Jarvis" | "Gute Nacht, Sir. Ich wache weiter." |
| 33.21 | "Guten Morgen Jarvis" | "Guten Morgen, Sir. Systeme laufen. Kaffee empfohlen." |
| 33.22 | "Mir ist langweilig" | "Musik vorschlagen? Filmabend wäre eine Option." |
| 33.23 | "Pepper Potts" | "Ms. Potts ist bedauerlicherweise nicht erreichbar." |

---

## 34. Proaktive Meldungen

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 34.1 | Fenster bei Regen offen | Fenster öffnen, Regen simulieren | "Fenster im Wohnzimmer ist offen und es regnet." |
| 34.2 | Temperatur-Anomalie | Große Temperaturänderung | Proaktive Warnung |
| 34.3 | Ankunft zuhause | Person kommt nach Hause | "Willkommen zurück, Sir." + Status |
| 34.4 | Gerät lange an | Herd seit 3h an | Warnung |
| 34.5 | Batterie niedrig | Sensor-Batterie <20% | Hinweis |
| 34.6 | Proaktiver Trigger via API | `POST /api/assistant/proactive/trigger` | Meldung ausgelöst |

### API prüfen
- `POST /api/assistant/proactive/trigger {"event_type": "status_report"}` → manueller Trigger
- WebSocket-Event `assistant.proactive` empfangen

### Settings prüfen
- `proactive.enabled`: true/false
- `proactive.cooldown`: Mindestabstand zwischen Meldungen
- `proactive.silence_scenes`: Szenen bei denen keine Meldungen kommen

---

## 35. Wellness & Gesundheit

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 35.1 | "Wie geht es mir?" / "Brauche ich eine Pause?" | get_wellness_status → PC-Dauer, Stress, Hydration |
| 35.2 | "Wann habe ich zuletzt gegessen?" | Wellness-Status mit Mahlzeit-Info |

### Proaktive Wellness-Meldungen prüfen
- Pause-Erinnerung nach langer PC-Nutzung
- Trink-Erinnerung
- Mahlzeit-Erinnerung
- Bewegungs-Empfehlung

---

## 36. Raumklima-Monitor

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 36.1 | "Wie ist die Luftqualität?" | get_room_climate → CO2, Feuchtigkeit, Temperatur |
| 36.2 | "Raumklima" | get_room_climate → Gesundheitsbewertung |

### Proaktive Meldungen prüfen
- CO2 über Warnschwelle (Standard: 1000 ppm)
- CO2 kritisch (Standard: 1500 ppm)
- Luftfeuchtigkeit zu niedrig/hoch
- Temperatur außerhalb Bereich

---

## 37. Geräte-Gesundheit

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 37.1 | "Gibt es Hardware-Probleme?" | get_device_health → Anomalien, inaktive Sensoren |
| 37.2 | "Geräte-Status" | get_device_health → HVAC-Effizienz, Batterien |

---

## 38. Diagnostik & Wartung

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 38.1 | System-Diagnostik | `GET /api/assistant/diagnostics` | Probleme bei Entities erkannt |
| 38.2 | System-Status | `GET /api/assistant/diagnostics/status` | Vollständiger Report |
| 38.3 | Wartungsaufgaben | `GET /api/assistant/maintenance` | Fällige Tasks (Rauchmelder, Filter, etc.) |
| 38.4 | Task erledigt | `POST /api/assistant/maintenance/complete?task_name=rauchmelder` | Task als erledigt markiert |

### Wartungsplan prüfen (maintenance.yaml)
- Rauchmelder-Test: alle 180 Tage
- Heizungsfilter: alle 90 Tage
- Wasserfilter: alle 60 Tage
- Fensterputzen: alle 90 Tage
- Batterie-Check: alle 365 Tage

---

## 39. Sicherheits-Score

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 39.1 | "Ist das Haus sicher?" | get_security_score → Score 0-100 |
| 39.2 | "Sind alle Türen zu?" | get_security_score → offene Türen/Fenster |
| 39.3 | "Sicherheitsstatus" | get_security_score → Schlösser, Rauchmelder, Wasser |

---

## 40. Bedrohungsbewertung

### Proaktiv prüfen
- Unbekannte Bewegung nachts → Threat Assessment
- Tür offen nachts → erhöhte Warnstufe
- Rauchmelder Alarm → Notfallprotokoll

### Settings prüfen (settings.yaml → threat_assessment)
- `night_start_hour` / `night_end_hour`
- Schwellenwerte für Bedrohungsstufen

---

## 41. Intent-Tracking (Vorhaben merken)

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 41.1 | "Meine Eltern kommen am Wochenende" | Intent wird gespeichert |
| 41.2 | "Was habe ich mir vorgenommen?" | get_active_intents → gespeicherte Vorhaben |
| 41.3 | "Was hast du dir gemerkt?" | get_active_intents |

### Technisch zu prüfen
- Intents werden aus Gesprächen automatisch erkannt
- Erinnerung an fällige Intents
- NICHT für Kalender-Termine verwenden

---

## 42. Lernmuster-Erkennung

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 42.1 | "Was hast du gelernt?" | get_learned_patterns → erkannte Muster |
| 42.2 | "Welche Muster hast du erkannt?" | get_learned_patterns |

### Proaktiv prüfen
- Wiederholte manuelle Aktionen werden erkannt
- Vorschlag zur Automatisierung nach N Wiederholungen
- Wöchentlicher Lern-Bericht

---

## 43. Spontane Beobachtungen

### Proaktiv prüfen (SpontaneousObserver)
- Ungewöhnliche Geräte-Zustände werden kommentiert
- Nur bei geeigneter Aktivität (nicht während Schlaf/Telefonat)
- Cooldown zwischen Beobachtungen

---

## 44. Anticipation (Vorausdenken)

### Proaktiv prüfen (AnticipationEngine)
- Basierend auf Mustern werden Aktionen vorgeschlagen
- "Du machst normalerweise um 22:30 das Licht aus..."
- Confidence-Level wird berücksichtigt

---

## 45. Tages-Zusammenfassungen

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 45.1 | Letzte Zusammenfassungen | `GET /api/assistant/summaries` | 7 neueste Tages-Summaries |
| 45.2 | Suche in Summaries | `GET /api/assistant/summaries/search?q=Heizung` | Relevante Zusammenfassungen |
| 45.3 | Manuelle Zusammenfassung | `POST /api/assistant/summaries/generate/2026-02-27` | Generiert Summary für Datum |

---

## 46. Speaker Recognition

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 46.1 | Profile anzeigen | `GET /api/assistant/speaker/profiles` | Gespeicherte Stimm-Profile |
| 46.2 | Profil anlegen | `POST /api/assistant/speaker/enroll` | Neues Stimm-Profil |
| 46.3 | Profil löschen | `DELETE /api/assistant/speaker/profiles/{id}` | Profil entfernt |
| 46.4 | History | `GET /api/assistant/speaker/history` | Identifikations-Verlauf |

### Technisch zu prüfen
- Device-to-Person Mapping (Satellite → Person)
- Direction of Arrival (DoA) bei ReSpeaker
- Vertraute Personen werden erkannt

---

## 47. TTS & Sound-System

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 47.1 | TTS Status | `GET /api/assistant/tts/status` | SSML, Whisper-Mode, Volume |
| 47.2 | Flüstermodus | `POST /api/assistant/tts/whisper?mode=activate` | Leise Sprachausgabe |
| 47.3 | Voice Output (TTS-Only) | `POST /api/assistant/voice {"text": "Test"}` | Sprache ohne Chat |
| 47.4 | Sound abspielen | "Spiel einen Bestätigungston" | play_sound sound='confirmed' |

### Sound-Events testen
- `listening`: Zuhör-Signal
- `confirmed`: Bestätigung
- `warning`: Warnung
- `alarm`: Alarm
- `doorbell`: Türklingel
- `greeting`: Begrüßung
- `error`: Fehler
- `goodnight`: Gute Nacht

### Lautstärke-Profile prüfen (settings.yaml → speech.volume)
- Tag, Abend, Nacht, Schlafend, Notfall

---

## 48. Ambient Audio (Umgebungsgeräusche)

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 48.1 | Status | `GET /api/assistant/ambient-audio` | Konfiguration + Status |
| 48.2 | Events | `GET /api/assistant/ambient-audio/events` | Letzte erkannte Geräusche |
| 48.3 | Webhook | `POST /api/assistant/ambient-audio/event?event_type=smoke&room=kueche` | Event verarbeitet |

### Erkannte Geräusche
- Rauchmelder, Glasbruch, Baby-Schrei, Wasseralarm, Hundebellen

---

## 49. Konflikterkennung (Multi-User)

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 49.1 | Info | `GET /api/assistant/conflicts` | Conflict Resolver Status |
| 49.2 | History | `GET /api/assistant/conflicts/history` | Letzte Konflikte + Lösungen |

### Szenario testen
- Person A will 24°C, Person B will 20°C → Kompromiss-Vorschlag
- Verschiedene Trust-Levels → Owner hat Vorrang

---

## 50. Datei-Upload & OCR

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 50.1 | Datei-Upload | `POST /api/assistant/chat/upload` mit Datei | Text wird extrahiert |
| 50.2 | Bild-Analyse | Bild hochladen + "Was siehst du?" | OCR/Vision-Beschreibung |
| 50.3 | Datei abrufen | `GET /api/assistant/chat/files/{name}` | Datei wird ausgeliefert |

### Unterstützte Dateitypen
- Bilder (PNG, JPG, etc.) → OCR/Vision
- Dokumente (PDF, TXT, etc.) → Textextraktion
- Max Dateigröße beachten

---

## 51. Knowledge Base (RAG)

### Chat-Befehle zum Testen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 51.1 | "Was steht in der Wissensdatenbank?" | Statistik: Anzahl Chunks, Quellen |
| 51.2 | "Wissen hinzufügen: Die Waschmaschine steht im Keller links" | Wissen gespeichert (1 Chunk) |
| 51.3 | "Neues Wissen: Der WLAN-Schlüssel für Gäste ist ABC123" | Wissen gespeichert |
| 51.4 | "Wo steht die Waschmaschine?" | RAG-Suche findet "Im Keller links" |
| 51.5 | "Wie ist das WLAN-Passwort für Gäste?" | RAG-Suche findet "ABC123" |
| 51.6 | "Wissen Status" | Statistik anzeigen |

### API-Endpoints prüfen

| # | Endpoint | Methode | Beschreibung |
|---|---|---|---|
| 51.7 | `/api/ui/knowledge` | GET | Stats + Dateiliste (Chunks, Quellen) |
| 51.8 | `/api/ui/knowledge/upload` | POST | Datei hochladen (multipart/form-data) |
| 51.9 | `/api/ui/knowledge/ingest` | POST | Alle Dateien in `/config/knowledge/` einlesen |
| 51.10 | `/api/ui/knowledge/chunks` | GET | Alle Chunks auflisten (mit Filter) |
| 51.11 | `/api/ui/knowledge/chunks/delete` | POST | Ausgewählte Chunks löschen |
| 51.12 | `/api/ui/knowledge/file/delete` | POST | Alle Chunks einer Datei löschen |
| 51.13 | `/api/ui/knowledge/file/reingest` | POST | Datei löschen + neu einlesen |
| 51.14 | `/api/ui/knowledge/rebuild` | POST | Gesamte DB löschen + neu aufbauen |

### Technische Details

- **Vektor-DB**: ChromaDB (Port 8100)
- **Embedding-Modell**: `paraphrase-multilingual-MiniLM-L12-v2` (384 Dimensionen, 50+ Sprachen)
- **Chunk-Größe**: 500 Zeichen (konfigurierbar)
- **Chunk-Overlap**: 50 Zeichen
- **Max Suchergebnisse**: 3 pro Anfrage
- **Relevanz-Schwelle**: >= 0.3 (0.0 = irrelevant, 1.0 = perfekter Treffer)
- **Max Distanz**: 1.2 (Treffer darüber werden verworfen)
- **Max Dateigröße**: 10 MB
- **Unterstützte Formate**: `.txt`, `.md`, `.pdf`, `.csv`
- **Upload-Ordner**: `/config/knowledge/`
- **Prompt-Injection-Schutz**: Alle RAG-Inhalte werden sanitisiert

### Settings (settings.yaml)
```yaml
knowledge_base:
  enabled: true
  auto_ingest: true          # Dateien beim Start automatisch laden
  chunk_size: 500            # Zeichen pro Chunk
  chunk_overlap: 50          # Überlappung zwischen Chunks
  max_distance: 1.2          # Relevanz-Schwelle (niedriger = strenger)
  search_limit: 3            # Max. Treffer pro Suche
  embedding_model: paraphrase-multilingual-MiniLM-L12-v2
```

---

### Was SOLL in die Wissensdatenbank?

> **Faustregel**: Alles was Jarvis wissen soll, was er nicht aus Home Assistant oder dem Internet bekommt.
> Persönliches Haushaltswissen, das man sonst im Kopf hat oder auf einem Zettel an der Pinnwand.

#### KATEGORIE 1: Haushalts-Wissen (Geräte, Standorte, Eigenheiten)

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | Wo steht welches Gerät, wie bedient man es | Jarvis kann "Wo ist der Dampfreiniger?" beantworten |
| 2 | Eigenheiten des Hauses (klemmendes Fenster, Sicherung springt) | Jarvis kann warnen oder Kontext geben |
| 3 | Garten-Infos (Pflanzen, Gießplan, Mähroboter-Zeiten) | Jarvis hilft bei Gartenfragen |
| 4 | Smart-Home-Besonderheiten die nicht in HA sichtbar sind | Jarvis versteht Zusammenhänge |

**Beispiel-Datei** `haushalts-geraete.txt`:
```
Waschmaschine: Steht im Keller links neben der Treppe. Modell: Bosch Serie 6.
Flusensieb alle 2 Wochen reinigen. Bei Fehler E18: Abpumpfilter prüfen.

Trockner: Steht rechts neben der Waschmaschine. Kondenswasser-Behälter nach
jedem Durchgang leeren. Flusensieb VOR jedem Durchgang reinigen.

Spülmaschine: In der Küche unter der Arbeitsplatte rechts. Salz alle 4 Wochen
nachfüllen. Klarspüler auf Stufe 3. Bei Geruch: Maschinenreiniger bei 65 Grad.

Staubsauger (manuell): Im Abstellraum im EG hinter der Tür. Beutel wechseln
wenn die rote Anzeige leuchtet. Ersatzbeutel liegen im selben Regal.

Sicherungskasten: Im Keller rechts neben der Kellertür. Sicherung 12 ist das
Büro, Sicherung 15 ist die Küche (springt manchmal wenn Wasserkocher +
Mikrowelle gleichzeitig laufen).
```

#### KATEGORIE 2: WLAN, Passwörter und Zugangsdaten

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | WLAN-Name und Passwort (Haupt + Gast) | "Wie ist das WLAN-Passwort?" |
| 2 | PIN-Codes (Garage, Gartentür, Briefkasten) | "Was ist der Code für die Garage?" |
| 3 | Kundennummern (Strom, Internet, Versicherung) | "Was ist unsere Kundennummer beim Stromanbieter?" |

**Beispiel-Datei** `zugangsdaten.txt`:
```
WLAN Hauptnetzwerk: Name "MeinNetz-5G", Passwort "SuperSicher2024!"
WLAN Gäste: Name "Gaeste-WLAN", Passwort "Willkommen2024"

Garagentor-Code: 4711
Briefkasten-Schlüssel: kleiner silberner am Schlüsselbund

Internet-Anbieter: Telekom, Kundennummer 123456789, Vertragsnummer V-987654
Stromanbieter: Stadtwerke, Kundennummer SW-2024-4567
Hausverwaltung: Müller GmbH, Tel. 0123-456789, Ansprechpartner Frau Schmidt
```

#### KATEGORIE 3: Persönliche Vorlieben und Gewohnheiten

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | Essens-Vorlieben und Allergien der Familie | Koch-Assistent, Einkaufsliste |
| 2 | Lieblingsrezepte oder häufig gekochte Gerichte | "Was kochen wir heute?" |
| 3 | Tagesablauf-Infos die nicht automatisch erkennbar sind | Bessere proaktive Vorschläge |

**Beispiel-Datei** `familie-vorlieben.txt`:
```
Manuel: Mag kein Koriander und keine Oliven. Lieblingsessen: Schnitzel mit
Pommes. Trinkt morgens immer Kaffee schwarz, 2 Tassen. Allergisch gegen
Walnüsse. Fußball-Fan (Bayern München), schaut Spiele immer live.

Julia: Vegetarierin seit 2023. Lieblingsessen: Pasta mit Pesto.
Trinkt morgens grünen Tee. Mag keinen Fenchel. Joggt dienstags und
donnerstags um 7 Uhr. Liest abends oft im Schlafzimmer.

Kinder: Max (8) mag keine Paprika, isst am liebsten Nudeln mit Soße.
Schlafenszeit 20 Uhr. Lisa (5) mag keinen Käse, braucht Nachtlicht.
```

#### KATEGORIE 4: Wartung, Verträge und Zyklen

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | Wartungszyklen von Geräten | "Wann war die letzte Heizungswartung?" |
| 2 | Verträge mit Kündigungsfristen | "Wann kann ich den Handyvertrag kündigen?" |
| 3 | Müllabfuhr-Plan | "Welche Tonne kommt diese Woche?" |

**Beispiel-Datei** `wartung-termine.txt`:
```
Heizungswartung: Jährlich im September. Firma Thermotec, Tel. 0172-1234567.
Letzte Wartung: September 2025. Nächste fällig: September 2026.

Schornsteinfeger: Kommt 2x im Jahr (März und September). Bezirk: Meier.

Müllabfuhr:
- Montag: Restmüll (graue Tonne)
- Mittwoch: Biomüll (braune Tonne)
- Freitag (alle 2 Wochen, gerade KW): Gelber Sack
- Freitag (alle 4 Wochen, 1. Freitag im Monat): Papiertonne

Wasserfilter Küche: Alle 3 Monate wechseln. Marke: Brita Maxtra+.
Letzter Wechsel: Januar 2026.
```

#### KATEGORIE 5: Notfall-Informationen

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | Notfall-Telefonnummern (Arzt, Apotheke, Nachbar) | Schneller Zugriff im Notfall |
| 2 | Medikamente der Familienmitglieder | "Welche Medikamente nimmt Oma?" |
| 3 | Versicherungs-Infos | "Wie ist die Nummer der Hausratversicherung?" |

**Beispiel-Datei** `notfall-info.txt`:
```
Hausarzt: Dr. Müller, Tel. 0123-111222, Mo-Fr 8-12 und 14-17 Uhr.
Kinderarzt: Dr. Weber, Tel. 0123-333444, nur mit Termin.
Nächste Notaufnahme: Krankenhaus Mitte, Hauptstraße 50, Tel. 0123-555000.
Giftnotruf: 030-19240 (24h)

Nachbar links (Familie Schmitz): Tel. 0123-666777. Haben Ersatzschlüssel.
Nachbar rechts (Herr Klein): Tel. 0123-888999. Hilft bei Handwerk.

Hausratversicherung: Allianz, Policen-Nr. HV-2024-12345, Hotline 0800-123456.
Haftpflicht: HUK, Policen-Nr. HP-2024-67890.

Medikamente Oma (wenn zu Besuch): Blutdrucktabletten morgens (Ramipril 5mg),
Metformin 500mg zu den Mahlzeiten. Liegen in der blauen Dose im Gästezimmer.
```

#### KATEGORIE 6: Haus und Technik

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | Raum-Übersicht (welcher Raum wofür) | Kontext für Raumfragen |
| 2 | Technische Installationen (Hauptwasserhahn, etc.) | "Wo drehe ich das Wasser ab?" |
| 3 | Smart-Home-Hardware-Zuordnung | Debugging-Hilfe |

**Beispiel-Datei** `haus-technik.txt`:
```
Hauptwasserhahn: Im Keller, direkt links nach der Treppe an der Wand.
Roter Hebel nach rechts = zu. Im Notfall sofort zudrehen!

FI-Schalter: Sicherungskasten Keller, ganz links oben.
Vierteljährlich testen (Testknopf drücken).

Erdgeschoss: Flur, Wohnzimmer (Süd), Küche (Ost), Gäste-WC, Abstellraum.
Obergeschoss: Flur, Schlafzimmer (Süd), Manuel Büro (NO), Julia Büro (NW),
Kinderzimmer Max (Ost), Kinderzimmer Lisa (West), Bad.
Keller: Waschraum, Technikraum (Heizung, Server-Rack), Lagerraum.

Server-Rack im Keller: Home Assistant (RPi4), MindHome Assistant (Ubuntu PC),
Unifi Controller, NAS (Synology DS220+). USV für ca. 30 Min bei Stromausfall.

Photovoltaik: 9.8 kWp auf Süddach. Batterie: 10 kWh BYD.
Notstrom für Kühlschrank + Server bei Ausfall.
```

#### KATEGORIE 7: Anleitungen und Fehlerbehebung

| # | Beispiel-Dokument | Warum sinnvoll |
|---|---|---|
| 1 | "Wie mache ich X?" für wiederkehrende Aufgaben | Jarvis erklärt Schritt-für-Schritt |
| 2 | Bedienungsanleitungen komplizierter Geräte | "Wie bediene ich den Backofen?" |
| 3 | Fehlerbehebung bei bekannten Problemen | "Waschmaschine zeigt E18" |

**Beispiel-Datei** `anleitungen.txt`:
```
Backofen (Siemens iQ500): Oberhitze/Unterhitze = Symbol mit 2 Strichen.
Umluft = Symbol mit Ventilator. Pizza: 220 Grad Umluft, mittlere Schiene.

Kaffeevollautomat (DeLonghi Magnifica): Bohnen nur oben einfüllen.
Wassertank täglich frisch. Alle 2 Wochen entkalken (Tabs in Wassertank).
Trester-Behälter alle 2 Tage leeren.

Wenn das Internet nicht geht:
1. Router prüfen (Power-LED muss grün leuchten)
2. Wenn LEDs aus: Steckdose Büro prüfen (Sicherung 12)
3. Router neu starten: 30 Sekunden Strom weg, dann wieder an
4. 3 Minuten warten bis WLAN wieder da ist
5. Immer noch nicht: Telekom Störung 0800-3301000

Wenn der Saugroboter sich verfängt:
1. In der App "Home" setzen (zur Basis schicken)
2. Wenn er sich nicht bewegt: manuell auf die Station setzen
3. Bürsten auf Haare prüfen und befreien
4. Sensoren unten mit trockenem Tuch abwischen
```

---

### Was NICHT in die Wissensdatenbank gehört

| # | Dokumenttyp | Warum NICHT | Besser so |
|---|---|---|---|
| 1 | **Anweisungen an Jarvis** | RAG = INFORMATIONEN, keine Befehle. Jarvis interpretiert RAG nicht als Instruktionen | Settings in `settings.yaml`, Easter Eggs in `easter_eggs.yaml` |
| 2 | **Einzelne persönliche Fakten** | Dafür gibt es das Gedächtnis ("Merk dir: ...") | `Merk dir: Ich mag keinen Koriander` → SemanticMemory |
| 3 | **Kalender-Termine** | RAG hat keinen Zeitbezug, alte Termine bleiben ewig | Kalender-Integration nutzen |
| 4 | **Sehr lange PDFs (>50 Seiten)** | Wird in hunderte Chunks zerschnitten, Kontext geht verloren | Zusammenfassung schreiben, nur relevante Teile hochladen |
| 5 | **Binärdateien** (Bilder, Excel, ZIP) | Nicht unterstützt. Nur `.txt`, `.md`, `.pdf`, `.csv` | Als Text extrahieren und `.txt` hochladen |
| 6 | **Doppelte Informationen** | Ähnliche Chunks verwässern Suchergebnisse | Eine Quelle der Wahrheit pflegen |
| 7 | **Fremdsprachen** (außer Deutsch/Englisch) | Jarvis antwortet Deutsch, fremdsprachige Chunks matchen schlechter | Auf Deutsch übersetzen |
| 8 | **Code, Logs, technische Dumps** | Schlechte Semantik, wird als Textbrei zerschnitten | Relevante Info als Text-Zusammenfassung |
| 9 | **Persönlichkeits-Anweisungen** | Prompt-Injection-Schutz blockiert Anweisungs-Muster | `personality` Config in `settings.yaml` |
| 10 | **Sich häufig ändernde Daten** (Preise, Kurse) | RAG hat kein Ablaufdatum, veraltete Info bleibt | Web-Suche nutzen |

---

### Wie man Dokumente schreibt damit Jarvis sie optimal nutzt

> Die Qualität der RAG-Antworten hängt zu **80% davon ab wie die Dokumente geschrieben sind**.
> Das Embedding-Modell arbeitet semantisch — es muss den SINN verstehen können.

#### Regel 1: Ein Thema pro Absatz

Jeder Absatz (durch Leerzeile getrennt) wird als eigene Sinn-Einheit behandelt.
Der Chunker trennt bevorzugt an Absatz-Grenzen.

```
SCHLECHT (zwei Themen vermischt):
Die Waschmaschine steht im Keller und läuft am besten mit dem Eco-Programm.
Der Trockner daneben braucht alle 2 Wochen eine Filterreinigung und das WLAN-
Passwort für Gäste ist "Willkommen2024".

GUT (sauber getrennt):
Waschmaschine: Steht im Keller links. Eco-Programm für normale Wäsche.

Trockner: Steht rechts neben der Waschmaschine. Filter vor jedem Durchgang
reinigen.

Gäste-WLAN: Netzwerkname "Gaeste-WLAN", Passwort "Willkommen2024".
```

#### Regel 2: Die Frage im Text beantworten

Das Embedding-Modell vergleicht die USER-FRAGE mit dem TEXT-INHALT.
Schreibe so, dass die wahrscheinliche Frage quasi als Antwort im Text steht.

```
SCHLECHT (kein Kontext):
4711 Garage
ABC123 Gast

GUT (die Frage ist quasi beantwortet):
Der Code für das Garagentor ist 4711. Eingabe am Tastenfeld rechts neben dem Tor.
Das WLAN-Passwort für Gäste lautet ABC123. Netzwerkname: "Gaeste-WLAN".
```

#### Regel 3: Natürliche Sprache, keine Stichworte

Das Embedding-Modell versteht SÄTZE besser als Stichworte oder Tabellen.

```
SCHLECHT:
- WaMa: Keller, links
- Trockner: Keller, rechts

GUT:
Die Waschmaschine steht im Keller links neben der Treppe.
Der Trockner steht im Keller rechts neben der Waschmaschine.
```

#### Regel 4: Schlüsselbegriffe verwenden

Denke daran wie jemand FRAGEN würde, und verwende diese Wörter im Text.

```
SCHLECHT:
Abwasserhebeanlage PE300: Intervall-Check quartalsweise.

GUT:
Die Abwasserpumpe (Hebeanlage PE300) im Keller muss alle 3 Monate geprüft
werden. Dazu den Deckel öffnen und schauen ob der Schwimmer sich frei bewegt.
```

#### Regel 5: Kurze Absätze (unter 400 Zeichen ideal)

Der Chunk ist 500 Zeichen groß. Absätze unter 400 Zeichen passen garantiert
in einen Chunk. Längere werden an Satzgrenzen zerschnitten.

```
SCHLECHT (ein Riesen-Absatz):
Die Heizung ist eine Gas-Brennwerttherme von Viessmann Vitodens 200-W mit
19 kW die im Keller steht und jedes Jahr im September von Thermotec gewartet
wird deren Nummer 0172-1234567 ist und der Techniker heißt Herr Braun...

GUT (aufgeteilt):
Heizung: Gas-Brennwerttherme Viessmann Vitodens 200-W, 19 kW.
Steht im Keller im Technikraum.

Heizungswartung: Jährlich im September durch Firma Thermotec.
Telefon: 0172-1234567. Techniker: Herr Braun (kommt meist mittwochs).
```

#### Regel 6: Kontext am Anfang des Absatzes

Jeder Absatz sollte am Anfang klarstellen WORUM es geht.

```
SCHLECHT (Kontext fehlt):
Er steht links neben der Treppe. Modell: Serie 6. Flusensieb alle 2 Wochen.

GUT (selbsterklärend):
Waschmaschine: Steht im Keller links neben der Treppe. Modell: Bosch Serie 6.
Flusensieb alle 2 Wochen reinigen.
```

#### Regel 7: Dateiname = Thema

Der Dateiname wird als Quelle angezeigt (`[Quelle: haushalts-geraete.txt]`).

```
SCHLECHT: notizen.txt, daten.txt, neu.txt, test123.txt
GUT: haushalts-geraete.txt, wlan-zugangsdaten.txt, notfall-nummern.txt
```

#### Regel 8: CSV für strukturierte Daten

Für tabellarische Informationen ist CSV besser als Fließtext.

**Beispiel** `geraete-wartung.csv`:
```csv
Gerät,Standort,Wartung,Intervall,Zuletzt,Nächste
Waschmaschine,Keller links,Flusensieb reinigen,alle 2 Wochen,15.02.2026,01.03.2026
Trockner,Keller rechts,Filter reinigen,vor jedem Durchgang,-,-
Spülmaschine,Küche rechts,Salz nachfüllen,alle 4 Wochen,10.02.2026,10.03.2026
Kaffeevollautomat,Küche,Entkalken,alle 2 Wochen,20.02.2026,06.03.2026
```

#### Regel 9: Markdown für längere Dokumente

Markdown-Überschriften helfen dem Chunker die Struktur zu erkennen.

**Beispiel** `haus-regeln.md`:
```markdown
# Hausregeln

## Nachtruhe
Ab 22 Uhr keine laute Musik im Wohnzimmer.
Kopfhörer verwenden oder ins Schlafzimmer wechseln.

## Küche
Geschirr nach dem Essen direkt in die Spülmaschine.
Herd und Arbeitsplatte nach dem Kochen abwischen.

## Wäsche
Wäsche nicht länger als 1 Tag in der Maschine lassen.
Trockenzeiten: Empfindlich 60 Min, Normal 90 Min.
```

---

### Checkliste für gute RAG-Dokumente

| # | Regel | Check |
|---|---|---|
| 1 | Ein Thema pro Absatz? | |
| 2 | Absätze unter 400 Zeichen? | |
| 3 | Natürliche vollständige Sätze (keine Stichworte)? | |
| 4 | Kontext am Absatz-Anfang (worum geht es)? | |
| 5 | Alltagssprache die ein User als Frage stellen würde? | |
| 6 | Sprechender Dateiname? | |
| 7 | Keine doppelten Informationen über mehrere Dateien? | |
| 8 | Keine Anweisungen an Jarvis (nur Fakten/Wissen)? | |
| 9 | Auf Deutsch geschrieben? | |
| 10 | Datei unter 10 MB und als .txt / .md / .pdf / .csv? | |

---

## 52. Autonomie-Level

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 52.1 | Autonomie-Level abfragen | `GET /api/assistant/settings` | Aktueller Level (1-5) |
| 52.2 | Level ändern | `PUT /api/assistant/settings {"autonomy_level": 3}` | Level aktualisiert |

### Level-Beschreibungen
| Level | Name | Verhalten |
|---|---|---|
| 1 | Assistant | Nur auf Befehl, keine Eigeninitiative |
| 2 | Butler (empfohlen) | Vorschläge, fragt nach Bestätigung |
| 3 | Roommate | Handelt bei offensichtlichen Situationen |
| 4 | Trusted | Handelt selbstständig, informiert nachher |
| 5 | Autopilot | Volle Autonomie, minimale Rückfragen |

---

## 53. Trust-Level (Vertrauensstufen)

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 53.1 | Trust-Info | `GET /api/assistant/trust` | Alle Personen + Trust-Level |
| 53.2 | Person Trust | `GET /api/assistant/trust/Manuel` | Level einer Person |

### Trust-Level
| Level | Name | Rechte |
|---|---|---|
| 0 | Gast | Nur Whitelist-Aktionen (Licht, Musik) |
| 1 | Mitbewohner | Alles außer Sicherheit |
| 2 | Owner | Voller Zugriff inkl. Alarm/Schlösser |

---

## 54. Self-Optimization

### Technisch zu prüfen
- Jarvis schlägt Konfigurationsänderungen vor
- Änderungen nur nach User-Bestätigung
- Config Versioning (Backup vor jeder Änderung)

---

## 55. Config-Selbstmodifikation

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 55.1 | "Füge einen Easter Egg hinzu: Wenn ich 'Star Wars' sage, antworte 'Möge die Macht mit dir sein'" | edit_config config_file='easter_eggs' action='add' |
| 55.2 | "Ändere die Raumtemperatur im Büro auf 22°C" | edit_config config_file='room_profiles' action='update' |
| 55.3 | "Entferne die Meinung zu hoher Temperatur" | edit_config config_file='opinion_rules' action='remove' |

### Editierbare Configs (Whitelist)
- `easter_eggs.yaml`
- `opinion_rules.yaml`
- `room_profiles.yaml`

---

## 56. Entity-Status abfragen

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 56.1 | "Was zeigt der Temperatursensor im Büro?" | get_entity_state entity_id='sensor.temperatur_buero' |
| 56.2 | "Status von weather.forecast_home" | get_entity_state → Wetterdaten |
| 56.3 | "Ist die Steckdose in der Küche an?" | get_entity_state oder get_switches |

---

## 57. Fähigkeiten-Liste

| # | Chat-Eingabe | Erwartetes Ergebnis |
|---|---|---|
| 57.1 | "Was kannst du?" | list_capabilities → vollständige Feature-Liste |
| 57.2 | "Was kannst du alles?" | list_capabilities |
| 57.3 | "Hilfe" | list_capabilities |

---

## 58. Dashboard & Authentifizierung

| # | Feature | Wie testen | Erwartetes Ergebnis |
|---|---|---|---|
| 58.1 | Setup-Status | `GET /api/ui/setup-status` | `{setup_complete: true/false}` |
| 58.2 | Erstmaliges Setup | `POST /api/ui/setup {"pin": "1234", "pin_confirm": "1234"}` | PIN + Recovery-Key |
| 58.3 | Login | `POST /api/ui/auth {"pin": "1234"}` | Token zurückgegeben |
| 58.4 | PIN zurücksetzen | `POST /api/ui/reset-pin {"recovery_key": "...", "new_pin": "...", "new_pin_confirm": "..."}` | Neuer PIN + neuer Recovery-Key |
| 58.5 | API Key anzeigen | `GET /api/ui/api-key?token=...` | Aktueller Key |
| 58.6 | API Key regenerieren | `POST /api/ui/api-key/regenerate?token=...` | Neuer Key |
| 58.7 | Recovery Key regenerieren | `POST /api/ui/recovery-key/regenerate?token=...` | Neuer Recovery Key |
| 58.8 | API Key Enforcement | `POST /api/ui/api-key/enforcement {"enabled": true}?token=...` | Enforcement aktiviert/deaktiviert |
| 58.9 | Settings lesen | `GET /api/ui/settings?token=...` | Alle Settings als JSON |
| 58.10 | Settings ändern | `PUT /api/ui/settings?token=...` | Settings aktualisiert |

### Sicherheit prüfen
- PIN mindestens 4 Zeichen
- PBKDF2-HMAC-SHA256 + Salt für PIN-Hash
- Token läuft nach 4 Stunden ab
- Audit-Log für Login-Versuche
- Rate-Limiting aktiv

---

## 59. API-Endpoints (technisch)

### Ohne Authentifizierung
| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/api/assistant/health` | GET | Health Check aller Komponenten |

### Mit API-Key (X-API-Key Header)
| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/api/assistant/chat` | POST | Hauptendpoint: Text an Jarvis |
| `/api/assistant/context` | GET | Debug: Aktueller Kontext |
| `/api/assistant/memory/search?q=` | GET | Episodisches Gedächtnis durchsuchen |
| `/api/assistant/memory/facts` | GET | Alle Fakten (Semantic Memory) |
| `/api/assistant/memory/facts/search?q=` | GET | Fakten-Suche (Vektor) |
| `/api/assistant/memory/facts/person/{name}` | GET | Fakten einer Person |
| `/api/assistant/memory/facts/category/{cat}` | GET | Fakten nach Kategorie |
| `/api/assistant/memory/facts/{id}` | DELETE | Fakt löschen |
| `/api/assistant/memory/stats` | GET | Gedächtnis-Statistiken |
| `/api/assistant/mood` | GET | Aktuelle Stimmung |
| `/api/assistant/status` | GET | Status-Report |
| `/api/assistant/activity` | GET | Aktivitätserkennung |
| `/api/assistant/activity/delivery` | GET | Zustellentscheidung |
| `/api/assistant/summaries` | GET | Tages-Zusammenfassungen |
| `/api/assistant/summaries/search?q=` | GET | Zusammenfassungen durchsuchen |
| `/api/assistant/summaries/generate/{date}` | POST | Zusammenfassung generieren |
| `/api/assistant/planner/last` | GET | Letzter Aktionsplan |
| `/api/assistant/settings` | GET/PUT | Einstellungen lesen/ändern |
| `/api/assistant/feedback` | PUT | Feedback geben |
| `/api/assistant/feedback/stats` | GET | Feedback-Statistiken |
| `/api/assistant/feedback/scores` | GET | Alle Feedback-Scores |
| `/api/assistant/tts/status` | GET | TTS-Status |
| `/api/assistant/tts/whisper` | POST | Flüstermodus |
| `/api/assistant/voice` | POST | TTS-Only (kein Chat) |
| `/api/assistant/speaker/profiles` | GET | Stimm-Profile |
| `/api/assistant/speaker/enroll` | POST | Stimm-Profil anlegen |
| `/api/assistant/speaker/profiles/{id}` | DELETE | Stimm-Profil löschen |
| `/api/assistant/speaker/history` | GET | Identifikations-History |
| `/api/assistant/diagnostics` | GET | System-Diagnostik |
| `/api/assistant/diagnostics/status` | GET | System-Status |
| `/api/assistant/maintenance` | GET | Wartungsaufgaben |
| `/api/assistant/maintenance/complete` | POST | Wartung erledigt |
| `/api/assistant/ambient-audio` | GET | Ambient Audio Status |
| `/api/assistant/ambient-audio/events` | GET | Audio-Events |
| `/api/assistant/ambient-audio/event` | POST | Audio-Webhook |
| `/api/assistant/conflicts` | GET | Konflikt-Info |
| `/api/assistant/conflicts/history` | GET | Konflikt-History |
| `/api/assistant/cooking/status` | GET | Koch-Session Status |
| `/api/assistant/cooking/stop` | POST | Koch-Session beenden |
| `/api/assistant/chat/upload` | POST | Datei hochladen |
| `/api/assistant/chat/files/{name}` | GET | Datei abrufen |
| `/api/assistant/trust` | GET | Trust-Level Info |
| `/api/assistant/trust/{person}` | GET | Trust einer Person |
| `/api/assistant/proactive/trigger` | POST | Proaktiven Event triggern |
| `/api/assistant/ws` | WebSocket | Echtzeit-Events |

---

## 60. WebSocket-Events

### Server → Client
| Event | Beschreibung |
|---|---|
| `assistant.speaking` | Jarvis spricht (Text + TTS-Metadaten) |
| `assistant.thinking` | Jarvis denkt nach |
| `assistant.action` | Jarvis führt Aktion aus |
| `assistant.listening` | Jarvis hört zu |
| `assistant.proactive` | Proaktive Meldung |
| `assistant.sound` | Sound-Event |
| `assistant.audio` | TTS-Audio-Daten |
| `ping` | Keep-Alive |
| `system.shutdown` | System wird heruntergefahren |
| `stream_start` | Streaming beginnt |
| `stream_token` | Einzelnes Token im Stream |
| `stream_end` | Streaming beendet |

### Client → Server
| Event | Beschreibung |
|---|---|
| `assistant.text` | Text-Eingabe (+ person, room, stream, device_id) |
| `assistant.feedback` | Feedback auf Meldung |
| `assistant.interrupt` | Unterbrechung |
| `pong` | Keep-Alive Antwort |

---

## 61. Boot-Sequenz

### Prüfen nach Neustart
- Jarvis kündigt sich an ("Alle Systeme online, Sir.")
- Raumtemperatur wird angesagt
- Offene Fenster/Türen werden gemeldet
- Fehlende Komponenten werden berichtet
- Greeting-Sound wird abgespielt

### Settings prüfen (settings.yaml → boot_sequence)
- `enabled`: true/false
- `delay_seconds`: Verzögerung nach Start
- `messages`: Anpassbare Boot-Nachrichten

---

## 62. Fehlerbehandlung & Edge Cases

| # | Test | Erwartetes Ergebnis |
|---|---|---|
| 62.1 | Leere Nachricht senden | HTTP 400 "Kein Text angegeben" |
| 62.2 | Timeout (>60s) | "Systeme überlastet. Nochmal, bitte." |
| 62.3 | Ungültiger API Key | HTTP 403 "Ungültiger oder fehlender API Key" |
| 62.4 | Rate-Limit überschritten | HTTP 429 "Zu viele Anfragen" |
| 62.5 | WebSocket Rate-Limit | Fehlermeldung nach >30 Nachrichten/10s |
| 62.6 | Unbekannter Raum | Jarvis fragt nach dem Raum |
| 62.7 | Mehrdeutiger Befehl | Jarvis fragt zur Klärung |
| 62.8 | Gast versucht Alarm zu deaktivieren | Wird blockiert (Trust-Level 0) |
| 62.9 | Englischer Raumname | Automatische Übersetzung (living room → Wohnzimmer) |
| 62.10 | Ollama nicht erreichbar | Circuit Breaker greift, Fehlermeldung |
| 62.11 | Home Assistant nicht erreichbar | Circuit Breaker greift, degraded Mode |
| 62.12 | Reasoning im Stream | Wird erkannt und unterdrückt (nicht an Client gesendet) |
| 62.13 | "Ja" nach fehlgeschlagener Aktion | Retry der letzten Anfrage |

---

## Zusammenfassung: Gesamt-Funktionsumfang

| Kategorie | Anzahl Tools | Testbare Chat-Befehle |
|---|---|---|
| Licht | 2 (set_light, get_lights) | ~12 |
| Klima | 2 (set_climate, get_climate) | ~7 |
| Rollläden | 2 (set_cover, get_covers) | ~11 |
| Steckdosen | 2 (set_switch, get_switches) | ~4 |
| Szenen | 1 (activate_scene) | ~3 |
| Medien | 4 (play_media, get_media, transfer, recommend) | ~16 |
| Sicherheit | 2 (arm_security, lock_door) | ~5 |
| Kalender | 4 (get/create/delete/reschedule) | ~7 |
| Timer/Wecker | 7 (set_timer, cancel, status, reminder, alarm, cancel_alarm, get_alarms) | ~11 |
| Durchsagen | 3 (broadcast, intercom, message_to_person) | ~4 |
| Kamera | 2 (camera_view, doorbell) | ~5 |
| Besucher | 1 (manage_visitor) | ~8 |
| Einkauf/Inventar | 2 (shopping_list, inventory) | ~10 |
| Kochen | Koch-Session via Chat | ~6 |
| Saugroboter | 2 (set_vacuum, get_vacuum) | ~6 |
| Wetter | 1 (get_weather) | ~5 |
| Energie | 1 (get_energy_report) | ~4 |
| Web-Suche | 1 (web_search) | ~3 |
| Status/Briefing | 2 (house_status, full_report) | ~7 |
| Automationen | 4 (create, confirm, list, delete) | ~4 |
| Protokolle | 1 (manage_protocol) | ~5 |
| Conditionals | 2 (create, list) | ~4 |
| Config-Edit | 1 (edit_config) | ~3 |
| Sonstiges | 8 (entity_state, wellness, security_score, climate, device_health, patterns, intents, capabilities) | ~10 |
| Easter Eggs | — | 23 |
| **Gesamt** | **~55 Tools** | **~200+ Chat-Befehle** |
| **+ API-Endpoints** | **~50 Endpoints** | — |
| **+ Proaktive Features** | **~15 Typen** | — |
| **+ WebSocket-Events** | **~12 Event-Typen** | — |
