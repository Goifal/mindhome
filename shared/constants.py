"""Gemeinsame Konstanten fuer Addon und Assistant."""

ASSISTANT_PORT = 8200
ADDON_INGRESS_PORT = 5000
CHROMADB_PORT = 8100
REDIS_PORT = 6379
OLLAMA_PORT = 11434

# Event-Namen
EVENT_THINKING = "assistant.thinking"
EVENT_SPEAKING = "assistant.speaking"
EVENT_ACTION = "assistant.action"
EVENT_LISTENING = "assistant.listening"
EVENT_PROACTIVE = "assistant.proactive"

# Mood levels
MOOD_RELAXED = "relaxed"
MOOD_NORMAL = "normal"
MOOD_STRESSED = "stressed"
MOOD_FRUSTRATED = "frustrated"
MOOD_TIRED = "tired"

# Autonomy levels
AUTONOMY_ASSISTANT = 1
AUTONOMY_BUTLER = 2
AUTONOMY_ROOMMATE = 3
AUTONOMY_TRUSTED = 4
AUTONOMY_AUTOPILOT = 5
