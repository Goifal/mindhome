# Prompt 7: Testing, Resilience & Deployment-Verifikation

## Rolle

Du bist ein Elite-DevOps-Engineer und QA-Experte mit tiefem Wissen in:

- **Python Testing**: pytest, pytest-asyncio, Mocking, Fixtures, Coverage, Integration Tests
- **Docker**: Multi-Container-Setups, docker-compose, Health Checks, Networking, Volume-Mounts
- **Resilience Engineering**: Circuit Breaker, Graceful Degradation, Retry-Strategien, Health Monitoring
- **CI/CD**: Test-Automation, Build-Pipelines, Deployment-Strategien

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6d bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke aus allen vorherigen Prompts ein:
> - Prompt 1: Konflikt-Karte & Architektur-Bewertung (3-Service-Architektur!)
> - Prompt 2: Memory-Diagnose & Root Cause
> - Prompt 3: Flow-Analyse mit Bruchstellen (13 Flows)
> - Prompt 4: Bug-Report mit allen Bugs + Security + Resilience + **Performance**
> - Prompt 5: Persönlichkeits-Audit & Config
> - Prompt 6a: Stabilisierung (Kritische Bugs + Memory)
> - Prompt 6b: Architektur (Konflikte + Flows + Performance)
> - Prompt 6c: Charakter (Persönlichkeit + Config + Dead Code)
> - Prompt 6d: Härtung (Security + Resilience + Addon-Koordination)

---

## Aufgabe

Nach den Fixes aus Prompt 6a–6d: **Verifiziere** dass alles funktioniert, **teste** systematisch, **miss die Latenz**, und stelle sicher dass das Deployment **robust** ist.

### Zusätzliche Dokumentation (lies diese zuerst!):
- `docs/ASSISTANT_TEST_CHECKLIST.md` — Bestehende Test-Checkliste (falls vorhanden, als Basis nutzen)
- `docs/AUDIT_OPERATIONAL_RELIABILITY.md` — Vorherige Reliability-Analyse (was wurde schon geprüft?)
- `docs/AUDIT_TTS_STT.md` — Speech-System-Audit (relevant für Speech-Tests)

---

### Teil A: Bestehende Tests ausführen und bewerten

**Schritt 1** — Tests laufen lassen (**Claude Code: Mit Bash-Tool ausführen!**):
```bash
# AUSFÜHREN mit Bash-Tool — nicht nur lesen!
cd assistant && python -m pytest --tb=short -q 2>&1 | tail -50
```

> Falls pytest nicht installiert ist: `cd assistant && pip install -r requirements.txt && pip install pytest pytest-asyncio`

**Schritt 2** — Ergebnisse analysieren:

| Metrik | Wert |
|---|---|
| Tests gesamt | ? |
| Bestanden | ? |
| Fehlgeschlagen | ? |
| Übersprungen | ? |
| Errors | ? |
| Laufzeit | ? |

**Schritt 3** — Fehlgeschlagene Tests kategorisieren:

| Test | Fehler-Typ | Ursache | Fix nötig in Test oder Code? |
|---|---|---|---|
| ? | ? | ? | ? |

**Schritt 4** — Test-Coverage bewerten:

| Modul-Bereich | Tests vorhanden? | Abdeckung |
|---|---|---|
| brain.py (Orchestrator) | ? | ? |
| Memory-Kette (7 Module) | ? | ? |
| Function Calling | ? | ? |
| Persönlichkeit | ? | ? |
| Proaktive Systeme | ? | ? |
| Speech Pipeline | ? | ? |
| **Addon-Module** | ? | ? |
| **Integration zwischen Services** | ? | ? |

### Teil B: Kritische Test-Lücken schließen

Basierend auf Prompt 3 (Flows) und Prompt 4 (Bugs) — prüfe ob es Tests gibt für:

| Szenario | Test existiert? | Datei | Status |
|---|---|---|---|
| Sprach-Input → Antwort (E2E) | ? | ? | ? |
| Memory speichern → Memory abrufen | ? | ? | ? |
| Function Calling → HA-Aktion | ? | ? | ? |
| Proaktive Benachrichtigung | ? | ? | ? |
| Morgen-Briefing E2E | ? | ? | ? |
| Autonome Aktion mit Level-Check | ? | ? | ? |
| Concurrent Requests (Race Condition) | ? | ? | ? |
| Ollama Timeout / Nicht erreichbar | ? | ? | ? |
| Redis nicht erreichbar | ? | ? | ? |
| ChromaDB nicht erreichbar | ? | ? | ? |
| HA nicht erreichbar | ? | ? | ? |
| Prompt Injection Schutz | ? | ? | ? |
| Speaker Recognition → korrekter User | ? | ? | ? |
| Addon + Assistant gleichzeitige Aktion | ? | ? | ? |

