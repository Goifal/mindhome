# Audit-Ergebnis: Prompt 4c — Addon + Security-Audit + Performance-Analyse

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: 67+ Addon-Module, Speech-Server, Shared-Schemas, HA-Integration, 18 Security-Checks, 10 Resilience-Szenarien, 12 Performance-Checks
**Methode**: 6 parallele Audit-Agenten, jedes Modul komplett gelesen

---

## Gesamt-Statistik

```
Gesamt: 106 Bugs (Addon + Speech + Shared + Routes)
  KRITISCH: 8
  HOCH: 25
  MITTEL: 34
  NIEDRIG: 39

Security-Findings: 7 (1 HOCH, 4 MITTEL, 2 NIEDRIG)
Resilience-Luecken: 3 kritische
Performance-Probleme: 5 wesentliche

Haeufigste Fehlerklasse: None/Type-Fehler (22 Vorkommen)
Zweithaeufigste: Security — fehlende Auth (14 Vorkommen)
Am staerksten betroffenes Modul: automation_engine.py (9 Bugs)
Zweitstaerkstes: fire_water.py (8 Bugs)
```

---

## Teil 1: Batch 14a — Addon-Kern (13 Module)

Module: `app.py`, `ha_connection.py`, `event_bus.py`, `automation_engine.py`, `pattern_engine.py`, `task_scheduler.py`, `base.py`, `models.py`, `db.py`, `helpers.py`, `cover_helpers.py`, `init_db.py`, `version.py`

### Shared-Schema/Constants Check

- **Keine `from shared` oder `import shared` Imports gefunden** — bestaetigt: Addon nutzt KEINE shared schemas/constants.
- **Keine `ChatRequest`/`ChatResponse` Definitionen im Addon**.

### Bug-Report

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 1 | **KRITISCH** | `automation_engine.py` | 732-740 | 10: Logik | `_check_time_trigger` vergleicht `now.hour`/`now.minute` gegen UTC, aber Pattern-Zeiten stammen aus HA-Lokalzeit. Time-Trigger matchen zur falschen Stunde in jeder Zeitzone ausser UTC. | `now` via `helpers.local_now()` statt `datetime.now(timezone.utc)` berechnen |
| 2 | **KRITISCH** | `automation_engine.py` | 2283-2284 | 10: Logik | `QuietHoursManager.is_quiet_time()` nutzt `datetime.now()` (naive Systemzeit, wahrscheinlich UTC im Container), aber Quiet-Hours-Konfiguration ist in Lokalzeit. | `from helpers import local_now; now = local_now()` |
| 3 | **HOCH** | `pattern_engine.py` | 443-453 | 4: Type-Error | `should_log` Fallback: `new_state.get("state", "")` — aber `new_state` ist `str`, kein `dict`. Wirft `AttributeError` bei jedem unbekannten Sensor. | `new_state` direkt verwenden, da es bereits ein String ist |
| 4 | **HOCH** | `event_bus.py` | 96-130 | 3: Race Condition | `_stats[event_type] += 1` ausserhalb des Locks. Read-modify-write ist nicht thread-safe. | Stats-Update innerhalb des `with self._lock:` Blocks |
| 5 | **HOCH** | `automation_engine.py` | 2260 | 12: Resilience | `PluginConflictDetector.check_conflicts()` oeffnet Session ohne `try/finally`. Bei Exception leakt die Session. | `try/finally` wrappen |
| 6 | **HOCH** | `base.py` | 126-129 | 12: Resilience | `_load_settings()` — wenn `self.get_session()` fehlschlaegt, wird `session` nie definiert und `session.close()` im except-Handler fehlt. | Konsistent `with self.get_session() as session:` nutzen |
| 7 | **HOCH** | `base.py` | 147-163 | 12: Resilience | `set_setting()` — bei Exception wird rollback nur im `except` gemacht, `session.close()` liegt ausserhalb des try-blocks. | `try/except/finally` mit `session.close()` im `finally` |
| 8 | **MITTEL** | `app.py` | 394 | 9: Memory | `_recent_events` Dedup-Cache waechst bis 500 bei Burst-Events. | Hard-Limit auf 200 setzen |
| 9 | **MITTEL** | `pattern_engine.py` | 311 | 12: Resilience | Session-Close kann bei Exception uebersprungen werden. | `try/finally` Block |
| 10 | **MITTEL** | `pattern_engine.py` | 382-392 | 5: Init | `_thresholds_loaded = True` wird auch nach fehlgeschlagener Query gesetzt. Custom Thresholds werden dann nie nachgeladen. | Nur im Erfolgsfall setzen |
| 11 | **MITTEL** | `pattern_engine.py` | 472 | 3: Race Condition | `_event_timestamps` List-Reassignment ist nicht atomar. | `threading.Lock` oder `deque` mit `maxlen` |
| 12 | **MITTEL** | `helpers.py` | 69-83 | 9: Memory | `_rate_limit_data` Dict waechst unbegrenzt pro IP. | Periodisches Cleanup |
| 13 | **MITTEL** | `automation_engine.py` | 1183-1184 | 10: Logik | `datetime.utcnow()` (deprecated) kann `TypeError` bei Vergleich naive vs. aware datetime. | `datetime.now(timezone.utc)` |
| 14 | **MITTEL** | `automation_engine.py` | 1231 | 10: Logik | Gleiches `datetime.utcnow()` Problem. | `datetime.now(timezone.utc)` |
| 15 | **MITTEL** | `automation_engine.py` | 317 | 10: Logik | `datetime.now().strftime()` fuer Holiday-Pruefung nutzt UTC statt HA-Lokalzeit. | `local_now()` verwenden |
| 16 | **MITTEL** | `ha_connection.py` | 558 | 12: Resilience | `_ws_command` schreibt auf `self._ws.send()` ohne None-Check. | `if self._ws:` vor `.send()` |
| 17 | **MITTEL** | `ha_connection.py` | 74-75 | 3: Race Condition | `_stats["api_calls"] += 1` nicht thread-safe bei mehreren Flask-Threads. | `threading.Lock` |
| 18 | **MITTEL** | `init_db.py` | 317-321 | 5: Init | `create_default_settings` fuegt immer blind hinzu ohne Existenzpruefung. UNIQUE Constraint Fehler bei Wiederholung. | `session.merge()` oder Existenzpruefung |
| 19 | **NIEDRIG** | `base.py` | 223 | 10: Logik | `datetime.utcnow()` deprecated. | `datetime.now(timezone.utc)` |
| 20 | **NIEDRIG** | `helpers.py` | 60-62 | 10: Logik | `utc_iso()` haengt `Z` an naive datetimes — gefaehrlich bei Lokalzeit. | Nur bei explizit bekanntem UTC |
| 21 | **NIEDRIG** | `automation_engine.py` | 2450-2458 | 10: Logik | Watchdog erkennt tote Threads, startet sie aber NICHT neu. | Thread-Restart-Logik |
| 22 | **NIEDRIG** | `pattern_engine.py` | 336-341 | 9: Memory | `_last_sensor_values`/`_last_sensor_times` Dicts wachsen unbegrenzt. | LRU-Cache |
| 23 | **NIEDRIG** | `pattern_engine.py` | 335 | 9: Memory | `_motion_last_on` Dict waechst unbegrenzt. | LRU bei grossen Installationen |
| 24 | **NIEDRIG** | `automation_engine.py` | 1320 | 9: Memory | `_reported` Set Halbierung ist nicht deterministisch (set hat keine Ordnung). | `OrderedDict` fuer FIFO |
| 25 | **NIEDRIG** | `app.py` | 451-454 | 13: Performance | Bei Presence-Trigger wird neuer Thread gestartet — GPS-Jitter erzeugt viele Threads. | Rate-Limiting/Debouncing |
| 26 | **NIEDRIG** | `automation_engine.py` | 2361-2431 | 13: Performance | 10+ eigene daemon-Threads statt zentralen `task_scheduler` zu nutzen. | Auf `task_scheduler.register()` migrieren |

