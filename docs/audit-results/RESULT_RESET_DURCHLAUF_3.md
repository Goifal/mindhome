# Audit-Reset: Vorbereitung Durchlauf #3

**Datum**: 2026-03-13
**Auditor**: Claude Code (Opus 4.6)
**Zweck**: Zusammenfassung Durchlauf #1 + #2, Delta seit letztem Reset, unfixte Bugs als Checkliste

---

## ZUSAMMENFASSUNG DURCHLAUF #1 + #2

### Analyse-Phase
#### Architektur (P01)
- Kritischste Konflikte: (A) personality.py vs proactive.py (wer bestimmt Jarvis-Text) — dokumentiert, nicht geloest. (B) User vs Addon-Automation — Locks statt Event-Bus. (E) Race Conditions auf Shared State — 6 Module mit asyncio/threading.Lock
- God-Objects: brain.py (damals 10.231 Zeilen), main.py (88+ Endpoints)

#### Memory (P02)
- Fakten-Abruf: Funktioniert (nach Redis-bytes-Decode an 10+ Stellen)
- Memory-Prioritaet: Teilweise — 12 isolierte Memory-Systeme, kein kohaerenter Stack
- semantic_memory.store_fact() Redis-Fallback implementiert

#### Flows (P03a + P03b)
- Core-Flows 1-7: 4 funktionieren, 3 mit Einschraenkungen (Proactive Templates hardcoded, Personality-Pipeline 4 Bypass-Pfade, Memory kein Stack)
- Extended-Flows 8-13: Addon-Automation KEINE Koordination mit Assistant, Workshop-Bug gefixt, Boot-Sequenz mit _safe_init() gewrappt
- Kollisionen: circadian vs light_engine, cover_control vs cover_config — OFFEN

#### Bug-Jagd (P04a + P04b + P04c)
- Gesamt: 225 Bugs (KRITISCH: 5, HOCH: 47, MITTEL: 106, NIEDRIG: 64, Quick-Win: 3)
- Security-Findings: 7 (alle 7 behoben — Prompt-Injection, PIN-Brute-Force, Factory-Reset, Path-Traversal etc.)
- Performance: Latenz-Budget nicht systematisch gemessen. recipe_store.py mit Semaphore(5)

#### Persoenlichkeit (P05)
- MCU-Score: 7.2/10 → 8/10 (nach P06c)
- System-Prompt: ~850 Token
- Config-Inkonsistenzen: 11 Null-Werte korrigiert, 14 fehlende Sektionen in settings.yaml.example OFFEN

### Fix-Phase
#### Stabilisierung (P06a)
- Kritische Bugs gefixt: 8 von 10
- Memory repariert: Ja (Redis-bytes-Decode, semantic_memory Rollback, dialogue_state Eviction)

#### Architektur (P06b)
- Konflikte aufgeloest: A (dokumentiert), B (Locks), E (6 Module mit Locks)
- brain.py → Mixin-Extraktion Phase 1: 13 _humanize_* → brain_humanizers.py (-506 Zeilen)
- Priority-System: Dokumentiert, NICHT implementiert

#### Charakter (P06c)
- Persoenlichkeit harmonisiert: Teilweise — Error-Meldungen + Morgen-Briefing auf Jarvis-Stil
- Dead Code entfernt: shared/ Verzeichnis (6 Dateien)

#### Haertung (P06d)
- Security-Luecken geschlossen: 7 von 7
- Resilience: 8/10 Szenarien OK (Disk-Space gefixt, OOM/VRAM-Check OFFEN)

#### Geraetesteuerung (P06e)
- Tool-Calling: Umlaut-Normalisierung gefixt (Kueche→kuche Entity-Matching)
- Entity-Suche: MindHome-First-Strategie implementiert (DB vor HA-States)
- LLM-Fehlermeldung bei gescheiterter Aktion: Fix implementiert

#### TTS & Response (P06f)
- Pre-TTS-Filter: Nicht explizit dokumentiert
- Meta-Leakage: Nicht explizit verifiziert

