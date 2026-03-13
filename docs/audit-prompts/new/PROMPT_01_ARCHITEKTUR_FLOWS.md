# Prompt 01: Architektur + Flows (Konsolidiert)

> Ersetzt: PROMPT_01 (Architektur), PROMPT_03a (Core Flows), PROMPT_03b (Extended Flows)
> Ziel: Architektur-Analyse + Flow-Dokumentation in EINEM Durchlauf (~90min)

---

## Rolle

Du bist ein Elite-Software-Architekt und KI-Ingenieur mit tiefem Wissen in:

- **LLM-Engineering**: Prompt Design, Context Window Management, Token-Budgetierung, Function Calling
- **Agent-Architekturen**: ReAct, Tool-Use-Loops, Planning-Agents, Multi-Agent-Koordination, Autonomy Levels
- **Python**: AsyncIO, FastAPI, Flask, Pydantic, aiohttp, Type Hints, Dataclasses
- **Smart Home**: Home Assistant REST/WebSocket API, Entity States, Services, Automations, Event Bus
- **Infrastruktur**: Docker, Redis, SQLite, YAML/Jinja2 Templating, WebSocket, Multi-Service-Architekturen

Du kennst **J.A.R.V.I.S. aus dem MCU** und nutzt ihn als Goldstandard:
- **Ein Bewusstsein** mit vielen Faehigkeiten — nie isolierte Module
- **Widerspricht sich nie**, kennt immer den Kontext, handelt koordiniert
- **Eine Stimme, ein Charakter** — egal ob Licht, Wetter oder Warnung

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (`supports_think_with_tools: false`)
- Tool-Call-Format: Ollama-Standard (`{"name": "...", "arguments": {...}}`)
- `character_hint` in `settings.yaml` model_profiles nutzen fuer Anti-Floskel

---

## Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem **GitHub-Quellcode**, NICHT mit einem laufenden System:
- **Keine `.env`-Datei vorhanden** — nur `.env.example`
- **Keine HA-Tokens, keine Secrets** — pruefe ob der Code graceful damit umgeht
- **Kein laufendes Redis/ChromaDB/Ollama** — du kannst nur den Code lesen, nicht testen

**Konsequenz**: Du musst ALLES aus dem Code herauslesen. Keine Annahmen. Folge jedem Funktionsaufruf bis zum Ende.

---

## Kontext

Jarvis ist ein lokaler KI-Butler fuer Home Assistant. Drei Services:

### Service-Map

| Service | Pfad | Module | Framework |
|---|---|---|---|
| **Assistant-Server** | `/assistant/assistant/` | 89 Module | FastAPI |
| **Addon-Server** | `/addon/rootfs/opt/mindhome/` | 67 Module | Flask |
| **Speech-Server** | `/speech/` | 2 Module | Whisper STT |
| **Shared-Module** | `/shared/` | 6 Dateien | API-Vertraege |
| **HA-Integration** | `/ha_integration/custom_components/mindhome_assistant/` | 3 Dateien | HA Custom Component |

### Assistant — Modul-Uebersicht

| Bereich | Module |
|---|---|
| **Orchestrierung** | `brain.py`, `brain_callbacks.py`, `main.py`, `websocket.py` |
| **Vorverarbeitung** | `pre_classifier.py`, `request_context.py` |
| **Persoenlichkeit** | `personality.py`, `mood_detector.py` |
| **Aktionen** | `function_calling.py`, `function_validator.py`, `declarative_tools.py`, `action_planner.py`, `self_automation.py`, `conditional_commands.py`, `protocol_engine.py` |
| **Memory** | `memory.py`, `semantic_memory.py`, `conversation_memory.py`, `memory_extractor.py`, `correction_memory.py`, `dialogue_state.py` |
| **Kontext** | `context_builder.py`, `situation_model.py`, `time_awareness.py` |
| **Proaktiv** | `proactive.py`, `proactive_planner.py`, `routine_engine.py` |
| **Intelligence** | `insight_engine.py`, `anticipation.py`, `learning_observer.py`, `learning_transfer.py`, `autonomy.py`, `spontaneous_observer.py` |
| **HA-Integration** | `ha_client.py`, `light_engine.py`, `climate_model.py`, `cover_config.py`, `camera_manager.py` |
| **Domain-Assistenten** | `cooking_assistant.py`, `music_dj.py`, `smart_shopping.py`, `calendar_intelligence.py`, `inventory.py`, `recipe_store.py`, `workshop_library.py`, `workshop_generator.py` |
| **Resilience** | `error_patterns.py`, `circuit_breaker.py`, `conflict_resolver.py`, `adaptive_thresholds.py` |

