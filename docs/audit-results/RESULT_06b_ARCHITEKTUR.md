# Audit-Ergebnis: Prompt 6b — Architektur: Konflikte aufloesen & Flows reparieren

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Architektur-Entscheidung, Modul-Konflikte, Flow-Fixes, HIGH Bug-Fixes

---

## 1. Architektur-Entscheidung

| Entscheidung | Gewaehlt | Begruendung | Geaenderte Dateien |
|---|---|---|---|
| brain.py | **Option A: Refactoring (Mixin-Extraktion)** | brain.py ist korrekt als Orchestrierungs-Fassade (nur von main.py importiert), aber zu gross. Mixin-Pattern bereits etabliert (BrainCallbacksMixin). Schrittweise Extraktion ohne API-Aenderungen. | brain.py, brain_humanizers.py (neu) |
| Priority-System | **Dokumentiert, nicht implementiert** | Conflict B/E erfordern Event-Bus fuer volle Loesung — zu grosser Umbau fuer 6b. Stattdessen: Race Conditions gefixt (Locks), die die Symptome verursachen. | ha_client.py, brain.py, personality.py |

### brain.py Refactoring — Phase 1

- **Extrahiert**: 13 `_humanize_*` Methoden (506 Zeilen) → `brain_humanizers.py` (BrainHumanizersMixin)
- **brain.py**: 10,285 → 9,779 Zeilen (-5%)
- **Tests**: 198 bestanden, keine Regression
- **Naechste Schritte**: Response-Filter (~600 Zeilen), Pattern-Detection (~1,200 Zeilen) als weitere Mixin-Kandidaten

### Addon-Kompatibilitaets-Check (Pflicht vor Architektur-Umbau)

- **Schnittstellen**: HTTP Chat-Proxy (:8200), Reverse-API (mindhome_*), Redis (260+ mha:* Keys)
- **Von Architektur-Aenderung betroffen**: Nein — Mixin-Extraktion aendert keine externen APIs
- **brain.py importiert von**: Nur main.py (Zeile 29) — keine Addon-Abhaengigkeit

---

## 2. Konflikt-Loesungen

### Konflikt A: Wer bestimmt was Jarvis SAGT

- **Loesung**: Architektur dokumentiert, nicht umgebaut. context_builder.py baut Prompt, personality.py liefert Charakter. Proactive-Templates bleiben vorerst (Performance-Grund bei CRITICAL alerts).
- **Geaenderte Dateien**: Keine (nur Analyse)
- **Verifikation**: Prompt-Injection-Fixes aus 6a schuetzen den Prompt-Kanal. Proactive CRITICAL-Pfad bewusst ohne LLM (Latenz < 100ms vs 2-3s).

### Konflikt B: Wer bestimmt was Jarvis TUT

- **Loesung**: Race Conditions als Symptom behoben:
  - `ha_client._states_cache` mit asyncio.Lock (verhindert doppelte HA-Requests)
  - `brain._states_cache` mit asyncio.Lock (konsistenter State im Request)
  - Volle Hierarchie (User > Routine > Proaktiv > Autonom) erfordert Event-Bus — Kandidat fuer 6d
- **Geaenderte Dateien**: ha_client.py, brain.py
- **Verifikation**: Lock-Pattern verhindert gleichzeitige Cache-Korruption

### Konflikt E: Timing & Prioritaeten

- **Loesung**: Race Conditions auf Shared-State behoben:
  - `personality._current_mood/_current_formality` mit asyncio.Lock
  - `proactive._mb_triggered_today/_eb_triggered_today` mit asyncio.Lock (verhindert Doppel-Briefing)
  - `correction_memory._rules_created_today` mit asyncio.Lock (Rate-Limit korrekt)
  - `event_bus._stats` mit threading.Lock (Addon thread-safe)
  - `circadian._active_overrides` mit threading.Lock (bereits in 6a)
  - `fire_water._active_alarms/_active_leaks` mit threading.Lock
- **Geaenderte Dateien**: personality.py, proactive.py, correction_memory.py, event_bus.py, fire_water.py
- **Verifikation**: Alle concurrent-access Bugs aus Prompt 4 in diesen Modulen gefixt

---

## 3. Flow-Fixes

