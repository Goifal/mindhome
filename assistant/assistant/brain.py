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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .action_planner import ActionPlanner
from .activity import ActivityEngine
from .autonomy import AutonomyManager
from .config import settings, yaml_config
from .context_builder import ContextBuilder
from .cooking_assistant import CookingAssistant
from .device_health import DeviceHealthMonitor
from .diagnostics import DiagnosticsEngine
from .health_monitor import HealthMonitor
from .feedback import FeedbackTracker
from .function_calling import get_assistant_tools, FunctionExecutor
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
from .ocr import OCREngine
from .conflict_resolver import ConflictResolver
from .personality import PersonalityEngine
from .proactive import ProactiveManager
from .anticipation import AnticipationEngine
from .intent_tracker import IntentTracker
from .routine_engine import RoutineEngine
from .config_versioning import ConfigVersioning
from .self_automation import SelfAutomation
from .self_optimization import SelfOptimization
from .sound_manager import SoundManager
from .speaker_recognition import SpeakerRecognition
from .summarizer import DailySummarizer
from .time_awareness import TimeAwareness
from .timer_manager import TimerManager
from .camera_manager import CameraManager
from .conditional_commands import ConditionalCommands
from .energy_optimizer import EnergyOptimizer
from .web_search import WebSearch
from .wellness_advisor import WellnessAdvisor
from .threat_assessment import ThreatAssessment
from .learning_observer import LearningObserver
from .tts_enhancer import TTSEnhancer
from .websocket import emit_thinking, emit_speaking, emit_action, emit_proactive

logger = logging.getLogger(__name__)

# Audit-Log (gleicher Pfad wie main.py, fuer Chat-basierte Sicherheitsevents)
_AUDIT_LOG_PATH = Path(__file__).parent.parent / "logs" / "audit.jsonl"

# Security-Confirmation: Redis-Key + TTL fuer ausstehende Sicherheitsbestaetigungen
SECURITY_CONFIRM_KEY = "mha:pending_security_confirmation"
SECURITY_CONFIRM_TTL = 300  # 5 Minuten


