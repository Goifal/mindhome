"""
MindHome Koch-Assistent — Schritt-für-Schritt Kochunterstuetzung.

Features:
- Rezept-Generierung via LLM (Deep-Model)
- Schritt-für-Schritt Navigation per Sprache
- Software-Timer (kein HA-Timer nötig)
- Portionen anpassen
- Praeferenzen/Allergien aus Semantic Memory
- Rezepte im Gedaechtnis speichern
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .config import get_person_title

from .config import yaml_config

logger = logging.getLogger(__name__)


@dataclass
class CookingTimer:
    """Ein Software-Timer für Koch-Schritte."""
    label: str
    duration_seconds: int
    started_at: float = 0.0
    finished: bool = False

    def start(self):
        self.started_at = time.time()
        self.finished = False

    @property
    def remaining_seconds(self) -> int:
        if self.finished or self.started_at == 0:
            return 0
        elapsed = time.time() - self.started_at
        remaining = self.duration_seconds - elapsed
        return max(0, int(remaining + 0.5))

    @property
    def is_done(self) -> bool:
        if self.finished:
            return True
        return self.started_at > 0 and self.remaining_seconds <= 0

    def format_remaining(self) -> str:
        secs = self.remaining_seconds
        if secs <= 0:
            return "abgelaufen"
        minutes = secs // 60
        seconds = secs % 60
        if minutes > 0:
            return f"{minutes} Minuten und {seconds} Sekunden"
        return f"{seconds} Sekunden"


@dataclass
class CookingStep:
    """Ein einzelner Koch-Schritt."""
    number: int
    instruction: str
    timer_minutes: Optional[int] = None


@dataclass
class CookingSession:
    """Eine aktive Koch-Session mit Rezept und Schritten."""
    dish: str
    portions: int = 2
    ingredients: list[str] = field(default_factory=list)
    steps: list[CookingStep] = field(default_factory=list)
    current_step: int = 0
    timers: list[CookingTimer] = field(default_factory=list)
    started_at: float = 0.0
    person: str = ""
    raw_recipe: str = ""

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def is_finished(self) -> bool:
        return self.current_step >= self.total_steps

    def get_current_step(self) -> Optional[CookingStep]:
        if 0 <= self.current_step < self.total_steps:
            return self.steps[self.current_step]
        return None


# Koch-Intent Erkennung
COOKING_START_TRIGGERS = [
    "ich will", "ich möchte", "lass uns", "wir kochen",
    "wir backen", "hilf mir", "ich koche", "ich backe",
]

COOKING_KEYWORDS = [
    "kochen", "backen", "zubereiten", "braten", "grillen",
    "rezept für",
    "wie mache ich", "wie macht man", "wie bereite ich",
    "wie koche ich", "wie backe ich", "wie brate ich",
]

# Navigation per Sprache
NAV_NEXT = ["weiter", "nächster schritt", "next", "und dann",
            "was kommt jetzt", "wie gehts weiter"]
NAV_PREV = ["zurück", "vorheriger schritt", "nochmal den letzten"]
NAV_REPEAT = ["nochmal", "wiederhole", "wie war das", "sag das nochmal",
              "repeat", "bitte nochmal"]
NAV_STATUS = ["wo bin ich", "welcher schritt", "status", "übersicht"]
NAV_TIMER = ["timer", "stell timer", "stell einen timer", "weck mich",
             "erinner mich"]
NAV_TIMER_CHECK = ["wie lange noch", "timer status", "läuft der timer"]
NAV_STOP = ["stop kochen", "stopp kochen", "abbrechen", "koch session beenden",
            "fertig kochen", "ich bin fertig", "koch modus beenden",
            "kochen beenden", "kochmodus beenden", "beende kochen",
            "beende den koch", "kochen stopp", "kochen stop",
            "kochen beende", "beenden"]
NAV_INGREDIENTS = ["zutaten", "was brauche ich", "einkaufsliste",
                   "welche zutaten"]
NAV_PORTIONS = ["für", "portionen", "personen"]
NAV_SAVE = ["merk dir das rezept", "rezept speichern", "speichere das rezept",
            "merk dir dieses rezept"]


RECIPE_GENERATION_PROMPT = """Du bist ein erfahrener Koch-Assistent. Erstelle ein Rezept auf Deutsch.

WICHTIG: Antworte NUR im folgenden JSON-Format, KEIN anderer Text:

