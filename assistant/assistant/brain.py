"""
MindHome Assistant Brain - Das zentrale Gehirn.
Verbindet alle Komponenten: Context Builder, Model Router, Personality,
Function Calling, Memory, Autonomy, Memory Extractor und Action Planner.

Phase 6: Easter Eggs, Opinion Engine, Antwort-Varianz, Formality Score,
         Zeitgefuehl, Emotionale Intelligenz, Running Gags.
Phase 7: Routinen (Morning Briefing, Gute-Nacht, Gaeste-Modus,
         Szenen-Intelligenz, Raum-Profile, Saisonale Anpassung).
"""

import asyncio
import json
import logging
from typing import Optional

from .action_planner import ActionPlanner
from .activity import ActivityEngine
from .autonomy import AutonomyManager
from .config import settings
from .context_builder import ContextBuilder
from .feedback import FeedbackTracker
from .function_calling import ASSISTANT_TOOLS, FunctionExecutor
from .function_validator import FunctionValidator
from .ha_client import HomeAssistantClient
from .memory import MemoryManager
from .memory_extractor import MemoryExtractor
from .model_router import ModelRouter
from .mood_detector import MoodDetector
from .ollama_client import OllamaClient
from .personality import PersonalityEngine
from .proactive import ProactiveManager
from .routine_engine import RoutineEngine
from .summarizer import DailySummarizer
from .time_awareness import TimeAwareness
from .websocket import emit_thinking, emit_speaking, emit_action

logger = logging.getLogger(__name__)

# Phase 7.5: Szenen-Intelligenz — Prompt fuer natuerliches Situationsverstaendnis
SCENE_INTELLIGENCE_PROMPT = """

SZENEN-INTELLIGENZ:
Verstehe natuerliche Situationsbeschreibungen und reagiere mit passenden Aktionen:
- "Mir ist kalt" → Heizung im aktuellen Raum um 2°C erhoehen
- "Mir ist warm" → Heizung runter ODER Fenster-Empfehlung
- "Zu hell" → Rolladen runter ODER Licht dimmen (je nach Tageszeit)
- "Zu dunkel" → Licht an oder heller
- "Zu laut" → Musik leiser oder Fenster-Empfehlung
- "Romantischer Abend" → Licht 20%, warmweiss, leise Musik vorschlagen
- "Ich bin krank" → Temperatur 23°C, sanftes Licht, weniger Meldungen
- "Filmabend" → Licht dimmen, Rolladen runter, TV vorbereiten
- "Ich arbeite" → Helles Tageslicht, 21°C, Benachrichtigungen reduzieren
- "Party" → Musik an, Lichter bunt/hell, Gaeste-WLAN

Nutze den aktuellen Raum-Kontext fuer die richtige Aktion.
Frage nur bei Mehrdeutigkeit nach (z.B. "Welchen Raum?")."""


