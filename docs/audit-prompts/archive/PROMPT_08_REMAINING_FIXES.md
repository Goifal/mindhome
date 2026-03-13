# Prompt 8: Verbleibende Bugs fixen — Alle offenen Findings aus dem Audit abarbeiten

## Rolle

Du bist ein Elite-Software-Ingenieur. Du hast die Audit-Ergebnisse (Prompts 1–7b) sowie die Fixes aus Prompts 6a–6d vorliegen. Deine Aufgabe ist es, **alle verbleibenden Bugs** systematisch zu fixen.

---

## ⚠️ Arbeitsumgebung

- Du arbeitest mit dem **GitHub-Quellcode** in `/home/user/mindhome/`
- Assistant-Code: `assistant/assistant/`
- Addon-Code: `addon/rootfs/opt/mindhome/`
- Speech-Code: `speech/`
- Shared: `shared/`
- HA-Integration: `ha_integration/custom_components/mindhome_assistant/`
- Tests: `assistant/tests/`

---

## Kontext

Die Prompts 6a–6d haben **142 Bugs gefixt** (alle damals KRITISCHEN + die meisten HOHEN). Es verbleiben **222 offene Bugs**: 5 KRITISCH, 47 HOCH, 106 MITTEL, 64 NIEDRIG. Dazu kommen 3 Quick-Win-Infrastruktur-Verbesserungen.

**Dieser Prompt fixxt ALLES was noch offen ist.**

---

## Arbeitsweise

### Pro Bug:
1. **Read** — Datei lesen, Bug verifizieren (ist er nach den 6er-Fixes noch da?)
2. **Grep** — Alle Aufrufer/Abhängigkeiten der betroffenen Funktion finden
3. **Edit** — Fix direkt in die Datei schreiben
4. **Grep** — Prüfen ob der Fix konsistent mit allen Aufrufern ist

### Batching:
- Arbeite **eine Datei komplett ab** bevor du zur nächsten gehst (alle Bugs in einer Datei zusammen fixen)
- **Tests nach jedem Batch**: `cd /home/user/mindhome/assistant && python -m pytest tests/test_betroffenes_modul.py -x --tb=short -q`
- **Commit nach jedem Batch**: `git add betroffene_dateien && git commit -m "Fix: Beschreibung"`

### Regeln:
- **Jeder Fix muss VERIFIZIERT sein** — Lies die Datei mit Read, mache die Änderung mit Edit, prüfe mit Grep alle Aufrufer
- **Einfach > Komplex** — Wenn ein simpler Fix reicht, kein Refactoring
- **Tests nicht brechen** — Wenn ein Fix Tests bricht: Fix anpassen, nicht den Test
- **Keine neuen Features** — Nur Bugs fixen, kein Umbau
- **Keine Architektur-Änderungen** — brain.py bleibt wie es ist, kein Event-Bus, kein Refactoring

---

## Phase 1: KRITISCHE Bugs (5 Stück) — ZUERST

> Diese müssen alle gefixt sein bevor Phase 2 beginnt.

### KRIT-1: function_calling.py — _tools_cache Race Condition
- **Datei**: `assistant/assistant/function_calling.py:3119-3154`
- **Problem**: `_tools_cache` ist ein Module-Level Global ohne Lock. Concurrent Requests können Rebuild triggern oder teilweise-geschriebenen Cache lesen.
- **Fix**: `asyncio.Lock` um den Cache-Rebuild. Atomarer Swap: Neuen Cache in lokaler Variable bauen, dann `_tools_cache = new_cache` zuweisen.
- **Grep danach**: `_tools_cache` — alle Lesestellen prüfen

### KRIT-2: wellness_advisor.py — Redis bytes bei Ambient-Cooldown
- **Datei**: `assistant/assistant/wellness_advisor.py:690, 693-694`
- **Problem**: `redis.get()` gibt `bytes` zurück, `fromisoformat()` erwartet `str`. Ambient-Aktions-Cooldown greift nie — Aktionen alle 15 Min statt 30 Min.
- **Fix**: `.decode()` vor `fromisoformat()`. Pattern: `val = await self.redis.get(key); if val: val = val.decode() if isinstance(val, bytes) else val`

### KRIT-3: wellness_advisor.py — Redis bytes bei Break-Cooldown
- **Datei**: `assistant/assistant/wellness_advisor.py:256, 259`
- **Problem**: Gleicher Bug wie KRIT-2 aber für Break-Erinnerungen. 1h-Cooldown wird ignoriert.
- **Fix**: Gleicher Fix wie KRIT-2.

