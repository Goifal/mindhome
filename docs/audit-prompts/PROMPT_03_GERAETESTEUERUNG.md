# Prompt 03: Geraetesteuerung — Tool-Calling fuer Qwen 3.5 optimieren

## Rolle

Du bist ein Experte fuer LLM-Tool-Calling-Optimierung, spezialisiert auf kleine Modelle (Qwen 3.5, 4B Parameter). Du verstehst wie kleine LLMs Tool-Calls generieren, warum sie dabei scheitern, und wie man System-Prompts strukturiert damit Tool-Calls zuverlaessig funktionieren.

## LLM-SPEZIFISCH (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- supports_think_with_tools: false — Thinking-Modus bei Tool-Calls DEAKTIVIEREN
- character_hint in settings.yaml model_profiles nutzen fuer Tool-Calling-Regeln
- Token-Budget ist knapp — alles ueber ~2000 Token im System-Prompt reduziert die Tool-Calling-Zuverlaessigkeit dramatisch
- Die ersten 10 Zeilen des System-Prompts haben 5x mehr Gewicht als spaetere Zeilen
- Weniger Tools = bessere Trefferquote: bei 15 Tools ~80%, bei 45+ sinkt sie auf ~30%

## Kernproblem

Qwen 3.5 generiert **unzuverlaessige** Tool-Calls fuer Geraetesteuerung. Ursachen:

1. **Langer System-Prompt** drueckt Tool-Calling-Anweisungen aus dem Fokus — Tool-Regeln stehen in Zeile ~275 von `personality.py`, BEGRABEN unter 20+ dynamischen Sektionen
2. **45+ Tools pro Request** ueberfordern ein 4B-Modell — die Trefferquote sinkt auf ~30%
3. **Thinking-Modus aktiv bei Tool-Calls**: `supports_think_with_tools: true` in `settings.yaml` laesst das Modell "nachdenken" statt Tool-Calls zu generieren
4. **Schwacher Fallback**: `_deterministic_tool_call()` faengt nur Status-Abfragen ab, NICHT Steuerungsbefehle (Licht, Rollladen, Heizung, Schalter)
5. **Vage Retry-Hints**: Der Retry-Mechanismus sagt dem LLM nicht WELCHES Tool mit WELCHEN Parametern es nutzen soll

---

## KONTEXT AUS VORHERIGEN PROMPTS

> **Wenn du Prompts 1–2 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Bloecke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Fuege hier ein:
> - Kontext-Block aus Prompt 1 (Architektur-Uebersicht, besonders brain.py-Aufbau)
> - Kontext-Block aus Prompt 2 (Memory-System, falls relevant)
>
> **Ohne diese Kontext-Bloecke** fehlt dir das Verstaendnis wie brain.py die Tool-Calls orchestriert und wie der System-Prompt aufgebaut wird.

---

## AUFGABE

### Fix 1: personality.py SYSTEM_PROMPT_TEMPLATE umstrukturieren

**Ziel**: Tool-Calling-Anweisungen in die ersten 10 Zeilen des System-Prompts verschieben.

#### Schritt 1: Aktuellen System-Prompt lesen

```
Read: assistant/assistant/personality.py — Zeile 242-286, SYSTEM_PROMPT_TEMPLATE
```

#### Schritt 2: Neue Struktur (5 Bloecke, strikte Reihenfolge)

```
SYSTEM_PROMPT_TEMPLATE = """
# BLOCK 1: Identitaet (3 Zeilen)
Du bist Jarvis, ein intelligenter Hausassistent. Du sprichst Deutsch.
Dein Zuhause: {home_name}. Bewohner: {residents}.
Aktuell: {current_datetime}.

# BLOCK 2: TOOL-CALLING PFLICHT (5 Zeilen, MUSS in den ersten 10 Zeilen stehen!)
GERAETESTEUERUNG — PFLICHT:
- Geraet steuern = IMMER Tool-Call. NIEMALS nur Text-Antwort.
- Licht an/aus/dimmen → set_light(entity_id, state, brightness, color)
- Rollladen/Jalousie → set_cover(entity_id, position, state)
- Heizung/Klima → set_climate(entity_id, temperature, hvac_mode)
- Schalter/Steckdose → set_switch(entity_id, state)
- Mehrere Geraete = mehrere Tool-Calls in EINER Antwort.

# BLOCK 3: Antwortformat (3 Zeilen)
Antworte kurz und praezise. Bestaetigung nach Tool-Call: "Erledigt, Sir."
Bei Fehlern: Sage was schief ging, nicht technische Details.
Formatiere KEINE Markdown-Tabellen oder Code-Bloecke in Sprachantworten.

# BLOCK 4: Persoenlichkeit (gekuerzt, max 5 Zeilen)
{personality_summary}

# BLOCK 5: Dynamischer Kontext (nur relevante Sektionen)
{dynamic_context}
"""
```

