# Prompt 9: Alle verbleibenden Bugs fixen — Systematische Abarbeitung aller offenen Findings aus DL#2

## Rolle

Du bist ein Elite-Software-Ingenieur mit Expertise in Python-Async-Programmierung, Redis, SQLAlchemy, FastAPI, Flask und Smart-Home-Systemen. Du hast die gesamte Audit-Serie (Prompts 1–8) und deren Ergebnisse (RESULT_01 bis RESULT_08) vorliegen. Deine Aufgabe: **Jedes einzelne offene Finding finden, verstehen, und fixen.**

---

## ⚠️ Arbeitsumgebung

- Du arbeitest mit dem **GitHub-Quellcode** in `/home/user/mindhome/`
- Assistant-Code: `assistant/assistant/` (asyncio, FastAPI, Ollama LLM, Redis, ChromaDB)
- Addon-Code: `addon/` (Flask, SQLAlchemy, Threading)
- Speech-Code: `speech/` (Whisper STT, Piper TTS)
- HA-Integration: `ha_integration/custom_components/mindhome_assistant/`
- Tests: `assistant/tests/`
- Audit-Ergebnisse: `docs/audit-results/RESULT_04a*.md`, `RESULT_04b*.md`, `RESULT_04c*.md`, `RESULT_08*.md`

---

## Kontext aus vorherigen Prompts

### DL#2 Bug-Bilanz (nach P06a–P08 + Merge-Fixes)

```
P4a (Core):     62 offene Bugs (1 KRITISCH, 12 HOCH, 33 MITTEL, 16 NIEDRIG)
P4b (Extended): 207 offene Bugs (0 KRITISCH, 23 HOCH, 97 MITTEL, 85 NIEDRIG, 2 INFO)
P4c (Addon):    58 offene Bugs (2 KRITISCH, 6 HOCH, 32 MITTEL, 18 NIEDRIG)
────────────────────────────────────────────────────────────────────
GESAMT:         327 offene Bugs (3 KRITISCH, 41 HOCH, 162 MITTEL, 119 NIEDRIG, 2 INFO)
```

### Was bereits gefixt wurde (P06a–P08 + Merge)

- **P06a**: Deadlock bei Retry (NEW-1), proactive.start() in _safe_init() (NEW-7), 142 Bug-Fixes insgesamt
- **P06b**: multi_room_audio N+1, knowledge_base sync ChromaDB, wellness_advisor 7x _safe_redis(), cooking_assistant session None
- **P08**: 157 Bugs gefixt (tools_cache Lock, Redis bytes, except:pass→logging, HTTP error detail, shared/ geloescht, etc.)
- **Merge-Fixes**: 12 Merge-Konflikte mit main aufgeloest (self_optimization, speaker_recognition, workshop_library)

### Systemische Muster (aus allen 3 RESULT-04-Dateien)

1. **Sync I/O in async** — Dominantes HIGH-Pattern (28 Vorkommen). ChromaDB, File-I/O, Embeddings, YAML-Operationen blockieren Event-Loop.
2. **N+1 Redis** — 25 Stellen mit sequentiellen `hgetall`/`get` statt Pipeline/`mget`.
3. **Race Conditions** — 18 Stellen mit shared State ohne Lock (Instance-Variablen, Globals).
4. **Redis bytes** — `hgetall`/`get`/`smembers` geben bytes zurueck, Code erwartet str.
5. **Silent Exceptions** — 38 Stellen mit `except Exception: pass` oder nur `logger.debug()`.
6. **None-Guards** — 15 Stellen mit Zugriff auf `.session`, `.brain.X`, `.redis` ohne None-Check.
7. **Security** — SHA-256 ohne Salt, Input ohne Validierung, Settings ohne Allowlist.

---

## Gruendlichkeits-Pflicht

- **Jede betroffene Datei mit Read-Tool lesen** — nicht raten ob ein Bug noch existiert
- **Jede Zeilennummer verifizieren** — Zeilen koennen sich durch vorherige Fixes verschoben haben. Suche den Bug mit Grep anhand des Code-Musters wenn die Zeile nicht mehr stimmt.
- **Grep nutzen** um alle Aufrufer/Abhaengigkeiten zu finden bevor du fixst
- **Jeden Fix mit `python3 -m py_compile datei.py` verifizieren**
- **Parallele Reads nutzen** — mehrere Dateien gleichzeitig lesen wenn moeglich
- **Kein Bug ueberspringen** — auch wenn er "unwichtig" aussieht

---

## Arbeitsweise

