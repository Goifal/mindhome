# Changelog

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
