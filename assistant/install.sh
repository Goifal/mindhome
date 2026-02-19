#!/bin/bash
# ============================================================
# MindHome Assistant — Setup & Installation
# Vom frischen Ubuntu Server zum laufenden KI-Assistenten
#
# Unterstuetzt Dual-SSD:
#   SSD 1 (NVMe): System + Ollama + Modelle
#   SSD 2 (SATA): Daten (ChromaDB, Redis, Uploads, Backups, Logs)
#
# Kann auf jedem PC ausgefuehrt werden — nichts ist hardcoded.
# ============================================================

set -euo pipefail

# --- Farben ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# --- Hilfsfunktionen ---
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARNUNG]${NC} $*"; }
error()   { echo -e "${RED}[FEHLER]${NC} $*"; }
step()    { echo ""; echo -e "${CYAN}${BOLD}$*${NC}"; echo ""; }

ask_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local suffix
    if [ "$default" = "j" ]; then suffix="(J/n)"; else suffix="(j/N)"; fi
    read -p "  $prompt $suffix: " -r answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Jj]$ ]]
}

MHA_DIR="$(cd "$(dirname "$0")" && pwd)"
STEPS_TOTAL=8

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}    MindHome Assistant — Setup & Installation${NC}"
echo -e "${BLUE}    Lokaler KI-Sprachassistent mit Dual-SSD Support${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# ============================================================
# Schritt 1: System pruefen
# ============================================================
step "[1/$STEPS_TOTAL] System pruefen..."

if [ "$(id -u)" -eq 0 ]; then
    error "Bitte NICHT als root ausfuehren. Nutze deinen normalen User."
    echo "  Richtig: ./install.sh"
    echo "  Falsch:  sudo ./install.sh"
    exit 1
fi

# Ubuntu-Version pruefen
if [ -f /etc/os-release ]; then
    . /etc/os-release
    info "OS: $PRETTY_NAME"
else
    warn "Konnte OS nicht erkennen. Script ist fuer Ubuntu Server 24.04 LTS gedacht."
fi

# RAM pruefen
TOTAL_RAM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
info "RAM: ${TOTAL_RAM_GB} GB"
if [ "$TOTAL_RAM_GB" -lt 8 ]; then
    warn "Weniger als 8 GB RAM. Nur das kleine Modell (qwen3:4b) wird funktionieren."
fi

# CPU pruefen
CPU_CORES=$(nproc)
CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)
info "CPU: $CPU_MODEL ($CPU_CORES Kerne)"

# GPU pruefen
if command -v nvidia-smi &> /dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "nicht erkannt")
    info "GPU: $GPU_INFO"
else
    info "GPU: Keine NVIDIA-GPU erkannt (Ollama nutzt CPU)"
    info "  Falls du eine NVIDIA-GPU hast, installiere zuerst die Treiber:"
    info "  sudo apt install -y nvidia-driver-535"
fi

success "System-Check abgeschlossen"

# ============================================================
# Schritt 2: Daten-SSD einrichten
# ============================================================
step "[2/$STEPS_TOTAL] Daten-SSD einrichten..."

# Pruefen ob /mnt/data bereits gemountet ist
if mountpoint -q /mnt/data 2>/dev/null; then
    success "/mnt/data ist bereits gemountet"
    info "$(df -h /mnt/data | tail -1)"
    DATA_DIR="/mnt/data"
