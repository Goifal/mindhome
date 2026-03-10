# Audit-Ergebnis: Prompt 1 — Architektur-Analyse & Modul-Konflikte (Durchlauf #2)

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Drei-Service-Architektur, Modul-Konflikte A–F, Verdrahtungs-Graph, Architektur-Bewertung
**Durchlauf**: #2 (Verifikation nach P6a–P8 Fixes)

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
│   48 Module       │  → /api/assistant/  │  90 Module         │
│   SQLite (68 Tab) │    chat             │  Redis + ChromaDB  │
└─────────┬─────────┘                     └────────┬───────────┘
          │                                        │
          │  GET /api/assistant/                    │  Wyoming ASR (TCP)
          │  entity_owner/{id}                     │  Port 10300
          │  (Advisory Check)                      │
          └────────────────────────────────────────┤
                                          ┌────────┴───────────┐
                                          │  Speech-Server     │
                                          │  (Whisper, PC2)    │
                                          │  2 Module          │
                                          │  Redis (Embeddings)│
                                          └────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  HA-Integration (Custom Component)                              │
│  ha_integration/custom_components/mindhome_assistant/           │
│  conversation.py → HTTP POST → Assistant /api/assistant/chat    │
│  = HA Voice Pipeline Bridge                                     │
└─────────────────────────────────────────────────────────────────┘
```

### Kommunikationskanaele

| Von | Nach | Protokoll | Code-Referenz |
|-----|------|-----------|---------------|
| HA-Integration | Assistant | HTTP POST `/api/assistant/chat` | `conversation.py:108-109` |
| Addon | Assistant | HTTP POST (Proxy) `/api/assistant/chat` | `routes/chat.py:159` |
| Addon | Assistant | GET `/api/assistant/entity_owner/{id}` (Advisory) | `ha_connection.py:177` |
| Assistant | HA | REST API + WebSocket (Events) | `ha_client.py`, `proactive.py` |
| Addon | HA | REST API (`/core/api/`) + WebSocket (Events) | `ha_connection.py:69-147` |
| Speech | Redis | Voice Embeddings (`mha:speaker:*`) | `speech/handler.py:410-426` |
| Assistant | Redis | Memory, State, Embeddings | `memory.py`, `semantic_memory.py` |

### Aenderungen seit Durchlauf #1

- **shared/ geloescht** — Keine gemeinsamen Schemas mehr. Jeder Service definiert eigene Datenstrukturen.
- **Entity-Ownership-Check im Addon** — `ha_connection.py:177` prueft via HTTP GET ob der Assistant eine Entity "besitzt". Ist aber **advisory** (Timeout 2s, bei Fehler wird trotzdem gehandelt).

---

## 2. God-Object-Analyse

### 2a) brain.py — Primaeres God-Object

| Metrik | Durchlauf #1 | Durchlauf #2 | Delta |
|--------|-------------|-------------|-------|
| **Zeilen** | 10.231 → 9.779 (nach Mixin) | 9.800 | +21 |
| **Imports** | 81 interne Module | 81 interne Module | 0 |
| **Methoden** | 80+ | 68+ direkt + 15 Mixin | 0 |
| **_process_inner()** | ~4.838 Zeilen | ~4.700 Zeilen | -138 |
| **Init-Komponenten** | 50+ Objekte | 50+ Objekte | 0 |
| **Locks** | 0 | 2 (asyncio.Lock) | +2 ✅ |

**Bewertung**: brain.py ist weiterhin ein God-Object. Die Mixin-Extraktion (Phase 1: `brain_humanizers.py` 502Z, `brain_callbacks.py` 29Z) hat 531 Zeilen ausgelagert, aber das Grundproblem besteht: Ein monolithischer `_process_inner()` mit ~4.700 Zeilen.

**Positiv seit Durchlauf #1:**
- `_process_lock` (asyncio.Lock) schuetzt alle per-Request-State-Variablen ✅
- `_states_lock` (asyncio.Lock) schuetzt HA-States-Cache ✅
- 36 von 37 Modulen in `_safe_init()` gewrappt ✅

**Kritischer Bug (NEU):**
- **ProactiveManager.start() (Zeile 773) ist NICHT in `_safe_init()` gewrappt** — identisch zu Durchlauf #1!
- Der Bug wurde in RESULT_06a als "gefixt" gemeldet, ist aber im aktuellen Code NICHT gefixt.
- Wenn HA nicht erreichbar ist beim Start → Exception → gesamter Start schlaegt fehl.
- **Severity**: 🔴 KRITISCH — Verletzung von F-069 Graceful Degradation.

### 2b) main.py — Sekundaeres God-Object

| Metrik | Durchlauf #1 | Durchlauf #2 | Delta |
|--------|-------------|-------------|-------|
| **Zeilen** | ~7.809 | 8.228 | +419 |
| **API-Endpoints** | ~200 | 270 | +70 |
| **brain.process() Aufrufe** | ~6 | 6 | 0 |

**Bewertung**: main.py ist GEWACHSEN und noch staerker ein God-Object. Es enthaelt:
- 270 API-Endpoints in einer einzigen Datei
- Signifikante Business-Logik (PIN-Auth, Settings-Reload, Cover-Management, Workshop 70+ Endpoints)
- Error/Activity-Buffer-System mit Redis-Persistenz

**Aufspaltungs-Empfehlung:**
```
main.py (8.228Z) → Aufspaltung in:
├── main.py (~500Z)          — Nur Route-Registration, Lifespan
├── auth.py (~500Z)          — PIN, Tokens, API-Keys, Rate-Limiting
├── settings_routes.py (~300Z) — Settings-CRUD und Validation
├── cover_routes.py (~300Z)  — Cover/Blind-Management
├── workshop_routes.py (~400Z) — Workshop-Endpoints
├── system_routes.py (~400Z) — Git, Docker, Ollama Ops
└── buffer_manager.py (~150Z) — Error/Activity Ring-Buffer
```

---

## 3. Konflikt-Karten (A–F)

### Konflikt A: Wer bestimmt was Jarvis SAGT?

| Modul | Was es tut | Wie es die Antwort beeinflusst | Koordination mit anderen? |
|---|---|---|---|
| `personality.py` | Sarkasmus (1-4), Humor, Running Gags, Formality | Build-System-Prompt mit dynamischen Sektionen (~850 Token) | Liest mood_detector, gibt Prompt an LLM |
| `context_builder.py` | Baut den System-Prompt (HA-States, Wetter, Kalender) | Sammelt parallel Kontext, baut P1-P4 Prompt-Sektionen | Liest semantic_memory, function_calling, ha_client |
| `mood_detector.py` | Erkennt User-Stimmung aus Text/Voice | Beeinflusst personality.py Sarkasmus-Level | Wird von personality.py gelesen |
| `routine_engine.py` | Morning Briefing, Gute-Nacht Templates | In P6c auf Jarvis-Stil angepasst | Eigene LLM-Calls (nicht via brain.process) |
| `proactive.py` | CRITICAL-Alerts, Proaktive Nachrichten | **Hardcoded Templates fuer CRITICAL** (Latenz <100ms) | Kein personality.py, eigene Templates |
| `situation_model.py` | Situations-Kontext (Schlaf, Arbeit, Party) | Liefert Kontext-String fuer System-Prompt | Wird von brain.py gelesen |
| `time_awareness.py` | Tageszeit, Feiertage, Jahreszeiten | Liefert Zeitkontext fuer System-Prompt | Wird von brain.py gelesen |

**Zusammenfassung:** personality.py + context_builder.py + brain.py bilden die Haupt-Pipeline. Die meisten Module liefern nur Kontext. **Proactive CRITICAL-Alerts umgehen die Pipeline bewusst** (Latenz-Entscheidung). Error-Meldungen in main.py wurden in P8 auf generische Jarvis-Texte angepasst (71 Stellen). **Status: ⚠️ Teilweise geloest** — CRITICAL-Pfad bewusst belassen, 3 variierende Error-Meldungen eingefuehrt.

### Konflikt B: Wer bestimmt was Jarvis TUT?

| Modul | Was es tut | Wann es handelt | Koordination mit anderen? |
|---|---|---|---|
| `function_calling.py` | Direkte HA-Aktionen via Tool-Calls | Bei LLM-generiertem Tool-Call | Validiert durch function_validator |
| `function_validator.py` | Validiert Function Calls (Bereiche, Typen) | Vor Ausfuehrung | Prueft Trust-Level |
| `action_planner.py` | Multi-Step-Planung | Bei komplexen Anfragen | Nutzt function_calling + ollama |
| `anticipation.py` | Vorausschauend handeln (Confidence-Schwellen) | Bei hoher Confidence (>0.95 fuer auto) | Schreibt Vorschlaege, brain.py entscheidet |
| `autonomy.py` | Entscheidet OB gehandelt wird | Bei jedem proaktiven Handlungsvorschlag | Trust-Level-basiert |
| `self_automation.py` | Generiert HA-Automationen aus NL | Bei User-Request | Rate-Limited, Whitelist |
| `routine_engine.py` | Feste Ablaeufe (Morning, Gute-Nacht) | Zeitgesteuert | Eigene HA-Calls |
| `conditional_commands.py` | If/Then-Automationen | Event-getriggert | Eigene Ausfuehrung |
| `conflict_resolver.py` | Loest Konflikte zwischen Intents | Bei konkurrierenden Aktionen | Nutzt autonomy + ollama |
| **Addon: automation_engine.py** | Pattern-basierte Automationen | Bei erkanntem Pattern + Confidence | **Advisory Entity-Ownership-Check** |
| **Addon: 21 Domain-Module** | Direkte HA-Steuerung (Licht, Klima, Cover) | Bei state_changed Events | **Advisory Entity-Ownership-Check** |
| **Addon: circadian.py** | Zirkadiane Lichtsteuerung | Periodisch (alle 5 Min) | **KEINE Koordination mit light_engine.py** |
| **Addon: cover_control.py** | Rollladen-Automatik | Bei Sonnenstand/Wetter-Events | **KEINE Koordination mit cover_config.py** |

**🔴 KRITISCH: Addon ↔ Assistant Entity-Kollision**
- Addon `circadian.py` steuert **dieselben Lichter** wie Assistant `light_engine.py`
- Addon `cover_control.py` steuert **dieselben Rolllaeden** wie Assistant `cover_config.py`
- Addon hat einen **Advisory** Entity-Ownership-Check (`ha_connection.py:177`), aber:
  - Timeout: 2 Sekunden — bei Nichterreichbarkeit handelt der Addon trotzdem
  - Kein transaktionales Locking — Race Condition moeglich
  - Last-Write-Wins — wer zuletzt schreibt, gewinnt
  - Kein Back-Channel vom Addon zum Assistant bei Konflikten
- **Status seit Durchlauf #1: UNVERAENDERT** — Entity-Ownership-Check existiert, ist aber advisory und nicht enforced.

### Konflikt C: Wer bestimmt was Jarvis WEISS?

| Modul | Datenquelle | Wird von anderen gelesen? | Synchronisiert? |
|---|---|---|---|
| `memory.py` | Redis (Working Memory, 50 Eintraege, 7d TTL) | brain.py, summarizer.py | Ja (Redis) |
| `semantic_memory.py` | ChromaDB + Redis (Langzeit-Fakten) | context_builder, memory_extractor | Ja (ChromaDB + Redis-Fallback) ✅ |
| `conversation_memory.py` | Redis (mha:memory:*) | brain.py | Ja (Redis) |
| `memory_extractor.py` | Ollama LLM → semantic_memory | brain.py (fire-and-forget) | Async, eventual consistency |
| `correction_memory.py` | Redis (mha:correction_memory:*) | brain.py | Ja (Redis, mit Lock seit P6b) ✅ |
| `dialogue_state.py` | In-Memory Dict (max 50 Eintraege) | brain.py | **Nein — Verlust bei Restart** |
| `learning_observer.py` | Redis (mha:learning:*) | brain.py, proactive.py | Ja (Redis) |
| `learning_transfer.py` | Redis + In-Memory pending (max 50) | brain.py | Teilweise (pending nur in-memory) |
| `knowledge_base.py` | ChromaDB (mha_knowledge_base) | brain.py | Ja (ChromaDB) |
| `context_builder.py` | Liest aus allen obigen + HA | brain.py | Read-only Aggregator |
| **Addon: pattern_engine.py** | SQLite (state_history) | Addon-intern | **KEINE Synchronisierung mit Assistant** |
| **Addon: db.py / models.py** | SQLite (68 Tabellen) | Addon-intern | **KEINE Synchronisierung mit Assistant** |

**Zusammenfassung:** 12 weitgehend isolierte Memory-Systeme im Assistant, zusammengehalten nur durch brain.py. Addon hat **komplett separate Datenhaltung** (SQLite) ohne jegliche Synchronisierung mit dem Assistant. **Status seit Durchlauf #1: UNVERAENDERT** — kein kohaerenter Memory-Stack, kein Wissensaustausch Addon↔Assistant.

### Konflikt D: Wie Jarvis KLINGT

| Modul | Was es steuert | Code-Referenz | Status |
|---|---|---|---|
| `personality.py` | Charakter, Sarkasmus (gedeckelt auf 4), Formality | `personality.py:118, 240-284` | ✅ MCU-Score 8/10 |
| `mood_detector.py` | Ton-Anpassung an User-Stimmung | `mood_detector.py` (mit asyncio.Lock) | ✅ Thread-safe |
| `context_builder.py` | System-Prompt-Zusammenbau mit P1-P4 Priorisierung | `context_builder.py:216, 928` | ✅ Parallel async |
| `tts_enhancer.py` | TTS-Anpassungen (Emotion, Pausen, Speed) | `tts_enhancer.py` | ✅ Funktioniert |
| `sound_manager.py` | Audio-Wiedergabe, Auto-Volume | `sound_manager.py` | ✅ Funktioniert |
| `multi_room_audio.py` | Raum-spezifische Ausgabe | `multi_room_audio.py` | ✅ Funktioniert |

**Status: ✅ Weitgehend geloest** — Sarkasmus auf Level 4 gedeckelt, Weather-Kontext-Bug repariert, Error-Meldungen auf Jarvis-Stil angepasst.

### Konflikt E: Timing & Prioritaeten

| Szenario | Was passiert? | Code-Referenz | Status |
|---|---|---|---|
| Proaktive Warnung WAEHREND User spricht | `_process_lock` serialisiert — Warnung wartet | `brain.py:1103` | ✅ Geloest |
| Morgen-Briefing WAEHREND Konversation laeuft | `_mb_triggered_today` mit asyncio.Lock | `proactive.py` | ✅ Geloest (P6b) |
| Zwei autonome Aktionen gleichzeitig | `_process_lock` serialisiert | `brain.py:1103` | ✅ Geloest |
| anticipation + function_calling gleichzeitig | Sequenziell im _process_inner() | `brain.py` | ✅ Kein Konflikt |
| Addon-Automation + Assistant-Aktion gleichzeitig | **Advisory Check, kein Locking** | `ha_connection.py:177` | 🔴 OFFEN |
| Addon-Event + Proactive.py gleichzeitig | **Keine Koordination** | — | 🔴 OFFEN |

**Status seit Durchlauf #1:** Die internen Konflikte (innerhalb des Assistant) sind durch `_process_lock` und Module-Level-Locks geloest. Die **cross-service Konflikte** (Addon vs Assistant) sind **UNVERAENDERT** offen.

### Konflikt F: Assistant ↔ Addon Interaktion

| Frage | Antwort | Code-Referenz |
|---|---|---|
| Wie kommunizieren Assistant und Addon? | HTTP REST (Chat-Proxy + Entity-Owner-Check) | `routes/chat.py:159`, `ha_connection.py:177` |
| Steuern beide dieselben HA-Entities? | **JA** — Lichter, Rolllaeden, Klima | `circadian.py` vs `light_engine.py`, `cover_control.py` vs `cover_config.py` |
| Hat der Addon seinen eigenen HA-State-Cache? | Ja — via fresh `get_states()` REST calls (nicht gecacht) | `ha_connection.py` |
| Kennt der Assistant den Addon-State? | **NEIN** — keine Rueckkanal-Information | — |
| Kennt der Addon die Assistant-Entscheidungen? | **Minimal** — Advisory Entity-Ownership GET | `ha_connection.py:177` |
| Wer hat Vorrang? | **Niemand** — Last-Write-Wins | — |
| Koennen Addon-Automationen die Assistant-Logik unterlaufen? | **JA** — Addon kann jederzeit Entities steuern | `automation_engine.py:_execute_action()` |
| Nutzen beide denselben Redis? | **NEIN** — Addon nutzt kein Redis | — |

**Status seit Durchlauf #1: UNVERAENDERT** — Entity-Ownership-Check existiert als Advisory, keine echte Koordination.

---

## 4. Verdrahtungs-Graph

### 4.1 Import-Hierarchie (5 Schichten)

```
SCHICHT 5: ENTRY POINT
  main.py (7 Imports) → brain, config, constants, cover_config, file_handler, request_context, websocket

