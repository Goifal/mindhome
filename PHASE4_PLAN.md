# MindHome Phase 4 — Implementierungsplan
# "Smart Features + Gesundheit" (29 Features)

> **Stand:** 2026-02-14
> **Branch:** `claude/plan-phase-4-SM8O7`
> **Zielversion:** v0.7.0+
> **Bereits fertig:** #7 Szenen-Generator, #8 Anomalieerkennung, #9 Korrelationsanalyse
> **Zu implementieren:** 26 Features

---

## Strategie

Phase 4 wird in **6 Batches** mit **~15 Commits** implementiert:

1. Zuerst die **Infrastruktur** (Modul-Struktur, DB-Migration, Feature-Flags, Retention)
2. Dann Feature-Batches in logischer Reihenfolge
3. Jeder Batch: Backend → Frontend → Tests
4. Jedes Feature: Graceful Degradation bei fehlenden Sensoren
5. Am Ende: Dashboard, Version-Bump, README-Update, Changelog

### Commit-Plan (Hybrid: ~15 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v0.7.0` | 0 | version.py |
| 2 | `feat: Add Phase 4 infrastructure` | 0 | engines/ stubs, routes/health.py, feature flags, bus_type |
| 3 | `feat: Add Phase 4 DB models + migration v8` | 0 | models.py + migration + retention |
| 4 | `feat(energy): Add optimization + forecaster` | 1 | #1, #26 |
| 5 | `feat(energy): Add PV management + standby killer` | 1 | #2, #3 |
| 6 | `feat(sleep): Add detection + quality tracker` | 2 | #4, #16 |
| 7 | `feat(sleep): Add smart wakeup + morning routine` | 2 | #25, #5 |
| 8 | `feat(presence): Add room transitions + visit prep + vacation` | 2 | #6, #22, #29 |
| 9 | `feat(comfort): Add score + climate traffic light` | 3 | #10, #17 |
| 10 | `feat(comfort): Add ventilation + circadian lighting` | 3 | #18, #27 |
| 11 | `feat(weather): Add alerts` | 3 | #21 |
| 12 | `feat(ai): Add adaptive timing + habit drift + mood` | 4 | #11, #12, #15 |
| 13 | `feat(ux): Add favorites + calendar + screen time + gentle + context notifications` | 4 | #20, #13, #14, #19, #23, #24 |
| 14 | `feat(health): Add dashboard` | 5 | #28 |
| 15 | `docs: Finalize Phase 4` | 5 | README, Changelog, Translations |

---

## Batch 0: Infrastruktur & Datenbank (Commits 1-3)

**Ziel:** Modul-Struktur anlegen, DB-Migration, Feature-Flags, Retention-Policy.

### 0a: Engine-Module auslagern (automation_engine.py → engines/)

`automation_engine.py` ist bereits 1756 Zeilen. Statt alle neuen Klassen dort reinzupacken,
werden sie in eigene Module ausgelagert. `automation_engine.py` bleibt als Orchestrator.

```
engines/
├── __init__.py               # Exports aller Engine-Klassen
├── sleep.py                  # SleepDetector, WakeUpManager (#4, #16, #25)
├── energy.py                 # EnergyOptimizer, StandbyMonitor, EnergyForecaster (#1, #3, #26)
├── circadian.py              # CircadianLightManager (#27)
├── comfort.py                # ComfortCalculator, VentilationMonitor (#10, #17, #18)
├── routines.py               # RoutineEngine, MoodEstimator (#5, #15)
├── weather_alerts.py         # WeatherAlertManager (#21)
└── visit.py                  # VisitPreparationManager (#22)
```

Bestehende Klassen in `automation_engine.py` bleiben dort (SuggestionGenerator,
FeedbackProcessor, AutomationExecutor, ConflictDetector, PhaseManager, AnomalyDetector,
NotificationManager, PresenceModeManager, PluginConflictDetector, QuietHoursManager).
Nur neue Phase-4-Klassen kommen in `engines/`.

