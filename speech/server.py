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


def _build_initial_prompt() -> str:
    """Baut einen initial_prompt mit Smart-Home-Vokabular fuer bessere Whisper-Erkennung.

    Der initial_prompt gibt Whisper Kontext ueber erwartete Woerter.
    Das verbessert die Erkennung von Eigennamen, Raumnamen und
    deutschen Smart-Home-Begriffen erheblich.
    """
    # Raumnamen dynamisch aus room_profiles.yaml laden (falls gemountet)
    _room_names = []
    _config_path = os.getenv("ROOM_PROFILES_PATH", "/app/config/room_profiles.yaml")
    try:
        if os.path.exists(_config_path):
            import json as _json
            # Einfaches YAML-Parsing ohne PyYAML — nur die rooms-Keys extrahieren
            with open(_config_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Raumnamen aus YAML extrahieren (Einrueckung 2 Spaces unter "rooms:")
            in_rooms = False
            for line in content.splitlines():
                if line.strip() == "rooms:":
                    in_rooms = True
                    continue
                if in_rooms:
                    # Ende des rooms-Blocks (neue Top-Level-Section)
                    if line and not line.startswith(" ") and not line.startswith("#"):
                        break
                    # Room-Key: 2 Spaces Einrueckung, kein weiteres Nesting
                    stripped = line.rstrip()
                    if stripped and not stripped.startswith("#"):
                        indent = len(line) - len(line.lstrip())
                        if indent == 2 and stripped.endswith(":"):
                            key = stripped.strip().rstrip(":")
                            # key → menschenlesbarer Name
                            _name = key.replace("_", " ").title()
                            # Spezifische Korrekturen
                            _name = _name.replace("Ue", "ü").replace("Oe", "ö").replace("Ae", "ä")
                            _room_names.append(_name)
            if _room_names:
                logger.info("Raumnamen aus room_profiles.yaml geladen: %s", _room_names)
    except Exception as e:
        logger.debug("room_profiles.yaml nicht lesbar (ignoriert): %s", e)

    # Fallback: Standard-Raumnamen wenn keine Config gefunden
    if not _room_names:
        _room_names = [
            "Wohnzimmer", "Küche", "Schlafzimmer", "Badezimmer",
            "Büro", "Kinderzimmer", "Flur", "Ankleide", "Toilette",
        ]

    _rooms_str = ", ".join(_room_names)

    return (
        f"Jarvis, Smart Home Assistent. "
        f"Räume: {_rooms_str}. "
        f"Personen: Manuel, Julia. "
        f"Geräte: Rollladen, Jalousie, Licht, Lampe, Heizung, Thermostat, "
        f"Steckdose, Saugroboter, Waschmaschine, Trockner, Spülmaschine, "
        f"Markise, Sensor, Bewegungsmelder. "
        f"Befehle: einschalten, ausschalten, hochfahren, runterfahren, dimmen, "
        f"Temperatur, Helligkeit, Szene, Timer, Wecker, Rollladen hoch, "
        f"Licht an, Licht aus, Musik abspielen, Musik stopp."
    )


def _build_hotwords() -> str:
    """Baut eine hotwords-Liste mit den wichtigsten Smart-Home-Begriffen.

    Hotwords werden von faster-whisper im Beam-Search bevorzugt.
    Besonders nuetzlich fuer Eigennamen die Whisper sonst nicht kennt.
    """
    return (
        "Jarvis, Wohnzimmer, Küche, Schlafzimmer, Badezimmer, Büro, "
        "Kinderzimmer, Rollladen, Jalousie, Manuel, Julia"
    )


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

    # --- STT-Qualitaet: initial_prompt + hotwords ---
    # initial_prompt gibt Whisper Domain-Vokabular als Kontext.
    # Das verbessert die Erkennung von Eigennamen, Raumnamen und
    # Fachbegriffen erheblich (Whisper "erwartet" diese Woerter).
    initial_prompt = os.getenv("WHISPER_INITIAL_PROMPT", "")
    if not initial_prompt:
        initial_prompt = _build_initial_prompt()
    # hotwords: Komma-separierte Woerter die im Beam-Search geboostet werden.
    # Format: "Jarvis,Wohnzimmer,Rollladen" oder via Env-Var konfigurierbar.
    hotwords = os.getenv("WHISPER_HOTWORDS", "")
    if not hotwords:
        hotwords = _build_hotwords()

    logger.info(
        "MindHome Speech Server: model=%s, lang=%s, device=%s, compute=%s, beam=%d, port=%d",
        model, language, device, compute_type, beam_size, port,
    )
    logger.info("Initial prompt: %s", initial_prompt[:120] + "..." if len(initial_prompt) > 120 else initial_prompt)
    logger.info("Hotwords: %s", hotwords[:100] if hotwords else "(keine)")

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
        initial_prompt=initial_prompt,
        hotwords=hotwords,
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
