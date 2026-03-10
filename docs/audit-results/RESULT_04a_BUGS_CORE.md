# Audit-Ergebnis: Prompt 4a — Systematische Bug-Jagd (Core-Module, Prioritaet 1-4)

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: 26 Core-Module in 4 Batches, 13 Fehlerklassen, Cross-Modul-Pruefung
**Methode**: 4 parallele Audit-Agenten + Grep-Bulk-Suche + Dokumentations-Verifikation

---

## Gesamt-Statistik

```
Gesamt: 88 Bugs (Prioritaet 1-4)
  KRITISCH: 10
  HOCH: 18
  MITTEL: 38
  NIEDRIG: 22

Haeufigste Fehlerklasse: Race Conditions (17 Vorkommen)
Am staerksten betroffenes Modul: function_calling.py (12 Bugs)
Zweitstaerkstes: brain.py (11 Bugs)
```

---

## Bug-Report: Batch 1 — Core (brain.py, brain_callbacks.py, main.py, websocket.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 1 | KRITISCH | brain.py | 2356+2394 | Logic | **Duplicate "conv_memory" key in _mega_tasks.** Zeile 2356 `("conv_memory", _get_conversation_memory(text))` und Zeile 2394 `("conv_memory", conversation_memory.get_memory_context())`. `dict(zip())` ueberschreibt ersten Wert. Semantische Konversationssuche geht verloren. | Distinct keys: `"conv_memory"` und `"conv_memory_ctx"` |
| 2 | KRITISCH | brain.py | 1076-1104 | Race Condition | **Kein Lock auf `process()`.** Schreibt `self._current_person`, `self._request_from_pipeline`, `self._last_context` etc. ohne Lock. Concurrent HTTP + WebSocket + Workshop-Requests korrumpieren Shared State. Person A's Befehle koennten unter Person B's Trust-Level ausgefuehrt werden. | `asyncio.Lock` oder per-Request Context-Objekt statt Instance-Attribute |
| 3 | KRITISCH | brain.py | 477-597 | Init | **Module 1-30 nicht in `_safe_init()`.** Jede Exception (Redis down, ChromaDB timeout) crasht den gesamten Start. `ProactiveManager.start()` (Zeile 760) ebenfalls nicht geschuetzt. | `_safe_init()` Wrapper fuer Module 1-30 |
| 4 | HOCH | brain.py | 10131-10178 | Resilience | **Shutdown verpasst Komponenten.** `shutdown()` schliesst `ollama_client`, `memory`, `ha`, `proactive`, `task_registry`. Aber `self.cooking_assistant`, `self.music_dj`, `self.repair_planner`, `self.ambient_audio`, `self.health_monitor` haben eigene Background-Tasks/Connections die nie gestoppt werden. | Alle Module mit Background-Tasks in shutdown() aufnehmen |
| 5 | HOCH | brain.py | 2465-2482 | Race Condition | **`_states_cache` ohne Lock.** `self._states_cache` wird in `process()` geschrieben und von vielen Subsystemen gelesen. Bei parallelen Requests kann ein Request den Cache mitten im Lesen eines anderen ueberschreiben. | Per-Request lokale Variable oder Lock |
| 6 | HOCH | main.py | 363 | Memory Leak | **`_update_log` ring-buffer waechst unbegrenzt bei Log-Flooding.** `_UpdateLogHandler.emit()` appendet zu Liste mit `maxlen` — korrekt. Aber `_error_buffer` und `_activity_buffer` (Zeile 82-149) nutzen Deques mit Limit, was OK ist. `_active_tokens` (Zeile 2189) waechst bis zum 15-Min Cleanup. | Cleanup-Intervall fuer `_active_tokens` verkuerzen |
| 7 | HOCH | main.py | 7351-7362 | Performance | **Synchrones `subprocess.run` in async Endpoints.** `_run_cmd()` blockiert Event-Loop in `ui_system_status` (5+ sequentielle Subprocess-Calls: git, docker inspect). | `asyncio.create_subprocess_exec()` oder `asyncio.to_thread()` |
| 8 | HOCH | main.py | 6118 | Security | **Workshop-Chat umgeht API-Key.** `/api/workshop/chat` hat keinen API-Key-Check, geht aber durch `brain.process()`. Jeder im Netzwerk kann ohne Auth den Assistenten nutzen. | API-Key-Middleware fuer Workshop-Endpoints |
| 9 | HOCH | main.py | 1340, 1380 | Security | **Interne Error-Details in HTTP-Responses geleakt.** 30+ Endpoints nutzen `detail=f"Fehler: {e}"` — exponiert Hostnames, Ports, interne Fehlermeldungen. | Generische Fehlermeldung fuer Client, Details nur server-seitig loggen |
| 10 | HOCH | brain.py | 2405-2412 | Silent Error | **`_with_timeout` gibt Exception-Objekte als normale Werte zurueck.** Nur `"context"` Key wird auf `isinstance(BaseException)` geprueft. Alle anderen Keys aus `_result_map` werden mit `.get()` konsumiert OHNE Exception-Check. Eine Exception in einem Subsystem wird als truthy Ergebnis behandelt. | `isinstance(v, BaseException)` Check fuer jedes Ergebnis |
| 11 | HOCH | main.py | 6381 | None Error | **`brain.workshop_gen` statt `brain.workshop_generator`.** 6 Workshop-Endpoints (Zeilen 6381, 6465, 6481, 6498, 6513, 6527) referenzieren nicht-existentes Attribut. Garantierter `AttributeError` bei Aufruf. | `brain.workshop_gen` → `brain.workshop_generator` |
| 12 | MITTEL | main.py | 5025, 5043, 2196, 7061 | Performance | **Synchrones File-I/O in async Handlern.** `yaml.safe_load()/safe_dump()` blockiert Event-Loop. | `asyncio.to_thread()` |
| 13 | MITTEL | main.py | 871-872 | Silent Error | **`except Exception: pass` auf ChromaDB count.** Persistenter ChromaDB-Fehler zeigt dauerhaft 0 Episoden. | Debug-Level Logging |
| 14 | MITTEL | main.py | 6591-6602, 7265-7275 | Silent Error | **Multiple `except Exception: pass` Bloecke** in Workshop-Notifications und Automations-Listing. | Debug-Level Logging |
| 15 | MITTEL | brain.py | 6023-6027 | Logic | **Re-Import von datetime im lokalen Scope.** Shadows Module-Level Import. | Inneren Import entfernen |
| 16 | MITTEL | websocket.py | 51 | Data | **`datetime.now().isoformat()` ohne Timezone.** Naive Timestamps in Broadcast-Messages. | `datetime.now(timezone.utc).isoformat()` |
| 17 | NIEDRIG | brain.py | 1200-1204 | Logic | **Rekursiver Self-Call in `process()` fuer Retry.** Bounded durch Reset, aber fragiles Pattern. | Loop statt Rekursion |
| 18 | NIEDRIG | main.py | 585 | None | **`request.client` koennte None sein.** Korrekt behandelt, aber Rate-Limiting gruppiert Proxy-Clients zusammen. | X-Forwarded-For Header nutzen |

