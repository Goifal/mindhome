"""
Action Planner (Phase 4) - Plant und fuehrt komplexe Multi-Step Aktionen aus.
Phase 9: Narration Mode — Fliessende Uebergaenge bei Szenen.

Erkennt komplexe Anfragen die mehrere Schritte brauchen und fuehrt sie
iterativ aus: LLM plant -> Aktionen ausfuehren -> Ergebnisse zurueck an LLM
-> weiter planen -> bis fertig.

Narration Mode (Phase 9):
- Transition-Dauern fuer Licht-Aenderungen (sanftes Dimmen)
- Pausen zwischen Aktionsschritten fuer natuerlichen Ablauf
- Jarvis kann beschreiben was er gerade tut

Beispiele:
  "Mach alles fertig fuer morgen frueh"
  -> Kalender checken, Wecker stellen, Klima Nachtmodus, Kaffee-Timer

  "Ich gehe fuer 3 Tage weg"
  -> Away-Modus, Heizung runter, Rolllaeden zu, Alarm scharf

  "Filmabend" (mit Narration)
  -> "Licht dimmt langsam..." (5s) -> Rolladen -> TV -> "Viel Spass."
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import settings, yaml_config
from .function_calling import get_assistant_tools, FunctionExecutor
from .function_validator import FunctionValidator
from .ollama_client import OllamaClient
from .websocket import emit_action, emit_speaking

logger = logging.getLogger(__name__)

# Defaults — werden von planner-Config in settings.yaml ueberschrieben
_DEFAULT_MAX_ITERATIONS = 5
_DEFAULT_COMPLEX_KEYWORDS = [
    "alles", "fertig machen", "vorbereiten",
    "gehe weg", "fahre weg", "verreise", "urlaub",
    "routine", "morgenroutine", "abendroutine",
    "wenn ich", "falls ich", "bevor ich",
    "zuerst", "danach", "und dann", "ausserdem",
    "komplett", "ueberall", "in allen",
    "party", "besuch kommt", "gaeste",
]

# Config-Werte laden
_planner_cfg = yaml_config.get("planner", {})
MAX_ITERATIONS = int(_planner_cfg.get("max_iterations", _DEFAULT_MAX_ITERATIONS))
COMPLEX_KEYWORDS = _planner_cfg.get("complex_keywords", _DEFAULT_COMPLEX_KEYWORDS)

# Prompt fuer den Action Planner
PLANNER_SYSTEM_PROMPT = """Du bist der MindHome Action Planner.
Deine Aufgabe: Komplexe Anfragen in konkrete Aktionen umsetzen.

REGELN:
- Nutze die verfuegbaren Tools um Aktionen auszufuehren.
- Fuehre ALLE noetige Schritte aus, nicht nur den ersten.
- Wenn du Informationen brauchst (z.B. Kalender), frage sie zuerst ab.
- Ergebnisse vorheriger Schritte nutzen um naechste Schritte zu planen.
- Am Ende: Kurze Zusammenfassung auf Deutsch (max 2-3 Saetze).
- Antworte IMMER auf Deutsch.
- Sei knapp. Butler-Stil. Kein Geschwafel.
- Bei Szenen und Stimmungen: Nutze den 'transition' Parameter bei set_light
  fuer sanfte Uebergaenge (z.B. transition=5 fuer 5 Sekunden Dimmen).
