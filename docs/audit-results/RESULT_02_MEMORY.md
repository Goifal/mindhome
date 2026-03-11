# Audit-Ergebnis: Prompt 2 — Memory-System End-to-End-Analyse (Durchlauf #2)

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle 12 Memory-Module + Addon-Memory + Datenbank-Schemas
**Durchlauf**: #2 (Verifikation nach P6a–P8 Fixes)
**Vergleichsbasis**: DL#1 (3 kritische Memory-Bugs, 6 offene Probleme, 22 Checks)

---

## DL#1 vs DL#2 Vergleich

### Gesamt-Statistik

```
DL#1: 3 kritische Bugs + 6 offene Probleme
DL#2: 3 FIXED, 0 TEILWEISE, 6 UNFIXED

Veraenderung:
  Vollstaendig behoben:  3 (33%) — alle 3 KRITISCHEN gefixt!
  Unveraendert:          6 (67%) — alle MITTEL/GERING

Check-Tabelle: 14/22 OK (DL#1: 12/22)
Dead Code: 1 reaktiviert (memory.search_memories)
```

### DL#1 → DL#2 Status

| # | Severity | Modul | DL#1-Zeile | DL#2-Zeile | Status | Beschreibung |
|---|----------|-------|-----------|-----------|--------|-------------|
| 1 | KRITISCH | brain.py | 2356+2394 | 2374+2412 | ✅ FIXED | Distinct keys: `conv_memory` + `conv_memory_extended` |
| 2 | KRITISCH | brain.py | 2824+2946 | 2824+2946 | ✅ FIXED | P2 liest `conv_memory`, P3 liest `conv_memory_extended` |
| 3 | HOCH | brain.py/memory.py | 276/— | 5569 | ✅ FIXED | `search_memories(text, limit=3)` in `_get_conversation_memory()` |
| 4 | MITTEL | memory.py | 89 | 89 | ❌ UNFIXED | 7d TTL Working Memory (durch ChromaDB-Fix weniger kritisch) |
| 5 | MITTEL | dialogue_state.py | ganzes Modul | ganzes Modul | ❌ UNFIXED | In-memory only, `deque`-basiert, verloren bei Restart |
| 6 | MITTEL | learning_transfer.py | 27+74 | 27+74 | ❌ UNFIXED | `REDIS_KEY_TRANSFERS` definiert, nie verwendet |
| 7 | MITTEL | conversation_memory.py | ganzes Modul | ganzes Modul | ❌ UNFIXED | Irrefuehrender Name (ist Projekt-Tracker) |
| 8 | MITTEL | Addon pattern_engine.py | ganzes Modul | ganzes Modul | ❌ UNFIXED | 68 SQLite-Tabellen, kein Export an Assistant |
| 9 | MITTEL | brain.py | — | — | ❌ UNFIXED | 12 isolierte Memory-Silos, brain.py einziger Integrationspunkt |

---

## 1. Memory-Abhaengigkeitskarte

| Modul | Zeilen | Importiert von | Wird importiert von | Shared State |
|---|---|---|---|---|
| `memory.py` | 620 | `config`, `semantic_memory`, `embeddings` | `brain.py`, `main.py`, `summarizer.py` | Redis `mha:conversations` + ChromaDB `mha_conversations` |
| `semantic_memory.py` | 437 | `config`, `embeddings` | `memory.py`, `context_builder.py`, `memory_extractor.py`, `brain.py` | ChromaDB `mha_semantic_facts` + Redis Fact-Indexes |
| `conversation_memory.py` | 412 | `config` | `brain.py` | Redis `mha:memory:*` |
| `memory_extractor.py` | 289 | `config`, `ollama_client`, `semantic_memory` | `brain.py` | Schreibt via `semantic_memory` + Redis emotional_memory |
| `correction_memory.py` | 435 | `config` | `brain.py` | Redis `mha:correction_memory:*` |
| `dialogue_state.py` | 410 | `config` | `brain.py` | **Rein in-memory** (deque, max 50, 5min Timeout) |
| `learning_observer.py` | 569 | `config` | `brain.py`, `proactive.py`, `self_report.py`, `function_calling.py` | Redis `mha:learning:*` |
| `learning_transfer.py` | 379 | `config` | `brain.py` | Redis `mha:learning_transfer:*` + **in-memory `_pending_transfers`** |
| `knowledge_base.py` | 427 | `config`, `embeddings` | `brain.py` | ChromaDB `mha_knowledge_base` |
| `embeddings.py` | 82 | `config` | `memory.py`, `semantic_memory.py`, `knowledge_base.py`, `recipe_store.py`, `brain.py` | Singleton `_embedding_fn` |
| `embedding_extractor.py` | 115 | *(keine)* | `speaker_recognition.py` | **Kein Memory-Modul** — ECAPA-TDNN Speaker-Embeddings |
| `context_builder.py` | 973 | `config`, `semantic_memory`, `function_calling`, `ha_client` | `brain.py` | Read-only Aggregator |

