# Jarvis Selbstverbesserung: Geschlossene Feedback-Loops

**Datum:** 2026-02-27
**Ziel:** Jarvis lernt aus seinen eigenen Ergebnissen — Beobachten, Messen, Anpassen

---

## Problemstellung

Jarvis hat 8 bestehende Lernsysteme (Anticipation, Learning Observer, Feedback Tracker, Experiential Memory, Insight Engine, Situation Model, Self-Optimization, Self-Automation). Keines davon hat einen geschlossenen Feedback-Loop. Jarvis sammelt Daten, validiert aber nie, ob seine Aktionen tatsaechlich gut waren.

**Loesung:** 8 neue Features in 3 Phasen — von Datensammlung ueber Intelligenz bis zur automatischen Anpassung.

---

## Uebersicht: 8 Features in 3 Phasen

| Phase | # | Feature | Beschreibung | Neue Dateien |
|-------|---|---------|-------------|--------------|
| A | 1 | Outcome Tracker | Beobachtet ob Aktionen gut waren | outcome_tracker.py |
| A | 2 | Korrektur-Gedaechtnis | Speichert + nutzt Korrekturen | correction_memory.py |
| A | 5 | Response Quality | Trackt Antwort-Klarheit | response_quality.py |
| A | 8 | Error Patterns | Erkennt wiederkehrende Fehler | error_patterns.py |
| B | 6 | Per-Person Learning | Individuelle Praeferenzen pro Person | (Erweiterung bestehender) |
| B | 7 | Prompt Self-Refinement | Gelernte Regeln im Prompt | (Erweiterung correction_memory + personality) |
| C | 3 | Self-Report | Woechentlicher Selbstbericht | self_report.py |
| C | 4 | Adaptive Thresholds | Automatische Schwellwert-Anpassung | adaptive_thresholds.py |

---

## Phase A: Daten-Grundlage

### Feature 1: Outcome Tracker (Wirkungstracker)

#### Was es tut
Nach jeder Jarvis-Aktion wird der Zustand der betroffenen Entity gesnapshotten. Nach 3 Minuten wird erneut geprueft:
- **POSITIVE:** User hat nichts geaendert oder "Danke" gesagt
- **NEUTRAL:** Keine Interaktion (Standard-Annahme)
- **PARTIAL:** User hat den Wert angepasst (z.B. Helligkeit nachjustiert)
- **NEGATIVE:** User hat die Aktion rueckgaengig gemacht

Ergebnisse werden pro Aktionstyp, Raum und Tageszeit aggregiert.

#### Technische Details
- **outcome_tracker.py:** Klasse `OutcomeTracker` mit `track_action()`, `record_verbal_feedback()`, `_delayed_check()`, `_classify_outcome()`
- **brain.py:** Hook nach Tool-Ausfuehrung (~Zeile 2732) startet Background-Observation
- **Redis:** `mha:outcome:stats:{action_type}`, `mha:outcome:score:{action_type}` (Rolling Score 0-1)
- Nutzt `JARVIS_ACTION_KEY` aus learning_observer.py zur Unterscheidung Jarvis/User-Aktionen
- Max 500 Ergebnisse, 90 Tage TTL

#### Einstellungen (settings.yaml)
```yaml
outcome_tracker:
  enabled: true
  observation_delay_seconds: 180   # 3 Minuten
  max_results: 500
```

#### Sicherheit
- Rein lesend (nur `ha.get_state()`)
- Scores bounded 0-1
- Redis TTL 90 Tage
- Keine neuen HA-Rechte

---

### Feature 2: Korrektur-Gedaechtnis

#### Was es tut
Wenn der User korrigiert ("Nein, das Schlafzimmer!"), wird strukturiert gespeichert: Original-Aktion + Korrektur + Kontext. Vor aehnlichen zukuenftigen Aktionen werden relevante Korrekturen ins LLM-Kontext injiziert.

