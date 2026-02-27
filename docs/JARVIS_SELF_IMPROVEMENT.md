# Jarvis Selbstverbesserung: Geschlossene Feedback-Loops

**Datum:** 2026-02-27
**Ziel:** Jarvis lernt aus seinen eigenen Ergebnissen — Beobachten, Messen, Anpassen

---

## Problemstellung

Jarvis hat 8 bestehende Lernsysteme (Anticipation, Learning Observer, Feedback Tracker, Experiential Memory, Insight Engine, Situation Model, Self-Optimization, Self-Automation). Keines davon hat einen geschlossenen Feedback-Loop. Jarvis sammelt Daten, validiert aber nie, ob seine Aktionen tatsaechlich gut waren.

**Loesung:** 9 Features in 3 Phasen — von Datensammlung ueber Intelligenz bis zur automatischen Anpassung.

---

## Uebersicht: 9 Features in 3 Phasen

| Phase | # | Feature | Beschreibung | Dateien |
|-------|---|---------|-------------|---------|
| A | 1 | Outcome Tracker | Beobachtet ob Aktionen gut waren | outcome_tracker.py (NEU) |
| A | 2 | Korrektur-Gedaechtnis | Speichert + nutzt Korrekturen | correction_memory.py (NEU) |
| A | 5 | Response Quality | Trackt Antwort-Klarheit | response_quality.py (NEU) |
| A | 8 | Error Patterns | Erkennt wiederkehrende Fehler | error_patterns.py (NEU) |
| B | 6 | Per-Person Learning | Individuelle Praeferenzen pro Person | (Erweiterung bestehender) |
| B | 7 | Prompt Self-Refinement | Gelernte Regeln im Prompt | (Erweiterung correction_memory + personality) |
| C | 3 | Self-Report | Woechentlicher Selbstbericht | self_report.py (NEU) |
| C | 4 | Adaptive Thresholds | Automatische Schwellwert-Anpassung | adaptive_thresholds.py (NEU) |
| C | 9 | Self-Optimization+ | Erweiterte Selbstoptimierung | self_optimization.py (Modifiziert) |

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

### Feature 9: Self-Optimization+ (Erweiterte Selbstoptimierung)

#### Was es tut
Die bestehende `self_optimization.py` wird in 6 Bereichen erweitert:

1. **Mehr Datenquellen:** Statt nur Corrections + Feedback-Stats fliessen jetzt Outcome-Scores, Response-Quality-Scores und Correction-Patterns in die Analyse ein.
2. **Vorher/Nachher-Vergleich:** Nach jeder genehmigten Aenderung werden Metriken gesnapshotten. 7 Tage spaeter wird verglichen ob die Aenderung geholfen hat.
3. **Auto-Rollback:** Wenn Metriken nach 7 Tagen signifikant schlechter sind (>10% Outcome Score Drop ODER >15% mehr Korrekturen), wird der vorherige Wert automatisch wiederhergestellt.
4. **Mehr Parameter:** 4 neue optimierbare Parameter (insight_cooldown_hours, anticipation_min_confidence, feedback_base_cooldown, spontaneous_max_per_day).
5. **Trend-Metriken:** Das LLM bekommt Wochen-Trends statt roher Zahlen — z.B. "set_climate Score: 0.71 → 0.65 → 0.62 → 0.58 (FALLEND)".
6. **Aktivierung:** `enabled: true` (bisher `false`), weiterhin mit manueller Approval.

#### Technische Details

**9a. Erweiterte Datenquellen** (~Zeile 89 in run_analysis):
```python
# Bestehend:
corrections = await self._get_recent_corrections()
feedback_stats = await self._get_feedback_stats()
# NEU:
outcome_stats = await self._get_outcome_stats()
quality_stats = await self._get_quality_stats()
correction_patterns = await self._get_correction_patterns()
```

**9b. Effectiveness Tracking:**
- Nach Genehmigung: Metriken-Snapshot in `mha:self_opt:baseline:{param}` (TTL 30d)
- Nach 7 Tagen: Vergleich und Ergebnis in `mha:self_opt:effect:{param}` (TTL 90d)

**9c. Auto-Rollback:**
- Trigger: >10% Outcome Score Drop ODER >15% mehr Korrekturen
- Mechanismus: `config_versioning.rollback()` auf gespeicherten Snapshot
- User wird IMMER informiert

