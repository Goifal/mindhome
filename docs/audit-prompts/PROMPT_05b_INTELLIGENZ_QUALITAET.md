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

### ⚠️ KONTEXT-WARNUNG: Dieses Prompt hat 14 Teile

Dieses Prompt ist LANG. Um Kontext-Erschöpfung zu vermeiden:
- **Arbeite Teil für Teil** — schließe jeden Teil ab bevor du den nächsten beginnst
- **Speichere Zwischen-Ergebnisse** nach jedem Teil im Output-Format (=== TEIL X ===)
- **Lies Code sparsam** — nur die relevanten Stellen, nicht ganze Dateien
- **Wenn der Kontext knapp wird**: Teile 12-14 (Anti-Halluzination, Persönlicher Assistent, Gesamtbewertung) können als separater Durchlauf gemacht werden

### ⚠️ Hinweis zu Read-Instruktionen

Dieses Prompt verwendet `Read: datei.py (Abschnitte: X, Y)` als Kurzschreibweise. Das bedeutet:
1. **Erst Grep** um die genannten Abschnitte/Funktionen zu finden: `Grep: "X\|Y" in datei.py`
2. **Dann Read mit offset/limit** basierend auf den Grep-Ergebnissen: `Read: datei.py offset=[Zeile] limit=150`
3. **NIEMALS** große Dateien (>100KB) komplett lesen! Siehe P00 für die Liste großer Dateien.

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
3. **Sampling-Parameter** (temperature, top_p, top_k):
   - Sind die 6 Task-Typen mit korrekten Temperaturen versehen? Werden alle tatsächlich genutzt?
   - **top_p** (Nucleus Sampling): Wird es gesetzt? Welcher Wert? (Zu hoch = halluziniert, zu niedrig = repetitiv)
   - **top_k**: Wird es gesetzt? Interagiert es sinnvoll mit top_p?
   - **Pro Modell-Tier**: Haben Fast/Smart/Deep UNTERSCHIEDLICHE Sampling-Werte? (Sollten sie — Fast braucht konservativere Werte)
   - **Persönlichkeits-Impact**: Niedrige Temperature = robotisch klingender Jarvis. Hohe Temperature = inkonsistenter Charakter. Wo ist der Sweet Spot für MCU-Jarvis?
   - **Prüfe in settings.yaml**: `Grep: "temperature\|top_p\|top_k" in assistant/config/settings.yaml`
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

5. **Few-Shot-Beispiele** (KRITISCH für Antwortqualität):

   ```
   Grep: "few.shot\|few_shot\|example_select\|shot_example\|good_response\|best_response" in assistant/assistant/
   ```

   Prüfe:
   - **Quelle**: Woher kommen die Few-Shot-Beispiele? Manuell kuratiert oder automatisch aus guten Antworten?
   - **Qualitätskontrolle**: Wird geprüft ob ein Beispiel WIRKLICH gut ist? (Score ≥ X, User-Feedback positiv?)
   - **Aktualität**: Wie alt dürfen Beispiele sein? Alte Beispiele mit veralteten Gerätenamen = Verwirrung
   - **Kategorie-Abdeckung**: Gibt es Beispiele für ALLE Kategorien? (device_command, smalltalk, analysis, knowledge, cooking, etc.)
   - **Persönlichkeits-Konsistenz**: Klingen die Beispiele wie MCU-Jarvis? Oder sind sie generisch?
   - **Token-Budget**: Wie viele Tokens verbrauchen die Few-Shot-Beispiele? Verdrängen sie wichtigeren Kontext?
   - **Negativ-Beispiele**: Gibt es auch "so NICHT"-Beispiele? (Hilft dem LLM schlechte Muster zu vermeiden)

6. **Self-Optimization**:
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

### Teil 7: Multi-Person — Persönlicher Assistent für JEDEN Bewohner

> **Jarvis ist nicht EIN Assistent für ALLE — er ist der PERSÖNLICHE Assistent von JEDEM.**
> Jeder Bewohner hat eigene Vorlieben, Erinnerungen, Routinen, Termine, Notizen.
> Jarvis muss wissen WER spricht und den Kontext DIESER Person laden.

```
Read: assistant/assistant/family_manager.py
Read: assistant/assistant/person_preferences.py
Read: assistant/assistant/speaker_recognition.py (Abschnitte: identify_speaker, Confidence-Levels)
Read: assistant/assistant/conflict_resolver.py (Abschnitte: Mediation, Trust-Level)
Read: assistant/assistant/semantic_memory.py (Abschnitte: search_facts person-Filter)
```

