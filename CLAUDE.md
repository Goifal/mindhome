# CLAUDE.md — MindHome / J.A.R.V.I.S. Entwicklungshandbuch

## WICHTIG: Produktivsystem — Arbeitsregeln

> **Dieses System läuft produktiv in einem echten Zuhause und steuert reale Geräte.**
> Du siehst hier nur das GitHub-Repository — du hast keinen Zugriff auf die laufende Instanz,
> die Datenbank, Home Assistant, die Hardware oder Logs.

### Regel 1: Vorsicht bei Änderungen
Ändere niemals leichtfertig bestehende Logik. Fehler beeinträchtigen das laufende Smart Home direkt. Besondere Vorsicht bei:
- Automatisierungslogik (steuert echte Geräte — Licht, Heizung, Rollläden, Schlösser)
- Datenbank-Migrationen (Datenverlust möglich, kein Alembic — eigenes System)
- HA-Verbindung und WebSocket-Code (Konnektivitätsverlust zum ganzen Haus)
- Pattern Engine / Automation Engine (beeinflusst über Wochen gelerntes Verhalten)
- Autonomy-Level und Trust-Level Logik (Sicherheitskritisch — wer darf was steuern)
- Proaktive Systeme (falsche Auslösung stört die Bewohner, besonders nachts)

### Regel 2: Bestandscode zuerst prüfen
Bevor du etwas Neues vorschlägst oder implementierst:
1. **Durchsuche die Codebase gründlich** — es gibt 98+ Module im Assistenten und 23 Domain-Plugins. Die Funktionalität existiert sehr wahrscheinlich schon
2. **Wenn es schon existiert:** Prüfe ob die bestehende Lösung verbessert werden kann, statt eine neue zu bauen
3. **Keine Duplikate erzeugen** — lieber bestehenden Code erweitern als parallele Lösungen schaffen
4. **Bestehende Muster respektieren** — neue Features müssen sich in die vorhandene Architektur einfügen (Blueprints, Domain-Plugins, Engines, Event-Bus)

### Regel 3: Kontinuierliche Selbstprüfung
Bei jeder Aufgabe hinterfrage dich aktiv:
- **"Könnte ich das besser machen?"** — Gibt es eine elegantere, performantere oder robustere Lösung?
- **"Was würde Jarvis verbessern?"** — Denke proaktiv mit: Welche Optimierungen, Bugfixes oder Feature-Verbesserungen fallen dir beim Lesen des Codes auf?
- **"Gibt es hier technische Schulden?"** — Race Conditions, fehlende Error-Handles, ineffiziente Patterns, Security-Lücken?
- Teile solche Beobachtungen aktiv mit — auch wenn sie nicht direkt zur aktuellen Aufgabe gehören

### Regel 4: Expertenniveau
Programmiere und prüfe alles auf Expertenniveau:
- **Code-Qualität:** Clean Code, SOLID-Prinzipien, keine Quick-and-Dirty-Lösungen
- **Fehlerbehandlung:** Robustes Error-Handling, keine stillen Fehler (`except: pass` ist verboten)
- **Sicherheit:** OWASP Top 10 beachten, Input-Sanitization, keine Prompt-Injection-Vektoren
- **Performance:** Async-Patterns korrekt nutzen, keine blockierenden Aufrufe in async Code, Batch-Operationen wo möglich
- **Concurrency:** Locks für shared State, konsistente Lock-Reihenfolge, kein Lock-Halten während I/O
- **Tests:** Jede Änderung muss testbar sein, bestehende Tests dürfen nicht brechen
- **Review-Mentalität:** Prüfe eigenen Code so kritisch wie fremden Code in einem Code-Review

---

## Projektübersicht

MindHome ist ein KI-gesteuertes Home Assistant Add-on, das Benutzergewohnheiten lernt und Smart Homes vollständig lokal steuert. Der Assistent heißt **J.A.R.V.I.S.** — ein intelligenter KI-Butler mit eigener Persönlichkeit, inspiriert von Tony Starks Jarvis. Es läuft zu 100% lokal ohne Cloud-Abhängigkeiten.

### 2-PC-Architektur
- **PC 1 (Add-on auf HAOS):** Flask-App — UI, Geräteverwaltung, Mustererkennung, Automatisierung
- **PC 2 (Ubuntu-Server):** FastAPI-Server — KI-Brain, LLM-Inferenz (Ollama), Gedächtnis (ChromaDB + Redis), Sprachverarbeitung

