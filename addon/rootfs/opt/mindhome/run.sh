#!/usr/bin/with-contenv bashio

# ==============================================================================
# MindHome - Smart Home AI
# Startup script
# ==============================================================================

bashio::log.info "Starting MindHome..."

# Read configuration from add-on options (with fallbacks)
if bashio::config.has_value 'language'; then
    export MINDHOME_LANGUAGE=$(bashio::config 'language')
else
    export MINDHOME_LANGUAGE="de"
fi

if bashio::config.has_value 'log_level'; then
    export MINDHOME_LOG_LEVEL=$(bashio::config 'log_level')
else
    export MINDHOME_LOG_LEVEL="info"
fi

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

# Ensure database initialized
if [ ! -f "${MINDHOME_DB_PATH}" ]; then
    bashio::log.info "First run detected - initializing database..."
    python3 /opt/mindhome/init_db.py
    if [ $? -eq 0 ]; then
        bashio::log.info "Database initialized successfully."
    else
        bashio::log.error "Database initialization failed!"
        exit 1
    fi
fi

# Start the MindHome application
bashio::log.info "MindHome is ready!"
exec python3 /opt/mindhome/app.py
