# Prompt 6d: Härtung — Security, Resilience & Addon-Koordination

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte mit Fokus auf Security und Resilience. In 6a–6c hast du stabilisiert, die Architektur aufgeräumt und den Charakter harmonisiert. Jetzt härtest du das System.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6c bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke ein:
> - Prompt 1: Konflikt-Karte — **Konflikt F** (Assistant ↔ Addon Interaktion)
> - Prompt 4c: Bug-Report — **Security-Report** und **Resilience-Report**
> - Prompt 6a–6c: Stabilisierungs-/Architektur-/Charakter-Ergebnisse

---

## Fokus dieses Prompts

**Drei Dinge**: Security-Lücken schließen, Resilience implementieren, Addon-Koordination fixen.

### Harmonisierungs-Prinzipien in diesem Prompt

- **Ein robustes System**: Jarvis darf nie einfach crashen — MCU-Jarvis funktioniert auch unter Stress
- **Addon-Koordination**: Assistant und Addon als ein System, nicht als zwei

---

## Aufgabe

### ⚠️ Phase Gate: Regression-Check vor Start

1. **Tests ausführen**: `cd assistant && python -m pytest --tb=short -q`
2. **Vergleiche mit 6c-Checkpoint**: Alle Tests noch grün?
3. Falls Tests fehlschlagen → zurück zu 6c, dort fixen

### Schritt 1: Security-Bugs fixen (aus Prompt 4c Security-Report)

Arbeite **jeden** Security-Bug aus dem Prompt-4c-Report ab:

#### Die kritischsten Security-Checks

| # | Check | Modul | Was fixen |
|---|---|---|---|
| 1 | **Prompt Injection** | `context_builder.py` | User-Input sanitizen bevor er im System-Prompt landet |
| 2 | **Input Validation** | `main.py`, `websocket.py` | API-Inputs bei allen 200+ Endpoints validieren |
| 3 | **Factory Reset Schutz** | `main.py` | `/api/ui/factory-reset` — Trust-Level + Bestätigung |
| 4 | **System Update/Restart** | `main.py` | `/api/ui/system/update`, `/restart` — Auth prüfen |
| 5 | **API-Key Management** | `main.py` | `/api/ui/api-key/regenerate` — Recovery-Key-Logik |
| 6 | **PIN-Auth** | `main.py` | Brute-Force-Schutz? Rate Limiting? |
| 7 | **File Upload** | `file_handler.py`, `ocr.py` | Path Traversal, MIME-Type, Dateigröße |
| 8 | **Workshop Hardware** | `main.py` | Roboter-Arm + 3D-Drucker Trust-Level-geschützt? |
| 9 | **Function Call Safety** | `function_calling.py`, `function_validator.py` | Bösartige Tool-Calls verhindern |
| 10 | **Self-Automation Safety** | `self_automation.py` | Gefährliche HA-Automationen verhindern |
| 11 | **Autonomy Limits** | `autonomy.py` | Harte Grenzen für autonome Aktionen |
| 12 | **WebSearch SSRF** | `web_search.py` | IP-Blocklist, URL-Validierung |
| 13 | **Frontend XSS** | `app.jsx`, `app.js` | User-Input escaped? |
| 14 | **CORS** | `main.py`, `addon/app.py` | Nicht zu permissiv? |
| 15 | **Sensitive Data** | `main.py` | API-Keys/Tokens in Logs redacted? |

**Für jeden Security-Fix:**
1. **Read** — Betroffene Datei lesen
2. **Grep** — Alle Stellen finden wo das Pattern vorkommt
3. **Edit** — Fix implementieren
4. **Grep** — Verifizieren dass alle Stellen gefixt sind

### Schritt 2: Resilience implementieren (aus Prompt 4c Resilience-Report)

**Für jedes Ausfallszenario** — stelle sicher dass Jarvis graceful degradiert:

| # | Szenario | Erwartetes Verhalten | Was implementieren |
|---|---|---|---|
| 1 | Ollama nicht erreichbar | User informieren, kein Crash | Timeout + Error-Message |
| 2 | Ollama crasht während Call | Retry mit Backoff, dann Error | Circuit Breaker |
| 3 | Redis nicht erreichbar | Memory degraded, Antworten funktionieren | Fallback auf In-Memory |
| 4 | ChromaDB nicht erreichbar | Langzeit-Memory degraded | Fallback auf Redis-only |
| 5 | Home Assistant nicht erreichbar | Fehlermeldung, Function Calls disabled | Graceful Error |
| 6 | Speech-Server nicht erreichbar | Text-only Mode | Fallback |
| 7 | Addon nicht erreichbar | Assistant funktioniert standalone | Independence |
| 8 | Netzwerk-Timeout | Retry mit Backoff | Timeout-Werte prüfen |
| 9 | Ungültiges LLM-Response | Parsing-Fehler abfangen | Try/Except + Fallback |
| 10 | Disk voll | Logging + DB graceful | Prüfe Log-Rotation |

**Prüfe und integriere bestehende Resilience-Module:**
```
Grep: pattern="circuit_breaker|CircuitBreaker" path="assistant/assistant/" output_mode="content"
Grep: pattern="error_patterns|ErrorPattern" path="assistant/assistant/" output_mode="content"
```

- Wird `circuit_breaker.py` überhaupt genutzt? Von welchen Modulen?
- Wird `error_patterns.py` genutzt? Führt es zu Verbesserungen?
- Wenn nicht genutzt: **Integrieren**, nicht nur existieren lassen

### Schritt 3: Addon-Koordination fixen (Konflikt F aus Prompt 1)