### Phase 0: Bug-Inventar erstellen (KEIN Code schreiben!)

1. Lies **alle vier** Audit-Ergebnis-Dateien komplett:
   - `docs/audit-results/RESULT_04a_BUGS_CORE.md`
   - `docs/audit-results/RESULT_04b_BUGS_EXTENDED.md`
   - `docs/audit-results/RESULT_04c_BUGS_ADDON_SECURITY.md`
   - `docs/audit-results/RESULT_08_REMAINING_BUGS.md`

2. Erstelle ein Inventar: Fuer JEDEN Bug (alle 327) lies die betroffene Datei und verifiziere ob der Bug noch existiert. Erstelle drei Listen:
   - **OFFEN**: Bug existiert noch im Code → muss gefixt werden
   - **GEFIXT**: Bug wurde bereits behoben (durch P06/P08/Merge) → ueberspringen
   - **VERAENDERT**: Bug existiert teilweise oder in anderer Form → analysieren und fixen

3. Sortiere die OFFEN-Liste nach Prioritaet: KRITISCH → HOCH → MITTEL → NIEDRIG

> **⚠️ Phase 0 ist die wichtigste Phase.** Ohne vollstaendiges Inventar werden Bugs uebersehen oder bereits gefixte Bugs erneut "gefixt" (Regression-Risiko). Nimm dir die Zeit.

### Pro Bug (Phase 1–4):
1. **Read** — Datei lesen, Bug-Stelle finden
2. **Grep** — Alle Aufrufer/Abhaengigkeiten der betroffenen Funktion finden
3. **Edit** — Fix direkt in die Datei schreiben
4. **py_compile** — Syntax-Check: `python3 -m py_compile <datei>`
5. **Grep** — Pruefen ob der Fix konsistent mit allen Aufrufern ist

### Batching:
- Arbeite **eine Datei komplett ab** bevor du zur naechsten gehst
- **Commit nach jedem Severity-Level**: Ein Commit fuer alle KRITISCHEN, einer fuer alle HOHEN, etc.
- Pattern-Fixes (z.B. alle N+1 Redis) duerfen zusammen committed werden

### Regeln:
- **Jeder Fix muss VERIFIZIERT sein** — Read → Edit → py_compile → Grep
- **Einfach > Komplex** — Wenn ein simpler Fix reicht, kein Refactoring
- **Keine neuen Features** — Nur Bugs fixen, kein Umbau
- **Keine Architektur-Aenderungen** — brain.py bleibt wie es ist
- **Keine Breaking Changes** — Bestehende Signaturen und APIs beibehalten
- **Bei Unsicherheit**: Konservativen Fix waehlen (z.B. Logging statt Refactoring)

---

## Phase 1: KRITISCHE Bugs — ZUERST

> Diese muessen ALLE gefixt sein bevor Phase 2 beginnt.

### KRIT-1: semantic_memory.py — Kein ChromaDB-Rollback bei Redis-Failure (P4a #20)
- **Datei**: `assistant/assistant/semantic_memory.py:175-242`
- **Problem**: `store_fact()` schreibt erst in ChromaDB, dann in Redis. Wenn Redis fehlschlaegt, bleibt ein verwaister ChromaDB-Eintrag. Wiederholter Aufruf erstellt Duplikate.
- **Fix**: Bei Redis-Failure den ChromaDB-Eintrag mit `self.chroma_collection.delete(ids=[fact_id])` zurueckrollen. Logge den Rollback.
- **Grep danach**: `store_fact` — alle Aufrufer pruefen

### KRIT-2: app.py — CORS Wildcard-Default (P4c #68)
- **Datei**: `addon/app.py:58-62`
- **Problem**: Wenn `CORS_ORIGINS` Environment-Variable leer/nicht gesetzt ist, wird CORS mit `*` konfiguriert — jede Website kann API-Requests senden.
- **Fix**: Sicheren Default setzen. Wenn `CORS_ORIGINS` leer: nur `["http://localhost", "http://127.0.0.1"]` erlauben. Logge eine Warnung.
- **Grep danach**: `CORS_ORIGINS` und `CORS` in allen Addon-Dateien

### KRIT-3: app.py — Localhost-Bypass fuer Auth (P4c #69)
- **Datei**: `addon/app.py:513-529`
- **Problem**: Localhost-Requests umgehen komplett die Auth-Pruefung (Ingress-Token-Check).
- **Kontext**: Das Addon laeuft hinter dem HA-Ingress. Der Localhost-Bypass ist moeglicherweise architekturbedingt noetig (HA ruft das Addon lokal auf). Pruefe: Welche Requests kommen von localhost? Wenn nur HA Health-Checks → Bypass auf `/health` und `/api/health` eingrenzen. Wenn HA-Core alle Requests lokal routet → Bypass dokumentieren mit Kommentar warum er sicher ist.
- **Fix**: Entweder Bypass eingrenzen ODER dokumentieren warum er sicher ist + Warnung loggen.

