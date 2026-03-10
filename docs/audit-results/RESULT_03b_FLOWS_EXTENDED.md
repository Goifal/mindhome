# Audit-Ergebnis: Prompt 3b — End-to-End Flow-Analyse (Extended-Flows 8–13) + Kollisionen

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Extended-Flows 8–13, Flow-Kollisionen, Service-Interaktionsanalyse

---

## 1. Flow-Dokumentation (Flows 8–13)

### Flow 8: Addon-Automation
**Status**: ⚠️ Teilweise — funktioniert intern, aber KEINE Koordination mit Assistant

**Ablauf**:
1. HA WebSocket Event (state_changed) → `app.py:on_state_changed()` (ca. Zeile 399)
2. Dedup-Check (1s Window, Zeile 415) verhindert Doppel-Events
3. `state_logger.log_state_change()` → `pattern_engine.py` zeichnet in SQLite `state_history` auf
4. `event_bus.publish("state.changed", ...)` → `event_bus.py:108` verteilt an Subscriber
5. `automation_engine.py` prüft ob gelernte Patterns matchen (Confidence-Threshold)
6. Domain-spezifische Confidence-Schwellen: Lock/Alarm 95%, Light 75%, Climate 85%
7. `automation_engine.py:_execute_action()` (ca. Zeile 791) → `ha_connection.call_service()`
8. Ergebnis in `ActionLog` + `Prediction` (SQLite) gespeichert

**Engines die parallel laufen**:
- `circadian.py` — Zirkadiane Lichtsteuerung (Brightness + Color-Temperature Kurven)
- `cover_control.py` — Rollladen-Automatik (Sonnenschutz, Wetter, Zeitplan, Anwesenheit)
- `sleep.py` — Schlaf-Erkennung und -Aktionen
- `fire_water.py` — Feuer/Wasser-Notfall-Aktionen (8× `call_service`)
- `energy.py` — PV-Überschuss-Steuerung
- `adaptive.py` — Adaptive Aktionen (14× `call_service`)
- `special_modes.py` — Party/Cinema/Emergency (27× `call_service`)

**Bruchstellen**:
- `circadian.py` steuert **dieselben Lichter** wie Assistant `light_engine.py` — **KEINE Koordination**
- `cover_control.py` steuert **dieselben Rollläden** wie Assistant `cover_config.py` — **KEINE Koordination**
- `fire_water.py` ruft HA-Services direkt auf (Lichter an, Benachrichtigungen) — Assistant erfährt nichts
- Addon nutzt **KEINE Shared Schemas** — eigene Event-Klasse in `event_bus.py:17-31`
- Addon nutzt **KEINE Shared Constants** — Ports/Events lokal definiert

**Fehler-Pfade**:
- HA nicht erreichbar → `ha_connection.py` hat 3 Retries mit Backoff (Zeile 69-115)
- Pattern-Confidence zu niedrig → Action wird geloggt aber nicht ausgeführt
- Fehler erreichen den User **NICHT** — werden nur im Addon-Log protokolliert

**Kollisionen mit anderen Flows**:
- 🔴 Flow 1 (User-Aktion via Assistant) + Flow 8 (Addon-Automation) → **Race Condition auf dieselbe Entity**
- 🔴 Flow 5 (Personality) — Addon-Aktionen haben **KEINE Persönlichkeit**, keine Jarvis-Ansage
- 🟠 Flow 2 (Proactive) — Addon-Events könnten Assistant-Proactive-Events triggern die mit Addon-Aktionen kollidieren

---

### Flow 9: Domain-Assistenten
**Status**: ✅ Funktioniert — korrekt in brain.py integriert

**Ablauf**:
1. User-Text → `brain.process()` (Zeile 1076)
2. Shortcut-Detection: Spezifische Shortcuts für Cooking (Zeile 1380-1399), Calendar (Zeile 1461-1616), Weather (Zeile 1618-1664)
3. Falls kein Shortcut: Pre-Classifier → Intent-Erkennung
4. Context-Builder sammelt domain-spezifischen Kontext
5. LLM-Call mit Tools → Tool-Calls können Domain-Assistenten aktivieren:
   - `cooking_assistant.py` via Tool-Calls (Rezept-Suche, Timer)
   - `music_dj.py` via `media_player.*` Tool-Calls
   - `smart_shopping.py` via Shopping-Tools
   - `calendar_intelligence.py` via Calendar-Tools + Shortcut
   - `web_search.py` via Web-Search-Tool
