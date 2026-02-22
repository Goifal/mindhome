#!/bin/bash
# ============================================================
# MindHome Assistant — Update Script
# Aktualisiert Code, Container und optional Ollama-Modelle
#
# Nutzung:
#   ./update.sh                             Normales Update (git pull + rebuild)
#   ./update.sh --branch claude/fix-xyz     Auf Branch wechseln + Update
#   ./update.sh --quick                     Nur Container neustarten (kein Rebuild)
#   ./update.sh --full                      Alles: Code + Container + Ollama-Modelle
#   ./update.sh --full --branch <name>      Branch-Wechsel + Full Update
#   ./update.sh --models                    Nur Ollama-Modelle aktualisieren
#   ./update.sh --status                    Zeigt aktuellen Systemstatus
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

MHA_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$MHA_DIR/.." && pwd)"
MODE=""
TARGET_BRANCH=""

# Parameter parsen
while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch|-b)
            TARGET_BRANCH="${2:-}"
            if [ -z "$TARGET_BRANCH" ]; then
                error "Option --branch erfordert einen Branch-Namen."
                echo "  Beispiel: ./update.sh --branch claude/fix-xyz-Ab12C"
                exit 1
            fi
            shift 2
            ;;
        *)
            MODE="$1"
            shift
            ;;
    esac
done

# ============================================================
# Status anzeigen
# ============================================================
show_status() {
    step "MindHome Assistant — Status"

    cd "$MHA_DIR"

    # Git-Status
    info "Git:"
    BRANCH=$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
    COMMIT=$(git -C "$REPO_DIR" log -1 --format='%h %s' 2>/dev/null || echo "?")
    echo "    Branch: $BRANCH"
    echo "    Commit: $COMMIT"

    # Container-Status
    echo ""
    info "Container:"
    docker compose ps 2>/dev/null || warn "Docker Compose nicht verfuegbar"

    # Health-Check
    echo ""
    info "Health:"
    for CONTAINER in mindhome-assistant mha-chromadb mha-redis; do
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo "nicht gefunden")
        case "$STATUS" in
            healthy)   echo -e "    $CONTAINER: ${GREEN}$STATUS${NC}" ;;
            unhealthy) echo -e "    $CONTAINER: ${RED}$STATUS${NC}" ;;
            *)         echo -e "    $CONTAINER: ${YELLOW}$STATUS${NC}" ;;
        esac
    done

    # Ollama
    echo ""
    info "Ollama:"
    if command -v ollama &> /dev/null; then
        OLLAMA_VERSION=$(ollama --version 2>/dev/null | awk '{print $NF}' || echo "?")
        echo "    Version: $OLLAMA_VERSION"
        echo "    Modelle:"
        ollama list 2>/dev/null | while IFS= read -r line; do echo "      $line"; done || echo "      nicht erreichbar"
    else
        echo "    nicht installiert"
    fi

    # Disk-Nutzung
    echo ""
    info "Speicher:"
    if [ -f "$MHA_DIR/.env" ]; then
        DATA_DIR=$(grep "^DATA_DIR=" "$MHA_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "./data")
    else
        DATA_DIR="./data"
    fi
    echo "    Daten:   $(du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}' || echo '?') ($DATA_DIR)"
    echo "    Modelle: $(du -sh ~/.ollama/models 2>/dev/null | awk '{print $1}' || echo '?') (~/.ollama/models)"
    echo "    Docker:  $(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || echo '?')"
}

# ============================================================
# Pre-Update Checks
# ============================================================
preflight_check() {
    # Docker pruefen
    if ! command -v docker &> /dev/null; then
        error "Docker nicht gefunden. Bitte zuerst install.sh ausfuehren."
        exit 1
    fi
    if ! docker compose version &> /dev/null; then
        error "Docker Compose nicht gefunden."
        exit 1
    fi

    # .env pruefen
    if [ ! -f "$MHA_DIR/.env" ]; then
        error ".env nicht gefunden. Bitte zuerst install.sh ausfuehren."
        exit 1
    fi
}