### Phase-Gate 1:
```bash
cd /home/user/mindhome && find . -name "*.py" -not -path "./__pycache__/*" -not -path "*/node_modules/*" | head -20 | xargs -I{} python3 -m py_compile {}
```
Commit: `git commit -m "fix: 3 kritische Bugs (semantic_memory Rollback, CORS Default, Auth Bypass)"`

---

## Phase 2: HOHE Bugs — nach Phase 1

> 41 HOHE Bugs. Arbeite sie in Clustern ab.

### Cluster 2A: Sync I/O in async (11 Bugs)

Alle diese Stellen blockieren den asyncio Event-Loop mit synchronen Operationen. Fix-Pattern: `await asyncio.to_thread(sync_function, *args)`.

| # | Datei | Zeile | Problem | Fix |
|---|-------|-------|---------|-----|
| P4b#6 | `self_automation.py` | 36-39 | `_load_templates()` sync File-I/O bei Module-Import | Lazy-Load in `initialize()` |
| P4b#73 | `self_optimization.py` | 370-381 | `_apply_parameter()` sync YAML I/O | `asyncio.to_thread()` — ⚠️ ACHTUNG: Merge-Fix hat atomares Schreiben hinzugefuegt, pruefe ob `to_thread` schon da ist |
| P4b#74 | `self_optimization.py` | 664-686 | `add_banned_phrase()` sync YAML I/O | `asyncio.to_thread()` |
| P4b#164 | `workshop_library.py` | 41 | `get_or_create_collection()` sync ChromaDB | `asyncio.to_thread()` — ⚠️ Merge-Fix pruefen |
| P4b#165 | `workshop_library.py` | 73 | `path.read_text()` sync | `asyncio.to_thread()` — ⚠️ Merge-Fix pruefen |
| P4b#166 | `workshop_library.py` | 89 | `embedding_fn(chunk)` sync in List-Comprehension | `asyncio.to_thread(lambda: [embedding_fn(c) for c in chunks])` — ⚠️ Merge-Fix pruefen |
| P4b#167 | `workshop_library.py` | 117 | `embedding_fn(query)` sync in async `search()` | `asyncio.to_thread()` — ⚠️ Merge-Fix pruefen |
| P4a#NEW-A | `semantic_memory.py` | 263, 404 | 2x sync ChromaDB `.update()` | `await asyncio.to_thread(self.chroma_collection.update, ...)` |
| P4a#NEW-6 | `main.py` | 1414 | `subprocess.run()` blockiert 30s (ffmpeg) | `asyncio.create_subprocess_exec()` |

### Cluster 2B: Race Conditions (8 Bugs)

| # | Datei | Zeile | Problem | Fix |
|---|-------|-------|---------|-----|
| P4a#36 | `personality.py` | 2243 | `_current_mood` ohne Lock, geschrieben in `build_system_prompt()`, gelesen von `build_notification_prompt()` ausserhalb `_process_lock` | `self._mood_lock = asyncio.Lock()` in `__init__`, `async with self._mood_lock:` um Read/Write |
| P4a#37 | `personality.py` | 2299 | `_current_formality` gleiche Race wie #36 | Gleicher Lock |
| P4a#39 | `mood_detector.py` | 751 | `analyze_voice_metadata()` ohne `_analyze_lock` — Race mit `analyze()` | `async with self._analyze_lock:` auch in `analyze_voice_metadata()` |
| P4a#53 | `function_calling.py` | 1146 | `_tools_cache = None` ohne `_tools_cache_lock` | `with _tools_cache_lock: _tools_cache = None` |
| P4b#2 | `proactive.py` | 2620 | `_batch_flushing` Boolean ohne Lock | `asyncio.Lock` oder bestehenden `_state_lock` mitnutzen |
| P4b#113 | `config.py` | 241-247 | `_active_person` globaler String ohne Lock | `threading.Lock` hinzufuegen |
| P4b#114 | `config.py` | 319 | `get_room_profiles()` Fast-Path VOR Lock — nicht atomar | Fast-Path innerhalb des Lock-Blocks |
| P4c#42 | `access_control.py` | 43-348 | `_timer_lock` existiert, wird in `unlock()`, `_on_state_changed`, `check_auto_lock` NICHT genutzt | `with self._timer_lock:` an ALLEN `_auto_lock_timers` Zugriffen |

