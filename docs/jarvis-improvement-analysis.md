# JARVIS Verbesserungsanalyse — Verifiziert gegen Code

**Datum:** 2026-03-20
**Analysiert:** Alle 98+ Assistant-Module, Brain, Personality, Proactive, Memory, Autonomy

---

## KATEGORIE 1: UNTERUTILISIERTE MODULE

### 1. LearningTransfer — Still und ungenutzt
- **Datei:** `assistant/assistant/learning_transfer.py`
- **Status:** Vollständig implementiert, in brain.py initialisiert, aber nirgends aktiv aufgerufen
- **Problem:** Transfers passieren still ohne User-Benachrichtigung
- **Fix:** Aktiv aufrufen bei neuer Raum-Präferenz + proaktive Nachricht

### 2. PredictiveMaintenance — Naive Berechnung
- **Datei:** `assistant/assistant/predictive_maintenance.py` (453 Zeilen)
- **Problem:** 2-Punkt-Linearextrapolation ohne Ausreißer-Erkennung
- **Fix:** 3-Punkt-Median, health_score mit failure_count verknüpfen

### 3. SeasonalInsight — Nur Monats-basiert
- **Datei:** `assistant/assistant/seasonal_insight.py` (386 Zeilen)
- **Problem:** Saisonerkennung nur auf Monaten, nicht Temperatur/Tageslicht
- **Fix:** Hybrid-Erkennung + vorgefertigte Tipps als LLM-Fallback

### 4. ConversationMemory Threads — Erstellt aber vergessen
- **Datei:** `assistant/assistant/conversation_memory.py`
- **Problem:** Phase 3B Threads werden im Context-Building nicht genutzt
- **Fix:** Thread-Historie in LLM-Kontext einbauen

### 5. KEY_ABSTRACT_CONCEPTS — Toter Code
- **Datei:** `assistant/assistant/learning_observer.py`
- **Problem:** Definiert aber keine Schreibzugriffe
- **Fix:** Implementieren oder entfernen

---

## KATEGORIE 2: FEHLENDE FEEDBACK-LOOPS

### 6. OutcomeTracker → AnticipationEngine
- **Problem:** Kein Rückkanal — fehlgeschlagene Patterns behalten Confidence
- **Fix:** success_score in Pattern-Confidence einfließen lassen

### 7. OutcomeTracker → LearningObserver
- **Problem:** Erfolgreiche Automations-Patterns werden nicht geboostet
- **Fix:** Bei Erfolg +0.1 Confidence-Boost

### 8. CorrectionMemory — Keine Domain-übergreifenden Regeln
- **Problem:** "Raumverwechslung bei Licht" gilt nicht für Klima
- **Fix:** Domain-generische Regeln extrahieren

### 9. FeedbackTracker — Score-Volatilität
- **Problem:** Kein Smoothing, einzelne Events bewegen Score stark
- **Fix:** Exponential Moving Average (70% alt + 30% neu)

### 10. MoodDetector → Personality — Keine Reaktion
- **Problem:** Stimmung erkannt aber Persönlichkeit reagiert nicht
- **Fix:** Bei frustrated 2+: Sarkasmus reduzieren, Klarheit erhöhen

---

## KATEGORIE 3: PROAKTIVITÄT & ANTIZIPATION

### 11. Wetter-Vorhersage nicht genutzt
- **Problem:** Nur aktuelles Wetter, nicht Forecast
- **Fix:** HA Wetter-Forecast-API für cover-Planung

### 12. Keine Routine-Anomalie-Erkennung
- **Problem:** Kennt Routinen, erkennt nicht wenn sie ausbleiben
- **Fix:** Expected vs. actual tracken, sanft nachfragen

### 13. Proaktive Nachrichten ohne Persönlichkeit
- **Problem:** Generische Templates statt Jarvis-Flavor
- **Fix:** Durch PersonalityEngine filtern

### 14. Think-Ahead nicht implementiert
- **Problem:** last_action Parameter existiert aber wird nie übergeben
- **Fix:** Nach Funktion: Folge-Aktion vorschlagen

### 15. What-If Reasoning passiv
- **Problem:** Nur als Kontext-Hint, nie aktive Frage
- **Fix:** Bei Confidence >0.7 aktiv vorschlagen