{{
  "dish": "Name des Gerichts",
  "portions": {portions},
  "ingredients": [
    "200g Spaghetti",
    "100g Guanciale"
  ],
  "steps": [
    {{"number": 1, "instruction": "Wasser in einem grossen Topf zum Kochen bringen und salzen.", "timer_minutes": null}},
    {{"number": 2, "instruction": "Spaghetti ins kochende Wasser geben.", "timer_minutes": 8}},
    {{"number": 3, "instruction": "Guanciale in Streifen schneiden und in einer Pfanne knusprig braten.", "timer_minutes": 5}}
  ]
}}

Regeln:
- Klare, kurze Schritte (1-2 Sätze pro Schritt)
- timer_minutes nur wenn der Schritt eine Wartezeit hat (sonst null)
- Mengenangaben in metrischen Einheiten (Gramm, Liter, Essloeffel)
- Maximal {max_steps} Schritte
- Portionen: {portions}
{preferences}

Erstelle das Rezept für: {dish}"""


STORED_RECIPE_PARSE_PROMPT = """Du bist ein Koch-Assistent. Du hast ein bestehendes Rezept erhalten.
Wandle es in das folgende JSON-Format um. Passe die Mengen auf {portions} Portionen an.
{preferences}

WICHTIG: Antworte NUR im JSON-Format:
{{
  "dish": "Name des Gerichts",
  "portions": {portions},
  "ingredients": ["200g Zutat1", "100ml Zutat2"],
  "steps": [
    {{"number": 1, "instruction": "Schritt 1...", "timer_minutes": null}},
    {{"number": 2, "instruction": "Schritt 2...", "timer_minutes": 5}}
  ]
}}

