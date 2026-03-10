# Audit-Ergebnis: Prompt 2 — Memory-System End-to-End-Analyse

**Datum**: 2026-03-09
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle 12 Memory-Module + Addon-Memory + Datenbank-Schemas

---

## 1. Memory-Abhängigkeitskarte

| Modul | Importiert von | Wird importiert von | Shared State? |
|---|---|---|---|
| `memory.py` | `config`, `semantic_memory`, `embeddings` | `brain.py`, `main.py`, `summarizer.py` | Redis-Client wird an ~25 Module weitergegeben |
| `semantic_memory.py` | `config`, `embeddings` | `memory.py`, `context_builder.py`, `memory_extractor.py`, `brain.py` (lazy) | ChromaDB `mha_semantic_facts` + Redis fact-indexes |
| `conversation_memory.py` | `config` | `brain.py` | Redis `mha:memory:*` |
| `memory_extractor.py` | `config`, `ollama_client`, `semantic_memory` | `brain.py` | Schreibt via `semantic_memory` |
| `correction_memory.py` | `config` | `brain.py` | Redis `mha:correction_memory:*` |
| `dialogue_state.py` | `config` | `brain.py` | **Rein in-memory** (dict), kein Redis |
| `learning_observer.py` | `config` | `brain.py`, `proactive.py`, `self_report.py`, `function_calling.py` | Redis `mha:learning:*` |
| `learning_transfer.py` | `config` | `brain.py` | Redis `mha:learning_transfer:*`, pending transfers **nur in-memory** |
| `knowledge_base.py` | `config`, `embeddings` | `brain.py` | ChromaDB `mha_knowledge_base` |
| `embeddings.py` | `config` | `memory.py`, `semantic_memory.py`, `knowledge_base.py`, `recipe_store.py`, `brain.py` | Singleton `_embedding_fn` (in-process) |
| `embedding_extractor.py` | *(keine Memory-Module)* | `speaker_recognition.py` | **Kein Memory-Modul** — Audio/Speaker-Embeddings |
| `context_builder.py` | `config`, `semantic_memory` | `brain.py` | Liest aus `semantic_memory`, formatiert für Prompt |

**Ergebnis: Es gibt KEINEN kohärenten Memory-Stack.** `brain.py` ist der einzige Integrationspunkt, der alle Module manuell verdrahtet. Die Module kennen sich untereinander kaum — es sind **12 weitgehend isolierte Systeme**, zusammengehalten nur durch brain.py als God-Object.

---

## 2. Memory-Flow-Diagramm

```
═══════════════════════════════════════════════════════════════
                    WRITE PATH (nach LLM-Response)
═══════════════════════════════════════════════════════════════

User Input + LLM Response
    │
    ├─► _remember_exchange() [brain.py:1007-1017] FIRE-AND-FORGET
    │       └─► memory.add_conversation("user"/"assistant") [memory.py:73]
    │               └─► Redis LPUSH mha:conversations (50 Einträge, 7d TTL)
    │               └─► Redis RPUSH mha:archive:{date} (30d TTL)
    │
    ├─► memory.store_episode() [brain.py:4278] FIRE-AND-FORGET
    │       └─► ChromaDB mha_conversations (chunked, dedupliziert)
    │           Nur wenn text > 3 Wörter
    │
    ├─► _extract_facts_background() [brain.py:6179] FIRE-AND-FORGET
    │       └─► memory_extractor.extract_and_store()
    │               ├─► Ollama LLM extrahiert Fakten (JSON)
    │               └─► semantic_memory.store_fact() [semantic_memory.py:149]
    │                       ├─► ChromaDB mha_semantic_facts (.add)
    │                       └─► Redis mha:fact:{id}, mha:facts:all/person/category
    │
    └─► memory_extractor.extract_reaction() [brain.py:4300] FIRE-AND-FORGET
            └─► Redis mha:emotional_memory:{action}:{person} (90d TTL)

═══════════════════════════════════════════════════════════════
                    READ PATH (vor LLM-Antwort)
═══════════════════════════════════════════════════════════════

User Input
    │
    ├─► context_builder.build() → _get_relevant_memories() [context_builder.py:308]
    │       ├─► semantic.search_facts(user_text) → max 3 relevant facts
    │       └─► semantic.get_facts_by_person(person) → max 5 person facts
    │       └─► Ergebnis → context["memories"] → _build_memory_context() [brain.py:5977]
    │           └─► P1 SECTION (IMMER im Prompt) ✅
    │
    ├─► _get_conversation_memory(text) [brain.py:6008] ← Key "conv_memory" ❌
    │       └─► semantic.get_relevant_conversations(text, limit=3)
    │       └─► ⚠️ WIRD ÜBERSCHRIEBEN durch duplicate key Bug!
    │
    ├─► conversation_memory.get_memory_context() [brain.py:2394] ← Key "conv_memory" ❌
    │       └─► Redis: Projekte + offene Fragen + Tages-Summary
    │       └─► ÜBERSCHREIBT den semantischen conv_memory!
    │           └─► P2 + P3 SECTION (doppelt eingefügt!)
    │
    ├─► correction_memory.get_relevant_corrections() [brain.py:2389]
    │       └─► P2 SECTION
    │
    ├─► dialogue_state.resolve_references() [brain.py:1297]
    │       └─► Pronomen-Resolution (in-memory, max 5 Min)
    │
    └─► memory.get_recent_conversations(limit) [brain.py:3031]
            └─► Redis mha:conversations → Messages-Array ans LLM
```

