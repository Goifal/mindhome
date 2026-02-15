# MindHome Phase 5 — Implementierungsplan
# "Sicherheit + Spezial-Modi" (13 Features)

> **Stand:** 2026-02-15
> **Branch:** `claude/plan-phase-5-yZBaB`
> **Zielversion:** v0.8.0+
> **Basis:** Phase 4 fertig (v0.7.29, Build 82, DB Migration v11)
> **Zu implementieren:** 13 Features

---

## Strategie

Phase 5 wird in **5 Batches** mit **~12 Commits** implementiert:

1. Zuerst die **Infrastruktur** (neue Engine-Module, DB-Migration, Feature-Flags)
2. Dann Feature-Batches in logischer Reihenfolge: Alarm → Sensoren → Zugang → Modi → Dashboard
3. Jeder Batch: Backend → Frontend → Tests
4. Jedes Feature: Integration mit bestehenden Engines (Presence, Notifications, EventBus)
5. Am Ende: Sicherheits-Dashboard, Version-Bump, README-Update, Changelog

### Commit-Plan (~12 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v0.8.0` | 0 | version.py |
| 2 | `feat: Add Phase 5 infrastructure` | 0 | engines/ Stubs, routes/security.py, Feature-Flags |
| 3 | `feat: Add Phase 5 DB models + migration v12` | 0 | models.py + Migration + neue Enums |
| 4 | `feat(security): Add alarm system + intrusion detection` | 1 | #1 |
| 5 | `feat(security): Add fire/CO + water leak response` | 2 | #2, #3 |
| 6 | `feat(security): Add camera snapshots on alert` | 2 | #4 |
| 7 | `feat(security): Add access control + smart lock management` | 3 | #5 |
| 8 | `feat(security): Add geo-fencing` | 3 | #6 |
| 9 | `feat(modes): Add party + cinema + home-office modes` | 4 | #8, #9, #10 |
| 10 | `feat(modes): Add child safety + night lockdown + emergency protocol` | 4 | #11, #12, #13 |
| 11 | `feat(security): Add security dashboard` | 5 | #7 |
| 12 | `docs: Finalize Phase 5` | 5 | README, Changelog, Translations |

---

## Feature-Übersicht

### Sicherheit (7 Features)

| # | Feature | Beschreibung |
|---|---------|-------------|
| 1 | Alarm-System & Einbruch-Erkennung | Arm/Disarm-Zustände, Sensor-Überwachung, Sirene/Alarm |
| 2 | Rauch-/CO-Melder-Reaktion | Automatische Aktionen bei Feuer/Rauch/CO-Alarm |
| 3 | Wassermelder-Reaktion | Leck-Erkennung, Ventil-Steuerung, Schutzmaßnahmen |
| 4 | Kamera-Snapshots bei Alarm | Foto-Aufnahme bei Bewegung im Alarm-Zustand |
| 5 | Zutrittskontrolle | Smart-Lock-Management, Codes, Zutrittsprotokoll |
| 6 | Geo-Fencing | Standortbasiertes Arm/Disarm, Auto-Aktionen |
| 7 | Sicherheits-Dashboard | Zentrale Sicherheitsübersicht, Ereignisprotokoll |

### Spezial-Modi (6 Features)

| # | Feature | Beschreibung |
|---|---------|-------------|
| 8 | Party-Modus | Musik, Beleuchtungsszenen, Lautstärke-Monitoring |
| 9 | Kino-Modus | Licht dimmen, Rollläden schließen, Media-Sync |
| 10 | Home-Office-Modus | Fokus-Beleuchtung, DnD, Klimakomfort |
| 11 | Kinder-Sicherung | Geräte-Einschränkung, Schlafenszeit-Durchsetzung |
| 12 | Nacht-Sicherungs-Modus | Auto-Lock, Bewegungs-Alerts, Minimal-Beleuchtung |
| 13 | Notfall-Protokoll | Koordinierte Notfall-Reaktion, Eskalation |

---

## Batch 0: Infrastruktur & Datenbank (Commits 1-3)

**Ziel:** Neue Engine-Module, DB-Migration, Feature-Flags, Route-Blueprint.

### 0a: Neue Engine-Module

```
engines/
├── ... (bestehende Phase 4 Module)
├── security.py           # AlarmManager, IntrusionDetector (#1)
├── fire_water.py         # FireResponseManager, WaterLeakManager (#2, #3)
├── access_control.py     # AccessControlManager, GeoFenceManager (#5, #6)
├── camera_security.py    # SecurityCameraManager (#4)
└── special_modes.py      # PartyMode, CinemaMode, HomeOfficeMode, ChildSafety,
                          # NightLockdown, EmergencyProtocol (#8-#13)
```

Bestehende Engine-Module bleiben unverändert. Neue Phase-5-Klassen kommen in eigene Module.

### 0b: Neue Route

```
routes/
├── ... (bestehende 14 Blueprints)
└── security.py           # Security-Endpoints (Alarm, Zutritt, Kamera, Geo-Fence, Dashboard)
```

- `security_bp` in `routes/__init__.py` registrieren
- 15. Blueprint

### 0c: Feature-Flags

Wie Phase 4 über `SystemSettings`-Einträge:

```
phase5.alarm_system         = true/false  (braucht: binary_sensor Tür/Fenster ODER motion)
phase5.fire_co_response     = true/false  (braucht: smoke/CO-Sensor binary_sensor)
phase5.water_leak_response  = true/false  (braucht: moisture binary_sensor)
phase5.camera_snapshots     = true/false  (braucht: camera.* Entity)
phase5.access_control       = true/false  (braucht: lock.* Entity)
phase5.geo_fencing          = true/false  (braucht: device_tracker/person.* mit GPS)
phase5.security_dashboard   = true/false
phase5.party_mode           = true/false
phase5.cinema_mode          = true/false  (braucht: media_player Entity)
phase5.home_office_mode     = true/false
phase5.child_safety         = true/false  (braucht: profile_type="child" User)
phase5.night_lockdown       = true/false  (braucht: lock.* Entity empfohlen)
phase5.emergency_protocol   = true/false
```