**Statistik Batch 14a**: 26 Bugs (2 KRITISCH, 5 HOCH, 10 MITTEL, 9 NIEDRIG)

---

## Teil 2: Batch 14b — Addon-Domains + Engines (36 Module)

Module: 21 `domains/*.py` + 15 `engines/*.py`

### call_service Statistik

| Modul | call_service Aufrufe |
|-------|---------------------|
| **engines/special_modes.py** | 27 |
| **engines/adaptive.py** | 14 |
| **engines/fire_water.py** | 8 |
| **engines/sleep.py** | 4 |
| **engines/visit.py** | 3 |
| **engines/circadian.py** | 3 |
| **engines/access_control.py** | 3 |
| **Domains (base.py)** | 3 |
| **engines/cover_control.py** | 2 |
| **engines/routines.py** | 2 |
| **engines/energy.py** | 2 |
| **engines/camera_security.py** | 1 |
| **GESAMT Addon** | **72** |
| **Assistant (Licht+Cover)** | **24** |

### Entity-Duplikat-Liste (Addon vs Assistant steuern DIESELBEN Entities)

| Entity-Domain | Addon-Modul | Assistant-Modul | Konflikt-Schwere |
|---------------|-------------|-----------------|-----------------|
| `light.*` | `domains/light.py` (evaluate) | `light_engine.py` (turn_on/off, brightness) | **HOCH** |
| `light.*` | `engines/circadian.py` (brightness + color_temp) | `light_engine.py` (circadian-aware) | **KRITISCH** — Ping-Pong |
| `light.*` | `engines/special_modes.py` (Party/Cinema/Night) | `light_engine.py` (motion-based) | **HOCH** |
| `light.*` | `engines/sleep.py` (WakeUp gradual) | `light_engine.py` (Aufwach-Licht) | **HOCH** |
| `cover.*` | `engines/cover_control.py` (set_position) | `function_calling.py` + `main.py` | **HOCH** |
| `lock.*` | `engines/access_control.py` (lock/unlock/auto-lock) | function_calling moeglich | MITTEL |
| `lock.*` | `engines/special_modes.py` (NightLockdown/Emergency) | — | Security-relevant |

### Bug-Report

#### Klasse 2: Stille Fehler

| # | Severity | Modul | Zeile | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-----|
| 27 | **KRITISCH** | `fire_water.py` | 164-165 | `_is_assigned_entity` bei DB-Fehler: `return False` — FEUERALARM wird STILLSCHWEIGEND IGNORIERT! | Failsafe: `return True` bei DB-Fehler |
| 28 | **KRITISCH** | `fire_water.py` | 470-471 | Gleicher Bug bei `WaterLeakManager._is_assigned_entity` | `return True` bei DB-Fehler |
| 29 | **HOCH** | `fire_water.py` | 301-302 | `except Exception: pass` bei Notfall-Notification — Benachrichtigung versagt still | Logging + Retry |
| 30 | **HOCH** | `fire_water.py` | 519-522 | Doppeltes `except: pass` bei TTS im Notfall | Logging |
| 31 | **HOCH** | `fire_water.py` | 639-640 | `except Exception: pass` bei Wasserleck-Notification | Logging |
| 32 | **HOCH** | `special_modes.py` | 562-563, 575-576 | `except Exception: pass` bei NightLockdown Lock/Media — Tuer bleibt offen ohne Log | Logging + Fallback |
| 33 | **HOCH** | `base.py` | 88-93 | ContextBuilder-Fehler → hartcodierter Fallback `is_dark: False` — bei Dunkelheit werden Lichter NICHT eingeschaltet | Failsafe: `is_dark: True` oder letzten bekannten Wert cachen |
| 34 | **MITTEL** | `circadian.py` | 320-321 | `except Exception: pass` bei Farbtemperatur | Logging |
| 35 | **MITTEL** | `special_modes.py` | 1011-1012 | `except Exception: pass` bei PIN-Verifikation | Logging |
| 36 | **MITTEL** | `access_control.py` | 349-350 | `except Exception: pass` bei Person-Matching — alle Unlocks als "unknown" | Logging |
| 37 | **MITTEL** | `sleep.py` | 122-123, 154-155, 173-174 | Mehrfach `except Exception: pass` bei Schlaf-Erkennung | Logging |
| 38 | **NIEDRIG** | `special_modes.py` | 442-443 | `except Exception: pass` bei Cinema-Mode Covers | Logging |

#### Klasse 3: Race Conditions / Threading