### 16. Keine implizite Bedürfnis-Erkennung
- **Problem:** Nur bekannte Patterns, keine First-Time-Szenarien
- **Fix:** Kontext-basierte Needs-Detection als neuen Pattern-Typ

---

## KATEGORIE 4: PERSÖNLICHKEIT & EMOTIONEN

### 17. InnerState ohne Mood-Decay
- **Problem:** Stimmung persistiert bis nächstes Event
- **Fix:** Zeitbasierten Decay implementieren

### 18. Kein Emotion Blending
- **Problem:** Einzelne _mood Variable, kein Mix
- **Fix:** Dict mit Gewichtungen

### 19. InnerState Trigger zu flach
- **Problem:** Jeder Erfolg/Fehler gleich gewichtet
- **Fix:** Domain-spezifische Confidence-Deltas

### 20. Keine neuen Traits über Zeit
- **Problem:** Formality decayed, aber keine neuen Humor-Stile
- **Fix:** Stage-basierte Trait-Unlocks

### 21. Transition-Kommentare unsichtbar
- **Problem:** Definiert aber nie in Antworten injiziert
- **Fix:** Als optionalen Zusatz einbauen

---

## KATEGORIE 5: KONTEXT & INTELLIGENZ

### 22. HA-States nicht gecacht
- **Problem:** get_states() bei jeder Context-Erstellung
- **Fix:** 5-10s Cache mit Event-basierter Invalidierung

### 23. DeviceHealth ohne saisonale Baseline
- **Problem:** Winter-Baseline im Sommer angewendet
- **Fix:** Baselines mit Monat taggen

### 24. HealthMonitor ohne Hysterese
- **Problem:** Alert-Flapping bei Grenzwerten
- **Fix:** Warn bei >Schwelle, clear bei <(Schwelle-2%)

### 25. HealthMonitor nicht raumspezifisch
- **Problem:** Gleiche Schwellen für alle Räume
- **Fix:** Raum-Level-Overrides in Config

### 26. CalendarIntelligence Pendel-Zeit hardcoded
- **Problem:** Ein globaler Wert
- **Fix:** Per (von, zu) Zeiten speichern

### 27. Activity ohne Confidence-Scoring
- **Problem:** Binärer State, kein "wahrscheinlich"
- **Fix:** Confidence 0.0-1.0 einführen

---

## KATEGORIE 6: ENERGIEOPTIMIERUNG

### 28. Keine Preis-Vorhersage
- **Problem:** Nur aktueller Preis vs. Schwelle
- **Fix:** Trend aus Historie oder ENTSO-E API

### 29. Load-Empfehlung ohne Status-Check
- **Problem:** Empfiehlt laufende Geräte
- **Fix:** Entity-State prüfen

### 30. Keine Solar-Vorhersage
- **Problem:** Nur aktuelle Produktion
- **Fix:** Weather Forecast für Prognose

---

## KATEGORIE 7: AUTONOMIE & SICHERHEIT

### 31. Core Identity ohne Runtime-Enforcement
- **Problem:** Nur Textblock, keine Validierung
- **Fix:** IdentityValidator für Self-Optimization

### 32. ProactivePlanner minimal (391 Zeilen)
- **Problem:** Kein Rollback, keine parallele Ausführung
- **Fix:** Rollback-Logik, mehr Trigger

### 33. Vacation-Simulation mit RNG
- **Problem:** Zufällig statt gelernte Muster
- **Fix:** Patterns nachspielen mit Offset

---

## KATEGORIE 8: QUICK WINS

### 34. Semantic Memory ohne Fakt-Versionierung
- **Problem:** Alte Fakten stillschweigend gelöscht
- **Fix:** Versions-Kette mit Timestamp

### 35. Widersprüche ohne Nachfrage
- **Problem:** Detection existiert, User wird nie gefragt
- **Fix:** Proaktive Klärungsfrage

### 36. InsightEngine dupliziert Alerts
- **Problem:** Gleiche Entity, mehrere Checks, mehrere Alerts
- **Fix:** Deduplizierung nach Entity + Check-Type

### 37. WellnessAdvisor ignoriert Away-State
- **Problem:** Erinnerungen auch wenn keiner zuhause
- **Fix:** activity.away prüfen

