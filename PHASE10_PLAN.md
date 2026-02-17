# MindHome Phase 10 — Implementierungsplan
# "Jarvis Multi-Room & Kommunikation" (5 Features)

> **Stand:** 2026-02-17
> **Version:** v1.0.0 → v1.1.0
> **Basis:** Assistant v1.0.0 (Phase 9 fertig)
> **Status:** IN ARBEIT

---

## Strategie

Phase 10 wird in **3 Batches** mit **~5 Commits** implementiert:

1. **Multi-Room & Messaging** (Room Presence, TTS Routing, Person Delegation)
2. **Vertrauensstufen** (Person-basierte Berechtigungen)
3. **Diagnostik & Wartung** (Sensor-Watchdog, Maintenance-Reminders)

### Commit-Plan (~5 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v1.0.1 + Phase 10 plan` | 0 | Version bump |
| 2 | `feat(room): Add multi-room presence + TTS routing` | 1 | #10.1 |
| 3 | `feat(delegation): Add person messaging + delegation intent` | 1 | #10.2 |
| 4 | `feat(trust): Add per-person trust levels` | 2 | #10.3 |
| 5 | `feat(diag): Add diagnostics + maintenance assistant` | 3 | #10.4, #10.5 |

---

## Batch 1: Multi-Room & Messaging (Commits 2-3)

### Feature 10.1: Multi-Room Presence

**Datei:** `assistant/context_builder.py` — Raum-Tracking erweitern

- `_build_room_presence()` — Tracked alle Personen in allen Raeumen
- Motion-Sensoren + letzte Interaktion = Raum bestimmen
- `room_history` — Letzte N Raum-Wechsel pro Person (Redis-basiert)
- Kontext erhaelt `persons_by_room` Dict

**Datei:** `assistant/function_calling.py` — TTS-Routing

- `send_notification()` erhaelt `room` Parameter
- `_find_speaker_in_room(room)` — Findet Speaker im Zielraum
- TTS-Output gezielt an den richtigen Speaker
- Wenn kein Raum → aktueller Raum des Users

**Config:** `settings.yaml` — Room-Speaker-Mapping

```yaml
multi_room:
  enabled: true
  room_speakers:
    wohnzimmer: "media_player.wohnzimmer_speaker"
    schlafzimmer: "media_player.schlafzimmer_speaker"
    kueche: "media_player.kueche_speaker"
  room_motion_sensors:
    wohnzimmer: "binary_sensor.wohnzimmer_motion"
    schlafzimmer: "binary_sensor.schlafzimmer_motion"
    kueche: "binary_sensor.kueche_motion"
  presence_timeout_minutes: 15
```

### Feature 10.2: Delegieren an Personen

**Datei:** `assistant/brain.py` — Delegations-Intent

- `_classify_intent()` erkennt Delegations-Muster:
  - "Sag Lisa dass...", "Frag Max ob..."
  - "Teile [Person] mit dass...", "Gib [Person] Bescheid"
- `_handle_delegation()` — Extrahiert Empfaenger + Nachricht
- Routing: Person zu Hause → TTS in deren Raum, weg → Push

**Datei:** `assistant/function_calling.py` — Neues Tool

- `send_message_to_person` — Tool-Definition:
  - person: Name des Empfaengers
  - message: Nachricht
  - urgency: low/medium/high
- Routing-Logik: Raum-Lookup → Speaker oder Push-Notification

**Config:** `settings.yaml` — Person-Geraete-Mapping

```yaml
persons:
  profiles:
    lisa:
      notify_service: "notify.lisa_phone"
      preferred_room: "schlafzimmer"
    max:
      notify_service: "notify.max_phone"
      preferred_room: "buero"
```

---

## Batch 2: Vertrauensstufen (Commit 4)

### Feature 10.3: Vertrauensstufen

**Datei:** `assistant/autonomy.py` — Person-basierte Berechtigungen

- `TRUST_LEVELS` Dict:
  - 0 (Gast): Licht, Temperatur, Musik — nur eigener Raum
  - 1 (Mitbewohner): Alles ausser Sicherheit
  - 2 (Owner): Voller Zugriff
- `get_trust_level(person)` — Gibt Trust-Level zurueck
- `can_person_act(person, action_type)` → bool
- `TRUST_PERMISSIONS` — Welcher Level fuer welche Aktion noetig

**Datei:** `assistant/function_calling.py` — Pre-Check

- `execute()` prueft Trust-Level VOR Ausfuehrung
- Gaeste koennen keine Tueren oeffnen/schliessen
- Mitbewohner keine Alarm-Aenderungen

**Config:** `settings.yaml` — Person-Trust-Mapping

```yaml
trust_levels:
  default: 0  # Gaeste
  persons:
    max: 2     # Owner
    lisa: 1    # Mitbewohner
  guest_allowed_actions:
    - set_light
    - set_climate
    - play_media
  security_actions:
    - lock_door
    - set_alarm
    - set_presence_mode
```

---

## Batch 3: Diagnostik & Wartung (Commit 5)

### Feature 10.4: Selbst-Diagnostik

**Neue Datei:** `assistant/diagnostics.py`

- `DiagnosticsEngine` — Sensor-Watchdog
- `check_entities()` — Prueft HA-Entities auf Probleme:
  - Offline-Entities (state == "unavailable" seit > X Min)
  - Batterie-Warnungen (< 20%)
  - Stale Sensoren (kein Update seit > Schwellwert)
- `get_system_status()` — Vollstaendiger Status-Report
- Meldung ueber proactive.py (nur bei echten Problemen)
- Cooldown: Gleiche Warnung nicht doppelt melden

### Feature 10.5: Wartungs-Assistent

**Neue Datei:** `config/maintenance.yaml`

```yaml
tasks:
  - name: "Rauchmelder testen"
    interval_days: 180
    last_done: null
    priority: medium
  - name: "Heizungsfilter wechseln"
    interval_days: 90
    last_done: null
    priority: low
  - name: "Wasserfilter wechseln"
    interval_days: 60
    last_done: null
    priority: low
```

**Datei:** `assistant/diagnostics.py` — Wartungs-Check

- `check_maintenance()` — Prueft faellige Wartungsaufgaben
- `complete_task(name)` — Markiert Aufgabe als erledigt
- Sanfte Delivery: LOW Priority, nur wenn User entspannt
- "Nebenbei: Rauchmelder koennten mal getestet werden."

---

## Neue/Geaenderte Dateien

### Neue Dateien:
| Datei | Beschreibung |
|-------|-------------|
| `assistant/diagnostics.py` | Sensor-Watchdog + Wartungs-Assistent |
| `config/maintenance.yaml` | Wartungs-Kalender |

### Geaenderte Dateien:
| Datei | Aenderung |
|-------|---------|
| `config/settings.yaml` | Version bump, Multi-Room, Persons, Trust-Config |
| `assistant/context_builder.py` | Room-Presence-Tracking |
| `assistant/function_calling.py` | TTS-Routing, send_message_to_person, Trust-PreCheck |
| `assistant/autonomy.py` | Person-basierte Trust-Levels |
| `assistant/brain.py` | Delegations-Intent, Diagnostik-Integration |
| `assistant/proactive.py` | Diagnostik- + Wartungs-Events |
| `assistant/main.py` | Neue API-Endpoints |
