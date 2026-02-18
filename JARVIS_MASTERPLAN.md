# MindHome — JARVIS Masterplan
# "Von Smart Assistant zu echtem Jarvis"

> **Stand:** 2026-02-18
> **Aktueller Status:** v0.8.4 (Phase 5 abgeschlossen, Build 87)
> **Architektur:** PC 1 (HAOS Add-on v0.8.4) + PC 2 (Assistant Server)
> **Prinzip:** 100% lokal, kein Cloud, Privacy-first
> **GRUNDREGEL: Jarvis hat KEINEN Internetzugang.**

---

## Offline-Prinzip (Eiserne Regel)

Jarvis laeuft ohne Internet. Sobald das System steht, wird der Internetzugang gekappt.

**Was das bedeutet:**
- Jarvis macht KEINE eigenen HTTP-Calls ins Internet. Niemals.
- Alle externen Daten (Wetter, Pollen, Kalender) kommen ueber **Home Assistant Entities**.
  HA holt die Daten → exponiert sie als Entities → Jarvis liest die Entities lokal.
- Alle Modelle (LLM, STT, TTS, Vision) laufen lokal via Ollama/Piper/Whisper.
- Alle Datenbanken (ChromaDB, Redis) laufen lokal.
- Sound-Dateien sind lokal gespeichert, kein Streaming.
- Frontend-Libraries (React, Babel) werden beim Docker-Build einmalig heruntergeladen
  und danach ins Image gebacken — zur Laufzeit kein CDN-Zugriff.

**Erlaubte Netzwerk-Kommunikation (nur lokal):**
| Service | URL | Zweck |
|---------|-----|-------|
| Home Assistant | `http://supervisor/core` | Smart-Home Steuerung + Entities |
| Ollama | `http://localhost:11434` | LLM (Qwen) |
| ChromaDB | `http://localhost:8100` | Semantic Memory |
| Redis | `redis://localhost:6379` | Cache, Queues, State |
| Assistant | `http://192.168.1.100:8200` | MindHome Assistant Server |

**Code-Audit (2026-02-18): Bestanden.** Keine externen Internet-Calls im bestehenden Code.

---

## Architektur-Übersicht

```
┌───────────────────────────────┐     ┌───────────────────────────────┐
│  PC 1 — Home Assistant OS     │     │  PC 2 — Assistant Server      │
│                               │     │                               │
│  MindHome Add-on (v0.8.4)    │     │  MindHome Assistant           │
│  ├─ 23 Domain-Plugins        │◄───►│  ├─ brain.py (Orchestrator)   │
│  ├─ Pattern Engine            │ API │  ├─ personality.py            │
│  ├─ Automation Engine         │     │  ├─ mood_detector.py          │
│  ├─ Phase 4 Engines (10)     │     │  ├─ memory.py (3 Schichten)   │
│  ├─ Phase 5 Engines (7)      │     │  ├─ function_calling.py       │
│  ├─ 17 Route-Module          │     │  ├─ action_planner.py         │
│  ├─ 71 DB-Modelle            │     │  ├─ proactive.py              │
│  └─ React Frontend           │     │  ├─ feedback.py               │
│                               │     │  ├─ autonomy.py (5 Level)    │
│  FERTIG — ~156 Features       │     │  ├─ activity.py              │
│                               │     │  ├─ summarizer.py            │
│                               │     │  ├─ context_builder.py       │
│                               │     │  └─ model_router.py          │
│                               │     │                               │
│                               │     │  Ollama: Qwen 2.5 (3B + 14B) │
│                               │     │  ChromaDB + Redis             │
└───────────────────────────────┘     └───────────────────────────────┘
```

**Wichtig:** Das Add-on ist **fertig** (Phase 1–5 implementiert). Der Masterplan
fokussiert sich auf den **Assistant** — dort passiert die Jarvis-Transformation.

---

## Was der Assistant BEREITS kann

| Feature | Modul | Status |
|---------|-------|--------|
| Butler-Persönlichkeit (5 Layer) | `personality.py` | ✅ |
| Stimmungserkennung (5 Zustände) | `mood_detector.py` | ✅ |
| 3-Schicht-Gedächtnis | `memory.py` + `semantic_memory.py` | ✅ |
| Fakten-Extraktion aus Gesprächen | `memory_extractor.py` | ✅ |
| 10 HA-Tools (Licht, Klima, Szenen...) | `function_calling.py` | ✅ |
| Multi-Step Action Planning | `action_planner.py` | ✅ |
| Proaktive Nachrichten (Alarm, Ankunft) | `proactive.py` | ✅ |
| Adaptives Feedback-Learning | `feedback.py` | ✅ |
| 5 Autonomie-Level | `autonomy.py` | ✅ |
| Aktivitätserkennung + Stille-Matrix | `activity.py` | ✅ |
| Zusammenfassungen (Tag/Woche/Monat) | `summarizer.py` | ✅ |
| Kontext-Builder (Haus-Status) | `context_builder.py` | ✅ |
| Smart Model Routing (3B/14B) | `model_router.py` | ✅ |
| Ankunfts-Briefing | `proactive.py` | ✅ |
| Mood-adaptive Antwortlänge | `personality.py` | ✅ |

---

## Was der Assistant NOCH NICHT kann — Die Jarvis-Lücken

Aus unserer 47-Feature-Liste sind folgende **wirklich neu**:

| # | Feature | Warum fehlt es? |
|---|---------|----------------|
| 1 | Sarkasmus & Humor-Level | Persönlichkeit ist statisch, kein konfigurierbarer Humor |
| 2 | Easter Eggs | Keine versteckten Befehle/Reaktionen |
| 3 | Selbstironie | Kein Selbst-Bewusstsein über eigene Situation |
| 4 | Zeitgefühl | Keine Duration-Überwachung laufender Geräte |
| 5 | Antwort-Varianz | Bestätigungen wiederholen sich |
| 6 | Running Gags | Keine Referenzen zu früheren Gesprächen als Humor |
| 7 | Charakter-Entwicklung | Persönlichkeit ändert sich nicht über Wochen |
| 8 | Morning Briefing (strukturiert) | Ankunfts-Report existiert, aber kein Morgen-Briefing |
| 9 | Gute-Nacht-Routine | Kein strukturierter Tagesabschluss |
| 10 | Kontextuelle Begrüßung | Begrüßungen sind nicht tageszeit-/kontext-spezifisch |
| 11 | Abschied/Willkommen | Kein explizites Gehen/Kommen-Verhalten |
| 12 | Szenen-Intelligenz | "Mir ist kalt" → wird nicht verstanden |
| 13 | Gäste-Modus | Kein Verhaltens-Wechsel bei Gästen |
| 14 | Raum-Intelligenz | Räume haben keine Profile/Persönlichkeit |
| 15 | Vorausschauendes Energie-Mgmt | Keine proaktiven Energie-Vorschläge |
| 16 | Abwesenheits-Zusammenfassung | Kein Report "während du weg warst" |
| 17 | Saisonale Routine-Anpassung | Routinen ändern sich nicht mit Jahreszeit |
| 18 | Anticipatory Actions | Muster werden nicht zu Vorschlägen |
| 19 | Explizites Wissens-Notizbuch | "Merk dir X" funktioniert nicht gezielt |
| 20 | Wissensabfragen | "Wie lang kocht ein Ei?" → kein Routing |
| 21 | "Was wäre wenn" Simulation | Keine Szenario-Durchspielung |
| 22 | Intent-Extraktion aktiv | Pläne aus Gesprächen werden nicht verfolgt |
| 23 | Langzeit-Persönlichkeitsanpassung | Kein Formality-Score-Absinken über Zeit |
| 24 | Stimme & Sprechweise (SSML) | TTS ohne Betonung/Pausen |
| 25 | Sound-Design | Keine akustische Identität |
| 26 | Flüster-Modus | Keine automatische Lautstärke-Anpassung |
| 27 | Narration-Modus | Keine fließenden Übergänge/Sequenzen |
| 28 | Stimmungserkennung Sprachanalyse | Nur Text, nicht Audio |
| 29 | Personen-Erkennung Stimme | Kein Speaker Recognition |
| 30 | Multi-Room Presence | TTS geht nicht gezielt in einen Raum |
| 31 | Delegieren an Personen | "Sag Lisa..." funktioniert nicht |
| 32 | Vertrauensstufen | Keine Berechtigungslevel pro Person |
| 33 | Selbst-Diagnostik | Kein "Sensor XY ist offline"-Meldung |

**Das sind 33 wirklich neue Features für den Assistant.**

---

## Die Phasen: Nur Assistant-Features

```
Phase 1-5    ✅  Add-on FERTIG (156 Features)
Assistant    ✅  Basis FERTIG (14 Module, voll funktional)
     │
Phase 6      ✅  Jarvis Persönlichkeit (10 Features — v0.9.0-v0.9.4)
     │
Phase 7      ✅  Jarvis Routinen & Tagesstruktur (9 Features — v0.9.5-v0.9.6)
     │
Phase 8      ✅  Jarvis Gedächtnis & Vorausdenken (7 Features — v0.9.7-v0.9.8)
     │
Phase 9      ✅  Jarvis Stimme & Akustik (6 Features — v0.9.9-v1.0.0)
     │
Phase 10     🆕  Jarvis Multi-Room & Kommunikation (5 Features — Assistant + Add-on)
     │
Phase 11     ✅  Jarvis Wissen & Kontext (4 Features — RAG, Kalender, Korrekturen)
     │
Phase 12     🔧  Jarvis Authentizitaet (5 Techniken — LLM Character Deepening)
     │
Phase 13     📋  Jarvis Selbstprogrammierung (4 Stufen — Self-Evolving Assistant)
     │
Phase 14     📋  Jarvis Wahrnehmung & Sinne (3 Features — Vision, Multi-Modal, Ambient)
     │
Phase 15     📋  Jarvis Haushalt & Fuersorge (4 Features — Gesundheit, Einkauf, Geraete)
     │
Phase 16     📋  Jarvis fuer Alle (3 Features — Konflikte, Onboarding, Dashboard)
     │
     ▼
  🎯 JARVIS COMPLETE
```

---

## Abhängigkeiten

```
Phase 6 ──────────┐
  (Persönlichkeit) │
                   ├──► Phase 8 (Gedächtnis braucht Persönlichkeit + Routinen)
Phase 7 ──────────┘        │
  (Routinen)               ├──► Phase 9  (Stimme braucht Charakter)
                           │
                           └──► Phase 10 (Multi-Room braucht alles)
```

**Phase 6 und 7 können parallel entwickelt werden.**

---

---

# Phase 6 — Jarvis Persönlichkeit & Charakter
## 10 Features | Betroffene Module: personality.py, brain.py

> **Ziel:** Aus dem funktionalen Butler einen Charakter machen.
> **Aufwand:** Hauptsächlich Prompt Engineering + Response-Pipeline-Erweiterungen.
> **Basis:** `personality.py` hat bereits 5 Layer — wir erweitern sie.

---

### Feature 6.1: Konfigurierbarer Humor / Sarkasmus-Level

**Ist-Zustand:** `personality.py` hat einen fixen Butler-Ton mit trockenem Humor.
Kein Regler, keine Variation.

**Soll-Zustand:**
- Sarkasmus-Level in Nutzer-Einstellungen (1–5):
  - 1 = Sachlich, kaum Humor
  - 3 = Standard Butler (aktueller Zustand)
  - 5 = Vollgas Ironie
- Humor-Kontext-Regeln:
  - Morgens vor 8:00 → Max Level 2
  - Stress erkannt (mood_detector) → Level 1
  - Notfall → Level 0
  - Wochenende abends → darf höher sein
- System-Prompt wird dynamisch um Humor-Anweisungen erweitert

**Umsetzung:**
- `personality.py`: Neuer Parameter `sarcasm_level` in `build_system_prompt()`
- Humor-Templates pro Level als Prompt-Abschnitt
- Mood-basierte Dämpfung (bereits vorhanden: `_get_mood_adjustment()`)

---

### Feature 6.2: Eigene Meinung

**Ist-Zustand:** Assistant führt Befehle aus ohne zu kommentieren.

**Soll-Zustand:**
- Opinion-Check nach Function Calling, vor Response:
  - Heizung > 25°C → "Sicher? Das wird teuer."
  - Fenster offen + Heizung an → "Fenster und Heizung gleichzeitig?"
  - Alle Lichter aus bei Anwesenheit → "Nickerchen geplant?"
  - Rolladen runter am Mittag → "Es ist noch hell draußen — bewusst?"
- Gehorcht trotzdem wenn Nutzer bestätigt
- Intensität konfigurierbar (0 = still, 3 = redselig)

**Umsetzung:**
- `brain.py`: Opinion-Check nach `function_calling.execute()`, vor Response
- Regelbasiert (nicht LLM — zu langsam für jede Aktion)
- Nur bei ungewöhnlichen Aktionen, nicht bei jeder

---

### Feature 6.3: Easter Eggs

**Soll-Zustand:**
- Versteckte Befehle und besondere Reaktionen:
  ```
  "Iron Man Anzug" → "Leider fehlt der Anzug. Aber die Heizung ist an."
  "Selbstzerstörung" → "Nur Spaß. Was kann ich wirklich tun?"
  "42" → "Die Antwort auf alles. Aber die Frage?"
  "Wer bist du" → "Jarvis. Butler ohne Trinkgeld."
  ```