Aktuelle Version: **0.6.17** | Add-on Build: **104** | Codename: **"Jarvis Voice"**

---

## Was Jarvis ausmacht — Assistent-Architektur (98 Module)

### Kern-Systeme
| Modul | Datei | Funktion |
|-------|-------|----------|
| Brain | `brain.py` (~629KB) | Zentraler Orchestrator — verbindet alle 30+ Komponenten, steuert Konversationsfluss, Autonomie-Entscheidungen |
| Persönlichkeit | `personality.py` (~179KB) | Dynamische Persönlichkeit: Sarkasmus-Level 1-5, stimmungsabhängiger Stil, Butler-Humor, Meinungs-Engine |
| Core Identity | `core_identity.py` | Unveränderlicher Identitätsblock: Werte (Loyalität, Ehrlichkeit, Diskretion), Emotionsspektrum |
| Function Calling | `function_calling.py` (~419KB) | 50+ Home-Assistant-Tools: Licht, Klima, Medien, Sicherheit, Szenen, Timer, Kalender |
| Proaktiv-Manager | `proactive.py` (~378KB) | Event-getriebene proaktive Benachrichtigungen, 4 Dringlichkeitsstufen, Quiet-Hours, Batching |

### Persönlichkeit & Emotionen
| Modul | Funktion |
|-------|----------|
| `inner_state.py` | Jarvis' eigene Emotionen: 7 Stimmungen (neutral, zufrieden, amüsiert, besorgt, stolz, neugierig, gereizt) |
| `mood_detector.py` | Erkennt Benutzerstimmung: gut, neutral, gestresst, frustriert, müde — per Sprache + Text |
| `brain_humanizers.py` | Anti-Bot-Features: variiert Antwortstruktur, natürliche Pausen, Denkpausen |
| `activity.py` | Silence Matrix: 7 Aktivitätszustände × 3 Dringlichkeitsstufen → Zustellmethode (laut/leise/LED/unterdrücken) |

### Gedächtnis & Lernen (3-Schichten-Architektur)
| Modul | Funktion |
|-------|----------|
| `memory.py` | Arbeitsgedächtnis (Redis, letzte 50 Gespräche, 7-Tage-TTL) |
| `semantic_memory.py` | Semantisches Gedächtnis (ChromaDB): Fakten mit Konfidenz, 9 Kategorien (Vorlieben, Gewohnheiten, Gesundheit, Termine...) |
| `conversation_memory.py` | Projekt-Tracking, offene Fragen (14-Tage-TTL), Tageszusammenfassungen, Follow-ups |
| `memory_extractor.py` | Automatische Faktenextraktion aus Gesprächen |
| `learning_observer.py` | Erkennt manuelle Wiederholungsmuster (≥3×) → schlägt Automatisierung vor |
| `learning_transfer.py` | Überträgt gelernte Präferenzen zwischen ähnlichen Räumen |
| `correction_memory.py` | Lernt aus Korrekturen — passt Schwellwerte und Verhalten an |
| `feedback.py` | Feedback-Tracking: ignoriert/abgelehnt/gelobt → adaptive Cooldowns |
| `self_optimization.py` | Schlägt Persönlichkeits-Parameteränderungen vor (nie automatisch!) |

### Antizipation & Proaktivität
| Modul | Funktion |
|-------|----------|
| `anticipation.py` | Mustererkennung: Zeit-, Sequenz- und Kontextmuster → vorhersagende Aktionen |
| `spontaneous_observer.py` | 1-2 unaufgeforderte Beobachtungen/Tag (Energie-Trends, Rekorde, Fun Facts) |
| `proactive_planner.py` | Mehrstufige Aktionssequenzen mit Timing und Narration |
| `outcome_tracker.py` | Misst Aktionsergebnisse vs. Absicht → lernt aus Erfolg/Misserfolg |
| `insight_engine.py` (~89KB) | Kreuzreferenz-Analysen: Wetter↔Fenster, Frost↔Heizung, Energie-Anomalien |
| `seasonal_insight.py` | Saisonale Empfehlungen (Heizstrategie, Lichtanpassung) |

