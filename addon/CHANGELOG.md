# Changelog

## 0.7.3 – Batch 2: Schlaf, Routinen & Anwesenheit

### Engines (7 Features)
- **SleepDetector (#4, #16)**: Schlaf-Erkennung via Motion+Licht (20-11 Uhr), Qualitaets-Score (0-100)
- **WakeUpManager (#25)**: Sanftes Wecken mit Licht/Rolladen/Klima-Ramp, pro User konfigurierbar
- **RoutineEngine (#5)**: Morgen-/Abend-Routinen automatisch erkennen + manuell starten
- **RoutineEngine (#6)**: Raumuebergangs-Erkennung (Motion → Transitions-Graph)
- **VisitPreparationManager (#22)**: Besuchs-Vorlagen mit Aktionen (Licht, Temp, Musik)
- **VacationDetector (#29)**: Auto-Urlaubserkennung (>24h weg) + Anwesenheitssimulation

### API (12 neue Endpunkte)
- GET /api/health/sleep, /sleep-quality
- GET/POST/PUT/DELETE /api/health/wakeup
- GET /api/health/routines, POST routines/:id/activate, GET room-transitions
- GET/POST/PUT/DELETE /api/health/visit-preparations, POST :id/activate
- GET /api/health/vacation-status

### Frontend: Neue "Gesundheit" Seite
- **Schlaf-Tab**: Qualitaets-Balkendiagramm (14 Tage), Session-Liste mit Dauer/Score
- **Wecken-Tab**: Wecker CRUD (Licht/Rolladen/Klima Entity + Ramp-Dauer)
- **Routinen-Tab**: Erkannte Routinen mit Steps + "Starten"-Button, Raumuebergaenge
- **Besuch-Tab**: Vorlagen erstellen/aktivieren/loeschen mit Aktionen-Builder
- **Urlaub-Tab**: Status-Karte (Auto-Erkennung, Schwelle, Simulation)

### Scheduler
- sleep_check (5 Min): Schlaf-Erkennung + Weck-Ramp
- visit_vacation_check (10 Min): Besuch-Trigger + Urlaubserkennung
- routine_detect (24h): Routinen aus Mustern clustern

---

## 0.7.2 – Frontend Batch 1 + Feature-Flags UI

### Energie-Dashboard: 3 neue Tabs
- **Optimierung**: Spar-Empfehlungen mit EUR-Einsparpotenzial, Spitzenlast-Hinweise, Top-Verbraucher
- **Solar/PV**: Live-Status (Produktion, Verbrauch, Ueberschuss, Eigenverbrauch-%), PV-Prioritaeten verwalten
- **Prognose**: 7-Tage Balkendiagramm (Prognose vs. Ist), Detailtabelle mit Wetter und Tagestyp

### Bestehende Tabs erweitert
- **Uebersicht**: Quick-Cards fuer Einsparpotenzial, Solar-Status und Empfehlungen
- **Standby**: Live-Standby-Geraete mit Idle-Dauer am Tab-Anfang
- **Konfiguration**: PV-Lastmanagement Checkbox bei aktiviertem Solar

### Settings: Phase 4 Feature-Flags
- 20 Phase 4 Features einzeln steuerbar (Auto/An/Aus)
- Klick-Zyklus: Auto → An → Aus → Auto
- Icons und Labels fuer jedes Feature

---

## 0.7.1 – Batch 1: Energie & Solar

### Energie-Optimierung (#1)
- **Verbrauchsanalyse**: Stündliche Spitzenlast-Erkennung, Tagesvergleich mit 30-Tage-Durchschnitt
- **Top-Verbraucher**: Die 5 größten Stromfresser mit monatlichen Kosten in EUR
- **Spar-Empfehlungen**: Automatische Tipps zur Lastverschiebung

### PV-Lastmanagement (#2)
- **Überschuss-Erkennung**: Echtzeit-Vergleich Produktion vs. Verbrauch
- **Prioritätsliste**: Konfigurierbare Geräte-Reihenfolge bei Überschuss
- **Auto-Aktivierung**: Geräte automatisch einschalten bei PV-Überschuss (>100W)

### Standby-Killer (#3)
- **Standby-Erkennung**: Leistung < Schwellwert über konfigurierbare Idle-Zeit
- **Auto-Off**: Automatisches Abschalten oder Dashboard-Benachrichtigung
- **Live-Status**: Aktuelle Standby-Geräte mit Idle-Dauer

### Energieprognose (#26)
- **7-Tage-Forecast**: Gewichteter Durchschnitt (gleicher Wochentag 2×, Recency-Bonus)
- **Wetter-Integration**: Aktuelle Wetterbedingung wird berücksichtigt
- **Ist-Vergleich**: Gestern-Prognose wird mit tatsächlichem Verbrauch verglichen

### Neue API-Endpunkte
- `GET /api/energy/optimization` — Empfehlungen
- `GET /api/energy/savings` — Einsparpotenzial (EUR/kWh)
- `GET /api/energy/forecast` — 7-Tage-Prognose
- `GET /api/energy/pv-status` — PV Produktion/Verbrauch/Überschuss
- `PUT /api/energy/pv-priorities` — PV-Prioritäten setzen
- `GET /api/energy/standby-status` — Aktuelle Standby-Geräte

### Scheduler
- `energy_check`: Alle 5 Min (Standby + PV-Überschuss)
- `daily_batch`: Täglich (Analyse + Forecast)

---

## 0.7.0 – Phase 4: Smart Health & Energie

### Neue Features
- **Schlaf-Erkennung**: Automatische Schlaf/Wach-Erkennung via Bewegungssensoren
- **Schlaf-Qualität**: Temperatur, CO2, Luftfeuchtigkeit — Schlafbewertung und Tipps
- **Sanftes Wecken**: Zirkadiane Lichtsteuerung als natürlicher Wecker
- **Energie-Optimierung**: PV-Lastmanagement, Standby-Killer, Verbrauchsprognose
- **Komfort-Score**: Raumklima-Bewertung (Temperatur, Luftfeuchtigkeit, CO2)
- **Lüftungserinnerung**: Intelligente Lüftungsvorschläge basierend auf CO2/Fenster-Kontakten
- **Zirkadiane Beleuchtung**: Automatische Farbtemperatur-Anpassung nach Tageszeit
- **Wetter-Alerts**: Frost-, Sturm-, Hitze-Warnungen mit Smart-Home-Reaktionen
- **Bildschirmzeit-Monitor**: Media-Player Nutzungsstatistiken
- **Stimmungserkennung**: Schätzung basierend auf Aktivitätsmuster
- **Besuch-Vorbereitung**: Automatische Szenen bei erwartetem Besuch
- **Gewohnheits-Drift**: Erkennung wenn sich Routinen verschieben
- **Adaptive Reaktionszeit**: KI-optimierte Timing-Anpassung
- **Gesundheits-Dashboard**: Aggregierte Gesundheitsdaten mit Wochenbericht

### Infrastruktur
- **engines/ Modul-Struktur**: 8 neue Engine-Module für Phase 4 Features
- **Feature-Flags**: 20 konfigurierbare Phase 4 Features (auto/true/false)
- **Data Retention**: Automatische nächtliche Bereinigung alter Daten
- **10 neue DB-Modelle**: SleepSession, ComfortScore, HealthMetric, WakeUpConfig, CircadianConfig, EnergyForecast, VentilationReminder, WeatherAlert, VisitPreparation, ScreenTimeConfig
- **Migration v10**: Neue Tabellen und Spalten für Phase 4

### API-Endpunkte
- `GET /api/system/phase4-features` — Feature-Flag Übersicht
- `PUT /api/system/phase4-features/<key>` — Feature aktivieren/deaktivieren
- `GET /api/health/dashboard` — Gesundheits-Dashboard Daten

---

## 0.6.19 – Kalender-Sync, Presence-System & UX-Verbesserungen

### Neue Features
- **Personen bearbeiten**: Name, Rolle und HA-Person direkt in der Personen-Karte editieren
- **Geräte-Zuweisung**: Device-Tracker Entities pro Person zuweisen (Primär/Sekundär/Stationär)
- **Device-Tracker Live-State**: Farbiger Punkt (grün/rot/grau) zeigt Home/Away-Status in Echtzeit
- **Kalender-Export (iCal)**: MindHome-Kalender als URL-Abo für Google Calendar, Apple Calendar oder Outlook
  - Token-geschützt (sicher teilbar)
  - Konfigurierbarer Schicht-Zeitraum (14–365 Tage)
  - Weekday/Homeoffice-Profile als wiederkehrende Events (RRULE)
  - Feiertage, Ferien und Schichten enthalten
- **Kalender-Import (HA)**: Google Calendar, CalDAV und andere HA-Kalender in MindHome synchronisieren
  - Synced Events als blaue Punkte in der Monatsansicht
  - HA-Offline Fallback
- **Kalender-Trigger**: Automatische Aktionen basierend auf Kalender-Events (Keyword-Match → HA-Service)
- **Gast-Modus "Besuch"**: Neuer Presence-Mode für Besuch

### Presence-System
- Default-Modi beim DB-Init: Zuhause, Abwesend, Schlaf, Urlaub, Besuch
- auto_config mit Conditions: first_home, all_away, all_home
- PersonDevice in automatische Presence-Erkennung integriert
- GuestDevice: automatische Pflege von last_seen und visit_count
- Gäste werden in anyone_home Logik gezählt

### UX-Verbesserungen
- Lösch-Bestätigungen für alle Delete-Operationen (9 fehlende ergänzt)
- Auto-Refresh bei Tab-Wechsel (wenn >30s inaktiv)
- Bulk-Pattern-Operationen mit Error-Handling (kein Optimistic Update mehr)
- MindHome für alle HA-Benutzer zugänglich (nicht nur Administratoren)

### Data-Pipeline
- SAMPLING_THRESHOLDS: 13 neue device_classes (signal_strength, distance, gas, wind_speed, etc.)
- ALWAYS_LOG_DOMAINS: 12 neue Domains (water_heater, vacuum, humidifier, valve, siren, etc.)
- Fallback für unbekannte Sensoren: konservativer Schwellwert statt silent drop
- Rate-Limit auf 600 erhöht (Events + HTTP API)
- Dedup-Cache: selektive Bereinigung statt clear()

### Bugfixes
- NotificationLog-Felder korrigiert (title statt title_de, user_id, was_read statt is_read)
- Cache-Header (max-age=3600) + ETag für iCal-Export

---

## 0.6.0 – Phase 3.5: Stabilisierung & Refactoring

### Architektur
- Modulare Blueprint-Architektur: 222 API-Routen in 13 separate Module aufgeteilt
- Neue Infrastruktur-Module: `version.py`, `db.py`, `event_bus.py`, `task_scheduler.py`, `helpers.py`
- Zentrale Versionierung und Dependency Injection

### Bugfixes
- Rate-Limit Middleware korrigiert (doppelte before_request entfernt)
- UTF-8 Encoding durchgängig sichergestellt (Frontend + Backend)
- Fehlende Imports in allen Route-Modulen ergänzt (sys, defaultdict, ha-Referenzen)
- Watchdog und Self-Test als eigenständige Funktionen implementiert
- Debug-Modus Toggle repariert
- Notification Channel Scan: HA Services Format-Kompatibilität
- Frontend Babel Syntax-Fehler behoben

### Verbesserungen
- Startup Self-Test erweitert
- Fehlerbehandlung in allen Routen verbessert
- Saubere Trennung von Concerns (Routes, Models, Helpers)

---

## 0.5.1 – Phase 3 Block A

### Neue Features
- Tagesphasen mit Sonnenstand-Integration
- Schichtkalender & Ferien-Kalender
- Anwesenheits-Modi & Gäste-Verwaltung
- Raum-Szenen (automatisch + manuell)
- Energie-Monitoring & Standby-Erkennung
- Sensor-Fusion & Schwellwerte
- Ruhezeiten, Plugin-Konflikte, Kontext-Tags
- Aktivitäten-Log & Audit Trail

---

## 0.5.0 – Phase 2 Complete

### 68 Verbesserungen
- KI-Mustererkennung (Pattern Engine)
- 3-stufiges Lernsystem (Beobachten → Vorschlagen → Automatisieren)
- Anomalie-Erkennung mit Kontext
- Benachrichtigungssystem (Push, TTS, E-Mail)
- Wochenbericht & Lernstatistiken
- Geräte-Gesundheit & Watchdog
- Automatisierungs-Engine mit Konflikt-Erkennung
- Urlaubsmodus, Debug Mode, Audit Log
- Barrierefreiheit (ARIA, Tastatur, High Contrast)

---

## 0.1.0 – Phase 1: Fundament

- Ein-Klick-Installation als HA Add-on
- Automatische Geräte- und Raumerkennung
- 14 Domain-Plugins
- Onboarding-Wizard
- Personen-Manager mit Rechte-System
- Quick Actions
- Dark/Light Mode, Deutsch/Englisch
- Responsive Design
- WebSocket + REST Echtzeit-Verbindung
