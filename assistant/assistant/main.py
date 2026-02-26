"""
MindHome Assistant - Hauptanwendung (FastAPI Server)
Startet den MindHome Assistant REST API Server.
"""

import asyncio
import json
import logging
import os
import random

# ChromaDB Telemetrie deaktivieren (posthog capture() Fehler vermeiden)
os.environ["ANONYMIZED_TELEMETRY"] = "False"
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
from .config import settings, yaml_config, load_yaml_config, get_person_title
from .constants import ERROR_BUFFER_MAX_SIZE, RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_REQUESTS
from .cover_config import load_cover_configs, save_cover_configs
from .file_handler import (
    allowed_file, ensure_upload_dir,
    get_file_path, save_upload, MAX_FILE_SIZE,
)
from .request_context import RequestContextMiddleware, setup_structured_logging, get_request_id
from .websocket import ws_manager, emit_speaking, emit_stream_start, emit_stream_token, emit_stream_end

# Structured Logging (mit Request-ID Support)
setup_structured_logging()
logger = logging.getLogger("mindhome-assistant")

# ---- Fehlerspeicher: Ring-Buffer fuer WARNING/ERROR Logs (2000 statt 200) ----
_error_buffer: deque[dict] = deque(maxlen=ERROR_BUFFER_MAX_SIZE)
_REDIS_ERROR_BUFFER_KEY = "mha:error_buffer"
_REDIS_ERROR_BUFFER_TTL = 7 * 86400  # 7 Tage


# F-067: Sensitive Patterns die aus Error-Buffer-Nachrichten entfernt werden
import re as _re
_SENSITIVE_PATTERNS = _re.compile(
    r'(api[_-]?key|token|password|secret|credential|auth)[=:"\s]+\S+',
    _re.IGNORECASE,
)


class _ErrorBufferHandler(logging.Handler):
    """Faengt WARNING+ Log-Eintraege ab und speichert sie im Ring-Buffer.

    F-067: Sensitive Daten (API-Keys, Tokens, Passwoerter) werden
    vor dem Speichern aus der Nachricht entfernt.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # F-067: Sensitive Daten maskieren
            msg = _SENSITIVE_PATTERNS.sub("[REDACTED]", msg)
            _error_buffer.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
            })
        except Exception:
            pass


_err_handler = _ErrorBufferHandler(level=logging.WARNING)
_err_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_err_handler)


async def _restore_error_buffer(redis_client) -> int:
    """Stellt den Fehlerspeicher aus Redis wieder her (nach Neustart)."""
    try:
        raw = await redis_client.get(_REDIS_ERROR_BUFFER_KEY)
        if not raw:
            return 0
        entries = json.loads(raw)
        for entry in entries:
            _error_buffer.append(entry)
        return len(entries)
    except Exception as e:
        logger.debug("Fehlerspeicher-Restore fehlgeschlagen: %s", e)
        return 0


async def _persist_error_buffer(redis_client) -> None:
    """Speichert den Fehlerspeicher in Redis (vor Shutdown)."""
    try:
        entries = list(_error_buffer)
        await redis_client.set(
            _REDIS_ERROR_BUFFER_KEY,
            json.dumps(entries),
            ex=_REDIS_ERROR_BUFFER_TTL,
        )
    except Exception as e:
        logger.debug("Fehlerspeicher-Persist fehlgeschlagen: %s", e)


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

        # Raumtemperatur: Konfigurierte Sensoren (Mittelwert) bevorzugen
        rt_cfg = yaml_config.get("room_temperature", {})
        sensor_ids = rt_cfg.get("sensors", []) or []
        if sensor_ids:
            temps = []
            for s in (states or []):
                if s.get("entity_id") in sensor_ids:
                    try:
                        temps.append(float(s.get("state", "")))
                    except (ValueError, TypeError):
                        pass
            if temps:
                temp = sum(temps) / len(temps)

        for s in (states or []):
            eid = s.get("entity_id", "")
            state_val = s.get("state", "")
            attrs = s.get("attributes", {})

            # Fallback: climate.* Temperatur nur wenn keine Sensoren konfiguriert
            if temp is None and eid.startswith("climate."):
                t = attrs.get("current_temperature")
                if t is not None:
                    try:
                        temp = float(t)
                    except (ValueError, TypeError):
                        pass

            # Offene Fenster/Tueren zaehlen — MindHome-Domain + device_class
            from .function_calling import is_window_or_door
            if state_val == "on" and is_window_or_door(eid, s):
                name = attrs.get("friendly_name", eid)
                open_items.append(name)

        # Boot-Nachricht zusammenbauen
        title = get_person_title()
        default_msgs = [
            f"Alle Systeme online, {title}.",
            f"Systeme hochgefahren, {title}. Alles bereit.",
            f"Online, {title}. Soll ich den Status durchgehen?",
        ]
        messages = cfg.get("messages", default_msgs)
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
        # TTS-Sprachausgabe auf dem Default-Speaker
        if hasattr(brain_instance, "sound_manager"):
            await brain_instance.sound_manager.speak_response(msg)
        logger.info("Boot-Sequenz: %s", msg)

    except Exception as e:
        logger.warning("Boot-Sequenz fehlgeschlagen: %s", e)
        try:
            await emit_speaking(f"Alle Systeme online, {get_person_title()}.")
        except Exception:
            pass


async def _periodic_token_cleanup():
    """Raumt abgelaufene UI-Tokens alle 15 Minuten auf."""
    while True:
        await asyncio.sleep(900)  # 15 Minuten
        try:
            _cleanup_expired_tokens()
        except Exception as e:
            logger.debug("Token-Cleanup Fehler: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup und Shutdown."""
    logger.info("=" * 50)
    logger.info(" MindHome Assistant v1.4.1 startet...")
    logger.info("=" * 50)
    await brain.initialize()

    # Fehlerspeicher aus Redis wiederherstellen (Restart-sicher)
    if brain.memory.redis:
        restored = await _restore_error_buffer(brain.memory.redis)
        if restored:
            logger.info("Fehlerspeicher wiederhergestellt: %d Eintraege", restored)

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
        task = asyncio.create_task(_boot_announcement(brain, health, boot_cfg))
        task.add_done_callback(lambda t: t.exception() and logger.error("Boot-Sequenz Task Fehler: %s", t.exception()))

    # Periodischer Token-Cleanup (alle 15 Min)
    cleanup_task = asyncio.create_task(_periodic_token_cleanup())

    yield

    cleanup_task.cancel()

    # F-065: WebSocket-Clients ueber Shutdown benachrichtigen
    try:
        await ws_manager.broadcast("system", {"event": "shutdown", "message": "System wird heruntergefahren"})
        await asyncio.sleep(0.5)  # Kurz warten damit Clients die Nachricht empfangen
    except Exception as e:
        logger.debug("F-065: WS-Shutdown-Broadcast fehlgeschlagen: %s", e)

    # Fehlerspeicher in Redis sichern (vor Shutdown)
    if brain.memory.redis:
        await _persist_error_buffer(brain.memory.redis)

    await brain.shutdown()
    logger.info("MindHome Assistant heruntergefahren.")


# F-062: OpenAPI-Docs nur wenn explizit konfiguriert (Default: aus in Produktion)
_expose_docs = os.getenv("EXPOSE_OPENAPI_DOCS", "true").lower() in ("1", "true", "yes")
app = FastAPI(
    title="MindHome Assistant",
    description="Lokaler KI-Sprachassistent fuer Home Assistant — OpenAPI Docs unter /docs",
    version="1.4.2",
    lifespan=lifespan,
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
)

# Request-ID Tracing Middleware (muss VOR CORS stehen)
app.add_middleware(RequestContextMiddleware)

# ----- CORS Policy -----
# Nur lokale Zugriffe erlauben (HA Add-on + lokale Clients)
# F-046: allow_credentials nur bei expliziten Origins, nie bei Wildcard
_cors_origins = os.getenv("CORS_ORIGINS", "").strip()
_cors_origin_list = (
    [o.strip() for o in _cors_origins.split(",") if o.strip()]
    if _cors_origins
    else [
        "http://localhost",
        "http://localhost:8123",
        "http://homeassistant.local:8123",
        f"http://localhost:{settings.assistant_port}",
    ]
)
_cors_has_wildcard = "*" in _cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origin_list,
    # F-046: credentials nur erlauben wenn keine Wildcard-Origin gesetzt ist
    allow_credentials=not _cors_has_wildcard,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "Accept"],
)

# ----- Rate-Limiting (in-memory, pro IP) -----
import time as _time
import asyncio as _asyncio
from collections import defaultdict as _defaultdict

_rate_limits: dict[str, list[float]] = _defaultdict(list)
_rate_lock = _asyncio.Lock()
_RATE_WINDOW = RATE_LIMIT_WINDOW
_RATE_MAX_REQUESTS = RATE_LIMIT_MAX_REQUESTS