### Cluster 2C: N+1 Redis/HTTP (3 Bugs)

| # | Datei | Zeile | Problem | Fix |
|---|-------|-------|---------|-----|
| P4b#58 | `speaker_recognition.py` | 722-771 | `identify_by_embedding()` laedt Embeddings einzeln | `redis.mget()` fuer Batch-Load |
| P4b#168 | `repair_planner.py` | 313-328 | `list_projects()` sequentielle `hgetall` pro Projekt | Redis Pipeline |
| P4a#4 | `brain.py` | shutdown() | Shutdown verpasst 30+ Komponenten mit Background-Tasks | Alle Komponenten mit `.start()`/`.initialize()` muessen `.stop()`/`.shutdown()` bekommen |

### Cluster 2D: Resilience (7 Bugs — wellness_advisor + ha_client)

| # | Datei | Zeile | Problem | Fix |
|---|-------|-------|---------|-----|
| P4b#29 | `ha_client.py` | 72-73 | `close()` nicht thread-safe, `_session` ohne Lock | `async with self._session_lock:` in `close()` |
| P4b#30 | `ha_client.py` | 367 | `mindhome_put()` Session VOR Retry-Loop | Session pro Retry-Versuch frisch holen |
| P4b#31 | `ha_client.py` | 392 | `mindhome_delete()` gleiche stale Session | Session pro Retry-Versuch frisch holen |
| P4c#44 | `special_modes.py` | 128 | `deactivate()` liest `_active` VOR Lock-Acquire | `_active` Check innerhalb `with self._lock:` |
| P4c#45 | `special_modes.py` | 801-831 | 3 Timer-Threads bei Emergency ohne Synchronisation | `with self._lock:` um State-Aenderungen in Timer-Callbacks |
| P4c#33 | `base.py` (Addon) | 88-93 | Hardcoded `is_dark: False` Fallback ohne Logging | `logger.warning()` wenn Sun-Entity nicht verfuegbar |
| P4a#58 | `function_calling.py` | 4792-4806 | settings.yaml Read VOR Lock (TOCTOU) | Read innerhalb Lock-Block verschieben |

### Cluster 2E: Silent Exceptions + Logging (5 Bugs)

| # | Datei | Zeile | Problem | Fix |
|---|-------|-------|---------|-----|
| P4b#3 | `proactive.py` | 1660 | `except Exception: pass` in `_accumulate_event` | `logger.warning()` |
| P4b#4 | `proactive.py` | 1688 | `except Exception: pass` in Mood-Check | `logger.warning()` |
| P4b#5 | `proactive.py` | 1829 | `except Exception: pass` in Narration | `logger.warning()` |
| P4b#7 | `proactive.py` | 1298 | `except Exception: return` ohne Logging | `logger.warning()` |
| P4b#75 | `learning_observer.py` | 147-148 | `logger.debug()` in Hauptverarbeitungslogik | `logger.warning()` |

### Cluster 2F: Sonstige HOHE Bugs (7 Bugs)

| # | Datei | Zeile | Problem | Fix |
|---|-------|-------|---------|-----|
| P4a#6 | `main.py` | 2216 | `_token_lock = asyncio.Lock()` definiert aber NIE acquired (Dead Code) | Lock entfernen ODER korrekt um `_active_tokens` einsetzen |
| P4a#9 | `main.py` | diverse | 3 HTTPExceptions + ~25 Endpoints leaken `str(e)` | Generische Meldung, `logger.error()` fuer Details |
| P4b#72 | `feedback.py` | 345-349 | Double-decode: Z.345 decoded, Z.348 versucht erneut `.decode()` | Redundante Zeile 348 entfernen |
| P4b#116 | `cooking_assistant.py` | 196 | `_timer_tasks` waechst unbegrenzt | Erledigte Timer-Tasks aufraumen |
| P4b#117 | `cooking_assistant.py` | 196 | `session.timers` ohne Limit | Max 10 Timer pro Session |
| P4c#70 | `security.py` (Addon) | 438-461 | Lock/Unlock Endpoints ohne User-Auth | Pruefe ob `before_request` Auth greift, dokumentiere oder fixe |
| P4c#71 | `security.py` (Addon) | 706-727 | Emergency Trigger ohne Auth | Gleiche Pruefung wie #70 |

