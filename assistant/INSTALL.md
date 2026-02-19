# MindHome Assistant — Installationsanleitung

Komplette Anleitung: Vom leeren PC zum laufenden KI-Assistenten.

---

## Was wird installiert?

| Dienst | Aufgabe | Port |
|--------|---------|------|
| **MindHome Assistant** | KI-Gehirn (FastAPI) | 8200 |
| **Ollama** | LLM-Inferenz (Qwen 3) | 11434 |
| **ChromaDB** | Langzeitgedaechtnis (Vektor-DB) | 8100 |
| **Redis** | Arbeitsspeicher / Cache | 6379 |

Ollama laeuft nativ auf dem Host (fuer GPU-Zugriff).
Assistant, ChromaDB und Redis laufen in Docker.

---

## Voraussetzungen

### Hardware (Minimum)

| Komponente | Minimum | Empfohlen |
|------------|---------|-----------|
| CPU | 4 Kerne (x86_64) | 8 Kerne |
| RAM | 8 GB (nur 4B-Modell) | 16-32 GB (fuer 14B-Modell) |
| Festplatte | 30 GB frei | 50+ GB SSD |
| Netzwerk | LAN-Verbindung zum HA-Server | Ethernet (kein WLAN) |

### Was du brauchst bevor du anfaengst

1. **USB-Stick** (4+ GB) fuer Ubuntu-Installation
2. **Einen zweiten PC** (oder Laptop) um die Anleitung zu lesen und SSH zu machen
3. **Deine Home-Assistant IP-Adresse** (z.B. `192.168.1.100`)
4. **Einen HA Long-Lived Access Token** (Anleitung in Schritt 6)

---

## Schritt 1: Ubuntu Server installieren

### 1.1 USB-Stick erstellen

Auf deinem **anderen PC** (nicht dem leeren):

1. Lade **Ubuntu Server 24.04 LTS** herunter:
   https://ubuntu.com/download/server

2. Lade **Balena Etcher** herunter:
   https://etcher.balena.io

3. Stecke den USB-Stick ein

4. Starte Etcher:
   - "Flash from file" → die heruntergeladene Ubuntu `.iso` waehlen
   - "Select target" → deinen USB-Stick waehlen
   - "Flash!" klicken und warten

### 1.2 Ubuntu installieren

1. **USB-Stick in den leeren PC** stecken
2. **PC starten** und vom USB booten
   - Beim Starten `F12`, `F2` oder `DEL` druecken (je nach Hersteller)
   - Im Boot-Menue den USB-Stick waehlen
3. **Sprache:** English (oder Deutsch)
4. **Keyboard:** German
5. **Installation type:** Ubuntu Server (minimized)
6. **Netzwerk:** Ethernet automatisch (DHCP)
   - **Wichtig:** Notiere dir die IP-Adresse die angezeigt wird!
   - Oder vergib spaeter eine feste IP (empfohlen)
7. **Festplatte:** "Use an entire disk" → bestaetigen
8. **Benutzername:** `mindhome` (oder was du willst)
9. **Passwort:** waehle ein sicheres Passwort
10. **OpenSSH installieren:** JA (Haken setzen!)
11. **Featured Snaps:** nichts auswaehlen, weiter
12. Warten bis fertig → **"Reboot Now"**
13. USB-Stick rausziehen wenn aufgefordert

### 1.3 Erste Anmeldung

Nach dem Neustart meldet sich der PC mit dem Login-Prompt.

Melde dich an:
```
mindhome login: mindhome
Password: (dein Passwort)
```

Pruefe die IP-Adresse:
```bash
ip addr show
```

Notiere die Adresse (z.B. `192.168.1.50`).

---

## Schritt 2: System aktualisieren

```bash
sudo apt update && sudo apt upgrade -y
```

Wenn gefragt wird ob Dienste neu gestartet werden sollen → **Enter** druecken (Standard).

Falls ein Kernel-Update kam:
```bash
sudo reboot
```

---

## Schritt 3: Git installieren und Repo klonen

