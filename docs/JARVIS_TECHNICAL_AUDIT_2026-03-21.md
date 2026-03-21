# J.A.R.V.I.S. Technical Audit — 2026-03-21

> **Scope:** Vollständiger Code-Audit aller 99 Python-Dateien im `assistant/assistant/`-Paket + Addon-Code
> **Methodik:** 5-Pass-Analyse (Modul-Audit → Quality Deep Dive → Cross-Verification → Concurrency-Audit → Security-Deep-Dive) + Vollständigkeitsabgleich
> **Auditor:** Claude Code (Opus 4.6), 10 parallele Audit-Agents
> **Dateien auditiert:** 99 Assistant-Module + 18 Routes + 23 Domains + Core Addon-Dateien (100% Abdeckung verifiziert)

---

## Executive Summary

Die J.A.R.V.I.S.-Codebase ist insgesamt **solide und professionell** aufgebaut. Die Architektur mit Event-Bus, 3-Schichten-Gedächtnis, 3-Tier-LLM-Routing und 7-Schichten-SSRF-Schutz zeigt fortgeschrittenes Engineering. Test-Coverage ist mit 90+ Testdateien für ~99 Module herausragend.

### Findings-Übersicht

| Kategorie | Anzahl |
|-----------|--------|
| **Kritisch** (Laufzeitfehler) | 2 |
| **Hoch** (Sicherheit + fehlende Error-Callbacks) | 4 |
| **Mittel** (Logik, Concurrency, Qualität) | 21 |
| **Niedrig** (Code-Qualität, Stil) | 19+ |
| **Widerlegte Findings** | 3 |

---

## Teil 1: Bestätigte Bugs

### KRITISCH — Laufzeitfehler

#### K-1: memory_extractor.py:219 — Falscher Import (ImportError)

```python
# memory_extractor.py:219
from .embeddings import get_embedding, cosine_similarity
```

**Problem:** Die Funktionen `get_embedding` und `cosine_similarity` existieren **nicht** in `embeddings.py`. Die korrekten Namen sind:
- `get_cached_embedding` (embeddings.py:29)
- `compute_cosine_similarity` (embeddings.py:42)

**Auswirkung:** Jeder Codepfad der diese Zeile erreicht löst einen `ImportError` aus. Die semantische Duplikat-Erkennung bei der Faktenextraktion ist funktionsunfähig.

**Fix:**
```python
from .embeddings import get_cached_embedding, compute_cosine_similarity
```

---

#### K-2: situation_model.py:96-98 — Naive/Aware Datetime-Mischung (TypeError)

```python
# situation_model.py:96-98
if last_dt.tzinfo is not None:
    last_dt = last_dt.replace(tzinfo=None)  # → naiv
diff = datetime.now(timezone.utc) - last_dt   # aware - naiv → TypeError!
```

**Problem:** Zeile 97 entfernt die Timezone-Info, Zeile 98 subtrahiert ein aware `datetime` von einem jetzt naiven `datetime`.

**Fix:**
```python
if last_dt.tzinfo is not None:
    last_dt = last_dt.astimezone(timezone.utc)
else:
    last_dt = last_dt.replace(tzinfo=timezone.utc)
diff = datetime.now(timezone.utc) - last_dt
```

---

## Teil 2: Sicherheits-Findings

### HOCH — Prompt Injection

#### H-1: intent_tracker.py:50 — User-Text ungefiltert im Prompt

```python
# INTENT_EXTRACTION_PROMPT (Zeile 50)
Text:
{text}
```

User-Text wird ungefiltert direkt in den LLM-Prompt eingesetzt. Kein Sanitizing, keine Trennung als separate User-Message.

**CLAUDE.md-Regel verletzt:** *"Niemals User-Daten in LLM System-Prompts einbetten"*

---

#### H-2: action_planner.py — User-Request direkt im Planungs-Prompt

```python
# action_planner.py, _PLAN_PROMPT
prompt = _PLAN_PROMPT.format(request=user_request, context=context)
```