else
    echo "  MindHome nutzt zwei SSDs:"
    echo "    SSD 1: System + Ollama + Modelle (die, von der Ubuntu gebootet hat)"
    echo "    SSD 2: Daten (ChromaDB, Redis, Uploads, Backups)"
    echo ""

    if ask_yes_no "Hast du eine zweite SSD/Festplatte fuer Daten?" "j"; then
        echo ""
        info "Verfuegbare Laufwerke:"
        echo ""

        # Boot-Disk ermitteln (die mit /)
        BOOT_DISK=$(lsblk -ndo PKNAME "$(findmnt -n -o SOURCE /)" 2>/dev/null || echo "")
        if [ -z "$BOOT_DISK" ]; then
            BOOT_DISK=$(lsblk -ndo NAME "$(findmnt -n -o SOURCE /)" 2>/dev/null | sed 's/[0-9]*$//' || echo "")
        fi

        # Alle Disks anzeigen (ohne Boot-Disk, ohne Loop/RAM)
        echo "  ---------------------------------------------------------------"
        printf "  %-12s %-8s %-10s %s\n" "DEVICE" "GROESSE" "TYP" "MODELL"
        echo "  ---------------------------------------------------------------"

        AVAILABLE_DISKS=()
        while IFS= read -r line; do
            DISK_NAME=$(echo "$line" | awk '{print $1}')
            DISK_SIZE=$(echo "$line" | awk '{print $2}')
            DISK_TYPE=$(echo "$line" | awk '{print $3}')
            DISK_MODEL=$(echo "$line" | awk '{$1=$2=$3=""; print $0}' | xargs)

            # Boot-Disk ueberspringen
            if [ "$DISK_NAME" = "$BOOT_DISK" ]; then
                printf "  %-12s %-8s %-10s %s ${YELLOW}(Boot — uebersprungen)${NC}\n" \
                    "$DISK_NAME" "$DISK_SIZE" "$DISK_TYPE" "$DISK_MODEL"
                continue
            fi

            AVAILABLE_DISKS+=("$DISK_NAME")
            printf "  %-12s %-8s %-10s %s\n" "$DISK_NAME" "$DISK_SIZE" "$DISK_TYPE" "$DISK_MODEL"
        done < <(lsblk -dnpo NAME,SIZE,TYPE,MODEL | grep -E 'disk' | awk '{gsub("/dev/","",$1); print}')

        echo "  ---------------------------------------------------------------"
        echo ""

        if [ ${#AVAILABLE_DISKS[@]} -eq 0 ]; then
            warn "Keine zusaetzlichen Laufwerke gefunden."
            warn "Daten werden lokal gespeichert (${MHA_DIR}/data)"
            DATA_DIR="${MHA_DIR}/data"
        else
            # Disk auswaehlen
            read -p "  Welches Laufwerk soll fuer Daten genutzt werden? (z.B. ${AVAILABLE_DISKS[0]}): " CHOSEN_DISK
            CHOSEN_DISK="${CHOSEN_DISK:-${AVAILABLE_DISKS[0]}}"
            CHOSEN_DEV="/dev/${CHOSEN_DISK}"

            # Pruefen ob Device existiert
            if [ ! -b "$CHOSEN_DEV" ]; then
                error "Device $CHOSEN_DEV existiert nicht!"
                exit 1
            fi

            # Info zum gewaehlten Laufwerk
            DISK_SIZE=$(lsblk -dnbo SIZE "$CHOSEN_DEV" | awk '{printf "%.0f", $1/1024/1024/1024}')
            echo ""
            info "Gewaehltes Laufwerk: $CHOSEN_DEV (${DISK_SIZE} GB)"

            # Pruefen ob bereits ein Dateisystem existiert
            EXISTING_FS=$(lsblk -nfo FSTYPE "$CHOSEN_DEV" | head -1 | xargs)
            FIRST_PARTITION="${CHOSEN_DEV}1"

            if [ -n "$EXISTING_FS" ] || ([ -b "$FIRST_PARTITION" ] && [ -n "$(lsblk -nfo FSTYPE "$FIRST_PARTITION" 2>/dev/null | head -1 | xargs)" ]); then
                # Disk hat bereits Dateisystem
                if [ -n "$EXISTING_FS" ]; then
                    MOUNT_DEV="$CHOSEN_DEV"
                    FS_TYPE="$EXISTING_FS"
                else
                    MOUNT_DEV="$FIRST_PARTITION"
                    FS_TYPE=$(lsblk -nfo FSTYPE "$FIRST_PARTITION" | head -1 | xargs)
                fi

                warn "Laufwerk hat bereits ein Dateisystem: $FS_TYPE"
                echo ""
                echo "  Optionen:"
                echo "    1) Bestehendes Dateisystem nutzen (Daten bleiben erhalten)"
                echo "    2) Neu formatieren (ALLE DATEN WERDEN GELOESCHT)"
                echo "    3) Abbrechen"
                echo ""
                read -p "  Wahl (1/2/3): " FS_CHOICE

                case "$FS_CHOICE" in
                    1)
                        info "Nutze bestehendes Dateisystem auf $MOUNT_DEV"
                        ;;
                    2)
                        echo ""
                        warn "ACHTUNG: ALLE Daten auf $CHOSEN_DEV werden UNWIDERRUFLICH geloescht!"
                        echo ""
                        read -p "  Zum Bestaetigen 'JA' eingeben: " CONFIRM
                        if [ "$CONFIRM" != "JA" ]; then
                            info "Abgebrochen. Nichts wurde geaendert."
                            exit 0
                        fi
                        info "Formatiere $CHOSEN_DEV mit ext4..."
                        sudo wipefs -a "$CHOSEN_DEV"
                        sudo mkfs.ext4 -L mindhome-data "$CHOSEN_DEV"
                        MOUNT_DEV="$CHOSEN_DEV"
                        success "Formatierung abgeschlossen"
                        ;;
                    *)
                        info "Abgebrochen."
                        exit 0
                        ;;
                esac
            else
                # Leere Disk — formatieren
                info "Laufwerk ist leer. Formatiere mit ext4..."
                echo ""
                read -p "  Zum Bestaetigen 'JA' eingeben: " CONFIRM
                if [ "$CONFIRM" != "JA" ]; then
                    info "Abgebrochen. Nichts wurde geaendert."
                    exit 0
                fi
                sudo mkfs.ext4 -L mindhome-data "$CHOSEN_DEV"
                MOUNT_DEV="$CHOSEN_DEV"
                success "Formatierung abgeschlossen"
            fi

            # Mountpoint erstellen und mounten
            sudo mkdir -p /mnt/data
            sudo mount "$MOUNT_DEV" /mnt/data
            sudo chown "$(id -u):$(id -g)" /mnt/data
            success "Gemountet: $MOUNT_DEV → /mnt/data"

            # fstab-Eintrag pruefen/erstellen
            UUID=$(sudo blkid -s UUID -o value "$MOUNT_DEV")
            if ! grep -q "$UUID" /etc/fstab 2>/dev/null; then
                echo "UUID=$UUID  /mnt/data  ext4  defaults,noatime  0  2" | sudo tee -a /etc/fstab > /dev/null
                success "fstab-Eintrag erstellt (automatisch beim Booten)"
            else
                success "fstab-Eintrag existiert bereits"
            fi

            DATA_DIR="/mnt/data"
        fi
    else
        info "Kein Daten-Laufwerk. Daten werden lokal gespeichert."
        DATA_DIR="${MHA_DIR}/data"
    fi
