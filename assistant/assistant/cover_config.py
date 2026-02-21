"""
Lokale Cover-Konfiguration (JSON-basiert).

Speichert Cover-Typ (shutter, garage_door, etc.) und enabled-Status
direkt auf dem Assistant, ohne Umweg ueber das Addon.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("mindhome-assistant")

_COVER_CONFIG_FILE = Path(os.environ.get("DATA_DIR", "/app/data")) / "cover_configs.json"


def load_cover_configs() -> dict:
    """Cover-Configs aus lokaler JSON-Datei laden."""
    try:
        if _COVER_CONFIG_FILE.exists():
            return json.loads(_COVER_CONFIG_FILE.read_text())
    except Exception as e:
        logger.warning("Cover-Config laden fehlgeschlagen: %s", e)
    return {}


def save_cover_configs(configs: dict) -> None:
    """Cover-Configs in lokale JSON-Datei speichern."""
    try:
        _COVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COVER_CONFIG_FILE.write_text(json.dumps(configs, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error("Cover-Config speichern fehlgeschlagen: %s", e)
        raise
