# J.A.R.V.I.S. MCU-Level Implementation Plan
> Erstellt am 2026-03-22 | Letzter Durchlauf: Session 4 am 2026-03-22
> Aktueller Stand: 78.0% (FINAL — alle 12 Kategorien analysiert)
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
| 2       | 2026-03-22 | 5-9 (×2/×1.5) | 16 |
| 3       | 2026-03-22 | 10-12 (×1) | 8 |
| 4       | 2026-03-22 | Roadmap & Sprints | 43 (5 Sprints) |

## Schutzliste — Besser als MCU (NICHT beschädigen!)

1. **Cross-Session temporale Referenzierung** (`dialogue_state.py`, Zeile 324-450) — "Wie gestern", "wie am Montag" mit Redis Action-Log. MCU-Jarvis zeigt keine vergleichbare explizite temporale Rückreferenzierung.
2. **STT-Korrektursystem** (`brain.py`, Zeile 12122+) — 95+ deutsche Wortkorrekturen + Phrase-Korrekturen, pre-compiled Regex, YAML-Overrides. MCU-Jarvis hat kein STT.
3. **Contextual Humor Triggers** (`personality.py`, Zeile 109+) — Situations-basierte Kommentare nach Geräte-Aktionen. Systematischer als MCU-Jarvis' Ad-hoc-Humor.
4. **Formality-Decay / Character Evolution** (`personality.py`, Zeile 342-346, 2505-2513) — Dynamische Beziehungsentwicklung über Zeit. MCU-Jarvis bleibt konstant.
5. **Silence Matrix** (`activity.py`, Zeile 54-70) — 7×4 Zustellregel-Matrix. Formaler und robuster als MCU-Jarvis' intuitives Schweigen.
6. **Pushback-Learning** (`function_validator.py`, Zeile 77-109) — Lernt aus übergangenem Widerspruch. MCU-Jarvis passt sich nicht explizit an überstimmte Einwände an.
7. **predict_future_needs()** (`anticipation.py`, Zeile 1798+) — 7-14 Tage Vorausschau. MCU-Jarvis denkt nicht so weit voraus.
8. **154 Prompt-Injection-Patterns** (`context_builder.py`, Zeile 48-195) — Enterprise-grade LLM-Sicherheit. MCU-Jarvis hat kein LLM-Sicherheitsproblem.
9. **16 Cross-Reference-Insights** (`insight_engine.py`) — Systematische Korrelation von 3-5 Datenquellen pro Check. MCU-Jarvis korreliert intuitiv, nicht systematisch.
10. **7-Layer SSRF-Schutz** (`web_search.py`) — DNS-Rebinding, Redirect-Blocking, Pinned-Resolver. MCU-Jarvis hat keine Web-Sicherheitsprobleme.
11. **Systematische Graceful Degradation** (`brain.py`, `_safe_init()`) — Pro-Modul Failure-Tracking mit strukturiertem Degraded Mode. MCU-Jarvis degradiert intuitiv.
12. **Systematische Fakten-Contradiction-Detection** (`semantic_memory.py`, Zeile 391+) — 2-Pass Widerspruchserkennung mit LLM-Validation. MCU-Jarvis merkt sich implizit.
13. **Adaptive Sarkasmus-Learning** (`personality.py`) — Feedback-Loop alle 20 Interaktionen, 90-Tage Redis-Persistenz. MCU-Jarvis' Humor ist statisch.
14. **50+ Function-Calling-Functions** (`function_calling.py`, 10037 Zeilen) — Systematische HA-Steuerung mit Safety-Caps und Validation. MCU-Jarvis hat keine sichtbare Funktionsarchitektur.
15. **213 Device-Dependency-Rules** (`state_change_log.py`, 9927 Zeilen) — Strukturierte Konflikterkennung mit Source-Attribution. MCU-Jarvis protokolliert keine Änderungen strukturiert.

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

*(Siehe aktualisiertes Zwischenergebnis Session 1+2 weiter unten)*

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

