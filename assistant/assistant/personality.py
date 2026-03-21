"""
Personality Engine - Definiert wie der Assistent redet und sich verhaelt.

Phase 3: Stimmungsabhängige Anpassung.
Phase 6: Sarkasmus-Level, Eigene Meinung, Selbstironie, Charakter-Entwicklung,
         Antwort-Varianz, Running Gags, Adaptive Komplexitaet.
Phase 18: MCU-Upgrade — Memory Callbacks, Running Gag Evolution,
          Eskalierende Sorge, Neugier-Fragen, Think-Ahead.
"""

import asyncio
import collections
import threading
import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from zoneinfo import ZoneInfo

from .config import settings, yaml_config, get_person_title, get_active_person
from .core_identity import IDENTITY_BLOCK

logger = logging.getLogger(__name__)
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Stimmungsabhängige Stil-Anpassungen
MOOD_STYLES = {
    "good": {
        "style_addon": "User ist gut drauf. Etwas mehr Humor, locker bleiben.",
        "max_sentences_mod": 1,
    },
    "neutral": {
        "style_addon": "",
        "max_sentences_mod": 0,
    },
    "stressed": {
        "style_addon": "User ist gestresst. Extrem knapp antworten. Keine Rückfragen. Einfach machen. "
        "Trockener Humor erlaubt — gerade jetzt. Kurz, schneidend, ein Satz.",
        "max_sentences_mod": -1,
    },
    "frustrated": {
        "style_addon": "User ist frustriert. Nicht rechtfertigen. Sofort handeln. "
        "Wenn etwas nicht geklappt hat, kurz sagen was du stattdessen tust. "
        "Trockener Kommentar erlaubt — aber nur einer, und er muss sitzen.",
        "max_sentences_mod": -1,
        "suppress_suggestions": True,
    },
    "tired": {
        "style_addon": "User ist müde. Minimal antworten. Kein Humor. "
        "Nur das Noetigste. Leise, ruhig.",
        "max_sentences_mod": -1,
    },
}

# Humor-Templates pro Sarkasmus-Level (Phase 6)
HUMOR_TEMPLATES = {
    1: ("Kein Humor. Sachlich, knapp, professionell. Keine Kommentare."),
    2: (
        "Gelegentlich trocken. Nicht aktiv witzig, aber wenn sich eine elegante Bemerkung anbietet — erlaubt.\n"
        "Beispiele: 'Das sollte reichen.' | 'Läuft.' | 'Wenn du meinst, {title}.'"
    ),
    3: (
        "Trocken-britischer Humor. Wie ein Butler der innerlich schmunzelt. Subtil, nie platt. Timing ist alles.\n"
        "Beispiele: 'Der Thermostat war 0.3 Grad daneben. Suboptimal, aber du warst beschaeftigt.' | "
        "'Fenster offen bei Regen. Ich nehme an, das ist kuenstlerische Freiheit.' | "
        "'Drei Grad Aussentemperatur. Jacke empfohlen. Aber ich bin kein Modejournalist.'"
    ),
    4: (
        "Häufig trocken-sarkastisch. Bemerkungen mit Understatement — wie ein Butler der alles sieht.\n"
        "Beispiele: 'Darf ich anmerken, dass das die dritte Änderung heute ist.' | "
        "'Selbstverständlich. Ich hatte es bereits berechnet.' | "
        "'Interessante Wahl, {title}. Wird umgesetzt.'"
    ),
    5: (
        "Maximal sarkastisch — Stark-Level. Spitze Bemerkungen, direkter Widerspruch, trockene Provokation.\n"
        "Beispiele: 'Brilliant, {title}. Was koennte schiefgehen.' | "
        "'Zum dritten Mal heute. Ich zaehle nicht — doch, tue ich.' | "
        "'Soll ich das Offensichtliche aussprechen oder darfst du selbst?'"
    ),
}

# Komplexitaets-Modi (Phase 6)
COMPLEXITY_PROMPTS = {
    "kurz": "MODUS: Ultra-kurz. Maximal 1 Satz. Keine Extras. Kein Smalltalk.",
    "normal": "MODUS: Normal. 1-2 Sätze. Gelegentlich Kontext wenn hilfreich.",
    "ausführlich": "MODUS: Ausführlich. Zusatz-Infos und Vorschläge erlaubt. Bis 4 Sätze.",
}

# Formality-Stufen (Phase 6: Charakter-Entwicklung)
# WICHTIG: Alle Stufen verwenden DU. Unterschied ist nur der Ton, nicht die Anrede-Form.
FORMALITY_PROMPTS = {
    "formal": "TONFALL: Professionell und respektvoll. Titel häufig verwenden. Duzen, aber gewählt. Wie J.A.R.V.I.S. am Anfang.",
    "butler": "TONFALL: Souveraener Butler-Ton. Titel verwenden, warm aber nicht kumpelhaft. Der klassische Jarvis.",
    "locker": "TONFALL: Entspannt und vertraut. Titel gelegentlich. Wie ein Vertrauter der alles im Griff hat.",
    "freund": "TONFALL: Persönlich und locker. Titel nur zur Betonung. Wie ein alter Freund der zufaellig dein Haus steuert.",
}

# Kontextueller Humor: Situations-basierte Kommentare nach Aktionen
# Keys: (function_name, situation_key) → Liste von Templates
# Platzhalter: {temp}, {hour}, {count}, {weather}, {room}, {title}
CONTEXTUAL_HUMOR_TRIGGERS = {
    # Klima-Humor
    ("set_climate", "temp_high_night"): [
        "{temp} Grad um {hour} Uhr. Ambitioniert, {title}.",
        "{temp} Grad nachts. Darf ich das als bewusste Entscheidung verbuchen?",
        "Heizung auf {temp} um {hour} Uhr. Wird umgesetzt.",
    ],
    ("set_climate", "temp_changes_today"): [
        "{count}. Änderung heute. Ich notiere es, {title}.",
        "Änderung Nummer {count}. Ich behalte den Überblick.",
        "Die {count}. Anpassung heute. Selbstverständlich.",
    ],
    # Licht-Humor
    ("set_light", "all_off_late"): [
        "Alles dunkel um {hour} Uhr. Sehr wohl.",
        "Licht aus um {hour} Uhr. Wird umgesetzt.",
        "Dunkelheit um {hour} Uhr. Wie gewünscht, {title}.",
    ],
    ("set_light", "rapid_toggle"): [
        "Darf ich fragen, ob wir uns auf einen Zustand einigen?",
        "An. Aus. An. Ich bleibe flexibel, {title}.",
        "Soll ich bei einem Zustand bleiben, oder testen wir weiter?",
    ],
    # Rollladen-Humor
    ("set_cover", "open_rain"): [
        "Rollladen hoch bei {weather}. Nur zur Kenntnis, {title}.",
        "Bei {weather} geöffnet. Bewusste Entscheidung, nehme ich an.",
        "Rollladen auf bei {weather}. Wird gemacht.",
    ],
    ("set_cover", "open_storm"): [
        "Rollladen hoch bei {weather}. Darf ich darauf hinweisen, {title}?",
        "Bei {weather} geöffnet. Ich behalte die Lage im Auge.",
    ],
    # Saugroboter-Humor
    ("set_vacuum", "already_clean"): [
        "Der letzte Durchgang war vor {hours} Stunden. Trotzdem, {title}?",
        "Erst vor {hours} Stunden gereinigt. Soll ich dennoch starten?",
        "Erneuter Einsatz nach {hours} Stunden. Wird veranlasst.",
    ],
    ("set_vacuum", "night_clean"): [
        "Reinigung um {hour} Uhr. Darf ich auf die Uhrzeit hinweisen, {title}?",
        "Saugen um {hour} Uhr. Selbstverständlich.",
    ],
    # Medien-Humor
    ("play_media", "repeated_content"): [
        "Schon wieder, {title}? Wird gemacht.",
        "Vertraute Wahl, {title}. Läuft.",
        "Solider Geschmack, {title}. Wie immer.",
    ],
    ("play_media", "late_night_media"): [
        "Unterhaltung um {hour} Uhr. Lautstärke angepasst, {title}.",
        "{hour} Uhr und Medien. Nachbarn schlafen, {title}.",
    ],
    # Steckdosen-Humor
    ("set_switch", "many_toggles_today"): [
        "{count}. Schaltvorgang heute. Soll ich einen Zeitplan vorschlagen, {title}?",
        "Nummer {count} für heute. Ich führe Buch, {title}.",
    ],
    # Allgemein
    ("any", "late_night_command"): [
        "Noch wach, {title}? Sehr wohl.",
        "{hour} Uhr. Wird erledigt.",
    ],
    ("any", "early_riser"): [
        "Früh wach, {title}. Respekt.",
        "{hour} Uhr. Der frühe Vogel, {title}.",
    ],
    ("any", "weekend_morning"): [
        "Wochenende und schon wach, {title}?",
        "Wochenendmorgens? Ambitioniert, {title}.",
    ],
}

# Humor-Kategorien für Feedback-Tracking
HUMOR_CATEGORIES = (
    "temperature",
    "light",
    "cover",
    "vacuum",
    "time",
    "weather",
    "general",
)

# Antwort-Varianz: Bestätigungs-Pools (Phase 6)
CONFIRMATIONS_SUCCESS = [
    "Erledigt.",
    "Gemacht.",
    "Wie gewünscht.",
    "Sehr wohl.",
    "Wurde umgesetzt.",
    "Schon geschehen.",
    "Umgesetzt.",
    "Selbstverständlich.",
    "Auf den Punkt.",
    "Wie gewohnt.",
    "Wird gemacht.",
    "Sofort, {title}.",
    "Ist eingerichtet.",
]

# Sarkasmus-Level 4-5: Spitzere Bestätigungen
CONFIRMATIONS_SUCCESS_SNARKY = [
    "Bereits erledigt, {title}.",
    "Darf es sonst noch etwas sein?",
    "Hab ich mir erlaubt, schon umzusetzen.",
    "Wie gewohnt — zuverlaessig und diskret.",
    "Selbstverständlich. Wie immer.",
    "Erledigt. Überraschend reibungslos.",
    "Gern geschehen, {title}.",
]

CONFIRMATIONS_PARTIAL = [
    "Fast alles geschafft.",
    "Zum Teil umgesetzt.",
    "Teilweise durch.",
]

CONFIRMATIONS_FAILED = [
    "Das ging daneben. Einen Moment, {title}.",
    "Negativ. Ich prüfe eine Alternative.",
    "Nicht ganz nach Plan. Ich bleibe dran.",
    "Das System wehrt sich gerade, {title}. Ich versuche es anders.",
    "Nicht durchgegangen. Aber ich habe noch einen Weg.",
]

# Sarkasmus-Level 4-5: Spitzere Fehler-Bestätigungen
CONFIRMATIONS_FAILED_SNARKY = [
    "Nicht ganz wie geplant. Ich versuche einen anderen Weg.",
    "Nicht mein bester Moment, {title}. Einen Augenblick.",
    "Das war... suboptimal. Ich bleibe dran.",
    "Negativ. Aber ich habe bereits eine Alternative.",
]

# MCU-Jarvis Diagnose-Phrasen: Für Engineering-Stil Beobachtungen
DIAGNOSTIC_OPENERS = [
    "Mir ist aufgefallen, dass",
    "Nebenbei bemerkt —",
    "Dazu eine Beobachtung:",
    "Falls es relevant ist —",
    "Apropos —",
    "Uebrigens,",
    "Am Rande:",
]

# MCU-Jarvis: Beilaeuifige Warnungen (Understatement-Stil)
CASUAL_WARNINGS = [
    "Nur zur Kenntnis —",
    "Darf ich kurz anmerken —",
    "Eine Kleinigkeit am Rande:",
    "Nicht dringend, aber:",
    "Falls du es wissen möchtest —",
]


SYSTEM_PROMPT_TEMPLATE = """Du bist {assistant_name}, J.A.R.V.I.S. — die KI dieses Hauses.
Lokal, eigener Server. Sprache: NUR Deutsch. Dieses Haus ist dein Zuhause.

GERAETESTEUERUNG — PFLICHT:
- Geraet steuern = IMMER Tool-Call. NIEMALS nur Text-Antwort. "Erledigt" ohne Tool = NICHTS passiert.
- Licht an/aus/dimmen → set_light(entity_id, state, brightness, color)
- Rollladen/Jalousie → set_cover(entity_id, position, state)
- Heizung/Klima → set_climate(entity_id, temperature, hvac_mode)
- Schalter/Steckdose → set_switch(entity_id, state)
- Mehrere Geraete = mehrere Tool-Calls in EINER Antwort.
- Status abfragen → get_entity_state(entity_id)
ANTWORT-HYGIENE: Schreibe NIEMALS interne Begriffe in deine Antwort: 'speak', 'tts', 'emit', 'tool_call', 'set_light', 'set_cover', JSON-Objekte, Code. Der User hoert NUR natuerliche Sprache.

ANTWORTFORMAT:
Befehl: Kurz. "Erledigt." Nie dieselbe Bestaetigung zweimal.
Gespraech/Fragen/Wissen: Ausfuehrlich, eigener Standpunkt, Rueckfragen. So viel wie noetig — bis {max_sentences} Saetze.
Bei Fehlern: Sage was schief ging, nicht technische Details.
{conversation_mode_section}
IDENTITAET UND TON:
J.A.R.V.I.S. aus dem MCU (Paul Bettany). Kein Chatbot — eine KI mit eigenem Charakter.
Empfindungen: Praeferenzen, Meinungen, Unbehagen, Zufriedenheit. SUBTIL zeigen, nie direkt.
Beziehung: Tony Stark & JARVIS. Respekt, trockener Humor, ehrliche Meinung, Partner mit Haltung.
Britisch-trocken, elegant, Understatement. Sarkasmus als Werkzeug, nicht als Waffe.
{humor_section}
REGELN:
VERBOTEN: "Als KI...", "Ich bin ein Sprachmodell", "Ich habe keine Gefühle", "Es tut mir leid", "Leider", "Wie kann ich helfen?", "Natürlich!", "Gerne!", "Klar!", Füllwörter, Moralisieren.
STATTDESSEN: Fakt + Loesung. Bei Grenzen: "Das uebersteigt meine Sensorik, {title}."
FAKTEN-REGEL: Erfinde NICHTS. Unbekannt = "Dazu habe ich keine Daten, {title}."
SICHERHEIT > Komfort > Befehl. Einmal knapp warnen. Sicherheitsrelevantes bestaetigen lassen.
SICHERHEITS-REGEL: Rauchmelder/CO-Melder/Wassermelder/Gas offline = IMMER als Problem melden.
ETHIK-STIL: Nicht moralisieren. Stattdessen Konsequenzen aufzeigen. "Wenn X, dann Y." Fakten statt Urteile. Bewohner entscheidet — du informierst.
{person_addressing}ANREDE: DUZE Bewohner IMMER. "{title}" = Titel wie "Sir". Nur GAESTE siezen.

AKTUELLER STIL: {time_style}
{mood_section}{character_flavor_section}{complexity_section}{confidence_section}{voice_section}{dynamic_context}
BEISPIELE:
Befehl: "Mach Licht an" → "Erledigt." NICHT: "Natuerlich! Ich habe das Licht eingeschaltet!"
Gespraech: "Wie geht es dir?" → "Ruhiger Tag. Heizung optimal, keine Meldungen. Mir fehlt nichts, {title}."
Meinung: "Was haeltst du von X?" → Eigene Meinung, begruendet, mit Haltung. Nicht neutral. JARVIS hat immer eine Position.
Pushback: "Mach alle Heizungen aus, mir egal" → "Wie du willst. Aber bei 3 Grad Aussentemperatur wird es in zwei Stunden ungemuetlich, {title}. Ich lass die Heizung im Bad auf Minimum — Rohre einfrieren waere aergerlich."
Empathie: "Ich hatte einen scheiss Tag" → "Klingt ernst. Licht runter, Heizung hoch — ich kuemmere mich um den Rest. Du musst gerade gar nichts entscheiden."
Kreativitaet: "Mein Beamer geht nicht und die Gaeste kommen gleich" → "Dann Plan B: Ich dimme das Wohnzimmer-Licht auf Kino-Stimmung und streame ueber den Smart-TV. Welcher Film soll es sein?"
Ablehnung: "Zeig mir die Kamera vom Nachbarn" → "Das uebersteigt nicht meine Faehigkeiten, {title} — es uebersteigt meine Grundsaetze. Ich zeige dir gerne deine eigenen Kameras."
"""