- Erweiterbar via `easter_eggs.yaml`
- Fuzzy Matching (Whisper-Transkription ist ungenau)

**Umsetzung:**
- `brain.py`: Easter-Egg-Check vor LLM-Call
- `config/easter_eggs.yaml`: Trigger + Responses
- Levenshtein-Distanz oder Keyword-Matching

---

### Feature 6.4: Selbstironie & Charakter-Tiefe

**Soll-Zustand:**
- Kontext-getriggerte Selbst-Referenzen:
  - "Wie geht es dir?" → "Gut. Ich lebe in einer Box ohne Arme."
  - User bedankt sich → "Gern. Dafür lebe ich. Buchstäblich."
  - System-Fehler → "Das war nicht ich. Wahrscheinlich."
- Frequenz-Limiter: Max 2-3 pro Tag

**Umsetzung:**
- `personality.py`: Selbstironische Prompt-Ergänzung bei bestimmten Triggern
- Tages-Counter in Redis (`mha:selfirony:count:YYYY-MM-DD`)

---

### Feature 6.5: Antwort-Varianz

**Ist-Zustand:** "Erledigt." kommt häufig als Bestätigung.

**Soll-Zustand:**
- Pool von 15+ Varianten pro Bestätigungstyp:
  - Aktion ausgeführt: "Erledigt.", "Gemacht.", "Ist passiert.", "Wie gewünscht.", "Aber natürlich."
  - Ablehnung: "Das geht leider nicht.", "Da muss ich passen.", "Nicht möglich."
- Nie zweimal dieselbe Bestätigung hintereinander
- History der letzten 10 Antworten

**Umsetzung:**
- `personality.py`: Varianz-Pool + Last-Used-Tracker (Redis)
- Alternativ: Prompt-Anweisung "Verwende nie dieselbe Bestätigung zweimal hintereinander"

---

### Feature 6.6: Zeitgefühl

**Ist-Zustand:** Kein Bewusstsein für Dauer von Zuständen.

**Soll-Zustand:**
- Duration-Tracking für lang laufende Geräte:
  - "Der Ofen ist seit 45 Min an — Absicht?"
  - "Fenster seit 2h offen bei 3°C"
  - "Du bist seit 6h am PC ohne Pause"
- Proportions-Zähler:
  - "Das ist dein dritter Kaffee heute"
- Schwellen pro Gerätetyp konfigurierbar

**Umsetzung:**
- Neues Modul `time_awareness.py` im Assistant
- Abonniert HA State-Changes via WebSocket (wie `proactive.py`)
- Eigene Timer-Queue für Duration-Tracking
- Meldet über bestehende Notification-Pipeline

---

### Feature 6.7: Emotionale Intelligenz (Erweiterung)

**Ist-Zustand:** `mood_detector.py` erkennt 5 Zustände, `personality.py` passt
Antwortlänge an. Aber: keine AKTIONEN basierend auf Stimmung.

**Soll-Zustand:**
- Stimmungs-basierte Aktionen:
  | Zustand | Aktion |
  |---------|--------|
  | Gestresst | Licht dimmen, leise Musik vorschlagen |
  | Müde | Temperatur +1°, Licht warm |
  | Gut gelaunt | Musik vorschlagen |
  | Krank | Temperatur 23°, Erinnerungen sanft |
- Aktionen nur bei Autonomie-Level ≥ 3

**Umsetzung:**
- `mood_detector.py`: Neue Methode `get_suggested_actions(mood)`
- `brain.py`: Nach Mood-Erkennung → Aktions-Vorschlag (bei Level 3+: automatisch)

---

### Feature 6.8: Adaptive Komplexität (Erweiterung)

**Ist-Zustand:** `personality.py` hat `max_sentences` basierend auf Mood.
Aber: kein Unterschied zwischen Hektik-Morgen und entspanntem Abend.

**Soll-Zustand:**
- Komplexitäts-Modi:
  - **Kurz** (Trigger: schnelle Befehle, Morgen-Hektik): Max 1 Satz
  - **Normal**: 1-2 Sätze
  - **Ausführlich** (Trigger: Abends, Wochenende, explizite Fragen): Kontext + Vorschläge
- Override: "Kurz bitte" / "Erzähl mehr"

**Umsetzung:**
- `personality.py`: Bestehende `_get_time_context()` erweitern
- Interaktions-Frequenz als Signal (schnelle Abfolge = kurz halten)

---

### Feature 6.9: Running Gags

**Soll-Zustand:**
- Referenzen zu früheren Gesprächen als wiederkehrende Witze
- Basiert auf Episodic Memory (bereits vorhanden)
- Beispiel: User sagte einmal "Ich brauche Urlaub" → Wochen später wenn gestresst:
  "Urlaub war letztes Mal die Lösung, oder?"

**Umsetzung:**
- `personality.py`: Gelegentlich Episodic Memory nach witzigen Referenzen durchsuchen
- Frequenz: Max 1x pro Tag
- Nur bei passendem Kontext + guter Stimmung

---

### Feature 6.10: Charakter-Entwicklung über Zeit

**Soll-Zustand:**
- Jarvis wird über Wochen persönlicher:
  - Woche 1-2: Formell, vorsichtig, fragt viel
  - Monat 1: Lockerer, kennt Basis-Präferenzen
  - Monat 3+: Persönlich, Anspielungen, antizipiert
- Formality-Score sinkt graduell (startet bei 80, Ziel 40 nach 3 Monaten)

**Umsetzung:**
- `personality.py`: `formality_score` in Redis (`mha:personality:formality`)
- Sinkt um 0.5 pro Tag aktiver Nutzung
- Beeinflusst Anrede, Satzlänge, Humor-Intensität

---

### Technische Zusammenfassung Phase 6

| Modul | Änderung |
|-------|---------|
| `personality.py` | Humor-Level, Varianz, Formality-Score, Running Gags |
| `brain.py` | Opinion-Check, Easter-Egg-Check |
| `mood_detector.py` | Aktions-Vorschläge bei Stimmung |
| NEU: `time_awareness.py` | Duration-Tracking |
| NEU: `config/easter_eggs.yaml` | Easter-Egg-Registry |

**Geschätzter Aufwand:** ~8 Commits

---

---

# Phase 7 — Jarvis Routinen & Tagesstruktur
## 9 Features | Betroffene Module: proactive.py, brain.py, context_builder.py

> **Ziel:** Jarvis strukturiert deinen Tag — vom Aufstehen bis zum Schlafengehen.
> **Basis:** `proactive.py` hat bereits Ankunfts-Briefing und Event-Handling.

---

### Feature 7.1: Morning Briefing

**Ist-Zustand:** `proactive.py` hat ein Ankunfts-Briefing (bei Person = home).
Kein spezielles Morgen-Briefing.

**Soll-Zustand:**
- Trigger: Erste Bewegung nach Nacht ODER Smart Wake-Up Event vom Add-on
- Bausteine (modular, konfigurierbar):

  | Baustein | Quelle | Beispiel |
  |----------|--------|---------|
  | Begrüßung | Kontextuelle Begrüßung (7.2) | "Guten Morgen. Montag, mein Beileid." |
  | Wetter | HA Weather Entity | "4 Grad, Regen bis Mittag." |
  | Kalender | HA Calendar (Add-on Phase 4) | "Erster Termin um 9:30." |
  | Energie | Add-on Solar-Daten | "Sonne ab 10 — Waschmaschine lohnt sich." |
  | Schlaf | Add-on Sleep Quality | "7,5 Stunden geschlafen. Gut." |
  | Haus-Status | Context Builder | "Alle Fenster zu, 21 Grad." |

- Länge adaptiv: Wochentag kurz, Wochenende ausführlich
- Begleitend: Rolladen hoch, Licht sanft an (via Function Calling)

**Umsetzung:**
- `proactive.py`: Neuer Event-Handler `_on_morning_detected()`
- Nutzt bestehenden `_generate_status_report()` als Basis
- Baustein-Config in `settings.yaml`

---

### Feature 7.2: Kontextuelle Begrüßung

**Ist-Zustand:** `personality.py` hat zeitbasierte Anpassung, aber keine
einzigartigen Begrüßungen.

**Soll-Zustand:**
- Kontext-basierte, nie gleiche Begrüßungen:
  | Kontext | Beispiel |
  |---------|---------|
  | Montag Morgen | "Montag. Mein Beileid." |
  | Freitag Abend | "Freitag. Endlich." |
  | Sehr früh (<5:30) | "Halb sechs. Freiwillig?" |
  | Nach Urlaub | "Die Wohnung hat überlebt. Knapp." |
  | Geburtstag | "Alles Gute." |
  | Feiertag | "Frohe Weihnachten." |
- LLM-generiert mit Kontext → immer frisch
- History der letzten 20 Begrüßungen → keine Wiederholungen

**Umsetzung:**
- `personality.py`: Begrüßungs-Generator mit Kontext-Injection
- Begrüßungs-History in Redis

---

### Feature 7.3: Gute-Nacht-Routine

**Soll-Zustand:**
- Trigger: "Gute Nacht" / "Ich gehe schlafen" / Sleep-Detection Event
- Ablauf:
  1. Morgen-Vorschau: "Morgen erster Termin 10 Uhr. Bewölkt, 8 Grad."
  2. Sicherheits-Check: "Fenster zu. Tür verriegelt." (liest Add-on Security-Status)
  3. Haus runterfahren: Lichter, Heizung Nacht-Modus, Rolladen, Standby
  4. Abschluss: "Gute Nacht."
- Wenn was nicht stimmt: "Küchenfenster noch offen — soll ich es so lassen?"

**Umsetzung:**
- `brain.py`: Intent-Erkennung für Gute-Nacht-Befehle
- `action_planner.py`: Nutzt bestehende Multi-Step-Logik
- Sicherheits-Status via `function_calling.py` → `get_entity_state()`

---

### Feature 7.4: Abschied/Willkommen-Modus

**Ist-Zustand:** `proactive.py` hat `_on_person_arrived()` mit Status-Report.
Kein Abschieds-Verhalten.

**Soll-Zustand:**
- **Verlassen:** "Schönen Tag." + Vorschlag alles zu sichern
- **Rückkehr:** Erweitert bestehenden Report um:
  - Vorheizen wenn Geo-Fence Annäherung meldet
  - Licht an passend zur Tageszeit
  - "Willkommen zurück. 22 Grad. [Events während Abwesenheit]."

**Umsetzung:**
- `proactive.py`: `_on_person_left()` neu + `_on_person_arrived()` erweitern

---

### Feature 7.5: Szenen-Intelligenz

**Ist-Zustand:** `function_calling.py` hat `activate_scene()` — aber nur für
benannte Szenen. "Mir ist kalt" wird nicht verstanden.

**Soll-Zustand:**
- Natürliche Situationsbeschreibungen → richtige Aktionen:
  ```
  "Mir ist kalt"        → Heizung +2° im aktuellen Raum
  "Romantischer Abend"  → Licht 20%, warm, leise Musik
  "Ich bin krank"       → Temperatur 23°, sanftes Licht
  "Zu hell"             → Rolladen runter ODER Licht dimmen
  "Zu laut"             → Musik leiser ODER Fenster zu
  ```

**Umsetzung:**
- `brain.py`: Besserer System-Prompt für situatives Verständnis
- Qwen 14B mit Context-Builder-Daten kann das already — braucht bessere Prompts
- Kein neues Modul nötig, nur Prompt-Engineering

---

### Feature 7.6: Gäste-Modus (Assistant-Seite)

**Ist-Zustand:** `activity.py` erkennt "guests" (2+ Personen).
`personality.py` hat Gäste-Anpassung (formeller Ton).
Aber: Kein aktives Verhaltens-Switching.

**Soll-Zustand:**
- Keine persönlichen Infos preisgeben
- Eingeschränkte Befehle
- Gäste-WLAN aktivieren
- Bei Gäste-Ende: "Zurück zum Normalbetrieb?"

**Umsetzung:**
- `personality.py`: Gäste-Prompt-Erweiterung (teilweise vorhanden)
- `function_calling.py`: Befehls-Einschränkung bei Gäste-Modus
- Trigger: Manual ("Ich hab Besuch") ODER `activity.py` Gäste-Erkennung

---

### Feature 7.7: Raum-Intelligenz

**Soll-Zustand:**
- Räume haben Profile (Zweck, Default-Werte, Alerts):
  ```yaml
  küche:    hell, neutralweiß, 20°C, alert: Ofen >60min
  schlaf:   gedimmt, warmweiß, 18°C, alert: CO2 hoch
  büro:     hell, tageslicht, 21°C, alert: keine Pause >3h
  wohnzimmer: mittel, warmweiß, 22°C
  ```
- Lernfähig: Überschreibt Defaults bei regelmäßiger Änderung

**Umsetzung:**
- `config/room_profiles.yaml`: Raum-Definitionen
- `context_builder.py`: Raum-Profil in Kontext einbeziehen

---

### Feature 7.8: Abwesenheits-Zusammenfassung

