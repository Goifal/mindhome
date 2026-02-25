MindHome - Projektstruktur / Project Structure
================================================

mindhome/
├── repository.yaml                         # HA Add-on Store Konfiguration
├── README.md                               # Dokumentation DE + EN
├── STRUCTURE.md                            # Diese Datei
│
├── shared/                                 # Gemeinsame Schemas & Konstanten
│   ├── __init__.py
│   ├── constants.py                        # Ports, Events, Moods, Autonomy Levels
│   └── schemas/                            # Pydantic-Schemas
│       ├── __init__.py
│       ├── chat_request.py                 # ChatRequest Schema
│       ├── chat_response.py                # ChatResponse Schema
│       └── events.py                       # MindHomeEvent Schema
│
├── assistant/                              # MindHome Assistant (KI-Backend, PC 2)
│   ├── Dockerfile                          # Python 3.12-slim Container
│   ├── docker-compose.yml                  # Assistant + ChromaDB + Redis
│   ├── requirements.txt                    # Python-Abhaengigkeiten
│   ├── install.sh                          # Ein-Klick-Installation
│   ├── .env.example                        # Konfigurations-Vorlage
│   ├── config/
│   │   └── settings.yaml                   # Hauptkonfiguration
│   └── assistant/                          # Python-Package (22 Module)
│       ├── __init__.py
│       ├── main.py                         # FastAPI Server (:8200)
│       ├── brain.py                        # Orchestrator (verbindet alles)
│       ├── config.py                       # Settings-Loader (.env + YAML)
│       ├── context_builder.py              # Kontext-Sammlung (HA + Memory)
│       ├── model_router.py                 # Modell-Auswahl (fast vs. smart)
│       ├── ollama_client.py                # Ollama REST API Client
│       ├── ha_client.py                    # Home Assistant REST API Client
│       ├── personality.py                  # Persoenlichkeits-Engine
│       ├── mood_detector.py                # Stimmungserkennung
│       ├── memory.py                       # 3-Schichten-Gedaechtnis
│       ├── semantic_memory.py              # Fakten-Speicher (ChromaDB + Redis)
│       ├── memory_extractor.py             # LLM-basierte Fakten-Extraktion
│       ├── function_calling.py             # 10 Tool-Funktionen
│       ├── function_validator.py           # Sicherheits-Checks
│       ├── action_planner.py               # Multi-Step Aktionsplanung
│       ├── proactive.py                    # Proaktive Meldungen
│       ├── feedback.py                     # Adaptives Feedback-Lernen
│       ├── autonomy.py                     # Autonomie-Level 1-5
│       ├── activity.py                     # Aktivitaetserkennung
│       ├── summarizer.py                   # Tages-/Wochen-/Monats-Summaries
│       └── websocket.py                    # WebSocket-Verbindungsmanager
│
├── esphome/                               # ESPHome Voice Satellite Configs
│   ├── m5-atom-echo-test.yaml             # M5Stack Atom Echo (Test, eingebauter Speaker)
│   ├── secrets.yaml.example               # Vorlage fuer WiFi + API Credentials
│   └── .gitignore                         # Schuetzt secrets.yaml
│
├── addon/                                  # MindHome Add-on (HA, PC 1)
│   ├── config.yaml                         # Add-on Konfiguration (Ingress, Permissions)
│   ├── Dockerfile                          # Container-Build
│   └── rootfs/opt/mindhome/               # Anwendungscode
│       ├── run.sh                          # Startskript
│       ├── requirements.txt                # Python-Abhaengigkeiten
│       ├── app.py                          # Flask Backend + API Routen
│       ├── models.py                       # Datenbank-Modelle (SQLAlchemy)
│       ├── init_db.py                      # Datenbank-Initialisierung
│       ├── ha_connection.py                # HA WebSocket + REST API Verbindung
│       ├── routes/                         # API-Routen (15 Blueprints)
│       ├── engines/                        # 14 Intelligenz-Engines
│       ├── domains/                        # 23 Domain-Plugins
│       ├── translations/                   # Uebersetzungen (DE + EN)
│       └── static/frontend/               # React Frontend
│
└── docs/                                   # Dokumentation
    ├── UPGRADE_v0.6.0.md                   # Phase 3.5 Upgrade Notes
    └── PROJECT_MINDHOME_ASSISTANT.md       # Assistant Projekt-Dokumentation


Architektur:
============

PC 1: HAOS (Intel NUC)              PC 2: Assistant Server (Ubuntu)
┌─────────────────────────┐          ┌─────────────────────────────┐
│  Home Assistant          │          │  Ollama (Qwen 2.5 LLM)     │
│  MindHome Add-on (:8099) │◄── LAN──►│  MindHome Assistant (:8200) │
│  Whisper (STT)           │          │  ChromaDB (:8100) Memory    │
│  Piper (TTS)             │          │  Redis (:6379) Cache        │
└─────────────────────────┘          └─────────────────────────────┘
