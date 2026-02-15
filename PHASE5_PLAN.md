# MindHome Phase 5 — Implementierungsplan
# "Sicherheit + Spezial-Modi" (11 Features)

> **Stand:** 2026-02-15
> **Branch:** `claude/plan-phase-5-yZBaB`
> **Zielversion:** v0.8.0+
> **Basis:** Phase 4 fertig (v0.7.29, Build 82, DB Migration v11)
> **Zu implementieren:** 11 Features
> **Hinweis:** Alarm-System / Einbruch-Erkennung wird **nicht** in MindHome implementiert —
> das läuft über eine separate HA-Integration. MindHome kann den HA `alarm_control_panel`
> State lesen (read-only im Dashboard), steuert aber keine Arm/Disarm-Logik.

---

## Strategie

Phase 5 wird in **4 Batches** mit **~10 Commits** implementiert:

1. Zuerst die **Infrastruktur** (neue Engine-Module, DB-Migration, Feature-Flags)
2. Dann Feature-Batches in logischer Reihenfolge: Sensoren → Zugang → Modi → Dashboard
3. Jeder Batch: Backend → Frontend → Tests
4. Jedes Feature: Integration mit bestehenden Engines (Presence, Notifications, EventBus)
5. Am Ende: Sicherheits-Dashboard, Version-Bump, README-Update, Changelog

### Commit-Plan (~10 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v0.8.0` | 0 | version.py |
| 2 | `feat: Add Phase 5 infrastructure` | 0 | engines/ Stubs, routes/security.py, Feature-Flags |
| 3 | `feat: Add Phase 5 DB models + migration v12` | 0 | models.py + Migration + neue Enums |
| 4 | `feat(security): Add fire/CO + water leak response` | 1 | #1, #2 |
| 5 | `feat(security): Add camera snapshots on security events` | 1 | #3 |
| 6 | `feat(security): Add access control + smart lock management` | 2 | #4 |
| 7 | `feat(security): Add geo-fencing` | 2 | #5 |
| 8 | `feat(modes): Add party + cinema + home-office modes` | 3 | #7, #8, #9 |
| 9 | `feat(modes): Add night lockdown + emergency protocol` | 3 | #10, #11 |
| 10 | `feat(security): Add security dashboard + finalize Phase 5` | 4 | #6 + Docs |

---

## Feature-Übersicht

### Sicherheit (6 Features)

| # | Feature | Beschreibung |
|---|---------|-------------|
| 1 | Rauch-/CO-Melder-Reaktion | Automatische Aktionen bei Feuer/Rauch/CO-Alarm |
| 2 | Wassermelder-Reaktion | Leck-Erkennung, Ventil-Steuerung, Schutzmaßnahmen |
| 3 | Kamera-Snapshots bei Sicherheitsereignissen | Foto-Aufnahme bei Notfall-Events |
| 4 | Zutrittskontrolle | Smart-Lock-Management, Codes, Zutrittsprotokoll |
| 5 | Geo-Fencing | Standortbasierte Aktionen, Auto-Presence |
| 6 | Sicherheits-Dashboard | Zentrale Sicherheitsübersicht, Ereignisprotokoll |

### Spezial-Modi (5 Features)

| # | Feature | Beschreibung |
|---|---------|-------------|
| 7 | Party-Modus | Musik, Beleuchtungsszenen, Lautstärke-Monitoring |
| 8 | Kino-Modus | Licht dimmen, Rollläden schließen, Media-Sync |
| 9 | Home-Office-Modus | Fokus-Beleuchtung, DnD, Klimakomfort |
| 10 | Nacht-Sicherungs-Modus | Auto-Lock, Bewegungs-Alerts, Minimal-Beleuchtung |
| 11 | Notfall-Protokoll | Koordinierte Notfall-Reaktion, Eskalation |

---

## Batch 0: Infrastruktur & Datenbank (Commits 1-3)

**Ziel:** Neue Engine-Module, DB-Migration, Feature-Flags, Route-Blueprint.

### 0a: Neue Engine-Module

```
engines/
├── ... (bestehende Phase 4 Module)
├── fire_water.py         # FireResponseManager, WaterLeakManager (#1, #2)
├── access_control.py     # AccessControlManager, GeoFenceManager (#4, #5)
├── camera_security.py    # SecurityCameraManager (#3)
└── special_modes.py      # PartyMode, CinemaMode, HomeOfficeMode,
                          # NightLockdown, EmergencyProtocol (#7-#11)
```

Bestehende Engine-Module bleiben unverändert. Neue Phase-5-Klassen kommen in eigene Module.

### 0b: Neue Route

```
routes/
├── ... (bestehende 14 Blueprints)
└── security.py           # Security-Endpoints (Zutritt, Kamera, Geo-Fence, Modi, Dashboard)
```

- `security_bp` in `routes/__init__.py` registrieren
- 15. Blueprint

### 0c: Feature-Flags

Wie Phase 4 über `SystemSettings`-Einträge:

```
phase5.fire_co_response     = true/false  (braucht: smoke/CO-Sensor binary_sensor)
phase5.water_leak_response  = true/false  (braucht: moisture binary_sensor)
phase5.camera_snapshots     = true/false  (braucht: camera.* Entity)
phase5.access_control       = true/false  (braucht: lock.* Entity)
phase5.geo_fencing          = true/false  (braucht: device_tracker/person.* mit GPS)
phase5.security_dashboard   = true/false
phase5.party_mode           = true/false
phase5.cinema_mode          = true/false  (braucht: media_player Entity)
phase5.home_office_mode     = true/false
phase5.night_lockdown       = true/false  (braucht: lock.* Entity empfohlen)
phase5.emergency_protocol   = true/false
```

- Jeder Scheduler-Task prüft sein Flag bevor er läuft
- Frontend zeigt nur aktivierte Features
- Defaults: Features ohne spezielle Sensoren = true, mit Sensoren = auto-detect
- API: `GET /api/system/phase5-features` → Liste mit Status + Sensor-Anforderungen
- API: `PUT /api/system/phase5-features/<key>` → Feature ein/ausschalten

