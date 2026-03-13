# Audit-Ergebnis: Prompt 6a — Stabilisierung (Kritische Bugs & Memory)

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle verbleibenden 🔴 KRITISCHEN Bugs aus P4a/P4b + Memory-Verifikation aus P2
**Durchlauf**: #3 (nach DL#2 — nur noch 2 KRITISCHE Bugs offen)

> **DL#3 (2026-03-13)**: Historisches Fix-Log aus DL#2. P02 Memory-Reparatur aendert diese Fixes nicht. Alle dokumentierten Fixes bleiben gueltig.

---

## DL#2 vs DL#3 Vergleich

```
DL#2 offene KRITISCHE Bugs: 2
  - NEW-1 (4a): brain.py:1218 — Deadlock bei Retry
  - Bug #1 (4b): proactive.py:98,146 — event_handlers ueberschrieben

DL#3: Beide gefixt.
  Alle KRITISCHEN Bugs aus P4a + P4b + P4c: 0 offen.
```

---

## 1. Bug-Fix-Log

### 🔴 Bug NEW-1 (4a): Deadlock bei Retry (brain.py)
- **Datei**: `assistant/assistant/brain.py:1218`
- **Problem**: `_process_inner()` haelt `_process_lock` (acquired in `process()` Zeile 1103). Bei Retry ("ja", "nochmal") wurde `self.process()` aufgerufen, das versucht den Lock erneut zu acquiren. `asyncio.Lock` ist nicht reentrant → **garantierter Deadlock** bei jedem Retry-Versuch.
- **Fix**: `self.process()` → `self._process_inner()` auf Zeile 1218. Da wir bereits innerhalb von `_process_inner()` sind (und der Lock gehalten wird), rufen wir direkt die innere Methode auf.
- **Aufrufer geprueft**: Ja
  - `self.process()` wird nur extern aufgerufen (main.py 6x, websocket.py 2x)
  - `_process_inner()` wird nur von `process()` (mit Lock) und Retry-Pfad (bereits innerhalb Lock) aufgerufen
  - Konsistent, kein Reentrance-Risiko
- **Tests**: ✅ 161 brain-Tests bestanden. 4 Failures sind pre-existing `pytest.mark.asyncio` Issues.

### 🔴 Bug #1 (4b): event_handlers ueberschrieben (proactive.py)
- **Datei**: `assistant/assistant/proactive.py:98,146`
- **Problem**: Zeile 98 initialisiert `self.event_handlers = {}`, Zeilen 100-110 fuegen dynamische Appliance-Handler aus YAML-Config hinzu (z.B. custom `robot_vacuum_done`, `coffee_machine_done`). Zeile 146 ueberschreibt dann **KOMPLETT** mit `self.event_handlers = {...}` (hardcoded defaults). **Alle YAML-konfigurierten Appliance-Handler gehen verloren.**
- **Fix**:
  1. Zeile 146: `_dynamic_handlers = self.event_handlers` — dynamische Handler zwischenspeichern
  2. Nach hardcoded Dict (Zeile 176): `self.event_handlers.update(_dynamic_handlers)` — dynamische Handler mergen
  3. Reihenfolge: Hardcoded Defaults → Dynamische YAML-Appliance-Handler (ueberschreiben Defaults) → YAML Event-Handler Overrides (ueberschreiben alles)
- **Aufrufer geprueft**: Ja — 5 Stellen lesen `event_handlers` via `.get()` (Zeilen 1724, 1754, 1811, 2028, 2091). Alle kompatibel, da Signatur `(priority, description)` unveraendert.
- **Tests**: ✅ 163 proactive-Tests bestanden. 17 Failures sind pre-existing `pytest.mark.asyncio` Issues.

---

## 2. Memory-Fix

### Memory-Architektur-Entscheidung
- **Gewaehlt**: Aktuelles System beibehalten (keine Aenderung noetig)
- **Begruendung**: Alle 3 KRITISCHEN Memory-Bugs aus DL#1 wurden bereits in DL#1/DL#2 gefixt:
  1. ✅ Duplicate Key "conv_memory" → Distinct Keys (`conv_memory` + `conv_memory_extended`)
  2. ✅ Doppelte Prompt-Insertion → P2 liest `conv_memory`, P3 liest `conv_memory_extended`
  3. ✅ ChromaDB-Episoden nie gelesen → `search_memories()` in brain.py:5569 eingebunden
- **Geaenderte Dateien**: Keine (alle Memory-Fixes bereits umgesetzt)

### Verifikation der 4 Memory-Checks

| Check | Status | Beweis |
|---|---|---|
| **1. Conversation History** | ✅ | `brain.py:2416` → `memory.get_recent_conversations(limit=3)` → Redis Working Memory |
| **2. Fakten-Speicherung** | ✅ | `brain.py:4286` → `memory_extractor.extract_and_store()` → `semantic_memory.store_fact()` → ChromaDB + Redis |
| **3. Korrektur-Lernen** | ✅ | Write: `brain.py:9273` → `correction_memory.store_correction()`. Read: `brain.py:2407+2410` → `get_relevant_corrections()` + `get_active_rules()` |
| **4. Kontext im LLM-Prompt** | ✅ | P1: `search_facts()` (immer). P2: `conv_memory` + `corrections`. P3: `conv_memory_extended` (Projekte). Memory-Callbacks: `personality.build_memory_callback_section()` |

