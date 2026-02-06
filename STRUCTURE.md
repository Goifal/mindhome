MindHome - Projektstruktur / Project Structure
================================================

mindhome/
├── repository.yaml                         # HA Add-on Store Konfiguration
├── README.md                               # Dokumentation DE + EN
│
├── addon/                                  # Das Add-on
│   ├── config.yaml                         # Add-on Konfiguration (Ingress, Permissions)
│   ├── Dockerfile                          # Container-Build
│   │
│   └── rootfs/opt/mindhome/               # Anwendungscode
│       ├── run.sh                          # Startskript
│       ├── requirements.txt                # Python-Abhängigkeiten
│       ├── app.py                          # Flask Backend + API Routen
│       ├── models.py                       # Datenbank-Modelle (SQLAlchemy)
│       ├── init_db.py                      # Datenbank-Initialisierung
│       ├── ha_connection.py                # HA WebSocket + REST API Verbindung
│       │
│       ├── translations/                   # Übersetzungen
│       │   ├── de.json                     # Deutsch
│       │   └── en.json                     # Englisch
│       │
│       ├── domains/                        # [Teil C] Domain Plugin-System
│       │   └── .gitkeep                    # (wird in Teil C gefüllt)
│       │
│       ├── ml/                             # [Phase 2] Machine Learning Engine
│       │   └── .gitkeep                    # (wird in Phase 2 gefüllt)
│       │
│       ├── utils/                          # Hilfsfunktionen
│       │   └── .gitkeep                    # (wird nach Bedarf gefüllt)
│       │
│       └── static/frontend/               # [Teil B] React Frontend
│           └── .gitkeep                    # (wird in Teil B gefüllt)
│
└── docs/                                   # [Teil E] Dokumentation + Logo
    └── .gitkeep                            # (wird in Teil E gefüllt)


Status:
=======
[✅] Teil A - Backend Grundgerüst          (fertig)
[⏳] Teil B - Frontend (React)             (als nächstes)
[⏳] Teil C - Domain Plugin-System         (danach)
[⏳] Teil D - Onboarding + Personen-Mgr    (danach)
[⏳] Teil E - Logo + Feinschliff + README  (zuletzt)
