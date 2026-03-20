# JARVIS Verbesserungsanalyse — Verifiziert gegen Code

**Datum:** 2026-03-20
**Analysiert:** Alle 98+ Assistant-Module, Brain, Personality, Proactive, Memory, Autonomy

---

## KATEGORIE 1: UNTERUTILISIERTE MODULE

### 1. LearningTransfer — Still und ungenutzt
- **Datei:** `assistant/assistant/learning_transfer.py`
- **Status:** Vollständig implementiert, in brain.py initialisiert, aber nirgends aktiv aufgerufen
- **Problem:** Transfers passieren still ohne User-Benachrichtigung
- **Fix:** Aktiv aufrufen bei neuer Raum-Präferenz + proaktive Nachricht

### 2. PredictiveMaintenance — Naive Berechnung
- **Datei:** `assistant/assistant/predictive_maintenance.py` (453 Zeilen)
- **Problem:** 2-Punkt-Linearextrapolation ohne Ausreißer-Erkennung
- **Fix:** 3-Punkt-Median, health_score mit failure_count verknüpfen

### 3. SeasonalInsight — Nur Monats-basiert
- **Datei:** `assistant/assistant/seasonal_insight.py` (386 Zeilen)
- **Problem:** Saisonerkennung nur auf Monaten, nicht Temperatur/Tageslicht
- **Fix:** Hybrid-Erkennung + vorgefertigte Tipps als LLM-Fallback

### 4. ConversationMemory Threads — Erstellt aber vergessen
- **Datei:** `assistant/assistant/conversation_memory.py`
- **Problem:** Phase 3B Threads werden im Context-Building nicht genutzt
- **Fix:** Thread-Historie in LLM-Kontext einbauen

### 5. KEY_ABSTRACT_CONCEPTS — Toter Code
- **Datei:** `assistant/assistant/learning_observer.py`
- **Problem:** Definiert aber keine Schreibzugriffe
- **Fix:** Implementieren oder entfernen

---

## KATEGORIE 2: FEHLENDE FEEDBACK-LOOPS

### 6. OutcomeTracker → AnticipationEngine
- **Problem:** Kein Rückkanal — fehlgeschlagene Patterns behalten Confidence
- **Fix:** success_score in Pattern-Confidence einfließen lassen

### 7. OutcomeTracker → LearningObserver
- **Problem:** Erfolgreiche Automations-Patterns werden nicht geboostet
- **Fix:** Bei Erfolg +0.1 Confidence-Boost

### 8. CorrectionMemory — Keine Domain-übergreifenden Regeln
- **Problem:** "Raumverwechslung bei Licht" gilt nicht für Klima
- **Fix:** Domain-generische Regeln extrahieren

### 9. FeedbackTracker — Score-Volatilität
- **Problem:** Kein Smoothing, einzelne Events bewegen Score stark
- **Fix:** Exponential Moving Average (70% alt + 30% neu)

### 10. MoodDetector → Personality — Keine Reaktion
- **Problem:** Stimmung erkannt aber Persönlichkeit reagiert nicht
- **Fix:** Bei frustrated 2+: Sarkasmus reduzieren, Klarheit erhöhen

---

## KATEGORIE 3: PROAKTIVITÄT & ANTIZIPATION

### 11. Wetter-Vorhersage nicht genutzt
- **Problem:** Nur aktuelles Wetter, nicht Forecast
- **Fix:** HA Wetter-Forecast-API für cover-Planung

### 12. Keine Routine-Anomalie-Erkennung
- **Problem:** Kennt Routinen, erkennt nicht wenn sie ausbleiben
- **Fix:** Expected vs. actual tracken, sanft nachfragen

### 13. Proaktive Nachrichten ohne Persönlichkeit
- **Problem:** Generische Templates statt Jarvis-Flavor
- **Fix:** Durch PersonalityEngine filtern

### 14. Think-Ahead nicht implementiert
- **Problem:** last_action Parameter existiert aber wird nie übergeben
- **Fix:** Nach Funktion: Folge-Aktion vorschlagen

### 15. What-If Reasoning passiv
- **Problem:** Nur als Kontext-Hint, nie aktive Frage
- **Fix:** Bei Confidence >0.7 aktiv vorschlagen

### 16. Keine implizite Bedürfnis-Erkennung
- **Problem:** Nur bekannte Patterns, keine First-Time-Szenarien
- **Fix:** Kontext-basierte Needs-Detection als neuen Pattern-Typ

---

## KATEGORIE 4: PERSÖNLICHKEIT & EMOTIONEN

### 17. InnerState ohne Mood-Decay
- **Problem:** Stimmung persistiert bis nächstes Event
- **Fix:** Zeitbasierten Decay implementieren

### 18. Kein Emotion Blending
- **Problem:** Einzelne _mood Variable, kein Mix
- **Fix:** Dict mit Gewichtungen

