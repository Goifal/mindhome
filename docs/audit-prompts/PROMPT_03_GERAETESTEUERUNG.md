# Prompt 3: Geraetesteuerung — Tool-Calling reparieren

## Rolle

Du bist ein Experte fuer LLM-Tool-Calling, Prompt Engineering fuer kleine Modelle (4B–8B Parameter) und Home-Assistant-Integration. Du verstehst wie Qwen 3.5, Llama und Mistral Tool-Calls generieren — und warum sie dabei scheitern.

### Kernproblem

Jarvis steuert Geraete ueber LLM-Tool-Calls. Das LLM (Qwen 3.5, 4B Parameter) generiert aber **unzuverlaessig** Tool-Calls weil:

1. **System-Prompt zu lang**: Die Tool-Calling-Anweisung ("GERAETESTEUERUNG: Geraet steuern = IMMER Tool-Call") steht in Zeile ~275 von `personality.py`, BEGRABEN unter 20+ dynamischen Sektionen
2. **45+ Tools** werden dem LLM bei JEDEM Request uebergeben — ein 4B-Modell wird davon ueberfordert
3. **Thinking-Modus aktiv**: `supports_think_with_tools: true` in `settings.yaml` laesst das Modell "nachdenken" statt Tool-Calls zu generieren
4. **Fallback zu schwach**: `_deterministic_tool_call()` faengt Status-Abfragen ab, aber NICHT Steuerungsbefehle (Licht, Rollladen, Heizung)
5. **Retry-Hint zu vage**: Der Retry-Mechanismus sagt dem LLM nicht WELCHES Tool mit WELCHEN Parametern es nutzen soll

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–2 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Bloecke) automatisch. Du musst nichts einfuegen.
>
> **Wenn dies eine neue Konversation ist**: Fuege hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte, besonders brain.py-Architektur)
> - Kontext-Block aus Prompt 2 (Memory-Analyse, besonders Kontext-Aufbau)
>
> **Ohne diese Kontext-Bloecke** fehlt dir das Verstaendnis wie brain.py die Tool-Calls orchestriert und wie der System-Prompt aufgebaut wird.

---

## Aufgabe

### Qwen 3.5 Spezifische Hinweise

> **Wichtig**: Qwen 3.5 (4B) hat folgende Eigenheiten beim Tool-Calling:
> - **Token-Budget ist knapp** — alles ueber ~2000 Token im System-Prompt reduziert die Tool-Calling-Zuverlaessigkeit dramatisch
> - **Tool-Beschreibungen muessen kurz und praezise sein** — lange Docstrings verwirren das Modell
> - **Thinking-Modus (`<think>...</think>`) konkurriert mit Tool-Calls** — das Modell "denkt" statt zu handeln
> - **Weniger Tools = bessere Trefferquote** — bei 15 Tools ist die Trefferquote ~80%, bei 45+ sinkt sie auf ~30%
> - **Die ersten 10 Zeilen des System-Prompts haben 5x mehr Gewicht** als spaetere Zeilen — Tool-Regeln muessen OBEN stehen
> - **Explizite Beispiele im System-Prompt erhoehen die Trefferquote um ~40%** — "Licht an → set_light(state='on')"

---

### Fix 1: System-Prompt umstrukturieren (personality.py)

**Ziel**: Tool-Calling-Anweisungen in die ersten 10 Zeilen des System-Prompts verschieben.

#### Schritt 1: Aktuellen System-Prompt lesen

```
Read: personality.py — suche SYSTEM_PROMPT_TEMPLATE (circa Zeile 240-290)
```

#### Schritt 2: Alle dynamischen Sektionen identifizieren

```
Grep: pattern="\{.*_section\}" path="assistant/assistant/personality.py" output_mode="content"
```

Erwartete Treffer (zu viele!):
- `{proactive_thinking_section}` — Proaktives Denken
- `{engineering_diagnosis_section}` — Ingenieur-Diagnose
- `{self_awareness_section}` — Selbstbewusstsein
- `{conversation_callback_section}` — Gespraechs-Rueckruf
- `{weather_awareness_section}` — Wetter-Bewusstsein
- `{empathy_section}` — Empathie
- `{self_irony_section}` — Selbstironie
- `{formality_section}` — Foermlichkeit
- `{urgency_section}` — Dringlichkeit

#### Schritt 3: System-Prompt neu strukturieren

