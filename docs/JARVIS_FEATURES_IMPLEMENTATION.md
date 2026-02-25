# Jarvis-Features: Implementierung & Bug-Review

**Datum:** 2026-02-25
**Branch:** `claude/enhance-assistant-features-AfIAe`
**Ziel:** MindHome Assistant naeher an MCU-Jarvis bringen — 7 Features fuer das "lebendige" Gefuehl

---

## Uebersicht: 7 implementierte Features

| # | Feature | Beschreibung | Neue Dateien | Modifizierte Dateien |
|---|---------|-------------|--------------|---------------------|
| 1 | Progressive Antworten | Jarvis "denkt laut" — Zwischen-Meldungen statt Stille | — | brain.py, websocket.py, personality.py |
| 2 | Benannte Protokolle | Multi-Step-Sequenzen per Sprache ("Filmabend") | protocol_engine.py | brain.py, function_calling.py |
| 3 | Geraete-Persoenlichkeit | Spitznamen fuer Geraete in proaktiven Meldungen | — | personality.py, proactive.py |
| 4 | Spontane Beobachtungen | 1-2x taeglich unaufgeforderte Bemerkungen | spontaneous_observer.py | brain.py |
| 5 | Emotionales Gedaechtnis | Merkt sich negative Reaktionen auf Aktionen | — | memory_extractor.py, brain.py |
| 8 | Lern-Transparenz | "Was hast du beobachtet?" + woechentlicher Bericht | — | learning_observer.py, brain.py |
| 10 | Daten-basierter Widerspruch | Live-Daten-Check vor Ausfuehrung (offene Fenster etc.) | — | function_validator.py, brain.py |

**Zusaetzlich:** UI-Tab "Jarvis-Features" in app.js + index.html fuer alle Einstellungen.

---

## Feature 1: Progressive Antworten ("Denken laut")

### Was es tut
Statt still zu verarbeiten, sendet Jarvis Zwischen-Meldungen via WebSocket:
- **Context-Phase:** "Ich pruefe den aktuellen Hausstatus."
- **Thinking-Phase:** "Einen Moment, ich ueberlege."
- **Action-Phase:** "Wird sofort erledigt."

### Technische Details
- **websocket.py:** Neue Funktion `emit_progress(step, message)` → Event `assistant.progress`
- **personality.py:** `get_progress_message(step)` waehlt Nachricht passend zum Formality-Level (formal/casual)
- **brain.py:** 3 Stellen in `process()` wo `emit_progress()` aufgerufen wird
- Nur aktiv wenn **kein Streaming** laeuft (`not stream_callback`)
- Jeder Schritt einzeln abschaltbar in settings.yaml

### Einstellungen (settings.yaml)
```yaml
progressive_responses:
  enabled: true
  show_context_step: true
  show_thinking_step: true
  show_action_step: true
```

---

## Feature 2: Benannte Protokolle

### Was es tut
User erstellt Multi-Step-Sequenzen per Sprache:
- "Erstelle Protokoll Filmabend: Licht 20%, Rolladen zu, TV an"
- Danach reicht: "Filmabend" → alle Schritte werden sequentiell ausgefuehrt
- "Protokoll Filmabend rueckgaengig" → Undo-Schritte

### Technische Details
- **protocol_engine.py** (neue Datei, ~350 Zeilen):
  - `create_protocol()` — LLM parst natuerliche Beschreibung zu strukturierten Schritten
  - `execute_protocol()` — Sequentielle Ausfuehrung via FunctionExecutor
  - `undo_protocol()` — Reverse-Schritte (automatisch generiert)
  - `detect_protocol_intent()` — Erkennt Protokoll-Namen im User-Text
- **function_calling.py:** Tool `manage_protocol` mit Aktionen create/execute/undo/list/delete
- **brain.py:** Fast-Shortcut fuer Protokoll-Erkennung + Tool in QUERY_TOOLS