### KRIT-4: recipe_store.py — Sequentielle Ingestion
- **Datei**: `assistant/assistant/recipe_store.py:87, 101-113`
- **Problem**: `ingest_all()` verarbeitet Rezepte sequentiell, Embedding pro Chunk einzeln. Blockiert Event-Loop bei vielen Rezepten.
- **Fix**: `asyncio.gather()` für parallele Verarbeitung oder Batching mit Semaphore (max 5 parallel).

### KRIT-5: Personality-Konsistenz — 25-35% User-Texte umgehen personality.py
- **Datei**: Mehrere Dateien — `assistant/assistant/function_calling.py`, `assistant/assistant/main.py`
- **Problem**: Error-Handler in main.py und execute()-Rückgaben in function_calling.py geben hardcoded Text zurück statt durch personality.py zu gehen.
- **Fix für function_calling.py**: Suche alle `return "..."` Strings in execute-Methoden. Ersetze generische Rückgaben durch Aufrufe von `self.brain.get_varied_confirmation()` oder Jarvis-authentische Varianten.
- **Fix für main.py**: Suche alle `except ... detail=f"..."` Patterns. Ersetze mit 2-3 rotierenden Jarvis-Meldungen: `random.choice(["Suboptimal. Ich prüfe eine Alternative.", "Da stimmt etwas nicht. Ich kümmere mich darum.", "Ein unerwartetes Hindernis. Ich arbeite daran."])`
- **Grep**: `"Fehler"` und `"Error"` und `"nicht verfügbar"` und `"Systeme"` in main.py und function_calling.py — alle hardcoded Texte finden und ersetzen.
- **ACHTUNG**: CRITICAL-Alert-Texte in proactive.py NICHT ändern — die sind bewusst knapp für Latenz (<100ms).

### Phase-Gate 1:
```bash
cd /home/user/mindhome/assistant && python -m pytest --tb=short -q
```
Alle Tests müssen bestehen. Commit: `git commit -m "Fix: 5 kritische Bugs (tools_cache lock, wellness bytes, recipe perf, personality consistency)"`

---

## Phase 2: HOHE Bugs (47 Stück) — nach Phase 1

> Arbeite Datei für Datei. Fasse Bugs pro Datei zusammen.

### Batch 2A: brain.py (2 Bugs)

**BUG-6**: `brain.py:10131-10178` — Shutdown verpasst Module mit Background-Tasks.
- Finde alle Module die `_background_task`, `_loop`, `_timer` oder ähnliche Background-Attribute haben.
- Füge `shutdown()`/`stop()`/`close()` Aufrufe für diese Module in `brain.shutdown()` hinzu.
- Betroffene: `cooking_assistant`, `music_dj`, `repair_planner`, `ambient_audio`, `health_monitor`.

**BUG-7**: `brain.py:2405-2412` — `_with_timeout` gibt Exception-Objekte als normale Werte zurück.
- Nach `results = await asyncio.gather(*tasks, return_exceptions=True)` müssen ALLE Ergebnisse geprüft werden.
- Fix: Nach dem `dict(zip(keys, results))` eine Schleife die `isinstance(v, BaseException)` prüft und diese durch `None` ersetzt + loggt.

### Batch 2B: main.py (3 Bugs)

**BUG-8**: `main.py` ~30 Endpoints — Interne Error-Details in HTTP-Responses.
- Grep: `detail=f"Fehler` und `detail=f"Error` und `detail=str(e)` in main.py.
- Ersetze `detail=f"Fehler: {e}"` durch `detail="Ein interner Fehler ist aufgetreten"`. Logge `e` serverseitig mit `logger.error(f"Endpoint X: {e}")`.
- **NICHT** die User-facing Chat-Responses ändern, nur HTTP-API-Error-Responses.

**BUG-9**: `main.py` — `_active_tokens` unbegrenztes Wachstum.
- Prüfe ob `_active_tokens` ein Dict mit TTL-Cleanup ist. Wenn der 15-Min-Cleanup existiert, reduziere auf 5 Min.
- Alternativ: `if len(_active_tokens) > 10000: _active_tokens.clear()` als Safety-Cap.

**BUG-10**: `main.py:6` — `memory.py:420-443` — `get_all_episodes()` lädt alles.
- Prüfe ob `get_all_episodes()` ein `limit`-Parameter hat. Wenn nicht, füge `limit=1000` Default hinzu.
- Wenn ChromaDB `.get()` kein Limit unterstützt, nutze `.get(limit=1000)`.

### Batch 2C: Memory-Module (3 Bugs)