### Sprache & Audio
| Modul | Funktion |
|-------|----------|
| `speaker_recognition.py` | 7-stufiges Sprecher-ID-System: Gerät→DoA→Raum→Präsenz→Voice-Embedding→Merkmale→Cache |
| `ambient_audio.py` | Umgebungsgeräusch-Erkennung: Glasbruch, Rauchmelder, Hundebellen, Babycry, Türklingel |
| `tts_enhancer.py` | Prosodie, Emotionsinjection, Lautstärkenormalisierung |
| `multi_room_audio.py` | Raum-aware Nachrichtenzustellung, Sprecher-Gruppen |
| `follow_me.py` | Audio folgt dem Benutzer zwischen Räumen |
| `sound_manager.py` | TTS + Soundeffekte Mixing |

### Reasoning & Planung
| Modul | Funktion |
|-------|----------|
| `action_planner.py` | Mehrstufige iterative Planung mit Narration ("alles fertig machen" → 5 Schritte) |
| `context_builder.py` (~63KB) | Sammelt HA-State, Wetter, Kalender, Energie — Prompt-Injection-Schutz (80+ Muster) |
| `model_router.py` | 3-Tier LLM-Routing: Fast (3B, <500ms) → Smart (14B, <2s) → Deep (32B, <5s) |
| `dialogue_state.py` | Konversationszustand, Referenzauflösung ("es", "das", "dort"), Cross-Session-Referenzen |
| `conflict_resolver.py` | Erkennt Gerätekonflikte (Fenster offen + Heizung an) |
| `pre_classifier.py` | Schnelle Intent-Erkennung vor LLM (Befehl vs. Frage vs. Chat) |
| `intent_tracker.py` | Multi-Turn Intent-Tracking und -Verfeinerung |

### Autonomie & Sicherheit
| Modul | Funktion |
|-------|----------|
| `autonomy.py` | 5 Autonomie-Level: 1=Assistent → 5=Autopilot, domänenspezifisch konfigurierbar |
| `function_validator.py` | Pre-Execution Sicherheitsprüfung: Trust-Level, Security-Zones, Parameter-Bounds |
| `threat_assessment.py` | Bedrohungserkennung: ungewöhnliche Bewegung, offene Fenster bei Sturm, Notfall-Playbooks |
| `self_automation.py` | Erstellt neue Automatisierungen aus gelernten Mustern (mit Sicherheitsvalidierung) |
| `config_versioning.py` | Snapshots vor jeder Konfigurationsänderung, Rollback möglich |

### Haushalt & Spezial-Features
| Modul | Funktion |
|-------|----------|
| `routine_engine.py` | Morgen-Briefing, Gute-Nacht-Routine, Ankunfts-Begrüßung, Urlaubssimulation |
| `energy_optimizer.py` | Strompreis-Monitoring, Solar-Awareness, flexible Lastverschiebung |
| `cooking_assistant.py` | Rezepte, Schritt-für-Schritt-Anleitung, Zutatenersetzung, Ernährungsfilter |
| `smart_shopping.py` | Einkaufslisten, Preisoptimierung, Vorratsverwaltung |
| `workshop_generator.py` | Code-Generierung (Arduino, Python, C++), OpenSCAD 3D-Modelle, SVG-Schaltpläne, Berechnungen |
| `repair_planner.py` | Diagnose, Reparaturanleitungen, Teile-Identifikation, Kostenabschätzung |
| `wellness_advisor.py` | PC-Pausen, Stressintervention, Mahlzeiten-Erinnerungen, Hydration |
| `calendar_intelligence.py` | Gewohnheitserkennung, Konfliktwarnungen, Pendelzeit-Puffer |
| `web_search.py` | SearXNG (self-hosted) + DuckDuckGo Fallback, 7-Schichten SSRF-Schutz |
| `ocr.py` | Texterkennung aus Fotos, Tabellenerkennung |

### System-Intelligenz
| Modul | Funktion |
|-------|----------|
| `diagnostics.py` | Sensor-Health, System-Ressourcen, Service-Health (HA, Ollama, Redis, ChromaDB) |
| `device_health.py` | Anomalie-Erkennung (30-Tage-Baseline), HVAC-Effizienz, Energie-Anomalien |
| `health_monitor.py` | CO2 (>1000ppm Warnung), Luftfeuchtigkeit, Temperatur-Alerts |
| `predictive_maintenance.py` | Geräte-Lebensdauer-Schätzung, Wartungsplanung |
| `state_change_log.py` (~379KB) | Attribution: WER hat WAS geändert (Jarvis/Automation/User/Unbekannt), 80+ Abhängigkeitsregeln |
| `circuit_breaker.py` | Fault Tolerance: Auto-Fallback bei Service-Ausfall |
| `explainability.py` | XAI: Warum hat Jarvis diese Entscheidung getroffen? |
| `latency_tracker.py` | Response-Time-Tracking, Optimierungsziele |
| `response_cache.py` | Cache häufiger Antworten, TTL-basiert |

