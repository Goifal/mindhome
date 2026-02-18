"""
MindHome Assistant Brain - Das zentrale Gehirn.
Verbindet alle Komponenten: Context Builder, Model Router, Personality,
Function Calling, Memory, Autonomy, Memory Extractor und Action Planner.

Phase 6: Easter Eggs, Opinion Engine, Antwort-Varianz, Formality Score,
         Zeitgefuehl, Emotionale Intelligenz, Running Gags.
Phase 7: Routinen (Morning Briefing, Gute-Nacht, Gaeste-Modus,
         Szenen-Intelligenz, Raum-Profile, Saisonale Anpassung).
Phase 8: Gedaechtnis & Vorausdenken (Explizites Notizbuch, Intent-Routing,
         Was-waere-wenn, Anticipation, Intent-Tracking, Konversations-
         Kontinuitaet, Langzeit-Persoenlichkeitsanpassung).
Phase 9: Stimme & Akustik (TTS Enhancement, Sound Design, Auto-Volume,
         Narration Mode, Voice Emotion, Speaker Recognition).
Phase 10: Multi-Room & Kommunikation (Room Presence, TTS Routing,
          Person Delegation, Trust Levels, Diagnostik, Wartungs-Assistent).
"""

import asyncio
import json
import logging
import re
from typing import Optional