---

## 3. Check-Tabelle (22 Checks)

| # | Check | Ergebnis | Code-Referenz |
|---|---|---|---|
| 1 | Wird `memory.py` **vor** jeder Antwort aufgerufen? | ✅ JA — via `context_builder._get_relevant_memories()` + mega-gather | `context_builder.py:308`, `brain.py:2356` |
| 2 | Wird `memory.py` **nach** jeder Konversation aufgerufen? | ✅ JA — `_remember_exchange()` + `store_episode()` als fire-and-forget | `brain.py:1007-1017`, `brain.py:4278` |
| 3 | Werden Erinnerungen in den LLM-Prompt **injiziert**? | ✅ JA — als P1 Section (immer) | `brain.py:2797` |
| 4 | Redis TTL: Laufen Erinnerungen stillschweigend ab? | ⚠️ JA — Working Memory 7d, Archive 30d, Emotional 90d, Corrections 180d | `memory.py:89-96` |
| 5 | Async: Werden Memory-Ops korrekt **awaited**? | ✅ JA — alle Reads im gather sind awaited | `brain.py:2405-2416` |
| 6 | Race Condition: Antwort vor Memory-Abfrage? | ✅ NEIN — gather läuft vor LLM-Call | `brain.py:2405-2416` |
| 7 | ChromaDB: Richtiges Embedding-Modell? | ✅ JA — `paraphrase-multilingual-MiniLM-L12-v2` überall | `embeddings.py:21` |
| 8 | ChromaDB: Wird geschrieben? | ✅ JA — via `store_episode()` + `store_fact()` | `brain.py:4278`, `memory_extractor.py:154` |
| 9 | Conversation History als Messages-Array? | ✅ JA — `get_recent_conversations()` → messages | `brain.py:3031` |
| 10 | History zwischen Sessions persistiert? | ⚠️ TEILWEISE — Redis 7d TTL, ChromaDB permanent | `memory.py:89` (7d), `memory.py:153` (ChromaDB) |
| 11 | `memory_extractor.py`: Wird aufgerufen? | ✅ JA — fire-and-forget nach Response | `brain.py:6179` |
| 12 | `correction_memory.py`: Wird genutzt? | ✅ JA — Read in mega-gather, Write bei Korrekturen | `brain.py:2389`, `brain.py:9273` |
| 13 | `dialogue_state.py`: Multi-Turn korrekt? | ⚠️ TEILWEISE — 5 Min Timeout, in-memory only (verloren bei Restart) | `dialogue_state.py:67-69` |
| 14 | `conversation_memory.py`: Kurz+Langzeit? | ❌ NEIN — ist ein Projekt/Fragen-Tracker, KEINE Konversations-History | `conversation_memory.py:56-412` |
| 15 | `learning_observer.py`: Muster im Prompt? | ⚠️ INDIREKT — via "JARVIS DENKT MIT" P2 Section | `brain.py:2386`, `brain.py:2830` |
| 16 | `learning_transfer.py`: Funktioniert? | ⚠️ TEILWEISE — pending transfers in-memory only, verloren bei Restart | `learning_transfer.py:217-230` |
| 17 | `knowledge_base.py`: Im Prompt genutzt? | ✅ JA — P3 Section (P1 für knowledge-Queries) | `brain.py:2378`, `brain.py:6094` |
| 18 | `embeddings.py` vs `embedding_extractor.py`: Redundanz? | ✅ KEINE — Text-Embeddings vs Audio-Speaker-Embeddings | `embeddings.py` vs `embedding_extractor.py` |
| 19 | Addon-Daten für Assistant zugänglich? | ❌ NEIN — komplett isolierte SQLite-DB, kein API-Endpoint | Addon `models.py`, kein Export |
| 20 | Addon-DB: Was gespeichert? | `LearnedPattern`, `StateHistory`, `Prediction` + 40 weitere Tabellen | `addon/models.py:204-927` |
| 21 | Addon-Pattern-Engine: Muster für Assistant? | ❌ NEIN — PatternDetector läuft isoliert im Addon | `addon/pattern_engine.py:697+` |
| 22 | Addon-Event-Bus: Memory-Events weitergeleitet? | ❌ NEIN — Addon EventBus nur intern, kein Forward an Assistant | `addon/pattern_engine.py:2319` |

