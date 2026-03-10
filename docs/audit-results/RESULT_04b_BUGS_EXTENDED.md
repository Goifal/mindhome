# Audit-Ergebnis: Prompt 4b — Systematische Bug-Jagd (Extended-Module, Prioritaet 5-9)

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: 63 Extended-Module in 9 Batches (Prio 5-9), 13 Fehlerklassen
**Methode**: 9 parallele Audit-Agenten, jedes Modul komplett gelesen

---

## Gesamt-Statistik

```
Gesamt: 155 Bugs (Prioritaet 5-9)
  KRITISCH: 12
  HOCH: 39
  MITTEL: 58
  NIEDRIG: 46

Haeufigste Fehlerklasse: Redis bytes vs string (42 Vorkommen)
Zweithaeufigste: Stille Fehler / except:pass (22 Vorkommen)
Am staerksten betroffenes Modul: repair_planner.py (8 Bugs)
Zweitstaerkstes: wellness_advisor.py (7 Bugs inkl. Dead Code)
```

---

## Bug-Report: Batch 5 — Proaktive Systeme (proactive.py, proactive_planner.py, routine_engine.py, anticipation.py, spontaneous_observer.py, autonomy.py, self_automation.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 1 | KRITISCH | proactive.py | 108 | Init | **`self.event_handlers` gelesen vor Definition.** Wird in Zeile 108 gebraucht (`if event_type not in self.event_handlers`) aber erst in Zeile 145 definiert. Wenn `appliance_monitor.devices` in YAML gesetzt ist, crasht `__init__` mit `AttributeError`. Deaktiviert gesamten ProactiveManager. | `self.event_handlers = {}` vor dem `devices`-Loop initialisieren. |
| 2 | HOCH | proactive.py | 594 | Logic | **Operator-Praezedenz-Bug.** `entity_id.startswith("proximity.") or entity_id.startswith("sensor.") and "distance" in entity_id` — `and` bindet staerker als `or`. JEDE `proximity.*` Entity loest Geo-Fence-Logik aus. | Klammern: `... or (entity_id.startswith("sensor.") and "distance" in entity_id)` |
| 3 | HOCH | proactive.py | 969, 1064 | Race Condition | **`_mb_triggered_today` / `_eb_triggered_today` ohne Lock.** Mehrere Motion-Events koennen doppeltes Briefing ausloesen. | `self._state_lock` verwenden. |
| 4 | HOCH | self_automation.py | 449 | Security | **User-Beschreibung unsanitized in LLM-Prompt.** `f"Erstelle eine Automation fuer: {description}"` — Prompt Injection kann nicht-whitelisted Services generieren. | Sanitize: Zeilenumbrueche/Steuerzeichen entfernen, alphanumerisch beschraenken. |
| 5 | HOCH | self_automation.py | 103 | Race Condition | **`_pending` dict ohne Lock.** Concurrent `generate_automation`, `confirm_automation`, `_cleanup_expired_pending` koennen sich gegenseitig korrumpieren. | `asyncio.Lock` einfuehren. |
| 6 | HOCH | self_automation.py | 996-1001 | Race Condition | **`_daily_count` / `_daily_reset` ohne Lock.** Parallele Requests umgehen Rate-Limit. | `asyncio.Lock` oder atomaren Reset. |
| 7 | MITTEL | proactive.py | 990 | None | **`getattr(autonomy, "current_level", 3)` — Attribut heisst `level`.** Fallback `3` greift immer, echtes Autonomie-Level wird ignoriert. | `getattr(autonomy, "level", 3)` |
| 8 | MITTEL | proactive_planner.py | 218 | Logic | **`if not actions: return None` ist unerreichbar** — mindestens ein Eintrag wird immer hinzugefuegt (Zeile 212). | Check entfernen oder Musik-Hinzufuegung konditionell machen. |
| 9 | MITTEL | anticipation.py | 131-135 | Data | **`redis.lrange()` gibt `bytes` zurueck.** `json.loads(e)` funktioniert, aber fehlende explizite Dekodierung (im Gegensatz zu spontaneous_observer.py:325). | `json.loads(e.decode() if isinstance(e, bytes) else e)` |
| 10 | MITTEL | anticipation.py | 601 | Data | **`pattern_key` enthaelt rohe `description`.** Sonderzeichen/lange Strings erzeugen ungueltige/riesige Redis-Keys. | Key laengenlimitieren, Hash verwenden. |
| 11 | MITTEL | routine_engine.py | 533 | Silent Error | **`except Exception: pass`** in `_get_energy_briefing()`. Energie-Daten fehlen stillschweigend im Briefing. | `logger.debug()` hinzufuegen. |
| 12 | MITTEL | self_automation.py | 453 | API | **`ollama.chat()` ohne Timeout.** LLM-Haenger blockiert `generate_automation` unbegrenzt. | `asyncio.wait_for(..., timeout=30)` |
| 13 | MITTEL | proactive.py | 1040 | None | **`self.brain.memory.redis` ohne None-Check.** An anderen Stellen korrekt (z.B. Zeile 1264). | Guard hinzufuegen. |
| 14 | MITTEL | proactive.py | 5184 | None | **Inkonsistenter Redis-Zugriff.** `self.brain.redis` vs `self.brain.memory.redis` — unterschiedliche Pfade. | Einheitlich zugreifen. |
| 15 | MITTEL | autonomy.py | 408 | Data | **`hgetall()` gibt `bytes`-Keys zurueck.** `stats.get("total", 0)` matched nie — echte Redis-Werte werden nie gelesen. | Keys dekodieren. |
| 16 | NIEDRIG | proactive.py | 2130-2139 | Logic | **`_get_person_title()` dupliziert globale `get_person_title()`.** Code-Duplikation. | Eine entfernen. |
| 17 | NIEDRIG | spontaneous_observer.py | 260-261 | Silent Error | **`except (ValueError, TypeError): pass`** in `_check_energy_comparison`. | `logger.debug()` |
| 18 | NIEDRIG | self_automation.py | 107 | Memory | **`_audit_log` Liste statt deque.** Trimming (`[-100:]`) erstellt jedes Mal neue Liste. | `collections.deque(maxlen=100)` |
| 19 | NIEDRIG | proactive.py | 1998-1999 | Performance | **`scan_iter` Keys in Liste gesammelt** statt direkt iteriert. | Direkt ueber Iterator arbeiten. |

