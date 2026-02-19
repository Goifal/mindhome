"""
Conversation Agent - Verbindet HA Voice Pipeline mit MindHome Assistant.

Phase 9: Erweitert um Voice-Metadaten, TTS-Volume-Steuerung,
SSML-Durchleitung und automatische Raumerkennung.
"""

import logging
import time
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
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    """MindHome Assistant als HA Conversation Agent.

    Leitet Spracheingaben aus der HA Assist-Pipeline
    an den MindHome Assistant Server (PC2) weiter.

    Phase 9 Features:
    - Voice-Metadaten (Wortanzahl, geschaetzte Dauer)
    - Automatische Raumerkennung aus Device-Kontext
    - TTS-Volume-Steuerung vor Sprachausgabe
    - SSML-Durchleitung an Piper TTS
    """

    _attr_has_entity_name = True
    _attr_name = "MindHome Assistant"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._url = entry.data["url"].rstrip("/")
        self._api_key = entry.data.get("api_key", "")
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        self._last_request_time: float = 0.0
        self._cached_speaker: str | None = None

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

        # Phase 9: Voice-Metadaten berechnen
        now = time.time()
        voice_metadata = self._build_voice_metadata(text, now)
        self._last_request_time = now

        # Room aus Device-Kontext ermitteln
        room = await self._detect_room(user_input)

        # Payload zusammenbauen
        payload = {"text": text, "person": person}
        if voice_metadata:
            payload["voice_metadata"] = voice_metadata
        if room:
            payload["room"] = room

        response_text = "Ich kann gerade nicht denken."
        tts_data = None

        try:
            session = async_get_clientsession(self.hass)
            headers = {}
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            async with session.post(
                f"{self._url}/api/assistant/chat",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response_text = data.get("response", "Keine Antwort.")
                    tts_data = data.get("tts")
                else:
                    _LOGGER.error(
                        "MindHome Assistant Fehler: HTTP %d", resp.status
                    )
                    response_text = "Da stimmt etwas nicht."
        except Exception as e:
            _LOGGER.error("MindHome Assistant nicht erreichbar: %s", e)
            response_text = (
                "Ich kann gerade nicht denken. "
                "Der Assistant-Server ist nicht erreichbar."
            )

        # Phase 9: TTS-Steuerung aus Antwort verarbeiten
        if tts_data:
            response_text = await self._handle_tts(tts_data, response_text)

        intent_response = IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_text)
        return ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
        )

    # ------------------------------------------------------------------
    # Phase 9: Voice-Metadaten
    # ------------------------------------------------------------------

    def _build_voice_metadata(self, text: str, now: float) -> dict:
        """Berechnet Voice-Metadaten aus dem transkribierten Text.

        Da die HA Assist-Pipeline keine Audio-Rohdaten an den
        Conversation Agent weitergibt, berechnen wir was wir koennen:
        - Wortanzahl
        - Geschaetzte Sprechdauer (Deutsch: ~130 WPM)
        - Geschaetzte WPM
        - Schnelle Nachfrage-Erkennung
        """
        words = text.split()
        word_count = len(words)

        # Geschaetzte Sprechdauer: Deutsch ~130 WPM = ~2.2 Woerter/Sek
        estimated_duration = word_count / 2.2 if word_count > 0 else 0.5
        estimated_wpm = 130  # Durchschnitt

        metadata = {
            "word_count": word_count,
            "duration": round(estimated_duration, 1),
            "wpm": estimated_wpm,
            "source": "ha_assist_pipeline",
        }

        # Kurze Befehle (<= 3 Woerter) deuten auf knappe Sprechweise hin
        if word_count <= 3:
            metadata["wpm"] = 160  # Schneller Befehlston

        # Schnelle Nachfrage: Wenn letzter Request < 5 Sekunden her
        if self._last_request_time > 0:
            gap = now - self._last_request_time
            if gap < 5 and word_count > 1:
                metadata["rapid_follow_up"] = True
                metadata["wpm"] = 180  # Deutet auf Ungeduld/Stress hin

        return metadata

    # ------------------------------------------------------------------
    # Phase 9: Raumerkennung
    # ------------------------------------------------------------------

    async def _detect_room(
        self, user_input: ConversationInput
    ) -> str | None:
        """Ermittelt den Raum aus dem Device-Kontext.

        Wenn die Spracheingabe von einem Voice-Satellite kommt,
        hat dieser ein zugewiesenes Area (Raum) in HA.
        """
        device_id = getattr(user_input, "device_id", None)
        if not device_id:
            return None

        try:
            dev_reg = dr.async_get(self.hass)
            device = dev_reg.async_get(device_id)
            if device and device.area_id:
                area_reg = ar.async_get(self.hass)
                area = area_reg.async_get(device.area_id)
                if area:
                    _LOGGER.debug("Room detected: %s", area.name)
                    return area.name
        except Exception as e:
            _LOGGER.debug("Room detection fehlgeschlagen: %s", e)

        return None

    # ------------------------------------------------------------------
    # Phase 9: TTS-Steuerung (Volume + SSML)
    # ------------------------------------------------------------------

    async def _handle_tts(self, tts_data: dict, plain_text: str) -> str:
        """Verarbeitet TTS-Daten aus der Assistant-Antwort.

        1. Setzt Volume auf dem TTS-Speaker (ggf. Raum-spezifisch)
        2. Gibt SSML zurueck wenn verfuegbar (sonst Plaintext)
        """
        # Phase 10: Raum-spezifischen Speaker nutzen falls vorhanden
        target_speaker = tts_data.get("target_speaker")

        # Volume setzen vor TTS-Ausgabe
        volume = tts_data.get("volume")
        if volume is not None:
            await self._set_tts_volume(volume, target_speaker=target_speaker)

        # SSML verwenden wenn verfuegbar und gueltig
        ssml = tts_data.get("ssml", "")
        if ssml and ssml.strip().startswith("<speak"):
            return ssml

        return plain_text

    async def _set_tts_volume(self, volume: float, target_speaker: str | None = None):
        """Setzt die Lautstaerke des TTS-Speakers vor der Ausgabe.

        Wird aufgerufen BEVOR die Pipeline den Text an Piper TTS
        weitergibt, sodass die Lautstaerke schon korrekt ist.

        Phase 10: Nutzt target_speaker fuer Multi-Room-TTS-Routing.
        """
        speaker = target_speaker or await self._find_tts_speaker()
        if not speaker:
            _LOGGER.debug("Kein TTS-Speaker gefunden fuer Volume-Steuerung")
            return

        try:
            await self.hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": speaker, "volume_level": volume},
                blocking=True,
            )
            _LOGGER.debug(
                "TTS Volume gesetzt: %.2f auf %s", volume, speaker
            )
        except Exception as e:
            _LOGGER.warning("Volume setzen fehlgeschlagen: %s", e)

    async def _find_tts_speaker(self) -> str | None:
        """Findet den Media-Player fuer TTS-Ausgabe.

        Sucht nach Media-Playern in dieser Reihenfolge:
        1. Gecachter Speaker (wenn noch verfuegbar)
        2. Speaker mit 'tts', 'speaker', 'vlc', 'mpd' im Namen
        3. Erster verfuegbarer Media-Player
        """
        # Cache pruefen
        if self._cached_speaker:
            state = self.hass.states.get(self._cached_speaker)
            if state and state.state != "unavailable":
                return self._cached_speaker
            self._cached_speaker = None

        states = self.hass.states.async_all("media_player")

        # Bevorzuge TTS-typische Speaker
        preferred_keywords = ("tts", "speaker", "vlc", "mpd", "piper")
        for state in states:
            if state.state == "unavailable":
                continue
            if any(kw in state.entity_id for kw in preferred_keywords):
                self._cached_speaker = state.entity_id
                return state.entity_id

        # Fallback: Erster verfuegbarer Media-Player
        for state in states:
            if state.state != "unavailable":
                self._cached_speaker = state.entity_id
                return state.entity_id

        return None
