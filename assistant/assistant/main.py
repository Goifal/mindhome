"""
MindHome Assistant - Hauptanwendung (FastAPI Server)
Startet den MindHome Assistant REST API Server.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

import yaml

from .brain import AssistantBrain
from .config import settings, yaml_config, load_yaml_config
from .file_handler import (
    allowed_file, ensure_upload_dir,
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

# ----- CORS Policy -----
# Nur lokale Zugriffe erlauben (HA Add-on + lokale Clients)
_cors_origins = os.getenv("CORS_ORIGINS", "").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins.split(",") if _cors_origins else [
        "http://localhost",
        "http://localhost:8123",
        "http://homeassistant.local:8123",
        f"http://localhost:{settings.assistant_port}",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ----- Rate-Limiting (in-memory, pro IP) -----
import time as _time
from collections import defaultdict as _defaultdict

_rate_limits: dict[str, list[float]] = _defaultdict(list)
_RATE_WINDOW = 60        # Sekunden
_RATE_MAX_REQUESTS = 60  # Max Requests pro Fenster


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Einfaches Rate-Limiting pro Client-IP."""
    client_ip = request.client.host if request.client else "unknown"
    now = _time.time()

    # Alte Eintraege bereinigen
    _rate_limits[client_ip] = [
        t for t in _rate_limits[client_ip] if now - t < _RATE_WINDOW
    ]

    if len(_rate_limits[client_ip]) >= _RATE_MAX_REQUESTS:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": "Zu viele Anfragen. Bitte warten."},
        )

    _rate_limits[client_ip].append(now)
    return await call_next(request)


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
async def update_settings(update: SettingsUpdate, token: str = ""):
    """Einstellungen aktualisieren (PIN-geschuetzt)."""
    _check_token(token)
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


class VoiceRequest(BaseModel):
    text: str
    room: Optional[str] = None