---

## Bug-Report: Batch 6 — HA-Integration (conditional_commands.py, protocol_engine.py, ha_client.py, light_engine.py, climate_model.py, cover_config.py, camera_manager.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 20 | HOCH | ha_client.py | 53-54, 77-90 | Race Condition | **`_states_cache` ohne Lock.** Zwei gleichzeitige `get_states()` feuern beide HTTP-Request. | `asyncio.Lock` um Cache-Zyklus. |
| 21 | HOCH | ha_client.py | 140-165 | API | **`get_camera_snapshot()` ohne Timeout/Retry.** Haengende Kamera blockiert bis Session-Timeout (20s). | Per-Request Timeout + Retry. |
| 22 | HOCH | ha_client.py | 154-157 | Resilience | **Camera 404/500 oeffnet Circuit Breaker nicht.** `record_failure()` nur im Exception-Zweig. | Auch bei nicht-200 Status aufrufen. |
| 23 | HOCH | ha_client.py | 357-377 | Resilience | **`mindhome_put/delete` ohne Retry-Logik** (im Gegensatz zu `mindhome_post`). | Retry-Loop analog zu `mindhome_post`. |
| 24 | MITTEL | ha_client.py | 69-73 | Resilience | **`close()` nicht thread-safe.** Session ohne Lock geprueft/gesetzt. | `_session_lock` verwenden. |
| 25 | MITTEL | protocol_engine.py | 124 | Logic | **`datetime.now().isoformat()` ohne Timezone.** Inkonsistent mit conditional_commands.py (UTC). | `datetime.now(timezone.utc)` |
| 26 | MITTEL | protocol_engine.py | 193-194 | Silent Error | **`except Exception: pass`** bei Redis-Update der Undo-Steps. | `logger.warning()` |
| 27 | MITTEL | protocol_engine.py | 267-270 | Resilience | **Undo-Fehler nur auf debug-Level.** `success: True` trotz fehlgeschlagener Schritte. | Fehler zaehlen, `success: False` bei Teilfehlern. |
| 28 | MITTEL | protocol_engine.py | 345-350 | Logic | **`if name in text_lower` zu breit.** Protokoll "an" matched jeden Text mit "an". | `re.search(rf'\b{re.escape(name)}\b', text_lower)` |
| 29 | MITTEL | light_engine.py | 187 | Logic | **Private `_get_adaptive_brightness` von externem Modul aufgerufen.** Enge Kopplung. | Methode oeffentlich machen oder auslagern. |
| 30 | MITTEL | light_engine.py | 418, 530 | Performance | **Redis `KEYS` Befehl (O(N)).** Wird alle 60s aufgerufen. | `SCAN`-basierte Iteration. |
| 31 | MITTEL | light_engine.py | 532-533 | Logic | **Pathlight-Timeout prueft `ttl <= 0`** — greift nur bei Keys ohne TTL (Bug-Fall). | Aktive Pathlights in Set tracken. |
| 32 | MITTEL | camera_manager.py | 69, 77 | Memory | **Snapshot-Bytes (mehrere MB) im Response-Dict.** Haeufige Abfragen = Memory-Wachstum. | Separat zurueckgeben oder Groessencheck. |
| 33 | NIEDRIG | conditional_commands.py | 140 | None | **Type-Hint `dict` statt `Optional[dict]`.** Korrekt abgefangen aber irreführend. | `Optional[dict] = None` |
| 34 | NIEDRIG | conditional_commands.py | 282 | Logic | **Float-Vergleich mit `==`.** Unzuverlaessig bei Fliesskommazahlen. | `math.isclose()` |
| 35 | NIEDRIG | protocol_engine.py | 369 | Logic/Security | **User-Input unsanitized in LLM-Prompt** via `prompt.replace("{description}", description)`. | Template-Engine oder Escape-Logik. |
| 36 | NIEDRIG | cover_config.py | 196, 212 | Security | **`position` in `update_cover_schedule` nicht validiert** (im Gegensatz zu `create`). | `max(0, min(100, ...))` Validierung. |
| 37 | NIEDRIG | cover_config.py | 35-44 | Resilience | **Korrupte Cover-Config = stiller Datenverlust.** Gibt leeres Dict zurueck. | Backup-Datei (.bak). |
| 38 | NIEDRIG | climate_model.py | 279 | Logic | **Fehlende Warnung bei Temperatur ausserhalb 15-30 Grad.** Wert wird still verworfen. | Optionale Warnung. |

---