# ============================================================
# Git Update
# ============================================================
update_code() {
    step "Code aktualisieren..."

    cd "$REPO_DIR"

    # Aktuellen Branch merken (fuer Rollback und Log)
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    PULL_BRANCH="${TARGET_BRANCH:-$CURRENT_BRANCH}"
    SWITCHING=false

    if [ -n "$TARGET_BRANCH" ] && [ "$TARGET_BRANCH" != "$CURRENT_BRANCH" ]; then
        SWITCHING=true
        info "Branch-Wechsel: $CURRENT_BRANCH -> $TARGET_BRANCH"
    fi

    # User-Konfiguration in-memory sichern (settings.yaml + .env)
    SETTINGS_BACKUP=""
    ENV_BACKUP=""
    if [ -f "$MHA_DIR/config/settings.yaml" ]; then
        SETTINGS_BACKUP=$(cat "$MHA_DIR/config/settings.yaml")
        success "settings.yaml gesichert"
    fi
    if [ -f "$MHA_DIR/.env" ]; then
        ENV_BACKUP=$(cat "$MHA_DIR/.env")
        success ".env gesichert"
    fi

    # Lokale Aenderungen pruefen und stashen
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        warn "Lokale Aenderungen erkannt:"
        git status --short
        echo ""
        read -rp "  Trotzdem aktualisieren? (Aenderungen werden per Stash gesichert) (j/N): " ANSWER
        if [[ ! "$ANSWER" =~ ^[Jj]$ ]]; then
            info "Abgebrochen."
            exit 0
        fi
        git stash push -m "update.sh Auto-Stash $(date '+%Y-%m-%d %H:%M')"
        STASHED=true
        success "Aenderungen gesichert (git stash)"
    else
        STASHED=false
    fi

    OLD_COMMIT=$(git rev-parse --short HEAD)

    # Branch-Wechsel (falls gewuenscht)
    if [ "$SWITCHING" = true ]; then
        info "Fetch origin/$TARGET_BRANCH..."
        if ! git fetch origin "$TARGET_BRANCH"; then
            error "git fetch fehlgeschlagen fuer $TARGET_BRANCH"
            # Stash wiederherstellen
            if [ "$STASHED" = true ]; then
                git stash pop 2>/dev/null || true
            fi
            # Config wiederherstellen
            _restore_configs
            exit 1
        fi

        info "Checkout $TARGET_BRANCH..."
        if ! git checkout "$TARGET_BRANCH"; then
            error "git checkout fehlgeschlagen fuer $TARGET_BRANCH"
            # Zurueck zum alten Branch
            git checkout "$CURRENT_BRANCH" 2>/dev/null || true
            if [ "$STASHED" = true ]; then
                git stash pop 2>/dev/null || true
            fi
            _restore_configs
            exit 1
        fi
        success "Auf Branch $TARGET_BRANCH gewechselt"
    fi

    info "Hole Updates von origin/$PULL_BRANCH..."
    if ! git pull origin "$PULL_BRANCH"; then
        error "git pull fehlgeschlagen"
        # Rollback bei Branch-Wechsel
        if [ "$SWITCHING" = true ]; then
            warn "Rollback zu $CURRENT_BRANCH..."
            git checkout "$CURRENT_BRANCH" 2>/dev/null || true
        fi
        if [ "$STASHED" = true ]; then
            git stash pop 2>/dev/null || true
        fi
        _restore_configs
        exit 1
    fi

    NEW_COMMIT=$(git rev-parse --short HEAD)
    if [ "$OLD_COMMIT" = "$NEW_COMMIT" ] && [ "$SWITCHING" = false ]; then
        success "Bereits aktuell ($OLD_COMMIT)"
    else
        success "Aktualisiert: $OLD_COMMIT -> $NEW_COMMIT"
        if [ "$SWITCHING" = true ]; then
            success "Branch: $CURRENT_BRANCH -> $PULL_BRANCH"
        fi
        echo ""
        info "Aenderungen:"
        git log --oneline "${OLD_COMMIT}..${NEW_COMMIT}" 2>/dev/null | while IFS= read -r line; do
            echo "    $line"
        done
    fi

    # Stash zurueckholen (nur wenn KEIN Branch-Wechsel — Stash gehoert zum alten Branch)
    if [ "$STASHED" = true ] && [ "$SWITCHING" = false ]; then
        echo ""
        if git stash pop 2>/dev/null; then
            success "Lokale Aenderungen wiederhergestellt"
        else
            warn "Stash konnte nicht automatisch angewendet werden."
            warn "Manuelle Loesung: git stash pop"
        fi
    elif [ "$STASHED" = true ]; then
        info "Stash beibehalten (Branch-Wechsel). Manuell anwenden: git stash pop"
    fi

    # User-Konfiguration wiederherstellen
    _restore_configs
}

