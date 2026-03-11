# Audit-Ergebnis: Prompt 4b — Systematische Bug-Jagd (Extended-Module, Prioritaet 5-9)

**Durchlauf**: #2 (nach Fixes aus P6a-P8)
**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: 63 Extended-Module in 9 Batches, 13 Fehlerklassen
**Methode**: 9 parallele Audit-Agenten, jedes Modul komplett gelesen
**Vergleichsbasis**: DL#1 (kein separater DL#1 fuer Extended-Module — Erstaudit in DL#2)

---

## DL#1 vs DL#2 Vergleich

### Hinweis

Die Extended-Module (Prioritaet 5-9) wurden erstmals in DL#2 systematisch auditiert.
Es gibt keinen DL#1-Vergleich fuer diese 221 Bugs — sie sind alle **NEU identifiziert**.
Die DL#1-Zeilen-Spalte entfaellt daher. Status-Tracking beginnt mit DL#2 als Baseline.

```
DL#2 Erstaudit: 221 Bugs (KRITISCH 1, HOCH 36, MITTEL 97, NIEDRIG 85, INFO 2)
Alle Bugs sind NEU — keine DL#1-Vergleichsdaten vorhanden.

Systemische Muster:
  Sync I/O in async:          28 Vorkommen (dominantes HIGH-Pattern)
  Stille Fehler (except:pass): 38 Vorkommen
  Performance N+1:             25 Vorkommen
  Race Conditions:             18 Vorkommen
  Am staerksten betroffen:     proactive.py (16 Bugs), cooking_assistant.py (13 Bugs)
```

---

## Gesamt-Statistik

```
Gesamt: 221 Bugs (Prioritaet 5-9)
  KRITISCH: 1
  HOCH:     36
  MITTEL:   97
  NIEDRIG:  85
  INFO:     2

Haeufigste Fehlerklasse: Stille Fehler / except:pass (38 Vorkommen)
Zweithaeufigste: Sync I/O in async (28 Vorkommen)
Dritthaeufigstes: Performance N+1 / sequentiell (25 Vorkommen)
Am staerksten betroffenes Modul: proactive.py (16 Bugs)
Zweitstaerkstes: cooking_assistant.py (13 Bugs)
```

### Verteilung nach Fehlerklasse

| # | Fehlerklasse | Anzahl | Kritischste offene |
|---|---|---|---|
| 1 | Async-Fehler (sync I/O in async) | 28 | workshop_library.py ChromaDB+Embeddings, knowledge_base.py, self_optimization.py YAML |
| 2 | Stille Fehler (except: pass/debug) | 38 | proactive.py 4x `except: pass`, multi_room_audio.py 3x silent return |
| 3 | Race Conditions | 18 | config.py _active_person, proactive.py _batch_flushing, feedback.py _pending |
| 4 | None-Fehler | 15 | cooking_assistant.py 7x session-None, proactive.py 5x brain.X ohne Check |
| 5 | Init-Fehler | 3 | proactive_planner.py redis=None vor initialize() |
| 6 | API-Fehler (Timeouts) | 5 | threat_assessment.py get_states() ohne Timeout, cooking_assistant.py ollama.chat() |
| 7 | Daten-Fehler (bytes/str) | 8 | outcome_tracker.py hgetall bytes-Keys, repair_planner.py arm_pick_tool |
| 8 | Config-Fehler | 2 | autonomy.py Class-Variable statt Instance |
| 9 | Memory Leaks | 10 | cooking_assistant.py Timer-Tasks, proactive.py _batch_queue |
| 10 | Logik-Fehler | 12 | proactive.py event_handlers ueberschrieben (KRITISCH), ha_client.py Retry nur bei Exception |
| 11 | Security | 7 | repair_planner.py 4x unvalidierte Redis-Keys, recipe_store.py MD5 |
| 12 | Resilience | 10 | wellness_advisor.py 7x Redis ohne _safe_redis, light_engine.py Redis ohne Wrapper |
| 13 | Performance (N+1/sequentiell) | 25 | inventory.py 4x N+1, energy_optimizer.py 14 seq. Redis, repair_planner.py 3x N+1 |

---

## Bug-Report: Batch 5 — Proaktive Systeme (28 Bugs: 1 KRIT, 6 HOCH, 16 MITTEL, 5 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 1 | KRITISCH | proactive.py | 98,146 | Logik (10) | `event_handlers` in Z.98 mit dynamischen Appliance-Handlern befuellt, dann in Z.146 komplett ueberschrieben. Alle YAML-konfigurierten Handler gehen verloren. | Hardcoded Dict als Basis, dynamische Handler DANACH einfuegen |
| 2 | HOCH | proactive.py | 2620-2622 | Race (3) | `_batch_flushing` Boolean ohne Lock. Zwei Codepfade rufen `_flush_batch()` auf (Batch-Loop + Early-Flush aus `_notify`). | `asyncio.Lock` oder `_state_lock` mitnutzen |
| 3 | HOCH | proactive.py | 1660-1661 | Stille (2) | `except Exception: pass` in `_accumulate_event` verschluckt alle Fehler | `logger.debug()` statt `pass` |
| 4 | HOCH | proactive.py | 1688-1689 | Stille (2) | `except Exception: pass` im Mood-Check | `logger.debug()` statt `pass` |
| 5 | HOCH | proactive.py | 1829-1830 | Stille (2) | `except Exception: pass` bei Narration | `logger.debug()` statt `pass` |
| 6 | HOCH | self_automation.py | 36-39 | Async (1) | `_load_templates()` synchrones File-I/O beim Import auf Modul-Ebene | `aiofiles` oder lazy load in `initialize()` |
| 7 | HOCH | proactive.py | 1298-1299 | Stille (2) | `except Exception: return` ohne Logging in `_check_personal_dates` | Logger hinzufuegen |
| 8 | MITTEL | proactive.py | 1672 | None (4) | `self.brain.autonomy.level` ohne `getattr` Schutz | `getattr(self.brain.autonomy, "level", 2)` |
| 9 | MITTEL | proactive.py | 1679 | None (4) | `self.brain.mood.get_current_mood()` ohne Null-Check | `getattr(self.brain, "mood", None)` |
| 10 | MITTEL | proactive.py | 1693 | None (4) | `self.brain.feedback` ohne `getattr` | `getattr(self.brain, "feedback", None)` |
| 11 | MITTEL | proactive.py | 1570 | None (4) | `self.brain.autonomy.level` in `_check_music_follow` ohne Check | `getattr` Schutz |
| 12 | MITTEL | proactive.py | 1055-1056 | None (4) | `self.brain.memory.redis` direkt ohne Null-Check | Doppeltes `getattr` |
| 13 | MITTEL | protocol_engine.py | 193-194 | Stille (2) | `except Exception: pass` beim Redis-Update der Undo-Steps | `logger.warning()` |
| 14 | MITTEL | routine_engine.py | 1245-1246 | Stille (2) | `except Exception:` beim Personality-Prompt ohne Logging | `logger.debug()` |
| 15 | MITTEL | anticipation.py | 741-762 | Shutdown (12) | `_check_loop` startet vor `set_notify_callback()` — Suggestions gehen verloren | Callback vor `initialize()` setzen |
| 16 | MITTEL | spontaneous_observer.py | 97-128 | Shutdown (12) | Gleicher Init-Race wie anticipation.py | Callback als Parameter in `initialize()` |
| 17 | MITTEL | proactive.py | 261-263 | Shutdown (12) | Task-Variablen in `start()` statt `__init__` deklariert | In `__init__` verschieben |
| 18 | MITTEL | self_automation.py | 100 | Race (3) | `_daily_count`/`_daily_reset` ohne Lock | Lock oder Redis-basierter Counter |
| 19 | MITTEL | proactive.py | 1724-1725 | Leak (9) | `_batch_queue` waechst auf 1000 Items bei Flush-Fehler | TTL auf Items oder Overflow-Handling |
| 20 | MITTEL | proactive_planner.py | 40 | Init (5) | `self.redis = None` — Planung ohne Cooldown-Schutz moeglich | Early-return wenn `not self.redis` |
| 21 | MITTEL | protocol_engine.py | 281-304 | Perf (13) | N+1 Redis in `list_protocols()` | Pipeline verwenden |
| 22 | MITTEL | conditional_commands.py | 160-219 | Perf (13) | N+1 Redis in `check_event()` pro Conditional | Pipeline verwenden |
| 23 | MITTEL | spontaneous_observer.py | 309-348 | Perf (13) | Gleiche Redis-Liste doppelt geladen | Einmal laden und durchreichen |
| 24 | NIEDRIG | proactive.py | 2148-2157 | Dead Code | `_get_person_title()` dupliziert `config.get_person_title()` | Instance-Methode entfernen |
| 25 | NIEDRIG | proactive.py | 1351 | Dead Code | Redundanter `from datetime import datetime` Import | Entfernen |
| 26 | NIEDRIG | routine_engine.py | 1532 | Resilience (12) | `while True:` statt `while self._running:` | Running-Flag verwenden |
| 27 | NIEDRIG | autonomy.py | 342 | Config (8) | `_redis = None` als Class-Variable statt Instance | In `__init__` verschieben |
| 28 | NIEDRIG | self_automation.py | 109 | Leak (9) | `_audit_log` deque: bei Redis-Ausfall gehen Audit-Eintraege verloren | Warning-Log bei Redis-Ausfall |

