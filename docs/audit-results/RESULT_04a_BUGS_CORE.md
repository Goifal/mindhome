# Audit-Ergebnis: Prompt 4a — Systematische Bug-Jagd (Core-Module, Prioritaet 1-4)

**Durchlauf**: #2 (Verifikation nach Fixes aus P6a-P8)
**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: 26 Core-Module in 4 Batches, 13 Fehlerklassen, Cross-Modul-Pruefung
**Methode**: 3 parallele Audit-Agenten + manuelle Verifikation kritischer Findings
**Vergleichsbasis**: DL#1 (88 Bugs: 10 KRITISCH, 18 HOCH, 38 MITTEL, 22 NIEDRIG)

---

## DL#1 vs DL#2 Vergleich

### Gesamt-Statistik

```
DL#1: 88 Bugs (KRITISCH 10, HOCH 18, MITTEL 38, NIEDRIG 22)
DL#2: 88 Bugs → 26 FIXED, 15 PARTIALLY FIXED, 33 UNFIXED, 14 NEW

Veraenderung:
  Vollstaendig behoben:     26 (30%)
  Teilweise behoben:        15 (17%)
  Unveraendert:             33 (37%)
  Neue Bugs:                14 (davon 1 KRITISCH, 4 HOCH, 7 MITTEL, 2 NIEDRIG)

Aktuelle Bug-Bilanz (DL#2):
  Offene Bugs:              62 (33 alt-unfixed + 15 teilweise + 14 neu)
  Davon KRITISCH:            1 (NEW-1: Deadlock bei Retry)
  Davon HOCH:               12 (6 alt-unfixed + 2 teilweise + 4 neu)
  Davon MITTEL:             33 (17 alt-unfixed + 9 teilweise + 7 neu)
  Davon NIEDRIG:            16 (10 alt-unfixed + 4 teilweise + 2 neu)
```

---

## Bug-Report: Batch 1 — Core (brain.py, brain_callbacks.py, main.py, websocket.py)

### DL#1 → DL#2 Status

| # | Severity | Modul | DL#1-Zeile | DL#2-Zeile | Status | Beschreibung |
|---|----------|-------|-----------|-----------|--------|-------------|
| 1 | KRITISCH | brain.py | 2356+2394 | 2374+2412 | ✅ FIXED | Distinct keys: `conv_memory` + `conv_memory_extended` |
| 2 | KRITISCH | brain.py | 1076-1104 | 1089-1104 | ✅ FIXED | `_process_lock = asyncio.Lock()` (Zeile 215), acquired in `process()` (Zeile 1103) |
| 3 | KRITISCH | brain.py | 477-597, 760 | 524-760, 773 | ⚠️ TEILWEISE | Module 1-30 in `_safe_init()` gewrappt. **ABER**: `proactive.start()` (Zeile 773) weiterhin UNGESCHUETZT |
| 4 | HOCH | brain.py | 10131-10178 | 9773-9800 | ⚠️ TEILWEISE | `_task_registry.shutdown()` + 18 Komponenten explizit. **ABER**: 30+ Komponenten ohne Shutdown (workshop_generator, self_automation, cooking_assistant, music_dj, etc.) |
| 5 | HOCH | brain.py | 2465-2482 | 469-479 | ✅ FIXED | `_states_lock = asyncio.Lock()` (Zeile 212), `get_states_cached()` (Zeile 472) mit Lock |
| 6 | HOCH | main.py | 2189 | 2518-2519 | ⚠️ TEILWEISE | Safety-Cap bei 10.000 Eintraegen. **ABER**: `_token_lock` (Zeile 2216) wird NIE acquired — toter Code |
| 7 | HOCH | main.py | 7351-7362 | 7544-7560 | ⚠️ TEILWEISE | `_run_cmd()` nutzt jetzt `asyncio.to_thread()`. **ABER**: `_convert_audio_to_16k_mono()` (Zeile 1414) blockiert weiterhin synchron mit 30s Timeout |
| 8 | HOCH | main.py | 6118 | 6246-6248 | ✅ FIXED | F-086: API-Key-Check hinzugefuegt, HTTP 403 bei fehlendem Key |
| 9 | HOCH | main.py | 1340, 1380 | 1368, 1408, 4970 | ⚠️ TEILWEISE | Viele Stellen korrigiert. **ABER**: 3 HTTPExceptions leaken weiterhin `{e}`, ~25 Endpoints geben `str(e)` in JSON zurueck |
| 10 | HOCH | brain.py | 2405-2412 | 2438-2442 | ✅ FIXED | Post-Processing-Loop ersetzt ALLE `BaseException` in `_result_map` durch `None` |
| 11 | HOCH | main.py | 6381 | 6021-6328 | ✅ FIXED | Alle Referenzen konsistent `brain.workshop_generator` |
| 12 | MITTEL | main.py | 5025, 5043 | 5043-5053 | ⚠️ TEILWEISE | Urspruengliche Stelle gefixt. **ABER**: ~20 weitere synchrone `open()` in async Handlern |
| 13 | MITTEL | main.py | 871-872 | 871-874 | ❌ UNFIXED | `except Exception` jetzt mit `logger.debug()` statt `pass` — funktional identisch |
| 14 | MITTEL | brain.py | 6023-6027 | 2523 | ❌ UNFIXED | Re-Import `from datetime import datetime as _dt_cm` weiterhin vorhanden |
| 15 | MITTEL | websocket.py | 51 | 51, 76 | ❌ UNFIXED | `datetime.now().isoformat()` ohne Timezone in broadcast() und send_personal() |
| 16 | NIEDRIG | brain.py | 1200-1204 | 1218 | ⚠️ VERSCHLECHTERT | Rekursion jetzt **DEADLOCK**: `_process_inner()` haelt `_process_lock` → ruft `self.process()` auf → versucht Lock erneut zu acquiren → blockiert fuer immer |
| 17 | NIEDRIG | main.py | 585 | 585 | ❌ UNFIXED | `request.client` None-Check vorhanden, aber Proxy-Clients gruppiert |
| 18 | — | brain_callbacks.py | — | — | ✅ CLEAN | 29 Zeilen, leere Mixin-Klasse, 0 Bugs |