**9d. Neue Parameter in `_PARAMETER_PATHS`:**
```python
_PARAMETER_PATHS = {
    # Bestehend:
    "sarcasm_level": ["personality", "sarcasm_level"],
    "opinion_intensity": ["personality", "opinion_intensity"],
    "max_response_sentences": ["response_filter", "max_response_sentences"],
    "formality_min": ["personality", "formality_min"],
    "formality_start": ["personality", "formality_start"],
    # NEU:
    "insight_cooldown_hours": ["insights", "cooldown_hours"],
    "anticipation_min_confidence": ["anticipation", "min_confidence"],
    "feedback_base_cooldown": ["feedback", "base_cooldown_seconds"],
    "spontaneous_max_per_day": ["spontaneous", "max_per_day"],
}
```

**9e. Trend-Metriken im LLM-Prompt:**
```
OUTCOME-TRENDS (letzte 4 Wochen):
- set_light: Score 0.82 → 0.85 → 0.79 → 0.83 (stabil)
- set_climate: Score 0.71 → 0.65 → 0.62 → 0.58 (FALLEND ↓)

KORREKTUREN (Top 3):
- Raum-Verwechslung: 12x (meistens abends)
- Helligkeit zu hoch: 5x
- Falsches Geraet: 3x
```

#### Einstellungen (settings.yaml)
```yaml
self_optimization:
  enabled: true               # Bisher false
  approval_mode: manual        # NICHT aendern
  analysis_interval: weekly
  max_proposals_per_cycle: 3
  auto_rollback: true          # NEU
  rollback_threshold_outcome: 0.10   # 10% Drop
  rollback_threshold_corrections: 0.15   # 15% Anstieg
  parameter_bounds:
    # Bestehend:
    sarcasm_level: {min: 1, max: 5}
    opinion_intensity: {min: 0, max: 3}
    max_response_sentences: {min: 1, max: 5}
    formality_min: {min: 10, max: 80}
    formality_start: {min: 30, max: 100}
    # NEU:
    insight_cooldown_hours: {min: 2, max: 8}
    anticipation_min_confidence: {min: 0.5, max: 0.8}
    feedback_base_cooldown: {min: 120, max: 600}
    spontaneous_max_per_day: {min: 0, max: 5}
```

#### Sicherheit
- Approval bleibt manuell — User muss jeden Vorschlag bestaetigen
- Auto-Rollback geht nur ZURUECK (nie vorwaerts), nutzt config_versioning Snapshots
- Neue Bounds sind hardcoded in settings.yaml
- `_HARDCODED_IMMUTABLE` bleibt unangetastet
- User wird bei Auto-Rollback immer informiert

---

## Risiko-Mitigationen (alle Features)

Jedes Feature implementiert diese **7 Schutzschichten** aus bestehenden Codebase-Patterns:

### Schicht 1: Minimum-Datenmenge vor Aktion
Pattern-Referenz: `learning_observer.py:47,139` (`min_repetitions`)

Kein Feature darf Schlussfolgerungen ziehen ohne genuegend Daten:

| Feature | Minimum | Bevor... |
|---|---|---|
| Outcome Tracker | 10 Outcomes pro Aktionstyp | Score wird berechnet (vorher default 0.5) |
| Correction Memory | 2 gleichartige Korrekturen | Regel abgeleitet wird |
| Response Quality | 20 Exchanges pro Kategorie | Score als zuverlaessig gilt |
| Error Patterns | 3 gleiche Fehler in 1h | Mitigation aktiviert wird |
| Adaptive Thresholds | 50 Outcomes + 4 Wochen Daten | Schwellwert geaendert wird |
| Self-Optimization+ | Outcome Score + 30 Samples | Vorschlag generiert wird |

Jede Klasse hat einen `_has_sufficient_data()` Check.

### Schicht 2: Score-Decay / Alterung
Pattern-Referenz: `semantic_memory.py:317-395` (`apply_decay()`)

- **Outcome Tracker:** Rolling Window der letzten 200 Ergebnisse. Aeltere zaehlen weniger.
- **Correction Memory:** Regeln verlieren 5% Confidence pro 30 Tage. Unter 0.4 → Regel geloescht.
- **Response Quality:** Exponential Moving Average (alpha=0.1) — neuere Daten zaehlen mehr.
- **Error Patterns:** Counter pro Stunde, nicht kumulativ. 3 Fehler in der letzten Stunde ≠ 3 Fehler in 3 Monaten.

### Schicht 3: Sanitization
Pattern-Referenz: `context_builder.py:41-71` (`_sanitize_for_prompt()`)

