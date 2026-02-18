"""
MindHome Assistant - Hauptanwendung (FastAPI Server)
Startet den MindHome Assistant REST API Server.
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from .brain import AssistantBrain
from .config import settings
from .file_handler import (
    allowed_file, build_file_context, ensure_upload_dir,
    get_file_path, save_upload, MAX_FILE_SIZE,
)
from .websocket import ws_manager, emit_speaking

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mindhome-assistant")

# Brain-Instanz
brain = AssistantBrain()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup und Shutdown."""
    logger.info("=" * 50)
    logger.info(" MindHome Assistant v1.1.0 startet...")
    logger.info("=" * 50)
    await brain.initialize()

    health = await brain.health_check()
    for component, status in health["components"].items():
        icon = "OK" if status == "connected" else "!!"
        logger.info(" [%s] %s: %s", icon, component, status)

    logger.info(" Autonomie: Level %d (%s)",
        health["autonomy"]["level"],
        health["autonomy"]["name"])
    logger.info("=" * 50)
    logger.info(" MindHome Assistant bereit auf %s:%d",
        settings.assistant_host, settings.assistant_port)
    logger.info("=" * 50)

    yield

    await brain.shutdown()
    logger.info("MindHome Assistant heruntergefahren.")


app = FastAPI(
    title="MindHome Assistant",
    description="Lokaler KI-Sprachassistent fuer Home Assistant",
    version="1.1.0",
    lifespan=lifespan,
)


# ----- Request/Response Modelle -----

class ChatRequest(BaseModel):
    text: str
    person: Optional[str] = None
    room: Optional[str] = None
    speaker_confidence: Optional[float] = None
    # Phase 9: Voice-Metadaten von STT
    voice_metadata: Optional[dict] = None


class TTSInfo(BaseModel):
    text: str = ""
    ssml: str = ""
    message_type: str = "casual"
    speed: int = 100
    volume: float = 0.8
    target_speaker: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    actions: list = []
    model_used: str = ""
    context_room: str = ""
    tts: Optional[TTSInfo] = None


class FeedbackRequest(BaseModel):
    notification_id: str = ""
    event_type: str = ""
    feedback_type: str  # ignored, dismissed, acknowledged, engaged, thanked


class SettingsUpdate(BaseModel):
    autonomy_level: Optional[int] = None


# ----- API Endpoints -----

@app.get("/api/assistant/health")
async def health():
    """Health Check - Status aller Komponenten."""
    return await brain.health_check()


@app.post("/api/assistant/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Hauptendpoint - Text an den Assistenten senden.

    Beispiel:
    POST /api/assistant/chat
    {"text": "Mach das Licht im Wohnzimmer aus", "person": "Max"}
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Kein Text angegeben")

    # Phase 9: Voice-Metadaten an MoodDetector weiterleiten
    if request.voice_metadata:
        brain.mood.analyze_voice_metadata(request.voice_metadata)

    result = await brain.process(request.text, request.person, request.room)

    # TTS-Daten als TTSInfo-Modell wrappen
    tts_raw = result.pop("tts", None)
    if tts_raw and isinstance(tts_raw, dict):
        result["tts"] = TTSInfo(**tts_raw)

    return ChatResponse(**result)


@app.get("/api/assistant/context")
async def get_context():
    """Debug: Aktueller Kontext-Snapshot."""
    return await brain.context_builder.build()


@app.get("/api/assistant/memory/search")
async def search_memory(q: str):
    """Sucht im Langzeitgedaechtnis (Episodic Memory)."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Kein Suchbegriff")
    results = await brain.memory.search_memories(q)
    return {"query": q, "results": results}


# ----- Semantic Memory Endpoints (Phase 2) -----

@app.get("/api/assistant/memory/facts")
async def get_all_facts():
    """Alle gespeicherten Fakten im semantischen Gedaechtnis."""
    facts = await brain.memory.semantic.get_all_facts()
    stats = await brain.memory.semantic.get_stats()
    return {"facts": facts, "stats": stats}


@app.get("/api/assistant/memory/facts/search")
async def search_facts(q: str, person: Optional[str] = None):
    """Sucht relevante Fakten per Vektor-Suche."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Kein Suchbegriff")
    results = await brain.memory.semantic.search_facts(
        query=q, limit=10, person=person
    )
    return {"query": q, "person": person, "results": results}


