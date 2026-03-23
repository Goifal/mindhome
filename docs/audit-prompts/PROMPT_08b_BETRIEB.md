# Prompt 08b — Betrieb: Multi-User, Frontend, Monitoring & Logging

> **Abhängigkeit**: Nach P08a (Code-Qualität). Nutzt Ergebnisse aller vorherigen Prompts.
> **Dauer**: ~30–45 Minuten
> **Fokus**: Alles was den laufenden Betrieb betrifft — Gleichzeitigkeit, Frontend, Beobachtbarkeit.

---

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du analysierst die Betriebs-Aspekte des MindHome-Projekts: Wie verhält es sich unter Last, wie beobachtet man es, und funktioniert die Oberfläche.

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Analyse-Prompts:

```
Read: docs/audit-results/RESULT_08a_CODEQUALITAET.md
```

> Falls eine Datei nicht existiert → überspringe sie. Wenn KEINE Result-Dateien existieren, nutze Kontext-Blöcke aus der Konversation oder starte mit Prompt 01.

---

## Kontext

MindHome ist ein lokal betriebener KI-Home-Assistant mit 3 Services:
- **Assistant** (`/assistant/`, FastAPI, 89 Module)
- **Addon** (`/addon/`, Flask, 67 Module)
- **Speech** (`/speech/`, Whisper STT, 2 Module)
- Hardware: AMD Ryzen 7 3700X, 64GB RAM, RTX 3090 (24GB VRAM)

---

## Teil 1: Multi-User & Concurrency

### Schritt 1 — Gleichzeitigkeits-Analyse

MindHome kann von mehreren Personen/Geräten gleichzeitig genutzt werden (HA Voice Pipeline, Web-Frontend, API). Prüfe:

```
Grep: pattern="async def|asyncio.Lock|threading.Lock|Semaphore|Queue" path="assistant/assistant/" output_mode="content" head_limit=50
Grep: pattern="global |_instance|singleton|_lock" path="assistant/assistant/" output_mode="content"
Grep: pattern="session|user_id|client_id|request_id" path="assistant/assistant/" output_mode="content" head_limit=30
```

| Check | Methode | ✅ PASS | ❌ FAIL |
|---|---|---|---|
| **Request-Isolation** | Prüfe mit Grep ob globale Variablen oder Modul-Level-State zwischen Requests geteilt wird: `Grep: pattern='global |_instance|_singleton' path='assistant/assistant/' output_mode='content'` | User A sieht nicht User B's Kontext | Shared mutable State zwischen Requests (z.B. `self.current_context` ohne Lock) |
| **Brain Singleton Safety** | brain.py als Singleton — Thread-Safe? | Lock-geschützt oder Request-scoped | Shared mutable State ohne Lock |
| **Memory Isolation** | conversation_memory trennt User | Jeder User hat eigene Conversation-History | Alle User teilen eine History |
| **Redis Key-Isolation** | Redis-Keys enthalten User-ID | `jarvis:user:123:memory` | `jarvis:memory` (global) |
| **LLM-Queue** | Nur 1 LLM-Request gleichzeitig (GPU!) | Queue oder Semaphore vorhanden | Parallel-Requests → GPU OOM |
| **WebSocket-Isolation** | Jede WS-Connection unabhängig | Connection-scoped State | Shared State über Connections |

```
# Redis Key-Pattern prüfen
Grep: pattern="redis.*set\|redis.*get\|self\.redis\." path="assistant/assistant/" output_mode="content" head_limit=30

# LLM Concurrency Control prüfen
Grep: pattern="ollama|generate|chat.*completion|llm.*request" path="assistant/assistant/brain.py" output_mode="content" head_limit=20
```

### Schritt 2 — Race Conditions

Prüfe die **3 kritischsten Race-Condition-Szenarien**:

| Szenario | Was passiert | Prüf-Methode |
|---|---|---|
| **2 User gleichzeitig "Licht an"** | Doppelte HA-Calls? | Grep nach Lock/Semaphore um HA-Calls |
| **User fragt während Proactive läuft** | Antwort-Collision? | Prüfe ob brain.process() reentrant ist |
| **Addon-Automation + User-Command gleichzeitig** | Wer gewinnt? (Konflikt F aus P01) | Prüfe Priority/Locking in function_calling.py |

```
# Reentrant-Check: Kann brain.process() parallel aufgerufen werden?
Read: /home/user/mindhome/assistant/assistant/brain.py offset=1 limit=50
Grep: pattern="self\._processing|self\._lock|asyncio\.Lock" path="assistant/assistant/brain.py" output_mode="content"
```

### Schritt 3 — GPU-Resource-Schutz

