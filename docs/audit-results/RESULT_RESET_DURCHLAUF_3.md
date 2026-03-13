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

- [ ] **F-068 brain.py God Class** — brain.py:1-9906 — VERSCHLECHTERT (+188%): Von 3.429 → 9.906 Zeilen. brain_humanizers.py (502Z) und brain_callbacks.py (29Z) extrahiert, aber kein brain_core.py, brain_proactive.py oder brain_tools.py. Hunderte Methoden fuer Autonomy, Speaker Recognition, Activity, Alarms, Timers, Reminders, Feedback, Response Quality, Emotions, Humor, Sarkasmus — alles in einer Datei.
  → Im naechsten Durchlauf: P01 + P06b priorisiert behandeln

- [ ] **F-029 Redis Graceful Degradation** — moduluebergreifend — TEILWEISE GEFIXT: Module haben try/except und pruefen `if not self.redis`, aber Degradation ist nicht "graceful" — sie geben leere Listen/Defaults zurueck statt alternative Speicher-Strategien zu nutzen. memory.py setzt self.redis=None bei Fehler, personality.py hat 50+ try/except-Bloecke. Kein alternativer State-Storage als Fallback.
  → Im naechsten Durchlauf: P06d (Haertung) priorisiert

- [ ] **Event-Bus / Priority-System** — brain.py — OFFEN: User > Routine > Proaktiv > Autonom Hierarchie nur dokumentiert, nicht implementiert. Kein Event-Bus.
  → Im naechsten Durchlauf: P01 Architektur-Analyse

- [ ] **Addon↔Assistant Koordination** — circadian vs light_engine, cover_control vs cover_config — OFFEN: Keine direkte Koordination zwischen Addon-Engines und Assistant-Modulen
  → Im naechsten Durchlauf: P03b Extended-Flows prueft

- [ ] **Memory-Stack Architektur** — 12 isolierte Memory-Systeme — OFFEN: Kein kohaerenter Memory-Stack, nur brain.py als Vermittler
  → Im naechsten Durchlauf: P02 Memory prueft

### NAECHSTER_PROMPT (Thematisch verschoben)

- [ ] **F-035 brain.py Overly Broad Exception** — brain.py — OFFEN: 21+ bare `except Exception` Handler (Zeilen 144, 494, 531, 543, 684, 783, 855, 991, 1070, 1095, 1345, 1360, 1547, 1644, 1659, 1707, 1753, 1801, 1884, 1937 etc.). SystemExit/KeyboardInterrupt werden verschluckt.
  → Im naechsten Durchlauf: P04a Bug-Jagd

- [ ] **F-039 Zwei Settings-Endpoints** — main.py — OFFEN: PUT /api/assistant/settings (Zeile 1136, nur autonomy_level) vs PUT /api/ui/settings (Zeile 3804, deep_merge in YAML) vs PUT /api/ui/presence/settings (Zeile 5351). Kein Locking, kein Version-Check, Race Conditions moeglich.
  → Im naechsten Durchlauf: P04a Bug-Jagd

- [ ] **F-043 Knowledge Base Chunking** — knowledge_base.py — TEILWEISE GEFIXT: Chunk-Groesse verbessert (300→500 Zeichen, Overlap 100→50, konfigurierbar via settings.yaml). ABER: _split_text_into_chunks() nutzt weiterhin einfaches Zeichen-basiertes Splitting ohne Satz-Erkennung. Nur memory.py episodic hat sentence-aware Splitting (`re.split(r'(?<=[.!?])\s+', segment)`).
  → Im naechsten Durchlauf: P04a Bug-Jagd

- [ ] **F-047 WebSocket Auth nur bei Connect** — main.py — TEILWEISE GEFIXT: Auth weiterhin NUR beim Handshake (Zeile 1853-1867). ABER: Neue Safeguards hinzugefuegt — Rate-Limiting (30 msgs/10s), Inactivity-Timeout (5 Min), Keep-alive Ping/Pong (25s). Kompromittiertes Token gilt fuer gesamte Session.
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
- Fixes intakt (verifiziert): brain_humanizers.py (502Z), brain_callbacks.py (29Z) Extraktionen
- Teilweise gefixt: F-029 (Redis try/except vorhanden, aber keine graceful Degradation), F-043 (Chunks 300→500, aber kein Sentence-Splitting), F-047 (Rate-Limiting + Timeout hinzugefuegt, aber kein per-Message Auth)
- Weiterhin offen: F-035 (21+ bare `except Exception`), F-039 (3 Settings-Endpoints ohne Sync), F-068 (9906 Zeilen, +188%)
- Fixes zu pruefen: Alle Code-Fixes — 133 Commits, 218 Dateien seit Audit
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

