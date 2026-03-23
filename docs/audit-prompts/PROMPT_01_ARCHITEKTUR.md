# Prompt 1: Architektur-Analyse & Modul-Konflikte

## Rolle

Du bist ein Elite-Software-Architekt und KI-Ingenieur mit tiefem Wissen in:

- **LLM-Engineering**: Prompt Design, Context Window Management, Token-Budgetierung, Function Calling, Chain-of-Thought
- **Agent-Architekturen**: ReAct, Tool-Use-Loops, Planning-Agents, Multi-Agent-Koordination, Autonomy Levels, Self-Reflection
- **Python**: AsyncIO, FastAPI, Flask, Pydantic, aiohttp, Type Hints, Dataclasses, ABC/Protocols, GIL-Implikationen
- **Smart Home**: Home Assistant REST/WebSocket API, Entity States, Services, Automations, Event Bus, Area/Device Registry
- **Infrastruktur**: Docker, Redis, SQLite, YAML/Jinja2 Templating, WebSocket, Multi-Service-Architekturen

Du kennst **J.A.R.V.I.S. aus dem MCU** in- und auswendig und nutzt ihn als Goldstandard:
- **Ein Bewusstsein** mit vielen Fähigkeiten — nie isolierte Module
- **Widerspricht sich nie**, kennt immer den Kontext, handelt koordiniert
- **Eine Stimme, ein Charakter** — egal ob Licht, Wetter oder Warnung

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem **GitHub-Quellcode**, NICHT mit einem laufenden System. Das bedeutet:
- **Keine `.env`-Datei vorhanden** — nur `.env.example`. Prüfe welche Variablen erwartet werden und ob der Code mit fehlenden Werten umgeht.
- **Keine HA-Tokens, keine Secrets** — prüfe ob der Code graceful damit umgeht wenn Credentials fehlen.
- **Kein laufendes Redis/ChromaDB/Ollama** — du kannst nur den Code lesen, nicht testen. Umso wichtiger: **Lies jede Zeile**.
- **Prüfe `.env.example`** — Sind alle nötigen Variablen dokumentiert? Fehlen welche?

**Konsequenz**: Du musst ALLES aus dem Code herauslesen. Keine Annahmen. Keine "das wird schon laufen". Folge jedem Funktionsaufruf bis zum Ende.

---

## Kontext

Jarvis ist ein lokaler KI-Butler für Home Assistant. Das Projekt besteht aus **drei Services** die zusammenarbeiten:

### ⚠️ WICHTIG: Drei separate Services

Das System ist NICHT nur der Assistant. Es besteht aus:

1. **Assistant-Server** (`/assistant/assistant/`, 89 Python-Module, FastAPI)
   - KI-Kern: LLM, Memory, Persönlichkeit, Function Calling
   - Kommuniziert mit HA über REST/WebSocket API

2. **Addon-Server** (`/addon/rootfs/opt/mindhome/`, 67 Python-Module, Flask)
   - Smart-Home-Logik: Domain-Controller, Automation-Engine, Pattern-Engine
   - Eigener Event-Bus (`event_bus.py`), eigene HA-Connection (`ha_connection.py`)
   - 25+ Domain-Module (light, climate, cover, presence, motion, camera, energy, solar, etc.)
   - 14+ Engines (circadian, sleep, comfort, cover_control, energy, fire_water, weather_alerts, etc.)
   - 17+ API-Routes

3. **Speech-Server** (`/speech/`, 2 Python-Module, Whisper STT)
   - Separate Speech-to-Text Service
   - Eigener Docker-Container

4. **Shared-Module** (`/shared/`, 6 Dateien) — **API-Verträge zwischen Services**
   - `constants.py` — Gemeinsame Konstanten: Ports (ASSISTANT_PORT=8200, ADDON_INGRESS_PORT=5000, CHROMADB_PORT=8000, REDIS_PORT=6379, OLLAMA_PORT=11434), Event-Namen, Mood-Levels, Autonomy-Levels
   - `schemas/chat_request.py` — `ChatRequest` Pydantic-Model (text, person, room, speaker_confidence, voice_metadata) — **DER Vertrag zwischen Addon → Assistant**
   - `schemas/chat_response.py` — `ChatResponse` + `TTSInfo` Models — **Was der Assistant zurückgibt**
   - `schemas/events.py` — `MindHomeEvent` Model + Event-Typ-Konstanten — **WebSocket-Kommunikation**

   > ⚠️ **KRITISCH**: Dieses Modul definiert die **Schnittstelle** zwischen allen Services. Prüfe ob Assistant UND Addon diese Schemas tatsächlich importieren und nutzen, oder ob sie ihre eigenen (abweichenden) Definitionen haben.

