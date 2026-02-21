"""
MindHome Assistant - Hauptanwendung (FastAPI Server)
Startet den MindHome Assistant REST API Server.
"""

import asyncio
import json
import logging
import os
import random
import secrets
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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
from .websocket import ws_manager, emit_speaking, emit_stream_start, emit_stream_token, emit_stream_end

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mindhome-assistant")

# ---- Fehlerspeicher: Ring-Buffer fuer WARNING/ERROR Logs ----
_error_buffer: deque[dict] = deque(maxlen=200)


class _ErrorBufferHandler(logging.Handler):
    """Faengt WARNING+ Log-Eintraege ab und speichert sie im Ring-Buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _error_buffer.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            })
        except Exception:
            pass


_err_handler = _ErrorBufferHandler(level=logging.WARNING)
_err_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_err_handler)

# Brain-Instanz
brain = AssistantBrain()


async def _boot_announcement(brain_instance: "AssistantBrain", health_data: dict, cfg: dict):
    """Jarvis Boot-Sequenz — kuendigt sich nach dem Start gesprochenen an."""
    delay = cfg.get("delay_seconds", 5)
    await asyncio.sleep(delay)

    try:
        # Haus-Status sammeln
        states = await brain_instance.ha.get_states()
        temp = None
        open_items = []

        for s in (states or []):
            eid = s.get("entity_id", "")
            state_val = s.get("state", "")
            attrs = s.get("attributes", {})

            # Erste Raumtemperatur finden
            if temp is None and eid.startswith("climate."):
                t = attrs.get("current_temperature")
                if t is not None:
                    try:
                        temp = float(t)
                    except (ValueError, TypeError):
                        pass

            # Offene Fenster/Tueren zaehlen
            if state_val == "on" and (
                attrs.get("device_class") in ("window", "door")
                or "window" in eid
                or "door" in eid
            ):
                name = attrs.get("friendly_name", eid)
                open_items.append(name)

        # Boot-Nachricht zusammenbauen
        messages = cfg.get("messages", [
            "Alle Systeme online, Sir.",
            "Systeme hochgefahren, Sir. Alles bereit.",
            "Online, Sir. Soll ich den Status durchgehen?",
        ])
        msg = random.choice(messages)

        # Temperatur anhaengen
        if temp is not None:
            msg += f" Raumtemperatur bei {temp:.0f} Grad."

        # Fehlende Komponenten pruefen
        components = health_data.get("components", {})
        failed = [c for c, s in components.items() if s != "connected"]
        if failed:
            msg += f" {len(failed)} {'System' if len(failed) == 1 else 'Systeme'} eingeschraenkt."
        elif not open_items:
            msg += " Keine Auffaelligkeiten."

        # Offene Fenster/Tueren
        if open_items:
            if len(open_items) <= 3:
                msg += f" Offen: {', '.join(open_items)}."
            else:
                msg += f" {len(open_items)} Fenster oder Tueren sind offen."

        # Greeting-Sound + Ansage
        if hasattr(brain_instance, "sound_manager"):
            await brain_instance.sound_manager.play_event_sound("greeting")
            await asyncio.sleep(1)

        await emit_speaking(msg)
        logger.info("Boot-Sequenz: %s", msg)

    except Exception as e:
        logger.warning("Boot-Sequenz fehlgeschlagen: %s", e)
        try:
            await emit_speaking("Alle Systeme online, Sir.")
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup und Shutdown."""
    logger.info("=" * 50)
    logger.info(" MindHome Assistant v1.4.1 startet...")
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

    # Boot-Sequenz: Jarvis kuendigt sich an
    boot_cfg = yaml_config.get("boot_sequence", {})
    if boot_cfg.get("enabled", True):
        asyncio.create_task(_boot_announcement(brain, health, boot_cfg))

    yield

    await brain.shutdown()
    logger.info("MindHome Assistant heruntergefahren.")