| Durchlauf | Datum | Phase | Bugs gefunden | Bugs behandelt | Offen | Regressions |
|---|---|---|---|---|---|---|
| #1 | 2026-03-10 | Komplett (P01-P10) | 225 | 173 (157 gefixt, 16 bereits OK) | 52 | N/A |
| #2 | 2026-03-10 | Komplett (Verifikation) | — | 8 Log-Audit + Tests | 52+ | Zu pruefen |
| #3 | 2026-03-13 | **Analyse abgeschlossen, Fix-Phase ausstehend** | 232 NEUE (P04a: 92, P04b: 92, P04c: 48) | P02: 11 Memory-Fixes, Fix 3: Memory-Keywords 25→32 | ~536 gesamt (131 P4a + 299 P4b + 106 P4c) | 0 Regressionen bisher |

---

## DURCHLAUF #3 — FORTSCHRITT (Stand 2026-03-13)

### Status-Uebersicht

| Phase | Prompt | Status DL#3 | Ergebnis |
|---|---|---|---|
| Analyse | P01 (Architektur) | ABGESCHLOSSEN | Vollstaendig neu analysiert, DL#3-Header in RESULT_01 |
| Analyse | P02 (Memory) | ABGESCHLOSSEN + CODE-FIXES | 11 Code-Fixes implementiert (Kern des DL#3) |
| Analyse | P03a (Flows Core) | ABGESCHLOSSEN | Verifiziert nach P02-Fixes, proactive.start() Regression aufgeloest |
| Analyse | P03b (Flows Extended) | ABGESCHLOSSEN | Verifiziert nach P02-Fixes |
| Analyse | P04a (Bugs Core) | ABGESCHLOSSEN (NEU) | 92 neue Bugs (4 KRIT, 22 HOCH, 42 MITTEL, 15 NIEDRIG) |
| Analyse | P04b (Bugs Extended) | ABGESCHLOSSEN (NEU) | 92 neue Bugs (5 KRIT, 18 HOCH, 41 MITTEL, 28 NIEDRIG) |
| Analyse | P04c (Bugs Addon) | ABGESCHLOSSEN (NEU) | 48 neue Findings (N1-N38, S1-S4, P1-P6) |
| Analyse | P05 (Personality) | ABGESCHLOSSEN | Verifiziert, P02 verbessert Memory-Kontext indirekt |
| Fix | P06a (Stabilisierung) | **AUSSTEHEND** | Kritische Bugs + Memory aus P04a-P04c fixen |
| Fix | P06b (Architektur) | **AUSSTEHEND** | Konflikte aufloesen, Flows reparieren |
| Fix | P06c (Charakter) | **AUSSTEHEND** | Persoenlichkeit harmonisieren |
| Fix | P06d (Haertung) | **AUSSTEHEND** | Security + Resilience |
| Fix | P06e (Geraetesteuerung) | **AUSSTEHEND** | Tool-Calling + System-Prompt |
| Fix | P06f (TTS/Response) | **AUSSTEHEND** | speak-Filter + Meta-Leakage |
| Verifikation | P07a (Testing) | **AUSSTEHEND** | Tests + Coverage |
| Verifikation | P07b (Deployment) | **AUSSTEHEND** | Docker + Performance |
| Qualitaet | P08a (Codequalitaet) | **AUSSTEHEND** | Docs + Deps + CI/CD |
| Qualitaet | P08b (Betrieb) | **AUSSTEHEND** | Multi-User + Monitoring |
| Abschluss | P09a (Fix Codequalitaet) | **AUSSTEHEND** | P08a Findings fixen |
| Abschluss | P09b (Fix Betrieb) | **AUSSTEHEND** | P08b Findings fixen |
| Abschluss | P10 (Final Validation) | **AUSSTEHEND** | Zero-Bug Declaration |

### Abgeschlossene Prompts — Details:

**P01 (Architektur):** Vollstaendig neu analysiert. DL#3-Header in RESULT_01_ARCHITEKTUR.md geschrieben.

**P02 (Memory): 11 Code-Fixes implementiert — Kern des DL#3**
- Confidence 0.6→0.4, Relevance 0.3→0.2, Limit 3→10
- conv_memory_ext Priority 3→1 (immer im System-Prompt)
- "ERFINDE KEINE Erinnerungen" Halluzinations-Schutz
- proactive.start() in _safe_init() gewrappt
- + 6 weitere Fixes (siehe RESULT_02)

**P03a/P03b (Flows):** Verifiziert nach P02-Fixes. proactive.start() REGRESSION aufgeloest.

**P04a (Bugs Core): VOLLSTAENDIG NEU AUSGEFUEHRT** — 5 parallele Agents, alle 26 Module gelesen
- 92 NEUE Bugs (4 KRITISCH, 22 HOCH, 42 MITTEL, 15 NIEDRIG)
- Gesamt offen: ~131 Bugs (inkl. DL#2-Altlasten)
- Kritischste: DL3-ME1 (Prompt-Injection Memory), DL3-AI1 (action_planner Reihenfolge), DL3-AI2/AI3 (pre_classifier Frage-Erkennung)

**P04b (Bugs Extended): VOLLSTAENDIG NEU AUSGEFUEHRT** — 7 parallele Agents, alle 63 Module gelesen
- 92 NEUE Bugs (5 KRITISCH, 18 HOCH, 41 MITTEL, 28 NIEDRIG)
- Gesamt offen: 299 Bugs (207 DL#2 + 92 DL#3 neu)
- Kritischste: DL3-H01/H02 (ha_client PUT/DELETE ohne Auth), DL3-D01/M01 (OCR Pfad-Validierung blockiert Uploads)

**P04c (Bugs Addon): VOLLSTAENDIG NEU AUSGEFUEHRT** — 6 parallele Agents
- 48 NEUE Findings (N1-N38, S1-S4, P1-P6)
- Gesamt: ~106 offene Bugs

**P05 (Personality):** Verifiziert. P02 Memory-Reparatur verbessert Memory-Kontext indirekt.

**Zusaetzlicher Code-Fix:** Memory-Intent-Keywords erweitert (25→32) — Commit 52a504f

**P06a-P09:** Historische Fix-Logs aus DL#2 mit DL#3-Notes versehen (keine Aenderungen noetig, Fixes bleiben gueltig).

### Bug-Zusammenfassung DL#3 (Analyse-Phase):

| Quelle | KRITISCH | HOCH | MITTEL | NIEDRIG | Gesamt |
|---|---|---|---|---|---|
| P04a (Core) — NEU | 4 | 22 | 42 | 15 | 92 |
| P04b (Extended) — NEU | 5 | 18 | 41 | 28 | 92 |
| P04c (Addon) — NEU | — | — | — | — | 48 (N38+S4+P6) |
| DL#2 Altlasten | — | 10 | 16 | 26 | 52 |
| **Gesamt offen** | **9+** | **50+** | **99+** | **69+** | **~536** |

### Kritischste offene Bugs (Top 10):

1. DL3-ME1 — Prompt-Injection ueber Memory (memory_extractor.py)
2. DL3-H01 — ha_client PUT ohne Auth-Header
3. DL3-H02 — ha_client DELETE ohne Auth-Header
4. DL3-AI1 — action_planner Reihenfolge-Bug
5. DL3-AI2 — pre_classifier Frage-Erkennung falsch
6. DL3-AI3 — pre_classifier false positives
7. DL3-D01 — OCR Pfad-Validierung blockiert Uploads
8. DL3-M01 — OCR Upload-Pfad Konflikt
9. F-068 — brain.py God Class (9.906 Zeilen — verschlechtert seit DL#1)
10. F-029 — Redis Graceful Degradation (systemweit)

### Naechste Schritte (Fix-Phase):

Die **gesamte Analyse-Phase (P01-P05) ist abgeschlossen**. Als naechstes startet die **Fix-Phase**:

1. **P06a (Stabilisierung)** — Alle KRITISCHEN Bugs aus P04a-P04c fixen + Memory verifizieren
2. **P06b (Architektur)** — brain.py God-Class, Konflikte aufloesen
3. **P06c (Charakter)** — Persoenlichkeits-Inkonsistenzen
4. **P06d (Haertung)** — Security-Bugs (DL3-H01/H02, DL3-ME1), Resilience
5. **P06e (Geraetesteuerung)** — Tool-Calling Fixes
6. **P06f (TTS/Response)** — speak-Filter, Meta-Leakage
7. **P07a-P07b** — Testing + Deployment Verifikation
8. **P08a-P10** — Codequalitaet, Betrieb, Final Validation

→ **Naechster Prompt: PROMPT_06a_STABILISIERUNG.md**

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
ZUSAMMENFASSUNG DL#3: Analyse-Phase KOMPLETT (P01-P05).
  P02: 11 Memory-Fixes implementiert + Memory-Keywords 25→32.
  P04a/P04b/P04c: Vollstaendig neu ausgefuehrt mit parallelen Agents.
  232 NEUE Bugs gefunden (9 KRIT, 40 HOCH, 83 MITTEL, 43 NIEDRIG + 48 Addon).
  Gesamt offen: ~536 Bugs (inkl. 52 DL#2-Altlasten).
KRITISCHSTE BUGS:
  1. DL3-ME1 Prompt-Injection Memory (memory_extractor.py)
  2. DL3-H01/H02 ha_client PUT/DELETE ohne Auth
  3. DL3-AI1 action_planner Reihenfolge
  4. F-068 brain.py God Class (9.906 Zeilen)
  5. F-029 Redis Graceful Degradation (systemweit)
CODE-FIXES IN DL#3: P02 (11 Memory-Fixes), Fix 3 (Keywords 25→32)
REGRESSIONS: 0 bisher. proactive.start() Regression aus P02 aufgeloest.
NAECHSTER SCHRITT: Starte PROMPT_06a_STABILISIERUNG.md (Fix-Phase beginnt)
=====================================
```