### Neue Bugs Batch 1

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| NEW-1 | 🔴 KRITISCH | brain.py | 1218 | Deadlock | **Retry-Pfad deadlockt.** `_process_inner()` haelt `_process_lock` → ruft `self.process()` auf → `asyncio.Lock` ist nicht reentrant → garantierter Deadlock bei "ja"/"nochmal". Regression durch Bug #2 Fix. | `self._process_inner()` statt `self.process()` auf Zeile 1218 |
| NEW-2 | 🟡 MITTEL | main.py | 2216 | Dead Code | `_token_lock = asyncio.Lock()` wird definiert aber NIE acquired. `_active_tokens` wird ohne Lock gelesen/geschrieben. | Lock entfernen oder korrekt einsetzen |
| NEW-3 | 🟢 NIEDRIG | brain.py | 2434 | Logic | `return_exceptions=True` in `gather()` ist redundant — `_with_timeout()` faengt alle Exceptions intern ab. No-Op Flag. | `return_exceptions=False` oder Kommentar |
| NEW-4 | 🟢 NIEDRIG | brain.py | 2448, 2451 | Dead Code | `isinstance(context, TimeoutError/BaseException)` Checks nach Exception-Filter-Loop — Branches sind unerreichbar. | Dead Code entfernen |
| NEW-5 | 🟡 MITTEL | main.py | 6526-6941 | Security | ~25 Endpoints geben `str(e)` in JSON-Body an Clients zurueck. Exponiert interne Fehlermeldungen (Pfade, Connection-Strings). | Generische Fehlermeldung, Details nur loggen |
| NEW-6 | 🟠 HOCH | main.py | 1414 | Performance | `_convert_audio_to_16k_mono()` ruft `subprocess.run()` synchron mit 30s Timeout auf. Blockiert Event-Loop komplett fuer Dauer der ffmpeg-Konvertierung. | `asyncio.create_subprocess_exec()` |
| NEW-7 | 🟠 HOCH | brain.py | 773 | Init | `proactive.start()` weiterhin NICHT in `_safe_init()`. Einziger `.start()` Call ohne Schutz. Exception = kompletter Init-Abbruch. | `_safe_init()` Wrapper |

---