fi

# DATA_DIR festlegen falls noch nicht gesetzt
DATA_DIR="${DATA_DIR:-/mnt/data}"
success "Daten-Verzeichnis: $DATA_DIR"

# ============================================================
# Schritt 3: Docker installieren
# ============================================================
step "[3/$STEPS_TOTAL] Docker pruefen..."

if ! command -v docker &> /dev/null; then
    info "Docker nicht gefunden. Installiere Docker..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) \
        signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER"
    success "Docker installiert"
    echo ""
    warn "WICHTIG: Log dich aus und wieder ein, damit Docker ohne sudo geht."
    warn "Danach fuehre install.sh nochmal aus."
    echo ""
    echo "  exit"
    echo "  # Neu anmelden, dann:"
    echo "  cd $(pwd) && ./install.sh"
    exit 0
fi

success "Docker: OK ($(docker --version | awk '{print $3}' | tr -d ','))"

if docker compose version &> /dev/null; then
    success "Docker Compose: OK"
else
    error "Docker Compose nicht gefunden. Bitte Docker aktualisieren."
    exit 1
fi

# ============================================================
# Schritt 4: Ollama installieren
# ============================================================
step "[4/$STEPS_TOTAL] Ollama pruefen..."

if ! command -v ollama &> /dev/null; then
    info "Ollama nicht gefunden. Installiere..."
    curl -fsSL https://ollama.ai/install.sh | sh
    success "Ollama installiert"