# Hilfsfunktion: User-Config wiederherstellen
_restore_configs() {
    if [ -n "$SETTINGS_BACKUP" ]; then
        echo "$SETTINGS_BACKUP" > "$MHA_DIR/config/settings.yaml"
        success "settings.yaml wiederhergestellt"
    fi
    if [ -n "$ENV_BACKUP" ]; then
        echo "$ENV_BACKUP" > "$MHA_DIR/.env"
        success ".env wiederhergestellt"
    fi
}

# ============================================================
# Container Update (Rebuild + Restart)
# ============================================================
update_containers() {
    step "Container aktualisieren..."

    cd "$MHA_DIR"

    info "Baue Docker-Image neu..."
    docker compose build

    info "Starte Container neu..."
    docker compose up -d

    wait_for_healthy
}

# ============================================================
# Quick Restart (ohne Rebuild)
# ============================================================
quick_restart() {
    step "Container neustarten (ohne Rebuild)..."

    cd "$MHA_DIR"
    docker compose restart

    wait_for_healthy
}

# ============================================================
# Ollama Modelle aktualisieren
# ============================================================
update_models() {
    step "Ollama-Modelle aktualisieren..."

    if ! command -v ollama &> /dev/null; then
        warn "Ollama nicht installiert. Uebersprungen."
        return
    fi

    # Ollama erreichbar?
    if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
        warn "Ollama antwortet nicht. Ist der Service gestartet?"
        warn "  sudo systemctl start ollama"
        return
    fi

    # Alle installierten Modelle aktualisieren
    MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
    if [ -z "$MODELS" ]; then
        warn "Keine Modelle installiert."
        return
    fi

    for MODEL in $MODELS; do
        info "Aktualisiere $MODEL..."
        if ollama pull "$MODEL" 2>&1 | tail -1; then
            success "$MODEL aktualisiert"
        else
            warn "Fehler beim Aktualisieren von $MODEL"
        fi
    done
}

# ============================================================
# Health-Check warten
# ============================================================
wait_for_healthy() {
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
        success "Alle Container sind healthy!"
    else
        warn "Nicht alle Container sind healthy. Logs pruefen:"
        warn "  docker compose logs -f assistant"
    fi

    echo ""
    docker compose ps
}

# ============================================================
# Hauptprogramm
# ============================================================

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}    MindHome Assistant — Update${NC}"
echo -e "${BLUE}============================================================${NC}"

if [ -n "$TARGET_BRANCH" ]; then
    info "Ziel-Branch: $TARGET_BRANCH"
fi

case "$MODE" in
    --status|-s)
        show_status
        ;;

    --quick|-q)
        preflight_check
        quick_restart
        success "Quick-Restart abgeschlossen!"
        ;;

    --models|-m)
        update_models
        success "Modell-Update abgeschlossen!"
        ;;

    --full|-f)
        preflight_check
        update_code
        update_containers
        update_models
        echo ""
        success "Voll-Update abgeschlossen!"
        ;;

    --help|-h)
        echo ""
        echo "  Nutzung: ./update.sh [OPTION] [--branch <name>]"
        echo ""
        echo "  Optionen:"
        echo "    (keine)         Standard-Update: Code + Container rebuild"
        echo "    --quick, -q     Nur Container neustarten (kein Rebuild)"
        echo "    --full, -f      Alles: Code + Container + Ollama-Modelle"
        echo "    --models, -m    Nur Ollama-Modelle aktualisieren"
        echo "    --status, -s    Aktuellen Systemstatus anzeigen"
        echo "    --help, -h      Diese Hilfe"
        echo ""
        echo "  Branch-Wechsel:"
        echo "    --branch, -b <name>  Auf angegebenen Branch wechseln vor Update"
        echo ""
        echo "  Beispiele:"
        echo "    ./update.sh --branch claude/fix-xyz-Ab12C"
        echo "    ./update.sh --full --branch claude/new-feature-Cd34E"
        echo ""
        ;;

    "")
        # Standard: Code + Container
        preflight_check
        update_code
        update_containers
        echo ""
        success "Update abgeschlossen!"
        ;;

    *)
        error "Unbekannte Option: $MODE"
        echo "  Nutze --help fuer verfuegbare Optionen."
        exit 1
        ;;
esac

echo ""
