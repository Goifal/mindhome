"""
Speaker Recognition - Phase 9: Personen-Erkennung.

Identifiziert WER spricht ueber 7 Methoden (Prioritaet absteigend):
1. Device-Mapping: Welches Geraet/Satellite sendet? → Person zuordnen (0.95)
2. DoA (Direction of Arrival): Winkel der Stimme → Sitzposition → Person (0.85)
3. Room + Presence: Raum + Anwesenheit → wahrscheinlichste Person (0.80)
4. Sole Person Home: Nur 1 Person zuhause → muss die sein (0.85)
5. Voice Embeddings: ECAPA-TDNN 192-dim Stimmabdruck (0.60-0.95)
6. Voice Features: WPM, Dauer, Lautstaerke (0.30-0.90, spoofable)
7. Last Speaker Cache: Letzter identifizierter Sprecher (0.20-0.50)

Architektur:
- Device-zu-Person Mapping in settings.yaml konfigurierbar
- DoA-Mapping: Winkelbereich → Person pro Geraet (ReSpeaker XVF3800)
- Voice Embeddings: SpeechBrain ECAPA-TDNN, EMA-Lerneffekt via Redis
- Profiles werden in Redis gespeichert (Lerneffekt)
- Fallback: "Wer spricht?" bei Mehrdeutigkeit (mit Lerneffekt)
"""

import asyncio
import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config
from .embedding_extractor import extract_embedding, is_available as embeddings_available
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Redis Keys
SPEAKER_PROFILES_KEY = "mha:speaker:profiles"
SPEAKER_LAST_IDENTIFIED_KEY = "mha:speaker:last_identified"
SPEAKER_HISTORY_KEY = "mha:speaker:history"
SPEAKER_PENDING_ASK_KEY = "mha:speaker:pending_ask"


class SpeakerProfile:
    """Ein gespeichertes Stimm-Profil."""

    def __init__(self, name: str, person_id: str):
        self.name = name
        self.person_id = person_id
        self.created_at: float = time.time()
        self.sample_count: int = 0
        self.last_identified: float = 0.0
        # Audio-Feature-Durchschnitte (WPM, avg_duration, avg_volume)
        self.avg_wpm: float = 0.0
        self.avg_duration: float = 0.0
        self.avg_volume: float = 0.0
        # Geraete die dieser Person zugeordnet sind
        self.devices: list[str] = []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "person_id": self.person_id,
            "created_at": self.created_at,
            "sample_count": self.sample_count,
            "last_identified": self.last_identified,
            "avg_wpm": self.avg_wpm,
            "avg_duration": self.avg_duration,
            "avg_volume": self.avg_volume,
            "devices": self.devices,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeakerProfile":
        profile = cls(data.get("name", "Unknown"), data.get("person_id", "unknown"))
        profile.created_at = data.get("created_at", time.time())
        profile.sample_count = data.get("sample_count", 0)
        profile.last_identified = data.get("last_identified", 0.0)
        profile.avg_wpm = data.get("avg_wpm", 0.0)
        profile.avg_duration = data.get("avg_duration", 0.0)
        profile.avg_volume = data.get("avg_volume", 0.0)
        profile.devices = data.get("devices", [])
        return profile

    def update_voice_stats(self, wpm: float = 0, duration: float = 0, volume: float = 0):
        """Aktualisiert Voice-Statistiken mit gleitendem Durchschnitt."""
        n = self.sample_count
        if n == 0:
            self.avg_wpm = wpm
            self.avg_duration = duration
            self.avg_volume = volume
        else:
            # Exponentieller gleitender Durchschnitt (alpha=0.3)
            alpha = 0.3
            if wpm > 0:
                self.avg_wpm = alpha * wpm + (1 - alpha) * self.avg_wpm
            if duration > 0:
                self.avg_duration = alpha * duration + (1 - alpha) * self.avg_duration
            if volume > 0:
                self.avg_volume = alpha * volume + (1 - alpha) * self.avg_volume
        self.sample_count += 1
        self.last_identified = time.time()