app = FastAPI(
    title="MindHome Assistant",
    description="Lokaler KI-Sprachassistent fuer Home Assistant",
    version="1.4.1",
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ----- Rate-Limiting (in-memory, pro IP) -----
import time as _time
from collections import defaultdict as _defaultdict

_rate_limits: dict[str, list[float]] = _defaultdict(list)
_RATE_WINDOW = 60        # Sekunden
_RATE_MAX_REQUESTS = 60  # Max Requests pro Fenster


@app.middleware("http")
async def auth_header_middleware(request: Request, call_next):
    """Extract Bearer token from Authorization header and add as query param."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and "token=" not in str(request.url):
        token = auth[7:]
        # Inject token into query params for FastAPI parameter resolution
        scope = request.scope
        qs = scope.get("query_string", b"").decode()
        sep = "&" if qs else ""
        scope["query_string"] = f"{qs}{sep}token={token}".encode()
    return await call_next(request)


# ----- API Key Authentication fuer /api/assistant/* Endpoints -----
# Schuetzt alle Assistant-API-Endpoints gegen unautorisierte Netzwerkzugriffe.
#
# WICHTIG: Key wird beim ersten Start auto-generiert und bereitgehalten,
# aber NUR enforced wenn security.api_key_required = true in settings.yaml.
# Grund: Addon und HA-Integration laufen auf separaten Systemen und kennen
# den Key nicht automatisch. Der User muss den Key erst dort eintragen
# und dann die Pruefung im Dashboard aktivieren.
#
# Key-Quellen (Prioritaet): 1. Env ASSISTANT_API_KEY  2. settings.yaml security.api_key  3. Auto-generiert

_assistant_api_key: str = ""
_api_key_required: bool = False

# Pfade die OHNE API Key zugaenglich bleiben (Health fuer Discovery/Config-Flow)
_API_KEY_EXEMPT_PATHS = frozenset({
    "/api/assistant/health",
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
})


def _init_api_key():
    """Initialisiert den API Key (einmalig beim Import/Start).

    Der Key wird IMMER generiert (fuer Bereitschaft), aber nur enforced
    wenn security.api_key_required = true in settings.yaml gesetzt ist.
    """
    global _assistant_api_key, _api_key_required

    security_cfg = yaml_config.get("security", {})
    _api_key_required = security_cfg.get("api_key_required", False)

    # 1. Env-Variable hat hoechste Prioritaet
    env_key = os.getenv("ASSISTANT_API_KEY", "").strip()
    if env_key:
        _assistant_api_key = env_key
        # Wenn explizit per Env gesetzt, automatisch enforced
        _api_key_required = True
        logger.info("API Key aus Umgebungsvariable geladen (Enforcement aktiv)")
        return

    # 2. Aus settings.yaml lesen
    yaml_key = security_cfg.get("api_key", "")
    if isinstance(yaml_key, str):
        yaml_key = yaml_key.strip()
    else:
        yaml_key = ""
    if yaml_key:
        _assistant_api_key = yaml_key
        logger.info(
            "API Key aus settings.yaml geladen (Enforcement: %s)",
            "aktiv" if _api_key_required else "INAKTIV — im Dashboard aktivieren",
        )
        return

    # 3. Auto-generieren und in settings.yaml speichern (Enforcement bleibt aus)
    _assistant_api_key = secrets.token_urlsafe(32)
    try:
        config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        security = cfg.setdefault("security", {})
        security["api_key"] = _assistant_api_key
        # api_key_required bewusst NICHT auf true setzen
        if "api_key_required" not in security:
            security["api_key_required"] = False
        with open(config_path, "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info("API Key auto-generiert (Enforcement INAKTIV bis im Dashboard aktiviert)")
    except Exception as e:
        logger.warning("API Key konnte nicht in settings.yaml gespeichert werden: %s", e)


_init_api_key()

if not _assistant_api_key:
    logger.error("SICHERHEIT: API Key konnte nicht initialisiert werden! Generiere Fallback-Key.")
    _assistant_api_key = secrets.token_urlsafe(32)


def _check_api_key(request: Request) -> bool:
    """Prueft ob ein gueltiger API Key mitgesendet wurde.

    Akzeptiert Key via:
    - X-API-Key Header
    - api_key Query-Parameter
    """
    key = request.headers.get("x-api-key", "")
    if not key:
        key = request.query_params.get("api_key", "")

    return secrets.compare_digest(key, _assistant_api_key) if key else False


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Prueft API Key fuer alle /api/assistant/* Endpoints (ausser Health).

    Nur aktiv wenn security.api_key_required = true ODER Env ASSISTANT_API_KEY gesetzt.
    """
    path = request.url.path

    # Nur pruefen wenn Enforcement aktiviert ist
    if _api_key_required:
        if path.startswith("/api/assistant/") or path == "/api/assistant":
            if path not in _API_KEY_EXEMPT_PATHS:
                if not _check_api_key(request):
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Ungueltiger oder fehlender API Key"},
                    )

    return await call_next(request)


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

    try:
        result = await asyncio.wait_for(
            brain.process(request.text, request.person, request.room),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.error("brain.process() Timeout nach 60s fuer: %s", request.text[:100])
        result = {
            "response": "Systeme ueberlastet. Nochmal, bitte.",
            "actions": [],
            "model_used": "timeout",
            "context_room": request.room or "unbekannt",
        }
    except Exception as e:
        logger.error("brain.process() Exception fuer '%s': %s", request.text[:100], e, exc_info=True)
        error_type = type(e).__name__
        result = {
            "response": f"Da ist etwas schiefgelaufen ({error_type}: {e}). Versuch es nochmal.",
            "actions": [],
            "model_used": "error",
            "context_room": request.room or "unbekannt",
        }

    # TTS-Daten als TTSInfo-Modell wrappen
    tts_raw = result.pop("tts", None)
    try:
        if tts_raw and isinstance(tts_raw, dict):
            result["tts"] = TTSInfo(**tts_raw)
    except Exception as e:
        logger.warning("TTSInfo-Erstellung fehlgeschlagen: %s", e)

    try:
        return ChatResponse(**result)
    except Exception as e:
        logger.error("ChatResponse-Erstellung fehlgeschlagen: %s", e)
        return ChatResponse(
            response=result.get("response", "Systemfehler."),
            actions=[],
            model_used=result.get("model_used", "error"),
            context_room=result.get("context_room", "unbekannt"),
        )


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
        old_level = brain.autonomy.level
        success = brain.autonomy.set_level(update.autonomy_level)
        if not success:
            raise HTTPException(status_code=400, detail="Level muss 1-5 sein")
        result["autonomy"] = brain.autonomy.get_level_info()
        _audit_log("autonomy_level_changed", {"old": old_level, "new": update.autonomy_level})
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
    try:
        result = await brain.process(
            text=text,
            person=person or None,
            room=None,
            files=[file_info],
        )
    except Exception as e:
        logger.error("brain.process() Exception bei Upload '%s': %s", file_info.get("name", "?"), e, exc_info=True)
        result = {
            "response": "Datei empfangen, aber bei der Verarbeitung ist ein Fehler aufgetreten.",
            "actions": [],
            "model_used": "error",
        }

    # TTS wrapping
    tts_raw = result.pop("tts", None)
    try:
        if tts_raw and isinstance(tts_raw, dict):
            result["tts"] = TTSInfo(**tts_raw)
    except Exception as e:
        logger.warning("TTSInfo-Erstellung fehlgeschlagen bei Upload: %s", e)

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

    Authentifizierung via api_key Query-Parameter:
    ws://host:port/api/assistant/ws?api_key=DEIN_KEY

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
    # API Key Authentifizierung fuer WebSocket (nur wenn Enforcement aktiv)
    if _api_key_required:
        ws_key = websocket.query_params.get("api_key", "")
        if not ws_key or not secrets.compare_digest(ws_key, _assistant_api_key):
            await websocket.close(code=4003, reason="Ungueltiger API Key")
            return

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
                    use_stream = message.get("data", {}).get("stream", False)
                    if text:
                        # Phase 9: Voice-Metadaten verarbeiten
                        if voice_meta:
                            brain.mood.analyze_voice_metadata(voice_meta)

                        if use_stream:
                            # Streaming: Token-fuer-Token an Client senden
                            await emit_stream_start()
                            result = await brain.process(
                                text, person,
                                stream_callback=emit_stream_token,
                            )
                            tts_data = result.get("tts")
                            await emit_stream_end(result["response"], tts_data=tts_data)
                        else:
                            # brain.process() sendet intern via _speak_and_emit
                            result = await brain.process(text, person)

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


def _hash_value(value: str, salt: str | None = None) -> str:
    """Hasht einen Wert mit PBKDF2-HMAC-SHA256 + Salt.

    Returns 'salt:hash' format. If salt is None, a random salt is generated.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), iterations=100_000)
    return f"{salt}:{h.hex()}"


def _verify_hash(value: str, stored: str) -> bool:
    """Prueft ob value zum gespeicherten Hash passt.

    Unterstuetzt sowohl neues 'salt:hash'-Format als auch altes Plain-SHA-256.
    """
    if ":" in stored:
        salt, _ = stored.split(":", 1)
        return secrets.compare_digest(_hash_value(value, salt), stored)
    # Legacy: Plain SHA-256 ohne Salt
    return secrets.compare_digest(hashlib.sha256(value.encode()).hexdigest(), stored)


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
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
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
    _audit_log("initial_setup", {"setup_complete": True})

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

    # Vergleich: Env-PIN (Klartext, timing-safe) oder gehashter PIN aus YAML
    env_pin = os.environ.get("JARVIS_UI_PIN")
    if env_pin:
        valid = secrets.compare_digest(req.pin, env_pin)
    else:
        stored_hash = _get_dashboard_config().get("pin_hash", "")
        valid = (stored_hash and _verify_hash(req.pin, stored_hash))

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
    if not stored_recovery_hash or not _verify_hash(req.recovery_key, stored_recovery_hash):
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


@app.get("/api/ui/api-key")
async def ui_get_api_key(token: str = ""):
    """API Key + Enforcement-Status anzeigen (PIN-geschuetzt)."""
    _check_token(token)
    return {
        "api_key": _assistant_api_key,
        "enforcement": _api_key_required,
        "env_locked": bool(os.getenv("ASSISTANT_API_KEY", "").strip()),
    }


@app.post("/api/ui/api-key/regenerate")
async def ui_regenerate_api_key(token: str = ""):
    """API Key neu generieren (PIN-geschuetzt). Invalidiert alle bestehenden Clients."""
    _check_token(token)
    global _assistant_api_key
    _assistant_api_key = secrets.token_urlsafe(32)

    try:
        with open(SETTINGS_YAML_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        cfg.setdefault("security", {})["api_key"] = _assistant_api_key
        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        _audit_log("api_key_regenerated", {})
        return {"api_key": _assistant_api_key, "message": "Neuer API Key generiert. Addon und HA-Integration muessen aktualisiert werden."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.post("/api/ui/recovery-key/regenerate")
async def ui_regenerate_recovery_key(token: str = ""):
    """Recovery-Key neu generieren (nur fuer eingeloggte User)."""
    _check_token(token)
    new_recovery_key = secrets.token_urlsafe(16)[:12].upper()
    recovery_hash = _hash_value(new_recovery_key)

    try:
        with open(SETTINGS_YAML_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        cfg.setdefault("dashboard", {})["recovery_key_hash"] = recovery_hash
        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        _audit_log("recovery_key_regenerated", {})
        return {"recovery_key": new_recovery_key, "message": "Neuer Recovery-Key generiert. Bitte sicher aufbewahren!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


class ApiKeyEnforcementRequest(BaseModel):
    enabled: bool


@app.post("/api/ui/api-key/enforcement")
async def ui_set_api_key_enforcement(req: ApiKeyEnforcementRequest, token: str = ""):
    """API Key Enforcement ein-/ausschalten (PIN-geschuetzt).

    Aktiviert oder deaktiviert die API Key Pruefung fuer /api/assistant/* Endpoints.
    WICHTIG: Erst aktivieren NACHDEM der Key in Addon + HA-Integration eingetragen wurde!
    """
    _check_token(token)

    # Env-Variable erzwingt Enforcement — Dashboard darf nicht deaktivieren
    if not req.enabled and os.getenv("ASSISTANT_API_KEY", "").strip():
        raise HTTPException(
            status_code=400,
            detail="API Key Enforcement kann nicht deaktiviert werden wenn ASSISTANT_API_KEY als Umgebungsvariable gesetzt ist.",
        )

    global _api_key_required
    _api_key_required = req.enabled

    try:
        with open(SETTINGS_YAML_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        cfg.setdefault("security", {})["api_key_required"] = req.enabled
        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        _audit_log("api_key_enforcement_changed", {"enabled": req.enabled})
        status = "aktiviert" if req.enabled else "deaktiviert"
        logger.info("API Key Enforcement %s", status)
        return {"enforcement": _api_key_required, "message": f"API Key Pruefung {status}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


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


# Sicherheitskritische Keys die aus Bulk-Settings-Updates herausgefiltert werden.
# Diese duerfen NUR ueber ihre dedizierten Endpoints geaendert werden.
# "dashboard" → PIN-Hash, Recovery-Key duerfen nie per Bulk ueberschrieben werden
# "self_optimization.immutable_keys" → Schutz vor Manipulation der Immutable-Liste
_SETTINGS_STRIP_KEYS = frozenset({"dashboard"})
_SETTINGS_STRIP_SUBKEYS = {
    "security": frozenset({"api_key", "api_key_required"}),  # Nur via dedizierte Endpoints
    "self_optimization": frozenset({"immutable_keys"}),       # Darf nicht per UI geaendert werden
}


def _strip_protected_settings(data: dict) -> tuple[dict, list[str]]:
    """Entfernt sicherheitskritische Keys aus einem Settings-Dict.

    Returns:
        (bereinigtes Dict, Liste der entfernten Keys)
    """
    stripped = []
    cleaned = {}
    for key, value in data.items():
        if key in _SETTINGS_STRIP_KEYS:
            stripped.append(key)
            continue
        if key in _SETTINGS_STRIP_SUBKEYS and isinstance(value, dict):
            protected_subkeys = _SETTINGS_STRIP_SUBKEYS[key]
            filtered_value = {k: v for k, v in value.items() if k not in protected_subkeys}
            removed = [f"{key}.{k}" for k in value if k in protected_subkeys]
            stripped.extend(removed)
            if filtered_value:
                cleaned[key] = filtered_value
        else:
            cleaned[key] = value
    return cleaned, stripped


@app.put("/api/ui/settings")
async def ui_update_settings(req: SettingsUpdateFull, token: str = ""):
    """Settings in settings.yaml aktualisieren (Merge, nicht ersetzen).

    SICHERHEIT: Sicherheitskritische Sub-Keys (dashboard.*, security.api_key,
    self_optimization.immutable_keys) werden automatisch herausgefiltert.
    """
    _check_token(token)

    try:
        # SICHERHEIT: Geschuetzte Keys herausfiltern
        safe_settings, stripped = _strip_protected_settings(
            req.settings if isinstance(req.settings, dict) else {}
        )
        if stripped:
            logger.warning("Settings-Update: Geschuetzte Keys herausgefiltert: %s", stripped)

        if not safe_settings:
            return {"success": True, "message": "Keine aenderbaren Settings vorhanden"}

        # Aktuelle Config laden
        with open(SETTINGS_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}

        # Deep Merge (nur bereinigte Settings)
        _deep_merge(config, safe_settings)

        # Zurueckschreiben
        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # yaml_config im Speicher aktualisieren
        import assistant.config as cfg
        cfg.yaml_config = load_yaml_config()

        # Household → persons/trust_levels synchronisieren
        cfg.apply_household_to_config()

        # ModelRouter neu laden (Enabled-Status, Keywords)
        if hasattr(brain, "model_router") and brain.model_router:
            brain.model_router.reload_config()

        # DeviceHealth: monitored_entities aktualisieren
        if hasattr(brain, "device_health"):
            dh_cfg = cfg.yaml_config.get("device_health", {})
            brain.device_health.monitored_entities = dh_cfg.get("monitored_entities", [])

        # Audit-Log (mit Details ueber geschuetzte Keys)
        changed_keys = list(safe_settings.keys())
        audit_details = {"changed_sections": changed_keys}
        if stripped:
            audit_details["stripped_protected"] = stripped
        _audit_log("settings_update", audit_details)

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


@app.get("/api/ui/entities/mindhome")
async def ui_get_mindhome_entities(token: str = ""):
    """Entities aus MindHome Device-DB mit Raum- und Domain-Zuordnung."""
    _check_token(token)
    try:
        devices = await brain.ha.search_devices() or []
        # Nach Raum gruppieren
        by_room: dict[str, list] = {}
        for d in devices:
            room = d.get("room", "Unbekannt") or "Unbekannt"
            by_room.setdefault(room, []).append({
                "entity_id": d.get("ha_entity_id", ""),
                "name": d.get("name", d.get("ha_entity_id", "")),
                "room": room,
                "domain": d.get("ha_entity_id", "").split(".")[0],
            })
        # Aktuelle Whitelist mitgeben
        monitored = brain.device_health.monitored_entities
        return {
            "rooms": by_room,
            "monitored_entities": monitored,
            "total": sum(len(v) for v in by_room.values()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/covers")
async def ui_get_covers(token: str = ""):
    """Alle Cover-Entities mit Typ-Konfiguration (fuer Rollladen/Garagentor-Verwaltung)."""
    _check_token(token)
    try:
        states = await brain.ha.get_states()
        configs = await brain.ha.mindhome_get("/api/covers/configs") or {}
        covers = []
        for s in (states or []):
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
                continue
            attrs = s.get("attributes", {})
            conf = configs.get(eid, {}) if isinstance(configs, dict) else {}
            covers.append({
                "entity_id": eid,
                "name": attrs.get("friendly_name", eid),
                "state": s.get("state", "unknown"),
                "device_class": attrs.get("device_class", ""),
                "cover_type": conf.get("cover_type", attrs.get("device_class", "shutter") or "shutter"),
                "enabled": conf.get("enabled", True),
            })
        covers.sort(key=lambda c: c["name"])
        return {"covers": covers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.put("/api/ui/covers/{entity_id:path}/type")
async def ui_set_cover_type(entity_id: str, request: Request, token: str = ""):
    """Cover-Typ und enabled-Status setzen."""
    _check_token(token)
    try:
        data = await request.json()
        payload = {}
        if "cover_type" in data:
            payload["cover_type"] = data["cover_type"]
        if "enabled" in data:
            payload["enabled"] = data["enabled"]
        if not payload:
            raise HTTPException(status_code=400, detail="Keine Daten")
        result = await brain.ha.mindhome_put(
            f"/api/covers/{entity_id}/config",
            payload,
        )
        if result is None:
            logger.warning("Cover-Config save failed for %s (mindhome_put returned None)", entity_id)
            raise HTTPException(status_code=502, detail="Add-on nicht erreichbar oder Speichern fehlgeschlagen")
        return {"success": True, **payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/action-log")
async def ui_get_action_log(token: str = "", limit: int = 30):
    """Jarvis Action-Log vom MindHome Add-on holen."""
    _check_token(token)
    try:
        result = await brain.ha.mindhome_get(
            f"/api/action-log?type=jarvis_action&limit={limit}&period=7d"
        )
        return result or {"items": [], "total": 0}
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


class NotificationChannelUpdate(BaseModel):
    channels: dict


@app.put("/api/ui/notification-channels")
async def ui_update_notification_channels(
    req: NotificationChannelUpdate, token: str = "",
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

        cfg.setdefault("notifications", {})["channels"] = req.channels
        with open(config_path, "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False)

        _audit_log("notification_channels_update", {"channels": list(req.channels.keys()) if isinstance(req.channels, dict) else []})
        return {"success": True, "channels": req.channels}
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
    _audit_log("knowledge_base_ingest", {"new_chunks": count, "total_chunks": stats.get("total_chunks", 0)})
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


@app.get("/api/ui/errors")
async def ui_get_errors(token: str = "", limit: int = 100, level: str = ""):
    """Fehlerspeicher: Letzte WARNING/ERROR Log-Eintraege."""
    _check_token(token)
    entries = list(_error_buffer)
    if level:
        entries = [e for e in entries if e["level"] == level.upper()]
    entries.reverse()  # Neueste zuerst
    return {"errors": entries[:min(limit, 200)], "total": len(entries)}


@app.delete("/api/ui/errors")
async def ui_clear_errors(token: str = ""):
    """Fehlerspeicher leeren."""
    _check_token(token)
    _error_buffer.clear()
    return {"status": "ok"}


# Statische UI-Dateien ausliefern
_ui_static_dir = Path(__file__).parent.parent / "static" / "ui"
_ui_static_dir.mkdir(parents=True, exist_ok=True)
_chat_static_dir = Path(__file__).parent.parent / "static" / "chat"
_chat_static_dir.mkdir(parents=True, exist_ok=True)

_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


@app.get("/ui/{path:path}")
async def ui_serve(path: str = ""):
    """Jarvis Dashboard — Single-Page App."""
    index_path = _ui_static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html", headers=_NO_CACHE_HEADERS)
    return HTMLResponse("<h1>Jarvis Dashboard — index.html nicht gefunden</h1>", status_code=404)


@app.get("/ui")
async def ui_redirect():
    """Redirect /ui zu /ui/."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/")


@app.get("/chat/{path:path}")
async def chat_serve(path: str = ""):
    """Jarvis Chat — Standalone Chat-Seite."""
    index_path = _chat_static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html", headers=_NO_CACHE_HEADERS)
    return HTMLResponse("<h1>Jarvis Chat — index.html nicht gefunden</h1>", status_code=404)


@app.get("/chat")
async def chat_redirect():
    """Redirect /chat zu /chat/."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/chat/")


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
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # Personality-Engine neu laden
        if hasattr(brain, "personality") and brain.personality:
            brain.personality._easter_eggs = brain.personality._load_easter_eggs()

        _audit_log("easter_eggs_update", {"count": len(req.easter_eggs)})
        return {"success": True, "message": f"{len(req.easter_eggs)} Easter Eggs gespeichert"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


# ------------------------------------------------------------------
# Phase 13.4: Config Snapshots & Rollback API
# ------------------------------------------------------------------

@app.get("/api/ui/snapshots")
async def ui_list_snapshots(token: str = "", config_file: str = ""):
    """Listet Config-Snapshots (optional gefiltert nach config_file)."""
    _check_token(token)
    try:
        if config_file:
            snapshots = await brain.config_versioning.list_snapshots(config_file)
        else:
            snapshots = await brain.config_versioning.list_all_snapshots()
        return {"snapshots": snapshots, "total": len(snapshots)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


class RollbackRequest(BaseModel):
    snapshot_id: str


@app.post("/api/ui/rollback")
async def ui_rollback(req: RollbackRequest, token: str = ""):
    """Stellt eine Config-Datei aus einem Snapshot wieder her.

    SICHERHEIT: Nach Rollback werden kritische Security-Sections aus der
    aktuellen Config beibehalten, falls der Snapshot aeltere/schwaecher
    konfigurierte Versionen enthaelt.
    """
    _check_token(token)
    try:
        # Aktuelle Security-Sections sichern BEVOR Rollback
        try:
            with open(SETTINGS_YAML_PATH) as f:
                pre_rollback = yaml.safe_load(f) or {}
        except Exception:
            pre_rollback = {}

        result = await brain.config_versioning.rollback(req.snapshot_id)
        if result["success"]:
            # Post-Rollback: Kritische Security-Sections wiederherstellen
            _sections_to_preserve = ("dashboard", "security", "trust_levels")
            try:
                with open(SETTINGS_YAML_PATH) as f:
                    restored = yaml.safe_load(f) or {}
                patched = False
                for section in _sections_to_preserve:
                    if section in pre_rollback:
                        restored[section] = pre_rollback[section]
                        patched = True
                if patched:
                    with open(SETTINGS_YAML_PATH, "w") as f:
                        yaml.safe_dump(restored, f, allow_unicode=True,
                                       default_flow_style=False, sort_keys=False)
                    logger.info("Rollback: Security-Sections aus Pre-Rollback beibehalten: %s",
                                _sections_to_preserve)
            except Exception as e:
                logger.error("Rollback Post-Validation fehlgeschlagen: %s", e)

            # yaml_config im Speicher aktualisieren
            import assistant.config as cfg
            cfg.yaml_config = load_yaml_config()
            _audit_log("config_rollback", {
                "snapshot_id": req.snapshot_id,
                "security_sections_preserved": list(_sections_to_preserve),
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/self-optimization/status")
async def ui_self_opt_status(token: str = ""):
    """Status der Selbstoptimierung inkl. offener Vorschlaege."""
    _check_token(token)
    try:
        proposals = await brain.self_optimization.get_pending_proposals()
        return {
            "health": brain.self_optimization.health_status(),
            "proposals": proposals,
            "versioning": brain.config_versioning.health_status(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


class ProposalAction(BaseModel):
    index: int


@app.post("/api/ui/self-optimization/approve")
async def ui_self_opt_approve(req: ProposalAction, token: str = ""):
    """User genehmigt einen Optimierungs-Vorschlag (explizite Zustimmung)."""
    _check_token(token)
    try:
        result = await brain.self_optimization.approve_proposal(req.index)
        if result["success"]:
            # yaml_config im Speicher aktualisieren
            import assistant.config as cfg
            cfg.yaml_config = load_yaml_config()
            _audit_log("self_opt_approve", {"index": req.index, "message": result.get("message", "")})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.post("/api/ui/self-optimization/reject")
async def ui_self_opt_reject(req: ProposalAction, token: str = ""):
    """User lehnt einen Optimierungs-Vorschlag ab."""
    _check_token(token)
    try:
        result = await brain.self_optimization.reject_proposal(req.index)
        if result["success"]:
            _audit_log("self_opt_reject", {"index": req.index})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.post("/api/ui/self-optimization/reject-all")
async def ui_self_opt_reject_all(token: str = ""):
    """User lehnt alle Optimierungs-Vorschlaege ab."""
    _check_token(token)
    try:
        result = await brain.self_optimization.reject_all()
        if result["success"]:
            _audit_log("self_opt_reject_all", {})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.post("/api/ui/self-optimization/run-analysis")
async def ui_self_opt_run_analysis(token: str = ""):
    """Manuelle Analyse-Ausloesung (nur durch User, nie automatisch)."""
    _check_token(token)
    try:
        proposals = await brain.self_optimization.run_analysis()
        return {
            "success": True,
            "proposals": proposals,
            "message": f"{len(proposals)} Vorschlag/Vorschlaege generiert" if proposals else "Keine Vorschlaege — alles optimal",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


def _deep_merge(base: dict, override: dict):
    """Tiefer Merge von override in base (in-place)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ============================================================
# System Management API (Update, Restart, Status)
# ============================================================

import subprocess
import shutil
import aiohttp as _aiohttp

# Pfade: /repo ist das gemountete Git-Repo, /repo/assistant hat docker-compose.yml
_REPO_DIR = Path("/repo") if Path("/repo/.git").exists() else Path(__file__).parent.parent.parent
_MHA_DIR = _REPO_DIR / "assistant"
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
_update_lock = asyncio.Lock()
_update_log: list[str] = []


def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[int, str]:
    """Fuehrt einen Shell-Befehl aus und gibt (returncode, output) zurueck."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return -1, "Timeout"
    except Exception as e:
        return -1, str(e)


async def _ollama_api(path: str, method: str = "GET", json_data: dict | None = None) -> tuple[bool, dict | str]:
    """Ruft die Ollama HTTP API auf (laeuft auf dem Host, nicht im Container)."""
    try:
        timeout = _aiohttp.ClientTimeout(total=600)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            url = f"{_OLLAMA_URL}{path}"
            if method == "GET":
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return True, await resp.json()
                    return False, f"HTTP {resp.status}"
            elif method == "POST":
                async with session.post(url, json=json_data) as resp:
                    # Ollama pull streamt — wir lesen die letzte Zeile
                    text = await resp.text()
                    return resp.status == 200, text
    except Exception as e:
        return False, str(e)


@app.get("/api/ui/system/status")
async def ui_system_status(token: str = ""):
    """Systemstatus: Git, Container, Ollama, Speicher."""
    _check_token(token)

    # Git (via gemountetes /repo Volume)
    _, branch = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(_REPO_DIR))
    _, commit = _run_cmd(["git", "log", "-1", "--format=%h %s"], cwd=str(_REPO_DIR))
    _, git_status = _run_cmd(["git", "status", "--short"], cwd=str(_REPO_DIR))

    # Container Health (via gemounteten Docker-Socket)
    containers = {}
    for name in ["mindhome-assistant", "mha-chromadb", "mha-redis"]:
        rc, out = _run_cmd(["docker", "inspect", "--format", "{{.State.Health.Status}}", name])
        containers[name] = out.strip() if rc == 0 else "unknown"

    # Ollama (via HTTP API auf dem Host)
    ollama_ok, ollama_data = await _ollama_api("/api/tags")
    ollama_models = ""
    if ollama_ok and isinstance(ollama_data, dict):
        models = ollama_data.get("models", [])
        lines = [f"{m.get('name', '?'):30s} {m.get('size', 0) / 1e9:.1f} GB" for m in models]
        ollama_models = "\n".join(["NAME                           SIZE"] + lines)

    # Disk
    disk_info = {}
    disk_path = _REPO_DIR if _REPO_DIR.exists() else Path("/app")
    total, used, free = shutil.disk_usage(str(disk_path))
    disk_info["system"] = {
        "total_gb": round(total / (1024**3), 1),
        "used_gb": round(used / (1024**3), 1),
        "free_gb": round(free / (1024**3), 1),
    }

    return {
        "git": {
            "branch": branch.strip(),
            "commit": commit.strip(),
            "changes": git_status.strip(),
        },
        "containers": containers,
        "ollama": {
            "available": ollama_ok,
            "models": ollama_models,
        },
        "disk": disk_info,
        "version": "1.4.1",
        "update_log": _update_log[-20:],
    }


async def _docker_restart(container: str = "mindhome-assistant", timeout: int = 5):
    """Restart via Docker Engine API (Unix-Socket). Atomar — Daemon fuehrt komplett aus."""
    sock = "/var/run/docker.sock"
    try:
        conn = _aiohttp.UnixConnector(path=sock)
        async with _aiohttp.ClientSession(connector=conn) as session:
            url = f"http://localhost/containers/{container}/restart?t={timeout}"
            async with session.post(url) as resp:
                return resp.status == 204
    except Exception:
        return False


@app.post("/api/ui/system/update")
async def ui_system_update(token: str = ""):
    """System-Update: git pull + Container-Restart (Code ist als Volume gemountet)."""
    _check_token(token)

    if _update_lock.locked():
        raise HTTPException(status_code=409, detail="Update laeuft bereits")

    async with _update_lock:
        _update_log.clear()
        _update_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Update gestartet...")

        # 1. Git Pull (via gemountetes /repo)
        _update_log.append("Git pull...")
        rc, out = _run_cmd(["git", "pull"], cwd=str(_REPO_DIR), timeout=60)
        _update_log.append(out.strip())
        if rc != 0:
            _update_log.append("FEHLER: Git pull fehlgeschlagen")
            return {"success": False, "log": _update_log}

        _update_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Code aktualisiert! Container startet neu...")

        # 2. Restart via Docker Engine API (Code als Volume = sofort aktiv)
        # asyncio.ensure_future damit Response noch rausgeht bevor Restart
        asyncio.ensure_future(_docker_restart())

        return {"success": True, "log": _update_log}


@app.post("/api/ui/system/restart")
async def ui_system_restart(token: str = ""):
    """Container-Restart via Docker Engine API (atomar, kein Crash)."""
    _check_token(token)

    if _update_lock.locked():
        raise HTTPException(status_code=409, detail="Update/Restart laeuft bereits")

    # Restart via Docker Engine API — Daemon fuehrt komplett aus
    asyncio.ensure_future(_docker_restart())

    return {"success": True, "output": "Container wird neugestartet..."}


@app.post("/api/ui/system/update-models")
async def ui_system_update_models(token: str = ""):
    """Aktualisiert alle installierten Ollama-Modelle via HTTP API."""
    _check_token(token)

    if _update_lock.locked():
        raise HTTPException(status_code=409, detail="Update laeuft bereits")

    async with _update_lock:
        results = []

        # Installierte Modelle via Ollama HTTP API
        ok, data = await _ollama_api("/api/tags")
        if not ok or not isinstance(data, dict):
            return {"success": False, "models": [], "error": "Ollama nicht erreichbar"}

        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]

        for model in models:
            ok, out = await _ollama_api("/api/pull", method="POST", json_data={"name": model})
            results.append({
                "model": model,
                "success": ok,
                "output": str(out)[-200:],
            })

        return {
            "success": all(r["success"] for r in results),
            "models": results,
        }


@app.get("/api/ui/system/update-check")
async def ui_system_update_check(token: str = ""):
    """Prueft ob neue Commits auf dem Remote verfuegbar sind."""
    _check_token(token)

    # Aktuellen Branch ermitteln
    _, current_branch = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(_REPO_DIR))
    branch = current_branch.strip() or "main"

    # Fetch
    rc, _ = _run_cmd(["git", "fetch", "origin", branch], cwd=str(_REPO_DIR), timeout=30)
    if rc != 0:
        return {"updates_available": False, "error": "Git fetch fehlgeschlagen"}

    _, local = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(_REPO_DIR))
    _, remote = _run_cmd(["git", "rev-parse", f"origin/{branch}"], cwd=str(_REPO_DIR))

    local = local.strip()
    remote = remote.strip()

    if local == remote:
        return {"updates_available": False, "local": local[:8], "remote": remote[:8]}

    _, log = _run_cmd(
        ["git", "log", "--oneline", f"{local}..{remote}"],
        cwd=str(_REPO_DIR),
    )

    return {
        "updates_available": True,
        "local": local[:8],
        "remote": remote[:8],
        "new_commits": log.strip().split("\n") if log.strip() else [],
    }


@app.get("/")
async def root():
    """Startseite."""
    return {
        "name": "MindHome Assistant",
        "version": "1.4.1",
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