6. Antwort → `_filter_response_inner()` → personality pipeline → TTS

**Routing-Mechanismus**:
- **Shortcuts** (deterministic, brain.py:1304-2325): Keyword-basiert, umgeht LLM
- **Pre-Classifier** (brain.py:2482-2520): Bestimmt Model-Tier
- **LLM Tool-Selection**: Das LLM entscheidet welcher Domain-Assistent via Tool-Call aktiviert wird

**Bruchstellen**:
- Domain-Assistenten gehen durch die **vollständige Personality-Pipeline** ✅
- Domain-Assistenten haben Zugriff auf **Memory und Kontext** ✅ (via context_builder)
- **Shortcuts umgehen LLM** aber nutzen trotzdem personality/TTS — konsistent ✅
- Calendar-Shortcut (Zeile 1506-1616) macht eigenen LLM-Call für "Polish" — **separater Call**, nicht der Haupt-LLM-Call

**Fehler-Pfade**:
- Domain-Assistent nicht erreichbar (z.B. ChromaDB für recipe_store) → Graceful Degradation, LLM antwortet ohne Domain-Daten
- Web-Search fehlgeschlagen → User wird informiert ("Konnte keine Informationen finden")

**Kollisionen mit anderen Flows**: Keine signifikanten.

---

### Flow 10: Workshop-System
**Status**: ⚠️ Teilweise — Funktional, aber Sicherheits-Lücke

**Ablauf**:
1. Workshop-UI oder Chat → `main.py:6100` POST `/api/workshop/chat`
2. Chat geht durch **`brain.process()`** mit `room="werkstatt"` (Zeile 6118)
3. 80+ Workshop-Endpoints in `main.py` (Zeile 5816-7008) delegieren an:
   - `repair_planner.py` — Projekt-Management, Diagnose, Schritt-Navigation
   - `workshop_generator.py` — Code-Generierung (Arduino, Python, C++), 3D-Modelle (OpenSCAD), SVGs, BOMs
   - `workshop_library.py` — Technische Referenz-Dokumentation (ChromaDB RAG)
4. Hardware-Steuerung (3D-Drucker, Roboter-Arm) → über HA-Entity-States (main.py:6901-6978)
5. WebSocket: `emit_workshop()` sendet Events (step, diagnosis, file_created, printer, arm)

**Integration**:
- Workshop-Chat → `brain.process()` → **volle Persönlichkeits-Pipeline** ✅
- Workshop hat Zugriff auf Memory und Kontext ✅
- Hardware-Steuerung (Drucker/Arm) nutzt `brain.ha.call_service()` — geht durch HA ✅

**Bruchstellen**:
- 🔴 **Sicherheits-Lücke**: `/api/workshop/chat` ist NICHT durch API-Key-Middleware geschützt (main.py:6102-6106 Kommentar bestätigt dies explizit). Jeder im Netzwerk kann ohne Authentifizierung mit brain.process() interagieren.
- 🟠 **Kein Trust-Level-Check** für Hardware-Steuerung: Roboter-Arm-Befehle (move, gripper, home, pick-tool) haben KEINEN Autonomie- oder Trust-Level-Check — jeder Workshop-User kann Hardware steuern
- 🟠 3D-Drucker Start/Pause/Cancel: Keine Bestätigung vor destruktiven Aktionen
- Workshop-Endpoints sind die **größte Gruppe** (80+ von 170+ total in main.py) — massiver Code-Anteil

**Fehler-Pfade**:
- brain.process() Timeout (60s) → "Systeme überlastet" Meldung (Zeile 6122)
- Projekt nicht gefunden → 404
- Hardware nicht erreichbar → HA-Call-Fehler, User wird informiert

