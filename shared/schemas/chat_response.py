"""Chat Response Schema - wird von Assistant zurueckgegeben."""
from pydantic import BaseModel


class ChatResponse(BaseModel):
    response: str
    actions: list = []
    model_used: str = ""
    context_room: str = ""