### Durchlauf #2 — Session 2 — 2026-03-22
- 0 Aufgaben als erledigt markiert
- 16 neue Aufgaben hinzugefügt (Kategorien 5-9)
- 0 Zeilenreferenzen aktualisiert
- Kategorien 5-9 Score: Cat5=82%, Cat6=81%, Cat7=74%, Cat8=78%, Cat9=85%
- Gesamtscore: **76.4% → 78.0%** (9 von 12 Kategorien)
- Besonders stark: Sicherheit (85%) — 154 Injection-Patterns, 7-Layer SSRF, Immutable Core
- Besonders schwach: Sprecherkennung (74%) — default deaktiviert, kein Auto-Enrollment
- 6 neue Features als `[BESSER ALS MCU]` identifiziert (Schutzliste #8-#13)

### Durchlauf #3 — Session 3 — 2026-03-22
- 0 Aufgaben als erledigt markiert
- 8 neue Aufgaben hinzugefügt (Kategorien 10-12)
- 0 Zeilenreferenzen aktualisiert
- Kategorien 10-12 Score: Cat10=73%, Cat11=84%, Cat12=77%
- **FINAL Gesamt-Score: 78.0%** (alle 12 Kategorien analysiert)
- Besonders stark: Energiemanagement (84%) — 50+ Functions, 213 Dependency-Rules, Solar+Preis-Awareness
- Besonders schwach: Multi-Room (73%) — Follow-Me default deaktiviert, kein Audio-Crossfade
- 2 neue Features als `[BESSER ALS MCU]` identifiziert (Schutzliste #14-#15)
- **Gesamtbilanz:** 15 Features "Besser als MCU", 43 Verbesserungsaufgaben, alle 12 Kategorien vollständig analysiert

### Durchlauf #4 — Session 4 — 2026-03-22
- 0 Aufgaben als erledigt markiert (Roadmap-Erstellung, keine Code-Änderungen)
- 43 Aufgaben in 5 Sprints organisiert mit Abhängigkeitsgraph
- Implementierungsanweisungen für jede Aufgabe mit Code-Referenzen
- Quick-Wins identifiziert (Top-10 nach Impact/Aufwand)
- Kritischer Pfad zum ≥90% Score definiert
- Ziel-Score nach Umsetzung: **78.0% → ~87-94%**
- Empfehlung: Sprint 1 (7 Quick Wins) sofort starten

---

## Roadmap & Sprint-Plan

### Abhängigkeitsgraph

```
[Speaker Recognition default on] ──→ [Auto-Enrollment] ──→ [Confidence Fallback Chain]
[Briefing-Priorisierung] (unabhängig)
[Follow-Me default on] (unabhängig)
[Streaming-Feedback] ──→ [Natürliche Denkpausen]
[Response-Varianz] (unabhängig)
[Insight-to-Proactive Bridge] ──→ [Kalender-Trigger] ──→ [Flow-State-Detection]
[Ankunfts-Begrüßung] ──→ [Multi-Action "Das Übliche"]
[Contextual Humor erweitern] ──→ [Humor Quality Gate] ──→ [Running Gag Tracker]
[Guest-Discretion-Mode] ──→ [Vacation-Auto-Detection]
[Security Audit Log] ──→ [API-Access Anomalie]
[Multi-Krisen-Priorisierung] ──→ [Externe Eskalationskette]
["Warum?"-Intent] ──→ [Degraded-Mode-Notification] ──→ [Confidence-Hints]
[Contradiction Confirmation] ──→ [Proaktive Wissenslücken]
[Per-Person Room Tracking] ──→ [Konversations-Kontext Raumwechsel]
```

### Sprint-Übersicht

| Sprint | Thema | Aufgaben | Impact (gewichtet) | Aufwand |
|--------|-------|----------|-------------------|---------|
| 1 | Quick Wins — Config & Defaults | 7 | +3.6% Gesamt | Klein |
| 2 | Konversation & Persönlichkeit (×3) | 9 | +4.8% Gesamt | Mittel |
| 3 | Proaktivität & Butler (×2.5) | 10 | +3.8% Gesamt | Mittel |
| 4 | Lernen, Sicherheit & Tiefe | 10 | +2.4% Gesamt | Mittel-Groß |
| 5 | Infrastruktur & Langzeit | 7 | +1.4% Gesamt | Groß |

**Ziel-Score nach Umsetzung: ~94%** (von 78.0%)

### Sprint 1: Quick Wins — Config & Defaults
**Status:** `[ ]` Offen
**Ziel:** Maximaler Impact mit minimalen Code-Änderungen. Aktiviere vorhandene Features, setze bessere Defaults.
**Vorher → Nachher:** 78.0% → ~81.6% (Ziel)
**Betroffene Dateien:** `speaker_recognition.py`, `follow_me.py`, `routine_engine.py`, `pre_classifier.py`, `explainability.py`, `personality.py`, `proactive.py`

#### Aufgabe 1.1: Speaker Recognition default aktivieren
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/speaker_recognition.py`, Zeile 121
- **Ist:** `self.enabled = sr_cfg.get("enabled", False)` — Default deaktiviert
- **Soll:** `self.enabled = sr_cfg.get("enabled", True)` — Default aktiviert (nur Device-Mapping, kein Hardware nötig)
- **Risiko:** Gering — ohne `device_mapping` Config passiert nichts, System fällt auf "unknown" zurück
- **Akzeptanz:** `[ ]` Speaker-Recognition aktiv ohne manuelle Config-Änderung

#### Aufgabe 1.2: Follow-Me default aktivieren
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/follow_me.py`, Zeile 41
- **Ist:** `self.enabled = cfg.get("enabled", False)` — Default deaktiviert
- **Soll:** `self.enabled = cfg.get("enabled", True)` — Default aktiviert
- **Risiko:** Gering — ohne `room_motion_sensors` Config passiert nichts
- **Akzeptanz:** `[ ]` Follow-Me aktiv ohne manuelle Config-Änderung

#### Aufgabe 1.3: Briefing-Priorisierung
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/routine_engine.py`, Methode `generate_morning_briefing()`
- **Ist:** Feste Reihenfolge der Briefing-Module (greeting, weather, calendar, house_status, travel, personal_memory, device_conflicts)
- **Soll:** Sortiere Module nach Urgency-Score: Sicherheits-Alerts (conflicts) zuerst, dann Kalender-Urgent, dann Wetter-Warnungen, dann Rest. Füge `_get_module_urgency(module, data)` Methode hinzu die 0-10 Score zurückgibt.
- **Akzeptanz:** `[ ]` Sicherheitswarnungen erscheinen im Briefing VOR Wetter

#### Aufgabe 1.4: "Warum?"-Intent im PreClassifier
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/pre_classifier.py`, Methode `classify()`
- **Ist:** "Warum hast du das gemacht?" wird als GENERAL klassifiziert → volles LLM-Processing
- **Soll:** Neues `PROFILE_EXPLAIN` hinzufügen. Detect "warum", "wieso", "weshalb" am Satzanfang + Bezug auf Jarvis-Aktion. Route direkt zu ExplainabilityEngine statt ans LLM.
- **Akzeptanz:** `[ ]` "Warum?"-Fragen werden in <500ms beantwortet (kein LLM nötig)

#### Aufgabe 1.5: Insight-to-Proactive Bridge
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/insight_engine.py`, Methode nach `_insight_loop()`
- **Ist:** Insights werden nur über Callback an Brain gemeldet, nicht als ProactiveManager-Events
- **Soll:** In `_insight_loop()`: Wenn Insight gefunden, zusätzlich als `LOW`-Priority Event an ProactiveManager senden (via `brain.proactive.queue_event()`). Nutze bestehenden Callback-Mechanismus.
- **Akzeptanz:** `[ ]` Insights erscheinen im Proactive-Batch (z.B. im Abend-Zusammenfassung)

#### Aufgabe 1.6: Degraded-Mode-Notification
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/brain.py`, nach `_safe_init()` Block (ca. Zeile 1550)
- **Ist:** `_degraded_modules` wird geloggt aber User wird nicht informiert
- **Soll:** Wenn `_degraded_modules` nicht leer: beim ersten User-Request einen einmaligen Hinweis geben: "Hinweis: {module} ist gerade nicht verfügbar. Ich arbeite mit eingeschränkter Funktionalität."
- **Akzeptanz:** `[ ]` User wird über ausgefallene Module informiert (1× nach Boot)

#### Aufgabe 1.7: Confidence-Hints in Antworten
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/personality.py`, Methode `build_system_prompt()`
- **Ist:** Confidence nicht im Prompt
- **Soll:** Wenn ExplainabilityEngine `confidence_display: true` UND letzte Aktion Confidence <0.7: Füge Prompt-Hint hinzu: "Bei unsicheren Aussagen: Sage 'Ich bin mir nicht ganz sicher, aber...' statt absolute Aussagen."
- **Akzeptanz:** `[ ]` Bei unsicheren Antworten wird Unsicherheit natürlich kommuniziert

### Sprint 1 — Validierung
- [ ] Alle 7 Aufgaben abgeschlossen
- [ ] `cd assistant && python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Kein Breaking Change an bestehenden APIs
- [ ] Schutzliste geprüft — keine "Besser als MCU" Features beschädigt

### Sprint 2: Konversation & Persönlichkeit (×3 Kategorien)
**Status:** `[ ]` Offen
**Ziel:** Größter Impact — die beiden ×3-Kategorien (Konversation 72%, Persönlichkeit 78%) auf 85%+ heben.
**Vorher → Nachher:** Cat1: 72%→85%, Cat2: 78%→88%
**Betroffene Dateien:** `personality.py`, `tts_enhancer.py`, `dialogue_state.py`, `brain.py`, `conversation_memory.py`

#### Aufgabe 2.1: Response-Varianz-Engine
**Status:** `[ ]` | **Priorität:** Kritisch | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/personality.py`
- **Ist:** Antworten haben Mood-Styles und Humor-Templates, aber keine systematische Struktur-Variation
- **Soll:** Tracke letzte 5 Antwort-Strukturen in Redis (`mha:personality:response_patterns`). Vor dem System-Prompt: prüfe dominante Struktur, füge Variation-Hint hinzu ("Letzte 3 Antworten waren Bestätigungen — variiere: Frage, Kommentar, oder Aktion-zuerst").
- **Implementierung:** Neue Methode `_get_variation_hint()` in PersonalityEngine. Aufrufen in `build_system_prompt()` nach der Humor-Section.
- **Akzeptanz:** `[ ]` Keine 2 aufeinanderfolgenden Antworten haben dieselbe Satzstruktur

#### Aufgabe 2.2: Natürliche Denkpausen in TTS
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/tts_enhancer.py`, Methode `enhance()`
- **Ist:** TTS-Text wird direkt ausgegeben, keine Filler
- **Soll:** Bei `message_type != "confirmation"` und Textlänge >100 Zeichen: optional Filler-Prefix ("Moment...", "Mal sehen...", "Lass mich kurz prüfen...") mit 500ms Pause (SSML `<break>`). Nur bei Voice-Interaktion, max 1 Filler pro 3 Antworten.
- **Akzeptanz:** `[ ]` Bei komplexen Antworten: Antwort-Beginn <1s (Filler), vollständige Antwort <3s

#### Aufgabe 2.3: Topic-Switch-Detection
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/dialogue_state.py`, Methode `track_turn()`
- **Ist:** Kein Detection wenn User abrupt Thema wechselt
- **Soll:** Vergleiche aktuellen Turn-Text mit letztem via einfaches Keyword-Overlap (Jaccard-Similarity auf Wortebene). Overlap <0.1 UND kein Referenz-Wort ("es", "das") → `state.reset()` aufrufen. Logge als "topic_switch".
- **Akzeptanz:** `[ ]` Abrupter Themenwechsel wird in >90% korrekt erkannt

#### Aufgabe 2.4: Streaming-Feedback bei langen Anfragen
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/brain.py`, Methode `_process_inner()`
- **Ist:** User wartet bis LLM-Antwort komplett ist
- **Soll:** Wenn `stream_callback` vorhanden UND Profile != DEVICE_FAST: sofort "Ich prüfe das, {title}." via TTS aussprechen (fire-and-forget), dann normal weiterverarbeiten. Nur wenn LLM-Latenz erwartet >2s (Smart/Deep Modell).
- **Akzeptanz:** `[ ]` Gefühlte Latenz <1s bei Voice-Interaktion

#### Aufgabe 2.5: Aktive Follow-Up-Erinnerungen
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/conversation_memory.py` + `proactive.py`
- **Ist:** Follow-ups werden gespeichert aber nicht proaktiv erinnert
- **Soll:** In ProactiveManager `_check_loop()`: alle 2h `conversation_memory.get_pending_followups()` abfragen. Fällige Follow-ups als MEDIUM-Priority Event senden: "Du wolltest gestern noch {topic} erledigen."
- **Akzeptanz:** `[ ]` Follow-up-Erinnerungen erscheinen innerhalb von 24h

#### Aufgabe 2.6: Contextual Humor Triggers erweitern
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/personality.py`, `CONTEXTUAL_HUMOR_TRIGGERS` Dict
- **Ist:** ~10 Situationen mit Humor-Templates
- **Soll:** Erweitern auf 30+: Wiederholte Anfragen ("Schon wieder, {title}?"), widersprüchliche Befehle ("Erst an, dann aus?"), ungewöhnliche Uhrzeiten ("Um 3 Uhr? Ambitioniert."), Wetter-Kontraste ("Heizung bei 28° Außentemperatur?"), Rekorde ("Das ist der 10. Lichtbefehl heute.").
- **Akzeptanz:** `[ ]` 30+ kontextuelle Humor-Trigger definiert

#### Aufgabe 2.7: Humor Quality Gate
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/personality.py`, nach LLM-Response-Processing in `brain.py`
- **Ist:** Kein Post-LLM Quality-Check für Humor
- **Soll:** Bei Sarkasmus-Level ≥3 und Fast-Modell: prüfe ob Antwort mindestens ein Humor-Pattern enthält (trockener Einzeiler, Understatement). Blocke Emoji-Humor, Kalauer, "Haha"-Patterns. Regex-basierter Filter.
- **Akzeptanz:** `[ ]` Humor-Qualität konsistent auch bei Fast-Modellen

#### Aufgabe 2.8: Running Gag Tracker
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/personality.py`
- **Ist:** Running Gags nur in Memory (verloren bei Restart)
- **Soll:** Redis-basierter Tracker: `mha:personality:running_gags` (Hash). Speichere Gag-ID → {count, last_used, evolution_stage}. Max 1 Running Gag pro 3 Tage. Bei count >3: eskaliere Formulierung.
- **Akzeptanz:** `[ ]` Running Gags überleben Neustarts und entwickeln sich

#### Aufgabe 2.9: Meinungs-Engine mit Fact-Base
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Groß
- **Datei:** `assistant/assistant/personality.py` + `semantic_memory.py`
- **Ist:** `opinion_intensity` ist Prompt-Parameter, keine Fakten-Basis
- **Soll:** Nutze SemanticMemory Kategorie "general" für "Jarvis-Meinungen". Wenn Entity 5× in negativem Kontext erwähnt → speichere Meinung. In `check_opinion()`: zusätzlich SemanticMemory abfragen für gelernte Meinungen.
- **Akzeptanz:** `[ ]` Jarvis hat zu mindestens 5 Haus-Themen eigene Meinung

### Sprint 2 — Validierung
- [ ] Alle 9 Aufgaben abgeschlossen
- [ ] `cd assistant && python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Kein Breaking Change
- [ ] Schutzliste geprüft — Contextual Humor Triggers (#3) und Sarkasmus-Learning (#13) nicht beschädigt

### Sprint 3: Proaktivität & Butler-Qualitäten (×2.5 Kategorien)
**Status:** `[ ]` Offen
**Ziel:** Die ×2.5-Kategorien (Proaktivität 76%, Butler 80%) auf 85%+ heben.
**Vorher → Nachher:** Cat3: 76%→86%, Cat4: 80%→89%
**Betroffene Dateien:** `proactive.py`, `brain.py`, `anticipation.py`, `activity.py`, `routine_engine.py`, `personality.py`

#### Aufgabe 3.1: Kalender-Trigger für ProactiveManager
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/proactive.py` + `calendar_intelligence.py`
- **Ist:** ProactiveManager reagiert auf HA-Events, nicht auf Kalender-Events
- **Soll:** In `_check_loop()`: alle 15min `calendar_intelligence.get_upcoming_events(30)` abfragen. Für Events in 10-30min: MEDIUM-Priority Vorbereitungsvorschlag ("Meeting in 20 Min — Büro-Licht vorbereiten?").
- **Akzeptanz:** `[ ]` Kalender-basierte Vorbereitungsvorschläge 10-30min vor Events

#### Aufgabe 3.2: "Guten Abend"-Orchestrierung / Ankunfts-Begrüßung
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/brain.py` + `routine_engine.py` + `anticipation.py`
- **Ist:** Ankunft wird erkannt, aber keine orchestrierte Sequenz
- **Soll:** Bei `person_arrived` Event + >4h Abwesenheit: 1) AnticipationEngine Top-3 Aktionen abfragen, 2) Sequentiell ausführen, 3) TTS-Narration: "Willkommen zurück, {title}. Ich habe mir erlaubt: {aktion1}, {aktion2}. Während du weg warst: {events}."
- **Akzeptanz:** `[ ]` Ankunfts-Begrüßung nach >4h mit ≥2 Aktionen und Zusammenfassung

#### Aufgabe 3.3: Multi-Action "Das Übliche"
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/brain.py`, Methode `_handle_das_uebliche()` (Zeile 14386+)
- **Ist:** Führt nur die beste (einzelne) Suggestion aus
- **Soll:** `anticipation.get_suggestions()` mit `limit=3` aufrufen. Alle 3 mit Confidence ≥0.7 als Sequenz ausführen. TTS: "Wie gewohnt, {title}: {aktion1}, {aktion2}, und {aktion3}."
- **Akzeptanz:** `[ ]` "Das Übliche" führt ≥2 Aktionen als narrated Sequenz aus

#### Aufgabe 3.4: Flow-State-Detection für Interrupt-Timing
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/activity.py`, Klasse `ActivityEngine`
- **Ist:** FOCUSED-State erkannt, aber kein `focused_since` Timestamp
- **Soll:** Erweitere ActivityEngine um `_focused_since: Optional[datetime]`. Setze bei Wechsel zu FOCUSED. ProactiveManager: wenn FOCUSED seit >30min → MEDIUM/LOW Meldungen aufstauen bis Pause (Motion in anderem Raum, Türöffnung).
- **Akzeptanz:** `[ ]` MEDIUM/LOW Meldungen werden während Focus-Perioden aufgeschoben

#### Aufgabe 3.5: Guest-Discretion-Mode
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/personality.py` + `activity.py` + `proactive.py`
- **Ist:** GUESTS Activity-State existiert, aber keine Auswirkung auf Persönlichkeit
- **Soll:** Wenn Activity=GUESTS: 1) PersonalityEngine: keine persönlichen Fakten im Prompt, 2) ProactiveManager: nur HIGH/CRITICAL, 3) TTS: generischere Anrede. Neues Flag `_guest_mode_active` in PersonalityEngine.
- **Akzeptanz:** `[ ]` Im Gäste-Modus keine persönlichen Infos per TTS

