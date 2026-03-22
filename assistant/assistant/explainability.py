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
from .core_identity import IDENTITY_BLOCK

logger = logging.getLogger(__name__)

REDIS_KEY_DECISIONS = "mha:explainability:decisions"
REDIS_KEY_LAST_ACTION = "mha:explainability:last_action"

# Kontrafaktische Regeln: (domain, context_key) -> Template
# Erklaert was OHNE Jarvis' Eingreifen passiert waere.
_COUNTERFACTUAL_RULES: dict[tuple[str, str], str] = {
    (
        "climate",
        "window_open",
    ): "Ohne Eingreifen: Heizkosten von ca. {cost}€/h verschwendet.",
    (
        "climate",
        "empty_room",
    ): "Ohne Eingreifen: Leerer Raum waere auf {temp}°C geheizt worden.",
    (
        "climate",
        "high_temp",
    ): "Ohne Eingreifen: Raumtemperatur waere auf {temp}°C gestiegen.",
    (
        "cover",
        "wind_warning",
    ): "Ohne Eingreifen: Markise bei {wind_speed} km/h Windboeen beschaedigt.",
    ("cover", "rain_warning"): "Ohne Eingreifen: Terrassenmoebel waeren nass geworden.",
    (
        "light",
        "empty_room",
    ): "Ohne Eingreifen: Unnoetiger Stromverbrauch von ~{watts}W.",
    ("light", "daylight"): "Ohne Eingreifen: Licht haette trotz Tageslicht gebrannt.",
    (
        "security",
        "door_unlocked",
    ): "Ohne Eingreifen: Haustuer waere ueber Nacht unverschlossen geblieben.",
    (
        "security",
        "alarm_triggered",
    ): "Ohne Eingreifen: Keine sofortige Benachrichtigung.",
    (
        "lock",
        "night_unlocked",
    ): "Ohne Eingreifen: Schloss waere bis morgen offen geblieben.",
}


