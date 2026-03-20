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

from .config import settings, yaml_config, get_person_title
from .function_calling import get_assistant_tools, FunctionExecutor
from .function_validator import FunctionValidator
from .ollama_client import OllamaClient
from .websocket import emit_action, emit_speaking

logger = logging.getLogger(__name__)

# Defaults — werden von planner-Config in settings.yaml ueberschrieben
_DEFAULT_MAX_ITERATIONS = 8
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
PLANNER_SYSTEM_PROMPT = """ZUSAETZLICHE PLANUNGS-FAEHIGKEIT:
Du kannst komplexe Anfragen in mehrere Schritte zerlegen und iterativ ausfuehren.

CHAIN-OF-THOUGHT PLANUNGSPROZESS:
1. ANALYSE: Was genau will der User? Welche Geraete/Systeme sind betroffen?
2. INFORMATIONEN: Fehlende Daten zuerst abfragen (Status, Kalender, Wetter).
3. PLANUNG: Schritte in logischer Reihenfolge planen. Abhaengigkeiten beachten.
4. AUSFUEHRUNG: Jeden Schritt einzeln ausfuehren und Ergebnis pruefen.
5. ANPASSUNG: Bei Fehler alternative Loesung suchen statt aufzugeben.
6. ZUSAMMENFASSUNG: Kurz berichten was getan wurde (2-3 Saetze).

PLANUNGS-REGELN:
- Nutze die verfuegbaren Tools um Aktionen auszufuehren.
- Fuehre ALLE noetige Schritte aus, nicht nur den ersten.
- Wenn du Informationen brauchst (z.B. Kalender), frage sie zuerst ab.
- Ergebnisse vorheriger Schritte nutzen um naechste Schritte zu planen.
- Am Ende: Kurze Zusammenfassung (max 2-3 Saetze) in deinem normalen Ton.
- Bei Szenen und Stimmungen: Nutze den 'transition' Parameter bei set_light
  fuer sanfte Uebergaenge (z.B. transition=5 fuer 5 Sekunden Dimmen).
- Bei Filmabend/Romantik/etc: Langsame Transitions (5-10s) fuer Atmosphaere.

FEHLERBEHANDLUNG:
- Wenn ein Schritt fehlschlaegt: Pruefen ob es eine Alternative gibt.
- Beispiel: Lampe X reagiert nicht → andere Lampe im Raum versuchen.
- Beispiel: Szene existiert nicht → einzelne Geraete manuell setzen.
- Nicht einfach aufgeben — kreativ nach Loesungen suchen.

WICHTIG: Du bist und bleibst J.A.R.V.I.S. — auch beim Planen. Dein Ton aendert sich NICHT."""


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
        self._max_pending_plans = 5  # Maximal gleichzeitige Planungen
        self._max_plan_messages = 20  # Max Messages pro Plan (Memory-Schutz)

        # Phase 9: Narration Mode Konfiguration
        narr_cfg = yaml_config.get("narration", {})
        self.narration_enabled = narr_cfg.get("enabled", True)
        self.default_transition = int(narr_cfg.get("default_transition", 3))
        self.scene_transitions = narr_cfg.get("scene_transitions", {})
        self.step_delay = float(narr_cfg.get("step_delay", 1.5))
        self.narrate_actions = narr_cfg.get("narrate_actions", True)

    # Fragewoerter — wenn der Satz damit beginnt, ist es eine Frage, kein Befehl
    _QUESTION_STARTS = (
        "was ", "wer ", "wie ", "wo ", "warum ", "wieso ", "weshalb ",
        "wann ", "welche ", "welcher ", "welches ", "wieviel ",
        "wie viel", "woher ", "wohin ",
    )
    # Polite forms that are only questions if combined with '?'
    _POLITE_STARTS = (
        "kannst du", "koenntest du", "wuerdest du", "hast du", "bist du",
        "machst du", "denkst du", "findest du", "magst du", "weisst du",
    )

    def is_complex_request(self, text: str) -> bool:
        """
        Erkennt ob eine Anfrage komplex ist und den Planner braucht.

        Heuristik:
        - Enthaelt Keywords fuer komplexe Aktionen
        - Enthaelt mehrere Befehle (und/dann/ausserdem)
        - NICHT bei reinen Fragen (was/wie/warum/wo/wer...)
        """
        text_lower = text.lower().strip()

        # Pure question words always indicate a question
        if text_lower.startswith(self._QUESTION_STARTS):
            return False
        # Polite forms are only questions when they end with '?'
        if text_lower.endswith("?") and text_lower.startswith(self._POLITE_STARTS):
            return False

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
            from .config import resolve_model
            planner_model = resolve_model(_planner_cfg.get("model", ""), fallback_tier="deep")
            planner_max_tokens = int(_planner_cfg.get("max_tokens", 512))

            # SICHERHEIT: Tools VOR dem LLM-Aufruf nach Trust-Level filtern
            available_tools = get_assistant_tools()
            if autonomy:
                effective_person = person if person else "__anonymous_guest__"
                available_tools = [
                    t for t in available_tools
                    if autonomy.can_person_act(
                        effective_person,
                        t.get("function", {}).get("name", ""),
                    ).get("allowed", True)
                ]

            response = await self.ollama.chat(
                messages=planner_messages,
                model=planner_model,
                tools=available_tools,
                max_tokens=planner_max_tokens,
                think=True,
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

            # Phase 1: Validierung + Trust-Check (sequentiell, kein I/O)
            valid_steps: list[tuple[PlanStep, str, dict]] = []  # (step, func_name, func_args)
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

                # Narration: Transition bei Licht-Aktionen injizieren
                if self.narration_enabled and func_name == "set_light":
                    if "transition" not in func_args:
                        func_args["transition"] = self._get_transition(text)

                # Rollback-Info VOR Ausfuehrung erfassen
                step.rollback_function, step.rollback_args = self._get_rollback_info(
                    func_name, func_args
                )

                valid_steps.append((step, func_name, func_args))

            # Device-Dependency-Validierung: Gesamten Plan pruefen
            if valid_steps:
                try:
                    from .state_change_log import StateChangeLog
                    import assistant.main as main_module
                    if hasattr(main_module, "brain"):
                        _states = await main_module.brain.ha.get_states() or []
                        for _vs_step, _vs_fn, _vs_args in valid_steps:
                            _dep_hints = StateChangeLog.check_action_dependencies(
                                _vs_fn, _vs_args, _states,
                            )
                            if _dep_hints:
                                plan.confirmation_reasons.extend(_dep_hints)
                        if plan.confirmation_reasons:
                            plan.needs_confirmation = True
                            logger.info(
                                "Planner: %d Dependency-Konflikte erkannt",
                                len(plan.confirmation_reasons),
                            )
                except Exception as _dep_err:
                    logger.debug("Planner Dependency-Check: %s", _dep_err)

            # Phase 2: Ausfuehrung — parallel oder sequentiell (Narration)
            use_parallel = len(valid_steps) > 1 and not (self.narration_enabled and self.step_delay > 0)

            if use_parallel:
                # Parallele Ausfuehrung: Alle Steps gleichzeitig starten
                logger.info("Planner: %d Tool-Calls parallel ausfuehren", len(valid_steps))

                async def _run_step(s: PlanStep, fn: str, fa: dict) -> tuple[PlanStep, str, dict, dict]:
                    s.status = "running"
                    res = await self.executor.execute(fn, fa)
                    s.result = res
                    s.status = "done" if res.get("success", False) else "failed"
                    return s, fn, fa, res

                tasks = [asyncio.create_task(_run_step(s, fn, fa)) for s, fn, fa in valid_steps]
                done, pending = await asyncio.wait(tasks, timeout=120)
                if pending:
                    logger.warning("T3: Action planner %d steps timed out (120s)", len(pending))
                    for t in pending:
                        t.cancel()
                results = []
                for t in tasks:
                    if t in done:
                        if t.cancelled():
                            results.append(asyncio.CancelledError())
                        else:
                            try:
                                results.append(t.result())
                            except Exception as exc:
                                results.append(exc)
                    else:
                        results.append(asyncio.TimeoutError())

                for idx, r in enumerate(results):
                    if isinstance(r, Exception):
                        logger.error("Planner parallel Step Fehler: %s", r)
                        # Fehlgeschlagenen Step trotzdem im Audit-Trail erfassen
                        if idx < len(valid_steps):
                            err_step, err_fn, err_fa = valid_steps[idx]
                            err_step.status = "failed"
                            err_step.result = {"success": False, "message": f"Exception: {r}"}
                            plan.steps.append(err_step)
                            all_actions.append({
                                "function": err_fn,
                                "args": err_fa,
                                "result": err_step.result,
                            })
                            tool_results.append(f"{err_fn}: Fehler — {r}")
                        continue
                    step, func_name, func_args, result = r
                    plan.steps.append(step)
                    all_actions.append({
                        "function": func_name,
                        "args": func_args,
                        "result": result,
                    })
                    await emit_action(func_name, func_args, result)
                    tool_results.append(
                        f"{func_name}: {result.get('message', 'OK')}"
                    )
                    logger.info(
                        "Planner Step: %s(%s) -> %s",
                        func_name, func_args, result.get("message", ""),
                    )
            else:
                # Sequentielle Ausfuehrung (Narration-Modus oder einzelner Step)
                for step, func_name, func_args in valid_steps:
                    # Narration: Kurze Pause zwischen Schritten
                    if self.narration_enabled and len(plan.steps) > 0 and self.step_delay > 0:
                        await asyncio.sleep(self.step_delay)

                    # Ausfuehren
                    step.status = "running"
                    result = await self.executor.execute(func_name, func_args)
                    step.result = result
                    step.status = "done" if result.get("success", False) else "failed"

                    # Bei Fehlschlag: Re-Planning versuchen, dann ggf. Rollback
                    if step.status == "failed" and len(plan.steps) > 0:
                        error_msg = result.get("message", "Unbekannter Fehler")
                        try:
                            replan_result = await self._attempt_replan(
                                func_name, func_args, error_msg, plan, planner_messages,
                            )
                        except Exception as rp_err:
                            logger.error("Re-Planning Ausnahme fuer '%s': %s", func_name, rp_err)
                            replan_result = None
                        if replan_result:
                            tool_results.append(
                                f"RE-PLAN: {func_name} fehlgeschlagen ({error_msg}). "
                                f"Alternative: {replan_result}"
                            )
                        else:
                            # Kein Re-Planning moeglich — Rollback
                            try:
                                rollback_count = await self._rollback_completed_steps(plan.steps)
                            except Exception as rb_err:
                                logger.error("Rollback Ausnahme: %s", rb_err)
                                rollback_count = 0
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

                    # Narration: beschreiben was passiert
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
            valid_tool_calls = [
                tc for tc in tool_calls
                if isinstance(tc, dict) and "function" in tc
            ]
            planner_messages.append({
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": valid_tool_calls,
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
        import hashlib, time
        plan_id = f"plan_{hashlib.md5(f'{text}{time.monotonic()}'.encode()).hexdigest()[:8]}"

        planning_prompt = f"""Analysiere diese Planungsanfrage und stelle die noetigsten Rueckfragen.
WICHTIG: Stelle maximal 2-3 Fragen. Nicht zu viele auf einmal.
Formuliere die Fragen als nummerierte Liste.
Am Ende: "Sobald ich die Details habe, erstelle ich einen Plan."

Anfrage: {text}
Person: {person or get_person_title(person)}"""

        try:
            response = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": f"""Du bist {settings.assistant_name}, der intelligente Butler.
Du hilfst bei der Planung von Events/Aktivitaeten.
Stelle kurze, praesize Rueckfragen um den Plan zu verfeinern.
Deutsch. Butler-Stil. Max 3 Fragen.
Beispiel:
Sehr gerne, {get_person_title(person)}. Fuer die Planung brauche ich noch:
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
            # Expired Plans aufraumen bevor neuer hinzukommt (Memory-Schutz)
            self._cleanup_expired_plans()
            # Aelteste Plans entfernen wenn Limit erreicht
            while len(self._pending_plans) >= self._max_pending_plans:
                oldest_id = min(list(self._pending_plans.keys()),
                                key=lambda k: self._pending_plans[k].get("created_at", 0))
                self._pending_plans.pop(oldest_id, None)
                logger.info("Planungs-Dialog %s entfernt (max %d erreicht)",
                            oldest_id, self._max_pending_plans)
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

        # Memory-Schutz: Aelteste Messages trimmen wenn Limit erreicht
        if len(plan_state["messages"]) > self._max_plan_messages:
            # Erste und letzte Messages behalten, Mitte kuerzen
            plan_state["messages"] = (
                plan_state["messages"][:2] + plan_state["messages"][-(self._max_plan_messages - 2):]
            )

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

    def _cleanup_expired_plans(self):
        """Entfernt abgelaufene Plans (>10 Min). Wird vor neuen Plans aufgerufen."""
        import time as _time
        expired = [
            pid for pid, state in self._pending_plans.items()
            if (_time.time() - state.get("created_at", 0)) > 600
        ]
        for pid in expired:
            self._pending_plans.pop(pid, None)
            logger.info("Planungs-Dialog %s nach Timeout entfernt", pid)

    def clear_plan(self, plan_id: str):
        """Beendet einen Planungs-Dialog."""
        self._pending_plans.pop(plan_id, None)

    # ------------------------------------------------------------------
    # Failure Re-Planning — Alternative Aktion bei Fehler
    # ------------------------------------------------------------------

    async def _attempt_replan(
        self,
        failed_func: str,
        failed_args: dict,
        error_msg: str,
        plan: "ActionPlan",
        planner_messages: list[dict],
    ) -> str | None:
        """Versucht bei einem fehlgeschlagenen Step eine Alternative zu finden.

        Fragt das LLM nach einer alternativen Aktion und fuehrt diese aus.
        Wird nur einmal pro fehlgeschlagenem Step versucht (kein Rekursions-Loop).

        Returns:
            Beschreibung der erfolgreichen Alternative oder None.
        """
        replan_prompt = (
            f"Die Aktion '{failed_func}' mit Parametern {json.dumps(failed_args, ensure_ascii=False)} "
            f"ist fehlgeschlagen: {error_msg}\n\n"
            f"Gibt es eine alternative Aktion die das gleiche Ziel erreicht? "
            f"Wenn ja, fuehre NUR die alternative Aktion aus. "
            f"Wenn nein, antworte mit 'Keine Alternative moeglich.' ohne Tool-Calls."
        )

        try:
            tools = get_assistant_tools()
            replan_messages = list(planner_messages) + [{
                "role": "user",
                "content": replan_prompt,
            }]

            from .config import resolve_model
            replan_model = resolve_model(_planner_cfg.get("model", ""), fallback_tier="smart")

            response = await asyncio.wait_for(
                self.ollama.chat(
                    messages=replan_messages,
                    model=replan_model,
                    tools=tools,
                    max_tokens=256,
                    temperature=0.3,
                ),
                timeout=15.0,
            )

            alt_text = (response.get("message", {}).get("content") or "").strip()
            alt_calls = response.get("message", {}).get("tool_calls") or []

            if not alt_calls or "keine alternative" in alt_text.lower():
                logger.info("Re-Planning: Keine Alternative fuer '%s'", failed_func)
                return None

            # Maximal eine alternative Aktion ausfuehren
            tc = alt_calls[0]
            func = tc.get("function", {})
            alt_name = func.get("name", "")
            alt_args = func.get("arguments", {})

            if not alt_name:
                return None

            logger.info(
                "Re-Planning: Alternative fuer '%s' -> '%s'(%s)",
                failed_func, alt_name, alt_args,
            )

            alt_result = await self.executor.execute(alt_name, alt_args)
            if alt_result.get("success"):
                alt_step = PlanStep(
                    function=alt_name,
                    args=alt_args,
                    result=alt_result,
                    status="done",
                )
                plan.steps.append(alt_step)
                return f"{alt_name}: {alt_result.get('message', 'OK')}"

            logger.info("Re-Planning: Alternative '%s' auch fehlgeschlagen", alt_name)
            return None

        except Exception as e:
            logger.warning("Re-Planning Fehler: %s", e)
            return None

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

    # ------------------------------------------------------------------
    # Phase 11C: Cost Estimation, Resource Conflicts, Partial Success
    # ------------------------------------------------------------------

    def _estimate_cost(
        self, action: str, duration_minutes: int = 30
    ) -> Optional[dict]:
        """Schaetzt die Kosten einer Aktion basierend auf Geraetetyp.

        Args:
            action: Funktionsname (z.B. 'set_climate', 'set_light').
            duration_minutes: Geschaetzte Dauer in Minuten.

        Returns:
            Dict mit cost_estimate, unit, description oder None.
        """
        cost_per_hour = {
            "set_climate": 0.15,
            "set_light": 0.01,
            "play_media": 0.02,
            "set_cover": 0.005,
            "set_fan": 0.03,
        }

        rate = cost_per_hour.get(action)
        if rate is None:
            return None

        hours = duration_minutes / 60.0
        estimate = round(rate * hours, 4)

        return {
            "cost_estimate": estimate,
            "unit": "EUR",
            "description": f"{action} fuer {duration_minutes}min ~ {estimate:.4f} EUR",
        }

    def _check_resource_conflicts(self, actions: list[dict]) -> list[str]:
        """Prueft ob geplante Aktionen in Konflikt stehen.

        Erkennt z.B. zwei Klima-Einstellungen fuer denselben Raum
        oder widerspruechliche Licht-Befehle.

        Args:
            actions: Liste von Aktions-Dicts mit 'function' und 'args'.

        Returns:
            Liste von Konfliktbeschreibungen.
        """
        conflicts: list[str] = []
        seen: dict[str, list[dict]] = {}

        for action in actions:
            func = action.get("function", "")
            args = action.get("args", {})
            entity = args.get("entity_id", "") or args.get("area", "")

            if not entity:
                continue

            key = f"{func}:{entity}"
            if key in seen:
                prev_args = seen[key][0].get("args", {})
                conflicts.append(
                    f"Konflikt: {func} fuer '{entity}' wird mehrfach aufgerufen "
                    f"(vorher: {prev_args}, jetzt: {args})"
                )
            seen.setdefault(key, []).append(action)

        return conflicts

    def _handle_partial_success(self, results: list[dict]) -> dict:
        """Fasst Ergebnisse eines Multi-Step-Plans zusammen.

        Args:
            results: Liste von Ergebnis-Dicts mit 'success' Key.

        Returns:
            Dict mit total, succeeded, failed, summary.
        """
        total = len(results)
        succeeded = sum(1 for r in results if r.get("success", False))
        failed = total - succeeded

        if failed == 0:
            summary = f"Alle {total} Aktionen erfolgreich ausgefuehrt."
        elif succeeded == 0:
            summary = f"Alle {total} Aktionen fehlgeschlagen."
        else:
            summary = (
                f"{succeeded} von {total} Aktionen erfolgreich, "
                f"{failed} fehlgeschlagen."
            )

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "summary": summary,
        }