else
    OLLAMA_VERSION=$(ollama --version 2>/dev/null | awk '{print $NF}' || echo "?")
    success "Ollama: OK ($OLLAMA_VERSION)"
fi

# Ollama von aussen erreichbar machen
if ! grep -q "OLLAMA_HOST=0.0.0.0" /etc/systemd/system/ollama.service.d/override.conf 2>/dev/null; then
    info "Konfiguriere Ollama fuer Netzwerk-Zugriff..."
    sudo mkdir -p /etc/systemd/system/ollama.service.d/
    cat <<'OLLAMA_OVERRIDE' | sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
OLLAMA_OVERRIDE
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
    success "Ollama hoert auf 0.0.0.0:11434"
fi

# Warte bis Ollama bereit ist
info "Warte auf Ollama..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 15 ]; then
        error "Ollama antwortet nicht. Pruefe: sudo systemctl status ollama"
        exit 1
    fi
    sleep 2
done
success "Ollama ist bereit"

# ============================================================
# Schritt 5: LLM-Modelle herunterladen
# ============================================================
step "[5/$STEPS_TOTAL] LLM-Modelle pruefen..."

# Modell-Verzeichnis anzeigen
MODELS_DIR=$(ollama show --modelfile qwen3:4b 2>/dev/null | grep -oP '(?<=FROM ).*' | head -1 | xargs dirname 2>/dev/null || echo "${HOME}/.ollama/models")
info "Modell-Verzeichnis: ${HOME}/.ollama/models (SSD 1)"

if ! ollama list 2>/dev/null | grep -q "qwen3:4b"; then
    info "Lade Qwen 3 4B (schnelles Modell, ~3 GB)..."
    ollama pull qwen3:4b
    success "Qwen 3 4B: OK"
else
    success "Qwen 3 4B: bereits vorhanden"
fi

if ! ollama list 2>/dev/null | grep -q "qwen3:14b"; then
    echo ""
    echo "  Das schlaue Modell (Qwen 3 14B, ~9 GB) ist deutlich besser fuer"
    echo "  komplexe Fragen und Konversation. Braucht ~16 GB RAM."
    echo ""
    if [ "$TOTAL_RAM_GB" -ge 16 ]; then
        info "Du hast ${TOTAL_RAM_GB} GB RAM — 14B sollte gut laufen."
    else
        warn "Du hast nur ${TOTAL_RAM_GB} GB RAM — 14B koennte langsam sein."
    fi
    if ask_yes_no "Qwen 3 14B herunterladen?" "j"; then
        ollama pull qwen3:14b
        success "Qwen 3 14B: OK"
    else
        info "Uebersprungen. Spaeter: ollama pull qwen3:14b"
    fi
else
    success "Qwen 3 14B: bereits vorhanden"
fi

echo ""
info "Installierte Modelle:"
ollama list 2>/dev/null | head -10

# ============================================================
# Schritt 6: Daten-Verzeichnisse erstellen
# ============================================================
step "[6/$STEPS_TOTAL] Daten-Verzeichnisse erstellen..."

DIRS=(
    "$DATA_DIR/chromadb"
    "$DATA_DIR/redis"
    "$DATA_DIR/assistant"
    "$DATA_DIR/uploads"
    "$DATA_DIR/backups"
    "$DATA_DIR/logs"
)

for dir in "${DIRS[@]}"; do
    mkdir -p "$dir"
done

# Berechtigungen sicherstellen
if [ "$DATA_DIR" = "/mnt/data" ]; then
    sudo chown -R "$(id -u):$(id -g)" "$DATA_DIR"
fi

success "Verzeichnisse auf $DATA_DIR:"
for dir in "${DIRS[@]}"; do
    echo "    $(basename "$dir")/"
done

# ============================================================
# Schritt 7: Konfiguration (.env)
# ============================================================
step "[7/$STEPS_TOTAL] Konfiguration..."

cd "$MHA_DIR"