#### 7.1: Sprecher-Erkennung als Fundament

Prüfe:
1. **Genauigkeit**: 7-stufiges System (Device → DoA → Room → Presence → Voice → Features → Cache) — sind die Konfidenz-Schwellen realistisch?
2. **Fallback-Kette**: Was passiert bei Konfidenz < 0.5? Fragt Jarvis "Wer spricht?" oder rät er?
3. **Neuer Bewohner**: Wie schnell lernt das System eine neue Stimme? Wie viele Samples braucht ECAPA-TDNN?
4. **Verwechslung**: Ähnliche Stimmen (Geschwister, Eltern/Kind) — wie wird das gehandhabt?
5. **Gast-Erkennung**: Unbekannte Stimme → Gast-Modus mit eingeschränkten Rechten?

#### 7.2: Per-Person Gedächtnis & Privatsphäre

Prüfe:
1. **Fakt-Isolation**: "Ich habe eine Nussallergie" (Max) → Wird das NUR bei Max gespeichert?
2. **Abruf-Isolation**: Kann Lisa fragen "Hat Max eine Allergie?" → Darf Jarvis das verraten?
3. **Privatsphäre-Regeln**: Gibt es eine Konfiguration was geteilt wird und was privat ist?
   - Gesundheitsdaten → IMMER privat?
   - Termine → teilbar?
   - Vorlieben → teilbar?
4. **Shared Memory**: Haushalts-Fakten ("Die Waschmaschine ist kaputt") → Für ALLE gespeichert?
5. **Cross-Person-Leakage**: Prüfe ob `search_facts(person="Max")` WIRKLICH nur Max-Fakten zurückgibt

```
Grep: "person.*filter\|person.*search\|person.*query" in assistant/assistant/semantic_memory.py
```

#### 7.3: Per-Person Präferenzen & Kommunikationsstil

Prüfe:
1. **Altersgerechte Kommunikation**: Kind (0-12) → einfach, Emojis, "Hey". Teenager → casual. Erwachsener → Butler-Stil. Funktioniert das?
2. **Sarkasmus pro Person**: Mag Lisa Humor Level 4, Max nur Level 2 → wird das personalisiert?
3. **Sprach-Tempo**: Kinder → langsamer, einfacher. Erwachsene → normal. Wird TTS angepasst?
4. **Begrüßung**: "Guten Morgen, Sir" (Max) vs. "Morgen, Lisa!" vs. "Hey, Tim!" → per Person konfiguriert?

#### 7.4: Per-Person Routinen & Proaktivität

Prüfe:
1. **Morgen-Briefing**: Hat JEDER sein eigenes? (Max steht um 6 auf, Lisa um 8 → zwei verschiedene Briefings?)
2. **Gute-Nacht-Routine**: Pro Person? (Kind geht um 20 Uhr ins Bett, Erwachsene um 23 Uhr)
3. **Proaktive Hinweise**: Werden Hinweise an die RICHTIGE Person geliefert? ("Max, dein Meeting in 30 Minuten" → nicht an Lisa sagen)
4. **Ankunfts-Begrüßung**: Personalisiert? ("Willkommen zurück, Sir. Die Heizung läuft bereits." vs. "Hey Tim, Mama hat Essen gemacht!")
5. **Quiet Hours pro Person**: Max schläft bis 10 am Wochenende, Lisa steht um 7 auf → KEINE Benachrichtigungen an Max vor 10?

```
Grep: "person\|per_person\|person_name" in assistant/assistant/routine_engine.py
Grep: "person\|target_person\|delivery.*person" in assistant/assistant/proactive.py
```

#### 7.5: Persönliche Assistenz-Features pro Person

Prüfe ob diese Module wissen WER fragt:

1. **Kochen** (`cooking_assistant.py`):
   - "Was soll ICH kochen?" → Berücksichtigt Max' Allergie, nicht Lisas
   - "Was sollen WIR kochen?" → Berücksichtigt ALLE Allergien/Vorlieben
   - Session-Tracking: Wer kocht gerade? (Person-Feld existiert, wird es genutzt?)

2. **Einkauf** (`smart_shopping.py`):
   ```
   Grep: "person" in assistant/assistant/smart_shopping.py
   ```
   - Gibt es persönliche vs. Haushalts-Listen? ("Max' Wunschliste" vs. "Einkaufsliste")
   - ⚠️ **Bekanntes Defizit**: Keine Person-Filterung gefunden. Alle sehen alles.

