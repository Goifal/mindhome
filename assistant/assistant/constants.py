"""
Zentrale Konstanten fuer den MindHome Assistant.

Sammelt alle Magic Numbers, Timeouts, Limits und Schwellwerte
an einem Ort statt sie ueber 50+ Module zu verstreuen.
"""

from typing import Final

# ============================================================
# Timeouts (Sekunden)
# ============================================================

# Ollama LLM Timeouts
LLM_TIMEOUT_FAST: Final[int] = 30
LLM_TIMEOUT_SMART: Final[int] = 45
LLM_TIMEOUT_DEEP: Final[int] = 120
LLM_TIMEOUT_STREAM: Final[int] = 120
LLM_TIMEOUT_AVAILABILITY: Final[int] = 5

# Home Assistant Client
HA_SESSION_TIMEOUT: Final[int] = 10
HA_RETRY_MAX: Final[int] = 3
HA_RETRY_BACKOFF_BASE: Final[float] = 1.5
HA_STATES_CACHE_TTL: Final[float] = 2.0

# Brain Processing
BRAIN_PROCESS_TIMEOUT: Final[int] = 60
BRAIN_FALLBACK_TIMEOUT_RATIO: Final[float] = 0.66

# ============================================================
# Redis TTLs (Sekunden)
# ============================================================

# Working Memory
REDIS_WORKING_MEMORY_MAX_ITEMS: Final[int] = 50
REDIS_CONVERSATION_ARCHIVE_TTL: Final[int] = 30 * 86400  # 30 Tage
REDIS_PENDING_TOPICS_TTL: Final[int] = 86400  # 24h
REDIS_NOTIFICATION_COOLDOWN_TTL: Final[int] = 3600  # 1h
REDIS_CONTEXT_DEFAULT_TTL: Final[int] = 3600  # 1h

# Health Monitor
REDIS_HEALTH_SNAPSHOT_TTL: Final[int] = 168 * 3600  # 7 Tage
REDIS_HYDRATION_TTL: Final[int] = 86400  # 24h

# Cross-Room Context
REDIS_CROSS_ROOM_TTL: Final[int] = 1800  # 30 Min

# Security Confirmation
REDIS_SECURITY_CONFIRM_TTL: Final[int] = 300  # 5 Min
REDIS_SECURITY_CONFIRM_KEY: Final[str] = "mha:pending_security_confirmation"

# Pending Summary
REDIS_PENDING_SUMMARY_TTL: Final[int] = 86400  # 24h

# Config Snapshots
REDIS_CONFIG_SNAPSHOT_TTL: Final[int] = 90 * 86400  # 90 Tage

# Feedback Scores
REDIS_FEEDBACK_SCORE_TTL: Final[int] = 90 * 86400  # 90 Tage

# Device Health Baselines
REDIS_DEVICE_BASELINE_TTL: Final[int] = 30 * 86400  # 30 Tage

# ============================================================
# Limits & Sizes
# ============================================================

# Error Buffer
ERROR_BUFFER_MAX_SIZE: Final[int] = 2000

# Activity Buffer (Jarvis-Aktivitaetsprotokoll)
ACTIVITY_BUFFER_MAX_SIZE: Final[int] = 3000

# Rate Limiting
RATE_LIMIT_WINDOW: Final[int] = 60  # Sekunden
RATE_LIMIT_MAX_REQUESTS: Final[int] = 60

# API Key
API_KEY_LENGTH: Final[int] = 32

# Context Builder
MAX_CONTEXT_TOKENS_DEFAULT: Final[int] = 6000
MIN_SECTION_TOKEN_BUDGET: Final[int] = 300
SECTION_BUDGET_RATIO: Final[float] = 0.6

# Memory Chunks
EPISODE_CHUNK_SIZE: Final[int] = 200
EPISODE_CHUNK_OVERLAP: Final[int] = 50

# Notification Validation
MAX_NOTIFICATION_LENGTH: Final[int] = 300
MIN_GERMAN_CHECK_LENGTH: Final[int] = 50

# Batching
BATCH_MAX_ITEMS_DEFAULT: Final[int] = 10
BATCH_INTERVAL_MINUTES_DEFAULT: Final[int] = 30

# ============================================================
# Scheduling Intervals (Sekunden)
# ============================================================

# Main Loops
TOKEN_CLEANUP_INTERVAL: Final[int] = 900  # 15 Min
HEALTH_CHECK_DEFAULT_INTERVAL_MIN: Final[int] = 10
HEALTH_MONITOR_STARTUP_DELAY: Final[int] = 180  # 3 Min