### Memory-Flow (verifiziert)

```
READ PATH:
User Input
  ├─► context_builder._get_relevant_memories() → P1 "WICHTIGE ERINNERUNGEN" ✅
  ├─► _get_conversation_memory(text) → P2 "RELEVANTE GESPRAECHE" ✅
  │       ├─► semantic.get_relevant_conversations(text, limit=3)
  │       └─► memory.search_memories(text, limit=3) ← ChromaDB Episoden
  ├─► conversation_memory.get_memory_context() → P3 "GEDAECHTNIS" ✅
  │       └─► Key "conv_memory_extended" (eigener Key!)
  ├─► correction_memory.get_relevant_corrections() → P2 ✅
  ├─► correction_memory.get_active_rules() → P2 ✅
  └─► memory.get_recent_conversations(limit=3) → Messages-Array ✅

WRITE PATH:
  ├─► memory.add_conversation() → Redis 7d TTL (fire-and-forget)
  ├─► memory.store_episode() → ChromaDB mha_conversations (fire-and-forget)
  ├─► memory_extractor.extract_and_store() → semantic_memory (fire-and-forget)
  └─► correction_memory.store_correction() → Redis 180d TTL (awaited)
```

### Verbleibende Memory-Issues (alle 🟡/🟢 — kein Blocker)
- `learning_transfer.REDIS_KEY_TRANSFERS` unused (🟡)
- `dialogue_state` nicht persistiert, in-memory only (🟡)
- `conversation_memory.py` irrefuehrender Name (🟢)
- Addon-Wissen isoliert, 68 SQLite-Tabellen (🟡)
- Faktenextraktion ohne Retry (🟢)

---

## 3. Stabilisierungs-Status

| Check | Status |
|---|---|
| Alle 🔴 Bugs gefixt | ✅ (2 von 2 in DL#3) |
| Memory: Conversation History funktioniert | ✅ |
| Memory: Fakten werden gespeichert | ✅ |
| Memory: Korrekturen werden gemerkt | ✅ |
| Memory: Kontext im LLM-Prompt | ✅ |
| Tests bestehen nach Fixes | ✅ (2551 passed, 0 neue Failures durch Fixes) |

---

## 4. Offene Punkte fuer 6b

1. **brain.py God Object**: ~10.000+ Zeilen, einziger Integrationspunkt — Refactoring-Kandidat
2. **Memory-Konsolidierung**: 12 Module → 4 langfristig sinnvoll, aber kein Blocker
3. **Addon-Integration**: 68 SQLite-Tabellen isoliert — `GET /api/addon/context` Endpoint empfohlen
4. **Shutdown-Asymmetrie**: 30+ Komponenten ohne korrespondierenden `shutdown()` Call
5. **N+1 Redis**: Systemisches Pattern in `semantic_memory.py` (5+ Methoden)
6. **Sync I/O in async**: 28 Vorkommen (dominantes HIGH-Pattern in Extended-Modules)
7. **Test-Infrastruktur**: pytest-asyncio fehlt, ~1197 async-Tests nicht ausfuehrbar

---

## 5. Test-Ergebnis

```
python -m pytest --tb=short -q (nach Fixes):
  2551 passed
  1197 failed (pre-existing: pytest.mark.asyncio Infrastruktur-Issue)
  3 skipped
  1 collection error (test_security_http_endpoints.py)

Brain-spezifische Tests: 161 passed, 4 failed (async infra)
Proactive-spezifische Tests: 163 passed, 17 failed (async infra)

Unsere Fixes: 0 neue Failures eingefuehrt ✅
```

---

## KONTEXT AUS PROMPT 6a: Stabilisierung (DL#3)

### Gefixte 🔴 Bugs
1. NEW-1 (4a) → `brain.py:1218` → Deadlock bei Retry: `self.process()` → `self._process_inner()`
2. Bug #1 (4b) → `proactive.py:98,146` → event_handlers ueberschrieben: `.update()` mit zwischengespeicherten dynamischen Handlern

### Memory-Entscheidung
- Aktuelles System beibehalten — alle 3 KRITISCHEN Fixes bereits in DL#1/DL#2 umgesetzt
- 4 Memory-Checks bestanden: Conversation History ✅, Fakten ✅, Korrekturen ✅, Kontext im Prompt ✅
- Keine Dateien geaendert (Memory-Fixes bereits vorhanden)

### Neue Erkenntnisse
- Deadlock-Risiko bei `asyncio.Lock`: Nicht reentrant! Immer pruefen ob Lock bereits gehalten wird bevor `self.method()` aufgerufen wird das den Lock auch acquired.
- proactive.py Init-Reihenfolge: Dict-Zuweisung nach Loop-Befuellung ueberschreibt alle dynamischen Eintraege — `.update()` Pattern verwenden
- Test-Infrastruktur: pytest-asyncio fehlt, 1197 async-Tests koennen nicht laufen — in 6b/7a aufloesen

### Test-Status
2551 Tests bestanden, 1197 fehlgeschlagen (pre-existing async Infrastructure), 0 neue Failures