3. **Kalender** (`calendar_intelligence.py`):
   ```
   Grep: "person" in assistant/assistant/calendar_intelligence.py
   ```
   - "Was steht MORGEN an?" → Wessen Termine? Nur meine? Alle?
   - ⚠️ **Bekanntes Defizit**: Keine explizite Multi-Person-Unterstützung gefunden.

4. **Notizen** (`note_manager.py`): ✅ Per Person implementiert — prüfe ob Abruf korrekt filtert
5. **Todos** (`task_manager.py`): ✅ Per Person implementiert — prüfe ob Zuweisung funktioniert
6. **Wellness** (`wellness_advisor.py`): Weiß der Advisor WER zu lange am PC sitzt?

#### 7.6: Konfliktmediation & Fairness

Prüfe:
1. **Trust-Level-Fairness**: Verliert ein Gast IMMER gegen ein Familienmitglied? Auch wenn der Gast zuerst gefragt hat?
2. **Konflikt-Mediation**: 300s Konflikt-Fenster — zu breit? (Person A stellt Heizung ein → geht → Person B kommt 4min später → Konflikt?)
3. **Gleichzeitige Requests**: Max und Lisa sagen gleichzeitig "Licht an" in verschiedenen Räumen → per-Person Locks korrekt?
4. **Shared Spaces**: Wohnzimmer — Max will 22°C, Lisa will 20°C → wie wird mediiert?
5. **Raum-Restriktionen**: Schlafzimmer nur für bestimmte Personen → funktioniert `room_restrictions`?

#### 7.7: Multi-Person End-to-End Szenarien

Trace diese Szenarien mental durch den Code:

**Szenario A: Familien-Abend**
→ Max: "Jarvis, mach Filmabend" → Licht dimmen, TV an, Persönliche Filmvorlieben laden
→ Lisa (5 min später): "Jarvis, es ist zu kalt" → Heizung hoch, OHNE Filmabend zu stören
→ Kind Tim: "Jarvis, ich will auch einen Film!" → Altersgerechte Antwort, ggf. Kinderschutz

**Szenario B: Getrennte Routinen**
→ 06:00 Max steht auf → Sein Briefing (seine Termine, sein Pendelweg)
→ 08:00 Lisa steht auf → Ihr Briefing (ihre Termine, ihr Pendelweg)
→ Jarvis verwechselt NICHTS zwischen beiden Briefings

**Szenario C: Privatsphäre**
→ Max: "Merk dir, ich plane eine Überraschungsparty für Lisa"
→ Lisa: "Was hat Max dir heute erzählt?"
→ Jarvis DARF DAS NICHT VERRATEN

**Szenario D: Gast im Haus**
→ Unbekannte Stimme: "Jarvis, öffne die Haustür"
→ Jarvis: Gast-Modus → Security-Action → NICHT ausführen, Bewohner informieren

Für jedes Szenario: Wo bricht die Kette?

**Output**: Multi-Person-IQ-Score (1-5) + Privatsphäre-Risiken + Cross-Module-Lücken.

### Teil 8: Konversations-Intelligenz

**Ziel**: Prüfe ob Jarvis Gespräche korrekt verfolgt und Referenzen auflöst.

```
Read: assistant/assistant/dialogue_state.py
Read: assistant/assistant/action_planner.py (Abschnitte: Planung, Narration)
Read: assistant/assistant/time_awareness.py
```

**Prüfe**:

1. **Referenz-Auflösung** (`dialogue_state.py`):
   - "Mach DAS Licht an" → Welches Licht? Das zuletzt besprochene? Das im aktuellen Raum?
   - "Dort" → Welcher Raum? Der zuletzt erwähnte?
   - "Nochmal" / "Das gleiche" → Wird die letzte Aktion korrekt wiederholt?
   - Cross-Session: "Was hatten wir gestern besprochen?" → Funktioniert das?
   - **Szenarien testen**: "Mach das Licht im Wohnzimmer an. Und dort auch die Heizung." → "dort" = Wohnzimmer?

2. **Multi-Step-Planung** (`action_planner.py`):
   - "Mach alles fertig für die Nacht" → Wie viele Schritte? In welcher Reihenfolge?
   - Ist die Narration natürlich? ("Ich dimme das Licht... schließe die Rollläden... stelle die Heizung runter.")
   - Was wenn ein Schritt fehlschlägt? Wird der Rest abgebrochen oder fortgesetzt?
   - Sind die Schritte LOGISCH? (Erst Licht aus, dann Rollläden → oder andersherum?)

