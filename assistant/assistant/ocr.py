"""
MindHome Assistant - OCR & Bild-Analyse (Phase 14.2)
Tesseract-OCR fuer Text-Extraktion aus Bildern,
optionales Vision-LLM fuer Bild-Beschreibung via Ollama.
"""

import base64
import io
import logging
from pathlib import Path
from typing import Optional

from .config import yaml_config

logger = logging.getLogger("mindhome-assistant.ocr")

# ── Tesseract availability (lazy check) ──────────────────────────

_tesseract_available: Optional[bool] = None


def _check_tesseract() -> bool:
    """Prueft ob Tesseract OCR installiert ist."""
    global _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        _tesseract_available = True
        logger.info("Tesseract OCR verfuegbar (Version: %s)", version)
    except Exception:
        _tesseract_available = False
        logger.info("Tesseract OCR nicht installiert — OCR deaktiviert")
    return _tesseract_available


# ── Standalone OCR function (used by file_handler) ───────────────

MAX_OCR_CHARS = 4000


def extract_text_from_image(
    image_path: Path,
    languages: str = "deu+eng",
) -> Optional[str]:
    """
    Extrahiert Text aus einem Bild via Tesseract OCR.

    Args:
        image_path: Pfad zum Bild
        languages: Tesseract Sprachcodes (z.B. "deu+eng")

    Returns:
        Extrahierter Text oder None
    """
    if not _check_tesseract():
        return None

    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(image_path)

        # Convert to RGB if needed
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Upscale small images for better OCR
        min_dimension = 1000
        if min(img.size) < min_dimension:
            scale = min_dimension / min(img.size)
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)

        # Grayscale + contrast enhancement + sharpen
        gray = img.convert("L")
        gray = ImageEnhance.Contrast(gray).enhance(1.5)
        gray = gray.filter(ImageFilter.SHARPEN)

        # Adaptive PSM: Erst PSM 3, bei wenig Ergebnis PSM 6 (einheitlicher Block)
        text = pytesseract.image_to_string(gray, lang=languages, config="--psm 3")
        text = text.strip()

        if len(text) < 10:
            text_psm6 = pytesseract.image_to_string(gray, lang=languages, config="--psm 6")
            text_psm6 = text_psm6.strip()
            if len(text_psm6) > len(text):
                text = text_psm6

        if not text or len(text) < 3:
            return None

        if len(text) > MAX_OCR_CHARS:
            text = text[:MAX_OCR_CHARS] + "\n... (abgeschnitten)"

        logger.info("OCR: %d Zeichen extrahiert aus %s", len(text), image_path.name)
        return text

    except Exception as e:
        logger.warning("OCR fehlgeschlagen fuer %s: %s", image_path.name, e)
        return None


def extract_text_with_confidence(
    image_path: Path,
    languages: str = "deu+eng",
    min_confidence: int = 40,
) -> Optional[dict]:
    """
    Extrahiert Text mit Confidence-Werten pro Wort.

    Args:
        image_path: Pfad zum Bild
        languages: Tesseract Sprachcodes
        min_confidence: Minimaler Confidence-Wert (0-100) fuer ein Wort

    Returns:
        Dict mit text, avg_confidence, word_count, low_confidence_words
        oder None
    """
    if not _check_tesseract():
        return None

    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(image_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        min_dimension = 1000
        if min(img.size) < min_dimension:
            scale = min_dimension / min(img.size)
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)

        gray = img.convert("L")
        gray = ImageEnhance.Contrast(gray).enhance(1.5)
        gray = gray.filter(ImageFilter.SHARPEN)

        # Tesseract data output mit Confidence pro Wort
        data = pytesseract.image_to_data(
            gray, lang=languages, config="--psm 3",
            output_type=pytesseract.Output.DICT,
        )

        words = []
        confidences = []
        low_conf_words = []

        for i, text in enumerate(data.get("text", [])):
            text = text.strip()
            if not text:
                continue
            conf = int(data["conf"][i])
            if conf < 0:
                continue  # Tesseract gibt -1 fuer leere Felder

            words.append(text)
            confidences.append(conf)

            if conf < min_confidence:
                low_conf_words.append({"word": text, "confidence": conf})

        if not words:
            return None

        full_text = " ".join(words)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        if len(full_text) > MAX_OCR_CHARS:
            full_text = full_text[:MAX_OCR_CHARS] + " ..."

        return {
            "text": full_text,
            "avg_confidence": round(avg_confidence, 1),
            "word_count": len(words),
            "low_confidence_words": low_conf_words[:10],  # Max 10
        }

    except Exception as e:
        logger.warning("OCR Confidence-Analyse fehlgeschlagen: %s", e)
        return None


# ── OCR Engine (full, initialized by brain.py) ───────────────────