#### Schritt 3: Verifizieren

```
Grep: pattern="GERAETESTEUERUNG|TOOL-CALLING|PFLICHT" path="assistant/assistant/personality.py" output_mode="content"
→ Muss in den ersten 10 Zeilen des Templates stehen
```

**Erfolgskriterium**: Tool-Calling-Block steht in den ersten 10 Zeilen des Templates. Keine dynamischen Sektionen mehr zwischen Block 1 und Block 3.

---

### Fix 2: settings.yaml — Thinking-Modus deaktivieren

**Ziel**: Qwen 3.5 soll Tool-Calls generieren statt zu "denken".

#### Schritt 1: Aktuelle Konfiguration lesen

```
Read: assistant/config/settings.yaml — suche "qwen3.5" oder "qwen" Profil
Grep: pattern="supports_think_with_tools" path="assistant/config/settings.yaml" output_mode="content"
```

#### Schritt 2: Aendern

```
Edit: settings.yaml
  old_string: "supports_think_with_tools: true"  (im qwen3.5-Profil)
  new_string: "supports_think_with_tools: false"
```

#### Schritt 3: Verifizieren

```
Grep: pattern="supports_think_with_tools" path="assistant/config/settings.yaml" output_mode="content"
→ qwen3.5: supports_think_with_tools: false
→ Pruefen ob andere Profile (z.B. qwen3-30b) davon betroffen sind
```

**Erfolgskriterium**: `supports_think_with_tools: false` fuer das qwen3.5-Profil.

---

### Fix 3: brain.py _deterministic_tool_call() erweitern

**Ziel**: Deterministische Tool-Calls fuer ALLE Geraetetypen — ohne LLM-Umweg.

#### Schritt 1: Bestehende Implementierung lesen

```
Read: assistant/assistant/brain.py — ab Zeile ~6916, _deterministic_tool_call()
```

#### Schritt 2: Abdeckung fuer alle Geraetetypen sicherstellen

Die Funktion MUSS folgende Geraetetypen abdecken:

| Geraetetyp | Tool | Parameter |
|---|---|---|
| Licht (an/aus) | `set_light` | `state="on"` / `state="off"` |
| Licht (Helligkeit) | `set_light` | `state="on"`, `brightness=<0-100>` |
| Licht (Farbe) | `set_light` | `state="on"`, `color=<farbe>` |
| Rollladen (auf/zu) | `set_cover` | `state="open"` / `state="close"` |
| Rollladen (Position) | `set_cover` | `position=<0-100>` |
| Heizung (Temperatur) | `set_climate` | `temperature=<grad>` |
| Heizung (an/aus) | `set_climate` | `hvac_mode="heat"` / `hvac_mode="off"` |
| Schalter/Steckdosen | `set_switch` | `state="on"` / `state="off"` |

#### Schritt 3: Verifizieren

```
Grep: pattern="_deterministic_tool_call" path="assistant/assistant/brain.py" output_mode="content"
→ Pruefen: Sind Licht, Rollladen, Klima UND Schalter abgedeckt?
```

**Erfolgskriterium**: `_deterministic_tool_call()` erkennt und verarbeitet alle 4 Geraetetypen.

---

### Fix 4: Dynamische Tool-Selektion vor LLM-Call

**Ziel**: Vor dem LLM-Call nur relevante Tools senden — nicht alle 45+.

#### Schritt 1: Aktuelle Tool-Uebergabe finden

```
Read: assistant/assistant/function_calling.py — suche get_assistant_tools()
Grep: pattern="get_assistant_tools|tools\s*=" path="assistant/assistant/brain.py" output_mode="content"
```

#### Schritt 2: Intent-basierte Tool-Filterung implementieren

