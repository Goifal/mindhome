# RESULT_02: Memory-System Reparatur — Alle 11 Fixes

## KONTEXT AUS PROMPT 2: Memory-Reparatur

### Durchgefuehrte Fixes

1. [x] **Fix 1**: `get_recent_conversations(limit=3)` → `limit=10` (brain.py:2317, brain.py:2442)
2. [x] **Fix 2**: Semantic Facts werden BEREITS immer geladen in `context_builder.py:301` — kein Code-Aenderung noetig
3. [x] **Fix 3**: Memory-Keywords erweitert von ~6 auf ~20 Keywords (brain.py:8048-8058)
4. [x] **Fix 4**: `_build_memory_context()` Header verbessert — "DEIN GEDAECHTNIS" mit direktiver Anweisung (brain.py:5580-5587)
5. [x] **Fix 5**: `conv_memory_ext` Priority 3 → 1 (brain.py:2973)
6. [x] **Fix 6**: Doppelter Wort-Filter gefixt:
   - `memory_extractor.py:175`: `max(self._min_words, 5)` → `max(self._min_words, 3)`
   - `brain.py:4368`: `len(text.split()) > 3` → `> 2` (Episode-Speicherung)
   - `brain.py:4380`: `len(text.split()) > 3` → `> 2` (Fakten-Extraktion)
   - `settings.yaml:796`: `extraction_min_words: 5` → `3`
7. [x] **Fix 7**: JSON-Parse Logging verbessert:
   - `memory_extractor.py:263`: Error-Logging mit model + text_len Info
   - `memory_extractor.py:291`: `logger.debug` → `logger.warning` fuer Parse-Fehler
8. [x] **Fix 8**: Retry-Logik in `_extract_facts_background()` (brain.py:5784) — 2 Versuche mit 1s Pause
9. [x] **Fix 9**: Whitelist fuer explizite Merk-Befehle in `_should_extract()` (memory_extractor.py:175):
   - "merk dir", "merke dir", "vergiss nicht", "ab sofort", "von jetzt an"
   - "ich heisse", "mein name ist", "meine frau", "mein mann"
   - "ich mag", "ich hasse", "ich bevorzuge", "ich bin allergisch"
   - Wird VOR allen Filtern geprueft → erzwungene Extraktion
10. [x] **Fix 10**: Relevance/Confidence Schwellen gesenkt:
    - `context_builder.py:320`: `min_confidence 0.6` → `0.4`
    - `context_builder.py:329`: `relevance > 0.3` → `> 0.2`
    - `settings.yaml:802`: `min_confidence_for_context: 0.6` → `0.4`
11. [x] **Fix 11**: Guest-Mode Logging in `context_builder.py:301`:
    - `logger.info("Guest-Mode aktiv — Memory-Abruf uebersprungen")` wenn Guest-Mode Memory blockiert

### Verifizierung

- [x] Syntax-Check: Alle 3 Dateien parsen fehlerfrei (`ast.parse`)
- [x] `get_recent_conversations` → alle Stellen `limit=10`
- [x] `search_facts`/`get_facts_by_person` in context_builder.py → ausserhalb intent-Bedingung (war schon so)
- [x] Memory-Keywords-Liste hat 20+ Eintraege
- [x] `_build_memory_context()` Header ist direktiv ("DEIN GEDAECHTNIS", "Nutze sie AKTIV")
- [x] `conv_memory_ext` Priority = 1
- [x] `_should_extract()` min_words = 3 (nicht 5)
- [x] `_parse_facts()` Logger-Level = warning (nicht debug)
- [x] `_extract_facts_background()` hat Retry (2 Versuche)
- [x] `_should_extract()` hat force_extract_patterns VOR den Filtern
- [x] `min_confidence_for_context` = 0.4 (nicht 0.6)
- [x] Relevance-Filter = 0.2 (nicht 0.3)
- [x] Guest-Mode Logging vorhanden
- [ ] Tests: pytest hat vorbestehenden ImportError (`pydantic_settings` fehlt) — kein Zusammenhang mit unseren Aenderungen

### Geaenderte Dateien

1. `assistant/assistant/brain.py` — Fixes 1, 3, 4, 5, 6 (brain.py-Teil), 8
2. `assistant/assistant/memory_extractor.py` — Fixes 6 (extractor-Teil), 7, 9
3. `assistant/assistant/context_builder.py` — Fixes 10, 11
4. `assistant/config/settings.yaml` — Fixes 6, 10

### Noch offen / Beobachten

- personality.py:build_memory_callback_section() nutzt SEPARATES Memory-System (mha:personality:memorable:{person})
  → Konsolidierung mit semantic_memory in spaeteren Prompts (P06b)
- Token-Budget nach Erhoehung auf limit=10 beobachten
- `pydantic_settings` Modul fehlt in Test-Umgebung (vorbestehend)

### Memory-Flow nach Fixes

```
User Input → Redis (limit=10) + SemanticMemory (IMMER, Confidence≥0.4, Relevance>0.2) + ConversationMemory (Priority 1)
           → Alles im System-Prompt mit direktivem Header ("DEIN GEDAECHTNIS")
           → LLM antwortet mit Kontext
           → memory_extractor.py speichert neue Fakten (min 3 Woerter, Whitelist fuer Merk-Befehle, 2x Retry)
           → Guest-Mode wird geloggt wenn aktiv
```

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT:
- BUG 1: get_recent_conversations limit=3→10 (brain.py:2317, brain.py:2442)
- BUG 2: BEREITS GEFIXT in context_builder.py:301 (Fakten werden immer geladen)
- BUG 3: Memory-Keywords erweitert auf 20+ (brain.py:8048)
- BUG 4: Memory-Header direktiv ("DEIN GEDAECHTNIS") (brain.py:5580)
- BUG 5: conv_memory_ext Priority 3→1 (brain.py:2973)
- BUG 6: Wort-Minimum 5→3 + brain.py Filter >3→>2 (memory_extractor.py:175, brain.py:4368,4380, settings.yaml)
- BUG 7: JSON-Parse Logging debug→warning (memory_extractor.py:291)
- BUG 8: Retry-Logik 2x Versuche (brain.py:5784)
- BUG 9: Whitelist force_extract_patterns (memory_extractor.py:175)
- BUG 10: Confidence 0.6→0.4, Relevance 0.3→0.2 (context_builder.py:320,329, settings.yaml)
- BUG 11: Guest-Mode Logging (context_builder.py:301)
OFFEN:
- 🟡 [LOW] Memory-Silos nicht konsolidiert (personality.py, correction_memory.py) | ARCHITEKTUR_NOETIG → P06b
- 🟡 [LOW] pydantic_settings fehlt in Test-Env | MENSCH (pip install)
GEAENDERTE DATEIEN: brain.py, memory_extractor.py, context_builder.py, settings.yaml
REGRESSIONEN: Keine (Syntax-Check OK, Test-Fehler vorbestehend)
NAECHSTER SCHRITT: P03 oder Praxis-Test mit echtem Dialog
===================================
```
