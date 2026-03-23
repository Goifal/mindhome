# Prompt 7b: Docker, Deployment, Resilience & Performance-Verifikation

## Rolle

Du bist ein Elite-DevOps-Engineer mit tiefem Wissen in:

- **Docker**: Multi-Container-Setups, docker-compose, Health Checks, Networking, Volume-Mounts
- **Resilience Engineering**: Circuit Breaker, Graceful Degradation, Retry-Strategien, Health Monitoring
- **Performance**: Latenz-Analyse, Bottleneck-Identifikation, GPU-Setup
- **CI/CD**: Build-Pipelines, Deployment-Strategien

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Kurzfassung: Thinking-Mode bei Tool-Calls deaktivieren (`supports_think_with_tools: false`), `character_hint` in model_profiles nutzen.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–7a bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke ein:
> - Prompt 4c: Performance-Report + Resilience-Report
> - Prompt 6b: Architektur-Entscheidungen + Performance-Optimierungen
> - Prompt 6d: Security-Fixes + Resilience-Implementierung + Addon-Koordination
> - Prompt 7a: Test-Report + Security-Endpoint-Status

---

## Aufgabe

> **Dieser Prompt ist Teil 2 von 2** der Verifikation:
> - **P07a**: Tests + Coverage + Security-Endpoints — ✅ erledigt
> - **P07b** (dieser): Docker + Deployment + Resilience + Performance

---

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

---

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

**Compound-Failure-Szenarien** (zusätzlich prüfen):
- Ollama + Redis gleichzeitig down → Was passiert? Crash oder graceful?
- HA nicht erreichbar + proaktive Events aktiv → Endlosschleife?
- ChromaDB voll + neue Fakten-Speicherung → Datenverlust oder Fallback?

---

### Teil E: Performance & Latenz-Verifikation

> **Jarvis muss schnell antworten.** Ziel: < 3 Sekunden für einfache Befehle ("Licht an").

> **Performance kann nur aus dem Code geschätzt werden** (Anzahl sequentieller await-Ketten, LLM-Calls pro Request, Netzwerk-Roundtrips). Exakte Zeitmessungen erfordern ein laufendes System und sind hier nicht möglich. Dokumentiere stattdessen die Anzahl der I/O-Operationen pro Flow.

**Schritt 1** — Latenz-relevante Code-Pfade prüfen:

| Phase | Ziel-Latenz | Was prüfen | Tool |
|---|---|---|---|
| Context Building | < 200ms | Werden Memory + HA-State parallel geladen? | **Grep**: `pattern="asyncio\.gather" path="assistant/assistant/context_builder.py"` |
| LLM-Inference | < 2000ms | Model-Routing: Einfache Befehle → schnelles Modell? | **Read**: `model_router.py` |
| Function Execution | < 500ms | HA-API-Timeouts korrekt? Parallele Calls? | **Read**: `ha_client.py` |
| Response Streaming | Sofort | Token-Streaming aktiv oder Batch? | **Grep**: `pattern="stream|emit_stream" path="assistant/assistant/"` |

**Schritt 2** — Performance-Antipatterns verifizieren (aus Prompt 4c):

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

---

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

---

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

---

### Teil H: Dependency-Audit

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

---

### Teil I: Frontend-Dateien prüfen

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

### 1. Deployment-Report

```
Docker-Build: ✅/❌
Service-Start: ✅/❌
Service-Kommunikation: ✅/❌
Startup-Order: ✅/❌
Health-Checks: ✅/❌
```

### 2. Resilience-Report (ausgefüllt)

Alle 10 Szenarien mit tatsächlichem Verhalten.

### 3. Performance-Report

| Phase | Geschätzt | Ziel | Status |
|---|---|---|---|
| Context Building | ?ms | <200ms | ✅/⚠️/❌ |
| LLM-Inference | ?ms | <2000ms | ✅/⚠️/❌ |
| Function Execution | ?ms | <500ms | ✅/⚠️/❌ |
| Response Processing | ?ms | <200ms | ✅/⚠️/❌ |
| **Gesamt** | **?ms** | **<3000ms** | ✅/⚠️/❌ |

### 4. Fix-Liste

```
### [SEVERITY] Kurzbeschreibung
- **Bereich**: Docker / Resilience / Monitoring / Dependency
- **Datei**: path/to/file
- **Problem**: Was ist falsch
- **Fix**: Konkreter Fix
```

### 5. Empfehlungen

