# J.A.R.V.I.S. MCU-Level Implementation Plan
> Erstellt am 2026-03-22 | Letzter Durchlauf: Session 1 am 2026-03-22
> Aktueller Stand: 76.4% (Teilergebnis — 4 von 12 Kategorien analysiert)
> Dieses Dokument ist die Single Source of Truth für alle MCU-Level Verbesserungen.

## Status-Legende
- `[ ]` — Offen, noch nicht umgesetzt
- `[~]` — Teilweise erledigt
- `[x]` — Vollständig erledigt und verifiziert
- `⏭️` — Obsolet
- `🆕` — Neu hinzugefügt

## Fortschritts-Tracker
| Session | Datum | Kategorien | Aufgaben |
|---------|-------|------------|----------|
| 1       | 2026-03-22 | 1-4 (×3/×2.5) | 19 |

## Schutzliste — Besser als MCU (NICHT beschädigen!)

1. **Cross-Session temporale Referenzierung** (`dialogue_state.py`, Zeile 324-450) — "Wie gestern", "wie am Montag" mit Redis Action-Log. MCU-Jarvis zeigt keine vergleichbare explizite temporale Rückreferenzierung.
2. **STT-Korrektursystem** (`brain.py`, Zeile 12122+) — 95+ deutsche Wortkorrekturen + Phrase-Korrekturen, pre-compiled Regex, YAML-Overrides. MCU-Jarvis hat kein STT.
3. **Contextual Humor Triggers** (`personality.py`, Zeile 109+) — Situations-basierte Kommentare nach Geräte-Aktionen. Systematischer als MCU-Jarvis' Ad-hoc-Humor.
4. **Formality-Decay / Character Evolution** (`personality.py`, Zeile 342-346, 2505-2513) — Dynamische Beziehungsentwicklung über Zeit. MCU-Jarvis bleibt konstant.
5. **Silence Matrix** (`activity.py`, Zeile 54-70) — 7×4 Zustellregel-Matrix. Formaler und robuster als MCU-Jarvis' intuitives Schweigen.
6. **Pushback-Learning** (`function_validator.py`, Zeile 77-109) — Lernt aus übergangenem Widerspruch. MCU-Jarvis passt sich nicht explizit an überstimmte Einwände an.
7. **predict_future_needs()** (`anticipation.py`, Zeile 1798+) — 7-14 Tage Vorausschau. MCU-Jarvis denkt nicht so weit voraus.

## 1. Natürliche Konversation & Sprachverständnis (×3)

### MCU-Jarvis Benchmark
MCU-Jarvis versteht Kontext über lange Gespräche, ironische Bemerkungen, implizite Anweisungen ("mach mal alles fertig"), Unterbrechungen, und antwortet in flüssigem, natürlichem Englisch mit perfekter Prosodie. Er löst Referenzen mühelos auf ("das Ding da", "mach es aus"), versteht Multi-Turn-Dialoge und kann mit vagen, elliptischen Befehlen umgehen.

### MindHome-Jarvis Status: 72%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **DialogueStateManager** (`assistant/assistant/dialogue_state.py`, Zeile 128-450)
   - `[OK]` Per-Person Dialog-Zustand mit 5 Zuständen: idle, awaiting_clarification, follow_up, multi_step
   - `[OK]` Entity-Referenzauflösung: "mach es aus" → letztes Entity, "dort" → letzter Raum, "nochmal" → letzte Aktion (Zeile 268-298)
   - `[BESSER ALS MCU]` Cross-Session temporale Referenzierung: "wie gestern", "wie am Montag", "wie immer" — sucht in Redis Action-Log (Zeile 324-450). MCU-Jarvis zeigt keine vergleichbare explizite temporale Rückreferenzierung.
   - `[OK]` Auto-Eviction bei >50 Person-States, 600s Timeout für veraltete Dialoge

2. **PreClassifier** (`assistant/assistant/pre_classifier.py`, Zeile 265-384)
   - `[OK]` 2-stufige Klassifikation: Regex/Keyword-Match → LLM-Fallback (Fast-Modell, 2s Timeout)
   - `[OK]` Kategorien: device_command, device_query, knowledge, memory, general
   - `[OK]` Spezialbehandlung: Fragewörter-Erkennung, Verb-Start-Detection, Multi-Raum-Befehle bis 12 Wörter

3. **ConversationMemory** (`assistant/assistant/conversation_memory.py`, Zeile 46-75)
   - `[OK]` Projekt-Tracking, offene Fragen mit 14-Tage-TTL, Tageszusammenfassungen, Follow-ups
   - `[OK]` Redis-basiert, Startup-Cleanup abgelaufener Einträge

4. **STT-Korrekturen** (`assistant/assistant/brain.py`, Zeile 12122+, 584-611)
   - `[BESSER ALS MCU]` 95+ deutsche Wortkorrekturen + Phrase-Korrekturen, pre-compiled Regex, Merge mit YAML-Overrides. MCU-Jarvis hat kein STT — er "versteht" direkt.

