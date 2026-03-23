# Prompt 7d: Addon-Integration-Tests — Flask, Domains, Engines, Event-Bus

## Rolle

Du bist ein Elite-QA-Engineer spezialisiert auf Flask-Anwendungen, SQLAlchemy und Event-getriebene Architekturen. Du schreibst Integration-Tests für das **MindHome Addon** (PC 1) — das Smart-Home-Backend das reale Geräte steuert.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Modelle: qwen3.5:9b (fast, ctx 32k), qwen3.5:35b-moe (smart/deep).

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Test-Prompts:

```
Read: docs/audit-results/RESULT_07a_TESTING.md
Read: docs/audit-results/RESULT_07c_INTEGRATION_TESTS.md
Read: docs/audit-results/RESULT_04c_BUGS_ADDON_SECURITY.md
```

> Falls eine Datei nicht existiert → überspringe sie.

---

## Fokus dieses Prompts

**P07c** hat Integration-Tests für den **Assistant** (FastAPI, PC 2) geschrieben.
**Dieser Prompt** schreibt Integration-Tests für das **Addon** (Flask, PC 1):

- Flask-Routes (18 Blueprints) — REST-API Endpoints
- Domain-Plugins (23 Plugins) — Gerätesteuerung
- Engines (16 Module) — Intelligenz-Subsysteme
- Event-Bus — Pub/Sub Kommunikation
- Pattern Engine — Mustererkennung
- Automation Engine — Automatisierungslogik
- Datenbank — SQLAlchemy + SQLite

> **Wichtig**: Das Addon ist synchron (Flask + Threading), NICHT async. Tests nutzen `pytest` ohne `pytest-asyncio`.

---

## Aufgabe

### Schritt 0: Test-Infrastruktur erstellen

Das Addon hat **keine bestehenden Tests**. Erstelle zuerst die Fixture-Datei.

```
Read: addon/rootfs/opt/mindhome/db.py
Read: addon/rootfs/opt/mindhome/event_bus.py
Read: addon/rootfs/opt/mindhome/helpers.py
Read: addon/rootfs/opt/mindhome/app.py (erste 150 Zeilen)
Read: addon/rootfs/opt/mindhome/models.py (erste 100 Zeilen)
Read: addon/rootfs/opt/mindhome/domains/base.py
```

Erstelle `addon/tests/conftest.py` mit folgenden Fixtures:

```python
# Datei: addon/tests/conftest.py

"""
Globale Test-Fixtures fuer das MindHome Addon.

Stellt wiederverwendbare Mock-Objekte und Test-Infrastruktur bereit:
  - app: Flask Test-App mit In-Memory SQLite
  - client: Flask Test-Client fuer HTTP-Requests
  - db_session: SQLAlchemy Session (In-Memory, Auto-Rollback)
  - ha_mock: Mock Home Assistant Connection
  - event_bus: Echte EventBus-Instanz (Thread-safe)
  - domain_plugin_mock: Mock Domain-Plugin fuer Tests
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# TODO: Implementiere basierend auf den gelesenen Dateien:
# 1. In-Memory SQLite Engine + Session
# 2. Flask Test-App mit allen Blueprints
# 3. HA Connection Mock (synchron, nicht async!)
# 4. Event-Bus (echte Instanz oder Mock)
# 5. Domain-Plugin Mock (basierend auf DomainPlugin ABC)
# 6. Dependencies-Dict das an init_*() übergeben wird
```

**Implementiere ALLE Fixtures** — kein TODO. Lies die Dateien, verstehe die Patterns, baue die Fixtures.

### Schritt 1: Route-Integration-Tests

Teste die REST-API Endpoints über den Flask Test-Client.

