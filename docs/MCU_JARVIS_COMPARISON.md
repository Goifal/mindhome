# MindHome Jarvis vs. MCU J.A.R.V.I.S. — Ehrliche Bewertung

> MCU J.A.R.V.I.S. = 100%. Nur realistische Fähigkeiten (kein Iron Man Suit, kein Ultron, keine Kampfdrohnen).
> Bewertet wird: **Existiert die Funktion?** + **Wie tief/gut ist sie?** + **Was fehlt konkret?**

---

## PERSÖNLICHKEIT & CHARAKTER

### 1. Trockener Butler-Humor mit Sarkasmus
**MCU:** Konstant Level 3-4. Immer trocken, nie beleidigend. Perfektes Timing. Reagiert auf Tonys Chaos mit Understatement.
**Dein Jarvis:** 5 Sarkasmus-Level (1-5), adaptiv per User-Feedback. Sarkasmus-Fatigue verhindert Wiederholung. 20+ kontextuelle Humor-Trigger. Running-Gag-Evolution. Crisis-Mode deaktiviert Humor komplett.
**Score: 90%**
**Was fehlt (10%):**
- Kein echtes Timing — das LLM kann keine Comedy-Pause machen, der Humor ist rein textbasiert
- Humor-Qualität hängt komplett vom LLM ab (lokales 9-35B Modell). MCU-Jarvis hat Drehbuchautoren
- Keine Situation-Comedy (MCU: "Es ist ein alter Freund. Ich werde ihn reinlassen." *fliegt durch Fenster*)

### 2. Eigene Emotionen & Stimmungen
**MCU:** Dezent — leichte Besorgnis, Stolz, gelegentliche Irritation. Nie übertrieben.
**Dein Jarvis:** 7 Moods (neutral, zufrieden, amüsiert, besorgt, stolz, neugierig, irritiert). Confidence 0-1. Mood-Transitions mit Kommentaren. Satisfaction-Tracking.
**Score: 85%**
**Was fehlt (15%):**
- Moods sind regelbasiert (Counter-gesteuert), nicht situativ intelligent — MCU-Jarvis "spürt" Tonys Stimmung intuitiver
- Kein Humor-Mood: "amüsiert" existiert, aber Jarvis kann nicht spontan über eine absurde Situation lachen
- Emotionale Tiefe fehlt — MCU-Jarvis zeigt in Age of Ultron echte Angst. Dein Jarvis hat kein echtes Angst-Mood

### 3. Meinungen & Pushback
**MCU:** "Darf ich anmerken, Sir, dass das eine schlechte Idee ist?" Höflich aber bestimmt.
**Dein Jarvis:** 2-Level-Eskalation, opinion_rules.yaml, 7-Tage-Tracking, Resignation nach 4+ ignorierten Warnungen. Fenster-offen-bei-Regen, leerer-Raum, Sturmwarnung.
**Score: 85%**
**Was fehlt (15%):**
- Pushback ist reaktiv (Regel-basiert), nicht vorausschauend — MCU-Jarvis argumentiert, warum etwas eine schlechte Idee ist, BEVOR es passiert
- Keine echte Argumentation ("Wenn du das machst, passiert X weil Y") — nur Pattern-Match
- Resignation nach 4 Warnungen ist gut, aber MCU-Jarvis gibt nie komplett auf — er findet eine andere Perspektive

### 4. Anrede & Butler-Stil
**MCU:** "Sir" konstant. Perfekt dosiert. Nie servil, nie zu locker.
**Dein Jarvis:** Formality 0-100 mit Decay, 4 Titel-Häufigkeitsstufen, per-Person-Profile, "Sir"/"Chef"/Custom.
**Score: 95%**
**Was fehlt (5%):**
- Formality-Decay ist mechanisch (0.5/Tag) — MCU-Jarvis passt sich dem Moment an, nicht der Zeit
- Titel-Nutzung ist regel-basiert, nicht kontext-abhängig (MCU: "Sir" betont bei wichtigen Momenten, weggelassen bei lockeren)