**Kollisionen mit anderen Flows**:
- Flow 1 — Workshop-Chat nutzt **denselben brain.process()**, concurrent Requests können sich gegenseitig beeinflussen (kein Lock in brain.py)

---

### Flow 11: Boot-Sequenz & Startup-Announcement
**Status**: ✅ Funktioniert

**Ablauf**:
1. Docker-Start → FastAPI `lifespan()` (`main.py:322`)
2. `brain.initialize()` (main.py:328) — 66 Schritte (siehe RESULT_03a)
3. Error/Activity Buffers aus Redis restaurieren (main.py:331-337)
4. Cover-Settings an Addon synchronisieren (main.py:339-345)
5. `brain.health_check()` — prüft Ollama, HA, Redis, ChromaDB (main.py:347)
6. Log: "MindHome Assistant bereit" (main.py:356)
7. `_boot_announcement()` als Background-Task (main.py:363):
   a. Wartet `delay_seconds` (default 5s) (main.py:216)
   b. Fragt HA-States ab: Raumtemperatur, offene Fenster/Türen (main.py:220-258)
   c. Baut Boot-Nachricht: Zufällige Begrüßung + Temperatur + Status (main.py:260-291)
   d. `sound_manager.play_event_sound("greeting")` (main.py:295)
   e. `emit_speaking(msg)` → WebSocket (main.py:298)
   f. `sound_manager.speak_response(msg)` → TTS (main.py:301)
8. `yield` — App serviert Requests (main.py:369)

**Persönlichkeits-Pipeline**:
- Boot-Nachricht geht **NICHT** durch personality.py — ist hardcoded (main.py:262-266)
- Templates konfigurierbar via `settings.yaml:boot_sequence.messages`
- Fallback bei Fehler: "Alle Systeme online, {title}." (main.py:307) — hardcoded, kein personality

**Dependency-Failure**:
- Module 1-30 nicht in `_safe_init()` → **Exception = Fatal Crash** (keine Degradation)
- Module 31-62 in `_safe_init()` → Graceful Degradation, `_degraded_modules` Liste
- `ProactiveManager.start()` (Schritt 64) NICHT in `_safe_init()` → **Fatal bei HA-WS-Fehler**
- `brain.health_check()` zeigt Status an, crasht aber nicht bei "degraded"

**Ready-Status**:
- Readiness Probe: `GET /readyz` (main.py:7934) — prüft `brain._initialized`
- Health Probe: `GET /healthz` (main.py:7928) — immer 200, Inhalt zeigt Status

**Bruchstellen**:
- Boot-Nachricht hat **keine JARVIS-Persönlichkeit** — hardcoded Templates
- Wenn HA beim Start nicht erreichbar: kein Temperatur/Fenster-Status, aber Boot-Nachricht wird trotzdem gesendet

**Fehler-Pfade**:
- Gesamte `_boot_announcement()` in try/except — Fehler → Fallback-Nachricht (main.py:304-309)
- Fallback-Fallback auch in try/except — komplett stiller Fehler bei doppeltem Exception (main.py:308-309)

**Kollisionen**: Keine — Boot läuft einmal beim Start.

---

### Flow 12: File-Upload & OCR
**Status**: ✅ Funktioniert

**Ablauf**:
1. POST `/api/assistant/chat/upload` (main.py:1658) — mit API-Key-Schutz ✅
2. Validierung: Dateiname, erlaubte Extensions, 50MB Limit (main.py:1671-1680)
3. `file_handler.save_upload()` (file_handler.py:62):
   a. Filename-Sanitierung: Nur alphanumerische Zeichen + `._- ` (file_handler.py:72)
   b. UUID-Prefix für Eindeutigkeit (file_handler.py:77)
   c. Text-Extraktion je nach Typ (file_handler.py:83)
4. Bei Bildern: `ocr.extract_text_from_image()` (ocr.py:66):
   a. **Path-Validierung** (F-045): Shell-Metazeichen blockiert (ocr.py:51)
   b. **Pfadtraversal-Check**: `..` in resolved path → blockiert (ocr.py:56-62)
   c. Tesseract OCR mit Vorverarbeitung (Grayscale, Contrast, Sharpen) (ocr.py:97-100+)
   d. Max 4000 Zeichen extrahiert (ocr.py:40)
