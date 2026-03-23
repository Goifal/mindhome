# PROMPT 06f — TTS & Response-Filter: Meta-Leakage eliminieren

## ZIEL

Jarvis darf NIEMALS interne Begriffe wie "speak", "tts", "emit", Funktionsnamen, JSON-Fragmente oder Meta-Text in seiner Antwort haben. Aktuell sagt Jarvis bei Sprachausgabe (TTS) manchmal "speak" — das kommt vom LLM, das interne Begriffe in den Antwort-Text leakt.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Kurzfassung: Thinking-Mode bei Tool-Calls deaktivieren (`supports_think_with_tools: false`), `character_hint` in model_profiles nutzen.
> **TTS-spezifisch**: Qwen kann interne Begriffe wie "speak", "tts", "emit" in den Antwort-Text leaken.

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Analyse-Prompts:

```
Read: docs/audit-results/RESULT_06a_STABILISIERUNG.md
Read: docs/audit-results/RESULT_06e_GERAETESTEUERUNG.md
```

> Falls eine Datei nicht existiert → überspringe sie. Wenn KEINE Result-Dateien existieren, nutze Kontext-Blöcke aus der Konversation oder starte mit Prompt 01.

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

Zuerst die exakte Position finden:
```
Grep: pattern="def _filter_response" path="assistant/assistant/brain.py" output_mode="content"
→ Finde die Zeile wo _filter_response_inner() definiert ist
```

Dann den Filter lesen:
```
Read: assistant/assistant/brain.py
Offset: [Ergebnis aus Grep], Limit: 200
Funktion: _filter_response_inner()

Prüfe:
□ Werden Meta-Begriffe wie "speak", "tts", "emit" gefiltert?
□ Werden Funktionsnamen (set_light, set_cover etc.) gefiltert?
□ Werden JSON-Fragmente ({"name": "...", "arguments": ...}) gefiltert?
□ Werden <tool_call>...</tool_call> XML-Tags gefiltert?
□ In welcher Reihenfolge laufen die Filter-Schritte?
```

Bestehende Meta-Filter pruefen:
```
Grep: pattern="speak\|tts\|emit\|meta" path="assistant/assistant/brain.py" output_mode="content"
→ Gibt es bereits einen Filter fuer diese Begriffe?
→ Falls ja: Ist er vollstaendig? Fehlen Patterns?
→ Falls nein: Filter muss komplett neu erstellt werden (siehe FIX 1)
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

### FIX 0: Floskeln-Filter mit Jarvis-Fallback-Antworten

> **MCU-Referenz**: Jarvis sagt NIE "Natürlich!", "Gerne!", "Kann ich noch etwas tun?". Er sagt "Erledigt.", "Wie gewünscht.", "Wird gemacht." — kurz, trocken, effizient.

**Das Problem:** `_filter_response()` entfernt Floskeln, aber was wenn die Antwort DANACH leer oder zu kurz ist? Es braucht Jarvis-authentische Fallback-Antworten.

**Datei:** `assistant/assistant/brain.py`
**Position:** IN `_filter_response_inner()`, NACH dem Banned-Phrases-Filter

**Read** brain.py um `banned_phrases` / `BANNED` zu finden
**Grep** `"banned_phrases\|BANNED\|_banned"` in brain.py

**Edit** — NACH dem Banned-Phrases-Filter einfügen:

```python
# Fallback wenn Text nach Floskeln-Filter zu kurz ist
if not text or len(text.strip()) < 5:
    # Intent-basierte Jarvis-Fallbacks (KEINE Floskeln!)
    _jarvis_fallbacks = {
        "device_control": [
            "Erledigt.", "Wie gewünscht.", "Wird gemacht.",
            "Umgesetzt.", "Erledigt, Sir.",
        ],
        "query": [
            "Keine weiteren Daten verfügbar.",
            "Das übersteigt meine aktuelle Sensorik.",
        ],
        "greeting": [
            "Sir.", "Guten Morgen, Sir.", "Willkommen zurück.",
        ],
        "confirmation": [
            "Verstanden.", "Notiert.", "Wird berücksichtigt.",
        ],
        "unknown": [
            "Sir?", "Ich bin hier.", "Systeme bereit.",
        ],
    }
    import random
    intent = _detect_intent(original_text) if original_text else "unknown"
    fallbacks = _jarvis_fallbacks.get(intent, _jarvis_fallbacks["unknown"])
    text = random.choice(fallbacks)
    logger.info("Floskeln-Fallback aktiviert: intent=%s → '%s'", intent, text)