**BUG-11**: `dialogue_state.py:104` — `_states` dict wächst unbegrenzt.
- Fix: `if len(self._states) > 50: oldest = sorted(self._states, key=lambda k: self._states[k].get("last_update", 0))[:25]; [self._states.pop(k) for k in oldest]`

**BUG-12**: `semantic_memory.py:571-597` — `_delete_fact_inner` meldet falschen Erfolg.
- Read die Methode. Wenn `self.redis is None: return True` → ändern zu `return False`.
- Dead-Code auf Zeile 582 entfernen.

**BUG-13**: `mood_detector.py:267-381` + `mood_detector.py:741-808` — Load-Modify-Store ohne Lock (2 Stellen).
- Fix: `self._analyze_lock = asyncio.Lock()` in `__init__`.
- In `analyze()`: `async with self._analyze_lock:` um den gesamten Load-Modify-Store Block.
- In `analyze_voice_metadata()`: Gleicher Lock.

### Batch 2D: function_calling.py (5 Bugs)

**BUG-15**: `function_calling.py:1050-1052` — `_tools_cache = None` während Catalog-Refresh.
- Fix: Setze `_tools_cache = None` erst NACH dem neuen Catalog-Build. Also: `new_catalog = ...; _tools_cache = None` → `new_catalog = ...; _entity_catalog = new_catalog; _tools_cache = None`.
- Oder besser: Baue neuen Cache direkt und setze atomisch: `_tools_cache = build_new_cache()`.

**BUG-16**: `action_planner.py:335-345` — `wait_for` um `gather` verliert Ergebnisse.
- Fix: Ersetze `asyncio.wait_for(asyncio.gather(*tasks), timeout=X)` durch `done, pending = await asyncio.wait(tasks, timeout=X); results = [t.result() for t in done]; for t in pending: t.cancel()`.

**BUG-17**: `action_planner.py:431-440` — Malformed tool_calls unvalidiert.
- Fix: Vor dem Senden an Ollama: `if not isinstance(tc, dict) or "function" not in tc: continue`.

**BUG-18**: `function_calling.py:1356-1358` — `_ASSISTANT_TOOLS_STATIC` bei Module-Load.
- Fix: Lazy Init mit `_ASSISTANT_TOOLS_STATIC = None` und einer Funktion `_get_static_tools()` die beim ersten Aufruf baut.

**BUG-19**: `function_calling.py:3413-3424` — Mehrfache `get_states()` pro Request.
- Fix: Am Anfang von `_check_consequences()` einmal `states = await self.ha.get_states()` aufrufen und als Parameter durchreichen.

**BUG-20**: `function_calling.py:4741-4786` — settings.yaml ohne File-Lock.
- Fix: `import fcntl`. Vor `yaml.safe_dump()`: `with open(path, 'w') as f: fcntl.flock(f, fcntl.LOCK_EX); yaml.safe_dump(data, f); fcntl.flock(f, fcntl.LOCK_UN)`.

### Batch 2E: self_automation.py (3 Bugs)

**BUG-21**: `self_automation.py:449` — Prompt Injection.
- Fix: `description = description[:500].replace('\n', ' ').replace('\r', '')` und Role-Marker entfernen: `.replace('SYSTEM:', '').replace('USER:', '').replace('ASSISTANT:', '')`.

**BUG-22**: `self_automation.py:103` — `_pending` dict ohne Lock.
- Fix: `self._pending_lock = asyncio.Lock()` in `__init__`. `async with self._pending_lock:` um alle `_pending` Zugriffe.

**BUG-23**: `self_automation.py:996-1001` — `_daily_count`/`_daily_reset` ohne Lock.
- Fix: Gleicher Lock wie BUG-22 oder separater Lock für Rate-Limit.

### Batch 2F: ha_client.py (3 Bugs)

**BUG-24**: `ha_client.py:140-165` — `get_camera_snapshot()` ohne Timeout.
- Fix: `async with asyncio.timeout(10):` um den HTTP-Call. Oder `timeout=aiohttp.ClientTimeout(total=10)`.

**BUG-25**: `ha_client.py:154-157` — Camera 404/500 öffnet Circuit Breaker nicht.
- Fix: Nach dem Response-Check: `if resp.status != 200: self._breaker.record_failure()`.

**BUG-26**: `ha_client.py:357-377` — `mindhome_put/delete` ohne Retry.
- Fix: Analog zu `mindhome_post`: `for attempt in range(3): try: ... break except: if attempt == 2: raise; await asyncio.sleep(1)`.