5. **TTS-Enhancer** (`assistant/assistant/tts_enhancer.py`, Zeile 239-260, 602-621)
   - `[VERBESSERBAR]` SSML-Generierung mit Speed/Volume/Pitch, Emotion-Injection aus inner_mood, Message-Type-Classification
   - Narration-Modus mit Segmenten, Pausen, Fade-Effekten (Zeile 515+)

6. **ContextBuilder** (`assistant/assistant/context_builder.py`, Zeile 215-245)
   - `[OK]` Aggregiert HA-States, Wetter, Kalender, Energie, Semantic Memory, Activity, Health — 5s State-Cache

7. **ModelRouter** (`assistant/assistant/model_router.py`, Zeile 27-57)
   - `[OK]` 3-Tier Routing (Fast/Smart/Deep) mit Task-aware Temperature (command: 0.3, conversation: 0.7, creative: 0.8)

8. **Brain "Das Übliche"** (`assistant/assistant/brain.py`, Zeile 2839-2846, 14373-14450)
   - `[OK]` 10 Trigger-Patterns ("das übliche", "wie immer", "du weisst schon", "mach mal")
   - `[OK]` Verbindung zur AnticipationEngine: bei Confidence ≥0.8 auto-execute, bei ≥0.6 nachfragen, sonst elegant zugeben

**[V2] Zweite Analyse:**

- `[OK]` Keine TODOs/FIXMEs in dialogue_state.py — saubere Implementierung
- `[OK]` Tests: 760 Zeilen in test_dialogue_state.py, 610 in test_pre_classifier.py — solide Abdeckung
- `[VERBESSERBAR]` brain_humanizers.py ist ein reiner Query-Result-Humanizer (Wetter, Kalender etc. → natürliche Sprache), KEIN Anti-Bot/Varianz-System. Der Name ist irreführend — es fehlt: Antwortstruktur-Variation, natürliche Denkpausen, Filler-Wörter
- `[VERBESSERBAR]` Referenzauflösung liefert nur Context-Hints ans LLM, ersetzt NICHT den Text direkt (Zeile 313: `resolved_text: text` = Original). Das ist korrekt für LLM-Nutzung, aber die Qualität hängt vom LLM ab
- `[VERBESSERBAR]` Kein expliziter Interruption-Handler — wenn der User mitten im Gespräch ein neues Thema anfängt, gibt es keinen speziellen Code dafür
- `[UNTERVERBUNDEN]` ConversationMemory Follow-ups werden gesammelt, aber die aktive Nachverfolgung ("Du wolltest gestern noch X erledigen") hängt vom Prompt-Kontext ab

### Was fehlt zum MCU-Level