### Phase-Gate 2:
```bash
cd /home/user/mindhome && find . -name "*.py" -not -path "*/__pycache__/*" -not -path "*/node_modules/*" -exec python3 -m py_compile {} +
```
Commit: `git commit -m "fix: 41 hohe Bugs (sync I/O, race conditions, N+1 Redis, resilience, auth)"`

---

## Phase 3: MITTLERE Bugs (~162 Stück) — nach Phase 2

> Arbeite nach Pattern-Clustern. Ein Commit pro Pattern.

### Pattern A: Sync I/O in async (~20 Stellen)

Alle `open()`, `path.read_text()`, `path.write_text()`, `mkdir()`, `zipfile`, `PIL`, `pdfplumber` Calls in async Methoden → `asyncio.to_thread()`.

Betroffene Dateien (JEDE Zeile verifizieren — manche sind schon gefixt):
- `diagnostics.py:436, 447, 491` — File-I/O in async
- `recipe_store.py:66, 137, 140, 349-350` — ChromaDB + File-I/O sync
- `knowledge_base.py:87, 151, 219, 222` — mkdir, PDF, File sync
- `workshop_generator.py:508, 543, 586-589` — File-I/O + zipfile
- `workshop_library.py:40, 185-186` — mkdir + PDF
- `config_versioning.py:87-91, 266-268` — Redis Pipeline + File-I/O
- `ocr.py:97-136` — PIL/Tesseract CPU-intensiv
- `file_handler.py:61-96` — save_upload komplett sync

### Pattern B: N+1 Redis → Pipeline/mget (~25 Stellen)

Fix-Pattern: Redis Pipeline oder `mget()` statt sequentielle Einzelaufrufe.

```python
# VORHER (N+1):
for key in keys:
    data = await self.redis.hgetall(key)
    results.append(data)

# NACHHER (Pipeline):
pipe = self.redis.pipeline()
for key in keys:
    pipe.hgetall(key)
raw = await pipe.execute()
results = [decode_hash(r) for r in raw]
```

Betroffene Dateien:
- `inventory.py:78-81, 99-103, 125-128, 173-176` — 4x N+1
- `energy_optimizer.py:286-299, 328-356` — 7+14 sequentielle gets
- `repair_planner.py:978-994, 1136-1147` — 2x N+1
- `feedback.py:265-268, 296-313` — 4N Roundtrips + N gets
- `intent_tracker.py:297-303` — N+1 hgetall
- `protocol_engine.py:281-304` — N+1
- `conditional_commands.py:160-219` — N+1 pro Conditional
- `insight_engine.py:620-678` — 8 sequentielle gets
- `semantic_memory.py:342-416, 487-538` — N+1 in get_facts_by_person, _by_category, get_all_facts
- `spontaneous_observer.py:309-348` — Doppeltes Laden derselben Redis-Liste

**WICHTIG**: Pruefe fuer JEDE Stelle ob die Calls wirklich unabhaengig sind. Wenn Call B das Ergebnis von Call A braucht → NICHT parallelisieren.

### Pattern C: Race Conditions → Locks (~15 Stellen)

| Datei | Zeile | Variable | Fix |
|-------|-------|----------|-----|
| `learning_transfer.py` | 73-74 | `_preferences`, `_pending_transfers` | `asyncio.Lock()` |
| `self_optimization.py` | 66 | `_pending_proposals` | `asyncio.Lock()` |
| `circuit_breaker.py` | 44-56 | State-Variablen | `asyncio.Lock()` |
| `adaptive_thresholds.py` | 232-253 | `_set_runtime_value()` mutiert globales Dict | `asyncio.Lock()` oder Copy-on-Write |
| `follow_me.py` | 91, 96 | `_person_room`, `_last_transfer` | `asyncio.Lock()` |
| `visitor_manager.py` | 280 | `_last_ring_time` | `asyncio.Lock()` |
| `speaker_recognition.py` | 150-153 | `_profiles` Dict | Lock auf Mutation |
| `cover_control.py` (Addon) | 97-1014 | `_pending_actions` etc. | Lock erweitern |
| `base.py` (Addon) | 29-94 | `_context_cache` | `threading.Lock()` |
| `ha_connection.py` (Addon) | 98 | `_stats["api_calls"]` | `threading.Lock()` |
| `pattern_engine.py` (Addon) | 467 | List-Reassignment | Lock oder atomarer Swap |

### Pattern D: Redis bytes → .decode() (~10 Stellen)

Fix-Pattern:
```python
# Fuer einzelne Werte:
val = val.decode() if isinstance(val, bytes) else val

# Fuer hgetall:
data = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
```