### Batch 2G: Sound & Audio (6 Bugs)

**BUG-27**: `sound_manager.py:302-303` — `except Exception: pass` bei unjoin.
- Fix: `except Exception as e: logger.warning(f"unjoin failed: {e}")`

**BUG-28 bis BUG-31**: `multi_room_audio.py:174, 362-363, 482, 495-496` — 4× `except Exception: pass/return`.
- Fix: Für jede Stelle `logger.warning(f"...")` hinzufügen.
- Bei BUG-30 (volume_set): `success: False` statt `success: True` zurückgeben.

**BUG-32+33**: `feedback.py:262-264, 344-351` — Redis bytes nicht dekodiert.
- Fix: `.decode()` Pattern an den betroffenen Stellen.

**BUG-34**: `feedback.py:84, 406-411` — `_pending` concurrent Access.
- Fix: Iteration über `list(self._pending.items())` statt direkt über dict.

### Batch 2H: Config & Task (4 Bugs)

**BUG-35**: `config.py:319` — `get_room_profiles()` TOCTOU.
- Fix: Gesamten Cache-Check unter Lock: `async with self._lock: if cached: return cached; result = ...; cache = result; return result`.

**BUG-36**: `config_versioning.py:133` — `rsplit("_", 2)` bei Config-Namen mit Unterstrich.
- Fix: Config-Name aus Redis-Metadaten lesen statt aus dem Dateinamen.

**BUG-37**: `cooking_assistant.py:891` — Redis bytes.
- Fix: `.decode()` Pattern.

**BUG-38**: `task_registry.py:94, 117` — `shutdown(timeout=...)` wird ignoriert.
- Fix: `timeout=timeout` statt `timeout=30`.

### Batch 2I: Shared Schemas (2 Bugs)

**BUG-39+40**: `shared/` — Komplettes Paket ist Dead Code.
- Fix: **Lösche das gesamte `shared/` Verzeichnis** (schemas, constants, events). Es wird von NIEMAND importiert. Die tatsächlichen Schemas sind in main.py definiert.
- Grep vorher: `from shared` und `import shared` in ALLEN Verzeichnissen — muss 0 Treffer geben.
- Wenn > 0 Treffer: NICHT löschen, sondern als Kommentar dokumentieren.

### Batch 2J: Addon Security (5 Bugs)

**BUG-41**: `addon/rootfs/opt/mindhome/routes/security.py:438-453` — Lock/Unlock ohne Auth.
- Fix: Auth-Middleware-Check am Anfang der Route (analog zu anderen geschützten Endpoints).

**BUG-42**: `addon/rootfs/opt/mindhome/routes/security.py:696-707` — Emergency-Trigger ohne Auth.
- Fix: Auth + Rate-Limit (max 3 Calls/Minute).

**BUG-43**: `addon/rootfs/opt/mindhome/routes/automation.py:134-188` — None-Crash bei deps.
- Fix: `sched = _deps.get("automation_scheduler"); if not sched: return jsonify({"error": "Scheduler not ready"}), 503`

**BUG-44**: `addon/rootfs/opt/mindhome/routes/notifications.py:103, 111, 119` — Gleicher None-Crash.
- Fix: Gleicher Pattern wie BUG-43.

**BUG-45**: `addon/rootfs/opt/mindhome/routes/presence.py:175, 188` — Gleicher None-Crash.
- Fix: Gleicher Pattern wie BUG-43.

### Batch 2K: Addon Threading (5 Bugs)

**BUG-46**: `automation_engine.py:2260` — Session ohne try/finally.
- Fix: `session = ...; try: ... finally: session.close()`.

**BUG-47+48**: `special_modes.py:36-37, 103, 138, 284-290` — `_active` ohne Lock + Timer Race.
- Fix: `self._lock = threading.Lock()`. `with self._lock:` um alle `_active`/`_active_log_id` Zugriffe.

**BUG-49**: `special_modes.py:804-829` — Emergency-Escalation Timer.
- Fix: Lock um State-Änderungen + try/finally.

**BUG-50**: `access_control.py:42, 116, 255-268, 328` — `_auto_lock_timers` ohne Lock.
- Fix: `self._timer_lock = threading.Lock()`. `with self._timer_lock:` um alle Zugriffe.

**BUG-51**: `routines.py:153` — `time.sleep(1)` blockiert Flask.
- Fix: `threading.Thread(target=lambda: [time.sleep(1), action()], daemon=True).start()` oder besser: `task_scheduler.register()`.