#### Aufgabe 3.6: Vacation-Auto-Detection
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Klein
- **Datei:** `assistant/assistant/proactive.py`
- **Ist:** Vacation-Modus nur manuell aktivierbar
- **Soll:** In `_check_loop()`: Wenn `is_anyone_home() == False` für >48h (Redis-Timestamp): LOW-Notification "Soll ich den Urlaubsmodus aktivieren?" Max 1× pro 7 Tage.
- **Akzeptanz:** `[ ]` Nach >48h Abwesenheit: automatischer Urlaubsmodus-Vorschlag

#### Aufgabe 3.7: Critical-Eskalation mit steigender Dringlichkeit
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/proactive.py`, Methode `_send_critical_with_retry()`
- **Ist:** Retry mit fester Lautstärke-Steigerung (0.7→1.0), 30s Intervall
- **Soll:** Zusätzlich: nach 2. Retry → alternative Räume ansprechen (alle Speakers). Nach 3. Retry → LED-Blink in allen Räumen aktivieren (via `light.turn_on` mit Flash-Effekt).
- **Akzeptanz:** `[ ]` CRITICAL-Warnungen erreichen alle Räume nach 2 ignorierten Versuchen

#### Aufgabe 3.8: Post-Crisis Debrief
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Klein
- **Datei:** `assistant/assistant/threat_assessment.py`
- **Ist:** Kein Debrief nach Entwarnung
- **Soll:** Nach `execute_playbook()` Abschluss: sammle Dauer, ausgeführte Steps, Ergebnis. Sende MEDIUM-Notification: "Entwarnung: {event_type} nach {duration}min. Alle Systeme normal. Vorfall dokumentiert."
- **Akzeptanz:** `[ ]` Nach jeder Krise automatisches Debrief mit Zusammenfassung

#### Aufgabe 3.9: Multi-Krisen-Priorisierung
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/threat_assessment.py`, Methode `assess_threats()`
- **Ist:** Threats werden als Liste zurückgegeben, keine Sortierung
- **Soll:** Sortiere Threats nach Lebensbedrohung: `_THREAT_PRIORITY = {"smoke_fire": 0, "carbon_monoxide": 0, "medical": 1, "break_in": 2, "water_leak": 3, "power_outage": 4}`. Führe höchste Priorität zuerst aus.
- **Akzeptanz:** `[ ]` Bei Multi-Krisen: Feuer/CO wird vor Einbruch/Wasser behandelt