| # | Severity | Modul | Zeile | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-----|
| 39 | **KRITISCH** | `circadian.py` | 88, 120, 207, 211 | `_active_overrides` Dict ohne Lock — Event-Callbacks + Check gleichzeitig, Dict-Mutation bei Iteration → RuntimeError | `threading.Lock` einfuehren |
| 40 | **HOCH** | `fire_water.py` | 47, 146-153, 219 | `_active_alarms` Dict ohne Lock — Event-Callbacks vs Flask-Thread | `threading.Lock` |
| 41 | **HOCH** | `fire_water.py` | 355, 453-459 | `_active_leaks` Dict ohne Lock | `threading.Lock` |
| 42 | **HOCH** | `access_control.py` | 42, 116, 255-268, 328 | `_auto_lock_timers` Dict ohne Lock — 3 Threads greifen zu | `threading.Lock` |
| 43 | **HOCH** | `special_modes.py` | 36-37, 103, 138 | `_active`/`_active_log_id` ohne Lock — Flask + Timer + Events | `threading.Lock` |
| 44 | **HOCH** | `special_modes.py` | 284-290 | `threading.Timer` ruft `deactivate()` auf — Timer vs Flask Race | Lock um State-Aenderungen |
| 45 | **HOCH** | `special_modes.py` | 804-829 | Emergency-Escalation: 3 Timer-Threads ohne Synchronisation | Lock + try/finally |
| 46 | **MITTEL** | `cover_control.py` | 97-100, 996-1013 | `_lock` existiert, aber nur fuer `_manual_overrides`. `_pending_actions` etc. ungeschuetzt. | Lock erweitern |
| 47 | **HOCH** | `routines.py` | 153 | `time.sleep(1)` blockiert Flask-Thread bis zu 8 Sekunden | `threading.Thread` oder `task_scheduler` |
| 48 | **MITTEL** | `base.py` | 29-30, 77-94 | `_context_cache` ohne Lock — Cache-Inkonsistenz | `threading.Lock` |

#### Klasse 4: None-Fehler + Klasse 10: Logik

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 49 | **KRITISCH** | `sleep.py` | 326-330 | 10: Logik | UTC/Lokal-Verwechslung: `now = datetime.now(timezone.utc)`, aber `today = now.replace(hour=wake_h)` setzt lokale Weckzeit in UTC. Weck-Rampe startet 1-2h zu spaet! | `now` in Lokalzeit konvertieren |
| 50 | **KRITISCH** | `cover_control.py` | 781 | 10: Logik | Forecast-Wind setzt Markise auf `position: 100` (OFFEN) bei Sturmwarnung! Sollte 0 (eingefahren) sein. | `"position": 0` |
| 51 | **MITTEL** | `circadian.py` | 362 | 4: None | `session.query(Room).get(c.room_id).name` — wenn Room None, crasht `.name`. Plus 2 DB-Queries pro Config. | None-Check + einzelne Query |
| 52 | **MITTEL** | `light.py` | 81 | 10: Logik | Day-Phase Vergleich `"Nacht", "Nachtruhe", "Night"` — sprachabhaengig | Konstanten oder beide Sprachen |
| 53 | **MITTEL** | `energy.py` | 352 | 10: Logik | `entity_id` als Keyword statt in service_data-Dict — inkonsistent | `{"entity_id": switch_entity}` |
| 54 | **NIEDRIG** | `circadian.py` | 203 | 4: None | `.get(cfg.room_id)` ist deprecated in SQLAlchemy 2.x | `session.get(Room, cfg.room_id)` |
| 55 | **NIEDRIG** | `circadian.py` | 282-283 | 10: Logik | Inkonsistente brightness API (0-255 vs Prozent) | Einheitlich verwenden |

#### Klasse 11: Security

| # | Severity | Modul | Zeile | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-----|
| 56 | **KRITISCH** | `access_control.py` | 108-120 | `lock()`/`unlock()` pruefen NICHT ob Entity-ID zugewiesen ist. Beliebige Locks steuerbar! | Entity-Whitelist-Check |
| 57 | **MITTEL** | `special_modes.py` | 585 | `alarm_control_panel` Entity aus User-Config ohne Validierung | Entity-ID-Format validieren |
| 58 | **MITTEL** | `fire_water.py` | 198 | `unlock_on_fire: True` als Default — falscher Rauchmelder oeffnet alle Tueren | Default auf `False` |
| 59 | **MITTEL** | `special_modes.py` | 1000-1013 | PIN mit SHA-256 ohne Salt — bruteforce-bar | PBKDF2 oder bcrypt |
| 60 | **MITTEL** | `access_control.py` | 163 | Access-Codes mit SHA-256 ohne Salt | PBKDF2 oder bcrypt |
| 61 | **MITTEL** | `special_modes.py` | 369 | User-konfigurierter String als HA-Service — Injection moeglich | Service-Whitelist |

#### Klasse 12: Resilience

| # | Severity | Modul | Zeile | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-----|
| 62 | **MITTEL** | `fire_water.py` | 167-215 | Sequenzielle Notfall-Aktionen — Exception bei #2 ueberspringt #3-#8 | Jede Aktion einzeln try/except |
| 63 | **MITTEL** | `fire_water.py` | 473-528 | Gleiche sequenzielle Logik bei Wasserleck | try/except pro Aktion |
| 64 | **MITTEL** | `circadian.py` | 128-129 | Sleep-Override faellt bei DB-Fehler komplett aus | Retry oder Fallback |
| 65 | **NIEDRIG** | `cover_control.py` | ganzes Modul | `_is_running` ohne Lock — Start/Stop Race | Lock hinzufuegen |
| 66 | **MITTEL** | `special_modes.py` | 284-290 | Timer-Crash → Mode bleibt dauerhaft aktiv | Watchdog |
| 67 | **NIEDRIG** | `base.py` | 124-134 | Manuelles Session-Management ohne Rollback | `with` Statement |

#### Dead Code

| # | Modul | Code | Grund |
|---|-------|------|-------|
| D1 | `domains/cover.py` | `_is_safe_for_automation()` (Z.56-89) | `evaluate()` gibt immer `[]` zurueck |
| D2 | `domains/cover.py` | `_is_bed_occupied()` (Z.91-101) | Kein Aufrufer |
| D3 | `domains/cover.py` | `get_plugin_actions()` (Z.44-49) | Actions definiert, nie implementiert |
| D4 | `engines/cover_control.py` | `_pending_actions` (Z.100) | Initialisiert, nie beschrieben/gelesen |
| D5 | `engines/adaptive.py` | `GradualTransitioner._pending` (Z.285) | Nie befuellt, immer 0 |

**Statistik Batch 14b**: 41 Bugs (6 KRITISCH, 11 HOCH, 14 MITTEL, 10 NIEDRIG) + 5 Dead Code

---