if [ -f .env ]; then
    success ".env existiert bereits"
    if ask_yes_no "Moechtest du die .env neu konfigurieren?" "n"; then
        cp .env ".env.backup.$(date +%Y%m%d_%H%M%S)"
        info "Backup erstellt"
        CONFIGURE_ENV=true
    else
        CONFIGURE_ENV=false
    fi
else
    CONFIGURE_ENV=true
fi

if [ "$CONFIGURE_ENV" = true ]; then
    echo ""
    echo -e "${BOLD}  Verbindung zu Home Assistant konfigurieren:${NC}"
    echo ""

    # HA URL
    DEFAULT_HA_URL="http://192.168.1.100:8123"
    read -p "  Home Assistant URL [$DEFAULT_HA_URL]: " HA_URL
    HA_URL="${HA_URL:-$DEFAULT_HA_URL}"

    # HA Token
    echo ""
    echo "  Du brauchst einen Long-Lived Access Token aus Home Assistant:"
    echo "    1. Oeffne $HA_URL im Browser"
    echo "    2. Klick unten links auf deinen Benutzernamen"
    echo "    3. Scrolle zu 'Langlebige Zugriffstoken'"
    echo "    4. Erstelle einen Token mit Name 'MindHome'"
    echo ""
    read -p "  HA Token: " HA_TOKEN

    if [ -z "$HA_TOKEN" ]; then
        warn "Kein Token eingegeben. Du musst ihn spaeter in .env eintragen!"
        HA_TOKEN="HIER_TOKEN_EINTRAGEN"
    fi

    # MindHome Addon URL
    MINDHOME_PORT="${HA_URL%:*}:8099"
    read -p "  MindHome Add-on URL [$MINDHOME_PORT]: " MINDHOME_URL
    MINDHOME_URL="${MINDHOME_URL:-$MINDHOME_PORT}"

    # Username
    read -p "  Dein Vorname: " USER_NAME
    USER_NAME="${USER_NAME:-User}"

    # Assistant Name
    read -p "  Name des Assistenten [Jarvis]: " ASSISTANT_NAME
    ASSISTANT_NAME="${ASSISTANT_NAME:-Jarvis}"

    # .env schreiben
    cat > .env << ENVFILE
# ============================================================
# MindHome Assistant — Konfiguration
# Erstellt am: $(date '+%Y-%m-%d %H:%M')
# ============================================================

# --- Home Assistant Verbindung ---
HA_URL=$HA_URL
HA_TOKEN=$HA_TOKEN

# --- MindHome Add-on Verbindung ---
MINDHOME_URL=$MINDHOME_URL

# --- Daten-Verzeichnis (SSD 2) ---
# Aendern falls Daten woanders liegen (z.B. /mnt/data oder ./data)
DATA_DIR=$DATA_DIR

# --- Ollama (laeuft nativ auf dem Host) ---
OLLAMA_URL=http://host.docker.internal:11434

# --- Datenbanken (Docker-intern, nicht aendern) ---
REDIS_URL=redis://redis:6379
CHROMA_URL=http://chromadb:8000

# --- Benutzer ---
USER_NAME=$USER_NAME
ASSISTANT_NAME=$ASSISTANT_NAME

# --- Server (nicht aendern) ---
ASSISTANT_HOST=0.0.0.0
ASSISTANT_PORT=8200

# --- API Key (wird auto-generiert wenn leer) ---
# ASSISTANT_API_KEY=
ENVFILE

    success ".env erstellt"
else
    # DATA_DIR aus bestehender .env lesen oder Standard setzen
    if grep -q "^DATA_DIR=" .env 2>/dev/null; then
        EXISTING_DATA_DIR=$(grep "^DATA_DIR=" .env | cut -d= -f2)
        if [ "$EXISTING_DATA_DIR" != "$DATA_DIR" ]; then
            warn "DATA_DIR in .env ($EXISTING_DATA_DIR) weicht ab von $DATA_DIR"
            if ask_yes_no "DATA_DIR in .env auf $DATA_DIR aktualisieren?" "j"; then
                sed -i "s|^DATA_DIR=.*|DATA_DIR=$DATA_DIR|" .env
                success "DATA_DIR aktualisiert"
            fi
        fi
    else
        # DATA_DIR zur bestehenden .env hinzufuegen
        echo "" >> .env
        echo "# --- Daten-Verzeichnis (SSD 2) ---" >> .env
        echo "DATA_DIR=$DATA_DIR" >> .env
        success "DATA_DIR=$DATA_DIR zur .env hinzugefuegt"
    fi
