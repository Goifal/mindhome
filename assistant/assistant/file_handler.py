"""
MindHome Assistant - File Handler
Verarbeitet hochgeladene Dateien: Speicherung, Text-Extraktion, Metadaten.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mindhome-assistant.file_handler")

# Upload configuration
UPLOAD_DIR = Path("/app/data/uploads")
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

# Max chars to extract from documents for the LLM prompt
MAX_EXTRACT_CHARS = 4000


def ensure_upload_dir():
    """Create upload directory if it doesn't exist."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def allowed_file(filename: str) -> bool:
    """Check if the file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_type(filename: str) -> str:
    """Get the file type category from filename."""
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    return FILE_TYPE_MAP.get(ext, "document")


def save_upload(filename: str, content: bytes) -> dict:
    """
    Save an uploaded file and return metadata.

    Returns:
        dict with name, unique_name, type, ext, size, path, url, extracted_text
    """
    ensure_upload_dir()

    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    if not safe_name or "." not in safe_name:
        safe_name = "upload.bin"

    ext = safe_name.rsplit(".", 1)[1].lower() if "." in safe_name else ""
    unique_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    dest = UPLOAD_DIR / unique_name

    dest.write_bytes(content)

    file_type = FILE_TYPE_MAP.get(ext, "document")
    extracted_text = _extract_text(dest, ext)

    logger.info("File saved: %s (%s, %d bytes, extracted: %d chars)",
                safe_name, file_type, len(content),
                len(extracted_text) if extracted_text else 0)

    return {
        "name": safe_name,
        "unique_name": unique_name,
        "type": file_type,
        "ext": ext,
        "size": len(content),
        "url": f"api/assistant/chat/files/{unique_name}",
        "extracted_text": extracted_text,
    }


def get_file_path(unique_name: str) -> Optional[Path]:
    """Get the full path for a stored file, or None if not found."""
    # Sanitize to prevent path traversal
    safe = os.path.basename(unique_name)
    path = UPLOAD_DIR / safe
    if path.is_file():
        return path
    return None


def _extract_text(path: Path, ext: str) -> Optional[str]:
    """Extract text content from supported document types."""
    try:
        if ext == "txt":
            return _read_text(path)
        elif ext == "csv":
            return _read_text(path)
        elif ext in ("json", "xml"):
            return _read_text(path)
        elif ext == "pdf":
            return _extract_pdf(path)
        elif ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
            return _extract_ocr(path)
    except Exception as e:
        logger.warning("Text extraction failed for %s: %s", path.name, e)
    return None


def _extract_ocr(path: Path) -> Optional[str]:
    """Extract text from image using Tesseract OCR (Phase 14.2)."""
    try:
        from .ocr import extract_text_from_image
        return extract_text_from_image(path)
    except ImportError:
        logger.debug("OCR module not available — skipping image text extraction")
        return None


def _read_text(path: Path) -> Optional[str]:
    """Read a text file with size limit."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_EXTRACT_CHARS:
            text = text[:MAX_EXTRACT_CHARS] + "\n... (abgeschnitten)"
        return text.strip() or None
    except Exception:
        return None


def _extract_pdf(path: Path) -> Optional[str]:
    """Extract text from PDF using pdfplumber (if available)."""
    try:
        import pdfplumber
    except ImportError:
        logger.debug("pdfplumber not installed — skipping PDF extraction")
        return None

    text_parts = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= 20:  # Max 20 pages
                text_parts.append("... (weitere Seiten abgeschnitten)")
                break
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    full_text = "\n\n".join(text_parts)
    if len(full_text) > MAX_EXTRACT_CHARS:
        full_text = full_text[:MAX_EXTRACT_CHARS] + "\n... (abgeschnitten)"
    return full_text.strip() or None


def build_file_context(files: list[dict]) -> str:
    """
    Build a prompt context string for uploaded files.

    Args:
        files: List of file metadata dicts (from save_upload or chat history)

    Returns:
        Prompt string describing the uploaded files
    """
    if not files:
        return ""

    parts = ["\nHOCHGELADENE DATEIEN:"]
    for f in files:
        file_type = f.get("type", "document")
        name = f.get("name", "unbekannt")
        size = f.get("size", 0)
        size_str = f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"

        parts.append(f"- {name} ({file_type}, {size_str})")

        extracted = f.get("extracted_text")
        vision_desc = f.get("vision_description")

        if extracted and file_type == "image":
            parts.append(f"  OCR-Text (per Texterkennung):\n  ---\n  {extracted}\n  ---")
        elif extracted:
            parts.append(f"  Inhalt:\n  ---\n  {extracted}\n  ---")

        if vision_desc:
            parts.append(f"  Bild-Analyse (Vision-LLM):\n  ---\n  {vision_desc}\n  ---")
        elif file_type == "image" and not extracted:
            parts.append("  (Bild — kein Text erkannt)")
        elif file_type == "video":
            parts.append("  (Video — kein Text-Inhalt extrahierbar)")
        elif file_type == "audio":
            parts.append("  (Audio — kein Text-Inhalt extrahierbar)")

    parts.append("")
    parts.append("Beziehe dich auf die Dateien in deiner Antwort. "
                 "Bei Dokumenten mit extrahiertem Text, beantworte Fragen basierend auf dem Inhalt. "
                 "Bei Bildern mit OCR-Text oder Bild-Analyse, nutze diese Informationen fuer deine Antwort. "
                 "Bei Bildern/Videos/Audio ohne Analyse, bestatige den Empfang und beschreibe was du weisst (Dateiname, Typ, Groesse).")

    return "\n".join(parts)