User-Request wird ohne Sanitisierung direkt in den Planungs-Prompt eingebettet. Ein bösartiger Input könnte die Aktionsplanung manipulieren und unbeabsichtigte Gerätesteuerung auslösen.

---

#### H-3: protocol_engine.py:418 — Prompt Injection (teilweise mitigiert)

```python
prompt = _PARSE_PROMPT.replace("{description}", sanitized_description)
```

`_sanitize_input()` entfernt Control Characters und Role-Marker, aber der Text wird trotzdem direkt eingebettet statt als separate User-Message. Architekturmuster widerspricht der eigenen Sicherheitsregel.

---

### MITTEL — Weitere Sicherheits-Findings

#### S-1: tts_enhancer.py — SSML-Injection

User-Text wird ohne Sanitizing in SSML eingebettet. Ein Input wie `<break time="999s"/>` könnte die TTS-Ausgabe manipulieren.

#### S-2: main.py:1986-1994 — WebSocket Same-Origin Auth-Bypass

```python
if origin and origin.startswith(("http://localhost", "http://127.0.0.1", ...)):
    # Auth bypass für Browser-Clients
```

Ein lokaler Prozess oder XSS auf einer lokalen Seite könnte den WebSocket ohne API-Key nutzen. Da das System lokal läuft, ist das Risiko begrenzt.

#### S-3: brain.py — Exception-Details in Chat-Antworten

Interne Fehlermeldungen (Ollama-Connection-Errors, Redis-Errors) werden teilweise an den User weitergegeben. Könnte Infrastruktur-Details preisgeben (Hostnames, Ports).

#### S-4: personality.py — User-Daten im Persona-Prompt

User-Name, erkannte Stimmung und Präferenzen fließen via f-String in den System-Prompt. Da diese aus internen Quellen (Redis, Semantic Memory) kommen, ist das Risiko geringer als bei direktem User-Input.

---

## Teil 3: Concurrency & Race Conditions

### MITTEL — Async Race Conditions

#### C-1: proactive.py — Cooldown-Dict TOCTOU ohne Lock

```python
# Zwei Coroutines können gleichzeitig _check_cooldown passieren
async def _check_cooldown(self, key):
    if key in self._cooldowns:  # Check
        ...
async def _set_cooldown(self, key):
    self._cooldowns[key] = time.time()  # Set
# Kein asyncio.Lock → doppelte Auslösung möglich
```

#### C-2: anticipation.py — Dict-Iteration während Modifikation

`_evaluate_patterns` iteriert über `self._patterns.items()` während `_learn_pattern` neue Patterns hinzufügt. Kann `RuntimeError: dictionary changed size during iteration` auslösen.

#### C-3: pattern_engine.py (Addon) — Shared Dicts ohne threading.Lock

`self._pattern_cache` und `self._active_patterns` werden von Flask-Request-Handlern und Event-Bus-Callbacks in verschiedenen Threads modifiziert, ohne Lock.

### MITTEL — Blockierende Aufrufe in Async Code

#### C-4: semantic_memory.py, knowledge_base.py, recipe_store.py, workshop_library.py — Synchrone ChromaDB

ChromaDB's Python-Client ist synchron. Aufrufe wie `collection.query()` blockieren den asyncio Event-Loop. Sollte in `asyncio.to_thread()` gewrappt werden.

#### C-5: embeddings.py — Synchrone Embedding-Berechnung

`sentence-transformers model.encode()` ist CPU-intensiv und blockiert den Event-Loop. Sollte in `asyncio.to_thread()` gewrappt werden.

### MITTEL — Fire-and-Forget ohne Error-Callback

#### C-6: proactive.py — 4-6 Stellen mit `create_task()` ohne `add_done_callback`

Per CLAUDE.md-Regel müssen alle Fire-and-Forget Tasks einen Error-Callback haben. In proactive.py fehlt dieser an mehreren Stellen.

#### C-6b: light_engine.py:80 — `ensure_future()` ohne `add_done_callback` (HOCH)