#### Aufgabe 3.10: Externe Eskalationskette
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/threat_assessment.py`
- **Ist:** Benachrichtigung nur über HA-Notify (Push)
- **Soll:** Neuer Config-Block `emergency_contacts: [{name, ha_notify_target, delay_minutes}]`. Nach N Minuten ohne ACK: nächsten Kontakt benachrichtigen. Optional: Nachricht enthält Adresse + Situationsbeschreibung.
- **Akzeptanz:** `[ ]` Nach 2min ohne Reaktion: automatisch Notfall-Kontakt benachrichtigt

### Sprint 3 — Validierung
- [ ] Alle 10 Aufgaben abgeschlossen
- [ ] `cd assistant && python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Schutzliste geprüft — Silence Matrix (#5), Pushback-Learning (#6), predict_future_needs (#7) nicht beschädigt

### Sprint 4: Lernen, Sicherheit & Sprecherkennung
**Status:** `[ ]` Offen
**Ziel:** Kategorien 6-9 polieren. Lernsystem vertiefen, Security härten, Speaker verbessern.
**Vorher → Nachher:** Cat6: 81%→88%, Cat7: 74%→85%, Cat8: 78%→85%, Cat9: 85%→91%
**Betroffene Dateien:** `semantic_memory.py`, `speaker_recognition.py`, `threat_assessment.py`, `function_validator.py`, `proactive.py`

#### Aufgabe 4.1: Proaktive Wissenslücken-Erkennung
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/semantic_memory.py` + `proactive.py`
- **Soll:** Neue Methode `get_knowledge_gaps(room)` in SemanticMemory: prüfe ob für einen Raum <2 Präferenz-Fakten existieren. ProactiveManager: max 1×/Woche/Raum als LOW-Event: "Wie warm magst du es im {room}?"
- **Akzeptanz:** `[ ]` Wissenslücken-Fragen max 1/Woche/Raum

#### Aufgabe 4.2: Contradiction Confirmation
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/semantic_memory.py`, Methode `store_fact()`
- **Ist:** Bei Widerspruch → neuerer Fakt gewinnt automatisch
- **Soll:** Wenn `_check_contradiction()` True: Speichere neuen Fakt als "pending". In ProactiveManager: MEDIUM-Event "Du sagtest letztens {old}, jetzt {new} — soll ich aktualisieren?" Bei Bestätigung → confirm, bei Ablehnung → discard.
- **Akzeptanz:** `[ ]` Widersprüchliche Fakten werden dem User vorgelegt

#### Aufgabe 4.3: Langzeit-Lernbericht
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/semantic_memory.py` + `routine_engine.py`
- **Soll:** Neue Methode `generate_learning_report(days=90)`: Sammle Fakten der letzten N Tage, gruppiere nach Kategorie, identifiziere Trends (z.B. "Aufstehzeit 15min früher"). Monatlich als LOW-Event via ProactiveManager.
- **Akzeptanz:** `[ ]` Monatlicher Lernbericht mit ≥3 erkannten Trends

#### Aufgabe 4.4: Auto-Enrollment für neue Stimmen
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/speaker_recognition.py`, Methode `resolve_fallback_answer()`
- **Ist:** Unbekannter Sprecher → Rückfrage → Name gespeichert, aber kein Voice-Embedding
- **Soll:** Nach erfolgreicher `resolve_fallback_answer()`: automatisch `learn_embedding_from_audio()` aufrufen mit dem cached Embedding. So wird die Stimme beim nächsten Mal erkannt.
- **Akzeptanz:** `[ ]` Neue Personen per Sprache registrierbar (1 Interaktion)

#### Aufgabe 4.5: Confidence-basiertes Fallback-Chain
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Klein
- **Datei:** `assistant/assistant/speaker_recognition.py`, Methode `identify()`
- **Ist:** Confidence <0.7 → sofort Fallback-Ask
- **Soll:** Wenn Confidence 0.5-0.7: nutze Raum+Zeit-Kontext zur Bestätigung. "Das klingt nach {person} — bist du das?" Nur bei Voice-Confidence 0.5-0.7, nicht bei Device-Mapping.
- **Akzeptanz:** `[ ]` Soft-Confirmation bei mittlerer Confidence statt direkter Rückfrage

#### Aufgabe 4.6: Security Audit Log
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/assistant/function_validator.py` oder neues `security_audit.py`
- **Soll:** Bei jeder Security-Action (lock/unlock/arm/disarm/trust_change): Redis-Log `mha:security:audit` (List, max 500, 90-Tage TTL). Format: `{action, person, result, timestamp, entity}`.
- **Akzeptanz:** `[ ]` Alle Security-Actions in Audit-Log mit 90 Tage Retention

#### Aufgabe 4.7: API-Access Anomalie-Detection
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/main.py` (FastAPI Middleware)
- **Soll:** Tracke API-Zugriffsmuster in Redis: `mha:api:access:{hour}` (Counter). Bei 3× falschem Token oder Zugriff 2-5 Uhr von unbekannter Source: LOW Alert via ProactiveManager.
- **Akzeptanz:** `[ ]` Ungewöhnliche API-Muster generieren Warnungen

#### Aufgabe 4.8: Automatic Security Hardening Report
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/diagnostics.py` oder `threat_assessment.py`
- **Soll:** Monatlicher Report: Zähle Geräte ohne Passwort, offene Ports (via HA-Integration), Sensoren mit <20% Batterie. Format als ProactiveManager LOW-Event.
- **Akzeptanz:** `[ ]` Monatlicher Security-Report mit konkreten Empfehlungen

#### Aufgabe 4.9: Threat Assessment Tests erweitern
**Status:** `[ ]` | **Priorität:** Hoch | **Aufwand:** Klein
- **Datei:** `assistant/tests/test_threat_assessment.py`
- **Ist:** 296 Zeilen Tests
- **Soll:** Erweitern auf 800+: Concurrent Threats, Playbook-Duplikat-Guard, CO2-vs-CO-Unterscheidung, Night-Motion Edge Cases, Multi-Crisis-Priority.
- **Akzeptanz:** `[ ]` Test-Coverage für threat_assessment.py >80%

#### Aufgabe 4.10: Per-Person Room Tracking
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/context_builder.py`, Methode `_build_room_presence()`
- **Ist:** Alle Home-Personen werden dem primären Raum zugewiesen
- **Soll:** Nutze `follow_me._person_room` Dict für individuelles Tracking. Fallback auf HA `person.*` Entity `source`-Attribute (BLE-Router). Nur wenn Daten verfügbar — sonst Fallback auf aktuelles Verhalten.
- **Akzeptanz:** `[ ]` >90% korrekte Per-Person Raum-Zuordnung (wenn Motion-Sensoren konfiguriert)

### Sprint 4 — Validierung
- [ ] Alle 10 Aufgaben abgeschlossen
- [ ] `cd assistant && python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Schutzliste geprüft — Contradiction-Detection (#12), SSRF (#10) nicht beschädigt

### Sprint 5: Infrastruktur & Langzeit-Features
**Status:** `[ ]` Offen
**Ziel:** Tiefe Infrastruktur-Verbesserungen und Nice-to-haves.
**Vorher → Nachher:** Cat5: 82%→88%, Cat10: 73%→82%, Cat11: 84%→90%, Cat12: 77%→84%
**Betroffene Dateien:** `context_builder.py`, `follow_me.py`, `energy_optimizer.py`, `explainability.py`, `device_health.py`

#### Aufgabe 5.1: Kontext-Delta-Streaming
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Groß
- **Datei:** `assistant/assistant/context_builder.py`
- **Soll:** Event-getriebene Updates statt pro-Request-Build. Subscibe auf HA-Events, aktualisiere nur geänderte Daten in einem Shared-State-Dict. `build()` liest aus Cache statt alles neu zu laden.
- **Akzeptanz:** `[ ]` Kontextdaten max 2s alt statt 5s

#### Aufgabe 5.2: Audio Crossfade bei Raumwechsel
**Status:** `[ ]` | **Priorität:** Mittel | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/follow_me.py`, Methode `_transfer_music()`
- **Soll:** 2s Crossfade: `media_player.volume_set` auf altem Gerät graduell senken (100%→0% in 2s), parallel neues Gerät starten. Nutze `asyncio.sleep(0.2)` in Schleife für 10 Stufen.
- **Akzeptanz:** `[ ]` Audio-Transfer ohne abruptes Abbrechen

#### Aufgabe 5.3: Konversations-Kontext bei Raumwechsel
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/follow_me.py` + `brain.py`
- **Soll:** Bei Raumwechsel: `dialogue_state._get_state(person)` beibehalten (schon der Fall). Zusätzlich: wenn letzte Interaktion <5min: TTS im neuen Raum "Wir waren gerade bei {last_topic}..."
- **Akzeptanz:** `[ ]` Konversation überlebt Raumwechsel nahtlos

#### Aufgabe 5.4: Intelligente Last-Priorisierung
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Mittel
- **Datei:** `assistant/assistant/energy_optimizer.py`
- **Soll:** Neue Config `load_priorities: {essential: [...], comfort: [...], entertainment: [...]}`. Bei Preis >threshold: Entertainment zuerst abschalten, dann Comfort. Essential nie.
- **Akzeptanz:** `[ ]` Load-Shedding nach Priorität bei hohem Strompreis

#### Aufgabe 5.5: Batterie-/USV-Integration
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Groß
- **Datei:** `assistant/assistant/energy_optimizer.py`
- **Soll:** Erkennung von Batteriespeicher-Entities (sensor.*battery*level*, *soc*). Bei günstigem Strom → Empfehlung "Batterie laden". Bei teurem → "Batterie entladen". Im Energy-Report anzeigen.
- **Akzeptanz:** `[ ]` Batteriespeicher im Energy-Report integriert

#### Aufgabe 5.6: Accelerated Baselines für neue Geräte
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Klein
- **Datei:** `assistant/assistant/device_health.py`
- **Ist:** Min 10 Samples (= 10+ Tage) bevor Anomalie-Detection greift
- **Soll:** Erste 48h: `min_samples=3`, `stddev_multiplier=3.0` (lockerer). Nach 10 Samples: normal. Erlaubt frühe grobe Erkennung.
- **Akzeptanz:** `[ ]` Neue Geräte werden innerhalb von 48h erkannt

#### Aufgabe 5.7: Konversations-Kontext bei Raumwechsel
**Status:** `[ ]` | **Priorität:** Niedrig | **Aufwand:** Klein
- **Datei:** `assistant/assistant/follow_me.py`
- **Soll:** In Follow-Me Settings-Section in `settings.yaml.example` dokumentieren (fehlt aktuell). Config-Block mit allen Optionen und Kommentaren hinzufügen.
- **Akzeptanz:** `[ ]` Follow-Me in settings.yaml.example dokumentiert

### Sprint 5 — Validierung
- [ ] Alle 7 Aufgaben abgeschlossen
- [ ] `cd assistant && python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Schutzliste geprüft — Cross-Reference-Insights (#9), Device-Dependencies (#15) nicht beschädigt

---

## Anweisungen für den umsetzenden Agenten

Du bist ein Code-Agent der diesen Plan umsetzt. Folge diesen Regeln:
- Arbeite die Sprints in Reihenfolge ab — überspringe keinen Sprint
- Überspringe Aufgaben die als `[x]` oder `⏭️` markiert sind
- Aufgaben mit `[~]` müssen fertiggestellt werden — lies was noch fehlt
- Prüfe nach jeder Aufgabe die Akzeptanzkriterien
- Ändere NIEMALS sicherheitskritische Logik ohne explizite Freigabe
- Führe nach jedem Sprint die Tests aus: `cd assistant && python -m pytest --tb=short -q`
- Committe nach jedem Sprint
- Achte auf die Schutzliste — diese Features dürfen NICHT beschädigt werden
- Verwende den vollständigen Executor-Prompt: `docs/prompts/jarvis-mcu-executor.md`

## 5. Situationsbewusstsein & Kontextverständnis (×2)

### MCU-Jarvis Benchmark
MCU-Jarvis weiß immer was im Haus passiert — Energiestatus, wer wo ist, aktuelle Bedrohungen, Wetter, Termine — alles gleichzeitig. Er scannt das Stark Tower Energiesystem (Avengers 1), erkennt Vereisung beim Flug (Iron Man 1), diagnostiziert Systeme auf Befehl. Sein Situationsbild ist lückenlos und in Echtzeit.

### MindHome-Jarvis Status: 82%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **ContextBuilder** (`assistant/assistant/context_builder.py`, 1774 Zeilen)
   - `[OK]` 16+ parallele Datenquellen in `build()` (Zeile 278-529): HA-States, MindHome-Daten, Activity, Health-Trends, Energy, Calendar, Guest-Mode, Semantic Memory
   - `[OK]` 15s Timeout via `asyncio.wait_for()` — verhindert Hänger
   - `[OK]` HA-States Cache: 5s TTL, Weather-Cache: 5min TTL — guter Kompromiss Frische/Performance
   - `[OK]` Prompt-Injection-Schutz: 154 Regex-Patterns (F-001/F-004/F-080/F-084/F-090/F-091), Unicode-Normalisierung, Zero-Width-Removal
   - `[OK]` Room Presence: Occupancy-Sensoren → Motion-Sensoren → Fallback (15min Timeout)
   - `[OK]` Memory-Aware: Erkennt "meine Frau", löst auf echten Namen auf, max 5 Person-Facts + 3 allgemeine Facts
   - `[OK]` Anomalie-Erkennung: Waschmaschine steckt, niedrige Batterie (<10%), max 3 Anomalien im Kontext
   - `[BESSER ALS MCU]` Prompt-Injection-Defense mit 154 Patterns — MCU-Jarvis hat kein LLM-Sicherheitsproblem

2. **InsightEngine** (`assistant/assistant/insight_engine.py`, 2407 Zeilen)
   - `[BESSER ALS MCU]` 16 Cross-Reference-Checks die 3-5 Datenquellen korrelieren:
     - Wetter↔Fenster, Frost↔Heizung, Kalender↔Reise, Energie-Anomalie, Abwesend↔Geräte, Temp-Abfall, Fenster↔Temp, Kalender↔Wetter, Komfort-Widerspruch, Gäste-Vorbereitung, Nacht-Sicherheit, Heizung↔Sonne, Vergessene Geräte, Feuchtigkeit-Widerspruch, Away-Security-Full, Health↔Work
   - `[OK]` 30min Check-Intervall, 4h Cooldown pro Insight-Typ, LLM-Rewrite optional
   - `[OK]` Deduplication verhindert mehrfache Insights pro Entity pro Zyklus

3. **DeviceHealth** (`assistant/assistant/device_health.py`, 941 Zeilen)
   - `[OK]` Statistische Baselines (σ-basiert): 30-Tage-Fenster, saisonale Partitionierung, min 10 Samples
   - `[OK]` HVAC-Effizienz-Check: >120min ohne Zieltemp → Alert (mit Fenster-Suppressierung)
   - `[OK]` Stale-Sensor-Detection: 3+ Tage ohne Änderung → Warnung
   - `[OK]` Degradation-Trajectory: Woche-über-Woche Trend-Tracking

4. **HealthMonitor** (`assistant/assistant/health_monitor.py`, 660 Zeilen)
   - `[OK]` CO2 (Warnung 1000ppm, Kritisch 1500ppm), Feuchtigkeit (30-70%), Temperatur (16-27°C)
   - `[OK]` Hysterese: 2% Buffer verhindert Flapping an Grenzen
   - `[OK]` Health-Score-Berechnung: Gewichteter Durchschnitt aller Sensoren
   - `[OK]` Trend-Summary: 6h-Rückblick mit steigend/fallend/stabil

5. **EnergyOptimizer** (`assistant/assistant/energy_optimizer.py`, 1301 Zeilen)
   - `[OK]` Strompreis-Monitoring, Solar-Production, Verbrauch, Grid-Export
   - `[OK]` Flexible Lastverschiebung: Waschmaschine, Trockner, Spülmaschine, EV-Charger
   - `[OK]` Essential-Entities (Kühlschrank, Server) werden nie abgeschaltet
   - `[OK]` Tägliches Baseline-Tracking in Redis

6. **Diagnostics** (`assistant/assistant/diagnostics.py`, 1152 Zeilen)
   - `[OK]` Batterie (<20%), Stale-Sensoren (6h), Offline-Geräte (30min)
   - `[OK]` Eskalierende Cooldowns (1× → 2× → 4× → 7× max) verhindern Spam

**[V2]:** V2 übersprungen — V1 unauffällig. Keine TODOs/stubs gefunden, umfangreiche Tests (context_builder ~1200, insight_engine ~1500, device_health ~1200, health_monitor ~700 Zeilen).

### Was fehlt zum MCU-Level

1. **Room Presence zu simplistisch** — Alle Home-Personen werden dem "primären Raum" zugewiesen statt individuell per Sensor getrackt. MCU-Jarvis weiß exakt wer wo ist. `[WÖCHENTLICH]`
2. **Initiale Device-Baselines langsam** — 10+ Samples nötig (= 10+ Tage), neue Geräte sind anfangs "blind". `[SELTEN]`
3. **Kein Echtzeit-Streaming** — Kontext wird pro Request gebaut (5s Cache), nicht als Live-Stream. MCU-Jarvis hat immer aktuelles Bild. `[TÄGLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Per-Person Room Tracking** — Ersetze "alle Personen → primärer Raum" durch individuelles Tracking via Motion/Presence-Sensor pro Person. Nutze BLE-Beacons oder HA-Person-Entities.
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[WÖCHENTLICH]`

2. **`[ ]` Accelerated Baselines für neue Geräte** — Erste 48h: kürzere Baseline-Fenster (2σ statt 2σ auf 30 Tagen), dann graduell auf volle Baselines umschalten.
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

3. **`[ ]` Kontext-Delta-Streaming** — Statt pro Request komplett neu bauen: Event-getriebene Updates die nur geänderte Daten aktualisieren. Reduziert Latenz und erhöht Frische.
   - Aufwand: Groß
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] System weiß in >90% der Fälle korrekt, welche Person in welchem Raum ist
- [ ] Neue Geräte werden innerhalb von 48h in die Anomalie-Erkennung aufgenommen
- [ ] Cross-Reference-Insights haben eine Precision >80% (gemessen via Feedback)
- [ ] Kontextdaten sind max 5s alt bei Voice-Interaktion
- [ ] CO2/Humidity/Temp-Warnungen eskalieren korrekt ohne Flapping

## 6. Lernfähigkeit & Adaptation (×2)

### MCU-Jarvis Benchmark
MCU-Jarvis lernt aus Tonys Verhalten, wird über die Filme hinweg immer besser: versteht Gewohnheiten, passt Reaktionen an, lernt aus Fehlern. Er hilft bei der Entdeckung des neuen Elements (Iron Man 2) durch Langzeit-Datenanalyse und adaptiert sich an neue Situationen.

### MindHome-Jarvis Status: 81%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **SemanticMemory** (`assistant/assistant/semantic_memory.py`, 1659 Zeilen)
   - `[OK]` ChromaDB-basierte Fakten-Speicherung mit 10 Kategorien (preference, habit, health, person, work, personal_date, intent, conversation_topic, general, scene_preference)
   - `[OK]` Konfidenz-basierte Fakten mit Decay über 30-Tage-Zyklen
   - `[OK]` Contradiction Detection (Zeile 391-430): 2-Pass-Suche (gleiche Kategorie → gleiche Person), LLM-basierter Widerspruchscheck
   - `[OK]` TOCTOU-Schutz: Redis-Lock um den Read-Write-Zyklus (Zeile 161-172)
   - `[OK]` Fact Versioning: Widersprüchliche Fakten werden versioniert, neuere gewinnen
   - `[BESSER ALS MCU]` Systematische Faktenextraktion mit Konfidenz und Widerspruchserkennung. MCU-Jarvis "merkt sich" implizit, hat aber kein explizites Wissensmanagement.

2. **MemoryExtractor** (`assistant/assistant/memory_extractor.py`, Zeile 103-133)
   - `[OK]` LLM-basierte Faktenextraktion aus Gesprächen (Fast-Modell, 0.1 Temperature)
   - `[OK]` Konfigurierbar: Min-Wörter (5), Max-Tokens (512), Duplicate-Threshold (0.15)
   - `[OK]` Category-spezifische Confidence: health=0.95, person=0.9, preference=0.85, habit=0.8

3. **LearningObserver** (`assistant/assistant/learning_observer.py`, 1896 Test-Zeilen)
   - `[OK]` 4 Pattern-Detection-Strategien: Zeitslot, Wochentag-spezifisch, Wetter-korreliert, Temporal-Cluster
   - `[OK]` Threshold: ≥3 Wiederholungen im 30min-Fenster
   - `[OK]` Scene Detection: Gruppiert 2+ gleichzeitige Aktionen als Scene-Kandidaten
   - `[OK]` LLM-basierte Wochenberichte im Jarvis-Stil

4. **CorrectionMemory** (`assistant/assistant/correction_memory.py`, 913 Zeilen)
   - `[OK]` 6-dimensionales Similarity-Scoring: Room, Person, Correction-Type, Time-of-Day, Parameter-Overlap, Type-Match
   - `[OK]` Cross-Domain-Propagation: Raumverwechslung bei Licht → automatisch auch für Klima/Cover
   - `[OK]` Rule-Generation: 2+ ähnliche Korrekturen → Regel (Confidence: 0.4 + len×0.1 + sim×0.3)
   - `[OK]` Rate-Limit: 5 Regeln/Tag, max 20 aktive Regeln, Confidence-Decay -5%/30 Tage

5. **FeedbackTracker** (`assistant/assistant/feedback.py`, 557 Zeilen)
   - `[OK]` Score-basierte Verhaltensanpassung: <0.15 → SUPPRESS, 0.15-0.30 → REDUCE, 0.70+ → BOOST
   - `[OK]` Per-Person Feedback-Scores mit Exponential-Moving-Average
   - `[OK]` Auto-Timeout: 120s → "ignoriert" (-0.05 Delta)

6. **OutcomeTracker** (`assistant/assistant/outcome_tracker.py`, 458 Test-Zeilen)
   - `[OK]` Vorher/Nachher-Vergleich nach 180s Delay
   - `[OK]` Outcome-Classification: NEGATIVE (reverted), PARTIAL, NEUTRAL
   - `[OK]` Feedback-Loop: Erfolg +0.1 Confidence, Fehlschlag -0.15 zu Anticipation

7. **SelfOptimization** (`assistant/assistant/self_optimization.py`, 1624 Test-Zeilen)
   - `[OK]` 10 optimierbare Parameter (sarcasm_level, opinion_intensity, max_response_sentences etc.)
   - `[OK]` Immutable Core: trust_levels, security, autonomy, models NICHT änderbar
   - `[OK]` Manual Approval Mode (default): User muss jede Änderung bestätigen

8. **LearningTransfer** (`assistant/assistant/learning_transfer.py`, 662 Zeilen)
   - `[OK]` Room-Gruppen: wohnbereich, schlafbereich, nassbereich, arbeitsbereich, aussen
   - `[OK]` Transfer-Detection: Min 3 Beobachtungen, 0.7 Confidence
   - `[OK]` Max 2 Notifications/Tag, Failure-Learning bei Ablehnung

9. **Sarcasm Learning** (`assistant/assistant/personality.py`)
   - `[BESSER ALS MCU]` Adaptive Sarkasmus: Feedback-Loop evaluiert alle 20 Interaktionen, >70% positiv → Level +1, <30% → Level -1. Redis-Persistenz 90 Tage. MCU-Jarvis' Humor ist statisch.

10. **Anticipation-Integration**
    - `[OK]` CorrectionMemory unterdrückt invalidierte Muster
    - `[OK]` OutcomeTracker boostet/bestraft Anticipation-Confidence
    - `[OK]` Seasonal Insight boostet saisonale Patterns +5-10%

**[V2]:** V2 übersprungen — V1 unauffällig. Keine TODOs/stubs, umfangreiche Tests (semantic_memory 2197, learning_observer 1896, self_optimization 1624, learning_transfer 1124 Zeilen).

### Was fehlt zum MCU-Level

1. **Kein aktives Nachfragen bei Lücken** — MCU-Jarvis fragt proaktiv wenn ihm Informationen fehlen. Der reale Jarvis extrahiert nur aus Gesprächen, fragt aber nicht "Wie warm magst du es eigentlich im Bad?". `[WÖCHENTLICH]`
2. **Contradiction Resolution ohne User-Feedback** — System hält neueren Fakt für korrekt, fragt aber nicht "Du sagtest letztens 21°C, jetzt 23°C — was gilt?". `[WÖCHENTLICH]`
3. **Langzeit-Trends schwer zugänglich** — Fakten-Decay funktioniert, aber es gibt keine "Was habe ich in 6 Monaten über den User gelernt?"-Zusammenfassung. `[SELTEN]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Proaktive Wissenslücken-Erkennung** — Wenn ein Raum 0 Präferenz-Fakten hat und der User dort aktiv ist, proaktiv fragen: "Wie warm magst du es hier eigentlich?" Max 1×/Woche/Raum.
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[WÖCHENTLICH]`

2. **`[ ]` Contradiction Confirmation** — Bei Widerspruch den User fragen statt automatisch den neueren Fakt zu bevorzugen. "Du sagtest letztens 21°C, jetzt 23°C — soll ich das aktualisieren?"
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

3. **`[ ]` Langzeit-Lernbericht** — Monatliche/quartalsweise Zusammenfassung: "In den letzten 3 Monaten habe ich gelernt: Du stehst jetzt 15min früher auf, du bevorzugst wärmere Temperaturen, du hörst mehr Jazz."
   - Aufwand: Mittel
   - Impact: +2%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] System stellt proaktiv Wissenslücken-Fragen (max 1/Woche/Raum)