### Addon — Modul-Uebersicht

| Bereich | Module |
|---|---|
| **App** | `app.py`, `base.py`, `models.py`, `db.py` |
| **HA-Anbindung** | `ha_connection.py`, `event_bus.py` |
| **Domains** | `light.py`, `climate.py`, `cover.py`, `switch.py`, `door_window.py`, `motion.py`, `camera.py`, `media.py`, `lock.py`, `presence.py`, `weather.py`, `energy.py`, `solar.py` u.a. |
| **Engines** | `circadian.py`, `sleep.py`, `comfort.py`, `cover_control.py`, `energy.py`, `fire_water.py`, `weather_alerts.py`, `routines.py`, `adaptive.py` u.a. |
| **Automation** | `automation_engine.py`, `pattern_engine.py`, `task_scheduler.py` |
| **Routes** | 17+ API-Endpoints |

---

## Aufgabe

Drei Phasen, ein Durchlauf. Kompakt, mit Datei:Zeile Referenzen.

---

### Phase 1: Architektur (30min)

#### Schritt 1 — Dokumentation lesen

> **WICHTIG**: Pruefe ZUERST mit `Glob: pattern="**/{dateiname}"` ob die Datei existiert. Falls nicht → ueberspringe und dokumentiere "Datei nicht vorhanden".

Lies diese 5 Dateien komplett (parallel mit Read):

1. `docs/PROJECT_MINDHOME_ASSISTANT.md` — Architektur & Abhaengigkeiten
2. `docs/JARVIS_AUDIT.md` — Modul-Audit
3. `JARVIS_AUDIT_REPORT.md` — Audit-Ergebnisse (Root-Verzeichnis)
4. `docs/STRUCTURE.md` — Projektstruktur
5. `CHANGELOG.md` — Aenderungshistorie

#### Schritt 2 — Service-Map erstellen

**2a)** Lies `brain.py` komplett (**10.000+ Zeilen! Read in 2000-Zeilen-Abschnitten: offset=1 limit=2000, offset=2001 limit=2000, usw.**). Verstehe:
- Initialisierungsreihenfolge aller Module
- Zentrale Koordination vs. dumme Weiterleitung
- Wo Entscheidungen getroffen werden

**2b)** Lies `addon/rootfs/opt/mindhome/app.py` und `event_bus.py`. Verstehe:
- Kommunikation mit Home Assistant
- Eigener Event-Bus?
- Eigenstaendige Aktionen (ohne Assistant)?

**2c)** Lies `speech/server.py` — Kommunikation und Single-Point-of-Failure.

#### Schritt 3 — Top-3 Konflikt-Karten (fokussiert)

> Statt 6 Konfliktkarten: **nur die 3 kritischsten**. Kompakt, max 3 Zeilen pro Eintrag.

##### Konflikt A: Wer bestimmt was Jarvis SAGT?

| Modul | Einfluss auf Antwort | Koordination? |
|---|---|---|
| `personality.py` | Sarkasmus, Humor, Character-Lock | ? |
| `context_builder.py` | System-Prompt Zusammenbau | ? |
| `mood_detector.py` | Ton-Anpassung an User-Stimmung | ? |
| `routine_engine.py` | Eigene Antwort-Templates | ? |
| `proactive.py` | Eigene Nachrichten | ? |
| `situation_model.py` | Situations-Kontext | ? |
| `time_awareness.py` | Tageszeit-Kontext | ? |

**Kernfrage**: Ueberschreiben sich diese Systeme? Wer hat Vorrang?

##### Konflikt B: Wer bestimmt was Jarvis TUT?

