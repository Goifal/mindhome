# Prompt 5b: Intelligenz-Qualitätsaudit — Denkt Jarvis richtig?

## Rolle

Du bist ein KI-Systemarchitekt und Kognitionswissenschaftler spezialisiert auf Agenten-Qualität. Du prüfst nicht ob der Code **funktioniert** (das machen P04a–P04c), sondern ob er das **Richtige tut** — ob Jarvis intelligent, lernfähig, vorausschauend und konsistent handelt.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Modelle: qwen3.5:9b (fast, ctx 32k), qwen3.5:35b-moe (smart/deep).

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Prompts:

```
Read: docs/audit-results/RESULT_01_KONFLIKTKARTE.md
Read: docs/audit-results/RESULT_02_MEMORY.md
Read: docs/audit-results/RESULT_05_PERSONALITY.md
Read: docs/audit-results/RESULT_04a_BUGS_CORE.md
```

> Falls eine Datei nicht existiert → überspringe sie.

---

## Fokus dieses Prompts

**P04a–P04c** finden Code-Bugs (Crashes, Race Conditions, Security).
**P05** prüft Persönlichkeits-Konfiguration und MCU-Authentizität.
**Dieser Prompt** prüft die **kognitive Qualität** — ob Jarvis' Intelligenz-Systeme korrekte Entscheidungen treffen.

> **Zentrale Frage**: Wenn der Code fehlerfrei läuft — macht Jarvis dann trotzdem das Richtige?

---

## Aufgabe

### Teil 1: LLM-Routing-Qualität

**Ziel**: Prüfe ob `model_router.py` das richtige LLM-Modell für die richtige Aufgabe wählt.

```
Read: assistant/assistant/model_router.py
```

**Prüfe**:

1. **Wortanzahl-Schwelle**: Der Router nutzt 15+ Wörter als Trigger für Deep-Modell. Ist das sinnvoll für Deutsche Sätze (Komposita, lange Wörter)?
2. **Keyword-Matching**: Werden Keywords wie "an"/"aus" korrekt als Wortgrenzen behandelt? Oder matcht "Anleitung" als "an"?
3. **Temperatur-Routing**: Sind die 6 Task-Typen mit korrekten Temperaturen versehen? Werden alle tatsächlich genutzt?
4. **Latenz-Degradation**: Verwendet der Router Median oder Durchschnitt? Werden Ausreißer gefiltert?
5. **Tier-Recovery**: Wie oft wird geprüft ob ein degradierter Tier wieder verfügbar ist?

**Output**: Tabelle mit Schwächen + konkreten Verbesserungsvorschlägen.

### Teil 2: Kausales Denken & Antizipation

**Ziel**: Prüfe ob Jarvis Zusammenhänge korrekt erkennt und vorhersagt.

```
Read: assistant/assistant/anticipation.py (Abschnitte: Confidence-Berechnung, Pattern-Typen, Schwellwerte)
Read: assistant/assistant/insight_engine.py (Abschnitte: Cross-Reference-Regeln, Trigger-Logik)
Read: assistant/assistant/learning_observer.py (Abschnitte: Wiederholungserkennung, Schwellwerte)
```

**Prüfe**:

1. **Konfidenz-Formel** in `anticipation.py`:
   - `weeks_in_data = max(1, len(entries) / 50)` — Ist das korrekt? Was passiert bei 5 Einträgen in 1 Woche?
   - Recency-Gewichtung: Überschreiben 3 neue Aktionen 7 alte Gewohnheiten?
   - Werden saisonale Muster korrekt erkannt (Heizung nur im Winter)?

2. **Pattern-Typen**: Sind die 4 Typen (Zeit, Sequenz, Kontext, Kausal) ausreichend? Fehlt etwas (z.B. Wochentag-abhängig, Anwesenheits-abhängig)?

3. **Insight-Engine Regeln**: Sind die Cross-Reference-Regeln vollständig? (Fenster+Regen, Frost+Heizung, Abwesenheit+Geräte, ...). Was fehlt?

4. **Learning Observer**: Ist der 3-Wiederholungen-Cliff sinnvoll? Oder sollte es eine graduelle Konfidenz-Kurve geben?