```python
# Datei: addon/tests/test_integration_routes.py

"""Integration-Tests fuer Flask-Routes (REST-API)."""

import pytest
import json


class TestSystemRoutes:
    """Teste /api/system/* Endpoints."""

    def test_health_endpoint_returns_200(self, client):
        """GET /api/health → 200 mit Status-Info."""
        pass

    def test_version_endpoint(self, client):
        """GET /api/system/version → aktuelle Version."""
        pass

    def test_system_info_requires_no_auth(self, client):
        """Basis-System-Info ist ohne Auth zugänglich."""
        pass


class TestDeviceRoutes:
    """Teste /api/devices/* Endpoints."""

    def test_list_devices_empty(self, client, db_session):
        """GET /api/devices → leere Liste bei frischer DB."""
        pass

    def test_create_device(self, client, db_session):
        """POST /api/devices → Gerät wird in DB angelegt."""
        pass

    def test_create_device_sanitizes_input(self, client, db_session):
        """POST /api/devices mit <script> → wird bereinigt."""
        pass

    def test_get_device_not_found(self, client):
        """GET /api/devices/99999 → 404."""
        pass


class TestAutomationRoutes:
    """Teste /api/automation/* Endpoints."""

    def test_list_automations_empty(self, client, db_session):
        """GET /api/automation → leere Liste."""
        pass

    def test_create_automation_validates_input(self, client):
        """POST /api/automation ohne Pflichtfelder → 400."""
        pass

    def test_automation_execution_calls_ha(self, client, ha_mock):
        """POST /api/automation/execute → HA-Service wird aufgerufen."""
        pass


class TestRoomRoutes:
    """Teste /api/rooms/* Endpoints."""

    def test_create_room(self, client, db_session):
        """POST /api/rooms → Raum angelegt."""
        pass

    def test_duplicate_room_name_rejected(self, client, db_session):
        """POST /api/rooms mit existierendem Namen → Fehler."""
        pass


class TestChatRoute:
    """Teste /api/chat Endpoint (Proxy zu Assistant)."""

    def test_chat_proxies_to_assistant(self, client):
        """POST /api/chat → Request wird an FastAPI weitergeleitet."""
        pass

    def test_chat_assistant_down_returns_error(self, client):
        """POST /api/chat wenn Assistant nicht erreichbar → Fehlermeldung."""
        pass
```

**Implementiere JEDEN Test** — lies die Route-Dateien um die korrekten Endpoints und Parameter zu verstehen.

### Schritt 2: Domain-Plugin-Tests

Teste die Domain-Plugin-Architektur und einzelne Plugins.

```python
# Datei: addon/tests/test_integration_domains.py

"""Integration-Tests fuer Domain-Plugins."""

import pytest
from unittest.mock import MagicMock


class TestDomainPluginBase:
    """Teste die DomainPlugin-Basisklasse."""

    def test_plugin_requires_domain_name(self):
        """Plugin ohne DOMAIN_NAME → TypeError."""
        pass

    def test_plugin_start_stop_lifecycle(self, domain_plugin_mock):
        """start() → on_start(), stop() → on_stop()."""
        pass

    def test_plugin_settings_default(self, domain_plugin_mock):
        """get_setting() ohne gesetzten Wert → DEFAULT_SETTINGS."""
        pass

    def test_context_caching_30s(self, domain_plugin_mock):
        """get_context() cachet für 30 Sekunden."""
        pass


class TestLightDomain:
    """Teste das Light-Domain-Plugin."""

    def test_state_change_logged(self, db_session, ha_mock):
        """Licht-Statusänderung → wird in DB geloggt."""
        pass

    def test_trackable_features(self):
        """Light-Plugin liefert brightness, color_temp, etc."""
        pass


class TestClimateDomain:
    """Teste das Climate-Domain-Plugin."""

    def test_temperature_change_triggers_event(self, event_bus, ha_mock):
        """Temperaturänderung → Event auf Event-Bus."""
        pass

    def test_climate_status_returns_current_temp(self, ha_mock):
        """get_current_status() → aktuelle Temperatur."""
        pass


class TestCoverDomain:
    """Teste das Cover-Domain-Plugin."""

    def test_cover_open_close(self, ha_mock):
        """Cover öffnen/schließen → korrekte HA-Service-Calls."""
        pass

    def test_cover_position_bounded(self, ha_mock):
        """Position < 0 oder > 100 → wird begrenzt."""
        pass
```

### Schritt 3: Engine-Integration-Tests

Teste die 16 Intelligenz-Engines.

