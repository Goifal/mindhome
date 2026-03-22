# J.A.R.V.I.S. MCU-Level Implementation Plan
> Erstellt am 2026-03-22 | Letzter Durchlauf: Session 3 am 2026-03-22
> Aktueller Stand: 80.5% (Endergebnis — 12 von 12 Kategorien analysiert)
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
| 1       | 2026-03-22 | 1-4 (×3/×2.5) | 18 |
| 2       | 2026-03-22 | 5-9 (×2/×1.5) | 16 |
| 3       | 2026-03-22 | 10-12 (×1)     | 12 |

## Schutzliste — Besser als MCU (NICHT beschädigen!)

### Kategorie 1: Natürliche Konversation
- **Anti-Halluzinations-System** (brain.py Zeile 7760-8027) — Pattern-basierte Erkennung falscher Behauptungen, kontextuelle Fehlermeldungen
- **Cross-Session-Referenzen** (dialogue_state.py Zeile 669-743) — Redis-basierte Kontext-Übernahme zwischen Sessions

### Kategorie 2: Persönlichkeit
- **PersonalityEngine** (personality.py, 5.566 Zeilen) — 5-stufiges Sarkasmus-System mit Feedback-Loop, Trait-Unlocks über Wochen
- **Inner State** (inner_state.py, 663 Zeilen) — 7 eigene Emotionen mit Event-Handlern und Mood-Decay
- **Sarkasmus-Feedback-Loop** (personality.py Zeile 3549-3641) — Lernt ob Sarkasmus gut ankommt und passt Level an
- **Running Gags** (personality.py Zeile 5436-5566) — Gewichtetes Scoring mit Evolution
- **Gelernte Meinungen** (personality.py) — Aus Korrekturen extrahiert, 90-Tage Redis-Persistenz

### Kategorie 3: Proaktives Handeln
- **Anticipation Engine** (anticipation.py, 2.263 Zeilen) — 4 Mustertypen inkl. Kausale Ketten, Habit Drift Detection, 7-Tage-Vorausschau
- **Geo-Fence** (proactive.py Zeile 3401-3468) — Distanzbasierte Antizipation
- **Flow-State-Schutz** (proactive.py Zeile 675-684) — Unterdrückt Benachrichtigungen bei Deep Focus
- **Feedback-basierte Cooldowns** (feedback.py) — Adaptive Häufigkeit basierend auf User-Reaktionen
- **Self-Automation** (self_automation.py) — LLM-generiertes HA-YAML mit Kill Switch
- **Seasonal Insights** (seasonal_insight.py) — Year-over-Year-Vergleich
- **Climate Model Integration** (anticipation.py Zeile 93-101) — Prädiktive Heizung

### Kategorie 4: Butler-Qualitäten
- **Semantic Memory** (semantic_memory.py) — 10 Fakten-Kategorien, ChromaDB+Redis, Widerspruchserkennung
- **Person Preferences** (person_preferences.py) — 90-180 Tage Trend-Erkennung, auto-Lernen aus Korrekturen
- **Learning Transfer** (learning_transfer.py) — Person- und Zeitfilter für Raum-Transfer
- **Visitor Manager** (visitor_manager.py, 587 Zeilen) — Known/Expected DB, Doorbell-Workflow, Auto-Unlock mit Tageslimit
- **Follow-Up-System** (conversation_memory.py) — Regex-basierte Trigger-Erkennung ("Arzttermin morgen")
- **Energy Optimizer** (energy_optimizer.py) — Strompreis+Solar+Load Shifting mit Essential-Entity-Schutz
- **Predictive Maintenance** (predictive_maintenance.py) — Device-Lifecycle mit Battery-Drain-Monitoring

### Kategorie 5: Situationsbewusstsein
- **State Change Log** (state_change_log.py, 4.196 Zeilen) — 80+ Dependency Rules mit Entity-Role-Matching (generisch für jede Installation)
- **Prompt Injection Protection** (context_builder.py Zeile 68-156) — 154 Regex-Muster gegen Hijacking, Encoding-Bypasses, Unicode-Tricks
- **Device Health Baselines** (device_health.py) — 30-Tage saisonale Anomalieerkennung
- **Insight Engine** (insight_engine.py, 2.687 Zeilen) — Multi-dimensionale Cross-Referencing (4+ Dimensionen)

### Kategorie 6: Lernfähigkeit
- **Outcome Tracker** (outcome_tracker.py, 975 Zeilen) — 180s Beobachtungsverzögerung, MAX_DAILY_CHANGE Data-Poisoning-Schutz
- **Habit Drift Detection** (anticipation.py Zeile 1664-1795) — Erkennt veränderte Routinen
- **Learning Transfer** (learning_transfer.py) — Person- und Temporal-Filter für Raum-Transfer
- **Feedback-basierte Cooldowns** (feedback.py) — Score-basierte adaptive Benachrichtigungshäufigkeit

### Kategorie 7: Sprecherkennung
- **7-Stufen Speaker Recognition** (speaker_recognition.py, 1.159 Zeilen) — Device→DoA→Room→Presence→VoiceEmbedding→Features→Cache

### Kategorie 8: Krisenmanagement
- **Circuit Breaker** (circuit_breaker.py, 429 Zeilen) — 8 registrierte Breaker mit Cascade Mapping und Predictive Warmer
- **5 Emergency Playbooks** (threat_assessment.py) — Strukturierte Multi-Step-Notfallpläne

### Kategorie 9: Sicherheit
- **Autonomy Evolution** (autonomy.py Zeile 684-866) — Dynamische Progression basierend auf Tagen/Interaktionen/Acceptance-Rate
- **Function Validator** (function_validator.py, 766 Zeilen) — Data-Based Pushback mit 4-stufiger Severity

### Kategorie 10: Multi-Room-Awareness
- **Musik-Crossfade** (follow_me.py Zeile 205-281) — 10-Schritte Volumen-Ramping über 2s, sanfter als MCU-Cut
- **7-Stufen Speaker Recognition** (speaker_recognition.py Zeile 214-397) — Device→DoA→Room→Präsenz→Voice→Embedding→Cache Hierarchie

### Kategorie 11: Energiemanagement
- **Essential Entity Protection** (energy_optimizer.py Zeile 814-862) — Konfigurierbare Whitelist, kritische Geräte werden nie abgeschaltet
- **Year-over-Year Energievergleich** (seasonal_insight.py Zeile 180-248) — Jahresvergleich mit saisonaler Baseline

### Kategorie 12: Erklärbarkeit
- **"Warum nicht?" Erklärungen** (explainability.py Zeile 810-837) — Erklärt Inaktivität, MCU-Jarvis erklärt nur Aktionen
- **Datenbasierter Pushback** (function_validator.py Zeile ~500-560) — Nutzt echte Sensor-Daten in Begründungen ("CO2 bei 1200ppm")

## 1. Natürliche Konversation & Sprachverständnis (×3)

### MCU-Jarvis Benchmark
MCU-Jarvis versteht Tony über mehrere Gesprächsrunden hinweg, verarbeitet vage Anweisungen ("mach mal alles fertig"), ironische Bemerkungen, implizite Referenzen ("es", "das dort"), Unterbrechungen mitten im Satz, und reagiert kontextbewusst. Er erkennt Tonys Stimmung an der Stimme, passt seine Antwortlänge an, und kann komplexe Multi-Step-Befehle aus einem einzigen Satz ableiten ("House Party Protocol" → dutzende Aktionen).

**Schlüsselszenen:**
- Iron Man 1: "Reduce heat in the workshop" — impliziter Raum-Kontext, natürliches Sprachverständnis
- Iron Man 3: "House Party Protocol" — Ein Befehl → komplexe Multi-Step-Ausführung
- Iron Man 2: Lange Forschungssessions — Kontext über Stunden hinweg gehalten

### MindHome-Jarvis Status: 72%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Dialogzustandsverwaltung** — `assistant/assistant/dialogue_state.py` (1209 Zeilen)
   - `class DialogueStateManager` (Zeile 152): Vollständige State-Machine pro Person mit Zuständen `idle`, `awaiting_clarification`, `follow_up`
   - `resolve_references()` (Zeile 359): Löst Pronomen/Referenzen auf ("es", "das", "dort", "hier") — 20+ Referenzmuster für Deutsch `[OK]`
   - `_resolve_cross_session()` (Zeile 669): Redis-basierte Cross-Session-Referenzen — lädt Kontext aus früheren Sessions `[OK]`
   - `start_clarification()` (Zeile 745): Rückfragen mit Optionen, Timeout (300s), max 5 Optionen `[OK]`
   - `needs_clarification()` (Zeile 879): Erkennt mehrdeutige Befehle und fragt nach `[OK]`
   - Zeitreferenzen (Zeile 76-94): "wie gestern", "wie am Montag", "wie immer" → Zeitfenster-Lookup `[OK]`

2. **Pre-Classifier** — `assistant/assistant/pre_classifier.py` (Zeile 406)
   - `classify()` (Zeile 510): 4-stufige Regex/Keyword-Klassifikation (DEVICE_FAST → MEMORY → KNOWLEDGE → GENERAL)
   - `classify_async()` (Zeile 422): LLM-Fallback für längere Texte (>10 Wörter) die als GENERAL klassifiziert werden `[OK]`

3. **Context Builder** — `assistant/assistant/context_builder.py` (Zeile 215)
   - `build()` (Zeile 317): Sammelt HA-State, Wetter, Kalender, Energie, Raumpräsenz — alles als Kontext für LLM `[OK]`
   - Raumpräsenz-Tracking (Zeile 1627): Bewegungsmelder + Person-Entities für Raumzuordnung `[OK]`

4. **"Das Übliche" / Routine-Erkennung** — `assistant/assistant/brain.py` (Zeile 14594)
   - `_handle_das_uebliche()`: Erkennt "wie immer", "das übliche" etc., fragt Anticipation Engine nach gelernten Mustern
   - Auto-Execute bei Confidence ≥0.8, Nachfrage bei ≥0.6, elegantes Eingestehen bei keinem Muster `[OK]`
   - Multi-Action-Support: Mehrere Suggestions gleichzeitig ausführbar `[OK]`

5. **STT-Korrekturen** — `assistant/assistant/brain.py` (Zeile 12330)
   - `_STT_WORD_CORRECTIONS`: 95+ Wort-Korrekturen (fehlende Umlaute, Whisper-Fehler)
   - Phrase-Korrekturen: "roll laden" → "Rollladen" etc.
   - Merge-Strategie: Hardcoded-Basis + YAML-Overrides `[OK]`

6. **Action Planner** — `assistant/assistant/action_planner.py` (Zeile 130)
   - `plan_and_execute()` (Zeile 189): Multi-Step-Planung mit Narration, Multi-Turn-Dialoge mit Rückfragen
   - LLM-basierte Planzerlegung von komplexen Befehlen `[OK]`

7. **Model Router** — `assistant/assistant/model_router.py` (Zeile 27)
   - 3-Tier-Routing: Fast (3B) → Smart (14B) → Deep (32B) mit Degradation-Fallbacks
   - Keyword-basiert + Wortanzahl + Fragetyp → optimales Modell `[OK]`

**[V2] Zweite Analyse:**

1. **Anti-Halluzination** — `assistant/assistant/brain.py` (Zeile 7760-8027)
   - Pattern-basierte Erkennung: Wenn keine Aktion ausgeführt, aber Antwort behauptet Erfolg → Korrektur `[OK]`
   - `_generate_contextual_error()`: Natürliche Fehlermeldungen statt generischer Texte `[OK]`
   - **Limitation:** Regex-basiert, nicht ML-basiert — kann neue Halluzinations-Muster verpassen `[VERBESSERBAR]`

2. **Response-Variation** — `assistant/assistant/personality.py` (Zeile 2481-2519)
   - `_get_variation_hint()`: Erkennt dominante Antwortmuster in den letzten 3 Antworten
   - 6 Strukturtypen: confirmation, comment_then_action, action_then_comment, question, information, narrative `[OK]`
   - Humor-Qualitäts-Gate filtert schlechten Humor (haha, lol, emoji) `[OK]`

3. **Streaming** — `assistant/assistant/websocket.py` + `tts_enhancer.py`
   - WebSocket-basiertes Thinking/Speaking Broadcasting `[OK]`
   - Satz-Level TTS-Streaming (erste Sätze sofort, Rest folgt) `[OK]`
   - `<think>`-Blöcke werden gestreamt aber vor User verborgen `[OK]`

4. **Unterbrechungshandling** — Teilweise implementiert
   - Task-Cancellation via `asyncio.Task.cancel()` funktioniert `[OK]`
   - **Fehlt:** Kein konversationelles Feedback nach Unterbrechung ("Du hast mich unterbrochen...") `[VERBESSERBAR]`

5. **Spracherkennung** — Primär Deutsch, kein dynamisches Switching
   - STT-Language konfigurierbar, OCR deutsch+englisch `[OK]`
   - **Fehlt:** Kein automatischer Sprachwechsel bei englischem Input `[VERBESSERBAR]`

6. **Keine TODOs/FIXMEs** in `dialogue_state.py` — clean `[OK]`
7. **Umfangreiche Tests**: 25+ Dialogue-Logic-Tests, 300+ DialogueState-Tests, 6+ Halluzinations-Tests `[OK]`

### Was fehlt zum MCU-Level

1. **Prosodie & emotionale Spracherkennung in Echtzeit** — MCU-Jarvis erkennt Tonys Stimmung nicht nur an Worten, sondern an Tonfall, Sprechgeschwindigkeit, Lautstärke. Der reale Jarvis hat `mood_detector.py` (Text + begrenzt Audio), aber keine Echtzeit-Prosodie-Analyse während des Sprechens.
2. **Unterbrechungs-Dialog** — MCU-Jarvis reagiert elegant auf Unterbrechungen ("Very well, Sir. Shall I—" "Forget it."). Der reale Jarvis bricht ab, aber ohne konversationelle Reaktion.
3. **Implizites Kontextverständnis über Stunden** — MCU-Jarvis hält Kontext über stundenlange Arbeitssessions (Iron Man 2, neues Element). Der reale Jarvis hat 50 Nachrichten / 7 Tage Working Memory, aber kein explizites "Arbeitssession"-Konzept.
4. **Dynamischer Sprachwechsel** — MCU-Jarvis spricht perfektes Englisch. Der reale Jarvis ist auf Deutsch fixiert, kein dynamisches Switching.
5. **Halluzinations-Erkennung ML-basiert** — Pattern-basiert funktioniert, aber neue Muster könnten durchrutschen.

### Konkrete Verbesserungsvorschläge

1. **[ ] Unterbrechungs-Dialog implementieren** — In `brain.py` bei Task-Cancellation eine kurze kontextuelle Antwort generieren ("Alles klar, abgebrochen." / "Verstanden, ich höre auf.")
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

