# P04a — Core Bug-Audit: MindHome/Jarvis

**Auditor:** Claude Opus 4.6
**Datum:** 2026-03-13
**Scope:** 26 Core-Module (Priority 1-4)
**Fokus:** FK10 (Logik), FK8 (Config), FK7 (Daten), FK13 (Performance), FK5 (Init), FK11 (Sicherheit)

---

## Bug-Tabelle (sortiert nach Severity)

### Sev-1 (Critical)

| # | Datei:Zeile | FK | Beschreibung | Fix-Vorschlag |
|---|-------------|-----|-------------|---------------|
| B01 | `proactive.py:404` | FK10 | **HA-WebSocket ohne Timeout/Keepalive.** `async for msg in ws:` blockiert endlos. Wenn HA den WebSocket stumm schliesst (TCP half-open), haengt der gesamte Event-Loop-Thread und es werden KEINE Events mehr verarbeitet — kein Alarm, kein Rauchmelder, kein Wassersensor. Reconnect-Logik greift nicht. | `asyncio.wait_for()` um `ws.receive()` mit z.B. 120s Timeout, oder `ws_connect(heartbeat=30)` nutzen. |
| B02 | `memory.py:427-448` | FK13 | **get_all_episodes() laedt GESAMTE ChromaDB-Collection in RAM.** `chroma_collection.get(limit=total)` bei z.B. 50.000 Episoden alloziert hunderte MB, nur um dann `episodes[offset:offset+limit]` zu slicen. Bei grosser DB OOM-Crash oder Timeout. | ChromaDB `get()` mit `offset`/`limit` direkt nutzen, oder Index-basierte Pagination implementieren. Alternative: `where`-Filter auf Timestamp-Range. |

### Sev-2 (High)

| # | Datei:Zeile | FK | Beschreibung | Fix-Vorschlag |
|---|-------------|-----|-------------|---------------|
| B03 | `brain.py:198` | FK8 | **SCENE_INTELLIGENCE_PROMPT zur Module-Ladezeit berechnet.** `SCENE_INTELLIGENCE_PROMPT = _build_scene_intelligence_prompt()` wird einmalig beim Import ausgefuehrt. YAML-Config-Aenderungen (Hot-Reload) an Szenen werden NIE in diesen Prompt uebernommen — alle Szenen-Intelligence-Features arbeiten mit veralteten Daten. | `SCENE_INTELLIGENCE_PROMPT` als Property oder Methode implementieren, die bei jedem Aufruf `_build_scene_intelligence_prompt()` aufruft (mit Cache + TTL). |
| B04 | `brain.py:2551` | FK7 | **Timezone-Mismatch bei Conversation-Mode.** `datetime.now() - datetime.fromisoformat(_cm_ts)` — `datetime.now()` ist naive (kein tzinfo), aber `_cm_ts` aus Redis kann timezone-aware sein (ISO-Format mit `+00:00`). Ergebnis: `TypeError: can't subtract offset-naive and offset-aware datetimes` → Conversation-Mode bricht still fehl (im except-Block). | `datetime.now(timezone.utc)` konsistent verwenden, oder den Timestamp vor Subtraktion normalisieren. |
| B05 | `action_planner.py:52-54` | FK8 | **Module-Level Config-Auswertung nicht Hot-Reload-faehig.** `_planner_cfg`, `MAX_ITERATIONS`, `COMPLEX_KEYWORDS` werden einmalig beim Import berechnet. Config-Aenderungen via Dashboard greifen erst nach Neustart. `main.py:2995` patcht `ap.MAX_ITERATIONS` nach, aber das greift nur fuer die Brain-Instanz, nicht fuer den module-globalen Wert in `range(MAX_ITERATIONS)` (Zeile 212). | Zugriff auf `yaml_config.get("planner", {})` direkt in `plan_and_execute()` statt Module-Level-Konstanten. |
| B06 | `correction_memory.py:387` | FK10 | **Rate-Limit-Zaehler wird VOR Regelanlage inkrementiert.** `self._rules_created_today += 1` wird INNERHALB des Locks erhoeht, aber BEVOR die eigentliche Rule-Erstellung (ab Zeile 389) ausgefuehrt wird. Wenn die Erstellung fehlschlaegt (Exception in `_get_entries`, LLM-Fehler, etc.), zaehlt der Fehlversuch trotzdem gegen das Tageslimit. Bei z.B. 3 fehlgeschlagenen Versuchen ist das Limit fuer den Tag ausgeschoepft. | Zaehler erst NACH erfolgreicher Rule-Erstellung inkrementieren (nach dem `_save_rule()`-Aufruf). |
| B07 | `model_router.py:191-192` | FK5 | **Alle Modelle "unavailable" vor initialize().** `_is_model_installed()` gibt `False` zurueck wenn `self._available_models` leer ist. Vor dem Aufruf von `initialize()` (das die Ollama-API abfragt) sind ALLE Modelle "nicht installiert". Jeder Early-Access auf den Router (z.B. waehrend Boot-Sequenz oder parallel startende Tasks) erhaelt nur Fallback-Modelle. | Lazy-Init mit `await self._ensure_initialized()` vor `_is_model_installed()`, oder `_available_models = None` als "unbekannt" behandeln (return `True` statt `False`). |