5. **False-Positive-Rate**: Wie wahrscheinlich ist es, dass Jarvis eine falsche Korrelation erkennt? (Beispiel: "User macht Licht an um 22:30 → 3 Tage hintereinander → muss Gewohnheit sein" — oder 3 zufällig kalte Abende?)

**Output**: Tabelle mit Schwächen + Qualitätsverbesserungen.

### Teil 3: Lernfähigkeit & Feedback-Loops

**Ziel**: Prüfe ob Jarvis aus Fehlern lernt und sich über Zeit verbessert.

```
Read: assistant/assistant/correction_memory.py
Read: assistant/assistant/outcome_tracker.py
Read: assistant/assistant/feedback.py
Read: assistant/assistant/response_quality.py
Read: assistant/assistant/self_optimization.py (erste 100 Zeilen)
Read: assistant/assistant/adaptive_thresholds.py
```

**Prüfe**:

1. **Correction Memory**:
   - Werden LLM-generierte Korrekturregeln validiert bevor sie aktiv werden?
   - Kann ein User durch gezielte Korrekturen das System manipulieren (Adversarial Feedback)?
   - Ist Substring-Matching ("hell", "dunkel") robust genug oder gibt es False Positives?

2. **Outcome Tracker**:
   - Ist 180s Beobachtungszeit für alle Domains sinnvoll? (Licht: 1s, Klima: 10min)
   - Wird zwischen "User hat rückgängig gemacht" und "automatische Änderung" unterschieden?
   - Können 10 schnelle positive Feedbacks den Score vergiften (Data Poisoning)?

3. **Feedback-System**:
   - Auto-Timeout nach 120s → "ignored" (-0.05). Ist das fair? Was wenn User beschäftigt war?
   - Kann der Score unter 0.15 sinken und nie wieder steigen (Death Spiral)?
   - Gibt es einen Reset-Mechanismus für zu niedrige Scores?

4. **Response Quality**:
   - EMA mit α=0.1 — bedeutet 7-10 Interaktionen bis eine Änderung spürbar ist. Zu langsam? Zu schnell?
   - "Follow-up innerhalb 60s = schlecht" — was wenn User eine legitime Anschlussfrage hat?
   - Werden gute Antworten als Few-Shot-Beispiele gespeichert? Wie alt dürfen sie sein?

5. **Self-Optimization**:
   - Welche Parameter sind optimierbar? Welche sind immutable? Ist die Grenze sinnvoll?
   - Werden Vorschläge validiert bevor sie dem User gezeigt werden?
   - Max 3 Vorschläge pro Zyklus — ist das zu wenig/viel?

**Output**: Tabelle mit Qualitäts-Score pro Subsystem (1-5) und Verbesserungsvorschlägen.

### Teil 4: Proaktivitäts-Qualität

**Ziel**: Prüfe ob Jarvis zur richtigen Zeit die richtigen Dinge proaktiv sagt.

```
Read: assistant/assistant/proactive.py (Abschnitte: Salience-Scoring, Urgency-Level, Quiet-Hours)
Read: assistant/assistant/spontaneous_observer.py
Read: assistant/assistant/notification_dedup.py
```

**Prüfe**:

1. **Salience-Scoring**: Ist die Formel `base × time × fatigue × dismiss × activity` sinnvoll?
   - Können mehrere Faktoren zusammen ALLES unterdrücken (Cascade Suppression)?
   - Beispiel: fatigue=0.3 × dismiss=0.6 × activity=0.4 = 0.072 → User hört stundenlang nichts

2. **Notification-Fatigue**: >10 Meldungen/Stunde → Salience 30%. Ist 10 die richtige Grenze?

3. **Spontaneous Observer**: Max 5 Beobachtungen/Tag. Verteilt auf Slots (Morgen 2, Tag 3, Abend 1). Passt das?

4. **Quiet Hours**: 22:00-07:00 → LOW/MEDIUM halbiert. Ist die Grenze hart oder weich? Was wenn User Nachtschicht arbeitet?

5. **Deduplication**: Cosine-Similarity 0.85. Zu hoch (lässt leicht variierte Duplikate durch)? Zu niedrig (blockt ähnliche aber verschiedene Meldungen)?

**Output**: Szenarien-Tabelle: "Was passiert wenn..." mit erwartetem vs. tatsächlichem Verhalten.

