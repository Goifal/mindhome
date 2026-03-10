# Audit-Ergebnis: Prompt 1 — Architektur-Analyse & Modul-Konflikte

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Drei-Service-Architektur, Modul-Konflikte A–F, Verdrahtungs-Graph, Architektur-Bewertung

---

## 1. Service-Interaktions-Diagramm

```
                    ┌─────────────────────────┐
                    │   Home Assistant (HA)    │
                    │   (PC1 / HAOS)           │
                    └──────┬───────┬───────────┘
                           │       │
            REST+WS API    │       │  REST+WS API
            (Supervisor)   │       │  (Long-Lived Token)
                           │       │
        ┌──────────────────┘       └──────────────────┐
        ▼                                             ▼
┌───────────────────┐                     ┌───────────────────┐
│   Addon-Server    │   HTTP Proxy        │  Assistant-Server  │
│   (Flask, PC1)    │ ──────────────────► │  (FastAPI, PC2)    │
│   Port 5000       │  /api/chat/send     │  Port 8200         │
│   67 Module       │  → /api/assistant/  │  88 Module         │
│   SQLite (68 Tab) │    chat             │  Redis + ChromaDB  │
└───────────────────┘                     └────────┬───────────┘
                                                   │
                                          Wyoming ASR (TCP)
                                          Port 10300
                                                   │
                                          ┌────────┴───────────┐
                                          │  Speech-Server     │
                                          │  (Whisper, PC2)    │
                                          │  2 Module          │
                                          └────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  HA-Integration (Custom Component)                              │
│  ha_integration/custom_components/mindhome_assistant/           │
│  conversation.py → HTTP POST → Assistant /api/assistant/chat    │
│  = HA Voice Pipeline Bridge                                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Shared Module (/shared/)                                       │
│  constants.py, schemas/chat_request.py, chat_response.py,       │
│  events.py — API-Verträge zwischen Services                     │
│  ⚠️ WERDEN VON NIEMANDEM IMPORTIERT (siehe Konflikt F)          │
└─────────────────────────────────────────────────────────────────┘
```

### Kommunikationskanäle

| Von | Nach | Protokoll | Code-Referenz |
|-----|------|-----------|---------------|
| HA-Integration | Assistant | HTTP POST `/api/assistant/chat` | `conversation.py:108-109` |
| Addon | Assistant | HTTP POST (Proxy) | `routes/chat.py:159` |
| Assistant | HA | REST API + WebSocket (Events) | `ha_client.py`, `proactive.py` |
| Addon | HA | REST API + WebSocket (Events) | `ha_connection.py:69-147, 534-680` |
| Speech | Assistant | **Indirekt** via Redis (Embeddings) + Wyoming TCP | `speech/server.py:9`, `speaker_recognition.py` |
| Addon ↔ Assistant | **Kein direkter Kanal** | Nur HTTP Chat-Proxy | Kein Zustandssync |

---

## 2. God-Object-Analyse

### 2a) brain.py — Primäres God-Object

| Metrik | Wert |
|--------|------|
| **Zeilen** | 10.231 |
| **Imports** | 89 (davon 80+ interne Module) |
| **Methoden** | 80+ |
| **process() Methode** | 4.838 Zeilen (Zeile 1076–5913) |
| **Init-Komponenten** | 60+ Objekte in `__init__()` (Zeile 203–370) |

brain.py ist der **einzige Integrationspunkt** des gesamten Assistant-Systems. Alle Module werden hier instanziiert, verdrahtet und orchestriert. Es gibt kein Event-Bus-Pattern, keinen Mediator, keine Dependency Injection — nur direkte Attribut-Zugriffe auf `self.<modul>`.

**Besonders kritisch**: `process()` mit 4.838 Zeilen enthält:
- 20+ Shortcut-Pfade für deterministische Antworten (Zeile 1304–2325)
- Mega-parallelen Context-Gather mit ~25 async Tasks (Zeile 2320–2416)
- Token-budgetierten Prompt-Aufbau (Zeile 2624–2997)
- Tool-Call-Loop mit 7 Phasen (Zeile 3270–3764)
- 400-Zeilen Response-Filter (Zeile 5259–5842)

### 2b) main.py — Zweites God-Object

| Metrik | Wert |
|--------|------|
| **Zeilen** | 8.037 |
| **API-Endpoints** | 170+ |
| **Eigene Request/Response-Models** | Zeile 630–656 (statt shared/schemas) |

