# MindHome - version.py | Zentrale Versionsverwaltung
"""
MindHome Version Info
Alle Dateien importieren von hier - Version nur an EINER Stelle ändern.
"""

VERSION = "0.6.45"
BUILD = 46
BUILD_DATE = "2026-02-13"
CODENAME = "Phase 3.5 - Kalender & Presence"

# Changelog
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