3. **Zeit-Verständnis** (`time_awareness.py`):
   - "Morgen früh" → Welche Uhrzeit? 6:00? 7:00? Abhängig vom User-Profil?
   - "Nächste Woche" → Montag oder gleicher Wochentag?
   - "In einer Stunde" → Wird ein Timer gesetzt oder eine Erinnerung?
   - Saisonale Unterschiede: "Abends" im Sommer (21:00) vs. Winter (17:00)?

**Output**: Konversations-IQ-Score (1-5) + Schwächen.

### Teil 9: Umgebungs-Intelligenz

**Ziel**: Prüfe ob Jarvis seine Umgebung korrekt versteht und darauf reagiert.

```
Read: assistant/assistant/activity.py (Abschnitte: Silence Matrix, Aktivitätszustände)
Read: assistant/assistant/climate_model.py (Abschnitte: Vorhersage, Vorheizen)
Read: assistant/assistant/threat_assessment.py
Read: assistant/assistant/mood_detector.py (Abschnitte: Stimmungserkennung, Schwellwerte)
Read: assistant/assistant/device_health.py (Abschnitte: Anomalie-Erkennung)
```

**Prüfe**:

1. **Aktivitäts-Erkennung** (`activity.py`):
   - Silence Matrix: 7 Zustände × 3 Dringlichkeiten → Ist die Matrix korrekt?
   - "sleeping" → Wie wird Schlaf erkannt? (Licht aus + keine Bewegung + Nachtzeit?)
   - "focused" → Wie wird Konzentration erkannt? (PC aktiv + keine Interaktion?)
   - **Kritisch**: Kann Jarvis fälschlich "sleeping" erkennen und wichtige Meldungen unterdrücken?

2. **Klima-Vorhersage** (`climate_model.py`):
   - Vorheizen: "Morgen um 7:00 soll es 22°C sein" → Wann muss die Heizung starten?
   - Berücksichtigt das Modell Außentemperatur, Isolierung, Sonneneinstrahlung?
   - Wie genau ist die Vorhersage? Gibt es eine Feedback-Schleife?

3. **Bedrohungs-Erkennung** (`threat_assessment.py`):
   - Rauchmelder → Emergency. Aber was bei Fehlalarm (Kochen)?
   - Wassermelder → Ventil schließen. Aber was wenn Sensor defekt?
   - Offenes Fenster bei Sturm → Warnung. Aber was wenn User absichtlich lüftet?
   - **False-Positive-Rate**: Wie oft warnt Jarvis unnötig?

4. **Stimmungs-Erkennung** (`mood_detector.py`):
   - Wird "Stress" korrekt von "Eile" unterschieden? (Beide haben kurze Sätze)
   - Wird "Müde" korrekt von "Gelangweilt" unterschieden?
   - Sprach-Metadaten (Geschwindigkeit, Lautstärke): Werden sie tatsächlich genutzt?
   - **Qualitäts-Frage**: Verbessert die Stimmungserkennung die Antworten wirklich?

5. **Geräte-Anomalie** (`device_health.py`):
   - 30-Tage-Baseline → Was beim ersten Monat? (Keine Baseline)
   - Saisonale Schwankungen: Heizungsverbrauch im Winter ≠ Sommer
   - Batterieschwache Sensoren: Werden sie rechtzeitig erkannt?

**Output**: Umgebungs-IQ-Score (1-5) + Schwächen.

### Teil 10: Wissens- & Erklär-Intelligenz

**Ziel**: Prüfe ob Jarvis Wissen korrekt abruft und Entscheidungen erklären kann.

```
Read: assistant/assistant/knowledge_base.py
Read: assistant/assistant/knowledge_graph.py (Abschnitte: Nodes, Edges, Queries)
Read: assistant/assistant/explainability.py
Read: assistant/assistant/energy_optimizer.py (Abschnitte: Optimierungslogik)
Read: assistant/assistant/routine_engine.py (Abschnitte: Morgen-Briefing, Gute-Nacht)
```

**Prüfe**:

1. **RAG-Retrieval** (`knowledge_base.py`):
   - Relevanz-Schwelle: dynamisch nach Query-Länge. Sind die Werte sinnvoll?
   - Top-K Retrieval: Wie viele Dokumente werden geholt? Zu viele = Token-Verschwendung, zu wenige = Wissenslücke
   - Werden veraltete Dokumente entfernt? Gibt es TTL?