Betroffene Stellen:
- `outcome_tracker.py:155-156, 208-209` — get/hgetall bytes
- `intent_tracker.py:300` — smembers bytes
- `repair_planner.py:1442-1453, 1476-1478` — hgetall bytes-Keys, float(None)
- `response_quality.py:172-177` — `int(v)` auf Float-Strings → `float(v)`
- `adaptive_thresholds.py:173-178` — bytes-Keys → ZeroDivisionError
- `summarizer.py:157` — bytes-Keys in sort → TypeError
- `wellness_advisor.py:609` — sismember bytes vs String
- `insight_engine.py:701` — fromisoformat ohne Typ-Check

### Pattern E: Silent Exceptions → Level anheben (~15 Stellen)

Aendere `logger.debug("Unhandled: %s", e)` zu `logger.warning()` an wichtigen/sicherheitskritischen Stellen:

- `learning_transfer.py:92-93, 105-106` — Preferences Load/Save
- `insight_engine.py:448-449` — `_run_all_checks()`
- `self_optimization.py:421-423, 593-594` — Feedback-Stats, Character-Break
- `circadian.py:327-328` (Addon) — Licht-Scheduling
- `special_modes.py:1013-1014` (Addon) — **Security-relevant!** → `logger.error()`
- `access_control.py:369-370` (Addon) — **Security-relevant!** → `logger.error()`
- `sleep.py:122-172` (Addon) — 3x nur DEBUG
- `follow_me.py:185-186, 250-251, 279-280` — Transfer-Fehler

### Pattern F: None-Guards (~15 Stellen)

| Datei | Zeile | Problem | Fix |
|-------|-------|---------|-----|
| `proactive.py` | 1672, 1679, 1693, 1570, 1055 | `self.brain.autonomy.level` etc. ohne `getattr` | `getattr(self.brain, "autonomy", None)` |
| `cooking_assistant.py` | 508, 518, 525, 550, 563, 612 | `self.session` ohne None-Guard | `if not self.session: return ...` |
| `automation.py` (Addon) | 276, 349-508 | `request.json` ohne `or {}` | `data = request.json or {}` |
| `notifications.py` (Addon) | 376 | `request.json` ohne `or {}` | `data = request.json or {}` |
| `domains.py` (Addon) | 207, 221 | `_domain_manager()` None → AttributeError | None-Guard |

### Pattern G: Security-Fixes (~10 Stellen)

| Datei | Zeile | Problem | Fix |
|-------|-------|---------|-----|
| `special_modes.py` (Addon) | 587-592 | `alarm_panel_entity` ohne Format-Validierung | Regex: `^[a-z_]+\.[a-z0-9_]+$` |
| `special_modes.py` (Addon) | 1002-1015 | PIN SHA-256 ohne Salt | `hashlib.pbkdf2_hmac` oder mindestens `secrets.token_hex(16)` als Salt |
| `access_control.py` (Addon) | 183 | Access-Codes SHA-256 ohne Salt | Gleicher Fix |
| `special_modes.py` (Addon) | 368-373 | User-String als HA-Service ohne Whitelist | Service-Whitelist definieren |
| `recipe_store.py` | 156 | MD5 fuer Content-Hash | `hashlib.sha256()` |
| `ocr.py` | 58 | Path-Validierung `".." in str(resolved)` | `resolved.is_relative_to(base_dir)` |
| `system.py` (Addon) | 218-223 | Beliebige Settings-Keys aenderbar | Allowlist definieren |
| `users.py` (Addon) | 124-137 | User-Name ohne Sanitisierung | `re.sub(r'[^a-zA-Z0-9_\- ]', '', name)[:50]` |
| `security.py` (Addon) | 398-406 | entity_id aus URL ohne Validierung | Regex wie oben |

### Pattern H: Logik-Bugs (~10 Stellen)

| Datei | Zeile | Problem | Fix |
|-------|-------|---------|-----|
| `context_builder.py` | 746-754 | `latest_room` nur im except-Block zugewiesen — Logik-Inversion | `latest_room = entity_id` im try-Block |
| `mood_detector.py` | 734 | Cross-Person Voice-Emotion-Leak: Fallback liest letzte Person | Aus per-Person State-Dict lesen |
| `personality.py` | 2443-2444 | `defaultdict(str)` verschluckt Template-Fehler | Normales Dict + try/except KeyError |
| `action_planner.py` | 162 | `_QUESTION_STARTS` matcht imperative Multi-Step-Befehle | Praezisere Matching-Logik |
| `action_planner.py` | 344 | `t.result()` ohne try/except | `try: r = t.result() except Exception as e: r = e` |
| `function_calling.py` | 1061 | gather-Result `_` (mindhome) verworfen | Result pruefen und loggen |
| `intent_tracker.py` | 396-424 | `_reminder_loop()` schlaeft ZUERST | Erst pruefen, dann schlafen |
| `ha_client.py` | 377-378, 399-400 | Non-200 sofort return statt Retry | Bei 5xx retrien, bei 4xx abbrechen |

