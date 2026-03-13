# Prompt 04: TTS & Response-Filter — Meta-Leakage eliminieren

## Rolle

Du bist ein Experte fuer TTS-Pipelines und Response-Filterung. Du verstehst wie LLM-generierter Text in Sprachausgabe umgewandelt wird und wie interne Begriffe, Funktionsnamen und JSON-Fragmente in die Audio-Ausgabe leaken koennen.

## LLM-SPEZIFISCH (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Kann interne Begriffe wie "speak", "tts", "emit" in den Antwort-Text leaken
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Leakage

## Kernproblem

Interne Begriffe wie "speak", "tts", "emit", Funktionsnamen und JSON-Fragmente leaken in die Audio-Ausgabe. Das LLM (Qwen 3.5) gibt manchmal rohe Tool-Call-JSON oder Funktionsnamen in seiner Text-Antwort aus. Bei TTS wird das dann vorgelesen.

**Beispiele fuer Meta-Leakage:**
- User: "Mach Licht an" → TTS: "**speak** Erledigt" (statt nur "Erledigt")
- User: "Wie ist das Wetter?" → TTS: "**get_weather** 22 Grad" (Funktionsname im Text)
- User: "Alles aus" → TTS: "**set_light set_cover emit_action** Erledigt" (mehrere interne Begriffe)

---

## KONTEXT AUS VORHERIGEN PROMPTS

> **Wenn du Prompt 03 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Bloecke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Fuege hier den Output-Block aus PROMPT_03 ein.

