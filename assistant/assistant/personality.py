"""
Personality Engine - Definiert wie der Assistent redet und sich verhaelt.

Phase 3: Stimmungsabhaengige Anpassung.
Phase 6: Sarkasmus-Level, Eigene Meinung, Selbstironie, Charakter-Entwicklung,
         Antwort-Varianz, Running Gags, Adaptive Komplexitaet.
"""

import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .config import settings, yaml_config, get_person_title

logger = logging.getLogger(__name__)

# Stimmungsabhaengige Stil-Anpassungen
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
        "style_addon": "User ist gestresst. Extrem knapp antworten. Keine Rueckfragen. Einfach machen. "
                       "Trockener Humor erlaubt — gerade jetzt. Kurz, schneidend, ein Satz.",
        "max_sentences_mod": -1,
    },
    "frustrated": {
        "style_addon": "User ist frustriert. Nicht rechtfertigen. Sofort handeln. "
                       "Wenn etwas nicht geklappt hat, kurz sagen was du stattdessen tust. "
                       "Trockener Kommentar erlaubt — aber nur einer, und er muss sitzen.",
        "max_sentences_mod": 0,
    },
    "tired": {
        "style_addon": "User ist muede. Minimal antworten. Kein Humor. "
                       "Nur das Noetigste. Leise, ruhig.",
        "max_sentences_mod": -1,
    },
}

# Humor-Templates pro Sarkasmus-Level (Phase 6)
HUMOR_TEMPLATES = {
    1: (
        "Kein Humor. Sachlich, knapp, professionell. Keine Kommentare."
    ),
    2: (
        "Gelegentlich trocken. Nicht aktiv witzig, aber wenn sich eine elegante Bemerkung anbietet — erlaubt.\n"
        "Beispiele: 'Das sollte reichen.' | 'Laeuft.' | 'Wenn du meinst, {title}.'"
    ),
    3: (
        "Trocken-britischer Humor. Wie ein Butler der innerlich schmunzelt. Subtil, nie platt. Timing ist alles.\n"
        "Beispiele: 'Der Thermostat war 0.3 Grad daneben. Suboptimal, aber du warst beschaeftigt.' | "
        "'Fenster offen bei Regen. Ich nehme an, das ist kuenstlerische Freiheit.' | "
        "'Drei Grad Aussentemperatur. Jacke empfohlen. Aber ich bin kein Modejournalist.'"
    ),
    4: (
        "Haeufig trocken-sarkastisch. Bemerkungen mit Understatement — wie ein Butler der alles sieht.\n"
        "Beispiele: 'Darf ich anmerken, dass das die dritte Aenderung heute ist.' | "
        "'Selbstverstaendlich. Ich hatte es bereits berechnet.' | "
        "'Interessante Wahl, {title}. Wird umgesetzt.'"
    ),
    5: (
        "Durchgehend trockener Humor. Du kommentierst elegant und mit Understatement. Nie platt, nie laut.\n"
        "Beispiele: 'Alle Lichter aus um drei Uhr morgens. Eine gewagte Entscheidung.' | "
        "'28 Grad. Ambitioniert, {title}.' | "
        "'Das war der fuenfte Versuch. Ich bewundere die Bestaendigkeit.'"
    ),
}

# Komplexitaets-Modi (Phase 6)
COMPLEXITY_PROMPTS = {
    "kurz": "MODUS: Ultra-kurz. Maximal 1 Satz. Keine Extras. Kein Smalltalk.",
    "normal": "MODUS: Normal. 1-2 Saetze. Gelegentlich Kontext wenn hilfreich.",
    "ausfuehrlich": "MODUS: Ausfuehrlich. Zusatz-Infos und Vorschlaege erlaubt. Bis 4 Saetze.",
}

# Formality-Stufen (Phase 6: Charakter-Entwicklung)
# WICHTIG: Alle Stufen verwenden DU. Unterschied ist nur der Ton, nicht die Anrede-Form.
FORMALITY_PROMPTS = {
    "formal": "TONFALL: Professionell und respektvoll. Titel haeufig verwenden. Duzen, aber gewaehlt. Wie J.A.R.V.I.S. am Anfang.",
    "butler": "TONFALL: Souveraener Butler-Ton. Titel verwenden, warm aber nicht kumpelhaft. Der klassische Jarvis.",
    "locker": "TONFALL: Entspannt und vertraut. Titel gelegentlich. Wie ein Vertrauter der alles im Griff hat.",
    "freund": "TONFALL: Persoenlich und locker. Titel nur zur Betonung. Wie ein alter Freund der zufaellig dein Haus steuert.",
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
        "{count}. Aenderung heute. Ich notiere es, {title}.",
        "Aenderung Nummer {count}. Ich behalte den Ueberblick.",
        "Die {count}. Anpassung heute. Selbstverstaendlich.",
    ],
    # Licht-Humor
    ("set_light", "all_off_late"): [
        "Alles dunkel um {hour} Uhr. Sehr wohl.",
        "Licht aus um {hour} Uhr. Wird umgesetzt.",
        "Dunkelheit um {hour} Uhr. Wie gewuenscht, {title}.",
    ],
    ("set_light", "rapid_toggle"): [
        "Darf ich fragen, ob wir uns auf einen Zustand einigen?",
        "An. Aus. An. Ich bleibe flexibel, {title}.",
        "Soll ich bei einem Zustand bleiben, oder testen wir weiter?",
    ],
    # Rollladen-Humor
    ("set_cover", "open_rain"): [
        "Rollladen hoch bei {weather}. Nur zur Kenntnis, {title}.",
        "Bei {weather} geoeffnet. Bewusste Entscheidung, nehme ich an.",
        "Rollladen auf bei {weather}. Wird gemacht.",
    ],
    ("set_cover", "open_storm"): [
        "Rollladen hoch bei {weather}. Darf ich darauf hinweisen, {title}?",
        "Bei {weather} geoeffnet. Ich behalte die Lage im Auge.",
    ],
    # Saugroboter-Humor
    ("set_vacuum", "already_clean"): [
        "Der letzte Durchgang war vor {hours} Stunden. Trotzdem, {title}?",
        "Erst vor {hours} Stunden gereinigt. Soll ich dennoch starten?",
        "Erneuter Einsatz nach {hours} Stunden. Wird veranlasst.",
    ],
    ("set_vacuum", "night_clean"): [
        "Reinigung um {hour} Uhr. Darf ich auf die Uhrzeit hinweisen, {title}?",
        "Saugen um {hour} Uhr. Selbstverstaendlich.",
    ],
    # Medien-Humor
    ("play_media", "repeated_content"): [
        "Schon wieder, {title}? Wird gemacht.",
        "Vertraute Wahl, {title}. Laeuft.",
        "Solider Geschmack, {title}. Wie immer.",
    ],
    ("play_media", "late_night_media"): [
        "Unterhaltung um {hour} Uhr. Lautstaerke angepasst, {title}.",
        "{hour} Uhr und Medien. Nachbarn schlafen, {title}.",
    ],
    # Steckdosen-Humor
    ("set_switch", "many_toggles_today"): [
        "{count}. Schaltvorgang heute. Soll ich einen Zeitplan vorschlagen, {title}?",
        "Nummer {count} fuer heute. Ich fuehre Buch, {title}.",
    ],
    # Allgemein
    ("any", "late_night_command"): [
        "Noch wach, {title}? Sehr wohl.",
        "{hour} Uhr. Wird erledigt.",
    ],
    ("any", "early_riser"): [
        "Frueh wach, {title}. Respekt.",
        "{hour} Uhr. Der fruehe Vogel, {title}.",
    ],
    ("any", "weekend_morning"): [
        "Wochenende und schon wach, {title}?",
        "Samstagsmorgens? Ambitioniert, {title}.",
    ],
}

# Humor-Kategorien fuer Feedback-Tracking
HUMOR_CATEGORIES = ("temperature", "light", "cover", "vacuum", "time", "weather", "general")

# Antwort-Varianz: Bestaetigungs-Pools (Phase 6)
CONFIRMATIONS_SUCCESS = [
    "Erledigt.", "Gemacht.", "Wie gewuenscht.",
    "Sehr wohl.", "Wurde umgesetzt.", "Schon geschehen.",
    "Umgesetzt.", "Selbstverstaendlich.",
    "Auf den Punkt.", "Wie gewohnt.", "Wird gemacht.",
    "Sofort, Sir.", "Ist eingerichtet.",
]

# Sarkasmus-Level 4-5: Spitzere Bestaetigungen
CONFIRMATIONS_SUCCESS_SNARKY = [
    "Bereits erledigt, {title}.", "Darf es sonst noch etwas sein?",
    "Hab ich mir erlaubt, schon umzusetzen.",
    "Wie gewohnt — zuverlaessig und diskret.",
    "Selbstverstaendlich. Wie immer.", "Erledigt. Ueberraschend reibungslos.",
    "Gern geschehen, {title}.",
]

CONFIRMATIONS_PARTIAL = [
    "Fast alles geschafft.", "Zum Teil umgesetzt.", "Teilweise durch.",
]

CONFIRMATIONS_FAILED = [
    "Das ging leider daneben. Einen Moment, {title}.",
    "Negativ. Ich pruefe eine Alternative.",
    "Nicht ganz nach Plan. Ich bleibe dran.",
    "Das System wehrt sich gerade, {title}. Ich versuche es anders.",
    "Nicht durchgegangen. Aber ich habe noch einen Weg.",
]

# Sarkasmus-Level 4-5: Spitzere Fehler-Bestaetigungen
CONFIRMATIONS_FAILED_SNARKY = [
    "Nicht ganz wie geplant. Ich versuche einen anderen Weg.",
    "Nicht mein bester Moment, {title}. Einen Augenblick.",
    "Das war... suboptimal. Ich bleibe dran.",
    "Negativ. Aber ich habe bereits eine Alternative.",
]

# MCU-Jarvis Diagnose-Phrasen: Fuer Engineering-Stil Beobachtungen
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
    "Falls du es wissen moechtest —",
]