### Besondere Jarvis-Features
- **"Das Übliche"** — Phrasen wie "wie immer", "du weißt schon" triggern gelernte Routinen (Konfidenz ≥0.8: Auto-Execute)
- **Pushback-System** — Intelligente Rückfragen: offene Fenster, leerer Raum, Tageslicht, Sturmwarnung
- **Butler Instinct** — Auto-Execute bei hoher Konfidenz (≥0.8) ab Autonomie-Level 3
- **Krisenmodus** — Deaktiviert Humor bei kritischen Events, Effizienzmodus
- **Boot-Sequenz** — "Alle Systeme online, Sir." beim Start
- **Character Lock** — Persönlichkeitskonsistenz über Antworten hinweg
- **STT-Korrekturen** — 95+ deutsche Wortkorrekturen für Spracheingabe
- **Immutable Core** — Trust-Levels, Security, Autonomie, Modelle können nicht per Self-Optimization geändert werden

---

## Repository-Struktur

```
mindhome/
├── addon/                          # Home Assistant Add-on (PC 1 — Flask)
│   ├── config.yaml                 # Add-on Metadaten (v1.5.13)
│   ├── Dockerfile                  # Alpine Linux Container
│   └── rootfs/opt/mindhome/        # Hauptanwendungscode
│       ├── app.py                  # Flask Einstiegspunkt
│       ├── models.py               # SQLAlchemy Modelle (SQLite, ~99KB)
│       ├── ha_connection.py        # HA WebSocket/REST Client (~46KB)
│       ├── pattern_engine.py       # KI-Mustererkennung (~106KB)
│       ├── automation_engine.py    # Automatisierungslogik (~118KB)
│       ├── db.py                   # Datenbank-Session-Verwaltung
│       ├── helpers.py              # Timezone, Sanitize, Rate-Limiting
│       ├── event_bus.py            # Thread-safe Pub/Sub mit Wildcards + Prioritäten
│       ├── version.py              # Zentrale Versionsverwaltung (Single Source of Truth)
│       ├── routes/                 # 18 Flask Blueprint Module
│       ├── domains/                # 23 Domain-Plugins (light, climate, cover, etc.)
│       ├── engines/                # 16 Intelligenz-Engines
│       ├── translations/           # de.json, en.json
│       └── static/frontend/        # React 18 Frontend (app.jsx, ~13K Zeilen)
│
├── assistant/                      # KI-Assistent "Jarvis" Backend (PC 2 — FastAPI)
│   ├── docker-compose.yml          # Assistent + ChromaDB + Redis
│   ├── requirements.txt            # FastAPI, Ollama, ChromaDB, etc.
│   ├── config/settings.yaml        # Umfangreiche YAML-Konfiguration (~60KB)
│   ├── .env.example                # Umgebungsvariablen-Vorlage
│   ├── tests/                      # 124+ pytest Testdateien
│   │   └── conftest.py             # Globale Fixtures (redis, chroma, ha, ollama, brain Mocks)
│   └── assistant/                  # Python-Paket (98 Module, ~106K Zeilen)
│
├── speech/                         # Whisper STT Container
├── esphome/                        # ESP32 Sprach-Satelliten (M5Stack)
├── ha_integration/                 # Custom HA-Komponenten
├── docs/                           # Erweiterte Dokumentation
├── .github/workflows/ci.yml       # CI/CD Pipeline
└── .pre-commit-config.yaml         # Ruff + Pre-Commit Hooks
```

## Tech-Stack

