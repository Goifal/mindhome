# Audit-Ergebnis: Prompt 6a — Stabilisierung: Kritische Bugs & Memory reparieren

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle 🔴 KRITISCHEN Bugs aus Prompt 4 (4a + 4b + 4c) + Memory-Reparatur aus Prompt 2

---

## 1. Bug-Fix-Log

### 🔴 Bug #1: Modules 1-30 nicht in _safe_init() — Crash bei fehlenden Dependencies
- **Datei**: `assistant/assistant/brain.py` (Init-Bereich)
- **Problem**: ~25 Module-Initialisierungen (FeedbackTracker, Summarizer, TimeAwareness, LightEngine, RoutineEngine, etc.) konnten bei ImportError/RuntimeError den gesamten Start crashen
- **Fix**: Alle Initialisierungen in `_safe_init()` gewrappt, `_degraded_modules` Liste + `_start_fact_decay_task()` / `_start_autonomy_evolution_task()` Helper
- **Aufrufer geprüft**: Ja — brain.py ist einziger Konsument
- **Tests**: ⏭️ Kein spezifischer Test vorhanden (Integration)

### 🔴 Bug #2: event_handlers gelesen vor Definition
- **Datei**: `assistant/assistant/proactive.py:97`
- **Problem**: `self.event_handlers` wurde in der devices-Loop (Zeile ~108) referenziert, aber erst bei Zeile ~145 definiert → `AttributeError`
- **Fix**: `self.event_handlers = {}` vor der devices-Loop initialisiert
- **Aufrufer geprüft**: Ja — nur proactive.py intern
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #3: process() Race Condition — parallele Requests korrumpieren State
- **Datei**: `assistant/assistant/brain.py:1076`
- **Problem**: Kein Lock auf `process()` — parallele Requests konnten `_current_person`, `_last_intent` etc. überschreiben
- **Fix**: `self._process_lock = asyncio.Lock()` in `__init__`, `process()` delegiert an `_process_inner()` unter Lock
- **Aufrufer geprüft**: Ja — main.py ruft process() über API auf
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #4: Duplicate Key "conv_memory" — Semantische Suche überschrieben
- **Datei**: `assistant/assistant/brain.py:2394`
- **Problem**: Doppelter Key `"conv_memory"` in `_mega_tasks` — zweiter (Projekte/Fragen) überschreibt ersten (semantische Konversationssuche) bei Dict-Konvertierung
- **Fix**: Key zu `"conv_memory_extended"` umbenannt, Consumer bei Zeile ~2937 angepasst zu `_safe_get("conv_memory_extended")` mit Section-Name `"conv_memory_ext"`
- **Aufrufer geprüft**: Ja — alle _safe_get-Aufrufe verifiziert
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #5: TOCTOU Race in embedding_extractor._load_model()
- **Datei**: `assistant/assistant/embedding_extractor.py`
- **Problem**: `_classifier` wurde ohne Synchronisierung geladen — parallele Aufrufe konnten doppelt laden oder None-Referenz sehen
- **Fix**: `threading.Lock()` mit Double-Check-Locking Pattern
- **Aufrufer geprüft**: Ja — speaker_recognition.py ist einziger Aufrufer
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #6: semantic_memory.store_fact() — Kein Rollback bei partiellem Fehler
- **Datei**: `assistant/assistant/semantic_memory.py`
- **Problem**: ChromaDB-Fehler führte zu sofortigem Return ohne Redis-Speicherung → Fakt komplett verloren
- **Fix**: `chroma_ok` Flag, bei Fehler Warnung aber Redis-Store wird trotzdem versucht
- **Aufrufer geprüft**: Ja — memory_extractor.py ruft store_fact() auf
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #7: Redis bytes bei fromisoformat() in wellness_advisor.py (3 Stellen)
- **Datei**: `assistant/assistant/wellness_advisor.py:237, 335, 634`
- **Problem**: Redis gibt `bytes` zurück, `fromisoformat()` erwartet `str` → `TypeError`
- **Fix**: `.decode()` Pattern an allen 3 Cooldown-Stellen (pc_start, stress_nudge, hydration)
- **Aufrufer geprüft**: Ja — brain.py Wellness-Callbacks
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #8: function_calling gather ohne Exception-Check
- **Datei**: `assistant/assistant/function_calling.py`
- **Problem**: `asyncio.gather(return_exceptions=True)` aber Exceptions nie geprüft → AttributeError wenn domains_data eine Exception ist
- **Fix**: Post-gather Loop prüft `isinstance(result, BaseException)` mit Logging
- **Aufrufer geprüft**: Ja — brain.py ruft function_calling auf
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #9: lock/alarm_control_panel in generic gateway
- **Datei**: `assistant/assistant/function_calling.py`
- **Problem**: Sicherheitskritische Domains (lock, alarm_control_panel) in `_CALL_SERVICE_ALLOWED_DOMAINS` → ungeschützter Zugriff
- **Fix**: Entfernt aus allowed list
- **Aufrufer geprüft**: Ja — call_service() prüft die Liste
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #10: lock_door unlock ohne Bestätigung
- **Datei**: `assistant/assistant/function_calling.py`
- **Problem**: Tür-Entriegelung ohne Sicherheitsabfrage → potentiell gefährlich
- **Fix**: `requires_confirmation: True` Response bei unlock-Action
- **Aufrufer geprüft**: Ja — brain.py Function-Calling Pipeline
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #11: Prompt Injection via conversation_topic
- **Datei**: `assistant/assistant/personality.py`
- **Problem**: User-Text wird ungefiltert in System-Prompt eingefügt → Prompt Injection möglich
- **Fix**: Länge auf 200 Zeichen, Newlines entfernt, Role-Marker (SYSTEM:/ASSISTANT:/USER:) entfernt
- **Aufrufer geprüft**: Ja — brain.py ruft personality.get_system_prompt() auf
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #12: Prompt Injection via weather data
- **Datei**: `assistant/assistant/personality.py`
- **Problem**: Wetterdaten (temp, condition, wind) ungefiltert im Prompt → Injection-Vektor
- **Fix**: Typ-Validierung (`isinstance(x, (int, float, str))`), Länge begrenzt, Newlines entfernt
- **Aufrufer geprüft**: Ja — personality.py intern
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #13: fire_water Failsafe return False statt True
- **Datei**: `addon/rootfs/opt/mindhome/engines/fire_water.py:164, 470`
- **Problem**: Bei DB-Fehler in `_is_assigned_entity()` → `return False` → Feuer/Wasser-Alarm wird ignoriert
- **Fix**: `return True` (Failsafe: im Zweifel alarmieren) + Error-Logging
- **Aufrufer geprüft**: Ja — fire_water.py interne Aufrufe in handle_event()
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #14: Markise öffnet bei Sturm
- **Datei**: `addon/rootfs/opt/mindhome/engines/cover_control.py`
- **Problem**: Wind-Forecast gab `position: 100` (OFFEN) statt 0 (GESCHLOSSEN)
- **Fix**: `position: 0` bei weather_forecast_wind
- **Aufrufer geprüft**: Ja — cover_control.py _calculate_target_position()
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #15: UTC statt local in _check_time_trigger
- **Datei**: `addon/rootfs/opt/mindhome/automation_engine.py:633`
- **Problem**: `datetime.now(timezone.utc)` statt lokaler Zeit → Automationen mit 1-2h Versatz
- **Fix**: `from helpers import local_now as _local_now; now = _local_now()`
- **Aufrufer geprüft**: Ja — automation_engine.py intern
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #16: UTC statt local in is_quiet_time
- **Datei**: `addon/rootfs/opt/mindhome/automation_engine.py:2283`
- **Problem**: Ruhezeit-Check mit UTC → nachts Licht/Aktionen trotz Ruhezeit
- **Fix**: `local_now()` statt `datetime.now(timezone.utc)`
- **Aufrufer geprüft**: Ja — automation_engine.py + Engines
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #17: UTC in WakeUp-Ramp
- **Datei**: `addon/rootfs/opt/mindhome/engines/sleep.py:298`
- **Problem**: WakeUp-Lichtrampe mit UTC → startet zu falscher Zeit
- **Fix**: `local_now()` statt `datetime.now(timezone.utc)`
- **Aufrufer geprüft**: Ja — sleep.py _run_wakeup_ramp()
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #18: Race Condition auf circadian._active_overrides
- **Datei**: `addon/rootfs/opt/mindhome/engines/circadian.py`
- **Problem**: `_active_overrides` dict ohne Lock → Race bei gleichzeitigem Sleep/Wake/Guest Event
- **Fix**: `self._overrides_lock = threading.Lock()` in allen Methoden die `_active_overrides` lesen/schreiben
- **Aufrufer geprüft**: Ja — stop(), _on_sleep(), _on_wake(), _on_guests(), check()
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #19: access_control ohne Entity-Whitelist
- **Datei**: `addon/rootfs/opt/mindhome/engines/access_control.py`
- **Problem**: Lock/Unlock ohne Prüfung ob Entity ein zugewiesenes Lock ist → beliebige Entities steuerbar
- **Fix**: `_is_assigned_lock()` Methode + Whitelist-Check in lock/unlock
- **Aufrufer geprüft**: Ja — access_control.py handle_command()
- **Tests**: ⏭️ Kein spezifischer Test