from .action_planner import ActionPlanner
from .activity import ActivityEngine
from .autonomy import AutonomyManager
from .config import settings, yaml_config
from .context_builder import ContextBuilder
from .cooking_assistant import CookingAssistant
from .diagnostics import DiagnosticsEngine
from .health_monitor import HealthMonitor
from .feedback import FeedbackTracker
from .function_calling import ASSISTANT_TOOLS, FunctionExecutor
from .function_validator import FunctionValidator
from .ha_client import HomeAssistantClient
from .inventory import InventoryManager
from .knowledge_base import KnowledgeBase
from .memory import MemoryManager
from .memory_extractor import MemoryExtractor
from .model_router import ModelRouter
from .mood_detector import MoodDetector
from .ollama_client import OllamaClient
from .ambient_audio import AmbientAudioClassifier
from .conflict_resolver import ConflictResolver
from .personality import PersonalityEngine
from .proactive import ProactiveManager
from .anticipation import AnticipationEngine
from .intent_tracker import IntentTracker
from .routine_engine import RoutineEngine
from .self_automation import SelfAutomation
from .sound_manager import SoundManager
from .speaker_recognition import SpeakerRecognition
from .summarizer import DailySummarizer
from .time_awareness import TimeAwareness
from .tts_enhancer import TTSEnhancer
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
        self.anticipation = AnticipationEngine()
        self.intent_tracker = IntentTracker(self.ollama)

        # Phase 9: Stimme & Akustik
        self.tts_enhancer = TTSEnhancer()
        self.sound_manager = SoundManager(self.ha)
        self.speaker_recognition = SpeakerRecognition(ha_client=self.ha)

        # Phase 10: Diagnostik + Wartungs-Assistent
        self.diagnostics = DiagnosticsEngine(self.ha)

        # Phase 14.3: Ambient Audio (Umgebungsgeraeusch-Erkennung)
        self.ambient_audio = AmbientAudioClassifier(self.ha)

        # Phase 16.1: Multi-User Konfliktloesung
        self.conflict_resolver = ConflictResolver(self.autonomy, self.ollama)

        # Phase 15.1: Gesundheits-Monitor
        self.health_monitor = HealthMonitor(self.ha)

        # Phase 15.2: Vorrats-Tracking
        self.inventory = InventoryManager(self.ha)

        # Phase 13.2: Self Automation (Automationen aus natuerlicher Sprache)
        self.self_automation = SelfAutomation(self.ha, self.ollama)

        # Phase 11: Koch-Assistent
        self.cooking = CookingAssistant(self.ollama)

        # Phase 11.1: Knowledge Base (RAG)
        self.knowledge_base = KnowledgeBase()

    async def initialize(self):
        """Initialisiert alle Komponenten."""
        await self.memory.initialize()

        # Model-Router: Verfuegbare Modelle von Ollama holen und pruefen
        try:
            available_models = await self.ollama.list_models()
            await self.model_router.initialize(available_models)
            logger.info("Modell-Erkennung: %d Modelle verfuegbar, bestes: %s",
                        len(available_models), self.model_router.get_best_available())
        except Exception as e:
            logger.warning("Modell-Erkennung fehlgeschlagen: %s (alle Modelle angenommen)", e)

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

        # Phase 8: Anticipation Engine + Intent Tracker
        await self.anticipation.initialize(redis_client=self.memory.redis)
        self.anticipation.set_notify_callback(self._handle_anticipation_suggestion)
        await self.intent_tracker.initialize(redis_client=self.memory.redis)
        self.intent_tracker.set_notify_callback(self._handle_intent_reminder)

        # Phase 9: Speaker Recognition initialisieren
        await self.speaker_recognition.initialize(redis_client=self.memory.redis)

        # Phase 11: Koch-Assistent mit Semantic Memory verbinden
        self.cooking.semantic_memory = self.memory.semantic
        self.cooking.set_notify_callback(self._handle_cooking_timer)

        # Phase 11.1: Knowledge Base initialisieren
        await self.knowledge_base.initialize()

        # Phase 15.2: Inventory Manager initialisieren
        await self.inventory.initialize(redis_client=self.memory.redis)

        # Phase 13.2: Self Automation initialisieren
        await self.self_automation.initialize(redis_client=self.memory.redis)

        # Phase 14.3: Ambient Audio initialisieren und starten
        await self.ambient_audio.initialize(redis_client=self.memory.redis)
        self.ambient_audio.set_notify_callback(self._handle_ambient_audio_event)
        await self.ambient_audio.start()

        # Phase 16.1: Conflict Resolver initialisieren
        await self.conflict_resolver.initialize(redis_client=self.memory.redis)

        # Phase 15.1: Health Monitor initialisieren und starten
        await self.health_monitor.initialize(redis_client=self.memory.redis)
        self.health_monitor.set_notify_callback(self._handle_health_alert)
        await self.health_monitor.start()

        await self.proactive.start()
        logger.info("Jarvis initialisiert (alle Systeme aktiv)")

    async def process(self, text: str, person: Optional[str] = None, room: Optional[str] = None, files: Optional[list] = None) -> dict:
        """
        Verarbeitet eine User-Eingabe.

        Args:
            text: User-Text (z.B. "Mach das Licht aus")
            person: Name der Person (optional)
            room: Raum aus dem die Anfrage kommt (optional)
            files: Liste von Datei-Metadaten aus file_handler.save_upload() (optional)

        Returns:
            Dict mit response, actions, model_used
        """
        logger.info("Input: '%s' (Person: %s, Raum: %s)", text, person or "unbekannt", room or "unbekannt")

        # Phase 9: Fluestermodus-Check
        whisper_cmd = self.tts_enhancer.check_whisper_command(text)
        if whisper_cmd == "activate":
            response_text = "Verstanden. Ich fluester ab jetzt."
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", response_text)
            tts_data = self.tts_enhancer.enhance(response_text, message_type="confirmation")
            await emit_speaking(response_text)
            return {
                "response": response_text,
                "actions": [],
                "model_used": "tts_enhancer",
                "context_room": room or "unbekannt",
                "tts": tts_data,
            }
        elif whisper_cmd == "deactivate":
            response_text = "Normale Lautstaerke wiederhergestellt."
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", response_text)
            tts_data = self.tts_enhancer.enhance(response_text, message_type="confirmation")
            await emit_speaking(response_text)
            return {
                "response": response_text,
                "actions": [],
                "model_used": "tts_enhancer",
                "context_room": room or "unbekannt",
                "tts": tts_data,
            }

        # Phase 9: Speaker Recognition — Person ermitteln wenn nicht angegeben
        if person:
            asyncio.create_task(
                self.speaker_recognition.set_current_speaker(person.lower())
            )
        elif self.speaker_recognition.enabled:
            identified = await self.speaker_recognition.identify(room=room)
            if identified.get("person") and not identified.get("fallback"):
                person = identified["person"]
                logger.info("Speaker erkannt: %s (Confidence: %.2f, Methode: %s)",
                            person, identified.get("confidence", 0),
                            identified.get("method", "unknown"))

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

        # Phase 13.2: Automation-Bestaetigung (VOR allem anderen)
        automation_result = await self._handle_automation_confirmation(text)
        if automation_result:
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", automation_result)
            await emit_speaking(automation_result)
            return {
                "response": automation_result,
                "actions": [],
                "model_used": "self_automation",
                "context_room": room or "unbekannt",
            }

        # Phase 8: Explizites Notizbuch — Memory-Befehle (VOR allem anderen)
        memory_result = await self._handle_memory_command(text, person or "")
        if memory_result:
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", memory_result)
            await emit_speaking(memory_result)
            return {
                "response": memory_result,
                "actions": [],
                "model_used": "memory_direct",
                "context_room": room or "unbekannt",
            }

        # Phase 11: Koch-Navigation — aktive Session hat Vorrang
        if self.cooking.is_cooking_navigation(text):
            logger.info("Koch-Navigation: '%s'", text)
            cooking_response = await self.cooking.handle_navigation(text)
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", cooking_response)
            tts_data = self.tts_enhancer.enhance(cooking_response, message_type="casual")
            await emit_speaking(cooking_response)
            return {
                "response": cooking_response,
                "actions": [],
                "model_used": "cooking_assistant",
                "context_room": room or "unbekannt",
                "tts": tts_data,
            }

        # Phase 11: Koch-Intent — neue Koch-Session starten
        if self.cooking.is_cooking_intent(text):
            logger.info("Koch-Intent erkannt: '%s'", text)
            cooking_model = self.model_router.get_best_available()
            cooking_response = await self.cooking.start_cooking(
                text, person or "", cooking_model
            )
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", cooking_response)
            tts_data = self.tts_enhancer.enhance(cooking_response, message_type="casual")
            await emit_speaking(cooking_response)
            return {
                "response": cooking_response,
                "actions": [],
                "model_used": f"cooking_assistant ({cooking_model})",
                "context_room": room or "unbekannt",
                "tts": tts_data,
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

        # Phase 9: "listening" Sound abspielen wenn Verarbeitung startet
        asyncio.create_task(
            self.sound_manager.play_event_sound("listening", room=room)
        )

        # Phase 6.9: Running Gag Check (VOR LLM)
        gag_response = await self.personality.check_running_gag(text)

        # Phase 8: Konversations-Kontinuitaet — offene Themen anbieten
        continuity_hint = await self._check_conversation_continuity()

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

        # Phase 6: Selbstironie-Zaehler aus Redis
        irony_count = await self.personality._get_self_irony_count_today()

        # 4. System Prompt bauen (mit Phase 6 Erweiterungen)
        system_prompt = self.personality.build_system_prompt(
            context, formality_score=formality_score,
            irony_count_today=irony_count,
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

        # Phase 16.2: Tutorial-Modus fuer neue User
        tutorial_hint = await self._get_tutorial_hint(person or "unknown")
        if tutorial_hint:
            system_prompt += tutorial_hint

        # Warning-Dedup: Bereits gegebene Warnungen nicht wiederholen
        alerts = context.get("alerts", [])
        if alerts:
            dedup_notes = await self.personality.get_warning_dedup_notes(alerts)
            if dedup_notes:
                system_prompt += "\n\nWARNUNGS-DEDUP:\n" + "\n".join(dedup_notes)

        # Semantische Erinnerungen zum System Prompt hinzufuegen
        memories = context.get("memories", {})
        memory_context = self._build_memory_context(memories)
        if memory_context:
            system_prompt += memory_context

        # Langzeit-Summaries bei Fragen ueber die Vergangenheit
        summary_context = await self._get_summary_context(text)
        if summary_context:
            system_prompt += summary_context

        # Phase 11.1: RAG Knowledge Base — Wissen aus Dokumenten
        rag_context = await self._get_rag_context(text)
        if rag_context:
            system_prompt += rag_context

        # Phase 12: Datei-Kontext in Prompt einbauen
        if files:
            from .file_handler import build_file_context
            file_context = build_file_context(files)
            if file_context:
                system_prompt += "\n" + file_context

        # Phase 8: Konversations-Kontinuitaet in Prompt einbauen
        if continuity_hint:
            if " | " in continuity_hint:
                topics = continuity_hint.split(" | ")
                system_prompt += f"\n\nOFFENE THEMEN ({len(topics)}):\n"
                for t in topics:
                    system_prompt += f"- {t}\n"
                system_prompt += "Erwaehne kurz die offenen Themen: 'Wir hatten noch ein paar offene Punkte — [Topics]. Noch relevant?'"
            else:
                system_prompt += f"\n\nOFFENES THEMA: {continuity_hint}"
                system_prompt += "\nErwaehne kurz das offene Thema, z.B.: 'Wir waren vorhin bei [Thema] — noch relevant?'"

        # Phase 8: Was-waere-wenn Erkennung
        whatif_prompt = self._get_whatif_prompt(text)
        if whatif_prompt:
            system_prompt += whatif_prompt

        # 5. Letzte Gespraeche laden (Working Memory)
        recent = await self.memory.get_recent_conversations(limit=5)
        messages = [{"role": "system", "content": system_prompt}]
        for conv in recent:
            messages.append({"role": conv["role"], "content": conv["content"]})
        messages.append({"role": "user", "content": text})

        # Phase 8: Intent-Routing — Wissensfragen ohne Tools beantworten
        intent_type = self._classify_intent(text)

        # Phase 10: Delegations-Intent → Nachricht an Person weiterleiten
        if intent_type == "delegation":
            logger.info("Delegations-Intent erkannt")
            delegation_result = await self._handle_delegation(text, person or "")
            if delegation_result:
                await self.memory.add_conversation("user", text)
                await self.memory.add_conversation("assistant", delegation_result)
                tts_data = self.tts_enhancer.enhance(delegation_result, message_type="confirmation")
                await emit_speaking(delegation_result)
                return {
                    "response": delegation_result,
                    "actions": [],
                    "model_used": "delegation",
                    "context_room": room or "unbekannt",
                    "tts": tts_data,
                }

        # 6. Komplexe Anfragen ueber Action Planner routen
        if self.action_planner.is_complex_request(text):
            logger.info("Komplexe Anfrage erkannt -> Action Planner (Deep: %s)",
                         settings.model_deep)
            planner_result = await self.action_planner.plan_and_execute(
                text=text,
                system_prompt=system_prompt,
                context=context,
                messages=messages,
            )
            response_text = planner_result.get("response", "")
            executed_actions = planner_result.get("actions", [])
            model = settings.model_deep
        elif intent_type == "knowledge":
            # Phase 8: Wissensfragen -> Deep-Model fuer bessere Qualitaet
            logger.info("Wissensfrage erkannt -> LLM direkt (Deep: %s, keine Tools)",
                         settings.model_deep)
            model = settings.model_deep
            response = await self.ollama.chat(
                messages=messages,
                model=model,
            )
            response_text = self._filter_response(response.get("message", {}).get("content", ""))
            executed_actions = []

            if "error" in response:
                logger.error("LLM Fehler: %s", response["error"])
                response_text = "Da bin ich mir nicht sicher."
        elif intent_type == "memory":
            # Phase 8: Erinnerungsfrage -> Memory-Suche + Deep-Model
            logger.info("Erinnerungsfrage erkannt -> Memory-Suche + Deep-Model")
            memory_facts = await self.memory.semantic.search_by_topic(text, limit=5)
            if memory_facts:
                facts_text = "\n".join(f"- {f['content']}" for f in memory_facts)
                system_prompt += f"\n\nGESPEICHERTE FAKTEN ZU DIESER FRAGE:\n{facts_text}"
                system_prompt += "\nBeantworte basierend auf diesen gespeicherten Fakten."
                messages[0] = {"role": "system", "content": system_prompt}

            model = settings.model_deep
            response = await self.ollama.chat(
                messages=messages,
                model=model,
            )
            response_text = self._filter_response(response.get("message", {}).get("content", ""))
            executed_actions = []
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
            # Tools die Daten zurueckgeben und eine LLM-formatierte Antwort brauchen
            QUERY_TOOLS = {"get_entity_state", "send_message_to_person", "get_calendar_events",
                          "create_automation", "list_jarvis_automations"}
            has_query_results = False

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

                    # Phase 10: Trust-Level Pre-Check (mit Raum-Scoping)
                    if person:
                        action_room = func_args.get("room", "") if isinstance(func_args, dict) else ""
                        trust_check = self.autonomy.can_person_act(person, func_name, room=action_room)
                        if not trust_check["allowed"]:
                            logger.warning(
                                "Trust-Check fehlgeschlagen: %s darf '%s' nicht (%s)",
                                person, func_name, trust_check.get("reason", ""),
                            )
                            executed_actions.append({
                                "function": func_name,
                                "args": func_args,
                                "result": f"blocked: {trust_check.get('reason', 'Keine Berechtigung')}",
                            })
                            continue

                    # Phase 16.1: Konflikt-Check (Multi-User)
                    final_args = func_args
                    conflict_msg = None
                    if person and self.conflict_resolver.enabled:
                        conflict = await self.conflict_resolver.check_conflict(
                            person=person,
                            function_name=func_name,
                            function_args=func_args,
                            room=room,
                        )
                        if conflict and conflict.get("conflict"):
                            conflict_msg = conflict.get("message", "")
                            # Modifizierte Args verwenden (Kompromiss/Gewinner)
                            if conflict.get("modified_args"):
                                final_args = conflict["modified_args"]
                                logger.info(
                                    "Konflikt geloest (%s): Args modifiziert %s -> %s",
                                    conflict.get("strategy"), func_args, final_args,
                                )

                    # Ausfuehren
                    result = await self.executor.execute(func_name, final_args)
                    executed_actions.append({
                        "function": func_name,
                        "args": final_args,
                        "result": result,
                    })

                    # Befehl fuer Konflikt-Tracking aufzeichnen
                    if person:
                        self.conflict_resolver.record_command(
                            person=person,
                            function_name=func_name,
                            function_args=final_args,
                            room=room,
                        )

                    # Konflikt-Nachricht an Response anhaengen
                    if conflict_msg:
                        if response_text:
                            response_text = f"{response_text} {conflict_msg}"
                        else:
                            response_text = conflict_msg

                    if func_name in QUERY_TOOLS:
                        has_query_results = True

                    # WebSocket: Aktion melden
                    await emit_action(func_name, final_args, result)

                    # Phase 6: Opinion Check — Jarvis kommentiert Aktionen
                    opinion = self.personality.check_opinion(func_name, func_args)
                    if opinion:
                        logger.info("Jarvis Meinung: '%s'", opinion)
                        if response_text:
                            response_text = f"{response_text} {opinion}"
                        else:
                            response_text = opinion

            # 8b. Tool-Result Feedback Loop: Ergebnisse zurueck ans LLM
            # Damit Jarvis natuerlich antwortet ("Im Buero sind es 22 Grad, Sir.")
            # statt nur "Erledigt." bei Abfragen
            if tool_calls and has_query_results and not response_text:
                try:
                    # Tool-Ergebnisse als Messages aufbauen
                    feedback_messages = list(messages)
                    # LLM-Antwort mit Tool-Calls anhaengen
                    feedback_messages.append(message)
                    # Tool-Results als "tool" Messages
                    for action in executed_actions:
                        result = action.get("result", {})
                        result_text = ""
                        if isinstance(result, dict):
                            result_text = result.get("message", str(result))
                        else:
                            result_text = str(result)
                        feedback_messages.append({
                            "role": "tool",
                            "content": result_text,
                        })

                    # Zweiter LLM-Call: Natuerliche Antwort generieren (ohne Tools)
                    logger.debug("Tool-Feedback: %d Results -> LLM fuer natuerliche Antwort",
                                 len(executed_actions))
                    feedback_response = await self.ollama.chat(
                        messages=feedback_messages,
                        model=model,
                        temperature=0.7,
                        max_tokens=128,
                    )
                    if "error" not in feedback_response:
                        feedback_text = feedback_response.get("message", {}).get("content", "")
                        if feedback_text:
                            response_text = self._filter_response(feedback_text)
                except Exception as e:
                    logger.debug("Tool-Feedback fehlgeschlagen: %s", e)

            # Phase 6: Variierte Bestaetigung statt immer "Erledigt."
            # Nur fuer reine Action-Tools (set_light etc.), nicht fuer Query-Tools
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

        # Phase 12: Response-Filter (Post-Processing) — Floskeln entfernen
        response_text = self._filter_response(response_text)

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

        # Phase 9: Warning-Sound bei Warnungen im Response
        if response_text and any(w in response_text.lower() for w in [
            "warnung", "achtung", "vorsicht", "offen", "alarm", "offline",
        ]):
            asyncio.create_task(
                self.sound_manager.play_event_sound("warning", room=room)
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

        # Phase 11.4: Korrektur-Lernen — erkennt Korrekturen und speichert sie
        if self._is_correction(text):
            asyncio.create_task(
                self._handle_correction(text, response_text, person or "unknown")
            )

        # Phase 8: Action-Logging fuer Anticipation Engine
        for action in executed_actions:
            if isinstance(action.get("result"), dict) and action["result"].get("success"):
                asyncio.create_task(
                    self.anticipation.log_action(
                        action["function"], action.get("args", {}), person or ""
                    )
                )

        # Phase 8: Intent-Extraktion im Hintergrund
        if len(text.split()) > 5:
            asyncio.create_task(
                self._extract_intents_background(text, person or "")
            )

        # Phase 8: Personality-Metrics tracken
        asyncio.create_task(
            self.personality.track_interaction_metrics(
                mood=mood_result.get("mood", "neutral"),
                response_accepted=True,
            )
        )

        # Phase 8: Offenes Thema markieren (wenn Frage ohne klare Antwort)
        if text.endswith("?") and len(text.split()) > 5:
            asyncio.create_task(
                self.memory.mark_conversation_pending(
                    topic=text[:100], context=response_text[:200], person=person or ""
                )
            )

        # Phase 9+10: Activity-basiertes Volume + Silence-Matrix
        urgency = "high" if executed_actions else "medium"
        activity_result = await self.activity.should_deliver(urgency)
        current_activity = activity_result.get("activity", "relaxing")
        activity_volume = activity_result.get("volume", 0.8)

        # TTS Enhancement mit Activity-Kontext
        tts_data = self.tts_enhancer.enhance(
            response_text,
            urgency=urgency,
            activity=current_activity,
        )

        # Activity-Volume ueberschreibt TTS-Volume (ausser Whisper-Modus)
        if not self.tts_enhancer.is_whisper_mode and urgency != "critical":
            tts_data["volume"] = activity_volume

        # Phase 10: Multi-Room TTS — Speaker anhand Raum bestimmen
        if room:
            room_speaker = await self.executor._find_speaker_in_room(room)
            if room_speaker:
                tts_data["target_speaker"] = room_speaker

        # Phase 9: Sound-Events vollstaendig integrieren
        if executed_actions:
            all_success = all(
                isinstance(a.get("result"), dict) and a["result"].get("success", False)
                for a in executed_actions
            )
            any_failed = any(
                isinstance(a.get("result"), dict) and not a["result"].get("success", False)
                for a in executed_actions
            )
            if all_success:
                asyncio.create_task(
                    self.sound_manager.play_event_sound(
                        "confirmed", room=room, volume=tts_data.get("volume")
                    )
                )
            elif any_failed:
                asyncio.create_task(
                    self.sound_manager.play_event_sound(
                        "error", room=room, volume=tts_data.get("volume")
                    )
                )

        result = {
            "response": response_text,
            "actions": executed_actions,
            "model_used": model,
            "context_room": context.get("room", "unbekannt"),
            "tts": tts_data,
        }
        # WebSocket: Antwort senden
        await emit_speaking(response_text)

        logger.info("Output: '%s' (Aktionen: %d, TTS: %s)", response_text,
                     len(executed_actions), tts_data.get("message_type", ""))
        return result

    # ------------------------------------------------------------------
    # Phase 12: Response-Filter (Post-Processing)
    # ------------------------------------------------------------------

    def _filter_response(self, text: str) -> str:
        """
        Filtert LLM-Floskeln und unerwuenschte Muster aus der Antwort.
        Wird nach jedem LLM-Response aufgerufen, vor Speicherung und TTS.
        """
        if not text:
            return text

        filter_config = yaml_config.get("response_filter", {})
        if not filter_config.get("enabled", True):
            return text

        original = text

        # 1. Banned Phrases komplett entfernen
        banned_phrases = filter_config.get("banned_phrases", [
            "Natürlich!", "Natuerlich!", "Gerne!", "Selbstverständlich!",
            "Selbstverstaendlich!", "Klar!", "Gern geschehen!",
            "Kann ich sonst noch etwas für dich tun?",
            "Kann ich sonst noch etwas fuer dich tun?",
            "Kann ich dir sonst noch helfen?",
            "Wenn du noch etwas brauchst",
            "Sag einfach Bescheid",
            "Ich bin froh, dass",
            "Es freut mich",
            "Es ist mir eine Freude",
            "Als KI", "Als künstliche Intelligenz",
            "Als kuenstliche Intelligenz",
            "Ich bin nur ein Programm",
            "Lass mich mal schauen",
            "Lass mich kurz schauen",
            "Das klingt frustrierend",
            "Ich verstehe, wie du dich fuehlst",
            "Ich verstehe, wie du dich fühlst",
            "Das klingt wirklich",
        ])
        for phrase in banned_phrases:
            # Case-insensitive Entfernung
            idx = text.lower().find(phrase.lower())
            while idx != -1:
                text = text[:idx] + text[idx + len(phrase):]
                idx = text.lower().find(phrase.lower())

        # 2. Banned Starters am Satzanfang entfernen
        banned_starters = filter_config.get("banned_starters", [
            "Also,", "Also ", "Grundsätzlich", "Grundsaetzlich",
            "Im Prinzip", "Nun,", "Nun ", "Sozusagen",
            "Quasi", "Eigentlich", "Im Grunde genommen",
            "Tatsächlich,", "Tatsaechlich,",
        ])
        for starter in banned_starters:
            if text.lstrip().lower().startswith(starter.lower()):
                text = text.lstrip()[len(starter):].lstrip()
                # Ersten Buchstaben gross machen
                if text:
                    text = text[0].upper() + text[1:]

        # 3. "Es tut mir leid" Varianten durch Fakt ersetzen
        sorry_patterns = [
            "es tut mir leid,", "es tut mir leid.", "es tut mir leid ",
            "leider ", "entschuldigung,", "entschuldigung.",
            "ich entschuldige mich,", "tut mir leid,", "tut mir leid.",
        ]
        for pattern in sorry_patterns:
            idx = text.lower().find(pattern)
            if idx != -1:
                text = text[:idx] + text[idx + len(pattern):].lstrip()
                if text:
                    text = text[0].upper() + text[1:]

        # 4. Mehrere Leerzeichen / fuehrende Leerzeichen bereinigen
        text = re.sub(r"  +", " ", text).strip()

        # 5. Leere Saetze entfernen (". ." oder ". , .")
        text = re.sub(r"\.\s*\.", ".", text)
        text = re.sub(r"!\s*!", "!", text)

        # 6. Max Sentences begrenzen
        max_sentences = filter_config.get("max_response_sentences", 0)
        if max_sentences > 0:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            if len(sentences) > max_sentences:
                text = " ".join(sentences[:max_sentences])

        text = text.strip()

        if text != original:
            logger.debug("Response-Filter: '%s' -> '%s'", original[:80], text[:80])

        return text if text else original

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
                "anticipation": "running" if self.anticipation._running else "stopped",
                "intent_tracker": "running" if self.intent_tracker._running else "stopped",
                "tts_enhancer": f"active (SSML: {self.tts_enhancer.ssml_enabled}, whisper: {self.tts_enhancer.is_whisper_mode})",
                "sound_manager": "active" if self.sound_manager.enabled else "disabled",
                "speaker_recognition": self.speaker_recognition.health_status(),
                "diagnostics": self.diagnostics.health_status(),
                "cooking_assistant": f"active (session: {'ja' if self.cooking.has_active_session else 'nein'})",
                "knowledge_base": f"active ({self.knowledge_base.chroma_collection.count() if self.knowledge_base.chroma_collection else 0} chunks)" if self.knowledge_base.chroma_collection else "disabled",
                "ambient_audio": self.ambient_audio.health_status(),
                "conflict_resolver": self.conflict_resolver.health_status(),
                "self_automation": self.self_automation.health_status(),
            },
            "models_available": models,
            "model_routing": self.model_router.get_model_info(),
            "autonomy": self.autonomy.get_level_info(),
            "trust": self.autonomy.get_trust_info(),
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
            parts.insert(0, (
                "\n\nGEDAECHTNIS (nutze diese Infos MIT HALTUNG — "
                "wie ein alter Bekannter, nicht wie eine Datenbank):"
            ))
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

    async def _get_rag_context(self, text: str) -> str:
        """Durchsucht die Knowledge Base nach relevantem Wissen (RAG)."""
        if not self.knowledge_base.chroma_collection:
            return ""

        try:
            hits = await self.knowledge_base.search(text, limit=3)
            if not hits:
                return ""

            parts = ["\n\nWISSENSBASIS (relevante Dokumente):"]
            for hit in hits:
                source = hit.get("source", "")
                content = hit.get("content", "")
                source_hint = f" [Quelle: {source}]" if source else ""
                parts.append(f"- {content}{source_hint}")

            parts.append("Nutze dieses Wissen falls relevant fuer die Antwort.")
            return "\n".join(parts)
        except Exception as e:
            logger.debug("RAG-Suche fehlgeschlagen: %s", e)
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

    async def _handle_cooking_timer(self, alert: dict):
        """Callback fuer Koch-Timer — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        if message:
            await emit_speaking(message)
            logger.info("Koch-Timer -> Meldung: %s", message)

    async def _handle_time_alert(self, alert: dict):
        """Callback fuer TimeAwareness-Alerts — leitet an proaktive Meldung weiter."""
        message = alert.get("message", "")
        if message:
            await emit_speaking(message)
            logger.info("TimeAwareness -> Proaktive Meldung: %s", message)

    async def _handle_health_alert(self, alert_type: str, urgency: str, message: str):
        """Callback fuer Health Monitor — leitet an proaktive Meldung weiter."""
        if message:
            await emit_speaking(message)
            logger.info("Health Monitor [%s/%s]: %s", alert_type, urgency, message)

    # ------------------------------------------------------------------
    # Phase 14.3: Ambient Audio Callback
    # ------------------------------------------------------------------

    async def _handle_ambient_audio_event(
        self,
        event_type: str,
        message: str,
        severity: str,
        room: Optional[str] = None,
        actions: Optional[list] = None,
    ):
        """Callback fuer Ambient Audio Events — reagiert auf Umgebungsgeraeusche."""
        if not message:
            return

        logger.info(
            "Ambient Audio [%s/%s]: %s (Raum: %s)",
            event_type, severity, message, room or "?",
        )

        # Sound-Alarm abspielen (wenn konfiguriert)
        sound_event = None
        from .ambient_audio import DEFAULT_EVENT_REACTIONS
        reaction = DEFAULT_EVENT_REACTIONS.get(event_type, {})
        sound_event = reaction.get("sound_event")
        if sound_event and self.sound_manager.enabled:
            await self.sound_manager.play_event_sound(sound_event, room=room)

        # HA-Aktionen ausfuehren
        if actions:
            if "lights_on" in actions and room:
                try:
                    await self.executor.execute("set_light", {
                        "room": room,
                        "state": "on",
                        "brightness": 100,
                    })
                except Exception as e:
                    logger.debug("Ambient Audio lights_on fehlgeschlagen: %s", e)

        # Nachricht via WebSocket senden
        await emit_speaking(message)

    # ------------------------------------------------------------------
    # Phase 16.2: Tutorial-Modus
    # ------------------------------------------------------------------

    async def _get_tutorial_hint(self, person: str) -> Optional[str]:
        """Gibt Tutorial-Hinweise fuer neue User zurueck (erste 10 Interaktionen)."""
        tutorial_cfg = yaml_config.get("tutorial", {})
        if not tutorial_cfg.get("enabled", True):
            return None

        max_interactions = tutorial_cfg.get("max_interactions", 10)

        if not self.memory.redis:
            return None

        try:
            key = f"mha:tutorial:count:{person}"
            count = await self.memory.redis.incr(key)
            # Expire nach 30 Tagen (danach kein Tutorial mehr)
            if count == 1:
                await self.memory.redis.expire(key, 30 * 24 * 3600)

            if count > max_interactions:
                return None

            # Verschiedene Tipps je nach Interaktions-Nummer
            tips = [
                "Tipp: Du kannst mich fragen 'Was kannst du?' fuer eine Uebersicht aller Funktionen.",
                "Tipp: Sag 'Merk dir [etwas]' und ich speichere es fuer dich. 'Was weisst du?' zeigt alles an.",
                "Tipp: Ich kann Licht, Heizung und Rolllaeden steuern. Sag einfach was du brauchst.",
                "Tipp: Ich habe Easter Eggs. Probier mal 'Wer bist du?' oder '42'.",
                "Tipp: Sag 'Gute Nacht' fuer einen Sicherheits-Check und die Nacht-Routine.",
                "Tipp: 'Setz Milch auf die Einkaufsliste' funktioniert auch per Sprache.",
                "Tipp: Ich lerne aus Korrekturen. Sag einfach 'Nein, ich meinte...'",
                "Tipp: Im Dashboard (Web-UI) kannst du alles konfigurieren — Sarkasmus, Stimme, Easter Eggs.",
                "Tipp: Ich kann kochen! Sag 'Rezept fuer Spaghetti Carbonara'.",
                "Tipp: Frag 'Was hast du von mir gelernt?' um deine Korrekturen zu sehen.",
            ]

            tip_index = (count - 1) % len(tips)
            return f"\n\nTUTORIAL-MODUS (Interaktion {count}/{max_interactions}):\n{tips[tip_index]}\nFuege diesen Tipp KURZ am Ende deiner Antwort an, z.B.: '...Uebrigens: [Tipp]'"

        except Exception as e:
            logger.debug("Tutorial-Check Fehler: %s", e)
            return None

    # ------------------------------------------------------------------
    # Phase 13.2: Automation-Bestaetigung
    # ------------------------------------------------------------------

    async def _handle_automation_confirmation(self, text: str) -> Optional[str]:
        """Erkennt Automation-Bestaetigungen und fuehrt sie aus."""
        if not self.self_automation.get_pending_count():
            return None

        text_lower = text.lower().strip().rstrip("!?.")

        # Direkte Bestaetigung per ID: "Automation abc12345 bestaetigen"
        import re
        id_match = re.search(r"automation\s+([a-f0-9]{8})\s+bestaetig", text_lower)
        if id_match:
            pending_id = id_match.group(1)
            result = await self.self_automation.confirm_automation(pending_id)
            return result.get("message", "")

        # Einfache Bestaetigung: "Ja" / "Ja, erstellen" / "Mach das"
        confirm_triggers = [
            "ja", "jo", "jap", "klar", "genau", "passt",
            "ja, erstellen", "ja erstellen", "ja mach das",
            "ja, aktivieren", "ja aktivieren", "erstellen",
            "aktivieren", "ja bitte", "mach das", "bitte",
        ]
        if any(text_lower == t or text_lower.startswith(t + " ") or text_lower.startswith(t + ",") for t in confirm_triggers):
            # Letztes Pending nehmen
            pending_ids = list(self.self_automation._pending.keys())
            if pending_ids:
                result = await self.self_automation.confirm_automation(pending_ids[-1])
                return result.get("message", "")

        # Ablehnung
        reject_triggers = [
            "nein", "abbrechen", "cancel", "nicht erstellen", "doch nicht",
        ]
        if any(text_lower == t or text_lower.startswith(t) for t in reject_triggers):
            if self.self_automation._pending:
                self.self_automation._pending.clear()
                return "Automation verworfen."

        return None

    # ------------------------------------------------------------------
    # Phase 8: Memory-Befehle
    # ------------------------------------------------------------------

    async def _handle_memory_command(self, text: str, person: str) -> Optional[str]:
        """Erkennt und verarbeitet explizite Memory-Befehle."""
        text_lower = text.lower().strip()

        # "Merk dir: ..."
        for trigger in ["merk dir ", "merke dir ", "speichere ", "remember "]:
            if text_lower.startswith(trigger):
                content = text[len(trigger):].strip().rstrip(".")
                if len(content) > 3:
                    success = await self.memory.semantic.store_explicit(
                        content=content, person=person
                    )
                    if success:
                        return f"Notiert: \"{content}\""
                    return "Das konnte ich leider nicht speichern."

        # "Was weisst du ueber ...?"
        for trigger in ["was weisst du ueber ", "was weißt du über ",
                        "was weisst du zu ", "kennst du "]:
            if text_lower.startswith(trigger):
                topic = text[len(trigger):].strip().rstrip("?").rstrip(".")
                if len(topic) > 1:
                    facts = await self.memory.semantic.search_by_topic(topic, limit=10)
                    if facts:
                        lines = [f"Was ich ueber \"{topic}\" weiss:"]
                        for f in facts:
                            conf = f.get("confidence", 0)
                            src = " (von dir)" if f.get("source") == "explicit" else ""
                            lines.append(f"- {f['content']}{src}")
                        return "\n".join(lines)
                    return f"Zu \"{topic}\" habe ich leider nichts gespeichert."

        # "Vergiss ..."
        for trigger in ["vergiss ", "loesche ", "vergesse "]:
            if text_lower.startswith(trigger):
                topic = text[len(trigger):].strip().rstrip(".")
                if len(topic) > 1:
                    deleted = await self.memory.semantic.forget(topic)
                    if deleted > 0:
                        return f"Erledigt. {deleted} Eintrag/Eintraege zu \"{topic}\" vergessen."
                    return f"Zu \"{topic}\" hatte ich ohnehin nichts gespeichert."

        # Phase 11.1: "Wissen hinzufuegen: ..." / "Neues Wissen: ..."
        for trigger in ["wissen hinzufuegen ", "neues wissen ", "wissen speichern "]:
            if text_lower.startswith(trigger):
                content = text[len(trigger):].strip().rstrip(".")
                if len(content) > 10:
                    chunks = await self.knowledge_base.ingest_text(content, source="voice")
                    if chunks > 0:
                        return f"Wissen gespeichert: {chunks} Eintrag/Eintraege in der Wissensdatenbank."
                    return "Das konnte ich leider nicht in die Wissensdatenbank aufnehmen."

        # Phase 11.1: "Was steht in der Wissensdatenbank?" / "Wissen Status"
        if any(kw in text_lower for kw in ["wissensdatenbank status", "wissen status",
                                            "was steht in der wissensdatenbank"]):
            stats = await self.knowledge_base.get_stats()
            if stats.get("total_chunks", 0) > 0:
                sources = ", ".join(stats["sources"][:10]) if stats.get("sources") else "keine"
                return (
                    f"Wissensdatenbank: {stats['total_chunks']} Eintraege "
                    f"aus {len(stats.get('sources', []))} Quellen ({sources})."
                )
            return "Die Wissensdatenbank ist noch leer. Leg Textdateien in config/knowledge/ ab."

        # "Was hast du von mir gelernt?" — Korrektur-History
        if any(kw in text_lower for kw in ["was hast du von mir gelernt",
                                            "was hast du gelernt von mir",
                                            "korrektur history",
                                            "korrektur-history",
                                            "was habe ich dir beigebracht",
                                            "meine korrekturen"]):
            corrections = await self.memory.semantic.get_correction_history(person)
            if corrections:
                lines = [f"Von dir habe ich {len(corrections)} Korrektur(en) gelernt:"]
                for f in corrections:
                    lines.append(f"- {f['content']}")
                return "\n".join(lines)
            return "Von dir habe ich noch keine Korrekturen gelernt."

        # "Was hast du heute gelernt?"
        if any(kw in text_lower for kw in ["was hast du heute gelernt",
                                            "was hast du gelernt",
                                            "neue fakten"]):
            facts = await self.memory.semantic.get_todays_learnings()
            if facts:
                lines = [f"Heute habe ich {len(facts)} neue(s) gelernt:"]
                for f in facts:
                    lines.append(f"- {f['content']} [{f['category']}]")
                return "\n".join(lines)
            return "Heute habe ich noch nichts Neues gelernt."

        # Phase 16.2: "Was kannst du?" — Faehigkeiten auflisten
        if any(kw in text_lower for kw in [
            "was kannst du", "was koennen sie", "was koenntest du",
            "hilfe", "help", "funktionen", "faehigkeiten",
            "was sind deine", "zeig mir was du",
        ]):
            result = await self.executor.execute("list_capabilities", {})
            return result.get("message", "Ich kann vieles. Frag einfach.")

        # Phase 15.2: "Was steht auf der Einkaufsliste?"
        if any(kw in text_lower for kw in [
            "einkaufsliste", "shopping list", "was muss ich einkaufen",
            "was brauchen wir", "einkaufszettel",
        ]):
            # "Setz X auf die Einkaufsliste"
            for trigger in ["setz ", "setze ", "pack ", "tu ", "schreib "]:
                if text_lower.startswith(trigger):
                    # Extrahiere den Artikel
                    rest = text[len(trigger):].strip()
                    # "X auf die Einkaufsliste"
                    for sep in [" auf die einkaufsliste", " auf den einkaufszettel",
                                " auf die liste"]:
                        if sep in rest.lower():
                            item = rest[:rest.lower().index(sep)].strip()
                            if item:
                                result = await self.executor.execute(
                                    "manage_shopping_list", {"action": "add", "item": item}
                                )
                                return result.get("message", f"'{item}' hinzugefuegt.")
                    # Fallback: ganzer Rest als Item
                    result = await self.executor.execute(
                        "manage_shopping_list", {"action": "add", "item": rest}
                    )
                    return result.get("message", f"'{rest}' hinzugefuegt.")

            # "Zeig die Einkaufsliste" / "Was steht auf der Einkaufsliste"
            if any(kw in text_lower for kw in ["zeig", "was steht", "was muss", "was brauchen"]):
                result = await self.executor.execute(
                    "manage_shopping_list", {"action": "list"}
                )
                return result.get("message", "Einkaufsliste nicht verfuegbar.")

        # Phase 15.2: Vorrats-Tracking
        if any(kw in text_lower for kw in [
            "vorrat", "vorraete", "inventory", "was haben wir",
            "was ist im kuehlschrank", "was ist im gefrier",
            "laeuft ab", "ablaufdatum", "haltbarkeit",
        ]):
            # "Zeig den Vorrat"
            if any(kw in text_lower for kw in ["zeig", "was haben", "was ist", "vorrat anzeigen", "liste"]):
                result = await self.executor.execute("manage_inventory", {"action": "list"})
                return result.get("message", "Vorrat nicht verfuegbar.")

            # "Was laeuft ab?"
            if any(kw in text_lower for kw in ["laeuft ab", "ablauf", "haltbar"]):
                result = await self.executor.execute("manage_inventory", {"action": "check_expiring"})
                return result.get("message", "Keine Ablauf-Infos.")

        return None

    # ------------------------------------------------------------------
    # Phase 8: Intent-Routing (Wissen vs Smart-Home vs Memory)
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        """
        Klassifiziert den Intent einer Anfrage.
        Returns: 'smart_home', 'knowledge', 'memory', 'delegation', 'general'
        """
        text_lower = text.lower().strip()

        # Phase 10: Delegations-Intent erkennen
        delegation_patterns = [
            r"^sag\s+(\w+)\s+(dass|das)\s+",
            r"^frag\s+(\w+)\s+(ob|mal|nach)\s+",
            r"^teile?\s+(\w+)\s+mit\s+(dass|das)\s+",
            r"^gib\s+(\w+)\s+bescheid\s+",
            r"^richte?\s+(\w+)\s+aus\s+(dass|das)\s+",
            r"^schick\s+(\w+)\s+eine?\s+nachricht",
            r"^nachricht\s+an\s+(\w+)",
        ]
        for pattern in delegation_patterns:
            if re.search(pattern, text_lower):
                return "delegation"

        # Memory-Fragen
        memory_keywords = [
            "erinnerst du dich", "weisst du noch", "was weisst du",
            "habe ich dir", "hab ich gesagt", "was war",
        ]
        if any(kw in text_lower for kw in memory_keywords):
            return "memory"

        # Wissensfragen (allgemeine Fragen die KEINE Smart-Home-Steuerung brauchen)
        knowledge_patterns = [
            "wie lange", "wie viel", "wie viele", "was ist",
            "was sind", "was bedeutet", "erklaer mir", "erklaere",
            "warum ist", "wer ist", "wer war", "was passiert wenn",
            "wie funktioniert", "wie macht man", "wie kocht man",
            "rezept fuer", "rezept für", "definition von", "unterschied zwischen",
        ]

        # Nur als Wissensfrage wenn KEIN Smart-Home-Keyword dabei
        smart_home_keywords = [
            "licht", "lampe", "heizung", "temperatur", "rollladen",
            "jalousie", "szene", "alarm", "tuer", "fenster",
            "musik", "tv", "fernseher", "kamera", "sensor",
        ]

        is_knowledge = any(text_lower.startswith(kw) or f" {kw}" in text_lower
                          for kw in knowledge_patterns)
        has_smart_home = any(kw in text_lower for kw in smart_home_keywords)

        if is_knowledge and not has_smart_home:
            return "knowledge"

        return "general"

    # ------------------------------------------------------------------
    # Phase 8: Was-waere-wenn Simulation
    # ------------------------------------------------------------------

    @staticmethod
    def _get_whatif_prompt(text: str) -> str:
        """Erkennt Was-waere-wenn-Fragen und gibt erweiterten Prompt zurueck."""
        text_lower = text.lower()
        whatif_triggers = [
            "was waere wenn", "was wäre wenn", "was passiert wenn",
            "was kostet es wenn", "was kostet", "was wuerde passieren",
            "stell dir vor", "angenommen", "hypothetisch",
            "wenn ich 2 wochen", "wenn ich eine woche", "wenn ich verreise",
        ]

        if not any(t in text_lower for t in whatif_triggers):
            return ""

        return """

WAS-WAERE-WENN SIMULATION:
Der User stellt eine hypothetische Frage. Beantworte sie:
- Nutze den aktuellen Haus-Kontext (Temperaturen, Verbrauch, Geraete)
- Bei Energiefragen: Schaetze basierend auf typischen Werten
- Bei Abwesenheit: Gib eine Checkliste (Heizung, Alarm, Fenster, Pflanzen, Simulation)
- Bei Kosten: Schaetze realistisch (Strompreis ~0.30 EUR/kWh, Gas ~0.08 EUR/kWh)
- Sei ehrlich wenn du schaetzen musst: "Grob geschaetzt..."
- Maximal 5 Punkte, klar strukturiert."""

    # ------------------------------------------------------------------
    # Phase 8: Konversations-Kontinuitaet
    # ------------------------------------------------------------------

    async def _check_conversation_continuity(self) -> Optional[str]:
        """Prueft ob es offene Gespraechsthemen gibt.

        Unterstuetzt mehrere Topics — gibt bis zu 3 als kombinierten
        Hinweis zurueck, statt nur das aelteste.
        """
        try:
            pending = await self.memory.get_pending_conversations()
            if not pending:
                return None

            ready_topics = []
            for item in pending:
                topic = item.get("topic", "")
                age = item.get("age_minutes", 0)
                if topic and age >= 10:
                    ready_topics.append(topic)

            if not ready_topics:
                return None

            # Bis zu 3 Topics anbieten, alle als erledigt markieren
            topics_to_show = ready_topics[:3]
            for topic in topics_to_show:
                await self.memory.resolve_conversation(topic)

            if len(topics_to_show) == 1:
                return topics_to_show[0]

            # Mehrere Topics: als Liste formatieren
            return " | ".join(topics_to_show)
        except Exception as e:
            logger.debug("Fehler bei Konversations-Kontinuitaet: %s", e)
        return None

    # ------------------------------------------------------------------
    # Phase 10: Delegations-Handler
    # ------------------------------------------------------------------

    async def _handle_delegation(self, text: str, person: str) -> Optional[str]:
        """Verarbeitet Delegations-Intents ('Sag Lisa dass...', 'Frag Max ob...')."""
        text_lower = text.lower().strip()

        # Muster: "Sag X dass Y" / "Frag X ob Y" / "Teile X mit dass Y" / etc.
        patterns = [
            (r"^sag\s+(\w+)\s+(?:dass|das)\s+(.+)", "sag"),
            (r"^frag\s+(\w+)\s+(?:ob|mal|nach)\s+(.+)", "frag"),
            (r"^teile?\s+(\w+)\s+mit\s+(?:dass|das)\s+(.+)", "teile_mit"),
            (r"^gib\s+(\w+)\s+bescheid\s+(.+)", "bescheid"),
            (r"^richte?\s+(\w+)\s+aus\s+(?:dass|das)\s+(.+)", "ausrichten"),
            (r"^schick\s+(\w+)\s+eine?\s+nachricht:?\s*(.+)", "nachricht"),
            (r"^nachricht\s+an\s+(\w+):?\s*(.+)", "nachricht"),
        ]

        target_person = None
        message_content = None

        for pattern, _ in patterns:
            match = re.search(pattern, text_lower)
            if match:
                target_person = match.group(1).capitalize()
                message_content = match.group(2).strip().rstrip(".")
                break

        if not target_person or not message_content:
            return None

        # Trust-Check: Darf der Sender Nachrichten senden?
        if person:
            trust_check = self.autonomy.can_person_act(person, "send_message_to_person")
            if not trust_check["allowed"]:
                return f"Entschuldigung, du darfst keine Nachrichten senden. {trust_check.get('reason', '')}"

        # Nachricht senden ueber FunctionExecutor
        result = await self.executor.execute("send_message_to_person", {
            "person": target_person,
            "message": message_content,
            "urgency": "medium",
        })

        if result.get("success"):
            delivery = result.get("delivery", "")
            if delivery == "tts":
                return f"Ich habe {target_person} die Nachricht durchgesagt."
            else:
                return f"Ich habe {target_person} eine Nachricht geschickt."
        else:
            return f"Die Nachricht an {target_person} konnte leider nicht zugestellt werden."

    # ------------------------------------------------------------------
    # Phase 8: Intent-Extraktion im Hintergrund
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase 11.4: Korrektur-Lernen
    # ------------------------------------------------------------------

    @staticmethod
    def _is_correction(text: str) -> bool:
        """Erkennt ob der User eine Korrektur macht."""
        text_lower = text.lower().strip()
        correction_patterns = [
            "nein, ich mein",
            "nein ich mein",
            "das stimmt nicht",
            "das ist falsch",
            "nicht richtig",
            "ich meinte",
            "ich meine",
            "falsch, ich",
            "nein, das ist",
            "quatsch",
            "unsinn",
            "das habe ich nicht gesagt",
            "das hab ich nicht gesagt",
            "ich habe gesagt",
            "ich hab gesagt",
            "korrektur:",
            "richtigstellung:",
            "nein,",  # "Nein, XYZ" als einfachstes Muster
        ]
        return any(text_lower.startswith(p) or p in text_lower for p in correction_patterns)

    async def _handle_correction(self, text: str, response: str, person: str):
        """Verarbeitet eine Korrektur und speichert sie als hochkonfidenten Fakt."""
        try:
            # LLM extrahiert den korrigierten Fakt
            extraction_prompt = (
                "Der User hat eine Korrektur gemacht. "
                "Extrahiere den korrekten Fakt als einen einzigen, klaren Satz. "
                "Nur den Fakt, keine Erklaerung.\n\n"
                f"User: {text}\n"
                f"Assistent-Antwort: {response}\n\n"
                "Korrekter Fakt:"
            )

            model = self.model_router.select_model("korrektur extrahieren")
            result = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": "Du extrahierst Fakten. Antworte mit einem einzigen Satz."},
                    {"role": "user", "content": extraction_prompt},
                ],
                model=model,
                temperature=0.1,
                max_tokens=64,
            )

            fact_text = result.get("message", {}).get("content", "").strip()
            if fact_text and len(fact_text) > 5:
                # Fakt mit hoher Confidence speichern (User hat korrigiert = sicher)
                from .semantic_memory import SemanticFact
                fact = SemanticFact(
                    content=fact_text,
                    category="general",
                    person=person,
                    confidence=0.95,
                    source_conversation=f"correction: {text[:100]}",
                )
                await self.memory.semantic.store_fact(fact)
                logger.info("Korrektur-Lernen: '%s' gespeichert (Person: %s)", fact_text, person)
        except Exception as e:
            logger.debug("Fehler bei Korrektur-Lernen: %s", e)

    async def _extract_intents_background(self, text: str, person: str):
        """Extrahiert und speichert Intents im Hintergrund."""
        try:
            intents = await self.intent_tracker.extract_intents(text, person)
            for intent in intents:
                await self.intent_tracker.track_intent(intent)
        except Exception as e:
            logger.debug("Fehler bei Intent-Extraktion: %s", e)

    # ------------------------------------------------------------------
    # Phase 8: Anticipation + Intent Callbacks
    # ------------------------------------------------------------------

    async def _handle_anticipation_suggestion(self, suggestion: dict):
        """Callback fuer Anticipation-Vorschlaege."""
        mode = suggestion.get("mode", "ask")
        desc = suggestion.get("description", "")
        action = suggestion.get("action", "")

        if mode == "auto" and self.autonomy.level >= 4:
            # Automatisch ausfuehren + informieren
            args = suggestion.get("args", {})
            result = await self.executor.execute(action, args)
            text = f"Ich habe {desc} automatisch ausgefuehrt."
            await emit_speaking(text)
            logger.info("Anticipation auto-execute: %s", desc)
        else:
            # Vorschlagen
            if mode == "suggest":
                text = f"Darf ich anmerken: {desc}. Soll ich?"
            else:
                text = f"Muster erkannt: {desc}. Soll ich das ausfuehren?"
            await emit_speaking(text)
            logger.info("Anticipation suggestion: %s (%s)", desc, mode)

    async def _handle_intent_reminder(self, reminder: dict):
        """Callback fuer Intent-Erinnerungen."""
        text = reminder.get("text", "")
        if text:
            await emit_speaking(text)
            logger.info("Intent-Erinnerung: %s", text)

    async def shutdown(self):
        """Faehrt MindHome Assistant herunter."""
        await self.ambient_audio.stop()
        await self.anticipation.stop()
        await self.intent_tracker.stop()
        await self.time_awareness.stop()
        await self.health_monitor.stop()
        await self.proactive.stop()
        await self.summarizer.stop()
        await self.feedback.stop()
        await self.memory.close()
        await self.ha.close()
        logger.info("MindHome Assistant heruntergefahren")