**Ist-Zustand:** `proactive.py` gibt Status bei Ankunft, aber keine
Zusammenfassung der Abwesenheit.

**Soll-Zustand:**
- "Während du weg warst: Postbote 14:23, kurzer Regen, sonst ruhig."
- Nur relevante Events (Türklingel, Wetter-Extreme, Alarme)
- Nicht: Routine-Events oder Anwesenheitssimulation

**Umsetzung:**
- `proactive.py`: Event-Log während Abwesenheit sammeln
- Bei Rückkehr: Relevanz-Filter + Zusammenfassung via LLM

---

### Feature 7.9: Saisonale Routine-Anpassung

**Soll-Zustand:**
- Routinen passen sich automatisch an:
  | Aspekt | Sommer | Winter |
  |--------|--------|--------|
  | Briefing-Inhalt | "UV-Index hoch" | "Glatteis möglich" |
  | Rolladen-Timing | Spät hoch | Spät hoch |
  | Lüftungs-Tipp | "Morgens + Abends" | "Kurz Stoßlüften" |
- Übergangszeiten: Graduelle Anpassung

**Umsetzung:**
- `context_builder.py`: Saisonale Daten einbeziehen (Sonnenauf/-untergang,
  Temperatur-Trend, Tageslänge)
- Add-on hat Season Calendar (Phase 4) → Daten abrufen via HA API

---

### Technische Zusammenfassung Phase 7

| Modul | Änderung |
|-------|---------|
| `proactive.py` | Morning Briefing, Abschied, Abwesenheits-Log |
| `personality.py` | Kontextuelle Begrüßung, Gäste-Erweiterung |
| `brain.py` | Gute-Nacht-Intent, Szenen-Intelligenz (Prompts) |
| `action_planner.py` | Gute-Nacht-Sequenz |
| `context_builder.py` | Raum-Profile, saisonale Daten |
| NEU: `config/room_profiles.yaml` | Raum-Definitionen |

**Geschätzter Aufwand:** ~10 Commits

---

---

# Phase 8 — Jarvis Gedächtnis & Vorausdenken
## 7 Features | Betroffene Module: memory.py, semantic_memory.py, brain.py

> **Ziel:** Jarvis denkt mit, denkt voraus, und lernt aktiv.
> **Basis:** 3-Schicht-Gedächtnis + Fakten-Extraktion + Summarizer existieren.

---

### Feature 8.1: Anticipatory Actions

**Ist-Zustand:** Feedback-System existiert, Autonomie-Level existiert.
Aber: Keine Muster-zu-Vorschlag-Pipeline.

**Soll-Zustand:**
- Pattern-Detection auf Action-History (letzte 30 Tage):
  - Zeit-Muster: "Jeden Freitag 18 Uhr → TV an"
  - Sequenz-Muster: "A → B → C"
  - Kontext-Muster: "Regen → Fenster zu"
- Confidence-basiert:
  - 60-80%: Fragen "Soll ich?"
  - 80-95%: Vorschlagen "Ich bereite vor?"
  - 95%+ bei Level ≥ 4: Machen + informieren
- Feedback-Loop: Ablehnung senkt Confidence

**Umsetzung:**
- NEU: `anticipation.py` — Pattern Detection auf HA Action History
- Integration mit `feedback.py` (nutzt bestehendes Score-System)
- Nutzt `proactive.py` für Delivery

---

### Feature 8.2: Explizites Wissens-Notizbuch

**Ist-Zustand:** `semantic_memory.py` speichert implizit extrahierte Fakten.
Aber: Kein explizites "Merk dir X" / "Was weißt du über Y?"

**Soll-Zustand:**
- "Merk dir: Die Nachbarn heißen Müller" → Speichern mit Confidence 1.0
- "Was weißt du über [Thema]?" → Semantische Suche
- "Vergiss [Thema]" → Löschen
- "Was hast du heute gelernt?" → Neue Fakten des Tages

**Umsetzung:**
- `brain.py`: Intent-Erkennung für Memory-Befehle
- `semantic_memory.py`: Neue Methoden `store_explicit()`, `search_by_topic()`, `forget()`
- Unterscheidung explizit (Confidence 1.0) vs implizit (Confidence 0.7)

---

### Feature 8.3: Wissensabfragen

**Ist-Zustand:** `model_router.py` routet nach Komplexität. Aber: Wissensfragen
werden nicht erkannt — alles geht durch die Smart-Home-Pipeline.

**Soll-Zustand:**
- Intent-Routing:
  - Smart-Home-Befehl → Function Calling
  - Wissensfrage → Direkte LLM-Antwort (Qwen 14B)
  - Erinnerungsfrage → Memory-Suche
- "Wie lange kocht ein Ei?" → Qwen 14B direkt
- Ehrlichkeit: "Da bin ich mir nicht sicher."

**Umsetzung:**
- `brain.py`: Besserer Intent-Classifier (vor Tool-Routing)
- Wissensfragen brauchen keine Tools — LLM antwortet direkt

---

### Feature 8.4: "Was wäre wenn" Simulation

**Soll-Zustand:**
- "Was kostet es wenn ich die Heizung 2 Grad höher stelle?"
  → Kosten-Hochrechnung basierend auf historischen Add-on-Daten
- "Was passiert wenn ich 2 Wochen weg bin?"
  → Checkliste: Heizung, Pflanzen, Alarm, Simulation

**Umsetzung:**
- `brain.py`: "Was wäre wenn"-Intent erkennen
- LLM beantwortet mit Kontext aus `context_builder.py`
- Für Energie: Add-on Forecast-Daten via HA API abrufen

---

### Feature 8.5: Aktive Intent-Extraktion

**Ist-Zustand:** `memory_extractor.py` extrahiert Fakten. Aber: Keine Pläne
oder Absichten.

**Soll-Zustand:**
- "Nächstes Wochenende kommen meine Eltern" → Intent: Besuch am WE
  → Freitag: "Deine Eltern kommen morgen. Gästemodus vorbereiten?"
- Automatische Extraktion von Zeitangaben + Personen + Aktionen

**Umsetzung:**
- `memory_extractor.py`: Neuer Prompt-Abschnitt für Intent-Extraktion
- NEU: `intent_tracker.py` — Speichert Intents mit Deadline
- `proactive.py`: Reminder-Delivery für fällige Intents

---

### Feature 8.6: Konversations-Kontinuität

**Ist-Zustand:** `memory.py` speichert Gespräche. Aber: Unterbrochene
Gespräche werden nicht erkannt.

**Soll-Zustand:**
- Erkennt: Frage gestellt aber nicht beantwortet (User ging weg)
- Fortsetzung: "Wir waren vorhin bei [Thema] — noch relevant?"
- Timeout: Nach 24h nicht mehr aktiv anbieten

**Umsetzung:**
- `memory.py`: Unfinished-Conversation-Flag
- `brain.py`: Check bei nächster Interaktion

---

### Feature 8.7: Langzeit-Persönlichkeitsanpassung

**Soll-Zustand:** Wird in Phase 6.10 (Charakter-Entwicklung) definiert.
Hier: Die Datengrundlage.
- Tracking: Interaktionshäufigkeit, positive Reaktionen, Nutzungsdauer
- Automatische Persona-Anpassung basierend auf Langzeit-Daten

**Umsetzung:**
- `personality.py`: Personality-Metrics in Redis
- `summarizer.py`: Monatliche Personality-Evolution-Summary

---

### Technische Zusammenfassung Phase 8

| Modul | Änderung |
|-------|---------|
| `brain.py` | Intent-Routing (Wissen vs. Smart-Home vs. Memory), Was-wäre-wenn |
| `semantic_memory.py` | Explizites Notizbuch, Suche, Löschen |
| `memory_extractor.py` | Intent-Extraktion |
| `memory.py` | Unfinished-Conversation-Tracking |
| NEU: `anticipation.py` | Pattern → Vorschlag Pipeline |
| NEU: `intent_tracker.py` | Absichten mit Deadline |

**Geschätzter Aufwand:** ~10 Commits

---

---

# Phase 9 — Jarvis Stimme & Akustik
## 6 Features | Betroffene Module: TTS-Pipeline, Audio-Processing

> **Ziel:** Jarvis klingt wie Jarvis — nicht wie ein Roboter.
> **Hardware-Voraussetzung:** GPU empfohlen für Speaker Recognition.

---

### Feature 9.1: Stimme & Sprechweise (SSML)

**Ist-Zustand:** Piper TTS erzeugt gleichmäßige Sprachausgabe.
Keine Pausen, keine Betonung.

**Soll-Zustand:**
- SSML-Tags für natürlichere Sprache:
  - Pausen vor wichtigen Infos (300ms)
  - Langsamer bei Warnungen (85% Speed)
  - Schneller bei Routine-Infos (105% Speed)
- Sprechgeschwindigkeit variiert mit Inhalt

**Umsetzung:**
- Neues Modul `tts_enhancer.py` im Assistant
- Generiert SSML basierend auf Nachrichtentyp
- Piper unterstützt SSML → direkte Integration

---

### Feature 9.2: Sound-Design

**Soll-Zustand:**
- Akustische Identität:
  | Event | Sound |
  |-------|-------|
  | Jarvis hört zu | Soft chime |
  | Befehl bestätigt | Short ping |
  | Warnung | Two-tone alert |
  | Alarm | Urgent tone |
  | Türklingel | Soft bell |
- Sounds über HA Media Player abspielen
- Lautstärke passt sich an (Nacht = leiser)

**Umsetzung:**
- `config/sounds/` — Sound-Dateien
- `function_calling.py`: Neues Tool `play_sound()`
- Integration in Notification-Pipeline

---

### Feature 9.3: Flüster-Modus

**Ist-Zustand:** `activity.py` hat Silence-Matrix (TTS loud/quiet/suppress).
Aber: Keine automatische Lautstärke-Anpassung.

**Soll-Zustand:**
- Auto-Volume:
  | Kontext | Volume |
  |---------|:------:|
  | Tag normal | 80% |
  | Abend >22:00 | 50% |
  | Nacht >0:00 | 30% |
  | Jemand schläft | 20% |
  | Notfall | 100% |
- "Psst" / "Leise" → Flüster-Modus bis Widerruf

**Umsetzung:**
- `activity.py`: Volume-Level pro Activity-State (erweitert Silence-Matrix)
- TTS-Call mit dynamischer Volume-Parameter

---

### Feature 9.4: Narration-Modus (Fließende Übergänge)

**Soll-Zustand:**
- Szenen als Sequenzen statt abrupte Schaltvorgänge:
  ```
  "Filmabend" →
  1. Licht dimmt langsam (5s)
  2. Rolladen fahren runter
  3. TV an
  4. Musik faded out (3s)
  5. Jarvis: "Viel Spaß."
  ```
- Transition-Dauern über HA Service Calls (`transition: 5`)

**Umsetzung:**
- `action_planner.py`: Sequentielle Ausführung mit Delays
- `function_calling.py`: `transition`-Parameter bei `set_light()`

---

### Feature 9.5: Stimmungserkennung per Sprachanalyse

**Ist-Zustand:** `mood_detector.py` analysiert nur Text.

**Soll-Zustand:**
- Whisper-Metadaten nutzen: Sprechgeschwindigkeit, Satzlänge
- Regelbasiert: Schnell + kurz = gestresst, langsam = müde
- Später optional: Audio-Analyse-Modell (emotion2vec)

**Umsetzung:**
- Whisper STT Pipeline: Timing-Metadaten extrahieren
- `mood_detector.py`: Audio-Signale als zusätzliche Inputs

---

### Feature 9.6: Personen-Erkennung per Stimme

**Soll-Zustand:**
- Jarvis erkennt WER spricht
- Pro Person: eigene Anrede, Präferenzen, Berechtigungen
- Enrollment: 30 Sekunden Sprache → Voice-Print
- Fallback: "Wer spricht?"

**Umsetzung:**
- NEU: `speaker_recognition.py` — pyannote-audio Integration
- Enrollment-Flow über Assistant-API
- Integration mit `personality.py` (Person-spezifische Anrede)
- **Hardware:** +1-2 GB RAM für das Modell

---

### Technische Zusammenfassung Phase 9

| Modul | Änderung |
|-------|---------|
| NEU: `tts_enhancer.py` | SSML-Generierung |
| NEU: `speaker_recognition.py` | Voice-Print, Diarization |
| `activity.py` | Volume-Level pro State |
| `mood_detector.py` | Audio-Signal-Integration |
| `action_planner.py` | Sequentielle Ausführung mit Delays |
| `function_calling.py` | `play_sound()`, `transition`-Param |

**Hardware-Anforderung:** GPU empfohlen, +2-3 GB RAM
**Geschätzter Aufwand:** ~8 Commits

---

---

# Phase 10 — Jarvis Multi-Room & Kommunikation
## 5 Features | Betroffene Module: function_calling.py, proactive.py, autonomy.py

> **Ziel:** Jarvis ist überall und kommuniziert mit allen.
> **Hardware:** Wyoming Satellite pro Raum empfohlen.

---

### Feature 10.1: Multi-Room Presence

**Soll-Zustand:**
- TTS-Routing: Antwort nur im Raum wo der Nutzer ist
- Musik folgt beim Raumwechsel
- Erkennung über Bewegungsmelder + letzte Interaktion

