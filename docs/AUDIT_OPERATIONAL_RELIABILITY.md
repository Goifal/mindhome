# Jarvis Assistant - Betriebsstoerungsanalyse

> Datum: 2026-02-28
> Umfang: 14 Module, 65+ Findings
> Analysierte Dateien: brain.py, main.py, proactive.py, routine_engine.py, memory.py, semantic_memory.py, function_calling.py, function_validator.py, ollama_client.py, model_router.py, circuit_breaker.py, error_patterns.py, self_automation.py, self_optimization.py

---

## KRITISCH (Sofortiger Handlungsbedarf)

### K1: Singleton Brain -- Shared Mutable State bei gleichzeitigen Requests
**Datei:** `assistant/brain.py` (Zeilen 688, 695, 286, 808, 3421, 733, 3341, 2048, 2123)

`AssistantBrain` ist ein Singleton. Per-Request-State wird als Instanz-Attribute gespeichert:
- `self._request_from_pipeline` (Zeile 688)
- `self._current_person` (Zeile 695)
- `self._last_failed_query` (Zeile 286/808)
- `self._last_response_was_snarky` (Zeile 3421)
- `self._last_humor_category` (Zeile 733)
- `self._last_executed_action` (Zeile 3341)
- `self._last_context` (Zeile 2048)
- `self._last_formality_score` (Zeile 2123)

Bei gleichzeitigen Requests (Pipeline + Web-UI, zwei Nutzer) ueberschreiben sich die Werte gegenseitig.

**Auswirkung:** Falsche TTS-Routierung (doppelt oder stumm), Sicherheitsbestaetigung der falschen Person zugeordnet, falsche Persoenlichkeitsanpassung.

**Fix:** Per-Request-State in ein `RequestContext`-Dataclass kapseln und als Parameter durch die gesamte `process()`-Pipeline durchreichen statt als `self.*`-Attribute.

### K2: Timezone-naive datetime-Vergleiche mit HA UTC-Timestamps
**Datei:** `assistant/brain.py` (Zeile 553-574, `_get_occupied_room`)
**Auch:** `proactive.py` (Zeilen 160, 481, 576, 2999), `routine_engine.py`, `error_patterns.py`

```python
now = datetime.now()  # Lokale Zeit (naive)
changed = datetime.fromisoformat(last_changed.replace("Z", "+00:00")).replace(tzinfo=None)  # UTC stripped!
```

HA liefert UTC-Timestamps. `datetime.now()` liefert lokale Zeit. In UTC+1/+2 (DE) ist die Differenz immer um 1-2 Stunden falsch.

**Auswirkung:** Raumerkennung systematisch fehlerhaft -- TTS geht an falschen Lautsprecher oder keinen. Morgen-Briefing-Fenster um 1-2h verschoben. Cover-Automatik timing falsch.

**Fix:** Durchgehend `datetime.now(timezone.utc)` verwenden ODER Timestamps korrekt in lokale Zeit konvertieren mit `ZoneInfo("Europe/Berlin")`.

### K3: ChromaDB `get_all_episodes` laedt komplette Collection in RAM
**Datei:** `assistant/memory.py` (Zeile 393)

```python
self.chroma_collection.get(include=["documents", "metadatas"])  # ALLES
```

Nach Monaten/Jahren waechst die Collection unbegrenzt. Jeder Aufruf allokiert die gesamte Datenmenge.

**Auswirkung:** OOM-Kill des Assistenten nach laengerem Betrieb.

**Fix:** Pagination einfuehren (`limit`/`offset` Parameter), oder nur IDs+Metadaten laden und Dokumente lazy nachladen.

### K4: Synchrone ChromaDB-Aufrufe blockieren den asyncio Event Loop
**Dateien:** `assistant/memory.py` (Zeilen 171, 249, 393, 422), `assistant/semantic_memory.py` (viele Stellen)

`chromadb.HttpClient` ist synchron. Jeder `add()`, `query()`, `get()`, `delete()` Aufruf blockiert den gesamten Event Loop.

**Auswirkung:** Bei Last friert die gesamte Request-Verarbeitung ein. Ein langsamer ChromaDB-Query blockiert alle parallelen Anfragen.

**Fix:** ChromaDB-Calls in `asyncio.to_thread()` wrappen.

---

## HOCH (Sollte zeitnah behoben werden)

### H1: Anonyme User koennen Sicherheitsaktionen bestaetigen
**Datei:** `assistant/brain.py` (Zeilen 5276-5282)

```python
if pending.get("person") and person and pending["person"] != person:
    return None
```

