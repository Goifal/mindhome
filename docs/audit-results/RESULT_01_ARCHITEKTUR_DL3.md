# Audit-Ergebnis: Prompt 1 — Architektur-Analyse & Modul-Konflikte (Durchlauf #3)

**Datum**: 2026-03-13
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Drei-Service-Architektur, Modul-Konflikte A–F, Verdrahtungs-Graph, Architektur-Bewertung
**Durchlauf**: #3 (Verifikation nach DL#2, 125 Commits seit 2026-03-10)
**Vergleichsbasis**: DL#2 (Architektur-Analyse: 6 Konflikte, God-Objects, Entity-Ownership Advisory)

---

## DL#2 vs DL#3 Vergleich

### Gesamt-Statistik

```
Konflikte A-F:
  A (Sprache):       ⚠️ TEILWEISE — CRITICAL-Alerts bewusst hardcoded (unveraendert seit DL#2)
  B (Aktionen):      ❌ UNFIXED — Addon↔Assistant Last-Write-Wins (unveraendert)
  C (Wissen):        ❌ UNFIXED — 12 isolierte Memory-Silos (unveraendert)
  D (Klang):         ✅ FIXED — Sarkasmus gedeckelt, TTS-Pipeline konsistent (unveraendert)
  E (Timing):        ⚠️ TEILWEISE — Intern geloest, cross-service offen (unveraendert)
  F (Addon↔Assist):  ⚠️ TEILWEISE — Advisory Entity-Ownership-Check (unveraendert)

God-Objects:
  brain.py:   ❌ UNFIXED — 9.800 → 9.906 Zeilen (+106), 81 Imports, ~4.700Z _process_inner()
  main.py:    ❌ UNFIXED — 8.228 → 8.278 Zeilen (+50), 273 Endpoints (+3)
  config.py:  ❌ UNFIXED — 74 → 75 Module importieren config

Fixes seit DL#2:
  ✅ ProactiveManager.start() JETZT in _safe_init() gewrappt (brain.py:776)
  ❌ Kein bidirektionaler State-Sync
  ❌ Kein Event-Bus zwischen Services
  ❌ Keine main.py Aufspaltung
```

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
          │  (Advisory Check, 2s Timeout)          │
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

### Kommunikationskanaele (unveraendert seit DL#2)

| Von | Nach | Protokoll | Code-Referenz |
|-----|------|-----------|---------------|
| HA-Integration | Assistant | HTTP POST `/api/assistant/chat` | `conversation.py:108-109` |
| Addon | Assistant | HTTP POST (Proxy) `/api/assistant/chat` | `routes/chat.py:159` |
| Addon | Assistant | GET `/api/assistant/entity_owner/{id}` (Advisory) | `ha_connection.py:70-88` |
| Assistant | HA | REST API + WebSocket (Events) | `ha_client.py`, `proactive.py` |
| Addon | HA | REST API (`/core/api/`) + WebSocket (Events) | `ha_connection.py:69-147` |
| Speech | Redis | Voice Embeddings (`mha:speaker:*`) | `speech/handler.py:410-426` |
| Assistant | Redis | Memory, State, Embeddings | `memory.py`, `semantic_memory.py` |

### Aenderungen seit DL#2

- **ProactiveManager.start() gefixt** — Jetzt in `_safe_init()` gewrappt (brain.py:776). DL#2-Finding #1 (🔴 KRITISCH) ist **BEHOBEN**.
- **Keine strukturellen Aenderungen** — Kommunikationskanaele identisch zu DL#2.
- **shared/ weiterhin geloescht** — 0 Imports gefunden (Grep-verifiziert).

---

## 2. God-Object-Analyse

### 2a) brain.py — Primaeres God-Object

| Metrik | DL#1 | DL#2 | DL#3 | Delta DL#2→3 |
|--------|------|------|------|-------------|
| **Zeilen** | 10.231 → 9.779 | 9.800 | 9.906 | +106 |
| **Imports** | 81 | 81 | 81 | 0 |
| **Methoden** | 80+ | 68 + 15 Mixin | 41 direkt + Mixin | Umstrukturiert |
| **_process_inner()** | ~4.838 | ~4.700 | ~4.700 | 0 |
| **Init-Komponenten** | 50+ | 50+ | 47 explizit + Locks | 0 |
| **Locks** | 0 | 2 | 2 | 0 |
| **Per-Request-State** | 11 Variablen | 11 Variablen | 11 Variablen | 0 |