5. **HA-Integration** (`/ha_integration/custom_components/mindhome_assistant/`, 3 Dateien)
   - `__init__.py` — HA-Integration Setup/Teardown, DOMAIN-Definition
   - `config_flow.py` — Konfigurations-UI für HA (URL + API-Key Eingabe, Verbindungstest)
   - `conversation.py` — HA Voice Pipeline → Assistant Bridge

### Das Kernproblem

Die Module — sowohl innerhalb des Assistants als auch **zwischen Assistant und Addon** — sind nicht als **ein System** designt worden. Das führt zu Konflikten, Überschreibungen und inkonsistentem Verhalten.

**Kritische Frage**: Wie kommunizieren Assistant und Addon? Steuern beide dieselben HA-Entities? Wer hat Vorrang?

### Assistant — Vollständige Modul-Liste

| Bereich | Module |
|---|---|
| **Orchestrierung** | `brain.py`, `brain_callbacks.py`, `main.py`, `websocket.py` |
| **Vorverarbeitung** | `pre_classifier.py` (Intent), `request_context.py` (Request State) |
| **Persönlichkeit** | `personality.py`, `mood_detector.py` |
| **Aktionen** | `function_calling.py`, `function_validator.py`, `declarative_tools.py`, `action_planner.py`, `self_automation.py`, `conditional_commands.py`, `protocol_engine.py` |
| **Memory** | `memory.py`, `semantic_memory.py`, `conversation_memory.py`, `memory_extractor.py`, `correction_memory.py`, `dialogue_state.py` |
| **Embeddings** | `embeddings.py`, `embedding_extractor.py` |
| **Kontext** | `context_builder.py`, `situation_model.py`, `time_awareness.py` |
| **Proaktiv** | `proactive.py`, `proactive_planner.py`, `routine_engine.py` |
| **Inference** | `ollama_client.py`, `model_router.py` |
| **Intelligence** | `insight_engine.py`, `anticipation.py`, `learning_observer.py`, `learning_transfer.py`, `autonomy.py`, `spontaneous_observer.py` |
| **Self-Improvement** | `self_optimization.py`, `self_report.py`, `feedback.py`, `response_quality.py`, `intent_tracker.py`, `outcome_tracker.py` |
| **Sprache / Audio** | `tts_enhancer.py`, `sound_manager.py`, `ambient_audio.py`, `multi_room_audio.py`, `speaker_recognition.py` |
| **HA-Integration** | `ha_client.py`, `light_engine.py`, `climate_model.py`, `cover_config.py`, `camera_manager.py` |
| **Domain-Assistenten** | `cooking_assistant.py`, `music_dj.py`, `smart_shopping.py`, `calendar_intelligence.py`, `inventory.py`, `recipe_store.py`, `workshop_library.py`, `workshop_generator.py` |
| **Monitoring** | `health_monitor.py`, `device_health.py`, `energy_optimizer.py`, `predictive_maintenance.py`, `repair_planner.py` |
| **Resilience** | `error_patterns.py`, `circuit_breaker.py`, `conflict_resolver.py`, `adaptive_thresholds.py` |
| **Sicherheit** | `threat_assessment.py` |
| **Timer** | `timer_manager.py` |
| **Sonstiges** | `web_search.py`, `knowledge_base.py`, `summarizer.py`, `ocr.py`, `file_handler.py`, `visitor_manager.py`, `follow_me.py`, `wellness_advisor.py`, `activity.py`, `seasonal_insight.py`, `explainability.py`, `diagnostics.py`, `task_registry.py`, `config.py`, `constants.py`, `config_versioning.py` |

### Addon — Kern-Module

