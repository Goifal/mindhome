# Verbesserungsplan: MindHome/Jarvis — Alle 8 Bereiche

> Strategie: Bestehende Module erweitern, keine neuen Module erstellen.
> Alle Claims gegen den tatsächlichen Code verifiziert (18.03.2026).

---

## Bereich 1: Personality Integration — Unified Character State

**IST:** Zwei unabhängige Streams (User-Mood via MoodDetector, Jarvis-Mood via InnerStateEngine) ohne Cross-Talk. Sarcasm, Formality, Opinion Intensity sind separate Knöpfe ohne gemeinsamen State. (`inner_state.py` hat keine Referenz zu `mood_detector.py` und umgekehrt — verifiziert per Grep.)

**SOLL:** Bidirektionale Beeinflussung — User-Frustration sollte Jarvis besorgt machen; Jarvis-Irritation sollte Sarkasmus dämpfen.

### Änderungen

**Datei: `assistant/assistant/inner_state.py`**
- Neue Methode `on_user_mood_change(mood: str, person: str)` hinzufügen
- Mapping: user frustrated → Jarvis concerned, user good → Jarvis satisfied (mit Decay)
- Aufruf von `_update_mood()` nach User-Mood-Events
- ~30 Zeilen

**Datei: `assistant/assistant/personality.py`**
- In `_build_humor_section()` (Zeile ~1883): Jarvis `inner_state.mood` in effective_level einbeziehen
  - Jarvis irritiert → `effective_level = max(1, effective_level - 1)`
  - Jarvis amüsiert → `effective_level = min(4, effective_level + 1)`
- In `check_opinion()` (Zeile ~970): Bei Jarvis-Mood "concerned" ebenfalls Opinions unterdrücken
- ~20 Zeilen

**Datei: `assistant/assistant/brain.py`**
- Nach Mood-Detection (wo `self.mood.detect_mood()` aufgerufen wird): Ergebnis an `self.inner_state.on_user_mood_change()` weiterleiten
- ~5 Zeilen

**Tests:**
- `test_inner_state.py`: Test für `on_user_mood_change()` mit verschiedenen User-Moods
- `test_personality.py`: Test dass Jarvis-Mood die effective sarcasm/opinion beeinflusst

---

## Bereich 2: Kausales Gedächtnis — Outcome-Feedback-Loop

**IST:** Outcome Tracker speichert Erfolg/Misserfolg, aber:
- Kein direkter Feedback an Anticipation (`anticipation.py` hat null Referenzen zu `outcome_tracker` — verifiziert per Grep)
- Der indirekte Pfad über `adaptive_thresholds.py` (Zeile 211-218) ist effektiv tot: `outcome_tracker.get_success_score("anticipation")` liefert immer Default 0.5, weil kein Code Anticipation-Actions unter dem Key "anticipation" trackt
- Keine Blocklist bei wiederholtem Versagen (verifiziert: kein `blocklist`/`ban`/`block` in outcome_tracker.py)
- Correction Memory nur im Prompt (`brain.py` Zeile 3499-3503), nicht in Anticipation (verifiziert per Grep)

**SOLL:** Geschlossener Feedback-Loop: Outcome → Anticipation-Konfidenz, wiederholte Fehler → Soft-Block.

### Änderungen

**Datei: `assistant/assistant/anticipation.py`**
- Neue Methode `set_outcome_tracker(tracker)` — speichert Referenz als `self._outcome_tracker`
- In `_detect_time_patterns()` und `_detect_sequence_patterns()`:
  Nach Pattern-Erkennung `self._outcome_tracker.get_success_score(action_type, person)` abfragen
  - Score < 0.3 → Konfidenz des Patterns um 30% reduzieren
  - Score > 0.8 → Konfidenz um 10% erhöhen
- In `get_suggestions()` (Zeile ~643): Fehlende `elif pattern["type"] == "causal_chain"` Branch hinzufügen — analog zu den bestehenden Branches für time/sequence/context
- ~40 Zeilen

**Datei: `assistant/assistant/outcome_tracker.py`**
- Neue Methode `is_soft_blocked(action_type: str, person: str) -> bool`:
  - 3+ aufeinanderfolgende Failures für dieselbe action_type+person Kombination → True
  - Reset bei nächstem Erfolg
  - Redis-Key: `mha:outcome:softblock:{action_type}:{person}`