**Bewertung**: brain.py ist weiterhin ein God-Object mit 9.906 Zeilen. Die Mixin-Extraktion bleibt auf Phase 1 (`brain_humanizers.py`, `brain_callbacks.py`). `_process_inner()` ist weiterhin ~4.700 Zeilen.

**Positiv seit DL#2:**
- ✅ **ProactiveManager.start() in _safe_init()** (brain.py:776) — DL#2-Bug BEHOBEN
- ✅ `_process_lock` mit 30s Timeout (brain.py:1117) — korrekt implementiert
- ✅ `_states_lock` fuer HA-Cache (brain.py:212) — stabil

**Per-Request-State-Variablen** (brain.py:351-374, geschuetzt durch _process_lock):

| Zeile | Variable | Typ | Race-Condition-Risiko |
|-------|----------|-----|----------------------|
| 352 | `_last_failed_query` | Optional[str] | Geschuetzt ✅ |
| 355 | `_current_person` | str | Geschuetzt ✅ |
| 358 | `_last_context` | dict | Geschuetzt ✅ |
| 361 | `_last_executed_action` | str | Geschuetzt ✅ |
| 362 | `_last_executed_action_args` | dict | Geschuetzt ✅ |
| 365 | `_request_from_pipeline` | bool | Geschuetzt ✅ |
| 366 | `_active_conversation_mode` | bool | Geschuetzt ✅ |
| 369 | `_last_response_was_snarky` | bool | Geschuetzt ✅ |
| 370 | `_last_humor_category` | Optional[str] | Geschuetzt ✅ |
| 371 | `_active_conversation_topic` | str | Geschuetzt ✅ |
| 374 | `_last_formality_score` | Optional[int] | Geschuetzt ✅ |

### 2b) main.py — Sekundaeres God-Object

| Metrik | DL#1 | DL#2 | DL#3 | Delta DL#2→3 |
|--------|------|------|------|-------------|
| **Zeilen** | ~7.809 | 8.228 | 8.278 | +50 |
| **API-Endpoints** | ~200 | 270 | 273 | +3 |
| **brain.process() Aufrufe** | ~6 | 6 | 5 aktiv + 5 Referenzen | 0 |
| **Private Hilfsfunktionen** | — | — | 97 | — |