### 38. DialogueState nur 10 Referenzen
- **Problem:** Lange Gespräche verlieren frühe Referenzen
- **Fix:** Auf 20 erhöhen oder semantisch gruppieren

---

## TOP 10 NACH IMPACT

| # | Verbesserung | Aufwand | Impact |
|---|---|---|---|
| 1 | Wetter-Forecast für Antizipation (11) | ~50 Zeilen | Verhindert Wasserschäden |
| 2 | Outcome→Anticipation Feedback (6) | ~40 Zeilen | Selbstkorrigierende Patterns |
| 3 | Mood→Personality Reaktion (10) | ~30 Zeilen | Menschlicherer Jarvis |
| 4 | Think-Ahead implementieren (14) | ~60 Zeilen | MCU-Jarvis-Level |
| 5 | Routine-Anomalie-Erkennung (12) | ~100 Zeilen | Fürsorge-Feature |
| 6 | InnerState Mood-Decay (17) | ~20 Zeilen | Realistischere Emotionen |
| 7 | DeviceHealth saisonale Baseline (23) | ~40 Zeilen | Weniger False Positives |
| 8 | HealthMonitor Hysterese (24) | ~10 Zeilen | Kein Alert-Flapping |
| 9 | Widerspruch-Nachfrage (35) | ~40 Zeilen | Besseres Gedächtnis |
| 10 | LearningTransfer aktivieren (1) | ~30 Zeilen | Schnelleres Lernen |

---

## KATEGORIE 9: AUTONOMIE & SICHERHEIT (KRITISCH)

### 39. Threat Playbooks werden NICHT ausgeführt
- **Datei:** `assistant/assistant/threat_assessment.py` (1011 Zeilen)
- **Problem:** 5 Emergency-Playbooks (Brand, Einbruch, Wasser, Strom, Notfall) existieren als Pläne, aber es gibt keinen Executor
- **Impact:** KRITISCH — Bei Feuer plant Jarvis Aktionen, führt sie aber nicht aus
- **Fix:** `execute_playbook()` implementieren die ha_actions tatsächlich ausführt

### 40. Keine Autonomie-Eskalation bei Notfall
- **Problem:** Level bleibt gleich bei Normalzustand und Feueralarm
- **Fix:** Temporärer Level-Boost auf 5 bei Emergency mit Auto-Reset

### 41. Keine Autonomie-De-Eskalation
- **Problem:** Levels gehen nur hoch, nie runter
- **Fix:** Bei acceptance <50% für 7 Tage → Level-Reduktion vorschlagen

### 42. Keine temporale Autonomie
- **Problem:** Gleicher Level Tag und Nacht
- **Fix:** temporal_profile als Offset (night: -1, day: +0)

### 43. Service-Whitelist dupliziert
- **Dateien:** `function_validator.py` + `self_automation.py`
- **Problem:** Separate Whitelist-Listen die auseinanderdriften können
- **Fix:** Single Source of Truth

### 44. Conflict Resolver nur reaktiv
- **Problem:** Erkennt Konflikte erst nach beiden Kommandos
- **Fix:** Prediction basierend auf kürzlichen Aktionen

### 45. Pushback lernt nicht
- **Problem:** Gleiche Warnung kommt auch nach 10× Override
- **Fix:** Override-Rate tracken, bei >80% unterdrücken

---

## AKTUALISIERTE TOP 10 NACH IMPACT

| # | Verbesserung | Aufwand | Impact |
|---|---|---|---|
| 1 | **Threat Playbook Executor (39)** | ~80 Zeilen | KRITISCH — Sicherheit |
| 2 | Wetter-Forecast für Antizipation (11) | ~50 Zeilen | Verhindert Wasserschäden |
| 3 | Notfall-Autonomie-Eskalation (40) | ~40 Zeilen | Sicherheitskritisch |
| 4 | Outcome→Anticipation Feedback (6) | ~40 Zeilen | Selbstkorrigierende Patterns |
| 5 | Mood→Personality Reaktion (10) | ~30 Zeilen | Menschlicherer Jarvis |
| 6 | Think-Ahead implementieren (14) | ~60 Zeilen | MCU-Jarvis-Level |
| 7 | Routine-Anomalie-Erkennung (12) | ~100 Zeilen | Fürsorge-Feature |
| 8 | InnerState Mood-Decay (17) | ~20 Zeilen | Realistischere Emotionen |
| 9 | HealthMonitor Hysterese (24) | ~10 Zeilen | Kein Alert-Flapping |
| 10 | Service-Whitelist vereinheitlichen (43) | ~20 Zeilen | Code-Qualität |