| Bereich | Module |
|---|---|
| **App** | `app.py` (Flask), `base.py`, `models.py`, `db.py` |
| **HA-Anbindung** | `ha_connection.py`, `event_bus.py` |
| **Domains** | `light.py`, `climate.py`, `cover.py`, `switch.py`, `door_window.py`, `motion.py`, `motion_control.py`, `camera.py`, `media.py`, `lock.py`, `presence.py`, `weather.py`, `vacuum.py`, `ventilation.py`, `humidifier.py`, `air_quality.py`, `energy.py`, `solar.py`, `bed_occupancy.py`, `seat_occupancy.py`, `system.py` |
| **Engines** | `circadian.py`, `sleep.py`, `comfort.py`, `cover_control.py`, `energy.py`, `fire_water.py`, `weather_alerts.py`, `health_dashboard.py`, `routines.py`, `special_modes.py`, `visit.py`, `adaptive.py`, `access_control.py`, `camera_security.py`, `data_retention.py` |
| **Automation** | `automation_engine.py`, `pattern_engine.py`, `task_scheduler.py` |
| **Hilfsdateien** | `helpers.py`, `cover_helpers.py`, `init_db.py`, `version.py` |
| **Routes** | 17+ API-Endpoints: `automation.py`, `chat.py`, `covers.py`, `devices.py`, `domains.py`, `energy.py`, `frontend.py`, `health.py`, `notifications.py`, `patterns.py`, `presence.py`, `rooms.py`, `scenes.py`, `schedules.py`, `security.py`, `system.py`, `users.py` |

---

## Aufgabe

### Schritt 1 — Dokumentation lesen

Lies diese Dateien **komplett** (aber vertraue keiner Aussage blind):

> **WICHTIG**: Prüfe ZUERST mit `Glob: pattern="**/{dateiname}"` ob die Datei existiert. Manche Dokumentationen können in einem früheren Durchlauf umbenannt oder entfernt worden sein. Falls eine Datei nicht existiert → überspringe sie und dokumentiere "Datei nicht vorhanden" im Output.

1. `docs/PROJECT_MINDHOME_ASSISTANT.md` — Architektur & Modul-Abhängigkeiten
2. `docs/JARVIS_AUDIT.md` — Modul-Audit
3. `JARVIS_AUDIT_REPORT.md` (im Root-Verzeichnis) — Audit-Ergebnisse
4. `JARVIS_MASTERPLAN.md` — Gesamtplan
5. `docs/AUDIT_OPERATIONAL_RELIABILITY.md` — Operational Reliability Audit (falls vorhanden, wertvoller Kontext)

### Schritt 2 — Die drei Services verstehen

**2a)** Verstehe `brain.py` (**⚠️ 10.000+ Zeilen — NICHT komplett lesen!**):

**Strategie für große Dateien (>5000 Zeilen):**
1. **Grep zuerst** — finde die relevanten Abschnitte:
   - `Grep: pattern="class AssistantBrain|def __init__|async def initialize|def process|_safe_init" path="assistant/assistant/brain.py" output_mode="content"`
   - `Grep: pattern="async def |def " path="assistant/assistant/brain.py" output_mode="count"` → Anzahl Methoden
2. **Read gezielt** — nur die gefundenen Abschnitte lesen (offset/limit nutzen)
3. **NICHT** alle 10.000+ Zeilen sequentiell durchlesen — das füllt den Kontext unnötig

Verstehe:
- Wie wird **jedes** Modul initialisiert? (`_safe_init()` Pattern)
- In welcher **Reihenfolge** werden Module aufgerufen?
- Gibt es eine zentrale **Koordination** oder ist brain.py nur eine dumme Weiterleitung?
- Wo werden Entscheidungen getroffen — in brain.py oder in den Modulen selbst?

**2a-2)** Verstehe `main.py` (**⚠️ 8000+ Zeilen — gleiche Grep-First-Strategie wie brain.py!**):
Nutze `Grep: pattern="@app\.(get|post|put|delete|websocket)" path="assistant/assistant/main.py" output_mode="content"` um alle Endpoints zu finden, dann lies nur relevante Abschnitte. Verstehe:
- **API-Endpunkte**: Welche Endpoints gibt es? (`/api/assistant/*`, `/api/ui/*`, `/api/workshop/*`)
- **Boot-Sequenz**: `_boot_announcement()` — Wie kündigt sich Jarvis nach dem Start an?
- **Authentifizierung**: API-Key Middleware, PIN-Auth, Rate Limiting
- **Sicherheits-Endpoints**: Factory Reset, System Update/Restart, API-Key-Regeneration, Recovery Key
- **Error/Activity Buffer**: Ring-Buffer mit Redis-Persistenz, Sensitive-Data-Redaction
- **Workshop-System**: 80+ Endpoints für ein vollständiges Maker/Repair-Tool
- **Dashboard-API**: Alle `/api/ui/*` Endpoints für Entity-, Cover-, Szenen-, Zeitplan-Management
- **WebSocket Streaming**: `emit_stream_start/token/end` für Echtzeit-Antworten
- **File-Upload**: Verarbeitung mit OCR und Text-Extraktion
- **Prometheus Metrics**: `/metrics` Endpoint
- **Health/Readiness Probes**: `/healthz`, `/readyz`