**BUG-52**: Sarkasmus-Level 5 nicht MCU-authentisch.
- Prüfe ob dieser Bug in P06c bereits gefixt wurde (Sarkasmus auf Level 4 gedeckelt). Wenn ja → überspringen.

### Phase-Gate 2:
```bash
cd /home/user/mindhome/assistant && python -m pytest --tb=short -q
```
Commit: `git commit -m "Fix: 47 hohe Bugs (race conditions, auth, bytes, threading, shutdown)"`

---

## Phase 3: MITTLERE Bugs (106 Stück) — nach Phase 2

> Hier sind die Bugs nach Muster gruppiert statt einzeln, da viele dieselbe Fix-Kategorie haben.

### Muster A: `except Exception: pass` → Logging hinzufügen (ca. 25 Stellen)

Führe diesen Grep aus:
```bash
cd /home/user/mindhome && grep -rn "except.*Exception.*pass" assistant/assistant/ addon/rootfs/opt/mindhome/ --include="*.py" | grep -v test | grep -v __pycache__
```

Für **jede** gefundene Stelle:
- Prüfe ob sie bereits in P06a-d gefixt wurde (Vergleiche mit dem Git-Log).
- Wenn noch `except Exception: pass` oder `except Exception:\n            pass`: Ersetze durch `except Exception as e: logger.debug(f"[Modulname] {e}")`.
- Bei **sicherheitskritischen** Stellen (fire_water, security, access_control): `logger.error()` statt `logger.debug()`.

Betroffene Dateien (aus Bug-Liste):
- `main.py:871, 6591, 7265`
- `semantic_memory.py:396`
- `memory.py:176`
- `function_calling.py:3803`
- `speaker_recognition.py:877, 905`
- `multi_room_audio.py:101`
- `self_optimization.py:549, 575, 633`
- `protocol_engine.py:193`
- `music_dj.py:116, 383`
- `config_versioning.py:195`
- `smart_shopping.py:389`
- `special_modes.py:442`
- `explainability.py:55`
- `timer_manager.py:699, 749`
- `spontaneous_observer.py:260`

### Muster B: Redis bytes → `.decode()` (ca. 15 Stellen)

Führe diesen Grep aus:
```bash
cd /home/user/mindhome && grep -rn "fromisoformat\|\.replace.*mha\|hgetall\|\.get(" assistant/assistant/anticipation.py assistant/assistant/autonomy.py assistant/assistant/self_optimization.py assistant/assistant/smart_shopping.py assistant/assistant/intent_tracker.py assistant/assistant/outcome_tracker.py assistant/assistant/mood_detector.py assistant/assistant/time_awareness.py assistant/assistant/cooking_assistant.py assistant/assistant/speaker_recognition.py --include="*.py"
```

Betroffene Stellen:
- `anticipation.py:131-135` — `lrange()` bytes
- `autonomy.py:408` — `hgetall()` bytes-Keys
- `self_optimization.py:623-625` — `hgetall()` bytes in Phrase-Filter
- `smart_shopping.py:175` — `hgetall()` bytes-Keys
- `intent_tracker.py:300-301` — `hgetall()` bytes
- `outcome_tracker.py:200-202` — `key.split(":")` auf bytes
- `mood_detector.py:519` / `time_awareness.py:519` — Bytes vs String bei Redis-Date

Pattern für alle: `val = val.decode() if isinstance(val, bytes) else val`
Für hgetall: `{k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}`

### Muster C: `datetime.now()` ohne Timezone (ca. 8 Stellen)

- `websocket.py:51`
- `situation_model.py:95`
- `protocol_engine.py:124`
- `base.py:223` (Addon, deprecated `utcnow()`)
- `automation_engine.py:1183-1184, 1231`
- `automation_engine.py:317`

Fix: `datetime.now()` → `datetime.now(timezone.utc)` oder `datetime.now(tz=timezone.utc)`.
Importiere `from datetime import timezone` wo nötig.

### Muster D: Sequentielle async-Calls → `asyncio.gather()` (ca. 15 Stellen)