def _audit_log(action: str, details: dict = None):
    """Schreibt einen Audit-Eintrag (append-only JSONL)."""
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details or {},
        }
        with open(_AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Audit-Log Fehler: %s", exc)

# Phase 7.5: Szenen-Intelligenz — Prompt fuer natuerliches Situationsverstaendnis
def _build_scene_intelligence_prompt() -> str:
    """Baut den Szenen-Intelligenz-Prompt je nach Heizungsmodus."""
    heating = yaml_config.get("heating", {})
    mode = heating.get("mode", "room_thermostat")

    if mode == "heating_curve":
        heat_cold = "Heizungs-Offset um +1 erhoehen (Heizkurve)"
        heat_warm = "Heizungs-Offset um -1 senken ODER Fenster-Empfehlung"
        heat_sick = "Heizungs-Offset +2, sanftes Licht, weniger Meldungen"
        heat_work = "Helles Tageslicht, Heizungs-Offset beibehalten, Benachrichtigungen reduzieren"
    else:
        heat_cold = "Heizung im aktuellen Raum um 2°C erhoehen"
        heat_warm = "Heizung runter ODER Fenster-Empfehlung"
        heat_sick = "Temperatur 23°C, sanftes Licht, weniger Meldungen"
        heat_work = "Helles Tageslicht, 21°C, Benachrichtigungen reduzieren"

    return f"""

SZENEN-INTELLIGENZ:
Verstehe natuerliche Situationsbeschreibungen und reagiere mit passenden Aktionen:
- "Mir ist kalt" → {heat_cold}
- "Mir ist warm" → {heat_warm}
- "Zu hell" → Rolladen runter ODER Licht dimmen (je nach Tageszeit)
- "Zu dunkel" → Licht an oder heller
- "Zu laut" → Musik leiser oder Fenster-Empfehlung
- "Romantischer Abend" → Licht 20%, warmweiss, leise Musik vorschlagen
- "Ich bin krank" → {heat_sick}
- "Filmabend" → Licht dimmen, Rolladen runter, TV vorbereiten
- "Ich arbeite" → {heat_work}
- "Party" → Musik an, Lichter bunt/hell, Gaeste-WLAN

Nutze den aktuellen Raum-Kontext fuer die richtige Aktion.
Frage nur bei Mehrdeutigkeit nach (z.B. "Welchen Raum?")."""


SCENE_INTELLIGENCE_PROMPT = _build_scene_intelligence_prompt()


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

        # Phase 14.2: OCR & Bild-Analyse (Multi-Modal Input)
        self.ocr = OCREngine(self.ollama)

        # Phase 14.3: Ambient Audio (Umgebungsgeraeusch-Erkennung)
        self.ambient_audio = AmbientAudioClassifier(self.ha)

        # Phase 16.1: Multi-User Konfliktloesung
        self.conflict_resolver = ConflictResolver(self.autonomy, self.ollama)

        # Phase 15.1: Gesundheits-Monitor
        self.health_monitor = HealthMonitor(self.ha)

        # Phase 15.2: Vorrats-Tracking
        self.inventory = InventoryManager(self.ha)

        # Phase 15.3: Geraete-Beziehung (Anomalie-Erkennung)
        self.device_health = DeviceHealthMonitor(self.ha)

        # Phase 13.2: Self Automation (Automationen aus natuerlicher Sprache)
        self.self_automation = SelfAutomation(self.ha, self.ollama)

        # Phase 13.4: Config Versioning + Self Optimization
        self.config_versioning = ConfigVersioning()
        self.self_optimization = SelfOptimization(self.ollama, self.config_versioning)

        # Phase 11: Koch-Assistent
        self.cooking = CookingAssistant(self.ollama)

        # Phase 11.1: Knowledge Base (RAG)
        self.knowledge_base = KnowledgeBase()

        # Phase 17: Neue Jarvis-Features
        self.timer_manager = TimerManager()
        self.camera_manager = CameraManager(self.ha, self.ollama)
        self.conditional_commands = ConditionalCommands()
        self.energy_optimizer = EnergyOptimizer(self.ha)
        self.web_search = WebSearch()
        self.threat_assessment = ThreatAssessment(self.ha)
        self.learning_observer = LearningObserver()

        # Wellness Advisor (Caring Loops)
        self.wellness_advisor = WellnessAdvisor(self.ha, self.activity, self.mood)

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

        # Redis fuer Context Builder (Guest-Mode-Check)
        self.context_builder.set_redis(self.memory.redis)

        # Mood Detector initialisieren
        await self.mood.initialize(redis_client=self.memory.redis)
        self.personality.set_mood_detector(self.mood)

        # Phase 6: Redis fuer Personality Engine (Formality Score, Counter)
        self.personality.set_redis(self.memory.redis)

        # Gelernten Sarkasmus-Level laden
        await self.personality.load_learned_sarcasm_level()

        # Fact Decay: Einmal taeglich alte Fakten abbauen
        asyncio.create_task(self._run_daily_fact_decay())

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
        self.summarizer.set_notify_callback(self._handle_daily_summary)

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

        # Phase 13.4: Config Versioning + Self Optimization initialisieren
        await self.config_versioning.initialize(redis_client=self.memory.redis)
        await self.self_optimization.initialize(redis_client=self.memory.redis)
        self.executor.set_config_versioning(self.config_versioning)

        # Phase 14.2: OCR Engine initialisieren
        await self.ocr.initialize(redis_client=self.memory.redis)

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

        # Phase 15.3: Device Health Monitor initialisieren und starten
        await self.device_health.initialize(redis_client=self.memory.redis)
        self.device_health.set_notify_callback(self._handle_device_health_alert)
        await self.device_health.start()

        # Phase 17: Neue Features initialisieren
        await self.timer_manager.initialize(redis_client=self.memory.redis)
        self.timer_manager.set_notify_callback(self._handle_timer_notification)
        self.timer_manager.set_action_callback(
            lambda func, args: self.executor.execute(func, args)
        )
        await self.conditional_commands.initialize(redis_client=self.memory.redis)
        self.conditional_commands.set_action_callback(
            lambda func, args: self.executor.execute(func, args)
        )
        await self.energy_optimizer.initialize(redis_client=self.memory.redis)
        await self.cooking.initialize(redis_client=self.memory.redis)
        await self.threat_assessment.initialize(redis_client=self.memory.redis)
        await self.learning_observer.initialize(redis_client=self.memory.redis)
        self.learning_observer.set_notify_callback(self._handle_learning_suggestion)

        # Wellness Advisor initialisieren und starten
        await self.wellness_advisor.initialize(redis_client=self.memory.redis)
        self.wellness_advisor.set_notify_callback(self._handle_wellness_nudge)
        await self.wellness_advisor.start()

        await self.proactive.start()
        logger.info("Jarvis initialisiert (alle Systeme aktiv, inkl. Phase 17)")

    async def process(self, text: str, person: Optional[str] = None, room: Optional[str] = None, files: Optional[list] = None, stream_callback=None) -> dict:
        """
        Verarbeitet eine User-Eingabe.

        Args:
            text: User-Text (z.B. "Mach das Licht aus")
            person: Name der Person (optional)
            room: Raum aus dem die Anfrage kommt (optional)
            files: Liste von Datei-Metadaten aus file_handler.save_upload() (optional)
            stream_callback: Optionaler async callback(token: str) fuer Streaming

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

        # Phase 13.1: Sicherheits-Bestaetigung (lock_door:unlock, set_alarm:disarm, etc.)
        security_result = await self._handle_security_confirmation(text, person or "")
        if security_result:
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", security_result)
            await emit_speaking(security_result)
            return {
                "response": security_result,
                "actions": [],
                "model_used": "security_confirmation",
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

        # Phase 13.4: Optimierungs-Vorschlag Bestaetigung
        opt_result = await self._handle_optimization_confirmation(text)
        if opt_result:
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", opt_result)
            await emit_speaking(opt_result)
            return {
                "response": opt_result,
                "actions": [],
                "model_used": "self_optimization",
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

        # Phase 17: Planungs-Dialog Check — laufender Dialog hat Vorrang
        pending_plan = self.action_planner.has_pending_plan()
        if pending_plan:
            logger.info("Laufender Planungs-Dialog: %s", pending_plan)
            plan_result = await self.action_planner.continue_planning_dialog(text, pending_plan)
            response_text = plan_result.get("response", "")
            if plan_result.get("status") == "error":
                self.action_planner.clear_plan(pending_plan)
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", response_text)
            await emit_speaking(response_text)
            return {
                "response": response_text,
                "actions": [],
                "model_used": "action_planner_dialog",
                "context_room": room or "unbekannt",
            }

        # Phase 17: Neuen Planungs-Dialog starten
        if self.action_planner.is_planning_request(text):
            logger.info("Planungs-Dialog gestartet: '%s'", text)
            plan_result = await self.action_planner.start_planning_dialog(text, person or "")
            response_text = plan_result.get("response", "")
            await self.memory.add_conversation("user", text)
            await self.memory.add_conversation("assistant", response_text)
            await emit_speaking(response_text)
            return {
                "response": response_text,
                "actions": [],
                "model_used": "action_planner_dialog",
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

        # 1. Kontext sammeln (mit Subsystem-Timeout)
        try:
            context = await asyncio.wait_for(
                self.context_builder.build(
                    trigger="voice", user_text=text, person=person or ""
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Context Build Timeout (5s) — Fallback auf Minimal-Kontext")
            context = {"time": {"datetime": datetime.now().isoformat()}}
        except Exception as e:
            logger.error("Context Build Fehler: %s — Fallback auf Minimal-Kontext", e)
            context = {"time": {"datetime": datetime.now().isoformat()}}
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

        # Phase 17: Timer-Kontext in System Prompt
        timer_hints = self.timer_manager.get_context_hints()
        if timer_hints:
            system_prompt += "\n\nAKTIVE TIMER:\n" + "\n".join(f"- {h}" for h in timer_hints)

        # Phase 17: Security Score im Kontext (nur bei Warnungen)
        try:
            sec_score = await self.threat_assessment.get_security_score()
            if sec_score.get("level") in ("warning", "critical"):
                details = ", ".join(sec_score.get("details", []))
                system_prompt += (
                    f"\n\nSICHERHEITS-STATUS: {sec_score['level'].upper()} "
                    f"(Score: {sec_score['score']}/100). {details}. "
                    f"Erwaehne dies bei Gelegenheit."
                )
        except Exception as e:
            logger.debug("Security Score Fehler: %s", e)

        # Phase 17: Kontext-Persistenz ueber Raumwechsel
        prev_context = await self._get_cross_room_context(person or "")
        if prev_context:
            system_prompt += f"\n\nVORHERIGER KONTEXT (anderer Raum): {prev_context}"

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
        # Phase 14.2: Vision-LLM Bild-Analyse (erweitert Datei-Kontext)
        if files:
            if self.ocr.enabled and self.ocr._vision_available:
                for f in files:
                    if f.get("type") == "image":
                        try:
                            description = await self.ocr.describe_image(f, text)
                            if description:
                                f["vision_description"] = description
                        except Exception as e:
                            logger.warning("Vision-LLM fuer %s fehlgeschlagen: %s",
                                           f.get("name", "?"), e)

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

        # Phase 8: Was-waere-wenn Erkennung (mit echten HA-Daten)
        whatif_prompt = await self._get_whatif_prompt(text, context)
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
                person=person,
                autonomy=self.autonomy,
            )
            response_text = planner_result.get("response", "")
            executed_actions = planner_result.get("actions", [])
            model = settings.model_deep
        elif intent_type == "knowledge":
            # Phase 8: Wissensfragen -> Deep-Model fuer bessere Qualitaet
            logger.info("Wissensfrage erkannt -> LLM direkt (Deep: %s, keine Tools)",
                         settings.model_deep)
            model = settings.model_deep
            if stream_callback:
                collected_tokens = []
                async for token in self.ollama.stream_chat(
                    messages=messages,
                    model=model,
                ):
                    collected_tokens.append(token)
                    await stream_callback(token)
                response_text = self._filter_response("".join(collected_tokens))
            else:
                response = await self.ollama.chat(
                    messages=messages,
                    model=model,
                )
                response_text = self._filter_response(response.get("message", {}).get("content", ""))

                if "error" in response:
                    logger.error("LLM Fehler: %s", response["error"])
                    response_text = "Kann ich gerade nicht beantworten. Mein Modell streikt."
            executed_actions = []
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
            if stream_callback:
                collected_tokens = []
                async for token in self.ollama.stream_chat(
                    messages=messages,
                    model=model,
                ):
                    collected_tokens.append(token)
                    await stream_callback(token)
                response_text = self._filter_response("".join(collected_tokens))
            else:
                response = await self.ollama.chat(
                    messages=messages,
                    model=model,
                )
                response_text = self._filter_response(response.get("message", {}).get("content", ""))
            executed_actions = []
        else:
            # 6b. Einfache Anfragen: Direkt LLM aufrufen (mit Timeout + Fallback)
            try:
                response = await asyncio.wait_for(
                    self.ollama.chat(
                        messages=messages,
                        model=model,
                        tools=get_assistant_tools(),
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.error("LLM Timeout (30s) fuer Modell %s", model)
                # Fallback: Schnelleres Modell versuchen
                fallback_model = self.model_router.get_fallback_model(model)
                if fallback_model and fallback_model != model:
                    logger.info("LLM Fallback: %s -> %s", model, fallback_model)
                    try:
                        response = await asyncio.wait_for(
                            self.ollama.chat(
                                messages=messages,
                                model=fallback_model,
                                tools=get_assistant_tools(),
                            ),
                            timeout=20.0,
                        )
                        model = fallback_model
                    except (asyncio.TimeoutError, Exception):
                        return {
                            "response": "Beide Sprachmodelle reagieren nicht. Server moeglicherweise ueberlastet.",
                            "actions": [],
                            "model_used": model,
                            "error": "timeout_all_models",
                        }
                else:
                    return {
                        "response": "Mein Sprachmodell reagiert nicht. Server moeglicherweise ueberlastet.",
                        "actions": [],
                        "model_used": model,
                        "error": "timeout",
                    }
            except Exception as e:
                logger.error("LLM Exception: %s", e)
                return {
                    "response": "Mein Sprachmodell hat ein Problem. Versuch es nochmal.",
                    "actions": [],
                    "model_used": model,
                    "error": str(e),
                }

            if "error" in response:
                logger.error("LLM Fehler: %s", response["error"])
                return {
                    "response": "Mein Sprachmodell reagiert nicht. Ich versuche es gleich nochmal.",
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
                          "create_automation", "list_jarvis_automations",
                          "get_timer_status", "list_conditionals", "get_energy_report",
                          "web_search", "get_camera_view", "get_security_score",
                          "get_room_climate", "get_active_intents",
                          "get_wellness_status", "get_device_health",
                          "get_learned_patterns", "describe_doorbell"}
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
                            # Pending-Aktion in Redis speichern fuer Follow-Up
                            if self.memory.redis:
                                pending = {
                                    "function": func_name,
                                    "args": func_args,
                                    "person": person or "",
                                    "room": room or "",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "reason": validation.reason,
                                }
                                await self.memory.redis.setex(
                                    SECURITY_CONFIRM_KEY,
                                    SECURITY_CONFIRM_TTL,
                                    json.dumps(pending),
                                )
                            response_text = f"Sir, das braucht deine Bestaetigung. {validation.reason}"
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
                    # SICHERHEIT: Wenn person unbekannt/leer → als Gast behandeln (restriktivste Stufe)
                    effective_person = person if person else "__anonymous_guest__"
                    action_room = func_args.get("room", "") if isinstance(func_args, dict) else ""
                    trust_check = self.autonomy.can_person_act(effective_person, func_name, room=action_room)
                    if not trust_check["allowed"]:
                        logger.warning(
                            "Trust-Check fehlgeschlagen: %s darf '%s' nicht (%s)",
                            effective_person, func_name, trust_check.get("reason", ""),
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

                    # Pushback-Check: Jarvis warnt VOR der Ausfuehrung
                    pushback_msg = None
                    pushback = self.personality.check_pushback(func_name, final_args)
                    if pushback:
                        if pushback["level"] >= 2:
                            # Level 2: Bestaetigung verlangen — nicht ausfuehren
                            if self.memory.redis:
                                pending = {
                                    "function": func_name,
                                    "args": final_args,
                                    "person": person or "",
                                    "room": room or "",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "reason": f"pushback:{pushback['rule_id']}",
                                }
                                timeout = yaml_config.get("pushback", {}).get("confirmation_timeout", 120)
                                await self.memory.redis.setex(
                                    SECURITY_CONFIRM_KEY,
                                    timeout,
                                    json.dumps(pending),
                                )
                            response_text = pushback["message"]
                            executed_actions.append({
                                "function": func_name,
                                "args": final_args,
                                "result": "pushback_confirmation_needed",
                            })
                            continue
                        elif pushback["level"] == 1:
                            # Level 1: Warnung voranstellen, aber trotzdem ausfuehren
                            pushback_msg = pushback["message"]

                    # Ausfuehren
                    result = await self.executor.execute(func_name, final_args)
                    executed_actions.append({
                        "function": func_name,
                        "args": final_args,
                        "result": result,
                    })

                    # Phase 17: Learning Observer — Jarvis-Aktionen markieren
                    # damit sie nicht als "manuelle" Aktionen gezaehlt werden
                    if isinstance(result, dict) and result.get("success"):
                        entity_id = final_args.get("entity_id", "")
                        if not entity_id:
                            # Entity aus Room ableiten (z.B. light.wohnzimmer)
                            r = final_args.get("room", "")
                            if r and func_name in ("set_light", "set_cover", "set_climate", "set_switch"):
                                domain = func_name.replace("set_", "")
                                entity_id = f"{domain}.{r.lower().replace(' ', '_')}"
                        if entity_id:
                            asyncio.create_task(
                                self.learning_observer.mark_jarvis_action(entity_id)
                            )

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

                    # Pushback-Warnung (Level 1) an Response voranstellen
                    if pushback_msg:
                        logger.info("Pushback (Level 1): '%s'", pushback_msg)
                        if response_text:
                            response_text = f"{pushback_msg} {response_text}"
                        else:
                            response_text = pushback_msg

                    # Phase 6: Opinion Check — Jarvis kommentiert Aktionen
                    # Nur wenn kein Pushback-Kommentar (sonst doppelt)
                    if not pushback_msg:
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

                    if stream_callback:
                        # Streaming: Token-fuer-Token via stream_chat()
                        collected = []
                        async for token in self.ollama.stream_chat(
                            messages=feedback_messages,
                            model=model,
                            temperature=0.7,
                            max_tokens=128,
                        ):
                            collected.append(token)
                            await stream_callback(token)
                        feedback_text = "".join(collected)
                    else:
                        feedback_response = await self.ollama.chat(
                            messages=feedback_messages,
                            model=model,
                            temperature=0.7,
                            max_tokens=128,
                        )
                        feedback_text = ""
                        if "error" not in feedback_response:
                            feedback_text = feedback_response.get("message", {}).get("content", "")

                    if feedback_text:
                        response_text = self._filter_response(feedback_text)
                except Exception as e:
                    logger.debug("Tool-Feedback fehlgeschlagen: %s", e)

            # Phase 6: Variierte Bestaetigung statt immer "Erledigt."
            # Nur fuer reine Action-Tools (set_light etc.), nicht fuer Query-Tools
            # Bei Multi-Actions: Narrative statt einzelne Bestaetigungen
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
                    if len(executed_actions) >= 2:
                        # Multi-Action Narrative: "Licht, Heizung und Rolladen — alles erledigt."
                        action_names = []
                        for a in executed_actions:
                            name = a.get("function", "").replace("set_", "").replace("_", " ").title()
                            action_names.append(name)
                        if len(action_names) == 2:
                            summary = f"{action_names[0]} und {action_names[1]}"
                        else:
                            summary = ", ".join(action_names[:-1]) + f" und {action_names[-1]}"
                        confirmation = self.personality.get_varied_confirmation(success=True)
                        response_text = f"{summary} — {confirmation.rstrip('.')}"
                    else:
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

            # Fehlerbehandlung auch wenn LLM optimistischen Text generiert hat
            # (LLM sagt "Erledigt" aber Aktion ist fehlgeschlagen)
            if executed_actions and response_text:
                failed_actions = [
                    a for a in executed_actions
                    if isinstance(a["result"], dict) and not a["result"].get("success", True)
                ]
                if failed_actions:
                    # Phase 17: Natuerliche Fehlerbehandlung statt hartem "Problem: ..."
                    first_fail = failed_actions[0]
                    error_msg = first_fail["result"].get("message", "Unbekannter Fehler")
                    try:
                        response_text = await self._generate_error_recovery(
                            first_fail["function"], first_fail.get("args", {}), error_msg
                        )
                    except Exception:
                        response_text = f"Problem: {error_msg}"

        # Phase 12: Response-Filter (Post-Processing) — Floskeln entfernen
        # Nachtmodus: Harter Sentence-Limit von 2 (LLM-Prompt ist nur Empfehlung)
        night_limit = 0
        time_of_day = self.personality.get_time_of_day()
        if time_of_day in ("night", "early_morning"):
            night_limit = 2
        response_text = self._filter_response(response_text, max_sentences_override=night_limit)

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

        # Phase 17: Kontext-Persistenz fuer Raumwechsel speichern
        asyncio.create_task(
            self._save_cross_room_context(person or "", text, response_text, room or "")
        )

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

    def _filter_response(self, text: str, max_sentences_override: int = 0) -> str:
        """
        Filtert LLM-Floskeln und unerwuenschte Muster aus der Antwort.
        Wird nach jedem LLM-Response aufgerufen, vor Speicherung und TTS.

        Args:
            max_sentences_override: Harter Sentence-Limit (z.B. fuer Nachtmodus).
                                    Ueberschreibt den Config-Wert wenn > 0.
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
            "Ich bin ein KI", "Ich bin eine KI",
            "Ich bin ein Sprachmodell",
            "Ich bin ein grosses Sprachmodell",
            "als Sprachmodell", "als KI-Assistent",
            "Ich habe keine Gefuehle",
            "Ich habe keine eigenen Gefühle",
            "Hallo! Wie kann ich",
            "Hallo, wie kann ich",
            "Hi! Wie kann ich",
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
            "es tut mir leid!", "leider ", "leider,", "leider.",
            "entschuldigung,", "entschuldigung.", "entschuldigung!",
            "entschuldige,", "entschuldige.", "entschuldige!",
            "ich entschuldige mich,", "tut mir leid,", "tut mir leid.",
            "bedauerlicherweise ", "ich bedaure,", "ich bedaure.",
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

        # 6. Max Sentences begrenzen (Override hat Vorrang, z.B. Nachtmodus)
        max_sentences = max_sentences_override or filter_config.get("max_response_sentences", 0)
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
                "ocr": self.ocr.health_status(),
                "ambient_audio": self.ambient_audio.health_status(),
                "conflict_resolver": self.conflict_resolver.health_status(),
                "self_automation": self.self_automation.health_status(),
                "config_versioning": self.config_versioning.health_status(),
                "self_optimization": self.self_optimization.health_status(),
                "threat_assessment": "active" if self.threat_assessment.enabled else "disabled",
                "learning_observer": "active" if self.learning_observer.enabled else "disabled",
                "energy_optimizer": "active" if self.energy_optimizer.enabled else "disabled",
                "wellness_advisor": "running" if self.wellness_advisor._running else "stopped",
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

    async def _handle_timer_notification(self, alert: dict):
        """Callback fuer allgemeine Timer — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await emit_speaking(formatted)
            logger.info("Timer -> Meldung: %s", formatted)

    async def _handle_learning_suggestion(self, alert: dict):
        """Callback fuer Learning Observer — schlaegt Automatisierungen vor."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "low")
            await emit_speaking(formatted)
            logger.info("Learning -> Vorschlag: %s", formatted)

    async def _handle_cooking_timer(self, alert: dict):
        """Callback fuer Koch-Timer — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await emit_speaking(formatted)
            logger.info("Koch-Timer -> Meldung: %s", formatted)

    async def _handle_time_alert(self, alert: dict):
        """Callback fuer TimeAwareness-Alerts — leitet an proaktive Meldung weiter."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await emit_speaking(formatted)
            logger.info("TimeAwareness -> Meldung: %s", formatted)

    async def _handle_health_alert(self, alert_type: str, urgency: str, message: str):
        """Callback fuer Health Monitor — leitet an proaktive Meldung weiter."""
        if message:
            formatted = await self.proactive.format_with_personality(message, urgency)
            await emit_speaking(formatted)
            logger.info("Health Monitor [%s/%s]: %s", alert_type, urgency, formatted)

    async def _handle_device_health_alert(self, alert: dict):
        """Callback fuer DeviceHealthMonitor — meldet Geraete-Anomalien."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await emit_speaking(formatted)
            logger.info(
                "DeviceHealth [%s]: %s",
                alert.get("alert_type", "?"), formatted,
            )

    async def _handle_wellness_nudge(self, nudge_type: str, message: str):
        """Callback fuer Wellness Advisor — kuemmert sich um den User."""
        if message:
            formatted = await self.proactive.format_with_personality(message, "low")
            await emit_speaking(formatted)
            logger.info("Wellness [%s]: %s", nudge_type, formatted)

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
    # Phase 13.1: Sicherheits-Bestaetigung (lock_door, set_alarm, etc.)
    # ------------------------------------------------------------------

    async def _handle_security_confirmation(self, text: str, person: str) -> Optional[str]:
        """Prueft ob eine ausstehende Sicherheitsbestaetigung beantwortet wird.

        Flow: User sagt z.B. 'Tuer aufschliessen' → needs_confirmation blockiert
        und speichert Pending in Redis → User sagt 'Ja' → wird hier abgefangen
        und ausgefuehrt (nur wenn dieselbe Person bestaetigt).
        """
        if not self.memory.redis:
            return None

        raw = await self.memory.redis.get(SECURITY_CONFIRM_KEY)
        if not raw:
            return None

        text_lower = text.lower().strip().rstrip("!?.")

        # Bestaetigung
        confirm_triggers = [
            "ja", "jo", "jap", "klar", "genau", "passt",
            "ja bitte", "mach das", "bestaetigen", "ausfuehren",
            "ja mach das", "ja, mach das", "bitte",
        ]
        if any(text_lower == t or text_lower.startswith(t + " ") or text_lower.startswith(t + ",") for t in confirm_triggers):
            try:
                pending = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.error("Security-Confirmation: Korrupte Daten in Redis")
                await self.memory.redis.delete(SECURITY_CONFIRM_KEY)
                return None
            # Person-Check: nur dieselbe Person darf bestaetigen
            if pending.get("person") and person and pending["person"] != person:
                logger.warning(
                    "Security-Confirmation abgelehnt: %s != %s",
                    person, pending["person"],
                )
                return None  # Stille Ablehnung, weiter im normalen Flow

            # Ausfuehren
            func_name = pending.get("function")
            func_args = pending.get("args", {})
            if not func_name:
                logger.error("Security-Confirmation: Fehlende Funktion in Pending-Daten")
                await self.memory.redis.delete(SECURITY_CONFIRM_KEY)
                return None
            result = await self.executor.execute(func_name, func_args)
            await self.memory.redis.delete(SECURITY_CONFIRM_KEY)

            _audit_log("security_confirmation_executed", {
                "function": func_name,
                "args": func_args,
                "person": person,
            })
            logger.info(
                "Security-Confirmation ausgefuehrt: %s(%s) durch %s",
                func_name, func_args, person,
            )

            if result.get("success"):
                return f"Bestaetigt und ausgefuehrt: {func_name}"
            else:
                return f"Bestaetigt, aber fehlgeschlagen: {result.get('message', 'Unbekannter Fehler')}"

        # Ablehnung
        reject_triggers = [
            "nein", "abbrechen", "cancel", "doch nicht", "stop", "nee",
        ]
        if any(text_lower == t or text_lower.startswith(t) for t in reject_triggers):
            await self.memory.redis.delete(SECURITY_CONFIRM_KEY)
            return "Verstanden, Aktion verworfen."

        return None

    # ------------------------------------------------------------------
    # Phase 13.4: Optimierungs-Vorschlag Bestaetigung (Chat)
    # ------------------------------------------------------------------

    async def _handle_optimization_confirmation(self, text: str) -> Optional[str]:
        """Erkennt Optimierungs-Bestaetigungen im Chat.

        SICHERHEIT: Jarvis kann NIEMALS selbst Vorschlaege genehmigen.
        Nur explizite User-Eingaben loesen approve_proposal() aus.
        """
        proposals = await self.self_optimization.get_pending_proposals()
        if not proposals:
            return None

        text_lower = text.lower().strip().rstrip("!?.")

        # "Vorschlag 1 annehmen" / "Vorschlag 2 ablehnen"
        import re
        approve_match = re.search(r"vorschlag\s+(\d+)\s+(annehmen|genehmigen|akzeptieren|ok)", text_lower)
        if approve_match:
            idx = int(approve_match.group(1)) - 1  # 1-basiert -> 0-basiert
            result = await self.self_optimization.approve_proposal(idx)
            if result["success"]:
                # yaml_config im Speicher aktualisieren
                from .config import load_yaml_config
                import assistant.config as cfg
                cfg.yaml_config = load_yaml_config()
                _audit_log("self_opt_approve_chat", {"proposal_index": idx, "result": result.get("message", "")})
            return result.get("message", "")

        reject_match = re.search(r"vorschlag\s+(\d+)\s+(ablehnen|verwerfen|nein)", text_lower)
        if reject_match:
            idx = int(reject_match.group(1)) - 1
            result = await self.self_optimization.reject_proposal(idx)
            _audit_log("self_opt_reject_chat", {"proposal_index": idx})
            return result.get("message", "")

        # "Alle Vorschlaege ablehnen"
        if any(t in text_lower for t in ["alle vorschlaege ablehnen", "alle ablehnen", "vorschlaege verwerfen"]):
            result = await self.self_optimization.reject_all()
            _audit_log("self_opt_reject_all_chat", {})
            return result.get("message", "")

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
                    return "Speichervorgang fehlgeschlagen. Zweiter Versuch empfohlen, Sir."

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
                    return f"Zu \"{topic}\" ist nichts hinterlegt."

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
                    return "Wissensdatenbank hat den Eintrag nicht akzeptiert. Anderer Wortlaut koennte helfen."

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

    async def _get_whatif_prompt(self, text: str, context: dict = None) -> str:
        """Erkennt Was-waere-wenn-Fragen und gibt erweiterten Prompt mit echten HA-Daten zurueck."""
        text_lower = text.lower()
        whatif_triggers = [
            "was waere wenn", "was wäre wenn", "was passiert wenn",
            "was kostet es wenn", "was kostet", "was wuerde passieren",
            "stell dir vor", "angenommen", "hypothetisch",
            "wenn ich 2 wochen", "wenn ich eine woche", "wenn ich verreise",
        ]

        if not any(t in text_lower for t in whatif_triggers):
            return ""

        # Echte HA-Daten sammeln fuer fundierte Simulation
        data_lines = []
        try:
            states = await self.ha.get_states()
            if states:
                # Temperaturen
                temps = {}
                for s in states:
                    eid = s.get("entity_id", "")
                    val = s.get("state", "")
                    attrs = s.get("attributes", {})
                    if eid.startswith("climate.") and val != "unavailable":
                        name = attrs.get("friendly_name", eid)
                        current = attrs.get("current_temperature")
                        target = attrs.get("temperature")
                        if current:
                            temps[name] = f"{current}°C (Soll: {target}°C)"
                    elif eid.startswith("sensor.") and "temperature" in eid and val.replace(".", "").replace("-", "").isdigit():
                        name = attrs.get("friendly_name", eid)
                        temps[name] = f"{val}°C"
                if temps:
                    data_lines.append("TEMPERATUREN:")
                    for name, val in list(temps.items())[:8]:
                        data_lines.append(f"  - {name}: {val}")

                # Energie-Verbrauch
                energy = {}
                for s in states:
                    eid = s.get("entity_id", "")
                    val = s.get("state", "")
                    attrs = s.get("attributes", {})
                    unit = attrs.get("unit_of_measurement", "")
                    if ("energy" in eid or "power" in eid or "verbrauch" in eid) and val.replace(".", "").isdigit():
                        name = attrs.get("friendly_name", eid)
                        energy[name] = f"{val} {unit}"
                if energy:
                    data_lines.append("ENERGIE:")
                    for name, val in list(energy.items())[:6]:
                        data_lines.append(f"  - {name}: {val}")

                # Offene Fenster/Tueren
                open_items = []
                for s in states:
                    eid = s.get("entity_id", "")
                    if (eid.startswith("binary_sensor.") and
                            ("window" in eid or "door" in eid or "fenster" in eid or "tuer" in eid) and
                            s.get("state") == "on"):
                        name = s.get("attributes", {}).get("friendly_name", eid)
                        open_items.append(name)
                if open_items:
                    data_lines.append(f"OFFENE FENSTER/TUEREN: {', '.join(open_items)}")

                # Alarmsystem
                for s in states:
                    eid = s.get("entity_id", "")
                    if eid.startswith("alarm_control_panel."):
                        data_lines.append(f"ALARM: {s.get('state', 'unbekannt')}")

                # Wetter
                for s in states:
                    eid = s.get("entity_id", "")
                    if eid.startswith("weather."):
                        attrs = s.get("attributes", {})
                        temp = attrs.get("temperature", "?")
                        forecast = attrs.get("forecast", [])
                        data_lines.append(f"WETTER: {s.get('state', '?')}, {temp}°C")
                        if forecast and len(forecast) >= 1:
                            fc = forecast[0]
                            data_lines.append(
                                f"  Morgen: {fc.get('condition', '?')}, "
                                f"{fc.get('temperature', '?')}°C"
                            )
        except Exception as e:
            logger.debug("Was-waere-wenn Datensammlung Fehler: %s", e)

        # Saisonale Daten
        if context and "seasonal" in context:
            seasonal = context["seasonal"]
            data_lines.append(f"SAISON: {seasonal.get('season', '?')}")
            data_lines.append(
                f"  Tageslicht: {seasonal.get('daylight_hours', '?')}h "
                f"({seasonal.get('sunrise_approx', '?')} - {seasonal.get('sunset_approx', '?')})"
            )

        data_block = "\n".join(data_lines) if data_lines else "Keine Live-Daten verfuegbar."

        return f"""

WAS-WAERE-WENN SIMULATION:
Der User stellt eine hypothetische Frage. Nutze die ECHTEN Hausdaten fuer deine Antwort:

{data_block}

Regeln:
- Rechne mit echten Werten wenn verfuegbar (Temperaturen, Verbrauch, Geraete-Status)
- Bei Energiefragen: Nutze reale Verbrauchsdaten, Strompreis ~0.30 EUR/kWh, Gas ~0.08 EUR/kWh
- Bei Abwesenheit: Pruefe offene Fenster/Tueren, Alarm-Status, aktive Geraete
- Bei Kosten: Rechne konkret mit den vorhandenen Daten
- Sei ehrlich wenn du schaetzen musst: "Basierend auf deinem aktuellen Verbrauch..."
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
                return f"Nachrichten-Versand fuer dein Profil nicht freigegeben. {trust_check.get('reason', '')}"

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
            return f"Zustellung an {target_person} fehlgeschlagen. Empfaenger moeglicherweise nicht erreichbar."

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
            text = f"Sir, {desc} — hab ich uebernommen."
            await emit_proactive(text, "anticipation_auto", "medium")
            logger.info("Anticipation auto-execute: %s", desc)
        else:
            # Vorschlagen
            if mode == "suggest":
                text = f"Sir, wenn ich darf — {desc}. Soll ich?"
            else:
                text = f"Mir ist aufgefallen: {desc}. Soll ich das uebernehmen?"
            await emit_proactive(text, "anticipation_suggest", "low")
            logger.info("Anticipation suggestion: %s (%s)", desc, mode)

    async def _handle_intent_reminder(self, reminder: dict):
        """Callback fuer Intent-Erinnerungen."""
        text = reminder.get("text", "")
        if text:
            await emit_speaking(text)
            logger.info("Intent-Erinnerung: %s", text)

    async def _run_daily_fact_decay(self):
        """Fuehrt einmal taeglich den Fact Decay aus (04:00 Uhr)."""
        while True:
            try:
                now = datetime.now()
                # Naechste 04:00 berechnen
                target = now.replace(hour=4, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                wait_seconds = (target - now).total_seconds()

                await asyncio.sleep(wait_seconds)
                logger.info("Fact Decay gestartet (taeglich 04:00)")
                await self.memory.semantic.apply_decay()

                # Tagesverbrauch speichern (fuer Anomalie-Erkennung & Wochen-Vergleich)
                try:
                    await self.energy_optimizer.track_daily_cost()
                except Exception as e:
                    logger.debug("Energy daily tracking Fehler: %s", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fact Decay Fehler: %s", e)
                await asyncio.sleep(3600)  # Bei Fehler 1h warten

    async def _handle_daily_summary(self, data: dict):
        """Callback fuer Tages-Zusammenfassungen — wird morgens beim naechsten Kontakt gesprochen."""
        summary_text = data.get("text", "")
        date = data.get("date", "")
        if summary_text and self.memory.redis:
            # Zusammenfassung fuer naechsten Morning-Kontakt speichern
            await self.memory.redis.set(
                "jarvis:pending_summary", summary_text, ex=86400
            )
            logger.info("Tages-Zusammenfassung fuer %s zum Abruf bereitgestellt", date)

    # ------------------------------------------------------------------
    # Phase 17: Kontext-Persistenz ueber Raumwechsel
    # ------------------------------------------------------------------

    async def _save_cross_room_context(self, person: str, text: str, response: str, room: str):
        """Speichert Konversationskontext fuer Raumwechsel."""
        if not self.memory.redis or not person:
            return
        try:
            context_data = json.dumps({
                "last_question": text[:200],
                "last_response": response[:300],
                "room": room,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self.memory.redis.setex(
                f"mha:cross_room_context:{person.lower()}", 1800, context_data  # 30 Min TTL
            )
        except Exception:
            pass

    async def _get_cross_room_context(self, person: str) -> str:
        """Holt den vorherigen Konversationskontext wenn Raum gewechselt wurde."""
        if not self.memory.redis or not person:
            return ""
        try:
            raw = await self.memory.redis.get(f"mha:cross_room_context:{person.lower()}")
            if not raw:
                return ""
            if isinstance(raw, bytes):
                raw = raw.decode()
            data = json.loads(raw)
            return f"Letzte Frage (in {data.get('room', '?')}): \"{data.get('last_question', '')}\". Antwort: \"{data.get('last_response', '')}\""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Phase 17: Natuerliche Fehlerbehandlung
    # ------------------------------------------------------------------

    async def _generate_error_recovery(self, func_name: str, func_args: dict, error: str) -> str:
        """Generiert eine menschliche Fehlermeldung mit Loesungsvorschlag."""
        try:
            response = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": f"""Du bist {settings.assistant_name}.
Ein Smart-Home-Befehl ist fehlgeschlagen. Erklaere kurz was passiert ist und schlage eine Loesung vor.
Max 2 Saetze. Deutsch. Butler-Stil. Nicht entschuldigen, sondern sachlich loesen.
Beispiele:
- "Das Licht im Bad reagiert nicht. Moeglicherweise ist es offline. Soll ich den Status pruefen?"
- "Die Heizung laesst sich gerade nicht steuern. Ich versuche es in einer Minute erneut." """},
                    {"role": "user", "content": f"Fehlgeschlagen: {func_name}({func_args}). Fehler: {error}"},
                ],
                model=settings.model_fast,
                temperature=0.5,
                max_tokens=100,
            )
            return response.get("message", {}).get("content", f"{func_name} reagiert nicht. Ich pruefe das.")
        except Exception:
            return f"{func_name} reagiert nicht. Ich pruefe das."

    # ------------------------------------------------------------------
    # Phase 17: Predictive Resource Management
    # ------------------------------------------------------------------

    async def get_predictive_briefing(self) -> str:
        """Generiert vorausschauende Empfehlungen basierend auf Wetter + Kalender + Energie.

        Wird im Morning Briefing eingebunden.
        """
        try:
            states = await self.ha.get_states()
            if not states:
                return ""

            forecasts = []

            # Wetter-Forecast
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    attrs = s.get("attributes", {})
                    forecast = attrs.get("forecast", [])
                    if forecast:
                        tomorrow = forecast[0] if len(forecast) > 0 else {}
                        high = tomorrow.get("temperature", "")
                        cond = tomorrow.get("condition", "")
                        precip = tomorrow.get("precipitation", 0)
                        try:
                            high_f = float(high) if high else None
                        except (ValueError, TypeError):
                            high_f = None
                        try:
                            precip_f = float(precip) if precip else None
                        except (ValueError, TypeError):
                            precip_f = None
                        if high_f is not None and high_f > 30:
                            forecasts.append(f"Morgen wird es heiss ({high}°C). Hitzeschutz-Rolladen empfohlen.")
                        if precip_f is not None and precip_f > 5:
                            forecasts.append(f"Morgen Regen erwartet ({precip}mm). Fenster schliessen empfohlen.")
                        if cond in ("snowy", "snowy-rainy") or (high_f is not None and high_f < 0):
                            forecasts.append(f"Frost erwartet ({high}°C). Heizung im Voraus hochfahren?")
                    break

            # Energie-Preis Forecast (wenn verfuegbar)
            for s in states:
                eid = s.get("entity_id", "")
                if "price" in eid.lower() and "tomorrow" in eid.lower():
                    try:
                        price = float(s.get("state", 0))
                        if price < 10:
                            forecasts.append(f"Morgen guenstiger Strom ({price:.1f} ct). Groessere Verbraucher einplanen.")
                    except (ValueError, TypeError):
                        pass

            if not forecasts:
                return ""

            return "Vorausschau: " + " ".join(forecasts)
        except Exception as e:
            logger.debug("Predictive Briefing Fehler: %s", e)
            return ""

    async def get_foresight_predictions(self) -> list:
        """Fusioniert Kalender + Wetter + HA-States zu proaktiven Vorhersagen.

        Laeuft im Threat Assessment Loop (alle 5 Min).
        Gibt nur Vorhersagen zurueck die noch nicht gemeldet wurden (Cooldown via Redis).

        Returns:
            Liste von Dicts: [{"message": str, "urgency": str, "type": str}]
        """
        foresight_cfg = yaml_config.get("foresight", {})
        if not foresight_cfg.get("enabled", True):
            return []

        predictions = []

        try:
            states = await self.ha.get_states()
            if not states:
                return []

            # Redis fuer Cooldown-Checks
            redis = self.memory.redis

            # ----------------------------------------------------------
            # 1. Kalender: Termin in 30-60 Min → "Rechtzeitig los, Sir."
            # ----------------------------------------------------------
            lookahead = foresight_cfg.get("calendar_lookahead_minutes", 60)
            departure_warn = foresight_cfg.get("departure_warning_minutes", 45)

            try:
                calendar_entity = None
                for s in states:
                    if s.get("entity_id", "").startswith("calendar."):
                        calendar_entity = s.get("entity_id")
                        break

                if calendar_entity:
                    now = datetime.now()
                    end = now + timedelta(minutes=lookahead)
                    result = await self.ha.call_service_with_response(
                        "calendar", "get_events",
                        {
                            "entity_id": calendar_entity,
                            "start_date_time": now.isoformat(),
                            "end_date_time": end.isoformat(),
                        },
                    )

                    events = []
                    if isinstance(result, dict):
                        for entity_data in result.values():
                            if isinstance(entity_data, dict):
                                events.extend(entity_data.get("events", []))
                            elif isinstance(entity_data, list):
                                events.extend(entity_data)

                    for ev in events:
                        summary = ev.get("summary", "Termin")
                        ev_start = ev.get("start", "")
                        location = ev.get("location", "")

                        if not ev_start:
                            continue

                        try:
                            if "T" in str(ev_start):
                                start_dt = datetime.fromisoformat(str(ev_start).replace("Z", "+00:00"))
                                # In lokale naive Zeit konvertieren fuer Vergleich mit now
                                if start_dt.tzinfo:
                                    start_dt = start_dt.astimezone().replace(tzinfo=None)
                            else:
                                continue  # Ganztaegig → kein Departure-Warning
                        except (ValueError, TypeError):
                            continue

                        minutes_until = (start_dt - now).total_seconds() / 60

                        if departure_warn <= minutes_until <= lookahead:
                            # Cooldown: Nicht doppelt melden
                            cool_key = f"mha:foresight:cal:{summary[:30]}"
                            if redis and await redis.exists(cool_key):
                                continue
                            if redis:
                                await redis.setex(cool_key, 3600, "1")

                            msg = f"Termin '{summary}' in {int(minutes_until)} Minuten"
                            if location:
                                msg += f" ({location})"
                            msg += ". Rechtzeitig los, Sir."
                            predictions.append({
                                "message": msg,
                                "urgency": "medium",
                                "type": "departure_warning",
                            })
            except Exception as e:
                logger.debug("Foresight Calendar Fehler: %s", e)

            # ----------------------------------------------------------
            # 2. Wetter: Regen erwartet + Fenster offen
            # ----------------------------------------------------------
            if foresight_cfg.get("weather_alerts", True):
                try:
                    for s in states:
                        if not s.get("entity_id", "").startswith("weather."):
                            continue

                        attrs = s.get("attributes", {})
                        forecast = attrs.get("forecast", [])
                        wind_speed = attrs.get("wind_speed")
                        condition = s.get("state", "")

                        # Sturm-Warnung (>60 km/h)
                        if wind_speed is not None:
                            try:
                                ws = float(wind_speed)
                                if ws > 60:
                                    cool_key = "mha:foresight:storm"
                                    if not redis or not await redis.exists(cool_key):
                                        if redis:
                                            await redis.setex(cool_key, 3600, "1")
                                        predictions.append({
                                            "message": f"Sturmwarnung: Wind bei {ws:.0f} km/h. Rolllaeden sichern?",
                                            "urgency": "medium",
                                            "type": "storm_warning",
                                        })
                            except (ValueError, TypeError):
                                pass

                        # Regen + offene Fenster
                        rain_conditions = ("rainy", "pouring", "lightning-rainy", "snowy-rainy")
                        rain_expected = condition in rain_conditions

                        if not rain_expected and forecast:
                            next_fc = forecast[0] if forecast else {}
                            fc_cond = next_fc.get("condition", "")
                            if fc_cond in rain_conditions:
                                rain_expected = True
                            try:
                                precip = float(next_fc.get("precipitation", 0))
                                if precip > 2:
                                    rain_expected = True
                            except (ValueError, TypeError):
                                pass

                        if rain_expected:
                            # Offene Fenster zaehlen
                            open_windows = []
                            for ws in states:
                                weid = ws.get("entity_id", "")
                                wattrs = ws.get("attributes", {})
                                if (ws.get("state") == "on" and
                                    wattrs.get("device_class") == "window"):
                                    open_windows.append(
                                        wattrs.get("friendly_name", weid)
                                    )

                            if open_windows:
                                cool_key = "mha:foresight:rain_windows"
                                if not redis or not await redis.exists(cool_key):
                                    if redis:
                                        await redis.setex(cool_key, 1800, "1")  # 30 Min Cooldown
                                    predictions.append({
                                        "message": f"Regen erwartet. {len(open_windows)} Fenster noch offen.",
                                        "urgency": "medium",
                                        "type": "rain_windows",
                                    })

                        # Temperatursturz heute Nacht
                        if forecast:
                            current_temp = attrs.get("temperature")
                            tonight = None
                            for fc in forecast:
                                fc_dt = fc.get("datetime", "")
                                if "T" in str(fc_dt):
                                    try:
                                        fdt = datetime.fromisoformat(str(fc_dt).replace("Z", "+00:00"))
                                        # In lokale Zeit konvertieren fuer korrekten Stunden-Check
                                        if fdt.tzinfo:
                                            fdt = fdt.astimezone()
                                        if fdt.hour >= 20 or fdt.hour <= 6:
                                            tonight = fc
                                            break
                                    except (ValueError, TypeError):
                                        pass

                            if tonight and current_temp is not None:
                                try:
                                    temp_now = float(current_temp)
                                    temp_night = float(tonight.get("templow", tonight.get("temperature", temp_now)))
                                    if temp_now - temp_night > 10:
                                        cool_key = "mha:foresight:temp_drop"
                                        if not redis or not await redis.exists(cool_key):
                                            if redis:
                                                await redis.setex(cool_key, 7200, "1")
                                            predictions.append({
                                                "message": f"Temperatursturz heute Nacht: von {temp_now:.0f} auf {temp_night:.0f} Grad.",
                                                "urgency": "low",
                                                "type": "temp_drop",
                                            })
                                except (ValueError, TypeError):
                                    pass

                        break  # Nur erste Weather-Entity
                except Exception as e:
                    logger.debug("Foresight Weather Fehler: %s", e)

        except Exception as e:
            logger.debug("Foresight Fehler: %s", e)

        return predictions

    async def shutdown(self):
        """Faehrt MindHome Assistant herunter."""
        await self.ambient_audio.stop()
        await self.anticipation.stop()
        await self.intent_tracker.stop()
        await self.time_awareness.stop()
        await self.health_monitor.stop()
        await self.device_health.stop()
        await self.wellness_advisor.stop()
        await self.proactive.stop()
        await self.summarizer.stop()
        await self.feedback.stop()
        await self.memory.close()
        await self.ha.close()
        logger.info("MindHome Assistant heruntergefahren")
