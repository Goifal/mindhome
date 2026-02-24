# TTS/STT Triple-Audit Report

**Datum:** 2026-02-24
**Scope:** Alle Dateien die mit Text-to-Speech und Speech-to-Text zusammenhaengen
**Methode:** 3 unabhaengige Code-Audits (Wyoming Handler, Docker/Network, Full Pipeline)

---

## Zusammenfassung

| Severity | Anzahl |
|----------|--------|
| CRITICAL | 4 |
| WARNING  | 4 |
| INFO     | 5 |

---

## CRITICAL Bugs

### C-1: Embedding wird doppelt konsumiert (Daten gehen verloren)

**Dateien:** `assistant/brain.py:654`, `assistant/speaker_recognition.py:292,655`

**Problem:** `_get_wyoming_embedding()` liest das Embedding aus Redis und LOESCHT es sofort (Zeile 632). Wenn `identify()` aufgerufen wird und die Person per Device-Mapping erkannt wird (nicht per Embedding), ruft `brain.py:666` danach `learn_embedding_from_audio()` auf — aber dort ruft `_get_wyoming_embedding()` erneut Redis auf und bekommt `None`, weil der Key schon geloescht wurde.

**Auswirkung:** Voice-Embeddings werden NIE gelernt fuer Personen die per Device-Mapping, Room-Presence, Sole-Person oder DoA erkannt werden. Das Embedding geht bei jeder Identifikation verloren. Speaker-Recognition per Voice-Embedding kann sich nie verbessern.

**Ablauf:**
```
1. identify() → _get_wyoming_embedding() → liest+loescht Redis Key
2. identify() erkennt per device_mapping → return (Embedding ungenutzt)
3. brain.py ruft learn_embedding_from_audio() auf
4. learn_embedding_from_audio() → _get_wyoming_embedding() → None (schon geloescht!)
5. Fallback audio_pcm_b64 → auch None (HA Assist Pipeline sendet kein PCM)
6. Embedding ging verloren
```

**Fix:** `identify()` soll das Embedding einmal lesen und als Rueckgabe-Feld mitgeben, damit `brain.py` es an `learn_embedding_from_audio()` weitergeben kann. Oder: `_get_wyoming_embedding()` mit Cache-Parameter, der beim zweiten Aufruf den gecachten Wert zurueckgibt statt erneut Redis zu fragen.

---

### C-2: Doppelte TTS-Wiedergabe bei Assist Pipeline Requests

**Dateien:** `assistant/brain.py:460-478`, `assistant/sound_manager.py:430-524`, `ha_integration/conversation.py:134-136`

**Problem:** Wenn ein Sprachbefehl ueber die HA Assist Pipeline kommt:

1. **HA Pipeline spricht:** `conversation.py` gibt `IntentResponse` mit `speech` zurueck (Zeile 135) → HA Assist Pipeline nimmt diesen Text und schickt ihn an Wyoming Piper TTS → **Speaker spielt Antwort ab**
2. **brain.py spricht auch:** `_speak_and_emit()` (Zeile 475-477) ruft `sound_manager.speak_response()` auf → findet `tts.*piper*` Entity → ruft `tts.speak` Service auf → **Speaker spielt Antwort nochmal ab**

**Auswirkung:** Der User hoert JEDE Antwort DOPPELT — einmal von der HA Pipeline und einmal von brain.py/sound_manager.

**Fix:** brain.py muss erkennen ob der Request von der HA Assist Pipeline kommt (z.B. via `source: "ha_assist_pipeline"` im Request) und in dem Fall `speak_response()` NICHT aufrufen, weil die Pipeline das selbst erledigt.

---

### C-3: TTS-Entity verschwindet nach Piper Add-on Entfernung

**Dateien:** `assistant/sound_manager.py:403-428`

**Problem:** `_find_tts_entity()` sucht nach `tts.*piper*` Entity (Zeile 417). Aktuell existiert diese Entity weil das Piper HA Add-on laeuft. Nach der Migration zu Wyoming Piper auf PC 2:

- Das Piper Add-on wird entfernt → `tts.piper` Entity verschwindet
- Wyoming Piper registriert sich als STT/TTS Provider in der Assist Pipeline
- ABER: Wyoming Integration erstellt **nicht automatisch** eine `tts.*` Entity die in HA States sichtbar ist

**Auswirkung:** Alle proaktiven Sprachausgaben (Benachrichtigungen, Warnungen, Doorbell, Greetings, Alarme) funktionieren nicht mehr. Nur die Assist Pipeline (die direkt Wyoming nutzt) funktioniert noch.

