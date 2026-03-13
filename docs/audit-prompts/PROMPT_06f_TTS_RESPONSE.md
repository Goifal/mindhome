# PROMPT 06f — TTS & Response-Filter: Meta-Leakage eliminieren

## ZIEL

Jarvis darf NIEMALS interne Begriffe wie "speak", "tts", "emit", Funktionsnamen, JSON-Fragmente oder Meta-Text in seiner Antwort haben. Aktuell sagt Jarvis bei Sprachausgabe (TTS) manchmal "speak" — das kommt vom LLM, das interne Begriffe in den Antwort-Text leakt.

## LLM-SPEZIFISCH (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu höflichen Floskeln ("Natürlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann interne Begriffe wie "speak", "tts", "emit" in den Antwort-Text leaken
- character_hint in settings.yaml model_profiles nutzen für Anti-Leakage

## KONTEXT AUS VORHERIGEM PROMPT

[Hier den Output-Block aus PROMPT_06e einfuegen]

## ARCHITEKTUR

```
User-Eingabe → brain.py process()
  → LLM-Call (Ollama/Qwen 3.5)
  → Response-Text vom LLM
  → brain.py _filter_response() ← HIER filtern
  → sound_manager.py speak_response() ← HIER nochmal filtern vor TTS
  → Home Assistant TTS Service (tts.speak)
  → Lautsprecher spricht Text
```

## ANALYSE (Read-Only Phase)

### Schritt 1: Response-Filter lesen

```
Lies: assistant/assistant/brain.py
Offset: 4844, Limit: 200
Funktion: _filter_response_inner()

Prüfe:
□ Werden Meta-Begriffe wie "speak", "tts", "emit" gefiltert?
□ Werden Funktionsnamen (set_light, set_cover etc.) gefiltert?
□ Werden JSON-Fragmente ({"name": "...", "arguments": ...}) gefiltert?
□ Werden <tool_call>...</tool_call> XML-Tags gefiltert?
□ In welcher Reihenfolge laufen die Filter-Schritte?
```

### Schritt 2: Sound Manager lesen

```
Lies: assistant/assistant/sound_manager.py
Offset: 495, Limit: 80
Funktion: speak_response()

Prüfe:
□ Gibt es einen Pre-TTS-Filter bevor Text gesprochen wird?
□ Zeile 543: speak_text = tts_data.get("ssml", text) — wird hier gefiltert?
□ Wird der Text an HA tts.speak Service weitergegeben ohne Filter?
```

### Schritt 3: System-Prompt lesen

```
Lies: assistant/assistant/personality.py
Offset: 242, Limit: 50
Funktion: SYSTEM_PROMPT_TEMPLATE

Prüfe:
□ Enthält der Prompt eine Regel gegen Meta-Begriffe in der Antwort?
□ Steht da "VERBOTEN: 'speak', 'tts', 'emit'..."?
```

### Schritt 4: Banned Phrases prüfen

```
Grep: "banned_phrases\|banned_starters" in brain.py
Prüfe: Sind interne Begriffe in der Banned-Liste?
```

## FIXES (in dieser Reihenfolge)

### FIX 1: Meta-Leakage-Filter in _filter_response_inner()

**Datei:** `assistant/assistant/brain.py`
**Position:** NACH Schritt 0d (Meta-Narration entfernen, ca. Zeile 4973), VOR Schritt 1 (Banned Phrases)

**Read** brain.py ab Zeile 4940, Limit 40 — finde das Ende von Schritt 0d
**Grep** "# 1. Banned Phrases" in brain.py — finde den Anfang von Schritt 1

**Edit** — füge ZWISCHEN 0d und 1 ein:

```python
# 0e. Meta-Leakage entfernen: LLM gibt interne Begriffe/Funktionsnamen aus
# Qwen 3.5 neigt dazu, Funktionsnamen wie "speak" oder "set_light" in den
# Antwort-Text zu schreiben. Bei TTS wird das dann vorgelesen.
_meta_leak_patterns = [
    r'\bspeak\b',
    r'\btts\b',
    r'\bemit\b',
    r'\btool_call\b',
    r'\bfunction_call\b',
    r'\bcall_service\b',
    r'\bspeak_response\b',
    r'\bemit_speaking\b',
    r'\bemit_action\b',
    r'\bset_light\b',
    r'\bset_cover\b',
    r'\bset_climate\b',
    r'\bset_switch\b',
    r'\bplay_media\b',
    r'\bactivate_scene\b',
    r'\bget_lights\b',
    r'\bget_covers\b',
    r'\bget_climate\b',
    r'\bget_switches\b',
    r'\bget_house_status\b',
    r'\bget_weather\b',
    r'<tool_call>.*?</tool_call>',
    r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:.*?\}',
]
for _ml_pat in _meta_leak_patterns:
    _new = re.sub(_ml_pat, '', text, flags=re.IGNORECASE | re.DOTALL)
    if _new != text:
        logger.info("Meta-Leakage entfernt: %s", _ml_pat[:30])
    text = _new
# Bereinigung: Mehrfach-Leerzeichen und leere Klammern
text = re.sub(r'\s{2,}', ' ', text).strip()
text = re.sub(r'\(\s*\)', '', text).strip()
text = re.sub(r'^\s*[,;:\-–—]\s*', '', text).strip()
if text:
    text = text[0].upper() + text[1:]
```

