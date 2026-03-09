# Prompt 7: Testing, Resilience & Deployment-Verifikation

## Rolle

Du bist ein Elite-DevOps-Engineer und QA-Experte mit tiefem Wissen in:

- **Python Testing**: pytest, pytest-asyncio, Mocking, Fixtures, Coverage, Integration Tests
- **Docker**: Multi-Container-Setups, docker-compose, Health Checks, Networking, Volume-Mounts
- **Resilience Engineering**: Circuit Breaker, Graceful Degradation, Retry-Strategien, Health Monitoring
- **CI/CD**: Test-Automation, Build-Pipelines, Deployment-Strategien

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke aus allen 6 vorherigen Prompts ein:
> - Prompt 1: Konflikt-Karte & Architektur-Bewertung (3-Service-Architektur!)
> - Prompt 2: Memory-Diagnose & Root Cause
> - Prompt 3: Flow-Analyse mit Bruchstellen (9 Flows)
> - Prompt 4: Bug-Report mit allen Bugs + Security + Resilience
> - Prompt 5: Persönlichkeits-Audit & Config
> - Prompt 6: Harmonisierungs-Änderungen (was wurde gefixt?)

---

## Aufgabe

Nach den Fixes aus Prompt 6: **Verifiziere** dass alles funktioniert, **teste** systematisch, und stelle sicher dass das Deployment **robust** ist.

---

### Teil A: Bestehende Tests ausführen und bewerten

**Schritt 1** — Tests laufen lassen:
```bash
cd /assistant && pytest --tb=short -q
```

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

Für **jedes fehlende kritische Szenario**: Schreibe einen Test.

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

### Teil E: Monitoring & Observability

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

### Teil F: Installationsscripts prüfen

Lies und prüfe:
- `assistant/install.sh` — Installiert es korrekt?
- `assistant/update.sh` — Update-Logik robust?
- `assistant/nvidia-watchdog.sh` — GPU-Monitoring
- `install-nvidia-toolkit.sh` — GPU-Setup

| Script | Funktioniert? | Edge Cases abgedeckt? | Idempotent? |
|---|---|---|---|
| install.sh | ? | ? | ? |
| update.sh | ? | ? | ? |
| nvidia-watchdog.sh | ? | ? | ? |

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

## Regeln

- **Tests MÜSSEN laufen** — nicht nur lesen, sondern ausführen
- **Fehlgeschlagene Tests analysieren** — ist der Test falsch oder der Code?
- **Docker-Builds prüfen** — nicht nur das Dockerfile lesen
- **Resilience ist nicht optional** — ein Smart-Home-Butler MUSS robust sein (MCU-Jarvis crasht nicht)
- **Keine neuen Tests für Code-Stil** — nur für funktionale Lücken
- **Addon-Tests nicht vergessen** — falls vorhanden
- **Nach jedem Fix: Tests erneut laufen lassen**
