# CLAUDE.md — MindHome Entwicklungshandbuch

## Projektbeschreibung

MindHome ist ein KI-gesteuertes Home Assistant Add-on, das Benutzergewohnheiten lernt und Smart Homes vollstaendig lokal steuert. Es laeuft zu 100% auf dem Geraet ohne Cloud-Abhaengigkeiten und unterstuetzt Deutsch und Englisch in einer 2-PC-Architektur.

- **PC 1 (Add-on):** Flask-App als Home Assistant Add-on — UI, Geraeteverwaltung, Mustererkennung, Automatisierung
- **PC 2 (Assistent):** FastAPI-Server mit Ollama LLM, ChromaDB Vektordatenbank und Redis — KI-Konversation, proaktive Vorschlaege, Sprachverarbeitung

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
│       ├── pattern_engine.py       # KI-Mustererkennung
│       ├── automation_engine.py    # Automatisierungslogik
│       ├── routes/                 # 18 Flask Blueprint Module
│       ├── domains/                # 23 Domain-Plugins (light, climate, cover, etc.)
│       ├── engines/                # 16 Intelligenz-Engines
│       ├── translations/           # de.json, en.json
│       └── static/frontend/        # React 18 Frontend (einzelne app.jsx Datei)
│
├── assistant/                      # KI-Assistent Backend (PC 2)
│   ├── docker-compose.yml          # Assistent + ChromaDB + Redis
│   ├── requirements.txt            # FastAPI, Ollama, ChromaDB, etc.
│   ├── config/settings.yaml        # Umfangreiche YAML-Konfiguration
│   ├── tests/                      # 124 pytest Testdateien
│   └── assistant/                  # Python-Paket (104 Module)
│       ├── main.py                 # FastAPI Server Einstiegspunkt
│       ├── brain.py                # Kern-Orchestrator
│       ├── personality.py          # Persoenlichkeits-Engine
│       ├── function_calling.py     # LLM Tool-Definitionen
│       ├── proactive.py            # Proaktive Nachrichten
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
| Container | Docker (Alpine fuer Add-on, Python 3.12 fuer Assistent) |

## Build-, Lint- und Test-Befehle

### Tests
```bash
# Alle Assistent-Tests ausfuehren
cd assistant && python -m pytest --tb=short -q

# Einzelne Testdatei ausfuehren
cd assistant && python -m pytest tests/test_brain.py -v

# Test-Abhaengigkeiten installieren
pip install pytest pytest-asyncio
```

### Linting
```bash
# Ruff Lint (CI verwendet eingeschraenkten Regelsatz)
ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/ addon/ speech/

# Ruff Lint mit automatischer Korrektur
ruff check --fix assistant/ addon/ speech/

# Ruff Formatierung
ruff format assistant/ addon/ speech/

# Alle Pre-Commit Hooks ausfuehren
pre-commit run --all-files
```

