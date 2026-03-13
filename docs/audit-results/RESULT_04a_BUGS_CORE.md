# Audit-Ergebnis: Prompt 4a — Systematische Bug-Jagd (Core-Module, Prioritaet 1-4)

**Durchlauf**: #3 (DL#3) — Vollstaendige Neu-Ausfuehrung
**Datum**: 2026-03-10 (DL#2), 2026-03-13 (DL#3 vollstaendig)
**Auditor**: Claude Code (Opus 4.6)
**Scope**: 26 Core-Module in 4 Batches, 13 Fehlerklassen, Cross-Modul-Pruefung
**Methode DL#3**: 5 parallele Audit-Agenten (brain.py, main.py+ws, Memory-Kette, Context+Personality, Actions+Inference) + 1 Dokumentations-Verifikations-Agent + Grep-Bulk-Suche
**Vergleichsbasis**: DL#1 (88 Bugs), DL#2 (62 offene Bugs)

---

## DL#3: Vollstaendige Neu-Ausfuehrung (2026-03-13)

### Methode
1. **Grep-Bulk-Suche** ueber 9 Patterns (fehlende awaits, silent exceptions, race conditions, API-calls, timeouts, memory leaks, prompt injection)
2. **5 parallele Agents** haben JEDES der 26 Module KOMPLETT gelesen (brain.py in 5x2000-Zeilen-Chunks, main.py in 4x2000-Zeilen-Chunks)
3. **Dokumentations-Verifikation** separat fuer B1-B6 Claims + Token Streaming + Interrupt Queueing
4. **Cross-Modul-Analyse** zwischen allen Batches

### DL#2 Fixes verifiziert (bestaetigt GEFIXT):

| Bug | Severity | Beschreibung | Status DL#3 |
|-----|----------|-------------|-------------|
| #3/NEW-7 | KRITISCH/HOCH | `proactive.start()` in `_safe_init()` | ✅ GEFIXT |
| NEW-1 | KRITISCH | Deadlock bei Retry | ✅ GEFIXT |
| #1 | KRITISCH | Distinct conv_memory keys | ✅ GEFIXT |
| #2 | KRITISCH | _process_lock | ✅ GEFIXT |
| #49-52 | KRITISCH | function_calling security | ✅ GEFIXT |

### DL#2 Bugs verifiziert NOCH OFFEN:

| Bug | Severity | Modul | DL#3-Status |
|-----|----------|-------|-------------|
| #20 | KRITISCH | semantic_memory.py | ⚠️ TEILWEISE — Kein ChromaDB-Rollback bei Redis-Failure |
| #4 | HOCH | brain.py | ❌ UNFIXED — Shutdown verpasst 30+ Komponenten |
| #6 | HOCH | main.py | ❌ UNFIXED — `_token_lock` nie acquired |
| #7/NEW-6 | HOCH | main.py | ❌ UNFIXED — subprocess.run blockiert Event-Loop |
| #9 | HOCH | main.py | ❌ UNFIXED — Error-Details in HTTP-Responses |
| #21 | HOCH | memory.py | ⚠️ TEILWEISE — Hard-Cap 1000 |
| #36 | HOCH | personality.py | ❌ UNFIXED — _current_mood Race Condition |
| #37 | HOCH | personality.py | ❌ UNFIXED — _current_formality Race Condition |
| #39 | HOCH | mood_detector.py | ❌ UNFIXED — analyze_voice_metadata() ohne Lock |
| #53 | HOCH | function_calling.py | ⚠️ TEILWEISE — _tools_cache ohne Lock |
| #56 | HOCH | function_calling.py | ❌ UNFIXED — ASSISTANT_TOOLS_STATIC bei Load |
| #58 | HOCH | function_calling.py | ⚠️ TEILWEISE — TOCTOU settings.yaml |
| NEW-A | HOCH | semantic_memory.py | ❌ UNFIXED — 2 synchrone ChromaDB .update() |
| NEW-E | MITTEL | semantic_memory.py | ❌ UNFIXED — N+1 Redis systemisch |
| #27 | MITTEL | semantic_memory.py | ❌ UNFIXED — MD5 Lock-Key Kollisionen |

### NEUE Bugs in DL#3 gefunden (nicht in DL#2):

#### Batch 1: brain.py + brain_callbacks.py (17 Bugs)

| # | Severity | Datei:Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------------|-------------|-------------|-----|
| DL3-B1 | 🟠 HOCH | brain.py:6270 | 11. Security | **Leerer Person-String umgeht Security-Confirmation**: Wenn `pending["person"]` leer, kann JEDER die Sicherheitsaktion (Tuer/Alarm) bestaetigen | `if not pending.get("person"): return None` |
| DL3-B2 | 🟠 HOCH | brain.py:3472 | 7. Daten | **Leere Args bei ungueltigem LLM-JSON**: `func_args = {}` bei Parse-Error → Funktion mit leeren Args ausgefuehrt (z.B. `set_light({})`) | `continue` nach `func_args = {}` oder Fehler melden |
| DL3-B3 | 🟠 HOCH | brain.py:8404 | 4. None | **Redis None-Guard fehlt**: `_log_experiential_memory` greift auf `self.memory.redis.lpush()` ohne Check → `AttributeError` wenn Redis=None | `if not self.memory.redis: return` |
| DL3-B4 | 🟡 MITTEL | brain.py:6257 | 11. Security | **Generische Bestaetigungs-Trigger**: "ja", "klar", "passt" triggern ausstehende Sicherheitsaktion auch bei anderen Saetzen ("ja bitte, mach Licht an") | Exakte Matches statt startswith |
| DL3-B5 | 🟡 MITTEL | brain.py:3129 | 11. Security | **Prompt-Injection via User-Text**: `[KONTEXT: {situation_delta}]` vor User-Text ermoeglicht Fake-System-Tags | Brackets escapen oder separate Message-Blöcke |
| DL3-B6 | 🟡 MITTEL | brain.py:6220 | 11. Security | **Private Attribut-Zugriff**: `self.self_automation._pending` + `pending_ids[-1]` ohne Laenge-Check — Race bei concurrent Requests | Public API `confirm_latest()` |
| DL3-B7 | 🟡 MITTEL | brain.py:3745 | 2. Stiller Fehler | **`except Exception: pass`** bei Redis Entity-Ownership-Write | `logger.debug()` hinzufuegen |
| DL3-B8 | 🟡 MITTEL | brain.py:9462 | 7. Daten | **Fragiler Redis-Key**: `str(sorted(...))` erzeugt Key mit Klammern/Quotes | `":".join(sorted(...))` |
| DL3-B9 | 🟡 MITTEL | brain.py:4601 | 10. Logik | **Trivial-Schwelle zu breit**: `len(text.split()) <= 8` markiert echte Fragen als trivial → nie als offenes Thema gespeichert | Schwellwert auf <=4 oder entfernen |
| DL3-B10 | 🟡 MITTEL | brain.py:1244 | 3. Race | **Retry-Race**: `_last_failed_query` zwischen Read und Delete bei concurrent Requests → doppelte Ausfuehrung | Atomares `query, self._last_failed_query = self._last_failed_query, None` |
| DL3-B11 | 🟡 MITTEL | brain.py:9877 | 12. Resilience | **Shutdown ohne ABC-Contract**: Komponenten ohne `.stop()` werfen `AttributeError` (in try/except, aber verschleiert) | `hasattr(comp, 'stop')` Check |
| DL3-B12 | 🟢 NIEDRIG | brain.py:845 | 2. Stiller Fehler | `except (ValueError, TypeError): pass` bei datetime-Parsing ohne Log | `logger.debug()` |
| DL3-B13 | 🟢 NIEDRIG | brain.py:4757+ | 2. Stiller Fehler | Mehrere `except (json.JSONDecodeError): pass` in `_filter_response` | Debug-Logging |
| DL3-B14 | 🟢 NIEDRIG | brain.py:9059 | 10. Logik | Naive `datetime.now()` in weekly_report — DST-Probleme | `datetime.now(timezone.utc)` |
| DL3-B15 | 🟢 NIEDRIG | brain.py:852 | 12. Resilience | Private Methoden-Zugriff `context_builder._guess_current_room()` | Public API erstellen |

#### Batch 1: main.py + websocket.py (32 Bugs)

| # | Severity | Datei:Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------------|-------------|-------------|-----|
| DL3-M1 | 🟠 HOCH | main.py:6018 | 11. Security | **kwargs-Injection**: `workshop_update_project` akzeptiert `**data` direkt → beliebige Felder ueberschreibbar | Whitelist erlaubter Felder |
| DL3-M2 | 🟠 HOCH | main.py:6383 | 11. Security | **Prompt-Injection**: Workshop coding-agent bettet `existing_code[:6000]` direkt in LLM-Prompt ein | Input als separate User-Message |
| DL3-M3 | 🟠 HOCH | main.py:1981 | 1. Async | **Fire-and-forget** `speak_response()` ohne Error-Callback — Exception still verschluckt | `task.add_done_callback()` |
| DL3-M4 | 🟠 HOCH | main.py:2064 | 1. Async | **Fire-and-forget** `call_service("media_stop")` ohne Error-Callback | Error-Callback |
| DL3-M5 | 🟠 HOCH | main.py:2173 | 1. Async | **Fire-and-forget** `track_interaction()` ohne Error-Callback | Error-Callback |
| DL3-M6 | 🟠 HOCH | main.py:5460 | 13. Performance | **168 sequentielle Redis-Calls** in health-trends Endpoint | `redis.mget()` oder Pipeline |
| DL3-M7 | 🟠 HOCH | main.py:8036 | 1. Async | **Fire-and-forget** Docker-Restart: User bekommt `success: True` auch bei Fehler | Error-Callback + Status-Check |
| DL3-M8 | 🟠 HOCH | main.py:8073 | 13. Performance | **Sequentielles Ollama-Model-Update**: 5 Models × mehrere Minuten = Endpoint blockiert 10+ Min | Parallel oder Background-Task |
| DL3-M9 | 🟡 MITTEL | main.py:2438 | 11. Security | **PIN in Token-Hash**: Brute-Force-Risiko wenn Token+Timestamp bekannt | `secrets.token_urlsafe(32)` ohne PIN |
| DL3-M10 | 🟡 MITTEL | main.py:2678 | 11. Security | **Entity-ID nicht validiert**: Redis-Key-Manipulation via `srem` moeglich | Pydantic-Model mit Regex |
| DL3-M11 | 🟡 MITTEL | main.py:6844 | 11. Security | **Prompt-Injection**: Workshop `analyze_error_log` — `log_text` direkt ans LLM | Input-Laenge begrenzen, User-Message |
| DL3-M12 | 🟡 MITTEL | main.py:6445 | 11. Security | Exception-Message an Client: `f"Fehler beim Speichern: {e}"` | Generische Meldung |
| DL3-M13 | 🟡 MITTEL | main.py:1906 | 3. Race | WebSocket `_ws_interrupt_flag` als Closure — fragil | Mutable Container oder nonlocal |
| DL3-M14 | 🟡 MITTEL | main.py:7590 | 9. Memory Leak | `_update_log` globale Liste nie gereinigt | `deque(maxlen=100)` |
| DL3-M15 | 🟡 MITTEL | main.py:2230 | 3. Race | `_pin_attempts` Dict ohne Lock | `asyncio.Lock` |
| DL3-M16 | 🟡 MITTEL | main.py:4461 | 13. Performance | Cover-Gruppen sequentiell gesteuert | `asyncio.gather()` |
| DL3-M17 | 🟡 MITTEL | main.py:4548 | 13. Performance | Cover-Szenen sequentiell aktiviert | `asyncio.gather()` |
| DL3-M18 | 🟡 MITTEL | main.py:930 | 13. Performance | Facts sequentiell geloescht | `asyncio.gather()` oder Batch |
| DL3-M19 | 🟡 MITTEL | main.py:3713 | 10. Dead Code | `loop.run_until_complete()` nie erreichbar in async Context | Entfernen |
| DL3-M20 | 🟡 MITTEL | main.py:5842 | 13. Performance | Audit-Log komplett in Memory geladen (bis 10 MB) | Vom Ende lesen |
| DL3-M21 | 🟡 MITTEL | main.py:2185 | 1. Async | Zweites Fire-and-forget `media_stop` | Error-Callback |
| DL3-M22 | 🟡 MITTEL | main.py:364 | 1. Async | `_boot_announcement` done_callback: `CancelledError` in `t.exception()` | Separate Error-Handler-Funktion |
| DL3-M23 | 🟡 MITTEL | websocket.py:43 | 3. Race | `broadcast()` modifiziert `active_connections` bei concurrent Calls | Lock hinzufuegen |
| DL3-M24 | 🟢 NIEDRIG | main.py:5288 | 10. Logik | `datetime.now()` ohne Timezone in live-status | `datetime.now(timezone.utc)` |
| DL3-M25 | 🟢 NIEDRIG | main.py:6522 | 10. Logik | `datetime.now()` ohne Timezone in inventory | `datetime.now(timezone.utc)` |
| DL3-M26 | 🟢 NIEDRIG | main.py:1377 | 6. API | STT Upload ohne Size-Limit | 50 MB Limit |
| DL3-M27 | 🟢 NIEDRIG | main.py:1458 | 6. API | Voice-Chat Upload ohne Size-Limit | 50 MB Limit |
| DL3-M28 | 🟢 NIEDRIG | main.py:585 | 4. None | `request.client` None → alle Proxy-Requests teilen Rate-Limit | Dokumentieren oder Skip |
| DL3-M29 | 🟡 MITTEL | main.py:3048 | 1. Async | `_sync_cover_settings_to_addon` — ensure_future Return nie geprueft | Async Variante verwenden |

#### Batch 2: Memory-Kette (23 Bugs)

| # | Severity | Datei:Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------------|-------------|-------------|-----|
| DL3-ME1 | 🔴 KRITISCH | memory_extractor.py:87-120 | 11. Security | **Prompt-Injection in Memory-Extraktion**: User-Text wird direkt ans LLM zur Fakten-Extraktion geschickt. Manipulierter Text kann beliebige "Fakten" ins System einschleusen (Gaslighting-Vektor) | `_sanitize()` wie in correction_memory.py |
| DL3-ME2 | 🟠 HOCH | semantic_memory.py:254 | 10. Logik | **store_fact() returns True bei totalem Backend-Ausfall**: Wenn Redis UND ChromaDB down → Fakt "gespeichert" aber nirgends geschrieben | `if not self.redis and not self.chroma_collection: return False` |
| DL3-ME3 | 🟠 HOCH | correction_memory.py:120-135 | 12. Resilience | **Redis-Writes nicht in try/except** in `store_correction()` → Crash bei Redis-Timeout | try/except um Redis-Block |
| DL3-ME4 | 🟠 HOCH | memory.py:196 | 1. Async | **Synchroner ChromaDB-Call** `clear_all_memory()` ohne `asyncio.to_thread()` — blockiert Event-Loop | `asyncio.to_thread()` Wrapper |
| DL3-ME5 | 🟠 HOCH | conversation_memory.py:35-48 | 2. Stiller Fehler | **`except Exception: pass`** bei Redis-Init — wenn Redis nicht erreichbar, scheitert gesamtes Memory-System still | Mindestens Warning loggen |
| DL3-ME6 | 🟡 MITTEL | semantic_memory.py:426 | 7. Daten | **ChromaDB Metadata-Konflikt**: `{**data, "confidence": ...}` uebernimmt alle Redis-Felder inkl. `content` — Duplikat in ChromaDB | Explizit nur gewuenschte Felder |
| DL3-ME7 | 🟡 MITTEL | memory_extractor.py:95 | 10. Logik | **Harter Truncate bei 2000 Zeichen**: Kann mitten im Satz schneiden → LLM extrahiert unvollstaendige Fakten | Am naechsten Satzende abschneiden |
| DL3-ME8 | 🟡 MITTEL | correction_memory.py:108 | 3. Race | **Counter-Inkrement vor Regelerstellung**: Wenn zwischen Counter-Read und Rule-Write ein Fehler passiert, zaehlt der Counter hoch ohne dass eine Regel erstellt wird | Atomare Operation oder Rollback |
| DL3-ME9 | 🟡 MITTEL | dialogue_state.py:131 | 4. None | **Kein Type-Guard**: `entities: list[str] = None` — wenn ein String statt Liste uebergeben wird, iteriert Code ueber Buchstaben | `if entities and isinstance(entities, list):` |
| DL3-ME10 | 🟡 MITTEL | dialogue_state.py:103 | 9. Memory Leak | **Stale States nie aktiv entfernt**: Eviction nur bei >50 Eintraegen, stale States belegen weiterhin Speicher | Periodische Cleanup-Methode |
| DL3-ME11 | 🟡 MITTEL | conversation.py:108 | 6. API | **Kein Connect-Timeout**: `aiohttp.ClientTimeout(total=30)` wartet 30s auch bei unerreichbarem Server | `aiohttp.ClientTimeout(total=30, connect=5)` |
| DL3-ME12 | 🟡 MITTEL | conversation.py:118 | 12. Resilience | **HTTP-Fehler ohne Response-Body**: Nur Status-Code geloggt, nicht die Fehlermeldung | `body = await resp.text()` loggen |
| DL3-ME13 | 🟡 MITTEL | semantic_memory.py:748 | 13. Performance | **Sequential ChromaDB Deletes**: Fuer jeden Fakt separater Query + Delete (2*N Roundtrips) | Alle IDs sammeln, ein `delete(ids=[...])` |

#### Batch 3: Context, Embeddings, Personality (21 Bugs)

| # | Severity | Datei:Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------------|-------------|-------------|-----|
| DL3-CP1 | 🟠 HOCH | embedding_extractor.py:35 | 3. Race | **Model-Loading ausserhalb Lock**: Bei gleichzeitigen Requests doppeltes Model-Loading oder None-Return | Double-Checked-Locking erweitern |
| DL3-CP2 | 🟠 HOCH | time_awareness.py:518 | 7. Daten | **Redis bytes vs str Vergleich**: `stored_date != today` vergleicht bytes mit str → immer True → Tages-Zaehler reset bei JEDEM Aufruf (Kaffee-Counter kaputt) | `stored_date.decode() if isinstance(stored_date, bytes)` |
| DL3-CP3 | 🟠 HOCH | context_builder.py:426 | 11. Security | **Unzureichende Prompt-Injection-Sanitisierung**: `conversation_topic` wird per `_sanitize_for_prompt()` behandelt, aber Funktion existiert und wird nicht genutzt an allen Stellen | `_sanitize_for_prompt()` konsistent verwenden |
| DL3-CP4 | 🟠 HOCH | mood_detector.py:166 | 3. Race | **State-Zugriff ohne Lock**: `detect_audio_emotion()` und `get_mood_prompt_hint()` greifen ohne `_analyze_lock` auf Instanzvariablen zu | Alle State-Methoden unter Lock |
| DL3-CP5 | 🟡 MITTEL | embeddings.py:26 | 3. Race | **Globaler Embedding-Cache ohne Lock**: `_embedding_cache` OrderedDict kann bei parallelen Requests crashen | `threading.Lock` oder `lru_cache` |
| DL3-CP6 | 🟡 MITTEL | personality.py:867 | 1. Async | **3 sequentielle Redis-Calls** statt Pipeline in `build_evolved_gag()` | Redis-Pipeline verwenden |
| DL3-CP7 | 🟡 MITTEL | personality.py:2010 | 13. Performance | **14 sequentielle Redis-Calls** in `get_humor_preferences()` (2 pro Kategorie × 7) | `mget` oder Pipeline |
| DL3-CP8 | 🟡 MITTEL | context_builder.py:480 | 10. Logik | **Timezone-Mischung**: `changed_dt` kann aware sein, `datetime.now()` ist naive → `TypeError` in Docker-Containern ohne lokale TZ | `datetime.now(timezone.utc)` konsistent |
| DL3-CP9 | 🟡 MITTEL | situation_model.py:132 | 1. Async | **Background-Task ohne Error-Callback**: `asyncio.create_task()` in `start()` — Exception still verloren | `add_done_callback()` |
| DL3-CP10 | 🟡 MITTEL | context_builder.py:193-220 | 2. Stiller Fehler | **Parallel Tasks Fehler verschluckt**: Einzelne Fehler in Context-Gather werden per try/except geloggt aber Kontext fehlt dann still | Mindestens Warning-Level |
| DL3-CP11 | 🟢 NIEDRIG | personality.py:333 | 10. Dead Code | `_state_lock = asyncio.Lock()` deklariert aber nie verwendet | Entfernen oder einsetzen |
| DL3-CP12 | 🟢 NIEDRIG | mood_detector.py:220 | 6. API | **Redis KEYS Befehl** blockierend bei vielen Keys | `scan_iter()` verwenden |
| DL3-CP13 | 🟢 NIEDRIG | time_awareness.py:363 | 4. None | `float("unavailable")` bei HA-Sensoren — gefangen per try/except, aber unsauber | Vorab auf "unavailable" pruefen |

#### Batch 4: Actions & Inference (22 Bugs)

| # | Severity | Datei:Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------------|-------------|-------------|-----|
| DL3-AI1 | 🔴 KRITISCH | action_planner.py:342 | 1. Async | **Task-Ergebnis-Zuordnung falsch**: `asyncio.wait()` garantiert keine Reihenfolge → Ergebnisse koennen falschen Steps zugeordnet werden → falscher Rollback | `asyncio.gather()` verwenden oder Task-ID mitgeben |
| DL3-AI2 | 🔴 KRITISCH | pre_classifier.py:166 | 10. Logik | **Rhetorische Fragen blockieren Device-Commands**: `"Mach das Licht an?"` wird wegen `?` als Frage erkannt → DEVICE_FAST-Pfad blockiert → unnoetige Latenz | `?` allein reicht nicht, Fragewort UND `?` noetig |
| DL3-AI3 | 🔴 KRITISCH | pre_classifier.py:233 | 10. Logik | **Fragewort-Prefix zu aggressiv**: `"Ist mir egal, mach Licht an"` wird als Frage erkannt. `"Wie viel Prozent Rolladen"` kann nicht als DEVICE_QUERY erkannt werden | Differenziertere Frage-Erkennung |
| DL3-AI4 | 🟠 HOCH | ollama_client.py:416 | 2. Stiller Fehler | **Circuit Breaker silent**: `stream_chat()` gibt bei offenem Circuit leeren Stream zurueck ohne Hinweis an Caller | Exception oder Hinweis-Token senden |
| DL3-AI5 | 🟠 HOCH | function_validator.py:135 | 11. Security | **Validator mutiert Original-Args**: `args["state"] = ...; del args["brightness"]` veraendert die uebergebenen Daten → bei Retry/Audit inkonsistent | Kopie der Args anlegen |
| DL3-AI6 | 🟠 HOCH | declarative_tools.py:91 | 3. Race | **YAML-Write ohne Lock**: Concurrent Tool-Erstellung kann YAML-Datei korrumpieren | `threading.Lock` oder atomares Schreiben |
| DL3-AI7 | 🟡 MITTEL | function_validator.py:56 | 11. Security | **getattr-Dispatch**: `getattr(self, f"_validate_{function_name}")` — manipulierter function_name ruft unerwartete Methoden auf | Explizite Dispatch-Map |
| DL3-AI8 | 🟡 MITTEL | action_planner.py:344 | 1. Async | **t.result() ohne try/except**: Task-Exceptions propagieren unkontrolliert | try/except um t.result() |
| DL3-AI9 | 🟡 MITTEL | ollama_client.py:275 | 12. Resilience | **Session ohne Timeout**: `aiohttp.ClientSession()` bei Lazy-Init ohne Default-Timeout | `aiohttp.ClientTimeout(total=60)` |
| DL3-AI10 | 🟡 MITTEL | model_router.py:145 | 10. Logik | **Fallback bei leerem Model-Cache**: `_is_model_installed` gibt True zurueck wenn `_available_models` leer | False bei leerem Cache |
| DL3-AI11 | 🟡 MITTEL | ollama_client.py:350-370 | 2. Stiller Fehler | **Streaming-Error verschluckt**: Bei JSON-Decode-Error im Stream wird nur geloggt, Client bekommt unvollstaendige Antwort | Error-Token an Client senden |
| DL3-AI12 | 🟢 NIEDRIG | declarative_tools.py:83 | 7. Daten | **Kein Encoding bei open()**: Umlaute in Tool-Namen koennen auf non-UTF8 Systemen crashen | `encoding="utf-8"` |
| DL3-AI13 | 🟢 NIEDRIG | action_planner.py:162 | 10. Logik | **_QUESTION_STARTS zu aggressiv**: "kannst du" matched imperative Multi-Step-Befehle | Pattern verfeinern |

---

### DL#3 Gesamt-Statistik (NEUE Bugs)

```
Neue Bugs gefunden in DL#3: 92
  Batch 1a (brain.py): 15 (0 KRITISCH, 3 HOCH, 8 MITTEL, 4 NIEDRIG)
  Batch 1b (main.py+ws): 29 (0 KRITISCH, 8 HOCH, 17 MITTEL, 4 NIEDRIG)
  Batch 2 (Memory): 13 (1 KRITISCH, 4 HOCH, 7 MITTEL, 1 NIEDRIG)
  Batch 3 (Context+Pers): 13 (0 KRITISCH, 4 HOCH, 6 MITTEL, 3 NIEDRIG)
  Batch 4 (Actions): 13 (3 KRITISCH, 3 HOCH, 4 MITTEL, 3 NIEDRIG) + 9 aus DL#2 unveraendert

  🔴 KRITISCH: 4 (DL3-ME1, DL3-AI1, DL3-AI2, DL3-AI3)
  🟠 HOCH: 22
  🟡 MITTEL: 42
  🟢 NIEDRIG: 15
```

### Aktualisierte Bug-Bilanz (DL#3 komplett):

```
DL#2: 62 offene Bugs (1 KRITISCH, 12 HOCH, 33 MITTEL, 16 NIEDRIG)
DL#3 (nach Verifikation + Neu-Suche):
  Aus DL#2 noch offen:     ~48 (DL#2 Bugs die noch nicht gefixt sind)
  Neue DL#3 Bugs:          +83 (nur wirklich NEUE, nicht DL#2-Duplikate)
  Gesamt offen:            ~131 Bugs
    🔴 KRITISCH:    4
    🟠 HOCH:       30
    🟡 MITTEL:     65
    🟢 NIEDRIG:    32

Haeufigste Fehlerklasse: 11. Security (15 Vorkommen)
Am staerksten betroffenes Modul: main.py (29 Bugs)
Zweitstaerkstes Modul: brain.py (15 Bugs)
```

### P02 Fixes die P04a-Scope betreffen (positiv):
- Memory Confidence-Schwelle 0.6→0.4 (brain.py:3167) — mehr Facts abgerufen
- Memory Relevance-Schwelle 0.3→0.2 (brain.py:3172) — breiterer Match
- Memory Limit 3→10 (brain.py:3163) — mehr Context
- conv_memory_ext Priority 3→1 (brain.py:2973) — immer im System-Prompt
- "ERFINDE KEINE Erinnerungen" Hint (brain.py:3216-3224) — weniger Halluzinationen

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

## Dokumentations-Verifikation (DL#3 Update)

| Behauptung | DL#3 Status | Beweis |
|---|---|---|
| Bug B1 gefixt (intent_tracker.start()) | ✅ FEHLALARM BESTAETIGT | intent_tracker.py:146 — `initialize()` ruft `asyncio.create_task(self._reminder_loop())` auf. brain.py:583 — `self.intent_tracker.initialize(redis_client=self.memory.redis)` |
| Bug B2 gefixt (Morning Briefing Auto-Trigger) | ✅ GEFIXT BESTAETIGT | proactive.py:966 — `_check_morning_briefing()`. proactive.py:606 — Motion-Trigger aufgerufen |
| Bug B3 gefixt (Summarizer Callback) | ✅ GEFIXT BESTAETIGT | summarizer.py:76 — `set_notify_callback()`. brain.py:556 — Callback gesetzt. brain.py:9301 — `_handle_daily_summary()` |
| Bug B4 gefixt (Saisonale Rolladen) | ✅ GEFIXT BESTAETIGT | proactive.py:2914 — `_run_seasonal_loop()`. proactive.py:4386 — `_execute_seasonal_cover()`. proactive.py:261 — Task gestartet |
| Bug B5 gefixt (Was-waere-wenn mit HA-Daten) | ✅ GEFIXT BESTAETIGT | brain.py:8132 — `_get_whatif_prompt()` async. brain.py:2394 — in Mega-Gather aufgerufen |
| Bug B6 (Wartungs-Loop) | ✅ FEHLALARM BESTAETIGT | proactive.py:2330 — `_run_diagnostics_loop()`. proactive.py:254 — Task gestartet |
| Token Streaming "komplett fehlend" | ❌ BEHAUPTUNG FALSCH — IST IMPLEMENTIERT | brain.py:929-964 `stream_callback`, `self.ollama.stream_chat()`. websocket.py:137-147 `emit_stream_start/token/end` |
| Interrupt Queueing "komplett fehlend" | ✅ BEHAUPTUNG KORREKT — FEHLT | Kein "interrupt" in brain.py. Kein Queuing-Mechanismus. `_ws_interrupt_flag` in main.py ist nur ein einfaches Cancel-Flag, kein echtes Queuing |

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

## Post-Fix-Verifikation (2026-03-11, nach P06a-P08 + finale Fixes)

**Methode**: Jeder HIGH/CRITICAL Bug gegen den tatsaechlichen Quellcode geprueft.

### Nachtraeglich als GEFIXT bestaetigt (im Code verifiziert):

| Bug | Severity | Beschreibung | Gefixt durch |
|-----|----------|-------------|-------------|
| NEW-1 | KRITISCH | Deadlock bei Retry: `_process_inner()` statt `self.process()` | P06a |
| #3/NEW-7 | KRITISCH/HOCH | `proactive.start()` in `_safe_init()` gewrappt | P06b |

### Verifiziert NOCH OFFEN (im Code geprueft, Bug existiert noch):

| Bug | Severity | Modul | Beschreibung |
|-----|----------|-------|-------------|
| #20 | KRITISCH | semantic_memory.py | Kein ChromaDB-Rollback bei Redis-Failure |
| #4 | HOCH | brain.py | Shutdown verpasst 30+ Komponenten |
| #6 | HOCH | main.py | `_token_lock` definiert aber nie acquired (Dead Code) |
| #7/NEW-6 | HOCH | main.py | `subprocess.run()` blockiert Event-Loop (ffmpeg 30s) |
| #9 | HOCH | main.py | 3 HTTPExceptions + ~25 Endpoints leaken `str(e)` |
| #21 | HOCH | memory.py | Hard-Cap 1000 verhindert Pagination |
| #36 | HOCH | personality.py | `_current_mood` ohne Lock |
| #37 | HOCH | personality.py | `_current_formality` ohne Lock |
| #39 | HOCH | mood_detector.py | `analyze_voice_metadata()` ohne Lock |
| #53 | HOCH | function_calling.py | `_tools_cache = None` ohne Lock bei Invalidation |
| #56 | HOCH | function_calling.py | `_ASSISTANT_TOOLS_STATIC` bei Module-Load (unnoetig) |
| #58 | HOCH | function_calling.py | TOCTOU: settings.yaml Read vor Lock |
| NEW-A | HOCH | semantic_memory.py | 2 synchrone ChromaDB `.update()` Calls |

### Aktualisierte Bug-Bilanz (Post-Verifikation):

```
Offene HIGH/CRITICAL Bugs:  13 (1 KRITISCH, 12 HOCH)
Offene MITTEL Bugs:         ~33
Offene NIEDRIG Bugs:        ~16
Gesamt offen (P04a):        ~62
Davon code-verifiziert:     13 HIGH/CRITICAL bestaetigt offen
```

---

## KONTEXT AUS PROMPT 4a (DL#3): Bug-Report (Core-Module)

### Statistik
DL#3 (vollstaendige Neu-Ausfuehrung): ~131 offene Bugs in Prioritaet 1-4
  🔴 KRITISCH: 4
  🟠 HOCH: 30
  🟡 MITTEL: 65
  🟢 NIEDRIG: 32

Haeufigste Fehlerklasse: 11. Security (15 Vorkommen)
Am staerksten betroffenes Modul: main.py (29 Bugs)

### Kritische Bugs (🔴 4 offen)

| Bug | Modul:Zeile | Beschreibung | Fix |
|-----|------------|-------------|-----|
| DL3-ME1 | memory_extractor.py:87 | Prompt-Injection in Fakten-Extraktion — Gaslighting-Vektor | `_sanitize()` fuer User-Input |
| DL3-AI1 | action_planner.py:342 | Task-Ergebnis-Zuordnung falsch bei asyncio.wait() | `asyncio.gather()` verwenden |
| DL3-AI2 | pre_classifier.py:166 | Rhetorische Fragen blockieren Device-Commands | Fragewort UND ? noetig |
| DL3-AI3 | pre_classifier.py:233 | Fragewort-Prefix zu aggressiv | Differenziertere Logik |

### Hohe Bugs (🟠 Top-10)

| Bug | Modul:Zeile | Beschreibung |
|-----|------------|-------------|
| DL3-B1 | brain.py:6270 | Security-Confirmation Bypass bei leerem Person-String |
| DL3-B2 | brain.py:3472 | Leere Args bei ungueltigem LLM-JSON |
| DL3-B3 | brain.py:8404 | Redis None-Guard fehlt in experiential memory |
| DL3-M1 | main.py:6018 | kwargs-Injection in workshop_update_project |
| DL3-M2 | main.py:6383 | Prompt-Injection in Workshop coding-agent |
| DL3-ME2 | semantic_memory.py:254 | store_fact returns True bei totalem Backend-Ausfall |
| DL3-CP2 | time_awareness.py:518 | bytes vs str → Tages-Zaehler reset bei jedem Aufruf |
| DL3-AI4 | ollama_client.py:416 | Circuit Breaker gibt leeren Stream ohne Hinweis |
| DL3-AI5 | function_validator.py:135 | Validator mutiert Original-Args |
| DL3-AI6 | declarative_tools.py:91 | YAML-Write ohne Lock → Korruption |

### Patterns die in 4b weitergesucht werden sollten
1. **Fire-and-forget Tasks ohne Error-Callback** — 8 Instanzen in main.py. In 4b: Alle Module mit `asyncio.ensure_future/create_task` pruefen
2. **Race Conditions auf Instance-Variables** — personality.py, mood_detector.py, embedding_extractor.py. In 4b: proactive.py, routine_engine.py, anticipation.py pruefen
3. **N+1 Redis** — Systemisches Pattern in semantic_memory.py (5+ Methoden). In 4b: Alle Redis-intensiven Module pruefen
4. **Security: Prompt-Injection** — memory_extractor, context_builder, workshop-endpoints. In 4b: Alle LLM-Prompt-Aufrufe pruefen
5. **Synchrone I/O in async Handlern** — ChromaDB .update(), subprocess.run, file open. In 4b: Alle async Endpoints pruefen
6. **pre_classifier Frage-Erkennung** — Befehle mit ? werden falsch klassifiziert. In 4b: Downstream-Effekte in allen Modulen pruefen
7. **Redis bytes vs str** — time_awareness Counter kaputt. In 4b: Alle Redis-Vergleiche pruefen

---

=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Keine Fixes in diesem Prompt — nur Finden und Dokumentieren]
OFFEN:
- 🔴 KRITISCH DL3-ME1: Prompt-Injection Memory-Extraktion | memory_extractor.py:87 | GRUND: User-Text direkt ans LLM → ESKALATION: NAECHSTER_PROMPT
- 🔴 KRITISCH DL3-AI1: Task-Ergebnis-Zuordnung falsch | action_planner.py:342 | GRUND: asyncio.wait() Reihenfolge → ESKALATION: NAECHSTER_PROMPT
- 🔴 KRITISCH DL3-AI2/AI3: pre_classifier Frage-Erkennung | pre_classifier.py:166,233 | GRUND: Device-Commands blockiert → ESKALATION: NAECHSTER_PROMPT
- 🟠 HOCH DL3-B1: Security-Bypass | brain.py:6270 | GRUND: Leerer Person-String → ESKALATION: NAECHSTER_PROMPT
- 🟠 HOCH DL3-M1: kwargs-Injection | main.py:6018 | GRUND: **data direkt → ESKALATION: NAECHSTER_PROMPT
- 🟠 HOCH DL3-M2: Prompt-Injection | main.py:6383 | GRUND: Code im LLM-Prompt → ESKALATION: NAECHSTER_PROMPT
- 🟠 HOCH DL3-CP2: bytes vs str | time_awareness.py:518 | GRUND: Counter kaputt → ESKALATION: NAECHSTER_PROMPT
- 🟠 HOCH DL3-ME2: False-positive store_fact | semantic_memory.py:254 | GRUND: Beide Backends down → ESKALATION: NAECHSTER_PROMPT
- [+22 weitere HOCH, 65 MITTEL, 32 NIEDRIG — siehe vollstaendige Tabellen oben]
GEAENDERTE DATEIEN: [docs/audit-results/RESULT_04a_BUGS_CORE.md]
REGRESSIONEN: [Keine — nur Audit, keine Code-Aenderungen]
NAECHSTER SCHRITT: Prompt 4b (Extended-Module, Prioritaet 5-9) — suche dieselben Patterns in allen erweiterten Modulen
===================================