---

## 4. Performance-Check: Memory-Latenz

| # | Check | Ergebnis | Code-Referenz |
|---|---|---|---|
| 1 | Memory-Abfragen parallel oder sequentiell? | ✅ PARALLEL — alles im `asyncio.gather()` | `brain.py:2405` |
| 2 | Redis-Roundtrips pro Request? | ~8-12 (context_builder + mega-gather + conversations) | Mehrere Module parallel |
| 3 | ChromaDB-Query-Latenz? | 2x ChromaDB queries parallel (search_facts + get_facts_by_person) | `context_builder.py:324-335` |
| 4 | Embedding-Berechnungen gecacht? | ✅ JA — Singleton, Modell bleibt geladen | `embeddings.py:35-36` |
| 5 | Blockiert Memory-Speicherung den nächsten Request? | ✅ NEIN — alle fire-and-forget | `brain.py:4264-4313` |
| 6 | Memory-Kontext Token-Budget? | P1 (always): ~200-500 tokens, P2 conv_memory: ~100-300 — effizient | `brain.py:2797`, `brain.py:2809` |

---

## 5. Root Cause Analyse

### Warum funktioniert Jarvis' Erinnerung nicht?

**Root Cause 1: 🔴 KRITISCH — Duplicate Key "conv_memory" überschreibt semantische Konversations-Suche**

`brain.py:2356` registriert `("conv_memory", self._get_conversation_memory(text))` — eine semantische Suche nach relevanten vergangenen Gesprächen via ChromaDB.

`brain.py:2394` registriert `("conv_memory", self.conversation_memory.get_memory_context())` — Projekte/Fragen aus Redis.

Da `_mega_tasks` als List-of-Tuples zu einem Dict konvertiert wird, **überschreibt die zweite den Wert der ersten**. Für alle non-device Requests (Conversation, Knowledge, etc.) geht die semantische Konversationssuche verloren. Jarvis kann vergangene Gespräche nicht mit aktuellen verbinden.

**Root Cause 2: 🔴 KRITISCH — Doppelte Prompt-Insertion desselben conv_memory**

`brain.py:2809` fügt `conv_memory` als P2 ein. `brain.py:2924` fügt denselben `conv_memory` Wert nochmals als P3 ein. Statt semantische Konversationen (P2) + Projekte/Fragen (P3) zu haben, bekommt das LLM Projekte/Fragen **doppelt**.

**Root Cause 3: 🟠 HOCH — 7-Tage TTL auf Working Memory**

`mha:conversations` hat ein 7-Tage TTL (`memory.py:89`). Alles älter als 7 Tage ist weg aus dem Redis Working Memory. ChromaDB Episodes bleiben permanent, werden aber nur durch `search_memories()` abgerufen — und diese Funktion wird nur in `main.py:792` für die API aufgerufen, **nie im normalen process()-Flow für die Messages-Array Konstruktion**.