### 0d: Entity-Zuordnung & Steuerbarkeit

**Prinzip:** Jedes Feature arbeitet mit HA-Entities. Der User kann **alle Entity-Zuordnungen
selbst verwalten** — hinzufügen, entfernen, konfigurieren. Auto-Detection schlägt Entities
vor, der User bestätigt/ändert. Nichts passiert automatisch ohne Bestätigung.

**Generische Entity-Management API** (für alle Features einheitlich):
- `GET /api/security/entities/<feature_key>` → Alle zugeordneten Entities + Rollen
- `POST /api/security/entities/<feature_key>` → Entity zuordnen: `{entity_id, role, config}`
- `PUT /api/security/entities/<feature_key>/<id>` → Zuordnung bearbeiten
- `DELETE /api/security/entities/<feature_key>/<id>` → Zuordnung entfernen
- `POST /api/security/entities/<feature_key>/auto-detect` → Vorschläge (nicht auto-speichern!)

**Entity-Rollen pro Feature:**

| Feature | `feature_key` | Verfügbare Rollen |
|---------|---------------|-------------------|
| #1 Rauch/CO | `fire_co` | `trigger` (smoke/co Sensoren), `emergency_light` (Lichter → 100%), `emergency_cover` (Rollläden → hoch), `hvac` (Lüftung stoppen/starten), `emergency_lock` (Locks → entriegeln), `tts_speaker` (TTS-Durchsage) |
| #2 Wassermelder | `water_leak` | `trigger` (moisture Sensoren), `valve` (Hauptventil), `heating` (Heizung im Raum) |
| #3 Kamera | `camera` | `snapshot_camera` (Kameras für Snapshots) |
| #4 Zutrittskontrolle | `access` | `lock` (Smart Locks) |
| #5 Geo-Fencing | `geofence` | `person` (person.*/device_tracker.* für GPS-Tracking) |
| #7 Party | `party` | `light` (Party-Beleuchtung), `media` (Musik-Player), `climate` (Temperatur) |
| #8 Kino | `cinema` | `light` (Dimm-Lichter), `cover` (Verdunklung), `media` (Haupt-Player), `climate` (Leise-Modus) |
| #9 Home-Office | `home_office` | `light` (Fokus-Beleuchtung), `climate` (Komfort-Temp), `motion` (Pausen-Erkennung), `tts_speaker` (DnD-Ansage) |
| #10 Nacht-Sicherung | `night_lockdown` | `lock` (Verriegelung), `motion` (EG-Überwachung), `night_light` (Orientierungslichter), `media` (→ aus), `climate` (Nacht-Temp), `window_sensor` (Fenster-Check), `alarm_panel` (HA alarm_control_panel) |
| #11 Notfall | `emergency` | `siren` (Sirene), `light` (Alle Lichter an), `lock` (Typ-abhängig auf/zu), `tts_speaker` (Durchsage), `cover` (Rollläden), `hvac` (Lüftung) |

**Jede Entity-Zuordnung hat optionale role-spezifische Config** (JSON), z.B.:
- `light` + `{brightness: 100, color_temp: 4000}` — Zielhelligkeit + Farbtemperatur
- `climate` + `{target_temp: 21.5}` — Zieltemperatur
- `cover` + `{position: 100}` — Zielposition (100 = offen)
- `night_light` + `{brightness: 5, color_temp: 2700}` — Gedimmtes Nachtlicht
- `media` + `{volume: 0.8, source: "playlist_party"}` — Media-Konfiguration
- `tts_speaker` + `{volume: 1.0}` — TTS-Lautstärke

**Frontend: Entity-Zuordnungs-UI** (pro Feature im Einstellungen-Tab):
- Liste aller zugeordneten Entities mit Rolle + Config
- "Entity hinzufügen" Button → Entity-Picker (filtert nach passenden Domains)
- "Auto-Erkennung" Button → zeigt Vorschläge an, User bestätigt einzeln
- Inline-Edit für role-spezifische Config (Helligkeit, Temperatur, etc.)
- Drag & Drop zum Umsortieren (Priorität)

### 0e: Graceful Degradation

| Feature | Voll-Sensorik | Fallback wenn fehlt |
|---------|---------------|---------------------|
| Rauch-/CO-Reaktion | smoke/CO binary_sensor | Feature auto-deaktiviert |
| Wassermelder | moisture binary_sensor + Ventil | Notification ohne Auto-Ventil |
| Kamera-Snapshots | camera.* Entity | Feature auto-deaktiviert |
| Zutrittskontrolle | lock.* Entity | Nur Logging, keine Lock-Steuerung |
| Geo-Fencing | GPS device_tracker | Fallback: WiFi-Presence (home/away) |
| Party-Modus | Licht + Media + Motion | Nur vorhandene Domains steuern |
| Kino-Modus | Media + Licht + Cover | Nur vorhandene Domains steuern |
| Home-Office | Licht + Klima | Nur vorhandene Domains steuern |
| Nacht-Sicherung | Lock + Motion | Nur Notification ohne Lock |
| Notfall | Alle | Eskalation: Notification → TTS → HA-Alert |

### 0f: Neue Enums

```python
class SecurityEventType(enum.Enum):
    FIRE = "fire"
    CO = "co"
    WATER_LEAK = "water_leak"
    ACCESS_UNLOCK = "access_unlock"
    ACCESS_LOCK = "access_lock"
    ACCESS_JAMMED = "access_jammed"
    ACCESS_UNKNOWN = "access_unknown"
    PANIC = "panic"
    EMERGENCY = "emergency"
    MODE_ACTIVATED = "mode_activated"
    MODE_DEACTIVATED = "mode_deactivated"

class SecuritySeverity(enum.Enum):
    INFO = "info"            # Zutritt, Modus-Wechsel
    WARNING = "warning"      # Unbekannter Zutritt, Fenster offen
    CRITICAL = "critical"    # Wassermelder, Jammed Lock
    EMERGENCY = "emergency"  # Feuer, Gas, Panik
```