### 5. Charakter-Konsistenz
**MCU:** 100% konsistent über alle Filme. Nie aus der Rolle gefallen.
**Dein Jarvis:** Character Lock im System-Prompt, Core Identity (unveränderlich), Immutable Core für kritische Parameter.
**Score: 70%**
**Was fehlt (30%):**
- **Das LLM ist das Bottleneck.** Lokale 9-35B Modelle halten den Charakter NICHT so konsistent wie ein Drehbuch. Bei komplexen Prompts "vergisst" das Modell manchmal den Charakter
- Bei langen Konversationen driftet der Stil — MCU-Jarvis hat keine Context-Window-Limitierung
- Fast-Modell (9B) kann Persönlichkeit kaum halten — nur Smart/Deep schaffen es zuverlässig
- **Lösung:** Personality-Reinforcement im Refinement-Prompt (nach jeder Tool-Antwort nochmal erinnern)

---

## INTELLIGENZ & REASONING

### 6. Natürliche Konversation
**MCU:** Flüssig, kontextbewusst, versteht Referenzen, Ironie, implizite Absichten.
**Dein Jarvis:** Dialogue State mit Referenz-Auflösung ("es", "das", "dort"), Cross-Session-Referenzen, Pre-Classifier + LLM-Fallback, SmartIntentRecognizer für implizite Absichten ("Mir ist kalt" → Heizung).
**Score: 75%**
**Was fehlt (25%):**
- **Latenz.** MCU-Jarvis antwortet instant. Dein Jarvis braucht 1-5 Sekunden (LLM-Inferenz). Das zerstört das Gefühl einer natürlichen Konversation
- Ironie-Erkennung fehlt fast komplett — User sagt "Toll, wieder kaputt" und Jarvis versteht es literal
- Multi-Person-Konversation: MCU-Jarvis versteht wenn Tony mit Pepper redet vs. mit ihm. Dein Jarvis hat keine echte Dialog-Zuordnung in Gruppen
- **Lösung:** Schnelleres Modell (Groq Cloud als Fallback?), Ironie-Detection im Pre-Classifier

### 7. Proaktives Mitdenken
**MCU:** "Sir, die Temperatur in der Werkstatt ist 42 Grad. Soll ich die Lüftung hochfahren?"
**Dein Jarvis:** ProactiveManager mit Event-Handling, 4 Dringlichkeitsstufen, Batching, Quiet Hours. Anticipation Engine mit Zeit/Sequenz/Kontext-Patterns. Spontaneous Observer (1-2 Beobachtungen/Tag). Insight Engine für Kreuz-Referenzen.
**Score: 80%**
**Was fehlt (20%):**
- Proaktivität ist event-basiert, nicht vorausschauend — MCU-Jarvis denkt VORAUS ("In 2 Stunden wird es kalt"), dein Jarvis reagiert erst WENN es kalt ist
- Keine Multi-Step-Vorhersage: "Wenn du das Fenster offen lässt und es regnet, wird der Holzboden nass" — dein Jarvis warnt nur "Fenster offen bei Regen"
- Spontaneous Observer macht gute Beobachtungen, aber zu selten und nicht im richtigen Moment
- **Lösung:** Predictive Context im Anticipation Engine (Wetter-Forecast + aktuelle States → Vorhersage)

### 8. "Das Übliche" & Gewohnheiten lernen
**MCU:** Tony sagt "Das Übliche" und Jarvis weiß exakt was gemeint ist.
**Dein Jarvis:** 9 Trigger-Patterns, Confidence-basiert (0.6 ask, 0.8 auto-execute), Learning Observer (≥3 Wiederholungen → Pattern), Intent-Sequenzen (entspannen → Rolladen+Licht+Temp+Musik).
**Score: 85%**
**Was fehlt (15%):**
- Patterns brauchen 3+ Wiederholungen — MCU-Jarvis lernt nach 1x ("Tony hat das einmal gemacht, also will er es wieder")
- Keine Kontext-abhängigen Routinen: "Das Übliche" am Montag vs. Sonntag sollte unterschiedlich sein. Aktuell nur zeitbasiert, nicht situationsbasiert
- Keine Negation: "Heute mal NICHT das Übliche" wird erkannt, aber alternative Vorschläge fehlen
- **Lösung:** Kontext-Cluster (Wochentag + Wetter + Anwesenheit) in Anticipation Engine