class ExplainabilityEngine:
    """Trackt Entscheidungen und macht sie erklaerbar."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._ollama = None

        cfg = yaml_config.get("explainability", {})
        self.enabled = cfg.get("enabled", True)
        self.max_history = cfg.get("max_history", 50)
        self.detail_level = cfg.get(
            "detail_level", "normal"
        )  # minimal, normal, verbose
        self.auto_explain = cfg.get("auto_explain", True)
        self.counterfactual_enabled = cfg.get("counterfactual_enabled", True)
        self.reasoning_chains = cfg.get("reasoning_chains", True)
        self.confidence_display = cfg.get("confidence_display", True)
        self.explanation_style = cfg.get("explanation_style", "auto")

        # In-Memory Decision Log (FIFO)
        self._decisions: deque[dict] = deque(maxlen=self.max_history)

    def reload_config(self):
        """Laedt die Konfiguration aus yaml_config neu (Hot-Reload)."""
        cfg = yaml_config.get("explainability", {})
        self.enabled = cfg.get("enabled", True)
        self.max_history = cfg.get("max_history", 50)
        self.detail_level = cfg.get("detail_level", "normal")
        self.auto_explain = cfg.get("auto_explain", True)
        self.counterfactual_enabled = cfg.get("counterfactual_enabled", True)
        self.reasoning_chains = cfg.get("reasoning_chains", True)
        self.confidence_display = cfg.get("confidence_display", True)
        self.explanation_style = cfg.get("explanation_style", "auto")
        if self._decisions.maxlen != self.max_history:
            old_items = list(self._decisions)
            self._decisions.clear()
            # Erstelle neue Deque mit neuem maxlen
            self._decisions = deque(
                old_items[-self.max_history :], maxlen=self.max_history
            )
        logger.info(
            "ExplainabilityEngine config reloaded (enabled: %s, style: %s)",
            self.enabled,
            self.explanation_style,
        )

    def set_ollama(self, ollama_client):
        """Setzt den OllamaClient fuer LLM-basierte Erklaerungen."""
        self._ollama = ollama_client

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_decisions()
        logger.info(
            "ExplainabilityEngine initialisiert (enabled: %s, detail: %s)",
            self.enabled,
            self.detail_level,
        )

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
        alternative_outcomes: list[str] = None,
    ):
        """Loggt eine Entscheidung mit Begruendung und kontrafaktischen Ergebnissen.

        Args:
            action: Was wurde gemacht (z.B. "Licht Wohnzimmer auf 50%")
            reason: Warum (z.B. "Abend-Routine, Sonnenuntergang vor 15 Min")
            context: Zusaetzlicher Kontext (Sensordaten, Regeln etc.)
            trigger: Was hat die Aktion ausgeloest (user_command, automation, anticipation, etc.)
            person: Betroffene Person
            domain: Domaene (climate, light, media, etc.)
            confidence: Konfidenz der Entscheidung (0-1)
            alternative_outcomes: Was waere ohne Eingreifen passiert (kontrafaktisch)
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
                k: v
                for k, v in (context or {}).items()
                if k
                in (
                    "room",
                    "sensor_values",
                    "rule",
                    "pattern",
                    "mood",
                    "autonomy_level",
                    "weather",
                    "calendar_event",
                    "counterfactual",
                )
            }

        # Kontrafaktische Ergebnisse: explizit, proaktiv (aus Context) oder automatisch
        if alternative_outcomes:
            decision["alternative_outcomes"] = alternative_outcomes
        elif context and context.get("counterfactual"):
            # Proaktives Counterfactual (vor Ausfuehrung berechnet)
            decision["alternative_outcomes"] = [context["counterfactual"]]
        elif self.counterfactual_enabled:
            counterfactual = self._build_counterfactual(domain, context or {})
            if counterfactual:
                decision["alternative_outcomes"] = [counterfactual]

        self._decisions.append(decision)

        # In Redis persistieren
        if self.redis:
            try:
                await self.redis.lpush(
                    REDIS_KEY_DECISIONS, json.dumps(decision, ensure_ascii=False)
                )
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
        return [d for d in reversed(self._decisions) if d.get("domain") == domain][:n]

    def explain_by_action(self, action_keyword: str, n: int = 5) -> list[dict]:
        """Sucht Entscheidungen die ein bestimmtes Keyword enthalten."""
        kw = action_keyword.lower()
        return [
            d
            for d in reversed(self._decisions)
            if kw in d.get("action", "").lower() or kw in d.get("reason", "").lower()
        ][:n]

    # Butler-Ton Templates: natuerliche Erklaerungen statt Logfile-Stil
    BUTLER_TEMPLATES: dict[str, str] = {
        "user_command": "Wie gewuenscht: {action}.",
        "automation": "Ich habe mir erlaubt, {action} auszufuehren — {reason}.",
        "anticipation": "Basierend auf Ihren Gewohnheiten habe ich {action} — {reason}.",
        "proactive": "Mir ist aufgefallen: {reason}. Daher habe ich {action}.",
        "schedule": "Planmaessig: {action} — {reason}.",
        "sensor": "Die Sensoren zeigen: {reason}. Ich habe daher {action}.",
        "conflict": "Ich habe einen Konflikt bemerkt: {reason}. Daher {action}.",
        "safety": "Aus Sicherheitsgruenden: {action} — {reason}.",
    }

    # Confidence-Einschuebe fuer Butler-Ton
    CONFIDENCE_HINTS: list[tuple[float, str]] = [
        (0.9, ""),  # Sehr sicher — kein Hinweis noetig
        (0.7, " (ziemlich sicher)"),
        (0.0, " (unsicher)"),
    ]

    def format_explanation(self, decision: dict) -> str:
        """Formatiert eine Entscheidung als natuerlichsprachliche Erklaerung.

        Nutzt Butler-Templates fuer natuerlichen Ton. Faellt auf strukturiertes
        Format zurueck wenn kein passendes Template existiert.

        Args:
            decision: Entscheidungs-Dict

        Returns:
            Menschenlesbare Erklaerung im Butler-Stil
        """
        action = decision.get("action", "Unbekannte Aktion")
        reason = decision.get("reason", "Kein Grund angegeben")
        trigger = decision.get("trigger", "")
        time_str = decision.get("time_str", "")
        confidence = decision.get("confidence", 1.0)

        # Butler-Template waehlen
        template = self.BUTLER_TEMPLATES.get(trigger)
        if template:
            text = template.format(action=action, reason=reason)

            # Confidence-Hinweis anfuegen wenn aktiviert
            if self.confidence_display:
                for threshold, hint in self.CONFIDENCE_HINTS:
                    if confidence >= threshold:
                        if hint:
                            text = text.rstrip(".") + hint + "."
                        break

            if time_str:
                text = text.rstrip(".") + f" ({time_str})."

            # Reasoning-Chain auch im Template-Pfad anfuegen
            if self.reasoning_chains:
                domain = decision.get("domain", "")
                if trigger and domain:
                    text = (
                        text.rstrip(".")
                        + f". Kausalkette: {trigger} -> {reason} -> {action}."
                    )

            return text

        # Fallback: strukturiertes Format fuer unbekannte Trigger
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

        if self.confidence_display:
            if confidence >= 0.9:
                action_prefix = f"Ich habe '{action}' ausgefuehrt"
            elif confidence >= 0.7:
                action_prefix = (
                    f"Ich habe wahrscheinlich richtig gehandelt: '{action}' ausgefuehrt"
                )
            else:
                action_prefix = f"Ich habe moeglicherweise '{action}' ausgefuehrt"
        else:
            action_prefix = f"Ich habe '{action}' ausgefuehrt"

        parts = [action_prefix]
        if trigger_text:
            parts[0] += f" ({trigger_text})"
        parts.append(f"Grund: {reason}")

        if self.detail_level == "verbose" and confidence < 1.0:
            parts.append(f"Konfidenz: {confidence:.0%}")

        if time_str:
            parts.append(f"Zeitpunkt: {time_str}")

        if self.reasoning_chains:
            domain = decision.get("domain", "")
            if trigger and domain:
                parts.append(f"Kausalkette: {trigger} -> {reason} -> {action}")

        return ". ".join(parts) + "."

    async def get_explanation(self, decision: dict) -> str:
        """Gibt eine Erklaerung basierend auf dem konfigurierten explanation_style zurueck.

        - "template": Immer format_explanation() (schnell)
        - "llm": Immer format_explanation_llm() (natuerlich)
        - "auto": Template fuer einfache Erklaerungen (einzelner Trigger), LLM fuer komplexe
        """
        style = self.explanation_style
        if style == "template":
            return self.format_explanation(decision)
        if style == "llm":
            return await self.format_explanation_llm(decision)
        # auto: LLM fuer komplexe Erklaerungen, Template fuer einfache
        is_complex = (
            len(decision.get("alternative_outcomes", [])) > 0
            or decision.get("confidence", 1.0) < 0.9
            or decision.get("trigger", "") in ("anticipation", "proactive", "conflict")
        )
        if is_complex:
            return await self.format_explanation_llm(decision)
        return self.format_explanation(decision)

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
                                IDENTITY_BLOCK + "\n\n"
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
                    content = content[think_end + 8 :].strip()

            if content and len(content) > 10:
                return content

        except Exception as e:
            logger.debug("Explainability LLM Fehler: %s", e)

        return self.format_explanation(decision)

    @staticmethod
    def _build_counterfactual(domain: str, context: dict) -> Optional[str]:
        """Generiert kontrafaktische Erklaerung: Was waere ohne Eingreifen passiert?

        Args:
            domain: Domaene der Aktion (climate, light, cover, etc.)
            context: Kontext-Dict mit Sensordaten und Regeln

        Returns:
            Kontrafaktische Erklaerung oder None
        """
        if not domain or not context:
            return None

        # Context-Keys durchgehen und passende Regel finden
        context_keys = set()
        rule = context.get("rule", "")
        sensor_values = context.get("sensor_values", {})

        # Context-Keys aus verschiedenen Quellen ableiten
        if "window" in str(context).lower() or "fenster" in str(context).lower():
            context_keys.add("window_open")
        if context.get("room_empty") or "leer" in str(context).lower():
            context_keys.add("empty_room")
        if "wind" in str(context).lower() or "sturm" in str(context).lower():
            context_keys.add("wind_warning")
        if "regen" in str(context).lower() or "rain" in str(context).lower():
            context_keys.add("rain_warning")
        if "tageslicht" in str(context).lower() or "daylight" in str(context).lower():
            context_keys.add("daylight")
        if "nacht" in str(context).lower() or "night" in str(context).lower():
            context_keys.add("night_unlocked")
        if "alarm" in str(context).lower():
            context_keys.add("alarm_triggered")

        # Temperaturschwelle
        temp = sensor_values.get("temperature", sensor_values.get("temp"))
        if temp and domain == "climate":
            try:
                if float(temp) > 26:
                    context_keys.add("high_temp")
            except (ValueError, TypeError):
                pass

        # Beste Regel finden
        for ctx_key in context_keys:
            rule_key = (domain, ctx_key)
            template = _COUNTERFACTUAL_RULES.get(rule_key)
            if template:
                # Template mit verfuegbaren Werten fuellen
                format_vals = {
                    "cost": sensor_values.get("cost", "0.50"),
                    "temp": sensor_values.get("temperature", "25"),
                    "wind_speed": sensor_values.get("wind_speed", "60"),
                    "watts": sensor_values.get("power", "60"),
                }
                try:
                    return template.format(**format_vals)
                except (KeyError, ValueError):
                    return template.split("{")[0].rstrip()

        return None

    def get_explanation_prompt_hint(self) -> str:
        """Gibt einen Prompt-Hinweis fuer Erklaerbarkeit zurueck.

        Wird in den System-Prompt eingebaut wenn auto_explain aktiv ist.
        Enthaelt jetzt auch kontrafaktische Daten.
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

        hint = f"Letzte automatische Aktion: '{d['action']}' (Grund: {d['reason']}). "

        # Kontrafaktische Daten hinzufuegen
        alt_outcomes = d.get("alternative_outcomes", [])
        if alt_outcomes:
            hint += f"{alt_outcomes[0]} "

        hint += "Bei Rueckfragen erklaere warum du das getan hast."
        return hint

    def get_auto_explanation(self, action_type: str, domain: str = "") -> Optional[str]:
        """Gibt automatische Erklaerung fuer sicherheitskritische Domaenen zurueck.

        Bei HIGH_IMPACT_DOMAINS wird eine kurze Begruendung generiert,
        damit der User versteht warum Jarvis autonom gehandelt hat.
        """
        HIGH_IMPACT_DOMAINS = {"security", "climate", "lock", "alarm"}
        if domain in HIGH_IMPACT_DOMAINS:
            return (
                f"Grund: {domain}-Aktion ({action_type}) bei Autonomie-Level >= 3 "
                f"automatisch ausgefuehrt."
            )
        return None

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

    # ------------------------------------------------------------------
    # Deep Causal Reasoning: Multi-Level Why-Chains
    # ------------------------------------------------------------------

    # Kausale Regeln: (trigger_type, context_key) → naechste Ebene
    # Jede Kette beschreibt: "Warum X?" → "Weil Y" → "Warum Y?" → "Weil Z"
    _CAUSAL_CHAINS: dict[str, list[dict]] = {
        "climate_window_open": [
            {
                "level": 1,
                "cause": "Fenster offen erkannt",
                "sensor": "binary_sensor.*window*",
            },
            {
                "level": 2,
                "cause": "Heizenergie wird verschwendet",
                "metric": "energy_waste",
            },
            {
                "level": 3,
                "cause": "Waermeverlust: {loss_rate}°C/Stunde bei {delta_temp}°C Differenz",
            },
        ],
        "climate_empty_room": [
            {
                "level": 1,
                "cause": "Raum als leer erkannt (kein Bewegungsmelder-Signal)",
            },
            {"level": 2, "cause": "Heizen eines leeren Raums ist Energieverschwendung"},
            {
                "level": 3,
                "cause": "Praesenz-Sensor meldet seit {minutes} Min keine Bewegung",
            },
        ],
        "climate_frost": [
            {
                "level": 1,
                "cause": "Frostgefahr erkannt (Vorhersage: {forecast_temp}°C)",
            },
            {
                "level": 2,
                "cause": "Wasserleitungen und Pflanzen koennten Schaden nehmen",
            },
            {
                "level": 3,
                "cause": "Wetterdienst meldet Frost fuer die naechsten {hours} Stunden",
            },
        ],
        "cover_storm": [
            {
                "level": 1,
                "cause": "Sturmwarnung: Windgeschwindigkeit {wind_speed} km/h",
            },
            {"level": 2, "cause": "Markise/Rollladen koennte beschaedigt werden"},
            {
                "level": 3,
                "cause": "Schwellwert {threshold} km/h ueberschritten (Wetterstation)",
            },
        ],
        "light_daylight": [
            {"level": 1, "cause": "Ausreichend Tageslicht vorhanden"},
            {
                "level": 2,
                "cause": "Sonnenstand: Elevation {sun_elevation}°, Helligkeit genuegt",
            },
            {
                "level": 3,
                "cause": "Astronomischer Sensor: Sonnenauf-/untergangsberechnung",
            },
        ],
        "security_night_unlock": [
            {"level": 1, "cause": "Naechtliches Entriegeln ist ein Sicherheitsrisiko"},
            {
                "level": 2,
                "cause": "Uhrzeit {hour}:00 liegt in der Sicherheitszone (22-06 Uhr)",
            },
            {
                "level": 3,
                "cause": "Konfigurierte Sicherheitsregel: Nachtverriegelung aktiv",
            },
        ],
        "energy_peak": [
            {"level": 1, "cause": "Hoher Strompreis erkannt ({price}€/kWh)"},
            {
                "level": 2,
                "cause": "Flexible Verbraucher sollten auf guenstigere Zeiten verschoben werden",
            },
            {
                "level": 3,
                "cause": "Stromboerse meldet Peak-Tarif fuer die naechsten {hours} Stunden",
            },
        ],
        "anticipation_pattern": [
            {
                "level": 1,
                "cause": "Wiederkehrendes Muster erkannt (Confidence: {confidence}%)",
            },
            {
                "level": 2,
                "cause": "Aktion wurde {count}x zur selben Uhrzeit/Wochentag beobachtet",
            },
            {"level": 3, "cause": "Datengrundlage: {weeks} Wochen Aktionshistorie"},
        ],
    }

    async def build_why_chain(
        self,
        action: str,
        domain: str = "",
        context: dict = None,
        max_depth: int = 3,
    ) -> list[dict]:
        """Baut eine mehrstufige Why-Chain fuer eine Entscheidung.

        Beispiel-Ausgabe::

            [
                {"level": 1, "why": "Heizung wurde reduziert", "because": "Fenster offen erkannt"},
                {"level": 2, "why": "Fenster offen ist relevant", "because": "Heizenergie wird verschwendet"},
                {"level": 3, "why": "Verschwendung entsteht", "because": "Waermeverlust: 2.1°C/Stunde..."},
            ]

        Args:
            action: Die ausgefuehrte Aktion.
            domain: Die Domaene (climate, cover, light, security...).
            context: Kontext-Daten (Sensoren, Wetter, Regeln).
            max_depth: Maximale Tiefe der Kette (1-3).

        Returns:
            Liste von Why-Chain-Ebenen.
        """
        ctx = context or {}
        chain = []

        # 1. Passende kausale Kette finden
        chain_key = self._find_chain_key(domain, ctx)
        if chain_key and chain_key in self._CAUSAL_CHAINS:
            template_chain = self._CAUSAL_CHAINS[chain_key]
            for step in template_chain[:max_depth]:
                cause = step["cause"]
                # Template-Variablen ersetzen
                try:
                    cause = cause.format(**ctx)
                except (KeyError, ValueError):
                    pass  # Fehlende Variablen bleiben als Platzhalter
                chain.append(
                    {
                        "level": step["level"],
                        "because": cause,
                    }
                )

        # 2. Letzte Entscheidung aus History anreichern
        last = self._find_related_decision(action, domain)
        if last and not chain:
            chain.append(
                {
                    "level": 1,
                    "because": last.get("reason", "Kein Grund protokolliert"),
                }
            )
            alt = last.get("alternative_outcomes", [])
            if alt:
                chain.append(
                    {
                        "level": 2,
                        "because": f"Alternative: {alt[0]}",
                    }
                )

        # 3. Wenn immer noch leer: LLM-Fallback
        if not chain and self._ollama:
            llm_reason = await self._generate_why_chain_llm(action, domain, ctx)
            if llm_reason:
                chain = llm_reason

        return chain

    def _find_chain_key(self, domain: str, context: dict) -> Optional[str]:
        """Findet den passenden Causal-Chain-Schluessel basierend auf Domain + Kontext."""
        # Direkte Kontext-Schluessel pruefen
        for ctx_key in (
            "window_open",
            "empty_room",
            "frost",
            "storm",
            "daylight",
            "night_unlock",
            "peak",
            "pattern",
        ):
            full_key = f"{domain}_{ctx_key}"
            if full_key in self._CAUSAL_CHAINS:
                # Pruefen ob Kontext passt
                if ctx_key in context or any(
                    ctx_key in str(v) for v in context.values()
                ):
                    return full_key

        # Fallback: Domain-basiert
        for key in self._CAUSAL_CHAINS:
            if key.startswith(f"{domain}_"):
                return key

        # Anticipation-Pattern als Fallback
        if context.get("trigger") == "anticipation" or context.get("confidence"):
            return "anticipation_pattern"

        return None

    def _find_related_decision(self, action: str, domain: str) -> Optional[dict]:
        """Sucht die letzte verwandte Entscheidung in der History."""
        for d in reversed(self._decisions):
            if (
                d.get("domain") == domain
                or action.lower() in d.get("action", "").lower()
            ):
                return d
        return None

    async def _generate_why_chain_llm(
        self,
        action: str,
        domain: str,
        context: dict,
    ) -> list[dict]:
        """LLM-basierte Why-Chain fuer Faelle ohne vordefinierte Regeln."""
        if not self._ollama:
            return []
        try:
            prompt = (
                f"Erklaere in GENAU 3 Schritten warum ein Smart-Home-Assistent "
                f"die Aktion '{action}' (Domain: {domain}) ausgefuehrt hat.\n"
                f"Kontext: {json.dumps(context, ensure_ascii=False, default=str)[:500]}\n\n"
                f"Antwort als JSON-Liste: "
                f'[{{"level": 1, "because": "..."}}, {{"level": 2, "because": "..."}}, '
                f'{{"level": 3, "because": "..."}}]'
            )
            response = await self._ollama.generate(prompt, model_tier="fast")
            text = (
                response.get("response", "")
                if isinstance(response, dict)
                else str(response)
            )

            # JSON aus Antwort extrahieren
            import re

            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.debug("LLM Why-Chain Fehler: %s", e)
        return []

    def format_why_chain(self, chain: list[dict]) -> str:
        """Formatiert eine Why-Chain als lesbaren Text.

        Beispiel::

            Warum? → Fenster offen erkannt
              └─ Weil: Heizenergie wird verschwendet
                  └─ Weil: Waermeverlust: 2.1°C/Stunde bei 12°C Differenz
        """
        if not chain:
            return "Keine Begruendungskette verfuegbar."
        lines = []
        for step in chain:
            level = step.get("level", 1)
            indent = "  " * (level - 1) + ("└─ Weil: " if level > 1 else "Warum? → ")
            lines.append(f"{indent}{step.get('because', '?')}")
        return "\n".join(lines)