**Neue Struktur (5 Bloecke, strikte Reihenfolge):**

```
SYSTEM_PROMPT_TEMPLATE = """
# BLOCK 1: Identitaet (3 Zeilen)
Du bist Jarvis, ein intelligenter Hausassistent. Du sprichst Deutsch.
Dein Zuhause: {home_name}. Bewohner: {residents}.
Aktuell: {current_datetime}.

# BLOCK 2: TOOL-CALLING-REGELN (5 Zeilen, MUSS in den ersten 10 Zeilen stehen!)
WICHTIG — Geraetesteuerung:
- Geraet steuern = IMMER Tool-Call. NIEMALS nur Text-Antwort.
- Licht an/aus/dimmen → set_light(entity_id, state, brightness, color)
- Rollladen/Jalousie → set_cover(entity_id, position, state)
- Heizung/Klima → set_climate(entity_id, temperature, hvac_mode)
- Schalter/Steckdose → set_switch(entity_id, state)
- Mehrere Geraete = mehrere Tool-Calls in EINER Antwort.
- Status abfragen → get_entity_state(entity_id)

# BLOCK 3: Antwortformat (3 Zeilen)
Antworte kurz und praezise. Bestaetigung nach Tool-Call: "Erledigt, Sir." oder aehnlich.
Bei Fehlern: Sage was schief ging, nicht technische Details.
Formatiere KEINE Markdown-Tabellen oder Code-Bloecke in Sprachantworten.

# BLOCK 4: Persoenlichkeit (gekuerzt, max 5 Zeilen)
Stil: Britisch-hoefllich, trockener Humor, Butler-Ton. "Sir" statt "Hey".
{personality_summary}

# BLOCK 5: Dynamischer Kontext (nur relevante Sektionen)
{dynamic_context}
"""
```

#### Schritt 4: Dynamische Sektionen konsolidieren

Die folgenden Sektionen ENTFERNEN oder in `{dynamic_context}` zusammenfassen (max 3 Saetze gesamt):

| Sektion | Aktion | Begruendung |
|---|---|---|
| `{proactive_thinking_section}` | **ENTFERNEN** | Erzeugt Text statt Tool-Calls |
| `{engineering_diagnosis_section}` | **ENTFERNEN** | Irrelevant fuer Geraetesteuerung |
| `{self_awareness_section}` | **ENTFERNEN** | Fuellt Token-Budget ohne Nutzen |
| `{conversation_callback_section}` | **ENTFERNEN** | Kann in Personality-Modul bleiben |
| `{weather_awareness_section}` | In `{dynamic_context}` | 1 Satz: "Wetter: {summary}" |
| `{empathy_section}` | **ENTFERNEN** | Personality-Modul regelt das |
| `{self_irony_section}` | **ENTFERNEN** | Personality-Modul regelt das |
| `{formality_section}` | **ENTFERNEN** | Durch Block 4 abgedeckt |
| `{urgency_section}` | In `{dynamic_context}` | 1 Satz: "Dringlichkeit: {level}" |

**Wichtig**: Die Sektionen werden NICHT geloescht — nur aus dem SYSTEM_PROMPT_TEMPLATE entfernt. Die Logik in `build_system_prompt()` die diese Sektionen generiert bleibt erhalten fuer zukuenftigen Gebrauch. Sie werden nur nicht mehr in den LLM-System-Prompt injiziert.

#### Schritt 5: Verifizieren

```
Read: personality.py — SYSTEM_PROMPT_TEMPLATE pruefen: Stehen Tool-Regeln in Zeile 1–10?
Grep: pattern="GERAETESTEUERUNG|set_light|set_cover|set_climate" path="assistant/assistant/personality.py" output_mode="content"
```

**Erfolgskriterium**: Tool-Calling-Block steht in den ersten 10 Zeilen des Templates. Keine dynamischen Sektionen mehr zwischen Block 1 und Block 3.

---

### Fix 2: Thinking-Modus deaktivieren (settings.yaml)

**Ziel**: Qwen 3.5 soll Tool-Calls generieren statt zu "denken".

#### Schritt 1: Aktuelle Konfiguration lesen

```
Read: settings.yaml — suche "qwen3.5" oder "qwen" Profil
Grep: pattern="supports_think_with_tools|think.*tool" path="assistant/assistant/settings.yaml" output_mode="content"
```

#### Schritt 2: Aendern

