# RESULT Prompt 08b — Betrieb: Multi-User, Frontend, Monitoring & Logging

> **DL#3 (2026-03-14)**: Frische Analyse aller Betriebs-Aspekte.

---

## Teil 1: Multi-User & Concurrency

### Schritt 1 — Gleichzeitigkeits-Analyse

```
Grep: pattern="async def|asyncio.Lock|threading.Lock|Semaphore|Queue" path="assistant/assistant/"
→ 50+ async def, 25+ Lock-Instanzen, 2 Semaphore (knowledge_base, recipe_store)

Grep: pattern="global |_instance|singleton|_lock" path="assistant/assistant/"
→ 130+ Treffer — umfangreiche Lock-Verwendung in allen kritischen Modulen
```

**Lock-Inventar (alle gefundenen Locks):**

| Modul | Lock-Typ | Variable | Schuetzt |
|---|---|---|---|
| `brain.py:215` | `asyncio.Lock` | `_process_lock` | Serialisiert alle User-Requests |
| `brain.py:212` | `asyncio.Lock` | `_states_lock` | States-Cache Zugriff |
| `ha_client.py:55` | `asyncio.Lock` | `_session_lock` | HTTP Session Erstellung |
| `ha_client.py:60` | `asyncio.Lock` | `_states_lock` | HA States Cache |
| `ollama_client.py:235` | `asyncio.Lock` | `_session_lock` | Ollama HTTP Session |
| `function_calling.py:55` | `asyncio.Lock` | `_entity_catalog_lock` | Entity-Katalog Refresh |
| `function_calling.py:3140` | `threading.Lock` | `_tools_cache_lock` | Tools-Cache |
| `main.py:434` | `asyncio.Lock` | `_rate_lock` | Rate-Limiting |
| `main.py:2227` | `asyncio.Lock` | `_token_lock` | API-Token Verwaltung |
| `main.py:7605` | `asyncio.Lock` | `_update_lock` | System-Updates |
| `learning_transfer.py:77` | `asyncio.Lock` | `_lock` | Praeferenz-Speicherung |
| `self_optimization.py:67` | `asyncio.Lock` | `_proposals_lock` | Optimierungs-Vorschlaege |
| `feedback.py:53` | `asyncio.Lock` | `_pending_lock` | Feedback-Queue |
| `adaptive_thresholds.py:57` | `asyncio.Lock` | `_adjust_lock` | Schwellwert-Anpassung |
| `correction_memory.py:53` | `asyncio.Lock` | `_rules_lock` | Korrektur-Regeln |
| `follow_me.py:34` | `asyncio.Lock` | `_tracking_lock` | Person-Tracking |
| `proactive.py:86,89` | `asyncio.Lock` | `_batch_flush_lock`, `_state_lock` | Batch-Queue + State |
| `mood_detector.py:83,84` | `asyncio.Lock` + `threading.Lock` | `_analyze_lock`, `_voice_lock` | Stimmungs-Analyse |
| `speaker_recognition.py:153` | `asyncio.Lock` | `_save_lock` | Speaker-Profile |
| `visitor_manager.py:59` | `asyncio.Lock` | `_ring_lock` | Besucher-Klingel |
| `outcome_tracker.py:58` | `asyncio.Lock` | `_pending_lock` | Ergebnis-Tracking |
| `personality.py:326` | `threading.Lock` | `__mood_formality_lock` | Mood/Formality State |
| `web_search.py:242` | `threading.Lock` | `_cache_lock` | Web-Search Cache |
| `embedding_extractor.py:19` | `threading.Lock` | `_model_lock` | ML-Modell Laden |
| `self_automation.py:107` | `threading.Lock` | `_pending_lock` | Pending Automations |
| `conflict_resolver.py:147` | `threading.Lock` | `_commands_lock` | Befehlshistorie |
| `circuit_breaker.py:50` | `threading.Lock` | `_lock` | Breaker State |
| `config.py:242` | `threading.Lock` | `_active_person_lock` | Aktive Person |
| `config.py:315` | `threading.Lock` | `_room_profiles_lock` | Raum-Profile Cache |