## Bug-Report: Batch 2 — Memory-Kette

### DL#1 → DL#2 Status

| # | Severity | Modul | DL#1-Zeile | DL#2-Zeile | Status | Beschreibung |
|---|----------|-------|-----------|-----------|--------|-------------|
| 19 | KRITISCH | embedding_extractor.py | 23-27 | 19, 28-31 | ✅ FIXED | `threading.Lock` + Double-Checked-Locking in `_load_model()` |
| 20 | KRITISCH | semantic_memory.py | 193-201 | 175-242 | ⚠️ TEILWEISE | `chroma_ok`/`redis_ok` getrennt getrackt, `False` bei Redis-Failure. **ABER**: Kein Rollback des ChromaDB-Eintrags bei Redis-Failure |
| 21 | HOCH | memory.py | 420-443 | 418-449 | ⚠️ TEILWEISE | `offset`/`limit` Parameter + Cap bei 1000. **ABER**: Hard-Cap 1000 verhindert Pagination darueber hinaus |
| 22 | HOCH | dialogue_state.py | 104 | 110-117 | ✅ FIXED | Eviction der 25 aeltesten bei >50 Eintraegen |
| 23 | HOCH | memory.py + semantic_memory.py | 167, 280 | 168, 196, 282, 307, 428, 460, 584 | ✅ FIXED | Alle ChromaDB Calls in `asyncio.to_thread()`. **Ausnahme**: 2 `.update()` Calls (siehe NEW-A) |
| 24 | HOCH | correction_memory.py | 50-51 | 51-53, 381 | ✅ FIXED | `_rules_lock = asyncio.Lock()`, Lock acquired vor Rate-Limit-Check |
| 25 | HOCH | semantic_memory.py | 571-597 | 580-606 | ✅ FIXED | Redis-Indices (person, category, all Sets) werden korrekt bereinigt, `True` nur bei Erfolg |
| 26 | MITTEL | memory.py | 178-179 | 181 | ✅ FIXED | `dict(metadata)` Copy statt Mutation |
| 27 | MITTEL | semantic_memory.py | 151 | 151 | ❌ UNFIXED | MD5 mit Modulo 100K fuer Lock-Keys — hohe Kollisionswahrscheinlichkeit |
| 28 | MITTEL | conversation_memory.py | 78 | 78 | ❌ UNFIXED | Sekunden-Praezision fuer Project-IDs |
| 29 | MITTEL | semantic_memory.py | 334-411 | 342-416 | ⚠️ TEILWEISE | Async-Calls korrekt, **ABER**: N+1 Redis-Pattern (individuelle `hgetall` pro Fact) bleibt |
| 30 | MITTEL | conversation.py | 78 | 78, 92 | ❌ UNFIXED | HA UUID als `person` — kein Resolve zu menschenlesbarem Namen |
| 31 | NIEDRIG | semantic_memory.py | 396-401 | 402-409 | ⚠️ TEILWEISE | `logger.debug("Unhandled: %s", e)` — Exception weiterhin geschluckt, ChromaDB/Redis Divergenz |
| 32 | NIEDRIG | memory.py | 176-177 | 176-179 | ❌ UNFIXED | `except Exception: pass` bei Dedup-Check — stille Duplikat-Speicherung |
| 33 | NIEDRIG | memory.py | 453-455 | 454-461 | ❌ UNFIXED | `delete_episodes` gibt `len(episode_ids)` zurueck ohne Verifikation |

### Neue Bugs Batch 2

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| NEW-A | 🟠 HOCH | semantic_memory.py | 263, 404 | Async-Fehler | **2 synchrone ChromaDB `.update()` Calls** nicht in `asyncio.to_thread()`: `_update_existing_fact()` (Zeile 263) und `apply_decay()` (Zeile 404). Blockieren Event-Loop trotz Fix von Bug #23. | `asyncio.to_thread(self.chroma_collection.update, ...)` |
| NEW-E | 🟡 MITTEL | semantic_memory.py | 487-538 | Performance | **N+1 Redis in 5+ weiteren Methoden**: `get_facts_by_person()` (494), `get_facts_by_category()` (517), `get_all_facts()` (538). Systemisches Pattern, nicht nur in `apply_decay()`. | Redis Pipeline fuer Batch-`hgetall` |

