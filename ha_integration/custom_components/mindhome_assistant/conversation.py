"""Conversation Agent - Verbindet HA Voice Pipeline mit MindHome Assistant."""

import logging
from typing import Literal

import aiohttp

from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.intent import IntentResponse

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation platform."""
    async_add_entities([MindHomeAssistantAgent(hass, config_entry)])


class MindHomeAssistantAgent(ConversationEntity):
    """MindHome Assistant als HA Conversation Agent."""

    _attr_has_entity_name = True
    _attr_name = "MindHome Assistant"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._url = entry.data["url"].rstrip("/")
        self._attr_unique_id = f"{entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> Literal["*"]:
        """Unterstuetzte Sprachen (alle)."""
        return "*"

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Verarbeitet Spracheingabe ueber MindHome Assistant API."""
        text = user_input.text
        person = user_input.context.user_id if user_input.context else None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._url}/api/assistant/chat",
                    json={"text": text, "person": person},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        response_text = data.get("response", "Keine Antwort.")
                    else:
                        _LOGGER.error("MindHome Assistant Fehler: HTTP %d", resp.status)
                        response_text = "Da stimmt etwas nicht."
        except (aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.error("MindHome Assistant nicht erreichbar: %s", e)
            response_text = "Ich kann gerade nicht denken. Der Assistant-Server ist nicht erreichbar."

        intent_response = IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_text)
        return ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
        )