Wenn `person` leer ist (nicht identifiziert), greift der Check nicht. Ein Gast sagt "Ja" und bestaetigt eine Tuerentriegelung des Besitzers.

**Fix:** Wenn `person` leer ist, Sicherheitsbestaetigungen ablehnen: `if not person: return None` als erste Pruefung.

### H2: WebSocket Streaming -- `UnboundLocalError` nach Exception
**Datei:** `assistant/main.py` (Zeilen 1583-1615)

Im Streaming-Pfad: wenn `brain.process()` eine Exception wirft, wird `result` nie zugewiesen. Zeile 1615 (`result.get("actions", [])`) crasht mit `UnboundLocalError`.

**Auswirkung:** WebSocket-Verbindung bricht ab bei jedem Streaming-Fehler.

**Fix:** `result = {}` vor dem try-Block initialisieren, oder nach Exception-Handler `continue` zum naechsten Message.

### H3: Gleichzeitige YAML-Writes korrumpieren `settings.yaml`
**Datei:** `assistant/main.py` (Zeilen 502-511, 1714-1725, 1946-1950, 1965-1969, 2000-2004)

Mehrere Endpoints lesen-modifizieren-schreiben `settings.yaml` ohne Lock oder atomaren Write.

**Auswirkung:** Config-Verlust wenn zwei API-Calls gleichzeitig Settings aendern.

**Fix:** `asyncio.Lock` fuer alle YAML-Writes + atomares Schreiben (temp-Datei + `os.replace()`).

### H4: Vacuum-Tasks werden bei `stop()` nicht gecancelled
**Datei:** `assistant/proactive.py` (Zeilen 216-255 vs 188-199)

`_vacuum_task`, `_vacuum_power_task`, `_vacuum_scene_task` werden in `start()` erstellt, aber `stop()` cancelt sie nicht.

**Auswirkung:** Hintergrund-Tasks laufen nach Shutdown weiter und interagieren mit bereits abgebauten Ressourcen.

**Fix:** Alle drei Tasks in `stop()` canceln wie die anderen Tasks.

### H5: Self-Optimization schreibt Config aber laedt Runtime nicht neu
**Datei:** `assistant/self_optimization.py` (Zeilen 357-385)

`_apply_parameter()` schreibt nach `settings.yaml`, aber `yaml_config` im Speicher wird nie aktualisiert.

**Auswirkung:** Parameter-Aenderungen haben keinen Effekt bis zum naechsten Neustart. Nutzer denkt es funktioniert.

**Fix:** Nach dem Schreiben `yaml_config` aktualisieren oder Config-Reload triggern.

### H6: Rate-Limit Reset bei jedem Neustart
**Datei:** `assistant/self_automation.py` (Zeilen 96-101, 988-1015)

`_daily_reset` ist nach Init `None`. Erster Aufruf von `_check_rate_limit()` sieht `None` und setzt `_daily_count` auf 0 zurueck -- obwohl gerade der gespeicherte Wert aus Redis geladen wurde.

**Auswirkung:** Automations-Ratelimit greift nie nach einem Neustart. Theoretisch unbegrenzt viele Automationen pro Tag moeglich.

**Fix:** `_daily_reset` beim Laden aus Redis auf `datetime.now()` setzen.

### H7: Keine Supervision fuer Hintergrund-Tasks
**Datei:** `assistant/proactive.py` (Zeilen 168-214)

9+ Background-Tasks (`_listen_ha_events`, `_run_diagnostics_loop`, `_run_batch_loop`, etc.) werden als `asyncio.Task` erstellt, aber nie ueberwacht. Kein `done_callback`, kein Health-Check.

**Auswirkung:** Ein gestorbener Task (z.B. Diagnostics-Loop) bleibt unbemerkt. System laeuft scheinbar normal aber Funktionalitaet fehlt.

**Fix:** `done_callback` auf allen Tasks registrieren der den Task-Tod loggt und optional neu startet. Health-Endpoint erweitern um Task-Liveness.

### H8: Operator-Precedence Bug in Geo-Fence Entity Matching
**Datei:** `assistant/proactive.py` (Zeile 429)

```python
entity_id.startswith("proximity.") or entity_id.startswith("sensor.") and "distance" in entity_id
```

`and` bindet staerker als `or`. ALLE `proximity.*` Entities matchen, nicht nur distance-relevante.

**Fix:** Klammern setzen: `entity_id.startswith("proximity.") or (entity_id.startswith("sensor.") and "distance" in entity_id)`

### H9: entity_id-Validation nur fuer `target`-Dict, nicht fuer `data`
**Datei:** `assistant/self_automation.py` (Zeilen 709-717)