### Statische Pruefungen
```bash
# Kompilierungspruefung aller Python-Dateien
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
- **Stil:** Ruff fuer Linting und Formatierung (ersetzt Black + flake8)
- **Benennung:** `snake_case` fuer Funktionen/Variablen, `PascalCase` fuer Klassen, `UPPER_CASE` fuer Konstanten
- **Type Hints:** Verwendet in assistant/ Code; weniger konsistent in addon/
- **Kein `eval()`** — durch Pre-Commit Hook erzwungen
- **Kein pauschales `noqa`** — durch Pre-Commit Hook erzwungen
- **Maximale Dateigroesse:** 500KB (durch Pre-Commit erzwungen)

### Datenbank (Add-on)
- **ORM:** SQLAlchemy deklarative Modelle in `models.py`
- **DB:** SQLite mit eigenem Migrationssystem (kein Alembic)
- **Session-Muster:**
  - `get_db_session()` — Context Manager mit Auto-Commit/Rollback (bevorzugt)
  - `get_db_readonly()` — Nur-Lese Context Manager
  - `get_db()` — manuelles Schliessen (Legacy, in neuem Code vermeiden)

### API-Design
- RESTful JSON-Endpunkte in Flask Blueprints (`routes/`)
- Eingabebereinigung ueber `sanitize_input()` und `sanitize_dict()` in `helpers.py`
- IP-basierte Ratenbegrenzung (600 Anfragen/60s)
- Rollenbasierte Zugriffskontrolle (User/Admin, 3 Stufen)

### Frontend
- Einzeldatei React-App (`app.jsx`, ~13K Zeilen) — kein Bundler, Babel transpiliert im Browser
- CSS-Variablen fuer Theming (Dark Mode Standard + Light Mode)
- Material Design Icons (MDI)
- Mobile-First responsives Design (Breakpoints: 768px, 480px)

### Assistent (FastAPI)
- Durchgehend async (`async`/`await`)
- LLM-Interaktion ueber `ollama_client.py` Wrapper
- 3-Schichten-Gedaechtnis: Arbeits- + episodisches + semantisches Gedaechtnis (ChromaDB)
- Function Calling mit Sicherheitsvalidierung bei LLM Tool-Aufrufen
- 3-Schichten Anti-Halluzinations-System

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
- Grosse-Dateien-Pruefung (500KB Maximum)
- `python-no-eval`, `python-check-blanket-noqa`

## Wichtige Architekturentscheidungen

- **2-PC-Aufteilung:** Add-on bleibt leichtgewichtig fuer HAOS Ressourcenbeschraenkungen; schwere KI laeuft auf separater Hardware
- **Einzeldatei-Frontend:** Vermeidet Build-Tooling-Komplexitaet; wird als statische Datei von Flask bereitgestellt
- **SQLite:** Funktioniert offline, keine Serververwaltung, Standard fuer HA Add-ons
- **Ollama:** Lokale LLM-Inferenz, keine API-Schluessel noetig, unterstuetzt mehrere Modelle
- **ChromaDB:** Vektorspeicher fuer semantische Gedaechtnissuche
- **Keine Cloud-Abhaengigkeiten:** Gesamte Verarbeitung lokal fuer Datenschutz

## Wichtige Dateien fuer Kontext

| Zweck | Datei |
|-------|-------|
| Add-on Einstiegspunkt | `addon/rootfs/opt/mindhome/app.py` |
| Datenbankmodelle | `addon/rootfs/opt/mindhome/models.py` |
| HA-Verbindung | `addon/rootfs/opt/mindhome/ha_connection.py` |
| Mustererkennung | `addon/rootfs/opt/mindhome/pattern_engine.py` |
| Assistent Einstiegspunkt | `assistant/assistant/main.py` |
| KI-Brain/Orchestrator | `assistant/assistant/brain.py` |
| LLM Function Calling | `assistant/assistant/function_calling.py` |
| Assistent-Konfiguration | `assistant/config/settings.yaml` |
| Versionsverwaltung | `addon/rootfs/opt/mindhome/version.py` |
| CI Pipeline | `.github/workflows/ci.yml` |

## Gaengige Muster

### Neue Flask-Route hinzufuegen
Blueprint in `addon/rootfs/opt/mindhome/routes/` erstellen oder erweitern. Registrierung in `routes/__init__.py`.

### Neues Domain-Plugin hinzufuegen
Neue Datei in `addon/rootfs/opt/mindhome/domains/` erstellen, die die Basis-Domain-Klasse aus `domains/base.py` erweitert.

### Neue Intelligenz-Engine hinzufuegen
Neue Datei in `addon/rootfs/opt/mindhome/engines/` erstellen, bestehende Engine-Muster befolgen.

### Assistent-Tests hinzufuegen
Testdateien in `assistant/tests/` als `test_*.py` ablegen. `pytest-asyncio` fuer async Tests verwenden.

## Sprachhinweise

- Die Codebasis und Commit-Nachrichten sind eine Mischung aus **Deutsch und Englisch**
- Benutzerorientierte Strings verwenden das Uebersetzungssystem (`translations/de.json`, `translations/en.json`)
- Code-Kommentare erscheinen in beiden Sprachen
- Variablen- und Funktionsnamen sind auf Englisch