```bash
sudo apt install -y git
```

```bash
git clone https://github.com/Goifal/mindhome.git
```

```bash
cd mindhome/assistant
```

---

## Schritt 4: Automatische Installation starten

Das Installationsskript erledigt alles Weitere:

```bash
chmod +x install.sh
./install.sh
```

### Was passiert automatisch:

| Schritt | Was |
|---------|-----|
| 1/6 | Docker & Docker Compose installieren |
| 2/6 | Ollama installieren und fuer Netzwerk konfigurieren |
| 3/6 | LLM-Modelle herunterladen (Qwen 3 4B + optional 14B) |
| 4/6 | `.env` Konfigurationsdatei erstellen |
| 5/6 | Daten-Verzeichnisse anlegen |
| 6/6 | Docker-Container bauen und starten |

### Wichtige Fragen waehrend der Installation:

**"Qwen 3 14B herunterladen?"**
- `j` wenn du 16+ GB RAM hast (empfohlen — viel schlauer)
- `n` wenn du nur 8 GB RAM hast

**".env jetzt bearbeiten?"**
- `j` waehlen! Hier musst du deine HA-Daten eintragen (siehe Schritt 6)

### Docker-Neuanmeldung

Falls Docker frisch installiert wurde, stoppt das Skript mit:
```
WICHTIG: Log dich aus und wieder ein, damit Docker ohne sudo geht.
```

Dann:
```bash
exit
```

Neu anmelden und nochmal starten:
```bash
cd mindhome/assistant
./install.sh
```

---

## Schritt 5: Feste IP-Adresse vergeben (empfohlen)

Damit der Assistant-PC immer unter der gleichen Adresse erreichbar ist:

```bash
sudo nano /etc/netplan/50-cloud-init.yaml
```

Ersetze den Inhalt mit (IP-Adressen anpassen!):

```yaml
network:
  version: 2
  ethernets:
    eno1:          # ← dein Interface-Name (siehe "ip addr show")
      dhcp4: no
      addresses:
        - 192.168.1.50/24        # ← deine gewuenschte IP
      routes:
        - to: default
          via: 192.168.1.1       # ← dein Router
      nameservers:
        addresses:
          - 192.168.1.1          # ← dein Router (oder 8.8.8.8)
```

Anwenden:
```bash
sudo netplan apply
```

---

## Schritt 6: Firewall einrichten

Ubuntu hat **UFW** (Uncomplicated Firewall) vorinstalliert, aber standardmaessig deaktiviert.
Du solltest die Firewall aktivieren und nur die noetigen Ports oeffnen.

### 6.1 Firewall aktivieren und Ports freigeben

```bash
# SSH zuerst! Sonst sperrst du dich aus
sudo ufw allow 22/tcp comment "SSH"

# MindHome Assistant API (muss vom HA-Server erreichbar sein)
sudo ufw allow 8200/tcp comment "MindHome Assistant"

# Ollama (muss vom HA-Server erreichbar sein)
sudo ufw allow 11434/tcp comment "Ollama LLM"

# Firewall einschalten
sudo ufw enable
```

Bei der Frage `Command may disrupt existing SSH connections. Proceed with operation (y|n)?` → **y**

### 6.2 Pruefen

```bash
sudo ufw status
```

Erwartete Ausgabe:
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere       # SSH
8200/tcp                   ALLOW       Anywhere       # MindHome Assistant
11434/tcp                  ALLOW       Anywhere       # Ollama LLM
```

### 6.3 Optional: Nur Heimnetzwerk erlauben (sicherer)

Statt die Ports fuer alle zu oeffnen, kannst du sie auf dein lokales Netz beschraenken:

```bash
# Erst die offenen Regeln entfernen
sudo ufw delete allow 8200/tcp
sudo ufw delete allow 11434/tcp