**Ergebnis**: Es gibt weiterhin **KEINEN kohaerenten Memory-Stack**. `brain.py` ist der einzige Integrationspunkt. Die 12 Module bilden 6 isolierte Cluster:
1. **Working Memory**: `memory.py` ← `semantic_memory.py` ← `embeddings.py`
2. **Fact Extraction**: `memory_extractor.py` → `semantic_memory.py`
3. **Projekt-Tracking**: `conversation_memory.py` (standalone)
4. **Korrektur-Lernen**: `correction_memory.py` (standalone)
5. **Verhaltens-Lernen**: `learning_observer.py` + `learning_transfer.py` (lose gekoppelt)
6. **RAG Knowledge**: `knowledge_base.py` ← `embeddings.py`

**Keine neuen Memory-Module seit Durchlauf #1 hinzugefuegt.**

---

## 2. Memory-Flow-Diagramm

```
═══════════════════════════════════════════════════════════════
                    WRITE PATH (nach LLM-Response)
═══════════════════════════════════════════════════════════════

User Input + LLM Response
    │
    ├─► _remember_exchange() [brain.py:1020-1030] FIRE-AND-FORGET
    │       └─► memory.add_conversation("user"/"assistant") [memory.py:73]
    │               └─► Redis LPUSH mha:conversations (50 Eintraege, 7d TTL)
    │               └─► Redis RPUSH mha:archive:{date} (30d TTL)
    │
    ├─► memory.store_episode() [brain.py:4278] FIRE-AND-FORGET
    │       └─► ChromaDB mha_conversations (chunked, dedupliziert)
    │           Nur wenn text > 3 Woerter
    │
    ├─► _extract_facts_background() [brain.py:4286→6179] FIRE-AND-FORGET
    │       └─► memory_extractor.extract_and_store()
    │               ├─► Ollama LLM extrahiert Fakten (JSON)
    │               └─► semantic_memory.store_fact()
    │                       ├─► ChromaDB mha_semantic_facts (.add)
    │                       └─► Redis mha:fact:{id}, mha:facts:all/person/category
    │
    ├─► memory_extractor.extract_reaction() [brain.py:4300] FIRE-AND-FORGET
    │       └─► Redis mha:emotional_memory:{action}:{person} (90d TTL)
    │
    ├─► learning_observer.observe() [brain.py:4308] FIRE-AND-FORGET
    │       └─► Redis mha:learning:observations/patterns/insights (30-60d TTL)
    │
    ├─► learning_transfer.observe() [brain.py:4360] FIRE-AND-FORGET
    │       └─► Redis mha:learning_transfer:room_actions (60d)
    │       └─► In-memory _pending_transfers (NICHT persistiert!)
    │
    ├─► conversation_memory.track_project/question() [brain.py:4313-4329] F&F
    │       └─► Redis mha:memory:projects/open_questions (permanent)
    │
    ├─► outcome_tracker.record_exchange() [brain.py:4507] FIRE-AND-FORGET
    │       └─► Redis mha:outcomes:* (90d TTL)
    │
    ├─► response_quality.record_exchange() [brain.py:4507] FIRE-AND-FORGET
    │       └─► Redis mha:response_quality:history (60d TTL)
    │
    ├─► correction_memory.store_correction() [brain.py:9273] AWAITED
    │       └─► Redis mha:correction_memory:entries (180d) + rules (365d)
    │
    └─► dialogue_state.track_turn() [brain.py:4385] SYNCHRON
            └─► In-memory deque (max 50, 5min Timeout, verloren bei Restart)

Total fire-and-forget Tasks pro Request: ~10-12
Total awaited Writes: 1 (correction_memory, nur bei Korrektur)

═══════════════════════════════════════════════════════════════
            READ PATH (vor LLM-Antwort) — GEFIXT IN DL#2
═══════════════════════════════════════════════════════════════

User Input
    │
    ├─► [GATHER] context_builder._get_relevant_memories() [brain.py:2355]
    │       ├─► semantic_memory.search_facts(text, limit=3) → ChromaDB
    │       └─► semantic_memory.get_facts_by_person(person, limit=5) → Redis+ChromaDB
    │       └─► Ergebnis → P1 "WICHTIGE ERINNERUNGEN" (IMMER im Prompt) ✅
    │
    ├─► [GATHER] _get_conversation_memory(text) [brain.py:2374] Key="conv_memory" ✅
    │       ├─► semantic.get_relevant_conversations(text, limit=3) → ChromaDB
    │       └─► memory.search_memories(text, limit=3) → ChromaDB mha_conversations ✅ NEU
    │       └─► Ergebnis → P2 "RELEVANTE VERGANGENE GESPRAECHE" ✅
    │
    ├─► [GATHER] conversation_memory.get_memory_context() [brain.py:2412]
    │       Key="conv_memory_extended" ✅ EIGENER KEY
    │       └─► Redis: Projekte + offene Fragen + Tages-Summary
    │       └─► Ergebnis → P3 "GEDAECHTNIS" ✅
    │
    ├─► [GATHER] correction_memory.get_relevant_corrections() [brain.py:2407]
    │       └─► Redis: relevante Korrekturen
    │       └─► Ergebnis → P2 "GELERNTE KORREKTUREN" ✅
    │
    ├─► [GATHER] correction_memory.get_active_rules() [brain.py:2410]
    │       └─► Redis: aktive Korrektur-Regeln ✅
    │
    ├─► [GATHER] learning_observer.get_learned_patterns() [brain.py:2404]
    │       └─► Redis: erkannte Verhaltensmuster
    │       └─► Ergebnis → P2 Section ✅
    │
    ├─► [GATHER] knowledge_base — via _get_rag_context() [brain.py:2396]
    │       └─► ChromaDB mha_knowledge_base
    │       └─► Ergebnis → P3 (P1 fuer knowledge-Queries) ✅
    │
    ├─► [GATHER] memory_extractor.get_emotional_context() — via gather
    │       └─► Redis: emotionale Reaktionen ✅
    │
    ├─► [GATHER] personality.build_memory_callback_section() [brain.py:2417]
    │       └─► Memory-Callbacks fuer Persoenlichkeit ✅ NEU
    │
    ├─► [GATHER] memory.get_recent_conversations(limit=3) [brain.py:2416]
    │       └─► Redis mha:conversations → Messages fuer Konversationsmodus
    │
    ├─► dialogue_state.get_context_prompt() [brain.py:2890]
    │       └─► In-memory: Dialog-Kontext (Pronomen, Multi-Turn)
    │       └─► Ergebnis → P2 "DIALOG-KONTEXT" ✅
    │
    └─► dialogue_state.resolve_references() [brain.py:1315]
    │       └─► Pronomen-Resolution (in-memory, max 5 Min)
    │
    └─► dialogue_state.check_clarification_answer() [brain.py:1306]
            └─► Klaerungsfragen-Antwort pruefen
```

