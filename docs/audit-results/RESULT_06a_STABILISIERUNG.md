# Audit-Ergebnis: Prompt 6a — Stabilisierung (Kritische Bugs & Memory)

**Durchlauf**: #3 (DL#3)
**Datum**: 2026-03-13
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Alle KRITISCHEN Bugs aus P04a/b/c fixen + Memory-System verifizieren

---

## Bug-Zuordnung P04 → P06

### KRITISCHE Bugs — Zuordnung

| Bug-# | Quelle | Beschreibung | Datei:Zeile | Zugeordnet an | Status |
|---|---|---|---|---|---|
| DL3-ME1 | P04a | Prompt-Injection in Memory-Extraktion (Gaslighting) | memory_extractor.py:87 | **P06a** | ✅ GEFIXT |
| DL3-AI1 | P04a | Task-Ergebnis-Zuordnung falsch (asyncio.wait) | action_planner.py:342 | **P06a** | ✅ FALSE POSITIVE (bereits DL#2 gefixt) |
| DL3-AI2 | P04a | Rhetorische Fragen blockieren Device-Commands | pre_classifier.py:166 | **P06a** | ✅ GEFIXT |
| DL3-AI3 | P04a | Fragewort-Prefix zu aggressiv | pre_classifier.py:233 | **P06a** | ✅ GEFIXT (zusammen mit AI2) |
| #20/DL3-ME2 | P04a | store_fact() True bei totalem Backend-Ausfall | semantic_memory.py:175 | **P06a** | ✅ GEFIXT |
| DL3-H01 | P04b | mindhome_put() ohne Auth-Header | ha_client.py:373 | **P06a** | ✅ GEFIXT |
| DL3-H02 | P04b | mindhome_delete() ohne Auth-Header | ha_client.py:404 | **P06a** | ✅ GEFIXT |
| DL3-D01/M01 | P04b | OCR _validate_image_path() blockiert Uploads | ocr.py:57 | **P06a** | ✅ GEFIXT |
| N9 | P04c | pattern_engine.py datetime TypeError | pattern_engine.py:1073 | **P06a** | ✅ GEFIXT |
| N21 | P04c | Hot-Update Endpoint XSS | routes/system.py:912 | **P06d** | ⏳ Offen |
| P1 | P04c | 50+ sync Komponenten in __init__ | brain.py:204 | **P06b** | ⏳ Offen |
| #68 | P04c | CORS Wildcard Default | app.py:58 | **P06d** | ⏳ Offen |
| #69 | P04c | Localhost-Bypass Auth | app.py:508 | **P06d** | ⏳ Offen |

### HOHE Bugs (P06a-Scope, Memory-relevant) — zusaetzlich gefixt

| Bug-# | Beschreibung | Datei:Zeile | Status |
|---|---|---|---|
| DL3-B1 | Security-Confirmation Bypass bei leerem Person | brain.py:6270 | ✅ GEFIXT |
| DL3-B2 | Leere Args bei ungueltigem LLM-JSON | brain.py:3472 | ✅ GEFIXT |
| DL3-B3 | Redis None-Guard fehlt in experiential memory | brain.py:8404 | ✅ GEFIXT |

### HOHE/MITTLERE Bugs — Zuordnung an nachfolgende Prompts

| Kategorie | Anzahl | Zugeordnet an |
|---|---|---|
| Security (Prompt-Injection, kwargs-Injection, Auth) | ~15 | **P06d** |
| Architektur/Flow/Performance (Race Conditions, Sequential Redis) | ~25 | **P06b** |
| Tool-Calling (Validator mutiert Args, declarative_tools Race) | ~5 | **P06e** |
| Fire-and-forget ohne Error-Callback (TTS, media_stop) | ~8 | **P06f** |
| Persoenlichkeit/Config/Dead Code | ~40 | **P06c** |

---

## 1. Bug-Fix-Log

### 🔴 Bug #1: DL3-ME1 — Prompt-Injection in Memory-Extraktion
- **Datei**: assistant/assistant/memory_extractor.py:258
- **Problem**: User-Text wurde via `EXTRACTION_PROMPT.replace("{conversation}", conversation)` direkt in den LLM-Prompt eingefuegt. Manipulierter Text konnte beliebige "Fakten" ins Semantic Memory einschleusen (Gaslighting-Vektor).
- **Fix**: Neue `_sanitize_for_extraction()` Methode mit `_INJECTION_PATTERN` (gleiches Pattern wie correction_memory.py). Alle Inputs (user_text, assistant_response, person, room, time) werden sanitisiert.
- **Aufrufer geprueft**: 1 Stelle (brain.py:5794), kompatibel
- **Tests**: ✅ 67 bestanden, 0 fehlgeschlagen
→ Commit: 713933d

### 🔴 Bug #2: DL3-AI1 — Task-Ergebnis-Zuordnung (asyncio.wait)
- **Datei**: assistant/assistant/action_planner.py:342
- **Problem**: War als KRITISCH gemeldet, aber Code iteriert korrekt ueber `tasks` (originale Liste), nicht ueber `done` Set. Index-Zuordnung zu `valid_steps[idx]` stimmt.
- **Status**: ✅ FALSE POSITIVE — bereits in DL#2 korrekt gefixt (Bug #54)

### 🔴 Bug #3+4: DL3-AI2/AI3 — pre_classifier Frage-Erkennung
- **Datei**: assistant/assistant/pre_classifier.py:233
- **Problem**: `?` am Satzende allein markierte Text als Frage → Befehle wie "Mach Licht an?" wurden faelschlicherweise blockiert. Fragewort-Prefixe wie "ist" matchten zu aggressiv ("Ist mir egal, mach Licht an").
- **Fix**: Neue Logik: `_is_question = _question_starts and (_has_question_mark or word_count <= 6)`. Fragewort UND Fragezeichen (oder kurzer Satz mit Fragewort) = echte Frage. Befehl mit `?` am Ende = weiterhin Device-Command.
- **Aufrufer geprueft**: 1 Stelle (brain.py:2301), kompatibel
- **Tests**: ✅ 103 bestanden (1 Test-Assertion korrigiert: alte Assertion prueft das buggy Verhalten)
→ Commit: d94a0e0

### 🔴 Bug #5: #20/DL3-ME2 — store_fact() bei Backend-Ausfall
- **Datei**: assistant/assistant/semantic_memory.py:193
- **Problem**: Wenn BEIDE Backends (ChromaDB + Redis) nicht verfuegbar waren, gab `store_fact()` `True` zurueck — Fakt "gespeichert" aber nirgends geschrieben.
- **Fix**: Early-Return `False` wenn `not self.chroma_collection and not self.redis`.
- **Aufrufer geprueft**: 4 Stellen, alle pruefen return-Wert
- **Tests**: ✅ 51 bestanden
→ Commit: f3cec69

### 🔴 Bug #6+7: DL3-H01/H02 — ha_client PUT/DELETE ohne Auth
- **Datei**: assistant/assistant/ha_client.py:376, 408
- **Problem**: `mindhome_put()` und `mindhome_delete()` fehlten `headers=self._mindhome_headers`. Alle Schreib-Operationen an die Addon-API waren unautorisiert.
- **Fix**: `headers=self._mindhome_headers` bei beiden Methoden ergaenzt.
- **Aufrufer geprueft**: 8+ Stellen (cover_settings, learn_pattern, etc.), alle kompatibel
- **Tests**: ✅ Compile OK
→ Commit: e322749

### 🔴 Bug #8: DL3-D01/M01 — OCR blockiert Uploads
- **Datei**: assistant/assistant/ocr.py:59
- **Problem**: `_validate_image_path()` erlaubte nur `/tmp` als Basis-Pfad. Hochgeladene Bilder in `/app/data/uploads` wurden als Pfadtraversal abgelehnt → OCR funktionierte nie fuer Uploads.
- **Fix**: `allowed_bases = [Path("/tmp"), Path("/app/data/uploads")]`
- **Aufrufer geprueft**: 1 Stelle (extract_text_from_image), kompatibel
- **Tests**: ✅ 1 bestanden
→ Commit: 686653f

### 🔴 Bug #9: N9 — pattern_engine datetime TypeError
- **Datei**: addon/rootfs/opt/mindhome/pattern_engine.py:1073
- **Problem**: `datetime.now(timezone.utc) - p.last_matched_at` warf TypeError wenn `last_matched_at` ein naiver datetime war (aus alten DB-Eintraegen).
- **Fix**: `if lma.tzinfo is None: lma = lma.replace(tzinfo=timezone.utc)` vor dem Vergleich.
- **Aufrufer geprueft**: Konsistent mit Line 994-995 (gleiche Behandlung)
- **Tests**: ✅ Compile OK
→ Commit: a0ccfd1

### 🟠 Bug #10: DL3-B1 — Security-Confirmation Bypass
- **Datei**: assistant/assistant/brain.py:6270
- **Problem**: Leerer `pending["person"]` String umging Person-Check → JEDER konnte Sicherheitsaktion bestaetigen.
- **Fix**: Explizite Ablehnung wenn `pending_person` leer + Redis-Key loeschen.

### 🟠 Bug #11: DL3-B2 — Leere Args bei ungueltigem JSON
- **Datei**: assistant/assistant/brain.py:3472
- **Problem**: `func_args = {}` bei JSON-Parse-Error → Funktion mit leeren Args ausgefuehrt.
- **Fix**: `continue` statt `func_args = {}` — Tool-Call wird uebersprungen.

### 🟠 Bug #12: DL3-B3 — Redis None-Guard
- **Datei**: assistant/assistant/brain.py:8405
- **Problem**: `_log_experiential_memory()` griff auf `self.memory.redis.lpush()` zu ohne None-Check.
- **Fix**: `if not self.memory.redis: return` am Anfang.

→ Commit (B1+B2+B3): 3bd66e1

---

## 2. Memory-Fix

### Memory-Architektur-Entscheidung
- **Gewaehlt**: Aktuelles System fixen (kein Umbau noetig)
- **Begruendung**: Alle Root Causes aus P02 sind bereits in DL#2 + DL#3 gefixt. Die 12 Module funktionieren korrekt. Verbleibende Issues (N+1 Redis, dialogue_state in-memory) sind Performance-/Resilience-Themen fuer P06b.
- **Geaenderte Dateien**: memory_extractor.py (Injection-Schutz), semantic_memory.py (Backend-Check)
- **Verifikation**:
  1. ✅ Conversation History: brain.py:2317,2442 → `get_recent_conversations(limit=10)`
  2. ✅ Fakten-Speicherung: brain.py:5794 → `extract_and_store()` → `store_fact()`
  3. ✅ Korrektur-Lernen: brain.py:8922 → `store_correction()`, brain.py:2433 → `get_relevant_corrections()`
  4. ✅ Kontext im LLM-Prompt: context_builder.py:326-337 → `search_facts()` + `get_facts_by_person()`

---

## 3. Stabilisierungs-Status

| Check | Status |
|---|---|
| Alle 🔴 Bugs gefixt (P06a-Scope) | ✅ 9/10 gefixt (1 False Positive) |
| 🔴 Bugs fuer andere Prompts | ⏳ 3 offen (N21→P06d, P1→P06b, #68/#69→P06d) |
| Memory: Conversation History funktioniert | ✅ |
| Memory: Fakten werden gespeichert | ✅ |
| Memory: Korrekturen werden gemerkt | ✅ |
| Memory: Kontext im LLM-Prompt | ✅ |
| Tests bestehen nach Fixes | ✅ 5103 bestanden (81 pre-existing failures in security HTTP tests) |
| `python -m py_compile brain.py` | ✅ |
| `python -m py_compile memory.py` | ✅ |
| `python -m py_compile personality.py` | ✅ |
| `except.*pass` in brain.py | ✅ 0 |
| `_safe_init` in brain.py | ✅ Vorhanden |

---

## 4. Offene Punkte fuer P06b

1. **P1 (KRITISCH)**: 50+ sync Komponenten in `brain.__init__` → Startup 30-60s+. Async Init-Pattern noetig.
2. **Race Conditions**: `_current_mood`/`_current_formality` in personality.py (#36/#37), `analyze_voice_metadata()` in mood_detector.py (#39)
3. **N+1 Redis**: Systemisches Pattern in semantic_memory.py (5+ Methoden). Redis-Pipeline Migration.
4. **Shutdown**: 30+ Komponenten ohne `.stop()` (#4)
5. **Fire-and-forget**: 8+ `asyncio.ensure_future()` ohne Error-Callback in main.py

---

## KONTEXT AUS PROMPT 6a: Stabilisierung

### Gefixte 🔴 Bugs
- DL3-ME1 → memory_extractor.py → Prompt-Injection-Schutz via _sanitize_for_extraction()
- DL3-AI2/AI3 → pre_classifier.py → Frage-Erkennung: Fragewort+? statt ? allein
- #20/DL3-ME2 → semantic_memory.py → Early-Return False bei totalem Backend-Ausfall
- DL3-H01/H02 → ha_client.py → Auth-Header fuer PUT/DELETE ergaenzt
- DL3-D01/M01 → ocr.py → Upload-Pfad erlaubt (/tmp + /app/data/uploads)
- N9 → pattern_engine.py → Naive datetime → UTC vor Vergleich

### Gefixte 🟠 Bugs
- DL3-B1 → brain.py → Security-Confirmation: Leerer Person = Ablehnung
- DL3-B2 → brain.py → JSON-Parse-Error: Skip statt leere Args
- DL3-B3 → brain.py → Redis None-Guard in _log_experiential_memory

### Memory-Entscheidung
- Aktuelles System beibehalten (alle P02 Root Causes gefixt)
- 4/4 Memory-Checks bestanden

### Neue Erkenntnisse
- DL3-AI1 war False Positive (bereits DL#2 gefixt)
- pre_classifier Test prueft altes buggy Verhalten — Test korrigiert
- 81 pre-existing Test-Failures in test_security_http_endpoints.py (brauchen Running Server)

### Test-Status
- 5103 Tests bestanden, 81 fehlgeschlagen (pre-existing), 17 uebersprungen, 18 Errors (pre-existing)
- Alle Tests in geaenderten Modulen: 205 bestanden, 0 fehlgeschlagen

### Bug-Zuordnungstabelle fuer P06b-P06f
| Prompt | Scope | Beispiel-Bugs |
|---|---|---|
| P06b | Architektur/Performance/Race | P1, #36/#37, #4, N+1 Redis, Shutdown |
| P06c | Persoenlichkeit/Config/Dead Code | #47, #48, NEW-D, DL3-CP11 |
| P06d | Security/Haertung | N21, #68, #69, DL3-M1/M2, DL3-M9 |
| P06e | Geraetesteuerung/Tool-Calling | DL3-AI5, DL3-AI6, DL3-AI7 |
| P06f | TTS/Response | DL3-M3/M4/M5, DL3-AI4 |

---

=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: DL3-ME1 (memory_extractor.py:258), DL3-AI2/AI3 (pre_classifier.py:233), #20/DL3-ME2 (semantic_memory.py:193), DL3-H01 (ha_client.py:376), DL3-H02 (ha_client.py:408), DL3-D01/M01 (ocr.py:59), N9 (pattern_engine.py:1073), DL3-B1 (brain.py:6270), DL3-B2 (brain.py:3472), DL3-B3 (brain.py:8405)
OFFEN:
- 🔴 N21 KRITISCH Hot-Update XSS | routes/system.py:912 | GRUND: Security → ESKALATION: P06d
- 🔴 P1 KRITISCH 50+ sync Init | brain.py:204 | GRUND: Architektur → ESKALATION: P06b
- 🔴 #68 KRITISCH CORS Wildcard | app.py:58 | GRUND: Security → ESKALATION: P06d
- 🔴 #69 KRITISCH Localhost-Bypass | app.py:508 | GRUND: Security → ESKALATION: P06d
- 🟠 #36/#37 HOCH personality Race | personality.py:2243,2299 | GRUND: Architektur → P06b
- 🟠 #4 HOCH Shutdown 30+ Komp | brain.py:9773 | GRUND: Architektur → P06b
- 🟠 DL3-AI5 HOCH Validator mutiert | function_validator.py:135 | GRUND: Tool-Calling → P06e
- 🟠 DL3-AI6 HOCH YAML Race | declarative_tools.py:91 | GRUND: Tool-Calling → P06e
- [+55 HOHE, 160 MITTEL, 71 NIEDRIG verteilt auf P06b-P06f]
GEAENDERTE DATEIEN: assistant/assistant/memory_extractor.py, assistant/assistant/pre_classifier.py, assistant/tests/test_pre_classifier.py, assistant/assistant/semantic_memory.py, assistant/assistant/ha_client.py, assistant/assistant/ocr.py, addon/rootfs/opt/mindhome/pattern_engine.py, assistant/assistant/brain.py
REGRESSIONEN: Keine — alle 205 Tests in geaenderten Modulen bestanden
NAECHSTER SCHRITT: P06b (Architektur) — Race Conditions, Performance, Shutdown, N+1 Redis
===================================