**Verify:**
```
Grep: "meta_leak_patterns\|Meta-Leakage" in brain.py → mindestens 1 Treffer
Read: brain.py um die neue Stelle → Code-Syntax korrekt?
```

### FIX 2: Pre-TTS-Filter in sound_manager.py

**Datei:** `assistant/assistant/sound_manager.py`
**Position:** VOR Zeile 543 (wo `speak_text` zusammengebaut wird)

**Read** sound_manager.py ab Zeile 540, Limit 10

**Edit** — füge VOR der Zeile `speak_text = tts_data.get("ssml", text) if tts_data.get("ssml") else text` ein:

```python
# Pre-TTS-Filter: Meta-Begriffe entfernen bevor Text gesprochen wird
# Sicherheitsnetz falls _filter_response etwas durchlässt
import re as _re
text = _re.sub(
    r'\b(?:speak|tts|emit|tool_call|function_call|call_service'
    r'|set_light|set_cover|set_climate|set_switch|get_\w+)\b',
    '', text, flags=_re.IGNORECASE,
).strip()
if not text:
    logger.warning("Pre-TTS-Filter hat gesamten Text entfernt — Fallback")
    text = "Erledigt."
```

**Verify:**
```
Grep: "Pre-TTS-Filter\|Meta-Begriffe" in sound_manager.py → mindestens 1 Treffer
Read: sound_manager.py um die neue Stelle → Syntax korrekt?
```

### FIX 3: Anti-Leakage-Regel im System-Prompt

**Datei:** `assistant/assistant/personality.py`
**Position:** Im SYSTEM_PROMPT_TEMPLATE, idealerweise im Tool-Calling-Block

**Read** personality.py ab Zeile 242, Limit 50

**Edit** — nach der Zeile "GERAETESTEUERUNG: Geraet steuern = IMMER Tool-Call..." füge hinzu:

```
ANTWORT-HYGIENE: Schreibe NIEMALS interne Begriffe in deine Antwort: 'speak', 'tts', 'emit', 'tool_call', 'function', 'set_light', 'set_cover', JSON-Objekte, Code-Blöcke. Der User darf NUR natürliche Sprache hören.
```

**Verify:**
```
Grep: "ANTWORT-HYGIENE\|interne Begriffe" in personality.py → 1 Treffer
```

### FIX 4: Qwen 3.5 character_hint erweitern

**Datei:** `assistant/config/settings.yaml`
**Position:** model_profiles → qwen3.5 → character_hint

**Read** settings.yaml ab Zeile 474, Limit 20

**Edit** — erweitere den character_hint um:

```
NIEMALS interne Begriffe wie 'speak', 'tts', 'emit' in die Antwort schreiben.
```

**Verify:**
```
Grep: "speak.*tts.*emit\|interne Begriffe" in settings.yaml → mindestens 1 Treffer
```

### FIX 5: validate_notification() erweitern

**Datei:** `assistant/assistant/ollama_client.py`
**Position:** Funktion `validate_notification()` oder `strip_think_tags()`

**Read** — suche nach `validate_notification` in ollama_client.py

**Prüfe:** Filtert diese Funktion Meta-Begriffe aus Notifications?
Wenn nicht → gleiche Meta-Leak-Patterns wie in FIX 1 hinzufügen.

## PRAXIS-TESTSZENARIEN

Nach allen Fixes — diese Szenarien MÜSSEN funktionieren:

```
TEST 1: Einfacher Befehl per Voice
  User: "Mach Licht an" (über Mikrofon)
  → TTS-Ausgabe: "Erledigt."
  → NICHT: "speak Erledigt" oder "tts set_light Erledigt"

TEST 2: Status-Abfrage per Voice
  User: "Wie warm ist es?"
  → TTS-Ausgabe: "22 Grad im Wohnzimmer."
  → NICHT: "get_climate 22 Grad" oder "tool_call get_climate"

TEST 3: Komplexer Befehl
  User: "Mach alles aus"
  → TTS-Ausgabe: "Erledigt." oder "Alles ausgeschaltet."
  → NICHT: "set_light set_cover emit_action Erledigt"
```

## ROLLBACK-REGEL

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zurücknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum nächsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## ERFOLGS-CHECK

Alle müssen bestehen:
```
□ grep -c "meta_leak_patterns" assistant/assistant/brain.py → ≥ 1
□ grep -c "Pre-TTS-Filter" assistant/assistant/sound_manager.py → ≥ 1
□ grep -c "ANTWORT-HYGIENE" assistant/assistant/personality.py → ≥ 1
□ grep "speak.*tts" assistant/config/settings.yaml → in character_hint
□ python -c "import assistant.brain" → kein ImportError
□ python -c "import assistant.sound_manager" → kein ImportError
```

## OUTPUT

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FÜR NÄCHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEÄNDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NÄCHSTER SCHRITT: [Was der nächste Prompt tun soll]
===================================
```