---

## 3. Check-Tabelle (22 Checks)

| # | Check | DL#1-Status | DL#2-Status | Code-Referenz |
|---|---|---|---|---|
| 1 | Wird `memory.py` **vor** jeder Antwort aufgerufen? | ✅ | ✅ | `context_builder._get_relevant_memories()`, `brain.py:2374` |
| 2 | Wird `memory.py` **nach** jeder Konversation aufgerufen? | ✅ | ✅ | `_remember_exchange()` brain.py:1020, `store_episode()` brain.py:4278 |
| 3 | Werden Erinnerungen in den LLM-Prompt **injiziert**? | ✅ | ✅ | P1 brain.py:2821, P2 brain.py:2824-2833 |
| 4 | Redis TTL: Laufen Erinnerungen stillschweigend ab? | ⚠️ | ⚠️ | Working Memory 7d, Archive 30d, Emotional 90d, Corrections 180d |
| 5 | Async: Werden Memory-Ops korrekt **awaited**? | ✅ | ✅ | Alle Reads im gather sind awaited |
| 6 | Race Condition: Antwort vor Memory-Abfrage? | ✅ | ✅ | Gather laeuft vor LLM-Call, brain.py:2419 |
| 7 | ChromaDB: Richtiges Embedding-Modell? | ✅ | ✅ | `paraphrase-multilingual-MiniLM-L12-v2` ueberall, embeddings.py |
| 8 | ChromaDB: Wird geschrieben? | ✅ | ✅ | `store_episode()` + `store_fact()` |
| 9 | Conversation History als Messages-Array? | ✅ | ✅ | `get_recent_conversations()` → messages |
| 10 | History zwischen Sessions persistiert? | ⚠️ | ✅ BESSER | Redis 7d + **ChromaDB Episoden jetzt gelesen** (brain.py:5569) |
| 11 | `memory_extractor.py`: Wird aufgerufen? | ✅ | ✅ | Fire-and-forget brain.py:4286 |
| 12 | `correction_memory.py`: Wird genutzt? | ✅ | ✅ | Read: brain.py:2407+2410, Write: brain.py:9273 |
| 13 | `dialogue_state.py`: Multi-Turn korrekt? | ⚠️ | ⚠️ | 410Z, deque-basiert, in-memory only, 5min Timeout |
| 14 | `conversation_memory.py`: Kurz+Langzeit? | ❌ | ❌ | Ist Projekt/Fragen-Tracker, KEINE Conv-History |
| 15 | `learning_observer.py`: Muster im Prompt? | ⚠️ | ✅ BESSER | brain.py:2404 `get_learned_patterns()` direkt im Gather |
| 16 | `learning_transfer.py`: Funktioniert? | ⚠️ | ⚠️ | _pending_transfers in-memory only, REDIS_KEY_TRANSFERS unused |
| 17 | `knowledge_base.py`: Im Prompt genutzt? | ✅ | ✅ | Via `_get_rag_context()`, brain.py:2396 |
| 18 | `embeddings.py` vs `embedding_extractor.py`: Redundanz? | ✅ | ✅ | Text-Embeddings vs Audio-Speaker-Embeddings — keine Redundanz |
| 19 | Addon-Daten fuer Assistant zugaenglich? | ❌ | ❌ | Komplett isolierte SQLite, kein API-Endpoint genutzt |
| 20 | Addon-DB: Was gespeichert? | — | 68 Tab. | `LearnedPattern`, `StateHistory`, `Prediction`, `entity_relationships` + 64 weitere |
| 21 | Addon-Pattern-Engine: Muster fuer Assistant? | ❌ | ❌ | PatternDetector laeuft isoliert, ~2.400 Zeilen, kein Export |
| 22 | Addon-Event-Bus: Memory-Events weitergeleitet? | ❌ | ❌ | EventBus rein intern (~180Z), kein Forward an Assistant |