### Redis-Struktur
```
mha:protocol:{name_normalized}     → JSON (Protokoll-Daten + Schritte + Undo-Schritte)
mha:protocol:list                  → Set (alle Protokoll-Namen)
mha:protocol:last_executed:{name}  → JSON (TTL: 1 Stunde, fuer Undo-Fenster)
```

### Einstellungen
```yaml
protocols:
  enabled: true
  max_protocols: 20
  max_steps: 10
```

---

## Feature 3: Geraete-Persoenlichkeit (Narration)

### Was es tut
Geraete bekommen Spitznamen in proaktiven Meldungen:
- Statt: "Waschmaschine ausgeschaltet"
- Jetzt: "Die Fleissige hat ihre Arbeit erledigt, Sir."

### Technische Details
- **personality.py:**
  - `_DEVICE_NICKNAMES` — Default-Mappings (Waschmaschine → "die Fleissige", Saugroboter → "der Kleine", etc.)
  - `_DEVICE_EVENT_TEMPLATES` — Vorlagen pro Event-Typ (turned_off, turned_on, running_long, anomaly, stale)
  - `narrate_device_event(entity_id, event_type, detail)` → Fertiger Narrations-Text
  - `_get_device_nickname()` — Prueft erst Custom-Config, dann Defaults
- **proactive.py:** In `_notify()` wird vor dem LLM-Call geprueft ob eine Narration moeglich ist → spart LLM-Call

### Einstellungen
```yaml
device_narration:
  enabled: true
  custom_nicknames: {}
    # waschmaschine: "Frau Waschkraft"
    # saugroboter: "Robbie"
```

---

## Feature 4: Spontane Beobachtungen

### Was es tut
Jarvis macht 1-2x taeglich unaufgeforderte, interessante Bemerkungen:
- "Heute verbrauchen wir 20% weniger Energie als letzte Woche."
- "Die Waschmaschine lief diese Woche 7 Mal — Rekord!"
- "Draussen hat es 28 Grad bei strahlendem Sonnenschein. Vielleicht ein guter Moment fuer frische Luft."

### Technische Details
- **spontaneous_observer.py** (neue Datei, ~280 Zeilen):
  - Background-Loop mit zufaelligem Intervall (min_interval bis 2x min_interval Stunden)
  - Initiales Warten: 30-60 Min nach Start
  - Nur waehrend aktiver Stunden (default: 8-22 Uhr)
  - Max N Beobachtungen pro Tag
  - Cooldown pro Observation-Typ (24 Stunden)
- **4 Observation-Checks:**
  1. `_check_energy_comparison()` — Vergleich mit Vorwoche (>15% Differenz)
  2. `_check_weather_streak()` — Sonnig >25°C oder Schnee
  3. `_check_usage_record()` — Neuer Tages-Rekord bei manuellen Aktionen
  4. `_check_device_milestone()` — Entity 7+ Mal pro Woche genutzt
- **brain.py:** `_handle_spontaneous_observation()` Callback

### Redis-Struktur
```
mha:spontaneous:daily_count:{date}  → int (TTL: 48h)
mha:spontaneous:cooldown:{type}     → "1" (TTL: 24h)
mha:spontaneous:record:*            → Rekord-Werte
```

### Einstellungen
```yaml
spontaneous:
  enabled: true
  max_per_day: 2
  min_interval_hours: 3
  active_hours:
    start: 8
    end: 22
  checks:
    energy_comparison: true
    streak: true
    usage_record: true
    device_milestone: true
```

---

## Feature 5: Emotionales Gedaechtnis

### Was es tut
Jarvis merkt sich wenn der User negativ auf Aktionen reagiert:
- User: "Lass das!" (nach automatischem Fenster-Schliessen)
- Jarvis speichert: negative Reaktion auf `set_cover`
- Beim naechsten Mal: "Der Benutzer hat bereits 2x negativ auf set_cover reagiert. Frage lieber nach."