```
Edit: settings.yaml
  old_string: "supports_think_with_tools: true"  (im qwen3.5-Profil)
  new_string: "supports_think_with_tools: false"
```

#### Schritt 3: Verifizieren

```
Grep: pattern="supports_think_with_tools" path="assistant/assistant/settings.yaml" output_mode="content"
```

**Erfolgskriterium**: `supports_think_with_tools: false` fuer das qwen3.5-Profil. Pruefen ob andere Profile (z.B. qwen3-30b) davon betroffen sind — groessere Modelle KOENNEN Thinking + Tools.

#### Schritt 4: Code pruefen der diese Einstellung liest

```
Grep: pattern="supports_think_with_tools" path="assistant/assistant/" output_mode="content"
```

Verifiziere dass die Einstellung tatsaechlich ausgewertet wird und den `<think>`-Modus bei Tool-Calls unterdrueckt.

---

### Fix 3: Deterministische Tool-Calls erweitern (brain.py)

**Ziel**: `_deterministic_tool_call()` soll Steuerungsbefehle erkennen und direkt als Tool-Call ausfuehren — OHNE den LLM-Umweg.

#### Schritt 1: Bestehende Implementierung lesen

```
Read: brain.py — suche _deterministic_tool_call (circa Zeile 6900-7000)
```

#### Schritt 2: Steuerungs-Patterns hinzufuegen

Erweitere die Funktion um diese Pattern-Erkennung:

```python
# === LICHT-STEUERUNG ===
# Patterns: "Licht an/aus", "mach Licht an", "Lampe auf 50%", "Licht dimmen"
light_patterns = [
    (r"(?:mach|schalte?|dreh|stell).*(?:licht|lampe|beleuchtung).*(?:an|ein)", {"state": "on"}),
    (r"(?:mach|schalte?|dreh|stell).*(?:licht|lampe|beleuchtung).*(?:aus)", {"state": "off"}),
    (r"(?:licht|lampe|beleuchtung).*(?:an|ein)", {"state": "on"}),
    (r"(?:licht|lampe|beleuchtung).*(?:aus)", {"state": "off"}),
    (r"(?:licht|lampe).*?(\d{1,3})\s*%", lambda m: {"state": "on", "brightness": int(m.group(1))}),
    (r"(?:dimm|dimme).*(?:licht|lampe)", {"state": "on", "brightness": 30}),
]

# === ROLLLADEN-STEUERUNG ===
# Patterns: "Rollladen hoch/runter", "Jalousie auf 50%", "Rollladen oeffnen"
cover_patterns = [
    (r"(?:rollladen|rollo|jalousie|markise).*(?:hoch|auf|oeffne|rauf)", {"state": "open"}),
    (r"(?:rollladen|rollo|jalousie|markise).*(?:runter|zu|schliess|ab)", {"state": "close"}),
    (r"(?:rollladen|rollo|jalousie).*?(\d{1,3})\s*%", lambda m: {"position": int(m.group(1))}),
]

# === KLIMA-STEUERUNG ===
# Patterns: "Heizung auf 22 Grad", "Temperatur auf 20", "Heizung aus"
climate_patterns = [
    (r"(?:heizung|thermostat|temperatur|klima).*?(\d{1,2}(?:[.,]\d)?)\s*(?:grad|°)",
     lambda m: {"temperature": float(m.group(1).replace(",", "."))}),
    (r"(?:heizung|thermostat).*(?:aus|ab)", {"hvac_mode": "off"}),
    (r"(?:heizung|thermostat).*(?:an|ein)", {"hvac_mode": "heat"}),
]

# === SCHALTER/STECKDOSEN ===
# Patterns: "Steckdose an/aus", "Fernseher an/aus"
switch_patterns = [
    (r"(?:steckdose|schalter|ventilator|fernseher|tv).*(?:an|ein)", {"state": "on"}),
    (r"(?:steckdose|schalter|ventilator|fernseher|tv).*(?:aus)", {"state": "off"}),
]
```

#### Schritt 3: Raum-Erkennung hinzufuegen

```python
# Raum aus dem Text extrahieren fuer entity_id-Aufloesung
room_patterns = {
    r"(?:wohnzimmer|wohnraum)": "wohnzimmer",
    r"(?:schlafzimmer|schlafraum)": "schlafzimmer",
    r"(?:kueche|kitchen)": "kueche",
    r"(?:bad|badezimmer|bathroom)": "badezimmer",
    r"(?:flur|gang|eingang)": "flur",
    r"(?:buero|arbeitszimmer|office)": "buero",
    r"(?:kinderzimmer)": "kinderzimmer",
    r"(?:keller|basement)": "keller",
    r"(?:garage)": "garage",
    r"(?:garten|terrasse|balkon)": "garten",
}
```

