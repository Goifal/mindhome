# Prompt 4c: Systematische Bug-Jagd — Addon + Security + Performance

## Rolle

Du bist ein Elite-Debugging-Experte für Python, AsyncIO, FastAPI, Flask, Redis, ChromaDB und Home Assistant. Du findest Bugs die andere übersehen — fehlende awaits, stille Exceptions, Race Conditions, Type-Fehler, Security-Lücken.

---

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Kurzfassung: Thinking-Mode bei Tool-Calls deaktivieren (`supports_think_with_tools: false`), `character_hint` in model_profiles nutzen.

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode, nicht mit einem laufenden System.

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Analyse-Prompts:

```
Read: docs/audit-results/RESULT_01_KONFLIKTKARTE.md
Read: docs/audit-results/RESULT_04a_BUGS_CORE.md
Read: docs/audit-results/RESULT_04b_BUGS_EXTENDED.md
```

> Falls eine Datei nicht existiert → überspringe sie. Wenn KEINE Result-Dateien existieren, nutze Kontext-Blöcke aus der Konversation oder starte mit Prompt 01.
>
> **⚠️ OHNE diese Kontext-Blöcke fehlt dir das Bild der bisherigen Bugs!** Die Security-Analyse hier baut auf den Findings aus 4a/4b auf.

---

## Aufgabe

Prüfe die **Addon-Module, Speech, Shared-Module** (Priorität 10–12) und führe den **Security-Audit** und die **Performance-Analyse** durch.

> **Dieser Prompt ist Teil 3 von 3** der Bug-Jagd:
> - **P04a**: Core-Module — ✅ erledigt
> - **P04b**: Extended-Module — ✅ erledigt
> - **P04c** (dieser): Addon + Security-Audit + Performance-Analyse — Priorität 10–12

---

## Teil 1: Addon-Module (Priorität 10)

79. `addon/rootfs/opt/mindhome/app.py` — Flask-App
80. `addon/rootfs/opt/mindhome/ha_connection.py` — HA-Anbindung
81. `addon/rootfs/opt/mindhome/event_bus.py` — Event-Bus
82. `addon/rootfs/opt/mindhome/automation_engine.py` — Automationen
83. `addon/rootfs/opt/mindhome/pattern_engine.py` — Pattern-Matching
84. `addon/rootfs/opt/mindhome/task_scheduler.py` — Task-Scheduling
85. `addon/rootfs/opt/mindhome/helpers.py`, `cover_helpers.py`, `init_db.py`, `version.py` — Hilfsdateien
86. `addon/rootfs/opt/mindhome/domains/*.py` — Alle Domain-Module (21 Dateien)
87. `addon/rootfs/opt/mindhome/engines/*.py` — Alle Engine-Module (15 Dateien)
88. `addon/rootfs/opt/mindhome/routes/*.py` — Alle Route-Module (17 Dateien)

> **Arbeite in 3 Batches:**
> - **Batch 14a** (Addon-Kern): `app.py`, `ha_connection.py`, `event_bus.py`, `automation_engine.py`, `pattern_engine.py`, `task_scheduler.py`, `base.py`, `models.py`, `db.py`, `helpers.py`, `cover_helpers.py`, `init_db.py`, `version.py`
> - **Batch 14b** (Addon-Domains+Engines): Alle `domains/*.py` + `engines/*.py`
> - **Batch 14c** (Addon-Routes): Alle `routes/*.py` — API-Endpoints prüfen (Auth, Validierung, Error Handling)

**Prüfe für jedes Addon-Modul alle 13 Fehlerklassen**, besonders:
- Nutzt der Addon die **Shared Schemas** (`shared/schemas/`) oder eigene Definitionen?
- Nutzt der Addon die **Shared Constants** (`shared/constants.py`) für Ports?
- Gibt es **Duplikate** zwischen Addon-Domains und Assistant-Modulen? (z.B. `addon/domains/light.py` vs `assistant/light_engine.py`)

---

## Teil 2: Speech-Server (Priorität 11)

86. `speech/server.py`
87. `speech/handler.py`

---

## Teil 3: Shared-Module & HA-Integration (Priorität 12)

88. `shared/constants.py` — Stimmen die Port-Definitionen mit den tatsächlich genutzten Ports überein?
89. `shared/schemas/chat_request.py` — Wird `ChatRequest` überall verwendet wo Requests gesendet werden?
90. `shared/schemas/chat_response.py` — Wird `ChatResponse` überall verwendet wo Responses erzeugt werden?
91. `shared/schemas/events.py` — Werden die Event-Typen konsistent genutzt?
92. `ha_integration/.../config_flow.py` — Validierung, Error Handling
93. `ha_integration/.../__init__.py` — Setup/Teardown korrekt?