### 19. InnerState Trigger zu flach
- **Problem:** Jeder Erfolg/Fehler gleich gewichtet
- **Fix:** Domain-spezifische Confidence-Deltas

### 20. Keine neuen Traits über Zeit
- **Problem:** Formality decayed, aber keine neuen Humor-Stile
- **Fix:** Stage-basierte Trait-Unlocks

### 21. Transition-Kommentare unsichtbar
- **Problem:** Definiert aber nie in Antworten injiziert
- **Fix:** Als optionalen Zusatz einbauen

---

## KATEGORIE 5: KONTEXT & INTELLIGENZ

### 22. HA-States nicht gecacht
- **Problem:** get_states() bei jeder Context-Erstellung
- **Fix:** 5-10s Cache mit Event-basierter Invalidierung

### 23. DeviceHealth ohne saisonale Baseline
- **Problem:** Winter-Baseline im Sommer angewendet
- **Fix:** Baselines mit Monat taggen

### 24. HealthMonitor ohne Hysterese
- **Problem:** Alert-Flapping bei Grenzwerten
- **Fix:** Warn bei >Schwelle, clear bei <(Schwelle-2%)

### 25. HealthMonitor nicht raumspezifisch
- **Problem:** Gleiche Schwellen für alle Räume
- **Fix:** Raum-Level-Overrides in Config

### 26. CalendarIntelligence Pendel-Zeit hardcoded
- **Problem:** Ein globaler Wert
- **Fix:** Per (von, zu) Zeiten speichern

### 27. Activity ohne Confidence-Scoring
- **Problem:** Binärer State, kein "wahrscheinlich"
- **Fix:** Confidence 0.0-1.0 einführen

---

## KATEGORIE 6: ENERGIEOPTIMIERUNG

### 28. Keine Preis-Vorhersage
- **Problem:** Nur aktueller Preis vs. Schwelle
- **Fix:** Trend aus Historie oder ENTSO-E API

### 29. Load-Empfehlung ohne Status-Check
- **Problem:** Empfiehlt laufende Geräte
- **Fix:** Entity-State prüfen

### 30. Keine Solar-Vorhersage
- **Problem:** Nur aktuelle Produktion
- **Fix:** Weather Forecast für Prognose

---

## KATEGORIE 7: AUTONOMIE & SICHERHEIT

### 31. Core Identity ohne Runtime-Enforcement
- **Problem:** Nur Textblock, keine Validierung
- **Fix:** IdentityValidator für Self-Optimization

### 32. ProactivePlanner minimal (391 Zeilen)
- **Problem:** Kein Rollback, keine parallele Ausführung
- **Fix:** Rollback-Logik, mehr Trigger

### 33. Vacation-Simulation mit RNG
- **Problem:** Zufällig statt gelernte Muster
- **Fix:** Patterns nachspielen mit Offset

---

## KATEGORIE 8: QUICK WINS

### 34. Semantic Memory ohne Fakt-Versionierung
- **Problem:** Alte Fakten stillschweigend gelöscht
- **Fix:** Versions-Kette mit Timestamp

### 35. Widersprüche ohne Nachfrage
- **Problem:** Detection existiert, User wird nie gefragt
- **Fix:** Proaktive Klärungsfrage

### 36. InsightEngine dupliziert Alerts
- **Problem:** Gleiche Entity, mehrere Checks, mehrere Alerts
- **Fix:** Deduplizierung nach Entity + Check-Type

### 37. WellnessAdvisor ignoriert Away-State
- **Problem:** Erinnerungen auch wenn keiner zuhause
- **Fix:** activity.away prüfen

### 38. DialogueState nur 10 Referenzen
- **Problem:** Lange Gespräche verlieren frühe Referenzen
- **Fix:** Auf 20 erhöhen oder semantisch gruppieren

---

## TOP 10 NACH IMPACT

| # | Verbesserung | Aufwand | Impact |
|---|---|---|---|
| 1 | Wetter-Forecast für Antizipation (11) | ~50 Zeilen | Verhindert Wasserschäden |
| 2 | Outcome→Anticipation Feedback (6) | ~40 Zeilen | Selbstkorrigierende Patterns |
| 3 | Mood→Personality Reaktion (10) | ~30 Zeilen | Menschlicherer Jarvis |
| 4 | Think-Ahead implementieren (14) | ~60 Zeilen | MCU-Jarvis-Level |
| 5 | Routine-Anomalie-Erkennung (12) | ~100 Zeilen | Fürsorge-Feature |
| 6 | InnerState Mood-Decay (17) | ~20 Zeilen | Realistischere Emotionen |
| 7 | DeviceHealth saisonale Baseline (23) | ~40 Zeilen | Weniger False Positives |
| 8 | HealthMonitor Hysterese (24) | ~10 Zeilen | Kein Alert-Flapping |
| 9 | Widerspruch-Nachfrage (35) | ~40 Zeilen | Besseres Gedächtnis |
| 10 | LearningTransfer aktivieren (1) | ~30 Zeilen | Schnelleres Lernen |