@app.get("/api/assistant/memory/facts/person/{person}")
async def get_person_facts(person: str):
    """Alle Fakten ueber eine bestimmte Person."""
    facts = await brain.memory.semantic.get_facts_by_person(person)
    return {"person": person, "facts": facts}


@app.get("/api/assistant/memory/facts/category/{category}")
async def get_category_facts(category: str):
    """Alle Fakten einer bestimmten Kategorie."""
    facts = await brain.memory.semantic.get_facts_by_category(category)
    return {"category": category, "facts": facts}


@app.delete("/api/assistant/memory/facts/{fact_id}")
async def delete_fact(fact_id: str):
    """Loescht einen einzelnen Fakt."""
    success = await brain.memory.semantic.delete_fact(fact_id)
    if not success:
        raise HTTPException(status_code=404, detail="Fakt nicht gefunden")
    return {"deleted": fact_id}


@app.get("/api/assistant/memory/stats")
async def memory_stats():
    """Statistiken ueber das gesamte Gedaechtnis."""
    semantic_stats = await brain.memory.semantic.get_stats()
    episodic_count = 0
    if brain.memory.chroma_collection:
        try:
            episodic_count = brain.memory.chroma_collection.count()
        except Exception:
            pass
    return {
        "semantic": semantic_stats,
        "episodic": {"total_episodes": episodic_count},
        "working": {
            "connected": brain.memory.redis is not None,
        },
    }


# ----- Feedback Endpoints (Phase 5) -----

@app.put("/api/assistant/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    Feedback auf eine proaktive Meldung geben.

    feedback_type: ignored, dismissed, acknowledged, engaged, thanked
    notification_id: ID der Meldung (aus WebSocket-Event)
    event_type: Alternativ den Event-Typ direkt angeben
    """
    identifier = request.notification_id or request.event_type
    if not identifier:
        raise HTTPException(
            status_code=400,
            detail="notification_id oder event_type erforderlich",
        )

    result = await brain.feedback.record_feedback(identifier, request.feedback_type)
    if not result:
        raise HTTPException(
            status_code=400,
            detail=f"Ungueltiger feedback_type: {request.feedback_type}",
        )
    return result


@app.get("/api/assistant/feedback/stats")
async def feedback_stats():
    """Feedback-Statistiken fuer alle Event-Typen."""
    return await brain.feedback.get_stats()


@app.get("/api/assistant/feedback/stats/{event_type}")
async def feedback_stats_event(event_type: str):
    """Feedback-Statistiken fuer einen bestimmten Event-Typ."""
    return await brain.feedback.get_stats(event_type)


@app.get("/api/assistant/feedback/scores")
async def feedback_scores():
    """Alle Feedback-Scores auf einen Blick."""
    scores = await brain.feedback.get_all_scores()
    return {"scores": scores, "total_types": len(scores)}


# ----- Mood Detector Endpoints (Phase 3) -----

@app.get("/api/assistant/mood")
async def get_mood():
    """Aktuelle Stimmungserkennung des Benutzers."""
    return brain.mood.get_current_mood()


# ----- Status Report Endpoint -----

@app.get("/api/assistant/status")
async def get_status_report(person: Optional[str] = None):
    """Generiert einen Jarvis-artigen Status-Bericht."""
    report = await brain.proactive.generate_status_report(person or settings.user_name)
    return {"report": report, "person": person or settings.user_name}


# ----- Activity Engine Endpoints (Phase 6) -----

@app.get("/api/assistant/activity")
async def get_activity():
    """Erkennt die aktuelle Aktivitaet des Benutzers."""
    detection = await brain.activity.detect_activity()
    return detection


@app.get("/api/assistant/activity/delivery")
async def get_delivery(urgency: str = "medium"):
    """Prueft wie eine Meldung bei aktueller Aktivitaet zugestellt wuerde."""
    result = await brain.activity.should_deliver(urgency)
    return result


# ----- Summarizer Endpoints (Phase 7) -----

@app.get("/api/assistant/summaries")
async def get_summaries():
    """Die neuesten Tages-Zusammenfassungen."""
    summaries = await brain.summarizer.get_recent_summaries(limit=7)
    return {"summaries": summaries}


@app.get("/api/assistant/summaries/search")
async def search_summaries(q: str):
    """Sucht in allen Zusammenfassungen (Vektor-Suche)."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Kein Suchbegriff")
    results = await brain.summarizer.search_summaries(q, limit=5)
    return {"query": q, "results": results}