@app.middleware("http")
async def auth_header_middleware(request: Request, call_next):
    """Extract Bearer token from Authorization header and add as query param."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and "token=" not in str(request.url):
        token = auth[7:]
        # URL-encode token to prevent parameter injection (e.g. token containing '&admin=true')
        from urllib.parse import quote
        safe_token = quote(token, safe="")
        scope = request.scope
        qs = scope.get("query_string", b"").decode()
        sep = "&" if qs else ""
        scope["query_string"] = f"{qs}{sep}token={safe_token}".encode()
    return await call_next(request)


# ----- API Key Authentication fuer /api/assistant/* Endpoints -----
# Schuetzt alle Assistant-API-Endpoints gegen unautorisierte Netzwerkzugriffe.
#
# WICHTIG: Key wird beim ersten Start auto-generiert.
# Enforcement ist per Default AKTIV (sicher). User kann es mit
# security.api_key_required: false in settings.yaml deaktivieren,
# falls Addon den Key noch nicht kennt.
#
# Key-Quellen (Prioritaet): 1. Env ASSISTANT_API_KEY  2. settings.yaml security.api_key  3. Auto-generiert

_assistant_api_key: str = ""
_api_key_required: bool = False

# Pfade die OHNE API Key zugaenglich bleiben (Health fuer Discovery/Config-Flow)
_API_KEY_EXEMPT_PATHS = frozenset({
    "/api/assistant/health",
    "/api/assistant/ws",  # WebSocket hat eigene Auth-Pruefung im Endpoint
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
    # Default: ON (sicher), User kann es explizit mit api_key_required: false deaktivieren
    _api_key_required = security_cfg.get("api_key_required", True)

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

    # 3. Auto-generieren und in settings.yaml speichern (Enforcement aktiv per Default)
    _assistant_api_key = secrets.token_urlsafe(32)
    try:
        config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        security = cfg.setdefault("security", {})
        security["api_key"] = _assistant_api_key
        if "api_key_required" not in security:
            security["api_key_required"] = True
        with open(config_path, "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info("API Key auto-generiert und in settings.yaml gespeichert (Enforcement AKTIV)")
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


_rate_limit_last_cleanup = 0.0
_RATE_CLEANUP_INTERVAL = 300  # Alle 5 Minuten globaler Cleanup
_RATE_MAX_IPS = 10000  # F-011: Maximale Anzahl getrackte IPs


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Einfaches Rate-Limiting pro Client-IP (thread-safe via Lock)."""
    global _rate_limit_last_cleanup
    client_ip = request.client.host if request.client else "unknown"

    async with _rate_lock:
        now = _time.time()

        # F-011: Periodischer Cleanup aller abgelaufenen IPs (alle 5 Min)
        if now - _rate_limit_last_cleanup > _RATE_CLEANUP_INTERVAL:
            expired_ips = [
                ip for ip, timestamps in _rate_limits.items()
                if all(now - t >= _RATE_WINDOW for t in timestamps)
            ]
            for ip in expired_ips:
                del _rate_limits[ip]
            if expired_ips:
                logger.debug("Rate-Limit Cleanup: %d IPs entfernt", len(expired_ips))
            _rate_limit_last_cleanup = now

        # F-011: Schutz gegen unbegrenztes Wachstum bei IP-Scan/DDoS
        if client_ip not in _rate_limits and len(_rate_limits) >= _RATE_MAX_IPS:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Zu viele Anfragen. Bitte warten."},
            )

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
    # Phase 9: Device-ID fuer Speaker Recognition (Satellite → Person Mapping)
    device_id: Optional[str] = None


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
            brain.process(request.text, request.person, request.room,
                          voice_metadata=request.voice_metadata,
                          device_id=request.device_id),
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

    # Aktionen ans Addon melden fuer Aktivitaeten-Log
    actions = result.get("actions", [])
    if actions:
        task = asyncio.ensure_future(brain.ha.log_actions(
            actions, user_text=request.text,
            response_text=result.get("response", ""),
        ))
        task.add_done_callback(
            lambda t: logger.warning("log_actions fehlgeschlagen: %s", t.exception())
            if t.exception() else None
        )

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
        except Exception as e:
            logger.debug("ChromaDB count() fehlgeschlagen: %s", e)
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


class EnrollRequest(BaseModel):
    person_id: str
    name: str
    audio_features: Optional[dict] = None
    device_id: Optional[str] = None


@app.post("/api/assistant/speaker/enroll")
async def enroll_speaker(req: EnrollRequest):
    """Phase 9: Neues Stimm-Profil anlegen oder aktualisieren."""
    if not brain.speaker_recognition.enabled:
        raise HTTPException(status_code=400, detail="Speaker Recognition ist deaktiviert")
    success = await brain.speaker_recognition.enroll(
        req.person_id, req.name,
        audio_features=req.audio_features,
        device_id=req.device_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Enrollment fehlgeschlagen (max Profile erreicht?)")
    return {"enrolled": True, "person_id": req.person_id, "name": req.name}


@app.delete("/api/assistant/speaker/profiles/{person_id}")
async def delete_speaker_profile(person_id: str):
    """Phase 9: Stimm-Profil loeschen."""
    success = await brain.speaker_recognition.remove_profile(person_id)
    if not success:
        raise HTTPException(status_code=404, detail="Profil nicht gefunden")
    return {"deleted": person_id}


@app.get("/api/assistant/speaker/history")
async def get_speaker_history(limit: int = 20):
    """Phase 9: Identifikations-Historie (fuer Debugging/Analyse)."""
    history = await brain.speaker_recognition.get_identification_history(limit=limit)
    return {"history": history, "count": len(history)}


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
    # Auth: WebSocket ist via _API_KEY_EXEMPT_PATHS von der Middleware ausgenommen,
    # da die Chat-UI (/chat/) keinen API Key mitschickt.
    # Optional: Client kann api_key als Query-Parameter senden (z.B. externe Clients).
    ws_key = websocket.query_params.get("api_key", "")
    if _api_key_required and ws_key:
        # Wenn ein Key mitgeschickt wird, muss er stimmen
        if not secrets.compare_digest(ws_key, _assistant_api_key):
            await websocket.close(code=4003, reason="Ungueltiger API Key")
            return

    await ws_manager.connect(websocket)

    # Ping/Pong Keep-Alive: Alle 25 Sek einen Ping senden
    async def _ws_keepalive():
        try:
            while True:
                await asyncio.sleep(25)
                try:
                    await websocket.send_json({"event": "ping", "data": {}})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    keepalive_task = asyncio.create_task(_ws_keepalive())

    # F-063: WebSocket Rate-Limiting (max 30 Nachrichten pro 10 Sekunden)
    _ws_msg_times: list[float] = []
    _WS_RATE_LIMIT = 30
    _WS_RATE_WINDOW = 10.0
    try:
        while True:
            data = await websocket.receive_text()

            # F-063: Rate-Limit pruefen
            import time as _t
            now = _t.time()
            _ws_msg_times = [t for t in _ws_msg_times if now - t < _WS_RATE_WINDOW]
            _ws_msg_times.append(now)
            if len(_ws_msg_times) > _WS_RATE_LIMIT:
                logger.warning("F-063: WebSocket Rate-Limit ueberschritten")
                await ws_manager.send_personal(
                    websocket, "error", {"message": "Rate limit exceeded"}
                )
                continue

            try:
                message = json.loads(data)
                event = message.get("event", "")

                if event == "pong":
                    continue  # Keep-alive Antwort — ignorieren

                if event == "assistant.text":
                    text = message.get("data", {}).get("text", "")
                    person = message.get("data", {}).get("person")
                    room = message.get("data", {}).get("room")
                    voice_meta = message.get("data", {}).get("voice_metadata")
                    ws_device_id = message.get("data", {}).get("device_id")
                    use_stream = message.get("data", {}).get("stream", False)
                    if text:
                        # Phase 9: Voice-Metadaten verarbeiten
                        if voice_meta:
                            brain.mood.analyze_voice_metadata(voice_meta)

                        if use_stream:
                          try:
                            # Streaming: Token-fuer-Token an Client senden
                            # Reasoning-Guard: Erste Tokens buffern um Chain-of-Thought
                            # zu erkennen bevor sie an den Client gehen.
                            stream_tokens_sent = []
                            _stream_buffer = []
                            _stream_suppressed = False
                            _BUFFER_THRESHOLD = 12  # Tokens buffern bevor Streaming startet
                            _REASONING_STARTERS = [
                                "okay, the user", "ok, the user", "the user",
                                "let me ", "i need to", "i should ", "i'll ",
                                "first, i", "hmm,", "so, the user", "now, i",
                                "alright,", "so the user", "wait,",
                                "okay, so", "right,", "let's ",
                            ]

                            async def _guarded_stream_token(token: str):
                                """Buffert initiale Tokens um Reasoning zu erkennen."""
                                nonlocal _stream_suppressed
                                if _stream_suppressed:
                                    return  # Reasoning erkannt — nichts senden

                                _stream_buffer.append(token)
                                buf_text = "".join(_stream_buffer).lstrip()

                                # Noch im Buffer-Modus: pruefen ob Reasoning
                                if len(_stream_buffer) <= _BUFFER_THRESHOLD:
                                    buf_lower = buf_text.lower()
                                    for starter in _REASONING_STARTERS:
                                        if buf_lower.startswith(starter):
                                            _stream_suppressed = True
                                            logger.info(
                                                "Stream-Reasoning erkannt ('%s...'), "
                                                "Streaming unterdrueckt",
                                                buf_text[:60],
                                            )
                                            return
                                    return  # Noch im Buffer, warten

                                # Buffer-Phase vorbei, kein Reasoning → alles senden
                                if not stream_tokens_sent:
                                    await emit_stream_start()
                                    # Gebufferte Tokens nachholen
                                    for bt in _stream_buffer[:-1]:
                                        stream_tokens_sent.append(bt)
                                        await emit_stream_token(bt)
                                stream_tokens_sent.append(token)
                                await emit_stream_token(token)

                            result = await brain.process(
                                text, person, room=room,
                                stream_callback=_guarded_stream_token,
                                voice_metadata=voice_meta,
                                device_id=ws_device_id,
                            )
                            tts_data = result.get("tts")
                            if stream_tokens_sent:
                                # Es wurden Tokens gestreamt → stream_end senden
                                await emit_stream_end(result["response"], tts_data=tts_data)
                            elif not result.get("_emitted"):
                                # Keine Tokens gestreamt (z.B. Tool-Query mit Humanizer)
                                # → normale Antwort senden statt leerer Stream-Blase
                                # _emitted=True: Shortcut-Pfade in brain.py haben
                                # bereits via _speak_and_emit gesendet
                                await emit_speaking(result["response"], tts_data=tts_data)
                          except Exception as e:
                            logger.error("Streaming-Fehler: %s", e, exc_info=True)
                            # Sicherstellen dass der Client nicht haengen bleibt
                            if stream_tokens_sent:
                                await emit_stream_end(
                                    "Da ist etwas schiefgelaufen. Versuch es nochmal.")
                            else:
                                await emit_speaking(
                                    "Da ist etwas schiefgelaufen. Versuch es nochmal.")
                        else:
                            # brain.process() sendet intern via _speak_and_emit
                            result = await brain.process(text, person, room=room,
                                                         voice_metadata=voice_meta,
                                                         device_id=ws_device_id)

                        # Aktionen ans Addon melden fuer Aktivitaeten-Log
                        actions = result.get("actions", [])
                        if actions:
                            _ws_task = asyncio.ensure_future(brain.ha.log_actions(
                                actions, user_text=text,
                                response_text=result.get("response", ""),
                            ))
                            _ws_task.add_done_callback(
                                lambda t: logger.warning("log_actions fehlgeschlagen: %s", t.exception())
                                if t.exception() else None
                            )

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
        pass
    finally:
        keepalive_task.cancel()
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
_token_lock = asyncio.Lock()


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
    h = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), iterations=600_000)
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
    legacy_migration = False
    if env_pin:
        valid = secrets.compare_digest(req.pin, env_pin)
    else:
        stored_hash = _get_dashboard_config().get("pin_hash", "")
        valid = (stored_hash and _verify_hash(req.pin, stored_hash))
        # Legacy-Migration: SHA-256 ohne Salt → PBKDF2 mit Salt
        if valid and stored_hash and ":" not in stored_hash:
            legacy_migration = True

    if not valid:
        _audit_log("login", {"success": False})
        raise HTTPException(status_code=401, detail="Falscher PIN")

    # Legacy-PIN-Hash automatisch auf PBKDF2 upgraden
    if legacy_migration:
        try:
            new_hash = _hash_value(req.pin)
            dc = _get_dashboard_config()
            recovery_hash = dc.get("recovery_key_hash", "")
            _save_dashboard_config(new_hash, recovery_hash, setup_complete=True)
            logger.info("Dashboard: Legacy PIN-Hash auf PBKDF2 migriert")
            _audit_log("pin_hash_migrated", {"from": "sha256", "to": "pbkdf2"})
        except Exception as e:
            logger.warning("PIN-Hash Migration fehlgeschlagen: %s", e)

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