**Fix:** In `settings.yaml` explizit `sounds.tts_entity` konfigurieren. Oder: Wyoming Piper Integration in HA manuell als TTS-Platform einrichten (nicht nur als Pipeline-Provider). Der Code hat bereits den Fallback `self._configured_tts_entity` (Zeile 406) — das muss nur in der Doku und settings.yaml dokumentiert werden.

---

### C-4: Race Condition — Embedding noch nicht in Redis wenn brain.py es liest

**Dateien:** `speech/handler.py:167`, `assistant/speaker_recognition.py:627`

**Problem:** In `handler.py:167` wird das Embedding als `asyncio.create_task()` (fire-and-forget) gestartet. Das Transcript wird SOFORT an HA zurueckgegeben (Zeile 140). Die Zeitlinie:

```
t=0ms:   AudioStop empfangen
t=200ms: Whisper Transkription fertig → Transcript an HA gesendet
t=200ms: Embedding-Extraktion startet (asyncio.create_task)
t=250ms: HA sendet Text an conversation.py → POST an brain.py
t=300ms: brain.py ruft identify() → _get_wyoming_embedding() → Redis Key existiert noch NICHT
t=500ms: ECAPA-TDNN fertig → Embedding in Redis geschrieben
```

**Auswirkung:** Bei schnellem Netzwerk (~50ms) kommt brain.py's Anfrage BEVOR das Embedding in Redis steht. Die Embedding-basierte Speaker-Erkennung schlaegt fehl, obwohl das Embedding verfuegbar waere.

**Fix:** Entweder (a) kurzes `await asyncio.sleep(0.1)` in `identify()` vor dem Redis-Read, oder (b) Embedding SYNCHRON extrahieren (vor dem Transcript senden) — dauert ~300ms extra Latenz, ist aber zuverlaessig, oder (c) Retry-Loop in `_get_wyoming_embedding()` mit max 500ms Wartezeit.

---

## WARNING

### W-1: Einzelner Redis Key fuer alle gleichzeitigen Requests

**Datei:** `speech/handler.py:209-213`

**Problem:** Alle Wyoming Handler-Instanzen schreiben auf denselben Redis Key `mha:speaker:latest_embedding`. Bei gleichzeitigen Anfragen (z.B. 2 Personen sprechen fast gleichzeitig in verschiedenen Raeumen) ueberschreibt das zweite Embedding das erste.

**Auswirkung:** Bei gleichzeitigen Spracheingaben wird das Embedding der falschen Person zugeordnet. In der Praxis selten (Anfragen kommen normalerweise sequenziell), aber technisch moeglich.

**Fix:** Request-ID als Teil des Redis Keys verwenden, z.B. `mha:speaker:embedding:{request_id}`. Die Request-ID koennte aus dem Wyoming Transcribe-Event oder als UUID generiert werden.

---

### W-2: Preload erstellt Modell-Instanz die weggeworfen wird

**Datei:** `speech/server.py:95-118`

**Problem:** `_preload_models()` erstellt ein `WhisperModel()` Objekt (Zeile 101), speichert es aber NICHT in der globalen `_whisper_model` Variable. Beim ersten echten Request laedt `_get_whisper_model()` das Modell nochmal. Gleiches Problem fuer ECAPA-TDNN.

**Auswirkung:** Der erste Request dauert doppelt so lange (Modell wird zweimal geladen). RAM-Verbrauch verdoppelt sich kurzzeitig.

**Fix:** `_preload_models()` soll direkt `_get_whisper_model()` und `_get_embedding_model()` aufrufen statt eigene Instanzen zu erstellen.

---

### W-3: `asyncio.get_event_loop()` ist deprecated

**Datei:** `speech/handler.py:155,198`

**Problem:** `asyncio.get_event_loop()` ist seit Python 3.10 deprecated und wird in Python 3.12+ eine Warnung erzeugen. Korrekt ist `asyncio.get_running_loop()`.

**Auswirkung:** Deprecation-Warnings im Log. Funktioniert aktuell noch, koennte in Python 3.14 entfernt werden.

**Fix:** `asyncio.get_event_loop()` → `asyncio.get_running_loop()` ersetzen.

---

### W-4: Docker Piper Container hat keinen expliziten Port im `command`

**Datei:** `assistant/docker-compose.yml:131`