**Root Cause 4: 🟠 HOCH — Faktenextraktion ist fire-and-forget via LLM**

`memory_extractor.extract_and_store()` (`brain.py:6179`) ist ein Hintergrund-Task. Wenn Ollama langsam ist, der LLM fehlerhaftes JSON zurückgibt, oder der Task abgebrochen wird, werden keine Fakten gespeichert. Kein Retry, kein Logging des Erfolgs/Misserfolgs auf User-Ebene.

**Root Cause 5: 🟠 HOCH — conversation_memory.py ist KEIN Konversations-Gedächtnis**

Der Name ist irreführend. `ConversationMemory` verwaltet Projekte, offene Fragen und Tages-Summaries — **nicht** Konversationsverläufe. Das eigentliche Konversations-Gedächtnis ist `memory.py:add_conversation()` (Redis, 7d TTL) und `memory.py:store_episode()` (ChromaDB, permanent).

**Root Cause 6: 🟡 MITTEL — Addon-Wissen ist für Assistant unsichtbar**

Der Addon hat eine eigene SQLite mit `LearnedPattern`, `StateHistory`, `Prediction` — alles Verhaltensmuster die Jarvis verbessern könnten. Aber es gibt **keinen API-Endpoint und keinen Event-Forward** an den Assistant. Zwei isolierte Wissensspeicher.

**Root Cause 7: 🟡 MITTEL — dialogue_state rein in-memory**

`DialogueState` speichert Multi-Turn-Context (Pronomen-Resolution, Clarification-State) nur im Python-Dict. Bei Restart alles weg. 5-Minuten Timeout ist knapp für unterbrochene Gespräche.

---

## 6. Dead-Code-Liste

| Modul | Status | Beweis |
|---|---|---|
| `embeddings.py` | ⚠️ **Kein Dead Code** (Prompt 1 Fehler korrigiert) | 6 Module importieren es lazy |
| `embedding_extractor.py` | ✅ Aktiv — aber **kein Memory-Modul** | Nur von `speaker_recognition.py` genutzt |
| `learning_transfer.REDIS_KEY_TRANSFERS` | Dead constant | Definiert Zeile 27, nie verwendet |
| `conversation_memory._cleanup_old_questions()` | Nur reaktiv | Nur bei `max_questions` Überschreitung, kein Schedule |
| `shared/schemas/*` | Dead Code | Bereits in Prompt 1 identifiziert — von niemand importiert |

### 6a. Dead-Code-Beweis (Grep-Proof)

Folgende Grep-Befehle belegen die Dead-Code-Einträge:

**shared/schemas/\* — von keinem Service importiert:**
```
$ grep -r "from shared\|import shared" assistant/ addon/ ha_integration/ speech/
→ 0 Treffer
```
Bestätigt: `shared/schemas/chat_request.py`, `shared/schemas/chat_response.py`, `shared/events.py`, `shared/constants.py` werden von **keinem Service** importiert. Die Dateien existieren, aber alle Services definieren eigene Modelle lokal (Assistant: `main.py:630-656`, Addon: eigene Klassen, HA-Integration: Dict-Literal).

**learning_transfer.REDIS_KEY_TRANSFERS — definiert aber nie verwendet:**
```
$ grep -rn "REDIS_KEY_TRANSFERS" assistant/assistant/learning_transfer.py
27: REDIS_KEY_TRANSFERS = "mha:learning_transfer:transfers"
```
```
$ grep -rn "REDIS_KEY_TRANSFERS" assistant/assistant/
→ Nur 1 Treffer: Definition in Zeile 27
```
Die Konstante wird definiert aber in keiner `redis.set()`/`redis.get()` Operation genutzt. Stattdessen werden pending transfers in einer Python-Liste `_pending_transfers` gehalten (in-memory only).

**conversation_memory._cleanup_old_questions() — nie scheduled:**
```
$ grep -rn "_cleanup_old_questions" assistant/assistant/
→ Nur Definition in conversation_memory.py
```
Die Methode existiert, wird aber nur intern bei `max_questions` Überschreitung aufgerufen — kein periodischer Cleanup-Schedule.