@app.post("/api/assistant/summaries/generate/{date}")
async def generate_summary(date: str):
    """Erstellt manuell eine Tages-Zusammenfassung fuer ein bestimmtes Datum."""
    summary = await brain.summarizer.summarize_day(date)
    if not summary:
        return {"date": date, "summary": None, "message": "Keine Konversationen fuer diesen Tag"}
    return {"date": date, "summary": summary}


# ----- Action Planner Endpoints (Phase 4) -----

@app.get("/api/assistant/planner/last")
async def get_last_plan():
    """Gibt den letzten ausgefuehrten Aktionsplan zurueck."""
    plan = brain.action_planner.get_last_plan()
    if not plan:
        return {"plan": None, "message": "Kein Plan ausgefuehrt"}
    return {"plan": plan}


@app.get("/api/assistant/settings")
async def get_settings():
    """Aktuelle Einstellungen."""
    return {
        "autonomy": brain.autonomy.get_level_info(),
        "models": brain.model_router.get_model_info(),
        "user_name": settings.user_name,
        "language": settings.language,
    }


@app.put("/api/assistant/settings")
async def update_settings(update: SettingsUpdate):
    """Einstellungen aktualisieren."""
    result = {}
    if update.autonomy_level is not None:
        success = brain.autonomy.set_level(update.autonomy_level)
        if not success:
            raise HTTPException(status_code=400, detail="Level muss 1-5 sein")
        result["autonomy"] = brain.autonomy.get_level_info()
    return result


# ----- Phase 9: TTS & Sound Endpoints -----

@app.get("/api/assistant/tts/status")
async def tts_status():
    """Phase 9: TTS-Status (SSML, Whisper-Mode, Volume)."""
    return {
        "ssml_enabled": brain.tts_enhancer.ssml_enabled,
        "whisper_mode": brain.tts_enhancer.is_whisper_mode,
        "sounds_enabled": brain.sound_manager.enabled,
        "sounds": brain.sound_manager.get_sound_info(),
    }


@app.post("/api/assistant/tts/whisper")
async def toggle_whisper(mode: str = "toggle"):
    """Phase 9: Fluestermodus steuern (activate/deactivate/toggle)."""
    if mode == "activate":
        brain.tts_enhancer._whisper_mode = True
    elif mode == "deactivate":
        brain.tts_enhancer._whisper_mode = False
    elif mode == "toggle":
        brain.tts_enhancer._whisper_mode = not brain.tts_enhancer._whisper_mode
    return {"whisper_mode": brain.tts_enhancer.is_whisper_mode}


# ----- Phase 9: Speaker Recognition Endpoints -----

@app.get("/api/assistant/speaker/profiles")
async def get_speaker_profiles():
    """Phase 9: Alle gespeicherten Stimm-Profile."""
    return {
        "enabled": brain.speaker_recognition.enabled,
        "profiles": brain.speaker_recognition.get_profiles(),
        "last_speaker": brain.speaker_recognition.get_last_speaker(),
    }


