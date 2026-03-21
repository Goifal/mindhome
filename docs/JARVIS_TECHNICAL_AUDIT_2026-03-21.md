# J.A.R.V.I.S. Technical Audit — 2026-03-21

> **Scope:** Vollständiger Code-Audit aller 98 Module im `assistant/assistant/`-Paket
> **Methodik:** 3-Pass-Analyse (Modul-Audit → Quality Deep Dive → Cross-Verification)
> **Auditor:** Claude Code (Opus 4.6), 6 parallele Audit-Agents
> **Module auditiert:** 65+ Dateien, ~106K Zeilen Code

---

## Executive Summary

Die J.A.R.V.I.S.-Codebase ist insgesamt **solide und professionell** aufgebaut. Die Architektur mit Event-Bus, 3-Schichten-Gedächtnis, 3-Tier-LLM-Routing und 7-Schichten-SSRF-Schutz zeigt fortgeschrittenes Engineering. Das System ist für ein Einzelentwickler-Projekt bemerkenswert umfangreich und durchdacht.

**Kritische Findings:** 2 Bugs die Laufzeitfehler verursachen
**Sicherheits-Findings:** 2 Prompt-Injection-Vektoren
**Qualitäts-Findings:** 18 verbesserungswürdige Stellen
**Architektur-Findings:** 5 strukturelle Beobachtungen

---

## Bestätigte Findings nach Schweregrad

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

**Problem:** Zeile 97 entfernt die Timezone-Info, Zeile 98 subtrahiert ein aware `datetime` von einem jetzt naiven `datetime`. Dies löst `TypeError: can't subtract offset-naive and offset-aware datetimes` aus.

**Fix:**
```python
if last_dt.tzinfo is not None:
    last_dt = last_dt.astimezone(timezone.utc)
else:
    last_dt = last_dt.replace(tzinfo=timezone.utc)
diff = datetime.now(timezone.utc) - last_dt
```

---

### HOCH — Sicherheit

#### H-1: intent_tracker.py:26-52 — Prompt Injection

```python
# intent_tracker.py, INTENT_EXTRACTION_PROMPT (Zeile 50)
Text:
{text}
```

**Problem:** User-Text wird ungefiltert direkt in den LLM-Prompt eingesetzt. Kein Sanitizing, keine Trennung als separate User-Message. Ein bösartiger Input kann den Intent-Extraction-Prompt manipulieren.

**CLAUDE.md-Regel verletzt:** *"Niemals User-Daten in LLM System-Prompts einbetten — als separate User-Messages übergeben"*

**Fix:** User-Text als separate `{"role": "user", "content": text}` Message übergeben, nicht per String-Interpolation.

---

#### H-2: protocol_engine.py:418 — Prompt Injection (teilweise mitigiert)

```python
# protocol_engine.py:418
prompt = _PARSE_PROMPT.replace("{description}", sanitized_description)
```

**Problem:** Obwohl `_sanitize_input()` (Zeile 402-412) Control Characters und Role-Marker entfernt, wird der sanitisierte Text trotzdem direkt in den Prompt-String eingebettet statt als separate User-Message.

**Risiko:** Reduziert durch Sanitisierung, aber Architekturmuster widerspricht der eigenen Sicherheitsregel.

---

### MITTEL — Logik- und Qualitätsfehler

#### M-1: llm_enhancer.py:296 — Operator-Precedence-Bug

```python
# llm_enhancer.py:296
role = person or "User" if m.get("role") == "user" else "Jarvis"
```

**Python parsed als:** `role = person or ("User" if condition else "Jarvis")`
**Beabsichtigt:** `role = (person or "User") if condition else "Jarvis"`

**Auswirkung:** Wenn `person` truthy ist, wird `role` **immer** zum Personennamen — auch für Jarvis-Nachrichten. Jarvis-Antworten werden dann mit dem Benutzernamen gelabelt.

**Fix:** Klammern setzen: `role = (person or "User") if m.get("role") == "user" else "Jarvis"`

---

#### M-2: main.py — Hardcodierte Versionsstrings (5 Stellen)

| Zeile | Wert | Soll (version.py) |
|-------|------|--------------------|
| 347 | `"v1.4.1"` | `1.5.13` |
| 416 | `"1.4.2"` | `1.5.13` |
| 8484 | `"1.4.2"` | `1.5.13` |
| 8804 | `"1.4.2"` | `1.5.13` |
| 8926 | `"1.4.2"` | `1.5.13` |

**Fix:** `from assistant.version import VERSION` importieren und überall verwenden.

---

#### M-3: health_monitor.py:71,78 — Kein Redis-Backing für Alert-State

```python
# health_monitor.py:71,78
self._alert_active: dict[str, bool] = {}     # nur In-Memory
self._alert_cooldowns: dict[str, datetime] = {}  # nur In-Memory
```

**Problem:** Nach Neustart sind alle Alert-Zustände zurückgesetzt. Alle Alerts können erneut feuern (Flapping-Risiko), besonders störend nachts.

**Fix:** Hysteresis-State und Cooldowns in Redis persistieren mit geeignetem TTL.

---

#### M-4: multi_room_audio.py:651 — Potentieller call_service Bug

```python
# multi_room_audio.py:651-654
await self.ha.call_service("tts", "speak", entity_id=speaker, message=message)
```

**Problem:** Parameter werden als Keyword-Args statt als Dict übergeben. Je nach `call_service`-Signatur könnte dies fehlschlagen.

---

#### M-5: config.py:72-73 — YAML-Fehler wird still geschluckt

```python
except yaml.YAMLError:
    return {}  # Kein Logging!
```

