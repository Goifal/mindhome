# MindHome - version.py | Zentrale Versionsverwaltung
"""
MindHome Version Info
Alle Dateien importieren von hier - Version nur an EINER Stelle ändern.
"""

VERSION = "0.6.2"
BUILD = 3
BUILD_DATE = "2026-02-10"
CODENAME = "Phase 3.5 - Bugfix"

# Changelog
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