_AUDIT_LOG_MAX_SIZE = 10 * 1024 * 1024  # F-066: 10 MB Max


def _audit_log(action: str, details: dict = None):
    """Schreibt einen Eintrag ins Audit-Log (JSON-Lines).

    F-066: Rotation bei > 10 MB — altes Log wird zu .bak umbenannt.
    """
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # F-066: Rotation
        if _AUDIT_LOG_PATH.exists() and _AUDIT_LOG_PATH.stat().st_size > _AUDIT_LOG_MAX_SIZE:
            bak = _AUDIT_LOG_PATH.with_suffix(".jsonl.bak")
            if bak.exists():
                bak.unlink()
            _AUDIT_LOG_PATH.rename(bak)
            logger.info("Audit-Log rotiert (> %d MB)", _AUDIT_LOG_MAX_SIZE // (1024 * 1024))

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
    """Entfernt abgelaufene Tokens (thread-safe: nur aus async-Kontext aufrufen)."""
    now = datetime.now(timezone.utc).timestamp()
    expired = [t for t, ts in _active_tokens.items() if now - ts > _TOKEN_EXPIRY_SECONDS]
    for t in expired:
        _active_tokens.pop(t, None)


def _check_token(token: str):
    """Prueft ob ein UI-Token gueltig ist und nicht abgelaufen."""
    if token not in _active_tokens:
        raise HTTPException(status_code=401, detail="Nicht autorisiert")
    # Ablaufzeit pruefen
    created = _active_tokens[token]
    now = datetime.now(timezone.utc).timestamp()
    if now - created > _TOKEN_EXPIRY_SECONDS:
        _active_tokens.pop(token, None)
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


# F-041: Settings-Validierung
def _validate_settings_values(settings: dict) -> list[str]:
    """Validiert Settings-Werte auf sinnvolle Bereiche."""
    errors = []
    RANGE_RULES = {
        ("autonomy", "level"): (1, 5),
        ("personality", "sarcasm_level"): (1, 5),
        ("personality", "opinion_intensity"): (0, 5),
        ("personality", "self_irony_max_per_day"): (0, 20),
        ("personality", "formality_start"): (0, 100),
        ("personality", "formality_min"): (0, 100),
        ("personality", "formality_decay_per_day"): (0, 5),
        ("threat_assessment", "night_start_hour"): (0, 23),
        ("threat_assessment", "night_end_hour"): (0, 23),
        ("health_monitor", "co2_warn"): (400, 5000),
        ("health_monitor", "co2_critical"): (400, 10000),
        ("health_monitor", "temp_low"): (5, 22),
        ("health_monitor", "temp_high"): (20, 40),
        ("health_monitor", "humidity_low"): (10, 50),
        ("health_monitor", "humidity_high"): (40, 95),
        ("health_monitor", "check_interval_minutes"): (5, 60),
        ("health_monitor", "alert_cooldown_minutes"): (5, 1440),
        ("proactive", "batch_interval"): (5, 300),
        ("interrupt_queue", "pause_ms"): (100, 1000),
        ("situation_model", "min_pause_minutes"): (5, 120),
        ("situation_model", "max_changes"): (1, 10),
        ("situation_model", "temp_threshold"): (1, 5),
        ("insights", "check_interval_minutes"): (10, 120),
        ("insights", "cooldown_hours"): (1, 24),
        ("insights", "thresholds", "frost_temp_c"): (-10, 10),
        ("insights", "thresholds", "energy_anomaly_percent"): (10, 100),
        ("insights", "thresholds", "away_device_minutes"): (30, 480),
        ("insights", "thresholds", "temp_drop_degrees_per_2h"): (1, 10),
        ("speech", "stt_beam_size"): (1, 10),
        ("music_dj", "default_volume"): (0, 100),
        ("music_dj", "cooldown_minutes"): (5, 120),
        ("music_dj", "proactive_interval_minutes"): (10, 120),
        ("visitor_management", "ring_cooldown_seconds"): (5, 120),
        ("visitor_management", "history_max"): (10, 500),
    }
    # Erlaubte Werte fuer Strings (Whitelist)
    ENUM_RULES = {
        ("speech", "stt_model"): ["tiny", "base", "small", "medium", "large-v3-turbo"],
        ("speech", "stt_compute"): ["int8", "float16", "float32"],
        ("speech", "stt_device"): ["cpu", "cuda"],
    }
    for path_keys, (min_val, max_val) in RANGE_RULES.items():
        # path_keys kann 2-Tupel ("section", "key") oder 3-Tupel ("section", "sub", "key") sein
        obj = settings
        for pk in path_keys[:-1]:
            if isinstance(obj, dict) and pk in obj:
                obj = obj[pk]
            else:
                obj = None
                break
        if obj is None or not isinstance(obj, dict):
            continue
        val = obj.get(path_keys[-1])
        path_str = ".".join(path_keys)
        if val is not None:
            try:
                num = float(val)
                if num < min_val or num > max_val:
                    errors.append(f"{path_str}={val} (erlaubt: {min_val}-{max_val})")
            except (ValueError, TypeError):
                errors.append(f"{path_str}={val} (kein gueltiger Wert)")
    for (section, key), allowed in ENUM_RULES.items():
        if section in settings and isinstance(settings[section], dict):
            val = settings[section].get(key)
            if val is not None and val not in allowed:
                errors.append(f"{section}.{key}={val} (erlaubt: {', '.join(allowed)})")
    return errors


# F-038: Settings-Propagation — Module nach UI-Update benachrichtigen
def _get_reloaded_modules(changed_settings: dict) -> list[str]:
    """Ermittelt welche Module von den geaenderten Settings betroffen sind."""
    reloaded = []
    keys = set(changed_settings.keys())

    # Mapping: Settings-Key → (brain-Attribut, Config-Key, zu setzende Attribute)
    MODULE_CONFIG_MAP = {
        "personality": "personality",
        "proactive": "proactive",
        "routines": "proactive",
        "autonomy": "autonomy",
        "threat_assessment": "threat_assessment",
        "energy": "energy_optimizer",
        "wellness": "wellness_advisor",
        "health_monitor": "health_monitor",
        "insights": "insight_engine",
        "tts": "tts_enhancer",
        "web_search": "web_search",
        "ambient_audio": "ambient_audio",
        "feedback": "feedback",
        "situation_model": "situation_model",
        "interrupt_queue": "interrupt_queue",
    }

    for config_key, attr_name in MODULE_CONFIG_MAP.items():
        if config_key in keys:
            reloaded.append(attr_name)

    return reloaded


def _reload_all_modules(yaml_cfg: dict, changed_settings: dict):
    """F-038: Benachrichtigt alle Module deren Config sich geaendert hat.

    Module die reload_config() implementieren werden direkt aufgerufen.
    Fuer alle anderen wird die neue Config in yaml_config gespeichert —
    Module die bei jedem Zugriff yaml_config lesen profitieren automatisch.
    Module die im __init__ cachen werden hier explizit aktualisiert.
    """
    try:
        # Personality: Sarkasmus, Humor, Style direkt aktualisieren
        if "personality" in changed_settings and hasattr(brain, "personality"):
            p_cfg = yaml_cfg.get("personality", {})
            pe = brain.personality
            pe.sarcasm_level = int(p_cfg.get("sarcasm_level", pe.sarcasm_level))
            pe.opinion_intensity = int(p_cfg.get("opinion_intensity", pe.opinion_intensity))
            pe.self_irony_enabled = bool(p_cfg.get("self_irony_enabled", pe.self_irony_enabled))
            pe.self_irony_max_per_day = int(p_cfg.get("self_irony_max_per_day", pe.self_irony_max_per_day))
            pe.character_evolution = bool(p_cfg.get("character_evolution", pe.character_evolution))
            pe.formality_start = int(p_cfg.get("formality_start", pe.formality_start))
            pe.formality_min = int(p_cfg.get("formality_min", pe.formality_min))
            pe.formality_decay = float(p_cfg.get("formality_decay_per_day", pe.formality_decay))
            pe.time_layers = p_cfg.get("time_layers") or pe.time_layers
            logger.info("Personality Engine Settings aktualisiert")

        # Proactive: Cooldowns und Batch-Interval
        if "proactive" in changed_settings and hasattr(brain, "proactive"):
            pro_cfg = yaml_cfg.get("proactive", {})
            brain.proactive.batch_interval = int(pro_cfg.get("batch_interval", 30))
            brain.proactive.enabled = bool(pro_cfg.get("enabled", True))
            logger.info("Proactive Settings aktualisiert")

        # Routines: Morning/Evening Briefing
        if "routines" in changed_settings and hasattr(brain, "proactive"):
            routines_cfg = yaml_cfg.get("routines", {})
            mb_cfg = routines_cfg.get("morning_briefing", {})
            brain.proactive._mb_enabled = bool(mb_cfg.get("enabled", True))
            brain.proactive._mb_window_start = int(mb_cfg.get("window_start_hour", 6))
            brain.proactive._mb_window_end = int(mb_cfg.get("window_end_hour", 10))
            eb_cfg = routines_cfg.get("evening_briefing", {})
            brain.proactive._eb_enabled = bool(eb_cfg.get("enabled", True))
            brain.proactive._eb_window_start = int(eb_cfg.get("window_start_hour", 20))
            brain.proactive._eb_window_end = int(eb_cfg.get("window_end_hour", 22))
            logger.info("Routine Settings aktualisiert")

        # Autonomy: Trust-Levels
        if "autonomy" in changed_settings and hasattr(brain, "autonomy"):
            auto_cfg = yaml_cfg.get("autonomy", {})
            brain.autonomy.level = int(auto_cfg.get("level", brain.autonomy.level))
            logger.info("Autonomy Settings aktualisiert")

        # Threat Assessment: Nacht-Zeiten
        if "threat_assessment" in changed_settings and hasattr(brain, "threat_assessment"):
            ta_cfg = yaml_cfg.get("threat_assessment", {})
            ta = brain.threat_assessment
            ta.night_start = int(ta_cfg.get("night_start_hour", ta.night_start))
            ta.night_end = int(ta_cfg.get("night_end_hour", ta.night_end))
            ta.enabled = bool(ta_cfg.get("enabled", ta.enabled))
            logger.info("Threat Assessment Settings aktualisiert")

        # TTS Enhancer
        if "tts" in changed_settings and hasattr(brain, "tts_enhancer"):
            tts_cfg = yaml_cfg.get("tts", {})
            te = brain.tts_enhancer
            speed_val = tts_cfg.get("speed", getattr(te, "speed", 1.0))
            if not isinstance(speed_val, dict):
                te.speed = float(speed_val)
            pitch_val = tts_cfg.get("pitch", getattr(te, "pitch", 1.0))
            if not isinstance(pitch_val, dict):
                te.pitch = float(pitch_val)
            logger.info("TTS Enhancer Settings aktualisiert")

        # Web Search
        if "web_search" in changed_settings and hasattr(brain, "web_search"):
            ws_cfg = yaml_cfg.get("web_search", {})
            ws = brain.web_search
            ws.enabled = bool(ws_cfg.get("enabled", False))
            ws.engine = ws_cfg.get("engine", ws.engine)
            ws.searxng_url = ws_cfg.get("searxng_url", ws.searxng_url)
            ws.max_results = int(ws_cfg.get("max_results", ws.max_results))
            ws.timeout = int(ws_cfg.get("timeout_seconds", ws.timeout))
            logger.info("Web Search Settings aktualisiert (enabled=%s, engine=%s)",
                        ws.enabled, ws.engine)

        # Health Monitor: Schwellwerte + Exclude-Patterns
        if "health_monitor" in changed_settings and hasattr(brain, "health_monitor"):
            hm_cfg = yaml_cfg.get("health_monitor", {})
            hm = brain.health_monitor
            hm.enabled = bool(hm_cfg.get("enabled", True))
            hm.check_interval = int(hm_cfg.get("check_interval_minutes", 10))
            hm.co2_warn = int(hm_cfg.get("co2_warn", 1000))
            hm.co2_critical = int(hm_cfg.get("co2_critical", 1500))
            hm.humidity_low = int(hm_cfg.get("humidity_low", 30))
            hm.humidity_high = int(hm_cfg.get("humidity_high", 70))
            hm.temp_low = int(hm_cfg.get("temp_low", 16))
            hm.temp_high = int(hm_cfg.get("temp_high", 27))
            hm._alert_cooldown_minutes = int(hm_cfg.get("alert_cooldown_minutes", 60))
            # Exclude-Patterns neu laden
            user_excludes = hm_cfg.get("exclude_patterns", [])
            if isinstance(user_excludes, str):
                user_excludes = [p.strip() for p in user_excludes.splitlines() if p.strip()]
            hm._exclude_patterns = [p.lower() for p in (hm._default_excludes + user_excludes)]
            logger.info("Health Monitor Settings aktualisiert")

        # InsightEngine: Alle Einstellungen hot-reloadbar
        if "insights" in changed_settings and hasattr(brain, "insight_engine"):
            brain.insight_engine.reload_config()
            logger.info("InsightEngine Settings aktualisiert")

        # Situation Model: Schwellwerte + Toggle
        if "situation_model" in changed_settings and hasattr(brain, "situation_model"):
            sm_cfg = yaml_cfg.get("situation_model", {})
            sm = brain.situation_model
            sm.enabled = bool(sm_cfg.get("enabled", True))
            sm.min_pause_minutes = int(sm_cfg.get("min_pause_minutes", 5))
            sm.max_changes = int(sm_cfg.get("max_changes", 5))
            sm.temp_threshold = float(sm_cfg.get("temp_threshold", 2))
            logger.info("Situation Model Settings aktualisiert")

        # Interrupt-Queue: Wird direkt aus yaml_config gelesen (websocket.py),
        # keine gecachten Attribute — nur Logging fuer Feedback
        if "interrupt_queue" in changed_settings:
            logger.info("Interrupt-Queue Settings aktualisiert (live aus yaml_config)")

    except Exception as e:
        logger.warning("Settings-Propagation teilweise fehlgeschlagen: %s", e)


# Sicherheitskritische Keys die aus Bulk-Settings-Updates herausgefiltert werden.
# Diese duerfen NUR ueber ihre dedizierten Endpoints geaendert werden.
# "dashboard" → PIN-Hash, Recovery-Key duerfen nie per Bulk ueberschrieben werden
# "self_optimization.immutable_keys" → Schutz vor Manipulation der Immutable-Liste
_SETTINGS_STRIP_KEYS = frozenset({"dashboard"})
_SETTINGS_STRIP_SUBKEYS = {
    "security": frozenset({"api_key", "api_key_required"}),  # Nur via dedizierte Endpoints
    "self_optimization": frozenset({"immutable_keys"}),       # Darf nicht per UI geaendert werden
}


def _sync_speech_to_env(speech_cfg: dict):
    """Synchronisiert speech-Settings aus settings.yaml in die .env Datei.

    Damit docker-compose beim naechsten Neustart die neuen Werte verwendet.
    Mapping: speech.stt_model → WHISPER_MODEL, speech.tts_voice → PIPER_VOICE, etc.
    """
    ENV_MAP = {
        "stt_model": "WHISPER_MODEL",
        "stt_language": "WHISPER_LANGUAGE",
        "stt_beam_size": "WHISPER_BEAM_SIZE",
        "stt_compute": "WHISPER_COMPUTE",
        "stt_device": "SPEECH_DEVICE",
        "tts_voice": "PIPER_VOICE",
    }
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = set()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            for yaml_key, env_key in ENV_MAP.items():
                if key == env_key and yaml_key in speech_cfg:
                    val = speech_cfg[yaml_key]
                    # Kommentar nach dem Wert beibehalten
                    old_parts = line.split("#", 1)
                    comment = f"  # {old_parts[1].strip()}" if len(old_parts) > 1 else ""
                    # Whitespace-Ausrichtung vom Original beibehalten
                    prefix = line[:len(line) - len(line.lstrip())]
                    lines[i] = f"{prefix}{env_key}={val}{comment}"
                    updated.add(env_key)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if updated:
            logger.info("Speech-Settings in .env aktualisiert: %s", ", ".join(sorted(updated)))
    except Exception as e:
        logger.warning("Speech → .env Sync fehlgeschlagen: %s", e)


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

        # F-041: Settings-Werte validieren
        validation_errors = _validate_settings_values(safe_settings)
        if validation_errors:
            return {
                "success": False,
                "message": f"Ungueltige Werte: {', '.join(validation_errors)}",
            }

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

        # Diagnostics: monitored_entities aktualisieren
        if hasattr(brain, "diagnostics"):
            diag_cfg = cfg.yaml_config.get("diagnostics", {})
            brain.diagnostics.monitored_entities = diag_cfg.get("monitored_entities", [])

        # SoundManager: alexa_speakers aktualisieren
        if hasattr(brain, "sound_manager"):
            sound_cfg = cfg.yaml_config.get("sounds", {})
            brain.sound_manager.alexa_speakers = sound_cfg.get("alexa_speakers", [])

        # Speech-Engine: settings.yaml → .env synchronisieren (fuer docker-compose)
        if "speech" in safe_settings:
            _sync_speech_to_env(cfg.yaml_config.get("speech", {}))

        # F-038: Alle weiteren Module benachrichtigen die Config bei __init__ cachen
        _reload_all_modules(cfg.yaml_config, safe_settings)

        # Audit-Log (mit Details ueber geschuetzte Keys)
        changed_keys = list(safe_settings.keys())
        audit_details = {"changed_sections": changed_keys}
        if stripped:
            audit_details["stripped_protected"] = stripped
        _audit_log("settings_update", audit_details)

        reloaded_count = 4 + len(_get_reloaded_modules(safe_settings))
        restart_hint = " — Container-Neustart noetig fuer Sprach-Engine!" if "speech" in safe_settings else ""
        return {
            "success": True,
            "message": f"Settings gespeichert ({reloaded_count} Module aktualisiert){restart_hint}",
            "restart_needed": "speech" in safe_settings,
        }
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


# ---------------------------------------------------------------
# Room Temperature Sensors (Mittelwert-Berechnung)
# ---------------------------------------------------------------

@app.get("/api/ui/room-temperature")
async def ui_get_room_temperature(token: str = ""):
    """Konfigurierte Raumtemperatur-Sensoren mit aktuellem Wert und Mittelwert."""
    _check_token(token)
    try:
        import assistant.config as cfg
        rt_cfg = cfg.yaml_config.get("room_temperature", {})
        sensor_ids = rt_cfg.get("sensors", []) or []

        states = await brain.ha.get_states()
        state_map = {s.get("entity_id"): s for s in (states or [])}

        sensors = []
        temps = []
        for sid in sensor_ids:
            s = state_map.get(sid, {})
            name = s.get("attributes", {}).get("friendly_name", sid) if s else sid
            val = None
            try:
                val = float(s.get("state", ""))
            except (ValueError, TypeError):
                pass
            sensors.append({
                "entity_id": sid,
                "name": name,
                "value": val,
                "unit": s.get("attributes", {}).get("unit_of_measurement", "°C") if s else "°C",
                "available": s.get("state") not in (None, "unavailable", "unknown", ""),
            })
            if val is not None:
                temps.append(val)

        avg = round(sum(temps) / len(temps), 1) if temps else None

        return {
            "sensors": sensors,
            "average": avg,
            "count": len(sensors),
            "active_count": len(temps),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.put("/api/ui/room-temperature")
async def ui_set_room_temperature(req: Request, token: str = ""):
    """Raumtemperatur-Sensoren konfigurieren. Body: {"sensors": ["sensor.x", ...]}"""
    _check_token(token)
    try:
        data = await req.json()
        sensor_list = data.get("sensors", [])
        if not isinstance(sensor_list, list):
            raise HTTPException(status_code=400, detail="sensors muss eine Liste sein")

        # Validierung: nur sensor.* Entity-IDs erlaubt
        for sid in sensor_list:
            if not isinstance(sid, str) or not sid.startswith("sensor."):
                raise HTTPException(status_code=400, detail=f"Ungueltige Entity-ID: {sid}")

        # In settings.yaml speichern
        with open(SETTINGS_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}

        if "room_temperature" not in config:
            config["room_temperature"] = {}
        config["room_temperature"]["sensors"] = sensor_list

        with open(SETTINGS_YAML_PATH, "w") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # yaml_config im Speicher aktualisieren
        import assistant.config as cfg
        cfg.yaml_config = load_yaml_config()

        return {"success": True, "count": len(sensor_list)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/room-temperature/available")
async def ui_get_available_temp_sensors(token: str = ""):
    """Alle verfuegbaren Temperatur-Sensoren aus Home Assistant."""
    _check_token(token)
    try:
        states = await brain.ha.get_states()
        sensors = []
        for s in (states or []):
            eid = s.get("entity_id", "")
            if not eid.startswith("sensor."):
                continue
            attrs = s.get("attributes", {})
            unit = attrs.get("unit_of_measurement", "")
            device_class = attrs.get("device_class", "")
            # Nur Temperatur-Sensoren
            if device_class == "temperature" or unit in ("°C", "°F"):
                val = None
                try:
                    val = float(s.get("state", ""))
                except (ValueError, TypeError):
                    pass
                sensors.append({
                    "entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                    "value": val,
                    "unit": unit or "°C",
                })
        sensors.sort(key=lambda x: x["name"])
        return {"sensors": sensors, "total": len(sensors)}
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
        configs = load_cover_configs()
        covers = []
        for s in (states or []):
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
                continue
            attrs = s.get("attributes", {})
            conf = configs.get(eid, {})
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
    """Cover-Typ und enabled-Status setzen (lokal + Addon-Sync)."""
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
        # 1. Lokal speichern (fuer Assistant-Level _is_safe_cover)
        configs = load_cover_configs()
        if entity_id not in configs:
            configs[entity_id] = {}
        configs[entity_id].update(payload)
        save_cover_configs(configs)
        # 2. An Addon synchen (fuer Addon-Level set_position/Automationen)
        try:
            await brain.ha.mindhome_put(
                f"/api/covers/{entity_id}/config", payload,
            )
        except Exception as sync_err:
            logger.warning("Cover-Config Sync zum Addon fehlgeschlagen: %s", sync_err)
        return {"success": True, **payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/action-log")
async def ui_get_action_log(
    token: str = "",
    limit: int = 50,
    offset: int = 0,
    type: str = "",
    period: str = "7d",
):
    """Jarvis Action-Log vom MindHome Add-on holen (mit Filtern)."""
    _check_token(token)
    try:
        params = f"limit={limit}&offset={offset}&period={period}"
        if type:
            params += f"&type={type}"
        result = await brain.ha.mindhome_get(f"/api/action-log?{params}")
        return result or {"items": [], "total": 0, "has_more": False}
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
            except Exception as e:
                logger.debug("ChromaDB count() fehlgeschlagen: %s", e)

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


# ----- Presence: Live Person Status + Settings -----

@app.get("/api/ui/presence")
async def ui_get_presence(token: str = ""):
    """Live-Anwesenheitsstatus aller Personen aus Home Assistant."""
    _check_token(token)
    try:
        states = await brain.ha.get_states()
        persons = []
        for s in (states or []):
            eid = s.get("entity_id", "")
            if not eid.startswith("person."):
                continue
            attrs = s.get("attributes", {})
            persons.append({
                "entity_id": eid,
                "name": attrs.get("friendly_name", eid),
                "state": s.get("state", "unknown"),
                "source": attrs.get("source"),
                "latitude": attrs.get("latitude"),
                "longitude": attrs.get("longitude"),
            })
        home_count = sum(1 for p in persons if p["state"] == "home")
        away_count = sum(1 for p in persons if p["state"] == "not_home")
        return {
            "persons": persons,
            "total": len(persons),
            "home_count": home_count,
            "away_count": away_count,
            "unknown_count": len(persons) - home_count - away_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.get("/api/ui/presence/settings")
async def ui_get_presence_settings(token: str = ""):
    """Presence-Einstellungen vom MindHome Addon holen."""
    _check_token(token)
    try:
        result = await brain.ha.mindhome_get("/api/presence/settings")
        return result or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler: {e}")


@app.put("/api/ui/presence/settings")
async def ui_update_presence_settings(token: str = "", data: dict = {}):
    """Presence-Einstellungen im MindHome Addon aktualisieren."""
    _check_token(token)
    try:
        result = await brain.ha.mindhome_put("/api/presence/settings", data)
        return result or {"success": False}
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


@app.get("/api/ui/knowledge/chunks")
async def ui_knowledge_chunks(token: str = "", source: str = "", offset: int = 0, limit: int = 50):
    """Alle Knowledge-Chunks auflisten (optional gefiltert nach Quelle)."""
    _check_token(token)
    chunks = await brain.knowledge_base.get_chunks(source=source, offset=offset, limit=min(limit, 200))
    stats = await brain.knowledge_base.get_stats()
    return {"chunks": chunks, "total": stats.get("total_chunks", 0)}


@app.post("/api/ui/knowledge/chunks/delete")
async def ui_knowledge_delete_chunks(request: Request, token: str = ""):
    """Einzelne Knowledge-Chunks loeschen."""
    _check_token(token)
    body = await request.json()
    chunk_ids = body.get("ids", [])
    if not chunk_ids:
        raise HTTPException(status_code=400, detail="Keine Chunk-IDs angegeben")
    deleted = await brain.knowledge_base.delete_chunks(chunk_ids)
    _audit_log("knowledge_base_delete", {"deleted": deleted, "ids": chunk_ids[:5]})
    stats = await brain.knowledge_base.get_stats()
    return {"deleted": deleted, "stats": stats}


@app.post("/api/ui/knowledge/file/delete")
async def ui_knowledge_file_delete(request: Request, token: str = ""):
    """Alle Chunks einer Datei aus der Knowledge Base loeschen."""
    _check_token(token)
    body = await request.json()
    filename = body.get("filename", "")
    if not filename:
        raise HTTPException(status_code=400, detail="Kein Dateiname angegeben")
    deleted = await brain.knowledge_base.delete_source_chunks(filename)
    _audit_log("knowledge_file_delete", {"filename": filename, "deleted_chunks": deleted})
    stats = await brain.knowledge_base.get_stats()
    return {"deleted": deleted, "filename": filename, "stats": stats}


@app.post("/api/ui/knowledge/file/reingest")
async def ui_knowledge_file_reingest(request: Request, token: str = ""):
    """Einzelne Datei loeschen und neu einlesen."""
    _check_token(token)
    body = await request.json()
    filename = body.get("filename", "")
    if not filename:
        raise HTTPException(status_code=400, detail="Kein Dateiname angegeben")
    new_chunks = await brain.knowledge_base.reingest_file(filename)
    _audit_log("knowledge_file_reingest", {"filename": filename, "new_chunks": new_chunks})
    stats = await brain.knowledge_base.get_stats()
    return {"new_chunks": new_chunks, "filename": filename, "stats": stats}


@app.post("/api/ui/knowledge/rebuild")
async def ui_knowledge_rebuild(token: str = ""):
    """Knowledge Base komplett neu aufbauen (Collection loeschen + alle Dateien neu einlesen).

    Noetig nach Wechsel des Embedding-Modells, damit alle Vektoren
    mit dem neuen Modell berechnet werden.
    """
    _check_token(token)
    result = await brain.knowledge_base.rebuild()
    _audit_log("knowledge_base_rebuild", result)
    return result


@app.post("/api/ui/knowledge/upload")
async def ui_knowledge_upload(file: UploadFile = File(...), token: str = Form("")):
    """Datei in die Wissensdatenbank hochladen und sofort einlesen."""
    _check_token(token)
    from .knowledge_base import KB_UPLOAD_MAX_SIZE, KB_UPLOAD_ALLOWED

    if not file.filename:
        raise HTTPException(status_code=400, detail="Keine Datei ausgewaehlt")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in KB_UPLOAD_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Dateityp '{suffix}' nicht erlaubt. Erlaubt: {', '.join(sorted(KB_UPLOAD_ALLOWED))}")

    content = await file.read()
    if len(content) > KB_UPLOAD_MAX_SIZE:
        mb = KB_UPLOAD_MAX_SIZE // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Datei zu gross (max {mb} MB)")

    # Sicheren Dateinamen erzeugen
    safe_name = Path(file.filename).name.replace("/", "_").replace("\\", "_")
    kb_dir = Path(__file__).parent.parent / "config" / "knowledge"
    kb_dir.mkdir(parents=True, exist_ok=True)
    target = kb_dir / safe_name

    # Datei speichern
    target.write_bytes(content)

    # Sofort einlesen
    new_chunks = await brain.knowledge_base.ingest_file(target)
    _audit_log("knowledge_file_upload", {"filename": safe_name, "size": len(content), "chunks": new_chunks})
    stats = await brain.knowledge_base.get_stats()
    return {"filename": safe_name, "new_chunks": new_chunks, "size": len(content), "stats": stats}


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
    """Jarvis Dashboard — Single-Page App + statische Assets (JS/CSS)."""
    # Statische Assets (app.js, *.css etc.) direkt ausliefern
    if path and not path.endswith("/"):
        asset = _ui_static_dir / path
        if asset.is_file() and asset.resolve().is_relative_to(_ui_static_dir.resolve()):
            media_types = {".js": "application/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml"}
            mt = media_types.get(asset.suffix, None)
            return FileResponse(asset, media_type=mt, headers=_NO_CACHE_HEADERS)
    # SPA-Fallback: immer index.html
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


def _deep_merge(base: dict, override: dict, _depth: int = 0):
    """Tiefer Merge von override in base (in-place).

    F-040: Tiefe begrenzt auf 10 Level um endlose Rekursion bei
    zirkulaeren Referenzen zu verhindern.
    """
    if _depth > 10:
        logger.warning("_deep_merge: Maximale Tiefe erreicht (10)")
        return
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value, _depth + 1)
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
    for name in ["mindhome-assistant", "mha-chromadb", "mha-redis", "mha-whisper", "mha-piper"]:
        rc, out = _run_cmd(["docker", "inspect", "--format", "{{.State.Health.Status}}", name])
        containers[name] = out.strip() if rc == 0 else "unknown"

    # Ollama (via HTTP API auf dem Host)
    ollama_ok, ollama_data = await _ollama_api("/api/tags")
    ollama_models = ""
    if ollama_ok and isinstance(ollama_data, dict):
        models = ollama_data.get("models", [])
        lines = [f"{m.get('name', '?'):30s} {m.get('size', 0) / 1e9:.1f} GB" for m in models]
        ollama_models = "\n".join(["NAME                           SIZE"] + lines)

    # Disk — alle physischen Partitionen erkennen (inkl. zweite SSD)
    disk_info = {}
    disk_path = _REPO_DIR if _REPO_DIR.exists() else Path("/app")
    total, used, free = shutil.disk_usage(str(disk_path))
    disk_info["system"] = {
        "total_gb": round(total / (1024**3), 1),
        "used_gb": round(used / (1024**3), 1),
        "free_gb": round(free / (1024**3), 1),
    }
    # Weitere Partitionen aus /proc/mounts lesen
    try:
        seen_devs = set()
        with open("/proc/mounts") as f:
            for line in f:
                parts_m = line.split()
                if len(parts_m) < 2:
                    continue
                dev, mount = parts_m[0], parts_m[1]
                if not dev.startswith("/dev/") or dev in seen_devs:
                    continue
                # Nur echte Block-Devices (sd*, nvme*, vd*), keine loop/ram
                base = dev.split("/")[-1]
                if not any(base.startswith(p) for p in ("sd", "nvme", "vd", "hd")):
                    continue
                seen_devs.add(dev)
                try:
                    t, u, fr = shutil.disk_usage(mount)
                    total_gb = round(t / (1024**3), 1)
                    # Ueberspringe wenn es dasselbe wie system ist
                    if total_gb == disk_info["system"]["total_gb"]:
                        continue
                    disk_info[mount] = {
                        "total_gb": total_gb,
                        "used_gb": round(u / (1024**3), 1),
                        "free_gb": round(fr / (1024**3), 1),
                        "device": dev,
                    }
                except Exception:
                    pass
    except Exception:
        pass

    # RAM (via /proc/meminfo)
    ram_info = {}
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            used_kb = total_kb - avail_kb
            ram_info = {
                "total_gb": round(total_kb / (1024**2), 1),
                "used_gb": round(used_kb / (1024**2), 1),
                "free_gb": round(avail_kb / (1024**2), 1),
                "percent": round(used_kb / total_kb * 100, 1) if total_kb else 0,
            }
    except Exception:
        pass

    # CPU Load
    cpu_info = {}
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        cpu_info = {
            "load_1m": round(load1, 2),
            "load_5m": round(load5, 2),
            "load_15m": round(load15, 2),
            "cores": cpu_count,
            "percent": round(load1 / cpu_count * 100, 1),
        }
    except Exception:
        pass

    # GPU — Status-Datei vom Host-Watchdog lesen (nvidia-watchdog schreibt alle 60s)
    gpu_info = {}
    _gpu_status_file = Path("/var/lib/mindhome/gpu_status.json")
    try:
        if _gpu_status_file.exists():
            data = json.loads(_gpu_status_file.read_text())
            if data.get("available") and data.get("name"):
                gpu_info = {
                    "name": data["name"],
                    "memory_used_mb": int(data["memory_used_mb"]),
                    "memory_total_mb": int(data["memory_total_mb"]),
                    "utilization_percent": int(data["utilization_percent"]),
                    "temperature_c": int(data["temperature_c"]),
                }
    except Exception:
        pass
    # Fallback 1: direktes nvidia-smi (falls Container GPU-Zugriff hat)
    if not gpu_info:
        rc_gpu, gpu_out = _run_cmd([
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ])
        if rc_gpu == 0 and gpu_out.strip():
            parts = [p.strip() for p in gpu_out.strip().split(",")]
            if len(parts) >= 5:
                try:
                    gpu_info = {
                        "name": parts[0],
                        "memory_used_mb": int(parts[1]),
                        "memory_total_mb": int(parts[2]),
                        "utilization_percent": int(parts[3]),
                        "temperature_c": int(parts[4]),
                    }
                except (ValueError, IndexError):
                    pass

    # Fallback 2: nvidia-smi via Host PID namespace (Container hat Docker-Socket)
    if not gpu_info:
        rc_gpu, gpu_out = _run_cmd([
            "nsenter", "--target", "1", "--mount", "--uts", "--",
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ], timeout=10)
        if rc_gpu == 0 and gpu_out.strip():
            parts = [p.strip() for p in gpu_out.strip().split(",")]
            if len(parts) >= 5:
                try:
                    gpu_info = {
                        "name": parts[0],
                        "memory_used_mb": int(parts[1]),
                        "memory_total_mb": int(parts[2]),
                        "utilization_percent": int(parts[3]),
                        "temperature_c": int(parts[4]),
                    }
                except (ValueError, IndexError):
                    pass

    # Fallback 3: Ollama /api/ps — zeigt GPU-Nutzung geladener Modelle
    if not gpu_info:
        try:
            import aiohttp as _aio_tmp
            async with _aio_tmp.ClientSession(
                timeout=_aio_tmp.ClientTimeout(total=5)
            ) as _sess:
                async with _sess.get(f"{_OLLAMA_URL}/api/ps") as resp:
                    if resp.status == 200:
                        ps_data = await resp.json()
                        models = ps_data.get("models", [])
                        for m in models:
                            details = m.get("details", {})
                            size_vram = m.get("size_vram", 0)
                            size_total = m.get("size", 0)
                            if size_vram > 0:
                                gpu_info = {
                                    "name": "GPU (via Ollama)",
                                    "memory_used_mb": round(size_vram / 1024 / 1024),
                                    "memory_total_mb": round(size_total / 1024 / 1024),
                                    "utilization_percent": 0,
                                    "temperature_c": 0,
                                    "ollama_fallback": True,
                                }
                                break
        except Exception:
            pass

    # Remote claude/* Branches auflisten
    _, remote_branches_raw = _run_cmd(
        ["git", "branch", "-r", "--list", "origin/claude/*"],
        cwd=str(_REPO_DIR),
    )
    remote_branches = [
        b.strip().removeprefix("origin/")
        for b in remote_branches_raw.strip().splitlines()
        if b.strip() and "->" not in b
    ]

    return {
        "git": {
            "branch": branch.strip(),
            "commit": commit.strip(),
            "changes": git_status.strip(),
            "remote_branches": remote_branches,
        },
        "containers": containers,
        "ollama": {
            "available": ollama_ok,
            "models": ollama_models,
        },
        "disk": disk_info,
        "ram": ram_info,
        "cpu": cpu_info,
        "gpu": gpu_info,
        "version": "1.4.2",
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


class BranchUpdateRequest(BaseModel):
    branch: str | None = None


@app.post("/api/ui/system/update")
async def ui_system_update(token: str = "", body: BranchUpdateRequest | None = None):
    """System-Update: git pull + Container-Restart (Code ist als Volume gemountet).

    WICHTIG: User-Konfiguration (settings.yaml, .env) wird vor dem Pull
    gesichert und danach wiederhergestellt, damit Einstellungen nicht verloren gehen.

    Optionaler Body-Parameter 'branch': Wenn angegeben, wird auf diesen Branch
    gewechselt bevor der Pull ausgefuehrt wird.
    """
    _check_token(token)

    if _update_lock.locked():
        raise HTTPException(status_code=409, detail="Update laeuft bereits")

    target_branch = body.branch.strip() if body and body.branch else None

    async with _update_lock:
        _update_log.clear()
        _update_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Update gestartet...")

        # Aktuellen Branch merken (fuer Rollback bei Fehler)
        _, current_branch_raw = _run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(_REPO_DIR)
        )
        old_branch = current_branch_raw.strip()
        switching = target_branch and target_branch != old_branch

        if switching:
            _update_log.append(f"Branch-Wechsel: {old_branch} -> {target_branch}")
        else:
            _update_log.append(f"Update auf Branch: {target_branch or old_branch}")

        # 0. User-Konfiguration sichern (vor git pull!)
        _user_config_files = [
            _MHA_DIR / "config" / "settings.yaml",
            _MHA_DIR / ".env",
            Path("/app/data/cover_configs.json"),
        ]
        _saved_configs = {}
        for cfg_path in _user_config_files:
            if cfg_path.exists():
                _saved_configs[cfg_path] = cfg_path.read_text(encoding="utf-8")
                _update_log.append(f"Config gesichert: {cfg_path.name}")

        # 0b. ALLE lokalen Aenderungen stashen, damit git pull/checkout sauber durchlaeuft.
        #     User-Config ist bereits in _saved_configs gesichert und wird danach
        #     wiederhergestellt — unabhaengig davon was Git macht.
        _run_cmd(["git", "stash", "--include-untracked"], cwd=str(_REPO_DIR))
        _update_log.append("Lokale Aenderungen gestasht")

        # 1. Branch-Wechsel (falls gewuenscht)
        if switching:
            # Fetch des Ziel-Branches
            _update_log.append(f"Fetch origin/{target_branch}...")
            rc_fetch, out_fetch = _run_cmd(
                ["git", "fetch", "origin", target_branch],
                cwd=str(_REPO_DIR), timeout=60,
            )
            if rc_fetch != 0:
                _update_log.append(f"FEHLER: git fetch fehlgeschlagen: {out_fetch.strip()}")
                # Stash droppen, Config wiederherstellen, abbrechen
                _run_cmd(["git", "stash", "drop"], cwd=str(_REPO_DIR))
                for cfg_path, content in _saved_configs.items():
                    try:
                        cfg_path.write_text(content, encoding="utf-8")
                    except Exception:
                        pass
                return {"success": False, "log": _update_log}

            # Checkout auf Ziel-Branch
            _update_log.append(f"Checkout {target_branch}...")
            rc_co, out_co = _run_cmd(
                ["git", "checkout", target_branch],
                cwd=str(_REPO_DIR), timeout=30,
            )
            if rc_co != 0:
                _update_log.append(f"FEHLER: git checkout fehlgeschlagen: {out_co.strip()}")
                # Zurueck zum alten Branch
                _run_cmd(["git", "checkout", old_branch], cwd=str(_REPO_DIR))
                _run_cmd(["git", "stash", "drop"], cwd=str(_REPO_DIR))
                for cfg_path, content in _saved_configs.items():
                    try:
                        cfg_path.write_text(content, encoding="utf-8")
                    except Exception:
                        pass
                _update_log.append(f"Rollback zu {old_branch}")
                return {"success": False, "log": _update_log}

        # 2. Git Pull
        pull_branch = target_branch or old_branch
        _update_log.append(f"Git pull origin/{pull_branch}...")
        rc, out = _run_cmd(
            ["git", "pull", "--rebase", "origin", pull_branch],
            cwd=str(_REPO_DIR), timeout=60,
        )

        # Stash wieder droppen (User-Config kommt aus _saved_configs, nicht aus stash)
        _run_cmd(["git", "stash", "drop"], cwd=str(_REPO_DIR))
        _update_log.append(out.strip())
        if rc != 0:
            # Bei Fehler und Branch-Wechsel: zurueck zum alten Branch
            if switching:
                _run_cmd(["git", "checkout", old_branch], cwd=str(_REPO_DIR))
                _update_log.append(f"Rollback zu {old_branch}")
            # User-Config wiederherstellen
            for cfg_path, content in _saved_configs.items():
                try:
                    cfg_path.write_text(content, encoding="utf-8")
                except Exception:
                    pass
            _update_log.append("FEHLER: Git pull fehlgeschlagen")
            return {"success": False, "log": _update_log}

        # 3. User-Konfiguration wiederherstellen (nach git pull!)
        #    Die gesicherten User-Settings ueberschreiben die Repo-Defaults.
        for cfg_path, content in _saved_configs.items():
            try:
                cfg_path.write_text(content, encoding="utf-8")
                _update_log.append(f"Config wiederhergestellt: {cfg_path.name}")
            except Exception as e:
                _update_log.append(f"WARNUNG: {cfg_path.name} konnte nicht wiederhergestellt werden: {e}")

        _update_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Code aktualisiert! Container startet neu...")

        # 4. Restart via Docker Engine API (Code als Volume = sofort aktiv)
        # asyncio.ensure_future damit Response noch rausgeht bevor Restart
        asyncio.ensure_future(_docker_restart())

        return {"success": True, "log": _update_log, "branch": pull_branch}


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
async def ui_system_update_check(token: str = "", branch: str = ""):
    """Prueft ob neue Commits auf dem Remote verfuegbar sind.

    Optionaler Query-Parameter 'branch': Wenn angegeben, wird gegen diesen
    Remote-Branch verglichen statt gegen den aktuellen Branch.
    """
    _check_token(token)

    # Aktuellen Branch ermitteln
    _, current_branch_raw = _run_cmd(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(_REPO_DIR)
    )
    current_branch = current_branch_raw.strip() or "main"
    check_branch = branch.strip() if branch.strip() else current_branch
    is_different_branch = check_branch != current_branch

    # Fetch
    rc, fetch_out = _run_cmd(
        ["git", "fetch", "origin", check_branch],
        cwd=str(_REPO_DIR), timeout=30,
    )
    if rc != 0:
        return {
            "updates_available": False,
            "error": f"Git fetch fehlgeschlagen fuer {check_branch}",
            "current_branch": current_branch,
            "check_branch": check_branch,
        }

    # Lokalen HEAD ermitteln
    _, local = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(_REPO_DIR))
    _, remote = _run_cmd(
        ["git", "rev-parse", f"origin/{check_branch}"], cwd=str(_REPO_DIR)
    )

    local = local.strip()
    remote = remote.strip()

    result = {
        "current_branch": current_branch,
        "check_branch": check_branch,
        "is_branch_switch": is_different_branch,
        "local": local[:8],
        "remote": remote[:8],
    }

    if not is_different_branch and local == remote:
        result["updates_available"] = False
        return result

    # Bei anderem Branch oder unterschiedlichen Commits: Updates vorhanden
    if is_different_branch:
        # Commits auf dem Ziel-Branch anzeigen (letzte 20)
        _, log = _run_cmd(
            ["git", "log", "--oneline", "-20", f"origin/{check_branch}"],
            cwd=str(_REPO_DIR),
        )
        result["updates_available"] = True
        result["new_commits"] = log.strip().split("\n") if log.strip() else []
    else:
        _, log = _run_cmd(
            ["git", "log", "--oneline", f"{local}..{remote}"],
            cwd=str(_REPO_DIR),
        )
        result["updates_available"] = True
        result["new_commits"] = log.strip().split("\n") if log.strip() else []

    return result


@app.get("/")
async def root():
    """Startseite."""
    return {
        "name": "MindHome Assistant",
        "version": "1.4.2",
        "status": "running",
        "docs": "/docs",
        "dashboard": "/ui/",
    }


# ----- Kubernetes-ready Health Probes -----

@app.get("/healthz", tags=["probes"])
async def healthz():
    """Liveness Probe — Ist der Prozess am Leben?"""
    return {"status": "alive"}


@app.get("/readyz", tags=["probes"])
async def readyz():
    """Readiness Probe — Ist der Assistant bereit fuer Requests?"""
    try:
        health = await brain.health_check()
        components = health.get("components", {})
        redis_ok = components.get("redis") == "connected"
        ollama_ok = components.get("ollama") == "connected"

        if redis_ok and ollama_ok:
            return {"status": "ready", "components": components}

        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "components": components},
        )
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(type(e).__name__)},
        )