## Bug-Report: Batch 7 — Audio (tts_enhancer.py, sound_manager.py, ambient_audio.py, multi_room_audio.py, speaker_recognition.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 39 | HOCH | sound_manager.py | 302-303 | Silent Error | **`except Exception: pass` bei `unjoin`-Call.** Speaker bleiben gruppiert ohne Benachrichtigung. | Exception loggen. |
| 40 | HOCH | multi_room_audio.py | 174 | Silent Error | **`except Exception: return []` in `list_groups()`.** Redis-Fehler werden nicht geloggt. | `logger.warning()` |
| 41 | HOCH | multi_room_audio.py | 482 | Silent Error | **`except Exception: return None` in `_get_group()`.** Aufrufer interpretiert None als "nicht existent". | Loggen und ggf. Exception re-raisen. |
| 42 | HOCH | multi_room_audio.py | 362-363 | Silent Error | **`except Exception: pass` bei `volume_set`.** Gibt `success: True` trotz Fehler zurueck. | Exception loggen, Erfolgs-Status korrekt reflektieren. |
| 43 | HOCH | multi_room_audio.py | 495-496 | Silent Error | **`except Exception` bei `get_state()`.** Systematische HA-Probleme nie sichtbar. | Logger-Aufruf hinzufuegen. |
| 44 | MITTEL | tts_enhancer.py | 309-315 | Logic | **Tageszeit-Logik-Fehler.** Abends (22-23:59) wird `vol_day` statt `vol_evening` zurueckgegeben wenn `night_start=0`. | Evening-Check vor Night-Check setzen. |
| 45 | MITTEL | speaker_recognition.py | 877 | Silent Error | **`except Exception: pass`** beim Redis-Set der Pending-Ask. Rueckfrage ohne State. | Loggen. |
| 46 | MITTEL | speaker_recognition.py | 905 | Silent Error | **`except Exception: return None`** in `resolve_fallback_answer()`. | Exception loggen. |
| 47 | MITTEL | multi_room_audio.py | 101-102 | Silent Error | **`except Exception` in `create_group()`.** Exception nicht geloggt. | `logger.warning()` |
| 48 | MITTEL | sound_manager.py | 549-556 | Memory | **`asyncio.create_task()` nicht referenziert.** Task kann vom GC eingesammelt werden. | Task in Set einfuegen. |
| 49 | MITTEL | speaker_recognition.py | 192 | Data | **Inkonsistente bytes-Dekodierung.** `identify_by_embedding()` nutzt `json.loads(data)` auf Redis-bytes direkt (funktioniert, aber inkonsistent). | Konsistenz herstellen. |
| 50 | NIEDRIG | multi_room_audio.py | 485-496 | Performance | **`get_state()` sequentiell pro Speaker.** Bei 5+ Speakern langsam. | `asyncio.gather()` |
| 51 | NIEDRIG | speaker_recognition.py | 737-746 | Performance | **Embeddings sequentiell aus Redis geladen** pro Profil. | `asyncio.gather()` oder Pipeline. |
| 52 | NIEDRIG | ambient_audio.py | 387-406 | Performance | **`get_state()` sequentiell pro Sensor** in `_poll_loop()`. | `asyncio.gather()` oder `get_states()`. |
| 53 | NIEDRIG | tts_enhancer.py | 337 | Performance | **Regex bei jedem Aufruf neu kompiliert** in `check_whisper_command()`. | Vorkompilieren. |

---

## Bug-Report: Batch 8 — Intelligence (insight_engine.py, learning_observer.py, learning_transfer.py, self_optimization.py, self_report.py, feedback.py, response_quality.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 54 | HOCH | feedback.py | 262-264 | Data | **`key.replace(...)` auf `bytes` statt `str`.** `redis.scan()` gibt bytes zurueck. `TypeError`. Auch Zeile 299. | `.decode()` vor `.replace()` |
| 55 | HOCH | feedback.py | 344-351 | Data | **`hgetall()` gibt bytes-Keys.** Downstream erwartet String-Keys. | Keys dekodieren. |
| 56 | HOCH | self_optimization.py | 96 | Data | **`datetime.fromisoformat(last_run)` auf bytes.** `TypeError` bei jedem Aufruf — Rate-Limiting greift nie. | `.decode()` |
| 57 | HOCH | self_optimization.py | 588-590 | Data | **`hgetall()` bytes-Keys** in `get_character_break_stats()`. | `.decode()` |
| 58 | HOCH | feedback.py | 84, 406-411 | Race Condition | **`_pending` dict concurrent gelesen/geschrieben.** `pop()` waehrend Iteration → doppelter Score-Abzug. | Iteration ueber `list()`, Guard-Check. |
| 59 | MITTEL | self_optimization.py | 420-421 | Silent Error | **`except Exception: return {}`** in `_get_feedback_stats()`. | `logger.debug()` |
| 60 | MITTEL | learning_transfer.py | 73-74 | Memory | **`_pending_transfers` Liste ohne Limit.** Waechst unbegrenzt. | `self._pending_transfers = self._pending_transfers[:50]` |
| 61 | MITTEL | self_optimization.py | 549-550, 575-576 | Silent Error | **2x `except Exception: pass`** in `track_filtered_phrase()` und `track_character_break()`. | `logger.debug()` |
| 62 | MITTEL | self_optimization.py | 633-634 | Silent Error | **2x `except Exception: pass`** in `detect_new_banned_phrases()`. | `logger.debug()` |
| 63 | MITTEL | insight_engine.py | 934 | Logic | **`ltrim` hardcoded auf 5** statt `self.max_temp_snapshots - 1`. Config-Erhoehung wirkungslos. | Dynamischen Wert verwenden. |
| 64 | MITTEL | insight_engine.py | 936 | Silent Error | **`except Exception: pass`** in `_store_temp_snapshot()`. Trend-Prediction ohne Daten. | `logger.debug()` |
| 65 | MITTEL | insight_engine.py | 878-890 | Logic | **`run_checks_now()` hat andere Check-Liste als `_run_all_checks()`.** 6 Checks fehlen on-demand. | Check-Listen synchronisieren. |
| 66 | MITTEL | self_optimization.py | 623-625 | Data | **`hgetall()` bytes in Phrase-Filter.** String-Vergleiche schlagen fehl. | `.decode()` |
| 67 | NIEDRIG | feedback.py | 338-344 | Resilience | **`_increment_counter()` ohne try/except.** Redis-Ausfall crasht Feedback-Verarbeitung. | try/except mit logger.debug. |
| 68 | NIEDRIG | self_optimization.py | 366-379 | Resilience | **`_apply_parameter()` schreibt nicht atomar.** Absturz = korrupte settings.yaml. | Tempfile + `os.replace()`. |
| 69 | NIEDRIG | learning_observer.py | 148 | Silent Error | **Fehler nur auf debug-Level.** Im Produktivbetrieb unsichtbar. | `logger.warning()` |
| 70 | NIEDRIG | self_report.py | 50-53 | Logic | **Rate-Limit im RAM** (`_last_report_day`). Bei Neustart geht Wert verloren. | Aus Redis-Timestamp initialisieren. |
| 71 | NIEDRIG | response_quality.py | 207 | Logic | **`if total == 0: return False` unerreichbar.** Dead Code. | Zeile entfernen. |