### Sev-3 (Medium)

| # | Datei:Zeile | FK | Beschreibung | Fix-Vorschlag |
|---|-------------|-----|-------------|---------------|
| B08 | `semantic_memory.py:739` | FK7 | **Timezone-Mismatch bei Fakten-Alter-Berechnung.** `age_days = (datetime.now() - datetime.fromisoformat(created)).days` — gleiche Problematik wie B04: `datetime.now()` ist naive, `created` kann aware sein. Ergebnis: `TypeError` → Fakt-Decay-Score wird nicht berechnet, alte Fakten werden nie heruntergestuft. | `datetime.now(timezone.utc)` verwenden. |
| B09 | `situation_model.py:96-98` | FK7 | **Fragiler Timezone-Strip.** `last_dt = last_dt.replace(tzinfo=None)` vor Vergleich mit `datetime.now()`. Funktioniert nur wenn `last_dt` in lokaler Zeitzone gespeichert wurde. Bei UTC-Timestamps ist der Delta falsch (um Stunden verschoben). | Konsequent UTC verwenden: `datetime.now(timezone.utc)` und ggf. `last_dt = last_dt.astimezone(timezone.utc).replace(tzinfo=None)`. |
| B10 | `time_awareness.py:518` | FK7 | **Redis-String/Bytes-Vergleich bei Datumspruefung.** `if stored_date and stored_date != today` — `stored_date` kommt von `redis.get()` und kann je nach `decode_responses`-Setting ein `bytes`-Objekt sein. `bytes("2026-03-13") != str("2026-03-13")` ist IMMER `True` → Zaehler werden bei JEDEM Check-Zyklus zurueckgesetzt. | `stored_date` explizit dekodieren: `stored_date = stored_date.decode() if isinstance(stored_date, bytes) else stored_date`. |
| B11 | `proactive.py:60-61,99,145-179` | FK10 | **event_handlers wird dreimal initialisiert.** `self.event_handlers = {}` bei Zeile 99, dann `self.event_handlers = {...}` bei Zeile 148 (ueberschreibt dynamische Appliance-Handler), dann `self.event_handlers.update(_dynamic_handlers)` bei Zeile 179. Der Code bei Z.99 ist ein Fix-Kommentar ("Fix: Vor devices-Loop initialisieren"), aber die Architektur ist fragil: Zwischen Z.110 und Z.148 werden Handler in `self.event_handlers` geschrieben, die bei Z.148 ueberschrieben werden. Nur der Backup `_dynamic_handlers` rettet sie. | Dict einmalig zusammenbauen: Erst defaults, dann dynamic, dann YAML-Overrides. |
| B12 | `function_calling.py:55` | FK5 | **Module-Level `asyncio.Lock()` erstellt vor Event-Loop.** `_entity_catalog_lock = asyncio.Lock()` wird beim Import erstellt. In Python <3.10 war dies an den laufenden Event-Loop gebunden; in neueren Versionen lazy, aber bei Multi-Loop-Szenarien (Tests, uvicorn reload) kann das Lock an den falschen Loop gebunden sein. | Lock als Instanzvariable oder lazy im FunctionExecutor erstellen. |

### Sev-4 (Low/Info)