2. **Wissensgraph** (`knowledge_graph.py`):
   - Max 1000 Nodes → Was wenn erreicht? Werden alte entfernt?
   - 2-Hop-Queries: "Person → Raum → Gerät" → Funktioniert das?
   - Edge-TTL 180 Tage → Veralten Verbindungen korrekt?

3. **Erklärbarkeit** (`explainability.py`):
   - "Warum hast du die Heizung aufgedreht?" → Bekommt der User eine verständliche Antwort?
   - Werden ALLE Entscheidungsfaktoren genannt? (Temperatur, Wetter, Zeitplan, Gewohnheit)
   - Ist die Erklärung natürlich formuliert oder technisch?

4. **Energie-Intelligenz** (`energy_optimizer.py`):
   - Strompreis-Monitoring: Werden flexible Verbraucher korrekt verschoben?
   - Solar-Awareness: Wird Überschuss erkannt und genutzt?
   - Empfehlungs-Qualität: Sind die Tipps hilfreich oder generisch?

5. **Routinen-Qualität** (`routine_engine.py`):
   - Morgen-Briefing: Ist es knapp und relevant? (Wetter + Termine + Highlights)
   - Gute-Nacht: Werden alle Sicherheits-Checks durchlaufen?
   - Ankunfts-Begrüßung: Ist sie natürlich und informativ?
   - **Qualitäts-Frage**: Hört sich das Briefing jeden Tag gleich an? Oder variiert es?

**Output**: Wissens-IQ-Score (1-5) + Schwächen.

### Teil 11: Autonomie-Intelligenz

**Ziel**: Prüfe ob Jarvis korrekt entscheidet WANN er selbst handeln darf und WANN er fragen muss.

```
Read: assistant/assistant/autonomy.py
Read: assistant/assistant/self_automation.py
Read: assistant/assistant/proactive_planner.py
Read: assistant/assistant/conditional_commands.py
Read: assistant/assistant/seasonal_insight.py
```

**Prüfe**:

1. **Autonomie-Level** (`autonomy.py`):
   - Level 1 (Assistent) → Fragt immer. Level 5 (Autopilot) → Handelt immer.
   - Sind die Grenzen pro Domain sinnvoll? (Sicherheit: immer fragen. Licht: ab Level 3 auto.)
   - Kann ein Bug oder eine falsche Konfidenz das Autonomie-Level umgehen?

2. **Auto-Automatisierung** (`self_automation.py`):
   - Erstellt Jarvis korrekte Automatisierungen aus Mustern?
   - Sicherheitsvalidierung: Kann er gefährliche Automatisierungen erstellen? (z.B. Türschloss nachts offen)
   - Werden erstellte Automatisierungen dem User gezeigt bevor sie aktiv werden?

3. **Proaktive Mehrstufige Sequenzen** (`proactive_planner.py`):
   - Timing korrekt? (Schritt 1 um 18:00, Schritt 2 um 18:05, etc.)
   - Narration natürlich? ("Ich bereite jetzt alles vor...")
   - Rollback wenn ein Schritt fehlschlägt?

4. **Bedingte Befehle** (`conditional_commands.py`):
   - "Wenn es regnet, mach die Fenster zu" → Wird das korrekt evaluiert?
   - Werden Bedingungen regelmäßig geprüft oder nur einmalig?
   - Timeout: Wie lange gilt die Bedingung?

5. **Saisonale Empfehlungen** (`seasonal_insight.py`):
   - Sind die Empfehlungen zeitlich korrekt? (Heizstrategie ab Oktober, nicht Juli)
   - Werden sie oft genug / nicht zu oft ausgegeben?
   - Sind sie hilfreich oder generisch?

**Output**: Autonomie-IQ-Score (1-5) + Schwächen.

### Teil 12: Anti-Halluzinations-Guard (3 Schichten)

> **Dies ist eine der kritischsten Intelligenz-Komponenten: Sie bestimmt ob Jarvis die Wahrheit sagt.**

```
Read: assistant/assistant/brain.py offset=8100 limit=500
Grep: "_generate_contextual_error" in assistant/assistant/brain.py
Grep: "_verify_device_state" in assistant/assistant/brain.py
```

**Schicht 1: Action-Claims-Guard** — Erkennt falsche Handlungsbehauptungen

Prüfe:
1. **Erkennung**: Wenn LLM sagt "Ich habe das Licht eingeschaltet" aber 0 Aktionen ausgeführt wurden → wird das erkannt?
2. **Pattern-Abdeckung**: Werden ALLE deutschen Formulierungen abgedeckt? ("eingeschaltet", "aktiviert", "angemacht", "hochgefahren", "gestartet", etc.)
3. **False Positives**: "Ich WÜRDE einschalten" (Konjunktiv) ist keine Behauptung → wird das korrekt unterschieden?
4. **Teilweise Ausführung**: 3 von 5 Geräten geschaltet → werden die 2 fehlgeschlagenen korrekt gemeldet oder wird alles als Erfolg dargestellt?