- Jeder Scheduler-Task prüft sein Flag bevor er läuft
- Frontend zeigt nur aktivierte Features
- Defaults: Features ohne spezielle Sensoren = true, mit Sensoren = auto-detect
- API: `GET /api/system/phase5-features` → Liste mit Status + Sensor-Anforderungen
- API: `PUT /api/system/phase5-features/<key>` → Feature ein/ausschalten

### 0d: Graceful Degradation

| Feature | Voll-Sensorik | Fallback wenn fehlt |
|---------|---------------|---------------------|
| Alarm-System | Tür/Fenster + Motion + Sirene | Nur Notification, kein Sirenen-Trigger |
| Rauch-/CO-Reaktion | smoke/CO binary_sensor | Feature auto-deaktiviert |
| Wassermelder | moisture binary_sensor + Ventil | Notification ohne Auto-Ventil |
| Kamera-Snapshots | camera.* Entity | Feature auto-deaktiviert |
| Zutrittskontrolle | lock.* Entity | Nur Logging, kein Lock-Steuerung |
| Geo-Fencing | GPS device_tracker | Fallback: WiFi-Presence (home/away) |
| Party-Modus | Licht + Media + Motion | Nur vorhandene Domains steuern |
| Kino-Modus | Media + Licht + Cover | Nur vorhandene Domains steuern |
| Home-Office | Licht + Klima | Nur vorhandene Domains steuern |
| Kinder-Sicherung | Beliebig | Nur Zeitbegrenzung (ScreenTime) |
| Nacht-Sicherung | Lock + Motion | Nur Notification ohne Lock |
| Notfall | Alle | Eskalation: Notification → TTS → HA-Alert |

### 0e: Neue Enums

```python
class AlarmState(enum.Enum):
    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"      # Zu Hause, Perimeter bewacht
    ARMED_AWAY = "armed_away"      # Abwesend, alles bewacht
    ARMED_NIGHT = "armed_night"    # Nacht, Perimeter + Erdgeschoss
    PENDING = "pending"            # Entschärfungs-Countdown
    TRIGGERED = "triggered"        # Alarm ausgelöst

class SecurityEventType(enum.Enum):
    INTRUSION = "intrusion"
    FIRE = "fire"
    CO = "co"
    WATER_LEAK = "water_leak"
    DOOR_FORCED = "door_forced"
    PANIC = "panic"
    TAMPER = "tamper"
    ARM = "arm"
    DISARM = "disarm"

class SecuritySeverity(enum.Enum):
    INFO = "info"            # Arm/Disarm, Zutritt
    WARNING = "warning"      # Verzögertes Event (Pending)
    CRITICAL = "critical"    # Alarm ausgelöst
    EMERGENCY = "emergency"  # Feuer, Gas, Panik
```

### 0f: Neue Models in `models.py`

| Model | Zweck | Felder |
|-------|-------|--------|
| `SecurityConfig` | Alarm-Konfiguration | arm_state (Enum), pin_code_hash, entry_delay_sec (30), exit_delay_sec (60), siren_entity, siren_duration_sec (300), auto_arm_away (Boolean), auto_arm_night (Boolean), auto_arm_delay_min (15), notify_on_arm (Boolean), notify_on_alarm (Boolean) |
| `SecurityZone` | Zonen-Definition | name_de, name_en, zone_type ("perimeter"/"interior"/"fire"/"water"/"panic"), armed_states (JSON: welche AlarmStates diese Zone aktiv machen), entry_delay (Boolean), is_active |
| `SecuritySensor` | Sensor→Zonen-Zuordnung | device_id (FK), zone_id (FK), sensor_role ("trigger"/"tamper"/"bypass"), is_bypassed |
| `SecurityEvent` | Sicherheits-Ereignislog | event_type (Enum), severity (Enum), zone_id (FK), device_id (FK), message_de, message_en, alarm_state_before, alarm_state_after, resolved_at, resolved_by, snapshot_path, context (JSON) |
| `AccessCode` | Smart-Lock-Codes | user_id (FK, nullable), name, code_hash, lock_entity_ids (JSON), valid_from (nullable), valid_until (nullable), is_temporary, max_uses (nullable), use_count, is_active |
| `AccessLog` | Zutrittsereignisse | lock_entity_id, user_id (FK, nullable), access_code_id (FK, nullable), action ("lock"/"unlock"/"jammed"/"failed"), method ("code"/"key"/"auto"/"remote"/"unknown"), timestamp |
| `GeoFence` | Geo-Fence-Zone | name, latitude, longitude, radius_m, user_id (FK), action_on_enter (JSON), action_on_leave (JSON), linked_alarm_state (nullable), is_active |
| `SpecialModeConfig` | Spezial-Modi Config | mode_type ("party"/"cinema"/"home_office"/"child_safety"/"night_lockdown"/"emergency"), config (JSON), auto_deactivate_after_min (nullable), linked_presence_mode_id (FK, nullable), is_active |
| `SpecialModeLog` | Modi-Aktivierungslog | mode_type, activated_at, deactivated_at, activated_by (FK), reason |
| `ChildRestriction` | Kinder-Einschränkungen | user_id (FK), restriction_type ("device_block"/"time_limit"/"bedtime"), target_entities (JSON), config (JSON: limit_min, bedtime, weekday_bedtime, weekend_bedtime), is_active |
| `EmergencyContact` | Notfall-Kontakte | name, phone, email, notify_method ("push"/"sms"/"email"/"call"), priority, is_active |

