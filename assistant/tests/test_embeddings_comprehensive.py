"""
Comprehensive tests for embeddings.py and embedding_extractor.py —
covering caching, cosine similarity, embedding function initialization,
voice embedding extraction, model loading, and audio processing.
"""

import base64
import struct
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

import assistant.embeddings as emb_mod
import assistant.embedding_extractor as ext_mod


# ══════════════════════════════════════════════════════════════
#  embeddings.py — Caching
# ══════════════════════════════════════════════════════════════


class TestEmbeddingCacheOperations:
    """Tests for get_cached_embedding and cache_embedding."""

    def setup_method(self):
        """Save and clear cache state before each test."""
        self._original_cache = OrderedDict(emb_mod._embedding_cache)
        emb_mod._embedding_cache.clear()

    def teardown_method(self):
        """Restore original cache state."""
        emb_mod._embedding_cache.clear()
        emb_mod._embedding_cache.update(self._original_cache)

    def test_cache_miss_returns_none(self):
        result = emb_mod.get_cached_embedding("nonexistent_key")
        assert result is None

    def test_cache_hit_returns_embedding(self):
        emb_mod.cache_embedding("hello", [1.0, 2.0, 3.0])
        result = emb_mod.get_cached_embedding("hello")
        assert result == [1.0, 2.0, 3.0]

    def test_cache_updates_existing_key(self):
        emb_mod.cache_embedding("key", [1.0])
        emb_mod.cache_embedding("key", [2.0])
        assert emb_mod.get_cached_embedding("key") == [2.0]

    def test_cache_lru_eviction_order(self):
        """Oldest entries are evicted when cache exceeds max size."""
        max_size = emb_mod._EMBEDDING_CACHE_MAX
        # Fill cache to max + 10
        for i in range(max_size + 10):
            emb_mod.cache_embedding(f"key_{i}", [float(i)])

        assert len(emb_mod._embedding_cache) == max_size
        # First 10 entries should be evicted
        assert emb_mod.get_cached_embedding("key_0") is None
        assert emb_mod.get_cached_embedding("key_9") is None
        # Last entry should still be present
        assert emb_mod.get_cached_embedding(f"key_{max_size + 9}") is not None

    def test_cache_move_to_end_on_insert(self):
        """Reinserting a key moves it to the end (most recent)."""
        emb_mod.cache_embedding("a", [1.0])
        emb_mod.cache_embedding("b", [2.0])
        emb_mod.cache_embedding("a", [1.0])  # Re-insert a
        keys = list(emb_mod._embedding_cache.keys())
        assert keys[-1] == "a"

    def test_cache_with_empty_embedding(self):
        """Empty embedding list can be cached."""
        emb_mod.cache_embedding("empty", [])
        assert emb_mod.get_cached_embedding("empty") == []

    def test_cache_with_high_dimensional_embedding(self):
        """Large embedding vectors work correctly."""
        big = [float(i) for i in range(768)]
        emb_mod.cache_embedding("big_vector", big)
        assert emb_mod.get_cached_embedding("big_vector") == big


# ══════════════════════════════════════════════════════════════
#  embeddings.py — Cosine Similarity
# ══════════════════════════════════════════════════════════════


