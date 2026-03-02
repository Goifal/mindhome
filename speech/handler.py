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
        initial_prompt: str = "",
        hotwords: str = "",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.wyoming_info_event = wyoming_info.event()
        self.model_name = model_name
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.redis_url = redis_url
        self.initial_prompt = initial_prompt
        self.hotwords = hotwords

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
            await self.write_event(self.wyoming_info_event)
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

        # STT-4: Dynamischen Kontext aus Redis laden (letzte User-Saetze)
        # brain.py schreibt nach jeder Verarbeitung die letzten Saetze nach Redis.
        # Das gibt Whisper Gespraechskontext → bessere Erkennung von Referenzen.
        dynamic_context = ""
        try:
            redis = await _get_redis(self.redis_url)
            if redis:
                dynamic_context = await redis.get("mha:stt:recent_context") or ""
        except Exception:
            pass  # Redis-Fehler sind nicht kritisch

        # C-7: Lock serialisiert Transkriptionen (CTranslate2 nicht thread-safe)
        # I-10: Timeout verhindert endlose Haenger bei korruptem Audio
        loop = asyncio.get_running_loop()
        async with _get_model_lock():
            try:
                text = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, self._transcribe, audio_bytes, dynamic_context
                    ),
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

    def _transcribe(self, audio_bytes: bytes, dynamic_context: str = "") -> str:
        """Transkribiert PCM-Audio mit faster-whisper (synchron, fuer Thread)."""
        model = _get_whisper_model(self.model_name, self.device, self.compute_type)

        # PCM 16-bit signed → numpy float32 [-1.0, 1.0]
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if len(audio_array) < 1600:  # < 0.1s bei 16kHz
            return ""

        # STT-1: Audio-Normalisierung — Lautstaerke auf einheitliches Niveau bringen.
        # Zu leise Aufnahmen (weit vom Mikro) werden verstaerkt,
        # zu laute (Clipping) werden reduziert.
        audio_array = self._normalize_audio(audio_array)

        # STT-5: Adaptive beam_size — kurze Utterances (<2s) bekommen
        # groesseren Beam weil der Speed-Overhead minimal ist,
        # aber die Qualitaet deutlich steigt.
        audio_duration_sec = len(audio_array) / 16000.0
        effective_beam = self.beam_size
        if audio_duration_sec < 2.0 and self.beam_size < 5:
            effective_beam = 5
            logger.debug("Adaptive beam: %d → %d (kurzes Audio: %.1fs)",
                         self.beam_size, effective_beam, audio_duration_sec)

        # Gemeinsame Transcribe-Parameter
        _transcribe_kwargs = {
            "language": self.language,
            "beam_size": effective_beam,
            # Anti-Hallucination: Whisper halluziniert manchmal in stillen Passagen
            # repetition_penalty reduziert wiederholte Phrasen
            "repetition_penalty": 1.2,
            # no_speech_threshold: Segmente mit hoher "kein Sprechen"-Wahrscheinlichkeit
            # werden verworfen (0.6 = Standard, 0.4 = strenger)
            "no_speech_threshold": 0.4,
            # hallucination_silence_threshold: Wenn eine Pause > N Sekunden erkannt wird
            # und trotzdem Text generiert wird → wahrscheinlich Halluzination → skippen
            "hallucination_silence_threshold": 1.0,
        }

        # STT-3: initial_prompt mit dynamischem Kontext kombinieren.
        # Statischer Prompt (Raumnamen, Vokabular) + letzte User-Saetze aus Redis.
        _full_prompt = self.initial_prompt
        if dynamic_context:
            # Dynamischen Kontext VOR den statischen Prompt setzen
            # (Whisper gewichtet den Anfang des Prompts staerker)
            _full_prompt = f"{dynamic_context} {self.initial_prompt}"
            # Whisper hat ein Limit fuer initial_prompt (~224 Tokens)
            # Kuerzen wenn zu lang (grob: 1 Token ≈ 4 Zeichen fuer Deutsch)
            if len(_full_prompt) > 800:
                _full_prompt = _full_prompt[:800]

        if _full_prompt:
            _transcribe_kwargs["initial_prompt"] = _full_prompt

        # hotwords: Boosted bestimmte Woerter im Beam-Search
        if self.hotwords:
            _transcribe_kwargs["hotwords"] = self.hotwords

        # W-9: VAD-Fallback — bei ValueError nochmal ohne VAD versuchen
        try:
            # S-3: min_silence von 500ms auf 250ms reduziert — schnellere
            # Endeerkennung bei kurzen Sprachbefehlen (~250ms Latenzgewinn)
            segments_list = list(model.transcribe(
                audio_array,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 250},
                **_transcribe_kwargs,
            )[0])
        except ValueError as e:
            logger.warning("VAD-Fehler, Retry ohne VAD: %s", e)
            segments_list = list(model.transcribe(
                audio_array,
                vad_filter=False,
                **_transcribe_kwargs,
            )[0])

        # STT-2: Confidence-Filter — Segmente mit sehr niedriger Confidence verwerfen.
        # avg_logprob < -1.0 bedeutet Whisper ist sich sehr unsicher.
        filtered_texts = []
        for seg in segments_list:
            seg_text = seg.text.strip()
            if not seg_text:
                continue
            # Confidence-Logging fuer Diagnostik
            logger.debug(
                "Segment: '%s' (avg_logprob=%.3f, no_speech=%.3f)",
                seg_text[:60], seg.avg_logprob, seg.no_speech_prob,
            )
            # Sehr niedrige Confidence → wahrscheinlich Halluzination oder Rauschen
            if seg.avg_logprob < -1.0:
                logger.info(
                    "Segment verworfen (low confidence): '%s' (logprob=%.3f)",
                    seg_text[:60], seg.avg_logprob,
                )
                continue
            # Hohe no_speech_prob → kein Sprechen erkannt, aber trotzdem Text generiert
            if seg.no_speech_prob > 0.8:
                logger.info(
                    "Segment verworfen (no_speech): '%s' (no_speech=%.3f)",
                    seg_text[:60], seg.no_speech_prob,
                )
                continue
            filtered_texts.append(seg_text)

        text = " ".join(filtered_texts)
        return text.strip()

    @staticmethod
    def _normalize_audio(audio_array: np.ndarray, target_rms: float = 0.1) -> np.ndarray:
        """Normalisiert Audio-Lautstaerke auf ein einheitliches Niveau.

        Berechnet den RMS (Root Mean Square) und skaliert das Signal
        auf target_rms (~-20dB). Verhindert Clipping bei > 0.95.

        Dies hilft bei:
        - Zu leisen Aufnahmen (User weit vom Mikro)
        - Unterschiedlichen Mikrofon-Empfindlichkeiten pro Raum
        - Schwankender Lautstaerke zwischen Personen
        """
        if len(audio_array) == 0:
            return audio_array

        # RMS berechnen
        rms = np.sqrt(np.mean(audio_array ** 2))
        if rms < 1e-6:  # Stille — nicht verstaerken (wuerde nur Rauschen verstaerken)
            return audio_array

        # Skalierungsfaktor berechnen (mit Clipping-Schutz)
        gain = target_rms / rms
        # Gain begrenzen: max 10x Verstaerkung (vermeidet Rausch-Explosion),
        # min 0.1x Reduktion (bei extrem lautem Signal)
        gain = np.clip(gain, 0.1, 10.0)

        normalized = audio_array * gain

        # Clipping verhindern — Werte auf [-0.95, 0.95] begrenzen
        peak = np.max(np.abs(normalized))
        if peak > 0.95:
            normalized = normalized * (0.95 / peak)

        if abs(gain - 1.0) > 0.1:
            logger.debug("Audio normalisiert: RMS %.4f → %.4f (gain=%.2fx)", rms, target_rms, gain)

        return normalized

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