### Verifikation
#### Testing (P07a)
- Tests bestanden: 3763 von 3763 (nach Fix aller 47 Failures)
- Coverage: 37% → erhoeht durch 28 neue Test-Module (115 Test-Dateien aktuell)
- 2 pre-existing Failures in test_function_tools.py: Status unklar

#### Deployment (P07b)
- Docker Build: Erfolgreich (3 Dockerfiles, Multi-Arch Addon)
- Performance: Latenz nicht systematisch gemessen

### Aenderungen seit Reset #2 (2026-03-10 → 2026-03-13)
- **v1.5.11 (Build 102)**: Test Coverage Audit — 28 neue Test-Module
- **v1.5.12 (Build 103)**: Patch-Version fuer HA Update
- **v1.5.13 (Build 104)**: LLM keep_alive Fix + MindHome Auth
- **8 Log-Audit Bugs gefixt**: Auth, datetime, DB lock, LLM fallback, silence trigger, security score, WS logging, hallucination guard
- **Room-Validation**: Kommas in Raumnamen erlaubt (LLM-generiert)
- **Prompt-Konsolidierung**: Audit-Prompts finalisiert (P08a-P10 hinzugefuegt)

---

## UNFIXTE BUGS AUS DURCHLAUF #1 + #2

### ARCHITEKTUR_NOETIG (Groesserer Umbau erforderlich)

- [ ] **F-068 brain.py God Class** — brain.py:1-9906 — VERSCHLECHTERT: Von 3.429 → 9.906 Zeilen (trotz Extraktion von brain_humanizers.py, brain_callbacks.py). Empfehlung: Weitere Mixin-Extraktion (Response-Filter ~600Z, Pattern-Detection ~1.200Z)
  → Im naechsten Durchlauf: P01 + P06b priorisiert behandeln

- [ ] **F-029 Redis Graceful Degradation** — moduluebergreifend — OFFEN: Viele Module haben try/except fuer Redis, aber keine systematische Degradation mit sinnvollen Defaults (personality.py, timer_manager.py, memory.py)
  → Im naechsten Durchlauf: P06d (Haertung) priorisiert

- [ ] **Event-Bus / Priority-System** — brain.py — OFFEN: User > Routine > Proaktiv > Autonom Hierarchie nur dokumentiert, nicht implementiert. Kein Event-Bus.
  → Im naechsten Durchlauf: P01 Architektur-Analyse

- [ ] **Addon↔Assistant Koordination** — circadian vs light_engine, cover_control vs cover_config — OFFEN: Keine direkte Koordination zwischen Addon-Engines und Assistant-Modulen
  → Im naechsten Durchlauf: P03b Extended-Flows prueft

- [ ] **Memory-Stack Architektur** — 12 isolierte Memory-Systeme — OFFEN: Kein kohaerenter Memory-Stack, nur brain.py als Vermittler
  → Im naechsten Durchlauf: P02 Memory prueft

### NAECHSTER_PROMPT (Thematisch verschoben)

- [ ] **F-035 brain.py Overly Broad Exception** — brain.py process() — OFFEN: Faengt weiterhin generisches `Exception` statt spezifischer Typen. SystemExit/KeyboardInterrupt werden verschluckt.
  → Im naechsten Durchlauf: P04a Bug-Jagd

- [ ] **F-039 Zwei Settings-Endpoints** — main.py — OFFEN: PUT /api/assistant/settings und PUT /api/ui/settings koennen sich gegenseitig ueberschreiben
  → Im naechsten Durchlauf: P04a Bug-Jagd

- [ ] **F-043 Knowledge Base Chunking** — knowledge_base.py — OFFEN: 300-Zeichen-Chunks mit 100 Overlap schneiden Fakten mitten im Satz
  → Im naechsten Durchlauf: P04a Bug-Jagd

- [ ] **F-047 WebSocket Auth nur bei Connect** — main.py — OFFEN: Kein per-Message oder periodisches Re-Auth. Token-Rotation nicht durchgesetzt.
  → Im naechsten Durchlauf: P04c Security

- [ ] **OOM/VRAM-Check** — fehlt — OFFEN: Kein Check ob GPU-Speicher fuer LLM ausreicht
  → Im naechsten Durchlauf: P07b Deployment

