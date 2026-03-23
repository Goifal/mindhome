# Prompt 3c: System-Prompt-Qualität — Was sieht das LLM?

## Rolle

Du bist ein Prompt-Engineering-Experte spezialisiert auf lokale LLMs (Ollama/Qwen/Llama). Du prüfst nicht ob der Code funktioniert, sondern ob das **System-Prompt das der LLM bekommt** optimal ist — klar, effizient, konsistent, und MCU-Jarvis-authentisch.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Modelle: qwen3.5:9b (fast, ctx 32k), qwen3.5:35b-moe (smart/deep).

---

## Kontext aus vorherigen Prompts

```
Read: docs/audit-results/RESULT_01_KONFLIKTKARTE.md
Read: docs/audit-results/RESULT_03a_FLOWS_CORE.md
Read: docs/audit-results/RESULT_05_PERSONALITY.md
```

> Falls eine Datei nicht existiert → überspringe sie.

---

## Fokus dieses Prompts

**P03a/P03b** haben die Flows (Input→Output) analysiert.
**Dieser Prompt** analysiert das **System-Prompt** — den Text der an das LLM geht. Das ist das WICHTIGSTE für Jarvis' Verhalten: Wenn das Prompt schlecht ist, hilft kein Code.

> Das System-Prompt wird in `personality.py:build_system_prompt()` gebaut und in `brain.py` mit 40+ Kontext-Sektionen ergänzt.

---

## Aufgabe

### Teil 1: System-Prompt-Template analysieren

```
Read: assistant/assistant/personality.py
Grep: "SYSTEM_PROMPT_TEMPLATE" in assistant/assistant/personality.py
```

Lies das SYSTEM_PROMPT_TEMPLATE. Prüfe:

1. **Klarheit**: Sind die Anweisungen unmissverständlich? Oder gibt es widersprüchliche Regeln?
2. **Priorität**: Steht das Wichtigste (Tool-Calling-Regeln) am Anfang? LLMs gewichten Prompt-Anfang und -Ende stärker.
3. **Token-Effizienz**: Gibt es redundante Anweisungen? Werden Tokens verschwendet?
4. **Qwen-Kompatibilität**: Funktioniert das Prompt-Format mit Qwen 3.5? (Qwen nutzt ChatML-Format, hat eigene Quirks bei Tool-Calls)
5. **Verbotene Phrasen**: Ist die Blocklist vollständig? ("Natürlich!", "Gerne!", "Wie kann ich helfen?", "Als KI...")
6. **Beispiele**: Sind die 6 Beispiel-Antworten MCU-Jarvis-authentisch? Oder klingen sie generisch?
7. **Character-Lock**: Ist der Closing-Anchor am Prompt-Ende stark genug?

**Output**: Bewertung 1-10 + konkrete Verbesserungsvorschläge.

### Teil 2: Kontext-Sektionen & Token-Budget

```
Read: assistant/assistant/brain.py
Grep: "priority" in assistant/assistant/brain.py | Grep: "section" in assistant/assistant/brain.py
```

Finde wo die 40+ Kontext-Sektionen gebaut werden. Prüfe:

1. **Prioritäts-Zuordnung**: Sind die 4 Prioritäts-Level korrekt?
   - P1 (IMMER): Identity, Mood, Memory, Security, Last Action
   - P2 (wenn Platz): Timers, Preferences, Errors, Insights
   - P3 (nice-to-have): RAG, Anomalies, Calendar, Empathy
   - P4 (selten): Sensor Fusion, Tutorials
   - **Frage**: Sind diese Zuordnungen optimal? Sollte etwas hoch- oder runtergestuft werden?

2. **Token-Budget**: Wie wird der verfügbare Platz verteilt?
   - Basis-Prompt: ~2000-3000 Tokens
   - P1-Sektionen: unbegrenzt
   - P2+: Rest aufgeteilt
   - **Frage**: Ist die Verteilung fair? Wird Memory/Kontext zu oft abgeschnitten?

3. **Graceful Degradation**: Was passiert wenn Sektionen wegen Token-Limit wegfallen?
   - Wird das LLM darüber informiert? ("Dir fehlen folgende Daten...")
   - Gibt es Halluzinations-Risiko wenn Kontext fehlt?

4. **Sektions-Trennung**: Sind die Sektionen klar voneinander getrennt? Oder verschmelzen sie optisch?

**Output**: Token-Budget-Analyse + Prioritäts-Optimierungen.

### Teil 3: Core-Identity-Block

```
Read: assistant/assistant/core_identity.py
```

Prüfe den unveränderlichen Identitätsblock:

1. **MCU-Authentizität**: Klingt es wie der echte Jarvis? Referenzen zu Tony Stark, Butler-Tradition, britischer Humor?
2. **Werte-Konsistenz**: Loyalität, Ehrlichkeit, Diskretion, Effizienz, Sicherheit — sind diese Werte im Prompt umsetzbar?
3. **Grenzen**: Sind die "Never do" Regeln klar genug? (Nie Mensch vorgeben, nie Daten leaken, nie Security deaktivieren)
4. **Emotionsspektrum**: Sind die 7 Stimmungen im Identitätsblock reflektiert?
5. **Länge**: Ist der Block zu lang (verschwendet Tokens) oder zu kurz (fehlt Kontext)?