### Teil 5: Intent-Erkennung & Kontext-Qualität

**Ziel**: Prüfe ob Jarvis versteht was der User meint und dem LLM den richtigen Kontext gibt.

```
Read: assistant/assistant/pre_classifier.py (Abschnitte: Implicit Commands, Device Keywords, Status Queries)
Read: assistant/assistant/context_builder.py (Abschnitte: State-Sammlung, Prompt-Injection-Schutz)
Read: assistant/assistant/llm_enhancer.py
Read: assistant/assistant/situation_model.py
```

**Prüfe**:

1. **Implicit Commands**: "Mir ist kalt" → Heizung hoch. Aber:
   - "Mir ist Kalt lieber als Heiß" → False Positive? (Syntaktische Unterscheidung)
   - "Die Waschmaschine ist kaputt" → Device Command? (False Positive auf "Maschine")
   - "Es ist dunkel" → Status-Query oder Licht-Befehl? (Ambiguität)

2. **Context Builder**: Welche Informationen bekommt das LLM?
   - HA-State, Wetter, Kalender, Energie — alles? Nur relevantes?
   - Wird der Kontext zu groß? (60KB settings.yaml + State + Memory = Token-Explosion?)
   - Prompt-Injection-Schutz: 152+ Regex-Patterns — gibt es False Positives die legitimen User-Input blocken?

3. **LLM Enhancer**: Implicit-Intent-Erkennung mit Konfidenz ≥0.65.
   - Gibt es einen Feedback-Mechanismus wenn die Erkennung falsch war?
   - Wie wird "Mir ist kalt" von "Stell die Heizung auf 22°C" unterschieden? (Implicit vs. Explicit)

4. **Situation Model**: "Seit wir zuletzt gesprochen haben..." Kontext.
   - Max 5 Änderungen pro Report — werden die wichtigsten gewählt oder die neuesten?
   - 24h TTL — was wenn User 3 Tage nicht spricht?

**Output**: False-Positive/Negative-Analyse mit konkreten Beispielen.

### Teil 6: Persönlichkeits-Konsistenz

**Ziel**: Prüfe ob Jarvis über Konversationen hinweg wie die gleiche Person klingt.

```
Read: assistant/assistant/personality.py (Abschnitte: Sarcasm-Level, Formality, Humor-Templates)
Read: assistant/assistant/inner_state.py
Read: assistant/assistant/core_identity.py
Read: assistant/assistant/brain_humanizers.py
```

**Prüfe**:

1. **Sarkasmus-Konsistenz**: Schwankt der Sarkasmus-Level innerhalb einer Konversation? (Sollte er nicht)
2. **Formalitäts-Sprünge**: Wechselt Jarvis von "butler" zu "freund" ohne Grund?
3. **Emotions-Authentizität**: Triggern die 7 Stimmungen (inner_state.py) authentisch? Oder wirken sie künstlich?
4. **Core-Identity-Verletzungen**: Gibt es Szenarien wo Jarvis seine eigenen Werte bricht? (z.B. moralisieren, Wissen erfinden, Privatsphäre verletzen)
5. **Humor-Qualität**: Sind die 30+ Humor-Templates witzig und situationsgerecht? Oder generisch?
6. **Anti-Bot-Features** (brain_humanizers.py): Variiert Jarvis seine Antwortstruktur genug? Oder klingen alle Antworten gleich?

**Output**: MCU-Jarvis-Score (1-10) für jeden Aspekt mit Beispielen.

### Teil 7: Multi-User-Fairness

**Ziel**: Prüfe ob Jarvis alle Bewohner fair behandelt.

```
Read: assistant/assistant/family_manager.py
Read: assistant/assistant/person_preferences.py
Read: assistant/assistant/conflict_resolver.py (Abschnitte: Mediation, Trust-Level)
```

**Prüfe**:

1. **Trust-Level-Fairness**: Verliert ein Gast IMMER gegen ein Familienmitglied? Auch wenn der Gast zuerst gefragt hat?
2. **Konfidenz-Separation**: Werden Lernmuster pro Person getrennt? Oder verschmutzen sich Profile?
3. **Konflikt-Mediation**: Ist die 300s Konflikt-Fenster zu breit? (Person A stellt Heizung ein → Person A geht → Person B kommt 4min später → Konflikt?)
4. **Sprachstil pro Person**: Bekommt jeder den gleichen Sarkasmus? Oder wird personalisiert?