### Technische Details
- **memory_extractor.py:**
  - `extract_reaction(user_text, action_performed, accepted, person, redis_client)` — Speichert Reaktion
  - `get_emotional_context(action_type, person, redis_client)` — Liest negative History, gibt Warntext zurueck
  - `detect_negative_reaction(text)` — Pattern-Matching gegen Negativ-Woerter ("nein", "lass das", "stopp", etc.)
- **brain.py:**
  - Vor Tool-Execution: Emotionalen Kontext abrufen → an pushback_msg anhaengen
  - Nach Tool-Execution: Negative Reaktion tracken (gegen **vorherige** Aktion, nicht aktuelle)

### Redis-Struktur
```
mha:emotional_memory:{action_type}:{person} → JSON-Liste (max 20, TTL: decay_days)
```

### Einstellungen
```yaml
emotional_memory:
  enabled: true
  negative_threshold: 2   # Ab 2 negativen Reaktionen warnen
  decay_days: 90
```

---

## Feature 8: Lern-Transparenz

### Was es tut
- **On-Demand:** "Was hast du beobachtet?" → Bericht ueber erkannte Muster
- **Woechentlich:** Automatischer Lern-Bericht (konfigurierbar: Tag + Uhrzeit)

### Technische Details
- **learning_observer.py:**
  - `get_learning_report(period)` — Aggregiert Muster, Beobachtungen, Vorschlag-Statistiken
  - `format_learning_report(report)` — Formatiert als natuerlichen deutschen Text
- **brain.py:**
  - Fast-Shortcut fuer Trigger: "was hast du beobachtet", "lernbericht", "meine muster", etc.
  - `_weekly_learning_report_loop()` — Background-Task, sendet Bericht am konfigurierten Tag/Uhrzeit

### Einstellungen
```yaml
learning:
  enabled: true
  min_repetitions: 3
  time_window_minutes: 30
  weekly_report:
    enabled: true
    day: 6       # 0=Montag, 6=Sonntag
    hour: 19
```

---

## Feature 10: Daten-basierter Widerspruch

### Was es tut
Vor einer Aktion prueft Jarvis Live-Daten und warnt konkret:
- "Heizung auf 25? Das Bad-Fenster ist offen."
- "Licht an? Die Sonne steht hoch (Elevation 30°)."
- "Rolladen oeffnen? Starker Wind mit 75 km/h."

Die Aktion wird trotzdem ausgefuehrt, aber die Warnung beilaeufig erwaehnt.

### Technische Details
- **function_validator.py:**
  - `set_ha_client(ha_client)` — Verbindet mit Home Assistant fuer Live-Daten
  - `get_pushback_context(func_name, args)` — Dispatcht an spezifische Checker
  - `_pushback_set_climate()` — Prueft offene Fenster, leerer Raum, unnoetige Heizung
  - `_pushback_set_light()` — Prueft Tageslicht (sun.sun Elevation > 25°)
  - `_pushback_set_cover()` — Prueft Sturmwarnung (Wind > 60 km/h)
  - `format_pushback_warnings()` — Formatiert Warnungen als LLM-Kontext
- **brain.py:** Nach bestehendem Pushback-Check wird `get_pushback_context()` aufgerufen

### Einstellungen
```yaml
pushback:
  enabled: true
  checks:
    open_windows: true
    empty_room: true
    daylight: true
    storm_warning: true
    unnecessary_heating: true
```

---

## UI: Jarvis-Features Tab

Neuer Tab "Jarvis-Features" im Assistant UI (Port 8200) unter der Gruppe "Automatisierung".

- **index.html:** Navigation-Item `tab-jarvis` hinzugefuegt
- **app.js:** `renderJarvisFeatures()` mit 7 Sektionen — alle Einstellungen konfigurierbar
- Nutzt bestehende UI-Helper: `fToggle`, `fRange`, `fNum`, `fSelect`, `fTextarea`, `sectionWrap`
- `collectSettings()` sammelt generisch alle `data-path` Elemente — keine Aenderung noetig