---

## UI-KONFIGURATION — Implementierungsplan

> **WICHTIG:** Alle Einstellungen werden im **Jarvis Assistant UI** (`assistant/static/ui/app.js`) konfigurierbar gemacht.
> NICHT im MindHome Add-on UI! Die UI nutzt die bestehenden Form-Builder (`fToggle`, `fRange`, `fSelect`, `fNum`, `fText`, `fChipSelect`, `fTextarea`, `fSubheading`, `fInfo`, `sectionWrap`).
> Settings werden über `settings.yaml` persistiert und via `/api/ui/settings` GET/PUT synchronisiert.
> Bestehende Sektionen werden erweitert — KEINE Duplikate erzeugen.

### UI-Stil-Referenz

- **Theme:** Cyan-blaues Holographic-HUD (Jarvis MCU-inspiriert)
- **Schrift:** JetBrains Mono (technisch), Outfit (UI)
- **Sections:** `sectionWrap(icon, title, content)` — einklappbar
- **Toggles:** `fToggle(path, label)`
- **Slider:** `fRange(path, label, min, max, step, presets)` — presets als `{value:'label'}`
- **Dropdown:** `fSelect(path, label, [{v:value, l:label}])`
- **Nummer:** `fNum(path, label, min, max, step)`
- **Chips:** `fChipSelect(path, label, items, hint)`
- **Info:** `fInfo(text)` — Hilfe-Infobox
- **Tabs:** Bestehende Tabs: `tab-security`, `tab-autonomie`, `tab-intelligence`
- **Suchindex:** `_searchIndex` in app.js (Zeile 24-170) — neue Sektionen dort eintragen

---

### TAB: Sicherheit (`tab-security` → `renderSecurity()`)

#### Bestehende Sektion erweitern: "Notfall-Protokolle" (Zeile 5587)

**Neue Settings darunter einfügen (NICHT duplizieren):**

```javascript
// --- Threat Assessment Konfiguration (unter Notfall-Protokolle) ---
fSubheading('Bedrohungserkennung') +
fInfo('Konfiguriert wann und wie Jarvis Bedrohungen erkennt. Die Nacht-Stunden definieren den Zeitraum für erhöhte Wachsamkeit bei Bewegungserkennung.') +
fToggle('threat_assessment.enabled', 'Bedrohungserkennung aktiv') +
fToggle('threat_assessment.auto_execute_playbooks', 'Playbooks automatisch ausführen') +
fRange('threat_assessment.night_start_hour', 'Nacht-Start (Uhr)', 20, 23, 1,
  {20:'20:00',21:'21:00',22:'22:00 (Standard)',23:'23:00'}) +
fRange('threat_assessment.night_end_hour', 'Nacht-Ende (Uhr)', 5, 8, 1,
  {5:'05:00',6:'06:00 (Standard)',7:'07:00',8:'08:00'}) +
fNum('threat_assessment.motion_cooldown_minutes', 'Bewegungs-Cooldown (Min.)', 5, 60, 5) +
fNum('threat_assessment.state_max_age_minutes', 'Max. Sensor-Alter (Min.)', 5, 30, 5) +
fSubheading('Eskalation') +
fToggle('threat_assessment.emergency_autonomy_boost', 'Autonomie-Boost bei Notfall (→ Level 5)') +
fRange('threat_assessment.emergency_boost_duration_min', 'Boost-Dauer (Min.)', 5, 60, 5,
  {5:'5',10:'10',15:'15 (Standard)',30:'30',60:'60'})
```

**settings.yaml Erweiterung:**
```yaml
threat_assessment:
  enabled: true
  auto_execute_playbooks: false        # Sicherheits-Default: aus
  night_start_hour: 22
  night_end_hour: 6
  motion_cooldown_minutes: 30
  state_max_age_minutes: 10
  emergency_autonomy_boost: false      # Sicherheits-Default: aus
  emergency_boost_duration_min: 15
```