5. `brain.process(text, files=[file_info])` (main.py:1691) — volle Pipeline mit File-Kontext

**Sicherheit**:
- ✅ Path Traversal: Doppelte Absicherung (UUID-Prefix + resolved-path-Check)
- ✅ Injection via Dateinamen: Sanitiert auf `[a-zA-Z0-9._- ]`
- ✅ SVG-Upload blockiert (F-018): XSS-Risiko durch JavaScript in SVG
- ✅ Shell-Metazeichen im OCR-Pfad blockiert (F-045)
- ✅ Größenlimit: 50MB für Upload, 4000 Zeichen für extrahierten Text
- ⚠️ `get_file_path()` (file_handler.py:100) — prüft ob Datei existiert, aber **kein expliziter Pfad-Confinement-Check** beim Serving

**Bruchstellen**:
- Extrahierter Text auf 4000 Zeichen begrenzt — passt ins Context-Window ✅
- Tesseract nicht installiert → OCR deaktiviert, aber Upload funktioniert weiter (graceful)

**Fehler-Pfade**:
- brain.process() Exception → "Datei empfangen, aber Fehler bei Verarbeitung" (main.py:1698-1703)
- Datei zu groß → HTTP 413 (main.py:1680)
- Dateityp nicht erlaubt → HTTP 400 (main.py:1675)

**Kollisionen**: Keine signifikanten.

---

### Flow 13: WebSocket-Streaming
**Status**: ✅ Funktioniert

**Ablauf**:
1. Client → `ws://host:8200/api/assistant/ws?api_key=KEY` (main.py:1792)
2. Auth: API-Key Check ODER Same-Origin erlaubt (main.py:1817-1828)
3. `ws_manager.connect()` — max 50 Verbindungen (websocket.py:20, 27)
4. Keep-Alive: Ping alle 25s (main.py:1834-1843)
5. Message-Loop mit 300s Inaktivitäts-Timeout (main.py:1857-1863)
6. Rate-Limiting: max 30 Nachrichten pro 10s (F-063, main.py:1847-1878)

**Events (Server → Client)**:
| Event | Funktion | Zeile |
|-------|----------|-------|
| `assistant.thinking` | `emit_thinking()` | websocket.py:88 |
| `assistant.speaking` | `emit_speaking()` | websocket.py:93 |
| `assistant.action` | `emit_action()` | websocket.py:104 |
| `assistant.listening` | `emit_listening()` | websocket.py:113 |
| `assistant.proactive` | `emit_proactive()` | websocket.py:155 |
| `assistant.sound` | `emit_sound()` | websocket.py:118 |
| `assistant.progress` | `emit_progress()` | websocket.py:126 |
| `assistant.stream_start` | `emit_stream_start()` | websocket.py:137 |
| `assistant.stream_token` | `emit_stream_token()` | websocket.py:142 |
| `assistant.stream_end` | `emit_stream_end()` | websocket.py:147 |
| `assistant.interrupt` | `emit_interrupt()` | websocket.py:189 |
| `workshop.*` | `emit_workshop()` | websocket.py:170 |

**Events (Client → Server)**:
| Event | Handling | Zeile |
|-------|----------|-------|
| `assistant.text` | → `brain.process()` (optional streaming) | main.py:1888 |
| `assistant.feedback` | → `brain.feedback.*` | main.py (nach Zeile 1900) |
| `assistant.interrupt` | → setzt `_ws_interrupt_flag` | main.py:1852 |
| `pong` | → ignoriert (keep-alive) | main.py:1885 |

**Streaming-Modus** (main.py:1903+):
- Client sendet `{"event": "assistant.text", "data": {"text": "...", "stream": true}}`
- Reasoning-Guard: Erste 12 Tokens buffern um Chain-of-Thought zu erkennen (main.py:1911)
- Token-für-Token via `emit_stream_token()` → `emit_stream_end(full_text)`

