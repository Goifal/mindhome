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

    person = request.form.get("person", get_setting("primary_user", "Max"))
    caption = request.form.get("caption", "").strip()

    # Forward to Assistant (PC 2)
    assistant_url = _get_assistant_url()
    try:
        resp = requests.post(
            f"{assistant_url}/api/assistant/chat/upload",
            files={"file": (file.filename, file.stream, file.content_type or "application/octet-stream")},
            data={"caption": caption, "person": person},
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
                _conversation_history.append(assistant_msg)

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
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/api/chat/files/<path:filename>", methods=["GET"])
def api_chat_serve_file(filename):
    """Proxy file serving from the Assistant (PC 2)."""
    assistant_url = _get_assistant_url()
    try:
        resp = requests.get(
            f"{assistant_url}/api/assistant/chat/files/{filename}",
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