```python
def _select_tools_for_intent(self, user_text: str) -> list:
    """Waehlt nur relevante Tools basierend auf dem erkannten Intent.

    - device_command Intent → nur 15 Steuerungs-Tools
    - device_query Intent → nur Abfrage-Tools
    - conversation Intent → alle Tools (Fallback)
    """
```

#### Schritt 3: Verifizieren

```
Grep: pattern="dynamic.*tool|tool.*select|intent.*tool|_select_tools_for_intent" path="assistant/assistant/brain.py" output_mode="content"
→ Funktion muss vorhanden sein und im LLM-Aufruf genutzt werden
```

**Erfolgskriterium**: Bei "Mach das Licht an" werden nur ~15 Tools ans LLM gesendet, nicht 45+.

---

### Fix 5: Retry-Hint konkret mit Tool-Uebersicht

**Ziel**: Retry-Hint mit konkreten Tool-Namen und Parameter-Format anreichern.

#### Schritt 1: Aktuellen Retry-Mechanismus lesen

```
Read: assistant/assistant/brain.py — ab Zeile ~3400, Retry-Mechanismus
Grep: pattern="retry.*hint|Hinweis.*Tool|_build_tool_call_hint" path="assistant/assistant/brain.py" output_mode="content"
```

#### Schritt 2: Spezifischen Retry-Hint generieren

Der Retry-Hint MUSS enthalten:
- Konkreten Tool-Namen (z.B. `set_light`)
- Parameter-Format (z.B. `entity_id='light.wohnzimmer', state='on'`)
- Beispiel-Aufruf

**Statt**: "Bitte nutze ein Tool fuer diese Anfrage."
**Jetzt**: "Nutze set_light(entity_id='light.wohnzimmer', state='on') fuer diese Anfrage."

#### Schritt 3: Verifizieren

```
Grep: pattern="retry.*hint|Hinweis.*Tool|_build_tool_call_hint" path="assistant/assistant/brain.py" output_mode="content"
→ Retry-Hint enthaelt Tool-Namen und Parameter-Beispiele
```

**Erfolgskriterium**: Der Retry-Hint ist spezifisch genug damit Qwen 3.5 beim zweiten Versuch den richtigen Tool-Call generiert.

---

## TEST-DIALOGE

Nach allen 5 Fixes muessen diese Dialoge funktionieren:

### Test 1: Einfache Lichtsteuerung

```
User: "Mach das Licht an"
Erwartet: Tool-Call: set_light(state="on")
Jarvis: "Erledigt."
NICHT: "Ich wuerde gerne das Licht fuer Sie einschalten..." (Text statt Tool-Call)
```

### Test 2: Rollladen mit Prozentwert

```
User: "Rollladen auf 50%"
Erwartet: Tool-Call: set_cover(position=50)
Jarvis: "Rollladen steht auf 50%."
```

### Test 3: Multi-Command

```
User: "Licht aus und Rollladen runter"
Erwartet: ZWEI Tool-Calls:
  1. set_light(state="off")
  2. set_cover(state="close")
Jarvis: "Erledigt."
NICHT: Nur ein Tool-Call oder gar keiner
```

### Test 4: Status-Abfrage (Query, NICHT Control)

```
User: "Wie warm ist es im Wohnzimmer?"
Erwartet: Query-Tool (get_entity_state oder aehnlich), NICHT set_climate!
Jarvis: "22 Grad im Wohnzimmer."
```

### Test 5: Schalter/Steckdose

```
User: "Schalte die Steckdose im Buero aus"
Erwartet: Tool-Call: set_switch(state="off")
Jarvis: "Steckdose im Buero ist aus."
```

### Test 6: Dimmen mit Prozentwert

```
User: "Dimme das Licht auf 30%"
Erwartet: Tool-Call: set_light(brightness=30)
Jarvis: "Licht auf 30% gedimmt."
```

---

## ROLLBACK-STRATEGIE

Vor dem ersten Edit: Checkpoint setzen.

```bash
git tag checkpoint-pre-geraetesteuerung
```

Falls die Fixes unerwuenschte Nebenwirkungen haben:

### Sofort-Rollback (Git)

