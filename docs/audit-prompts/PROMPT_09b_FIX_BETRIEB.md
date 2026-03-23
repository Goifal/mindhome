# Prompt 09b — Fix: Betriebs-Findings beheben

> **Abhängigkeit**: Nach P08b (Betrieb Analyse) + P09a (Code-Qualität Fixes).
> **Dauer**: ~30–60 Minuten
> **Fokus**: Alles fixen was P08b gefunden hat. Multi-User absichern, Frontend härten, Logging verbessern.

---

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du fixst systematisch alle Betriebs-Probleme die in Prompt 08b identifiziert wurden.

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Analyse-Prompts:

```
Read: docs/audit-results/RESULT_08b_BETRIEB.md
Read: docs/audit-results/RESULT_09a_FIX_CODEQUALITAET.md
```

> Falls eine Datei nicht existiert → überspringe sie. Wenn KEINE Result-Dateien existieren, nutze Kontext-Blöcke aus der Konversation oder starte mit Prompt 01.

---

## Grundregel

**Jedes Finding wird gefixt. Keine Ausnahmen.**

Für jedes Finding aus P08b:
1. **Lies den Code** an der betroffenen Stelle
2. **Fix den Code** direkt mit Edit/Write
3. **Verifiziere** dass der Fix korrekt ist (Tests, Code-Review)
4. Wenn du **nicht genug Kontext** hast → Lies mehr Code bis du genug weißt
5. Wenn der Fix **Architektur-Änderungen** braucht → Triff die beste Entscheidung, dokumentiere WARUM

---

## Phase Gate: Regression-Check

```bash
cd assistant && python -m pytest --tb=short -q 2>&1 | tail -20
```
→ BASELINE notieren. Nach jedem Fix-Block erneut prüfen.

---

## Fix-Aufgaben (aus P08b Kontext-Block)

### 1. Multi-User & Concurrency Fixes

#### Fix: Request-Isolation

Wenn `brain.py` Shared Mutable State hat (kein Lock, globale Variablen):

```python
# VORHER (unsicher):
class Brain:
    def __init__(self):
        self.current_context = None  # Shared zwischen Requests!

# NACHHER (sicher):
class Brain:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def process(self, user_input, user_id):
        async with self._lock:
            context = self._build_context(user_input, user_id)  # Request-scoped
            ...
```

**Fix-Pattern**: Jeder mutable State muss entweder:
- **Lock-geschützt** sein (`asyncio.Lock()`)
- **Request-scoped** sein (als lokale Variable, nicht `self.`)
- **User-isoliert** sein (Redis-Key mit `user_id`)

#### Fix: LLM-Concurrency (GPU-Schutz)

Wenn kein Concurrency-Control für LLM-Requests existiert:

```python
# In brain.py oder llm_client.py hinzufügen:
_llm_semaphore = asyncio.Semaphore(1)  # Nur 1 LLM-Request gleichzeitig

async def _call_llm(self, prompt, **kwargs):
    async with self._llm_semaphore:
        try:
            result = await asyncio.wait_for(
                self._ollama_generate(prompt, **kwargs),
                timeout=30.0
            )
            return result
        except asyncio.TimeoutError:
            logger.error("LLM request timed out after 30s")
            return self._fallback_response()
```

#### Fix: Redis Key-Isolation

Wenn Redis-Keys keine User-ID enthalten:

```python
# VORHER:
await redis.set("jarvis:memory", data)

# NACHHER:
await redis.set(f"jarvis:{user_id}:memory", data)
```

**Prüf-Methode:**
```
Grep: pattern="redis.*set\(.*jarvis:" path="assistant/assistant/" output_mode="content"
```
→ Jeder Key ohne `user_id` oder äquivalenten Identifier → fixen.

### 2. Frontend-Fixes

#### Fix: XSS

```javascript
// VORHER (unsicher):
element.innerHTML = userInput;

// NACHHER (sicher):
element.textContent = userInput;
// Oder bei HTML-Rendering:
element.innerHTML = DOMPurify.sanitize(userInput);
```

#### Fix: CORS

```python
# VORHER (zu offen):
app.add_middleware(CORSMiddleware, allow_origins=["*"])

# NACHHER (spezifisch):
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8123", "http://homeassistant.local:8123"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

#### Fix: WebSocket-Reconnect

Wenn kein Auto-Reconnect im Frontend:

```javascript
// WebSocket mit Reconnect-Logik
function connectWebSocket() {
    const ws = new WebSocket(WS_URL);
    ws.onclose = () => {
        console.log('WebSocket closed, reconnecting in 3s...');
        setTimeout(connectWebSocket, 3000);
    };
    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
    };
    return ws;
}
```

### 3. Logging-Fixes

#### Fix: print() → logger

```
Grep: pattern="print\(" path="assistant/assistant/" output_mode="content"
```

Für jeden Fund:
```python
# VORHER:
print(f"Processing request: {user_input}")

# NACHHER:
logger.info("Processing request for user %s", user_id)
# WICHTIG: Keine User-Inputs im Log (Datenschutz)!
```

#### Fix: Stille Fehler

```
Grep: pattern="except.*:\s*$|except.*:.*pass" path="assistant/assistant/" output_mode="content" multiline=true
```

Für jeden Fund:
```python
# VORHER:
try:
    result = await risky_operation()
except:
    pass

# NACHHER:
try:
    result = await risky_operation()
except Exception as e:
    logger.exception("Failed to execute risky_operation")
    result = default_value  # Sinnvoller Fallback