#### Security-Endpoint-Tests (Pflicht — aus P04 Sicherheits-Findings!)

> ⚠️ P04 identifiziert kritische Endpoints (Factory-Reset, System-Restart, API-Key-Regeneration). P06d soll sie absichern. Hier **verifizieren** wir dass die Absicherung funktioniert.

| Endpoint | Unauthenticated → 401? | Auth-geschützt? | Brute-Force-Schutz? | Test-Status |
|---|---|---|---|---|
| `/api/ui/factory-reset` | ? | ? | ? | ? |
| `/api/ui/system/update` | ? | ? | ? | ? |
| `/api/ui/system/restart` | ? | ? | ? | ? |
| `/api/ui/api-key/regenerate` | ? | ? | ? | ? |
| `/api/ui/auth` (PIN-Login) | ? | ? | ? | ? |

**Prüf-Strategie:**
1. **Grep** — `pattern="factory.reset|system.restart|api.key.*regenerate" path="assistant/assistant/main.py"` → Finde die Endpoint-Definitionen
2. **Read** — Lies die Endpoint-Handler: Ist Auth-Middleware vorhanden? Wird Trust-Level geprüft?
3. **Test schreiben** — Für jeden Endpoint: unauthenticated Request muss mit 401/403 abgelehnt werden
4. **Brute-Force** — Für `/api/ui/auth`: Prüfe ob nach N fehlgeschlagenen Versuchen Rate-Limiting greift (HTTP 429 oder Lockout)

```python
# Beispiel-Test für Security-Endpoints
async def test_factory_reset_requires_auth():
    """Factory-Reset ohne Auth muss abgelehnt werden."""
    async with AsyncClient(app=app) as client:
        response = await client.post("/api/ui/factory-reset")
        assert response.status_code in (401, 403), \
            f"Factory-Reset ohne Auth erlaubt! Status: {response.status_code}"

async def test_pin_auth_rate_limiting():
    """Nach 10 falschen PIN-Versuchen: Rate-Limiting aktiv."""
    async with AsyncClient(app=app) as client:
        for i in range(10):
            await client.post("/api/ui/auth", json={"pin": f"wrong_{i}"})
        response = await client.post("/api/ui/auth", json={"pin": "wrong_11"})
        assert response.status_code == 429, \
            f"Kein Rate-Limiting nach 10 Fehlversuchen! Status: {response.status_code}"
```

Für **jedes fehlende kritische Szenario**: **Schreibe einen Test mit dem Write/Edit-Tool** und führe ihn sofort mit Bash aus:
```bash
cd assistant && python -m pytest tests/test_neuer_test.py -v 2>&1
```

### Teil C: Docker & Deployment Verifikation

**Schritt 1** — Docker-Konfiguration prüfen:

Lies und prüfe:
- `assistant/Dockerfile` — Build-Steps korrekt? Dependencies vollständig?
- `assistant/docker-compose.yml` — Services, Volumes, Networking
- `assistant/docker-compose.gpu.yml` — GPU-Variante
- `speech/Dockerfile.whisper` — Whisper-Setup
- `addon/Dockerfile` — Addon-Build
- `addon/build.yaml` — Build-Config

| Check | Status | Problem |
|---|---|---|
| Assistant Dockerfile baut fehlerfrei | ? | ? |
| Speech Dockerfile baut fehlerfrei | ? | ? |
| Addon Dockerfile baut fehlerfrei | ? | ? |
| docker-compose startet alle Services | ? | ? |
| Services können sich gegenseitig erreichen | ? | ? |
| Volumes sind korrekt gemountet | ? | ? |
| Health-Checks definiert? | ? | ? |
| Restart-Policy korrekt? | ? | ? |
| Environment-Variablen vollständig? (.env.example) | ? | ? |
| GPU-Compose funktioniert (nvidia-runtime)? | ? | ? |

**Schritt 2** — Startup-Reihenfolge:

| Service | Abhängig von | Startup-Order korrekt? | Wartet auf Dependencies? |
|---|---|---|---|
| Redis | - | ? | - |
| ChromaDB | - | ? | - |
| Ollama | - (GPU) | ? | - |
| Speech-Server | - | ? | - |
| Assistant | Redis, ChromaDB, Ollama | ? | ? |
| Addon | Home Assistant, ggf. Assistant | ? | ? |

**Frage**: Gibt es `depends_on` / `healthcheck` Konfigurationen? Oder starten alle blind gleichzeitig?

**Schritt 3** — Graceful Shutdown:

| Service | Signal-Handling? | Offene Connections aufräumen? | Redis-State persistiert? |
|---|---|---|---|
| Assistant | ? | ? | ? |
| Addon | ? | ? | ? |
| Speech | ? | ? | ? |

### Teil D: Resilience-Verifikation

Simuliere (gedanklich oder per Code) diese Ausfallszenarien:

| # | Szenario | Erwartetes Verhalten | Tatsächlich | Code-Referenz |
|---|---|---|---|---|
| 1 | **Ollama crasht** während LLM-Call | Timeout → User informieren → kein Crash | ? | ? |
| 2 | **Ollama crasht** beim Start | Assistant startet degraded | ? | ? |
| 3 | **Redis crasht** | Memory degraded, aber Antworten funktionieren | ? | ? |
| 4 | **ChromaDB crasht** | Langzeit-Memory degraded | ? | ? |
| 5 | **Home Assistant nicht erreichbar** | Function Calls fehlschlagen → User informieren | ? | ? |
| 6 | **Speech-Server crasht** | Text-Interface funktioniert weiter | ? | ? |
| 7 | **Addon crasht** | Assistant funktioniert standalone | ? | ? |
| 8 | **Netzwerk-Partition** zwischen Services | Graceful Degradation | ? | ? |
| 9 | **Disk voll** | Logging, ChromaDB, Redis Persistence | ? | ? |
| 10 | **OOM (Out of Memory)** | LLM-Inference auf schwacher Hardware | ? | ? |

**Prüfe für jedes Szenario**:
- Wird `circuit_breaker.py` genutzt?
- Gibt es Retry-Logik? (Mit Backoff?)
- Gibt es Fallback-Verhalten?
- Wird der User informiert oder stirbt Jarvis still?

### Teil E: Performance & Latenz-Verifikation (NEU)

> **Jarvis muss schnell antworten.** Ziel: < 3 Sekunden für einfache Befehle ("Licht an").

**Schritt 1** — Latenz-relevante Code-Pfade prüfen:

| Phase | Ziel-Latenz | Was prüfen | Tool |
|---|---|---|---|
| Context Building | < 200ms | Werden Memory + HA-State parallel geladen? | **Grep**: `pattern="asyncio\.gather" path="assistant/assistant/context_builder.py"` |
| LLM-Inference | < 2000ms | Model-Routing: Einfache Befehle → schnelles Modell? | **Read**: `model_router.py` |
| Function Execution | < 500ms | HA-API-Timeouts korrekt? Parallele Calls? | **Read**: `ha_client.py` |
| Response Streaming | Sofort | Token-Streaming aktiv oder Batch? | **Grep**: `pattern="stream|emit_stream" path="assistant/assistant/"` |

**Schritt 2** — Performance-Antipatterns verifizieren (aus Prompt 4):

| Antipattern | Behoben in 6b? | Verifizieren |
|---|---|---|
| Sequentielle awaits statt asyncio.gather | ? | Grep für gather in brain.py, context_builder.py |
| Mehrere LLM-Calls pro Request | ? | Grep für ollama_client-Aufrufe in brain.py |
| Großes Modell für einfache Befehle | ? | Read model_router.py — Routing-Logik |
| Embeddings ohne Cache | ? | Grep für cache in embeddings.py |
| Übergroßer System-Prompt | ? | Token-Count des Prompts |

**Schritt 3** — Falls pytest verfügbar, Performance-Test schreiben:

```python
# Einfacher Latenz-Test (Smoke Test)
import time
async def test_simple_command_latency():
    """Ein einfacher Befehl sollte < 3 Sekunden dauern."""
    start = time.monotonic()
    # Simuliere: "Mach das Licht im Wohnzimmer an"
    # ... (mock Ollama, HA, Redis)
    elapsed = time.monotonic() - start
    assert elapsed < 3.0, f"Einfacher Befehl dauerte {elapsed:.1f}s (Ziel: <3s)"
```