# Proactive Manager
PROACTIVE_COOLDOWN_DEFAULT: Final[int] = 300  # 5 Min
PROACTIVE_WS_RECONNECT_DELAY: Final[int] = 10
PROACTIVE_DIAGNOSTICS_STARTUP_DELAY: Final[int] = 120  # 2 Min
PROACTIVE_BATCH_STARTUP_DELAY: Final[int] = 60  # 1 Min
PROACTIVE_SEASONAL_STARTUP_DELAY: Final[int] = 180  # 3 Min
PROACTIVE_THREAT_STARTUP_DELAY: Final[int] = 180  # 3 Min
PROACTIVE_THREAT_CHECK_INTERVAL: Final[int] = 300  # 5 Min
PROACTIVE_AMBIENT_CHECK_INTERVAL: Final[int] = 600  # 10 Min

# Fact Decay
FACT_DECAY_HOUR: Final[int] = 4  # 04:00 Uhr
FACT_DECAY_ERROR_WAIT: Final[int] = 3600  # 1h bei Fehler

# Morning Briefing
MORNING_BRIEFING_WINDOW_START: Final[int] = 6
MORNING_BRIEFING_WINDOW_END: Final[int] = 10

# ============================================================
# Health Monitor Schwellwerte
# ============================================================

CO2_WARN_PPM: Final[int] = 1000
CO2_CRITICAL_PPM: Final[int] = 1500
HUMIDITY_LOW_PERCENT: Final[int] = 30
HUMIDITY_HIGH_PERCENT: Final[int] = 70
TEMP_LOW_CELSIUS: Final[int] = 16
TEMP_HIGH_CELSIUS: Final[int] = 27
HYDRATION_INTERVAL_HOURS: Final[int] = 2
HYDRATION_START_HOUR: Final[int] = 8
HYDRATION_END_HOUR: Final[int] = 22
ALERT_COOLDOWN_MINUTES: Final[int] = 60

# CO2 Scoring
CO2_SCORE_EXCELLENT: Final[int] = 600
CO2_SCORE_GOOD: Final[int] = 800
CO2_SCORE_MODERATE: Final[int] = 1000
CO2_SCORE_POOR: Final[int] = 1200
CO2_SCORE_BAD: Final[int] = 1500

# ============================================================
# Geo-Fence
# ============================================================

GEO_APPROACHING_KM: Final[float] = 2.0
GEO_ARRIVING_KM: Final[float] = 0.5
GEO_APPROACHING_COOLDOWN_MIN: Final[int] = 15
GEO_ARRIVING_COOLDOWN_MIN: Final[int] = 10

# ============================================================
# LLM Defaults
# ============================================================

LLM_DEFAULT_TEMPERATURE: Final[float] = 0.7
LLM_DEFAULT_MAX_TOKENS: Final[int] = 256

# ============================================================
# Websocket
# ============================================================

WS_DEFAULT_VOLUME: Final[float] = 0.8
WS_DEFAULT_SOUND_VOLUME: Final[float] = 0.5

# ============================================================
# Trust Levels
# ============================================================

TRUST_OWNER: Final[int] = 2
TRUST_MEMBER: Final[int] = 1
TRUST_GUEST: Final[int] = 0

# ============================================================
# Websocket Keepalive & Rate Limits
# ============================================================

WS_KEEPALIVE_INTERVAL: Final[int] = 25  # Sekunden
WS_RATE_LIMIT_MESSAGES: Final[int] = 30
WS_RATE_LIMIT_WINDOW: Final[float] = 10.0
WS_RECEIVE_TIMEOUT: Final[int] = 300  # 5 Min

# ============================================================
# Audio / TTS / STT Timeouts
# ============================================================

AUDIO_CHUNK_TIMEOUT: Final[float] = 15.0
AUDIO_PAYLOAD_TIMEOUT: Final[float] = 10.0
TRANSCRIPT_TIMEOUT: Final[float] = 30.0
PIPER_CONNECT_TIMEOUT: Final[float] = 5.0
WHISPER_CONNECT_TIMEOUT: Final[float] = 5.0
TTS_PLAYBACK_TIMEOUT: Final[int] = 15

# ============================================================
# Background Task Intervals (Sekunden)
# ============================================================

ENTITY_CATALOG_REFRESH_INTERVAL: Final[int] = 1800  # 30 Min (war 270/4.5 Min — unnoetig haeufig fuer statische Entity-Listen)
ERROR_BACKOFF_SHORT: Final[int] = 60
ERROR_BACKOFF_LONG: Final[int] = 3600  # 1h

# ============================================================
# Redis SCAN Batch Sizes
# ============================================================

