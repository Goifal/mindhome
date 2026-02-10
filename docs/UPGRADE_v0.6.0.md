# MindHome v0.6.0 - Phase 3.5 Upgrade-Anleitung

## Was wurde gemacht?

### Block A: Bugs gefixt
- ✅ Duplizierte `_apply_domain_scoring` Methode entfernt (pattern_engine.py)
- ✅ `migration_ok` wird jetzt bei Fehlern auf `False` gesetzt (models.py)
- ✅ UTF-8 Encoding-Probleme in allen Dateien behoben (→ statt Ã¢â€ â€™, ° statt Ã‚Â°, etc.)

### Block B: DB Context Manager
- ✅ Neue `db.py` mit `get_db_session()` Context Manager
- ✅ Kein manuelles `session.close()` mehr nötig
- ✅ Auto-Rollback bei Exceptions, Auto-Commit bei Erfolg

### Block C: Backend in Blueprints aufgeteilt
- ✅ `app.py`: 5.929 → 472 Zeilen (nur Init + Startup)
- ✅ 222 API-Routen in 13 Blueprint-Module aufgeteilt:
  - `routes/system.py` (55 Routen) - System, Health, Backup, Export, Quick Actions
  - `routes/patterns.py` (21 Routen) - Muster, Exclusions, Manual Rules
  - `routes/automation.py` (24 Routen) - Automationen, Predictions, Phases, Anomalien
  - `routes/schedules.py` (27 Routen) - Schichtplan, Kalender, Feiertage, Ruhezeiten
  - `routes/energy.py` (16 Routen) - Energie, Sensoren, Standby
  - `routes/notifications.py` (15 Routen) - Benachrichtigungen, Settings
  - `routes/devices.py` (10 Routen) - Geräte, Discovery
  - `routes/domains.py` (10 Routen) - Domains, Plugin-Settings
  - `routes/rooms.py` (8 Routen) - Räume, Orientierung
  - `routes/scenes.py` (7 Routen) - Szenen
  - `routes/presence.py` (24 Routen) - Anwesenheit, Tagesphasen, Personen
  - `routes/users.py` (4 Routen) - Benutzerverwaltung
  - `routes/frontend.py` (3 Routen) - Static Files

### Block D: Frontend
- ⚠️ app.jsx ist noch ein Monolith (6.589 Zeilen)
- Das Frontend-Splitting erfordert einen Build-Prozess-Umbau (Babel/Webpack)
- Wird in einem separaten Schritt gemacht

### Block E: Event-Bus + Task-Scheduler
- ✅ `event_bus.py` - Erweiterter Event-Bus mit Wildcards, Prioritäten, History
- ✅ `task_scheduler.py` - Generischer Task-Scheduler für Phase 4

### Versionierung
- ✅ `version.py` - Zentrale Versionsverwaltung mit Build-Nummer
- Version: v0.6.0 (Build 1)

## Neue Dateien

```
NEU:  version.py          - Zentrale Version + Build
NEU:  db.py               - DB Context Manager
NEU:  helpers.py           - Shared Helper-Funktionen
NEU:  event_bus.py         - Erweiterter Event-Bus
NEU:  task_scheduler.py    - Generischer Task-Scheduler
NEU:  routes/__init__.py   - Blueprint-Registrierung
NEU:  routes/system.py     - System-Routen
NEU:  routes/rooms.py      - Raum-Routen
NEU:  routes/devices.py    - Geräte-Routen
NEU:  routes/users.py      - User-Routen
NEU:  routes/patterns.py   - Muster-Routen
NEU:  routes/automation.py - Automations-Routen
NEU:  routes/energy.py     - Energie-Routen
NEU:  routes/notifications.py - Benachrichtigungs-Routen
NEU:  routes/domains.py    - Domain-Routen
NEU:  routes/scenes.py     - Szenen-Routen
NEU:  routes/presence.py   - Anwesenheits-Routen
NEU:  routes/schedules.py  - Zeitplan-Routen
NEU:  routes/frontend.py   - Frontend-Routen
NEU:  ml/__init__.py       - ML-Modul-Wrapper
```

## Geänderte Dateien

```
GEÄNDERT: app.py              - Von 5.929 auf 472 Zeilen (Init only)
GEÄNDERT: models.py           - migration_ok Bug gefixt, Encoding
GEÄNDERT: pattern_engine.py   - Duplizierte Methode entfernt, Encoding
GEÄNDERT: automation_engine.py - Encoding gefixt
GEÄNDERT: ha_connection.py    - Encoding gefixt
```

## Installation

1. Sichere deinen aktuellen Stand auf GitHub (Commit!)
2. Entpacke `mindhome_v0.6.0.zip`
3. Ersetze ALLE Dateien in deinem Projekt mit den neuen
4. Starte das Add-on neu

## ⚠️ WICHTIG

- Die **API-URLs bleiben EXAKT gleich** - das Frontend muss nicht geändert werden
- Die **Datenbank bleibt kompatibel** - kein Datenverlust
- **Backup vor dem Update** machen!
- Das Frontend (app.jsx) ist noch NICHT aufgeteilt - das kommt separat