> ⚠️ **main.py ist möglicherweise ein zweites God-Object** neben brain.py. Es enthält nicht nur Routing sondern signifikante Business-Logik.

**2b)** Lies `addon/rootfs/opt/mindhome/app.py` und `event_bus.py`. Verstehe:
- Wie kommuniziert der Addon mit Home Assistant?
- Hat der Addon seinen **eigenen** Event-Bus?
- Welche Aktionen führt der Addon **eigenständig** aus (ohne den Assistant)?

**2c)** Lies `speech/server.py`. Verstehe:
- Wie kommuniziert der Speech-Server mit dem Assistant?
- Gibt es Single-Point-of-Failure?

### Schritt 3 — Konflikt-Karte erstellen

#### Konflikt A: Wer bestimmt was Jarvis SAGT?

| Modul | Was es tut | Wie es die Antwort beeinflusst | Koordination mit anderen? |
|---|---|---|---|
| `personality.py` | Sarkasmus, Humor, Easter Eggs | ? | ? |
| `context_builder.py` | Baut den System-Prompt | ? | ? |
| `mood_detector.py` | Erkennt User-Stimmung | ? | ? |
| `routine_engine.py` | Eigene Antwort-Templates | ? | ? |
| `proactive.py` | Eigene Nachrichten | ? | ? |
| `situation_model.py` | Situations-Kontext | ? | ? |
| `time_awareness.py` | Tageszeit-Kontext | ? | ? |

**Frage**: Überschreiben sich diese Systeme? Wer hat Vorrang?

#### Konflikt B: Wer bestimmt was Jarvis TUT?

| Modul | Was es tut | Wann es handelt | Koordination mit anderen? |
|---|---|---|---|
| `function_calling.py` | Direkte Aktionen (Licht, Klima) | ? | ? |
| `function_validator.py` | Validiert Function Calls | ? | ? |
| `action_planner.py` | Multi-Step-Planung | ? | ? |
| `anticipation.py` | Vorausschauend handeln | ? | ? |
| `autonomy.py` | Entscheidet OB gehandelt wird | ? | ? |
| `self_automation.py` | Generiert HA-Automationen | ? | ? |
| `routine_engine.py` | Feste Abläufe | ? | ? |
| `conditional_commands.py` | If/Then-Automationen | ? | ? |
| `conflict_resolver.py` | Löst Konflikte zwischen Intents | ? | ? |
| **Addon**: `automation_engine.py` | Addon-eigene Automationen | ? | ? |
| **Addon**: Domain-Module | Direkte HA-Steuerung | ? | ? |
| **Addon**: `cover_control.py`, `circadian.py`, etc. | Engine-gesteuerte Aktionen | ? | ? |

**Frage**: Können Assistant UND Addon gleichzeitig dieselbe Entity steuern?

#### Konflikt C: Wer bestimmt was Jarvis WEISS?

| Modul | Datenquelle | Wird von anderen gelesen? | Synchronisiert? |
|---|---|---|---|
| `memory.py` | Redis (Working Memory) | ? | ? |
| `semantic_memory.py` | ChromaDB (Langzeit-Fakten) | ? | ? |
| `ha_integration/.../conversation.py` | HA Voice Pipeline → Assistant Bridge | ? | ? |
| `conversation_memory.py` | Konversations-Gedächtnis | ? | ? |
| `memory_extractor.py` | Fakten-Extraktion aus Gesprächen | ? | ? |
| `correction_memory.py` | Gelernte Korrekturen | ? | ? |
| `dialogue_state.py` | Konversations-Zustandsmaschine | ? | ? |
| `learning_observer.py` | Gelerntes aus Verhalten | ? | ? |
| `learning_transfer.py` | Wissenstransfer zwischen Domains | ? | ? |
| `context_builder.py` | Was tatsächlich im Prompt landet | ? | ? |
| `knowledge_base.py` | Lokales Wissen | ? | ? |
| **Addon**: `pattern_engine.py` | Erkannte Muster | ? | ? |
| **Addon**: `db.py` / `models.py` | Addon-Datenbank | ? | ? |