---

## 4. Performance-Check: Memory-Latenz

| # | Check | DL#1-Status | DL#2-Status | Code-Referenz |
|---|---|---|---|---|
| 1 | Memory-Abfragen parallel oder sequentiell? | ✅ | ✅ | Alles im `asyncio.gather()`, brain.py:2419 |
| 2 | Redis-Roundtrips pro Request? | ~8-12 | ~10-15 | Mehr Gather-Tasks (correction_ctx + learned_rules + personality callback) |
| 3 | ChromaDB-Queries pro Request? | 2 | **4** | search_facts + get_facts_by_person + get_relevant_conversations + **search_memories** (NEU) |
| 4 | Embedding-Berechnungen gecacht? | ✅ | ✅ | Singleton in embeddings.py, Modell bleibt geladen |
| 5 | Blockiert Memory-Speicherung den naechsten Request? | ✅ | ✅ | Alle fire-and-forget via TaskRegistry |
| 6 | Memory-Kontext Token-Budget? | ~300-800 | ~400-1200 | P1 memories ~200-500, P2 conv_memory ~100-300, P3 conv_memory_extended ~100-300, P2 corrections ~50-200 |

**Bewertung**: Durch den ChromaDB-Episode-Fix (brain.py:5569) kommen 2 zusaetzliche ChromaDB-Queries hinzu. Bei typischer Latenz von ~50-100ms pro Query und paralleler Ausfuehrung im Gather ist das akzeptabel. Der Token-Verbrauch steigt um ~200-400 Tokens — ebenfalls im Budget.

---

## 5. Root Cause Analyse

### Warum hat Jarvis' Erinnerung nicht funktioniert? (Durchlauf #1 Root Causes)

**Root Cause 1: ✅ GEFIXT — Duplicate Key "conv_memory"**

- DL#1: `brain.py:2356` und `brain.py:2394` verwendeten beide Key `"conv_memory"`.
- DL#2: `brain.py:2374` → `"conv_memory"` (semantische Suche), `brain.py:2412` → `"conv_memory_extended"` (Projekt-Tracker). **Verschiedene Keys, kein Ueberschreiben mehr.**

**Root Cause 2: ✅ GEFIXT — Doppelte Prompt-Insertion**

- DL#1: `conv_memory` wurde als P2 UND P3 eingefuegt.
- DL#2: P2 liest `_safe_get("conv_memory")` (Zeile 2824), P3 liest `_safe_get("conv_memory_extended")` (Zeile 2946). **Korrekt getrennt.**

**Root Cause 3: ✅ GEFIXT — ChromaDB-Episoden nie gelesen**

- DL#1: `search_memories()` nur in `main.py:817` als API-Endpoint.
- DL#2: `brain.py:5569` ruft `self.memory.search_memories(text, limit=3)` in `_get_conversation_memory()` auf. **Episodisches Gedaechtnis jetzt im Read-Path.**

**Root Cause 4: ⚠️ UNVERAENDERT — Faktenextraktion fire-and-forget**

`memory_extractor.extract_and_store()` (brain.py:4286) laeuft als Hintergrund-Task. Bei fehlerhaftem LLM-JSON oder Timeout: keine Fakten gespeichert, kein Retry. **Risiko bleibt, aber Impact ist geringer** da ChromaDB-Episoden jetzt als Fallback dienen.

**Root Cause 5: ⚠️ UNVERAENDERT — conversation_memory.py ist KEIN Konversations-Gedaechtnis**