```python
self._task = asyncio.ensure_future(self._check_loop())
# Kein add_done_callback → Exception in der Check-Loop geht still verloren
```

Die zentrale Licht-Check-Loop hat keinen Error-Callback. Wenn die Loop crashed, stoppt die Lichtsteuerung ohne jede Fehlermeldung.

### MITTEL — Lock während I/O

#### C-7: conversation_memory.py — Lock während ChromaDB-Zugriff

`self._lock` wird gehalten während ChromaDB-Operationen ausgeführt werden (>100ms bei großen Collections). Andere Coroutines die auf den Lock warten werden unnötig blockiert.

---

## Teil 4: Logik- und Qualitätsfehler

### MITTEL

#### M-1: llm_enhancer.py:296 — Operator-Precedence-Bug

```python
role = person or "User" if m.get("role") == "user" else "Jarvis"
# Python parsed: person or ("User" if cond else "Jarvis")
# Beabsichtigt: (person or "User") if cond else "Jarvis"
```

Wenn `person` truthy ist, wird `role` **immer** zum Personennamen — auch für Jarvis-Nachrichten.

#### M-2: main.py — Hardcodierte Versionsstrings (5 Stellen)

| Zeile | Wert | Soll (version.py) |
|-------|------|--------------------|
| 347 | `"v1.4.1"` | `1.5.13` |
| 416 | `"1.4.2"` | `1.5.13` |
| 8484 | `"1.4.2"` | `1.5.13` |
| 8804 | `"1.4.2"` | `1.5.13` |
| 8926 | `"1.4.2"` | `1.5.13` |

#### M-3: health_monitor.py:71,78 — Kein Redis-Backing für Alert-State

Alert-Hysteresis und Cooldowns nur In-Memory → Flapping nach Neustart, besonders störend nachts.

#### M-4: multi_room_audio.py:651 — call_service mit Keyword-Args statt Dict

#### M-5: config.py:72-73 — YAML-Fehler wird still geschluckt

```python
except yaml.YAMLError:
    return {}  # Kein Logging!
```

#### M-6: ha_connection.py:~380 — WebSocket-Lock blockiert bei Timeout

`_ws_lock` wird während `send_json` + `receive_json` gehalten. Bei Netzwerk-Timeout kann der Lock bis zu 30s blockiert sein → andere Threads warten.

#### M-7: cover_config.py — Kein File-Locking bei JSON-Dateizugriffen

Mehrere API-Endpunkte können gleichzeitig die JSON-Konfigurationsdatei lesen und schreiben. Bei parallelen Requests kann es zum Datenverlust kommen. Ein `threading.Lock()` oder `filelock` fehlt.

#### M-8: time_awareness.py:308 — Zugriff auf nicht-initialisierten Attribut

`_check_lights_empty_rooms()` greift auf `self._light_engine` zu, das weder im Konstruktor noch in `initialize()` gesetzt wird. Es muss extern via `setattr` gesetzt werden — fragil und fehleranfällig.

---

## Teil 4b: Übersehene Module (nachträglicher Vollständigkeitsabgleich)

Folgende 5 Module waren in keiner der initialen 6 Audit-Gruppen enthalten und wurden nachträglich auditiert:

### climate_model.py — Climate Digital Twin

Simuliert Temperaturverläufe für Was-wäre-wenn-Fragen. Wird von brain.py importiert.

- **NIEDRIG:** `import re` inline in `_parse_what_if()` statt auf Modul-Ebene
- **NIEDRIG:** Keine Längenbegrenzung für `question`-Parameter (kommt aus User-Input via brain.py)

### cover_config.py — Cover-Konfiguration

Lokale JSON-basierte Cover-Gruppen, Szenen, Zeitpläne. Wird von function_calling.py, proactive.py, main.py importiert.

- **MITTEL:** Kein File-Locking (siehe M-7)
- **NIEDRIG:** `update_power_close_rule()` hat keine Input-Validierung (threshold könnte negativ sein)
- **NIEDRIG:** Hardcoded `_DATA_DIR = Path("/app/data")`