---

## Bug-Report: Batch 6 — HA-Integration & Covers (27 Bugs: 3 HOCH, 14 MITTEL, 10 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 29 | HOCH | ha_client.py | 72-73 | Resilience (12) | `close()` nicht thread-safe: `_session` ohne `_session_lock` | `async with self._session_lock:` in `close()` |
| 30 | HOCH | ha_client.py | 367 | Race (3) | `mindhome_put()`: Session VOR Retry-Loop geholt, bei Close stale | Session pro Retry-Versuch holen |
| 31 | HOCH | ha_client.py | 392 | Race (3) | `mindhome_delete()`: Identisches Problem wie #30 | Session in Loop verschieben |
| 32 | MITTEL | ha_client.py | 377-378 | Logik (10) | `mindhome_put()`: Non-200 sofort `return None` statt Retry | Bei 5xx retrien, bei 4xx abbrechen |
| 33 | MITTEL | ha_client.py | 399-400 | Logik (10) | `mindhome_delete()`: Identisch wie #32 | Differenzieren |
| 34 | MITTEL | ha_client.py | 291 | API (6) | `mindhome_post()`: `timeout=0` wird als falsy behandelt — kein Timeout | `if timeout is not None` pruefen |
| 35 | MITTEL | light_engine.py | 885 | Resilience (12) | `redis.get()` OHNE `_safe_redis()` Wrapper | `_safe_redis()` verwenden |
| 36 | MITTEL | light_engine.py | 187 | Init (5) | Zugriff auf private Methode `FunctionExecutor._get_adaptive_brightness()` | In shared utility extrahieren |
| 37 | MITTEL | light_engine.py | 291 | Race (3) | `_check_dusk_auto_on()` TOCTOU bei Redis-Flag | Atomare SET-NX verwenden |
| 38 | MITTEL | light_engine.py | 418 | Perf (13) | `redis.keys()` O(N) ueber ALLE Keys | `SCAN` verwenden |
| 39 | MITTEL | ha_client.py | 80-92 | Race (3) | `_states_lock` waehrend HTTP-Call gehalten — blockiert alle Caller | Lock nur fuer Cache-Read/Write |
| 40 | MITTEL | cover_config.py | 35-54 | Race (3) | Alle read-modify-write Ops nicht atomar | File-Locking oder Redis/SQLite |
| 41 | MITTEL | cover_config.py | 39 | Async (1) | Alle File-I/O sync in async-Kontext | `aiofiles` oder `asyncio.to_thread()` |
| 42 | MITTEL | conditional_commands.py | 153 | Data (7) | `smembers()` Set waehrend Iteration durch `srem()` modifiziert | Lokale Kopie vor Iteration |
| 43 | MITTEL | conditional_commands.py | 165 | Resilience (12) | `redis.get(key)` in Loop ohne try/except | try/except um Redis-Zugriffe |
| 44 | MITTEL | conditional_commands.py | 294 | Resilience (12) | `list_conditionals()` Redis ohne try/except | try/except hinzufuegen |
| 45 | NIEDRIG | light_engine.py | 530 | Perf (13) | `redis.keys()` + N+1 TTL-Abfragen | `SCAN` + Pipeline |
| 46 | NIEDRIG | light_engine.py | 362-376 | Perf (13) | Sequentielle `get_state()` pro Licht | `asyncio.gather()` |
| 47 | NIEDRIG | cover_config.py | 212-214 | Security (11) | `update_cover_schedule()` validiert Position nicht | `max(0, min(100, position))` |
| 48 | NIEDRIG | camera_manager.py | 69 | Data (7) | Snapshot-Bytes im Return-Dict (nicht JSON-serialisierbar) | base64-Encoding |
| 49 | NIEDRIG | camera_manager.py | 33-37 | Config (8) | Config einmalig im `__init__` — kein Reload | Live-Config-Read oder Reload |
| 50 | NIEDRIG | protocol_engine.py | 124 | Data (7) | `datetime.now()` ohne Timezone | `datetime.now(timezone.utc)` |
| 51 | NIEDRIG | protocol_engine.py | 199 | Data (7) | Gleicher Fehler wie #50 | `datetime.now(timezone.utc)` |
| 52 | NIEDRIG | protocol_engine.py | 270 | Stille (2) | Undo-Fehler nur `logger.debug()`, Antwort meldet Erfolg | Fehler zaehlen und kommunizieren |
| 53 | NIEDRIG | protocol_engine.py | 131 | Leak (9) | Protokolle in Redis ohne TTL | TTL setzen (z.B. 90 Tage) |
| 54 | NIEDRIG | climate_model.py | 279 | Logik (10) | Regex matcht Zahlen die keine Temperaturen sind | Kontext-Regex verbessern |
| 55 | NIEDRIG | ha_client.py | 6 | API (6) | `mindhome_post()` Timeout-Handling bei `timeout=None` | Explizite Pruefung |

