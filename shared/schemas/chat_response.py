"""Chat Response Schema - wird von Assistant zurueckgegeben."""
from pydantic import BaseModel
from typing import Optional


class TTSInfo(BaseModel):
    """TTS-Metadaten fuer Sprachausgabe."""
    ssml: str = ""
    volume: float = 1.0
    speed: float = 1.0
    target_speaker: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    actions: list = []
    model_used: str = ""
    context_room: str = ""
    tts: Optional[TTSInfo] = None