# Nur fuer dein Heimnetz erlauben (Adresse anpassen!)
sudo ufw allow from 192.168.1.0/24 to any port 8200 comment "MindHome lokal"
sudo ufw allow from 192.168.1.0/24 to any port 11434 comment "Ollama lokal"
```

### Ports die NICHT geoeffnet werden muessen

| Port | Dienst | Warum nicht |
|------|--------|-------------|
| 6379 | Redis | Nur intern (Docker-Netzwerk) |
| 8100 | ChromaDB | Nur intern (Docker-Netzwerk) |

Redis und ChromaDB werden nur vom Assistant-Container angesprochen,
der im selben Docker-Netzwerk laeuft. Von aussen muss da niemand ran.

---

## Schritt 7: Home Assistant Token erstellen

Auf deinem **Home Assistant** (im Browser):

1. Gehe zu: `http://DEINE-HA-IP:8123`
2. Klicke auf deinen **Benutzernamen** (unten links)
3. Scrolle ganz nach unten zu **"Langlebige Zugriffstoken"**
4. Klicke **"Token erstellen"**
5. Name: `MindHome Assistant`
6. **Token kopieren** (wird nur einmal angezeigt!)

---

## Schritt 8: .env Datei konfigurieren

Falls du die `.env` nicht waehrend der Installation bearbeitet hast:

```bash
cd ~/mindhome/assistant
nano .env
```

**Diese drei Werte MUSST du anpassen:**

```env
# Deine Home Assistant IP und Port
HA_URL=http://192.168.1.100:8123

# Der Token aus Schritt 6
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc123...

# Dein Name
USER_NAME=Max
```

**Optionale Einstellungen:**

```env
# MindHome Add-on Verbindung (nur wenn MindHome Add-on installiert)
MINDHOME_URL=http://192.168.1.100:8099

# Assistent-Name (Standard: Jarvis)
ASSISTANT_NAME=Jarvis
```

**Nicht aendern** (werden automatisch gesetzt):

```env
OLLAMA_URL=http://host.docker.internal:11434
REDIS_URL=redis://redis:6379
CHROMA_URL=http://chromadb:8000
```

Speichern: `Strg+O` → `Enter` → `Strg+X`

Nach Aenderungen neu starten:
```bash
cd ~/mindhome/assistant
docker compose restart assistant
```

---

## Schritt 9: Pruefen ob alles laeuft

### Container-Status

```bash
docker compose ps
```

Erwartete Ausgabe:
```
NAME                 STATUS              PORTS
mindhome-assistant   Up (healthy)        0.0.0.0:8200->8200/tcp
mha-chromadb         Up (healthy)        0.0.0.0:8100->8000/tcp
mha-redis            Up (healthy)        0.0.0.0:6379->6379/tcp
```

Alle drei muessen **"Up (healthy)"** sein.

### Health-Check

```bash
curl http://localhost:8200/api/assistant/health
```

### Erster Test

```bash
curl -X POST http://localhost:8200/api/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Hallo, wie geht es dir?", "person": "Max"}'
```

Du solltest eine JSON-Antwort mit Jarvis' Antwort bekommen.

### Ollama pruefen

```bash
ollama list
```

Sollte mindestens `qwen3:4b` zeigen.

---

## Schritt 10: Autostart einrichten

Die Docker-Container starten automatisch nach einem Neustart (dank `restart: unless-stopped`).

Ollama startet ebenfalls automatisch als Systemd-Service.

Pruefe nach einem Neustart:
```bash
sudo reboot
```

Nach 1-2 Minuten einloggen und pruefen:
```bash
docker compose -f ~/mindhome/assistant/docker-compose.yml ps
curl http://localhost:8200/api/assistant/health
```

---

## Zusammenfassung: Alle Befehle auf einen Blick

```bash
# 1. System aktualisieren
sudo apt update && sudo apt upgrade -y

# 2. Git installieren + Repo klonen
sudo apt install -y git
git clone https://github.com/Goifal/mindhome.git

# 3. Installation starten
cd mindhome/assistant
chmod +x install.sh
./install.sh

# 4. .env anpassen
nano .env

# 5. Neustart nach .env-Aenderung
docker compose restart assistant

# 6. Pruefen
docker compose ps
curl http://localhost:8200/api/assistant/health
```