### 0b: Feature-Flags

Nicht jeder User hat alle Sensoren. Features können einzeln aktiviert/deaktiviert werden
über `SystemSettings`-Einträge:

```
phase4.sleep_detection      = true/false  (braucht: Bewegungsmelder oder Licht im Schlafzimmer)
phase4.sleep_quality        = true/false  (braucht: #4 + optional Temp/CO2-Sensor)
phase4.smart_wakeup         = true/false  (braucht: dimmbare Lampe im Schlafzimmer)
phase4.energy_optimization  = true/false  (braucht: Power-Sensoren)
phase4.pv_management        = true/false  (braucht: Solar-Sensoren)
phase4.standby_killer       = true/false  (braucht: Power-Sensoren an Geräten)
phase4.energy_forecast      = true/false  (braucht: EnergyReadings Verlaufsdaten)
phase4.comfort_score        = true/false  (braucht: min. 1 Sensor: Temp ODER Humidity ODER CO2)
phase4.ventilation_reminder = true/false  (braucht: CO2-Sensor ODER Fenster-Kontakt)
phase4.circadian_lighting   = true/false  (braucht: dimmbare Lampen)
phase4.weather_alerts       = true/false  (braucht: weather.* Entity)
phase4.screen_time          = true/false  (braucht: media_player Entity)
phase4.mood_estimate        = true/false  (braucht: mehrere aktive Domains)
phase4.room_transitions     = true/false  (braucht: Bewegungsmelder in >1 Raum)
phase4.visit_preparation    = true/false
phase4.vacation_detection   = true/false  (braucht: Person-Tracking)
phase4.habit_drift          = true/false  (braucht: >30 Tage Pattern-Daten)
phase4.adaptive_timing      = true/false
phase4.calendar_integration = true/false  (braucht: calendar.* Entity)
phase4.health_dashboard     = true/false
```

- Jeder Scheduler-Task prüft sein Flag bevor er läuft
- Frontend zeigt nur aktivierte Features im Menü
- Defaults: Features ohne spezielle Sensoren = true, mit Sensoren = auto-detect
- API: `GET /api/system/phase4-features` → Liste mit Status + Sensor-Anforderungen
- API: `PUT /api/system/phase4-features/<key>` → Feature ein/ausschalten

### 0c: Graceful Degradation

Jedes Feature muss mit **Minimal-Sensorik** funktionieren:

| Feature | Voll-Sensorik | Fallback wenn fehlt |
|---------|---------------|---------------------|
| Schlaf-Erkennung | Bewegungsmelder Schlafzimmer | Licht-aus + Inaktivität > 30 Min |
| Schlafqualität | Temp + CO2 + Bewegung | Score nur aus vorhandenen Faktoren (Gewichtung anpassen) |
| Lüftungserinnerung | CO2-Sensor | Timer-basiert (alle 2h erinnern) |
| Komfort-Score | Temp + Humidity + CO2 + Lux | Score aus vorhandenen Sensoren, fehlende = neutral (50/100) |
| PV-Lastmanagement | Solar-Sensor | Feature auto-deaktiviert |
| Bildschirmzeit | Media-Player Entity | Feature auto-deaktiviert |
| Wetter-Vorwarnung | weather.* Entity | Feature auto-deaktiviert |
| Stimmungserkennung | Mehrere aktive Domains | Nur "Aktiv"/"Ruhig" aus Bewegungsdaten |

### 0d: Data Retention Policy

Hochfrequente Tabellen brauchen Cleanup, sonst wächst DB unkontrolliert:

| Tabelle | Frequenz | Rows/Jahr (5 Räume) | Retention |
|---------|----------|---------------------|-----------|
| `ComfortScore` | 15 Min | ~175.000 | 90 Tage Detail, dann Tages-Durchschnitt behalten |
| `HealthMetric` | 15 Min | ~35.000 | 30 Tage Detail, dann Wochen-Summary |
| `EnergyForecast` | täglich | ~1.800 | 365 Tage, dann löschen |
| `SleepSession` | täglich | ~730 | Unbegrenzt (kleine Tabelle) |
| `WeatherAlert` | bei Bedarf | ~500 | 30 Tage nach Ablauf löschen |
| `EnergyReading` (besteht) | ~5 Min | ~525.000 | 90 Tage Detail, dann Stunden-Durchschnitt |
| `StateHistory` (besteht) | Events | variabel | 30 Tage (bestehende Policy beibehalten) |

Neuer Scheduler-Task: `data_retention_cleanup` — 1x/Nacht um 03:30:
1. Aggregiert alte Detail-Daten zu Summaries
2. Löscht aggregierte Detail-Rows
3. Loggt Cleanup-Ergebnis in AuditTrail

### 0e: Neue Spalte `bus_type` in Device

Für KNX-spezifische Optimierungen (Transition, schnellere Erkennung):

| Model | Neue Spalte | Werte |
|-------|-------------|-------|
| `Device` | `bus_type` (String, default=null) | `"knx"`, `"zigbee"`, `"wifi"`, `"zwave"`, `null` (unbekannt) |

- Automatisch erkennbar aus Entity-ID-Prefix oder HA Device-Registry
- Nutzen: KNX-Geräte können native Transitions, Zigbee hat Latenz, etc.
- Feature #23 (Sanftes Eingreifen) kann bus_type-spezifische Strategien wählen

### 0f: Neue Models in `models.py`