### Shared Schema Verification (Pflicht!)

Für **jedes** der 3 Shared Schemas (`ChatRequest`, `ChatResponse`, `MindHomeEvent`):

**Schritt 1 — Import-Prüfung:**
```
Grep: pattern="from shared.schemas import|from shared.schemas." path="." output_mode="content"
Grep: pattern="ChatRequest" path="." output_mode="content"
Grep: pattern="ChatResponse" path="." output_mode="content"
Grep: pattern="MindHomeEvent" path="." output_mode="content"
```

**Schritt 2 — Duplikat-Prüfung:**
```
Grep: pattern="class ChatRequest|class ChatResponse|class MindHomeEvent" path="." output_mode="content"
```

**Schritt 3 — Port/Konstanten-Konsistenz:**
```
Grep: pattern="from shared.constants import|from shared import constants" path="." output_mode="content"
Grep: pattern="port.*=.*[0-9]{4}" path="." output_mode="content" glob="*.py"
```

**Pass/Fail Kriterien:**

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| Import-Quelle | Alle Services importieren aus `shared/schemas/` | Service definiert eigene Klasse oder importiert aus anderem Pfad |
| Feld-Konsistenz | `ChatRequest` hat identische Felder in Assistant + Addon + Speech | Felder weichen ab (z.B. Addon hat `extra_field` das Assistant nicht kennt) |
| Port-Konsistenz | Alle Services nutzen `shared/constants.py` für Ports | Hardcoded Ports (z.B. `port=5000` statt `ADDON_PORT`) |
| Event-Typen | `MindHomeEvent` Enum-Werte werden konsistent genutzt | String-Literale statt Enum (z.B. `"light_on"` statt `MindHomeEvent.LIGHT_ON`) |
| Serialisierung | Gleiche JSON-Serialisierung in allen Services | Ein Service nutzt `.dict()`, anderer `.model_dump()` oder manuelles Dict |

> **Jeder FAIL ist ein 🟠 HOCH Bug.** Zwei oder mehr FAILs für dasselbe Schema → 🔴 KRITISCH.

---

## Teil 4: Security-Audit (KRITISCH!)

Prüfe **alle** diese Security-Checks:

| # | Security-Check | Modul | Was prüfen |
|---|---|---|---|
| 1 | Prompt Injection | `context_builder.py` | Wird User-Input sanitized bevor er im System-Prompt landet? |
| 2 | Input Validation | `main.py`, `websocket.py` | Werden API-Inputs validiert? (**200+ Endpoints in main.py!**) |
| 3 | HA-Auth | `ha_client.py` | Werden Credentials sicher gehandhabt? |
| 4 | Function Call Safety | `function_calling.py`, `function_validator.py` | Können bösartige Tool-Calls ausgeführt werden? |
| 5 | Self-Automation Safety | `self_automation.py` | Kann Jarvis gefährliche HA-Automationen generieren? |
| 6 | Autonomy Limits | `autonomy.py` | Gibt es harte Grenzen für autonome Aktionen? |
| 7 | Threat Assessment | `threat_assessment.py` | Funktioniert es? Wird es genutzt? |
| 8 | **Factory Reset** | `main.py` | Endpoint `/api/ui/factory-reset`: (1) Braucht `trust_level >= 3`? (2) Braucht Bestaetigungscode (OTP/PIN/Recovery-Key)? (3) Wird User benachrichtigt? Grep: `pattern="factory.reset" path="assistant/assistant/main.py" output_mode="content"` |
| 9 | **System Update/Restart** | `main.py` | Sind `/api/ui/system/update` und `/restart` geschützt? |
| 10 | **API-Key Management** | `main.py` | Ist `/api/ui/api-key/regenerate` geschützt? Recovery-Key-Logik sicher? |
| 11 | **PIN-Auth** | `main.py` | Ist die PIN-Authentifizierung (`/api/ui/auth`) sicher? Brute-Force-Schutz? |
| 12 | **File Upload** | `main.py`, `file_handler.py`, `ocr.py` | Path Traversal, Injection über Dateinamen, Dateigröße, MIME-Type? |
| 13 | **Workshop Hardware** | `main.py` | Sind `/api/workshop/arm/*` und `/api/workshop/printer/*` Trust-Level-geschützt? |
| 14 | **Sensitive Data in Logs** | `main.py` | Werden API-Keys/Tokens in Error/Activity Buffer redacted? Grep: `pattern="api.key\|api_key\|token\|password" path="assistant/assistant/main.py" output_mode="content"` → pruefen ob jeder Match ein `redact\|redacted\|****` hat |
| 15 | **WebSearch SSRF** | `web_search.py` | IP-Blocklist, DNS-Rebinding-Check, URL-Validierung |
| 16 | **Frontend XSS** | `addon/.../app.jsx`, `assistant/.../app.js` | Werden API-Responses escaped? User-Input in DOM? |
| 17 | **CORS** | `main.py`, `addon/app.py` | CORS-Headers korrekt? Zu permissiv (allow-origin: *)? |
| 18 | **Dependency-CVEs** | `requirements.txt` (alle 3) | `pip-audit` mit Bash ausführen |

