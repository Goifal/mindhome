# Prompt 7a: Testing & Test-Coverage

## Rolle

Du bist ein Elite-QA-Engineer mit tiefem Wissen in:

- **Python Testing**: pytest, pytest-asyncio, Mocking, Fixtures, Coverage, Integration Tests
- **Security Testing**: Endpoint-Schutz, Rate-Limiting, Auth-Verifikation
- **Resilience Testing**: Service-Ausfall-Szenarien, Graceful Degradation

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6d bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke aus allen vorherigen Prompts ein:
> - Prompt 1: Konflikt-Karte & Architektur-Bewertung
> - Prompt 2: Memory-Diagnose & Root Cause
> - Prompt 3a + 3b: Flow-Analyse mit Bruchstellen (13 Flows)
> - Prompt 4a + 4b + 4c: Bug-Report mit allen Bugs + Security + Resilience + Performance
> - Prompt 5: Persönlichkeits-Audit & Config
> - Prompt 6a: Stabilisierung (Kritische Bugs + Memory)
> - Prompt 6b: Architektur (Konflikte + Flows + Performance)
> - Prompt 6c: Charakter (Persönlichkeit + Config + Dead Code)
> - Prompt 6d: Härtung (Security + Resilience + Addon-Koordination)

---

## Aufgabe

Nach den Fixes aus Prompt 6a–6d: **Teste** systematisch und **schließe Test-Lücken**.

> **Dieser Prompt ist Teil 1 von 2** der Verifikation:
> - **P07a** (dieser): Tests ausführen + Test-Coverage + Security-Endpoint-Tests
> - **P07b**: Docker + Deployment + Resilience + Performance-Verifikation

### Zusätzliche Dokumentation (lies diese zuerst!):
- `docs/ASSISTANT_TEST_CHECKLIST.md` — Bestehende Test-Checkliste (falls vorhanden, als Basis nutzen)
- `docs/AUDIT_OPERATIONAL_RELIABILITY.md` — Vorherige Reliability-Analyse
- `docs/AUDIT_TTS_STT.md` — Speech-System-Audit

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

Basierend auf Prompt 3a/3b (Flows) und Prompt 4a–4c (Bugs) — prüfe ob es Tests gibt für:

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

#### Security-Endpoint-Tests (Pflicht — aus P04c Sicherheits-Findings!)

> ⚠️ P04c identifiziert kritische Endpoints (Factory-Reset, System-Restart, API-Key-Regeneration). P06d soll sie absichern. Hier **verifizieren** wir dass die Absicherung funktioniert.

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

#### Praxis-Szenarien: Funktioniert Jarvis wirklich?

> ⚠️ **Diese Szenarien prüfen ob die Module im Zusammenspiel funktionieren** — nicht nur ob einzelne Units korrekt sind.

Verfolge diese Szenarien **im Code** (mit Read + Grep) und prüfe ob der gesamte Pfad funktioniert:

| # | User-Szenario | Erwartetes Ergebnis | Was prüfen |
|---|---|---|---|
| 1 | User sagt: "Mach das Licht im Wohnzimmer an" | Licht geht an, Jarvis bestätigt | `brain.py` → `function_calling.py` → `ha_client.py`: Wird die richtige Entity gefunden? Wird das Ergebnis an den User zurückgemeldet? |
| 2 | User sagt: "Was habe ich gestern über den Urlaub gesagt?" | Jarvis erinnert sich | `brain.py` → `memory.py` → `semantic_memory.py` → `embeddings.py`: Wird die Erinnerung gefunden und korrekt im Prompt eingebaut? |
| 3 | User sagt: "Guten Morgen" (Routine) | Morgen-Briefing mit Wetter, Terminen, Status | `routine_engine.py` → `brain.py` → `context_builder.py` → `ha_client.py`: Werden alle Daten parallel geladen? |
| 4 | Waschmaschine fertig (HA-Event) | Jarvis informiert proaktiv | `proactive.py` → `brain.py` → `personality.py` → TTS: Kommt die Nachricht beim User an? |
| 5 | Ollama antwortet nicht (Timeout) | User bekommt Fehlermeldung, kein Crash | `ollama_client.py` → `brain.py` → Response: Gibt es Timeout? Was sagt Jarvis? |
| 6 | User lädt ein Foto hoch | OCR/Vision-Beschreibung, Antwort im Kontext | `file_handler.py` → `ocr.py` → `brain.py`: Kommt der extrahierte Text im LLM-Prompt an? |

Für jedes Szenario: Dokumentiere den **tatsächlichen Code-Pfad** und ob er **lückenlos** funktioniert oder wo er bricht.

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

### 2. Security-Endpoint-Report

| Endpoint | Geschützt? | Brute-Force-Schutz? | Test geschrieben? |
|---|---|---|---|

### 3. Fix-Liste

Für jedes gefundene Problem:
```
### [SEVERITY] Kurzbeschreibung
- **Bereich**: Test / Code
- **Datei**: path/to/file
- **Problem**: Was ist falsch
- **Fix**: Konkreter Fix
```

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## Regeln

- **Tests MÜSSEN mit Bash ausgeführt werden** — nicht nur lesen, sondern tatsächlich `pytest` starten
- **Fehlgeschlagene Tests analysieren** — ist der Test falsch oder der Code?
- **Keine neuen Tests für Code-Stil** — nur für funktionale Lücken
- **Addon-Tests nicht vergessen** — falls vorhanden
- **Nach jedem Fix: Tests erneut laufen lassen**

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Befehl |
|---|---|---|
| Tests ausführen | **Bash** | `cd assistant && python -m pytest --tb=short -q` |
| Einzelnen Test debuggen | **Bash** | `cd assistant && python -m pytest tests/test_X.py -v --tb=long` |
| Test-Coverage messen | **Bash** | `cd assistant && python -m pytest --cov=assistant --cov-report=term-missing` |
| Neue Tests schreiben | **Write/Edit** | Test-Datei erstellen, dann mit Bash ausführen |

**Wichtig bei Addon-Tests**: Der Addon braucht ein laufendes Home Assistant. Addon-Module können nur **statisch analysiert** werden (Read + Grep), nicht mit pytest getestet.

---

## Erfolgs-Kriterien

- □ Tests ausgefuehrt
- □ Coverage dokumentiert
- □ Alle KRITISCH Tests bestehen

## ⚡ Übergabe an Prompt 7b

Formatiere am Ende einen kompakten **Kontext-Block** für Prompt 7b:

```
## KONTEXT AUS PROMPT 7a: Test-Report

### Test-Ergebnisse
Tests: X bestanden / X fehlgeschlagen / X errors
Neue Tests geschrieben: [Liste]

### Security-Endpoint-Status
[Welche Endpoints geschützt, welche nicht]

### Offene Test-Lücken
[Szenarien die nicht getestet werden konnten]
```

**Wenn du Prompt 7b in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke automatisch ein.

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
