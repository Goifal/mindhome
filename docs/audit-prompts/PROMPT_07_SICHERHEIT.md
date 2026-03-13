# Prompt 07: Sicherheit & Resilience — Fokussiertes Security-Audit

## Rolle

Du bist ein Elite-Security-Architekt fuer Python/FastAPI/Flask-Systeme. Du pruefst gezielt die Top-5-Sicherheitsluecken und die Top-3-Resilience-Szenarien. Nicht alles — aber das Wichtigste gruendlich.

---

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Bloecke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Fuege hier die Kontext-Bloecke ein:
> - Prompt 4c: Security-Report (falls vorhanden)
> - Prompt 5: Fix-Ergebnisse (falls Security-Bugs gefixt)
> - Prompt 6: Personality-Ergebnisse (falls relevant)

---

## Aufgabe

> **Fokus auf TOP 5 Security-Issues + Resilience-Basics. Nicht alles — das Wichtigste gruendlich.**

### Security (Top 5)

| # | Check | Was pruefen | Wie pruefen |
|---|---|---|---|
| 1 | **Prompt Injection** | System-Prompt auf Injection-Schutz pruefen, alle User-Inputs vor LLM validieren | Read `context_builder.py`, Grep: `pattern="user_input\|user_message\|f\".*{" path="assistant/assistant/context_builder.py"` |
| 2 | **Input Validation** | Alle HTTP-Endpoints validieren Input-Typen und -Laengen | Grep: `pattern="request\.(json\|form\|args)" path="assistant/assistant/main.py"`, Read relevante Endpoints |
| 3 | **Factory Reset** | Verifiziere `trust_level >= 3` + Bestaetigungscode-Anforderung | Grep: `pattern="factory.reset\|factory_reset" path="assistant/"`, Read betroffene Endpoints |
| 4 | **API Keys** | Verifiziere Keys nicht im Source-Code, `.env`-Handling, Key-Rotation | Grep: `pattern="api_key\|API_KEY\|secret\|token" path="assistant/assistant/"`, pruefen ob Werte hardcoded |
| 5 | **PIN Auth** | Verifiziere Brute-Force-Schutz (5 Versuche, 5min Lockout) | Grep: `pattern="pin\|PIN\|brute.force\|lockout\|rate.limit" path="assistant/assistant/main.py"` |

**Fuer jeden Check: Status dokumentieren als PASS / FAIL / PARTIAL mit Begruendung.**

### Resilience (Top 3 Szenarien)

| # | Szenario | Was passiert? | Wie pruefen |
|---|---|---|---|
| 1 | **Ollama Crash/Unerreichbar** | Degradiert der Assistant graceful? | Read `ollama_client.py`, Grep: `pattern="timeout\|ConnectionError\|except" path="assistant/assistant/ollama_client.py"` |
| 2 | **Redis Crash** | Was passiert mit Memory, Sessions, State? | Read `memory.py`, Grep: `pattern="redis.*except\|ConnectionError" path="assistant/assistant/memory.py"` |
| 3 | **HA Unerreichbar** | Kann der Assistant noch auf Nicht-HA-Anfragen antworten? | Read `ha_client.py`, Grep: `pattern="timeout\|except\|fallback" path="assistant/assistant/ha_client.py"` |

**Fuer jedes Szenario: Verhalten dokumentieren (Crash / Graceful Degradation / Fallback).**

### Circuit Breaker

1. **Read** `circuit_breaker.py` — Existiert das Modul?
2. **Grep** — Wird es tatsaechlich IMPORTIERT und VERWENDET?

```
Grep: pattern="circuit_breaker\|CircuitBreaker" path="assistant/assistant/" output_mode="content"
```

3. **Dokumentiere**: Welche Module importieren den Circuit Breaker? Welche SOLLTEN ihn importieren aber tun es nicht?

### Addon-Koordination

**6 bekannte Duplikationen zwischen Assistant und Addon dokumentieren:**

| Assistant | Addon | Funktion | Konflikt-Risiko |
|---|---|---|---|
| `light_engine.py` | `domains/light.py` + `engines/circadian.py` | Licht-Steuerung | Beide steuern gleiche Entities |
| `climate_model.py` | `domains/climate.py` + `engines/comfort.py` | Klima-Steuerung | Beide setzen Temperatur |
| `cover_config.py` | `domains/cover.py` + `engines/cover_control.py` | Rollladen | Beide oeffnen/schliessen |
| `energy_optimizer.py` | `domains/energy.py` + `engines/energy.py` | Energie | Doppelte Optimierung |
| `threat_assessment.py` | `engines/camera_security.py` | Sicherheit | Doppelte Alarme |
| `camera_manager.py` | `domains/camera.py` | Kameras | Doppelte Steuerung |

**Pruefen**: Gibt es Entity-Konflikte (beide kontrollieren dasselbe Geraet)?

```
Grep: pattern="call_service\|set_state\|turn_on\|turn_off" path="addon/" output_mode="content"
Grep: pattern="call_service\|set_state\|turn_on\|turn_off" path="assistant/assistant/" output_mode="content"
```

### Eskalations-Protokoll

**4 Stufen verifizieren:**

| Stufe | Name | Ton | Autonomie |
|---|---|---|---|
| 1 | **INFO** | Beilaeufig | Nur melden |
| 2 | **WARNING** | Ernster, kuerzer | Melden + Loesung anbieten |
| 3 | **URGENT** | Kurz, bestimmt | Handeln + informieren |
| 4 | **EMERGENCY** | Minimal, sofort | Sofort autonom handeln |

**Autonomie-Whitelist pruefen**: Was darf Jarvis autonom, was nicht?

```
Grep: pattern="autonomy\|AUTONOMY\|can_act\|requires_confirmation\|trust_level" path="assistant/assistant/" output_mode="content"
```

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren mit Eskalation
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

---

## Erfolgs-Check (Schnellpruefung)

```
□ 5 Security-Checks dokumentiert mit Status (PASS/FAIL/PARTIAL)
□ 3 Resilience-Szenarien getestet
□ Circuit Breaker Nutzung verifiziert
□ grep "circuit_breaker" assistant/assistant/*.py → Importierer auflisten
□ Addon-Koordination dokumentiert
□ Keine neuen Security-Vulnerabilities eingefuehrt
```

---

## Regeln

### Claude Code Tool-Einsatz

| Aufgabe | Tool |
|---|---|
| Security-Patterns finden | **Grep**: `pattern="request\.(json\|form\|args)" path="assistant/"` |
| Circuit Breaker Nutzung | **Grep**: `pattern="circuit_breaker\|CircuitBreaker" path="assistant/"` |
| Hardcoded Secrets | **Grep**: `pattern="password\|secret\|api_key.*=" path="assistant/assistant/"` |
| CORS-Config finden | **Grep**: `pattern="CORS\|Access-Control\|allow_origin" path="."` |
| Addon-HA-Calls finden | **Grep**: `pattern="call_service\|set_state\|turn_on\|turn_off" path="addon/"` |

- **Security-Bugs sind immer KRITISCH** — keine Abstriche
- **Resilience ist Pflicht** — MCU-Jarvis crasht nicht
- **Addon-Koordination konkret dokumentieren** — nicht nur "sollte koordiniert werden"
- **Jeden Check mit PASS/FAIL/PARTIAL bewerten**

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