**Problem:** Der `command` fuer Piper setzt nur `--voice` aber keinen `--port`. Das offizielle `rhasspy/wyoming-piper` Image nutzt standardmaessig Port 10200, aber das ist ein impliziter Default.

**Auswirkung:** Gering — funktioniert aktuell weil der Default 10200 stimmt. Aber bei Image-Updates koennte sich der Default aendern.

**Fix:** Explizit `command: --voice ${PIPER_VOICE:-de_DE-thorsten-high} --port 10200` setzen.

---

## INFO

### I-1: Kein Graceful Shutdown fuer Redis Connection

**Datei:** `speech/handler.py:67-80`

Die globale Redis-Connection (`_redis_client`) wird nie explizit geschlossen. Bei Container-Stop koennten offene Connections im Redis Server verbleiben.

### I-2: `embedding_extractor.py` wird nach Migration redundant

**Datei:** `assistant/assistant/embedding_extractor.py`

Dieser Modul extrahiert Embeddings lokal mit SpeechBrain. Nach der Migration zu Wyoming Whisper (das Embeddings im Handler extrahiert) wird dieses Modul nur noch als Fallback benoetigt. Langfristig kann es entfernt werden sobald Wyoming stabil laeuft.

### I-3: Voice-Metadaten aus HA Pipeline sind nur Schaetzungen

**Datei:** `ha_integration/conversation.py:145-180`

`_build_voice_metadata()` berechnet WPM und Duration nur aus der Wortanzahl (nicht aus echten Audio-Daten). Die Werte sind immer ~130 WPM / geschaetzte Dauer. Fuer Voice-Feature-Matching sind diese Schaetzungen unzuverlaessig.

### I-4: ECAPA-TDNN Minimum Audio-Laenge unterschiedlich

- `speech/handler.py:230` prueft `< 3200 samples` (0.2s bei 16kHz)
- `assistant/embedding_extractor.py:73` prueft `< 3200 bytes` (0.1s bei 16kHz, 16-bit)

Beide Schwellenwerte sind niedrig genug fuer normale Spracheingaben, aber die Inkonsistenz koennte verwirrend sein.

### I-5: `docker-compose.gpu.yml` Piper GPU-Support fraglich

Das offizielle `rhasspy/wyoming-piper` Image nutzt ONNX Runtime fuer Inferenz. ONNX auf GPU erfordert `onnxruntime-gpu` — das offizielle Image hat das moeglicherweise nicht installiert. GPU-Reservierung fuer Piper koennte wirkungslos sein.

---

## Dateien im Scope

| Datei | Rolle | Bugs |
|-------|-------|------|
| `speech/handler.py` | Wyoming Whisper STT + Embedding Handler | C-4, W-1, W-2, W-3 |
| `speech/server.py` | Wyoming Server Entry Point | W-2 |
| `speech/Dockerfile.whisper` | Docker Image fuer Whisper | - |
| `speech/requirements.txt` | Python Dependencies | - |
| `assistant/docker-compose.yml` | Service-Orchestrierung | W-4 |
| `assistant/docker-compose.gpu.yml` | GPU Override | I-5 |
| `assistant/assistant/speaker_recognition.py` | Speaker-Erkennung + Embedding | C-1, C-4 |
| `assistant/assistant/sound_manager.py` | TTS-Ausgabe + Event-Sounds | C-2, C-3 |
| `assistant/assistant/brain.py` | Hauptlogik, spricht+identifiziert | C-1, C-2 |
| `assistant/assistant/embedding_extractor.py` | Lokale Embedding-Extraktion (Legacy) | I-2 |
| `ha_integration/conversation.py` | HA Conversation Agent | C-2, I-3 |

---

## Empfohlene Reihenfolge fuer Fixes

1. **C-1** (Embedding verloren) — Einfachster Fix, groesste Auswirkung auf Speaker-Recognition-Lernen
2. **C-2** (Doppelte TTS) — Muss vor dem ersten Deployment gefixt werden, sonst hoert User alles doppelt
3. **C-3** (TTS Entity) — Doku-Fix + settings.yaml Config, kein Code noetig
4. **C-4** (Race Condition) — Retry-Loop ist der pragmatischste Fix
5. **W-2** (Preload weggeworfen) — Quick-Fix, spart RAM + Startup-Zeit
6. **W-3** (deprecated API) — Quick-Fix, 2 Zeilen
7. **W-1** (Redis Key Collision) — Kann spaeter gefixt werden (selten in der Praxis)
8. **W-4** (Piper Port) — Quick-Fix, 1 Zeile
