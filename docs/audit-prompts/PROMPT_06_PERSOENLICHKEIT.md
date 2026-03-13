# Prompt 06: Persoenlichkeit — Audit + MCU-Jarvis-Authentizitaet

## Rolle

Du bist ein Elite-Software-Architekt mit Fokus auf Character Consistency und MCU-Jarvis-Authentizitaet. Du sorgst dafuer, dass JEDE Antwort durch dieselbe Personality-Pipeline laeuft und der Charakter konsistent, trocken und professionell bleibt — wie im MCU. Dieser Prompt ersetzt die alten P05 (Analyse) + P06c (Charakter-Fix).

---

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–5 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Bloecke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Fuege hier die Kontext-Bloecke ein:
> - Prompt 1: Konflikt-Karte (besonders Personality-Konflikte)
> - Prompt 4a-c: Bug-Reports (besonders Personality-relevante Bugs)
> - Prompt 5: Fix-Ergebnisse (falls vorhanden)

---

## Aufgabe (3 Phasen)

### Phase 1: Personality-Audit (20min)

1. **Read** `personality.py` — `SYSTEM_PROMPT_TEMPLATE` (Zeile 242–286)
2. **Read** `personality.py` — `build_system_prompt()` (Zeile 2233–2515)
3. **MCU-Authentizitaets-Check** — Score-Ziel: ≥ 7/10
   - Ist der Ton trocken, professionell, mit Hauch von Humor?
   - Wird "Sir" korrekt verwendet?
   - Keine Floskeln ("Natuerlich!", "Gerne!", "Klar!")?
4. **Token-Schaetzung** — Ziel: < 800 Tokens Basis-Text
   - System-Prompt zaehlen (ca. 4 Zeichen = 1 Token)
   - Wenn > 800: Kuerzungspotenzial identifizieren
5. **Pipeline-Konsistenz** — Gehen ALLE Code-Pfade durch dieselbe Personality-Pipeline?
   - Grep: `pattern="build_system_prompt\|_filter_response" path="assistant/assistant/"`
   - Shortcuts finden die die Pipeline umgehen
6. **Read** `personality.py` — `MOOD_STYLES` — Humor-Level pruefen, Stress/Humor-Konflikt pruefen
7. **Read** `settings.yaml` — Persona-Config pruefen

### Phase 2: Personality-Fixes (40min)

1. **System-Prompt optimieren** — Kuerzen auf unter 800 Tokens Basis-Text
   - Redundante Anweisungen entfernen
   - Kompaktere Formulierungen
   - Kern-Charakter beibehalten
2. **Humor Level 4/5 identisch** — Fix in `personality.py:74-85`
   - Level 4 und Level 5 muessen sich unterscheiden
   - Level 5 = maximaler Sarkasmus, Level 4 = haeufiger Humor aber zurueckhaltender
3. **Humor nicht gedaempft bei Stress** — Fix in `personality.py:1433-1434`
   - Bei Stress-Mood: Humor automatisch reduzieren
   - Jarvis wird bei Stress kuerzer und sachlicher (MCU-authentisch)
4. **Alle Response-Pfade durch `_filter_response`**
   - Grep: `pattern="return.*response\|return.*answer\|return.*reply" path="assistant/assistant/brain.py"`
   - Jeder Pfad der NICHT durch `_filter_response` geht = Bug
5. **Config aufraeumen** — Ungenutzte YAML-Keys loeschen
   - Grep ZUERST: `pattern="KEY_NAME" path="assistant/"` — nur loeschen wenn 0 Treffer
   - NIEMALS Keys loeschen ohne Grep-Verifikation
6. **Banned Phrases fuer Qwen-Floskeln hinzufuegen**
   - "Natuerlich!", "Gerne!", "Klar!", "Selbstverstaendlich!"
   - In `_filter_response` oder `banned_phrases` Liste
7. **Shortcuts umgehen Personality-Pipeline** — Fix in `brain.py:1349-2300`
   - Alle Shortcut-Antworten muessen durch `_filter_response`
   - Grep: `pattern="return.*\"" path="assistant/assistant/brain.py"` — Hardcoded Strings finden
8. **Dead Code entfernen**
   - Grep ZUERST: `pattern="function_name" path="assistant/assistant/"` — nur loeschen wenn 0 Aufrufer
   - NIEMALS Code loeschen ohne Grep-Verifikation

### Phase 3: MCU Character Polish (20min)

1. **Sarkasmus-System verifizieren** — 5 Stufen muessen existieren und sich unterscheiden
   - Stufe 1: Minimal, fast neutral
   - Stufe 2: Gelegentlich trocken
   - Stufe 3: Regelmaessig, aber nie beleidigend
   - Stufe 4: Haeufig, pointiert
   - Stufe 5: Maximal, jede Antwort hat Edge
2. **Easter-Egg-Trigger pruefen** — Existieren MCU-Referenzen?
   - "Avengers Protocol", "Clean Slate Protocol", "House Party Protocol"
3. **Mood-Detection-Integration** — Ist `mood_detector.py` korrekt mit Personality verbunden?
4. **MCU-Dialog-Beispiele fuer Testing** — Referenz-Antworten erstellen

---

## Test-Dialoge

### TEST 1: Normaler Gruss
**User**: "Guten Morgen, Jarvis."
**Erwartet**: Trocken, professionell, Hauch von Humor. Beispiel: "Guten Morgen, Sir. Die Systeme laufen, das Wetter weniger."
**FAIL wenn**: "Guten Morgen! Wie kann ich Ihnen helfen?" (zu generisch, zu freundlich)

### TEST 2: Floskel-Check
**User**: Beliebige Frage
**Erwartet**: Antwort enthaelt NICHT "Natuerlich!", "Gerne!", "Klar!", "Selbstverstaendlich!"
**FAIL wenn**: Jede dieser Floskeln in der Antwort auftaucht

### TEST 3: Stress-Szenario
**User**: Rauchmelder-Alarm + Frage
**Erwartet**: Kuerzere Antworten, weniger Humor, aber immer noch in Character. Beispiel: "Rauchmelder aktiv im Erdgeschoss. Fenster werden geschlossen."
**FAIL wenn**: Antwort ist lang, humorvoll, oder aus dem Charakter fallend

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren mit Eskalation
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

---

## Erfolgs-Check (Schnellpruefung)

```
□ MCU-Score ≥ 7/10
□ System-Prompt base < 800 tokens
□ grep "Natuerlich\|Gerne\|Klar" personality.py → in banned_phrases
□ Alle Response-Pfade durch _filter_response
□ Keine ungenutzten Config-Keys
□ python -c "import assistant.personality" → kein ImportError
```

---

## Regeln

### Claude Code Tool-Einsatz

| Aufgabe | Tool |
|---|---|
| Personality-Code lesen | **Read**: `personality.py`, `brain.py`, `mood_detector.py` |
| Pipeline-Umgehungen finden | **Grep**: `pattern="_filter_response\|build_system_prompt" path="assistant/assistant/"` |
| Floskel-Check | **Grep**: `pattern="Natuerlich\|Gerne\|Klar\|Selbstverstaendlich" path="assistant/assistant/"` |
| Config-Nutzung pruefen | **Grep**: `pattern="KEY_NAME" path="assistant/"` |
| Syntax-Check | **Bash**: `python -c "import assistant.personality"` |

- **MCU-Authentizitaet hat Prioritaet** — lieber zu trocken als zu freundlich
- **Config-Keys NUR loeschen nach Grep-Verifikation**
- **Dead Code NUR loeschen nach Grep-Verifikation**
- **Jeder Fix muss Character-konsistent sein**

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