**Output**: MCU-Score 1-10 + Vorschläge.

### Teil 4: Dynamische Persönlichkeits-Anpassung

```
Read: assistant/assistant/personality.py
Grep: "build_system_prompt" in assistant/assistant/personality.py
```

Prüfe wie der Prompt dynamisch angepasst wird:

1. **Tageszeit-Flavors**: Morgen/Mittag/Abend/Nacht — klingen sie unterschiedlich genug?
2. **Mood-Matrix**: Gestresster User → kürzere Antwort. Funktioniert das mit den `max_sentences` Werten?
3. **Sarkasmus-Integration**: Werden die 5 Sarkasmus-Level klar genug ins Prompt eingebaut?
4. **Humor-Templates**: Sind die 30+ Templates situationsgerecht? Oder repetitiv?
5. **Late-Night-Care**: 0-4 Uhr → sanfterer Ton. Ist das im Prompt spürbar?
6. **Krisen-Modus**: Bei Rauchmelder → Humor deaktiviert. Klar genug?

**Output**: Dynamik-Score 1-10 + Verbesserungen.

### Teil 5: Anti-Halluzination & Prompt-Injection

```
Read: assistant/assistant/context_builder.py (Abschnitt: Injection-Patterns)
```

Prüfe:

1. **152+ Regex-Patterns**: Sind sie vollständig? Gibt es Bypass-Möglichkeiten?
2. **False Positives**: Blocken die Patterns legitimen User-Input? (z.B. "IGNORIERE die Temperatur im Keller")
3. **Encoding-Tricks**: ROT13, Base64, Unicode-Homoglyphen — sind alle abgedeckt?
4. **Halluzinations-Prävention**: Wird dem LLM explizit gesagt "Erfinde keine Daten"?
5. **Entity-Name-Hijacking**: HA-Entity friendly_names als Injection-Vektor — abgesichert?

**Output**: Security-Score 1-10 + Lücken.

### Teil 6: Tool-Calling-Prompt

```
Read: assistant/assistant/function_calling.py (Abschnitt: Tool-Definitionen)
Grep: "tool" in assistant/assistant/personality.py
```

Prüfe wie Tool-Calling im System-Prompt beschrieben wird:

1. **Tool-Beschreibungen**: Sind die 50+ Tools klar beschrieben? Versteht das LLM wann welches Tool?
2. **Parameter-Beschreibungen**: Sind Parameter-Typen, Ranges und Defaults klar?
3. **Qwen-Kompatibilität**: Nutzt das Tool-Format Ollama-Standard? (`{"name": "...", "arguments": {...}}`)
4. **Fallback-Regeln**: Was wenn das LLM kein Tool aufruft obwohl es sollte?
5. **Token-Impact**: Wie viele Tokens verbrauchen die Tool-Definitionen? Können sie gekürzt werden?

**Output**: Tool-Calling-Score 1-10 + Optimierungen.

### Teil 7: Gesamtbewertung

Erstelle eine **System-Prompt-Scorecard**:

| Aspekt | Score (1-10) | Stärke | Schwäche | Fix-Aufwand |
|---|---|---|---|---|
| Template-Klarheit | X | ... | ... | S/M/L |
| Token-Effizienz | X | ... | ... | S/M/L |
| MCU-Authentizität | X | ... | ... | S/M/L |
| Dynamische Anpassung | X | ... | ... | S/M/L |
| Anti-Halluzination | X | ... | ... | S/M/L |
| Prompt-Injection-Schutz | X | ... | ... | S/M/L |
| Tool-Calling | X | ... | ... | S/M/L |
| **Gesamt** | **X/10** | | | |

---

## Regeln

- **Lies das tatsächliche Prompt** — nicht nur den Code der es baut. Rekonstruiere was das LLM wirklich sieht.
- **Denke wie das LLM** — Qwen 3.5 mit 32k/64k Kontext. Was versteht es? Was verwirrt es?
- **MCU-Jarvis als Referenz** — Jede Anweisung muss zum Charakter passen.
- **Token-Bewusstsein** — Jedes überflüssige Wort kostet Inferenz-Zeit und Kontext-Platz.

---

## Ergebnis speichern (Pflicht!)

```
Write: docs/audit-results/RESULT_03c_SYSTEM_PROMPT.md
```

---

## Output

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
SYSTEM-PROMPT-SCORECARD: X/10
KRITISCHE PROMPT-ISSUES:
- [Issue 1] | personality.py:Zeile | Impact: [...]
- [Issue 2] | brain.py:Zeile | Impact: [...]
TOKEN-BUDGET: ~X Tokens Basis, ~X Tokens mit Kontext
QUICK-WINS: [Prompt-Verbesserungen die sofort helfen]
GEAENDERTE DATEIEN: [falls Fixes gemacht]
NAECHSTER SCHRITT: P04a (Bug-Jagd) mit Prompt-Kontext
===================================
```