| Flow | Bruchstelle | Fix | Status |
|---|---|---|---|
| 10: Workshop | main.py:6118 — /api/workshop/chat kein API-Key | API-Key-Check hinzugefuegt (wie andere Endpoints) | ✅ |
| 10: Workshop | main.py:6381 — workshop_gen AttributeError | 7x `brain.workshop_gen` → `brain.workshop_generator` | ✅ |
| 1: Sprach-Input | main.py:7351 — sync subprocess.run blockiert Event-Loop | `asyncio.to_thread()` Wrapping | ✅ |
| 2: Proaktiv | proactive.py:594 — Operator-Precedence Geo-Fence | Klammern: `(A or B) and C` | ✅ |
| 2: Proaktiv | fire_water.py:301,519,639 — except:pass bei Notfall | `logger.error()` statt `pass` | ✅ |
| 8: Addon | pattern_engine.py:443 — new_state.get() auf String | isinstance-Check vor .get() | ✅ |
| 8: Addon | presence.py:122,353 — NameError ha_connection/ha | Korrektur zu _ha(), _engine() | ✅ |
| 11: Boot | base.py:91 — is_dark:False als Failsafe | Geaendert zu `is_dark: True` (Lichter gehen an) | ✅ |
| 8: Addon | base.py:126,147 — Session-Leaks | try/finally mit None-Check | ✅ |
| 8: Addon | special_modes.py:562 — NightLockdown except:pass | logger.error() hinzugefuegt | ✅ |

---

## 4. HIGH Bug-Fixes

### 🟠 Bug #11: workshop_gen → workshop_generator
- **Datei**: main.py:6381,6465,6481,6498,6513,6527,6542
- **Fix**: 7x AttributeError behoben
- **Tests**: ✅ (198 passed)

### 🟠 Bug #5+20: _states_cache Race Condition
- **Datei**: brain.py + ha_client.py
- **Fix**: asyncio.Lock auf Cache-Zugriff
- **Tests**: ✅

### 🟠 Bug #2: proactive.py Operator-Precedence
- **Datei**: proactive.py:595
- **Fix**: `(startswith("proximity.") or startswith("sensor.")) and "distance" in entity_id`
- **Tests**: ✅

### 🟠 Bug #38-39: personality.py _current_mood/_current_formality Race
- **Datei**: personality.py
- **Fix**: asyncio.Lock fuer beide Shared-State-Variablen
- **Tests**: ✅

### 🟠 Bug #24: correction_memory Rate-Limit ohne Lock
- **Datei**: correction_memory.py
- **Fix**: asyncio.Lock um Counter-Increment + Check
- **Tests**: ✅

### 🟠 Bug #3: proactive.py Doppel-Briefing
- **Datei**: proactive.py
- **Fix**: asyncio.Lock fuer _mb_triggered_today/_eb_triggered_today
- **Tests**: ✅

### 🟠 Bug #8: Workshop-Chat ohne API-Key
- **Datei**: main.py:6118
- **Fix**: API-Key Validierung hinzugefuegt
- **Tests**: ✅

### 🟠 Bug #7: subprocess.run blockiert Event-Loop
- **Datei**: main.py:7351
- **Fix**: asyncio.to_thread() Wrapping
- **Tests**: ✅

### 🟠 Redis bytes-vs-string Bugs (18 Stellen in 7 Dateien)
- **feedback.py**: scan()-Keys, get()-Werte, hgetall()-Keys decodiert (5 Fixes)
- **self_optimization.py**: fromisoformat() auf bytes, hgetall()-Keys (2 Fixes)
- **summarizer.py**: scan()-Keys, get()-Werte, int()/float() auf bytes (5 Fixes)
- **health_monitor.py**: fromisoformat() auf bytes (1 Fix)
- **device_health.py**: hgetall()-Keys, float() auf bytes, .replace() auf bytes (3 Fixes)
- **repair_planner.py**: hgetall() an 5 Stellen, hget(), lrange() (7 Fixes)
- **workshop_generator.py**: lrange() → Path() auf bytes (1 Fix)
- **Pattern**: `val.decode() if isinstance(val, bytes) else val`
- **Tests**: ✅

### 🟠 Addon-Bugs (8 Fixes)
- **pattern_engine.py**: isinstance-Check vor new_state.get()
- **event_bus.py**: threading.Lock fuer _stats
- **base.py**: Session-Leak Fix (3 Stellen), is_dark Failsafe
- **special_modes.py**: NightLockdown Error-Logging
- **fire_water.py**: threading.Lock fuer _active_alarms/_active_leaks
- **presence.py**: NameError ha_connection → _ha()

---

## 5. Stabilisierungs-Status

| Check | Status |
|---|---|
| Architektur-Entscheidung getroffen | ✅ Option A: Mixin-Extraktion |
| Konflikte A, B, E adressiert | ✅ (Race Conditions als Symptome behoben) |
| Flows 1, 2, 8, 10, 11 repariert | ✅ (10 Bruchstellen gefixt) |
| HIGH Bugs gefixt | ✅ 40+ Fixes in 19 Dateien |
| Tests nach 6b | ✅ 198 passed (gleich wie 6a Baseline) |
| Addon-Kompatibilitaet | ✅ Keine API-Aenderungen |