**Schicht 2: Quantitative Guard** — Erkennt erfundene Zahlen/Messwerte

Prüfe:
1. **Zahlen-Extraktion**: Werden ALLE Zahlen im Response gegen den Kontext geprüft?
2. **Toleranz**: "20.3°C" im Kontext, LLM sagt "etwa 20 Grad" → wird das als Halluzination erkannt? (Sollte es NICHT, Rundung ist OK)
3. **Zeitangaben**: "Es ist 14:30" → wird das gegen die echte Uhrzeit geprüft?
4. **Prozentangaben**: Batterie "87%" im Kontext, LLM sagt "87%" → OK. Aber "90%"? → Halluzination
5. **Kontext-Vollständigkeit**: Wenn eine Zahl NICHT im Kontext steht (weil der Kontext abgeschnitten wurde), wird sie fälschlicherweise als Halluzination markiert?

**Schicht 3: Qualitative Guard** — Erkennt erfundene Geräte

Prüfe:
1. **Entity-Katalog**: Woher kommt die Liste bekannter Geräte? Ist sie aktuell?
2. **Synonyme**: "Wohnzimmerlampe" vs. "light.wohnzimmer" → erkennt der Guard beide?
3. **Neue Geräte**: Wenn ein Gerät gerade erst hinzugefügt wurde → wird es fälschlich als "erfunden" markiert?
4. **Nur device-Kategorien**: Guard ist nur aktiv bei `device_command` und `device_query` → was ist mit `analysis`-Kategorie die Geräte erwähnt?

**Fallback: `_generate_contextual_error()`**

Prüfe:
1. Was passiert wenn ALLE 3 Schichten den gesamten Response entfernen?
2. Ist der Fallback-Text natürlich oder robotisch? ("Ich konnte nicht..." vs. "Error 500")
3. Wird der Fallback als Character-Break geloggt?
4. Gibt es einen Eskalationsmechanismus wenn der Fallback häufig ausgelöst wird?

**Post-Verification: `_verify_device_state()`**

Prüfe:
1. **Timing**: 1.5s Wartezeit → reicht das für langsame Geräte (Rollläden, Heizung)?
2. **Korrektur-Nachricht**: Wenn Gerät nicht reagiert hat → was sagt Jarvis dem User?
3. **Retry**: Wird ein erneuter Versuch gestartet oder nur gemeldet?
4. **Background-Task**: Läuft als `asyncio.create_task()` → hat es einen `add_done_callback`?

**Response-Cache als Halluzinations-Vektor:**

```
Read: assistant/assistant/response_cache.py
```

Prüfe:
1. **TTL**: Wie lange werden Antworten gecacht? Wenn >5min → Zustand kann sich geändert haben
2. **Invalidierung**: Wird der Cache geleert wenn sich der HA-State ändert? (Licht an → "Licht ist aus" aus Cache = FALSCH)
3. **Personalisierung**: Werden gecachte Antworten für User A auch an User B ausgegeben?
4. **Kontext-Hash**: Wird der Kontext (Raum, Tageszeit, Gerätezustand) im Cache-Key berücksichtigt?

**State-Change-Attribution als Lern-Gift:**

```
Grep: "attribution\|AttributionResult\|_determine_cause" in assistant/assistant/state_change_log.py limit=30
```

Prüfe:
1. **Korrekte Attribution**: Wenn User manuell das Licht schaltet → erkennt das System "User" und nicht "Automation"?
2. **Timing-Fenster**: Wie groß ist das Fenster für die Zuordnung? Zu klein → User-Aktionen werden als "Unbekannt" geloggt. Zu groß → Zufälle werden als kausal verknüpft.
3. **Lern-Impact**: Falsche Attribution → Anticipation lernt falsche Muster → Jarvis schlägt falsche Aktionen vor
4. **80+ Abhängigkeitsregeln**: Sind die Regeln vollständig? Fehlen neue Gerätetypen?

**Output**: Halluzinations-Guard-Score (1-5) + kritische Schwächen.

### Teil 13: Persönlicher Assistent-IQ

> **Jarvis ist nicht nur Smart-Home-Controller — er ist ein persönlicher Assistent.**
> Hier wird geprüft ob die Assistenz-Features QUALITATIV gut sind, nicht nur ob sie keine Bugs haben.