| # | Datei:Zeile | FK | Beschreibung | Fix-Vorschlag |
|---|-------------|-----|-------------|---------------|
| B13 | `brain.py:2458+` | FK13 | **Mega-Parallel-Gather mit 20+ Coroutines.** `asyncio.gather()` startet ~20 parallele Coroutines fuer Kontext-Building (Redis, ChromaDB, HA, LLM-Calls). Bei langsamer Redis/HA-Verbindung koennen die Timeouts (15s) kaskadieren und 20 gleichzeitige Timeout-Exceptions erzeugen. `return_exceptions=True` faengt sie ab, aber die Verarbeitung danach prueft nicht systematisch alle Results auf Exceptions. | Exception-Results nach dem Gather systematisch loggen. Ggf. Batch-Groesse begrenzen. |
| B14 | `personality.py:334` | FK10 | **Doppeltes Lock-Pattern (asyncio.Lock + threading.Lock).** `self._state_lock = asyncio.Lock()` UND `self.__mood_formality_lock = threading.Lock()` fuer aehnliche State-Zugriffe. threading.Lock blockiert den Event-Loop bei Contention. | Entweder komplett asyncio.Lock (wenn nur async Code) oder komplett threading.Lock (wenn auch sync Code). Nicht mischen. |
| B15 | `main.py:364` | FK10 | **Boot-Task Exception-Callback nur bei truthy exception.** `task.add_done_callback(lambda t: t.exception() and logger.error(...))` — wenn `t.exception()` `None` ist (kein Fehler), wird nichts geloggt. Aber wenn der Task cancelled wird, wirft `t.exception()` ein `CancelledError`. Das Lambda wuerde dann `CancelledError and logger.error(...)` evaluieren → `CancelledError` wird re-raised im Callback-Kontext, was zu einem unhandled-Exception-Log fuehrt. | `try/except` im Callback, oder `task.add_done_callback` mit separater Funktion. |
| B16 | `main.py:585` | FK10 | **Rate-Limit verwendet `time.monotonic()` korrekt (F-092), aber `_rate_limit_last_cleanup` startet bei 0.0.** Erster Cleanup passiert sofort beim ersten Request (da `monotonic() - 0.0 > 300` immer True). Kein funktionaler Bug, aber unnoetiger Cleanup bei Startup. | `_rate_limit_last_cleanup = _time.monotonic()` statt `0.0`. |

---

## Systemische Probleme (Cross-Module)

### S1: Datetime-Timezone-Inkonsistenz (FK7) — 7 betroffene Module

**278 Vorkommen** von `datetime.now()` ohne Timezone vs. nur **36 mit `timezone.utc`**.

Betroffene Module mit konkreten Bugs:
- `brain.py:2551` — Conversation-Mode-Age (B04)
- `semantic_memory.py:739` — Fakten-Decay-Score (B08)
- `situation_model.py:96-98` — Situations-Delta (B09)
- `time_awareness.py:553` — `datetime.now().timestamp()` (harmlos da UNIX-Timestamp, aber inkonsistent)
- `situation_model.py:61` — Snapshot-Zeitstempel
- `correction_memory.py` — Rule-Timestamps

**Auswirkung:** `datetime.fromisoformat()` gibt bei ISO-Strings mit `+00:00`-Suffix ein timezone-aware Objekt zurueck. Subtraktion mit `datetime.now()` (naive) wirft `TypeError`. Der Fehler ist oft in `try/except`-Bloecken versteckt und fuehrt zu stillem Feature-Ausfall.

**Empfehlung:** Projekt-weites `datetime.now(timezone.utc)` als Standard etablieren. Hilfsfunktion `utcnow()` einmal definieren.

### S2: Module-Level Config-Auswertung (FK8) — 3 betroffene Module

Config-Werte werden beim Import aus `yaml_config` gelesen und als Module-Konstanten gespeichert:
- `brain.py:198` — `SCENE_INTELLIGENCE_PROMPT` (B03)
- `action_planner.py:52-54` — `_planner_cfg`, `MAX_ITERATIONS`, `COMPLEX_KEYWORDS` (B05)
- `function_calling.py:52-54` — `_entity_catalog`, `_CATALOG_TTL`

Hot-Reload via Dashboard (config-Endpunkt) aktualisiert `yaml_config`, aber die Module-Level-Variablen bleiben auf dem alten Wert. `main.py:2995` patcht einzelne Werte nach — fragil und unvollstaendig.