---

## Bug-Report: Batch 9 — Resilience & Tracking (intent_tracker.py, outcome_tracker.py, error_patterns.py, circuit_breaker.py, conflict_resolver.py, adaptive_thresholds.py, threat_assessment.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 72 | MITTEL | conflict_resolver.py | 146 | Race Condition | **`_recent_commands` ohne Lock.** `_cleanup_old_commands()` kann waehrend Iteration Keys loeschen. | `asyncio.Lock`. |
| 73 | MITTEL | conflict_resolver.py | 311 | Silent Error | **`create_task` ohne Referenz.** Task kann vom GC eingesammelt werden. | Task in Set speichern. |
| 74 | MITTEL | outcome_tracker.py | 57 | Race Condition | **`_pending_count` ohne Lock.** Parallele `track_action()` → inkonsistenter Zaehler. | `asyncio.Lock` oder Redis INCR/DECR. |
| 75 | MITTEL | threat_assessment.py | 81 | API | **`get_states()` ohne Timeout.** Haengender HA-Server blockiert gesamte Threat-Loop. | `asyncio.wait_for(..., timeout=15)` |
| 76 | MITTEL | threat_assessment.py | 96 | Logic | **Doppelte Weather-Logik.** `_check_storm_windows()` liest Wind selbst, obwohl `assess_threats()` bereits `weather_ctx` hat. | `weather_ctx` als Parameter uebergeben. |
| 77 | NIEDRIG | circuit_breaker.py | 44-109 | Race Condition | **State-Mutation in Property.** `state` Property mutiert `_state` als Seiteneffekt. | Seiteneffekt in `try_acquire`. |
| 78 | NIEDRIG | threat_assessment.py | 37 | Config | **`security_cfg.get("threat_assessment", True)`** — wenn Wert ein Dict ist, greift `if not self.enabled` nie. | `bool()` Konvertierung. |
| 79 | NIEDRIG | threat_assessment.py | 100-101 | Performance | **Dreifach-redundante States-Iteration.** Jeder Sub-Check filtert komplett. | Einmalig filtern, Ergebnisse uebergeben. |
| 80 | NIEDRIG | adaptive_thresholds.py | 54 | Race Condition | **`_adjustments_this_week` ohne Lock.** Parallele `run_analysis()` umgeht Rate-Limit. | `asyncio.Lock`. |
| 81 | NIEDRIG | adaptive_thresholds.py | 242-253 | Security | **`_set_runtime_value()` schreibt beliebige yaml_config-Pfade.** Aktuell sicher (hardcoded Bounds). | Methode privat halten, Pfade gegen Allowlist validieren. |
| 82 | NIEDRIG | intent_tracker.py | 300-301 | Data | **`hgetall()` bytes-Keys.** `.get("intent_id")` liefert `None` da Keys `b"intent_id"`. | Keys dekodieren. |
| 83 | NIEDRIG | outcome_tracker.py | 200-202 | Data | **`key.split(":")` auf bytes.** `bytes.split()` braucht `b":"`. | Keys dekodieren. |
| 84 | NIEDRIG | error_patterns.py | 87 | Logic | **Redundanter `int()` Cast** und verwirrende `max()`-Logik. | Saubere if/elif-Logik. |

---