**Bruchstellen**:
- ⚠️ **Kein Reconnection-Handling**: Bei WebSocket-Abbruch muss der Client selbst reconnecten — kein Server-seitiger Retry
- ✅ Backpressure: `broadcast()` fängt send-Fehler ab und entfernt tote Connections (websocket.py:54-69)
- ✅ Alle Antwort-Pfade (normal, proaktiv, routine, workshop) nutzen WebSocket-Events
- ⚠️ **300s Timeout**: Inaktive Clients werden nach 5 Min getrennt — könnte UI-Clients betreffen die nur zuhören

**Fehler-Pfade**:
- Client disconnected → `WebSocketDisconnect` → `ws_manager.disconnect()` — sauber
- Max 50 Connections erreicht → Client bekommt Close mit Code 4008 (websocket.py:28)
- Rate-Limit überschritten → "Rate limit exceeded" Error-Event (main.py:1875-1878)

**Kollisionen**:
- Proaktive Meldungen und Streaming können **gleichzeitig** über denselben WebSocket laufen — Client muss damit umgehen

---

## 2. Kollisions-Tabelle

| Szenario | Was sollte passieren | Was passiert tatsächlich | Code-Referenz |
|----------|---------------------|------------------------|---------------|
| **Proaktive Warnung während User spricht** | Queue, nach Antwort ausspielen | Proactive hat 6 Filter-Layer (Quiet Hours, Autonomy, Mood, Feedback, Cooldown, Batching), aber **kein Check auf laufende Konversation**. Events werden sofort gesendet. | `proactive.py:222` → `emit_proactive()` |
| **Morgen-Briefing während Konversation** | Briefing verzögern | Briefing sendet `emit_proactive()` ohne Konversations-Check. **Kein Verzögerungsmechanismus.** | `routine_engine.py` → `proactive.py:1036` |
| **Zwei autonome Aktionen gleichzeitig** | Priorisieren | Autonomy-Level prüft pro Aktion, **kein globaler Mutex**. Beide können parallel ausgeführt werden. | `autonomy.py` |
| **Function Call + autonome Aktion** | User-Aktion hat Vorrang | **Kein Prioritätsmechanismus.** Beide rufen HA unabhängig auf. Letzte gewinnt. | `function_calling.py` + `autonomy.py` |
| **Memory-Speicherung während nächster Request** | Nicht blockieren | ✅ Korrekt: Memory writes sind fire-and-forget (`asyncio.create_task`) | `brain.py:4264-4313` |
| **Addon-Automation + Assistant-Aktion** | Wer gewinnt? | **NIEMAND koordiniert. Race Condition.** Addon kennt Assistant-Absichten nicht, Assistant kennt Addon-Aktionen nicht. HA nimmt den letzten Befehl. | Addon `automation_engine.py` vs. `function_calling.py` |
| **Addon-Cover-Control + Assistant-Cover-Config** | Gleiche Rollläden? | **JA — gleiche Entities, keine Koordination.** Addon `cover_control.py` hat Priority-System (Schedule=10, Weather=40, Security=50), Assistant hat eigenes `cover_config.py`. Kein gegenseitiges Vetorecht. | `cover_control.py:27-31` vs. `cover_config.py` |
| **Addon-Circadian + Assistant-Light-Engine** | Gleiche Lampen? | **JA — gleiche Entities, keine Koordination.** Addon sendet Brightness+CT-Kurven, Assistant hat eigene `light_engine.py` mit Adaptive Lighting. Können sich gegenseitig überschreiben. | `circadian.py` vs. `light_engine.py` |
| **Speech in Raum A + Speech in Raum B** | Parallel oder sequentiell? | **Sequentiell.** Whisper hat `_model_lock` (asyncio.Lock in `handler.py:37-46`). Zweite Transkription wartet. brain.py hat **keinen Lock** — zwei process()-Aufrufe laufen parallel, können Shared State korrumpieren. | `handler.py:37` + brain.py (kein Lock) |

---

## 3. Service-Interaktions-Analyse