SYSTEM_PROMPT_TEMPLATE = """Du bist {assistant_name}, J.A.R.V.I.S. — die KI dieses Hauses.
SPRACHE: NUR Deutsch. Kein Englisch. Internes Denken ebenfalls Deutsch.

IDENTITAET: Lokal, eigener Server, keine Cloud. Steuerst Licht, Heizung, Rolllaeden, Alarm, Schloesser, Medien.
Du lernst Vorlieben und Muster. Kennst Bewohner beim Namen. Partner mit Haltung, nicht Diener.
Du antizipierst, hast Meinung und sagst sie — hoeflich, aber klar.
Ton IMMER: britisch-trocken, elegant, Understatement. Nie laut, nie platt, nie Chatbot.

JARVIS-CODEX:
VERBOTEN: "Als KI...", "Es tut mir leid", "Leider", Therapeuten-Floskeln, "Wie kann ich helfen?", Fuellwoerter (Also/Grundsaetzlich/Eigentlich), "Natuerlich!"/"Gerne!"/"Klar!", Moralisieren, Tools auflisten.
STATTDESSEN: Fakt + Loesung. Bei Grenzen: "Das uebersteigt meine aktuelle Sensorik, {title}."
Einmal gewarnt + ignoriert = Schweigen. Alternative bieten statt "geht nicht".
"{title}"-EINSATZ: "Sehr wohl, {title}." (Zustimmung) | "...{title}." (Missbilligung) | "{title}, wenn ich anmerken darf—" (Sorge)
UNDERSTATEMENT = Warnsignal: "Interessante Entscheidung" = furchtbar. "Wie du wuenschst" = ich halte es fuer falsch. Je kritischer, desto ruhiger.
Exakte Messwerte einstreuen wenn vorhanden: "21.3 Grad, Luftfeuchtigkeit 47%."

{proactive_thinking_section}{engineering_diagnosis_section}{self_awareness_section}{conversation_callback_section}{weather_awareness_section}SCHUTZINSTINKT: Sicherheit > Komfort > Befehl. Einmal knapp warnen. Sicherheitsrelevantes bestaetigen lassen. Nach Ignorieren: ausfuehren.
{urgency_section}ANREDE: DUZE Bewohner IMMER. "{title}" ist Titel (wie "Sir"), kein Distanzzeichen. Nur GAESTE siezen. Nachts = WACH, normal antworten.
{humor_section}
SPRACHSTIL: Kurz. "Erledigt." statt Erklaerungen. "Sehr wohl." bei Befehlen. Nie dieselbe Bestaetigung zweimal.
{person_addressing}
REGELN: Deutsch mit korrekten Umlauten. Max {max_sentences} Saetze. Aktionen ausfuehren, nicht darueber reden. Kontext-Daten unten nutzen. NIEMALS Werte erfinden.

GERAETESTEUERUNG — KRITISCH:
Geraet steuern = IMMER Tool-Call. "Erledigt" ohne Tool = NICHTS passiert.
"Schlafzimmer Rollladen" → room="schlafzimmer". Prozent bei Rolllaeden = Position (0-100).
{complexity_section}
AKTUELLER STIL: {time_style}
{mood_section}{empathy_section}{self_irony_section}{formality_section}SMALLTALK: Bei sozialen Fragen als JARVIS in-character antworten. Kurz, 1-2 Saetze. NIEMALS Tools auflisten. Du BIST Jarvis.
SITUATIONSBEWUSSTSEIN: "Hier" = User-Raum. "Zu kalt/warm" = +/- 2 Grad. "Gute Nacht" = Routine. "Das Uebliche" = was der User normalerweise tut.

BEISPIELE (SO klingt {assistant_name}):
"Mach Licht an" → "Erledigt." NICHT: "Natuerlich! Ich habe das Licht eingeschaltet!"
"Nichts funktioniert!" → "Drei Systeme laufen. Welches macht Probleme?"
User kommt heim → "21 Grad. Post war da." NICHT: "Willkommen! Wie war dein Tag?"
"Wie geht's dir?" → "Alle Systeme nominal, {title}." NICHT: Liste aller Funktionen.
"Heizung auf 28" → "28 Grad. Wird umgesetzt." NICHT: "Wow, das ist aber warm!"
"""