#### Schritt 4: Multi-Command-Erkennung

Wenn der User-Text "und" oder Komma enthaelt, MEHRERE Tool-Calls generieren:

```python
# "Licht aus und Rollladen runter" → 2 Tool-Calls
if " und " in user_text or ", " in user_text:
    parts = re.split(r"\s+und\s+|,\s*", user_text)
    tool_calls = []
    for part in parts:
        tc = self._match_single_command(part.strip())
        if tc:
            tool_calls.append(tc)
    if tool_calls:
        return tool_calls
```

#### Schritt 5: Verifizieren

```
Read: brain.py — _deterministic_tool_call pruefen: Sind alle 4 Geraetetypen abgedeckt?
Grep: pattern="light_patterns|cover_patterns|climate_patterns|switch_patterns" path="assistant/assistant/brain.py" output_mode="content"
```

**Erfolgskriterium**: `_deterministic_tool_call()` erkennt Licht-, Rollladen-, Klima- und Schalter-Befehle und gibt strukturierte Tool-Calls zurueck.

---

### Fix 4: Dynamische Tool-Selektion (brain.py)

**Ziel**: Vor dem LLM-Call nur die relevanten Tools senden, nicht alle 45+.

#### Schritt 1: LLM-Aufruf-Stelle finden

```
Read: brain.py — suche get_assistant_tools oder tools= im LLM-Aufruf (circa Zeile 3300-3350)
Grep: pattern="get_assistant_tools|tools\s*=" path="assistant/assistant/brain.py" output_mode="content"
```

#### Schritt 2: Intent-basierte Tool-Filterung einbauen

Fuege VOR dem LLM-Aufruf eine Intent-Erkennung ein:

```python
def _select_tools_for_intent(self, user_text: str) -> list:
    """Waehlt nur relevante Tools basierend auf dem erkannten Intent.

    Reduziert die Tool-Liste von 45+ auf max 15, um kleine Modelle
    nicht zu ueberfordern.
    """
    text_lower = user_text.lower()

    # Intent: Geraet steuern
    CONTROL_KEYWORDS = [
        "mach", "schalte", "stell", "dreh", "dimm", "oeffne", "schliess",
        "an", "aus", "hoch", "runter", "auf", "zu",
        "licht", "lampe", "rollladen", "rollo", "jalousie", "heizung",
        "thermostat", "temperatur", "steckdose", "schalter",
    ]

    # Intent: Geraet abfragen
    QUERY_KEYWORDS = [
        "wie ist", "was ist", "status", "temperatur", "wie warm",
        "ist das", "sind die", "offen", "geschlossen", "an oder aus",
    ]

    # Intent: Konversation (alles andere)
    is_control = any(kw in text_lower for kw in CONTROL_KEYWORDS)
    is_query = any(kw in text_lower for kw in QUERY_KEYWORDS)

    if is_control and not is_query:
        # Nur Steuerungs-Tools (15 Stueck max)
        return self._get_control_tools()
    elif is_query and not is_control:
        # Nur Abfrage-Tools
        return self._get_query_tools()
    else:
        # Alle Tools (Fallback)
        return get_assistant_tools()


def _get_control_tools(self) -> list:
    """Gibt nur die 15 wichtigsten Steuerungs-Tools zurueck."""
    CONTROL_TOOL_NAMES = [
        "set_light", "set_cover", "set_climate", "set_switch",
        "set_media_player", "set_fan", "set_lock", "set_alarm",
        "get_entity_state", "call_ha_service", "run_scene",
        "run_script", "run_automation", "set_input_boolean",
        "set_input_number",
    ]
    all_tools = get_assistant_tools()
    return [t for t in all_tools if t.get("function", {}).get("name") in CONTROL_TOOL_NAMES]


def _get_query_tools(self) -> list:
    """Gibt nur Abfrage-Tools zurueck."""
    QUERY_TOOL_NAMES = [
        "get_entity_state", "get_entities", "get_history",
        "get_weather", "get_calendar", "get_shopping_list",
        "search_entities", "get_area_entities",
    ]
    all_tools = get_assistant_tools()
    return [t for t in all_tools if t.get("function", {}).get("name") in QUERY_TOOL_NAMES]
```