---

## Bug-Report: Batch 3 — Prompt & Persoenlichkeit

### DL#1 → DL#2 Status

| # | Severity | Modul | DL#1-Zeile | DL#2-Zeile | Status | Beschreibung |
|---|----------|-------|-----------|-----------|--------|-------------|
| 34 | KRITISCH | personality.py | 2375-2384 | 2406-2408 | ✅ FIXED | `conversation_topic` sanitized: 200 Chars Limit, Newlines entfernt, SYSTEM:/ASSISTANT:/USER: gefiltert |
| 35 | KRITISCH | personality.py | 2352-2363 | 2377-2383 | ✅ FIXED | Weather-Daten typ-validiert: `isinstance(..., (int, float, str))`, Truncation auf 10/50 Chars |
| 36 | HOCH | personality.py | 2217-2218 | 2243 | ❌ UNFIXED | `_current_mood` Shared State ohne Lock in `build_system_prompt()` |
| 37 | HOCH | personality.py | 2274 | 2299 | ❌ UNFIXED | `_current_formality` Shared State ohne Lock |
| 38 | HOCH | mood_detector.py | 267-381 | 269-281 | ✅ FIXED | `_analyze_lock = asyncio.Lock()` (Zeile 83), `analyze()` vollstaendig geschuetzt |
| 39 | HOCH | mood_detector.py | 741-808 | 751-819 | ❌ UNFIXED | `analyze_voice_metadata()` weiterhin OHNE Lock — Race mit `analyze()` |
| 40 | MITTEL | personality.py | 1681-1708 | 1685-1787 | ⚠️ TEILWEISE | try/except um individuelle Redis-Calls. **ABER**: `incr`+`expire` nicht pipelined — Crash dazwischen laesst Keys ohne TTL |
| 41 | MITTEL | context_builder.py | 745 | 735-756 | ❌ UNFIXED | **Logik-Inversion entdeckt**: `latest_room` wird nur im `except`-Block zugewiesen, nie bei erfolgreichem Parse → falsche Raum-Zuordnung |
| 42 | MITTEL | personality.py | 2350-2354 | 2374-2375 | ✅ FIXED | Weather jetzt aus `context.get("house", {}).get("weather", {})` ODER `context.get("weather", {})` |
| 43 | MITTEL | situation_model.py | 95 | 90-95 | ⚠️ TEILWEISE | Aktuell selbst-konsistent (naive ↔ naive). **ABER**: Fragil — externe aware-Timestamps wuerden TypeError verursachen |
| 44 | MITTEL | mood_detector.py | 719, 725 | 734 | ❌ UNFIXED | `self._last_voice_emotion` Fallback liest Daten von zuletzt verarbeiteter Person — Cross-Person-Leak |
| 45 | MITTEL | mood_detector.py/time_awareness.py | 519 | 518 | ⚠️ TEILWEISE | Abhaengig von Redis-Client-Config (`decode_responses`). Bei bytes-Client: Counter reset bei jedem Call |
| 46 | NIEDRIG | personality.py | 1385 | 1388 | ❌ UNFIXED | MD5 + Modulo 10M fuer Alert-Dedup — Kollisionen unterdruecken Warnungen |
| 47 | NIEDRIG | personality.py | 2229 | 2258 | ❌ UNFIXED | `mood_config["style_addon"]` Bracket-Notation → `KeyError` bei fehlendem Key |
| 48 | NIEDRIG | personality.py | 355-356 | 358, 684 | ❌ UNFIXED | `_curiosity_count_today` dict unbegrenzt innerhalb eines Tages |

### Neue Bugs Batch 3

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| NEW-B | 🟡 MITTEL | context_builder.py | 746-754 | Logic | **Logik-Inversion in `_detect_user_location()`**: `latest_room` nur im `except`-Block zugewiesen. Erfolgreicher Parse aktualisiert nur `latest_motion`, nicht `latest_room`. Funktion gibt falschen Raum zurueck. | `latest_room = entity_id` im `try`-Block setzen |
| NEW-C | 🟡 MITTEL | mood_detector.py | 734 | Logic | **Cross-Person Voice-Emotion-Leak**: `self._last_voice_emotion` Fallback liest Emotion der zuletzt verarbeiteten Person. Person A bekommt Person B's Voice-Emotion. (Gleiche Root Cause wie #44) | Aus per-Person State-Dict lesen |
| NEW-D | 🟡 MITTEL | personality.py | 2443-2444 | Logic | **Stille Template-Variablen**: `format_map(defaultdict(str, ...))` ersetzt fehlende Platzhalter mit Leerstrings. Template/Code-Mismatches werden unsichtbar. | `str.format_map()` mit normalem Dict + explizite Fehlerbehandlung |