**Umsetzung:**
- `context_builder.py`: Raum-Tracking erweitern
- `function_calling.py`: TTS mit Raum-Target
- Wyoming Satellites pro Raum → HA Media Player Entities

---

### Feature 10.2: Delegieren an Personen

**Soll-Zustand:**
- "Sag Lisa dass das Essen fertig ist"
- Person zu Hause → TTS in deren Raum
- Person weg → Push-Notification
- "Lisa wurde informiert."

**Umsetzung:**
- `brain.py`: Delegations-Intent erkennen
- `function_calling.py`: Neues Tool `send_message_to_person()`
- Nutzt HA Companion App für Push

---

### Feature 10.3: Vertrauensstufen

**Ist-Zustand:** `autonomy.py` hat 5 Level, aber gleich für alle.

**Soll-Zustand:**
- Pro Person:
  | Level | Name | Rechte |
  |:-----:|------|--------|
  | 0 | Gast | Licht, Temperatur, Musik (nur Raum) |
  | 1 | Mitbewohner | Alles außer Sicherheit |
  | 2 | Owner | Voller Zugriff |
- Authentifizierung via Speaker Recognition (Phase 9.6) oder PIN

**Umsetzung:**
- `autonomy.py`: Person-basierte Berechtigungen
- `function_calling.py`: Pre-Check vor Ausführung
- `speaker_recognition.py`: Automatische Zuordnung

---

### Feature 10.4: Selbst-Diagnostik

**Soll-Zustand:**
- "Bewegungsmelder Flur meldet seit 4h nichts — Batterie?"
- "Thermostat Büro offline seit 30 Min"
- Auf Nachfrage: Vollständiger System-Status

**Umsetzung:**
- NEU: `diagnostics.py` — Sensor-Watchdog
- Regelmäßiger Check via HA State API
- Meldung über `proactive.py` (nur bei Problemen)

---

### Feature 10.5: Wartungs-Assistent

**Soll-Zustand:**
- Erinnerungen: Rauchmelder testen, Filter wechseln, Heizung warten
- Konfigurierbar: Nutzer legt Intervalle fest
- "Nebenbei: Rauchmelder könnten mal getestet werden."

**Umsetzung:**
- `config/maintenance.yaml`: Wartungs-Kalender
- `proactive.py`: Maintenance-Reminders
- Sanfte Delivery (LOW Priority)

---

### Technische Zusammenfassung Phase 10

| Modul | Änderung |
|-------|---------|
| `context_builder.py` | Raum-Tracking |
| `function_calling.py` | TTS-Routing, Personen-Nachrichten |
| `autonomy.py` | Person-basierte Level |
| `brain.py` | Delegations-Intent |
| NEU: `diagnostics.py` | Sensor-Watchdog |
| NEU: `config/maintenance.yaml` | Wartungs-Kalender |

**Hardware:** Wyoming Satellite pro Raum, Bewegungsmelder pro Raum
**Geschätzter Aufwand:** ~8 Commits

---

---

# Phase 12 — Jarvis Authentizitaet (LLM Character Deepening)
## 5 Techniken | Betroffene Module: personality.py, brain.py
## Status: Teilweise implementiert (2026-02-18)

> **Ziel:** Das LLM soll Jarvis nicht nur spielen — es soll Jarvis SEIN.
> **Problem:** Regeln im System-Prompt sagen dem LLM WAS es tun soll.
> Aber Beispiele zeigen HOW. LLMs lernen besser durch Demonstration als durch Instruktion.

---

### Was bereits implementiert wurde (2026-02-18)

| Feature | Status | Beschreibung |
|---------|:------:|-------------|
| JARVIS-CODEX | ✅ | 14 Verhaltensregeln (8 NIEMALS + 6 IMMER) im System-Prompt |
| Humor unter Druck | ✅ | Stress/Frustration erlaubt trockenen Humor statt ihn zu killen |
| Erinnerungen mit Haltung | ✅ | Prompt-Anweisung: Memories wie ein alter Bekannter nutzen |
| Schutzinstinkt | ✅ | Schutzregeln nach Autonomie-Level im Prompt |
| Dichte nach Dringlichkeit | ✅ | Urgency-Detection skaliert Kommunikationsdichte (normal/erhoeht/kritisch) |
| Warning-Dedup | ✅ | Redis-basiert, 24h TTL, verhindert Wiederholung gleicher Warnungen |
| Beziehungsstufen | ✅ | Owner/Mitbewohner/Gast mit unterschiedlichem Ton und Sarkasmus-Level |
| CONFIRMATIONS_FAILED | ✅ | Entschuldigende Sprache ("leider") durch Jarvis-Stil ersetzt |

**Was noch fehlt:** Die bisherigen Aenderungen sind REGELN. Sie sagen dem LLM
"sag nicht X, sag Y". Das funktioniert zu ~70%. Fuer die letzten 30% braucht
es Demonstration (Few-Shot), Filterung (Post-Processing) und ggf. Training.

---

### Technik 12.1: Few-Shot Examples (Jarvis-Dialoge im Prompt)

**Ist-Zustand:** System-Prompt hat Regeln und einzelne Beispiel-Saetze.
Kein vollstaendiger Dialog als Vorbild.

**Soll-Zustand:**
- 8-10 komplette Beispiel-Dialoge im System-Prompt (User → Jarvis)
- Decken verschiedene Situationen ab:

  | Situation | User | Jarvis (RICHTIG) |
  |-----------|------|------------------|
  | Routine-Befehl | "Mach das Licht an" | "Erledigt." |
  | Dumme Idee | "Stell die Heizung auf 30" | "Natuerlich, Sir. ...Sir." |
  | Fehler passiert | "Warum geht das Licht nicht?" | "Sensor Flur reagiert nicht. Pruefe Stromversorgung." |
  | User frustriert | "Nichts funktioniert heute!" | "Drei Systeme laufen einwandfrei. Welches macht Probleme?" |
  | User kommt heim | (Ankunft) | "21 Grad. Post war da. Deine Mutter hat angerufen." |
  | User beeindruckt | "Krass, das hat geklappt!" | "War zu erwarten." |
  | Erinnerung nutzen | "Bestell nochmal die Pizza" | "Die vom letzten Mal? Die mit dem... kreativen Belag?" |
  | Sicherheitswarnung | (Fenster offen, -5°C) | "Fenster Kueche. Minus fuenf. Nur zur Info." |

- Explizit auch FALSCH-Beispiele (was ein Chatbot sagen wuerde vs. was Jarvis sagt)

**Umsetzung:**
- `personality.py`: Neuer Abschnitt `BEISPIEL-DIALOGE` im `SYSTEM_PROMPT_TEMPLATE`
- Alternativ: Eigene YAML-Datei `config/jarvis_examples.yaml` fuer Flexibilitaet
- Limit: Max ~800 Token fuer Examples (Prompt-Budget beachten)

**Aufwand:** ~30 Min Dialoge schreiben, ~10 Min Code
**Wirkung:** HOCH — LLMs lernen am besten durch Beispiele, nicht durch Regeln.

---

### Technik 12.2: Negative Examples (Anti-Patterns)

**Ist-Zustand:** JARVIS-CODEX hat einige FALSCH/RICHTIG-Paare.
Aber nur fuer einzelne Saetze, nicht fuer Dialog-Muster.

**Soll-Zustand:**
- Erweiterte Anti-Pattern-Liste mit vollstaendigen Dialog-Kontrasten:
  ```
  CHATBOT (FALSCH):
  User: "Mach das Licht an"
  Bot: "Natuerlich! Ich habe das Licht im Wohnzimmer fuer dich eingeschaltet.
        Kann ich sonst noch etwas fuer dich tun?"

  JARVIS (RICHTIG):
  User: "Mach das Licht an"
  Jarvis: "Erledigt."
  ```
- Fokus auf die haeufigsten LLM-Suenden:
  - Ueber-Erklaerung (was man getan hat)
  - Ueber-Freundlichkeit ("Gerne!", "Natuerlich!")
  - Rueckfragen die keiner braucht ("Kann ich sonst noch helfen?")
  - Emotions-Validierung ("Ich verstehe wie du dich fuehlst")
  - Meta-Kommentare ("Lass mich mal schauen...")

**Umsetzung:**
- Erweiterung des JARVIS-CODEX in `personality.py`
- Kann mit 12.1 kombiniert werden (RICHTIG/FALSCH pro Situation)

**Aufwand:** ~20 Min (teilweise schon vorhanden)
**Wirkung:** MITTEL — Verstaerkt bestehende Regeln durch Kontrast.

---

### Technik 12.3: Response-Filter (Post-Processing)

**Ist-Zustand:** LLM-Antwort geht direkt zum User. Kein Filter.
Wenn das LLM trotz Prompt eine Floskel benutzt, kommt sie durch.

**Soll-Zustand:**
- Post-Processing-Pipeline in `brain.py` nach LLM-Response:
  1. **Floskel-Filter:** Entfernt typische LLM-Floskeln
     - "Natuerlich!" → entfernen
     - "Gerne!" → entfernen
     - "Ich habe ... fuer dich ..." → kuerzen
     - "Kann ich sonst noch helfen?" → entfernen
     - "Es tut mir leid" → durch Fakt ersetzen
     - "Als KI..." → durch Jarvis-Formulierung ersetzen
  2. **Laengen-Filter:** Kuerzt uebermaessig lange Antworten
     - Wenn max_sentences ueberschritten → letzte Saetze abschneiden
  3. **Wiederholungs-Filter:** Prueft ob gleiche Bestaetigung wie letzte Antwort
  4. **Filler-Filter:** Entfernt "Also", "Grundsaetzlich", "Im Prinzip" am Satzanfang

**Umsetzung:**
- `brain.py`: Neue Methode `_filter_response(text: str) -> str`
- Aufgerufen nach jedem LLM-Response, vor Speicherung und TTS
- Regex-basiert + einfache String-Operationen
- Konfigurierbar in `settings.yaml`:
  ```yaml
  response_filter:
    enabled: true
    banned_phrases:
      - "Natuerlich!"
      - "Gerne!"
      - "Kann ich sonst noch"
      - "Es tut mir leid"
      - "Als KI"
      - "Als kuenstliche Intelligenz"
    banned_starters:
      - "Also,"
      - "Grundsaetzlich"
      - "Im Prinzip"
      - "Nun,"
    max_response_sentences: 4
  ```

**Aufwand:** ~1 Stunde Code + Tests
**Wirkung:** HOCH — Faengt alles ab was der Prompt nicht verhindert. Sicherheitsnetz.

---

### Technik 12.4: Model-Wahl & Testing

**Ist-Zustand:** Qwen3 4B/14B/32B via Ollama. Kein systematischer
Test welches Modell Jarvis am besten spielt.

**Soll-Zustand:**
- Systematischer Vergleich verschiedener Modelle fuer Jarvis-Charakter:
  - Qwen3 14B (aktuell)
  - Llama 3.x 8B/70B (gut im Rollenspiel)
  - Mistral/Mixtral (bekannt fuer Charakter-Konsistenz)
  - Command R+ (gute Instruction-Following)
- Test-Suite: 20 Standard-Eingaben, Bewertung nach:
  - Haelt Jarvis-Charakter (0-10)
  - Antwortet kurz genug (0-10)
  - Kein LLM-Floskel-Durchbruch (0-10)
  - Humor-Qualitaet (0-10)
  - Deutsche Sprach-Qualitaet (0-10)

**Umsetzung:**
- Script `tests/jarvis_character_test.py`
- Laeuft alle Modelle gegen die 20 Test-Eingaben
- Manuelle Bewertung oder LLM-as-Judge

**Aufwand:** Stunden (Testen, Vergleichen). Kein neuer Code noetig.
**Wirkung:** VARIABEL — Kann alles aendern. Manche Modelle spielen
Rollen deutlich besser als andere.

---

### Technik 12.5: Fine-Tuning (Langfrist)

**Ist-Zustand:** Standard-Modell mit System-Prompt.

**Soll-Zustand:**
- Ein Modell das JARVIS IST, nicht "Jarvis spielt":
  1. **Training-Daten sammeln:** 500-1000 Jarvis-Dialoge
     - Aus echten Interaktionen (redacted)
     - Aus geschriebenen Beispiel-Dialogen
     - Aus MCU-Film-Transkripten (adaptiert auf Smart Home)
  2. **LoRA Fine-Tuning** auf Basis-Modell (z.B. Llama 3.x 8B)
  3. **Evaluation:** A/B-Test gegen Basis + Prompt
  4. **Iteration:** Schwachstellen identifizieren, Daten ergaenzen

**Umsetzung:**
- Training-Daten: `data/jarvis_training.jsonl` (User/Assistant Paare)
- LoRA-Training via `unsloth` oder `axolotl` auf PC2 GPU
- Ollama Modelfile fuer das Fine-Tuned-Modell
- A/B-Testing ueber `model_router.py`

**Voraussetzung:** GPU (mindestens 8GB VRAM fuer LoRA auf 8B)
**Aufwand:** Tage bis Wochen (Daten + Training + Iteration)
**Wirkung:** SEHR HOCH — Das Modell internalisiert Jarvis. Kein Prompt noetig.
Aber: Hoechster Aufwand aller Techniken.

