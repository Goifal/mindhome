# MindHome — Dein Zuhause denkt mit!

[English version below](#english)

<p align="center">
  <img src="addon/rootfs/opt/mindhome/static/icon.png" alt="MindHome Logo" width="128">
</p>

<p align="center">
  <strong>v0.6.17</strong> · Phase 3.5 – Stabilisierung & Refactoring<br>
  ~130 Features · 14 Domain-Plugins · 100% lokal
</p>

---

## Was ist MindHome?

MindHome ist ein KI-basiertes Home Assistant Add-on, das deine Gewohnheiten lernt und dein Zuhause intelligent steuert. Alles läuft **lokal** auf deinem Rechner — keine Cloud, keine externen Server.

## Aktueller Stand

| Phase | Beschreibung | Features | Status |
|-------|-------------|----------|--------|
| **Phase 1** | Fundament + Datenschutz | ~27 | ✅ Fertig |
| **Phase 2** | Erste KI + Lernphasen | ~68 | ✅ Fertig |
| **Phase 3** | Alle Domains intelligent | ~30 | ✅ Fertig |
| **Phase 3.5** | Stabilisierung & Refactoring | — | ✅ Fertig |
| **Phase 4** | Smarte Features + Gesundheit | 24 | 📋 Geplant |
| **Phase 5** | Sicherheit + Spezial-Modi | 13 | 📋 Geplant |
| **Phase 6** | Premium Frontend + Gamification | 12 | 📋 Geplant |
| **Phase 7** | System & Integration | 7 | 📋 Geplant |

## Features

### Phase 1 — Fundament ✅
- Ein-Klick-Installation als HA Add-on
- Automatische Geräte- und Raumerkennung
- 14 Domain-Plugins (Licht, Klima, Rollläden, Presence, Medien, Türen/Fenster, Bewegung, Energie, Wetter, Schlösser, Steckdosen, Luftqualität, Lüftung, Solar PV)
- Onboarding-Wizard mit geführter Einrichtung
- Personen-Manager mit Rechte-System (Admin/Benutzer)
- Quick Actions (Alles aus, Ich gehe, Ich bin zurück, Gäste, Not-Aus)
- Datenschutz-Dashboard & Privatsphäre-Modus pro Raum
- Dark/Light Mode, Einfache/Ausführliche Ansicht, Deutsch/Englisch
- Responsive (Desktop + Handy)
- Echtzeit-Verbindung zu HA (WebSocket + REST)
- Offline-Fallback & Backup/Restore

### Phase 2 — Erste Intelligenz 🧠 ✅
- KI-Mustererkennung (Pattern Engine)
- 3-stufiges Lernsystem (Beobachten → Vorschlagen → Automatisieren)
- Vorhersagen mit Bestätigung/Ablehnung
- Anomalie-Erkennung mit Kontext (Schicht, Gäste, Feiertag)
- Benachrichtigungssystem (Push, TTS, E-Mail)
- Manuelle Regeln & Pattern-Ausschlüsse
- Wochenbericht & Lernstatistiken
- Geräte-Gesundheit & Watchdog
- Automatisierungs-Engine mit Konflikt-Erkennung

### Phase 3 — Alle Domains intelligent ✅
- Tagesphasen (Morgen, Tag, Abend, Nacht) mit Sonnenstand
- Schichtkalender & Ferien-Kalender
- Anwesenheits-Modi & Gäste-Verwaltung
- Raum-Szenen (automatisch erkennen + manuell anlegen)
- Energie-Monitoring & Standby-Erkennung
- Sensor-Fusion & Schwellwerte
- Ruhezeiten verknüpft mit Tagesphasen
- Plugin-Konflikte & Kontext-Tags
- Aktivitäten-Log & Audit Trail

### Phase 3.5 — Stabilisierung ✅
- Modulare Blueprint-Architektur (13 Route-Module)
- Infrastruktur-Module (db.py, event_bus.py, task_scheduler.py, helpers.py, version.py)
- Systematische Bug-Fixes & Code-Qualität

## MindHome Assistant (KI-Sprachassistent)

MindHome Assistant ist ein separater, lokaler KI-Sprachassistent der auf einem zweiten PC laeuft und MindHome eine Stimme gibt.

| Komponente | PC | Technologie | Port |
|---|---|---|---|
| **MindHome Add-on** | PC 1 (HAOS) | Flask, SQLite | 8099 |
| **MindHome Assistant** | PC 2 (Ubuntu) | FastAPI, Ollama, ChromaDB, Redis | 8200 |

### Features
- Lokale LLM-Inference (Qwen 3.5 via Ollama)
- Function Calling (Licht, Klima, Szenen, Alarme, Schloesser)
- 3-Schichten-Gedaechtnis (Working + Episodic + Semantic)
- Proaktive Meldungen (Morgen-Briefing, Ankunft, Warnungen)
- Stimmungserkennung & adaptives Verhalten
- Butler-Persoenlichkeit mit Tageszeit-Anpassung
- Autonomie-Level 1-5 (Assistent bis Autopilot)

### Installation (Assistant-PC)
```bash
cd assistant/
chmod +x install.sh
./install.sh
```

Siehe [docs/PROJECT_MINDHOME_ASSISTANT.md](docs/PROJECT_MINDHOME_ASSISTANT.md) fuer die vollstaendige Dokumentation.

### ESPHome Voice Satellites

MindHome unterstuetzt ESP32-basierte Sprach-Satellites fuer die Spracheingabe in jedem Raum.

| Geraet | Mikrofon | Einsatz | Preis |
|---|---|---|---|
| **ReSpeaker XVF3800** | 4x MEMS + DSP | Hauptraeume (Kueche, Wohnzimmer) | ~55 EUR |
| **M5Stack Atom Echo** | 1x PDM | Nebenraeume (Flur, Bad) | ~12 EUR |

ESPHome-Konfigurationen liegen unter `esphome/`. Siehe [docs/SPEAKER_RECOGNITION.md](docs/SPEAKER_RECOGNITION.md) fuer Details.

---

## Architektur

```
mindhome/
├── repository.yaml              # HA Add-on Store
├── README.md
├── shared/                      # Gemeinsame Schemas & Konstanten
│   ├── constants.py
│   └── schemas/
│       ├── chat_request.py
│       ├── chat_response.py
│       └── events.py
├── assistant/                   # MindHome Assistant (PC 2)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── install.sh
│   ├── .env.example
│   ├── config/settings.yaml
│   └── assistant/               # Python-Package (90 Module)
│       ├── main.py              # FastAPI Server
│       ├── brain.py             # Orchestrator
│       ├── personality.py       # Persoenlichkeits-Engine
│       ├── function_calling.py  # 10 HA-Tools
│       ├── memory.py            # 3-Schichten-Gedaechtnis
│       └── ...                  # 17 weitere Module
├── addon/
│   ├── config.yaml              # Add-on Konfiguration
│   ├── build.yaml               # Docker Build
│   └── rootfs/opt/mindhome/     # Anwendungscode
│       ├── run.sh               # Startskript
│       ├── requirements.txt     # Python-Abhängigkeiten
│       ├── app.py               # Flask App + Startup
│       ├── version.py           # Zentrale Versionierung
│       ├── db.py                # Datenbank-Verbindung
│       ├── event_bus.py         # Event-System
│       ├── task_scheduler.py    # Hintergrund-Tasks
│       ├── helpers.py           # Hilfsfunktionen
│       ├── models.py            # SQLAlchemy-Modelle + Migrationen
│       ├── init_db.py           # Datenbank-Initialisierung
│       ├── ha_connection.py     # HA WebSocket + REST API
│       ├── pattern_engine.py    # KI-Mustererkennung
│       ├── automation_engine.py # Automatisierungs-Engine
│       ├── routes/              # API-Routen (13 Blueprints)
│       │   ├── system.py        # System, Settings, Backup, Health
│       │   ├── devices.py       # Geräte & Räume
│       │   ├── patterns.py      # Muster & Regeln
│       │   ├── automation.py    # Automationen & Vorhersagen
│       │   ├── notifications.py # Benachrichtigungen & TTS
│       │   ├── energy.py        # Energie-Monitoring
│       │   ├── presence.py      # Anwesenheit & Gäste
│       │   ├── scenes.py        # Szenen-Verwaltung
│       │   ├── phases.py        # Tagesphasen
│       │   ├── persons.py       # Personen & Schichtpläne
│       │   ├── domains.py       # Domain-Verwaltung
│       │   ├── stats.py         # Statistiken & Reports
│       │   └── ha_proxy.py      # HA-Proxy Endpunkte
│       ├── domains/             # 14 Domain-Plugins
│       │   ├── base.py          # Basis-Klasse
│       │   ├── light.py         # Licht
│       │   ├── climate.py       # Klima/Heizung
│       │   ├── cover.py         # Rollläden
│       │   ├── presence.py      # Anwesenheit
│       │   ├── media.py         # Medien
│       │   ├── door_window.py   # Türen/Fenster
│       │   ├── motion.py        # Bewegung
│       │   ├── energy.py        # Energie
│       │   ├── weather.py       # Wetter
│       │   ├── lock.py          # Schlösser
│       │   ├── switch.py        # Steckdosen
│       │   ├── air_quality.py   # Luftqualität
│       │   ├── ventilation.py   # Lüftung
│       │   └── solar.py         # Solar PV
│       ├── translations/        # Übersetzungen
│       │   ├── de.json
│       │   └── en.json
│       └── static/frontend/     # React Frontend
│           └── app.jsx          # Single-File JSX (~6600 Zeilen)
```

## Installation

### Voraussetzungen
- Home Assistant OS (HAOS)
- Mindestens 4GB RAM empfohlen

### Schritte
1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store**
2. Oben rechts: **⋮ → Repositories → URL hinzufügen:**
   ```
   https://github.com/Goifal/mindhome
   ```
3. **MindHome** im Store suchen und **Installieren** klicken
4. Add-on starten
5. Im Seitenmenü auf **MindHome** klicken
6. Der Onboarding-Wizard führt dich durch die Einrichtung

## Technologie

- **Backend:** Python 3.12, Flask, SQLAlchemy, SQLite
- **Frontend:** React (JSX), Babel 7, CSS Custom Properties
- **Verbindung:** Home Assistant REST API + WebSocket
- **Container:** Docker (Alpine Linux)

## Datenschutz

Alle Daten werden **ausschließlich lokal** gespeichert. MindHome sendet keine Daten an externe Server. Du hast volle Kontrolle über alle gesammelten Daten und kannst sie jederzeit einsehen und löschen.

---

<a name="english"></a>

# MindHome — Your Home Thinks Ahead!

<p align="center">
  <strong>v0.6.17</strong> · Phase 3.5 – Stabilization & Refactoring<br>
  ~130 Features · 14 Domain Plugins · 100% local
</p>

## What is MindHome?

MindHome is an AI-powered Home Assistant add-on that learns your habits and intelligently controls your home. Everything runs **locally** on your machine — no cloud, no external servers.

## Current Status

| Phase | Description | Features | Status |
|-------|-----------|----------|--------|
| **Phase 1** | Foundation + Privacy | ~27 | ✅ Complete |
| **Phase 2** | First AI + Learning | ~68 | ✅ Complete |
| **Phase 3** | All Domains Intelligent | ~30 | ✅ Complete |
| **Phase 3.5** | Stabilization & Refactoring | — | ✅ Complete |
| **Phase 4** | Smart Features + Health | 24 | 📋 Planned |
| **Phase 5** | Security + Special Modes | 13 | 📋 Planned |
| **Phase 6** | Premium Frontend + Gamification | 12 | 📋 Planned |
| **Phase 7** | System & Integration | 7 | 📋 Planned |

## Features

### Phase 1 — Foundation ✅
- One-click installation as HA add-on
- Automatic device and room discovery
- 14 domain plugins (Light, Climate, Covers, Presence, Media, Doors/Windows, Motion, Energy, Weather, Locks, Smart Plugs, Air Quality, Ventilation, Solar PV)
- Onboarding wizard with guided setup
- People manager with role system (Admin/User)
- Quick Actions (All off, Leaving, Arriving, Guests, Emergency Stop)
- Data privacy dashboard & per-room privacy mode
- Dark/Light mode, Simple/Advanced view, German/English
- Responsive (Desktop + Mobile)
- Real-time connection to HA (WebSocket + REST)
- Offline fallback & Backup/Restore

### Phase 2 — First Intelligence 🧠 ✅
- AI pattern recognition (Pattern Engine)
- 3-stage learning system (Observe → Suggest → Automate)
- Predictions with accept/reject workflow
- Anomaly detection with context (shift, guests, holidays)
- Notification system (Push, TTS, Email)
- Manual rules & pattern exclusions
- Weekly report & learning statistics
- Device health & watchdog
- Automation engine with conflict detection

### Phase 3 — All Domains Intelligent ✅
- Day phases (Morning, Day, Evening, Night) with sun position
- Shift calendar & school vacation calendar
- Presence modes & guest management
- Room scenes (auto-detect + manual creation)
- Energy monitoring & standby detection
- Sensor fusion & thresholds
- Quiet hours linked to day phases
- Plugin conflicts & context tags
- Activity log & audit trail

### Phase 3.5 — Stabilization ✅
- Modular Blueprint architecture (13 route modules)
- Infrastructure modules (db.py, event_bus.py, task_scheduler.py, helpers.py, version.py)
- Systematic bug fixes & code quality

## MindHome Assistant (AI Voice Assistant)

MindHome Assistant is a separate, local AI voice assistant running on a second PC that gives MindHome a voice.

| Component | PC | Technology | Port |
|---|---|---|---|
| **MindHome Add-on** | PC 1 (HAOS) | Flask, SQLite | 8099 |
| **MindHome Assistant** | PC 2 (Ubuntu) | FastAPI, Ollama, ChromaDB, Redis | 8200 |

### Installation (Assistant PC)
```bash
cd assistant/
chmod +x install.sh
./install.sh
```

See [docs/PROJECT_MINDHOME_ASSISTANT.md](docs/PROJECT_MINDHOME_ASSISTANT.md) for full documentation.

---

## Installation

### Requirements
- Home Assistant OS (HAOS)
- Minimum 4GB RAM recommended

### Steps
1. In Home Assistant: **Settings → Add-ons → Add-on Store**
2. Top right: **⋮ → Repositories → Add URL:**
   ```
   https://github.com/Goifal/mindhome
   ```
3. Search for **MindHome** and click **Install**
4. Start the add-on
5. Click **MindHome** in the sidebar
6. The onboarding wizard will guide you through setup

## Technology

- **Backend:** Python 3.12, Flask, SQLAlchemy, SQLite
- **Frontend:** React (JSX), Babel 7, CSS Custom Properties
- **Connection:** Home Assistant REST API + WebSocket
- **Container:** Docker (Alpine Linux)

## Privacy

All data is stored **exclusively locally**. MindHome does not send any data to external servers. You have full control over all collected data and can view and delete it at any time.

## License

MIT License
