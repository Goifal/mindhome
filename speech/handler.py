"""
Wyoming Event Handler — Whisper STT + ECAPA-TDNN Voice Embedding.

Verarbeitet Wyoming ASR Events:
1. Transcribe → Start einer neuen Transkription
2. AudioChunk → Sammelt Audio-Daten
3. AudioStop  → Transkription + Embedding-Extraktion → Transcript + Redis

Die Embedding-Extraktion laeuft parallel (fire-and-forget),
damit die Transkription nicht verzoegert wird.
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Optional

import numpy as np
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler

logger = logging.getLogger(__name__)

# ── Lazy-loaded Models (shared ueber alle Handler-Instanzen) ─────────────────

_whisper_model = None
_embedding_model = None
_redis_client = None
_init_lock = threading.Lock()

# C-7: asyncio.Lock serialisiert Transkriptionen (CTranslate2 ist nicht thread-safe)
_model_lock: Optional[asyncio.Lock] = None


def _get_model_lock() -> asyncio.Lock:
    """Gibt den shared asyncio.Lock zurueck (lazy-init)."""
    global _model_lock
    if _model_lock is None:
        _model_lock = asyncio.Lock()
    return _model_lock


def _get_whisper_model(model_name: str, device: str, compute_type: str):
    """Lazy-load faster-whisper Modell (thread-safe)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _init_lock:
        if _whisper_model is not None:
            return _whisper_model
        from faster_whisper import WhisperModel

        logger.info("Lade Whisper Modell: %s (device=%s, compute=%s)", model_name, device, compute_type)
        _whisper_model = WhisperModel(model_name, device=device, compute_type=compute_type)
        logger.info("Whisper Modell geladen: %s", model_name)
    return _whisper_model


def _get_embedding_model(device: str):
    """Lazy-load ECAPA-TDNN Embedding Modell (thread-safe)."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    with _init_lock:
        if _embedding_model is not None:
            return _embedding_model
        try:
            from speechbrain.inference.speaker import EncoderClassifier

            run_device = "cuda" if device == "cuda" else "cpu"
            logger.info("Lade ECAPA-TDNN (device=%s)...", run_device)
            _embedding_model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="/app/models/spkrec-ecapa-voxceleb",
                run_opts={"device": run_device},
            )
            logger.info("ECAPA-TDNN geladen (192-dim)")
        except Exception as e:
            logger.warning("ECAPA-TDNN laden fehlgeschlagen: %s — Embeddings deaktiviert", e)
    return _embedding_model


async def _get_redis(redis_url: str):
    """Lazy-load Redis-Verbindung."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as redis_async

            _redis_client = redis_async.from_url(redis_url, decode_responses=True)
            await _redis_client.ping()
            logger.info("Redis verbunden: %s", redis_url)
        except Exception as e:
            logger.warning("Redis nicht erreichbar: %s — Embeddings werden nicht gespeichert", e)
            _redis_client = None
    return _redis_client