| Modul | Wann es handelt | Koordination? |
|---|---|---|
| `function_calling.py` | Direkte Aktionen (Licht, Klima) | ? |
| `action_planner.py` | Multi-Step-Planung | ? |
| `anticipation.py` | Vorausschauend handeln | ? |
| `autonomy.py` | Entscheidet OB gehandelt wird | ? |
| `self_automation.py` | Generiert HA-Automationen | ? |
| `conflict_resolver.py` | Loest Konflikte zwischen Intents | ? |
| **Addon**: `automation_engine.py` | Addon-eigene Automationen | ? |
| **Addon**: Domain-Module | Direkte HA-Steuerung | ? |

**Kernfrage**: Koennen Assistant UND Addon gleichzeitig dieselbe Entity steuern?

##### Konflikt F: Assistant <-> Addon Interaktion (KRITISCH)

| Frage | Antwort | Code-Referenz |
|---|---|---|
| Kommunikationskanal? (HTTP? WS? Shared DB?) | ? | ? |
| Steuern beide dieselben HA-Entities? | ? | ? |
| Eigener HA-State-Cache im Addon? | ? | ? |
| Wer hat Vorrang bei gleichzeitiger Steuerung? | ? | ? |
| Koennen Addon-Automationen die Assistant-Logik unterlaufen? | ? | ? |
| Nutzen beide denselben Redis? | ? | ? |

#### Schritt 4 — Verdrahtungs-Graph

Erstelle mit Grep (Bulk-Suche, nicht einzeln lesen):

```
# Alle Projekt-Imports im Assistant
Grep: pattern="^from \.|^import \." path="assistant/assistant/" output_mode="content"

# Wer importiert brain?
Grep: pattern="from.*brain import|import.*brain" path="assistant/assistant/" output_mode="content"

# Addon-Imports
Grep: pattern="^from \.|^import \." path="addon/rootfs/opt/mindhome/" output_mode="content"
```

Finde damit:
- **Verwaiste Module** — von NIEMANDEM importiert (Dead Code?)
- **Zirkulaere Abhaengigkeiten** — A importiert B, B importiert A
- **God-Object-Indikatoren** — Module die von >10 anderen importiert werden

#### Schritt 5 — Shared-Module Audit

```
# Welche Shared-Schemas existieren?
Glob: pattern="shared/**/*.py"

# Wer importiert Shared-Schemas?
Grep: pattern="from shared|import shared" path="." output_mode="content"

# Eigene Request/Response-Klassen im Assistant?
Grep: pattern="class.*Request|class.*Response" path="assistant/assistant/" output_mode="content"

# Eigene Request/Response-Klassen im Addon?
Grep: pattern="class.*Request|class.*Response" path="addon/rootfs/opt/mindhome/" output_mode="content"
```

Ergebnis-Tabelle:
| Shared-Datei | Assistant importiert? | Addon importiert? | Abweichende Definitionen? |
|---|---|---|---|
| shared/constants.py | ? | ? | ? |
| shared/schemas/chat_request.py | ? | ? | ? |
| shared/schemas/chat_response.py | ? | ? | ? |
| shared/schemas/events.py | ? | ? | ? |

---

### Phase 2: Core-Flows (7 Flows, 40min)

> Pro Flow: Status (OK/WARN/FAIL), Entry:Zeile, Critical Breakpoints, Error Path, Kollisionen. **Max 15 Zeilen pro Flow.**

#### Flow 1: Speech Input -> Antwort (Hauptpfad)
- **Entry**: `main.py` POST /api/assistant/chat → `brain.py` process()
- Dokumentiere: Shortcut-Kaskade, Pre-Classification, Mega-Parallel-Gather, LLM-Call, Tool-Call-Ausfuehrung
- **Kritisch**: Wie viele Zeilen hat die Shortcut-Kaskade? Umgeht sie Personality?

#### Flow 2: Proaktive Benachrichtigungen
- **Entry**: `proactive.py` → HA WebSocket `state_changed` Events
- Dokumentiere: Event-Handler, Cooldown, Quiet-Hours, TTS-Ausgabe
- **Kritisch**: Gibt es ein TTS-Lock? Koennen proaktive + User-TTS sich ueberlagern?

