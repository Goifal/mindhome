# MindHome - version.py | Zentrale Versionsverwaltung
"""
MindHome Version Info
Alle Dateien importieren von hier - Version nur an EINER Stelle ändern.
"""

VERSION = "0.7.13"
BUILD = 66
BUILD_DATE = "2026-02-14"
CODENAME = "Phase 4 - Smart Health"

# Changelog
# Build 66: v0.7.13 Diagnose-Logging + Cross-Room Integration
#   - INFO-Logging: Zeitmuster zeigt actionable Events, Gruppen, Cluster, Confidence-Filter
#   - INFO-Logging: Korrelationen zeigt Trigger-Paare, Schwellwert-Filter, Confidence-Filter
#   - Fix: Cross-Room Korrelationen waren orphaned (5 Raumpaare gefunden, 0 Patterns erstellt)
#   - Cross-Room Raumpaare werden jetzt als correlation/insight Patterns gespeichert
#   - Analyse-Summary zeigt jetzt alle 4 Pattern-Typen (time, sequence, correlation, cross-room)
#
# Build 65: v0.7.12 Fix Korrelations-Regression (MAX_STATE_AGE 2h → 8h)
#   - Fix: 0 Korrelationsmuster durch zu aggressiven Staleness-Filter (2h → 8h)
#   - Viele Entities (person, Licht, Klima) halten State stundenlang
#   - Debug-Logging fuer Zeitmuster-Erkennung (Diagnose 0 time patterns)
#
# Build 64: v0.7.11 Mustererkennung komplett ueberarbeitet (29 Fixes)
#   KRITISCHE FIXES:
#   - Fix: Cross-Room Confidence-Formel (Doppelbestrafung behoben, min_count wirkt korrekt)
#   - Fix: Mitternachts-Bug in Clustering + Average (zirkulaerer Mittelwert via sin/cos)
#   - Fix: Confidence sinkt jetzt bei Upsert (gewichteter Durchschnitt 30/70 statt max())
#   - Fix: Executor prueft DOMAIN_THRESHOLDS vor Ausfuehrung (Schloss braucht 0.95)
#   - Fix: Bidirektionale Loop-Erkennung (A->B + B->A wird verhindert)
#   - Fix: unavailable/unknown States werden aus Analyse gefiltert
#   DATEN-QUALITAET:
#   - Korrelationen (B3) Room-Aware Filtering (same/cross-room Schwellwerte)
#   - entity_states Bereinigung in Korrelationen (max 2h Alter)
#   - Exclusions sofort wirksam (Detektoren + Executor Runtime)
#   - Example-Cap 20->50, Timing als Confidence-Faktor, 5s Min-Toleranz
#   - Automation-triggered Ketten werden uebersprungen
#   PERFORMANCE:
#   - Mutex-Lock verhindert parallele Analysen
#   - Thread-Lock fuer Dedup-Cache, Pre-Fetch Devices, Upsert-Cache
#   - Cross-Room Correlations in run_full_analysis integriert
#   INFRASTRUKTUR:
#   - Migration v11: 9 neue DB-Indexes
#   - API: Status "insight"/"rejected" in Whitelist
#   - Time-String Validierung im Context Builder
#
# Build 63: v0.7.10 Raum-Filter fuer Sequence-Patterns + JSX-Fix
#   - Fix: Cross-Room-Patterns (z.B. Wohnzimmer-BWM → Toilette-Licht) werden jetzt gefiltert
#     Same-Room: normaler Schwellwert (min 7 Vorkommen, Confidence 0.45)
#     Cross-Room: deutlich hoeher (min 20 Vorkommen, Confidence 0.65, strengere Timing-Varianz)
#   - entity→room_id Lookup vor Analyse, room-aware Thresholds in _detect_sequence_patterns()
#   - Fix: JSX adjacent-elements Fehler im EnergyPage Config-Tab (Fragment-Wrapper)
#
# Build 62: v0.7.9 Phase 4 Feature-Konfiguration pro Seite
#   - Neu: Umfassende Feature-Einstellungen fuer alle 20 Phase-4 Features
#   - Konfiguration-Tab auf Klima-, Gesundheits-, Energie- und KI-Seite
#   - Backend: PHASE4_FEATURE_SETTINGS mit GET/PUT per Category
#   - Wiederverwendbare FeatureSettingsPanel-Komponente (Number/Toggle/Select/Time)
#   - Pro Feature: An/Aus/Auto Toggle + detaillierte Parameter
#   - Fix: Domain-Filter erweitert um RoomDomainState.mode='off'
#
# Build 61: v0.7.8 Bugfix - Muster-Ablehnung & Domain-Ausschluss
#   - Fix: Abgelehnte Muster tauchten nach "Jetzt synchronisieren" wieder auf
#     Root-Cause: _upsert_pattern() pruefte nur is_active=True, rejected/disabled Muster unsichtbar
#     Fix: Query findet jetzt auch rejected/disabled Muster und ueberspringt sie
#   - Fix: Deaktivierte Domains (z.B. Klima, Licht) wurden bei Mustererkennung nicht beachtet
#     Root-Cause: run_full_analysis() filterte Events nicht nach Domain-Status
#     Fix: Events von deaktivierten Domains werden vor Analyse herausgefiltert
#
# Build 60: v0.7.7 UI Polish - Klima & KI Seiten
#   - ClimatePage: Hardcoded Hex-Farben ersetzt durch CSS-Variablen (--success, --warning, --danger, --info)
#   - ClimatePage: Tab-Bar auf btn btn-sm btn-primary/btn-ghost Klassen umgestellt
#   - ClimatePage: Cards auf className="card animate-in" Pattern umgestellt
#   - ClimatePage: Badges auf className="badge badge-*" Pattern umgestellt
#   - ClimatePage: Page-Header h2 mit Icon hinzugefuegt
#   - ClimatePage: Empty-States mit zentrierter Card + Icon statt rohem <p>
#   - ClimatePage: Formular-Inputs mit bg-tertiary + border-color Theming
#   - AiPage: Hardcoded Hex-Farben ersetzt durch CSS-Variablen
#   - AiPage: Tab-Bar auf btn btn-sm btn-primary/btn-ghost Klassen umgestellt
#   - AiPage: Cards auf className="card animate-in" Pattern umgestellt
#   - AiPage: Badges auf className="badge badge-*" Pattern umgestellt
#   - AiPage: Page-Header h2 mit Icon hinzugefuegt
#   - AiPage: Empty-States mit zentrierter Card + Icon
#   - AiPage: Mood-Stats als Grid mit bg-tertiary Kacheln + Icons
#   - var(--text-secondary) → var(--text-muted), var(--border) → var(--border-color)
#   - var(--primary) → var(--accent-primary), var(--card-bg) → className="card"
#
# Build 59: v0.7.6 Batch 5 - Health Dashboard & Finalisierung
#   - HealthAggregator Engine: Aggregiert Daten aus allen Phase 4 Engines
#   - HealthAggregator: Gesamt-Score (gewichtet: Schlaf 35%, Komfort 30%, Lueftung 20%, Bildschirmzeit 15%)
#   - HealthAggregator: Stuendliche Metric-Snapshots in health_metrics Tabelle
#   - HealthAggregator: Trend-Berechnung (improving/stable/declining) aus 2-Wochen-Vergleich
#   - Wochenbericht: Automatische Empfehlungen (Schlaf, Komfort, Bildschirmzeit)
#   - Wochenbericht: Woche-zu-Woche Vergleich mit Richtungsanzeige
#   - API: GET /api/health/dashboard (Aggregiertes Dashboard)
#   - API: GET /api/health/weekly-report (Wochenbericht mit Empfehlungen)
#   - API: GET /api/health/metrics/:type/history (Historische Metriken)
#   - Scheduler: health_aggregate (1h) - stuendliche Aggregation
#   - Frontend: Gesundheitsseite neues Dashboard-Tab (6 Metrik-Kacheln + Ampel + Wetter-Alerts)
#   - Frontend: Wochenbericht-Tab (4 Sektionen mit Vorwochen-Vergleich + Empfehlungen)
#   - Fix: MoodEstimator brightness None-Vergleich
#   - Fix: ComfortCalculator/VentilationMonitor Device.is_active → Device.is_tracked
#   - Fix: ComfortCalculator/VentilationMonitor Device.entity_id → Device.ha_entity_id
#
# Build 58: v0.7.5 Batch 4 - KI, Kalender & UX
#   - MoodEstimator (#15): Stimmungserkennung (Relaxed/Active/Cozy/Quiet/Away/Focused)
#   - MoodEstimator: Heuristik aus Media/Licht/Motion/Klima Zustaenden
#   - ScreenTimeMonitor (#19): Bildschirmzeit-Tracking (Media-Player Nutzung pro User)
#   - ScreenTimeMonitor: Tages-Limit + Erinnerungen (konfigurierbar)
#   - HabitDriftDetector (#12): Gewohnheits-Drift (2-Wochen Vergleich, Zeitverschiebung)
#   - AdaptiveTimingManager (#11): Lernt Timing aus manuellen Aktionen (gleitender Durchschnitt)
#   - GradualTransitioner (#23): Sanftes Eingreifen (Licht-Transition, Klima-Schritte)
#   - SeasonalAdvisor (#13): Saison-Tipps (Winter/Fruehling/Sommer/Herbst + Wetter)
#   - CalendarIntegration (#14): HA-Kalender Events (naechste 48h)
#   - Szenen-Favoriten (#20): Stern-Toggle + Favoriten-API
#   - API: 14 neue Endpunkte (mood, screen-time, drift, adaptive, seasonal, calendar, favorites)
#   - Scheduler: screen_time_check (5min), adaptive_check (15min), weekly_drift (7d)
#   - Frontend: Neue "KI" Seite mit 6 Tabs (Stimmung, Bildschirmzeit, Gewohnheiten, Adaptive, Saison, Kalender)
#   - Frontend: Szenen-Favoriten Stern in Szenen-Liste
#
# Build 57: v0.7.4 Batch 3 - Klima & Umgebung
#   - Fix: EventBus emit/publish Alias (Batch 2 Engines nutzten .emit, EventBus hat .publish)
#   - Fix: Event-Namen auf Dot-Notation (sleep.detected statt sleep_detected)
#   - ComfortCalculator (#10): Komfort-Score pro Raum (Temp/Feuchtigkeit/CO2/Licht gewichtet)
#   - ComfortCalculator (#17): Raumklima-Ampel (gruen/gelb/rot pro Faktor)
#   - VentilationMonitor (#18): Lueftungserinnerung (CO2-Schwellwert + Fenster-Tracking)
#   - CircadianLightManager (#27): Zirkadiane Beleuchtung (MindHome + Hybrid HCL Modus)
#   - CircadianLightManager: 3 Lampentypen (dim2warm, tunable_white, standard)
#   - CircadianLightManager: Event-basierte Overrides (Schlaf/Aufwachen/Gaeste)
#   - CircadianLightManager: Brightness + Color-Temperature Interpolation
#   - WeatherAlertManager (#21): Wetter-Vorwarnung (Frost/Hitze/Starkregen/Sturm/Schnee)
#   - WeatherAlertManager: 2-12h Vorlauf, Deduplizierung, Severity-Level
#   - API: 10 neue Endpunkte (comfort, traffic-light, ventilation, circadian CRUD, weather)
#   - Scheduler: comfort_check (15min), ventilation_check (10min), weather_check (30min)
#   - Frontend: Neue "Klima" Seite mit 4 Tabs (Komfort, Lueftung, Zirkadian, Wetter)
#   - Frontend: Komfort-Score Kacheln mit Ampel-Farben + Verlaufs-Balkendiagramm
#   - Frontend: Lueftungs-Status mit CO2-Werten und Fenster-Tracking
#   - Frontend: Zirkadian CRUD (Modus/Lampentyp/Override-Konfiguration)
#   - Frontend: Wetter-Warnungen mit Severity-Badges und Zeitfenster
#
# Build 56: v0.7.3 Batch 2 - Schlaf, Routinen & Anwesenheit
#   - SleepDetector: Schlaf-Erkennung via Motion+Licht-Heuristik (20-11 Uhr)
#   - SleepDetector: Schlafqualitaet (0-100) aus Dauer, Unterbrechungen, Temperatur
#   - WakeUpManager: Sanftes Wecken (Licht/Rolladen/Klima Ramp, pro User konfigurierbar)
#   - RoutineEngine: Morgen-/Abend-Routinen aus Pattern-Daten erkennen + manuell starten
#   - RoutineEngine: Raumuebergangs-Erkennung (Motion-Events → Transitions-Graph)
#   - VisitPreparationManager: Besuchs-Vorlagen (Aktionen: Licht, Temp, Musik)
#   - VacationDetector: Automatische Urlaubserkennung (>24h weg → Vacation-Modus)
#   - VacationDetector: Anwesenheitssimulation (18-23 Uhr Licht-Toggle)
#   - API: 12 neue Endpunkte (/health/sleep, wakeup, routines, visit, vacation)
#   - Scheduler: sleep_check (5min), visit_vacation_check (10min), routine_detect (24h)
#   - Frontend: Neue "Gesundheit" Seite mit 5 Tabs (Schlaf, Wecken, Routinen, Besuch, Urlaub)
#   - Frontend: Schlaf-Balkendiagramm (14 Tage, Qualitaet farbcodiert)
#   - Frontend: Wecker-Management (CRUD mit Entity-Konfiguration)
#   - Frontend: Routinen-Karten mit Steps + manueller Aktivierung
#   - Frontend: Besuchs-Vorlagen mit Aktionen-Builder
#   - Frontend: Urlaubs-Status mit Auto-Erkennung Info
#
# Build 55: v0.7.2 Frontend Batch 1 + Phase 4 Feature-Flags UI
#   - Energy-Dashboard: 3 neue Tabs (Optimierung, Solar/PV, Prognose)
#   - Optimierung-Tab: Spar-Empfehlungen, Einsparpotenzial (EUR/kWh)
#   - Solar/PV-Tab: Live-Status (Produktion/Verbrauch/Ueberschuss/Eigenverbrauch)
#   - Solar/PV-Tab: PV-Prioritaeten-Management (Geraete hinzufuegen/entfernen)
#   - Prognose-Tab: 7-Tage Balkendiagramm + Detailtabelle (Prognose vs Ist)
#   - Standby-Tab: Live-Standby-Geraete mit Idle-Dauer oben angezeigt
#   - Uebersicht-Tab: Quick-Cards (Einsparpotenzial, Solar, Empfehlungen)
#   - Settings: Phase 4 Feature-Flags Panel (20 Features toggle: Auto/An/Aus)
#   - Config-Tab: PV-Lastmanagement Checkbox bei Solar-Konfiguration
#
# Build 54: v0.7.1 Batch 1 - Energie & Solar
#   - EnergyOptimizer: Verbrauchsmuster-Analyse, Spar-Empfehlungen, EUR-Schaetzung
#   - EnergyForecaster: 7-Tage-Prognose (Wochentag + Wetter gewichtet)
#   - PV-Lastmanagement: Ueberschuss-Erkennung, Prioritaetsliste, Auto-Verschiebung
#   - StandbyMonitor: Standby-Erkennung mit Benachrichtigung oder Auto-Off
#   - Neue API-Endpunkte: /api/energy/optimization, forecast, pv-status, standby-status
#   - Scheduler: energy_check (5min), daily_batch (1x/Tag)
#
# Build 53: v0.7.0 Phase 4 - Smart Health
#   - Infrastruktur: engines/ Modul-Struktur, Feature-Flags, Data Retention
#   - Energie: Optimierung, PV-Lastmanagement, Standby-Killer, Prognose
#   - Schlaf: Erkennung, Qualitaets-Tracker, Sanftes Wecken, Morgenroutine
#   - Klima: Komfort-Score, Raumklima-Ampel, Lueftungserinnerung, Zirkadian
#   - KI: Adaptive Reaktionszeit, Gewohnheits-Drift, Stimmungserkennung
#   - UX: Favoriten, Kalender, Bildschirmzeit, Sanftes Eingreifen
#   - Gesundheits-Dashboard mit Wochenbericht
#
# Build 52: v0.6.51 DB Cleanup, Indexes & Maintenance
#   - DB Indexes: 7 neue Indexes auf learned_patterns + pattern_match_log
#     (status+is_active, pattern_type+is_active, domain_id, room_id, confidence, last_matched_at, matched_at)
#   - run_cleanup(): Intelligentes Aufraeumen implementiert (war vorher undefiniert/crashte)
#     - Rejected Patterns nach 30 Tagen loeschen
#     - Disabled Patterns (confidence < 0.1) nach 14 Tagen loeschen
#     - StateHistory nach data_retention_days loeschen
#     - PatternMatchLog nach 90 Tagen loeschen
#     - ActionLog nach data_retention_days loeschen
#     - NotificationLog nach 90 Tagen loeschen
#     - AuditTrail nach 180 Tagen loeschen
#   - Smart Eviction: Bei > 500 observed Patterns werden die mit niedrigster
#     Confidence + aeltestem last_matched_at zuerst entfernt
#   - DB Maintenance: Woechentliches VACUUM + ANALYZE (SQLite Optimierung)
#   - Scheduler: Cleanup taeglich, Maintenance woechentlich
#   - Migration v9: Indexes als DB-Migration fuer bestehende Installationen
#
# Build 51: v0.6.50 Presence Auto-Detection Fix
#   - Event-basierte Erkennung: person.*/device_tracker.* loest sofort check aus
#   - Kein falsches "Abwesend" mehr bei HA-API-Ausfall (502 Gateway)
#   - Manual Override wird in check_auto_transitions geprueft
#   - Manual Override auto-reset nach 4 Stunden
#   - Debounce reduziert: 60s -> 30s
#   - Polling-Fallback: 120s -> 60s
#
# Build 50: v0.6.49 TTS Speaker-Toggle rechts + UI Polish
#   - Speaker Ein/Aus-Toggle nach ganz rechts verschoben
#   - Layout: Name | Raum-Dropdown | Test | Toggle
#
# Build 49: v0.6.48 Einzelne TTS-Speaker ein/ausschaltbar
#   - Toggle pro Speaker in der TTS-Sektion (ein/aus)
#   - Deaktivierte Speaker werden im Backend gefiltert (tts_disabled_speakers)
#   - Visuelles Dimming bei deaktivierten Speakern
#
# Build 48: v0.6.47 Gruppierte Regeln + TTS Motion-Routing
#   - ManualRules gruppiert nach Trigger (1 Sensor → n Aktionen visuell)
#   - "+ Aktion hinzufuegen" Button pro Trigger-Gruppe
#   - Delay-Feld im Regel-Modal
#   - TTS: Globaler Ein/Aus-Schalter
#   - TTS: Bewegungs-Modus - nur Speaker im Raum mit letzter Bewegung spricht
#   - TTS: Konfigurierbarer Timeout (15/30/60 min) + Fallback-Option
#   - Backend: /api/tts/last-motion Endpoint fuer Bewegungs-Tracking
#
# Build 47: v0.6.46 Frontend-Fix bilingual Controls/Features
#   - Fix: React Error #31 in DomainsPage (Objekte statt Strings gerendert)
#   - Frontend liest jetzt label_de/label_en je nach Spracheinstellung
#
# Build 46: v0.6.45 Domains erweitert + Controls/Features zweisprachig
#   - Neue Domains: humidifier (Luftbefeuchter), camera (Kamera)
#   - Proximity von System-Domain nach Presence-Domain verschoben
#   - alarm_control_panel entfernt (redundant mit Lock/Sicherheit)
#   - DOMAIN_PLUGINS: controls + pattern_features jetzt bilingual (label_de/label_en)
#   - Konsistente Zweisprachigkeit ueber alle 21 Domains
#
# Build 31: v0.6.30 Raum-Domain-Modus (Hierarchie)
#   - Neues mode-Feld in RoomDomainState (global/suggest/auto/off)
#   - API: PUT /api/phases/{room}/{domain}/mode
#   - Frontend: Modus-Dropdown pro Domain auf Raum-Karte
#   - Hierarchie: Global aus = immer aus, Raum kann verfeinern
# Build 29: v0.6.28 Domain-Karten Layout verbessert
#   - Control-Badges und Pattern-Badges als getrennte Gruppen mit Trennlinie
#   - Domain-Icons: mdi: zu mdi- Konvertierung korrigiert
#   - Plugin-Settings API liefert DEFAULT_SETTINGS aus allen Domain-Plugins
# Build 28: v0.6.27 Domain-Steuerung anzeigen und bearbeitbar
#   - Domain-Karten zeigen Plugin-Settings (Steuerung) unterhalb Trennstrich an
#   - Bearbeiten-Button fuer ALLE Domains (nicht nur Custom)
#   - MdiIconPicker im Edit- und Create-Dialog (statt Text-Input)
#   - Steuerungs-Einstellungen editierbar (Mode, Helligkeit, Temperatur etc.)
#   - Backend: Icon-Aenderung auch fuer System-Domains erlaubt
#
# Build 27: v0.6.26 UI: Domain-Karten an Raeume/Personen-Design angeglichen
#   - Domain-Karten nutzen jetzt card/card-icon/card-title/card-subtitle Klassen
#   - Rundes Icon mit Farbhintergrund statt flachem Icon
#   - Einheitliches Grid (320px min) und Card-Layout wie Raeume und Personen
#   - Linker Akzentbalken entfernt, konsistentes .card Design
#   - Edit/Delete Buttons fuer Custom-Domains neben Toggle verschoben
#
# Build 26: v0.6.25 Schicht-Sync: [MH]-Tag Erkennung statt Description (Fix Duplikate)
#   - Root-Cause: HA Calendar API gibt description nicht zurueck → Events nie als "eigene" erkannt
#   - Fix: Events werden jetzt mit [MH]-Tag im Summary markiert (z.B. "Frueh (Max) [MH]")
#   - Fix: Erkennung per Summary-Tag statt Description (funktioniert mit allen HA-Kalendern)
#   - Fix: Legacy-Events ohne [MH] aber mit "MindHome Schicht:" Description werden auch erkannt
#   - Fix: Alle Duplikate pro Tag werden bis auf 1 geloescht
#   - Fix: Veraltete Events (Rotation geaendert) werden automatisch entfernt
#
# Build 25: v0.6.24 Kompletter Rewrite Schicht-Kalender-Sync (Duplikate + Loeschung)
#   - Ablauf: 1) Erwartete Events berechnen, 2) HA-Kalender lesen, 3) Diff, 4) Loeschen/Erstellen
#
# Build 24: v0.6.23 Fix Schicht-Kalender Datum off-by-one + alte Events loeschen
#   - Fix: Schicht-Startdatum wurde 1 Tag zu frueh in Kalender geschrieben (UTC vs Lokalzeit)
#   - Fix: Kalender-Sync nutzt jetzt HA-Timezone statt UTC fuer Datumsberechnung
#   - Fix: Alte Kalender-Eintraege werden jetzt bei Aenderung automatisch geloescht
#   - Fix: iCal Export hatte gleichen Timezone-Bug (ebenfalls gefixt)
#
# Build 23: v0.6.22 Fix Anwesenheitserkennung (7 Bugs)
#   - Fix: get_current_mode() ignorierte Logs ohne mode_id - mode_name Fallback + Backfill
#   - Fix: auto_detect Endpoint schrieb kein mode_id in PresenceLog
#   - Fix: API fallback waehlte immer "Zuhause" (priority.asc statt desc)
#   - Fix: API fallback entfernt - zeigt "Erkennung laeuft..." statt falsches "Zuhause"
#   - Fix: Frontend Auto-Select hardcoded "Zuhause" - jetzt HA-basierte Auto-Detection
#   - Fix: Kaskadierende Fehler: kein mode_id → get_current_mode null → Fallback Zuhause
#   - Fix: System blieb permanent auf "Zuhause" auch wenn niemand zuhause war
#
# Build 22: v0.6.21 Schicht-Auto-Sync in HA-Kalender
#   - Kalender: Schichtplan automatisch in HA-Kalender schreiben (Google Calendar, etc.)
#   - Kalender: Background-Task alle 6h, Duplikat-Erkennung via UID-Tracking
#   - Kalender: Konfigurierbarer Ziel-Kalender und Vorlaufzeit (7-90 Tage)
#   - Kalender: "Jetzt synchronisieren" Button fuer sofortigen Sync
#   - Kalender: API GET/PUT /api/calendar/shift-sync + POST shift-sync/run
#   - Kalender: Frontend ShiftCalendarSync Komponente mit Toggle
#
# Build 21: v0.6.20 Kalender-Schreiben (HA Calendar Events)
#   - Kalender: Termine direkt in HA-Kalender erstellen (Google Calendar, CalDAV, etc.)
#   - Kalender: calendar.create_event + calendar.delete_event Service-Aufrufe
#   - Kalender: API-Routen POST/DELETE /api/calendar/events
#   - Kalender: Frontend CalendarEventCreator mit Ganztags-/Zeitraum-Support
#   - Kalender: Beschreibung und Ort optional
#
# Build 20: v0.6.19 Kalender-Sync, Presence-System, UX-Verbesserungen
#   - Personen: Bearbeiten (Name, Rolle, HA-Person) + Geraete-Zuweisung (device_tracker)
#   - Personen: Device-Tracker Live-State (home/away Punkt mit Farbindikator)
#   - Kalender: iCal-Export mit Token-Schutz und Cache-Header
#   - Kalender: HA-Kalender-Import (Google, CalDAV) mit Sync-Konfiguration
#   - Kalender: Synced Events in Monatsansicht (blaue Punkte)
#   - Kalender: Konfigurierbarer Schicht-Export-Zeitraum (14-365 Tage)
#   - Kalender: Weekday/Homeoffice-Profile im iCal-Export (RRULE)
#   - Kalender: Trigger Background-Loop (5min, Keyword-Match → HA-Service)
#   - Kalender: HA-Offline Fallback fuer Calendar API
#   - Presence: Default-Modi beim DB-Init (Zuhause, Abwesend, Schlaf, Urlaub, Besuch)
#   - Presence: auto_config mit Conditions (first_home, all_away, all_home)
#   - Presence: PersonDevice in Erkennung integriert
#   - Presence: Gaeste in anyone_home Logik + GuestDevice Pflege
#   - Presence: NotificationLog-Felder gefixed (title, user_id, was_read)
#   - UX: Loesch-Bestaetigungen fuer alle 9 fehlenden Delete-Operationen
#   - UX: Auto-Refresh bei Tab-Wechsel (>30s inaktiv)
#   - UX: Bulk-Pattern-Ops Error-Handling (kein Optimistic Update mehr)
#   - Data: SAMPLING_THRESHOLDS +13 device_classes (signal_strength, gas, etc.)
#   - Data: ALWAYS_LOG_DOMAINS +12 Domains (vacuum, humidifier, valve, etc.)
#   - Data: Fallback fuer unbekannte Sensoren (konservativer Schwellwert)
#   - Data: Rate-Limit auf 600 erhoeht (Events + HTTP API)
#   - Data: Dedup-Cache selektive Bereinigung statt clear()
#   - Config: panel_admin: false (Zugang fuer alle HA-Benutzer)
#
# Build 19: v0.6.18 Rotation + TTS + Fixes
#   - Fix Rotation: Speichern funktioniert (parseInt-Bug bei Person-ID gefixt)
#   - Gespeicherte Rotationen: Anzeige, Bearbeiten, Loeschen im Schichtdienst-Tab
#   - Kalender-Eintraege einstellbar: Toggle "Im Kalender anzeigen" pro Rotation
#   - TTS Fix: Alle TTS-Entities durchprobieren, HA Cloud (de-DE), cloud_say Fallback
#   - Domain-Separator: Sichtbarer Trennstrich zwischen Steuerung/Sensoren
#   - Zeitprofile: Person-Dropdown fix (users.id statt persons.entity_id)
#
# Build 18: v0.6.17 Standby-Geraeteauswahl
#   - Standby-Ueberwachung: Sensor-Dropdown statt Textfeld
#   - Laedt Power-Sensoren (W/kW) aus HA via discover-sensors API
#
# Build 17: v0.6.16 UI-Fixes
#   - Fix Schichttypen: Person-Dropdown (users→persons), Edit-Modal, Date-Grid
#   - Fix Geraete: Tabelle fixed-layout, Entity-ID truncate, overflow-x scroll
#   - Fix Domains: Trennstrich zwischen Steuerung/Sensoren, Custom-Domain Info
#   - Fix Dashboard: stat-card bg-tertiary (einheitlich mit Domains/Lernfortschritt)
#
# Build 16: v0.6.15 Refactoring
#   - ml/ Verzeichnis entfernt — alle Imports auf Root-Module umgestellt
#   - Root automation_engine.py + pattern_engine.py werden jetzt direkt verwendet
#   - Fixes greifen jetzt: Sensor-Anomalie-Skip, Presence-Dedup, Confidence-Decay
#
# Build 15: v0.6.14 UI + Bugfix
#   - Fix Domains: Groessere Kacheln, bessere Lesbarkeit (300px min, Font 15px)
#   - Fix Wochenbericht: bg-tertiary statt bg-main (einheitliche Kartenfarbe)
#   - Fix Systemstatus: Neues Card-Design mit Icons (wie Lernfortschritt)
#   - Fix Anwesenheit: Backend-Dedup verhindert Log-Spam bei bereits aktivem Modus
#
# Build 14: v0.6.13 Bugfix
#   - Fix Anwesenheit: Infinite Loop bei Auto-Select (useRef Guard)
#
# Build 13: v0.6.12 Bugfix
#   - Fix Push: notify.* Prefix aus Service-Name entfernt (doppeltes notify)
#   - Fix TTS: Kein Retry bei Fehler, direkter _api_request statt call_service
#   - Fix TTS: Besseres Logging (Speaker, TTS-Entity, Language)
#
# Build 12: v0.6.11 Bugfix
#   - Fix TTS: tts.speak mit entity_id (TTS-Entity Discovery), kein Retry bei 4xx
#   - Fix Notification: test-channel POST + channel PUT Routen hinzugefuegt
#   - Fix DomainsPage: devices Variable in useApp() Destrukturierung
#   - Fix Anwesenheit: Modus-Deduplizierung + Auto-Select
#   - Fix Zeiteingabe: type="text" statt type="time" (Safari-Kompatibilitaet)
#   - Fix Geraete: Responsive Layout (Mobile Cards / Desktop Tabelle)
#   - Fix Ladescreen: MindHome-Logo statt Gehirn-Icon
#   - Fix Design: Fehlende CSS-Variablen (--bg-hover, --accent-primary-alpha)
#   - Fix SplashScreen: CSS-Variablen statt hardcoded Farben
#   - Fix Bibliotheken: Lokal gebundelt mit CDN-Fallback
#   - Fix Mojibake: Umlaute in Fehlermeldungen entfernt
#
# Build 5: v0.6.4 Stabilisierung
#   - Mustererkennung: Confidence Decay 1x/Tag, Cap 10%/Tag, Sequenz-Formel, Korrelation erweitert
#   - Mustererkennung: Motion-Debounce, Merge-Zeitfenster, Time-Parsing, Context-Tags Update
#   - Anwesenheit: Duplikat-Check, Fallback-Mode, notify_on_enter/leave, DB-Init, Debounce
#   - Push Notifications: push_channel aus Settings, Fallback persistent_notification
#   - TTS: media_player_entity_id, Language-Parameter, Speaker-Auswahl, Fehler-Feedback
#   - Anomalie: Sensor-Domain ausgeschlossen, Domain-Exceptions, Device-Whitelist, LRU-Cache
#   - Stuck-Device: cover + climate Erkennung
#   - Security: Path-Traversal-Schutz, Hot-Update hinter Debug, CORS, Security-Headers
#   - Backend: bare except entfernt, request.json Guards, generische Error-Messages
#   - Frontend: Domain-Redesign, CSS-Variablen, Geraete-Dropdowns, Raeume responsive
#   - Frontend: Gast-Rolle, Backup-Refresh, Schichtdienst-Fixes, Kalender-Monatsansicht
#   - Frontend: Anwesenheit Fehlerbehandlung, Input-Validierung, Loesch-Bestaetigungen
#
# Build 4: v0.6.3 Bugfix
#   - Fix ReferenceError: isAdmin nicht verfuegbar in RoomsPage
#   - Settings-Refresh: Vacation/Debug/Mute/Anomaly-Pause sofort sichtbar
#   - Hardcoded Version "0.5.0" durch zentrale VERSION ersetzt
#   - Frontend Version-Fallbacks entfernt
#
# Build 3: v0.6.2 Bugfix (Issue #3)
#   - Fix AttributeError in /api/backup/export (NotificationSetting, NotificationChannel)
#   - Fix AttributeError in /api/backup/export (OfflineActionQueue)
#   - Fix AttributeError in /api/export/automations (ActionLog)
#   - Enum-Serialisierung fuer NotificationType/NotificationPriority
#
# Build 2: v0.6.1 Hotfix
#   - PatternSettings (konfigurierbare Schwellenwerte)
#   - Unified Confidence Decay (Grace 2d, 1%/w, 5%/d)
#   - Event-Deduplizierung (#15)
#   - Muster-Duplikat-Erkennung verbessert (#4)
#   - Mojibake-Fixes in allen Dateien (#31)
#   - CustomSelect ersetzt native <select> (#9)
#   - Szenen-Detailansicht (#12)
#   - Geraete Mobile Card Layout (#23)
#   - Presence Auto-Detect + Manual-Override (#13/#28)
#   - DataCollection.created_at Fix
#   - Query.get() -> Session.get() Migration
#
# Build 1: Phase 3.5 - Kompletter Umbau
#   - Bugs gefixt (duplizierte Methoden, Encoding, Session-Leaks, migration_ok)
#   - DB Context Manager eingefuehrt
#   - Backend in Flask Blueprints aufgeteilt
#   - Frontend in React Komponenten aufgeteilt
#   - Event-Bus + Task-Scheduler erweitert
#   - Zentrale Versionsverwaltung eingefuehrt


def version_string():
    """Return formatted version string."""
    return f"v{VERSION} (Build {BUILD})"


def version_info():
    """Return full version info dict."""
    return {
        "version": VERSION,
        "build": BUILD,
        "build_date": BUILD_DATE,
        "codename": CODENAME,
        "full": version_string(),
    }