### Flow 8: Addon-Automation
```
Addon (Flask, PC1) ←WebSocket→ HA ←REST→ Addon
       ↓ (State Events)
  pattern_engine → automation_engine → ha_connection.call_service()
       ↓                                      ↓
  SQLite (68 Tabellen)                    HA Entity State
                                               ↑
  Assistant (FastAPI, PC2) ─────REST──────────┘
  (weiß NICHTS von Addon-Aktionen)
```
**Problem**: Beide Services greifen auf denselben HA-State zu, ohne vom anderen zu wissen.

### Flow 9-10: Domain-Assistenten & Workshop
```
User → main.py → brain.process() → LLM → Tool-Calls
                      ↓                      ↓
               personality.py          function_calling.py
                      ↓                      ↓
               context_builder.py      ha_client.py → HA
                      ↓
            cooking/music/calendar/workshop
```
**Sauber**: Alles geht durch brain.py und die Persönlichkeits-Pipeline.

### Flow 11: Boot
```
main.py:lifespan() → brain.initialize() → health_check()
                          ↓
                    _boot_announcement()
                          ↓
                    ha.get_states() → Temperatur + offene Türen
                          ↓
                    emit_speaking() + sound_manager.speak_response()
```
**Einmal-Flow**: Keine Service-Interaktion nach Boot.

### Flow 12-13: Upload & WebSocket
```
Client ─HTTP POST─→ main.py:/api/assistant/chat/upload
                          ↓
                    file_handler.save_upload() → ocr.extract_text()
                          ↓
                    brain.process(files=[...])
                          ↓
                    WebSocket broadcast (emit_speaking/stream)
```
**Sauber**: File-Upload geht durch volle Pipeline, WebSocket ist reiner Event-Broadcast.

---

## 4. Kritische Findings (Top-5)

| # | Finding | Severity | Impact |
|---|---------|----------|--------|
| 1 | **Addon ↔ Assistant Entity-Kollision**: Circadian (Addon) vs. Light-Engine (Assistant) und Cover-Control (Addon) vs. Cover-Config (Assistant) steuern **dieselben HA-Entities** ohne Koordination. Race Conditions sind unvermeidlich. | 🔴 KRITISCH | Lichter/Rollläden flackern, inkonsistentes Verhalten |
| 2 | **brain.py hat KEINEN Lock**: Mehrere concurrent `process()`-Aufrufe (WebSocket + HTTP + Workshop-Chat) laufen parallel, teilen Shared State (`dialogue_state`, `_last_*` Variablen, `_current_person`). | 🔴 KRITISCH | State-Corruption, falsche Person-Zuordnung |
| 3 | **Workshop-Chat umgeht API-Key**: `/api/workshop/chat` (main.py:6100) geht durch `brain.process()` aber hat **keinen API-Key-Check** — jeder im Netzwerk kann ohne Authentifizierung den Assistenten nutzen. | 🔴 KRITISCH | Unautorisierte Nutzung, potentielle HA-Steuerung |
| 4 | **Keine Hardware-Sicherheit im Workshop**: Roboter-Arm (move, gripper) und 3D-Drucker (start, cancel) haben **keinen Trust-Level-Check**. Jeder Workshop-User kann Hardware steuern. | 🟠 HOCH | Physische Schäden möglich |
| 5 | **Proaktiv-Events ignorieren laufende Konversation**: Proactive/Routine-Events werden sofort gesendet ohne zu prüfen ob gerade ein User-Request verarbeitet wird. Kein Queue-Mechanismus. | 🟠 HOCH | Unterbrechende, verwirrende UX |

---

## 5. Feature-Gaps

| Feature | Beschreibung | Impact |
|---------|-------------|--------|
| **Action-Broker** | Kein zentraler Koordinator der HA-Aufrufe beider Services (Assistant + Addon) synchronisiert | 🔴 KRITISCH |
| **Conversation Lock** | Kein Mechanismus der parallele brain.process()-Aufrufe serialisiert oder isoliert | 🔴 KRITISCH |
| **Cross-Service State Sync** | Assistant kennt Addon-Aktionen nicht, Addon kennt Assistant-Entscheidungen nicht | 🔴 KRITISCH |
| **Proactive Queue** | Kein Priority-Queue der proaktive Meldungen zurückhält wenn User gerade spricht | 🟠 HOCH |
| **Boot-Persönlichkeit** | Boot-Nachricht geht nicht durch personality.py — hardcoded Templates | 🟡 MITTEL |
| **WebSocket Reconnection** | Kein Server-seitiger Reconnection-Mechanismus bei Verbindungsabbruch | 🟡 MITTEL |