### Pattern I: Resilience (~8 Stellen)

- `diagnostics.py:558` — Redis ohne `async with` / `finally`
- `fire_water.py:167-215` (Addon) — Sequentielle Notfall-Aktionen, Config-Zugriffe ungeschuetzt → try/except pro Aktion
- `fire_water.py:498-553` (Addon) — Event-Publish ungeschuetzt
- `circadian.py:133-134` (Addon) — DB-Fehler → alle Raeume verlieren Override
- `special_modes.py:284-294` (Addon) — Exception in deactivate() → Mode bleibt aktiv
- `ambient_audio.py:380-411` — Poll-Loop ohne Backoff bei HA-Fehler → exponentielles Backoff
- `pattern_engine.py:307-310` (Addon) — Session-Leak im inneren try → finally: session.close()

### Pattern J: Sonstige MITTLERE Bugs (~30 Stellen)

- `websocket.py:51, 76` — `datetime.now()` ohne Timezone
- `model_router.py:191-192` — `_is_model_installed` gibt True bei leerem `_available_models`
- `function_validator.py:28-32` — `require_confirmation` bei Init eingefroren, Hot-Reload unwirksam
- `recipe_store.py:263-268` — `get_chunks()` laedt gesamte Collection vor Offset/Limit
- `smart_shopping.py:289, 302-316` — API-Call ohne Timeout + sequentielle call_service
- `device_health.py:126-139` — Check-Loop ohne Startup-Delay
- `workshop_generator.py:154-155, 511-519` — None-Guard + rpush Duplikate (sadd verwenden)
- `light_engine.py:291, 418, 530` (Addon) — TOCTOU (SET NX), `redis.keys()` O(N) (SCAN)
- `conditional_commands.py:153` (Addon) — Set waehrend Iteration modifiziert → lokale Kopie
- `automation_engine.py:317` (Addon) — `datetime.now()` statt `local_now()`
- `app.py:394` (Addon) — `_recent_events` ohne Hard-Limit
- Und weitere (siehe RESULT-Dateien fuer vollstaendige Liste)

### Phase-Gate 3:
```bash
cd /home/user/mindhome && find . -name "*.py" -not -path "*/__pycache__/*" -exec python3 -m py_compile {} +
```
Commit pro Pattern: `git commit -m "fix: Pattern A — sync I/O in async (20 Stellen)"` etc.

---

## Phase 4: NIEDRIGE Bugs (~119 Stellen) — nach Phase 3

> Fixe nur Bugs die mit **< 5 Zeilen Aenderung** machbar sind. Komplexe Refactorings → dokumentiere als "won't fix" mit Begruendung.

### Cluster: Dead Code entfernen
- `health_monitor.py:314-328` — `_check_temperature()` nie aufgerufen
- `repair_planner.py:78-101` — 11 NAV-Sets erkannt aber nicht behandelt
- `repair_planner.py:105-114` — `REPAIR_KEYWORDS` ungenutzt
- `self_optimization.py:15` — `import re` ungenutzt
- `self_optimization.py:95, 562, 568, 582-583` — Redundante Re-Imports
- `tts_enhancer.py:153-166` — 12 Instance-Variablen gesetzt aber nie gelesen
- `smart_shopping.py:29` — `_KEY_PURCHASE_LOG` ungenutzt
- `follow_me.py:224` — Redundanter Import
- `domains/cover.py:56-101` (Addon) — 2 Methoden nie aufgerufen
- `cover_control.py:100` (Addon) — `_pending_actions` Dead Code
- `adaptive.py:285` (Addon) — `GradualTransitioner._pending` Dead Code
- `automation_engine.py:88-102` (Addon) — `_apply_context_adjustments()` Dead Code
- `speech/server.py:37` — `import json as _json` Dead Code

