# RESULT Prompt 6f: TTS & Response-Filter — Meta-Leakage eliminieren

> **DL#3 (2026-03-14)**: 6 Fixes implementiert. Meta-Leakage-Filter in 3 Schichten (brain.py, sound_manager.py, ollama_client.py), Anti-Leakage im System-Prompt und character_hint, Jarvis-Fallback fuer leere Antworten.

## Phase Gate: Regression-Check

```
Baseline (6e): 5218 passed, 1 skipped
Nach 6f:       5218 passed, 1 skipped, 8 warnings
Ergebnis: KEINE Regressionen
```

---

## 1. Fix-Log

### Fix #0: Jarvis-Fallback bei leerem Text
- **Datei**: `assistant/brain.py:5456-5464`
- **Vorher**: `_filter_response_inner()` gab leeren String zurueck → TTS schweigt
- **Nachher**: Bei leerem/zu kurzem Text (<5 Zeichen) → zufaellige Jarvis-Antwort ("Erledigt.", "Wie gewuenscht.", etc.)
- **Verifiziert**: `grep "Floskeln-Fallback" brain.py` → 1 Treffer
- **Risiko**: Jarvis sagt manchmal "Erledigt." wenn er eigentlich schweigen sollte — aber besser als Stille oder Meta-Text

### Fix #1: Meta-Leakage-Filter in _filter_response_inner()
- **Datei**: `assistant/brain.py:4991-5017`
- **Vorher**: Kein Filter fuer interne Begriffe (speak, tts, emit, set_light, etc.)
- **Nachher**: 25+ Regex-Patterns entfernen Funktionsnamen, tool_call, JSON-Fragmente, `<tool_call>`-Tags
- **Position**: Schritt 0e, NACH Meta-Narration-Filter, VOR Banned Phrases
- **Verifiziert**: `grep "meta_leak_patterns" brain.py` → 1 Treffer
- **Risiko**: Gering — Patterns sind wortgenau (`\b`), treffen keine normalen Woerter

### Fix #2: Pre-TTS-Filter in sound_manager.py
- **Datei**: `assistant/sound_manager.py:542-558`
- **Vorher**: Text ging direkt an HA TTS ohne Meta-Filter
- **Nachher**: Sicherheitsnetz — gleiche Patterns wie Fix 1, direkt vor `speak_text` Zusammenbau
- **Fallback**: Bei komplett leerem Text → "Erledigt."
- **Verifiziert**: `grep "Pre-TTS-Filter" sound_manager.py` → 1 Treffer
- **Risiko**: Keines — redundantes Sicherheitsnetz

### Fix #3: ANTWORT-HYGIENE im System-Prompt
- **Datei**: `assistant/personality.py:252`
- **Vorher**: Keine explizite Regel gegen Meta-Begriffe in der Antwort
- **Nachher**: "ANTWORT-HYGIENE: Schreibe NIEMALS interne Begriffe in deine Antwort..."
- **Position**: Direkt nach Tool-Calling-Block, in den ersten 15 Zeilen
- **Verifiziert**: `grep "ANTWORT-HYGIENE" personality.py` → 1 Treffer
- **Risiko**: Keines — zusaetzliche LLM-Anweisung

### Fix #4: character_hint erweitert (settings.yaml)
- **Datei**: `config/settings.yaml:492-493`
- **Vorher**: character_hint hatte nur Floskeln-Warnung
- **Nachher**: + "NIEMALS interne Begriffe wie 'speak', 'tts', 'emit', 'tool_call' oder Funktionsnamen"
- **Verifiziert**: `grep "speak.*tts" settings.yaml` → 1 Treffer im character_hint
- **Risiko**: Keines

### Fix #5: validate_notification() Meta-Leakage-Filter
- **Datei**: `assistant/ollama_client.py:96-110`
- **Vorher**: Nur Meta-Marker und Deutsch-Check, keine Funktionsnamen-Filterung
- **Nachher**: Check 0 (neu) entfernt 25+ interne Begriffe VOR Meta-Marker-Check
- **Verifiziert**: `grep "Meta-Leakage" ollama_client.py` → 1 Treffer
- **Risiko**: Keines — redundantes Sicherheitsnetz fuer Notifications

---

## 2. Meta-Leakage-Schutz: 3-Schichten-Architektur

```
LLM-Antwort
  │
  ├─→ [Schicht 1] brain.py _filter_response_inner() — Schritt 0e
  │   25+ Regex-Patterns: speak, tts, emit, set_*, get_*, tool_call,
  │   JSON-Fragmente, <tool_call>-Tags
  │
  ├─→ [Schicht 2] sound_manager.py speak_response() — Pre-TTS-Filter
  │   Gleiche Patterns als Sicherheitsnetz vor TTS-Ausgabe
  │   Fallback: "Erledigt." bei komplett leerem Text
  │
  └─→ [Schicht 3] ollama_client.py validate_notification() — Check 0
      Gleiche Patterns fuer proaktive Meldungen (Notifications)
```