---

## Bug-Report: Batch 7 — Audio (16 Bugs: 3 HOCH, 7 MITTEL, 6 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 56 | HOCH | multi_room_audio.py | 484-496 | Perf (13) | `_get_speaker_names()` sequentielle `get_state()` pro Speaker — N+1 HTTP | `asyncio.gather()` oder gecachte States |
| 57 | HOCH | multi_room_audio.py | 416-438 | Perf (13) | `_build_group_status()` identisches N+1 Pattern | `asyncio.gather()` |
| 58 | HOCH | speaker_recognition.py | 722-771 | Perf (13) | `identify_by_embedding()` laedt Embeddings einzeln aus Redis — N+1 | `redis.mget()` verwenden |
| 59 | MITTEL | multi_room_audio.py | 174 | Stille (2) | `except Exception:` ohne Logging in `list_groups()` | `logger.warning()` |
| 60 | MITTEL | multi_room_audio.py | 481-482 | Stille (2) | `except Exception:` ohne Logging in `_get_group()` | `logger.debug()` |
| 61 | MITTEL | multi_room_audio.py | 437-438 | Stille (2) | `except Exception:` ohne Logging in `_build_group_status()` | `logger.debug()` |
| 62 | MITTEL | speaker_recognition.py | 358-368 | Perf (13) | `_get_persons_home()` Full-State-Dump bis 2x pro identify() | States einmal abrufen und durchreichen |
| 63 | MITTEL | speaker_recognition.py | 150-153 | Race (3) | `_profiles` Dict ohne Lock bei concurrent enroll()/identify() | Lock auf gesamte `_profiles`-Mutation |
| 64 | MITTEL | sound_manager.py | 95-96 | None (4) | `int(vol_cfg.get("evening_start", 22))` ohne try/except | `_safe_int` Pattern verwenden |
| 65 | MITTEL | ambient_audio.py | 380-411 | Resilience (12) | `_poll_loop` kein Backoff bei HA-Fehler — Logspam | Exponentielles Backoff |
| 66 | NIEDRIG | multi_room_audio.py | 101-102 | Stille (2) | `create_group()` loggt Fehler nicht | `logger.warning()` vor Return |
| 67 | NIEDRIG | speaker_recognition.py | 151 | Race (3) | `_last_speaker` ohne Lock bei parallelen identify()-Aufrufen | Atomarer Zugriff |
| 68 | NIEDRIG | sound_manager.py | 575 | Logik (10) | `success = False` Init semantisch verwirrend | Klarere Variable-Semantik |
| 69 | NIEDRIG | ambient_audio.py | 199-208 | Resilience (12) | `stop()` raumt `_background_tasks` nicht auf | Tasks in `stop()` canceln |
| 70 | NIEDRIG | tts_enhancer.py | 378 | Stille (2) | `except Exception:` in `_is_auto_night_whisper()` | `logger.debug()` |
| 71 | NIEDRIG | speaker_recognition.py | 904 | Stille (2) | `except Exception:` in `resolve_fallback_answer()` | `logger.debug()` |

---

## Bug-Report: Batch 8 — Intelligence (24 Bugs: 4 HOCH, 12 MITTEL, 8 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 72 | HOCH | feedback.py | 345-349 | Logik (10) | Double-decode: Z.345-346 decoded bytes, Z.348 versucht erneut `.decode()` auf String | Z.348 Dead Code entfernen |
| 73 | HOCH | self_optimization.py | 370-381 | Async (1) | Synchrone File-I/O (`open()`, `yaml.safe_load/dump`) in async `_apply_parameter()` | `asyncio.to_thread()` |
| 74 | HOCH | self_optimization.py | 664-686 | Async (1) | Synchrone File-I/O in async `add_banned_phrase()` | `asyncio.to_thread()` |
| 75 | HOCH | learning_observer.py | 147-148 | Stille (2) | `except Exception: logger.debug()` in Hauptverarbeitungslogik | `logger.warning()` |
| 76 | MITTEL | learning_transfer.py | 92-93 | Stille (2) | Preferences laden fehlgeschlagen — nur `logger.debug()` | `logger.warning()` |
| 77 | MITTEL | learning_transfer.py | 105-106 | Stille (2) | Preferences speichern fehlgeschlagen — nur `logger.debug()` | `logger.warning()` |
| 78 | MITTEL | insight_engine.py | 701 | Data (7) | `fromisoformat(away_since)` ohne Typ-Absicherung | Validierung vor Parse |
| 79 | MITTEL | insight_engine.py | 448-449 | Stille (2) | `except Exception: logger.debug()` in `_run_all_checks()` | `logger.warning()` |
| 80 | MITTEL | self_optimization.py | 421-423 | Stille (2) | `except Exception:` OHNE Logging in `_get_feedback_stats()` | Logger hinzufuegen |
| 81 | MITTEL | self_optimization.py | 593-594 | Stille (2) | `except Exception:` ohne Logging in `get_character_break_stats()` | Logger hinzufuegen |
| 82 | MITTEL | response_quality.py | 172-177 | Data (7) | `int(v)` Cast auf Float-Strings schlaegt fehl | `float(v)` verwenden |
| 83 | MITTEL | feedback.py | 265-268 | Perf (13) | N+1 Redis in `get_stats()` — 4N Roundtrips pro Event-Type | Pipeline oder `mget` |
| 84 | MITTEL | feedback.py | 296-313 | Perf (13) | N+1 Redis in `get_all_scores()` — einzelnes `get()` pro Key | `mget()` nach SCAN |
| 85 | MITTEL | insight_engine.py | 382-399 | Perf (13) | Sequentielle Kalender-Abfragen pro Calendar-Entity | `asyncio.gather()` |
| 86 | MITTEL | learning_transfer.py | 73-74 | Race (3) | `_preferences`/`_pending_transfers` ohne Lock | `asyncio.Lock()` |
| 87 | MITTEL | self_optimization.py | 66 | Race (3) | `_pending_proposals` ohne Lock bei concurrent API-Aufrufen | `asyncio.Lock()` |
| 88 | NIEDRIG | feedback.py | 52 | Leak (9) | `_pending: dict` ohne Groessenlimit | Maximum-Groesse erzwingen |
| 89 | NIEDRIG | insight_engine.py | 620-678 | Resilience (12) | 8 sequentielle Redis-Calls in `_check_energy_anomaly()` | Pipeline mit `mget()` |
| 90 | NIEDRIG | self_optimization.py | 384 | Init (5) | `load_yaml_config()` ohne Validierung nach korruptem Write | Validierung vor `clear()+update()` |
| 91 | NIEDRIG | self_report.py | 50 | Race (3) | `_last_report_day` ohne Lock — doppelte Reports | `asyncio.Lock()` oder Redis-Check |
| 92 | NIEDRIG | response_quality.py | 39-42 | Race (3) | Instance-Variablen ohne Lock bei Concurrent Access | Formal ein Risk |
| 93 | NIEDRIG | insight_engine.py | 237-238 | Resilience (12) | Error-Loop ohne Backoff erzeugt Logspam | Exponentielles Backoff |
| 94 | NIEDRIG | self_optimization.py | 331-348 | Security (11) | LLM-Ausgabe in `json.loads()` — grosses JSON-Array moeglich | Sofortiges Limit nach Parse |
| 95 | NIEDRIG | self_report.py | 122 | Perf (13) | Redundantes `expire` bei jedem Report | Nur beim ersten `lpush` setzen |