**Bereiche in main.py**:
- Chat-API + Voice-API (Zeile 670–1500)
- Dashboard/UI-Endpoints (40+)
- Workshop-System (80+ Endpoints)
- System-Management (Factory Reset, Update, Restart)
- Auth-Middleware (API-Key + PIN, Zeile 601–625)
- Error/Activity Ring-Buffer (Zeile 82–149)
- Prometheus Metrics, Health/Readiness Probes

main.py enthält **signifikante Business-Logik** die in Module gehört, insbesondere die eigenen Request/Response-Modelle die von den Shared Schemas abweichen.

---

## 3. Konflikt-Karte

### 🔴 Konflikt A: Wer bestimmt was Jarvis SAGT?

| Modul | Was es tut | Wie es die Antwort beeinflusst | Koordination |
|-------|-----------|-------------------------------|--------------|
| `personality.py` | JARVIS-Charakter, Sarkasmus 1-5, Formality-Decay | System-Prompt Template + Post-Processing | Einziges Modul mit `SYSTEM_PROMPT_TEMPLATE` (Zeile 240–284) |
| `context_builder.py` | Baut dynamischen Kontext | Injiziert Memory, Situation, Corrections ins Prompt | Wird von brain.py aufgerufen, Output → personality.py |
| `mood_detector.py` | Erkennt User-Stimmung (5 Moods) | Mood-spezifische Prompt-Anweisungen | An personality.py angebunden (`set_mood_detector()`) |
| `routine_engine.py` | Morgen-/Abendbriefing | **Eigene Hardcoded-Templates** + LLM für Formatierung | **Umgeht** personality.py teilweise |
| `proactive.py` | Eigene Nachrichten bei Events | CRITICAL: Hardcoded-Text, kein personality.py | **Keine Koordination** für CRITICAL |
| `situation_model.py` | Situations-Delta-Tracking | Kontext über Änderungen seit letztem Turn | In brain.py eingebaut, nicht in personality |
| `time_awareness.py` | Tageszeit-Kontext | Zeitsensitive Aktionen (Rollläden, Beleuchtung) | Eigene HA-Calls, kein Einfluss auf Sprache |

**Problem**: Drei verschiedene Wege zur Antwort-Generierung existieren nebeneinander:
1. **Normaler Pfad**: context_builder → personality → LLM → response_filter ✅
2. **Proaktive Pfade**: Hardcoded Templates für CRITICAL/HIGH ❌
3. **Routine-Pfade**: Eigene Templates + LLM-Polish, Grußformel hardcoded ⚠️

### 🔴 Konflikt B: Wer bestimmt was Jarvis TUT?

| Modul | Was es tut | Wann es handelt | Koordination |
|-------|-----------|----------------|--------------|
| `function_calling.py` | Direkte HA-Aktionen per LLM Tool-Call | Bei User-Anfrage | 70 `call_service` Aufrufe, zentraler Aktor |
| `function_validator.py` | Validiert Climate/Light/Cover-Calls | Vor Execution | Kann pushback + confirmation erzwingen |
| `action_planner.py` | Multi-Step-Planung | Bei komplexen Anfragen | Nutzt eigenes LLM-Call-Pattern |
| `anticipation.py` | Vorausschauendes Handeln | Bei erkannten Mustern | Confidence-basiert: ask/suggest/auto |
| `autonomy.py` | Entscheidet OB gehandelt wird | Gate für autonome Aktionen | 5 Level (1-5), per-Person Trust |
| `self_automation.py` | Generiert HA-Automationen | Bei Muster-Erkennung | Schreibt YAML-Automationen |
| `routine_engine.py` | Feste Abläufe | Timer/Motion-getriggert | Eigene HA-Calls (8× call_service) |
| `conditional_commands.py` | If/Then-Automationen | Bei Bedingung-Match | Eigene Logik, parallel zu HA-Automationen |
| `conflict_resolver.py` | Löst Multi-Intent-Konflikte | Bei mehreren erkannten Intents | In brain.py integriert |
| **Addon**: `automation_engine.py` | Pattern-basierte Automationen | Bei Confidence-Threshold | **Eigene HA-Calls**, keine Abstimmung mit Assistant |
| **Addon**: Domain-Module | Direkte HA-Steuerung | Bei State-Events | 107 `call_service` Aufrufe |
| **Addon**: Engines | Engine-gesteuerte Aktionen | Diverse Trigger | circadian, sleep, fire_water, etc. |