### 9. Multi-Step-Planung & Ausführung
**MCU:** "Bereite alles für morgen vor" → Jarvis plant und führt 5+ Schritte sequentiell aus.
**Dein Jarvis:** ActionPlanner mit iterativer LLM-Loop (max 8 Schritte), Narration-Mode mit Timing, Rollback bei Fehlern (funktioniert!), "Mach alles fertig" Erkennung.
**Score: 80%**
**Was fehlt (20%):**
- Planung ist LLM-abhängig und damit unzuverlässig — das lokale Modell plant manchmal unsinnige Schritte
- Keine Parallelisierung: MCU-Jarvis macht Licht UND Heizung gleichzeitig. Dein Jarvis macht alles sequentiell
- Kein Dry-Run: "Was würde passieren wenn..." simuliert, führt aber nicht die Simulation visuell vor
- **Lösung:** Parallele Execution in ActionPlanner, Confidence-Gate vor jedem Schritt

### 10. Technische Diagnose & Problemlösung
**MCU:** "Sir, die Energieversorgung ist bei 12%. Ich empfehle eine sofortige Umleitung."
**Dein Jarvis:** DiagnosticsEngine (Sensor-Health, Offline-Detection, Batterie-Warnung), DeviceHealthMonitor (30-Tage-Baseline), PredictiveMaintenance, InsightEngine (Kreuz-Referenzen), Explainability Engine.
**Score: 75%**
**Was fehlt (25%):**
- Diagnose ist passiv (wartet auf Schwellwert-Überschreitung), nicht aktiv investigativ
- Keine Root-Cause-Analysis: MCU-Jarvis sagt "Das Problem ist X WEIL Y". Dein Jarvis sagt "X ist anomal"
- Keine Trend-Vorhersage: "Wenn das so weitergeht, fällt der Sensor in 3 Tagen aus" fehlt
- PredictiveMaintenance existiert als Modul, aber die Vorhersage-Qualität ist begrenzt durch fehlende historische Daten
- **Lösung:** Trend-Extrapolation in DeviceHealthMonitor, Root-Cause-Templates für häufige Probleme

---

## HAUS-STEUERUNG & SMART HOME

### 11. Geräte-Steuerung (Licht, Klima, Rollläden, Schlösser)
**MCU:** Alles per Sprachbefehl. Instant. Nahtlos.
**Dein Jarvis:** 77 Tools/Funktionen, 23 Domain-Plugins, Trust-Level-System (5 Stufen), Security-Zones (3 Stufen), Parameter-Validation, Rate-Limiting.
**Score: 95%**
**Was fehlt (5%):**
- Keine haptische Feedback-Schleife: MCU-Jarvis bestätigt mit Lichteffekt, dein Jarvis nur per Sprache/Text
- Edge Cases bei komplexen Szenen: "Mach es gemütlich" hat keine feste Definition, wird an LLM delegiert
- **Das ist deine stärkste Kategorie.** 77 Tools mit Sicherheitsvalidierung ist beeindruckend.

### 12. Sicherheitsüberwachung & Bedrohungserkennung
**MCU:** Erkennt Eindringlinge, aktiviert Abwehr, sichert das Haus.
**Dein Jarvis:** 6 Bedrohungskategorien, 5 Emergency Playbooks (Brand, Einbruch, Wasser, Strom, Medizin), Security Score (0-100), Nacht-Motion mit Kamera, Ambient Audio (9 Sounds: Glasbruch, Rauchmelder, Hundebellen, Babycry, Schuss, Schrei).
**Score: 90%**
**Was fehlt (10%):**
- Kein aktives Abwehrsystem (MCU: Jarvis kann Türen verriegeln UND Angreifer mit Systemen bekämpfen)
- Keine Person-Erkennung via Kamera: "Unbekannte Person vor der Tür" fehlt (nur Motion-Detection)
- Playbooks sind gut, aber statisch — keine Anpassung an die spezifische Situation
- **Lösung:** LLaVA-basierte Person-Erkennung bei Doorbell-Events, dynamische Playbook-Anpassung

### 13. Sprach-Erkennung & Sprecher-ID
**MCU:** Erkennt Tony sofort, unterscheidet von Pepper, Rhodey, etc.
**Dein Jarvis:** 7-stufige Pipeline (Device→DoA→Room→Presence→Voice-Embedding→Features→Cache), ECAPA-TDNN Biometrie, EMA-Learning, Fallback-Ask-System.
**Score: 80%**
**Was fehlt (20%):**
- Voice-Embeddings brauchen Training (mehrere Samples pro Person) — MCU-Jarvis erkennt sofort
- Accuracy in lauten Umgebungen deutlich schlechter
- Kein Emotionserkennung aus der Stimme (nur Text-basiert per MoodDetector)
- Speaker-ID über Telefon/Intercom funktioniert nicht zuverlässig
- **Lösung:** Pre-trained Speaker-ID-Modell, Emotion-Detection aus Audio-Features