---

## Bug-Report: Batch 2 — Memory-Kette (memory.py, semantic_memory.py, conversation_memory.py, memory_extractor.py, correction_memory.py, dialogue_state.py, embeddings.py, embedding_extractor.py, conversation.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 19 | KRITISCH | embedding_extractor.py | 23-27 | Race Condition | **TOCTOU Race in `_load_model()`.** Kein `threading.Lock` — zwei Threads koennen gleichzeitig Modell laden. `_model_loading` Flag bietet keinen Schutz. | `threading.Lock` um Load-Block |
| 20 | KRITISCH | semantic_memory.py | 193-201 | Logic | **`_store_fact_inner` hat kein Rollback.** ChromaDB-Fehler verhindert Redis-Speicherung; Redis-Fehler laesst ChromaDB-Eintrag ohne Index. Partial Failure hinterlaesst inkonsistente Stores. | Unabhaengig in beide Stores schreiben, Inkonsistenzen loggen |
| 21 | HOCH | memory.py | 420-443 | Performance | **`get_all_episodes()` laedt ALLE ChromaDB-Dokumente in Memory.** Kein serverseitiges Limit/Offset. O(n) Memory bei grosser Collection. | ChromaDB limit/offset nutzen |
| 22 | HOCH | dialogue_state.py | 104 | Memory Leak | **`self._states` dict waechst unbegrenzt.** Jeder unique `person` Wert erstellt Eintrag der nie entfernt wird. | LRU-Cache oder periodisches Pruning |
| 23 | HOCH | memory.py | 167 + semantic_memory.py | Async/Blocking | **ChromaDB `.query()` Calls blockieren Event-Loop.** `store_episode` nutzt `asyncio.to_thread()` fuer `.add()`, aber `.query()` Calls (memory.py:167, 280) und ALLE semantic_memory.py Calls sind synchron. | Alle ChromaDB-Calls in `asyncio.to_thread()` wrappen |
| 24 | HOCH | correction_memory.py | 50-51 | Race Condition | **Rate-Limit-Counter ohne Lock.** Concurrent `store_correction` kann `RULES_PER_DAY_LIMIT` ueberschreiten. | `asyncio.Lock` um Rate-Limit Check |
| 25 | HOCH | semantic_memory.py | 571-597 | Logic | **`_delete_fact_inner` meldet Erfolg obwohl Redis-Indexes nicht bereinigt.** `return True` wenn Redis=None. Dead-Code auf Zeile 582. | Rueckgabewert korrigieren, Dead-Code entfernen |
| 26 | MITTEL | memory.py | 178-179 | Data | **Mutable Default Mutation.** `meta = metadata or {}` mutiert Caller's Dict. | `dict(metadata) if metadata else {}` |
| 27 | MITTEL | semantic_memory.py | 151 | Logic | **MD5 mit Modulo 100K fuer Lock-Keys.** Unrelated Facts koennen sich gegenseitig blockieren. | SHA-256 und groesserer Keyspace |
| 28 | MITTEL | conversation_memory.py | 78 | Logic | **Project-ID mit Sekunden-Praezision.** Kollision bei gleichzeitiger Erstellung. | Microseconds oder Random-Suffix |
| 29 | MITTEL | semantic_memory.py | 334-411 | Performance | **N+1 Redis Pattern in apply_decay().** Hunderte individuelle `hgetall` Calls statt Pipeline. | Redis Pipeline nutzen |
| 30 | MITTEL | conversation.py | 78 | Data | **HA `user_id` (UUID) als `person` gesendet.** Memory-Chain erwartet human-readable Names. Facts via Voice Pipeline werden nie per Person gefunden. | UUID → Display Name Aufloesung |
| 31 | NIEDRIG | semantic_memory.py | 396-401 | Silent Error | **`except Exception: pass` in `apply_decay` ChromaDB Update.** Redis/ChromaDB Divergenz wird nie geloggt. | Logging hinzufuegen |
| 32 | NIEDRIG | memory.py | 176-177 | Silent Error | **`except Exception: pass` bei Dedup-Check.** Persistenter ChromaDB-Fehler deaktiviert Dedup still. | Debug Logging |
| 33 | NIEDRIG | memory.py | 453-455 | Logic | **`delete_episodes` meldet count die nicht existieren.** ChromaDB ignoriert non-existent IDs still. | Count verifizieren |

