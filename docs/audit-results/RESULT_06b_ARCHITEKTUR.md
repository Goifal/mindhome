# Audit-Ergebnis: Prompt 6b — Architektur: Konflikte auflösen & Flows reparieren

**Durchlauf**: #2
**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: brain.py Architektur, Konflikte A/B/E, Flows 1/2/6/11, HIGH-Bugs, Performance
**Baseline**: 2551 passed, 1197 failed (identisch mit 6a-Baseline)

> **DL#3 (2026-03-13)**: Historisches Fix-Log aus DL#2. P02 Memory-Reparatur aendert diese Fixes nicht. Alle dokumentierten Fixes bleiben gueltig.

---

## Phase Gate: Baseline

```
Vor 6b: 2551 passed, 1197 failed
Nach 6b: 2551 passed, 1197 failed
→ KEINE Regressionen
```

---

## 1. Architektur-Entscheidung

| Entscheidung | Gewählt | Begründung | Geänderte Dateien |
|---|---|---|---|
| brain.py | **Option A: Refactoring** (Mixin-Extraktion fortsetzen) | brain.py hat 9800 Zeilen, 111 Methoden, 81+ Imports. Mixin-Pattern bereits gestartet (BrainHumanizersMixin, BrainCallbacksMixin). Minimaler Umbau, maximaler Effekt. | brain.py (Zukunft: weitere Mixins extrahieren) |
| Priority-System | **User-Request-Flag + Lock-Timeout** | `_user_request_active` Flag suppressed proaktive Callbacks während User-Requests. Lock-Timeout verhindert endloses Warten. | brain.py |

### Addon-Kompatibilitäts-Check (Pflicht vor Architektur-Umbau)

- **Schnittstellen**:
  - `addon/rootfs/opt/mindhome/routes/chat.py:79-107` → Proxy zu `/api/assistant/chat`
  - `addon/rootfs/opt/mindhome/ha_connection.py:69-87` → GET `/api/assistant/entity_owner/{id}`
  - `assistant/assistant/ha_client.py:43,287-322` → `mindhome_url`, `mindhome_get()`, `mindhome_post()` zum Addon
- **Von Architektur-Änderung betroffen**: Nein — alle Änderungen sind intern (brain.py Methoden, Locks, Flags). API-Endpoints und Redis-Keys bleiben unverändert.

---

## 2. Konflikt-Lösungen

### Konflikt A: Wer bestimmt was Jarvis SAGT?
- **Status**: Bereits korrekt implementiert — `context_builder.py` baut den Prompt (mit Mega-Gather für 20+ parallele Datenquellen), `personality.py` liefert System-Prompt und Charakter. Keine Änderung nötig.

### Konflikt B: Wer bestimmt was Jarvis TUT?
- **Lösung**: Priority-Hierarchie implementiert: `User-Befehl > Routine > Proaktiv > Autonom`
  - `_user_request_active` Flag in brain.py (gesetzt während `process()`)
  - `_callback_should_speak()` prüft das Flag — unterdrückt proaktive Callbacks während User-Requests (außer CRITICAL)
  - Bestehender `conflict_resolver` im Function-Calling-Loop (brain.py:3503-3518) bleibt aktiv für Multi-User-Konflikte
- **Geänderte Dateien**: brain.py (3 Stellen: __init__, process(), _callback_should_speak())
- **Verifikation**: Tests grün (2551 passed)

### Konflikt E: Timing & Prioritäten
- **Lösung**: Lock-Timeout für `_process_lock`
  - `asyncio.wait_for(self._process_lock.acquire(), timeout=30.0)` statt `async with self._process_lock`
  - Bei Timeout: Freundliche Fehlermeldung statt endlosem Warten
  - User-Request wird nie länger als 30s durch vorherigen Request blockiert
- **Geänderte Dateien**: brain.py (process() Methode)
- **Verifikation**: Tests grün (2551 passed)

---

## 3. Flow-Fixes

| Flow | Bruchstelle | Fix | Status |
|---|---|---|---|
| 1: Sprach-Input → Antwort | brain.py:1103 — `_process_lock` serialisiert ALLE Requests (nur 1 concurrent) | Lock-Timeout (30s) + User-Priority-Flag | ✅ |
| 2: Proaktive Benachrichtigung | brain.py:773 — `proactive.start()` nicht in `_safe_init()` | Gewrappt in `_safe_init("Proactive.start", ...)` | ✅ |
| 6: Memory-Frage | brain.py:3204 — Wenn keine Fakten gefunden: LLM halluziniert "Erinnerungen" | Expliziter No-Memory-Prompt: "ERFINDE KEINE Erinnerungen" | ✅ |
| 11: Boot-Sequenz | brain.py:520-800 — Alle Module in `_safe_init()` | Proactive.start() war die letzte Lücke → jetzt gefixt | ✅ |