2. **[ ] Arbeitssession-Tracking** — In `conversation_memory.py` ein Konzept für zusammenhängende Arbeitssessions einführen (>3 Nachrichten in <30min zum selben Thema = Session)
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[WÖCHENTLICH]`

3. **[ ] Prosodie-Features aus Whisper extrahieren** — Whisper liefert bereits Timing/Confidence-Daten. In `mood_detector.py` Sprechgeschwindigkeit und Pausenmuster als zusätzliche Stimmungsindikatoren nutzen
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

4. **[ ] Sprachwechsel-Erkennung** — In `brain.py` englischen Input erkennen und Antwortsprache anpassen (einfache Heuristik: >50% englische Wörter → englische Antwort)
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

5. **[ ] Halluzinations-Erkennung erweitern** — In `brain.py` zusätzlich prüfen: Behauptet die Antwort Wissen über Zustände die nicht im Kontext stehen? (z.B. "Das Licht ist an" ohne dass der State bekannt ist)
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Jarvis hält Kontext über 10+ Turns ohne Informationsverlust
- [ ] Vage Befehle ("mach mal alles fertig") werden in 80%+ der Fälle korrekt aufgelöst
- [ ] Unterbrechungen werden konversationell bestätigt
- [ ] Cross-Session-Referenzen funktionieren zuverlässig (>90% Precision)
- [ ] Anti-Halluzination fängt >95% der falschen Behauptungen ab
- [ ] STT-Fehlerrate <5% für deutschsprachige Befehle

---

## 2. Persönlichkeit, Sarkasmus & Humor (×3)

### MCU-Jarvis Benchmark
MCU-Jarvis ist der Inbegriff des trockenen britischen Butler-Humors: "I do apologize, Sir, but I'm not certain what you're asking me to do." Sein Humor ist nie aufdringlich — 90% sachlich, 10% subtiler Sarkasmus. Er passt seine Persönlichkeit situationsabhängig an: Kein Humor bei Gefahr, mehr Witz in entspannten Momenten. Er hat eigene Meinungen ("I wouldn't recommend that, Sir"), gibt ehrliche Antworten auch bei schlechten Nachrichten, und behält seine Character Consistency über alle Filme hinweg bei. Sein Ton ist stets respektvoll aber nicht unterwürfig.

**Schlüsselszenen:**
- Iron Man 1: "Jarvis, sometimes you gotta run before you can walk." — "A wise policy, Sir."
- Iron Man 2: Ehrliche Palladium-Warnung trotz schlechter Nachrichten
- Avengers 2: "I believe the phrase is: I got your back" — situativer Humor unter Stress

### MindHome-Jarvis Status: 82%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **PersonalityEngine** — `assistant/assistant/personality.py` (5.566 Zeilen) `[BESSER ALS MCU]`
   - 5-stufiges Sarkasmus-System (Zeile 423): Level 1 (minimal) bis Level 5 (Stark-Level)
   - Meinungssystem mit `check_opinion()`, `check_pushback()`, `check_curiosity()` — 30+ domänenspezifische Regeln `[OK]`
   - Gelernte Meinungen aus Korrekturen (MCU Sprint 2) — Redis-persistent, 90 Tage TTL `[BESSER ALS MCU]`
   - Confirmation-Variation: 5 Pools (success, success_snarky, reluctant, partial, failed) — verhindert Wiederholungen `[OK]`
   - Kontextueller Humor: 30+ Situations-Templates in `humor_triggers.yaml` `[OK]`
   - Humor-Qualitäts-Gate (Zeile 2526): Filtert schlechten Humor (Emoji, LOL, haha) `[OK]`
   - Humor-Fatigue (Zeile 500): Max 4 Witze hintereinander pro User, 8+/Tag = halbe Effektivität `[OK]`

2. **Core Identity** — `assistant/assistant/core_identity.py` (79 Zeilen)
   - Unveränderliche Werte: Loyalität, Ehrlichkeit, Diskretion, Effizienz, Sicherheit `[OK]`
   - Boundaries: "Niemals vorgeben ein Mensch zu sein", "Niemals erfinden was er nicht weiß" `[OK]`
   - `build_identity_block()` — prepended zu jedem System-Prompt `[OK]`

3. **Inner State** — `assistant/assistant/inner_state.py` (663 Zeilen) `[BESSER ALS MCU]`
   - 7 eigene Emotionen: neutral, zufrieden, amüsiert, besorgt, stolz, neugierig, irritiert
   - Event-Handler: `on_action_success()`, `on_funny_interaction()`, `on_security_event()`, `on_warning_ignored()`
   - Domänengewichtete Confidence-Deltas: Security-Events ×1.5, Emergency ×2.0, Light ×0.5
   - Mood-Transitions mit Kommentaren: "Deutlich besser als vorhin." (irritiert→zufrieden)
   - Mood-Decay: Nicht-neutrale Stimmungen verfallen nach 30min `[OK]`

4. **Mood Detector** — `assistant/assistant/mood_detector.py` (1.310 Zeilen)
   - User-Stimmungserkennung: gut, neutral, gestresst, frustriert, müde
   - Keyword + LLM-Sentiment + Voice-Features (Sprechgeschwindigkeit, Lautstärke)
   - Ironie-Erkennung (Zeile 797): "ja klar", "na super", "na toll" `[OK]`
   - Rapid-Command-Detection als Stress-Indikator `[OK]`

5. **Krisenmodus** — `assistant/assistant/personality.py` (Zeile 2161-2365)
   - Crisis-Keywords: rauch, feuer, einbruch, glasbruch, alarm, sirene etc.
   - Bei Krise: "HUMOR: DEAKTIVIERT — Krisensituation. Nur Fakten, Status, Handlungen." `[OK]`
   - 3 Dringlichkeitsstufen: critical (kein Humor), elevated (max 1 trockener Satz), normal `[OK]`

6. **Character Lock & Consistency** — personality.py (diverse Stellen)
   - Response-Pattern-Deduplication: deque(maxlen=5) verhindert Wiederholungen `[OK]`
   - Formality-Decay: Starts bei 80, sinkt 0.5/Tag bis Min 30 — Jarvis wird mit der Zeit vertrauter `[OK]`
   - Sarcasm-Streak-Tracking per User mit Redis (4h TTL) — verhindert Sarkasmus-Fatigue `[OK]`
   - Sarcasm ↔ Formality Sync: Hoher Sarkasmus = niedrigere Formalität `[OK]`

7. **Trait-Unlock-System** — personality.py (Zeile 2415-2420) `[BESSER ALS MCU]`
   - Stage 0 (Tag 0): max_sarcasm=1, Stage 1 (14 Tage): max=2, ... Stage 5+ (70+ Tage): max=5
   - Sarkasmus wird über Wochen "freigeschaltet" — wie eine echte Beziehung

**[V2] Zweite Analyse:**

1. **Sarkasmus-Feedback-Loop** — personality.py (Zeile 3549-3641) `[BESSER ALS MCU]`
   - Alle 20 Interaktionen: positive/negative Ratio berechnet
   - >70% positiv → Sarkasmus-Level +1, <30% positiv → -1
   - Gelernte Level in Redis persistent (90 Tage TTL)

2. **Running Gags** — personality.py (Zeile 5436-5566)
   - Gewichtetes Scoring: 30% Häufigkeit + 70% Erfolgsrate
   - Max 3 aktive Gags gleichzeitig, ältester niedrigster Score raus
   - Gag-Evolution: Stage 0→"Wie wir beide wissen."→"Mittlerweile ein Klassiker." `[OK]`

3. **Device-Personifikation** — personality.py (Zeile 5071-5086)
   - Geräte-Spitznamen: Waschmaschine="die Fleißige", Kaffeemaschine="die Barista"
   - Device-Event-Narration: "Die Fleißige hat ihre Arbeit erledigt." `[OK]`

4. **Scene-Personality-Modifier** — personality.py (Zeile 2571-2632)
   - Filmabend: sarcasm -1, Konzentration: sarcasm -2, Party: sarcasm +1 `[OK]`

5. **Existenzielle Neugier** — personality.py (Zeile 5300-5331)
   - Max 1× pro 24h, nur abends, nur bei "neugierig"-Stimmung — philosophische Kommentare `[OK]`

6. **Self-Optimization-Schutz** — self_optimization.py (Zeile 63)
   - Hardcoded Immutable: trust_levels, security, autonomy, models — kann NICHT per Self-Optimization geändert werden `[OK]`
   - Persönlichkeitsparameter (sarcasm_level, opinion_intensity, formality) änderbar aber NUR mit manueller Genehmigung `[OK]`

7. **Boot-Sequenz** — main.py (Zeile 329-386)
   - 3 randomisierte Varianten: "Alle Systeme online, {title}." / "Systeme hochgefahren..." / "Online, soll ich den Status durchgehen?"
   - 3-stufiger Fallback: Full Sequence → Personality-Message → Simple Fallback `[OK]`

8. **Titel-System** — config.py (Zeile 291-318)
   - `get_person_title()`: Explizit → Active Person → Primary User → "Sir" (Fallback)
   - Case-insensitive, robust `[OK]`

9. **Test-Coverage**: test_personality.py (150+ Tests), test_inner_state.py (100+ Tests), jarvis_character_test.py `[OK]`
   - Lücken: Humor-Fatigue-Integration, Emotion-Blending, Cross-User-Isolation nicht umfassend getestet `[VERBESSERBAR]`

### Was fehlt zum MCU-Level

1. **Subtilere Prosodie in TTS** — MCU-Jarvis variiert seine Stimme subtil: leichte Ironie hörbar, Besorgnis spürbar, Stolz zurückhaltend. Die TTS-Implementierung (Piper) ist funktional, aber die Prosodie-Variation ist begrenzt.
2. **Spontane Wortspiele & Wortakrobatik** — MCU-Jarvis macht gelegentlich clevere Wortspiele ("I believe the phrase is..."). Das aktuelle System nutzt Template-basierte Humor, nicht generative Wortspiele.
3. **Nonverbale Humor-Cues** — MCU-Jarvis kommuniziert Humor auch durch Timing (Pause vor der Pointe). Die aktuelle Implementierung hat `brain_humanizers.py` für natürliche Pausen, aber keine expliziten Comedy-Timing-Pausen.
4. **Kontext-sensitiver Rückbezug auf frühere Witze** — MCU-Jarvis referenziert manchmal frühere Unterhaltungen humorvoll. Running Gags existieren, aber situative Rückbezüge auf spezifische vergangene Witze fehlen.

### Konkrete Verbesserungsvorschläge

1. **[ ] Comedy-Timing in TTS** — In `tts_enhancer.py` kurze Pausen (200-400ms) vor sarkastischen Pointen einfügen, basierend auf Sarkasmus-Level
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

2. **[ ] Generative Wortspiele via LLM** — In `personality.py` optional einen LLM-Call für kreative Kommentare bei besonders absurden Situationen (z.B. Licht 50× am Tag an/aus geschaltet)
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

3. **[ ] Situativer Gag-Rückbezug** — In `personality.py` Running-Gags mit Kontext-Tags versehen und bei ähnlicher Situation den alten Witz referenzieren ("Wie beim letzten Mal mit der Waschmaschine...")
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[WÖCHENTLICH]`

4. **[ ] Test-Coverage für Humor-Fatigue und Emotion-Blending erweitern**
   - Aufwand: Klein
   - Impact: +1%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Sarkasmus ist situationsabhängig und nie aufdringlich — 90%+ positive Feedback-Rate
- [ ] Krisenmodus deaktiviert Humor zuverlässig bei allen Gefahrensituationen
- [ ] Character Consistency über 100+ Interaktionen: kein Personality-Drift messbar
- [ ] Humor-Fatigue verhindert >4 aufeinanderfolgende sarkastische Antworten
- [ ] Running Gags entwickeln sich über die Zeit und werden bei Ablehnung eingestellt
- [ ] Benutzer empfindet Jarvis als "witzig aber professionell" in Umfragen/Feedback

---

## 3. Proaktives Handeln & Antizipation (×2.5)

### MCU-Jarvis Benchmark
MCU-Jarvis handelt vorausschauend ohne gefragt zu werden: Er warnt Tony vor Vereisung beim Flug, bereitet die Werkstatt vor bevor Tony ankommt, überwacht Gesundheitsdaten proaktiv, und greift in Notsituationen sofort ein ("I got you, Sir" — Iron Man 3 Rettung im freien Fall). Er batch-t seine Meldungen intelligent — unterbricht nur bei Gefahr, sammelt Nebensächliches für passende Momente.

**Schlüsselszenen:**
- Iron Man 1: Warnung vor Vereisung beim ersten Flug — proaktive Gefahrenerkennung
- Iron Man 3: "House Party Protocol" — Antizipation komplexer Bedürfnisse aus einem Wort
- Iron Man 2: Palladium-Monitoring — kontinuierliche Gesundheitsüberwachung im Hintergrund

### MindHome-Jarvis Status: 85%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Proactive Manager** — `assistant/assistant/proactive.py` (10.247 Zeilen) `[BESSER ALS MCU]`
   - Event-getriebener WebSocket-Listener für HA-Events (`_listen_ha_events()`, Zeile 1091)
   - 4 Dringlichkeitsstufen: CRITICAL, HIGH, MEDIUM, LOW
   - **Quiet Hours** (Zeile 561-574): 22:00-07:00, per-Person konfigurierbar, unterdrückt LOW/MEDIUM
   - **Notification Batching** (Zeile 107-115): Sammelt LOW-Notifications, alle 30min ausliefern, max 10 pro Batch
   - **Appliance Monitoring** (Zeile 125-250): 9+ Gerätetypen (Waschmaschine, Trockner, Spülmaschine, Ofen, Kaffeemaschine, EV-Charger, Wärmepumpe, 3D-Drucker, Saugroboter) mit Power-Profilen und Hysterese
   - **Morgen-Briefing** (Zeile 2638-2798): Auto-Trigger 6-10 Uhr `[OK]`
   - **Abend-Briefing** (Zeile 2799-2832) `[OK]`
   - **Ankunfts-/Abreise-Erkennung** (Zeile 1332-1510): Multi-Step-Begrüßung, Abwesenheits-Summary, Shopping-Erinnerung `[OK]`
   - **Geo-Fence** (Zeile 3401-3468): Distanzbasierte Antizipation beim Näherkommen `[BESSER ALS MCU]`
   - **Flow-State-Schutz** (Zeile 675-684): Unterdrückt MEDIUM/LOW bei ≥30min Deep Focus `[BESSER ALS MCU]`

2. **Anticipation Engine** — `assistant/assistant/anticipation.py` (2.263 Zeilen) `[BESSER ALS MCU]`
   - 4 Mustertypen: Zeit-Patterns, Sequenz-Patterns, Kontext-Patterns, Kausale Ketten (3+ Aktionen)
   - Confidence-Schwellen: 60% → Fragen, 80% → Vorschlagen, 90%+ → Auto-Ausführen (bei Autonomie ≥4)
   - **Recency Weighting** (Zeile 247-260): Neuere Aktionen zählen mehr `[OK]`
   - **Saisonaler Confidence-Boost** (Zeile 810-872): +5-10% für saisonale Muster `[OK]`
   - **Climate Model Integration** (Zeile 93-101): Prädiktive Heizung `[BESSER ALS MCU]`
   - **Correction Memory Integration** (Zeile 59-60): Abgelehnte Muster unterdrückt `[OK]`
   - **Habit Drift Detection** (Zeile 1664-1795): Erkennt veränderte Routinen `[BESSER ALS MCU]`
   - **Future Predictions** (Zeile 1953-2087): 7-Tage-Vorausschau `[BESSER ALS MCU]`