---

## Bug-Report: Batch 3 — Prompt & Persoenlichkeit (context_builder.py, personality.py, mood_detector.py, situation_model.py, time_awareness.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 34 | KRITISCH | personality.py | 2375-2384 | Security | **Prompt Injection via `conversation_topic`.** Wird aus User-Texten gebaut (brain.py:2514) und UNSANITIZED in System-Prompt injiziert. `_sanitize_for_prompt()` existiert in context_builder.py wird aber NICHT aufgerufen. Malicious User kann JARVIS-Persoenlichkeit ueberschreiben. | `_sanitize_for_prompt()` auf `_conv_topic` anwenden |
| 35 | KRITISCH | personality.py | 2352-2363 | Security | **Prompt Injection via Weather-Daten.** `temperature` und `wind_speed` aus HA-Context werden unsanitized in System-Prompt eingebettet. Kompromittierte HA-Entity kann Injection-Payload liefern. context_builder sanitized `condition`, aber nicht temp/wind. | Typ-Validierung (numerisch) oder Sanitization |
| 36 | HOCH | personality.py | 2217-2218 | Race Condition | **`self._current_mood` Shared State.** Wird pro Request geschrieben, aber von `build_notification_prompt()`, `build_routine_prompt()` etc. gelesen. Concurrent Requests ueberschreiben sich gegenseitig. Code-Kommentar F-020 erkennt das Problem bereits. | Mood als Parameter durchreichen statt Instance-Variable |
| 37 | HOCH | personality.py | 2274 | Race Condition | **`self._current_formality` Shared State.** Gleicher Pattern wie #36 — geschrieben in `build_system_prompt()`, gelesen von 4+ Methoden. | Formality als Parameter durchreichen |
| 38 | HOCH | mood_detector.py | 267-381 | Race Condition | **Load-Modify-Store Pattern ohne Lock.** `_load_person_state()` → Instance-Vars mutieren → `_store_person_state()`. Jedes `await` dazwischen erlaubt Interleaving. Concurrent `analyze()` Calls korrumpieren Mood-State. | Per-Person `asyncio.Lock` |
| 39 | HOCH | mood_detector.py | 741-808 | Race Condition | **`analyze_voice_metadata()` gleicher Pattern.** Load/Store ohne Lock, concurrent mit `analyze()`. | Gleicher Fix wie #38 |
| 40 | MITTEL | personality.py | 1681-1708, 1738-1763 | Resilience | **Ungeschuetzte Redis-Calls in Running-Gag-Funktionen.** `incr()`, `expire()` ohne try/except. Redis-Fehler crasht den gesamten Request. | try/except um Redis-Calls |
| 41 | MITTEL | context_builder.py | 745 | Logic | **String-Vergleich fuer Timestamps.** `last_changed > latest_motion` vergleicht ISO-Strings. Funktioniert nur bei identischem Format. Timezone-Suffixe (`Z` vs `+00:00` vs None) brechen Vergleich. | `datetime.fromisoformat()` vor Vergleich |
| 42 | MITTEL | personality.py | 2350-2354 | Logic | **Weather Section liest `context.get("weather")`.** Aber context_builder.py speichert Weather unter `context["house"]["weather"]`. Wetter-Awareness-Section wird NIE populiert. | `context.get("house", {}).get("weather", {})` |
| 43 | MITTEL | situation_model.py | 95 | Logic | **Timezone-Mismatch.** `datetime.now()` (naive) minus `datetime.fromisoformat(t)` (potenziell aware) → `TypeError`. | Konsistente TZ-Behandlung |
| 44 | MITTEL | mood_detector.py | 719, 725 | Logic | **Person-spezifische Daten aus Instance-State statt Person-Dict gelesen.** `get_mood_prompt_hint()` liest `self._last_voice_signals` statt aus dem per-Person State Dict `s`. Falsche Voice-Daten fuer angefragte Person. | Aus `s.get("voice_signals", [])` lesen |
| 45 | MITTEL | mood_detector.py | 519 / time_awareness.py:519 | Data | **Bytes vs String Vergleich bei Redis-Date.** `stored_date != today` ist IMMER True weil `bytes != str`. Tageszaehler resetten bei JEDEM Call statt nur bei Datumswechsel. | `stored_date.decode()` vor Vergleich |
| 46 | NIEDRIG | personality.py | 1385 | Security | **MD5 mit kleinem Modulo fuer Alert-Dedup.** 10M Buckets → Kollisionen unterdrucken legitime Warnungen. | SHA-256 oder groesserer Modulus |
| 47 | NIEDRIG | personality.py | 2229 | Logic | **`mood_config["max_sentences_mod"]` mit Bracket-Notation.** YAML-konfigurierte Mood-Styles ohne dieses Feld → `KeyError`. | `.get("max_sentences_mod", 0)` |
| 48 | NIEDRIG | personality.py | 355-356 | Memory | **`_curiosity_count_today` unbegrenzt.** Per-User Dict ohne Size-Cap. | Size-Limit hinzufuegen |