Validation prueft nur `target.entity_id`. HA akzeptiert `entity_id` auch in `data` oder auf Action-Ebene. Ausserdem: wenn `entity_id` eine Liste ist (HA-Feature), schlaegt `match()` fehl.

**Fix:** Alle entity_id-Felder pruefen (`target`, `data`, Action-Level). Listen-Support einbauen.

---

## MITTEL (Beeintraechtigt Zuverlaessigkeit)

### M1: Morning Briefing Race -- kann mehrfach am Tag ausloesen
**Datei:** `assistant/proactive.py` (Zeilen 486-552)

`_mb_triggered_today` wird ohne Lock geprueft/gesetzt. Mehrere Motion-Events gleichzeitig koennen mehrere Briefings triggern.

**Fix:** `_state_lock` verwenden oder ein einmaliges Redis-Flag setzen.

### M2: Absence-Log wird geloescht auch wenn LLM-Zusammenfassung fehlschlaegt
**Datei:** `assistant/routine_engine.py` (Zeilen 1173-1238)

Log wird immer geloescht (Zeile 1238), auch nach LLM-Fehler. Events gehen verloren.

**Fix:** Loeschung nur nach erfolgreicher Zusammenfassung.

### M3: Redis `bytes` nicht decodiert vor String-Operationen
**Dateien:** `routine_engine.py` (Zeilen 557-558, 617-618), `self_optimization.py` (Zeile 91-98)

`redis.asyncio` kann `bytes` zurueckgeben. `.startswith(today)` oder `fromisoformat()` auf `bytes` wirft TypeError.

**Fix:** Konsistente `.decode()` vor String-Operationen, oder `decode_responses=True` im Redis-Client.

### M4: Kein Timeout auf LLM-Calls in Routinen
**Datei:** `routine_engine.py` (Zeilen 153-159, 1010-1017, 1223-1231)

`self.ollama.chat()` ohne Timeout. Wenn Ollama haengt, blockiert Morning Briefing / Gute-Nacht / Absence-Summary den gesamten Event-Verarbeitungspipeline.

**Fix:** `asyncio.wait_for(self.ollama.chat(...), timeout=30.0)` mit Fallback-Text.

### M5: WebSocket Non-Streaming Pfad ohne Timeout
**Datei:** `assistant/main.py` (Zeilen 1608-1612)

HTTP-Endpoint hat 60s Timeout (`asyncio.wait_for`), WebSocket nicht.

**Fix:** `asyncio.wait_for(brain.process(...), timeout=60.0)` auch im WebSocket-Pfad.

### M6: `_batch_queue` waechst unbegrenzt waehrend Quiet Hours
**Datei:** `assistant/proactive.py` (Zeilen 1889-1893)

Flush wird unterdrueckt, aber neue Items werden weiter hinzugefuegt.

**Fix:** Max-Queue-Size definieren, aelteste Items verwerfen wenn Limit erreicht.

### M7: Quiet-Hours-Logik in Ambient Presence fehlerhaft fuer nicht-wrappende Bereiche
**Datei:** `assistant/proactive.py` (Zeilen 2999-3002)

`quiet_start <= hour or hour < quiet_end` ist falsch wenn der Bereich Mitternacht nicht ueberschreitet.

**Fix:** Gleiche Logik wie `_is_quiet_hours()` verwenden (prueft ob start > end).

### M8: `_pending` Automations nie automatisch bereinigt
**Datei:** `assistant/self_automation.py` (Zeilen 204-210, 386-397)

Cleanup nur bei Zugriff, kein Timer. Dict waechst unbegrenzt wenn niemand interagiert.

**Fix:** Periodischen Cleanup-Task einrichten oder TTL-basierte Bereinigung bei jeder `generate_automation()`.

### M9: `_tasks` Dict in TaskRegistry waechst unbegrenzt (Memory Leak)
**Datei:** `assistant/task_registry.py`

Abgeschlossene Tasks werden nie aus `_tasks` entfernt. Ueber Tage/Wochen sammeln sich Tausende Eintraege.

**Fix:** `_on_task_done` Callback um Cleanup erweitern: abgeschlossene Tasks nach kurzer Verzoegerung entfernen.

### M10: Distributed Lock in semantic_memory nutzt nicht-deterministisches `hash()`
**Datei:** `assistant/semantic_memory.py` (Zeile 149)

Python `hash()` ist per-Prozess randomisiert (seit 3.3). Cross-Process-Lock wirkungslos.

**Fix:** `hashlib.md5(fact.content.encode()).hexdigest()[:12]` verwenden.