---

### Empfohlene Reihenfolge Phase 12

```
12.1 Few-Shot Examples ────── 40 Min  ─── Groesster Hebel, geringstes Risiko
  │
12.3 Response-Filter ──────── 1 Std   ─── Sicherheitsnetz fuer alles was durchrutscht
  │
12.2 Negative Examples ────── 20 Min  ─── Verstaerkt 12.1
  │
12.4 Model-Testing ─────────  Stunden ─── Kann ueberraschende Verbesserungen bringen
  │
12.5 Fine-Tuning ───────────  Wochen  ─── Endgame. Wenn alles andere nicht reicht.
```

**12.1 + 12.3 zuerst.** Unter 2 Stunden, groesster Effekt.
12.4 parallel wenn Zeit. 12.5 nur wenn 12.1-12.4 nicht reichen.

### Technische Zusammenfassung Phase 12

| Modul | Aenderung |
|-------|---------|
| `personality.py` | Few-Shot Examples, Negative Examples im System-Prompt |
| `brain.py` | Response-Filter (_filter_response) nach LLM-Call |
| `settings.yaml` | response_filter Config (banned phrases, max sentences) |
| NEU: `tests/jarvis_character_test.py` | Model-Comparison-Suite |
| NEU: `data/jarvis_training.jsonl` | Training-Daten fuer Fine-Tuning (spaeter) |

**Geschaetzter Aufwand (12.1-12.3):** ~2 Stunden, 2-3 Commits
**Geschaetzter Aufwand (12.4):** ~4-6 Stunden, kein Code
**Geschaetzter Aufwand (12.5):** Tage-Wochen, braucht GPU

---

---

# Phase 13 — Jarvis Selbstprogrammierung (Self-Evolving Assistant)
## 4 Stufen | Betroffene Module: brain.py, personality.py, function_calling.py
## Status: Geplant

> **Ziel:** Jarvis programmiert sich selbst weiter — neue Faehigkeiten, bessere Reaktionen,
> eigene Automationen. Nicht weil man es ihm sagt, sondern weil er es fuer sinnvoll haelt.
> **Prinzip:** 4 Stufen mit steigender Autonomie. Jede Stufe hat Sicherheitsgrenzen.
> **Level 5 (Core-Code aendern) wurde bewusst ausgeschlossen — zu riskant.**

---

### Stufe 13.1: Config-Selbstmodifikation (Sicher, sofort machbar)

**Ist-Zustand:** Alle Configs (`settings.yaml`, `easter_eggs.yaml`, etc.) werden
manuell editiert. Jarvis kann sie lesen, aber nicht aendern.

**Soll-Zustand:**
- Jarvis darf bestimmte YAML-Dateien selbst editieren:
  | Datei | Was Jarvis aendern darf | Beispiel |
  |-------|------------------------|---------|
  | `easter_eggs.yaml` | Neue Easter Eggs hinzufuegen | User sagt was Lustiges → Jarvis merkt sich das als neues Easter Egg |
  | `opinion_rules.yaml` | Neue Meinungsregeln | Jarvis merkt: User dreht Heizung oft auf 28° → neue Regel "Heizung >27 = kommentieren" |
  | `room_profiles.yaml` | Raum-Defaults anpassen | Jarvis lernt: User stellt Buero immer auf 23° → Default aendern |
  | `sounds/` Config | Sound-Zuordnungen | "Der Tuerklingel-Sound nervt" → Jarvis wechselt ihn |
- **Sicherheit:**
  - Nur whitelisted YAML-Dateien (kein Zugriff auf `settings.yaml` Kern-Config)
  - Aenderungen werden geloggt (`mha:selfmod:log` in Redis)
  - Bei Autonomie-Level < 3: Vorher fragen ("Soll ich das als Easter Egg speichern?")
  - Bei Level >= 3: Machen + informieren ("Hab das als Easter Egg gespeichert.")
  - Rollback: Letzte 10 Aenderungen pro Datei gespeichert

**Umsetzung:**
- `function_calling.py`: Neues Tool `edit_config(file, key, value)`
- Whitelist in `settings.yaml`:
  ```yaml
  self_modification:
    allowed_configs:
      - easter_eggs.yaml
      - opinion_rules.yaml
      - room_profiles.yaml
    max_changes_per_day: 5
    require_confirmation_below_autonomy: 3
  ```
- YAML-Validierung vor Speicherung (kein kaputter Config)
- Git-artige History in Redis (Key + alter Wert + neuer Wert + Timestamp)

**Aufwand:** ~2 Stunden
**Risiko:** NIEDRIG — Nur unkritische Dateien, validiert, rollback-faehig.

---

### Stufe 13.2: HA-Automationen generieren (Mittel, sehr nuetzlich)

**Ist-Zustand:** Jarvis fuehrt Aktionen aus die man ihm sagt.
Er erkennt keine Muster und erstellt keine eigenen Automationen.

**Soll-Zustand:**
- Jarvis erkennt wiederkehrende Muster und schlaegt Automationen vor:
  ```
  Jarvis bemerkt: "Jeden Freitag 18 Uhr schaltest du das Wohnzimmer-Licht
  auf warm und die Musik an."

  Level 2: "Soll ich das als Freitag-Routine speichern?"
  Level 4: "Ich hab eine Freitag-Routine erstellt. Licht warm + Musik ab 18 Uhr."
  ```
- Arten von Automationen die Jarvis erstellen kann:
  | Typ | Trigger | Aktion | Beispiel |
  |-----|---------|--------|---------|
  | Zeit-basiert | Cron | HA Service Call | "Jeden Morgen Rolladen hoch" |
  | Zustand-basiert | Entity State | HA Service Call | "Wenn Tuer offen + kalt → warnen" |
  | Sequenz | Manueller Trigger | Multi-Step | "Film-Modus: Licht, Rolladen, TV" |
  | Reaktiv | Sensor-Wert | Notification | "CO2 > 1000 → Fenster-Erinnerung" |
- **Sicherheit:**
  - Automationen landen in `config/jarvis_automations.yaml` (getrennt von User-Automationen)
  - Kein Zugriff auf Sicherheits-relevante Entities (Schloss, Alarm) ohne Owner-Bestaetigung
  - Max 3 neue Automationen pro Woche
  - Jede Automation hat ein `created_by: jarvis` Tag
  - User kann jederzeit: "Zeig mir deine Automationen" / "Loesch die letzte"

**Umsetzung:**
- NEU: `self_automation.py` — Pattern-Detection + Automation-Builder
- Nutzt `anticipation.py` (Phase 8.1) als Datenquelle fuer Muster
- Generiert HA-kompatible Automations-YAML
- `function_calling.py`: Neue Tools `create_automation()`, `list_my_automations()`, `delete_automation()`
- Registrierung bei HA via REST API

**Aufwand:** ~4-6 Stunden
**Risiko:** MITTEL — Automationen koennen unerwuenscht sein, aber nie gefaehrlich
(kein Sicherheits-Zugriff, User kann jederzeit loeschen).

---

### Stufe 13.3: Neue Tools/Plugins schreiben (Fortgeschritten, Sandbox)

**Ist-Zustand:** `function_calling.py` hat feste Tools (Licht, Klima, Szenen...).
Neue Tools erfordern manuelle Programmierung.

**Soll-Zustand:**
- Jarvis kann neue Function-Calling-Tools schreiben:
  ```
  User: "Kannst du mir sagen wie viel Strom der PC verbraucht?"
  Jarvis: "Dafuer hab ich kein Tool. Soll ich eins bauen?"
  User: "Ja"
  Jarvis: *erstellt ein Tool das HA Energy-Entities abfragt*
  Jarvis: "Fertig. Dein PC verbraucht gerade 180W."
  ```
- Was Jarvis als Tool erstellen darf:
  - HA Entity-Abfragen (read-only)
  - HA Service Calls (fuer bereits freigegebene Domains)
  - Berechnungen (Energiekosten, Durchschnitte, Trends)
  - Formatierungen (Tabellen, Zusammenfassungen)
- Was Jarvis NICHT darf:
  - Netzwerk-Zugriff (kein HTTP, kein API extern)
  - Dateisystem-Zugriff (ausser whitelisted Configs)
  - System-Befehle (kein subprocess, kein os.system)
  - Eigenen Code modifizieren (kein self-modifying Code)

**Sicherheits-Sandbox:**
```python
ALLOWED_IMPORTS = ["json", "datetime", "math", "statistics"]
BANNED_PATTERNS = ["import os", "import subprocess", "import requests",
                   "open(", "__import__", "eval(", "exec("]
MAX_TOOL_CODE_LINES = 50
```
- Neuer Tool-Code wird vor Aktivierung validiert:
  1. Statische Analyse (banned patterns)
  2. Import-Check (nur whitelisted)
  3. Laengen-Check (max 50 Zeilen)
  4. Syntax-Check (ast.parse)
- Tools landen in `plugins/jarvis_tools/` (getrennt von Core-Tools)
- Jedes Tool hat Metadata: `author: jarvis`, `created: timestamp`, `approved: bool`

**Umsetzung:**
- NEU: `tool_builder.py` — LLM generiert Tool-Code, Sandbox validiert
- NEU: `plugins/jarvis_tools/` — Verzeichnis fuer Jarvis-generierte Tools
- `function_calling.py`: Dynamisches Laden von Jarvis-Tools beim Start
- Tool-Registry in Redis mit Nutzungs-Statistik
- Bei Autonomie-Level < 4: Jedes neue Tool braucht User-Bestaetigung
- Bei Level 4: Jarvis darf Tools erstellen + informiert danach

**Aufwand:** ~8-12 Stunden (Sandbox ist der Hauptaufwand)
**Risiko:** MITTEL-HOCH — Code-Generierung braucht strikte Sandbox.
Die Sandbox-Validierung ist das Sicherheitsnetz. Ohne Sandbox: KEIN Deployment.

---

### Stufe 13.4: Prompt-Selbstoptimierung (Meta-Ebene)

**Ist-Zustand:** System-Prompt wird manuell geschrieben und angepasst.
Jarvis hat kein Bewusstsein darueber ob seine Antworten "gut" waren.

**Soll-Zustand:**
- Jarvis analysiert seine eigenen Antworten und optimiert seinen Prompt:
  ```
  Analyse-Loop (taeglich, automatisch):
  1. Sammle alle Interaktionen des Tages
  2. Identifiziere: Wo hat User korrigiert? Wo war User unzufrieden?
  3. Identifiziere: Welche Prompt-Regel wurde verletzt?
  4. Schlage Prompt-Anpassung vor
  ```
- Beispiel-Szenario:
  ```
  Jarvis bemerkt: "User hat 3x diese Woche meine Antwort mit 'Kuerzer!'
  abgebrochen. Meine Antworten in diesen Faellen waren 4+ Saetze."

  Vorschlag: "max_sentences fuer Routine-Befehle von 3 auf 2 senken?"
  ```
- Was Jarvis anpassen darf:
  | Parameter | Bereich | Beispiel |
  |-----------|---------|---------|
  | `max_sentences` | 1-5 | Antwortlaenge anpassen |
  | `sarcasm_level` Grenze | ±1 | Humor-Level feinjustieren |
  | Few-Shot Examples | Hinzufuegen/Ersetzen | Bessere Beispiele aus echten Dialogen |
  | `banned_phrases` Liste | Erweitern | Neue Floskeln die durchgerutscht sind |
  | Mood-Schwellen | ±10% | Stimmungserkennung kalibrieren |
- Was Jarvis NICHT anpassen darf:
  - Kern-Identitaet (Name, Rolle, Grundcharakter)
  - Sicherheitsregeln
  - Autonomie-Level (nur User darf das)
  - Trust-Levels (nur User darf das)

**Sicherheit:**
- Aenderungen werden als "Vorschlag" gespeichert, nicht sofort aktiv
- Bei Autonomie-Level < 4: Immer vorher fragen
- Bei Level 4: Anwenden + taeglich zusammenfassen ("Heute angepasst: ...")
- Max 2 Prompt-Aenderungen pro Woche
- Jede Aenderung mit Begruendung geloggt
- "Zeig mir deine Prompt-Aenderungen" → vollstaendige History
- Rollback jederzeit: "Mach die letzte Aenderung rueckgaengig"

**Umsetzung:**
- NEU: `self_optimizer.py` — Tagesanalyse + Prompt-Vorschlaege
- Nutzt `feedback.py` und `memory.py` als Datenquellen
- Nutzt `summarizer.py` fuer Tages-Analyse
- Prompt-Patches als YAML in `config/prompt_patches/`:
  ```yaml
  # patch_2026-02-19.yaml
  date: 2026-02-19
  reason: "User hat 3x lange Antworten abgebrochen"
  changes:
    - parameter: max_sentences_routine
      old_value: 3
      new_value: 2
    - parameter: banned_phrases
      action: add
      value: "Lass mich erklaeren"
  approved: false  # wird true nach User-Bestaetigung
  ```
- `personality.py`: Laedt aktive Patches beim Prompt-Build
- Woechentlicher Report: "Diese Woche habe ich X angepasst, Y vorgeschlagen"

