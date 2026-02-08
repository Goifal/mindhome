# MindHome v0.5.0 – Release Notes

## Dateien (12.486 Zeilen)

| Datei | Zeilen | Beschreibung |
|---|---|---|
| `app.jsx` | 4.368 | React Frontend |
| `app.py` | 3.917 | Flask Backend + API |
| `ha_connection.py` | 532 | HA WebSocket/REST |
| `models.py` | 850 | SQLAlchemy Models + Migrations |
| `ml/pattern_engine.py` | 1.405 | Mustererkennung |
| `ml/automation_engine.py` | 1.328 | Automatisierung |
| `ml/__init__.py` | 3 | ML Package |
| `config.yaml` | 27 | HA Add-on Config |
| `run.sh` | 56 | Startup Script |
| `icon.png` / `logo.png` | — | Branding |

## 68 Verbesserungen

### Stabilität (1–15)
- #1 Healthcheck mit Device Health + Memory
- #2 Graceful Shutdown (WAL Checkpoint, Flush)
- #3 Rate Limiting (120 req/min)
- #5 Ingress Token Forwarding
- #6 DB Auto-Vacuum
- #10 Startup Self-Test
- #11 WebSocket Reconnect Counter (max 20)
- #12 Event Batching
- #13 Request Middleware
- #14 Input Sanitization
- #15 Migration Rollback Safety

### Performance (31–36)
- #32 API Response Cache (30s TTL)
- #33 SQLite QueuePool + check_same_thread
- #35 Thread-safe WS ID Generation
- #36 Batch Callbacks
- #39 Retry mit Exponential Backoff

### Intelligenz (22–30, 51–58)
- #22 Confidence Decay (stale patterns)
- #23 Urlaubsmodus (Pause + Simulation)
- #24 Device Health Check (Batterie, Erreichbarkeit)
- #25 Energie-Dashboard API
- #26 Pattern Conflict Detection
- #27 Saisonale Gewichtung
- #28 Kalender-Integration
- #29 Szenen-Erkennung
- #30 TTS Announcement
- #40 Watchdog Timer
- #41 Connection Stats
- #51 Confidence Explanation
- #53 Lernen aus Undo
- #54 Tageszeit-Clustering
- #55 Abwesenheits-Simulation
- #56 Cross-Room Korrelation
- #57 Wetter-adaptive Muster
- #58 Gäste-Erkennung

### Frontend UX (4, 7–9, 16–21, 43, 49–50)
- #4 Error Boundary (Crash-Isolation)
- #8 Toast Stacking (max 5)
- #9 Mobile Responsive CSS
- #16 Keyboard Shortcuts (Esc, N, D)
- #17 Skeleton Loading
- #43 Onboarding Checkliste
- #49 Auto Theme (System)
- #50 CSS Transitions

### Admin & Wartung (42, 60–64)
- #42 Debug Mode API + UI
- #44 Device Groups API
- #55 Vacation Mode API + UI
- #60 Audit Log
- #61 Auto-Backup (täglich, 7 behalten)
- #62 Update Checker (Stub)
- #63 CSV/JSON Export + UI
- #64 Diagnose-Paket API

### Barrierefreiheit (65–68)
- #65 ARIA Labels
- #66 Tab-Navigation + Focus-Visible
- #67 High Contrast Mode (CSS)
- #68 Schriftgröße S/M/L

## Bugfixes in dieser Version
1. `system/frontend-error` Route fehlte
2. `ContextBuilder` Session-Crash bei Vacation-Query
3. SQLite `pool_size` ohne `QueuePool` → SQLAlchemy Error
4. `config.yaml` Version veraltet
5. Backend-APIs ohne Frontend-Anbindung