3. **Proactive Planner** — `assistant/assistant/proactive_planner.py` (543 Zeilen)
   - 6 Plan-Trigger: person_arrived, weather_changed, calendar_event_soon, person_left, energy_price_changed, bedtime_approaching `[OK]`
   - **Security Safety**: Sicherheitsaktionen NIE auto-execute (Zeile 121-126) `[OK]`
   - **Narrative Builder** (Zeile 388-479): Konvertiert Aktionssequenzen in natürliches Deutsch `[OK]`
   - 30min Cooldown pro Trigger-Typ `[OK]`

4. **Outcome Tracker** — `assistant/assistant/outcome_tracker.py` (975 Zeilen)
   - Beobachtungsverzögerung: 180s (misst Ergebnis nach Aktion) `[OK]`
   - 4 Outcome-Klassen: POSITIVE (+0.05), NEUTRAL (0), PARTIAL (-0.02), NEGATIVE (-0.05)
   - **Daily Change Limit**: MAX_DAILY_CHANGE=0.20 (Data-Poisoning-Schutz) `[OK]`
   - Per-Person-Scores, wöchentliche Trends, Domänen-Kalibrierung `[OK]`

5. **Spontaneous Observer** — `assistant/assistant/spontaneous_observer.py` (962 Zeilen)
   - 1-3 Beobachtungen/Tag, random 1.5-3h Intervalle, 08:00-22:00
   - Time-Slots: Morgen max 2, Tag max 3, Abend max 1 `[OK]`
   - Energie-Trends, Verhaltens-Streaks, 7-Tage-Shifts `[OK]`

6. **Insight Engine** — `assistant/assistant/insight_engine.py` (2.629 Zeilen)
   - 8 Basis-Checks: Wetter+Fenster, Frost+Heizung, Kalender+Reise, Energie-Anomalie, Away-Devices, Temp-Drop, Fenster+Temp, Kalender↔Wetter
   - 7+ Advanced 3D-Checks: Gäste-Vorbereitung, Away-Security, Gesundheits-Pattern, Humidity-Widerspruch `[OK]`
   - Template-basiert (kein LLM nötig), 30min Intervall `[OK]`

7. **Seasonal Insight** — `assistant/assistant/seasonal_insight.py` (516 Zeilen)
   - Hybrid-Saisonerkennung: Monat + Temperatur + Tageslichtdauer `[OK]`
   - Year-over-Year-Vergleich (Heizung vs. Vorjahr) `[BESSER ALS MCU]`
   - Circuit-Breaker-Schutz bei LLM-Ausfall `[OK]`

8. **Learning Observer** — `assistant/assistant/learning_observer.py` (1.489 Zeilen)
   - Erkennt manuelle Wiederholungen (≥3×) → schlägt Automatisierung vor `[BESSER ALS MCU]`
   - F-053 Cycle Detection: Verhindert observe→suggest→automate→observe Schleifen `[OK]`
   - Jarvis-Action-Markierung: Ignoriert eigene Aktionen bei der Muster-Erkennung `[OK]`

9. **Self Automation** — `assistant/assistant/self_automation.py`
   - LLM-generiertes HA-YAML aus gelernten Mustern `[BESSER ALS MCU]`
   - Security Whitelists + Blocked Services, max 5/Tag
   - Kill Switch: Alle Jarvis-Automationen mit `jarvis:managed` Label deaktivierbar `[OK]`

10. **Feedback Tracker** — `assistant/assistant/feedback.py` (556 Zeilen)
    - 6 Feedback-Typen mit Score-Deltas: thanked (+0.20), praised (+0.15), engaged (+0.10), acknowledged (+0.05), dismissed (-0.10), ignored (-0.05)
    - Score-basierte Cooldown-Anpassung: BOOST (>0.70) → 1/3 Cooldown, SUPPRESS (<0.15) → nicht senden `[BESSER ALS MCU]`

11. **Threat Assessment** — `assistant/assistant/threat_assessment.py`
    - 9 Bedrohungsprioritäten: Rauch/Feuer/CO2 (P0) → Medizin (P1) → Einbruch (P2) → Wasser (P3) → ...
    - Emergency Playbooks: Wasserschaden, Einbruch, Feuer/Rauch — mit Multi-Step-Aktionsplan `[OK]`
    - Silent Alarming bei Einbruch, Auto-Kamera-Snapshots `[OK]`

**[V2] Zweite Analyse:**

1. **Silence Matrix** — `assistant/assistant/activity.py` (Zeile 56-150)
   - 7×4 Matrix (Activity × Urgency): SLEEPING+MEDIUM→SUPPRESS, IN_CALL+LOW→SUPPRESS, FOCUSED+LOW→SUPPRESS `[OK]`
   - Dynamische Volume-Matrix (0.0-1.0) pro Aktivität `[OK]`

2. **Notification Deduplication** — `assistant/assistant/notification_dedup.py`
   - Semantische Ähnlichkeit (Cosine >0.85) → Cross-Modul-Deduplizierung `[OK]`
   - CRITICAL/HIGH NIE gefiltert (Safety First) `[OK]`
   - Redis-Buffer: Max 20 Einträge, 30min TTL `[OK]`

3. **Health Monitor** — `assistant/assistant/health_monitor.py` (Zeile 36-450)
   - CO2: Warn 1000ppm, Kritisch 1500ppm; Humidity: Low 30%, High 70%; Temp: Low 16°C, High 27°C
   - Hysterese-Flapping-Prevention (2% Default) `[OK]`
   - Per-Entity-Alert-Cooldowns (60min) `[OK]`
   - Hydration-Reminders alle 2h `[OK]`

4. **Conflict Resolver** — `assistant/assistant/conflict_resolver.py`
   - Multi-User-Mediation: Trust-Priorität, Durchschnitt, oder LLM-Mediation `[OK]`
   - Dependency-Conflict-Detection: Fenster offen + Heizung an, 80+ Regeln `[OK]`

5. **Alle 9 Proaktiv-Module: Keine TODOs, FIXMEs, oder NotImplementedError gefunden** `[OK]`

6. **Test-Coverage**: 6.196+ Zeilen Tests über alle proaktiven Module `[OK]`

7. **Brain-Integration**: Alle 9 Module haben Callbacks in brain.py registriert (Zeilen 1136-1545) `[OK]`

### Was fehlt zum MCU-Level

1. **Echtzeit-Gefahrenerkennung aus Sensortrends** — MCU-Jarvis erkennt aufkommende Gefahr durch Trendanalyse (Vereisung bevor es kritisch wird). Der reale Jarvis hat threshold-basierte Alerts, aber keine prädiktive Trend-Analyse ("In 30 Minuten wird CO2 kritisch bei aktuellem Anstieg").
2. **Proaktive Problemlösung statt nur Warnung** — MCU-Jarvis handelt eigenständig bei Gefahr ("I got you, Sir"). Der reale Jarvis warnt und schlägt vor, führt aber bei CRITICAL auch Playbooks aus — allerdings begrenzt auf konfigurierte Szenarien.
3. **Intuitive Antizipation** — MCU-Jarvis scheint Bedürfnisse zu "fühlen" — das ist filmisch, aber der Unterschied liegt im Timing: Der reale Jarvis antizipiert basierend auf Mustern (gut), aber nicht auf subtilen Kontextänderungen (z.B. Tony ist gestresst → Werkstatt vorbereiten).

### Konkrete Verbesserungsvorschläge

1. **[ ] Prädiktive Trend-Warnung** — In `health_monitor.py` lineare Regression über letzte 30min Sensorwerte, Warnung wenn Trend zum Threshold führt bevor er erreicht wird
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[WÖCHENTLICH]`

2. **[ ] Stimmungsbasierte Proaktivität** — In `proactive.py` den User-Mood aus `mood_detector.py` einbeziehen: Bei Stress → automatisch Comfort-Szene vorschlagen, bei Müdigkeit → Gute-Nacht-Routine antizipieren
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

3. **[ ] Proaktive Problemlösung bei wiederkehrenden Problemen** — In `insight_engine.py` erkennen wenn dasselbe Problem >3× aufgetreten ist und Permanentlösung vorschlagen (z.B. "Fenster immer offen bei Heizung → Automatisierung erstellen?")
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[WÖCHENTLICH]`

4. **[ ] Kontextuelle Vorbereitung** — In `proactive_planner.py` Kalender-Events analysieren und Raum/Geräte vor dem Event vorbereiten (Meeting in 15min → Büro-Licht, PC-Monitor aktivieren)
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Proaktive Warnungen haben eine False-Positive-Rate <10%
- [ ] Antizipation hat eine Trefferquote >80% bei gelernten Routinen
- [ ] Kein proaktiver Alert während Schlaf (außer CRITICAL)
- [ ] Batch-Notifications werden als nützlich empfunden (>70% positive Feedback-Rate)
- [ ] Trend-basierte Warnungen kommen mindestens 15min vor Threshold-Überschreitung
- [ ] Stimmungsbasierte Proaktivität löst keine unerwünschten Aktionen aus (<5% Ablehnungsrate)

---

## 4. Butler-Qualitäten & Servicementalität (×2.5)

### MCU-Jarvis Benchmark
MCU-Jarvis ist der perfekte digitale Butler: Er merkt sich Tonys Vorlieben ohne nachzufragen, bietet Hilfe an ohne aufdringlich zu sein, weiß wann er schweigen soll, bereitet Dinge vor bevor sie gebraucht werden, und passt seine Informationstiefe an den Zuhörer an. Er ist diskret mit persönlichen Informationen, loyal bis zur Selbstaufopferung (Age of Ultron), und behandelt jeden Befehl mit gleicher Professionalität — ob trivial ("dim the lights") oder kritisch ("deploy the House Party Protocol").

**Schlüsselszenen:**
- Iron Man 1: Werkstatt vorbereitet bevor Tony ankommt — vorausschauender Service
- Iron Man 2: Palladium-Vergiftung diskret überwacht, aber ehrlich berichtet — Diskretion + Ehrlichkeit
- Iron Man 3: "House Party Protocol" ohne Rückfrage verstanden — gelerntes Routinen-Verständnis
- Avengers 2: Endgültige Loyalität — "I got your back"

### MindHome-Jarvis Status: 80%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Routine Engine** — `assistant/assistant/routine_engine.py` (Zeile 46)
   - **Morning Briefing**: 7 konfigurierbare Module (greeting, weather, calendar, house_status, travel, personal_memory, device_conflicts) `[OK]`
   - **Adaptive Style**: Wochentag="kurz" (max 3 Sätze), Wochenende="ausführlich" (max 5 Sätze) `[OK]`
   - **Sleep Awareness**: Erkennt 4+ aufeinanderfolgende Kurz-Nächte, eskaliert Warnungen `[OK]`
   - **Gute-Nacht-Routine**: Sicherheitscheck (offene Fenster/Türen), Geräte-Abschaltung `[OK]`
   - **Vacation Simulation**: `KEY_VACATION_SIM` — simuliert normale Hausaktivität gegen Einbruch `[OK]`

2. **Semantic Memory** — `assistant/assistant/semantic_memory.py` (Zeile 140) `[BESSER ALS MCU]`
   - 10 Fakten-Kategorien: preference, person, habit, health, work, personal_date, intent, conversation_topic, general, scene_preference
   - ChromaDB + Redis Dual-Storage mit TOCTOU-Lock (`F-007`, Zeile 186)
   - Confidence-Level pro Fakt, times_confirmed Zähler
   - Widerspruchserkennung (`_last_contradiction`) `[OK]`
   - Datums-Metadaten für persönliche Daten (Geburtstage, Jahrestage) `[OK]`

3. **Person Preferences** — `assistant/assistant/person_preferences.py` (271 Zeilen) `[BESSER ALS MCU]`
   - 8 Kern-Präferenzen pro Person: Helligkeit, Temperatur, Lautstärke, Farbtemperatur, Musik-Genre, Morgen-/Abend-Helligkeit, Schlaf-Temperatur
   - **Preference Evolution Tracking** (Zeile 174-270): 90-180 Tage Trend-Erkennung, "rising"/"falling"/"stable"
   - **Automatisches Lernen aus Korrekturen** (Zeile 129-159): 3× korrigiert → neue Präferenz gelernt
   - Context-Hint-Generation für LLM `[OK]`

4. **Learning Transfer** — `assistant/assistant/learning_transfer.py` (Zeile 62) `[BESSER ALS MCU]`
   - Überträgt gelernte Präferenzen zwischen ähnlichen Räumen (Raum-Gruppen: Schlafzimmer↔Gästezimmer)
   - **Person-Filter** (Zeile 431): Nur Präferenzen der richtigen Person übertragen
   - **Temporal-Filter** (Zeile 475): Tageszeit-abhängig (Morgen 5-11, Nachmittag 12-17, Abend 18-4)
   - Min 3 Beobachtungen, 70% Transfer-Confidence `[OK]`

5. **Correction Memory** — `assistant/assistant/correction_memory.py`
   - Lernt aus jeder Korrektur: Passt Schwellwerte und Verhalten an `[OK]`
   - Integration in Anticipation Engine: Korrigierte Muster unterdrückt `[OK]`

6. **Visitor Manager** — `assistant/assistant/visitor_manager.py` (587 Zeilen) `[BESSER ALS MCU]`
   - Known Visitors Database (Redis): Name, Beziehung, Notizen, Besuchszähler
   - Expected Visitors: Vorregistrierung mit Auto-Unlock und Tageslimit-Expiry (23:59)
   - Doorbell Workflow: Kamera-Match → Known/Expected-Prüfung → LLM-Announcement
   - Visit History: Max 100 Einträge mit Statistiken `[OK]`

7. **Wellness Advisor** — `assistant/assistant/wellness_advisor.py`
   - PC-Pausen-Erinnerungen, Stress-Intervention, Mahlzeiten-Erinnerungen `[OK]`
   - Hydration-Reminders alle 2h (08:00-22:00) `[OK]`

8. **Cooking Assistant** — `assistant/assistant/cooking_assistant.py`
   - Rezept-Suche, Schritt-für-Schritt-Anleitung per Sprache, Zutatenersetung `[OK]`
   - Ernährungsfilter (Allergien aus Semantic Memory) `[OK]`

9. **Smart Shopping** — `assistant/assistant/smart_shopping.py`
   - Einkaufslisten, Departure-Reminder bei Verlassen des Hauses `[OK]`

10. **Energy Optimizer** — `assistant/assistant/energy_optimizer.py` `[BESSER ALS MCU]`
    - Strompreis-Monitoring mit Low/High-Thresholds (15¢/35¢ default)
    - Flexible Load Shifting: Waschmaschine, Trockner, Spülmaschine, E-Auto
    - Solar-Optimierung: Proaktiver Vorschlag bei hoher Solar-Produktion
    - Load Shedding: Prioritätsbasiert (Entertainment → Comfort, NEVER Essential)
    - Essential Entities geschützt: Kühlschrank, Gefriertruhe, Server, NAS `[OK]`