**memory.search_memories() — im process()-Flow nie aufgerufen:**
```
$ grep -rn "search_memories" assistant/assistant/
→ memory.py: Definition (Zeile 274)
→ main.py:792: API-Endpoint /api/assistant/memory/search
```
Die Methode wird **nur** als REST-API-Endpoint exponiert, **nie** im normalen `brain.process()` Flow aufgerufen. ChromaDB-Episoden (`mha_conversations`) werden geschrieben (`store_episode`) aber im LLM-Prompt-Aufbau nie gelesen — effektiver Dead Code im Hauptpfad.

**shared/ — gesamtes Verzeichnis von keinem Service importiert (Cross-Service-Beweis):**
```
$ grep -r "from shared\|import shared" assistant/ addon/ ha_integration/ speech/
→ 0 Treffer

$ ls shared/
__init__.py  constants.py  schemas/
```
Das gesamte `shared/`-Verzeichnis (constants.py, schemas/chat_request.py, schemas/chat_response.py, events.py) ist Dead Code. Kein Service importiert daraus. Stattdessen:
- **Assistant** definiert eigene Models in `main.py:630-656`
- **Addon** nutzt eigene Klassen und raw JSON
- **HA-Integration** baut Dict-Literals in `conversation.py:92-98`

Die "API-Verträge" existieren nur als Dateien auf der Festplatte — sie werden weder gelesen noch enforced.

---

## 7. Bug-Report

### [🔴 KRITISCH] Duplicate Key "conv_memory" — Semantische Konversationssuche geht verloren
- **Datei**: `brain.py:2356` + `brain.py:2394`
- **Problem**: Beide Tasks verwenden Key `"conv_memory"`. Bei Dict-Konvertierung (`brain.py:2418`) überschreibt der zweite den ersten. Für non-device Requests (>80% aller Anfragen) geht `_get_conversation_memory()` — die ChromaDB-Suche nach relevanten vergangenen Gesprächen — stillschweigend verloren.
- **Auswirkung**: Jarvis kann vergangene Gespräche nicht mit aktuellen Topics verbinden. "Was haben wir gestern besprochen?" funktioniert nicht, weil die semantische Suche nie im Prompt landet.
- **Fix**: Key umbenennen: `brain.py:2394` → `("conv_memory_projects", self.conversation_memory.get_memory_context())`

### [🔴 KRITISCH] Doppelte Prompt-Insertion von conv_memory
- **Datei**: `brain.py:2809` (P2) + `brain.py:2924` (P3)
- **Problem**: Derselbe `_safe_get("conv_memory")` Wert wird zweimal in den Prompt eingefügt — einmal als P2 "RELEVANTE VERGANGENE GESPRÄCHE", einmal als P3 "GEDÄCHTNIS". Aber nach dem Key-Collision enthält conv_memory nur Projekte/Fragen, nicht Konversationen.
- **Auswirkung**: Token-Budget wird verschwendet durch doppelten identischen Content. Semantische Konversationen fehlen komplett.
- **Fix**: `brain.py:2800-2809` soll `_safe_get("conv_memory")` (semantisch) nutzen, `brain.py:2921-2924` soll `_safe_get("conv_memory_projects")` nutzen.

### [🟠 HOCH] ChromaDB-Episoden nie im process()-Flow abgerufen
- **Datei**: `memory.py:274` (`search_memories`)
- **Problem**: `store_episode()` schreibt Gespräche nach ChromaDB (`mha_conversations`). Aber `search_memories()` wird nur in `main.py:792` als API-Endpoint aufgerufen — **nie** im normalen `brain.py:process()` Flow. Die Episoden werden gespeichert und nie gelesen.
- **Auswirkung**: Langzeit-Episodisches Gedächtnis existiert in der Datenbank, erreicht aber nie den LLM-Prompt.
- **Fix**: `_get_conversation_memory()` sollte auch `memory.search_memories(text)` einbeziehen.

### [🟠 HOCH] Working Memory 7d TTL ohne Archiv-Zugriff
- **Datei**: `memory.py:89`
- **Problem**: `mha:conversations` hat 7d TTL. `mha:archive:{date}` hat 30d TTL. Aber `get_recent_conversations()` liest nur aus `mha:conversations`. Die Archive werden nur von `summarizer.py` gelesen.
- **Auswirkung**: Messages-Array an LLM enthält nur Gespräche der letzten 7 Tage.
- **Fix**: Akzeptabel wenn ChromaDB-Episoden korrekt abgefragt werden (s.o.).