- Bei Filmabend/Romantik/etc: Langsame Transitions (5-10s) fuer Atmosphaere."""


@dataclass
class PlanStep:
    """Ein einzelner Schritt im Plan."""
    function: str
    args: dict
    result: Optional[dict] = None
    status: str = "pending"  # pending, running, done, failed, blocked
    rollback_function: Optional[str] = None  # Funktion fuer Rollback
    rollback_args: Optional[dict] = None  # Args fuer Rollback


@dataclass
class ActionPlan:
    """Ein kompletter Aktionsplan."""
    request: str
    steps: list[PlanStep] = field(default_factory=list)
    summary: str = ""
    iterations: int = 0
    needs_confirmation: bool = False
    confirmation_reasons: list[str] = field(default_factory=list)

    rollback_performed: bool = False

    def to_dict(self) -> dict:
        return {
            "request": self.request,
            "steps": [
                {
                    "function": s.function,
                    "args": s.args,
                    "result": s.result,
                    "status": s.status,
                }
                for s in self.steps
            ],
            "summary": self.summary,
            "iterations": self.iterations,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_reasons": self.confirmation_reasons,
            "rollback_performed": self.rollback_performed,
        }


class ActionPlanner:
    """Plant und fuehrt komplexe Multi-Step Aktionen aus. Phase 9: mit Narration.
    Phase 17: Multi-Turn Planning Dialoge mit Rueckfragen."""

    def __init__(
        self,
        ollama: OllamaClient,
        executor: FunctionExecutor,
        validator: FunctionValidator,
    ):
        self.ollama = ollama
        self.executor = executor
        self.validator = validator
        self._last_plan: Optional[ActionPlan] = None
        self._redis = None
        self._pending_plans: dict[str, dict] = {}  # In-Memory Cache fuer laufende Dialoge

        # Phase 9: Narration Mode Konfiguration
        narr_cfg = yaml_config.get("narration", {})
        self.narration_enabled = narr_cfg.get("enabled", True)
        self.default_transition = int(narr_cfg.get("default_transition", 3))
        self.scene_transitions = narr_cfg.get("scene_transitions", {})
        self.step_delay = float(narr_cfg.get("step_delay", 1.5))
        self.narrate_actions = narr_cfg.get("narrate_actions", True)

    def is_complex_request(self, text: str) -> bool:
        """
        Erkennt ob eine Anfrage komplex ist und den Planner braucht.

        Heuristik:
        - Enthaelt Keywords fuer komplexe Aktionen
        - Enthaelt mehrere Befehle (und/dann/ausserdem)
        """
        text_lower = text.lower()
        return any(kw in text_lower for kw in COMPLEX_KEYWORDS)

    async def plan_and_execute(
        self,
        text: str,
        system_prompt: str,
        context: dict,
        messages: list[dict],
        person: str = "",
        autonomy=None,
    ) -> dict:
        """
        Plant und fuehrt eine komplexe Anfrage aus.

        Args:
            text: User-Anfrage
            system_prompt: Basis-System-Prompt (inkl. Persoenlichkeit + Memory)
            context: Aktueller Kontext
            messages: Bisherige Nachrichten (History)
            person: Name der ausfuehrenden Person (fuer Trust-Check)
            autonomy: AutonomyManager-Instanz (fuer Trust-Check)

        Returns:
            Dict mit response, actions, plan
        """
        plan = ActionPlan(request=text)

        # System Prompt fuer Planner erweitern
        planner_prompt = system_prompt + "\n\n" + PLANNER_SYSTEM_PROMPT

        # Nachrichten fuer den Planner aufbauen
        planner_messages = [{"role": "system", "content": planner_prompt}]
        # History uebernehmen (ohne System Prompt)
        for msg in messages:
            if msg["role"] != "system":
                planner_messages.append(msg)

        all_actions = []

        # Iterative Ausfuehrung: LLM -> Tools -> Ergebnisse -> LLM -> ...
        for iteration in range(MAX_ITERATIONS):
            plan.iterations = iteration + 1

            logger.info("Action Planner: Iteration %d", iteration + 1)

            # LLM aufrufen — Modell und max_tokens aus planner-Config
            planner_model = _planner_cfg.get("model", "") or settings.model_deep
            planner_max_tokens = int(_planner_cfg.get("max_tokens", 512))
            response = await self.ollama.chat(
                messages=planner_messages,
                model=planner_model,
                tools=get_assistant_tools(),
                max_tokens=planner_max_tokens,
            )

            if "error" in response:
                logger.error("Planner LLM Fehler: %s", response["error"])
                plan.summary = "Fehler bei der Planung."
                break

            message = response.get("message", {})
            response_text = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            # Keine weiteren Tool Calls -> LLM ist fertig
            if not tool_calls:
                plan.summary = response_text
                logger.info("Action Planner fertig nach %d Iterationen", iteration + 1)
                break

            # Tool Calls ausfuehren
            tool_results = []
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                func_name = func.get("name", "")
                func_args = func.get("arguments", {})

                step = PlanStep(function=func_name, args=func_args)

                # Validierung
                validation = self.validator.validate(func_name, func_args)
                if not validation.ok:
                    if validation.needs_confirmation:
                        step.status = "blocked"
                        step.result = {"needs_confirmation": True, "reason": validation.reason}
                        plan.needs_confirmation = True
                        plan.confirmation_reasons.append(validation.reason)
                        tool_results.append(
                            f"BLOCKIERT: {func_name} braucht Bestaetigung - {validation.reason}"
                        )
                    else:
                        step.status = "failed"
                        step.result = {"success": False, "message": validation.reason}
                        tool_results.append(
                            f"FEHLER: {func_name} - {validation.reason}"
                        )
                    plan.steps.append(step)
                    all_actions.append({
                        "function": func_name,
                        "args": func_args,
                        "result": step.result,
                    })
                    continue

                # SICHERHEIT: Trust-Level Pre-Check (wie in brain.py)
                if autonomy:
                    effective_person = person if person else "__anonymous_guest__"
                    action_room = func_args.get("room", "") if isinstance(func_args, dict) else ""
                    trust_check = autonomy.can_person_act(effective_person, func_name, room=action_room)
                    if not trust_check["allowed"]:
                        logger.warning(
                            "Planner Trust-Check fehlgeschlagen: %s darf '%s' nicht (%s)",
                            effective_person, func_name, trust_check.get("reason", ""),
                        )
                        step.status = "blocked"
                        step.result = {"success": False, "message": f"blocked: {trust_check.get('reason', 'Keine Berechtigung')}"}
                        plan.steps.append(step)
                        all_actions.append({
                            "function": func_name,
                            "args": func_args,
                            "result": step.result,
                        })
                        tool_results.append(
                            f"BLOCKIERT: {func_name} - Keine Berechtigung ({trust_check.get('reason', '')})"
                        )
                        continue

                # Phase 9: Narration — Transition bei Licht-Aktionen injizieren
                if self.narration_enabled and func_name == "set_light":
                    if "transition" not in func_args:
                        func_args["transition"] = self._get_transition(text)

                # Phase 9: Narration — Kurze Pause zwischen Schritten
                if self.narration_enabled and len(plan.steps) > 0 and self.step_delay > 0:
                    await asyncio.sleep(self.step_delay)

                # Rollback-Info VOR Ausfuehrung erfassen
                step.rollback_function, step.rollback_args = self._get_rollback_info(
                    func_name, func_args
                )

                # Ausfuehren
                step.status = "running"
                result = await self.executor.execute(func_name, func_args)
                step.result = result
                step.status = "done" if result.get("success", False) else "failed"

                # Bei Fehlschlag: Vorherige erfolgreiche Steps zurueckrollen
                if step.status == "failed" and len(plan.steps) > 0:
                    rollback_count = await self._rollback_completed_steps(plan.steps)
                    if rollback_count > 0:
                        plan.rollback_performed = True
                        logger.info(
                            "Rollback: %d Step(s) nach Fehler in '%s' zurueckgerollt",
                            rollback_count, func_name,
                        )
                        tool_results.append(
                            f"ROLLBACK: {rollback_count} vorherige Aktion(en) zurueckgesetzt"
                        )

                plan.steps.append(step)
                all_actions.append({
                    "function": func_name,
                    "args": func_args,
                    "result": result,
                })

                # WebSocket: Aktion melden
                await emit_action(func_name, func_args, result)

                # Phase 9: Narration — beschreiben was passiert
                if self.narration_enabled and self.narrate_actions and result.get("success"):
                    narration = self._get_narration_text(func_name, func_args)
                    if narration:
                        await emit_speaking(narration)

                tool_results.append(
                    f"{func_name}: {result.get('message', 'OK')}"
                )

                logger.info(
                    "Planner Step: %s(%s) -> %s",
                    func_name, func_args, result.get("message", ""),
                )

            # Ergebnisse zurueck an LLM fuer naechste Iteration
            # Aktuelle Antwort des LLM als assistant message hinzufuegen
            planner_messages.append({
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": tool_calls,
            })
            # Tool-Ergebnisse als tool response
            planner_messages.append({
                "role": "tool",
                "content": "\n".join(tool_results),
            })

        else:
            # Max Iterations erreicht
            logger.warning("Action Planner: Max Iterations erreicht")
            if not plan.summary:
                plan.summary = "Plan ausgefuehrt."

        # Fallback-Summary wenn keins vorhanden
        if not plan.summary and plan.steps:
            successful = sum(1 for s in plan.steps if s.status == "done")
            total = len(plan.steps)
            plan.summary = f"{successful} von {total} Aktionen ausgefuehrt."

        self._last_plan = plan

        return {
            "response": plan.summary,
            "actions": all_actions,
            "plan": plan.to_dict(),
        }

    def get_last_plan(self) -> Optional[dict]:
        """Gibt den letzten ausgefuehrten Plan zurueck."""
        if self._last_plan:
            return self._last_plan.to_dict()
        return None

    # ------------------------------------------------------------------
    # Phase 9: Narration Mode Hilfsmethoden
    # ------------------------------------------------------------------

    def _get_transition(self, request_text: str) -> int:
        """Bestimmt die Transition-Dauer basierend auf der Anfrage."""
        text_lower = request_text.lower()

        # Szenen-spezifische Transitions pruefen
        for scene, duration in self.scene_transitions.items():
            if scene in text_lower:
                return duration

        return self.default_transition

    @staticmethod
    def _get_narration_text(func_name: str, func_args: dict) -> str:
        """Generiert einen kurzen Narrations-Text fuer eine Aktion."""
        narrations = {
            "set_light": lambda a: (
                f"Licht {a.get('room', '')} dimmt..."
                if a.get("state") == "on" and a.get("brightness", 100) < 50
                else ""
            ),
            "set_cover": lambda a: (
                f"Rolladen {a.get('room', '')} faehrt..."
                if a.get("position", 50) != 50
                else ""
            ),
            "set_climate": lambda a: "",  # Leise, keine Narration
            "activate_scene": lambda a: "",  # Wird vom LLM zusammengefasst
            "play_media": lambda a: "",
        }

        generator = narrations.get(func_name)
        if generator:
            return generator(func_args)
        return ""

    # ------------------------------------------------------------------
    # Multi-Turn Planning Dialoge
    # ------------------------------------------------------------------

    # Keywords die auf Planungs-Anfragen hindeuten (benoetigen Rueckfragen)
    PLANNING_KEYWORDS = [
        "plane", "organisiere", "bereite vor", "dinner party",
        "feier", "event planen", "vorbereiten fuer",
    ]

    def is_planning_request(self, text: str) -> bool:
        """Erkennt ob eine Anfrage ein interaktiver Planungs-Dialog sein soll."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.PLANNING_KEYWORDS)

    async def start_planning_dialog(self, text: str, person: str = "") -> dict:
        """Startet einen mehrstufigen Planungs-Dialog.

        Das LLM analysiert die Anfrage und stellt Rueckfragen bevor es Aktionen plant.

        Args:
            text: User-Anfrage (z.B. "Plane eine Dinner-Party fuer Samstag")
            person: Person die den Dialog startet

        Returns:
            Dict mit response (Rueckfrage oder Plan), plan_id, status
        """
        plan_id = f"plan_{id(text) % 10000}"

        planning_prompt = f"""Analysiere diese Planungsanfrage und stelle die noetigsten Rueckfragen.
WICHTIG: Stelle maximal 2-3 Fragen. Nicht zu viele auf einmal.
Formuliere die Fragen als nummerierte Liste.
Am Ende: "Sobald ich die Details habe, erstelle ich einen Plan."

Anfrage: {text}
Person: {person or 'Sir'}"""

        try:
            response = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": f"""Du bist {settings.assistant_name}, der intelligente Butler.