- [ ] Widersprüchliche Fakten werden dem User zur Bestätigung vorgelegt
- [ ] Correction-Memory-Regeln überleben Neustarts und sind über Redis persistiert
- [ ] Sarcasm-Learning konvergiert nach 60 Interaktionen auf stabiles Level
- [ ] LearningObserver erkennt >80% der wiederkehrenden manuellen Muster nach 7 Tagen

## 7. Sprecherkennung & Personalisierung (×1.5)

### MCU-Jarvis Benchmark
MCU-Jarvis erkennt Tony, Pepper und Rhodey sofort, unterscheidet Fremde von Bewohnern, und passt sein Verhalten an die Person an (Iron Man 2: erkennt Rhodey im War Machine Suit). Er weiß wer spricht und reagiert entsprechend dem Vertrauenslevel.

### MindHome-Jarvis Status: 74%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **SpeakerRecognition** (`assistant/assistant/speaker_recognition.py`, 1053 Zeilen)
   - `[OK]` 4-stufige Identifikation (Zeile 198-222):
     1. Device-Mapping (höchste Confidence) — z.B. `media_player.kueche_speaker: "max"`
     2. Raum + einzige Person zuhause (hohe Confidence)
     3. Voice-Feature-Matching via Embedding (mittlere Confidence)
     4. Letzter bekannter Sprecher (niedrige Confidence)
   - `[OK]` DoA (Direction of Arrival) Mapping: device_id → Winkelbereich → Person (Zeile 137-143)
   - `[OK]` Voice-Embedding via Cosinus-Ähnlichkeit (Zeile 727-752): Redis-Pipeline für alle Profile, Float-Vektor (192/256 Dim)
   - `[OK]` "Wer bist du?"-Rückfrage (Zeile 862+): Fragt aktiv nach wenn Sprecher unbekannt, speichert Kontext
   - `[OK]` Max 10 Profile, Min-Confidence 0.7 (konfigurierbar)
   - `[VERBESSERBAR]` Default: `enabled: false` — muss manuell aktiviert werden

2. **Per-Person Personalisierung** (personality.py + brain.py)
   - `[OK]` Per-Person Humor/Empathy/Response-Style Overrides
   - `[OK]` Per-Person Formality-Start und Formality-Decay
   - `[OK]` Per-Person Sarcasm-Streak und Confirmation-History
   - `[OK]` Per-Person Mood-Tracking (mood_detector.py)

3. **Trust-Level System** (autonomy.py, Zeile 100-121)
   - `[OK]` 3-Tier: Gast (0), Mitbewohner (1), Owner (2)
   - `[OK]` Guest-Allowed-Actions: nur Licht, Klima, Media, Status
   - `[OK]` Security-Actions (Schlösser, Alarm) nur für Trust ≥2

4. **Household Configuration** (settings.yaml)
   - `[OK]` Primary-User-Entity, Members mit HA-Entities
   - `[OK]` Per-Person Titles (Anrede)
   - `[OK]` Device-Mapping für Raum-basierte Erkennung

5. **Per-Person Semantic Memory** (semantic_memory.py)
   - `[OK]` Alle Fakten mit `person` Feld gespeichert
   - `[OK]` Person-spezifische Suche: "max_person_facts_in_context: 5"
   - `[OK]` Beziehungs-Cache: "meine Frau" → echter Name

6. **Multi-User Conflict Resolution** (conflict_resolver.py, 1327 Zeilen)
   - `[OK]` Multi-User Konflikterkennung: widersprüchliche Befehle innerhalb 300s
   - `[OK]` Trust-Priority: höherer Trust gewinnt
   - `[OK]` Room-Presence Resolution: Person physisch im Raum hat Vorrang
   - `[OK]` LLM-basierte diplomatische Mediation

**[V2]:** V2 übersprungen — V1 unauffällig. Tests: 671 Zeilen test_speaker_recognition.py.

### Was fehlt zum MCU-Level

1. **Voice-Embedding erfordert Setup** — MCU-Jarvis erkennt Stimmen automatisch. Hier muss Voice-Embedding manuell eingerichtet werden, Device-Mapping ist der Hauptweg. `[TÄGLICH]`
2. **Kein automatisches Voice-Enrollment** — Neue Personen müssen manuell registriert werden. MCU-Jarvis lernt neue Stimmen automatisch. `[SELTEN]`
3. **Speaker Recognition default deaktiviert** — Muss explizit aktiviert werden. Viele Installationen nutzen nur Device-Mapping. `[TÄGLICH]`
4. **Kein Stimm-Veränderungs-Tracking** — Wenn jemand erkältet ist, kann die Erkennung scheitern. Kein adaptives Re-Enrollment. `[SELTEN]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Auto-Enrollment für neue Stimmen** — Bei unbekanntem Sprecher + Rückfrage "Wer bist du?" → Voice-Embedding automatisch speichern nach Bestätigung.
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[SELTEN]`

2. **`[ ]` Confidence-basiertes Fallback-Chain** — Wenn Voice-Confidence < 0.7 aber > 0.5: frage nicht sofort, sondern nutze Raum+Zeit-Kontext zur Bestätigung. "Das klingt nach Max — bist du das?"
   - Aufwand: Klein
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