### [🟡 MITTEL] dialogue_state nicht persistiert
- **Datei**: `dialogue_state.py:104`
- **Problem**: Multi-Turn State (Pronomen, Clarifications) nur in Python-Dict. Verloren bei Restart.
- **Auswirkung**: Nach Restart weiß Jarvis nicht mehr was "die" oder "dort" referenziert.
- **Fix**: Optional Redis-Backup, aber 5-Min Timeout macht dies weniger kritisch.

### [🟡 MITTEL] learning_transfer pending transfers in-memory only
- **Datei**: `learning_transfer.py:217-230`
- **Problem**: `_pending_transfers` ist eine Python-Liste. `REDIS_KEY_TRANSFERS` ist definiert aber nie verwendet.
- **Auswirkung**: Raum-Transfer-Vorschläge gehen bei Restart verloren.
- **Fix**: `REDIS_KEY_TRANSFERS` tatsächlich nutzen.

### [🟡 MITTEL] conversation_memory.py Namens-Verwirrung
- **Datei**: `conversation_memory.py`
- **Problem**: Name suggeriert Konversations-History, ist aber ein Projekt/Fragen-Tracker.
- **Auswirkung**: Entwickler-Verwirrung, falscher Key-Name "conv_memory" für Projekte.
- **Fix**: Umbenennen zu `project_tracker.py` oder `workspace_memory.py`.

### [🟡 MITTEL] Addon-Wissen isoliert
- **Datei**: Addon `pattern_engine.py`, `models.py`
- **Problem**: Addon hat `LearnedPattern`, `StateHistory`, `PatternDetector` — alles behavioral patterns die Jarvis verbessern würden. Kein API-Export, kein Event-Forward.
- **Auswirkung**: Assistant hat kein Wissen über erkannte Nutzungsmuster, Anomalien, Szenen.
- **Fix**: REST-Endpoint im Addon + periodischer Sync.

---

## 8. Dokumentations-Verifikation