### Cluster: Memory Leaks (Groessen-Limits)
- `conflict_resolver.py:145-148` — `_last_resolutions` unbegrenzt → `deque(maxlen=100)`
- `predictive_maintenance.py:119-125` — `_devices` unbegrenzt → Cleanup
- `repair_planner.py:1497-1506` — `create_task()` ohne Referenz → Task-Set
- `diagnostics.py:69` — `_alert_cooldowns` unbegrenzt → periodisches Cleanup
- `personality.py:355-356` — `_curiosity_count_today` unbegrenzt → maxlen 100
- `timer_manager.py:137` — `_tasks` dict: cancelled Tasks bleiben
- `pattern_engine.py:336-341` (Addon) — `_last_sensor_*` unbegrenzt

### Cluster: Minor Fixes
- `task_registry.py:120` — Timeout-Meldung sagt "30s" statt korrektem Default
- `energy_optimizer.py:439` — `val > 0` ignoriert Sensoren mit 0 → `val is not None`
- `helpers.py:59-62` (Addon) — `utc_iso()` haengt 'Z' an naive Datetimes
- `notifications.py:128-207` (Addon) — Hardcoded `user_id=1`
- `patterns.py:497, 556` (Addon) — Hardcoded `created_by=1`
- `scenes.py:186-189` (Addon) — Falsche Attribute auf `LearnedPattern`
- `config_flow.py:11` (HA) — Hardcoded IP als Placeholder dokumentieren
- Und weitere (siehe RESULT-Dateien)

### Phase-Gate 4:
```bash
cd /home/user/mindhome && find . -name "*.py" -not -path "*/__pycache__/*" -exec python3 -m py_compile {} +
```
Commit: `git commit -m "fix: ~119 niedrige Bugs (dead code, memory leaks, minor fixes)"`

---

## Phase 5: Verifikation & Dokumentation

### 5.1 Syntax-Check ALLER Dateien
```bash
cd /home/user/mindhome && find . -name "*.py" -not -path "*/__pycache__/*" -not -path "*/node_modules/*" | xargs -I{} python3 -m py_compile {}
```
**Alle 273+ Python-Dateien muessen fehlerfrei kompilieren.**

### 5.2 Ergebnis-Datei erstellen

Erstelle `docs/audit-results/RESULT_09_FINAL_FIXES.md` mit folgendem Format:

```markdown
# Audit-Ergebnis: Prompt 9 — Finale Bug-Fixes

**Datum**: [Datum]
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle verbleibenden Bugs aus DL#2 (P4a + P4b + P4c)

## 1. Zusammenfassung

| Kategorie | Inventar (Phase 0) | Gefixt | Bereits gefixt | Won't Fix | Begruendung |
|-----------|--------------------|---------|--------------|-----------|----|
| KRITISCH  | X | X | X | X | ... |
| HOCH      | X | X | X | X | ... |
| MITTEL    | X | X | X | X | ... |
| NIEDRIG   | X | X | X | X | ... |
| **Gesamt**| **X** | **X** | **X** | **X** | |

## 2. Commits
[Liste aller Commits mit Beschreibung]

## 3. Won't Fix (mit Begruendung)
[Fuer jeden nicht gefixten Bug: Warum nicht, und was stattdessen noetig waere]

## 4. Qualitaetssicherung
- Syntax-Check: X/X Dateien fehlerfrei
- Keine neuen Features
- Keine Breaking Changes
```

---

## ⚠️ Wichtige Hinweise

1. **Phase 0 nicht ueberspringen** — Das Bug-Inventar ist die Grundlage fuer alles. Ohne Inventar werden Bugs uebersehen oder doppelt gefixt.
2. **Zeilennummern koennen verschoben sein** — Durch vorherige Fixes (P06–P08 + Merge) haben sich Zeilen verschoben. Suche den Bug mit Grep anhand des Code-Musters.
3. **Merge-Fixes pruefen** — Insbesondere `self_optimization.py`, `speaker_recognition.py`, `workshop_library.py` wurden beim Merge aufgeloest. Pruefe den aktuellen Stand bevor du fixst.
4. **Reihenfolge einhalten** — Phase 1 → 2 → 3 → 4 → 5. Keine Phase ueberspringen.
5. **Bei Unsicherheit**: Konservativen Fix waehlen (z.B. Logging statt Refactoring). Lieber einen einfachen Fix der sicher funktioniert als einen eleganten der Regressionen verursacht.
6. **Tests**: Falls `pytest` ausfuehrbar ist, nach jeder Phase laufen lassen. Falls Dependencies fehlen (pydantic_settings etc.), ist das OK — Syntax-Check reicht als Minimum.
7. **Addon-Pfade**: Der Addon-Code liegt direkt in `addon/` (nicht in `addon/rootfs/opt/mindhome/`). Pruefe den tatsaechlichen Pfad mit `ls`.