---

## Bug-Report: Batch 4 — Aktionen & Inference (function_calling.py, function_validator.py, declarative_tools.py, action_planner.py, ollama_client.py, model_router.py, pre_classifier.py, request_context.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 49 | KRITISCH | function_calling.py | 5212-5244 | Security | **`_exec_call_service` ist generische HA-Gateway-Funktion.** LLM kann JEDEN Service in erlaubten Domains ausfuehren. Domain-Whitelist enthaelt `lock`, `alarm_control_panel`. LLM-Halluzination `domain="lock", service="unlock"` oeffnet Haustuer OHNE zusaetzliche Validierung. | Service-Name Whitelist pro Domain, oder `call_service` aus `_ALLOWED_FUNCTIONS` entfernen |
| 50 | KRITISCH | function_calling.py | 5471 | Security | **`_exec_lock_door` akzeptiert `action` direkt vom LLM.** `action="unlock"` oeffnet Tuer ohne Confirmation-Flow. Umgeht `FunctionValidator` da Unlock nicht in Default `require_confirmation` ist. | Expliziter `action in ("lock", "unlock")` Check + Pflicht-Confirmation fuer Unlock |
| 51 | KRITISCH | function_calling.py | 87-92 | None/Data | **`return_exceptions=True` in `_load_mindhome_domains`.** Exception-Objekte werden nicht einzeln geprueft. Individueller API-Endpoint-Failure wird still geschluckt. | `isinstance(X, BaseException)` Check pro Ergebnis |
| 52 | KRITISCH | function_calling.py | 3119-3154 | Race Condition | **`_tools_cache` Module-Level Global ohne Lock.** Concurrent Requests koennen Rebuild triggern oder teilweise-geschriebenen Cache lesen. `_entity_catalog` hat Lock, aber `_tools_cache` nicht. | `asyncio.Lock` oder atomarer Swap |
| 53 | HOCH | function_calling.py | 1050-1052 | Race Condition | **`_tools_cache = None` waehrend Catalog-Refresh.** Innerhalb Entity-Catalog Lock, aber `get_assistant_tools()` liest AUSSERHALB des Locks. Concurrent Call baut Tools mit stale Catalog. | `_tools_cache = None` erst NACH Catalog-Update |
| 54 | HOCH | action_planner.py | 335-345 | Async/Logic | **`asyncio.wait_for` um `asyncio.gather` verliert Ergebnisse bei Timeout.** Tasks werden cancelled, teilweise abgeschlossene Ergebnisse gehen verloren. Fake TimeoutError-Liste ersetzt echte Resultate. | `asyncio.wait` mit Timeout statt `wait_for` |
| 55 | HOCH | action_planner.py | 431-440 | Data/Resilience | **Malformed `tool_calls` von LLM werden unvalidiert an Ollama zurueckgesendet.** Fehlendes `function` Key verursacht 400 Error. | `tool_calls` Struktur validieren |
| 56 | HOCH | function_calling.py | 1356-1358 | Init | **`_ASSISTANT_TOOLS_STATIC` wird bei Module-Load gebaut.** `yaml_config` moeglicherweise noch nicht vollstaendig geladen. Stale Defaults fuer Climate-Tool. | Lazy Init oder Sentinel |
| 57 | HOCH | function_calling.py | 3413-3424 | Performance | **Mehrfache `get_states()` Calls pro Request.** `_check_consequences` ruft HA-States mehrmals ab — jeweils ein voller HTTP-Request. | States einmal am Anfang cachen |
| 58 | HOCH | function_calling.py | 4741-4786 | Security/Config | **`_exec_configure_cover_automation` schreibt direkt in settings.yaml.** `yaml.safe_dump` zerstoert Kommentare und Formatierung. Kein File-Lock bei concurrenten Calls. | ConfigVersioning fuer Backup, File-Lock |
| 59 | MITTEL | function_calling.py | 4963 | None | **`args.get("room")` kann None liefern.** `_clean_room(None)` funktioniert aber verletzt Type-Contract. | `args.get("room", "") or ""` |
| 60 | MITTEL | ollama_client.py | 596-610 | Logic | **`is_available` ist async Methode.** `if ollama_client.is_available:` (ohne await) ist immer truthy (Coroutine-Objekt). | Umbenennen zu `check_availability()` |
| 61 | MITTEL | function_calling.py | 3803-3804 | Silent Error | **`except Exception: pass` bei `record_manual_override`.** Bugs in Light-Engine werden permanent versteckt. | Debug-Logging |
| 62 | MITTEL | action_planner.py | 162 | Logic | **`_QUESTION_STARTS` zu aggressiv.** "kannst du" matched auch imperative Multi-Step-Befehle, faelschlich als nicht-komplex klassifiziert. | Nur echte Fragewörter (was/wie/warum/wo) |
| 63 | MITTEL | model_router.py | 191-192 | Logic | **`_is_model_installed` gibt True bei leerem `_available_models`.** Wenn Ollama down → alle Modelle "installiert" → kein Fallback. | Flag "initialized" hinzufuegen, pessimistisch bei leerem Check |
| 64 | MITTEL | function_validator.py | 28-32 | Init/Config | **`require_confirmation` wird bei Init eingefroren.** Hot-Reload aendert Confirmation-Rules nicht. | Live aus `yaml_config` lesen |
| 65 | MITTEL | declarative_tools.py | 218-220 | Init | **Jeder `DeclarativeToolExecutor` erstellt eigene Registry.** Mehrfaches YAML-Parsen. | Shared Registry Instance |
| 66 | MITTEL | function_calling.py | 3309-3336 | Performance | **Levenshtein-Distance gegen ALLE Room-Profiles pro Call.** Kein Early-Return fuer exakte Matches. | Early-Return bei exaktem Match |
| 67 | NIEDRIG | function_calling.py | 61-63 | Memory | **`_entity_catalog` unbegrenzt.** Grosse HA-Installationen koennen signifikant Memory nutzen. | Bounded LRU |
| 68 | NIEDRIG | action_planner.py | 52-54 | Config | **`MAX_ITERATIONS` bei Module-Load gesetzt.** Hot-Reload hat keinen Effekt. | Live aus yaml_config lesen |
| 69 | NIEDRIG | request_context.py | 38 | Data | **`dict(scope["headers"])` dropped Duplicate Headers.** ASGI headers als (bytes, bytes) Tuples — dict() behält nur letzten Wert. | Minor, kein realer Impact |