```
# Ollama/LLM Concurrency
Grep: pattern="Semaphore|max_concurrent|queue|_llm_lock" path="assistant/assistant/" output_mode="content"
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| LLM-Requests serialisiert | Semaphore(1) oder Queue | Kein Concurrency-Control → GPU OOM bei 2+ parallelen Requests |
| Timeout für LLM-Requests | `asyncio.wait_for(timeout=30)` | Kein Timeout → hängende Requests blockieren Queue |
| Fallback bei Queue-Overflow | "Jarvis ist gerade beschäftigt" | Request wartet endlos oder crashed |

---

## Teil 2: Frontend-Analyse

### Frontend-Analyse (app.jsx — 13.000+ Zeilen)

> ⚠️ `app.jsx` ist das gesamte Frontend in einer Datei. Nutze Grep-first-Strategie.

**Security-Checks:**
```
Grep: pattern="innerHTML|dangerouslySetInnerHTML|eval\(|document\.write" path="addon/rootfs/opt/mindhome/static/frontend/" output_mode="content"
Grep: pattern="fetch\(|XMLHttpRequest|axios" path="addon/rootfs/opt/mindhome/static/frontend/" output_mode="content"
```

| # | Check | Was prüfen |
|---|---|---|
| 1 | **XSS** | Wird User-Input escaped bevor er ins DOM kommt? `textContent` statt `innerHTML`? |
| 2 | **API-Calls** | Werden API-Responses validiert bevor sie angezeigt werden? |
| 3 | **Auth-Token** | Wird der API-Key sicher gespeichert? Nicht in localStorage ohne Verschlüsselung? |
| 4 | **CSRF** | Werden State-ändernde Requests mit Token geschützt? |
| 5 | **Error Handling** | Werden API-Fehler dem User angezeigt oder verschluckt? |
| 6 | **Sensitive Data** | Werden Passwörter/PINs/Keys im Frontend angezeigt oder maskiert? |

### Schritt 1 — Frontend-Dateien inventarisieren

```
Glob: pattern="**/{app,index,main}.{jsx,js,tsx,ts,html,css}" path="/home/user/mindhome/"
Glob: pattern="**/static/**" path="/home/user/mindhome/"
Glob: pattern="**/templates/**" path="/home/user/mindhome/"
```

### Schritt 2 — Frontend-Code prüfen

Für jede Frontend-Datei:

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| **XSS-Schutz** | User-Input escaped vor Rendering | `innerHTML` mit User-Input ohne Escaping |
| **CSRF-Schutz** | Token bei State-Changing Requests | POST/PUT/DELETE ohne CSRF-Token |
| **API-Endpoint-Match** | Frontend-URLs matchen Backend-Routes | 404-Endpoints oder falsche Methoden |
| **Error Handling** | Fehler werden dem User angezeigt | Stille Fehler, UI hängt |
| **WebSocket-Reconnect** | Auto-Reconnect bei Verbindungsverlust | Verbindung stirbt ohne Recovery |
| **Responsive Design** | Funktioniert auf Tablet/Handy | Nur Desktop |

```
# XSS-Patterns suchen
Grep: pattern="innerHTML|dangerouslySetInnerHTML|v-html|document\.write" path="/home/user/mindhome/" glob="*.{js,jsx,ts,tsx,html}" output_mode="content"

# API-Endpoints im Frontend finden
Grep: pattern="fetch\(|axios\.|\.get\(|\.post\(" path="/home/user/mindhome/" glob="*.{js,jsx,ts,tsx}" output_mode="content"
```

### Schritt 3 — CORS-Konfiguration

```
Grep: pattern="CORS|cors|Access-Control|allow_origins" path="." output_mode="content"
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| CORS konfiguriert | `allow_origins` spezifisch (nicht `*`) | `allow_origins=["*"]` in Produktion |
| Credentials erlaubt | Nur wenn nötig (Cookie-Auth) | `allow_credentials=True` mit `*` Origins |
| Methods eingeschränkt | Nur benötigte Methods | `allow_methods=["*"]` |

---

## Teil 3: Logging & Observability

### Schritt 1 — Logging-Inventar

