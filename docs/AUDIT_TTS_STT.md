# TTS/STT Triple-Audit Report

**Datum:** 2026-02-24
**Scope:** Alle Dateien die mit Text-to-Speech und Speech-to-Text zusammenhaengen
**Methode:** 3 unabhaengige Code-Audits (Wyoming Handler, Docker/Network, Full Pipeline)

---

## Zusammenfassung

| Severity | Anzahl |
|----------|--------|
| CRITICAL | 6 |
| WARNING  | 7 |
| INFO     | 7 |

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

### C-5: `WHISPER_MODEL=small-int8` ist KEIN gueltiger faster-whisper Modellname (SHOWSTOPPER)

**Dateien:** `assistant/.env.example:47`, `speech/server.py:101`, `speech/handler.py:42`

**Problem:** Der Default `WHISPER_MODEL=small-int8` wird an `WhisperModel(model_name)` uebergeben. Aber `faster-whisper` (die Bibliothek die hier DIREKT verwendet wird) akzeptiert diesen Namen nicht. Gueltige Namen sind: `tiny`, `base`, `small`, `medium`, `large-v1`, `large-v2`, `large-v3`, `large-v3-turbo`, `turbo`, etc.

`small-int8` ist eine Konvention von `rhasspy/wyoming-faster-whisper` (dem HA Add-on), das den Namen intern auf das HuggingFace-Repo `rhasspy/faster-whisper-small-int8` mappt. Unser Code nutzt faster-whisper DIREKT und hat dieses Mapping nicht.

**Auswirkung:** Der Whisper Container STARTET NICHT. `WhisperModel("small-int8")` wirft sofort `ValueError: Invalid model size 'small-int8'`. Kein STT moeglich.

**Fix:** `WHISPER_MODEL` Default aendern auf `small` (INT8-Quantisierung wird bereits ueber `WHISPER_COMPUTE=int8` gesteuert). Oder das volle HuggingFace-Repo angeben: `rhasspy/faster-whisper-small-int8`.

---

### C-6: Ungepinnte torch/torchaudio/speechbrain Versionen koennen SpeechBrain crashen

**Datei:** `speech/requirements.txt:6-8`

**Problem:**
```
speechbrain>=1.0.0
torch>=2.0.0
torchaudio>=2.0.0
```

Diese offenen Versionsbereiche erlauben pip `torchaudio>=2.9` zu installieren, welches `torchaudio.list_audio_backends()` entfernt hat. SpeechBrain ruft diese Funktion beim Import auf → `AttributeError` Crash. Ausserdem MUESSEN `torch` und `torchaudio` versionssynchron sein (z.B. beide 2.5.x). Offene Bereiche riskieren Mismatch.

**Auswirkung:** Container baut erfolgreich, aber beim ersten Import von SpeechBrain crasht der Prozess mit `AttributeError`. Voice Embeddings funktionieren nicht.

**Fix:** Versionen pinnen:
```
torch==2.5.1
torchaudio==2.5.1
speechbrain==1.0.3
```

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

### W-5: HuggingFace Cache nicht im Volume — Modell-Downloads gehen bei Rebuild verloren

**Dateien:** `speech/handler.py:58`, `speech/Dockerfile.whisper`

**Problem:** SpeechBrain laedt ECAPA-TDNN zuerst in den HuggingFace Cache (`~/.cache/huggingface/`) und erstellt dann Symlinks im `savedir` (`/app/models/`). Das Volume mountet nur `/app/models/` — der HuggingFace Cache liegt in der Container-Schreibschicht und geht bei Rebuild verloren. Die Symlinks zeigen dann ins Nichts.

**Fix:** `ENV HF_HOME=/app/models/.hf_cache` in der Dockerfile setzen, damit alle Downloads im gemounteten Volume landen.

---

### W-6: PyTorch installiert CUDA-Version (~2.3GB) obwohl CPU reicht

**Datei:** `speech/Dockerfile.whisper`

**Problem:** `pip install torch torchaudio` ohne `--index-url` installiert die volle CUDA-Version von PyTorch (~2.3GB). Fuer CPU-only Betrieb (Phase 1) reicht die CPU-Version (~300MB).