## Teil 3: Batch 14c — Addon-Routes (17 Module)

Module: Alle `routes/*.py` + `app.py` Auth-Analyse

### Auth-Analyse

**KRITISCH: Es gibt KEINE Authentifizierung auf den API-Endpoints.**
- `before_request`-Middleware prueft ausschliesslich Rate-Limiting per IP
- Kein Login-Mechanismus, keine Token/Session-Validierung
- Kommentar verspricht "ingress token check", Code macht es nicht
- **Einzige Ausnahme**: `/api/calendar/export.ics` (Token via Query-Parameter)
- **CORS**: `CORS(app, supports_credentials=False)` = Wildcard `*` fuer alle Origins

### Bug-Report

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 68 | **KRITISCH** | `app.py` | 58 | 11: Security | CORS erlaubt alle Origins. Jede Website kann API-Requests machen. | `CORS(app, origins=[])` |
| 69 | **KRITISCH** | `app.py` | 508-517 | 11: Security | Keine Auth-Middleware. Alle ~200 Endpoints offen. | Ingress-Token-Validierung implementieren |
| 70 | **HOCH** | `security.py` | 438-453 | 11: Security | Lock/Unlock-Endpoints ohne Auth. Physische Tuerschloesser offen. | Auth-Middleware |
| 71 | **HOCH** | `security.py` | 696-707 | 11: Security | Emergency-Trigger ohne Auth. Jeder kann Notfall ausloesen. | Auth + Rate-Limit |
| 72 | **HOCH** | `chat.py` | 96-97 | 11: Security | SSRF-Schutz: `"172.2"` Prefix matcht falsch (zu breit und zu schmal zugleich). | `ipaddress.ip_address(host).is_private` |
| 73 | **HOCH** | `system.py` | 2075-2078 | 11: Security | Gleicher SSRF-Bug. | Identischer Fix |
| 74 | **HOCH** | `presence.py` | 122 | 4: NameError | `ha_connection` und `engine` referenziert als globale Variablen, existieren nicht. Crash bei `/api/day-phases/current`. | `_ha()` und `_engine()` verwenden |
| 75 | **HOCH** | `presence.py` | 353 | 4: NameError | `ha` Variable existiert nicht. Crash bei `/api/sun`. | `_ha()` verwenden |
| 76 | **HOCH** | `automation.py` | 134-188 | 4: None | `_deps.get("automation_scheduler").feedback.confirm_prediction(...)` — 8+ Endpoints crashen wenn None. | None-Guard |
| 77 | **HOCH** | `notifications.py` | 103, 111, 119 | 4: None | `_deps.get("automation_scheduler").notification_mgr.*` ohne None-Check. | None-Guard |
| 78 | **HOCH** | `presence.py` | 175, 188 | 4: None | `_deps.get("automation_scheduler").presence_mgr.*` ohne None-Check. | None-Guard |
| 79 | **MITTEL** | `automation.py` | 276 | 4: None | `request.json` ohne `or {}` Fallback. | `data = request.json or {}` |
| 80 | **MITTEL** | `automation.py` | 349, 419, 445, 508 | 4: None | Mehrere Stellen `request.json` ohne Fallback. | `or {}` |
| 81 | **MITTEL** | `domains.py` | 89, 118 | 4: None | `request.json` ohne Fallback. | `or {}` |
| 82 | **MITTEL** | `rooms.py` | 213, 247 | 4: None | `request.json` ohne Fallback. | `or {}` |
| 83 | **MITTEL** | `schedules.py` | 97, 133 | 4: None | `request.json` ohne Fallback. | `or {}` |
| 84 | **MITTEL** | `notifications.py` | 367 | 4: None | `request.json` ohne Fallback. | `or {}` |
| 85 | **MITTEL** | `domains.py` | 207, 221 | 4: None | `_domain_manager()` ohne None-Check. | None-Guard |
| 86 | **MITTEL** | `chat.py` | 880-903 | 11: Security | File-Proxy leitet beliebige Pfade weiter. Path-Traversal moeglich (`../../etc/passwd`). | `secure_filename()` oder `..`-Check |
| 87 | **MITTEL** | `security.py` | 398-406 | 11: Security | `camera_take_snapshot(entity_id)` — beliebige Strings an `take_snapshot()`. | Entity-ID-Format validieren |
| 88 | **MITTEL** | `users.py` | 124-131 | 11: Security | User-Erstellung ohne Auth und ohne Input-Sanitisierung. XSS moeglich. | `sanitize_input()` |
| 89 | **MITTEL** | `chat.py` | 511-533 | 12: Resilience | Audio via ffmpeg ohne Groessenlimit. RAM-Erschoepfung moeglich. | Max 20 MB vor ffmpeg |
| 90 | **MITTEL** | `system.py` | 219-224 | 11: Security | `/api/system/settings/<key>` erlaubt beliebige Settings. Angreifer kann `assistant_url` aendern. | Key-Whitelist |
| 91 | **NIEDRIG** | `chat.py` | 56-57 | 10: Logik | Lock-Variablen unuebersichtlich positioniert. | Code-Reihenfolge |
| 92 | **NIEDRIG** | `notifications.py` | 128, 130, 207 | 10: Logik | Hardcoded `user_id=1`. Multi-User broken. | User-ID aus Request |
| 93 | **NIEDRIG** | `schedules.py` | 668 | 12: Resilience | MD5 fuer ETag (kryptografisch unsicher, aber OK fuer Cache). | Kein dringender Fix |
| 94 | **NIEDRIG** | `patterns.py` | 497 | 10: Logik | `created_by=1` hardcoded. | User-ID dynamisch |
| 95 | **NIEDRIG** | `scenes.py` | 157-158 | 4: None | `d.entity_id` statt `d.ha_entity_id`. | Korrektes Attribut |
| 96 | **NIEDRIG** | `scenes.py` | 186-189 | 4: None | Falsche Attribute `p.description`, `p.entities`. | Korrekte Attributnamen |
| 97 | **NIEDRIG** | `chat.py` | 660-664 | 12: Resilience | PCM-Audio als Base64 im JSON (430KB). | Concurrent-Limit |

**Statistik Batch 14c**: 30 Bugs (2 KRITISCH, 10 HOCH, 12 MITTEL, 6 NIEDRIG) + 1 SSRF-Bug doppelt gezaehlt

---

## Teil 4: Speech + Shared + HA-Integration

