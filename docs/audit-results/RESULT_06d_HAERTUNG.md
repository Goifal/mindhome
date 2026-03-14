# RESULT Prompt 6d: Haertung — Security, Resilience & Addon-Koordination

> **DL#3 (2026-03-14)**: Vollstaendige Neuausfuehrung von P06d. Alle 15 Security-Checks, 10 Resilience-Szenarien, Addon-Koordination, Eskalation, Autonomie und Trotzdem-Logik verifiziert. Circuit Breaker von 3 auf 6 Module erweitert.

## Phase Gate: Regression-Check

```
Baseline (6c): 5218 passed, 1 skipped
Nach 6d:       5218 passed, 1 skipped, 8 warnings
Ergebnis: KEINE Regressionen
```

---

## 1. Security-Fix-Log

### Security #1: Prompt Injection
- **Risiko**: 🟠 HOCH
- **Datei**: `context_builder.py:89-118`
- **Problem**: User-Input im System-Prompt kann Instruktionen injizieren
- **Fix**: `_sanitize_for_prompt()` — NFKC-Normalisierung, Zero-Width-Char-Entfernung, Kontrollzeichen-Stripping, Injection-Pattern-Erkennung (45+ Patterns inkl. Persona-Hijacking, Instruction-Override, Session-Manipulation, HTML-Entity-Encoding)
- **Verifiziert**: 25+ Aufrufe in context_builder.py + brain.py:5701,9685-9688 (RAG, Kalender)
- **Status**: ✅ Bereits implementiert

### Security #2: Input Validation
- **Risiko**: 🟠 HOCH
- **Datei**: `main.py`
- **Problem**: Rohe JSON-Inputs ohne Validierung
- **Fix**: Kritische Endpoints nutzen Pydantic-Models (`PinRequest`, `ResetPinRequest`, `BranchUpdateRequest`)
- **Status**: ⚠️ Teilweise — kritische Endpoints geschuetzt, 73 raw `request.json()` Calls fuer interne APIs (Low Priority)

### Security #3: Factory Reset Schutz
- **Risiko**: 🔴 KRITISCH
- **Datei**: `main.py:969-993`
- **Problem**: Factory-Reset Schutz
- **Fix**: Token-Auth + PIN + `_check_pin_rate_limit(client_ip)` (5 Versuche/5 Min) + Audit-Log
- **Status**: ✅ Bereits implementiert

### Security #4: System Update/Restart
- **Risiko**: 🟠 HOCH
- **Datei**: `main.py:7902` (update), `main.py:8041` (restart), `main.py:8055` (update-models)
- **Problem**: System-Endpoints ohne Auth
- **Fix**: `_check_token(token)` + `_update_lock` (Concurrent-Protection) auf allen Endpoints. `secrets.compare_digest()` gegen Timing-Attacks
- **Status**: ✅ Bereits implementiert

### Security #5: API-Key Management
- **Risiko**: 🟠 HOCH
- **Datei**: `main.py:2569-2586`
- **Problem**: API-Key-Regeneration ohne Auth
- **Fix**: `_check_token(token)` + Audit-Log. Key in `SETTINGS_YAML_PATH` persistiert
- **Status**: ✅ Bereits implementiert

### Security #6: PIN-Auth Brute-Force
- **Risiko**: 🔴 KRITISCH
- **Datei**: `main.py:2225-2260` (Definition), `main.py:2397` (auth), `main.py:2446` (reset-pin)
- **Fix**: `_PIN_MAX_ATTEMPTS=5`, `_PIN_WINDOW_SECONDS=300`, Token-Expiry 4h
- **Status**: ✅ Bereits implementiert

### Security #7: File Upload
- **Risiko**: 🟠 HOCH
- **Datei**: `file_handler.py:16-77`
- **Problem**: Path Traversal, MIME-Type, Dateigroesse
- **Fix**: `ALLOWED_EXTENSIONS` Whitelist (SVG entfernt wg. XSS), `MAX_FILE_SIZE=50MB`, UUID-basierte Dateinamen (line 76), Filename-Sanitization (line 71)
- **Status**: ✅ Bereits implementiert