**Suchindex-Eintrag:**
```javascript
{tab:'tab-security', title:'Bedrohungserkennung', keywords:'bedrohung threat nacht bewegung einbruch eskalation notfall playbook cooldown', icon:'&#128680;'}
```

---

#### Bestehende Sektion erweitern: "Sicherheit" (Zeile 5481)

**Pushback-Lernfunktion (unter bestehende Bestätigungs-Chips):**

```javascript
fSubheading('Pushback-Verhalten') +
fInfo('Pushback sind Warnungen wenn eine Aktion im Kontext problematisch ist (z.B. "Heizung an bei offenem Fenster"). Lernfunktion: Wenn du eine Warnung oft ignorierst, wird sie seltener angezeigt.') +
fToggle('pushback.learning_enabled', 'Pushback-Lernfunktion') +
fRange('pushback.suppress_after_overrides', 'Unterdrücken nach X Overrides', 3, 20, 1,
  {3:'3',5:'5 (Standard)',10:'10',15:'15',20:'20'}) +
fRange('pushback.suppress_duration_days', 'Unterdrückungsdauer (Tage)', 7, 90, 7,
  {7:'1 Woche',14:'2 Wochen',30:'1 Monat (Standard)',60:'2 Monate',90:'3 Monate'})
```

**settings.yaml Erweiterung:**
```yaml
pushback:
  # ... bestehende Settings ...
  learning_enabled: false
  suppress_after_overrides: 5
  suppress_duration_days: 30
```

---

#### Bestehende Sektion erweitern: "Konflikt-Sicherheitsgrenzen" (Zeile 5599)

**Conflict Prediction (unter bestehende Aktive Konflikt-Regeln):**

```javascript
fSubheading('Konflikt-Vorhersage') +
fInfo('Warnt proaktiv wenn eine gerade gegebene Anweisung mit einer kürzlichen Aktion kollidieren wird. Z.B. "Achtung: Anna hat vor 2 Min. runtergekühlt."') +
fToggle('conflict_resolution.prediction_enabled', 'Konflikt-Vorhersage') +
fRange('conflict_resolution.prediction_window_seconds', 'Vorhersage-Zeitfenster (Sek.)', 60, 600, 30,
  {60:'1 Min',120:'2 Min',180:'3 Min (Standard)',300:'5 Min',600:'10 Min'}) +
fSubheading('Multi-User Mediation') +
fSelect('conflict_resolution.mediation.model', 'Mediations-Modell', modelOptions) +
fNum('conflict_resolution.mediation.max_tokens', 'Max. Tokens', 128, 512, 64)
```

**settings.yaml Erweiterung:**
```yaml
conflict_resolution:
  # ... bestehende Settings ...
  prediction_enabled: false
  prediction_window_seconds: 180
```

---

### TAB: Autonomie (`tab-autonomie` → `renderAutonomie()`)

#### Bestehende Sektion erweitern: "Autonomie-Stufen & Berechtigungen" (Zeile 6029)

**Temporale Autonomie + De-Eskalation (nach "Automatische Evolution"):**

```javascript
fSubheading('Temporale Autonomie') +
fInfo('Unterschiedlicher Autonomie-Level je nach Tageszeit. Offset wird auf das aktuelle Level addiert. "-1" nachts bedeutet z.B. Level 3 → Level 2 zwischen 22-7 Uhr.') +
fToggle('autonomy.temporal.enabled', 'Temporale Autonomie aktiv') +
fRange('autonomy.temporal.night_offset', 'Nacht-Offset (22-7 Uhr)', -3, 0, 1,
  {'-3':'-3','-2':'-2','-1':'-1 (Standard)','0':'Aus'}) +
fRange('autonomy.temporal.day_offset', 'Tag-Offset (7-22 Uhr)', 0, 2, 1,
  {'0':'±0 (Standard)','1':'+1','2':'+2'}) +

fSubheading('De-Eskalation') +
fInfo('Automatische Level-Reduktion wenn die Akzeptanzrate dauerhaft niedrig ist. Jarvis schlägt dann eine Rückstufung vor — führt sie nie selbst durch.') +
fToggle('autonomy.deescalation.enabled', 'De-Eskalation aktiv') +
fRange('autonomy.deescalation.min_acceptance_rate', 'Schwelle Akzeptanzrate', 0.3, 0.7, 0.05,
  {0.3:'30%',0.4:'40%',0.5:'50% (Standard)',0.6:'60%',0.7:'70%'}) +
fNum('autonomy.deescalation.evaluation_days', 'Bewertungszeitraum (Tage)', 3, 14, 1)
```