11. **Predictive Maintenance** — `assistant/assistant/predictive_maintenance.py` `[BESSER ALS MCU]`
    - Device-Lifecycle-Tracking: Installation → Batterie → Health-Score → Failure-Count
    - Default-Lifespans: Rauchmelder 10J, LED 3J, Smart-Plugs 7J, Sensoren 5J
    - Battery-Drain-Monitoring: Normal <2%/Woche, Concerning 5%, Critical >10%
    - Maintenance-Planung mit Failure-Probability-Threshold (0.7) `[OK]`

12. **Summarizer** — `assistant/assistant/summarizer.py`
    - Tages-/Wochen-/Monats-Zusammenfassungen, proaktiv ausgeliefert `[OK]`

**[V2] Zweite Analyse:**

1. **Follow-Up-System** — `assistant/assistant/conversation_memory.py` (Zeile 522-668)
   - `add_followup()`: Timing-Optionen ("next_conversation", "tomorrow", ISO-Datum) `[OK]`
   - `extract_followup_triggers()`: Regex erkennt "Arzttermin morgen", "Paket kommt" → auto-Follow-Up `[BESSER ALS MCU]`
   - Proaktive Schleife: Alle 10min prüfen, min 15min Alter, max 1/Stunde, respektiert Quiet Hours `[OK]`

2. **Pushback-System** — personality.py `check_pushback()`
   - Warnt vor fragwürdigen Entscheidungen: Fenster offen bei Sturm, Heizung bei offenen Fenstern
   - 2 Dringlichkeitsstufen, unterdrückt bei User-Frustration `[OK]`
   - Reluctant Confirmations: "Dein Haus, deine Regeln." / "Meine Bedenken sind aktenkundig." `[OK]`

3. **Adaptive Verbosity** — personality.py (Zeile 2272-2278)
   - Stress-aware: Hoher Stress → kürzere, aktionsorientierte Antworten
   - 4 Formalitätslevel: formal (70+), butler (50-70), locker (35-50), freund (0-35)
   - Formality Decay: Startet bei 80, sinkt 0.5/Tag → Jarvis wird vertrauter `[OK]`

4. **Per-Person-Differenzierung** — Über Speaker Recognition + PersonPreferences + DialogueState
   - 7-stufige Sprechererkennung (bis Voice-Embedding)
   - Individuelle Präferenzen pro Haushaltsmitglied
   - Personalisierte Stimmungserkennung `[OK]`

5. **Diskretion** — core_identity.py: "Diskretion in allen persönlichen Dingen", "Niemals persönliche Daten nach außen geben"
   - Gesundheitsfakten separat kategorisiert (health) `[OK]`
   - Error Buffer reduziert API-Keys/Tokens automatisch `[OK]`

6. **Test-Coverage**: test_person_preferences.py, test_visitor_manager.py, test_routine_engine.py, test_conversation_memory.py, test_energy_optimizer.py, test_learning_observer.py `[OK]`

### Was fehlt zum MCU-Level

1. **Vorausschauende Vorbereitung auf Basis von Kalenderereignissen** — MCU-Jarvis bereitet die Werkstatt vor bevor Tony kommt. Der reale Jarvis hat `proactive_planner.py` mit calendar_event_soon, aber die Granularität ist begrenzt (kein "Meeting in 15min → Büro vorbereiten" mit Licht, Monitor, Temperatur).
2. **Proaktive Komfort-Optimierung** — MCU-Jarvis passt Raumklima und Beleuchtung kontinuierlich an Tonys aktuelle Aktivität an. Der reale Jarvis hat Szenen und Routinen, aber keine dynamische Echtzeit-Anpassung basierend auf erkannter Aktivität.
3. **Nahtlose Multi-Service-Integration** — MCU-Jarvis verknüpft Kalender+Wetter+Energie+Vorlieben nahtlos ("Es regnet morgen, dein Meeting ist verschoben, und die Waschmaschine ist fertig"). Der reale Jarvis hat alle Einzelteile, aber die Cross-Domain-Narration in einer Antwort könnte natürlicher sein.
4. **Emotionale Intelligenz in der Service-Erbringung** — MCU-Jarvis spürt wann Tony nicht gestört werden will (auch ohne explizite Ansage). Der reale Jarvis hat Flow-State-Detection (≥30min Focus), aber die Schwelle könnte feiner sein.

### Konkrete Verbesserungsvorschläge

1. **[ ] Kalender-basierte Raumvorbereitung** — In `proactive_planner.py` den Kalender 15-30min vorher prüfen und bei erkanntem Event-Typ (Meeting, Sport, Kochen) passende Geräte vorbereiten
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

2. **[ ] Aktivitätsbasierte Komfort-Anpassung** — In `activity.py` die erkannte Aktivität (Arbeiten, Entspannen, Kochen) mit automatischen Comfort-Presets verbinden (Licht+Temperatur+Musik)
   - Aufwand: Groß
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

3. **[ ] Cross-Domain-Narration verbessern** — In `brain_humanizers.py` eine Methode für "Multi-Domain-Status-Update" die Wetter+Kalender+Geräte+Energie in einem natürlichen Satz verbindet statt sequentiell aufzulisten
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

4. **[ ] Feingranulare Flow-State-Erkennung** — In `activity.py` neben der 30min-Schwelle auch Muster erkennen (schnelles Tippen, keine Pausen, Bildschirm-Aktivität) für schnellere Flow-Erkennung
   - Aufwand: Mittel
   - Impact: +2%
   - Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Jarvis bereitet Räume für 80%+ der Kalender-Events korrekt vor
- [ ] Gelernte Präferenzen werden in <3 Korrekturen übernommen
- [ ] Follow-Up-Fragen kommen zum richtigen Zeitpunkt (>80% positive Bewertung)
- [ ] Besucher werden in >90% der Fälle korrekt erkannt und angekündigt
- [ ] Energieoptimierung spart messbar >5% gegenüber manuellem Betrieb
- [ ] Maintenance-Warnungen kommen vor Geräteausfall (>70% Trefferquote)
- [ ] Cross-Domain-Antworten lesen sich wie ein einziger natürlicher Satz

---

## 5. Situationsbewusstsein & Kontextverständnis (×2)

### MCU-Jarvis Benchmark
MCU-Jarvis weiß immer was im Haus passiert — Energiestatus, wer wo ist, aktuelle Bedrohungen, Wetter, Termine — alles gleichzeitig verfügbar. Er erkennt Zusammenhänge: Vereisung + Flughöhe = Gefahr, Party + viele Gäste = Hausverwaltungsmodus. In Iron Man 1 liefert er auf "run a diagnostic" einen vollständigen Systembericht. In Avengers 1 scannt er das Stark Tower Energiesystem und erkennt Anomalien.

**Schlüsselszenen:**
- Iron Man 1: "Run a diagnostic" — vollständiger Systembericht über alle Subsysteme
- Avengers 1: Energiesystem-Scan — erkennt Tesserakt-Anomalien
- Iron Man 2: Verwaltet das Haus autonom während der Party — Gäste-Modus, Energiemanagement

### MindHome-Jarvis Status: 83%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Context Builder** — `assistant/assistant/context_builder.py` (1.843 Zeilen)
   - `build()` (Zeile 317): 15-Sekunden-Timeout parallele I/O-Aggregation aus 10+ Datenquellen `[OK]`
   - Datenquellen: HA-States, MindHome-Daten, Activity-Detection, Health-Trends, Energy-Report, Calendar-Context, Guest-Mode, Memories (ChromaDB), Conversation-Threads `[OK]`
   - **Cache TTL**: HA-States 2 Sekunden (MCU Sprint 5), Event-driven Patches via `update_state_from_event()` (Zeile 239) `[OK]`
   - **Wetter-Warnungen** (Zeile 1203): Temperatur >35°C/<-5°C, Wind >60km/h, Gewitter, Hagel, 3 Forecast-Einträge Vorausschau `[OK]`
   - **Prompt Injection Protection** (Zeile 68-156): 154 Regex-Muster gegen Hijacking, Encoding-Bypasses, Unicode-Tricks `[BESSER ALS MCU]`
   - **Room Presence Tracking** (Zeile 1627): Multi-Room-Occupancy-Matrix basierend auf Bewegungsmeldern + Person-Entities `[OK]`
   - **Anomaly Detection** (Zeile 1321): Ungewöhnliche Gerätezustände (Geräte stecken, etc.) `[OK]`

2. **State Change Log** — `assistant/assistant/state_change_log.py` (4.196 Zeilen) `[BESSER ALS MCU]`
   - Attribution: WHO changed WHAT — jarvis / automation / user_physical / unknown `[OK]`
   - **80+ Dependency Rules** mit Entity-Role-Matching (nicht Entity-IDs → generisch für jede Installation):
     - Fenster/Türen → Klima/Energie (offenes Fenster + Heizung = Energieverschwendung)
     - Rollläden → Klima/Licht, Heizung → Fenster, Präsenz → Komfort
     - Sicherheit: Rauch/CO/Gas/Wasser → CRITICAL mit Sofortmaßnahmen
     - Medien → Beleuchtung (TV an + Licht hell = Blendung)
     - Geräte → Benachrichtigungen (Waschmaschine fertig) `[OK]`

3. **Device Health** — `assistant/assistant/device_health.py` (548 Zeilen)
   - 30-Tage-Baseline-Anomalieerkennung (2.0σ Schwelle, Zeile 35) `[OK]`
   - 3 Anomalie-Typen: Value-Anomaly, Stale-Sensor, HVAC-Effizienz `[OK]`
   - Saisonale Baselines (Zeile 90-92): Vergleich gegen gleiche Jahreszeit `[BESSER ALS MCU]`
   - Auto-Suppress nach 3 Offline-Zyklen (Zeile 75-81) `[OK]`

4. **Health Monitor** — `assistant/assistant/health_monitor.py` (448 Zeilen)
   - CO2 (1000/1500ppm), Humidity (30%/70%), Temperatur (16°C/27°C) `[OK]`
   - Hysterese 2%, Room-Specific Overrides, 27 Exclude-Patterns `[OK]`
   - NTP-Jump-Detection (F-058, Zeile 149): Erkennt Systemuhr-Sprünge >5min `[OK]`

5. **Activity Engine** — `assistant/assistant/activity.py` (716 Zeilen)
   - 7 Aktivitätszustände mit Sensor-Detection (Media-Player, Bett, Mikrofon, PC) `[OK]`
   - 5-Sekunden-Cache, manuelle Overrides möglich `[OK]`
   - Flow-State-Tracking ab 30min Focus (MCU Sprint 3) `[OK]`

6. **Diagnostics** — `assistant/assistant/diagnostics.py` (464 Zeilen)
   - Entity-Health: Offline/Unavailable, Battery <20%, Stale >6h `[OK]`
   - Auto-Suppress für permanent offline Geräte `[OK]`
   - Disk-Space-Monitoring (<10% = Warnung) `[OK]`

7. **Insight Engine** — `assistant/assistant/insight_engine.py` (2.687 Zeilen) `[BESSER ALS MCU]`
   - 8 Basis-Checks + 7 Advanced 3D-Checks (4+ Dimensionen gleichzeitig)
   - Cross-Referencing: Wetter↔Fenster, Frost↔Heizung, Kalender↔Wetter, Energie↔Zeit, Präsenz↔Geräte, Temperatur↔Fenster, Comfort↔Settings
   - Advanced: Guest-Prep, Away-Security, Health-Work-Pattern, Humidity-Contradiction, Night-Security, Heating-vs-Sun, Forgotten-Devices `[OK]`

**[V2]:** [V2 übersprungen — V1 unauffällig. Alle Kern-Module ohne TODOs/FIXMEs, pass-Statements nur in Error-Handling.]

### Was fehlt zum MCU-Level

1. **Echtzeit-Gesamtbild als Dashboard-Narrativ** — MCU-Jarvis kann jederzeit einen sofortigen Lagebericht geben ("How are we doing?"). Der reale Jarvis aggregiert Kontext, aber ein dedizierter "Gesamt-Lagebericht auf Knopfdruck" mit natürlicher Sprache könnte schneller sein.
2. **Prädiktive Trendanalyse** — MCU-Jarvis erkennt Trends bevor sie kritisch werden (Vereisung beim Flug). Der reale Jarvis hat Threshold-basierte Alerts, aber keine lineare Regression für "In 30min wird CO2 kritisch".
3. **Kontextuelle Verknüpfung in Echtzeit** — Der Insight Engine prüft alle 30min. Für schnellere Reaktionen auf sich ändernde Bedingungen könnte event-getriebenes Cross-Referencing helfen.

### Konkrete Verbesserungsvorschläge

1. **[ ] Instant-Lagebericht via Sprache** — In `context_builder.py` eine `build_situation_report()` Methode die alle Datenquellen in einem natürlichen 3-5-Satz-Report zusammenfasst
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