Bestehendes Rezept:
{recipe_text}"""


MAX_TIMERS_PER_SESSION = 50  # Bug #117: Limit active timers per session


class CookingAssistant:
    """Koch-Assistent mit Schritt-für-Schritt Fuehrung."""

    REDIS_SESSION_KEY = "mha:cooking:session"
    REDIS_SESSION_TTL = 6 * 3600  # 6h — Session überlebt Neustart

    def __init__(self, ollama_client, semantic_memory=None):
        self.ollama = ollama_client
        self.semantic_memory = semantic_memory
        self.recipe_store = None  # set by Brain after init
        self.redis = None
        self.session: Optional[CookingSession] = None
        self._timer_tasks: list[asyncio.Task] = []
        self._notify_callback = None

        # Config aus settings.yaml lesen
        cook_cfg = yaml_config.get("cooking", {})
        self.enabled = cook_cfg.get("enabled", True)
        self.default_portions = int(cook_cfg.get("default_portions", 2))
        self.max_steps = int(cook_cfg.get("max_steps", 12))
        self.max_tokens = int(cook_cfg.get("max_tokens", 1024))
        self.timer_notify_tts = cook_cfg.get("timer_notify_tts", True)

    async def initialize(self, redis_client=None):
        """Initialisiert mit Redis und lädt ggf. eine gespeicherte Session."""
        self.redis = redis_client
        if self.redis:
            await self._restore_session()

    def set_notify_callback(self, callback):
        """Setzt den Callback für Timer-Benachrichtigungen."""
        self._notify_callback = callback

    @property
    def has_active_session(self) -> bool:
        return self.session is not None and not self.session.is_finished

    def is_cooking_intent(self, text: str) -> bool:
        """Erkennt ob der User kochen will."""
        if not self.enabled:
            return False
        text_lower = text.lower().strip()

        # Stopp-Phrasen ausschliessen – "kochen beende" ist kein Koch-Start
        if any(kw in text_lower for kw in NAV_STOP):
            return False

        # Direkte Rezept-Anfrage
        if any(kw in text_lower for kw in COOKING_KEYWORDS):
            return True

        # "Ich will X kochen/backen"
        if any(t in text_lower for t in COOKING_START_TRIGGERS):
            if any(kw in text_lower for kw in ["kochen", "backen", "zubereiten",
                                                 "braten", "grillen", "machen"]):
                return True

        return False

    def is_cooking_navigation(self, text: str) -> bool:
        """Erkennt ob der User durch ein aktives Rezept navigiert."""
        if not self.has_active_session:
            return False
        text_lower = text.lower().strip()
        all_nav = (NAV_NEXT + NAV_PREV + NAV_REPEAT + NAV_STATUS +
                   NAV_TIMER + NAV_TIMER_CHECK + NAV_STOP +
                   NAV_INGREDIENTS + NAV_PORTIONS + NAV_SAVE)
        return any(kw in text_lower for kw in all_nav)

    async def _search_recipe_store(self, dish: str) -> Optional[str]:
        """Durchsucht den Recipe Store nach einem passenden Rezept.

        Gibt den Rezept-Text zurück falls ein guter Treffer gefunden wird,
        sonst None.
        """
        if not self.recipe_store:
            return None

        try:
            rs_config = yaml_config.get("recipe_store", {})
            min_relevance = rs_config.get("min_relevance", 0.4)
            limit = rs_config.get("search_limit", 5)

            hits = await self.recipe_store.search(dish, limit=limit)
            good_hits = [h for h in hits if h.get("relevance", 0) >= min_relevance]

            if not good_hits:
                return None

            best = good_hits[0]
            logger.info(
                "Rezept aus Recipe Store gefunden: '%s' (Relevanz: %.2f, Quelle: %s)",
                dish, best.get("relevance", 0), best.get("source", "?"),
            )
            combined = "\n\n".join(h["content"] for h in good_hits)
            return combined
        except Exception as e:
            logger.warning("Recipe Store Suche fehlgeschlagen: %s", e)
            return None

    async def _parse_stored_recipe(
        self, recipe_text: str, dish: str, portions: int,
        person: str, model: str, preferences: str,
    ) -> Optional[CookingSession]:
        """Wandelt gespeicherten Rezepttext in strukturierte CookingSession um."""
        prompt = STORED_RECIPE_PARSE_PROMPT.format(
            portions=portions,
            preferences=preferences,
            recipe_text=recipe_text[:3000],
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Wandle das Rezept für {dish} um ({portions} Portionen)"},
        ]
        response = await self.ollama.chat(
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=self.max_tokens,
        )
        if "error" in response:
            logger.warning("Gespeichertes Rezept konnte nicht geparst werden: %s",
                           response["error"])
            return None

        content = response.get("message", {}).get("content", "")
        return self._parse_recipe(content, dish, portions, person)

    async def start_cooking(self, text: str, person: str, model: str) -> str:
        """Startet eine Koch-Session: Sucht zuerst im Recipe Store, dann LLM."""
        # Bestehende Session aufraumen (Zombie-Timer verhindern)
        if self.session:
            for task in self._timer_tasks:
                task.cancel()
            self._timer_tasks.clear()
        # Gericht aus Text extrahieren
        dish = self._extract_dish(text)
        if not dish:
            return "Was möchtest du kochen? Sag mir einfach das Gericht."

        # Portionen extrahieren (Default: 2)
        portions = self._extract_portions(text)

        # Praeferenzen + Recipe-Store parallel laden (spart ~50-200ms)
        preferences, stored_recipe = await asyncio.gather(
            self._load_preferences(person),
            self._search_recipe_store(dish),
        )

        logger.info("Koch-Session starten: '%s' für %d Portionen (Person: %s)",
                     dish, portions, person)
        if stored_recipe:
            session = await self._parse_stored_recipe(
                stored_recipe, dish, portions, person, model, preferences,
            )
            if session and session.steps:
                self.session = session
                self.session.started_at = time.time()
                await self._persist_session()

                parts = [f"Ein Rezept für {dish} liegt vor — {portions} Portionen."]
                if preferences:
                    parts.append("Deine Praeferenzen sind berücksichtigt.")
                parts.append(f"\nDu brauchst {len(session.ingredients)} Zutaten:")
                for ing in session.ingredients:
                    parts.append(f"  - {ing}")
                parts.append(f"\nDas Rezept hat {session.total_steps} Schritte.")
                parts.append("Sag 'weiter' wenn du bereit bist für den ersten Schritt.")
                parts.append("Du kannst jederzeit 'zutaten', 'nochmal', 'zurück' oder 'stop kochen' sagen.")
                return "\n".join(parts)
            logger.info("Gespeichertes Rezept nicht parsbar, Fallback auf LLM-Generierung")

        # Kein Treffer oder Parse fehlgeschlagen: Rezept via LLM generieren
        prompt = RECIPE_GENERATION_PROMPT.format(
            dish=dish,
            portions=portions,
            preferences=preferences,
            max_steps=self.max_steps,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Rezept für {dish}, {portions} Portionen"},
        ]

        response = await self.ollama.chat(
            messages=messages,
            model=model,
            temperature=0.7,
            max_tokens=self.max_tokens,
        )

        # Fallback-Kaskade: deep(32b) → smart(14b) → fast(8b)
        if "error" in response:
            from .config import settings
            fallback_chain = [settings.model_smart, settings.model_fast]
            for fallback_model in fallback_chain:
                if fallback_model == model:
                    continue
                logger.warning(
                    "Rezept-Generierung mit %s fehlgeschlagen (%s), "
                    "Fallback auf %s", model, response["error"], fallback_model,
                )
                response = await self.ollama.chat(
                    messages=messages,
                    model=fallback_model,
                    temperature=0.7,
                    max_tokens=self.max_tokens,
                )
                if "error" not in response:
                    break
                model = fallback_model  # für nächste Iteration im Log

        if "error" in response:
            error_detail = response["error"]
            logger.error("Rezept-Generierung fehlgeschlagen: %s", error_detail)
            if "Circuit Breaker" in str(error_detail):
                return "Ollama ist gerade nicht erreichbar. Bitte einen Moment warten und nochmal versuchen."
            if "Timeout" in str(error_detail):
                return f"Rezept-Generierung für {dish} hat zu lange gedauert. Bitte nochmal versuchen."
            return f"Rezept-Generierung für {dish} fehlgeschlagen. Bitte nochmal versuchen."

        content = response.get("message", {}).get("content", "")
        session = self._parse_recipe(content, dish, portions, person)

        if not session or not session.steps:
            logger.warning("Rezept-Parsing fehlgeschlagen für: %s", dish)
            return f"Rezept für {dish} nicht strukturierbar. Anderes Gericht empfohlen."

        self.session = session
        self.session.started_at = time.time()
        await self._persist_session()

        # Antwort zusammenbauen
        parts = [f"Sehr wohl — {dish} für {portions} Portionen."]

        if preferences:
            parts.append("Deine Praeferenzen sind berücksichtigt.")

        parts.append(f"\nDu brauchst {len(session.ingredients)} Zutaten:")
        for ing in session.ingredients:
            parts.append(f"  - {ing}")

        parts.append(f"\nDas Rezept hat {session.total_steps} Schritte.")
        parts.append("Sag 'weiter' wenn du bereit bist für den ersten Schritt.")
        parts.append("Du kannst jederzeit 'zutaten', 'nochmal', 'zurück' oder 'stop kochen' sagen.")

        return "\n".join(parts)

    async def handle_navigation(self, text: str) -> str:
        """Verarbeitet Navigation durch das aktive Rezept."""
        if not self.has_active_session:
            return "Es läuft gerade keine Koch-Session. Sag mir was du kochen willst!"

        text_lower = text.lower().strip()

        # Stop
        if any(kw in text_lower for kw in NAV_STOP):
            return await self._stop_session()

        # Rezept speichern
        if any(kw in text_lower for kw in NAV_SAVE):
            return await self._save_recipe()

        # Zutaten anzeigen
        if any(kw in text_lower for kw in NAV_INGREDIENTS):
            return self._show_ingredients()

        # Portionen ändern — nur wenn explizit eine Zahl mit Portionen/Personen genannt wird
        if any(kw in text_lower for kw in NAV_PORTIONS):
            new_portions = self._extract_explicit_portions(text)
            if new_portions > 0:
                return await self._adjust_portions(new_portions)

        # Timer setzen
        if any(kw in text_lower for kw in NAV_TIMER):
            return await self._set_timer_from_text(text)

        # Timer prüfen
        if any(kw in text_lower for kw in NAV_TIMER_CHECK):
            return self._check_timers()

        # Status
        if any(kw in text_lower for kw in NAV_STATUS):
            return self._show_status()

        # Nächster Schritt
        if any(kw in text_lower for kw in NAV_NEXT):
            return await self._next_step()

        # Vorheriger Schritt
        if any(kw in text_lower for kw in NAV_PREV):
            return await self._prev_step()

        # Wiederholen
        if any(kw in text_lower for kw in NAV_REPEAT):
            return self._repeat_step()

        return "Das habe ich nicht verstanden. Sag 'weiter', 'zurück', 'nochmal' oder 'status'."

    async def _next_step(self) -> str:
        """Geht zum nächsten Schritt."""
        session = self.session
        if session is None:
            return "Keine aktive Koch-Session. Sag mir was du kochen moechtest."

        session.current_step += 1
        await self._persist_session()
        step = session.get_current_step()

        if step is None:
            # Alle Schritte durch
            elapsed = int(time.time() - session.started_at) // 60
            return (f"Fertig! Alle {session.total_steps} Schritte abgeschlossen. "
                    f"Das hat etwa {elapsed} Minuten gedauert. "
                    f"Guten Appetit! Sag 'merk dir das rezept' wenn du es speichern willst.")

        response = f"Schritt {step.number} von {session.total_steps}:\n{step.instruction}"

        if step.timer_minutes:
            response += f"\n(Dieser Schritt dauert {step.timer_minutes} Minuten. Sag 'timer' wenn ich einen stellen soll.)"

        return response

    async def _prev_step(self) -> str:
        """Geht zum vorherigen Schritt."""
        if self.session is None:
            return "Keine aktive Koch-Session. Sag mir was du kochen moechtest."
        if self.session.current_step <= 0:
            return "Du bist schon beim ersten Schritt."

        self.session.current_step -= 1
        await self._persist_session()
        step = self.session.get_current_step()
        return f"Zurück zu Schritt {step.number} von {self.session.total_steps}:\n{step.instruction}"

    def _repeat_step(self) -> str:
        """Wiederholt den aktuellen Schritt."""
        if self.session is None:
            return "Keine aktive Koch-Session. Sag mir was du kochen moechtest."
        step = self.session.get_current_step()
        if step is None:
            return "Es gibt keinen aktuellen Schritt. Sag 'weiter' für den nächsten."
        return f"Nochmal Schritt {step.number}:\n{step.instruction}"

    def _show_status(self) -> str:
        """Zeigt den aktuellen Status."""
        session = self.session
        if session is None:
            return "Keine aktive Koch-Session. Sag mir was du kochen moechtest."
        step = session.get_current_step()
        elapsed = int(time.time() - session.started_at) // 60

        parts = [f"Koch-Session: {session.dish}"]
        parts.append(f"Portionen: {session.portions}")
        parts.append(f"Zeit: {elapsed} Minuten")

        if step:
            parts.append(f"Aktueller Schritt: {step.number} von {session.total_steps}")
            parts.append(f"  {step.instruction}")
        else:
            parts.append("Noch nicht gestartet. Sag 'weiter' für Schritt 1.")

        # Aktive Timer
        active_timers = [t for t in session.timers if not t.is_done]
        if active_timers:
            parts.append("\nAktive Timer:")
            for t in active_timers:
                parts.append(f"  - {t.label}: noch {t.format_remaining()}")

        return "\n".join(parts)

    def _show_ingredients(self) -> str:
        """Zeigt die Zutatenliste."""
        if not self.session.ingredients:
            return "Keine Zutaten gespeichert."

        parts = [f"Zutaten für {self.session.dish} ({self.session.portions} Portionen):"]
        for ing in self.session.ingredients:
            parts.append(f"  - {ing}")
        return "\n".join(parts)

    async def _adjust_portions(self, new_portions: int) -> str:
        """Passt die Portionen an (einfache Skalierung)."""
        if new_portions < 1 or new_portions > 20:
            return "Portionen muessen zwischen 1 und 20 liegen."

        old = self.session.portions
        if old == new_portions:
            return f"Es sind bereits {new_portions} Portionen."

        factor = new_portions / old
        self.session.portions = new_portions

        # Zutaten skalieren (einfache Regex für Zahlen am Anfang)
        new_ingredients = []
        for ing in self.session.ingredients:
            match = re.match(r"^(\d+(?:[.,]\d+)?)\s*(.*)", ing)
            if match:
                amount = float(match.group(1).replace(",", "."))
                rest = match.group(2)
                new_amount = amount * factor
                # Ganzzahlig wenn moeglich
                if new_amount == int(new_amount):
                    new_ingredients.append(f"{int(new_amount)} {rest}")
                else:
                    new_ingredients.append(f"{new_amount:.1f} {rest}")
            else:
                new_ingredients.append(ing)

        self.session.ingredients = new_ingredients
        await self._persist_session()
        ingredient_list = "\n".join(f"- {ing}" for ing in new_ingredients)
        return f"Portionen angepasst: {old} → {new_portions}.\n\nZutaten für {new_portions} Portionen:\n{ingredient_list}"

    async def _set_timer_from_text(self, text: str) -> str:
        """Setzt einen Timer basierend auf Text-Eingabe."""
        # Minuten extrahieren
        match = re.search(r"(\d+)\s*(?:minuten?|min)", text.lower())
        if not match:
            # Fallback: timer_minutes des aktuellen Schritts verwenden
            step = self.session.get_current_step() if self.session else None
            if step and step.timer_minutes:
                return await self._start_step_timer_with_response(step)
            return "Wie viele Minuten? Sag z.B. 'Timer 8 Minuten für die Pasta'."

        minutes = int(match.group(1))
        if minutes < 1 or minutes > 180:
            return "Timer muss zwischen 1 und 180 Minuten liegen."

        # Bug #117: Limit active timers per session
        active_timers = [t for t in self.session.timers if not t.is_done]
        if len(active_timers) >= MAX_TIMERS_PER_SESSION:
            return f"Maximale Anzahl aktiver Timer ({MAX_TIMERS_PER_SESSION}) erreicht. Warte bis ein Timer abläuft."

        # Label extrahieren
        label_match = re.search(r"(?:für|für)\s+(.+?)(?:\s*$)", text.lower())
        label = label_match.group(1) if label_match else f"Timer ({minutes} Min)"

        timer = CookingTimer(label=label, duration_seconds=minutes * 60)
        timer.start()
        self.session.timers.append(timer)

        # Hintergrund-Task für Benachrichtigung
        self._cleanup_completed_tasks()
        task = asyncio.create_task(self._timer_watcher(timer))
        self._timer_tasks.append(task)

        # Timer in Redis persistieren (für Neustart-Recovery)
        await self._persist_session()

        return f"Timer gesetzt: {label} — {minutes} Minuten. Ich sage Bescheid wenn er abgelaufen ist."

    async def _start_step_timer_with_response(self, step: CookingStep) -> str:
        """Startet einen Timer für einen Koch-Schritt und gibt Bestätigung zurück."""
        if not step.timer_minutes:
            return "Dieser Schritt hat keine Zeitangabe."

        # Bug #117: Limit active timers per session
        active_timers = [t for t in self.session.timers if not t.is_done]
        if len(active_timers) >= MAX_TIMERS_PER_SESSION:
            return f"Maximale Anzahl aktiver Timer ({MAX_TIMERS_PER_SESSION}) erreicht. Warte bis ein Timer abläuft."

        label = f"Schritt {step.number}"
        timer = CookingTimer(label=label, duration_seconds=step.timer_minutes * 60)
        timer.start()
        self.session.timers.append(timer)

        self._cleanup_completed_tasks()
        task = asyncio.create_task(self._timer_watcher(timer))
        self._timer_tasks.append(task)

        # Timer in Redis persistieren (für Neustart-Recovery)
        await self._persist_session()

        return f"Timer gesetzt: {label} — {step.timer_minutes} Minuten. Ich sage Bescheid wenn er abgelaufen ist."

    def _cleanup_completed_tasks(self):
        """Entfernt abgeschlossene oder abgebrochene Tasks aus _timer_tasks."""
        self._timer_tasks = [t for t in self._timer_tasks if not t.done()]

    async def _timer_watcher(self, timer: CookingTimer):
        """Überwacht einen Timer und benachrichtigt bei Ablauf."""
        try:
            remaining = timer.remaining_seconds
            if remaining <= 0 and timer.started_at == 0:
                # Timer wurde noch nicht gestartet — sollte nicht vorkommen,
                # aber Fallback auf volle Dauer statt sofortigem Ablauf
                remaining = timer.duration_seconds
            if remaining > 0:
                await asyncio.sleep(remaining)
            timer.finished = True
            message = f"{get_person_title()}, der Timer für '{timer.label}' ist abgelaufen!"
            logger.info("Koch-Timer abgelaufen: %s", timer.label)
            if self._notify_callback and self.timer_notify_tts:
                await self._notify_callback({"message": message, "type": "cooking_timer"})
        except asyncio.CancelledError:
            pass
        finally:
            # Bug #116: Clean up completed tasks to prevent unbounded growth
            self._cleanup_completed_tasks()

    def _check_timers(self) -> str:
        """Zeigt alle aktiven Timer."""
        if not self.session or not self.session.timers:
            return "Kein Timer aktiv."

        active = [t for t in self.session.timers if not t.is_done]
        done = [t for t in self.session.timers if t.is_done]

        if not active and not done:
            return "Kein Timer aktiv."

        parts = []
        if active:
            parts.append("Aktive Timer:")
            for t in active:
                parts.append(f"  - {t.label}: noch {t.format_remaining()}")
        if done:
            parts.append("Abgelaufene Timer:")
            for t in done:
                parts.append(f"  - {t.label}: fertig!")

        return "\n".join(parts)

    async def _stop_session(self) -> str:
        """Beendet die Koch-Session."""
        dish = self.session.dish if self.session else "unbekannt"
        # Alle Timer-Tasks canceln und auf Abschluss warten
        for task in self._timer_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._timer_tasks.clear()
        self.session = None
        await self._clear_persisted_session()
        return f"Koch-Session für '{dish}' beendet. Guten Appetit!"

    async def _save_recipe(self) -> str:
        """Speichert das aktuelle Rezept im Semantic Memory."""
        if not self.session:
            return "Keine aktive Koch-Session zum Speichern."

        if not self.semantic_memory:
            return "Gedaechtnis nicht verfügbar, kann Rezept nicht speichern."

        recipe_text = (
            f"Rezept: {self.session.dish} ({self.session.portions} Portionen). "
            f"Zutaten: {', '.join(self.session.ingredients)}. "
            f"Schritte: {self.session.total_steps}."
        )

        try:
            success = await self.semantic_memory.store_explicit(
                content=recipe_text,
                person=self.session.person,
            )
            if success:
                return f"Rezept für '{self.session.dish}' gespeichert! Ich erinnere mich beim nächsten Mal daran."
            return "Rezept-Speicherung fehlgeschlagen."
        except Exception as e:
            logger.error("Fehler beim Speichern des Rezepts: %s", e)
            return "Fehler beim Speichern des Rezepts."

    def _extract_dish(self, text: str) -> str:
        """Extrahiert den Gerichtnamen aus dem Text."""
        text_lower = text.lower().strip()

        # "Rezept für X" / "Rezept für X"
        match = re.search(r"rezept\s+(?:für|für)\s+(.+?)(?:\s+für\s+\d|\s+für\s+\d|$)", text_lower)
        if match:
            return match.group(1).strip().rstrip(".?!")

        # "Wie mache/koche/backe ich X?"
        match = re.search(
            r"wie\s+(?:mache|koche|backe|brate|grille|bereite)\s+ich\s+(.+?)(?:\?|$)",
            text_lower,
        )
        if match:
            return match.group(1).strip().rstrip(".?!")

        # "Wie macht/kocht man X?"
        match = re.search(
            r"wie\s+(?:macht|kocht|backt|brät|grillt|bereitet)\s+man\s+(.+?)(?:\?|$)",
            text_lower,
        )
        if match:
            return match.group(1).strip().rstrip(".?!")

        # "Ich will/möchte X kochen/backen"
        match = re.search(
            r"(?:ich\s+(?:will|möchte|möchte)|lass\s+uns|wir)\s+(.+?)\s+"
            r"(?:kochen|backen|zubereiten|braten|grillen|machen)",
            text_lower,
        )
        if match:
            return match.group(1).strip()

        # "Koche/Backe mir X"
        match = re.search(r"(?:koch|back|brat|grill)\w*\s+(?:mir\s+)?(.+?)(?:\s+für\s+\d|\s+für\s+\d|$)", text_lower)
        if match:
            dish = match.group(1).strip().rstrip(".?!")
            # Keine Navigation-Keywords als Gericht
            if dish and dish not in ["was", "etwas", "mir"]:
                return dish

        # "Hilf mir bei/beim X"
        match = re.search(r"hilf\s+mir\s+(?:bei|beim)\s+(.+?)(?:\s+kochen|\s+backen|$)", text_lower)
        if match:
            return match.group(1).strip().rstrip(".?!")

        # Fallback: Letztes Substantiv nach Koch-Keyword
        for kw in COOKING_KEYWORDS:
            if kw in text_lower:
                after = text_lower.split(kw, 1)[-1].strip()
                if after and len(after) > 2:
                    return after.rstrip(".?!").strip()

        return ""

    def _extract_explicit_portions(self, text: str) -> int:
        """Extrahiert Portionen NUR wenn explizit Zahl+Keyword genannt wird. Gibt 0 zurück wenn nicht."""
        match = re.search(r"(?:für|für)\s+(\d+)\s*(?:portionen?|personen?|leute)", text.lower())
        if match:
            return min(int(match.group(1)), 20)

        match = re.search(r"(\d+)\s*(?:portionen?|personen?)", text.lower())
        if match:
            return min(int(match.group(1)), 20)

        return 0

    def _extract_portions(self, text: str) -> int:
        """Extrahiert die Portionenanzahl aus dem Text (mit Default-Fallback für start_cooking)."""
        explicit = self._extract_explicit_portions(text)
        if explicit > 0:
            return explicit

        # Lockerer Match: "für 4" ohne Keyword reicht beim Session-Start
        match = re.search(r"(?:für|für)\s+(\d+)", text.lower())
        if match:
            return min(int(match.group(1)), 20)

        return self.default_portions

    def _parse_recipe(self, content: str, dish: str, portions: int, person: str) -> Optional[CookingSession]:
        """Parst die LLM-Antwort in eine CookingSession."""
        try:
            # JSON aus der Antwort extrahieren
            json_match = re.search(r"\{[\s\S]*\}", content)
            if not json_match:
                logger.warning("Kein JSON in Rezept-Antwort gefunden")
                return None

            data = json.loads(json_match.group())

            ingredients = data.get("ingredients", [])
            raw_steps = data.get("steps", [])

            steps = []
            for i, s in enumerate(raw_steps):
                steps.append(CookingStep(
                    number=s.get("number", i + 1),
                    instruction=s.get("instruction", ""),
                    timer_minutes=s.get("timer_minutes"),
                ))

            if not steps:
                return None

            return CookingSession(
                dish=data.get("dish", dish),
                portions=data.get("portions", portions),
                ingredients=ingredients,
                steps=steps,
                current_step=-1,  # -1 = noch nicht gestartet, 0 = erster Schritt
                person=person,
                raw_recipe=content,
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Rezept-Parsing Fehler: %s", e)
            return None

    # ------------------------------------------------------------------
    # Redis Session-Persistenz
    # ------------------------------------------------------------------

    async def _persist_session(self):
        """Speichert die aktive Koch-Session in Redis (überlebt Neustart)."""
        if not self.redis or not self.session:
            return
        try:
            # Aktive Timer mit-persistieren
            active_timers = []
            for t in self.session.timers:
                if not t.is_done:
                    active_timers.append({
                        "label": t.label,
                        "duration_seconds": t.duration_seconds,
                        "started_at": t.started_at,
                    })

            data = {
                "dish": self.session.dish,
                "portions": self.session.portions,
                "ingredients": self.session.ingredients,
                "steps": [
                    {"number": s.number, "instruction": s.instruction,
                     "timer_minutes": s.timer_minutes}
                    for s in self.session.steps
                ],
                "current_step": self.session.current_step,
                "started_at": self.session.started_at,
                "person": self.session.person,
                "active_timers": active_timers,
            }
            await self.redis.setex(
                self.REDIS_SESSION_KEY,
                self.REDIS_SESSION_TTL,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception as e:
            logger.debug("Koch-Session nicht persistiert: %s", e)

    async def _restore_session(self):
        """Lädt eine gespeicherte Koch-Session aus Redis (inkl. aktive Timer)."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(self.REDIS_SESSION_KEY)
            if not raw:
                return
            raw = raw.decode() if isinstance(raw, bytes) else raw
            data = json.loads(raw)
            steps = [
                CookingStep(
                    number=s["number"],
                    instruction=s["instruction"],
                    timer_minutes=s.get("timer_minutes"),
                )
                for s in data.get("steps", [])
            ]
            if not steps:
                return
            self.session = CookingSession(
                dish=data["dish"],
                portions=data.get("portions", 2),
                ingredients=data.get("ingredients", []),
                steps=steps,
                current_step=data.get("current_step", -1),
                started_at=data.get("started_at", 0.0),
                person=data.get("person", ""),
            )

            # Aktive Timer wiederherstellen
            restored_timers = 0
            for td in data.get("active_timers", []):
                timer = CookingTimer(
                    label=td["label"],
                    duration_seconds=td["duration_seconds"],
                    started_at=td.get("started_at", 0.0),
                )
                # Nur Timer die noch laufen
                if not timer.is_done:
                    self.session.timers.append(timer)
                    task = asyncio.create_task(self._timer_watcher(timer))
                    self._timer_tasks.append(task)
                    restored_timers += 1

            logger.info("Koch-Session wiederhergestellt: %s (Schritt %d/%d, %d Timer)",
                        self.session.dish, self.session.current_step + 1,
                        self.session.total_steps, restored_timers)
        except Exception as e:
            logger.debug("Koch-Session nicht wiederhergestellt: %s", e)

    async def _clear_persisted_session(self):
        """Loescht die gespeicherte Session aus Redis."""
        if self.redis:
            await self.redis.delete(self.REDIS_SESSION_KEY)

    async def _load_preferences(self, person: str) -> str:
        """Lädt Koch-Praeferenzen und Allergien aus dem Semantic Memory."""
        if not self.semantic_memory or not person:
            return ""

        try:
            # Suche nach Allergien, Unvertraeglichkeiten, Vorlieben
            facts = await self.semantic_memory.search_by_topic(
                "essen kochen allergie unvertraeglichkeit vegetarisch vegan laktose",
                limit=10,
            )

            if not facts:
                return ""

            prefs = []
            for f in facts:
                content = f.get("content", "")
                if content:
                    prefs.append(f"- {content}")

            if prefs:
                return "\nBekannte Praeferenzen/Einschraenkungen:\n" + "\n".join(prefs)

        except Exception as e:
            # F-028: Bei Fehler WARNEN statt stumm ignorieren — Allergien sind sicherheitsrelevant
            logger.error("WARNUNG: Allergie/Praeferenz-Check fehlgeschlagen: %s", e)
            return ("\n⚠ WARNUNG: Allergie-Datenbank nicht erreichbar. "
                    "Frage den Nutzer AKTIV nach Allergien und Unvertraeglichkeiten "
                    "bevor du Rezepte vorschlaegst!")

        return ""