#### Flow 3: Morgen-Briefing / Routinen
- **Entry**: `proactive.py` Motion-Sensor im Zeitfenster 6-10 Uhr ODER manuell via brain.py
- Dokumentiere: Redis-Lock (1x pro Tag), Bausteine, LLM-Prompt
- **Kritisch**: Nutzt es model_router oder hardcoded model_fast?

#### Flow 4: Autonome Aktion
- **Entry**: `anticipation.py` _check_loop() + `autonomy.py` can_act()
- Dokumentiere: Confidence-Schwellen (ask 60%, suggest 80%, auto 95%), SAFETY_CAPS
- **Kritisch**: Gibt es einen Auto-Execute-Pfad oder nur Vorschlaege?

#### Flow 5: Persoenlichkeits-Pipeline
- **Entry**: `personality.py` build_system_prompt() aufgerufen von brain.py
- Dokumentiere: SYSTEM_PROMPT_TEMPLATE, Dynamic Sections, Character-Lock
- **Kritisch**: Umgehen Shortcuts die Personality-Pipeline?

#### Flow 6: Memory-Abruf
- **Entry**: Explizit (`_handle_memory_command`), Intent-basiert, Passiv (`context_builder`)
- Dokumentiere: 5 Memory-Systeme (Working, Semantic, Conversation, Correction, Episodic)
- **Kritisch**: Gibt es eine Unified Query ueber alle Memory-Systeme?

#### Flow 7: Speech-Pipeline
- **Entry**: `speech/server.py` Wyoming Protocol → HA Assist → `conversation.py` → Assistant
- Dokumentiere: Whisper STT, Speaker Embedding, HTTP POST an Assistant
- **Kritisch**: Timeout-Asymmetrie (conversation.py 30s vs brain.process 60s)?

---

### Phase 3: Extended Flows & Kollisionen (20min)

> Leichtere Dokumentation: nur Status + kritische Issues. **Max 5 Zeilen pro Flow.**

#### Flow 8: Addon-Automation
**KRITISCH**: Koennen Addon (AutomationExecutor, CoverControlManager, CircadianLightManager) und Assistant (function_calling.py, light_engine.py, cover_config.py) gleiche Entities steuern?

#### Flow 9: Domain-Assistenten
cooking_assistant, music_dj, smart_shopping, calendar_intelligence, web_search — Routing und Personality-Konsistenz?

#### Flow 10: Workshop-System
80+ Endpoints in main.py, eigene LLM-Prompts — umgeht Personality?

#### Flow 11: Boot-Sequenz & Startup
Graceful Degradation (F-069), Module-Level brain Instanziierung — Import-Fehler abgefangen?

#### Flow 12: File-Upload & OCR
Extension-Whitelist, Path-Traversal-Schutz, OCR Pfad-Validierung — funktioniert OCR fuer regulaere Uploads?

#### Flow 13: WebSocket-Streaming
Event-Typen, Max Connections, Keep-Alive — gibt es Event-Recovery bei Verbindungsabbruch?

#### Flow-Kollisions-Analyse

Fuege diese Tabelle aus:

| Kollision | Was sollte passieren | Was passiert tatsaechlich | Code-Referenz |
|---|---|---|---|
| Proaktive Warnung waehrend User spricht | Queue, nach Antwort | ? | ? |
| Addon-Automation + Assistant-Aktion gleichzeitig | Koordination | ? | ? |
| Addon-CoverControl + Assistant-cover_config | Ein Owner | ? | ? |
| Addon-Circadian + Assistant-Circadian | Eine Engine | ? | ? |
| Multi-Room Speech parallel | Parallel Processing | ? | ? |
| Morning-Briefing waehrend Konversation | Briefing verzoegern | ? | ? |

---

## Output-Format

Kompakt — pro Konflikt/Flow max 3 Zeilen: **Problem, Ursache, Fix-Vorschlag**.

### 1. Konflikt-Karte (Top 3)