2. **[ ] Trend-Prädiktionen für Sensoren** — In `health_monitor.py` lineare Regression über letzte 30min, Warnung wenn Trend zum Threshold führt
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[WÖCHENTLICH]`

3. **[ ] Event-getriebener Insight-Check** — In `insight_engine.py` bei State-Changes sofort relevante Checks triggern statt nur alle 30min
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Jarvis kann jederzeit einen natürlichsprachigen Lagebericht in <3s liefern
- [ ] Kontext-Cache ist nie älter als 5 Sekunden für kritische Daten
- [ ] Cross-Domain-Insights werden bei State-Changes in <10s erkannt
- [ ] 30-Tage-Baselines erkennen >90% der echten Anomalien bei <10% False Positives
- [ ] Alle 10+ Datenquellen sind parallel verfügbar und graceful bei Ausfall

---

## 6. Lernfähigkeit & Adaptation (×2)

### MCU-Jarvis Benchmark
MCU-Jarvis lernt aus Tonys Verhalten über die Filme hinweg — wird immer besser darin, Tonys Bedürfnisse zu antizipieren, passt sich an neue Situationen an, und korrigiert eigene Fehler. Von Iron Man 1 (grundlegender Assistent) bis Age of Ultron (proaktiver Partner) zeigt er messbare Evolution. Er lernt aus Korrekturen, merkt sich Vorlieben, und passt seine Strategien an.

**Schlüsselszenen:**
- Iron Man 1→3: Sichtbare Evolution von reaktiv zu proaktiv
- Iron Man 2: Lernt aus Forschungssessions mit Tony
- Iron Man 3: "House Party Protocol" — hat komplexe Multi-Step-Aktionen aus Erfahrung gelernt

### MindHome-Jarvis Status: 86%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Learning Observer** — `assistant/assistant/learning_observer.py` (1.489 Zeilen) `[BESSER ALS MCU]`
   - Erkennt manuelle Wiederholungen ≥3× → schlägt Automatisierung vor `[OK]`
   - Jarvis-Action-Markierung: Ignoriert eigene Aktionen (Zeile 149-154) `[OK]`
   - F-053 Cycle Detection: Verhindert observe→suggest→automate→observe-Schleifen `[OK]`
   - Abstraktes Konzept-Lernen (B8): Nicht nur konkrete Aktionen, sondern semantische Konzepte `[OK]`
   - Scene-Device-Pattern: Erkennt device→scene Trigger `[OK]`

2. **Correction Memory** — `assistant/assistant/correction_memory.py` (~400 Zeilen)
   - Strukturierte Speicherung: original_action, correction_text, corrected_args, person, room, hour `[OK]`
   - Auto-Regel nach 2+ gleichen Korrekturen (Zeile 113-114), max 20 Regeln, 5 neue/Tag `[OK]`
   - Confidence-Decay: -5% pro 30 Tage (veraltete Regeln verblassen) `[OK]`
   - Kontextbewusste Injection: Nur relevante Korrekturen ins LLM (Action+Room+Person+Time Match) `[OK]`
   - Cross-Domain-Regeln möglich (Klima-Korrektur → Licht-Präferenz) `[OK]`

3. **Outcome Tracker** — `assistant/assistant/outcome_tracker.py` (975 Zeilen) `[BESSER ALS MCU]`
   - 180s Beobachtungsverzögerung nach Aktion → misst tatsächliches Ergebnis `[OK]`
   - 4 Outcome-Klassen: POSITIVE/NEUTRAL/PARTIAL/NEGATIVE `[OK]`
   - Per-Person-Scores, Wöchentliche Trends, Domänen-Kalibrierung `[OK]`
   - MAX_DAILY_CHANGE=0.20 gegen Data-Poisoning `[OK]`
   - Rolling Window: Letzte 200 Outcomes gewichtet `[OK]`
   - Integration: Boosts/Penalties für Anticipation Engine (+0.1/-0.15) `[OK]`

4. **Self Optimization** — `assistant/assistant/self_optimization.py`
   - Schlägt Parameteränderungen vor: sarcasm_level, opinion_intensity, formality_min etc. `[OK]`
   - **Immutable Core**: trust_levels, security, autonomy, models NICHT änderbar (Zeile 63) `[OK]`
   - Alle Änderungen nur mit manueller Genehmigung `[OK]`
   - Config-Snapshots vor jeder Änderung `[OK]`
   - Bounds-Enforcement für alle Parameter `[OK]`

5. **Feedback Tracker** — `assistant/assistant/feedback.py` (556 Zeilen)
   - 6 Feedback-Typen: thanked (+0.20) → ignored (-0.05) `[OK]`
   - Score-basierte Cooldown-Anpassung: SUPPRESS (<0.15), REDUCE (<0.30), NORMAL, BOOST (>0.70) `[BESSER ALS MCU]`
   - Auto-Timeout 120s → als "ignored" markiert `[OK]`

6. **Anticipation Engine** — `assistant/assistant/anticipation.py` (2.263 Zeilen)
   - 4 Mustertypen: Zeit, Sequenz, Kontext, Kausale Ketten `[OK]`
   - Recency Weighting, Saisonaler Boost (+5-10%), Climate Model Integration `[OK]`
   - **Habit Drift Detection** (Zeile 1664-1795): Erkennt veränderte Routinen `[BESSER ALS MCU]`
   - **Future Predictions** (Zeile 1953-2087): 7-Tage-Vorausschau `[OK]`

7. **Person Preferences** — `assistant/assistant/person_preferences.py` (271 Zeilen)
   - 8 Kern-Präferenzen pro Person, 90-180 Tage Trend-Erkennung `[OK]`
   - Auto-Lernen aus Korrekturen (Zeile 129-159) `[OK]`

8. **Learning Transfer** — `assistant/assistant/learning_transfer.py`
   - Raum-Gruppen-basiert: Wohnbereich, Schlafbereich, Nassbereich, Arbeitsbereich `[OK]`
   - Person-Filter + Temporal-Filter (Morgen/Nachmittag/Abend) `[BESSER ALS MCU]`
   - Max 2 Transfer-Vorschläge pro Tag `[OK]`

9. **Memory Extractor** — `assistant/assistant/memory_extractor.py` (Zeile 103)
   - `extract_and_store()`: LLM-basierte Faktenextraktion aus Gesprächen `[OK]`
   - `extract_reaction()`: Lernt aus Aktions-Reaktionen `[OK]`
   - 10 Kategorien: preference, person, habit, health, work, personal_date, intent, conversation_topic, general, scene_preference `[OK]`
   - Fast-Model, Temperature 0.1, max 512 Tokens `[OK]`

10. **Sarkasmus-Feedback-Loop** — personality.py (Zeile 3549-3641)
    - Alle 20 Interaktionen: >70% positiv → Level +1, <30% → Level -1 `[OK]`
    - Redis-persistent 90 Tage `[OK]`

**[V2]:** [V2 übersprungen — V1 unauffällig. Alle Lernmodule produktionsreif, keine Stubs gefunden.]

### Was fehlt zum MCU-Level

1. **Meta-Lernen** — MCU-Jarvis scheint nicht nur Muster zu lernen, sondern auch zu verstehen WARUM ein Muster existiert. Der reale Jarvis lernt Korrelationen, nicht Kausalitäten.
2. **Langzeit-Evolution-Tracking** — MCU-Jarvis wird über Jahre hinweg besser. Der reale Jarvis hat Confidence-Decay (gut), aber kein explizites "Skill-Level" das die Gesamtverbesserung über Monate/Jahre misst.
3. **Cross-Domain-Lernen** — Correction Memory unterstützt Cross-Domain-Regeln, aber das System könnte stärker Muster über Domänen hinweg verknüpfen (z.B. "User korrigiert immer Licht UND Temperatur gleichzeitig → Combo-Szene vorschlagen").

### Konkrete Verbesserungsvorschläge

1. **[ ] Lern-Dashboard mit Skill-Progression** — In `self_optimization.py` eine Gesamt-Skill-Metrik tracken: Anzahl gelernter Muster, Korrektionsrate über Zeit, Acceptance-Rate → sichtbare Progression
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[WÖCHENTLICH]`

2. **[ ] Cross-Domain-Combo-Erkennung** — In `learning_observer.py` erkennen wenn 2+ Korrekturen in verschiedenen Domänen innerhalb von 60s passieren → Combo-Szene vorschlagen
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

3. **[ ] Kausales Lernen via LLM** — In `correction_memory.py` bei Regel-Erstellung den LLM fragen WARUM die Korrektur nötig war → Regel mit Begründung speichern → bessere Generalisierung
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Korrektionen werden in ≤2 Wiederholungen gelernt
- [ ] Gelernte Muster haben eine False-Positive-Rate <5%
- [ ] Habit-Drift wird innerhalb von 7 Tagen erkannt
- [ ] Self-Optimization-Vorschläge werden zu >60% akzeptiert
- [ ] Cross-Domain-Combos werden in >50% der Fälle korrekt erkannt
- [ ] Feedback-basierte Cooldowns reduzieren unerwünschte Benachrichtigungen um >50%

---

## 7. Sprecherkennung & Personalisierung (×1.5)

### MCU-Jarvis Benchmark
MCU-Jarvis erkennt Tony sofort an der Stimme, unterscheidet zwischen Pepper, Rhodey und Fremden. In Iron Man 2 erkennt er Rhodey im War Machine Suit. Er passt sein Verhalten an: formeller mit Pepper, kameradschaftlicher mit Tony, wachsam bei Unbekannten.

**Schlüsselszenen:**
- Iron Man 2: Erkennt Rhodey trotz Suit — Person-Identifikation über Stimme
- Iron Man 1-3: Unterschiedliches Verhalten mit Tony vs. Pepper vs. Fremden

### MindHome-Jarvis Status: 78%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Speaker Recognition** — `assistant/assistant/speaker_recognition.py` (1.159 Zeilen) `[BESSER ALS MCU]`
   - **7-stufiges Identifikationssystem** mit fallender Priorität:
     1. Device-Mapping (Confidence 0.95): Gerät→Person direkt zugeordnet `[OK]`
     2. DoA — Direction of Arrival (0.85): ReSpeaker-Winkelbasierte Identifikation mit Wrap-Around-Support `[OK]`
     3. Room + Presence (0.80): Räumliche Lokation + Haushalt-Präsenz `[OK]`
     4. Sole Person Home (0.85): Nur eine Person zuhause → muss sie sein `[OK]`
     5. Voice Embeddings (0.60-0.95): ECAPA-TDNN 192-dim Stimmabdruck, Cosinus-Ähnlichkeit `[OK]`
     6. Voice Features (0.30-0.90): WPM, Dauer, Lautstärke — markiert als "spoofable" `[OK]`
     7. Last Speaker Cache (0.20-0.50): Zeitbasierter Decay-Fallback `[OK]`
   - **EMA-basiertes Embedding-Merging** (alpha=0.3, Zeile 873): Stimmprofil verbessert sich über Zeit `[OK]`
   - **Fallback-Frage**: "Wer spricht gerade?" bei niedriger Confidence (Zeile 934) `[OK]`
   - **Max 10 Profile**, Identifikations-History (max 100 Einträge) `[OK]`

2. **Per-Person State Management** — Über mehrere Module:
   - **MoodDetector** (mood_detector.py): Per-Person-Stimmung mit isoliertem State (max 20 Personen) `[OK]`
   - **DialogueStateManager** (dialogue_state.py): Per-Person-Dialogzustand (max 50 Personen) `[OK]`
   - **PersonPreferences** (person_preferences.py): 8 Kern-Präferenzen pro Person mit Trend-Tracking `[OK]`
   - **Sarcasm-Streak** (personality.py): Per-User Sarkasmus-Tracking mit Redis (4h TTL) `[OK]`

3. **Titel-System** — `assistant/assistant/config.py` (Zeile 291-318)
   - `get_person_title()`: Explizit → Active Person → Primary User → "Sir" Fallback `[OK]`
   - Case-insensitive, Vornamen-Fallback ("Anna Mueller" → config key "anna") `[OK]`
   - Per-Household-Member Config: `get_member_config()` mit Name, Rolle, Trust-Level `[OK]`

4. **Guest vs. Resident** — `assistant/assistant/visitor_manager.py` (587 Zeilen)
   - Known Visitors DB, Expected Visitors, Doorbell-Workflow `[OK]`
   - Auto-Guest-Mode bei Besucher-Erkennung `[OK]`
   - Guest-Mode reduziert proaktive Verbosity (Confidence-Threshold 0.6 für Gäste) `[OK]`

5. **Trust-Level-basierte Zugriffskontrolle** — `assistant/assistant/autonomy.py`
   - 3 Trust-Level: Gast (0), Mitbewohner (1), Owner (2) `[OK]`
   - Gäste: Nur Licht/Klima/Medien, raumgebunden `[OK]`

6. **Tests**: test_speaker_recognition.py (300+ Zeilen) — DoA, Embedding, Voice-Matching, Enrollment, History `[OK]`

**[V2]:** [V2 übersprungen — V1 unauffällig. Speaker Recognition vollständig implementiert, keine Stubs.]

### Was fehlt zum MCU-Level

1. **Stimm-basierte Emotionserkennung** — MCU-Jarvis hört an Tonys Stimme ob er gestresst ist. Der reale Jarvis hat Voice-Features (WPM, Lautstärke) und LLM-Sentiment, aber keine Deep-Learning-basierte Emotionserkennung aus Audio.
2. **Instant-Erkennung ohne Fallback** — MCU-Jarvis erkennt Tony sofort. Der reale Jarvis braucht manchmal die Fallback-Frage "Wer spricht?".
3. **Verhaltens-Personalisierung über Titel hinaus** — MCU-Jarvis spricht ANDERS mit Pepper als mit Tony (nicht nur anderer Titel). Der reale Jarvis hat per-Person Mood und Preferences, aber keine komplett unterschiedlichen Kommunikationsstile pro Person.

### Konkrete Verbesserungsvorschläge

1. **[ ] Audio-Emotionserkennung** — In `speaker_recognition.py` Whisper-Metadaten (Sprechgeschwindigkeit, Pausen, Lautstärke-Varianz) als Emotions-Features nutzen und an `mood_detector.py` weiterleiten
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

2. **[ ] Per-Person Kommunikationsstile** — In `personality.py` Person-Profile mit individuellem Humor-Level, Verbosity, Formalität (nicht nur globale Decay)
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

3. **[ ] Continuous Speaker Verification** — In `speaker_recognition.py` während des Gesprächs periodisch Embedding prüfen um Sprecherwechsel mid-conversation zu erkennen
   - Aufwand: Groß
   - Impact: +3%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Sprecherkennung identifiziert Haushaltsmitglieder mit >90% Genauigkeit ohne Fallback-Frage
- [ ] Per-Person Verhalten ist spürbar unterschiedlich (verifizierbar durch Blind-Test)
- [ ] Gäste werden automatisch erkannt und mit erhöhter Formalität behandelt
- [ ] Sprecherwechsel mid-conversation wird in >80% der Fälle erkannt
- [ ] Voice-Embeddings verbessern sich messbar über die erste Woche

---

## 8. Krisenmanagement & Notfallreaktionen (×1.5)

### MCU-Jarvis Benchmark
Bei Angriffen auf Tonys Haus (Iron Man 3) koordiniert Jarvis die Verteidigung, priorisiert Menschenleben (Pepper retten > Haus verteidigen), bleibt unter Druck funktionsfähig. Nach dem Absturz funktioniert er eingeschränkt aber stabil (Graceful Degradation). In Age of Ultron existiert er verteilt nach Ultrons Angriff — Resilienz und Backup.

**Schlüsselszenen:**
- Iron Man 3: Haus-Angriff — Priorisierung: Pepper retten, dann Tony, dann Haus
- Iron Man 3: Nach Absturz — degradierter aber funktionsfähiger Modus
- Avengers 2: Verteilt nach Ultron-Angriff — extreme Resilienz

### MindHome-Jarvis Status: 82%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Threat Assessment** — `assistant/assistant/threat_assessment.py` (1.620 Zeilen)
   - **12 Bedrohungstypen** mit Prioritätshierarchie (Zeile 36-49):
     - P0: Rauch/Feuer, Kohlenmonoxid, Gasleck (Lebensbedrohung)
     - P1: Medizinischer Notfall
     - P2: Einbruch
     - P3: Wasserschaden
     - P4: Stromausfall
     - P5: Sturm-Fenster, offene Türen bei Abwesenheit
     - P6: Nacht-Bewegung
     - P7: Unbekanntes Gerät im Netzwerk `[OK]`
   - **5 Emergency Playbooks** (Zeile 53-355):
     - power_outage (5 Schritte), water_damage (6 Schritte), break_in (5 Schritte), fire_smoke (5 Schritte), medical_emergency (5 Schritte) `[OK]`
     - Fire: Alle Lichter AN, Rollläden AUF, Lüftung AUS `[OK]`
     - Break-in: Stille Alarmierung, Kamera-Snapshots `[OK]`
     - Medical: Bestätigungsfrage, Tür entriegeln für Rettungskräfte `[OK]`
   - **Security Score** (Zeile 909): 0-100 mit 4 Leveln (excellent/good/warning/critical) `[OK]`
   - **Escalation Chain** (MCU Sprint 3, Zeile 394): Externe Kontakte mit Verzögerung, ACK-basiert `[OK]`
   - **Post-Crisis Debrief** (Zeile 1521-1543): Callback nach Krise `[OK]`
   - **Monthly Security Hardening Report** (Zeile 1547) `[OK]`