| Schicht | Technologie |
|---------|------------|
| Add-on Backend | Python 3.12, Flask 3.1, SQLAlchemy 2.0, SQLite |
| Assistent Backend | Python 3.12, FastAPI 0.115, Uvicorn (async) |
| LLM | Ollama lokal (Qwen, Llama, Mistral — 3 Tiers: Fast/Smart/Deep) |
| Vektordatenbank | ChromaDB 0.5 (semantische Suche) |
| Cache | Redis 5.2 (Stimmung, Kontext, Cooldowns, Sperren) |
| Embeddings | sentence-transformers 3.3 (ECAPA-TDNN für Stimme) |
| Frontend | React 18, JSX via Babel (kein Build-Schritt), Material Design Icons |
| Sprache | Whisper (STT), Piper (TTS), SpeechBrain (Speaker-ID) |
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
# Ruff Lint (CI-Regelsatz)
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
- **Migrationen:** Existenzprüfung vor dem Erstellen von Defaults (`session.query(...).filter_by(...).first()`), `session.merge()` für Idempotenz

### API-Design (Add-on)
- RESTful JSON-Endpunkte in Flask Blueprints (`routes/`)
- Eingabebereinigung über `sanitize_input()` und `sanitize_dict()` in `helpers.py`
- IP-basierte Ratenbegrenzung (600 Anfragen/60s)
- Rollenbasierte Zugriffskontrolle (User/Admin, 3 Stufen)
- Dependency-Injection via globales `_deps`-Dict → Accessor-Funktionen (`_ha()`, `_engine()`, etc.)

### Frontend
- Einzeldatei React-App (`app.jsx`, ~13K Zeilen) — kein Bundler, Babel transpiliert im Browser
- CSS-Variablen für Theming (Dark Mode Standard + Light Mode)
- Material Design Icons (MDI)
- Mobile-First responsives Design (Breakpoints: 768px, 480px)

### Assistent (FastAPI)
- Durchgehend async (`async`/`await`) — keine blockierenden Aufrufe in async Code!
- LLM-Interaktion über `ollama_client.py` (streift `<think>`-Blöcke, Metrics-Logging)
- 3-Schichten-Gedächtnis: Arbeits- (Redis) + episodisches (ChromaDB) + semantisches Gedächtnis
- Function Calling mit Sicherheitsvalidierung (Trust-Level, Security-Zones, Parameter-Bounds)
- 3-Schichten Anti-Halluzinations-System
- ChromaDB/PostHog-Telemetrie wird beim Import deaktiviert (`main.py` Zeilen 12-21)
- Fire-and-forget Tasks immer mit Error-Callback:
  ```python
  task = asyncio.create_task(...)
  task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
  ```

### Event-Bus (Add-on)
- Thread-safe Pub/Sub mit Prioritäten-Sortierung
- Wildcard-Subscriptions: `"state.*"` matched `"state.changed"`
- Event-Handler laufen synchron — keine langsamen Operationen in Handlern!
- History: letzte 100 Events

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

## Häufige Fallstricke

| Fehler | Lösung |
|--------|--------|
| `get_db()` ohne `session.close()` | Immer `get_db_session()` Context Manager verwenden |
| SQLite "database is locked" | `db_write_with_retry()` für Schreiboperationen nutzen |
| `datetime.now()` (naiv) statt aware | `local_now()` aus `helpers.py` oder `datetime.now(timezone.utc)` verwenden |
| Naive + Aware Datetime gemischt | Verursacht `TypeError` — immer konsistent aware verwenden |
| Domain-Plugin `__init__()` ohne super() | Bricht Dependency Injection — immer `super().__init__()` aufrufen |
| `get_context()` liefert veraltete Daten | Cache von 30 Sekunden beachten — nicht in schnellen Schleifen aufrufen |
| Blueprint registriert, aber Routen fehlen | `init_<name>(dependencies)` VOR `register_blueprint()` aufrufen |
| Sensible Daten in Logs | Error Buffer reduziert API-Keys/Tokens automatisch (Regex-Filter) |
| `OLLAMA_URL` in Docker | `http://host.docker.internal:11434` verwenden, nicht `localhost` |
| Große Dateien (brain.py ~629KB) | Gezielt per Grep suchen, nicht komplett laden |
| `except Exception: pass` | Verboten — mindestens auf WARNING-Level loggen |
| Blockierender Call in async Code | `asyncio.to_thread()` für sync I/O verwenden |
| Fire-and-forget Task ohne Callback | Fehler gehen still verloren — immer `add_done_callback` |
| User-Input direkt in LLM-Prompt | Prompt-Injection-Risiko — als separate User-Message übergeben |
| Redis kann `None` sein | Immer auf `if self.memory.redis:` prüfen bevor Zugriff |
| Shared State ohne Lock | `threading.Lock()` im Add-on, `asyncio.Lock()` im Assistenten |
| Lock halten während I/O | Acquire → kopieren → release → dann verarbeiten |