### 0g: Neue Models in `models.py`

| Model | Zweck | Felder |
|-------|-------|--------|
| `FeatureEntityAssignment` | Entity↔Feature-Zuordnung | feature_key (String), entity_id (String), role (String), config (JSON, nullable), sort_order (Integer, default=0), is_active (Boolean, default=true), created_at |
| `SecurityEvent` | Sicherheits-Ereignislog | event_type (Enum), severity (Enum), device_id (FK, nullable), room_id (FK, nullable), message_de, message_en, resolved_at, resolved_by, snapshot_path, context (JSON), timestamp |
| `AccessCode` | Smart-Lock-Codes | user_id (FK, nullable), name, code_hash, lock_entity_ids (JSON), valid_from (nullable), valid_until (nullable), is_temporary, max_uses (nullable), use_count, is_active, created_at |
| `AccessLog` | Zutrittsereignisse | lock_entity_id, user_id (FK, nullable), access_code_id (FK, nullable), action ("lock"/"unlock"/"jammed"/"failed"), method ("code"/"key"/"auto"/"remote"/"unknown"), timestamp |
| `GeoFence` | Geo-Fence-Zone | name, latitude, longitude, radius_m, user_id (FK, nullable), action_on_enter (JSON), action_on_leave (JSON), is_active, created_at |
| `SpecialModeConfig` | Spezial-Modi Config | mode_type ("party"/"cinema"/"home_office"/"night_lockdown"/"emergency"), config (JSON), auto_deactivate_after_min (nullable), linked_presence_mode_id (FK, nullable), is_active |
| `SpecialModeLog` | Modi-Aktivierungslog | mode_type, activated_at, deactivated_at, activated_by (FK, nullable), reason, previous_states (JSON) |
| `EmergencyContact` | Notfall-Kontakte | name, phone, email, notify_method ("push"/"email"), priority, is_active |

### Neue Spalten in bestehenden Models:

| Model | Neue Spalte | Zweck |
|-------|-------------|-------|
| `User` | `emergency_contact` (String, nullable) | Notfall-Telefon |
| `User` | `geo_tracking_enabled` (Boolean, default=False) | GPS-Tracking Opt-in |
| `NotificationLog` | `security_event_id` (FK, nullable) | Verknüpfung mit Security-Event |

### 0h: Migration v12

- Alle `CREATE TABLE` Statements für neue Models
- Alle `ALTER TABLE` Statements für neue Spalten
- Feature-Flag Defaults in `SystemSettings` einfügen
- `db_migration_version` auf 12 setzen

---

## Batch 1: Feuer/Wasser & Kamera — Commits 4-5 (Features #1, #2, #3)

### #1 Rauch-/CO-Melder-Reaktion
**Dateien:** `engines/fire_water.py`, `routes/security.py`

Automatische Reaktionen bei Feuer- oder CO-Alarm — zeitkritisch, immer aktiv.

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
  - **Konfigurierbare Einstellungen** (`PUT /api/security/fire-co/config`):
    - `unlock_on_fire`: Boolean — Locks bei Feuer entriegeln? (Default: true)
    - `stop_hvac_on_fire`: Boolean — Lüftung bei Rauch stoppen? (Default: true)
    - `start_hvac_on_co`: Boolean — Lüftung bei CO einschalten? (Default: true)
    - `tts_message_fire_de`: String — TTS-Text bei Feuer (editierbar)
    - `tts_message_fire_en`: String — TTS-Text bei Feuer EN
    - `tts_message_co_de`: String — TTS-Text bei CO (editierbar)
    - `tts_message_co_en`: String — TTS-Text bei CO EN
    - `tts_volume`: Integer 0-100 — TTS-Lautstärke (Default: 100)
    - `notification_users`: Liste von User-IDs — Wer wird benachrichtigt
    - `notify_emergency_contacts`: Boolean — Notfallkontakte benachrichtigen? (Default: true)
  - Entity-Zuordnung über generische API (siehe 0d): Sensoren, Lichter, Rollläden, Lüftung, Locks, TTS-Speaker einzeln hinzufügen/entfernen
  - API:
    - `GET /api/security/fire-co/status` → Sensor-Status
    - `GET /api/security/fire-co/config` → Vollständige Konfiguration
    - `PUT /api/security/fire-co/config` → Einstellungen ändern

- **Frontend:**
  - Feuer/CO-Karte auf Sicherheits-Seite
  - Sensor-Status pro Raum (OK / Warnung / Alarm)
  - Konfigurations-Panel: Alle Einstellungen editierbar
  - Entity-Zuordnung: Sensoren + Reaktions-Entities verwalten

### #2 Wassermelder-Reaktion
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
  - **Konfigurierbare Einstellungen** (`PUT /api/security/water-leak/config`):
    - `auto_shutoff`: Boolean — automatisch Ventil schließen? (Default: true)
    - `frost_protection_temp`: Float — Mindest-Temperatur bei Heizungs-Abschaltung (Default: 5.0°C)
    - `shutoff_heating_on_leak`: Boolean — Heizung im Raum abschalten? (Default: true)
    - `notification_users`: Liste von User-IDs
    - `tts_enabled`: Boolean — TTS-Durchsage bei Leck? (Default: false)
    - `tts_message_de/en`: String — TTS-Text (editierbar)
  - Entity-Zuordnung über generische API (siehe 0d): Moisture-Sensoren, Ventil, Heizung einzeln zuweisen
  - Event-Bus: Reagiert auf `state_changed` für moisture Sensoren
  - Event-Bus sendet: `emergency.water_leak`
  - API:
    - `GET /api/security/water-leak/status` → Sensor-Status + Ventil-Status
    - `GET /api/security/water-leak/config` → Vollständige Konfiguration
    - `PUT /api/security/water-leak/config` → Einstellungen ändern

