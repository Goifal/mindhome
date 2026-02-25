"""
Globale Test-Fixtures fuer den MindHome Assistant.

Stellt wiederverwendbare Mock-Objekte bereit die von allen Tests
genutzt werden koennen:
  - redis_mock: AsyncMock Redis Client mit allen gaengigen Methoden
  - chroma_mock: MagicMock ChromaDB Collection
  - ha_mock: AsyncMock Home Assistant Client
  - ollama_mock: AsyncMock Ollama Client
  - brain_mock: Vollstaendiger Brain-Mock fuer Integration-Tests
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================
# Redis Mock
# ============================================================

@pytest.fixture
def redis_mock():
    """AsyncMock Redis Client mit allen gaengigen Methoden."""
    mock = AsyncMock()

    # Key-Value Store
    _store: dict[str, str] = {}
    _lists: dict[str, list] = {}
    _hashes: dict[str, dict] = {}
    _sets: dict[str, set] = {}

    # Basis-Operationen
    mock.ping = AsyncMock(return_value=True)
    mock.close = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.setex = AsyncMock()
    mock.delete = AsyncMock()
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock()
    mock.exists = AsyncMock(return_value=0)

    # Listen
    mock.lpush = AsyncMock()
    mock.rpush = AsyncMock()
    mock.ltrim = AsyncMock()
    mock.lrange = AsyncMock(return_value=[])
    mock.llen = AsyncMock(return_value=0)
    mock.rpop = AsyncMock(return_value=None)

    # Hashes
    mock.hset = AsyncMock()
    mock.hget = AsyncMock(return_value=None)
    mock.hgetall = AsyncMock(return_value={})
    mock.hdel = AsyncMock()

    # Sets
    mock.sadd = AsyncMock()
    mock.srem = AsyncMock()
    mock.smembers = AsyncMock(return_value=set())
    mock.scard = AsyncMock(return_value=0)

    # Pipeline — redis.pipeline() ist synchron, gibt Pipeline-Objekt zurueck
    # Befehle auf der Pipeline sind ebenfalls synchron, nur execute() ist async
    pipe_mock = MagicMock()
    pipe_mock.lpush = MagicMock()
    pipe_mock.rpush = MagicMock()
    pipe_mock.ltrim = MagicMock()
    pipe_mock.expire = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe_mock)
    mock._pipeline = pipe_mock  # Fuer direkte Assertions in Tests

    return mock


# ============================================================
# ChromaDB Mock
# ============================================================

@pytest.fixture
def chroma_mock():
    """MagicMock ChromaDB Collection."""
    mock = MagicMock()
    mock.add = MagicMock()
    mock.query = MagicMock(return_value={
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    })
    mock.update = MagicMock()
    mock.delete = MagicMock()
    mock.count = MagicMock(return_value=0)
    return mock


# ============================================================
# Home Assistant Client Mock
# ============================================================

@pytest.fixture
def ha_mock():
    """AsyncMock Home Assistant Client."""
    mock = AsyncMock()
    mock.get_states = AsyncMock(return_value=[])
    mock.get_state = AsyncMock(return_value=None)
    mock.call_service = AsyncMock(return_value={"success": True})
    mock.fire_event = AsyncMock()
    mock.is_available = AsyncMock(return_value=True)
    mock.close = AsyncMock()
    return mock


# ============================================================
# Ollama Client Mock
# ============================================================

@pytest.fixture
def ollama_mock():
    """AsyncMock Ollama Client."""
    mock = AsyncMock()
    mock.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Test-Antwort"},
    })
    mock.generate = AsyncMock(return_value="Test-Antwort")
    mock.stream_chat = AsyncMock()
    mock.list_models = AsyncMock(return_value=["qwen3:4b", "qwen3:14b"])
    mock.is_available = AsyncMock(return_value=True)
    return mock


# ============================================================
# Brain Mock (fuer Integration-Tests)
# ============================================================

@pytest.fixture
def brain_mock(redis_mock, ha_mock, ollama_mock, chroma_mock):
    """Vollstaendiger Brain-Mock mit allen Subkomponenten."""
    brain = MagicMock()

    # Clients
    brain.ha = ha_mock
    brain.ollama = ollama_mock

    # Memory
    brain.memory = MagicMock()
    brain.memory.redis = redis_mock
    brain.memory.chroma_collection = chroma_mock
    brain.memory.add_conversation = AsyncMock()
    brain.memory.get_recent_conversations = AsyncMock(return_value=[])
    brain.memory.search_memories = AsyncMock(return_value=[])
    brain.memory.semantic = MagicMock()
    brain.memory.semantic.search_facts = AsyncMock(return_value=[])
    brain.memory.semantic.get_all_facts = AsyncMock(return_value=[])
    brain.memory.semantic.get_stats = AsyncMock(return_value={})
    brain.memory.semantic.store_fact = AsyncMock(return_value=True)
    brain.memory.get_last_notification_time = AsyncMock(return_value=None)
    brain.memory.set_last_notification_time = AsyncMock()

    # Mood
    brain.mood = MagicMock()
    brain.mood.get_current_mood = MagicMock(return_value={
        "mood": "neutral", "confidence": 0.5,
    })

    # Activity
    brain.activity = MagicMock()
    brain.activity.detect_activity = AsyncMock(return_value={
        "activity": "idle", "confidence": 0.8,
    })
    brain.activity.should_deliver = AsyncMock(return_value={
        "deliver": True, "delay": 0,
    })

    # Device Health
    brain.device_health = MagicMock()
    brain.device_health.get_status = AsyncMock(return_value={})
    brain.device_health.check_all = AsyncMock(return_value=[])

    # Learning Observer
    brain.learning_observer = MagicMock()
    brain.learning_observer.get_learned_patterns = AsyncMock(return_value=[])
    brain.learning_observer.mark_jarvis_action = AsyncMock()

    # Camera
    brain.camera_manager = MagicMock()
    brain.camera_manager.describe_doorbell = AsyncMock(return_value="")

    # Feedback
    brain.feedback = MagicMock()
    brain.feedback.record_feedback = AsyncMock(return_value={"success": True})
    brain.feedback.get_stats = AsyncMock(return_value={})
    brain.feedback.get_all_scores = AsyncMock(return_value={})

    # Autonomy
    brain.autonomy = MagicMock()
    brain.autonomy.level = 2
    brain.autonomy.get_level_info = MagicMock(return_value={"level": 2, "name": "Aktiv"})

    # Health Check
    brain.health_check = AsyncMock(return_value={
        "status": "ok",
        "components": {"redis": "connected", "chromadb": "connected", "ollama": "connected"},
        "autonomy": {"level": 2, "name": "Aktiv"},
    })

    # Proactive
    brain.proactive = MagicMock()
    brain.proactive.generate_status_report = AsyncMock(return_value="Alles in Ordnung, Sir.")

    return brain