Name ist weiterhin irrefuehrend. Key jetzt `conv_memory_extended`, aber Modul heisst immer noch `conversation_memory.py`.

**Root Cause 6: ❌ UNVERAENDERT — Addon-Wissen isoliert**

68 SQLite-Tabellen im Addon (LearnedPattern, StateHistory, Prediction, entity_relationships, anomaly_log etc.) — komplett unsichtbar fuer den Assistant. Addon hat REST-Endpoints fuer sein UI-Dashboard (`/api/patterns/`, `/api/predictions/`), aber der Assistant ruft diese **nie** auf.

**Root Cause 7: ⚠️ UNVERAENDERT — dialogue_state rein in-memory**

410 Zeilen, `deque`-basiert. Pronomen-Resolution, Klaerungsfragen, Multi-Turn-Context — alles verloren bei Restart. 5-Minuten Timeout fuer stale Eintraege.

### Verbleibende Root Causes (priorisiert)

| # | Root Cause | Severity | Impact |
|---|---|---|---|
| 1 | Addon-Wissen isoliert (68 Tabellen, kein Export) | 🟡 MITTEL | Jarvis kennt keine Verhaltensmuster, Anomalien, Praesenz-Daten |
| 2 | learning_transfer._pending_transfers in-memory | 🟡 MITTEL | Raum-Transfer-Vorschlaege bei Restart verloren |
| 3 | dialogue_state nicht persistiert | 🟡 MITTEL | Multi-Turn-Kontext bei Restart verloren |
| 4 | Faktenextraktion ohne Retry | 🟡 MITTEL | Manche Fakten werden nie gespeichert |
| 5 | 7d TTL Working Memory | 🟢 GERING | Durch ChromaDB-Fix kompensiert |
| 6 | conversation_memory.py Namensverwirrung | 🟢 GERING | Nur Entwickler-Verwirrung |

---

## 6. Dead-Code-Liste

