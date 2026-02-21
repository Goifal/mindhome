"""
MindHome Koch-Assistent — Schritt-fuer-Schritt Kochunterstuetzung.

Features:
- Rezept-Generierung via LLM (Deep-Model)
- Schritt-fuer-Schritt Navigation per Sprache
- Software-Timer (kein HA-Timer noetig)
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

from .config import yaml_config

logger = logging.getLogger(__name__)


@dataclass
class CookingTimer:
    """Ein Software-Timer fuer Koch-Schritte."""
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
        return max(0, int(remaining))

    @property
    def is_done(self) -> bool:
        if self.finished:
            return True
        if self.started_at > 0 and self.remaining_seconds <= 0:
            self.finished = True
            return True
        return False

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
    "ich will", "ich moechte", "ich möchte", "lass uns", "wir kochen",
    "wir backen", "hilf mir", "ich koche", "ich backe",
]

COOKING_KEYWORDS = [
    "kochen", "backen", "zubereiten", "braten", "grillen",
    "rezept fuer", "rezept für",
]

# Navigation per Sprache
NAV_NEXT = ["weiter", "naechster schritt", "nächster schritt", "next", "und dann",
            "was kommt jetzt", "wie gehts weiter"]
NAV_PREV = ["zurueck", "zurück", "vorheriger schritt", "nochmal den letzten"]
NAV_REPEAT = ["nochmal", "wiederhole", "wie war das", "sag das nochmal",
              "repeat", "bitte nochmal"]
NAV_STATUS = ["wo bin ich", "welcher schritt", "status", "uebersicht", "übersicht"]
NAV_TIMER = ["timer", "stell timer", "stell einen timer", "weck mich",
             "erinner mich"]
NAV_TIMER_CHECK = ["wie lange noch", "timer status", "laeuft der timer",
                   "läuft der timer"]
NAV_STOP = ["stop kochen", "stopp kochen", "abbrechen", "koch session beenden",
            "fertig kochen", "ich bin fertig"]
NAV_INGREDIENTS = ["zutaten", "was brauche ich", "einkaufsliste",
                   "welche zutaten"]
NAV_PORTIONS = ["fuer", "für", "portionen", "personen"]
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
- Klare, kurze Schritte (1-2 Saetze pro Schritt)
- timer_minutes nur wenn der Schritt eine Wartezeit hat (sonst null)
- Mengenangaben in metrischen Einheiten (Gramm, Liter, Essloeffel)
- Maximal {max_steps} Schritte
- Portionen: {portions}
{preferences}

Erstelle das Rezept fuer: {dish}"""