**Problem**: **Kein zentraler Aktor**. Mindestens 4 unabhängige Pfade können HA-Services aufrufen:
1. Assistant: `function_calling.py` (LLM-gesteuert)
2. Assistant: `routine_engine.py`, `proactive.py`, etc. (deterministic)
3. Addon: `automation_engine.py` (pattern-based)
4. Addon: Engines (event-driven)

### 🔴 Konflikt C: Wer bestimmt was Jarvis WEISS?

| Modul | Datenquelle | Wird gelesen von | Synchronisiert? |
|-------|------------|-----------------|-----------------|
| `memory.py` | Redis `mha:conversations` (7d TTL, 50 Einträge) | brain.py, main.py, summarizer.py | Nein — isoliert |
| `semantic_memory.py` | ChromaDB `mha_semantic_facts` + Redis | brain.py, context_builder.py, memory_extractor.py | Nein — isoliert |
| `conversation_memory.py` | Redis `mha:memory:*` (Projekte, Fragen) | brain.py | **NICHT** Konversations-History! |
| `memory_extractor.py` | Schreibt via semantic_memory | brain.py | Fire-and-forget |
| `correction_memory.py` | Redis `mha:correction_memory:*` | brain.py | Nein — isoliert |
| `dialogue_state.py` | **Rein in-memory** (Python dict) | brain.py | Verloren bei Restart! |
| `learning_observer.py` | Redis `mha:learning:*` | brain.py, proactive.py, function_calling.py | Nein |
| `learning_transfer.py` | Redis + **in-memory** pending | brain.py | Pending transfers gehen bei Restart verloren |
| `knowledge_base.py` | ChromaDB `mha_knowledge_base` | brain.py | Nein — isoliert |
| `embeddings.py` | Singleton in-process | 6 Module (lazy import) | In-memory only |
| `context_builder.py` | Liest semantic_memory, formatiert für Prompt | brain.py | **DER Flaschenhals**: was hier nicht rein kommt, weiß Jarvis nicht |
| **Addon**: `pattern_engine.py` | SQLite `learned_patterns`, `state_history` | Nur Addon | **SILO**: Assistant hat keinen Zugriff |
| **Addon**: `models.py` / `db.py` | SQLite mit 68 Tabellen | Nur Addon | **SILO**: Assistant hat keinen Zugriff |

**Problem**: **12 isolierte Memory-Silos** im Assistant, plus ein komplett getrenntes Addon-Wissen in SQLite. Es gibt KEINEN kohärenten Memory-Stack. brain.py ist der einzige Integrationspunkt — und hat dabei den **Duplicate-Key-Bug** (brain.py:2356+2394) wo `conv_memory` Semantic Search überschrieben wird.

### 🟠 Konflikt D: Wie Jarvis KLINGT

| Modul | Was es steuert | Code-Referenz |
|-------|---------------|---------------|
| `personality.py` | JARVIS MCU-Charakter, Sarkasmus-Level 1-5, Formality-Decay, Easter Eggs | `SYSTEM_PROMPT_TEMPLATE` (Zeile 240–284), `build_system_prompt()` (Zeile 2192–2457) |
| `mood_detector.py` | Ton-Anpassung an User-Stimmung | 5 Moods, per-Person-Tracking |
| `context_builder.py` | System-Prompt-Zusammenbau | P1-P4 Token-budgetiert (brain.py:2624-2997) |
| `tts_enhancer.py` | SSML, Whisper-Mode, Pausen | Message-Klassifikation → SSML-Tags |
| `sound_manager.py` | Speaker-Auswahl, Volume | Speaker-Resolution, parallele Ausgabe |
| `multi_room_audio.py` | Speaker-Gruppen | **Nur für Musik**, NICHT für TTS-Routing |
| `_filter_response_inner()` | 400-Zeilen Post-Processing | brain.py:5259-5842: Sie→du, Floskeln, Reasoning entfernen |

**Problem**: Persönlichkeits-Anweisungen kommen aus **3 verschiedenen Quellen** (personality.py System-Prompt, brain.py Shortcuts mit hardcoded Text, mood_detector Ton-Anpassung). Die `_filter_response_inner()` Methode in brain.py (400 Zeilen) ist ein zweiter Persönlichkeits-Layer der sich mit dem LLM-gesteuerten Layer überlappen kann.

### 🟠 Konflikt E: Timing & Prioritäten