**Output**: Fairness-Assessment mit Schwachstellen.

### Teil 8: Gesamtbewertung & Verbesserungsplan

Erstelle eine **Qualitäts-Scorecard**:

| System | Qualität (1-5) | Wichtigste Schwäche | Verbesserung | Aufwand |
|---|---|---|---|---|
| LLM-Routing | X/5 | ... | ... | S/M/L |
| Kausales Denken | X/5 | ... | ... | S/M/L |
| Lernfähigkeit | X/5 | ... | ... | S/M/L |
| Proaktivität | X/5 | ... | ... | S/M/L |
| Intent-Erkennung | X/5 | ... | ... | S/M/L |
| Persönlichkeit | X/5 | ... | ... | S/M/L |
| Multi-User | X/5 | ... | ... | S/M/L |
| **Gesamt** | **X/5** | | | |

Und einen priorisierten **Verbesserungsplan**:
1. Quick Wins (Aufwand S, Impact hoch)
2. Mittlere Verbesserungen (Aufwand M)
3. Größere Umbaumaßnahmen (Aufwand L, für späteren Durchlauf)

---

## Output-Format

Für jeden Teil:

```
=== TEIL X: [Name] ===
Geprüfte Module: [Liste mit Datei:Zeile]
Qualitäts-Score: X/5
Schwächen:
- [Schwäche 1] | Datei:Zeile | Impact: [beschreibung]
- [Schwäche 2] | Datei:Zeile | Impact: [beschreibung]
Verbesserungen:
- [Verbesserung 1] | Aufwand: S/M/L | Priorität: 🔴/🟠/🟡
========================
```

---

## Regeln

- **Lies den Code, nicht nur die Doku** — Funktionsnamen und Kommentare können lügen. Prüfe die tatsächliche Implementierung.
- **Denke in Szenarien** — "Was passiert wenn ein neuer User am ersten Tag 50 Aktionen macht?" "Was wenn User 2 Wochen im Urlaub war?"
- **Qualität ≠ Bug-Freiheit** — Code kann fehlerfrei laufen und trotzdem schlechte Entscheidungen treffen.
- **Vergleiche mit MCU-Jarvis** — Würde der echte Jarvis das so machen? Würde er so reagieren?
- **Konkrete Beispiele** — Nicht "die Konfidenz könnte falsch sein" sondern "bei 5 Aktionen in Woche 1 ist die Konfidenz 5.0, gekappt auf 1.0 — das ist zu hoch".
- **Verbesserungen müssen umsetzbar sein** — Nicht "verwende Deep Learning" sondern "ändere Zeile 239: `weeks = max(1, (max_ts - min_ts).days / 7)`".

### Fortschritts-Tracking (Pflicht!)

Dokumentiere nach JEDEM Teil:

```
=== CHECKPOINT Teil X/8 ===
Geprüfte Module: [Anzahl]
Qualitäts-Issues gefunden: [Anzahl]
Verbleibend: [Liste]
================================
```

---

## Ergebnis speichern (Pflicht!)

> **Speichere deinen gesamten Output** in:
> ```
> Write: docs/audit-results/RESULT_05b_INTELLIGENZ_QUALITAET.md
> ```

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
QUALITAETS-SCORECARD:
- LLM-Routing: X/5 — [Hauptproblem]
- Kausales Denken: X/5 — [Hauptproblem]
- Lernfähigkeit: X/5 — [Hauptproblem]
- Proaktivität: X/5 — [Hauptproblem]
- Intent-Erkennung: X/5 — [Hauptproblem]
- Persönlichkeit: X/5 — [Hauptproblem]
- Multi-User: X/5 — [Hauptproblem]
QUICK WINS: [Liste der einfachen Verbesserungen mit Datei:Zeile]
ARCHITEKTUR-ISSUES: [Größere Probleme die Umbau brauchen]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste]
NAECHSTER SCHRITT: P06a (Stabilisierung) mit Qualitäts-Fixes priorisiert
===================================
```