---

## Bug-Report: Batch 4 — Aktionen & Inference

### DL#1 → DL#2 Status

| # | Severity | Modul | DL#1-Zeile | DL#2-Zeile | Status | Beschreibung |
|---|----------|-------|-----------|-----------|--------|-------------|
| 49 | KRITISCH | function_calling.py | 5212-5244 | 5226-5233 | ✅ FIXED | `lock` und `alarm_control_panel` aus `_CALL_SERVICE_ALLOWED_DOMAINS` entfernt (Kommentar Zeile 5223) |
| 50 | KRITISCH | function_calling.py | 5471 | 5491-5507 | ✅ FIXED | `action` validiert (`lock`/`unlock`), `unlock` erfordert jetzt `requires_confirmation: True` |
| 51 | KRITISCH | function_calling.py | 87-92 | 94-97, 101, 110, 121 | ✅ FIXED | Exceptions geloggt (95-97), downstream `isinstance(X, list)` filtert Exception-Objekte sicher |
| 52 | KRITISCH | function_calling.py | 3119-3154 | 3124-3144 | ✅ FIXED | `_tools_cache_lock` (threading.Lock, Zeile 3127), Double-Checked-Locking Pattern |
| 53 | HOCH | function_calling.py | 1050-1052 | 1146 | ⚠️ TEILWEISE | `_tools_cache = None` weiterhin OHNE `_tools_cache_lock`. GIL-safe in CPython, aber logische Race bei parallelem Catalog-Refresh |
| 54 | HOCH | action_planner.py | 335-345 | 335-346 | ✅ FIXED | `asyncio.wait()` statt `wait_for`. Pending Tasks cancelled, Ergebnisse einzeln gesammelt |
| 55 | HOCH | action_planner.py | 431-440 | 432-435 | ✅ FIXED | `tool_calls` gefiltert: nur Dicts mit `"function"` Key akzeptiert |
| 56 | HOCH | function_calling.py | 1356-1358 | 1361-1362 | ❌ UNFIXED | `_ASSISTANT_TOOLS_STATIC` bei Module-Load gebaut. Runtime-Rebuild in `get_assistant_tools()` mitigiert, aber initiale Berechnung unnoetig |
| 57 | HOCH | function_calling.py | 3413-3424 | 3422-3428 | ✅ FIXED | Lazy-Load Closure mit `nonlocal` Cache in `_check_consequences()` |
| 58 | HOCH | function_calling.py | 4741-4786 | 4792-4806 | ⚠️ TEILWEISE | `fcntl.flock()` auf Write. **ABER**: Read (Zeile 4794) VOR Lock — TOCTOU bei concurrent Calls |
| 59 | MITTEL | function_calling.py | 4963 | 4983 | ✅ FIXED | `_clean_room(None)` gibt falsy Wert zurueck, alle Downstream-Checks pruefen Truthiness |
| 60 | MITTEL | ollama_client.py | 596-610 | 343, 407, 554 | ✅ FIXED | `is_available` ist `@property` auf `CircuitBreaker`, nicht async Methode. Korrekt ohne `await` |
| 61 | MITTEL | function_calling.py | 3803-3804 | 3820-3822 | ✅ FIXED | `CancelledError` re-raised, Failure via `logger.debug` geloggt |
| 62 | MITTEL | action_planner.py | 162 | 143-148, 162 | ❌ UNFIXED | `_QUESTION_STARTS` zu aggressiv: "kannst du" matched imperative Multi-Step-Befehle |
| 63 | MITTEL | model_router.py | 191-192 | 191-192 | ❌ UNFIXED | `_is_model_installed` gibt `True` bei leerem `_available_models` — kein Fallback |
| 64 | MITTEL | function_validator.py | 28-32 | 28-32 | ❌ UNFIXED | `require_confirmation` bei Init eingefroren, Hot-Reload unwirksam |
| 65 | MITTEL | declarative_tools.py | 218-220 | 220 | ❌ UNFIXED | Jeder Executor erstellt eigene Registry → redundantes YAML-Parsen |
| 66 | MITTEL | function_calling.py | 3309-3336 | 3329-3341 | ❌ UNFIXED | Levenshtein gegen ALLE Room-Profiles ohne Cache/Early-Return |
| 67 | NIEDRIG | function_calling.py | 61-63 | 52 | ✅ KEIN BUG | `_entity_catalog` wird per Refresh ersetzt, waechst nicht unbegrenzt |
| 68 | NIEDRIG | action_planner.py | 52-54 | 52-53 | ❌ UNFIXED | `MAX_ITERATIONS` bei Module-Load — Hot-Reload unwirksam |
| 69 | NIEDRIG | request_context.py | 38 | 38 | ❌ UNFIXED | `dict()` dropped Duplicate-Headers — Minor |

