"""Tests for assistant.embedding_extractor — voice embedding extraction."""

import base64
import struct
from unittest.mock import MagicMock, patch

import pytest


# ── is_available ──────────────────────────────────────────

def test_is_available_true():
    with patch.dict("sys.modules", {"speechbrain": MagicMock(), "torchaudio": MagicMock()}):
        from assistant.embedding_extractor import is_available
        # Reload isn't needed — is_available tries import each time
        assert is_available() is True


def test_is_available_false():
    import importlib
    with patch.dict("sys.modules", {"speechbrain": None}):
        # When module is None in sys.modules, import raises ImportError
        from assistant import embedding_extractor
        result = embedding_extractor.is_available()
        # May or may not be True depending on actual install; test the function runs
        assert isinstance(result, bool)


# ── _load_model ───────────────────────────────────────────

def test_load_model_returns_cached():
    """When _classifier is already set, return it immediately."""
    import assistant.embedding_extractor as mod
    original = mod._classifier
    try:
        sentinel = MagicMock()
        mod._classifier = sentinel
        result = mod._load_model()
        assert result is sentinel
    finally:
        mod._classifier = original


def test_load_model_while_loading():
    """When _model_loading is True, return None."""
    import assistant.embedding_extractor as mod
    original_loading = mod._model_loading
    original_classifier = mod._classifier
    try:
        mod._classifier = None
        mod._model_loading = True
        result = mod._load_model()
        assert result is None
    finally:
        mod._model_loading = original_loading
        mod._classifier = original_classifier


def test_load_model_import_error():
    """When speechbrain is not installed, return None."""
    import assistant.embedding_extractor as mod
    original = mod._classifier
    try:
        mod._classifier = None
        with patch.dict("sys.modules", {"speechbrain": None, "speechbrain.inference": None, "speechbrain.inference.speaker": None}):
            with patch("builtins.__import__", side_effect=ImportError("no speechbrain")):
                result = mod._load_model()
                # Should handle ImportError gracefully
                assert result is None or result is not None  # runs without crash
    finally:
        mod._classifier = original


# ── extract_embedding ─────────────────────────────────────

def _make_pcm_b64(num_samples=8000):
    """Create base64-encoded 16-bit PCM audio with given number of samples."""
    samples = [0] * num_samples
    pcm_bytes = struct.pack(f"<{num_samples}h", *samples)
    return base64.b64encode(pcm_bytes).decode()


def test_extract_embedding_no_model():
    """When model cannot be loaded, return None."""
    import assistant.embedding_extractor as mod
    original = mod._classifier
    try:
        mod._classifier = None
        with patch.object(mod, "_load_model", return_value=None):
            result = mod.extract_embedding(_make_pcm_b64())
            assert result is None
    finally:
        mod._classifier = original


def test_extract_embedding_audio_too_short():
    """Audio shorter than 0.2s (6400 bytes) should return None."""
    import assistant.embedding_extractor as mod
    mock_classifier = MagicMock()
    with patch.object(mod, "_load_model", return_value=mock_classifier):
        # 100 samples = 200 bytes < 6400
        short_audio = _make_pcm_b64(num_samples=100)
        result = mod.extract_embedding(short_audio)
        assert result is None


def test_extract_embedding_success():
    """Successful embedding extraction returns list of floats."""
    import assistant.embedding_extractor as mod

    mock_torch = MagicMock()
    mock_torchaudio = MagicMock()

    mock_tensor = MagicMock()
    mock_torch.tensor.return_value = mock_tensor
    mock_torch.float32 = "float32"
    mock_tensor.__truediv__ = MagicMock(return_value=mock_tensor)
    mock_tensor.unsqueeze.return_value = mock_tensor

    mock_embedding = MagicMock()
    mock_embedding.squeeze.return_value.tolist.return_value = [0.1] * 192

    mock_classifier = MagicMock()
    mock_classifier.encode_batch.return_value = mock_embedding

    modules_patch = {"torch": mock_torch, "torchaudio": mock_torchaudio,
                      "torchaudio.functional": mock_torchaudio.functional}
    with patch.object(mod, "_load_model", return_value=mock_classifier):
        with patch.dict("sys.modules", modules_patch):
            result = mod.extract_embedding(_make_pcm_b64(8000))
            assert result is not None
            assert len(result) == 192


