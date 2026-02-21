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
LLM_TIMEOUT_SMART: Final[int] = 60
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