class CookingAssistant:
    """Koch-Assistent mit Schritt-fuer-Schritt Fuehrung."""

    REDIS_SESSION_KEY = "mha:cooking:session"
    REDIS_SESSION_TTL = 6 * 3600  # 6h — Session ueberlebt Neustart

    def __init__(self, ollama_client, semantic_memory=None):
        self.ollama = ollama_client
        self.semantic_memory = semantic_memory
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
        """Initialisiert mit Redis und laedt ggf. eine gespeicherte Session."""
        self.redis = redis_client
        if self.redis:
            await self._restore_session()

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Timer-Benachrichtigungen."""
        self._notify_callback = callback

    @property
    def has_active_session(self) -> bool:
        return self.session is not None and not self.session.is_finished

    def is_cooking_intent(self, text: str) -> bool:
        """Erkennt ob der User kochen will."""
        if not self.enabled:
            return False
        text_lower = text.lower().strip()

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
                   NAV_INGREDIENTS + NAV_SAVE)
        return any(kw in text_lower for kw in all_nav)

    async def start_cooking(self, text: str, person: str, model: str) -> str:
        """Startet eine Koch-Session: Generiert Rezept via LLM."""
        # Gericht aus Text extrahieren
        dish = self._extract_dish(text)
        if not dish:
            return "Was moechtest du kochen? Sag mir einfach das Gericht."

        # Portionen extrahieren (Default: 2)
        portions = self._extract_portions(text)

        # Praeferenzen/Allergien aus Semantic Memory laden
        preferences = await self._load_preferences(person)

        logger.info("Koch-Session starten: '%s' fuer %d Portionen (Person: %s)",
                     dish, portions, person)

        # Rezept via LLM generieren
        prompt = RECIPE_GENERATION_PROMPT.format(
            dish=dish,
            portions=portions,
            preferences=preferences,
            max_steps=self.max_steps,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Rezept fuer {dish}, {portions} Portionen"},
        ]

        response = await self.ollama.chat(
            messages=messages,
            model=model,
            temperature=0.7,
            max_tokens=self.max_tokens,
        )

        if "error" in response:
            logger.error("Rezept-Generierung fehlgeschlagen: %s", response["error"])
            return "Rezept-Generierung fehlgeschlagen. Spezifischeres Gericht oder andere Portionsgroesse koennte helfen."

        content = response.get("message", {}).get("content", "")
        session = self._parse_recipe(content, dish, portions, person)

        if not session or not session.steps:
            logger.warning("Rezept-Parsing fehlgeschlagen fuer: %s", dish)
            return f"Rezept fuer {dish} nicht strukturierbar. Anderes Gericht empfohlen."

        self.session = session
        self.session.started_at = time.time()
        await self._persist_session()

        # Antwort zusammenbauen
        parts = [f"Alles klar, {dish} fuer {portions} Portionen!"]

        if preferences:
            parts.append("Ich habe deine Praeferenzen beruecksichtigt.")

        parts.append(f"\nDu brauchst {len(session.ingredients)} Zutaten:")
        for ing in session.ingredients:
            parts.append(f"  - {ing}")

        parts.append(f"\nDas Rezept hat {session.total_steps} Schritte.")
        parts.append("Sag 'weiter' wenn du bereit bist fuer den ersten Schritt.")
        parts.append("Du kannst jederzeit 'zutaten', 'nochmal', 'zurueck' oder 'stop kochen' sagen.")

        return "\n".join(parts)

    async def handle_navigation(self, text: str) -> str:
        """Verarbeitet Navigation durch das aktive Rezept."""
        if not self.has_active_session:
            return "Es laeuft gerade keine Koch-Session. Sag mir was du kochen willst!"

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

        # Portionen aendern
        if any(kw in text_lower for kw in NAV_PORTIONS) and self._extract_portions(text) > 0:
            new_portions = self._extract_portions(text)
            return self._adjust_portions(new_portions)

        # Timer setzen
        if any(kw in text_lower for kw in NAV_TIMER):
            return self._set_timer_from_text(text)

        # Timer pruefen
        if any(kw in text_lower for kw in NAV_TIMER_CHECK):
            return self._check_timers()

        # Status
        if any(kw in text_lower for kw in NAV_STATUS):
            return self._show_status()

        # Naechster Schritt
        if any(kw in text_lower for kw in NAV_NEXT):
            return await self._next_step()

        # Vorheriger Schritt
        if any(kw in text_lower for kw in NAV_PREV):
            return await self._prev_step()

        # Wiederholen
        if any(kw in text_lower for kw in NAV_REPEAT):
            return self._repeat_step()

        return "Das habe ich nicht verstanden. Sag 'weiter', 'zurueck', 'nochmal' oder 'status'."

    async def _next_step(self) -> str:
        """Geht zum naechsten Schritt."""
        session = self.session

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
            response += f"\n(Dieser Schritt dauert {step.timer_minutes} Minuten — ich stelle automatisch einen Timer.)"
            self._start_step_timer(step)

        return response

    async def _prev_step(self) -> str:
        """Geht zum vorherigen Schritt."""
        if self.session.current_step <= 0:
            return "Du bist schon beim ersten Schritt."

        self.session.current_step -= 1
        await self._persist_session()
        step = self.session.get_current_step()
        return f"Zurueck zu Schritt {step.number} von {self.session.total_steps}:\n{step.instruction}"

    def _repeat_step(self) -> str:
        """Wiederholt den aktuellen Schritt."""
        step = self.session.get_current_step()
        if step is None:
            return "Es gibt keinen aktuellen Schritt. Sag 'weiter' fuer den naechsten."
        return f"Nochmal Schritt {step.number}:\n{step.instruction}"

    def _show_status(self) -> str:
        """Zeigt den aktuellen Status."""
        session = self.session
        step = session.get_current_step()
        elapsed = int(time.time() - session.started_at) // 60

        parts = [f"Koch-Session: {session.dish}"]
        parts.append(f"Portionen: {session.portions}")
        parts.append(f"Zeit: {elapsed} Minuten")

        if step:
            parts.append(f"Aktueller Schritt: {step.number} von {session.total_steps}")
            parts.append(f"  {step.instruction}")
        else:
            parts.append("Noch nicht gestartet. Sag 'weiter' fuer Schritt 1.")

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

        parts = [f"Zutaten fuer {self.session.dish} ({self.session.portions} Portionen):"]
        for ing in self.session.ingredients:
            parts.append(f"  - {ing}")
        return "\n".join(parts)

    def _adjust_portions(self, new_portions: int) -> str:
        """Passt die Portionen an (einfache Skalierung)."""
        if new_portions < 1 or new_portions > 20:
            return "Portionen muessen zwischen 1 und 20 liegen."

        old = self.session.portions
        if old == new_portions:
            return f"Es sind bereits {new_portions} Portionen."

        factor = new_portions / old
        self.session.portions = new_portions

        # Zutaten skalieren (einfache Regex fuer Zahlen am Anfang)
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
        return f"Portionen angepasst: {old} → {new_portions}. Die Zutaten wurden umgerechnet."

    def _set_timer_from_text(self, text: str) -> str:
        """Setzt einen Timer basierend auf Text-Eingabe."""
        # Minuten extrahieren
        match = re.search(r"(\d+)\s*(?:minuten?|min)", text.lower())
        if not match:
            return "Wie viele Minuten? Sag z.B. 'Timer 8 Minuten fuer die Pasta'."

        minutes = int(match.group(1))
        if minutes < 1 or minutes > 180:
            return "Timer muss zwischen 1 und 180 Minuten liegen."

        # Label extrahieren
        label_match = re.search(r"(?:fuer|für)\s+(.+?)(?:\s*$)", text.lower())
        label = label_match.group(1) if label_match else f"Timer ({minutes} Min)"

        timer = CookingTimer(label=label, duration_seconds=minutes * 60)
        timer.start()
        self.session.timers.append(timer)

        # Hintergrund-Task fuer Benachrichtigung
        task = asyncio.create_task(self._timer_watcher(timer))
        self._timer_tasks.append(task)

        return f"Timer gesetzt: {label} — {minutes} Minuten. Ich sage Bescheid wenn er abgelaufen ist."

    def _start_step_timer(self, step: CookingStep):
        """Startet einen Timer fuer einen Koch-Schritt."""
        if not step.timer_minutes:
            return

        label = f"Schritt {step.number}"
        timer = CookingTimer(label=label, duration_seconds=step.timer_minutes * 60)
        timer.start()
        self.session.timers.append(timer)

        task = asyncio.create_task(self._timer_watcher(timer))
        self._timer_tasks.append(task)

    async def _timer_watcher(self, timer: CookingTimer):
        """Ueberwacht einen Timer und benachrichtigt bei Ablauf."""
        try:
            await asyncio.sleep(timer.duration_seconds)
            timer.finished = True
            message = f"Sir, der Timer fuer '{timer.label}' ist abgelaufen!"
            logger.info("Koch-Timer abgelaufen: %s", timer.label)
            if self._notify_callback:
                await self._notify_callback({"message": message, "type": "cooking_timer"})
        except asyncio.CancelledError:
            pass

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
        # Alle Timer-Tasks canceln
        for task in self._timer_tasks:
            task.cancel()
        self._timer_tasks.clear()
        self.session = None
        await self._clear_persisted_session()
        return f"Koch-Session fuer '{dish}' beendet. Guten Appetit!"

    async def _save_recipe(self) -> str:
        """Speichert das aktuelle Rezept im Semantic Memory."""
        if not self.session:
            return "Keine aktive Koch-Session zum Speichern."

        if not self.semantic_memory:
            return "Gedaechtnis nicht verfuegbar, kann Rezept nicht speichern."

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
                return f"Rezept fuer '{self.session.dish}' gespeichert! Ich erinnere mich beim naechsten Mal daran."
            return "Rezept-Speicherung fehlgeschlagen."
        except Exception as e:
            logger.error("Fehler beim Speichern des Rezepts: %s", e)
            return "Fehler beim Speichern des Rezepts."

    def _extract_dish(self, text: str) -> str:
        """Extrahiert den Gerichtnamen aus dem Text."""
        text_lower = text.lower().strip()

        # "Rezept fuer X" / "Rezept für X"
        match = re.search(r"rezept\s+(?:fuer|für)\s+(.+?)(?:\s+fuer\s+\d|\s+für\s+\d|$)", text_lower)
        if match:
            return match.group(1).strip().rstrip(".")

        # "Ich will/moechte X kochen/backen"
        match = re.search(
            r"(?:ich\s+(?:will|moechte|möchte)|lass\s+uns|wir)\s+(.+?)\s+"
            r"(?:kochen|backen|zubereiten|braten|grillen|machen)",
            text_lower,
        )
        if match:
            return match.group(1).strip()

        # "Koche/Backe mir X"
        match = re.search(r"(?:koch|back|brat|grill)\w*\s+(?:mir\s+)?(.+?)(?:\s+fuer\s+\d|\s+für\s+\d|$)", text_lower)
        if match:
            dish = match.group(1).strip().rstrip(".")
            # Keine Navigation-Keywords als Gericht
            if dish and dish not in ["was", "etwas", "mir"]:
                return dish

        # "Hilf mir bei/beim X"
        match = re.search(r"hilf\s+mir\s+(?:bei|beim)\s+(.+?)(?:\s+kochen|\s+backen|$)", text_lower)
        if match:
            return match.group(1).strip().rstrip(".")

        # Fallback: Letztes Substantiv nach Koch-Keyword
        for kw in COOKING_KEYWORDS:
            if kw in text_lower:
                after = text_lower.split(kw, 1)[-1].strip()
                if after and len(after) > 2:
                    return after.rstrip(".").strip()

        return ""

    def _extract_portions(self, text: str) -> int:
        """Extrahiert die Portionenanzahl aus dem Text."""
        match = re.search(r"(?:fuer|für)\s+(\d+)\s*(?:portionen?|personen?|leute)?", text.lower())
        if match:
            return min(int(match.group(1)), 20)

        match = re.search(r"(\d+)\s*(?:portionen?|personen?)", text.lower())
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
        """Speichert die aktive Koch-Session in Redis (ueberlebt Neustart)."""
        if not self.redis or not self.session:
            return
        try:
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
            }
            await self.redis.setex(
                self.REDIS_SESSION_KEY,
                self.REDIS_SESSION_TTL,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception as e:
            logger.debug("Koch-Session nicht persistiert: %s", e)

    async def _restore_session(self):
        """Laedt eine gespeicherte Koch-Session aus Redis."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(self.REDIS_SESSION_KEY)
            if not raw:
                return
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
            logger.info("Koch-Session wiederhergestellt: %s (Schritt %d/%d)",
                        self.session.dish, self.session.current_step + 1,
                        self.session.total_steps)
        except Exception as e:
            logger.debug("Koch-Session nicht wiederhergestellt: %s", e)

    async def _clear_persisted_session(self):
        """Loescht die gespeicherte Session aus Redis."""
        if self.redis:
            await self.redis.delete(self.REDIS_SESSION_KEY)

    async def _load_preferences(self, person: str) -> str:
        """Laedt Koch-Praeferenzen und Allergien aus dem Semantic Memory."""
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
            logger.debug("Fehler beim Laden der Koch-Praeferenzen: %s", e)

        return ""