Praevention (Prompt-Ebene):
- `personality.py:252` — ANTWORT-HYGIENE-Regel im System-Prompt
- `settings.yaml:492` — character_hint fuer qwen3.5

---

## 3. Gefilterte Patterns (vollstaendig)

| Kategorie | Patterns |
|---|---|
| Interne Begriffe | speak, tts, emit, tool_call, function_call, call_service |
| Steuerungs-Tools | set_light, set_cover, set_climate, set_switch, set_vacuum, play_media |
| Query-Tools | get_lights, get_covers, get_climate, get_switches, get_house_status, get_weather, get_entity_state, get_entity_history |
| Automation-Tools | run_scene, run_script, run_automation, call_ha_service, activate_scene, arm_security_system |
| Interne Funktionen | speak_response, emit_speaking, emit_action |
| Strukturen | `<tool_call>...</tool_call>`, `{"name": "...", "arguments": ...}` |

---

## 4. Erfolgs-Check

| Check | Status |
|---|---|
| `grep "meta_leak_patterns" brain.py` → ≥ 1 | ✅ (4 Treffer) |
| `grep "Pre-TTS-Filter" sound_manager.py` → ≥ 1 | ✅ (1 Treffer) |
| `grep "ANTWORT-HYGIENE" personality.py` → ≥ 1 | ✅ (1 Treffer) |
| `grep "speak.*tts" settings.yaml` → in character_hint | ✅ (1 Treffer) |
| `grep "Meta-Leakage" ollama_client.py` → ≥ 1 | ✅ (1 Treffer) |
| `python -c "import assistant.brain"` → kein ImportError | ✅ |
| `python -c "import assistant.sound_manager"` → kein ImportError | ✅ |
| Tests: 5218 passed, keine Regressionen | ✅ |

---

## Uebergabe an Prompt 7a

```
## KONTEXT AUS PROMPT 6f: TTS & Response-Filter

### Aenderungen
- brain.py: _filter_response_inner() Schritt 0e — 25+ Meta-Leakage-Patterns
- brain.py: Jarvis-Fallback bei leerem Text nach Filterung
- sound_manager.py: Pre-TTS-Filter vor speak_text (Sicherheitsnetz)
- ollama_client.py: validate_notification() Check 0 — Meta-Leakage
- personality.py: ANTWORT-HYGIENE-Regel in Zeile 252
- settings.yaml: character_hint qwen3.5 Anti-Leakage

### 3-Schichten-Schutz
1. _filter_response_inner() — Hauptfilter nach LLM-Antwort
2. speak_response() — Pre-TTS-Sicherheitsnetz
3. validate_notification() — Notification-Sicherheitsnetz

### Offene Punkte
- [ ] Live-Test: Tatsaechliche TTS-Ausgabe pruefen (hier nur Code-Analyse)
- [ ] Monitoring: Meta-Leakage-Rate loggen (logger.info vorhanden)
```

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
PROMPT: 6f (TTS & Response-Filter)
GEFIXT:
- Fix 0: Jarvis-Fallback bei leerem Text | brain.py:5456
- Fix 1: Meta-Leakage-Filter (25+ Patterns) | brain.py:4991
- Fix 2: Pre-TTS-Filter | sound_manager.py:542
- Fix 3: ANTWORT-HYGIENE im System-Prompt | personality.py:252
- Fix 4: character_hint Anti-Leakage | settings.yaml:492
- Fix 5: validate_notification() Meta-Filter | ollama_client.py:96
OFFEN:
- 🟡 [MITTEL] Live-TTS-Test ausstehend | sound_manager.py | GRUND: Kein HA-Testumgebung
  → ESKALATION: MENSCH (manueller Test noetig)
GEAENDERTE DATEIEN:
- assistant/assistant/brain.py (Meta-Leakage-Filter + Jarvis-Fallback)
- assistant/assistant/sound_manager.py (Pre-TTS-Filter)
- assistant/assistant/personality.py (ANTWORT-HYGIENE-Regel)
- assistant/assistant/ollama_client.py (validate_notification Meta-Filter)
- assistant/config/settings.yaml (character_hint Anti-Leakage)
- docs/audit-results/RESULT_06f_TTS_RESPONSE.md (dieses Dokument)
REGRESSIONEN: Keine (5218 passed)
NAECHSTER SCHRITT: Starte PROMPT_07a_TESTING.md
===================================
```