```

#### Fix: Sensitive Daten in Logs

```
Grep: pattern="logger.*token|logger.*password|logger.*api_key|logger.*secret" -i path="." output_mode="content"
```

Für jeden Fund:
```python
# VORHER:
logger.debug(f"Connecting with token: {api_token}")

# NACHHER:
logger.debug("Connecting with token: %s...%s", api_token[:4], api_token[-4:])
# Oder besser:
logger.debug("Connecting to service (token configured)")
```

#### Fix: Request-ID Tracking

Wenn kein Request-Tracking existiert, füge Middleware hinzu:

```python
# In main.py (FastAPI):
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        logger.info("[%s] %s %s", request_id, request.method, request.url.path)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

### 4. Health-Endpoint-Fixes

Wenn Health-Endpoints fehlen oder unvollständig:

```python
# In jedem Service (FastAPI/Flask):
import time
START_TIME = time.time()  # Am Modul-Top-Level definieren (beim Import/Start)

@app.get("/health")
async def health():
    checks = {}
    # Redis
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    # ChromaDB
    try:
        chroma_client.heartbeat()
        checks["chromadb"] = "ok"
    except Exception:
        checks["chromadb"] = "down"
    # Ollama
    try:
        # Simple model list check
        checks["ollama"] = "ok"
    except Exception:
        checks["ollama"] = "down"

    status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks, "uptime": time.time() - START_TIME}
```

### 5. Persistenz-Fixes

#### Fix: Redis-Persistenz

Wenn Redis ohne Persistenz läuft:

```yaml
# In docker-compose.yml, Redis-Service:
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes --appendfsync everysec
  volumes:
    - redis_data:/data
```

#### Fix: Volume-Mounts

Prüfe ob alle Daten-Verzeichnisse als Volumes gemounted sind:

```
Read: /home/user/mindhome/assistant/docker-compose.yml
```

Jedes persistente Datenverzeichnis muss ein Volume haben:
- Redis: `/data`
- ChromaDB: `/chroma/data` oder äquivalent
- SQLite: `/app/data` oder äquivalent

---

## Fix-Strategie bei komplexen Problemen

Wenn ein Fix tiefere Architektur-Änderungen braucht:

1. **Kleinsten möglichen Fix wählen** — kein Over-Engineering
2. **Rückwärts-kompatibel** — bestehende API-Verträge nicht brechen
3. **Test schreiben** für den Fix (wenn Test-Framework vorhanden)
4. **Dokumentieren** warum du dich so entschieden hast

Wenn du trotzdem blockiert bist:
```
OFFEN:
- 🔴 [KRITISCH] Beschreibung | Datei:Zeile | GRUND: Braucht Architektur-Umbau in brain.py
  → ESKALATION: ARCHITEKTUR_NOETIG
```

---

## Claude Code Tool-Einsatz

| Aufgabe | Tool |
|---|---|
| Code lesen & verstehen | **Read** + **Grep** |
| Code ändern | **Edit** |
| Neue Dateien erstellen | **Write** |
| Tests laufen lassen | **Bash** |
| Abhängigkeiten suchen | **Grep** |

---

## Erfolgskriterien

- □ Multi-User-Probleme gefixt (Locks, Isolation, GPU-Schutz)
- □ Frontend gehärtet (XSS, CORS, Reconnect)
- □ Logging verbessert (print→logger, keine Secrets, Request-ID)
- □ Health-Endpoints vollständig (alle Services, Dependency-Checks)
- □ Persistenz gesichert (Redis AOF, Volume-Mounts)
- □ Regression-Check bestanden
- □ Kein Finding offen ohne dokumentierten GRUND

```
Checkliste:
□ brain.py Thread-Safe (Lock oder Request-scoped)
□ LLM-Semaphore implementiert
□ Redis-Keys User-isoliert
□ Frontend XSS-sicher
□ CORS spezifisch konfiguriert
□ Null print() in Produktionscode
□ Null stille Fehler (except: pass)
□ Keine Secrets in Logs
□ Health-Endpoints in allen Services
□ Redis-Persistenz aktiviert
□ Alle Volumes gemounted
□ Tests bestehen
```

---

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_09b_FIX_BETRIEB.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

---

## Output

Am Ende erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
THEMA: Betriebs-Fixes

GEFIXT:
- [Datei:Zeile] Beschreibung des Fixes
- ...

MULTI-USER:
- Request-Isolation: [GEFIXT/WAR_OK]
- LLM-Queue: [GEFIXT/WAR_OK/OFFEN → Grund]
- Redis-Isolation: [GEFIXT/WAR_OK]

FRONTEND:
- XSS: [GEFIXT/WAR_OK/KEIN_FRONTEND]
- CORS: [GEFIXT/WAR_OK]

LOGGING:
- print()→logger: [X Stellen gefixt]
- Stille Fehler: [X gefixt]
- Secrets entfernt: [X gefixt]
- Request-ID: [HINZUGEFÜGT/WAR_OK]

HEALTH:
- Endpoints: [HINZUGEFÜGT/ERWEITERT/WAR_OK]

PERSISTENZ:
- Redis AOF: [AKTIVIERT/WAR_OK]
- Volumes: [GEFIXT/WAR_OK]

OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH

REGRESSION-CHECK:
- Baseline: [X passed, Y failed]
- Nach Fixes: [X passed, Y failed]
- Neue Failures: [KEINE / Liste]

GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
===================================
```