Alles was ins LLM-Kontext injiziert wird, durchlaeuft `_sanitize_for_prompt()`:
- **Correction Memory:** `correction_text` wird sanitized (max 100 Zeichen, Injection-Filter)
- **Prompt Self-Refinement:** Regel-Text wird aus Templates gebaut (nicht aus Raw-User-Input), trotzdem sanitized
- **Self-Report:** LLM-Summary wird nicht in System-Prompt injiziert, nur als Chat-Nachricht ausgegeben

### Schicht 4: Rate Limiting
Pattern-Referenz: `self_automation.py:95-98` (bounds-checked `max_per_day`)

| Feature | Limit | Reset |
|---|---|---|
| Outcome Tracker | Max 20 gleichzeitige Observations | Automatisch nach 5min TTL |
| Correction Memory | Max 5 Regeln pro Tag ableiten | Taeglich |
| Self-Report | Max 1 Report pro Tag | Taeglich |
| Error Patterns | Max 1 Mitigation-Wechsel pro Stunde pro Aktionstyp | Stuendlich |
| Adaptive Thresholds | Max 3 Auto-Adjustments pro Woche | Woechentlich |
| Self-Optimization+ | Max 3 Proposals pro Zyklus | Woechentlich |

### Schicht 5: Graceful Degradation
Pattern-Referenz: `anticipation.py:81-82`

Jede Methode beginnt mit:
```python
if not self.enabled or not self.redis:
    return DEFAULT_VALUE  # [], None, 0.5, etc.
```
Wenn Redis ausfaellt, funktioniert Jarvis normal weiter — nur ohne Lern-Features.

### Schicht 6: Audit-Logging
Pattern-Referenz: `self_automation.py:1017-1048` (`_audit()`)

Jede relevante Aktion wird geloggt:
- `logger.info("Outcome [%s]: %s (Room: %s)", outcome, action, room)`
- `logger.info("Korrektur gespeichert: %s -> %s", original, corrected)`
- `logger.info("Neue Regel: %s (confidence: %.2f)", rule_text, conf)`
- `logger.info("Auto-Adjust: %s %s -> %s (%s)", param, old, new, reason)`
- `logger.info("Mitigation aktiviert: %s fuer %s (TTL: %dh)", type, action, ttl)`

### Schicht 7: Circuit Breaker
Pattern-Referenz: `circuit_breaker.py:29-198`

- **Outcome Tracker → HA API:** Nutzt bestehenden `ha_breaker`. HA down → keine Snapshots statt Crash.
- **Self-Report/Self-Opt → Ollama:** Nutzt bestehenden `ollama_breaker`. LLM down → Fallback-Formatierung.
- **Alle → Redis:** Nutzt bestehenden `redis_breaker`. Graceful Degradation.

---

## Zusaetzliche Sicherheitsmassnahmen

### S1. Global Learning Kill Switch

Es gibt `disable_all_jarvis_automations()` fuer Self-Automation, aber keinen globalen Schalter fuer ALLE Lern-Features.

**Loesung:** Neuer Config-Key in settings.yaml:
```yaml
learning:
  enabled: true   # false = ALLE Lern-Features sofort deaktiviert
```

In `brain.py` wird bei `enabled: false` jedes Lern-Feature einzeln deaktiviert.
Sprachbefehl: "Jarvis, stopp alles Lernen" → setzt Flag ueber Self-Automation.

### S2. Data Retention / TTL-Strategie

Alle neuen Redis-Keys haben explizite TTLs:

| Key-Pattern | Feature | TTL | Grund |
|---|---|---|---|
| `mha:outcome:{action_id}` | Outcome Tracker | 90d | Trend-Analyse |
| `mha:outcome:score:{action_type}` | Outcome Tracker | 180d | Langzeit-Scores |
| `mha:correction:{hash}` | Correction Memory | 180d | Regeln leben laenger |
| `mha:correction:rules` | Correction Memory | 365d | Aktive Regeln (mit Decay) |
| `mha:resp_quality:{category}` | Response Quality | 90d | Rolling Window |
| `mha:error_pattern:{type}` | Error Patterns | 30d | Kurzzeitig relevant |
| `mha:error_mitigation:{type}` | Error Patterns | 24h | Automatisch ablaufend |
| `mha:adaptive:{param}` | Adaptive Thresholds | 180d | Langzeit-Optimierung |
| `mha:self_report:last` | Self-Report | 30d | Nur letzte Reports relevant |

Hartes Limit: Kein Feature darf mehr als 5000 Redis-Keys erzeugen.

### S3. Concurrency-Schutz

Redis `SET NX`-Lock Pattern (wie bestehend in `semantic_memory.py:148-166`):