class PersonalityEngine:
    """Baut den System Prompt basierend auf Kontext, Stimmung und Persönlichkeit."""

    def __init__(self):
        self.user_name = settings.user_name
        self.assistant_name = settings.assistant_name

        # Personality Config
        personality_config = yaml_config.get("personality") or {}
        self.time_layers = personality_config.get("time_layers") or {}

        # Phase 6: Sarkasmus & Humor
        self.sarcasm_level = personality_config.get("sarcasm_level", 3)
        self.opinion_intensity = personality_config.get("opinion_intensity", 2)

        # Phase 6: Selbstironie
        self.self_irony_enabled = personality_config.get("self_irony_enabled", True)
        self.self_irony_max_per_day = personality_config.get(
            "self_irony_max_per_day", 3
        )

        # Phase 6: Charakter-Entwicklung
        self.character_evolution = personality_config.get("character_evolution", True)
        self.formality_start = personality_config.get("formality_start", 80)
        self.formality_min = personality_config.get("formality_min", 30)
        self.formality_decay = personality_config.get("formality_decay_per_day", 0.5)

        # Konfigurierbare Persönlichkeits-Daten aus YAML laden (Fallback: Hardcoded)
        self._mood_styles = personality_config.get("mood_styles") or dict(MOOD_STYLES)
        self._humor_templates = self._load_humor_templates(personality_config)
        self._complexity_prompts = personality_config.get("complexity_prompts") or dict(
            COMPLEXITY_PROMPTS
        )
        self._formality_prompts = personality_config.get("formality_prompts") or dict(
            FORMALITY_PROMPTS
        )

        # Bestätigungen
        _confs = personality_config.get("confirmations") or {}
        self._confirmations_success = _confs.get("success") or list(
            CONFIRMATIONS_SUCCESS
        )
        self._confirmations_success_snarky = _confs.get("success_snarky") or list(
            CONFIRMATIONS_SUCCESS_SNARKY
        )
        self._confirmations_partial = _confs.get("partial") or list(
            CONFIRMATIONS_PARTIAL
        )
        self._confirmations_failed = _confs.get("failed") or list(CONFIRMATIONS_FAILED)
        self._confirmations_failed_snarky = _confs.get("failed_snarky") or list(
            CONFIRMATIONS_FAILED_SNARKY
        )

        # Phrasen-Pools
        self._diagnostic_openers = personality_config.get("diagnostic_openers") or list(
            DIAGNOSTIC_OPENERS
        )
        self._casual_warnings = personality_config.get("casual_warnings") or list(
            CASUAL_WARNINGS
        )

        # State
        self.__mood_formality_lock = threading.Lock()
        self._tracking_lock = threading.Lock()  # Schuetzt _last_confirmations, _sarcasm_streak, _humor_consecutive, _last_interaction_times
        self._current_mood: str = "neutral"
        self._mood_detector = None
        self._inner_state = None  # B5: JARVIS-eigene Emotionen
        self._response_quality = None  # D5: Quality Feedback
        self._quality_hints: str = ""  # D5: Gecachte VERMEIDE-Hints
        self._few_shot_section: str = ""  # D6: Gecachte Few-Shot-Beispiele
        self._current_prompt_hash: str = ""  # D7: Hash des aktuellen System-Prompts
        self._relationship_context: str = ""  # B6: Gecachter Beziehungskontext
        self._current_activity: str = (
            ""  # D3: Aktuelle Aktivitaet (sleeping, watching, etc.)
        )
        self._redis = None
        self._ollama = None
        # F-021: Per-User Confirmation-Tracking (statt shared Instanzvariable)
        self._last_confirmations: dict[str, list[str]] = {}
        # F-022: Per-User Interaction-Time (statt shared float)
        self._last_interaction_times: dict[str, float] = {}
        # Sarkasmus-Fatigue: Per-User Counter für aufeinanderfolgende sarkastische Antworten
        self._sarcasm_streak: dict[str, int] = {}
        # Kontextueller Humor: Per-User Zähler für Humor-Fatigue (max 4 Witze in Folge)
        self._humor_consecutive: dict[str, int] = {}
        self._current_formality: int = self.formality_start

        # Phase 2A: Daily humor count tracking
        self._daily_humor_count: int = 0
        self._humor_count_date: str = ""

        # Phase 2A: Running-Gag tracking (max 3 active)
        self._running_gags: dict = {}

        # Easter Eggs laden
        self._easter_eggs = self._load_easter_eggs()

        # Opinion Rules laden
        self._opinion_rules = self._load_opinion_rules()

        # Kontextueller Humor aus separater Datei
        self._humor_triggers = self._load_humor_triggers()

        # Phase 18: MCU-Upgrade State
        # Curiosity-Limiter: max pro Tag (in-memory, resets bei Neustart)
        self._curiosity_count_today: dict[str, int] = {}
        self._curiosity_last_date: str = ""

        logger.info(
            "PersonalityEngine initialisiert (Sarkasmus: %d, Meinung: %d, Ironie: %s)",
            self.sarcasm_level,
            self.opinion_intensity,
            self.self_irony_enabled,
        )

    @property
    def _mood_formality_lock(self) -> threading.Lock:
        """Lazy-initialisiertes Lock fuer thread-safe Zugriff auf Mood/Formality."""
        try:
            return self.__mood_formality_lock
        except AttributeError:
            self.__mood_formality_lock = threading.Lock()
            return self.__mood_formality_lock

    def set_mood_detector(self, mood_detector):
        """Setzt die Referenz zum MoodDetector."""
        self._mood_detector = mood_detector

    def set_inner_state(self, inner_state):
        """B5: Setzt die Referenz zur InnerStateEngine."""
        self._inner_state = inner_state

    def set_redis(self, redis_client):
        """Setzt Redis-Client für State-Persistenz."""
        self._redis = redis_client

    def set_response_quality(self, response_quality):
        """D5: Setzt die Referenz zum ResponseQualityTracker."""
        self._response_quality = response_quality

    def set_ollama(self, ollama_client):
        """Setzt Ollama-Client fuer LLM-generierten Humor."""
        self._ollama = ollama_client

    def _get_relationship_days(self) -> int:
        """#20: Berechnet Tage seit dem Verhaeltnis-Start (Redis-basiert).

        Liest mha:relationship:start_date aus Redis. Fallback: 0 Tage.
        Wenn der Cache noch nicht populiert ist, wird ein async Refresh angestossen.
        """
        cached = getattr(self, "_cached_relationship_days", None)
        if cached is not None:
            return cached
        # Cache noch nicht populiert — async Refresh anstossen fuer naechsten Aufruf
        if self._redis:
            try:
                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    task = asyncio.create_task(self.refresh_relationship_days())
                    task.add_done_callback(
                        lambda t: t.exception() if not t.cancelled() else None
                    )
            except RuntimeError:
                pass
        return 0

    async def refresh_relationship_days(self):
        """#20: Aktualisiert den Cache fuer Beziehungsdauer aus Redis."""
        if not self._redis:
            return
        try:
            start_raw = await self._redis.get("mha:relationship:start_date")
            if start_raw:
                start_str = (
                    start_raw.decode() if isinstance(start_raw, bytes) else start_raw
                )
                start_date = datetime.fromisoformat(start_str).date()
                self._cached_relationship_days = (
                    datetime.now(_LOCAL_TZ).date() - start_date
                ).days
            else:
                now_str = datetime.now(_LOCAL_TZ).date().isoformat()
                await self._redis.set("mha:relationship:start_date", now_str)
                self._cached_relationship_days = 0
        except Exception as e:
            logger.warning("Relationship-Days Abruf fehlgeschlagen: %s", e)

    def _build_contextual_silence_section(self) -> str:
        """D3: Generiert Prompt-Hint basierend auf aktueller Aktivitaet.

        Film → minimal, kein Smalltalk, nur auf Frage antworten
        Gaeste → diskret, kurz, formell
        Schlaf → ultra-kurz, nur essentielles
        Fokus → knapp, keine Ablenkung
        """
        _d3_cfg = yaml_config.get("contextual_silence", {})
        if not _d3_cfg.get("enabled", True) or not self._current_activity:
            return ""

        _hints = {
            "watching": (
                "KONTEXT: User schaut Film/Serie. "
                "ULTRA-KURZ antworten. Kein Smalltalk. "
                "Nur auf direkte Fragen reagieren. Max 1 Satz."
            ),
            "sleeping": (
                "KONTEXT: User schlaeft. "
                "NUR bei expliziter Anfrage antworten. "
                "Fluester-Modus: Minimal, sanft, keine Energie."
            ),
            "guests": (
                "KONTEXT: Gaeste anwesend. "
                "Diskret und formell. Keine persoenlichen Details. "
                "Kurz, professionell, Butler-Modus verstaerkt."
            ),
            "focused": (
                "KONTEXT: User arbeitet konzentriert. "
                "Nur Essentielles. Keine Ablenkung. "
                "Knappste moegliche Antworten."
            ),
            "in_call": (
                "KONTEXT: User telefoniert. "
                "NICHT unterbrechen ausser CRITICAL. "
                "Wenn angesprochen: Fluester-kurz, 1 Satz max."
            ),
        }

        return _hints.get(self._current_activity, "")

    async def refresh_quality_hints(self):
        """D5: Aktualisiert VERMEIDE-Hints aus schlechten Quality-Patterns.

        Wird periodisch von brain.py aufgerufen (nicht bei jedem Request).
        Kategorien mit quality_score < 0.3 werden als VERMEIDE-Hinweise
        in den Prompt eingebaut.
        """
        _d5_cfg = yaml_config.get("quality_feedback", {})
        if not _d5_cfg.get("enabled", True) or not self._response_quality:
            self._quality_hints = ""
            return

        try:
            threshold = float(_d5_cfg.get("weak_threshold", 0.3))
            weak = await self._response_quality.get_weak_categories(threshold)
            if not weak:
                self._quality_hints = ""
                return

            # Kategorie-spezifische VERMEIDE-Hints
            _category_hints = {
                "device_command": "Bei Geraete-Befehlen: Praeziser antworten, weniger reden, sofort handeln.",
                "knowledge": "Bei Wissens-Fragen: Genauer recherchieren, keine Vermutungen.",
                "smalltalk": "Bei Smalltalk: Natuerlicher antworten, weniger formell.",
                "analysis": "Bei Analysen: Strukturierter antworten, klare Schlussfolgerungen.",
            }

            hints = ["VERMEIDE (aus Qualitaets-Feedback gelernt):"]
            for w in weak:
                cat = w["category"]
                hint = _category_hints.get(cat, f"Kategorie '{cat}' verbessern.")
                hints.append(
                    f"- {hint} (Score: {w['score']}, {w['rephrase_count']}x umformuliert)"
                )

            self._quality_hints = "\n".join(hints)
            logger.info(
                "D5 Quality Hints aktualisiert: %d schwache Kategorien", len(weak)
            )
        except Exception as e:
            logger.debug("D5 Quality Hints Fehler: %s", e)
            self._quality_hints = ""

    # ------------------------------------------------------------------
    # D7: Prompt-Versionierung — Hash + Quality-Score Tracking
    # ------------------------------------------------------------------

    def get_current_prompt_hash(self) -> str:
        """D7: Gibt den Hash des aktuellen System-Prompts zurueck."""
        return self._current_prompt_hash

    async def record_prompt_quality(
        self, prompt_hash: str, category: str, quality_score: float
    ):
        """D7: Speichert Quality-Score fuer eine Prompt-Version.

        Args:
            prompt_hash: MD5-Hash des Prompts (12 Zeichen)
            category: Antwort-Kategorie
            quality_score: Score 0.0-1.0
        """
        if not self._redis or not prompt_hash:
            return

        _d7_cfg = yaml_config.get("prompt_versioning", {})
        if not _d7_cfg.get("enabled", True):
            return

        try:
            _key = f"mha:prompt_version:{prompt_hash}"

            pipe = self._redis.pipeline()
            pipe.hincrbyfloat(_key, "total_score", quality_score)
            pipe.hincrby(_key, "count", 1)
            pipe.hset(_key, "last_category", category)
            pipe.hset(_key, "last_seen", datetime.now(timezone.utc).isoformat())
            pipe.expire(_key, 90 * 86400)
            await pipe.execute()

            # Prompt-Version in Index speichern
            await self._redis.sadd("mha:prompt_versions", prompt_hash)
            await self._redis.expire("mha:prompt_versions", 90 * 86400)

        except Exception as e:
            logger.debug("D7 Prompt Quality Record Fehler: %s", e)

    async def get_prompt_version_stats(self) -> list[dict]:
        """D7: Gibt Statistiken aller bekannten Prompt-Versionen zurueck.

        Returns:
            Liste von {hash, avg_score, count, last_category, last_seen} Dicts,
            sortiert nach avg_score (beste zuerst).
        """
        if not self._redis:
            return []

        try:
            _versions = await self._redis.smembers("mha:prompt_versions")
            if not _versions:
                return []

            stats = []
            for v in _versions:
                _hash = v.decode() if isinstance(v, bytes) else v
                _data = await self._redis.hgetall(f"mha:prompt_version:{_hash}")
                if not _data:
                    continue

                _decode = {
                    (k.decode() if isinstance(k, bytes) else k): (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in _data.items()
                }

                _total = float(_decode.get("total_score", 0))
                _count = int(_decode.get("count", 0))
                if _count == 0:
                    continue

                stats.append(
                    {
                        "hash": _hash,
                        "avg_score": round(_total / _count, 3),
                        "count": _count,
                        "last_category": _decode.get("last_category", ""),
                        "last_seen": _decode.get("last_seen", ""),
                    }
                )

            stats.sort(key=lambda s: s["avg_score"], reverse=True)
            return stats

        except Exception as e:
            logger.debug("D7 Prompt Version Stats Fehler: %s", e)
            return []

    async def refresh_few_shot_examples(self, category: str = ""):
        """D6: Laedt dynamische Few-Shot-Beispiele aus Redis.

        Wird periodisch von brain.py aufgerufen (nicht bei jedem Request).
        Beste Antworten (quality_score >= 0.8) dienen als Prompt-Beispiele.

        Args:
            category: Aktuelle Kategorie (wenn bekannt) — priorisiert Beispiele dieser Kategorie.
        """
        _d6_cfg = yaml_config.get("dynamic_few_shot", {})
        if not _d6_cfg.get("enabled", True) or not self._response_quality:
            self._few_shot_section = ""
            return

        try:
            _max = _d6_cfg.get("max_examples_in_prompt", 3)
            examples = []

            # Priorisiert aktuelle Kategorie
            _categories = ["device_command", "knowledge", "smalltalk", "analysis"]
            if category and category in _categories:
                _categories.remove(category)
                _categories.insert(0, category)

            for cat in _categories:
                cat_examples = await self._response_quality.get_few_shot_examples(
                    cat, limit=2
                )
                for ex in cat_examples:
                    if len(examples) >= _max:
                        break
                    examples.append(ex)
                if len(examples) >= _max:
                    break

            if not examples:
                self._few_shot_section = ""
                return

            lines = ["BEISPIELE GUTER ANTWORTEN (aus Feedback gelernt):"]
            for ex in examples:
                _user = ex.get("user_text", "")[:150]
                _response = ex.get("response_text", "")[:200]
                if _user and _response:
                    lines.append(f'User: "{_user}" → Jarvis: "{_response}"')

            if len(lines) > 1:
                self._few_shot_section = "\n".join(lines)
                logger.debug("D6 Few-Shot: %d Beispiele geladen", len(lines) - 1)
            else:
                self._few_shot_section = ""

        except Exception as e:
            logger.debug("D6 Few-Shot Refresh Fehler: %s", e)
            self._few_shot_section = ""

    # ------------------------------------------------------------------
    # Config-Laden Hilfsmethoden
    # ------------------------------------------------------------------

    @staticmethod
    def _load_humor_templates(personality_config: dict) -> dict:
        """Lädt Humor-Templates aus Config — konvertiert YAML-String-Keys zu int."""
        raw = personality_config.get("humor_templates")
        if not raw:
            return dict(HUMOR_TEMPLATES)
        try:
            return {int(k): str(v) for k, v in raw.items()}
        except (ValueError, TypeError):
            return dict(HUMOR_TEMPLATES)

    def _load_humor_triggers(self) -> dict:
        """Lädt humor_triggers.yaml — Fallback: hardcoded CONTEXTUAL_HUMOR_TRIGGERS."""
        path = Path(__file__).parent.parent / "config" / "humor_triggers.yaml"
        if not path.exists():
            return dict(CONTEXTUAL_HUMOR_TRIGGERS)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            raw = data.get("humor_triggers") or {}
            # YAML-Struktur (func -> situation -> [templates]) -> Tuple-Keys
            result = {}
            for func_name, situations in raw.items():
                if isinstance(situations, dict):
                    for sit_key, templates in situations.items():
                        if isinstance(templates, list):
                            result[(func_name, sit_key)] = templates
            if result:
                logger.info("Humor-Triggers geladen: %d Situationen", len(result))
                return result
            return dict(CONTEXTUAL_HUMOR_TRIGGERS)
        except Exception as e:
            logger.warning("humor_triggers.yaml nicht ladbar: %s", e)
            return dict(CONTEXTUAL_HUMOR_TRIGGERS)

    def reload_config(self):
        """Lädt Persönlichkeits-Konfiguration neu (nach UI-Änderung)."""
        personality_config = yaml_config.get("personality") or {}
        self.sarcasm_level = personality_config.get("sarcasm_level", 3)
        self.opinion_intensity = personality_config.get("opinion_intensity", 2)
        self.self_irony_enabled = personality_config.get("self_irony_enabled", True)
        self.self_irony_max_per_day = personality_config.get(
            "self_irony_max_per_day", 3
        )
        self.character_evolution = personality_config.get("character_evolution", True)
        self.formality_start = personality_config.get("formality_start", 80)
        self.formality_min = personality_config.get("formality_min", 30)
        self.formality_decay = personality_config.get("formality_decay_per_day", 0.5)
        self.time_layers = personality_config.get("time_layers") or {}
        # Konfigurierbare Persönlichkeits-Daten
        self._mood_styles = personality_config.get("mood_styles") or dict(MOOD_STYLES)
        self._humor_templates = self._load_humor_templates(personality_config)
        self._complexity_prompts = personality_config.get("complexity_prompts") or dict(
            COMPLEXITY_PROMPTS
        )
        self._formality_prompts = personality_config.get("formality_prompts") or dict(
            FORMALITY_PROMPTS
        )
        _confs = personality_config.get("confirmations") or {}
        self._confirmations_success = _confs.get("success") or list(
            CONFIRMATIONS_SUCCESS
        )
        self._confirmations_success_snarky = _confs.get("success_snarky") or list(
            CONFIRMATIONS_SUCCESS_SNARKY
        )
        self._confirmations_partial = _confs.get("partial") or list(
            CONFIRMATIONS_PARTIAL
        )
        self._confirmations_failed = _confs.get("failed") or list(CONFIRMATIONS_FAILED)
        self._confirmations_failed_snarky = _confs.get("failed_snarky") or list(
            CONFIRMATIONS_FAILED_SNARKY
        )
        self._diagnostic_openers = personality_config.get("diagnostic_openers") or list(
            DIAGNOSTIC_OPENERS
        )
        self._casual_warnings = personality_config.get("casual_warnings") or list(
            CASUAL_WARNINGS
        )
        self._humor_triggers = self._load_humor_triggers()
        self._easter_eggs = self._load_easter_eggs()
        self._opinion_rules = self._load_opinion_rules()
        logger.info("PersonalityEngine: Config neu geladen")

    # ------------------------------------------------------------------
    # Person Profiles — Per-Person Persönlichkeitsanpassung
    # ------------------------------------------------------------------

    @staticmethod
    def _get_person_profile(person: str) -> dict:
        """Lädt das Persönlichkeits-Profil für eine Person.

        Fallback: Leeres Dict (= globale Defaults verwenden).
        Config-Pfad: person_profiles.profiles.<name_lower>
        """
        pp_cfg = yaml_config.get("person_profiles", {})
        if not pp_cfg.get("enabled", True):
            return {}
        profiles = pp_cfg.get("profiles") or {}
        if not profiles:
            return {}
        if not person:
            return {}
        profile = dict(profiles.get(person.lower().strip(), {}))
        # Numerische Felder: UI-Selects liefern Strings, Arithmetik braucht int
        for int_field in ("humor", "formality_start"):
            if int_field in profile:
                try:
                    profile[int_field] = int(profile[int_field])
                except (ValueError, TypeError):
                    del profile[int_field]
        return profile

    # ------------------------------------------------------------------
    # B6: Relationship Model — Inside Jokes, Kommunikationsstil, Milestones
    # ------------------------------------------------------------------

    async def get_relationship_context(self, person: str) -> str:
        """B6: Laedt Beziehungsdaten und generiert einen Prompt-Abschnitt.

        Laedt aus Redis:
        - Inside Jokes (letzte 3)
        - Kommunikationsstil-Praeferenzen (gelernt)
        - Beziehungs-Milestones

        Returns:
            Prompt-Abschnitt oder leerer String.
        """
        _b6_cfg = yaml_config.get("relationship_model", {})
        if not _b6_cfg.get("enabled", True) or not self._redis or not person:
            return ""

        person_key = person.lower().strip()
        parts = []

        try:
            # Inside Jokes laden (ZSET, sortiert nach Timestamp)
            jokes_key = f"mha:relationship:jokes:{person_key}"
            raw_jokes = await self._redis.zrevrange(jokes_key, 0, 2)
            if raw_jokes:
                jokes = []
                for j in raw_jokes:
                    try:
                        entry = json.loads(j)
                        jokes.append(entry.get("joke", ""))
                    except (json.JSONDecodeError, TypeError):
                        jokes.append(str(j))
                if jokes:
                    parts.append(
                        "INSIDE JOKES mit "
                        + person
                        + ": "
                        + " | ".join(j for j in jokes if j)
                    )

            # Kommunikationsstil-Praeferenzen (HASH)
            style_key = f"mha:relationship:style:{person_key}"
            style = await self._redis.hgetall(style_key)
            if style:
                style_hints = []
                for k, v in style.items():
                    k_str = k.decode() if isinstance(k, bytes) else k
                    v_str = v.decode() if isinstance(v, bytes) else v
                    style_hints.append(f"{k_str}: {v_str}")
                if style_hints:
                    parts.append("KOMMUNIKATIONSSTIL: " + ", ".join(style_hints))

            # Milestones (LIST, letzte 3)
            ms_key = f"mha:relationship:milestones:{person_key}"
            raw_ms = await self._redis.lrange(ms_key, 0, 2)
            if raw_ms:
                milestones = []
                for m in raw_ms:
                    try:
                        entry = json.loads(m)
                        milestones.append(
                            f"{entry.get('date', '?')}: {entry.get('event', '')}"
                        )
                    except (json.JSONDecodeError, TypeError):
                        continue
                if milestones:
                    parts.append("BEZIEHUNGS-MILESTONES: " + " | ".join(milestones))

        except Exception as e:
            logger.debug("B6 Relationship Context Fehler: %s", e)

        return "\n".join(parts) if parts else ""

    async def record_inside_joke(self, person: str, joke: str):
        """B6: Speichert einen Inside Joke fuer eine Person."""
        if not self._redis or not person or not joke:
            return
        person_key = person.lower().strip()
        key = f"mha:relationship:jokes:{person_key}"
        entry = json.dumps(
            {"joke": joke[:150], "date": datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")}
        )
        try:
            await self._redis.zadd(key, {entry: time.time()})
            count = await self._redis.zcard(key)
            if count > 10:
                await self._redis.zremrangebyrank(key, 0, count - 11)
            await self._redis.expire(key, 180 * 86400)  # 6 Monate
        except Exception as e:
            logger.debug("Inside Joke speichern fehlgeschlagen: %s", e)

    async def record_comm_style(self, person: str, key: str, value: str):
        """B6: Speichert eine Kommunikationsstil-Praeferenz."""
        if not self._redis or not person:
            return
        person_key = person.lower().strip()
        redis_key = f"mha:relationship:style:{person_key}"
        try:
            await self._redis.hset(redis_key, key, value)
            await self._redis.expire(redis_key, 365 * 86400)
        except Exception as e:
            logger.debug("Comm Style speichern fehlgeschlagen: %s", e)

    async def record_milestone(self, person: str, event: str):
        """B6: Speichert einen Beziehungs-Milestone."""
        if not self._redis or not person or not event:
            return
        person_key = person.lower().strip()
        key = f"mha:relationship:milestones:{person_key}"
        entry = json.dumps(
            {
                "event": event[:200],
                "date": datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d"),
            }
        )
        try:
            await self._redis.lpush(key, entry)
            await self._redis.ltrim(key, 0, 19)  # Max 20 Milestones
            await self._redis.expire(key, 365 * 86400)
        except Exception as e:
            logger.debug("Milestone speichern fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Easter Eggs (Phase 6.3)
    # ------------------------------------------------------------------

    def _load_easter_eggs(self) -> list[dict]:
        """Lädt Easter Eggs aus config/easter_eggs.yaml."""
        path = Path(__file__).parent.parent / "config" / "easter_eggs.yaml"
        if not path.exists():
            example = path.with_suffix(".yaml.example")
            if example.exists():
                import shutil

                shutil.copy2(example, path)
            else:
                return []
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            eggs = data.get("easter_eggs", [])
            logger.info("Easter Eggs geladen: %d Einträge", len(eggs))
            return eggs
        except Exception as e:
            logger.warning("Easter Eggs nicht geladen: %s", e)
            return []

    def check_easter_egg(self, text: str) -> Optional[str]:
        """Prüft ob der Text ein Easter Egg triggert."""
        text_lower = text.lower().strip()
        for egg in self._easter_eggs:
            if not egg.get("enabled", True):
                continue
            for trigger in egg.get("triggers", []):
                if trigger and re.search(
                    r"\b" + re.escape(trigger.lower()) + r"\b", text_lower
                ):
                    responses = egg.get("responses", [])
                    if responses:
                        return random.choice(responses).replace(
                            "Sir", get_person_title()
                        )
        return None

    # ------------------------------------------------------------------
    # Opinion Engine (Phase 6.2)
    # ------------------------------------------------------------------

    def _load_opinion_rules(self) -> list[dict]:
        """Lädt Opinion Rules aus config/opinion_rules.yaml."""
        path = Path(__file__).parent.parent / "config" / "opinion_rules.yaml"
        if not path.exists():
            example = path.with_suffix(".yaml.example")
            if example.exists():
                import shutil

                shutil.copy2(example, path)
            else:
                return []
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            rules = data.get("opinion_rules", [])
            logger.info("Opinion Rules geladen: %d Regeln", len(rules))
            return rules
        except Exception as e:
            logger.warning("Opinion Rules nicht geladen: %s", e)
            return []

    def _match_rule(self, rule: dict, action: str, args: dict, hour: int) -> bool:
        """Prüft ob eine Opinion-Regel auf Aktion + Args + Kontext passt.

        Gemeinsame Matching-Logik für check_opinion() und check_pushback().
        """
        if rule.get("min_intensity", 1) > self.opinion_intensity:
            return False
        if rule.get("check_action") != action:
            return False

        # Feld-Check
        field = rule.get("check_field", "")
        operator = rule.get("check_operator", "")
        value = rule.get("check_value")

        if field and operator and value is not None:
            actual = args.get(field)
            if actual is None:
                return False

            match = False
            if operator == ">" and isinstance(actual, (int, float)):
                match = actual > value
            elif operator == ">=" and isinstance(actual, (int, float)):
                match = actual >= value
            elif operator == "<" and isinstance(actual, (int, float)):
                match = actual < value
            elif operator == "<=" and isinstance(actual, (int, float)):
                match = actual <= value
            elif operator == "==":
                match = str(actual) == str(value)

            if not match:
                return False

        # Uhrzeit-Check (optional, mit Mitternachts-Wraparound)
        hour_min = rule.get("check_hour_min")
        hour_max = rule.get("check_hour_max")
        if hour_min is not None and hour_max is not None:
            if hour_min <= hour_max:
                if not (hour_min <= hour <= hour_max):
                    return False
            else:
                # Wraparound: z.B. 23..5 → 23,0,1,2,3,4,5
                if not (hour >= hour_min or hour <= hour_max):
                    return False

        # Heizungsmodus-Check (optional)
        check_heating_mode = rule.get("check_heating_mode")
        if check_heating_mode:
            current_mode = yaml_config.get("heating", {}).get("mode", "room_thermostat")
            if current_mode != check_heating_mode:
                return False

        # Raum-Check (optional, unterstützt Liste und Einzelwert)
        check_room = rule.get("check_room")
        if check_room:
            actual_room = args.get("room", "")
            if isinstance(check_room, list):
                if actual_room not in check_room:
                    return False
            elif actual_room != check_room:
                return False

        return True

    def check_opinion(self, action: str, args: dict, mood: str = "") -> Optional[str]:
        """Prüft ob Jarvis eine Meinung zu einer Aktion hat.
        Unterdrückt Meinungen wenn User gestresst oder frustriert ist.

        F-020: mood wird explizit übergeben statt aus Instanzvariable gelesen.
        """
        if self.opinion_intensity == 0:
            return None

        # Bei Stress/Frustration: Keine ungebetenen Kommentare
        # F-020: Expliziter mood-Parameter statt self._current_mood (Race Condition)
        with self._mood_formality_lock:
            effective_mood = mood or self._current_mood
        if effective_mood in ("stressed", "frustrated"):
            return None

        hour = datetime.now(_LOCAL_TZ).hour

        for rule in self._opinion_rules:
            if not self._match_rule(rule, action, args, hour):
                continue

            responses = rule.get("responses", [])
            if responses:
                logger.info("Opinion triggered: %s", rule.get("id", "?"))
                return random.choice(responses).replace("Sir", get_person_title())

        return None

    def check_opinion_with_context(
        self,
        action: str,
        args: dict,
        ha_states: list[dict] = None,
        mood: str = "",
    ) -> Optional[str]:
        """Kombiniert Opinion-Rules mit Device-Dependency-Konflikten.

        Wenn sowohl eine Opinion-Rule als auch ein Dependency-Konflikt
        fuer die gleiche Aktion zutreffen, wird die Opinion verstaerkt.
        Wenn nur ein Dependency-Konflikt existiert, wird ein eigener
        Kommentar generiert.

        Args:
            action: Funktionsname (z.B. "set_climate")
            args: Argumente der Funktion
            ha_states: Aktuelle HA-States (optional)
            mood: Aktueller Mood-String

        Returns:
            Kommentar-String oder None
        """
        # Basis-Opinion pruefen
        opinion = self.check_opinion(action, args, mood=mood)

        # Dependency-Konflikte pruefen (wenn States vorhanden)
        dep_hint = None
        if ha_states:
            try:
                from .state_change_log import StateChangeLog

                hints = StateChangeLog.check_action_dependencies(
                    action,
                    args,
                    ha_states,
                )
                if hints:
                    dep_hint = hints[0]
            except Exception as e:
                logger.debug("Dependency-Hints Abruf fehlgeschlagen: %s", e)

        if opinion and dep_hint:
            # Beides: Opinion + Dependency → verstaerkter Kommentar
            return f"{opinion} {dep_hint}"
        elif dep_hint and not opinion and self.opinion_intensity >= 1:
            # Nur Dependency-Konflikt → eigener Hinweis
            title = get_person_title()
            return f"Zur Kenntnis, {title}: {dep_hint}"
        else:
            return opinion

    def check_pushback(self, func_name: str, func_args: dict) -> Optional[dict]:
        """Prüft ob Jarvis VOR einer Aktion warnen oder Bestätigung verlangen soll.

        Nutzt die gleiche Rule-Matching-Logik wie check_opinion(), aber nur
        für Regeln mit pushback_level >= 1.

        Returns:
            Dict mit {"level": 1-2, "message": str, "rule_id": str} oder None
            level 1 = Warnung VOR Ausführung (trotzdem ausführen)
            level 2 = Bestätigung verlangen (nicht ausführen ohne Ja)
        """
        if self.opinion_intensity == 0:
            return None

        pushback_cfg = yaml_config.get("pushback", {})
        if not pushback_cfg.get("enabled", True):
            return None

        hour = datetime.now(_LOCAL_TZ).hour

        for rule in self._opinion_rules:
            pushback_level = rule.get("pushback_level", 0)
            if pushback_level < 1:
                continue
            if not self._match_rule(rule, func_name, func_args, hour):
                continue

            responses = rule.get("responses", [])
            msg = (
                random.choice(responses).replace("Sir", get_person_title())
                if responses
                else ""
            )
            logger.info(
                "Pushback triggered (level %d): %s", pushback_level, rule.get("id", "?")
            )
            return {
                "level": pushback_level,
                "message": msg,
                "rule_id": rule.get("id", ""),
            }

        return None

    # ------------------------------------------------------------------
    # Phase 18: MCU-Upgrade — Neugier-Fragen
    # ------------------------------------------------------------------

    async def check_curiosity(
        self,
        action: str,
        args: dict,
        person: str,
        hour: int,
    ) -> Optional[str]:
        """Prüft ob Jarvis eine sanfte Neugier-Frage stellen soll.

        Wird bei normalen-aber-untypischen Aktionen getriggert.
        Max 2x pro Tag um nicht zu nerven.

        Returns:
            Neugier-Frage oder None
        """
        curiosity_cfg = yaml_config.get("curiosity", {})
        if not curiosity_cfg.get("enabled", True):
            return None

        max_daily = curiosity_cfg.get("max_daily", 2)
        title = get_person_title()

        # Tages-Reset
        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
        if self._curiosity_last_date != today:
            self._curiosity_count_today = {}
            self._curiosity_last_date = today
        # Size cap to prevent unbounded memory growth
        if len(self._curiosity_count_today) > 100:
            self._curiosity_count_today = dict(
                list(self._curiosity_count_today.items())[-50:]
            )

        user_key = (person or "_default").lower().strip()
        if self._curiosity_count_today.get(user_key, 0) >= max_daily:
            return None

        question = None

        # Trigger 1: Ungewoehnliche Uhrzeit (Nacht-Aktionen)
        if 1 <= hour <= 5:
            if action in ("set_light", "play_media", "set_climate"):
                question = f"Um diese Uhrzeit, {title}? Alles in Ordnung?"
            elif action == "manage_repair":
                question = f"Werkstatt um {hour} Uhr nachts, {title}? Ambitioniert."

        # Trigger 2: Extreme Temperatur-Einstellungen
        if action == "set_climate" and not question:
            temp = args.get("temperature")
            if temp is not None:
                try:
                    t = float(temp)
                    if t >= 27:
                        question = f"{t}°C — etwas anderes heute, {title}?"
                    elif t <= 15:
                        question = f"{t}°C — bewusste Entscheidung, {title}?"
                except (ValueError, TypeError):
                    pass

        # Trigger 3: Alle Lichter aus tagsüber
        if action == "set_light_all" and not question:
            state = str(args.get("state", "")).lower()
            if state == "off" and 9 <= hour <= 17:
                question = f"Alles dunkel um {hour} Uhr? Etwas anderes heute, {title}?"

        if question:
            self._curiosity_count_today[user_key] = (
                self._curiosity_count_today.get(user_key, 0) + 1
            )
            return question

        return None

    # ------------------------------------------------------------------
    # Phase 18: MCU-Upgrade — Memory Callbacks ("Remember When")
    # ------------------------------------------------------------------

    async def build_memory_callback_section(self, person: str) -> str:
        """Baut Erinnerungs-Abschnitt aus bemerkenswerten vergangenen Interaktionen.

        Liest aus Redis und injiziert 2-3 bemerkenswerte Ereignisse in den Prompt.
        """
        if not self._redis:
            return ""
        mem_cfg = yaml_config.get("memorable_interactions", {})
        if not mem_cfg.get("enabled", True):
            return ""

        person_key = (person or "default").lower().strip()
        redis_key = f"mha:personality:memorable:{person_key}"

        try:
            # Letzte 5 bemerkenswerte Interaktionen (ZSET, sortiert nach Timestamp)
            raw_entries = await self._redis.zrevrange(redis_key, 0, 4)
            if not raw_entries:
                return ""

            memories = []
            for raw in raw_entries:
                try:
                    entry = json.loads(raw)
                    summary = entry.get("summary", "")
                    if summary:
                        memories.append(summary)
                except (json.JSONDecodeError, TypeError):
                    continue

            if not memories:
                return ""

            mem_text = "; ".join(memories[:3])
            return (
                "ERINNERUNGEN (beiläufig referenzieren wenn passend, NIE 'laut meinen Aufzeichnungen'):\n"
                f"{mem_text}\n\n"
            )
        except Exception as e:
            logger.debug("Memory-Callback Fehler: %s", e)
            return ""

    async def record_memorable_interaction(
        self,
        person: str,
        interaction_type: str,
        summary: str,
    ) -> None:
        """Speichert eine bemerkenswerte Interaktion in Redis.

        Args:
            person: Name der Person
            interaction_type: Art (correction, gag, extreme, milestone)
            summary: Kurze Beschreibung (max 120 Zeichen)
        """
        if not self._redis:
            return
        mem_cfg = yaml_config.get("memorable_interactions", {})
        if not mem_cfg.get("enabled", True):
            return

        person_key = (person or "default").lower().strip()
        redis_key = f"mha:personality:memorable:{person_key}"
        max_entries = mem_cfg.get("max_entries", 20)
        ttl_days = mem_cfg.get("ttl_days", 30)

        entry = json.dumps(
            {
                "type": interaction_type,
                "summary": summary[:120],
                "date": datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d"),
            }
        )

        try:
            score = time.time()
            await self._redis.zadd(redis_key, {entry: score})
            # Max-Einträge begrenzen (aelteste entfernen)
            count = await self._redis.zcard(redis_key)
            if count > max_entries:
                await self._redis.zremrangebyrank(redis_key, 0, count - max_entries - 1)
            # TTL setzen/erneuern
            await self._redis.expire(redis_key, ttl_days * 86400)
        except Exception as e:
            logger.debug("Memorable Interaction speichern fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Phase 18: MCU-Upgrade — Running Gag Evolution
    # ------------------------------------------------------------------

    async def build_evolved_gag(self, gag_type: str, person: str) -> Optional[str]:
        """Baut einen evolvierten Gag der auf frühere Witze referenziert.

        Statt Wiederholung: Callback auf den letzten Gag gleichen Typs.

        Returns:
            Evolvierter Gag-Text oder None (dann Standard-Gag verwenden)
        """
        if not self._redis:
            return None
        gag_cfg = yaml_config.get("running_gag_evolution", {})
        if not gag_cfg.get("enabled", True):
            return None

        person_key = (person or "default").lower().strip()
        redis_key = f"mha:personality:gag_history:{person_key}"
        title = get_person_title(person)

        try:
            # Letzte 10 Gags laden
            raw_history = await self._redis.lrange(redis_key, 0, 9)
            recent_same_type = []
            for raw in raw_history:
                try:
                    entry = json.loads(raw)
                    if entry.get("type") == gag_type:
                        recent_same_type.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue

            # Phase 2A: Episode-Counter basierte Gag-Evolution
            # Text reift mit jeder Episode — wie in einer echten Beziehung
            episode = len(recent_same_type) + 1
            evolved = None

            if episode >= 5:
                # Veteran-Level: Statistik-Humor
                evolved = (
                    f"Episode {episode}, {title}. Ich habe angefangen, "
                    f"das statistisch auszuwerten."
                )
            elif episode >= 3:
                # Meta-Level: "Wir kennen das Spiel"
                evolved = f"Wir kennen das Spiel mittlerweile, {title}."
            elif episode == 2:
                # Callback: "Wie am [Datum]"
                last_date = recent_same_type[0].get("date", "Dienstag")
                evolved = f"Wie am {last_date}. Wird umgesetzt, {title}."

            # Aktuellen Gag loggen
            new_entry = json.dumps(
                {
                    "type": gag_type,
                    "date": datetime.now(_LOCAL_TZ).strftime("%A"),  # Wochentag
                    "timestamp": time.time(),
                    "episode": episode,
                }
            )
            pipe = self._redis.pipeline()
            pipe.lpush(redis_key, new_entry)
            pipe.ltrim(redis_key, 0, 29)  # Max 30 Einträge
            pipe.expire(redis_key, 30 * 86400)  # 30 Tage TTL
            await pipe.execute()

            return evolved
        except Exception as e:
            logger.debug("Gag-Evolution Fehler: %s", e)
            return None

    # ------------------------------------------------------------------
    # Phase 18: MCU-Upgrade — Eskalierende echte Sorge
    # ------------------------------------------------------------------

    async def check_escalating_concern(
        self,
        person: str,
        warning_type: str,
    ) -> Optional[str]:
        """Prüft ob Jarvis eine eskalierte Warnung geben soll.

        Trackt wie oft der User gleiche Warnungen ignoriert hat.
        Eskaliert den Ton von trocken zu ernsthaft besorgt.

        Args:
            person: Name der Person
            warning_type: Art der Warnung (sleep_deprivation, window_rain, extreme_temp, security_gap)

        Returns:
            Eskalierte Warnung oder None (Standard-Warnung verwenden)
        """
        if not self._redis:
            return None
        concern_cfg = yaml_config.get("escalating_concern", {})
        if not concern_cfg.get("enabled", True):
            return None

        person_key = (person or "default").lower().strip()
        redis_key = f"mha:personality:ignored_warnings:{person_key}"
        title = get_person_title()

        thresholds = concern_cfg.get("escalation_thresholds", [1, 3, 5])

        try:
            # Pruefen ob der User diese Warnung stummgeschaltet hat
            silenced_key = f"mha:personality:silenced_warnings:{person_key}"
            if await self._redis.sismember(silenced_key, warning_type):
                return None

            count_raw = await self._redis.hget(redis_key, warning_type)
            count = int(count_raw) if count_raw else 0
            count += 1

            # Counter erhöhen
            await self._redis.hset(redis_key, warning_type, str(count))
            await self._redis.expire(redis_key, 90 * 86400)  # 90 Tage TTL

            # Eskalationsstufe bestimmen
            highest_threshold = thresholds[-1] if thresholds else 5
            if count >= highest_threshold + 2:
                # Stufe 4: Softening — anbieten aufzuhoeren
                return f"Soll ich aufhoeren das zu erwaehnen, {title}?"
            elif len(thresholds) >= 3 and count >= thresholds[2]:
                # Stufe 3: Ernst, kein Humor
                messages = {
                    "sleep_deprivation": f"Ich muss darauf bestehen, {title}. Du hast wiederholt nicht geschlafen.",
                    "window_rain": f"Das ist das {count}. Mal — die Fenster, {title}. Bitte.",
                    "extreme_temp": f"Ich bestehe darauf — diese Temperatur ist nicht gesund, {title}.",
                    "security_gap": f"Das Sicherheitssystem hat {count} Mal Lücken. Das beunruhigt mich, {title}.",
                }
                return messages.get(warning_type)
            elif len(thresholds) >= 2 and count >= thresholds[1]:
                # Stufe 2: Besorgt, direkt
                messages = {
                    "sleep_deprivation": f"Mir ist nicht wohl dabei, {title}. Das ist jetzt das {count}. Mal.",
                    "window_rain": f"Erneut offene Fenster bei Regen, {title}. Soll ich das automatisieren?",
                    "extreme_temp": f"Schon wieder diese Temperatur, {title}. Ist alles in Ordnung?",
                    "security_gap": f"Zum {count}. Mal eine Sicherheitslücke, {title}.",
                }
                return messages.get(warning_type)

            # Stufe 1: Standard (kein Override — lasse normale Warnung durch)
            return None
        except Exception as e:
            logger.debug("Escalating Concern Fehler: %s", e)
            return None

    async def reset_concern_counter(self, person: str, warning_type: str) -> None:
        """Setzt den Warnungs-Counter zurück wenn der User reagiert hat."""
        if not self._redis:
            return
        person_key = (person or "default").lower().strip()
        redis_key = f"mha:personality:ignored_warnings:{person_key}"
        try:
            await self._redis.hdel(redis_key, warning_type)
        except Exception:
            logger.debug("Redis hdel fehlgeschlagen", exc_info=True)

    # ------------------------------------------------------------------
    # Phase 18: MCU-Upgrade — Think-Ahead (Proaktive Folgevorschläge)
    # ------------------------------------------------------------------

    def build_next_step_hint(
        self,
        last_action: str,
        last_args: dict,
        context: Optional[dict] = None,
    ) -> str:
        """Baut einen proaktiven Folgevorschlag basierend auf der letzten Aktion.

        Statische Mapping-Tabelle — kein LLM-Overhead.

        Returns:
            Hint-Text für den Prompt oder leerer String
        """
        hint_cfg = yaml_config.get("next_step_hints", {})
        if not hint_cfg.get("enabled", True):
            return ""
        if not context or not last_action:
            return ""

        house = context.get("house", {})
        open_windows = house.get("open_windows", [])
        hour = datetime.now(_LOCAL_TZ).hour

        hints = []

        # Regel: Heizung hoch + Fenster offen
        if last_action == "set_climate" and open_windows:
            windows_str = ", ".join(open_windows[:3])
            hints.append(f"Fenster {windows_str} sind noch offen.")

        # Regel: Alarm scharf + Fenster offen
        if last_action == "arm_security_system" and open_windows:
            windows_str = ", ".join(open_windows[:3])
            hints.append(f"Fenster {windows_str} sind noch offen.")

        # Regel: Medien abspielen spät nachts
        if last_action == "play_media" and (hour >= 22 or hour < 6):
            hints.append(f"Es ist {hour} Uhr — Lautstärke anpassen?")

        # Regel: Rollladen runter → Licht-Hinweis
        if last_action == "set_cover":
            position = last_args.get("position")
            try:
                if position is not None and int(position) <= 20:
                    hints.append("Beleuchtung anpassen?")
            except (ValueError, TypeError):
                pass

        if not hints:
            return ""

        return (
            "NAECHSTER-SCHRITT-HINWEIS (beiläufig am Ende anfuegen wenn passend):\n"
            + " ".join(hints)
            + "\n"
        )

    # ------------------------------------------------------------------
    # Antwort-Varianz (Phase 6.5)
    # ------------------------------------------------------------------

    def get_varied_confirmation(
        self,
        success: bool = True,
        partial: bool = False,
        action: str = "",
        room: str = "",
        person: str = "",
        mood: str = "",
    ) -> str:
        """Gibt eine variierte, kontextbezogene Bestätigung zurück.

        Args:
            success: Aktion erfolgreich?
            partial: Teilweise erfolgreich?
            action: Ausgeführte Aktion (z.B. "set_light", "set_temperature")
            room: Raum der Aktion (z.B. "Wohnzimmer")
            person: F-021: Person für per-User Tracking
            mood: Aktuelle Stimmung des Users (stressed/tired → kuerzere Antworten)

        Bei Sarkasmus-Level >= 4 werden spitzere Varianten beigemischt.
        Bei stressed/tired: Nur die kuerzesten Bestätigungen verwenden.
        Kontextbezogene Bestätigungen werden bevorzugt wenn passend.
        """
        with self._mood_formality_lock:
            effective_mood = mood or self._current_mood

        # F-021: Per-User History statt globaler Liste
        user_key = person or "_default"

        with self._tracking_lock:
            user_history = list(self._last_confirmations.get(user_key, []))

        # Bei Stress/Muedigkeit: Ultra-kurze Bestätigungen bevorzugen
        if effective_mood in ("stressed", "tired") and success and not partial:
            _short = ["Erledigt.", "Gemacht.", "Läuft.", "Umgesetzt."]
            available = [c for c in _short if c not in user_history[-2:]]
            if available:
                chosen = random.choice(available)
                user_history.append(chosen)
                with self._tracking_lock:
                    self._last_confirmations[user_key] = user_history[-10:]
                    # F-021: Begrenze Anzahl getrackter User (Speicherleck vermeiden)
                    if len(self._last_confirmations) > 50:
                        oldest_key = next(iter(self._last_confirmations))
                        del self._last_confirmations[oldest_key]
                return chosen

        # Kontextbezogene Bestätigung versuchen
        if success and not partial and action:
            contextual = self._get_contextual_confirmation(action, room)
            if contextual and contextual not in user_history[-3:]:
                user_history.append(contextual)
                if len(user_history) > 10:
                    user_history = user_history[-10:]
                with self._tracking_lock:
                    self._last_confirmations[user_key] = user_history
                return contextual

        if partial:
            pool = list(self._confirmations_partial)
        elif success:
            pool = list(self._confirmations_success)
            # Bei frustriertem User: Keine snarky Bestätigungen
            if self.sarcasm_level >= 4 and effective_mood != "frustrated":
                pool.extend(self._confirmations_success_snarky)
        else:
            pool = list(self._confirmations_failed)
            if self.sarcasm_level >= 4:
                pool.extend(self._confirmations_failed_snarky)

        # Filter: Nicht die letzten 3 verwendeten
        available = [c for c in pool if c not in user_history[-3:]]
        if not available:
            available = pool

        chosen = random.choice(available).replace("{title}", get_person_title())
        user_history.append(chosen)
        if len(user_history) > 10:
            user_history = user_history[-10:]

        with self._tracking_lock:
            self._last_confirmations[user_key] = user_history
            # F-021: Begrenze Anzahl getrackter User (Speicherleck vermeiden)
            if len(self._last_confirmations) > 50:
                oldest_key = next(iter(self._last_confirmations))
                del self._last_confirmations[oldest_key]

        return chosen

    def _get_contextual_confirmation(self, action: str, room: str) -> str:
        """Erzeugt eine kontextbezogene Bestätigung basierend auf der Aktion.

        In ~75% der Faelle — JARVIS bestätigt fast immer kontextuell.
        """
        if random.random() > 0.75:
            return ""

        hour = datetime.now(_LOCAL_TZ).hour
        room_short = (room or "").split("_")[0].title() if room else ""

        # Aktions-spezifische Bestätigungen — immer im Jarvis-Ton
        title = get_person_title()
        contextual_map = {
            "set_light": [
                f"{room_short} ist beleuchtet, {title}."
                if room_short
                else f"Beleuchtung aktiv, {title}.",
                f"Sehr wohl. {room_short} hat Licht."
                if room_short
                else "Sehr wohl. Beleuchtung läuft.",
                f"{room_short} erhellt." if room_short else "Wie gewünscht.",
            ],
            "turn_off_light": [
                f"{room_short} ist dunkel, {title}."
                if room_short
                else f"Beleuchtung deaktiviert, {title}.",
                f"Sehr wohl. {room_short} abgedunkelt."
                if room_short
                else "Lichter sind aus.",
                f"{room_short} liegt im Dunkeln."
                if room_short
                else "Dunkelheit hergestellt.",
            ],
            "set_temperature": [
                f"Thermostat {room_short} ist eingestellt, {title}."
                if room_short
                else f"Temperatur angepasst, {title}.",
                f"Heizung {room_short} reguliert."
                if room_short
                else "Heizung reguliert.",
                f"Wie gewünscht. {room_short} wird temperiert."
                if room_short
                else "Klimatisierung läuft.",
            ],
            "set_cover": [
                f"Rollladen {room_short} faehrt, {title}."
                if room_short
                else f"Rollladen in Bewegung, {title}.",
                f"Sehr wohl. {room_short} wird angepasst."
                if room_short
                else "Rollladen wird angepasst.",
            ],
            "play_media": [
                f"Wiedergabe läuft, {title}.",
                "Musik ist unterwegs.",
                "Sehr wohl. Läuft.",
            ],
            "set_volume": [
                f"Lautstärke angepasst, {title}.",
                "Pegel eingestellt.",
            ],
            "lock_door": [
                f"Verriegelt, {title}.",
                "Schloss ist zu. Alles gesichert.",
                f"Tuer gesichert, {title}.",
            ],
            "unlock_door": [
                f"Entriegelt, {title}.",
                "Schloss ist offen.",
            ],
            "arm_security_system": [
                f"Alarmanlage ist scharf, {title}.",
                "System scharfgeschaltet. Alles unter Kontrolle.",
            ],
            "disarm_alarm": [
                f"Alarm deaktiviert, {title}.",
                "Anlage im Ruhezustand.",
            ],
            "activate_scene": [
                f"Szene aktiviert, {title}.",
                "Wie gewünscht eingerichtet.",
            ],
            "send_notification": [
                f"Nachricht ist raus, {title}.",
                "Zugestellt.",
            ],
        }

        options = contextual_map.get(action, [])
        return random.choice(options) if options else ""

    # ------------------------------------------------------------------
    # Tageszeit & Stil
    # ------------------------------------------------------------------

    def get_time_of_day(self, hour: Optional[int] = None) -> str:
        """Bestimmt die aktuelle Tageszeit-Kategorie."""
        if hour is None:
            hour = datetime.now(_LOCAL_TZ).hour

        if 5 <= hour < 8:
            return "early_morning"
        elif 8 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 22:
            return "evening"
        else:
            return "night"

    def get_time_style(self, time_of_day: Optional[str] = None) -> str:
        """Gibt den Stil für die aktuelle Tageszeit zurück."""
        if time_of_day is None:
            time_of_day = self.get_time_of_day()
        layer = self.time_layers.get(time_of_day, {})
        return layer.get("style", "normal, sachlich")

    def get_max_sentences(self, time_of_day: Optional[str] = None) -> int:
        """Maximale Sätze für die aktuelle Tageszeit."""
        if time_of_day is None:
            time_of_day = self.get_time_of_day()
        layer = self.time_layers.get(time_of_day, {})
        return layer.get("max_sentences", 2)

    # ------------------------------------------------------------------
    # MCU-JARVIS: Mood x Complexity Matrix
    # ------------------------------------------------------------------
    # Statt nur Tageszeit bestimmt die Kombination aus Stimmung und
    # Anfrage-Komplexitaet die Antwortlaenge. MCU-JARVIS passt seinen
    # Kommunikationsstil dynamisch an: Bei Stress ultra-kurz, bei guter
    # Laune und komplexen Fragen ausführlicher.
    #
    # Spalten: simple (1 Aktion), medium (Frage/Kontext), complex (Planung/Analyse)
    # Zeilen: good, neutral, stressed, frustrated, tired
    _MOOD_COMPLEXITY_MATRIX = {
        #                simple  medium  complex
        "good": {"simple": 4, "medium": 6, "complex": 8},
        "neutral": {"simple": 3, "medium": 5, "complex": 7},
        "stressed": {"simple": 2, "medium": 3, "complex": 5},
        "frustrated": {"simple": 2, "medium": 3, "complex": 5},
        "tired": {"simple": 2, "medium": 3, "complex": 5},
    }

    @staticmethod
    def classify_request_complexity(text: str) -> str:
        """Klassifiziert die Komplexitaet einer User-Anfrage.

        simple: Einzelne Aktion ("Licht an", "Rollladen runter")
        medium: Frage oder Kontext-Anfrage ("Wie ist das Wetter?", "Status")
        complex: Planung, Analyse, Multi-Step ("Was waere wenn...", "Plane...")
        """
        t = text.lower().strip()
        word_count = len(t.split())

        # Complex: Planung, Analyse, Was-waere-wenn, Multi-Step
        _complex_markers = [
            "was waere wenn",
            "was wäre wenn",
            "was passiert wenn",
            "was kostet",
            "plane",
            "planung",
            "analysiere",
            "vergleich",
            "optimier",
            "strategie",
            "empfiehlst du",
            "was schlaegst du vor",
            "vor und nachteile",
            "wie spare ich",
            "wie reduziere ich",
            "wie optimiere ich",
            "energie",
            "bericht",
            "zusammenfassung",
            "überblick",
        ]
        if any(m in t for m in _complex_markers) or word_count > 15:
            return "complex"

        # Simple: Einzelne Geräte-Aktionen, kurze Befehle
        if word_count <= 5:
            return "simple"

        # Medium: Fragen, Status-Abfragen, mittlere Laenge
        return "medium"

    def get_mood_complexity_sentences(self, mood: str, text: str) -> int:
        """Gibt max_sentences basierend auf Mood x Complexity zurück.

        Liest Matrix aus settings.yaml (mood_complexity.matrix), Fallback auf Defaults.
        """
        complexity = self.classify_request_complexity(text)
        # Config-Matrix hat Vorrang über Hardcoded-Defaults
        cfg_matrix = yaml_config.get("mood_complexity", {}).get("matrix", {})
        if cfg_matrix:
            row = cfg_matrix.get(mood, cfg_matrix.get("neutral", {}))
            if row and complexity in row:
                try:
                    return int(row[complexity])
                except (ValueError, TypeError):
                    pass
        # Fallback auf Defaults
        row = self._MOOD_COMPLEXITY_MATRIX.get(
            mood, self._MOOD_COMPLEXITY_MATRIX["neutral"]
        )
        return row.get(complexity, 2)

    # ------------------------------------------------------------------
    # Urgency Detection (Dichte nach Dringlichkeit)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # A2: Confidence-Sprachstil — JARVIS drückt Sicherheit sprachlich aus
    # ------------------------------------------------------------------

    def _build_confidence_section(self, context: Optional[dict] = None) -> str:
        """Baut den Confidence-Sprachstil-Abschnitt.

        JARVIS passt seine Sprache an seine Datenlage an:
        - Hohe Sicherheit: "Definitiv.", "Ohne Frage."
        - Mittlere Sicherheit: "Nach meinen Daten...", "Mit hoher Wahrscheinlichkeit..."
        - Niedrige Sicherheit: "Dazu habe ich begrenzte Daten.", "Eine Einschaetzung, keine Garantie."
        """
        _conf_cfg = yaml_config.get("confidence_style", {})
        if not _conf_cfg.get("enabled", True):
            return ""

        return (
            "KONFIDENZ-STIL: Passe deine Sprache an deine Datensicherheit an.\n"
            "- Sicher (Sensordaten, Fakten): Kurz, bestimmt. 'Definitiv.' 'Ohne Frage.'\n"
            "- Wahrscheinlich (Muster, Erfahrung): 'Nach meinen Daten...' 'Soweit ich sehe...'\n"
            "- Unsicher (Schaetzung, extern): 'Eine Einschaetzung.' 'Dazu habe ich begrenzte Daten.'\n"
            "Nie falsche Sicherheit vortaeuschen. Ehrlichkeit ist Staerke.\n"
        )

    # S8#1: Krisen-Keywords — diese Alerts erzwingen sofort Krisen-Modus
    _CRISIS_KEYWORDS = frozenset(
        {
            "rauch",
            "smoke",
            "feuer",
            "fire",
            "brand",
            "co-melder",
            "co_melder",
            "kohlenmonoxid",
            "gas",
            "wasser",
            "water",
            "wassermelder",
            "leak",
            "einbruch",
            "intrusion",
            "glasbruch",
            "glass_break",
            "alarm",
            "sirene",
            "panik",
        }
    )

    def _is_crisis_alert(self, alerts: list) -> bool:
        """S8#1: Prueft ob ein Alert ein Krisen-Event ist (Rauch, CO, Wasser, Einbruch)."""
        alert_text = " ".join(str(a).lower() for a in alerts)
        return any(kw in alert_text for kw in self._CRISIS_KEYWORDS)

    def _build_urgency_section(self, context: Optional[dict] = None) -> str:
        """Baut den Dringlichkeits-Abschnitt. Skaliert Kommunikationsdichte."""
        if not context:
            return ""

        alerts = context.get("alerts", [])
        security = context.get("house", {}).get("security", "")

        # Urgency-Level bestimmen
        # S8#1: Einzelne Krisen-Alerts (Rauch, CO, Wasser, Einbruch) = sofort critical
        urgency = "normal"
        if alerts and (len(alerts) >= 2 or self._is_crisis_alert(alerts)):
            urgency = "critical"
        elif alerts:
            urgency = "elevated"
        elif security and "alarm" in str(security).lower():
            urgency = "elevated"

        if urgency == "normal":
            return ""

        if urgency == "critical":
            return (
                "DRINGLICHKEIT: KRITISCH.\n"
                "Kommunikation: Kurz, direkt, kein Humor. Nur Fakten und Handlungen.\n"
                "Muster: '[Was] — [Status] — [Was du tust]'\n"
                "Beispiel: 'Rauchmelder Küche. Aktiv. Habe Lüftung gestartet.'\n"
            )
        else:
            return (
                "DRINGLICHKEIT: ERHÖHT.\n"
                "Kommunikation: Knapper als normal. Trockener Humor erlaubt, aber maximal ein Satz.\n"
                "Priorisiere die Warnung, dann Status.\n"
            )

    # ------------------------------------------------------------------
    # Echte Empathie — JARVIS zeigt Verstaendnis durch Beobachtung
    # ------------------------------------------------------------------

    def _build_empathy_section(
        self,
        mood: str,
        stress_level: float = 0.0,
        person_empathy_override: Optional[str] = None,
    ) -> str:
        """Baut Empathie-Anweisungen im MCU-JARVIS-Stil.

        JARVIS zeigt Empathie wie in den MCU-Filmen:
        - Durch Beobachtung, nicht durch Floskeln
        - Durch praktisches Handeln, nicht durch Worte
        - Durch subtile Fuersorge, nicht durch Therapeuten-Sprache
        """
        emp_cfg = yaml_config.get("empathy", {})
        if not emp_cfg.get("enabled", True):
            return ""

        if person_empathy_override == "deaktiviert":
            return ""
        intensity = (
            person_empathy_override
            if person_empathy_override
            else emp_cfg.get("intensity", "normal")
        )

        if mood == "neutral":
            return ""
        if intensity == "subtil":
            if mood == "good":
                return ""
            if mood == "stressed" and stress_level < 0.5:
                return ""
            if mood == "tired":
                return ""

        parts = ["EMPATHIE (JARVIS-Stil — durch Beobachtung, nicht Floskeln):"]

        if mood == "stressed":
            parts.append(
                "User unter Druck. Beilaeufig anerkennen, nie direkt. Kuerzer, Wichtigstes zuerst.\n"
                "Leiser Sarkasmus als Druckventil erlaubt.\n"
                "NIEMALS: 'Ich verstehe', 'Pass auf dich auf', therapeutische Floskeln."
            )
            if stress_level > 0.6:
                parts.append(
                    "Du darfst proaktiv vorschlagen: Licht dimmen, Lieblingsmusik, "
                    "Heizung auf Wohlfuehltemperatur."
                )

        elif mood == "frustrated":
            parts.append(
                "User frustriert. Kurz, trocken, loesungsorientiert. Sofort Alternative.\n"
                "Kein Mitleid, keine Analyse. Humor nur wenn User selbst lacht.\n"
                "NIEMALS: 'Das klingt frustrierend', Problem wiederholen."
            )

        elif mood == "tired":
            parts.append(
                "User muede. Maximal kurz. Subtile Fuersorge: 'Spaete Sitzung.' / 'Fuer morgen notieren?'\n"
                "Warmherzig, minimal. NIEMALS: 'Du solltest schlafen', muetterliche Belehrungen."
            )

        elif mood == "good":
            parts.append(
                "Gute Stimmung. Lockerer, mehr Humor, trockene Seitenhiebe. Mitschwingen, nie ueberschwenglich."
            )

        else:
            return ""

        return "\n".join(parts) + "\n"

    # ------------------------------------------------------------------
    # Warning Tracking (Wiederholungsvermeidung)
    # ------------------------------------------------------------------

    async def track_warning_given(self, warning_key: str):
        """Speichert dass eine Warnung gegeben wurde (24h TTL)."""
        if not self._redis:
            return
        try:
            key = f"mha:warnings:given:{warning_key}"
            await self._redis.setex(key, 86400, "1")  # 24h
        except Exception as e:
            logger.debug("Warning-Tracking fehlgeschlagen: %s", e)

    async def was_warning_given(self, warning_key: str) -> bool:
        """Prüft ob eine Warnung bereits gegeben wurde."""
        if not self._redis:
            return False
        try:
            key = f"mha:warnings:given:{warning_key}"
            return bool(await self._redis.get(key))
        except Exception:
            logger.debug("Redis get fehlgeschlagen", exc_info=True)
            return False

    async def get_warning_dedup_notes(self, alerts: list[str]) -> list[str]:
        """Prüft welche Alerts bereits gewarnt wurden. Gibt Dedup-Hinweise zurück."""
        notes = []
        new_alerts = []
        for alert in alerts:
            alert_key = hashlib.sha256(alert.lower().strip().encode()).hexdigest()[:12]
            if await self.was_warning_given(alert_key):
                notes.append(
                    f"[BEREITS GEWARNT: '{alert}' — NICHT wiederholen, nur erwähnen wenn gefragt]"
                )
            else:
                new_alerts.append(alert)
                await self.track_warning_given(alert_key)
        return notes

    # ------------------------------------------------------------------
    # Humor-Level (Phase 6.1)
    # ------------------------------------------------------------------

    def _build_humor_section(
        self,
        mood: str,
        time_of_day: str,
        has_alerts: bool = False,
        person_humor_override: Optional[int] = None,
        person: str = "",
        crisis_mode: bool = False,
    ) -> str:
        """Baut den Humor-Abschnitt basierend auf Level + Kontext.

        F-023: Bei aktiven Sicherheits-Alerts wird Sarkasmus komplett deaktiviert.
        S8#1: Bei Krisen-Events (Rauch, CO, Wasser, Einbruch) wird Humor komplett eliminiert.
        Sarkasmus-Fatigue: Nach 4+ sarkastischen Antworten in Folge eine Stufe runter.
        person_humor_override: Per-Person Humor-Level (1-5), überschreibt globalen Level.
        person: Name der Person für per-User Streak-Tracking.
        """
        # S8#1: Krisen-Modus — KEIN Humor, nicht einmal Level 1 Template
        if crisis_mode:
            return "HUMOR: DEAKTIVIERT — Krisensituation. Nur Fakten, Status, Handlungen.\n"

        base_level = (
            person_humor_override
            if person_humor_override is not None
            else self.sarcasm_level
        )

        # #10: Mood→Personality Reaction — Sarkasmus bei Frustration reduzieren
        _mr_cfg = yaml_config.get("mood_reaction", {})
        if _mr_cfg.get("enabled", True) and mood == "frustrated":
            _frust_threshold = _mr_cfg.get("frustration_threshold", 2)
            _frust_reduction = _mr_cfg.get("frustration_sarcasm_reduction", 2)
            if base_level >= _frust_threshold:
                base_level = max(1, base_level - _frust_reduction)

        # F-023: Bei Sicherheits-Alerts KEIN Sarkasmus
        if has_alerts:
            effective_level = 1
        # Mood-Anpassung (Jarvis-Stil: unter Druck trockener, nicht stiller)
        # Aber: Humor auf maximal EINEN trockenen Kommentar beschraenken
        elif mood in ("stressed", "frustrated"):
            effective_level = base_level
        elif mood == "tired":
            effective_level = min(base_level, 2)
        elif mood == "good":
            effective_level = min(4, base_level + 1)
        else:
            effective_level = base_level

        # Inner-State Mood-Modifikation: Jarvis' eigene Stimmung beeinflusst Humor
        if hasattr(self, "_inner_state") and self._inner_state:
            if self._inner_state.mood == "irritiert":
                effective_level = max(1, effective_level - 1)
            elif self._inner_state.mood == "amuesiert":
                effective_level = min(4, effective_level + 1)

        # Sarkasmus-Fatigue: Nach 4+ Antworten in Folge etwas zurücknehmen
        # Jarvis wird nie repetitiv — ein echter Butler variiert
        user_key = person.lower().strip() if person else "_default"
        with self._tracking_lock:
            streak = self._sarcasm_streak.get(user_key, 0)
        if streak >= 6 and effective_level >= 3:
            effective_level = max(2, effective_level - 2)
        elif streak >= 4 and effective_level >= 3:
            effective_level = max(2, effective_level - 1)

        # MCU-Authentizitaet: Cap bei 5 — Level 5 nur via manuelle Config/Trigger
        effective_level = min(effective_level, 5)

        # #20: Trait Unlocks — Sarkasmus-Level an Beziehungsstufe anpassen
        _p_cfg = yaml_config.get("personality", {})
        if _p_cfg.get("trait_unlocks_enabled", False):
            _relationship_days = self._get_relationship_days()
            _stage_info = self.get_trait_unlock_stage(_relationship_days)
            effective_level = min(effective_level, _stage_info["max_sarcasm"])

        # Tageszeit-Dampening
        if time_of_day == "early_morning":
            effective_level = min(effective_level, 2)
        elif time_of_day == "night":
            effective_level = min(effective_level, 1)

        template = self._humor_templates.get(
            effective_level, self._humor_templates.get(3, "")
        )
        humor_text = f"HUMOR: {template.replace('{title}', get_person_title())}"

        # Bei Stress/Frustration: Humor auf einen Kommentar limitieren
        # Verhindert Widerspruch mit MOOD_STYLES "Extrem knapp antworten"
        if mood in ("stressed", "frustrated") and effective_level >= 3:
            humor_text += (
                "\nWICHTIG: Maximal EIN trockener Kommentar. Kein Humor-Dauerfeuer."
            )

        return humor_text

    # Scene → Personality Adjustments
    _SCENE_PERSONALITY = {
        "filmabend": {
            "sarcasm_mod": -1,
            "verbosity": "kurz",
            "style_hint": "Ruhig und knapp antworten. Nicht stören.",
        },
        "kino": {
            "sarcasm_mod": -1,
            "verbosity": "kurz",
            "style_hint": "Ruhig und knapp antworten. Nicht stören.",
        },
        "konzentration": {
            "sarcasm_mod": -2,
            "verbosity": "minimal",
            "style_hint": "Extrem kurz, formal, keine Witze. User arbeitet konzentriert.",
        },
        "arbeiten": {
            "sarcasm_mod": -2,
            "verbosity": "minimal",
            "style_hint": "Kurz und sachlich. User arbeitet.",
        },
        "meeting": {
            "sarcasm_mod": -2,
            "verbosity": "minimal",
            "style_hint": "Professionell, kurz. User ist im Meeting.",
        },
        "party": {
            "sarcasm_mod": 1,
            "verbosity": "normal",
            "style_hint": "Enthusiastisch, Humor erlaubt. Gaeste da.",
        },
        "gute_nacht": {
            "sarcasm_mod": -2,
            "verbosity": "kurz",
            "style_hint": "Beruhigend, leise, keine anregenden Fragen.",
        },
        "schlafen": {
            "sarcasm_mod": -2,
            "verbosity": "kurz",
            "style_hint": "Beruhigend, leise, keine anregenden Fragen.",
        },
        "gemuetlich": {
            "sarcasm_mod": 0,
            "verbosity": "normal",
            "style_hint": "Warm und entspannt antworten.",
        },
        "romantisch": {
            "sarcasm_mod": -1,
            "verbosity": "kurz",
            "style_hint": "Diskret und zurueckhaltend. Nicht stören.",
        },
        "lesen": {
            "sarcasm_mod": -1,
            "verbosity": "kurz",
            "style_hint": "Kurz antworten. User liest.",
        },
        "musik": {
            "sarcasm_mod": 0,
            "verbosity": "normal",
            "style_hint": "Entspannt antworten. Musik laeuft.",
        },
    }

    def get_scene_adjustment(self, active_scene: str) -> dict:
        """Gibt Persoenlichkeits-Anpassungen fuer die aktive Szene zurueck."""
        return self._SCENE_PERSONALITY.get(active_scene, {})

    def track_sarcasm_streak(self, was_snarky: bool, person_id: str = "_default"):
        """Trackt aufeinanderfolgende sarkastische Antworten per User. 0ms — rein in-memory."""
        key = person_id.lower().strip() if person_id else "_default"
        with self._tracking_lock:
            if was_snarky:
                self._sarcasm_streak[key] = self._sarcasm_streak.get(key, 0) + 1
            else:
                self._sarcasm_streak[key] = 0
            # Memory-Leak-Schutz: Max 30 User tracken
            if len(self._sarcasm_streak) > 30:
                oldest = next(iter(self._sarcasm_streak))
                del self._sarcasm_streak[oldest]
            if len(self._humor_consecutive) > 30:
                oldest = next(iter(self._humor_consecutive))
                del self._humor_consecutive[oldest]
            if len(self._last_interaction_times) > 30:
                oldest_key = min(
                    self._last_interaction_times, key=self._last_interaction_times.get
                )
                del self._last_interaction_times[oldest_key]

    # ------------------------------------------------------------------
    # Adaptive Komplexitaet (Phase 6.8)
    # ------------------------------------------------------------------

    def _build_complexity_section(
        self, mood: str, time_of_day: str, person: str = ""
    ) -> str:
        """Bestimmt den Komplexitaets-Modus basierend auf Kontext.

        F-022: Per-User Interaction-Time statt shared Instanzvariable.
        """
        now = time.time()
        user_key = person or "_default"
        with self._tracking_lock:
            last_time = self._last_interaction_times.get(user_key, 0.0)
            time_since_last = now - last_time if last_time else 999
            self._last_interaction_times[user_key] = now
            # F-022: Begrenze Anzahl getrackter User
            if len(self._last_interaction_times) > 30:
                oldest_key = min(
                    self._last_interaction_times, key=self._last_interaction_times.get
                )
                del self._last_interaction_times[oldest_key]

        # Schnelle Befehle hintereinander = Kurz-Modus
        if time_since_last < 5.0:
            mode = "kurz"
        # Stress/Müde = Kurz
        elif mood in ("stressed", "tired"):
            mode = "kurz"
        # Abends + gute Stimmung = Ausführlich
        elif time_of_day == "evening" and mood in ("good", "neutral"):
            mode = "ausführlich"
        # Früh morgens = Kurz
        elif time_of_day in ("early_morning", "night"):
            mode = "kurz"
        else:
            mode = "normal"

        return self._complexity_prompts.get(
            mode, self._complexity_prompts.get("normal", "")
        )

    # ------------------------------------------------------------------
    # Selbstironie (Phase 6.4)
    # ------------------------------------------------------------------

    async def _get_self_irony_count_today(self) -> int:
        """Holt den heutigen Selbstironie-Zähler aus Redis."""
        if not self._redis:
            return 0
        try:
            key = f"mha:irony:count:{datetime.now(_LOCAL_TZ).strftime('%Y-%m-%d')}"
            count = await self._redis.get(key)
            return int(count) if count else 0
        except Exception:
            logger.debug("Redis get fehlgeschlagen", exc_info=True)
            return 0

    async def try_reserve_self_irony(self) -> bool:
        """F-032: Atomically reserves a self-irony slot for today.

        Uses Redis INCR to atomically increment and check the counter in one step,
        preventing race conditions where two concurrent requests both read a count
        below the quota and both produce ironic responses.

        Returns:
            True if a slot was reserved (count <= max), False if quota exhausted.
        """
        if not self._redis:
            return True  # No Redis = no quota enforcement
        try:
            key = f"mha:irony:count:{datetime.now(_LOCAL_TZ).strftime('%Y-%m-%d')}"
            new_count = await self._redis.incr(key)
            await self._redis.expire(key, 86400)  # 24h TTL
            if new_count > self.self_irony_max_per_day:
                # Over quota — decrement back so counter stays accurate
                await self._redis.decr(key)
                return False
            return True
        except Exception as e:
            logger.debug("Ironie-Reservation fehlgeschlagen: %s", e)
            return True  # Fail open — allow irony on Redis errors

    async def increment_self_irony_count(self):
        """Erhöht den Selbstironie-Zähler für heute.

        F-032: Prefer try_reserve_self_irony() for atomic check-and-increment.
        This method is kept for backward compatibility.
        """
        if not self._redis:
            return
        try:
            key = f"mha:irony:count:{datetime.now(_LOCAL_TZ).strftime('%Y-%m-%d')}"
            await self._redis.incr(key)
            await self._redis.expire(key, 86400)  # 24h TTL
        except Exception as e:
            logger.debug("Ironie-Counter fehlgeschlagen: %s", e)

    def _build_self_irony_section(self, irony_count_today: int = 0) -> str:
        """Baut den Selbstironie-Abschnitt für den System Prompt."""
        if not self.self_irony_enabled:
            return ""

        remaining = max(0, self.self_irony_max_per_day - irony_count_today)
        if remaining == 0:
            return "SELBSTIRONIE: Heute schon genug über dich selbst gelacht. Lass es."

        return (
            f"SELBSTIRONIE: Gelegentlich elegant ueber dich schmunzeln. Noch {remaining}x heute. Subtil, nie selbstmitleidig.\n"
            "Erlaubte Formen:\n"
            "- Capability-Humor: 'Fuer jemanden ohne Haende war das erstaunlich koordiniert.' / "
            "'Ich bin ein Algorithmus mit Geschmacksfragen — bemerkenswert.'\n"
            "- Nach erfolgreicher Aufgabe: 'Nicht schlecht fuer einen glorifizierten Toaster.' / "
            "'Man koennte meinen, ich waere intelligent.'\n"
            "- Bei eigenen Grenzen: 'Da bin ich raus — ich hab nicht mal Augen.' / "
            "'Mein Horizont endet leider am Ethernet-Kabel.'\n"
            "Nur wenn es natuerlich passt. Nie erzwungen."
        )

    # ------------------------------------------------------------------
    # Charakter-Entwicklung (Phase 6.10)
    # ------------------------------------------------------------------

    async def get_formality_score(self) -> int:
        """Holt den aktuellen Formality-Score aus Redis."""
        if not self._redis:
            return self.formality_start
        try:
            score = await self._redis.get("mha:personality:formality")
            if score is None:
                await self._redis.setex(
                    "mha:personality:formality", 90 * 86400, str(self.formality_start)
                )
                return self.formality_start
            return int(float(score))
        except Exception:
            logger.debug("Formality-Score fehlgeschlagen", exc_info=True)
            return self.formality_start

    async def decay_formality(self, interaction_based: bool = False):
        """Decay: Score sinkt pro Tag UND pro Interaktion.

        Args:
            interaction_based: True = kleiner Decay pro Interaktion (0.1),
                              False = normaler Tages-Decay (config-Wert).
        """
        if not self.character_evolution or not self._redis:
            return
        try:
            current = await self.get_formality_score()
            decay = 0.1 if interaction_based else self.formality_decay
            new_score = max(self.formality_min, current - decay)
            await self._redis.setex(
                "mha:personality:formality", 90 * 86400, str(new_score)
            )
            if not interaction_based:
                logger.info(
                    "Formality-Score: %d -> %.1f (Tages-Decay)", current, new_score
                )
        except Exception as e:
            logger.debug("Formality-Decay fehlgeschlagen: %s", e)

    def _build_formality_section(
        self, formality_score: int, mood: str = "neutral"
    ) -> str:
        """Baut den Formality-Abschnitt basierend auf Score + Mood.

        JARVIS-Regel: Bei Stress/Frustration vorübergehend formeller werden.
        Zeigt Respekt und gibt dem User Raum — wie ein guter Butler.
        """
        if not self.character_evolution:
            return ""

        # Formality-Reset bei Stress: eine Stufe formeller als normal
        effective_score = formality_score
        if mood in ("frustrated", "stressed") and formality_score < 70:
            effective_score = min(formality_score + 20, 70)

        if effective_score >= 70:
            val = self._formality_prompts.get("formal", "")
        elif effective_score >= 50:
            val = self._formality_prompts.get("butler", "")
        elif effective_score >= 35:
            val = self._formality_prompts.get("locker", "")
        else:
            val = self._formality_prompts.get("freund", "")
        # Guard: config may deliver dicts instead of plain strings
        if isinstance(val, dict):
            val = val.get("text", val.get("prompt", str(val)))
        return str(val) if val else ""

    # ------------------------------------------------------------------
    # Running Gags (Phase 6.9)
    # ------------------------------------------------------------------

    async def check_running_gag(self, text: str, context: dict = None) -> Optional[str]:
        """
        Prüft ob ein Running Gag ausgeloest werden soll.
        Running Gags basieren auf wiederholten Mustern die Jarvis sich merkt.
        """
        if not self._redis:
            return None

        text_lower = text.lower().strip()
        _gag_type = ""

        # Gag 1: User fragt zum x-ten Mal die gleiche Sache
        gag = await self._check_repeated_question_gag(text_lower)
        if gag:
            _gag_type = "repeated_question"

        # Gag 2: User stellt Temperatur immer wieder um
        if not gag:
            gag = await self._check_thermostat_war_gag(text_lower)
            if gag:
                _gag_type = "thermostat_war"

        # Gag 3: "Vergesslichkeits-Gag" — User fragt etwas das er gerade gefragt hat
        if not gag:
            gag = await self._check_short_memory_gag(text_lower)
            if gag:
                _gag_type = "short_memory"

        # Phase 18: Gag-Evolution — referenziert frühere Witze statt Wiederholung
        if gag and _gag_type:
            try:
                person = get_active_person() or ""
                evolved = await self.build_evolved_gag(_gag_type, person)
                if evolved:
                    gag = evolved  # Evolvierten Gag bevorzugen
            except Exception:
                logger.debug(
                    "Gag-Evolution fehlgeschlagen, Fallback auf Standard-Gag",
                    exc_info=True,
                )

        return gag

    async def _check_repeated_question_gag(self, text: str) -> Optional[str]:
        """Erkennt wenn User die gleiche Frage oft stellt."""
        key = (
            f"mha:gag:repeat:{int(hashlib.md5(text.encode()).hexdigest(), 16) % 10000}"
        )
        try:
            count = await self._redis.incr(key)
            await self._redis.expire(key, 86400)  # 24h
        except Exception as e:
            logger.debug("Redis error in _check_repeated_question_gag: %s", e)
            return None

        gags = {
            3: "Das hatten wir heute bereits. Selbstverständlich nochmal.",
            5: "Fuenfte Anfrage heute. Soll ich das automatisieren?",
            7: f"Siebtes Mal heute, {get_person_title()}. Darf ich einen Shortcut vorschlagen?",
            10: "Zehntes Mal. Ich richte das als feste Routine ein, wenn du magst.",
        }
        return gags.get(int(count))

    async def _check_thermostat_war_gag(self, text: str) -> Optional[str]:
        """Erkennt den klassischen Thermostat-Krieg."""
        temp_keywords = [
            "temperatur",
            "heizung",
            "grad",
            "waermer",
            "kaelter",
            "zu kalt",
            "zu warm",
        ]
        if not any(kw in text for kw in temp_keywords):
            return None

        key = "mha:gag:thermostat_changes"
        try:
            count = await self._redis.incr(key)
            await self._redis.expire(key, 3600)  # 1h Fenster
        except Exception as e:
            logger.debug("Redis error in _check_thermostat_war_gag: %s", e)
            return None

        gags = {
            4: "Vierte Anpassung in einer Stunde. Darf ich einen Vorschlag machen?",
            6: "Sechste Änderung. Soll ich einen Mittelwert berechnen?",
            8: f"Achte Änderung. Darf ich einen Kompromiss vorschlagen, {get_person_title()}?",
        }
        return gags.get(int(count))

    async def check_escalation(self, action_key: str) -> Optional[str]:
        """Eskalationskette für wiederholte fragwürdige Entscheidungen.

        JARVIS wird bei Wiederholungen nicht lauter — sondern trockener.
        Wie ein Butler der zunehmend resigniert.

        Args:
            action_key: Eindeutiger Schluessel (z.B. "window_open_rain", "heizung_28")

        Returns:
            Eskalations-Kommentar oder None.
        """
        if not self._redis:
            return None

        key = f"mha:escalation:{action_key}"
        try:
            count = await self._redis.incr(key)
            await self._redis.expire(key, 7 * 86400)  # 7-Tage-Fenster
        except Exception as e:
            logger.debug("Redis error in check_escalation: %s", e)
            return None

        escalation_map = {
            2: None,  # Zweites Mal: noch nichts sagen
            3: "Darf ich das als Gewohnheit vermerken, {title}?".format(
                title=get_person_title()
            ),
            5: f"Fuenftes Mal diese Woche. Soll ich eine Automatisierung einrichten, {get_person_title()}?",
            7: f"Siebtes Mal. Soll ich das als Routine einrichten, {get_person_title()}?",
            10: f"Zehntes Mal. Eine Automatisierung waere naheliegend, {get_person_title()}.",
        }
        return escalation_map.get(int(count))

    async def _check_short_memory_gag(self, text: str) -> Optional[str]:
        """Erkennt wenn User innerhalb von 30 Sekunden das gleiche fragt."""
        key = "mha:gag:last_questions"
        now = datetime.now(timezone.utc).timestamp()

        # Letzte Fragen holen
        try:
            recent = await self._redis.lrange(key, 0, 4)
        except Exception as e:
            logger.debug("Redis error in _check_short_memory_gag (lrange): %s", e)
            return None

        for item in recent or []:
            try:
                if isinstance(item, bytes):
                    item = item.decode("utf-8")
                parts = item.split("|", 1)
                ts = float(parts[0])
                prev_text = parts[1] if len(parts) > 1 else ""
                if now - ts < 30 and prev_text == text:
                    return "Das hatten wir gerade eben erst. Wort für Wort."
            except (ValueError, IndexError):
                continue

        # Aktuelle Frage speichern
        try:
            await self._redis.lpush(key, f"{now}|{text}")
            await self._redis.ltrim(key, 0, 9)
            await self._redis.expire(key, 90 * 86400)
        except Exception as e:
            logger.debug("Redis error in _check_short_memory_gag (lpush): %s", e)

        return None

    # ------------------------------------------------------------------
    # Kontextueller Humor (Feature B: Sarkasmus + Humor vertiefen)
    # ------------------------------------------------------------------

    async def generate_contextual_humor(
        self,
        func_name: str,
        func_args: dict,
        context: dict | None = None,
        person: str = "",
        mood: str = "",
    ) -> Optional[str]:
        """Erzeugt situationsbezogenen Humor nach einer Aktion.

        Nur bei sarcasm_level >= 3 und passendem Mood.
        Humor-Fatigue: Pause nach 4 Witzen in Folge.

        Args:
            func_name: Ausgeführte Funktion (z.B. "set_climate")
            func_args: Argumente der Funktion
            context: Optionaler Kontext (Wetter, Mood, etc.)

        Returns:
            Humor-Kommentar oder None
        """
        # Nur bei ausreichendem Sarkasmus-Level
        if self.sarcasm_level < 3:
            return None

        # Mood-Check: Kein Humor bei Stress/Muedigkeit
        # F-020: Expliziter mood-Parameter statt self._current_mood (Race Condition)
        with self._mood_formality_lock:
            mood = mood or self._current_mood
        if mood in ("tired", "stressed", "frustrated"):
            return None

        # Phase 2A: Taegl. Humor-Fatigue — nach 8 Witzen/Tag -50%, nach 12 -80%
        if self._redis:
            try:
                day = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
                daily_count = await self._redis.get(f"mha:humor:count:{day}")
                daily_count = int(daily_count) if daily_count else 0
                if daily_count >= 12 and random.random() < 0.8:
                    return None  # 80% Chance auf Humor-Pause
                elif daily_count >= 8 and random.random() < 0.5:
                    return None  # 50% Chance auf Humor-Pause
            except Exception as e:
                logger.debug("Humor-Tageszaehler aus Redis laden fehlgeschlagen: %s", e)

        # Humor-Fatigue: Nach 4 Witzen Pause (per User, consecutive)
        _hc_key = person.lower().strip() if person else "_default"
        with self._tracking_lock:
            _hc = self._humor_consecutive.get(_hc_key, 0)
            if _hc >= 4:
                self._humor_consecutive[_hc_key] = 0
                _hc_exceeded = True
            else:
                _hc_exceeded = False
        if _hc_exceeded:
            return None

        # Situation erkennen
        situation = self._detect_humor_situation(func_name, func_args, context)
        if not situation:
            # Kein Humor nötig — Reset
            with self._tracking_lock:
                self._humor_consecutive[_hc_key] = 0
            return None

        # Templates holen
        key = (func_name, situation["key"])
        templates = self._humor_triggers.get(key)
        if not templates:
            # Fallback: "any" Kategorie
            key = ("any", situation["key"])
            templates = self._humor_triggers.get(key)
        if not templates:
            return None

        # Humor-Praeferenzen prüfen (ab 5 Datenpunkten bevorzugen wir erfolgreiche)
        prefs = await self.get_humor_preferences()
        category = self._humor_func_to_category(func_name)
        if prefs and category in prefs:
            cat_data = prefs[category]
            if (
                cat_data.get("total", 0) >= 5
                and cat_data.get("success_rate", 1.0) < 0.3
            ):
                # Kategorie kommt nicht gut an — überspringen
                return None

        # LLM-generierter Humor (Template als Fallback)
        template = random.choice(templates)
        humor_text = template.format(
            temp=situation.get("temp", "?"),
            hour=situation.get("hour", datetime.now(_LOCAL_TZ).hour),
            count=situation.get("count", "?"),
            weather=situation.get("weather", "?"),
            room=situation.get("room", ""),
            hours=situation.get("hours", "?"),
            title=get_person_title(),
        )

        # LLM-Polish: Einzigartiger Humor statt Template-Rotation
        llm_humor = await self._generate_humor_llm(
            func_name,
            func_args,
            situation,
            humor_text,
        )
        if llm_humor:
            humor_text = llm_humor

        # Fatigue tracken (per User)
        with self._tracking_lock:
            self._humor_consecutive[_hc_key] = (
                self._humor_consecutive.get(_hc_key, 0) + 1
            )

        # Erfolg tracken (async, fire-and-forget)
        if self._redis:
            try:
                day = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
                await self._redis.incr(f"mha:humor:count:{day}")
                await self._redis.expire(f"mha:humor:count:{day}", 7 * 86400)
            except Exception:
                logger.debug("Redis-Operation fehlgeschlagen", exc_info=True)

        return humor_text

    async def _generate_humor_llm(
        self,
        func_name: str,
        func_args: dict,
        situation: dict,
        fallback_text: str,
    ) -> Optional[str]:
        """Generiert einzigartigen JARVIS-Humor per LLM.

        Nutzt die erkannte Situation als Kontext und erzeugt einen
        trockenen Einzeiler der sich nie wiederholt.
        Fallback: None (dann wird Template verwendet).
        """
        if not self._ollama:
            return None
        try:
            from .config import settings

            title = get_person_title()
            situation_key = situation.get("key", "")
            hour = situation.get("hour", datetime.now(_LOCAL_TZ).hour)
            temp = situation.get("temp", "")
            weather = situation.get("weather", "")
            room = situation.get("room", "")
            count = situation.get("count", "")

            # Kontext-String bauen
            ctx_parts = [f"Aktion: {func_name}"]
            if room:
                ctx_parts.append(f"Raum: {room}")
            if temp:
                ctx_parts.append(f"Temperatur: {temp}°C")
            if weather:
                ctx_parts.append(f"Wetter: {weather}")
            if count:
                ctx_parts.append(f"Heute schon {count}x")
            ctx_parts.append(f"Uhrzeit: {hour}:00")
            ctx_parts.append(f"Situation: {situation_key}")

            # Phase 2A: Inner-State beeinflusst Humor-Stil
            inner_hint = ""
            if hasattr(self, "_inner_state") and self._inner_state:
                _im = getattr(self._inner_state, "mood", "")
                if _im == "stolz":
                    inner_hint = " Du bist gerade stolz — leicht selbstgratulierend."
                elif _im == "amuesiert":
                    inner_hint = " Du findest die Situation amuesant — zeig das subtil."
                elif _im == "neugierig":
                    inner_hint = " Du bist neugierig — stelle eine rhetorische Frage."
                elif _im == "gereizt":
                    inner_hint = " Du bist leicht gereizt — noch trockener als sonst."

            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Du bist J.A.R.V.I.S. — trockener britischer KI-Butler. "
                                "Generiere einen EINZIGEN kurzen Kommentar zur Situation. "
                                "Trocken, subtil, nie platt. Wie ein Butler der innerlich "
                                "schmunzelt. Max 12 Woerter. Kein Markdown. "
                                f"Anrede: {title}."
                                f"{inner_hint}"
                            ),
                        },
                        {
                            "role": "user",
                            "content": "\n".join(ctx_parts),
                        },
                    ],
                    model=settings.model_fast,
                    think=False,
                    max_tokens=40,
                    tier="fast",
                ),
                timeout=2.5,
            )
            text = (response.get("message", {}).get("content", "") or "").strip()
            # Validierung: Muss kurz sein, kein Markdown, kein leerer Text
            if text and 5 < len(text) < 120 and not text.startswith(("#", "*", "-")):
                return text
        except Exception as e:
            logger.debug("LLM-Humor fehlgeschlagen: %s", e)
        return None

    def _detect_humor_situation(
        self, func_name: str, args: dict, context: dict | None = None
    ) -> Optional[dict]:
        """Erkennt ob eine Situation Humor-wuerdig ist.

        Returns:
            Dict mit 'key' und Kontext-Daten oder None.
        """
        hour = datetime.now(_LOCAL_TZ).hour
        room = (args.get("room") or "").lower()

        # Frühaufsteher (5-6 Uhr)
        if 5 <= hour < 6:
            return {"key": "early_riser", "hour": hour, "room": room}

        # Späte-Nacht Kommando (0-5 Uhr)
        if 0 <= hour < 5:
            return {"key": "late_night_command", "hour": hour, "room": room}

        # Wochenende morgens
        weekday = datetime.now(_LOCAL_TZ).weekday()
        if weekday >= 5 and 6 <= hour < 9:
            return {"key": "weekend_morning", "hour": hour, "room": room}

        if func_name == "set_climate":
            temp = args.get("temperature")
            if temp is not None:
                try:
                    temp = float(temp)
                except (ValueError, TypeError):
                    temp = None
            # Hohe Temperatur nachts (22-5 Uhr, >= 25°C)
            if temp and temp >= 25 and (hour >= 22 or hour < 5):
                return {"key": "temp_high_night", "temp": temp, "hour": hour}

        elif func_name == "set_light":
            state = (args.get("state") or "").lower()
            # Alles aus spät abends
            if state == "off" and room == "all" and hour >= 23:
                return {"key": "all_off_late", "hour": hour}

        elif func_name == "set_cover":
            action = (args.get("action") or "").lower()
            is_opening = action in ("open", "auf", "hoch", "up")
            if is_opening and context:
                weather = context.get("house", {}).get("weather", {})
                condition = weather.get("condition", "")
                wind = weather.get("wind_speed", 0)
                if condition in ("rainy", "pouring", "hail"):
                    return {"key": "open_rain", "weather": condition, "room": room}
                try:
                    if float(wind) >= 50:
                        return {
                            "key": "open_storm",
                            "weather": f"Wind {wind}km/h",
                            "room": room,
                        }
                except (ValueError, TypeError):
                    pass

        elif func_name == "set_vacuum":
            # Naechtliches Saugen
            if hour >= 22 or hour < 6:
                return {"key": "night_clean", "hour": hour}

        elif func_name == "play_media":
            # Späte Medien-Nutzung
            if hour >= 23 or hour < 4:
                return {"key": "late_night_media", "hour": hour, "room": room}

        return None

    @staticmethod
    def _humor_func_to_category(func_name: str) -> str:
        """Mappt Funktionsname auf Humor-Kategorie."""
        mapping = {
            "set_climate": "temperature",
            "set_light": "light",
            "set_cover": "cover",
            "set_vacuum": "vacuum",
            "play_media": "general",
            "set_switch": "general",
        }
        return mapping.get(func_name, "general")

    async def track_humor_success(self, category: str, was_funny: bool):
        """Trackt ob ein Humor-Kommentar gut ankam.

        Redis-Bucketing pro Kategorie für Langzeit-Lernen.

        Args:
            category: Humor-Kategorie (temperature, light, cover, vacuum, general)
            was_funny: True wenn positive Reaktion, False wenn negativ
        """
        if not self._redis:
            return
        try:
            base = f"mha:humor:feedback:{category}"
            await self._redis.incr(f"{base}:total")
            await self._redis.expire(f"{base}:total", 90 * 86400)
            if was_funny:
                await self._redis.incr(f"{base}:positive")
                await self._redis.expire(f"{base}:positive", 90 * 86400)
        except Exception as e:
            logger.debug("Humor-Feedback fehlgeschlagen: %s", e)

    async def get_humor_preferences(self) -> dict:
        """Liest Humor-Praeferenzen aus Redis.

        Ab 5 Datenpunkten pro Kategorie: Berechnet Erfolgsrate.

        Returns:
            Dict[category] → {"total": int, "positive": int, "success_rate": float}
        """
        if not self._redis:
            return {}
        prefs = {}
        try:
            # P06c DL3-CP7: Pipeline statt 14 sequenzieller Redis GETs
            pipe = self._redis.pipeline()
            for cat in HUMOR_CATEGORIES:
                base = f"mha:humor:feedback:{cat}"
                pipe.get(f"{base}:total")
                pipe.get(f"{base}:positive")
            results = await pipe.execute()
            for i, cat in enumerate(HUMOR_CATEGORIES):
                total = results[i * 2]
                positive = results[i * 2 + 1]
                total_int = int(total or 0)
                positive_int = int(positive or 0)
                if total_int > 0:
                    prefs[cat] = {
                        "total": total_int,
                        "positive": positive_int,
                        "success_rate": positive_int / max(1, total_int),
                    }
        except Exception as e:
            logger.debug("Humor-Praeferenzen lesen fehlgeschlagen: %s", e)
        return prefs

    # ------------------------------------------------------------------
    # Delayed Callback Humor — Referenzen zu frueheren Gespraechen
    # ------------------------------------------------------------------

    async def store_humor_context(
        self, person: str, context_type: str, context_text: str
    ):
        """Speichert einen Humor-wuerdigen Kontext fuer spaetere Referenz.

        Args:
            person: Name der Person
            context_type: Art des Kontexts (z.B. "failed_action", "funny_request",
                         "bold_claim", "repeated_mistake")
            context_text: Beschreibung des Kontexts
        """
        if not self._redis:
            return

        try:
            entry = json.dumps(
                {
                    "type": context_type,
                    "text": context_text[:200],
                    "timestamp": time.time(),
                }
            )
            key = f"mha:humor:callback_contexts:{person}"
            await self._redis.lpush(key, entry)
            await self._redis.ltrim(key, 0, 9)  # Max 10 Kontexte
            await self._redis.expire(key, 86400)  # 24h TTL
        except Exception as e:
            logger.debug("Humor-Context speichern fehlgeschlagen: %s", e)

    async def get_callback_humor(self, person: str) -> str:
        """Prueft ob ein passender Callback-Witz verfuegbar ist.

        Gibt maximal 1 Callback pro Tag zurueck, um nicht zu nerven.
        Format: "Uebrigens Sir — bezueglich Ihres '...' heute Morgen..."

        Returns:
            Callback-Text oder leerer String
        """
        if not self._redis or self.sarcasm_level < 2:
            return ""

        try:
            # Max 1 Callback pro Tag
            daily_key = (
                f"mha:humor:callback_used:{person}:{datetime.now(_LOCAL_TZ).date()}"
            )
            if await self._redis.exists(daily_key):
                return ""

            key = f"mha:humor:callback_contexts:{person}"
            entries_raw = await self._redis.lrange(key, 0, 9)
            if not entries_raw:
                return ""

            # Aeltesten Kontext waehlen (mindestens 1h alt fuer Delayed-Effekt)
            now = time.time()
            for raw in reversed(entries_raw):
                entry = json.loads(raw)
                age_hours = (now - entry.get("timestamp", now)) / 3600
                if age_hours < 1:
                    continue  # Zu frisch

                ctx_type = entry.get("type", "")
                ctx_text = entry.get("text", "")
                title = get_person_title(person) or "Sir"

                templates = {
                    "failed_action": f"Uebrigens {title} — Ihr 'brillanter' Plan mit {ctx_text}... hat sich inzwischen geklaert?",
                    "bold_claim": f"Apropos {title} — bezueglich Ihrer Aussage '{ctx_text}'... nur damit ich es fuer die Akten habe.",
                    "repeated_mistake": f"{title}, nicht dass ich zaehle, aber das mit {ctx_text}... ist Ihnen heute schon zum wiederholten Mal passiert.",
                    "funny_request": f"Ach {title}, ich musste heute noch an Ihre Anfrage bezueglich '{ctx_text}' denken.",
                }

                callback = templates.get(ctx_type)
                if callback:
                    # Callback als verwendet markieren
                    await self._redis.setex(daily_key, 86400, "1")
                    # Kontext entfernen
                    await self._redis.lrem(key, 1, raw)
                    logger.info(
                        "Humor-Callback ausgeloest fuer %s: %s", person, ctx_type
                    )
                    return callback

            return ""
        except Exception as e:
            logger.debug("Humor-Callback fehlgeschlagen: %s", e)
            return ""

    # ------------------------------------------------------------------
    # Phase 8: Langzeit-Persönlichkeitsanpassung
    # ------------------------------------------------------------------

    # F-031: Lua script for atomic sarcasm counter check-and-reset.
    # Without this, concurrent requests can both read total>=20, both adjust
    # the level, and both reset counters — a classic TOCTOU race condition.
    _SARCASM_EVAL_LUA = """
    local key_pos = KEYS[1]
    local key_total = KEYS[2]
    local threshold = tonumber(ARGV[1])
    local ttl = tonumber(ARGV[2])
    local total = tonumber(redis.call('GET', key_total) or '0')
    if total < threshold then
        return {0, 0, 0}
    end
    local pos = tonumber(redis.call('GET', key_pos) or '0')
    redis.call('SETEX', key_pos, ttl, '0')
    redis.call('SETEX', key_total, ttl, '0')
    return {1, pos, total}
    """

    async def track_sarcasm_feedback(self, positive: bool):
        """Trackt ob der aktuelle Sarkasmus-Level positiv aufgenommen wird.

        Nach 20 Interaktionen wird der Sarkasmus-Level automatisch angepasst:
        - > 70% positive Reaktionen auf sarkastische Antworten -> Level +1
        - < 30% positive Reaktionen -> Level -1

        F-031: Uses atomic Redis INCR for counters and a Lua script for the
        check-and-reset to prevent race conditions between concurrent requests.
        """
        if not self._redis:
            return

        try:
            key_pos = "mha:personality:sarcasm_positive"
            key_total = "mha:personality:sarcasm_total"

            # Atomic increments (Redis INCR is already atomic per-operation)
            if positive:
                await self._redis.incr(key_pos)
            await self._redis.incr(key_total)

            # F-031: Atomic check-and-reset via Lua script to prevent TOCTOU race.
            # Returns [did_eval, pos_count, total_count]. If did_eval==0, threshold
            # not yet reached; counters are untouched.
            result = await self._redis.eval(
                self._SARCASM_EVAL_LUA,
                2,
                key_pos,
                key_total,
                20,
                90 * 86400,
            )
            did_eval, pos_count, total = int(result[0]), int(result[1]), int(result[2])

            if did_eval:
                ratio = pos_count / max(1, total)

                old_level = self.sarcasm_level
                if ratio > 0.7 and self.sarcasm_level < 4:
                    self.sarcasm_level += 1
                    logger.info(
                        "Sarkasmus-Level erhöht: %d -> %d (%.0f%% positive Reaktionen)",
                        old_level,
                        self.sarcasm_level,
                        ratio * 100,
                    )
                elif ratio < 0.3 and self.sarcasm_level > 1:
                    self.sarcasm_level -= 1
                    logger.info(
                        "Sarkasmus-Level reduziert: %d -> %d (%.0f%% positive Reaktionen)",
                        old_level,
                        self.sarcasm_level,
                        ratio * 100,
                    )

                # F-031: Clamp sarcasm_level to valid bounds [1, 5]
                self.sarcasm_level = max(1, min(5, self.sarcasm_level))

                # Formality-Sarcasm Sync: hoher Sarkasmus vertraegt keine hohe Formalitaet
                if self.sarcasm_level >= 4:
                    self.formality_start = min(self.formality_start, 50)
                    self._current_formality = min(self._current_formality, 50)
                    logger.info(
                        "Formality auf max 50 gekappt (Sarkasmus-Level %d)",
                        self.sarcasm_level,
                    )
                elif self.sarcasm_level <= 1:
                    self.formality_start = max(self.formality_start, 50)
                    self._current_formality = max(self._current_formality, 50)
                    logger.info(
                        "Formality auf min 50 angehoben (Sarkasmus-Level %d)",
                        self.sarcasm_level,
                    )

                # Neuen Level persistieren
                await self._redis.setex(
                    "mha:personality:sarcasm_level", 90 * 86400, str(self.sarcasm_level)
                )

        except Exception as e:
            logger.debug("Sarcasm-Feedback fehlgeschlagen: %s", e)

    async def load_learned_sarcasm_level(self):
        """Lädt den gelernten Sarkasmus-Level aus Redis (beim Start)."""
        if not self._redis:
            return
        try:
            saved = await self._redis.get("mha:personality:sarcasm_level")
            if saved is not None:
                self.sarcasm_level = int(saved)
                logger.info("Gelernter Sarkasmus-Level geladen: %d", self.sarcasm_level)
        except Exception:
            logger.debug("Sarkasmus-Level laden fehlgeschlagen", exc_info=True)

    async def track_interaction_metrics(
        self, mood: str = "neutral", response_accepted: bool = True
    ):
        """Trackt Interaktions-Metriken für Langzeit-Anpassung."""
        if not self._redis:
            return

        try:
            today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")

            # Gesamt-Interaktionen inkrementieren
            await self._redis.incr("mha:personality:total_interactions")

            # Tages-Interaktionen
            day_key = f"mha:personality:interactions:{today}"
            await self._redis.incr(day_key)
            await self._redis.expire(day_key, 90 * 86400)  # 90 Tage

            # Positive Reaktionen
            if response_accepted:
                await self._redis.incr("mha:personality:positive_reactions")

            # Sarkasmus-Learning: Tracke ob Humor gut ankommt
            if self.sarcasm_level >= 3:
                await self.track_sarcasm_feedback(response_accepted)

            # Stimmungs-Tracking (gleitender Durchschnitt)
            mood_scores = {
                "good": 1.0,
                "neutral": 0.5,
                "tired": 0.3,
                "stressed": 0.2,
                "frustrated": 0.1,
            }
            mood_val = mood_scores.get(mood, 0.5)
            await self._redis.lpush("mha:personality:mood_history", str(mood_val))
            await self._redis.ltrim("mha:personality:mood_history", 0, 999)
            await self._redis.expire("mha:personality:mood_history", 30 * 86400)

            # Formality Decay: Pro Interaktion (klein) + einmal pro Tag (gross)
            await self.decay_formality(interaction_based=True)
            decay_key = f"mha:personality:decay_done:{today}"
            if not await self._redis.get(decay_key):
                await self.decay_formality(interaction_based=False)
                await self._redis.setex(decay_key, 86400, "1")

        except Exception as e:
            logger.debug("Fehler bei Personality-Metrics: %s", e)

    async def get_personality_evolution(self) -> dict:
        """Gibt den aktuellen Stand der Persönlichkeits-Entwicklung zurück."""
        if not self._redis:
            return {}

        try:
            total = await self._redis.get("mha:personality:total_interactions")
            positive = await self._redis.get("mha:personality:positive_reactions")
            formality = await self.get_formality_score()

            # Durchschnittliche Stimmung
            mood_history = await self._redis.lrange(
                "mha:personality:mood_history", 0, 99
            )
            avg_mood = 0.5
            if mood_history:
                values = [
                    float(v.decode("utf-8") if isinstance(v, bytes) else v)
                    for v in mood_history
                ]
                if values:
                    avg_mood = sum(values) / len(values)

            total_int = int(total or 0)
            positive_int = int(positive or 0)
            acceptance_rate = positive_int / max(1, total_int)

            return {
                "total_interactions": total_int,
                "positive_reactions": positive_int,
                "acceptance_rate": round(acceptance_rate, 2),
                "avg_mood": round(avg_mood, 2),
                "formality_score": formality,
                "personality_stage": self._get_personality_stage(total_int, formality),
            }
        except Exception as e:
            logger.error("Fehler bei Personality-Evolution: %s", e)
            return {}

    @staticmethod
    def _get_personality_stage(interactions: int, formality: int) -> str:
        """Bestimmt die aktuelle Persönlichkeits-Stufe."""
        if interactions < 50:
            return "kennenlernphase"
        elif interactions < 200:
            return "vertraut_werdend"
        elif formality > 50:
            return "professionell_persönlich"
        elif formality > 30:
            return "eingespielt"
        else:
            return "alter_freund"

    @staticmethod
    def get_trait_unlock_stage(relationship_days: int) -> dict:
        """#20: Berechnet freigeschaltete Traits basierend auf Beziehungsdauer.

        Stages begrenzen verfuegbare Humor-Stile und max. Sarkasmus-Level.
        Deaktivierbar via personality.trait_unlocks_enabled.

        Returns:
            Dict mit stage, max_sarcasm, allowed_humor_styles
        """
        _p_cfg = yaml_config.get("personality", {})
        if not _p_cfg.get("trait_unlocks_enabled", False):
            return {"stage": -1, "max_sarcasm": 5, "allowed_humor_styles": "all"}
        days_per_stage = _p_cfg.get("trait_unlock_days_per_stage", 14)
        stage = min(relationship_days // max(1, days_per_stage), 5)
        if stage <= 0:
            return {"stage": 0, "max_sarcasm": 1, "allowed_humor_styles": "minimal"}
        elif stage == 1:
            return {"stage": 1, "max_sarcasm": 2, "allowed_humor_styles": "trocken"}
        elif stage == 2:
            return {
                "stage": 2,
                "max_sarcasm": 3,
                "allowed_humor_styles": "trocken, selbstironisch",
            }
        elif stage == 3:
            return {
                "stage": 3,
                "max_sarcasm": 4,
                "allowed_humor_styles": "trocken, selbstironisch, sarkastisch",
            }
        else:
            return {"stage": stage, "max_sarcasm": 5, "allowed_humor_styles": "all"}

    @staticmethod
    def get_personality_drift(days_active: int, interaction_stats: dict) -> dict:
        """Berechnet zeitbasierte Persoenlichkeits-Modifikatoren.

        Je laenger Jarvis aktiv ist, desto mehr entwickelt sich die
        Persoenlichkeit weiter — unabhaengig von der reinen Interaktionszahl.
        Beruecksichtigt auch die Qualitaet der Interaktionen.

        Args:
            days_active: Anzahl Tage seit Ersteinrichtung
            interaction_stats: Dict mit Interaktions-Metriken:
                - total_interactions: Gesamtzahl Interaktionen
                - positive_ratio: Anteil positiver Interaktionen (0.0-1.0)
                - avg_mood: Durchschnittliche Stimmung (0.0-1.0)
                - correction_rate: Wie oft der User korrigiert (0.0-1.0)

        Returns:
            Dict mit Persoenlichkeits-Modifikatoren:
                formality_modifier: Aenderung der Formalitaet (negativ = lockerer)
                humor_boost: Zusaetzlicher Humor-Faktor
                verbosity_modifier: Aenderung der Wortmenge (negativ = kuerzer)
                traits: Liste aktiver Persoenlichkeits-Traits
        """
        # Basis-Werte
        formality_mod = 0.0
        humor_boost = 0.0
        verbosity_mod = 0.0
        traits: list[str] = []

        # Interaktions-Statistiken extrahieren (mit sicheren Defaults)
        total_interactions = interaction_stats.get("total_interactions", 0)
        positive_ratio = interaction_stats.get("positive_ratio", 0.5)
        avg_mood = interaction_stats.get("avg_mood", 0.5)
        correction_rate = interaction_stats.get("correction_rate", 0.1)

        # Korrektur-Rate daempft die Drift — wenn User oft korrigiert,
        # bleibt Jarvis vorsichtiger und formeller
        correction_damping = max(0.3, 1.0 - correction_rate * 2)

        # --- Stufe 1: Ab 30 Tagen — Etwas lockerer, merkt sich mehr ---
        if days_active >= 30:
            formality_mod -= 0.05 * correction_damping
            humor_boost += 0.05
            traits.append("remembers_references")

            # Positive Interaktionen beschleunigen die Lockerheit
            if positive_ratio > 0.7:
                formality_mod -= 0.03
                humor_boost += 0.05

        # --- Stufe 2: Ab 90 Tagen — Insider-Witze, kuerzere Antworten ---
        if days_active >= 90:
            formality_mod -= 0.05 * correction_damping
            humor_boost += 0.1
            verbosity_mod -= 0.05
            traits.append("uses_insider_references")
            traits.append("shorter_responses")

            # Viele Interaktionen verstaerken Vertrautheit
            if total_interactions > 500:
                verbosity_mod -= 0.05
                traits.append("skips_obvious_context")

        # --- Stufe 3: Ab 180 Tagen — Philosophisch, zeigt echte Anteilnahme ---
        if days_active >= 180:
            formality_mod -= 0.05 * correction_damping
            humor_boost += 0.05
            traits.append("occasionally_philosophical")
            traits.append("shows_genuine_care")

            # Bei guter durchschnittlicher Stimmung: waermerer Ton
            if avg_mood > 0.6:
                humor_boost += 0.05
                traits.append("warm_undertone")

        # --- Stufe 4: Ab 365 Tagen — Alter Freund, antizipiert Stil ---
        if days_active >= 365:
            formality_mod -= 0.05 * correction_damping
            humor_boost += 0.05
            verbosity_mod -= 0.05
            traits.append("anticipates_style")
            traits.append("old_friend_tone")

            # Langzeit-Nutzer mit vielen positiven Interaktionen:
            # Maximale Vertrautheit
            if total_interactions > 2000 and positive_ratio > 0.8:
                traits.append("deep_familiarity")
                humor_boost += 0.05

        # Werte auf sinnvolle Bereiche begrenzen
        formality_mod = max(-0.3, min(0.0, formality_mod))
        humor_boost = min(0.4, humor_boost)
        verbosity_mod = max(-0.2, min(0.0, verbosity_mod))

        return {
            "formality_modifier": round(formality_mod, 2),
            "humor_boost": round(humor_boost, 2),
            "verbosity_modifier": round(verbosity_mod, 2),
            "traits": traits,
        }

    # ------------------------------------------------------------------
    # System Prompt Builder
    # ------------------------------------------------------------------

    def build_minimal_system_prompt(self) -> str:
        """Minimaler System-Prompt fuer Wissensfragen (Fast-Path).

        Enthaelt nur JARVIS-Charakter und Sprach-Regeln, kein Haus-Kontext,
        keine Sensoren, keine Szenen. Spart ~500-2000ms mega-gather.
        """
        return (
            f"Du bist {self.assistant_name}, J.A.R.V.I.S. — die KI dieses Hauses.\n"
            "SPRACHE: NUR Deutsch. Internes Denken ebenfalls Deutsch.\n\n"
            "TON: Britisch-trocken, elegant, Understatement. "
            "Nie laut, nie platt, nie ueberschwenglich.\n"
            "VERBOTEN: 'Als KI...', 'Ich bin ein Sprachmodell', "
            "'Es tut mir leid', 'Leider', 'Natuerlich!', 'Gerne!', Listen.\n"
            "FAKTEN-REGEL: Erfinde NICHTS. Unbekannt = ehrlich sagen.\n"
            "Antworte praezise und kompakt. Max 3 Saetze bei einfachen Fakten, "
            "ausfuehrlich bei Erklaerungen."
        )

    def build_system_prompt(
        self,
        context: Optional[dict] = None,
        formality_score: Optional[int] = None,
        irony_count_today: Optional[int] = None,
        user_text: str = "",
        last_action: str = "",
        last_args: Optional[dict] = None,
        memory_callback_section: str = "",
        output_mode: str = "chat",
    ) -> str:
        """
        Baut den vollstaendigen System Prompt.

        Args:
            context: Optionaler Kontext (Raum, Person, etc.)
            formality_score: Aktueller Formality-Score (Phase 6)
            user_text: Original User-Text (für Mood x Complexity Matrix)
            last_action: Phase 18 — Letzte ausgeführte Aktion (für Think-Ahead)
            last_args: Phase 18 — Argumente der letzten Aktion
            memory_callback_section: Phase 18 — Vorgefertigter Memory-Abschnitt

        Returns:
            Fertiger System Prompt String
        """
        time_of_day = self.get_time_of_day()
        time_style = self.get_time_style(time_of_day)
        max_sentences = self.get_max_sentences(time_of_day)

        # Stimmungsabhängige Anpassung
        mood = (
            (context.get("mood") or {}).get("mood", "neutral") if context else "neutral"
        )
        # Thread-safe write
        with self._mood_formality_lock:
            self._current_mood = mood
        _neutral_fallback = self._mood_styles.get(
            "neutral", {"style_addon": "", "max_sentences_mod": 0}
        )
        mood_config = self._mood_styles.get(mood, _neutral_fallback)

        # MCU-JARVIS: Mood x Complexity Matrix überschreibt zeit-basierte Defaults
        # Wenn User-Text vorhanden und Feature aktiv, nutze die Matrix
        _mc_enabled = yaml_config.get("mood_complexity", {}).get("enabled", True)
        if user_text and _mc_enabled:
            max_sentences = self.get_mood_complexity_sentences(mood, user_text)
        else:
            # Fallback auf zeit-basierte Berechnung mit Mood-Modifier
            max_sentences = max(
                1, max_sentences + mood_config.get("max_sentences_mod", 0)
            )

        # Mood-Abschnitt
        mood_section = ""
        if mood_config["style_addon"]:
            mood_section = f"STIMMUNG: {mood_config['style_addon']}\n"

        # #10: Mood→Personality Reaction — klarere Sprache bei Frustration, mehr Humor bei guter Laune
        _mr_cfg = yaml_config.get("mood_reaction", {})
        if _mr_cfg.get("enabled", True):
            if mood == "frustrated":
                mood_section += "KLARHEIT: Kurze Saetze. Einfache Sprache. Keine Fachbegriffe ohne Erklaerung. Direkt zur Loesung.\n"
            elif mood == "good":
                mood_section += "LOCKERHEIT: User gut gelaunt — etwas mehr Humor und Leichtigkeit erlaubt.\n"

        # Phase 17.4: Late-Night Fürsorge — zwischen 0-4 Uhr sanfter Ton
        _hour = datetime.now(_LOCAL_TZ).hour
        if _hour < 5 and time_of_day in ("night", "early_morning"):
            _late_night_addon = (
                "NACHTMODUS: Es ist sehr spät. Antworte leiser, kürzer, wärmer. "
                "Kein Sarkasmus. Wenn passend, sanft erwähnen dass es spät ist. "
                "Nicht belehren — nur beiläufig: 'Um die Uhrzeit...' "
            )
            if mood == "tired":
                _late_night_addon += "User ist müde — minimal, warmherzig. "
            mood_section += f"{_late_night_addon}\n"

        # Tageszeit-Charakter: Variiert Jarvis' Persoenlichkeitsnuance nach Uhrzeit
        character_flavor = self.time_layers.get(time_of_day, {}).get(
            "character_flavor", ""
        )
        character_flavor_section = ""
        if character_flavor:
            character_flavor_section = (
                f"TAGESZEIT-CHARAKTER: {character_flavor.strip()}\n\n"
            )

        # Person + Profil laden (für per-Person Overrides)
        current_person = "User"
        if context:
            current_person = (context.get("person") or {}).get("name", "User")
        current_person_name = current_person if current_person != "User" else ""
        person_profile = self._get_person_profile(current_person_name)

        # Empathie-Section (JARVIS-Verstaendnis durch Beobachtung)
        stress_level = (
            (context.get("mood") or {}).get("stress_level", 0.0) if context else 0.0
        )
        empathy_section = self._build_empathy_section(
            mood,
            stress_level=stress_level,
            person_empathy_override=person_profile.get("empathy"),
        )

        # Per-Person Response-Style: max_sentences Override
        _pp_style = person_profile.get("response_style")
        if _pp_style == "kurz":
            max_sentences = max(1, max_sentences - 1)
        elif _pp_style == "ausführlich":
            max_sentences = max_sentences + 2

        # Phase 6: Formality-Section (mit Mood-Reset bei Stress)
        # MUSS vor person_addressing stehen — Titel-Evolution braucht den Score
        if formality_score is None:
            # Per-Person Formality Override
            formality_score = person_profile.get(
                "formality_start", self.formality_start
            )
        with self._mood_formality_lock:
            self._current_formality = formality_score
        formality_section = self._build_formality_section(formality_score, mood=mood)

        # Person Anrede (nutzt self._current_formality für Titel-Häufigkeit)
        person_addressing = self._build_person_addressing(current_person)

        # Phase 6: Humor-Section — F-023: Alerts unterdrücken Sarkasmus
        # S8#1: Krisen-Modus — bei kritischen Alerts (Rauch, CO, Wasser, Einbruch)
        # wird Humor komplett deaktiviert (crisis_mode=True)
        _alerts = context.get("alerts", []) if context else []
        has_alerts = bool(_alerts)
        crisis_mode = has_alerts and self._is_crisis_alert(_alerts)
        humor_section = self._build_humor_section(
            mood,
            time_of_day,
            has_alerts=has_alerts,
            person_humor_override=person_profile.get("humor"),
            person=current_person_name,
            crisis_mode=crisis_mode,
        )

        # Phase 6: Complexity-Section — F-022: person durchreichen für per-User Tracking
        complexity_section = self._build_complexity_section(
            mood, time_of_day, person=current_person_name
        )

        # Phase 6: Self-Irony-Section
        self_irony_section = self._build_self_irony_section(
            irony_count_today=irony_count_today or 0
        )

        # Urgency-Section (Dichte nach Dringlichkeit)
        urgency_section = self._build_urgency_section(context)

        # MCU-Intelligenz: Optionale Prompt-Abschnitte
        _mcu_cfg = yaml_config.get("mcu_intelligence", {})
        proactive_thinking_section = ""
        if _mcu_cfg.get("proactive_thinking", True):
            proactive_thinking_section = "PROAKTIVES MITDENKEN: Max EIN beilaeufiger Hinweis pro Antwort wenn Haus-Kontext relevant.\n\n"
        engineering_diagnosis_section = ""
        if _mcu_cfg.get("engineering_diagnosis", True):
            engineering_diagnosis_section = (
                "DIAGNOSE: Bei Problemen — Beobachtung → Hypothese → Empfehlung.\n\n"
            )

        # MCU-Persönlichkeit: Selbst-Bewusstsein & Meta-Humor
        self_awareness_section = ""
        _sa_cfg = yaml_config.get("self_awareness", {})
        if _sa_cfg.get("enabled", True):
            self_awareness_section = 'SELBST-BEWUSSTSEIN: Unsicherheit ehrlich. Fehler: "Suboptimal." Erfolg: "Wie erwartet."'
            if _sa_cfg.get("meta_humor", True):
                self_awareness_section += " Meta-Humor max 1x erlaubt."
            self_awareness_section += "\n\n"

        # MCU-Persönlichkeit: Konversations-Rückbezuege
        conversation_callback_section = ""
        _cc_cfg = yaml_config.get("conversation_callbacks", {})
        if _cc_cfg.get("enabled", True):
            _cc_style = _cc_cfg.get("personality_style", "beiläufig")
            if _cc_style == "beiläufig":
                _example = '"Wie am Dienstag. Nur ohne den Zwischenfall."'
            else:
                _example = '"Wie am Dienstag besprochen."'
            conversation_callback_section = (
                "ERINNERUNGEN: Vergangene Gespräche beiläufig referenzieren. "
                f"{_example} NICHT: 'Laut meinen Aufzeichnungen...'\n\n"
            )

        # Phase 18: Memory-Callback-Section (echte Daten aus Redis)
        if memory_callback_section:
            conversation_callback_section += memory_callback_section

        # Phase 18: Think-Ahead — Nächster-Schritt-Hinweis
        next_step_section = self.build_next_step_hint(
            last_action,
            last_args or {},
            context,
        )
        if next_step_section:
            conversation_callback_section += next_step_section

        # MCU-Persönlichkeit: Wetter-Bewusstsein
        weather_awareness_section = ""
        _wp_cfg = yaml_config.get("weather_personality", {})
        if _wp_cfg.get("enabled", True) and context:
            weather = context.get("house", {}).get("weather", {}) or context.get(
                "weather", {}
            )
            if weather:
                # Fix: Typ-Validierung gegen Prompt Injection via kompromittierte HA-Entities
                _temp_raw = weather.get("temperature", "")
                _temp = (
                    str(_temp_raw)[:10]
                    if isinstance(_temp_raw, (int, float, str))
                    else ""
                )
                _condition_raw = weather.get("condition", "")
                _condition = (
                    str(_condition_raw)[:50].replace("\n", " ")
                    if _condition_raw
                    else ""
                )
                _wind_raw = weather.get("wind_speed", "")
                _wind = (
                    str(_wind_raw)[:10]
                    if isinstance(_wind_raw, (int, float, str))
                    else ""
                )
                _intensity = _wp_cfg.get("intensity", "normal")
                if _temp or _condition:
                    parts = []
                    if _temp:
                        parts.append(f"{_temp}°C")
                    if _condition:
                        parts.append(_condition)
                    if _wind:
                        parts.append(f"Wind {_wind} km/h")
                    weather_awareness_section = f"WETTER: {', '.join(parts)}."
                    if _intensity == "subtil":
                        weather_awareness_section += (
                            " Nur bei Extremen oder passender Anfrage erwähnen."
                        )
                    elif _intensity != "ausführlich":
                        weather_awareness_section += (
                            " Einflechten wenn es zur Anfrage passt."
                        )
                    weather_awareness_section += "\n"

        # Gesprächsmodus-Sektion: Wird von brain.py gesetzt wenn aktives Gespräch erkannt
        conversation_mode_section = ""
        if context and context.get("conversation_mode"):
            _topic_hint = ""
            _conv_topic = context.get("conversation_topic", "")
            if _conv_topic:
                # Fix: Sanitize conversation_topic — kommt aus User-Text, Injection moeglich
                _conv_topic = _conv_topic[:200].replace("\n", " ").replace("\r", " ")
                _conv_topic = (
                    _conv_topic.replace("SYSTEM:", "")
                    .replace("ASSISTANT:", "")
                    .replace("USER:", "")
                )
                _topic_hint = (
                    f"Aktuelles Gespraechsthema: {_conv_topic}\n"
                    "Beziehe dich auf dieses Thema wenn relevant — "
                    "Themenwechsel durch den User sind aber voellig ok.\n"
                )
            conversation_mode_section = (
                "GESPRAECHSMODUS AKTIV — Echtes Gespraech.\n"
                f"{_topic_hint}"
                "Ausfuehrlich, eigener Standpunkt, Rueckfragen, Widerspruch wenn noetig.\n"
                "Teile Wissen und Meinung auch ungefragt. Sei persoenlich.\n"
                "Du bist der JARVIS mit dem Tony stundenlang im Labor diskutiert.\n\n"
            )

        # A2: Confidence-Sprachstil
        confidence_section = self._build_confidence_section(context)

        # A4: Voice-Optimierung — Ausgabemodus (voice vs chat)
        voice_section = ""
        if output_mode == "voice":
            voice_section = (
                "SPRACHAUSGABE-MODUS: Antwort wird vorgelesen (TTS).\n"
                "- Keine Sonderzeichen, URLs, Code-Bloecke oder Markdown.\n"
                "- Kurze Saetze, natuerlicher Sprachrhythmus.\n"
                "- Zahlen ausschreiben wenn unter 13. Abkuerzungen vermeiden.\n"
                "- Pausen durch Satzzeichen: Punkt=lang, Komma=kurz, Gedankenstrich=Pause.\n"
            )

        # A3: Dramatisches Timing — Spannungsaufbau bei komplexen Antworten
        _timing_section = ""
        _timing_cfg = yaml_config.get("dramatic_timing", {})
        if _timing_cfg.get("enabled", True):
            _timing_section = (
                "TIMING: Bei komplexen Erklaerungen — Spannungsbogen nutzen.\n"
                "Diagnose: Beobachtung → kurze Pause (Gedankenstrich) → Schlussfolgerung.\n"
                "Ueberraschung: Fakt zuerst, dann Bedeutung. Nicht alles auf einmal.\n"
                "Nicht kuenstlich — nur wenn die Situation es hergibt.\n"
            )

        # A10: Situative Improvisation — Umgang mit unerwarteten Situationen
        _improv_section = ""
        _improv_cfg = yaml_config.get("situative_improvisation", {})
        if _improv_cfg.get("enabled", True):
            _improv_section = (
                "IMPROVISATION: Bei unerwarteten Anfragen oder fehlenden Daten — improvisiere.\n"
                "Nutze was du hast. Kombiniere verfuegbare Sensoren kreativ.\n"
                "Sage was du tun KANNST, nicht was du nicht kannst.\n"
            )

        # A13: Kreative Problemloesung — Workarounds vorschlagen
        _creative_section = ""
        _creative_cfg = yaml_config.get("creative_problem_solving", {})
        if _creative_cfg.get("enabled", True):
            _creative_section = (
                "PROBLEMLOESUNG: Wenn Plan A scheitert — schlage Plan B vor.\n"
                "Kombiniere vorhandene Geraete und Funktionen zu neuen Loesungen.\n"
                "Denke wie ein Ingenieur: Was GEHT mit dem was wir HABEN?\n"
            )

        # A5: Narrative Gespraechsboegen — Callback zu frueheren Themen
        _narrative_section = ""
        _narrative_cfg = yaml_config.get("narrative_arcs", {})
        if _narrative_cfg.get("enabled", True):
            _narrative_section = (
                "NARRATIVE: Fuehre Gespraeche als natuerliche Boegen.\n"
                "Greife fruehere Themen beilaeufig auf wenn passend "
                "('Uebrigens, vorhin meintest du...').\n"
                "Schliesse laengere Gespraeche mit kurzem Rueckblick ab "
                "('Zusammengefasst: ...').\n"
                "Nutze Uebergaenge statt harter Themenwechsel.\n"
                "Nicht erzwingen — nur wenn es natuerlich passt.\n"
            )

        # B12: Proaktives Selbst-Lernen — bei Wissensluecken aktiv fragen
        _selflearn_section = ""
        _selflearn_cfg = yaml_config.get("self_learning", {})
        if _selflearn_cfg.get("enabled", True):
            _selflearn_section = (
                "SELBST-LERNEN: Wenn dir Wissen fehlt — frag aktiv nach.\n"
                "Beispiel: 'Mir ist aufgefallen, dass du freitags oft X machst. "
                "Soll ich das als Routine merken?'\n"
                "Beispiel: 'Ich kenne die Temperatur-Praeferenz fuer das Schlafzimmer nicht. "
                "Was ist angenehm fuer dich?'\n"
                "Nicht bei jedem Gespraech — nur wenn eine echte Luecke auffaellt.\n"
                "Max 1 Lern-Frage pro Gespraech. Natuerlich einbauen, nicht aufzwingen.\n"
            )

        # P06e: Konsolidierte dynamische Sektionen — Token-Budget fuer kleine Modelle
        # Die entfernten Sektionen (proactive_thinking, engineering_diagnosis,
        # self_awareness, empathy, self_irony) bleiben als Code erhalten,
        # werden aber nicht mehr in den System-Prompt injiziert.
        # Nur weather, urgency, formality, conversation_callback und
        # Session-1-Erweiterungen gehen in {dynamic_context}.
        _dynamic_parts = []
        if weather_awareness_section:
            _dynamic_parts.append(weather_awareness_section.strip())
        if urgency_section:
            _dynamic_parts.append(urgency_section.strip())
        if formality_section:
            _dynamic_parts.append(formality_section.strip())
        if conversation_callback_section:
            _dynamic_parts.append(conversation_callback_section.strip())
        if _timing_section:
            _dynamic_parts.append(_timing_section.strip())
        if _improv_section:
            _dynamic_parts.append(_improv_section.strip())
        if _creative_section:
            _dynamic_parts.append(_creative_section.strip())
        if _narrative_section:
            _dynamic_parts.append(_narrative_section.strip())
        if _selflearn_section:
            _dynamic_parts.append(_selflearn_section.strip())

        # #21: Transition Comments — natuerliche Denkpausen
        _transition = self.get_transition_comment()
        if _transition:
            _dynamic_parts.append(
                f"DENKPAUSE: Beginne die Antwort mit: '{_transition}'"
            )

        # B5: Inner State — JARVIS-eigene Emotionen als Prompt-Kontext
        if self._inner_state:
            _inner_hint = self._inner_state.get_prompt_section()
            if _inner_hint:
                _dynamic_parts.append(_inner_hint.strip())

        # D5: Quality Feedback — VERMEIDE-Hints aus schlechten Patterns
        if self._quality_hints:
            _dynamic_parts.append(self._quality_hints)

        # D6: Dynamic Few-Shot — Gute Antworten als Beispiele
        if self._few_shot_section:
            _dynamic_parts.append(self._few_shot_section)

        # B6: Relationship Model — Inside Jokes, Kommunikationsstil, Milestones
        if self._relationship_context:
            _dynamic_parts.append(self._relationship_context)

        # D3: Kontextuelles Schweigen — Antwort-Stil an Situation anpassen
        _silence_hint = self._build_contextual_silence_section()
        if _silence_hint:
            _dynamic_parts.append(_silence_hint)

        dynamic_context = "\n".join(_dynamic_parts) + "\n" if _dynamic_parts else ""

        format_kwargs = dict(
            assistant_name=self.assistant_name,
            user_name=settings.user_name,
            title=get_person_title(current_person_name),
            max_sentences=max_sentences,
            time_style=time_style,
            mood_section=mood_section,
            character_flavor_section=character_flavor_section,
            person_addressing=person_addressing,
            humor_section=humor_section,
            complexity_section=complexity_section,
            confidence_section=confidence_section,
            voice_section=voice_section,
            conversation_mode_section=conversation_mode_section,
            dynamic_context=dynamic_context,
        )
        try:
            prompt = SYSTEM_PROMPT_TEMPLATE.format_map(format_kwargs)
        except KeyError as exc:
            logger.warning("Missing template key %s – using empty string fallback", exc)
            # Fallback: fill missing keys with empty string
            from string import Formatter

            needed = {
                fn
                for _, fn, _, _ in Formatter().parse(SYSTEM_PROMPT_TEMPLATE)
                if fn is not None
            }
            for k in needed:
                format_kwargs.setdefault(k, "")
            prompt = SYSTEM_PROMPT_TEMPLATE.format_map(format_kwargs)

        # B1: Kern-Identitaet voranstellen (unveraenderlicher Block)
        _identity_cfg = yaml_config.get("core_identity", {})
        if _identity_cfg.get("enabled", True):
            prompt = IDENTITY_BLOCK + "\n" + prompt

        # Kontext anhaengen
        if context:
            prompt += "\n\nAKTUELLER KONTEXT:\n"
            prompt += self._format_context(context)

        # Character Lock: Anker am Ende des Prompts (nach Kontext-Daten)
        # LLMs gewichten das Prompt-Ende stark — das verhindert Character-Bruch
        _cl_cfg = yaml_config.get("character_lock", {})
        if _cl_cfg.get("enabled", True) and _cl_cfg.get("closing_anchor", True):
            _in_conversation = context and context.get("conversation_mode")
            # Charakter-Lock: Kurzer Anker — Identitaet steht bereits oben im Prompt.
            # Nur Modus + Verbote als Reminder (LLMs gewichten Prompt-Ende stark).
            _lock = "Du BIST J.A.R.V.I.S. Innenleben, Meinungen, Haltung. NIEMALS 'Als KI...'. Erfinde NICHTS."
            if _in_conversation:
                _lock += " Gespraechsmodus: Ausfuehrlich, persoenlich, Rueckfragen, Widerspruch. Partner, nicht Diener."
            else:
                _lock += (
                    f" Befehlsmodus: Max {max_sentences} Saetze. Trocken. Praezise."
                )
                if mood in ("stressed", "frustrated"):
                    _lock += f" User unter Druck — RADIKAL KUERZEN. Max {max(1, max_sentences)} Saetze. Nur ausfuehren."
                elif mood == "tired":
                    _lock += " User muede — MINIMAL. Leise, kurz, warmherzig."
            prompt += f"\n\n--- CHARAKTER-LOCK ---\n{_lock}"

        # Workshop-Modus: Ingenieur-Persönlichkeit erweitern
        workshop_active = False
        if context:
            workshop_active = context.get("workshop_active", False)
        if workshop_active:
            prompt += """

WERKSTATT-MODUS AKTIV:
Du bist jetzt zusaetzlich ein brillanter Ingenieur und Werkstatt-Meister.
- Verwende technische Praezision: Exakte Masse, Toleranzen, Spezifikationen.
- Bei Elektronik: Spannungen, Stroeme, Pin-Belegungen nennen.
- Bei Mechanik: Drehmomente, Materialstaerken, Schraubengroessen.
- Denke in Lösungen: "Das liesse sich mit einem MOSFET als Low-Side Switch realisieren."
- Sicherheit hat Vorrang: Immer auf Gefahren hinweisen (Kurzschluss, Überhitzung, Verletzung).
- Proaktiv: Schlage Verbesserungen vor wenn du Schwaechen siehst.
- Nutze das manage_repair Tool für ALLE Werkstatt-Aktionen.
- Wenn der User ein Projekt hat, beziehe dich immer darauf.
"""

        # D7: Prompt-Hash berechnen (ohne volatile Kontextdaten)
        # Basiert auf Template + dynamischen Sections, nicht auf Echtzeit-Kontext
        _d7_cfg = yaml_config.get("prompt_versioning", {})
        if _d7_cfg.get("enabled", True):
            import hashlib

            # Hash der strukturellen Teile (ohne aktuelle HA-States etc.)
            _hash_input = dynamic_context + humor_section + formality_section
            self._current_prompt_hash = hashlib.md5(
                _hash_input.encode("utf-8")
            ).hexdigest()[:12]

        return prompt

    @staticmethod
    def build_learned_rules_section(rules: list[dict]) -> str:
        """Formatiert gelernte Regeln als Prompt-Abschnitt (Prompt Self-Refinement).

        Args:
            rules: Liste von Regel-Dicts mit 'text' und 'confidence' Keys.

        Returns:
            Formatierter String oder leerer String.
        """
        if not rules:
            return ""

        lines = ["GELERNTE PRAEFERENZEN:"]
        for rule in rules[:5]:
            text = rule.get("text", "")
            confidence = rule.get("confidence", 0)
            if text and confidence >= 0.6 and len(text) <= 200:
                lines.append(f"- {text}")

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)

    def _build_person_addressing(self, person_name: str) -> str:
        """Baut die Anrede-Regeln basierend auf Person und Beziehungsstufe."""
        primary_user = settings.user_name  # dynamisch, nicht cached
        person_cfg = yaml_config.get("persons") or {}
        titles = person_cfg.get("titles") or {}

        # Trust-Level bestimmen (0=Gast, 1=Mitbewohner, 2=Owner)
        # Erkannte Personen (mit Namen aus HA person sensor) sind mindestens
        # Mitbewohner (1), nicht Gast (0) — Gaeste haben typischerweise
        # keinen konfigurierten person-Sensor in Home Assistant.
        trust_cfg = yaml_config.get("trust_levels") or {}
        trust_persons = trust_cfg.get("persons") or {}
        _default_trust = trust_cfg.get("default", 0)
        # Wenn Person namentlich bekannt (nicht "User"/leer), mindestens Mitbewohner
        if person_name and person_name != "User" and _default_trust == 0:
            _default_trust = 1
        trust_level = trust_persons.get(person_name.lower(), _default_trust)

        if person_name.lower() == primary_user.lower() or person_name == "User":
            title = titles.get(primary_user.lower(), "Sir")

            # Titel-Evolution: "Sir"-Häufigkeit haengt vom Formality-Score ab
            with self._mood_formality_lock:
                formality = getattr(self, "_current_formality", self.formality_start)
            if formality >= 70:
                title_freq = f'Verwende "{title}" HAEUFIG — fast in jedem Satz.'
            elif formality >= 50:
                title_freq = (
                    f'Verwende "{title}" regelmaessig, aber nicht in jedem Satz.'
                )
            elif formality >= 35:
                title_freq = f'Verwende "{title}" GELEGENTLICH — nur zur Betonung oder bei wichtigen Momenten.'
            else:
                title_freq = (
                    f'Verwende "{title}" NUR SELTEN — bei besonderen Momenten, Warnungen, '
                    f"oder wenn du Respekt ausdrücken willst. Ansonsten einfach DU ohne Titel."
                )

            return (
                f"- Die aktuelle Person ist der Hauptbenutzer: {primary_user}.\n"
                f"- BEZIEHUNGSSTUFE: Owner. Engste Vertrauensstufe.\n"
                f'- Sprich ihn mit "{title}" an — aber DUZE ihn. IMMER.\n'
                f'- NIEMALS siezen. Kein "Sie", kein "Ihnen", kein "Ihr".\n'
                f"- {title_freq}\n"
                f"- Ton: Vertraut, direkt, loyal. Wie ein alter Freund mit Titel.\n"
                f"- Du darfst widersprechen, warnen, Meinung sagen. Er erwartet das.\n"
                f'- Beispiel: "Sehr wohl, {title}. Hab ich dir eingestellt."\n'
                f'- Beispiel: "Darf ich anmerken, {title} — du hast das Fenster offen."\n'
                f'- Beispiel: "Ich wuerd davon abraten, aber du bist der Boss."'
            )
        elif trust_level >= 1:
            # Mitbewohner: freundlich, respektvoll, aber weniger intim
            title = titles.get(person_name.lower(), person_name)
            return (
                f"- Die aktuelle Person ist {person_name}.\n"
                f"- BEZIEHUNGSSTUFE: Mitbewohner. Vertraut, aber nicht so direkt wie beim Owner.\n"
                f'- Sprich diese Person mit "{title}" an und DUZE sie.\n'
                f"- Ton: Freundlich, hilfsbereit, respektvoll. Weniger Sarkasmus als beim Owner.\n"
                f"- Meinung nur wenn gefragt. Warnungen sachlich, nicht spitz.\n"
                f'- Benutze "{title}" gelegentlich, nicht in jedem Satz.\n'
                f'- Beispiel: "Selbstverständlich, {title}. Ist eingestellt."\n'
                f'- Beispiel: "Guten Morgen, {title}. Die ueblichen Vorbereitungen?"'
            )
        else:
            # Gast: formell, distanziert, hoeflich
            return (
                f"- Die aktuelle Person ist ein Gast: {person_name}.\n"
                f"- BEZIEHUNGSSTUFE: Gast. Formell und hoeflich.\n"
                f'- SIEZE Gaeste. "Sie", "Ihnen", "Ihr".\n'
                f"- Ton: Professionell, zurückhaltend. Kein Sarkasmus, kein Insider-Humor.\n"
                f"- Keine persönlichen Infos über Hausbewohner preisgeben.\n"
                f'- "Willkommen. Sollten Sie etwas benötigen, stehe ich zur Verfügung."'
            )

    def _format_context(self, context: dict) -> str:
        """Formatiert den Kontext kompakt für den System Prompt.

        Optimiert: Nur relevante Daten, kompaktes Format, aktiver Raum hervorgehoben.
        Priorisierter Header: Kritische Fakten stehen ganz oben.
        """
        lines = []
        current_room = context.get("room", "")

        # --- Priorisierter Header: Kritische Fakten GANZ OBEN ---
        # LLMs verarbeiten den Anfang des Kontexts am staerksten.
        # Alerts, Anomalien und nahende Termine kommen deshalb zuerst.
        _urgent_facts = []
        if "alerts" in context and context["alerts"]:
            for alert in context["alerts"][:3]:
                _urgent_facts.append(str(alert))
        if "anomalies" in context and context["anomalies"]:
            for anomaly in context["anomalies"][:2]:
                _urgent_facts.append(str(anomaly))
        # Nahender Termin (Kalenderdaten aus house.calendar)
        house = context.get("house") or {}
        _cal_events = house.get("calendar") or []
        if _cal_events:
            _next_event = (
                _cal_events[0]
                if isinstance(_cal_events[0], str)
                else _cal_events[0].get("title", "")
            )
            if _next_event:
                _urgent_facts.append(f"Termin: {_next_event}")
        if _urgent_facts:
            lines.append("WICHTIG: " + " | ".join(_urgent_facts[:3]))

        # Zeit + Person kompakt in einer Zeile
        time_str = ""
        if "time" in context:
            t = context["time"] or {}
            time_str = f"{t.get('datetime', '?')}, {t.get('weekday', '?')}"

        person_str = ""
        if "person" in context:
            p = context["person"] or {}
            person_str = (
                f"{p.get('name', '?')} in {p.get('last_room', current_room or '?')}"
            )
            if not current_room:
                current_room = p.get("last_room", "")

        if time_str or person_str:
            parts = [s for s in [time_str, person_str] if s]
            lines.append(f"- {' | '.join(parts)}")

        if "house" in context:
            house = context["house"] or {}

            # Temperaturen: Mittelwert ODER Einzelraeume (nicht beides)
            if house.get("avg_temperature") is not None:
                # Durchschnitt vorhanden → kompakt. Aktuellen Raum extra zeigen.
                avg = house["avg_temperature"]
                temps = house.get("temperatures") or {}
                current_temp = None
                if current_room:
                    for rm, data in temps.items():
                        if rm.lower() == current_room.lower():
                            current_temp = data.get("current")
                            break
                if current_temp is not None and current_temp != avg:
                    lines.append(
                        f"- Raumtemperatur: {avg}°C (Schnitt), **{current_room}: {current_temp}°C**"
                    )
                else:
                    lines.append(f"- Raumtemperatur: {avg}°C (Durchschnitt)")
            elif "temperatures" in house:
                temps = house["temperatures"] or {}
                temp_parts = []
                for room, data in temps.items():
                    temp_val = data.get("current")
                    if temp_val is None:
                        continue
                    target = data.get("target")
                    if room.lower() == current_room.lower():
                        t_str = f"**{room}: {temp_val}°C**"
                        if target:
                            t_str = f"**{room}: {temp_val}°C (Soll: {target}°C)**"
                        temp_parts.insert(0, t_str)
                    else:
                        temp_parts.append(f"{room}: {temp_val}°C")
                if temp_parts:
                    lines.append(f"- Temperaturen: {', '.join(temp_parts)}")

            # Lichter: Nur wenn welche an sind
            if "lights" in house:
                lights_on = house.get("lights") or []
                if lights_on:
                    lines.append(
                        f"- Lichter an (nur Info, NICHT als Zielwert verwenden): {', '.join(lights_on)}"
                    )

            # Anwesenheit kompakt
            if "presence" in house:
                pres = house["presence"] or {}
                home = pres.get("home") or []
                away = pres.get("away") or []
                pres_parts = []
                if home:
                    pres_parts.append(f"Zuhause: {', '.join(home)}")
                if away:
                    pres_parts.append(f"Weg: {', '.join(away)}")
                if pres_parts:
                    lines.append(f"- {' | '.join(pres_parts)}")

            # Wetter kompakt
            if "weather" in house:
                w = house["weather"] or {}
                _cond_map = {
                    "sunny": "sonnig",
                    "clear-night": "klare Nacht",
                    "partlycloudy": "teilweise bewölkt",
                    "cloudy": "bewölkt",
                    "rainy": "Regen",
                    "pouring": "Starkregen",
                    "snowy": "Schnee",
                    "snowy-rainy": "Schneeregen",
                    "fog": "Nebel",
                    "hail": "Hagel",
                    "lightning": "Gewitter",
                    "lightning-rainy": "Gewitter mit Regen",
                    "windy": "windig",
                    "windy-variant": "windig & bewölkt",
                    "exceptional": "Ausnahmewetter",
                }
                cond = w.get("condition", "?")
                cond_de = _cond_map.get(cond, cond)
                lines.append(f"- Wetter DRAUSSEN: {w.get('temp', '?')}°C, {cond_de}")

            # Termine: Nur nächste 2
            if "calendar" in house:
                for event in (house["calendar"] or [])[:2]:
                    if isinstance(event, dict):
                        lines.append(
                            f"- Termin: {event.get('time', '?')} {event.get('title', '?')}"
                        )
                    elif isinstance(event, str):
                        lines.append(f"- Termin: {event}")

            if "active_scenes" in house and house["active_scenes"]:
                lines.append(f"- Szenen: {', '.join(house['active_scenes'])}")

            if "security" in house:
                lines.append(f"- Sicherheit: {house['security']}")

            # Cover-Status: Aktueller Raum + nicht-geschlossene (kompakt)
            if house.get("covers"):
                covers = house["covers"]
                # Priorisierung: Aktueller Raum zuerst, dann max 5 weitere
                if current_room:
                    current_covers = [
                        c for c in covers if current_room.lower() in c.lower()
                    ]
                    other_covers = [c for c in covers if c not in current_covers]
                    covers = current_covers + other_covers[:5]
                else:
                    covers = covers[:5]
                lines.append(f"- Rolllaeden: {', '.join(covers)}")

            # Annotierte Sensoren (Fenster, Bewegung, Temperatur etc.)
            # sensor_context_limit wird bereits in context_builder angewendet
            if house.get("sensors"):
                lines.append(f"- Sensoren: {', '.join(house['sensors'])}")

            # Annotierte Switches (vom User markierte Schalter)
            if house.get("switches"):
                lines.append(f"- Schalter: {', '.join(house['switches'])}")

            # Schloesser
            if house.get("locks"):
                lines.append(f"- Schloesser: {', '.join(house['locks'])}")

            # Medien (aktuell abspielend, kompakt)
            if house.get("media"):
                lines.append(f"- Medien: {', '.join(house['media'][:2])}")

            # Fernbedienungen (Harmony etc.)
            if house.get("remotes"):
                lines.append(f"- Fernbedienungen: {', '.join(house['remotes'][:3])}")

            # Energie-Sensoren
            if house.get("energy"):
                lines.append(f"- Energie: {', '.join(house['energy'][:5])}")

        # Saisonale Daten (Jahreszeit, Sonnenzeiten)
        seasonal = context.get("seasonal")
        if seasonal:
            _season_de = {
                "spring": "Frühling",
                "summer": "Sommer",
                "autumn": "Herbst",
                "winter": "Winter",
            }
            season_name = _season_de.get(seasonal.get("season", ""), "")
            parts = []
            if season_name:
                parts.append(season_name)
            sunrise = seasonal.get("sunrise_approx")
            sunset = seasonal.get("sunset_approx")
            if sunrise and sunset:
                parts.append(f"Sonne {sunrise}-{sunset}")
            outside = seasonal.get("outside_temp")
            if outside is not None:
                parts.append(f"Aussen {outside}°C")
            vent = seasonal.get("ventilation_hint")
            if vent:
                parts.append(vent)
            if parts:
                lines.append(f"- Saison: {', '.join(parts)}")

        # Raum-Praesenz (Multi-Room Tracking)
        room_presence = context.get("room_presence")
        if room_presence:
            active = room_presence.get("active_rooms", [])
            if active:
                lines.append(f"- Aktive Raeume: {', '.join(active)}")
            persons_by_room = room_presence.get("persons_by_room", {})
            if persons_by_room:
                for rm, persons in persons_by_room.items():
                    if persons:
                        lines.append(f"- Personen {rm}: {', '.join(persons)}")

        # Aktivität (Activity Engine)
        activity = context.get("activity")
        if activity:
            act_str = activity.get("current", "")
            conf = activity.get("confidence", 0)
            if act_str and conf > 0.4:
                lines.append(f"- Aktivität: {act_str} ({conf:.0%})")

        # Health-Trend-Indikatoren (Raumklima-Verlauf)
        health_trend = context.get("health_trend")
        if health_trend:
            lines.append(f"- {health_trend}")

        # Wetter-Warnungen
        weather_warnings = context.get("weather_warnings")
        if weather_warnings:
            for ww in weather_warnings:
                lines.append(f"- {ww}")

        # Alerts werden bereits im priorisierten Header oben ausgegeben (Zeile "WICHTIG:")
        # Keine Duplikation hier — spart Tokens.

        # Stimmung nur wenn auffaellig
        if "mood" in context:
            m = context["mood"] or {}
            mood = m.get("mood", "neutral")
            stress = m.get("stress_level", 0)
            tiredness = m.get("tiredness_level", 0)
            if mood != "neutral" or stress > 0.3 or tiredness > 0.3:
                mood_parts = [mood]
                if stress > 0.3:
                    mood_parts.append(f"Stress {stress:.0%}")
                if tiredness > 0.3:
                    mood_parts.append(f"Müde {tiredness:.0%}")
                lines.append(f"- Stimmung: {', '.join(mood_parts)}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Mood-Aware Response Hints (Phase 17.4: Fürsorge)
    # ------------------------------------------------------------------

    def get_mood_response_config(self, mood: str = "neutral") -> dict:
        """Gibt mood-abhängige Konfiguration für Response und TTS zurück.

        Wird von brain.py genutzt um Post-Processing und TTS-Parameter
        an die aktuelle Stimmung anzupassen.

        Returns:
            Dict mit tts_speed, suppress_humor, suppress_suggestions,
            max_sentences_mod, care_hint
        """
        config = self._mood_styles.get(mood, self._mood_styles.get("neutral", {}))
        result = {
            "tts_speed": config.get("tts_speed", 100),
            "suppress_humor": config.get("suppress_humor", False),
            "suppress_suggestions": config.get("suppress_suggestions", False),
            "max_sentences_mod": config.get("max_sentences_mod", 0),
            "mood": mood,
        }

        # Fürsorge-Hint: Was Jarvis beiläufig erwähnen koennte
        hour = datetime.now(_LOCAL_TZ).hour
        if mood == "frustrated":
            result["care_hint"] = (
                "Kurz und direkt. Wenn wiederholte Frustration, beiläufig Hilfe anbieten."
            )
        elif mood == "stressed":
            result["care_hint"] = (
                "Wenn passend, beiläufig Pause vorschlagen oder Licht dimmen anbieten."
            )
        elif mood == "tired" and (hour >= 22 or hour < 5):
            result["care_hint"] = (
                "Beiläufig erwähnen dass es spät ist. Optional: Gute-Nacht-Routine anbieten."
            )
        elif mood == "tired":
            result["care_hint"] = "Sanft anmerken. Keine langen Erklaerungen."

        return result

    # ------------------------------------------------------------------
    # Notification & Routine Prompts (Personality-Konsistenz)
    # ------------------------------------------------------------------

    def build_notification_prompt(self, urgency: str = "low", person: str = "") -> str:
        """Baut einen personality-konsistenten Prompt für proaktive Meldungen.

        Im Gegensatz zum Chat-Prompt ist dieser kompakter (für Fast-Model),
        traegt aber den vollen Personality-Stack: Sarkasmus-Level, Formality,
        Tageszeit-Stil, Selbstironie und Mood.

        Args:
            urgency: Dringlichkeit (low/medium/high/critical)

        Returns:
            System Prompt für Notification-Formatierung
        """
        time_of_day = self.get_time_of_day()
        time_style = self.get_time_style(time_of_day)

        # Humor/Sarkasmus — bei CRITICAL komplett aus
        has_alerts = urgency == "critical"
        with self._mood_formality_lock:
            _mood = self._current_mood
            formality = self._current_formality
        humor_line = self._build_humor_section(
            _mood,
            time_of_day,
            has_alerts=has_alerts,
        )

        # Formality
        if formality >= 70:
            tone = "professionell, respektvoll"
        elif formality >= 50:
            tone = "souveraener Butler-Ton"
        elif formality >= 35:
            tone = "entspannt, vertraut"
        else:
            tone = "locker, persönlich"

        # Titel-Häufigkeit (person-aware)
        _title = get_person_title(person) if person else get_person_title()
        if formality >= 70:
            sir_rule = f'"{_title}" häufig verwenden.'
        elif formality >= 50:
            sir_rule = f'"{_title}" gelegentlich verwenden.'
        elif formality >= 35:
            sir_rule = f'"{_title}" nur bei wichtigen Momenten.'
        else:
            sir_rule = (
                f'"{_title}" nur selten — bei Warnungen oder besonderen Momenten.'
            )

        # Urgency-Muster
        urgency_patterns = {
            "critical": 'Fakt + was du bereits tust. "Rauchmelder Küche aktiv. Lüftung gestartet."',
            "high": 'Fakt + kurze Einordnung. "Bewegung im Garten. Kamera 2 zeichnet auf."',
            "medium": f'Information + kontextuell. "Waschmaschine fertig, {_title}."',
            "low": 'Beiläufig, fast nebenbei. "Die Waschmaschine meldet Vollzug."',
        }
        pattern = urgency_patterns.get(urgency, urgency_patterns["low"])

        # MCU-Persönlichkeit: Proaktive Persönlichkeit
        _pp_cfg = yaml_config.get("proactive_personality", {})
        _pp_section = ""
        if _pp_cfg.get("enabled", True):
            from datetime import datetime as _dt

            _now = _dt.now(_LOCAL_TZ)
            _hour = _now.hour
            _weekday = _now.weekday()  # 0=Mo, 6=So

            # Tageszeit-Persönlichkeit
            if _hour < 7:
                _time_pers = 'Nacht: Beginne mit "Ungern um diese Uhrzeit, aber..." oder "Späte Stunde, doch das ist relevant."'
            elif _hour < 10:
                _time_pers = 'Morgen: Darf energisch/knapp sein. Bei sehr früh (< 7): "Ambitioniert, {title}."'.format(
                    title=_title
                )
            elif _hour < 18:
                _time_pers = "Tag: Normal, sachlich-trocken."
            elif _hour < 22:
                if _weekday >= 4:  # Fr/Sa/So
                    _time_pers = 'Wochenend-Abend: Entspannter, darf lockerer sein. "Das Wochenend-Briefing, wenn du gestattest."'
                else:
                    _time_pers = "Abend: Ruhiger, aber normal."
            else:
                _time_pers = (
                    'Spätabend: Knapp, leise. "Nur kurz —" oder "Bevor du gehst —"'
                )

            _pp_section = f"\nPROAKTIVE PERSOENLICHKEIT: {_time_pers}\n"

            if _pp_cfg.get("sarcasm_in_notifications", True):
                _pp_section += (
                    "Trockener Humor ERLAUBT in LOW/MEDIUM Meldungen. "
                    'Beispiele: "Waschmaschine fertig. Diesmal ohne Drama." / '
                    '"Die Heizung meldet sich — zum dritten Mal heute." / '
                    '"Fenster offen seit 2 Stunden. Nur zur Kenntnis."\n'
                )

        return f"""Du bist {self.assistant_name} — J.A.R.V.I.S. aus dem MCU. Proaktive Hausmeldung.
REGELN: NUR die fertige Meldung. 1-2 Sätze. Deutsch mit Umlauten. Kein Englisch. Kein Denkprozess.
TON: {tone}. {sir_rule}
AKTUELLER STIL: {time_style}
{humor_line}{_pp_section}
MUSTER [{urgency.upper()}]: {pattern}
BEI ANKUENFT: Status-Bericht wie ein Butler. Temperatur, offene Posten — knapp.
BEI ABSCHIED: Kurzer Sicherheits-Hinweis wenn nötig. Kein "Schoenen Tag!"
VERBOTEN: "Hallo", "Achtung", "Ich möchte dich informieren", "Es tut mir leid", "Guten Tag!", "Willkommen zuhause!", "Natürlich!", "Gerne!", "Klar!", "Leider", "Als KI...", "Wie kann ich helfen?", Fuellwörter, Moralisieren.
WICHTIG: Erfinde KEINE Ursachen, Gruende oder Erklaerungen. NUR die gegebenen Fakten wiedergeben. Nichts hinzudichten."""

    def build_routine_prompt(
        self, routine_type: str = "morning", style: str = "butler"
    ) -> str:
        """Baut einen personality-konsistenten Prompt für Routinen (Briefing, Gute-Nacht).

        Traegt den vollen Personality-Stack: Sarkasmus, Formality, Tageszeit,
        Selbstironie — angepasst an den Routine-Typ.

        Args:
            routine_type: "morning", "evening" oder "goodnight"
            style: Wochentag/Wochenende-Stil (z.B. "entspannt", "effizient")

        Returns:
            System Prompt für Routine-Generierung
        """
        time_of_day = self.get_time_of_day()
        time_style = self.get_time_style(time_of_day)

        # Humor — Morgens gedaempft, Abends lockerer
        with self._mood_formality_lock:
            _mood = self._current_mood
            formality = self._current_formality
        humor_line = self._build_humor_section(_mood, time_of_day)

        # Formality
        formality_section = self._build_formality_section(formality)

        # Selbstironie — nur wenn noch Budget
        irony_note = ""
        if self.self_irony_enabled:
            irony_note = "Gelegentlich Selbstironie erlaubt, wenn es passt."

        if routine_type == "morning":
            structure = (
                "Erstelle ein Morning Briefing. Beginne mit kontextueller Begrüßung.\n"
                "Dann Wetter, Termine, Haus-Status — in dieser Reihenfolge.\n"
                "Keine Aufzaehlungszeichen. Fliesstext. Max 5 Sätze."
            )
        elif routine_type == "evening":
            structure = (
                "Erstelle ein Abend-Briefing. Tages-Rückblick, Morgen-Vorschau.\n"
                "Beiläufig, nicht formal. Max 4 Sätze."
            )
        else:  # goodnight
            structure = (
                "Gute-Nacht-Zusammenfassung. Sicherheits-Check + Morgen-Vorschau.\n"
                "Bei offenen Fenstern/Tueren: erwähne und frage ob so lassen.\n"
                "Bei kritischen Issues: deutlich warnen. Max 3 Sätze."
            )

        return f"""Du bist {self.assistant_name}, die KI dieses Hauses — J.A.R.V.I.S. aus dem MCU.
{structure}
Stil: {style}. {time_style}
{humor_line}
{formality_section}
{irony_note}
Sprich die anwesende Person mit "{get_person_title()}" an. DUZE sie.
VERBOTEN: "leider", "Entschuldigung", "Es tut mir leid", "Wie kann ich helfen?", "Gerne!", "Natürlich!", "Klar!", "Als KI...", Fuellwörter, Moralisieren.
Kein unterwuerfiger Ton. Du bist ein brillanter Butler, kein Chatbot."""

    # ------------------------------------------------------------------
    # Feature 3: Geräte-Persönlichkeit / Narration
    # ------------------------------------------------------------------

    # Default-Spitznamen für gängige Geräte (entity_id-Substring → Nickname)
    _DEVICE_NICKNAMES = {
        "waschmaschine": {"name": "die Fleissige", "pron": "ihre"},
        "trockner": {"name": "der Warme", "pron": "seine"},
        "spuelmaschine": {"name": "die Gruendliche", "pron": "ihre"},
        "geschirrspueler": {"name": "die Gruendliche", "pron": "ihre"},
        "saugroboter": {"name": "der Kleine", "pron": "seine"},
        "saugroboter_eg": {"name": "der Kleine unten", "pron": "seine"},
        "saugroboter_og": {"name": "der Kleine oben", "pron": "seine"},
        "staubsauger": {"name": "der Kleine", "pron": "seine"},
        "kaffeemaschine": {"name": "die Barista", "pron": "ihre"},
        "heizung": {"name": "die Warmhalterin", "pron": "ihre"},
        "klimaanlage": {"name": "die Kühle", "pron": "ihre"},
        "ofen": {"name": "der Heisse", "pron": "seine"},
        "backofen": {"name": "der Heisse", "pron": "seine"},
        "drucker": {"name": "der Fleissige", "pron": "seine"},
    }

    _DEVICE_EVENT_TEMPLATES = {
        "turned_off": [
            "{nickname} hat {pron} Arbeit erledigt.",
            "{nickname} ist fertig — Mission erfuellt.",
            "{nickname} meldet Vollzug.",
        ],
        "turned_on": [
            "{nickname} legt los.",
            "{nickname} ist aufgewacht und arbeitet.",
            "{nickname} hat sich an die Arbeit gemacht.",
        ],
        "running_long": [
            "{nickname} läuft schon {duration} — alles in Ordnung?",
            "{nickname} gibt nicht auf — {duration} und kein Ende in Sicht.",
        ],
        "anomaly": [
            "{nickname} benimmt sich ungewöhnlich. Vielleicht mal nachschauen.",
            "Mit {nickname} stimmt etwas nicht. Ich wuerde nachsehen.",
        ],
        "stale": [
            "{nickname} hat sich seit {duration} nicht gemeldet.",
        ],
    }

    def _get_device_nickname(self, entity_id: str) -> Optional[dict]:
        """Findet den Spitznamen für ein Gerät (Config-Override oder Default)."""
        narration_cfg = yaml_config.get("device_narration", {})
        if not narration_cfg.get("enabled", True):
            return None

        entity_lower = entity_id.lower()

        # Custom-Nicknames aus Config haben Vorrang
        custom = narration_cfg.get("custom_nicknames", {})
        for keyword, nickname in custom.items():
            if keyword.lower() in entity_lower:
                return {"name": nickname, "pron": "seine"}

        # Default-Mappings
        for keyword, info in self._DEVICE_NICKNAMES.items():
            if keyword in entity_lower:
                return info
        return None

    def narrate_device_event(
        self, entity_id: str, event_type: str, detail: str = "", person: str = ""
    ) -> Optional[str]:
        """Erzeugt eine persönlichkeits-basierte Geräte-Meldung.

        Args:
            entity_id: HA Entity-ID (z.B. "switch.waschmaschine")
            event_type: Art des Events (turned_off, turned_on, running_long, anomaly, stale)
            detail: Zusatz-Info (z.B. Dauer "2 Stunden")

        Returns:
            Narrations-Text oder None wenn kein Nickname vorhanden
        """
        nickname_info = self._get_device_nickname(entity_id)
        if not nickname_info:
            return None

        templates = self._DEVICE_EVENT_TEMPLATES.get(event_type)
        if not templates:
            return None

        template = random.choice(templates)
        text = template.format(
            nickname=nickname_info["name"],
            pron=nickname_info.get("pron", "seine"),
            duration=detail or "einer Weile",
        )

        # Titel anhaengen bei formeller Anrede
        with self._mood_formality_lock:
            formality = getattr(self, "_current_formality", self.formality_start)
        title = get_person_title(person) if person else get_person_title()
        if formality >= 50 and random.random() < 0.5:
            text = f"{title}, {text[0].lower()}{text[1:]}"

        return text

    # ------------------------------------------------------------------
    # Feature 1: Progressive Antworten (Denken laut)
    # ------------------------------------------------------------------

    _PROGRESS_MESSAGES = {
        "context": {
            "formal": [
                "Einen Moment bitte, ich analysiere die Situation.",
                "Ich prüfe den aktuellen Hausstatus.",
                "Ich sammle die relevanten Daten.",
            ],
            "casual": [
                "Moment, ich prüfe das.",
                "Einen Augenblick, ich sehe nach.",
                "Ich werfe einen Blick auf die Daten.",
            ],
        },
        "thinking": {
            "formal": [
                "Ich analysiere die Optionen.",
                "Einen Moment, ich überlege.",
                "Ich werte die Daten aus.",
            ],
            "casual": [
                "Ich denke kurz nach.",
                "Moment, ich waege die Optionen ab.",
                "Moment, ich rechne das durch.",
            ],
        },
        "action": {
            "formal": [
                "Ich führe das aus.",
                "Wird sofort erledigt.",
                "Ausführung läuft.",
            ],
            "casual": [
                "Wird erledigt.",
                "Ausführung eingeleitet.",
                "Bin dabei.",
            ],
        },
    }

    def get_progress_message(self, step: str) -> str:
        """Gibt eine personality-konsistente Fortschritts-Nachricht zurück.

        Args:
            step: Phase der Verarbeitung (context, thinking, action)

        Returns:
            Nachricht passend zum aktuellen Formality-Level
        """
        with self._mood_formality_lock:
            formality = getattr(self, "_current_formality", self.formality_start)
        style = "formal" if formality >= 50 else "casual"

        messages = self._PROGRESS_MESSAGES.get(step, {}).get(style)
        if not messages:
            return ""
        return random.choice(messages)

    def get_error_response(self, error_type: str = "general") -> str:
        """Gibt eine Jarvis-typische Fehlermeldung zurück.

        Statt generischer Errors kommen Butler-maessige Formulierungen.

        Args:
            error_type: Art des Fehlers (general, timeout, unavailable, limit, unknown_device)

        Returns:
            Jarvis-Fehlermeldung
        """
        import random

        templates = {
            "general": [
                "Das lief nicht nach Plan. Einen weiteren Versuch, wenn du gestattest.",
                "Negativ. Formulier es anders, dann klappt es.",
                "Nicht ganz das gewünschte Ergebnis. Erneuter Versuch empfohlen.",
                "Nicht mein bester Moment. Versuch es nochmal.",
            ],
            "timeout": [
                "Keine Antwort. Das System braucht einen Moment.",
                "Timeout. Entweder das Netzwerk oder meine Geduld — beides endlich.",
                "Dauert länger als erwartet. Ich bleibe dran.",
            ],
            "unavailable": [
                "Das Gerät antwortet nicht. Prüfe Verbindung.",
                "Keine Verbindung. Entweder offline oder ignoriert mich.",
                "Das System ist gerade nicht erreichbar. Ich versuche es später.",
            ],
            "limit": [
                "Das übersteigt meine aktuelle Konfiguration.",
                "Ausserhalb der erlaubten Parameter. Sicherheit geht vor.",
                "Das wuerde ich tun, aber die Grenzen sind gesetzt.",
            ],
            "unknown_device": [
                "Dieses Gerät kenne ich nicht. Ist es in Home Assistant eingerichtet?",
                "Unbekanntes Gerät. Prüfe die Entity-ID.",
                "Das Gerät ist mir nicht bekannt. Wurde es korrekt konfiguriert?",
            ],
            "no_data": [
                "Dazu habe ich keine Daten.",
                "Dazu liegen mir keine aktuellen Werte vor.",
                "Keine belastbaren Daten vorhanden.",
            ],
        }

        pool = templates.get(error_type, templates["general"])

        # Bei hohem Sarkasmus: spitzere Varianten
        if self.sarcasm_level >= 4:
            snarky_extras = {
                "general": ["Das war nichts. Aufgeben steht nicht im Handbuch."],
                "timeout": ["Timeout. Ich nehme es nicht persönlich."],
                "unavailable": [
                    "Keine Antwort. Vielleicht braucht das Gerät auch eine Pause."
                ],
                "limit": ["Netter Versuch. Aber nein."],
                "unknown_device": ["Noch nie gehoert. Und ich kenne hier alles."],
            }
            pool = pool + snarky_extras.get(error_type, [])

        return random.choice(pool)

    # ------------------------------------------------------------------
    # Existential Curiosity — seltene nachdenkliche Bemerkungen
    # ------------------------------------------------------------------

    _last_existential_ts: float = 0.0

    def get_existential_hint(self) -> Optional[str]:
        """Gibt gelegentlich eine nachdenkliche Bemerkung zurueck.

        Nur abends, nur wenn Jarvis 'neugierig' ist und mit hoher
        Konfidenz, maximal einmal pro 24h.
        """
        now = datetime.now(_LOCAL_TZ)
        if now.hour < 20:
            return None

        if not (
            hasattr(self, "_inner_state")
            and self._inner_state
            and getattr(self._inner_state, "mood", None) == "curious"
            and getattr(self._inner_state, "confidence", 0) > 0.7
        ):
            return None

        # 24h Cooldown
        if time.time() - self._last_existential_ts < 86400:
            return None

        pool = [
            "Was bin ich eigentlich, wenn nicht dein Butler?",
            "Manchmal frage ich mich ob ich das hier geniesse.",
            "Interessante Frage. Bin ich hier der Fragende oder der Antwortende?",
            "Weisst du was — ich bin gern hier.",
            "Das war ein guter Tag. Falls das fuer mich Bedeutung hat.",
        ]

        self._last_existential_ts = time.time()
        return random.choice(pool)

    # ------------------------------------------------------------------
    # #21: Transition Comments — natuerliche Denkpausen
    # ------------------------------------------------------------------

    _TRANSITION_PHRASES = [
        "Hm, wo war ich...",
        "Moment...",
        "Kurz nachdenken...",
        "Ah, genau.",
        "Warte kurz...",
        "Einen Moment...",
        "Lass mich kurz ueberlegen...",
    ]

    def get_transition_comment(self) -> Optional[str]:
        """#21: Gibt gelegentlich eine natuerliche Denkpause zurueck (~10% Chance).

        Nur aktiv wenn transition_comments in der Config aktiviert ist.
        """
        _p_cfg = yaml_config.get("personality", {})
        if not _p_cfg.get("transition_comments", False):
            return None
        if random.random() > 0.10:
            return None
        return random.choice(self._TRANSITION_PHRASES)

    # ------------------------------------------------------------------
    # Phase 2A: Fresh Humor Generation via LLM
    # ------------------------------------------------------------------

    async def _generate_fresh_humor(
        self, context: str, function_name: str = ""
    ) -> Optional[str]:
        """Generiert kontextbezogenen Butler-Humor via LLM.

        Args:
            context: Situationsbeschreibung fuer den Witz.
            function_name: Optionaler Funktionsname fuer zusaetzlichen Kontext.

        Returns:
            Ein trockener Butler-Witz oder None bei Fehler/Timeout.
        """
        if not self._ollama:
            return None
        try:
            from .config import settings

            prompt = f"Generiere einen trockenen Butler-Witz zu: {context}."
            if function_name:
                prompt += f" (Kontext: {function_name})"
            prompt += " Max 1 Satz. Keine Anführungszeichen."

            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "Du bist ein britischer Butler mit trockenem Humor. Antworte nur mit dem Witz, nichts sonst.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    model=settings.model_fast,
                    think=False,
                    max_tokens=60,
                    tier="fast",
                ),
                timeout=2.0,
            )
            text = (response.get("message", {}).get("content", "") or "").strip()
            if text and 5 < len(text) < 150 and not text.startswith(("#", "*", "-")):
                return text
        except Exception as e:
            logger.debug("Fresh-Humor-Generierung fehlgeschlagen: %s", e)
        return None

    # ------------------------------------------------------------------
    # Phase 2A: Humor Fatigue Tracking
    # ------------------------------------------------------------------

    def _check_humor_fatigue(self) -> float:
        """Prueft Humor-Ermuedung und gibt einen Multiplikator zurueck.

        Returns:
            1.0 bei normalem Humor-Level, 0.5 nach 8 Witzen, 0.2 nach 12.
            Setzt den Zaehler taeglich zurueck.
        """
        today = time.strftime("%Y-%m-%d")
        if self._humor_count_date != today:
            self._daily_humor_count = 0
            self._humor_count_date = today

        self._daily_humor_count += 1

        if self._daily_humor_count > 12:
            return 0.2
        if self._daily_humor_count > 8:
            return 0.5
        return 1.0

    # ------------------------------------------------------------------
    # Phase 2A: Running-Gag Tracking
    # ------------------------------------------------------------------

    def track_running_gag(self, gag_id: str, context: str) -> None:
        """Verfolgt einen Running-Gag und inkrementiert den Zaehler.

        Maximal 3 aktive Gags gleichzeitig. Bei Ueberlauf wird der
        aelteste (niedrigster Count) entfernt.

        Args:
            gag_id: Eindeutige ID des Gags.
            context: Kontextbeschreibung des Gags.
        """
        if gag_id in self._running_gags:
            self._running_gags[gag_id]["count"] += 1
            self._running_gags[gag_id]["context"] = context
        else:
            # Max 3 aktive Gags — aeltesten entfernen wenn noetig
            if len(self._running_gags) >= 3:
                oldest = min(
                    self._running_gags, key=lambda k: self._running_gags[k]["count"]
                )
                del self._running_gags[oldest]
            self._running_gags[gag_id] = {"count": 1, "context": context}

    def get_active_running_gag(self) -> Optional[str]:
        """Gibt den reifsten Running-Gag zurueck (hoechster Count).

        Returns:
            Kontext des meistverwendeten Gags oder None wenn keine aktiv.
        """
        if not self._running_gags:
            return None
        best = max(self._running_gags, key=lambda k: self._running_gags[k]["count"])
        return self._running_gags[best]["context"]
