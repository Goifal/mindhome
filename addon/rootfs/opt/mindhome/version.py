# MindHome - version.py | Zentrale Versionsverwaltung
"""
MindHome Version Info
Alle Dateien importieren von hier - Version nur an EINER Stelle ändern.
"""

VERSION = "0.6.0"
BUILD = 1
BUILD_DATE = "2026-02-10"
CODENAME = "Phase 3.5 - Stabilisierung & Refactoring"

# Changelog
# Build 1: Phase 3.5 - Kompletter Umbau
#   - Bugs gefixt (duplizierte Methoden, Encoding, Session-Leaks, migration_ok)
#   - DB Context Manager eingeführt
#   - Backend in Flask Blueprints aufgeteilt
#   - Frontend in React Komponenten aufgeteilt
#   - Event-Bus + Task-Scheduler erweitert
#   - Zentrale Versionsverwaltung eingeführt


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