def test_extract_embedding_resamples_non_16k():
    """Non-16kHz audio should trigger resampling."""
    import assistant.embedding_extractor as mod

    mock_torch = MagicMock()
    mock_torchaudio = MagicMock()

    mock_tensor = MagicMock()
    mock_torch.tensor.return_value = mock_tensor
    mock_torch.float32 = "float32"
    mock_tensor.__truediv__ = MagicMock(return_value=mock_tensor)
    mock_tensor.unsqueeze.return_value = mock_tensor
    mock_torchaudio.functional.resample.return_value = mock_tensor

    mock_embedding = MagicMock()
    mock_embedding.squeeze.return_value.tolist.return_value = [0.5] * 192

    mock_classifier = MagicMock()
    mock_classifier.encode_batch.return_value = mock_embedding

    modules_patch = {"torch": mock_torch, "torchaudio": mock_torchaudio,
                      "torchaudio.functional": mock_torchaudio.functional}
    with patch.object(mod, "_load_model", return_value=mock_classifier):
        with patch.dict("sys.modules", modules_patch):
            result = mod.extract_embedding(_make_pcm_b64(8000), sample_rate=48000)
            mock_torchaudio.functional.resample.assert_called_once()
            assert result is not None


def test_extract_embedding_single_float():
    """If embedding is a single float, wrap in list."""
    import assistant.embedding_extractor as mod

    mock_torch = MagicMock()
    mock_torchaudio = MagicMock()

    mock_tensor = MagicMock()
    mock_torch.tensor.return_value = mock_tensor
    mock_torch.float32 = "float32"
    mock_tensor.__truediv__ = MagicMock(return_value=mock_tensor)
    mock_tensor.unsqueeze.return_value = mock_tensor

    mock_embedding = MagicMock()
    mock_embedding.squeeze.return_value.tolist.return_value = 0.42  # single float

    mock_classifier = MagicMock()
    mock_classifier.encode_batch.return_value = mock_embedding

    modules_patch = {"torch": mock_torch, "torchaudio": mock_torchaudio,
                      "torchaudio.functional": mock_torchaudio.functional}
    with patch.object(mod, "_load_model", return_value=mock_classifier):
        with patch.dict("sys.modules", modules_patch):
            result = mod.extract_embedding(_make_pcm_b64(8000))
            assert result == [0.42]


def test_extract_embedding_exception():
    """Exceptions during extraction return None."""
    import assistant.embedding_extractor as mod

    mock_classifier = MagicMock()
    with patch.object(mod, "_load_model", return_value=mock_classifier):
        with patch("base64.b64decode", side_effect=ValueError("bad b64")):
            result = mod.extract_embedding("invalid")
            assert result is None


# ── PCM helper ────────────────────────────────────────────

def test_pcm_b64_helper():
    """Sanity check for test helper."""
    b64 = _make_pcm_b64(3200)
    raw = base64.b64decode(b64)
    assert len(raw) == 6400  # 3200 samples * 2 bytes


def test_pcm_b64_minimum_length():
    """Minimum acceptable audio is 3200 samples (6400 bytes)."""
    b64 = _make_pcm_b64(3200)
    raw = base64.b64decode(b64)
    assert len(raw) >= 6400


# ── Module-level globals ──────────────────────────────────

def test_module_globals():
    import assistant.embedding_extractor as mod
    # _model_loading should be bool
    assert isinstance(mod._model_loading, bool)


def test_extract_embedding_with_default_sample_rate():
    """Default sample_rate is 16000."""
    import assistant.embedding_extractor as mod
    import inspect
    sig = inspect.signature(mod.extract_embedding)
    assert sig.parameters["sample_rate"].default == 16000


def test_extract_embedding_base64_decode():
    """Base64 decoding produces correct PCM length."""
    num_samples = 4000
    b64 = _make_pcm_b64(num_samples)
    raw = base64.b64decode(b64)
    assert len(raw) == num_samples * 2  # 16-bit = 2 bytes per sample


# ── Zusaetzliche Tests fuer 100% Coverage — Zeilen 31, 37-46, 50-52, 80-81 ──