### M11: ChromaDB/Redis Split-Brain bei partiellem Write-Fehler
**Datei:** `assistant/semantic_memory.py` (Zeilen 186-218)

ChromaDB `add()` erfolgreich, Redis `hset/sadd` fehlgeschlagen = Fact in Suche findbar, aber nicht in `get_all_facts()`.

**Fix:** Transaktion: bei Redis-Fehler ChromaDB-Eintrag wieder loeschen (Compensation).

### M12: Substring-Keyword-Matching misrouted Queries zum falschen Modell
**Datei:** `assistant/model_router.py` (Zeilen 215-227)

`"an"` matched in "kann", "wann", "plan". `"aus"` matched in "ausfuehrlich". Kurze Queries werden faelschlich zum schnellen 3B-Modell geroutet.

**Fix:** Word-Boundary-Matching verwenden: `re.search(r'\b' + keyword + r'\b', text_lower)`.

### M13: Validator mutiert Input-Argumente in-place
**Datei:** `assistant/function_validator.py` (Zeilen 141-143)

`_validate_set_light` aendert `args["state"]` und loescht `args["brightness"]` direkt im uebergebenen Dict.

**Fix:** Auf einer Kopie arbeiten (`args = dict(args)`) oder Mutation in den Executor verschieben.

### M14: Duplicate Audit-Log-Funktion ohne Rotation in brain.py
**Dateien:** `brain.py` (Zeile 99/106), `main.py` (Zeile 1871/1877)

Beide definieren `_AUDIT_LOG_PATH` und `_audit_log()`. brain.py-Version hat keine Rotation.

**Fix:** Zentrale Audit-Funktion in eigenem Modul, mit Rotation.

### M15: Concurrent Proposals in self_optimization -- Index-Verschiebung
**Datei:** `assistant/self_optimization.py` (Zeilen 160-201)

Zwei gleichzeitige `approve_proposal()`-Calls arbeiten auf derselben Liste. `pop(index)` verschiebt Indizes.

**Fix:** Proposals per UUID identifizieren statt per Index.

### M16: Rate-Limiter Lock blockiert alle HTTP-Requests waehrend Cleanup
**Datei:** `assistant/main.py` (Zeilen 571-608)

Alle 5 Minuten: Cleanup iteriert ueber bis zu 10.000 IPs unter Lock. Alle HTTP-Requests warten.

**Fix:** Cleanup ausserhalb des Locks oder inkrementell.

### M17: Wiederholte `get_states()`-Aufrufe in Hot Paths
**Dateien:** `proactive.py`, `routine_engine.py`, `function_validator.py`

Morning Briefing kann 5-10 separate `get_states()`-Calls an HA ausloesen. Jeder ist ein HTTP-Request.

**Fix:** States einmal pro Event-Verarbeitungszyklus laden und durchreichen.

### M18: Bare `dict[]`-Zugriffe in Function Handlers
**Datei:** `assistant/function_calling.py` (Zeilen 3179, 3191, 3262, 3338, 3384)

`args["door"]`, `args["action"]` etc. ohne `.get()` -- KeyError bei fehlerhaften LLM-Tool-Calls.

**Fix:** `.get()` mit Fehlerbehandlung oder Pflichtfeld-Pruefung vor Zugriff.

### M19: Synchrone apply_decay -- N+1 Redis Round-Trips
**Datei:** `assistant/semantic_memory.py` (Zeilen 317-394)

Einzelne `hgetall` und `hset` pro Fact. Hunderte sequentielle Redis-Aufrufe.

**Fix:** Pipeline verwenden fuer Batch-Reads und Batch-Writes.

### M20: TOCTOU Race in Event-Accumulation
**Datei:** `assistant/proactive.py` (Zeilen 1352-1366)

Zwischen GET und SETEX kann ein anderer Coroutine den Key modifizieren oder loeschen.

**Fix:** Redis WATCH/MULTI oder Lua-Script fuer atomare Read-Modify-Write.

---

## NIEDRIG (Verbesserungspotenzial)

