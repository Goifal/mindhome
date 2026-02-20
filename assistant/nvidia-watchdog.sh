#!/bin/bash
# ============================================================
# MindHome NVIDIA GPU Watchdog
# Ueberwacht GPU-Treiber + Ollama und startet bei Crash neu
# ============================================================
#
# Installation:
#   sudo cp nvidia-watchdog.sh /usr/local/bin/
#   sudo chmod +x /usr/local/bin/nvidia-watchdog.sh
#   sudo cp systemd/nvidia-watchdog.service /etc/systemd/system/
#   sudo cp systemd/nvidia-watchdog.timer /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now nvidia-watchdog.timer
#
# Manuell ausfuehren:
#   sudo nvidia-watchdog.sh
#
# Logs anschauen:
#   journalctl -u nvidia-watchdog -f
#

LOG_TAG="nvidia-watchdog"
OLLAMA_URL="http://localhost:11434"
MAX_RETRIES=3
RETRY_DELAY=5

log_info()  { logger -t "$LOG_TAG" -p user.info  "$1"; echo "[INFO]  $1"; }
log_warn()  { logger -t "$LOG_TAG" -p user.warning "$1"; echo "[WARN]  $1"; }
log_error() { logger -t "$LOG_TAG" -p user.err "$1"; echo "[ERROR] $1"; }

# --- 1. NVIDIA-Treiber pruefen ---
check_nvidia() {
    if ! command -v nvidia-smi &>/dev/null; then
        log_warn "nvidia-smi nicht gefunden — kein NVIDIA-Treiber installiert?"
        return 1
    fi

    if nvidia-smi &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# --- 2. NVIDIA-Treiber Recovery ---
recover_nvidia() {
    log_warn "NVIDIA-Treiber antwortet nicht — versuche Recovery..."

    # Ollama stoppen (haelt GPU-Handles offen)
    if systemctl is-active --quiet ollama; then
        log_info "Stoppe Ollama..."
        systemctl stop ollama
        sleep 2
    fi

    # Alle GPU-Prozesse beenden
    local gpu_pids
    gpu_pids=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ')
    if [ -n "$gpu_pids" ]; then
        log_info "Beende GPU-Prozesse: $gpu_pids"
        echo "$gpu_pids" | xargs -r kill -9 2>/dev/null
        sleep 2
    fi

    # NVIDIA-Module neu laden
    log_info "Lade NVIDIA-Kernel-Module neu..."
    rmmod nvidia_uvm 2>/dev/null
    rmmod nvidia_drm 2>/dev/null
    rmmod nvidia_modeset 2>/dev/null
    rmmod nvidia 2>/dev/null
    sleep 2

    modprobe nvidia
    modprobe nvidia_uvm
    modprobe nvidia_drm
    modprobe nvidia_modeset
    sleep 2

    # Pruefen ob Recovery erfolgreich
    if nvidia-smi &>/dev/null; then
        log_info "NVIDIA-Treiber Recovery erfolgreich!"
        return 0
    else
        log_error "NVIDIA-Treiber Recovery FEHLGESCHLAGEN"
        return 1
    fi
}

# --- 3. Ollama pruefen ---
check_ollama() {
    if ! systemctl is-active --quiet ollama; then
        return 1
    fi

    # HTTP Health-Check
    if curl -sf --max-time 5 "$OLLAMA_URL/api/tags" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# --- 4. Ollama neustarten ---
restart_ollama() {
    log_warn "Ollama antwortet nicht — starte neu..."
    systemctl restart ollama
    sleep 5

    # Warten bis Ollama bereit ist
    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf --max-time 5 "$OLLAMA_URL/api/tags" &>/dev/null; then
            log_info "Ollama erfolgreich neugestartet"
            return 0
        fi
        log_info "Warte auf Ollama... (Versuch $i/$MAX_RETRIES)"
        sleep $RETRY_DELAY
    done

    log_error "Ollama antwortet nach Neustart nicht"
    return 1
}

# --- Hauptprogramm ---
main() {
    local nvidia_ok=true
    local ollama_ok=true

    # GPU pruefen
    if ! check_nvidia; then
        nvidia_ok=false
        if recover_nvidia; then
            nvidia_ok=true
        fi
    fi

    # Ollama pruefen (und bei Bedarf starten)
    if ! check_ollama; then
        ollama_ok=false
        if restart_ollama; then
            ollama_ok=true
        fi
    fi

    # Status ausgeben
    if $nvidia_ok && $ollama_ok; then
        log_info "GPU + Ollama OK"
        exit 0
    elif $nvidia_ok && ! $ollama_ok; then
        log_error "GPU OK, Ollama FEHLER"
        exit 1
    elif ! $nvidia_ok; then
        log_error "GPU FEHLER — manueller Eingriff noetig (evtl. Reboot)"
        exit 2
    fi
}

main "$@"