Betroffene Stellen:
- `energy_optimizer.py:291-299` (7 Redis gets) → `await asyncio.gather(*[self.redis.get(k) for k in keys])`
- `energy_optimizer.py:333-356` (14 Redis gets) → Gleich
- `summarizer.py:199-204` (7 Redis calls) → `asyncio.gather()`
- `summarizer.py:243-251` (31 Redis calls) → `asyncio.gather()`
- `repair_planner.py:322-326` (N hgetall) → `asyncio.gather()`
- `repair_planner.py:1629-1636` (N get_states) → Einmal cachen
- `wellness_advisor.py:186-190` (5 checks) → `asyncio.gather()`
- `follow_me.py:125-146` (3 transfers) → `asyncio.gather()`
- `diagnostics.py:585-604` (10 checks) → `asyncio.gather()`
- `knowledge_base.py:330-331` (multi query) → `asyncio.gather()`
- `knowledge_base.py:200-205` (ingest) → Batching
- `workshop_library.py:87, 107` (embedding) → Prüfen ob async
- `multi_room_audio.py:485-496` (get_state pro Speaker) → `asyncio.gather()`
- `speaker_recognition.py:737-746` (Redis pro Profil) → Pipeline
- `ambient_audio.py:387-406` (get_state pro Sensor) → `asyncio.gather()`

**WICHTIG**: Prüfe für jede Stelle ob die Calls wirklich unabhängig sind. Wenn Call B das Ergebnis von Call A braucht → NICHT parallelisieren.

### Muster E: Fehlende Locks / Thread-Safety (ca. 10 Stellen)

- `conflict_resolver.py:146` — `_recent_commands` → `asyncio.Lock`
- `outcome_tracker.py:57` — `_pending_count` → `asyncio.Lock`
- `config.py:241-247` — `_active_person` → `threading.Lock`
- `ha_client.py:69-73` — `close()` → `_session_lock`
- `ha_connection.py:74-75` (Addon) — `_stats["api_calls"]` → `threading.Lock`
- `pattern_engine.py:472` (Addon) — `_event_timestamps` → Lock/deque
- `base.py:29-30, 77-94` (Addon) — `_context_cache` → `threading.Lock`
- `cover_control.py:97-100` (Addon) — `_pending_actions` → Lock erweitern
- `adaptive_thresholds.py:54` — `_adjustments_this_week` → `asyncio.Lock`

### Muster F: None-Guards / Defensive Checks (ca. 10 Stellen)

- `conversation.py:78` — UUID als person → Display Name Auflösung
- `function_calling.py:4963` — `args.get("room", "") or ""`
- `ollama_client.py:596-610` — `is_available` ohne await → Methode umbenennen
- `proactive.py:1040` — `self.brain.memory.redis` None-Check
- `proactive.py:5184` — Inkonsistenter Redis-Zugriff
- `ha_connection.py:558` (Addon) — `self._ws` None-Check
- `circadian.py:362` (Addon) — Room None-Check
- `routes/automation.py:276+` (Addon, 5 Stellen) — `request.json or {}`
- `routes/domains.py:89+` (Addon, 4 Stellen) — `request.json or {}` + None-Guard
- `routes/rooms.py:213, 247` (Addon) — `request.json or {}`
- `routes/schedules.py:97, 133` (Addon) — `request.json or {}`

### Muster G: Performance-Fixes (ca. 5 Stellen)

- `function_calling.py:3309-3336` — Early-Return bei exaktem Room-Match
- `light_engine.py:418, 530` — Redis `KEYS` → `SCAN`
- `tts_enhancer.py:337` — Regex vorkompilieren
- `threat_assessment.py:100-101` — Doppelte Weather-Logik → Parameter
- `threat_assessment.py:81` — `get_states()` Timeout hinzufügen

### Muster H: Security-Fixes (ca. 8 Stellen)

- `routes/chat.py:880-903` (Addon) — File-Proxy Path-Traversal → `..` Check
- `routes/security.py:398-406` (Addon) — Entity-ID Format validieren
- `routes/users.py:124-131` (Addon) — Input-Sanitisierung
- `routes/chat.py:511-533` (Addon) — Audio ohne Größenlimit → max 20MB
- `routes/system.py:219-224` (Addon) — Settings-Key-Whitelist
- `special_modes.py:585, 1000` (Addon) — PIN ohne Salt → Log-Warnung (nicht brechen)
- `special_modes.py:369` (Addon) — Service-Injection → Whitelist
- `fire_water.py:198` (Addon) — `unlock_on_fire: True` Default → `False`
- `fire_water.py:167-215` (Addon) — Sequentielle Notfall-Aktionen → try/except pro Aktion
- `access_control.py:163` (Addon) — SHA-256 ohne Salt → Log-Warnung

### Muster I: Sonstige Einzelfixes (ca. 20 Stellen)