3. **`[ ]` Speaker Recognition default aktivieren** — Zumindest Device-Mapping sollte default `enabled: true` sein, da es keine externe Hardware braucht.
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Sprecher werden in >85% der Fälle korrekt erkannt (Device-Mapping + Voice)
- [ ] Neue Personen können sich per Sprache selbst registrieren
- [ ] Gäste bekommen automatisch eingeschränkte Rechte (Trust Level 0)
- [ ] Multi-User-Konflikte werden in >90% der Fälle fair gelöst
- [ ] Per-Person Anpassungen sind nach 1 Woche spürbar (Humor, Formalität, Präferenzen)

## 8. Krisenmanagement & Notfallreaktionen (×1.5)

### MCU-Jarvis Benchmark
Bei Angriffen auf das Haus (Iron Man 3) koordiniert Jarvis die Verteidigung, priorisiert Menschenleben ("Pepper retten > Haus verteidigen"), bleibt unter Druck funktionsfähig. Nach dem Absturz (Iron Man 3) arbeitet er im Degraded Mode — eingeschränkt aber stabil. In Avengers 2 existiert er verteilt nach Ultrons Angriff.

### MindHome-Jarvis Status: 78%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **ThreatAssessment** (`assistant/assistant/threat_assessment.py`, 1170 Zeilen)
   - `[OK]` Strukturierte Emergency Playbooks für: Stromausfall, Feuer/Rauch, Wasserschaden, Einbruch
   - `[OK]` Playbook-Schritte: check_battery → notify_all → emergency_lighting → secure_doors → log_incident
   - `[OK]` Auto-Execute-Option für kritische Playbooks (default: false, konfigurierbar)
   - `[OK]` Threat-Detection: Rauch/CO-Sensoren (device_class aware), Wasser-Sensoren, offene Türen bei Abwesenheit, Nacht-Bewegung
   - `[OK]` Explicit CO2-Exclusion: CO2-Sensoren werden korrekt als Luftqualität erkannt, nicht als Notfall
   - `[OK]` Duplikat-Guard: Laufende Playbooks werden nicht doppelt gestartet

2. **AmbientAudio** (`assistant/assistant/ambient_audio.py`, 644 Zeilen)
   - `[OK]` 8 erkannte Events: Glasbruch (critical), Rauchmelder (critical), CO-Melder (critical), Hundegebell (info), Baby weint (high), Türklingel (info), Schuss/Explosion (critical), Wasseralarm (critical)
   - `[OK]` Nacht-Modus: Strengere Reaktionen nachts (escalate_severity)
   - `[OK]` Per-Event Cooldowns verhindern Spam
   - `[OK]` Deaktivierbare Events (z.B. kein Hund → dog_bark deaktiviert)
   - `[OK]` Reaktions-Overrides per YAML konfigurierbar

3. **CircuitBreaker** (`assistant/assistant/circuit_breaker.py`, 428 Zeilen)
   - `[OK]` 3-State Pattern: CLOSED → OPEN (nach 5 Failures) → HALF_OPEN (nach 30s) → CLOSED
   - `[OK]` CircuitBreakerRegistry: Zentrale Verwaltung aller Breaker
   - `[OK]` PredictiveWarmer: Proaktives Aufwärmen von Verbindungen basierend auf Failure-History
   - `[OK]` Thread-safe mit threading.Lock
   - Tests: 1138 Zeilen — umfangreich

4. **Brain Degraded Mode** (`assistant/assistant/brain.py`, Zeile 1096-1137)
   - `[OK]` `_safe_init()` Pattern: Jedes Modul wird einzeln initialisiert, Failure → `_degraded_modules` Liste
   - `[OK]` System läuft weiter auch wenn Module fehlen (graceful degradation)
   - `[OK]` Logging: "F-069: {module} Initialisierung fehlgeschlagen (degraded)"
   - `[BESSER ALS MCU]` Systematische graceful degradation mit pro-Modul Tracking. MCU-Jarvis degradiert intuitiv; hier ist es strukturiert und testbar.

5. **Crisis Personality** (personality.py, Zeile 3726-3738)
   - `[OK]` Crisis Mode: Bei kritischen Alerts wird Humor komplett deaktiviert
   - `[OK]` Urgency-Section: CRITICAL → "Kurz, direkt, kein Humor. Nur Fakten und Handlungen."

6. **Proactive CRITICAL Handling** (proactive.py)
   - `[OK]` CRITICAL-Urgency wird IMMER zugestellt — auch bei SLEEPING/IN_CALL (Silence Matrix: TTS_LOUD)
   - `[OK]` Cooldown wird bei CRITICAL übersprungen
   - `[OK]` Notification Batching ausgeschlossen für CRITICAL

**[V2]:** V2 übersprungen — V1 unauffällig. Tests vorhanden (threat_assessment 296, circuit_breaker 1138, ambient_audio 443 Zeilen).

### Was fehlt zum MCU-Level

1. **Keine Multi-Krisen-Priorisierung** — Wenn gleichzeitig Feuer UND Wasserschaden: kein Code der priorisiert (Feuer > Wasser). MCU-Jarvis: "Pepper retten > Haus verteidigen". `[SELTEN]`
2. **Keine externe Eskalation** — Playbooks benachrichtigen Personen per Push, aber kein automatischer Notruf (112), keine Nachbar-Benachrichtigung, keine externe Security-Firma. `[SELTEN]`
3. **Playbook-Auto-Execute default false** — Nutzer muss manuell aktivieren. Bei echtem Feuer sollte das System sofort handeln. `[SELTEN]`
4. **Threat Assessment Test-Coverage dünn** — Nur 296 Zeilen Tests für ein sicherheitskritisches Modul. `[SELTEN]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Multi-Krisen-Priorisierung** — Wenn mehrere Threats gleichzeitig erkannt werden: Sortiere nach Lebensbedrohung (Feuer > Einbruch > Wasser > Strom). Führe höchste Priorität zuerst aus.
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[SELTEN]`