| Szenario | Was passiert? | Code-Referenz |
|----------|--------------|---------------|
| Proaktive Warnung WÄHREND User spricht | Proactive nutzt Cooldown + Quiet-Hours, aber **kein Lock** auf laufende Konversation | `proactive.py` 6 Filter-Layer |
| Morgen-Briefing WÄHREND Konversation | Briefing sendet WebSocket-Event, kein Konversations-Check | `routine_engine.py` → `emit_proactive()` |
| Zwei autonome Aktionen gleichzeitig | Autonomy-Level prüft pro Aktion, **kein globaler Mutex** | `autonomy.py` |
| Addon-Automation + Assistant-Aktion gleichzeitig | **KEIN Koordinationsmechanismus** — beide rufen HA unabhängig | Siehe Konflikt F |
| anticipation.py + function_calling.py | anticipation hat Confidence-Gate, aber kein Check ob User gerade anderes will | `anticipation.py` |

**Problem**: Es gibt **keine zentrale Queue oder Priority-System** — weder innerhalb des Assistants noch zwischen den Services. Proactive.py hat 6 eigene Filter-Layers, aber das betrifft nur proaktive Nachrichten, nicht die Gesamtkoordination.

### 🔴 Konflikt F: Assistant ↔ Addon Interaktion (KRITISCH)

| Frage | Antwort | Code-Referenz |
|-------|---------|---------------|
| Wie kommunizieren sie? | **Nur HTTP Chat-Proxy**: Addon → Assistant | `routes/chat.py:159` |
| Steuern beide dieselben HA-Entities? | **JA** — Assistant: 153 call_service, Addon: 107 call_service | Grep-Analyse |
| Hat der Addon eigenen HA-State-Cache? | **JA** — WebSocket-basierter State-Tracker + SQLite | `ha_connection.py`, `state_history` |
| Kennt der Assistant den Addon-State? | **NEIN** | Kein Import, kein API-Call |
| Kennt der Addon die Assistant-Entscheidungen? | **Nur Chat-Response** — keine State/Memory-Sync | `routes/chat.py` loggt nur ActionLog |
| Wer hat Vorrang bei gleichzeitiger Steuerung? | **NIEMAND** — HA nimmt den letzten Befehl | Race Condition |
| Können Addon-Automationen die Assistant-Logik unterlaufen? | **JA** — Addon kennt Assistant-Absichten nicht | Kein Vetorecht |
| Nutzen beide denselben Redis? | **NEIN** — Addon hat kein Redis, nur SQLite | Verschiedene Hosts |
| Shared Schemas genutzt? | **NEIN** — toter Code! | Siehe unten |

#### Shared Schemas sind toter Code

Die Shared Schemas (`shared/schemas/`) werden von **keinem Service importiert**:
- **Assistant** definiert **eigene** `ChatRequest`/`ChatResponse` in `main.py:630-656` mit **abweichenden Feldern**:
  - Shared `TTSInfo`: `ssml, volume, speed, target_speaker`
  - Assistant `TTSInfo`: `text, ssml, message_type, speed(int), volume(0.8), target_speaker`
  - Assistant `ChatRequest` hat zusätzliches `device_id` Feld
- **Addon** nutzt die Schemas ebenfalls nicht — proxied nur raw JSON
- **HA-Integration** baut eigenes Payload-Dict in `conversation.py:92-98`

**Die "API-Verträge" existieren nur auf dem Papier.**

---

## 4. Verdrahtungs-Graph

### brain.py Import-Karte (89 Imports)

brain.py importiert **alle** der folgenden Module:
`action_planner`, `activity`, `adaptive_thresholds`, `ambient_audio`, `anticipation`, `autonomy`, `brain_callbacks`, `calendar_intelligence`, `camera_manager`, `circuit_breaker`, `climate_model`, `conditional_commands`, `config`, `config_versioning`, `conflict_resolver`, `constants`, `context_builder`, `conversation_memory`, `cooking_assistant`, `correction_memory`, `device_health`, `diagnostics`, `dialogue_state`, `embeddings` (in-process), `energy_optimizer`, `error_patterns`, `explainability`, `feedback`, `follow_me`, `function_calling`, `function_validator`, `ha_client`, `health_monitor`, `insight_engine`, `intent_tracker`, `inventory`, `knowledge_base`, `learning_observer`, `learning_transfer`, `light_engine`, `memory`, `memory_extractor`, `model_router`, `mood_detector`, `multi_room_audio`, `music_dj`, `ocr`, `ollama_client`, `outcome_tracker`, `personality`, `predictive_maintenance`, `pre_classifier`, `proactive`, `proactive_planner`, `protocol_engine`, `recipe_store`, `repair_planner`, `response_quality`, `routine_engine`, `seasonal_insight`, `self_automation`, `self_optimization`, `self_report`, `situation_model`, `smart_shopping`, `sound_manager`, `speaker_recognition`, `spontaneous_observer`, `summarizer`, `task_registry`, `threat_assessment`, `time_awareness`, `timer_manager`, `tts_enhancer`, `visitor_manager`, `web_search`, `websocket`, `wellness_advisor`, `workshop_generator`, `workshop_library`

