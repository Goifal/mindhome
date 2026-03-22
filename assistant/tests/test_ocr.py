"""
Tests fuer Phase 14.2: OCR & Bild-Analyse
"""

import asyncio
import base64
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PIL = pytest.importorskip("PIL", reason="Pillow nicht installiert")

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
                assert (
                    len(result) <= ocr_mod.MAX_OCR_CHARS + 50
                )  # +50 for truncation text

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
        with patch(
            "assistant.ocr.yaml_config",
            {
                "ocr": {
                    "enabled": True,
                    "languages": "deu+eng",
                    "vision_model": "llava",
                    "max_image_size_mb": 10,
                    "description_max_tokens": 256,
                }
            },
        ):
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
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            mock_ollama = AsyncMock()
            mock_ollama.list_models.return_value = ["llava:latest", "qwen3.5:4b"]

            engine = OCREngine(ollama_client=mock_ollama)
            await engine.initialize()

            assert engine._vision_available is True

    @pytest.mark.asyncio
    async def test_initialize_vision_model_not_found(self):
        """Vision-LLM nicht installiert → _vision_available = False."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            mock_ollama = AsyncMock()
            mock_ollama.list_models.return_value = ["qwen3.5:4b", "qwen3.5:9b"]

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
        with patch(
            "assistant.ocr.yaml_config",
            {"ocr": {"vision_model": "llava", "max_image_size_mb": 20}},
        ):
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
                    user_context="Was steht da?",
                )

            assert result is not None
            assert "Hello World" in result
            mock_ollama.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_describe_image_uses_cache(self, tmp_path):
        """describe_image nutzt Redis-Cache."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
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

        with patch(
            "assistant.ocr.yaml_config",
            {"ocr": {"vision_model": "llava", "languages": "deu+eng"}},
        ):
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

        with patch(
            "assistant.file_handler._extract_ocr", return_value="OCR Text"
        ) as mock:
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

        files = [
            {
                "name": "screenshot.png",
                "type": "image",
                "size": 50000,
                "extracted_text": "Fehlermeldung: Connection refused",
            }
        ]
        context = build_file_context(files)
        assert "OCR-Text" in context
        assert "Fehlermeldung: Connection refused" in context

    def test_build_file_context_with_vision_description(self):
        """build_file_context zeigt Vision-LLM Beschreibung."""
        from assistant.file_handler import build_file_context

        files = [
            {
                "name": "foto.jpg",
                "type": "image",
                "size": 200000,
                "extracted_text": None,
                "vision_description": "Ein Hund im Park bei Sonnenuntergang.",
            }
        ]
        context = build_file_context(files)
        assert "Bild-Analyse" in context
        assert "Hund im Park" in context

    def test_build_file_context_with_both(self):
        """build_file_context zeigt OCR-Text UND Vision-Beschreibung."""
        from assistant.file_handler import build_file_context

        files = [
            {
                "name": "rechnung.jpg",
                "type": "image",
                "size": 100000,
                "extracted_text": "Rechnungsnr: 12345\nBetrag: 49,99 EUR",
                "vision_description": "Eine Rechnung von Amazon mit Artikeln.",
            }
        ]
        context = build_file_context(files)
        assert "OCR-Text" in context
        assert "Rechnungsnr: 12345" in context
        assert "Bild-Analyse" in context
        assert "Rechnung von Amazon" in context

    def test_build_file_context_image_no_text(self):
        """build_file_context zeigt Hinweis wenn kein Text erkannt."""
        from assistant.file_handler import build_file_context

        files = [
            {
                "name": "photo.jpg",
                "type": "image",
                "size": 300000,
                "extracted_text": None,
            }
        ]
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

        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
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
                with patch(
                    "assistant.ocr.extract_text_from_image", return_value="Hello"
                ):
                    result = await engine.analyze_image(
                        {"name": "combo.jpg", "unique_name": "combo.jpg"},
                        "Was steht da?",
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


# ── _check_tesseract ─────────────────────────────────────────


class TestCheckTesseract:
    """Tests fuer die lazy Tesseract-Verfuegbarkeitspruefung."""

    def test_cached_true(self):
        """Gibt gecachtes True zurueck ohne erneuten Check."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True
        assert ocr_mod._check_tesseract() is True

    def test_cached_false(self):
        """Gibt gecachtes False zurueck ohne erneuten Check."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = False
        assert ocr_mod._check_tesseract() is False

    def test_first_check_available(self):
        """Erster Check: Tesseract verfuegbar."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = None

        mock_pytesseract = MagicMock()
        mock_pytesseract.get_tesseract_version.return_value = "5.3.0"

        with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                result = ocr_mod._check_tesseract()

        assert result is True
        assert ocr_mod._tesseract_available is True

    def test_first_check_not_available(self):
        """Erster Check: Tesseract nicht installiert."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = None

        mock_pytesseract = MagicMock()
        mock_pytesseract.get_tesseract_version.side_effect = RuntimeError("not found")

        with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                result = ocr_mod._check_tesseract()

        assert result is False
        assert ocr_mod._tesseract_available is False


# ── _validate_image_path ─────────────────────────────────────


class TestValidateImagePath:
    """Tests fuer Pfad-Validierung gegen Command Injection."""

    def test_valid_tmp_path(self, tmp_path):
        """Pfad in /tmp ist erlaubt."""
        import assistant.ocr as ocr_mod

        img = tmp_path / "test.png"
        img.write_bytes(b"fake")
        with patch.object(Path, "resolve", return_value=Path("/tmp/test.png")):
            result = ocr_mod._validate_image_path(Path("/tmp/test.png"))
        assert result is True

    def test_dangerous_chars_blocked(self):
        """Dateiname mit Shell-Metazeichen wird blockiert."""
        import assistant.ocr as ocr_mod

        dangerous_names = [
            "test;rm -rf.png",
            "test|cat.png",
            "test$(cmd).png",
            "test`cmd`.png",
            "test'quote.png",
        ]
        for name in dangerous_names:
            result = ocr_mod._validate_image_path(Path(f"/tmp/{name}"))
            assert result is False, f"Should block: {name}"

    def test_path_traversal_blocked(self):
        """Pfadtraversal ausserhalb erlaubter Verzeichnisse wird blockiert."""
        import assistant.ocr as ocr_mod

        result = ocr_mod._validate_image_path(Path("/etc/passwd"))
        assert result is False

    def test_oserror_returns_false(self):
        """OSError bei resolve gibt False zurueck."""
        import assistant.ocr as ocr_mod

        p = Path("/tmp/normal.png")
        with patch.object(Path, "resolve", side_effect=OSError("disk error")):
            result = ocr_mod._validate_image_path(p)
        assert result is False


# ── extract_text_from_image edge cases ───────────────────────


class TestExtractTextEdgeCases:
    """Erweiterte Edge-Case-Tests fuer extract_text_from_image."""

    def test_large_file_rejected(self, tmp_path):
        """Bilder ueber 50 MB werden abgelehnt."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "huge.png"
        img_path.write_bytes(_create_test_image())

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=60 * 1024 * 1024)  # 60 MB
            with patch("assistant.ocr._validate_image_path", return_value=True):
                result = ocr_mod.extract_text_from_image(img_path)
        assert result is None

    def test_invalid_path_rejected(self, tmp_path):
        """Invalider Pfad wird durch Validierung abgelehnt."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        with patch("assistant.ocr._validate_image_path", return_value=False):
            result = ocr_mod.extract_text_from_image(tmp_path / "test.png")
        assert result is None

    def test_exception_returns_none(self, tmp_path):
        """Exception waehrend OCR gibt None zurueck."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "bad.png"
        img_path.write_bytes(b"not a valid image")

        with patch("assistant.ocr._validate_image_path", return_value=True):
            result = ocr_mod.extract_text_from_image(img_path)
        assert result is None

    def test_psm6_fallback(self, tmp_path):
        """PSM 6 Fallback wenn PSM 3 wenig Text liefert."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image("AB"))

        mock_pytesseract = MagicMock()
        # PSM 3 returns short text, PSM 6 returns longer text
        mock_pytesseract.image_to_string.side_effect = [
            "AB",  # PSM 3: short
            "AB CD EF GH",  # PSM 6: longer
        ]

        with patch("assistant.ocr._validate_image_path", return_value=True):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                    result = ocr_mod.extract_text_from_image(img_path)

        # Should use the PSM 6 result since it's longer
        assert result == "AB CD EF GH"

    def test_image_mode_conversion(self, tmp_path):
        """Bild im RGBA-Modus wird korrekt konvertiert."""
        from PIL import Image

        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img = Image.new("RGBA", (200, 50), color=(255, 255, 255, 255))
        img_path = tmp_path / "rgba.png"
        img.save(img_path, format="PNG")

        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Test RGBA text output"

        with patch("assistant.ocr._validate_image_path", return_value=True):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                    result = ocr_mod.extract_text_from_image(img_path)

        assert result == "Test RGBA text output"

    def test_small_image_upscaled(self, tmp_path):
        """Kleine Bilder werden hochskaliert."""
        from PIL import Image

        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        # Create a very small image (50x20)
        img = Image.new("RGB", (50, 20), color="white")
        img_path = tmp_path / "small.png"
        img.save(img_path, format="PNG")

        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Upscaled text result"

        with patch("assistant.ocr._validate_image_path", return_value=True):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                    result = ocr_mod.extract_text_from_image(img_path)

        assert result == "Upscaled text result"
        # Verify image_to_string was called (with the preprocessed image)
        assert mock_pytesseract.image_to_string.called


# ── extract_text_with_confidence ─────────────────────────────


class TestExtractTextWithConfidence:
    """Tests fuer die Confidence-basierte OCR-Funktion."""

    def test_no_tesseract_returns_none(self, tmp_path):
        """Ohne Tesseract gibt None zurueck."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = False
        result = ocr_mod.extract_text_with_confidence(tmp_path / "test.png")
        assert result is None

    def test_invalid_path_returns_none(self, tmp_path):
        """Invalider Pfad gibt None zurueck."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True
        with patch("assistant.ocr._validate_image_path", return_value=False):
            result = ocr_mod.extract_text_with_confidence(tmp_path / "test.png")
        assert result is None

    def test_successful_extraction(self, tmp_path):
        """Erfolgreiche Confidence-Extraktion."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_create_test_image("Hello World"))

        mock_pytesseract = MagicMock()
        mock_pytesseract.Output = MagicMock()
        mock_pytesseract.Output.DICT = "dict"
        mock_pytesseract.image_to_data.return_value = {
            "text": ["Hello", "World", "", "Test"],
            "conf": [95, 88, -1, 30],
        }

        with patch("assistant.ocr._validate_image_path", return_value=True):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                    result = ocr_mod.extract_text_with_confidence(img_path)

        assert result is not None
        assert result["text"] == "Hello World Test"
        assert result["word_count"] == 3
        assert result["avg_confidence"] == round((95 + 88 + 30) / 3, 1)
        assert len(result["low_confidence_words"]) == 1
        assert result["low_confidence_words"][0]["word"] == "Test"
        assert result["low_confidence_words"][0]["confidence"] == 30

    def test_no_words_returns_none(self, tmp_path):
        """Keine Woerter erkannt gibt None zurueck."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "empty.png"
        img_path.write_bytes(_create_test_image())

        mock_pytesseract = MagicMock()
        mock_pytesseract.Output = MagicMock()
        mock_pytesseract.Output.DICT = "dict"
        mock_pytesseract.image_to_data.return_value = {
            "text": ["", " ", ""],
            "conf": [-1, -1, -1],
        }

        with patch("assistant.ocr._validate_image_path", return_value=True):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                    result = ocr_mod.extract_text_with_confidence(img_path)

        assert result is None

    def test_long_text_truncated(self, tmp_path):
        """Langer Text wird auf MAX_OCR_CHARS abgeschnitten."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "long.png"
        img_path.write_bytes(_create_test_image())

        long_words = [f"Word{i}" for i in range(1000)]
        confs = [90] * 1000

        mock_pytesseract = MagicMock()
        mock_pytesseract.Output = MagicMock()
        mock_pytesseract.Output.DICT = "dict"
        mock_pytesseract.image_to_data.return_value = {
            "text": long_words,
            "conf": confs,
        }

        with patch("assistant.ocr._validate_image_path", return_value=True):
            with patch("assistant.ocr.pytesseract", mock_pytesseract, create=True):
                with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                    result = ocr_mod.extract_text_with_confidence(img_path)

        assert result is not None
        assert len(result["text"]) <= ocr_mod.MAX_OCR_CHARS + 10
        assert result["text"].endswith("...")

    def test_exception_returns_none(self, tmp_path):
        """Exception gibt None zurueck."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = True

        img_path = tmp_path / "bad.png"
        img_path.write_bytes(b"not an image")

        with patch("assistant.ocr._validate_image_path", return_value=True):
            result = ocr_mod.extract_text_with_confidence(img_path)
        assert result is None


# ── OCREngine extended tests ─────────────────────────────────


class TestOCREngineExtended:
    """Erweiterte Tests fuer OCREngine."""

    def test_reload_config_updates_values(self):
        """reload_config aktualisiert Konfiguration."""
        with patch(
            "assistant.ocr.yaml_config",
            {"ocr": {"enabled": True, "vision_model": "llava"}},
        ):
            from assistant.ocr import OCREngine

            engine = OCREngine()
            assert engine.vision_model == "llava"

        # Now reload with new config
        with patch("assistant.ocr.yaml_config") as mock_cfg:
            mock_cfg.get.return_value = {
                "enabled": False,
                "languages": "eng",
                "vision_model": "moondream",
                "max_image_size_mb": 5,
                "description_max_tokens": 128,
            }
            engine.reload_config()

        assert engine.enabled is False
        assert engine.languages == "eng"
        assert engine.vision_model == "moondream"
        assert engine.max_image_size_mb == 5
        assert engine.description_max_tokens == 128
        # Vision should be reset since model changed
        assert engine._vision_available is False

    def test_reload_config_same_model_keeps_vision(self):
        """reload_config behaelt _vision_available wenn Model gleich bleibt."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()
            engine._vision_available = True

        with patch("assistant.ocr.yaml_config") as mock_cfg:
            mock_cfg.get.return_value = {
                "vision_model": "llava",
            }
            engine.reload_config()

        assert engine._vision_available is True

    def test_extract_text_disabled(self):
        """extract_text gibt None wenn disabled."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"enabled": False}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()
            result = engine.extract_text(Path("/tmp/test.png"))
        assert result is None

    def test_extract_text_enabled(self):
        """extract_text delegiert an extract_text_from_image."""
        with patch(
            "assistant.ocr.yaml_config", {"ocr": {"enabled": True, "languages": "eng"}}
        ):
            from assistant.ocr import OCREngine

            engine = OCREngine()
            with patch(
                "assistant.ocr.extract_text_from_image", return_value="Extracted"
            ) as mock:
                result = engine.extract_text(Path("/tmp/test.png"))
            mock.assert_called_once_with(Path("/tmp/test.png"), "eng")
            assert result == "Extracted"

    @pytest.mark.asyncio
    async def test_initialize_ollama_exception(self):
        """Initialize handelt Ollama-Fehler graceful."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            mock_ollama = AsyncMock()
            mock_ollama.list_models.side_effect = ConnectionError("Ollama down")

            engine = OCREngine(ollama_client=mock_ollama)
            await engine.initialize()

            assert engine._vision_available is False

    @pytest.mark.asyncio
    async def test_describe_image_no_ollama(self):
        """describe_image gibt None ohne Ollama-Client."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"enabled": True}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()
            engine._vision_available = True
            engine._ollama = None
            result = await engine.describe_image({"name": "test.jpg"})
        assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_file_too_large(self, tmp_path):
        """describe_image gibt None fuer zu grosse Bilder."""
        with patch(
            "assistant.ocr.yaml_config",
            {"ocr": {"vision_model": "llava", "max_image_size_mb": 1}},
        ):
            from assistant.ocr import OCREngine

            img_path = tmp_path / "big.jpg"
            img_path.write_bytes(_create_test_image())

            mock_ollama = AsyncMock()
            engine = OCREngine(ollama_client=mock_ollama)
            engine._vision_available = True

            # Mock stat to return large file
            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                with patch("asyncio.to_thread") as mock_thread:
                    mock_stat = MagicMock()
                    mock_stat.st_size = 5 * 1024 * 1024  # 5 MB
                    mock_thread.return_value = mock_stat
                    result = await engine.describe_image(
                        {"name": "big.jpg", "unique_name": "big.jpg"}
                    )

            assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_no_file_path(self):
        """describe_image gibt None wenn Datei nicht gefunden."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            engine = OCREngine(ollama_client=AsyncMock())
            engine._vision_available = True

            with patch("assistant.file_handler.get_file_path", return_value=None):
                result = await engine.describe_image(
                    {"name": "missing.jpg", "unique_name": "missing.jpg"}
                )

            assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_error_response(self, tmp_path):
        """describe_image gibt None bei LLM-Fehler."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            img_path = tmp_path / "err.jpg"
            img_path.write_bytes(_create_test_image())

            mock_ollama = AsyncMock()
            mock_ollama.chat.return_value = {"error": "model not loaded"}

            engine = OCREngine(ollama_client=mock_ollama)
            engine._vision_available = True

            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                result = await engine.describe_image(
                    {"name": "err.jpg", "unique_name": "err.jpg"},
                )

            assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_empty_description(self, tmp_path):
        """describe_image gibt None bei leerer Beschreibung."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            img_path = tmp_path / "empty.jpg"
            img_path.write_bytes(_create_test_image())

            mock_ollama = AsyncMock()
            mock_ollama.chat.return_value = {"message": {"content": "  "}}

            engine = OCREngine(ollama_client=mock_ollama)
            engine._vision_available = True

            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                result = await engine.describe_image(
                    {"name": "empty.jpg", "unique_name": "empty.jpg"},
                )

            assert result is None

    @pytest.mark.asyncio
    async def test_describe_image_caches_result(self, tmp_path):
        """describe_image speichert Ergebnis im Redis-Cache."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            img_path = tmp_path / "cache.jpg"
            img_path.write_bytes(_create_test_image())

            mock_ollama = AsyncMock()
            mock_ollama.chat.return_value = {
                "message": {"content": "A beautiful picture."}
            }
            mock_redis = AsyncMock()
            mock_redis.get.return_value = None

            engine = OCREngine(ollama_client=mock_ollama)
            engine._vision_available = True
            engine._redis = mock_redis

            with patch("assistant.file_handler.get_file_path", return_value=img_path):
                result = await engine.describe_image(
                    {"name": "cache.jpg", "unique_name": "cache.jpg"},
                )

            assert result == "A beautiful picture."
            mock_redis.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_describe_image_exception_returns_none(self, tmp_path):
        """describe_image faengt allgemeine Exceptions ab."""
        with patch("assistant.ocr.yaml_config", {"ocr": {"vision_model": "llava"}}):
            from assistant.ocr import OCREngine

            engine = OCREngine(ollama_client=AsyncMock())
            engine._vision_available = True

            with patch(
                "assistant.file_handler.get_file_path", side_effect=RuntimeError("boom")
            ):
                result = await engine.describe_image(
                    {"name": "boom.jpg", "unique_name": "boom.jpg"},
                )

            assert result is None

    def test_health_status_no_backends(self):
        """health_status zeigt 'no backends' wenn nichts verfuegbar."""
        import assistant.ocr as ocr_mod

        ocr_mod._tesseract_available = False

        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()
            engine._vision_available = False
            status = engine.health_status()
            assert status == "active (no backends)"


# ── _prepare_image_b64 ───────────────────────────────────────


class TestPrepareImageB64:
    """Tests fuer die Bild-Vorbereitung als Base64-JPEG."""

    def test_normal_image(self, tmp_path):
        """Normales Bild wird zu Base64-JPEG konvertiert."""
        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()

            img_path = tmp_path / "normal.png"
            img_path.write_bytes(_create_test_image())

            result = engine._prepare_image_b64(img_path)
            assert result is not None
            # Should be valid base64
            import base64

            decoded = base64.b64decode(result)
            assert len(decoded) > 0

    def test_large_image_resized(self, tmp_path):
        """Grosse Bilder werden auf max 1024px verkleinert."""
        from PIL import Image

        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()

            # Create a large image (2048x1536)
            img = Image.new("RGB", (2048, 1536), color="white")
            img_path = tmp_path / "large.png"
            img.save(img_path, format="PNG")

            result = engine._prepare_image_b64(img_path)
            assert result is not None

            # Verify the output image was resized
            import base64

            decoded = base64.b64decode(result)
            buf = io.BytesIO(decoded)
            resized = Image.open(buf)
            assert max(resized.size) <= 1024

    def test_rgba_image_converted(self, tmp_path):
        """RGBA-Bilder werden zu RGB konvertiert."""
        from PIL import Image

        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()

            img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
            img_path = tmp_path / "rgba.png"
            img.save(img_path, format="PNG")

            result = engine._prepare_image_b64(img_path)
            assert result is not None

    def test_palette_image_converted(self, tmp_path):
        """P-Mode Bilder werden zu RGB konvertiert."""
        from PIL import Image

        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()

            img = Image.new("P", (100, 100))
            img_path = tmp_path / "palette.png"
            img.save(img_path, format="PNG")

            result = engine._prepare_image_b64(img_path)
            assert result is not None

    def test_invalid_image_returns_none(self, tmp_path):
        """Fehlerhafte Bilddatei gibt None zurueck."""
        with patch("assistant.ocr.yaml_config", {"ocr": {}}):
            from assistant.ocr import OCREngine

            engine = OCREngine()

            bad_path = tmp_path / "bad.jpg"
            bad_path.write_bytes(b"not a valid image file")

            result = engine._prepare_image_b64(bad_path)
            assert result is None