Top-5 Verbesserungen für Stabilität und Zuverlässigkeit im Produktionsbetrieb.

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode. Docker-Builds und pytest können ggf. nicht ausgeführt werden wenn Dependencies fehlen. Analysiere dann den Code statisch — lies Dockerfiles Zeile für Zeile, simuliere gedanklich was passiert.

### Ziel-Hardware

Das System läuft auf folgender Hardware:
- **CPU**: AMD Ryzen 7 3700X (8 Kerne / 16 Threads)
- **RAM**: 64GB DDR4 3200MHz
- **GPU**: ASUS ROG Strix **RTX 3090** (24GB VRAM) — für Ollama LLM-Inference
- **Storage**: 500GB NVMe (System) + 1TB SATA SSD (Daten)

> Berücksichtige dies bei GPU-Compose-Checks, VRAM-Limits, OOM-Szenarien und Modell-Empfehlungen.

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## Regeln

### Gründlichkeits-Pflicht

> **Lies JEDEN Dockerfile mit Read. Lies JEDES install/update Script mit Read.**

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Befehl |
|---|---|---|
| Dockerfiles lesen | **Read** (parallel: alle 3) | `assistant/Dockerfile`, `addon/Dockerfile`, `speech/Dockerfile.whisper` |
| Docker-Compose prüfen | **Read** (parallel) | `docker-compose.yml` + `docker-compose.gpu.yml` |
| Docker build testen | **Bash** | `cd assistant && docker build -t jarvis-test . 2>&1 \| tail -20` |
| Install-Scripts finden | **Glob** | `**/*.sh` in `assistant/`, `addon/`, Root |
| Install-Scripts lesen | **Read** (parallel, falls vorhanden) | `install.sh`, `update.sh`, `nvidia-watchdog.sh` |
| Requirements prüfen | **Read** (parallel: alle 3) | `assistant/requirements.txt`, `addon/.../requirements.txt`, `speech/requirements.txt` |
| Static Analysis | **Bash** | `cd assistant && python -m py_compile assistant/brain.py 2>&1` |

- **Docker-Builds wenn moeglich ausfuehren** — `docker build` mit Bash, falls Docker verfuegbar
- **Resilience ist nicht optional** — ein Smart-Home-Butler MUSS robust sein (MCU-Jarvis crasht nicht)

### Falls Docker NICHT verfuegbar

Wenn `docker` nicht installiert ist (haeufig in Analyse-Umgebungen):
1. **Dockerfile Zeile fuer Zeile lesen** — jeder `RUN`-Befehl, jede `COPY`-Anweisung
2. **Pruefen ob alle requirements.txt von den Dockerfiles referenziert werden**
3. **Pruefen ob Ports korrekt exponiert werden**: `EXPOSE` vs. `docker-compose.yml` ports
4. **Pruefen ob Volumes konsistent sind**: Wo werden Daten persistiert?
5. **GPU-Pass-Through pruefen**: `--gpus all` oder `deploy.resources.reservations.devices` in compose
6. **Static Analysis statt Build**: `python3 -m py_compile` fuer alle Python-Dateien

---

## Erfolgs-Kriterien

- □ Docker Build erfolgreich (oder Dockerfile-Analyse wenn Docker nicht verfuegbar)
- □ Health-Checks vorhanden (/healthz, /readyz)
- □ Startup-Reihenfolge korrekt und Dependency-Failures behandelt
- □ GPU/VRAM-Budget dokumentiert fuer RTX 3090
- □ Resilience-Szenarien dokumentiert

### Erfolgs-Check (Schnellpruefung)

```
□ ls **/Dockerfile* → alle Dockerfiles gefunden
□ grep "HEALTHCHECK\|healthz\|readyz" **/Dockerfile* → Health-Checks in Docker
□ grep "healthz\|readyz" assistant/assistant/main.py → Health-Endpoints vorhanden
□ grep "GPU\|gpu\|cuda\|NVIDIA" **/Dockerfile* docker-compose*.yml → GPU-Config
□ grep "restart:\|restart_policy" docker-compose*.yml → Restart-Policy konfiguriert
```

## ⚡ Nächster Schritt: Neuer Durchlauf?

Wenn du nach Prompt 7b einen **neuen Audit-Durchlauf** starten willst (z.B. um Fixes zu verifizieren):

1. Nutze `PROMPT_RESET.md` **vor** Prompt 1
2. Der Reset sichert die Ergebnisse dieses Durchlaufs als Vergleichsbasis
3. Starte dann frisch mit Prompt 1 — alle Dateien neu lesen, alle Bugs neu suchen

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_07b_DEPLOYMENT.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

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