@app.post("/api/assistant/speaker/enroll")
async def enroll_speaker(person_id: str, name: str):
    """Phase 9: Neues Stimm-Profil anlegen."""
    if not brain.speaker_recognition.enabled:
        raise HTTPException(status_code=400, detail="Speaker Recognition ist deaktiviert")
    success = await brain.speaker_recognition.enroll(person_id, name)
    if not success:
        raise HTTPException(status_code=400, detail="Enrollment fehlgeschlagen (max Profile erreicht?)")
    return {"enrolled": True, "person_id": person_id, "name": name}


@app.delete("/api/assistant/speaker/profiles/{person_id}")
async def delete_speaker_profile(person_id: str):
    """Phase 9: Stimm-Profil loeschen."""
    success = await brain.speaker_recognition.remove_profile(person_id)
    if not success:
        raise HTTPException(status_code=404, detail="Profil nicht gefunden")
    return {"deleted": person_id}


# ----- Phase 10: Diagnostik Endpoints -----

@app.get("/api/assistant/diagnostics")
async def diagnostics():
    """Phase 10: System-Diagnostik — Prueft Entities auf Probleme."""
    result = await brain.diagnostics.check_all()
    return result


@app.get("/api/assistant/diagnostics/status")
async def diagnostics_status():
    """Phase 10: Vollstaendiger System-Status-Report."""
    return await brain.diagnostics.get_system_status()


# ----- Phase 10: Wartungs-Assistent Endpoints -----

@app.get("/api/assistant/maintenance")
async def maintenance_tasks():
    """Phase 10: Alle Wartungsaufgaben und faellige Tasks."""
    tasks = brain.diagnostics.get_maintenance_tasks()
    due = brain.diagnostics.check_maintenance()
    return {"tasks": tasks, "due": due}


