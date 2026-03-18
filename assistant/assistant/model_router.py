"""
Model Router - 3-Stufen LLM Routing (fast / smart / deep)

Waehlt das richtige lokale LLM basierend auf Komplexitaet der Anfrage:
  - Fast (3B): Einfache Befehle ("Licht an", "Musik stopp")
  - Smart (14B): Fragen, Konversation, Standard-Interaktion
  - Deep (32B): Komplexe Planung, Multi-Step Reasoning, Simulationen

Auto-Capability: Erkennt beim Start welche Modelle verfuegbar sind.
Wenn das 32B-Modell nicht installiert ist, wird automatisch auf
14B (oder 3B) zurueckgefallen.

Modelle koennen ueber settings.yaml (models.enabled.fast/smart/deep)
einzeln aktiviert/deaktiviert werden — unabhaengig davon ob sie in
Ollama installiert sind.
"""

import logging
import re
from collections import deque

from .config import settings, yaml_config

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routet Anfragen zum passenden lokalen Modell (3 Stufen)."""

    def __init__(self):
        self.model_fast = settings.model_fast
        self.model_smart = settings.model_smart
        self.model_deep = settings.model_deep

        # Verfuegbare Modelle (wird bei initialize() befuellt)
        self._available_models: list[str] = []
        self._deep_available = True
        self._smart_available = True

        # Enabled-Status aus Settings (User-Kontrolle)
        self._deep_enabled = True
        self._smart_enabled = True
        self._fast_enabled = True

        # D1: Task-aware Temperature — Temperatur je nach Aufgabentyp
        self._task_temperatures = {
            "command": 0.3,       # Geraetesteuerung: deterministisch
            "factual": 0.4,       # Fakten-Fragen: wenig Kreativitaet
            "conversation": 0.7,  # Gespraech: natuerlich, variabel
            "creative": 0.8,      # Kreative Aufgaben: mehr Freiheit
            "analysis": 0.5,      # Analyse/Diagnose: balanciert
            "default": 0.6,       # Standard
        }

        # Phase 2C: Latenz-Feedback
        self._latency_history: dict[str, deque] = {
            "fast": deque(maxlen=50),
            "smart": deque(maxlen=50),
            "deep": deque(maxlen=50),
        }
        self._deep_degraded = False
        _router_cfg = yaml_config.get("model_router", {})
        self._latency_feedback_enabled = _router_cfg.get("latency_feedback", True)
        self._deep_degradation_threshold = _router_cfg.get("deep_degradation_threshold_s", 8.0)

        # Keywords und Config laden
        self._load_config()

    def _load_config(self):
        """Laedt Keywords und Enabled-Status aus yaml_config."""
        from .config import yaml_config as cfg
        models_config = cfg.get("models", {})

        # Enabled-Status
        enabled = models_config.get("enabled", {})
        self._fast_enabled = enabled.get("fast", True)
        self._smart_enabled = enabled.get("smart", True)
        self._deep_enabled = enabled.get("deep", True)

        # Keywords
        self.fast_keywords = models_config.get("fast_keywords", [
            "licht", "lampe", "temperatur", "heizung", "rollladen",
            "jalousie", "szene", "alarm", "tuer",
            "musik", "pause", "stopp", "stop",
            "leiser", "lauter", "an", "aus", "schalte", "mach",
        ])
        # Greetings/Smalltalk gehoeren NICHT ins Fast-Routing — sie brauchen
        # das Smart-Modell fuer JARVIS-Persoenlichkeit.
        # "guten morgen", "gute nacht" entfernt (jetzt ans LLM statt Shortcut).

        self.deep_keywords = models_config.get("deep_keywords", [
            "erklaer", "erklaere", "warum genau", "im detail",
            "analysiere", "analyse", "vergleich", "vergleiche",
            "unterschied zwischen", "vor- und nachteile",
            "strategie", "plan", "plane", "planung",
            "optimier", "optimiere", "optimierung",
            "was waere wenn", "was wäre wenn", "hypothetisch",
            "stell dir vor", "angenommen",
            "zusammenfassung", "zusammenfassen", "fasse zusammen",
            "berechne", "berechnung", "kalkulation",
            "wie funktioniert", "wie genau",
            "schreib mir", "schreibe mir", "formuliere",
            "rezept", "anleitung", "tutorial",
            "pro und contra", "bewerte", "bewertung",
        ])

        self.cooking_keywords = models_config.get("cooking_keywords", [
            "kochen", "backen", "rezept", "zubereiten",
            "braten", "grillen",
        ])

        self.deep_min_words = models_config.get("deep_min_words", 15)

    def reload_config(self):
        """
        Laedt Enabled-Status, Keywords UND Modellnamen neu aus yaml_config.
        Aufgerufen nach Settings-Aenderung ueber die UI.
        """
        old_fast = self._fast_enabled
        old_smart = self._smart_enabled
        old_deep = self._deep_enabled
        old_model_fast = self.model_fast
        old_model_smart = self.model_smart
        old_model_deep = self.model_deep

        # Modellnamen aus settings neu laden (config.py aktualisiert settings)
        from .config import settings as cfg
        self.model_fast = cfg.model_fast
        self.model_smart = cfg.model_smart
        self.model_deep = cfg.model_deep

        self._load_config()
        self._update_availability()

        # Aenderungen loggen
        changes = []
        if old_fast != self._fast_enabled:
            changes.append(f"Fast: {'AN' if self._fast_enabled else 'AUS'}")
        if old_smart != self._smart_enabled:
            changes.append(f"Smart: {'AN' if self._smart_enabled else 'AUS'}")
        if old_deep != self._deep_enabled:
            changes.append(f"Deep: {'AN' if self._deep_enabled else 'AUS'}")
        if old_model_fast != self.model_fast:
            changes.append(f"Fast-Modell: {old_model_fast} -> {self.model_fast}")
        if old_model_smart != self.model_smart:
            changes.append(f"Smart-Modell: {old_model_smart} -> {self.model_smart}")
        if old_model_deep != self.model_deep:
            changes.append(f"Deep-Modell: {old_model_deep} -> {self.model_deep}")

        if changes:
            logger.info("Modell-Konfiguration geaendert: %s", ", ".join(changes))
        else:
            logger.debug("Modell-Konfiguration neu geladen (keine Aenderungen)")

    async def initialize(self, available_models: list[str]):
        """
        Prueft welche Modelle tatsaechlich verfuegbar sind und passt
        das Routing entsprechend an.

        Args:
            available_models: Liste der installierten Ollama-Modelle
        """
        self._available_models = [m.lower() for m in available_models]
        self._update_availability()

    def _update_availability(self):
        """Berechnet effektive Verfuegbarkeit (installiert UND aktiviert)."""
        deep_installed = self._is_model_installed(self.model_deep)
        smart_installed = self._is_model_installed(self.model_smart)

        # Modell ist nur verfuegbar wenn: in Ollama installiert UND vom User aktiviert
        self._deep_available = deep_installed and self._deep_enabled
        self._smart_available = smart_installed and self._smart_enabled

        if not self._deep_available:
            reason = []
            if not deep_installed:
                reason.append("nicht installiert")
            if not self._deep_enabled:
                reason.append("deaktiviert")
            logger.info(
                "Deep-Modell '%s' nicht verfuegbar (%s). "
                "Deep-Anfragen → '%s'.",
                self.model_deep,
                ", ".join(reason),
                self.model_smart if self._smart_available else self.model_fast,
            )

        if not self._smart_available:
            reason = []
            if not smart_installed:
                reason.append("nicht installiert")
            if not self._smart_enabled:
                reason.append("deaktiviert")
            logger.info(
                "Smart-Modell '%s' nicht verfuegbar (%s). "
                "Alle Anfragen → '%s'.",
                self.model_smart, ", ".join(reason), self.model_fast,
            )

        logger.info(
            "Modell-Status: Fast(%s)=%s, Smart(%s)=%s, Deep(%s)=%s",
            self.model_fast,
            "AN" if self._fast_enabled else "AUS",
            self.model_smart,
            "AN" if self._smart_available else "AUS",
            self.model_deep,
            "AN" if self._deep_available else "AUS",
        )

    def _is_model_installed(self, model_name: str) -> bool:
        """Prueft ob ein Modell in Ollama installiert ist."""
        if not self._available_models:
            return False  # Kein Check moeglich -> pessimistisch (Fallback nutzen)

        model_lower = model_name.lower()
        for available in self._available_models:
            if available == model_lower or available.startswith(model_lower + ":"):
                return True
            if model_lower.startswith(available + ":"):
                return True
        return False

    def _cap_model(self, requested_model: str) -> str:
        """
        Begrenzt das Modell auf das beste verfuegbare.
        Wenn Deep nicht da/aktiv ist -> Smart. Wenn Smart nicht da/aktiv ist -> Fast.
        """
        if requested_model == self.model_deep and not self._deep_available:
            fallback = self.model_smart if self._smart_available else self.model_fast
            logger.debug("Deep nicht verfuegbar, Fallback: %s", fallback)
            return fallback

        if requested_model == self.model_smart and not self._smart_available:
            logger.debug("Smart nicht verfuegbar, Fallback: %s", self.model_fast)
            return self.model_fast

        return requested_model

    @staticmethod
    def _word_match(keyword: str, text: str) -> bool:
        """Prueft ob ein Keyword als ganzes Wort im Text vorkommt.

        Kurze Keywords (<=3 Zeichen) wie 'an', 'aus' werden als Wortgrenzen
        geprueft um False Positives zu vermeiden ('Manuel' matched nicht 'an').
        Laengere Keywords werden weiterhin als Substring geprueft ('temperatur'
        in 'aussentemperatur').
        """
        if len(keyword) <= 3:
            # Word-Boundary-Match fuer kurze Keywords
            return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
        return keyword in text

    def get_tier_for_model(self, model: str) -> str:
        """Gibt den Tier-Namen fuer ein Modell zurueck.

        Wichtig wenn alle Tiers das gleiche Modell nutzen — dann kann
        der Tier nicht mehr am Modellnamen abgelesen werden.
        """
        if model == self.model_fast and model != self.model_smart:
            return "fast"
        if model == self.model_deep and model != self.model_smart:
            return "deep"
        return "smart"

    def select_model_and_tier(self, text: str) -> tuple[str, str]:
        """Waehlt Modell UND gibt den Tier-Namen zurueck.

        Returns:
            Tuple (model_name, tier) wobei tier 'fast', 'smart' oder 'deep' ist.
            Wichtig fuer korrekten num_ctx wenn alle Tiers das gleiche Modell nutzen.
        """
        text_lower = text.lower().strip()
        word_count = len(text_lower.split())

        # 1. Kurze Befehle -> schnelles Modell (wenn aktiviert)
        if word_count <= 6 and self._fast_enabled:
            for keyword in self.fast_keywords:
                if self._word_match(keyword, text_lower):
                    logger.debug("FAST model fuer: '%s' (keyword: %s)", text, keyword)
                    return self.model_fast, "fast"

        # 2. Deep-Keywords -> Deep-Modell (oder Smart wenn degradiert)
        for keyword in self.deep_keywords:
            if self._word_match(keyword, text_lower):
                if self._deep_degraded:
                    model = self._cap_model(self.model_smart)
                    logger.debug("DEEP→SMART (degradiert) fuer: '%s' (keyword: %s)", text, keyword)
                    return model, "smart"
                model = self._cap_model(self.model_deep)
                logger.debug("DEEP model fuer: '%s' (keyword: %s, actual: %s)",
                             text, keyword, model)
                return model, "deep"

        # 3. Sehr lange Anfragen (>15 Woerter) -> Deep (oder Smart wenn degradiert)
        if word_count >= self.deep_min_words:
            if self._deep_degraded:
                model = self._cap_model(self.model_smart)
                logger.debug("DEEP→SMART (degradiert) fuer lange Anfrage: '%s'", text[:80])
                return model, "smart"
            model = self._cap_model(self.model_deep)
            logger.debug("DEEP model fuer lange Anfrage (%d Woerter): '%s' (actual: %s)",
                         word_count, text[:80], model)
            return model, "deep"

        # 4. Fragen -> schlaues Modell
        if any(text_lower.startswith(w) for w in [
            "was ", "wie ", "warum ", "wann ", "wo ", "wer ",
        ]):
            model = self._cap_model(self.model_smart)
            logger.debug("SMART model fuer Frage: '%s' (actual: %s)", text, model)
            return model, "smart"

        # Default: schlaues Modell
        model = self._cap_model(self.model_smart)
        logger.debug("SMART model (default) fuer: '%s' (actual: %s)", text, model)
        return model, "smart"

    def classify_task(self, text: str) -> str:
        """D1: Klassifiziert die Aufgabe fuer task-aware Temperature.

        Returns:
            Task-Typ: 'command', 'factual', 'conversation', 'creative', 'analysis', 'default'
        """
        text_lower = text.lower().strip()

        # Command: Geraetesteuerung
        for keyword in self.fast_keywords:
            if self._word_match(keyword, text_lower):
                return "command"

        # Creative: Schreibaufgaben, Ideen
        _creative_kw = ("schreib", "formulier", "erfinde", "stell dir vor", "was waere wenn",
                        "was wäre wenn", "hypothetisch", "kreativ", "idee")
        if any(kw in text_lower for kw in _creative_kw):
            return "creative"

        # Analysis: Diagnose, Vergleich, Erklaerung
        _analysis_kw = ("analysier", "vergleich", "unterschied", "vor- und nachteil",
                        "optimier", "berechne", "erklaer", "warum genau", "diagnos")
        if any(kw in text_lower for kw in _analysis_kw):
            return "analysis"

        # Factual: Kurze Fakten-Fragen
        _factual_starts = ("was ist", "wann ", "wo ", "wer ", "wie viel", "wie hoch", "wie warm")
        if any(text_lower.startswith(w) for w in _factual_starts):
            return "factual"

        # Conversation: Laengerer Text, Fragen, Meinungen
        if len(text_lower.split()) > 8 or "?" in text:
            return "conversation"

        return "default"

    def get_task_temperature(self, text: str) -> float:
        """D1: Gibt die optimale Temperature fuer den Task-Typ zurueck."""
        task_type = self.classify_task(text)
        return self._task_temperatures.get(task_type, self._task_temperatures["default"])

    def select_model(self, text: str) -> str:
        """Waehlt das passende Modell (Rueckwaertskompatibel, ohne Tier)."""
        model, _tier = self.select_model_and_tier(text)
        return model

    def get_fallback_model(self, current_model: str) -> str:
        """Gibt ein schnelleres Fallback-Modell zurueck wenn das aktuelle nicht antwortet.

        Deep -> Smart -> Fast. Ueberspringt identische Modelle
        (z.B. wenn Deep == Smart, direkt zu Fast).
        Gibt leeren String zurueck wenn kein Fallback moeglich.
        """
        if current_model == self.model_deep:
            # Wenn Smart ein anderes Modell ist, dorthin fallen
            if self._smart_available and self.model_smart != current_model:
                return self.model_smart
            # Sonst direkt zu Fast
            return self.model_fast
        if current_model == self.model_smart:
            return self.model_fast
        return ""  # Fast hat kein Fallback

    def get_best_available(self) -> str:
        """Gibt das beste verfuegbare und aktivierte Modell zurueck."""
        if self._deep_available:
            return self.model_deep
        if self._smart_available:
            return self.model_smart
        return self.model_fast

    # ------------------------------------------------------------------
    # Phase 2C: Latenz-Feedback und Urgency-Override
    # ------------------------------------------------------------------

    def record_latency(self, tier: str, duration_seconds: float):
        """Zeichnet die Latenz eines LLM-Calls auf.

        Wenn Deep-Tier ueber dem Degradations-Schwellwert liegt,
        wird automatisch auf Smart heruntergestuft fuer nicht-kritische Anfragen.

        Args:
            tier: 'fast', 'smart' oder 'deep'
            duration_seconds: Antwortzeit in Sekunden
        """
        if not self._latency_feedback_enabled:
            return
        if tier not in self._latency_history:
            return

        self._latency_history[tier].append(duration_seconds)

        # Deep-Degradation pruefen: Durchschnitt der letzten 10 Calls
        if tier == "deep" and len(self._latency_history["deep"]) >= 10:
            recent = list(self._latency_history["deep"])[-10:]
            avg = sum(recent) / len(recent)
            was_degraded = self._deep_degraded
            self._deep_degraded = avg > self._deep_degradation_threshold

            if self._deep_degraded and not was_degraded:
                logger.warning(
                    "Deep-Modell degradiert: Durchschnitt %.1fs > %.1fs Schwelle. "
                    "Nicht-kritische Anfragen werden auf Smart heruntergestuft.",
                    avg, self._deep_degradation_threshold,
                )
            elif not self._deep_degraded and was_degraded:
                logger.info("Deep-Modell erholt: Durchschnitt %.1fs unter Schwelle.", avg)

    def urgency_override(self, mood: str = "", stress_level: float = 0.0) -> str | None:
        """Gibt einen Tier-Override basierend auf Dringlichkeit zurueck.

        Bei hohem Stress oder Frustration → schnellstes Modell fuer sofortige Antwort.

        Args:
            mood: Aktuelle Stimmung (frustrated, stressed, etc.)
            stress_level: Stress-Level (0.0 - 1.0)

        Returns:
            Tier-Name ('fast') oder None wenn kein Override noetig.
        """
        if mood in ("frustrated", "stressed") and stress_level > 0.7:
            logger.debug("Urgency override: %s + stress=%.2f → Fast-Modell", mood, stress_level)
            return "fast"
        return None

    def get_routing_stats(self) -> dict:
        """Gibt Routing-Statistiken zurueck (Latenz, Degradation)."""
        stats = {}
        for tier, history in self._latency_history.items():
            if history:
                vals = list(history)
                stats[tier] = {
                    "count": len(vals),
                    "avg_s": round(sum(vals) / len(vals), 2),
                    "min_s": round(min(vals), 2),
                    "max_s": round(max(vals), 2),
                }
            else:
                stats[tier] = {"count": 0, "avg_s": 0, "min_s": 0, "max_s": 0}
        stats["deep_degraded"] = self._deep_degraded
        return stats

    def get_model_info(self) -> dict:
        """Gibt Info ueber die konfigurierten Modelle zurueck."""
        return {
            "fast": self.model_fast,
            "smart": self.model_smart,
            "deep": self.model_deep,
            "enabled": {
                "fast": self._fast_enabled,
                "smart": self._smart_enabled,
                "deep": self._deep_enabled,
            },
            "deep_available": self._deep_available,
            "smart_available": self._smart_available,
            "best_available": self.get_best_available(),
            "available_models": self._available_models,
            "fast_keywords_count": len(self.fast_keywords),
            "deep_keywords_count": len(self.deep_keywords),
            "cooking_keywords_count": len(self.cooking_keywords),
            "deep_min_words": self.deep_min_words,
            "deep_degraded": self._deep_degraded,
            "latency_feedback": self._latency_feedback_enabled,
        }