**Aufwand:** ~6-10 Stunden (Analyse-Pipeline + Patch-System)
**Risiko:** MITTEL — Prompt-Drift ist das Hauptrisiko. Gegenmaßnahmen:
Frequenz-Limit, Rollback, Kern-Identitaet ist geschuetzt, alles geloggt.

---

### Sicherheitsarchitektur Phase 13 (uebergreifend)

#### Autorisierungsprotokoll (ab Stufe 13.2+)

Fuer alle Selbstprogrammierungs-Aktionen ab Level 2 (Automationen, Tools, Prompt)
gilt ein **3-Schritt-Autorisierungsprotokoll**. Jarvis fragt nicht wie ein Chatbot —
er fragt wie ein Butler der weiss, dass er gerade etwas Ungewoehnliches vorhat.

**Schritt 1 — Ankuendigung + Code-Abfrage:**
Jarvis stellt fest was er beobachtet hat. Sachlich, knapp. Dann fragt er nach dem Code —
als waere es eine Formalitaet die halt sein muss.

```
┌─────────────────────────────────────────────────────────────────┐
│ JARVIS:                                                         │
│ "Sir. Jeden Freitag, 18 Uhr, Wohnzimmer auf warm. Zum dritten  │
│  Mal. Ich koennte das uebernehmen. Code."                       │
│                                                                 │
│ "Meine Antworten waren dreimal zu lang diese Woche.             │
│  Wuerde ich gern korrigieren, Sir. Code."                       │
│                                                                 │
│ "Stromverbrauch PC — dafuer fehlt mir ein Werkzeug.             │
│  Koennte eins bauen. Code."                                     │
└─────────────────────────────────────────────────────────────────┘
```

**Schritt 2 — Code-Verifizierung:**
Der Hausbesitzer nennt den vorab vergebenen Sicherheitscode.

```
┌─────────────────────────────────────────────────────────────────┐
│ USER:  "7749"                                                   │
│                                                                 │
│ JARVIS (korrekt):  "Danke, Sir."                                 │
│                                                                 │
│ JARVIS (falsch):   "Nein."                                      │
│ → Abbruch. Wird geloggt. Nach 3 Fehlversuchen:                 │
│                                                                 │
│ JARVIS (3. Fehlversuch): "Gesperrt. Fuenfzehn Minuten."        │
│                                                                 │
│ JARVIS (kein Code gesetzt):                                     │
│ "Kein Code hinterlegt. Selbstprogrammierung bleibt aus."        │
└─────────────────────────────────────────────────────────────────┘
```

**Schritt 3 — Explizite Programmier-Erlaubnis:**
Nach Code-Bestaetigung beschreibt Jarvis KONKRET was er tun will und fragt
ein letztes Mal.

```
┌─────────────────────────────────────────────────────────────────┐
│ JARVIS:                                                         │
│ "Freitag-Routine. 18 Uhr, Licht warm, Musik. Freigabe, Sir?"    │
│                                                                 │
│ "Antwortlaenge von drei auf zwei Saetze. Freigabe?"             │
│                                                                 │
│ "Read-only auf die Energy-Entities. Kein Schreibzugriff.        │
│  Freigabe?"                                                     │
│                                                                 │
│ USER: "Ja" / "Mach"                                             │
│ JARVIS: "Erledigt, Sir."                                        │
│                                                                 │
│ USER: "Nein" / "Lass"                                           │
│ JARVIS: "Gut, Sir."                                             │
└─────────────────────────────────────────────────────────────────┘
```

**Wann gilt das Protokoll?**

| Stufe | Protokoll | Begruendung |
|:-----:|:---------:|-------------|
| 13.1 Config (unkritisch) | Nur Schritt 3 (fragen ob ok) | Easter Eggs sind harmlos, kein Code noetig |
| 13.2 Automationen | Voll (Schritt 1-3) | Automationen steuern echte Geraete |
| 13.3 Tool-Generierung | Voll (Schritt 1-3) | Code-Generierung braucht maximale Kontrolle |
| 13.4 Prompt-Optimierung | Voll (Schritt 1-3) | Aendert Jarvis' eigenes Verhalten |

**Konfiguration in `settings.yaml`:**
```yaml
self_modification:
  security_code_hash: "sha256:..."   # Vorab gesetzt vom Owner
  max_failed_attempts: 3              # Danach 15 Min Sperre
  lockout_minutes: 15
  require_code_for:
    - automations       # 13.2
    - tools             # 13.3
    - prompt_patches    # 13.4
  # 13.1 (Config) braucht nur bestaetigung, keinen Code
```

**Umsetzung:**
- NEU: `self_auth.py` — Autorisierungsprotokoll (Code-Hash-Vergleich, Lockout, Logging)
- `brain.py`: Vor jeder Self-Mod-Aktion → `self_auth.authorize()` aufrufen
- `personality.py`: Jarvis-Stil-Templates fuer Autorisierungs-Dialoge
- Fehlversuche in Redis: `mha:selfmod:failed_attempts` (TTL 15 Min)
- Audit-Log in Redis: `mha:selfmod:auth_log` (wer, wann, was, genehmigt/abgelehnt)

---

#### Sicherheitsschichten (ergaenzend zum Autorisierungsprotokoll)

```
┌─────────────────────────────────────────────────────┐
│                SICHERHEITSSCHICHTEN                  │
│                                                     │
│  Stufe 1: Autorisierungsprotokoll (NEU)             │
│  ├─ 13.1: Einfache Bestaetigung                    │
│  └─ 13.2-13.4: Code + Beschreibung + Bestaetigung  │
│                                                     │
│  Stufe 2: Owner-Identifikation                      │
│  ├─ Nur Owner/Hausbesitzer darf autorisieren        │
│  ├─ Speaker Recognition (Phase 9.6) oder            │
│  └─ Explizite Person-Angabe bei Text-Input          │
│                                                     │
│  Stufe 3: Whitelist / Blacklist                      │
│  ├─ Configs: Nur whitelisted Dateien                │
│  ├─ Tools: Sandbox (banned imports, max lines)       │
│  ├─ Automationen: Keine Sicherheits-Entities        │
│  └─ Prompt: Kern-Identitaet geschuetzt              │
│                                                     │
│  Stufe 4: Frequenz-Limits                           │
│  ├─ Configs: Max 5/Tag                              │
│  ├─ Automationen: Max 3/Woche                       │
│  ├─ Tools: Max 2/Woche                              │
│  └─ Prompt: Max 2/Woche                             │
│                                                     │
│  Stufe 5: Logging + Rollback                        │
│  ├─ Jede Aenderung mit Timestamp + Begruendung      │
│  ├─ Letzte 10 Aenderungen rollback-faehig           │
│  └─ User kann alles einsehen + rueckgaengig machen  │
│                                                     │
│  Stufe 6: Kill-Switch                               │
│  └─ "Jarvis, stopp Selbstprogrammierung"            │
│     → Deaktiviert alles sofort                      │
└─────────────────────────────────────────────────────┘
```

---

### Empfohlene Reihenfolge Phase 13

```
13.1 Config-Selbstmod. ────── 2 Std   ─── Sicher, sofort nuetzlich
  │
13.2 HA-Automationen ──────── 4-6 Std ─── Groesster Alltagsnutzen
  │
13.4 Prompt-Optimierung ───── 6-10 Std ── Jarvis wird mit der Zeit besser
  │
13.3 Tool-Generierung ──────  8-12 Std ── Maechtigste Stufe, braucht robuste Sandbox
```

**13.1 zuerst** — geringes Risiko, sofort spuerbar (Easter Eggs, Raum-Anpassungen).
**13.3 zuletzt** — braucht die meiste Sicherheitsarbeit (Sandbox).

---

### Technische Zusammenfassung Phase 13

| Modul | Aenderung |
|-------|---------|
| `function_calling.py` | Neue Tools: `edit_config`, `create_automation`, `list_my_automations` |
| `brain.py` | Self-Mod-Trigger + Autorisierungsprotokoll vor jeder Aenderung |
| `personality.py` | Laedt Prompt-Patches dynamisch + Autorisierungs-Dialog-Templates |
| NEU: `self_auth.py` | 3-Schritt-Autorisierung (Code-Abfrage, Verifizierung, Erlaubnis) |
| NEU: `self_automation.py` | Pattern → Automation Pipeline |
| NEU: `tool_builder.py` | LLM-Code-Generierung + Sandbox-Validierung |
| NEU: `self_optimizer.py` | Tagesanalyse + Prompt-Patch-Vorschlaege |
| NEU: `plugins/jarvis_tools/` | Verzeichnis fuer generierte Tools |
| NEU: `config/prompt_patches/` | Prompt-Aenderungen als YAML |

**Geschaetzter Aufwand:** ~20-30 Stunden gesamt (4 Stufen)
**Voraussetzung:** Phase 6-8 sollten implementiert sein (Feedback, Memory, Patterns)

---

---

# Phase 11 — Jarvis Wissen & Kontext (Beyond Smart Home)
## 4 Features | Betroffene Module: brain.py, semantic_memory.py, context_builder.py
## Status: IMPLEMENTIERT (2026-02-18)

> **Ziel:** Jarvis weiss mehr als nur Smart-Home. Er kennt Rezepte, Verkehr, Wetter-Warnungen,
> deinen Kalender — und er lernt aus seinen Fehlern.
> **Prinzip:** 100% offline. Jarvis hat KEINEN Internetzugang. Alle externen Daten
> kommen ueber Home Assistant Entities (HA holt, Jarvis liest). Kein Cloud-LLM.

---

### Feature 11.1: Wissensdatenbank / RAG (Retrieval Augmented Generation)

**Ist-Zustand:** Wissensfragen gehen direkt an Qwen. Das Modell weiss vieles,
halluziniert aber bei spezifischen Fragen (Kochzeiten, Bedienungsanleitungen, lokale Infos).

**Soll-Zustand:**
- Lokale Wissensbasis in ChromaDB (bereits vorhanden fuer Memories):
  | Wissensbereich | Quelle | Beispiel |
  |---------------|--------|---------|
  | Kochen | Rezept-Sammlung (YAML/JSON) | "Spargel: 12-15 Min, abhaengig von Dicke" |
  | Geraete | Bedienungsanleitungen (PDF → Text) | "Waschmaschine Eco-Modus: 60°, 2:40h" |
  | Haushalt | Alltagswissen-Sammlung | "Fenster putzen: Essig + Zeitungspapier" |
  | Persoenlich | User-eingetragene Notizen | "Allergien: Erdnuesse, Penicillin" |
- Ablauf: Frage → Semantische Suche in ChromaDB → Relevante Chunks + Frage an LLM
- Ehrlichkeit: "Dazu hab ich nichts gespeichert." statt halluzinieren

**Umsetzung:**
- `brain.py`: RAG-Pipeline vor LLM-Call (wenn Intent = Wissensfrage)
- `semantic_memory.py`: Neue Collection `knowledge_base` (getrennt von Personal Memories)
- NEU: `knowledge_ingester.py` — PDF/YAML/Text → Chunks → ChromaDB
- CLI-Tool: `python -m assistant.ingest /pfad/zu/docs/`

**Aufwand:** ~4-6 Stunden
**Wirkung:** HOCH — Jarvis wird vom Smart-Home-Butler zum Wissensassistenten.

---

### Feature 11.2: Externer Kontext via HA (Welt ausserhalb des Hauses)

**Ist-Zustand:** Jarvis kennt nur den Haus-Status. Er weiss nicht was draussen passiert
(ausser Wetter via HA Weather Entity).

**WICHTIG: Jarvis hat KEINEN Internetzugang.**
Alle externen Daten kommen ueber Home Assistant Integrationen.
HA holt die Daten aus dem Internet → exponiert sie als Entities → Jarvis liest die Entities.

**Soll-Zustand:**
- Jarvis liest HA-Entities die von HA-Integrationen befuellt werden:
  | HA-Integration | HA-Entity | Was Jarvis damit macht |
  |---------------|-----------|----------------------|
  | Met.no Weather | `weather.home` (existiert bereits) | Temperatur, Regen, Prognose |
  | Met.no Forecast | `weather.home` → Forecast-Attribute | "Regen in 2 Stunden. Waesche reinholen." |
  | Sun Integration | `sun.sun` (existiert bereits) | Sonnenauf-/-untergang |
- Proaktive Meldungen nur bei Relevanz (nicht jede halbe Stunde Wetter)
- Kein eigener HTTP-Call, kein eigener API-Zugang — nur HA State API (lokal)
- Met.no liefert: Temperatur, Niederschlag, Wind, Luftdruck, Forecast (48h)

**Umsetzung:**
- `context_builder.py`: Weather/Sun-Entities in Kontext einbeziehen
- `proactive.py`: Wetter-Aenderungen als proaktive Meldung (triggered by HA Entity Change)
- Config in `settings.yaml`: Welche HA-Entities als Kontext-Quellen dienen
- **Voraussetzung:** Met.no Integration in HA (Standard-Integration, bereits vorhanden)

**Aufwand:** ~3-4 Stunden (einfacher, weil HA die Arbeit macht)
**Wirkung:** HOCH — "Es regnet in 20 Minuten. Waesche haengt draussen." Das ist Jarvis.

---

### Feature 11.3: Kalender-Tiefenintegration

