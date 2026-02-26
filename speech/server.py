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

from handler import WhisperEmbeddingHandler, _get_whisper_model, _get_embedding_model, close_redis

logger = logging.getLogger(__name__)


def main():
    """Entry Point — startet den Wyoming ASR Server."""
    logging.basicConfig(
        level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Konfiguration aus Umgebungsvariablen
    model = os.getenv("WHISPER_MODEL", "small")
    language = os.getenv("WHISPER_LANGUAGE", "de")
    device = os.getenv("SPEECH_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE", "int8")

    # WHISPER_MODEL kann "small-int8" enthalten — Compute-Typ abtrennen
    _compute_suffixes = ("int8", "float16", "float32")
    if "-" in model and model.rsplit("-", 1)[1] in _compute_suffixes:
        model, compute_type = model.rsplit("-", 1)
    # S-2: beam_size=1 (greedy) ist ~40% schneller als beam_size=5
    # bei minimaler Qualitaetseinbusse fuer kurze Sprachbefehle.
    # Ueber WHISPER_BEAM_SIZE konfigurierbar falls noetig.
    beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
    port = int(os.getenv("WHISPER_PORT", "10300"))
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

    logger.info(
        "MindHome Speech Server: model=%s, lang=%s, device=%s, compute=%s, port=%d",
        model, language, device, compute_type, port,
    )

    # Wyoming Service-Info (wird bei Describe-Events zurueckgegeben)
    # Struktur orientiert sich an der offiziellen wyoming-faster-whisper Implementation
    wyoming_info = Info(
        asr=[
            AsrProgram(
                name="faster-whisper",
                description="Faster Whisper transcription with CTranslate2",
                attribution=Attribution(
                    name="Guillaume Klein",
                    url="https://github.com/guillaumekln/faster-whisper/",
                ),
                installed=True,
                version="1.0.0",
                models=[
                    AsrModel(
                        name=model,
                        description=model,
                        attribution=Attribution(
                            name="Systran",
                            url="https://huggingface.co/Systran",
                        ),
                        installed=True,
                        languages=[language],
                        version="1.1.1",
                    )
                ],
            )
        ],
    )

    # W-2: Modelle vorladen via globale Funktionen (nicht wegwerfen)
    logger.info("Lade Modelle vor...")
    _get_whisper_model(model, device, compute_type)
    _get_embedding_model(device)

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

    # I-1: Graceful Shutdown — asyncio.run() statt new_event_loop()
    # (identisch zur offiziellen wyoming-faster-whisper Implementation)
    try:
        asyncio.run(_run_server(server, handler_factory))
    except KeyboardInterrupt:
        logger.info("Server wird beendet...")


async def _run_server(server: AsyncServer, handler_factory):
    """Startet den Server und schliesst Redis beim Beenden."""
    try:
        await server.run(handler_factory)
    finally:
        await close_redis()


if __name__ == "__main__":
    main()