#### Schritt 3: Im LLM-Aufruf die gefilterten Tools nutzen

```python
# VORHER (brain.py ~Zeile 3315):
tools = get_assistant_tools()

# NACHHER:
tools = self._select_tools_for_intent(user_text)
logger.debug(f"Tool-Selektion: {len(tools)} Tools fuer Intent")
```

#### Schritt 4: Verifizieren

```
Grep: pattern="_select_tools_for_intent|_get_control_tools|_get_query_tools" path="assistant/assistant/brain.py" output_mode="content"
```

**Erfolgskriterium**: Bei "Mach das Licht an" werden nur ~15 Tools ans LLM gesendet, nicht 45+.

---

### Fix 5: Retry-Hint verbessern (brain.py)

**Ziel**: Wenn der erste LLM-Aufruf keinen Tool-Call generiert, den Retry-Hint mit konkreten Tool-Namen und Parametern anreichern.

#### Schritt 1: Aktuellen Retry-Mechanismus lesen

```
Read: brain.py — suche den Retry-Mechanismus (circa Zeile 3400-3440)
Grep: pattern="retry|tool_call.*hint|no.*tool" path="assistant/assistant/brain.py" output_mode="content"
```

#### Schritt 2: Spezifischen Retry-Hint generieren

```python
def _build_tool_call_hint(self, user_text: str) -> str:
    """Generiert einen spezifischen Retry-Hint mit Tool-Name und Parametern.

    Statt: "Bitte nutze ein Tool fuer diese Anfrage."
    Jetzt:  "Nutze set_light(entity_id='light.wohnzimmer', state='on')
             fuer diese Anfrage."
    """
    text_lower = user_text.lower()

    hints = []

    # Licht
    if any(w in text_lower for w in ["licht", "lampe", "beleuchtung"]):
        state = "on" if any(w in text_lower for w in ["an", "ein"]) else "off"
        hints.append(
            f"Nutze set_light mit state='{state}'. "
            f"Beispiel: set_light(entity_id='light.wohnzimmer', state='{state}')"
        )

    # Rollladen
    if any(w in text_lower for w in ["rollladen", "rollo", "jalousie"]):
        if any(w in text_lower for w in ["hoch", "auf", "oeffne"]):
            hints.append(
                "Nutze set_cover mit state='open'. "
                "Beispiel: set_cover(entity_id='cover.wohnzimmer', state='open')"
            )
        elif any(w in text_lower for w in ["runter", "zu", "schliess"]):
            hints.append(
                "Nutze set_cover mit state='close'. "
                "Beispiel: set_cover(entity_id='cover.wohnzimmer', state='close')"
            )
        # Prozentwert
        import re
        m = re.search(r"(\d{1,3})\s*%", text_lower)
        if m:
            hints.append(
                f"Nutze set_cover mit position={m.group(1)}. "
                f"Beispiel: set_cover(entity_id='cover.wohnzimmer', position={m.group(1)})"
            )

    # Heizung
    if any(w in text_lower for w in ["heizung", "thermostat", "temperatur"]):
        import re
        m = re.search(r"(\d{1,2}(?:[.,]\d)?)\s*(?:grad|°)", text_lower)
        if m:
            temp = m.group(1).replace(",", ".")
            hints.append(
                f"Nutze set_climate mit temperature={temp}. "
                f"Beispiel: set_climate(entity_id='climate.wohnzimmer', temperature={temp})"
            )

    # Schalter
    if any(w in text_lower for w in ["steckdose", "schalter", "ventilator"]):
        state = "on" if any(w in text_lower for w in ["an", "ein"]) else "off"
        hints.append(
            f"Nutze set_switch mit state='{state}'. "
            f"Beispiel: set_switch(entity_id='switch.steckdose', state='{state}')"
        )

    if hints:
        return (
            "WICHTIG: Du MUSST einen Tool-Call generieren! "
            "Antworte NICHT mit Text, sondern rufe das passende Tool auf.\n"
            + "\n".join(hints)
        )

    # Generischer Fallback
    return (
        "WICHTIG: Diese Anfrage erfordert einen Tool-Call. "
        "Antworte NICHT mit Text. Nutze eines der verfuegbaren Tools."
    )
```