### 🔴 Bug #20-24: ChromaDB synchrone Aufrufe blockieren Event Loop (5 Module)
- **Dateien**: `recipe_store.py` (10 Stellen), `knowledge_base.py` (11 Stellen), `summarizer.py` (2 Stellen), `workshop_library.py` (10 Stellen), `memory.py` (5 Stellen), `semantic_memory.py` (7 Stellen)
- **Problem**: Synchrone ChromaDB-Aufrufe (.query(), .add(), .get(), .upsert(), .delete(), .count()) blockieren den asyncio Event Loop → alle parallelen Requests warten
- **Fix**: Alle 45 Stellen mit `await asyncio.to_thread()` gewrappt. `import asyncio` wo fehlend ergänzt (recipe_store.py, workshop_library.py, memory.py)
- **Aufrufer geprüft**: Ja — brain.py mega-gather, main.py API endpoints
- **Tests**: 198 syntaxfreie Tests bestanden ✅

---

## 2. Memory-Fix

### Memory-Architektur-Entscheidung
- **Gewählt**: Aktuelles System fixen (3 gezielte Änderungen, kein Umbau)
- **Begründung**: Das Design ist grundsätzlich korrekt — die Bugs sind der Grund für das Fehlverhalten, nicht die Architektur. Redis+ChromaDB Dual-Storage ist performant und skalierbar.