SCHICHT 4: ORCHESTRATOR
  brain.py (81 Imports!) → ALLE 81 internen Module

SCHICHT 3: KOORDINATOREN (5 Module)
  action_planner (5 Imports) → config, function_calling, function_validator, ollama_client, websocket
  context_builder (4 Imports) → config, function_calling, ha_client, semantic_memory
  light_engine (3 Imports) → config, ha_client, function_calling
  device_health (3 Imports) → config, ha_client, function_calling
  diagnostics (3 Imports) → config, ha_client, function_calling

SCHICHT 2: FEATURE-MODULE (25+ Module mit 2-4 Imports)
  Jeweils: config + ha_client/ollama_client + ggf. 1-2 weitere

SCHICHT 1: LEAF-MODULE (42+ Module mit 1 Import: nur config)
  Pure Funktionalitaet, keine Cross-Module-Dependencies

SCHICHT 0: INFRASTRUKTUR (6 Module — importieren nichts Internes)
  config, constants, circuit_breaker, websocket, request_context, cover_config
```

### 4.2 God-Object-Indikatoren (importiert von 10+ Modulen)

| Modul | Importiert von | Status |
|---|---|---|
| `config` | **74 Module** | 🔴 MEGA-GOD-OBJECT |
| `ha_client` | 21 Module | 🟠 Hoch, aber erwartbar (HA-API) |
| `ollama_client` | 12 Module | 🟡 Akzeptabel (LLM-API) |
| `constants` | 8 Module | ✅ Normal |
| `function_calling` | 6 Module | ✅ Normal |
| `websocket` | 5 Module | ✅ Normal |

### 4.3 Verwaiste Module (importiert von NIEMANDEM)

| Modul | Erwartung | Status |
|---|---|---|
| `main.py` | Entry Point — korrekt nicht importiert | ✅ OK |
| `embeddings.py` | Importiert nur von brain.py via Aufruf, nicht via Import | ⚠️ Pruefen ob tatsaechlich genutzt |

### 4.4 Zirkulaere Abhaengigkeiten

**KEINE GEFUNDEN** — ✅ Exzellente Architektur-Disziplin. Sauberer DAG (Directed Acyclic Graph).

### 4.5 Fehlende Verbindungen (Semantische Luecken)

| # | Luecke | Betroffene Module | Impact |
|---|--------|-------------------|--------|
| 1 | **Memory-Silos** | 9 Memory-Module kennen sich nicht | Kein kohaerenter Memory-Stack |
| 2 | **Wahrnehmungs-Isolation** | activity, ambient_audio, threat_assessment, spontaneous_observer | Keine vereinheitlichte Sensor-Interpretation |
| 3 | **Zeit-Isolation** | time_awareness, timer_manager, calendar_intelligence, seasonal_insight | Kein geteilter zeitlicher Kontext |
| 4 | **Persoenlichkeits-Isolation** | personality, mood_detector, speaker_recognition | Emotion/Stimmung/Erkennung nicht verknuepft |
| 5 | **Komfort-Isolation** | climate_model, energy_optimizer, light_engine | Keine koordinierte Optimierung |
| 6 | **Proactive ↔ Perception** | proactive importiert NICHT spontaneous_observer/activity | Proaktivitaet nicht umgebungsbewusst |

### 4.6 Addon-Architektur

**✅ EXZELLENT** — Sauberes Plugin-Pattern:
- 21 Domain-Module erben alle von `base.py`
- 14 Engines unabhaengig voneinander
- 13 HTTP-Routes sauber getrennt
- **Null Cross-Domain-Imports** — vorbildlich

---

## 5. Vorverarbeitung (Schritt 5)

### 5.1 Pre-Classifier (`pre_classifier.py`)

**Funktion:** Leichtgewichtige Anfrage-Klassifikation VOR Context-Build. Regex/Keyword-basiert.

**Profile:**
| Profil | Wann | Welche Subsysteme DEAKTIVIERT |
|--------|------|-------------------------------|
| `DEVICE_FAST` | "Licht an", ≤8 Woerter, Verb-Start | Mood, Formality, Irony, RAG, Summary, Activity, Memories |
| `DEVICE_QUERY` | "Wie warm ist es?", ≤10 Woerter | Mood, Formality, Irony, RAG, Summary |
| `KNOWLEDGE` | "Was ist...", ohne Smart-Home-Bezug | House-Status, Activity, Room-Profile |
| `MEMORY` | "Erinnerst du dich..." | House-Status, Activity, Room-Profile |
| `GENERAL` | Alles andere | Nichts deaktiviert (volle Pipeline) |

**Bewertung:** ✅ Sauber implementiert, gute Latenz-Optimierung. Word-Boundary-Matching fuer kurze Woerter ("an", "aus"). Embedded-Verb-Erkennung fuer konjugierte Formen.

### 5.2 Request Context (`request_context.py`)

**Funktion:** Request-ID-Tracing + Structured Logging Middleware.

**Features:**
- `ContextVar` fuer Request-ID (asyncio-kompatibel)
- X-Request-ID Header-Propagation
- Structured Log-Format mit Request-ID
- ✅ Kein Business-Logic — rein infrastrukturell, korrekt implementiert.

---

## 6. Architektur-Bewertung

### 6.1 Staerken der aktuellen Architektur

1. **Null zirkulaere Abhaengigkeiten** — sauberer 5-Schichten-DAG
2. **Addon-Architektur vorbildlich** — Plugin-Pattern, keine Cross-Domain-Imports
3. **Graceful Degradation** — 36/37 Module in `_safe_init()`, `_degraded_modules` Liste
4. **Thread-Safety verbessert** — `_process_lock` und `_states_lock` in brain.py, Locks in 12+ Modulen
5. **Security solide** — PIN-Brute-Force-Schutz, Error-Detail-Leak-Fixes, Path-Traversal-Schutz
6. **Pre-Classifier** — Effektive Latenz-Optimierung fuer einfache Befehle

### 6.2 Fundamentale Schwaechen

1. **🔴 brain.py bleibt God-Object** — 9.800 Zeilen, 81 Imports, 50+ Komponenten, 4.700-Zeilen-Methode
2. **🔴 main.py waechst** — 8.228 Zeilen, 270 Endpoints, signifikante Business-Logik in einer Datei
3. **🔴 config.py ist Mega-God-Object** — 74 Module importieren config. Ein Fehler betrifft 90% des Systems.
4. **🔴 Addon↔Assistant Koordination fehlt** — Advisory Entity-Check ist nicht ausreichend
5. **🟠 Memory-Silos** — 12 isolierte Systeme ohne kohaerenten Stack

### 6.3 Top-5 Architektur-Aenderungen mit hoechstem Impact

| # | Aenderung | Severity | Impact | Aufwand |
|---|-----------|----------|--------|---------|
| 1 | **ProactiveManager.start() in _safe_init() wrappen** | 🔴 | Verhindert fatalen Startup-Crash | 1 Zeile |
| 2 | **main.py aufspalten** (8.228Z → 7 Module) | 🟠 | Wartbarkeit, Code-Reviews, Testing | 2-3 Tage |
| 3 | **config.py aufspalten** (74 Importeure → 6 Sub-Configs) | 🟠 | Blast-Radius reduzieren, Coupling senken | 3-5 Tage |
| 4 | **brain.py _process_inner() dekomponieren** (4.700Z → 10 Phasen) | 🟠 | Testbarkeit, Lesbarkeit | 2-3 Tage |
| 5 | **Addon↔Assistant Event-Bus** (oder Shared Redis) | 🟡 | Entity-Konflikte eliminieren | 5-7 Tage |

---

## 7. Vergleich mit Durchlauf #1

### Was sich VERBESSERT hat:
- ✅ `_process_lock` in brain.py (Race Conditions eliminiert)
- ✅ `_states_lock` in brain.py (Cache-Korruption verhindert)
- ✅ 12+ Locks in Modulen (personality, proactive, mood_detector, event_bus, fire_water, etc.)
- ✅ 136 `except Exception: pass` → `logger.debug()` (Debugging verbessert)
- ✅ 71 Error-Detail-Leaks gefixt
- ✅ Redis-bytes-Decode an 10+ Stellen
- ✅ shared/ Dead Code entfernt

### Was sich NICHT verbessert hat:
- ❌ brain.py ist immer noch ~9.800 Zeilen (Ziel war weitere Mixin-Extraktion)
- ❌ main.py ist GEWACHSEN (7.809 → 8.228 Zeilen)
- ❌ ProactiveManager.start() ist immer noch NICHT in _safe_init() (Regression oder nie gefixt)
- ❌ Addon↔Assistant Koordination unveraendert (Advisory Check einziges Mittel)
- ❌ Kein Event-Bus oder Priority-System zwischen Services
- ❌ Kein kohaerenter Memory-Stack
- ❌ config.py immer noch monolithisch (74 Importeure)

### Neue Risiken durch P6-P8 Fixes:
- ⚠️ 12+ neue Locks — potenzielle Deadlock-Gefahr bei verschachtelter Akquisition
- ⚠️ Double-Check-Locking in `function_calling.py` — Python Memory Ordering subtil
- ⚠️ 136 Stellen `except Exception: pass` → `logger.debug()` — Verhaltensaenderung bei Debug-Level

---

## KONTEXT AUS PROMPT 1: Architektur-Analyse

### Konflikt-Karte

- **A (Sprache):** ⚠️ Teilweise geloest — personality.py Pipeline funktioniert, CRITICAL-Alerts bewusst hardcoded, Error-Texte Jarvis-Stil
- **B (Aktionen):** 🔴 Offen — Assistant intern serialisiert (_process_lock), aber Addon↔Assistant Last-Write-Wins
- **C (Wissen):** 🔴 Offen — 12 isolierte Memory-Silos, Addon hat separate SQLite ohne Sync
- **D (Klang):** ✅ Geloest — Sarkasmus gedeckelt, TTS-Pipeline konsistent
- **E (Timing):** ⚠️ Intern geloest — _process_lock serialisiert, aber keine cross-service Queue
- **F (Addon↔Assistant):** 🔴 Offen — Advisory Entity-Check, kein Locking, kein Shared State

### Service-Interaktion

3 Services + HA-Integration. Kommunikation via HTTP REST (Chat-Proxy + Advisory Entity-Owner). Speech via Redis (Embeddings). Kein gemeinsamer Event-Bus. Kein Shared State zwischen Addon und Assistant.

### Top-5 Architektur-Probleme

1. 🔴 **ProactiveManager.start() nicht in _safe_init()** — fataler Startup-Bug
2. 🔴 **Addon↔Assistant Entity-Kollision** — circadian vs light_engine, cover_control vs cover_config
3. 🟠 **brain.py God-Object** — 9.800 Zeilen, 81 Imports, 4.700-Zeilen process()
4. 🟠 **main.py God-Object** — 8.228 Zeilen, 270 Endpoints, Business-Logik
5. 🟠 **config.py Mega-Coupling** — 74 Module importieren config

### Architektur-Entscheidung

**brain.py → Weiter Mixin-Extraktion (Option A):**
- Phase 2: Response-Filter (~600Z), Pattern-Detection (~1.200Z), Memory-Handling
- _process_inner() in 10 Phasen-Methoden dekomponieren
- RequestContext Dataclass statt 11 per-Request-Instanz-Attribute
- Kein Event-Bus (zu grosser Umbau), aber Coordinator-Pattern fuer semantische Gruppen

**main.py → Aufspalten (NEUE Empfehlung Durchlauf #2):**
- 7 Module statt 1 monolithische Datei
- Workshop-Routes separat (70+ Endpoints)
- Auth-Logik in eigenes Modul