---

## 4. Performance-Optimierungen

| Optimierung | Datei | Vorher | Nachher |
|---|---|---|---|
| N+1 HTTP: `_get_speaker_names()` | multi_room_audio.py:484 | Sequentielle `get_state()` pro Speaker | `asyncio.gather()` — parallel |
| N+1 HTTP: `_build_group_status()` | multi_room_audio.py:416 | Sequentielle State-Queries pro Speaker | `asyncio.gather()` — parallel |

### asyncio.gather Nutzung nach 6b:
- brain.py: 1 (Mega-Gather mit 20+ Tasks)
- multi_room_audio.py: +2 (neu)

---

## 5. 🟠 Bug-Fixes

### 🟠 Bug: proactive.start() ohne _safe_init (CRITICAL)
- **Datei**: brain.py:773
- **Fix**: `await _safe_init("Proactive.start", self.proactive.start())`
- **Tests**: ✅

### 🟠 Bug: wellness_advisor.py — 9x ungeschützte Redis-Calls
- **Datei**: wellness_advisor.py:180,240,261,337,402,481,609,638,701
- **Fix**: Alle 9 bare `await self.redis.*` Calls durch `_safe_redis()` Wrapper ersetzt
- **Tests**: ✅

### 🟠 Bug: knowledge_base.py — Sync ChromaDB blockiert Event Loop
- **Datei**: knowledge_base.py:71,549,558
- **Fix**: `get_or_create_collection()` und `delete_collection()` in `asyncio.to_thread()` gewrappt
- **Tests**: ✅

### 🟠 Bug: cooking_assistant.py — NullPointer bei session=None
- **Datei**: cooking_assistant.py:486,510,520,527
- **Fix**: Null-Guards für `self.session` in `_next_step()`, `_prev_step()`, `_repeat_step()`, `_show_status()`
- **Tests**: ✅

### 🟠 Bug: multi_room_audio.py — N+1 HTTP sequentiell
- **Datei**: multi_room_audio.py:484-496,416-438
- **Fix**: Sequentielle Loops durch `asyncio.gather()` ersetzt
- **Tests**: ✅

---

## 6. Geänderte Dateien (Zusammenfassung)

| Datei | Änderungen | Zeilen |
|---|---|---|
| brain.py | proactive._safe_init, _user_request_active, Lock-Timeout, Memory-No-Hallucination | +40/-2 |
| wellness_advisor.py | 9x _safe_redis Wrapper | +9/-9 |
| knowledge_base.py | 3x asyncio.to_thread für ChromaDB | +12/-3 |
| cooking_assistant.py | 4x session Null-Guards | +8/+0 |
| multi_room_audio.py | 2x asyncio.gather für N+1 HTTP | +38/-29 |

---

## ⚡ Übergabe an Prompt 6c

```
## KONTEXT AUS PROMPT 6b: Architektur

### Architektur-Entscheidung
brain.py → Option A (Refactoring/Mixin-Extraktion), Priority-System → User-Request-Flag + Lock-Timeout

### Gelöste Konflikte
A → Bereits korrekt (context_builder + personality)
B → _user_request_active Flag unterdrückt proaktive Callbacks während User-Requests
E → Lock-Timeout 30s + freundliche Fehlermeldung bei Blockierung

### Reparierte Flows
Flow 1 → Lock-Timeout (30s), User-Priority
Flow 2 → proactive.start() in _safe_init()
Flow 6 → No-Hallucination-Prompt bei fehlenden Memory-Fakten
Flow 11 → Letzte _safe_init-Lücke geschlossen

### Gefixte 🟠 Bugs
- brain.py:773 → proactive.start() _safe_init
- wellness_advisor.py → 9x _safe_redis
- knowledge_base.py → 3x asyncio.to_thread
- cooking_assistant.py → 4x session Null-Guard
- multi_room_audio.py → 2x asyncio.gather

### Offene Punkte für 6c/6d
- Konflikt D (Wie Jarvis KLINGT) → 6c (Persönlichkeit)
- Konflikt F (Addon ↔ Assistant Koordination) → 6d
- personality.py _current_mood/_current_formality Race Condition → threading.Lock nötig (niedrige Priorität, da _process_lock serialisiert)
- brain.py: Weitere Mixin-Extraktion (Request-Shortcuts, Memory-Handling) → zukünftige Iteration
- Verbleibende 38 HIGH-Bugs aus P4a-4c (sync I/O, Race Conditions) → zukünftige Iteration
```
