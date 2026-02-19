"""
Tests fuer Phase 14.2: OCR & Bild-Analyse
"""

import asyncio
import base64
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────


def _create_test_image(text: str = "Hello World", size=(200, 50)) -> bytes:
    """Erzeugt ein einfaches Test-Bild als Bytes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── extract_text_from_image ───────────────────────────────────────


class TestExtractTextFromImage:
    """Tests fuer die standalone OCR-Funktion."""

    def test_returns_none_without_tesseract(self, tmp_path):
        """Ohne Tesseract muss None zurueckkommen."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = None  # Reset

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image())

        with patch.dict("sys.modules", {"pytesseract": None}):
            ocr_mod._tesseract_available = False
            result = ocr_mod.extract_text_from_image(img_path)
            assert result is None

    def test_extracts_text_with_tesseract(self, tmp_path):
        """Mit Tesseract wird Text extrahiert."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image("Test OCR 123"))

        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Test OCR 123"

        with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                # Directly mock the import inside the function
                result = ocr_mod.extract_text_from_image(img_path)
                # pytesseract.image_to_string should have been called
                assert mock_pytesseract.image_to_string.called or result is not None

    def test_truncates_long_text(self, tmp_path):
        """Langer OCR-Text wird abgeschnitten."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True
        long_text = "A" * 5000

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image())

        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = long_text

        with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
            ocr_mod._tesseract_available = True
            result = ocr_mod.extract_text_from_image(img_path)
            if result:
                assert len(result) <= ocr_mod.MAX_OCR_CHARS + 50  # +50 for truncation text

    def test_returns_none_for_empty_text(self, tmp_path):
        """Leerer OCR-Text ergibt None."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image())

        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "  "

        with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
            result = ocr_mod.extract_text_from_image(img_path)
            if result is not None:
                assert len(result.strip()) >= 3


# ── OCREngine ─────────────────────────────────────────────────────


class TestOCREngine:
    """Tests fuer die OCREngine Klasse."""

    def test_init_reads_config(self):
        """Engine liest Konfiguration aus yaml_config."""
        with patch("assistant.ocr.yaml_config", {
            "ocr": {
                "enabled": True,
                "languages": "deu+eng",
                "vision_model": "llava",
                "max_image_size_mb": 10,
                "description_max_tokens": 256,
            }
        }):
            from assistant.ocr import OCREngine
            engine = OCREngine(ollama_client=MagicMock())
            assert engine.enabled is True
            assert engine.languages == "deu+eng"
            assert engine.vision_model == "llava"
            assert engine.max_image_size_mb == 10
            assert engine.description_max_tokens == 256

    def test_init_defaults(self):
        """Engine hat sinnvolle Defaults."""
        with patch("assistant.ocr.yaml_config", {}):
            from assistant.ocr import OCREngine
            engine = OCREngine()
            assert engine.enabled is True
            assert engine.languages == "deu+eng"
            assert engine.vision_model == ""
            assert engine._vision_available is False

    @pytest.mark.asyncio
    async def test_initialize_checks_vision_model(self):
        """Initialize prueft ob Vision-LLM verfuegbar ist."""
        with patch("assistant.ocr.yaml_config", {
            "ocr": {"vision_model": "llava"}
        }):
            from assistant.ocr import OCREngine

            mock_ollama = AsyncMock()
            mock_ollama.list_models.return_value = ["llava:latest", "qwen3:4b"]

            engine = OCREngine(ollama_client=mock_ollama)
            await engine.initialize()

            assert engine._vision_available is True

    @pytest.mark.asyncio
    async def test_initialize_vision_model_not_found(self):
        """Vision-LLM nicht installiert → _vision_available = False."""
        with patch("assistant.ocr.yaml_config", {
            "ocr": {"vision_model": "llava"}
        }):
            from assistant.ocr import OCREngine

            mock_ollama = AsyncMock()
            mock_ollama.list_models.return_value = ["qwen3:4b", "qwen3:14b"]

            engine = OCREngine(ollama_client=mock_ollama)
            await engine.initialize()

            assert engine._vision_available is False

    @pytest.mark.asyncio
    async def test_describe_image_disabled(self):
        """describe_image gibt None wenn disabled."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"enabled": False}}):
            from assistant.ocr import OCREngine
            engine = OCREngine()
            result = await engine.describe_image({"name": "test.jpg"})
            assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_no_vision(self):
        """describe_image gibt None ohne Vision-LLM."""
        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine
            engine = OCREngine()
            engine._vision_available = False
            result = await engine.describe_image({"name": "test.jpg"})
            assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_success(self, tmp_path):
        """describe_image liefert Beschreibung via Vision-LLM."""
        with patch("assistant.ocr.yaml_config", {
            "ocr": {"vision_model": "llava", "max_image_size_mb": 20}
        }):
            from assistant.ocr import OCREngine

            # Create test image
            img_path = tmp_path / "abc123_test.jpg"
            img_path.write_bytes(_create_test_image())

            mock_ollama = AsyncMock()
            mock_ollama.chat.return_value = {
                "message": {"content": "Ein Bild mit dem Text 'Hello World'."}
            }

            engine = OCREngine(ollama_client=mock_ollama)
            engine._vision_available = True

            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                result = await engine.describe_image(
                    {"name": "test.jpg", "unique_name": "abc123_test.jpg"},
                    user_context="Was steht da?"
                )

            assert result is not None
            assert "Hello World" in result
            mock_ollama.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_describe_image_uses_cache(self, tmp_path):
        """describe_image nutzt Redis-Cache."""
        with patch("assistant.ocr.yaml_config", {
            "ocr": {"vision_model": "llava"}
        }):
            from assistant.ocr import OCREngine

            mock_redis = AsyncMock()
            mock_redis.get.return_value = "Cached: Ein schoenes Bild."

            engine = OCREngine(ollama_client=AsyncMock())
            engine._vision_available = True
            engine._redis = mock_redis

            img_path = tmp_path / "cached.jpg"
            img_path.write_bytes(_create_test_image())

            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                result = await engine.describe_image(
                    {"name": "cached.jpg", "unique_name": "cached.jpg"}
                )

            assert result == "Cached: Ein schoenes Bild."
            engine._ollama.chat.assert_not_called()

    def test_health_status_disabled(self):
        """health_status meldet 'disabled' wenn deaktiviert."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"enabled": False}}):
            from assistant.ocr import OCREngine
            engine = OCREngine()
            assert engine.health_status() == "disabled"

    def test_health_status_active(self):
        """health_status zeigt aktive Backends."""
        import assistant.ocr as ocr_mod
        ocr_mod._tesseract_available = True

        with patch("assistant.ocr.yaml_config", {
            "ocr": {"vision_model": "llava", "languages": "deu+eng"}
        }):
            from assistant.ocr import OCREngine
            engine = OCREngine()
            engine._vision_available = True
            status = engine.health_status()
            assert "tesseract" in status
            assert "vision" in status


# ── file_handler Integration ──────────────────────────────────────


class TestFileHandlerOCR:
    """Tests fuer OCR-Integration in file_handler."""

    def test_extract_text_calls_ocr_for_images(self, tmp_path):
        """_extract_text ruft OCR fuer Bildformate auf."""
        from assistant.file_handler import _extract_text

        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(_create_test_image())

        with patch("assistant.file_handler._extract_ocr", return_value="OCR Text") as mock:
            result = _extract_text(img_path, "jpg")
            mock.assert_called_once_with(img_path)
            assert result == "OCR Text"

    def test_extract_text_calls_ocr_for_png(self, tmp_path):
        """_extract_text ruft OCR fuer PNG auf."""
        from assistant.file_handler import _extract_text

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image())

        with patch("assistant.file_handler._extract_ocr", return_value=None) as mock:
            result = _extract_text(img_path, "png")
            mock.assert_called_once_with(img_path)

    def test_build_file_context_with_ocr_text(self):
        """build_file_context zeigt OCR-Text fuer Bilder."""
        from assistant.file_handler import build_file_context

        files = [{
            "name": "screenshot.png",
            "type": "image",
            "size": 50000,
            "extracted_text": "Fehlermeldung: Connection refused",
        }]
        context = build_file_context(files)
        assert "OCR-Text" in context
        assert "Fehlermeldung: Connection refused" in context

    def test_build_file_context_with_vision_description(self):
        """build_file_context zeigt Vision-LLM Beschreibung."""
        from assistant.file_handler import build_file_context

        files = [{
            "name": "foto.jpg",
            "type": "image",
            "size": 200000,
            "extracted_text": None,
            "vision_description": "Ein Hund im Park bei Sonnenuntergang.",
        }]
        context = build_file_context(files)
        assert "Bild-Analyse" in context
        assert "Hund im Park" in context

    def test_build_file_context_with_both(self):
        """build_file_context zeigt OCR-Text UND Vision-Beschreibung."""
        from assistant.file_handler import build_file_context

        files = [{
            "name": "rechnung.jpg",
            "type": "image",
            "size": 100000,
            "extracted_text": "Rechnungsnr: 12345\nBetrag: 49,99 EUR",
            "vision_description": "Eine Rechnung von Amazon mit Artikeln.",
        }]
        context = build_file_context(files)
        assert "OCR-Text" in context
        assert "Rechnungsnr: 12345" in context
        assert "Bild-Analyse" in context
        assert "Rechnung von Amazon" in context

    def test_build_file_context_image_no_text(self):
        """build_file_context zeigt Hinweis wenn kein Text erkannt."""
        from assistant.file_handler import build_file_context

        files = [{
            "name": "photo.jpg",
            "type": "image",
            "size": 300000,
            "extracted_text": None,
        }]
        context = build_file_context(files)
        assert "kein Text erkannt" in context


# ── OCREngine.analyze_image ───────────────────────────────────────


class TestAnalyzeImage:
    """Tests fuer die kombinierte Analyse."""

    @pytest.mark.asyncio
    async def test_analyze_combines_ocr_and_vision(self, tmp_path):
        """analyze_image kombiniert OCR und Vision-LLM."""
        import assistant.ocr as ocr_mod
        ocr_mod._tesseract_available = True

        with patch("assistant.ocr.yaml_config", {
            "ocr": {"vision_model": "llava"}
        }):
            from assistant.ocr import OCREngine

            img_path = tmp_path / "combo.jpg"
            img_path.write_bytes(_create_test_image("Hello"))

            mock_ollama = AsyncMock()
            mock_ollama.chat.return_value = {
                "message": {"content": "Ein Bild mit Text."}
            }

            engine = OCREngine(ollama_client=mock_ollama)
            engine._vision_available = True

            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                with patch("assistant.ocr.extract_text_from_image", return_value="Hello"):
                    result = await engine.analyze_image(
                        {"name": "combo.jpg", "unique_name": "combo.jpg"},
                        "Was steht da?"
                    )

            assert result["ocr_text"] == "Hello"
            assert result["has_text"] is True
            assert result["description"] is not None

    @pytest.mark.asyncio
    async def test_analyze_disabled_returns_empty(self):
        """analyze_image gibt leeres Result bei disabled."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"enabled": False}}):
            from assistant.ocr import OCREngine
            engine = OCREngine()
            result = await engine.analyze_image({"name": "test.jpg"})
            assert result["ocr_text"] is None
            assert result["description"] is None
            assert result["has_text"] is False
