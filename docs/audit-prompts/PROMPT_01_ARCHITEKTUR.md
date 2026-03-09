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

---

## Kontext

Jarvis ist ein lokaler KI-Butler für Home Assistant. Das Projekt besteht aus **drei Services** die zusammenarbeiten:

### ⚠️ WICHTIG: Drei separate Services

Das System ist NICHT nur der Assistant. Es besteht aus:

1. **Assistant-Server** (`/assistant/assistant/`, ~89 Python-Module, FastAPI)
   - KI-Kern: LLM, Memory, Persönlichkeit, Function Calling
   - Kommuniziert mit HA über REST/WebSocket API

2. **Addon-Server** (`/addon/rootfs/opt/mindhome/`, ~71 Python-Module, Flask)
   - Smart-Home-Logik: Domain-Controller, Automation-Engine, Pattern-Engine
   - Eigener Event-Bus (`event_bus.py`), eigene HA-Connection (`ha_connection.py`)
   - 25+ Domain-Module (light, climate, cover, presence, motion, camera, energy, solar, etc.)
   - 14+ Engines (circadian, sleep, comfort, cover_control, energy, fire_water, weather_alerts, etc.)
   - 17+ API-Routes

3. **Speech-Server** (`/speech/`, 2 Python-Module, Whisper STT)
   - Separate Speech-to-Text Service
   - Eigener Docker-Container

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
| **Sonstiges** | `web_search.py`, `knowledge_base.py`, `summarizer.py`, `ocr.py`, `file_handler.py`, `visitor_manager.py`, `follow_me.py`, `wellness_advisor.py`, `activity.py`, `seasonal_insight.py`, `explainability.py`, `diagnostics.py`, `task_registry.py`, `config.py`, `constants.py`, `config_versioning.py` |

### Addon — Kern-Module

| Bereich | Module |
|---|---|
| **App** | `app.py` (Flask), `base.py`, `models.py`, `db.py` |
| **HA-Anbindung** | `ha_connection.py`, `event_bus.py` |
| **Domains** | `light.py`, `climate.py`, `cover.py`, `switch.py`, `door_window.py`, `motion.py`, `motion_control.py`, `camera.py`, `media.py`, `lock.py`, `presence.py`, `weather.py`, `vacuum.py`, `ventilation.py`, `humidifier.py`, `air_quality.py`, `energy.py`, `solar.py`, `bed_occupancy.py`, `seat_occupancy.py`, `system.py` |
| **Engines** | `circadian.py`, `sleep.py`, `comfort.py`, `cover_control.py`, `energy.py`, `fire_water.py`, `weather_alerts.py`, `health_dashboard.py`, `routines.py`, `special_modes.py`, `visit.py`, `adaptive.py`, `access_control.py`, `camera_security.py`, `data_retention.py` |
| **Automation** | `automation_engine.py`, `pattern_engine.py`, `task_scheduler.py` |
| **Routes** | 17+ API-Endpoints (frontend, chat, devices, rooms, energy, health, etc.) |

---

## Aufgabe

### Schritt 1 — Dokumentation lesen

Lies diese Dateien **komplett** (aber vertraue keiner Aussage blind):

1. `docs/PROJECT_MINDHOME_ASSISTANT.md` — Architektur & Modul-Abhängigkeiten
2. `docs/JARVIS_AUDIT.md` — Modul-Audit
3. `JARVIS_AUDIT_REPORT.md` (im Root-Verzeichnis) — Audit-Ergebnisse
4. `JARVIS_MASTERPLAN.md` — Gesamtplan
5. `docs/AUDIT_OPERATIONAL_RELIABILITY.md` — Operational Reliability Audit (falls vorhanden, wertvoller Kontext)

### Schritt 2 — Die drei Services verstehen

**2a)** Lies `brain.py` komplett. Verstehe:
- Wie wird **jedes** Modul initialisiert?
- In welcher **Reihenfolge** werden Module aufgerufen?
- Gibt es eine zentrale **Koordination** oder ist brain.py nur eine dumme Weiterleitung?
- Wo werden Entscheidungen getroffen — in brain.py oder in den Modulen selbst?

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

### Schritt 4 — Vorverarbeitung verstehen

Prüfe den **Eingangs-Flow** vor brain.py:
- `pre_classifier.py` — Wie wird der Intent **vor** dem LLM klassifiziert?
- `request_context.py` — Welcher Kontext wird pro Request aufgebaut?
- Werden diese Ergebnisse in brain.py korrekt genutzt?

### Schritt 5 — Architektur bewerten

Bewerte mit konkreten Code-Referenzen:

1. **Ist brain.py ein God-Object?** Wenn ja — wäre Event-Bus, Pipeline oder Mediator-Pattern besser?
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

---

## Regeln

- Lies den Code **selbst** — vertraue der Dokumentation nicht blind
- **Addon-Layer NICHT vergessen** — er ist genauso wichtig wie der Assistant
- Fokus auf **Konflikte und Koordination** — keine Bug-Jagd in dieser Phase
- Wenn du einen Konflikt findest: Datei + Zeile + was genau passiert
- Bewerte: **Ist die Architektur selbst das Problem**, oder nur die Implementierung?
- Denke als MCU-Jarvis-Fan: Würde der echte Jarvis so funktionieren?

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