---

## Nuetzliche Befehle

| Befehl | Was |
|--------|-----|
| `docker compose ps` | Status aller Container |
| `docker compose logs -f assistant` | Live-Logs vom Assistant |
| `docker compose logs -f` | Live-Logs von ALLEN Containern |
| `docker compose restart` | Alle Container neustarten |
| `docker compose restart assistant` | Nur Assistant neustarten |
| `docker compose down` | Alles stoppen |
| `docker compose up -d` | Alles starten |
| `docker compose build && docker compose up -d` | Neu bauen nach Code-Aenderung |
| `ollama list` | Installierte LLM-Modelle anzeigen |
| `ollama pull qwen3:14b` | Weiteres Modell herunterladen |

---

## Fehlerbehebung

### "Cannot connect to Home Assistant"

```bash
# Testen ob HA erreichbar ist
curl -s -o /dev/null -w "%{http_code}" http://DEINE-HA-IP:8123/api/
```

→ Sollte `401` zeigen (erreichbar, aber nicht authentifiziert)
→ `000` = HA ist nicht erreichbar (falsche IP? Firewall?)

### "Ollama model not found"

```bash
ollama list                  # welche Modelle sind da?
ollama pull qwen3:4b         # fehlendes Modell laden
sudo systemctl restart ollama
```

### Container startet nicht (unhealthy)

```bash
docker compose logs chromadb  # oder redis, assistant
docker compose down
docker compose up -d
```

### Alles zuruecksetzen (Neustart)

```bash
cd ~/mindhome/assistant
docker compose down -v         # Container + Volumes loeschen
rm -rf data/                   # Alle Daten loeschen
docker compose build --no-cache
docker compose up -d
```

**Achtung:** Das loescht alle Daten (Gedaechtnis, Cache, Baselines)!

### Port schon belegt

```bash
sudo lsof -i :8200            # Wer belegt Port 8200?
sudo lsof -i :6379            # Wer belegt Port 6379?
```

---

## Netzwerk-Architektur

```
┌─────────────────────────────────────────────────────────┐
│                    Dein Heimnetzwerk                    │
│                                                         │
│  ┌──────────────────┐       ┌────────────────────────┐  │
│  │  Home Assistant   │       │   Assistant-PC          │  │
│  │  (PC 1 / NUC)    │       │   (Ubuntu Server)       │  │
│  │                   │       │                         │  │
│  │  :8123 HA Web UI  │◄─────►  :8200 Assistant API    │  │
│  │  :8099 MindHome   │       │  :11434 Ollama (nativ) │  │
│  │                   │       │  :8100 ChromaDB         │  │
│  │                   │       │  :6379 Redis            │  │
│  └──────────────────┘       └────────────────────────┘  │
│         ▲                              ▲                │
│         │          ┌──────┐            │                │
│         └──────────│Router│────────────┘                │
│                    └──────┘                             │
└─────────────────────────────────────────────────────────┘
```

Der Assistant-PC kommuniziert mit Home Assistant ueber das lokale Netzwerk.
Kein Internet noetig fuer den Betrieb (nur fuer Installation).

---
---

# Konfiguration — Alles einstellen

Nach der Installation muss der Assistant konfiguriert werden.
Es gibt **drei Schritte**:

1. `.env` Datei — Pflicht-Verbindungsdaten (einmalig per Terminal)
2. MindHome Add-on — Assistant-URL setzen (einmalig im Add-on UI)
3. Jarvis Dashboard — Alle Einstellungen bequem im Browser

---

## Schritt 1: .env — Pflicht-Einstellungen (Terminal)

Die `.env` Datei enthaelt die Verbindungsdaten zu Home Assistant.
Das muss **einmalig per Terminal** gesetzt werden, bevor der Assistant starten kann.

```bash
nano ~/mindhome/assistant/.env
```

### MUSS gesetzt werden:

```env
# 1. Home Assistant Adresse
HA_URL=http://192.168.1.100:8123

# 2. Long-Lived Access Token (aus HA → Profil → Langlebige Zugriffstoken)
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dein.token.hier

# 3. Dein Name (so kennt Jarvis dich)
USER_NAME=Max
```

**So erstellst du den HA-Token:**
1. Home Assistant oeffnen → unten links auf deinen Benutzernamen klicken
2. Runterscrollen zu "Langlebige Zugriffstoken"
3. "Token erstellen" → Name: `MindHome` → Token kopieren (wird nur einmal angezeigt!)

### SOLLTE gesetzt werden:

```env
# MindHome Add-on Adresse (wenn installiert)
MINDHOME_URL=http://192.168.1.100:8099

# Assistent-Name (Standard: Jarvis)
ASSISTANT_NAME=Jarvis
```

### NICHT aendern (funktioniert automatisch):

```env
OLLAMA_URL=http://host.docker.internal:11434
REDIS_URL=redis://redis:6379
CHROMA_URL=http://chromadb:8000
ASSISTANT_HOST=0.0.0.0
ASSISTANT_PORT=8200
```

Nach der Aenderung neu starten:
```bash
cd ~/mindhome/assistant && docker compose restart assistant
```

---

## Schritt 2: MindHome Add-on — Assistant verbinden

Das MindHome Add-on auf deinem Home Assistant muss wissen, wo der Assistant-PC laeuft.

1. Oeffne das MindHome Add-on im Browser (z.B. `http://192.168.1.100:8099`)
2. Gehe zu **Einstellungen**
3. Trage unter **"Assistant URL"** die Adresse deines Assistant-PCs ein:
   ```
   http://192.168.1.50:8200
   ```
   (Ersetze `192.168.1.50` mit der IP deines Assistant-PCs)
4. Klicke **Speichern**
5. Der Verbindungsstatus sollte "Verbunden" anzeigen

---

## Schritt 3: Jarvis Dashboard — Alle Einstellungen im Browser

**Alle weiteren Einstellungen** werden ueber das **Jarvis Dashboard** gemacht.
Kein Terminal noetig — alles laeuft im Browser mit Speichern-Knopf.

### Dashboard oeffnen:

```
http://<assistant-ip>:8200/ui/
```

Beispiel: `http://192.168.1.50:8200/ui/`

### Erster Aufruf — PIN setzen:

Beim ersten Oeffnen wirst du aufgefordert, einen **PIN** zu setzen (min. 4 Zeichen).
Du bekommst einen **Recovery-Key** — diesen sicher aufbewahren!

### Die 8 Einstellungs-Tabs:

Das Dashboard hat 8 Tabs. Hier ist was du wo findest und was du anpassen solltest:

---

### Tab 1: Allgemein

| Einstellung | Was | Empfehlung |
|-------------|-----|------------|
| Name | Wie heisst dein Assistent | "Jarvis" (Standard) oder frei waehlbar |
| Sprache | "de" oder "en" | "de" |
| Autonomie-Level | Wie eigenstaendig Jarvis handelt | Level 2 (Butler) |
| Modelle | Welche LLMs fuer welche Aufgaben | Siehe unten |

**Autonomie-Level erklaert:**

| Level | Name | Was Jarvis darf |
|-------|------|-----------------|
| 1 | Assistent | Nur auf Befehle reagieren |
| 2 | Butler | + Proaktive Infos geben (empfohlen) |
| 3 | Mitbewohner | + Kleine Aenderungen selbst machen |
| 4 | Vertrauter | + Routinen anpassen |
| 5 | Autopilot | + Automationen erstellen |

**Modelle:**
Jarvis waehlt automatisch das passende Modell:
- "Licht an" → Fast-Modell (`qwen3:4b`)
- "Was meinst du zum Wetter?" → Smart-Modell (`qwen3:14b`)
- "Erklaere mir den Unterschied zwischen..." → Deep-Modell (`qwen3:32b`)

Wenn du nur `qwen3:4b` installiert hast, setze alle drei auf `qwen3:4b`.

---

### Tab 2: Persoenlichkeit

