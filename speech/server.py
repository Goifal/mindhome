#!/usr/bin/env python3
"""
MindHome Speech Server — Wyoming STT mit Voice Embedding Extraktion.

Implementiert das Wyoming Protocol fuer Speech-to-Text (faster-whisper)
und extrahiert parallel ECAPA-TDNN Voice Embeddings fuer Speaker Recognition.

Port: 10300 (konfigurierbar ueber WHISPER_PORT)
Redis: Embeddings werden in mha:speaker:latest_embedding gespeichert
"""

import asyncio
import logging
import os
from functools import partial

from wyoming.info import AsrModel, AsrProgram, Attribution, Info
from wyoming.server import AsyncServer

from handler import WhisperEmbeddingHandler

logger = logging.getLogger(__name__)


def main():
    """Entry Point — startet den Wyoming ASR Server."""
    logging.basicConfig(
        level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Konfiguration aus Umgebungsvariablen
    model = os.getenv("WHISPER_MODEL", "small-int8")
    language = os.getenv("WHISPER_LANGUAGE", "de")
    device = os.getenv("SPEECH_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE", "int8")
    beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    port = int(os.getenv("WHISPER_PORT", "10300"))
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

    logger.info(
        "MindHome Speech Server: model=%s, lang=%s, device=%s, compute=%s, port=%d",
        model, language, device, compute_type, port,
    )

    # Wyoming Service-Info (wird bei Describe-Events zurueckgegeben)
    wyoming_info = Info(
        asr=[
            AsrProgram(
                name="MindHome Whisper",
                description="faster-whisper STT + ECAPA-TDNN Speaker Embeddings",
                attribution=Attribution(
                    name="MindHome",
                    url="",
                ),
                installed=True,
                models=[
                    AsrModel(
                        name=model,
                        description=f"faster-whisper {model}",
                        attribution=Attribution(
                            name="Systran",
                            url="https://github.com/SYSTRAN/faster-whisper",
                        ),
                        installed=True,
                        languages=[language],
                    )
                ],
            )
        ],
    )

    # Modelle vorladen (damit der erste Request schnell ist)
    logger.info("Lade Modelle vor...")
    _preload_models(model, device, compute_type)

    # Wyoming TCP Server starten
    server = AsyncServer.from_uri(f"tcp://0.0.0.0:{port}")
    logger.info("Wyoming STT Server lauscht auf Port %d", port)

    handler_factory = partial(
        WhisperEmbeddingHandler,
        wyoming_info=wyoming_info,
        model_name=model,
        language=language,
        device=device,
        compute_type=compute_type,
        beam_size=beam_size,
        redis_url=redis_url,
    )

    asyncio.run(server.run(handler_factory))


def _preload_models(model_name: str, device: str, compute_type: str):
    """Laedt Whisper + ECAPA-TDNN beim Start (nicht erst beim ersten Request)."""
    try:
        from faster_whisper import WhisperModel

        logger.info("Lade Whisper: %s (device=%s, compute=%s)...", model_name, device, compute_type)
        WhisperModel(model_name, device=device, compute_type=compute_type)
        logger.info("Whisper geladen: %s", model_name)
    except Exception as e:
        logger.error("Whisper laden fehlgeschlagen: %s", e)

    try:
        from speechbrain.inference.speaker import EncoderClassifier

        run_device = "cuda" if device == "cuda" else "cpu"
        logger.info("Lade ECAPA-TDNN (device=%s)...", run_device)
        EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="/app/models/spkrec-ecapa-voxceleb",
            run_opts={"device": run_device},
        )
        logger.info("ECAPA-TDNN geladen (192-dim)")
    except Exception as e:
        logger.warning("ECAPA-TDNN laden fehlgeschlagen: %s — Embeddings deaktiviert", e)


if __name__ == "__main__":
    main()
