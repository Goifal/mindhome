"""
Smart DJ — Feature 11: Kontextbewusste Musikempfehlungen.

Kombiniert Stimmung (MoodDetector), Aktivitaet (ActivityEngine) und Tageszeit
zu einem "Music Context", der auf passende Spotify-Genres/Playlists gemappt wird.
Nutzer-Feedback wird in Redis gespeichert und beeinflusst zukuenftige Empfehlungen.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from .config import yaml_config, get_person_title

logger = logging.getLogger(__name__)

# Genre → Spotify-Suchquery (kuratiert)
GENRE_QUERIES: dict[str, str] = {
    "acoustic_morning": "acoustic morning chill",
    "chill_evening": "chill evening lounge",
    "party_hits": "party hits deutsch",
    "focus_calm": "calm focus ambient",
    "meditation": "meditation relaxation",
    "comfort_classics": "feel good classics",
    "sleep_ambient": "sleep ambient sounds",
    "energize_morning": "morning energy upbeat",
    "focus_lofi": "lofi hip hop beats study",
    "easy_listening": "easy listening classics",
    "jazz_dinner": "jazz dinner background",
    "sunday_brunch": "sunday morning brunch",
}

# Freundliche Genre-Namen fuer die Ausgabe
GENRE_LABELS: dict[str, str] = {
    "acoustic_morning": "Acoustic Morning",
    "chill_evening": "Chill Evening Lounge",
    "party_hits": "Party Hits",
    "focus_calm": "Calm Focus",
    "meditation": "Meditation & Relaxation",
    "comfort_classics": "Feel-Good Classics",
    "sleep_ambient": "Sleep Ambient",
    "energize_morning": "Morning Energy",
    "focus_lofi": "Lo-Fi Hip Hop Beats",
    "easy_listening": "Easy Listening",
    "jazz_dinner": "Jazz Dinner",
    "sunday_brunch": "Sunday Brunch",
}


def _get_time_of_day() -> str:
    """Gibt die Tageszeit als String zurueck."""
    hour = datetime.now().hour
    if 5 <= hour < 10:
        return "morning"
    elif 10 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "night"


class MusicDJ:
    """Kontextbewusster Musik-DJ fuer Spotify via Home Assistant."""

    def __init__(self, mood_detector, activity_engine):
        self.mood = mood_detector
        self.activity = activity_engine
        self.redis = None
        self._notify_callback = None
        self.executor = None
        self.enabled = True
        self._config: dict = {}

    async def initialize(self, redis_client=None):
        """Initialisiert den Music DJ mit Redis und Config."""
        self.redis = redis_client
        self._config = yaml_config.get("music_dj", {})
        self.enabled = self._config.get("enabled", True)
        logger.info("MusicDJ initialisiert (enabled=%s)", self.enabled)

    def reload_config(self, cfg: dict):
        """Hot-Reload der MusicDJ-Konfiguration."""
        self._config = cfg
        self.enabled = cfg.get("enabled", True)
        logger.info("MusicDJ Config reloaded (enabled=%s)", self.enabled)

    def set_notify_callback(self, callback):
        """Registriert Callback fuer proaktive Benachrichtigungen."""
        self._notify_callback = callback

    def set_executor(self, executor):
        """Setzt den FunctionExecutor fuer Wiedergabe-Steuerung."""
        self.executor = executor

    # ------------------------------------------------------------------
    # Kern-Logik
    # ------------------------------------------------------------------

    def _build_music_context(self) -> dict:
        """Baut den Music Context aus Mood + Activity + Tageszeit."""
        mood_data = self.mood.get_current_mood()
        return {
            "mood": mood_data.get("mood", "neutral"),
            "stress_level": mood_data.get("stress_level", 0.0),
            "tiredness_level": mood_data.get("tiredness_level", 0.0),
            "time_of_day": _get_time_of_day(),
        }

    async def _get_activity(self) -> str:
        """Holt die aktuelle Aktivitaet."""
        try:
            result = await self.activity.detect_activity()
            return result.get("activity", "relaxing")
        except Exception:
            return "relaxing"

    def _context_to_genre(self, context: dict, activity: str) -> Optional[str]:
        """Mappt Context + Activity auf ein Genre. None = keine Empfehlung."""
        mood = context["mood"]
        time = context["time_of_day"]

        # Suppression-Checks
        suppress_list = self._config.get("suppress_during", ["sleeping", "in_call"])
        if activity in suppress_list:
            return None
        if activity == "watching":
            return None

        # Mood-basiertes Mapping
        if mood == "frustrated":
            return "comfort_classics"

        if mood == "stressed":
            if activity == "focused":
                return "focus_calm"
            return "meditation"

        if mood == "tired":
            if time in ("evening", "night"):
                return "sleep_ambient"
            if time == "morning":
                return "energize_morning"
            return "easy_listening"

        if mood == "good":
            if activity == "guests":
                return "party_hits"
            if time == "morning":
                return "acoustic_morning"
            if time == "evening":
                return "chill_evening"
            if time == "afternoon":
                return "easy_listening"
            return "chill_evening"

        # neutral
        if activity == "focused":
            return "focus_lofi"
        if time == "morning":
            return "acoustic_morning"
        if time == "evening":
            return "jazz_dinner"
        return "easy_listening"

    def _genre_to_query(self, genre: str) -> str:
        """Gibt den Spotify-Suchquery fuer ein Genre zurueck."""
        # Custom-Queries aus Config haben Vorrang
        custom = self._config.get("custom_queries", {})
        if custom and genre in custom:
            return custom[genre]
        return GENRE_QUERIES.get(genre, "chill music")

    async def _apply_preferences(self, genre: str, person: str) -> str:
        """Passt Genre an basierend auf gelernten Praeferenzen."""
        if not self.redis or not person:
            return genre

        try:
            key = f"mha:music_dj:preferences:{person.lower()}"
            score = await self.redis.hget(key, genre)
            if score is not None and int(score) <= -3:
                # Genre blockiert — Fallback auf easy_listening
                logger.info("Genre '%s' blockiert fuer %s (Score: %s)", genre, person, score)
                return "easy_listening" if genre != "easy_listening" else "acoustic_morning"
        except Exception as e:
            logger.debug("Preference-Check Fehler: %s", e)

        return genre

    async def get_recommendation(self, person: str = "") -> dict:
        """Generiert eine kontextbewusste Musikempfehlung.

        Returns:
            Dict mit genre, query, label, context, reason
        """
        if not self.enabled:
            return {"success": False, "message": "Music DJ ist deaktiviert."}

        context = self._build_music_context()
        activity = await self._get_activity()

        genre = self._context_to_genre(context, activity)
        if genre is None:
            reason = f"Keine Musik empfohlen (Aktivitaet: {activity})"
            return {
                "success": True,
                "genre": None,
                "query": None,
                "label": None,
                "reason": reason,
                "context": {**context, "activity": activity},
            }

        # Praeferenzen anwenden
        genre = await self._apply_preferences(genre, person)

        query = self._genre_to_query(genre)
        label = GENRE_LABELS.get(genre, genre.replace("_", " ").title())

        # Grund formulieren
        mood_de = {
            "good": "guter Stimmung",
            "stressed": "Stress",
            "frustrated": "Frustration",
            "tired": "Muedigkeit",
            "neutral": "entspannter Stimmung",
        }
        time_de = {
            "morning": "Morgen",
            "afternoon": "Nachmittag",
            "evening": "Abend",
            "night": "Nacht",
        }
        reason = (
            f"Bei {mood_de.get(context['mood'], context['mood'])} "
            f"am {time_de.get(context['time_of_day'], context['time_of_day'])}: {label}"
        )

        # Letzte Empfehlung in Redis speichern
        if self.redis:
            try:
                await self.redis.setex(
                    "mha:music_dj:last_recommendation",
                    14400,  # 4h TTL
                    json.dumps({
                        "genre": genre,
                        "query": query,
                        "label": label,
                        "person": person,
                        "context": {**context, "activity": activity},
                    }),
                )
            except Exception as e:
                logger.debug("Empfehlung nicht gespeichert: %s", e)

        return {
            "success": True,
            "genre": genre,
            "query": query,
            "label": label,
            "reason": reason,
            "context": {**context, "activity": activity},
        }

    async def play_recommendation(
        self,
        person: str = "",
        room: Optional[str] = None,
        genre_override: Optional[str] = None,
    ) -> dict:
        """Empfiehlt Musik und spielt sie direkt ab."""
        if not self.executor:
            return {"success": False, "message": "Kein Executor konfiguriert."}

        if genre_override and genre_override in GENRE_QUERIES:
            genre = genre_override
            genre = await self._apply_preferences(genre, person)
            query = self._genre_to_query(genre)
            label = GENRE_LABELS.get(genre, genre.replace("_", " ").title())
        else:
            rec = await self.get_recommendation(person=person)
            if not rec.get("success"):
                return rec
            if rec.get("genre") is None:
                return {"success": True, "message": rec.get("reason", "Keine Musik empfohlen.")}
            genre = rec["genre"]
            query = rec["query"]
            label = rec["label"]

        # Wiedergabe via play_media
        play_args = {"action": "play", "query": query}
        if room:
            play_args["room"] = room

        volume = self._config.get("default_volume")
        if volume:
            # Erst Musik starten, dann Lautstaerke setzen
            result = await self.executor.execute("play_media", play_args)
            if result.get("success"):
                vol_args = {"action": "volume", "volume": volume}
                if room:
                    vol_args["room"] = room
                await self.executor.execute("play_media", vol_args)
        else:
            result = await self.executor.execute("play_media", play_args)

        if result.get("success"):
            title = get_person_title(person) if person else get_person_title()
            return {
                "success": True,
                "message": f"{label} laeuft jetzt, {title}.",
                "genre": genre,
                "query": query,
                "label": label,
            }
        return result

    async def record_feedback(self, positive: bool, person: str = "") -> dict:
        """Speichert Nutzer-Feedback zur letzten Empfehlung."""
        if not self.redis:
            return {"success": False, "message": "Kein Redis verfuegbar."}

        # Letzte Empfehlung laden
        try:
            raw = await self.redis.get("mha:music_dj:last_recommendation")
            if not raw:
                return {"success": False, "message": "Keine aktuelle Empfehlung zum Bewerten."}
            last = json.loads(raw)
        except Exception:
            return {"success": False, "message": "Empfehlung konnte nicht geladen werden."}

        genre = last.get("genre", "unknown")
        person_key = (person or last.get("person", "default")).lower()

        # Genre-Gewichtung anpassen
        try:
            pref_key = f"mha:music_dj:preferences:{person_key}"
            delta = 1 if positive else -1
            new_score = await self.redis.hincrby(pref_key, genre, delta)

            # Feedback-History speichern (max 50)
            fb_key = f"mha:music_dj:feedback:{person_key}"
            entry = json.dumps({
                "genre": genre,
                "positive": positive,
                "timestamp": datetime.now().isoformat(),
            })
            await self.redis.lpush(fb_key, entry)
            await self.redis.ltrim(fb_key, 0, 49)
        except Exception as e:
            logger.warning("Feedback-Speicherung Fehler: %s", e)
            return {"success": False, "message": f"Das liess sich nicht speichern: {e}"}

        label = GENRE_LABELS.get(genre, genre)
        if positive:
            return {"success": True, "message": f"Vermerkt. {label} kommt auf die Liste."}
        else:
            blocked = " Wird kuenftig gemieden." if new_score <= -3 else ""
            return {"success": True, "message": f"Verstanden. {label} ist nicht nach deinem Geschmack.{blocked}"}

    async def get_music_status(self) -> dict:
        """Gibt den aktuellen Music-DJ-Status zurueck."""
        context = self._build_music_context()
        activity = await self._get_activity()
        genre = self._context_to_genre(context, activity)

        result = {
            "success": True,
            "enabled": self.enabled,
            "current_context": {**context, "activity": activity},
            "suggested_genre": genre,
            "suggested_label": GENRE_LABELS.get(genre, "") if genre else None,
        }

        # Letzte Empfehlung aus Redis
        if self.redis:
            try:
                raw = await self.redis.get("mha:music_dj:last_recommendation")
                if raw:
                    result["last_recommendation"] = json.loads(raw)
            except Exception:
                pass

        return result
