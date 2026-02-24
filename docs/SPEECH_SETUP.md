# Speech auf PC 2 verschieben — Schritt-fuer-Schritt Anleitung

> Whisper (STT) und Piper (TTS) von den HA-Add-ons auf PC 2 migrieren.
> Inklusive Stimmenerkennung (Voice Embeddings) und GPU-Upgrade-Pfad.

---

## Inhaltsverzeichnis

1. [Ueberblick: Was aendert sich?](#ueberblick-was-aendert-sich)
2. [Vorher / Nachher Architektur](#vorher--nachher-architektur)
3. [Was wird nicht mehr gebraucht?](#was-wird-nicht-mehr-gebraucht)
4. [Was bleibt gleich?](#was-bleibt-gleich)
5. [Phase 1: CPU-Modus (RTX 3070)](#phase-1-cpu-modus-rtx-3070)
6. [Phase 2: GPU-Upgrade (RTX 3090 Ti)](#phase-2-gpu-upgrade-rtx-3090-ti)
7. [Testen](#testen)
8. [Fehlerbehebung](#fehlerbehebung)
9. [Technische Details](#technische-details)

---

## Ueberblick: Was aendert sich?

| Komponente | Vorher (PC 1) | Nachher (PC 2) |
|---|---|---|
| **Whisper STT** | HA Add-on auf Intel NUC | Docker Container auf Assistant-PC |
| **Piper TTS** | HA Add-on auf Intel NUC | Docker Container auf Assistant-PC |
| **Stimmenerkennung** | Nicht moeglich (kein Audio auf PC 2) | Automatisch (Audio kommt ueber Wyoming) |
| **Voice Embeddings** | Toter Code | Aktiv — ECAPA-TDNN extrahiert Stimmabdruecke |

**Warum?**
- PC 2 hat die bessere Hardware (Ryzen 3700X, 64 GB RAM, GPU)
- Stimmenerkennung braucht Zugriff auf das rohe Audio
- Spaeter: GPU-Upgrade auf RTX 3090 Ti macht alles 10x schneller
- PC 1 (Intel NUC) wird entlastet

---

## Vorher / Nachher Architektur

### VORHER: Speech auf PC 1

```
ESP32 Satellit (Atom Echo / ReSpeaker)
    | WiFi (Audio-Stream)
    v
PC 1 — Home Assistant (Intel NUC)
    |
    +-- Whisper Add-on (STT)          <-- Transkription auf dem NUC
    +-- Piper Add-on (TTS)            <-- Sprachausgabe auf dem NUC
    +-- Conversation Agent
    |       | HTTP POST (nur TEXT)
    |       v
    |   PC 2 — MindHome Assistant     <-- Bekommt nur Text, kein Audio
    |       | HTTP Response (Text)
    |       v
    +-- Speaker (Sonos etc.)
```

### NACHHER: Speech auf PC 2

```
ESP32 Satellit (Atom Echo / ReSpeaker)
    | WiFi (Audio-Stream)
    v
PC 1 — Home Assistant (Intel NUC)
    |
    | Wyoming Protocol (TCP, rohe Audio-Bytes)
    v
PC 2 — Whisper + Embedding Service (:10300)
    |
    +-- faster-whisper: Audio --> Text
    +-- ECAPA-TDNN: Audio --> Stimmabdruck --> Redis
    |
    | Transkript zurueck an HA (Wyoming Protocol)
    v
PC 1 — Home Assistant
    |
    | Conversation Agent sendet Text an PC 2
    v
PC 2 — MindHome Assistant (:8200)
    |
    +-- speaker_recognition.py liest Embedding aus Redis
    +-- Identifiziert Person ("Das ist Max")
    +-- Ollama/Qwen verarbeitet Anfrage
    +-- Generiert Antwort + Function Calls
    |
    | Antwort-Text zurueck an HA
    v
PC 1 — Home Assistant
    |
    | Wyoming Protocol (Text an TTS)
    v
PC 2 — Piper TTS (:10200)
    |
    +-- Text --> Audio (WAV)
    |
    | Audio zurueck an HA (Wyoming Protocol)
    v
PC 1 — Home Assistant
    |
    +-- Spielt Audio auf Speaker ab
    v
Speaker (Sonos etc.)
```

**Wichtig:** Die ESP32 Satelliten verbinden sich weiterhin mit Home Assistant.
HA leitet Audio/Text nur weiter — kein schweres Rechnen mehr auf dem NUC.

---

## Was wird nicht mehr gebraucht?

### Auf PC 1 (Home Assistant) ENTFERNEN:

| Komponente | Aktion | Warum |
|---|---|---|
| **Whisper Add-on** | Deinstallieren | Laeuft jetzt auf PC 2 |
| **Piper Add-on** | Deinstallieren | Laeuft jetzt auf PC 2 |

### Auf PC 1 (Home Assistant) BEHALTEN:

| Komponente | Warum |
|---|---|
| Home Assistant Core | Steuert weiterhin alles |
| ESPHome Integration | Satelliten verbinden sich weiterhin mit HA |
| Wyoming Integration | Zeigt jetzt auf PC 2 statt auf lokale Add-ons |
| Assist Pipeline | Gleiche Konfiguration, nur andere STT/TTS-Ziele |
| Conversation Agent | Sendet weiterhin Text an PC 2 |
| openWakeWord Add-on | Wake Word Detection bleibt auf HA (oder ESP32) |
| Media Player | Sonos etc. werden weiterhin von HA gesteuert |
| MindHome Add-on | Alle Engines laufen weiterhin |
| Alle Automationen | Keine Aenderung noetig |

---

## Was bleibt gleich?

- **ESP32 Satelliten**: Keine Aenderung. Verbinden sich weiterhin mit HA.
- **Wake Word**: Bleibt auf dem ESP32 oder HA. Keine Aenderung.
- **Automationen**: Alle bestehenden Automationen funktionieren weiterhin.
- **Ollama / LLM**: Laeuft weiterhin nativ auf PC 2. Keine Aenderung.
- **ChromaDB / Redis**: Keine Aenderung.
- **MindHome Assistant**: Keine Aenderung am Chat-Endpoint.

---

## Phase 1: CPU-Modus (RTX 3070)

> In Phase 1 laufen Whisper und Piper auf der CPU von PC 2.
> Die GPU bleibt exklusiv fuer Ollama (LLM-Inference).
> Spaeter (Phase 2) laeuft alles auf der GPU.

### Erwartete Latenz (CPU)

| Modell | Latenz | Dialekt-Erkennung |
|---|---|---|
| `small-int8` | ~2-4 Sek | Akzeptabel |
| `medium-int8` | ~5-10 Sek | Gut |
| `large-v3-turbo` | ~15-25 Sek | Sehr gut (zu langsam fuer CPU) |

**Empfehlung Phase 1:** Starte mit `small-int8`. Wenn die Erkennung nicht reicht, wechsle auf `medium-int8`.

---

### Schritt 1: PC 2 — Software aktualisieren und Services starten

> Alles auf PC 2 (MindHome Assistant Server) via SSH ausfuehren.

---

#### 1.1 Per SSH auf PC 2 verbinden

Von deinem Laptop oder einem anderen PC:

```bash
ssh mindhome@192.168.1.50
```

(Ersetze `192.168.1.50` mit der IP deines Assistant-PCs.)

---

#### 1.2 Neuesten Code ziehen

```bash
cd ~/mindhome
git pull
```

Damit werden alle neuen Dateien heruntergeladen:

```
mindhome/
  assistant/
    docker-compose.yml          # Erweitert um whisper + piper Services
    docker-compose.gpu.yml      # Neu: GPU-Override (fuer Phase 2)
    .env.example                # Erweitert um Speech-Variablen
  speech/
    Dockerfile.whisper          # Neu: Custom Whisper + Embedding Server
    handler.py                  # Neu: Wyoming Handler mit Embedding-Extraktion
    server.py                   # Neu: Wyoming Server Entry Point
    requirements.txt            # Neu: faster-whisper, speechbrain, wyoming, redis
```

**Pruefen ob alles da ist:**

```bash
ls ~/mindhome/speech/
```

Erwartete Ausgabe:
```
Dockerfile.whisper  handler.py  requirements.txt  server.py
```

---

#### 1.3 Speech-Variablen in .env eintragen

Oeffne die `.env` Datei:

```bash
nano ~/mindhome/assistant/.env
```

Fuege **am Ende der Datei** folgende Zeilen hinzu:

```bash
# --- Speech Services (Whisper STT + Piper TTS) ---
SPEECH_DEVICE=cpu
WHISPER_MODEL=small-int8
WHISPER_LANGUAGE=de
WHISPER_BEAM_SIZE=5
WHISPER_COMPUTE=int8
PIPER_VOICE=de_DE-thorsten-high
```

Speichern: `Strg+O` → `Enter` → `Strg+X`

**Was die Variablen bedeuten:**

| Variable | Wert | Erklaerung |
|---|---|---|
| `SPEECH_DEVICE` | `cpu` | CPU fuer Phase 1, spaeter `cuda` fuer GPU |
| `WHISPER_MODEL` | `small-int8` | Kleines schnelles Modell (~2-4 Sek auf CPU) |
| `WHISPER_LANGUAGE` | `de` | Deutsch als Sprache |
| `WHISPER_BEAM_SIZE` | `5` | Genauigkeit der Suche (Standard) |
| `WHISPER_COMPUTE` | `int8` | CPU-optimiertes Format, spaeter `float16` fuer GPU |
| `PIPER_VOICE` | `de_DE-thorsten-high` | Deutsche maennliche Stimme (beste Qualitaet) |

---

#### 1.4 Firewall-Ports oeffnen

Die neuen Services muessen von Home Assistant (PC 1) erreichbar sein:

```bash
# Whisper STT Port
sudo ufw allow 10300/tcp comment "Wyoming Whisper STT"

# Piper TTS Port
sudo ufw allow 10200/tcp comment "Wyoming Piper TTS"
```

**Pruefen:**

```bash
sudo ufw status
```

Erwartete neue Eintraege:
```
10300/tcp                  ALLOW       Anywhere       # Wyoming Whisper STT
10200/tcp                  ALLOW       Anywhere       # Wyoming Piper TTS
```

> **Hinweis:** Falls UFW nicht aktiv ist (Status: inactive), wurde die Firewall
> nicht eingerichtet. Dann brauchst du diesen Schritt nicht — die Ports sind
> ohne Firewall sowieso offen.

---

#### 1.5 Docker-Container bauen und starten

Jetzt wird der Whisper-Container gebaut (das dauert beim ersten Mal 5-10 Minuten weil Modelle heruntergeladen werden):

```bash
cd ~/mindhome/assistant
docker compose build whisper
```

**Was passiert beim Build:**
- Python 3.12 Image wird heruntergeladen
- faster-whisper, speechbrain, torch, wyoming werden installiert
- Gesamtgroesse: ~3-4 GB (wegen PyTorch + Modelle)

Wenn der Build fertig ist, alle Container starten:

```bash
docker compose up -d
```

Docker ladet auch automatisch das Piper-Image (`rhasspy/wyoming-piper`) herunter.

---

#### 1.6 Warten bis Container healthy sind

Der Whisper-Container braucht beim ersten Start 1-3 Minuten, weil er die Modelle herunterlaed (faster-whisper + ECAPA-TDNN). Danach geht es schnell.

**Status pruefen (alle paar Sekunden wiederholen):**

```bash
docker compose ps
```

Warten bis **alle** Container "Up (healthy)" zeigen:

```
NAME                STATUS              PORTS
mindhome-assistant  Up (healthy)        0.0.0.0:8200->8200/tcp
mha-chromadb        Up (healthy)        127.0.0.1:8100->8000/tcp
mha-redis           Up (healthy)        127.0.0.1:6379->6379/tcp
mha-whisper         Up (healthy)        0.0.0.0:10300->10300/tcp
mha-piper           Up (healthy)        0.0.0.0:10200->10200/tcp
mha-autoheal        Up
```

**Falls ein Container "starting" oder "unhealthy" bleibt:**

```bash
# Logs anschauen:
docker compose logs whisper
docker compose logs piper
```

Typische Gruende:
- `mha-whisper` im Status "starting" → Modelle werden noch heruntergeladen (warte 2-3 Min)
- `mha-piper` im Status "starting" → Piper-Voice wird heruntergeladen (warte 1-2 Min)
- "Fehler: Redis nicht erreichbar" → Redis ist noch nicht healthy, Container startet sich automatisch neu

---

#### 1.7 Ports von PC 1 aus testen

Oeffne ein neues Terminal auf einem **anderen PC** (oder PC 1) und teste die Verbindung:

```bash
# Whisper erreichbar? (Ersetze 192.168.1.50 mit der IP von PC 2)
nc -zv 192.168.1.50 10300

# Piper erreichbar?
nc -zv 192.168.1.50 10200
```

Erwartete Ausgabe:
```
Connection to 192.168.1.50 10300 port [tcp/*] succeeded!
Connection to 192.168.1.50 10200 port [tcp/*] succeeded!
```

Falls `nc` nicht installiert ist:
```bash
sudo apt install -y netcat-openbsd
```

**Falls "Connection refused":** Container laeuft nicht → `docker compose ps` und Logs pruefen.
**Falls "Connection timed out":** Firewall blockiert → `sudo ufw allow 10300/tcp` auf PC 2.

---

#### Zusammenfassung: Alle Befehle fuer Schritt 1

Hier alle Befehle auf einen Blick (auf PC 2 ausfuehren):

```bash
# 1. Code holen
cd ~/mindhome && git pull

# 2. .env erweitern (Speech-Variablen am Ende anfuegen)
cat >> ~/mindhome/assistant/.env << 'EOF'

# --- Speech Services (Whisper STT + Piper TTS) ---
SPEECH_DEVICE=cpu
WHISPER_MODEL=small-int8
WHISPER_LANGUAGE=de
WHISPER_BEAM_SIZE=5
WHISPER_COMPUTE=int8
PIPER_VOICE=de_DE-thorsten-high
EOF

# 3. Firewall-Ports oeffnen
sudo ufw allow 10300/tcp comment "Wyoming Whisper STT"
sudo ufw allow 10200/tcp comment "Wyoming Piper TTS"

# 4. Whisper-Container bauen (dauert 5-10 Min beim ersten Mal)
cd ~/mindhome/assistant
docker compose build whisper

# 5. Alle Container starten
docker compose up -d

# 6. Warten und pruefen (ein paar Mal wiederholen bis alle "healthy")
docker compose ps
```

---

### Schritt 2: Home Assistant — Wyoming Integration hinzufuegen

> Diesen Schritt machst DU in der HA-Oberflaeche.

**2.1 STT (Whisper) als Wyoming-Service hinzufuegen:**

1. Oeffne Home Assistant: `http://192.168.1.100:8123`
2. Gehe zu: **Einstellungen** → **Geraete & Dienste** → **Integration hinzufuegen**
3. Suche nach: **Wyoming Protocol**
4. Eingeben:
   - **Host:** `<IP von PC 2>` (z.B. `192.168.1.200`)
   - **Port:** `10300`
5. Klicke **Absenden**
6. HA erkennt automatisch: "Faster Whisper" STT Service

**2.2 TTS (Piper) als Wyoming-Service hinzufuegen:**

1. Gehe erneut zu: **Einstellungen** → **Geraete & Dienste** → **Integration hinzufuegen**
2. Suche nach: **Wyoming Protocol**
3. Eingeben:
   - **Host:** `<IP von PC 2>` (z.B. `192.168.1.200`)
   - **Port:** `10200`
4. Klicke **Absenden**
5. HA erkennt automatisch: "Piper" TTS Service

---

### Schritt 3: Home Assistant — Assist Pipeline umstellen

> Diesen Schritt machst DU in der HA-Oberflaeche.

1. Gehe zu: **Einstellungen** → **Sprachassistenten**
2. Klicke auf deine bestehende Pipeline (z.B. "Jarvis" oder "Home Assistant")
3. Aendere:
   - **Sprache-zu-Text:** Waehle den neuen Wyoming Whisper (PC 2) statt des lokalen Add-ons
   - **Text-zu-Sprache:** Waehle den neuen Wyoming Piper (PC 2) statt des lokalen Add-ons
   - **Conversation Agent:** Bleibt gleich (MindHome Assistant)
4. Klicke **Speichern**

**Tipp:** Erstelle zuerst eine NEUE Pipeline zum Testen, bevor du die bestehende aenderst. So kannst du schnell zurueckwechseln falls etwas nicht funktioniert.

---

### Schritt 4: Testen

> Bevor du die alten Add-ons entfernst, teste ob alles funktioniert!

**4.1 Quick-Test ueber HA-Oberflaeche:**

1. Gehe zu: **Einstellungen** → **Sprachassistenten**
2. Klicke auf das Mikrofon-Symbol neben deiner neuen Pipeline
3. Sprich: "Wie ist die Temperatur im Wohnzimmer?"
4. Pruefen:
   - [ ] Sprache wird erkannt (Text erscheint)
   - [ ] Jarvis antwortet (Text-Antwort)
   - [ ] Antwort wird vorgelesen (Audio-Ausgabe)

**4.2 Test ueber Satellit:**

1. Sage das Wake Word am ESP32 Satelliten
2. Stelle eine Frage
3. Pruefen:
   - [ ] Wake Word wird erkannt
   - [ ] Sprache wird transkribiert
   - [ ] Antwort kommt zurueck
   - [ ] Audio wird auf dem Speaker abgespielt

**4.3 Latenz pruefen:**

```bash
# Auf PC 2: Whisper-Logs anschauen
docker compose logs -f whisper
```

Achte auf die Transkriptions-Zeit. Bei `small-int8` auf CPU sollten es 2-4 Sekunden sein.

**4.4 Stimmenerkennung pruefen:**

```bash
# Auf PC 2: Pruefen ob Embeddings in Redis ankommen
docker compose exec redis redis-cli KEYS "mha:speaker:*"
```

Nach dem ersten Sprachbefehl solltest du Keys wie `mha:speaker:latest_embedding` sehen.

---

### Schritt 5: Alte Add-ons entfernen

> ERST wenn Schritt 4 erfolgreich war!

1. Gehe zu: **Einstellungen** → **Add-ons**
2. Klicke auf **Whisper**
3. Klicke **Deinstallieren**
4. Klicke auf **Piper**
5. Klicke **Deinstallieren**

**Fertig!** PC 1 ist jetzt entlastet. STT und TTS laufen auf PC 2.

---

### Schritt 6 (Optional): Whisper-Modell wechseln

Falls die Erkennung mit `small-int8` nicht gut genug ist:

```bash
# Auf PC 2: .env editieren
nano /home/user/mindhome/assistant/.env

# Aendern:
WHISPER_MODEL=medium-int8

# Container neu starten:
cd /home/user/mindhome/assistant
docker compose up -d whisper
```

Das Medium-Modell ist 3x groesser und erkennt Dialekt besser, braucht aber laenger (~5-10 Sek auf CPU).

---

## Phase 2: GPU-Upgrade (RTX 3090 Ti)

> Wenn du die neue Grafikkarte hast, sind es nur wenige Schritte.
> An Home Assistant aenderst du NICHTS — nur PC 2.

### Erwartete Latenz (GPU)

| Modell | Latenz | Dialekt-Erkennung |
|---|---|---|
| `small-int8` | <0.5 Sek | Akzeptabel |
| `medium-int8` | ~1 Sek | Gut |
| `large-v3-turbo` | ~1-2 Sek | Sehr gut |

**Empfehlung Phase 2:** `large-v3-turbo` — beste Erkennung, trotzdem schnell.

### VRAM-Rechnung (RTX 3090 Ti = 24 GB)

```
Ollama Qwen3-14B:              ~8 GB
faster-whisper large-v3-turbo:  ~6 GB
Piper TTS:                     ~0.5 GB
SpeechBrain ECAPA-TDNN:        ~0.3 GB
────────────────────────────────────────
Gesamt:                        ~14.8 GB
Frei:                           ~9.2 GB
```

Alles passt locker in 24 GB. Sogar Qwen3-32B (~20 GB) waere moeglich wenn du die anderen Modelle auf CPU laesst.

---

### Schritt 1: Hardware einbauen

1. PC 2 ausschalten
2. RTX 3070 raus, RTX 3090 Ti rein
3. PC 2 starten

### Schritt 2: NVIDIA Treiber installieren

```bash
# Pruefen ob Karte erkannt wird:
lspci | grep -i nvidia

# Treiber installieren:
sudo apt update
sudo apt install -y nvidia-driver-550

# Neustart:
sudo reboot

# Pruefen:
nvidia-smi
```

Du solltest die RTX 3090 Ti mit 24 GB VRAM sehen.

### Schritt 3: NVIDIA Container Toolkit installieren

> Damit Docker-Container die GPU nutzen koennen.

```bash
# Repository hinzufuegen:
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit

# Docker konfigurieren:
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Testen:
docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi
```

Du solltest die RTX 3090 Ti auch innerhalb des Containers sehen.

### Schritt 4: .env umstellen (3 Zeilen aendern)

```bash
nano /home/user/mindhome/assistant/.env
```

**Aendern:**

```bash
# VORHER (CPU):
SPEECH_DEVICE=cpu
WHISPER_MODEL=small-int8
WHISPER_COMPUTE=int8

# NACHHER (GPU):
SPEECH_DEVICE=cuda
WHISPER_MODEL=large-v3-turbo
WHISPER_COMPUTE=float16
```

### Schritt 5: GPU-Override aktivieren

```bash
nano /home/user/mindhome/assistant/.env
```

**Hinzufuegen (ganz unten):**

```bash
# GPU-Modus aktivieren (Docker Compose Override):
COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml
```

Diese Zeile sagt Docker Compose, dass es die GPU-Override-Datei mit laden soll. Darin steht der GPU-Zugriff fuer die Whisper- und Piper-Container.

### Schritt 6: Container neu starten

```bash
cd /home/user/mindhome/assistant
docker compose down
docker compose up -d
```

### Schritt 7: Pruefen

```bash
# GPU-Auslastung pruefen:
nvidia-smi

# Whisper-Logs pruefen (sollte "cuda" zeigen):
docker compose logs whisper | head -20

# Einen Sprachbefehl testen und Latenz messen
docker compose logs -f whisper
```

**Fertig!** Alles laeuft jetzt auf der GPU. Latenz sollte unter 2 Sekunden sein.

---

### Zurueck zum CPU-Modus (falls noetig)

Falls du temporaer zurueck auf CPU willst (z.B. GPU-Problem):

```bash
nano /home/user/mindhome/assistant/.env
```

```bash
# Zurueck auf CPU:
SPEECH_DEVICE=cpu
WHISPER_MODEL=small-int8
WHISPER_COMPUTE=int8

# GPU-Override deaktivieren (auskommentieren oder loeschen):
# COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml
```

```bash
docker compose down
docker compose up -d
```

An Home Assistant aenderst du auch hier **nichts**. Die Wyoming-Verbindung bleibt auf PC2:10300 und PC2:10200.

---

## Testen

### Checkliste nach der Einrichtung

| Test | Befehl / Aktion | Erwartetes Ergebnis |
|---|---|---|
| Container laufen | `docker compose ps` | Alle 6 Services "Up (healthy)" |
| Whisper erreichbar | `echo '{}' \| nc PC2-IP 10300` | Verbindung wird angenommen |
| Piper erreichbar | `echo '{}' \| nc PC2-IP 10200` | Verbindung wird angenommen |
| Wyoming in HA | HA → Einstellungen → Integrationen | 2 Wyoming-Eintraege sichtbar |
| STT funktioniert | Mikrofon-Test in HA Pipeline | Text wird erkannt |
| TTS funktioniert | Test-Satz in HA Pipeline | Audio wird abgespielt |
| Satellit funktioniert | Wake Word + Frage | Kompletter Durchlauf |
| Embeddings in Redis | `docker compose exec redis redis-cli KEYS "mha:speaker:*"` | Keys vorhanden |
| Stimmenerkennung | Zwei Personen sprechen | Unterschiedliche Identifikation |

### Latenz messen

```bash
# Whisper-Logs zeigen Transkriptions-Zeit:
docker compose logs -f whisper 2>&1 | grep -i "transcri"

# Erwartete Werte:
# CPU small-int8:         2-4 Sek
# CPU medium-int8:        5-10 Sek
# GPU large-v3-turbo:     1-2 Sek
```

---

## Fehlerbehebung

### Problem: "Wyoming Integration nicht gefunden" in HA

**Ursache:** Service auf PC 2 laeuft nicht oder Firewall blockiert den Port.

**Loesung:**
```bash
# Auf PC 2: Pruefen ob Service laeuft
docker compose ps whisper
docker compose logs whisper

# Port-Freigabe pruefen (von PC 1 aus):
nc -zv <PC2-IP> 10300
nc -zv <PC2-IP> 10200

# Falls Firewall aktiv:
sudo ufw allow 10300/tcp
sudo ufw allow 10200/tcp
```

### Problem: Sprache wird nicht erkannt / leerer Text

**Ursache:** Falsches Whisper-Modell oder Sprache.

**Loesung:**
```bash
# .env pruefen:
grep WHISPER /home/user/mindhome/assistant/.env

# Muss enthalten:
# WHISPER_LANGUAGE=de
# WHISPER_MODEL=small-int8 (oder medium-int8)

# Logs pruefen:
docker compose logs -f whisper
```

### Problem: Sehr langsame Transkription (>15 Sek)

**Ursache:** Zu grosses Modell fuer CPU, oder CPU unter Last.

**Loesung:**
```bash
# Auf kleineres Modell wechseln:
# In .env: WHISPER_MODEL=small-int8
docker compose up -d whisper

# CPU-Last pruefen:
htop
```

### Problem: GPU wird nicht genutzt (Phase 2)

**Ursache:** NVIDIA Container Toolkit nicht konfiguriert oder `COMPOSE_FILE` fehlt.

**Loesung:**
```bash
# Container Toolkit testen:
docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi

# .env pruefen:
grep COMPOSE_FILE /home/user/mindhome/assistant/.env
# Muss enthalten: COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml

grep SPEECH_DEVICE /home/user/mindhome/assistant/.env
# Muss enthalten: SPEECH_DEVICE=cuda
```

### Problem: Piper-Stimme klingt falsch / andere Sprache

**Loesung:**
```bash
# Verfuegbare deutsche Stimmen:
# de_DE-thorsten-high       (maennlich, beste Qualitaet)
# de_DE-thorsten-medium     (maennlich, schneller)
# de_DE-kerstin-noble       (weiblich)

# In .env aendern:
# PIPER_VOICE=de_DE-thorsten-high
docker compose up -d piper
```

### Problem: Kein Embedding in Redis nach Sprachbefehl

**Ursache:** Custom Handler laeuft nicht korrekt.

**Loesung:**
```bash
# Whisper-Logs pruefen (Embedding-Extraktion):
docker compose logs whisper 2>&1 | grep -i "embed"

# Redis direkt pruefen:
docker compose exec redis redis-cli KEYS "mha:speaker:*"
docker compose exec redis redis-cli GET "mha:speaker:latest_embedding"
```

---

## Technische Details

### Wyoming Protocol

| Eigenschaft | Wert |
|---|---|
| **Transport** | TCP Socket |
| **Wire Format** | JSONL Header + Binary Payload |
| **Audio Format** | Raw PCM, 16kHz, 16-bit, Mono |
| **STT Port** | 10300 (Standard) |
| **TTS Port** | 10200 (Standard) |
| **PyPI Paket** | `pip install wyoming` (v1.8.0, MIT) |

### Audio-Weg im Detail

```
1. ESP32 nimmt Audio auf (I2S Mikrofon)
2. Audio-Stream geht ueber WiFi an HA
3. HA oeffnet TCP-Verbindung zu PC2:10300
4. HA sendet Wyoming Events:
   - Transcribe (Sprache: de)
   - AudioChunk (rohe PCM bytes, repeated)
   - AudioStop
5. Unser Custom Handler auf PC2:
   a) Sammelt alle AudioChunks in einem Buffer
   b) Bei AudioStop:
      - faster-whisper transkribiert: PCM --> Text
      - ECAPA-TDNN extrahiert Embedding: PCM --> 192-dim Vektor
      - Embedding --> Redis (fuer speaker_recognition.py)
      - Transcript --> zurueck an HA (Wyoming Protocol)
6. HA leitet Text an Conversation Agent weiter
7. Conversation Agent sendet an PC2:8200 (/api/assistant/chat)
8. MindHome Assistant:
   a) Liest Embedding aus Redis
   b) speaker_recognition.py identifiziert Person
   c) Ollama/Qwen verarbeitet Anfrage
   d) Antwort-Text zurueck an HA
9. HA oeffnet TCP-Verbindung zu PC2:10200
10. HA sendet Wyoming Event:
    - Synthesize (Text der Antwort)
11. Piper auf PC2:
    - Text --> Audio (WAV)
    - AudioStart + AudioChunks + AudioStop --> zurueck an HA
12. HA spielt Audio auf dem Speaker ab
```

### Ports die auf PC 2 offen sein muessen

| Port | Service | Richtung |
|---|---|---|
| 8200 | MindHome Assistant | PC 1 → PC 2 (schon offen) |
| 10300 | Whisper STT | PC 1 → PC 2 (NEU) |
| 10200 | Piper TTS | PC 1 → PC 2 (NEU) |

### Docker-Container Uebersicht (nach Migration)

| Container | Image | Port | GPU (Phase 2) |
|---|---|---|---|
| `mindhome-assistant` | Custom Build | 8200 | Nein |
| `mha-chromadb` | chromadb/chroma:0.5.23 | 8100 (intern) | Nein |
| `mha-redis` | redis:7-alpine | 6379 (intern) | Nein |
| `mha-whisper` | Custom Build | 10300 | Ja |
| `mha-piper` | Custom Build / rhasspy | 10200 | Optional |
| `mha-autoheal` | willfarrell/autoheal | — | Nein |

### Referenz-Projekt

Community-Fork der genau Speaker Recognition mit Wyoming Whisper implementiert:
[BBriele/wyoming-faster-whisper-recognition](https://github.com/BBriele/wyoming-faster-whisper-recognition)

---

## Zusammenfassung: Wann mache ich was?

### Jetzt (Phase 1 — CPU)

| Schritt | Wo | Was | Dauer |
|---|---|---|---|
| 1.1 | PC 2 (SSH) | `git pull` — neuesten Code ziehen | ~1 Min |
| 1.2 | PC 2 (SSH) | `.env` erweitern (6 Zeilen Speech-Variablen) | ~1 Min |
| 1.3 | PC 2 (SSH) | Firewall-Ports oeffnen (10300 + 10200) | ~1 Min |
| 1.4 | PC 2 (SSH) | `docker compose build whisper` — Container bauen | ~5-10 Min |
| 1.5 | PC 2 (SSH) | `docker compose up -d` — alle starten | ~2-3 Min |
| 1.6 | PC 2 (SSH) | Warten bis alle Container "healthy" sind | ~1-3 Min |
| 1.7 | Laptop/PC 1 | Ports testen (`nc -zv PC2-IP 10300`) | ~1 Min |
| 2 | HA (Browser) | Wyoming Integration hinzufuegen (2x: STT + TTS) | ~2 Min |
| 3 | HA (Browser) | Assist Pipeline auf neues Wyoming umstellen | ~1 Min |
| 4 | HA (Browser) | Testen (Mikrofon + Satellit) | ~5 Min |
| 5 | HA (Browser) | Alte Whisper + Piper Add-ons entfernen | ~1 Min |

### Spaeter (Phase 2 — GPU)

| Schritt | Wer | Was | Dauer |
|---|---|---|---|
| 1 | Du | RTX 3090 Ti einbauen | ~15 Min |
| 2 | Du | NVIDIA Treiber installieren | ~5 Min |
| 3 | Du | NVIDIA Container Toolkit installieren | ~5 Min |
| 4 | Du | 3 Zeilen in `.env` aendern | ~1 Min |
| 5 | Du | `COMPOSE_FILE` Zeile hinzufuegen | ~1 Min |
| 6 | Du | `docker compose down && docker compose up -d` | ~1 Min |
| 7 | Du | Testen | ~5 Min |

**An Home Assistant aenderst du in Phase 2 NICHTS.**