### God-Object-Indikatoren (Module importiert von >5 anderen)

| Modul | Importiert von |
|-------|---------------|
| `config.py` | **Fast alle Module** (Zentrale Konfiguration) |
| `ha_client.py` | brain.py, function_calling.py, proactive.py, routine_engine.py, light_engine.py, etc. |
| `brain.py` | main.py, websocket.py (nur 2 — aber ES IST das God-Object) |
| `memory.py` | brain.py, main.py, summarizer.py |
| `embeddings.py` | memory.py, semantic_memory.py, knowledge_base.py, recipe_store.py, brain.py, speaker_recognition.py |
| `personality.py` | brain.py (einziger Consumer) |

### Verwaiste Module (potentiell Dead Code)

| Modul | Status |
|-------|--------|
| `shared/schemas/*` | ❌ **DEAD CODE** — von niemandem importiert |
| `shared/constants.py` | ❌ **DEAD CODE** — Konstanten in Assistant/Addon lokal definiert |
| `embedding_extractor.py` | ✅ Wird von `speaker_recognition.py` importiert (Audio-Embeddings, kein Memory) |
| `declarative_tools.py` | ⚠️ Prüfen — möglicherweise nur von brain.py dynamisch geladen |

### 5. Verdrahtungs-Graph (Ergänzung)

Vollständige per-Modul Import-Tabelle basierend auf `grep "^from \.|^import \." assistant/assistant/`:

| Modul | Importiert | Wird importiert von |
|-------|-----------|---------------------|
| `action_planner.py` | config, function_calling, function_validator, ollama_client, websocket | brain.py |
| `activity.py` | config, ha_client | brain.py |
| `adaptive_thresholds.py` | config | brain.py |
| `ambient_audio.py` | *(keine internen)* | brain.py, main.py (lazy) |
| `anticipation.py` | config | brain.py |
| `autonomy.py` | config | brain.py, conflict_resolver.py, main.py (lazy) |
| `brain.py` | **80+ Module** (siehe Import-Karte oben) | main.py, websocket.py (indirekt) |
| `brain_callbacks.py` | *(Mixin)* | brain.py |
| `brain_humanizers.py` | *(Mixin)* | brain.py |
| `calendar_intelligence.py` | config | brain.py |
| `camera_manager.py` | config, ha_client, ollama_client | brain.py |
| `circuit_breaker.py` | *(keine internen)* | ha_client.py, ollama_client.py, brain.py |
| `climate_model.py` | config | brain.py, main.py (lazy) |
| `conditional_commands.py` | *(config)* | brain.py |
| `config.py` | *(stdlib/ext only)* | **fast alle Module** (~50+) |
| `config_versioning.py` | config, constants | brain.py, self_optimization.py, function_calling.py |
| `conflict_resolver.py` | config, autonomy, ollama_client | brain.py |
| `constants.py` | *(keine)* | brain.py, health_monitor.py, sound_manager.py, feedback.py, config_versioning.py, ollama_client.py |
| `context_builder.py` | config, function_calling, ha_client, semantic_memory | brain.py |
| `conversation_memory.py` | config | brain.py |
| `cooking_assistant.py` | config | brain.py |
| `correction_memory.py` | config | brain.py |
| `cover_config.py` | *(config-Datei)* | main.py, function_calling.py, proactive.py |
| `declarative_tools.py` | config | function_calling.py, spontaneous_observer.py (lazy) |
| `device_health.py` | config, function_calling, ha_client | brain.py |
| `diagnostics.py` | config, function_calling, ha_client | brain.py |
| `dialogue_state.py` | config | brain.py |
| `embeddings.py` | config | memory.py, semantic_memory.py, knowledge_base.py, recipe_store.py, brain.py (alle lazy) |
| `embedding_extractor.py` | *(ext only)* | speaker_recognition.py |
| `energy_optimizer.py` | config, ha_client | brain.py |
| `error_patterns.py` | config | brain.py |
| `explainability.py` | *(config)* | brain.py |
| `feedback.py` | config, constants | brain.py |
| `file_handler.py` | *(stdlib)* | main.py, brain.py (lazy), memory.py (lazy), ocr.py (lazy) |
| `follow_me.py` | config, ha_client | brain.py |
| `function_calling.py` | config, config_versioning, declarative_tools, ha_client | brain.py, context_builder.py, action_planner.py, device_health.py, diagnostics.py |
| `function_validator.py` | config | brain.py, action_planner.py |
| `ha_client.py` | circuit_breaker, config | brain.py, context_builder.py, sound_manager.py, routine_engine.py, light_engine.py, self_automation.py, insight_engine.py, spontaneous_observer.py, threat_assessment.py, time_awareness.py, follow_me.py, energy_optimizer.py, multi_room_audio.py, camera_manager.py, device_health.py, diagnostics.py, smart_shopping.py, activity.py |
| `health_monitor.py` | config, constants | brain.py |
| `insight_engine.py` | config, ha_client | brain.py |
| `intent_tracker.py` | config, ollama_client | brain.py |
| `inventory.py` | *(config)* | brain.py |
| `knowledge_base.py` | config, embeddings (lazy) | brain.py, recipe_store.py |
| `learning_observer.py` | config | brain.py, spontaneous_observer.py (lazy) |
| `learning_transfer.py` | config | brain.py |
| `light_engine.py` | config, ha_client, function_calling | brain.py |
| `main.py` | brain, config, cover_config, file_handler, request_context, websocket | *(Entry Point)* |
| `memory.py` | config, semantic_memory, embeddings (lazy) | brain.py, main.py, summarizer.py |
| `memory_extractor.py` | config, ollama_client, semantic_memory | brain.py |
| `model_router.py` | config | brain.py |
| `mood_detector.py` | config | brain.py |
| `multi_room_audio.py` | config, ha_client | brain.py |
| `music_dj.py` | config | brain.py |
| `ocr.py` | config, file_handler (lazy) | brain.py |
| `ollama_client.py` | circuit_breaker, config, constants | brain.py, self_automation.py, self_optimization.py, memory_extractor.py, protocol_engine.py, conflict_resolver.py, intent_tracker.py, action_planner.py, summarizer.py, routine_engine.py, camera_manager.py |
| `outcome_tracker.py` | *(config)* | brain.py |
| `personality.py` | config | brain.py |
| `pre_classifier.py` | *(config)* | brain.py |
| `predictive_maintenance.py` | config | brain.py, main.py (lazy) |
| `proactive.py` | websocket, cover_config (lazy) | brain.py |
| `proactive_planner.py` | config | brain.py |
| `protocol_engine.py` | config, ollama_client | brain.py |
| `recipe_store.py` | config, knowledge_base, embeddings (lazy) | brain.py |
| `repair_planner.py` | config, websocket (lazy) | brain.py |
| `request_context.py` | *(stdlib)* | main.py |
| `response_quality.py` | config | brain.py |
| `routine_engine.py` | config, ha_client, ollama_client, websocket | brain.py |
| `seasonal_insight.py` | config | brain.py |
| `self_automation.py` | config, ha_client, ollama_client | brain.py |
| `self_optimization.py` | config, config_versioning, ollama_client | brain.py |
| `self_report.py` | config | brain.py |
| `semantic_memory.py` | config, embeddings (lazy) | memory.py, context_builder.py, memory_extractor.py, brain.py (lazy) |
| `situation_model.py` | *(config)* | brain.py |
| `smart_shopping.py` | config, ha_client | brain.py |
| `sound_manager.py` | config, constants, ha_client | brain.py |
| `speaker_recognition.py` | embedding_extractor | brain.py |
| `spontaneous_observer.py` | config, ha_client, learning_observer (lazy), declarative_tools (lazy) | brain.py |
| `summarizer.py` | config, ollama_client | brain.py |
| `task_registry.py` | *(config)* | brain.py |
| `threat_assessment.py` | config, ha_client | brain.py |
| `time_awareness.py` | config, ha_client | brain.py |
| `timer_manager.py` | config | brain.py |
| `tts_enhancer.py` | config | brain.py |
| `visitor_manager.py` | config | brain.py |
| `web_search.py` | config | brain.py |
| `websocket.py` | *(stdlib/ext)* | brain.py, main.py, action_planner.py, routine_engine.py, proactive.py, repair_planner.py (lazy), workshop_generator.py (lazy) |
| `wellness_advisor.py` | config | brain.py |
| `workshop_generator.py` | websocket (lazy) | brain.py |
| `workshop_library.py` | *(config)* | brain.py |

**Stern-Topologie bestätigt**: 65 von 88 Modulen werden **ausschließlich** von brain.py importiert. `config.py` und `ha_client.py` sind die einzigen echten Utility-Hubs.