---

## Bug-Report: Batch 9 — Resilience & Tracking (17 Bugs: 6 MITTEL, 11 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 96 | MITTEL | circuit_breaker.py | 44-56 | Race (3) | State-Variablen ohne Lock bei concurrent access | `asyncio.Lock` einfuehren |
| 97 | MITTEL | outcome_tracker.py | 208-209 | Data (7) | `hgetall` gibt bytes-Keys zurueck — downstream `get("total")` findet `b"total"` nicht | Keys explizit decodieren |
| 98 | MITTEL | outcome_tracker.py | 155-156 | Data (7) | `redis.get()` gibt bytes zurueck — wird als String verwendet | `.decode()` vor Verwendung |
| 99 | MITTEL | intent_tracker.py | 297-303 | Perf (13) | N+1 Redis in `get_active_intents()` — einzelne `hgetall` pro Intent | Pipeline verwenden |
| 100 | MITTEL | adaptive_thresholds.py | 232-253 | Race (3) | `_set_runtime_value()` mutiert globales `yaml_config` ohne Lock | `asyncio.Lock` oder Copy-on-Write |
| 101 | MITTEL | intent_tracker.py | 396-424 | Logik (10) | `_reminder_loop()` schlaeft ZUERST — ueberfaellige Intents erst nach 60 Min | Zuerst pruefen, dann schlafen |
| 102 | NIEDRIG | circuit_breaker.py | 50-57 | Logik (10) | `state` Property hat Seiteneffekte — mutiert `_state` | Transition in dedizierte Methode |
| 103 | NIEDRIG | outcome_tracker.py | 57,127 | Race (3) | `_pending_count` ohne Lock | Akzeptabel in asyncio |
| 104 | NIEDRIG | intent_tracker.py | 300 | Data (7) | `intent_id` aus `smembers` ist bytes — wird in f-String eingesetzt | `.decode()` vor Verwendung |
| 105 | NIEDRIG | conflict_resolver.py | 145-148 | Leak (9) | `_last_resolutions` waechst unbegrenzt | TTL oder max-Size |
| 106 | NIEDRIG | conflict_resolver.py | 311-315 | Stille (2) | Fire-and-forget Task ohne Referenz — GC-Risk | Task in Set speichern |
| 107 | NIEDRIG | threat_assessment.py | 81 | API (6) | `get_states()` ohne Timeout | `asyncio.wait_for()` |
| 108 | NIEDRIG | threat_assessment.py | 535 | Perf (13) | Doppelter `get_states()` Call | States durchreichen |
| 109 | NIEDRIG | threat_assessment.py | 37 | Config (8) | Verwirrender Config-Key-Name | Explizit `enabled` Key |
| 110 | NIEDRIG | adaptive_thresholds.py | 173-178 | None (4) | `action_stats.get("total", 0)` findet bytes-Keys nicht → ZeroDivisionError | Guard `if total > 0` |
| 111 | NIEDRIG | error_patterns.py | 130-138 | Data (7) | `json.loads(item)` auf bytes — funktioniert aber fragil | Explizit decodieren |
| 112 | NIEDRIG | outcome_tracker.py | 297-298 | Logik (10) | `_classify_outcome()` unterscheidet nicht zwischen Ruecknahme und Weiterentwicklung | Richtung beruecksichtigen |

### circuit_breaker.py und threat_assessment.py — Nutzung

Beide Module sind **aktiv genutzt**:
- **circuit_breaker.py**: Importiert in `ha_client.py`, `ollama_client.py`, `brain.py`, `main.py`
- **threat_assessment.py**: Importiert in `brain.py`, `proactive.py`, `function_calling.py`, `main.py`

---

## Bug-Report: Batch 10 — Config & Domain-Start (31 Bugs: 5 HOCH, 14 MITTEL, 12 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 113 | HOCH | config.py | 241-247 | Race (3) | `_active_person` globaler String ohne Lock | `threading.Lock` |
| 114 | HOCH | config.py | 319 | Race (3) | `get_room_profiles()` Fast-Path VOR Lock — nicht atomar | Fast-Path entfernen oder Tuple-Swap |
| 115 | HOCH | cooking_assistant.py | 486-488 | None (4) | `_next_step()` greift auf `self.session` ohne None-Check — Race mit `_stop_session()` | None-Guard am Anfang |
| 116 | HOCH | cooking_assistant.py | 196 | Leak (9) | `_timer_tasks` waechst unbegrenzt — abgelaufene Tasks bleiben | Erledigte Tasks entfernen |
| 117 | HOCH | cooking_assistant.py | 196 | Leak (9) | `session.timers` ohne Limit — unbegrenzter Task-Spawn | Max 10 Timer pro Session |
| 118 | MITTEL | config.py | 168-219 | Race (3) | `_entity_to_name` globales Dict ohne Lock bei Reload | Immutable-Muster oder Lock |
| 119 | MITTEL | cooking_assistant.py | 508 | None (4) | `_prev_step()` ohne None-Guard fuer `self.session` | None-Check |
| 120 | MITTEL | cooking_assistant.py | 518 | None (4) | `_repeat_step()` ohne None-Guard | None-Check |
| 121 | MITTEL | cooking_assistant.py | 525-526 | None (4) | `_show_status()` ohne None-Guard | None-Check |
| 122 | MITTEL | cooking_assistant.py | 550 | None (4) | `_show_ingredients()` ohne None-Guard | None-Check |
| 123 | MITTEL | cooking_assistant.py | 563 | None (4) | `_adjust_portions()` ohne None-Guard | None-Check |
| 124 | MITTEL | cooking_assistant.py | 612 | None (4) | `_set_timer_from_text()` ohne None-Guard | None-Check |
| 125 | MITTEL | cooking_assistant.py | 298-303 | API (6) | `ollama.chat()` ohne Timeout | `asyncio.wait_for()` |
| 126 | MITTEL | config_versioning.py | 195-196 | Stille (2) | `except (...): pass` bei Snapshot-Cleanup | `logger.debug()` |
| 127 | MITTEL | config_versioning.py | 87-91 | Async (1) | `redis.pipeline()` ohne async Contextmanager | `async with self._redis.pipeline() as pipe:` |
| 128 | MITTEL | recipe_store.py | 66 | Async (1) | `get_or_create_collection()` sync in async `initialize()` | `asyncio.to_thread()` |
| 129 | MITTEL | recipe_store.py | 156 | Security (11) | `hashlib.md5()` fuer Content-Hash | `hashlib.sha256()` |
| 130 | MITTEL | recipe_store.py | 349-350 | Async (1) | `delete_collection()`/`get_or_create_collection()` sync in async `clear()` | `asyncio.to_thread()` |
| 131 | MITTEL | recipe_store.py | 263-268 | Logik (10) | `get_chunks()` laedt gesamte Collection, Offset/Limit erst danach | ChromaDB offset/limit Parameter nutzen |
| 132 | MITTEL | smart_shopping.py | 289 | API (6) | `ha.api_get()` ohne Timeout | Timeout mitgeben |
| 133 | MITTEL | smart_shopping.py | 302-316 | Perf (13) | `call_service()` sequentiell pro fehlende Zutat | `asyncio.gather()` |
| 134 | NIEDRIG | cooking_assistant.py | 116 | Stille (2) | `_get_activity()` gibt `"relaxing"` ohne Logging zurueck | `logger.debug()` |
| 135 | NIEDRIG | config_versioning.py | 133 | Logik (10) | `rsplit("_", 2)` — fragil bei Config-Namen mit 2+ Underscores | Eindeutigen Separator verwenden |
| 136 | NIEDRIG | config_versioning.py | 266-268 | Async (1) | `health_status()` sync I/O | `asyncio.to_thread()` |
| 137 | NIEDRIG | recipe_store.py | 137 | Async (1) | `_extract_pdf_text()` sync in async `ingest_file()` | `asyncio.to_thread()` |
| 138 | NIEDRIG | recipe_store.py | 140 | Async (1) | `filepath.read_text()` sync in async | `asyncio.to_thread()` |
| 139 | NIEDRIG | music_dj.py | 116-117 | Stille (2) | `except Exception: return "relaxing"` ohne Logging | `logger.debug()` |
| 140 | NIEDRIG | music_dj.py | 384 | Stille (2) | `logger.debug("Unhandled: %s", e)` — irrefuehrende Message | Message korrigieren |
| 141 | NIEDRIG | smart_shopping.py | 391 | Stille (2) | `logger.debug("Unhandled: %s", e)` — irrefuehrende Message | Message korrigieren |
| 142 | NIEDRIG | cooking_assistant.py | 107-108 | Logik (10) | Duplikate in `COOKING_KEYWORDS` durch Unicode-Varianten | Duplikate entfernen |
| 143 | NIEDRIG | cooking_assistant.py | 114-131 | Logik (10) | Duplikate in NAV-Listen durch Unicode-Varianten | Duplikate entfernen |