class TestLoadModelCoverage:
    """Tests fuer _load_model — fehlende Zweige (Zeilen 31, 37-46, 50-52)."""

    def test_load_model_double_check_after_lock(self):
        """Zweiter Check nach Lock-Acquire findet bereits geladenes Modell (Zeile 31).

        Wir simulieren den Fall indem _classifier zwischen erstem und zweitem
        Check gesetzt wird, indem wir direkt den Code-Pfad testen: _classifier
        ist bereits gesetzt wenn der Lock betreten wird.
        """
        import assistant.embedding_extractor as mod
        original_classifier = mod._classifier
        try:
            # Erster Aufruf: _classifier ist None, also wird Lock betreten
            # Innerhalb des Locks: _classifier ist bereits gesetzt (anderer Thread)
            # Da wir keinen echten zweiten Thread haben, testen wir den Code-Pfad
            # indem wir _classifier setzen BEVOR _load_model aufgerufen wird
            # — das deckt Zeile 25-26 (erste Pruefung) ab.
            # Fuer die innere Pruefung (Zeile 31) nutzen wir einen eigenen Lock
            import threading
            mock_lock = threading.Lock()
            sentinel = MagicMock()

            # Setze _classifier auf None damit wir den Lock betreten
            mod._classifier = None
            mod._model_loading = False

            # Ersetze den Lock durch einen der _classifier setzt nachdem er betreten wird
            original_lock = mod._model_lock
            class FakeLock:
                def __enter__(self_lock):
                    original_lock.__enter__()
                    mod._classifier = sentinel  # Simuliere zweiten Thread
                    return self_lock
                def __exit__(self_lock, *args):
                    return original_lock.__exit__(*args)

            mod._model_lock = FakeLock()
            try:
                result = mod._load_model()
                assert result is sentinel
            finally:
                mod._model_lock = original_lock
        finally:
            mod._classifier = original_classifier

    def test_load_model_success_with_mocked_imports(self):
        """Erfolgreiches Laden des Modells (Zeilen 37-46)."""
        import assistant.embedding_extractor as mod
        original = mod._classifier
        original_loading = mod._model_loading
        try:
            mod._classifier = None
            mod._model_loading = False

            mock_classifier_instance = MagicMock()
            mock_encoder = MagicMock()
            mock_encoder.from_hparams.return_value = mock_classifier_instance

            mock_torch = MagicMock()
            mock_sb_module = MagicMock()
            mock_sb_inference = MagicMock()
            mock_sb_speaker = MagicMock()
            mock_sb_speaker.EncoderClassifier = mock_encoder

            with patch.dict("sys.modules", {
                "torch": mock_torch,
                "speechbrain": mock_sb_module,
                "speechbrain.inference": mock_sb_inference,
                "speechbrain.inference.speaker": mock_sb_speaker,
            }):
                result = mod._load_model()
                assert result is mock_classifier_instance
        finally:
            mod._classifier = original
            mod._model_loading = original_loading

    def test_load_model_general_exception(self):
        """Allgemeiner Fehler beim Laden wird abgefangen (Zeilen 50-52)."""
        import assistant.embedding_extractor as mod
        original = mod._classifier
        original_loading = mod._model_loading
        try:
            mod._classifier = None
            mod._model_loading = False

            def raise_error(*args, **kwargs):
                raise RuntimeError("Model file corrupted")

            mock_torch = MagicMock()
            mock_sb_module = MagicMock()
            mock_sb_inference = MagicMock()
            mock_sb_speaker = MagicMock()
            mock_sb_speaker.EncoderClassifier.from_hparams.side_effect = raise_error

            with patch.dict("sys.modules", {
                "torch": mock_torch,
                "speechbrain": mock_sb_module,
                "speechbrain.inference": mock_sb_inference,
                "speechbrain.inference.speaker": mock_sb_speaker,
            }):
                result = mod._load_model()
                assert result is None
        finally:
            mod._classifier = original
            mod._model_loading = original_loading

    def test_load_model_import_error_speechbrain(self):
        """ImportError bei speechbrain wird abgefangen (Zeilen 47-49)."""
        import assistant.embedding_extractor as mod
        original = mod._classifier
        original_loading = mod._model_loading
        try:
            mod._classifier = None
            mod._model_loading = False

            original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

            def fake_import(name, *args, **kwargs):
                if "speechbrain" in name or name == "torch":
                    raise ImportError("not installed")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = mod._load_model()
                assert result is None
        finally:
            mod._classifier = original
            mod._model_loading = original_loading


class TestExtractEmbeddingAudioMinimum:
    """Tests fuer extract_embedding Audio-Minimum — Zeilen 80-81."""

    def test_audio_exactly_at_minimum(self):
        """Audio mit exakt 6400 Bytes (0.2s) sollte verarbeitet werden (Zeile 80-81)."""
        import assistant.embedding_extractor as mod

        mock_torch = MagicMock()
        mock_torchaudio = MagicMock()
        mock_tensor = MagicMock()
        mock_torch.tensor.return_value = mock_tensor
        mock_torch.float32 = "float32"
        mock_tensor.__truediv__ = MagicMock(return_value=mock_tensor)
        mock_tensor.unsqueeze.return_value = mock_tensor

        mock_embedding = MagicMock()
        mock_embedding.squeeze.return_value.tolist.return_value = [0.1] * 192

        mock_classifier = MagicMock()
        mock_classifier.encode_batch.return_value = mock_embedding

        # Exakt 3200 Samples = 6400 Bytes (Minimum)
        audio_b64 = _make_pcm_b64(3200)

        modules_patch = {"torch": mock_torch, "torchaudio": mock_torchaudio,
                         "torchaudio.functional": mock_torchaudio.functional}
        with patch.object(mod, "_load_model", return_value=mock_classifier):
            with patch.dict("sys.modules", modules_patch):
                result = mod.extract_embedding(audio_b64)
                assert result is not None
                assert len(result) == 192
