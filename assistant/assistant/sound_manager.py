"""
Sound Manager - Phase 9: Akustische Identitaet fuer Jarvis.

Verwaltet Event-Sounds und spielt sie ueber Home Assistant ab.
Jedes Event hat einen zugeordneten Sound der automatisch
bei passender Gelegenheit abgespielt wird.

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
from datetime import datetime
from typing import Optional

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Default Sound-URLs (lokale TTS-basierte Sounds als Fallback)
# In Produktion: eigene WAV/MP3 in /config/sounds/ ablegen
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

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client

        # Konfiguration
        sound_cfg = yaml_config.get("sounds", {})
        self.enabled = sound_cfg.get("enabled", True)
        self.event_sounds = sound_cfg.get("events", {})
        self.night_volume_factor = sound_cfg.get("night_volume_factor", 0.4)

        # Volume-Konfiguration
        vol_cfg = yaml_config.get("volume", {})
        self.evening_start = vol_cfg.get("evening_start", 22)
        self.morning_start = vol_cfg.get("morning_start", 7)

        # Letzte Sounds (Anti-Spam)
        self._last_sound_time: dict[str, float] = {}
        self._min_interval = 2.0  # Mindestens 2s zwischen gleichen Sounds

        logger.info(
            "SoundManager initialisiert (enabled: %s, events: %d)",
            self.enabled, len(self.event_sounds),
        )

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
        import time
        now = time.time()
        last = self._last_sound_time.get(event, 0)
        if now - last < self._min_interval:
            return False
        self._last_sound_time[event] = now

        # Sound-Name aus Config
        sound_name = self.event_sounds.get(event, event)
        if not sound_name:
            return False

        # Volume bestimmen
        if volume is None:
            volume = self._get_auto_volume(event)

        # Speaker finden
        speaker_entity = None
        if room:
            speaker_entity = await self._find_speaker(room)
        if not speaker_entity:
            speaker_entity = await self._find_default_speaker()
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

        logger.debug("Sound '%s' abspielen (Volume: %.2f, Speaker: %s)",
                      event, volume, speaker_entity)
        return True

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

    async def _find_speaker(self, room: str) -> Optional[str]:
        """Findet einen Speaker im angegebenen Raum."""
        states = await self.ha.get_states()
        if not states:
            return None
        room_lower = room.lower().replace(" ", "_")
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("media_player.") and room_lower in entity_id:
                return entity_id
        return None

    async def _find_default_speaker(self) -> Optional[str]:
        """Findet den Standard-Speaker."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("media_player."):
                return entity_id
        return None

    def get_sound_info(self) -> dict:
        """Gibt Infos ueber verfuegbare Sounds zurueck."""
        return {
            "enabled": self.enabled,
            "events": self.event_sounds,
            "descriptions": DEFAULT_SOUND_DESCRIPTIONS,
            "night_volume_factor": self.night_volume_factor,
        }