**settings.yaml Erweiterung:**
```yaml
autonomy:
  # ... bestehende Settings ...
  temporal:
    enabled: false
    night_offset: -1
    day_offset: 0
  deescalation:
    enabled: false
    min_acceptance_rate: 0.5
    evaluation_days: 7
```

---

#### Bestehende Sektion erweitern: "Lern-System & Selbstoptimierung" (Zeile 6073)

**Outcome→Anticipation Feedback (nach "Wirkungstracker"):**

```javascript
fSubheading('Feedback-Loops') +
fInfo('Verbindet den Wirkungstracker mit der Antizipation: Fehlgeschlagene Vorhersagen verlieren Konfidenz, erfolgreiche werden gestärkt.') +
fToggle('outcome_tracker.anticipation_feedback', 'Anticipation-Feedback aktiv') +
fRange('outcome_tracker.success_confidence_boost', 'Erfolgs-Boost', 0.05, 0.2, 0.01,
  {0.05:'0.05',0.1:'0.1 (Standard)',0.15:'0.15',0.2:'0.2'}) +
fRange('outcome_tracker.failure_confidence_penalty', 'Fehl-Penalty', 0.05, 0.3, 0.01,
  {0.05:'0.05',0.1:'0.1',0.15:'0.15 (Standard)',0.2:'0.2',0.3:'0.3'})
```

**settings.yaml Erweiterung:**
```yaml
outcome_tracker:
  # ... bestehende Settings ...
  anticipation_feedback: true
  success_confidence_boost: 0.1
  failure_confidence_penalty: 0.15
```

---

### TAB: Intelligenz (`tab-intelligence` → `renderIntelligence()`)

#### Bestehende Sektion erweitern: "Erklärbarkeit" (Zeile 11787)

**Erweiterte Erklärbarkeit (nach "Max. gespeicherte Entscheidungen"):**

```javascript
fSubheading('Erweiterte Erklaerungen') +
fToggle('explainability.counterfactual_enabled', 'Was-waere-wenn Erklaerungen') +
fToggle('explainability.reasoning_chains', 'Kausalketten anzeigen') +
fToggle('explainability.confidence_display', 'Konfidenz in Erklaerungen') +
fSelect('explainability.explanation_style', 'Erklärungs-Stil', [
  {v:'template', l:'Template (schnell, deterministic)'},
  {v:'llm', l:'LLM (natuerlich, Butler-Stil)'},
  {v:'auto', l:'Auto (Template fuer einfach, LLM fuer komplex)'}
])
```

**settings.yaml Erweiterung:**
```yaml
explainability:
  # ... bestehende Settings ...
  counterfactual_enabled: true
  reasoning_chains: false
  confidence_display: false
  explanation_style: auto
```

---

#### Neue Sektion: "Routine-Anomalie-Erkennung" (nach "Routine-Abweichungen" Zeile 11844)

```javascript
sectionWrap('&#128680;', 'Routine-Anomalie-Erkennung',
  fInfo('Erkennt wenn erwartete Routinen ausbleiben und fragt sanft nach. Z.B. "Du gehst normalerweise um 7:30 aus dem Haus — heute nicht. Alles okay?" Nur bei hoher Konfidenz und nie nachts.') +
  fToggle('routine_anomaly.enabled', 'Anomalie-Erkennung aktiv') +
  fRange('routine_anomaly.min_confidence', 'Min. Konfidenz', 0.6, 0.95, 0.05,
    {0.6:'60%',0.7:'70%',0.8:'80% (Standard)',0.9:'90%',0.95:'95%'}) +
  fRange('routine_anomaly.grace_period_minutes', 'Toleranz (Minuten)', 10, 60, 5,
    {10:'10',15:'15',20:'20',30:'30 (Standard)',45:'45',60:'60'}) +
  fNum('routine_anomaly.max_daily_checks', 'Max. Nachfragen pro Tag', 1, 5, 1) +
  fNum('routine_anomaly.min_pattern_days', 'Min. Tage für Routine', 7, 30, 1)
)
```

