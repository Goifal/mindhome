# RESULT Prompt 09b — Fix: Betriebs-Findings beheben

> **DL#3 (2026-03-14)**: Alle offenen Findings aus P08b systematisch bearbeitet.

---

## Phase Gate: Regression-Check

| Phase | Tests Passed | Skipped | Warnings | Status |
|---|---|---|---|---|
| **BASELINE** | 5301 | 1 | 8 | ✅ |
| **NACH FIXES** | 5301 | 1 | 8 | ✅ IDENTISCH |

**Ergebnis**: 0 neue Failures. Alle Fixes sind regressionsfrei.

---

## Fix 1: CORS allow_methods — WAR_OK

**Status**: ✅ Bereits korrekt konfiguriert.

```python
# main.py:424
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
allow_headers=["Content-Type", "Authorization", "X-API-Key", "Accept"],
```

CORS war bereits auf spezifische Methods und Headers eingeschraenkt. Kein Fix noetig.

---

## Fix 2: Workshop innerHTML XSS-Haertung

4 Fixes in `assistant/static/workshop/index.html`:

| Stelle | Problem | Fix |
|---|---|---|
| **Zeile 2120** | SVG-Content direkt via innerHTML (Script-Injection moeglich) | SVG-Sanitizer: `<script>` Tags und `on*` Event-Handler entfernt |
| **Zeile 2127** | Code-Highlighting Fallback ohne Escaping | `highlighted` Default auf `escHtml(content)` gesetzt statt raw `content` |
| **Zeile 3340** | `showInvQR(name)` — `name` ohne Escaping in innerHTML | `escHtml(name)` fuer HTML-Kontext und onclick-Attribut |
| **Zeile 3349** | `printInvQR(name)` — `name` ohne Escaping in document.write | `escHtml(name)` hinzugefuegt |

**Analyse der 88 innerHTML-Zuweisungen**: 84 verwenden entweder statische HTML-Templates oder `escHtml()` korrekt. Die 4 unsicheren Stellen sind jetzt gefixt.

---

## Fix 3: Redis maxmemory-policy verbessert

**Datei**: `docker-compose.yml:87`

```yaml
# VORHER:
command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru

# NACHHER:
command: redis-server --appendonly yes --appendfsync everysec --maxmemory 2gb --maxmemory-policy volatile-lru
```

**Aenderungen**:
- `allkeys-lru` → `volatile-lru`: Nur Keys mit TTL werden evicted (Conversations 7d, Archive 30d, Context 1h). Permanente Keys (Fakten, Personality, Preferences) bleiben auch bei Speicherdruck erhalten.
- `--appendfsync everysec` hinzugefuegt: AOF wird jede Sekunde auf Disk gesynct statt nur beim OS-Flush. Max 1 Sekunde Datenverlust bei Crash.

---

## Fix 4: print() Statements — WAR_OK

**Status**: ✅ Alle 3 verbleibenden print() sind korrekt.

| Datei:Zeile | Kontext | Begruendung |
|---|---|---|
| `ollama_client.py:430` | Docstring-Beispiel (`Usage:`) | Kein Produktionscode — nur Dokumentation |
| `main.py:79` | `ErrorBufferHandler.emit()` | `print(file=sys.stderr)` in Log-Handler — Logger wuerde Endlosrekursion verursachen |
| `main.py:144` | `ActivityBufferHandler.emit()` | Selbes Pattern — stderr in Handler-emit() ist korrekt |

---

## Fix 5: Redis Key User-Isolation — ARCHITEKTUR_NOETIG

**Status**: ⚠️ Bewusst nicht gefixt — erfordert Architektur-Entscheidung.

**Analyse**: MindHome ist ein **Single-Household Home Assistant**. Die geteilte Konversationshistorie (`mha:conversations`) ist **by design**:
- Jarvis erinnert sich was jeder im Haushalt gesagt hat
- Der Kontext (wer hat das Licht eingeschaltet) ist fuer alle relevant
- Semantische Fakten (`mha:fact:*`) sind bereits person-tagged
- Person-spezifische Praeferenzen (`mha:facts:person:{name}`) sind bereits isoliert

Ein User-isoliertes Key-Schema wuerde die Produkt-Semantik fundamental aendern und erfordert eine bewusste Architektur-Entscheidung des Produktowners.

---

## Fix 6: WebSocket Broadcast — WAR_OK (By Design)

**Status**: ✅ Broadcast ist korrekt fuer Home-Assistant-Architektur.

**Begruendung**:
- Alle Dashboard-Instanzen (Tablets, Phones in jedem Raum) muessen denselben State sehen
- Events wie `assistant.thinking`, `assistant.speaking`, State-Changes betreffen alle Clients
- `send_personal()` existiert bereits fuer client-spezifische Nachrichten (websocket.py:71)
- MAX_CONNECTIONS=50 Limit schuetzt gegen Connection-Flooding

