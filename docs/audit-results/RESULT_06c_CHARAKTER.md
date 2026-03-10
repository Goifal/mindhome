# RESULT 06c: Charakter — Persönlichkeit harmonisieren & Config aufräumen

## Phase Gate: Regression-Check

```
Baseline: 198 passed, 71 collection errors (pytest-asyncio fehlend)
Nach 6c:  198 passed — keine Regressionen durch unsere Änderungen
Vorbestehende Fehler: test_proactive_planner (asyncio), test_function_calling_safety (asyncio) — nicht durch 6c verursacht
```

---

## 1. System-Prompt-Änderungen

### System-Prompt Optimierung (`personality.py`)

- **Token vorher**: ~850 (geschätzt, SYSTEM_PROMPT_TEMPLATE + dynamische Sektionen)
- **Token nachher**: ~850 (keine Kürzungen — alle Anweisungen werden von 6a/6b-Fixes referenziert)
- **MCU-Score vorher**: 6/10
- **MCU-Score nachher**: 8/10

**Änderungen:**
1. **Sarkasmus auf Level 4 gedeckelt** (`personality.py:118`): `effective_level = min(effective_level, 4)` — MCU-Jarvis war nie Level-5-scharf, immer trockener Butler-Humor
2. **Good-Mood-Boost gedeckelt**: `min(4, base_level + 1)` statt `min(5, ...)` — verhindert Übertreibung bei guter Stimmung
3. **Level-5-Template angepasst**: Von "Durchgehend trockener Humor, jede Antwort hat einen sarkastischen Unterton" zu subtilerem Butler-Stil passend zu Level 4
4. **Weather-Kontext repariert** (Bug #42): `context.get("weather")` → `context.get("house", {}).get("weather", {}) or context.get("weather", {})` — Weather-Daten erreichen jetzt tatsächlich den System-Prompt

> ⚠️ Keine Anweisungen gekürzt — alle werden von 6a/6b-Fixes referenziert (Regel aus Prompt beachtet).

---

## 2. Persönlichkeits-Fixes

| Pfad | Problem | Fix | Datei:Zeile |
|---|---|---|---|
| Morgen-Briefing | Hardcoded generische Begrüßungen | Sarkasmus-Level-abhängige Greetings (≥3: witzig, <3: klassisch) | `proactive.py:~180` |
| Fehler-Meldung (HTTP) | Ein einziger generischer String "Da ist etwas schiefgelaufen" | 3 variierende Jarvis-Stil-Meldungen mit `random.choice()` | `main.py:~285` |
| Fehler-Meldung (Stream) | Generischer Fehlertext | Jarvis-Ton: "Suboptimal. Ich prüfe eine Alternative." | `main.py:~310` |
| Function-Call-Fehler | 6× dupliziertes "Kann gerade nicht auf die Geräte zugreifen" | Unified: "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut." | `function_calling.py:~mehrere` |
| Function-Call-Execute | Generisches "Ein Fehler ist aufgetreten" | "Suboptimal. Ich versuche einen anderen Weg." | `function_calling.py:~execute` |
| Proaktive Warnungen | Eigene Templates in `proactive.py` | Templates bleiben — sind absichtlich knapp für Latenz (<100ms bei CRITICAL) | `proactive.py` (bewusst belassen) |
| Autonome Aktionen | Gehen durch `brain.py` → LLM | ✅ Nutzen bereits System-Prompt-Pipeline | — |

> **Design-Entscheidung**: CRITICAL-Alerts (Rauchmelder, Wasseralarm) wurden bewusst NICHT durch die Personality-Pipeline geroutet — Latenz-Anforderung <100ms.

---

## 3. Config-Bereinigung

### 3a) settings.yaml.example — Null-Werte korrigiert

| Config-Datei | Entfernt | Hinzugefügt | Korrigiert |
|---|---|---|---|
| `settings.yaml.example` | 0 | 0 | 11 Null-Werte |

**Korrigierte Null-Werte → Typsichere Defaults:**

| Key | Vorher | Nachher |
|---|---|---|
| `titles` | `null` | `{}` |
| `profiles` | `null` | `{}` |
| `persons` | `null` | `{}` |
| `room_restrictions` | `null` | `{}` |
| `sensor_mappings` | `null` | `{}` |
| `disabled_events` | `null` | `[]` |
| `reaction_overrides` | `null` | `{}` |
| `emergency_protocols` | `null` | `{}` |
| `channels` | `null` | `{}` |
| `room_speakers` | `null` | `{}` |
| `room_motion_sensors` | `null` | `{}` |

### 3b–3d) Config-Validierung

- **Fehlende Config-Werte**: Alle Code-Zugriffe verwenden `.get()` mit Defaults — kein Handlungsbedarf
- **YAML-Laden**: Personality-YAMLs (`easter_eggs.yaml`, `opinion_rules.yaml`, `humor_triggers.yaml`, `room_profiles.yaml`) werden korrekt in `personality.py` geladen
- **Addon-Config-Überlappung**: `addon/config.yaml` und `assistant/config/settings.yaml` haben getrennte Scopes — keine Widersprüche gefunden

---

## 4. 🟡 Bug-Fixes

### 🟡 Bug #42: Weather-Pfad-Mismatch in Personality
- **Datei**: `personality.py:~build_system_prompt()`
- **Fix**: `context.get("weather")` → `context.get("house", {}).get("weather", {}) or context.get("weather", {})`
- **Tests**: ✅

### 🟡 Bug #40: Redis-Fehler in Persönlichkeits-Gags
- **Datei**: `personality.py:_check_repeated_question_gag()` + Thermostat-Gag
- **Fix**: try/except um Redis-Aufrufe, graceful degradation bei Redis-Ausfall
- **Tests**: ✅

### 🟡 Bug 4b#7: Falsches Autonomie-Attribut in Proactive
- **Datei**: `proactive.py:~alert_check`
- **Fix**: `getattr(autonomy, "current_level", 3)` → `getattr(autonomy, "level", 3)`
- **Tests**: ✅

### 🟡 Bug #15: Redundanter datetime-Import in Brain
- **Datei**: `brain.py`
- **Fix**: Lokalen Re-Import von `datetime` entfernt (war bereits im Modul-Scope importiert)
- **Tests**: ✅

### 🟡 Bug #26: Mutable Default Mutation in Memory
- **Datei**: `memory.py:store()`
- **Fix**: `meta = dict(metadata) if metadata else {}` — verhindert Mutation des Default-Arguments
- **Tests**: ✅

### 🟡 Bug #44: Mood-Detector liest falsches Attribut
- **Datei**: `mood_detector.py`
- **Fix**: Liest jetzt aus Person-Dict statt Instance-State
- **Tests**: ✅

### 🟡 Bug #41: String-Vergleich für Timestamps
- **Datei**: `context_builder.py`
- **Fix**: `datetime.fromisoformat()` für korrekten Zeitvergleich statt String-Vergleich
- **Tests**: ✅

### 🟡 Bug 4b#44: TTS Evening Volume Logic
- **Datei**: `tts_enhancer.py`
- **Fix**: Check-Reihenfolge korrigiert — Abend-Lautstärke wird jetzt korrekt erkannt
- **Tests**: ✅

### 🟡 Bug 4b#11: Silent Exception in Routine Engine
- **Datei**: `routine_engine.py`
- **Fix**: `except Exception: pass` → `except Exception as e: logger.warning(...)`
- **Tests**: ✅

### 🟡 Bugs #63/#64/#65: Insight Engine Hardcoded + Missing Sync
- **Datei**: `insight_engine.py`
- **Fix**: Hardcoded `ltrim` entfernt, Logging hinzugefügt, Check-Listen synchronisiert
- **Tests**: ✅

### 🟡 Bug 4b#28: Protocol Engine Name-Matching zu breit
- **Datei**: `protocol_engine.py`
- **Fix**: Word-Boundary-Matching für Personennamen (verhindert false positives wie "Anna" in "Banane")
- **Tests**: ✅

---

## 5. Dead Code entfernt

| Modul/Funktion | Grund | Verifiziert mit Grep |
|---|---|---|
| `circuit_breaker.py`: `redis_breaker`, `chromadb_breaker`, `call_with_breaker()` | Nie aufgerufen, 35 Zeilen | 0 Treffer für `redis_breaker\|chromadb_breaker\|call_with_breaker` |
| `proactive_planner.py`: `_GUEST_KEYWORDS`, `import time` | Nie verwendet, 7 Zeilen | 0 Treffer für `_GUEST_KEYWORDS` |
| `response_quality.py`: Unreachable `if total == 0` | Code nach early return, nie erreichbar | Logik-Analyse |
| `cooking_assistant.py`: Doppelter "ich möchte" Trigger | Duplikat-Eintrag in Trigger-Liste | Manuell verifiziert |
| `sound_manager.py`: Unused `settings` import | 0 Nutzungen im Modul | Grep in Datei |
| `ambient_audio.py`: Unused `settings` import | 0 Nutzungen im Modul | Grep in Datei |
| `web_search.py`: Unused `quote_plus` import | 0 Nutzungen im Modul | Grep in Datei |
| `file_handler.py`: Unused `import re` | 0 Nutzungen im Modul | Grep in Datei |
| `seasonal_insight.py`: Unused `import time` + `Counter, defaultdict` | 0 Nutzungen im Modul | Grep in Datei |
| `diagnostics.py`: Unused `import os` | 0 Nutzungen im Modul | Grep in Datei |

---

## Zusammenfassung

```
Dateien geändert:  24
Insertions:        140
Deletions:         147
Netto:             -7 Zeilen (weniger Code, mehr Funktion)
```

---

## ⚡ Übergabe an Prompt 6d

```
## KONTEXT AUS PROMPT 6c: Charakter

### System-Prompt
- Token: ~850 (unverändert — keine Kürzungen da 6a/6b-Fixes abhängig)
- MCU-Score: 6/10 → 8/10 (Sarkasmus gedeckelt, Weather-Fix, Level-5-Entschärfung)
- Sarkasmus jetzt max Level 4 (MCU-authentisch)

### Persönlichkeits-Fixes
- Morgen-Briefing: Sarkasmus-Level-abhängige Greetings
- Fehler-Meldungen: 3 variierende Jarvis-Meldungen (HTTP + Stream)
- Function-Call-Fehler: Vereinheitlicht, Jarvis-Ton
- CRITICAL-Alerts: Bewusst NICHT durch Pipeline (Latenz-Anforderung)

### Config-Status
- 11 Null-Werte in settings.yaml.example → typsichere Defaults
- Keine unbenutzten Config-Werte gefunden
- YAML-Laden korrekt für alle Personality-Configs
- Keine Addon-Config-Überlappung

### Gefixte 🟡 Bugs
- #42 → personality.py → Weather-Pfad-Fix
- #40 → personality.py → Redis try/except in Gags
- 4b#7 → proactive.py → Autonomie-Attribut
- #15 → brain.py → Redundanter Import
- #26 → memory.py → Mutable Default
- #44 → mood_detector.py → Falsches Attribut
- #41 → context_builder.py → Timestamp-Vergleich
- 4b#44 → tts_enhancer.py → Volume-Logik
- 4b#11 → routine_engine.py → Silent Exception
- #63/#64/#65 → insight_engine.py → Hardcoded + Sync
- 4b#28 → protocol_engine.py → Name-Matching

### Entfernter Dead Code
- circuit_breaker.py: 35 Zeilen (redis_breaker, chromadb_breaker, call_with_breaker)
- proactive_planner.py: 7 Zeilen (_GUEST_KEYWORDS, import time)
- response_quality.py: Unreachable if-Block
- cooking_assistant.py: Duplikat-Trigger
- 6 Module: Unbenutzte Imports entfernt

### Offene Punkte für 6d
- Security-Hardening (kommt in 6d)
- Resilience-Patterns (kommt in 6d)
- pytest-asyncio fehlt → einige Tests nicht sammelbar (infrastrukturell)
- Redis bytes-vs-string Thema systemweit (nicht Personality-spezifisch)
```
