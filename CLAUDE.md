# CLAUDE.md — MindHome Entwicklungshandbuch

## WICHTIG: Produktivsystem — Arbeitsregeln

> **Dieses System läuft produktiv in einem echten Zuhause.**
> Du siehst hier nur das GitHub-Repository — du hast keinen Zugriff auf die laufende Instanz,
> die Datenbank, Home Assistant oder die Hardware.

### Vorsicht bei Änderungen
Ändere niemals leichtfertig bestehende Logik, da Fehler das laufende Smart Home direkt beeinträchtigen können. Besondere Vorsicht bei:
- Automatisierungslogik (steuert echte Geräte)
- Datenbank-Migrationen (Datenverlust möglich)
- HA-Verbindung und WebSocket-Code (Konnektivitätsverlust)
- Pattern Engine / Automation Engine (beeinflusst gelerntes Verhalten)

### Vor jedem Vorschlag: Bestandscode prüfen
Bevor du etwas Neues vorschlägst oder implementierst:
1. **Prüfe zuerst, ob die Funktionalität bereits existiert** — durchsuche die Codebase gründlich
2. **Wenn es schon existiert:** Frage dich, ob die bestehende Lösung verbessert werden kann, statt eine neue zu bauen
3. **Keine Duplikate erzeugen** — lieber bestehenden Code erweitern als parallele Lösungen schaffen
4. **Bestehende Muster respektieren** — neue Features müssen sich in die vorhandene Architektur einfügen

## Projektübersicht

MindHome ist ein KI-gesteuertes Home Assistant Add-on, das Benutzergewohnheiten lernt und Smart Homes vollständig lokal steuert. Es läuft zu 100% auf dem Gerät ohne Cloud-Abhängigkeiten und unterstützt Deutsch und Englisch in einer 2-PC-Architektur.

- **PC 1 (Add-on):** Flask-App als Home Assistant Add-on — UI, Geräteverwaltung, Mustererkennung, Automatisierung
- **PC 2 (Assistent):** FastAPI-Server mit Ollama LLM, ChromaDB Vektordatenbank und Redis — KI-Konversation, proaktive Vorschläge, Sprachverarbeitung

Aktuelle Version: **0.6.17** | Phase 3.5 abgeschlossen (~130 Features, 14 Domain-Plugins)

## Repository-Struktur

```
mindhome/
├── addon/                          # Home Assistant Add-on (PC 1)
│   ├── config.yaml                 # Add-on Metadaten (v1.5.13)
│   ├── Dockerfile                  # Alpine Linux Container
│   └── rootfs/opt/mindhome/        # Hauptanwendungscode
│       ├── app.py                  # Flask Einstiegspunkt
│       ├── models.py               # SQLAlchemy Modelle (SQLite)
│       ├── ha_connection.py        # HA WebSocket/REST Client
│       ├── pattern_engine.py       # KI-Mustererkennung (~106KB)
│       ├── automation_engine.py    # Automatisierungslogik (~118KB)
│       ├── db.py                   # Datenbank-Session-Verwaltung
│       ├── helpers.py              # Hilfsfunktionen (Timezone, Sanitize, etc.)
│       ├── version.py              # Zentrale Versionsverwaltung
│       ├── routes/                 # 18 Flask Blueprint Module
│       ├── domains/                # 23 Domain-Plugins (light, climate, cover, etc.)
│       ├── engines/                # 16 Intelligenz-Engines
│       ├── translations/           # de.json, en.json
│       └── static/frontend/        # React 18 Frontend (einzelne app.jsx Datei)
│
├── assistant/                      # KI-Assistent Backend (PC 2)
│   ├── docker-compose.yml          # Assistent + ChromaDB + Redis
│   ├── requirements.txt            # FastAPI, Ollama, ChromaDB, etc.
│   ├── config/settings.yaml        # Umfangreiche YAML-Konfiguration (~60KB)
│   ├── .env.example                # Umgebungsvariablen-Vorlage
│   ├── tests/                      # 124+ pytest Testdateien
│   │   └── conftest.py             # Globale Test-Fixtures (redis, chroma, ha, ollama Mocks)
│   └── assistant/                  # Python-Paket (104 Module)
│       ├── main.py                 # FastAPI Server Einstiegspunkt (~359KB)
│       ├── brain.py                # Kern-Orchestrator (~629KB)
│       ├── personality.py          # Persönlichkeits-Engine (~179KB)
│       ├── function_calling.py     # LLM Tool-Definitionen (~419KB)
│       ├── proactive.py            # Proaktive Nachrichten (~378KB)
│       └── ...                     # 100+ spezialisierte Module
│
├── speech/                         # Whisper STT Container
├── esphome/                        # ESP32 Sprach-Satelliten Konfiguration
├── ha_integration/                 # Eigene HA-Komponenten
├── docs/                           # Erweiterte Dokumentation
├── .github/workflows/ci.yml       # CI/CD Pipeline
└── .pre-commit-config.yaml         # Ruff + Pre-Commit Hooks
```