class AssistantBrain:
    """Das zentrale Gehirn von MindHome Assistant."""

    def __init__(self):
        # Clients
        self.ha = HomeAssistantClient()
        self.ollama = OllamaClient()

        # Komponenten
        self.context_builder = ContextBuilder(self.ha)
        self.model_router = ModelRouter()
        self.personality = PersonalityEngine()
        self.executor = FunctionExecutor(self.ha)
        self.validator = FunctionValidator()
        self.memory = MemoryManager()
        self.autonomy = AutonomyManager()
        self.feedback = FeedbackTracker()
        self.activity = ActivityEngine(self.ha)
        self.proactive = ProactiveManager(self)
        self.summarizer = DailySummarizer(self.ollama)
        self.memory_extractor: Optional[MemoryExtractor] = None
        self.mood = MoodDetector()
        self.action_planner = ActionPlanner(self.ollama, self.executor, self.validator)
        self.time_awareness = TimeAwareness(self.ha)
        self.routines = RoutineEngine(self.ha, self.ollama)

    async def initialize(self):
        """Initialisiert alle Komponenten."""
        await self.memory.initialize()

        # Semantic Memory mit Context Builder verbinden
        self.context_builder.set_semantic_memory(self.memory.semantic)

        # Activity Engine mit Context Builder verbinden
        self.context_builder.set_activity_engine(self.activity)

        # Mood Detector initialisieren
        await self.mood.initialize(redis_client=self.memory.redis)
        self.personality.set_mood_detector(self.mood)

        # Phase 6: Redis fuer Personality Engine (Formality Score, Counter)
        self.personality.set_redis(self.memory.redis)

        # Memory Extractor initialisieren
        self.memory_extractor = MemoryExtractor(self.ollama, self.memory.semantic)

        # Feedback Tracker initialisieren
        await self.feedback.initialize(redis_client=self.memory.redis)

        # Daily Summarizer initialisieren
        self.summarizer.memory = self.memory
        await self.summarizer.initialize(
            redis_client=self.memory.redis,
            chroma_collection=self.memory.chroma_collection,
        )

        # Phase 6: TimeAwareness initialisieren und starten
        await self.time_awareness.initialize(redis_client=self.memory.redis)
        self.time_awareness.set_notify_callback(self._handle_time_alert)
        await self.time_awareness.start()

        # Phase 7: RoutineEngine initialisieren
        await self.routines.initialize(redis_client=self.memory.redis)
        self.routines.set_executor(self.executor)

        await self.proactive.start()
        logger.info("Jarvis initialisiert (alle Systeme aktiv)")

    async def process(self, text: str, person: Optional[str] = None, room: Optional[str] = None) -> dict:
        """
        Verarbeitet eine User-Eingabe.

        Args:
            text: User-Text (z.B. "Mach das Licht aus")
            person: Name der Person (optional)
            room: Raum aus dem die Anfrage kommt (optional)

        Returns:
            Dict mit response, actions, model_used
        """
        logger.info("Input: '%s' (Person: %s, Raum: %s)", text, person or "unbekannt", room or "unbekannt")

        # Phase 7: Gute-Nacht-Intent (VOR allem anderen)
        if self.routines.is_goodnight_intent(text):
            logger.info("Gute-Nacht-Intent erkannt")
            result = await self.routines.execute_goodnight(person or "")
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", result["text"])
            await emit_speaking(result["text"])
            return {
                "response": result["text"],
                "actions": result["actions"],
                "model_used": "routine_engine",
                "context_room": room or "unbekannt",
            }

        # Phase 7: Gaeste-Modus Trigger
        if self.routines.is_guest_trigger(text):
            logger.info("Gaeste-Modus Trigger erkannt")
            response_text = await self.routines.activate_guest_mode()
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", response_text)
            await emit_speaking(response_text)
            return {
                "response": response_text,
                "actions": [],
                "model_used": "routine_engine",
                "context_room": room or "unbekannt",
            }

        # Phase 7: Gaeste-Modus Deaktivierung
        guest_off_triggers = ["gaeste sind weg", "besuch ist weg", "normalbetrieb", "gaeste modus aus"]
        if any(t in text.lower() for t in guest_off_triggers):
            if await self.routines.is_guest_mode_active():
                response_text = await self.routines.deactivate_guest_mode()
                await self.memory.add_conversation("user", text)
                await self.memory.add_conversation("assistant", response_text)
                await emit_speaking(response_text)
                return {
                    "response": response_text,
                    "actions": [],
                    "model_used": "routine_engine",
                    "context_room": room or "unbekannt",
                }

        # Phase 6: Easter-Egg-Check (VOR dem LLM — spart Latenz)
        egg_response = self.personality.check_easter_egg(text)
        if egg_response:
            logger.info("Easter Egg getriggert: '%s'", egg_response)
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", egg_response)
            await emit_speaking(egg_response)
            return {
                "response": egg_response,
                "actions": [],
                "model_used": "easter_egg",
                "context_room": room or "unbekannt",
            }

        # Phase 6.9: Running Gag Check (VOR LLM)
        gag_response = await self.personality.check_running_gag(text)

        # WebSocket: Denk-Status senden
        await emit_thinking()

        # 1. Kontext sammeln (inkl. semantischer Erinnerungen)
        context = await self.context_builder.build(
            trigger="voice", user_text=text, person=person or ""
        )
        if room:
            context["room"] = room
        if person:
            context.setdefault("person", {})["name"] = person

        # 2. Stimmungsanalyse
        mood_result = await self.mood.analyze(text, person or "")
        context["mood"] = mood_result

        # 3. Modell waehlen
        model = self.model_router.select_model(text)

        # Phase 6: Formality Score laden
        formality_score = await self.personality.get_formality_score()

        # 4. System Prompt bauen (mit Phase 6 Erweiterungen)
        system_prompt = self.personality.build_system_prompt(
            context, formality_score=formality_score
        )

        # Phase 6.7: Emotionale Intelligenz — Mood-Hint in System Prompt
        mood_hint = self.mood.get_mood_prompt_hint()
        if mood_hint:
            system_prompt += f"\n\nEMOTIONALE LAGE: {mood_hint}"

        # Phase 6.6: Zeitgefuehl — Hinweise in System Prompt
        time_hints = await self.time_awareness.get_context_hints()
        if time_hints:
            system_prompt += "\n\nZEITGEFUEHL:\n" + "\n".join(f"- {h}" for h in time_hints)

        # Phase 7: Gaeste-Modus Prompt-Erweiterung
        if await self.routines.is_guest_mode_active():
            system_prompt += "\n\n" + self.routines.get_guest_mode_prompt()

        # Phase 7.5: Szenen-Intelligenz — erweiterte Prompt-Anweisung
        system_prompt += SCENE_INTELLIGENCE_PROMPT

        # Semantische Erinnerungen zum System Prompt hinzufuegen
        memories = context.get("memories", {})
        memory_context = self._build_memory_context(memories)
        if memory_context:
            system_prompt += memory_context

        # Langzeit-Summaries bei Fragen ueber die Vergangenheit
        summary_context = await self._get_summary_context(text)
        if summary_context:
            system_prompt += summary_context

        # 5. Letzte Gespraeche laden (Working Memory)
        recent = await self.memory.get_recent_conversations(limit=5)
        messages = [{"role": "system", "content": system_prompt}]
        for conv in recent:
            messages.append({"role": conv["role"], "content": conv["content"]})
        messages.append({"role": "user", "content": text})

        # 6. Komplexe Anfragen ueber Action Planner routen
        if self.action_planner.is_complex_request(text):
            logger.info("Komplexe Anfrage erkannt -> Action Planner")
            planner_result = await self.action_planner.plan_and_execute(
                text=text,
                system_prompt=system_prompt,
                context=context,
                messages=messages,
            )
            response_text = planner_result.get("response", "")
            executed_actions = planner_result.get("actions", [])
            model = "qwen2.5:14b"
        else:
            # 6b. Einfache Anfragen: Direkt LLM aufrufen
            response = await self.ollama.chat(
                messages=messages,
                model=model,
                tools=ASSISTANT_TOOLS,
            )

            if "error" in response:
                logger.error("LLM Fehler: %s", response["error"])
                return {
                    "response": "Da stimmt etwas nicht. Ich kann gerade nicht denken.",
                    "actions": [],
                    "model_used": model,
                    "error": response["error"],
                }

            # 7. Antwort verarbeiten
            message = response.get("message", {})
            response_text = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
            executed_actions = []

            # 8. Function Calls ausfuehren
            if tool_calls:
                for tool_call in tool_calls:
                    func = tool_call.get("function", {})
                    func_name = func.get("name", "")
                    func_args = func.get("arguments", {})

                    logger.info("Function Call: %s(%s)", func_name, func_args)

                    # Validierung
                    validation = self.validator.validate(func_name, func_args)
                    if not validation.ok:
                        if validation.needs_confirmation:
                            response_text = f"Sicherheitsbestaetigung noetig: {validation.reason}"
                            executed_actions.append({
                                "function": func_name,
                                "args": func_args,
                                "result": "needs_confirmation",
                            })
                            continue
                        else:
                            logger.warning("Validation failed: %s", validation.reason)
                            executed_actions.append({
                                "function": func_name,
                                "args": func_args,
                                "result": f"blocked: {validation.reason}",
                            })
                            continue

                    # Ausfuehren
                    result = await self.executor.execute(func_name, func_args)
                    executed_actions.append({
                        "function": func_name,
                        "args": func_args,
                        "result": result,
                    })

                    # WebSocket: Aktion melden
                    await emit_action(func_name, func_args, result)

                    # Phase 6: Opinion Check — Jarvis kommentiert Aktionen
                    opinion = self.personality.check_opinion(func_name, func_args)
                    if opinion:
                        logger.info("Jarvis Meinung: '%s'", opinion)
                        if response_text:
                            response_text = f"{response_text} {opinion}"
                        else:
                            response_text = opinion

            # Phase 6: Variierte Bestaetigung statt immer "Erledigt."
            if executed_actions and not response_text:
                all_success = all(
                    a["result"].get("success", False)
                    for a in executed_actions
                    if isinstance(a["result"], dict)
                )
                any_failed = any(
                    isinstance(a["result"], dict) and not a["result"].get("success", False)
                    for a in executed_actions
                )

                if all_success:
                    response_text = self.personality.get_varied_confirmation(success=True)
                elif any_failed:
                    failed = [
                        a["result"].get("message", "")
                        for a in executed_actions
                        if isinstance(a["result"], dict) and not a["result"].get("success", False)
                    ]
                    if failed:
                        response_text = f"Problem: {', '.join(failed)}"
                    else:
                        response_text = self.personality.get_varied_confirmation(partial=True)
                else:
                    response_text = self.personality.get_varied_confirmation(success=True)

        # Phase 6.9: Running Gag an Antwort anhaengen
        if gag_response and response_text:
            response_text = f"{response_text} {gag_response}"

        # Phase 6.7: Emotionale Intelligenz — Aktions-Vorschlaege loggen
        suggested_actions = self.mood.get_suggested_actions()
        if suggested_actions:
            for sa in suggested_actions:
                logger.info(
                    "Mood-Vorschlag [%s]: %s (%s)",
                    sa.get("priority", "?"), sa.get("action", "?"), sa.get("reason", ""),
                )

        # 9. Im Gedaechtnis speichern
        await self.memory.add_conversation("user", text)
        await self.memory.add_conversation("assistant", response_text)

        # 10. Episode speichern (Langzeitgedaechtnis)
        if len(text.split()) > 3:
            episode = f"User: {text}\nAssistant: {response_text}"
            await self.memory.store_episode(episode, {
                "person": person or "unknown",
                "room": context.get("room", "unknown"),
                "actions": json.dumps([a["function"] for a in executed_actions]),
            })

        # 11. Fakten extrahieren (async im Hintergrund)
        if self.memory_extractor and len(text.split()) > 3:
            asyncio.create_task(
                self._extract_facts_background(
                    text, response_text, person or "unknown", context
                )
            )

        result = {
            "response": response_text,
            "actions": executed_actions,
            "model_used": model,
            "context_room": context.get("room", "unbekannt"),
        }
        # WebSocket: Antwort senden
        await emit_speaking(response_text)

        logger.info("Output: '%s' (Aktionen: %d)", response_text, len(executed_actions))
        return result

    async def health_check(self) -> dict:
        """Prueft den Zustand aller Komponenten."""
        ollama_ok = await self.ollama.is_available()
        ha_ok = await self.ha.is_available()

        models = await self.ollama.list_models() if ollama_ok else []

        # Phase 6: Formality Score im Health Check
        formality = await self.personality.get_formality_score()
        # Phase 7: Guest Mode Status
        guest_mode = await self.routines.is_guest_mode_active()

        return {
            "status": "ok" if (ollama_ok and ha_ok) else "degraded",
            "components": {
                "ollama": "connected" if ollama_ok else "disconnected",
                "home_assistant": "connected" if ha_ok else "disconnected",
                "redis": "connected" if self.memory.redis else "disconnected",
                "chromadb": "connected" if self.memory.chroma_collection else "disconnected",
                "semantic_memory": "connected" if self.memory.semantic.chroma_collection else "disconnected",
                "memory_extractor": "active" if self.memory_extractor else "inactive",
                "mood_detector": f"active (mood: {self.mood.get_current_mood()['mood']})",
                "action_planner": "active",
                "feedback_tracker": "running" if self.feedback._running else "stopped",
                "activity_engine": "active",
                "summarizer": "running" if self.summarizer._running else "stopped",
                "proactive": "running" if self.proactive._running else "stopped",
                "time_awareness": "running" if self.time_awareness._running else "stopped",
                "routine_engine": "active",
                "guest_mode": "active" if guest_mode else "inactive",
            },
            "models_available": models,
            "autonomy": self.autonomy.get_level_info(),
            "personality": {
                "sarcasm_level": self.personality.sarcasm_level,
                "opinion_intensity": self.personality.opinion_intensity,
                "formality_score": formality,
                "easter_eggs": len(self.personality._easter_eggs),
                "opinion_rules": len(self.personality._opinion_rules),
            },
        }

    def _build_memory_context(self, memories: dict) -> str:
        """Baut den Gedaechtnis-Abschnitt fuer den System Prompt."""
        parts = []

        relevant = memories.get("relevant_facts", [])
        person_facts = memories.get("person_facts", [])

        if relevant:
            parts.append("\nRELEVANTE ERINNERUNGEN:")
            for fact in relevant:
                parts.append(f"- {fact}")

        if person_facts:
            parts.append("\nBEKANNTE FAKTEN UEBER DEN USER:")
            for fact in person_facts:
                parts.append(f"- {fact}")

        if parts:
            parts.insert(0, "\n\nGEDAECHTNIS (nutze diese Infos wenn relevant):")
            return "\n".join(parts)

        return ""

    async def _get_summary_context(self, text: str) -> str:
        """Holt relevante Langzeit-Summaries wenn die Frage die Vergangenheit betrifft."""
        past_keywords = [
            "gestern", "letzte woche", "letzten monat", "letztes jahr",
            "vor ", "frueher", "damals", "wann war", "wie war",
            "erinnerst du", "weisst du noch", "war der", "war die",
            "im januar", "im februar", "im maerz", "im april", "im mai",
            "im juni", "im juli", "im august", "im september",
            "im oktober", "im november", "im dezember",
            "letzte", "letzten", "letzter", "vorige", "vergangene",
        ]

        text_lower = text.lower()
        if not any(kw in text_lower for kw in past_keywords):
            return ""

        try:
            summaries = await self.summarizer.search_summaries(text, limit=3)
            if not summaries:
                return ""

            parts = ["\n\nLANGZEIT-ERINNERUNGEN (vergangene Tage/Wochen):"]
            for s in summaries:
                date = s.get("date", "")
                stype = s.get("summary_type", "")
                content = s.get("content", "")
                parts.append(f"[{stype} {date}]: {content}")

            return "\n".join(parts)
        except Exception as e:
            logger.debug("Fehler bei Summary-Kontext: %s", e)
            return ""

    async def _extract_facts_background(
        self,
        user_text: str,
        assistant_response: str,
        person: str,
        context: dict,
    ):
        """Extrahiert Fakten im Hintergrund (non-blocking)."""
        try:
            facts = await self.memory_extractor.extract_and_store(
                user_text=user_text,
                assistant_response=assistant_response,
                person=person,
                context=context,
            )
            if facts:
                logger.info(
                    "Hintergrund-Extraktion: %d Fakt(en) gespeichert", len(facts)
                )
        except Exception as e:
            logger.error("Fehler bei Hintergrund-Fakten-Extraktion: %s", e)

    async def _handle_time_alert(self, alert: dict):
        """Callback fuer TimeAwareness-Alerts — leitet an proaktive Meldung weiter."""
        message = alert.get("message", "")
        if message:
            await emit_speaking(message)
            logger.info("TimeAwareness -> Proaktive Meldung: %s", message)

    async def shutdown(self):
        """Faehrt MindHome Assistant herunter."""
        await self.time_awareness.stop()
        await self.proactive.stop()
        await self.summarizer.stop()
        await self.feedback.stop()
        await self.memory.close()
        logger.info("MindHome Assistant heruntergefahren")