### Teil F: Monitoring & Observability

| Check | Status | Details |
|---|---|---|
| Logging konfiguriert (Level, Format, Rotation)? | ? | ? |
| Structured Logging oder Freitext? | ? | ? |
| Health-Endpoints vorhanden? (`/health`, `/ready`) | ? | ? |
| Metriken gesammelt (Response-Time, Error-Rate)? | ? | ? |
| `diagnostics.py` — Was macht es? Wird es genutzt? | ? | ? |
| `self_report.py` — Generiert es nützliche Reports? | ? | ? |
| Alerts bei kritischen Fehlern? | ? | ? |
| Log-Rotation konfiguriert (Container-Logs wachsen!)? | ? | ? |

### Teil G: Installationsscripts prüfen

**Zuerst prüfen welche Scripts existieren** (nicht alle müssen vorhanden sein):
```
Glob: pattern="**/*.sh" path="assistant/"
Glob: pattern="**/*.sh" path="addon/"
Glob: pattern="*.sh"
Glob: pattern="repository.yaml"
```

Lies und prüfe **(nur falls vorhanden!)**:
- `assistant/install.sh` — Installiert es korrekt?
- `assistant/update.sh` — Update-Logik robust?
- `assistant/nvidia-watchdog.sh` — GPU-Monitoring
- `install-nvidia-toolkit.sh` — GPU-Setup
- `addon/rootfs/opt/mindhome/run.sh` — Addon-Startscript korrekt?
- `repository.yaml` — HA-Repository-Config vollständig?

> **Nicht-existierende Scripts dokumentieren als "nicht vorhanden"** — das ist selbst ein Finding (fehlende Install-Automation).

| Script | Funktioniert? | Edge Cases abgedeckt? | Idempotent? |
|---|---|---|---|
| install.sh | ? | ? | ? |
| update.sh | ? | ? | ? |
| nvidia-watchdog.sh | ? | ? | ? |
| addon/run.sh | ? | ? | ? |

### Teil H: Dependency-Audit (NEU)

**Claude Code: Mit Bash ausführen!**

```bash
# Dependency-Security-Check für alle 3 Services
cd assistant && pip install pip-audit 2>/dev/null && pip-audit -r requirements.txt 2>&1 | head -30
cd ../addon/rootfs/opt/mindhome && pip-audit -r requirements.txt 2>&1 | head -30
cd ../../../../speech && pip-audit -r requirements.txt 2>&1 | head -30
```

| Check | Status | Details |
|---|---|---|
| Assistant requirements.txt — bekannte CVEs? | ? | ? |
| Addon requirements.txt — bekannte CVEs? | ? | ? |
| Speech requirements.txt — bekannte CVEs? | ? | ? |
| Version-Pinning (alle Deps gepinnt?) | ? | ? |
| Konflikte zwischen Services (gleiche Lib, verschiedene Versionen?) | ? | ? |
| Veraltete Dependencies (>1 Jahr ohne Update?) | ? | ? |

### Teil I: Frontend-Dateien prüfen (NEU)

Lies und prüfe:
- `addon/rootfs/opt/mindhome/static/frontend/app.jsx` — React-Frontend
- `assistant/static/ui/app.js` — Assistant-UI

| Check | Status | Details |
|---|---|---|
| XSS-Schutz (User-Input escaped?) | ? | ? |
| API-Endpoints korrekt (passen zu main.py/app.py?) | ? | ? |
| Error-Handling (was wenn API nicht erreichbar?) | ? | ? |
| Auth-Token-Handling (sicher gespeichert?) | ? | ? |

---

## Output-Format

### 1. Test-Report

```
Tests gesamt: X
  ✅ Bestanden: X
  ❌ Fehlgeschlagen: X (Liste mit Ursachen)
  ⏭️ Übersprungen: X

Test-Coverage-Lücken: [Liste]
Neue Tests geschrieben: [Liste]
```

### 2. Deployment-Report

```
Docker-Build: ✅/❌
Service-Start: ✅/❌
Service-Kommunikation: ✅/❌
Startup-Order: ✅/❌
Health-Checks: ✅/❌
```

### 3. Resilience-Report (ausgefüllt)

Alle 10 Szenarien mit tatsächlichem Verhalten.

### 4. Fix-Liste