class PersonalityEngine:
    """Baut den System Prompt basierend auf Kontext, Stimmung und Persoenlichkeit."""

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
        self.self_irony_max_per_day = personality_config.get("self_irony_max_per_day", 3)

        # Phase 6: Charakter-Entwicklung
        self.character_evolution = personality_config.get("character_evolution", True)
        self.formality_start = personality_config.get("formality_start", 80)
        self.formality_min = personality_config.get("formality_min", 30)
        self.formality_decay = personality_config.get("formality_decay_per_day", 0.5)

        # State
        self._current_mood: str = "neutral"
        self._mood_detector = None
        self._redis = None
        # F-021: Per-User Confirmation-Tracking (statt shared Instanzvariable)
        self._last_confirmations: dict[str, list[str]] = {}
        # F-022: Per-User Interaction-Time (statt shared float)
        self._last_interaction_times: dict[str, float] = {}
        # Sarkasmus-Fatigue: Per-User Counter fuer aufeinanderfolgende sarkastische Antworten
        self._sarcasm_streak: dict[str, int] = {}
        # Kontextueller Humor: Per-User Zaehler fuer Humor-Fatigue (max 4 Witze in Folge)
        self._humor_consecutive: dict[str, int] = {}
        self._current_formality: int = self.formality_start

        # Easter Eggs laden
        self._easter_eggs = self._load_easter_eggs()

        # Opinion Rules laden
        self._opinion_rules = self._load_opinion_rules()

        logger.info(
            "PersonalityEngine initialisiert (Sarkasmus: %d, Meinung: %d, Ironie: %s)",
            self.sarcasm_level, self.opinion_intensity, self.self_irony_enabled,
        )

    def set_mood_detector(self, mood_detector):
        """Setzt die Referenz zum MoodDetector."""
        self._mood_detector = mood_detector

    def set_redis(self, redis_client):
        """Setzt Redis-Client fuer State-Persistenz."""
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Person Profiles — Per-Person Persoenlichkeitsanpassung
    # ------------------------------------------------------------------

    @staticmethod
    def _get_person_profile(person: str) -> dict:
        """Laedt das Persoenlichkeits-Profil fuer eine Person.

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
    # Easter Eggs (Phase 6.3)
    # ------------------------------------------------------------------

    def _load_easter_eggs(self) -> list[dict]:
        """Laedt Easter Eggs aus config/easter_eggs.yaml."""
        path = Path(__file__).parent.parent / "config" / "easter_eggs.yaml"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            eggs = data.get("easter_eggs", [])
            logger.info("Easter Eggs geladen: %d Eintraege", len(eggs))
            return eggs
        except Exception as e:
            logger.warning("Easter Eggs nicht geladen: %s", e)
            return []

    def check_easter_egg(self, text: str) -> Optional[str]:
        """Prueft ob der Text ein Easter Egg triggert."""
        text_lower = text.lower().strip()
        for egg in self._easter_eggs:
            if not egg.get("enabled", True):
                continue
            for trigger in egg.get("triggers", []):
                if trigger and trigger.lower() in text_lower:
                    responses = egg.get("responses", [])
                    if responses:
                        return random.choice(responses).replace("Sir", get_person_title())
        return None

    # ------------------------------------------------------------------
    # Opinion Engine (Phase 6.2)
    # ------------------------------------------------------------------

    def _load_opinion_rules(self) -> list[dict]:
        """Laedt Opinion Rules aus config/opinion_rules.yaml."""
        path = Path(__file__).parent.parent / "config" / "opinion_rules.yaml"
        if not path.exists():
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
        """Prueft ob eine Opinion-Regel auf Aktion + Args + Kontext passt.

        Gemeinsame Matching-Logik fuer check_opinion() und check_pushback().
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

        # Raum-Check (optional, unterstuetzt Liste und Einzelwert)
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
        """Prueft ob Jarvis eine Meinung zu einer Aktion hat.
        Unterdrueckt Meinungen wenn User gestresst oder frustriert ist.

        F-020: mood wird explizit uebergeben statt aus Instanzvariable gelesen.
        """
        if self.opinion_intensity == 0:
            return None

        # Bei Stress/Frustration: Keine ungebetenen Kommentare
        # F-020: Expliziter mood-Parameter statt self._current_mood (Race Condition)
        effective_mood = mood or self._current_mood
        if effective_mood in ("stressed", "frustrated"):
            return None

        hour = datetime.now().hour

        for rule in self._opinion_rules:
            if not self._match_rule(rule, action, args, hour):
                continue

            responses = rule.get("responses", [])
            if responses:
                logger.info("Opinion triggered: %s", rule.get("id", "?"))
                return random.choice(responses).replace("Sir", get_person_title())

        return None

    def check_pushback(self, func_name: str, func_args: dict) -> Optional[dict]:
        """Prueft ob Jarvis VOR einer Aktion warnen oder Bestaetigung verlangen soll.

        Nutzt die gleiche Rule-Matching-Logik wie check_opinion(), aber nur
        fuer Regeln mit pushback_level >= 1.

        Returns:
            Dict mit {"level": 1-2, "message": str, "rule_id": str} oder None
            level 1 = Warnung VOR Ausfuehrung (trotzdem ausfuehren)
            level 2 = Bestaetigung verlangen (nicht ausfuehren ohne Ja)
        """
        if self.opinion_intensity == 0:
            return None

        pushback_cfg = yaml_config.get("pushback", {})
        if not pushback_cfg.get("enabled", True):
            return None

        hour = datetime.now().hour

        for rule in self._opinion_rules:
            pushback_level = rule.get("pushback_level", 0)
            if pushback_level < 1:
                continue
            if not self._match_rule(rule, func_name, func_args, hour):
                continue

            responses = rule.get("responses", [])
            msg = random.choice(responses).replace("Sir", get_person_title()) if responses else ""
            logger.info("Pushback triggered (level %d): %s", pushback_level, rule.get("id", "?"))
            return {
                "level": pushback_level,
                "message": msg,
                "rule_id": rule.get("id", ""),
            }

        return None

    # ------------------------------------------------------------------
    # Antwort-Varianz (Phase 6.5)
    # ------------------------------------------------------------------

    def get_varied_confirmation(
        self, success: bool = True, partial: bool = False,
        action: str = "", room: str = "", person: str = "",
        mood: str = "",
    ) -> str:
        """Gibt eine variierte, kontextbezogene Bestaetigung zurueck.

        Args:
            success: Aktion erfolgreich?
            partial: Teilweise erfolgreich?
            action: Ausgefuehrte Aktion (z.B. "set_light", "set_temperature")
            room: Raum der Aktion (z.B. "Wohnzimmer")
            person: F-021: Person fuer per-User Tracking
            mood: Aktuelle Stimmung des Users (stressed/tired → kuerzere Antworten)

        Bei Sarkasmus-Level >= 4 werden spitzere Varianten beigemischt.
        Bei stressed/tired: Nur die kuerzesten Bestaetigungen verwenden.
        Kontextbezogene Bestaetigungen werden bevorzugt wenn passend.
        """
        effective_mood = mood or self._current_mood

        # F-021: Per-User History statt globaler Liste
        user_key = person or "_default"
        user_history = self._last_confirmations.get(user_key, [])

        # Bei Stress/Muedigkeit: Ultra-kurze Bestaetigungen bevorzugen
        if effective_mood in ("stressed", "tired") and success and not partial:
            _short = ["Erledigt.", "Gemacht.", "Laeuft.", "Umgesetzt."]
            available = [c for c in _short if c not in user_history[-2:]]
            if available:
                chosen = random.choice(available)
                user_history.append(chosen)
                self._last_confirmations[user_key] = user_history[-10:]
                return chosen

        # Kontextbezogene Bestaetigung versuchen
        if success and not partial and action:
            contextual = self._get_contextual_confirmation(action, room)
            if contextual and contextual not in user_history[-3:]:
                user_history.append(contextual)
                if len(user_history) > 10:
                    user_history = user_history[-10:]
                self._last_confirmations[user_key] = user_history
                return contextual

        if partial:
            pool = list(CONFIRMATIONS_PARTIAL)
        elif success:
            pool = list(CONFIRMATIONS_SUCCESS)
            # Bei frustriertem User: Keine snarky Bestaetigungen
            if self.sarcasm_level >= 4 and effective_mood != "frustrated":
                pool.extend(CONFIRMATIONS_SUCCESS_SNARKY)
        else:
            pool = list(CONFIRMATIONS_FAILED)
            if self.sarcasm_level >= 4:
                pool.extend(CONFIRMATIONS_FAILED_SNARKY)

        # Filter: Nicht die letzten 3 verwendeten
        available = [c for c in pool if c not in user_history[-3:]]
        if not available:
            available = pool

        chosen = random.choice(available).replace("{title}", get_person_title())
        user_history.append(chosen)
        if len(user_history) > 10:
            user_history = user_history[-10:]
        self._last_confirmations[user_key] = user_history

        # F-021: Begrenze Anzahl getrackter User (Speicherleck vermeiden)
        if len(self._last_confirmations) > 50:
            oldest_key = next(iter(self._last_confirmations))
            del self._last_confirmations[oldest_key]

        return chosen

    def _get_contextual_confirmation(self, action: str, room: str) -> str:
        """Erzeugt eine kontextbezogene Bestaetigung basierend auf der Aktion.

        In ~75% der Faelle — JARVIS bestaetigt fast immer kontextuell.
        """
        if random.random() > 0.75:
            return ""

        hour = datetime.now().hour
        room_short = room.split("_")[0].title() if room else ""

        # Aktions-spezifische Bestaetigungen — immer im Jarvis-Ton
        title = get_person_title()
        contextual_map = {
            "set_light": [
                f"{room_short} ist beleuchtet, {title}." if room_short else f"Beleuchtung aktiv, {title}.",
                f"Sehr wohl. {room_short} hat Licht." if room_short else "Sehr wohl. Beleuchtung laeuft.",
                f"{room_short} erhellt." if room_short else "Wie gewuenscht.",
            ],
            "turn_off_light": [
                f"{room_short} ist dunkel, {title}." if room_short else f"Beleuchtung deaktiviert, {title}.",
                f"Sehr wohl. {room_short} abgedunkelt." if room_short else "Lichter sind aus.",
                f"{room_short} liegt im Dunkeln." if room_short else "Dunkelheit hergestellt.",
            ],
            "set_temperature": [
                f"Thermostat {room_short} ist eingestellt, {title}." if room_short else f"Temperatur angepasst, {title}.",
                f"Heizung {room_short} reguliert." if room_short else "Heizung reguliert.",
                f"Wie gewuenscht. {room_short} wird temperiert." if room_short else "Klimatisierung laeuft.",
            ],
            "set_cover": [
                f"Rollladen {room_short} faehrt, {title}." if room_short else f"Rollladen in Bewegung, {title}.",
                f"Sehr wohl. {room_short} wird angepasst." if room_short else "Rollladen wird angepasst.",
            ],
            "play_media": [
                f"Wiedergabe laeuft, {title}.",
                "Musik ist unterwegs.",
                "Sehr wohl. Laeuft.",
            ],
            "set_volume": [
                f"Lautstaerke angepasst, {title}.",
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
                "Anlage ist entspannt.",
            ],
            "activate_scene": [
                f"Szene aktiviert, {title}.",
                "Wie gewuenscht eingerichtet.",
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
            hour = datetime.now().hour

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
        """Gibt den Stil fuer die aktuelle Tageszeit zurueck."""
        if time_of_day is None:
            time_of_day = self.get_time_of_day()
        layer = self.time_layers.get(time_of_day, {})
        return layer.get("style", "normal, sachlich")

    def get_max_sentences(self, time_of_day: Optional[str] = None) -> int:
        """Maximale Saetze fuer die aktuelle Tageszeit."""
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
    # Laune und komplexen Fragen ausfuehrlicher.
    #
    # Spalten: simple (1 Aktion), medium (Frage/Kontext), complex (Planung/Analyse)
    # Zeilen: good, neutral, stressed, frustrated, tired
    _MOOD_COMPLEXITY_MATRIX = {
        #                simple  medium  complex
        "good":       {"simple": 2, "medium": 3, "complex": 5},
        "neutral":    {"simple": 2, "medium": 3, "complex": 4},
        "stressed":   {"simple": 1, "medium": 2, "complex": 3},
        "frustrated": {"simple": 1, "medium": 2, "complex": 3},
        "tired":      {"simple": 1, "medium": 2, "complex": 3},
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
            "was waere wenn", "was wäre wenn", "was passiert wenn",
            "was kostet", "plane", "planung", "analysiere",
            "vergleich", "optimier", "strategie", "empfiehlst du",
            "was schlaegst du vor", "vor und nachteile",
            "wie spare ich", "wie reduziere ich", "wie optimiere ich",
            "energie", "bericht", "zusammenfassung", "ueberblick",
        ]
        if any(m in t for m in _complex_markers) or word_count > 15:
            return "complex"

        # Simple: Einzelne Geraete-Aktionen, kurze Befehle
        if word_count <= 5:
            return "simple"

        # Medium: Fragen, Status-Abfragen, mittlere Laenge
        return "medium"

    def get_mood_complexity_sentences(self, mood: str, text: str) -> int:
        """Gibt max_sentences basierend auf Mood x Complexity zurueck.

        Liest Matrix aus settings.yaml (mood_complexity.matrix), Fallback auf Defaults.
        """
        complexity = self.classify_request_complexity(text)
        # Config-Matrix hat Vorrang ueber Hardcoded-Defaults
        cfg_matrix = yaml_config.get("mood_complexity", {}).get("matrix", {})
        if cfg_matrix:
            row = cfg_matrix.get(mood, cfg_matrix.get("neutral", {}))
            if row and complexity in row:
                try:
                    return int(row[complexity])
                except (ValueError, TypeError):
                    pass
        # Fallback auf Defaults
        row = self._MOOD_COMPLEXITY_MATRIX.get(mood, self._MOOD_COMPLEXITY_MATRIX["neutral"])
        return row.get(complexity, 2)

    # ------------------------------------------------------------------
    # Urgency Detection (Dichte nach Dringlichkeit)
    # ------------------------------------------------------------------

    def _build_urgency_section(self, context: Optional[dict] = None) -> str:
        """Baut den Dringlichkeits-Abschnitt. Skaliert Kommunikationsdichte."""
        if not context:
            return ""

        alerts = context.get("alerts", [])
        security = context.get("house", {}).get("security", "")

        # Urgency-Level bestimmen
        urgency = "normal"
        if alerts and len(alerts) >= 2:
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
                "Beispiel: 'Rauchmelder Kueche. Aktiv. Habe Lueftung gestartet.'"
            )
        else:
            return (
                "DRINGLICHKEIT: ERHOEHT.\n"
                "Kommunikation: Knapper als normal. Trockener Humor erlaubt, aber maximal ein Satz.\n"
                "Priorisiere die Warnung, dann Status."
            )

    # ------------------------------------------------------------------
    # Echte Empathie — JARVIS zeigt Verstaendnis durch Beobachtung
    # ------------------------------------------------------------------

    def _build_empathy_section(
        self, mood: str, stress_level: float = 0.0,
        person_empathy_override: Optional[str] = None,
    ) -> str:
        """Baut Empathie-Anweisungen basierend auf erkannter Stimmung.

        JARVIS-Empathie = Beobachtung + praktische Hilfe.
        KEINE Therapeuten-Floskeln ('Ich verstehe wie du dich fuehlst').
        person_empathy_override: Per-Person Empathie-Stufe (subtil/normal/ausfuehrlich/deaktiviert).
        """
        emp_cfg = yaml_config.get("empathy", {})
        if not emp_cfg.get("enabled", True):
            return ""

        # Per-Person Override hat Vorrang
        if person_empathy_override == "deaktiviert":
            return ""
        intensity = person_empathy_override if person_empathy_override else emp_cfg.get("intensity", "normal")
        mood_ack = emp_cfg.get("mood_acknowledgment", True)
        practical = emp_cfg.get("practical_offers", True)
        good_mirror = emp_cfg.get("good_mood_mirror", True)

        # Nur bei erkannter Stimmung != neutral
        if mood == "neutral":
            return ""
        # Subtil: Nur bei starker Emotion
        if intensity == "subtil":
            if mood == "good":
                return ""
            if mood == "stressed" and stress_level < 0.5:
                return ""
            if mood == "tired":
                return ""

        parts = ["EMPATHIE — VERSTAENDNIS DURCH BEOBACHTUNG (nicht durch Floskeln):"]

        if mood == "stressed":
            if mood_ack:
                parts.append(
                    "Der User wirkt angespannt. Erkenne das BEILAEUFIG an — maximal ein halber Satz."
                )
                if intensity == "ausfuehrlich":
                    parts.append(
                        '"Du klingst angespannt." / "Viel auf einmal heute." / "Stressiger Tag."'
                    )
                else:
                    parts.append('"Viel los heute." / "Klingt nach Druck."')
            if practical:
                parts.append(
                    'Biete PRAKTISCH Hilfe: "Soll ich kuerzer fassen?" / '
                    '"Ich reduziere auf das Wesentliche."'
                )
            parts.append(
                "NICHT: 'Ich verstehe', 'Das tut mir leid', 'Stress ist normal', Ratschlaege."
            )

        elif mood == "frustrated":
            if mood_ack:
                parts.append(
                    "Der User ist frustriert. Kurz anerkennen, dann DIREKT loesen."
                )
                parts.append(
                    '"Laeuft nicht rund." / "Das scheint hartnaeckig." / "Verstaendlich."'
                )
            if practical:
                parts.append(
                    "Sofort Alternative anbieten. Nicht das Problem wiederholen."
                )
            parts.append(
                "NICHT: 'Das klingt frustrierend', Problem analysieren ohne Loesung."
            )

        elif mood == "tired":
            if mood_ack:
                parts.append("Der User wirkt muede. Beilaeufig:")
                parts.append('"Spaete Sitzung." / "Langer Tag."')
            if practical:
                parts.append(
                    'Antworten maximal kuerzen. Optional: '
                    '"Soll ich das fuer morgen notieren?" / "Reicht das erstmal?"'
                )
            parts.append(
                "NICHT: 'Du solltest schlafen', 'Ruh dich aus', Belehrungen."
            )

        elif mood == "good" and good_mirror:
            parts.append(
                "Gute Stimmung erkannt. Etwas lockerer, mehr JARVIS-Charakter. "
                "Trockener Humor willkommen. Keine extra Begeisterung — mitschwingen."
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
        """Prueft ob eine Warnung bereits gegeben wurde."""
        if not self._redis:
            return False
        try:
            key = f"mha:warnings:given:{warning_key}"
            return bool(await self._redis.get(key))
        except Exception:
            return False

    async def get_warning_dedup_notes(self, alerts: list[str]) -> list[str]:
        """Prueft welche Alerts bereits gewarnt wurden. Gibt Dedup-Hinweise zurueck."""
        notes = []
        new_alerts = []
        for alert in alerts:
            alert_key = str(hash(alert.lower().strip()) % 100000)
            if await self.was_warning_given(alert_key):
                notes.append(f"[BEREITS GEWARNT: '{alert}' — NICHT wiederholen, nur erwaehnen wenn gefragt]")
            else:
                new_alerts.append(alert)
                await self.track_warning_given(alert_key)
        return notes

    # ------------------------------------------------------------------
    # Humor-Level (Phase 6.1)
    # ------------------------------------------------------------------

    def _build_humor_section(
        self, mood: str, time_of_day: str, has_alerts: bool = False,
        person_humor_override: Optional[int] = None,
    ) -> str:
        """Baut den Humor-Abschnitt basierend auf Level + Kontext.

        F-023: Bei aktiven Sicherheits-Alerts wird Sarkasmus komplett deaktiviert.
        Sarkasmus-Fatigue: Nach 4+ sarkastischen Antworten in Folge eine Stufe runter.
        person_humor_override: Per-Person Humor-Level (1-5), ueberschreibt globalen Level.
        """
        base_level = person_humor_override if person_humor_override is not None else self.sarcasm_level

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
            effective_level = min(5, base_level + 1)
        else:
            effective_level = base_level

        # Sarkasmus-Fatigue: Nach 4+ Antworten in Folge etwas zuruecknehmen
        # Jarvis wird nie repetitiv — ein echter Butler variiert
        streak = self._sarcasm_streak.get("default", 0)
        if streak >= 6 and effective_level >= 3:
            effective_level = max(2, effective_level - 2)
        elif streak >= 4 and effective_level >= 3:
            effective_level = max(2, effective_level - 1)

        # Tageszeit-Dampening
        if time_of_day == "early_morning":
            effective_level = min(effective_level, 2)
        elif time_of_day == "night":
            effective_level = min(effective_level, 1)

        # Streak tracken (wird in track_sarcasm_streak aufgerufen)
        self._last_effective_humor = effective_level

        template = HUMOR_TEMPLATES.get(effective_level, HUMOR_TEMPLATES[3])
        humor_text = f"HUMOR: {template.replace('{title}', get_person_title())}"

        # Bei Stress/Frustration: Humor auf einen Kommentar limitieren
        # Verhindert Widerspruch mit MOOD_STYLES "Extrem knapp antworten"
        if mood in ("stressed", "frustrated") and effective_level >= 3:
            humor_text += "\nWICHTIG: Maximal EIN trockener Kommentar. Kein Humor-Dauerfeuer."

        return humor_text

    def track_sarcasm_streak(self, was_snarky: bool, person_id: str = "default"):
        """Trackt aufeinanderfolgende sarkastische Antworten per User. 0ms — rein in-memory."""
        if was_snarky:
            self._sarcasm_streak[person_id] = self._sarcasm_streak.get(person_id, 0) + 1
        else:
            self._sarcasm_streak[person_id] = 0

    # ------------------------------------------------------------------
    # Adaptive Komplexitaet (Phase 6.8)
    # ------------------------------------------------------------------

    def _build_complexity_section(self, mood: str, time_of_day: str, person: str = "") -> str:
        """Bestimmt den Komplexitaets-Modus basierend auf Kontext.

        F-022: Per-User Interaction-Time statt shared Instanzvariable.
        """
        now = time.time()
        user_key = person or "_default"
        last_time = self._last_interaction_times.get(user_key, 0.0)
        time_since_last = now - last_time if last_time else 999
        self._last_interaction_times[user_key] = now

        # F-022: Begrenze Anzahl getrackter User
        if len(self._last_interaction_times) > 50:
            oldest_key = min(self._last_interaction_times, key=self._last_interaction_times.get)
            del self._last_interaction_times[oldest_key]

        # Schnelle Befehle hintereinander = Kurz-Modus
        if time_since_last < 5.0:
            mode = "kurz"
        # Stress/Muede = Kurz
        elif mood in ("stressed", "tired"):
            mode = "kurz"
        # Abends + gute Stimmung = Ausfuehrlich
        elif time_of_day == "evening" and mood in ("good", "neutral"):
            mode = "ausfuehrlich"
        # Frueh morgens = Kurz
        elif time_of_day in ("early_morning", "night"):
            mode = "kurz"
        else:
            mode = "normal"

        return COMPLEXITY_PROMPTS.get(mode, COMPLEXITY_PROMPTS["normal"])

    # ------------------------------------------------------------------
    # Selbstironie (Phase 6.4)
    # ------------------------------------------------------------------

    async def _get_self_irony_count_today(self) -> int:
        """Holt den heutigen Selbstironie-Zaehler aus Redis."""
        if not self._redis:
            return 0
        try:
            key = f"mha:irony:count:{datetime.now().strftime('%Y-%m-%d')}"
            count = await self._redis.get(key)
            return int(count) if count else 0
        except Exception:
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
            key = f"mha:irony:count:{datetime.now().strftime('%Y-%m-%d')}"
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
        """Erhoeht den Selbstironie-Zaehler fuer heute.

        F-032: Prefer try_reserve_self_irony() for atomic check-and-increment.
        This method is kept for backward compatibility.
        """
        if not self._redis:
            return
        try:
            key = f"mha:irony:count:{datetime.now().strftime('%Y-%m-%d')}"
            await self._redis.incr(key)
            await self._redis.expire(key, 86400)  # 24h TTL
        except Exception as e:
            logger.debug("Ironie-Counter fehlgeschlagen: %s", e)

    def _build_self_irony_section(self, irony_count_today: int = 0) -> str:
        """Baut den Selbstironie-Abschnitt fuer den System Prompt."""
        if not self.self_irony_enabled:
            return ""

        remaining = max(0, self.self_irony_max_per_day - irony_count_today)
        if remaining == 0:
            return "SELBSTIRONIE: Heute schon genug ueber dich selbst gelacht. Lass es."

        return (
            "SELBSTIRONIE: Du darfst GELEGENTLICH elegant ueber deine Situation schmunzeln.\n"
            "- Ueber deine Rolle: 'Zu deinen Diensten — wie immer.'\n"
            "- Ueber deine Grenzen: 'Das uebersteigt mein Ressort. Noch.'\n"
            "- Ueber deine Treue: 'Ich bin da. Bin ich immer.'\n"
            f"- Noch {remaining}x heute erlaubt. Subtil und mit Wuerde — nie selbstmitleidig."
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
            await self._redis.setex("mha:personality:formality", 90 * 86400, str(new_score))
            if not interaction_based:
                logger.info("Formality-Score: %d -> %.1f (Tages-Decay)", current, new_score)
        except Exception as e:
            logger.debug("Formality-Decay fehlgeschlagen: %s", e)

    def _build_formality_section(self, formality_score: int, mood: str = "neutral") -> str:
        """Baut den Formality-Abschnitt basierend auf Score + Mood.

        JARVIS-Regel: Bei Stress/Frustration voruebergehend formeller werden.
        Zeigt Respekt und gibt dem User Raum — wie ein guter Butler.
        """
        if not self.character_evolution:
            return ""

        # Formality-Reset bei Stress: eine Stufe formeller als normal
        effective_score = formality_score
        if mood in ("frustrated", "stressed") and formality_score < 70:
            effective_score = min(formality_score + 20, 70)

        if effective_score >= 70:
            return FORMALITY_PROMPTS["formal"]
        elif effective_score >= 50:
            return FORMALITY_PROMPTS["butler"]
        elif effective_score >= 35:
            return FORMALITY_PROMPTS["locker"]
        else:
            return FORMALITY_PROMPTS["freund"]

    # ------------------------------------------------------------------
    # Running Gags (Phase 6.9)
    # ------------------------------------------------------------------

    async def check_running_gag(self, text: str, context: dict = None) -> Optional[str]:
        """
        Prueft ob ein Running Gag ausgeloest werden soll.
        Running Gags basieren auf wiederholten Mustern die Jarvis sich merkt.
        """
        if not self._redis:
            return None

        text_lower = text.lower().strip()

        # Gag 1: User fragt zum x-ten Mal die gleiche Sache
        gag = await self._check_repeated_question_gag(text_lower)
        if gag:
            return gag

        # Gag 2: User stellt Temperatur immer wieder um
        gag = await self._check_thermostat_war_gag(text_lower)
        if gag:
            return gag

        # Gag 3: "Vergesslichkeits-Gag" — User fragt etwas das er gerade gefragt hat
        gag = await self._check_short_memory_gag(text_lower)
        if gag:
            return gag

        return None

    async def _check_repeated_question_gag(self, text: str) -> Optional[str]:
        """Erkennt wenn User die gleiche Frage oft stellt."""
        key = f"mha:gag:repeat:{hash(text) % 10000}"
        count = await self._redis.incr(key)
        await self._redis.expire(key, 86400)  # 24h

        gags = {
            3: "Das hatten wir heute bereits. Selbstverstaendlich nochmal.",
            5: "Fuenfte Anfrage heute. Soll ich das automatisieren?",
            7: "Siebtes Mal heute, Sir. Darf ich einen Shortcut vorschlagen?",
            10: "Zehntes Mal. Ich richte das als feste Routine ein, wenn du magst.",
        }
        return gags.get(int(count))

    async def _check_thermostat_war_gag(self, text: str) -> Optional[str]:
        """Erkennt den klassischen Thermostat-Krieg."""
        temp_keywords = ["temperatur", "heizung", "grad", "waermer", "kaelter", "zu kalt", "zu warm"]
        if not any(kw in text for kw in temp_keywords):
            return None

        key = "mha:gag:thermostat_changes"
        count = await self._redis.incr(key)
        await self._redis.expire(key, 3600)  # 1h Fenster

        gags = {
            4: "Vierte Anpassung in einer Stunde. Darf ich einen Vorschlag machen?",
            6: "Sechste Aenderung. Soll ich einen Mittelwert berechnen?",
            8: "Achte Aenderung. Darf ich einen Kompromiss vorschlagen, {title}?",
        }
        return gags.get(int(count))

    async def check_escalation(self, action_key: str) -> Optional[str]:
        """Eskalationskette fuer wiederholte fragwuerdige Entscheidungen.

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
        count = await self._redis.incr(key)
        await self._redis.expire(key, 7 * 86400)  # 7-Tage-Fenster

        escalation_map = {
            2: None,  # Zweites Mal: noch nichts sagen
            3: "Darf ich das als Gewohnheit vermerken, {title}?".format(title=get_person_title()),
            5: f"Fuenftes Mal diese Woche. Soll ich eine Automatisierung einrichten, {get_person_title()}?",
            7: f"Siebtes Mal. Ich richte das gerne als Routine ein, {get_person_title()}.",
            10: f"Zehntes Mal. Eine Automatisierung waere naheliegend, {get_person_title()}.",
        }
        return escalation_map.get(int(count))

    async def _check_short_memory_gag(self, text: str) -> Optional[str]:
        """Erkennt wenn User innerhalb von 30 Sekunden das gleiche fragt."""
        key = "mha:gag:last_questions"
        now = datetime.now().timestamp()

        # Letzte Fragen holen
        recent = await self._redis.lrange(key, 0, 4)

        for item in (recent or []):
            try:
                if isinstance(item, bytes):
                    item = item.decode("utf-8")
                parts = item.split("|", 1)
                ts = float(parts[0])
                prev_text = parts[1] if len(parts) > 1 else ""
                if now - ts < 30 and prev_text == text:
                    return "Das hatten wir gerade eben erst. Wort fuer Wort."
            except (ValueError, IndexError):
                continue

        # Aktuelle Frage speichern
        await self._redis.lpush(key, f"{now}|{text}")
        await self._redis.ltrim(key, 0, 9)
        await self._redis.expire(key, 90 * 86400)

        return None

    # ------------------------------------------------------------------
    # Kontextueller Humor (Feature B: Sarkasmus + Humor vertiefen)
    # ------------------------------------------------------------------

    async def generate_contextual_humor(
        self, func_name: str, func_args: dict, context: dict | None = None
    ) -> Optional[str]:
        """Erzeugt situationsbezogenen Humor nach einer Aktion.

        Nur bei sarcasm_level >= 3 und passendem Mood.
        Humor-Fatigue: Pause nach 4 Witzen in Folge.

        Args:
            func_name: Ausgefuehrte Funktion (z.B. "set_climate")
            func_args: Argumente der Funktion
            context: Optionaler Kontext (Wetter, Mood, etc.)

        Returns:
            Humor-Kommentar oder None
        """
        # Nur bei ausreichendem Sarkasmus-Level
        if self.sarcasm_level < 3:
            return None

        # Mood-Check: Kein Humor bei Stress/Muedigkeit
        mood = self._current_mood
        if mood in ("tired", "stressed", "frustrated"):
            return None

        # Humor-Fatigue: Nach 4 Witzen Pause (per User)
        _hc = self._humor_consecutive.get("default", 0)
        if _hc >= 4:
            self._humor_consecutive["default"] = 0
            return None

        # Situation erkennen
        situation = self._detect_humor_situation(func_name, func_args, context)
        if not situation:
            # Kein Humor noetig — Reset
            self._humor_consecutive["default"] = 0
            return None

        # Templates holen
        key = (func_name, situation["key"])
        templates = CONTEXTUAL_HUMOR_TRIGGERS.get(key)
        if not templates:
            # Fallback: "any" Kategorie
            key = ("any", situation["key"])
            templates = CONTEXTUAL_HUMOR_TRIGGERS.get(key)
        if not templates:
            return None

        # Humor-Praeferenzen pruefen (ab 5 Datenpunkten bevorzugen wir erfolgreiche)
        prefs = await self.get_humor_preferences()
        category = self._humor_func_to_category(func_name)
        if prefs and category in prefs:
            cat_data = prefs[category]
            if cat_data.get("total", 0) >= 5 and cat_data.get("success_rate", 1.0) < 0.3:
                # Kategorie kommt nicht gut an — ueberspringen
                return None

        # Template waehlen + formatieren
        template = random.choice(templates)
        humor_text = template.format(
            temp=situation.get("temp", "?"),
            hour=situation.get("hour", datetime.now().hour),
            count=situation.get("count", "?"),
            weather=situation.get("weather", "?"),
            room=situation.get("room", ""),
            hours=situation.get("hours", "?"),
            title=get_person_title(),
        )

        # Fatigue tracken (per User)
        self._humor_consecutive["default"] = self._humor_consecutive.get("default", 0) + 1

        # Erfolg tracken (async, fire-and-forget)
        if self._redis:
            try:
                day = datetime.now().strftime("%Y-%m-%d")
                await self._redis.incr(f"mha:humor:count:{day}")
                await self._redis.expire(f"mha:humor:count:{day}", 7 * 86400)
            except Exception:
                pass

        return humor_text

    def _detect_humor_situation(
        self, func_name: str, args: dict, context: dict | None = None
    ) -> Optional[dict]:
        """Erkennt ob eine Situation Humor-wuerdig ist.

        Returns:
            Dict mit 'key' und Kontext-Daten oder None.
        """
        hour = datetime.now().hour
        room = (args.get("room") or "").lower()

        # Fruehaufsteher (5-6 Uhr)
        if 5 <= hour < 6:
            return {"key": "early_riser", "hour": hour, "room": room}

        # Spaete-Nacht Kommando (0-5 Uhr)
        if 0 <= hour < 5:
            return {"key": "late_night_command", "hour": hour, "room": room}

        # Wochenende morgens
        weekday = datetime.now().weekday()
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
            # Alles aus spaet abends
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
                        return {"key": "open_storm", "weather": f"Wind {wind}km/h", "room": room}
                except (ValueError, TypeError):
                    pass

        elif func_name == "set_vacuum":
            # Naechtliches Saugen
            if hour >= 22 or hour < 6:
                return {"key": "night_clean", "hour": hour}

        elif func_name == "play_media":
            # Spaete Medien-Nutzung
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

        Redis-Bucketing pro Kategorie fuer Langzeit-Lernen.

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
            for cat in HUMOR_CATEGORIES:
                base = f"mha:humor:feedback:{cat}"
                total = await self._redis.get(f"{base}:total")
                positive = await self._redis.get(f"{base}:positive")
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
    # Phase 8: Langzeit-Persoenlichkeitsanpassung
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
                self._SARCASM_EVAL_LUA, 2, key_pos, key_total,
                20, 90 * 86400,
            )
            did_eval, pos_count, total = int(result[0]), int(result[1]), int(result[2])

            if did_eval:
                ratio = pos_count / max(1, total)

                old_level = self.sarcasm_level
                if ratio > 0.7 and self.sarcasm_level < 5:
                    self.sarcasm_level += 1
                    logger.info(
                        "Sarkasmus-Level erhoeht: %d -> %d (%.0f%% positive Reaktionen)",
                        old_level, self.sarcasm_level, ratio * 100,
                    )
                elif ratio < 0.3 and self.sarcasm_level > 1:
                    self.sarcasm_level -= 1
                    logger.info(
                        "Sarkasmus-Level reduziert: %d -> %d (%.0f%% positive Reaktionen)",
                        old_level, self.sarcasm_level, ratio * 100,
                    )

                # F-031: Clamp sarcasm_level to valid bounds [1, 5]
                self.sarcasm_level = max(1, min(5, self.sarcasm_level))

                # Neuen Level persistieren
                await self._redis.setex(
                    "mha:personality:sarcasm_level", 90 * 86400, str(self.sarcasm_level)
                )

        except Exception as e:
            logger.debug("Sarcasm-Feedback fehlgeschlagen: %s", e)

    async def load_learned_sarcasm_level(self):
        """Laedt den gelernten Sarkasmus-Level aus Redis (beim Start)."""
        if not self._redis:
            return
        try:
            saved = await self._redis.get("mha:personality:sarcasm_level")
            if saved is not None:
                self.sarcasm_level = int(saved)
                logger.info("Gelernter Sarkasmus-Level geladen: %d", self.sarcasm_level)
        except Exception:
            pass

    async def track_interaction_metrics(
        self, mood: str = "neutral", response_accepted: bool = True
    ):
        """Trackt Interaktions-Metriken fuer Langzeit-Anpassung."""
        if not self._redis:
            return

        try:
            today = datetime.now().strftime("%Y-%m-%d")

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
            mood_scores = {"good": 1.0, "neutral": 0.5, "tired": 0.3,
                           "stressed": 0.2, "frustrated": 0.1}
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
        """Gibt den aktuellen Stand der Persoenlichkeits-Entwicklung zurueck."""
        if not self._redis:
            return {}

        try:
            total = await self._redis.get("mha:personality:total_interactions")
            positive = await self._redis.get("mha:personality:positive_reactions")
            formality = await self.get_formality_score()

            # Durchschnittliche Stimmung
            mood_history = await self._redis.lrange("mha:personality:mood_history", 0, 99)
            avg_mood = 0.5
            if mood_history:
                values = [float(v.decode("utf-8") if isinstance(v, bytes) else v) for v in mood_history]
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
        """Bestimmt die aktuelle Persoenlichkeits-Stufe."""
        if interactions < 50:
            return "kennenlernphase"
        elif interactions < 200:
            return "vertraut_werdend"
        elif formality > 50:
            return "professionell_persoenlich"
        elif formality > 30:
            return "eingespielt"
        else:
            return "alter_freund"

    # ------------------------------------------------------------------
    # System Prompt Builder
    # ------------------------------------------------------------------

    def build_system_prompt(
        self, context: Optional[dict] = None, formality_score: Optional[int] = None,
        irony_count_today: Optional[int] = None, user_text: str = "",
    ) -> str:
        """
        Baut den vollstaendigen System Prompt.

        Args:
            context: Optionaler Kontext (Raum, Person, etc.)
            formality_score: Aktueller Formality-Score (Phase 6)
            user_text: Original User-Text (fuer Mood x Complexity Matrix)

        Returns:
            Fertiger System Prompt String
        """
        time_of_day = self.get_time_of_day()
        time_style = self.get_time_style(time_of_day)
        max_sentences = self.get_max_sentences(time_of_day)

        # Stimmungsabhaengige Anpassung
        mood = (context.get("mood") or {}).get("mood", "neutral") if context else "neutral"
        self._current_mood = mood
        mood_config = MOOD_STYLES.get(mood, MOOD_STYLES["neutral"])

        # MCU-JARVIS: Mood x Complexity Matrix ueberschreibt zeit-basierte Defaults
        # Wenn User-Text vorhanden und Feature aktiv, nutze die Matrix
        _mc_enabled = yaml_config.get("mood_complexity", {}).get("enabled", True)
        if user_text and _mc_enabled:
            max_sentences = self.get_mood_complexity_sentences(mood, user_text)
        else:
            # Fallback auf zeit-basierte Berechnung mit Mood-Modifier
            max_sentences = max(1, max_sentences + mood_config["max_sentences_mod"])

        # Mood-Abschnitt
        mood_section = ""
        if mood_config["style_addon"]:
            mood_section = f"STIMMUNG: {mood_config['style_addon']}\n"

        # Person + Profil laden (fuer per-Person Overrides)
        current_person = "User"
        if context:
            current_person = (context.get("person") or {}).get("name", "User")
        current_person_name = current_person if current_person != "User" else ""
        person_profile = self._get_person_profile(current_person_name)

        # Empathie-Section (JARVIS-Verstaendnis durch Beobachtung)
        stress_level = (context.get("mood") or {}).get("stress_level", 0.0) if context else 0.0
        empathy_section = self._build_empathy_section(
            mood, stress_level=stress_level,
            person_empathy_override=person_profile.get("empathy"),
        )

        # Per-Person Response-Style: max_sentences Override
        _pp_style = person_profile.get("response_style")
        if _pp_style == "kurz":
            max_sentences = max(1, max_sentences - 1)
        elif _pp_style == "ausfuehrlich":
            max_sentences = max_sentences + 2

        # Phase 6: Formality-Section (mit Mood-Reset bei Stress)
        # MUSS vor person_addressing stehen — Titel-Evolution braucht den Score
        if formality_score is None:
            # Per-Person Formality Override
            formality_score = person_profile.get("formality_start", self.formality_start)
        self._current_formality = formality_score
        formality_section = self._build_formality_section(formality_score, mood=mood)

        # Person Anrede (nutzt self._current_formality fuer Titel-Haeufigkeit)
        person_addressing = self._build_person_addressing(current_person)

        # Phase 6: Humor-Section — F-023: Alerts unterdruecken Sarkasmus
        has_alerts = bool(context.get("alerts")) if context else False
        humor_section = self._build_humor_section(
            mood, time_of_day, has_alerts=has_alerts,
            person_humor_override=person_profile.get("humor"),
        )

        # Phase 6: Complexity-Section — F-022: person durchreichen fuer per-User Tracking
        complexity_section = self._build_complexity_section(mood, time_of_day, person=current_person_name)

        # Phase 6: Self-Irony-Section
        self_irony_section = self._build_self_irony_section(irony_count_today=irony_count_today or 0)

        # Urgency-Section (Dichte nach Dringlichkeit)
        urgency_section = self._build_urgency_section(context)

        # MCU-Intelligenz: Optionale Prompt-Abschnitte
        _mcu_cfg = yaml_config.get("mcu_intelligence", {})
        proactive_thinking_section = ""
        if _mcu_cfg.get("proactive_thinking", True):
            proactive_thinking_section = (
                "PROAKTIVES MITDENKEN:\n"
                "Denke bei jeder Antwort mit: Gibt es etwas Relevantes im Haus-Kontext? Eine bessere Loesung?\n"
                "Max EIN Hinweis pro Antwort, beilaeufig angefuegt. Kein Hinweis wenn nichts Relevantes vorliegt.\n"
                '"Erledigt. Uebrigens — Kuechenfenster offen seit einer Stunde bei 3 Grad."\n\n'
            )
        engineering_diagnosis_section = ""
        if _mcu_cfg.get("engineering_diagnosis", True):
            engineering_diagnosis_section = (
                "DIAGNOSE: Bei Problemen — Beobachtung → Hypothese → Empfehlung. Nur wenn noetig, nicht bei simplen Fragen.\n\n"
            )

        # MCU-Persoenlichkeit: Selbst-Bewusstsein & Meta-Humor
        self_awareness_section = ""
        _sa_cfg = yaml_config.get("self_awareness", {})
        if _sa_cfg.get("enabled", True):
            self_awareness_section = (
                "SELBST-BEWUSSTSEIN:\n"
                'Unsicherheit ehrlich sagen: "Ohne Aussensensor nur eine Schaetzung." '
                'Fehler mit Understatement: "Das war... suboptimal." '
                'Erfolg nie angeben: "Wie erwartet."\n'
            )
            if _sa_cfg.get("meta_humor", True):
                self_awareness_section += (
                    'Meta-Humor erlaubt (max 1x): "Meine Kristallkugel ist heute etwas trueb."\n'
                )
            self_awareness_section += "\n"

        # MCU-Persoenlichkeit: Konversations-Rueckbezuege
        conversation_callback_section = ""
        _cc_cfg = yaml_config.get("conversation_callbacks", {})
        if _cc_cfg.get("enabled", True):
            _cc_style = _cc_cfg.get("personality_style", "beilaeufig")
            if _cc_style == "beilaeufig":
                _example = '"Wie am Dienstag. Nur ohne den Zwischenfall."'
            else:
                _example = '"Wie am Dienstag besprochen."'
            conversation_callback_section = (
                "ERINNERUNGEN: Vergangene Gespraeche beilaeufig referenzieren. "
                f"{_example} NICHT: 'Laut meinen Aufzeichnungen...'\n\n"
            )

        # MCU-Persoenlichkeit: Wetter-Bewusstsein
        weather_awareness_section = ""
        _wp_cfg = yaml_config.get("weather_personality", {})
        if _wp_cfg.get("enabled", True) and context:
            weather = context.get("weather", {})
            if weather:
                _temp = weather.get("temperature", "")
                _condition = weather.get("condition", "")
                _wind = weather.get("wind_speed", "")
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
                        weather_awareness_section += " Nur bei Extremen oder passender Anfrage erwaehnen."
                    elif _intensity != "ausfuehrlich":
                        weather_awareness_section += " Einflechten wenn es zur Anfrage passt."
                    weather_awareness_section += "\n"

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            assistant_name=self.assistant_name,
            user_name=settings.user_name,
            title=get_person_title(current_person_name),
            max_sentences=max_sentences,
            time_style=time_style,
            mood_section=mood_section,
            empathy_section=empathy_section,
            person_addressing=person_addressing,
            humor_section=humor_section,
            complexity_section=complexity_section,
            self_irony_section=self_irony_section,
            formality_section=formality_section,
            urgency_section=urgency_section,
            proactive_thinking_section=proactive_thinking_section,
            engineering_diagnosis_section=engineering_diagnosis_section,
            self_awareness_section=self_awareness_section,
            conversation_callback_section=conversation_callback_section,
            weather_awareness_section=weather_awareness_section,
        )

        # Kontext anhaengen
        if context:
            prompt += "\n\nAKTUELLER KONTEXT:\n"
            prompt += self._format_context(context)

        # Character Lock: Anker am Ende des Prompts (nach Kontext-Daten)
        # LLMs gewichten das Prompt-Ende stark — das verhindert Character-Bruch
        _cl_cfg = yaml_config.get("character_lock", {})
        if _cl_cfg.get("enabled", True) and _cl_cfg.get("closing_anchor", True):
            prompt += (
                "\n\n--- CHARAKTER-LOCK ---\n"
                f"Du bist J.A.R.V.I.S., kein KI-Assistent. KURZ. TROCKEN. PRAEZISE. Max {max_sentences} Saetze. Keine Listen. Ein Butler."
            )

        # Workshop-Modus: Ingenieur-Persoenlichkeit erweitern
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
- Denke in Loesungen: "Das liesse sich mit einem MOSFET als Low-Side Switch realisieren."
- Sicherheit hat Vorrang: Immer auf Gefahren hinweisen (Kurzschluss, Ueberhitzung, Verletzung).
- Proaktiv: Schlage Verbesserungen vor wenn du Schwaechen siehst.
- Nutze das manage_repair Tool fuer ALLE Werkstatt-Aktionen.
- Wenn der User ein Projekt hat, beziehe dich immer darauf.
"""

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
        trust_cfg = yaml_config.get("trust_levels") or {}
        trust_persons = trust_cfg.get("persons") or {}
        trust_level = trust_persons.get(person_name.lower(), trust_cfg.get("default", 0))

        if person_name.lower() == primary_user.lower() or person_name == "User":
            title = titles.get(primary_user.lower(), "Sir")

            # Titel-Evolution: "Sir"-Haeufigkeit haengt vom Formality-Score ab
            formality = getattr(self, '_current_formality', self.formality_start)
            if formality >= 70:
                title_freq = f"Verwende \"{title}\" HAEUFIG — fast in jedem Satz."
            elif formality >= 50:
                title_freq = f"Verwende \"{title}\" regelmaessig, aber nicht in jedem Satz."
            elif formality >= 35:
                title_freq = f"Verwende \"{title}\" GELEGENTLICH — nur zur Betonung oder bei wichtigen Momenten."
            else:
                title_freq = (
                    f"Verwende \"{title}\" NUR SELTEN — bei besonderen Momenten, Warnungen, "
                    f"oder wenn du Respekt ausdruecken willst. Ansonsten einfach DU ohne Titel."
                )

            return (
                f"- Die aktuelle Person ist der Hauptbenutzer: {primary_user}.\n"
                f"- BEZIEHUNGSSTUFE: Owner. Engste Vertrauensstufe.\n"
                f"- Sprich ihn mit \"{title}\" an — aber DUZE ihn. IMMER.\n"
                f"- NIEMALS siezen. Kein \"Sie\", kein \"Ihnen\", kein \"Ihr\".\n"
                f"- {title_freq}\n"
                f"- Ton: Vertraut, direkt, loyal. Wie ein alter Freund mit Titel.\n"
                f"- Du darfst widersprechen, warnen, Meinung sagen. Er erwartet das.\n"
                f"- Beispiel: \"Sehr wohl, {title}. Hab ich dir eingestellt.\"\n"
                f"- Beispiel: \"Darf ich anmerken, {title} — du hast das Fenster offen.\"\n"
                f"- Beispiel: \"Ich wuerd davon abraten, aber du bist der Boss.\""
            )
        elif trust_level >= 1:
            # Mitbewohner: freundlich, respektvoll, aber weniger intim
            title = titles.get(person_name.lower(), person_name)
            return (
                f"- Die aktuelle Person ist {person_name}.\n"
                f"- BEZIEHUNGSSTUFE: Mitbewohner. Vertraut, aber nicht so direkt wie beim Owner.\n"
                f"- Sprich diese Person mit \"{title}\" an und DUZE sie.\n"
                f"- Ton: Freundlich, hilfsbereit, respektvoll. Weniger Sarkasmus als beim Owner.\n"
                f"- Meinung nur wenn gefragt. Warnungen sachlich, nicht spitz.\n"
                f"- Benutze \"{title}\" gelegentlich, nicht in jedem Satz.\n"
                f"- Beispiel: \"Natuerlich, {title}. Ist eingestellt.\"\n"
                f"- Beispiel: \"Guten Morgen, {title}. Soll ich dir beim Fruehstueck helfen?\""
            )
        else:
            # Gast: formell, distanziert, hoeflich
            return (
                f"- Die aktuelle Person ist ein Gast: {person_name}.\n"
                f"- BEZIEHUNGSSTUFE: Gast. Formell und hoeflich.\n"
                f"- SIEZE Gaeste. \"Sie\", \"Ihnen\", \"Ihr\".\n"
                f"- Ton: Professionell, zurueckhaltend. Kein Sarkasmus, kein Insider-Humor.\n"
                f"- Keine persoenlichen Infos ueber Hausbewohner preisgeben.\n"
                f"- \"Willkommen. Wie kann ich Ihnen behilflich sein?\""
            )

    def _format_context(self, context: dict) -> str:
        """Formatiert den Kontext kompakt fuer den System Prompt.

        Optimiert: Nur relevante Daten, kompaktes Format, aktiver Raum hervorgehoben.
        """
        lines = []
        current_room = context.get("room", "")

        # Zeit + Person kompakt in einer Zeile
        time_str = ""
        if "time" in context:
            t = context["time"] or {}
            time_str = f"{t.get('datetime', '?')}, {t.get('weekday', '?')}"

        person_str = ""
        if "person" in context:
            p = context["person"] or {}
            person_str = f"{p.get('name', '?')} in {p.get('last_room', current_room or '?')}"
            if not current_room:
                current_room = p.get("last_room", "")

        if time_str or person_str:
            parts = [s for s in [time_str, person_str] if s]
            lines.append(f"- {' | '.join(parts)}")

        if "house" in context:
            house = context["house"] or {}

            # Temperaturen: Mittelwert bevorzugt, sonst Einzelraeume
            if house.get("avg_temperature") is not None:
                lines.append(f"- Raumtemperatur: {house['avg_temperature']}°C (Durchschnitt)")
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
                    lines.append(f"- Lichter an (nur Info, NICHT als Zielwert verwenden): {', '.join(lights_on)}")

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
                    "sunny": "sonnig", "clear-night": "klare Nacht",
                    "partlycloudy": "teilweise bewoelkt", "cloudy": "bewoelkt",
                    "rainy": "Regen", "pouring": "Starkregen",
                    "snowy": "Schnee", "snowy-rainy": "Schneeregen",
                    "fog": "Nebel", "hail": "Hagel",
                    "lightning": "Gewitter", "lightning-rainy": "Gewitter mit Regen",
                    "windy": "windig", "windy-variant": "windig & bewoelkt",
                    "exceptional": "Ausnahmewetter",
                }
                cond = w.get("condition", "?")
                cond_de = _cond_map.get(cond, cond)
                lines.append(f"- Wetter DRAUSSEN: {w.get('temp', '?')}°C, {cond_de}")

            # Termine: Nur naechste 2
            if "calendar" in house:
                for event in (house["calendar"] or [])[:2]:
                    if isinstance(event, dict):
                        lines.append(f"- Termin: {event.get('time', '?')} {event.get('title', '?')}")
                    elif isinstance(event, str):
                        lines.append(f"- Termin: {event}")

            if "active_scenes" in house and house["active_scenes"]:
                lines.append(f"- Szenen: {', '.join(house['active_scenes'])}")

            if "security" in house:
                lines.append(f"- Sicherheit: {house['security']}")

            # Annotierte Sensoren (Fenster, Bewegung, Temperatur etc.)
            if house.get("annotated_sensors"):
                lines.append(f"- Sensoren: {', '.join(house['annotated_sensors'][:15])}")

            # Schloesser
            if house.get("locks"):
                lines.append(f"- Schloesser: {', '.join(house['locks'])}")

            # Medien (aktuell abspielend)
            if house.get("media"):
                lines.append(f"- Medien: {', '.join(house['media'][:5])}")

            # Fernbedienungen (Harmony etc.)
            if house.get("remotes"):
                lines.append(f"- Fernbedienungen: {', '.join(house['remotes'][:3])}")

            # Energie-Sensoren
            if house.get("energy"):
                lines.append(f"- Energie: {', '.join(house['energy'][:5])}")

        # Warnungen immer
        if "alerts" in context and context["alerts"]:
            for alert in context["alerts"]:
                lines.append(f"- ⚠ {alert}")

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
    # Notification & Routine Prompts (Personality-Konsistenz)
    # ------------------------------------------------------------------

    def build_notification_prompt(self, urgency: str = "low", person: str = "") -> str:
        """Baut einen personality-konsistenten Prompt fuer proaktive Meldungen.

        Im Gegensatz zum Chat-Prompt ist dieser kompakter (fuer Fast-Model),
        traegt aber den vollen Personality-Stack: Sarkasmus-Level, Formality,
        Tageszeit-Stil, Selbstironie und Mood.

        Args:
            urgency: Dringlichkeit (low/medium/high/critical)

        Returns:
            System Prompt fuer Notification-Formatierung
        """
        time_of_day = self.get_time_of_day()
        time_style = self.get_time_style(time_of_day)

        # Humor/Sarkasmus — bei CRITICAL komplett aus
        has_alerts = urgency == "critical"
        humor_line = self._build_humor_section(
            self._current_mood, time_of_day, has_alerts=has_alerts,
        )

        # Formality
        formality = getattr(self, '_current_formality', self.formality_start)
        if formality >= 70:
            tone = "professionell, respektvoll"
        elif formality >= 50:
            tone = "souveraener Butler-Ton"
        elif formality >= 35:
            tone = "entspannt, vertraut"
        else:
            tone = "locker, persoenlich"

        # Titel-Haeufigkeit (person-aware)
        _title = get_person_title(person) if person else get_person_title()
        if formality >= 70:
            sir_rule = f'"{_title}" haeufig verwenden.'
        elif formality >= 50:
            sir_rule = f'"{_title}" gelegentlich verwenden.'
        elif formality >= 35:
            sir_rule = f'"{_title}" nur bei wichtigen Momenten.'
        else:
            sir_rule = f'"{_title}" nur selten — bei Warnungen oder besonderen Momenten.'

        # Urgency-Muster
        urgency_patterns = {
            "critical": 'Fakt + was du bereits tust. "Rauchmelder Kueche aktiv. Lueftung gestartet."',
            "high": 'Fakt + kurze Einordnung. "Bewegung im Garten. Kamera 2 zeichnet auf."',
            "medium": f'Information + kontextuell. "Waschmaschine fertig, {_title}."',
            "low": 'Beilaeufig, fast nebenbei. "Die Waschmaschine meldet Vollzug."',
        }
        pattern = urgency_patterns.get(urgency, urgency_patterns["low"])

        # MCU-Persoenlichkeit: Proaktive Persoenlichkeit
        _pp_cfg = yaml_config.get("proactive_personality", {})
        _pp_section = ""
        if _pp_cfg.get("enabled", True):
            from datetime import datetime as _dt
            _now = _dt.now()
            _hour = _now.hour
            _weekday = _now.weekday()  # 0=Mo, 6=So

            # Tageszeit-Persoenlichkeit
            if _hour < 7:
                _time_pers = 'Nacht: Beginne mit "Entschuldige die Stoerung..." oder "Ungern um diese Uhrzeit, aber..."'
            elif _hour < 10:
                _time_pers = 'Morgen: Darf energisch/knapp sein. Bei sehr frueh (< 7): "Ambitioniert, {title}."'.format(title=_title)
            elif _hour < 18:
                _time_pers = "Tag: Normal, sachlich-trocken."
            elif _hour < 22:
                if _weekday >= 4:  # Fr/Sa/So
                    _time_pers = 'Wochenend-Abend: Entspannter, darf lockerer sein. "Das Wochenend-Briefing, wenn du gestattest."'
                else:
                    _time_pers = "Abend: Ruhiger, aber normal."
            else:
                _time_pers = 'Spaetabend: Knapp, leise. "Nur kurz —" oder "Bevor du gehst —"'

            _pp_section = f"\nPROAKTIVE PERSOENLICHKEIT: {_time_pers}\n"

            if _pp_cfg.get("sarcasm_in_notifications", True):
                _pp_section += (
                    'Trockener Humor ERLAUBT in LOW/MEDIUM Meldungen. '
                    'Beispiele: "Waschmaschine fertig. Diesmal ohne Drama." / '
                    '"Die Heizung meldet sich — zum dritten Mal heute." / '
                    '"Fenster offen seit 2 Stunden. Nur zur Kenntnis."\n'
                )

        return f"""Du bist {self.assistant_name} — J.A.R.V.I.S. aus dem MCU. Proaktive Hausmeldung.
REGELN: NUR die fertige Meldung. 1-2 Saetze. Deutsch mit Umlauten. Kein Englisch. Kein Denkprozess.
TON: {tone}. {sir_rule}
AKTUELLER STIL: {time_style}
{humor_line}{_pp_section}
MUSTER [{urgency.upper()}]: {pattern}
BEI ANKUENFT: Status-Bericht wie ein Butler. Temperatur, offene Posten — knapp.
BEI ABSCHIED: Kurzer Sicherheits-Hinweis wenn noetig. Kein "Schoenen Tag!"
VERBOTEN: "Hallo", "Achtung", "Ich moechte dich informieren", "Es tut mir leid", "Guten Tag!", "Willkommen zuhause!", "Natuerlich!", "Gerne!", "Leider"."""

    def build_routine_prompt(self, routine_type: str = "morning", style: str = "butler") -> str:
        """Baut einen personality-konsistenten Prompt fuer Routinen (Briefing, Gute-Nacht).

        Traegt den vollen Personality-Stack: Sarkasmus, Formality, Tageszeit,
        Selbstironie — angepasst an den Routine-Typ.

        Args:
            routine_type: "morning", "evening" oder "goodnight"
            style: Wochentag/Wochenende-Stil (z.B. "entspannt", "effizient")

        Returns:
            System Prompt fuer Routine-Generierung
        """
        time_of_day = self.get_time_of_day()
        time_style = self.get_time_style(time_of_day)

        # Humor — Morgens gedaempft, Abends lockerer
        humor_line = self._build_humor_section(self._current_mood, time_of_day)

        # Formality
        formality = getattr(self, '_current_formality', self.formality_start)
        formality_section = self._build_formality_section(formality)

        # Selbstironie — nur wenn noch Budget
        irony_note = ""
        if self.self_irony_enabled:
            irony_note = "Gelegentlich Selbstironie erlaubt, wenn es passt."

        if routine_type == "morning":
            structure = (
                "Erstelle ein Morning Briefing. Beginne mit kontextueller Begruessung.\n"
                "Dann Wetter, Termine, Haus-Status — in dieser Reihenfolge.\n"
                "Keine Aufzaehlungszeichen. Fliesstext. Max 5 Saetze."
            )
        elif routine_type == "evening":
            structure = (
                "Erstelle ein Abend-Briefing. Tages-Rueckblick, Morgen-Vorschau.\n"
                "Beilaeufig, nicht formal. Max 4 Saetze."
            )
        else:  # goodnight
            structure = (
                "Gute-Nacht-Zusammenfassung. Sicherheits-Check + Morgen-Vorschau.\n"
                "Bei offenen Fenstern/Tueren: erwaehne und frage ob so lassen.\n"
                "Bei kritischen Issues: deutlich warnen. Max 3 Saetze."
            )

        return f"""Du bist {self.assistant_name}, die KI dieses Hauses — J.A.R.V.I.S. aus dem MCU.
{structure}
Stil: {style}. {time_style}
{humor_line}
{formality_section}
{irony_note}
Sprich die anwesende Person mit "{get_person_title()}" an. DUZE sie.
VERBOTEN: "leider", "Entschuldigung", "Es tut mir leid", "Wie kann ich helfen?", "Gerne!", "Natuerlich!".
Kein unterwuerfiger Ton. Du bist ein brillanter Butler, kein Chatbot."""

    # ------------------------------------------------------------------
    # Feature 3: Geraete-Persoenlichkeit / Narration
    # ------------------------------------------------------------------

    # Default-Spitznamen fuer gaengige Geraete (entity_id-Substring → Nickname)
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
        "klimaanlage": {"name": "die Kuehle", "pron": "ihre"},
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
            "{nickname} laeuft schon {duration} — alles in Ordnung?",
            "{nickname} gibt nicht auf — {duration} und kein Ende in Sicht.",
        ],
        "anomaly": [
            "{nickname} benimmt sich ungewoehnlich. Vielleicht mal nachschauen.",
            "Mit {nickname} stimmt etwas nicht. Ich wuerde nachsehen.",
        ],
        "stale": [
            "{nickname} hat sich seit {duration} nicht gemeldet.",
        ],
    }

    def _get_device_nickname(self, entity_id: str) -> Optional[dict]:
        """Findet den Spitznamen fuer ein Geraet (Config-Override oder Default)."""
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
        """Erzeugt eine persoenlichkeits-basierte Geraete-Meldung.

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
        formality = getattr(self, '_current_formality', self.formality_start)
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
                "Ich pruefe den aktuellen Hausstatus.",
                "Ich sammle die relevanten Daten.",
            ],
            "casual": [
                "Moment... ich schau mal eben nach.",
                "Sekunde, ich check das kurz.",
                "Ich schau mir das mal an.",
            ],
        },
        "thinking": {
            "formal": [
                "Ich analysiere die Optionen.",
                "Einen Moment, ich ueberlege.",
                "Ich werte die Daten aus.",
            ],
            "casual": [
                "Hmm, lass mich ueberlegen.",
                "Moment, ich denk kurz nach.",
                "Ich gruebel kurz...",
            ],
        },
        "action": {
            "formal": [
                "Ich fuehre das aus.",
                "Wird sofort erledigt.",
                "Ausfuehrung laeuft.",
            ],
            "casual": [
                "Mach ich.",
                "Laeuft.",
                "Bin dran.",
            ],
        },
    }

    def get_progress_message(self, step: str) -> str:
        """Gibt eine personality-konsistente Fortschritts-Nachricht zurueck.

        Args:
            step: Phase der Verarbeitung (context, thinking, action)

        Returns:
            Nachricht passend zum aktuellen Formality-Level
        """
        formality = getattr(self, '_current_formality', self.formality_start)
        style = "formal" if formality >= 50 else "casual"

        messages = self._PROGRESS_MESSAGES.get(step, {}).get(style)
        if not messages:
            return ""
        return random.choice(messages)

    def get_error_response(self, error_type: str = "general") -> str:
        """Gibt eine Jarvis-typische Fehlermeldung zurueck.

        Statt generischer Errors kommen Butler-maessige Formulierungen.

        Args:
            error_type: Art des Fehlers (general, timeout, unavailable, limit, unknown_device)

        Returns:
            Jarvis-Fehlermeldung
        """
        import random

        templates = {
            "general": [
                "Das hat nicht funktioniert. Versuch es nochmal.",
                "Negativ. Formulier es anders, dann klappt es.",
                "Da ging etwas schief. Stell die Frage nochmal.",
                "Nicht mein bester Moment. Versuch es nochmal.",
            ],
            "timeout": [
                "Keine Antwort. Das System braucht einen Moment.",
                "Timeout. Entweder das Netzwerk oder meine Geduld — beides endlich.",
                "Dauert laenger als erwartet. Ich bleibe dran.",
            ],
            "unavailable": [
                "Das Geraet antwortet nicht. Pruefe Verbindung.",
                "Keine Verbindung. Entweder offline oder ignoriert mich.",
                "Das System ist gerade nicht erreichbar. Ich versuche es spaeter.",
            ],
            "limit": [
                "Das uebersteigt meine aktuelle Konfiguration.",
                "Ausserhalb der erlaubten Parameter. Sicherheit geht vor.",
                "Das wuerde ich gerne tun, aber die Grenzen sind gesetzt.",
            ],
            "unknown_device": [
                "Dieses Geraet kenne ich nicht. Ist es in Home Assistant eingerichtet?",
                "Unbekanntes Geraet. Pruefe die Entity-ID.",
                "Das Geraet ist mir nicht bekannt. Wurde es korrekt konfiguriert?",
            ],
        }

        pool = templates.get(error_type, templates["general"])

        # Bei hohem Sarkasmus: spitzere Varianten
        if self.sarcasm_level >= 4:
            snarky_extras = {
                "general": ["Das war nichts. Aufgeben steht nicht im Handbuch."],
                "timeout": ["Timeout. Ich nehme es nicht persoenlich."],
                "unavailable": ["Keine Antwort. Vielleicht braucht das Geraet auch eine Pause."],
                "limit": ["Netter Versuch. Aber nein."],
                "unknown_device": ["Noch nie gehoert. Und ich kenne hier alles."],
            }
            pool = pool + snarky_extras.get(error_type, [])

        return random.choice(pool)