@app.post("/api/assistant/voice")
async def voice_output(request: VoiceRequest):
    """
    Foundation F.1: TTS-Only Endpoint — Text direkt als Sprache ausgeben (kein Chat).

    Beispiel:
    POST /api/assistant/voice
    {"text": "Das Essen ist fertig!", "room": "kueche"}
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Kein Text angegeben")

    # TTS-Enhancer fuer SSML/Speed/Volume nutzen
    tts_data = brain.tts_enhancer.enhance(request.text, message_type="announcement")

    # WebSocket-Event senden (assistant.audio)
    from .websocket import ws_manager
    await ws_manager.broadcast("assistant.audio", {
        "text": request.text,
        "ssml": tts_data.get("ssml", request.text),
        "message_type": "announcement",
        "speed": tts_data.get("speed", 100),
        "volume": tts_data.get("volume", 0.8),
        "room": request.room,
    })

    return {
        "success": True,
        "text": request.text,
        "tts": tts_data,
        "room": request.room,
    }


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
async def complete_maintenance(task_name: str, token: str = ""):
    """Phase 10: Wartungsaufgabe als erledigt markieren (PIN-geschuetzt)."""
    _check_token(token)
    success = brain.diagnostics.complete_task(task_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Aufgabe '{task_name}' nicht gefunden")
    return {"completed": task_name, "date": __import__("datetime").datetime.now().strftime("%Y-%m-%d")}


# ----- Phase 14.3: Ambient Audio Endpoints -----

@app.get("/api/assistant/ambient-audio")
async def ambient_audio_info():
    """Phase 14.3: Ambient Audio Status und Konfiguration."""
    return brain.ambient_audio.get_info()


@app.get("/api/assistant/ambient-audio/events")
async def ambient_audio_events(limit: int = 20):
    """Phase 14.3: Letzte erkannte Audio-Events."""
    return {"events": brain.ambient_audio.get_recent_events(limit)}


@app.post("/api/assistant/ambient-audio/event")
async def ambient_audio_webhook(
    event_type: str,
    room: Optional[str] = None,
    confidence: float = 1.0,
):
    """Phase 14.3: Webhook fuer externe Audio-Klassifizierer (ESPHome, Frigate etc.)."""
    result = await brain.ambient_audio.process_event(
        event_type=event_type,
        room=room,
        confidence=confidence,
        source="webhook",
    )
    if result:
        return {"processed": True, "event": result}
    return {"processed": False, "reason": "Event unterdrueckt (Cooldown, Confidence oder deaktiviert)"}


# ----- Phase 16.1: Conflict Resolver Endpoints -----

@app.get("/api/assistant/conflicts")
async def conflict_info():
    """Phase 16.1: Conflict Resolver Status und Info."""
    return brain.conflict_resolver.get_info()


@app.get("/api/assistant/conflicts/history")
async def conflict_history(limit: int = 20):
    """Phase 16.1: Letzte Konflikte und ihre Loesungen."""
    return {"conflicts": brain.conflict_resolver.get_recent_conflicts(limit)}


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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


class ProactiveTriggerRequest(BaseModel):
    event_type: str  # z.B. "reminder", "check_in", "status_report"
    urgency: Optional[str] = "medium"  # low, medium, high, critical
    data: Optional[dict] = None


@app.post("/api/assistant/proactive/trigger")
async def proactive_trigger(request: ProactiveTriggerRequest):
    """
    Foundation F.2: Manueller Trigger fuer proaktive Aktionen.

    Kann von HA-Automationen aufgerufen werden, z.B.:
    POST /api/assistant/proactive/trigger
    {"event_type": "status_report", "urgency": "medium"}
    """
    data = request.data or {}
    data["event_type"] = request.event_type
    data["urgency"] = request.urgency
    data["triggered_by"] = "api"

    # Status-Report als Spezialfall
    if request.event_type == "status_report":
        report = await brain.proactive.generate_status_report()
        return {"success": True, "event_type": "status_report", "report": report}

    # Generischer Trigger: Event an ProactiveManager weiterleiten
    await brain.proactive._handle_mindhome_event(data)

    return {
        "success": True,
        "event_type": request.event_type,
        "urgency": request.urgency,
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
    assistant.audio - TTS-Audio-Daten (Foundation F.3, via /api/assistant/voice)

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


# ============================================================
# Jarvis Dashboard — UI + Settings API
# ============================================================

import hashlib
import secrets

# Settings-YAML Pfad
SETTINGS_YAML_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

# Session-Token mit Ablaufzeit (4 Stunden)
_TOKEN_EXPIRY_SECONDS = 4 * 60 * 60  # 4 Stunden
_active_tokens: dict[str, float] = {}  # token -> timestamp


def _get_dashboard_config() -> dict:
    """Liest die aktuelle Dashboard-Konfiguration aus settings.yaml."""
    try:
        with open(SETTINGS_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}
        return config.get("dashboard", {})
    except Exception:
        return {}


def _get_current_pin() -> str:
    """Gibt den aktuellen PIN zurueck (Env > YAML)."""
    env_pin = os.environ.get("JARVIS_UI_PIN")
    if env_pin:
        return env_pin
    return _get_dashboard_config().get("pin_hash", "")


def _is_setup_complete() -> bool:
    """Prueft ob das initiale Setup abgeschlossen ist."""
    dc = _get_dashboard_config()
    return dc.get("setup_complete", False)


def _hash_value(value: str) -> str:
    """Hasht einen Wert mit SHA-256."""
    return hashlib.sha256(value.encode()).hexdigest()


def _save_dashboard_config(pin_hash: str, recovery_hash: str, setup_complete: bool = True):
    """Speichert Dashboard-Konfiguration in settings.yaml."""
    try:
        with open(SETTINGS_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}
        if "dashboard" not in config:
            config["dashboard"] = {}
        config["dashboard"]["pin_hash"] = pin_hash
        config["dashboard"]["recovery_key_hash"] = recovery_hash
        config["dashboard"]["setup_complete"] = setup_complete
        # Alten Klartext-PIN entfernen falls vorhanden
        config["dashboard"].pop("pin", None)
        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        # Config im Speicher aktualisieren
        import assistant.config as cfg
        cfg.yaml_config = load_yaml_config()
    except Exception as e:
        logger.error("Dashboard-Config speichern fehlgeschlagen: %s", e)
        raise


class PinRequest(BaseModel):
    pin: str


class SetupRequest(BaseModel):
    pin: str
    pin_confirm: str


class ResetPinRequest(BaseModel):
    recovery_key: str
    new_pin: str
    new_pin_confirm: str


class SettingsUpdateFull(BaseModel):
    settings: dict


@app.get("/api/ui/setup-status")
async def ui_setup_status():
    """Prueft ob das initiale Setup abgeschlossen ist (kein Auth noetig)."""
    return {"setup_complete": _is_setup_complete()}


@app.post("/api/ui/setup")
async def ui_setup(req: SetupRequest):
    """Erstmaliges Setup: PIN setzen + Recovery-Key generieren."""
    if _is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup bereits abgeschlossen")

    if req.pin != req.pin_confirm:
        raise HTTPException(status_code=400, detail="PINs stimmen nicht ueberein")

    if len(req.pin) < 4:
        raise HTTPException(status_code=400, detail="PIN muss mindestens 4 Zeichen haben")

    # Recovery-Key generieren (12 Zeichen, alphanumerisch)
    recovery_key = secrets.token_urlsafe(16)[:12].upper()

    # PIN + Recovery-Key gehasht speichern
    pin_hash = _hash_value(req.pin)
    recovery_hash = _hash_value(recovery_key)
    _save_dashboard_config(pin_hash, recovery_hash, setup_complete=True)

    logger.info("Dashboard: Erstmaliges Setup abgeschlossen")

    # Recovery-Key dem User anzeigen (nur dieses eine Mal!)
    return {
        "success": True,
        "recovery_key": recovery_key,
        "message": "PIN gesetzt. Recovery-Key sicher aufbewahren!",
    }


@app.post("/api/ui/auth")
async def ui_auth(req: PinRequest):
    """PIN-Authentifizierung fuer das Jarvis Dashboard."""
    if not _is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup noch nicht abgeschlossen")

    # Vergleich: Env-PIN (Klartext) oder gehashter PIN aus YAML
    env_pin = os.environ.get("JARVIS_UI_PIN")
    if env_pin:
        valid = (req.pin == env_pin)
    else:
        stored_hash = _get_dashboard_config().get("pin_hash", "")
        valid = (stored_hash and _hash_value(req.pin) == stored_hash)

    if not valid:
        _audit_log("login", {"success": False})
        raise HTTPException(status_code=401, detail="Falscher PIN")

    token = hashlib.sha256(f"{req.pin}{datetime.now().isoformat()}{secrets.token_hex(8)}".encode()).hexdigest()[:32]
    _active_tokens[token] = datetime.now(timezone.utc).timestamp()
    # Abgelaufene Tokens aufraumen
    _cleanup_expired_tokens()
    _audit_log("login", {"success": True})
    return {"token": token}


@app.post("/api/ui/reset-pin")
async def ui_reset_pin(req: ResetPinRequest):
    """PIN zuruecksetzen mit Recovery-Key."""
    if not _is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup noch nicht abgeschlossen")

    if req.new_pin != req.new_pin_confirm:
        raise HTTPException(status_code=400, detail="PINs stimmen nicht ueberein")

    if len(req.new_pin) < 4:
        raise HTTPException(status_code=400, detail="PIN muss mindestens 4 Zeichen haben")

    # Recovery-Key pruefen
    stored_recovery_hash = _get_dashboard_config().get("recovery_key_hash", "")
    if not stored_recovery_hash or _hash_value(req.recovery_key) != stored_recovery_hash:
        raise HTTPException(status_code=401, detail="Falscher Recovery-Key")

    # Neuen Recovery-Key generieren
    new_recovery_key = secrets.token_urlsafe(16)[:12].upper()
    pin_hash = _hash_value(req.new_pin)
    recovery_hash = _hash_value(new_recovery_key)
    _save_dashboard_config(pin_hash, recovery_hash, setup_complete=True)

    # Alle bestehenden Sessions ungueltig machen
    _active_tokens.clear()

    logger.info("Dashboard: PIN zurueckgesetzt via Recovery-Key")
    _audit_log("pin_reset", {"via": "recovery_key"})

    return {
        "success": True,
        "recovery_key": new_recovery_key,
        "message": "Neuer PIN gesetzt. Neuen Recovery-Key sicher aufbewahren!",
    }


# ---- Audit-Logging: Dashboard-Aenderungen protokollieren ----
_AUDIT_LOG_PATH = Path(__file__).parent.parent / "logs" / "audit.jsonl"


def _audit_log(action: str, details: dict = None):
    """Schreibt einen Eintrag ins Audit-Log (JSON-Lines)."""
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details or {},
        }
        with open(_AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Audit-Log Fehler: %s", exc)


def _cleanup_expired_tokens():
    """Entfernt abgelaufene Tokens."""
    now = datetime.now(timezone.utc).timestamp()
    expired = [t for t, ts in _active_tokens.items() if now - ts > _TOKEN_EXPIRY_SECONDS]
    for t in expired:
        del _active_tokens[t]


def _check_token(token: str):
    """Prueft ob ein UI-Token gueltig ist und nicht abgelaufen."""
    if token not in _active_tokens:
        raise HTTPException(status_code=401, detail="Nicht autorisiert")
    # Ablaufzeit pruefen
    created = _active_tokens[token]
    now = datetime.now(timezone.utc).timestamp()
    if now - created > _TOKEN_EXPIRY_SECONDS:
        del _active_tokens[token]
        raise HTTPException(status_code=401, detail="Sitzung abgelaufen. Bitte erneut anmelden.")


@app.get("/api/ui/settings")
async def ui_get_settings(token: str = ""):
    """Alle Settings aus settings.yaml als JSON."""
    _check_token(token)
    try:
        with open(SETTINGS_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.put("/api/ui/settings")
async def ui_update_settings(req: SettingsUpdateFull, token: str = ""):
    """Settings in settings.yaml aktualisieren (Merge, nicht ersetzen)."""
    _check_token(token)
    try:
        # Aktuelle Config laden
        with open(SETTINGS_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}

        # Deep Merge
        _deep_merge(config, req.settings)

        # Zurueckschreiben
        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # yaml_config im Speicher aktualisieren
        import assistant.config as cfg
        cfg.yaml_config = load_yaml_config()

        # Audit-Log
        changed_keys = list(req.settings.keys()) if isinstance(req.settings, dict) else []
        _audit_log("settings_update", {"changed_sections": changed_keys})

        return {"success": True, "message": "Settings gespeichert"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/entities")
async def ui_get_entities(token: str = "", domain: str = ""):
    """Alle HA-Entities holen (optional nach Domain filtern)."""
    _check_token(token)
    try:
        states = await brain.ha.get_states()
        entities = []
        for s in (states or []):
            eid = s.get("entity_id", "")
            if domain and not eid.startswith(f"{domain}."):
                continue
            entities.append({
                "entity_id": eid,
                "state": s.get("state", "unknown"),
                "name": s.get("attributes", {}).get("friendly_name", eid),
                "domain": eid.split(".")[0] if "." in eid else "",
            })
        entities.sort(key=lambda e: (e["domain"], e["name"]))
        return {"entities": entities, "total": len(entities)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/stats")
async def ui_get_stats(token: str = ""):
    """Kombinierte Statistiken fuer das Dashboard."""
    _check_token(token)
    try:
        semantic_stats = await brain.memory.semantic.get_stats()
        kb_stats = await brain.knowledge_base.get_stats()
        episodic_count = 0
        if brain.memory.chroma_collection:
            try:
                episodic_count = brain.memory.chroma_collection.count()
            except Exception:
                pass

        return {
            "memory": {
                "semantic": semantic_stats,
                "episodic_count": episodic_count,
                "redis_connected": brain.memory.redis is not None,
            },
            "knowledge_base": kb_stats,
            "components": (await brain.health_check()).get("components", {}),
            "autonomy": brain.autonomy.get_level_info(),
            "mood": brain.mood.get_current_mood(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


# ----- Phase 16.3: Live-Status WebSocket Broadcast -----

@app.get("/api/ui/live-status")
async def ui_live_status(token: str = ""):
    """Phase 16.3: Live-Status aller Systeme fuer Dashboard-Polling."""
    _check_token(token)
    try:
        health = await brain.health_check()
        mood = brain.mood.get_current_mood()
        health_status = await brain.health_monitor.get_status() if hasattr(brain, "health_monitor") else {}
        autonomy = brain.autonomy.get_level_info()
        whisper = brain.tts_enhancer.is_whisper_mode

        return {
            "timestamp": datetime.now().isoformat(),
            "system_health": health,
            "mood": mood,
            "room_health": health_status,
            "autonomy": autonomy,
            "whisper_mode": whisper,
            "components_ok": all(
                v != "error" for v in health.get("components", {}).values()
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


# ----- Phase 15.4: Notification Kanal-Wahl -----

@app.get("/api/ui/notification-channels")
async def ui_notification_channels(token: str = ""):
    """Phase 15.4: Verfuegbare Benachrichtigungs-Kanaele und deren Status."""
    _check_token(token)
    channels = {
        "websocket": {
            "enabled": True,
            "description": "Browser/Dashboard Push",
            "connected_clients": len(ws_manager.active_connections) if hasattr(ws_manager, "active_connections") else 0,
        },
        "tts": {
            "enabled": brain.sound_manager.enabled if hasattr(brain, "sound_manager") else False,
            "description": "Sprachausgabe ueber Lautsprecher",
        },
        "ha_notify": {
            "enabled": True,
            "description": "Home Assistant Notifications (App/Handy)",
        },
    }

    # Kanal-Praeferenzen aus Config
    notify_cfg = yaml_config.get("notifications", {})
    channel_prefs = notify_cfg.get("channels", {})
    for ch_name, ch_cfg in (channel_prefs or {}).items():
        if ch_name in channels:
            channels[ch_name]["preferred"] = ch_cfg.get("preferred", False)
            channels[ch_name]["quiet_hours"] = ch_cfg.get("quiet_hours", [])
            channels[ch_name]["urgency_min"] = ch_cfg.get("urgency_min", "low")

    return {"channels": channels}


@app.put("/api/ui/notification-channels")
async def ui_update_notification_channels(
    updates: dict, token: str = "",
):
    """Phase 15.4: Kanal-Praeferenzen aktualisieren."""
    _check_token(token)
    # In settings.yaml speichern
    try:
        config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
        else:
            cfg = {}

        cfg.setdefault("notifications", {})["channels"] = updates
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        return {"success": True, "channels": updates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


# ----- Phase 15.1: Gesundheits-Trend-Dashboard -----

@app.get("/api/ui/health-trends")
async def ui_health_trends(token: str = "", hours: int = 24):
    """Phase 15.1: Trend-Daten fuer Raumklima (CO2, Temp, Humidity)."""
    _check_token(token)
    hours = min(hours, 168)  # Max 7 Tage

    # Aktueller Status
    current = await brain.health_monitor.get_status() if hasattr(brain, "health_monitor") else {}

    # Trend-Daten aus Redis (stuendliche Snapshots)
    trends = {"co2": [], "temperature": [], "humidity": []}
    if brain.memory.redis:
        try:
            now = datetime.now()
            for h in range(hours):
                ts = now - timedelta(hours=h)
                key = f"mha:health:snapshot:{ts.strftime('%Y-%m-%d:%H')}"
                data = await brain.memory.redis.get(key)
                if data:
                    import json as _json
                    snapshot = _json.loads(data)
                    time_str = ts.strftime("%Y-%m-%d %H:00")
                    for sensor_type in ("co2", "temperature", "humidity"):
                        if sensor_type in snapshot:
                            trends[sensor_type].append({
                                "time": time_str,
                                "value": snapshot[sensor_type],
                            })
        except Exception as e:
            logger.debug("Health-Trends laden fehlgeschlagen: %s", e)

    # Trends chronologisch sortieren
    for key in trends:
        trends[key].reverse()

    return {
        "current": current,
        "trends": trends,
        "hours_requested": hours,
    }


@app.get("/api/ui/knowledge")
async def ui_knowledge_info(token: str = ""):
    """Knowledge Base Statistiken und Dateiliste."""
    _check_token(token)
    stats = await brain.knowledge_base.get_stats()
    # Dateien im Knowledge-Verzeichnis auflisten
    kb_dir = Path(__file__).parent.parent / "config" / "knowledge"
    files = []
    if kb_dir.exists():
        for f in sorted(kb_dir.iterdir()):
            if f.is_file() and f.suffix in {".txt", ".md", ".yaml", ".yml", ".csv", ".pdf"}:
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
    return {"stats": stats, "files": files}


@app.post("/api/ui/knowledge/ingest")
async def ui_knowledge_ingest(token: str = ""):
    """Knowledge Base neu einlesen (alle Dateien)."""
    _check_token(token)
    count = await brain.knowledge_base.ingest_all()
    stats = await brain.knowledge_base.get_stats()
    return {"new_chunks": count, "stats": stats}


@app.get("/api/ui/logs")
async def ui_get_logs(token: str = "", limit: int = 50):
    """Letzte Konversationen aus dem Working Memory."""
    _check_token(token)
    conversations = await brain.memory.get_recent_conversations(min(limit, 200))
    return {"conversations": conversations, "total": len(conversations)}


@app.get("/api/ui/audit")
async def ui_get_audit(token: str = "", limit: int = 50):
    """Audit-Log: Letzte Dashboard-Aenderungen und Auth-Events."""
    _check_token(token)
    entries = []
    if _AUDIT_LOG_PATH.exists():
        with open(_AUDIT_LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    # Neueste zuerst, limitiert
    entries.reverse()
    return {"entries": entries[:min(limit, 200)], "total": len(entries)}


# Statische UI-Dateien ausliefern
_ui_static_dir = Path(__file__).parent.parent / "static" / "ui"
_ui_static_dir.mkdir(parents=True, exist_ok=True)


@app.get("/ui/{path:path}")
async def ui_serve(path: str = ""):
    """Jarvis Dashboard — Single-Page App."""
    index_path = _ui_static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>Jarvis Dashboard — index.html nicht gefunden</h1>", status_code=404)


@app.get("/ui")
async def ui_redirect():
    """Redirect /ui zu /ui/."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/")