- [ ] **SHA-256 + Salt fuer PIN-Hashing** — special_modes.py, access_control.py — OFFEN
  → Im naechsten Durchlauf: P06d Haertung

- [ ] **settings.yaml.example 14 fehlende Sektionen** — OFFEN
  → Im naechsten Durchlauf: P05 Personality

- [ ] **10 HOHE Bugs aufgeschoben** — brain.py Rekursion, sequentielle async-Calls, tieferes Refactoring
  → Im naechsten Durchlauf: P04a/P04b vollstaendig pruefen

- [ ] **16 MITTLERE Bugs aufgeschoben** — Pattern D (14 sequentielle Redis-Calls), config TOCTOU, personality Formality-Decay
  → Im naechsten Durchlauf: P04a/P04b vollstaendig pruefen

- [ ] **26 NIEDRIGE Bugs aufgeschoben** — Code-Quality, settings.yaml Sektionen, easter_eggs Trigger
  → Im naechsten Durchlauf: P04a/P04b vollstaendig pruefen

---

## REGRESSIONS-CHECK

Fuer JEDEN Fix aus den vorherigen Durchlaeufen:

| Fix | Datei | Status | Details |
|-----|-------|--------|---------|
| Prompt-Injection-Schutz (F-001) | context_builder.py | Pruefen in P04c | DANGEROUS_PATTERNS Regex |
| Conditional Commands Trust (F-002) | conditional_commands.py | Pruefen in P04c | Trust-Level Check |
| Redis-bytes-Decode (10+ Stellen) | Diverse | Pruefen in P02 | .decode() Aufrufe |
| brain_humanizers.py Extraktion | brain_humanizers.py | Intakt | 13 _humanize_* Methoden |
| brain_callbacks.py Extraktion | brain_callbacks.py | Intakt | Callback-Logik ausgelagert |
| Entity-Umlaut-Normalisierung | function_calling.py | Pruefen in P04a | _normalize_name() |
| Error-Detail-Leaks (71 Stellen) | main.py | Pruefen in P04c | Generische Error-Messages |
| _safe_init() Boot-Wrapping | brain.py | Pruefen in P01 | 30 Module gewrappt |
| _tools_cache Double-Check-Locking | function_calling.py | Pruefen in P04a | Race Condition Fix |
| Disk-Space-Check | health_monitor.py | Pruefen in P07b | Log-Rotation implementiert |
| PIN-Brute-Force Rate-Limit | special_modes.py | Pruefen in P04c | Lockout nach N Versuche |
| 327 Bug-Fixes (38397d2) | 218 Dateien | Stichproben in P04 | Bulk-Fix aller Severity-Levels |

**Ergebnis:**
- Fixes intakt (verifiziert): brain_humanizers.py, brain_callbacks.py Extraktionen
- Fixes zu pruefen: Alle anderen — Code hat sich seit Audit signifikant geaendert (133 Commits, 218 Dateien)
- Regressions-Risiko: HOCH — Bulk-Fixes (327 Bugs in einem Commit) erhoehen Regressionsrisiko

---

## DELTA-CHECKLISTE

### Offen gebliebene Punkte
- [ ] brain.py God Class (9.906 Zeilen) — P01 prueft
- [ ] Redis Graceful Degradation systemweit — P06d prueft
- [ ] Event-Bus / Priority-System — P01/P06b prueft
- [ ] Addon↔Assistant Koordination — P03b prueft
- [ ] Memory-Stack Architektur — P02 prueft
- [ ] 52 aufgeschobene Bugs (10 hoch, 16 mittel, 26 niedrig) — P04 prueft
- [ ] Test-Coverage (war 37%, nach Test-Audit hoeher) — P07a prueft
- [ ] OOM/VRAM-Check — P07b prueft
- [ ] settings.yaml.example Vollstaendigkeit — P05 prueft