class OCREngine:
    """
    Phase 14.2: Multi-Modal OCR & Bild-Analyse Engine.

    Kombiniert Tesseract-OCR (Text-Extraktion) mit optionalem
    Vision-LLM (Bild-Beschreibung via Ollama) fuer umfassende
    Bild-Analyse.
    """

    def __init__(self, ollama_client=None):
        cfg = yaml_config.get("ocr", {})
        self.enabled = cfg.get("enabled", True)
        self.languages = cfg.get("languages", "deu+eng")
        self.vision_model = cfg.get("vision_model", "")
        self.max_image_size_mb = cfg.get("max_image_size_mb", 20)
        self.description_max_tokens = cfg.get("description_max_tokens", 512)
        self._ollama = ollama_client
        self._redis = None
        self._vision_available = False

    async def initialize(self, redis_client=None):
        """Initialisiert OCR Engine und prueft verfuegbare Backends."""
        self._redis = redis_client

        tesseract_ok = _check_tesseract()

        # Check Vision-LLM availability
        if self.vision_model and self._ollama:
            try:
                models = await self._ollama.list_models()
                self._vision_available = any(
                    self.vision_model in m for m in models
                )
                if self._vision_available:
                    logger.info("Vision-LLM verfuegbar: %s", self.vision_model)
                else:
                    logger.info(
                        "Vision-LLM '%s' nicht gefunden — Bild-Beschreibung deaktiviert",
                        self.vision_model,
                    )
            except Exception as e:
                logger.warning("Vision-LLM Check fehlgeschlagen: %s", e)

        logger.info(
            "OCR Engine initialisiert (Tesseract: %s, Vision-LLM: %s)",
            "OK" if tesseract_ok else "nicht verfuegbar",
            self.vision_model if self._vision_available else "deaktiviert",
        )

    def extract_text(self, image_path: Path) -> Optional[str]:
        """Extrahiert Text aus einem Bild via Tesseract."""
        if not self.enabled:
            return None
        return extract_text_from_image(image_path, self.languages)

    async def describe_image(
        self, file_info: dict, user_context: str = ""
    ) -> Optional[str]:
        """
        Beschreibt ein Bild via Vision-LLM (Ollama).

        Args:
            file_info: Datei-Metadaten aus save_upload()
            user_context: Optionaler Kontext vom User

        Returns:
            Bild-Beschreibung oder None
        """
        if not self.enabled or not self._vision_available or not self._ollama:
            return None

        try:
            from .file_handler import get_file_path

            image_path = get_file_path(file_info.get("unique_name", ""))
            if not image_path:
                return None

            # Check file size
            size_mb = image_path.stat().st_size / (1024 * 1024)
            if size_mb > self.max_image_size_mb:
                logger.warning(
                    "Bild zu gross fuer Vision-LLM: %.1f MB (max: %d MB)",
                    size_mb,
                    self.max_image_size_mb,
                )
                return None

            # Check Redis cache
            cache_key = f"mha:ocr:vision:{file_info.get('unique_name', '')}"
            if self._redis:
                cached = await self._redis.get(cache_key)
                if cached:
                    logger.debug("Vision-LLM Cache Hit: %s", file_info.get("name"))
                    return cached if isinstance(cached, str) else cached.decode("utf-8")

            # Prepare image for API
            image_b64 = self._prepare_image_b64(image_path)
            if not image_b64:
                return None

            # Build prompt
            prompt = "Beschreibe dieses Bild ausfuehrlich auf Deutsch. "
            if user_context:
                prompt += f"Der Benutzer fragt: '{user_context}'. Beziehe dich darauf."
            else:
                prompt += "Was ist zu sehen? Gibt es Text im Bild?"

            # Send to Vision-LLM
            result = await self._ollama.chat(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64],
                    }
                ],
                model=self.vision_model,
                temperature=0.3,
                max_tokens=self.description_max_tokens,
                think=False,
            )

            if "error" in result:
                logger.warning("Vision-LLM Fehler: %s", result["error"])
                return None

            description = result.get("message", {}).get("content", "").strip()
            if not description:
                return None

            logger.info(
                "Vision-LLM: %d Zeichen Beschreibung fuer %s",
                len(description),
                file_info.get("name", "Bild"),
            )

            # Cache result (24h TTL)
            if self._redis:
                await self._redis.set(cache_key, description, ex=86400)

            return description

        except Exception as e:
            logger.warning("Vision-LLM Analyse fehlgeschlagen: %s", e)
            return None

    def _prepare_image_b64(self, image_path: Path) -> Optional[str]:
        """Bereitet ein Bild fuer die Vision-LLM API vor (Base64-JPEG)."""
        try:
            from PIL import Image

            img = Image.open(image_path)

            # Resize if too large (max 1024px longest side)
            max_side = 1024
            if max(img.size) > max_side:
                ratio = max_side / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            # Remove alpha channel
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Encode as JPEG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

        except Exception as e:
            logger.warning("Bild-Vorbereitung fehlgeschlagen: %s", e)
            return None

    async def analyze_image(
        self, file_info: dict, user_context: str = ""
    ) -> dict:
        """
        Komplette Bild-Analyse: OCR + Vision-LLM.

        Returns:
            Dict mit ocr_text, description, has_text, ocr_confidence
        """
        result = {
            "ocr_text": None, "description": None,
            "has_text": False, "ocr_confidence": None,
        }

        if not self.enabled:
            return result

        # 1. Tesseract OCR (mit Confidence wenn moeglich)
        from .file_handler import get_file_path

        image_path = get_file_path(file_info.get("unique_name", ""))
        if image_path:
            # Erst Confidence-Version versuchen
            conf_result = extract_text_with_confidence(image_path, self.languages)
            if conf_result:
                result["ocr_text"] = conf_result["text"]
                result["has_text"] = True
                result["ocr_confidence"] = conf_result["avg_confidence"]
            else:
                # Fallback auf einfache Version
                ocr_text = self.extract_text(image_path)
                if ocr_text:
                    result["ocr_text"] = ocr_text
                    result["has_text"] = True

        # 2. Vision-LLM (if available)
        description = await self.describe_image(file_info, user_context)
        if description:
            result["description"] = description

        return result

    def health_status(self) -> str:
        """Status-String fuer Health Check."""
        if not self.enabled:
            return "disabled"
        parts = []
        if _tesseract_available:
            parts.append(f"tesseract({self.languages})")
        if self._vision_available:
            parts.append(f"vision({self.vision_model})")
        return f"active ({', '.join(parts)})" if parts else "active (no backends)"