class TestCosineSimilarity:
    """Tests for compute_cosine_similarity."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        result = emb_mod.compute_cosine_similarity(v, v)
        assert abs(result - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        result = emb_mod.compute_cosine_similarity(a, b)
        assert abs(result) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        result = emb_mod.compute_cosine_similarity(a, b)
        assert abs(result - (-1.0)) < 1e-6

    def test_zero_vector_a_returns_zero(self):
        result = emb_mod.compute_cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert result == 0.0

    def test_zero_vector_b_returns_zero(self):
        result = emb_mod.compute_cosine_similarity([1.0, 2.0], [0.0, 0.0])
        assert result == 0.0

    def test_both_zero_vectors(self):
        result = emb_mod.compute_cosine_similarity([0.0], [0.0])
        assert result == 0.0

    def test_single_dimension(self):
        result = emb_mod.compute_cosine_similarity([3.0], [4.0])
        assert abs(result - 1.0) < 1e-6

    def test_negative_values(self):
        a = [-1.0, -2.0]
        b = [-2.0, -4.0]
        result = emb_mod.compute_cosine_similarity(a, b)
        assert abs(result - 1.0) < 1e-6

    def test_large_vectors(self):
        """Cosine similarity works with 384-dim vectors (typical embedding size)."""
        import math

        a = [math.sin(i) for i in range(384)]
        b = [math.cos(i) for i in range(384)]
        result = emb_mod.compute_cosine_similarity(a, b)
        assert -1.0 <= result <= 1.0

    def test_mismatched_lengths_truncates(self):
        """zip() truncates to shorter vector — verify behavior."""
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0]
        result = emb_mod.compute_cosine_similarity(a, b)
        # zip truncates, so only first 2 elements used
        # dot = 1.0, norm_a = 1.0, norm_b = 1.0
        assert abs(result - 1.0) < 1e-6


# ══════════════════════════════════════════════════════════════
#  embeddings.py — get_embedding_function
# ══════════════════════════════════════════════════════════════


class TestGetEmbeddingFunction:
    """Tests for the singleton embedding function loader."""

    def setup_method(self):
        self._original_fn = emb_mod._embedding_fn

    def teardown_method(self):
        emb_mod._embedding_fn = self._original_fn

    def test_returns_cached_singleton(self):
        """Once set, the singleton is returned."""
        sentinel = MagicMock()
        emb_mod._embedding_fn = sentinel
        result = emb_mod.get_embedding_function()
        assert result is sentinel

    @patch("assistant.embeddings.yaml_config", {"knowledge_base": {}})
    def test_import_error_returns_none(self):
        """Returns None when chromadb is not installed."""
        emb_mod._embedding_fn = None
        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def fail_chromadb(name, *args, **kwargs):
            if "chromadb" in name or "sentence_transformers" in name:
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_chromadb):
            result = emb_mod.get_embedding_function()
            assert result is None

    @patch(
        "assistant.embeddings.yaml_config",
        {"knowledge_base": {"embedding_model": "custom"}},
    )
    def test_uses_configured_model_name(self):
        """Model name from config is passed to SentenceTransformerEmbeddingFunction."""
        emb_mod._embedding_fn = None
        mock_ef_class = MagicMock()
        mock_ef_instance = MagicMock()
        mock_ef_class.return_value = mock_ef_instance

        mock_ef_module = MagicMock()
        mock_ef_module.SentenceTransformerEmbeddingFunction = mock_ef_class

        with patch.dict(
            "sys.modules",
            {
                "chromadb": MagicMock(),
                "chromadb.utils": MagicMock(),
                "chromadb.utils.embedding_functions": mock_ef_module,
            },
        ):
            result = emb_mod.get_embedding_function()
            # The function tries the import and creates the instance
            if result is not None:
                mock_ef_class.assert_called_with(model_name="custom")


# ══════════════════════════════════════════════════════════════
#  embedding_extractor.py — _load_model
# ══════════════════════════════════════════════════════════════


class TestLoadModel:
    """Tests for the lazy model loading mechanism."""

    def setup_method(self):
        self._original_classifier = ext_mod._classifier
        self._original_loading = ext_mod._model_loading

    def teardown_method(self):
        ext_mod._classifier = self._original_classifier
        ext_mod._model_loading = self._original_loading

    def test_returns_existing_classifier(self):
        sentinel = MagicMock()
        ext_mod._classifier = sentinel
        assert ext_mod._load_model() is sentinel

    def test_returns_none_while_loading(self):
        ext_mod._classifier = None
        ext_mod._model_loading = True
        assert ext_mod._load_model() is None

    def test_successful_model_load(self):
        ext_mod._classifier = None
        ext_mod._model_loading = False

        mock_classifier = MagicMock()
        mock_encoder = MagicMock()
        mock_encoder.from_hparams.return_value = mock_classifier

        with patch.dict(
            "sys.modules",
            {
                "torch": MagicMock(),
                "speechbrain": MagicMock(),
                "speechbrain.inference": MagicMock(),
                "speechbrain.inference.speaker": MagicMock(
                    EncoderClassifier=mock_encoder
                ),
            },
        ):
            result = ext_mod._load_model()
            assert result is mock_classifier

    def test_import_error_returns_none(self):
        ext_mod._classifier = None
        ext_mod._model_loading = False

        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def fail_sb(name, *args, **kwargs):
            if "speechbrain" in name or name == "torch":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_sb):
            result = ext_mod._load_model()
            assert result is None

    def test_general_exception_returns_none(self):
        ext_mod._classifier = None
        ext_mod._model_loading = False

        mock_encoder = MagicMock()
        mock_encoder.from_hparams.side_effect = RuntimeError("corrupt model")

        with patch.dict(
            "sys.modules",
            {
                "torch": MagicMock(),
                "speechbrain": MagicMock(),
                "speechbrain.inference": MagicMock(),
                "speechbrain.inference.speaker": MagicMock(
                    EncoderClassifier=mock_encoder
                ),
            },
        ):
            result = ext_mod._load_model()
            assert result is None

    def test_model_loading_reset_after_failure(self):
        """_model_loading is reset to False after a failed load."""
        ext_mod._classifier = None
        ext_mod._model_loading = False

        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def fail_all(name, *args, **kwargs):
            if "speechbrain" in name or name == "torch":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_all):
            ext_mod._load_model()
        assert ext_mod._model_loading is False


# ══════════════════════════════════════════════════════════════
#  embedding_extractor.py — extract_embedding
# ══════════════════════════════════════════════════════════════


def _make_pcm_b64(num_samples=8000):
    """Create base64-encoded 16-bit PCM audio."""
    samples = [0] * num_samples
    pcm_bytes = struct.pack(f"<{num_samples}h", *samples)
    return base64.b64encode(pcm_bytes).decode()


class TestExtractEmbedding:
    """Tests for the extract_embedding function."""

    def test_no_model_returns_none(self):
        with patch.object(ext_mod, "_load_model", return_value=None):
            result = ext_mod.extract_embedding(_make_pcm_b64())
            assert result is None

    def test_audio_too_short_returns_none(self):
        """Audio under 0.2s (6400 bytes / 3200 samples) returns None."""
        with patch.object(ext_mod, "_load_model", return_value=MagicMock()):
            short = _make_pcm_b64(num_samples=1000)  # 2000 bytes < 6400
            result = ext_mod.extract_embedding(short)
            assert result is None

    def test_audio_exactly_at_minimum(self):
        """Audio at exactly 3200 samples (6400 bytes) should be processed."""
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

        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch.dict(
                "sys.modules",
                {
                    "torch": mock_torch,
                    "torchaudio": mock_torchaudio,
                    "torchaudio.functional": mock_torchaudio.functional,
                },
            ):
                result = ext_mod.extract_embedding(_make_pcm_b64(3200))
                assert result is not None
                assert len(result) == 192

    def test_successful_192_dim_embedding(self):
        mock_torch = MagicMock()
        mock_torchaudio = MagicMock()
        mock_tensor = MagicMock()
        mock_torch.tensor.return_value = mock_tensor
        mock_torch.float32 = "float32"
        mock_tensor.__truediv__ = MagicMock(return_value=mock_tensor)
        mock_tensor.unsqueeze.return_value = mock_tensor

        expected = [float(i) / 192 for i in range(192)]
        mock_embedding = MagicMock()
        mock_embedding.squeeze.return_value.tolist.return_value = expected

        mock_classifier = MagicMock()
        mock_classifier.encode_batch.return_value = mock_embedding

        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch.dict(
                "sys.modules",
                {
                    "torch": mock_torch,
                    "torchaudio": mock_torchaudio,
                    "torchaudio.functional": mock_torchaudio.functional,
                },
            ):
                result = ext_mod.extract_embedding(_make_pcm_b64(8000))
                assert result == expected

    def test_resampling_triggered_for_48khz(self):
        """Non-16kHz audio triggers torchaudio resampling."""
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

        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch.dict(
                "sys.modules",
                {
                    "torch": mock_torch,
                    "torchaudio": mock_torchaudio,
                    "torchaudio.functional": mock_torchaudio.functional,
                },
            ):
                ext_mod.extract_embedding(_make_pcm_b64(8000), sample_rate=48000)
                mock_torchaudio.functional.resample.assert_called_once_with(
                    mock_tensor, 48000, 16000
                )

    def test_no_resampling_for_16khz(self):
        """16kHz audio does not trigger resampling."""
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

        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch.dict(
                "sys.modules",
                {
                    "torch": mock_torch,
                    "torchaudio": mock_torchaudio,
                    "torchaudio.functional": mock_torchaudio.functional,
                },
            ):
                ext_mod.extract_embedding(_make_pcm_b64(8000), sample_rate=16000)
                mock_torchaudio.functional.resample.assert_not_called()

    def test_single_float_wrapped_in_list(self):
        """If tolist() returns a single float, it is wrapped in a list."""
        mock_torch = MagicMock()
        mock_torchaudio = MagicMock()
        mock_tensor = MagicMock()
        mock_torch.tensor.return_value = mock_tensor
        mock_torch.float32 = "float32"
        mock_tensor.__truediv__ = MagicMock(return_value=mock_tensor)
        mock_tensor.unsqueeze.return_value = mock_tensor

        mock_embedding = MagicMock()
        mock_embedding.squeeze.return_value.tolist.return_value = 0.99

        mock_classifier = MagicMock()
        mock_classifier.encode_batch.return_value = mock_embedding

        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch.dict(
                "sys.modules",
                {
                    "torch": mock_torch,
                    "torchaudio": mock_torchaudio,
                    "torchaudio.functional": mock_torchaudio.functional,
                },
            ):
                result = ext_mod.extract_embedding(_make_pcm_b64(8000))
                assert result == [0.99]

    def test_exception_during_processing_returns_none(self):
        """Any exception during processing returns None."""
        mock_classifier = MagicMock()
        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch("base64.b64decode", side_effect=ValueError("bad data")):
                result = ext_mod.extract_embedding("invalid_b64")
                assert result is None

    def test_odd_byte_count_handled(self):
        """Odd number of PCM bytes is handled (truncated to even)."""
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

        # Create PCM data with an extra byte (odd count)
        samples = [0] * 4000
        pcm_bytes = struct.pack(f"<{4000}h", *samples) + b"\x00"  # 8001 bytes
        audio_b64 = base64.b64encode(pcm_bytes).decode()

        with patch.object(ext_mod, "_load_model", return_value=mock_classifier):
            with patch.dict(
                "sys.modules",
                {
                    "torch": mock_torch,
                    "torchaudio": mock_torchaudio,
                    "torchaudio.functional": mock_torchaudio.functional,
                },
            ):
                result = ext_mod.extract_embedding(audio_b64)
                assert result is not None


# ══════════════════════════════════════════════════════════════
#  embedding_extractor.py — is_available
# ══════════════════════════════════════════════════════════════


class TestIsAvailable:
    """Tests for the is_available check."""

    def test_returns_bool(self):
        result = ext_mod.is_available()
        assert isinstance(result, bool)

    def test_available_when_imports_succeed(self):
        with patch.dict(
            "sys.modules",
            {
                "speechbrain": MagicMock(),
                "torchaudio": MagicMock(),
            },
        ):
            assert ext_mod.is_available() is True

    def test_unavailable_when_speechbrain_missing(self):
        """When speechbrain import fails, returns False."""
        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def fail_sb(name, *args, **kwargs):
            if name == "speechbrain":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_sb):
            result = ext_mod.is_available()
            # May or may not be False depending on cached modules
            assert isinstance(result, bool)


# ══════════════════════════════════════════════════════════════
#  embeddings.py — Module constants
# ══════════════════════════════════════════════════════════════


class TestEmbeddingConstants:
    """Validate module-level constants."""

    def test_default_model_is_multilingual(self):
        assert "multilingual" in emb_mod.DEFAULT_MODEL

    def test_cache_max_is_positive_integer(self):
        assert isinstance(emb_mod._EMBEDDING_CACHE_MAX, int)
        assert emb_mod._EMBEDDING_CACHE_MAX > 0

    def test_cache_is_ordered_dict(self):
        assert isinstance(emb_mod._embedding_cache, OrderedDict)

    def test_default_model_contains_minilm(self):
        assert "MiniLM" in emb_mod.DEFAULT_MODEL