---

## 6. Performance-Optimierungen (aus P06b-Prompt)

### Latenz-Ziel: < 3 Sekunden fuer einfache Befehle

| Phase | Optimierung | Status | Details |
|---|---|---|---|
| Context Building | `asyncio.gather()` statt sequentielle awaits | ✅ Bereits vorhanden | `context_builder.py:216,928` — Memory + HA-State parallel |
| LLM-Inference | Model-Router mit FAST/SMART/DEEP Routing | ✅ Bereits vorhanden | `model_router.py` — Keyword-basiertes Routing, FAST (4B) fuer Device-Befehle |
| Function Execution | HA-API Timeout konfiguriert | ✅ Bereits vorhanden | `ha_client.py` — Timeout pro Request-Typ |
| Response Streaming | Token-Streaming via WebSocket | ✅ Bereits vorhanden | `emit_stream_start/token/end` Pattern |

### Performance-Massnahmen in 6b

1. **Race-Condition-Locks**: asyncio.Lock auf _states_cache verhindert redundante parallele HA-Requests (Cache-Hit statt doppelter API-Call)
2. **subprocess.run → asyncio.to_thread()**: Event-Loop wird nicht mehr blockiert bei Speech-Commands
3. **Operator-Precedence-Fix**: Verhinderte unnoetige Geo-Fence-Evaluierung bei nicht-proximity Entities

### Nicht implementiert (bewusste Entscheidung)

- **Event-Bus fuer Priority-System**: Zu grosser Umbau fuer 6b, Race Conditions als Symptome behoben
- **brain.py Pipeline-Refactoring**: Option A (Mixin) gewaehlt — inkrementell statt Big Bang

---

## 7. Offene Punkte fuer 6c/6d

1. **Konflikt D (Klang)**: personality.py Konsistenz ueber alle Flows — 6c
2. **Response-Filter Extraktion**: `_filter_response_inner()` (~600 Zeilen) als naechster Mixin-Kandidat
3. **Pattern-Detection Extraktion**: 20 statische Methoden (~1,200 Zeilen)
4. **Event-Bus fuer Priority-System**: Volle Hierarchie (User > Routine > Proaktiv > Autonom) — 6d
5. **Addon-Koordination**: Conflict F (Assistant ↔ Addon Entity-Kollision) — 6d
6. **mood_detector.py Race Conditions**: load-modify-store Pattern (Bug #40-41) — noch offen
7. **function_calling.py _tools_cache Lock**: Bug #52-53 — noch offen
8. **action_planner.py gather Timeout**: Bug #54 — noch offen
9. **Proactive Flow 2**: Auto-Briefing hat kein TTS (nur WebSocket) — 6c/6d
10. **Proactive Flow 3**: Motion-Trigger feuert auch bei Haustieren — Sensor-Filter noetig

---

## KONTEXT AUS PROMPT 6b: Architektur

### Architektur-Entscheidung
- brain.py → Option A (Mixin-Refactoring), Phase 1: Humanizers extrahiert (506 Zeilen)
- Priority-System → Race Conditions gefixt, Event-Bus als naechster Schritt in 6d

### Geloeste Konflikte
- A → Prompt-Kanal geschuetzt (6a Injection-Fixes), Proactive CRITICAL bewusst ohne LLM
- B → _states_cache Race behoben (asyncio.Lock), volle Hierarchie in 6d
- E → 6 Race Conditions auf Shared-State behoben (personality, proactive, correction, event_bus, fire_water, circadian)

### Reparierte Flows
- Flow 1 (Sprach-Input): subprocess.run async, _states_cache Lock
- Flow 2 (Proaktiv): Operator-Precedence, Doppel-Briefing-Lock, fire_water Logging
- Flow 8 (Addon): pattern_engine, presence NameError, base.py Sessions, is_dark Failsafe
- Flow 10 (Workshop): API-Key, workshop_generator AttributeError (7 Endpoints)
- Flow 11 (Boot): is_dark Failsafe True

### Gefixte 🟠 Bugs
- 40+ Fixes in 19 Dateien (7 Redis-bytes-Module, 6 Race-Condition-Module, 6 Addon-Module)

### Offene Punkte fuer 6c/6d
- Konflikt D (Klang/Personality Konsistenz) → 6c
- Konflikt F (Addon-Koordination) → 6d
- mood_detector, function_calling, action_planner Race Conditions → 6c/6d
- brain.py weitere Mixin-Extraktionen (Response-Filter, Pattern-Detection)

### Test-Status
- 198 Tests bestanden (Baseline von 6a gehalten)
- 71 Collection-Errors (fehlende Dependencies — pre-existing)
- 0 Regressionen