| Einstellung | Was | Standard |
|-------------|-----|----------|
| Stil | butler / minimal / freundlich | butler |
| Sarkasmus | 1-5 (1=sachlich, 5=Vollgas Ironie) | 3 |
| Meinungen | 0-3 (0=still, 3=redselig) | 2 |
| Selbstironie | Jarvis macht Witze ueber sich | an |
| Charakter-Entwicklung | Jarvis wird mit der Zeit persoenlicher | an |

**Tageszeit-Verhalten** (funktioniert automatisch):

| Zeit | Stil |
|------|------|
| 05-08 Uhr | Ruhig, minimal, kein Humor |
| 08-12 Uhr | Sachlich, effizient |
| 12-18 Uhr | Normal, trockener Humor |
| 18-22 Uhr | Entspannt, mehr Humor |
| 22-05 Uhr | Nur Notfaelle, Fluestern |

---

### Tab 3: Gedaechtnis

Jarvis merkt sich Fakten, Vorlieben und Gespraechsverlaeufe.
Die Standard-Einstellungen sind gut — nur aendern wenn noetig.

---

### Tab 4: Stimmung

Jarvis erkennt Stress, Muedigkeit und Ungeduld am Text.
Die Standard-Keywords und Schwellwerte passen fuer Deutsch.

---

### Tab 5: Raeume (SOLLTE anpassen)

Hier konfigurierst du **welche Geraete in welchem Raum** stehen.
Das ist wichtig fuer Multi-Room Audio und Praesenz-Erkennung.

**Was du eintragen solltest:**

1. **Raum-Speaker** — Welcher Lautsprecher steht wo?
   - Beispiel: Wohnzimmer → `media_player.wohnzimmer_speaker`
2. **Bewegungsmelder** — Welcher Sensor erkennt Bewegung wo?
   - Beispiel: Wohnzimmer → `binary_sensor.wohnzimmer_motion`
3. **Aktivitaets-Sensoren** (optional):
   - Bett-Sensor → Schlaf-Erkennung
   - PC-Sensor → Fokus-Erkennung
   - Mikrofon-Sensor → Telefonat-Erkennung

**So findest du deine Entity-IDs:**
1. Home Assistant → Einstellungen → Geraete & Dienste → Entitaeten
2. Oder: Entwicklerwerkzeuge → Zustande → Suchen
3. Oder: Im Dashboard unter dem Tab "Entitaeten" (listet alle HA-Entitaeten auf)

---

### Tab 6: Stimme

| Einstellung | Was | Standard |
|-------------|-----|----------|
| Lautstaerke Tag | Sprachausgabe tagsueber | 80% |
| Lautstaerke Abend | Ab 22 Uhr | 50% |
| Lautstaerke Nacht | Nach Mitternacht | 30% |
| Lautstaerke Notfall | Immer laut | 100% |
| Fluestermodus | Wenn jemand schlaeft | 15% |
| Sounds | Akustische Signale (Bestaetigungs-Ping etc.) | an |

---

### Tab 7: Routinen

**Morgen-Briefing:**
- Aktivierbar: Jarvis begruesst dich morgens mit Wetter, Terminen, Haus-Status
- Begleit-Aktionen: Rolladen hoch, Licht sanft an

**Gute-Nacht-Routine:**
- Trigger: "Gute Nacht" / "Ich gehe schlafen"
- Sicherheits-Checks: Offene Fenster, Tueren, Alarm-Status
- Aktionen: Lichter aus, Heizung Nacht-Modus, Rolladen runter, Alarm scharf

**Gaeste-Modus:**
- Trigger: "Ich habe Besuch"
- Wirkung: Keine persoenlichen Infos, formeller Ton, Sicherheit eingeschraenkt

**Zeitueberwachung:**
- Ofen laeuft > 60 Min → Warnung
- Buegeleisen > 30 Min → Warnung
- Fenster offen bei Kaelte > 2h → Warnung
- PC ohne Pause > 6h → "Mach mal Pause"

---