- ~25 Zeilen

**Datei: `assistant/assistant/brain.py`**
- Bei Anticipation-Init: `self.anticipation.set_outcome_tracker(self.outcome_tracker)` aufrufen
- Vor Auto-Execute in Anticipation-Flow: `outcome_tracker.is_soft_blocked()` prüfen
- ~10 Zeilen

**Datei: `assistant/assistant/adaptive_thresholds.py`**
- Den toten Pfad reparieren: In `anticipation.py` bei Auto-Execute-Aktionen `outcome_tracker.track_action()` mit action_type `"anticipation:{original_action}"` aufrufen, damit `adaptive_thresholds` echte Daten bekommt

**Tests:**
- `test_anticipation.py`: Test Confidence-Modulation durch Outcome-Score
- `test_outcome_tracker.py`: Test Soft-Block nach 3 Failures, Reset nach Erfolg

---

## Bereich 3: Multi-Signal Antizipation

**IST:**
- `log_action()` hat `weather_condition` Parameter, aber `brain.py` Zeile 5726-5728 übergibt nur 3 Argumente — Weather wird nie geliefert (verifiziert)
- `get_calendar_weather_crossrefs()` existiert (Zeile 725), wird aber nirgends aufgerufen — Dead Code (verifiziert: einziger Treffer ist die Definition selbst)
- Causal Chains fehlen in `get_suggestions()` (kein `elif pattern["type"] == "causal_chain"` Branch), werden aber in `auto_execute_ready_patterns()` korrekt verarbeitet (verifiziert)

**SOLL:** Wetter + Kalender + Kontext fließen tatsächlich in Mustervorhersagen ein.

### Änderungen

**Datei: `assistant/assistant/brain.py`**
- Bei `anticipation.log_action()` Aufruf (Zeile ~5726): Wetter-Condition aus Context/Redis-Cache mitgeben
  ```python
  weather = (context or {}).get("weather", {}).get("condition", "")
  self.anticipation.log_action(action["function"], action.get("args", {}), person or "", weather_condition=weather)
  ```
- ~5 Zeilen

**Datei: `assistant/assistant/anticipation.py`**
- `get_suggestions()`: `elif pattern["type"] == "causal_chain"` Branch ergänzen mit passender Suggestion-Formatierung (analog zu den bestehenden time/sequence/context Branches)
- ~15 Zeilen

**Datei: `assistant/assistant/brain.py` oder `proactive.py`**
- `get_calendar_weather_crossrefs()` in den Morgen-Briefing-Flow integrieren (z.B. in `routine_engine.py` beim Morgen-Briefing aufrufen)
- ~10 Zeilen

**Tests:**
- `test_anticipation.py`: Test dass weather_condition in gespeicherten Entries erscheint und Context-Patterns beeinflusst
- `test_anticipation.py`: Test dass causal_chain-Typ Suggestions generiert werden

---

## Bereich 4: Latenz-Optimierung — Redundante Klassifikation eliminieren

**IST:** 3 unabhängige Klassifikations-Systeme:
1. `pre_classifier.classify_async()` → `RequestProfile` mit category + Subsystem-Flags
2. `model_router.select_model_and_tier(text)` (Zeile 254) → eigene Keyword-Listen, ignoriert Pre-Classifier-Ergebnis (verifiziert: kein Zugriff auf `profile`)
3. `brain._classify_intent()` (Zeile 10036) → dritte unabhängige Keyword-Liste

Plus: Duplicate `get_tier()` Bug — Zeile 242 (nimmt Model-Name) wird von Zeile 370 (nimmt Text) überschrieben. Die erste Definition mit Edge-Case-Handling für gleiche Modelle auf allen Tiers ist Dead Code (verifiziert).

**SOLL:** Pre-Classifier als primäre Quelle, Model Router konsumiert dessen Ergebnis.

### Änderungen

**Datei: `assistant/assistant/model_router.py`**
- Erste `get_tier()` (Zeile 242) umbenennen zu `get_tier_for_model(model: str) -> str`
- Zweite `get_tier()` (Zeile 370) bleibt als Fallback
- Neue Methode `select_model_from_profile(profile) -> tuple[str, str]`:
  - `profile.category == "device_command"` oder `profile.prefer_fast` → Fast-Tier
  - `profile.category == "knowledge"` mit langer Query → Deep-Tier
  - Default → Smart-Tier