### Geänderte Dateien
1. `brain.py:2394` — Duplicate Key "conv_memory" → "conv_memory_extended" (Fix 1)
2. `brain.py:2937` — Consumer nutzt neuen Key mit eigenem Section-Name (Fix 2, automatisch durch Fix 1)
3. `brain.py:_get_conversation_memory()` — Episodisches ChromaDB-Gedächtnis (mha_conversations) in Read-Path eingebunden (Fix 3)
4. `brain.py:_format_days_ago()` — Neue Helper-Methode für relative Zeitangaben

### Verifikation der 4 Memory-Checks

| Check | Status | Beweis |
|---|---|---|
| **1. Conversation History** im LLM-Prompt | ✅ | `brain.py:3031` → `get_recent_conversations()` → Messages-Array. Funktionierte bereits. |
| **2. Fakten-Speicherung** | ✅ | `brain.py:6179` → `memory_extractor.extract_and_store()` → `semantic_memory.store_fact()` → ChromaDB + Redis. `store_fact()` jetzt mit Partial-Failure-Recovery (Bug #6). |
| **3. Korrektur-Lernen** | ✅ | `brain.py:9273` → `correction_memory` Read in mega-gather (Zeile 2389), Write bei Korrekturen. Funktionierte bereits. |
| **4. Kontext im LLM-Prompt** | ✅ | Fix: Semantische Konversationssuche (`conv_memory`, P2) jetzt getrennt von Projekten (`conv_memory_extended`, P3). Episodisches Gedächtnis neu im Read-Path. `context_builder.py:308` → `search_facts()` → P1 (immer). |

### Memory-Flow nach Fix

```
READ PATH (nach Fix):
User Input
  ├─► context_builder._get_relevant_memories() → P1 SECTION (IMMER) ✅
  │       ├─► semantic.search_facts(text) → max 3 facts
  │       └─► semantic.get_facts_by_person(person) → max 5 facts
  │
  ├─► _get_conversation_memory(text) → P2 SECTION ✅ (NEU: mit Episodes)
  │       ├─► semantic.get_relevant_conversations(text, limit=3)
  │       └─► memory.search_memories(text, limit=3)  ← NEU
  │
  ├─► conversation_memory.get_memory_context() → P3 SECTION ✅ (eigener Key)
  │       └─► Key "conv_memory_extended" (nicht mehr duplicate!)
  │
  ├─► correction_memory.get_relevant_corrections() → P2 SECTION ✅
  │
  └─► memory.get_recent_conversations(limit) → Messages-Array ✅
```

---

## 3. Stabilisierungs-Status

| Check | Status |
|---|---|
| Alle 🔴 Bugs gefixt | ✅ 24 von 24 (19 individuelle + 5 ChromaDB-Module systemisch) |
| Memory: Conversation History funktioniert | ✅ Messages-Array via Redis (7d TTL) |
| Memory: Fakten werden gespeichert | ✅ ChromaDB + Redis Dual-Storage, jetzt mit Partial-Failure-Recovery |
| Memory: Korrekturen werden gemerkt | ✅ correction_memory Read + Write verifiziert |
| Memory: Kontext im LLM-Prompt | ✅ P1 (facts), P2 (conversations + episodes), P3 (projects) — alle getrennt |
| Tests bestehen nach Fixes | ✅ 198 bestanden, 71 Collection-Errors (fehlende Dependencies: redis, fastapi, etc. — pre-existing) |

---

## 4. Offene Punkte für 6b

### Architektur-relevante Erkenntnisse

1. **God Objects**: `brain.py` (10.231+ Zeilen) ist einziger Integrationspunkt für 12 Memory-Module, ~88 Module insgesamt. Refactoring in 6b dringend empfohlen.

2. **Memory-Konsolidierung**: 12 weitgehend isolierte Memory-Module funktionieren jetzt korrekt, aber Langfristig: 12 → 3-4 Module sinnvoll (MemoryManager, SemanticMemory, ConversationTracker).

3. **ChromaDB Event-Loop-Pattern**: Alle 45 sync-Stellen sind jetzt mit `asyncio.to_thread()` gewrappt. Bei einem zukünftigen ChromaDB-Update auf async-native Client kann `to_thread()` einfach entfernt werden.

4. **Addon-Memory isoliert**: Addon SQLite (LearnedPattern, StateHistory, Predictions) hat keinen API-Endpoint zum Assistant → zwei isolierte Wissensspeicher. REST-Endpoint in 6b/6c empfohlen.

5. **42 Redis bytes-vs-string Bugs**: Nur 3 CRITICAL in wellness_advisor.py gefixt. Die restlichen ~39 (HIGH/MEDIUM) sind Kandidaten für 6b.

6. **dialogue_state nicht persistiert**: In-memory only, 5-Min Timeout. Optional Redis-Backup in 6b.

7. **Test-Infrastruktur**: 71 von 269 Tests können nicht ausgeführt werden wegen fehlender Dependencies. Test-Environment Setup empfohlen.

---

## 5. Commit-Historie

| Commit | Beschreibung | Dateien |
|---|---|---|
| `ed18080` | Fix: Init crashes + process() race + conv_memory duplicate | brain.py, proactive.py |
| `737f709` | Fix: Data loss — embedding race, semantic_memory, wellness bytes, return_exceptions | embedding_extractor.py, semantic_memory.py, wellness_advisor.py, function_calling.py |
| `48a0da3` | Fix: Security — prompt injection, lock.unlock, fire_water, cover | personality.py, function_calling.py, fire_water.py, cover_control.py |
| `a2bbb2b` | Fix: Addon — UTC/local time, circadian race, sleep wakeup, access_control | automation_engine.py, sleep.py, circadian.py, access_control.py |
| *(pending)* | Fix: ChromaDB async + Memory episodic read path | recipe_store.py, knowledge_base.py, summarizer.py, workshop_library.py, memory.py, semantic_memory.py, brain.py |

---

## KONTEXT AUS PROMPT 6a: Stabilisierung

### Gefixte 🔴 Bugs
| # | Datei | Fix |
|---|---|---|
| 1 | brain.py (Init) | 25 Module in _safe_init() gewrappt |
| 2 | proactive.py:97 | event_handlers vor devices-Loop initialisiert |
| 3 | brain.py:1076 | asyncio.Lock auf process() |
| 4 | brain.py:2394 | Duplicate Key conv_memory → conv_memory_extended |
| 5 | embedding_extractor.py | threading.Lock Double-Check auf _load_model() |
| 6 | semantic_memory.py | Partial-Failure-Recovery bei store_fact() |
| 7 | wellness_advisor.py (3x) | Redis bytes .decode() bei fromisoformat() |
| 8 | function_calling.py | gather return_exceptions Check-Loop |
| 9 | function_calling.py | lock/alarm_control_panel aus generic gateway entfernt |
| 10 | function_calling.py | lock_door unlock erfordert Bestätigung |
| 11 | personality.py | Prompt Injection Sanitization (conversation_topic) |
| 12 | personality.py | Prompt Injection Sanitization (weather data) |
| 13 | fire_water.py (2x) | Failsafe return True bei DB-Fehler |
| 14 | cover_control.py | Markise position 100→0 bei Sturm |
| 15-17 | automation_engine.py, sleep.py | UTC → local_now() (3 Stellen) |
| 18 | circadian.py | threading.Lock auf _active_overrides |
| 19 | access_control.py | Entity-Whitelist für lock/unlock |
| 20-24 | 6 Dateien (45 Stellen) | ChromaDB sync → asyncio.to_thread() |

### Memory-Entscheidung
- **Ansatz**: Aktuelles System fixen (3 gezielte Änderungen)
- **Dateien**: brain.py (conv_memory Key + episodic read path), semantic_memory.py (partial failure)
- **4 Checks**: Alle ✅ (Conversation History, Fakten, Korrekturen, Kontext im Prompt)

### Neue Erkenntnisse
- brain.py God Object (~10.231 Zeilen) ist größtes Risiko — alle Fixes mussten dort rein
- 45 ChromaDB sync-Stellen in 6 Dateien gefunden (mehr als die 5 im Bug-Report)
- Addon hat keinen Memory-Export zum Assistant (isolierte Wissensspeicher)
- Test-Environment fehlt (71 Tests nicht ausführbar wegen Dependencies)
- ~39 weitere Redis bytes-vs-string Bugs (HIGH/MEDIUM) noch offen

### Test-Status
- 198 Tests bestanden ✅
- 71 Collection-Errors (fehlende Dependencies — pre-existing, nicht durch Fixes verursacht)
- 0 Test-Failures durch Fixes
