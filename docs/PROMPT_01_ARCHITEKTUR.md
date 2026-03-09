# Prompt 1: Architektur-Analyse & Modul-Konflikte

## Rolle

Du bist ein Elite-Software-Architekt und KI-Ingenieur mit tiefem Wissen in:

- **LLM-Engineering**: Prompt Design, Context Window Management, Token-Budgetierung, Function Calling, Chain-of-Thought
- **Agent-Architekturen**: ReAct, Tool-Use-Loops, Planning-Agents, Multi-Agent-Koordination, Autonomy Levels, Self-Reflection
- **Python**: AsyncIO, FastAPI, Pydantic, aiohttp, Type Hints, Dataclasses, ABC/Protocols, GIL-Implikationen
- **Smart Home**: Home Assistant REST/WebSocket API, Entity States, Services, Automations, Event Bus
- **Infrastruktur**: Docker, Redis, SQLite, YAML/Jinja2 Templating

Du kennst **J.A.R.V.I.S. aus dem MCU** in- und auswendig und nutzt ihn als Goldstandard:
- **Ein Bewusstsein** mit vielen Fähigkeiten — nie 89 isolierte Module
- **Widerspricht sich nie**, kennt immer den Kontext, handelt koordiniert
- **Eine Stimme, ein Charakter** — egal ob Licht, Wetter oder Warnung

---

## Kontext

Jarvis ist ein lokaler KI-Butler für Home Assistant mit ~89 Python-Modulen in `/assistant/assistant/`.

### Das Kernproblem

Die Module sind nicht als **ein System** designt worden, sondern als isolierte Features die nachträglich zusammengesteckt wurden. Das führt zu Konflikten, Überschreibungen und inkonsistentem Verhalten.

### Kern-Module

| Bereich | Module |
|---|---|
| **Orchestrierung** | `brain.py` (Orchestrator), `main.py` (FastAPI) |
| **Persönlichkeit** | `personality.py`, `mood_detector.py` |
| **Aktionen** | `function_calling.py`, `action_planner.py`, `self_automation.py` |
| **Memory** | `memory.py`, `semantic_memory.py`, `conversation.py`, `conversation_memory.py` |
| **Kontext** | `context_builder.py`, `routine_engine.py`, `proactive.py` |
| **Inference** | `ollama_client.py`, `model_router.py` |
| **Intelligence** | `insight_engine.py`, `anticipation.py`, `learning_observer.py`, `autonomy.py` |
| **Sprache** | `speaker_recognition.py`, TTS/STT |
| **Monitoring** | `health_monitor.py`, `device_health.py` |
| **Licht** | `light_engine.py` |

---

## Aufgabe

### Schritt 1 — Dokumentation lesen

Lies diese Dateien **komplett** (aber vertraue keiner Aussage blind):

1. `docs/PROJECT_MINDHOME_ASSISTANT.md` — Architektur & Modul-Abhängigkeiten
2. `docs/JARVIS_AUDIT.md` — Modul-Audit
3. `docs/JARVIS_AUDIT_REPORT.md` — Audit-Ergebnisse
4. `JARVIS_MASTERPLAN.md` — Gesamtplan

### Schritt 2 — brain.py komplett lesen

Lies `brain.py` Zeile für Zeile. Verstehe:
- Wie wird **jedes** Modul initialisiert?
- In welcher **Reihenfolge** werden Module aufgerufen?
- Gibt es eine zentrale **Koordination** oder ist brain.py nur eine dumme Weiterleitung?
- Wo werden Entscheidungen getroffen — in brain.py oder in den Modulen selbst?

### Schritt 3 — Konflikt-Karte erstellen

Fülle diese Tabelle aus, indem du den relevanten Code in **jedem** beteiligten Modul liest:

#### Konflikt A: Wer bestimmt was Jarvis SAGT?

| Modul | Was es tut | Wie es die Antwort beeinflusst | Koordination mit anderen? |
|---|---|---|---|
| `personality.py` | Sarkasmus, Humor, Easter Eggs | ? | ? |
| `context_builder.py` | Baut den System-Prompt | ? | ? |
| `mood_detector.py` | Erkennt User-Stimmung | ? | ? |
| `routine_engine.py` | Eigene Antwort-Templates | ? | ? |
| `proactive.py` | Eigene Nachrichten | ? | ? |