---

## Bug-Report: Batch 11 — Domain (20 Bugs: 3 HOCH, 8 MITTEL, 9 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 144 | HOCH | knowledge_base.py | 71 | Async (1) | `get_or_create_collection()` sync ChromaDB in async `initialize()` | `asyncio.to_thread()` |
| 145 | HOCH | knowledge_base.py | 549 | Async (1) | `delete_collection()` sync in async `clear()` | `asyncio.to_thread()` |
| 146 | HOCH | knowledge_base.py | 558 | Async (1) | `get_or_create_collection()` sync in async `clear()` | `asyncio.to_thread()` |
| 147 | MITTEL | inventory.py | 78-81 | Perf (13) | N+1 Redis in `remove_item()` — einzelne `hgetall` pro Item | Pipeline |
| 148 | MITTEL | inventory.py | 99-103 | Perf (13) | N+1 Redis in `update_quantity()` | Pipeline |
| 149 | MITTEL | inventory.py | 125-128 | Perf (13) | N+1 Redis in `list_items()` | Pipeline |
| 150 | MITTEL | inventory.py | 173-176 | Perf (13) | N+1 Redis in `check_expiring()` | Pipeline |
| 151 | MITTEL | knowledge_base.py | 219 | Async (1) | `_extract_pdf_text()` sync in async `ingest_file()` | `asyncio.to_thread()` |
| 152 | MITTEL | knowledge_base.py | 222 | Async (1) | `filepath.read_text()` sync in async | `asyncio.to_thread()` |
| 153 | MITTEL | knowledge_base.py | 333-338 | Perf (13) | Multi-Query ChromaDB sequentiell | `asyncio.gather()` |
| 154 | MITTEL | ocr.py | 97-136 | Async (1) | PIL/Tesseract sync CPU-intensiv in async `analyze_image()` | `asyncio.to_thread()` |
| 155 | NIEDRIG | summarizer.py | 348 | Leak (9) | `lrange 0 -1` laedt ALLE Konversationen ohne Limit | Limit verwenden |
| 156 | NIEDRIG | summarizer.py | 305-313 | Perf (13) | SCAN sammelt alle Keys ohne Limit | Frueh abbrechen |
| 157 | NIEDRIG | summarizer.py | 316 | Data (7) | bytes-Keys in `sort()` — TypeError wenn gemischt | Vor Sort decodieren |
| 158 | NIEDRIG | knowledge_base.py | 459 | Logik (10) | `where=None` an ChromaDB undokumentiert | Explizite Conditional |
| 159 | NIEDRIG | knowledge_base.py | 87 | Async (1) | `mkdir()` sync in async `initialize()` | `asyncio.to_thread()` |
| 160 | NIEDRIG | knowledge_base.py | 238 | Security (11) | `hashlib.md5()` fuer Content-Hash | `hashlib.sha256()` |
| 161 | NIEDRIG | ocr.py | 58 | Security (11) | Path-Validierung `".." in str(resolved)` unzuverlaessig | `is_relative_to()` verwenden |
| 162 | NIEDRIG | file_handler.py | 61-96 | Async (1) | `save_upload()` komplett synchron | `asyncio.to_thread()` am Call-Site |
| 163 | NIEDRIG | file_handler.py | 164 | Resilience (12) | `pdfplumber.open()` ohne spezifischen Exception-Handler | Spezifischer try/except |

---