# I-1: Graceful Redis Shutdown — verhindert offene Connections bei Container-Stop
async def close_redis():
    """Schliesst die Redis-Verbindung sauber (fuer Shutdown-Handler)."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("Redis-Verbindung geschlossen")
        except Exception as e:
            logger.debug("Redis close Fehler (ignoriert): %s", e)
        finally:
            _redis_client = None


# ── Wyoming Event Handler ────────────────────────────────────────────────────


class WhisperEmbeddingHandler(AsyncEventHandler):
    """Wyoming Handler: Whisper STT + parallele Voice Embedding Extraktion."""

    def __init__(
        self,
        *args,
        wyoming_info: Info,
        model_name: str = "small",
        language: str = "de",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        redis_url: str = "redis://redis:6379",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.wyoming_info = wyoming_info
        self.model_name = model_name
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.redis_url = redis_url

        # Audio-Buffer fuer aktuelle Session
        self._audio_bytes = bytearray()
        # Converter: normalisiert Audio auf 16kHz/16-bit/mono
        self._converter = AudioChunkConverter(rate=16000, width=2, channels=1)
        # W-8: Task-Referenz speichern damit GC den Task nicht cancelt
        self._embedding_task: Optional[asyncio.Task] = None
        # W-1: Request-ID fuer eindeutigen Redis Key
        self._request_id: str = ""

    async def handle_event(self, event: Event) -> bool:
        """Verarbeitet ein Wyoming Event.

        Returns True um die Verbindung offen zu halten.
        """
        if Describe.is_type(event.type):
            await self.write_event(self.wyoming_info.event())
            return True

        if Transcribe.is_type(event.type):
            # Neuer STT-Request: Buffer leeren + neue Request-ID
            self._audio_bytes = bytearray()
            self._request_id = uuid.uuid4().hex[:12]
            return True

        # I-9: AudioStart explizit handlen — Buffer sicherheitshalber leeren
        if AudioStart.is_type(event.type):
            self._audio_bytes = bytearray()
            return True

        if AudioChunk.is_type(event.type):
            chunk = AudioChunk.from_event(event)
            # Audio normalisieren (16kHz/16-bit/mono) und sammeln
            chunk = self._converter.convert(chunk)
            self._audio_bytes.extend(chunk.audio)
            return True

        if AudioStop.is_type(event.type):
            # Audio komplett — Transkription starten
            text = await self._process_audio()
            # Ergebnis an HA zuruecksenden
            await self.write_event(Transcript(text=text).event())
            return True

        return True

    async def _process_audio(self) -> str:
        """Transkribiert Audio und extrahiert parallel das Voice-Embedding."""
        if not self._audio_bytes:
            return ""

        audio_bytes = bytes(self._audio_bytes)
        self._audio_bytes = bytearray()
        start_time = time.monotonic()

        # C-7: Lock serialisiert Transkriptionen (CTranslate2 nicht thread-safe)
        # I-10: Timeout verhindert endlose Haenger bei korruptem Audio
        loop = asyncio.get_running_loop()
        async with _get_model_lock():
            try:
                text = await asyncio.wait_for(
                    loop.run_in_executor(None, self._transcribe, audio_bytes),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.error("Transkription Timeout (30s) — Audio uebersprungen (%.1fs Audio)",
                             len(audio_bytes) / (16000 * 2))
                return ""

        elapsed = time.monotonic() - start_time
        audio_duration = len(audio_bytes) / (16000 * 2)  # 16kHz, 16-bit
        logger.info(
            "Transkription: '%s' (%.1fs fuer %.1fs Audio, RTF=%.2f)",
            text[:80], elapsed, audio_duration,
            elapsed / audio_duration if audio_duration > 0 else 0,
        )

        # W-8: Embedding-Extraktion parallel starten, Referenz speichern
        self._embedding_task = asyncio.create_task(
            self._extract_and_store_embedding(audio_bytes)
        )

        return text

    def _transcribe(self, audio_bytes: bytes) -> str:
        """Transkribiert PCM-Audio mit faster-whisper (synchron, fuer Thread)."""
        model = _get_whisper_model(self.model_name, self.device, self.compute_type)

        # PCM 16-bit signed → numpy float32 [-1.0, 1.0]
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if len(audio_array) < 1600:  # < 0.1s bei 16kHz
            return ""

        # W-9: VAD-Fallback — bei ValueError nochmal ohne VAD versuchen
        try:
            segments, _info = model.transcribe(
                audio_array,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join(seg.text.strip() for seg in segments)
        except ValueError as e:
            logger.warning("VAD-Fehler, Retry ohne VAD: %s", e)
            segments, _info = model.transcribe(
                audio_array,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=False,
            )
            text = " ".join(seg.text.strip() for seg in segments)

        return text.strip()

    async def _extract_and_store_embedding(self, audio_bytes: bytes):
        """Extrahiert ECAPA-TDNN Embedding und speichert es in Redis.

        Laeuft als Background-Task — Fehler werden nur geloggt, nicht propagiert.
        """
        try:
            loop = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(
                None, self._extract_embedding, audio_bytes,
            )

            if not embedding:
                return

            # W-1: Request-spezifischer Key + "latest" Key fuer Kompatibilitaet
            redis = await _get_redis(self.redis_url)
            if redis:
                request_id = self._request_id or uuid.uuid4().hex[:12]
                pipe = redis.pipeline()
                # Spezifischer Key (fuer Request-Zuordnung)
                pipe.set(
                    f"mha:speaker:embedding:{request_id}",
                    json.dumps(embedding),
                    ex=60,
                )
                # Latest Key (Fallback fuer einfachen Zugriff)
                pipe.set(
                    "mha:speaker:latest_embedding",
                    json.dumps(embedding),
                    ex=60,
                )
                await pipe.execute()
                logger.debug(
                    "Voice-Embedding gespeichert (%d dim, TTL 60s, id=%s)",
                    len(embedding), request_id,
                )

        except Exception as e:
            logger.warning("Embedding-Extraktion fehlgeschlagen: %s", e)

    def _extract_embedding(self, audio_bytes: bytes) -> Optional[list[float]]:
        """Extrahiert 192-dim ECAPA-TDNN Embedding (synchron, fuer Thread)."""
        model = _get_embedding_model(self.device)
        if model is None:
            return None

        import torch

        # PCM 16-bit → float32 tensor
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if len(audio_array) < 3200:  # < 0.2s — zu kurz fuer Embedding
            return None

        waveform = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)

        # Embedding extrahieren (ECAPA-TDNN → 192-dim Vektor)
        embedding = model.encode_batch(waveform)
        embedding_list = embedding.squeeze().tolist()

        if isinstance(embedding_list, float):
            embedding_list = [embedding_list]

        return embedding_list