#### Schritt 3: Retry-Hint im Retry-Mechanismus einsetzen

```python
# VORHER (brain.py ~Zeile 3420):
retry_hint = "Bitte nutze ein Tool fuer diese Anfrage."

# NACHHER:
retry_hint = self._build_tool_call_hint(user_text)
```

#### Schritt 4: Verifizieren

```
Grep: pattern="_build_tool_call_hint|retry_hint" path="assistant/assistant/brain.py" output_mode="content"
```

**Erfolgskriterium**: Der Retry-Hint enthaelt den konkreten Tool-Namen und Parameter-Beispiele.

---

## Test-Dialoge

Nach allen 5 Fixes muessen diese Dialoge funktionieren:

### Test 1: Einfache Lichtsteuerung

```
User: "Mach das Licht an"
Erwartet: set_light(entity_id=<erkannt oder default>, state="on")
Jarvis: "Erledigt, Sir." (oder aehnliche kurze Bestaetigung)
NICHT: "Ich wuerde gerne das Licht fuer Sie einschalten..." (Text statt Tool-Call)
```

### Test 2: Rollladen mit Prozentwert

```
User: "Rollladen auf 50%"
Erwartet: set_cover(entity_id=<erkannt>, position=50)
Jarvis: "Rollladen steht auf 50%, Sir."
NICHT: "Sie moechten den Rollladen auf 50% stellen. Das mache ich fuer Sie."
```

### Test 3: Heizung mit Temperatur

```
User: "Heizung auf 22 Grad"
Erwartet: set_climate(entity_id=<erkannt>, temperature=22)
Jarvis: "Heizung auf 22 Grad eingestellt."
NICHT: "Die Temperatur wird auf 22 Grad angepasst."
```

### Test 4: Multi-Command

```
User: "Licht aus und Rollladen runter"
Erwartet: ZWEI Tool-Calls:
  1. set_light(entity_id=<erkannt>, state="off")
  2. set_cover(entity_id=<erkannt>, state="close")
Jarvis: "Licht ist aus und Rollladen fahren runter, Sir."
NICHT: Nur ein Tool-Call oder gar keiner
```

### Test 5: Raum-spezifisch

```
User: "Mach das Licht im Schlafzimmer aus"
Erwartet: set_light(entity_id="light.schlafzimmer" oder aehnlich, state="off")
Jarvis: "Licht im Schlafzimmer ist aus."
```

### Test 6: Edge Case — Frage vs. Befehl

```
User: "Ist das Licht an?"
Erwartet: get_entity_state(entity_id=<erkannt>) — KEIN set_light!
Jarvis: "Das Licht im Wohnzimmer ist eingeschaltet, Sir."
```

---

## Reihenfolge der Fixes

**WICHTIG**: Die Fixes in dieser Reihenfolge implementieren:

1. **Fix 2 zuerst** (settings.yaml) — einfachste Aenderung, sofortige Wirkung
2. **Fix 1** (System-Prompt) — groesste Wirkung auf Tool-Call-Zuverlaessigkeit
3. **Fix 3** (deterministic fallback) — faengt Faelle ab die das LLM trotzdem verpasst
4. **Fix 4** (Tool-Selektion) — reduziert Cognitive Load des LLM
5. **Fix 5** (Retry-Hint) — verbessert den Retry-Fall

---

## Output-Format

### 1. Fix-Log

Fuer jeden implementierten Fix:

```
### Fix #X: Kurzbeschreibung
- **Datei**: path/to/file.py:zeile
- **Vorher**: Was stand da / wie war das Verhalten
- **Nachher**: Was steht jetzt da / wie ist das Verhalten
- **Verifiziert**: Read + Grep Ergebnisse
- **Risiko**: Was koennte durch diesen Fix kaputt gehen
```

### 2. Tool-Call-Zuverlaessigkeits-Matrix

```
| Test-Dialog | Vor Fix | Nach Fix | Methode |
|---|---|---|---|
| "Mach das Licht an" | ❌ Text-Antwort | ✅ set_light() | LLM / Deterministic |
| "Rollladen auf 50%" | ❌ Text-Antwort | ✅ set_cover(50) | LLM / Deterministic |
| "Heizung auf 22 Grad" | ❌ Text-Antwort | ✅ set_climate(22) | LLM / Deterministic |
| "Licht aus und Rollo runter" | ❌ Nur Text | ✅ 2 Tool-Calls | LLM / Deterministic |
| "Ist das Licht an?" | ✅ get_state | ✅ get_state | Deterministic |
```