```

**Verifizieren:**
```
Grep: "jarvis_fallbacks\|Floskeln-Fallback" in brain.py → mindestens 1 Treffer
```

**Warum FIX 0 (vor allen anderen):** Die Floskeln-Filterung ist die Grundlage. Wenn danach leerer Text rauskommt und kein Fallback existiert, sagt Jarvis NICHTS — oder schlimmer, spricht den leeren String als TTS. FIX 0 stellt sicher dass IMMER eine Jarvis-authentische Antwort rauskommt.

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

**Referenz-Implementierung (kompakt):**

```python
# 0e. Meta-Leakage: LLM gibt interne Begriffe/Funktionsnamen aus
_meta_patterns = [
    r'\bspeak\b', r'\btts\b', r'\bemit\b',
    r'\btool_call\b', r'\bfunction_call\b',
    r'\bset_light\b', r'\bset_cover\b', r'\bset_climate\b',
    r'\bset_switch\b', r'\bget_\w+\b',  # ACHTUNG: Pattern matcht auch natürliche Wörter wie 'get'. Nur auf LLM-Output anwenden, nicht auf User-Input.
    r'\bemit_speaking\b', r'\bemit_action\b',
    r'\bspeak_response\b', r'\bcall_service\b',
    r'<tool_call>.*?</tool_call>',
    r'\{"name":\s*"\w+".*?"arguments".*?\}',
]
for pattern in _meta_patterns:
    new_text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    if new_text != text:
        logger.info("Meta-Leakage entfernt: pattern=%s", pattern)
    text = new_text
text = re.sub(r'\s{2,}', ' ', text).strip()
```

**Verify:**
```
Grep: "meta_leak_patterns\|Meta-Leakage" in brain.py → mindestens 1 Treffer
Read: brain.py um die neue Stelle → Code-Syntax korrekt?
```

### FIX 1b: Markdown + Entity-ID + Timestamp Filter (Ergänzung P04d)

> **Dieses Fix ergänzt FIX 1.** P04d (Speech Pipeline) hat zusätzliche Leakage-Typen identifiziert die in FIX 1 fehlen.

**Datei:** `assistant/assistant/brain.py` — DIREKT NACH dem Meta-Leakage-Block aus FIX 1

```python
# 0f. Markdown entfernen (wird sonst von TTS vorgelesen)
text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **fett** → fett
text = re.sub(r'\*([^*]+)\*', r'\1', text)       # *kursiv* → kursiv
text = re.sub(r'`([^`]+)`', r'\1', text)         # `code` → code
text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # # Überschrift → Überschrift
text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)  # - Liste → Liste

# 0g. Entity-IDs durch natürliche Namen ersetzen
# "light.wohnzimmer_decke" → "Wohnzimmer Decke" (falls im Response)
text = re.sub(
    r'\b(light|switch|cover|climate|sensor|lock|media_player)\.\w+',
    lambda m: m.group(0).split('.')[-1].replace('_', ' ').title(),
    text
)

# 0h. Timestamps und Debug-Info entfernen
text = re.sub(r'\[\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]', '', text)
text = re.sub(r'\b(DEBUG|INFO|WARNING|ERROR|CRITICAL):?\s*', '', text)
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
    r'|set_light|set_cover|set_climate|set_switch|get_\w+)\b',  # ACHTUNG: Pattern matcht auch natürliche Wörter wie 'get'. Nur auf LLM-Output anwenden, nicht auf User-Input.
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
2. Im OFFEN-Block dokumentieren mit Eskalation (siehe unten)
3. Zum nächsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## ESKALATIONS-REGEL

Wenn ein Bug NICHT gefixt werden kann, dokumentiere ihn im OFFEN-Block mit:
- **Severity**: 🔴 KRITISCH / 🟠 HOCH / 🟡 MITTEL
- **Grund**: Warum nicht loesbar (Regression, Architektur-Umbau noetig, Domainwissen fehlt, etc.)
- **Eskalation**:
  - `ARCHITEKTUR_NOETIG` — Fix erfordert groesseren Umbau, naechster Durchlauf
  - `MENSCH` — Braucht menschliche Entscheidung oder Domainwissen

**MENSCH-Bugs: NICHT stoppen.** Triff die beste Entscheidung selbst, dokumentiere WARUM, und mach weiter.
**P06f ist der letzte Fix-Prompt** — alle verbleibenden OFFEN-Bugs gehen an P07a zur Validierung und dann an RESET.

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

## ⚡ Uebergabe an Prompt 7a

> **Nach P06f ist die Fix-Phase abgeschlossen (P06a-P06f).** Weiter mit P07a (Testing) um alle Fixes zu verifizieren.

## Praxis-Testszenarien

TEST 1: Sprachausgabe ohne Meta-Leakage
  User: "Mach Licht an" (per Voice)
  → TTS-Ausgabe: "Erledigt." (NICHT "speak Erledigt" oder "tts Erledigt")

TEST 2: Status-Abfrage
  User: "Wie ist das Wetter?"
  → TTS darf KEINE Funktionsnamen enthalten

TEST 3: Komplexer Befehl
  User: "Mach Licht an und sag mir die Temperatur"
  → Antwort darf KEIN JSON oder tool_call Tags enthalten

## Erfolgs-Check
□ grep "meta_patterns\|Meta-Leakage" brain.py → mindestens 1 Treffer
□ grep "VERBOTEN.*speak\|VERBOTEN.*tts" personality.py → vorhanden
□ grep "fallback\|Ersatz.*Antwort" brain.py → Empty-Response-Fallback existiert
□ python -c "import assistant.brain" → kein ImportError

---

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_06f_TTS_RESPONSE.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

---

## OUTPUT

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
PROMPT: 6f (TTS & Response-Filter)
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: Starte PROMPT_07a_TESTING.md
===================================
```