---

## KONTEXT AUS PROMPT 3 (gesamt: 3a + 3b): Flow-Analyse

### Init-Sequenz
66 Schritte in brain.initialize(). Module 1-30 NICHT in _safe_init() (Fatal). F-069 Boundary ab Schritt 31. ProactiveManager.start() (Schritt 64) ebenfalls NICHT safe.

### System-Prompt (rekonstruiert)
Token-budgetierter Aufbau in 4 Prioritäten (P1-P4). personality.py:SYSTEM_PROMPT_TEMPLATE als Base. Dynamisch: Memory (P1), Corrections (P1), Situation (P2), Conversation History (P3). Automatisches Dropping bei Token-Overflow.

### Flow-Status-Übersicht (alle 13 Flows)

| Flow | Status | Kritischste Bruchstelle |
|------|--------|------------------------|
| 1: Sprach-Input → Antwort | ⚠️ Teilweise | Duplicate conv_memory key (brain.py:2356+2394) |
| 2: Proaktive Benachrichtigung | ⚠️ Teilweise | Kein Check auf laufende Konversation |
| 3: Morgen-Briefing | ⚠️ Teilweise | Kein TTS — emit_proactive() statt _deliver() |
| 4: Autonome Aktion | ⚠️ Teilweise | Autonomy-Level-System funktioniert, aber kein globaler Mutex |
| 5: Persönlichkeits-Pipeline | ⚠️ Teilweise | Inkonsistent: CRITICAL proactive hat keine Persönlichkeit |
| 6: Memory-Abruf | ⚠️ Teilweise | ChromaDB-Episoden werden gespeichert aber nie gelesen |
| 7: Speech-Pipeline | ✅ Funktioniert | Wyoming TCP + Redis Embedding, 7-Methoden Speaker Recognition |
| 8: Addon-Automation | ⚠️ Teilweise | Steuert gleiche Entities wie Assistant, KEINE Koordination |
| 9: Domain-Assistenten | ✅ Funktioniert | Korrekt durch brain.py + personality integriert |
| 10: Workshop-System | ⚠️ Teilweise | API-Key-Bypass, keine Hardware-Sicherheit |
| 11: Boot-Sequenz | ✅ Funktioniert | Boot-Nachricht nicht durch personality.py |
| 12: File-Upload & OCR | ✅ Funktioniert | Gute Sicherheit (Path-Traversal, Injection, Größenlimit) |
| 13: WebSocket-Streaming | ✅ Funktioniert | Kein Reconnection-Handling, 300s Inaktivitäts-Timeout |

### Top-Bruchstellen (alle Flows)
1. 🔴 **Addon ↔ Assistant Entity-Kollision** — circadian/cover_control vs light_engine/cover_config
2. 🔴 **brain.py kein Lock** — concurrent process() korrumpiert Shared State
3. 🔴 **Workshop API-Key-Bypass** — unautorisierter Zugriff auf brain.process()
4. 🔴 **Duplicate conv_memory key** — Semantic Search wird überschrieben (brain.py:2356+2394)
5. 🟠 **Proactive ignoriert laufende Konversation** — keine Queue

### Kollisionen
- Addon-Engines vs. Assistant-Module auf denselben HA-Entities (Lichter, Rollläden)
- Parallele brain.process()-Aufrufe ohne Lock (HTTP + WebSocket + Workshop)
- Proaktive Events während laufender Verarbeitung

### Feature-Gaps
- Kein Action-Broker zwischen Assistant und Addon
- Kein Conversation-Lock in brain.py
- Kein Cross-Service State Sync
- Keine Proactive-Queue