## Tech-Stack

| Schicht | Technologie |
|---------|------------|
| Add-on Backend | Python 3.12, Flask 3.1, SQLAlchemy 2.0, SQLite |
| Assistent Backend | Python 3.12, FastAPI 0.115, Uvicorn |
| LLM | Ollama (Qwen, Llama, Mistral — lokal) |
| Vektordatenbank | ChromaDB 0.5 |
| Cache | Redis 5.2 |
| Embeddings | sentence-transformers 3.3 |
| Frontend | React 18 (JSX via Babel, kein Build-Schritt) |
| Sprache | Whisper (STT), Piper (TTS), SpeechBrain |
| Container | Docker (Alpine für Add-on, Python 3.12 für Assistent) |

## Build-, Lint- und Test-Befehle

### Tests
```bash
# Alle Assistent-Tests ausführen
cd assistant && python -m pytest --tb=short -q

# Einzelne Testdatei ausführen
cd assistant && python -m pytest tests/test_brain.py -v

# Test-Abhängigkeiten installieren
pip install pytest pytest-asyncio
```

### Linting
```bash
# Ruff Lint (CI verwendet eingeschränkten Regelsatz)
ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/ addon/ speech/

# Ruff Lint mit automatischer Korrektur
ruff check --fix assistant/ addon/ speech/

# Ruff Formatierung
ruff format assistant/ addon/ speech/

# Alle Pre-Commit Hooks ausführen
pre-commit run --all-files
```

### Statische Prüfungen
```bash
# Kompilierungsprüfung aller Python-Dateien
find assistant/assistant -name "*.py" -exec python -m py_compile {} \;
find addon/rootfs/opt/mindhome -name "*.py" -exec python -m py_compile {} \;
```

### Docker
```bash
docker build -t mindhome-assistant ./assistant
docker build -f speech/Dockerfile.whisper -t mindhome-speech ./speech
docker-compose -f assistant/docker-compose.yml up
```

## Code-Konventionen

### Python
- **Stil:** Ruff für Linting und Formatierung (ersetzt Black + flake8)
- **Benennung:** `snake_case` für Funktionen/Variablen, `PascalCase` für Klassen, `UPPER_CASE` für Konstanten
- **Type Hints:** Verwendet in assistant/ Code; weniger konsistent in addon/
- **Kein `eval()`** — durch Pre-Commit Hook erzwungen
- **Kein pauschales `noqa`** — durch Pre-Commit Hook erzwungen
- **Maximale Dateigröße:** 500KB (durch Pre-Commit erzwungen)

### Datenbank (Add-on)
- **ORM:** SQLAlchemy deklarative Modelle in `models.py`
- **DB:** SQLite mit eigenem Migrationssystem (kein Alembic)
- **Session-Muster (wichtig!):**
  - `get_db_session()` — Context Manager mit Auto-Commit/Rollback **(bevorzugt für neuen Code)**
  - `get_db_readonly()` — Nur-Lese Context Manager
  - `db_write_with_retry()` — Schreiboperationen mit automatischem Retry bei SQLite-Locks
  - `get_db()` — manuelles Schließen **(Legacy, in neuem Code vermeiden!)**