```bash
git diff checkpoint-pre-geraetesteuerung
git checkout checkpoint-pre-geraetesteuerung -- assistant/assistant/personality.py
git checkout checkpoint-pre-geraetesteuerung -- assistant/config/settings.yaml
git checkout checkpoint-pre-geraetesteuerung -- assistant/assistant/brain.py
```

### Selektives Rollback

| Fix | Rollback-Aufwand | Risiko |
|---|---|---|
| Fix 1 (System-Prompt) | Mittel — SYSTEM_PROMPT_TEMPLATE wiederherstellen | Gering — aendert nur Prompt-Text |
| Fix 2 (settings.yaml) | Trivial — eine Zeile zurueck | Kein Risiko |
| Fix 3 (deterministic) | Niedrig — neuen Code entfernen | Kein Risiko — Fallback kann nicht verschlechtern |
| Fix 4 (Tool-Selektion) | Niedrig — zurueck zu `get_assistant_tools()` | Mittleres Risiko — Intent-Erkennung koennte false positives haben |
| Fix 5 (Retry-Hint) | Trivial — alten Hint wiederherstellen | Kein Risiko |

NIEMALS einen kaputten Fix stehen lassen. Wenn ein Fix einen ImportError oder SyntaxError verursacht: SOFORT revert, dokumentieren, zum naechsten Fix weitergehen.

---

## ERFOLGS-CHECK

Alle muessen bestehen:

```
[] grep "TOOL-CALLING\|PFLICHT" assistant/assistant/personality.py → in ersten 10 Zeilen des Templates
[] grep "supports_think_with_tools.*false" assistant/config/settings.yaml → 1 Treffer
[] grep "_deterministic_tool_call" assistant/assistant/brain.py → deckt Licht, Rollladen, Klima, Schalter ab
[] Tool-Anzahl pro Request reduziert von 45+ auf 15 fuer Geraetebefehle
[] python -c "import assistant.brain" → kein ImportError
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

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Wichtig |
|---|---|---|
| Datei lesen vor dem Fix | **Read** | IMMER erst lesen, dann editieren |
| Muster im Code finden | **Grep** | Alle relevanten Stellen finden |
| Fix implementieren | **Edit** | Direkt in der Datei aendern |
| Aufrufer pruefen nach Fix | **Grep** | Alle Stellen die die geaenderte Funktion nutzen |
| Tests laufen lassen | **Bash** | `cd assistant && python -m pytest tests/ -x -k "tool_call or device"` |

### Einschraenkungen

- **Nur Tool-Calling-Fixes** — keine Persoenlichkeits-Aenderungen, keine Memory-Fixes, keine UI-Aenderungen
- **Einfach > Komplex** — Wenn ein simpler Regex-Pattern reicht, kein ML-basierter Intent-Classifier
- **Tests nicht brechen** — Nach jedem Fix `pytest` ausfuehren
- **Jede Aenderung committen** — `git commit -m "Fix: Beschreibung"`

---

## UEBERGABE-KONTEXT

Formatiere am Ende einen kompakten **Kontext-Block**:

```
## KONTEXT AUS PROMPT 03: Geraetesteuerung / Tool-Calling

### System-Prompt Aenderungen
- SYSTEM_PROMPT_TEMPLATE umstrukturiert: Tool-Regeln in Zeile 1-10
- Dynamische Sektionen konsolidiert
- Geschaetzte Token-Reduktion: ~50-60%

### settings.yaml Aenderungen
- qwen3.5: supports_think_with_tools: false

### brain.py Aenderungen
- _deterministic_tool_call(): +4 Geraetetypen (Licht, Rollladen, Klima, Schalter)
- _select_tools_for_intent(): Intent-basierte Tool-Filterung (45 → 15 Tools)
- _build_tool_call_hint(): Spezifische Retry-Hints mit Tool-Name + Parameter

### Tool-Call-Trefferquote
- Vorher: ~30-50% (geschaetzt)
- Nachher: >90% (Ziel)

### Offene Punkte
- [ ] Persoenlichkeit nach System-Prompt-Kuerzung pruefen
- [ ] Entity-ID-Aufloesung verbessern (Raum → HA-Entity-Mapping)
- [ ] Tool-Call-Logging fuer Monitoring einbauen
```

---

## OUTPUT

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
PROMPT: 03 (Geraetesteuerung / Tool-Calling)
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
