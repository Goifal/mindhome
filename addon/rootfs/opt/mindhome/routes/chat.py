# MindHome - routes/chat.py | see version.py for version info
"""
MindHome API Routes - Jarvis Chat
Proxies chat messages and file uploads to the MindHome Assistant (PC 2).
Files are stored on the Assistant server, not locally.
"""

import logging
import requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response

from helpers import get_setting

logger = logging.getLogger("mindhome.routes.chat")

chat_bp = Blueprint("chat", __name__)

# Module-level dependencies
_deps = {}

# In-memory conversation history (persists until addon restart)
_conversation_history = []
import threading

# Cached STT/TTS platform names (avoid repeated HA state lookups)
_stt_platform_cache = {}  # {stt_entity: platform_name}
_tts_engine_cache = {}    # {tts_entity: (engine_id, language)}


def _log_jarvis_actions(actions, user_text, response_text):
    """Log Jarvis actions to ActionLog for transparency."""
    if not actions:
        return
    try:
        from db import get_db_session
        from models import ActionLog
        with get_db_session() as session:
            for action in actions:
                func = action.get("function") or action.get("action") or "unknown"
                args = action.get("arguments") or action.get("args") or {}
                result_msg = action.get("result", {}).get("message", "")
                entry = ActionLog(
                    action_type="jarvis_action",
                    action_data={
                        "function": func,
                        "arguments": args,
                        "result": result_msg,
                        "response": response_text[:200] if response_text else "",
                    },
                    reason=f"Benutzer: {user_text[:150]}" if user_text else "Automatisch",
                )
                session.add(entry)
    except Exception as e:
        logger.debug("Action logging failed: %s", e)
_history_lock = threading.Lock()
MAX_HISTORY = 200

# File validation (checked before forwarding to assistant)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp",
    "mp4", "webm", "mov", "avi",
    "pdf", "txt", "csv", "json", "xml",
    "doc", "docx", "xls", "xlsx", "pptx",
    "mp3", "wav", "ogg", "m4a",
}
def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def init_chat(dependencies):
    """Initialize chat routes with shared dependencies."""
    global _deps
    _deps = dependencies


def _get_assistant_url():
    """Get the assistant URL from settings or environment.

    Only http/https schemes on private network addresses are allowed.
    """
    import os
    from urllib.parse import urlparse
    url = get_setting("assistant_url", None)
    if not url:
        url = os.environ.get("ASSISTANT_URL", "http://192.168.1.100:8200")
    url = url.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        logger.warning("Invalid assistant_url scheme: %s, falling back to default", parsed.scheme)
        return "http://192.168.1.100:8200"
    host = parsed.hostname or ""
    # Allow only private network ranges and localhost
    _ALLOWED_PREFIXES = ("192.168.", "10.", "172.16.", "172.17.", "172.18.",
                         "172.19.", "172.2", "172.30.", "172.31.",
                         "127.", "localhost", "::1")
    if not any(host.startswith(p) for p in _ALLOWED_PREFIXES):
        logger.warning("assistant_url host %s not in private range, falling back to default", host)
        return "http://192.168.1.100:8200"
    return url


def _get_assistant_api_key():
    """Get the assistant API key from settings or environment."""
    import os
    key = get_setting("assistant_api_key", None)
    if not key:
        key = os.environ.get("ASSISTANT_API_KEY", "")
    return key or ""


def _assistant_headers():
    """Build request headers including API key if configured."""
    headers = {}
    api_key = _get_assistant_api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


