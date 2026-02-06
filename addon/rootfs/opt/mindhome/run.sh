#!/usr/bin/with-contenv bashio

# ==============================================================================
# MindHome - Smart Home AI
# Startup script
# ==============================================================================

bashio::log.info "Starting MindHome..."

# Read configuration from add-on options
export MINDHOME_LANGUAGE=$(bashio::config 'language')
export MINDHOME_LOG_LEVEL=$(bashio::config 'log_level')

# Get Home Assistant connection details
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export HA_WS_URL="ws://supervisor/core/websocket"

# Get Ingress entry
export INGRESS_PATH=$(bashio::addon.ingress_entry)

# Database path (persistent storage)
export MINDHOME_DB_PATH="/data/mindhome/db/mindhome.db"
export MINDHOME_MODELS_PATH="/data/mindhome/models"
export MINDHOME_LOGS_PATH="/data/mindhome/logs"
export MINDHOME_BACKUPS_PATH="/data/mindhome/backups"

bashio::log.info "Language: ${MINDHOME_LANGUAGE}"
bashio::log.info "Log Level: ${MINDHOME_LOG_LEVEL}"
bashio::log.info "Ingress Path: ${INGRESS_PATH}"
bashio::log.info "Database: ${MINDHOME_DB_PATH}"

# Initialize database if first run
if [ ! -f "${MINDHOME_DB_PATH}" ]; then
    bashio::log.info "First run detected - initializing database..."
    python3 /opt/mindhome/init_db.py
fi

# Start the MindHome application
bashio::log.info "MindHome is ready!"
exec python3 /opt/mindhome/app.py
