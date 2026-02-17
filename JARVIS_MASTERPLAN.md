# MindHome — JARVIS Masterplan
# "Von Smart Assistant zu echtem Jarvis"

> **Stand:** 2026-02-17
> **Aktueller Status:** v0.8.4 (Phase 5 abgeschlossen, Build 87)
> **Architektur:** PC 1 (HAOS Add-on v0.8.4) + PC 2 (Assistant Server)
> **Prinzip:** 100% lokal, kein Cloud, Privacy-first

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
          │              │         │
          │              │ 37 neue Features
          │              │ ~44 Commits
          │              └─────────┘
          │
     Liefert Daten an Assistant via HA API
```

## Feature-Count

| Phase | Name | Features | Commits | Fokus |
|:-----:|------|:--------:|:-------:|-------|
| 6 | Persönlichkeit | 10 | ~8 | Charakter, Humor, Meinung |
| 7 | Routinen | 9 | ~10 | Tagesstruktur, Szenen |
| 8 | Gedächtnis | 7 | ~10 | Vorausdenken, Wissen |
| 9 | Stimme | 6 | ~8 | Akustik, Erkennung |
| 10 | Multi-Room | 5 | ~8 | Präsenz, Kommunikation |
| **Σ** | | **37** | **~44** | |

**Gesamt: 37 neue Assistant-Features + 156 bestehende (Add-on) + 14 bestehende (Assistant) = 207 Features**

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
```

**Phase 6 ist der beste Startpunkt** — größter Wow-Effekt bei geringstem Aufwand
(hauptsächlich Prompt Engineering, keine neue Hardware nötig).

---

*Nächster Schritt: Phase 6 implementieren.*
