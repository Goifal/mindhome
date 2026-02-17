"""
Speaker Recognition - Phase 9: Personen-Erkennung per Stimme.

Erkennt WER spricht anhand eines Voice-Print-Systems:
- Enrollment: 30 Sekunden Sprache → Voice-Print speichern
- Erkennung: Neue Sprache gegen gespeicherte Prints vergleichen
- Fallback: "Wer spricht?" bei niedriger Confidence

Architektur:
- Voice-Prints werden in Redis gespeichert
- Erkennung basiert auf einfachen Audio-Features (MFCC-aehnlich)
- Optional: pyannote-audio Integration fuer praezise Speaker Diarization

Dieses Feature ist standardmaessig DEAKTIVIERT (braucht GPU).
Aktivierung: speaker_recognition.enabled: true in settings.yaml
"""

import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Redis Keys
SPEAKER_PROFILES_KEY = "mha:speaker:profiles"
SPEAKER_LAST_IDENTIFIED_KEY = "mha:speaker:last_identified"


class SpeakerProfile:
    """Ein gespeichertes Stimm-Profil."""

    def __init__(self, name: str, person_id: str):
        self.name = name
        self.person_id = person_id
        self.created_at: float = time.time()
        self.sample_count: int = 0
        self.last_identified: float = 0.0
        # Feature-Vektor (Platzhalter — wird durch Audio-Modell ersetzt)
        self.features: list[float] = []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "person_id": self.person_id,
            "created_at": self.created_at,
            "sample_count": self.sample_count,
            "last_identified": self.last_identified,
            "features": self.features,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeakerProfile":
        profile = cls(data["name"], data["person_id"])
        profile.created_at = data.get("created_at", time.time())
        profile.sample_count = data.get("sample_count", 0)
        profile.last_identified = data.get("last_identified", 0.0)
        profile.features = data.get("features", [])
        return profile


class SpeakerRecognition:
    """
    Erkennt Personen anhand ihrer Stimme.

    Standardmaessig deaktiviert. Aktivierung:
    speaker_recognition:
      enabled: true
    """

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None

        # Konfiguration
        sr_cfg = yaml_config.get("speaker_recognition", {})
        self.enabled = sr_cfg.get("enabled", False)
        self.min_confidence = sr_cfg.get("min_confidence", 0.7)
        self.enrollment_duration = sr_cfg.get("enrollment_duration", 30)
        self.fallback_ask = sr_cfg.get("fallback_ask", True)
        self.max_profiles = sr_cfg.get("max_profiles", 10)

        # In-Memory Cache der Profile
        self._profiles: dict[str, SpeakerProfile] = {}
        self._last_speaker: Optional[str] = None

        if self.enabled:
            logger.info(
                "SpeakerRecognition initialisiert (min_confidence: %.2f, max_profiles: %d)",
                self.min_confidence, self.max_profiles,
            )
        else:
            logger.info("SpeakerRecognition deaktiviert (speaker_recognition.enabled = false)")

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis und laedt gespeicherte Profile."""
        self.redis = redis_client

        if not self.enabled:
            return

        # Gespeicherte Profile laden
        if self.redis:
            try:
                data = await self.redis.get(SPEAKER_PROFILES_KEY)
                if data:
                    profiles_dict = json.loads(data)
                    for pid, pdata in profiles_dict.items():
                        self._profiles[pid] = SpeakerProfile.from_dict(pdata)
                    logger.info(
                        "Speaker-Profile geladen: %d", len(self._profiles)
                    )
            except Exception as e:
                logger.debug("Speaker-Profile laden fehlgeschlagen: %s", e)

    async def identify(self, audio_metadata: Optional[dict] = None) -> dict:
        """
        Identifiziert den aktuellen Sprecher.

        Args:
            audio_metadata: Optional Audio-Features (WPM, Dauer, etc.)

        Returns:
            Dict mit:
                person: str - Erkannter Name (oder None)
                confidence: float - Sicherheit (0.0-1.0)
                fallback: bool - Ob gefragt werden soll
        """
        if not self.enabled:
            return {
                "person": None,
                "confidence": 0.0,
                "fallback": False,
            }

        if not self._profiles:
            return {
                "person": None,
                "confidence": 0.0,
                "fallback": self.fallback_ask,
            }

        # Platzhalter-Erkennung: Ohne echtes Audio-Modell
        # nutzen wir den zuletzt identifizierten Sprecher
        # In Produktion: pyannote-audio oder resemblyzer hier einbauen
        if self._last_speaker and self._last_speaker in self._profiles:
            profile = self._profiles[self._last_speaker]
            return {
                "person": profile.name,
                "confidence": 0.5,  # Niedrig weil nur Cache
                "fallback": False,
            }

        return {
            "person": None,
            "confidence": 0.0,
            "fallback": self.fallback_ask,
        }

    async def enroll(self, person_id: str, name: str,
                     audio_features: Optional[list[float]] = None) -> bool:
        """
        Erstellt oder aktualisiert ein Voice-Print fuer eine Person.

        Args:
            person_id: Eindeutige Person-ID
            name: Anzeigename
            audio_features: Feature-Vektor (optional)

        Returns:
            True wenn erfolgreich
        """
        if not self.enabled:
            return False

        if len(self._profiles) >= self.max_profiles and person_id not in self._profiles:
            logger.warning("Maximale Anzahl Speaker-Profile erreicht (%d)", self.max_profiles)
            return False

        if person_id in self._profiles:
            profile = self._profiles[person_id]
            profile.sample_count += 1
            if audio_features:
                profile.features = audio_features
        else:
            profile = SpeakerProfile(name, person_id)
            profile.sample_count = 1
            if audio_features:
                profile.features = audio_features
            self._profiles[person_id] = profile

        await self._save_profiles()
        logger.info("Speaker-Profil gespeichert: %s (%s)", name, person_id)
        return True

    async def set_current_speaker(self, person_id: str):
        """Setzt den aktuellen Sprecher manuell (z.B. durch Chat-API person-Parameter)."""
        self._last_speaker = person_id
        if self.redis:
            try:
                await self.redis.set(SPEAKER_LAST_IDENTIFIED_KEY, person_id, ex=3600)
            except Exception:
                pass

    async def remove_profile(self, person_id: str) -> bool:
        """Entfernt ein Voice-Print."""
        if person_id in self._profiles:
            del self._profiles[person_id]
            await self._save_profiles()
            return True
        return False

    def get_profiles(self) -> list[dict]:
        """Gibt alle gespeicherten Profile zurueck."""
        return [p.to_dict() for p in self._profiles.values()]

    def get_last_speaker(self) -> Optional[str]:
        """Gibt den zuletzt identifizierten Sprecher zurueck."""
        if self._last_speaker and self._last_speaker in self._profiles:
            return self._profiles[self._last_speaker].name
        return None

    async def _save_profiles(self):
        """Speichert alle Profile in Redis."""
        if not self.redis:
            return
        try:
            data = {pid: p.to_dict() for pid, p in self._profiles.items()}
            await self.redis.set(SPEAKER_PROFILES_KEY, json.dumps(data))
        except Exception as e:
            logger.debug("Speaker-Profile speichern fehlgeschlagen: %s", e)

    def health_status(self) -> str:
        """Gibt den Status zurueck."""
        if not self.enabled:
            return "disabled"
        return f"active ({len(self._profiles)} profiles)"