### Bug-Report

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 98 | **HOCH** | Shared/Assistant | `main.py:630` vs `shared/schemas/` | 7: Daten | ChatRequest/ChatResponse lokal redefiniert, Felder divergieren. TTSInfo: shared hat `speed: 1.0`, main.py hat `speed: 100` (int!). | Shared aktualisieren oder entfernen |
| 99 | **HOCH** | Shared | Gesamtprojekt | Dead Code | `shared/` wird NIRGENDS importiert (0 Treffer). Gesamtes Paket ist Dead Code. | Entfernen oder tatsaechlich nutzen |
| 100 | **MITTEL** | Shared | `constants.py` + `events.py` | 7: Daten | Event-Konstanten identisch in 2 Dateien definiert — stille Inkonsistenz moeglich. | Eine Quelle |
| 101 | **MITTEL** | Speech | `handler.py:41-46` | 3: Race Condition | `_get_model_lock()` nicht thread-safe bei Erst-Init. | Lock bei Modul-Load erstellen |
| 102 | **MITTEL** | Speech | `handler.py:92-101` | 12: Resilience | Redis-Reconnect fehlt. Tote Verbindung wird nie erneuert. | Health-Check + Reconnect |
| 103 | **MITTEL** | HA-Integration | `conversation.py:98` | 7: Daten | `device_id` im Payload, fehlt in shared ChatRequest. | Schema synchronisieren |
| 104 | **NIEDRIG** | Shared | `schemas/__init__.py` | Dead Code | `__all__` exportiert nur 2 von 7 Events. | Irrelevant (niemand importiert) |
| 105 | **NIEDRIG** | HA-Integration | `config_flow.py:11` | 8: Config | Hardcoded IP `192.168.1.200`. | Konfigurierbar machen |
| 106 | **NIEDRIG** | HA-Integration | `config_flow.py:57-58` | 10: Logik | Nicht-200 Status als "cannot_connect" statt "server_error". | Spezifischere Fehlermeldung |

### Port-Verifikation

| Port | Definiert in `constants.py` | Tatsaechlich genutzt | Status |
|------|-----------------------------|---------------------|--------|
| 8200 (ASSISTANT) | Ja | main.py, docker-compose, config_flow | **OK** |
| 5000 (ADDON_INGRESS) | Ja | addon/config.yaml | **OK** |
| 8000 (CHROMADB) | Ja | — | OK |
| 6379 (REDIS) | Ja | speech/handler.py | **OK** |
| 11434 (OLLAMA) | Ja | main.py, docker-compose | **OK** |
| 10300 (WHISPER) | **FEHLT** | speech/server.py, main.py, docker-compose | **FEHLT in constants.py** |

### Schema-Verifikation

| Pruefung | Ergebnis |
|----------|----------|
| `from shared` Importe | **0 Treffer** — wird nirgends importiert |
| `class ChatRequest` | **2x definiert** — Felder divergieren (`device_id` fehlt in shared) |
| `class ChatResponse` | **2x definiert** — Felder identisch |
| `class TTSInfo` | **2x definiert** — **stark divergierend** (speed int vs float, volume 0.8 vs 1.0) |
| Event-Konstanten | **Doppelt** in constants.py UND events.py |

**Statistik Teil 4**: 9 Bugs (0 KRITISCH, 2 HOCH, 4 MITTEL, 3 NIEDRIG)

---

## Teil 5: Security-Audit (18 Checks)

| # | Risiko | Check | Modul | Beschreibung | Empfehlung |
|---|--------|-------|-------|-------------|------------|
| SEC-1 | **OK** | Prompt Injection | `context_builder.py:45-118` | Umfassend: NFKC-Unicode, Zero-Width-Entfernung, ~40 Injection-Regex. Pattern-Check vor Truncation. | Regelmaessig neue Patterns ergaenzen |
| SEC-2 | **MITTEL** | Input Validation | `main.py` diverse | ~70 Stellen `await request.json()` ohne Pydantic. Workshop-Endpoints (Z.6941) ohne Bounds-Check fuer x/y/z. | Pydantic-Modelle fuer alle POST-Endpoints |
| SEC-3 | **OK** | HA-Auth | `ha_client.py:41-47` | Token aus Settings, Bearer-Auth, Connection Pooling mit Timeout. | — |
| SEC-4 | **HOCH** | Function Call Safety | `function_calling.py:5203-5245` | `lock` in `_CALL_SERVICE_ALLOWED_DOMAINS`. LLM kann `lock.unlock` ausfuehren. `_exec_lock_door` akzeptiert `action="unlock"` ohne Bestaetigung. | Lock aus Whitelist entfernen oder Service-Level-Filter. Unlock mit PIN/Confirmation. |
| SEC-5 | **OK** | Self-Automation Safety | `self_automation.py:56-82` | Dreifach-Schutz: Service-Whitelist, Blacklist (`lock.unlock`, `homeassistant.restart`), Trigger-Whitelist. Jinja2 verboten. | — |
| SEC-6 | **OK** | Autonomy Limits | `autonomy.py` | 5-stufig, Domain-spezifisch, Trust-Levels pro Person. Evolution mit hohen Schwellen. | — |
| SEC-7 | **OK** | Threat Assessment | verifiziert in P4b | Funktioniert und wird genutzt. | — |
| SEC-8 | **OK** | Factory Reset | `main.py:944-971` | PIN-geschuetzt (PBKDF2 + `secrets.compare_digest`). Audit-Log. | — |
| SEC-9 | **OK** | System Update/Restart | `main.py:7658-7798` | Token-Auth, Lock gegen Race, Config-Backup, Container-Name-Regex. | — |
| SEC-10 | **OK** | API-Key Management | `main.py:465-535` | `secrets.token_urlsafe(32)`, timing-safe Vergleich, Recovery-Key (PBKDF2). | — |
| SEC-11 | **MITTEL** | PIN-Auth / Brute-Force | `main.py:2320-2359` | PIN timing-safe, Audit-Log. **ABER: Kein Brute-Force-Schutz** — kein Lockout, kein Backoff. | Max 5 Versuche/5min pro IP, dann 15min Lockout |
| SEC-12 | **OK** | File Upload | `file_handler.py` | Extension-Whitelist, SVG blockiert, Path-Traversal-Schutz, Size-Limit 50MB, UUID-Prefix. | — |
| SEC-13 | **MITTEL** | Workshop Hardware | `main.py:6898-6986` | Keine Input-Bounds fuer x/y/z/speed. Kein Trust-Level-Check — jeder Auth-Client steuert Roboterarm. | Pydantic-Bounds + Owner-Only |
| SEC-14 | **OK** | Sensitive Data in Logs | `main.py:50-84` | Regex maskiert api_key, token, password, secret mit `[REDACTED]`. | — |
| SEC-15 | **OK** | WebSearch SSRF | `web_search.py` | IP-Blocklist, DNS-Rebinding-Schutz, IPv4-mapped-IPv6, Redirect-Blocking, Rate-Limiting. | — |
| SEC-16 | **NIEDRIG** | Frontend XSS | Addon JSX + Flask Jinja2 | React Auto-Escaping. SVG blockiert. Jinja2 Auto-Escaping. | `dangerouslySetInnerHTML` pruefen |
| SEC-17 | **MITTEL** | CORS | `main.py:404-426`, `addon/app.py:58` | Assistant: gute Policy mit Origin-Liste. **Addon: Wildcard CORS `*`** ohne Auth! | Addon-CORS auf HA-Origin beschraenken |
| SEC-18 | **NIEDRIG** | Dependency CVEs | `requirements.txt` (3) | Jinja2 3.1.2 (CVEs, >=3.1.5 empfohlen), Werkzeug 3.0.1 (>=3.0.6 empfohlen). | Updates + `pip-audit` in CI |