## Bug-Report: Batch 12 — Monitoring (31 Bugs: 5 HOCH, 12 MITTEL, 14 NIEDRIG)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 164 | HOCH | workshop_library.py | 41 | Async (1) | `get_or_create_collection()` sync ChromaDB in async | `asyncio.to_thread()` |
| 165 | HOCH | workshop_library.py | 73 | Async (1) | `path.read_text()` sync File-I/O in async | `asyncio.to_thread()` |
| 166 | HOCH | workshop_library.py | 89 | Async (1) | `embedding_fn(chunk)` sync in List-Comprehension, sequentiell | `asyncio.to_thread(lambda: [...])` |
| 167 | HOCH | workshop_library.py | 117 | Async (1) | `embedding_fn(query)` sync in async `search()` | `asyncio.to_thread()` |
| 168 | HOCH | repair_planner.py | 313-328 | Perf (13) | N+1 Redis in `list_projects()` — sequentielle `hgetall` | Pipeline oder `asyncio.gather` |
| 169 | MITTEL | workshop_library.py | 40 | Async (1) | `WORKSHOP_DOCS_DIR.mkdir()` sync in async | `asyncio.to_thread()` |
| 170 | MITTEL | workshop_library.py | 185-186 | Async (1) | PDF-Extraktion (fitz/pdfplumber/PyPDF2) komplett sync | `asyncio.to_thread()` |
| 171 | MITTEL | workshop_generator.py | 508 | Async (1) | `filepath.write_text()` sync in async | `asyncio.to_thread()` |
| 172 | MITTEL | workshop_generator.py | 543 | Async (1) | `filepath.read_text()` sync in async | `asyncio.to_thread()` |
| 173 | MITTEL | workshop_generator.py | 586-589 | Async (1) | `zipfile.ZipFile` sync in async `export_project()` | `asyncio.to_thread()` |
| 174 | MITTEL | repair_planner.py | 978-994 | Perf (13) | N+1 Redis in `list_workshop()` | Pipeline |
| 175 | MITTEL | repair_planner.py | 1136-1147 | Perf (13) | N+1 Redis in `list_lent_tools()` | `asyncio.gather` |
| 176 | MITTEL | repair_planner.py | 1442-1453 | None (4) | `arm_pick_tool()` bytes-Keys aus `hgetall` — `pos.get("x")` findet `b"x"` nicht | Bytes decodieren |
| 177 | MITTEL | repair_planner.py | 1476-1478 | None (4) | `pause_timer()` `float(None)` → TypeError | Explizit bytes decodieren |
| 178 | MITTEL | repair_planner.py | 1497-1506 | Leak (9) | `create_task()` ohne Referenz — GC-Risk. Kein Timer-Limit. | Task-Referenz speichern |
| 179 | MITTEL | energy_optimizer.py | 286-299 | Perf (13) | 7 sequentielle `redis.get()` in `_check_anomaly()` | Pipeline |
| 180 | MITTEL | energy_optimizer.py | 328-356 | Perf (13) | 14 sequentielle `redis.get()` in `_get_weekly_comparison()` | Pipeline |
| 181 | MITTEL | device_health.py | 126-139 | Resilience (12) | `_check_loop()` kein Startup-Delay — Check vor Init | `await asyncio.sleep(startup_delay)` |
| 182 | MITTEL | workshop_generator.py | 154-155 | None (4) | `model_router.model_deep` ohne `getattr` Schutz | `getattr()` verwenden |
| 183 | MITTEL | workshop_generator.py | 511-519 | Leak (9) | `rpush` ohne Deduplizierung — Dateiname-Liste waechst | `sadd` statt `rpush` |
| 184 | NIEDRIG | repair_planner.py | 453 | None (4) | `response.get()` — wenn String statt Dict: AttributeError | Typ-Check |
| 185 | NIEDRIG | repair_planner.py | 541-544 | None (4) | 6 weitere Stellen mit gleichem `_resp.get()` Problem | Wrapper-Methode |
| 186 | NIEDRIG | repair_planner.py | 964-965 | Security (11) | `add_workshop_item()` ohne Input-Validierung | Regex-Validierung |
| 187 | NIEDRIG | repair_planner.py | 1540 | Security (11) | `save_snippet()` ohne Name-Validierung | Regex-Validierung |
| 188 | NIEDRIG | repair_planner.py | 1002 | Security (11) | `add_maintenance_schedule()` ohne Validierung | Regex-Validierung |
| 189 | NIEDRIG | repair_planner.py | 1119 | Security (11) | `lend_tool()` ohne Validierung | Regex-Validierung |
| 190 | NIEDRIG | repair_planner.py | 948 | API (6) | `ollama.chat()` ohne `model` Parameter | Default-Model uebergeben |
| 191 | NIEDRIG | energy_optimizer.py | 439 | Logik (10) | `val > 0` ignoriert Sensoren mit Wert 0 | `val is not None` verwenden |
| 192 | NIEDRIG | predictive_maintenance.py | 170 | Perf (13) | `_save_devices()` serialisiert ALLE Devices pro Update | Individuellen Key pro Device |
| 193 | NIEDRIG | predictive_maintenance.py | 119-125 | Leak (9) | `_devices` dict waechst unbegrenzt | Cleanup fuer nicht existierende Entities |
| 194 | NIEDRIG | health_monitor.py | 314-328 | Dead Code | `_check_temperature()` nie aufgerufen (auskommentiert) | Entfernen |

---

## Bug-Report: Batch 13 — Rest (27 Bugs: 7 HOCH, 8 MITTEL, 10 NIEDRIG, 2 INFO)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 195 | HOCH | wellness_advisor.py | 240 | Resilience (12) | `redis.get()` OHNE `_safe_redis()` — direkt, crasht bei Redis-Fehler | `_safe_redis()` verwenden |
| 196 | HOCH | wellness_advisor.py | 261 | Resilience (12) | `redis.get()` ohne `_safe_redis()` in Break-Reminder | `_safe_redis()` |
| 197 | HOCH | wellness_advisor.py | 337 | Resilience (12) | `redis.get()` ohne `_safe_redis()` in Stress-Nudge | `_safe_redis()` |
| 198 | HOCH | wellness_advisor.py | 402 | Resilience (12) | `redis.exists()` ohne `_safe_redis()` | `_safe_redis()` |
| 199 | HOCH | wellness_advisor.py | 481 | Resilience (12) | `redis.exists()` ohne `_safe_redis()` in Late-Night | `_safe_redis()` |
| 200 | HOCH | wellness_advisor.py | 638 | Resilience (12) | `redis.get()` ohne `_safe_redis()` in Hydration | `_safe_redis()` |
| 201 | HOCH | wellness_advisor.py | 701 | Resilience (12) | `redis.get()` ohne `_safe_redis()` in Mood-Ambient | `_safe_redis()` |
| 202 | MITTEL | wellness_advisor.py | 609 | Data (7) | `sismember` bytes vs String Inkonsistenz | Konsistentes Encoding |
| 203 | MITTEL | follow_me.py | 91,96 | Race (3) | `_person_room`/`_last_transfer` ohne Lock bei parallelen Motion-Events | `asyncio.Lock()` |
| 204 | MITTEL | visitor_manager.py | 280 | Race (3) | `_last_ring_time` ohne Lock — Cooldown umgehbar | `asyncio.Lock()` |
| 205 | MITTEL | diagnostics.py | 436 | Async (1) | `open()` sync File-I/O in `_load_maintenance_tasks` | `aiofiles` oder `asyncio.to_thread()` |
| 206 | MITTEL | diagnostics.py | 447 | Async (1) | `open(..., "w")` sync in `_save_maintenance_tasks` | `asyncio.to_thread()` |
| 207 | MITTEL | diagnostics.py | 491 | Async (1) | `open(meminfo_path)` sync in `check_system_resources` | `asyncio.to_thread()` |
| 208 | MITTEL | diagnostics.py | 558 | Resilience (12) | Redis-Verbindung ohne `async with` — Leak bei Fehler | `async with` oder `finally` |
| 209 | MITTEL | timer_manager.py | 435 | Data (7) | `replace(tzinfo=_TZ)` — bei ZoneInfo akzeptabel, aber fragil | Kein Fix noetig |
| 210 | NIEDRIG | follow_me.py | 250-251 | Stille (2) | Transfer-Fehler nur `logger.debug()` | `logger.warning()` |
| 211 | NIEDRIG | follow_me.py | 185-186 | Stille (2) | Musik-Transfer-Fehler nur debug | `logger.warning()` |
| 212 | NIEDRIG | follow_me.py | 279-280 | Stille (2) | Klima-Transfer-Fehler nur debug | `logger.warning()` |
| 213 | NIEDRIG | seasonal_insight.py | 120 | Stille (2) | Loop-Fehler nur debug | `logger.warning()` |
| 214 | NIEDRIG | visitor_manager.py | 139-140 | Stille (2) | Korrupte Besucher still uebersprungen | `logger.debug()` |
| 215 | NIEDRIG | visitor_manager.py | 241 | Stille (2) | Parsing-Fehler still verschluckt | Logging hinzufuegen |
| 216 | NIEDRIG | task_registry.py | 120 | Logik (10) | Timeout-Warnung sagt "30s" obwohl Default 10s | Message korrigieren |
| 217 | NIEDRIG | wellness_advisor.py | 186-193 | Perf (13) | 4 parallele Checks rufen intern `detect_activity()` auf | Activity einmal vorladen |
| 218 | NIEDRIG | follow_me.py | 224 | Dead Code | Redundanter lokaler `from datetime import datetime` | Entfernen |
| 219 | INFO | diagnostics.py | 69 | Leak (9) | `_alert_cooldowns` waechst unbegrenzt | Periodisches Cleanup |
| 220 | INFO | timer_manager.py | 137 | Leak (9) | `_tasks` dict: cancelled Tasks bleiben | Cleanup in shutdown |
| 221 | NIEDRIG | explainability.py | 67 | None (4) | `context: dict = None` redundante Guard-Logik | Type-Hint korrigieren |