### API-Design
- RESTful JSON-Endpunkte in Flask Blueprints (`routes/`)
- Eingabebereinigung über `sanitize_input()` und `sanitize_dict()` in `helpers.py`
- IP-basierte Ratenbegrenzung (600 Anfragen/60s)
- Rollenbasierte Zugriffskontrolle (User/Admin, 3 Stufen)

### Frontend
- Einzeldatei React-App (`app.jsx`, ~13K Zeilen) — kein Bundler, Babel transpiliert im Browser
- CSS-Variablen für Theming (Dark Mode Standard + Light Mode)
- Material Design Icons (MDI)
- Mobile-First responsives Design (Breakpoints: 768px, 480px)

### Assistent (FastAPI)
- Durchgehend async (`async`/`await`)
- LLM-Interaktion über `ollama_client.py` Wrapper
- 3-Schichten-Gedächtnis: Arbeits- + episodisches + semantisches Gedächtnis (ChromaDB)
- Function Calling mit Sicherheitsvalidierung bei LLM Tool-Aufrufen
- 3-Schichten Anti-Halluzinations-System
- ChromaDB/PostHog-Telemetrie wird beim Import deaktiviert (siehe `main.py` Zeilen 12-21)

## CI/CD Pipeline

GitHub Actions bei Push auf `main`/`develop` und PRs auf `main`:

1. **test-assistant** — pytest mit Python 3.12 (CPU-only PyTorch)
2. **lint** — Ruff Check (E9, F63, F7, F82 Regeln, F823 ignoriert)
3. **static-check** — `py_compile` aller Python-Dateien
4. **dependency-audit** — `pip-audit` auf alle requirements.txt
5. **docker-build** — Bau der Assistent- und Speech-Container

## Pre-Commit Hooks

Konfiguriert in `.pre-commit-config.yaml`:
- Ruff Lint mit `--fix` + Ruff Format
- YAML/JSON Validierung
- End-of-File Fixer, Trailing Whitespace Bereinigung
- Merge-Konflikt-Erkennung
- Große-Dateien-Prüfung (500KB Maximum)
- `python-no-eval`, `python-check-blanket-noqa`

## Wichtige Architekturentscheidungen

- **2-PC-Aufteilung:** Add-on bleibt leichtgewichtig für HAOS Ressourcenbeschränkungen; schwere KI läuft auf separater Hardware
- **Einzeldatei-Frontend:** Vermeidet Build-Tooling-Komplexität; wird als statische Datei von Flask bereitgestellt
- **SQLite:** Funktioniert offline, keine Serververwaltung, Standard für HA Add-ons
- **Ollama:** Lokale LLM-Inferenz, keine API-Schlüssel nötig, unterstützt mehrere Modelle
- **ChromaDB:** Vektorspeicher für semantische Gedächtnissuche
- **Keine Cloud-Abhängigkeiten:** Gesamte Verarbeitung lokal für Datenschutz

## Wichtige Dateien für Kontext

| Zweck | Datei |
|-------|-------|
| Add-on Einstiegspunkt | `addon/rootfs/opt/mindhome/app.py` |
| Datenbankmodelle | `addon/rootfs/opt/mindhome/models.py` |
| DB-Session-Verwaltung | `addon/rootfs/opt/mindhome/db.py` |
| Hilfsfunktionen | `addon/rootfs/opt/mindhome/helpers.py` |
| HA-Verbindung | `addon/rootfs/opt/mindhome/ha_connection.py` |
| Mustererkennung | `addon/rootfs/opt/mindhome/pattern_engine.py` |
| Assistent Einstiegspunkt | `assistant/assistant/main.py` |
| KI-Brain/Orchestrator | `assistant/assistant/brain.py` |
| LLM Function Calling | `assistant/assistant/function_calling.py` |
| Assistent-Konfiguration | `assistant/config/settings.yaml` |
| Versionsverwaltung | `addon/rootfs/opt/mindhome/version.py` |
| CI Pipeline | `.github/workflows/ci.yml` |
| Test-Fixtures | `assistant/tests/conftest.py` |

## Gängige Muster

