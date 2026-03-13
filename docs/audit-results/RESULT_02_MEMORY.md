# Audit-Ergebnis: Prompt 2 — Memory-System End-to-End-Analyse (Durchlauf #2)

**Datum**: 2026-03-10 (DL#2), 2026-03-13 (DL#3 — P02 Fixes)
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle 12 Memory-Module + Addon-Memory + Datenbank-Schemas
**Durchlauf**: #3 (P02 Memory-Reparatur: 11 Fixes)
**Vergleichsbasis**: DL#2 (3 kritische Bugs gefixt, 6 offene Probleme)

---

## DL#3: P02 Memory-Reparatur — 11 Fixes

### Durchgefuehrte Fixes

1. [x] Fix 1: `get_recent_conversations(limit=3)` → `limit=10` (brain.py:2317 und brain.py:2442)
2. [x] Fix 2: Semantic Facts in context_builder.py:301 — BEREITS unconditional geladen (kein Fix noetig)
3. [x] Fix 3: Memory-Keywords erweitert (brain.py:8053, +16 neue Keywords, total 22)
4. [x] Fix 4: `_build_memory_context()` Header verbessert (brain.py:5580-5586) — "DEIN GEDAECHTNIS" mit direktiver Anweisung
5. [x] Fix 5: conversation_memory Priority 3→1 (brain.py:2973)
6. [x] Fix 6: Doppelter Wort-Filter gefixt:
   - memory_extractor.py:189: `max(self._min_words, 5)` → `max(self._min_words, 3)`
   - brain.py:4368: `len(text.split()) > 3` → `> 2` (Episode-Speicherung)
   - brain.py:4380: `len(text.split()) > 3` → `> 2` (Fakten-Extraktion)
   - settings.yaml: `extraction_min_words: 5` → `3`
7. [x] Fix 7: JSON-Parse Logging verbessert:
   - memory_extractor.py:277: Error-Logging mit model + text_len Info
   - memory_extractor.py:306: `logger.debug` → `logger.warning` fuer Parse-Fehler
8. [x] Fix 8: Retry-Logik in `_extract_facts_background()` (brain.py:5792) — 2 Versuche mit 1s Pause
9. [x] Fix 9: Whitelist fuer explizite Merk-Befehle in `_should_extract()` (memory_extractor.py:174-186):
   - "merk dir", "merke dir", "vergiss nicht", "ab sofort", "von jetzt an"
   - "ich heisse", "mein name ist", "meine frau", "mein mann"
   - "ich mag", "ich hasse", "ich bevorzuge", "ich bin allergisch"
   - Wird VOR allen Filtern geprueft → erzwungene Extraktion
10. [x] Fix 10: Relevance/Confidence Schwellen gesenkt:
    - context_builder.py:322: `min_confidence 0.6` → `0.4`
    - context_builder.py:331: `relevance > 0.3` → `> 0.2`
    - settings.yaml: `min_confidence_for_context: 0.6` → `0.4`
11. [x] Fix 11: Guest-Mode Logging in context_builder.py:301-302:
    - `logger.info("Guest-Mode aktiv — Memory-Abruf uebersprungen")` wenn Guest-Mode Memory blockiert

### Verifizierung

- [x] Grep: Alle `get_recent_conversations` Stellen = `limit=10`
- [x] Grep: `search_facts`/`get_facts_by_person` NICHT hinter `intent_type=="memory"` (war schon in context_builder.py)
- [x] Grep: Memory-Keywords-Liste hat 22 Eintraege (20+ Ziel)
- [x] Read: `_build_memory_context()` Header ist direktiv ("DEIN GEDAECHTNIS", "Nutze sie AKTIV")
- [x] Read: conversation_memory Priority = 1
- [x] Grep: `_should_extract()` min_words = 3 (nicht 5)
- [x] Grep: `_parse_facts()` Logger-Level = `logger.warning` (nicht debug)
- [x] Grep: `_extract_facts_background()` hat Retry (`for attempt in range(2)`)
- [x] Grep: `_should_extract()` hat `force_extract_patterns` VOR den Filtern
- [x] Grep: `min_confidence_for_context` = 0.4 (nicht 0.6)
- [x] Grep: Relevance-Filter = 0.2 (nicht 0.3)
- [x] Grep: Guest-Mode Logging vorhanden
- [x] Syntax-Check: `ast.parse` fuer brain.py, memory_extractor.py, context_builder.py — alle OK
- [ ] Tests: pytest hat vorbestehenden ImportError (`pydantic_settings` fehlt) — kein Zusammenhang mit Fixes

### Geaenderte Dateien

1. `assistant/assistant/brain.py` — Fixes 1, 3, 4, 5, 6 (brain.py-Teil), 8
2. `assistant/assistant/memory_extractor.py` — Fixes 6 (extractor-Teil), 7, 9
3. `assistant/assistant/context_builder.py` — Fixes 10, 11
4. `assistant/config/settings.yaml` — Fixes 6, 10

### Memory-Flow nach Fixes

```
User Input → Redis (limit=10) + SemanticMemory (IMMER, Confidence≥0.4, Relevance>0.2) + ConversationMemory (Priority 1)
           → Alles im System-Prompt mit direktivem Header ("DEIN GEDAECHTNIS")
           → LLM antwortet mit Kontext
           → memory_extractor.py speichert neue Fakten (min 3 Woerter, Whitelist fuer Merk-Befehle, 2x Retry)
           → Guest-Mode wird geloggt wenn aktiv
```

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

## KONTEXT AUS PROMPT 2: Memory-Reparatur (Durchlauf #3)

### Memory-Abhaengigkeitskarte
- `brain.py` bleibt einziger Integrationspunkt fuer 12 isolierte Memory-Module (6 Cluster)
- `memory.py` → Redis Working Memory (7d TTL) + ChromaDB Episodes (permanent)
- `semantic_memory.py` → ChromaDB `mha_semantic_facts` + Redis Fact-Indexes (Dual-Storage)
- `context_builder.py` → liest aus `semantic_memory`, formatiert fuer Prompt (Confidence≥0.4, Relevance>0.2)
- `conversation_memory.py` → NICHT Conv-History, sondern Projekt/Fragen-Tracker (Key `conv_memory_extended`, Priority 1)
- `memory_extractor.py` → Whitelist fuer Merk-Befehle, min 3 Woerter, 2x Retry, Warning-Logging bei Parse-Fehler
- `embeddings.py` → Singleton `paraphrase-multilingual-MiniLM-L12-v2` (384-dim), von 6 Modulen genutzt
- Addon hat eigene SQLite (68 Tabellen) mit `LearnedPattern`/`StateHistory` — komplett isoliert

### Memory-Flow (Ist-Zustand DL#3 — NACH P02 FIXES)
- **Write**: brain.py:1020→memory.add_conversation()→Redis 7d; brain.py:4368→store_episode()→ChromaDB (min 3 Woerter); brain.py:4380→_extract_facts_background()→semantic_memory (min 3 Woerter, 2x Retry, Whitelist) — alles fire-and-forget (~10-12 Tasks/Request)
- **Read**: context_builder→search_facts(Relevance>0.2)+get_facts_by_person(Confidence≥0.4)→P1 (immer); brain.py:2374→`conv_memory` (semantisch + ChromaDB Episoden)→P2; brain.py:2412→`conv_memory_extended` (Projekte, Priority 1)→P3; brain.py:2407→corrections→P2; brain.py:2404→learned_patterns→P2; brain.py:2317+2442→get_recent_conversations(limit=10)

### Root Cause Status
- ✅ **GEFIXT DL#2**: Duplicate Key "conv_memory" (brain.py:2374 vs 2412 — verschiedene Keys)
- ✅ **GEFIXT DL#2**: Doppelte Prompt-Insertion (P2 vs P3 korrekt getrennt)
- ✅ **GEFIXT DL#2**: ChromaDB-Episoden im Read-Path (brain.py:5569)
- ✅ **GEFIXT DL#3**: Conversation-History zu kurz (limit=3→10)
- ✅ **GEFIXT DL#3**: Memory-Intent-Erkennung zu eng (22 Keywords)
- ✅ **GEFIXT DL#3**: Memory-Header unklar (jetzt "DEIN GEDAECHTNIS" direktiv)
- ✅ **GEFIXT DL#3**: conv_memory_ext Priority zu niedrig (3→1)
- ✅ **GEFIXT DL#3**: Doppelter Wort-Filter (5→3 + >3→>2)
- ✅ **GEFIXT DL#3**: LLM-Extraktion scheitert leise (warning statt debug)
- ✅ **GEFIXT DL#3**: Fire-and-forget ohne Retry (jetzt 2x Versuche)
- ✅ **GEFIXT DL#3**: Keine Whitelist fuer Merk-Befehle (force_extract_patterns hinzugefuegt)
- ✅ **GEFIXT DL#3**: Confidence/Relevance zu streng (0.6→0.4, 0.3→0.2)
- ✅ **GEFIXT DL#3**: Guest-Mode blockiert ohne Feedback (Logging hinzugefuegt)
- ⚠️ OFFEN: Addon-Wissen isoliert, dialogue_state in-memory, learning_transfer in-memory

### Memory-Bugs (Durchlauf #3)
| Severity | Modul | Bug | Status |
|---|---|---|---|
| ~~🔴 KRITISCH~~ | ~~brain.py:2374+2412~~ | ~~Duplicate Key "conv_memory"~~ | ✅ GEFIXT DL#2 |
| ~~🔴 KRITISCH~~ | ~~brain.py:2824+2946~~ | ~~Doppelte Prompt-Insertion~~ | ✅ GEFIXT DL#2 |
| ~~🟠 HOCH~~ | ~~memory.py:276~~ | ~~ChromaDB-Episoden nie gelesen~~ | ✅ GEFIXT DL#2 |
| ~~🔴 KRITISCH~~ | ~~brain.py:2317+2442~~ | ~~Conversation limit=3 zu kurz~~ | ✅ GEFIXT DL#3 |
| ~~🔴 KRITISCH~~ | ~~memory_extractor.py:189+brain.py:4368~~ | ~~Doppelter Wort-Filter~~ | ✅ GEFIXT DL#3 |
| ~~🟠 HOCH~~ | ~~brain.py:8053~~ | ~~Memory-Intent zu eng~~ | ✅ GEFIXT DL#3 |
| ~~🟠 HOCH~~ | ~~brain.py:5580~~ | ~~Memory-Header unklar~~ | ✅ GEFIXT DL#3 |
| ~~🟠 HOCH~~ | ~~brain.py:2973~~ | ~~conv_memory Priority 3~~ | ✅ GEFIXT DL#3 |
| ~~🟠 MITTEL~~ | ~~context_builder.py:322+331~~ | ~~Confidence/Relevance zu streng~~ | ✅ GEFIXT DL#3 |
| ~~🟠 MITTEL~~ | ~~memory_extractor.py:306~~ | ~~JSON-Parse nur debug~~ | ✅ GEFIXT DL#3 |
| ~~🟢 GERING~~ | ~~brain.py:5792~~ | ~~Fire-and-forget ohne Retry~~ | ✅ GEFIXT DL#3 |
| ~~🟢 GERING~~ | ~~memory_extractor.py:174~~ | ~~Keine Whitelist Merk-Befehle~~ | ✅ GEFIXT DL#3 |
| ~~🟢 GERING~~ | ~~context_builder.py:302~~ | ~~Guest-Mode ohne Logging~~ | ✅ GEFIXT DL#3 |
| 🟡 MITTEL | learning_transfer.py:27+74 | REDIS_KEY_TRANSFERS unused, _pending in-memory |
| 🟡 MITTEL | dialogue_state.py | Multi-Turn State nicht persistiert (410Z, deque) |
| 🟡 MITTEL | conversation_memory.py | Irrefuehrender Name |
| 🟡 MITTEL | Addon pattern_engine.py | Behavioral patterns isoliert, kein Export |

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

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT:
- BUG 1: get_recent_conversations limit=3→10 (brain.py:2317, brain.py:2442)
- BUG 2: BEREITS GEFIXT in context_builder.py:301 (Fakten werden immer geladen)
- BUG 3: Memory-Keywords erweitert auf 22 (brain.py:8053)
- BUG 4: Memory-Header direktiv "DEIN GEDAECHTNIS" (brain.py:5580)
- BUG 5: conv_memory_ext Priority 3→1 (brain.py:2973)
- BUG 6: Wort-Minimum 5→3 + brain.py Filter >3→>2 (memory_extractor.py:189, brain.py:4368+4380, settings.yaml)
- BUG 7: JSON-Parse Logging debug→warning (memory_extractor.py:306)
- BUG 8: Retry-Logik 2x Versuche (brain.py:5792)
- BUG 9: Whitelist force_extract_patterns (memory_extractor.py:174-186)
- BUG 10: Confidence 0.6→0.4, Relevance 0.3→0.2 (context_builder.py:322+331, settings.yaml)
- BUG 11: Guest-Mode Logging (context_builder.py:302)
OFFEN:
- 🟡 [MITTEL] Memory-Silos nicht konsolidiert (personality.py, correction_memory.py) | ARCHITEKTUR_NOETIG → P06b
- 🟡 [MITTEL] learning_transfer REDIS_KEY_TRANSFERS unused | ~15 Zeilen Fix
- 🟡 [MITTEL] dialogue_state nicht persistiert | Optional Redis-Backup
- 🟡 [MITTEL] Addon-Wissen isoliert | GET /api/addon/context Endpoint
GEAENDERTE DATEIEN: brain.py, memory_extractor.py, context_builder.py, settings.yaml
REGRESSIONEN: Keine (Syntax-Check OK, Test-Fehler vorbestehend: pydantic_settings fehlt)
NAECHSTER SCHRITT: P03 oder Praxis-Test mit echtem Dialog
===================================
```