Für jeden gefundenen Problem:
```
### [SEVERITY] Kurzbeschreibung
- **Bereich**: Test / Docker / Resilience / Monitoring
- **Datei**: path/to/file
- **Problem**: Was ist falsch
- **Fix**: Konkreter Fix
```

### 5. Empfehlungen

Top-5 Verbesserungen für Stabilität und Zuverlässigkeit im Produktionsbetrieb.

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode. Docker-Builds und pytest können ggf. nicht ausgeführt werden wenn Dependencies fehlen. Analysiere dann den Code statisch — lies Dockerfiles Zeile für Zeile, lies Tests Zeile für Zeile, simuliere gedanklich was passiert.

### Ziel-Hardware

Das System läuft auf folgender Hardware:
- **CPU**: AMD Ryzen 7 3700X (8 Kerne / 16 Threads)
- **RAM**: 64GB DDR4 3200MHz
- **GPU**: ASUS ROG Strix **RTX 3090** (24GB VRAM) — für Ollama LLM-Inference
- **Storage**: 500GB NVMe (System) + 1TB SATA SSD (Daten)

> Berücksichtige dies bei GPU-Compose-Checks, VRAM-Limits, OOM-Szenarien und Modell-Empfehlungen.

---

## Regeln

### Gründlichkeits-Pflicht

> **Lies JEDEN Dockerfile mit Read. FÜHRE Tests mit Bash AUS. Lies JEDES install/update Script mit Read.**

### Claude Code Tool-Einsatz in diesem Prompt

| Aufgabe | Tool | Befehl |
|---|---|---|
| Tests ausführen | **Bash** | `cd assistant && python -m pytest --tb=short -q` |
| Einzelnen Test debuggen | **Bash** | `cd assistant && python -m pytest tests/test_X.py -v --tb=long` |
| Test-Coverage messen | **Bash** | `cd assistant && python -m pytest --cov=assistant --cov-report=term-missing` |
| Dockerfiles lesen | **Read** (parallel: alle 3) | `assistant/Dockerfile`, `addon/Dockerfile`, `speech/Dockerfile.whisper` |
| Docker-Compose prüfen | **Read** (parallel) | `docker-compose.yml` + `docker-compose.gpu.yml` |
| Docker build testen | **Bash** | `cd assistant && docker build -t jarvis-test . 2>&1 \| tail -20` |
| Install-Scripts finden | **Glob** | `**/*.sh` in `assistant/`, `addon/`, Root |
| Install-Scripts lesen | **Read** (parallel, falls vorhanden) | `install.sh`, `update.sh`, `nvidia-watchdog.sh` |
| Requirements prüfen | **Read** (parallel: alle 3) | `assistant/requirements.txt`, `addon/.../requirements.txt`, `speech/requirements.txt` |
| Neue Tests schreiben | **Write/Edit** | Test-Datei erstellen, dann mit Bash ausführen |
| Static Analysis | **Bash** | `cd assistant && python -m py_compile assistant/brain.py 2>&1` |

**Wichtig bei Addon-Tests**: Der Addon braucht ein laufendes Home Assistant. Addon-Module können nur **statisch analysiert** werden (Read + Grep), nicht mit pytest getestet.

- **Tests MÜSSEN mit Bash ausgeführt werden** — nicht nur lesen, sondern tatsächlich `pytest` starten
- **Fehlgeschlagene Tests analysieren** — ist der Test falsch oder der Code?
- **Docker-Builds wenn möglich ausführen** — `docker build` mit Bash, falls Docker verfügbar
- **Resilience ist nicht optional** — ein Smart-Home-Butler MUSS robust sein (MCU-Jarvis crasht nicht)
- **Keine neuen Tests für Code-Stil** — nur für funktionale Lücken
- **Addon-Tests nicht vergessen** — falls vorhanden
- **Nach jedem Fix: Tests erneut laufen lassen**

---

## ⚡ Nächster Schritt: Neuer Durchlauf?

Wenn du nach Prompt 7 einen **neuen Audit-Durchlauf** starten willst (z.B. um Fixes zu verifizieren):

1. Nutze `PROMPT_RESET.md` **vor** Prompt 1
2. Der Reset sichert die Ergebnisse dieses Durchlaufs als Vergleichsbasis
3. Starte dann frisch mit Prompt 1 — alle Dateien neu lesen, alle Bugs neu suchen