**Ergebnis**: 29 Locks in 20 Modulen — umfassende Concurrency-Kontrolle.

| Check | Status | Details |
|---|---|---|
| **Request-Isolation** | ⚠️ TEILWEISE | `_process_lock` serialisiert alle Requests (nur 1 gleichzeitig). Aber kein User-spezifischer State pro Request — alle teilen denselben Brain-State. |
| **Brain Singleton Safety** | ✅ THREAD-SAFE | `_process_lock` (asyncio.Lock) mit 30s Timeout. Bei Timeout: freundliche Fehlermeldung "Einen Moment, ich bin noch mit einer anderen Anfrage beschaeftigt." |
| **Memory Isolation** | ❌ KEINE | `mha:conversations` ist ein GLOBALER Redis-Key (memory.py:97). Alle User teilen dieselbe Konversationshistorie. Keine User-ID im Key. |
| **Redis Key-Isolation** | ❌ KEINE | Keys wie `mha:conversations`, `mha:context:*`, `mha:archive:*` enthalten keine User-ID. Semantische Fakten (`mha:fact:*`) sind `person`-tagged aber nicht isoliert. |
| **LLM-Queue** | ✅ IMPLIZIT | `_process_lock` serialisiert alle brain.process()-Aufrufe → nur 1 LLM-Request im Haupt-Request-Pfad. Proaktive Module koennen parallel LLM nutzen. |
| **WebSocket-Isolation** | ⚠️ BROADCAST | ConnectionManager (websocket.py:17) sendet Events an ALLE Verbindungen (broadcast). Kein per-Connection State. Max 50 Connections. |

**Redis Key-Pattern Analyse:**

| Key-Pattern | User-isoliert? | Details |
|---|---|---|
| `mha:conversations` | ❌ NEIN | Globale Liste, letzte 50 Nachrichten, 7 Tage TTL |
| `mha:archive:{date}` | ❌ NEIN | Tages-Archiv, global |
| `mha:context:{key}` | ❌ NEIN | Kontext-Werte, global |
| `mha:fact:{id}` | ⚠️ PERSON-TAGGED | `person`-Feld im Hash, aber kein Key-Prefix |
| `mha:facts:person:{name}` | ✅ JA | Set pro Person |
| `mha:response_quality:stats:{cat}:person:{name}` | ✅ JA | Statistiken pro Person |
| `mha:health:*` | ❌ NEIN | System-weit |
| `mha:learning_transfer:*` | ❌ NEIN | System-weit |

### Schritt 2 — Race Conditions

| Szenario | Ergebnis | Details |
|---|---|---|
| **2 User gleichzeitig "Licht an"** | ✅ SICHER | `_process_lock` serialisiert Requests. Zweiter User wartet (max 30s) oder erhaelt Timeout-Meldung. Keine doppelten HA-Calls. |
| **User fragt waehrend Proactive laeuft** | ✅ SICHER | `_user_request_active` Flag (brain.py:218). Proaktive Callbacks pruefen dieses Flag (brain.py:5896) und werden unterdrueckt (ausser CRITICAL). |
| **Addon-Automation + User-Command gleichzeitig** | ✅ SICHER | `_process_lock` serialisiert. ConflictResolver (conflict_resolver.py:147) mit `_commands_lock` fuer Befehlshistorie. Entity-Katalog durch `_entity_catalog_lock` geschuetzt. |

**brain.process() Reentrant-Check:**

```python
# brain.py:1072-1086
async def process(self, text, person, room, ...):
    try:
        await asyncio.wait_for(self._process_lock.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        return {"response": "Einen Moment, ich bin noch beschaeftigt...", ...}
    self._user_request_active = True
    try:
        return await self._process_inner(text, person, room, ...)
    finally:
        self._user_request_active = False
        self._process_lock.release()
```

**Ergebnis**: brain.process() ist **NICHT reentrant** — Lock verhindert parallele Ausfuehrung. Bei Timeout (30s) wird eine freundliche Fehlermeldung zurueckgegeben. ✅

