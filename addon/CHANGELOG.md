# Changelog

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