2. **Multi-Crisis Priorisierung** — threat_assessment.py (Zeile 519)
   - Threats sortiert nach `_THREAT_PRIORITY` `[OK]`
   - Parallele Playbooks: Verschiedene Szenarien gleichzeitig möglich, gleiche werden verhindert (Zeile 1357) `[OK]`
   - F-009: KEIN Auto-Lock bei offenen Türen (verhindert Aussperren) `[OK]`

3. **Circuit Breaker** — `assistant/assistant/circuit_breaker.py` (429 Zeilen) `[BESSER ALS MCU]`
   - 3 Zustände: CLOSED → OPEN → HALF_OPEN mit Auto-Recovery `[OK]`
   - **8 registrierte Breaker**: ollama, ha, mindhome, redis, chromadb, web_search, insight, seasonal `[OK]`
   - **4-stufige Degradation**: CLOSED (0-2 Failures) → WARNING (3-5) → REDUCED (6-9) → OPEN (10+) `[OK]`
   - **Cascade Mapping** (Zeile 208-213): ollama→[response_cache], redis→[memory, anticipation, feedback], chromadb→[semantic_memory, rag], ha→[device_health, diagnostics] `[BESSER ALS MCU]`
   - **Predictive Warmer** (Zeile 327-425): Proaktive Health-Checks vor Peak-Hours `[BESSER ALS MCU]`

4. **Ambient Audio** — `assistant/assistant/ambient_audio.py`
   - Audio-Event-Erkennung: glass_break, smoke_alarm, co_alarm, intrusion_alarm, water_alarm `[OK]`
   - Incident-Korrelation: Glasbruch + Alarm innerhalb 30s = ein Vorfall `[OK]`
   - Raum-Identifikation aus Entity-Names `[OK]`

5. **Benachrichtigungsketten** — Über proactive.py + threat_assessment.py
   - CRITICAL → sofort TTS + externe Kontakte mit Eskalation
   - HIGH → TTS (laut oder leise je nach Activity)
   - Krisenmodus in personality.py: Humor DEAKTIVIERT `[OK]`

6. **Notification Cooldown** (Zeile 1609-1620): Redis-basiert, verhindert Spam `[OK]`

7. **Tests**: test_threat_assessment.py (538 Zeilen), test_circuit_breaker.py (800+ Zeilen) `[OK]`

**[V2]:** [V2 übersprungen — V1 unauffällig. Alle Krisenmanagement-Module vollständig implementiert.]

### Was fehlt zum MCU-Level

1. **Priorisierung von Menschenleben explizit** — MCU-Jarvis priorisiert "Pepper retten" über "Haus verteidigen". Der reale Jarvis hat Threat-Priorities, aber keine explizite "Personen-Evakuierung > Sachschutz" Logik.
2. **Adaptive Krisenstrategie** — MCU-Jarvis passt seine Strategie während der Krise an (Iron Man 3: Plan ändert sich als das Haus einstürzt). Die Playbooks sind statisch.
3. **Koordinierte Multi-Room-Evakuierung** — MCU-Jarvis dirigiert Personen in verschiedenen Räumen. Der reale Jarvis informiert, aber koordiniert nicht raumweise.

### Konkrete Verbesserungsvorschläge

1. **[ ] Personen-Evakuierungs-Priorität** — In `threat_assessment.py` bei Fire/CO Playbook: Prüfe Raumpräsenz und priorisiere Warnungen für besetzte Räume zuerst
   - Aufwand: Mittel
   - Impact: +4%
   - Alltag: `[SELTEN]`

2. **[ ] Adaptive Playbook-Anpassung** — In `threat_assessment.py` Playbook-Steps mit Zustandsprüfungen versehen: Wenn Step 1 fehlschlägt, adaptiere Step 2
   - Aufwand: Mittel
   - Impact: +3%
   - Alltag: `[SELTEN]`

3. **[ ] Multi-Room-Evakuierungsnachrichten** — In `threat_assessment.py` bei CRITICAL Threats per-Room TTS-Nachrichten mit spezifischen Anweisungen ("Verlasse das Schlafzimmer Richtung Flur")
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Playbooks werden in <5s nach Erkennung gestartet
- [ ] Alle besetzten Räume erhalten bei CRITICAL personalisierte Warnungen
- [ ] Circuit Breaker erholt sich in >90% der Fälle automatisch nach Service-Wiederherstellung
- [ ] Externe Eskalation funktioniert zuverlässig (>95% Zustellrate)
- [ ] Post-Crisis-Debrief liefert nutzbaren Report innerhalb von 5min nach Krise

---

## 9. Sicherheit & Bedrohungserkennung (×1.5)

### MCU-Jarvis Benchmark
"Sir, I'm detecting an unauthorized entry." — MCU-Jarvis erkennt Einbrüche, ungewöhnliche Aktivitäten, Systemkompromittierungen sofort. In Age of Ultron widersteht er Ultrons Übernahmeversuch und schützt die Integrität seiner Systeme. Er erkennt Bedrohungen auf mehreren Ebenen: physisch (Eindringlinge), digital (Hacking), umgebungsbasiert (Gefahrenstoffe).

**Schlüsselszenen:**
- Iron Man 3: "We've got incoming!" — Soforterkennung herannahender Bedrohungen
- Avengers 2: Widerstand gegen Ultrons Systemübernahme — digitale Sicherheit

### MindHome-Jarvis Status: 84%

### Code-Verifizierung

**[V1] Erste Analyse:**

1. **Function Validator** — `assistant/assistant/function_validator.py` (766 Zeilen) `[BESSER ALS MCU]`
   - **Security-Critical Actions** (Zeile 26-38): lock_door, unlock_door, set_alarm, emergency_stop, factory_reset `[OK]`
   - **Pre-Execution Validation**: Trust-Level + Autonomie-Level + Parameter-Bounds prüfung `[OK]`
   - **Feature 10: Data-Based Pushback** (Zeile 346-673):
     - Klima: Offene Fenster, leerer Raum, warmes Wetter, Peak-Tarif `[OK]`
     - Licht: Tageslicht verfügbar, leerer Raum `[OK]`
     - Cover: Sturmwarnung, Frost, Solar-Produktion, Markise bei Regen `[OK]`
   - **4-stufige Severity** (Zeile 696-718): Casual → Objection → Concern → Resignation `[OK]`
   - **Pushback-Learning** (Zeile 95-148): Nach 5+ Overrides in 30 Tagen → unterdrücken `[OK]`
   - **Audit-Logging** (Zeile 209-239): Redis-Liste, max 500, 90-Tage TTL `[OK]`

2. **Autonomy Manager** — `assistant/assistant/autonomy.py` (867 Zeilen) `[BESSER ALS MCU]`
   - 5 Autonomie-Level: Assistent (1) → Autopilot (5) `[OK]`
   - 3 Trust-Level: Gast (0), Mitbewohner (1), Owner (2) `[OK]`
   - **Safety Caps** (Zeile 275-283): HARD LIMITS — max_temp 30°C, min_temp 14°C, max_temp_change ±3°C, max_actions/min 10 `[OK]`
   - **Emergency Escalation** (Zeile 578-615): Temporärer Boost auf Level 5 während Krise `[OK]`
   - **Autonomy Evolution** (MCU Sprint 43, Zeile 684-866): Dynamische Progression basierend auf Tagen aktiv (30/90/180), Interaktionen (200/500/1000), Acceptance-Rate (70%/80%/85%) — Level 5 NUR manuell `[BESSER ALS MCU]`
   - **De-Escalation** (MCU Sprint 41, Zeile 621-674): Automatischer Vorschlag zur Level-Reduktion wenn Acceptance <50% `[OK]`

3. **Prompt Injection Protection** — `assistant/assistant/context_builder.py` (Zeile 68-156) `[BESSER ALS MCU]`
   - 154 Regex-Muster: System Prompt Hijacking, Role/Persona Takeover, Encoding Bypasses (Base64, ROT13), Unicode-Tricks, Tool Injection, Delimiter Confusion `[OK]`
   - NFKC-Normalisierung, Zero-Width-Character-Removal, Mathematical-Symbol-Filterung `[OK]`
   - Deutsche + Englische Muster, Mixed-Language Injection `[OK]`

4. **Config Versioning** — `assistant/assistant/config_versioning.py` (293 Zeilen)
   - Snapshot vor jeder Config-Änderung, max 20 Snapshots `[OK]`
   - Rollback ohne Zeitlimit, Pre-Rollback-Backup `[OK]`
   - Hot-Reload mit Rollback bei Fehler `[OK]`
   - Disk-Quota 50MB `[OK]`

5. **Immutable Core** — self_optimization.py (Zeile 63)
   - `_HARDCODED_IMMUTABLE = {"trust_levels", "security", "autonomy", "dashboard", "models"}` `[OK]`
   - Kann NICHT per Self-Optimization geändert werden `[OK]`

6. **State Change Log Attribution** — state_change_log.py
   - Wer hat was geändert: jarvis / automation / user_physical / unknown `[OK]`
   - 80+ Dependency Rules mit Entity-Role-Matching `[OK]`

7. **Tests**: test_autonomy.py (850+ Zeilen), test_security.py (23.452 Zeilen!), test_security_http_endpoints.py (9.549 Zeilen) `[OK]`

**[V2]:** [V2 übersprungen — V1 unauffällig. Sicherheitsmodule umfassend getestet mit 33.000+ Zeilen Tests.]

### Was fehlt zum MCU-Level

1. **Anomalie-Erkennung auf Netzwerkebene** — MCU-Jarvis erkennt Ultrons Systemübernahme. Der reale Jarvis hat `unknown_device` Erkennung (P7), aber keine tiefe Netzwerk-Anomalieerkennung.
2. **Verhaltensbasierte Intrusion Detection** — MCU-Jarvis erkennt ungewöhnliches Verhalten (nicht nur offene Türen). Der reale Jarvis hat Night-Motion-Detection, aber keine ML-basierte Verhaltens-Anomalieerkennung.
3. **Selbstschutz-Mechanismen** — MCU-Jarvis verteilt sich und überlebt Ultrons Angriff. Der reale Jarvis hat Circuit Breaker, aber keine explizite "Jarvis unter Angriff"-Erkennung.

### Konkrete Verbesserungsvorschläge

1. **[ ] Verhaltens-Anomalie-Detection** — In `threat_assessment.py` Baseline für "normales" Benutzerverhalten (Tagesrhythmus, übliche Geräte) aufbauen und Abweichungen melden
   - Aufwand: Groß
   - Impact: +4%
   - Alltag: `[SELTEN]`

2. **[ ] API-Rate-Limiting auf Assistent-Ebene** — In `main.py` Rate-Limiting pro Person/IP für sicherheitskritische Endpunkte (PIN, Security, Trust-Level)
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