# ----- Prometheus-kompatible Metrics -----

@app.get("/metrics", tags=["monitoring"])
async def metrics():
    """Prometheus-Format Metrics Endpoint."""
    import time as _metrics_time

    lines = []

    # System-Info
    lines.append("# HELP mindhome_info MindHome Assistant Info")
    lines.append('# TYPE mindhome_info gauge')
    lines.append('mindhome_info{version="1.4.2"} 1')

    # Uptime (approximiert ueber Error-Buffer-Laenge)
    lines.append("# HELP mindhome_error_buffer_size Anzahl Fehler im Ring-Buffer")
    lines.append("# TYPE mindhome_error_buffer_size gauge")
    lines.append(f"mindhome_error_buffer_size {len(_error_buffer)}")

    # WebSocket Connections
    lines.append("# HELP mindhome_websocket_connections Aktive WebSocket-Verbindungen")
    lines.append("# TYPE mindhome_websocket_connections gauge")
    lines.append(f"mindhome_websocket_connections {len(ws_manager.active_connections)}")

    # Circuit Breaker Status
    try:
        from .circuit_breaker import registry as cb_registry
        for cb_status in cb_registry.all_status():
            name = cb_status["name"]
            state_val = 1 if cb_status["state"] == "closed" else 0
            lines.append(f'# HELP mindhome_circuit_{name}_closed Circuit Breaker Status')
            lines.append(f'# TYPE mindhome_circuit_{name}_closed gauge')
            lines.append(f'mindhome_circuit_{name}_closed {state_val}')
            lines.append(f'mindhome_circuit_{name}_failures {cb_status["failure_count"]}')
    except Exception:
        pass

    # Task Registry Status
    try:
        if hasattr(brain, '_task_registry'):
            lines.append("# HELP mindhome_background_tasks Aktive Background-Tasks")
            lines.append("# TYPE mindhome_background_tasks gauge")
            lines.append(f"mindhome_background_tasks {brain._task_registry.task_count}")
    except Exception:
        pass

    # Redis Memory (wenn verfuegbar)
    try:
        if brain.memory.redis:
            info = await brain.memory.redis.info("memory")
            used = info.get("used_memory", 0)
            lines.append("# HELP mindhome_redis_used_memory_bytes Redis Memory Usage")
            lines.append("# TYPE mindhome_redis_used_memory_bytes gauge")
            lines.append(f"mindhome_redis_used_memory_bytes {used}")
    except Exception:
        pass

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


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