#### Technische Details
- **correction_memory.py:** Klasse `CorrectionMemory` mit `store_correction()`, `get_relevant_corrections()`, `_update_rules()`
- **brain.py:** Erweitert `_handle_correction()` (~Zeile 7008) — nach LLM-Extraktion auch strukturierte Korrektur speichern
- **brain.py:** Mega-Gather (~Zeile 1940) — relevante Korrekturen als Kontext laden
- **Redis:** `mha:correction_memory:entries` (max 200), `mha:correction_memory:rules` (gelernte Regeln)
- Relevanz-Scoring: Aktionstyp + Raum + Person + Tageszeit
- Bei Korrektur: signalisiert NEGATIVE an Outcome Tracker

#### Einstellungen (settings.yaml)
```yaml
correction_memory:
  enabled: true
  max_entries: 200
  max_context_entries: 3    # Max Korrekturen im LLM-Kontext
```

#### Sicherheit
- Read-only Memory
- Beeinflusst nur LLM-Kontext (Vorschlaege), aendert nie Aktionen direkt
- Max 200 Eintraege, 90d TTL

---

### Feature 5: Response Quality Score

#### Was es tut
Trackt wie effektiv Jarvis' Antworten sind:
- Follow-Up-Frage innerhalb 60s = Antwort war unklar
- User wiederholt/umformuliert = Jarvis hat nicht verstanden
- Einzelner Austausch ohne Nachfrage = Erfolg
- Scores pro Kategorie: device_command, knowledge, smalltalk, analysis

#### Technische Details
- **response_quality.py:** Klasse `ResponseQualityTracker` mit `record_exchange()`, `_detect_rephrase()`, `get_quality_score()`
- **brain.py:** Am Anfang von `process()` pruefen ob Rephrase; am Ende Kategorie + Timestamp merken
- **Redis:** `mha:response_quality:score:{category}`, `mha:response_quality:stats:{category}`
- Rephrase-Erkennung: Keyword-Overlap > 60%

#### Einstellungen (settings.yaml)
```yaml
response_quality:
  enabled: true
  followup_window_seconds: 60
  rephrase_similarity_threshold: 0.6
```

#### Sicherheit
- Rein beobachtend, kein Schreibzugriff auf Config/HA
- Bounded Scores 0-1

---

### Feature 8: Error Pattern Analysis

#### Was es tut
Trackt wiederkehrende Fehler nach Typ (timeout, service_unavailable, entity_not_found). Wenn gleiches Muster 3+ mal auftritt: proaktive Mitigation.
- Timeout 3+ mal → Fallback-Modell fruehzeitig nutzen
- Entity not found 3+ mal → Entity aus Vorschlags-Cache entfernen
- Service unavailable 3+ mal → User proaktiv informieren

#### Technische Details
- **error_patterns.py:** Klasse `ErrorPatternTracker` mit `record_error()`, `get_mitigation()`, `get_stats()`
- **brain.py:** In allen `except`-Bloecken (~Zeile 2412 Timeout, ~Zeile 2430 Double-Timeout)
- **Redis:** `mha:errors:pattern:{type}:{action}`, `mha:errors:mitigation:{action}` (TTL 24h)
- Nutzt bestehende `model_router.get_fallback_model()` (brain.py:2415)

#### Einstellungen (settings.yaml)
```yaml
error_patterns:
  enabled: true
  min_occurrences_for_mitigation: 3
  mitigation_ttl_hours: 1
```

#### Sicherheit
- Rein beobachtend + lesend
- Mitigations aendern nur Laufzeit-Routing (nicht persistent)
- TTL 1-24h = automatischer Reset
- Keine neuen HA-Rechte

---

## Phase B: Intelligenz

### Feature 6: Per-Person Learning

#### Was es tut
Statt globaler Scores: individuelle Feedback-Scores, Korrektur-Muster, Outcome-Stats und Praeferenzen PRO Haushaltsmitglied. Lisa mag leise Musik, Max mag laute — Jarvis differenziert.