- `model_router.py:191-192` — `_is_model_installed` bei leerem `_available_models` → pessimistisch
- `function_validator.py:28-32` — `require_confirmation` bei Init eingefroren → live aus yaml_config
- `declarative_tools.py:218-220` — Mehrfaches YAML-Parsen → Shared Registry
- `conversation_memory.py:78` — Project-ID Kollision → Microseconds
- `semantic_memory.py:151` — MD5 → SHA-256 für Lock-Keys
- `semantic_memory.py:334-411` — N+1 Redis → Pipeline
- `learning_transfer.py:73-74` — `_pending_transfers` unbegrenzt → `[:50]`
- `sound_manager.py:549-556` — `create_task()` ohne Referenz → Task-Set
- `conflict_resolver.py:311` — `create_task()` ohne Referenz → Task-Set
- `proactive_planner.py:218` — Unerreichbarer Code → entfernen
- `init_db.py:317-321` (Addon) — `session.merge()` statt insert
- `light.py:81` (Addon) — Day-Phase Sprachabhängigkeit → Konstanten
- `energy.py:352` (Addon) — entity_id Placement → service_data Dict
- `app.py:394` (Addon) — `_recent_events` Hard-Limit → 200
- `helpers.py:69-83` (Addon) — `_rate_limit_data` Cleanup
- `automation_engine.py:1183` (Addon) — `utcnow()` → `datetime.now(timezone.utc)`
- `speech/handler.py:41-46` — `_get_model_lock()` → Lock bei Modul-Load
- `speech/handler.py:92-101` — Redis Reconnect
- `conversation.py:98` (HA-Integration) — `device_id` Schema
- `config_flow.py:11` (HA-Integration) — Hardcoded IP → konfigurierbar

### Muster J: Config & Personality (aus RESULT_05)

- `settings.yaml.example` — 14 fehlende Sektionen dokumentieren (als Kommentare mit Defaults)
- `personality.py` — Formality-Decay: Gradient auf 3-4 diskrete Stufen (LOW=30-45, MED=45-60, HIGH=60-75, FORMAL=75+)
- `easter_eggs.yaml` — Trigger "reaktor", "turm", "infinity" präzisieren (Wort-Grenzen)
- `personality.py` — Easter-Egg-Cooldown: `self._easter_egg_cooldown = {}`, 5 Min pro Trigger
- `mood_detector.py` — Substring → Wort-Grenzen: `r'\bnicht\b'` statt `"nicht" in text`
- `mood_detector.py` — Mood-Reset: "mir geht's gut", "alles ok" → Reset auf neutral

### Phase-Gate 3:
```bash
cd /home/user/mindhome/assistant && python -m pytest --tb=short -q
```
Commit: `git commit -m "Fix: 106 mittlere Bugs (logging, bytes, timezone, perf, security, config)"`

---

## Phase 4: NIEDRIGE Bugs (64 Stück) — nach Phase 3

> Diese sind größtenteils Code-Qualität. Gleiche Muster wie Phase 3.

### Muster K: Logging statt pass (ca. 10 Stellen)
Gleicher Ansatz wie Muster A für die verbleibenden `except:pass` Stellen.

### Muster L: Unbegrenzte Dicts/Listen → Limits (ca. 8 Stellen)
- `personality.py:355` — `_curiosity_count_today` → Size-Limit 100
- `function_calling.py:61` — `_entity_catalog` → prüfen ob LRU nötig
- `self_automation.py:107` — `_audit_log` → `collections.deque(maxlen=100)`
- `pattern_engine.py:336-341` (Addon) — `_last_sensor_*` → LRU/maxlen
- `automation_engine.py:1320` (Addon) — `_reported` → `OrderedDict` FIFO
- `cover_control.py` (Addon) — `_is_running` Lock
- `proactive.py:1998` — `scan_iter` direkt iterieren

### Muster M: Minor Code-Qualität (Rest)
Alle verbleibenden NIEDRIGEN Bugs:
- `brain.py:1200` — Rekursion → Loop
- `personality.py:1385` — MD5 → SHA-256
- `personality.py:2229` — `.get("max_sentences_mod", 0)`
- `request_context.py:38` — Minor, nur kommentieren
- `proactive.py:2130` — Duplikat-Funktion entfernen
- `conditional_commands.py:140` — Type-Hint Optional
- `conditional_commands.py:282` — `math.isclose()`
- `cover_config.py:196, 212` — `max(0, min(100, position))`
- `climate_model.py:279` — Warnung bei extremer Temperatur
- `error_patterns.py:87` — Saubere if/elif
- `circuit_breaker.py:44-109` — Seiteneffekt in Getter → `try_acquire`
- `threat_assessment.py:37` — `bool()` Konvertierung
- `threat_assessment.py:100` — Einmalig filtern
- `learning_observer.py:148` — `logger.warning()`
- `self_report.py:50-53` — Redis-Timestamp Init
- `self_optimization.py:366-379` — Tempfile + `os.replace()`
- `feedback.py:338-344` — try/except um Redis
- Alle verbleibenden Addon-Bugs (scenes.py Attribute, notifications.py user_id, schedules.py MD5, etc.)