| Model | Zweck | Felder |
|-------|-------|--------|
| `SleepSession` | Schlaf-Tracking (#4, #16) | user_id, sleep_start, sleep_end, quality_score, context (JSON), source |
| `ComfortScore` | Komfort-Bewertung (#10) | room_id, score (0-100), factors (JSON: temp, humidity, light, air), timestamp |
| `HealthMetric` | Gesundheits-Aggregation (#28) | user_id, metric_type, value, unit, context (JSON), timestamp |
| `WakeUpConfig` | Weck-Konfiguration (#25) | user_id, enabled, wake_time, linked_to_schedule, light_entity, climate_entity, cover_entity, ramp_minutes, is_active |
| `CircadianConfig` | Zirkadiane Beleuchtung (#27) | room_id, enabled, control_mode ("mindhome" / "hybrid_hcl"), light_type ("dim2warm" / "standard" / "tunable_white"), brightness_curve (JSON), hcl_pause_ga (String, KNX GA), hcl_resume_ga (String, KNX GA), override_sleep (Int %), override_wakeup (Int %), override_guests (Int %), override_transition_sec (Int) |
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
| `Device` | `bus_type` (String, default=null) | KNX/Zigbee/WiFi Erkennung |

### 0g: Migration v8:
- Alle `CREATE TABLE` + `ALTER TABLE` Statements
- Feature-Flag Defaults in `SystemSettings` einfügen
- `db_migration_version` auf 8 setzen

---

## Batch 1: Energie & Solar — Commits 4-5 (Features #1, #2, #3, #26)

### #1 Energieoptimierung
**Dateien:** `engines/energy.py`, `routes/energy.py`, `domains/energy.py`

- **Backend:**
  - `EnergyOptimizer`-Klasse in `engines/energy.py`
  - Analysiert Verbrauchsmuster pro Gerät/Raum
  - Erkennt Spitzenlasten und schlägt Verlagerungen vor
  - Vergleicht Tagesverbrauch mit Durchschnitt → Spar-Tipps
  - API: `GET /api/energy/optimization` → Empfehlungen
  - API: `GET /api/energy/savings` → Einspar-Potenzial in EUR
- **Frontend:** Neuer Tab "Optimierung" in der Energie-Seite

### #2 PV-Lastmanagement
**Dateien:** `domains/solar.py`, `routes/energy.py`, `engines/energy.py`

- **Backend:**
  - `solar.py` → `evaluate()` implementieren
  - PV-Überschuss erkennen (Produktion > Verbrauch)
  - Prioritätsliste: Welche Geräte bei Überschuss einschalten
  - Scheduler-Task: Alle 5 Min PV-Status prüfen
  - API: `GET /api/energy/pv-status` → aktueller Überschuss
  - API: `PUT /api/energy/pv-priorities` → Prioritäten setzen
- **Frontend:** PV-Karte mit Flussdiagramm (Produktion → Verbrauch → Netz)

### #3 Standby-Killer (Vervollständigung)
**Dateien:** `engines/energy.py`, `routes/energy.py`

- **Backend:**
  - `StandbyMonitor`-Klasse in `engines/energy.py`: Prüft alle konfigurierten Geräte
  - Wenn Power < threshold_watts für > idle_minutes → Aktion
  - Aktion: Benachrichtigung ODER Auto-Off (je nach Config)
  - Scheduler-Task: Alle 5 Min Standby-Geräte prüfen
  - API: `GET /api/energy/standby-status` → aktuelle Standby-Geräte
- **Frontend:** Standby-Geräte-Liste mit geschätzten Kosten

### #26 Energieprognose
**Dateien:** `engines/energy.py`, `routes/energy.py`

- **Backend:**
  - `EnergyForecaster`-Klasse in `engines/energy.py`
  - Nutzt letzte 30 Tage EnergyReadings + Wetter + Wochentag
  - Gewichteter Durchschnitt (gleicher Wochentag + ähnliches Wetter)
  - Speichert Prognose in `EnergyForecast`
  - Scheduler-Task: 1x täglich um 00:05
  - API: `GET /api/energy/forecast` → Prognose nächste 7 Tage
- **Frontend:** Prognose-Chart auf der Energie-Seite

---

## Batch 2: Schlaf, Routinen & Anwesenheit — Commits 6-8 (Features #4, #16, #25, #5, #6, #22, #29)

### #4 Schlaf-Erkennung
**Dateien:** `engines/sleep.py`, `routes/health.py`

- **Backend:**
  - `SleepDetector`-Klasse in `engines/sleep.py`
  - Heuristiken: Letzte Aktivität im Haus, Licht aus, Bewegungssensoren inaktiv
  - Nutzt `PersonSchedule.time_sleep` als Referenz
  - Erzeugt `SleepSession`-Einträge (start/end)
  - Event-Bus: `sleep_detected` / `wake_detected` Events
  - API: `GET /api/health/sleep` → letzte 7 Tage Schlaf-Daten

### #16 Schlafqualitäts-Tracker
**Dateien:** `engines/sleep.py`, `routes/health.py`

- **Backend:**
  - Erweitert `SleepSession` um Quality-Score
  - Faktoren: Schlafdauer, Unterbrechungen (Licht/Bewegung nachts), Raumtemperatur, Luftqualität
  - Scoring: 0-100 (gewichteter Score aus allen Faktoren)
  - API: `GET /api/health/sleep-quality` → Trend + Details
- **Frontend:** Schlafqualitäts-Karte mit Trendlinie

### #25 Sanftes Wecken (Smart Wake-Up)
**Dateien:** `engines/sleep.py`, `routes/health.py`

- **Backend:**
  - `WakeUpManager`-Klasse in `engines/sleep.py`
  - Liest `WakeUpConfig` pro User
  - X Min vor Weckzeit: Licht langsam hochdimmen (0% → 100% über ramp_minutes)
  - Rollläden schrittweise öffnen
  - Heizung auf Komfort-Temperatur hochfahren
  - Nutzt `transition`-Parameter bei HA Service Calls
  - Scheduler-Task: Jede Minute prüfen ob Weckzeit naht
  - API: `GET/PUT /api/health/wakeup` → Konfiguration
- **Frontend:** Weck-Konfiguration (Zeit, Geräte, Ramp-Dauer)

### #5 Morgenroutine (Vervollständigung)
**Dateien:** `engines/routines.py`, `routes/patterns.py`

- **Backend:**
  - `RoutineEngine`-Klasse in `engines/routines.py`
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
**Dateien:** `engines/visit.py`, `routes/presence.py`

- **Backend:**
  - `VisitPreparationManager`-Klasse in `engines/visit.py`
  - Konfigurierbare Vorbereitungs-Aktionen (Licht, Temperatur, Musik)
  - Trigger: Manuell, Kalender-Event, Gast-Gerät erkannt
  - Template-System: "Gäste kommen" → [Wohnzimmer 22°C, Licht 80%, Musik an]
  - API: `GET/POST/PUT/DELETE /api/presence/visit-preparations`
  - API: `POST /api/presence/visit-preparations/<id>/activate`
- **Frontend:** Besuchs-Vorbereitungs-Seite mit Templates

### #29 Automatische Urlaubserkennung
**Dateien:** `automation_engine.py` (PresenceModeManager erweitern), `routes/presence.py`

- **Backend:**
  - Erweitert `PresenceModeManager`
  - Erkennt mehrtägige Abwesenheit (>24h alle Personen weg)
  - Aktiviert automatisch Urlaubs-Modus (Energiesparen)
  - Optional: Anwesenheitssimulation (Licht zufällig an/aus)
  - Deaktiviert sich automatisch bei Rückkehr
  - API: `GET /api/presence/vacation-detection` → Status

---

## Batch 3: Klima & Umgebung — Commits 9-11 (Features #10, #17, #18, #27, #21)

### #10 Komfort-Score
**Dateien:** `engines/comfort.py`, `routes/health.py`

- **Backend:**
  - `ComfortCalculator`-Klasse in `engines/comfort.py`
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
**Dateien:** `engines/comfort.py`, `domains/air_quality.py`, `routes/health.py`

- **Backend:**
  - Erweitert `VentilationReminder`-Model
  - Prüft: CO2 > Schwellwert ODER letzte Lüftung > X Min
  - Benachrichtigung: "Raum X sollte gelüftet werden"
  - Tracking: Fenster-Öffnung als "gelüftet" registrieren
  - Scheduler-Task: Alle 10 Min prüfen
  - API: `GET /api/health/ventilation` → Lüftungs-Status pro Raum
  - API: `PUT /api/health/ventilation/<room_id>` → Config

### #27 Zirkadiane Beleuchtung (Dual-Mode: MindHome + MDT KNX HCL)
**Dateien:** `engines/circadian.py`, `routes/health.py`, `domains/light.py`

Unterstützt drei **Lampentypen** und zwei **Steuerungsmodi**:

- **Lampentypen:**
  - `dim2warm` — Helligkeit steuert Farbtemperatur (z.B. Luxvenum 1800K-3000K über MDT AKD KNX Dimmer)
  - `tunable_white` — Helligkeit + Farbtemperatur unabhängig steuerbar
  - `standard` — Nur Helligkeit, keine Farbsteuerung

- **Modus 1: "mindhome" — MindHome steuert komplett**
  - MindHome fährt die Tageskurve selbst über brightness_pct
  - Brightness-Kurve pro Raum konfigurierbar (JSON):
    ```
    Morgen  06:00 →  50% brightness → ~2400K (Dim2Warm)  ↗ 15 Min Transition
    Tag     09:00 → 100% brightness → 3000K               ↗ 30 Min
    Abend   19:00 →  60% brightness → ~2500K               ↗ 45 Min
    Spät    21:30 →  30% brightness → ~2100K               ↗ 30 Min
    Nacht   23:00 →  10% brightness → ~1800K               ↗ 15 Min
    ```
  - Nutzt HA `transition`-Parameter für sanftes Dimmen
  - Nutzt DayPhase-System als Trigger
  - Kein ETS-Eingriff nötig

- **Modus 2: "hybrid_hcl" — MDT AKD HCL + MindHome Overrides**
  - MDT AKD fährt die Basis-Tageskurve (HCL in ETS parametriert)
  - MindHome beobachtet nur und greift bei Events ein:
    - Pausiert HCL via KNX Gruppenadresse (knx.send)
    - Setzt eigene brightness_pct
    - Gibt HCL wieder frei wenn Event vorbei
  - KNX-Integration über HA KNX-Integration (`knx.send` Service)
  - Vorteil: Tageskurve läuft auch wenn HA/MindHome offline ist

- **Smarte Overrides (beide Modi):**
  - Schlaf erkannt → override_sleep (z.B. 10%)
  - Aufwachen → override_wakeup (z.B. 70%, mit Rampe)
  - Gäste da → override_guests (z.B. 90%)
  - Szene aktiviert → Szenen-Helligkeit übernehmen
  - Transition konfigurierbar (override_transition_sec)

- **Backend:**
  - `CircadianLightManager`-Klasse
  - Scheduler-Task: Alle 15 Min Helligkeit prüfen/anpassen
  - Event-Bus: Reagiert auf `sleep.detected`, `wake.detected`, `guests.arrived`
  - API: `GET/PUT /api/health/circadian` → Config pro Raum
  - API: `GET /api/health/circadian/status` → aktueller Zustand pro Raum

- **Frontend:**
  - Toggle pro Raum (aktiv/inaktiv)
  - Modus-Auswahl: "MindHome steuert" / "Hybrid (MDT HCL + MindHome)"
  - Lampentyp-Auswahl: Dim2Warm / Tunable White / Standard
  - Tageskurve als Balken visualisieren (Brightness + geschätzte Kelvin)
  - Override-Einstellungen (Schlaf, Wakeup, Gäste)
  - Bei Hybrid: KNX Gruppenadresse eingeben (Pause/Resume)

### #21 Wetter-Vorwarnung (Vervollständigung)
**Dateien:** `engines/weather_alerts.py`, `domains/weather.py`

- **Backend:**
  - `WeatherAlertManager`-Klasse in `engines/weather_alerts.py`
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

## Batch 4: KI, Kalender & UX — Commits 12-13 (Features #11, #12, #15, #13, #14, #20, #19, #23, #24)

### #11 Adaptive Reaktionszeit
**Dateien:** `automation_engine.py` (AutomationExecutor erweitern)

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
**Dateien:** `engines/routines.py`, `routes/health.py`

- **Backend:**
  - `MoodEstimator`-Klasse in `engines/routines.py` (kein ML, regelbasiert)
  - Heuristiken aus Gerätenutzung:
    - Viel Medienkonsum + dunkles Licht → "Entspannt"
    - Hohe Aktivität, viele Raumwechsel → "Aktiv"
    - Wenig Aktivität tagsüber → "Ruhig"
    - Ungewöhnliche Zeiten → "Unregelmäßig"
  - Kein personenbezogenes Profiling, nur Haus-Level
  - API: `GET /api/health/mood-estimate` → aktuelle Einschätzung
  - Nutzt Mood für Beleuchtungs-/Musik-Vorschläge

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
**Dateien:** `engines/comfort.py`, `routes/health.py`

- **Backend:**
  - `ScreenTimeMonitor`-Klasse in `engines/comfort.py`
  - Trackt: Media-Player aktiv, TV-Entity an
  - Erinnerung nach X Min Nutzung: "Du schaust seit 2h fern"
  - Konfigurierbar pro User: Limit, Intervall
  - API: `GET /api/health/screen-time` → aktuelle Nutzung
  - API: `PUT /api/health/screen-time/config` → Konfiguration

### #23 Sanftes Eingreifen (Vervollständigung)
**Dateien:** `automation_engine.py` (AutomationExecutor erweitern)

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
**Dateien:** `automation_engine.py` (NotificationManager erweitern), `routes/notifications.py`

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

## Batch 5: Dashboard & Finalisierung — Commits 14-15 (Feature #28)

### #28 Gesundheits-Dashboard
**Dateien:** `routes/health.py`, Frontend

- **Backend:**
  - Neuer Blueprint `routes/health.py` (erstellt in Batch 0)
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

### Version & Dokumentation
- `version.py`: VERSION = "0.7.0", CODENAME = "Phase 4 - Smart Health"
- `README.md`: Phase 4 auf "✅ Fertig" setzen, Feature-Liste aktualisieren
- `CHANGELOG.md`: Alle 26 neuen Features dokumentieren
- Translations: `de.json` + `en.json` aktualisieren

### Neue Route-Registrierung
- `routes/__init__.py`: `health_bp` registrieren
- `app.py`: Health-Blueprint importieren

### Scheduler-Tasks (gruppiert für Performance)

Statt 11 einzelner Tasks → **5 gruppierte Tasks** + 2 Einzel-Tasks:

| Gruppen-Task | Intervall | Enthält | Features |
|--------------|-----------|---------|----------|
| `energy_check` | 5 Min | StandbyMonitor + PV-Überschuss | #2, #3 |
| `health_check` | 15 Min | ComfortScore + Circadian + Ventilation + ScreenTime | #10, #18, #19, #27 |
| `sleep_check` | 5 Min | SleepDetector + WakeUpManager | #4, #25 |
| `weather_check` | 30 Min | WeatherAlerts | #21 |
| `daily_batch` | 1x/Tag 00:05 | Energieprognose + Energieoptimierung | #1, #26 |
| `weekly_batch` | 1x/Woche So 03:00 | Gewohnheits-Drift | #12 |
| `data_retention` | 1x/Nacht 03:30 | Cleanup aller Retention-Policies | Infrastruktur |

---

## Zusammenfassung

| Batch | Features | Commits | Neue Dateien | Geänderte Dateien |
|-------|----------|---------|-------------|-------------------|
| 0 | Infrastruktur | 1-3 | engines/ (8 Dateien), routes/health.py | models.py, automation_engine.py, version.py |
| 1 | #1, #2, #3, #26 | 4-5 | — | engines/energy.py, routes/energy.py, domains/solar.py |
| 2 | #4, #16, #25, #5, #6, #22, #29 | 6-8 | — | engines/sleep.py, engines/routines.py, engines/visit.py, routes/health.py, routes/presence.py, routes/patterns.py, pattern_engine.py, automation_engine.py |
| 3 | #10, #17, #18, #27, #21 | 9-11 | — | engines/comfort.py, engines/circadian.py, engines/weather_alerts.py, routes/health.py, domains/light.py, domains/air_quality.py, domains/weather.py |
| 4 | #11, #12, #15, #13, #14, #20, #19, #23, #24 | 12-13 | — | automation_engine.py, pattern_engine.py, engines/routines.py, engines/comfort.py, routes/system.py, routes/scenes.py, routes/health.py, routes/notifications.py |
| 5 | #28 + Finalisierung | 14-15 | — | routes/health.py, app.jsx, version.py, README.md, de.json, en.json |

**Geschätzte Änderungen:**
- 9 neue Dateien: `engines/` (7 Module + __init__) + `routes/health.py`
- ~10 neue DB-Models + ~9 neue Spalten (inkl. bus_type)
- ~20 Feature-Flags in SystemSettings
- ~15 bestehende Dateien modifiziert
- ~20 neue API-Endpoints
- 7 gruppierte Scheduler-Tasks (statt 11 einzelne)
- 1 Data-Retention-Task (Nacht-Cleanup)
- Frontend: ~5 neue Seiten/Tabs in app.jsx
- Graceful Degradation für alle Sensor-abhängigen Features
- **6 Batches, ~15 Commits**