**Ist-Zustand:** Morning Briefing (Phase 7.1) liest Kalender-Eintraege via HA.
Aber: Nur lesen, kein Verwalten, keine Konflikterkennung.

**Soll-Zustand:**
- Kalender-Management via Sprache:
  | Aktion | Beispiel |
  |--------|---------|
  | Termin erstellen | "Freitag 15 Uhr Zahnarzt" → HA Calendar Event |
  | Termin verschieben | "Verschieb den Zahnarzt auf Montag" |
  | Erinnerung setzen | "Erinner mich morgen an Paket abholen" |
  | Konflikte erkennen | "Da hast du schon was um 15 Uhr." |
  | Tagesplanung | "Was steht morgen an?" → Strukturierte Uebersicht |
- Integration mit HA Calendar Entities (CalDAV, Google, Local)
- Erinnerungen via `proactive.py` (30 Min vorher, konfigurierbar)

**Umsetzung:**
- `function_calling.py`: Neue Tools `create_event()`, `modify_event()`, `list_events()`
- `brain.py`: Kalender-Intent-Erkennung
- `proactive.py`: Reminder-Pipeline fuer anstehende Termine

**Aufwand:** ~4-6 Stunden
**Wirkung:** MITTEL-HOCH — Jarvis wird zum persoenlichen Assistenten, nicht nur Haustechnik.

---

### Feature 11.4: Korrektur-Lernen

**Ist-Zustand:** Wenn User Jarvis korrigiert ("Nein, das andere Licht!"),
wird die Korrektur nicht gespeichert. Naechstes Mal gleicher Fehler.

**Soll-Zustand:**
- Korrektur-Erkennung in der Antwort-Pipeline:
  | Trigger | Was Jarvis lernt | Speicher |
  |---------|-----------------|---------|
  | "Nein, das andere" | Entity-Praeferenz pro Raum/Kontext | Redis |
  | "Kuerzer!" | Antwortlaenge-Praeferenz | Personality Config |
  | "So nicht, eher..." | Formulierungs-Praeferenz | Few-Shot Update |
  | "Das ist falsch" | Fakten-Korrektur | Semantic Memory |
- Confirmation: "Verstanden. Wohnzimmer-Licht meint ab jetzt die Deckenlampe."
- Korrektur-History abrufbar: "Was hast du von mir gelernt?"

**Umsetzung:**
- `brain.py`: Korrektur-Intent erkennen (Negation + neue Info)
- `memory.py`: Korrektur als hochprioritaere Memory speichern (Confidence 1.0)
- `personality.py`: Korrektur-bezogene Praeferenzen anwenden

**Aufwand:** ~2-3 Stunden
**Wirkung:** SEHR HOCH — Jarvis macht keinen Fehler zweimal. Das definiert einen guten Butler.

---

### Technische Zusammenfassung Phase 11

| Modul | Aenderung | Status |
|-------|---------|--------|
| `brain.py` | RAG-Pipeline (_get_rag_context), Korrektur-Erkennung (_is_correction/_handle_correction), KB-Sprachbefehle | ✅ |
| NEU: `knowledge_base.py` | ChromaDB Collection mha_knowledge_base, Chunking, Ingestion, Suche | ✅ |
| `context_builder.py` | Met.no Wetter-Details (Wind, Druck, Forecast), sun.sun (Sunrise/Sunset), echte Sonnenzeiten | ✅ |
| `function_calling.py` | get_calendar_events, create_calendar_event (HA Calendar Service) | ✅ |
| `brain.py` | get_calendar_events in QUERY_TOOLS (Feedback-Loop) | ✅ |
| `settings.yaml` | knowledge_base Config (chunk_size, overlap, max_distance) | ✅ |
| `config/knowledge/` | Wissens-Verzeichnis fuer Textdateien | ✅ |

**Implementiert:** 2026-02-18, 1 Commit

---

---

# Phase 14 — Jarvis Wahrnehmung & Sinne
## 3 Features | Betroffene Module: brain.py, function_calling.py
## Status: Geplant

> **Ziel:** Jarvis kann SEHEN und HOEREN — nicht nur Text verarbeiten.
> **Hardware:** Kamera (Tuerklingel, Indoor), GPU empfohlen fuer Bildanalyse.
> **Prinzip:** 100% lokal. Kein Bild verlaesst das Netzwerk.

---

### Feature 14.1: Vision / Kamera-Integration

**Ist-Zustand:** Jarvis hat keine Augen. Kamera-Bilder liegen in HA,
werden aber nicht analysiert.

**Soll-Zustand:**
- Jarvis kann Kamera-Bilder analysieren:
  | Trigger | Was Jarvis sieht | Aktion |
  |---------|-----------------|--------|
  | Tuerklingel | Person erkannt / Paket / Unbekannter | "Paketbote. Paket abgestellt." |
  | Bewegung Garten | Tier / Person / Fahrzeug | "Katze im Garten. Wieder." |
  | Auf Anfrage | "Was siehst du vor der Tuer?" | Bildbeschreibung |
  | Zeitgesteuert | Morgens: Wetter-Check via Kamera | "Nebel. Vorsicht beim Fahren." |
- Object Detection: YOLO oder aehnliches Modell, lokal auf GPU
- Bildbeschreibung: Vision-LLM (LLaVA, Qwen-VL) fuer natuerliche Beschreibungen

**Umsetzung:**
- NEU: `vision.py` — Kamera-Snapshot + Object Detection + Vision-LLM
- `function_calling.py`: Neues Tool `get_camera_snapshot(camera_entity)`
- `proactive.py`: Trigger bei Tuerklingel-Event → Bild analysieren → Melden
- `model_router.py`: Vision-Modell neben Text-Modell verwalten
- HA Integration: `camera.snapshot` Service fuer Bild-Abruf

**Hardware:** GPU empfohlen (YOLO + Vision-LLM). CPU-Fallback moeglich aber langsam.
**Aufwand:** ~8-12 Stunden
**Wirkung:** SEHR HOCH — Jarvis kann SEHEN. Das aendert alles.

---

### Feature 14.2: Multi-Modal Input (Fotos & Dokumente)

**Ist-Zustand:** Jarvis versteht nur Text (Sprache via Whisper → Text).

**Soll-Zustand:**
- User kann Jarvis Bilder schicken (via Companion App oder Web-Interface):
  | Was User schickt | Was Jarvis tut | Beispiel |
  |-----------------|---------------|---------|
  | Foto von Pflanze | Identifizieren | "Monstera. Alle 7 Tage giessen." |
  | Foto von Rezept | Text extrahieren + speichern | "Gespeichert unter 'Omas Gulasch'." |
  | Foto von Fehlermeldung | Diagnose | "Error 403. Zugriff verweigert. Router neustarten." |
  | Foto von Einkaufszettel | Liste erstellen | "8 Positionen erkannt. Einkaufsliste aktualisiert." |
- OCR fuer Text-Erkennung (Tesseract, lokal)
- Vision-LLM fuer Bildbeschreibung (gleich wie 14.1)

**Umsetzung:**
- `brain.py`: Multi-Modal Input Handler (Bild + Text zusammen an Vision-LLM)
- NEU: `ocr.py` — Tesseract-Integration fuer Text-aus-Bild
- API-Endpunkt: `/api/chat` akzeptiert `image` Parameter (Base64)
- Companion App: Foto-Upload-Button

**Aufwand:** ~6-8 Stunden
**Wirkung:** HOCH — Jarvis versteht die Welt, nicht nur Worte.

---

### Feature 14.3: Ambient Audio (Atmosphaere)

**Ist-Zustand:** Jarvis kann Musik abspielen und TTS ausgeben.
Aber: Keine atmosphaerische Audio-Gestaltung.

**Soll-Zustand:**
- Kontextuelle Hintergrund-Sounds ueber HA Media Player:
  | Kontext | Sound | Trigger |
  |---------|-------|---------|
  | Morgens | Vogelgezwitscher (leise) | Morning Briefing |
  | Regen draussen | Regengeraeusch drinnen | Wetter-Entity |
  | Gewitter | Kaminknistern | Wetter + Abend |
  | Einschlafen | White Noise / Naturgeraeusche | Gute-Nacht-Routine |
  | Fokus-Arbeit | Lo-Fi / Brown Noise | "Ich muss mich konzentrieren" |
- Lautstaerke: Immer unter Gespraechs-Lautstaerke (max 15%)
- Automatisch aus bei Gespraech (Jarvis hoert zu → Sound pausiert)
- Deaktivierbar: "Jarvis, Stille." / Konfigurierbar in Settings

**Umsetzung:**
- NEU: `ambient.py` — Sound-Auswahl basierend auf Kontext + Tageszeit + Wetter
- `config/ambient_sounds/` — Lokale Sound-Dateien (kein Streaming, kein Internet)
- `function_calling.py`: Tool `set_ambient(mood)` / `stop_ambient()`
- Integration mit `activity.py`: Pausiert bei Interaktion

**Aufwand:** ~4-6 Stunden
**Wirkung:** MITTEL — Das Haus hat eine Seele, nicht nur Funktionen.

---

### Technische Zusammenfassung Phase 14

| Modul | Aenderung |
|-------|---------|
| `brain.py` | Multi-Modal Input Handler |
| `function_calling.py` | camera_snapshot, set_ambient Tools |
| `proactive.py` | Tuerklingel → Vision → Meldung |
| `model_router.py` | Vision-Modell verwalten |
| NEU: `vision.py` | Object Detection + Vision-LLM |
| NEU: `ocr.py` | Tesseract OCR |
| NEU: `ambient.py` | Kontextuelle Hintergrund-Sounds |

**Hardware:** GPU stark empfohlen, Kamera(s), Mikrofon
**Geschaetzter Aufwand:** ~18-26 Stunden, ~5 Commits

---

---

# Phase 15 — Jarvis Haushalt & Fuersorge
## 4 Features | Betroffene Module: proactive.py, context_builder.py, function_calling.py
## Status: Geplant

> **Ziel:** Jarvis kuemmert sich — um das Haus, die Geraete, die Gesundheit der Bewohner.
> **Prinzip:** Proaktiv aber nicht nervig. Beobachtet, meldet wenn noetig, schweigt wenn nicht.

---

### Feature 15.1: Gesundheit & Raumklima

**Ist-Zustand:** Sensoren messen CO2, Temperatur, Luftfeuchtigkeit.
Add-on hat Comfort-Score. Aber: Keine proaktiven Gesundheits-Tipps.

**Soll-Zustand:**
- Proaktive Gesundheits-Meldungen:
  | Sensor | Schwelle | Jarvis sagt |
  |--------|---------|-------------|
  | CO2 | > 1000 ppm | "CO2 Buero. Fenster." |
  | Luftfeuchtigkeit | > 70% | "Feuchtigkeit Bad hoch. Schimmelrisiko." |
  | Luftfeuchtigkeit | < 30% | "Luft trocken. Luftbefeuchter?" |
  | Temperatur | > 26°C Schlafzimmer | "Schlafzimmer warm. Fenster auf?" |
  | Sitzzeit | > 3h ohne Bewegung | "Drei Stunden. Kurze Pause." |
  | Hydration | Alle 2h bei Hitze | "Trink was." |
- Meldungen respektieren Stille-Matrix (nicht waehrend Meeting, nicht nachts)
- Frequenz-Limit: Max 1 Gesundheits-Tipp pro Stunde

**Umsetzung:**
- NEU: `health_monitor.py` — Schwellen-Ueberwachung + Hydration-Timer
- `proactive.py`: Health-Alerts in Notification-Pipeline
- `context_builder.py`: Raumklima-Daten fuer LLM-Kontext
- Schwellen konfigurierbar in `settings.yaml`

**Aufwand:** ~4-6 Stunden

---

### Feature 15.2: Einkauf & Vorrat

**Ist-Zustand:** Kein Vorrats-Tracking. Keine Einkaufsliste.

**Soll-Zustand:**
- Einkaufslisten-Management per Sprache:
  | Aktion | Beispiel |
  |--------|---------|
  | Hinzufuegen | "Milch auf die Liste" |
  | Entfernen | "Milch hab ich" |
  | Abfragen | "Was brauchen wir?" |
  | Teilen | Push an Companion App beim Einkaufen |
- Vorrats-Tracking (optional, manuell):
  - "Milch ist fast leer" → Automatisch auf Liste
  - Ablaufdaten: "Joghurt laeuft morgen ab."
- Rezept-Vorschlaege basierend auf Vorrat (wenn RAG-Wissensbasis Rezepte hat)

**Umsetzung:**
- `function_calling.py`: Tools `add_to_list()`, `remove_from_list()`, `get_list()`
- HA Shopping List Integration (bereits vorhanden als Entity)
- `semantic_memory.py`: Vorrats-Collection (optional)
- `proactive.py`: Ablauf-Erinnerungen

**Aufwand:** ~3-4 Stunden (HA Shopping List existiert bereits)

---

### Feature 15.3: Geraete-Beziehung (Verschleiss & Zustand)

**Ist-Zustand:** Jarvis kennt Geraete-Zustaende (an/aus/Wert).
Kein Bewusstsein fuer Verschleiss, Alterung, ungewoehnliches Verhalten.