### Neue Spalten in bestehenden Models:

| Model | Neue Spalte | Zweck |
|-------|-------------|-------|
| `Device` | `security_zone_id` (FK, nullable) | Zuordnung zu Sicherheitszone |
| `Room` | `security_priority` (Integer, default=0) | Alarmpiorität (EG > OG) |
| `User` | `emergency_contact` (String, nullable) | Notfall-Telefon |
| `User` | `geo_tracking_enabled` (Boolean, default=False) | GPS-Tracking Opt-in |
| `NotificationLog` | `security_event_id` (FK, nullable) | Verknüpfung mit Security-Event |
| `PresenceMode` | `linked_alarm_state` (String, nullable) | Automatisches Arm/Disarm bei Moduswechsel |

### 0g: Migration v12

- Alle `CREATE TABLE` Statements für neue Models
- Alle `ALTER TABLE` Statements für neue Spalten
- Feature-Flag Defaults in `SystemSettings` einfügen
- Default-Sicherheitszonen anlegen (Perimeter, Innenraum, Feuer, Wasser)
- `db_migration_version` auf 12 setzen

---

## Batch 1: Alarm-System & Einbruch-Erkennung — Commit 4 (Feature #1)

### #1 Alarm-System & Einbruch-Erkennung
**Dateien:** `engines/security.py`, `routes/security.py`

Das Herzstück von Phase 5. Ein flexibles Alarm-System mit 5 Zuständen.

- **Zustands-Maschine:**
  ```
  DISARMED ──→ ARMED_HOME ──→ TRIGGERED
       │            ↑              │
       │            │              ↓
       ├──→ ARMED_AWAY ──→ PENDING ──→ TRIGGERED
       │            ↑
       └──→ ARMED_NIGHT
  ```
  - `DISARMED → ARMED_*`: Exit-Delay (z.B. 60s zum Verlassen)
  - `ARMED_* → PENDING`: Entry-Delay (z.B. 30s zum Entschärfen, nur bei Perimeter-Zone mit entry_delay=true)
  - `PENDING → TRIGGERED`: Countdown abgelaufen ohne Entschärfung
  - `TRIGGERED → DISARMED`: PIN-Code oder Fernsteuerung