- **Frontend:**
  - Wassermelder-Karte auf Sicherheits-Seite
  - Sensor-Status pro Raum
  - Ventil-Status (offen/geschlossen) mit manuellem Toggle
  - Konfigurations-Panel mit Entity-Zuordnung
  - Letzter Alarm mit Zeitstempel

### #3 Kamera-Snapshots bei Sicherheitsereignissen
**Dateien:** `engines/camera_security.py`, `routes/security.py`

Automatische Foto-Aufnahme bei Sicherheitsereignissen.

- **Backend:**
  - `SecurityCameraManager`-Klasse in `engines/camera_security.py`
  - Überwacht Events: `emergency.fire`, `emergency.co`, `emergency.water_leak`, `emergency.triggered`, `access.unknown`
  - Bei Sicherheitsereignis:
    1. Snapshot von allen konfigurierten Kameras via `camera.snapshot` Service
    2. Speichert Bilder unter `/config/mindhome/snapshots/<timestamp>_<camera>.jpg`
    3. Verknüpft Snapshot-Pfad mit `SecurityEvent.snapshot_path`
    4. Optional: Snapshot als Notification-Attachment senden (wenn supported)
  - **Konfigurierbare Einstellungen** (`PUT /api/security/cameras/config`):
    - `snapshot_on_events`: Liste — Welche Event-Typen triggern Snapshot (Default: [fire, co, panic, access_unknown]) — User kann Events hinzufügen/entfernen
    - `retention_days`: Integer — Wie lange Snapshots behalten (Default: 30, editierbar)
    - `max_snapshots_per_event`: Integer — Max. Bilder pro Ereignis (Default: 5)
    - `attach_to_notification`: Boolean — Snapshot als Notification-Anhang? (Default: true)
  - Kameras über generische Entity-API (siehe 0d) zuordnen — nicht auto-detect
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

## Batch 2: Zutrittskontrolle & Geo-Fencing — Commits 6-7 (Features #4, #5)