### light_engine.py — Zentrale Lichtsteuerung

Präsenz-basiert, Bettsensoren, Lux-adaptiv, Night-Dimming, Weather-Boost. Wird von brain.py importiert.

- **HOCH:** `asyncio.ensure_future()` ohne `add_done_callback` (Zeile 80) — Exceptions in der Check-Loop gehen still verloren. Widerspricht direkt CLAUDE.md-Regel.
- **NIEDRIG:** Variable `l` in List-Comprehension (verwechselbar mit `1`)

### time_awareness.py — Geräte-Laufzeit-Überwachung

Ofen, Bügeleisen, Waschmaschine, Licht in leeren Räumen. Wird von brain.py importiert.

- **MITTEL:** `self._light_engine` nicht im Konstruktor initialisiert (siehe M-8)
- **NIEDRIG:** `_pending_alerts` (Zeile 73) wird nie gelesen — toter Code
- **NIEDRIG:** Zirkuläre Imports umgangen durch Inline-Imports (Zeilen 287, 381, 431) — funktioniert, aber undokumentiert

### circuit_breaker.py — Fault Tolerance

Circuit-Breaker für externe Dienste. Wird von ha_client.py, ollama_client.py, memory.py, web_search.py importiert.

- **NIEDRIG:** Direkter Zugriff auf privates `_failure_count` in `get_graduated_state()` (Zeile 200)
- **NIEDRIG:** Verwendet `threading.Lock()` in async-Kontext (Lock-Sektionen minimal, kein praktisches Problem)

---

## Teil 5: Addon-spezifische Findings

### MITTEL

#### A-1: 6 Route-Dateien — Legacy `get_db()` statt `get_db_session()` (17 Stellen)

| Datei | Vorkommen |
|-------|-----------|
| routes/api.py | 3 |
| routes/devices.py | 2 |
| routes/automation.py | 4 |
| routes/settings.py | 2 |
| routes/scenes.py | 1 |
| pattern_engine.py | 5 |

Risiko: Session-Leak wenn `session.close()` vergessen wird.

### NIEDRIG

#### A-2: pattern_engine.py + 3 Dateien — `datetime.now()` statt `local_now()` (25 Stellen)

Naive Datetimes statt timezone-aware. Da SQLite ohnehin naiv speichert, ist das Risiko gering, aber inkonsistent mit dem Rest der Codebase.

#### A-3: event_bus.py — Kein Handler-Timeout

Ein hängender Handler blockiert alle nachfolgenden Events in der Queue. Kein Schutz gegen Endlos-Handler.

#### A-4: app.py — SECRET_KEY bei jedem Restart neu generiert

Wenn `/data/flask_secret` nicht existiert und keine Umgebungsvariable gesetzt ist, werden Sessions bei jedem Restart invalidiert.

---

## Teil 6: Niedrige Findings (Sammlung)

| # | Datei | Finding |
|---|-------|---------|
| N-1 | task_registry.py:133,135 | `asyncio.get_event_loop()` und `ensure_future()` deprecated |
| N-2 | inventory.py:70 | Interne Fehlerdetails an User exponiert (`str(e)`) |
| N-3 | notification_dedup.py:73 | `_enabled` nicht im `__init__` gesetzt |
| N-4 | circuit_breaker.py | Kein asyncio.Lock für State-Transitions |
| N-5 | main.py | Health/Metrics-Endpunkte ohne Auth (üblich aber exponiert Systeminfo) |
| N-6 | context_builder.py | 80+ Regex für Prompt-Injection sequentiell → Performance bei langem Input |
| N-7 | event_logger.py | Keine Testdatei vorhanden |
| N-8 | response_cache.py | Cache-Dict ohne asyncio.Lock |
| N-9 | feedback.py | Cooldown-Dict ohne Lock |
| N-10 | inner_state.py | Stimmungs-Updates ohne Lock |
| N-11 | brain.py | 2-3 create_task ohne add_done_callback |
| N-12 | routine_engine.py | create_task ohne add_done_callback |
| N-13 | Diverse Module | Hardcoded Werte die konfigurierbar sein sollten |