- **Backend:**
  - `AlarmManager`-Klasse in `engines/security.py`
    - `arm(state, pin)` → Startet Exit-Delay, dann Arm
    - `disarm(pin)` → Entschärft sofort
    - `trigger(zone, device, reason)` → Löst Alarm aus
    - `handle_sensor_event(entity_id, new_state)` → Prüft ob Sensor in aktiver Zone
  - `IntrusionDetector`-Klasse in `engines/security.py`
    - Überwacht alle `SecuritySensor`-Einträge
    - Bei Tür/Fenster öffnen im ARMED-State → prüft Zone
    - Bei Bewegung im ARMED_AWAY/ARMED_NIGHT → prüft Interior-Zone
    - Tamper-Erkennung: Sensor wird unavailable → Warnung
  - Event-Bus Integration:
    - Empfängt: `state_changed` Events für Sicherheits-Sensoren
    - Sendet: `alarm.armed`, `alarm.triggered`, `alarm.disarmed`, `alarm.pending`
  - Alarm-Aktionen bei TRIGGERED:
    1. Siren Entity einschalten (für `siren_duration_sec`)
    2. Alle Lichter an (100%)
    3. Notification an alle Admins (CRITICAL)
    4. `SecurityEvent` loggen mit Kontext
    5. Optional: Kamera-Snapshot (→ Feature #4)
  - Scheduler-Task: Nicht nötig — Event-basiert über EventBus (reagiert auf `state_changed`)
  - Aber: Timer-Thread für Exit/Entry-Delay Countdowns
  - API:
    - `GET /api/security/alarm` → aktueller Status (State, aktive Zonen, letzte Events)
    - `POST /api/security/alarm/arm` → Body: `{state, pin}`
    - `POST /api/security/alarm/disarm` → Body: `{pin}`
    - `POST /api/security/alarm/panic` → Sofortiger Alarm (kein PIN)
    - `GET /api/security/zones` → Zonen-Übersicht
    - `POST/PUT/DELETE /api/security/zones/<id>` → Zonen CRUD
    - `GET /api/security/sensors` → Sensoren mit Zonenzuordnung
    - `PUT /api/security/sensors/<device_id>` → Sensor zuordnen/bypass
    - `PUT /api/security/config` → Alarm-Konfiguration

- **Frontend:**
  - Alarm-Panel oben auf der Sicherheits-Seite
    - Großer Status-Indikator (Grün=Disarmed, Gelb=Armed, Rot=Triggered)
    - Arm/Disarm Buttons mit PIN-Eingabe
    - Panic-Button (Rot, groß)
    - Exit/Entry-Countdown-Anzeige
  - Zonen-Konfiguration
    - Liste der Zonen mit Sensor-Zuordnung
    - Drag & Drop von Geräten in Zonen
    - Bypass-Toggle pro Sensor

### Integration mit Presence-System

Das Alarm-System arbeitet Hand in Hand mit dem bestehenden `PresenceModeManager`:

| Presence-Modus | Auto-Alarm-Aktion | Bedingung |
|----------------|-------------------|-----------|
| Abwesend (Away) | → ARMED_AWAY | Wenn `auto_arm_away=true` + alle Personen weg |
| Zuhause (Home) | → DISARMED | Wenn erste Person zurückkommt |
| Schlaf (Sleep) | → ARMED_NIGHT | Wenn `auto_arm_night=true` |
| Urlaub (Vacation) | → ARMED_AWAY | Immer |

- `PresenceMode.linked_alarm_state` speichert die Zuordnung
- `PresenceModeManager` feuert Event `presence.mode_changed`
- `AlarmManager` lauscht auf dieses Event und wechselt Alarm-State

---

## Batch 2: Feuer/Wasser & Kamera — Commits 5-6 (Features #2, #3, #4)

### #2 Rauch-/CO-Melder-Reaktion
**Dateien:** `engines/fire_water.py`, `routes/security.py`

Automatische Reaktionen bei Feuer- oder CO-Alarm — zeitkritisch, immer aktiv (auch bei DISARMED).

- **Backend:**
  - `FireResponseManager`-Klasse in `engines/fire_water.py`
  - Überwacht: `binary_sensor` mit `device_class: smoke` oder `device_class: gas/co`
  - **Sofort-Aktionen bei Erkennung:**
    1. SecurityEvent loggen (severity=EMERGENCY)
    2. Alle Lichter an (100%) — Fluchtweg-Beleuchtung
    3. Alle Rollläden hoch — Fluchtweg freihalten
    4. HVAC/Lüftung stoppen — Rauchausbreitung verhindern
    5. Notification CRITICAL an alle User + Notfallkontakte
    6. TTS-Durchsage auf allen Speakern: "Feueralarm! Gebäude verlassen!"
    7. Optional: Smart Lock entriegeln (Fluchtwege)
  - **CO-spezifisch:**
    - Lüftung AN (nicht aus!) — CO muss raus
    - TTS: "CO-Alarm! Fenster öffnen und Gebäude verlassen!"
  - Event-Bus: Reagiert auf `state_changed` für smoke/co Sensoren
  - Event-Bus sendet: `emergency.fire`, `emergency.co`
  - Kein separater Scheduler nötig — rein Event-basiert
  - API:
    - `GET /api/security/fire-co/status` → Sensor-Status
    - `GET /api/security/fire-co/config` → Konfiguration
    - `PUT /api/security/fire-co/config` → Aktionen konfigurieren

- **Frontend:**
  - Feuer/CO-Karte auf Sicherheits-Seite
  - Sensor-Status pro Raum (OK / Warnung / Alarm)
  - Konfigurierbares Aktions-Set

### #3 Wassermelder-Reaktion
**Dateien:** `engines/fire_water.py`, `routes/security.py`

Schützt vor Wasserschäden durch automatische Ventilsteuerung.

- **Backend:**
  - `WaterLeakManager`-Klasse in `engines/fire_water.py`
  - Überwacht: `binary_sensor` mit `device_class: moisture`
  - **Aktionen bei Leck-Erkennung:**
    1. SecurityEvent loggen (severity=CRITICAL)
    2. Haupt-Wasserventil schließen (wenn vorhanden: `valve.*` oder `switch.*`)
    3. Notification CRITICAL an alle Admins
    4. Betroffenen Raum identifizieren (über Device→Room Zuordnung)
    5. Optional: Heizung im Raum abschalten (Frostschutz beachten!)
  - **Konfiguration:**
    - `valve_entity`: HA-Entity für Haupt-Wasserventil
    - `auto_shutoff`: Boolean — automatisch Ventil schließen?
    - `frost_protection_temp`: Mindest-Temperatur bei Heizungs-Abschaltung (Default: 5°C)
  - Event-Bus: Reagiert auf `state_changed` für moisture Sensoren
  - Event-Bus sendet: `emergency.water_leak`
  - API:
    - `GET /api/security/water-leak/status` → Sensor-Status
    - `GET /api/security/water-leak/config` → Konfiguration
    - `PUT /api/security/water-leak/config` → Ventil-Entity + Auto-Shutoff

- **Frontend:**
  - Wassermelder-Karte auf Sicherheits-Seite
  - Sensor-Status pro Raum
  - Ventil-Status (offen/geschlossen) mit manuellem Toggle
  - Letzter Alarm mit Zeitstempel

### #4 Kamera-Snapshots bei Alarm
**Dateien:** `engines/camera_security.py`, `routes/security.py`

Automatische Foto-Aufnahme bei Sicherheitsereignissen.

- **Backend:**
  - `SecurityCameraManager`-Klasse in `engines/camera_security.py`
  - Überwacht Events: `alarm.triggered`, `alarm.pending`
  - Bei Alarm:
    1. Snapshot von allen konfigurierten Kameras via `camera.snapshot` Service
    2. Speichert Bilder unter `/config/mindhome/snapshots/<timestamp>_<camera>.jpg`
    3. Verknüpft Snapshot-Pfad mit `SecurityEvent.snapshot_path`
    4. Optional: Snapshot als Notification-Attachment senden (wenn supported)
  - **Konfiguration:**
    - `snapshot_cameras`: Liste von camera.* Entity-IDs
    - `snapshot_on_events`: Welche Event-Typen triggern Snapshot (Default: intrusion, panic)
    - `retention_days`: Wie lange Snapshots behalten (Default: 30)
    - `max_snapshots_per_event`: Max. Bilder pro Ereignis (Default: 5)
  - Snapshot-Cleanup im bestehenden `data_retention`-Task integrieren
  - API:
    - `GET /api/security/cameras` → Kamera-Liste mit Status
    - `GET /api/security/cameras/snapshots` → Snapshot-Galerie (paginiert)
    - `GET /api/security/cameras/snapshots/<id>` → Einzelnes Bild
    - `DELETE /api/security/cameras/snapshots/<id>` → Snapshot löschen
    - `POST /api/security/cameras/<entity_id>/snapshot` → Manueller Snapshot
    - `PUT /api/security/cameras/config` → Kamera-Konfiguration

- **Frontend:**
  - Kamera-Karte auf Sicherheits-Seite
  - Live-Status pro Kamera (Online/Offline)
  - Snapshot-Galerie (Grid, sortiert nach Datum)
  - Manueller Snapshot-Button
  - Verknüpfung: Security-Event → zugehörige Snapshots

---

## Batch 3: Zutrittskontrolle & Geo-Fencing — Commits 7-8 (Features #5, #6)

### #5 Zutrittskontrolle
**Dateien:** `engines/access_control.py`, `routes/security.py`

Smart-Lock-Management mit Code-Verwaltung und Zutrittsprotokoll.

- **Backend:**
  - `AccessControlManager`-Klasse in `engines/access_control.py`
  - **Code-Verwaltung:**
    - Permanente Codes (Bewohner): User-verknüpft, immer gültig
    - Temporäre Codes (Gäste): Zeitlich begrenzt, max. Nutzungen
    - Einmal-Codes: 1 Nutzung, dann auto-deaktiviert
    - Codes werden gehasht gespeichert (wie User-PINs)
  - **Lock-Steuerung:**
    - API: Lock/Unlock einzelner oder aller Schlösser
    - Auto-Lock nach X Minuten (konfigurierbar)
    - Jammed-Erkennung (Lock-Entity State = "jammed" → Notification)
  - **Zutrittserkennung:**
    - Lauscht auf `lock.locked`/`lock.unlocked` Events
    - Versucht User-Zuordnung über:
      1. Zeitgleiche Person-Arrival (±2 Min)
      2. Code-Erkennung (wenn Lock-Entity Attribut `last_code` liefert)
      3. Manuell (über App-Steuerung → User bekannt)
    - Unbekannte Zutritte → Notification
  - **Zutrittsprotokoll:**
    - Jeder Lock/Unlock wird in `AccessLog` gespeichert
    - Methode: code, key, auto, remote, unknown
  - Event-Bus sendet: `access.unlocked`, `access.locked`, `access.unknown`, `access.jammed`
  - API:
    - `GET /api/security/access/locks` → Lock-Status (alle Schlösser)
    - `POST /api/security/access/locks/<entity_id>/lock` → Sperren
    - `POST /api/security/access/locks/<entity_id>/unlock` → Entsperren
    - `POST /api/security/access/lock-all` → Alle sperren
    - `GET /api/security/access/codes` → Code-Liste (ohne Klartext)
    - `POST /api/security/access/codes` → Neuen Code anlegen
    - `PUT /api/security/access/codes/<id>` → Code bearbeiten
    - `DELETE /api/security/access/codes/<id>` → Code löschen
    - `GET /api/security/access/log` → Zutrittsprotokoll (paginiert)
    - `PUT /api/security/access/config` → Auto-Lock etc.

- **Frontend:**
  - Zutritts-Tab auf Sicherheits-Seite
  - Lock-Status pro Tür (🔒/🔓 + Batterie-Level wenn verfügbar)
  - Code-Verwaltung (CRUD, temporäre Codes mit Ablaufdatum)
  - Zutrittsprotokoll als Timeline

### #6 Geo-Fencing
**Dateien:** `engines/access_control.py`, `routes/security.py`

Standortbasierte Automatisierungen — nutzt `device_tracker` / `person.*` Entities.

- **Backend:**
  - `GeoFenceManager`-Klasse in `engines/access_control.py`
  - **Zonen-Verwaltung:**
    - "Zuhause"-Zone (Default, Radius konfigurierbar)
    - Benutzerdefinierte Zonen (Arbeit, Schule, Gym, etc.)
    - GPS-Koordinaten + Radius in Metern
  - **Enter/Leave-Erkennung:**
    - Nutzt HA `zone.*` Entities + `person.*` / `device_tracker.*`
    - Haversine-Formel für Distanzberechnung
    - Hysterese: Enter bei < Radius, Leave bei > Radius + 50m (verhindert Flapping)
  - **Aktionen bei Enter/Leave:**
    - Enter "Zuhause": Alarm disarm, Licht an, Heizung hoch
    - Leave "Zuhause": Alarm arm_away, Alles aus, Heizung Eco
    - Enter "Arbeit": Home-Office-Modus deaktivieren
    - Benutzerdefinierte Aktionen pro Zone (JSON Action-Set)
  - **Verknüpfung mit Alarm:**
    - `GeoFence.linked_alarm_state`: Welcher Alarm-State bei Enter/Leave
    - Nur wenn alle Personen die Zone verlassen haben → Arm
    - Erste Person betritt Zone → Disarm
  - **Datenschutz:**
    - `User.geo_tracking_enabled` muss opt-in sein
    - GPS-Koordinaten werden NICHT in DB gespeichert (nur Zone-Event)
    - Nur Zone-Wechsel werden geloggt, nicht kontinuierliche Position
  - Scheduler-Task: `geofence_check` alle 60s — prüft Person-Entities gegen Zonen
  - API:
    - `GET /api/security/geofence/zones` → Zonen-Liste
    - `POST/PUT/DELETE /api/security/geofence/zones/<id>` → Zonen CRUD
    - `GET /api/security/geofence/status` → Wer ist wo?
    - `GET /api/security/geofence/config` → Global Config
    - `PUT /api/security/geofence/config` → Config Update

- **Frontend:**
  - Geo-Fence-Tab auf Sicherheits-Seite
  - Zonen-Liste mit Koordinaten + Radius
  - Pro Zone: Aktionen bei Enter/Leave konfigurieren
  - Status-Übersicht: Welche Person ist in welcher Zone
  - Datenschutz-Hinweis + Opt-in pro User

---

## Batch 4: Spezial-Modi — Commits 9-10 (Features #8-#13)

Alle Spezial-Modi folgen dem gleichen Pattern:
1. **Aktivierung:** Manuell (Button), Automatisch (Trigger), oder API
2. **Aktionen:** Domain-übergreifende Steuerung (Licht, Klima, Cover, Media)
3. **Deaktivierung:** Manuell, Timeout, oder entgegengesetztes Event
4. **Logging:** Jede Aktivierung/Deaktivierung in `SpecialModeLog`
5. **Integration:** EventBus Events, Notification, PresenceMode optional

### Gemeinsame Infrastruktur in `engines/special_modes.py`

```python
class SpecialModeBase:
    """Basisklasse für alle Spezial-Modi."""
    mode_type: str

    def activate(self, user_id, config_override=None)
    def deactivate(self, user_id, reason="manual")
    def is_active(self) -> bool
    def get_status(self) -> dict
    def _apply_actions(self, actions: list)
    def _restore_previous_state(self)

    # Vor Aktivierung: Aktuellen Zustand aller betroffenen Entities speichern
    # Bei Deaktivierung: Gespeicherten Zustand wiederherstellen
```

**State-Restore-Mechanismus:**
- Vor Modus-Aktivierung: Snapshot aller betroffenen Entity-States
- Gespeichert in `SpecialModeLog.context` als JSON
- Bei Deaktivierung: States wiederherstellen
- Timeout: Falls vergessen, deaktiviert sich Modus nach `auto_deactivate_after_min`

### #8 Party-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

- **Aktionen bei Aktivierung:**
  - Beleuchtungsszene "Party" aktivieren (konfigurierbar)
  - Musik-Player starten (wenn konfiguriert)
  - Temperatur leicht senken (viele Personen → wärmer)
  - Quiet Hours deaktivieren (Party-Override)
  - Alarm auf DISARMED (wenn armed)
- **Intelligente Features:**
  - Lautstärke-Monitoring: Wenn Lautstärke über Schwellwert → Notification "Es ist spät, Nachbarn?"
  - Auto-Deaktivierung: Standard 4h, konfigurierbar
  - Aufräum-Modus nach Party: Licht 100%, Lüftung an
- **Trigger:**
  - Manuell: Button in App
  - Auto: Gäste-Modus + Media-Player aktiv + abends
- **API:**
  - `POST /api/security/modes/party/activate`
  - `POST /api/security/modes/party/deactivate`
  - `GET /api/security/modes/party/status`
  - `PUT /api/security/modes/party/config`

### #9 Kino-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

- **Aktionen bei Aktivierung:**
  - Licht auf 5-10% dimmen (über Transition, sanft!)
  - Rollläden schließen (Verdunklung)
  - DnD-Modus: Notifications stumm (außer CRITICAL/EMERGENCY)
  - Optional: Klima-Anpassung (kein Fan-Geräusch, leise Lüftung)
- **Intelligente Features:**
  - Auto-Aktivierung: Media-Player spielt Film (nicht Musik) + Abend
  - Auto-Deaktivierung: Media-Player wird pausiert/gestoppt für > 5 Min
  - Pause-Erkennung: Bei Media-Pause → Licht auf 30% (sanft), bei Resume → zurück auf 5%
  - Room-Aware: Nur der Raum mit dem aktiven Media-Player wird verdunkelt
- **Trigger:**
  - Manuell: Button in App
  - Auto: Media-Player "playing" + Content-Type "movie" (wenn verfügbar)
- **API:**
  - `POST /api/security/modes/cinema/activate` → Body: `{room_id}` (optional)
  - `POST /api/security/modes/cinema/deactivate`
  - `GET /api/security/modes/cinema/status`
  - `PUT /api/security/modes/cinema/config`

### #10 Home-Office-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

- **Aktionen bei Aktivierung:**
  - Fokus-Beleuchtung: Kühles, helles Licht (hohe Farbtemperatur wenn tunable_white)
  - Klima: Komfort-Temperatur (21-22°C)
  - DnD-Modus: Nur CRITICAL Notifications
  - Circadian Override: Büro-Beleuchtung statt Wohnraum-Kurve
  - Optional: "Bitte nicht stören" TTS wenn jemand den Raum betritt
- **Intelligente Features:**
  - Pausen-Erkennung: Keine Bewegung am Schreibtisch > 50 Min → "Mach mal Pause!"
  - Auto-Aktivierung: Werktag + bestimmter Raum + Kalender "Home Office" Event
  - Auto-Deaktivierung: Feierabend (aus Kalender oder nach X Stunden)
  - Raum-bezogen: Nur der konfigurierte Office-Raum wird angepasst
- **Trigger:**
  - Manuell: Button in App
  - Auto: Kalender-Event "Home Office" / "Homeoffice" / "WFH"
- **API:**
  - `POST /api/security/modes/home-office/activate` → Body: `{room_id}`
  - `POST /api/security/modes/home-office/deactivate`
  - `GET /api/security/modes/home-office/status`
  - `PUT /api/security/modes/home-office/config`

### #11 Kinder-Sicherung
**Dateien:** `engines/special_modes.py`, `routes/security.py`

Schutz für Kinder — kombiniert Gerätesperren, Zeitlimits und Schlafenszeit.

- **Backend:**
  - Pro Kind (User mit `profile_type="child"`):
    - **Geräte-Sperre:** Bestimmte Entities nicht steuerbar (z.B. Herd, Ofen)
    - **Zeitlimit:** Bildschirmzeit pro Tag (nutzt ScreenTimeMonitor aus Phase 4)
    - **Schlafenszeit:** Ab Uhrzeit X: Medien aus, Licht gedimmt, Schlafmodus
    - **Wochenend-Ausnahme:** Andere Zeiten für Freitag/Samstag
  - Enforcement:
    - Geräte-Sperre: Bei manuellem Toggle über MindHome → Aktion blockieren + Notification an Eltern
    - Schlafenszeit: Automatische Aktionen (Medien aus, Licht auf Nacht-Level)
    - Zeitlimit: Warnung bei 80%, Auto-Off bei 100% (sanft, mit Vorwarnung)
  - Keine physische Gerätesperre (das kann MindHome nicht) — nur MindHome-seitige Kontrolle
- **API:**
  - `GET /api/security/child-safety/users` → Kinder-User mit Restrictions
  - `POST/PUT /api/security/child-safety/restrictions` → Einschränkung CRUD
  - `GET /api/security/child-safety/status` → Aktueller Status pro Kind

- **Frontend:**
  - Kinder-Tab auf Sicherheits-Seite
  - Pro Kind: Geräte-Sperre, Zeitlimit, Schlafenszeit konfigurieren
  - Status: Verbleibende Bildschirmzeit, nächste Schlafenszeit

### #12 Nacht-Sicherungs-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

Automatische Absicherung für die Nacht — eng mit Alarm-System und Sleep-Detection verknüpft.

- **Aktionen bei Aktivierung:**
  - Alle Türen verriegeln (Smart Locks)
  - Alarm auf ARMED_NIGHT
  - Nacht-Beleuchtung: Orientierungslichter im Flur (5%, warmweiß)
  - Alle Medien aus
  - Heizung auf Nacht-Temperatur
  - Fenster-Check: Notification wenn Fenster offen (optional: nicht schließen)
- **Intelligente Features:**
  - Auto-Aktivierung: Sleep Detection (aus Phase 4) + Abend-Phase
  - Auto-Deaktivierung: Morgen-Phase oder Wake-Up-Manager Start
  - Bewegungs-Alerts: Bewegung im EG während Nacht → leise Notification an Hauptschlafzimmer
  - Nicht im Schlafzimmer: EG-Bewegungsmelder überwachen, nicht Schlafzimmer
- **Trigger:**
  - Manuell: Button in App
  - Auto: Sleep-Detection Event + Konfigurierte Uhrzeit
- **API:**
  - `POST /api/security/modes/night-lockdown/activate`
  - `POST /api/security/modes/night-lockdown/deactivate`
  - `GET /api/security/modes/night-lockdown/status`
  - `PUT /api/security/modes/night-lockdown/config`

### #13 Notfall-Protokoll
**Dateien:** `engines/special_modes.py`, `routes/security.py`

Koordinierte Notfall-Reaktion — der "rote Knopf".

- **Notfall-Typen:**
  - **Feuer:** (automatisch aus #2, oder manuell)
  - **Einbruch:** (automatisch aus #1, oder manuell)
  - **Medizinisch:** (nur manuell)
  - **Panik:** (manuell, unspezifisch)

- **Eskalations-Kette:**
  ```
  1. Sofort:    Alle Lichter an, Sirene (wenn vorhanden), TTS-Durchsage
  2. +30s:      Push-Notification an alle User
  3. +60s:      Notfallkontakte benachrichtigen (E-Mail/Push)
  4. +5min:     Zweite Benachrichtigung an Notfallkontakte
  5. Fortlaufend: Alarm-Zustand bis manuell deaktiviert
  ```

- **Typ-spezifische Aktionen:**
  | Typ | Aktion |
  |-----|--------|
  | Feuer | Licht an, Rollläden hoch, Lüftung aus, Locks öffnen, TTS "Feueralarm" |
  | Einbruch | Licht an, Sirene an, Locks zu, TTS "Alarm", Kamera-Snapshot |
  | Medizinisch | Licht an, Haustür öffnen (Rettungsdienst), TTS "Medizinischer Notfall" |
  | Panik | Licht an, Sirene an, TTS "Alarm" |

- **Backend:**
  - `EmergencyProtocol`-Klasse in `engines/special_modes.py`
  - `trigger(emergency_type, source="manual")` → Startet Eskalationskette
  - `cancel(pin)` → Bricht ab (braucht PIN)
  - Nutzt bestehenden NotificationManager für Eskalation
  - Nutzt bestehenden AlarmManager für Sirene/Alarm-State
  - Timer-Thread für Eskalations-Schritte
- **API:**
  - `POST /api/security/emergency/trigger` → Body: `{type, source}`
  - `POST /api/security/emergency/cancel` → Body: `{pin}`
  - `GET /api/security/emergency/status` → Aktiver Notfall?
  - `GET /api/security/emergency/contacts` → Notfallkontakte
  - `POST/PUT/DELETE /api/security/emergency/contacts/<id>` → Kontakte CRUD

- **Frontend:**
  - Notfall-Button auf Sicherheits-Seite (Rot, prominent)
  - Notfall-Typ Auswahl beim Triggern
  - Aktiver Notfall: Countdown, Eskalations-Stufe, Cancel-Button mit PIN
  - Notfallkontakte-Verwaltung

---

## Batch 5: Dashboard & Finalisierung — Commits 11-12 (Feature #7)

### #7 Sicherheits-Dashboard
**Dateien:** `routes/security.py`, Frontend

Zentrale Übersicht aller Sicherheits-Features.

- **Backend:**
  - Aggregiert alle Security-Daten:
    - Alarm-Status (aktueller State)
    - Zonen-Status (alle Zonen mit Sensor-Count)
    - Offene Fenster/Türen (binary_sensor)
    - Lock-Status (alle Schlösser)
    - Letzte Security-Events (Timeline)
    - Aktive Spezial-Modi
    - Kamera-Status (online/offline)
    - Geo-Fence Status (Personen in Zonen)
  - API: `GET /api/security/dashboard` → Aggregierte Übersicht
  - API: `GET /api/security/events` → Event-Log (paginiert, filterbar)
  - API: `GET /api/security/events/stats` → Statistiken (Events pro Woche/Typ)

- **Frontend:**
  - Neue Seite "Sicherheit" im Hauptmenü (🛡️ Icon)
  - **7 Tabs:**
    1. **Dashboard** — Übersicht aller Sicherheits-Features
    2. **Alarm** — Arm/Disarm, Zonen, Sensoren (Feature #1)
    3. **Zutritt** — Locks, Codes, Protokoll (Feature #5)
    4. **Kameras** — Snapshots, Live-Status (Feature #4)
    5. **Geo-Fence** — Zonen, Personen-Status (Feature #6)
    6. **Spezial-Modi** — Alle 6 Modi aktivieren/konfigurieren (#8-#13)
    7. **Einstellungen** — Feature-Flags, Notfallkontakte, Konfiguration

  - **Dashboard-Tab Layout:**
    ```
    ┌──────────────────────────────────────────┐
    │  🛡️ ALARM: DISARMED  [Arm Home] [Arm Away] │
    ├────────────┬────────────┬────────────────┤
    │ 🚪 Türen   │ 🔒 Schlösser │ 📹 Kameras    │
    │ 2/5 offen  │ 3/3 zu      │ 2/2 online    │
    ├────────────┴────────────┴────────────────┤
    │ 📋 Letzte Ereignisse                      │
    │  10:30 🔓 Haustür entsperrt (Max, Code)  │
    │  09:15 🛡️ Alarm scharf (Auto, Abwesend)   │
    │  08:45 🔒 Alle Türen verriegelt (Auto)   │
    ├──────────────────────────────────────────┤
    │ 🎬 Aktive Modi: Keine                     │
    └──────────────────────────────────────────┘
    ```

### Version & Dokumentation
- `version.py`: VERSION = "0.8.0", CODENAME = "Phase 5 - Security & Modes"
- `README.md`: Phase 5 auf "✅ Fertig" setzen, Feature-Liste aktualisieren
- `CHANGELOG.md`: Alle 13 neuen Features dokumentieren
- Translations: `de.json` + `en.json` aktualisieren

### Neue Route-Registrierung
- `routes/__init__.py`: `security_bp` registrieren
- `app.py`: Security-Blueprint importieren

### Scheduler-Tasks

Sicherheits-Features sind überwiegend **Event-basiert** (über EventBus), nicht Scheduler-basiert.
Das ist ein Unterschied zu Phase 4 — Sicherheit muss sofort reagieren, nicht alle 5 Min.

| Task | Intervall | Enthält | Features |
|------|-----------|---------|----------|
| `security_monitor` | Event-basiert | AlarmManager + IntrusionDetector + FireResponse + WaterLeak | #1, #2, #3 |
| `geofence_check` | 60s | GeoFenceManager | #6 |
| `access_autolock` | 60s | Auto-Lock Timer prüfen | #5 |
| `special_mode_check` | 5 Min | Timeout-Check für aktive Modi | #8-#13 |
| `child_safety_check` | 5 Min | Bildschirmzeit + Schlafenszeit | #11 |
| `camera_cleanup` | 24h | Alte Snapshots löschen (Retention) | #4 |

### EventBus-Registrierungen (neu)

| Event | Sender | Empfänger |
|-------|--------|-----------|
| `state_changed` | StateLogger | AlarmManager, FireResponse, WaterLeak, AccessControl |
| `alarm.armed` | AlarmManager | SecurityCameraManager, NotificationManager |
| `alarm.triggered` | AlarmManager | SecurityCameraManager, EmergencyProtocol, NotificationManager |
| `alarm.disarmed` | AlarmManager | — |
| `alarm.pending` | AlarmManager | SecurityCameraManager |
| `emergency.fire` | FireResponseManager | EmergencyProtocol |
| `emergency.co` | FireResponseManager | EmergencyProtocol |
| `emergency.water_leak` | WaterLeakManager | NotificationManager |
| `access.unlocked` | AccessControlManager | AlarmManager (Disarm-Check) |
| `access.jammed` | AccessControlManager | NotificationManager |
| `presence.mode_changed` | PresenceModeManager | AlarmManager (Auto-Arm/Disarm) |
| `sleep.detected` | SleepDetector | NightLockdown (Auto-Aktivierung) |
| `wake.detected` | WakeUpManager | NightLockdown (Auto-Deaktivierung) |
| `mode.activated` | SpecialModeBase | NotificationManager, Dashboard |
| `mode.deactivated` | SpecialModeBase | NotificationManager, Dashboard |

---

## Zusammenfassung

| Batch | Features | Commits | Neue Dateien | Geänderte Dateien |
|-------|----------|---------|-------------|-------------------|
| 0 | Infrastruktur | 1-3 | engines/ (5 Dateien), routes/security.py | models.py, version.py |
| 1 | #1 | 4 | — | engines/security.py, routes/security.py |
| 2 | #2, #3, #4 | 5-6 | — | engines/fire_water.py, engines/camera_security.py, routes/security.py |
| 3 | #5, #6 | 7-8 | — | engines/access_control.py, routes/security.py |
| 4 | #8-#13 | 9-10 | — | engines/special_modes.py, routes/security.py |
| 5 | #7 + Finalisierung | 11-12 | — | routes/security.py, app.jsx, version.py, README.md, de.json, en.json |

**Geschätzte Änderungen:**
- 6 neue Dateien: `engines/` (5 Module) + `routes/security.py`
- ~10 neue DB-Models + ~6 neue Spalten + 3 neue Enums
- ~13 Feature-Flags in SystemSettings
- ~10 bestehende Dateien modifiziert
- ~40 neue API-Endpoints
- 5 Scheduler-Tasks (+ Event-basierte Handler)
- 1 neuer EventBus-basierter Security-Monitor
- Frontend: 1 neue Seite "Sicherheit" mit 7 Tabs in app.jsx
- Graceful Degradation für alle Sensor-abhängigen Features
- State-Restore-Mechanismus für Spezial-Modi
- **5 Batches, ~12 Commits**