### Tab 8: Sicherheit & Heizung (SOLLTE pruefen)

**Heizungsmodus** (SOLLTE als erstes einstellen):

| Modus | Beschreibung |
|-------|-------------|
| Raumthermostate | Einzelraumregelung — jeder Raum hat eigenen Thermostat |
| Heizkurve | Feste Heizkurve, nur Vorlauftemperatur-Offset (±5°C) steuerbar |

Bei **Heizkurve** zusaetzlich eintragen:
- Entity-ID der Heizung (z.B. `climate.panasonic_heat_pump_main_z1_temp`)
- Offset-Grenzen (Standard: -5 bis +5)
- Nacht-Offset (Standard: -2)
- Abwesenheits-Offset (Standard: -3)

**Bestaetigungs-Pflicht:**
Bestimmte Aktionen brauchen eine Bestaetigung:
- Tuer aufschliessen
- Alarm deaktivieren
- Heizung komplett ausschalten

**Klima-Grenzen** (nur bei Raumthermostat-Modus):
- Minimum: 15°C (nie kaelter heizen)
- Maximum: 28°C (nie waermer heizen)

**Vertrauensstufen** (bei mehreren Personen im Haushalt):

| Level | Wer | Darf |
|-------|-----|------|
| 0 | Gast | Licht, Heizung, Musik |
| 1 | Mitbewohner | Alles ausser Alarm/Schloss |
| 2 | Owner | Alles |

---

## Was funktioniert OHNE Konfiguration

Diese Features laufen sofort nach Schritt 1 + 2 — kein Dashboard noetig:

| Feature | Warum |
|---------|-------|
| Chat / Gespraeche | Braucht nur HA-Token |
| Licht steuern | Findet `light.*` automatisch |
| Heizung steuern | Findet `climate.*` automatisch |
| Rolladen steuern | Findet `cover.*` automatisch |
| Szenen aktivieren | Entdeckt `scene.*` automatisch |
| Tuerschloss | Findet `lock.*` automatisch |
| Gedaechtnis | Redis + ChromaDB laufen in Docker |
| Persoenlichkeit | Defaults funktionieren |
| Stimmungserkennung | Analysiert Text automatisch |
| Koch-Assistent | Braucht nur LLM |
| Anomalie-Erkennung | Ueberwacht alle Sensoren automatisch |

---

## Konfigurations-Checkliste

### Pflicht (laeuft sonst nicht):

- [ ] `.env`: `HA_URL` = IP deines Home Assistant
- [ ] `.env`: `HA_TOKEN` = Langlebiger Zugriffstoken
- [ ] `.env`: `USER_NAME` = Dein Vorname
- [ ] MindHome Add-on: Assistant URL eintragen
- [ ] Firewall: Port 8200 und 11434 offen
- [ ] Ollama: Mindestens `qwen3:4b` installiert

### Empfohlen (im Jarvis Dashboard unter `http://<assistant-ip>:8200/ui/`):

- [ ] Tab "Sicherheit": Heizungsmodus waehlen (Raumthermostat oder Heizkurve)
- [ ] Tab "Sicherheit": Bei Heizkurve → Entity-ID und Offsets eintragen
- [ ] Tab "Allgemein": Autonomie-Level setzen (2 empfohlen)
- [ ] Tab "Raeume": Raum-Speaker zuordnen
- [ ] Tab "Raeume": Bewegungsmelder zuordnen
- [ ] Tab "Raeume": Aktivitaets-Sensoren eintragen
- [ ] Tab "Sicherheit": Trust-Levels setzen (bei mehreren Bewohnern)

### Optional (Feintuning im Dashboard):

- [ ] Tab "Persoenlichkeit": Sarkasmus, Meinungen anpassen
- [ ] Tab "Stimme": Lautstaerke-Stufen anpassen
- [ ] Tab "Routinen": Gute-Nacht-Checks konfigurieren
- [ ] Tab "Routinen": Morgen-Briefing Module waehlen
- [ ] Tab "Routinen": Zeitueberwachungs-Schwellen anpassen