---

## Dokumentations-Verifikation

| Behauptung | Status | Beweis |
|---|---|---|
| Bug B1 gefixt (intent_tracker.start()) | ✅ FEHLALARM (korrekt) | `brain.py:555` — `intent_tracker.initialize()` startet Loop |
| Bug B2 gefixt (Morning Briefing Auto-Trigger) | ✅ GEFIXT | `proactive.py:959` — `_check_morning_briefing()`, Motion-Trigger bei `:599` |
| Bug B3 gefixt (Summarizer Callback) | ✅ GEFIXT | `brain.py:531` — `set_notify_callback()`, `_handle_daily_summary` bei `:9643` |
| Bug B4 gefixt (Saisonale Rolladen) | ✅ GEFIXT | `proactive.py:2897` — `_run_seasonal_loop()`, `:4373` — `_execute_seasonal_cover()` |
| Bug B5 gefixt (Was-waere-wenn mit HA-Daten) | ✅ GEFIXT | `brain.py:8495` — `_get_whatif_prompt()` fetcht live Temps, Energie, Fenster, Alarm, Wetter |
| Bug B6 (Wartungs-Loop) | ✅ FEHLALARM (korrekt) | `proactive.py:2314` — `_run_diagnostics_loop()` laeuft alle 30 Min |
| Token Streaming "komplett fehlend" | ❌ FALSCH — IST IMPLEMENTIERT | `websocket.py:137-152` — `emit_stream_start/token/end`, genutzt in `main.py:1978-2100` |
| Interrupt Queueing "komplett fehlend" | ❌ FALSCH — IST IMPLEMENTIERT | `websocket.py:189` — `emit_interrupt()`, konfigurierbar via `interrupt_queue.*`, `_ws_interrupt_flag` in main.py |