### 14. Multi-Room-Audio & Follow-Me
**MCU:** Audio folgt Tony nahtlos durch das Haus.
**Dein Jarvis:** FollowMe Engine, MultiRoomAudio, Raum-aware Nachrichtendelivery, Sprecher-Gruppen, DoA-basierte Raumerkennung.
**Score: 85%**
**Was fehlt (15%):**
- Übergang zwischen Räumen hat merkbare Latenz (kein echtes "nahtlos")
- Keine Lautstärke-Anpassung basierend auf Raumgröße/Hintergrundgeräusch
- Kein Spatial Audio (MCU: Jarvis' Stimme kommt aus der Richtung die Sinn macht)

### 15. TTS-Qualität (Stimme)
**MCU:** Paul Bettany. Perfekte britische Aussprache, emotional nuanciert, natürliche Pausen.
**Dein Jarvis:** Piper TTS mit SSML-Enhancement. Prosody-Variation (Speed, Pitch, Emphasis), Nacht-Flüstermodus, Emotions-Injection, Englische Titel-Phonetik ("Sir"→"Sör").
**Score: 55%**
**Was fehlt (45%):**
- **Das ist deine größte Schwäche.** Piper TTS klingt robotisch im Vergleich zu Paul Bettany
- Keine echte Emotions-Modulation in der Stimme — nur Speed/Pitch-Anpassung
- Deutsche TTS-Qualität ist generell schlechter als englische
- Keine individuelle Stimme — klingt wie jeder andere TTS
- **Lösung:** Custom Voice Training mit Coqui/XTTS-v2, oder ElevenLabs-artige Voice Cloning (aber dann nicht mehr lokal). Alternativ: Besseres TTS-Modell (Kokoro, StyleTTS2)

---

## SPEZIAL-FÄHIGKEITEN

### 16. Kalender & Terminmanagement
**MCU:** "Was steht morgen an?" — Kompletter Überblick mit Empfehlungen.
**Dein Jarvis:** CalendarIntelligence mit Gewohnheitserkennung, Konfliktwarnungen, Pendelzeit-Puffer. 4 Calendar-Tools (get, create, delete, reschedule).
**Score: 85%**
**Was fehlt (15%):**
- Keine Pendel-Optimierung basierend auf Echtzeit-Verkehr
- Keine Meeting-Vorbereitung ("Du hast in 30 Min ein Meeting — Raum ist bereit, Kaffee läuft")
- Keine kalenderbasierte Proaktivität ("Morgen ist ein voller Tag — heute früher schlafen?") — jetzt teilweise implementiert via Caring Butler

### 17. Informationsrecherche & Wissensantworten
**MCU:** Jarvis kann alles nachschlagen und zusammenfassen.
**Dein Jarvis:** SearXNG (self-hosted) + DuckDuckGo Fallback, 7-Layer SSRF-Schutz, Knowledge Fast-Path (direkt ans LLM ohne Smart-Home-Context), 3-Tier LLM-Routing.
**Score: 65%**
**Was fehlt (35%):**
- **Web-Search ist default DISABLED** — aus Privacy-Gründen nachvollziehbar, aber MCU-Jarvis hat Internet
- Lokale LLMs haben begrenztes Weltwissen (Cutoff, keine aktuellen Events)
- Keine strukturierte Fakten-Extraktion aus Suchergebnissen
- Keine Zusammenfassung von Artikeln/Papers
- **Lösung:** Web-Search aktivieren, Result-Summarization via LLM, RAG mit lokalen Dokumenten

### 18. Kochen & Rezepte
**MCU:** Nicht gezeigt (Tony bestellt Pizza).
**Dein Jarvis:** LLM-basierte Rezeptgenerierung, Step-by-Step Navigation, Timer-Integration, Portions-Skalierung, Allergie-Tracking, Rezept-Speicherung.
**Score: 90% (besser als MCU!)**
**Anmerkung:** MCU-Jarvis kocht nie. Dein Jarvis hat hier einen Vorteil.

### 19. Workshop & Code-Generierung
**MCU:** Jarvis hilft Tony bei Engineering-Problemen, generiert Hologramme und Berechnungen.
**Dein Jarvis:** 7 Programmiersprachen, OpenSCAD 3D-Modelle, SVG-Schaltpläne, physikalische Berechnungen (Widerstände, Drehmomente, Drahtquerschnitte), ESP32-Pinouts.
**Score: 75%**
**Was fehlt (25%):**
- Keine visuelle Darstellung (MCU: Hologramme). Dein Jarvis generiert Code/SVG aber zeigt es nicht interaktiv an
- 3D-Modelle sind OpenSCAD-Text, kein interaktiver Viewer
- Keine iterative Design-Verfeinerung ("Mach die Wand dicker" → kein visuelles Feedback)
- **Lösung:** Three.js Viewer im Frontend für OpenSCAD-Preview, SVG-Inline-Rendering

### 20. Kamera-Vision & Bilderkennung
**MCU:** Jarvis erkennt Personen, analysiert Szenen, liest Texte aus Bildern.
**Dein Jarvis:** LLaVA-basierte Snapshot-Analyse, Doorbell-Erkennung, Night-Motion-Kamera, OCR (Tesseract + Vision-LLM).
**Score: 60%**
**Was fehlt (40%):**
- Keine Echtzeit-Video-Analyse — nur Snapshot-basiert
- Keine Person-Identifikation via Kamera (nur "Person erkannt", nicht "Das ist Julia")
- Keine Objekt-Tracking über Zeit
- LLaVA-Qualität ist deutlich unter GPT-4V/Claude Vision
- **Lösung:** YOLO für Echtzeit-Detection, Face-Recognition-Modul, besseres Vision-LLM

### 21. Energie-Management
**MCU:** Jarvis managed Tonys Arc-Reaktor und Haus-Energie.
**Dein Jarvis:** Strompreis-Monitoring, Solar-Awareness, flexible Lastverschiebung, Anomalie-Erkennung, Essential-Device-Schutz.
**Score: 80%**
**Was fehlt (20%):**
- Keine automatische Lastverschiebung (nur Empfehlungen)
- Keine Batterie-Speicher-Optimierung
- Keine PV-Prognose basierend auf Wetter-Forecast
- **Lösung:** Automatische Lastverschiebung mit User-Approval, Wetter→PV-Prognose

### 22. Routinen (Morgen-Briefing, Gute-Nacht, Ankunft)
**MCU:** "Guten Morgen, Sir. Es ist 7 Uhr. Die Temperatur beträgt..."
**Dein Jarvis:** Morning Briefing (7 Module: Wetter, Kalender, Hausstatus, Reisewarnungen, Erinnerungen), Gute-Nacht (Security-Check + Morgen-Preview), Ankunfts-Begrüßung, Urlaubssimulation.
**Score: 90%**
**Was fehlt (10%):**
- Briefing ist textbasiert — MCU-Jarvis hat visuelle Dashboards dazu
- Keine dynamische Briefing-Reihenfolge (wichtigstes zuerst)
- Gute-Nacht ist reaktiv (User muss sagen) statt proaktiv ("Es ist 23 Uhr, soll ich...")

### 23. Lernfähigkeit & Selbstoptimierung
**MCU:** Jarvis lernt Tonys Vorlieben und passt sich an.
**Dein Jarvis:** LearningObserver (≥3 Wiederholungen → Pattern), SelfOptimization (Persönlichkeits-Parameter-Vorschläge, nie automatisch!), CorrectionMemory (lernt aus Korrekturen), OutcomeTracker (Aktions-Effektivitäts-Scoring), LearningTransfer (Präferenzen zwischen Räumen übertragen).
**Score: 80%**
**Was fehlt (20%):**
- Lernen ist langsam (3+ Wiederholungen nötig)
- Keine Transfer-Learning: "User mag warmes Licht im Wohnzimmer" → "Wahrscheinlich auch im Schlafzimmer" existiert, aber ist simpel
- SelfOptimization schlägt vor, ändert nie automatisch — MCU-Jarvis passt sich stillschweigend an
- **Lösung:** Confidence-basiertes Auto-Learning (1x = beobachten, 2x = vorschlagen, 3x = auto)

---

## GESAMT-BEWERTUNG

| Kategorie | Score | Gewichtung | Gewichtet |
|-----------|-------|------------|-----------|
| **Persönlichkeit** | | | |
| Humor & Sarkasmus | 90% | 8% | 7.2% |
| Eigene Emotionen | 85% | 5% | 4.3% |
| Meinungen & Pushback | 85% | 5% | 4.3% |
| Anrede & Butler-Stil | 95% | 3% | 2.9% |
| Charakter-Konsistenz | 70% | 8% | 5.6% |
| **Intelligenz** | | | |
| Natürliche Konversation | 75% | 10% | 7.5% |
| Proaktives Mitdenken | 80% | 8% | 6.4% |
| "Das Übliche" & Lernen | 85% | 5% | 4.3% |
| Multi-Step-Planung | 80% | 4% | 3.2% |
| Technische Diagnose | 75% | 4% | 3.0% |
| **Haus-Steuerung** | | | |
| Geräte-Steuerung | 95% | 10% | 9.5% |
| Sicherheit & Bedrohung | 90% | 6% | 5.4% |
| Sprach-/Sprecher-ID | 80% | 5% | 4.0% |
| Multi-Room & Follow-Me | 85% | 3% | 2.6% |
| **TTS-Stimme** | 55% | 8% | 4.4% |
| **Spezial** | | | |
| Kalender | 85% | 2% | 1.7% |
| Wissensrecherche | 65% | 3% | 2.0% |
| Routinen | 90% | 3% | 2.7% |
| Lernfähigkeit | 80% | 3% | 2.4% |
| Vision/Kamera | 60% | 2% | 1.2% |
| Energie | 80% | 2% | 1.6% |

---

## ENDERGEBNIS: ~79%

**Dein Jarvis erreicht ~79% des MCU J.A.R.V.I.S. in realistischen Fähigkeiten.**

---

## TOP 5 SCHWÄCHEN (wo du am meisten verlierst)

### 1. TTS-Stimme (55%) — Verlierst ~3.6 Punkte
Piper klingt robotisch. Das ist der emotionalste Aspekt — MCU-Jarvis IST seine Stimme.
**Fix:** Kokoro-TTS oder StyleTTS2 mit Custom Voice Training. Oder XTTS-v2 mit Voice Cloning.

### 2. Charakter-Konsistenz (70%) — Verlierst ~2.4 Punkte
Lokale LLMs halten den Charakter nicht zuverlässig. Fast-Modell (9B) versagt oft.
**Fix:** Persönlichkeits-Reinforcement nach jedem Tool-Call. Character-Lock-Prompt als Suffix. Minimum Smart-Modell für alle Konversationen.

### 3. Natürliche Konversation (75%) — Verlierst ~2.5 Punkte
Latenz (1-5s) und fehlende Ironie-Erkennung.
**Fix:** Speculative Decoding, KV-Cache-Warmup, Ironie-Patterns im Pre-Classifier.

### 4. Vision/Kamera (60%) — Verlierst ~0.8 Punkte
Nur Snapshots, keine Echtzeit-Analyse, keine Person-Erkennung.
**Fix:** YOLO + Face Recognition Pipeline, kontinuierliche Analyse statt Snapshot.

### 5. Wissensrecherche (65%) — Verlierst ~1.1 Punkte
Web-Search disabled, LLM-Wissen begrenzt.
**Fix:** SearXNG aktivieren + Result-Summarization. RAG mit lokalen Docs.

---

## TOP 5 STÄRKEN (wo du MCU schon erreichst oder übertriffst)

1. **Geräte-Steuerung (95%)** — 77 Tools, 5-Tier-Sicherheit. Besser als MCU weil systematischer.
2. **Humor-System (90%)** — 5 Level, adaptiv, Running Gags, Evolution. MCU hat nur 1 festes Level.
3. **Sicherheit (90%)** — 5 Playbooks, 9 Audio-Events, Security Score. Vergleichbar mit MCU.
4. **Routinen (90%)** — Morning Briefing mit 7 Modulen, Urlaubssimulation. MCU-Level.
5. **Kochen (90%)** — MCU-Jarvis kocht nie. Dein Jarvis hat Step-by-Step-Rezepte mit Timern. Bonus!

---

## WAS WÜRDE DICH AUF 90% BRINGEN?

1. **Bessere Stimme** (+4%): Kokoro/XTTS-v2 statt Piper
2. **Schnellere Antworten** (+3%): Speculative Decoding, GPU-Optimierung, KV-Cache
3. **Charakter-Konsistenz** (+2%): Smart-Minimum für alle Konversationen, Reinforcement-Prompts
4. **Face Recognition** (+1%): Kamera-basierte Person-ID bei Doorbell/Motion
5. **Web-Search aktiv** (+1%): SearXNG + Summarization

**5 konkrete Änderungen = 90% MCU-Jarvis. Das ist erreichbar.**