## Bug-Report: Batch 10 — Config & Domain (config.py, constants.py, config_versioning.py, cooking_assistant.py, recipe_store.py, music_dj.py, smart_shopping.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 85 | KRITISCH | recipe_store.py | 53-65 | Async/Blocking | **Synchrone ChromaDB-Calls in async-Methoden.** `HttpClient()`, `get_or_create_collection()`, `count()` blockieren Event-Loop. | `asyncio.to_thread()` oder async ChromaDB Client. |
| 86 | KRITISCH | recipe_store.py | 92-338 | Async/Blocking | **Saemtliche `chroma_collection.*` Aufrufe synchron.** `get()`, `add()`, `query()`, `count()`, `delete()` — ~15 Call-Sites blockieren. | Alle in `asyncio.to_thread()` wrappen. |
| 87 | HOCH | recipe_store.py | 101-113 | Performance | **`ingest_all()` sequentiell** ueber alle Dateien. | `asyncio.gather()` oder Batching. |
| 88 | HOCH | config.py | 319 | Race Condition | **`get_room_profiles()` TOCTOU.** Cache-Check vor Lock, Cache-Write unter Lock — inkonsistenter Read moeglich. | Gesamten Check unter Lock. |
| 89 | HOCH | config_versioning.py | 133 | Logic | **`rsplit("_", 2)` bei Config-Namen mit Unterstrich.** `"easter_eggs_20260310_120000"` → `[0]` = `"easter"` statt `"easter_eggs"`. Rollbacks fuer solche Configs schlagen fehl. | Config-Name aus Redis-Metadaten lesen statt aus ID parsen. |
| 90 | HOCH | cooking_assistant.py | 891 | Data | **Redis `get()` gibt bytes.** `json.loads(raw)` funktioniert, aber inkonsistent mit explizitem `.decode()` Pattern. | Konsistentes `.decode()`. |
| 91 | MITTEL | music_dj.py | 383-384 | Silent Error | **`except Exception: pass`** beim Redis-Load der letzten Empfehlung. | `logger.debug()`. |
| 92 | MITTEL | music_dj.py | 116-117 | Silent Error | **`except Exception: return "relaxing"`** ohne Logging in `_get_activity()`. | `logger.debug()`. |
| 93 | MITTEL | config_versioning.py | 195-196 | Silent Error | **`except (...): pass`** beim Snapshot-Loeschen. Redis-Metadaten weg, Datei bleibt als Orphan. | Loggen. |
| 94 | MITTEL | smart_shopping.py | 175 | Data | **`hgetall()` bytes-Keys.** Keys nicht dekodiert (Values schon). | Keys dekodieren. |
| 95 | MITTEL | smart_shopping.py | 389-391 | Silent Error | **`except Exception: pass`** beim Einkaufslisten-Load. HA-API-Fehler unsichtbar. | `logger.debug()`. |
| 96 | MITTEL | config.py | 241-247 | Race Condition | **`_active_person` ohne Lock.** In Multi-Thread FastAPI-Kontext fragwuerdig. | `threading.Lock`. |
| 97 | NIEDRIG | cooking_assistant.py | 102 | Logic | **Doppelter Eintrag** `"ich möchte"` in `COOKING_START_TRIGGERS`. | Duplikat entfernen. |
| 98 | NIEDRIG | recipe_store.py | 141 | Security | **MD5 fuer Content-Hashing.** Funktional OK, aber deprecated. | `hashlib.sha256`. |

---

## Bug-Report: Batch 11 — Domain (calendar_intelligence.py, inventory.py, web_search.py, knowledge_base.py, summarizer.py, ocr.py, file_handler.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 99 | KRITISCH | knowledge_base.py | 71-550 | Async/Blocking | **Alle ChromaDB-Calls synchron in async-Methoden.** `get_or_create_collection()`, `.count()`, `.get()`, `.add()`, `.query()`, `.upsert()`, `.delete()` — ~14 Call-Sites blockieren Event-Loop. | `asyncio.to_thread()` oder `chromadb.AsyncHttpClient`. |
| 100 | KRITISCH | summarizer.py | 275, 391 | Async/Blocking | **`chroma_collection.query()` und `.upsert()` synchron** in async-Methoden. | `run_in_executor()`. |
| 101 | HOCH | summarizer.py | 322-323 | Data | **Redis `scan()` gibt bytes-Keys.** `key.replace("mha:summary:daily:", "")` schlaegt fehl auf bytes. | `.decode()`. |
| 102 | HOCH | summarizer.py | 407 | Data | **`redis.get()` gibt bytes, Rueckgabetyp ist `str`.** `_store_personality_snapshot()` Z.494: `bytes + str` → `TypeError`. | `.decode()`. |
| 103 | HOCH | summarizer.py | 469-471 | Data/None | **`int(b"42" or 0)` → `TypeError`.** Redis bytes + or-Pattern fehlerhaft. | `raw = await ...; val = int(raw) if raw else 0` mit decode. |
| 104 | HOCH | summarizer.py | 476 | Data | **`float(v)` auf bytes** aus `redis.lrange()`. `TypeError`. | `.decode()` vor `float()`. |
| 105 | HOCH | summarizer.py | 315 | Data | **Bytes-Keys sortiert, dann `.replace()` mit str-Argument.** | Nach Scan alle Keys decodieren. |
| 106 | MITTEL | knowledge_base.py | 330-331 | Performance | **Multi-Query sequentiell.** Jeder ChromaDB-Call blockiert. | `asyncio.gather()` nach async-Umstellung. |
| 107 | MITTEL | knowledge_base.py | 200-205 | Performance | **`ingest_all()` sequentiell** ueber Dateien. | `asyncio.gather()` oder Batching. |
| 108 | MITTEL | summarizer.py | 199-204 | Performance | **7 sequentielle Redis-Calls** in `summarize_week()`. | `asyncio.gather()`. |
| 109 | MITTEL | summarizer.py | 243-251 | Performance | **Bis zu 31 sequentielle Redis-Calls** in `summarize_month()`. | `asyncio.gather()`. |
| 110 | NIEDRIG | inventory.py | 99-111 | Performance | **O(n) Suche** ueber alle Items mit einzelnen `hgetall`-Calls. | Sekundaer-Index in Redis. |
| 111 | NIEDRIG | web_search.py | 329-332 | Race Condition | **Cache-Eviction nicht atomar.** In asyncio akzeptabel. | `asyncio.Lock` optional. |