class SpeakerRecognition:
    """
    Erkennt Personen ueber Device-Mapping, Raum-Praesenz und Voice-Features.

    Konfiguration in settings.yaml:
      speaker_recognition:
        enabled: true
        device_mapping:
          media_player.kueche_speaker: "max"
          media_player.schlafzimmer_speaker: "lisa"
    """

    def __init__(self, ha_client: Optional[HomeAssistantClient] = None):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None

        # Konfiguration
        sr_cfg = yaml_config.get("speaker_recognition", {})
        self.enabled = sr_cfg.get("enabled", False)
        self.min_confidence = sr_cfg.get("min_confidence", 0.7)
        self.fallback_ask = sr_cfg.get("fallback_ask", True)
        self.max_profiles = sr_cfg.get("max_profiles", 10)

        # Device-zu-Person Mapping (aus Config) — leere/None Werte filtern
        raw_mapping = sr_cfg.get("device_mapping", {}) or {}
        self._device_mapping: dict[str, str] = {
            str(k): str(v) for k, v in raw_mapping.items()
            if v is not None and v != ""
        }
        filtered_count = len(raw_mapping) - len(self._device_mapping)
        if filtered_count > 0:
            logger.info("Device-Mapping: %d Eintraege geladen, %d leere uebersprungen",
                        len(self._device_mapping), filtered_count)

        # DoA (Direction of Arrival) Mapping: device_id → {winkelbereich: person_id}
        raw_doa = sr_cfg.get("doa_mapping", {}) or {}
        self._doa_mapping: dict[str, dict[str, str]] = {}
        for dev_id, angle_map in raw_doa.items():
            if isinstance(angle_map, dict):
                self._doa_mapping[str(dev_id)] = {
                    str(k): str(v) for k, v in angle_map.items() if v
                }
        self._doa_tolerance = sr_cfg.get("doa_tolerance", 30)
        if self._doa_mapping:
            logger.info("DoA-Mapping: %d Geraete konfiguriert", len(self._doa_mapping))

        # In-Memory Cache der Profile
        self._profiles: dict[str, SpeakerProfile] = {}
        self._last_speaker: Optional[str] = None
        self._save_lock = asyncio.Lock()

        if self.enabled:
            logger.info(
                "SpeakerRecognition initialisiert (devices: %d, min_confidence: %.2f)",
                len(self._device_mapping), self.min_confidence,
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
                    # Device-Mapping aus Profilen rekonstruieren (ergaenzt Config-Mapping)
                    for pid, profile in self._profiles.items():
                        for device in profile.devices:
                            if device not in self._device_mapping:
                                self._device_mapping[device] = pid
                    logger.info("Speaker-Profile geladen: %d (devices: %d)",
                                len(self._profiles), len(self._device_mapping))
            except Exception as e:
                logger.warning("Speaker-Profile laden fehlgeschlagen: %s", e)

            # Letzten Sprecher aus Redis wiederherstellen
            try:
                last = await self.redis.get(SPEAKER_LAST_IDENTIFIED_KEY)
                if last:
                    self._last_speaker = last if isinstance(last, str) else last.decode()
                    logger.debug("Letzter Sprecher wiederhergestellt: %s", self._last_speaker)
            except Exception:
                pass

    async def identify(
        self,
        audio_metadata: Optional[dict] = None,
        device_id: Optional[str] = None,
        room: Optional[str] = None,
    ) -> dict:
        """
        Identifiziert den aktuellen Sprecher.

        Prioritaet:
        1. Device-Mapping (hoechste Confidence)
        2. Raum + einzige Person zuhause (hohe Confidence)
        3. Voice-Feature-Matching (mittlere Confidence)
        4. Letzter bekannter Sprecher (niedrige Confidence)

        Args:
            audio_metadata: Voice-Features (wpm, duration, volume)
            device_id: ID des sendenden Geraets/Satellite
            room: Raum aus dem die Anfrage kommt

        Returns:
            Dict mit person, confidence, fallback, method
        """
        if not self.enabled:
            return {"person": None, "confidence": 0.0, "fallback": False, "method": "disabled"}

        # 1. Device-Mapping: Geraet → Person
        if device_id and device_id in self._device_mapping:
            person_id = self._device_mapping[device_id]
            profile = self._profiles.get(person_id)
            name = profile.name if profile else person_id.capitalize()
            self._last_speaker = person_id

            # Voice-Stats aktualisieren wenn Audio-Metadata vorhanden
            if profile and audio_metadata:
                profile.update_voice_stats(
                    wpm=audio_metadata.get("wpm", 0),
                    duration=audio_metadata.get("duration", 0),
                    volume=audio_metadata.get("volume", 0),
                )
                await self._save_profiles()

            await self.log_identification(person_id, "device_mapping", 0.95)
            return {
                "person": name,
                "confidence": 0.95,
                "fallback": False,
                "method": "device_mapping",
            }

        # 2. DoA (Direction of Arrival): Winkel → Person
        # Erfordert ReSpeaker XVF3800 mit kalibriertem Winkel-Mapping
        if device_id and audio_metadata and audio_metadata.get("doa_angle") is not None:
            doa_result = self._identify_by_doa(device_id, audio_metadata["doa_angle"])
            if doa_result:
                self._last_speaker = doa_result["person_id"]
                await self.log_identification(
                    doa_result["person_id"], "doa", doa_result["confidence"],
                )
                return {
                    "person": doa_result["person"],
                    "confidence": doa_result["confidence"],
                    "fallback": False,
                    "method": "doa",
                }

        # 3. Raum + Anwesenheit: Wenn nur 1 Person im Raum
        if room and self.ha:
            room_person = await self._identify_by_room(room)
            if room_person:
                self._last_speaker = room_person.lower()
                await self.log_identification(room_person.lower(), "room_presence", 0.8)
                return {
                    "person": room_person,
                    "confidence": 0.8,
                    "fallback": False,
                    "method": "room_presence",
                }

        # 4. Nur 1 Person zuhause → muss die sein
        if self.ha:
            sole_person = await self._identify_sole_person()
            if sole_person:
                self._last_speaker = sole_person.lower()
                await self.log_identification(sole_person.lower(), "sole_person_home", 0.85)
                return {
                    "person": sole_person,
                    "confidence": 0.85,
                    "fallback": False,
                    "method": "sole_person_home",
                }

        # 5. Voice-Embedding-Matching (biometrischer Stimmabdruck)
        # Genuegt ~1-3s Audio. ECAPA-TDNN 192-dim Cosinus-Aehnlichkeit.
        if audio_metadata and audio_metadata.get("audio_pcm_b64") and self._profiles:
            embedding = extract_embedding(
                audio_metadata["audio_pcm_b64"],
                sample_rate=audio_metadata.get("sample_rate", 16000),
            )
            if embedding:
                emb_result = await self.identify_by_embedding(embedding)
                if emb_result:
                    self._last_speaker = emb_result["person_id"]
                    await self.log_identification(
                        emb_result["person_id"], "voice_embedding", emb_result["confidence"],
                    )
                    return {
                        "person": emb_result["person"],
                        "confidence": emb_result["confidence"],
                        "fallback": emb_result["confidence"] < self.min_confidence,
                        "method": "voice_embedding",
                    }

        # 6. Voice-Feature-Matching (wenn Audio-Metadata und Profile vorhanden)
        # F-048: Voice-Features (WPM, Dauer, Lautstaerke) sind KEIN sicheres
        # Identifikationsmerkmal — sie koennen leicht gefaelscht werden.
        # Ergebnis wird mit "spoofable" Flag markiert damit Trust-Entscheidungen
        # nur auf Methoden 1-5 basieren.
        if audio_metadata and self._profiles:
            match = self._match_voice_features(audio_metadata)
            if match:
                self._last_speaker = match["person_id"]
                await self.log_identification(
                    match["person_id"], "voice_features", match["confidence"],
                )
                return {
                    "person": match["name"],
                    "confidence": match["confidence"],
                    "fallback": match["confidence"] < self.min_confidence,
                    "method": "voice_features",
                    "spoofable": True,  # F-048: Nicht fuer Trust-Entscheidungen verwenden
                }

        # 7. Letzter bekannter Sprecher (Cache) — mit Time-Decay
        if self._last_speaker and self._last_speaker in self._profiles:
            profile = self._profiles[self._last_speaker]
            # Cache-Confidence sinkt mit der Zeit (max 1h nuetzlich)
            age_minutes = (time.time() - profile.last_identified) / 60 if profile.last_identified else 60
            cache_confidence = max(0.2, 0.5 - age_minutes / 120)
            result = {
                "person": profile.name,
                "confidence": round(cache_confidence, 2),
                "fallback": cache_confidence < self.min_confidence,
                "method": "cache",
            }
            await self.log_identification(self._last_speaker, "cache", cache_confidence)
            return result

        return {
            "person": None,
            "confidence": 0.0,
            "fallback": self.fallback_ask,
            "method": "unknown",
        }

    async def _get_persons_home(self) -> list[str]:
        """Ermittelt alle Personen die aktuell zuhause sind (aus HA person-Entities)."""
        states = await self.ha.get_states()
        if not states:
            return []
        return [
            state.get("attributes", {}).get("friendly_name", "User")
            for state in states
            if state.get("entity_id", "").startswith("person.")
            and state.get("state") == "home"
        ]

    def _identify_by_doa(self, device_id: str, doa_angle: float) -> Optional[dict]:
        """Identifiziert Person ueber Direction of Arrival (Winkel).

        Der ReSpeaker XVF3800 liefert den Azimut-Winkel (0-360 Grad)
        aus dem die Stimme kommt. Gegen kalibriertes Mapping pruefen.

        Args:
            device_id: Geraet das den DoA-Winkel liefert
            doa_angle: Winkel in Grad (0-360)

        Returns:
            Dict mit person, person_id, confidence oder None
        """
        if device_id not in self._doa_mapping:
            return None

        angle_map = self._doa_mapping[device_id]
        tolerance = self._doa_tolerance

        for angle_range, person_id in angle_map.items():
            # Format: "start-end" (z.B. "0-90") oder einzelner Winkel "45"
            parts = angle_range.split("-")
            try:
                if len(parts) == 2:
                    range_start = float(parts[0])
                    range_end = float(parts[1])
                else:
                    center = float(parts[0])
                    range_start = center - tolerance
                    range_end = center + tolerance

                # Winkel normalisieren (0-360) und pruefen
                # Beruecksichtigt Wrap-Around (z.B. 350-10 Grad)
                angle = doa_angle % 360
                if range_start < 0:
                    # Wrap: z.B. -30 bis 30 → 330-360 oder 0-30
                    if angle >= (360 + range_start) or angle <= range_end:
                        profile = self._profiles.get(person_id)
                        name = profile.name if profile else person_id.capitalize()
                        return {
                            "person": name,
                            "person_id": person_id,
                            "confidence": 0.85,
                        }
                elif range_end > 360:
                    if angle >= range_start or angle <= (range_end - 360):
                        profile = self._profiles.get(person_id)
                        name = profile.name if profile else person_id.capitalize()
                        return {
                            "person": name,
                            "person_id": person_id,
                            "confidence": 0.85,
                        }
                elif range_start <= angle <= range_end:
                    profile = self._profiles.get(person_id)
                    name = profile.name if profile else person_id.capitalize()
                    return {
                        "person": name,
                        "person_id": person_id,
                        "confidence": 0.85,
                    }
            except (ValueError, IndexError):
                continue

        return None

    async def _identify_by_room(self, room: str) -> Optional[str]:
        """Identifiziert Person anhand des Raums + Anwesenheit."""
        persons_home = await self._get_persons_home()

        # Wenn nur 1 Person zuhause → die ist es
        if len(persons_home) == 1:
            return persons_home[0]

        # Mehrere Personen: Preferred-Room Matching
        person_profiles = yaml_config.get("person_profiles", {}).get("profiles", {})
        room_lower = room.lower().replace(" ", "_")
        for person_key, profile in (person_profiles or {}).items():
            pref_room = (profile.get("preferred_room", "") or "").lower().replace(" ", "_")
            if pref_room == room_lower:
                # Pruefen ob die Person zuhause ist
                for ph in persons_home:
                    if ph.lower() == person_key:
                        return ph

        return None

    async def _identify_sole_person(self) -> Optional[str]:
        """Wenn nur eine Person zuhause ist, ist es die."""
        persons_home = await self._get_persons_home()
        if len(persons_home) == 1:
            return persons_home[0]
        return None

    def _match_voice_features(self, audio_metadata: dict) -> Optional[dict]:
        """Vergleicht Audio-Features mit gespeicherten Profilen.

        Beruecksichtigt WPM, Dauer, Lautstaerke und Time-Decay
        (kuerzlich identifizierte Profile werden bevorzugt).
        """
        wpm = audio_metadata.get("wpm", 0)
        duration = audio_metadata.get("duration", 0)
        volume = audio_metadata.get("volume", 0)

        if not wpm and not duration and not volume:
            return None

        best_match = None
        best_score = 0.0

        now = time.time()

        for pid, profile in self._profiles.items():
            if profile.sample_count < 3:
                continue  # Zu wenige Samples fuer Matching

            score = 0.0
            factors = 0

            # WPM-Aehnlichkeit
            if wpm > 0 and profile.avg_wpm > 0:
                wpm_diff = abs(wpm - profile.avg_wpm) / max(profile.avg_wpm, 1)
                wpm_score = max(0, 1.0 - wpm_diff)
                score += wpm_score
                factors += 1

            # Dauer-Aehnlichkeit
            if duration > 0 and profile.avg_duration > 0:
                dur_diff = abs(duration - profile.avg_duration) / max(profile.avg_duration, 1)
                dur_score = max(0, 1.0 - dur_diff)
                score += dur_score
                factors += 1

            # Lautstaerke-Aehnlichkeit
            if volume > 0 and profile.avg_volume > 0:
                vol_diff = abs(volume - profile.avg_volume) / max(profile.avg_volume, 0.01)
                vol_score = max(0, 1.0 - vol_diff)
                score += vol_score
                factors += 1

            if factors > 0:
                avg_score = score / factors
                # Sample-Count Bonus (mehr Samples = zuverlaessiger)
                sample_bonus = min(0.1, profile.sample_count * 0.01)

                # Time-Decay Bonus: Kuerzlich identifizierte Profile bevorzugen
                # Profile die in den letzten 10 Min aktiv waren bekommen Bonus
                recency_bonus = 0.0
                if profile.last_identified > 0:
                    minutes_ago = (now - profile.last_identified) / 60
                    if minutes_ago < 10:
                        recency_bonus = 0.05 * (1.0 - minutes_ago / 10)

                final_score = avg_score * 0.7 + sample_bonus + recency_bonus

                if final_score > best_score:
                    best_score = final_score
                    best_match = {
                        "person_id": pid,
                        "name": profile.name,
                        "confidence": round(min(1.0, final_score), 2),
                    }

        return best_match

    async def enroll(self, person_id: str, name: str,
                     audio_features: Optional[dict] = None,
                     device_id: Optional[str] = None) -> bool:
        """
        Erstellt oder aktualisiert ein Profil fuer eine Person.

        Args:
            person_id: Eindeutige Person-ID (kleingeschrieben)
            name: Anzeigename
            audio_features: Voice-Features (wpm, duration, volume)
            device_id: Geraet das dieser Person zugeordnet wird

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
            if audio_features:
                profile.update_voice_stats(
                    wpm=audio_features.get("wpm", 0),
                    duration=audio_features.get("duration", 0),
                    volume=audio_features.get("volume", 0),
                )
        else:
            profile = SpeakerProfile(name, person_id)
            if audio_features:
                profile.update_voice_stats(
                    wpm=audio_features.get("wpm", 0),
                    duration=audio_features.get("duration", 0),
                    volume=audio_features.get("volume", 0),
                )
            self._profiles[person_id] = profile

        # Device-Zuordnung
        if device_id and device_id not in profile.devices:
            profile.devices.append(device_id)
            self._device_mapping[device_id] = person_id

        await self._save_profiles()
        logger.info("Speaker-Profil gespeichert: %s (%s)", name, person_id)
        return True

    async def set_current_speaker(self, person_id: str):
        """Setzt den aktuellen Sprecher manuell (z.B. durch Chat-API person-Parameter)."""
        self._last_speaker = person_id
        # Profil-Timestamp aktualisieren (fuer Time-Decay / Cache-Confidence)
        profile = self._profiles.get(person_id)
        if profile:
            profile.last_identified = time.time()
            await self._save_profiles()
        if self.redis:
            try:
                await self.redis.set(SPEAKER_LAST_IDENTIFIED_KEY, person_id, ex=3600)
            except Exception:
                pass
        await self.log_identification(person_id, "manual", 1.0)

    async def remove_profile(self, person_id: str) -> bool:
        """Entfernt ein Profil."""
        if person_id in self._profiles:
            profile = self._profiles[person_id]
            # Device-Mappings entfernen
            for device in profile.devices:
                self._device_mapping.pop(device, None)
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

    async def learn_embedding_from_audio(self, person_id: str, audio_metadata: dict):
        """Extrahiert und speichert ein Voice-Embedding aus Audio-Metadaten.

        Wird aufgerufen wenn die Person bereits sicher identifiziert ist
        (z.B. per Device-Mapping oder manuell), um den Stimmabdruck
        zu trainieren. Nutzt EMA-Verschmelzung fuer kontinuierliches Lernen.
        """
        if not self.enabled or not audio_metadata:
            return
        audio_b64 = audio_metadata.get("audio_pcm_b64")
        if not audio_b64:
            return
        if person_id not in self._profiles:
            return

        embedding = extract_embedding(
            audio_b64, sample_rate=audio_metadata.get("sample_rate", 16000),
        )
        if embedding:
            await self.store_embedding(person_id, embedding)
            logger.debug("Embedding fuer %s gelernt (%d dim)", person_id, len(embedding))

    async def update_voice_stats_for_person(self, person_id: str, audio_metadata: dict):
        """Aktualisiert Voice-Stats fuer eine bekannte Person (z.B. aus UI).

        Wird von brain.py aufgerufen wenn der Sprecher bereits bekannt ist
        (z.B. ueber Chat-UI person-Parameter), damit die Voice-Profile
        trotzdem trainiert werden.
        """
        profile = self._profiles.get(person_id)
        if not profile:
            return
        profile.update_voice_stats(
            wpm=audio_metadata.get("wpm", 0),
            duration=audio_metadata.get("duration", 0),
            volume=audio_metadata.get("volume", 0),
        )
        await self._save_profiles()

    async def _save_profiles(self):
        """Speichert alle Profile in Redis (mit Lock gegen Race Conditions)."""
        if not self.redis:
            return
        async with self._save_lock:
            try:
                data = {pid: p.to_dict() for pid, p in self._profiles.items()}
                await self.redis.set(SPEAKER_PROFILES_KEY, json.dumps(data))
            except Exception as e:
                logger.warning("Speaker-Profile speichern fehlgeschlagen: %s", e)

    async def identify_by_embedding(self, embedding: list[float]) -> Optional[dict]:
        """Phase 9.6: Identifiziert Sprecher ueber Voice-Embedding (Cosinus-Aehnlichkeit).

        Args:
            embedding: Float-Vektor (z.B. 192 oder 256 Dimensionen)

        Returns:
            Dict mit person, confidence, method oder None
        """
        if not embedding or not self._profiles:
            return None

        best_match = None
        best_similarity = 0.0

        for pid, profile in self._profiles.items():
            # Embedding aus Redis laden
            stored = None
            if self.redis:
                try:
                    data = await self.redis.get(f"mha:speaker:embedding:{pid}")
                    if data:
                        stored = json.loads(data)
                except Exception:
                    pass

            if not stored or len(stored) != len(embedding):
                continue

            # Cosinus-Aehnlichkeit
            dot = sum(a * b for a, b in zip(embedding, stored))
            norm_a = sum(a * a for a in embedding) ** 0.5
            norm_b = sum(b * b for b in stored) ** 0.5
            if norm_a == 0 or norm_b == 0:
                continue
            similarity = dot / (norm_a * norm_b)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = {
                    "person": profile.name,
                    "person_id": pid,
                    "confidence": round(similarity, 3),
                    "method": "voice_embedding",
                }

        if best_match and best_match["confidence"] >= self.min_confidence:
            self._last_speaker = best_match["person_id"]
            return best_match
        return None

    async def store_embedding(self, person_id: str, embedding: list[float]) -> bool:
        """Phase 9.6: Speichert ein Voice-Embedding (mit EMA-Verschmelzung).

        Args:
            person_id: Person-ID
            embedding: Float-Vektor

        Returns:
            True wenn erfolgreich
        """
        if not self.enabled or person_id not in self._profiles:
            return False

        # Bestehendes Embedding laden und verschmelzen (EMA alpha=0.3)
        merged = embedding
        if self.redis:
            try:
                data = await self.redis.get(f"mha:speaker:embedding:{person_id}")
                if data:
                    stored = json.loads(data)
                    if len(stored) == len(embedding):
                        alpha = 0.3
                        merged = [alpha * e + (1 - alpha) * s
                                  for e, s in zip(embedding, stored)]
            except Exception:
                pass

        # Speichern
        if self.redis:
            try:
                await self.redis.set(
                    f"mha:speaker:embedding:{person_id}",
                    json.dumps(merged),
                )
                await self.redis.expire(f"mha:speaker:embedding:{person_id}", 365 * 86400)
            except Exception as e:
                logger.debug("Embedding speichern fehlgeschlagen: %s", e)

        logger.info("Voice-Embedding gespeichert: %s (%d Dim.)", person_id, len(embedding))
        return True

    async def log_identification(self, person_id: str, method: str, confidence: float):
        """Speichert eine Identifikation in der History (fuer Debugging/Analyse)."""
        if not self.redis:
            return
        try:
            entry = json.dumps({
                "person": person_id, "method": method,
                "confidence": round(confidence, 3), "time": time.time(),
            })
            await self.redis.lpush(SPEAKER_HISTORY_KEY, entry)
            await self.redis.ltrim(SPEAKER_HISTORY_KEY, 0, 99)  # Max 100 Eintraege
        except Exception:
            pass

    async def get_identification_history(self, limit: int = 20) -> list[dict]:
        """Gibt die letzten Identifikationen zurueck."""
        if not self.redis:
            return []
        try:
            entries = await self.redis.lrange(SPEAKER_HISTORY_KEY, 0, limit - 1)
            result = []
            for e in entries:
                try:
                    result.append(json.loads(e))
                except (json.JSONDecodeError, TypeError):
                    continue  # Korrupte Eintraege ueberspringen
            return result
        except Exception:
            return []

    async def start_fallback_ask(self, guessed_person: Optional[str] = None,
                                 original_text: str = "") -> str:
        """Startet eine 'Wer bist du?'-Rueckfrage und merkt sich den Kontext.

        Args:
            guessed_person: Vermutete Person (niedrige Confidence)
            original_text: Urspruenglicher Text (wird nach Identifikation wiederholt)

        Returns:
            Rueckfrage-Text fuer den User
        """
        # Haushaltsmitglieder ermitteln fuer die Frage
        persons_home = []
        if self.ha:
            persons_home = await self._get_persons_home()
        # Fallback: Profile als Quelle
        if not persons_home:
            persons_home = [p.name for p in self._profiles.values()]

        # Pending-State in Redis speichern (TTL 60s)
        pending = {
            "original_text": original_text,
            "guessed_person": guessed_person,
            "persons": persons_home,
            "time": time.time(),
        }
        if self.redis:
            try:
                await self.redis.set(
                    SPEAKER_PENDING_ASK_KEY, json.dumps(pending), ex=60,
                )
            except Exception:
                pass

        # Natuerliche Rueckfrage generieren
        if len(persons_home) == 2:
            return f"Kurze Frage — bist du {persons_home[0]} oder {persons_home[1]}?"
        elif len(persons_home) > 2:
            names = ", ".join(persons_home[:-1]) + f" oder {persons_home[-1]}"
            return f"Wer spricht gerade? {names}?"
        else:
            return "Wer spricht gerade?"

    async def resolve_fallback_answer(self, answer_text: str) -> Optional[dict]:
        """Versucht eine Antwort auf die 'Wer bist du?'-Frage aufzuloesen.

        Args:
            answer_text: User-Antwort (z.B. "Max", "Ich bin Lisa", "Die Lisa")

        Returns:
            Dict mit person, person_id oder None wenn nicht aufloesbar
        """
        if not self.redis:
            return None

        try:
            raw = await self.redis.get(SPEAKER_PENDING_ASK_KEY)
            if not raw:
                return None
            pending = json.loads(raw)
        except Exception:
            return None

        # Antwort cleanen
        clean = answer_text.lower().strip()
        # Typische Praefixe entfernen: "ich bin", "das ist", "hier ist", "die/der"
        for prefix in ["ich bin ", "das ist ", "hier ist ", "hier spricht ",
                        "der ", "die ", "das "]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break

        clean = clean.strip().rstrip(".!?")

        # Gegen bekannte Personen matchen
        persons = pending.get("persons", [])
        for person_name in persons:
            if clean == person_name.lower() or person_name.lower() in clean:
                person_id = person_name.lower()
                # Speaker setzen + Pending loeschen
                await self.set_current_speaker(person_id)
                if person_id not in self._profiles:
                    await self.enroll(person_id, person_name)
                try:
                    await self.redis.delete(SPEAKER_PENDING_ASK_KEY)
                except Exception:
                    pass
                logger.info("Fallback-Antwort aufgeloest: %s", person_name)
                return {
                    "person": person_name,
                    "person_id": person_id,
                    "original_text": pending.get("original_text", ""),
                }

        # Nicht erkannt — Pending loeschen
        try:
            await self.redis.delete(SPEAKER_PENDING_ASK_KEY)
        except Exception:
            pass
        return None

    async def has_pending_ask(self) -> bool:
        """Prueft ob eine 'Wer bist du?'-Rueckfrage laeuft."""
        if not self.redis:
            return False
        try:
            return await self.redis.exists(SPEAKER_PENDING_ASK_KEY) > 0
        except Exception:
            return False

    def health_status(self) -> str:
        """Gibt den Status zurueck."""
        if not self.enabled:
            return "disabled"
        embeds = "embeddings:on" if embeddings_available() else "embeddings:off"
        return f"active ({len(self._profiles)} profiles, {len(self._device_mapping)} devices, {embeds})"
