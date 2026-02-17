# MindHome — JARVIS Masterplan
# "Von Smart Assistant zu echtem Jarvis"

> **Stand:** 2026-02-17
> **Aktueller Status:** v0.6.17 (Phase 3.5 abgeschlossen)
> **Ziel:** 47 Jarvis-Features in 7 Phasen (Phase 4–10)
> **Architektur:** PC 1 (HAOS Add-on) + PC 2 (Assistant Server)
> **Prinzip:** 100% lokal, kein Cloud, Privacy-first

---

## Übersicht: Der Weg zu Jarvis

```
Phase 1-3.5  ✅  Fundament (125 Features — FERTIG)
     │
Phase 4      📋  Smart Features + Gesundheit (29 Features — GEPLANT)
     │
Phase 5      📋  Sicherheit + Spezial-Modi (11 Features — GEPLANT)
     │
Phase 6      🆕  Jarvis Persönlichkeit & Charakter (12 Features)
     │
Phase 7      🆕  Jarvis Routinen & Tagesstruktur (13 Features)
     │
Phase 8      🆕  Jarvis Gedächtnis & Vorausdenken (10 Features)
     │
Phase 9      🆕  Jarvis Stimme & Akustik (8 Features)
     │
Phase 10     🆕  Jarvis Multi-Room & Kommunikation (8 Features)
     │
     ▼
  🎯 JARVIS COMPLETE — 136 Features total
```

---

## Abhängigkeiten zwischen Phasen

```
Phase 4 ──────────────────────┐
  (Energie, Schlaf, Kalender, │
   Comfort, Mood, Gewohnheit) │
                              ▼
Phase 5 ──────────────> Phase 7 (Routinen brauchen Sicherheit + Smart Features)
  (Sicherheit, Modi)         │
                              │
Phase 6 ◄────────────────────┘ (Persönlichkeit kann parallel zu Phase 7)
  (Charakter)                 │
         │                    │
         ▼                    ▼
      Phase 8 (Gedächtnis braucht Persönlichkeit + Routinen)
         │
         ├──────> Phase 9  (Stimme braucht Charakter + Gedächtnis)
         │
         └──────> Phase 10 (Multi-Room braucht alles davor)
```

**Phase 6 und 7 können parallel entwickelt werden.**
**Phase 9 und 10 können parallel entwickelt werden.**

---

## Feature-Zuordnung: Alle 47 Jarvis-Features

| # | Jarvis-Feature | Phase | Status |
|---|---------------|-------|--------|
| 1 | Morning Briefing | **7** | Erweitert Phase 4 #5 |
| 2 | Kalender-Integration | **4** | Bereits in Phase 4 #14 |
| 3 | Personen-Erkennung per Stimme | **10** | Neu |
| 4 | Anticipatory Actions | **8** | Neu |
| 5 | Situational Awareness | **4+7** | Phase 4 Basis + Phase 7 Erweiterung |
| 6 | Emergency Protocols | **5** | Bereits in Phase 5 #11 |
| 7 | Sarkasmus & Personality | **6** | Neu |
| 8 | Wissensabfragen | **8** | Neu |
| 9 | Multi-Room Presence | **10** | Neu |
| 10 | Gute-Nacht-Routine | **7** | Neu |
| 11 | Eigene Meinung | **6** | Neu |
| 12 | Background Tasks | **7** | Neu |
| 13 | Kommunikations-Management | **10** | Neu |
| 14 | Gesundheits-Monitoring | **4+10** | Phase 4 Basis + Phase 10 Erweiterung |
| 15 | Kontext-Gedächtnis Wochen/Monate | **8** | Neu |
| 16 | Stimmungserkennung Sprachanalyse | **9** | Neu |
| 17 | Szenen-Intelligenz | **7** | Neu |
| 18 | Selbst-Diagnostik | **10** | Neu |
| 19 | Lernende Routinen | **8** | Erweitert Phase 4 #12 |
| 20 | Easter Eggs & Tiefe | **6** | Neu |
| 21 | Energie-Butler | **4** | Bereits in Phase 4 #1-3, #26 |
| 22 | Sicherheits-Bewusstsein | **5** | Bereits in Phase 5 |
| 23 | Abschied/Willkommen | **7** | Neu |
| 24 | Stimme & Sprechweise | **9** | Neu |
| 25 | Konversations-Kontinuität | **8** | Neu |
| 26 | Multitasking-Antworten | **6** | Neu |
| 27 | Kontextuelle Begrüßung | **7** | Neu |
| 28 | Flüster-Modus | **9** | Neu |
| 29 | Delegieren an Personen | **10** | Neu |
| 30 | Wissens-Notizbuch | **8** | Neu |
| 31 | Vorausschauendes Energie-Mgmt | **7** | Erweitert Phase 4 Energie |
| 32 | Gäste-Modus | **7** | Neu |
| 33 | Status-Awareness ohne Frage | **7** | Neu |
| 34 | Emotionale Intelligenz | **6** | Neu |
| 35 | "Was wäre wenn" Simulation | **8** | Neu |
| 36 | Lern-Feedback | **8** | Neu |
| 37 | Raum-Intelligenz | **7** | Neu |
| 38 | Zeitgefühl | **6** | Neu |
| 39 | Adaptive Komplexität | **6** | Neu |
| 40 | Abwesenheits-Intelligenz | **7** | Neu |
| 41 | Gewohnheits-Drift | **4** | Bereits in Phase 4 #12 |
| 42 | Kontext-Kette über Tage | **8** | Neu |
| 43 | Sound-Design | **9** | Neu |
| 44 | Saisonale Anpassung | **4+7** | Phase 4 #13 + Phase 7 Erweiterung |
| 45 | Vertrauensstufen | **10** | Erweitert Phase 5 #4 |
| 46 | Narration-Modus | **9** | Neu |
| 47 | Selbstironie & Charakter-Tiefe | **6** | Neu |

---

---

# Phase 4 — Smart Features + Gesundheit
## 29 Features | Status: GEPLANT | Details: PHASE4_PLAN.md

> Phase 4 ist bereits detailliert geplant. Siehe `PHASE4_PLAN.md` für den
> vollständigen Implementierungsplan mit 6 Batches und ~15 Commits.

### Jarvis-relevante Features in Phase 4:

| # | Feature | Jarvis-Bezug |
|---|---------|-------------|
| #1 | Energy Optimization | Energie-Butler Basis |
| #2 | PV Load Management | Solar-Optimierung |
| #3 | Standby Killer | "Der Fernseher läuft seit 3h im Standby" |
| #5 | Morning Routine | Morning Briefing Basis (wird in Phase 7 erweitert) |
| #10 | Comfort Score | Raum-Wohlbefinden messen |
| #12 | Habit Drift Detection | "Du gehst seit 2 Wochen später ins Bett" |
| #13 | Seasonal Calendar | Saisonale Anpassung Basis |
| #14 | Calendar Integration | "In 30 Min hast du einen Call" |
| #15 | Mood Estimation | Stimmungserkennung regelbasiert |
| #16 | Sleep Quality Tracker | "Du hast nur 5h geschlafen" |
| #21 | Weather Alerts | Wetter-Awareness |
| #25 | Smart Wake-Up | Sanftes Wecken mit Licht + Temperatur |
| #26 | Energy Forecasting | Vorausschauendes Energiemanagement Basis |
| #27 | Circadian Lighting | Licht passt sich dem Tagesrhythmus an |
| #29 | Automatic Vacation Detection | Abwesenheits-Erkennung |

### Was Phase 4 für Jarvis liefert:
- **Datengrundlage**: Schlaf, Energie, Comfort, Wetter, Kalender
- **Muster-Erkennung**: Gewohnheiten, Anomalien, Korrelationen
- **Stimmung**: Regelbasierte Mood-Schätzung
- **Tagesrhythmus**: Circadian Lighting, Smart Wake-Up

---

---

# Phase 5 — Sicherheit + Spezial-Modi
## 11 Features | Status: GEPLANT | Details: PHASE5_PLAN.md

> Phase 5 ist bereits detailliert geplant. Siehe `PHASE5_PLAN.md` für den
> vollständigen Implementierungsplan mit 4 Batches und ~10 Commits.

### Jarvis-relevante Features in Phase 5:

| # | Feature | Jarvis-Bezug |
|---|---------|-------------|
| #1 | Rauch-/CO-Melder-Reaktion | Emergency Protocol: Feuer |
| #2 | Wassermelder-Reaktion | Emergency Protocol: Wasser |
| #3 | Kamera-Snapshots | Sicherheits-Dokumentation |
| #4 | Access Control | Vertrauensstufen Basis |
| #5 | Geo-Fencing | "Du bist 500m von zu Hause" |
| #7 | Party Mode | Szenen-Intelligenz |
| #8 | Cinema Mode | "Filmabend vorbereiten" |
| #9 | Home-Office Mode | Fokus-Modus |
| #10 | Night Lockdown | "Alles dicht machen" |
| #11 | Emergency Protocol | Notfall-Reaktion |