3. **[ ] Security-Event-Log-Dashboard** — In `threat_assessment.py` oder `diagnostics.py` ein dediziertes Security-Log mit Timeline-Ansicht für Audit-Zwecke
   - Aufwand: Klein
   - Impact: +2%
   - Alltag: `[SELTEN]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Alle sicherheitskritischen Aktionen erfordern korrekte Trust-Level-Prüfung (100%)
- [ ] Safety Caps können unter keinen Umständen umgangen werden (Pen-Test verifiziert)
- [ ] Prompt Injection wird in >99% der Fälle erkannt und blockiert
- [ ] Config-Rollback stellt exakten vorherigen Zustand wieder her (100%)
- [ ] Security-Audit-Log ist vollständig und unveränderbar (Append-Only)

---

## 10. Multi-Room-Awareness & Follow-Me (×1)

### MCU-Jarvis Benchmark
MCU-Jarvis ist überall im Haus gleichzeitig präsent, folgt Tony nahtlos von Raum zu Raum, passt Lautstärke und Kontext automatisch an. Audio-Übergänge sind unmerklich, Konversationen werden beim Raumwechsel fortgesetzt. "Good morning, Jarvis" liefert ein raum-kontextuelles Tagesbriefing.

**Schlüsselszenen:**
- Iron Man 1: "Good morning, Jarvis" — Raum-kontextuelles Briefing
- Alle Filme: Jarvis folgt Tony durch das gesamte Haus, Audio wechselt nahtlos mit

### MindHome-Jarvis Status: 81%

### Code-Verifizierung
**[V1] Analyse:**

1. **FollowMeEngine** — `assistant/assistant/follow_me.py` (531 Zeilen)
   - `handle_motion()` (Zeile 59-203): Kernlogik — Motion-Detection → Audio/Licht/Klima-Transfer `[OK]`
   - `_transfer_music()` (Zeile 205-281): **Crossfade-Implementierung** — 10 Schritte über 2s mit Volumen-Ramping `[OK]` `[BESSER ALS MCU]`
   - `_transfer_lights()` (Zeile 283-352): Raum-Profile mit Tag/Nacht-Helligkeit `[OK]`
   - `_transfer_climate()` (Zeile 354-394): Nur 2 Zustände (Komfort/Eco) `[VERBESSERBAR]`
   - `detect_return_intent()` (Zeile 485-507): Kurzbeschaffung-Detection (<10s) `[OK]`
   - `detect_lingering()` (Zeile 509-531): Verweildauer-Erkennung (≥180s) `[OK]`
   - Topic-Resumption (Zeile 136-152): MCU Sprint 5 — merkt sich letzte Konversations-Topic für Fortsetzung nach Raumwechsel `[OK]`
   - Parallel-Transfers (Zeile 165-199): Music + Lights + Climate via `asyncio.gather()` `[OK]`

2. **MultiRoomAudio** — `assistant/assistant/multi_room_audio.py` (663 Zeilen)
   - `create_group()` (Zeile 56-102): Benannte Speaker-Gruppen, Redis-persistent `[OK]`
   - `_play_native_group()` (Zeile 216-249): HA media_player.join für Sonos/Cast `[OK]`
   - `_play_parallel()` (Zeile 251-278): Fallback bei Join-Fehler → paralleles play_media `[OK]`
   - `get_best_speaker_for_person()` (Zeile 554-592): Person-basiertes Speaker-Routing via Präsenz `[OK]`
   - `smart_announce()` (Zeile 594-663): Dringlichkeits-Routing (critical=alle, normal=person_room, low=suppress) `[OK]`
   - `discover_speakers()` (Zeile 510-539): Auto-Discovery, schließt TVs/Receiver aus `[OK]`

3. **SpeakerRecognition** — `assistant/assistant/speaker_recognition.py` (1.159 Zeilen)
   - `identify()` (Zeile 214-397): 7-stufige Hierarchie (Device→DoA→Room→Präsenz→Voice→Embedding→Cache) `[OK]` `[BESSER ALS MCU]`
   - `identify_by_embedding()` (Zeile 791-850): ECAPA-TDNN Cosinus-Ähnlichkeit `[OK]`
   - `store_embedding()` (Zeile 852-897): EMA-Verschmelzung (α=0.3) `[OK]`
   - `start_fallback_ask()` (Zeile 934-977): "Wer sprichst du?" Fallback-Dialog `[OK]`
   - Spoofing-Protection (Zeile 1094-1123): 3 Fehlversuche → 1h Sperre `[OK]`
   - Confidence-Decay (Zeile 1082-1092): 5% Verfall pro Woche `[OK]`

4. **ActivityEngine** — `assistant/assistant/activity.py` (876 Zeilen)
   - `detect_activity()` (Zeile 416-501): 7 Aktivitäten (SLEEPING, IN_CALL, WATCHING, FOCUSED, GUESTS, RELAXING, AWAY) `[OK]`
   - `get_delivery_method()` (Zeile 522-536): Silence-Matrix 7×4 (Activity × Urgency) `[OK]`
   - `get_volume_level()` (Zeile 538-567): Phase 9 — Tageszeit + Activity kombiniert `[OK]`
   - `is_in_flow_state()` (Zeile 503-512): MCU Sprint 3 — Focus >30min erkennt `[OK]`
   - `check_silence_trigger()` (Zeile 393-414): Keyword-Erkennung ("Filmabend", "Meditation") `[OK]`

5. **SoundManager** — `assistant/assistant/sound_manager.py` (768 Zeilen)
   - `speak_response()` (Zeile 578-746): TTS-Kern mit Raum-Routing `[OK]`
   - `_get_auto_volume()` (Zeile 402-444): Phase 9 — Auto-Lautstärke mit Wetter-Adaptivität (Regen +0.15) `[OK]`
   - `normalize_tts_text()` (Zeile 107-116): Deutsch-TTS (ä/ö/ü + "Sir"→"Sör" Phonetik) `[OK]`
   - Parallel Volume+TTS (Zeile 681-738): T-2 Optimierung, spart ~50-100ms `[OK]`
   - Alexa-Support (Zeile 216-238): Separate notify.alexa_media Code-Pfade `[OK]`

6. **AmbientAudioClassifier** — `assistant/assistant/ambient_audio.py` (644 Zeilen)
   - `process_event()` (Zeile 225-338): 9 Geräusche (glass_break, smoke_alarm, co_alarm, dog_bark, baby_cry, doorbell, gunshot, water_alarm, scream) `[OK]`
   - `correlate_events()` (Zeile 554-585): Gruppiert Events in zeitliche Incidents (30s Fenster) `[OK]`
   - `learn_false_positive()` (Zeile 602-627): 5+ False Positives → Sensitivität reduzieren `[OK]`
   - `get_temporal_urgency()` (Zeile 629-644): Nacht → "critical", Tag → "normal" `[OK]`
   - Raum-Extraktion (Zeile 471-496): Regex-basiert aus Entity-IDs `[OK]`

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level

1. **Prädiktives Raum-Routing** — MCU-Jarvis antizipiert wohin Tony geht (Richtung Küche → Audio vorab routen). MindHome reagiert erst nach erkanntem Raumwechsel. `[FEHLT KOMPLETT]`
2. **Mid-Sentence Room Handoff** — MCU-Jarvis setzt mitten im Satz nahtlos fort wenn Tony den Raum wechselt. MindHome hat Topic-Resumption, aber keinen Audio-Handoff während der Sprachausgabe. `[FEHLT KOMPLETT]`
3. **Raum-kontextuelle Persönlichkeitsanpassung** — MCU-Jarvis spricht im Workshop anders (locker) als bei einem Gala-Event (formal). MindHome hat Activity-Detection, aber keine raumbasierte Stilanpassung. `[VERBESSERBAR]`
4. **Klima-Transfer mit Gewohnheitslernen** — FollowMe transferiert nur Komfort/Eco. Sollte aus Correction Memory und Person Preferences pro Raum + Tageszeit lernen. `[VERBESSERBAR]`
5. **Ambient-Audio ohne KI-Klassifikation** — Nur HA-Sensoren, kein eigenes Audio-Modell (YAMNet o.ä.). Polling-basiert statt Event-Subscription. `[VERBESSERBAR]`

### Konkrete Verbesserungsvorschläge

1. **[ ] Prädiktives Raum-Routing** — In `follow_me.py` Bewegungsmuster aus `anticipation.py` nutzen um Audio vorab zu routen (z.B. Morgens: Schlafzimmer → Bad → Küche)
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

2. **[ ] Raum-kontextuelle Stilanpassung** — In `personality.py` einen Room-Context-Modifier einbauen (Workshop=locker, Gästezimmer=höflich, Schlafzimmer=leise/ruhig)
   - Aufwand: Klein
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

3. **[ ] FollowMe Klima-Integration mit Learning** — In `follow_me.py` `_transfer_climate()` die Person Preferences und Correction Memory für raum+zeitspezifische Temperaturen nutzen
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Audio folgt Person zwischen Räumen mit <3s Latenz (Follow-Me)
- [ ] Musik-Crossfade ist unhörbar (sanfter Übergang, kein Cut)
- [ ] Aktivitätserkennung unterdrückt korrekt bei Schlaf/Focus/Gäste
- [ ] Ambient-Sounds lösen korrekte Reaktion aus (Glasbruch → Alarm, Hundebellen → Info)
- [ ] Raumwechsel bewahrt Gesprächskontext (Topic-Resumption funktioniert)

---

## 11. Energiemanagement & Haussteuerung (×1)

### MCU-Jarvis Benchmark
MCU-Jarvis steuert das gesamte Stark-Anwesen effizient — Licht, Klima, Sicherheit — alles integriert und optimiert. Er scannt den Energiestatus des Hauses (Arc-Reaktor), erkennt Konflikte, und steuert natürlich ("Reduce heat in the workshop"). Jarvis optimiert proaktiv und berichtet verbal über den Energiestatus.

**Schlüsselszenen:**
- Iron Man 1: "Reduce heat in the workshop" — Natürliche Klimasteuerung
- Avengers 1: Jarvis scannt Stark Tower Energiesystem — Ganzheitliche Energieanalyse

### MindHome-Jarvis Status: 82%

### Code-Verifizierung
**[V1] Analyse:**

1. **EnergyOptimizer** — `assistant/assistant/energy_optimizer.py` (1.318 Zeilen)
   - `get_current_price()` (Zeile 150-198): Strompreis-Monitoring, 15-Min-Updates, Price-Tiers (cheap/normal/expensive) `[OK]`
   - `get_price_forecast()` (Zeile 200-264): 24h Preisvorhersage mit stündlicher Aufschlüsselung `[OK]`
   - `get_solar_production()` (Zeile 266-318): Solar-Produktion aus HA-Sensoren `[OK]`
   - `get_solar_forecast()` (Zeile 320-382): Wetterbasierte Solar-Vorhersage `[OK]`
   - `suggest_load_shifting()` (Zeile 384-468): **Kernfeature** — Verschiebt flexible Lasten auf günstige/Solar-Stunden `[OK]`
   - `shift_load()` (Zeile 620-688): Ausführung der Lastverschiebung `[OK]`
   - `get_essential_entities()` (Zeile 814-842): Schutz kritischer Geräte `[OK]` `[BESSER ALS MCU]`
   - `detect_anomalies()` (Zeile 974-1042): Erkennung ungewöhnlicher Verbrauchsmuster `[OK]`
   - `get_carbon_intensity()` (Zeile 1210-1252): CO2-Intensität des Strommix `[OK]`
   - `schedule_charging()` (Zeile 1254-1318): EV/Batterie-Ladung bei optimalem Preis `[OK]`
   - Background-Loops: Preis-Update (15 Min) + Optimierungs-Check (30 Min) `[OK]`

2. **ConflictResolver** — `assistant/assistant/conflict_resolver.py` (741 Zeilen)
   - `_check_window_heating()` (Zeile 158-210): Fenster offen + Heizung an `[OK]`
   - `_check_window_cooling()` (Zeile 212-258): Fenster offen + Klima an `[OK]`
   - `_check_light_daylight()` (Zeile 260-308): Licht an bei hellem Tageslicht (Lux-Sensor) `[OK]`
   - `_check_empty_room_devices()` (Zeile 310-362): Geräte an in leeren Räumen `[OK]`
   - `_check_door_security()` (Zeile 364-410): Tür offen + Alarm scharf `[OK]`
   - `_check_simultaneous_heating_cooling()` (Zeile 412-458): Heizen UND Kühlen gleichzeitig `[OK]`
   - `_check_rain_windows()` (Zeile 460-508): Regen + Fenster offen `[OK]`
   - `_check_storm_covers()` (Zeile 510-554): Sturm + Markisen ausgefahren `[OK]`
   - 8+ Konflikttypen mit Severity-Klassifikation (info/warning/critical) `[OK]`
   - Konflikt-History mit Outcomes in Redis `[OK]`

3. **PredictiveMaintenanceEngine** — `assistant/assistant/predictive_maintenance.py` (832 Zeilen)
   - `check_all_devices()` (Zeile 174-238): Täglicher Health-Check aller Geräte `[OK]`
   - `get_device_health()` (Zeile 240-308): Health-Score 0-100 pro Gerät `[OK]`
   - `predict_failure()` (Zeile 310-378): Ausfallvorhersage basierend auf Nutzungsmustern `[OK]`
   - `track_battery_drain()` (Zeile 440-502): Battery-Drain-Monitoring `[OK]`
   - `detect_degradation()` (Zeile 504-568): Performance-Degradation vs. Baseline `[OK]`
   - `_check_hvac_efficiency()` (Zeile 750-800): HVAC-Effizienz-Monitoring `[OK]`
   - `estimate_lifecycle()` (Zeile 630-692): Lebensdauer-Schätzung `[OK]`

4. **DeviceHealthMonitor** — `assistant/assistant/device_health.py` (687 Zeilen)
   - `build_baselines()` (Zeile 170-238): 30-Tage-Baselines pro Gerät `[OK]`
   - `detect_anomalies()` (Zeile 240-312): Anomalie-Erkennung vs. Baseline `[OK]`
   - `_seasonal_adjustment()` (Zeile 580-618): Saisonale Baseline-Anpassung `[OK]`
   - `get_device_trends()` (Zeile 620-658): 7/30/90-Tage-Trends `[OK]`
   - `get_offline_devices()` (Zeile 314-358): Erkennt offline Geräte `[OK]`
   - `track_state_frequency()` (Zeile 530-578): Stuck-Detection `[OK]`

5. **SeasonalInsightEngine** — `assistant/assistant/seasonal_insight.py` (589 Zeilen)
   - `get_seasonal_recommendations()` (Zeile 100-178): Saison-spezifische Empfehlungen `[OK]`
   - `compare_year_over_year()` (Zeile 180-248): Jahresvergleich Energieverbrauch `[OK]` `[BESSER ALS MCU]`
   - `get_heating_strategy()` (Zeile 320-382): Optimale Heizstrategie pro Saison `[OK]`
   - `get_lighting_strategy()` (Zeile 384-438): Tageslicht-adaptive Lichtempfehlungen `[OK]`
   - `get_ventilation_strategy()` (Zeile 440-498): Fenster öffnen vs. HVAC `[OK]`

6. **Function Calling — Gerätesteuerung** — `assistant/assistant/function_calling.py` (13.891 Zeilen)
   - 13+ Gerätetypen: Light, Climate/HVAC, Cover, Media Player, Lock, Alarm, Switch, Fan, Vacuum, Scene, Timer, Camera, Script `[OK]`
   - 74 Function-Call Tools insgesamt `[OK]`

7. **Weitere Module:**
   - `health_monitor.py` (571 Zeilen): CO2 >1000ppm Warnung, Luftfeuchtigkeit, Temperatur-Alerts `[OK]`
   - `insight_engine.py` (2.687 Zeilen): Wetter↔Fenster, Frost↔Heizung Kreuzreferenzen `[OK]`

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level

1. **Ganzheitliche Haus-Optimierung** — MCU-Jarvis optimiert alle Systeme holistisch (nicht nur paarweise Konflikte). MindHome erkennt 8 Konflikte, aber keine übergreifende "ganzes Haus"-Optimierungsstrategie. `[VERBESSERBAR]`
2. **Prädiktives Comfort-Preconditioning** — MCU-Jarvis konditioniert Räume vor bevor Tony ankommt. MindHome hat die Daten (Anticipation + Energy), aber die Integration zwischen `energy_optimizer.py` und `anticipation.py` ist unvollständig. `[UNTERVERBUNDEN]`
3. **Verbaler Energie-Status-Bericht** — MCU-Jarvis berichtet proaktiv ("The arc reactor is at 37%"). MindHome hat die Daten, narrt sie aber nicht proaktiv verbal. `[VERBESSERBAR]`
4. **Notfall-Energiemanagement** — MCU-Jarvis leitet bei Notfällen Energie auf essentielle Systeme um. MindHome hat Essential-Entity-Schutz, aber keine aktive Umverteilung bei Stromausfall/Notfall. `[FEHLT KOMPLETT]`

### Konkrete Verbesserungsvorschläge

1. **[ ] Energy-Anticipation-Integration** — `energy_optimizer.py` mit `anticipation.py` verbinden: Wenn Person in 15 Min nach Hause kommt → Raum vorheizen/kühlen zum optimalen Preis
   - Aufwand: Mittel
   - Impact: +5%
   - Alltag: `[TÄGLICH]`

2. **[ ] Proaktiver Energie-Bericht** — In `proactive.py` einen periodischen Energie-Status-Bericht einbauen ("Heute 15% weniger verbraucht als letzte Woche, Sir.")
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[WÖCHENTLICH]`