REDIS_SCAN_BATCH_SMALL: Final[int] = 20
REDIS_SCAN_BATCH_MEDIUM: Final[int] = 50
REDIS_SCAN_BATCH_LARGE: Final[int] = 100

# ============================================================
# asyncio.gather Timeouts (Sekunden)
# ============================================================

GATHER_MEGA_TIMEOUT: Final[int] = 45   # brain.py mega-gather
GATHER_CONTEXT_TIMEOUT: Final[int] = 15  # context_builder.py
GATHER_ACTION_TIMEOUT: Final[int] = 120  # action_planner.py
GATHER_SHUTDOWN_TIMEOUT: Final[int] = 30  # task_registry.py shutdown

# ============================================================
# Cooking Assistant
# ============================================================

MAX_TIMERS_PER_SESSION: Final[int] = 10
COOKING_SESSION_TTL: Final[int] = 6 * 3600  # 6h

# ============================================================
# Self Automation
# ============================================================

SELF_AUTOMATION_PENDING_TTL: Final[int] = 300  # 5 Min Timeout

# ============================================================
# Smart Shopping
# ============================================================

SHOPPING_MIN_PURCHASES: Final[int] = 2
SHOPPING_REMINDER_DAYS_BEFORE: Final[int] = 1
SHOPPING_REMINDER_COOLDOWN_H: Final[int] = 24
SHOPPING_CONSUMPTION_MAX_ENTRIES: Final[int] = 50
SHOPPING_CONSUMPTION_TTL: Final[int] = 365 * 86400  # 1 Jahr
SHOPPING_CONFIDENCE_DATAPOINTS: Final[int] = 10
SHOPPING_LOW_STOCK_THRESHOLD: Final[float] = 0.3

# ============================================================
# Climate Model
# ============================================================

CLIMATE_TEMP_MIN: Final[float] = 5.0
CLIMATE_TEMP_MAX: Final[float] = 35.0
CLIMATE_COMFORT_DEFAULT: Final[float] = 21.0
CLIMATE_VACATION_TARGET: Final[float] = 16.0
CLIMATE_COVER_HEAT_FACTOR: Final[float] = 0.7
CLIMATE_DEFAULT_ENERGY_PRICE: Final[float] = 0.30  # EUR/kWh

# ============================================================
# Service Whitelists / Blacklists (Single Source of Truth)
# Verwendet von: function_validator.py, self_automation.py
# ============================================================

ALLOWED_SERVICES: Final[frozenset[str]] = frozenset([
    "light.turn_on", "light.turn_off", "light.toggle",
    "switch.turn_on", "switch.turn_off", "switch.toggle",
    "climate.set_temperature", "climate.set_hvac_mode",
    "climate.set_preset_mode",
    "cover.open_cover", "cover.close_cover", "cover.set_cover_position",
    "cover.stop_cover",
    "media_player.media_play", "media_player.media_pause",
    "media_player.media_stop", "media_player.volume_set",
    "media_player.media_next_track", "media_player.media_previous_track",
    "scene.turn_on",
    "notify.notify",
    "input_boolean.turn_on", "input_boolean.turn_off",
    "input_boolean.toggle",
    "input_number.set_value",
    "input_select.select_option",
    "fan.turn_on", "fan.turn_off", "fan.set_percentage",
    "vacuum.start", "vacuum.return_to_base", "vacuum.stop",
    "humidifier.turn_on", "humidifier.turn_off",
    "humidifier.set_humidity",
    "water_heater.set_temperature",
    "button.press",
    "number.set_value",
    "select.select_option",
    "timer.start", "timer.cancel",
    "input_text.set_value",
    "input_datetime.set_datetime",
    "tts.speak",
    "media_player.select_source",
    "media_player.play_media",
    "media_player.shuffle_set",
    "media_player.repeat_set",
    "climate.turn_on", "climate.turn_off",
    "persistent_notification.create",
    "persistent_notification.dismiss",
    "siren.turn_on", "siren.turn_off",
])

BLOCKED_SERVICES: Final[frozenset[str]] = frozenset([
    "shell_command", "script", "python_script",
    "rest_command", "homeassistant.restart",
    "homeassistant.stop", "homeassistant.reload_all",
    "automation.turn_off", "automation.turn_on",
    "automation.trigger", "automation.reload",
    "lock.unlock", "lock.lock", "lock.open",
    "homeassistant.set_location",
    "homeassistant.check_config",
    "hassio.addon_start", "hassio.addon_stop",
    "hassio.addon_restart", "hassio.addon_update",
    "recorder.purge", "recorder.disable",
    "system_log.clear",
])