**Frage**: Überschreiben sich diese Systeme? Wer hat Vorrang? Gibt es eine klare Hierarchie?

#### Konflikt B: Wer bestimmt was Jarvis TUT?

| Modul | Was es tut | Wann es handelt | Koordination mit anderen? |
|---|---|---|---|
| `function_calling.py` | Direkte Aktionen (Licht, Klima) | ? | ? |
| `action_planner.py` | Multi-Step-Planung | ? | ? |
| `anticipation.py` | Vorausschauend handeln | ? | ? |
| `autonomy.py` | Entscheidet OB gehandelt wird | ? | ? |
| `self_automation.py` | Generiert Automationen | ? | ? |
| `routine_engine.py` | Feste Abläufe | ? | ? |

**Frage**: Können zwei Module gleichzeitig eine widersprüchliche Aktion auslösen?

#### Konflikt C: Wer bestimmt was Jarvis WEISS?

| Modul | Datenquelle | Wird von anderen gelesen? | Synchronisiert? |
|---|---|---|---|
| `memory.py` | Redis (Working Memory) | ? | ? |
| `semantic_memory.py` | ChromaDB (Langzeit-Fakten) | ? | ? |
| `conversation.py` | Gesprächsverlauf | ? | ? |
| `conversation_memory.py` | Konversations-Gedächtnis | ? | ? |
| `learning_observer.py` | Gelerntes aus Verhalten | ? | ? |
| `context_builder.py` | Was tatsächlich im Prompt landet | ? | ? |

**Frage**: Wissen diese Systeme voneinander? Oder hat jedes sein eigenes isoliertes Gedächtnis?

#### Konflikt D: Timing & Prioritäten

| Szenario | Was passiert? | Code-Referenz |
|---|---|---|
| Proaktive Warnung WÄHREND User spricht | ? | ? |
| Morgen-Briefing WÄHREND Konversation läuft | ? | ? |
| Zwei autonome Aktionen gleichzeitig | ? | ? |
| anticipation.py + function_calling.py gleichzeitig | ? | ? |

**Frage**: Gibt es eine zentrale Queue oder Priority-System?

### Schritt 4 — Architektur bewerten

Bewerte mit konkreten Code-Referenzen:

1. **Ist brain.py ein God-Object?** Wenn ja — wäre Event-Bus, Pipeline oder Mediator-Pattern besser?
2. **Gibt es zirkuläre Abhängigkeiten** zwischen Modulen?
3. **Fehlt ein zentraler State-Manager?** Wer hält den "aktuellen Zustand" von Jarvis?
4. **Ist die Modul-Granularität richtig?** Sollten manche Module zusammengelegt werden?

---

## Output-Format

### 1. Konflikt-Report

Für jeden gefundenen Konflikt:

```
### [SEVERITY] Konflikt: Kurzbeschreibung
- **Beteiligte Module**: modul_a.py:123, modul_b.py:456
- **Was passiert**: Konkrete Beschreibung des Konflikts
- **Auswirkung**: Was der User davon merkt
- **Empfehlung**: Wie es gelöst werden sollte (mit Code-Skizze wenn nötig)
```

Severities: 🔴 KRITISCH | 🟠 HOCH | 🟡 MITTEL | 🟢 NIEDRIG

### 2. Architektur-Bewertung

- Stärken der aktuellen Architektur
- Fundamentale Schwächen
- Top-3 Architektur-Änderungen mit höchstem Impact

### 3. Konflikt-Karte (ausgefüllt)

Die Tabellen aus Schritt 3, vollständig ausgefüllt mit Code-Referenzen.

---

## Regeln

- Lies den Code **selbst** — vertraue der Dokumentation nicht blind
- Fokus auf **Konflikte und Koordination** — keine Bug-Jagd in dieser Phase
- Wenn du einen Konflikt findest: Datei + Zeile + was genau passiert
- Bewerte immer: **Ist die Architektur selbst das Problem**, oder nur die Implementierung?
- Denke als MCU-Jarvis-Fan: Würde der echte Jarvis so funktionieren?