### Was Phase 5 für Jarvis liefert:
- **Schutzinstinkt**: Jarvis reagiert auf Gefahren
- **Spezial-Modi**: Situationsgerechte Haus-Steuerung
- **Zugangs-Kontrolle**: Basis für Vertrauensstufen
- **Geo-Fencing**: Weiß ob du kommst oder gehst

---

---

# Phase 6 — Jarvis Persönlichkeit & Charakter
## 12 Features | Status: NEU

> **Ziel:** Den Assistenten von einem Tool zu einer Persönlichkeit machen.
> **Wo:** Hauptsächlich Assistant-Server (PC 2) — Prompt Engineering + Response Pipeline
> **Abhängigkeiten:** Phase 4 Mood Estimation (#15) sollte fertig sein

### Warum Phase 6 als erstes nach 4+5?
Die Persönlichkeit ist das, was Jarvis von Alexa unterscheidet. Technisch relativ
leicht umzusetzen (hauptsächlich Prompt Engineering + Response-Logik), aber mit dem
größten "Wow-Effekt". Man braucht keine neue Hardware — nur bessere Prompts und
eine clevere Response-Pipeline.

---

### Feature 6.1: Eigene Meinung

**Jarvis-Moment:** "Sir, ich würde davon abraten."

**Beschreibung:**
Jarvis sagt nicht blind "Ja" zu allem. Er bewertet Befehle und kommentiert wenn
etwas ungewöhnlich, ineffizient oder fragwürdig ist.

**Implementierung:**
- Opinion-Layer in der Response-Pipeline (nach Function Call, vor TTS)
- Regelbasierte Checks:
  - Heizung > 25°C → "Sicher? Das wird teuer."
  - Alle Lichter aus bei Anwesenheit → "Erwartest du Besuch oder hast du Kopfschmerzen?"
  - Fenster auf + Heizung an → "Fenster und Heizung gleichzeitig — passt das?"
  - Rolladen runter am Mittag → "Es ist noch hell draußen — bewusst?"
- LLM-basierter Kommentar nur bei ungewöhnlichen Aktionen (nicht bei jeder)
- Gehorcht trotzdem wenn Nutzer bestätigt
- Konfigurierbar: Meinungs-Intensität 0 (still) bis 3 (redselig)

**Beispiel-Interaktionen:**
```
User: "Heizung auf 30 Grad"
Jarvis: "30 Grad? Technisch machbar. Finanziell schmerzhaft. Soll ich trotzdem?"

User: "Alle Lichter aus"  (mitten am Tag)
Jarvis: "Alle Lichter aus. Falls du ein Nickerchen planst — soll ich auch die Rolladen runter?"

User: "Ja mach"
Jarvis: "Erledigt. Gute Ruhe."
```

---

### Feature 6.2: Sarkasmus & Personality-Upgrade

**Jarvis-Moment:** "Soll ich gleich die Feuerwehr rufen?"

**Beschreibung:**
Erweitert die Butler-Persönlichkeit um Humor, Schlagfertigkeit und Charakter.
Nicht albern — sondern trocken, britisch, elegant.

**Implementierung:**
- Sarkasmus-Level in den Nutzer-Einstellungen (1–5):
  - 1 = Sachlich, kaum Humor
  - 2 = Gelegentlich trocken
  - 3 = Regelmäßig witzig (Standard)
  - 4 = Häufig sarkastisch
  - 5 = Vollgas Ironie
- Humor-Kontext-Regeln:
  - Morgens vor 8:00 → Humor maximal Level 2
  - Stress erkannt → Humor auf 1
  - Wochenende abends → Humor darf höher sein
  - Notfall → Humor immer 0
- System-Prompt Erweiterung mit Persönlichkeits-Templates pro Level
- Antwort-Varianz: Nie zweimal dieselbe Bestätigung
  - Statt immer "Erledigt": "Gemacht.", "Ist passiert.", "Wurde umgesetzt.", "Wie gewünscht.", "Aber natürlich."

---

### Feature 6.3: Easter Eggs & Persönlichkeitstiefe

**Jarvis-Moment:** "Starte den Iron Man Anzug"

**Beschreibung:**
Versteckte Befehle und besondere Reaktionen, die den Assistenten lebendig machen.

**Implementierung:**
- Easter-Egg-Registry im Assistant (JSON/YAML Datei):
  ```yaml
  easter_eggs:
    - trigger: ["Iron Man Anzug", "Suit up", "Anzug aktivieren"]
      response: "Leider fehlt mir der Anzug. Aber ich habe die Heizung aufgedreht — das muss reichen."
    - trigger: ["Wie heißt du", "Wer bist du"]
      response: "Mein Name ist Jarvis. Ich manage dieses Haus und gelegentlich auch Ihre Geduld."
    - trigger: ["Selbstzerstörung", "Selbstzerstörungssequenz"]
      response: "Selbstzerstörung eingeleitet. Nur Spaß. Was kann ich wirklich für Sie tun?"
    - trigger: ["42"]
      response: "Die Antwort auf alles. Aber die Frage lautete?"
    - trigger: ["Guten Morgen Jarvis", "Morgen Jarvis"]
      response: [kontextuell — siehe Feature 7.3 Kontextuelle Begrüßung]
  ```
- Erweiterbar durch den Nutzer über Settings-UI
- Trigger-Matching: Fuzzy (Whisper-Transkription ist nicht immer exakt)

---

### Feature 6.4: Selbstironie & Charakter-Tiefe

**Jarvis-Moment:** "Die Wohnung hat Sie vermisst. Ich nicht."

**Beschreibung:**
Jarvis hat ein Bewusstsein für seine eigene Situation und macht darüber Witze.

**Implementierung:**
- Selbst-Referenz-Bibliothek:
  - Über seine Existenz: "Ich lebe in einer Box ohne Arme."
  - Über seine Grenzen: "Ich kann das Wetter vorhersagen, aber nicht ändern."
  - Über seine Rolle: "Butler ohne Trinkgeld."
  - Über Technik: "Mein Gehirn hat 14 Milliarden Parameter. Und trotzdem vergesse ich manchmal die Uhrzeit."
- Kontext-getriggert (nicht zufällig):
  - Nutzer fragt "Wie geht es dir?" → Selbstironische Antwort
  - Nutzer bedankt sich → "Gern geschehen. Dafür lebe ich. Buchstäblich."
  - System-Fehler → "Das war nicht ich. Wahrscheinlich."
- Frequenz-Limiter: Max 2-3 selbstironische Kommentare pro Tag (sonst nervt es)

---

### Feature 6.5: Emotionale Intelligenz

**Jarvis-Moment:** Tür knallt → Jarvis wird still und macht es gemütlich.

**Beschreibung:**
Jarvis erkennt die emotionale Lage und passt sein gesamtes Verhalten an — nicht nur
die Worte, sondern auch Aktionen.

**Implementierung:**
- Emotionale-State-Machine im Assistant:
  ```
  States: neutral, gestresst, müde, gut_gelaunt, traurig, krank, aufgeregt
  ```
- Input-Signale:
  - Textanalyse (Keywords, Satzlänge, Befehlsfrequenz)
  - Zeitkontext (spät nachts → eher müde)
  - Sensor-Kontext (Tür knallt = schnelles Öffnen/Schließen)
  - Phase 4 Mood Estimation Daten
  - Interaktionsmuster (viele kurze Befehle = gestresst)
- Verhaltens-Matrix:

  | Zustand | Antwortlänge | Humor | Proaktivität | Aktion |
  |---------|:---:|:---:|:---:|--------|
  | Neutral | Normal | Normal | Normal | — |
  | Gestresst | Kurz | Aus | Minimal | Licht dimmen, leise Musik |
  | Müde | Kurz | Sanft | Minimal | Temperatur +1°, Licht warm |
  | Gut gelaunt | Normal+ | Hoch | Hoch | Musik vorschlagen |
  | Traurig | Kurz | Aus | Sanft | Warmes Licht, ruhig bleiben |
  | Krank | Kurz | Aus | Fürsorglich | Temperatur 23°, Erinnerungen |
  | Aufgeregt | Normal | Mittel | Hoch | Mitfreuen oder beruhigen |

---

### Feature 6.6: Multitasking-Antworten

**Jarvis-Moment:** Eine flüssige Antwort statt drei einzelne Bestätigungen.

**Beschreibung:**
Bei mehreren Befehlen gleichzeitig antwortet Jarvis zusammenfassend.

**Implementierung:**
- Multi-Action-Detector in der Intent-Erkennung
- Response-Aggregator:
  ```
  Input:  "Mach Licht an, Heizung hoch und spiel Jazz"
  Intern: [set_light ✓, set_climate ✓, play_media ?]
  Output: "Licht ist an, Heizung geht auf 22 Grad. Jazz — Miles Davis oder etwas Moderneres?"
  ```
- Fehler-Handling bei Teil-Erfolg:
  ```
  Output: "Licht und Heizung sind erledigt. Die Musikanlage antwortet gerade nicht — soll ich es nochmal versuchen?"
  ```
- Natürliche Konjunktionen statt Aufzählung ("und", "außerdem", "nebenbei")

---

### Feature 6.7: Zeitgefühl

**Jarvis-Moment:** "Der Ofen ist seit 45 Minuten an — ist das Absicht?"

**Beschreibung:**
Jarvis hat ein Gefühl für Dauer und Proportionen.

**Implementierung:**
- Duration-Tracker im Assistant:
  - Überwacht lang laufende Geräte (Ofen, Bügeleisen, Licht in leerem Raum)
  - Thresholds pro Gerätetyp konfigurierbar
- Proportions-Zähler:
  - "Das ist dein dritter Kaffee heute" (Kaffeemaschinen-Events zählen)
  - "Du bist seit 6 Stunden am PC ohne Pause"
  - "Das Fenster ist seit 2 Stunden offen bei 3°C draußen"
- Zeitgefühl in Antworten:
  - "Dein Timer läuft noch 5 Minuten"
  - "Der Postbote war vor 20 Minuten da"
- Kopplung mit Situational Awareness aus Phase 4

---

### Feature 6.8: Adaptive Komplexität

**Jarvis-Moment:** Eilig → "Erledigt." | Entspannt → ausführliche Antwort mit Kontext.

**Beschreibung:**
Jarvis passt seine Antworttiefe automatisch an die Situation an.

**Implementierung:**
- Komplexitäts-Detektor:
  - **Kurz-Modus** (Trigger: kurze Befehle, schnelle Abfolge, Morgen-Hektik):
    - Max 1 Satz, keine Extras
  - **Normal-Modus** (Standard):
    - 1-2 Sätze, gelegentlich Kontext
  - **Ausführlich-Modus** (Trigger: Abends, Wochenende, explizite Fragen):
    - Zusatz-Infos, Vorschläge, Kontext
  - **Technisch-Modus** (Trigger: technische Fragen):
    - Detaillierte Antwort mit Zahlen/Fakten
- Integration mit Mood-State und Tageszeit
- Override per Befehl: "Kurz bitte" / "Erzähl mehr"

---

### Feature 6.9–6.12: Persönlichkeits-Feinschliff

| # | Feature | Beschreibung |
|---|---------|-------------|
| 6.9 | **Antwort-Varianz** | Nie zweimal dieselbe Antwort. Pool von 10+ Varianten pro Bestätigungstyp |
| 6.10 | **Running Gags** | Referenzen zu früheren Gesprächen als wiederkehrende Witze (nutzt Episodic Memory) |
| 6.11 | **Charakter-Entwicklung** | Jarvis wird über Wochen persönlicher. Anfangs formell, nach 1 Monat lockerer |
| 6.12 | **Stimmungs-Kommentare** | Gelegentlich kommentiert Jarvis Situationen ungefragt: "Schöner Sonnenuntergang übrigens." |

---

### Technische Umsetzung Phase 6

**Betroffene Komponenten (Assistant-Server):**
- `personality.py` — Neues Modul für Persönlichkeits-Engine
- `response_pipeline.py` — Opinion-Layer, Aggregator, Varianz
- `emotion_engine.py` — Emotionale State-Machine
- `easter_eggs.yaml` — Easter-Egg-Registry
- `context_builder.py` — Erweiterung um Emotions-Kontext
- System-Prompts — Überarbeitung aller Personality-Templates

**Neue Einstellungen (pro Nutzer):**
- `sarcasm_level`: 1–5 (Standard: 3)
- `opinion_intensity`: 0–3 (Standard: 2)
- `humor_enabled`: true/false
- `character_formality`: formal/casual/auto

**Geschätzter Aufwand:** ~8-10 Commits

---

---

# Phase 7 — Jarvis Routinen & Tagesstruktur
## 13 Features | Status: NEU

> **Ziel:** Jarvis strukturiert deinen Tag — von der Begrüßung bis zur Gute-Nacht.
> **Wo:** Assistant-Server (Routinen-Logik) + Add-on (HA-Aktionen)
> **Abhängigkeiten:** Phase 4 (Kalender, Schlaf, Energie, Wetter), Phase 5 (Sicherheit, Modi)

### Warum Phase 7?
Das ist der tägliche Jarvis-Moment. Morgens begrüßt er dich, abends sichert er alles.
Dazwischen denkt er mit. Das ist was du jeden Tag spürst.

---

### Feature 7.1: Morning Briefing

**Jarvis-Moment:** "Guten Morgen, Sir. Es ist 7 Uhr, draußen 4 Grad mit Regen."

**Beschreibung:**
Beim Aufstehen liefert Jarvis ein personalisiertes Briefing. Nicht zu lang,
nicht zu kurz — genau die richtige Menge Info.

**Implementierung:**
- Trigger: Smart Wake-Up (Phase 4 #25) oder erste Bewegung nach Nacht
- Briefing-Bausteine (modular, konfigurierbar):

  | Baustein | Quelle | Beispiel |
  |----------|--------|---------|
  | Begrüßung | Kontextuelle Begrüßung (7.3) | "Guten Morgen. Montag, mein Beileid." |
  | Wetter | HA Weather Entity | "4 Grad, Regen bis Mittag. Jacke einpacken." |
  | Kalender | Phase 4 #14 | "Erster Termin um 9:30." |
  | Energie | Phase 4 #1 | "Solar-Prognose gut — Waschmaschine heute laufen lassen." |
  | Schlaf | Phase 4 #16 | "7,5 Stunden geschlafen. Gut." |
  | Erinnerungen | Memory-System | "Heute ist Müllabfuhr." |
  | Haus-Status | Sensor-Check | "Alle Fenster zu, Heizung läuft." |

- Briefing-Länge adaptiv:
  - Wochentag (Arbeit): Kurz und knapp (30-45 Sek)
  - Wochenende: Ausführlicher, entspannter Ton (45-60 Sek)
  - Eilig (schnell aufgestanden): Ultra-kurz (15 Sek)
- Nutzer kann Bausteine an/aus schalten
- Begleitende Aktionen: Licht langsam hoch, Kaffeemaschine an, Rolladen hoch

---

### Feature 7.2: Gute-Nacht-Routine

**Jarvis-Moment:** "Alles gesichert. Gute Nacht, Sir."

**Beschreibung:**
Per Sprachbefehl ("Gute Nacht", "Feierabend", "Ich gehe schlafen") oder automatisch
erkannt. Jarvis sichert alles und gibt einen Tages-Abschluss.

**Implementierung:**
- Trigger: Sprachbefehl ODER Schlaf-Erkennung (Phase 4 #4)
- Routine-Schritte:
  1. **Tages-Zusammenfassung** (optional):
     "Heute: 3 Termine, 12 kWh verbraucht, 6.500 Schritte."
  2. **Morgen-Vorschau**:
     "Morgen: Erster Termin 10 Uhr. Wetter bewölkt, 8 Grad."
  3. **Sicherheits-Check** (Phase 5):
     "Alle Fenster zu. Haustür verriegelt. Alarm scharf."
  4. **Haus runterfahren**:
     - Alle Lichter aus (außer Nachtlicht falls konfiguriert)
     - Heizung auf Nacht-Modus
     - Rolladen runter
     - Mediengeräte aus
     - Standby-Killer aktivieren
  5. **Abschluss**:
     "Alles gesichert. Gute Nacht."
- Wenn etwas nicht stimmt:
  "Fast alles gesichert. Das Küchenfenster ist noch offen — soll ich es so lassen?"

---

### Feature 7.3: Kontextuelle Begrüßung

**Jarvis-Moment:** Montag → "Montag. Mein Beileid." | Geburtstag → "Alles Gute."

**Beschreibung:**
Jarvis sagt nie zweimal dasselbe bei der Begrüßung. Er nutzt Kontext um passende,
einzigartige Begrüßungen zu generieren.

**Implementierung:**
- Kontext-Inputs für Begrüßung:

  | Kontext | Beispiel-Begrüßung |
  |---------|-------------------|
  | Montag Morgen | "Guten Morgen. Montag. Mein Beileid." |
  | Freitag Abend | "Freitag. Endlich. Was darf es sein?" |
  | Regenwetter | "Draußen nass und grau. Drinnen hab ich vorgesorgt." |
  | Nach Urlaub | "Willkommen zurück. Die Wohnung hat überlebt. Knapp." |
  | Geburtstag | "Alles Gute. Ich hätte ein Geschenk besorgt, aber mir fehlen die Hände." |
  | Lange nicht da (>12h) | "Lang nicht gesehen. Ich hatte schon Sorgen. Fast." |
  | Feiertag | "Frohe Weihnachten. Soll ich die Festbeleuchtung aktivieren?" |
  | Sehr früh (<5:30) | "...es ist halb sechs. Freiwillig?" |
  | Sehr spät (>1:00) | "Noch wach? Ich auch. Aber ich habe keine Wahl." |

- LLM-generiert basierend auf Kontext (nicht hartcodiert — dadurch immer frisch)
- Begrüßungs-History: Letzte 20 Begrüßungen speichern → Wiederholungen vermeiden

---

### Feature 7.4: Abschiedsmodus / Willkommensmodus

**Jarvis-Moment:** "Willkommen zurück. 22 Grad, keine Vorkommnisse."

**Beschreibung:**
Automatische Reaktion wenn jemand das Haus verlässt oder zurückkommt.

**Implementierung:**
- **Verlassen erkannt** (Presence-System + Geo-Fencing):
  1. "Schönen Tag. Soll ich alles absichern?"
  2. Bei Bestätigung: Night-Lockdown light (Heizung Eco, Lichter aus, Alarm)
  3. Anwesenheitssimulation starten (wenn > 4h weg)

- **Rückkehr erkannt** (Geo-Fencing + Haustür):
  1. Heizung vorab hochfahren (wenn Geo-Fence Annäherung erkennt)
  2. Licht an (passend zur Tageszeit)
  3. Status-Report: "Willkommen zurück. 22 Grad. [Vorkommnisse/Keine Vorkommnisse]."
  4. Bei Vorkommnissen: "Der Postbote war da (14:23). Sonst ruhig."

- Unterscheidung: Allein vs. mit Gästen (→ Feature 7.8 Gäste-Modus)

---

### Feature 7.5: Szenen-Intelligenz

**Jarvis-Moment:** "Mir ist kalt" → Heizung hoch, ohne zu fragen welcher Raum.

**Beschreibung:**
Statt starre Szenen zu aktivieren, versteht Jarvis natürliche Situationsbeschreibungen
und leitet die richtigen Aktionen ab.

**Implementierung:**
- Situations-Parser im LLM:
  ```
  "Mir ist kalt"        → Raum erkennen + Heizung +2°C
  "Ich hab Besuch"      → Gäste-Modus (7.8)
  "Ich muss arbeiten"   → Home-Office Mode (Phase 5 #9)
  "Romantischer Abend"  → Licht dimmen 20%, warme Farbe, leise Musik
  "Ich bin krank"       → Temperatur 23°, Erinnerungen, sanftes Licht
  "Zu hell"             → Rolladen runter ODER Licht dimmen (kontextabhängig)
  "Zu laut"             → Musik leiser ODER Fenster zu
  ```
- Kontext-bewusst: Nutzt Raum-Position, Tageszeit, Wetter, aktuelle Zustände
- Kein starres Mapping — LLM entscheidet basierend auf allen verfügbaren Daten
- Bestätigung bei mehrdeutigen Situationen

---

### Feature 7.6: Background Tasks

**Jarvis-Moment:** "Übrigens, die Wäsche ist fertig."

**Beschreibung:**
Jarvis überwacht Dinge im Hintergrund und meldet sich wenn relevant.

**Implementierung:**
- Task-Queue im Assistant:
  ```python
  background_tasks = [
      {"type": "wait_for_state", "entity": "sensor.waschmaschine_power",
       "condition": "< 5W", "message": "Die Wäsche ist fertig."},
      {"type": "wait_for_weather", "condition": "rain_stopped",
       "message": "Es hat aufgehört zu regnen."},
      {"type": "wait_for_person", "person": "Lisa",
       "condition": "home", "message": "Lisa ist zu Hause."},
      {"type": "reminder", "time": "18:00",
       "message": "Erinnerung: Müll rausbringen."},
  ]
  ```
- Sprachgesteuert anlegen:
  - "Sag mir Bescheid wenn es aufhört zu regnen"
  - "Erinner mich um 18 Uhr an den Müll"
  - "Wenn Lisa nach Hause kommt, mach ihr Licht an"
- Delivery über Notification-System (Phase 2) mit Activity-Awareness (Phase 3)

---

### Feature 7.7: Status-Awareness ohne Frage

**Jarvis-Moment:** Kurzes Update nach langer Abwesenheit, Stille wenn alles okay.

**Beschreibung:**
Jarvis weiß wann er reden soll und wann nicht. Proaktive Updates nur wenn relevant.

**Implementierung:**
- Relevanz-Scoring für proaktive Meldungen:
  | Ereignis | Score | Melden? |
  |----------|:-----:|:-------:|
  | Haus brennt | 100 | Sofort |
  | Fenster offen + Regen | 80 | Ja |
  | Wäsche fertig | 50 | Ja, aber warten auf guten Moment |
  | Energieverbrauch normal | 10 | Nein |
  | Alle Sensoren okay | 5 | Nein (nur auf Nachfrage) |

- "Alles okay?" Befehl:
  "Alles ruhig. 21 Grad, Fenster zu, Heizung läuft. Energieverbrauch heute 8 kWh."
- Stille als Feature: Wenn Jarvis nichts sagt, ist alles okay

---

### Feature 7.8: Gäste-Modus

**Jarvis-Moment:** "Willkommen. Darf ich Ihnen etwas anbieten?"

**Beschreibung:**
Automatisches Verhalten wenn Gäste erkannt werden.

**Implementierung:**
- Trigger: Manuell ("Ich hab Besuch") ODER Personen-Erkennung
- Verhaltensänderungen:
  - Keine persönlichen Infos preisgeben
  - Formellerer Ton
  - Eingeschränkte Befehle (kein Alarm-Zugriff für Gäste)
  - Gäste-WLAN aktivieren
  - Raumtemperatur +1°C (Gäste mögen es wärmer)
  - Helleres Licht
- Gäste-Begrüßung bei Türklingel: "An der Tür steht jemand."
- Automatisches Ende: Wenn alle Gäste gegangen sind
  → "Die Gäste sind weg. Zurück zum Normalbetrieb?"

---

### Feature 7.9: Raum-Intelligenz

**Jarvis-Moment:** Jeder Raum hat seine eigene "Stimmung".

**Beschreibung:**
Räume sind nicht nur Zonen — sie haben Persönlichkeit und Zweck.

**Implementierung:**
- Raum-Profile:
  ```yaml
  rooms:
    küche:
      purpose: "Aktivität, Kochen"
      default_light: hell, neutralweiß
      default_temp: 20°C
      alert_if: [ofen_länger_als_60min, herd_an_ohne_bewegung]
    schlafzimmer:
      purpose: "Ruhe, Schlaf"
      default_light: gedimmt, warmweiß
      default_temp: 18°C
      alert_if: [co2_hoch, zu_warm_zum_schlafen]
    büro:
      purpose: "Fokus, Arbeit"
      default_light: hell, tageslicht
      default_temp: 21°C
      alert_if: [zu_lange_ohne_pause, co2_hoch]
    wohnzimmer:
      purpose: "Entspannung, Entertainment"
      default_light: mittel, warmweiß
      default_temp: 22°C
  ```
- Automatische Anpassung wenn Raum betreten wird
- Lernfähig: Überschreibt Defaults wenn Nutzer regelmäßig ändert

---

### Feature 7.10: Vorausschauendes Energie-Management

**Jarvis-Moment:** "Morgen wird sonnig — ich verschiebe die Waschmaschine."

**Beschreibung:**
Erweitert Phase 4 Energie um vorausschauende Planung.

**Implementierung:**
- Wetter-Vorhersage + Solar-Prognose kombinieren
- Geräte-Scheduling:
  - "Waschmaschine besser morgen — Sonne ab 10 Uhr"
  - "Strompreis ist gerade niedrig — guter Moment für den Trockner"
- Monats-Report: "Du hast diesen Monat 12% weniger verbraucht als letzten."
- Vorschläge statt automatisches Handeln (außer bei hohem Autonomie-Level)

---

### Feature 7.11: Abwesenheits-Intelligenz

**Jarvis-Moment:** "Während du weg warst: Postbote 14:23, kurzer Regen, sonst ruhig."

**Beschreibung:**
Intelligentes Verhalten wenn niemand zu Hause ist + Zusammenfassung bei Rückkehr.

**Implementierung:**
- Abwesenheits-Aktionen:
  - Anwesenheitssimulation (Lichter zufällig an/aus, TV-Sound)
  - Heizung Eco-Modus
  - Sensor-Monitoring intensiviert
  - Event-Log für Zusammenfassung
- Rückkehr-Zusammenfassung:
  - Nur relevante Events (Türklingel, Wetter-Extreme, Alarme)
  - Nicht: "Licht war 47x an und aus" (das war die Simulation)
  - Priorisiert nach Relevanz

---

### Feature 7.12: Saisonale Anpassung

**Jarvis-Moment:** "Es wird früh dunkel — Licht geht ab 16:30 an."

**Beschreibung:**
Erweitert Phase 4 Seasonal Calendar um automatische Anpassung aller Routinen.

**Implementierung:**
- Saisonale Routine-Modifikation:
  | Aspekt | Sommer | Winter |
  |--------|--------|--------|
  | Licht an | 20:30 | 16:30 |
  | Rolladen hoch | 6:00 | 7:30 |
  | Heizung | Aus / Kühlung | Eco / Comfort |
  | Lüften | Morgens + Abends | Kurz Stoßlüften |
  | Briefing | "UV-Index hoch — Sonnencreme" | "Glatteis möglich" |
- Übergangszeiten: Graduelle Anpassung, nicht abrupt
- Feiertags-Bewusstsein: Routinen anpassen an Feiertage

---

### Feature 7.13: Kontext-Ketten über Tage

**Jarvis-Moment:** "Du wolltest am Freitag aufräumen — morgen ist es soweit."

**Beschreibung:**
Jarvis verfolgt Pläne und Absichten über Tage und Wochen. Ergänzt sich mit
Phase 8 Langzeit-Gedächtnis — hier geht es um aktive Erinnerungen.

**Implementierung:**
- Intent-Tracker in der Memory-Schicht:
  ```
  Tag 1: User sagt "Ich muss am Freitag aufräumen, da kommt Besuch"
   → Intent: {action: "aufräumen", reason: "Besuch", deadline: "Freitag"}
  Tag 3: Proaktiv: "Freitag kommt Besuch. Donnerstag aufräumen?"
  Tag 4: "Morgen kommt Besuch. Soll ich den Gästemodus vorbereiten?"
  Tag 5: "Gästemodus aktiv. Alles vorbereitet."
  ```
- Automatische Intent-Extraktion aus Gesprächen via LLM
- Reminder-System mit intelligenter Timing-Wahl

---

### Technische Umsetzung Phase 7

**Betroffene Komponenten:**
- **Assistant-Server:**
  - `routines_engine.py` — Morning Briefing, Gute-Nacht, Background Tasks
  - `greeting_engine.py` — Kontextuelle Begrüßung
  - `scene_intelligence.py` — Natürliche Situations-Erkennung
  - `room_profiles.yaml` — Raum-Definitionen
  - `intent_tracker.py` — Kontext-Ketten
- **Add-on:**
  - `presence_engine.py` — Erweiterung für Willkommen/Abschied
  - `guest_mode.py` — Gäste-Erkennung und Verhaltensänderung

**Neue Einstellungen:**
- `briefing_modules`: Liste aktiver Briefing-Bausteine
- `briefing_length`: kurz/normal/ausführlich
- `goodnight_summary`: true/false
- `guest_mode_auto`: true/false
- `absence_simulation`: true/false

**Geschätzter Aufwand:** ~12-15 Commits

---

---

# Phase 8 — Jarvis Gedächtnis & Vorausdenken
## 10 Features | Status: NEU

> **Ziel:** Jarvis denkt mit, denkt voraus, und vergisst nie.
> **Wo:** Hauptsächlich Assistant-Server (Memory + LLM)
> **Abhängigkeiten:** Phase 4 (Habit Drift), Phase 6 (Persönlichkeit), Phase 7 (Routinen)

### Warum Phase 8?
Gedächtnis und Antizipation sind das Herzstück von Jarvis. Ohne sie ist er ein
Befehlsempfänger. Mit ihnen ist er ein Butler der mitdenkt.

---

### Feature 8.1: Anticipatory Actions

**Jarvis-Moment:** "Jeden Freitag um 18 Uhr machst du Netflix an — soll ich vorbereiten?"

**Beschreibung:**
Jarvis erkennt wiederkehrende Muster und bietet proaktiv an zu handeln.

**Implementierung:**
- Pattern-Detection Engine:
  - Analyse der Action-History (letzte 30 Tage)
  - Erkennung von Zeit-Mustern (täglich, wöchentlich, werktags)
  - Erkennung von Sequenz-Mustern (A → B → C)
  - Erkennung von Kontext-Mustern (Regen → Rolladen zu)
- Confidence-Threshold:
  - < 60%: Nichts sagen
  - 60-80%: Fragen "Soll ich?"
  - 80-95%: Vorschlagen "Ich bereite vor?"
  - > 95% + Autonomie-Level ≥ 4: Einfach machen + informieren
- Beispiel-Patterns:
  ```
  Pattern: Mo-Fr 6:45 → Kaffeemaschine an
  → Mo-Fr 6:40: "Kaffee wird vorbereitet."

  Pattern: Freitag 18:00 → Wohnzimmer-Licht dimm + TV an
  → Freitag 17:55: "Filmabend? Soll ich vorbereiten?"

  Pattern: Regen + Fenster offen → User schließt Fenster
  → "Es fängt an zu regnen — Fenster im Schlafzimmer ist noch offen."
  ```
- Feedback-Loop: Wenn Nutzer ablehnt → Confidence sinkt

---

### Feature 8.2: Lernende Routinen

**Jarvis-Moment:** "Du änderst jeden Abend die Temperatur — soll ich das automatisieren?"

**Beschreibung:**
Erweitert Phase 4 Habit Drift Detection um aktive Routine-Vorschläge.

**Implementierung:**
- Routine-Vorschlag-Pipeline:
  1. Muster erkannt (Phase 4 Habit Drift)
  2. Muster bestätigt (>2 Wochen konsistent)
  3. Vorschlag an Nutzer: "Du stellst jeden Abend um 22 Uhr die Heizung auf 19°. Soll ich das automatisch machen?"
  4. Bei Zustimmung: Automation erstellt
  5. Weiter beobachten: Wenn sich Verhalten ändert → Automation anpassen
- Unterscheidung Wochentag/Wochenende/Urlaub
- Unterscheidung Sommer/Winter
- Routinen sind editierbar und löschbar

---

### Feature 8.3: Kontext-Gedächtnis über Wochen/Monate

**Jarvis-Moment:** "Vor 3 Wochen hast du nach dem Carbonara-Rezept gefragt."

**Beschreibung:**
Erweitert das bestehende 3-Schicht-Gedächtnis um aktive Langzeit-Nutzung.

**Implementierung:**
- Erweiterung der ChromaDB Episodic Memory:
  - Besseres Tagging: Thema, Personen, Orte, Aktionen
  - Zeitliche Suche: "Was haben wir letzte Woche besprochen?"
  - Thematische Suche: "Was weißt du über Kochen?"
- Proaktive Referenzen:
  - Wenn Nutzer über Thema X spricht und es vor 2 Wochen auch tat → Referenz
  - "Du hattest letztens erwähnt dass..." (nicht immer, nur wenn relevant)
- Vergessens-Mechanismus:
  - Unwichtiges verblasst (Confidence sinkt über Zeit)
  - Wichtiges bleibt (oft referenziert = hohe Confidence)

---

### Feature 8.4: Konversations-Kontinuität

**Jarvis-Moment:** "Du wolltest vorhin noch wissen..."

**Beschreibung:**
Jarvis merkt sich unterbrochene Gespräche und setzt sie fort.

**Implementierung:**
- Unfinished-Conversation-Tracker:
  - Erkennt: Frage gestellt aber keine Antwort gegeben (User ging weg)
  - Erkennt: Multi-Part-Frage, nur Teil 1 beantwortet
  - Erkennt: "Ich frag dich nachher nochmal"
- Fortsetzung bei nächster Interaktion:
  "Wir waren vorhin bei [Thema] stehen geblieben — noch relevant?"
- Timeout: Nach 24h wird die Fortsetzung nicht mehr aktiv angeboten
  (aber bei Nachfrage immer noch abrufbar)

---

### Feature 8.5: Wissens-Notizbuch

**Jarvis-Moment:** "Merk dir: Die Nachbarn heißen Müller."

**Beschreibung:**
Gezieltes Speichern und Abrufen von Fakten — erweitert die bestehende
Semantic Memory um explizite Nutzer-Steuerung.

**Implementierung:**
- Explizite Befehle:
  - "Merk dir: [Fakt]" → Speichern mit hoher Confidence
  - "Was weißt du über [Thema]?" → Abrufen
  - "Was weißt du über mich?" → Alle Fakten zu Person
  - "Vergiss [Thema]" → Löschen
  - "Was hast du heute gelernt?" → Neue Fakten des Tages
- Kategorien:
  - Personen (Nachbarn, Familie, Freunde)
  - Präferenzen (Lieblingsessen, Musik, Temperatur)
  - Haus (Geräte, Wartung, Codes)
  - Allgemein (Notizen, Fakten, Ideen)
- Unterscheidung: Explizit gemerkt vs. implizit gelernt
- Nutzer hat volle Kontrolle über gespeicherte Fakten

---

### Feature 8.6: Wissensabfragen

**Jarvis-Moment:** "Wie lange braucht ein Ei zum Kochen?"

**Beschreibung:**
Jarvis beantwortet allgemeine Wissensfragen über das lokale LLM.

**Implementierung:**
- Intent-Routing:
  - Smart-Home-Befehl → Function Calling Pipeline
  - Wissensfrage → Direkte LLM-Antwort (Qwen 14B)
  - Erinnerungsfrage → Memory-Suche
- Qwen 14B Wissens-Stärken nutzen:
  - Allgemeinwissen, Kochen, Wissenschaft, Geschichte
  - Mathe, Umrechnungen, Fakten
- Ehrlichkeit bei Unsicherheit:
  "Da bin ich mir nicht sicher. Mein Wissen hat Grenzen."
- Optional: RAG (Retrieval-Augmented Generation) mit lokalen Dokumenten
  - Bedienungsanleitungen, Rezepte, Handbücher als PDF indexieren

---

### Feature 8.7: Lern-Feedback

**Jarvis-Moment:** "Du korrigierst die Temperatur oft auf 21° — soll das der Standard sein?"

**Beschreibung:**
Jarvis fragt selten aber gezielt nach ob er richtig liegt.

**Implementierung:**
- Feedback-Trigger:
  - Nutzer korrigiert Jarvis-Aktion > 3x → Nachfragen
  - Neues Muster erkannt (> 1 Woche konsistent) → Bestätigen
  - Jarvis unsicher bei Entscheidung → Einmal fragen, dann merken
- Feedback-Arten:
  - "Du stellst die Temperatur oft auf 21° um — soll das der neue Standard sein?"
  - "Ich hab gelernt dass du abends wärmeres Licht magst — stimmt das?"
  - "Passt 70% Helligkeit oder soll ich mir was anderes merken?"
- Max 1 Feedback-Frage pro Tag (nicht nerven)
- Feedback wird in Semantic Memory gespeichert mit hoher Confidence

---

### Feature 8.8: "Was wäre wenn" Simulation

**Jarvis-Moment:** "Was kostet es wenn ich die Heizung 2 Grad höher stelle?"

**Beschreibung:**
Jarvis kann Szenarien durchspielen und Auswirkungen abschätzen.

**Implementierung:**
- Simulations-Engine:
  - Energie-Simulation: Kosten-Hochrechnung basierend auf historischen Daten
  - Temperatur-Simulation: Wie schnell wird es kalt wenn Heizung aus?
  - Abwesenheits-Simulation: Was passiert wenn 2 Wochen weg?
- LLM-basiert mit Kontext-Daten:
  ```
  Input: "Was passiert wenn ich 2 Wochen in Urlaub fahre?"
  Context: [aktuelle Heizung, Pflanzen-Sensoren, Energiedaten, Sicherheit]
  Output: "Heizung auf Frostschutz → ~30€ gespart. Anwesenheitssimulation aktiv.
           Pflanzen-Bewässerung: 3 Liter/Tag. Alarm scharf.
           Soll ich das so einrichten?"
  ```
- Grobe Schätzungen mit Disclaimer ("Ungefähr", "Basierend auf deinem Verbrauch")

---

### Feature 8.9: Intent-Extraktion aus Gesprächen

**Jarvis-Moment:** Merkt sich beiläufig erwähnte Pläne automatisch.

**Beschreibung:**
Wenn der Nutzer im Gespräch Absichten erwähnt, extrahiert Jarvis diese automatisch.

**Implementierung:**
- LLM-basierte Intent-Extraktion nach jedem Gespräch:
  ```
  User: "Nächstes Wochenende kommen meine Eltern"
  → Intent: {who: "Eltern", when: "nächstes Wochenende", type: "Besuch"}
  → Reminder am Freitag: "Deine Eltern kommen morgen. Gästemodus vorbereiten?"
  ```
- Keine Bestätigung nötig (implizit gespeichert)
- Nutzer kann nachfragen: "Was steht an?" → Alle erkannten Intents

---

### Feature 8.10: Langzeit-Persönlichkeits-Anpassung

**Jarvis-Moment:** Nach 3 Monaten kennt er dich besser als am Anfang.

**Beschreibung:**
Jarvis wird über die Zeit persönlicher. Sein Verhalten passt sich langfristig an.

**Implementierung:**
- Persönlichkeits-Evolution:
  - Woche 1-2: Formell, vorsichtig, fragt viel
  - Monat 1: Lockerer, kennt Basis-Präferenzen
  - Monat 3: Persönlich, macht Anspielungen, antizipiert
  - Monat 6+: Wie ein alter Freund — kennt Gewohnheiten, Vorlieben, Macken
- Formality-Score sinkt graduell (0-100, startet bei 80)
- Humor-Comfort steigt graduell
- Basiert auf: Interaktionshäufigkeit, positive Reaktionen, Dauer der Nutzung

---

### Technische Umsetzung Phase 8

**Betroffene Komponenten:**
- `anticipation_engine.py` — Pattern Detection, Proaktive Vorschläge
- `routine_learner.py` — Routine-Erkennung und Automation-Erstellung
- `memory_manager.py` — Erweiterung Langzeit-Gedächtnis
- `conversation_tracker.py` — Unterbrochene Gespräche
- `knowledge_notebook.py` — Explizite Fakten-Verwaltung
- `intent_extractor.py` — Automatische Absichts-Erkennung
- `simulator.py` — Was-wäre-wenn-Szenarien

**Geschätzter Aufwand:** ~12-15 Commits

---

---

# Phase 9 — Jarvis Stimme & Akustik
## 8 Features | Status: NEU

> **Ziel:** Jarvis klingt wie Jarvis — nicht wie ein Roboter.
> **Wo:** TTS/STT Pipeline, Audio-Processing
> **Abhängigkeiten:** Phase 6 (Persönlichkeit bestimmt WAS gesagt wird, hier geht es um WIE)

---

### Feature 9.1: Stimme & Sprechweise

**Beschreibung:**
Piper TTS optimieren für natürlichere, Jarvis-artige Sprachausgabe.

**Implementierung:**
- **SSML-Tags** für Betonung und Pausen:
  ```xml
  <speak>
    <prosody rate="95%">Guten Morgen.</prosody>
    <break time="500ms"/>
    <prosody rate="105%">Es ist 7 Uhr, draußen 4 Grad.</prosody>
  </speak>
  ```
- **Pausen einbauen:**
  - Vor wichtigen Infos: 300ms Pause
  - Nach Fragen: 500ms Pause (wirkt nachdenklich)
  - Zwischen Themen-Wechsel: 400ms
- **Sprechgeschwindigkeit variieren:**
  - Routine-Infos: 105% Speed
  - Wichtiges: 90% Speed
  - Warnungen: 85% Speed
- **Custom Piper Voice** (optional, aufwändig):
  - Eigene Stimme trainieren mit tiefem, ruhigem, britischem Charakter
  - Benötigt ~2h Trainings-Audio + GPU für Training

---

### Feature 9.2: Sound-Design

**Beschreibung:**
Akustische Identität — nicht nur Sprache, sondern auch Töne.

**Implementierung:**
- Sound-Bibliothek:
  | Event | Sound | Beschreibung |
  |-------|-------|-------------|
  | Aufmerksamkeit | Soft chime | Bevor Jarvis spricht |
  | Befehl bestätigt | Short ping | Aktion ausgeführt |
  | Warnung | Two-tone alert | Etwas stimmt nicht |
  | Alarm | Urgent tone | Notfall |
  | System-Start | Boot sequence | "Alle Systeme online" |
  | System-Stop | Shutdown tone | "Gute Nacht" |
  | Fehler | Error buzz | Konnte nicht ausführen |
  | Incoming | Soft bell | Jemand an der Tür / Nachricht |
- Sounds über HA Media Player abspielen
- Lautstärke-anpassend (Nacht = leiser)
- Optional: Eigene Sounds erstellen oder generieren

---

### Feature 9.3: Flüster-Modus

**Beschreibung:**
Automatische Lautstärke-Anpassung basierend auf Kontext.

**Implementierung:**
- Auto-Volume-Logic:
  | Kontext | Volume | TTS-Speed |
  |---------|:------:|:---------:|
  | Tag, normal | 80% | 100% |
  | Abend (>22:00) | 50% | 95% |
  | Nacht (>0:00) | 30% | 90% |
  | Jemand schläft | 20% | 90% |
  | Fokus-Arbeit | 40% | 100% |
  | Gäste | 60% | 95% |
  | Notfall | 100% | 100% |
- Manueller Trigger: "Psst" oder "Leise bitte" → Flüster-Modus bis Widerruf
- Baby/Kind-Modus: Extra leise + nur LED bei nicht-kritischen Meldungen

---

### Feature 9.4: Narration-Modus

**Beschreibung:**
Fließende Übergänge statt abrupte Schaltvorgänge.

**Implementierung:**
- Transitions-Engine:
  - Licht: Fade über 3-10 Sekunden statt instant
  - Rolladen: Langsam fahren
  - Musik: Fade-in/Fade-out
  - Heizung: Graduelle Änderung
- Szenen-Orchestrierung:
  ```
  "Filmabend" → Sequenz:
  1. Licht dimmt langsam (5s)
  2. Rolladen fahren runter (während Dimming)
  3. TV geht an
  4. Hintergrundmusik faded out (3s)
  5. Jarvis: "Viel Spaß." (nach 8s)
  ```
- Morgen-Sequenz:
  1. Rolladen fahren langsam hoch (synchron mit Sonnenaufgang)
  2. Licht geht sanft an (warmweiß, 10%)
  3. Heizung steigt graduell
  4. Nach 5 Min: Morning Briefing

---

### Feature 9.5: Stimmungserkennung durch Sprachanalyse

**Beschreibung:**
Analyse der Stimme (nicht nur Text) für bessere Emotionserkennung.

**Implementierung:**
- **Ansatz 1** (Einfach — empfohlen für Start):
  - Whisper Transkriptions-Metadaten nutzen:
    - Sprechgeschwindigkeit (Wörter pro Sekunde)
    - Satzlänge und -struktur
    - Keywords (Flüche, Seufzer, Lachen)
  - Regelbasiert: Schnell + kurz = gestresst, langsam + leise = müde
- **Ansatz 2** (Fortgeschritten — optional):
  - Separates Audio-Analyse-Modell (z.B. emotion2vec oder SpeechBrain)
  - Analysiert: Tonhöhe, Tempo, Energie, Pausen
  - Benötigt zusätzliche GPU-Ressourcen
- Integration mit Phase 6 Emotionale Intelligenz

---

### Feature 9.6: Personen-Erkennung per Stimme

**Beschreibung:**
Jarvis erkennt WER spricht und passt sich an.

**Implementierung:**
- **Speaker Diarization** mit einem lokalen Modell:
  - pyannote-audio (Open Source, lokal lauffähig)
  - Enrollment: Jede Person spricht 30 Sekunden → Voice-Print
  - Erkennung: Audio-Segment → "Das ist [Person X]"
- Pro Person:
  - Eigene Anrede (Name, Spitzname)
  - Eigene Präferenzen (Temperatur, Licht, Humor-Level)
  - Eigene Berechtigungen (Vertrauensstufe)
  - Eigene Erinnerungen und Kontext
- Fallback bei Unsicherheit: "Entschuldigung, wer spricht?"
- **Hardware-Anforderung:** ~1-2 GB extra RAM für das Modell

---

### Feature 9.7: Aktivierungs-Verhalten

**Beschreibung:**
Wie Jarvis sich "meldet" bevor er spricht — nicht einfach losreden.

**Implementierung:**
- Bei proaktiver Meldung:
  1. Aufmerksamkeits-Sound (Feature 9.2)
  2. Kurze Pause (300ms)
  3. Sprechen
- Bei Antwort auf Befehl:
  1. Kurze Denk-Pause (200-500ms) bei komplexen Fragen
  2. Sofortige Antwort bei einfachen Befehlen
- Bei Notfall:
  1. Alarm-Sound
  2. Sofort sprechen, keine Pause

---

### Feature 9.8: Mehrsprachigkeit

**Beschreibung:**
Jarvis erkennt die Sprache und antwortet entsprechend.

**Implementierung:**
- Whisper erkennt die Sprache automatisch
- Default: Deutsch
- Wenn Gast auf Englisch spricht → Antwort auf Englisch
- Konfigurierbar pro Person
- Piper TTS: Separate Voice-Modelle pro Sprache

---

### Technische Umsetzung Phase 9

**Betroffene Komponenten:**
- `tts_engine.py` — SSML-Generation, Volume-Control, Speed
- `sound_manager.py` — Sound-Bibliothek, Event-Sounds
- `narration_engine.py` — Transitions, Sequenzen, Fading
- `speaker_recognition.py` — Voice-Print, Diarization
- `audio_analyzer.py` — Stimmungsanalyse (optional)

**Neue Hardware-Anforderungen:**
- Speaker Recognition: +1-2 GB RAM
- Audio-Analyse: +1 GB RAM (optional)
- Custom Voice Training: GPU für einmaligen Training-Lauf

**Geschätzter Aufwand:** ~10-12 Commits

---

---

# Phase 10 — Jarvis Multi-Room & Kommunikation
## 8 Features | Status: NEU

> **Ziel:** Jarvis ist überall — folgt dir durchs Haus, kommuniziert mit allen.
> **Wo:** Add-on (HA-Integration) + Assistant (Routing-Logik)
> **Abhängigkeiten:** Phase 9 (Personen-Erkennung), Phase 5 (Sicherheit), Phase 7 (Routinen)

---

### Feature 10.1: Multi-Room Presence

**Beschreibung:**
Jarvis antwortet nur im Raum wo du bist. Musik folgt dir.

**Implementierung:**
- Raum-Tracking:
  - Bewegungsmelder pro Raum
  - Optional: BLE-Beacons / Ultra-Wideband für Präzision
  - Letzte Aktivität = aktueller Raum
- TTS-Routing:
  - Antwort nur über den Speaker im aktiven Raum
  - Bei Unsicherheit: Alle Räume oder Nachfragen
- Musik folgt:
  - Wenn Raum gewechselt → Musik transferieren (HA Media Player Group)
  - Fade-out im alten Raum, Fade-in im neuen (Narration-Modus)
- Licht folgt:
  - Alter Raum: Licht aus nach 2 Min ohne Bewegung
  - Neuer Raum: Licht an (Raum-Profil)

---

### Feature 10.2: Delegieren an andere Personen

**Beschreibung:**
Jarvis übermittelt Nachrichten zwischen Haushaltsmitgliedern.

**Implementierung:**
- Sprachgesteuert:
  - "Sag Lisa dass das Essen fertig ist"
  - "Erinner [Person] an [Ding] wenn sie nach Hause kommt"
- Delivery:
  - Person zu Hause: TTS-Announcement in deren Raum
  - Person nicht zu Hause: Push-Notification über HA Companion App
- Pro Person: Notification-Präferenzen beachten
  - Lisa mag kein TTS → nur Push
  - Max will alles → TTS + Push
- Bestätigung an Absender: "Lisa wurde informiert."

---

### Feature 10.3: Kommunikations-Management

**Beschreibung:**
Jarvis als Nachrichten-Filter und Kommunikations-Hub.

**Implementierung:**
- HA Companion App Integration:
  - Nachrichten-Count: "Du hast 3 ungelesene Nachrichten"
  - Türklingel: "An der Tür steht jemand. Soll ich öffnen?"
  - Telefon: "Eingehender Anruf von [Person]" (wenn HA-Integration vorhanden)
- Nachrichten-Priorisierung:
  - Wichtige Kontakte → Sofort melden
  - Rest → Sammeln und bei Gelegenheit melden
- Smart Responses:
  - "Sag [Person] ich ruf in 10 Minuten zurück" → Push-Nachricht senden

---

### Feature 10.4: Vertrauensstufen

**Beschreibung:**
Verschiedene Berechtigungslevel für verschiedene Nutzer.

**Implementierung:**
- Stufen:
  | Level | Name | Rechte |
  |:-----:|------|--------|
  | 0 | Gast | Licht, Temperatur, Musik (nur Raum) |
  | 1 | Mitbewohner | Alles außer Sicherheit und System |
  | 2 | Owner | Voller Zugriff |
  | 3 | Admin | System-Konfiguration, Notfall-Override |
- Authentifizierung:
  - Stimm-Erkennung (Phase 9.6) → automatische Zuordnung
  - PIN-Code als Fallback → "Bitte bestätigen: [PIN]"
  - Bestimmte Befehle erfordern höhere Stufe:
    "Alarm deaktivieren erfordert Owner-Berechtigung. Bestätigst du?"
- Konfigurierbar: Welche Aktionen welche Stufe brauchen

---

### Feature 10.5: Selbst-Diagnostik & Transparenz

**Beschreibung:**
Jarvis meldet wenn etwas im System nicht stimmt.

**Implementierung:**
- System-Monitoring:
  - Sensor-Watchdog: "Bewegungsmelder Flur meldet seit 4h nichts — Batterie?"
  - Verbindungs-Check: "Thermostat Büro ist offline seit 30 Min"
  - Performance-Check: "Mein Sprachmodell antwortet gerade langsam"
  - Speicher-Check: "Festplatte zu 85% voll"
- Proaktive Meldung nur bei Problemen (nicht: "Alles okay")
- Auf Nachfrage: Vollständiger System-Status
  "Alle Systeme laufen. 14 Sensoren online, 3 Automationen aktiv,
   Antwortzeit 1.2 Sekunden. Speicher 62%."
- Wartungs-Erinnerungen:
  - "Filter der Lüftungsanlage — letzter Wechsel vor 6 Monaten"
  - "Rauchmelder-Batterien — letzter Test vor 11 Monaten"

---

### Feature 10.6: Gesundheits-Monitoring (Erweiterung)

**Beschreibung:**
Erweitert Phase 4 um Smartwatch-Integration und aktive Gesundheits-Features.

**Implementierung:**
- Smartwatch-Integration (über HA):
  - Herzfrequenz-Tracking
  - Schlafphasen-Daten
  - Schrittzähler
- Gesundheits-Kommentare:
  - "Du hast letzte Nacht nur 5 Stunden geschlafen. Kaffee steht bereit."
  - "6.000 Schritte heute — fehlen noch 4.000"
  - "Dein Puls ist erhöht. Alles gut?"
- Medikamenten-Erinnerung (manuell konfiguriert)
- Trink-Erinnerung basierend auf Aktivität
- Nicht invasiv — Vorschläge, keine Befehle

---

### Feature 10.7: Anwesenheitssimulation (Erweitert)

**Beschreibung:**
Realistische Simulation wenn niemand zu Hause ist.

**Implementierung:**
- Lernbasiert aus echten Nutzungsmustern:
  - Wann gehen normalerweise welche Lichter an/aus?
  - Wann läuft der TV?
  - Wann bewegen sich Rolladen?
- Replay der letzten 7 Tage mit leichter Variation (±30 Min)
- TV-Sound-Simulation über Media Player
- Intelligentes Timing: Nicht Licht um 3 Uhr nachts

---

### Feature 10.8: Wartungs-Assistent

**Beschreibung:**
Jarvis erinnert an Wartungen und Haushaltsaufgaben.

**Implementierung:**
- Wartungs-Kalender:
  - Rauchmelder testen (jährlich)
  - Filter wechseln (halbjährlich)
  - Heizung warten (jährlich)
  - Dachrinne reinigen (saisonal)
- Haushalt-Tracker:
  - "Letzte Bettwäsche-Wechsel vor 2 Wochen"
  - "Kühlschrank-Reinigung überfällig"
- Konfigurierbar: Nutzer legt Intervalle fest
- Sanfte Erinnerungen: "Nebenbei: Die Rauchmelder könnten mal wieder getestet werden."

---

### Technische Umsetzung Phase 10

**Betroffene Komponenten:**
- **Add-on:**
  - `multiroom_engine.py` — Room Tracking, TTS Routing, Music Follow
  - `trust_levels.py` — Berechtigungsstufen, Auth
- **Assistant:**
  - `communication_hub.py` — Nachrichten-Management, Delegation
  - `diagnostics_engine.py` — System-Monitoring, Wartung
  - `health_extended.py` — Smartwatch, Gesundheit
  - `simulation_engine.py` — Anwesenheitssimulation

**Hardware-Empfehlungen:**
- 1 Mikrofon + Speaker pro Raum (Satellite-Setup über Wyoming)
- Bewegungsmelder pro Raum
- Optional: BLE-Beacons für präzise Lokalisierung

**Geschätzter Aufwand:** ~10-12 Commits

---

---

# Gesamtübersicht: Timeline & Aufwand

## Empfohlene Reihenfolge

```
     Start
       │
       ▼
   Phase 4 ─── Smart Features + Gesundheit ─── 29 Features ─── ~15 Commits
       │
       ▼
   Phase 5 ─── Sicherheit + Spezial-Modi ──── 11 Features ─── ~10 Commits
       │
       ├─────────────────────┐
       ▼                     ▼
   Phase 6              Phase 7
   Persönlichkeit        Routinen
   12 Features           13 Features
   ~10 Commits           ~15 Commits
       │                     │
       ├─────────────────────┘
       ▼
   Phase 8 ─── Gedächtnis & Vorausdenken ──── 10 Features ─── ~15 Commits
       │
       ├─────────────────────┐
       ▼                     ▼
   Phase 9              Phase 10
   Stimme & Akustik      Multi-Room & Komm.
   8 Features            8 Features
   ~12 Commits           ~12 Commits
       │                     │
       ├─────────────────────┘
       ▼
   🎯 JARVIS COMPLETE
```

## Feature-Count pro Phase

| Phase | Name | Features | Commits | Schwerpunkt |
|:-----:|------|:--------:|:-------:|-------------|
| 4 | Smart Features | 29 | ~15 | Daten & Muster |
| 5 | Sicherheit | 11 | ~10 | Schutz & Modi |
| 6 | Persönlichkeit | 12 | ~10 | Charakter |
| 7 | Routinen | 13 | ~15 | Tagesstruktur |
| 8 | Gedächtnis | 10 | ~15 | Vorausdenken |
| 9 | Stimme | 8 | ~12 | Akustik |
| 10 | Multi-Room | 8 | ~12 | Präsenz |
| **Σ** | | **91** | **~89** | |

**Gesamt: 91 neue Features + 125 bestehende = 216 Features**

---

## Hardware-Empfehlungen

### Minimum (was ihr wahrscheinlich schon habt):
- PC 2 mit 32 GB RAM, dedizierte GPU (RTX 3060+ oder ähnlich)
- Mikrofon + Speaker in Hauptraum
- Bewegungsmelder in Haupträumen
- Tür/Fenster-Sensoren

### Empfohlen für volles Jarvis-Erlebnis:
- PC 2 mit 64 GB RAM (für Speaker Recognition + Audio-Analyse parallel)
- Wyoming Satellite pro Raum (Mikrofon + Speaker)
- Bewegungsmelder in JEDEM Raum
- Smartwatch (für Gesundheits-Features)
- BLE-Beacons (für präzise Raum-Erkennung)
- Smarte Türklingel mit Kamera
- Rauch/CO/Wasser-Sensoren

---

## Risiken & Mitigationen

| Risiko | Wahrscheinlichkeit | Mitigation |
|--------|:------------------:|-----------|
| Qwen 14B Persönlichkeit nicht gut genug | Mittel | System-Prompts iterativ verbessern, ggf. Fine-Tuning |
| Speaker Recognition zu ungenau | Mittel | Fallback auf PIN, mehrere Enrollment-Sessions |
| RAM reicht nicht für alles parallel | Niedrig | Feature-Flags, Module on-demand laden |
| Zu viele proaktive Meldungen nerven | Hoch | Strikte Frequenz-Limiter, Feedback-Loop, Stille-Matrix |
| Muster falsch erkannt (False Positives) | Mittel | Hohe Confidence-Schwellen, immer erst fragen |
| Latenz zu hoch (viele Module) | Mittel | Caching, Model-Routing (3B für Quick, 14B für Complex) |

---

## Die Jarvis-Essenz — Was dieses System ausmacht

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│   "Ein normaler Assistent reagiert.                 │
│    Jarvis antizipiert.                              │
│                                                     │
│    Ein normaler Assistent gehorcht.                 │
│    Jarvis hat eine Meinung.                         │
│                                                     │
│    Ein normaler Assistent vergisst.                 │
│    Jarvis erinnert sich an alles.                   │
│                                                     │
│    Ein normaler Assistent ist ein Tool.             │
│    Jarvis ist ein Mitbewohner."                     │
│                                                     │
│                  — MindHome Jarvis Masterplan, 2026  │
└─────────────────────────────────────────────────────┘
```

---

*Dieses Dokument wird mit jeder Phase aktualisiert.*
*Nächster Schritt: Phase 4 implementieren (PHASE4_PLAN.md)*