---

## Dead-Code-Liste

| Modul | Zeile(n) | Beschreibung |
|-------|----------|-------------|
| proactive.py | 2148-2157 | `_get_person_title()` dupliziert `config.get_person_title()` |
| proactive.py | 1351 | Redundanter `from datetime import datetime` (bereits Modul-Level) |
| tts_enhancer.py | 153-166 | `self.vol_day`, `self.evening_start`, `self.auto_night_whisper` etc. (12 Variablen) — gesetzt aber nie gelesen; Methoden lesen live aus `yaml_config` |
| health_monitor.py | 314-328 | `_check_temperature()` definiert aber nie aufgerufen (auskommentiert in `check_all()`) |
| repair_planner.py | 78-101 | NAV_SHOP, NAV_SAVE, NAV_CODE etc. (11 Sets) — erkannt in `is_repair_navigation()` aber nicht in `handle_navigation()` behandelt |
| repair_planner.py | 105-114 | `REPAIR_KEYWORDS` Set definiert, nirgends im Modul verwendet |
| feedback.py | 348 | Dead-Code-Zeile: Double-decode nach vorherigem Decode (Bug #72) |
| self_optimization.py | 15 | `import re` — nie verwendet |
| self_optimization.py | 95, 562, 568, 582-583 | Redundante lokale Re-Imports (`datetime`, `json`, `timedelta`) |
| learning_observer.py | 345-346, 393, 405-406, 470 | Redundante `isinstance(x, bytes)` Checks — mit `decode_responses=True` immer False |
| smart_shopping.py | 29 | `_KEY_PURCHASE_LOG` Sorted-Set Key definiert aber nie verwendet |
| cooking_assistant.py | 84 | `raw_recipe` im CookingSession-Dataclass gesetzt aber nie gelesen |
| calendar_intelligence.py | 145-158 | `hour_activity` Counter befuellt aber nie zurueckgegeben in `_detect_habits()` |
| activity.py | 146-147 | `SILENCE_MATRIX`/`VOLUME_MATRIX` Modul-Level-Kopien — wahrscheinlich Dead Code |
| follow_me.py | 224 | Redundanter lokaler `from datetime import datetime` |

---

## Top-10 Bugs (Prioritaet fuer P6a)

| Rang | # | Severity | Modul | Beschreibung | Aufwand |
|------|---|----------|-------|-------------|---------|
| 1 | 1 | KRITISCH | proactive.py:98,146 | event_handlers ueberschrieben — YAML-Appliance-Handler verloren | 5 Zeilen: `.update()` statt Zuweisung |
| 2 | 195-201 | HOCH | wellness_advisor.py | 7 Redis-Calls ohne `_safe_redis()` — crasht bei Redis-Fehler | 7x `_safe_redis()` einsetzen |
| 3 | 164-167 | HOCH | workshop_library.py | 4x sync ChromaDB/Embedding in async — blockiert Event-Loop | 4x `asyncio.to_thread()` |
| 4 | 144-146 | HOCH | knowledge_base.py | 3x sync ChromaDB in async — Init und Clear blockieren | 3x `asyncio.to_thread()` |
| 5 | 2 | HOCH | proactive.py:2620 | `_batch_flushing` Race Condition ohne Lock | Lock verwenden |
| 6 | 113-114 | HOCH | config.py | `_active_person` + Room-Profiles Fast-Path Race | Lock oder Tuple-Swap |
| 7 | 115-124 | HOCH | cooking_assistant.py | 7x `self.session` ohne None-Guard + unbegrenzte Timer | None-Checks + Limit |
| 8 | 73-74 | HOCH | self_optimization.py | Sync YAML I/O in async — blockiert Event-Loop | `asyncio.to_thread()` |
| 9 | 56-58 | HOCH | multi_room_audio.py + speaker_recognition.py | 3x N+1 HTTP/Redis — Speaker-Status und Embeddings | `asyncio.gather()` + `mget()` |
| 10 | 30-31 | HOCH | ha_client.py | Session vor Retry-Loop — stale bei Close | Session pro Versuch holen |

---

## KONTEXT AUS PROMPT 4b (DL#2): Bug-Report (Extended-Module)

### Statistik
Gesamt: 221 Bugs in Prioritaet 5-9 (KRITISCH 1, HOCH 36, MITTEL 97, NIEDRIG 85, INFO 2)

### Kritische Bugs (1)
- `proactive.py:98,146` — event_handlers wird komplett ueberschrieben, YAML-Appliance-Handler gehen verloren

### Hohe Bugs (36) — Top-Cluster
- **Sync I/O in async (11)**: workshop_library.py (4x ChromaDB/Embeddings), knowledge_base.py (3x), self_optimization.py (2x YAML), self_automation.py (1x Import-Zeit)
- **Resilience (7)**: wellness_advisor.py 7x Redis-Calls ohne `_safe_redis()` Wrapper
- **Race Conditions (4)**: proactive.py _batch_flushing, config.py _active_person + room_profiles, ha_client.py Session-Lifecycle
- **Performance N+1 (3)**: multi_room_audio.py Speaker-Status, speaker_recognition.py Embeddings
- **None-Fehler (2)**: cooking_assistant.py session-Race + unbegrenzte Timer
- **Stille Fehler (5)**: proactive.py 4x `except: pass`, learning_observer.py Hauptlogik
- **Memory Leaks (2)**: cooking_assistant.py Timer-Tasks unbegrenzt
- **Logik (1)**: feedback.py Double-decode
- **API (1)**: ha_client.py Session vor Retry-Loop

### Dead-Code-Liste
- proactive.py: `_get_person_title()` Duplikat, redundanter Import
- tts_enhancer.py: 12 Instance-Variablen gesetzt aber nie gelesen
- health_monitor.py: `_check_temperature()` nie aufgerufen
- repair_planner.py: 11 NAV-Sets erkannt aber nicht behandelt, REPAIR_KEYWORDS ungenutzt
- self_optimization.py: `import re` ungenutzt, 4 redundante Re-Imports
- smart_shopping.py: `_KEY_PURCHASE_LOG` ungenutzt
- calendar_intelligence.py: `hour_activity` Counter nie zurueckgegeben

### Resilience-Findings
- **wellness_advisor.py**: Definiert `_safe_redis()` aber nutzt es inkonsistent — 7 von 14 Redis-Calls direkt
- **light_engine.py**: 1 Redis-Call ohne `_safe_redis()` Wrapper
- **conditional_commands.py**: Redis-Calls in Loop ohne try/except
- **circuit_breaker.py**: Aktiv genutzt (ha_client, ollama_client, brain, main), State-Properties mit Seiteneffekten
- **threat_assessment.py**: Aktiv genutzt (brain, proactive, function_calling, main), `get_states()` ohne Timeout

### Systemische Muster
1. **Sync I/O in async** ist das dominante HIGH-Pattern (11 von 36 HIGH Bugs) — ChromaDB, File-I/O, Embeddings, YAML
2. **N+1 Redis** bleibt systemisch (25 Stellen) — inventory.py, repair_planner.py, energy_optimizer.py am schlimmsten
3. **`except Exception: pass` → `logger.debug()`** Bulk-Fix aus P8 maskiert Fehler — 38 stille-Fehler-Bugs
4. **None-Fehler-Cluster** in cooking_assistant.py (7 Stellen) — alle session-bezogen
5. **Race Conditions** in globalen Variablen (config.py) und Instance-Variablen ohne Lock

---

## Post-Fix-Verifikation (2026-03-11, nach P06a-P08 + finale Fixes)

**Methode**: Jeder HIGH/CRITICAL Bug gegen den tatsaechlichen Quellcode geprueft.

### Nachtraeglich als GEFIXT bestaetigt (im Code verifiziert):

| Bug | Severity | Modul | Beschreibung | Gefixt durch |
|-----|----------|-------|-------------|-------------|
| #1 | KRITISCH | proactive.py | event_handlers ueberschrieben | P06a |
| #56 | HOCH | multi_room_audio.py | `_build_group_status()` N+1 → `asyncio.gather()` | P06b |
| #57 | HOCH | multi_room_audio.py | `_get_speaker_names()` N+1 → `asyncio.gather()` | P06b |
| #115 | HOCH | cooking_assistant.py | `_next_step()` session None-Check | P06b |
| #144 | HOCH | knowledge_base.py | `get_or_create_collection()` → `asyncio.to_thread()` | P06b |
| #145 | HOCH | knowledge_base.py | `delete_collection()` → `asyncio.to_thread()` | P06b |
| #146 | HOCH | knowledge_base.py | `get_or_create_collection()` → `asyncio.to_thread()` | P06b |
| #195 | HOCH | wellness_advisor.py | Redis get() → `_safe_redis()` | P06b |
| #196 | HOCH | wellness_advisor.py | Redis get() → `_safe_redis()` | P06b |
| #197 | HOCH | wellness_advisor.py | Redis get() → `_safe_redis()` | P06b |
| #198 | HOCH | wellness_advisor.py | Redis exists() → `_safe_redis()` | P06b |
| #199 | HOCH | wellness_advisor.py | Redis exists() → `_safe_redis()` | P06b |
| #200 | HOCH | wellness_advisor.py | Redis get() → `_safe_redis()` | P06b |
| #201 | HOCH | wellness_advisor.py | Redis get() → `_safe_redis()` | P06b |

### Verifiziert NOCH OFFEN (im Code geprueft, Bug existiert noch):

| Bug | Severity | Modul | Beschreibung |
|-----|----------|-------|-------------|
| #2 | HOCH | proactive.py | `_batch_flushing` Boolean ohne Lock |
| #3 | HOCH | proactive.py | `except Exception: pass` in `_accumulate_event` |
| #4 | HOCH | proactive.py | `except Exception: pass` in Mood-Check |
| #5 | HOCH | proactive.py | `except Exception: pass` in Narration |
| #6 | HOCH | self_automation.py | `_load_templates()` sync File-I/O bei Module-Load |
| #7 | HOCH | proactive.py | `except Exception: return` ohne Logging in `_check_personal_dates` |
| #29 | HOCH | ha_client.py | `close()` nicht thread-safe (kein `_session_lock`) |
| #30 | HOCH | ha_client.py | `mindhome_put()` Session vor Retry-Loop geholt |
| #31 | HOCH | ha_client.py | `mindhome_delete()` gleiche stale-Session |
| #58 | HOCH | speaker_recognition.py | `identify_by_embedding()` N+1 Redis |
| #72 | HOCH | feedback.py | Redundanter Double-Decode |
| #73 | HOCH | self_optimization.py | Sync File-I/O in async `_apply_parameter()` |
| #74 | HOCH | self_optimization.py | Sync File-I/O in async `add_banned_phrase()` |
| #75 | HOCH | learning_observer.py | `logger.debug()` statt `logger.warning()` |
| #113 | HOCH | config.py | `_active_person` global ohne Lock |
| #114 | HOCH | config.py | `get_room_profiles()` Fast-Path vor Lock |
| #116 | HOCH | cooking_assistant.py | `_timer_tasks` waechst unbegrenzt |
| #117 | HOCH | cooking_assistant.py | `session.timers` ohne Limit |
| #164 | HOCH | workshop_library.py | Sync ChromaDB `get_or_create_collection()` |
| #165 | HOCH | workshop_library.py | Sync `path.read_text()` in async |
| #166 | HOCH | workshop_library.py | Sync Embeddings in List-Comprehension |
| #167 | HOCH | workshop_library.py | Sync `embedding_fn(query)` in async `search()` |
| #168 | HOCH | repair_planner.py | N+1 Redis in `list_projects()` |

### Aktualisierte Bug-Bilanz (Post-Verifikation):

```
Urspruenglich: 221 Bugs (1 KRITISCH, 36 HOCH, 97 MITTEL, 85 NIEDRIG, 2 INFO)
Gefixt:        14 (1 KRITISCH, 13 HOCH)
Noch offen:    207 (0 KRITISCH, 23 HOCH, ~97 MITTEL, ~85 NIEDRIG, 2 INFO)
Davon code-verifiziert: 23 HIGH bestaetigt offen
```