---

## Bug-Report: Batch 12 — Monitoring (workshop_library.py, workshop_generator.py, health_monitor.py, device_health.py, energy_optimizer.py, predictive_maintenance.py, repair_planner.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 112 | KRITISCH | workshop_library.py | 40-43 | Async/Blocking | **Synchrone ChromaDB-Calls** in `initialize()`. | `asyncio.to_thread()`. |
| 113 | KRITISCH | workshop_library.py | 88-92 | Async/Blocking | **`collection.upsert()` synchron** in `ingest_document()`. | `asyncio.to_thread()`. |
| 114 | KRITISCH | workshop_library.py | 103-116 | Async/Blocking | **`collection.count()` und `.query()` synchron** in `search()`. | `asyncio.to_thread()`. |
| 115 | KRITISCH | workshop_library.py | 148 | Async/Blocking | **`collection.count()` synchron** in `get_stats()`. | `asyncio.to_thread()`. |
| 116 | HOCH | health_monitor.py | 361 | Data | **`redis.get()` bytes an `fromisoformat()`.** `TypeError`. | `.decode()`. |
| 117 | HOCH | device_health.py | 414-416 | Data | **`hgetall()` bytes-Keys.** `.get("mean", 0)` matched nie. Anomalie-Erkennung greift nie. | Keys/Values dekodieren. |
| 118 | HOCH | device_health.py | 459 | Data | **`float(s)` auf bytes** aus `lrange()`. `TypeError`. | `.decode()`. |
| 119 | HOCH | device_health.py | 361 | Data | **`start_raw.replace("Z", "+00:00")` auf bytes.** `AttributeError`. | Dekodieren vor Verarbeitung. |
| 120 | HOCH | repair_planner.py | 299-304 | Data | **`hgetall()` bytes-Keys.** JSON-Felder werden nie korrekt geparsed. | Vorher dekodieren. |
| 121 | HOCH | repair_planner.py | 334 | Data | **`hget()` bytes.** `srem()` mit bytes vs String-Key — alter Status nie entfernt. | `.decode()`. |
| 122 | HOCH | repair_planner.py | 1137 | Data | **`hgetall()` bytes-Dicts** direkt in Ergebnis-Liste. | Dekodieren. |
| 123 | HOCH | repair_planner.py | 989-990 | Data | **`hgetall()` bytes** in `list_workshop()`. | Dekodieren. |
| 124 | HOCH | repair_planner.py | 1025-1026 | Data | **`hgetall()` bytes.** `.get("last_done")` matched nie, faellt auf Defaults. | Dekodieren. |
| 125 | HOCH | repair_planner.py | 1509-1510 | Data | **`lrange()` bytes** in `get_journal()`. | Dekodieren. |
| 126 | HOCH | repair_planner.py | 1543 | Data | **`hgetall()` bytes** in `get_snippet()`. | Dekodieren. |
| 127 | HOCH | workshop_generator.py | 553-554 | Data | **`lrange()` bytes.** `Path(fn).name` auf bytes → falscher Pfad. | `.decode()`. |
| 128 | MITTEL | workshop_library.py | 87 | Async/Performance | **Embedding-Funktion sequentiell pro Chunk.** Falls async, fehlt `await`. | Pruefen ob async; batch-embedden. |
| 129 | MITTEL | workshop_library.py | 107 | Async | **`embedding_fn(query)` moeglicherweise async** ohne `await`. | `await` falls async. |
| 130 | MITTEL | energy_optimizer.py | 291-299 | Performance | **7 sequentielle `redis.get()` Calls.** | `mget()`. |
| 131 | MITTEL | energy_optimizer.py | 333-356 | Performance | **14 sequentielle `redis.get()` Calls.** | `mget()`. |
| 132 | MITTEL | repair_planner.py | 322-326 | Performance | **N sequentielle `hgetall()` Calls** in `list_projects()`. | `asyncio.gather()` oder Pipeline. |
| 133 | MITTEL | repair_planner.py | 1629-1636 | Performance | **N `ha.get_states()` Calls** in `check_all_devices()`. | Einmal cachen. |

---