#### 13.1: Kochen & Ernährung

```
Read: assistant/assistant/cooking_assistant.py (Abschnitte: Intent-Erkennung, Rezept-Flow, Persönlichkeit)
Read: assistant/assistant/meal_planner.py
```

Prüfe:
1. **Persönlichkeit**: Klingt Jarvis beim Kochen wie MCU-Jarvis? ("Die Zwiebeln sind bereit, Sir. Ich empfehle glasig, nicht verbrannt.") Oder ist es generisch? P03b zeigt: Cooking umgeht die Persönlichkeits-Pipeline!
2. **Schritt-für-Schritt**: Wartet Jarvis auf "weiter" bevor er den nächsten Schritt erklärt?
3. **Anpassung**: Kennt er Allergien/Vorlieben aus dem Gedächtnis? ("Sir, das Rezept enthält Nüsse. Soll ich eine Alternative vorschlagen?")
4. **Zeitmanagement**: "Das muss 20 Minuten köcheln" → Setzt er automatisch einen Timer?
5. **Cross-Modul**: Wird der Einkaufszettel (`smart_shopping`) aktualisiert wenn Zutaten fehlen?

#### 13.2: Einkauf & Vorräte

```
Read: assistant/assistant/smart_shopping.py
```

Prüfe:
1. **Natürliche Interaktion**: "Wir brauchen Milch" → Wird das auf die Einkaufsliste gesetzt ohne dass der User "füge Milch zur Einkaufsliste hinzu" sagen muss?
2. **Kontext-Awareness**: Weiß Jarvis was schon da ist? (Vorratsverwaltung)
3. **Proaktivität**: "Sir, die Milch müsste langsam aufgebraucht sein. Soll ich sie auf die Liste setzen?"
4. **Gedächtnis**: Lernt er welche Marke/Menge der User bevorzugt?

#### 13.3: Kalender & Termine

```
Read: assistant/assistant/calendar_intelligence.py
```

Prüfe:
1. **Aktive Abfrage**: "Was steht morgen an?" → Bekommt der User eine sinnvolle Antwort?
2. **Proaktive Erinnerungen**: Erinnert Jarvis VOR dem Termin? Mit Pendelzeit-Puffer?
3. **Konflikterkennung**: "Sir, der Zahnarzt überlappt mit dem Meeting. Soll ich einen umbuchen?"
4. **Gewohnheiten**: Erkennt er regelmäßige Termine die nicht im Kalender stehen? ("Dienstags gehen Sie immer joggen.")
5. **Cross-Modul**: Beeinflusst ein voller Kalender die Kochempfehlung? (Schnelles Rezept an stressigen Tagen)

#### 13.4: Wellness & Gesundheit

```
Read: assistant/assistant/wellness_advisor.py
Read: assistant/assistant/health_monitor.py
```

Prüfe:
1. **PC-Pausen**: Erkennt er lange PC-Sessions und erinnert an Pausen? Wie? Nervt er oder ist er dezent?
2. **Stressintervention**: "Sir, Sie arbeiten seit 4 Stunden ohne Pause. Darf ich einen Tee vorschlagen?"
3. **Nachtruhe**: "Es ist 2 Uhr nachts, Sir. Morgen steht ein Meeting um 8 an." — aber NICHT jeden Abend!
4. **Dosierung**: Wie oft darf Wellness-Advisor eingreifen? Zu oft = nervt, zu selten = nutzlos
5. **CO2/Luft**: Werden die health_monitor Alerts (CO2 >1000ppm) als Butler-Hinweis formuliert?

#### 13.5: Workshop, Reparatur & DIY

```
Read: assistant/assistant/workshop_generator.py
Read: assistant/assistant/repair_planner.py
```

Prüfe:
1. **Persönlichkeit**: P03b zeigt: Workshop hat EIGENE LLM-Prompts die die Persönlichkeit UMGEHEN. Klingt generierter Code/3D-Modell-Code wie von Jarvis kommentiert?
2. **Reparatur-Diagnose**: Ist die Diagnose hilfreich oder generisch? ("Das könnte X oder Y sein" vs. konkreter Ablauf)
3. **Sicherheitswarnungen**: "Sir, Arbeiten an der Elektrik ohne Abschaltung wäre... unklug." — Butler-Ton, nicht Warnschild
4. **Kostenabschätzung**: Realistisch oder geschätzt? Woher kommen die Preise?

#### 13.6: Notizen, Todos & Geburtstage

