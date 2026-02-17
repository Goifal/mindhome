"""Chat Request Schema - wird von Addon gesendet und von Assistant empfangen."""
from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    text: str
    person: Optional[str] = None
    room: Optional[str] = None
    speaker_confidence: Optional[float] = None