1. **Antwort-Varianz / Anti-Repetition** — MCU-Jarvis wiederholt nie dieselbe Satzstruktur. Der reale Jarvis hat Mood-Styles und Humor-Templates, aber keine systematische Struktur-Variation über Antworten hinweg. `[TÄGLICH]`
2. **Natürliche Denkpausen / Filler** — MCU-Jarvis sagt "Well, Sir..." oder "Let me check..." bevor er antwortet. Kein Code für natürliche Pause-Injection in TTS. `[TÄGLICH]`
3. **Interrupt-Handling** — MCU-Jarvis kann mitten im Satz unterbrochen werden und nahtlos auf das neue Thema wechseln. Kein expliziter Interrupt-Handler. `[WÖCHENTLICH]`
4. **Elliptische Befehle** — "Auch im Büro" (= wiederhole letzte Aktion im Büro). Die Referenzauflösung erkennt "auch im" als Action-Reference, aber die tatsächliche Ausführung liegt beim LLM. `[WÖCHENTLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Response-Varianz-Engine in personality.py** — Tracke die letzten 5 Antwort-Strukturen (Frage→Aktion→Bestätigung vs. Kommentar→Aktion→Witz) und erzwinge Variation im System-Prompt.
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

2. **`[ ]` Natürliche Denkpausen in tts_enhancer.py** — Füge optionale Filler-Segmente ein ("Moment...", "Mal sehen...") bei komplexen Anfragen die >2s LLM-Zeit brauchen. Nur bei Voice-Interaktion.
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

3. **`[ ]` Topic-Switch-Detection in dialogue_state.py** — Erkenne wenn der User abrupt das Thema wechselt (Kosinus-Ähnlichkeit zwischen aktuellem und letztem Turn < Threshold) und resette den Dialog-Zustand sauber.
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

4. **`[ ]` Aktive Follow-Up-Erinnerungen** — ConversationMemory hat Follow-up-Daten, aber kein proaktiver Trigger der sagt "Du wolltest gestern noch den Handwerker anrufen." Verbinde mit ProactiveManager.
   - Aufwand: Klein
   - Impact: +4%
   - Alltag: `[WÖCHENTLICH]`

5. **`[ ]` Streaming-Feedback bei langen Anfragen** — Bei Voice: sofort "Ich prüfe das" aussprechen, dann im Hintergrund verarbeiten und Ergebnis nachliefern. Reduziert gefühlte Latenz.
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Keine zwei aufeinanderfolgenden Antworten haben dieselbe Satzstruktur
- [ ] Bei Voice-Interaktion: Antwort-Beginn < 1s (Filler/Acknowledgment), vollständige Antwort < 3s
- [ ] Abrupter Themenwechsel wird in >90% der Fälle korrekt erkannt und behandelt
- [ ] Follow-up-Erinnerungen werden innerhalb von 24h proaktiv angeboten
- [ ] "Wie immer" / "Das Übliche" funktioniert zuverlässig (Confidence ≥0.8 nach 5+ Beobachtungen)
- [ ] Cross-Session-Referenzen ("wie gestern") lösen korrekt auf

## 2. Persönlichkeit, Sarkasmus & Humor (×3)

### MCU-Jarvis Benchmark
MCU-Jarvis hat trockenen britischen Humor, der nie aufdringlich ist. "I do apologize, Sir, but I'm not certain what you're asking me to do." — 90% sachlich, 10% Humor. Situationsabhängig: Schweigt bei Gefahr, mehr Humor wenn Tony entspannt ist. Konsistente Persönlichkeit über alle Filme hinweg. Eigene Meinung, aber respektvoll. Charakter-Entwicklung: wird vertrauter, aber nie respektlos.

### MindHome-Jarvis Status: 78%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **PersonalityEngine** (`assistant/assistant/personality.py`, Zeile 321-3743)
   - `[OK]` Sarkasmus-Level 1-5 mit detaillierten Templates pro Level (Zeile 64-70): Level 1 = kein Humor, Level 3 = "trocken-britischer Humor, wie ein Butler der innerlich schmunzelt", Level 5 = scharfzüngig
   - `[OK]` Mood-Styles: 5 Stimmungen (good, neutral, stressed, frustrated, tired) mit Stil-Addon und max_sentences-Modifikatoren
   - `[BESSER ALS MCU]` Contextual Humor Triggers (Zeile 109+): Situations-basierte Kommentare nach Aktionen — z.B. "25 Grad um 23 Uhr. Ambitioniert, Sir." oder "Änderung Nummer 5. Ich behalte den Überblick." MCU-Jarvis hat kontextuellen Humor, aber nicht systematisch an Geräte-Aktionen gebunden.
   - `[OK]` Mood x Complexity Matrix: Antwortlänge variiert nach Stimmung × Anfrage-Komplexität
   - `[OK]` Per-Person Profiles mit individuellen Humor/Empathy/Response-Style Overrides
   - `[OK]` Scene-Personality: Aktive Szenen beeinflussen Antwort-Stil (Filmabend → minimal)

2. **Core Identity** (`assistant/assistant/core_identity.py`, Zeile 1-78)
   - `[OK]` Unveränderliche Werte: Loyalität, Ehrlichkeit, Diskretion, Effizienz, Sicherheit
   - `[OK]` Beziehungsdynamik definiert: "Respektvoll aber nie unterwürfig — ein Partner, kein Diener"
   - `[OK]` Grenzen: "Niemals vorgeben ein Mensch zu sein", "Niemals erfinden was er nicht weiss"
   - `[OK]` Emotionales Spektrum: Zufriedenheit, Unbehagen, Neugier, Stolz, Sorge, Ironie

3. **InnerStateEngine** (`assistant/assistant/inner_state.py`, Zeile 140-180)
   - `[OK]` 7 Stimmungen: neutral, zufrieden, amüsiert, besorgt, stolz, neugierig, irritiert
   - `[OK]` Emotion Blending (#18): gewichtete Mischung statt harter Mood-Wechsel
   - `[OK]` Event-Counter: successful_actions, failed_actions, ignored_warnings, funny_interactions, complex_solves
   - `[OK]` Redis-Persistenz: Mood überlebt Neustarts (Zeile 166-179)

4. **Character Lock** (`assistant/assistant/personality.py`, Zeile 3572-3574)
   - `[OK]` Closing Anchor am Prompt-Ende: "CHARAKTER-LOCK" Section — LLMs gewichten Prompt-Ende stark
   - `[OK]` Konfigurierbar via `character_lock.enabled` und `character_lock.closing_anchor`

5. **Krisen-Modus** (`assistant/assistant/personality.py`, Zeile 3726-3738)
   - `[OK]` Bei kritischen Alerts (Rauch, CO, Wasser, Einbruch): `crisis_mode=True` → Humor komplett deaktiviert
   - `[OK]` Alerts unterdrücken Sarkasmus unabhängig vom Level

6. **Charakter-Entwicklung** (`assistant/assistant/personality.py`, Zeile 342-346, 2505-2513)
   - `[BESSER ALS MCU]` Formality-Decay: Startet bei 80, sinkt um 0.5/Tag (oder 0.1/Interaktion) bis Minimum 30. MCU-Jarvis wird nie wirklich vertrauter über die Zeit — hier wird die Beziehung dynamisch lockerer.
   - `[OK]` Stress-Reset: Bei Frustration wird temporär formeller — wie ein guter Butler

7. **Late-Night-Fürsorge** (`assistant/assistant/personality.py`, Zeile 3665-3675)
   - `[OK]` 0-4 Uhr: sanfterer Ton, kein Sarkasmus, wärmer. Bei müdem User: minimal, warmherzig

**[V2] Zweite Analyse:**

- `[OK]` Keine TODOs/FIXMEs in personality.py oder core_identity.py
- `[OK]` Test-Coverage: 581 Zeilen test_personality.py, 1140 Zeilen test_inner_state.py — sehr solide
- `[VERBESSERBAR]` Sarkasmus-Level wird als Prompt-Instruktion übergeben, nicht als Output-Filter. Das bedeutet die Qualität hängt davon ab wie gut das LLM die Instruktion befolgt. Bei kleinen Modellen (3B Fast) kann der Humor flach werden.
- `[VERBESSERBAR]` Keine Running-Gag-Persistenz sichtbar — Personality hat Running-Gag-Templates laut CLAUDE.md ("Phase 18: Running Gag Evolution"), aber der tatsächliche Mechanismus zur Speicherung und Evolution über Tage/Wochen fehlt in den gelesenen Abschnitten
- `[OK]` Empathy-Section im System-Prompt: Stress-Level des Users wird in den Prompt eingebaut
- `[VERBESSERBAR]` Meinungs-Engine: `opinion_intensity` Parameter existiert (Zeile 334), aber die tatsächliche Implementierung ist ein Prompt-Parameter — kein eigenständiges Meinungssystem mit Fakten-Basis

### Was fehlt zum MCU-Level

1. **Running Gag Evolution** — MCU-Jarvis hat wiederkehrende Witze die sich entwickeln. Im Code existieren Templates, aber kein Tracking welcher Gag schon N-mal kam und wie er eskalieren sollte. `[WÖCHENTLICH]`
2. **Situations-Comedy über Geräte-Kontext** — Contextual Humor Triggers existieren, aber nur für ca. 10 Situationen. MCU-Jarvis kommentiert ALLES was absurd ist. `[TÄGLICH]`
3. **Sarkasmus-Qualitäts-Check** — Bei Fast-Modellen (3B) kann der Humor platt werden. Kein Quality-Gate das flache Witze filtert. `[TÄGLICH]`
4. **Eigene Meinung mit Tiefe** — opinion_intensity ist ein Prompt-Scaler, kein System das Fakten sammelt und eine begründete Meinung bildet. `[WÖCHENTLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Contextual Humor Triggers erweitern** — Von ~10 auf 30+ Situationen. Besonders: Wiederholte Anfragen ("Schon wieder?"), widersprüchliche Befehle, ungewöhnliche Uhrzeiten, Wetter-Kontraste.
   - Aufwand: Klein
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

2. **`[ ]` Running Gag Tracker in Redis** — Speichere welche Gags benutzt wurden, zähle Wiederholungen, eskaliere Formulierungen. Max 1 Running Gag pro 3 Tage.
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

3. **`[ ]` Humor Quality Gate** — Post-LLM-Filter der bei Fast-Modellen prüft ob der Humor-Anteil der Antwort mindestens ein bestimmtes Pattern enthält (trockener Einzeiler, nicht Emoji-Spam oder Kalauer).
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

4. **`[ ]` Meinungs-Engine mit Fact-Base** — Semantic Memory für "Jarvis' Meinungen" nutzen: Wenn Jarvis 5× gehört hat dass ein Gerät Probleme macht, sollte er eine Meinung dazu haben ("Der Staubsauger war nie mein Favorit").
   - Aufwand: Groß
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Humor ist in >90% der Fälle situationsangemessen (kein Humor bei Krisen, mehr bei guter Stimmung)
- [ ] Sarkasmus-Qualität bleibt auch bei Fast-Modellen konsistent (kein Kalauer, kein Emoji-Humor)
- [ ] Character Lock verhindert Persönlichkeitsbrüche über 100+ aufeinanderfolgende Gespräche
- [ ] Formality-Evolution ist fühlbar: Woche 1 formeller als Monat 3
- [ ] Mindestens 1 Running Gag entwickelt sich über Wochen natürlich
- [ ] Jarvis hat zu mindestens 5 Haus-Themen eine eigene, begründete Meinung

## 3. Proaktives Handeln & Antizipation (×2.5)

### MCU-Jarvis Benchmark
MCU-Jarvis warnt Tony vor Vereisung beim Flug (Iron Man 1), rettet ihn im freien Fall ohne Befehl ("I got you, Sir" — Iron Man 3), verwaltet das Haus autonom während der Party (Iron Man 2), und bereitet Dinge vor die Tony brauchen wird bevor er fragt. Sein Timing ist perfekt: er unterbricht NUR bei Gefahr.

### MindHome-Jarvis Status: 76%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **AnticipationEngine** (`assistant/assistant/anticipation.py`, Zeile 35-198)
   - `[OK]` 4 Pattern-Typen: Zeit-Muster, Sequenz-Muster, Kontext-Muster (Wetter/Anwesenheit), Kausale Ketten (Phase 18)
   - `[OK]` Configurable Thresholds: ask (0.6), suggest (0.8), auto (0.90) — 3-stufiges Confidence-System
   - `[OK]` Correction-Memory-Integration: unterdrückt Muster die korrigiert wurden (Zeile 58)
   - `[OK]` Seasonal-Insight-Integration: Saisonale Daten boosten Pattern-Confidence (Zeile 62)
   - `[OK]` Climate-Model-Integration: Predictive Comfort / proaktive Vorheizung (Zeile 65)
   - `[OK]` Min 5 Beobachtungen bevor Pattern vorgeschlagen wird
   - `[BESSER ALS MCU]` `predict_future_needs()` (Zeile 1798+): Sagt Bedürfnisse für die nächsten 7-14 Tage voraus. MCU-Jarvis denkt nicht so weit voraus.

2. **ProactiveManager** (`assistant/assistant/proactive.py`, Zeile 83-123)
   - `[OK]` Event-getrieben mit 4 Urgency-Levels, Cooldown (300s), Silence-Scenes
   - `[OK]` Personality-Filter: Proaktive Meldungen werden durch Persönlichkeit gefiltert
   - `[OK]` Quiet Hours: Keine LOW/MEDIUM Meldungen nachts (22-7 Uhr konfigurierbar)
   - `[OK]` Notification Batching: LOW-Priority-Meldungen werden gesammelt und gebündelt (30min, max 10)
   - `[OK]` Appliance-Completion-Detection: Erkennt wenn Waschmaschine/Trockner fertig ist
   - `[OK]` Concurrent-safe: asyncio.Lock für shared state

3. **SpontaneousObserver** (`assistant/assistant/spontaneous_observer.py`, Zeile 43-73)
   - `[OK]` Zeitslot-basierte Limits: Morgens max 2, Tagsüber max 3, Abends max 1
   - `[OK]` Min 1.5h Intervall zwischen Beobachtungen
   - `[OK]` Trend-Detection: Erkennt Energie-Trends, Rekorde, Fun Facts
   - `[OK]` Max 5 pro Tag, aktive Stunden 8-22

4. **OutcomeTracker** (`assistant/assistant/outcome_tracker.py`, Zeile 50-77)
   - `[OK]` Vorher/Nachher-Vergleich von Aktionen (180s Delay)
   - `[OK]` Calibration-Range: 0.5-1.5 — verhindert extreme Confidence-Schwankungen
   - `[OK]` Feedback-Loop: Erfolgreiche Aktionen boosten Confidence (+0.1), Fehlschläge senken (-0.15)
   - `[OK]` Integration mit LearningObserver und AnticipationEngine

5. **LearningObserver** (`assistant/assistant/learning_observer.py`, Zeile 65-90)
   - `[OK]` Erkennt manuelle Wiederholungsmuster (≥3× im 30min-Fenster)
   - `[OK]` LLM-basierte Report-Generierung für Automatisierungsvorschläge

6. **CorrectionMemory** (`assistant/assistant/correction_memory.py`, Zeile 45-75)
   - `[OK]` Speichert strukturierte Korrekturen: Original-Aktion + Korrektur + Kontext
   - `[OK]` Cross-Domain-Rules: Korrekturen übertragen sich auf ähnliche Situationen
   - `[OK]` Max 500 Einträge, Rules-Limit pro Tag

7. **FeedbackTracker** (`assistant/assistant/feedback.py`, Zeile 55-81)
   - `[OK]` Trackt Reaktionen: ignoriert/abgelehnt/gelobt
   - `[OK]` Auto-Timeout (120s) für unbeantwortete Notifications
   - `[OK]` Adaptive Cooldowns basierend auf Feedback-Historie

8. **Brain-Integration** (`assistant/assistant/brain.py`, Zeile 2839-2846)
   - `[OK]` "Das Übliche" direkt im Konversationsfluss — bei Confidence ≥0.8 Auto-Execute

**[V2] Zweite Analyse:**

- `[OK]` Keine TODOs/FIXMEs in den analysierten Proactive-Dateien
- `[OK]` Tests: 2325 Zeilen test_anticipation.py (sehr umfangreich!), 631 test_proactive_comprehensive.py
- `[OK]` Quiet Hours in _check_loop: Pattern-Detection wird komplett übersprungen nachts (spart CPU)
- `[OK]` Anti-Spam: Cooldowns, Batching, Feedback-Learning, Correction-Memory
- `[VERBESSERBAR]` Proactive Manager reagiert auf Events, hat aber kein "vorausschauendes" Handeln basierend auf Kalender-Events (z.B. "Meeting in 10 Minuten — soll ich die Webcam-Beleuchtung vorbereiten?")
- `[VERBESSERBAR]` Keine Eskalation bei wiederholtem Ignorieren einer CRITICAL-Warnung — MCU-Jarvis würde insistieren
- `[UNTERVERBUNDEN]` InsightEngine und SeasonalInsight existieren separat, aber die Brücke zum ProactiveManager (aktiv Insights als Notifications ausspielen) könnte stärker sein

### Was fehlt zum MCU-Level

1. **Kalender-basierte Antizipation** — "Du hast in 30 Minuten ein Meeting. Soll ich das Büro vorbereiten?" Kalender-Events sollten proaktive Vorbereitungsvorschläge triggern. `[TÄGLICH]`
2. **Eskalation bei ignorierten kritischen Warnungen** — MCU-Jarvis insistiert bei Gefahr. Der reale Jarvis hat Cooldowns, aber keine Eskalation (1× sagen → 5min warten → nochmal lauter). `[SELTEN]`
3. **Multi-Step proaktive Sequenzen mit Timing** — "Guten Abend. Ich habe die Heizung vorgeheizt, die Lichter auf Kinobeleuchtung gestellt, und der Fernseher läuft bereits." Proactive Planner existiert, aber die orchestrierte Ausführung mit Narration scheint dünn. `[WÖCHENTLICH]`
4. **Kontext-Aware Interrupt-Timing** — MCU-Jarvis unterbricht NICHT wenn Tony konzentriert arbeitet, außer bei Gefahr. Activity-Engine existiert und Silence-Matrix auch, aber die Integration in den ProactiveManager könnte feiner sein (z.B. "User war 2h im Flow — jetzt ist Kaffeepause, passender Moment"). `[TÄGLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Kalender-Trigger für ProactiveManager** — CalendarIntelligence-Events als Trigger für Vorbereitungsvorschläge (Meeting → Büro-Licht, Sport → Wecker-Erinnerung). Verbinde calendar_intelligence.py mit proactive.py.
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

2. **`[ ]` Critical-Eskalation mit steigender Dringlichkeit** — Wenn CRITICAL-Warnung 2× ignoriert wird: Lautstärke +20%, alternative Räume ansprechen, LED-Blink aktivieren. Max 3 Eskalationsstufen.
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

3. **`[ ]` "Guten Abend"-Orchestrierung** — Wenn Ankunft erkannt wird: AnticipationEngine abfragen, Top-3 Aktionen als Sequenz ausführen, mit TTS-Narration zusammenfassen ("Ich habe mir erlaubt...").
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

4. **`[ ]` Flow-State-Detection für Interrupt-Timing** — ActivityEngine um "focused_since" Timestamp erweitern. ProactiveManager wartet mit MEDIUM/LOW Meldungen bis der User eine Pause macht (Bewegungssensor, Türöffnung, Raum-Wechsel).
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

5. **`[ ]` Insight-to-Proactive Bridge** — InsightEngine-Erkenntnisse (Energie-Anomalie, Wetter-Kontrast) direkt als LOW-Priority ProactiveManager-Events einspeisen statt nur passiv abrufbar zu sein.
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Kalender-basierte Vorbereitungsvorschläge erscheinen 10-30min vor Events
- [ ] CRITICAL-Warnungen eskalieren bei Nicht-Beachtung (max 3 Stufen)
- [ ] Ankunfts-Routine führt ≥2 Aktionen als narrated Sequenz aus
- [ ] MEDIUM/LOW Meldungen werden während Focus-Perioden aufgeschoben
- [ ] False-Positive-Rate für proaktive Vorschläge < 20% (gemessen via Feedback)
- [ ] AnticipationEngine erkennt >80% der wiederkehrenden Muster nach 7 Tagen

## 4. Butler-Qualitäten & Servicementalität (×2.5)

### MCU-Jarvis Benchmark
MCU-Jarvis ist der perfekte Butler: diskret, loyal, merkt sich Vorlieben, bietet Hilfe an ohne aufdringlich zu sein, weiß wann er schweigen soll. Er kennt Tonys Routinen, bereitet das Haus vor, verwaltet alles autonom wenn nötig, und hat eine klare Dienstleistungsmentalität — ohne unterwürfig zu sein. Boot-Sequenz: "All systems online, Sir."

### MindHome-Jarvis Status: 80%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **RoutineEngine** (`assistant/assistant/routine_engine.py`, Zeile 46-80, 188-700+)
   - `[OK]` Morning Briefing: 7 Module (Begrüßung, Wetter, Kalender, Hausstatus, Verkehr, Personal Memory, Gerätekonflikte)
   - `[OK]` Weekday/Weekend-Style: "kurz" vs. "ausfuehrlich" — konfigurierbar
   - `[OK]` Good Night Routine: konfigurierbare Trigger ("gute nacht" etc.)
   - `[OK]` Energy Briefing: HA-Sensoren + MindHome-Fallback
   - `[OK]` Personal Memory Briefing: anstehende persönliche Daten (nächste 7 Tage)
   - `[OK]` Device-Conflicts Briefing: Prüft Abhängigkeitsregeln gegen aktuelle States
   - `[OK]` Travel Briefing: HA travel_time Sensoren (Google/Waze/HERE)
   - `[OK]` Vacation Simulation Task vorhanden

2. **Activity Engine / Silence Matrix** (`assistant/assistant/activity.py`, Zeile 54-70, 192-240)
   - `[BESSER ALS MCU]` 7 Aktivitätszustände (SLEEPING, IN_CALL, WATCHING, FOCUSED, GUESTS, RELAXING, AWAY) × 4 Dringlichkeitsstufen (critical, high, medium, low) = 28 Zustellregeln. MCU-Jarvis hat kein explizites Silence-System — er "weiß es einfach". Die formale Matrix ist robuster und konfigurierbarer.
   - `[OK]` Volume-Matrix: Separate Lautstärke-Steuerung pro Aktivität × Dringlichkeit
   - `[OK]` Manueller Override: "Filmabend" → WATCHING für 2 Stunden
   - `[OK]` Config-Validierung: Ungültige Werte werden geloggt und ignoriert
   - `[OK]` CRITICAL immer hörbar — auch bei SLEEPING und IN_CALL ("Leben > Telefonat")

3. **SemanticMemory** (`assistant/assistant/semantic_memory.py`, Zeile 118-148)
   - `[OK]` ChromaDB-basiert: semantische Suche über extrahierte Fakten
   - `[OK]` 9 Kategorien (laut CLAUDE.md): Vorlieben, Gewohnheiten, Gesundheit, Termine etc.
   - `[OK]` Konfidenz-basierte Fakten: nicht alle Fakten gleich sicher

4. **Boot-Sequenz** (`assistant/assistant/main.py`, Zeile 274-328)
   - `[OK]` "Alle Systeme online, Sir." — mit 3 Varianten, zufällig ausgewählt
   - `[OK]` Fallback bei Fehler: vereinfachte Boot-Nachricht
   - `[OK]` TTS-Ausgabe beim Start

5. **FunctionValidator / Pushback** (`assistant/assistant/function_validator.py`, Zeile 32-109)
   - `[OK]` Pre-Execution Sicherheitsprüfung: Trust-Level, Confirmation-Rules
   - `[BESSER ALS MCU]` Pushback-Learning: Wenn User Pushback 3× übergeht → unterdrücke diesen Pushback für 30 Tage. MCU-Jarvis lernt nicht explizit aus übergangenem Widerspruch.
   - `[OK]` Redis-Persistenz für Pushback-Overrides

6. **AutonomyManager** (`assistant/assistant/autonomy.py`, Zeile 29-121)
   - `[OK]` 5 Autonomie-Level (1=Assistent → 5=Autopilot)
   - `[OK]` 7 Domains (climate, light, media, cover, security, automation, notification)
   - `[OK]` Per-Person Trust-Levels mit Guest-Restrictions
   - `[OK]` Security-Actions: Schlösser, Alarm nur bei hohem Trust

7. **ConflictResolver** (`assistant/assistant/conflict_resolver.py`, Zeile 103-286)
   - `[OK]` Multi-User Konflikt-Erkennung: wenn Person A und B innerhalb 300s widersprüchliche Befehle geben
   - `[OK]` Trust-Priority: höherer Trust gewinnt
   - `[OK]` LLM-basierte Mediation bei unklaren Konflikten
   - `[OK]` Resolution-Cooldown (120s) verhindert Mediation-Spam

8. **WellnessAdvisor** (`assistant/assistant/wellness_advisor.py`)
   - `[OK]` PC-Pausen, Stress-Intervention, Mahlzeiten-Erinnerungen, Late-Night-Hinweise, Hydration
   - `[OK]` Fusioniert Activity Engine, Mood Detector, Health Monitor

9. **Core Identity** (`assistant/assistant/core_identity.py`, Zeile 15-40)
   - `[OK]` Loyalität, Ehrlichkeit, Diskretion als unveränderliche Werte
   - `[OK]` "Respektvoll aber nie unterwürfig — ein Partner, kein Diener"
   - `[OK]` "Subtile Fürsorge — nie aufdringlich, immer aufmerksam"

**[V2] Zweite Analyse:**

- `[OK]` Tests: 1220 Zeilen test_routine_engine.py, 887 test_activity.py — gut abgedeckt
- `[OK]` Keine TODOs/FIXMEs in den Butler-bezogenen Dateien
- `[VERBESSERBAR]` Morning Briefing ist modular, aber die Reihenfolge ist fest konfiguriert. MCU-Jarvis priorisiert dynamisch — "das Wichtigste zuerst" (z.B. Sicherheitswarnung vor Wetter)
- `[VERBESSERBAR]` "Das Übliche" ist gut implementiert, aber nur für Geräte-Aktionen. Es fehlt: "Das Übliche zum Frühstück" (→ Kaffee-Maschine + Radio + Licht), "Das Übliche wenn ich heimkomme" (→ komplexe Multi-Domain-Sequenz)
- `[UNTERVERBUNDEN]` Vacation-Simulation existiert als Task, aber die Integration (automatische Aktivierung bei langer Abwesenheit, Benachrichtigung der Nachbarn) scheint manuell ausgelöst
- `[VERBESSERBAR]` Kein "Besucher-Modus" der automatisch Diskretion erhöht (z.B. keine persönlichen Infos aussprechen wenn Gäste erkannt werden), obwohl GUESTS in der Activity-Engine existiert

### Was fehlt zum MCU-Level

1. **Dynamische Briefing-Priorisierung** — Wichtigstes zuerst. Sicherheitswarnungen vor Wetter, Termine vor Energy-Report. Aktuell feste Reihenfolge. `[TÄGLICH]`
2. **Multi-Domain "Das Übliche"** — Komplexe Routine-Sequenzen ("Das Übliche für den Feierabend" → Licht dimmen + Musik an + Heizung hoch + Rollläden runter). Aktuell nur Einzel-Aktionen. `[TÄGLICH]`
3. **Gäste-Modus Diskretion** — Wenn Activity = GUESTS: keine persönlichen Infos laut aussprechen, keine Gesundheits-Hinweise, reduzierte Proaktivität. `[WÖCHENTLICH]`
4. **Proaktive Vacation-Erkennung** — Wenn >48h niemand zuhause: automatisch Vacation-Modus vorschlagen (Licht-Simulation, Post-Warnung, Heizung-Absenkung). `[SELTEN]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Briefing-Priorisierung** — In `routine_engine.py`: Sortiere Briefing-Module nach Dringlichkeit statt fester Reihenfolge. Sicherheit > Kalender-Urgent > Wetter-Warnung > Rest. Urgency-Score pro Modul.
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

2. **`[ ]` Multi-Action "Das Übliche" in brain.py** — Erweitere `_handle_das_uebliche` um Multi-Action-Support: AnticipationEngine soll die Top-3 Aktionen für den Zeitslot als Sequenz zurückgeben statt nur die beste. Mit TTS-Narration ("Ich erlaube mir: Licht auf 40%, Heizung auf 22°, und den Fernseher vorzubereiten.").
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

3. **`[ ]` Guest-Discretion-Mode** — Wenn ActivityEngine GUESTS erkennt: Flag an PersonalityEngine → keine persönlichen Fakten im TTS, keine Gesundheitshinweise, generischere Anrede. ProactiveManager auf HIGH/CRITICAL beschränken.
   - Aufwand: Mittel
   - Impact: +2%
   - Alltag: `[WÖCHENTLICH]`

4. **`[ ]` Vacation-Auto-Detection** — In ProactiveManager: Wenn `is_anyone_home() == False` für >48h → LOW-Notification "Soll ich den Urlaubsmodus aktivieren?" mit Erklärung was das bedeutet.
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

5. **`[ ]` Ankunfts-Begrüßung mit Haus-Zusammenfassung** — Bei erkannter Ankunft nach >4h Abwesenheit: "Willkommen zurück, Sir. Während du weg warst: Die Waschmaschine ist fertig, der Paketdienst war da, und im Bad sind es aktuell 19 Grad." Verbinde ProactiveManager mit RoutineEngine.
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Morning Briefing priorisiert dynamisch — Sicherheitswarnungen immer zuerst
- [ ] "Das Übliche" führt ≥3 Aktionen als narrated Sequenz aus
- [ ] Guest-Mode unterdrückt persönliche Informationen in TTS-Ausgabe
- [ ] Ankunfts-Begrüßung nach >4h Abwesenheit fasst relevante Events zusammen
- [ ] Pushback-Learning funktioniert: nach 3× Override wird Pushback für 30 Tage unterdrückt
- [ ] Autonomie-Level spürbar: Level 3 führt Routine-Aktionen eigenständig aus, Level 1 fragt immer

---

## Zwischenergebnis Session 1

### Scores (4 von 12 Kategorien)

| # | Kategorie | Gewicht | Score | Gewichtet |
|---|-----------|---------|-------|-----------|
| 1 | Natürliche Konversation & Sprachverständnis | ×3 | 72% | 216 |
| 2 | Persönlichkeit, Sarkasmus & Humor | ×3 | 78% | 234 |
| 3 | Proaktives Handeln & Antizipation | ×2.5 | 76% | 190 |
| 4 | Butler-Qualitäten & Servicementalität | ×2.5 | 80% | 200 |
| | **Teilsumme (Kat. 1-4)** | **11** | | **840** |
| | **Teildurchschnitt** | | **76.4%** | |

*Hinweis: Endgültiger Gesamt-Score erst nach Session 5 (alle 12 Kategorien).*

### Aufgaben-Zusammenfassung

| Kategorie | Offen | Teilweise | Erledigt | Gesamt |
|-----------|-------|-----------|----------|--------|
| 1. Konversation | 5 | 0 | 0 | 5 |
| 2. Persönlichkeit | 4 | 0 | 0 | 4 |
| 3. Proaktivität | 5 | 0 | 0 | 5 |
| 4. Butler-Qualitäten | 5 | 0 | 0 | 5 |
| **Gesamt** | **19** | **0** | **0** | **19** |

---

## Changelog

### Durchlauf #1 — Session 1 — 2026-03-22
- 0 Aufgaben als erledigt markiert (Erstanalyse)
- 19 neue Aufgaben hinzugefügt
- 0 Zeilenreferenzen aktualisiert
- Kategorien 1-4 Score: **76.4%** (Erstbewertung)
- Besonders stark: Butler-Qualitäten (80%) — Silence Matrix, Pushback-Learning, Autonomie-System
- Besonders schwach: Konversation (72%) — fehlende Antwort-Varianz und natürliche Pausen
- 5 Features als `[BESSER ALS MCU]` identifiziert und in Schutzliste aufgenommen