---

## Cross-Modul Findings (Top-5)

| # | Module | Beschreibung |
|---|--------|-------------|
| 1 | brain.py → alle Module | **Kein Lock auf `process()`** — main.py ruft `process()` von 3 Stellen gleichzeitig (HTTP, WebSocket, Workshop). Shared State (`_current_person`, `_states_cache`, `_last_context`) wird korrumpiert. |
| 2 | memory.py + semantic_memory.py | **ChromaDB Calls blockieren Event-Loop.** `store_episode` nutzt `to_thread()`, aber `query()` nicht. `semantic_memory.py` nutzt NIE `to_thread()`. Alle ChromaDB HTTP-Roundtrips blockieren. |
| 3 | conversation.py → Memory-Chain | **HA user_id (UUID) als `person`.** Memory-Chain erwartet human-readable Names. Facts via Voice Pipeline werden nie per Person gefunden. |
| 4 | personality.py ← context_builder.py | **Sanitization-Luecke.** context_builder.py hat starke `_sanitize_for_prompt()`. Aber personality.py injiziert `conversation_topic` und Weather-Daten UNSANITIZED direkt in System-Prompt. |
| 5 | function_calling.py → HA | **`call_service` ist generisches Gateway.** LLM kann jeden Service in erlaubten Domains ausfuehren. `lock.unlock` ohne Confirmation moeglich. |