---

## Teil 5: Resilience-Checks

| # | Szenario | Was sollte passieren | Was passiert? | Code-Referenz |
|---|---|---|---|---|
| 1 | Ollama nicht erreichbar | Graceful Error, User informieren | ? | ? |
| 2 | Redis nicht erreichbar | Degraded Mode ohne Memory | ? | ? |
| 3 | ChromaDB nicht erreichbar | Fallback auf Redis-only | ? | ? |
| 4 | Home Assistant nicht erreichbar | Fehlermeldung, kein Crash | ? | ? |
| 5 | Speech-Server nicht erreichbar | Text-only Mode | ? | ? |
| 6 | Addon nicht erreichbar | Assistant funktioniert standalone | ? | ? |
| 7 | Netzwerk-Timeout bei LLM-Call | Retry mit Backoff? Timeout-Wert? | ? | ? |
| 8 | Ungültiges LLM-Response-Format | Parsing-Fehler abfangen | ? | ? |
| 9 | `circuit_breaker.py` | Wird es überhaupt genutzt? Von welchen Modulen? | ? | ? |
| 10 | `error_patterns.py` | Werden Fehler klassifiziert? | ? | ? |

---

## Teil 6: Performance & Latenz-Analyse

> **Jarvis muss schnell antworten.** Ziel: < 3 Sekunden für einfache Befehle.

### Latenz-Budget

| Phase | Ziel | Was prüfen |
|---|---|---|
| Request Parsing + Pre-Classification | < 50ms | Wird `pre_classifier.py` synchron oder async? |
| Context Building (Memory + State) | < 200ms | Werden Memory-Abfragen **parallel** gemacht? |
| LLM-Inference (Ollama) | < 2000ms | Wird das richtige Modell gewählt? |
| Function Calling + HA-API | < 500ms | Timeouts? Parallele Calls? |
| Response Processing + TTS | < 200ms | Streaming oder Batch? |
| **Gesamt** | **< 3000ms** | End-to-End |

### Performance-Checks

| # | Check | Modul | Was prüfen |
|---|---|---|---|
| 1 | Sequentielle statt parallele Async-Calls | `brain.py`, `context_builder.py` | `await a(); await b()` statt `asyncio.gather(a(), b())`? |
| 2 | Überflüssige LLM-Calls | `brain.py`, `pre_classifier.py`, `mood_detector.py` | Wird LLM mehrfach pro Request aufgerufen? |
| 3 | Model-Routing-Effizienz | `model_router.py` | Einfache Befehle → schnellstes Modell? |
| 4 | Memory-Abfrage-Latenz | `memory.py`, `semantic_memory.py` | Redis-Roundtrips? ChromaDB-Query-Zeit? Cache? |
| 5 | Context Builder Overhead | `context_builder.py` | Wie viele HA-API-Calls pro Request? Parallelisiert? |
| 6 | Startup-Latenz | `main.py`, `brain.py` | Wie lange dauert der Boot? Lazy oder eager? |
| 7 | Embedding-Berechnung | `embeddings.py`, `embedding_extractor.py` | Gecacht oder jedes Mal neu? Welches Modell? |
| 8 | Token-Verschwendung | `context_builder.py`, `personality.py` | System-Prompt-Größe? Effizienter Kontext? |
| 9 | Proaktive Hintergrund-Last | `proactive.py`, `learning_observer.py` | CPU/Memory-Verbrauch im Hintergrund? |
| 10 | Addon-Roundtrip | `ha_client.py`, Addon API | Latenz der HTTP-Calls? Caching? |
| 11 | Streaming vs. Batch | `websocket.py`, `ollama_client.py` | Token-Streaming aktiv? |
| 12 | Unnötige Serialisierung | Überall | JSON-Overhead bei internen Calls? |

### Grep für Performance-Probleme

```
# Sequentielle awaits die parallel sein könnten
Grep: pattern="await self\." path="assistant/assistant/brain.py" output_mode="content"
Grep: pattern="await self\." path="assistant/assistant/context_builder.py" output_mode="content"

# asyncio.gather Nutzung (gut!)
Grep: pattern="asyncio\.gather" path="assistant/assistant/" output_mode="content"

# LLM-Aufrufe pro Request zählen
Grep: pattern="ollama_client|generate|chat_completion" path="assistant/assistant/brain.py" output_mode="content"

# Cache-Nutzung
Grep: pattern="cache|_cache|lru_cache|ttl_cache" path="assistant/assistant/" output_mode="content"

# Timeouts
Grep: pattern="timeout" path="assistant/assistant/" output_mode="content"
```