### Zirkuläre Abhängigkeiten

Keine **direkten** zirkulären Imports gefunden. brain.py ist ein Stern-Pattern: alles zeigt auf brain.py, brain.py zeigt auf alles, aber die Module kennen sich untereinander kaum. Dies verhindert Zyklen, **erzwingt aber** das God-Object-Pattern.

### Isolierte Inseln

| Insel | Module | Verbindung zum Rest |
|-------|--------|---------------------|
| **Addon komplett** | 67 Module, SQLite, eigener Event-Bus | Nur HTTP Chat-Proxy zum Assistant |
| **Speech-Server** | server.py, handler.py | Wyoming TCP + Redis Embedding-Cache |
| **HA-Integration** | 3 Dateien | HTTP POST an Assistant |

---

## 5. Vorverarbeitung (Pre-Classifier & Request Context)

### pre_classifier.py

**5 Request-Profile** (Zeile 267–269 für Memory-Keywords):
1. **DEVICE_FAST** — Einfache Gerätebefehle → Fast 3B Model
2. **DEVICE_QUERY** — Gerätestatus-Fragen → Fast 3B Model
3. **MEMORY** — Erinnerungsfragen ("was habe ich gestern...") → Smart 14B Model
4. **KNOWLEDGE** — Wissensfragen → Smart 14B Model
5. **GENERAL** — Alles andere → Smart 14B Model

**Auswirkung**: Bestimmt Modell-Wahl über `model_router.py` (Fast 3B → Smart 14B → Deep 32B).

### request_context.py

Wurde **nicht gefunden** — ist in der Modul-Liste aufgeführt aber offenbar in brain.py integriert (der Context wird direkt in `process()` aufgebaut).

---

## 6. Architektur-Bewertung

### Stärken

1. **Graceful Degradation** (F-069): `_safe_init()` Pattern für 32 non-critical Module — System startet auch mit Teilausfällen
2. **Shortcut-Architektur**: 20+ deterministische Fast-Paths vermeiden unnötige LLM-Calls und reduzieren Latenz
3. **Token-Budgetierung**: P1-P4 Priority-System für System-Prompt Assembly verhindert Context-Window-Overflow
4. **Model-Routing**: 3-Tier Cascade (3B → 14B → 32B) optimiert Kosten/Qualität pro Request-Typ
5. **Safety-First im Addon**: Confidence-basierte Automation mit Domain-spezifischen Thresholds, Undo-Window

### Fundamentale Schwächen

1. **🔴 Zwei unkoordinierte Akteure**: Assistant und Addon steuern dieselben HA-Entities ohne Wissen voneinander (153 + 107 call_service Aufrufe)
2. **🔴 God-Object brain.py**: 10.231 Zeilen, 80+ Imports, process() allein 4.838 Zeilen — jede Änderung birgt Regressions-Risiko
3. **🔴 Shared Schemas = Dead Code**: Die "API-Verträge" werden von niemandem importiert, die tatsächlichen Schemas divergieren
4. **🔴 Memory-Silos**: 12 isolierte Memory-Systeme im Assistant + separates SQLite im Addon, brain.py als einziger (fehlerhafter) Integrationspunkt
5. **🟠 Kein zentrales Event-System**: Weder innerhalb des Assistants noch service-übergreifend gibt es ein Priority-System für konkurrierende Aktionen

---

## 7. Top-5 Architektur-Änderungen mit höchstem Impact

| # | Änderung | Severity | Impact |
|---|----------|----------|--------|
| 1 | **Assistant ↔ Addon Koordination**: Zentraler Action-Broker oder Addon-Lock-Mechanismus — beide Services müssen vor HA-Calls prüfen ob der andere gerade agiert | 🔴 KRITISCH | Verhindert Race Conditions auf HA-Entities |
| 2 | **brain.py aufbrechen**: process() in Pipeline-Stages extrahieren (PreProcess → Context → LLM → ToolExecution → PostProcess) mit klaren Interfaces | 🔴 KRITISCH | Wartbarkeit, Testbarkeit, Regressions-Risiko |
| 3 | **Shared Schemas enforced**: Löschen der lokalen Definitionen, Import aus `/shared/`, CI-Check dass alle Services dasselbe Schema nutzen | 🔴 KRITISCH | Verhindert stille API-Inkompatibilitäten |
| 4 | **Memory-Stack konsolidieren**: Memory-Facade vor den 12 Einzelsystemen, Query-Router der weiß wo welche Info liegt | 🟠 HOCH | Jarvis "erinnert" sich konsistent |
| 5 | **Event-Bus für Assistant**: Proactive, Routines, Callbacks, Shortcuts über zentrale Event-Queue statt direkte brain.py-Methoden | 🟠 HOCH | Priority-System, Konfliktvermeidung, Testbarkeit |