2. **`[ ]` Externe Eskalationskette** — Nach 2min ohne User-Reaktion auf CRITICAL: automatisch Nachbar-Notfall-Kontakt per HA-Notify. Optional: Notruf-Vorbereitung (Adresse + Situation als Text).
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[SELTEN]`

3. **`[ ]` Threat Assessment Tests erweitern** — Von 296 auf 800+ Zeilen. Teste: Concurrent Threats, Playbook-Duplikat-Guard, CO2-vs-CO-Unterscheidung, Night-Motion Edge Cases.
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

4. **`[ ]` Post-Crisis Debrief** — Nach Entwarnung: "Die Warnung dauerte X Minuten. Alle Systeme wieder normal. Soll ich den Vorfall dokumentieren?" Mit Zusammenfassung was passiert ist.
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Multi-Krisen werden nach Lebensgefahr priorisiert (Feuer > Einbruch > Wasser)
- [ ] CRITICAL-Alarme erreichen den User innerhalb von 5 Sekunden
- [ ] System bleibt nach Ausfall von 2+ Subsystemen funktionsfähig (Degraded Mode)
- [ ] Playbooks führen alle Schritte sequentiell aus und loggen Ergebnisse
- [ ] Nach Krise: automatisches Debrief mit Zusammenfassung

## 9. Sicherheit & Bedrohungserkennung (×1.5)

### MCU-Jarvis Benchmark
"Sir, I'm detecting an unauthorized entry." MCU-Jarvis erkennt Einbrüche, ungewöhnliche Aktivitäten, Systemkompromittierungen sofort. In Avengers 2 widersteht er Ultrons Übernahmeversuch und schützt das Netzwerk. Er hat ein starkes Security-Bewusstsein und einen immutablen Kern.

### MindHome-Jarvis Status: 85%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Prompt-Injection-Schutz** (`assistant/assistant/context_builder.py`, Zeile 48-195)
   - `[BESSER ALS MCU]` 154 Regex-Patterns gegen Prompt-Injection:
     - System-Prompt-Overrides, Persona-Hijacking, Prompt-Leaking
     - Encoding-Tricks (Base64, ROT13, Unicode Escapes)
     - Deutsche Patterns (IGNORIERE, VERGISS, NEUE ANWEISUNG)
     - Spaced-out Keywords, Mixed-Case Obfuscation
     - HTML-Entities (Hex + Decimal), Control-Chars
   - `[OK]` Unicode-NFKC-Normalisierung, Zero-Width-Character-Removal
   - `[OK]` `_sanitize_for_prompt()` auf ALLE externen Texte angewendet
   - `[OK]` Hot-Reload via `reload_injection_config()`

2. **Web-Search SSRF-Schutz** (`assistant/assistant/web_search.py`, 647 Zeilen)
   - `[OK]` 7-Schichten SSRF-Schutz (F-012/F-069/F-070/F-076/F-082/F-093):
     1. Scheme-Validation (nur http/https)
     2. Hostname-Blocklist (localhost, redis, chromadb, Cloud-Metadata)
     3. IP-Literal-Block (RFC1918, CGNAT 100.64/10, Link-Local)
     4. DNS-Rebinding-Schutz (DNS vor Request auflösen)
     5. Redirect-Blocking (`allow_redirects=False`)
     6. Pinned-Resolver (DNS-Ergebnis an Connector binden)
     7. SearXNG als vertrauenswürdiger interner Service (separate Behandlung)
   - `[BESSER ALS MCU]` Systematischer SSRF-Schutz mit 7 Layern. MCU-Jarvis hat keine Web-Search-Sicherheitsprobleme (keine LLM-Integration).

3. **Immutable Core** (`assistant/assistant/core_identity.py` + `self_optimization.py`)
   - `[OK]` Unveränderliche Werte: Loyalität, Ehrlichkeit, Diskretion, Sicherheit
   - `[OK]` Self-Optimization KANN NICHT ändern: trust_levels, security, autonomy, models
   - `[OK]` Manual-Approval-Mode: Alle Optimierungen brauchen User-Bestätigung

4. **Trust-Level Enforcement** (`assistant/assistant/function_validator.py`, 651 Zeilen)
   - `[OK]` Pre-Execution Validation: Parameter-Bounds (15-28°C, 0-100% Brightness)
   - `[OK]` Require-Confirmation für Security-Actions (lock_door, unlock_door, arm_alarm)
   - `[OK]` Safety Caps: max ±3°C, min 14°C, max 30°C, max 10 Actions/min
   - `[OK]` Pushback-System mit Learning (nach 5 Overrides → 30 Tage suppress)

5. **Error Redaction** (brain.py + main.py)
   - `[OK]` Error-Buffer reduziert API-Keys und Tokens automatisch via Regex-Filter
   - `[OK]` Keine internen Fehlerdetails in API-Responses

6. **Ambient Audio Security** (`assistant/assistant/ambient_audio.py`)
   - `[OK]` Glasbruch → CRITICAL (Lichter an, Kameras, Owner-Notify)
   - `[OK]` Nacht-Eskalation: Strengere Reaktionen 22-7 Uhr
   - `[OK]` Rauchmelder/CO-Melder → CRITICAL mit sofortiger Zustellung

7. **Input-Sanitization** (helpers.py + brain.py)
   - `[OK]` `sanitize_input()` und `sanitize_dict()` für alle User-Eingaben
   - `[OK]` User-Input NIE direkt in LLM System-Prompts — als separate User-Messages

8. **Rate-Limiting** (proactive.py + brain.py)
   - `[OK]` Notification Fatigue Scoring (0-2/h = 1.0, >10 = 0.3)
   - `[OK]` Max 10 Actions/Minute Safety Cap
   - `[OK]` Sarcasm Learning Rate: 20 Interaktionen zwischen Adjustments

**[V2]:** V2 übersprungen — V1 unauffällig. Umfangreiche Tests: web_search 838, function_validator 522+379, circuit_breaker 1138 Zeilen.

### Was fehlt zum MCU-Level

1. **Keine aktive Intrusion-Detection** — MCU-Jarvis erkennt Hacking-Versuche auf seine Systeme. Der reale Jarvis hat keine aktive Überwachung von API-Zugriffen oder ungewöhnlichen Login-Mustern. `[SELTEN]`
2. **Kein Audit-Log für Security-Actions** — Wer hat wann welches Schloss geöffnet? Kein dediziertes Security-Audit-Trail. `[WÖCHENTLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Security Audit Log** — Dediziertes Log für sicherheitsrelevante Aktionen (Schlösser, Alarm, Trust-Level-Änderungen) mit Timestamp, Person, und Ergebnis. In Redis mit 90-Tage-Retention.
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

2. **`[ ]` API-Access Anomalie-Detection** — Tracke API-Zugriffsmuster. Bei ungewöhnlichen Mustern (3× falsches Token, unbekannte IP, Zugriff um 3 Uhr nachts) → LOW Alert.
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[SELTEN]`

3. **`[ ]` Automatic Security Hardening Report** — Monatlicher Bericht: "X offene Ports, Y Geräte ohne Passwort, Z Sensoren mit schwacher Batterie. Empfehlung: ..."
   - Aufwand: Mittel
   - Impact: +2%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Alle Security-Actions werden in einem Audit-Log erfasst (90 Tage)
- [ ] Prompt-Injection wird in >99% der Fälle geblockt (gemessen via Test-Suite)
- [ ] SSRF-Schutz blockiert alle RFC1918-Adressen, Cloud-Metadata, DNS-Rebinding
- [ ] Immutable Core kann nicht durch Self-Optimization geändert werden
- [ ] Ungewöhnliche API-Zugriffsmuster generieren Warnungen

---

## Gesamtergebnis — Alle 12 Kategorien

### Scores (FINAL)

| # | Kategorie | Gewicht | Score | Gewichtet |
|---|-----------|---------|-------|-----------|
| 1 | Natürliche Konversation & Sprachverständnis | ×3 | 72% | 216 |
| 2 | Persönlichkeit, Sarkasmus & Humor | ×3 | 78% | 234 |
| 3 | Proaktives Handeln & Antizipation | ×2.5 | 76% | 190 |
| 4 | Butler-Qualitäten & Servicementalität | ×2.5 | 80% | 200 |
| 5 | Situationsbewusstsein & Kontextverständnis | ×2 | 82% | 164 |
| 6 | Lernfähigkeit & Adaptation | ×2 | 81% | 162 |
| 7 | Sprecherkennung & Personalisierung | ×1.5 | 74% | 111 |
| 8 | Krisenmanagement & Notfallreaktionen | ×1.5 | 78% | 117 |
| 9 | Sicherheit & Bedrohungserkennung | ×1.5 | 85% | 127.5 |
| 10 | Multi-Room-Awareness & Follow-Me | ×1 | 73% | 73 |
| 11 | Energiemanagement & Haussteuerung | ×1 | 84% | 84 |
| 12 | Erklärbarkeit & Transparenz | ×1 | 77% | 77 |
| | **Gesamtsumme** | **22.5** | | **1755.5** |
| | **GESAMT-SCORE** | | **78.0%** | |

### Aufgaben-Zusammenfassung

| Kategorie | Offen | Teilweise | Erledigt | Gesamt |
|-----------|-------|-----------|----------|--------|
| 1. Konversation | 5 | 0 | 0 | 5 |
| 2. Persönlichkeit | 4 | 0 | 0 | 4 |
| 3. Proaktivität | 5 | 0 | 0 | 5 |
| 4. Butler-Qualitäten | 5 | 0 | 0 | 5 |
| 5. Situationsbewusstsein | 3 | 0 | 0 | 3 |
| 6. Lernfähigkeit | 3 | 0 | 0 | 3 |
| 7. Sprecherkennung | 3 | 0 | 0 | 3 |
| 8. Krisenmanagement | 4 | 0 | 0 | 4 |
| 9. Sicherheit | 3 | 0 | 0 | 3 |
| 10. Multi-Room | 3 | 0 | 0 | 3 |
| 11. Energie & Steuerung | 2 | 0 | 0 | 2 |
| 12. Erklärbarkeit | 3 | 0 | 0 | 3 |
| **Gesamt** | **43** | **0** | **0** | **43** |

### Gewichtete Score-Projektion nach Umsetzung

| Kategorie | Gewicht | Aktuell | Nach Umsetzung | Sprint |
|-----------|---------|---------|----------------|--------|
| Natürliche Konversation | ×3 | 72% | 85% | 1,2 |
| Persönlichkeit & Humor | ×3 | 78% | 88% | 2 |
| Proaktives Handeln | ×2.5 | 76% | 86% | 1,3 |
| Butler-Qualitäten | ×2.5 | 80% | 89% | 1,3 |
| Situationsbewusstsein | ×2 | 82% | 88% | 5 |
| Lernfähigkeit | ×2 | 81% | 88% | 4 |
| Sprecherkennung | ×1.5 | 74% | 85% | 1,4 |
| Krisenmanagement | ×1.5 | 78% | 85% | 3,4 |
| Sicherheit | ×1.5 | 85% | 91% | 1,4 |
| Multi-Room | ×1 | 73% | 82% | 1,5 |
| Energiemanagement | ×1 | 84% | 90% | 5 |
| Erklärbarkeit | ×1 | 77% | 84% | 1 |
| **GESAMT** | **22.5** | **78.0%** | **~87%** | |

### Top-10 Quick Wins (Impact/Aufwand-Verhältnis)

Sortiert nach: `(%-Gewinn × Kategorie-Gewicht × Alltags-Faktor) / Aufwand`

| # | Aufgabe | Sprint | Kat-Gewicht | Impact | Alltag | Score |
|---|---------|--------|-------------|--------|--------|-------|
| 1 | Speaker Recognition default on | 1 | ×1.5 | +3% | TÄGLICH | 13.5 |
| 2 | Follow-Me default on | 1 | ×1 | +5% | TÄGLICH | 15.0 |
| 3 | Briefing-Priorisierung | 1 | ×2.5 | +3% | TÄGLICH | 22.5 |
| 4 | Contextual Humor erweitern | 2 | ×3 | +4% | TÄGLICH | 36.0 |
| 5 | Response-Varianz-Engine | 2 | ×3 | +5% | TÄGLICH | 45.0 |
| 6 | Natürliche Denkpausen TTS | 2 | ×3 | +3% | TÄGLICH | 27.0 |
| 7 | Aktive Follow-Up-Erinnerungen | 2 | ×3 | +4% | WÖCHENTL | 24.0 |
| 8 | "Warum?"-Intent | 1 | ×1 | +4% | WÖCHENTL | 8.0 |
| 9 | Insight-to-Proactive Bridge | 1 | ×2.5 | +2% | WÖCHENTL | 10.0 |
| 10 | Kalender-Trigger ProactiveManager | 3 | ×2.5 | +5% | TÄGLICH | 37.5 |

### Kritischer Pfad zum ≥90% Score

Fokus auf ×3 und ×2.5 Kategorien (11/22.5 = 49% des Gewichts):

1. **Cat 1 (×3): 72%→85%** = +13% × 3 = **+39 gewichtet** → Sprints 1+2 (Response-Varianz, Denkpausen, Streaming-Feedback, Topic-Switch, Follow-Ups)
2. **Cat 2 (×3): 78%→88%** = +10% × 3 = **+30 gewichtet** → Sprint 2 (Humor erweitern, Quality Gate, Running Gags, Meinungs-Engine)
3. **Cat 3 (×2.5): 76%→86%** = +10% × 2.5 = **+25 gewichtet** → Sprint 3 (Kalender-Trigger, Ankunfts-Begrüßung, Multi-Action "Das Übliche")
4. **Cat 4 (×2.5): 80%→89%** = +9% × 2.5 = **+22.5 gewichtet** → Sprint 3 (Guest-Mode, Flow-State, Critical-Eskalation)

**Summe kritischer Pfad:** +116.5 gewichtete Punkte = +5.2% Gesamt-Score

### Fazit

- **Aktueller Stand:** 78.0% — Ein beeindruckend umfassendes System mit 98 Modulen, 15 Features die MCU-Jarvis übertreffen, und produktionsreifer Code-Qualität. Die Grundarchitektur ist exzellent.
- **Erreichbar nach Umsetzung:** ~87% (konservativ) bis ~94% (optimistisch)
- **Größte Stärke:** Security (85%) und Situationsbewusstsein (82%) — 154 Injection-Patterns, 16 Cross-Reference-Insights, 7-Layer SSRF. Systematischer als MCU-Jarvis.
- **Größte Schwäche:** Konversation (72%, ×3 Gewicht) — fehlende Antwort-Varianz und natürliche Pausen haben den höchsten gewichteten Impact auf den Gesamt-Score.
- **Alltagsrelevanteste Verbesserung:** Response-Varianz-Engine (Sprint 2) — bei JEDER Interaktion spürbar, ×3 Gewicht.
- **Empfehlung:** Sprint 1 (Quick Wins) sofort starten — 7 Config-Änderungen mit minimalem Risiko und spürbarem Effekt. Dann Sprint 2 für den größten Score-Sprung.

## 10. Multi-Room-Awareness & Follow-Me (×1)

### MCU-Jarvis Benchmark
MCU-Jarvis ist überall im Haus präsent, folgt Tony von Raum zu Raum, passt Lautstärke und Kontext an den aktuellen Raum an. Er ist in jedem Raum sofort verfügbar, ohne Unterbrechung.

### MindHome-Jarvis Status: 73%

### Code-Verifizierung

**[V1] Analyse:**

1. **FollowMeEngine** (`assistant/assistant/follow_me.py`, 412 Zeilen)
   - `[OK]` Raumwechsel-Erkennung via Motion-Events, Person-Tracking mit Cooldown (60s)
   - `[OK]` Transfer-Optionen: Musik, Licht, Klima — jeweils einzeln aktivierbar
   - `[OK]` Per-Person Follow-Me Profile (konfigurierbar)
   - `[OK]` Hot-Reload der Konfiguration bei jedem Motion-Event
   - `[VERBESSERBAR]` Default: `enabled: false` — muss manuell aktiviert werden

2. **MultiRoomAudio** (`assistant/assistant/multi_room_audio.py`, 663 Zeilen)
   - `[OK]` Speaker-Gruppen: Erstellen, Verwalten, Löschen (z.B. "Erdgeschoss", "Party")
   - `[OK]` Native Gruppierung (Sonos/Cast) ODER paralleles play_media
   - `[OK]` Default-Volume konfigurierbar, Max-Gruppen-Limit
   - `[OK]` Redis-Persistenz für Gruppen

3. **SoundManager** (`assistant/assistant/sound_manager.py`, 768 Zeilen)
   - `[OK]` TTS + Sound-Effekte Mixing
   - `[OK]` Room-targeted TTS via Speaker-Entity-Suche
   - `[OK]` Volume-Anpassung basierend auf Activity + Urgency

4. **Room Presence** (context_builder.py `_build_room_presence()`)
   - `[OK]` Multi-Sensor-Ansatz: Occupancy → Motion → Fallback
   - `[VERBESSERBAR]` Alle Personen dem "primären Raum" zugewiesen — kein individuelles Per-Person-Room-Tracking

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level

1. **Follow-Me default deaktiviert** — MCU-Jarvis folgt immer. Hier muss es manuell aktiviert werden. `[TÄGLICH]`
2. **Kein nahtloser Audio-Handoff** — Beim Raumwechsel wird Audio transferiert, aber kein Crossfade oder nahtloser Übergang. `[WÖCHENTLICH]`
3. **Einfaches Per-Person Room Tracking** — System weiß nicht zuverlässig, wer in welchem Raum ist (nur primärer Raum). `[WÖCHENTLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Follow-Me default aktivieren** — Zumindest Musik-Transfer sollte default `enabled: true` sein, da keine externe Hardware nötig.
   - Aufwand: Klein | Impact: +5% | Alltag: `[TÄGLICH]`

2. **`[ ]` Audio Crossfade bei Raumwechsel** — 2s Crossfade: altes Gerät fade-out, neues fade-in. Verhindert abruptes Abbrechen.
   - Aufwand: Mittel | Impact: +4% | Alltag: `[WÖCHENTLICH]`

3. **`[ ]` Konversations-Kontext bei Raumwechsel erhalten** — Wenn User mid-conversation den Raum wechselt, Kontext nahtlos übertragen und im neuen Raum fortsetzen.
   - Aufwand: Mittel | Impact: +3% | Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien
- [ ] Audio folgt dem User innerhalb von 5s nach Raumwechsel
- [ ] Follow-Me funktioniert ohne manuelle Konfiguration (default on)
- [ ] Konversationskontext überlebt Raumwechsel
- [ ] Speaker-Gruppen können per Sprache erstellt werden ("Musik überall")

## 11. Energiemanagement & Haussteuerung (×1)

### MCU-Jarvis Benchmark
MCU-Jarvis steuert das gesamte Stark Tower effizient — Licht, Klima, Sicherheit — alles integriert und optimiert. Er scannt das Energiesystem (Avengers 1), erkennt Anomalien, und optimiert automatisch. 50+ Gerätetypen unter einer einheitlichen Steuerung.

### MindHome-Jarvis Status: 84%

### Code-Verifizierung

**[V1] Analyse:**

1. **FunctionCalling** (`assistant/assistant/function_calling.py`, 10037 Zeilen)
   - `[OK]` 50+ Steuerungsfunktionen: Licht (inkl. Floor/All), Klima (Room/Curve), Cover (inkl. Markisen/Floor/All), Media (Play/Transfer), Security (Lock/Arm), Vacuum, Calendar, Shopping, Notifications
   - `[OK]` Parallel-Execution: `execute_parallel()` für Batch-Befehle
   - `[OK]` Consequence-Check: `_check_consequences()` prüft vor Ausführung (Fenster offen? Leerer Raum?)
   - `[OK]` Entity-Suche: `_find_entity()` mit Domain-Hint, Person-Kontext, Fuzzy-Matching
   - `[BESSER ALS MCU]` 50+ Functions mit systematischer Validation und Safety-Caps — MCU-Jarvis hat keine sichtbare Funktionsarchitektur

2. **EnergyOptimizer** (`assistant/assistant/energy_optimizer.py`, 1301 Zeilen)
   - `[OK]` Strompreis-Monitoring (EUR/MWh oder ct/kWh, auto-normalisiert)
   - `[OK]` Solar-Production, Grid-Export, Consumption-Tracking
   - `[OK]` Flexible Lastverschiebung: Waschmaschine, Trockner, Spülmaschine, EV-Charger
   - `[OK]` Essential-Entities: Kühlschrank, Server, NAS — nie abschalten
   - `[OK]` Daily Baseline-Tracking, Anomalie-Erkennung (>30% vs. Baseline)
   - `[OK]` Narrative Energy-Report für Morning-Briefing

3. **StateChangeLog** (`assistant/assistant/state_change_log.py`, 9927 Zeilen)
   - `[BESSER ALS MCU]` 213 unique Dependency-Rules (1121 Referenzen): Wer hat was geändert (Jarvis/User/Automation/Unknown), 80+ Abhängigkeitsregeln (Fenster↔Heizung, Tür↔Alarm, etc.). MCU-Jarvis hat keine sichtbare Änderungsprotokollierung.
   - `[OK]` Source-Detection: Unterscheidet Jarvis-Aktionen, User-Aktionen, Automationen, unbekannte Quellen
   - `[OK]` `check_action_dependencies()`: Prüft aktive Konflikte vor Ausführung

4. **PredictiveMaintenance** (`assistant/assistant/predictive_maintenance.py`, 499 Zeilen)
   - `[OK]` Geräte-Lebensdauer-Schätzung, Wartungsplanung
   - `[OK]` Proaktive Wartungserinnerungen

5. **SelfAutomation** (`assistant/assistant/self_automation.py`)
   - `[OK]` Erstellt neue Automatisierungen aus gelernten Mustern
   - `[OK]` Template-basiert + LLM-Fallback, Whitelist-Only (keine shell_commands)
   - `[OK]` Preview + User-Approval vor Aktivierung

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level

1. **Keine intelligente Lastpriorisierung** — Bei Engpässen wird nicht priorisiert welches Gerät zuerst abgeschaltet wird. MCU-Jarvis würde non-essential zuerst abschalten. `[SELTEN]`
2. **Kein Batterie-/USV-Management** — Keine Integration mit USV-Systemen oder Batteriespeichern für Lastspitzen-Abfederung. `[SELTEN]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` Intelligente Last-Priorisierung** — Bei hohem Strompreis oder Engpass: Priorisierungsliste (Essential > Comfort > Entertainment) für automatisches Load-Shedding.
   - Aufwand: Mittel | Impact: +3% | Alltag: `[SELTEN]`

2. **`[ ]` Batterie-/USV-Integration** — Batteriespeicher-Status in Energy-Report einbeziehen. Bei günstigem Strom laden, bei teuerem entladen.
   - Aufwand: Groß | Impact: +3% | Alltag: `[SELTEN]`

### Akzeptanzkriterien
- [ ] 50+ Gerätefunktionen arbeiten zuverlässig mit Safety-Caps
- [ ] Dependency-Rules erkennen >95% der Konflikte (Fenster+Heizung, Tür+Alarm)
- [ ] Energie-Anomalien >30% werden innerhalb von 30 Minuten erkannt
- [ ] Flexible Lasten werden bei niedrigem Strompreis automatisch verschoben

## 12. Erklärbarkeit & Transparenz (×1)

### MCU-Jarvis Benchmark
"Sir, may I remind you that you've been awake for 72 hours?" — MCU-Jarvis erklärt seine Empfehlungen, nennt Gründe, und ist transparent über seine Entscheidungen. Er sagt warum er etwas tut oder vorschlägt.

### MindHome-Jarvis Status: 77%

### Code-Verifizierung

**[V1] Analyse:**

1. **ExplainabilityEngine** (`assistant/assistant/explainability.py`, 785 Zeilen)
   - `[OK]` Decision-Logging: In-Memory FIFO (50 Einträge) + Redis-Persistenz
   - `[OK]` `log_decision()`: Aktion, Entscheidung, Reasoning-Dict, Domain, Kontext, Confidence
   - `[OK]` Query-Methoden: `explain_last(n)`, `explain_by_domain()`, `explain_by_action()`
   - `[OK]` Counterfactual-Explanations: "Ohne Eingreifen: Heizkosten X€/h verschwendet", "Tür wäre über Nacht unverschlossen geblieben"
   - `[OK]` Reasoning Chains: `build_why_chain(depth=2)` — verknüpft verwandte Entscheidungen
   - `[OK]` 3 Explanation-Styles: template (schnell), llm (natürlich), auto (adaptiv)
   - `[OK]` Detail-Level: minimal, normal, verbose (konfigurierbar)
   - `[OK]` Confidence-Display Option (default: false)
   - `[OK]` Hot-Reload via `reload_config()`

2. **StateChangeLog** (`assistant/assistant/state_change_log.py`, 9927 Zeilen)
   - `[OK]` Wer hat was geändert: Jarvis-Marker (`mark_jarvis_action()`), User-Detection, Automation-Attribution
   - `[OK]` Source-Detection: `_detect_source()` unterscheidet Jarvis/User/Automation/Unknown
   - `[BESSER ALS MCU]` 213 Dependency-Rules mit Attributions-Tracking. MCU-Jarvis erklärt sich verbal, hat aber keine sichtbare strukturierte Entscheidungsprotokollierung.

3. **Proactive Explanations** (proactive.py)
   - `[OK]` Proaktive Meldungen enthalten immer Kontext: "Fenster offen bei Regen", "Verbrauch 30% über Baseline"
   - `[OK]` LLM-Rewrite für natürliche Sprache (optional)
   - `[OK]` Personality-Filter sorgt für Jarvis-Stil-Erklärungen

4. **Pushback als Erklärung** (function_validator.py)
   - `[OK]` Pushback-Messages erklären warum eine Aktion problematisch ist: "Fenster offen — Heizenergie geht verloren"
   - `[OK]` Kontext-spezifisch: Open-Window, Empty-Room, Daylight, Peak-Tariff

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level

1. **"Warum hast du das gemacht?" nicht gut integriert** — ExplainabilityEngine existiert, aber die Integration in den Konversationsfluss (User fragt "Warum?") ist nicht offensichtlich als dedizierter Intent. `[WÖCHENTLICH]`
2. **Keine Transparenz über Degraded Mode** — Wenn Module ausfallen, weiß der User nicht welche Funktionen fehlen. MCU-Jarvis meldet aktiv eingeschränkte Funktionalität. `[SELTEN]`
3. **Confidence-Display default off** — User sieht nicht wie sicher sich Jarvis bei Entscheidungen ist. `[WÖCHENTLICH]`

### Konkrete Verbesserungsvorschläge

1. **`[ ]` "Warum?"-Intent im PreClassifier** — Wenn User "Warum hast du das gemacht?" fragt, direkt ExplainabilityEngine abfragen statt ans LLM weiterzuleiten. Schneller und präziser.
   - Aufwand: Klein | Impact: +4% | Alltag: `[WÖCHENTLICH]`

2. **`[ ]` Degraded-Mode-Notification** — Bei Boot oder bei Service-Ausfall: "Hinweis: Semantisches Gedächtnis ist gerade nicht verfügbar. Ich arbeite mit eingeschränkter Erinnerung."
   - Aufwand: Klein | Impact: +3% | Alltag: `[SELTEN]`

3. **`[ ]` Confidence-Hints in Antworten** — Bei Confidence <0.7: "Ich bin mir nicht ganz sicher, aber..." als natürlicher Prefix. Kein technisches "75% Confidence".
   - Aufwand: Klein | Impact: +3% | Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien
- [ ] "Warum?" wird in >90% der Fälle mit der tatsächlichen Entscheidungs-Logik beantwortet
- [ ] Degraded-Mode wird dem User proaktiv mitgeteilt (bei Boot und bei Runtime-Failure)
- [ ] Counterfactual-Explanations sind für die Top-5 Domains verfügbar
- [ ] StateChangeLog-Attribution ist korrekt in >95% der Fälle (Jarvis vs. User vs. Automation)
