"""
Activity Engine + Silence Matrix - Phase 6: Perfektes Timing, nie stoeren.
Phase 9: Volume-Level pro Aktivitaet + Tageszeit.

Erkennt die aktuelle Aktivitaet des Benutzers anhand von HA-Sensoren
und entscheidet WIE eine Meldung zugestellt werden soll.

Aktivitaeten:
  sleeping    - Schlaeft (Nacht + Bett belegt + Lichter aus)
  in_call     - In einem Anruf/Zoom (Mikrofon aktiv)
  watching    - Schaut Film/TV (Media Player aktiv)
  focused     - Arbeitet konzentriert (PC aktiv, wenig Bewegung)
  guests      - Gaeste anwesend (mehrere Personen zu Hause)
  relaxing    - Entspannt (Standard-Aktivitaet)
  away        - Nicht zu Hause

Zustellmethoden:
  tts_loud    - Volle Lautstaerke
  tts_quiet   - Leise TTS
  led_blink   - Nur LED-Signal (kein Ton)
  suppress    - Gar nicht zustellen
"""

import logging
import time
from datetime import datetime
from typing import Optional

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


# Erkannte Aktivitaeten
SLEEPING = "sleeping"
IN_CALL = "in_call"
WATCHING = "watching"
FOCUSED = "focused"
GUESTS = "guests"
RELAXING = "relaxing"
AWAY = "away"

# Zustellmethoden
TTS_LOUD = "tts_loud"
TTS_QUIET = "tts_quiet"
LED_BLINK = "led_blink"
SUPPRESS = "suppress"

# Standard Stille-Matrix: Aktivitaet x Urgency -> Zustellmethode
# Kann per settings.yaml ueberschrieben werden (activity.silence_matrix)
_DEFAULT_SILENCE_MATRIX = {
    SLEEPING: {
        "critical": TTS_LOUD,
        "high": LED_BLINK,
        "medium": SUPPRESS,
        "low": SUPPRESS,
    },
    IN_CALL: {
        "critical": TTS_LOUD,   # F-005: Leben > Telefonat — Critical MUSS hoerbar sein
        "high": TTS_QUIET,
        "medium": SUPPRESS,
        "low": SUPPRESS,
    },
    WATCHING: {
        "critical": TTS_LOUD,
        "high": LED_BLINK,
        "medium": SUPPRESS,
        "low": SUPPRESS,
    },
    FOCUSED: {
        "critical": TTS_LOUD,
        "high": TTS_QUIET,
        "medium": TTS_QUIET,
        "low": SUPPRESS,
    },
    GUESTS: {
        "critical": TTS_LOUD,
        "high": TTS_QUIET,
        "medium": TTS_QUIET,
        "low": SUPPRESS,
    },
    RELAXING: {
        "critical": TTS_LOUD,
        "high": TTS_LOUD,
        "medium": TTS_QUIET,
        "low": SUPPRESS,
    },
    AWAY: {
        "critical": TTS_LOUD,  # Wird an Handy weitergeleitet (spaeter)
        "high": SUPPRESS,
        "medium": SUPPRESS,
        "low": SUPPRESS,
    },
}

# Standard Volume-Levels pro Aktivitaet (0.0 - 1.0)
# Kann per settings.yaml ueberschrieben werden (activity.volume_matrix)
_DEFAULT_VOLUME_MATRIX = {
    SLEEPING: {
        "critical": 0.6,
        "high": 0.2,
        "medium": 0.15,
        "low": 0.1,
    },
    IN_CALL: {
        "critical": 0.3,
        "high": 0.2,
        "medium": 0.0,
        "low": 0.0,
    },
    WATCHING: {
        "critical": 0.7,
        "high": 0.4,
        "medium": 0.3,
        "low": 0.2,
    },
    FOCUSED: {
        "critical": 0.8,
        "high": 0.5,
        "medium": 0.4,
        "low": 0.3,
    },
    GUESTS: {
        "critical": 0.8,
        "high": 0.5,
        "medium": 0.4,
        "low": 0.3,
    },
    RELAXING: {
        "critical": 1.0,
        "high": 0.8,
        "medium": 0.7,
        "low": 0.5,
    },
    AWAY: {
        "critical": 1.0,
        "high": 0.0,
        "medium": 0.0,
        "low": 0.0,
    },
}