### Neue Bugs Batch 4

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| NEW-B4-A | 🟡 MITTEL | action_planner.py | 344 | Async | `t.result()` ohne try/except. Task-Exceptions propagieren unkontrolliert statt in `results` gesammelt. | `try: r = t.result() except Exception as e: r = e` |
| NEW-B4-B | 🟡 MITTEL | function_calling.py | 1061 | Silent Error | `asyncio.gather(states_task, mindhome_task)` Ergebnis `_` (mindhome) wird verworfen. Failure still geschluckt. | Mindhome-Result pruefen und loggen |

---

## Dokumentations-Verifikation (DL#2 Update)

| Behauptung | DL#1 Status | DL#2 Status | Beweis |
|---|---|---|---|
| Bug B1 gefixt (intent_tracker.start()) | ✅ FEHLALARM | ✅ BESTAETIGT | brain.py:555 — `intent_tracker.initialize()` startet Loop |
| Bug B2 gefixt (Morning Briefing Auto-Trigger) | ✅ GEFIXT | ✅ BESTAETIGT | proactive.py — `_check_morning_briefing()`, Motion-Trigger |
| Bug B3 gefixt (Summarizer Callback) | ✅ GEFIXT | ✅ BESTAETIGT | brain.py:531 — `set_notify_callback()` |
| Bug B4 gefixt (Saisonale Rolladen) | ✅ GEFIXT | ✅ BESTAETIGT | proactive.py — seasonal Loop + execute |
| Bug B5 gefixt (Was-waere-wenn mit HA-Daten) | ✅ GEFIXT | ✅ BESTAETIGT | brain.py:8495 — live HA-Daten |
| Bug B6 (Wartungs-Loop) | ✅ FEHLALARM | ✅ BESTAETIGT | proactive.py — `_run_diagnostics_loop()` alle 30 Min |
| Token Streaming "komplett fehlend" | ❌ IST IMPLEMENTIERT | ✅ BESTAETIGT | websocket.py:137-152, main.py:1978-2100 |
| Interrupt Queueing "komplett fehlend" | ❌ IST IMPLEMENTIERT | ✅ BESTAETIGT | websocket.py:189, `_ws_interrupt_flag` |

---

## Fehlerklassen-Verteilung (DL#2)