**settings.yaml Erweiterung:**
```yaml
routine_anomaly:
  enabled: false
  min_confidence: 0.8
  grace_period_minutes: 30
  max_daily_checks: 2
  min_pattern_days: 14
```

**Suchindex-Eintrag:**
```javascript
{tab:'tab-intelligence', title:'Routine-Anomalie-Erkennung', keywords:'routine anomalie abwesenheit check nachfrage sorge muster', icon:'&#128680;'}
```

---

#### Bestehende Sektion erweitern: "Saisonale Intelligenz" (Zeile 11853)

**Wetter-Forecast Integration (nach bestehenden Settings):**

```javascript
fSubheading('Wetter-Vorhersage') +
fInfo('Nutzt die HA Wetter-Forecast-API für vorausschauende Aktionen: Rollläden schliessen bevor Sturm kommt, Heizung hochdrehen bevor es kalt wird.') +
fToggle('weather_forecast.enabled', 'Wetter-Vorhersage aktiv') +
fNum('weather_forecast.lookahead_hours', 'Vorhersage-Horizont (Stunden)', 2, 24, 2) +
fText('weather_forecast.entity', 'Wetter-Entity', 'z.B. weather.home')
```

**settings.yaml Erweiterung:**
```yaml
weather_forecast:
  enabled: false
  lookahead_hours: 6
  entity: weather.home
```

---

### TAB: Jarvis-Features (`tab-jarvis`)

#### Bestehende Sektion "Stimmungs-Stile" erweitern

**Mood→Personality Reaktion (Verbesserung 10):**

```javascript
fSubheading('Stimmungs-Reaktion') +
fInfo('Jarvis passt seinen Kommunikationsstil an die erkannte Stimmung an. Bei Frustration: weniger Sarkasmus, klarere Sprache. Bei guter Laune: mehr Humor.') +
fToggle('mood_reaction.enabled', 'Stimmungs-Reaktion aktiv') +
fRange('mood_reaction.frustration_sarcasm_reduction', 'Sarkasmus-Reduktion bei Stress', 0, 3, 1,
  {0:'Keine',1:'-1 Level',2:'-2 Level (Standard)',3:'-3 Level'}) +
fRange('mood_reaction.frustration_threshold', 'Frustrations-Schwelle', 1, 3, 1,
  {1:'Leicht',2:'Mittel (Standard)',3:'Stark'})
```

**settings.yaml Erweiterung:**
```yaml
mood_reaction:
  enabled: true
  frustration_sarcasm_reduction: 2
  frustration_threshold: 2
```

---

#### Bestehende Sektion erweitern für InnerState Mood-Decay (Verbesserung 17)

**In "Stil & Charakter" Sektion:**

```javascript
fSubheading('Emotionaler Zerfall') +
fInfo('Jarvis-Stimmungen klingen natuerlich ab statt abrupt zu wechseln. Ein stolzer Jarvis wird langsam wieder neutral, statt sofort umzuschalten.') +
fToggle('inner_state.mood_decay_enabled', 'Mood-Decay aktiv') +
fRange('inner_state.mood_decay_minutes', 'Zerfallszeit (Minuten)', 10, 120, 10,
  {10:'10',20:'20',30:'30 (Standard)',60:'60',120:'120'})
```

**settings.yaml Erweiterung:**
```yaml
inner_state:
  mood_decay_enabled: true
  mood_decay_minutes: 30
```

---

### TAB: Klima & Haus (`tab-house-status`)

#### HealthMonitor Hysterese (Verbesserung 24)

**In bestehende HealthMonitor-Sektion einfügen:**

```javascript
fSubheading('Alert-Hysterese') +
fInfo('Verhindert Alert-Flapping an Grenzwerten. Warnung bei Ueberschreitung, Entwarnung erst bei (Schwelle - Puffer). Verhindert "CO2 hoch/normal/hoch" alle 2 Minuten.') +
fToggle('health_monitor.hysteresis_enabled', 'Hysterese aktiv') +
fRange('health_monitor.hysteresis_pct', 'Puffer (%)', 1, 10, 1,
  {1:'1%',2:'2% (Standard)',3:'3%',5:'5%',10:'10%'})
```

