"""
Jarvis - Hauptanwendung (FastAPI Server)
Startet den Jarvis REST API Server.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from .brain import JarvisBrain
from .config import settings

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("jarvis")

# Brain-Instanz
brain = JarvisBrain()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup und Shutdown."""
    logger.info("=" * 50)
    logger.info("  JARVIS v0.1.0 startet...")
    logger.info("=" * 50)
    await brain.initialize()

    health = await brain.health_check()
    for component, status in health["components"].items():
        icon = "OK" if status == "connected" else "!!"
        logger.info("  [%s] %s: %s", icon, component, status)

    logger.info("  Autonomie: Level %d (%s)",
                health["autonomy"]["level"],
                health["autonomy"]["name"])
    logger.info("=" * 50)
    logger.info("  Jarvis bereit auf %s:%d", settings.jarvis_host, settings.jarvis_port)
    logger.info("=" * 50)

    yield

    await brain.shutdown()
    logger.info("Jarvis heruntergefahren.")


app = FastAPI(
    title="Jarvis",
    description="Lokaler KI-Sprachassistent fuer Home Assistant",
    version="0.1.0",
    lifespan=lifespan,
)


# ----- Request/Response Modelle -----

class ChatRequest(BaseModel):
    text: str
    person: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    actions: list = []
    model_used: str = ""
    context_room: str = ""


class SettingsUpdate(BaseModel):
    autonomy_level: Optional[int] = None


# ----- API Endpoints -----

@app.get("/api/jarvis/health")
async def health():
    """Jarvis Health Check - Status aller Komponenten."""
    return await brain.health_check()


@app.post("/api/jarvis/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Hauptendpoint - Text an Jarvis senden.

    Beispiel:
        POST /api/jarvis/chat
        {"text": "Mach das Licht im Wohnzimmer aus", "person": "Max"}
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Kein Text angegeben")

    result = await brain.process(request.text, request.person)
    return ChatResponse(**result)


@app.get("/api/jarvis/context")
async def get_context():
    """Debug: Aktueller Kontext-Snapshot."""
    return await brain.context_builder.build()


@app.get("/api/jarvis/memory/search")
async def search_memory(q: str):
    """Sucht im Langzeitgedaechtnis."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Kein Suchbegriff")
    results = await brain.memory.search_memories(q)
    return {"query": q, "results": results}


@app.get("/api/jarvis/settings")
async def get_settings():
    """Aktuelle Jarvis-Einstellungen."""
    return {
        "autonomy": brain.autonomy.get_level_info(),
        "models": brain.model_router.get_model_info(),
        "user_name": settings.user_name,
        "language": settings.language,
    }


@app.put("/api/jarvis/settings")
async def update_settings(update: SettingsUpdate):
    """Einstellungen aktualisieren."""
    result = {}
    if update.autonomy_level is not None:
        success = brain.autonomy.set_level(update.autonomy_level)
        if not success:
            raise HTTPException(status_code=400, detail="Level muss 1-5 sein")
        result["autonomy"] = brain.autonomy.get_level_info()
    return result


@app.get("/")
async def root():
    """Startseite."""
    return {
        "name": "Jarvis",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


def start():
    """Einstiegspunkt fuer den Server."""
    import uvicorn

    uvicorn.run(
        "jarvis.main:app",
        host=settings.jarvis_host,
        port=settings.jarvis_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    start()