### Neue Flask-Route hinzufügen
1. Blueprint in `addon/rootfs/opt/mindhome/routes/` erstellen
2. Modul exportiert `<name>_bp` (Blueprint) und `init_<name>(dependencies)` Funktion
3. **Wichtig:** `init_<name>()` muss VOR `register_blueprint()` aufgerufen werden
4. Registrierung in `routes/__init__.py` nach dem bestehenden Muster

### Neues Domain-Plugin hinzufügen
1. Neue Datei in `addon/rootfs/opt/mindhome/domains/` erstellen
2. Von `DomainPlugin(ABC)` aus `domains/base.py` erben
3. Pflichtattribute setzen: `DOMAIN_NAME`, `HA_DOMAINS`, `DEVICE_CLASSES`, `DEFAULT_SETTINGS`
4. Abstrakte Methoden implementieren: `on_start()`, `on_stop()`, `on_state_change()`, `get_trackable_features()`, `get_current_status()`
5. Nützliche Basismethoden: `execute_or_suggest()`, `get_context()`, `is_anyone_home()`, `is_quiet_time()`

### Neue Intelligenz-Engine hinzufügen
Neue Datei in `addon/rootfs/opt/mindhome/engines/` erstellen, bestehende Engine-Muster befolgen.

### Assistent-Tests hinzufügen
1. Testdateien in `assistant/tests/` als `test_*.py` ablegen
2. Fixtures aus `conftest.py` nutzen: `redis_mock`, `chroma_mock`, `ha_mock`, `ollama_mock`, `brain_mock`
3. `pytest-asyncio` für async Tests verwenden
4. Mocks über Fixture-Injection, keine Inline-Mocks

## Häufige Fallstricke

| Fehler | Lösung |
|--------|--------|
| `get_db()` ohne `session.close()` | Immer `get_db_session()` Context Manager verwenden |
| SQLite "database is locked" | `db_write_with_retry()` für Schreiboperationen nutzen |
| `timezone.utc` für Zeitberechnungen | `get_ha_timezone()` / `local_now()` aus `helpers.py` verwenden |
| Domain-Plugin `__init__()` überschreiben | Immer `super().__init__()` aufrufen — bricht sonst Dependency Injection |
| `get_context()` liefert veraltete Daten | Cache von 30 Sekunden beachten |
| Blueprint registriert, aber Routen fehlen | `init_<name>(dependencies)` VOR `register_blueprint()` aufrufen |
| Sensible Daten in Logs | Error Buffer reduziert API-Keys/Tokens automatisch — keine manuelle Filterung nötig |
| `OLLAMA_URL` in Docker | `http://host.docker.internal:11434` verwenden, nicht `localhost` |
| Große Dateien (brain.py ~629KB) | Gezielt lesen, nicht komplett laden — Funktionen über Grep suchen |

## Umgebungsvariablen (Assistent)

Wichtigste Variablen aus `.env.example`:
```
HA_URL=http://192.168.1.100:8123       # Home Assistant URL
HA_TOKEN=...                            # Long-Lived Access Token
MINDHOME_URL=http://192.168.1.100:8099  # MindHome Add-on URL
OLLAMA_URL=http://host.docker.internal:11434  # Ollama (Docker-Host)
REDIS_URL=redis://redis:6379            # Redis (Docker-intern)
CHROMA_URL=http://chromadb:8000         # ChromaDB (Docker-intern)
DATA_DIR=/mnt/data                      # Datenverzeichnis
```

Modelle (3 Stufen): `MODEL_FAST` (4B), `MODEL_SMART` (9B), `MODEL_DEEP` (27B)

## Versionsverwaltung

Zentral in `addon/rootfs/opt/mindhome/version.py`:
```python
VERSION = "1.5.13"
BUILD = 104
BUILD_DATE = "2026-03-13"
CODENAME = "Jarvis Voice"
```
Alle Module importieren die Version von hier — niemals hardcoden.

## Sprachhinweise

- Codebase und Commit-Nachrichten sind eine Mischung aus **Deutsch und Englisch**
- Benutzerorientierte Strings verwenden das Übersetzungssystem (`translations/de.json`, `translations/en.json`)
- Code-Kommentare erscheinen in beiden Sprachen
- Variablen- und Funktionsnamen sind auf Englisch