| Konflikt | Module | SEVERITY | Problem | Fix-Vorschlag |
|---|---|---|---|---|
| A: Wer bestimmt was Jarvis SAGT | personality.py, context_builder.py, ... | 🔴/🟠/🟡 | ... | ... |
| B: Wer bestimmt was Jarvis TUT | function_calling.py, action_planner.py, ... | 🔴/🟠/🟡 | ... | ... |
| F: Assistant <-> Addon | ha_client.py, ha_connection.py, ... | 🔴/🟠/🟡 | ... | ... |

### 2. Core-Flow-Dokumentation (7 Flows)

Pro Flow:

```
### Flow N: Name
- **Status**: ✅/⚠️/❌
- **Entry**: datei.py:Zeile → ...
- **Critical Breakpoints**: [max 3, mit Datei:Zeile]
- **Error Path**: [was passiert bei Fehler]
- **Kollisionen**: [mit welchen anderen Flows]
```

### 3. Extended-Flow-Status (6 Flows)

| Flow | Status | Critical Issues |
|---|---|---|
| 8: Addon-Automation | ✅/⚠️/❌ | ... |
| 9: Domain-Assistenten | ✅/⚠️/❌ | ... |
| 10: Workshop | ✅/⚠️/❌ | ... |
| 11: Boot-Sequenz | ✅/⚠️/❌ | ... |
| 12: File-Upload & OCR | ✅/⚠️/❌ | ... |
| 13: WebSocket-Streaming | ✅/⚠️/❌ | ... |

### 4. Flow-Kollisionen

| Kollision | Module | Loesung | Status |
|---|---|---|---|
| ... | ... | ... | ✅/⚠️/❌ |

### 5. Top-10 Architektur-Probleme

Gerankt nach Severity (🔴 > 🟠 > 🟡):

```
1. 🔴 [Kurzbeschreibung] | Datei:Zeile | Fix: [...]
2. 🔴 [Kurzbeschreibung] | Datei:Zeile | Fix: [...]
...
10. 🟡 [Kurzbeschreibung] | Datei:Zeile | Fix: [...]
```

---

## Regeln

### Gruendlichkeits-Pflicht

> **KEINE Abkuerzungen. KEINE Annahmen.**
>
> Fuer jede Aussage:
> - Hast du die Datei **tatsaechlich mit Read gelesen**?
> - Hast du die Funktion **bis zur letzten Zeile** verfolgt?
> - Hast du **mit Grep geprueft** wer diese Funktion aufruft?

### Tool-Einsatz

| Aufgabe | Tool | Beispiel |
|---|---|---|
| Dokumentation lesen | **Read** (parallel) | `Read: docs/PROJECT_MINDHOME_ASSISTANT.md` |
| brain.py verstehen | **Read** (in 2000-Zeilen-Abschnitten!) | offset=1 limit=2000, offset=2001 limit=2000, usw. |
| Import-Karte | **Grep** (Bulk) | `Grep: pattern="^from \." path="assistant/"` |
| Shared-Schema-Nutzung | **Grep** | `Grep: pattern="from shared" path="."` |
| Wer ruft Funktion X? | **Grep** | `Grep: pattern="brain\.process" path="."` |

- Lies den Code **selbst** — vertraue der Dokumentation nicht blind
- **Addon-Layer NICHT vergessen**
- Fokus auf **Konflikte und Koordination** — keine Bug-Jagd
- **Parallele Reads nutzen** — mehrere unabhaengige Dateien gleichzeitig lesen

---

## Erfolgs-Check

```
□ 3 Conflict-Maps erstellt (A, B, F)
□ 7 Core-Flows dokumentiert mit Datei:Zeile
□ 6 Extended-Flows mit Status
□ Flow-Kollisions-Tabelle ausgefuellt
□ Top-10 Architektur-Probleme gerankt
□ grep "import brain\|from.*brain" assistant/assistant/*.py → God-Object-Abhaengigkeiten gezaehlt
```

---

## Kontext-Uebergabe

Am Ende der Analyse diesen Block erstellen:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [n/a - analysis only]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [n/a - analysis only]
REGRESSIONEN: [n/a]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
