# MindHome Phase 4 — Implementierungsplan
# "Smart Features + Gesundheit" (29 Features)

> **Stand:** 2026-02-13
> **Branch:** `claude/plan-phase-4-SM8O7`
> **Zielversion:** v0.7.0+
> **Bereits fertig:** #7 Szenen-Generator, #8 Anomalieerkennung, #9 Korrelationsanalyse
> **Zu implementieren:** 26 Features

---

## Strategie

Phase 4 wird in **9 Batches** implementiert, geordnet nach Abhängigkeiten:
1. Zuerst die **Datenbank-Migration** (alle neuen Models auf einmal)
2. Dann Feature-Batches in logischer Reihenfolge
3. Jeder Batch: Backend → Frontend → Tests
4. Am Ende: Version-Bump, README-Update, Changelog

---

## Batch 0: Datenbank & Infrastruktur

**Ziel:** Alle neuen DB-Models und Migration v8 auf einmal anlegen.

### Neue Models in `models.py`:

| Model | Zweck | Felder |
|-------|-------|--------|
| `SleepSession` | Schlaf-Tracking (#4, #16) | user_id, sleep_start, sleep_end, quality_score, context (JSON), source |
| `ComfortScore` | Komfort-Bewertung (#10) | room_id, score (0-100), factors (JSON: temp, humidity, light, air), timestamp |
| `HealthMetric` | Gesundheits-Aggregation (#28) | user_id, metric_type, value, unit, context (JSON), timestamp |
| `WakeUpConfig` | Weck-Konfiguration (#25) | user_id, enabled, wake_time, linked_to_schedule, light_entity, climate_entity, cover_entity, ramp_minutes, is_active |
| `CircadianConfig` | Zirkadiane Beleuchtung (#27) | room_id, enabled, morning_kelvin, day_kelvin, evening_kelvin, night_kelvin, transition_minutes |
| `EnergyForecast` | Energieprognose (#26) | date, predicted_kwh, actual_kwh, weather_condition, day_type, model_version |
| `VentilationReminder` | Lüftungserinnerung (#18) | room_id, last_ventilated, reminder_interval_min, co2_threshold, is_active |
| `WeatherAlert` | Wetter-Vorwarnung (#21) | alert_type, severity, message_de, message_en, valid_from, valid_until, was_notified, forecast_data (JSON) |
| `VisitPreparation` | Besuchs-Vorbereitung (#22) | name, guest_count, preparation_actions (JSON), auto_trigger, trigger_config (JSON), is_active |
| `ScreenTimeConfig` | Bildschirmzeit (#19) | user_id, entity_ids (JSON), daily_limit_min, reminder_interval_min, is_active |

### Neue Spalten in bestehenden Models:

| Model | Neue Spalte | Zweck |
|-------|-------------|-------|
| `LearnedScene` | `is_favorite` (Boolean, default=False) | Szenen-Favoriten (#20) |
| `LearnedScene` | `favorite_sort` (Integer, default=0) | Sortierung Favoriten |
| `LearnedPattern` | `transition_config` (JSON) | Sanftes Eingreifen (#23) |
| `LearnedPattern` | `adaptive_timing` (JSON) | Adaptive Reaktionszeit (#11) |
| `NotificationLog` | `context_data` (JSON) | Kontext-Benachrichtigungen (#24) |
| `NotificationLog` | `room_id` (FK) | Raum-Bezug für Kontext |
| `EnergyConfig` | `optimization_mode` (String) | Energieoptimierung (#1) |
| `EnergyConfig` | `pv_load_management` (Boolean) | PV-Lastmanagement (#2) |
| `EnergyConfig` | `pv_priority_entities` (JSON) | PV-Priorisierung |

### Migration v8:
- Alle `CREATE TABLE` + `ALTER TABLE` Statements
- `db_migration_version` auf 8 setzen

---

## Batch 1: Energie & Solar (Features #1, #2, #3, #26)

### #1 Energieoptimierung
**Dateien:** `routes/energy.py`, `automation_engine.py`, `domains/energy.py`

- **Backend:**
  - `EnergyOptimizer`-Klasse in `automation_engine.py`
  - Analysiert Verbrauchsmuster pro Gerät/Raum
  - Erkennt Spitzenlasten und schlägt Verlagerungen vor
  - Vergleicht Tagesverbrauch mit Durchschnitt → Spar-Tipps
  - API: `GET /api/energy/optimization` → Empfehlungen
  - API: `GET /api/energy/savings` → Einspar-Potenzial in EUR
- **Frontend:** Neuer Tab "Optimierung" in der Energie-Seite

### #2 PV-Lastmanagement
**Dateien:** `domains/solar.py`, `routes/energy.py`, `automation_engine.py`

- **Backend:**
  - `solar.py` → `evaluate()` implementieren
  - PV-Überschuss erkennen (Produktion > Verbrauch)
  - Prioritätsliste: Welche Geräte bei Überschuss einschalten
  - Scheduler-Task: Alle 5 Min PV-Status prüfen
  - API: `GET /api/energy/pv-status` → aktueller Überschuss
  - API: `PUT /api/energy/pv-priorities` → Prioritäten setzen
- **Frontend:** PV-Karte mit Flussdiagramm (Produktion → Verbrauch → Netz)

### #3 Standby-Killer (Vervollständigung)
**Dateien:** `routes/energy.py`, `automation_engine.py`

- **Backend:**
  - `StandbyMonitor`-Klasse: Prüft alle konfigurierten Geräte
  - Wenn Power < threshold_watts für > idle_minutes → Aktion
  - Aktion: Benachrichtigung ODER Auto-Off (je nach Config)
  - Scheduler-Task: Alle 5 Min Standby-Geräte prüfen
  - API: `GET /api/energy/standby-status` → aktuelle Standby-Geräte
- **Frontend:** Standby-Geräte-Liste mit geschätzten Kosten

### #26 Energieprognose
**Dateien:** `automation_engine.py`, `routes/energy.py`

- **Backend:**
  - `EnergyForecaster`-Klasse
  - Nutzt letzte 30 Tage EnergyReadings + Wetter + Wochentag
  - Gewichteter Durchschnitt (gleicher Wochentag + ähnliches Wetter)
  - Speichert Prognose in `EnergyForecast`
  - Scheduler-Task: 1x täglich um 00:05
  - API: `GET /api/energy/forecast` → Prognose nächste 7 Tage
- **Frontend:** Prognose-Chart auf der Energie-Seite

---

## Batch 2: Schlaf & Gesundheit (Features #4, #16, #25)

### #4 Schlaf-Erkennung
**Dateien:** `automation_engine.py`, `pattern_engine.py`

- **Backend:**
  - `SleepDetector`-Klasse
  - Heuristiken: Letzte Aktivität im Haus, Licht aus, Bewegungssensoren inaktiv
  - Nutzt `PersonSchedule.time_sleep` als Referenz
  - Erzeugt `SleepSession`-Einträge (start/end)
  - Event-Bus: `sleep_detected` / `wake_detected` Events
  - API: `GET /api/health/sleep` → letzte 7 Tage Schlaf-Daten

### #16 Schlafqualitäts-Tracker
**Dateien:** `automation_engine.py`, `routes/system.py` (neuer Blueprint: `routes/health.py`)

- **Backend:**
  - Erweitert `SleepSession` um Quality-Score
  - Faktoren: Schlafdauer, Unterbrechungen (Licht/Bewegung nachts), Raumtemperatur, Luftqualität
  - Scoring: 0-100 (gewichteter Score aus allen Faktoren)
  - API: `GET /api/health/sleep-quality` → Trend + Details
- **Frontend:** Schlafqualitäts-Karte mit Trendlinie

### #25 Sanftes Wecken (Smart Wake-Up)
**Dateien:** `automation_engine.py`, `routes/health.py`

- **Backend:**
  - `WakeUpManager`-Klasse
  - Liest `WakeUpConfig` pro User
  - X Min vor Weckzeit: Licht langsam hochdimmen (0% → 100% über ramp_minutes)
  - Rollläden schrittweise öffnen
  - Heizung auf Komfort-Temperatur hochfahren
  - Nutzt `transition`-Parameter bei HA Service Calls
  - Scheduler-Task: Jede Minute prüfen ob Weckzeit naht
  - API: `GET/PUT /api/health/wakeup` → Konfiguration
- **Frontend:** Weck-Konfiguration (Zeit, Geräte, Ramp-Dauer)

---

## Batch 3: Routinen & Anwesenheit (Features #5, #6, #22, #29)

### #5 Morgenroutine (Vervollständigung)
**Dateien:** `automation_engine.py`

- **Backend:**
  - `RoutineEngine`-Klasse
  - Erkennt Morgen-Sequenzen aus Pattern Engine (Cluster 5-9 Uhr)
  - Fasst einzelne Patterns zu einer "Routine" zusammen
  - Führt Routine als koordinierte Sequenz aus (nicht einzelne Patterns)
  - Unterstützt Delays zwischen Schritten
  - API: `GET /api/patterns/routines` → erkannte Routinen
  - API: `POST /api/patterns/routines/<id>/activate` → manuell starten

### #6 Raumübergangs-Erkennung
**Dateien:** `pattern_engine.py`

- **Backend:**
  - Erweitert `detect_cross_room_correlations()`
  - Erkennt sequentielle Raum-Nutzung (Bewegungsmelder + Licht-Events)
  - Baut Übergangs-Graph: Küche → Esszimmer → Wohnzimmer
  - Zeitliche Korrelation: "Nach Küche kommt meist Esszimmer (3 Min)"
  - Speichert als `LearnedPattern` mit `pattern_type="room_transition"`
  - Kann Licht im nächsten Raum vorab einschalten

### #22 Besuchs-Vorbereitung
**Dateien:** `automation_engine.py`, `routes/presence.py`

- **Backend:**
  - `VisitPreparationManager`-Klasse
  - Konfigurierbare Vorbereitungs-Aktionen (Licht, Temperatur, Musik)
  - Trigger: Manuell, Kalender-Event, Gast-Gerät erkannt
  - Template-System: "Gäste kommen" → [Wohnzimmer 22°C, Licht 80%, Musik an]
  - API: `GET/POST/PUT/DELETE /api/presence/visit-preparations`
  - API: `POST /api/presence/visit-preparations/<id>/activate`
- **Frontend:** Besuchs-Vorbereitungs-Seite mit Templates

### #29 Automatische Urlaubserkennung
**Dateien:** `automation_engine.py`, `routes/presence.py`

- **Backend:**
  - Erweitert `PresenceModeManager`
  - Erkennt mehrtägige Abwesenheit (>24h alle Personen weg)
  - Aktiviert automatisch Urlaubs-Modus (Energiesparen)
  - Optional: Anwesenheitssimulation (Licht zufällig an/aus)
  - Deaktiviert sich automatisch bei Rückkehr
  - API: `GET /api/presence/vacation-detection` → Status

---

## Batch 4: Klima & Umgebung (Features #10, #17, #18, #27, #21)

### #10 Komfort-Score
**Dateien:** `automation_engine.py`, `routes/health.py`

- **Backend:**
  - `ComfortCalculator`-Klasse
  - Bewertet pro Raum: Temperatur (20-23°C ideal), Luftfeuchtigkeit (40-60%), CO2 (<1000ppm), Lichtniveau
  - Gewichteter Score 0-100
  - Speichert in `ComfortScore` (alle 15 Min)
  - Scheduler-Task: Alle 15 Min berechnen
  - API: `GET /api/health/comfort` → aktuelle Scores pro Raum
  - API: `GET /api/health/comfort/<room_id>/history` → Trend
- **Frontend:** Komfort-Kacheln pro Raum (Farbskala grün/gelb/rot)

### #17 Raumklima-Ampel
**Dateien:** `routes/health.py`, Frontend

- **Backend:**
  - Nutzt `ComfortScore`-Daten
  - Ampel: Grün (80-100), Gelb (50-79), Rot (<50)
  - Pro Faktor einzeln: Temp-Ampel, Luft-Ampel, CO2-Ampel
  - API: `GET /api/health/climate-traffic-light` → pro Raum
- **Frontend:** Ampel-Widget (3 Kreise pro Raum, farbcodiert)

### #18 Lüftungserinnerung (Vervollständigung)
**Dateien:** `domains/air_quality.py`, `automation_engine.py`, `routes/health.py`

- **Backend:**
  - Erweitert `VentilationReminder`-Model
  - Prüft: CO2 > Schwellwert ODER letzte Lüftung > X Min
  - Benachrichtigung: "Raum X sollte gelüftet werden"
  - Tracking: Fenster-Öffnung als "gelüftet" registrieren
  - Scheduler-Task: Alle 10 Min prüfen
  - API: `GET /api/health/ventilation` → Lüftungs-Status pro Raum
  - API: `PUT /api/health/ventilation/<room_id>` → Config

### #27 Zirkadiane Beleuchtung
**Dateien:** `automation_engine.py`, `routes/health.py`, `domains/light.py`

- **Backend:**
  - `CircadianLightManager`-Klasse
  - Farbtemperatur-Kurve über den Tag:
    - Morgen: 2700K (warm)
    - Mittag: 5000K (neutral/kalt)
    - Abend: 3000K (warm)
    - Nacht: 2200K (sehr warm)
  - Übergang: Sanft über `transition_minutes`
  - Nutzt Day-Phases-System als Trigger
  - Nur für Lichter die `color_temp` unterstützen
  - Scheduler-Task: Alle 15 Min Farbtemperatur anpassen
  - API: `GET/PUT /api/health/circadian` → Config pro Raum
- **Frontend:** Farbtemperatur-Kurve visualisieren, Toggle pro Raum

### #21 Wetter-Vorwarnung (Vervollständigung)
**Dateien:** `domains/weather.py`, `automation_engine.py`

- **Backend:**
  - `WeatherAlertManager`-Klasse
  - Prüft HA-Wetter-Forecast auf:
    - Starkregen/Sturm → "Fenster schließen!"
    - Frost → "Heizung prüfen, Pflanzen schützen"
    - Hitze → "Rollläden schließen"
    - Schnee → "Heizung vorheizen"
  - Vorlaufzeit: 2-6 Stunden vor Event
  - Speichert in `WeatherAlert`, dedupliziert
  - Scheduler-Task: Alle 30 Min Forecast prüfen
  - API: `GET /api/health/weather-alerts` → aktive Warnungen

---

## Batch 5: KI-Verbesserungen (Features #11, #12, #15)

### #11 Adaptive Reaktionszeit
**Dateien:** `automation_engine.py`

- **Backend:**
  - Erweitert `AutomationExecutor._check_time_trigger()`
  - Lernt aus Feedback: Wenn User regelmäßig 5 Min früher handelt → Pattern-Zeit anpassen
  - Speichert Timing-Differenz in `LearnedPattern.adaptive_timing`
  - Algorithmus: Gleitender Durchschnitt der letzten 10 manuellen Ausführungen
  - Passt `trigger_conditions.hour/minute` schrittweise an

### #12 Gewohnheits-Drift (Vervollständigung)
**Dateien:** `pattern_engine.py`

- **Backend:**
  - `HabitDriftDetector`-Klasse
  - Vergleicht Pattern-Daten der letzten 2 Wochen mit den 2 Wochen davor
  - Erkennt: Zeitverschiebung, Frequenzänderung, neue Muster
  - Benachrichtigung: "Dein Schlafrhythmus hat sich um 30 Min verschoben"
  - Scheduler-Task: 1x wöchentlich (Sonntag 03:00)
  - API: `GET /api/patterns/drift` → erkannte Veränderungen

### #15 Stimmungserkennung
**Dateien:** `automation_engine.py`

- **Backend:**
  - `MoodEstimator`-Klasse (kein ML, regelbasiert)
  - Heuristiken aus Gerätenutzung:
    - Viel Medienkonsum + dunkles Licht → "Entspannt"
    - Hohe Aktivität, viele Raumwechsel → "Aktiv"
    - Wenig Aktivität tagsüber → "Ruhig"
    - Ungewöhnliche Zeiten → "Unregelmäßig"
  - Kein personenbezogenes Profiling, nur Haus-Level
  - API: `GET /api/health/mood-estimate` → aktuelle Einschätzung
  - Nutzt Mood für Beleuchtungs-/Musik-Vorschläge

---

## Batch 6: Kalender & Saison (Features #13, #14)

### #13 Saison-Kalender (Vervollständigung)
**Dateien:** `routes/system.py`, Frontend

- **Backend:**
  - Erweitert bestehende Season-Erkennung im ContextBuilder
  - Saisonale Empfehlungen generieren (Heizung runter im Frühling, etc.)
  - API: `GET /api/system/seasonal-tips` → aktuelle Saison-Tipps
- **Frontend:**
  - Kalender-Widget mit Saison-Anzeige
  - Saisonale Empfehlungen auf Dashboard

### #14 Kalender-Integration (Vervollständigung)
**Dateien:** `pattern_engine.py`, `routes/system.py`

- **Backend:**
  - Erweitert ContextBuilder um Kalender-Events
  - Pattern Engine berücksichtigt: "Wenn Termin in 30 Min → Licht an, Heizung hoch"
  - Unterstützt HA-Kalender-Entities (local_calendar, Google via HA)
  - API: `GET /api/system/calendar-events` → kommende Events
  - API: `PUT /api/system/calendar-config` → Kalender-Entity zuordnen

---

## Batch 7: UX Features (Features #20, #19, #23, #24)

### #20 Szenen-Favoriten
**Dateien:** `models.py`, `routes/scenes.py`, Frontend

- **Backend:**
  - `is_favorite` + `favorite_sort` Spalten in `LearnedScene`
  - API: `PUT /api/scenes/<id>/favorite` → Toggle Favorit
  - API: `GET /api/scenes/favorites` → nur Favoriten, sortiert
- **Frontend:**
  - Stern-Icon in Szenen-Liste
  - Favoriten-Sektion oben auf Dashboard
  - Drag & Drop Sortierung (optional)

### #19 Bildschirmzeit-Reminder
**Dateien:** `automation_engine.py`, `routes/health.py`

- **Backend:**
  - `ScreenTimeMonitor`-Klasse
  - Trackt: Media-Player aktiv, TV-Entity an
  - Erinnerung nach X Min Nutzung: "Du schaust seit 2h fern"
  - Konfigurierbar pro User: Limit, Intervall
  - API: `GET /api/health/screen-time` → aktuelle Nutzung
  - API: `PUT /api/health/screen-time/config` → Konfiguration

### #23 Sanftes Eingreifen (Vervollständigung)
**Dateien:** `automation_engine.py`

- **Backend:**
  - Erweitert `_execute_action()` um `transition`-Parameter
  - Licht: `transition: X` Sekunden bei HA Service Call
  - Klima: Temperatur in 0.5°C-Schritten über Y Min anpassen
  - Cover: Position schrittweise ändern (10% pro Intervall)
  - Config in `LearnedPattern.transition_config`:
    ```json
    {"type": "gradual", "duration_min": 15, "steps": 5}
    ```
  - Default: 5 Min Übergang für Licht, 30 Min für Klima

### #24 Kontext-Benachrichtigungen (Vervollständigung)
**Dateien:** `automation_engine.py`, `routes/notifications.py`

- **Backend:**
  - Erweitert `NotificationManager`
  - Kontext-Daten in `NotificationLog.context_data`:
    ```json
    {"room": "Wohnzimmer", "person": "Max", "day_phase": "Abend", "weather": "rainy"}
    ```
  - Nachrichtentext passt sich an: "Max, es regnet — Fenster im Wohnzimmer schließen?"
  - Raum-bezogene Notifications nur an Personen im/nahe dem Raum
  - Quiet-Hours-Integration: Kontextabhängig filtern

---

## Batch 8: Gesundheits-Dashboard (Feature #28)

### #28 Gesundheits-Dashboard
**Dateien:** `routes/health.py`, Frontend

- **Backend:**
  - Neuer Blueprint `routes/health.py` (erstellt in Batch 2)
  - Aggregiert alle Health-Daten:
    - Schlafqualität (letzte 7 Tage)
    - Komfort-Scores (alle Räume)
    - Raumklima-Ampeln
    - Lüftungs-Status
    - Bildschirmzeit
    - Mood-Estimate
  - API: `GET /api/health/dashboard` → aggregierte Übersicht
  - API: `GET /api/health/weekly-report` → Wöchentlicher Health-Report
- **Frontend:**
  - Neue Seite "Gesundheit" im Hauptmenü
  - Kacheln: Schlaf, Komfort, Klima, Lüftung, Bildschirmzeit
  - Trend-Charts (7 Tage)
  - Wöchentlicher Bericht (PDF-ähnlich)

---

## Batch 9: Finalisierung

### Version & Dokumentation
- `version.py`: VERSION = "0.7.0", CODENAME = "Phase 4 - Smart Health"
- `README.md`: Phase 4 auf "✅ Fertig" setzen, Feature-Liste aktualisieren
- `CHANGELOG.md`: Alle 26 neuen Features dokumentieren
- Translations: `de.json` + `en.json` aktualisieren

### Neue Route-Registrierung
- `routes/__init__.py`: `health_bp` registrieren
- `app.py`: Health-Blueprint importieren

### Scheduler-Tasks (Zusammenfassung)
| Task | Intervall | Feature |
|------|-----------|---------|
| Standby-Check | 5 Min | #3 |
| PV-Überschuss | 5 Min | #2 |
| Komfort-Score | 15 Min | #10 |
| Zirkadiane Beleuchtung | 15 Min | #27 |
| Lüftungserinnerung | 10 Min | #18 |
| Wetter-Forecast | 30 Min | #21 |
| Schlaf-Erkennung | 5 Min | #4 |
| Wakeup-Check | 1 Min | #25 |
| Energieprognose | 1x/Tag | #26 |
| Gewohnheits-Drift | 1x/Woche | #12 |
| Energieoptimierung | 1x/Tag | #1 |

---

## Zusammenfassung

| Batch | Features | Neue Dateien | Geänderte Dateien |
|-------|----------|-------------|-------------------|
| 0 | DB-Migration | — | models.py |
| 1 | #1, #2, #3, #26 | — | energy.py, solar.py, automation_engine.py |
| 2 | #4, #16, #25 | routes/health.py | automation_engine.py, pattern_engine.py |
| 3 | #5, #6, #22, #29 | — | automation_engine.py, presence.py, pattern_engine.py |
| 4 | #10, #17, #18, #27, #21 | — | health.py, automation_engine.py, weather.py, light.py, air_quality.py |
| 5 | #11, #12, #15 | — | automation_engine.py, pattern_engine.py |
| 6 | #13, #14 | — | system.py, pattern_engine.py |
| 7 | #20, #19, #23, #24 | — | scenes.py, health.py, automation_engine.py, notifications.py |
| 8 | #28 | — | health.py, app.jsx |
| 9 | Finalisierung | — | version.py, README.md, CHANGELOG.md, de.json, en.json |

**Geschätzte Änderungen:**
- 1 neue Datei: `routes/health.py`
- ~10 neue DB-Models + ~8 neue Spalten
- ~15 bestehende Dateien modifiziert
- ~20 neue API-Endpoints
- ~15 neue Scheduler-Tasks
- Frontend: ~5 neue Seiten/Tabs in app.jsx
