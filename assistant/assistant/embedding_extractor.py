"""
Voice Embedding Extractor - Extrahiert Speaker-Embeddings aus Audio-Daten.

Nutzt SpeechBrain ECAPA-TDNN (~40MB) fuer 192-dimensionale Speaker-Embeddings.
Modell wird lazy geladen beim ersten Aufruf.
"""

import base64
import io
import logging
import struct
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-loaded Model (nur einmal geladen)
_classifier = None
_model_loading = False


def _load_model():
    """Laedt das SpeechBrain ECAPA-TDNN Modell (lazy, thread-safe)."""
    global _classifier, _model_loading
    if _classifier is not None:
        return _classifier
    if _model_loading:
        return None

    _model_loading = True
    try:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier

        logger.info("Lade Speaker-Embedding Modell (ECAPA-TDNN)...")
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="/tmp/speechbrain_models/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
        )
        logger.info("Speaker-Embedding Modell geladen (192-dim, ECAPA-TDNN)")
        return _classifier
    except ImportError:
        logger.warning("SpeechBrain nicht installiert — Voice Embeddings deaktiviert")
        return None
    except Exception as e:
        logger.error("Speaker-Embedding Modell laden fehlgeschlagen: %s", e)
        return None
    finally:
        _model_loading = False


def extract_embedding(audio_b64: str, sample_rate: int = 16000) -> Optional[list[float]]:
    """Extrahiert ein 192-dim Speaker-Embedding aus base64-kodierten PCM-Daten.

    Args:
        audio_b64: Base64-kodierte 16-bit PCM Audio-Daten (mono)
        sample_rate: Sample-Rate (default 16000 Hz)

    Returns:
        Liste von 192 Floats oder None bei Fehler
    """
    classifier = _load_model()
    if classifier is None:
        return None

    try:
        import torch
        import torchaudio

        # Base64 → PCM bytes
        pcm_bytes = base64.b64decode(audio_b64)

        if len(pcm_bytes) < 3200:  # Weniger als 0.1s bei 16kHz — zu kurz
            logger.debug("Audio zu kurz fuer Embedding (%d bytes)", len(pcm_bytes))
            return None

        # PCM 16-bit signed → float tensor
        num_samples = len(pcm_bytes) // 2
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes[:num_samples * 2])
        waveform = torch.tensor(samples, dtype=torch.float32) / 32768.0
        waveform = waveform.unsqueeze(0)  # [1, num_samples]

        # Resample falls noetig (Modell erwartet 16kHz)
        if sample_rate != 16000:
            waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)

        # Embedding extrahieren
        embedding = classifier.encode_batch(waveform)
        embedding_list = embedding.squeeze().tolist()

        # ECAPA-TDNN gibt 192-dim Vektor
        if isinstance(embedding_list, float):
            embedding_list = [embedding_list]

        logger.debug("Speaker-Embedding extrahiert (%d Dimensionen)", len(embedding_list))
        return embedding_list

    except Exception as e:
        logger.warning("Embedding-Extraktion fehlgeschlagen: %s", e)
        return None


def is_available() -> bool:
    """Prueft ob SpeechBrain verfuegbar ist (ohne Modell zu laden)."""
    try:
        import speechbrain  # noqa: F401
        import torchaudio  # noqa: F401
        return True
    except ImportError:
        return False
