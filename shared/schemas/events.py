"""Event-Typen fuer WebSocket-Kommunikation."""
from pydantic import BaseModel
from typing import Optional

EVENT_THINKING = "assistant.thinking"
EVENT_SPEAKING = "assistant.speaking"
EVENT_ACTION = "assistant.action"
EVENT_LISTENING = "assistant.listening"
EVENT_PROACTIVE = "assistant.proactive"


class MindHomeEvent(BaseModel):
    event: str
    data: dict = {}
    timestamp: Optional[str] = None
