"""
Sound Manager - Phase 9: Akustische Identitaet fuer Jarvis.

Verwaltet Event-Sounds und spielt sie ueber Home Assistant ab.
Jedes Event hat einen zugeordneten Sound der automatisch
bei passender Gelegenheit abgespielt wird.

Sound-Quellen (Prioritaet):
  1. Eigene Soundfiles: /config/sounds/{event}.mp3 (wenn vorhanden)
  2. TTS-Chime: Kurze TTS-Nachricht als akustisches Signal

Sound-Events:
  listening  - Soft chime (Jarvis hoert zu)
  confirmed  - Short ping (Befehl bestaetigt)
  warning    - Two-tone alert
  alarm      - Urgent tone
  doorbell   - Soft bell
  greeting   - Welcome chime
  error      - Error tone
  goodnight  - Gute-Nacht-Melodie
"""

import logging
import time
from datetime import datetime
from typing import Optional

from .config import yaml_config, settings
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# TTS-Chime-Texte als Fallback wenn keine Soundfiles vorhanden
# Kurze, praegnante Texte die als akustisches Signal dienen
TTS_CHIME_TEXTS = {
    "listening": "Hmm?",
    "confirmed": "Erledigt.",
    "warning": "Achtung.",
    "alarm": "Alarm! Alarm!",
    "doorbell": "Es klingelt.",
    "greeting": "Guten Tag.",
    "error": "Da stimmt etwas nicht.",
    "goodnight": "Gute Nacht.",
}

DEFAULT_SOUND_DESCRIPTIONS = {
    "listening": "Kurzer sanfter Ton",
    "confirmed": "Kurzer Bestaetigungston",
    "warning": "Zweifach-Warnton",
    "alarm": "Dringender Alarmton",
    "doorbell": "Sanfter Klingelton",
    "greeting": "Willkommens-Melodie",
    "error": "Fehlerton",
    "goodnight": "Gute-Nacht-Melodie",
}


