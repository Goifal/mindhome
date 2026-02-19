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