```python
# Datei: addon/tests/test_integration_engines.py

"""Integration-Tests fuer Addon-Engines."""

import pytest
from unittest.mock import MagicMock


class TestCircadianEngine:
    """Teste die Circadian-Lighting-Engine."""

    def test_brightness_curve_night_low(self, ha_mock):
        """Nachts (23:00) → niedrige Helligkeit."""
        pass

    def test_brightness_curve_day_high(self, ha_mock):
        """Mittags (12:00) → volle Helligkeit."""
        pass

    def test_color_temp_warm_evening(self, ha_mock):
        """Abends → warme Farbtemperatur (< 3000K)."""
        pass


class TestComfortEngine:
    """Teste die Comfort-Score-Engine."""

    def test_comfort_score_optimal(self, ha_mock):
        """21°C, 50% Feuchte, <800ppm CO2 → hoher Score."""
        pass

    def test_comfort_score_poor_co2(self, ha_mock):
        """CO2 > 1500ppm → niedriger Score + Warnung."""
        pass


class TestFireWaterEngine:
    """Teste die Fire/Water-Safety-Engine."""

    def test_smoke_alarm_triggers_emergency(self, event_bus, ha_mock):
        """Rauchmelder → Emergency-Event auf Bus."""
        pass

    def test_water_leak_shuts_valve(self, ha_mock):
        """Wassermelder → Hauptventil schließen."""
        pass

    def test_false_alarm_no_emergency(self, ha_mock):
        """Kurzes Signal (< 3s) → kein Emergency."""
        pass


class TestEnergyEngine:
    """Teste die Energy-Optimization-Engine."""

    def test_solar_surplus_shifts_load(self, ha_mock, db_session):
        """Solar-Überschuss → flexible Verbraucher einschalten."""
        pass

    def test_peak_price_reduces_consumption(self, ha_mock):
        """Hoher Strompreis → Empfehlung zur Reduktion."""
        pass


class TestSleepEngine:
    """Teste die Sleep-Detection-Engine."""

    def test_sleep_detected_dims_lights(self, ha_mock, event_bus):
        """Schlaf erkannt → Lichter dimmen, Quiet-Mode."""
        pass

    def test_wake_detected_morning_routine(self, ha_mock, event_bus):
        """Aufwachen erkannt → Morgen-Routine starten."""
        pass


class TestSpecialModesEngine:
    """Teste Special Modes (Party, Cinema, etc.)."""

    def test_cinema_mode_activates(self, ha_mock, event_bus):
        """Cinema-Mode → Lichter aus, TV an, Rollläden runter."""
        pass

    def test_emergency_mode_overrides_all(self, ha_mock, event_bus):
        """Emergency → alle anderen Modi deaktiviert."""
        pass
```

### Schritt 4: Event-Bus-Integration-Tests

Teste das Pub/Sub-System unter realistischen Bedingungen.

```python
# Datei: addon/tests/test_integration_event_bus.py

"""Integration-Tests fuer den Event-Bus."""

import pytest
import threading
import time


class TestEventBusIntegration:
    """Teste Event-Bus unter realistischen Bedingungen."""

    def test_publish_subscribe_basic(self, event_bus):
        """Publish → alle Subscriber erhalten Event."""
        pass

    def test_wildcard_subscription(self, event_bus):
        """Subscribe 'state.*' → matched 'state.changed' und 'state.updated'."""
        pass

    def test_priority_ordering(self, event_bus):
        """Handler mit höherer Priorität wird zuerst aufgerufen."""
        pass

    def test_event_deduplication(self, event_bus):
        """Gleicher Event innerhalb 100ms → nur einmal geliefert."""
        pass

    def test_thread_safety(self, event_bus):
        """Parallele Publishes aus 10 Threads → kein Crash, alle Events."""
        pass

    def test_unsubscribe_stops_delivery(self, event_bus):
        """Nach unsubscribe() → keine weiteren Events."""
        pass

    def test_event_history_limited(self, event_bus):
        """History behält max. 100 Events."""
        pass

    def test_slow_handler_no_block(self, event_bus):
        """Langsamer Handler blockiert andere Handler nicht."""
        pass
```