```python
lock_key = f"mha:lock:{lock_name}"
acquired = await self.redis.set(lock_key, "1", nx=True, ex=10)
if not acquired:
    return  # Skip, anderer Prozess arbeitet gerade
```

Kritische Stellen mit Lock:
- Adaptive Thresholds beim Schreiben neuer Schwellwerte
- Self-Optimization beim Anwenden von Vorschlaegen
- Outcome Tracker beim Score-Update (Read-Modify-Write)

### S4. Feature-Konflikt-Aufloesung

Adaptive Thresholds (Feature 4) und Self-Optimization (Feature 9) koennten denselben Parameter aendern.

**Prioritaets-System:**
1. Self-Optimization hat Vorrang (manuell approved)
2. Adaptive Thresholds darf nur aendern was Self-Opt nicht gerade vorgeschlagen hat

Beide Features loggen Aenderungen im selben Audit-Log (`mha:param_changes`).

### S5. Data-Poisoning-Schutz

Schutz gegen falsches Training (absichtlich oder versehentlich):

1. **Anomalie-Erkennung:** >80% negative Outcomes bei >20 Samples → Alert statt Auto-Adjust
2. **Max Change Rate:** Kein Score darf sich um mehr als 20% pro Tag aendern (Smoothing/Clamping)
3. **Widerspruchs-Erkennung:** Gleichzeitig "Danke" + Rueckgaengig → Daten als unzuverlaessig markieren

### S6. Per-Person Data Deletion

Sprachbefehl: "Jarvis, vergiss alles ueber [Person]"

Loescht alle personenbezogenen Daten aus:
- Outcome-Stats pro Person
- Correction-Patterns pro Person
- Response-Quality-Scores pro Person
- Semantic Memory Fakten mit `person={name}`

Bestaetigung erforderlich. Immutable Fakten (Haushalts-Regeln) ausgenommen.

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
| 9. Self-Optimization+ | Ja (via approve) | Ja (manuell) | parameter_bounds | Auto-Rollback + config_versioning |

**Kern-Schutz unangetastet:**
- `_HARDCODED_IMMUTABLE` = {"trust_levels", "security", "autonomy", "dashboard", "models"}
- `_EDITABLE_CONFIGS` = {easter_eggs, opinion_rules, room_profiles}
- `_ALLOWED_FUNCTIONS` frozenset (69 Funktionen)
- Kein exec/eval/subprocess in Tool-Pfaden

**Zusaetzliche Schutzschichten:**
- Global Kill Switch: `learning.enabled: false` deaktiviert ALLE Lern-Features
- 7 Schutzschichten pro Feature (Min-Daten, Decay, Sanitization, Rate Limits, Degradation, Audit, Circuit Breaker)
- Concurrency-Schutz via Redis SET NX Locks
- Feature-Konflikt-Aufloesung (Self-Opt hat Vorrang vor Adaptive Thresholds)
- Data-Poisoning-Schutz (Anomalie-Erkennung, Max Change Rate, Widerspruchs-Erkennung)
- Per-Person Data Deletion ("Vergiss alles ueber X")

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
| `assistant/assistant/brain.py` | Init + Hooks + Kill Switch + forget_person (~130 Zeilen) |
| `assistant/assistant/personality.py` | Learned-Rules-Section (~20 Zeilen) |
| `assistant/assistant/feedback.py` | Per-Person Scores (~15 Zeilen) |
| `assistant/assistant/self_optimization.py` | 9a-9f: Datenquellen, Effectiveness, Auto-Rollback, Parameter, Trends (~80 Zeilen) |
| `assistant/config/settings.yaml` | Neue Sektionen + Bounds + learning.enabled (~60 Zeilen) |

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

# Feature 9: Self-Optimization+ (erweitert bestehende mha:self_opt:* Keys)
mha:self_opt:baseline:{param}                        # HASH (Metriken vor Aenderung, TTL 30d)
mha:self_opt:effect:{param}                          # HASH (Gemessener Effekt, TTL 90d)
mha:self_opt:pending_param:{param}                   # STRING (Konflikt-Guard, TTL 7d)

# Sicherheit: Global Kill Switch
mha:lock:{feature}:{operation}                       # STRING (Concurrency Lock, TTL 10s)