```
Read: assistant/assistant/note_manager.py
Read: assistant/assistant/task_manager.py
Read: assistant/assistant/personal_dates.py
```

Prüfe:
1. **Natürliche Notizen**: "Merk dir mal, der Schlüssel für die Garage liegt im Büro" → wird das zuverlässig gespeichert UND wiedergefunden?
2. **Proaktive Erinnerungen**: "Sir, morgen ist Marias Geburtstag." — am Vorabend oder am Morgen?
3. **Todo-Kontext**: "Ich muss den Rasen mähen" → Wird das mit Wetter verknüpft? ("Sir, heute regnet es. Vielleicht morgen?")
4. **Abruf**: "Was hatte ich mir letzte Woche gemerkt?" → Funktioniert die Suche?

#### 13.7: Web-Suche & Wissen

```
Read: assistant/assistant/web_search.py
Read: assistant/assistant/knowledge_base.py
```

Prüfe:
1. **Wann sucht Jarvis?**: Wenn er die Antwort nicht weiß → sucht er automatisch? Oder erst auf Nachfrage?
2. **Quellenangabe**: Nennt Jarvis woher er die Info hat? ("Laut SearXNG..." vs. als eigenes Wissen darstellen)
3. **SSRF-Schutz**: 7-Schichten → kurzer Check ob alle aktiv sind
4. **Fallback**: SearXNG down → DuckDuckGo? DuckDuckGo down → Was dann?

#### 13.8: Cross-Modul-Integration (DER ULTIMATIVE TEST)

> **Ein guter persönlicher Assistent verbindet Informationen aus ALLEN Modulen.**

Prüfe diese Szenarien mental durch den Code-Flow:

**Szenario A: "Jarvis, was soll ich heute kochen?"**
→ Checkt: Kalender (stressiger Tag? → schnelles Rezept), Vorräte (was ist da?), Vorlieben (Semantic Memory), Gesundheit (Diät?), Wetter (heißer Tag → kaltes Gericht?)
→ **Wird das ALLES berücksichtigt oder nur ein Rezept aus der DB geholt?**

**Szenario B: "Jarvis, ich fahre morgen in den Urlaub"**
→ Checkt: Kalender (Termine absagen?), Geräte (Urlaubssimulation starten), Pflanzen (Bewässerung), Sicherheit (Fenster zu? Alarmanlage?), Heizung (runter), Nachbarn (Briefkasten?)
→ **Wie viele dieser Module werden automatisch angesprochen?**

**Szenario C: "Jarvis, mein Rücken tut weh"**
→ Checkt: Wellness (Haltungstipps, Pause empfehlen), Kalender (Arzttermin vorschlagen?), Gedächtnis (hatte der User das schon mal erwähnt?), Heizung (Wärme hilft?)
→ **Oder antwortet Jarvis nur "Das tut mir leid, Sir"?**

**Szenario D: "Jarvis, Marias Geburtstag ist in 3 Tagen"**
→ Checkt: Personal Dates (speichern), Kalender (Termin erstellen?), Einkauf (Geschenk besorgen?), Proaktiv (Erinnerung am Tag)
→ **Werden alle Module getriggert?**

Für jedes Szenario: Trace den Code-Flow und dokumentiere wo die Kette BRICHT.

**Output**: Persönlicher-Assistent-IQ-Score (1-5) + Cross-Modul-Bruchstellen.

### Teil 14: Gesamtbewertung & Verbesserungsplan

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
| Konversations-IQ | X/5 | ... | ... | S/M/L |
| Umgebungs-IQ | X/5 | ... | ... | S/M/L |
| Wissens-IQ | X/5 | ... | ... | S/M/L |
| Autonomie-IQ | X/5 | ... | ... | S/M/L |
| Anti-Halluzination | X/5 | ... | ... | S/M/L |
| Persönlicher Assistent | X/5 | ... | ... | S/M/L |
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
=== CHECKPOINT Teil X/12 ===
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
- Konversations-IQ: X/5 — [Hauptproblem]
- Umgebungs-IQ: X/5 — [Hauptproblem]
- Wissens-IQ: X/5 — [Hauptproblem]
- Autonomie-IQ: X/5 — [Hauptproblem]
QUICK WINS: [Liste der einfachen Verbesserungen mit Datei:Zeile]
ARCHITEKTUR-ISSUES: [Größere Probleme die Umbau brauchen]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste]
NAECHSTER SCHRITT: P06a (Stabilisierung) mit Qualitäts-Fixes priorisiert
===================================
```