@chat_bp.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    """
    Send a message to Jarvis and get a response.

    Request: {"text": "Mach das Licht an", "person": "Max"}
    Response: {"response": "...", "actions": [...], "timestamp": "..."}
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Kein Text angegeben"}), 400

    person = data.get("person", get_setting("primary_user", "User"))
    room = data.get("room")

    # Store user message
    user_msg = {
        "role": "user",
        "text": text,
        "person": person,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with _history_lock:
        _conversation_history.append(user_msg)

    # Forward to assistant
    assistant_url = _get_assistant_url()
    try:
        resp = requests.post(
            f"{assistant_url}/api/assistant/chat",
            json={"text": text, "person": person, "room": room},
            headers=_assistant_headers(),
            timeout=30,
        )
        if resp.status_code == 200:
            result = resp.json()
            # Store assistant response
            assistant_msg = {
                "role": "assistant",
                "text": result.get("response", ""),
                "actions": result.get("actions", []),
                "model_used": result.get("model_used", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with _history_lock:
                _conversation_history.append(assistant_msg)
                while len(_conversation_history) > MAX_HISTORY:
                    _conversation_history.pop(0)

            # Log actions to ActionLog for transparency
            _log_jarvis_actions(result.get("actions", []), text, result.get("response", ""))

            return jsonify({
                "response": result.get("response", ""),
                "actions": result.get("actions", []),
                "model_used": result.get("model_used", ""),
                "timestamp": assistant_msg["timestamp"],
            })
        else:
            error_msg = f"Assistant returned {resp.status_code}"
            logger.warning("Chat proxy error: %s", error_msg)
            return jsonify({"error": error_msg, "response": None}), 502

    except requests.ConnectionError:
        logger.warning("Cannot reach assistant at %s", assistant_url)
        return jsonify({
            "error": "Assistant nicht erreichbar. Prüfe die Verbindung zu PC 2.",
            "response": None,
        }), 503
    except requests.Timeout:
        logger.warning("Assistant timeout at %s", assistant_url)
        return jsonify({
            "error": "Assistant antwortet nicht (Timeout).",
            "response": None,
        }), 504
    except Exception as e:
        logger.error("Chat proxy exception: %s", e)
        return jsonify({"error": "Operation failed", "response": None}), 500


@chat_bp.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    """
    Get conversation history.

    Query params:
        limit: Max messages to return (default 50)
        offset: Skip first N messages from the end (default 0)
    """
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    with _history_lock:
        total = len(_conversation_history)
        start = max(0, total - offset - limit)
        end = total - offset
        messages = list(_conversation_history[start:end])

    return jsonify({
        "messages": messages,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@chat_bp.route("/api/chat/clear", methods=["POST"])
def api_chat_clear():
    """Clear conversation history."""
    global _conversation_history
    with _history_lock:
        count = len(_conversation_history)
        _conversation_history = []
    return jsonify({"cleared": count})


@chat_bp.route("/api/chat/status", methods=["GET"])
def api_chat_status():
    """Check if the assistant is reachable."""
    assistant_url = _get_assistant_url()
    try:
        resp = requests.get(f"{assistant_url}/api/assistant/health", headers=_assistant_headers(), timeout=5)
        if resp.status_code == 200:
            health = resp.json()
            return jsonify({
                "connected": True,
                "assistant_url": assistant_url,
                "health": health,
            })
        return jsonify({"connected": False, "assistant_url": assistant_url, "error": f"Status {resp.status_code}"})
    except Exception as e:
        logger.error("Operation failed: %s", e)
        return jsonify({"connected": False, "assistant_url": assistant_url, "error": "Operation failed"}), 500


# ------------------------------------------------------------------
# File upload & serving — forwarded to Assistant (PC 2)
# ------------------------------------------------------------------

@chat_bp.route("/api/chat/upload", methods=["POST"])
def api_chat_upload():
    """
    Upload a file in the chat.

    Validates the file locally, then forwards it to the Assistant (PC 2)
    for storage, text extraction, and LLM processing.
    Returns file metadata + Jarvis response.
    """
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei angegeben"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Keine Datei ausgewählt"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": "Dateityp nicht erlaubt"}), 400

    # Check file size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        mb = MAX_FILE_SIZE // (1024 * 1024)
        return jsonify({"error": f"Datei zu groß (max {mb} MB)"}), 413

    person = request.form.get("person", get_setting("primary_user", "User"))
    caption = request.form.get("caption", "").strip()

    # Forward to Assistant (PC 2)
    assistant_url = _get_assistant_url()
    try:
        resp = requests.post(
            f"{assistant_url}/api/assistant/chat/upload",
            files={"file": (file.filename, file.stream, file.content_type or "application/octet-stream")},
            data={"caption": caption, "person": person},
            headers=_assistant_headers(),
            timeout=60,
        )

        if resp.status_code == 200:
            result = resp.json()
            file_info = result.get("file", {})

            # Rewrite URL: assistant URL -> addon proxy URL
            if file_info.get("url"):
                file_info["url"] = file_info["url"].replace(
                    "api/assistant/chat/files/", "api/chat/files/"
                )

            # Store user message with file
            user_msg = {
                "role": "user",
                "text": caption,
                "person": person,
                "timestamp": result.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "file": file_info,
            }
            with _history_lock:
                _conversation_history.append(user_msg)

            # Store assistant response (from LLM processing)
            if result.get("response"):
                assistant_msg = {
                    "role": "assistant",
                    "text": result["response"],
                    "actions": result.get("actions", []),
                    "model_used": result.get("model_used", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                with _history_lock:
                    _conversation_history.append(assistant_msg)

            with _history_lock:
                while len(_conversation_history) > MAX_HISTORY:
                    _conversation_history.pop(0)

            logger.info("Chat file uploaded to assistant: %s", file_info.get("name", "?"))

            return jsonify({
                "file": file_info,
                "response": result.get("response", ""),
                "actions": result.get("actions", []),
                "timestamp": user_msg["timestamp"],
            })
        else:
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                pass
            error_msg = f"Assistant returned {resp.status_code}: {detail}"
            logger.warning("Chat upload proxy error: %s", error_msg)
            return jsonify({"error": error_msg}), 502

    except requests.ConnectionError:
        logger.warning("Cannot reach assistant at %s for upload", assistant_url)
        return jsonify({
            "error": "Assistant nicht erreichbar. Prüfe die Verbindung zu PC 2.",
        }), 503
    except requests.Timeout:
        logger.warning("Assistant upload timeout at %s", assistant_url)
        return jsonify({
            "error": "Upload-Timeout. Datei zu groß oder Assistant überlastet.",
        }), 504
    except Exception as e:
        logger.error("Chat upload proxy exception: %s", e)
        return jsonify({"error": "Operation failed"}), 500


# ------------------------------------------------------------------
# Dialekt-Normalisierung (oesterreichisch / sueddeutsch)
# ------------------------------------------------------------------

# Whisper erkennt Dialekt oft falsch — diese Mappings korrigieren die
# haeufigsten Fehltranskriptionen bei oesterreichischer Aussprache.
# Format: (falsch_erkannt, korrekt) — case-insensitive Ersetzung

_DIALECT_WORD_MAP = {
    # Typische Whisper-Fehler bei oesterreichischem Deutsch
    "schalpte": "schalte",
    "schalptem": "schalte",
    "schoite": "schalte",
    "schoiten": "schalten",
    "beruhlicht": "bürolicht",
    "bürolickt": "bürolicht",
    "buerolicht": "bürolicht",
    "liacht": "licht",
    "hoazung": "heizung",
    "hazung": "heizung",
    "haizung": "heizung",
    "temperadur": "temperatur",
    "temparatur": "temperatur",
    "wohnzimma": "wohnzimmer",
    "schlofzimma": "schlafzimmer",
    "schlofzimmer": "schlafzimmer",
    "kuechn": "küche",
    "kuchl": "küche",
    "kuche": "küche",
    "fensta": "fenster",
    "rollodn": "rolladen",
    "rollladn": "rollladen",
    "jalousie": "jalousie",
    "jalusi": "jalousie",
    "oamoi": "einmal",
    "amoi": "einmal",
    "olle": "alle",
    "olles": "alles",
    "mochs": "machs",
    "moch": "mach",
    "wos": "was",
    "host": "hast",
    "hob": "hab",
    "mia": "mir",
    "nix": "nichts",
    "ned": "nicht",
    "net": "nicht",
    "a bissl": "ein bisschen",
    "bissl": "bisschen",
    "gemiatlich": "gemütlich",
    "gmuetlich": "gemütlich",
    "offen": "offen",
    "zuadrah": "zudrehen",
    "aufdrah": "aufdrehen",
    "abdrah": "abdrehen",
    "aufmochn": "aufmachen",
    "zumochn": "zumachen",
    "prozend": "prozent",
    "fernseha": "fernseher",
    "lautstaerke": "lautstärke",
    "lauda": "lauter",
    "leisa": "leiser",
    "guadn": "guten",
    "guatn": "guten",
    "mogn": "morgen",
    "nocht": "nacht",
    "danke scheen": "dankeschön",
}

import re as _re

def _normalize_dialect(text):
    """Korrigiert typische Whisper-Fehltranskriptionen bei oesterreichischem Dialekt."""
    if not text:
        return text
    original = text
    # Wort-fuer-Wort Ersetzung (case-insensitive, ganze Woerter)
    for wrong, correct in _DIALECT_WORD_MAP.items():
        pattern = _re.compile(r'\b' + _re.escape(wrong) + r'\b', _re.IGNORECASE)
        text = pattern.sub(correct, text)
    if text != original:
        logger.info("Dialekt-Normalisierung: '%s' -> '%s'", original, text)
    return text


# ------------------------------------------------------------------
# Voice chat — STT (Whisper) -> Jarvis -> TTS (Piper)
# ------------------------------------------------------------------

@chat_bp.route("/api/chat/voice", methods=["POST"])
def api_chat_voice():
    """
    Voice message: receive audio, transcribe via Whisper STT,
    send text to Jarvis, synthesize response via Piper TTS.

    Request: multipart/form-data with 'audio' file
    Optional form fields: person, room
    Response: JSON with text response + base64-encoded TTS audio
    """
    import base64

    if "audio" not in request.files:
        return jsonify({"error": "Keine Audiodatei angegeben"}), 400

    audio_file = request.files["audio"]
    if not audio_file:
        return jsonify({"error": "Leere Audiodatei"}), 400

    person = request.form.get("person", get_setting("primary_user", "User"))
    room = request.form.get("room")
    ha = _deps.get("ha")
    if not ha:
        return jsonify({"error": "Home Assistant nicht verbunden"}), 503

    # --- Step 1: STT via Whisper ---
    stt_entity = get_setting("stt_entity", "")
    if not stt_entity:
        # Auto-discover STT entity
        states = ha.get_states() or []
        stt_entities = [s["entity_id"] for s in states if s.get("entity_id", "").startswith("stt.")]
        if stt_entities:
            stt_entity = stt_entities[0]
        else:
            return jsonify({"error": "Kein STT-Entity gefunden. Bitte in Einstellungen konfigurieren."}), 503

    # Send audio to HA STT API
    audio_data = audio_file.read()
    content_type = audio_file.content_type or "audio/wav"

    # Convert non-WAV audio (e.g. webm from browser) to WAV for Whisper STT
    # HA STT API requires 16kHz mono 16-bit PCM WAV
    # Pipe-basiert: kein Temp-File auf Disk, ~50% schneller
    if content_type != "audio/wav":
        import subprocess
        try:
            result = subprocess.run(
                ["ffmpeg", "-i", "pipe:0", "-ar", "16000", "-ac", "1",
                 "-sample_fmt", "s16", "-f", "wav", "pipe:1",
                 "-loglevel", "error"],
                input=audio_data, capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                audio_data = result.stdout
                content_type = "audio/wav"
                logger.debug("Audio converted to WAV via pipe (%d bytes)", len(audio_data))
            else:
                logger.warning("ffmpeg conversion failed: %s", result.stderr.decode()[:200])
        except Exception as e:
            logger.warning("Audio conversion error: %s", e)

    # HA STT API erwartet X-Speech-Content Header mit Audio-Metadaten
    # Ohne diesen Header gibt HA HTTP 400 "Missing X-Speech-Content header" zurueck
    stt_language = get_setting("language", "de")
    if content_type == "audio/wav":
        x_speech = f"format=wav; codec=pcm; sample_rate=16000; bit_rate=16; channel=1; language={stt_language}"
    else:
        x_speech = f"format=ogg; codec=opus; sample_rate=16000; bit_rate=16; channel=1; language={stt_language}"

    try:
        import os
        ha_url = os.environ.get("SUPERVISOR_URL", ha.ha_url).rstrip("/")
        ha_token = os.environ.get("SUPERVISOR_TOKEN", ha.token)
        # HA STT API erwartet Platform-Name ohne Domain-Prefix (gecacht)
        if stt_entity in _stt_platform_cache:
            stt_platform = _stt_platform_cache[stt_entity]
        else:
            stt_platform = stt_entity.removeprefix("stt.")
            stt_state = ha.get_state(stt_entity) if hasattr(ha, "get_state") else None
            if stt_state and isinstance(stt_state, dict):
                attrs = stt_state.get("attributes", {})
                if attrs.get("platform"):
                    stt_platform = attrs["platform"]
            _stt_platform_cache[stt_entity] = stt_platform

        stt_headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": content_type,
            "X-Speech-Content": x_speech,
        }

        logger.info("STT request: entity=%s, platform=%s, X-Speech-Content=%s, url=%s/api/stt/%s",
                     stt_entity, stt_platform, x_speech, ha_url, stt_platform)

        stt_resp = requests.post(
            f"{ha_url}/api/stt/{stt_platform}",
            headers=stt_headers,
            data=audio_data,
            timeout=30,
        )

        # Fallback: Bei 404 mit vollem Entity-ID versuchen (neuere HA-Versionen)
        if stt_resp.status_code == 404 and stt_platform != stt_entity:
            logger.info("STT 404 mit platform='%s', versuche mit vollem Entity-ID '%s'",
                        stt_platform, stt_entity)
            stt_resp = requests.post(
                f"{ha_url}/api/stt/{stt_entity}",
                headers=stt_headers,
                data=audio_data,
                timeout=30,
            )
            if stt_resp.status_code == 200:
                _stt_platform_cache[stt_entity] = stt_entity

        # Fallback 2: Bei 404 "wyoming" als Platform versuchen (häufigster STT-Provider)
        if stt_resp.status_code == 404 and stt_platform != "wyoming":
            logger.info("STT 404, versuche Fallback platform='wyoming'")
            stt_resp = requests.post(
                f"{ha_url}/api/stt/wyoming",
                headers=stt_headers,
                data=audio_data,
                timeout=30,
            )
            if stt_resp.status_code == 200:
                _stt_platform_cache[stt_entity] = "wyoming"

        if stt_resp.status_code != 200:
            logger.warning("STT API error: %s %s (entity=%s, platform=%s, url=%s)",
                           stt_resp.status_code, stt_resp.text[:200], stt_entity, stt_platform, ha_url)
            return jsonify({"error": f"STT fehlgeschlagen (HTTP {stt_resp.status_code})"}), 502

        stt_result = stt_resp.json()
        transcribed_text = stt_result.get("text", "").strip()
        if not transcribed_text:
            return jsonify({"error": "Sprache nicht erkannt", "stt_result": stt_result}), 422

        # Dialekt-Normalisierung (oesterreichisch/sueddeutsch)
        transcribed_text = _normalize_dialect(transcribed_text)

    except requests.Timeout:
        return jsonify({"error": "STT Timeout"}), 504
    except Exception as e:
        logger.error("STT exception: %s", e)
        return jsonify({"error": "Operation failed"}), 500

    logger.info("STT transcribed: '%s' (person=%s)", transcribed_text, person)

    # --- Step 2: Send text to Jarvis (same as /api/chat/send) ---
    user_msg = {
        "role": "user",
        "text": transcribed_text,
        "person": person,
        "input_mode": "voice",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with _history_lock:
        _conversation_history.append(user_msg)

    assistant_url = _get_assistant_url()
    try:
        resp = requests.post(
            f"{assistant_url}/api/assistant/chat",
            json={"text": transcribed_text, "person": person, "room": room},
            headers=_assistant_headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return jsonify({
                "error": f"Assistant returned {resp.status_code}",
                "transcribed_text": transcribed_text,
            }), 502
        result = resp.json()
        response_text = result.get("response", "")

        assistant_msg = {
            "role": "assistant",
            "text": response_text,
            "actions": result.get("actions", []),
            "model_used": result.get("model_used", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with _history_lock:
            _conversation_history.append(assistant_msg)
            while len(_conversation_history) > MAX_HISTORY:
                _conversation_history.pop(0)

        # Log voice actions for transparency
        _log_jarvis_actions(result.get("actions", []), transcribed_text, response_text)

    except Exception as e:
        logger.error("Voice chat assistant error: %s", e)
        return jsonify({"error": "Operation failed", "transcribed_text": transcribed_text}), 500

    # --- Step 3: TTS Audio generieren ---
    tts_audio_b64 = None
    tts_entity = get_setting("tts_entity", "")
    if not tts_entity:
        states = ha.get_states() or []
        tts_entities = [s["entity_id"] for s in states if s.get("entity_id", "").startswith("tts.")]
        if tts_entities:
            tts_entity = tts_entities[0]

    if tts_entity and response_text:
        try:
            import os
            ha_url = os.environ.get("SUPERVISOR_URL", ha.ha_url).rstrip("/")
            ha_token = os.environ.get("SUPERVISOR_TOKEN", ha.token)
            tts_headers = {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            }

            # Gecachte Engine-ID + Sprache verwenden (spart bis zu 10 HTTP-Requests)
            cached = _tts_engine_cache.get(tts_entity)
            if cached:
                cid, lang = cached
                tts_resp = requests.post(
                    f"{ha_url}/api/tts_get_url",
                    headers=tts_headers,
                    json={"engine_id": cid, "message": response_text, "language": lang},
                    timeout=15,
                )
                if tts_resp.status_code != 200:
                    logger.info("TTS cache miss (engine=%s, lang=%s), re-discovering", cid, lang)
                    _tts_engine_cache.pop(tts_entity, None)
                    cached = None

            if not cached:
                # Engine-Discovery: Platform-Name aus Entity-Attributen lesen
                engine_id = tts_entity.removeprefix("tts.")
                tts_state = ha.get_state(tts_entity)
                if tts_state and isinstance(tts_state, dict):
                    attrs = tts_state.get("attributes") or {}
                    engine_id = attrs.get("platform", engine_id)

                candidate_ids = list(dict.fromkeys([
                    engine_id,
                    tts_entity.removeprefix("tts."),
                    "wyoming",
                    "cloud",
                    "google_translate",
                ]))

                tts_resp = None
                cid = None
                for cid in candidate_ids:
                    for lang in ("de", "de_DE"):
                        tts_resp = requests.post(
                            f"{ha_url}/api/tts_get_url",
                            headers=tts_headers,
                            json={"engine_id": cid, "message": response_text, "language": lang},
                            timeout=15,
                        )
                        if tts_resp.status_code == 200:
                            _tts_engine_cache[tts_entity] = (cid, lang)
                            logger.info("TTS engine discovered and cached: %s/%s", cid, lang)
                            break
                        logger.debug("TTS tts_get_url failed (engine=%s, lang=%s): %s – %s",
                                     cid, lang, tts_resp.status_code, tts_resp.text[:200])
                    if tts_resp and tts_resp.status_code == 200:
                        break

            if tts_resp and tts_resp.status_code == 200:
                tts_data = tts_resp.json()
                tts_url = tts_data.get("url") or tts_data.get("path", "")
                if tts_url:
                    audio_resp = requests.get(
                        tts_url if tts_url.startswith("http") else f"{ha_url}{tts_url}",
                        headers={"Authorization": f"Bearer {ha_token}"},
                        timeout=15,
                    )
                    if audio_resp.status_code == 200:
                        tts_audio_b64 = base64.b64encode(audio_resp.content).decode("utf-8")
                        logger.info("TTS audio generated (%d bytes, engine=%s)", len(audio_resp.content), cid)
                    else:
                        logger.warning("TTS audio download failed: %s", audio_resp.status_code)
            else:
                body = tts_resp.text[:500] if tts_resp else "no response"
                logger.warning("HA TTS unavailable (%s), trying gTTS fallback. (entity=%s, tried=%s)",
                               tts_resp.status_code if tts_resp else "?", tts_entity, candidate_ids)
        except Exception as e:
            logger.warning("HA TTS failed: %s – trying gTTS fallback", e)

    # --- Fallback: gTTS (Google Text-to-Speech) direkt ---
    if not tts_audio_b64 and response_text:
        try:
            from gtts import gTTS
            import io
            tts_obj = gTTS(text=response_text, lang="de")
            audio_buf = io.BytesIO()
            tts_obj.write_to_fp(audio_buf)
            audio_buf.seek(0)
            tts_audio_b64 = base64.b64encode(audio_buf.read()).decode("utf-8")
            logger.info("TTS audio via gTTS fallback generated (%d bytes)", len(audio_buf.getvalue()))
        except Exception as e:
            logger.warning("gTTS fallback also failed: %s", e)

    return jsonify({
        "transcribed_text": transcribed_text,
        "response": response_text,
        "actions": result.get("actions", []),
        "model_used": result.get("model_used", ""),
        "tts_audio": tts_audio_b64,
        "timestamp": assistant_msg["timestamp"],
    })


@chat_bp.route("/api/chat/voice/settings", methods=["GET"])
def api_chat_voice_settings():
    """Get voice settings (STT/TTS entity configuration)."""
    ha = _deps.get("ha")
    stt_entity = get_setting("stt_entity", "")
    tts_entity = get_setting("tts_entity", "")

    # Discover available entities
    available_stt = []
    available_tts = []
    if ha:
        states = ha.get_states() or []
        available_stt = [s["entity_id"] for s in states if s.get("entity_id", "").startswith("stt.")]
        available_tts = [s["entity_id"] for s in states if s.get("entity_id", "").startswith("tts.")]

    return jsonify({
        "stt_entity": stt_entity,
        "tts_entity": tts_entity,
        "available_stt": available_stt,
        "available_tts": available_tts,
    })


@chat_bp.route("/api/chat/voice/settings", methods=["PUT"])
def api_chat_voice_settings_update():
    """Update voice settings."""
    from helpers import set_setting
    data = request.get_json(silent=True) or {}
    updated = []
    if "stt_entity" in data:
        set_setting("stt_entity", data["stt_entity"])
        updated.append("stt_entity")
    if "tts_entity" in data:
        set_setting("tts_entity", data["tts_entity"])
        updated.append("tts_entity")
    return jsonify({"success": True, "updated": updated})


@chat_bp.route("/api/chat/files/<path:filename>", methods=["GET"])
def api_chat_serve_file(filename):
    """Proxy file serving from the Assistant (PC 2)."""
    assistant_url = _get_assistant_url()
    try:
        resp = requests.get(
            f"{assistant_url}/api/assistant/chat/files/{filename}",
            headers=_assistant_headers(),
            timeout=30,
            stream=True,
        )
        if resp.status_code == 200:
            return Response(
                resp.iter_content(chunk_size=8192),
                content_type=resp.headers.get("content-type", "application/octet-stream"),
                headers={
                    "Content-Disposition": resp.headers.get("content-disposition", ""),
                    "Cache-Control": "public, max-age=86400",
                },
            )
        return jsonify({"error": "Datei nicht gefunden"}), 404
    except Exception as e:
        logger.warning("File proxy error: %s", e)
        return jsonify({"error": "Datei konnte nicht geladen werden"}), 502