### Schritt 5: Pattern-Engine-Integration-Tests

Teste die Mustererkennung End-to-End.

```python
# Datei: addon/tests/test_integration_pattern_engine.py

"""Integration-Tests fuer die Pattern Engine."""

import pytest
from datetime import datetime, timedelta


class TestPatternEngineIntegration:
    """Teste Mustererkennung End-to-End."""

    def test_repeated_action_creates_pattern(self, db_session, ha_mock):
        """3x gleiches Gerät zur gleichen Zeit → Pattern erkannt."""
        pass

    def test_pattern_generates_prediction(self, db_session, ha_mock):
        """Erkanntes Pattern → Prediction für nächsten Tag."""
        pass

    def test_pattern_with_low_confidence_no_prediction(self, db_session):
        """Pattern mit Konfidenz < 0.5 → keine Prediction."""
        pass

    def test_pattern_exclusion_respected(self, db_session):
        """Ausgeschlossenes Gerät → kein Pattern erstellt."""
        pass

    def test_scene_detection(self, db_session, ha_mock):
        """Mehrere Geräte gleichzeitig → Szene erkannt."""
        pass
```

### Schritt 6: Automation-Engine-Integration-Tests

Teste die Automatisierungslogik.

```python
# Datei: addon/tests/test_integration_automation_engine.py

"""Integration-Tests fuer die Automation Engine."""

import pytest


class TestAutomationEngineIntegration:
    """Teste Automatisierung End-to-End."""

    def test_suggestion_from_pattern(self, db_session, ha_mock):
        """Pattern erkannt → Automatisierungs-Vorschlag generiert."""
        pass

    def test_approved_suggestion_executes(self, db_session, ha_mock):
        """Genehmigter Vorschlag → wird zur richtigen Zeit ausgeführt."""
        pass

    def test_rejected_suggestion_not_repeated(self, db_session):
        """Abgelehnter Vorschlag → wird nicht nochmal vorgeschlagen."""
        pass

    def test_conflict_detection_blocks_execution(self, db_session, ha_mock):
        """Automation + manuelle Aktion gleichzeitig → Automation gestoppt."""
        pass

    def test_undo_reverts_action(self, db_session, ha_mock):
        """Undo → Gerät auf vorherigen Zustand zurückgesetzt."""
        pass

    def test_automation_respects_quiet_hours(self, db_session, ha_mock):
        """Automation während Quiet Hours → nicht ausgeführt (außer Safety)."""
        pass
```

### Schritt 7: Datenbank-Integration-Tests

Teste DB-Operationen unter realistischen Bedingungen.

```python
# Datei: addon/tests/test_integration_database.py

"""Integration-Tests fuer Datenbank-Operationen."""

import pytest
import threading


class TestDatabaseIntegration:
    """Teste DB unter realistischen Bedingungen."""

    def test_session_context_manager_commits(self, db_session):
        """get_db_session() committed automatisch bei Erfolg."""
        pass

    def test_session_context_manager_rollbacks(self, db_session):
        """get_db_session() rollbackt bei Exception."""
        pass

    def test_readonly_session_no_commit(self, db_session):
        """get_db_readonly() → keine Änderungen persistiert."""
        pass

    def test_concurrent_writes_no_deadlock(self, db_session):
        """Parallele Schreibzugriffe → kein Deadlock (db_write_with_retry)."""
        pass

    def test_migration_idempotent(self, db_session):
        """Migration 2x ausführen → kein Fehler."""
        pass

    def test_cascade_delete(self, db_session):
        """Raum löschen → zugehörige Geräte-Zuordnungen auch gelöscht."""
        pass
```

### Schritt 8: Security-Tests für Addon