fi

# ============================================================
# Schritt 8: Docker Container starten
# ============================================================
step "[8/$STEPS_TOTAL] MindHome Assistant starten..."

cd "$MHA_DIR"

info "Baue Docker-Image..."
docker compose build

info "Starte Container..."
docker compose up -d

# Health-Check
echo ""
info "Warte auf Health-Checks..."
HEALTHY=false
for i in $(seq 1 30); do
    ASSISTANT_STATUS=$(docker inspect --format='{{.State.Health.Status}}' mindhome-assistant 2>/dev/null || echo "starting")
    CHROMA_STATUS=$(docker inspect --format='{{.State.Health.Status}}' mha-chromadb 2>/dev/null || echo "starting")
    REDIS_STATUS=$(docker inspect --format='{{.State.Health.Status}}' mha-redis 2>/dev/null || echo "starting")

    if [ "$ASSISTANT_STATUS" = "healthy" ] && [ "$CHROMA_STATUS" = "healthy" ] && [ "$REDIS_STATUS" = "healthy" ]; then
        HEALTHY=true
        break
    fi

    printf "\r  Assistant: %-10s  ChromaDB: %-10s  Redis: %-10s  (%d/30)" \
        "$ASSISTANT_STATUS" "$CHROMA_STATUS" "$REDIS_STATUS" "$i"
    sleep 3
done
echo ""

if [ "$HEALTHY" = true ]; then
    success "Alle Container laufen!"
else
    warn "Nicht alle Container sind healthy. Pruefe mit: docker compose logs"
fi

# Container-Status
echo ""
docker compose ps

# API-Test
echo ""
LOCAL_IP=$(hostname -I | awk '{print $1}')
HEALTH_RESPONSE=$(curl -sf http://localhost:8200/api/assistant/health 2>/dev/null || echo "nicht erreichbar")

if echo "$HEALTH_RESPONSE" | grep -q "ok\|healthy\|status" 2>/dev/null; then
    success "API antwortet!"
else
    warn "API antwortet noch nicht. Logs pruefen: docker compose logs -f assistant"
fi

# ============================================================
# Fertig!
# ============================================================
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}    MindHome Assistant ist installiert und gestartet!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  System-SSD:  $(findmnt -n -o SOURCE / 2>/dev/null || echo '?')"
echo "  Daten-SSD:   $DATA_DIR"
echo "  Modelle:     ~/.ollama/models"
echo ""
echo "  ┌────────────────────────────────────────────────┐"
echo "  │  API:        http://${LOCAL_IP}:8200            │"
echo "  │  Dashboard:  http://${LOCAL_IP}:8200/ui/        │"
echo "  │  Health:     http://${LOCAL_IP}:8200/api/assistant/health │"
echo "  │  Ollama:     http://${LOCAL_IP}:11434            │"
echo "  └────────────────────────────────────────────────┘"
echo ""
echo "  Nuetzliche Befehle:"
echo "    docker compose ps                     Status"
echo "    docker compose logs -f assistant      Live-Logs"
echo "    docker compose restart                Neustarten"
echo "    docker compose down && docker compose up -d   Komplett-Neustart"
echo "    ollama list                           Installierte Modelle"
echo ""
echo "  Erster Test:"
echo "    curl -X POST http://localhost:8200/api/assistant/chat \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"text\": \"Hallo\", \"person\": \"${USER_NAME:-User}\"}'"
echo ""
echo -e "${BLUE}  Naechster Schritt: Oeffne das Dashboard im Browser und${NC}"
echo -e "${BLUE}  konfiguriere Raeume, Heizung und Persoenlichkeit.${NC}"
echo ""