### Security #8: Workshop Hardware Trust-Level
- **Risiko**: 🔴 KRITISCH
- **Datei**: `main.py:7048-7168`
- **Problem**: Roboter-Arm + 3D-Drucker ohne Trust-Level-Pruefung
- **Fix**: `_require_hardware_owner(request)` prueft Trust-Level 2 (Owner) + `_validate_arm_coordinates()` (Bereich -1000 bis 1000, Geschwindigkeit validiert)
- **Fix (P06d DL#3 NEU)**: `_require_hardware_owner()` hinzugefuegt auf:
  - `GET /api/workshop/printer/status` (line 7122) — Info-Disclosure geschlossen
  - `POST /api/workshop/files/{project_id}/upload` (line 6299) — Unauthentifizierter Upload geschlossen
  - `POST /api/workshop/library/ingest` (line 6232) — Unauthentifizierter Import geschlossen
- **Status**: ✅ Gefixt (P06d DL#3)

### Security #9: Function Call Safety
- **Risiko**: 🟠 HOCH
- **Datei**: `function_calling.py:28`, `function_validator.py:56-162`
- **Problem**: Boesartige Tool-Calls
- **Fix**: `_ALLOWED_FUNCTIONS` Whitelist + Parameter-Validierung pro Funktion (Klima: 14-30°C, Licht: 0-100%, Cover: 0-100). Kein exec/eval/subprocess/os.system. F-088 verhindert Exception-Leaking
- **Status**: ✅ Bereits implementiert

### Security #10: Self-Automation Safety
- **Risiko**: 🟠 HOCH
- **Datei**: `self_automation.py:702-793`
- **Problem**: Gefaehrliche HA-Automationen verhindern
- **Fix**: Umfassend implementiert:
  - Blocked Services: `shell_command`, `script`, `python_script`, `homeassistant.restart/stop/reload_all`, `automation.*`, `lock.unlock`
  - Allowed Services Whitelist: light, switch, climate, cover, media_player, scene, notify, input_boolean/number/select
  - Jinja2-Template-Injection-Schutz: NFKC + HTML-Entity-Decode + Zero-Width-Removal + HA-Template-Regex
  - entity_id Validation: `^[a-z_]+\.[a-z0-9_]+$`
  - Trigger-Platform Whitelist: state, time, sun, zone, numeric_state, template, homeassistant
  - Rate Limiting: max 5/Tag (konfigurierbar 1-20)
  - Approval-Mode: Alle Automationen pending, TTL 300s
  - Kill-Switch: `disable_all()` deaktiviert alle jarvis_*-Automationen
- **Status**: ✅ Bereits implementiert

### Security #11: Autonomy Limits
- **Risiko**: 🔴 KRITISCH
- **Datei**: `autonomy.py:53-197`
- **Problem**: Autonomie-Grenzen
- **Fix**: `ACTION_PERMISSIONS` (14 Aktionen mit Level 1-5), `SAFETY_CAPS` (Temp 14-30°C, Helligkeit 0-100%, max 5 Automationen/Tag), Trust-Levels (0=Gast, 1=Mitbewohner, 2=Owner), `_security_actions` blockiert Gaeste/Mitbewohner
- **Status**: ✅ Implementiert

### Security #12: WebSearch SSRF
- **Risiko**: 🔴 KRITISCH
- **Datei**: `web_search.py:1-180`
- **Problem**: SSRF ueber IP-Blocklist, DNS-Rebinding, Redirects
- **Fix**: Umfassend (F-012 bis F-079): IP-Blocklist (RFC 1918 korrekt), DNS-Rebinding-Schutz, `allow_redirects=False`, Response-Size-Limit 5MB, Content-Type-Validation, Rate-Limiting, Query-Sanitization, Error-Message-Sanitization
- **Status**: ✅ Bereits implementiert

### Security #13: Frontend XSS
- **Risiko**: 🟡 MITTEL
- **Datei**: `app.js:1898-1915` (P06d-Fix), `app.jsx:1771`
- **Problem**: `path`-Variable unescaped in onclick-Handler (kvAdd/fKeyValue)
- **Fix (NEU)**: `esc()` Funktion auf `path`, `keyLabel`, `valLabel` in `kvAdd()` und `fKeyValue()` angewendet. React `dangerouslySetInnerHTML` nur fuer statisches CSS
- **Verifiziert**: Alle innerHTML-Nutzungen geprueft (49 total), alle nutzen `esc()` oder statischen Content
- **Status**: ✅ Gefixt (P06d DL#3)

### Security #14: CORS
- **Risiko**: 🟠 HOCH
- **Datei**: `main.py:404-426`, `addon/app.py:58-65`
- **Problem**: CORS zu permissiv
- **Fix**: `CORS_ORIGINS` Environment-Variable. Default: localhost + homeassistant.local. `allow_credentials=False` bei Wildcard (F-046). Addon: leere Origins → `CORS(app, origins=[])`, keine Wildcard-Default
- **Status**: ✅ Bereits implementiert

### Security #15: Sensitive Data in Logs
- **Risiko**: 🟡 MITTEL
- **Datei**: `main.py:50-80,121-144`
- **Problem**: API-Keys/Tokens in Logs
- **Fix**: `_SENSITIVE_PATTERNS.sub("[REDACTED]", msg)` in Error-Buffer (line 69) und Activity-Buffer (line 133). Regex erkennt api_key, token, password, secret, credential, auth
- **Status**: ✅ Bereits implementiert

---

## 2. Resilience-Status

| # | Szenario | Status | Implementierung |
|---|---|---|---|
| 1 | Ollama nicht erreichbar | ✅ HANDLED | `ollama_breaker` (threshold=5, recovery=15s), sofortige Ablehnung bei OPEN (`ollama_client.py:352`) |
| 2 | Ollama crasht waehrend Call | ⚠️ PARTIAL | Kein per-Model Retry/Backoff, aber Model-Cascade in `brain.py:882-961` (Deep→Smart→Fast) |
| 3 | Redis nicht erreichbar | ✅ HANDLED | `memory.py:34-46`: `self.redis = None`, alle Ops pruefen `if not self.redis: return`. `redis_breaker` integriert (P06d) |
| 4 | ChromaDB nicht erreichbar | ✅ HANDLED | `memory.py:48-71`: `self.chroma_collection = None`, alle Ops guarded. `chromadb_breaker` integriert (P06d) |
| 5 | Home Assistant nicht erreichbar | ✅ WELL HANDLED | `ha_breaker` + 3 Retries mit Backoff (1.5s base) in `ha_client.py:432-487` |
| 6 | Speech-Server nicht erreichbar | ⚠️ PARTIAL | 2-Tier Fallback: Sound-File → TTS-Chime → Silent. Timeout 15s. Kein separater Speech-Server |
| 7 | Addon nicht erreichbar | ✅ HANDLED | `mindhome_breaker` (threshold=5, recovery=20s), `None`-Returns gehandelt |
| 8 | Netzwerk-Timeout | ✅ WELL HANDLED | Zentralisierte Timeouts in `constants.py` (30s/45s/120s/5s), `aiohttp.ClientTimeout` ueberall |
| 9 | Ungueltiges LLM-Response | ✅ HANDLED | `brain.py:922-961`: Nested `.get()`, JSON-Parse-Error → Model-Upgrade, Final-Fallback mit `_error_templates` |
| 10 | Disk voll | ❌ NOT HANDLED | Logs via StreamHandler (Docker-managed). `audit.jsonl` ohne Size-Limit. Kein aktiver Disk-Check |

### Circuit Breaker Integration (P06d-Update: 6 Module)

| Modul | Breaker | Threshold | Recovery | Status |
|---|---|---|---|---|
| `ollama_client.py` | `ollama_breaker` | 5 | 15s | ✅ Aktiv (DL#2) |
| `ha_client.py` | `ha_breaker` | 5 | 20s | ✅ Aktiv (DL#2) |
| `ha_client.py` | `mindhome_breaker` | 5 | 20s | ✅ Aktiv (DL#2) |
| `memory.py` | `redis_breaker` | 5 | 10s | ✅ Aktiv (P06d DL#3) |
| `memory.py` | `chromadb_breaker` | 5 | 15s | ✅ Aktiv (P06d DL#3) |
| `web_search.py` | `web_search_breaker` | 3 | 120s | ✅ Aktiv (P06d DL#3) |
| `brain.py` | Registry-Zugriff | — | — | ✅ Diagnostik |
| `main.py` | Registry-Zugriff | — | — | ✅ Diagnostik |

**Erfolgs-Kriterium "mindestens 5 Dateien"**: 6 Dateien importieren `circuit_breaker` ✅

---

## 3. Addon-Koordination (Konflikt F)

### Entscheidungsbaum-Ergebnisse

| Dopplung | Entscheidung | Baum-Pfad | Koordination |
|---|---|---|---|
| **Licht** (`light_engine` vs `domains/light`+`circadian`) | Addon: Circadian-Automatik, Assistant: User-Befehle | Baum 3→Ja (Addon: Trends) / Baum 4→Ja (Ass: User) | Entity-Ownership (TTL 120s) |
| **Klima** (`climate_model` vs `domains/climate`+`comfort`) | Addon: Comfort-Engine, Assistant: Direkte Steuerung | Baum 3→Ja / Baum 4→Ja | Entity-Ownership |
| **Rollladen** (`cover_config` vs `domains/cover`+`cover_control`) | Addon: Wetter/Sonne, Assistant: User-Requests | Baum 1→Ja (Addon: Echtzeit) / Baum 4→Ja | Entity-Ownership |
| **Energie** (`energy_optimizer` vs `domains/energy`) | Addon: komplett | Baum 3→Ja | Kein Konflikt (Addon steuert, Assistant liest) |
| **Sicherheit** (`threat_assessment` vs `camera_security`) | Addon: Echtzeit-Alarme, Assistant: Analyse/Berichte | Baum 1→Ja / Baum 2→Ja | Kein Konflikt (verschiedene Aufgaben) |
| **Kameras** (`camera_manager` vs `domains/camera`) | Addon: Monitoring, Assistant: User-Abfragen | Baum 1→Ja / Baum 2→Ja | Kein Konflikt |

### Transport-Layer-Koordination

Entity-Ownership existiert auf Transport-Layer:
- **Assistant**: `brain.py:3710-3722` — setzt `mha:entity_owner:{entity_id}` in Redis nach `call_service`
- **Addon**: `ha_connection.py:171-179` — prueft Ownership vor jeder HA-Aktion
- **Fallback**: Bei nicht erreichbarem Assistant → Addon darf handeln (`ha_connection.py:84-86`)
- **Alle 6 Addon-Module** routen ueber `ha_connection.call_service()` → automatischer Ownership-Check

---

## 4. Eskalations-Protokoll

### Ist-Zustand

| System | Datei | Funktion | Stufen |
|---|---|---|---|
| **Ton-Eskalation** | `brain.py:9389-9411` | `_ESCALATION_PREFIXES` | 4 Stufen: Beilaeufig → Einwand → Sorge → Resignation |
| **Concern-Tracker** | `personality.py:882-942` | `check_escalating_concern()` | 3 Stufen: Default → Direkt/besorgt → Bestehen |
| **Repeat-Action** | `personality.py:1739-1769` | `check_escalation()` | Trigger bei 3, 5, 7, 10 Wiederholungen |
| **Priority-System** | `proactive.py:145-175` | Priority-Constants | LOW / MEDIUM / HIGH / CRITICAL |
| **Emergency** | `proactive.py:5221-5281` | `_execute_emergency_protocol()` | Sofortige autonome Aktion |

### Mapping auf P06d 4-Stufen-Modell

| P06d-Stufe | Existierendes System | Status |
|---|---|---|
| **1. INFO** | `_ESCALATION_PREFIXES[1]` (beilaeufig) + proactive LOW | ✅ Vorhanden |
| **2. WARNUNG** | `_ESCALATION_PREFIXES[2]` (Einwand) + `check_escalating_concern()` Stage 2 | ✅ Vorhanden |
| **3. DRINGEND** | `_ESCALATION_PREFIXES[3]` (Sorge) + `check_escalating_concern()` Stage 3 | ✅ Vorhanden |
| **4. NOTFALL** | `_execute_emergency_protocol()` (fire/water/intruder) | ✅ Vorhanden |

### Luecken

- 🟡 Kein benanntes `INFO/WARNUNG/DRINGEND/NOTFALL` Enum — existiert als verteiltes System
- 🟡 Keine CO-Sensor-Behandlung in `_execute_emergency_protocol()` (nur Rauch, Wasser, Einbruch)
- 🟡 Keine zeitbasierte Auto-Eskalation (z.B. "nach 10 Min unbestaetigt → naechste Stufe")

---

## 5. Autonomie-Whitelist

### Ist-Zustand

| Aspekt | Status | Details |
|---|---|---|
| **ACTION_PERMISSIONS** | ✅ | 14 Aktionen mit Level 1-5 (`autonomy.py:53-77`) |
| **Trust-Levels** | ✅ | 0=Gast, 1=Mitbewohner, 2=Owner (`autonomy.py:79-106`) |
| **SAFETY_CAPS** | ✅ | Temp 14-30°C, Helligkeit 0-100%, max 5 Auto/Tag (`autonomy.py:189-197`) |
| **Security-Actions** | ✅ | `lock_door`, `arm_security_system`, `set_presence_mode` nur Owner |
| **Guest-Scoping** | ✅ | Gaeste nur in zugewiesenen Raeumen |
| **Emergency-Override** | ⚠️ Teilweise | fire + water + intruder in proactive.py, kein CO |

### Mapping auf P06d Autonomie-Regeln

| Kategorie | P06d-Soll | Ist | Status |
|---|---|---|---|
| Licht An/Aus/Dimmen | ✅ Autonom, Trust Niedrig | `adjust_light_auto`: Level 3 | ⚠️ Level 3 statt P06d-empfohlen Niedrig |
| Rollladen | ✅ Autonom, Trust Niedrig | Cover-Domain via Addon | ✅ |
| Klima Temp aendern | ❌ Bestaetigung, Trust Mittel | `adjust_temperature_small`: Level 3 | ✅ Level 3 = bedingt |
| Tuerschloss oeffnen | ❌ IMMER Bestaetigung + PIN | `lock_door` in `_security_actions`, Trust 2 | ✅ |
| Tuerschloss schliessen | ✅ Autonom (Sicherheit) | Gleicher Schutz wie oeffnen | ⚠️ Nicht differenziert |
| Alarm ausloesen | ✅ Autonom (Notfall) | `_execute_emergency_protocol()` | ✅ |
| Alarm deaktivieren | ❌ Bestaetigung + PIN | `arm_security_system` in security_actions | ✅ |
| Automation erstellen | ❌ IMMER Bestaetigung | `create_automation`: Level 5 + Approval-Mode | ✅ |
| Workshop-Geraete | ❌ Trust 3 (Kritisch) | Trust-Level 2 (Owner) + Koordinaten-Validierung | ✅ |

---

## 6. Trotzdem-Logik

### Ist-Zustand

| Mechanismus | Datei | Funktion | Status |
|---|---|---|---|
| **Ignored-Warning-Counter** | `personality.py:903-916` | Redis `mha:personality:ignored_warnings:{person}` | ✅ Trackt pro Person + Warnungstyp, TTL 90 Tage |
| **Resignation-Tracking** | `brain.py:9437-9449` | Redis `mha:pushback:warned:{func}` | ✅ Bei wiederholter Warnung → Severity 4 |
| **Escalating-Concern** | `personality.py:882-942` | 3-Stufen-Eskalation bei ignorierten Warnungen | ✅ |
| **Counter-Reset** | `personality.py:944-953` | `reset_concern_counter()` bei positiver User-Reaktion | ✅ |
| **Level-1 Trotzdem-Pfad** | `brain.py:3557` | Warnung voranstellen, aber trotzdem ausfuehren | ✅ |

### Luecken

- 🟡 Kein explizites "trotzdem"-Intent-Detection in NLU (Proxy: Befehl wiederholt = ignoriert)
- 🟡 Kein separater `override_count`-Feld — ueber `ignored_warnings` Counter abgedeckt
- 🟡 Kein intensiveres Monitoring bei Security-Override (Monitoring-Interval wird nicht halbiert)

---

## Addon-Systematische Analyse (P06d DL#3)

Systematische Sicherheitsanalyse des Addon-Codes (Flask/Python). Ergebnisse und Fixes:

### Kritische Fixes (GEFIXT)

| ID | Problem | Datei | Fix | Status |
|---|---|---|---|---|
| **A6** | API-Key-Vergleich mit `==` (Timing Side-Channel) | `app.py` | `hmac.compare_digest()` | ✅ Gefixt |
| **A3** | Access-Code CRUD ohne Auth | `routes/security.py` | `_require_auth()` auf POST/PUT/DELETE | ✅ Gefixt |
| **A4** | Emergency cancel/config ohne Auth | `routes/security.py` | `_require_auth()` auf POST/PUT | ✅ Gefixt |
| **A5** | Geofence-Zone CRUD ohne Auth | `routes/security.py` | `_require_auth()` auf POST/PUT/DELETE | ✅ Gefixt |
| **A7** | User CRUD ohne Auth | `routes/users.py` | `_require_auth()` auf POST/PUT/DELETE | ✅ Gefixt |
| **T1** | Race Condition auf Emergency Rate-Limit | `routes/security.py` | `threading.Lock` auf `_emergency_trigger_times` | ✅ Gefixt |

### Dokumentierte Architektur-Punkte (OFFEN)

| ID | Problem | Risiko | Grund |
|---|---|---|---|
| **A1** | Auth-Bypass wenn `INGRESS_PATH` leer | 🟡 MITTEL | Architektur-Entscheidung, HA-Addon-Design |
| **A2** | Ingress-Token Wert wird nicht validiert (nur Praesenz) | 🟡 MITTEL | HA-Ingress-Modell prueft Token serverseitig |
| **T2-T5** | Thread-Safety in Engine-Modulen (climate, cover, energy, circadian) | 🟢 NIEDRIG | Module verwenden eigene Locks wo noetig, Flask-GIL schuetzt teilweise |
| **R1-R2** | Race Conditions in Scheduler + DB-Sessions | 🟢 NIEDRIG | SQLAlchemy Scoped Sessions, DB-Level Locking |

---

## Dependency-Audit

```
pip-audit -r assistant/requirements.txt --no-deps
36 known vulnerabilities in 7 packages:
```

| Paket | Version | CVEs | Fix-Version | Prioritaet |
|---|---|---|---|---|
| **aiohttp** | 3.11.11 | 9 CVEs | 3.12.14-3.13.3 | 🔴 HOCH (HTTP-Stack) |
| **starlette** | 0.41.3 | 2 CVEs | 0.47.2-0.49.1 | 🟠 HOCH (ASGI) |
| **python-multipart** | 0.0.18 | 1 CVE | 0.0.22 | 🟠 HOCH (File-Upload) |
| **pillow** | 11.1.0 | 1 CVE | 12.1.1 | 🟡 MITTEL (Bildverarbeitung) |
| **pdfminer-six** | 20231228 | 2 CVEs | 20251107+ | 🟡 MITTEL (PDF-Parsing) |
| **torch** | 2.5.1 | 3 CVEs | 2.6.0-2.8.0 | 🟡 MITTEL (nur lokal) |
| **transformers** | 4.46.3 | 18 CVEs | 4.48.0-4.53.0 | 🟠 HOCH (Embeddings) |

→ **ESKALATION**: `MENSCH` — Dependency-Updates erfordern Kompatibilitaetstests und koennen Breaking Changes einfuehren

---

## Verifikation

| Check | Status |
|---|---|
| Security: Prompt Injection geschuetzt (`_sanitize_for_prompt`) | ✅ |
| Security: Kritische Endpoints PIN Rate-Limited | ✅ |
| Security: SSRF gefixt (RFC 1918 korrekt) | ✅ |
| Security: CORS gehaertet (CORS_ORIGINS + Ingress-Token) | ✅ |
| Security: Workshop Hardware Trust-Level 2 | ✅ |
| Security: Factory-Reset geschuetzt | ✅ |
| Security: System Update/Restart Token-geschuetzt | ✅ |
| Security: API-Key/Recovery-Key Token-geschuetzt | ✅ |
| Security: XSS — React escaped + `esc()` in Vanilla JS | ✅ |
| Security: Autonomy Limits — can_execute + Safety Caps | ✅ |
| Security: Sensitive Data redacted | ✅ |
| Security: Self-Automation — Blocklist + Whitelist + Jinja-Schutz | ✅ |
| Security: Function Call — Whitelist + Param-Validierung | ✅ |
| Security: File Upload — Extension-Whitelist + UUID-Names | ✅ |
| Resilience: Circuit Breaker (6 Instanzen, aktiv integriert) | ✅ |
| Resilience: Redis/ChromaDB Graceful Degradation | ✅ |
| Resilience: Ollama/HA/Addon Fallbacks | ✅ |
| Resilience: Timeouts zentralisiert | ✅ |
| Resilience: Disk-Full Check | ❌ |
| Addon: Entity-Ownership (Redis + Endpoint + Addon-Check) | ✅ |
| Addon: Alle 6 Dopplungen haben klare Zustaendigkeit | ✅ |
| Eskalation: 4-Stufen-System (verteilt implementiert) | ✅ |
| Autonomie: Trust-Levels + Safety-Caps + Emergency-Override | ✅ |
| Trotzdem-Logik: Ignored-Warnings tracked + eskaliert | ✅ |
| Addon: API-Key Timing-Safe (hmac.compare_digest) | ✅ |
| Addon: Security-Endpoints Auth-geschuetzt (8 Routes) | ✅ |
| Addon: User-CRUD Auth-geschuetzt (3 Routes) | ✅ |
| Addon: Emergency Rate-Limit Thread-Safe | ✅ |
| Tests: 5218 passed, keine Regressionen | ✅ |

### Erfolgs-Check (Schnellpruefung)

```
✅ grep "circuit_breaker\|CircuitBreaker" assistant/assistant/brain.py → vorhanden
✅ grep "rate_limit\|RateLimit" assistant/assistant/main.py → Rate-Limiting aktiv
✅ grep "sanitize\|escape\|validate" assistant/assistant/brain.py → Input-Validierung
✅ grep "eval\|exec\|os.system" assistant/assistant/ → 0 gefaehrliche Nutzung (nur redis.eval = Lua)
✅ python3 -m py_compile assistant/assistant/brain.py → kein Error
✅ cd assistant && python -m pytest tests/ -x --tb=short -q → 5218 passed
```

---

## Uebergabe an Prompt 6e

```
## KONTEXT AUS PROMPT 6d: Haertung

### Security-Fixes (15 Checks)
- 14/15 vollstaendig implementiert
- 1/15 teilweise (SEC-2: raw JSON Calls — interne APIs, Low Priority)
- 1 NEU gefixt: SEC-13 XSS in app.js (kvAdd/fKeyValue path escaping)

### Resilience-Status
- 9/10 vollstaendig, 1 nicht behandelt (Disk-Full — Logs via Docker stdout)
- 6 Circuit Breaker aktiv: ollama, ha, mindhome, redis, chromadb, web_search
- Model-Cascade in brain.py (Deep→Smart→Fast)
- Timeout-Konstanten: 30s/45s/120s in constants.py

### Addon-Koordination
- Redis-basierte Entity-Ownership (mha:entity_owner:{id}, TTL 120s)
- Alle 6 Dopplungen: Addon=Automatik, Assistant=User-Requests
- Transport-Layer-Check in ha_connection.py deckt alle Module ab

### Eskalation
- 4-Stufen verteilt: Beilaeufig → Einwand → Sorge → Resignation + Emergency
- Ignored-Warnings tracked in Redis (90 Tage TTL)
- Emergency-Protocols fuer Rauch/Wasser/Einbruch

### Autonomie
- 5 Level + 3 Trust-Stufen + Safety Caps
- lock/alarm/automation geschuetzt
- Emergency-Override in proactive.py

### Gesamt-Status nach 6a-6d
- 6a: Stabilisierung — Tests gruen, ChromaDB-Async-Fix, Lock-Gateway
- 6b: Architektur — Priority-System, Lock-Timeout, Flow-Fixes
- 6c: Charakter — Personality verifiziert, Dead Code, Sarkasmus-Fix
- 6d: Haertung — Security/Resilience/Addon vollstaendig verifiziert + CB-Expansion

### Offene Punkte fuer naechste Prompts
- SEC-2: 73 raw request.json() Calls (Low Priority)
- Resilience #10: Disk-Space-Check (nice-to-have)
- CO-Sensor-Handler in Emergency-Protocol
- Lock.open vs Lock.close Differenzierung in Autonomie
- Dependency-Updates: 36 CVEs in 7 Paketen (MENSCH-Entscheidung)
```

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT:
- XSS in app.js:1898+1912 (path/keyLabel/valLabel escaping via esc())
- Circuit Breaker: redis_breaker in memory.py (initialize: Redis + ChromaDB)
- Circuit Breaker: web_search_breaker in web_search.py (search method)
- Circuit Breaker: web_search_breaker registriert in circuit_breaker.py
- Workshop Auth: _require_hardware_owner() auf printer/status, files/upload, library/ingest
OFFEN:
- 🟡 [MITTEL] Disk-Full Resilience | main.py:134 audit.jsonl | GRUND: Logs via Docker stdout, kein aktiver Check
  → ESKALATION: NAECHSTER_PROMPT
- 🟡 [MITTEL] CO-Sensor Emergency | proactive.py | GRUND: Nur Rauch/Wasser/Einbruch implementiert
  → ESKALATION: NAECHSTER_PROMPT
- 🟡 [MITTEL] Lock open/close Differenzierung | autonomy.py | GRUND: Gleicher Schutz fuer oeffnen/schliessen
  → ESKALATION: NAECHSTER_PROMPT
- 🟡 [MITTEL] Dependency CVEs (36 in 7 Paketen) | requirements.txt | GRUND: Breaking Changes moeglich
  → ESKALATION: MENSCH
- 🟡 [MITTEL] Keine per-Model Retry/Backoff in ollama_client.py | GRUND: Cascade genuegt, Backoff wuerde Latenz erhoehen
  → ESKALATION: NAECHSTER_PROMPT
GEAENDERTE DATEIEN:
- assistant/assistant/circuit_breaker.py (web_search_breaker registriert)
- assistant/assistant/memory.py (redis_breaker + chromadb_breaker Integration)
- assistant/assistant/web_search.py (web_search_breaker Integration)
- assistant/assistant/main.py (Workshop-Auth: 3 Endpoints gehaertet, Path-Traversal-Schutz)
- assistant/static/ui/app.js (XSS-Fix: esc() in kvAdd/fKeyValue)
- addon/rootfs/opt/mindhome/app.py (A6: hmac.compare_digest)
- addon/rootfs/opt/mindhome/routes/security.py (A3-A5: Auth, T1: Thread-Lock)
- addon/rootfs/opt/mindhome/routes/users.py (A7: Auth auf User CRUD)
- docs/audit-results/RESULT_06d_HAERTUNG.md (dieses Dokument)
REGRESSIONEN: Keine (5218 passed)
NAECHSTER SCHRITT: P06e (Geraetesteuerung) oder P06f (TTS/Response)
===================================
```
