# MindHome - routes/chat.py | see version.py for version info
"""
MindHome API Routes - Jarvis Chat
Proxies chat messages to the MindHome Assistant (PC 2) and stores conversation history.
Supports file uploads (images, videos, documents) in chat.
"""

import logging
import os
import time
import uuid
import requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

from helpers import get_setting, set_setting

logger = logging.getLogger("mindhome.routes.chat")

chat_bp = Blueprint("chat", __name__)

# Module-level dependencies
_deps = {}

# In-memory conversation history (persists until addon restart)
_conversation_history = []
MAX_HISTORY = 200

# Upload configuration
UPLOAD_DIR = "/data/mindhome/uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {
    # Images
    "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp",
    # Videos
    "mp4", "webm", "mov", "avi",
    # Documents
    "pdf", "txt", "csv", "json", "xml",
    "doc", "docx", "xls", "xlsx", "pptx",
    # Audio
    "mp3", "wav", "ogg", "m4a",
}
FILE_TYPE_MAP = {
    "jpg": "image", "jpeg": "image", "png": "image", "gif": "image",
    "webp": "image", "svg": "image", "bmp": "image",
    "mp4": "video", "webm": "video", "mov": "video", "avi": "video",
    "mp3": "audio", "wav": "audio", "ogg": "audio", "m4a": "audio",
    "pdf": "document", "txt": "document", "csv": "document",
    "json": "document", "xml": "document",
    "doc": "document", "docx": "document",
    "xls": "document", "xlsx": "document", "pptx": "document",
}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def init_chat(dependencies):
    """Initialize chat routes with shared dependencies."""
    global _deps
    _deps = dependencies
    _ensure_upload_dir()


def _get_assistant_url():
    """Get the assistant URL from settings or environment."""
    import os
    url = get_setting("assistant_url", None)
    if not url:
        url = os.environ.get("ASSISTANT_URL", "http://192.168.1.100:8200")
    return url.rstrip("/")


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

    person = data.get("person", get_setting("primary_user", "Max"))
    room = data.get("room")

    # Store user message
    user_msg = {
        "role": "user",
        "text": text,
        "person": person,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _conversation_history.append(user_msg)

    # Forward to assistant
    assistant_url = _get_assistant_url()
    try:
        resp = requests.post(
            f"{assistant_url}/api/assistant/chat",
            json={"text": text, "person": person, "room": room},
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
            _conversation_history.append(assistant_msg)

            # Trim history
            while len(_conversation_history) > MAX_HISTORY:
                _conversation_history.pop(0)

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
        return jsonify({"error": str(e), "response": None}), 500


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

    total = len(_conversation_history)
    start = max(0, total - offset - limit)
    end = total - offset
    messages = _conversation_history[start:end]

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
    count = len(_conversation_history)
    _conversation_history = []
    return jsonify({"cleared": count})


@chat_bp.route("/api/chat/status", methods=["GET"])
def api_chat_status():
    """Check if the assistant is reachable."""
    assistant_url = _get_assistant_url()
    try:
        resp = requests.get(f"{assistant_url}/api/assistant/health", timeout=5)
        if resp.status_code == 200:
            health = resp.json()
            return jsonify({
                "connected": True,
                "assistant_url": assistant_url,
                "health": health,
            })
        return jsonify({"connected": False, "assistant_url": assistant_url, "error": f"Status {resp.status_code}"})
    except Exception as e:
        return jsonify({"connected": False, "assistant_url": assistant_url, "error": str(e)})


# ------------------------------------------------------------------
# File upload & serving
# ------------------------------------------------------------------

@chat_bp.route("/api/chat/upload", methods=["POST"])
def api_chat_upload():
    """
    Upload a file in the chat.

    Accepts multipart/form-data with field 'file'.
    Stores in /data/mindhome/uploads/ with a unique name.
    Returns file metadata + URL for display.
    """
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei angegeben"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Keine Datei ausgewählt"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": "Dateityp nicht erlaubt"}), 400

    # Check file size (read into memory, enforce limit)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        mb = MAX_FILE_SIZE // (1024 * 1024)
        return jsonify({"error": f"Datei zu groß (max {mb} MB)"}), 413

    # Generate unique filename
    orig = secure_filename(file.filename)
    ext = orig.rsplit(".", 1)[1].lower() if "." in orig else ""
    unique_name = f"{uuid.uuid4().hex[:12]}_{orig}"

    _ensure_upload_dir()
    dest = os.path.join(UPLOAD_DIR, unique_name)
    file.save(dest)

    file_type = FILE_TYPE_MAP.get(ext, "document")
    url = f"api/chat/files/{unique_name}"

    # Store as chat message
    person = request.form.get("person", get_setting("primary_user", "Max"))
    caption = request.form.get("caption", "").strip()

    user_msg = {
        "role": "user",
        "text": caption,
        "person": person,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file": {
            "name": orig,
            "url": url,
            "type": file_type,
            "size": size,
            "ext": ext,
        },
    }
    _conversation_history.append(user_msg)

    while len(_conversation_history) > MAX_HISTORY:
        _conversation_history.pop(0)

    logger.info("Chat file uploaded: %s (%s, %d bytes)", orig, file_type, size)

    return jsonify({
        "file": user_msg["file"],
        "timestamp": user_msg["timestamp"],
    })


@chat_bp.route("/api/chat/files/<path:filename>", methods=["GET"])
def api_chat_serve_file(filename):
    """Serve an uploaded chat file."""
    safe = secure_filename(filename)
    if not safe or not os.path.isfile(os.path.join(UPLOAD_DIR, safe)):
        return jsonify({"error": "Datei nicht gefunden"}), 404
    return send_from_directory(UPLOAD_DIR, safe)