```
Grep: pattern="import logging|getLogger|logger\." path="assistant/assistant/" output_mode="content" head_limit=30
Grep: pattern="import logging|getLogger|logger\." path="addon/rootfs/opt/mindhome/" output_mode="content" head_limit=20
Grep: pattern="print\(" path="assistant/assistant/" output_mode="content" head_limit=20
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| **Logger statt print()** | Alle Module nutzen `logging.getLogger()` | `print()` für Debug/Error-Output |
| **Log-Level korrekt** | DEBUG für Details, INFO für Flow, WARNING für Probleme, ERROR für Fehler | Alles auf INFO oder DEBUG |
| **Strukturiertes Logging** | JSON oder formatierter Output | Unstrukturierte Strings |
| **Sensitive Daten** | Keine Passwörter/Tokens in Logs | API-Keys, Credentials in Log-Output |
| **Request-ID Tracking** | Jeder Request hat eine ID die durch alle Logs geht | Kein Request-Tracking möglich |
| **Performance-Logging** | Latenz pro Request geloggt | Keine Timing-Information |

```
# Sensitive Daten in Logs suchen
Grep: pattern="logger.*password|logger.*token|logger.*key|logger.*secret|logger.*api_key" -i path="." output_mode="content"
Grep: pattern="print.*password|print.*token|print.*key|print.*secret" -i path="." output_mode="content"
```

### Schritt 2 — Error-Tracking

```
Grep: pattern="except.*:|except:" path="assistant/assistant/" output_mode="content" head_limit=40
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| **Keine bare excepts** | `except SpecificError` überall | `except:` oder `except Exception:` mit `pass` |
| **Errors geloggt** | `logger.error()` oder `logger.exception()` in jedem except | Stille Fehler (`except: pass`) |
| **Stack Traces erhalten** | `logger.exception()` oder `traceback.format_exc()` | Nur Error-Message ohne Stack |
| **Error Rates messbar** | Counter oder Metrik für Fehler | Keine Aggregation möglich |

### Schritt 3 — Health-Monitoring