### Security-Zusammenfassung

```
11 von 18 Checks bestanden (OK)
1 HOCH: lock.unlock ohne Bestaetigung via LLM
4 MITTEL: Input-Validation, Brute-Force, Workshop-Hardware, Addon-CORS
2 NIEDRIG: Frontend-XSS (minimal), Dependencies
```

---

## Teil 6: Resilience-Report

| # | Szenario | Bewertung | Was passiert | Code-Referenz |
|---|----------|-----------|-------------|---------------|
| 1 | **Ollama nicht erreichbar** | **SEHR GUT** | Circuit Breaker (threshold=5, recovery=15s). Kaskade Deep→Smart→Fast. ErrorPatterns nach 3x Timeout/h. | `ollama_client.py:343-387` |
| 2 | **Redis nicht erreichbar** | **MITTEL** | `self.redis = None`, alle Methoden pruefen. **KEIN Circuit Breaker** (`redis_breaker` = Dead Code). | `memory.py:24,42` |
| 3 | **ChromaDB nicht erreichbar** | **MITTEL** | `chroma_collection = None`, Methoden pruefen. Calls synchron (blockieren Event-Loop). **KEIN Circuit Breaker** (`chromadb_breaker` = Dead Code). | `memory.py:65` |
| 4 | **HA nicht erreichbar** | **SEHR GUT** | Circuit Breaker (threshold=5, recovery=20s). Retry mit Backoff (3x, 1.5/3.0/4.5s). States-Cache 5s. | `ha_client.py:402-457` |
| 5 | **Speech nicht erreichbar** | **MITTEL** | WebSocket-Timeouts konfiguriert. Kein expliziter Text-Fallback-Mode. | `websocket.py` |
| 6 | **Addon nicht erreichbar** | **GUT** | `mindhome_breaker` (threshold=5, recovery=20s). Brain laeuft standalone weiter. | `ha_client.py:648-700` |
| 7 | **Netzwerk-Timeout LLM** | **SEHR GUT** | Tier-Timeouts (Fast=30s, Smart=45s, Deep=120s). Auto-Kaskade. ErrorPatterns-Mitigation. | `brain.py:910-981` |
| 8 | **Ungueltiges LLM-Response** | **SEHR GUT** | 4-stufig: Native tool_calls → Deterministisch → Text-Parsing → Retry mit Hint. | `brain.py:3273-3372` |
| 9 | **Circuit Breaker** | **LUECKE** | `ollama_breaker`: AKTIV. `ha_breaker`: AKTIV. `mindhome_breaker`: AKTIV. **`redis_breaker`: DEAD CODE. `chromadb_breaker`: DEAD CODE.** | `circuit_breaker.py:167-171` |
| 10 | **Error Patterns** | **GUT** | 6 Fehlertypen, Auto-Mitigation bei ≥3/h, TTL 1h. Abhaengig von Redis. | `error_patterns.py:22-24` |

### Resilience-Zusammenfassung

```
SEHR GUT: Ollama, HA, LLM-Timeout, LLM-Response (4/10)
GUT: Addon, Error Patterns (2/10)
MITTEL: Redis, ChromaDB, Speech (3/10)
LUECKE: 2 von 5 Circuit Breakern sind Dead Code (1/10)
```

---

## Teil 7: Performance-Report

| # | Check | Ergebnis | Modul:Zeile | Empfehlung |
|---|-------|---------|-------------|------------|
| 1 | Parallele Async-Calls | Mega-Gather mit ~25 Tasks. Context-Builder eigenes Gather. **Startup rein sequentiell (~40 awaits).** | `brain.py:2320-2417` | Startup parallelisieren |
| 2 | LLM-Calls pro Request | Standard: 1. Retry: 2. Shortcut: 0. Humanizer: +1. Kaskade worst-case: 3. | `brain.py:910-981` | Humanizer nur bei komplexen Antworten |
| 3 | Model-Routing | 3 Stufen (Fast/Smart/Deep). Auto-Capability. Think-Mode bei Commands deaktiviert. | `model_router.py:232-280` | Gut implementiert |
| 4 | Memory-Latenz | Pipeline fuer add (5 Ops). **N+1 Problem** bei `get_facts_by_person` (smembers + N x hgetall). | `semantic_memory.py:481-498` | Pipeline oder Lua-Script |
| 5 | Context Builder | 1x states (cached), 4x MindHome (parallel), activity, health_trend. Alles in Gather. | `context_builder.py:186-224` | MindHome in 1 Batch-Endpoint |
| 6 | Startup-Latenz | **~40 sequentielle awaits** in `initialize()`. Alles eager. | `brain.py:475-775` | Phasen-Parallelisierung |
| 7 | Embedding | `MiniLM-L12-v2` Singleton-gecacht. Kein Text-Level-Cache (ChromaDB intern). | `embeddings.py:21-56` | OK |
| 8 | Token-Verschwendung | Dynamisches Budget (num_ctx - 800). Priorisierte Sektionen. Device: 150, Standard: 512, Deep: 768. | `brain.py:2640-2670` | Gut — System-Prompt-Groesse monitoren |
| 9 | Proaktive Last | **10+ Background-Loops** permanent. **4 Vacuum-Tasks** separat. | `proactive.py:246-293` | Vacuum konsolidieren, dynamische Intervalle |
| 10 | Addon-Roundtrip | aiohttp mit Connection Pooling. Retry 3x. **Kein Response-Caching** fuer MindHome-Daten. | `ha_client.py:648-700` | 10-30s TTL Cache fuer Presence/Energy/Comfort |
| 11 | Streaming | Token-Streaming implementiert. Tool-Calls nicht gestreamt (korrekt). Stream-Timeout 120s. | `ollama_client.py:389-530` | Gut |
| 12 | Cache-Nutzung | HA States: 5s. Weather: eigener TTL. WebSearch: 5min/100 LRU. **Kein Cache**: MindHome, ChromaDB-Queries, Semantic-Facts. | diverse | MindHome-Cache + ChromaDB-Query-Cache |