class SoundManager:
    """Verwaltet die akustische Identitaet von Jarvis."""

    # Entity-IDs die KEINE TTS-Speaker sind (TVs, Receiver, etc.)
    _EXCLUDED_SPEAKER_PATTERNS = (
        "tv", "fernseher", "television", "fire_tv", "firetv", "apple_tv",
        "appletv", "chromecast", "roku", "shield", "receiver", "avr",
        "denon", "marantz", "yamaha_receiver", "onkyo", "pioneer",
        "soundbar", "xbox", "playstation", "ps5", "ps4", "nintendo",
        "kodi", "plex", "emby", "jellyfin", "vlc", "mpd",
    )

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client

        # Konfiguration
        sound_cfg = yaml_config.get("sounds", {})
        self.enabled = sound_cfg.get("enabled", True)
        self.event_sounds = sound_cfg.get("events", {})
        self.night_volume_factor = sound_cfg.get("night_volume_factor", 0.4)
        self.sound_base_url = sound_cfg.get("sound_base_url", "/local/sounds")

        # Volume-Konfiguration
        vol_cfg = yaml_config.get("volume", {})
        self.evening_start = vol_cfg.get("evening_start", 22)
        self.morning_start = vol_cfg.get("morning_start", 7)

        # Letzte Sounds (Anti-Spam)
        self._last_sound_time: dict[str, float] = {}
        self._min_interval = 2.0  # Mindestens 2s zwischen gleichen Sounds

        # Stille Events: Nur Volume-Ping, kein TTS (zu stoerend)
        self._silent_events = {"listening", "confirmed", "greeting", "goodnight"}

        logger.info(
            "SoundManager initialisiert (enabled: %s, events: %d)",
            self.enabled, len(self.event_sounds),
        )

    def _is_tts_speaker(self, entity_id: str, attributes: dict = None) -> bool:
        """Prueft ob ein media_player ein echter TTS-faehiger Speaker ist.

        Schliesst TVs, Receiver, Streaming-Boxen etc. aus.
        """
        if not entity_id.startswith("media_player."):
            return False

        entity_lower = entity_id.lower()
        for pattern in self._EXCLUDED_SPEAKER_PATTERNS:
            if pattern in entity_lower:
                return False

        # Zusaetzlich: Attribute-basierte Erkennung (wenn verfuegbar)
        if attributes:
            device_class = (attributes.get("device_class") or "").lower()
            if device_class in ("tv", "receiver"):
                return False

        return True

    async def play_event_sound(
        self,
        event: str,
        room: Optional[str] = None,
        volume: Optional[float] = None,
    ) -> bool:
        """
        Spielt einen Event-Sound ab.

        Args:
            event: Event-Name (listening, confirmed, warning, etc.)
            room: Zielraum (optional, sonst Standard-Speaker)
            volume: Lautstaerke 0.0-1.0 (optional, sonst automatisch)

        Returns:
            True wenn erfolgreich
        """
        if not self.enabled:
            return False

        # Anti-Spam: Nicht denselben Sound doppelt abspielen
        now = time.time()
        last = self._last_sound_time.get(event, 0)
        if now - last < self._min_interval:
            return False
        self._last_sound_time[event] = now

        # Volume bestimmen
        if volume is None:
            volume = self._get_auto_volume(event)

        # Speaker finden (erst Config-Mapping, dann Raum-Match, dann Default)
        speaker_entity = await self._resolve_speaker(room)
        if not speaker_entity:
            logger.debug("Kein Speaker fuer Sound '%s' gefunden", event)
            return False

        # Volume setzen
        try:
            await self.ha.call_service(
                "media_player", "volume_set",
                {"entity_id": speaker_entity, "volume_level": volume},
            )
        except Exception as e:
            logger.debug("Volume setzen fehlgeschlagen: %s", e)

        # 1. Versuch: Soundfile abspielen (media_player.play_media)
        sound_played = await self._play_sound_file(event, speaker_entity)
        if sound_played:
            logger.debug("Sound '%s' als Datei abgespielt (Speaker: %s)", event, speaker_entity)
            return True

        # 2. Fallback: TTS-Chime (nur fuer nicht-stille Events)
        if event not in self._silent_events:
            tts_played = await self._play_tts_chime(event, speaker_entity)
            if tts_played:
                logger.debug("Sound '%s' als TTS abgespielt (Speaker: %s)", event, speaker_entity)
                return True

        logger.debug("Sound '%s' nur als Volume-Ping (Speaker: %s)", event, speaker_entity)
        return True

    async def _play_sound_file(self, event: str, speaker_entity: str) -> bool:
        """Versucht einen Soundfile via media_player.play_media abzuspielen.

        Phase 9.2: Sucht konfigurierte Mappings und mehrere Formate.
        """
        # 1. Konfiguriertes Mapping (custom URL aus settings.yaml)
        if event in self.event_sounds:
            custom_url = self.event_sounds[event]
            try:
                success = await self.ha.call_service(
                    "media_player", "play_media",
                    {
                        "entity_id": speaker_entity,
                        "media_content_id": custom_url,
                        "media_content_type": "music",
                    },
                )
                if success:
                    return True
            except Exception as e:
                logger.debug("Custom Sound '%s' fehlgeschlagen: %s", event, e)

        # 2. Standard-Pfad mit mehreren Formaten (mp3, wav, ogg, flac)
        for ext in (".mp3", ".wav", ".ogg", ".flac"):
            sound_url = f"{self.sound_base_url}/{event}{ext}"
            try:
                success = await self.ha.call_service(
                    "media_player", "play_media",
                    {
                        "entity_id": speaker_entity,
                        "media_content_id": sound_url,
                        "media_content_type": "music",
                    },
                )
                if success:
                    return True
            except Exception as e:
                logger.debug("Sound-Datei %s nicht abspielbar: %s", sound_url, e)
                continue

        return False

    async def _play_tts_chime(self, event: str, speaker_entity: str) -> bool:
        """Spielt einen kurzen TTS-Text als akustisches Signal."""
        chime_text = TTS_CHIME_TEXTS.get(event)
        if not chime_text:
            return False

        # TTS-Entity finden (Piper bevorzugt)
        tts_entity = await self._find_tts_entity()
        if tts_entity:
            try:
                return await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker_entity,
                        "message": chime_text,
                        "language": "de",
                    },
                )
            except Exception as e:
                logger.debug("TTS-Chime fehlgeschlagen: %s", e)

        return False

    def _get_auto_volume(self, event: str) -> float:
        """Bestimmt die automatische Lautstaerke basierend auf Tageszeit und Event."""
        hour = datetime.now().hour
        is_night = hour >= self.evening_start or hour < self.morning_start

        # Basis-Volume pro Event-Typ
        base_volumes = {
            "listening": 0.3,
            "confirmed": 0.4,
            "warning": 0.7,
            "alarm": 1.0,
            "doorbell": 0.6,
            "greeting": 0.5,
            "error": 0.5,
            "goodnight": 0.3,
        }
        base = base_volumes.get(event, 0.5)

        # Nacht-Faktor anwenden (ausser Alarm)
        if is_night and event not in ("alarm",):
            base *= self.night_volume_factor

        return round(min(1.0, base), 2)

    async def _resolve_speaker(self, room: Optional[str] = None) -> Optional[str]:
        """Findet den besten Speaker: Config-Mapping > Raum-Match > Default."""
        # 1. Konfiguriertes Mapping pruefen
        if room:
            room_speakers = yaml_config.get("multi_room", {}).get("room_speakers", {})
            room_lower = room.lower().replace(" ", "_")
            for cfg_room, entity_id in (room_speakers or {}).items():
                if cfg_room.lower() == room_lower:
                    return entity_id

        # 2. Entity-Name-Matching im Raum
        if room:
            speaker = await self._find_speaker(room)
            if speaker:
                return speaker

        # 3. Standard-Speaker
        return await self._find_default_speaker()

    async def _find_speaker(self, room: str) -> Optional[str]:
        """Findet einen TTS-faehigen Speaker im angegebenen Raum.

        Schliesst TVs und andere nicht-TTS-Geraete aus.
        """
        states = await self.ha.get_states()
        if not states:
            return None
        room_lower = room.lower().replace(" ", "_")
        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})
            if (
                room_lower in entity_id
                and self._is_tts_speaker(entity_id, attributes)
            ):
                return entity_id
        return None

    async def _find_default_speaker(self) -> Optional[str]:
        """Findet den Standard-Speaker (kein TV/Receiver)."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})
            if self._is_tts_speaker(entity_id, attributes):
                return entity_id
        return None

    async def _find_tts_entity(self) -> Optional[str]:
        """Findet die TTS-Entity (Piper bevorzugt)."""
        states = await self.ha.get_states()
        if not states:
            return None
        # Piper bevorzugen
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("tts.") and "piper" in entity_id:
                return entity_id
        # Fallback: Erste TTS-Entity
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("tts."):
                return entity_id
        return None

    async def speak_response(
        self,
        text: str,
        room: Optional[str] = None,
        tts_data: Optional[dict] = None,
    ) -> bool:
        """Spricht eine Jarvis-Antwort ueber einen HA-Speaker aus.

        Args:
            text: Der zu sprechende Text.
            room: Zielraum (optional, sonst Default-Speaker).
            tts_data: TTS-Metadaten (volume, speed, ssml, target_speaker).

        Returns:
            True wenn erfolgreich.
        """
        if not self.enabled:
            return False

        tts_data = tts_data or {}

        # Speaker bestimmen: expliziter target_speaker > room > default
        speaker_entity = tts_data.get("target_speaker")
        if not speaker_entity:
            speaker_entity = await self._resolve_speaker(room)
        if not speaker_entity:
            logger.debug("Kein Speaker fuer Sprachausgabe gefunden")
            return False

        # Volume setzen
        volume = tts_data.get("volume", 0.8)
        try:
            await self.ha.call_service(
                "media_player", "volume_set",
                {"entity_id": speaker_entity, "volume_level": volume},
            )
        except Exception as e:
            logger.debug("Volume setzen fehlgeschlagen: %s", e)

        # SSML-Text bevorzugen, sonst Plaintext
        speak_text = tts_data.get("ssml", text) if tts_data.get("ssml") else text

        # TTS-Entity finden und sprechen
        tts_entity = await self._find_tts_entity()
        if tts_entity:
            try:
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker_entity,
                        "message": speak_text,
                        "language": "de",
                    },
                )
                if success:
                    logger.info(
                        "Jarvis spricht via %s auf %s (vol: %.1f)",
                        tts_entity, speaker_entity, volume,
                    )
                    return True
            except Exception as e:
                logger.warning("TTS speak fehlgeschlagen: %s", e)

        # Kein cloud_say Fallback — Piper (lokal) ist der einzige TTS-Service.
        # cloud_say wuerde nur 500er erzeugen wenn kein Cloud-TTS konfiguriert ist.
        logger.warning("TTS-Ausgabe fehlgeschlagen — kein TTS-Service verfuegbar")
        return False

    def get_sound_info(self) -> dict:
        """Gibt Infos ueber verfuegbare Sounds zurueck."""
        return {
            "enabled": self.enabled,
            "events": self.event_sounds,
            "descriptions": DEFAULT_SOUND_DESCRIPTIONS,
            "night_volume_factor": self.night_volume_factor,
            "sound_base_url": self.sound_base_url,
        }