**Problem:** Fehlerhafte settings.yaml wird als leeres Dict interpretiert, ohne WARNING-Log. Schwer zu debuggen.

---

### NIEDRIG — Code-Qualität

#### N-1: task_registry.py:133,135 — Deprecated APIs

- `asyncio.get_event_loop()` → sollte `asyncio.get_running_loop()` sein
- `asyncio.ensure_future()` → sollte `asyncio.create_task()` sein

#### N-2: inventory.py:70 — Interne Fehlerdetails exponiert

```python
f"Da gab es ein Problem: {e}"  # Exponiert Stack-Details
```

#### N-3: notification_dedup.py:73 — `_enabled` nicht im `__init__` gesetzt

```python
getattr(self, "_enabled", True)  # Fallback weil Attribut fehlt
```

#### N-4: Diverse Hardcoded Werte

| Modul | Wert | Besser |
|-------|------|--------|
| wellness_advisor.py | `power > 30` Watt für PC-Erkennung | Config |
| cooking_assistant.py:294 | `recipe_text[:3000]` Truncation | Config |
| web_search.py | Cache max 100 Einträge | Config |
| timer_manager.py | Max 7 Tage für Erinnerungen | Config |
| file_handler.py | `MAX_FILE_SIZE = 50 MB` | Config |

---

## Widerlegte Findings

Diese Findings aus den Einzel-Audits konnten in der Cross-Verification **nicht bestätigt** werden:

| Finding | Ergebnis | Grund |
|---------|----------|-------|
| knowledge_graph.py ist Dead Code | **WIDERLEGT** | Wird in brain.py:48 importiert und brain.py:489 instanziiert |
| brain.py schneidet Kontext still ab | **WIDERLEGT** | Informiert LLM explizit per `[SYSTEM-HINWEIS]` über fehlende Daten (brain.py:5622) |
| dialogue_state.py:573 Deque-Index-Bug | **WIDERLEGT** | Zugriff via `[-1]` auf Deque ist korrekt, nur redundante Prüfung |

---

## Architektur-Beobachtungen

### A-1: Herausragend — SSRF-Schutz (web_search.py)

Der 7-Schichten SSRF-Schutz mit DNS-Pinning (F-093), IPv4-mapped IPv6-Entpackung (F-082), SearXNG Bang-Filterung (F-089) und Response-Size-Limits ist vorbildlich und übertrifft viele professionelle Anwendungen.

### A-2: Herausragend — Context Window Management (brain.py)

Das adaptive Budget-System mit priorisiertem Dropping und expliziter LLM-Benachrichtigung über fehlende Kontextsektionen ist durchdacht implementiert.

### A-3: Herausragend — Sicherheitsarchitektur (function_validator.py)

Trust-Level-System, Security Zones, Parameter-Bounds-Validierung und Immutable Core bilden ein mehrschichtiges Sicherheitsmodell.

### A-4: Verbesserungspotential — Gedächtnis-Integration

Die 3-Schichten-Gedächtnis-Architektur (Redis → ChromaDB → Semantic Memory) ist konzeptionell stark, aber der ImportError in memory_extractor.py (K-1) bedeutet, dass die semantische Duplikat-Erkennung aktuell nicht funktioniert. Die Grundfunktionalität (Speichern/Abrufen) funktioniert aber korrekt.

### A-5: Beobachtung — Dateigröße

Mehrere Dateien überschreiten 100KB erheblich (brain.py: 629KB, function_calling.py: 419KB, state_change_log.py: 379KB, proactive.py: 378KB, main.py: 359KB). Dies erschwert Navigation und Wartung, ist aber für die Funktionalität unkritisch.

---

## Positiv-Befunde

Was besonders gut umgesetzt ist:

1. **Anti-Bot-Features** (brain_humanizers.py): Natürliche Antwortvarianz, Denkpausen, Strukturvariation
2. **Autonomie-System** (autonomy.py): 5 Level, domänenspezifisch, mit Sicherheitsvalidierung
3. **Pushback-System**: Intelligente Rückfragen bei fragwürdigen Befehlen (offene Fenster + Heizung, leerer Raum)
4. **Speaker Recognition**: 7-stufiges System mit Voice-Embedding-basierter Identifikation
5. **Threat Assessment**: Notfall-Playbooks, Krisenmodus, automatische Humor-Deaktivierung
6. **Timer-Sicherheit**: Whitelist für Timer-Aktionen (timer_manager.py:42-47)
7. **PIN-Sicherheit**: PBKDF2-HMAC-SHA256, 600K Iterationen, Brute-Force-Schutz (main.py:2441)
8. **Fire-and-Forget-Pattern**: Konsequent mit `add_done_callback` implementiert
9. **Circuit Breaker**: Auto-Fallback bei Service-Ausfall
10. **Config Versioning**: Snapshots vor Konfigurationsänderungen mit Rollback

---

## Empfohlene Prioritäten

| Priorität | Finding | Aufwand |
|-----------|---------|---------|
| 1 | K-1: memory_extractor.py Import fixen | 5 Min |
| 2 | K-2: situation_model.py Datetime fixen | 5 Min |
| 3 | M-1: llm_enhancer.py Klammern setzen | 2 Min |
| 4 | H-1: intent_tracker.py User-Message trennen | 15 Min |
| 5 | M-2: main.py Versionen zentralisieren | 10 Min |
| 6 | M-3: health_monitor.py Redis-State | 30 Min |
| 7 | H-2: protocol_engine.py User-Message trennen | 15 Min |
| 8 | M-5: config.py YAML-Fehler loggen | 5 Min |

---

*Audit durchgeführt am 21.03.2026 — basierend auf dem Repository-Stand zum Zeitpunkt des Audits.*