**Fix:** Vor dem `pip install -r requirements.txt` separat installieren:
```dockerfile
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**Auswirkung:** Docker Image ist ~2GB groesser als noetig. Kein funktionaler Bug.

---

### W-7: Whisper `start_period: 120s` reicht beim ersten Start moeglicherweise nicht

**Datei:** `assistant/docker-compose.yml:120`

**Problem:** Beim ersten Container-Start muessen Whisper (~461MB) + ECAPA-TDNN (~80MB) Modelle heruntergeladen werden. Bei langsamer Verbindung dauert das laenger als `120s + (5 * 30s) = 270s`. Autoheal startet den Container dann neu → Download-Loop.

**Fix:** `start_period: 300s` setzen, oder Modelle waehrend `docker build` vorladen.

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

### I-6: Healthchecks nutzen korrekte Python-Binaries

- **Whisper** (custom `python:3.12-slim`): `python -c "..."` — korrekt
- **Piper** (`rhasspy/wyoming-piper`, Debian-basiert): `python3 -c "..."` — korrekt

Beide Healthchecks pruefen TCP Socket-Connect, was korrekt den Wyoming Server Status verifiziert.

### I-7: Wyoming Ports und Netzwerk-Architektur korrekt

- Whisper `10300`, Piper `10200` — korrekte Wyoming Defaults
- Redis/ChromaDB auf `127.0.0.1` gebunden (kein externer Zugriff) — gut
- Inter-Container Kommunikation ueber Docker-Netzwerk — korrekt
- `depends_on: redis: condition: service_healthy` — korrekt

---

## Dateien im Scope

| Datei | Rolle | Bugs |
|-------|-------|------|
| `speech/handler.py` | Wyoming Whisper STT + Embedding Handler | C-4, W-1, W-3 |
| `speech/server.py` | Wyoming Server Entry Point | C-5, W-2 |
| `speech/Dockerfile.whisper` | Docker Image fuer Whisper | W-6 |
| `speech/requirements.txt` | Python Dependencies | C-6 |
| `assistant/docker-compose.yml` | Service-Orchestrierung | W-4, W-7 |
| `assistant/docker-compose.gpu.yml` | GPU Override | I-5 |
| `assistant/.env.example` | Umgebungsvariablen | C-5 |
| `assistant/assistant/speaker_recognition.py` | Speaker-Erkennung + Embedding | C-1, C-4 |
| `assistant/assistant/sound_manager.py` | TTS-Ausgabe + Event-Sounds | C-2, C-3 |
| `assistant/assistant/brain.py` | Hauptlogik, spricht+identifiziert | C-1, C-2 |
| `assistant/assistant/embedding_extractor.py` | Lokale Embedding-Extraktion (Legacy) | I-2 |
| `ha_integration/conversation.py` | HA Conversation Agent | C-2, I-3 |

---

## Empfohlene Reihenfolge fuer Fixes

1. **C-5** (Ungueltiger Modellname) — **SHOWSTOPPER**: Whisper startet gar nicht. 1-Zeilen-Fix.
2. **C-6** (Ungepinnte Versionen) — Container crasht beim SpeechBrain-Import. 3-Zeilen-Fix.
3. **C-1** (Embedding verloren) — Einfachster Fix, groesste Auswirkung auf Speaker-Recognition-Lernen
4. **C-2** (Doppelte TTS) — Muss vor dem ersten Deployment gefixt werden, sonst hoert User alles doppelt
5. **C-3** (TTS Entity) — Doku-Fix + settings.yaml Config, kein Code noetig
6. **C-4** (Race Condition) — Retry-Loop ist der pragmatischste Fix
7. **W-2** (Preload weggeworfen) — Quick-Fix, spart RAM + Startup-Zeit
8. **W-5** (HF Cache) — Verhindert Download-Loop nach Container-Rebuild
9. **W-6** (PyTorch CUDA statt CPU) — Spart ~2GB Image-Groesse
10. **W-3** (deprecated API) — Quick-Fix, 2 Zeilen
11. **W-7** (start_period) — Quick-Fix, 1 Zeile
12. **W-1** (Redis Key Collision) — Kann spaeter gefixt werden (selten in der Praxis)
13. **W-4** (Piper Port) — Quick-Fix, 1 Zeile