**settings.yaml Erweiterung:**
```yaml
health_monitor:
  # ... bestehende Settings ...
  hysteresis_enabled: true
  hysteresis_pct: 2
```

---

### ZUSAMMENFASSUNG UI-ÄNDERUNGEN

| Tab | Sektion | Aktion | Neue Settings |
|-----|---------|--------|---------------|
| Security | Notfall-Protokolle | Erweitern | `threat_assessment.*` (8 Settings) |
| Security | Sicherheit | Erweitern | `pushback.learning_*` (3 Settings) |
| Security | Konflikt-Sicherheitsgrenzen | Erweitern | `conflict_resolution.prediction_*` (3 Settings) |
| Autonomie | Autonomie-Stufen | Erweitern | `autonomy.temporal.*`, `autonomy.deescalation.*` (7 Settings) |
| Autonomie | Lern-System | Erweitern | `outcome_tracker.anticipation_*` (3 Settings) |
| Intelligenz | Erklärbarkeit | Erweitern | `explainability.*` (4 Settings) |
| Intelligenz | NEU: Routine-Anomalie | Neue Sektion | `routine_anomaly.*` (5 Settings) |
| Intelligenz | Saisonale Intelligenz | Erweitern | `weather_forecast.*` (3 Settings) |
| Jarvis | Stimmungs-Stile | Erweitern | `mood_reaction.*` (3 Settings) |
| Jarvis | Stil & Charakter | Erweitern | `inner_state.mood_decay_*` (2 Settings) |
| Haus-Status | HealthMonitor | Erweitern | `health_monitor.hysteresis_*` (2 Settings) |

**Gesamt: 43 neue konfigurierbare Settings verteilt auf 5 Tabs, 11 Sektionen (10 erweitert, 1 neu)**

### Validierung in Backend (`main.py` → `_validate_settings_values()`)

Alle neuen Settings müssen in der Validierung ergänzt werden:

```python
# threat_assessment
_clamp("threat_assessment.night_start_hour", 20, 23)
_clamp("threat_assessment.night_end_hour", 5, 8)
_clamp("threat_assessment.motion_cooldown_minutes", 5, 60)
_clamp("threat_assessment.state_max_age_minutes", 5, 30)
_clamp("threat_assessment.emergency_boost_duration_min", 5, 60)

# pushback learning
_clamp("pushback.suppress_after_overrides", 3, 20)
_clamp("pushback.suppress_duration_days", 7, 90)

# conflict prediction
_clamp("conflict_resolution.prediction_window_seconds", 60, 600)

# temporal autonomy
_clamp("autonomy.temporal.night_offset", -3, 0)
_clamp("autonomy.temporal.day_offset", 0, 2)

# deescalation
_clamp("autonomy.deescalation.min_acceptance_rate", 0.3, 0.7)
_clamp("autonomy.deescalation.evaluation_days", 3, 14)

# outcome feedback
_clamp("outcome_tracker.success_confidence_boost", 0.05, 0.2)
_clamp("outcome_tracker.failure_confidence_penalty", 0.05, 0.3)

# explainability
# detail_level, explanation_style: enum validation

# routine anomaly
_clamp("routine_anomaly.min_confidence", 0.6, 0.95)
_clamp("routine_anomaly.grace_period_minutes", 10, 60)
_clamp("routine_anomaly.max_daily_checks", 1, 5)
_clamp("routine_anomaly.min_pattern_days", 7, 30)

# weather forecast
_clamp("weather_forecast.lookahead_hours", 2, 24)

# mood reaction
_clamp("mood_reaction.frustration_sarcasm_reduction", 0, 3)
_clamp("mood_reaction.frustration_threshold", 1, 3)

# inner state
_clamp("inner_state.mood_decay_minutes", 10, 120)

# health monitor
_clamp("health_monitor.hysteresis_pct", 1, 10)
```

### Implementierungsreihenfolge

1. **settings.yaml.example** — Alle neuen Defaults eintragen
2. **Backend-Module** — Logik implementieren + `yaml_config.get()` Zugriffe
3. **main.py** — Validierung in `_validate_settings_values()` ergänzen
4. **app.js** — UI-Felder in bestehende Sektionen einfügen
5. **Suchindex** — Neue Sektionen in `_searchIndex` Array eintragen
6. **Tests** — Neue Settings in Tests abdecken