Du hilfst bei der Planung von Events/Aktivitaeten.
Stelle kurze, praesize Rueckfragen um den Plan zu verfeinern.
Deutsch. Butler-Stil. Max 3 Fragen.
Beispiel:
"Sehr gerne, Sir. Fuer die Planung brauche ich noch:
1. Fuer wie viele Gaeste?
2. Welche Uhrzeit?
3. Soll ich auch eine Einkaufsliste erstellen?
Sobald ich die Details habe, kuemmere ich mich um alles."
"""},
                    {"role": "user", "content": planning_prompt},
                ],
                model=settings.model_fast,
                temperature=0.7,
            )

            response_text = response.get("message", {}).get("content", "")

            # Plan-State speichern fuer Follow-Up (mit Timestamp fuer Auto-Expiry)
            import time as _time
            self._pending_plans[plan_id] = {
                "original_request": text,
                "person": person,
                "status": "waiting_for_details",
                "created_at": _time.time(),
                "messages": [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": response_text},
                ],
            }

            return {
                "response": response_text,
                "plan_id": plan_id,
                "status": "waiting_for_details",
            }

        except Exception as e:
            logger.error("Planning Dialog Start Fehler: %s", e)
            return {
                "response": "Planung fehlgeschlagen. Versuch es nochmal anders zu formulieren.",
                "plan_id": plan_id,
                "status": "error",
            }

    async def continue_planning_dialog(self, text: str, plan_id: str) -> dict:
        """Setzt einen laufenden Planungs-Dialog fort.

        Args:
            text: User-Antwort auf Rueckfragen
            plan_id: ID des laufenden Plans

        Returns:
            Dict mit response, actions (falls Plan fertig), status
        """
        plan_state = self._pending_plans.get(plan_id)
        if not plan_state:
            return {"response": "Der Plan ist abgelaufen. Was soll ich planen?", "status": "error"}

        plan_state["messages"].append({"role": "user", "content": text})

        finalize_prompt = """Basierend auf den bisherigen Informationen:
1. Erstelle einen konkreten Plan mit nummerierten Schritten
2. Frage ob der Plan so passt oder ob Anpassungen noetig sind
3. Formatiere als uebersichtliche Liste

Beispiel:
"Verstanden. Hier ist mein Plan:
1. Einkaufsliste erstellen (Zutaten fuer 6 Personen)
2. Samstag 18:00: Gaeste-Modus aktivieren
3. 19:00: Szene 'Dinner' (Licht dimmen, Musik)
4. Kalender-Eintrag anlegen

Soll ich das so umsetzen, oder gibt es Aenderungen?"
"""

        messages = [
            {"role": "system", "content": f"""Du bist {settings.assistant_name}.
Du planst ein Event/Aktivitaet basierend auf der Konversation.
Erstelle einen konkreten, ausfuehrbaren Plan.
Deutsch. Butler-Stil. Praezise.
Frage am Ende ob der Plan so umgesetzt werden soll."""},
        ]
        messages.extend(plan_state["messages"])
        messages.append({"role": "user", "content": finalize_prompt})

        try:
            response = await self.ollama.chat(
                messages=messages,
                model=settings.model_fast,
                temperature=0.7,
            )

            response_text = response.get("message", {}).get("content", "")
            plan_state["messages"].append({"role": "assistant", "content": response_text})
            plan_state["status"] = "plan_proposed"

            return {
                "response": response_text,
                "plan_id": plan_id,
                "status": "plan_proposed",
            }

        except Exception as e:
            logger.error("Planning Dialog Continue Fehler: %s", e)
            return {"response": "Die Planung hakt gerade. Nochmal von vorn?", "status": "error"}

    def has_pending_plan(self) -> Optional[str]:
        """Prueft ob ein Planungs-Dialog laeuft.

        Returns:
            Plan-ID oder None. Expired Plans (>10 Min) werden automatisch entfernt.
        """
        import time as _time
        expired = []
        result = None
        for plan_id, state in self._pending_plans.items():
            # Auto-Expiry: Plans aelter als 10 Minuten entfernen
            created = state.get("created_at", 0)
            if created and (_time.time() - created) > 600:
                expired.append(plan_id)
                continue
            if state.get("status") in ("waiting_for_details", "plan_proposed"):
                result = plan_id
        for plan_id in expired:
            self._pending_plans.pop(plan_id, None)
            logger.info("Planungs-Dialog %s nach Timeout entfernt", plan_id)
        return result

    def clear_plan(self, plan_id: str):
        """Beendet einen Planungs-Dialog."""
        self._pending_plans.pop(plan_id, None)

    # ------------------------------------------------------------------
    # Rollback-Mechanismus
    # ------------------------------------------------------------------

    @staticmethod
    def _get_rollback_info(func_name: str, func_args: dict) -> tuple[Optional[str], Optional[dict]]:
        """Bestimmt die Rollback-Aktion fuer eine gegebene Funktion.

        Gibt (rollback_function, rollback_args) zurueck oder (None, None)
        wenn kein Rollback moeglich ist.
        """
        rollback_map = {
            "set_light": lambda args: (
                "set_light",
                {
                    "room": args.get("room", ""),
                    "state": "off" if args.get("state") == "on" else "on",
                },
            ),
            "set_climate": lambda args: (
                "set_climate",
                {
                    "room": args.get("room", ""),
                    "temperature": args.get("temperature", 21),  # Default zurueck
                },
            ),
            "set_cover": lambda args: (
                "set_cover",
                {
                    "room": args.get("room", ""),
                    "position": 100 if args.get("position", 100) < 50 else 0,
                },
            ),
            "lock_door": lambda args: (
                "lock_door",
                {
                    "door": args.get("door", ""),
                    "action": "lock" if args.get("action") == "unlock" else "unlock",
                },
            ),
            "activate_scene": lambda args: (None, None),  # Szenen nicht zurueckrollbar
        }

        generator = rollback_map.get(func_name)
        if generator:
            return generator(func_args)
        return None, None

    async def _rollback_completed_steps(self, completed_steps: list[PlanStep]) -> int:
        """Rollt erfolgreich ausgefuehrte Steps zurueck.

        Returns:
            Anzahl zurueckgerollter Steps
        """
        rollback_count = 0

        # In umgekehrter Reihenfolge zurueckrollen (LIFO)
        for step in reversed(completed_steps):
            if step.status != "done":
                continue
            if not step.rollback_function or not step.rollback_args:
                continue

            try:
                result = await self.executor.execute(
                    step.rollback_function, step.rollback_args
                )
                if result.get("success", False):
                    step.status = "rolled_back"
                    rollback_count += 1
                    logger.info(
                        "Rollback: %s(%s) -> %s",
                        step.rollback_function, step.rollback_args,
                        result.get("message", "OK"),
                    )
            except Exception as e:
                logger.warning("Rollback fehlgeschlagen fuer %s: %s", step.function, e)

        return rollback_count