#### Technische Details
Kein neues File — Erweiterung der Features 1, 2, 5 und feedback.py:
- **Outcome Tracker:** Zusaetzliche Redis-Keys `mha:outcome:stats:{action}:person:{person}`
- **Correction Memory:** Person-Filter bei `get_relevant_corrections()` (hoehere Gewichtung fuer aktive Person)
- **Response Quality:** Per-Person Scores `mha:response_quality:score:{category}:person:{person}`
- **Feedback Tracker:** Per-Person Scores `mha:feedback:score:{event_type}:person:{person}`

Person ist bereits in `brain.py:process()` verfuegbar (`self._current_person`, Zeile 646).

#### Sicherheit
- Nutzt bestehendes Trust-Level-System
- Kein neuer Zugriff, nur Redis-Key-Erweiterung

---

### Feature 7: Prompt Self-Refinement

#### Was es tut
Basierend auf Korrektur-Mustern baut Jarvis "gelernte Regeln" auf, die als Kontext in den System-Prompt injiziert werden.

Beispiel: Nach 3+ Korrekturen "Nein, Schlafzimmer!" am Abend bei `set_light` → Regel: "Abends meint der User mit 'Licht' meistens das Schlafzimmer."

#### Technische Details
- **correction_memory.py:** Existierende `_update_rules()` Methode implementiert Regel-Ableitung
  - Regel-Typen: `room_preference`, `param_preference`, `time_context`
  - Min 2 gleichartige Korrekturen fuer Regel-Erstellung
  - Max 20 aktive Regeln, 90d TTL
- **personality.py:** Neue Methode `build_learned_rules_section(rules)` formatiert max 5 Regeln
  - Format: `GELERNTE PRAEFERENZEN:\n- Abends meint User mit 'Licht' meistens Schlafzimmer.`
- **brain.py:** Im Mega-Gather Regeln laden, beim System-Prompt-Build injizieren

#### Sicherheit
- Regeln sind statische Strings, NICHT LLM-generiert (keine Prompt-Injection)
- Max 20 Regeln, max 200 Zeichen pro Regel
- Regeln koennen nur KONTEXT hinzufuegen, nie Core-Personality/Security aendern
- Confidence >= 0.6 erforderlich (min 2 gleichartige Korrekturen)

---

## Phase C: Synthese

### Feature 3: Woechentlicher Self-Report

#### Was es tut
Jeden Sonntag Abend aggregiert Jarvis Daten aus ALLEN Lernsystemen und generiert via LLM einen natuerlichsprachlichen Selbstbericht. Auch per Chat abrufbar ("Wie lernst du?" / "Selbstbericht").

Beispiel-Output:
> "Sir, diese Woche habe ich 47 Aktionen ausgefuehrt, 43 davon erfolgreich — eine Quote von 91%.
> Viermal wurde ich korrigiert, dreimal ging es um die Raum-Zuordnung abends.
> Ihre Energie-Warnungen haben Sie dreimal zur Kenntnis genommen — das scheint nuetzlich.
> Verbesserungsvorschlag: Ich sollte abends haeufiger nach dem genauen Raum fragen."

#### Technische Details
- **self_report.py:** Klasse `SelfReport` mit `generate_report()`, `_generate_summary()`, `get_latest_report()`
- **brain.py:** Erweitert `_weekly_learning_report_loop()` (~Zeile 7164) — aggregiert alle Subsysteme
- **brain.py:** Chat-Trigger fuer "Selbstbericht", "Wie lernst du?" (~Zeile 5188)
- **Redis:** `mha:self_report:latest` (TTL 14d), `mha:self_report:history` (max 12, TTL 365d)
- LLM-generierte Summary (qwen3:14b) mit Fallback-Formatierung

#### Einstellungen (settings.yaml)
```yaml
self_report:
  enabled: true
  model: qwen3:14b
```
Scheduling nutzt bestehende `learning.weekly_report` Config (Tag: Sonntag, Uhrzeit: 19:00).

#### Sicherheit
- Rein lesend + aggregierend
- Keine Schreibzugriffe
- User sieht alles

