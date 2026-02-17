# MindHome Phase 7 — Implementierungsplan
# "Jarvis Routinen & Tagesstruktur" (9 Features)

> **Stand:** 2026-02-17
> **Zielversion:** v0.9.5 → v1.0.0
> **Basis:** Assistant v0.9.4 (Phase 6 fertig)
> **Betroffene Seite:** Nur Assistant-Server (PC 2)
> **Zu implementieren:** 9 Features

---

## Strategie

Phase 7 wird in **4 Batches** mit **~9 Commits** implementiert:

1. **Config + Raum-Profile** (room_profiles.yaml, saisonale Config)
2. **Tagesstruktur** (Morning Briefing, Gute-Nacht, Begrüßung)
3. **Szenen & Modi** (Szenen-Intelligenz, Gäste-Modus)
4. **Abwesenheit & Kontext** (Willkommen/Abschied, Abwesenheits-Log, saisonale Anpassung)

### Commit-Plan (~9 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v0.9.5 + Phase 7 plan` | 0 | Version bump |
| 2 | `feat(config): Add room_profiles.yaml + seasonal config` | 0 | #7 Config |
| 3 | `feat(routines): Add routine_engine.py — morning briefing + good night` | 1 | #1, #3 |
| 4 | `feat(personality): Add contextual greetings` | 1 | #2 |
| 5 | `feat(brain): Add scene intelligence prompts` | 2 | #5 |
| 6 | `feat(personality): Add guest mode` | 2 | #6 |
| 7 | `feat(proactive): Add arrival/departure + absence summary` | 3 | #4, #8 |
| 8 | `feat(context): Add room profiles + seasonal awareness` | 3 | #7, #9 |
| 9 | `docs: Mark Phase 7 complete` | 3 | Docs |

---

## Batch 0: Config & Infrastruktur (Commits 1-2)

### 0a: Version Bump

**Datei:** `config/settings.yaml`
```yaml
assistant:
  version: "0.9.5"
```

### 0b: room_profiles.yaml

**Neue Datei:** `config/room_profiles.yaml`

```yaml
rooms:
  wohnzimmer:
    type: living
    default_temp: 22
    default_light: "warmweiss"
    default_brightness: 70
    alerts: []

  schlafzimmer:
    type: bedroom
    default_temp: 18
    default_light: "warmweiss"
    default_brightness: 30
    alerts: ["co2_hoch"]

  kueche:
    type: kitchen
    default_temp: 20
    default_light: "neutralweiss"
    default_brightness: 100
    alerts: ["ofen_lange_an"]

  buero:
    type: office
    default_temp: 21
    default_light: "tageslicht"
    default_brightness: 80
    alerts: ["keine_pause_3h"]

  bad:
    type: bathroom
    default_temp: 23
    default_light: "warmweiss"
    default_brightness: 60
    alerts: []
```

### 0c: Saisonale + Routinen-Config in settings.yaml

```yaml
routines:
  morning_briefing:
    enabled: true
    trigger: "first_motion_after_night"
    modules:
      - greeting
      - weather
      - calendar
      - energy
      - house_status
    weekday_style: "kurz"
    weekend_style: "ausfuehrlich"

  good_night:
    enabled: true
    triggers: ["gute nacht", "ich gehe schlafen", "schlaf gut"]
    checks:
      - windows
      - doors
      - alarm
      - lights
    actions:
      - lights_off
      - heating_night
      - covers_down

  seasonal:
    enabled: true
    # Automatisch aus HA weather + Sonnendaten
```

---

## Batch 1: Tagesstruktur (Commits 3-4)

### Feature 7.1: Morning Briefing + Feature 7.3: Gute-Nacht-Routine

**Neue Datei:** `assistant/routine_engine.py`

Zentrale Routinen-Engine die Morgen-/Abend-Routinen orchestriert.

- Morning Briefing:
  - Trigger: Erste Bewegung nach Nachtmodus (via proactive.py Event)
  - Bausteine: Begrüßung, Wetter, Kalender, Energie, Haus-Status
  - Weekday kurz (2-3 Sätze), Weekend ausführlich
  - Begleit-Aktionen: Rolladen hoch, Licht sanft an

- Gute-Nacht-Routine:
  - Trigger: Intent-Erkennung ("Gute Nacht" etc.)
  - Ablauf: Morgen-Vorschau → Sicherheits-Check → Haus runterfahren
  - Rückfrage bei offenen Fenstern/Türen

### Feature 7.2: Kontextuelle Begrüßung

**Datei:** `personality.py`

Neue Methode `generate_greeting()`:
- Kontext-Inputs: Wochentag, Uhrzeit, Wetter, Feiertag, Urlaub-Rückkehr
- History der letzten 20 Begrüßungen in Redis
- LLM-generiert mit Kontext → immer frisch

---

## Batch 2: Szenen & Modi (Commits 5-6)

### Feature 7.5: Szenen-Intelligenz

**Datei:** `brain.py` / System Prompt

Erweiterter System Prompt für situatives Verständnis:
- "Mir ist kalt" → Heizung +2°C im aktuellen Raum
- "Zu hell" → Rolladen oder Licht dimmen
- "Romantischer Abend" → Szene zusammenstellen
- Kein neues Modul, nur bessere Prompt-Engineering

### Feature 7.6: Gäste-Modus

**Dateien:** `personality.py`, `brain.py`

- Trigger: "Ich hab Besuch" oder activity.py Gäste-Erkennung
- Einschränkungen: Keine persönlichen Infos, formeller Ton
- Ende: "Zurück zum Normalbetrieb?"
- Guest WLAN vorschlagen

---

## Batch 3: Abwesenheit & Kontext (Commits 7-8)

### Feature 7.4: Abschied/Willkommen-Modus

**Datei:** `proactive.py`

- Verlassen: Sicherheits-Vorschlag + Verabschiedung
- Rückkehr: Erweitert bestehenden Report (Vorheizen, Licht, Events)

### Feature 7.8: Abwesenheits-Zusammenfassung

**Datei:** `proactive.py`

- Event-Log während Abwesenheit sammeln (Redis List)
- Bei Rückkehr: Relevanz-Filter + LLM-Zusammenfassung
- "Während du weg warst: Postbote 14:23, kurzer Regen, sonst ruhig."

### Feature 7.7: Raum-Intelligenz

**Datei:** `context_builder.py`

- room_profiles.yaml laden und in Kontext einbeziehen
- Raum-Profil beeinflusst Default-Werte bei Aktionen

### Feature 7.9: Saisonale Routine-Anpassung

**Datei:** `context_builder.py`

- Saisonale Daten: Sonnenauf-/untergang, Tageslänge, Temperatur-Trend
- System-Prompt erhält saisonalen Kontext
- Briefing-Inhalte passen sich an (Sommer: UV, Winter: Glatteis)

---

## Geänderte/Neue Dateien

### Neue Dateien:
| Datei | Beschreibung |
|-------|-------------|
| `assistant/routine_engine.py` | Morning Briefing, Gute-Nacht, Routinen-Orchestrierung |
| `config/room_profiles.yaml` | Raum-Definitionen mit Defaults |

### Geänderte Dateien:
| Datei | Änderung |
|-------|---------|
| `config/settings.yaml` | Routinen-Config, saisonale Settings |
| `personality.py` | Kontextuelle Begrüßung, Gäste-Erweiterung |
| `brain.py` | Szenen-Intelligenz Prompts, Routine-Integration |
| `proactive.py` | Abschied, Abwesenheits-Log, Morning-Trigger |
| `context_builder.py` | Raum-Profile, saisonale Daten |