- ~30 Zeilen

**Datei: `assistant/assistant/brain.py`**
- Nach `pre_classifier.classify_async()` (Zeile ~2805): `model_router.select_model_from_profile(profile)` aufrufen statt `select_model_and_tier(text)` (Zeile ~3091)
- Fallback bei Fehler: weiterhin `select_model_and_tier(text)` nutzen
- ~10 Zeilen

**Tests:**
- `test_model_router.py`: Test `get_tier_for_model()` separat von `get_tier()`
- `test_model_router.py`: Test Profile-basierte Model-Selection

---

## Bereich 5: Langzeit-Beziehung — Formality + Sarcasm Synchronisation

**IST:** Formality decayed zeitbasiert (personality.py Zeile 2077-2094), Sarcasm lernt über Feedback nach 20+ Samples (Zeile 2596-2653). Aber kein Cross-Signal: Sarcasm 5 + Formality 80 ist widersprüchlich (hoher Sarkasmus bei gleichzeitig sehr förmlichem Ton).

**SOLL:** Konsistente Persönlichkeitsentwicklung — hoher Sarkasmus impliziert niedrigere Formalität.

### Änderungen

**Datei: `assistant/assistant/personality.py`**
- In `track_sarcasm_feedback()` (Zeile ~2632/2638): Nach Sarcasm-Level-Änderung auch Formality-Bounds anpassen
  - Sarcasm 4-5 → `formality_min` auf max 30 (informell)
  - Sarcasm 1-2 → `formality_min` auf min 50 (förmlich)
- In `_update_formality()`: Interaktions-basierter Decay-Boost
  - Tage mit >5 Interaktionen → Formality decayed 50% schneller (häufige Interaktion = mehr Vertrautheit)
- ~25 Zeilen

**Tests:**
- `test_personality.py`: Test dass Sarcasm-Level-Änderung Formality-Floor beeinflusst
- `test_personality.py`: Test Interaction-basierter Decay-Boost

---

## Bereich 6: Erklärbarkeit — Proaktive Transparenz

**IST:** `explainability.py` hat `auto_explain` Config-Flag (Zeile 37, default False), macht aber nur System-Prompt-Hint via `get_explanation_prompt_hint()` (Zeile 261). Kein proaktiver Push — verifiziert: keine `notify_callback` oder Push-Logik vorhanden. Erklärungen sind rein reaktiv (User muss fragen).

**SOLL:** Bei Autonomie-Level ≥3 und impactful Actions (Heizung, Schloss, Alarm): Kurze Begründung automatisch in die Antwort einfügen.

### Änderungen

**Datei: `assistant/assistant/explainability.py`**
- Neue Methode `get_auto_explanation(action_type: str, domain: str) -> Optional[str]`:
  - Nur für high-impact Domains: `security`, `climate`, `lock`, `alarm`
  - Nur bei `auto_explain=True`
  - Formatiert 1-Satz-Erklärung aus dem letzten `log_decision()` Eintrag für diese Domain
  - Return: z.B. `"(Heizung reduziert: Fenster im Wohnzimmer ist offen bei 2°C Außentemperatur)"`
- ~30 Zeilen

**Datei: `assistant/assistant/brain.py`**
- Nach erfolgreicher Aktionsausführung (wo `on_action_success` aufgerufen wird):
  - `explanation = self.explainability.get_auto_explanation(action_type, domain)`
  - Wenn vorhanden: An Response-Text anhängen
- ~10 Zeilen

**Tests:**
- `test_explainability.py`: Test auto_explanation für high-impact Domain (security/climate)
- `test_explainability.py`: Test dass low-impact Domains (light) keine Erklärung generieren
- `test_explainability.py`: Test dass auto_explain=False keine Erklärungen liefert

---

## Bereich 7: Sicherheit — Verbal-Feedback Cross-User-Leakage

**IST:** `_last_executed_action` in `brain.py` ist ein einzelner Instance-String (Zeile ~399, mit TODO-Kommentar: "Per Person scopen um Cross-User-Leakage im Pronomen-Shortcut zu verhindern"). Positive Feedback-Erkennung (Zeile 5780: "danke", "super" etc.) und negative Feedback (Zeile 11210-11213: Korrekturen) nutzen beide diesen globalen String. In einem Multi-User-Haushalt kann ein "Danke" von Person A die letzte Aktion von Person B positiv bewerten.