---

### Feature 4: Lernende Schwellwerte (Adaptive Thresholds)

#### Was es tut
Analysiert woechentlich Outcome-Daten + Feedback-Scores und passt System-Schwellwerte an. Zwei Stufen:

**Auto-Adjust (ohne Genehmigung, enge Grenzen):**
| Parameter | Min | Max | Default |
|---|---|---|---|
| Insight Cooldown (Stunden) | 2 | 8 | 4 |
| Anticipation Min-Confidence | 0.5 | 0.8 | 0.6 |
| Feedback Basis-Cooldown (Sek) | 120 | 600 | 300 |

**Proposal-Based (mit User-Genehmigung, weiter):**
| Parameter | Min | Max |
|---|---|---|
| Energie-Anomalie-Schwelle (%) | 15 | 50 |
| Anticipation Ask-Threshold | 0.5 | 0.7 |
| Anticipation Suggest-Threshold | 0.7 | 0.9 |

#### Technische Details
- **adaptive_thresholds.py:** Klasse `AdaptiveThresholds` mit `run_analysis()`, `_auto_apply()`, `get_adjustment_history()`
- **brain.py:** Triggered nach Self-Report im `_weekly_self_report_loop()`
- **self_optimization.py:** Neue Eintraege in `_PARAMETER_PATHS` fuer Proposal-Based Params
- **Redis:** `mha:adaptive:adjustments` (max 100, TTL 90d), `mha:adaptive:last_run`

#### Einstellungen (settings.yaml)
```yaml
adaptive_thresholds:
  enabled: false          # Default OFF bis genug Daten gesammelt
  analysis_interval_hours: 168   # Woechentlich
  auto_adjust: true
```

#### Sicherheit
- Auto-Adjust aendert NUR Laufzeit-`yaml_config` dict, NICHT die Datei (Reset bei Restart)
- Bounds HARDCODED in `_AUTO_BOUNDS` (nicht aus Config lesbar, kein Drift moeglich)
- Proposals gehen durch bestehendes Self-Optimization Approval-System (manuell)
- `_HARDCODED_IMMUTABLE` frozenset bleibt unangetastet
- Alle Anpassungen geloggt mit Audit-Trail

---

## Sicherheits-Zusammenfassung

| Feature | Schreibt settings.yaml? | Genehmigung? | Bounded? | Rollback? |
|---|---|---|---|---|
| 1. Outcome Tracker | Nein | Nein (read-only) | Scores 0-1 | N/A |
| 2. Korrektur-Gedaechtnis | Nein | Nein (read-only) | Max 200 | N/A |
| 3. Self-Report | Nein | Nein (read-only) | N/A | N/A |
| 4. Adaptive (auto) | Nein (Laufzeit) | Nein | Hardcoded Bounds | Reset bei Restart |
| 4. Adaptive (proposals) | Ja (via self_opt) | Ja (manuell) | parameter_bounds | config_versioning |
| 5. Response Quality | Nein | Nein (read-only) | Scores 0-1 | N/A |
| 6. Per-Person | Nein | Nein | Gleiche Bounds | N/A |
| 7. Prompt Refinement | Nein | Nein | Max 20 Regeln | TTL 90d |
| 8. Error Patterns | Nein | Nein | TTL 1-24h | Auto-Reset |

**Kern-Schutz unangetastet:**
- `_HARDCODED_IMMUTABLE` = {"trust_levels", "security", "autonomy", "dashboard", "models"}
- `_EDITABLE_CONFIGS` = {easter_eggs, opinion_rules, room_profiles}
- `_ALLOWED_FUNCTIONS` frozenset (69 Funktionen)
- Kein exec/eval/subprocess in Tool-Pfaden

---

## Modifizierte Dateien