| Modul / Element | Status | Beweis |
|---|---|---|
| `learning_transfer.REDIS_KEY_TRANSFERS` | Dead constant | Definiert Zeile 27, nie verwendet. `_pending_transfers` nur in-memory (Zeile 74). Grep: 1 Treffer (nur Definition). |
| `conversation_memory._cleanup_old_questions()` | Nur reaktiv | Kein periodischer Schedule, nur bei max_questions Ueberschreitung. |
| `shared/schemas/*` | Dead Code | Von keinem Service importiert (bereits Prompt 1 identifiziert, in DL#1 geloescht). |

### Nicht mehr Dead Code (seit DL#2):

| Element | DL#1 Status | DL#2 Status |
|---|---|---|
| `memory.search_memories()` | ❌ Dead (nur API) | ✅ **AKTIV** — brain.py:5569 |

---

## 7. Bug-Report

### Gefixte Bugs seit Durchlauf #1

#### [✅ GEFIXT] Duplicate Key "conv_memory"
- **Datei**: `brain.py:2374` + `brain.py:2412`
- **Vorher**: Beide Keys waren `"conv_memory"`, zweiter ueberschrieb ersten
- **Jetzt**: `"conv_memory"` (semantisch) + `"conv_memory_extended"` (Projekte)
- **Verifiziert**: Grep zeigt eindeutige Keys, Prompt-Sections korrekt getrennt

#### [✅ GEFIXT] Doppelte Prompt-Insertion
- **Datei**: `brain.py:2824` (P2) + `brain.py:2946` (P3)
- **Vorher**: Beide lasen `_safe_get("conv_memory")` — identischer Content doppelt
- **Jetzt**: P2 liest `"conv_memory"`, P3 liest `"conv_memory_extended"` — verschiedener Content

#### [✅ GEFIXT] ChromaDB-Episoden nie im process()-Flow
- **Datei**: `brain.py:5567-5581`
- **Vorher**: `search_memories()` nur in `main.py:817` als API-Endpoint
- **Jetzt**: In `_get_conversation_memory()` eingebunden mit Dedup-Check (Zeile 5575)

### Verbleibende Bugs

#### [🟡 MITTEL] learning_transfer._pending_transfers in-memory only
- **Datei**: `learning_transfer.py:74`
- **Problem**: `_pending_transfers` ist Python-Liste. `REDIS_KEY_TRANSFERS` (Zeile 27) definiert aber nie verwendet.
- **Auswirkung**: Raum-Transfer-Vorschlaege bei Restart verloren.
- **Fix**: `REDIS_KEY_TRANSFERS` tatsaechlich nutzen — ~15 Zeilen Code.

#### [🟡 MITTEL] dialogue_state nicht persistiert
- **Datei**: `dialogue_state.py` (410 Zeilen)
- **Problem**: Multi-Turn State (Pronomen, Klaerungen) nur in `deque`. Verloren bei Restart.
- **Auswirkung**: Nach Restart weiss Jarvis nicht mehr was "die" oder "dort" referenziert.
- **Fix**: Optional Redis-Backup. 5-Min Timeout macht dies weniger kritisch.

#### [🟡 MITTEL] Addon-Wissen isoliert
- **Datei**: Addon `pattern_engine.py` (~2.400Z), `models.py` (~927Z, 68 Tabellen)
- **Problem**: Addon hat REST-Endpoints (`/api/patterns/`, `/api/predictions/`) fuer sein UI, aber der Assistant ruft diese **nie** auf. Kein Event-Forward ueber EventBus (~180Z, rein intern).
- **Auswirkung**: Assistant kennt keine gelernten Verhaltensmuster, Anomalien, Praesenz-Daten.
- **Fix**: `GET /api/addon/context` Endpoint + Abruf im mega-gather (~50 Zeilen).

#### [🟡 MITTEL] conversation_memory.py Namensverwirrung
- **Datei**: `conversation_memory.py` (412 Zeilen)
- **Problem**: Name suggeriert Konversations-History, ist aber Projekt/Fragen-Tracker.
- **Auswirkung**: Entwickler-Verwirrung. Key jetzt korrekt `conv_memory_extended`.
- **Fix**: Umbenennen zu `project_tracker.py` oder `workspace_memory.py`.

#### [🟢 GERING] Faktenextraktion ohne Retry
- **Datei**: `brain.py:4286` → `memory_extractor.py`
- **Problem**: Fire-and-forget LLM-Call fuer Faktenextraktion. Bei Fehler: still ignoriert.
- **Auswirkung**: Manche Fakten werden nie gespeichert. Durch ChromaDB-Episoden-Fix weniger kritisch.
- **Fix**: Einfacher Retry (1x) oder Erfolgs-Counter.

---

## 8. Dokumentations-Verifikation

| Feature (Docs) | Behauptet | Code-Realitaet DL#2 |
|---|---|---|
| 9 Self-Learning Features | Alle implementiert | ✅ Alle 9 existieren UND sind in brain.py verdrahtet |
| Correction Learning | Implementiert | ✅ Read (`brain.py:2407+2410`) + Write (`brain.py:9273`) |
| Behavioral Patterns | Implementiert | ✅ `learning_observer.observe()` + `get_learned_patterns()` |
| Emotional Memory | Implementiert | ✅ `extract_reaction()` nach Funktions-Ausfuehrung |
| Fact Extraction | Implementiert | ✅ `extract_and_store()` fire-and-forget (kein Retry) |
| Outcome Tracking | Implementiert | ✅ `outcome_tracker.record_exchange()` brain.py:4507 |
| Response Quality | Implementiert | ✅ `response_quality.record_exchange()` |
| Adaptive Thresholds | Implementiert | ✅ Initialisiert in `_safe_init()` brain.py:760 |
| Error Patterns | Implementiert | ✅ Initialisiert in `_safe_init()` brain.py:756 |
| Weekly Learning Report | Implementiert | ✅ `_weekly_learning_report_loop()` als Background-Task |
| Memory insgesamt | "Jarvis merkt sich alles" | ✅ BESSER — semantische Suche + Episoden jetzt korrekt |
| Duplicate Key Bugfix | (Durchlauf #2 Fix) | ✅ **GEFIXT** |

---

## 9. Datenbank-Schemas

### Redis Key-Uebersicht (Memory-relevant)

| Key-Pattern | Modul | Typ | TTL | Zweck |
|---|---|---|---|---|
| `mha:conversations` | memory.py | List | 7d | Working Memory (50 Eintraege) |
| `mha:archive:{date}` | memory.py | List | 30d | Taegliches Archiv |
| `mha:context:{key}` | memory.py | String | 1h | Kurzzeit-Kontext |
| `mha:pending_topics` | memory.py | Hash | 1d | Offene Gespraechsthemen |
| `mha:fact:{id}` | semantic_memory.py | Hash | — | Semantische Fakten (permanent) |
| `mha:facts:all` | semantic_memory.py | Set | — | Alle Fact-IDs |
| `mha:facts:person:{person}` | semantic_memory.py | Set | — | Facts pro Person |
| `mha:facts:category:{cat}` | semantic_memory.py | Set | — | Facts pro Kategorie |
| `mha:memory:projects` | conversation_memory.py | Hash | — | Projekte (permanent) |
| `mha:memory:open_questions` | conversation_memory.py | Hash | — | Offene Fragen (permanent) |
| `mha:memory:summary:{date}` | conversation_memory.py | String | 30d | Tages-Summaries |
| `mha:correction_memory:entries` | correction_memory.py | List | 180d | Korrekturen (max 200) |
| `mha:correction_memory:rules` | correction_memory.py | Hash | 365d | Gelernte Regeln |
| `mha:emotional_memory:{action}:{person}` | memory_extractor.py | List | 90d | Emotionale Reaktionen |
| `mha:learning:observations:{person}` | learning_observer.py | List | 60d | Beobachtungen |
| `mha:learning:patterns:{person}` | learning_observer.py | Hash | 30d | Erkannte Muster |
| `mha:learning:insights:{person}` | learning_observer.py | String | 30d | Formatierte Insights |
| `mha:learning_transfer:preferences` | learning_transfer.py | String (JSON) | 90d | Raum-Praeferenzen |
| `mha:learning_transfer:room_actions:{person}` | learning_transfer.py | List | 60d | Raum-spezifische Aktionen |
| `mha:outcomes:{action_type}` | outcome_tracker.py | List | 90d | Outcome-Records |
| `mha:response_quality:history` | response_quality.py | List | 60d | Qualitaets-Analysen |
| `mha:error_patterns:log` | error_patterns.py | List | 30d | Error-Records |
| `mha:adaptive_thresholds:{type}` | adaptive_thresholds.py | Hash | 90d | Schwellwert-Historie |
| `mha:speaker:{speaker_id}` | speech/handler.py | String | — | Voice-Embeddings (permanent) |

**Total: 24 unique Redis-Key-Patterns**

### ChromaDB Collections

| Collection | Modul | Embedding-Modell | Zweck |
|---|---|---|---|
| `mha_conversations` | memory.py | MiniLM-L12-v2 (384-dim) | Episodisches Gedaechtnis |
| `mha_semantic_facts` | semantic_memory.py | MiniLM-L12-v2 (384-dim) | Semantische Fakten |
| `mha_knowledge_base` | knowledge_base.py | MiniLM-L12-v2 (384-dim) | RAG Knowledge Documents |
| `mha_recipes` | recipe_store.py | MiniLM-L12-v2 (384-dim) | Rezepte |
| `workshop_library` | workshop_library.py | MiniLM-L12-v2 (384-dim) | Workshop-Dokumente |

**Alle 5 Collections nutzen dasselbe Embedding-Modell** — konsistent, kein Model-Mismatch.

### Addon SQLite (isoliert, 68 Tabellen)

| Tabelle | Zweck | Fuer Assistant relevant? |
|---|---|---|
| `state_history` | Rohe HA State-Changes mit Kontext | ✅ Ja — Muster-Erkennung |
| `learned_patterns` | Erkannte Verhaltensmuster | ✅ Ja — Antizipation |
| `predictions` | Vorhergesagte Aktionen | ✅ Ja — Proaktive Hinweise |
| `entity_relationships` | Entity-Korrelationsgraph | ✅ Ja — Smarte Multi-Device-Steuerung |
| `presence_history` | Praesenz-Tracking | ✅ Ja — Kontext-Anreicherung |
| `anomaly_log` | Anomalie-Erkennung | ✅ Ja — Proaktive Warnungen |
| `learned_scenes` | Auto-erkannte Szenen | ✅ Ja — Szenen-Vorschlaege |
| `energy_data` | Energieverbrauch | ✅ Ja — Kosten-bewusste Vorschlaege |
| `automation_rules` | Pattern-Automationen | ⚠️ Teilweise — Konfliktvermeidung |
| + 59 weitere | Diverse Konfiguration/Status | ❌ Nein |

---

## 10. Fix-Empfehlung

### Status der DL#1-Empfehlungen

| Empfehlung | DL#1 | DL#2 |
|---|---|---|
| Fix 1: Duplicate Key umbenennen | ✅ UMGESETZT | `conv_memory_extended` |
| Fix 2: Prompt-Sections trennen | ✅ UMGESETZT | P2 vs P3 korrekt |
| Fix 3: ChromaDB-Episoden im Read-Path | ✅ UMGESETZT | brain.py:5569 |

### Neue Empfehlungen fuer DL#2

| # | Empfehlung | Severity | Aufwand | Impact |
|---|---|---|---|---|
| 1 | `learning_transfer`: `REDIS_KEY_TRANSFERS` nutzen | 🟡 | ~15 Zeilen | Persistente Transfer-Vorschlaege |
| 2 | Addon-Kontext-Endpoint (`GET /api/addon/context`) | 🟡 | ~50 Zeilen | Jarvis kennt Verhaltensmuster |
| 3 | `conversation_memory.py` umbenennen → `project_tracker.py` | 🟢 | Rename | Klarheit |
| 4 | Faktenextraktion: 1x Retry bei Fehler | 🟢 | ~10 Zeilen | Zuverlaessigere Fakten |
| 5 | Langfristig: 12 Module → 4 konsolidieren | 🟡 | 3-5 Tage | Wartbarkeit |

**Gesamtbewertung**: Das Memory-System ist nach den 3 kritischen Fixes **funktional**. Die semantische Konversationssuche, ChromaDB-Episoden und Prompt-Injection funktionieren korrekt. Die verbleibenden Issues sind 🟡 MITTEL oder 🟢 GERING — kein Blocker fuer den normalen Betrieb.

---

## KONTEXT AUS PROMPT 2: Memory-Analyse (Durchlauf #2)

### Memory-Abhaengigkeitskarte
- `brain.py` bleibt einziger Integrationspunkt fuer 12 isolierte Memory-Module (6 Cluster)
- `memory.py` → Redis Working Memory (7d TTL) + ChromaDB Episodes (permanent)
- `semantic_memory.py` → ChromaDB `mha_semantic_facts` + Redis Fact-Indexes (Dual-Storage)
- `context_builder.py` → liest aus `semantic_memory`, formatiert fuer Prompt
- `conversation_memory.py` → NICHT Conv-History, sondern Projekt/Fragen-Tracker (Key jetzt `conv_memory_extended`)
- `embeddings.py` → Singleton `paraphrase-multilingual-MiniLM-L12-v2` (384-dim), von 6 Modulen genutzt
- Addon hat eigene SQLite (68 Tabellen) mit `LearnedPattern`/`StateHistory` — komplett isoliert

### Memory-Flow (Ist-Zustand DL#2 — KORRIGIERT)
- **Write**: brain.py:1020→memory.add_conversation()→Redis 7d; brain.py:4278→store_episode()→ChromaDB; brain.py:4286→extract_and_store()→semantic_memory — alles fire-and-forget (~10-12 Tasks/Request)
- **Read**: context_builder→search_facts()→P1 (immer); brain.py:2374→`conv_memory` (semantisch + **ChromaDB Episoden NEU**)→P2; brain.py:2412→`conv_memory_extended` (Projekte)→P3; brain.py:2407→corrections→P2; brain.py:2404→learned_patterns→P2

### Root Cause Status
- ✅ **GEFIXT**: Duplicate Key "conv_memory" (brain.py:2374 vs 2412 — verschiedene Keys)
- ✅ **GEFIXT**: Doppelte Prompt-Insertion (P2 vs P3 korrekt getrennt)
- ✅ **GEFIXT**: ChromaDB-Episoden im Read-Path (brain.py:5569)
- ⚠️ OFFEN: Addon-Wissen isoliert, dialogue_state in-memory, learning_transfer in-memory

### Empfohlener Fix
Die 3 kritischen Fixes aus DL#1 sind umgesetzt. Verbleibend: (1) learning_transfer REDIS_KEY_TRANSFERS nutzen, (2) Addon-Kontext-Endpoint, (3) conversation_memory.py umbenennen. **Kein Blocker.**

### Memory-Bugs (Durchlauf #2)
| Severity | Modul | Bug | Status |
|---|---|---|---|
| ~~🔴 KRITISCH~~ | ~~brain.py:2374+2412~~ | ~~Duplicate Key "conv_memory"~~ | ✅ GEFIXT |
| ~~🔴 KRITISCH~~ | ~~brain.py:2824+2946~~ | ~~Doppelte Prompt-Insertion~~ | ✅ GEFIXT |
| ~~🟠 HOCH~~ | ~~memory.py:276~~ | ~~ChromaDB-Episoden nie gelesen~~ | ✅ GEFIXT |
| 🟡 MITTEL | learning_transfer.py:27+74 | REDIS_KEY_TRANSFERS unused, _pending in-memory |
| 🟡 MITTEL | dialogue_state.py | Multi-Turn State nicht persistiert (410Z, deque) |
| 🟡 MITTEL | conversation_memory.py | Irrefuehrender Name |
| 🟡 MITTEL | Addon pattern_engine.py | Behavioral patterns isoliert, kein Export |
| 🟢 GERING | memory_extractor.py | Fire-and-forget ohne Retry |

### Dead-Code-Module
- `learning_transfer.REDIS_KEY_TRANSFERS` — definierte Konstante, nie verwendet
- `conversation_memory._cleanup_old_questions()` — nie scheduled, nur reaktiv
- ~~`memory.search_memories()`~~ → ✅ **Nicht mehr Dead Code** (brain.py:5569)

### Memory-Performance
- Redis: ~10-15 Roundtrips/Request (parallel via gather) — akzeptabel
- ChromaDB: **4 Queries** parallel (search_facts + get_facts_by_person + get_relevant_conversations + search_memories) — ~100-300ms total
- Embedding: Singleton gecacht, kein Re-Load
- Token-Budget: P1 ~200-500, P2 conv_memory ~100-300, P3 conv_memory_extended ~100-300 — ~400-1200 total
- Alle Writes fire-and-forget — 0ms Latenz-Impact auf Response