### Bash für Security-Check

```bash
# Dependency-CVEs prüfen
cd assistant && pip install pip-audit 2>/dev/null && pip-audit -r requirements.txt 2>&1 | head -30
cd ../addon/rootfs/opt/mindhome && pip-audit -r requirements.txt 2>&1 | head -30
cd ../../../../speech && pip-audit -r requirements.txt 2>&1 | head -30
```

---

## Output-Format

### Bug-Report-Tabelle (Addon + Shared + Speech)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|---|---|---|---|---|---|

### Security-Report

| # | Risiko | Modul | Beschreibung | Empfehlung |
|---|---|---|---|---|

### Resilience-Report (ausgefüllt)

### Performance-Report

| # | Check | Ergebnis | Modul:Zeile | Empfehlung |
|---|---|---|---|---|

**Geschätzte Latenz (Haupt-Flow):**
| Phase | Geschätzt | Ziel | Status |
|---|---|---|---|
| Pre-Classification | ?ms | <50ms | ✅/⚠️/❌ |
| Context Building | ?ms | <200ms | ✅/⚠️/❌ |
| LLM-Inference | ?ms | <2000ms | ✅/⚠️/❌ |
| Function Execution | ?ms | <500ms | ✅/⚠️/❌ |
| Response Processing | ?ms | <200ms | ✅/⚠️/❌ |
| **Gesamt** | **?ms** | **<3000ms** | ✅/⚠️/❌ |

### Dead-Code-Liste (gesamt aus 4a + 4b + 4c)

### Gesamtstatistik (alle 3 Prompts)

```
Gesamt: X Bugs (alle Prioritäten)
  🔴 KRITISCH: X (aus 4a: X, 4b: X, 4c: X)
  🟠 HOCH: X
  🟡 MITTEL: X
  🟢 NIEDRIG: X

Security-Findings: X
Resilience-Lücken: X
Performance-Probleme: X
```

---

## Regeln

- **Addon-Module NICHT vergessen** — sie haben eigene Bugs und eigene HA-Integration
- **Security-Bugs sind immer KRITISCH**
- **Jeder Bug mit Code-Referenz** (Datei:Zeile)
- **Nicht fixen** — nur dokumentieren (Fixes in P6a–6d)

---

## Erfolgskriterien

- Alle Addon-Module gelesen, Bugs nach 13 Fehlerklassen kategorisiert
- Security-Audit: Alle 18 Security-Checks (Teil 4) durchgeführt und dokumentiert
- Performance/Latenz: Alle 12 Performance-Checks (Teil 6) durchgeführt. Latenz-Schätzungen basieren auf Code-Analyse (Anzahl await-Ketten, LLM-Calls pro Request), nicht auf Laufzeitmessungen.
- Addon ↔ Assistant Interaktion geprueft

### Erfolgs-Check (Schnellpruefung)

```
□ Addon-Module gelesen: grep "def " addon/rootfs/opt/mindhome/app.py | wc -l
□ Security-Checks: grep "eval\|exec\|os.system\|subprocess" addon/ -r
□ SQL-Injection geprueft: grep "f\".*SELECT\|format.*SELECT" addon/ -r
□ Auth-Check: grep "api_key\|auth\|token\|secret" addon/rootfs/opt/mindhome/app.py
□ Thread-Safety: grep "threading\|Lock\|global " addon/rootfs/opt/mindhome/ -r | wc -l
□ Frontend-Security: grep "innerHTML\|eval\|document\.write" ha_integration/ -r
```

---

## ⚡ Übergabe an Prompt 5

Formatiere am Ende einen kompakten **Kontext-Block** für Prompt 5:

```
## KONTEXT AUS PROMPT 4 (gesamt: 4a + 4b + 4c): Bug-Report

### Statistik
Gesamt: X Bugs (🔴 X, 🟠 X, 🟡 X, 🟢 X)

### Kritische Bugs (🔴)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Hohe Bugs (🟠)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Security-Report
[Findings mit Severity]

### Resilience-Report
[Welche Ausfälle abgefangen werden, welche nicht]

### Performance-Report
[Geschätzte Latenz, kritische Bottlenecks]

### Dokumentations-Verifikation
[Welche behaupteten Fixes stimmen, welche nicht]

### Dead-Code-Liste
[Module/Funktionen die nie aufgerufen werden]
```

**Wenn du Prompt 5 in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1–4c) automatisch ein.

---

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_04c_BUGS_ADDON_SECURITY.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