**Frage**: Wissen diese Systeme voneinander? Oder isolierte Silos?

#### Konflikt D: Wie Jarvis KLINGT

| Modul | Was es steuert | Code-Referenz |
|---|---|---|
| `personality.py` | Charakter, Sarkasmus, Formality | ? |
| `mood_detector.py` | Ton-Anpassung an User-Stimmung | ? |
| `context_builder.py` | System-Prompt-Zusammenbau | ? |
| `tts_enhancer.py` | TTS-Anpassungen | ? |
| `sound_manager.py` | Audio-Wiedergabe | ? |
| `multi_room_audio.py` | Raum-spezifische Ausgabe | ? |

**Frage**: Widersprechen sich Persönlichkeits-Anweisungen im Prompt?

#### Konflikt E: Timing & Prioritäten

| Szenario | Was passiert? | Code-Referenz |
|---|---|---|
| Proaktive Warnung WÄHREND User spricht | ? | ? |
| Morgen-Briefing WÄHREND Konversation läuft | ? | ? |
| Zwei autonome Aktionen gleichzeitig | ? | ? |
| anticipation.py + function_calling.py gleichzeitig | ? | ? |
| Addon-Automation + Assistant-Aktion gleichzeitig | ? | ? |
| Addon-Event + Proactive.py gleichzeitig | ? | ? |

**Frage**: Gibt es eine zentrale Queue oder Priority-System? **Über beide Services hinweg?**

#### Konflikt F: Assistant ↔ Addon Interaktion (NEU — KRITISCH)

| Frage | Antwort | Code-Referenz |
|---|---|---|
| Wie kommunizieren Assistant und Addon? (HTTP? WebSocket? Shared DB?) | ? | ? |
| Steuern beide dieselben HA-Entities? | ? | ? |
| Hat der Addon seinen eigenen HA-State-Cache? | ? | ? |
| Kennt der Assistant den Addon-State? | ? | ? |
| Kennt der Addon die Assistant-Entscheidungen? | ? | ? |
| Wer hat Vorrang wenn beide gleichzeitig eine Entity steuern? | ? | ? |
| Können Addon-Automationen die Assistant-Logik unterlaufen? | ? | ? |
| Nutzen beide denselben Redis? | ? | ? |

### Schritt 4 — Vollständiger Verdrahtungs-Graph

**KRITISCH**: Erstelle eine **vollständige Import-Karte** aller Module. Nicht nur Memory — ALLE.

**Shared-Module Prüfung**: Prüfe zusätzlich ob und wie die Dateien aus `/shared/` (constants.py, schemas/) von Assistant, Addon und HA-Integration importiert werden. Nutzen alle Services dieselben Schemas oder definieren sie eigene?

#### Shared-Module Audit (PFLICHT)

```
# 1. Welche Shared-Schemas existieren?
Glob: pattern="shared/**/*.py"

# 2. Wer importiert die Shared-Schemas?
Grep: pattern="from shared|import shared" path="." output_mode="content"

# 3. Definiert der Assistant eigene Request/Response-Klassen?
Grep: pattern="class.*Request|class.*Response" path="assistant/assistant/" output_mode="content"

# 4. Definiert der Addon eigene Request/Response-Klassen?
Grep: pattern="class.*Request|class.*Response" path="addon/rootfs/opt/mindhome/" output_mode="content"

# 5. Nutzen alle Services dieselben Ports/Konstanten?
Grep: pattern="8200|5000|ASSISTANT_PORT|ADDON.*PORT" path="." output_mode="content"
```

Erwartetes Ergebnis:
| Shared-Datei | Von Assistant importiert? | Von Addon importiert? | Von HA-Integration importiert? | Abweichende eigene Definitionen? |
|---|---|---|---|---|
| shared/constants.py | ? | ? | ? | ? |
| shared/schemas/chat_request.py | ? | ? | ? | ? |
| shared/schemas/chat_response.py | ? | ? | ? | ? |
| shared/schemas/events.py | ? | ? | ? | ? |

#### Claude Code Strategie — Import-Karte effizient erstellen

