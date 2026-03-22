"""
MindHome Assistant - Custom Integration fuer Home Assistant.

Verbindet die HA Voice Pipeline (Whisper STT + Piper TTS)
mit dem MindHome Assistant Server.

Phase 9: Voice-Metadaten, TTS-Volume, SSML, Raumerkennung.
Phase 10: Jarvis Chat Lovelace Card fuer HA Dashboards.
"""

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DOMAIN = "mindhome_assistant"
PLATFORMS = [Platform.CONVERSATION]

CARD_URL = "/jarvis-chat-card.js"
CARD_PATH = Path(__file__).parent / "www" / "jarvis-chat-card.js"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MindHome Assistant from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "url": entry.data["url"],
        "api_key": entry.data.get("api_key", ""),
    }

    # Jarvis Chat Card als Lovelace-Ressource registrieren
    await _register_chat_card(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "MindHome Assistant v1.1.2 geladen: %s", entry.data["url"]
    )
    return True


async def _register_chat_card(hass: HomeAssistant) -> None:
    """Register the Jarvis Chat Card as a static frontend resource.

    Makes the card JS available at /jarvis-chat-card.js so it can be
    added as a Lovelace resource without manual file copying.
    """
    if DOMAIN + "_card_registered" in hass.data:
        return

    if not CARD_PATH.is_file():
        _LOGGER.warning(
            "Jarvis Chat Card nicht gefunden: %s", CARD_PATH
        )
        return

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
        )
        hass.data[DOMAIN + "_card_registered"] = True
        _LOGGER.info(
            "Jarvis Chat Card registriert: %s", CARD_URL
        )
    except Exception as exc:
        _LOGGER.warning("Chat Card Registrierung fehlgeschlagen: %s", exc)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