# ============================================================
# Easter Eggs API
# ============================================================

EASTER_EGGS_PATH = Path(__file__).parent.parent / "config" / "easter_eggs.yaml"


@app.get("/api/ui/easter-eggs")
async def ui_get_easter_eggs(token: str = ""):
    """Alle Easter Eggs aus easter_eggs.yaml."""
    _check_token(token)
    try:
        with open(EASTER_EGGS_PATH) as f:
            data = yaml.safe_load(f) or {}
        return {"easter_eggs": data.get("easter_eggs", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


class EasterEggUpdate(BaseModel):
    easter_eggs: list


@app.put("/api/ui/easter-eggs")
async def ui_update_easter_eggs(req: EasterEggUpdate, token: str = ""):
    """Easter Eggs speichern."""
    _check_token(token)
    try:
        data = {"easter_eggs": req.easter_eggs}
        with open(EASTER_EGGS_PATH, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # Personality-Engine neu laden
        if hasattr(brain, "personality") and brain.personality:
            brain.personality._easter_eggs = brain.personality._load_easter_eggs()

        _audit_log("easter_eggs_update", {"count": len(req.easter_eggs)})
        return {"success": True, "message": f"{len(req.easter_eggs)} Easter Eggs gespeichert"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


def _deep_merge(base: dict, override: dict):
    """Tiefer Merge von override in base (in-place)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@app.get("/")
async def root():
    """Startseite."""
    return {
        "name": "MindHome Assistant",
        "version": "1.1.0",
        "status": "running",
        "docs": "/docs",
        "dashboard": "/ui/",
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