### #4 Zutrittskontrolle
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
    - Unbekannte Zutritte → Notification + Kamera-Snapshot (→ Feature #3)
  - **Zutrittsprotokoll:**
    - Jeder Lock/Unlock wird in `AccessLog` gespeichert
    - Methode: code, key, auto, remote, unknown
  - **Konfigurierbare Einstellungen** (`PUT /api/security/access/config`):
    - `auto_lock_enabled`: Boolean — Auto-Lock nach Timeout? (Default: true)
    - `auto_lock_delay_min`: Integer — Minuten bis Auto-Lock (Default: 5, editierbar)
    - `jammed_notification`: Boolean — Benachrichtigung bei Jammed? (Default: true)
    - `unknown_access_notification`: Boolean — Bei unbekanntem Zutritt? (Default: true)
    - `unknown_access_snapshot`: Boolean — Kamera-Snapshot bei unbekanntem Zutritt? (Default: true)
    - `person_match_window_min`: Integer — Zeitfenster für User-Zuordnung (Default: 2)
    - `notification_users`: Liste von User-IDs
  - Lock-Entities über generische Entity-API (siehe 0d) zuordnen
  - Event-Bus sendet: `access.unlocked`, `access.locked`, `access.unknown`, `access.jammed`
  - API:
    - `GET /api/security/access/locks` → Lock-Status (alle zugeordneten Schlösser)
    - `POST /api/security/access/locks/<entity_id>/lock` → Sperren
    - `POST /api/security/access/locks/<entity_id>/unlock` → Entsperren
    - `POST /api/security/access/lock-all` → Alle sperren
    - `GET /api/security/access/codes` → Code-Liste (ohne Klartext)
    - `POST /api/security/access/codes` → Neuen Code anlegen
    - `PUT /api/security/access/codes/<id>` → Code bearbeiten
    - `DELETE /api/security/access/codes/<id>` → Code löschen
    - `GET /api/security/access/log` → Zutrittsprotokoll (paginiert, filterbar)
    - `GET /api/security/access/config` → Konfiguration
    - `PUT /api/security/access/config` → Einstellungen ändern

- **Frontend:**
  - Zutritts-Tab auf Sicherheits-Seite
  - Lock-Status pro Tür (Locked/Unlocked + Batterie-Level wenn verfügbar)
  - Code-Verwaltung (CRUD, temporäre Codes mit Ablaufdatum)
  - Zutrittsprotokoll als Timeline

### #5 Geo-Fencing
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
    - Enter "Zuhause": Presence → Home, Licht an, Heizung hoch
    - Leave "Zuhause": Presence → Away, Alles aus, Heizung Eco
    - Enter "Arbeit": Home-Office-Modus deaktivieren
    - Benutzerdefinierte Aktionen pro Zone (JSON Action-Set)
  - **Verknüpfung mit Presence-System:**
    - Enter/Leave löst automatisch PresenceMode-Wechsel aus
    - Nur wenn alle Personen die Zone verlassen haben → Away-Modus
    - Erste Person betritt Zone → Home-Modus
  - **Datenschutz:**
    - `User.geo_tracking_enabled` muss opt-in sein
    - GPS-Koordinaten werden NICHT in DB gespeichert (nur Zone-Event)
    - Nur Zone-Wechsel werden geloggt, nicht kontinuierliche Position
  - **Konfigurierbare Einstellungen** (`PUT /api/security/geofence/config`):
    - `check_interval_sec`: Integer — Prüf-Intervall (Default: 60, editierbar)
    - `hysteresis_m`: Integer — Leave-Hysterese in Metern (Default: 50)
    - `all_away_action`: JSON — Was passiert wenn alle weg (Presence → Away, etc.)
    - `first_home_action`: JSON — Was passiert wenn erste Person zurück
    - `log_zone_events`: Boolean — Zone-Wechsel loggen? (Default: true)
  - Person-/Device-Tracker-Entities über generische Entity-API (siehe 0d) zuordnen
  - Zonen: Volle CRUD — User kann beliebig viele Zonen mit eigenen Aktionen definieren
  - Pro Zone: `action_on_enter` + `action_on_leave` komplett konfigurierbar als JSON Action-Set
  - Scheduler-Task: `geofence_check` alle `check_interval_sec` Sekunden
  - API:
    - `GET /api/security/geofence/zones` → Zonen-Liste mit Aktionen
    - `POST /api/security/geofence/zones` → Neue Zone anlegen
    - `PUT /api/security/geofence/zones/<id>` → Zone bearbeiten (Name, Koordinaten, Radius, Aktionen)
    - `DELETE /api/security/geofence/zones/<id>` → Zone löschen
    - `GET /api/security/geofence/status` → Wer ist wo?
    - `GET /api/security/geofence/config` → Globale Konfiguration
    - `PUT /api/security/geofence/config` → Einstellungen ändern

- **Frontend:**
  - Geo-Fence-Tab auf Sicherheits-Seite
  - Zonen-Liste mit Koordinaten + Radius
  - Pro Zone: Aktionen bei Enter/Leave konfigurieren
  - Status-Übersicht: Welche Person ist in welcher Zone
  - Datenschutz-Hinweis + Opt-in pro User

---

## Batch 3: Spezial-Modi — Commits 8-9 (Features #7-#11)

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
- Gespeichert in `SpecialModeLog.previous_states` als JSON
- Bei Deaktivierung: States wiederherstellen
- Timeout: Falls vergessen, deaktiviert sich Modus nach `auto_deactivate_after_min`

### #7 Party-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

- **Aktionen bei Aktivierung:**
  - Beleuchtungsszene "Party" aktivieren (konfigurierbar)
  - Musik-Player starten (wenn konfiguriert)
  - Temperatur leicht senken (viele Personen → wärmer)
  - Quiet Hours deaktivieren (Party-Override)
- **Intelligente Features:**
  - Lautstärke-Monitoring: Wenn Lautstärke über Schwellwert → Notification "Es ist spät, Nachbarn?"
  - Auto-Deaktivierung: konfigurierbar
  - Aufräum-Modus nach Party: Licht 100%, Lüftung an
- **Konfigurierbare Einstellungen** (`PUT /api/security/modes/party/config`):
  - `light_scene`: JSON — Licht-Konfiguration pro Entity (Farbe, Helligkeit, Effekt)
  - `temperature_offset`: Float — Grad Celsius Absenkung (Default: -1.0)
  - `volume_threshold`: Integer 0-100 — Lautstärke-Warnschwelle (Default: 70)
  - `volume_warning_after`: String HH:MM — Ab wann Lautstärke-Warnung (Default: "22:00")
  - `auto_deactivate_min`: Integer — Auto-Aus nach X Minuten (Default: 240)
  - `cleanup_mode_enabled`: Boolean — Aufräum-Modus nach Party? (Default: true)
  - `cleanup_duration_min`: Integer — Dauer Aufräum-Modus (Default: 30)
  - `quiet_hours_override`: Boolean — Quiet Hours deaktivieren? (Default: true)
  - `auto_trigger_enabled`: Boolean — Automatischer Trigger? (Default: false)
  - `media_playlist`: String — Playlist/Source für Musik-Player (nullable)
  - `media_volume`: Float 0-1 — Start-Lautstärke (Default: 0.5)
- Entity-Zuordnung über generische API (siehe 0d): Lichter, Media-Player, Klima
- **Trigger:**
  - Manuell: Button in App
  - Auto (wenn `auto_trigger_enabled`): Gäste-Modus + Media-Player aktiv + abends
- **API:**
  - `POST /api/security/modes/party/activate`
  - `POST /api/security/modes/party/deactivate`
  - `GET /api/security/modes/party/status`
  - `GET /api/security/modes/party/config`
  - `PUT /api/security/modes/party/config`

### #8 Kino-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

- **Aktionen bei Aktivierung:**
  - Licht dimmen (über Transition, sanft!)
  - Rollläden schließen (Verdunklung)
  - DnD-Modus: Notifications stumm (außer CRITICAL/EMERGENCY)
  - Optional: Klima-Anpassung (kein Fan-Geräusch, leise Lüftung)
- **Intelligente Features:**
  - Auto-Aktivierung: Media-Player spielt Film (nicht Musik) + Abend
  - Auto-Deaktivierung: Media-Player wird pausiert/gestoppt
  - Pause-Erkennung: Bei Media-Pause → Licht auf Pause-Level, bei Resume → zurück auf Dim-Level
  - Room-Aware: Nur der Raum mit dem aktiven Media-Player wird verdunkelt
- **Konfigurierbare Einstellungen** (`PUT /api/security/modes/cinema/config`):
  - `dim_brightness`: Integer 0-100 — Licht-Level beim Film (Default: 5)
  - `pause_brightness`: Integer 0-100 — Licht-Level bei Pause (Default: 30)
  - `transition_sec`: Integer — Dimm-Übergang in Sekunden (Default: 3)
  - `close_covers`: Boolean — Rollläden schließen? (Default: true)
  - `dnd_enabled`: Boolean — DnD-Modus aktivieren? (Default: true)
  - `dnd_exceptions`: Liste — Welche Notification-Level durchlassen (Default: [critical, emergency])
  - `climate_quiet_mode`: Boolean — Leise Lüftung? (Default: false)
  - `auto_trigger_enabled`: Boolean — Automatischer Trigger? (Default: false)
  - `auto_deactivate_pause_min`: Integer — Minuten Pause bis Auto-Aus (Default: 5)
  - `room_id`: Integer — Standard-Raum (nullable, sonst Media-Player-Raum)
- Entity-Zuordnung über generische API (siehe 0d): Lichter, Rollläden, Media-Player, Klima
- **Trigger:**
  - Manuell: Button in App
  - Auto (wenn `auto_trigger_enabled`): Media-Player "playing" + Content-Type "movie"
- **API:**
  - `POST /api/security/modes/cinema/activate` → Body: `{room_id}` (optional)
  - `POST /api/security/modes/cinema/deactivate`
  - `GET /api/security/modes/cinema/status`
  - `GET /api/security/modes/cinema/config`
  - `PUT /api/security/modes/cinema/config`

### #9 Home-Office-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

- **Aktionen bei Aktivierung:**
  - Fokus-Beleuchtung: Kühles, helles Licht (hohe Farbtemperatur wenn tunable_white)
  - Klima: Komfort-Temperatur
  - DnD-Modus: Nur CRITICAL Notifications
  - Circadian Override: Büro-Beleuchtung statt Wohnraum-Kurve
  - Optional: "Bitte nicht stören" TTS wenn jemand den Raum betritt
- **Intelligente Features:**
  - Pausen-Erkennung: Keine Bewegung am Schreibtisch → "Mach mal Pause!"
  - Auto-Aktivierung: Werktag + bestimmter Raum + Kalender-Event
  - Auto-Deaktivierung: Feierabend (aus Kalender oder nach X Stunden)
  - Raum-bezogen: Nur der konfigurierte Office-Raum wird angepasst
- **Konfigurierbare Einstellungen** (`PUT /api/security/modes/home-office/config`):
  - `room_id`: Integer — Office-Raum (Pflicht)
  - `focus_brightness`: Integer 0-100 — Helligkeit (Default: 85)
  - `focus_color_temp`: Integer — Farbtemperatur in Kelvin (Default: 5000)
  - `comfort_temp`: Float — Zieltemperatur (Default: 21.5)
  - `dnd_enabled`: Boolean — DnD-Modus? (Default: true)
  - `dnd_exceptions`: Liste — Durchgelassene Level (Default: [critical, emergency])
  - `circadian_override`: Boolean — Circadian-Kurve überschreiben? (Default: true)
  - `break_reminder_enabled`: Boolean — Pausen-Erinnerung? (Default: true)
  - `break_reminder_interval_min`: Integer — Minuten ohne Bewegung (Default: 50)
  - `break_reminder_message_de/en`: String — Erinnerungstext (editierbar)
  - `dnd_tts_enabled`: Boolean — TTS bei Raum-Betreten? (Default: false)
  - `dnd_tts_message_de/en`: String — TTS-Text (editierbar)
  - `auto_trigger_enabled`: Boolean — Automatischer Trigger? (Default: false)
  - `auto_trigger_calendar_keywords`: Liste — Kalender-Keywords (Default: ["Home Office", "Homeoffice", "WFH"])
  - `auto_deactivate_after_hours`: Float — Max. Dauer (Default: 9.0)
- Entity-Zuordnung über generische API (siehe 0d): Lichter, Klima, Motion-Sensor, TTS-Speaker
- **Trigger:**
  - Manuell: Button in App
  - Auto (wenn `auto_trigger_enabled`): Kalender-Event mit passendem Keyword
- **API:**
  - `POST /api/security/modes/home-office/activate` → Body: `{room_id}` (optional wenn konfiguriert)
  - `POST /api/security/modes/home-office/deactivate`
  - `GET /api/security/modes/home-office/status`
  - `GET /api/security/modes/home-office/config`
  - `PUT /api/security/modes/home-office/config`

### #10 Nacht-Sicherungs-Modus
**Dateien:** `engines/special_modes.py`, `routes/security.py`

Automatische Absicherung für die Nacht — eng mit Sleep-Detection verknüpft.

- **Aktionen bei Aktivierung:**
  - Alle zugeordneten Türen verriegeln (Smart Locks)
  - Nacht-Beleuchtung: Orientierungslichter (konfigurierbar)
  - Alle zugeordneten Medien aus
  - Heizung auf Nacht-Temperatur
  - Fenster-Check: Notification wenn Fenster offen
  - Optional: HA `alarm_control_panel` auf "armed_night" setzen
- **Intelligente Features:**
  - Auto-Aktivierung: Sleep Detection (aus Phase 4) + Abend-Phase
  - Auto-Deaktivierung: Morgen-Phase oder Wake-Up-Manager Start
  - Bewegungs-Alerts: Bewegung im EG während Nacht → leise Notification
  - Nur konfigurierte Bereiche überwachen (nicht Schlafzimmer)
- **Konfigurierbare Einstellungen** (`PUT /api/security/modes/night-lockdown/config`):
  - `night_temp`: Float — Nacht-Temperatur (Default: 18.0)
  - `night_light_brightness`: Integer 0-100 — Orientierungslicht-Helligkeit (Default: 5)
  - `night_light_color_temp`: Integer — Farbtemperatur (Default: 2700, warmweiß)
  - `lock_doors`: Boolean — Türen verriegeln? (Default: true)
  - `turn_off_media`: Boolean — Medien ausschalten? (Default: true)
  - `window_check_enabled`: Boolean — Fenster-Check? (Default: true)
  - `window_check_notify_only`: Boolean — Nur benachrichtigen, nicht blockieren (Default: true)
  - `motion_alerts_enabled`: Boolean — Bewegungs-Alerts? (Default: true)
  - `motion_alert_rooms`: Liste von Room-IDs — Welche Räume überwachen (Default: EG-Räume)
  - `motion_alert_notification_target`: User-ID — Wer bekommt Alert (Default: Admin)
  - `alarm_panel_enabled`: Boolean — HA alarm_control_panel setzen? (Default: false)
  - `alarm_panel_entity`: String — Entity-ID des alarm_control_panel (nullable)
  - `auto_trigger_enabled`: Boolean — Automatischer Trigger? (Default: true)
  - `auto_trigger_time`: String HH:MM — Spätestens aktivieren um (Default: "23:00")
- Entity-Zuordnung über generische API (siehe 0d): Locks, Motion-Sensoren, Nachtlichter, Medien, Klima, Fenstersensoren, alarm_panel
- **Trigger:**
  - Manuell: Button in App
  - Auto (wenn `auto_trigger_enabled`): Sleep-Detection Event ODER `auto_trigger_time`
- **API:**
  - `POST /api/security/modes/night-lockdown/activate`
  - `POST /api/security/modes/night-lockdown/deactivate`
  - `GET /api/security/modes/night-lockdown/status`
  - `GET /api/security/modes/night-lockdown/config`
  - `PUT /api/security/modes/night-lockdown/config`

### #11 Notfall-Protokoll
**Dateien:** `engines/special_modes.py`, `routes/security.py`

Koordinierte Notfall-Reaktion — der "rote Knopf".

- **Notfall-Typen:**
  - **Feuer:** (automatisch aus #1, oder manuell)
  - **Medizinisch:** (nur manuell)
  - **Panik:** (manuell, unspezifisch)

- **Eskalations-Kette:**
  ```
  1. Sofort:    Alle Lichter an, Sirene (wenn siren.* Entity vorhanden), TTS-Durchsage
  2. +30s:      Push-Notification an alle User
  3. +60s:      Notfallkontakte benachrichtigen (E-Mail/Push)
  4. +5min:     Zweite Benachrichtigung an Notfallkontakte
  5. Fortlaufend: Notfall-Zustand bis manuell deaktiviert
  ```

- **Typ-spezifische Aktionen:**
  | Typ | Aktion |
  |-----|--------|
  | Feuer | Licht an, Rollläden hoch, Lüftung aus, Locks öffnen, TTS "Feueralarm" |
  | Medizinisch | Licht an, Haustür öffnen (Rettungsdienst), TTS "Medizinischer Notfall" |
  | Panik | Licht an, Sirene an (wenn vorhanden), TTS "Alarm" |

- **Konfigurierbare Einstellungen** (`PUT /api/security/emergency/config`):
  - `escalation_step1_delay_sec`: Integer — Verzögerung Schritt 2 (Default: 30)
  - `escalation_step2_delay_sec`: Integer — Verzögerung Schritt 3 (Default: 60)
  - `escalation_step3_delay_sec`: Integer — Verzögerung Schritt 4 (Default: 300)
  - `siren_duration_sec`: Integer — Sirenen-Dauer (Default: 300)
  - `tts_volume`: Integer 0-100 — TTS-Lautstärke (Default: 100)
  - `tts_message_fire_de/en`: String — TTS-Text Feuer (editierbar)
  - `tts_message_medical_de/en`: String — TTS-Text Medizinisch (editierbar)
  - `tts_message_panic_de/en`: String — TTS-Text Panik (editierbar)
  - `cancel_requires_pin`: Boolean — PIN zum Abbrechen? (Default: true)
  - `notify_emergency_contacts`: Boolean — Notfallkontakte benachrichtigen? (Default: true)
  - Per Notfall-Typ konfigurierbar welche Aktionen ausgeführt werden:
    - `fire_actions`: JSON — z.B. `{lights: true, covers: "open", hvac: "off", locks: "unlock"}`
    - `medical_actions`: JSON — z.B. `{lights: true, locks: "unlock_front"}`
    - `panic_actions`: JSON — z.B. `{lights: true, siren: true, locks: "lock"}`
- Entity-Zuordnung über generische API (siehe 0d): Sirene, Lichter, Locks, TTS-Speaker, Rollläden, Lüftung
- **Backend:**
  - `EmergencyProtocol`-Klasse in `engines/special_modes.py`
  - `trigger(emergency_type, source="manual")` → Startet Eskalationskette
  - `cancel(pin)` → Bricht ab (wenn `cancel_requires_pin`)
  - Nutzt bestehenden NotificationManager für Eskalation
  - Sirene direkt über HA `siren.*` Entity (kein eigenes Alarm-Management)
  - Timer-Thread für Eskalations-Schritte
- **API:**
  - `POST /api/security/emergency/trigger` → Body: `{type, source}`
  - `POST /api/security/emergency/cancel` → Body: `{pin}`
  - `GET /api/security/emergency/status` → Aktiver Notfall?
  - `GET /api/security/emergency/config` → Konfiguration
  - `PUT /api/security/emergency/config` → Einstellungen ändern
  - `GET /api/security/emergency/contacts` → Notfallkontakte
  - `POST /api/security/emergency/contacts` → Kontakt hinzufügen
  - `PUT /api/security/emergency/contacts/<id>` → Kontakt bearbeiten
  - `DELETE /api/security/emergency/contacts/<id>` → Kontakt löschen

- **Frontend:**
  - Notfall-Button auf Sicherheits-Seite (Rot, prominent)
  - Notfall-Typ Auswahl beim Triggern
  - Aktiver Notfall: Countdown, Eskalations-Stufe, Cancel-Button mit PIN
  - Notfallkontakte-Verwaltung

---

## Batch 4: Dashboard & Finalisierung — Commit 10 (Feature #6)

### #6 Sicherheits-Dashboard
**Dateien:** `routes/security.py`, Frontend

Zentrale Übersicht aller Sicherheits-Features.

- **Backend:**
  - Aggregiert alle Security-Daten:
    - HA-Alarm-Status (read-only, wenn `alarm_control_panel.*` Entity vorhanden)
    - Offene Fenster/Türen (binary_sensor)
    - Lock-Status (alle Schlösser)
    - Letzte Security-Events (Timeline)
    - Aktive Spezial-Modi
    - Kamera-Status (online/offline)
    - Geo-Fence Status (Personen in Zonen)
    - Feuer/Wasser-Sensor Status
  - API: `GET /api/security/dashboard` → Aggregierte Übersicht
  - API: `GET /api/security/events` → Event-Log (paginiert, filterbar)
  - API: `GET /api/security/events/stats` → Statistiken (Events pro Woche/Typ)

- **Frontend:**
  - Neue Seite "Sicherheit" im Hauptmenü
  - **6 Tabs:**
    1. **Dashboard** — Übersicht aller Sicherheits-Features
    2. **Zutritt** — Locks, Codes, Protokoll (Feature #4)
    3. **Kameras** — Snapshots, Live-Status (Feature #3)
    4. **Geo-Fence** — Zonen, Personen-Status (Feature #5)
    5. **Spezial-Modi** — Alle 5 Modi aktivieren/konfigurieren (#7-#11)
    6. **Einstellungen** — Feature-Flags, Notfallkontakte, Konfiguration

  - **Dashboard-Tab Layout:**
    ```
    ┌──────────────────────────────────────────┐
    │  HA-Alarm: armed_home (read-only)        │  ← nur wenn alarm_control_panel existiert
    ├────────────┬────────────┬────────────────┤
    │ Türen      │ Schlösser  │ Kameras        │
    │ 2/5 offen  │ 3/3 zu    │ 2/2 online     │
    ├────────────┼────────────┼────────────────┤
    │ Rauch/CO   │ Wasser     │ Geo-Fence      │
    │ alle OK    │ alle OK    │ 2/3 zuhause    │
    ├────────────┴────────────┴────────────────┤
    │ Letzte Ereignisse                         │
    │  10:30 Haustür entsperrt (Max, Code)     │
    │  09:15 Nacht-Sicherung deaktiviert       │
    │  08:45 Alle Türen verriegelt (Auto)      │
    ├──────────────────────────────────────────┤
    │ Aktive Modi: Keine                        │
    └──────────────────────────────────────────┘
    ```

### Version & Dokumentation
- `version.py`: VERSION = "0.8.0", CODENAME = "Phase 5 - Security & Modes"
- `README.md`: Phase 5 auf "fertig" setzen, Feature-Liste aktualisieren
- `CHANGELOG.md`: Alle 11 neuen Features dokumentieren
- Translations: `de.json` + `en.json` aktualisieren

### Neue Route-Registrierung
- `routes/__init__.py`: `security_bp` registrieren
- `app.py`: Security-Blueprint importieren

### Scheduler-Tasks

Sicherheits-Features sind überwiegend **Event-basiert** (über EventBus), nicht Scheduler-basiert.
Das ist ein Unterschied zu Phase 4 — Sicherheit muss sofort reagieren, nicht alle 5 Min.

| Task | Intervall | Enthält | Features |
|------|-----------|---------|----------|
| `security_monitor` | Event-basiert | FireResponse + WaterLeak (state_changed Handler) | #1, #2 |
| `geofence_check` | 60s | GeoFenceManager | #5 |
| `access_autolock` | 60s | Auto-Lock Timer prüfen | #4 |
| `special_mode_check` | 5 Min | Timeout-Check für aktive Modi | #7-#11 |
| `camera_cleanup` | 24h | Alte Snapshots löschen (Retention) | #3 |

### EventBus-Registrierungen (neu)

| Event | Sender | Empfänger |
|-------|--------|-----------|
| `state_changed` | StateLogger | FireResponse, WaterLeak, AccessControl |
| `emergency.fire` | FireResponseManager | EmergencyProtocol, SecurityCameraManager |
| `emergency.co` | FireResponseManager | EmergencyProtocol, SecurityCameraManager |
| `emergency.water_leak` | WaterLeakManager | NotificationManager, SecurityCameraManager |
| `emergency.triggered` | EmergencyProtocol | SecurityCameraManager, NotificationManager |
| `access.unlocked` | AccessControlManager | SecurityEvent Logging |
| `access.locked` | AccessControlManager | SecurityEvent Logging |
| `access.unknown` | AccessControlManager | NotificationManager, SecurityCameraManager |
| `access.jammed` | AccessControlManager | NotificationManager |
| `presence.mode_changed` | PresenceModeManager | GeoFenceManager (Sync) |
| `sleep.detected` | SleepDetector | NightLockdown (Auto-Aktivierung) |
| `wake.detected` | WakeUpManager | NightLockdown (Auto-Deaktivierung) |
| `mode.activated` | SpecialModeBase | NotificationManager, Dashboard |
| `mode.deactivated` | SpecialModeBase | NotificationManager, Dashboard |

---

## Zusammenfassung

| Batch | Features | Commits | Neue Dateien | Geänderte Dateien |
|-------|----------|---------|-------------|-------------------|
| 0 | Infrastruktur | 1-3 | engines/ (4 Dateien), routes/security.py | models.py, version.py |
| 1 | #1, #2, #3 | 4-5 | — | engines/fire_water.py, engines/camera_security.py, routes/security.py |
| 2 | #4, #5 | 6-7 | — | engines/access_control.py, routes/security.py |
| 3 | #7-#11 | 8-9 | — | engines/special_modes.py, routes/security.py |
| 4 | #6 + Finalisierung | 10 | — | routes/security.py, app.jsx, version.py, README.md, de.json, en.json |

**Geschätzte Änderungen:**
- 5 neue Dateien: `engines/` (4 Module) + `routes/security.py`
- 8 neue DB-Models (inkl. `FeatureEntityAssignment`) + 3 neue Spalten + 2 neue Enums
- 11 Feature-Flags in SystemSettings
- ~10 bestehende Dateien modifiziert
- ~40 neue API-Endpoints (inkl. generische Entity-Management API)
- 5 Scheduler-Tasks (+ Event-basierte Handler)
- Frontend: 1 neue Seite "Sicherheit" mit 6 Tabs in app.jsx
- **Vollständige User-Steuerbarkeit:** Alle Entity-Zuordnungen + Einstellungen per CRUD-API konfigurierbar
- Graceful Degradation für alle Sensor-abhängigen Features
- State-Restore-Mechanismus für Spezial-Modi
- HA-Alarm read-only Integration (alarm_control_panel, falls vorhanden)
- **4 Batches, ~10 Commits**