**SOLL:** Per-Person Tracking der letzten Aktion.

### Änderungen

**Datei: `assistant/assistant/brain.py`**
- `_last_executed_action: str` ersetzen durch `_last_executed_action: dict[str, tuple[str, float]]`
  - Key: Person-Name, Value: (Action-Type, Timestamp)
- Bei Aktion-Ausführung (Zeile ~2315-2316, 2371-2372): `self._last_executed_action[person] = (action_type, time.time())`
- Bei Feedback-Detection (Zeile ~5832, 11210): `action, ts = self._last_executed_action.get(person, ("", 0))`
  - Nur akzeptieren wenn `time.time() - ts < 300` (5 Minuten TTL)
- Aufräumen: Einträge älter als 5 Minuten bei jedem Zugriff entfernen
- ~20 Zeilen

**Tests:**
- `test_brain.py`: Test dass Feedback korrekt per Person zugeordnet wird
- `test_brain.py`: Test dass TTL abgelaufene Aktionen nicht mehr zugeordnet werden

---

## Bereich 8: Wellness — Inner-State-Integration

**IST:** Wellness Advisor nutzt `mood_detector` (User-Mood) intensiv — verifiziert: `__init__` Zeile 38 nimmt `mood_detector`, genutzt in `_check_stress_intervention()` (Zeile 330), `_check_meal_time()` (Zeile 438), `_check_mood_ambient_actions()` (Zeile 697). Aber null Referenzen zu `inner_state` — verifiziert per Grep.

**SOLL:** Wenn Jarvis "besorgt" ist (z.B. wegen Security-Event), nicht-kritische Wellness-Checks pausieren. Wenn Jarvis "zufrieden", freundlichere Wellness-Nachrichten.

### Änderungen

**Datei: `assistant/assistant/wellness_advisor.py`**
- Neuen optionalen Parameter `inner_state=None` im Constructor akzeptieren (backward-compatible)
- In `_wellness_loop()`: Wenn `self._inner_state` vorhanden und `self._inner_state.mood == "concerned"`:
  - Nur kritische Checks durchführen (Stress-Intervention, Hydration)
  - Non-critical überspringen (PC-Pausen, Mahlzeiten-Erinnerungen)
- In Message-Generierung: Jarvis-Mood als Kontext nutzen (zufrieden → wärmerer Ton)
- ~20 Zeilen

**Datei: `assistant/assistant/brain.py`**
- Bei Wellness-Advisor-Init: `inner_state` Referenz übergeben
- ~3 Zeilen

**Tests:**
- `test_wellness_advisor.py`: Test dass concerned-Mood non-critical Checks überspringt
- `test_wellness_advisor.py`: Test dass critical Checks weiterhin laufen

---

## Umsetzungsreihenfolge

| Phase | Bereich | Aufwand | Impact | Risiko |
|-------|---------|---------|--------|--------|
| 1 | **7: Security Fix** (Cross-User-Leakage) | Klein (~20 LOC) | Kritisch | Niedrig |
| 2 | **4: Latenz** (Duplicate get_tier Bug + Klassifikation) | Mittel (~40 LOC) | Hoch | Niedrig |
| 3 | **3: Multi-Signal** (Dead Code aktivieren) | Mittel (~30 LOC) | Hoch | Niedrig |
| 4 | **1: Personality Integration** | Mittel (~55 LOC) | Hoch | Mittel |
| 5 | **2: Kausales Gedächtnis** (Outcome-Loop) | Mittel (~75 LOC) | Hoch | Mittel |
| 6 | **6: Erklärbarkeit** | Klein (~40 LOC) | Mittel | Niedrig |
| 7 | **5: Langzeit-Beziehung** | Klein (~25 LOC) | Mittel | Niedrig |
| 8 | **8: Wellness Integration** | Klein (~23 LOC) | Niedrig | Niedrig |

## Geschätzte Änderungen gesamt

- **~8 Dateien** modifiziert (keine neuen Module)
- **~310 Zeilen** Produktivcode
- **~18 neue Tests**
- Alle Änderungen backward-compatible (optionale Parameter, Fallbacks)
- Jede Phase einzeln deploybar und testbar