# Modul-Level Kopien fuer Rueckwaertskompatibilitaet (Tests, externer Zugriff)
SILENCE_MATRIX = dict(_DEFAULT_SILENCE_MATRIX)
VOLUME_MATRIX = dict(_DEFAULT_VOLUME_MATRIX)

# Gueltige Zustellmethoden (fuer Config-Validierung)
_VALID_DELIVERY_METHODS = {TTS_LOUD, TTS_QUIET, LED_BLINK, SUPPRESS}

# Gueltige Aktivitaeten (fuer Config-Validierung)
_VALID_ACTIVITIES = {SLEEPING, IN_CALL, WATCHING, FOCUSED, GUESTS, RELAXING, AWAY}


def _build_matrix_from_config(config_matrix: dict, default_matrix: dict,
                               validate_values: set | None = None) -> dict:
    """Baut eine Matrix aus Config + Defaults.

    Config-Werte ueberschreiben einzelne Eintraege, fehlende werden
    aus den Defaults ergaenzt.

    Args:
        config_matrix: User-Overrides aus settings.yaml
        default_matrix: Hardcoded Defaults
        validate_values: Wenn gesetzt, werden Werte gegen diese Menge validiert

    Returns:
        Vollstaendige Matrix (Default + Overrides)
    """
    result = {}
    for activity in _VALID_ACTIVITIES:
        default_row = default_matrix.get(activity, {})
        config_row = config_matrix.get(activity, {})
        merged = dict(default_row)
        for urgency, value in config_row.items():
            if urgency not in ("critical", "high", "medium", "low"):
                logger.warning("Unbekannte Urgency '%s' in silence_matrix.%s ignoriert",
                               urgency, activity)
                continue
            if validate_values and value not in validate_values:
                logger.warning("Ungueltiger Wert '%s' in silence_matrix.%s.%s ignoriert "
                               "(erlaubt: %s)", value, activity, urgency, validate_values)
                continue
            merged[urgency] = value
        result[activity] = merged
    return result