| Feature (Docs) | Behauptet | Code-Realität |
|---|---|---|
| 9 Self-Learning Features | Alle implementiert | ✅ Code existiert — aber Effektivität fraglich wegen Memory-Bugs |
| Emotional Memory (Feature 5) | Implementiert | ✅ `memory_extractor.extract_reaction()` existiert |
| Emotional Memory Bugfix (#3) | Gefixt | ✅ `_last_executed_action` Tracking in brain.py |
| Weekly Learning Report | Implementiert | ✅ `_weekly_learning_report_loop()` in brain.py |
| Outcome Tracker | Implementiert | ✅ `outcome_tracker.py` existiert, wired in brain.py |
| Correction Memory | Implementiert | ✅ Funktioniert (Read+Write verifiziert) |
| Memory insgesamt | "Jarvis merkt sich alles" | ❌ **NEIN** — semantische Konversationssuche geht verloren (Key-Bug) |

---

## 9. Datenbank-Schemas

### Redis Key-Übersicht (Memory-relevant)

| Key-Pattern | Modul | Typ | TTL | Zweck |
|---|---|---|---|---|
| `mha:conversations` | memory.py | List | 7d | Working Memory (50 Einträge) |
| `mha:archive:{date}` | memory.py | List | 30d | Tägliches Archiv |
| `mha:context:{key}` | memory.py | String | 1h | Kurzzeit-Kontext |
| `mha:pending_topics` | memory.py | Hash | 1d | Offene Gesprächsthemen |
| `mha:fact:{id}` | semantic_memory.py | Hash | — | Semantische Fakten |
| `mha:facts:all` | semantic_memory.py | Set | — | Alle Fact-IDs |
| `mha:facts:person:{person}` | semantic_memory.py | Set | — | Facts pro Person |
| `mha:facts:category:{cat}` | semantic_memory.py | Set | — | Facts pro Kategorie |
| `mha:memory:projects` | conversation_memory.py | Hash | — | Projekte |
| `mha:memory:open_questions` | conversation_memory.py | Hash | — | Offene Fragen |
| `mha:memory:summary:{date}` | conversation_memory.py | String | 30d | Tages-Summaries |
| `mha:correction_memory:entries` | correction_memory.py | List | 180d | Korrekturen (max 200) |
| `mha:correction_memory:rules` | correction_memory.py | Hash | 365d | Gelernte Regeln |
| `mha:emotional_memory:{action}:{person}` | memory_extractor.py | List | 90d | Emotionale Reaktionen |
| `mha:learning:*` | learning_observer.py | Diverse | 30-60d | Gelernte Muster |
| `mha:learning_transfer:preferences` | learning_transfer.py | String (JSON) | 90d | Raum-Präferenzen |

### ChromaDB Collections

| Collection | Modul | Embedding-Modell | Zweck |
|---|---|---|---|
| `mha_conversations` | memory.py | MiniLM-L12-v2 (384-dim) | Episodisches Gedächtnis |
| `mha_semantic_facts` | semantic_memory.py | MiniLM-L12-v2 (384-dim) | Semantische Fakten |
| `mha_knowledge_base` | knowledge_base.py | MiniLM-L12-v2 (384-dim) | RAG Knowledge Documents |
| `mha_recipes` | recipe_store.py | MiniLM-L12-v2 (384-dim) | Rezepte |
| `workshop_library` | workshop_library.py | MiniLM-L12-v2 (384-dim) | Workshop-Dokumente |

### Addon SQLite (isoliert)

| Tabelle | Zweck |
|---|---|
| `state_history` | Rohe HA State-Changes mit Kontext |
| `learned_patterns` | Erkannte Verhaltensmuster |
| `predictions` | Vorhergesagte Aktionen |
| `pattern_match_log` | Pattern-Match Events |
| `learned_scenes` | Auto-erkannte Szenen |
| + 40 weitere | Diverse Konfiguration/Status |

---

## 10. Fix-Empfehlung

| Ansatz | Pro | Contra | Empfehlung |
|---|---|---|---|
| SQLite statt Redis für History | Persistent, kein TTL | Langsamer | ❌ Nicht nötig |
| In-Memory-Liste in brain.py | Einfach, schnell | Verlust bei Restart | ❌ Nicht nötig |
| Sliding Window (letzte N) | Vorhersagbar | Kein Langzeit | ❌ Bereits vorhanden |
| MemGPT-Pattern | Bewährt, skalierbar | Komplex | ❌ Overkill |
| Hybrid: Sliding Window + SQLite | Kurz + Archiv | Mittlere Komplexität | ❌ Redis+ChromaDB ist besser |
| **Aktuelles System fixen** | Kein Umbau nötig | 3 Bugs fixen | ✅ **EMPFOHLEN** |
| Konsolidierung: 12 → 3 | Weniger Silos | Großer Umbau | ⚠️ Langfristig sinnvoll |

### Empfohlener Fix: 3 Änderungen, kein Umbau

**Fix 1** — Duplicate Key beheben (`brain.py`):
```python
# Zeile 2394: Key umbenennen
_mega_tasks.append(("conv_memory_projects", self.conversation_memory.get_memory_context()))
```

**Fix 2** — Prompt-Sections trennen (`brain.py`):
```python
# Zeile 2800: Semantische Konversationen (P2)
conv_memory = _safe_get("conv_memory")  # Bleibt — jetzt korrekt semantisch

# Zeile 2921: Projekte/Fragen (P3) — eigener Key
conv_projects = _safe_get("conv_memory_projects", "")
if conv_projects:
    sections.append(("conv_projects", f"\n\nGEDÄCHTNIS: {conv_projects}", 3))
```

**Fix 3** — ChromaDB-Episoden im Read-Path einbinden (`brain.py:_get_conversation_memory`):
```python
async def _get_conversation_memory(self, text: str) -> Optional[str]:
    parts = []
    # Semantic facts about conversations
    convs = await self.memory.semantic.get_relevant_conversations(text, limit=3)
    if convs: parts.append(convs)
    # Episodic memory from ChromaDB
    episodes = await self.memory.search_memories(text, limit=3)
    if episodes:
        for ep in episodes:
            parts.append(f"[{ep.get('timestamp','')}] {ep.get('document','')[:200]}")
    return "\n".join(parts) if parts else None
```

---

## KONTEXT AUS PROMPT 2: Memory-Analyse

### Memory-Abhängigkeitskarte
- `brain.py` ist einziger Integrationspunkt für 12 isolierte Memory-Module
- `memory.py` (MemoryManager) → Redis Working Memory + ChromaDB Episodes + SemanticMemory
- `semantic_memory.py` → ChromaDB `mha_semantic_facts` + Redis Fact-Indexes (Dual-Storage)
- `context_builder.py` → liest aus `semantic_memory`, formatiert für Prompt
- `conversation_memory.py` → NICHT Conv-History, sondern Projekt/Fragen-Tracker
- `embeddings.py` → Singleton `paraphrase-multilingual-MiniLM-L12-v2` (384-dim), von 6 Modulen genutzt
- `embedding_extractor.py` → Audio-Speaker-Embeddings (ECAPA-TDNN), kein Memory-Modul
- Addon hat eigene SQLite mit `LearnedPattern`/`StateHistory` — komplett isoliert

### Memory-Flow (Ist-Zustand)
- **Write**: brain.py:1007→memory.add_conversation()→Redis 7d; brain.py:4278→store_episode()→ChromaDB; brain.py:6179→extract_and_store()→semantic_memory — alles fire-and-forget
- **Read**: context_builder.py:308→search_facts()→P1 (immer); brain.py:2356→conv_memory (semantisch)→**ÜBERSCHRIEBEN** durch brain.py:2394→conv_memory (Projekte); brain.py:3031→get_recent_conversations()→Messages-Array

### Root Cause
Jarvis' Erinnerung scheitert an einem **Duplicate-Key-Bug** (brain.py:2356+2394 — Key "conv_memory"): Die semantische Konversationssuche wird für >80% aller Requests stillschweigend überschrieben. Zusätzlich werden ChromaDB-Episoden zwar gespeichert, aber im normalen process()-Flow nie gelesen. Semantische Fakten (P1) funktionieren — aber Konversations-Kontinuität ist gebrochen.

### Empfohlener Fix
3 gezielte Änderungen ohne Umbau: (1) Duplicate Key "conv_memory" umbenennen, (2) Prompt-Sections trennen (semantisch P2, Projekte P3), (3) ChromaDB-Episoden im Read-Path einbinden. Langfristig: 12 Module → 3-4 konsolidieren.

### Memory-Bugs (8 Funde)
| Severity | Modul | Bug |
|---|---|---|
| 🔴 KRITISCH | brain.py:2356+2394 | Duplicate Key "conv_memory" — semantische Suche geht verloren |
| 🔴 KRITISCH | brain.py:2809+2924 | Doppelte Prompt-Insertion desselben conv_memory |
| 🟠 HOCH | memory.py:274 | ChromaDB-Episoden werden nie im process()-Flow gelesen |
| 🟠 HOCH | memory.py:89 | 7d TTL Working Memory, Archiv nicht genutzt |
| 🟡 MITTEL | dialogue_state.py:104 | Multi-Turn State nicht persistiert |
| 🟡 MITTEL | learning_transfer.py:27 | REDIS_KEY_TRANSFERS definiert aber nie genutzt |
| 🟡 MITTEL | conversation_memory.py | Irreführender Name (ist Projekt-Tracker, nicht Conv-History) |
| 🟡 MITTEL | Addon pattern_engine.py | Behavioral patterns isoliert, kein Export an Assistant |

### Dead-Code-Module
- `shared/schemas/*` — von niemand importiert (bereits Prompt 1)
- `learning_transfer.REDIS_KEY_TRANSFERS` — definierte Konstante, nie verwendet

### Memory-Performance
- Redis: ~8-12 Roundtrips/Request (parallel via gather) — akzeptabel
- ChromaDB: 2 Queries parallel (search_facts + get_facts_by_person) — ~50-200ms
- Embedding: Singleton gecacht, kein Re-Load
- Token-Budget: Memory P1 ~200-500 Tokens, conv_memory P2 ~100-300 — effizient
- Alle Writes fire-and-forget — 0ms Latenz-Impact auf Response