---

## Widerlegte Findings

| Finding | Ergebnis | Grund |
|---------|----------|-------|
| knowledge_graph.py ist Dead Code | **WIDERLEGT** | Wird in brain.py:48 importiert und brain.py:489 instanziiert |
| brain.py schneidet Kontext still ab | **WIDERLEGT** | Informiert LLM explizit per `[SYSTEM-HINWEIS]` über fehlende Daten (brain.py:5622) |
| dialogue_state.py:573 Deque-Index-Bug | **WIDERLEGT** | Zugriff via `[-1]` auf Deque ist korrekt, nur redundante Prüfung |

---

## Positiv-Befunde

Was besonders gut umgesetzt ist:

1. **7-Schichten SSRF-Schutz** (web_search.py): DNS-Pinning, IPv4-mapped IPv6, SearXNG Bang-Filterung — übertrifft Industriestandard
2. **Context Window Management** (brain.py): Adaptives Budget mit priorisiertem Dropping und LLM-Benachrichtigung
3. **Function Validator**: Trust-Level, Security Zones, Parameter-Bounds, Immutable Core
4. **Anti-Bot-Features** (brain_humanizers.py): Natürliche Antwortvarianz, Denkpausen
5. **Autonomie-System** (autonomy.py): 5 Level, domänenspezifisch, mit Sicherheitsvalidierung
6. **Pushback-System**: Intelligente Rückfragen bei fragwürdigen Befehlen
7. **Speaker Recognition**: 7-stufiges System mit Voice-Embedding-basierter Identifikation
8. **PIN-Sicherheit**: PBKDF2-HMAC-SHA256, 600K Iterationen, Brute-Force-Schutz
9. **Test-Coverage**: 90+ Testdateien für ~99 Module
10. **Config Versioning**: Snapshots vor Konfigurationsänderungen mit Rollback
11. **Circuit Breaker**: Redis-persistierter State, Auto-Fallback bei Service-Ausfall
12. **Timer-Sicherheit**: Whitelist für erlaubte Timer-Aktionen

---

## Empfohlene Prioritäten

### Sofort fixbar (< 15 Min)

| Prio | Finding | Aufwand |
|------|---------|--------|
| 1 | K-1: memory_extractor.py Import fixen | 2 Min |
| 2 | K-2: situation_model.py Datetime fixen | 5 Min |
| 3 | M-1: llm_enhancer.py Klammern setzen | 2 Min |
| 4 | M-5: config.py YAML-Fehler loggen | 5 Min |
| 5 | light_engine.py:80 add_done_callback ergänzen | 5 Min |

### Kurzfristig (< 1 Stunde)

| Prio | Finding | Aufwand |
|------|---------|--------|
| 6 | H-1: intent_tracker.py User-Message trennen | 15 Min |
| 7 | H-2: action_planner.py User-Message trennen | 15 Min |
| 8 | M-2: main.py Versionen zentralisieren | 10 Min |
| 9 | C-6: proactive.py add_done_callback ergänzen | 15 Min |
| 10 | M-7: cover_config.py File-Locking hinzufügen | 15 Min |
| 11 | M-8: time_awareness.py _light_engine im __init__ | 10 Min |

### Mittelfristig (< 1 Tag)

| Prio | Finding | Aufwand |
|------|---------|--------|
| 12 | M-3: health_monitor.py Redis-State | 30 Min |
| 13 | C-4: ChromaDB-Aufrufe in asyncio.to_thread() wrappen | 2 Std |
| 14 | C-5: Embedding-Berechnung in asyncio.to_thread() | 30 Min |
| 15 | A-1: Legacy get_db() → get_db_session() migrieren | 1 Std |
| 16 | C-1/C-2: asyncio.Lock für Cooldown/Pattern-Dicts | 1 Std |

---

*Audit durchgeführt am 21.03.2026 — 5-Pass-Analyse mit 10 parallelen Audit-Agents über alle 99 Module + Addon-Code.*