- **N1:** Episode-ID-Kollision bei gleichem Sekundenwert (`memory.py:161`)
- **N2:** `_success_count` nicht zurueckgesetzt bei HALF_OPEN Failure (`circuit_breaker.py:93-100`)
- **N3:** `call_with_breaker` schluckt alle Exceptions (`circuit_breaker.py:195-198`)
- **N4:** `SCENE_INTELLIGENCE_PROMPT` stale nach Config-Reload (`brain.py:171`)
- **N5:** `_active_tokens` Dict unbegrenzt (`main.py:1661`)
- **N6:** CORS erlaubt spoofbare `.local` Domain (`main.py:400`)
- **N7:** `_remember_exchange` Fire-and-Forget verliert Conversations bei Task-Name-Kollision (`brain.py:660-670`)
- **N8:** Boot-Task nicht im TaskRegistry registriert (`main.py:349-350`)
- **N9:** Vacation-Simulation-Loop prueft kein `_running` Flag (`routine_engine.py:1282-1329`)
- **N10:** Zwei verschiedene `_is_bed_occupied`-Implementierungen (`routine_engine.py` vs `proactive.py`)
- **N11:** `generate()` meldet keinen Circuit-Breaker-Failure bei HTTP-Fehler (`ollama_client.py:471-474`)
- **N12:** `list_models()` ohne Timeout (`ollama_client.py:507-512`)
- **N13:** aiohttp Session Leak bei ungraceful Shutdown (`ollama_client.py:165-188`)
- **N14:** `stream_chat` Error-Marker nicht von echtem Text unterscheidbar (`ollama_client.py:352`)
- **N15:** `_exec_set_cover_markisen` liest YAML direkt statt Cache (`function_calling.py:2666`)
- **N16:** Unsafe `int()` Cast in Cover-Pushback (`function_validator.py:363`)
- **N17:** Open-Window-Check nutzt hardcoded Prefixes statt `is_window_or_door()` (`function_validator.py:222-225`)
- **N18:** `reload_config()` aktualisiert Model-Namen nicht (`model_router.py:88-112`)
- **N19:** Docstring sagt "TTL 24h" aber Default ist 1h (`error_patterns.py:9 vs 39`)
- **N20:** Snapshot erstellt vor Validation in self_optimization (`self_optimization.py:171-177`)

---

## Empfohlene Umsetzungsreihenfolge

### Phase 1: Kritische Fixes (Betrieb direkt betroffen)
1. **K2** -- Timezone-Fix (groesste Auswirkung, betrifft Raumerkennung, Routinen, Cover)
2. **K1** -- RequestContext einfuehren (verhindert Cross-Request-Korruption)
3. **H1** -- Security-Fix fuer anonyme Bestaetigung
4. **H2** -- WebSocket UnboundLocalError
5. **K4** -- ChromaDB in `asyncio.to_thread()` wrappen

### Phase 2: Stabilitaet
6. **H3** -- YAML Write-Lock
7. **H4** -- Vacuum Tasks canceln
8. **H7** -- Task-Supervision
9. **H5** -- Self-Optimization Runtime-Reload
10. **H6** -- Rate-Limit Reset Fix
11. **M1** -- Morning Briefing Race
12. **M3** -- Redis bytes Decode
13. **M4** -- LLM-Call Timeouts

### Phase 3: Wachstum & Performance
14. **K3** -- get_all_episodes Pagination
15. **M9** -- TaskRegistry Cleanup
16. **M10** -- hash() durch hashlib ersetzen
17. **M11** -- ChromaDB/Redis Compensation
18. **M12** -- Word-Boundary Keyword Matching
19. **M17** -- States-Caching pro Event-Zyklus
20. **M19** -- apply_decay Pipeline

### Phase 4: Restliche Medium/Low Fixes
- Alle weiteren M- und N-Findings nach Aufwand/Nutzen

---

## Kritische Dateien

| Datei | Findings |
|-------|----------|
| `assistant/assistant/brain.py` | K1, K2, H1, M14, N4, N7 |
| `assistant/assistant/main.py` | H2, H3, M5, M16, N5, N6, N8 |
| `assistant/assistant/proactive.py` | H4, H7, H8, M1, M6, M7, M17, M20 |
| `assistant/assistant/routine_engine.py` | M2, M3, M4, N9, N10 |
| `assistant/assistant/memory.py` | K3, K4, N1 |
| `assistant/assistant/semantic_memory.py` | K4, M10, M11, M19 |
| `assistant/assistant/self_automation.py` | H6, H9, M8 |
| `assistant/assistant/self_optimization.py` | H5, M3, M15, N20 |
| `assistant/assistant/function_calling.py` | M18, N15 |
| `assistant/assistant/function_validator.py` | M13, N16, N17 |
| `assistant/assistant/model_router.py` | M12, N18 |
| `assistant/assistant/ollama_client.py` | N11, N12, N13, N14 |
| `assistant/assistant/circuit_breaker.py` | N2, N3 |
| `assistant/assistant/error_patterns.py` | N19 |
| `assistant/assistant/task_registry.py` | M9 |