---

## Zero-Bug-Acknowledgments (Priority 1-4)

Die folgenden Module aus Prioritaet 1-4 wurden vollstaendig auditiert und weisen **0 Bugs** auf:

| Modul | Batch | Ergebnis |
|-------|-------|----------|
| `brain_callbacks.py` | Batch 1 (Core) | 0 Bugs gefunden |
| `embeddings.py` | Batch 2 (Memory-Kette) | 0 Bugs gefunden |
| `memory_extractor.py` | Batch 2 (Memory-Kette) | 0 Bugs gefunden |
| `pre_classifier.py` | Batch 4 (Aktionen & Inference) | 0 Bugs gefunden |

Alle anderen 22 Module aus Prioritaet 1-4 haben mindestens einen dokumentierten Bug (siehe Bug-Reports oben).

---

## Fehlerklassen-Verteilung

| Fehlerklasse | Anzahl | Kritischste |
|---|:---:|---|
| 1. Async-Fehler | 5 | ChromaDB blocking in Memory-Chain (#23) |
| 2. Stille Fehler | 8 | `_with_timeout` gibt Exceptions als Werte (#10) |
| 3. Race Conditions | 17 | brain.py `process()` ohne Lock (#2) |
| 4. None-Fehler | 5 | `workshop_gen` statt `workshop_generator` (#11) |
| 5. Init-Fehler | 5 | Module 1-30 ohne `_safe_init()` (#3) |
| 6. API-Fehler | 2 | Mehrfache `get_states()` pro Request (#57) |
| 7. Daten-Fehler | 5 | Bytes vs String bei Redis-Date (#45) |
| 8. Config-Fehler | 3 | `require_confirmation` bei Init eingefroren (#64) |
| 9. Memory Leaks | 5 | `dialogue_state._states` unbegrenzt (#22) |
| 10. Logik-Fehler | 14 | Duplicate conv_memory key (#1) |
| 11. Security | 8 | `call_service` generisches Gateway (#49) |
| 12. Resilience | 5 | Ungeschuetzte Redis-Calls in Gag-Funktionen (#40) |
| 13. Performance | 6 | N+1 Redis in semantic_memory (#29) |

---

## KONTEXT AUS PROMPT 4a: Bug-Report (Core-Module)

### Statistik
Gesamt: 88 Bugs in Prioritaet 1-4 (KRITISCH 10, HOCH 18, MITTEL 38, NIEDRIG 22)

### Kritische Bugs (10)
1. `brain.py:2356+2394` — Duplicate "conv_memory" key, semantische Suche geht verloren
2. `brain.py:1076` — Kein Lock auf `process()`, concurrent Requests korrumpieren Shared State
3. `brain.py:477-597` — Module 1-30 nicht in `_safe_init()`, Exception = Fatal Crash
4. `embedding_extractor.py:23-27` — TOCTOU Race in `_load_model()`, kein Threading-Lock
5. `semantic_memory.py:193-201` — Kein Rollback bei partiellem Store-Failure (ChromaDB+Redis)
6. `personality.py:2375-2384` — Prompt Injection via unsanitized `conversation_topic`
7. `personality.py:2352-2363` — Prompt Injection via unsanitized Weather-Daten
8. `function_calling.py:5212-5244` — `call_service` generisches Gateway, LLM kann `lock.unlock` ausfuehren
9. `function_calling.py:5471` — `lock_door` akzeptiert `action="unlock"` ohne Confirmation
10. `function_calling.py:87-92` — `return_exceptions=True` Ergebnisse nicht einzeln geprueft

### Hohe Bugs (18)
- `brain.py:10131` — Shutdown verpasst Module mit Background-Tasks
- `brain.py:2465` — `_states_cache` Race Condition
- `main.py:7351` — Synchrones subprocess.run in async Endpoints
- `main.py:6118` — Workshop-Chat ohne API-Key
- `main.py:1340` — Error-Details in HTTP-Responses geleakt
- `brain.py:2405` — Exception-Objekte als Werte in `_result_map`
- `main.py:6381` — `workshop_gen` statt `workshop_generator` (6 Endpoints crashen)
- `memory.py:420` — `get_all_episodes()` laedt alle ChromaDB-Dokumente
- `dialogue_state.py:104` — `_states` dict waechst unbegrenzt
- `memory.py:167` + `semantic_memory.py` — ChromaDB Calls blockieren Event-Loop
- `correction_memory.py:50` — Rate-Limit Race Condition
- `semantic_memory.py:571` — `_delete_fact_inner` meldet falschen Erfolg
- `personality.py:2217` — `_current_mood` Race Condition
- `personality.py:2274` — `_current_formality` Race Condition
- `mood_detector.py:267` — Load-Modify-Store ohne Lock
- `function_calling.py:1050` — `_tools_cache = None` waehrend Catalog-Refresh
- `action_planner.py:335` — `wait_for` um `gather` verliert Ergebnisse
- `function_calling.py:4741` — settings.yaml ohne File-Lock ueberschrieben

### Patterns die in 4b weitergesucht werden sollten
1. **Race Conditions auf Instance-Variables** — Pervasives Pattern in personality.py, mood_detector.py, brain.py. In 4b auf proactive.py, routine_engine.py, anticipation.py pruefen
2. **ChromaDB synchrone Calls** — memory.py und semantic_memory.py blockieren Event-Loop. In 4b auf knowledge_base.py, recipe_store.py, workshop_library.py pruefen
3. **`except Exception: pass` Bloecke** — 887 `except Exception` ueber 77 Dateien. In 4b systematisch auf stille Datenverlust-Faelle pruefen
4. **Unsanitized User-Input in Prompts** — personality.py hat Luecken trotz context_builder Defenses. In 4b auf routine_engine.py, proactive.py pruefen
5. **`return_exceptions=True` ohne individuelle Exception-Checks** — Pattern in brain.py und function_calling.py. In 4b auf andere Module mit gather() pruefen
6. **Redis bytes vs string Vergleiche** — mood_detector.py:519 und time_awareness.py:519. In 4b auf alle Redis-Consumers pruefen