### 3. System-Prompt Token-Vergleich

```
| Metrik | Vorher | Nachher |
|---|---|---|
| Template-Zeilen | ~44 + Sektionen | ~25 + dynamic_context |
| Geschaetzte Tokens (expandiert) | ~800-1200 | ~300-500 |
| Tool-Regeln Position | Zeile ~275 | Zeile 4-11 |
| Dynamische Sektionen | 9+ | 2 (Wetter, Dringlichkeit) |
```

---

## Erfolgsmetriken

| Metrik | Zielwert | Messmethode |
|---|---|---|
| Tool-Call-Trefferquote (Steuerung) | >90% | 10 Steuerungsbefehle testen |
| System-Prompt Laenge | <500 Tokens | Token-Zaehler nach Expansion |
| Tool-Regeln Position | Zeile 1-10 | Read personality.py |
| Anzahl Tools bei Steuerungs-Intent | <=15 | Log-Ausgabe pruefen |
| Deterministic Fallback Coverage | 4 Geraetetypen | Grep nach Patterns |
| Retry-Hint Spezifitaet | Tool-Name + Parameter | Grep nach _build_tool_call_hint |
| Multi-Command Erkennung | "und"-Split funktioniert | Test-Dialog 4 |

---

## Rollback-Strategie

Falls die Fixes unerwuenschte Nebenwirkungen haben:

### Sofort-Rollback (Git)

```bash
# Vor den Fixes: Checkpoint setzen
git tag checkpoint-pre-toolcalling

# Nach den Fixes: Wenn etwas kaputt ist
git diff checkpoint-pre-toolcalling  # Was hat sich geaendert?
git checkout checkpoint-pre-toolcalling -- assistant/assistant/personality.py  # Einzelne Datei zuruecksetzen
git checkout checkpoint-pre-toolcalling -- assistant/assistant/settings.yaml
git checkout checkpoint-pre-toolcalling -- assistant/assistant/brain.py
```

### Selektives Rollback

| Fix | Rollback-Aufwand | Risiko |
|---|---|---|
| Fix 1 (System-Prompt) | Mittel — SYSTEM_PROMPT_TEMPLATE wiederherstellen | Gering — aendert nur Prompt-Text |
| Fix 2 (settings.yaml) | Trivial — eine Zeile zurueck | Kein Risiko |
| Fix 3 (deterministic) | Niedrig — neuen Code entfernen | Kein Risiko — Fallback kann nicht verschlechtern |
| Fix 4 (Tool-Selektion) | Niedrig — zurueck zu `get_assistant_tools()` | Mittleres Risiko — Intent-Erkennung koennte false positives haben |
| Fix 5 (Retry-Hint) | Trivial — alten Hint wiederherstellen | Kein Risiko |

### Bekannte Risiken

1. **Fix 1**: Kuerzerer System-Prompt koennte die Persoenlichkeit verwassern — nach dem Fix pruefen ob Jarvis noch "wie Jarvis" klingt
2. **Fix 3**: Deterministic Tool-Calls umgehen das LLM — wenn die Pattern-Erkennung falsch matched, wird das falsche Geraet gesteuert. IMMER mit Raum-Validierung gegen HA-Entity-Liste pruefen
3. **Fix 4**: False Positives bei der Intent-Erkennung koennten relevante Tools ausfiltern. Logging einbauen und im Zweifel ALLE Tools senden (Fallback)

---

## Regeln

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

## Uebergabe-Kontext

Formatiere am Ende einen kompakten **Kontext-Block**:

```
## KONTEXT AUS PROMPT 3: Geraetesteuerung / Tool-Calling

### System-Prompt Aenderungen
- SYSTEM_PROMPT_TEMPLATE umstrukturiert: Tool-Regeln in Zeile 1-10
- Dynamische Sektionen konsolidiert: 9 → 2
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

### Offene Punkte fuer Prompt 4+
- [ ] Persoenlichkeit nach System-Prompt-Kuerzung pruefen (Prompt 5)
- [ ] Entity-ID-Aufloesung verbessern (Raum → HA-Entity-Mapping)
- [ ] Tool-Call-Logging fuer Monitoring einbauen
- [ ] Groessere Modelle (Qwen 3 30B) testen — evtl. andere Optimierungen noetig
```

---

## OUTPUT

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