**Endpoint-Verteilung (DL#3):**

| Domain | GET | POST | PUT | DELETE | Total | % |
|--------|-----|------|-----|--------|-------|---|
| `/api/ui/*` | 69 | 42 | 13 | 11 | 135 | 49% |
| `/api/workshop/*` | 30 | 50 | 1 | 3 | 84 | 31% |
| `/api/assistant/*` | 25 | 12 | 2 | 1 | 40 | 15% |
| Sonstige | 6 | 6 | 0 | 0 | 14 | 5% |
| **Total** | **130** | **110** | **16** | **15** | **273** | |

**Business-Logik die extrahiert werden sollte:**

| Bereich | Zeilen | Empfohlenes Modul |
|---------|--------|-------------------|
| PIN-Authentifizierung | 2235-2468 (~233Z) | `auth_manager.py` |
| Settings-Reload | 2926-3623 (~697Z) | `config_manager.py` |
| Cover-Management | 3670-4570 (~900Z) | `cover_manager.py` |
| Workshop-Endpoints | 5979-7262 (~1.283Z) | `workshop_routes.py` |
| **Gesamt extrahierbar** | **~3.113 Zeilen** | **4 Module** |

**Bewertung**: main.py waechst weiter (+50 Zeilen). Die empfohlene Aufspaltung aus DL#2 wurde nicht umgesetzt. 49% aller Endpoints sind UI-spezifisch, 31% Workshop — diese koennten sofort extrahiert werden.

### 2c) config.py — Mega-Coupling

| Metrik | DL#2 | DL#3 |
|--------|------|------|
| **Importeure** | 74 Module | 75 Module (+1) |
| **Haeufigster Import** | `yaml_config` | `yaml_config` (38×) |

**Status**: Unveraendert. Ein Fehler in config.py betrifft ~83% aller Module.

---

## 3. Konflikt-Karten (A–F)

### Konflikt A: Wer bestimmt was Jarvis SAGT?

| Modul | Was es tut | Wie es die Antwort beeinflusst | Koordination | Status |
|---|---|---|---|---|
| `personality.py` | Sarkasmus (1-4), Humor, Formality | System-Prompt mit ~850 Token | Liest mood_detector | ✅ |
| `context_builder.py` | System-Prompt (HA-States, Wetter, Kalender) | P1-P4 Prompt-Sektionen parallel | Liest semantic_memory, ha_client | ✅ |
| `mood_detector.py` | User-Stimmung aus Text/Voice | Beeinflusst Sarkasmus-Level | Wird von personality gelesen | ✅ |
| `routine_engine.py` | Morning Briefing, Gute-Nacht | Eigene LLM-Calls, Jarvis-Stil | Nicht via brain.process() | ⚠️ |
| `proactive.py` | CRITICAL-Alerts, Proaktive Nachrichten | **Hardcoded Templates** (<100ms) | Kein personality.py | ⚠️ Bewusst |
| `situation_model.py` | Situations-Kontext | Kontext-String fuer System-Prompt | Wird von brain.py gelesen | ✅ |
| `time_awareness.py` | Tageszeit, Feiertage | Zeitkontext fuer System-Prompt | Wird von brain.py gelesen | ✅ |

**Status DL#3: ⚠️ TEILWEISE — unveraendert seit DL#2.**
Personality-Pipeline funktioniert fuer regulaere Anfragen. CRITICAL-Alerts und routine_engine umgehen die Pipeline bewusst (Latenz / eigenstaendige LLM-Calls).

### Konflikt B: Wer bestimmt was Jarvis TUT?

| Modul | Wann es handelt | Koordination | Status |
|---|---|---|---|
| `function_calling.py` | Bei LLM-Tool-Call | Validiert durch function_validator | ✅ Intern |
| `function_validator.py` | Vor Ausfuehrung | Prueft Trust-Level | ✅ |
| `action_planner.py` | Bei komplexen Anfragen | Nutzt function_calling + ollama | ✅ |
| `anticipation.py` | Bei Confidence >0.95 | brain.py entscheidet | ✅ |
| `autonomy.py` | Bei proaktivem Handeln | Trust-Level-basiert | ✅ |
| `self_automation.py` | Bei User-Request | Rate-Limited, Whitelist | ✅ |
| `routine_engine.py` | Zeitgesteuert | Eigene HA-Calls | ⚠️ |
| `conditional_commands.py` | Event-getriggert | Eigene Ausfuehrung | ⚠️ |
| `conflict_resolver.py` | Bei konkurrierenden Intents | Nutzt autonomy + ollama | ✅ |
| **Addon: automation_engine.py** | Bei Pattern + Confidence | **Advisory Entity-Check** | 🔴 |
| **Addon: 21 Domain-Module** | Bei state_changed Events | **Advisory Entity-Check** | 🔴 |
| **Addon: circadian.py** | Alle 5 Min | **KEINE Koordination mit light_engine.py** | 🔴 |
| **Addon: cover_control.py** | Bei Sonnenstand/Wetter | **KEINE Koordination mit cover_config.py** | 🔴 |

**🔴 KRITISCH: Addon ↔ Assistant Entity-Kollision — UNVERAENDERT seit DL#2.**
- Advisory Check in `ha_connection.py:70-88`: 2s Timeout, bei Fehler handelt Addon trotzdem
- Aufruf bei `ha_connection.py:183`: Logging bei Skip, aber kein Locking
- Last-Write-Wins bleibt bestehen
- Kein transaktionales Entity-Locking
- Kein Back-Channel Addon → Assistant

### Konflikt C: Wer bestimmt was Jarvis WEISS?

| Modul | Datenquelle | Synchronisiert? | Status |
|---|---|---|---|
| `memory.py` | Redis (Working Memory, 50 Eintraege, 7d TTL) | Ja (Redis) | ✅ |
| `semantic_memory.py` | ChromaDB + Redis (Langzeit-Fakten) | Ja (ChromaDB + Redis-Fallback) | ✅ |
| `conversation_memory.py` | Redis (mha:memory:*) | Ja (Redis) | ✅ |
| `memory_extractor.py` | Ollama LLM → semantic_memory | Async, eventual consistency | ⚠️ |
| `correction_memory.py` | Redis (mha:correction_memory:*) | Ja (Redis, mit Lock) | ✅ |
| `dialogue_state.py` | In-Memory Dict (max 50) | **NEIN — Verlust bei Restart** | 🟠 |
| `learning_observer.py` | Redis (mha:learning:*) | Ja (Redis) | ✅ |
| `learning_transfer.py` | Redis + In-Memory pending (max 50) | Teilweise (pending in-memory) | ⚠️ |
| `knowledge_base.py` | ChromaDB (mha_knowledge_base) | Ja (ChromaDB) | ✅ |
| `context_builder.py` | Aggregiert aus allen obigen + HA | Read-only | ✅ |
| **Addon: pattern_engine.py** | SQLite (state_history) | **KEINE Sync mit Assistant** | 🔴 |
| **Addon: db.py / models.py** | SQLite (68 Tabellen) | **KEINE Sync mit Assistant** | 🔴 |

**Status DL#3: ❌ UNFIXED — 12 isolierte Memory-Systeme, unveraendert seit DL#2.**

### Konflikt D: Wie Jarvis KLINGT

| Modul | Was es steuert | Status |
|---|---|---|
| `personality.py` | Charakter, Sarkasmus (gedeckelt auf 4), Formality | ✅ MCU-Score 8/10 |
| `mood_detector.py` | Ton-Anpassung (mit asyncio.Lock) | ✅ Thread-safe |
| `context_builder.py` | System-Prompt P1-P4 (parallel async) | ✅ |
| `tts_enhancer.py` | TTS Emotion, Pausen, Speed | ✅ |
| `sound_manager.py` | Audio-Wiedergabe, Auto-Volume | ✅ |
| `multi_room_audio.py` | Raum-spezifische Ausgabe | ✅ |

**Status DL#3: ✅ GELOEST — unveraendert seit DL#2.**

### Konflikt E: Timing & Prioritaeten

| Szenario | Was passiert? | Status |
|---|---|---|
| Proaktiv WAEHREND User spricht | `_process_lock` serialisiert (30s Timeout) | ✅ |
| Morgen-Briefing WAEHREND Konversation | `_mb_triggered_today` mit Lock | ✅ |
| Zwei autonome Aktionen gleichzeitig | `_process_lock` serialisiert | ✅ |
| anticipation + function_calling gleichzeitig | Sequenziell in _process_inner() | ✅ |
| **Addon + Assistant gleichzeitig** | **Advisory Check, kein Locking** | 🔴 OFFEN |
| **Addon-Event + Proactive gleichzeitig** | **Keine Koordination** | 🔴 OFFEN |

**Status DL#3: ⚠️ TEILWEISE — unveraendert seit DL#2.**

### Konflikt F: Assistant ↔ Addon Interaktion

| Frage | Antwort | Code-Referenz |
|---|---|---|
| Kommunikation | HTTP REST (Chat-Proxy + Entity-Owner) | `routes/chat.py:159`, `ha_connection.py:70-88` |
| Gleiche Entities? | **JA** — Lichter, Rolllaeden, Klima | `circadian.py` vs `light_engine.py` |
| Addon State-Cache? | Fresh REST calls (nicht gecacht) | `ha_connection.py` |
| Assistant kennt Addon-State? | **NEIN** | — |
| Addon kennt Assistant? | **Minimal** — Advisory GET | `ha_connection.py:70-88, 183` |
| Vorrang? | **Niemand** — Last-Write-Wins | — |
| Addon unterlauft Assistant? | **JA** — jederzeit | `automation_engine.py` |
| Gemeinsames Redis? | **NEIN** — Addon hat kein Redis | — |

**Status DL#3: ⚠️ TEILWEISE — unveraendert seit DL#2.**

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

| Modul | Importiert von | Status | Delta DL#2→3 |
|---|---|---|---|
| `config` | **75 Module** | 🔴 MEGA-GOD-OBJECT | +1 |
| `ha_client` | 21 Module | 🟠 Hoch (HA-API) | 0 |
| `ollama_client` | 12 Module | 🟡 Akzeptabel (LLM-API) | 0 |
| `constants` | 8 Module | ✅ Normal | 0 |
| `function_calling` | 6 Module | ✅ Normal | 0 |
| `websocket` | 5 Module | ✅ Normal | 0 |

### 4.3 Shared-Module-Audit

| Pruefung | Ergebnis |
|----------|----------|
| shared/ Verzeichnis existiert? | **NEIN** — geloescht in DL#1 P6c |
| `from shared` / `import shared` Imports? | **0 Treffer** (Grep-verifiziert) |
| Eigene Request/Response-Klassen im Assistant? | **JA** — `ChatRequest`, `ChatResponse`, `TTSInfo` in main.py:630-655 |
| Eigene Request/Response-Klassen im Addon? | **NEIN** — kein Pydantic, sendet raw JSON |
| Gemeinsame Ports/Konstanten? | **Hardcoded** — Port 8200 in Addon als `ASSISTANT_URL` Env-Var |

### 4.4 Verwaiste Module

| Modul | Status |
|---|---|
| `main.py` | ✅ Entry Point — korrekt nicht importiert |
| `embeddings.py` | ⚠️ Nur via brain.py dynamisch geladen |
| Alle anderen 88 Module | ✅ Mindestens 1 Importeur |

### 4.5 Zirkulaere Abhaengigkeiten

**KEINE GEFUNDEN** — ✅ Sauberer DAG (automatisierte Analyse ueber 90 Module).

### 4.6 Fehlende Verbindungen (Semantische Luecken)

| # | Luecke | Betroffene Module | Impact | Delta DL#2→3 |
|---|--------|-------------------|--------|-------------|
| 1 | **Memory-Silos** | 9 Memory-Module isoliert | Kein kohaerenter Stack | ❌ Unveraendert |
| 2 | **Wahrnehmungs-Isolation** | activity, ambient_audio, threat_assessment, spontaneous_observer | Keine vereinheitlichte Sensor-Interpretation | ❌ Unveraendert |
| 3 | **Zeit-Isolation** | time_awareness, timer_manager, calendar_intelligence, seasonal_insight | Kein geteilter zeitlicher Kontext | ❌ Unveraendert |
| 4 | **Persoenlichkeits-Isolation** | personality, mood_detector, speaker_recognition | Emotion/Stimmung/Erkennung nicht verknuepft | ❌ Unveraendert |
| 5 | **Komfort-Isolation** | climate_model, energy_optimizer, light_engine | Keine koordinierte Optimierung | ❌ Unveraendert |
| 6 | **Proactive ↔ Perception** | proactive ↛ spontaneous_observer/activity | Proaktivitaet nicht umgebungsbewusst | ❌ Unveraendert |

### 4.7 Addon-Architektur

**✅ EXZELLENT — unveraendert seit DL#2**
- 21 Domain-Module erben von `base.py`
- 14 Engines unabhaengig
- 13+ HTTP-Routes sauber getrennt
- Null Cross-Domain-Imports

### 4.8 Modul-Gesamtstatistik

| Service | Module | Zeilen (gesamt) |
|---------|--------|-----------------|
| Assistant | 90 (davon 2 Mixins) | ~81.416 |
| Addon | 48 | ~unbekannt |
| Speech | 2 | ~700 |
| HA-Integration | 3 | ~300 |
| **Gesamt** | **143** | **~82.400+** |

---

## 5. Vorverarbeitung (Schritt 5)

### 5.1 Pre-Classifier (`pre_classifier.py`, 285 Zeilen)

| Profil | Trigger | Deaktivierte Subsysteme |
|--------|---------|------------------------|
| `DEVICE_FAST` | "Licht an", ≤8 Woerter, Verb-Start | Mood, Formality, Irony, RAG, Summary, Activity, Memories |
| `DEVICE_QUERY` | "Wie warm ist es?", ≤10 Woerter | Mood, Formality, Irony, RAG, Summary |
| `KNOWLEDGE` | "Was ist...", ohne Smart-Home-Bezug | House-Status, Activity, Room-Profile |
| `MEMORY` | "Erinnerst du dich..." | House-Status, Activity, Room-Profile |
| `GENERAL` | Alles andere | Nichts deaktiviert |

**Bewertung DL#3:** ✅ Unveraendert, sauber implementiert.

### 5.2 Request Context (`request_context.py`, 102 Zeilen)

- `ContextVar` fuer Request-ID (asyncio-kompatibel) ✅
- X-Request-ID Header-Propagation ✅
- Structured Log-Format ✅

---

## 6. Architektur-Bewertung

### 6.1 Staerken

1. **Null zirkulaere Abhaengigkeiten** — sauberer 5-Schichten-DAG (90 Module verifiziert)
2. **Addon-Architektur vorbildlich** — Plugin-Pattern, Cross-Domain-freie Module
3. **Graceful Degradation** — 37/37 Module in `_safe_init()` (DL#2-Bug behoben!)
4. **Thread-Safety** — `_process_lock` (30s Timeout), `_states_lock`, 12+ Feature-Locks
5. **Security** — PIN-Brute-Force, Error-Detail-Leak-Fixes, Path-Traversal, Entity-ID-Validierung
6. **Pre-Classifier** — Latenz-Optimierung fuer einfache Befehle

### 6.2 Fundamentale Schwaechen

1. **🔴 brain.py God-Object** — 9.906 Zeilen, 81 Imports, 47 Komponenten, 4.700-Zeilen _process_inner()
2. **🔴 main.py God-Object** — 8.278 Zeilen, 273 Endpoints, ~3.113Z Business-Logik extrahierbar
3. **🔴 config.py Mega-Coupling** — 75 Importeure (83% aller Module)
4. **🔴 Addon↔Assistant Koordination fehlt** — Advisory Entity-Check nicht ausreichend
5. **🟠 Memory-Silos** — 12 isolierte Systeme ohne kohaerenten Stack
6. **🟠 6 Semantische Luecken** — Module die zusammenarbeiten sollten, kennen sich nicht

### 6.3 Top-5 Architektur-Aenderungen mit hoechstem Impact

| # | Aenderung | Severity | Impact | Aufwand |
|---|-----------|----------|--------|---------|
| 1 | **main.py aufspalten** (8.278Z → 5+ Module) | 🟠 | Wartbarkeit, Reviews, Tests | 2-3 Tage |
| 2 | **config.py aufspalten** (75 Importeure → Sub-Configs) | 🟠 | Blast-Radius reduzieren | 3-5 Tage |
| 3 | **brain.py _process_inner() dekomponieren** (4.700Z → Phasen) | 🟠 | Testbarkeit, Lesbarkeit | 2-3 Tage |
| 4 | **Addon↔Assistant Shared State** (Redis oder Event-Bus) | 🟡 | Entity-Konflikte eliminieren | 5-7 Tage |
| 5 | **Memory-Coordinator** (Facade ueber 9 Memory-Module) | 🟡 | Kohaerenter Wissensstand | 3-4 Tage |

*Anmerkung: DL#2-Top-1 (ProactiveManager.start() in _safe_init()) wurde BEHOBEN und faellt weg.*

---

## 7. DL#2 → DL#3 Detailvergleich

### Was sich VERBESSERT hat:

| # | Finding | DL#2-Status | DL#3-Status | Beschreibung |
|---|---------|------------|------------|-------------|
| 1 | ProactiveManager.start() | 🔴 NICHT in _safe_init() | ✅ FIXED | brain.py:776 — `_safe_init("Proactive.start", self.proactive.start())` |

### Was sich NICHT verbessert hat:

| # | Finding | DL#2 | DL#3 | Delta |
|---|---------|------|------|-------|
| 2 | brain.py God-Object | 9.800Z | 9.906Z | +106Z ❌ |
| 3 | main.py God-Object | 8.228Z, 270 EP | 8.278Z, 273 EP | +50Z, +3 EP ❌ |
| 4 | config.py Coupling | 74 Importeure | 75 Importeure | +1 ❌ |
| 5 | Addon↔Assistant Sync | Advisory Check | Advisory Check | 0 ❌ |
| 6 | Event-Bus fehlt | Fehlt | Fehlt | 0 ❌ |
| 7 | Memory-Stack | 12 Silos | 12 Silos | 0 ❌ |
| 8 | 6 Semantische Luecken | Offen | Offen | 0 ❌ |

### Risiken aus DL#2 (unveraendert):

| # | Risiko | Status |
|---|--------|--------|
| 9 | Deadlock-Gefahr (12+ Locks) | ⚠️ Weiterhin potentiell |
| 10 | Double-Check-Locking (function_calling.py) | ⚠️ Weiterhin potentiell |
| 11 | Debug-Level Masking (136× logger.debug) | ⚠️ Unveraendert |

---

## KONTEXT AUS PROMPT 1: Architektur-Analyse

### Konflikt-Karte

- **A (Sprache):** ⚠️ Teilweise — personality.py Pipeline funktioniert, CRITICAL-Alerts bewusst hardcoded, routine_engine eigene LLM-Calls
- **B (Aktionen):** 🔴 Offen — Assistant intern serialisiert (_process_lock), Addon↔Assistant Last-Write-Wins, circadian vs light_engine, cover_control vs cover_config
- **C (Wissen):** 🔴 Offen — 12 isolierte Memory-Silos, Addon SQLite ohne Sync, dialogue_state In-Memory
- **D (Klang):** ✅ Geloest — Sarkasmus gedeckelt (4), TTS-Pipeline konsistent
- **E (Timing):** ⚠️ Intern geloest (_process_lock 30s), cross-service offen (kein Event-Bus)
- **F (Addon↔Assistant):** ⚠️ Advisory Check — ha_connection.py:70-88 (2s Timeout, Fallback: Addon handelt trotzdem)

### Service-Interaktion

3 Services + HA-Integration. Kommunikation via HTTP REST (Chat-Proxy + Advisory Entity-Owner-GET). Speech via Redis (Embeddings). Kein gemeinsamer Event-Bus. Addon hat keine Redis-Anbindung. Kein bidirektionaler State-Sync.

### Top-5 Architektur-Probleme

1. 🟠 **main.py God-Object** — 8.278Z, 273 EP, ~3.113Z extrahierbare Business-Logik
2. 🟠 **brain.py God-Object** — 9.906Z, 81 Imports, 4.700Z _process_inner()
3. 🟠 **config.py Mega-Coupling** — 75 Module importieren config (83% aller Module)
4. 🔴 **Addon↔Assistant Entity-Kollision** — Last-Write-Wins, Advisory-only Check
5. 🟠 **12 Memory-Silos** — kein kohaerenter Stack, Addon-Wissen isoliert

### Architektur-Entscheidung

**brain.py → Weiter Mixin-Extraktion (Phase 2 empfohlen):**
- Phase 2: _process_inner() in 10 Phasen-Methoden → RequestContext Dataclass
- Response-Filter (~600Z), Pattern-Detection (~1.200Z) extrahieren
- Kein Event-Bus (zu grosser Umbau), aber Coordinator-Pattern fuer Memory-Facade

**main.py → Aufspaltung (DRINGEND empfohlen, seit DL#2 unveraendert):**
- Workshop-Routes (84 EP, ~1.283Z) → `workshop_routes.py`
- Cover-Management (~900Z) → `cover_manager.py`
- Settings-Reload (~697Z) → `config_manager.py`
- PIN-Auth (~233Z) → `auth_manager.py`

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: ProactiveManager.start() in _safe_init() (brain.py:776)
OFFEN:
- 🔴 Addon↔Assistant Entity-Kollision | ha_connection.py:70-88,183 | GRUND: Last-Write-Wins, Advisory-only
  → ESKALATION: ARCHITEKTUR_NOETIG (Shared Redis oder Event-Bus)
- 🟠 brain.py God-Object | brain.py:9906 Zeilen, 81 Imports | GRUND: Kein weiteres Refactoring seit DL#1
  → ESKALATION: NAECHSTER_PROMPT (P6b Mixin Phase 2)
- 🟠 main.py God-Object | main.py:8278 Zeilen, 273 EP | GRUND: ~3.113Z extrahierbar
  → ESKALATION: NAECHSTER_PROMPT (P6b Aufspaltung)
- 🟠 config.py Mega-Coupling | 75 Importeure | GRUND: Monolithisch
  → ESKALATION: NAECHSTER_PROMPT (P6b Sub-Configs)
- 🟠 12 Memory-Silos | 9 Assistant + 2 Addon + 1 dialogue_state | GRUND: Kein kohaerenter Stack
  → ESKALATION: NAECHSTER_PROMPT (P2 Memory)
- 🟡 6 Semantische Luecken | Module die sich nicht kennen | GRUND: Architektonisch
  → ESKALATION: ARCHITEKTUR_NOETIG
- ⚠️ Deadlock-Risiko | 12+ Locks verschachtelt | GRUND: Keine Lock-Hierarchie definiert
  → ESKALATION: NAECHSTER_PROMPT (P4 Bug-Analyse)
GEAENDERTE DATEIEN: docs/audit-results/RESULT_01_ARCHITEKTUR_DL3.md (NEU)
REGRESSIONEN: Keine neuen (ProactiveManager-Regression aus DL#2 behoben)
NAECHSTER SCHRITT: PROMPT_02_MEMORY.md — Memory-Analyse mit Fokus auf 12 Silos und fehlenden Stack
===================================
```