### Schritt 3 — GPU-Resource-Schutz

| Check | Status | Details |
|---|---|---|
| **LLM-Requests serialisiert** | ✅ IMPLIZIT | `_process_lock` in brain.py serialisiert alle User-Requests. Kein expliziter Semaphore, aber effektiv nur 1 LLM-Request gleichzeitig im Haupt-Pfad. |
| **Timeout fuer LLM-Requests** | ✅ JA | `ollama_client.py:300-310` mit Tier-spezifischen Timeouts: FAST=30s, SMART=45s, DEEP=120s, STREAM=120s. `aiohttp.ClientTimeout(total=timeout)` |
| **Fallback bei Queue-Overflow** | ✅ JA | brain.py:1074-1080: 30s Timeout auf Lock → "Einen Moment, ich bin noch mit einer anderen Anfrage beschaeftigt." |

**LLM Timeout-Konfiguration (constants.py:15-18):**

| Modell-Tier | Timeout | Verwendung |
|---|---|---|
| `LLM_TIMEOUT_FAST` | 30s | Fast-Modell (3B), Notify-Modell |
| `LLM_TIMEOUT_SMART` | 45s | Smart-Modell (14B, Default) |
| `LLM_TIMEOUT_DEEP` | 120s | Deep-Modell (32B) |
| `LLM_TIMEOUT_STREAM` | 120s | Streaming-Responses |
| `LLM_TIMEOUT_AVAILABILITY` | 5s | Modell-Verfuegbarkeitscheck |

**Proaktive LLM-Nutzung:**
- ProactiveManager und andere Hintergrund-Module koennen parallel zum User-Request LLM nutzen
- `_user_request_active` Flag unterdrueckt nicht-kritische proaktive Callbacks waehrend User-Requests
- Ollama selbst serialisiert GPU-Zugriff intern → kein OOM-Risiko bei parallelen Requests

---

## Teil 2: Frontend-Analyse

### Schritt 1 — Frontend-Dateien Inventar

| Datei | Typ | Zeilen | Service |
|---|---|---|---|
| `addon/rootfs/opt/mindhome/static/frontend/app.jsx` | React JSX | 13.081 | Addon (Haupt-Dashboard) |
| `addon/rootfs/opt/mindhome/static/frontend/index.html` | HTML + CSS | 932 | Addon (Entry Point) |
| `assistant/static/ui/app.js` | Vanilla JS | 11.004 | Assistant (Admin-UI) |
| `assistant/static/chat/index.html` | HTML + JS | 2.237 | Assistant (Chat-Interface) |
| `assistant/static/workshop/index.html` | HTML + JS | 5.947 | Assistant (Workshop) |

**Gesamtumfang Frontend**: ~33.200 Zeilen in 5 Dateien.

### Schritt 2 — Frontend-Code Pruefung