# Sicherheit: Audit
mha:param_changes                                    # LIST (max 200, TTL 180d)
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
9. **Self-Optimization+:** Vorschlag genehmigen → 7 Tage → Log: "Effect: sarcasm_level 3->4: Outcome +5%"
10. **Auto-Rollback:** Wenn Metriken schlechter → Log: "Auto-Rollback: sarcasm_level 4->3 (Outcome -12%)"
11. **Kill Switch:** "Jarvis, stopp alles Lernen" → Log: "GLOBAL: Alle Lern-Features deaktiviert"
12. **Data Deletion:** "Vergiss alles ueber Max" → Log: "Person-Daten geloescht: max (47 Keys)"
13. **Syntax-Check:** `python3 -m py_compile assistant/assistant/outcome_tracker.py` etc.
14. **Logs:** `docker compose logs -f assistant` → Alle neuen Log-Eintraege pruefen

---

## Integrationsanalyse: Exakte Hook-Points in brain.py

Basierend auf vollstaendiger Code-Analyse von `brain.py` (7764 Zeilen). Jeder Hook ist auf die exakte Zeile referenziert.

### I1. Modul-Erstellung (`__init__`, Zeile 170-274)

Neue Module werden am Ende des bestehenden Blocks eingefuegt (~Zeile 265):

```python
# Bestehende letzte Eintraege:
self.music_dj = MusicDJ(self.mood, self.activity)          # Zeile 262
self.visitor_manager = VisitorManager(self.ha, self.camera_manager)  # Zeile 265

# NEU: Self-Improvement Features
from .outcome_tracker import OutcomeTracker
from .correction_memory import CorrectionMemory
from .response_quality import ResponseQualityTracker
from .error_patterns import ErrorPatternTracker
from .self_report import SelfReport
from .adaptive_thresholds import AdaptiveThresholds

self.outcome_tracker = OutcomeTracker(self.ha)
self.correction_memory = CorrectionMemory()
self.response_quality = ResponseQualityTracker()
self.error_patterns = ErrorPatternTracker()
self.self_report = SelfReport(self.ollama)
self.adaptive_thresholds = AdaptiveThresholds()
```

**Risiko:** Keines. Alle Konstruktoren sind sync und leichtgewichtig (nur Config lesen). Redis kommt erst in `initialize()`.

**Potentieller Bug:** Import-Fehler wenn Modul-Datei fehlt → **Mitigation:** Imports innerhalb try/except im Kopf der Datei, Fallback auf `None`.

### I2. Redis-Initialisierung (`initialize()`, Zeile 367-460)

Neue Module nutzen das bestehende `_safe_init` Pattern (F-069, Graceful Degradation):

```python
# Nach bestehenden _safe_init Aufrufen (~Zeile 458):
await _safe_init("OutcomeTracker", self.outcome_tracker.initialize(redis_client=self.memory.redis))
await _safe_init("CorrectionMemory", self.correction_memory.initialize(redis_client=self.memory.redis))
await _safe_init("ResponseQuality", self.response_quality.initialize(redis_client=self.memory.redis))
await _safe_init("ErrorPatterns", self.error_patterns.initialize(redis_client=self.memory.redis))
await _safe_init("SelfReport", self.self_report.initialize(redis_client=self.memory.redis))
await _safe_init("AdaptiveThresholds", self.adaptive_thresholds.initialize(redis_client=self.memory.redis))

# Global Learning Kill Switch pruefen:
if not cfg.yaml_config.get("learning", {}).get("enabled", True):
    self.outcome_tracker.enabled = False
    self.correction_memory.enabled = False
    self.response_quality.enabled = False
    self.error_patterns.enabled = False
    self.adaptive_thresholds.enabled = False
    logger.warning("GLOBAL: Alle Lern-Features deaktiviert (learning.enabled=false)")
```

**Risiko:** Wenn ein Modul `initialize()` failt, wird es durch `_safe_init` als degraded markiert → Jarvis startet trotzdem. ✅

**Potentieller Bug:** Reihenfolge ist wichtig! `SelfReport` braucht Referenzen zu den anderen Modulen. **Loesung:** `SelfReport` bekommt Referenzen NACH der Init-Phase via setter (wie bestehende Module):
```python
self.self_report.set_subsystems(
    outcome_tracker=self.outcome_tracker,
    correction_memory=self.correction_memory,
    response_quality=self.response_quality,
    error_patterns=self.error_patterns,
    feedback=self.feedback,
    learning_observer=self.learning_observer,
)
```

### I3. Mega-Gather: Kontext laden (~Zeile 1940)

Correction Memory Regeln werden parallel mit den bestehenden Intelligence-Fusion-Daten geladen:

```python
# Bestehend (Zeile 1940-1943):
_mega_tasks.append(("anticipation", self.anticipation.get_suggestions()))
_mega_tasks.append(("learned_patterns", self.learning_observer.get_learned_patterns()))
_mega_tasks.append(("insights_now", self.insight_engine.run_checks_now()))
_mega_tasks.append(("experiential", self._get_experiential_hints(text)))

# NEU:
_mega_tasks.append(("correction_rules", self.correction_memory.get_active_rules()))
_mega_tasks.append(("outcome_scores", self.outcome_tracker.get_action_scores()))
_mega_tasks.append(("error_mitigations", self.error_patterns.get_active_mitigations()))
```

**Risiko:** Jeder Task im Mega-Gather laeuft mit `return_exceptions=True` → ein Fehler in einem neuen Task kann die anderen nicht blockieren. ✅

**Potentieller Bug:** Mega-Gather hat schon 15+ Tasks. 3 weitere erhoehen die Parallelitaet. **Analyse:** Alle 3 neuen Tasks sind reine Redis-Reads (<1ms), keine HA-API oder Ollama-Calls → kein Performance-Problem.

### I4. Tool-Execution Hook: Outcome Tracker (~Zeile 2732)

DIREKT nach dem bestehenden Learning-Observer Hook:

```python
# Bestehend (Zeile 2730-2744):
if isinstance(result, dict) and result.get("success"):
    entity_id = final_args.get("entity_id", "")
    if not entity_id:
        r = final_args.get("room", "")
        if r and func_name in ("set_light", "set_cover", "set_climate", "set_switch"):
            domain = func_name.replace("set_", "")
            entity_id = f"{domain}.{r.lower().replace(' ', '_')}"
    if entity_id:
        self._task_registry.create_task(
            self.learning_observer.mark_jarvis_action(entity_id),
            name="mark_jarvis_action",
        )

    # NEU: Outcome Tracker — beobachte ob Aktion gut war
    self._task_registry.create_task(
        self.outcome_tracker.track_action(
            action_type=func_name,
            args=final_args,
            entity_id=entity_id,
            room=final_args.get("room", room or ""),
            person=person or "",
        ),
        name="track_outcome",
    )
```

**Risiko:** `track_action()` startet einen 3-Minuten-Timer im Hintergrund (asyncio.sleep + HA state check). Max 20 gleichzeitige Observations verhindert Memory-Wachstum. ✅

**Potentieller Bug:** Wenn `entity_id` leer ist (z.B. bei `web_search`, `get_weather`), kann der Outcome Tracker keinen State vergleichen. **Loesung:** `track_action()` prüft ob `entity_id` vorhanden — ohne Entity kein State-Snapshot, nur verbal feedback ("Danke") wird getrackt.

### I5. Correction Hook: Erweiterung (~Zeile 3114)

Die bestehende Correction-Erkennung wird ERWEITERT, nicht ersetzt:

```python
# Bestehend (Zeile 3113-3118):
if self._is_correction(text):
    self._task_registry.create_task(
        self._handle_correction(text, response_text, person or "unknown"),
        name="handle_correction",
    )
    # NEU: Auch in Correction Memory speichern
    self._task_registry.create_task(
        self.correction_memory.store_correction(
            original_text=self._last_user_text or "",
            correction_text=text,
            response=response_text,
            person=person or "",
            room=room or "",
            last_action=self._last_executed_action,
        ),
        name="store_correction_memory",
    )
    # NEU: Korrektur = NEGATIVE Outcome
    if self._last_executed_action:
        self._task_registry.create_task(
            self.outcome_tracker.record_correction(self._last_executed_action),
            name="outcome_correction",
        )
```

**Risiko:** Zwei Background-Tasks statt einem. Beide sind fire-and-forget via `_task_registry` → kein Blockieren. ✅

**Potentieller Bug:** `self._last_user_text` existiert noch nicht! **Loesung:** Am Anfang von `process()` (~Zeile 646): `self._last_user_text = text` speichern. Minimal-invasive Aenderung.

### I6. Response Quality Hook: Anfang + Ende von process()

Am **Anfang** von `process()` (~Zeile 646):
```python
self._current_person = person or ""
# NEU: Response Quality — war die letzte Antwort unklar?
rq_rephrase = await self.response_quality.check_rephrase(text)
```

Am **Ende** vor Return (~Zeile 3100):
```python
# NEU: Response Quality — Exchange loggen
category = profile.category if profile else "unknown"
self._task_registry.create_task(
    self.response_quality.record_exchange(
        text=text,
        response=response_text,
        category=category,
        was_rephrase=rq_rephrase,
        person=person or "",
    ),
    name="record_quality",
)
```