```python
# Datei: addon/tests/test_integration_addon_security.py

"""Security-Integration-Tests fuer das Addon."""

import pytest


class TestAddonSecurity:
    """Teste Security-Grenzen des Addons."""

    def test_xss_in_device_name_sanitized(self, client, db_session):
        """<script>alert(1)</script> in Gerätename → wird escaped."""
        pass

    def test_sql_injection_blocked(self, client, db_session):
        """SQL-Injection in Suchfeld → kein DB-Zugriff."""
        pass

    def test_rate_limiting_enforced(self, client):
        """600+ Requests in 60s → 429 Too Many Requests."""
        pass

    def test_large_payload_rejected(self, client):
        """Payload > 1MB → 413 Payload Too Large."""
        pass

    def test_invalid_json_returns_400(self, client):
        """Ungültiger JSON-Body → 400 Bad Request."""
        pass

    def test_audit_log_on_sensitive_action(self, client, db_session):
        """Sensible Aktion → wird im AuditTrail geloggt."""
        pass
```

### Schritt 9: Tests ausführen und fixen

```bash
# Addon-Tests ausführen (aus Projekt-Root)
cd addon && python -m pytest tests/ -v --tb=short

# Bei Import-Fehlern: sys.path anpassen in conftest.py
# Bei DB-Fehlern: In-Memory SQLite Engine prüfen
# Bei HA-Mock-Fehlern: Synchrone Mocks (MagicMock, nicht AsyncMock!)
```

**Für JEDEN fehlschlagenden Test:**
1. Analysiere die Ursache (Import? Mock falsch? Code-Bug?)
2. Fix den Test ODER den Code
3. Retest bis grün

**Danach: Alle Tests zusammen ausführen:**
```bash
# Assistant-Tests (dürfen nicht brechen!)
cd assistant && python -m pytest --tb=short -q

# Addon-Tests
cd addon && python -m pytest tests/ --tb=short -q
```

---

## Output-Format

### 1. Test-Infrastruktur

```
Fixtures erstellt: [Anzahl]
- app (Flask Test-App): ✅/❌
- client (Test-Client): ✅/❌
- db_session (In-Memory SQLite): ✅/❌
- ha_mock (HA Connection): ✅/❌
- event_bus (EventBus): ✅/❌
- domain_plugin_mock: ✅/❌
```

### 2. Test-Übersicht

| Test-Datei | Tests | Bestanden | Fehlgeschlagen |
|---|---|---|---|
| test_integration_routes.py | X | X | X |
| test_integration_domains.py | X | X | X |
| test_integration_engines.py | X | X | X |
| test_integration_event_bus.py | X | X | X |
| test_integration_pattern_engine.py | X | X | X |
| test_integration_automation_engine.py | X | X | X |
| test_integration_database.py | X | X | X |
| test_integration_addon_security.py | X | X | X |
| **Gesamt** | **X** | **X** | **X** |

### 3. Gefundene Bugs

| # | Test | Bug | Datei:Zeile | Fix |
|---|---|---|---|---|
| 1 | test_X | Beschreibung | datei.py:123 | Was gefixt |

---

## Regeln

- **Addon ist SYNCHRON** — kein `async`/`await`, kein `pytest-asyncio`. Nutze `MagicMock`, nicht `AsyncMock`.
- **In-Memory SQLite** für DB-Tests — kein File-basiertes SQLite.
- **Flask Test-Client** für Route-Tests — kein `requests` oder HTTP.
- **Echte EventBus-Instanz** wenn möglich — sie ist thread-safe und einfach genug.
- **Lies die Route-Dateien** bevor du Tests schreibst — Endpoints, Parameter und Response-Formate variieren.
- **Import-Pfade prüfen** — Addon-Code liegt unter `addon/rootfs/opt/mindhome/`, Tests unter `addon/tests/`. `sys.path` muss in conftest.py angepasst werden.
- **Keine Abhängigkeit auf laufende Services** — kein HA, kein Redis, kein Ollama.

### Fortschritts-Tracking (Pflicht!)

Dokumentiere nach JEDER Test-Datei:

```
=== CHECKPOINT Test-Datei X/8 ===
Geschriebene Tests: [Anzahl]
Bestanden: [Anzahl]
Bugs gefunden: [Anzahl]
Verbleibend: [Liste]
================================
```

---

## Ergebnis speichern (Pflicht!)

> **Speichere deinen gesamten Output** in:
> ```
> Write: docs/audit-results/RESULT_07d_ADDON_INTEGRATION_TESTS.md
> ```

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der durch Tests gefundenen und gefixten Bugs]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten/erstellten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