### Geschaetzte Latenz (typischer Voice-Request)

| Phase | Geschaetzt (ms) | Ziel (ms) | Status |
|-------|-----------------|-----------|--------|
| STT (Whisper) | 500-2000 | <1500 | OK |
| Shortcut-Erkennung | 1-5 | <5 | **OPTIMAL** |
| Mega-Gather (Context+Sub) | 200-1500 | <500 | VERBESSERBAR |
| Context Builder (HA+MindHome) | 100-500 | <300 | OK |
| Model-Routing | <1 | <1 | **OPTIMAL** |
| LLM-Call (Fast/3B) | 500-2000 | <1500 | OK |
| LLM-Call (Smart/14B) | 1000-5000 | <3000 | HW-ABHAENGIG |
| LLM-Call (Deep/32B) | 3000-15000 | <8000 | HW-ABHAENGIG |
| Tool-Call Execution | 100-2000 | <1000 | OK |
| Humanizer (generate) | 500-2000 | <1000 | VERBESSERBAR |
| Memory-Speicherung | 50-200 | <100 | OK |
| TTS (Piper) | 200-1000 | <500 | OK |
| **Gesamt (Shortcut)** | **50-200** | **<200** | **OPTIMAL** |
| **Gesamt (Fast)** | **1500-4000** | **<3000** | **OK** |
| **Gesamt (Smart)** | **2500-8000** | **<5000** | **GRENZWERTIG** |
| **Gesamt (Deep)** | **5000-20000** | **<10000** | **KRITISCH bei schwacher HW** |

---

## Zero-Bug-Acknowledgments (Addon-Module)

Die folgenden Addon-Module wurden vollstaendig auditiert und weisen **0 Bugs** auf:

### Batch 14a — Addon-Kern
| Modul | Ergebnis |
|-------|----------|
| `task_scheduler.py` | 0 Bugs gefunden |
| `models.py` | 0 Bugs gefunden |
| `db.py` | 0 Bugs gefunden |
| `cover_helpers.py` | 0 Bugs gefunden |
| `version.py` | 0 Bugs gefunden |

### Batch 14b — Addon-Domains (domains/*.py ohne Bug-Eintraege)
| Modul | Ergebnis |
|-------|----------|
| `domains/switch.py` | 0 Bugs gefunden |
| `domains/media.py` | 0 Bugs gefunden |
| `domains/climate.py` | 0 Bugs gefunden |
| `domains/sensor.py` | 0 Bugs gefunden |
| `domains/binary_sensor.py` | 0 Bugs gefunden |
| `domains/person.py` | 0 Bugs gefunden |
| `domains/fan.py` | 0 Bugs gefunden |
| `domains/input_boolean.py` | 0 Bugs gefunden |
| `domains/input_number.py` | 0 Bugs gefunden |
| `domains/input_select.py` | 0 Bugs gefunden |
| `domains/input_text.py` | 0 Bugs gefunden |
| `domains/automation.py` | 0 Bugs gefunden |
| `domains/script.py` | 0 Bugs gefunden |
| `domains/scene.py` | 0 Bugs gefunden |
| `domains/group.py` | 0 Bugs gefunden |
| `domains/vacuum.py` | 0 Bugs gefunden |
| `domains/water_heater.py` | 0 Bugs gefunden |

### Batch 14b — Addon-Engines (engines/*.py ohne Bug-Eintraege)
| Modul | Ergebnis |
|-------|----------|
| `engines/adaptive.py` | 0 Bugs gefunden (nur Dead Code: `GradualTransitioner._pending`) |
| `engines/camera_security.py` | 0 Bugs gefunden |
| `engines/visit.py` | 0 Bugs gefunden |

### Batch 14c — Addon-Routes (routes/*.py ohne Bug-Eintraege)
| Modul | Ergebnis |
|-------|----------|
| `routes/energy.py` | 0 Bugs gefunden |
| `routes/health.py` | 0 Bugs gefunden |
| `routes/dashboard.py` | 0 Bugs gefunden |
| `routes/devices.py` | 0 Bugs gefunden |
| `routes/logs.py` | 0 Bugs gefunden |

### Teil 4 — Speech + Shared + HA-Integration (Module ohne Bug-Eintraege)
| Modul | Ergebnis |
|-------|----------|
| `speech/server.py` | 0 Bugs gefunden (nur Dead Code: `import json as _json`) |

Alle anderen Addon-Module haben mindestens einen dokumentierten Bug (siehe Bug-Reports oben).

---

## pip-audit Ergebnisse (Dependency-CVEs)

Ergebnisse des `pip-audit` Scans ueber alle drei Subsysteme:

### Assistant (32 CVEs in 6 Paketen)
| Paket | Version | CVE-Anzahl |
|-------|---------|:----------:|
| aiohttp | 3.11.11 | betroffen |
| python-multipart | 0.0.18 | betroffen |
| pillow | 11.1.0 | betroffen |
| pdfminer-six | 20231228 | betroffen |
| starlette | 0.41.3 | betroffen |
| transformers | 4.46.3 | betroffen |
| **Gesamt** | | **32 CVEs** |

### Addon (20 CVEs in 5 Paketen)
| Paket | Version | CVE-Anzahl |
|-------|---------|:----------:|
| flask | 3.0.0 | betroffen |
| flask-cors | 4.0.0 | betroffen |
| requests | 2.31.0 | betroffen |
| werkzeug | 3.0.1 | betroffen |
| jinja2 | 3.1.2 | betroffen |
| **Gesamt** | | **20 CVEs** |