---

## Bug-Review: 5 Bugs gefunden und behoben

### Bug 1: No-Op Replacements (Niedrig)
**Datei:** `protocol_engine.py:350`
**Problem:** `name.replace("ae", "ae")` — ersetzt "ae" mit "ae", tut nichts.
**Fix:** Zeile entfernt (die eigentliche Umlaut-Konvertierung `ä → ae` darunter funktioniert korrekt).

### Bug 2: Person nicht uebergeben (Mittel)
**Datei:** `function_calling.py:4533`
**Problem:** `create_protocol(name, description)` und `execute_protocol(name)` ohne `person` — Ersteller/Ausfuehrender wird nicht gespeichert.
**Fix:** `brain._current_person` wird in `process()` gesetzt und in `_exec_manage_protocol` ausgelesen.

### Bug 3: Emotionales Gedaechtnis Falsch-Positive (Hoch)
**Datei:** `brain.py:2649-2664`
**Problem:** Pruefte den aktuellen User-Text auf negative Patterns und markierte die aktuell ausgefuehrten Aktionen als negativ. Wenn User "Nein, mach das Licht aus" sagte, wurde "nein" erkannt UND `set_light` ausgefuehrt → falsche negative Reaktion.
**Fix:** Emotionale Reaktion wird nur getrackt wenn im aktuellen Turn KEINE Aktionen ausgefuehrt wurden (d.h. der User reagiert auf eine vorherige Aktion). `_last_executed_action` speichert die letzte Aktion fuer den naechsten Turn.

### Bug 4: Woechentlicher Bericht fehlte (Hoch)
**Datei:** `brain.py`
**Problem:** Config `learning.weekly_report` + UI-Einstellungen vorhanden, aber der Background-Task der den Bericht tatsaechlich sendet fehlte komplett.
**Fix:** `_weekly_learning_report_loop()` implementiert — berechnet naechsten Termin, wartet, sendet Bericht via `_speak_and_emit()`.

### Bug 5: ValueError bei Brightness (Mittel)
**Datei:** `function_validator.py:280`
**Problem:** `int(brightness)` ohne try/except — wenn brightness ein ungueltiger String ist, crasht die Pushback-Pruefung.
**Fix:** try/except um `int(brightness)` mit Fallthrough bei ValueError.

---

## Commits

```
adf00a0 feat: Feature 1+3 — Geraete-Persoenlichkeit + Progressive Antworten
8785eb9 feat: Feature 5+10 — Emotionales Gedaechtnis + Daten-basierter Widerspruch (WIP)
b473326 feat: add data-driven pushback system to function_validator (Feature 10)
55b4556 feat: 7 Jarvis-Features — vollstaendige Integration
7409d4e feat: add Jarvis-Features settings tab to Assistant UI
aeb1b35 fix: 5 bugs in Jarvis-Features behoben
```

---

## Architektur-Hinweise

### Graceful Degradation
Alle neuen Module sind in `_safe_init()` gewrappt. Wenn ein Modul fehlschlaegt, laeuft der Assistent im Degraded Mode weiter.

### Feature-Toggles
Jedes Feature hat `enabled: true/false` in settings.yaml und ist im UI abschaltbar.

### Callback-Pattern
Neue Module (SpontaneousObserver, ProtocolEngine) nutzen das etablierte Callback-Pattern:
1. `set_notify_callback(callback)` in der Komponente
2. `_handle_*()` Methode in brain.py
3. Delivery via `_callback_should_speak()` + `_safe_format()` + `_speak_and_emit()`

### Redis-Keys Uebersicht (neu)
```
mha:protocol:*                    → Feature 2 (Protokolle)
mha:spontaneous:*                 → Feature 4 (Beobachtungen)
mha:emotional_memory:*            → Feature 5 (Emotionales Gedaechtnis)
mha:learning:* (bestehend)        → Feature 8 (erweitert)
```