---

## 8. Initialize-Sequenz Zusammenfassung

**66 Schritte** in `brain.initialize()` (Zeile 475–783):

| Phase | Schritte | Module | _safe_init()? | Failure = |
|-------|----------|--------|---------------|-----------|
| 1: Core | 1–9 | Memory, ModelRouter, ContextBuilder, Autonomy, Mood, Personality | ❌ NEIN | **FATAL** |
| 2: Background | 10–30 | MemoryExtractor, Feedback, Summarizer, TimeAwareness, LightEngine, RoutineEngine, Anticipation, Speaker, Knowledge, Recipe, Inventory, Shopping, ConvMemory, MultiRoom, SelfAutomation, ConfigVersioning, OCR | ❌ NEIN | **FATAL** |
| **F-069 Boundary** | — | `_safe_init()` Wrapper beginnt | — | — |
| 3: Degradable | 31–62 | 32 Module (Ambient, Conflict, Health, Timer, Cooking, Workshop, Threat, Learning, Protocol, Spontaneous, Music, Visitor, Wellness, Insight, Situation, Proactive, Seasonal, Calendar, Explainability, LearningTransfer, PredictiveMaint, Outcome, Correction, ResponseQuality, ErrorPatterns, SelfReport, Adaptive) | ✅ JA | Graceful: `_degraded_modules` |
| 4: Final | 63–66 | Learning Kill Switch, **ProactiveManager.start()** (⚠️ NICHT safe_init!), Entity Catalog Refresh | Teilweise | Schritt 64 = **FATAL** |

**Kritisch**: Module 1–30 sind **nicht** in `_safe_init()` gewrappt. Jede Exception dort (Redis nicht erreichbar, ChromaDB down, Ollama timeout) crasht den gesamten Start. Zusätzlich ist `ProactiveManager.start()` (Schritt 64) ebenfalls nicht geschützt.

---

## KONTEXT AUS PROMPT 1: Architektur-Analyse

### Konflikt-Karte

- **A (Sprache)**: 3 verschiedene Antwort-Pfade (personality.py, hardcoded proactive, routine templates) — keine Konsistenz
- **B (Aktionen)**: 4+ unabhängige Aktor-Pfade (function_calling, routines, addon automations, addon engines) — kein zentraler Broker
- **C (Wissen)**: 12 isolierte Memory-Silos + getrenntes Addon-SQLite — brain.py als fehlerhafter einziger Integrationspunkt (duplicate key bug)
- **D (Klang)**: Persönlichkeit kommt aus 3 Quellen (personality.py, brain.py shortcuts, response filter) — können sich widersprechen
- **E (Timing)**: Kein zentrales Priority-System, weder intra-service noch inter-service
- **F (Services)**: Shared Schemas = Dead Code, divergierende API-Definitionen, keine State-Synchronisation, Race Conditions auf HA-Entities

### Service-Interaktion

Assistant (PC2, FastAPI, Port 8200) ← HTTP Chat-Proxy ← Addon (PC1, Flask, Port 5000). Beide → HA REST/WS unabhängig. Speech (PC2, Wyoming, Port 10300) → Redis Embeddings → Assistant. HA-Integration → HTTP POST → Assistant. **Kein bidirektionaler State-Sync zwischen Assistant und Addon.**

### Top-5 Architektur-Probleme

1. 🔴 **Zwei unkoordinierte HA-Akteure** — Race Conditions auf Entities
2. 🔴 **God-Object brain.py** (10.231 Zeilen, 4.838-Zeilen process()) — untestbar, Regression bei jeder Änderung
3. 🔴 **Shared Schemas = Dead Code** — API-Verträge existieren nur auf Papier
4. 🔴 **12 Memory-Silos** — kein kohärenter Memory-Stack
5. 🟠 **Kein Event-System** — weder intern noch service-übergreifend

### Architektur-Entscheidung

**brain.py ist eindeutig ein God-Object**. Empfohlenes Pattern: **Pipeline + Event-Bus**. process() in klar getrennte Stages aufbrechen, Module über Events statt direkte Aufrufe koordinieren. Service-übergreifend: Action-Broker der HA-Zugriffe beider Services koordiniert.