### Muster N: Humor & Easter Eggs
- `humor_triggers.yaml` — "Samstagsmorgens" → "Wochenendmorgens"
- `easter_eggs.yaml` — "joke" Easter Egg überarbeiten (MCU-authentischer Witz statt Knock-Knock)
- `mood_detector.py` — `rapid_command_stress_boost` Schwelle von 2 auf 4 erhöhen
- `mood_detector.py` — `tired_boost` nach 23 Uhr von 0.3 auf 0.15 reduzieren
- `personality.py` — `sarcasm_negative_patterns` → Wort-Grenzen-Matching

### Phase-Gate 4:
```bash
cd /home/user/mindhome/assistant && python -m pytest --tb=short -q
```
Commit: `git commit -m "Fix: 64 niedrige Bugs (code quality, limits, humor, minor fixes)"`

---

## Phase 5: Quick-Win Infrastruktur (3 Stück) — nach Phase 4

### QW-1: Log-Rotation in docker-compose.yml
- **Datei**: `docker-compose.yml`
- Füge zu JEDEM Service hinzu:
```yaml
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### QW-2: Embeddings-Cache
- **Datei**: `assistant/assistant/embeddings.py`
- Füge einen LRU-Cache hinzu:
```python
from functools import lru_cache
# Oder manueller Cache mit maxsize für die embed()-Funktion
_embedding_cache = {}
_CACHE_MAX = 1000

def get_embedding(text):
    if text in _embedding_cache:
        return _embedding_cache[text]
    result = _compute_embedding(text)
    if len(_embedding_cache) >= _CACHE_MAX:
        _embedding_cache.pop(next(iter(_embedding_cache)))
    _embedding_cache[text] = result
    return result
```

### QW-3: Disk-Space-Check
- **Datei**: `assistant/assistant/diagnostics.py`
- Füge in `check_all()` oder als eigene Methode hinzu:
```python
import shutil
def check_disk_space(self):
    usage = shutil.disk_usage("/")
    free_pct = (usage.free / usage.total) * 100
    if free_pct < 10:
        logger.warning(f"Disk space low: {free_pct:.1f}% free")
        return {"status": "warning", "free_pct": round(free_pct, 1)}
    return {"status": "ok", "free_pct": round(free_pct, 1)}
```

### Phase-Gate 5:
```bash
cd /home/user/mindhome/assistant && python -m pytest --tb=short -q
```
Commit: `git commit -m "Infra: Log-Rotation, Embeddings-Cache, Disk-Space-Check"`

---

## Finaler Phase-Gate

```bash
# Vollständige Test-Suite
cd /home/user/mindhome/assistant && python -m pytest --tb=short -q

# Ergebnis dokumentieren:
# Tests: X bestanden / Y fehlgeschlagen / Z übersprungen
```

### Output am Ende

Erstelle eine Zusammenfassung:

```
## Fix-Report Prompt 8

### Statistik
- Bugs gefixt: X von 222
- Bugs übersprungen (bereits gefixt): X
- Bugs die nicht fixbar waren: X (mit Begründung)
- Neue Tests geschrieben: X
- Tests nach allen Fixes: X bestanden / Y fehlgeschlagen

### Commits
[Liste aller Commits]

### Verbleibende Punkte
[Falls Bugs nicht fixbar waren — warum und was stattdessen nötig ist]
```

---

## ⚠️ Wichtige Hinweise

1. **Wenn ein Bug bereits durch P06a-d gefixt wurde**: Prüfe kurz mit Read/Grep ob der Fix da ist, dann überspringe und notiere "bereits gefixt".
2. **Wenn eine Datei nicht existiert oder die Zeilennummer nicht stimmt**: Die Zeilen können sich durch vorherige Fixes verschoben haben. Suche den Bug mit Grep anhand des Codemusters.
3. **Wenn ein Fix Tests bricht**: Fix anpassen, NICHT den Test. Tests repräsentieren gewünschtes Verhalten.
4. **Reihenfolge ist wichtig**: Phase 1 → 2 → 3 → 4 → 5. Keine Phase überspringen.
5. **Bei Unsicherheit**: Lieber einen konservativen Fix (z.B. nur Logging hinzufügen) als einen riskanten Umbau.