class ActivityEngine:
    """Erkennt die aktuelle Aktivitaet des Benutzers.

    Unterstuetzt manuellen Override: Wenn der User explizit eine Aktivitaet
    angibt (z.B. "Filmabend", "Meditation"), wird diese bevorzugt.
    """

    # Keywords die einen manuellen Silence-Modus triggern
    SILENCE_KEYWORDS = {
        WATCHING: ["filmabend", "film", "kino", "netflix", "serie schauen", "fernsehen"],
        FOCUSED: ["meditation", "meditieren", "fokus", "nicht stören", "nicht stoeren",
                   "ruhe", "konzentration", "arbeiten", "homeoffice"],
        SLEEPING: ["gute nacht", "schlaf gut", "ich geh schlafen", "ich geh ins bett"],
    }

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client

        # Manueller Override (z.B. wenn User "Filmabend" sagt)
        self._manual_override: Optional[str] = None
        self._override_until: Optional[datetime] = None

        # Konfiguration aus YAML
        activity_cfg = yaml_config.get("activity", {})

        # Entity-IDs (konfigurierbar pro Installation)
        entities = activity_cfg.get("entities", {})
        self.media_players = entities.get("media_players", [
            "media_player.wohnzimmer",
            "media_player.fernseher",
            "media_player.tv",
        ])
        self.mic_sensors = entities.get("mic_sensors", [
            "binary_sensor.mic_active",
            "binary_sensor.microphone",
        ])
        self.bed_sensors = entities.get("bed_sensors", [
            "binary_sensor.bed_occupancy",
            "binary_sensor.bett",
        ])
        self.pc_sensors = entities.get("pc_sensors", [
            "binary_sensor.pc_active",
            "binary_sensor.computer",
            "switch.pc",
        ])

        # Schwellwerte
        thresholds = activity_cfg.get("thresholds", {})
        self.night_start = int(thresholds.get("night_start", 22))
        self.night_end = int(thresholds.get("night_end", 7))
        self.guest_person_count = int(thresholds.get("guest_person_count", 2))
        self.focus_min_minutes = int(thresholds.get("focus_min_minutes", 30))

        # Konfigurierbare Silence- und Volume-Matrix (Override aus settings.yaml)
        self._silence_matrix = _build_matrix_from_config(
            activity_cfg.get("silence_matrix", {}),
            _DEFAULT_SILENCE_MATRIX,
            validate_values=_VALID_DELIVERY_METHODS,
        )
        self._volume_matrix = _build_matrix_from_config(
            activity_cfg.get("volume_matrix", {}),
            _DEFAULT_VOLUME_MATRIX,
        )

        # Haushaltsmitglieder-Entities sammeln (fuer praezise Guest-Detection)
        household = yaml_config.get("household", {})
        self._household_entities: set[str] = set()
        primary_entity = (household.get("primary_user_entity") or "").strip().lower()
        if primary_entity:
            self._household_entities.add(primary_entity)
        for m in (household.get("members") or []):
            ha_entity = (m.get("ha_entity") or "").strip().lower()
            if ha_entity:
                self._household_entities.add(ha_entity)

        # Cache: letzte erkannte Aktivitaet
        self._last_activity = RELAXING
        self._last_detection = None
        self._cache_ts: float = 0.0  # monotonic timestamp
        self._cache_ttl: float = 5.0  # Sekunden — verhindert Burst-Abfragen

    def reload_config(self, activity_cfg: dict):
        """Config aus YAML neu laden (wird von _reload_all_modules aufgerufen)."""
        entities = activity_cfg.get("entities", {})
        self.media_players = entities.get("media_players", [
            "media_player.wohnzimmer",
            "media_player.fernseher",
            "media_player.tv",
        ])
        self.mic_sensors = entities.get("mic_sensors", [
            "binary_sensor.mic_active",
            "binary_sensor.microphone",
        ])
        self.bed_sensors = entities.get("bed_sensors", [
            "binary_sensor.bed_occupancy",
            "binary_sensor.bett",
        ])
        self.pc_sensors = entities.get("pc_sensors", [
            "binary_sensor.pc_active",
            "binary_sensor.computer",
            "switch.pc",
        ])

        thresholds = activity_cfg.get("thresholds", {})
        self.night_start = int(thresholds.get("night_start", 22))
        self.night_end = int(thresholds.get("night_end", 7))
        self.guest_person_count = int(thresholds.get("guest_person_count", 2))
        self.focus_min_minutes = int(thresholds.get("focus_min_minutes", 30))

        # Silence- und Volume-Matrix neu laden
        self._silence_matrix = _build_matrix_from_config(
            activity_cfg.get("silence_matrix", {}),
            _DEFAULT_SILENCE_MATRIX,
            validate_values=_VALID_DELIVERY_METHODS,
        )
        self._volume_matrix = _build_matrix_from_config(
            activity_cfg.get("volume_matrix", {}),
            _DEFAULT_VOLUME_MATRIX,
        )
        logger.info("ActivityDetector Config neu geladen (media_players=%d, bed_sensors=%d, night=%d-%d)",
                     len(self.media_players), len(self.bed_sensors), self.night_start, self.night_end)

    def set_manual_override(self, activity: str, duration_minutes: int = 120):
        """Setzt einen manuellen Aktivitaets-Override.

        Wird verwendet wenn der User explizit eine Aktivitaet angibt,
        z.B. "Filmabend" → WATCHING fuer 2 Stunden.
        """
        from datetime import timedelta
        self._manual_override = activity
        self._override_until = datetime.now() + timedelta(minutes=duration_minutes)
        logger.info("Manueller Override: %s fuer %d Minuten", activity, duration_minutes)

    def clear_manual_override(self):
        """Entfernt den manuellen Override."""
        if self._manual_override:
            logger.info("Manueller Override aufgehoben: %s", self._manual_override)
        self._manual_override = None
        self._override_until = None

    def check_silence_trigger(self, text: str) -> Optional[str]:
        """Prueft ob ein Text einen Silence-Modus triggern soll.

        Returns:
            Aktivitaets-String oder None
        """
        text_lower = text.lower().strip()
        for activity, keywords in self.SILENCE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return activity
        return None

    async def detect_activity(self) -> dict:
        """
        Erkennt die aktuelle Aktivitaet.

        Manueller Override hat Vorrang vor Sensor-Erkennung.

        Returns:
            Dict mit:
                activity: str - Erkannte Aktivitaet
                confidence: float - Wie sicher (0.0-1.0)
                signals: dict - Erkannte Signale
                delivery: str - Nicht gesetzt (wird von SilenceMatrix bestimmt)
        """
        # Manueller Override pruefen
        if self._manual_override and self._override_until:
            if datetime.now() < self._override_until:
                return {
                    "activity": self._manual_override,
                    "confidence": 1.0,
                    "signals": {"manual_override": True},
                }
            else:
                self.clear_manual_override()

        # TTL-Cache: bei Callback-Bursts nicht mehrfach HA abfragen
        now = time.monotonic()
        if self._last_detection and (now - self._cache_ts) < self._cache_ttl:
            return self._last_detection

        signals = {}
        states = await self.ha.get_states()

        if not states:
            return {
                "activity": self._last_activity,
                "confidence": 0.3,
                "signals": {"ha_unavailable": True},
            }

        # Signale sammeln
        signals["away"] = self._check_away(states)
        signals["media_playing"] = self._check_media_playing(states)
        signals["in_call"] = self._check_in_call(states)
        signals["bed_occupied"] = self._check_bed_occupied(states)
        signals["sleeping"] = self._check_sleeping(states)
        signals["pc_active"] = self._check_pc_active(states)
        signals["guests"] = self._check_guests(states)
        signals["lights_off"] = self._check_lights_off(states)

        # Aktivitaet klassifizieren (Prioritaet: hoehere ueberschreiben niedrigere)
        activity, confidence = self._classify(signals)

        self._last_activity = activity

        # Ausloesendes Geraet merken (z.B. media_player.wohnzimmer bei watching)
        trigger = ""
        if activity == WATCHING and signals.get("media_playing"):
            trigger = signals["media_playing"]

        result = {
            "activity": activity,
            "confidence": confidence,
            "signals": signals,
            "trigger": trigger,
        }
        self._last_detection = result
        self._cache_ts = now

        logger.debug(
            "Aktivitaet erkannt: %s (confidence: %.2f, trigger: %s, signals: %s)",
            activity, confidence, trigger, signals,
        )

        return result

    def get_delivery_method(self, activity: str, urgency: str) -> str:
        """
        Bestimmt die Zustellmethode anhand der Stille-Matrix.

        Args:
            activity: Erkannte Aktivitaet
            urgency: Dringlichkeit (critical, high, medium, low)

        Returns:
            Zustellmethode (tts_loud, tts_quiet, led_blink, suppress)
        """
        activity_row = self._silence_matrix.get(activity, self._silence_matrix[RELAXING])
        return activity_row.get(urgency, TTS_LOUD)

    def get_volume_level(self, activity: str, urgency: str) -> float:
        """
        Phase 9: Bestimmt die Volume-Level basierend auf Aktivitaet und Urgency.

        Args:
            activity: Erkannte Aktivitaet
            urgency: Dringlichkeit (critical, high, medium, low)

        Returns:
            Volume-Level 0.0 - 1.0
        """
        activity_row = self._volume_matrix.get(activity, self._volume_matrix[RELAXING])
        base_volume = activity_row.get(urgency, 0.7)

        # Tageszeit-Faktor: Abends/Nachts leiser
        hour = datetime.now().hour
        # Nacht-Erkennung (funktioniert auch bei Mitternachts-Uebergang, z.B. 22-7)
        is_night = hour >= self.night_start or hour < self.night_end
        if is_night:
            # Nacht: Volume reduzieren (ausser Critical)
            if urgency != "critical":
                base_volume = min(base_volume, 0.3)
        elif hour >= self.night_start - 1:  # 1h vor Nacht = Abend
            if urgency not in ("critical", "high"):
                base_volume = min(base_volume, 0.5)

        return round(base_volume, 2)

    async def should_deliver(self, urgency: str) -> dict:
        """
        Kombinierte Methode: Erkennt Aktivitaet und bestimmt Zustellmethode.

        Returns:
            Dict mit:
                activity: str - Erkannte Aktivitaet
                delivery: str - Zustellmethode
                suppress: bool - Soll die Meldung unterdrueckt werden?
                confidence: float - Sicherheit der Erkennung
                volume: float - Empfohlene Lautstaerke (Phase 9)
        """
        detection = await self.detect_activity()
        activity = detection["activity"]
        delivery = self.get_delivery_method(activity, urgency)
        volume = self.get_volume_level(activity, urgency)

        return {
            "activity": activity,
            "delivery": delivery,
            "suppress": delivery == SUPPRESS,
            "confidence": detection["confidence"],
            "signals": detection["signals"],
            "volume": volume,
            "trigger": detection.get("trigger", ""),
        }

    # ----- Signal-Erkennung -----

    def _check_away(self, states: list[dict]) -> bool:
        """Prueft ob niemand zu Hause ist."""
        for state in states:
            if state.get("entity_id", "").startswith("person."):
                if state.get("state") == "home":
                    return False
        return True

    def _check_media_playing(self, states: list[dict]) -> str:
        """Prueft ob ein konfigurierter Media Player aktiv ist (TV, Film).

        Erkennt nicht nur "playing" sondern auch "on", "paused", "buffering" —
        also jeden Zustand der bedeutet, dass der TV an ist und jemand zuschaut.
        Nur "off", "standby", "unavailable", "unknown", "idle" gelten als inaktiv.

        Returns:
            entity_id des aktiven Players (truthy) oder "" (falsy).
        """
        inactive_states = {"off", "standby", "unavailable", "unknown", "idle"}
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id in self.media_players:
                s = state.get("state", "off").lower()
                if s not in inactive_states:
                    return entity_id
        return ""

    def _check_in_call(self, states: list[dict]) -> bool:
        """Prueft ob ein Mikrofon aktiv ist (Call/Zoom)."""
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id in self.mic_sensors:
                if state.get("state") == "on":
                    return True
        return False

    def _check_bed_occupied(self, states: list[dict]) -> bool:
        """Prueft ob der Bettsensor belegt ist (reines Sensor-Signal)."""
        for state in states:
            if state.get("entity_id", "") in self.bed_sensors:
                if state.get("state") == "on":
                    return True
        return False

    def _check_sleeping(self, states: list[dict]) -> bool:
        """Prueft ob der Benutzer schlaeft.

        Bett belegt + kein TV/PC = schlaeft (auch Mittagsschlaf).
        Bett belegt + TV an = NICHT sleeping (fernsehen im Bett) → wird WATCHING.
        Nacht + alle Lichter aus = wahrscheinlich schlaeft (Fallback ohne Bettsensor).
        """
        # PC aktiv oder Media spielt → User ist wach, auch im Bett
        if self._check_pc_active(states) or self._check_media_playing(states):
            return False

        # Bett belegt + kein TV/PC → schlaeft
        if self._check_bed_occupied(states):
            return True

        # Fallback: Nacht + alle Lichter aus (fuer Installationen ohne Bettsensor)
        now = datetime.now()
        is_night = now.hour >= self.night_start or now.hour < self.night_end
        if is_night:
            return self._check_lights_off(states)

        return False

    def _check_pc_active(self, states: list[dict]) -> bool:
        """Prueft ob der PC aktiv ist (Arbeit/Fokus)."""
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id in self.pc_sensors:
                if state.get("state") in ("on", "active"):
                    return True
        return False

    def _check_guests(self, states: list[dict]) -> bool:
        """Prueft ob echte Gaeste anwesend sind (nicht nur Haushaltsmitglieder)."""
        persons_home = 0
        unknown_home = 0
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("person."):
                if state.get("state") == "home":
                    persons_home += 1
                    if self._household_entities and entity_id.lower() not in self._household_entities:
                        unknown_home += 1
        # Wenn Haushaltsmitglieder konfiguriert: nur unbekannte Personen = Gaeste
        if self._household_entities:
            return unknown_home > 0
        # Fallback: mehr Personen als konfigurierte Haushaltsmitglieder-Anzahl
        return persons_home > self.guest_person_count

    def _check_lights_off(self, states: list[dict]) -> bool:
        """Prueft ob alle Lichter aus sind."""
        any_light = False
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("light."):
                any_light = True
                if state.get("state") == "on":
                    return False
        # Nur True wenn es ueberhaupt Lichter gibt
        return any_light

    # ----- Klassifikation -----

    def _classify(self, signals: dict) -> tuple[str, float]:
        """
        Klassifiziert die Aktivitaet basierend auf gesammelten Signalen.
        Prioritaet: away > sleeping > in_call > watching > guests > focused > relaxing
        """
        # Niemand zu Hause
        if signals.get("away"):
            return AWAY, 0.95

        # Schlaf: Bett belegt + kein TV/PC
        if signals.get("sleeping"):
            confidence = 0.90 if signals.get("lights_off") else 0.70
            return SLEEPING, confidence

        # Anruf hat hohe Prioritaet (darf nicht gestoert werden)
        if signals.get("in_call"):
            return IN_CALL, 0.95

        # Media/TV aktiv (inkl. fernsehen im Bett)
        if signals.get("media_playing"):
            return WATCHING, 0.85

        # Gaeste anwesend
        if signals.get("guests"):
            return GUESTS, 0.80

        # PC aktiv = Arbeitsmodus
        if signals.get("pc_active"):
            return FOCUSED, 0.70

        # Standard: Entspannt
        return RELAXING, 0.60