@app.post("/api/assistant/maintenance/complete")
async def complete_maintenance(task_name: str):
    """Phase 10: Wartungsaufgabe als erledigt markieren."""
    success = brain.diagnostics.complete_task(task_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Aufgabe '{task_name}' nicht gefunden")
    return {"completed": task_name, "date": __import__("datetime").datetime.now().strftime("%Y-%m-%d")}


# ----- Phase 11: Koch-Assistent Endpoints -----

@app.get("/api/assistant/cooking/status")
async def cooking_status():
    """Phase 11: Status der Koch-Session."""
    if not brain.cooking.has_active_session:
        return {"active": False, "session": None}

    session = brain.cooking.session
    current_step = session.get_current_step()
    active_timers = [
        {"label": t.label, "remaining": t.format_remaining(), "done": t.is_done}
        for t in session.timers
    ]

    return {
        "active": True,
        "session": {
            "dish": session.dish,
            "portions": session.portions,
            "total_steps": session.total_steps,
            "current_step": session.current_step,
            "current_instruction": current_step.instruction if current_step else None,
            "ingredients": session.ingredients,
            "timers": active_timers,
        },
    }


@app.post("/api/assistant/cooking/stop")
async def cooking_stop():
    """Phase 11: Koch-Session beenden."""
    if not brain.cooking.has_active_session:
        return {"stopped": False, "message": "Keine aktive Koch-Session."}
    result = brain.cooking._stop_session()
    return {"stopped": True, "message": result}


# ----- Phase 12: Datei-Upload im Chat -----

@app.post("/api/assistant/chat/upload")
async def chat_upload(
    file: UploadFile = File(...),
    caption: str = Form(""),
    person: str = Form(""),
):
    """
    Datei hochladen und im Chat-Kontext verarbeiten.

    Speichert die Datei, extrahiert Text aus Dokumenten und
    sendet den Inhalt zusammen mit der optionalen Beschreibung
    an das Brain zur Verarbeitung.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Keine Datei ausgewaehlt")

    if not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Dateityp nicht erlaubt")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        mb = MAX_FILE_SIZE // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Datei zu gross (max {mb} MB)")

    # Save file and extract text
    file_info = save_upload(file.filename, content)

    # Build a message for the brain that includes file context
    file_context = build_file_context([file_info])
    text = caption.strip() if caption.strip() else (
        f"Ich habe eine Datei geschickt: {file_info['name']}"
    )

    # Process through brain with file context
    result = await brain.process(
        text=text,
        person=person or None,
        room=None,
        files=[file_info],
    )

    # TTS wrapping
    tts_raw = result.pop("tts", None)
    if tts_raw and isinstance(tts_raw, dict):
        result["tts"] = TTSInfo(**tts_raw)

    return {
        "file": {
            "name": file_info["name"],
            "url": file_info["url"],
            "type": file_info["type"],
            "size": file_info["size"],
            "ext": file_info["ext"],
        },
        "response": result.get("response", ""),
        "actions": result.get("actions", []),
        "model_used": result.get("model_used", ""),
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }


@app.get("/api/assistant/chat/files/{filename:path}")
async def chat_serve_file(filename: str):
    """Gespeicherte Chat-Datei ausliefern."""
    path = get_file_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(path, filename=path.name)


# ----- Phase 10: Trust-Level Endpoints -----

@app.get("/api/assistant/trust")
async def trust_info():
    """Phase 10: Trust-Level-Konfiguration aller Personen."""
    return brain.autonomy.get_trust_info()


@app.get("/api/assistant/trust/{person}")
async def trust_person(person: str):
    """Phase 10: Trust-Level einer bestimmten Person."""
    trust_level = brain.autonomy.get_trust_level(person)
    trust_names = {0: "Gast", 1: "Mitbewohner", 2: "Owner"}
    return {
        "person": person,
        "trust_level": trust_level,
        "trust_name": trust_names.get(trust_level, "Unbekannt"),
    }


@app.websocket("/api/assistant/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket fuer Echtzeit-Events.

    Events (Server -> Client):
    assistant.speaking - Assistent spricht (Text + TTS-Metadaten)
    assistant.thinking - Assistent denkt nach
    assistant.action - Assistent fuehrt Aktion aus
    assistant.listening - Assistent hoert zu
    assistant.proactive - Proaktive Meldung
    assistant.sound - Sound-Event (Phase 9)

    Events (Client -> Server):
    assistant.text - Text-Eingabe (+ optional voice_metadata)
    assistant.feedback - Feedback auf Meldung
    assistant.interrupt - Unterbrechung
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                event = message.get("event", "")

                if event == "assistant.text":
                    text = message.get("data", {}).get("text", "")
                    person = message.get("data", {}).get("person")
                    voice_meta = message.get("data", {}).get("voice_metadata")
                    if text:
                        # Phase 9: Voice-Metadaten verarbeiten
                        if voice_meta:
                            brain.mood.analyze_voice_metadata(voice_meta)
                        result = await brain.process(text, person)
                        tts_data = result.get("tts")
                        await emit_speaking(result["response"], tts_data=tts_data)

                elif event == "assistant.feedback":
                    # Phase 5: Feedback ueber FeedbackTracker verarbeiten
                    fb_data = message.get("data", {})
                    notification_id = fb_data.get("notification_id", "")
                    event_type = fb_data.get("event_type", "")
                    feedback_type = fb_data.get("response", fb_data.get("feedback_type", "ignored"))
                    identifier = notification_id or event_type
                    if identifier:
                        await brain.feedback.record_feedback(identifier, feedback_type)

                elif event == "assistant.interrupt":
                    pass  # Fuer spaetere Streaming-Unterbrechung

            except json.JSONDecodeError:
                await ws_manager.send_personal(
                    websocket, "error", {"message": "Ungueltiges JSON"}
                )
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/")
async def root():
    """Startseite."""
    return {
        "name": "MindHome Assistant",
        "version": "1.1.0",
        "status": "running",
        "docs": "/docs",
    }


def start():
    """Einstiegspunkt fuer den Server."""
    import uvicorn

    uvicorn.run(
        "assistant.main:app",
        host=settings.assistant_host,
        port=settings.assistant_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    start()