| Datei | Aenderung |
|-------|-----------|
| `assistant/assistant/outcome_tracker.py` | **NEU** (~300 Zeilen) |
| `assistant/assistant/correction_memory.py` | **NEU** (~300 Zeilen) |
| `assistant/assistant/response_quality.py` | **NEU** (~200 Zeilen) |
| `assistant/assistant/error_patterns.py` | **NEU** (~200 Zeilen) |
| `assistant/assistant/self_report.py` | **NEU** (~250 Zeilen) |
| `assistant/assistant/adaptive_thresholds.py` | **NEU** (~300 Zeilen) |
| `assistant/assistant/brain.py` | Init + Hooks (~100 Zeilen) |
| `assistant/assistant/personality.py` | Learned-Rules-Section (~20 Zeilen) |
| `assistant/assistant/feedback.py` | Per-Person Scores (~15 Zeilen) |
| `assistant/assistant/self_optimization.py` | Neue Parameter (~15 Zeilen) |
| `assistant/config/settings.yaml` | Neue Sektionen (~40 Zeilen) |

---

## Redis-Key-Map (Alle neuen Keys)

```
# Feature 1: Outcome Tracker
mha:outcome:pending:{uuid}                           # STRING (TTL ~5min)
mha:outcome:results                                  # LIST (max 500, TTL 90d)
mha:outcome:stats:{action_type}                      # HASH
mha:outcome:stats:{action_type}:{room}               # HASH
mha:outcome:score:{action_type}                      # STRING (float)
mha:outcome:stats:{action_type}:person:{person}      # HASH (Feature 6)
mha:outcome:score:{action_type}:person:{person}      # STRING (Feature 6)

# Feature 2: Korrektur-Gedaechtnis
mha:correction_memory:entries                        # LIST (max 200, TTL 90d)
mha:correction_memory:rules                          # HASH (max 20 Regeln)

# Feature 3: Self-Report
mha:self_report:latest                               # STRING (TTL 14d)
mha:self_report:history                              # LIST (max 12, TTL 365d)

# Feature 4: Adaptive Thresholds
mha:adaptive:adjustments                             # LIST (max 100, TTL 90d)
mha:adaptive:last_run                                # STRING (ISO timestamp)

# Feature 5: Response Quality
mha:response_quality:score:{category}                # STRING (float)
mha:response_quality:stats:{category}                # HASH
mha:response_quality:history                         # LIST (max 300, TTL 90d)
mha:response_quality:score:{category}:person:{person}# STRING (Feature 6)

# Feature 6: Per-Person (extends Features 1, 2, 5)
mha:feedback:score:{event_type}:person:{person}      # STRING (float)

# Feature 8: Error Patterns
mha:errors:recent                                    # LIST (max 200, TTL 30d)
mha:errors:pattern:{error_type}:{action_type}        # HASH
mha:errors:mitigation:{action_type}                  # STRING (TTL 24h)
```

---

## Verifizierung

1. **Outcome Tracker:** Licht einschalten → 3 Min spaeter manuell ausschalten → Log: "Outcome [negative]: set_light"
2. **Outcome Tracker:** "Danke" nach Aktion → Log: "Outcome [positive]"
3. **Korrektur-Gedaechtnis:** "Nein, das Schlafzimmer!" → Log: "Korrektur gespeichert"
4. **Prompt Refinement:** Nach 3+ Schlafzimmer-Korrekturen abends → System-Prompt enthaelt "GELERNTE PRAEFERENZEN"
5. **Response Quality:** Gleiche Frage 2x stellen → Log: "Rephrase erkannt"
6. **Error Patterns:** LLM 3x Timeout → Log: "Mitigation: use_fallback" → Fallback-Modell
7. **Self-Report:** "Wie lernst du?" → Bericht mit Zahlen pro Person und Verbesserungsvorschlaegen
8. **Adaptive Thresholds:** Nach Wochenbericht → Log: "Auto-Adjust: insights.cooldown_hours 4 -> 5"
9. **Syntax-Check:** `python3 -m py_compile assistant/assistant/outcome_tracker.py` etc.
10. **Logs:** `docker compose logs -f assistant` → Alle neuen Log-Eintraege pruefen