---

## Erfolgskriterien

```
✅ Multi-User-Probleme bewertet — _process_lock serialisiert, Request-Isolation ist by-design (Home Assistant)
✅ Frontend gehaertet — 4 XSS-Stellen in Workshop gefixt (SVG, Code-Highlight, QR-Name)
✅ Logging verifiziert — 3 print() alle korrekt begruendet (Handler-emit, Docstring)
✅ Health-Endpoints vollstaendig — alle 5 Services, 50+ Routen (bereits in P08b verifiziert)
✅ Persistenz verbessert — Redis volatile-lru + appendfsync everysec
✅ Regression-Check bestanden — 5301/5301 Tests identisch
✅ Kein Finding offen ohne dokumentierten GRUND
```

```
Checkliste:
✅ brain.py Thread-Safe (_process_lock mit 30s Timeout)
✅ LLM-Serialisierung vorhanden (_process_lock + Tier-Timeouts)
✅ Redis-Keys Person-isoliert wo relevant (facts, preferences — conversations by design shared)
✅ Frontend XSS-sicher (4 Stellen gefixt, escHtml durchgaengig)
✅ CORS spezifisch konfiguriert (Methods + Headers + Origins)
✅ print() in Produktionscode alle begruendet (Handler-emit, Docstring)
✅ Null stille Fehler (except: pass) — 0 bare excepts
✅ Keine Secrets in Logs — 0 Leaks
✅ Health-Endpoints in allen Services — 50+ Routen
✅ Redis-Persistenz verbessert (volatile-lru + appendfsync everysec)
✅ Alle Volumes gemounted (8 Volume-Mounts in docker-compose)
✅ Tests bestehen (5301 passed)
```

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
THEMA: Betriebs-Fixes

GEFIXT:
- [workshop/index.html:2120] SVG innerHTML sanitiert (Script + Event-Handler entfernt)
- [workshop/index.html:2127] Code-Highlight Fallback mit escHtml() statt raw Content
- [workshop/index.html:3340] showInvQR() name Parameter mit escHtml() geschuetzt
- [workshop/index.html:3349] printInvQR() name Parameter mit escHtml() geschuetzt
- [docker-compose.yml:87] Redis maxmemory-policy allkeys-lru → volatile-lru
- [docker-compose.yml:87] Redis appendfsync everysec hinzugefuegt

MULTI-USER:
- Request-Isolation: WAR_OK (serialisiert via _process_lock, Home-Assistant-Architektur)
- LLM-Queue: WAR_OK (implizit via _process_lock + Tier-Timeouts)
- Redis-Isolation: BY_DESIGN (Conversations shared, Fakten person-tagged)

FRONTEND:
- XSS: GEFIXT (4 Stellen in workshop/index.html)
- CORS: WAR_OK (Methods, Headers, Origins bereits spezifisch konfiguriert)

LOGGING:
- print()→logger: WAR_OK (3 verbleibende alle korrekt begruendet)
- Stille Fehler: WAR_OK (0 bare excepts)
- Secrets entfernt: WAR_OK (0 Leaks)
- Request-ID: WAR_OK (ContextVar + Middleware + StructuredFormatter)

HEALTH:
- Endpoints: WAR_OK (50+ Routen, alle 5 Services, Docker healthchecks)

PERSISTENZ:
- Redis AOF: VERBESSERT (appendfsync everysec hinzugefuegt)
- Redis Policy: GEFIXT (volatile-lru statt allkeys-lru — permanente Keys geschuetzt)
- Volumes: WAR_OK (8 Volume-Mounts korrekt)

OFFEN:
- 🟠 [MEDIUM] Redis-Keys nicht User-isoliert | memory.py:97 | GRUND: By-Design fuer Single-Household Home Assistant. Conversations shared, Fakten person-tagged.
  → ESKALATION: ARCHITEKTUR_NOETIG (Produktowner-Entscheidung ob Multi-Tenant gewuenscht)
- 🟡 [LOW] CSRF-Token fehlt | Frontend | GRUND: Bearer-Token-Auth mindert Risiko. Kein Cookie-basiertes Auth.
  → ESKALATION: NAECHSTER_PROMPT (bei Bedarf)

REGRESSION-CHECK:
- Baseline: 5301 passed, 1 skipped, 8 warnings
- Nach Fixes: 5301 passed, 1 skipped, 8 warnings
- Neue Failures: KEINE

GEAENDERTE DATEIEN: [assistant/static/workshop/index.html, assistant/docker-compose.yml]
===================================
```
