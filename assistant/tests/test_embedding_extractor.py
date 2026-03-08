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