**Potentieller Bug:** `check_rephrase()` ist ein async Call im Hot-Path von `process()`. **Analyse:** Es ist ein reiner Redis-Read (letzter User-Text vergleichen) → <1ms. Akzeptabel im Hot-Path.

**Aber:** `check_rephrase()` muss VOR dem Mega-Gather laufen, weil es den vorherigen Text braucht. Position zwischen Person-Setup (~646) und Pre-Classification (~1872) ist korrekt.

### I7. Error Pattern Hook: LLM-Timeout (~Zeile 2412)

```python
# Bestehend (Zeile 2412-2413):
except asyncio.TimeoutError:
    logger.error("LLM Timeout (%ss) fuer Modell %s", llm_timeout, model)

    # NEU: Error Pattern tracken
    self._task_registry.create_task(
        self.error_patterns.record_error(
            error_type="timeout",
            action_type="llm_call",
            model=model,
            context=text[:100],
        ),
        name="track_error_timeout",
    )

    # Bestehend: Fallback-Modell versuchen
    fallback_model = self.model_router.get_fallback_model(model)
```

Zusaetzlich bei Double-Timeout (~Zeile 2429):
```python
except (asyncio.TimeoutError, Exception):
    # NEU:
    self._task_registry.create_task(
        self.error_patterns.record_error(
            error_type="double_timeout",
            action_type="llm_call",
            model=model,
        ),
        name="track_error_double_timeout",
    )
    _err = "Beide Sprachmodelle reagieren nicht..."
```

Und bei General Exception (~Zeile 2445):
```python
except Exception as e:
    logger.error("LLM Exception: %s", e)
    # NEU:
    self._task_registry.create_task(
        self.error_patterns.record_error(
            error_type="exception",
            action_type="llm_call",
            model=model,
            detail=str(e)[:200],
        ),
        name="track_error_exception",
    )
```

**Risiko:** Keines. Alles fire-and-forget in `except`-Bloecken. ✅

### I8. Weekly Report Loop erweitern (~Zeile 7164)

Der bestehende `_weekly_learning_report_loop` wird ersetzt durch eine erweiterte Version:

```python
async def _weekly_learning_report_loop(self):
    """Erweiterter woechentlicher Bericht: Learning + Self-Report + Adaptive + Self-Opt."""
    while True:
        try:
            weekly_cfg = cfg.yaml_config.get("learning", {}).get("weekly_report", {})
            target_day = int(weekly_cfg.get("day", 6))
            target_hour = int(weekly_cfg.get("hour", 19))
            # ... bestehende Scheduling-Logik ...
            await asyncio.sleep(max(wait_seconds, 60))

            if not weekly_cfg.get("enabled", True):
                continue

            # 1. Bestehender Learning Report
            report = await self.learning_observer.get_learning_report()

            # 2. NEU: Self-Report generieren (Feature 3)
            self_report = await self.self_report.generate_report()

            # 3. NEU: Adaptive Thresholds Analyse (Feature 4)
            adjustments = await self.adaptive_thresholds.run_analysis()

            # 4. NEU: Self-Optimization+ Analyse (Feature 9)
            proposals = await self.self_optimization.run_analysis()

            # Bericht zusammenbauen und senden
            if self_report:
                title = get_person_title()
                if await self._callback_should_speak("low"):
                    formatted = await self._safe_format(self_report, "low")
                    await self._speak_and_emit(formatted)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Weekly Report Fehler: %s", e)
            await asyncio.sleep(3600)
```

**Potentieller Bug:** Wenn `self_report.generate_report()` das Ollama LLM aufruft und es einen Timeout gibt, blockiert der gesamte Loop. **Loesung:** Timeout-Wrapper:
```python
try:
    self_report = await asyncio.wait_for(
        self.self_report.generate_report(), timeout=60
    )
except asyncio.TimeoutError:
    self_report = self.self_report.generate_fallback_report()
```

### I9. Prompt-Injection fuer Correction Rules (Feature 7)

Die Correction Rules muessen in den System-Prompt. Bestehender Pattern: `personality.py` baut den System-Prompt-String via `build_system_prompt()`.

Integration in `brain.py` nach dem Mega-Gather (~Zeile 2070), wo der Message-Build passiert:

```python
# Correction Rules als Kontext-Sektion (wie Intelligence Fusion)
correction_rules = _safe_get("correction_rules", [])
if correction_rules:
    rules_text = self.personality.build_learned_rules_section(correction_rules)
    # rules_text wird dem system_prompt_additions hinzugefuegt
```