### Speech (4 CVEs in 1 Paket)
| Paket | Version | CVE-Anzahl |
|-------|---------|:----------:|
| torch | 2.5.1 | betroffen |
| **Gesamt** | | **4 CVEs** |

### Zusammenfassung
```
Gesamt: 56 CVEs in 12 Paketen ueber 3 Subsysteme
Empfehlung: Alle betroffenen Pakete auf aktuelle Patch-Versionen aktualisieren
             pip-audit in CI/CD-Pipeline integrieren fuer kontinuierliche Ueberwachung
```

---

## Dead-Code-Liste (gesamt 4a + 4b + 4c)

| # | Modul | Code | Grund |
|---|-------|------|-------|
| D1 | `shared/` (gesamtes Paket) | Alle Dateien | Wird von keinem Modul importiert |
| D2 | `circuit_breaker.py:170` | `redis_breaker` | Registriert, nie importiert |
| D3 | `circuit_breaker.py:171` | `chromadb_breaker` | Registriert, nie importiert |
| D4 | `domains/cover.py:56-101` | `_is_safe_for_automation()`, `_is_bed_occupied()` | `evaluate()` gibt immer `[]` |
| D5 | `domains/cover.py:44-49` | `get_plugin_actions()` | Actions definiert, nie implementiert |
| D6 | `engines/cover_control.py:100` | `_pending_actions` | Nie beschrieben/gelesen |
| D7 | `engines/adaptive.py:285` | `GradualTransitioner._pending` | Nie befuellt |
| D8 | `app.py:385` | `_start_time = 0` Modul-Variable | Nur `dependencies["start_time"]` genutzt |
| D9 | `speech/server.py:37` | `import json as _json` | Importiert, nie verwendet |
| D10 | `ha_connection.py:764-765` | `is_connected()` Methode | Identisch mit `connected` Property |
| D11 | `automation_engine.py:88-102` | `_apply_context_adjustments()` | Doppelt mit `_get_adjusted_thresholds()` |

---

## Gesamtstatistik (alle 3 Prompts: 4a + 4b + 4c)

```
Gesamt: 349 Bugs (alle Prioritaeten)
  KRITISCH: 30 (aus 4a: 10, 4b: 12, 4c: 8)
  HOCH: 82 (aus 4a: 18, 4b: 39, 4c: 25)
  MITTEL: 130 (aus 4a: 38, 4b: 58, 4c: 34)
  NIEDRIG: 107 (aus 4a: 22, 4b: 46, 4c: 39)

Security-Findings: 7 (11 OK, 1 HOCH, 4 MITTEL, 2 NIEDRIG)
Resilience-Luecken: 3 kritische (Redis/ChromaDB Breaker Dead Code, kein Speech-Fallback)
Performance-Probleme: 5 wesentliche (Startup, N+1, Vacuum, MindHome-Cache, Humanizer)
Dead Code: 11 Eintraege (inkl. gesamtes shared/ Paket)
```

---

## KONTEXT AUS PROMPT 4 (gesamt: 4a + 4b + 4c): Bug-Report

### Statistik
Gesamt: 349 Bugs (KRITISCH 30, HOCH 82, MITTEL 130, NIEDRIG 107)

### Kritische Bugs (Top-10)
1. `brain.py:2356+2394` — Doppelter Key "conv_memory", zweiter ueberschreibt ersten (4a)
2. `brain.py:4838` — process() Methode 4838 Zeilen, God-Method (4a)
3. `memory.py:32-42` — Redis bytes vs string (42 Vorkommen systemweit) (4b)
4. `automation_engine.py:732-740` — UTC vs Lokalzeit in Time-Triggers (4c)
5. `automation_engine.py:2283-2284` — UTC vs Lokalzeit in Quiet Hours (4c)
6. `sleep.py:326-330` — UTC/Lokal bei WakeUp-Rampe, 1-2h zu spaet (4c)
7. `cover_control.py:781` — Markise bei Sturm AUSgefahren statt EINgefahren (4c)
8. `fire_water.py:164,470` — Feueralarm bei DB-Fehler stillschweigend ignoriert (4c)
9. `circadian.py:88` — Race Condition auf `_active_overrides` ohne Lock (4c)
10. `access_control.py:108-120` — lock/unlock ohne Entity-Whitelist (4c)

### Security-Report
- **11/18 Checks bestanden** (Prompt-Injection, HA-Auth, Self-Automation, Autonomy, Factory-Reset, Update/Restart, API-Key, File-Upload, Logs, SSRF, Threat)
- **HOCH**: `lock.unlock` via LLM ohne Bestaetigung (`function_calling.py:5203`)
- **MITTEL**: Fehlende Input-Validation (70+ Endpoints), kein Brute-Force-Schutz, Workshop ohne Bounds, Addon Wildcard-CORS
- **ADDON KRITISCH**: 199/200 Endpoints OHNE Auth, CORS erlaubt alle Origins

### Resilience-Report
- **Abgefangen**: Ollama (Circuit Breaker + Kaskade), HA (Breaker + Retry + Cache), Addon (Breaker), LLM-Timeout (Kaskade), LLM-Response (4-stufig)
- **Teilweise**: Redis (graceful degradation, kein Breaker), ChromaDB (degradation, kein Breaker, blockiert Event-Loop), Speech (kein Text-Fallback)
- **Dead Code**: `redis_breaker` und `chromadb_breaker` registriert aber nie importiert

### Performance-Report
- **Latenz Shortcut-Pfad**: 50-200ms (OPTIMAL)
- **Latenz Fast-Modell**: 1500-4000ms (OK)
- **Latenz Smart-Modell**: 2500-8000ms (GRENZWERTIG)
- **Bottlenecks**: Startup (~40 sequentielle awaits), Semantic Memory N+1, 4 Vacuum-Tasks, kein MindHome-Cache, Humanizer bei trivialen Antworten

### Dead-Code-Liste
- `shared/` gesamtes Paket (0 Imports)
- `redis_breaker`, `chromadb_breaker` (registriert, nie genutzt)
- `domains/cover.py` — 3 Methoden (evaluate() ist leer)
- `engines/cover_control.py` — `_pending_actions`
- `engines/adaptive.py` — `GradualTransitioner._pending`
- `automation_engine.py` — `_apply_context_adjustments()` (Duplikat)

**Wenn du Prompt 5 in derselben Konversation erhaeltst**: Setze alle bisherigen Kontext-Bloecke (Prompt 1–4c) automatisch ein.