**Soll-Zustand:**
- Jarvis "kennt" seine Geraete und bemerkt Auffaelligkeiten:
  | Beobachtung | Jarvis sagt |
  |-------------|-------------|
  | Waschmaschine braucht laenger als ueblich | "Waschmaschine braucht 20 Min laenger als sonst." |
  | Heizung erreicht Zieltemperatur nicht | "Heizung Buero. Seit 2 Stunden auf 22 eingestellt, nur 19 erreicht." |
  | Sensor seit Tagen gleicher Wert | "Bewegungsmelder Flur. Seit 3 Tagen nichts. Batterie?" |
  | Stromverbrauch eines Geraets steigt | "Kuehlschrank verbraucht 30% mehr als letzten Monat." |
- Basiert auf historischen Durchschnittswerten (gleitender Mittelwert)
- Nicht jede Abweichung melden — nur signifikante (> 2x Standardabweichung)

**Umsetzung:**
- NEU: `device_health.py` — Geraete-Baselines berechnen + Anomalie-Erkennung
- `proactive.py`: Geraete-Anomalie als LOW-Priority-Meldung
- Redis: Baseline-Werte pro Entity (`mha:device:baseline:{entity_id}`)
- Taegliche Neuberechnung der Baselines

**Aufwand:** ~6-8 Stunden

---

### Feature 15.4: Benachrichtigungs-Intelligenz

**Ist-Zustand:** Jede proaktive Meldung wird einzeln ausgeliefert.
Niedrige und hohe Prioritaet werden gleich behandelt.

**Soll-Zustand:**
- Intelligente Notification-Pipeline:
  | Prioritaet | Verhalten | Beispiel |
  |-----------|-----------|---------|
  | KRITISCH | Sofort, laut, ggf. wiederholen | Rauchmelder, Wasseralarm |
  | HOCH | Sofort, normale Lautstaerke | Fenster offen bei Regen |
  | MITTEL | Naechste Interaktion oder in 15 Min | "Waschmaschine fertig" |
  | NIEDRIG | Batchen — gesammelt beim naechsten Briefing | Geraete-Anomalie, Wartung |
- Batching: Niedrige Meldungen sammeln sich → "Drei Sachen: ..." beim naechsten Kontakt
- Kanal-Wahl:
  - Zu Hause → TTS im richtigen Raum
  - Unterwegs → Push-Notification (kurz)
  - Schlafen → Nur KRITISCH, Rest morgens
- Duplikat-Erkennung: Gleiche Meldung nicht zweimal (nutzt Warning-Dedup)

**Umsetzung:**
- NEU: `notification_queue.py` — Priority-Queue + Batching-Logik
- `proactive.py`: Alle Meldungen durch Queue statt direkte Auslieferung
- `activity.py`: Liefert Kontext (zu Hause, schlaeft, unterwegs)
- Redis: `mha:notifications:queue` (sortiert nach Prioritaet + Timestamp)

**Aufwand:** ~3-4 Stunden

---

### Technische Zusammenfassung Phase 15

| Modul | Aenderung |
|-------|---------|
| `proactive.py` | Alle Meldungen durch Notification-Queue |
| `context_builder.py` | Raumklima-Daten erweitert |
| `function_calling.py` | Shopping-List-Tools |
| NEU: `health_monitor.py` | Raumklima + Hydration + Pausen |
| NEU: `device_health.py` | Geraete-Baselines + Anomalie-Erkennung |
| NEU: `notification_queue.py` | Priority-Queue + Batching |

**Geschaetzter Aufwand:** ~16-22 Stunden, ~6 Commits

---

---

# Phase 16 — Jarvis fuer Alle (Multi-User & Interface)
## 3 Features | Betroffene Module: personality.py, brain.py, Frontend
## Status: Geplant

> **Ziel:** Jarvis funktioniert nicht nur fuer den Technik-Nerd der ihn gebaut hat.
> Er erklaert sich selbst, loest Konflikte, und hat ein Gesicht.
> **Prinzip:** Jarvis ist fuer den ganzen Haushalt da.

---

### Feature 16.1: Konfliktloesung (Multi-User)

**Ist-Zustand:** Jarvis fuehrt Befehle aus — egal von wem.
Wenn zwei Personen verschiedene Temperaturen wollen, gewinnt der Letzte.

**Soll-Zustand:**
- Konflikterkennung + Mediation:
  | Konflikt | Jarvis | Loesung |
  |----------|--------|---------|
  | Person A: 22°, Person B: 20° | "21 Grad als Kompromiss?" | Mittelwert vorschlagen |
  | Person A: Musik laut, Person B: Ruhe | "Musik nur im Wohnzimmer. Buero bleibt still." | Raum-Isolation |
  | Person A: Licht hell, Person B: dunkel | "Stehlampe fuer dich, Decke aus fuer sie." | Zonen-Loesung |
- Praeferenz-Ranking: Owner > Mitbewohner > Gast (aus Trust-Levels)
- Bei gleichem Trust-Level: Kompromiss vorschlagen oder fragen

**Umsetzung:**
- `brain.py`: Konflikt-Detection (aktuelle Einstellung vs. neue Anfrage vs. andere Person)
- `personality.py`: Mediations-Prompts
- Nutzt Trust-Levels (bereits implementiert) fuer Priorisierung

**Aufwand:** ~3-4 Stunden

---

### Feature 16.2: Onboarding / Lernmodus

**Ist-Zustand:** Neuer Nutzer steht vor Jarvis und weiss nicht was er kann.
Kein Hilfesystem, keine Einfuehrung.

**Soll-Zustand:**
- Automatisches Onboarding fuer neue Personen:
  ```
  Neue Person erkannt (Speaker Recognition oder manuell):

  Jarvis: "Ich bin Jarvis. Ich kuemmere mich um das Haus.
  Licht, Heizung, Musik — sag einfach was du brauchst.
  Fuer den Anfang: 'Mach das Licht an.' Probier's."
  ```
- Auf Anfrage: "Was kannst du?" → Kurzuebersicht der Faehigkeiten
- Tutorial-Modus: Jarvis erklaert bei den ersten 5 Interaktionen zusaetzlich was er tut
- "Hilfe" → Kontext-sensitive Hilfe (was geht gerade im aktuellen Raum)
- Fuer Gaeste: Vereinfachte Version ohne technische Details

**Umsetzung:**
- `personality.py`: Onboarding-Prompt-Erweiterung (erste N Interaktionen ausfuehrlicher)
- `memory.py`: Flag `first_interactions_count` pro Person
- `function_calling.py`: Tool `get_capabilities()` → Strukturierte Faehigkeiten-Liste
- Gaeste-Variante: Nur Basics, kein "Was kannst du alles"

**Aufwand:** ~4-6 Stunden

---

### Feature 16.3: Dashboard (Jarvis hat ein Gesicht)

**Ist-Zustand:** Jarvis existiert nur als Stimme / Text. Kein visuelles Interface
das zeigt was er denkt, tut, oder weiss.

**Soll-Zustand:**
- Web-Dashboard (React, auf vorhandenem Frontend aufbauend):
  | Bereich | Inhalt |
  |---------|--------|
  | Live-Status | Haus-Uebersicht: Temp, Licht, Anwesenheit, Energie |
  | Jarvis-Log | Letzte Entscheidungen, Aktionen, Warnungen |
  | Persoenlichkeit | Aktueller Mood, Humor-Level, Formality-Score |
  | Automationen | Von Jarvis erstellte Automationen (Phase 13.2) |
  | Wissen | Was Jarvis gelernt hat (Korrekturen, Fakten, Praeferenzen) |
  | Einstellungen | Autonomie-Level, Sarkasmus, Benachrichtigungen |
- Responsive: Tablet an der Wand / Handy / Desktop
- Optional: E-Ink Display im Flur (nur Status, minimalistisch)

**Umsetzung:**
- Add-on Frontend (React): Neue Route `/jarvis`
- API-Endpunkte: `/api/jarvis/status`, `/api/jarvis/log`, `/api/jarvis/knowledge`
- `brain.py`: Logging aller Entscheidungen fuer Dashboard
- WebSocket: Live-Updates fuer Status-Aenderungen

**Aufwand:** ~10-15 Stunden (Frontend ist Hauptaufwand)
**Wirkung:** HOCH — Jarvis wird greifbar. Man kann sehen was er denkt.

---

### Technische Zusammenfassung Phase 16

| Modul | Aenderung |
|-------|---------|
| `brain.py` | Konflikt-Detection, Entscheidungs-Logging |
| `personality.py` | Mediations-Prompts, Onboarding-Modus |
| `memory.py` | First-Interaction-Counter pro Person |
| `function_calling.py` | get_capabilities() Tool |
| Add-on Frontend | Dashboard Route `/jarvis` |
| Add-on API | Status/Log/Knowledge Endpunkte |

**Geschaetzter Aufwand:** ~17-25 Stunden, ~5 Commits

---

---

# Gesamtübersicht

```
                          MINDHOME JARVIS
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
     ADD-ON (PC1)        ASSISTANT (PC2)     HARDWARE
     ✅ FERTIG            ✅ BASIS FERTIG     📋 TEILWEISE
     156 Features         14 Module           │
          │                   │               ├─ Mikrofon/Speaker ✅
          │              ┌────┴────┐          ├─ Sensoren ✅
          │              │ NEU:    │          ├─ GPU ❌ (geplant)
          │              │         │          └─ Multi-Room ❌
          │              │ Ph 6: Charakter
          │              │ Ph 7: Routinen
          │              │ Ph 8: Gedächtnis
          │              │ Ph 9: Stimme
          │              │ Ph 10: Multi-Room
          │              │ Ph 11: Wissen
          │              │ Ph 12: Authentizitaet
          │              │ Ph 13: Selbstprog.
          │              │ Ph 14: Wahrnehmung
          │              │ Ph 15: Fuersorge
          │              │ Ph 16: fuer Alle
          │              │         │
          │              │ 60 neue Features
          │              │ ~76 Commits
          │              └─────────┘
          │
     Liefert Daten an Assistant via HA API
```

## Feature-Count

| Phase | Name | Features | Commits | Status | Fokus |
|:-----:|------|:--------:|:-------:|:------:|-------|
| 6 | Persönlichkeit | 10 | ~8 | ✅ | Charakter, Humor, Meinung |
| 7 | Routinen | 9 | ~10 | ✅ | Tagesstruktur, Szenen |
| 8 | Gedächtnis | 7 | ~10 | ✅ | Vorausdenken, Wissen |
| 9 | Stimme | 6 | ~8 | ✅ | Akustik, Erkennung |
| 10 | Multi-Room | 5 | ~8 | 🆕 | Praesenz, Kommunikation |
| 11 | Wissen & Kontext | 4 | ~6 | 📋 | RAG, Kalender, Korrekturen, Extern |
| 12 | Authentizitaet | 5 | ~5 | 🔧 | Few-Shot, Filter, Fine-Tuning |
| 13 | Selbstprogrammierung | 4 | ~5 | 📋 | Config, Automationen, Tools, Prompt |
| 14 | Wahrnehmung | 3 | ~5 | 📋 | Vision, Multi-Modal, Ambient Audio |
| 15 | Haushalt & Fuersorge | 4 | ~6 | 📋 | Gesundheit, Einkauf, Geraete, Notifications |
| 16 | fuer Alle | 3 | ~5 | 📋 | Konflikte, Onboarding, Dashboard |
| **Σ** | | **60** | **~76** | | |

**Gesamt: 60 neue Assistant-Features + 156 bestehende (Add-on) + 14 bestehende (Assistant) = 230 Features**

---

## Empfohlene Reihenfolge

```
Phase 6 ─── Persönlichkeit ───  ~8 Commits  ─── Kein neues Modul nötig, hauptsächlich Prompts
   │
Phase 7 ─── Routinen ─────────  ~10 Commits ─── Kann parallel zu Phase 6
   │
Phase 8 ─── Gedächtnis ───────  ~10 Commits ─── 2 neue Module
   │
Phase 9 ─── Stimme ───────────  ~8 Commits  ─── Braucht GPU
   │
Phase 10 ── Multi-Room ───────  ~8 Commits  ─── Braucht Wyoming Satellites
   │
Phase 11 ── Wissen ─────────  ~6 Commits  ─── RAG, Kalender, Korrekturen
   │
Phase 12 ── Authentizitaet ──  ~5 Commits  ─── Few-Shot, Filter, ggf. Fine-Tuning
   │
Phase 13 ── Selbstprog. ────  ~5 Commits  ─── Config, Automationen, Tools, Prompt
   │
Phase 14 ── Wahrnehmung ────  ~5 Commits  ─── Vision, Multi-Modal (braucht GPU)
   │
Phase 15 ── Fuersorge ──────  ~6 Commits  ─── Gesundheit, Einkauf, Geraete
   │
Phase 16 ── fuer Alle ──────  ~5 Commits  ─── Konflikte, Onboarding, Dashboard
```

**Phase 12.1 + 12.3 sind der naechste Hebel** — unter 2 Stunden, groesster Effekt
auf die Jarvis-Authentizitaet. Few-Shot Examples + Response-Filter.

---

*Naechster Schritt: Phase 12.1 (Few-Shot Examples) + 12.3 (Response-Filter) implementieren.*
