"""
Explainability Engine - "Warum hast du das gemacht?"

Quick Win: Trackt Entscheidungen und deren Gruende, sodass Jarvis
auf Nachfrage erklaeren kann warum eine Aktion ausgefuehrt wurde.

Konfigurierbar in der Jarvis Assistant UI.
"""

import json
import logging
import time
from collections import deque
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

REDIS_KEY_DECISIONS = "mha:explainability:decisions"
REDIS_KEY_LAST_ACTION = "mha:explainability:last_action"


class ExplainabilityEngine:
    """Trackt Entscheidungen und macht sie erklaerbar."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._ollama = None

        cfg = yaml_config.get("explainability", {})
        self.enabled = cfg.get("enabled", True)
        self.max_history = cfg.get("max_history", 50)
        self.detail_level = cfg.get("detail_level", "normal")  # minimal, normal, verbose
        self.auto_explain = cfg.get("auto_explain", False)

        # In-Memory Decision Log (FIFO)
        self._decisions: deque[dict] = deque(maxlen=self.max_history)

    def set_ollama(self, ollama_client):
        """Setzt den OllamaClient fuer LLM-basierte Erklaerungen."""
        self._ollama = ollama_client

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_decisions()
        logger.info("ExplainabilityEngine initialisiert (enabled: %s, detail: %s)",
                     self.enabled, self.detail_level)

    async def _load_decisions(self):
        """Laedt gespeicherte Entscheidungen aus Redis."""
        if not self.redis:
            return
        try:
            raw = await self.redis.lrange(REDIS_KEY_DECISIONS, 0, self.max_history - 1)
            for entry in reversed(raw):
                try:
                    self._decisions.append(json.loads(entry))
                except json.JSONDecodeError as e:
                    logger.debug("Decision entry parse failed: %s", e)
        except Exception as e:
            logger.debug("Decisions laden fehlgeschlagen: %s", e)

    async def log_decision(
        self,
        action: str,
        reason: str,
        context: dict = None,
        trigger: str = "",
        person: str = "",
        domain: str = "",
        confidence: float = 1.0,
    ):
        """Loggt eine Entscheidung mit Begruendung.

        Args:
            action: Was wurde gemacht (z.B. "Licht Wohnzimmer auf 50%")
            reason: Warum (z.B. "Abend-Routine, Sonnenuntergang vor 15 Min")
            context: Zusaetzlicher Kontext (Sensordaten, Regeln etc.)
            trigger: Was hat die Aktion ausgeloest (user_command, automation, anticipation, etc.)
            person: Betroffene Person
            domain: Domaene (climate, light, media, etc.)
            confidence: Konfidenz der Entscheidung (0-1)
        """
        if not self.enabled:
            return

        decision = {
            "action": action,
            "reason": reason,
            "trigger": trigger or "unknown",
            "person": person,
            "domain": domain,
            "confidence": round(confidence, 2),
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
        }

        if context and self.detail_level in ("normal", "verbose"):
            # Kontext komprimieren
            decision["context"] = {
                k: v for k, v in (context or {}).items()
                if k in ("room", "sensor_values", "rule", "pattern", "mood",
                         "autonomy_level", "weather", "calendar_event")
            }

        self._decisions.append(decision)

        # In Redis persistieren
        if self.redis:
            try:
                await self.redis.lpush(REDIS_KEY_DECISIONS, json.dumps(decision, ensure_ascii=False))
                await self.redis.ltrim(REDIS_KEY_DECISIONS, 0, self.max_history - 1)
                await self.redis.expire(REDIS_KEY_DECISIONS, 86400 * 7)  # 7 Tage
                # Letzte Aktion fuer schnellen Zugriff
                await self.redis.set(
                    REDIS_KEY_LAST_ACTION,
                    json.dumps(decision, ensure_ascii=False),
                    ex=3600,
                )
            except Exception as e:
                logger.debug("Decision Redis-Fehler: %s", e)

    def explain_last(self, n: int = 1) -> list[dict]:
        """Gibt die letzten N Entscheidungen mit Erklaerung zurueck.

        Args:
            n: Anzahl der Entscheidungen (default: 1)

        Returns:
            Liste von Entscheidungs-Dicts
        """
        if not self._decisions:
            return []
        return list(self._decisions)[-n:]

    def explain_by_domain(self, domain: str, n: int = 5) -> list[dict]:
        """Gibt Entscheidungen fuer eine bestimmte Domaene zurueck."""
        return [
            d for d in reversed(self._decisions)
            if d.get("domain") == domain
        ][:n]

    def explain_by_action(self, action_keyword: str, n: int = 5) -> list[dict]:
        """Sucht Entscheidungen die ein bestimmtes Keyword enthalten."""
        kw = action_keyword.lower()
        return [
            d for d in reversed(self._decisions)
            if kw in d.get("action", "").lower() or kw in d.get("reason", "").lower()
        ][:n]

    def format_explanation(self, decision: dict) -> str:
        """Formatiert eine Entscheidung als natuerlichsprachliche Erklaerung.

        Args:
            decision: Entscheidungs-Dict

        Returns:
            Menschenlesbare Erklaerung
        """
        action = decision.get("action", "Unbekannte Aktion")
        reason = decision.get("reason", "Kein Grund angegeben")
        trigger = decision.get("trigger", "")
        time_str = decision.get("time_str", "")
        confidence = decision.get("confidence", 1.0)

        trigger_labels = {
            "user_command": "auf deinen Befehl",
            "automation": "durch eine Automation",
            "anticipation": "weil ich ein Muster erkannt habe",
            "proactive": "proaktiv",
            "schedule": "nach Zeitplan",
            "sensor": "wegen Sensordaten",
            "conflict": "zur Konfliktloesung",
        }
        trigger_text = trigger_labels.get(trigger, "")

        parts = [f"Ich habe '{action}' ausgefuehrt"]
        if trigger_text:
            parts[0] += f" ({trigger_text})"
        parts.append(f"Grund: {reason}")

        if self.detail_level == "verbose" and confidence < 1.0:
            parts.append(f"Konfidenz: {confidence:.0%}")

        if time_str:
            parts.append(f"Zeitpunkt: {time_str}")

        return ". ".join(parts) + "."

    async def format_explanation_llm(self, decision: dict) -> str:
        """Formuliert eine Erklaerung via LLM im Butler-Stil.

        Natuerlichere Erklaerungen als das Template-basierte format_explanation().
        Fallback auf Template-Version wenn LLM nicht verfuegbar.
        """
        cfg = yaml_config.get("explainability", {})
        if not cfg.get("llm_explanations", True) or not self._ollama:
            return self.format_explanation(decision)

        action = decision.get("action", "Unbekannte Aktion")
        reason = decision.get("reason", "Kein Grund angegeben")
        trigger = decision.get("trigger", "unknown")
        confidence = decision.get("confidence", 1.0)
        time_str = decision.get("time_str", "")

        try:
            import asyncio
            from .config import settings, get_person_title
            title = get_person_title()

            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Du bist J.A.R.V.I.S., ein trocken-britischer Smart-Home-Butler. "
                                "Erklaere dem Benutzer warum du eine Aktion ausgefuehrt hast. "
                                "1-2 Saetze, souveraen und knapp. Keine Aufzaehlungen."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Erklaere warum du '{action}' gemacht hast.\n"
                                f"Grund: {reason}\n"
                                f"Ausloeser: {trigger}\n"
                                f"Zeitpunkt: {time_str}\n"
                                f"Konfidenz: {confidence:.0%}\n"
                                f"Anrede: {title}"
                            ),
                        },
                    ],
                    model=settings.model_fast,
                    temperature=0.4,
                    max_tokens=500,
                    think=False,
                    tier="fast",
                ),
                timeout=4.0,
            )
            content = (response.get("message", {}).get("content", "") or "").strip()
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            if content and len(content) > 10:
                return content

        except Exception as e:
            logger.debug("Explainability LLM Fehler: %s", e)

        return self.format_explanation(decision)

    def get_explanation_prompt_hint(self) -> str:
        """Gibt einen Prompt-Hinweis fuer Erklaerbarkeit zurueck.

        Wird in den System-Prompt eingebaut wenn auto_explain aktiv ist.
        """
        if not self.enabled or not self.auto_explain:
            return ""

        last = self.explain_last(1)
        if not last:
            return ""

        d = last[0]
        age = time.time() - d.get("timestamp", 0)
        if age > 300:  # Aelter als 5 Min -> nicht erwaehnen
            return ""

        return (
            f"Letzte automatische Aktion: '{d['action']}' (Grund: {d['reason']}). "
            "Bei Rueckfragen erklaere warum du das getan hast."
        )

    def get_stats(self) -> dict:
        """Gibt Statistiken ueber geloggte Entscheidungen zurueck."""
        if not self._decisions:
            return {"total": 0, "domains": {}, "triggers": {}}

        domains: dict[str, int] = {}
        triggers: dict[str, int] = {}
        for d in self._decisions:
            dom = d.get("domain", "unknown")
            trig = d.get("trigger", "unknown")
            domains[dom] = domains.get(dom, 0) + 1
            triggers[trig] = triggers.get(trig, 0) + 1

        return {
            "total": len(self._decisions),
            "domains": domains,
            "triggers": triggers,
        }