## Bug-Report: Batch 13 — Rest (visitor_manager.py, follow_me.py, wellness_advisor.py, activity.py, seasonal_insight.py, explainability.py, diagnostics.py, task_registry.py, timer_manager.py)

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|----------|-------|-------|-------------|-------------|-----|
| 134 | KRITISCH | wellness_advisor.py | 237, 245 | Data | **`redis.get()` bytes an `fromisoformat()`.** `TypeError` wird gefangen → Timer resetten bei jedem Check. PC-Pause-Erinnerung wird **NIE** ausgeloest. | `.decode()`. |
| 135 | KRITISCH | wellness_advisor.py | 330, 333 | Data | **Bytes an `fromisoformat()`.** Cooldown greift nie → Stress-Nudges bei **JEDEM** Check-Interval. | `.decode()`. |
| 136 | KRITISCH | wellness_advisor.py | 629, 631-633 | Data | **Bytes an `fromisoformat()`.** Cooldown greift nie → Hydration-Erinnerungen alle 15 Min statt alle 2h. | `.decode()`. |
| 137 | HOCH | wellness_advisor.py | 690, 693-694 | Data | **Bytes an `fromisoformat()`.** Cooldown greift nie → Ambient-Aktionen alle 15 Min statt alle 30 Min. | `.decode()`. |
| 138 | HOCH | wellness_advisor.py | 256, 259 | Data | **Bytes an `fromisoformat()`.** 1h-Cooldown fuer Break-Erinnerungen ignoriert. | `.decode()`. |
| 139 | HOCH | task_registry.py | 94, 117 | Init/Logic | **`shutdown(timeout=...)` Parameter ignoriert.** Hardcoded `timeout=30` statt Parameter. | `timeout=timeout`. |
| 140 | MITTEL | wellness_advisor.py | 186-190 | Performance | **5 Wellness-Checks sequentiell.** Jeder macht HA + Redis Calls. | `asyncio.gather()`. |
| 141 | MITTEL | follow_me.py | 125-146 | Performance | **3 Transfers sequentiell** (Music, Lights, Climate). Unabhaengig. | `asyncio.gather()`. |
| 142 | MITTEL | diagnostics.py | 585-604 | Performance | **5 Diagnostik-Checks sequentiell.** | `asyncio.gather()`. |
| 143 | MITTEL | diagnostics.py | 501-555 | Performance | **5 Connectivity-Checks sequentiell.** Bei Timeouts bis 25s. | `asyncio.gather()`. |
| 144 | NIEDRIG | explainability.py | 55-58 | Silent Error | **`json.JSONDecodeError` mit `pass`.** Korrupte Eintraege still uebersprungen. | `logger.debug()`. |
| 145 | NIEDRIG | timer_manager.py | 699, 749 | Silent Error | **`except Exception: pass`** bei Alarm-Cancel. Redis-Wecker ueberlebt Cancel. | Loggen + Fehlerstatus melden. |

---

## Spezifische Pruefpunkte (aus Prompt)