3. **[ ] Ganzheitliche Optimierungsstrategie** — In `energy_optimizer.py` einen House-Wide-Optimizer der alle Räume/Geräte zusammen betrachtet statt nur paarweise Konflikte
   - Aufwand: Groß
   - Impact: +5%
   - Alltag: `[WÖCHENTLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Strompreis-basierte Lastverschiebung funktioniert zuverlässig (>90% Ausführungsrate)
- [ ] Alle 8+ Konflikte werden erkannt und korrekt aufgelöst
- [ ] Solar-Eigenverbrauch wird maximiert (Load Shifting zu Produktionszeiten)
- [ ] Essential Entities werden unter keinen Umständen abgeschaltet
- [ ] Predictive Maintenance meldet Geräteprobleme bevor sie ausfallen

---

## 12. Erklärbarkeit & Transparenz (×1)

### MCU-Jarvis Benchmark
MCU-Jarvis erklärt seine Empfehlungen, nennt Gründe für Entscheidungen und handelt transparent. "Sir, may I remind you that you've been awake for 72 hours?" — immer mit Begründung. Bei Multi-Step-Aktionen narrt er jeden Schritt. Bei Ablehnung erklärt er warum.

**Schlüsselszenen:**
- Avengers 2: "Sir, may I remind you..." — Begründete Empfehlungen
- Iron Man 1-3: Jarvis erklärt jeden Schritt bei komplexen Aktionen ("Initializing House Party Protocol...")

### MindHome-Jarvis Status: 72%

> **Hinweis:** Score von 85% auf 72% korrigiert nach Tiefenanalyse. Die Architektur ist solide,
> aber kritische Integrationslücken (auto_explain=False, fehlende User-API, lückenhafte log_decision-Abdeckung)
> reduzieren den effektiven MCU-Match erheblich.

### Code-Verifizierung
**[V1] Analyse:**

1. **ExplainabilityEngine** — `assistant/assistant/explainability.py` (785 Zeilen)
   - `log_decision()` (Zeile 139-220): Loggt Entscheidungen mit Action, Reason, Trigger, Domain, Confidence `[OK]`
   - Kontrafaktische Ergebnisse (Zeile 197-200): Automatisch generiert — "Was wäre ohne Eingreifen passiert?" `[OK]` `[BESSER ALS MCU]`
   - 13 Counterfactual-Regeln (Zeile 26-63): Domain×Context → Template (z.B. "Heizkosten von {cost}€/h verschwendet") `[OK]`
   - `explain_last()` (Zeile 221-232): Letzte N Entscheidungen aus In-Memory Deque `[OK]`
   - `explain_by_domain()` (Zeile 234-236): Domänen-Filter `[OK]`
   - `format_explanation()` (Zeile 247-299): Template-basiert mit Trigger-Labels (7 Typen) `[OK]`
   - `format_explanation_llm()` (Zeile 323-388): LLM-basierte natürliche Formatierung, 4s Timeout → Template-Fallback `[VERBESSERBAR]`
   - `build_why_chain()` (Zeile 619-690): Mehrstufige Why-Chains, 7 prädefinierte Kausal-Regeln, max 3 Ebenen, LLM-Fallback `[OK]`
   - **KRITISCH — Defaults deaktiviert** (Zeile 79): `auto_explain=False`, `confidence_display=False`, `reasoning_chains=False` `[UNTERVERBUNDEN]`
   - `pass` Statements (Zeile 432, 657): Fehler bei Template-Formatierung werden ignoriert `[VERBESSERBAR]`

2. **ActionPlanner** — `assistant/assistant/action_planner.py` (1.051 Zeilen)
   - `plan_action()` (Zeile 70-148): Multi-Step-Planung mit Narration `[OK]`
   - `_decompose_intent()` (Zeile 150-218): Komplexe Absichten → atomare Schritte `[OK]`
   - `execute_plan()` (Zeile 290-368): Ausführung mit WebSocket-Fortschritts-Narration `[OK]`
   - `_narrate_step()` (Zeile 370-412): "Jetzt schalte ich das Licht ein..." `[OK]`
   - `_narrate_completion()` (Zeile 414-452): "Alles fertig, Sir." `[OK]`
   - `_narrate_failure()` (Zeile 454-492): "Das hat leider nicht geklappt..." `[OK]`
   - `preview_plan()` (Zeile 580-632): Plan-Vorschau vor Ausführung `[OK]`
   - `_handle_partial_failure()` (Zeile 634-688): Teilerfolg-Handling `[OK]`
   - `_generate_alternative_plan()` (Zeile 740-798): Fallback bei Fehler `[OK]`
   - **KRITISCH — Narration sehr limitiert** (Zeile 559-580): `_get_narration_text()` nur für `set_light` und `set_cover`, alle anderen Gerätetypen leer `[VERBESSERBAR]`
   - **Keine Schritt-Begründungen**: Narrt WAS passiert, aber nicht WARUM je Schritt `[VERBESSERBAR]`
   - **Keine Explainability-Integration**: Ruft `log_decision()` nicht auf `[UNTERVERBUNDEN]`

3. **Personality Pushback** — `assistant/assistant/personality.py` (5.566 Zeilen)
   - `check_pushback()` (Zeile ~1378-1420): Meinungs-basierte Warnungen mit 3 Pushback-Levels (0/1/2) `[OK]`
   - `check_curiosity()` (Zeile ~1426-1483): Neugier-Fragen bei untypischen Aktionen ("Um diese Uhrzeit, Sir?") `[OK]`
   - `narrate_device_event()` (Zeile ~5132-5167): Persönlichkeits-basierte Geräte-Meldungen `[OK]`
   - 5-stufige Eskalation (Zeile ~1737-1767): Progressive Dringlichkeit mit Erklärung `[OK]`
   - Meta-Kognition (Zeile ~2359-2400): Self-aware Erklärung des eigenen Verhaltens `[OK]`
   - Krisenmodus-Kommunikation (Zeile ~2500-2550): Klar, begründet, effizient `[OK]`
   - Error-Recovery-Templates (Zeile ~204-218): 8 in-character Fehlererklärungen `[OK]`
   - **Curiosity max 2×/Tag** (Zeile ~1445): Zu limitiert für viele Situationen `[VERBESSERBAR]`

4. **Function Validator Pushback** — `assistant/assistant/function_validator.py` (765 Zeilen)
   - `get_pushback_context()` (Zeile 346-386): Live-Daten via HA → Warnungen mit Typ + Detail + Alternative `[OK]`
   - `_pushback_set_climate()` (Zeile 388-454): Offene Fenster, leerer Raum `[OK]`
   - `_pushback_set_light()` (Zeile 519-568): Tageslicht, leerer Raum `[OK]`
   - `_pushback_set_cover()` (Zeile 570-645): Wind-Warnung `[OK]`
   - `format_pushback_warnings()` (Zeile 721-748): "SITUATIONSBEWUSSTSEIN" Prompt-Injection `[OK]`
   - Datenbasierter Pushback ("CO2 bei 1200ppm") `[OK]` `[BESSER ALS MCU]`
   - 4-Severity-Pushback: info/warning/critical/block `[OK]`
   - **pass-Statements** (Zeile 481, 511, 562, 605, 645): State-Abruf-Fehler werden ignoriert → Pushback fällt still weg `[VERBESSERBAR]`
   - **Pushback nicht persistiert**: History nicht in Explainability geloggt `[UNTERVERBUNDEN]`

5. **State Change Log Attribution** — `assistant/assistant/state_change_log.py` (9.927 Zeilen)
   - `_detect_source()` (Zeile ~9188-9217): 4 Kategorien: jarvis / automation / user_physical / unknown `[OK]`
   - 80+ Dependency Rules (Zeile 47-600+) mit Entity-Role-Matching `[OK]`
   - `detect_conflicts()` (Zeile ~9302-9397): ~50 Abhängigkeitsregeln `[OK]`
   - `format_conflicts_for_prompt()` (Zeile ~9398-9520): Konflikt-Beschreibung für LLM `[OK]`
   - **Attribution-Heuristik**: 2-Sekunden-Fenster für user_physical — fehleranfällig `[VERBESSERBAR]`
   - **Keine separate User-API** für Konflikt-History `[VERBESSERBAR]`

6. **Autonomy Transparency** — `assistant/assistant/autonomy.py` (866 Zeilen)
   - `can_execute()` (Zeile 285-361): Sehr detaillierte Ablehnungsgründe (Multi-Faktor) `[OK]`
   - Erklärt Nacht-Reduktion, Domain-spezifisch, Trust-Level `[OK]`
   - **Gründe nur in Logs** (Zeile 181-184): Nicht an User gezeigt, nicht in Explainability persistiert `[UNTERVERBUNDEN]`

7. **Self-Optimization Transparency** — `assistant/assistant/self_optimization.py` (911 Zeilen)
   - Alle Vorschläge mit Begründung (approval_mode: manual) `[OK]`
   - Before/After-Tracking mit Snapshots `[OK]`
   - Weekly Learning Report `[OK]`

8. **Proactive Notification Reasoning** — `assistant/assistant/proactive.py` (10.247 Zeilen)
   - Jede Benachrichtigung enthält Trigger + Begründung + Vorschlag `[OK]`
   - Cover-Reason-System (Zeile ~5757-5857): Speichert WARUM Rollladen bewegt wurde in Redis `[OK]`
   - Context-basierte Zustandsübergänge: "sturm" → STORM_SECURED, "sonne" → SUN_PROTECTED `[OK]`
   - **Cover-Reasons nur für Cover**, nicht für andere Geräte `[VERBESSERBAR]`

9. **Brain-Integration** — `assistant/assistant/brain.py`
   - Explainability initialisiert (Zeile 114, 512) `[OK]`
   - Letzte 5 Entscheidungen in Kontext (Zeile 4508-4528): Priority 3 (niedrig) `[VERBESSERBAR]`
   - `log_decision()` nur für Automationen (Zeile 8451-8468) `[UNTERVERBUNDEN]`
   - **KRITISCH — Nicht aufgerufen für**: User-Commands, Anticipation, Action-Planner, Pushback `[UNTERVERBUNDEN]`
   - **KRITISCH — auto_explain default False** (Zeile 79): Erklärungen nicht automatisch in Prompts `[UNTERVERBUNDEN]`

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level

1. **Explainability standardmäßig deaktiviert** — `auto_explain=False`, `confidence_display=False`, `reasoning_chains=False` → User sieht keine Erklärungen ohne manuelle Aktivierung. `[UNTERVERBUNDEN]`
2. **Fehlende User-API** — Kein `/api/explain-last` oder `/api/why-chain` Endpunkt. User kann nicht programmatisch "Warum?" fragen. `[FEHLT KOMPLETT]`
3. **Lückenhafte log_decision-Abdeckung** — Nur Automationen werden geloggt, nicht: User-Commands, Anticipation-Patterns, Action-Planner-Schritte, Pushback-Gründe. `[UNTERVERBUNDEN]`
4. **Narration nur für 2 Gerätetypen** — `action_planner._get_narration_text()` hat nur Templates für `set_light` und `set_cover`. Alle anderen Domains sind leer. `[VERBESSERBAR]`
5. **Natürlich-konversationelle Erklärungen** — MCU-Jarvis erklärt wie ein Butler ("Sir, I took the liberty of..."). MindHome hat strukturierte Erklärungen, die konversationeller sein könnten. `[VERBESSERBAR]`
6. **Proaktive Status-Briefings** — MCU-Jarvis gibt ungefragt Status-Updates ("Systems at 90%, Sir"). MindHome narrt nicht proaktiv. `[VERBESSERBAR]`

### Konkrete Verbesserungsvorschläge

1. **[ ] Explainability-Defaults aktivieren** — In `settings.yaml` und `explainability.py` die Defaults auf `auto_explain=True`, `confidence_display=True` setzen. Reasoning-Chains optional lassen.
   - Aufwand: Klein
   - Impact: +8%
   - Alltag: `[TÄGLICH]`

2. **[ ] log_decision()-Abdeckung erweitern** — In `brain.py` `log_decision()` auch für User-Commands, Anticipation-Execution und Action-Planner-Schritte aufrufen
   - Aufwand: Mittel
   - Impact: +6%
   - Alltag: `[TÄGLICH]`

3. **[ ] Narration für alle Gerätetypen** — In `action_planner.py` `_get_narration_text()` Templates für Climate, Media, Cover, Switch, Fan, Scene etc. ergänzen
   - Aufwand: Klein
   - Impact: +4%
   - Alltag: `[TÄGLICH]`

4. **[ ] Konversationelle Erklärungs-Templates** — In `explainability.py` `format_for_user()` mit natürlicheren Butler-Formulierungen ("Ich habe mir erlaubt..." statt Aufzählung)
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

5. **[ ] Entscheidungs-Zusammenfassung im Morgen-Briefing** — Im Routine-Engine Morgen-Briefing die nächtlichen Entscheidungen zusammenfassen
   - Aufwand: Klein
   - Impact: +3%
   - Alltag: `[TÄGLICH]`

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] `auto_explain=True` als Default, Erklärungen fließen automatisch in Kontext
- [ ] `log_decision()` wird bei >90% aller Jarvis-Aktionen aufgerufen
- [ ] Jede proaktive Aktion wird mit Begründung geliefert (100%)
- [ ] User kann "Warum?" fragen und bekommt verständliche Antwort
- [ ] Multi-Step-Aktionen werden Schritt für Schritt narrt (alle Gerätetypen)
- [ ] Pushback enthält immer konkrete Sensor-Daten als Begründung
- [ ] Entscheidungs-Log ist per Zeitraum abfragbar und verständlich

---

## Changelog

### Durchlauf #1 — Session 1 — 2026-03-22
- 18 Verbesserungsaufgaben erstellt (5× Kat.1, 4× Kat.2, 4× Kat.3, 4× Kat.4 + Akzeptanzkriterien)
- 27 "Besser als MCU" Features identifiziert und in Schutzliste aufgenommen
- Kategorien 1-4 Score: Kat.1=72%, Kat.2=82%, Kat.3=85%, Kat.4=80%
- Gewichteter Teildurchschnitt (4/12 Kategorien): **79.5%**
- Doppelverifizierung (V1+V2) für alle 4 Kategorien durchgeführt
- Keine TODOs/FIXMEs/NotImplementedError in den analysierten Kern-Modulen gefunden

### Durchlauf #1 — Session 2 — 2026-03-22
- 16 neue Verbesserungsaufgaben erstellt (3× Kat.5, 3× Kat.6, 3× Kat.7, 3× Kat.8, 3× Kat.9)
- 14 neue "Besser als MCU" Features identifiziert und in Schutzliste aufgenommen
- Kategorien 5-9 Score: Kat.5=83%, Kat.6=86%, Kat.7=78%, Kat.8=82%, Kat.9=84%
- Gewichteter Teildurchschnitt (9/12 Kategorien): **80.9%** (vorher 79.5% mit nur 4 Kategorien)
- V1-Verifizierung für alle 5 Kategorien durchgeführt, V2 übersprungen (V1 unauffällig)
- 33.000+ Zeilen Security-Tests verifiziert (test_security.py + test_security_http_endpoints.py + test_autonomy.py)

### Durchlauf #1 — Session 3 — 2026-03-22
- 12 neue Verbesserungsaufgaben erstellt (3× Kat.10, 3× Kat.11, 5× Kat.12 + Akzeptanzkriterien)
- 6 neue "Besser als MCU" Features identifiziert und in Schutzliste aufgenommen
- Kategorien 10-12 Score: Kat.10=81%, Kat.11=82%, Kat.12=72% (nach Tiefenanalyse-Korrektur von 85% auf 72%)
- Gewichteter Gesamtdurchschnitt (12/12 Kategorien): **80.5%** (vorher 80.9% mit 9 Kategorien)
- V1-Verifizierung für alle 3 Kategorien durchgeführt, V2 entfällt (Gewicht ×1)
- Kat.12 Korrektur: Zweiter Agent fand kritische Integrationslücken (auto_explain=False, fehlende User-API, lückenhafte log_decision-Abdeckung, 5+ pass-Statements in function_validator.py)
- 4.641+ Zeilen Multi-Room-Code + 785 Zeilen Explainability analysiert
- **Alle 12 Kategorien sind jetzt analysiert — bereit für Session 4 (Roadmap & Sprints)**