| Fehlerklasse | DL#1 | DL#2 (offen) | Trend | Kritischste offene |
|---|:---:|:---:|---|---|
| 1. Async-Fehler | 5 | 3 | ↓ | 2 synchrone ChromaDB `.update()` Calls (NEW-A) |
| 2. Stille Fehler | 8 | 5 | ↓ | `except Exception: pass` bei Dedup (#32) |
| 3. Race Conditions | 17 | 6 | ↓↓ | `_current_mood`/`_current_formality` ohne Lock (#36/#37) |
| 4. None-Fehler | 5 | 0 | ↓↓↓ | Alle behoben |
| 5. Init-Fehler | 5 | 3 | ↓ | proactive.start() ungeschuetzt (NEW-7) |
| 6. API-Fehler | 2 | 0 | ↓↓ | Alle behoben |
| 7. Daten-Fehler | 5 | 3 | ↓ | HA UUID als person (#30) |
| 8. Config-Fehler | 3 | 3 | → | `require_confirmation` eingefroren (#64) |
| 9. Memory Leaks | 5 | 2 | ↓ | `_curiosity_count_today` (#48) |
| 10. Logik-Fehler | 14 | 8 | ↓ | `_detect_user_location()` Inversion (NEW-B) |
| 11. Security | 8 | 2 | ↓↓↓ | ~25 Endpoints leaken `str(e)` (NEW-5) |
| 12. Resilience | 5 | 3 | ↓ | Shutdown verpasst 30+ Komponenten (#4) |
| 13. Performance | 6 | 5 | ↓ | N+1 Redis systemisch in semantic_memory (NEW-E) |

---

## Cross-Modul Findings (DL#2 Update)

| # | DL#1 Finding | DL#2 Status | Verbleibend |
|---|-------------|-----------|------------|
| 1 | brain.py process() ohne Lock | ✅ FIXED — `_process_lock` vorhanden | **ABER**: Retry-Pfad deadlockt (NEW-1) |
| 2 | ChromaDB Calls blockieren Event-Loop | ✅ FIXED — `asyncio.to_thread()` | **ABER**: 2 `.update()` Calls vergessen (NEW-A) |
| 3 | conversation.py UUID als person | ❌ UNFIXED | HA Voice Pipeline Facts werden nie per Person gefunden |
| 4 | Sanitization-Luecke personality.py | ✅ FIXED — conversation_topic + Weather sanitized | — |
| 5 | call_service generisches Gateway | ✅ FIXED — lock/alarm aus Domains entfernt, unlock braucht Confirmation | — |

### Neue Cross-Modul Findings DL#2

| # | Module | Beschreibung |
|---|--------|-------------|
| 6 | brain.py → personality.py | **_process_lock schuetzt nicht personality State**: brain.py serialisiert process()-Calls, aber personality.py's `_current_mood`/`_current_formality` werden in `build_system_prompt()` geschrieben, das INNERHALB des process()-Locks aufgerufen wird. Da Lock reentrant ist → kein paralleler Schutz noetig WENN personality nur aus process() aufgerufen wird. ABER: `build_notification_prompt()` und `build_routine_prompt()` rufen personality AUSSERHALB von process() auf. |
| 7 | semantic_memory.py | **N+1 Redis ist systemisch**: Nicht nur `apply_decay()` (Bug #29), sondern 5+ weitere Methoden (`get_facts_by_person`, `get_facts_by_category`, `get_all_facts`, etc.) verwenden identisches Pattern. Gesamtimpact: Hunderte individuelle Redis-Roundtrips pro Operation. |

---

## Top-5 verbleibende Bugs (Prioritaet fuer P6a)

| Rang | Bug | Severity | Beschreibung | Aufwand |
|------|-----|----------|-------------|---------|
| 1 | NEW-1 | 🔴 KRITISCH | **Deadlock bei Retry**: `_process_inner()` → `self.process()` → Lock re-acquire → haengt | 1 Zeile: `self._process_inner()` statt `self.process()` |
| 2 | NEW-7 | 🟠 HOCH | **proactive.start() ungeschuetzt**: Exception = kompletter Init-Abbruch | 3 Zeilen: `_safe_init()` Wrapper |
| 3 | NEW-6 | 🟠 HOCH | **Audio-Konvertierung blockiert Event-Loop**: 30s synchrones subprocess.run | `asyncio.create_subprocess_exec()` |
| 4 | #36/#37 | 🟠 HOCH | **personality.py Race Conditions**: `_current_mood`/`_current_formality` als Parameter durchreichen | Signatur-Aenderung in 4+ Methoden |
| 5 | NEW-A | 🟠 HOCH | **2 synchrone ChromaDB Updates**: Block Event-Loop trotz Bug #23 Fix | 2x `asyncio.to_thread()` Wrapper |

---

## Zero-Bug-Acknowledgments (DL#2)

| Modul | Batch | DL#1 | DL#2 |
|-------|-------|------|------|
| `brain_callbacks.py` | Batch 1 | 0 Bugs | 0 Bugs — weiterhin clean |
| `embeddings.py` | Batch 2 | 0 Bugs | 0 Bugs — weiterhin clean |
| `memory_extractor.py` | Batch 2 | 0 Bugs | 0 Bugs — weiterhin clean |
| `pre_classifier.py` | Batch 4 | 0 Bugs | 0 Bugs — weiterhin clean |

---

## KONTEXT AUS PROMPT 4a (DL#2): Bug-Report (Core-Module)

### Statistik
DL#1: 88 Bugs → DL#2: 26 FIXED, 15 PARTIALLY, 33 UNFIXED, 14 NEW
Aktuelle Bug-Bilanz: 62 offene Bugs (1 KRITISCH, 12 HOCH, 33 MITTEL, 16 NIEDRIG)

### Kritische Bugs (1 offen)
1. `brain.py:1218` — **NEW-1: Deadlock bei Retry** — `_process_inner()` haelt `_process_lock`, ruft `self.process()` auf → nicht-reentrant Lock → garantierter Deadlock

### Frueherer KRITISCH-Status (alle gefixt)
- Bug #1 (conv_memory Duplikat) → FIXED
- Bug #2 (process() ohne Lock) → FIXED (aber Regression NEW-1)
- Bug #3 (Module ohne _safe_init) → TEILWEISE (proactive.start() offen)
- Bug #19 (embedding_extractor TOCTOU) → FIXED
- Bug #20 (semantic_memory Rollback) → TEILWEISE
- Bug #34 (Prompt Injection conversation_topic) → FIXED
- Bug #35 (Prompt Injection Weather) → FIXED
- Bug #49 (call_service Gateway lock/alarm) → FIXED
- Bug #50 (lock_door unlock ohne Confirmation) → FIXED
- Bug #51 (return_exceptions nicht geprueft) → FIXED
- Bug #52 (_tools_cache ohne Lock) → FIXED

### Hohe Bugs (12 offen)
- `brain.py:773` — NEW-7: proactive.start() ohne _safe_init()
- `main.py:1414` — NEW-6: Synchrones subprocess.run (ffmpeg 30s)
- `personality.py:2243` — #36: _current_mood Race Condition (unfixed)
- `personality.py:2299` — #37: _current_formality Race Condition (unfixed)
- `mood_detector.py:751` — #39: analyze_voice_metadata() ohne Lock (unfixed)
- `semantic_memory.py:263,404` — NEW-A: 2 synchrone ChromaDB .update()
- `brain.py:9773-9800` — #4: Shutdown verpasst 30+ Komponenten (teilweise)
- `main.py:1368,1408,4970` — #9: Error-Details in HTTP-Responses (teilweise)
- `main.py:7544` — #7: Audio-Konvertierung blockiert (teilweise)
- `function_calling.py:1146` — #53: _tools_cache = None ohne Lock (teilweise)
- `function_calling.py:4794` — #58: settings.yaml TOCTOU (teilweise)
- `function_calling.py:1361` — #56: _ASSISTANT_TOOLS_STATIC bei Module-Load (unfixed)

### Patterns die in 4b weitergesucht werden sollten
1. **Race Conditions auf Instance-Variables** — personality.py (#36/#37) und mood_detector.py (#39) unfixed. In 4b: proactive.py, routine_engine.py, anticipation.py pruefen
2. **N+1 Redis** — Systemisches Pattern in semantic_memory.py (5+ Methoden). In 4b: Alle Redis-intensiven Module pruefen
3. **`except Exception: pass` → `logger.debug()`** — Bulk-Fix aus P8 funktional identisch mit `pass` bei Default-Log-Level. In 4b: Pruefen ob kritische Fehler dadurch maskiert
4. **Synchrone I/O in async Handlern** — main.py hat ~20 ungefixte Stellen. In 4b: Alle async Endpoints pruefen
5. **Deadlock-Risiko bei verschachtelten Locks** — NEW-1 zeigt reales Deadlock durch Lock-Regression. In 4b: Alle Module mit asyncio.Lock auf Reentrance-Risiko pruefen
6. **Shutdown-Asymmetrie** — 30+ Komponenten in `initialize()` ohne korrespondierenden `shutdown()` Call. In 4b: Pruefen welche Module Background-Tasks/Connections halten