```
Grep: pattern="health|healthcheck|/health|readiness|liveness" path="." output_mode="content"
Grep: pattern="metrics|prometheus|statsd|datadog" path="." output_mode="content"
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| **Health-Endpoint** | `/health` oder `/healthz` in jedem Service | Kein Health-Check |
| **Dependency-Health** | Health prüft Redis, ChromaDB, Ollama, HA | Nur "200 OK" ohne Dependency-Check |
| **Startup-Probe** | Container hat Startup-Check in docker-compose | Kein healthcheck in compose |
| **Uptime-Tracking** | Service-Startzeit geloggt | Unbekannt wann Service gestartet |

---

## Teil 4: Graceful Degradation (Erweitert)

Über P06d (Resilience) hinaus — prüfe **kombinierte Ausfälle**:

| Szenario | Erwartetes Verhalten | Prüf-Methode |
|---|---|---|
| Redis DOWN + ChromaDB DOWN | Jarvis antwortet trotzdem (ohne Memory) | Prüfe Fallback-Ketten |
| Ollama DOWN + User fragt | Freundliche Fehler-Meldung in < 3s | Prüfe Timeout + Error-Response |
| GPU OOM (2 parallele LLM-Requests) | Zweiter Request queued oder abgelehnt | Prüfe Concurrency-Control |
| Addon DOWN + User will Licht steuern | Klare Fehlermeldung "Smart Home nicht erreichbar" | Prüfe HA-Fallback |
| Speech DOWN + Voice Input | Fehler an HA Voice Pipeline zurück | Prüfe Speech-Error-Path |
| Disk Full + Memory-Write | Kein Crash, Warning geloggt | Prüfe Disk-Space-Check |

```
# Fallback-Ketten finden
Grep: pattern="fallback|graceful|degrad|circuit.?break" path="assistant/assistant/" output_mode="content"
Grep: pattern="try:.*\n.*except.*:.*\n.*fallback\|backup\|default" path="assistant/assistant/" multiline=true output_mode="content" head_limit=20
```

---

## Teil 5: Daten-Persistenz & Backup

### Schritt 1 — Persistenz-Inventar

| Daten-Typ | Storage | Pfad/Key | Backup-Strategie |
|---|---|---|---|
| Conversation History | Redis | ? | ? |
| Semantic Memory | ChromaDB | ? | ? |
| User Preferences | ? | ? | ? |
| Automation Rules | SQLite/DB | ? | ? |
| Addon Config | ? | ? | ? |
| Personality State | ? | ? | ? |

```
# Daten-Pfade finden
Grep: pattern="DATA_DIR|data_dir|db_path|chroma.*path|persist" path="." output_mode="content"
Grep: pattern="volume|volumes:" path="." glob="docker-compose*" output_mode="content"
```

### Schritt 2 — Datenverlust-Szenarien

| Szenario | Was geht verloren? | Recovery? |
|---|---|---|
| Redis-Neustart ohne Persistenz | Conversation History, Session State | ❌ Weg |
| ChromaDB-Volume gelöscht | Alle semantischen Erinnerungen | ❌ Weg |
| Docker-Container gelöscht | Alles ohne Volume-Mount | ❌ Weg |
| Korrupte SQLite-DB | Automation Rules, Addon-State | Backup nötig |
| Host-Neustart | Alles im RAM | Redis RDB/AOF? |

```
# Redis Persistenz-Config prüfen
Grep: pattern="appendonly|save |rdb|aof|persist" path="." glob="redis*" output_mode="content"
Grep: pattern="redis.*config|REDIS.*PERSIST|redis.*save" path="." output_mode="content"
```

---

## Claude Code Tool-Einsatz

| Aufgabe | Tool | Befehl |
|---|---|---|
| Concurrency-Patterns finden | **Grep** | `pattern="Lock\|Semaphore\|Queue"` |
| Frontend-Dateien finden | **Glob** | `pattern="**/*.{js,jsx,html}"` |
| Logging analysieren | **Grep** | `pattern="logger\.\|print\("` |
| Health-Endpoints finden | **Grep** | `pattern="health\|/health"` |
| Docker Volumes prüfen | **Read** | docker-compose Dateien |
| Redis-Config prüfen | **Grep** | `pattern="redis.*persist"` |

---

## Erfolgskriterien

- □ Multi-User Sicherheit bewertet — Race Conditions identifiziert
- □ GPU-Concurrency geprüft — Schutz vorhanden oder empfohlen
- □ Frontend analysiert — XSS, CORS, API-Match, Error Handling
- □ Logging-Qualität bewertet — Stille Fehler, Sensitive Data, Struktur
- □ Health-Monitoring geprüft — alle Services haben Health-Endpoints
- □ Kombinierte Ausfälle analysiert — Fallback-Ketten dokumentiert
- □ Datenpersistenz geprüft — Backup-Strategie bewertet

```
Checkliste:
□ Request-Isolation verifiziert
□ LLM-Concurrency geschützt
□ Frontend XSS/CORS sicher
□ Logging strukturiert, keine sensitive Daten
□ Health-Endpoints in allen Services
□ Daten-Persistenz gesichert (Redis, ChromaDB, SQLite)
□ Kombinierte Ausfälle getestet
□ Backup-Strategie dokumentiert (Redis RDB/AOF, ChromaDB Snapshots, SQLite-Kopie)
□ Restore-Prozedur getestet (Backup einspielen → System funktioniert)
□ Datenaufbewahrung/GDPR: Löschfristen definiert, User-Daten exportierbar, Recht auf Vergessen
□ Log-Rotation konfiguriert (keine unbegrenzten Logs auf Produktivsystem)
□ Sensitive Daten in Logs gefiltert (API-Keys, Tokens, Passwörter)
□ Health-Endpoints explizit getestet (/health, /ready, /health/deep in allen 3 Services)
□ Graceful Shutdown (SIGTERM → laufende Requests abschließen → sauber beenden)
□ Frontend Accessibility (Screenreader, Tastatur-Navigation, Kontrast — WCAG 2.1 AA)
□ Frontend Mobile-Responsiveness (Breakpoints 768px, 480px funktionieren)
□ Memory-Deduplication (ChromaDB: keine doppelten Fakten gespeichert)
□ Secrets-Management (keine Secrets in Code/Config, nur in .env oder HA Secrets)
```

---

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_08b_BETRIEB.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

---

## Output

Am Ende erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
THEMA: Betrieb (Multi-User, Frontend, Monitoring, Persistenz)

MULTI-USER:
- Request-Isolation: [JA/NEIN + Details]
- Brain Singleton: [THREAD-SAFE/UNSICHER]
- LLM-Queue: [VORHANDEN/FEHLT]
- Race Conditions: [Anzahl gefunden]

FRONTEND:
- XSS-Risiken: [Anzahl]
- CORS: [KORREKT/ZU OFFEN]
- API-Match: [Anzahl Mismatches]
- WebSocket-Reconnect: [JA/NEIN]

LOGGING:
- print() statt logger: [Anzahl]
- Stille Fehler (except: pass): [Anzahl]
- Sensitive Daten in Logs: [Anzahl]
- Request-ID Tracking: [JA/NEIN]
- Health-Endpoints: [Anzahl Services mit/ohne]

PERSISTENZ:
- Redis-Persistenz: [RDB/AOF/KEINE]
- ChromaDB-Volume: [MOUNTED/NICHT MOUNTED]
- Backup-Strategie: [VORHANDEN/FEHLT]

GRACEFUL DEGRADATION (kombiniert):
- [Szenario]: [BESTANDEN/FEHLT]

GEFIXT: [Liste der Fixes mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste]
===================================
```