**Sicherheit:** `build_learned_rules_section()` in `personality.py` wendet `_sanitize_for_prompt()` an. Max 5 Regeln, max 200 Zeichen pro Regel. Kein User-Input wird direkt injiziert — Regeln werden aus Templates gebaut.

---

## Potentielle Bugs und Mitigationen

### Bug 1: `self._last_user_text` existiert nicht
**Wo:** Correction Hook (I5) braucht den vorherigen User-Text
**Fix:** Einfache Zeile am Anfang von `process()`:
```python
self._last_user_text = text  # Zeile 646
```
**Risiko:** Minimal. String-Referenz, kein Memory-Leak.

### Bug 2: Outcome Tracker Timer bei Container-Restart
**Wo:** `track_action()` startet 3-Minuten-Timer. Wenn Container restartet, sind pending Observations weg.
**Fix:** Pending Observations werden in Redis gespeichert (`mha:outcome:pending:{uuid}`, TTL 5min). Beim Start: `_recover_pending_observations()` prueft Redis fuer unabgeschlossene Observations.
**Alternativ:** Ignorieren — verlorene Observations sind kein Problem, weil wir Rolling Averages nutzen.

### Bug 3: Hot-Reload Kompatibilitaet
**Wo:** `config_versioning.reload_config()` aktualisiert `yaml_config` global. Unsere neuen Module lesen Config im `__init__`.
**Fix:** Module muessen `yaml_config` NICHT cachen, sondern bei jedem Aufruf lesen. Pattern:
```python
# FALSCH (cached, reagiert nicht auf Hot-Reload):
self._enabled = cfg.get("enabled", True)

# RICHTIG (dynamisch):
@property
def enabled(self):
    return yaml_config.get("outcome_tracker", {}).get("enabled", True)
```
**Ausnahme:** Performance-kritische Werte (die im Hot-Path gelesen werden) duerfen gecached werden, aber muessen in `reload_config()` aktualisiert werden.

### Bug 4: Race Condition bei Outcome Score Update
**Wo:** Zwei gleichzeitige `track_action()` Callbacks updaten denselben Score
**Fix:** Redis SET NX Lock (S3):
```python
async def _update_score(self, action_type, outcome):
    lock_key = f"mha:lock:outcome:{action_type}"
    if not await self.redis.set(lock_key, "1", nx=True, ex=5):
        return  # Skip, anderer Task updatet gerade
    try:
        # Read-Modify-Write hier
    finally:
        await self.redis.delete(lock_key)
```

### Bug 5: Mega-Gather Timeout
**Wo:** Wenn alle 18+ Mega-Gather Tasks gleichzeitig laufen und Redis langsam ist
**Fix:** Der bestehende `asyncio.gather(*coros, return_exceptions=True)` faengt alle Fehler ab. Neue Tasks sind reine Redis-Reads (<1ms) → kein zusaetzliches Timeout-Risiko.

### Bug 6: Self-Optimization + Adaptive Thresholds Konflikt
**Wo:** Beide laufen im selben weekly-Loop (I8)
**Fix:** Reihenfolge: Adaptive Thresholds ZUERST, dann Self-Optimization. Self-Opt sieht die auto-adjustments und kann sie in seine Analyse einbeziehen. Wenn Self-Opt einen Vorschlag fuer denselben Parameter hat → Adaptive-Adjustment wird nicht gespeichert (S4 Prioritaetssystem).

### Bug 7: Correction Memory Regeln konfligierten
**Wo:** Regel 1: "Abends meint User Schlafzimmer" vs Regel 2: "User meint Wohnzimmer"
**Fix:** Confidence-System. Neuere Korrekturen erhoehen die Confidence der passenden Regel, aeltere decayen. Bei Konflikt gewinnt die hoehere Confidence. Max 20 Regeln mit Garbage Collection.

---

## Error Isolation: Kein Feature darf Jarvis crashen

Jede Methode die von `process()` aufgerufen wird, ist durch mindestens eine dieser Schichten geschuetzt:

1. **`_safe_init` (F-069):** Init-Fehler → Module degraded, Jarvis laeuft trotzdem
2. **`_task_registry.create_task()`:** Background-Tasks fangen Exceptions intern
3. **`return_exceptions=True` im Mega-Gather:** Fehler werden zu Werten statt Crashes
4. **`if not self.enabled or not self.redis: return`:** Graceful Degradation
5. **try/except in jedem Hook:** Explizites Error-Handling

**Worst Case:** Alle 6 neuen Module fallen aus → Jarvis funktioniert exakt wie vorher, nur ohne Lern-Features. Kein bestehender Code wird geaendert oder gebrochen.