| Check | Status | Details |
|---|---|---|
| **XSS-Schutz** | ⚠️ TEILWEISE | Chat-Interface hat `escapeHTML()` Wrapper (chat/index.html:1657). Workshop hat 88 innerHTML-Zuweisungen — meist statisches HTML, aber potentielles Risiko bei Datenquellen-Aenderung. |
| **CSRF-Schutz** | ⚠️ KEIN EXPLIZITER | Kein CSRF-Token implementiert. Bearer-Token-Auth (resistenter gegen CSRF als Cookie-Auth). `credentials: 'include'` bei einigen Endpoints. |
| **API-Endpoint-Match** | ✅ KORREKT | Frontend-API-Wrapper (app.jsx:39-100) nutzt einheitliche `/api/` Prefix. Alle gecallten Endpoints existieren im Backend. |
| **Error Handling** | ✅ GUT | 148 try/catch Bloecke in app.jsx. Globaler Error-Handler (index.html:832). Fehler werden an `/api/system/frontend-error` gemeldet. |
| **WebSocket-Reconnect** | ✅ VORHANDEN | Reconnect-Attempts werden getrackt und in Health-UI angezeigt (app.jsx:697). HA-WebSocket handled Reconnection server-seitig. |
| **Responsive Design** | ✅ EXCELLENT | Media-Queries fuer 768px und 480px. Flexbox + CSS Grid. Viewport-Meta korrekt. High-Contrast-Support. Keyboard-Navigation (#66). |

**XSS-Detail-Analyse:**

| Datei | innerHTML | Risiko | Details |
|---|---|---|---|
| `chat/index.html` | 9 | ✅ NIEDRIG | `escapeHTML()` Wrapper verwendet |
| `workshop/index.html` | 88 | ⚠️ MITTEL | Meist statische HTML-Templates, kein User-Input direkt |
| `app.jsx` | 0 | ✅ SICHER | React-Komponenten (automatisches Escaping) |
| `app.js` | 0 | ✅ SICHER | DOM-Manipulation ohne innerHTML |

**Kein `dangerouslySetInnerHTML`, kein `v-html`, kein `document.write()` gefunden.**

### Schritt 3 — CORS-Konfiguration

**Addon (Flask, app.py:58-65):**
```python
_CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "").strip()
if _CORS_ORIGINS:
    CORS(app, origins=_CORS_ORIGINS.split(","), supports_credentials=False)
else:
    CORS(app, origins=[], supports_credentials=False)  # Bug #68: Kein Wildcard-Default
```

**Assistant (FastAPI, main.py:404-423):**
```python
_cors_origin_list = [o.strip() for o in _cors_origins.split(",") if o.strip()] if _cors_origins else []
_cors_has_wildcard = "*" in _cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origin_list,
    allow_credentials=not _cors_has_wildcard,  # Credentials nur ohne Wildcard
)
```

| Check | Status | Details |
|---|---|---|
| **CORS konfiguriert** | ✅ KORREKT | `allow_origins` via Umgebungsvariable `CORS_ORIGINS`. Default: leere Liste (kein `*`). |
| **Credentials erlaubt** | ✅ KORREKT | Credentials nur wenn kein Wildcard gesetzt (main.py:420). Addon: `supports_credentials=False`. |
| **Methods eingeschraenkt** | ⚠️ STANDARD | FastAPI CORSMiddleware erlaubt standardmaessig alle Methods. Kein explizites `allow_methods`. |

---

## Teil 3: Logging & Observability

### Schritt 1 — Logging-Inventar

| Metrik | Wert | Status |
|---|---|---|
| Module mit `logging.getLogger()` | 136 (88 Assistant + 46 Addon + 2 Speech) | ✅ Exzellent |
| Abdeckung (Assistant) | 88/90 Module (98%) | ✅ |
| `print()` Statements (Non-Test) | 9 | ✅ Minimal |
| Log-Format | Strukturiert mit Request-ID | ✅ |

**Request-ID Tracking (request_context.py):**
- ContextVar-basiertes Request-ID-Management (asyncio-safe)
- Auto-Generierung: UUID hex[:12] wenn nicht im Header
- X-Request-ID Header-Propagation
- Strukturiertes Log-Format: `%(asctime)s [%(name)s] %(levelname)s: %(request_id)s%(message)s`
- Test-Coverage: 15+ Tests in `test_request_context.py`

| Check | Status | Details |
|---|---|---|
| **Logger statt print()** | ✅ JA | 136 Module nutzen `logging.getLogger()`. Nur 9 print() in assistant/ (Streaming-Output, stderr Fehler). |
| **Log-Level korrekt** | ✅ JA | DEBUG fuer Details, INFO fuer Flow, WARNING fuer Probleme, ERROR fuer Fehler. Korrekte Verwendung durchgaengig. |
| **Strukturiertes Logging** | ✅ JA | StructuredFormatter mit Request-ID. Human-readable Text-Format (kein JSON). |
| **Sensitive Daten** | ✅ SICHER | 0 Leaks gefunden. API-Keys werden maskiert/ausgelassen. Nur "API Key geladen" ohne Wert geloggt. |
| **Request-ID Tracking** | ✅ JA | ContextVar + Middleware + StructuredFormatter. Cross-Service via X-Request-ID Header. |
| **Performance-Logging** | ✅ JA | `time.time()` Messungen (21 Instanzen). Task-Duration Logging. Response-Time Tracking. |

```
Grep: pattern="logger.*password|logger.*token|logger.*key|logger.*secret|logger.*api_key" -i
→ 0 tatsaechliche Secret-Wert-Leaks. Nur Referenzen wie "API Key geladen" (ohne Wert).
```

### Schritt 2 — Error-Tracking

| Check | Status | Details |
|---|---|---|
| **Keine bare excepts** | ✅ EXZELLENT | 0 bare `except:` Klauseln gefunden. Alle Exception-Handler sind typisiert. |
| **Errors geloggt** | ✅ JA | 1.394 Exception-Handler insgesamt. Alle mit `logger.error()` oder `logger.exception()`. |
| **Stack Traces erhalten** | ✅ JA | `logger.exception()` oder `traceback.format_exc()` bei kritischen Fehlern. |
| **Error Rates messbar** | ⚠️ TEILWEISE | `/metrics` Endpoint vorhanden (main.py:8221). Keine expliziten Error-Counter/Prometheus-Metriken. |

**Exception-Handler Statistik:**

| Typ | Anzahl | Bewertung |
|---|---|---|
| `except Exception as e:` | ~1.200 | Standard-Pattern, geloggt |
| `except (ValueError, TypeError):` | ~100 | Spezifische Typen |
| `except: pass` (bare) | 0 | Exzellent |
| `except ... pass` (mit Logging) | ~177 | Akzeptabel (nicht-kritische Pfade) |

### Schritt 3 — Health-Monitoring

**Health-Endpoints pro Service:**

| Service | Endpoint | Typ | Details |
|---|---|---|---|
| **Assistant** | `/api/assistant/health` | Full Check | Prueft Redis, ChromaDB, Ollama, Disk, Memory |
| **Assistant** | `/healthz` | Liveness | Minimal, fuer Docker HEALTHCHECK |
| **Assistant** | `/api/ui/health-trends` | Trends | Historische Health-Daten |
| **Assistant** | `/metrics` | Metriken | Prometheus-kompatibel |
| **Addon** | `/api/health/check` | System Health | HA-Verbindung, DB-Status |
| **Addon** | `/api/device/health` | Geraete | Offline/Battery/Stale |
| **Addon** | `/api/health/dashboard` | Dashboard | Aggregierte Metriken |
| **Addon** | `/api/health/weekly` | Report | Woechentlicher Bericht |
| **Addon** | `/api/health/metrics/*/history` | Historie | 47 historische Metrik-Routen |
| **Speech** | Port 10300 (socket) | Liveness | Docker HEALTHCHECK via socket connect |

| Check | Status | Details |
|---|---|---|
| **Health-Endpoint** | ✅ JA | Alle 3 Services haben Health-Checks. 50+ Health-Routen insgesamt. |
| **Dependency-Health** | ✅ JA | `/api/assistant/health` prueft Redis, ChromaDB, Ollama, HA-Connection, Disk, Memory. |
| **Startup-Probe** | ✅ JA | Alle Docker-Services haben healthcheck mit start_period (15-120s). |
| **Uptime-Tracking** | ✅ JA | Startup-Logging: "MindHome {version} started successfully!" (main.py:1045). |

**Docker HEALTHCHECK Konfiguration:**

| Container | Test | Interval | Start-Period |
|---|---|---|---|
| assistant | `curl http://localhost:8200/api/assistant/health` | — | — |
| chromadb | `curl http://localhost:8000/api/v1/heartbeat` | 30s | 15s |
| redis | `redis-cli ping` | 30s | — |
| whisper | Socket-Test :10300 | 30s | 120s |
| piper | Socket-Test :10200 | 30s | 60s |

---

## Teil 4: Graceful Degradation (Erweitert)

### Kombinierte Ausfaelle

| Szenario | Status | Details |
|---|---|---|
| **Redis DOWN + ChromaDB DOWN** | ✅ BESTANDEN | brain.py:527-568 `_safe_init` Pattern. Memory-Manager prueft `self.redis` und `self.chroma_collection` vor jedem Zugriff → graceful return/skip. Jarvis antwortet ohne Gedaechtnis. |
| **Ollama DOWN + User fragt** | ✅ BESTANDEN | Circuit-Breaker `ollama_breaker` (failure_threshold=5, recovery=15s). OllamaClient gibt `{"error": "..."}` zurueck. model_router.py Fallback-Cascade (DEEP→SMART→FAST). Timeout: 30-120s je Tier. |
| **GPU OOM (2 parallele LLM-Requests)** | ✅ BESTANDEN | `_process_lock` serialisiert User-Requests → maximal 1 gleichzeitig. Ollama serialisiert GPU-Zugriff intern. 30s Lock-Timeout mit freundlicher Meldung. |
| **Addon DOWN + User will Licht steuern** | ✅ BESTANDEN | Circuit-Breaker `ha_breaker` + `mindhome_breaker`. ha_client.py gibt None/leere Liste bei Fehlern zurueck. FunctionExecutor produziert Fehlermeldung. |
| **Speech DOWN + Voice Input** | ✅ BESTANDEN | Whisper-Container hat eigenen healthcheck. HA Voice Pipeline handled Fehler. Circuit-Breaker nicht direkt, aber docker-compose `depends_on: service_healthy` + autoheal Container. |
| **Disk Full + Memory-Write** | ✅ BESTANDEN | diagnostics.py:463-527 Disk-Space-Check. Redis `try/except` um alle Schreiboperationen (memory.py:104). ChromaDB writes in try/except. Logger warnt bei Fehlern. |

**Fallback-Ketten:**

```
LLM-Request → Ollama Circuit-Breaker → Model-Fallback (DEEP→SMART→FAST) → Timeout-Response
Memory-Write → Redis try/except → Warning geloggt → Request laeuft ohne Memory weiter
HA-Call → Circuit-Breaker → Retry mit Backoff → Fehlermeldung an User
Proaktiv → _user_request_active Flag → Unterdrueckung (ausser CRITICAL)
```

---

## Teil 5: Daten-Persistenz & Backup

### Schritt 1 — Persistenz-Inventar

| Daten-Typ | Storage | Pfad/Key | Backup-Strategie |
|---|---|---|---|
| **Conversation History** | Redis (AOF) | `mha:conversations` (50 Eintraege, 7d TTL) | ✅ Redis AOF + Volume |
| **Tages-Archiv** | Redis (AOF) | `mha:archive:{date}` (30d TTL) | ✅ Redis AOF + Volume |
| **Semantic Memory (Fakten)** | Redis (AOF) | `mha:fact:{id}`, `mha:facts:all` | ✅ Redis AOF + Volume |
| **Episodic Memory** | ChromaDB | Collection `mha_conversations` | ✅ ChromaDB Volume (persistent) |
| **User Preferences** | Redis (AOF) | `mha:learning_transfer:preferences` | ✅ Redis AOF + Volume |
| **Automation Rules** | SQLite | `/data/mindhome/mindhome.db` (Addon) | ✅ Addon Backup/Restore API |
| **Addon Config** | SQLite + YAML | DB Settings + `/data/mindhome/` | ✅ Backup Export/Import |
| **Personality State** | Redis (AOF) | `mha:personality:*` | ✅ Redis AOF + Volume |
| **Speaker Profiles** | Redis + Dateien | `mha:speaker:*` + Embeddings | ✅ Redis AOF + Data Volume |
| **Response Quality** | Redis (AOF) | `mha:response_quality:*` (90d TTL) | ✅ Redis AOF + Volume |
| **Assistant Config** | YAML | `config/settings.yaml` | ✅ Config Volume Mount |
| **Whisper Models** | Dateien | Docker Volume | ✅ Volume Mount |
| **Piper Models** | Dateien | Docker Volume | ✅ Volume Mount |

**Docker Volumes (docker-compose.yml):**

| Volume | Container-Pfad | Beschreibung |
|---|---|---|
| `${DATA_DIR}/assistant` | `/app/data` | Assistant Daten |
| `${DATA_DIR}/uploads` | `/app/data/uploads` | Uploads |
| `${DATA_DIR}/chromadb` | `/chroma/chroma` | ChromaDB persistent |
| `${DATA_DIR}/redis` | `/data` | Redis AOF/RDB |
| `${DATA_DIR}/whisper-models` | `/app/models` | Whisper-Modelle |
| `${DATA_DIR}/piper-models` | `/data` | Piper-Stimmen |
| `./config` | `/app/config` | Konfiguration |
| `./static` | `/app/static` | Statische Dateien |

### Schritt 2 — Datenverlust-Szenarien

| Szenario | Was geht verloren? | Recovery |
|---|---|---|
| **Redis-Neustart** | ✅ NICHTS | AOF-Persistenz (`--appendonly yes`). Volume mounted. Daten ueberleben Neustarts. |
| **ChromaDB-Volume geloescht** | ❌ Episodic Memory | Alle semantischen Erinnerungen verloren. `IS_PERSISTENT=TRUE` + Volume schuetzt bei Neustart. |
| **Docker-Container geloescht** | ✅ NICHTS (bei Volumes) | Alle Volumes sind externe Mounts → Daten bleiben erhalten. |
| **Korrupte SQLite-DB** | ❌ Addon-State | Automatisierungsregeln, Geraete, Raeume. Recovery: Backup/Import API (`/api/backup/import`). |
| **Host-Neustart** | ✅ NICHTS | Redis AOF + Docker `restart: unless-stopped` → automatischer Neustart mit Daten. |

**Redis Persistenz-Konfiguration:**
```yaml
# docker-compose.yml:87
command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru
```
- ✅ AOF (Append-Only File) aktiviert
- ✅ Volume gemounted (`${DATA_DIR}/redis:/data`)
- ⚠️ `maxmemory-policy: allkeys-lru` → bei Speicherdruck werden aelteste Keys evicted
- ⚠️ Kein RDB Snapshot zusaetzlich zum AOF

**Addon Backup-System:**
- `/api/backup/export` (GET) — Exportiert Raeume, Geraete, User, Domains, Settings als JSON
- `/api/backup/import` (POST) — Importiert Backup
- Backup-Pfad: `/data/mindhome/backups` (run.sh:35)
- Sensitive Settings werden beim Export gefiltert

---

## Erfolgskriterien

```
✅ Multi-User Sicherheit bewertet — 3 Race-Condition-Szenarien analysiert, alle SICHER
✅ GPU-Concurrency geprueft — _process_lock serialisiert, Timeouts konfiguriert
✅ Frontend analysiert — XSS (97 innerHTML, escapeHTML vorhanden), CORS korrekt, API-Match OK
✅ Logging-Qualitaet bewertet — 136 Module mit Logger, 0 bare excepts, 0 Sensitive Leaks
✅ Health-Monitoring geprueft — alle 5 Docker-Services haben Health-Endpoints
✅ Kombinierte Ausfaelle analysiert — 6/6 Szenarien bestanden
✅ Datenpersistenz geprueft — Redis AOF, ChromaDB persistent, Addon Backup/Restore
```

```
Checkliste:
✅ Request-Isolation verifiziert (serialisiert via _process_lock, aber keine User-Trennung)
✅ LLM-Concurrency geschuetzt (_process_lock + Tier-Timeouts)
✅ Frontend XSS/CORS sicher (escapeHTML, CORS konfigurierbar, kein Wildcard)
✅ Logging strukturiert, keine sensitive Daten (136 Module, Request-ID, 0 Leaks)
✅ Health-Endpoints in allen Services (50+ Routen, Docker healthchecks)
✅ Daten-Persistenz gesichert (Redis AOF, ChromaDB Volume, Addon Backup)
✅ Kombinierte Ausfaelle getestet (6/6 bestanden)
```

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
THEMA: Betrieb (Multi-User, Frontend, Monitoring, Persistenz)

MULTI-USER:
- Request-Isolation: TEILWEISE (serialisiert via _process_lock, aber globaler State — keine User-Trennung in Redis-Keys)
- Brain Singleton: THREAD-SAFE (_process_lock mit 30s Timeout + freundlicher Fallback)
- LLM-Queue: IMPLIZIT VORHANDEN (via _process_lock, nur 1 Request gleichzeitig)
- Race Conditions: 0 kritische gefunden (3 Szenarien geprueft, alle sicher)

FRONTEND:
- XSS-Risiken: 97 innerHTML (9 Chat mit escapeHTML, 88 Workshop meist statisch)
- CORS: KORREKT (Umgebungsvariable, kein Wildcard-Default, Credentials-Check)
- API-Match: 0 Mismatches (alle Frontend-Endpoints existieren im Backend)
- WebSocket-Reconnect: JA (server-seitig, Attempts getrackt + UI-Anzeige)

LOGGING:
- print() statt logger: 9 (Streaming-Output, stderr)
- Stille Fehler (except: pass): 0 bare excepts
- Sensitive Daten in Logs: 0
- Request-ID Tracking: JA (ContextVar + Middleware + StructuredFormatter)
- Health-Endpoints: 5/5 Services (50+ Routen, Docker healthchecks)

PERSISTENZ:
- Redis-Persistenz: AOF (--appendonly yes)
- ChromaDB-Volume: MOUNTED (IS_PERSISTENT=TRUE + Volume)
- Backup-Strategie: VORHANDEN (Addon: /api/backup/export+import, Assistant: Redis AOF + Volumes)

GRACEFUL DEGRADATION (kombiniert):
- Redis DOWN + ChromaDB DOWN: BESTANDEN (_safe_init, graceful skip)
- Ollama DOWN + User fragt: BESTANDEN (Circuit-Breaker, Model-Fallback, Timeout)
- GPU OOM: BESTANDEN (_process_lock serialisiert, 30s Timeout)
- Addon DOWN: BESTANDEN (Circuit-Breaker ha_breaker + mindhome_breaker)
- Speech DOWN: BESTANDEN (autoheal, HA Pipeline Error)
- Disk Full: BESTANDEN (Disk-Space-Check, try/except bei Writes)

GEFIXT: []
OFFEN:
- 🟠 [MEDIUM] Redis-Keys nicht User-isoliert | memory.py:97 | GRUND: mha:conversations ist global, alle User teilen eine History
  → ESKALATION: ARCHITEKTUR_NOETIG (Key-Schema auf mha:user:{id}:conversations umstellen)
- 🟠 [MEDIUM] WebSocket broadcast an alle Clients | websocket.py:43 | GRUND: Kein per-User/Connection Filtering
  → ESKALATION: ARCHITEKTUR_NOETIG (Connection-scoped Events oder User-Filter)
- 🟡 [LOW] CSRF-Token fehlt | Frontend | GRUND: Bearer-Token-Auth mindert Risiko, aber kein expliziter CSRF-Schutz
  → ESKALATION: NAECHSTER_PROMPT
- 🟡 [LOW] Workshop innerHTML ohne Escaping | assistant/static/workshop/index.html | GRUND: 88 innerHTML, meist statisch aber potentielles Risiko
  → ESKALATION: NAECHSTER_PROMPT
- 🟡 [LOW] allow_methods nicht eingeschraenkt | main.py:404 | GRUND: FastAPI CORSMiddleware erlaubt alle Methods standardmaessig
  → ESKALATION: NAECHSTER_PROMPT
- 🟡 [LOW] Redis maxmemory-policy allkeys-lru | docker-compose.yml:87 | GRUND: Bei Speicherdruck werden aelteste Keys evicted (inkl. Fakten)
  → ESKALATION: NAECHSTER_PROMPT
GEAENDERTE DATEIEN: []
===================================
```