### Protocol Engine: "5 Bugs dokumentiert — Alle gefixt?"
Die groebsten Bugs (Race Conditions, bytes-Decoding) scheinen gefixt. **Verbleibend:** stille Fehler beim Undo (Bug #26-27), zu breite Intent-Detection (Bug #28), inkonsistente Timestamps (Bug #25).

### Insight Engine: "70% fertig — Was fehlt?"
1. `run_checks_now()` fehlen 6 von 16 Checks (Bug #65)
2. Keine Persistierung der Check-Ergebnisse in Redis
3. Keine Wochen-Trends (nur 6 Snapshots a 30min)
4. Temperatur-Snapshots nicht raumbezogen
5. Kein konsistentes Health-Interface

### Circuit Breaker: "Wird es genutzt?"
**JA** — aktiv genutzt von `ha_client.py` (`ha_breaker`, `mindhome_breaker`), `ollama_client.py` (`ollama_breaker`), `brain.py` (`registry`), `main.py` (`registry`).
**Dead Code:** `redis_breaker`, `chromadb_breaker`, `call_with_breaker()` — definiert aber nie importiert.

### Threat Assessment: "Funktioniert es?"
**JA** — voll integriert. Initialisiert in `brain.py`, periodisch aufgerufen von `proactive.py`, Security-Score abrufbar via `function_calling.py`.

---

## Dead-Code-Liste

| Modul | Element | Beschreibung |
|-------|---------|-------------|
| circuit_breaker.py | `redis_breaker` (Z.170) | Definiert, nie importiert |
| circuit_breaker.py | `chromadb_breaker` (Z.171) | Definiert, nie importiert |
| circuit_breaker.py | `call_with_breaker()` (Z.174-202) | Definiert, nie aufgerufen |
| proactive_planner.py | `_GUEST_KEYWORDS` (Z.30-33) | Definiert, nie verwendet |
| proactive_planner.py | `import time` (Z.16) | Importiert, nie verwendet |
| proactive.py | `_get_person_title()` (Z.2130) | Dupliziert globale Funktion |
| light_engine.py | `on_motion_clear()` (Z.211-213) | Leere Methode (`pass`) |
| light_engine.py | `_is_morning_window()` (Z.911-917) | Nie aufgerufen, Logic inline |
| ha_client.py | `_get_lock()` (Z.57-59) | Triviale Wrapper-Methode |
| cover_config.py | `get_sensors_by_role()` | Nie aufgerufen |
| tts_enhancer.py | 9 Instance-Variablen (Z.153-166) | `vol_day`, `vol_evening`, etc. — `get_volume()` liest live aus yaml_config |
| sound_manager.py | `settings` Import (Z.29) | Importiert, nie verwendet |
| ambient_audio.py | `settings` Import (Z.33) | Importiert, nie verwendet |
| calendar_intelligence.py | `hour_activity` Counter (Z.145-158) | Befuellt, nie gelesen |
| web_search.py | `quote_plus` Import (Z.37) | Importiert, nie verwendet |
| file_handler.py | `import re` (Z.8) | Importiert, nie verwendet |
| health_monitor.py | `_check_temperature()` (Z.314-328) | Methode existiert, Aufruf auskommentiert |
| predictive_maintenance.py | 3 Redis-Key-Konstanten (Z.27-29) | Definiert, nie verwendet |
| smart_shopping.py | `_KEY_PURCHASE_LOG` (Z.29) | Definiert, nie verwendet |
| cooking_assistant.py | `CookingSession.raw_recipe` (Z.84) | Gesetzt, nie gelesen |
| seasonal_insight.py | `import time` + `Counter, defaultdict` (Z.17) | Importiert, nie verwendet |
| visitor_manager.py | `self.auto_guest_mode` (Z.54) | Gesetzt, nie verwendet |
| diagnostics.py | `import os` (Z.19) | Importiert, nie verwendet |
| wellness_advisor.py | `self.executor` (Z.42) | Immer `None`, Mood-Ambient-Feature dadurch tot |
| response_quality.py | `if total == 0` Check (Z.207) | Unerreichbar |

---

## Fehlerklassen-Verteilung

| Fehlerklasse | Anzahl | Kritischste |
|---|:---:|---|
| 1. Async/Blocking (ChromaDB) | 12 | knowledge_base.py, recipe_store.py, workshop_library.py, summarizer.py |
| 2. Stille Fehler (except:pass) | 22 | multi_room_audio.py gibt `success:True` bei Fehler (#42) |
| 3. Race Conditions | 10 | self_automation.py `_pending` + Rate-Limit (#5, #6) |
| 4. None-Fehler | 5 | proactive.py `getattr` falscher Attributname (#7) |
| 5. Init-Fehler | 2 | proactive.py `event_handlers` vor Definition (#1) |
| 6. API-Fehler (Timeout) | 3 | ha_client.py Camera, self_automation.py Ollama |
| 7. Daten-Fehler (bytes/str) | 42 | wellness_advisor.py — KEIN Cooldown funktioniert (#134-136) |
| 8. Config-Fehler | 1 | threat_assessment.py bool vs Dict (#78) |
| 9. Memory Leaks | 3 | learning_transfer.py `_pending_transfers` (#60) |
| 10. Logik-Fehler | 14 | proactive.py Operator-Praezedenz (#2) |
| 11. Security | 3 | self_automation.py Prompt Injection (#4) |
| 12. Resilience | 7 | ha_client.py fehlende Retries (#23) |
| 13. Performance | 19 | summarizer.py 31 sequentielle Redis-Calls (#109) |

---

## KONTEXT AUS PROMPT 4b: Bug-Report (Extended-Module)

### Statistik
Gesamt: 155 Bugs in Prioritaet 5-9 (KRITISCH 12, HOCH 39, MITTEL 58, NIEDRIG 46)

### Kritische Bugs (12)
1. `proactive.py:108` — Init: `event_handlers` gelesen vor Definition, crasht ProactiveManager
2. `recipe_store.py:53-338` — Alle ChromaDB-Calls synchron in async-Methoden (~15 Sites)
3. `knowledge_base.py:71-550` — Alle ChromaDB-Calls synchron in async-Methoden (~14 Sites)
4. `summarizer.py:275,391` — ChromaDB query/upsert synchron in async
5. `workshop_library.py:40-148` — Alle ChromaDB-Calls synchron (~6 Sites)
6. `wellness_advisor.py:237,245` — Redis bytes an fromisoformat, PC-Pause-Erinnerung funktioniert NIE
7. `wellness_advisor.py:330,333` — Redis bytes, Stress-Nudge-Cooldown greift nie
8. `wellness_advisor.py:629,631` — Redis bytes, Hydration-Cooldown greift nie

### Hohe Bugs (39) — Top-10
- `proactive.py:594` — Operator-Praezedenz: alle proximity-Entities loesen Geo-Fence aus
- `self_automation.py:449` — User-Beschreibung unsanitized in LLM-Prompt
- `self_automation.py:103,996` — Race Conditions auf _pending und _daily_count
- `ha_client.py:53-90` — States-Cache Race Condition
- `ha_client.py:140-165` — Camera Snapshot ohne Timeout/Retry
- `repair_planner.py` — 8 Stellen mit undekodiertem Redis bytes
- `device_health.py` — 3 Stellen mit undekodiertem Redis bytes
- `summarizer.py` — 5 Stellen mit undekodiertem Redis bytes
- `config_versioning.py:133` — rsplit bei Config-Namen mit Unterstrich
- `feedback.py:84` — Race Condition auf _pending dict

### Dead-Code-Liste
- `circuit_breaker.py`: `redis_breaker`, `chromadb_breaker`, `call_with_breaker()` — nie importiert
- `wellness_advisor.py`: `self.executor` immer None → Mood-Ambient-Feature tot
- `health_monitor.py`: `_check_temperature()` — Aufruf auskommentiert
- `tts_enhancer.py`: 9 Instance-Variablen — `get_volume()` liest live aus yaml_config
- 25 weitere Dead-Code-Eintraege (Imports, Konstanten, Methoden)

### Resilience-Findings
- `ha_client.py`: PUT/DELETE ohne Retry, Camera ohne Circuit-Breaker-Reporting bei HTTP-Fehlern
- `multi_room_audio.py`: 5 stille except-Bloecke, gibt success:True bei Fehlern
- `protocol_engine.py`: Undo meldet Erfolg trotz fehlgeschlagener Schritte
- `self_automation.py`: Ollama-Chat ohne Timeout
- `threat_assessment.py`: get_states() ohne Timeout

### Systemisches Problem: Redis bytes vs string
42 von 155 Bugs (27%) sind Redis bytes/string-Inkonsistenzen. **Globaler Fix**: Redis-Client mit `decode_responses=True` konfigurieren wuerde alle 42 Bugs auf einen Schlag beheben.