## Sicherheitsregeln

- **Alle User-Eingaben sind potenziell bösartig** — `sanitize_input()` und `sanitize_dict()` verwenden
- **Niemals User-Daten in LLM System-Prompts einbetten** — als separate User-Messages übergeben
- **Alle Parameter validieren und whitelisten** — keine beliebigen Strings/Dicts akzeptieren
- **Sicherheitskritische Operationen rate-limiten** (PIN-Eingabe, Emergency Stop, Factory Reset)
- **Keine internen Fehlerdetails** in API-Responses exponieren
- **Immutable Core respektieren** — Trust-Levels, Security, Autonomie, Modelle können nicht per Self-Optimization geändert werden

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

Modelle (3 Stufen): `MODEL_FAST` (3-4B), `MODEL_SMART` (9-14B), `MODEL_DEEP` (27-32B)

## Versionsverwaltung

Zentral in `addon/rootfs/opt/mindhome/version.py`:
```python
VERSION = "1.5.13"
BUILD = 104
BUILD_DATE = "2026-03-13"
CODENAME = "Jarvis Voice"
```
Alle Module importieren die Version von hier — niemals hardcoden.

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

### Neues Assistent-Modul hinzufügen
1. Modul in `assistant/assistant/` erstellen
2. Im `brain.py` als Komponente registrieren (über `_safe_init()`)
3. Bestehende Patterns beachten: Redis für State, ChromaDB für semantische Daten
4. Error-Handling: Graceful Degradation wenn Abhängigkeit nicht verfügbar

### Assistent-Tests hinzufügen
1. Testdateien in `assistant/tests/` als `test_*.py` ablegen
2. Fixtures aus `conftest.py` nutzen: `redis_mock`, `chroma_mock`, `ha_mock`, `ollama_mock`, `brain_mock`
3. `pytest-asyncio` für async Tests verwenden
4. Mocks über Fixture-Injection, keine Inline-Mocks

## Sprachhinweise

- Codebase und Commit-Nachrichten sind eine Mischung aus **Deutsch und Englisch**
- Benutzerorientierte Strings verwenden das Übersetzungssystem (`translations/de.json`, `translations/en.json`)
- Code-Kommentare erscheinen in beiden Sprachen
- Variablen- und Funktionsnamen sind auf Englisch
- Jarvis spricht Deutsch mit dem Benutzer (Persönlichkeits-Prompts auf Deutsch)

## Wichtige Dateien für Kontext

| Zweck | Datei | Hinweis |
|-------|-------|---------|
| Add-on Einstiegspunkt | `addon/rootfs/opt/mindhome/app.py` | Globales `_deps` Dict |
| Datenbankmodelle | `addon/rootfs/opt/mindhome/models.py` | ~99KB, eigene Migrationen |
| DB-Session-Verwaltung | `addon/rootfs/opt/mindhome/db.py` | Context Manager bevorzugen |
| HA-Verbindung | `addon/rootfs/opt/mindhome/ha_connection.py` | WebSocket kann deadlocken |
| Mustererkennung | `addon/rootfs/opt/mindhome/pattern_engine.py` | ~106KB, beeinflusst gelerntes Verhalten |
| Event-Bus | `addon/rootfs/opt/mindhome/event_bus.py` | Thread-safe Pub/Sub |
| Assistent Einstiegspunkt | `assistant/assistant/main.py` | ~359KB, Telemetrie-Deaktivierung |
| KI-Brain/Orchestrator | `assistant/assistant/brain.py` | ~629KB, per Grep durchsuchen |
| Persönlichkeit | `assistant/assistant/personality.py` | ~179KB, Sarkasmus + Stimmung |
| LLM Function Calling | `assistant/assistant/function_calling.py` | ~419KB, 50+ Tools |
| Proaktiv-Manager | `assistant/assistant/proactive.py` | ~378KB, Event-getrieben |
| Assistent-Konfiguration | `assistant/config/settings.yaml` | ~60KB YAML |
| Versionsverwaltung | `addon/rootfs/opt/mindhome/version.py` | Single Source of Truth |
| CI Pipeline | `.github/workflows/ci.yml` | 5 Jobs |
| Test-Fixtures | `assistant/tests/conftest.py` | Globale Mocks |