**Nutze Grep** statt jede Datei einzeln zu öffnen:

```
# Schritt 1: Alle Projekt-Imports im Assistant finden
Grep: pattern="^from \.|^import \." path="assistant/assistant/" output_mode="content"

# Schritt 2: Alle Shared-Schema-Imports finden
Grep: pattern="from shared|import shared" path="." output_mode="content"

# Schritt 3: Wer importiert brain/memory/personality?
Grep: pattern="from.*brain import|import.*brain" path="assistant/assistant/" output_mode="content"

# Schritt 4: Addon-Imports
Grep: pattern="^from \.|^import \." path="addon/rootfs/opt/mindhome/" output_mode="content"
```

**Dann** für die Top-10 meistimportierten Module: **Read** um die Klasse/Funktionen zu verstehen.

Erstelle eine **Verdrahtungs-Tabelle**:

| Modul | Importiert diese Projekt-Module | Wird importiert von |
|---|---|---|
| `brain.py` | ? (Liste ALLE) | ? |
| `main.py` | ? | ? |
| `personality.py` | ? | ? |
| ... für JEDES Modul ... | ... | ... |

**Finde damit**:
- **Verwaiste Module** — Dateien die von NIEMANDEM importiert werden (Dead Code?)
- **Zirkuläre Abhängigkeiten** — A importiert B, B importiert A
- **God-Object-Indikatoren** — Module die von >10 anderen importiert werden
- **Isolierte Inseln** — Gruppen von Modulen die keine Verbindung zu anderen haben
- **Fehlende Verbindungen** — Module die EIGENTLICH zusammenarbeiten sollten aber sich nicht kennen

> **Wichtig**: Nutze Grep für die Bulk-Suche, dann Read für Details. Nicht 89 Dateien einzeln öffnen wenn ein Grep-Pattern alle Imports auf einmal findet.

### Schritt 5 — Vorverarbeitung verstehen

Prüfe den **Eingangs-Flow** vor brain.py:
- `pre_classifier.py` — Wie wird der Intent **vor** dem LLM klassifiziert?
- `request_context.py` — Welcher Kontext wird pro Request aufgebaut?
- Werden diese Ergebnisse in brain.py korrekt genutzt?

### Schritt 6 — Architektur bewerten

Bewerte mit konkreten Code-Referenzen:

1. **Ist brain.py ein God-Object?** Wenn ja — wäre Event-Bus, Pipeline oder Mediator-Pattern besser?
1b. **Ist main.py ein zweites God-Object?** 8000+ Zeilen, 200+ Endpoints, Boot-Logik, Auth, Workshop, Dashboard — gehört Logik hier oder in Module?
2. **Gibt es zirkuläre Abhängigkeiten** zwischen Modulen?
3. **Fehlt ein zentraler State-Manager?** Wer hält den "aktuellen Zustand" von Jarvis?
4. **Ist die Modul-Granularität richtig?** Sollten manche Module zusammengelegt werden?
5. **Ist die Drei-Service-Architektur sinnvoll?** Oder erzeugt sie mehr Probleme als sie löst?
6. **Addon vs. Assistant Dopplung**: Gibt es Funktionen die in BEIDEN implementiert sind?

---

## Output-Format

### 1. Konflikt-Report

Für jeden gefundenen Konflikt:

```
### [SEVERITY] Konflikt: Kurzbeschreibung
- **Beteiligte Module**: modul_a.py:123, modul_b.py:456
- **Was passiert**: Konkrete Beschreibung des Konflikts
- **Auswirkung**: Was der User davon merkt
- **Empfehlung**: Wie es gelöst werden sollte
```

Severities: 🔴 KRITISCH | 🟠 HOCH | 🟡 MITTEL | 🟢 NIEDRIG

### 2. Service-Interaktions-Diagramm

```
[Assistant] ←→ [???] ←→ [Addon]
     ↕                      ↕
[Speech]              [Home Assistant]
```

Wie kommunizieren die Services? Dokumentiere jeden Kanal.

### 3. Architektur-Bewertung

- Stärken der aktuellen Architektur
- Fundamentale Schwächen
- Top-5 Architektur-Änderungen mit höchstem Impact

### 4. Konflikt-Karten (alle 6 ausgefüllt)

Die Tabellen aus Schritt 3, vollständig mit Code-Referenzen.

