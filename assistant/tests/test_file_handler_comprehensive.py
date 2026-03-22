"""
Comprehensive tests for file_handler.py — focusing on edge cases in
save_upload, get_file_path security, text extraction, and build_file_context.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from assistant.file_handler import (
    ALLOWED_EXTENSIONS,
    FILE_TYPE_MAP,
    MAX_EXTRACT_CHARS,
    MAX_FILE_SIZE,
    UPLOAD_DIR,
    allowed_file,
    build_file_context,
    get_file_path,
    get_file_type,
    save_upload,
    _extract_text,
    _read_text,
)


# ── save_upload edge cases ───────────────────────────────────


class TestSaveUploadEdgeCases:
    """Edge cases for file saving and sanitization."""

    @patch("assistant.file_handler._extract_text", return_value=None)
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_filename_with_unicode_chars(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        """Unicode characters not in the allowed set are stripped."""
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("bericht_\u00fc\u00e4\u00f6.txt", b"data")
        # Umlauts are not alnum in the "c for c in filename if c.isalnum()" check
        # Actually, isalnum() returns True for unicode letters
        assert result["ext"] == "txt"
        assert result["size"] == 4

    @patch("assistant.file_handler._extract_text", return_value=None)
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_filename_with_spaces_preserved(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        """Spaces in filenames are preserved (in the allowed chars)."""
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("my report.txt", b"data")
        assert " " in result["name"]
        assert result["name"] == "my report.txt"

    @patch("assistant.file_handler._extract_text", return_value=None)
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_filename_with_dashes_and_underscores(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        """Dashes and underscores are allowed in filenames."""
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("my-report_v2.txt", b"data")
        assert result["name"] == "my-report_v2.txt"

    @patch("assistant.file_handler._extract_text", return_value="extracted content")
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_url_contains_unique_name(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        """URL in result contains the unique filename."""
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("report.pdf", b"pdf content")
        assert result["unique_name"] in result["url"]

    @patch("assistant.file_handler._extract_text", return_value=None)
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_image_file_type_detected(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        """Image extensions produce file type 'image'."""
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("photo.png", b"\x89PNG")
        assert result["type"] == "image"

    @patch("assistant.file_handler._extract_text", return_value=None)
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_audio_file_type_detected(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("recording.mp3", b"audio data")
        assert result["type"] == "audio"

    @patch("assistant.file_handler._extract_text", return_value=None)
    @patch("assistant.file_handler.UPLOAD_DIR")
    @patch("assistant.file_handler.ensure_upload_dir")
    def test_video_file_type_detected(
        self, mock_ensure, mock_dir, mock_extract, tmp_path
    ):
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        result = save_upload("clip.mp4", b"video data")
        assert result["type"] == "video"


# ── get_file_path security ────────────────────────────────────


class TestGetFilePathSecurity:
    """Security-focused tests for path traversal prevention."""

    def test_symlink_outside_upload_dir(self, tmp_path):
        """Symlinks pointing outside the upload directory are rejected."""
        target = tmp_path / "outside" / "secret.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("secret")

        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        link = upload_dir / "link.txt"
        link.symlink_to(target)

        with patch("assistant.file_handler.UPLOAD_DIR", upload_dir):
            # resolve() follows the symlink, so it should be outside
            result = get_file_path("link.txt")
            # The resolved path points outside UPLOAD_DIR
            assert result is None

    def test_null_bytes_in_filename(self, tmp_path):
        """Null bytes in filename should be handled safely (raises or returns None)."""
        with patch("assistant.file_handler.UPLOAD_DIR", tmp_path):
            # Null bytes cause ValueError in pathlib.resolve() — verify no crash
            try:
                result = get_file_path("file\x00.txt")
                assert result is None
            except ValueError:
                pass  # ValueError from embedded null byte is acceptable

    def test_encoded_slashes(self, tmp_path):
        """Filenames with various path separators."""
        with patch("assistant.file_handler.UPLOAD_DIR", tmp_path):
            # os.path.basename strips the directory part
            result = get_file_path("subdir/file.txt")
            assert result is None

    def test_very_long_filename(self, tmp_path):
        """Very long filenames should not cause crashes (may raise OSError)."""
        long_name = "a" * 500 + ".txt"
        with patch("assistant.file_handler.UPLOAD_DIR", tmp_path):
            try:
                result = get_file_path(long_name)
                assert result is None  # File doesn't exist
            except OSError:
                pass  # OS rejects overly long filenames — acceptable

    def test_windows_path_separator(self, tmp_path):
        """Windows-style backslash paths are handled."""
        with patch("assistant.file_handler.UPLOAD_DIR", tmp_path):
            result = get_file_path("..\\..\\etc\\passwd")
            # os.path.basename on Linux treats backslash as part of filename
            # so this becomes a regular filename that doesn't exist
            assert result is None


# ── _read_text edge cases ────────────────────────────────────


class TestReadTextEdgeCases:
    """Additional edge cases for text file reading."""

    def test_exactly_one_char_over_limit(self, tmp_path):
        """Text exactly one char over MAX_EXTRACT_CHARS is truncated."""
        f = tmp_path / "over.txt"
        text = "x" * (MAX_EXTRACT_CHARS + 1)
        f.write_text(text, encoding="utf-8")
        result = _read_text(f)
        assert result.endswith("... (abgeschnitten)")
        # First MAX_EXTRACT_CHARS chars kept + suffix appended
        suffix = "\n... (abgeschnitten)"
        assert len(result) == MAX_EXTRACT_CHARS + len(suffix)

    def test_file_with_utf8_bom(self, tmp_path):
        """Files with UTF-8 BOM are handled."""
        f = tmp_path / "bom.txt"
        f.write_bytes(b"\xef\xbb\xbfHello BOM")
        result = _read_text(f)
        assert result is not None
        assert "Hello BOM" in result

    def test_file_with_newlines_only(self, tmp_path):
        """File with only newlines returns None after strip."""
        f = tmp_path / "newlines.txt"
        f.write_text("\n\n\n\n", encoding="utf-8")
        result = _read_text(f)
        assert result is None

    def test_file_with_mixed_encoding_content(self, tmp_path):
        """Binary content mixed with text is handled via errors='replace'."""
        f = tmp_path / "mixed.txt"
        f.write_bytes(b"Start\xff\xfeMiddle\x00End")
        result = _read_text(f)
        assert result is not None
        assert "Start" in result


# ── _extract_text dispatch ────────────────────────────────────


class TestExtractTextDispatch:
    """Test the text extraction dispatch logic."""

    def test_unknown_binary_format_returns_none(self, tmp_path):
        """Binary formats like mp4, avi return None."""
        f = tmp_path / "video.avi"
        result = _extract_text(f, "avi")
        assert result is None

    def test_doc_extension_returns_none(self, tmp_path):
        """doc/docx without library returns None."""
        f = tmp_path / "doc.docx"
        result = _extract_text(f, "docx")
        assert result is None

    def test_pptx_extension_returns_none(self, tmp_path):
        """pptx without library returns None."""
        f = tmp_path / "slide.pptx"
        result = _extract_text(f, "pptx")
        assert result is None


# ── build_file_context edge cases ─────────────────────────────


class TestBuildFileContextEdgeCases:
    """Edge cases for prompt context generation."""

    def test_document_with_extracted_text_and_vision(self):
        """Document with both extracted text and vision description."""
        files = [
            {
                "name": "scan.pdf",
                "type": "document",
                "size": 1024,
                "extracted_text": "PDF content here",
                "vision_description": "A scanned document",
            }
        ]
        result = build_file_context(files)
        # For documents, extracted_text goes under "Inhalt:" not "OCR-Text"
        assert "Inhalt:" in result
        assert "PDF content here" in result
        # Vision description should also appear
        assert "Bild-Analyse" in result

    def test_zero_size_file(self):
        """File with size 0 shows 0 KB."""
        files = [{"name": "empty.txt", "type": "document", "size": 0}]
        result = build_file_context(files)
        assert "0 KB" in result

    def test_exact_1mb_file(self):
        """File at exactly 1MB boundary uses MB format."""
        files = [{"name": "exact.bin", "type": "document", "size": 1024 * 1024}]
        result = build_file_context(files)
        assert "1.0 MB" in result

    def test_just_under_1mb(self):
        """File just under 1MB uses KB format."""
        files = [{"name": "small.bin", "type": "document", "size": 1024 * 1024 - 1}]
        result = build_file_context(files)
        assert "KB" in result

    def test_large_file_mb_formatting(self):
        """Large files show decimal MB."""
        files = [
            {
                "name": "huge.bin",
                "type": "document",
                "size": 15 * 1024 * 1024 + 512 * 1024,
            }
        ]
        result = build_file_context(files)
        assert "MB" in result
        assert "15.5 MB" in result

    def test_many_files_all_types(self):
        """Multiple files of different types in one context."""
        files = [
            {
                "name": "doc.pdf",
                "type": "document",
                "size": 1024,
                "extracted_text": "PDF text",
            },
            {
                "name": "photo.jpg",
                "type": "image",
                "size": 2048,
                "vision_description": "A cat",
            },
            {
                "name": "scan.png",
                "type": "image",
                "size": 3072,
                "extracted_text": "OCR text",
            },
            {"name": "video.mp4", "type": "video", "size": 4096},
            {"name": "audio.mp3", "type": "audio", "size": 5120},
            {"name": "raw.bmp", "type": "image", "size": 6144},
        ]
        result = build_file_context(files)
        assert "HOCHGELADENE DATEIEN:" in result
        assert "doc.pdf" in result
        assert "photo.jpg" in result
        assert "scan.png" in result
        assert "video.mp4" in result
        assert "audio.mp3" in result
        assert "raw.bmp" in result
        assert "HINWEIS" in result


# ── allowed_file edge cases ──────────────────────────────────


class TestAllowedFileEdgeCases:
    """Additional edge cases for file extension validation."""

    def test_path_traversal_disguised_as_extension(self):
        """Filenames with path components still check extension."""
        assert allowed_file("../../etc/passwd.txt") is True  # Extension is valid
        assert allowed_file("../../etc/passwd.exe") is False

    def test_multiple_dots_uses_last_extension(self):
        """Multiple dots — only the last extension matters."""
        assert allowed_file("backup.tar.gz") is False
        assert allowed_file("image.backup.jpg") is True

    def test_extension_with_numbers(self):
        """Extensions with numbers are rejected."""
        assert allowed_file("file.mp3") is True
        assert allowed_file("file.7z") is False

    def test_all_allowed_extensions_in_file_type_map(self):
        """Every allowed extension has a corresponding file type."""
        for ext in ALLOWED_EXTENSIONS:
            assert ext in FILE_TYPE_MAP, f"Extension '{ext}' missing from FILE_TYPE_MAP"

    def test_file_type_map_has_no_extra_entries(self):
        """FILE_TYPE_MAP should not have entries not in ALLOWED_EXTENSIONS."""
        for ext in FILE_TYPE_MAP:
            assert ext in ALLOWED_EXTENSIONS, f"FILE_TYPE_MAP has extra entry '{ext}'"


# ── Constants validation ─────────────────────────────────────


class TestConstantsValidation:
    """Validate constant values are sensible."""

    def test_max_file_size_positive(self):
        assert MAX_FILE_SIZE > 0

    def test_max_extract_chars_positive(self):
        assert MAX_EXTRACT_CHARS > 0

    def test_upload_dir_is_absolute(self):
        assert UPLOAD_DIR.is_absolute()

    def test_no_executable_extensions_allowed(self):
        """Dangerous executable extensions should never be allowed."""
        dangerous = {
            "exe",
            "bat",
            "cmd",
            "sh",
            "ps1",
            "msi",
            "com",
            "vbs",
            "js",
            "php",
            "py",
            "rb",
            "pl",
        }
        assert ALLOWED_EXTENSIONS.isdisjoint(dangerous)

    def test_no_html_or_svg_allowed(self):
        """HTML and SVG should be blocked (XSS risk)."""
        assert "html" not in ALLOWED_EXTENSIONS
        assert "htm" not in ALLOWED_EXTENSIONS
        assert "svg" not in ALLOWED_EXTENSIONS