**Empfehlung:** Config-Werte lazy aus `yaml_config` lesen (in Methoden-Aufrufen), nicht beim Import.

### S3: Module-Level `asyncio.Lock()` (FK5) — 1 betroffenes Modul

`function_calling.py:55` erstellt ein `asyncio.Lock()` auf Module-Ebene. In Python 3.10+ ist dies meist harmlos (lazy Loop-Binding), aber bei uvicorn-Reload oder Test-Szenarien mit mehreren Event-Loops problematisch.

---

## Statistik

| Severity | Anzahl |
|----------|--------|
| Sev-1 (Critical) | 2 |
| Sev-2 (High) | 5 |
| Sev-3 (Medium) | 5 |
| Sev-4 (Low/Info) | 4 |
| **Gesamt** | **16** |

| Fehlerklasse | Anzahl |
|-------------|--------|
| FK10 (Logik) | 6 |
| FK8 (Config) | 3 |
| FK7 (Daten/Timezone) | 3 |
| FK13 (Performance) | 2 |
| FK5 (Init/Lifecycle) | 2 |

| Systemisches Problem | Betroffene Module |
|---------------------|-------------------|
| S1: Timezone-Inkonsistenz | 7 |
| S2: Module-Level Config | 3 |
| S3: Module-Level Lock | 1 |

### Audit-Abdeckung

| Prioritaet | Module | Gelesen | Bugs gefunden |
|-----------|--------|---------|---------------|
| P1 (brain.py, main.py) | 2 | Ja (Teile) | 4 |
| P2 (function_calling, proactive, personality, memory) | 4 | Ja | 6 |
| P3 (context_builder, ollama_client, model_router, etc.) | 10 | Ja | 4 |
| P4 (time_awareness, declarative_tools, etc.) | 10 | Ja | 2 |
| **Gesamt** | **26** | **26** | **16** |

---

## P04b Kontext-Block

```yaml
p04a_summary:
  date: "2026-03-13"
  total_bugs: 16
  critical: 2
  high: 5
  medium: 5
  low: 4
  systemic_issues: 3

  top_priority_fixes:
    - id: B01
      file: proactive.py:404
      issue: "HA-WebSocket ohne Timeout — kein Reconnect bei silent disconnect"
      impact: "CRITICAL: Alarm/Rauchmelder/Wassersensor Events gehen verloren"
      effort: "klein (1 Zeile: heartbeat=30 in ws_connect)"

    - id: B02
      file: memory.py:427-448
      issue: "get_all_episodes() laedt gesamte ChromaDB in RAM"
      impact: "CRITICAL: OOM bei grosser DB"
      effort: "mittel (ChromaDB Pagination umbauen)"

    - id: S1
      issue: "Systemweite Timezone-Inkonsistenz (278x datetime.now() ohne tz)"
      impact: "HIGH: Stiller Feature-Ausfall bei timezone-aware Timestamps"
      effort: "gross (projekt-weites Refactoring)"

    - id: B03
      file: brain.py:198
      issue: "SCENE_INTELLIGENCE_PROMPT statisch bei Import"
      impact: "HIGH: Config-Hot-Reload fuer Szenen wirkungslos"
      effort: "klein (Property mit Cache)"

  modules_clean:
    - websocket.py          # Sauber, gute Patterns
    - request_context.py    # Sauber, ContextVar korrekt
    - conversation_memory.py # Sauber, Limits + TTLs
    - memory_extractor.py   # Sauber, konfigurierbar
    - dialogue_state.py     # Sauber, Per-Person State
    - embeddings.py         # Sauber, LRU Cache
    - embedding_extractor.py # Sauber, threading.Lock fuer CPU-bound
    - function_validator.py # Sauber, gute Validierung
    - declarative_tools.py  # Sauber, Schema-Validierung
    - pre_classifier.py     # Sauber, Pattern-basiert

  p04b_focus:
    - "Extended Module (Priority 5-8): ha_client, config, health_monitor, diagnostics"
    - "Addon-Module: cover_config, file_handler, sound_manager, multi_room_audio"
    - "Intelligence-Module: anticipation, insight_engine, learning_observer, learning_transfer"
    - "FK11 (Security) Deep-Dive: Token-Handling, CORS, API-Key-Flow"
```