### Bereiche die sich seit Durchlauf #1 geaendert haben
- [ ] **assistant/assistant/brain.py** — 9.906 Zeilen, Shutdown-Liste, _with_timeout, _states_cache Lock
- [ ] **assistant/assistant/main.py** — 71 Error-Leaks gefixt, _active_tokens Safety-Cap
- [ ] **assistant/assistant/function_calling.py** — Double-Check-Locking, tool_calls Validierung
- [ ] **33 Dateien** — `except Exception: pass` → `logger.debug()` (136 Stellen)
- [ ] **assistant/assistant/brain_humanizers.py** — NEU: 13 Methoden extrahiert
- [ ] **assistant/assistant/brain_callbacks.py** — NEU: Callback-Logik ausgelagert
- [ ] **115 Test-Dateien** — NEU: Umfangreiche Test-Suite hinzugefuegt
- [ ] **v1.5.11-v1.5.13** — keep_alive Fix, Auth Fix, Room-Validation, 8 Log-Audit Bugs
- [ ] **Addon** — Locks in event_bus, fire_water, special_modes, access_control
- [ ] **shared/** — Komplett geloescht

### Neue Risiken durch Aenderungen
- [ ] **Lock-Deadlocks** — 12+ neue Locks (brain.py, ha_client, personality, proactive, mood_detector). Verschachtelte Lock-Akquisitionen koennen Deadlocks verursachen
- [ ] **Bulk `except Exception: pass` → `logger.debug()`** an 136 Stellen — Verhaltensaenderung wenn Logging-Level anders konfiguriert
- [ ] **Double-Check-Locking** in function_calling.py — Python Memory Ordering kann subtile Probleme verursachen
- [ ] **71 generische Error-Meldungen** — Weniger Debug-Kontext fuer User
- [ ] **brain_humanizers.py Mixin** — Methoden-Resolution bei Mehrfachvererbung pruefen
- [ ] **Test-Assertions angepasst statt Code** — 11 Tests "korrigiert" durch Assertion-Aenderung — koennte echte Bugs maskieren
- [ ] **133 Commits seit Audit** — Hohe Aenderungsrate erhoeht Regressionsrisiko

---

## Durchlauf-Tracking

| Durchlauf | Datum | Bugs gefunden | Bugs behandelt | Offen | Regressions |
|---|---|---|---|---|---|
| #1 | 2026-03-10 | 225 | 173 (157 gefixt, 16 bereits OK) | 52 | N/A |
| #2 | 2026-03-10 | (Verifikation) | 8 Log-Audit + Tests | 52+ | Zu pruefen |
| #3 | 2026-03-13 | ? | ? | ? | ? |

---

## RESET ABGESCHLOSSEN — Bereit fuer Durchlauf #3

Vorheriger Durchlauf zusammengefasst: Ja (Durchlauf #1 + #2)
Unfixte Bugs uebernommen: 15 explizite + 52 aufgeschobene = 67 Bugs
Regressions-Check: 2 intakt, 10+ zu pruefen im neuen Durchlauf
Delta-Checkliste erstellt: Ja (9 offene Punkte, 10 geaenderte Bereiche, 7 neue Risiken)
Alle Kontext-Bloecke verworfen: Ja

→ Starte jetzt mit PROMPT_00_OVERVIEW.md

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
ZUSAMMENFASSUNG: Durchlauf #1 fand 225 Bugs (157 gefixt, 52 aufgeschoben).
  Seit dem letzten Reset: 133 Commits, v1.5.11-v1.5.13, massive Test-Erweiterung (115 Dateien),
  8 Log-Audit-Bugs gefixt, Prompt-Struktur finalisiert (P08a-P10).
  brain.py wuchs auf 9.906 Zeilen (trotz Mixin-Extraktion).
UNFIXTE BUGS: 67 total. Top 3 kritischste:
  1. brain.py God Class (9.906 Zeilen — verschlechtert)
  2. Redis Graceful Degradation (systemweit, keine systematische Loesung)
  3. Event-Bus / Priority-System (nur dokumentiert, nicht implementiert)
REGRESSIONS: 2 Extraktionen intakt, 10+ Fixes zu pruefen (hohe Aenderungsrate)
DELTA: 133 Commits, 218 Dateien, v1.5.11→v1.5.13, 115 Test-Dateien hinzugefuegt
NAECHSTER SCHRITT: Starte PROMPT_00_OVERVIEW.md
=====================================
```