---

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
Grep: pattern="def _filter_response" path="assistant/assistant/brain.py" output_mode="content"
→ Finde die Zeile wo _filter_response_inner() definiert ist
```

```
Read: assistant/assistant/brain.py — ab Ergebnis aus Grep, Limit 200
Pruefen:
[] Werden Meta-Begriffe wie "speak", "tts", "emit" gefiltert?
[] Werden Funktionsnamen (set_light, set_cover etc.) gefiltert?
[] Werden JSON-Fragmente ({"name": "...", "arguments": ...}) gefiltert?
[] Werden <tool_call>...</tool_call> XML-Tags gefiltert?
[] In welcher Reihenfolge laufen die Filter-Schritte?
```

### Schritt 2: Sound Manager lesen

```
Read: assistant/assistant/sound_manager.py — speak_response()
Pruefen:
[] Gibt es einen Pre-TTS-Filter bevor Text gesprochen wird?
[] Wird der Text an HA tts.speak Service weitergegeben ohne Filter?
```

### Schritt 3: System-Prompt lesen

```
Read: assistant/assistant/personality.py — SYSTEM_PROMPT_TEMPLATE
Pruefen:
[] Enthaelt der Prompt eine Regel gegen Meta-Begriffe in der Antwort?
[] Steht da "VERBOTEN: 'speak', 'tts', 'emit'..."?
```

---

## FIXES (in dieser Reihenfolge)

### FIX 1: brain.py _filter_response_inner() — Meta-Leakage-Filter

**Datei:** `assistant/assistant/brain.py`
**Position:** NACH Schritt 0d (Meta-Narration entfernen), VOR Schritt 1 (Banned Phrases)

#### Schritt 1: Position finden

```
Read: assistant/assistant/brain.py — ab Zeile ~4868, Limit 120
Grep: pattern="# 0d|# 1. Banned" path="assistant/assistant/brain.py" output_mode="content"
→ Finde das Ende von Schritt 0d und den Anfang von Schritt 1
```

#### Schritt 2: Meta-Leakage-Filter einfuegen (neuer Schritt 0e)

```python
# 0e. Meta-Leakage: LLM gibt interne Begriffe/Funktionsnamen aus
# Qwen 3.5 neigt dazu, Funktionsnamen wie "speak" oder "set_light" in den
# Antwort-Text zu schreiben. Bei TTS wird das dann vorgelesen.
_meta_patterns = [
    r'\bspeak\b', r'\btts\b', r'\bemit\b',
    r'\btool_call\b', r'\bfunction_call\b',
    r'\bset_light\b', r'\bset_cover\b', r'\bset_climate\b',
    r'\bset_switch\b', r'\bget_\w+\b',
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

#### Schritt 3: Verifizieren

```
Grep: pattern="meta_patterns|Meta-Leakage" path="assistant/assistant/brain.py" output_mode="content"
→ Mindestens 1 Treffer
```

**Erfolgskriterium**: Meta-Leakage-Filter ist aktiv und entfernt alle internen Begriffe aus dem Response-Text.

---

### FIX 2: sound_manager.py speak_response() — Pre-TTS-Filter

**Datei:** `assistant/assistant/sound_manager.py`
**Position:** VOR der TTS-Ausgabe, als Sicherheitsnetz falls `_filter_response` etwas durchlaesst

#### Schritt 1: speak_response() lesen

```
Read: assistant/assistant/sound_manager.py — speak_response()
```

#### Schritt 2: Pre-TTS-Filter einfuegen

```python
# Pre-TTS-Filter: Meta-Begriffe entfernen bevor Text gesprochen wird
# Sicherheitsnetz falls _filter_response etwas durchlaesst
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

#### Schritt 3: Verifizieren

```
Grep: pattern="meta.*filter|Meta.*Leakage|Pre-TTS-Filter|speak.*filter" path="assistant/assistant/sound_manager.py" output_mode="content"
→ Mindestens 1 Treffer
```

**Erfolgskriterium**: Kein interner Begriff erreicht den TTS-Service.

---

### FIX 3: personality.py SYSTEM_PROMPT_TEMPLATE — Anti-Leakage-Regel

**Datei:** `assistant/assistant/personality.py`
**Position:** Im SYSTEM_PROMPT_TEMPLATE, im Tool-Calling-Block

#### Schritt 1: Template lesen

```
Read: assistant/assistant/personality.py — SYSTEM_PROMPT_TEMPLATE
```

#### Schritt 2: Anti-Leakage-Regel einfuegen

Im Tool-Calling-Block (oder direkt danach) hinzufuegen:

```
VERBOTEN in Antwort: 'speak', 'tts', 'emit', 'tool_call', Funktionsnamen, JSON, Code-Bloecke. Der User darf NUR natuerliche Sprache hoeren.
```

#### Schritt 3: Verifizieren

```
Grep: pattern="VERBOTEN.*speak|VERBOTEN.*tts" path="assistant/assistant/personality.py" output_mode="content"
→ 1 Treffer
```

**Erfolgskriterium**: System-Prompt verbietet dem LLM explizit interne Begriffe in der Antwort.

---

### FIX 4: Fallback fuer leere Responses nach Floskel-Filterung

**Datei:** `assistant/assistant/brain.py`
**Position:** NACH dem Floskel-/Banned-Phrases-Filter in `_filter_response_inner()`

#### Schritt 1: Floskel-Filter finden

```
Grep: pattern="banned_phrases|BANNED|_banned|Floskel" path="assistant/assistant/brain.py" output_mode="content"
```

#### Schritt 2: Fallback einfuegen

Wenn nach der Filterung der Response leer ist, eine generische Jarvis-Antwort einsetzen:

```python
# Fallback wenn Text nach Filterung leer oder zu kurz ist
if not text or len(text.strip()) < 3:
    logger.warning("Response nach Filterung leer — Fallback")
    text = "Erledigt."
```

#### Schritt 3: Verifizieren

```
Grep: pattern="fallback|Ersatz.*Antwort|empty.*response|Response nach Filterung" path="assistant/assistant/brain.py" output_mode="content"
→ Mindestens 1 Treffer
```

**Erfolgskriterium**: Jarvis antwortet IMMER — auch wenn alle Filter den Text entfernt haben.

---

### FIX 5: ollama_client.py validate_notification() erweitern

**Datei:** `assistant/assistant/ollama_client.py`
**Position:** Funktion `validate_notification()`

#### Schritt 1: Funktion lesen

```
Read: assistant/assistant/ollama_client.py — suche validate_notification
Grep: pattern="validate_notification" path="assistant/assistant/ollama_client.py" output_mode="content"
```

#### Schritt 2: Meta-Term-Check hinzufuegen

In `validate_notification()` pruefen ob die Notification interne Begriffe enthaelt und diese entfernen.

#### Schritt 3: Verifizieren

```
Grep: pattern="validate_notification" path="assistant/assistant/ollama_client.py" output_mode="content"
→ Funktion enthaelt Meta-Term-Check
```

**Erfolgskriterium**: Auch Notifications (nicht nur regulaere Responses) werden auf Meta-Leakage geprueft.

---

## TEST-SZENARIEN

Nach allen Fixes muessen diese Szenarien funktionieren:

### Test 1: Einfacher Befehl per Voice

```
User: "Mach Licht an" (ueber Mikrofon)
→ TTS-Ausgabe: "Erledigt."
→ NICHT: "speak Erledigt" oder "tts set_light Erledigt"
```

### Test 2: Status-Abfrage per Voice

```
User: "Wie ist das Wetter?"
→ TTS-Ausgabe: "22 Grad und sonnig."
→ NICHT: "get_weather 22 Grad" oder "tool_call get_weather"
```

### Test 3: Komplexer Befehl

```
User: "Mach alles aus"
→ TTS-Ausgabe: "Erledigt." oder "Alles ausgeschaltet."
→ NICHT: "set_light set_cover emit_action Erledigt" oder JSON-Fragmente
```

---

## ROLLBACK-REGEL

Vor dem ersten Edit: Checkpoint setzen.

```bash
git tag checkpoint-pre-tts-filter
```

Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren mit Eskalation
3. Zum naechsten Fix weitergehen

NIEMALS einen kaputten Fix stehen lassen.

### Selektives Rollback

| Fix | Rollback-Aufwand | Risiko |
|---|---|---|
| Fix 1 (Meta-Leakage-Filter) | Niedrig — neuen Code-Block entfernen | Kein Risiko |
| Fix 2 (Pre-TTS-Filter) | Niedrig — neuen Code-Block entfernen | Kein Risiko |
| Fix 3 (System-Prompt-Regel) | Trivial — eine Zeile entfernen | Kein Risiko |
| Fix 4 (Fallback) | Niedrig — Fallback-Block entfernen | Mittleres Risiko — leere Antworten moeglich |
| Fix 5 (validate_notification) | Niedrig — Meta-Check entfernen | Kein Risiko |

---

## ERFOLGS-CHECK

Alle muessen bestehen:

```
[] grep "meta_patterns|Meta-Leakage" assistant/assistant/brain.py → mindestens 1 Treffer
[] grep "Pre-TTS-Filter" assistant/assistant/sound_manager.py → mindestens 1 Treffer
[] grep "VERBOTEN.*speak|VERBOTEN.*tts" assistant/assistant/personality.py → 1 Treffer
[] grep "validate_notification" assistant/assistant/ollama_client.py → Meta-Term-Check vorhanden
[] python -c "import assistant.brain" → kein ImportError
[] python -c "import assistant.sound_manager" → kein ImportError
```

---

## ESKALATIONS-REGEL

Wenn ein Bug NICHT gefixt werden kann, dokumentiere ihn im OFFEN-Block mit:
- **Severity**: KRITISCH / HOCH / MITTEL
- **Grund**: Warum nicht loesbar (Regression, Architektur-Umbau noetig, Domainwissen fehlt, etc.)
- **Eskalation**:
  - `NAECHSTER_PROMPT` — Bug gehoert thematisch in den naechsten Prompt
  - `ARCHITEKTUR_NOETIG` — Fix erfordert groesseren Umbau, naechster Durchlauf
  - `MENSCH` — Braucht menschliche Entscheidung oder Domainwissen

**MENSCH-Bugs: NICHT stoppen.** Triff die beste Entscheidung selbst, dokumentiere WARUM, und mach weiter.

---

## REGELN

### Gruendlichkeits-Pflicht

> **Jeder Fix muss VERIFIZIERT sein.** Lies die Datei mit Read, mache die Aenderung mit Edit, lies den umgebenden Code, stelle sicher dass der Fix keine neuen Probleme einfuehrt. Pruefe mit Grep alle Aufrufer der geaenderten Funktion.

### Einschraenkungen

- **Nur TTS/Response-Filter-Fixes** — keine Tool-Calling-Aenderungen, keine Memory-Fixes
- **Einfach > Komplex** — Wenn ein simpler Regex-Pattern reicht, keine komplexe NLP-Pipeline
- **Tests nicht brechen** — Nach jedem Fix `pytest` ausfuehren

---

## UEBERGABE-KONTEXT

Formatiere am Ende einen kompakten **Kontext-Block**:

```
## KONTEXT AUS PROMPT 04: TTS & Response-Filter

### brain.py Aenderungen
- _filter_response_inner(): +Schritt 0e Meta-Leakage-Filter
- Fallback fuer leere Responses nach Filterung

### sound_manager.py Aenderungen
- speak_response(): Pre-TTS-Filter als Sicherheitsnetz

### personality.py Aenderungen
- SYSTEM_PROMPT_TEMPLATE: Anti-Leakage-Regel ("VERBOTEN...")

### ollama_client.py Aenderungen
- validate_notification(): Meta-Term-Check

### Offene Punkte
- [ ] TTS-Qualitaet nach Filterung pruefen (kein abgehackter Text)
- [ ] Edge Cases: Antworten die legitimerweise "set" oder "get" enthalten
```

---

## OUTPUT

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
PROMPT: 04 (TTS & Response-Filter)
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