### 5. Verdrahtungs-Graph (ausgefüllt)

Die vollständige Import-Tabelle aus Schritt 4 mit verwaisten Modulen, Zyklen und fehlenden Verbindungen.

---

## Regeln

### Gründlichkeits-Pflicht

> **KEINE Abkürzungen. KEINE Annahmen. KEIN "das wird schon funktionieren".**
>
> Für jede Aussage die du machst:
> - Hast du die Datei **tatsächlich mit Read gelesen**?
> - Hast du die Funktion **bis zur letzten Zeile** verfolgt?
> - Hast du **mit Grep geprüft** wer diese Funktion aufruft und mit welchen Parametern?
>
> Wenn du bei einer Frage unsicher bist — lies die Datei mit Read nach. Lieber zu gründlich als ein Problem übersehen.

### Claude Code Tool-Einsatz in diesem Prompt

| Aufgabe | Tool | Beispiel |
|---|---|---|
| Dokumentation lesen (Schritt 1) | **Read** (parallel: alle 5 Docs gleichzeitig) | `Read: docs/PROJECT_MINDHOME_ASSISTANT.md` |
| brain.py + main.py verstehen (Schritt 2) | **Grep** zuerst (Methoden/Klassen finden), dann **Read** gezielt (nur relevante Abschnitte) | `Grep: pattern="def process\|_safe_init\|class Assistant" path="assistant/assistant/brain.py"` |
| Addon + Speech verstehen (Schritt 2b/c) | **Read** (parallel: app.py + event_bus.py + server.py) | — |
| Import-Karte (Schritt 4) | **Grep** (Bulk-Suche über alle Module) | `Grep: pattern="^from \." path="assistant/"` |
| Shared-Schema-Nutzung prüfen | **Grep** | `Grep: pattern="from shared" path="."` |
| Wer ruft Funktion X auf? | **Grep** | `Grep: pattern="brain\.process" path="."` |

- Lies den Code **selbst** — vertraue der Dokumentation nicht blind
- **Addon-Layer NICHT vergessen** — er ist genauso wichtig wie der Assistant
- Fokus auf **Konflikte und Koordination** — keine Bug-Jagd in dieser Phase
- Wenn du einen Konflikt findest: Datei + Zeile + was genau passiert
- Bewerte: **Ist die Architektur selbst das Problem**, oder nur die Implementierung?
- Denke als MCU-Jarvis-Fan: Würde der echte Jarvis so funktionieren?
- **Verdrahtungs-Graph ist Pflicht** — nicht optional. Jedes Modul, jeder Import.
- **Parallele Reads nutzen** — Mehrere unabhängige Dateien gleichzeitig lesen

---

## Erfolgsmetriken

- Alle 6 Konfliktkarten (A-F) ausgefüllt mit Code-Referenzen (Datei:Zeile)
- Verdrahtungs-Graph für die **Top-20 meistimportierten Module** erstellt (nicht alle 89 — nutze Grep für Bulk-Suche)
- Service-Interaktions-Diagramm dokumentiert mit konkreten Kommunikationskanälen
- Top-5 Architektur-Probleme identifiziert und mit Severity bewertet
- Verwaiste Module und zirkuläre Abhängigkeiten identifiziert

---

## ⚡ Übergabe an Prompt 2

**WICHTIG**: Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block**, den du direkt in Prompt 2 einsetzt. Dieser Block soll enthalten:

1. **Konflikt-Karte** (alle 6 Konflikte A–F, je 2–3 Sätze + kritischste Code-Referenzen)
2. **Service-Interaktions-Diagramm** (wie kommunizieren die 3 Services)
3. **Top-5 Architektur-Probleme** (1 Satz + Severity pro Problem)
4. **Architektur-Entscheidung** (God-Object ja/nein, empfohlenes Pattern)

Formatiere ihn so:

```
## KONTEXT AUS PROMPT 1: Architektur-Analyse

### Konflikt-Karte
[Konflikte A–F hier]

### Service-Interaktion
[Diagramm + Erklärung hier]

### Top-5 Architektur-Probleme
[Liste hier]

### Architektur-Entscheidung
[Empfehlung hier]
```

**Wenn du Prompt 2 in derselben Konversation erhältst**: Setze diesen Kontext-Block automatisch ein — der User muss nichts kopieren.

---

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_01_ARCHITEKTUR.md
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
