# MindHome - version.py | Zentrale Versionsverwaltung
"""
MindHome Version Info
Alle Dateien importieren von hier - Version nur an EINER Stelle ändern.
"""

VERSION = "0.6.12"
BUILD = 13
BUILD_DATE = "2026-02-11"
CODENAME = "Phase 3.5 - Bugfix"

# Changelog
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