**Das Kernproblem**: Assistant und Addon können gleichzeitig dieselbe HA-Entity steuern.

**Was zu klären und zu implementieren:**

| Frage | Lösung |
|---|---|
| Wer steuert HA-Entities? | Klare Zuständigkeit definieren |
| Was wenn beide gleichzeitig steuern? | Lock-Mechanismus oder Priorität |
| Kennt der Assistant den Addon-State? | State-Sharing implementieren wenn nötig |
| Kennt der Addon die Assistant-Entscheidungen? | Events oder API |
| Doppelte Funktionalität | Eliminieren oder klare Abgrenzung |

**Doppelte Module identifizieren und auflösen:**

| Assistant | Addon | Gleiche Funktion? | Lösung |
|---|---|---|---|
| `light_engine.py` | `domains/light.py` + `engines/circadian.py` | Licht-Steuerung | ? |
| `climate_model.py` | `domains/climate.py` + `engines/comfort.py` | Klima-Steuerung | ? |
| `cover_config.py` | `domains/cover.py` + `engines/cover_control.py` | Rollladen | ? |
| `energy_optimizer.py` | `domains/energy.py` + `engines/energy.py` | Energie | ? |
| `threat_assessment.py` | `engines/camera_security.py` | Sicherheit | ? |
| `camera_manager.py` | `domains/camera.py` | Kameras | ? |

**Für jede Dopplung:**
1. **Read** — Beide Module lesen und vergleichen
2. Entscheiden: Wer ist zuständig?
3. **Edit** — Koordination implementieren (API-Call, Event, oder Elimination)

---

## Output-Format

### 1. Security-Fix-Log

Für jeden Fix:
```
### Security #X: Kurzbeschreibung
- **Risiko**: 🔴/🟠/🟡
- **Datei**: path:zeile
- **Problem**: Was war die Lücke
- **Fix**: Was implementiert
- **Verifiziert**: Grep zeigt alle Stellen gefixt
```

### 2. Resilience-Status

| Szenario | Vorher | Nachher | Implementierung |
|---|---|---|---|
| Ollama down | Crash | Graceful Error | circuit_breaker.py integriert |
| ... | ... | ... | ... |

### 3. Addon-Koordination

| Dopplung | Entscheidung | Implementierung |
|---|---|---|
| Licht: light_engine vs domains/light | ? | ? |
| ... | ... | ... |

### 4. Verifikation

| Check | Status |
|---|---|
| Security: Prompt Injection geschützt | ✅/❌ |
| Security: Kritische Endpoints geschützt | ✅/❌ |
| Resilience: Ollama-Ausfall abgefangen | ✅/❌ |
| Resilience: Redis-Ausfall abgefangen | ✅/❌ |
| Resilience: HA-Ausfall abgefangen | ✅/❌ |
| Addon: Keine Doppelsteuerung mehr | ✅/❌ |
| Tests bestehen | ✅/❌ |

---

## Regeln

### Gründlichkeits-Pflicht

> **Lies JEDE Security-relevante Datei mit Read. Prüfe JEDEN Endpoint in main.py auf Input-Validierung. Prüfe JEDES Ausfallszenario im Code.**

### Claude Code Tool-Einsatz

| Aufgabe | Tool |
|---|---|
| Security-Patterns finden | **Grep**: `pattern="request\.(json|form|args)" path="assistant/"` |
| CORS-Config finden | **Grep**: `pattern="CORS|Access-Control|allow_origin" path="."` |
| Circuit Breaker Nutzung | **Grep**: `pattern="circuit_breaker|CircuitBreaker" path="assistant/"` |
| Timeout-Werte finden | **Grep**: `pattern="timeout" path="assistant/assistant/ha_client.py"` |
| Addon-HA-Calls finden | **Grep**: `pattern="call_service|set_state|turn_on|turn_off" path="addon/"` |

- **Security-Bugs sind immer KRITISCH** — keine Abstriche
- **Resilience ist Pflicht** — MCU-Jarvis crasht nicht
- **Addon-Koordination konkret lösen** — nicht nur "sollte koordiniert werden"
- **Tests nach jedem Fix**
- **Security-Reihenfolge beachten**: Input-Validierung VOR Prompt-Injection-Schutz. Auth VOR API-Key-Management.

### ⚠️ Phase Gate: Finaler Checkpoint am Ende von 6d

> **Dieser Checkpoint ist besonders wichtig** — nach 6d gehen wir in die Test-Phase (P07a). Alle Fixes aus 6a–6d müssen stabil sein.

1. **Alle Tests laufen lassen**: `cd assistant && python -m pytest --tb=short -q`
2. **Git-Tag setzen**: `git tag checkpoint-6d-pre-testing`
3. **Vergleiche mit 6a-Baseline**: Mindestens gleich viele Tests grün wie nach 6a, idealerweise mehr
4. Falls Tests schlechter → Problem identifizieren und fixen bevor P07a beginnt

---

## ⚡ Übergabe an Prompt 7a

```
## KONTEXT AUS PROMPT 6d: Härtung

### Security-Fixes
[Liste: Security-# → Datei → Was gefixt]

### Resilience-Status
[Welche Szenarien jetzt abgefangen werden, welche nicht]

### Addon-Koordination
[Welche Dopplungen aufgelöst, welche Zuständigkeiten geklärt]

### Gesamt-Status nach 6a–6d
[Zusammenfassung aller Harmonisierungs-Schritte]

### Offene Punkte für Prompt 7a
[Was in Testing & Deployment verifiziert werden muss]
```

**Wenn du Prompt 7a in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1–6d) automatisch ein.
