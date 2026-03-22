# J.A.R.V.I.S. MCU-Level Implementation Plan
> Erstellt am 2026-03-22 | Letzter Durchlauf: Session 1 am 2026-03-22
> Aktueller Stand: 79.5% (Teilergebnis — 4 von 12 Kategorien analysiert)
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

---

## Changelog

### Durchlauf #1 — Session 1 — 2026-03-22
- 18 Verbesserungsaufgaben erstellt (5× Kat.1, 4× Kat.2, 4× Kat.3, 4× Kat.4 + Akzeptanzkriterien)
- 27 "Besser als MCU" Features identifiziert und in Schutzliste aufgenommen
- Kategorien 1-4 Score: Kat.1=72%, Kat.2=82%, Kat.3=85%, Kat.4=80%
- Gewichteter Teildurchschnitt (4/12 Kategorien): **79.5%**
- Doppelverifizierung (V1+V2) für alle 4 Kategorien durchgeführt
- Keine TODOs/FIXMEs/NotImplementedError in den analysierten Kern-Modulen gefunden
