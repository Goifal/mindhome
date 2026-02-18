"""
Model Router - 3-Stufen LLM Routing (fast / smart / deep)

Waehlt das richtige lokale LLM basierend auf Komplexitaet der Anfrage:
  - Fast (3B): Einfache Befehle ("Licht an", "Musik stopp")
  - Smart (14B): Fragen, Konversation, Standard-Interaktion
  - Deep (32B): Komplexe Planung, Multi-Step Reasoning, Simulationen

Auto-Capability: Erkennt beim Start welche Modelle verfuegbar sind.
Wenn das 32B-Modell nicht installiert ist, wird automatisch auf
14B (oder 3B) zurueckgefallen.
"""

import logging

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

        # Keywords aus settings.yaml laden
        models_config = yaml_config.get("models", {})
        self.fast_keywords = models_config.get("fast_keywords", [
            "licht", "lampe", "temperatur", "heizung", "rollladen",
            "jalousie", "szene", "alarm", "tuer", "gute nacht",
            "guten morgen", "musik", "pause", "stopp", "stop",
            "leiser", "lauter", "an", "aus",
        ])

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

        # Koch-Keywords die Deep triggern
        self.cooking_keywords = models_config.get("cooking_keywords", [
            "kochen", "backen", "rezept", "zubereiten",
            "braten", "grillen",
        ])

        # Minimale Wortanzahl fuer Deep-Routing (lange Anfragen = komplex)
        self.deep_min_words = models_config.get("deep_min_words", 15)

    async def initialize(self, available_models: list[str]):
        """
        Prueft welche Modelle tatsaechlich verfuegbar sind und passt
        das Routing entsprechend an.

        Args:
            available_models: Liste der installierten Ollama-Modelle
        """
        self._available_models = [m.lower() for m in available_models]

        # Pruefen ob Deep-Modell verfuegbar
        self._deep_available = self._is_model_available(self.model_deep)
        self._smart_available = self._is_model_available(self.model_smart)

        if not self._deep_available:
            logger.warning(
                "Deep-Modell '%s' NICHT verfuegbar! "
                "Deep-Anfragen werden auf '%s' umgeleitet.",
                self.model_deep,
                self.model_smart if self._smart_available else self.model_fast,
            )

        if not self._smart_available:
            logger.warning(
                "Smart-Modell '%s' NICHT verfuegbar! "
                "Alle Anfragen laufen ueber '%s'.",
                self.model_smart, self.model_fast,
            )

        # Logge verfuegbare Modelle
        logger.info(
            "Modell-Verfuegbarkeit: Fast(%s)=%s, Smart(%s)=%s, Deep(%s)=%s",
            self.model_fast, "JA" if self._is_model_available(self.model_fast) else "NEIN",
            self.model_smart, "JA" if self._smart_available else "NEIN",
            self.model_deep, "JA" if self._deep_available else "NEIN",
        )

    def _is_model_available(self, model_name: str) -> bool:
        """Prueft ob ein Modell in der verfuegbaren Liste ist."""
        if not self._available_models:
            return True  # Kein Check moeglich -> optimistisch

        model_lower = model_name.lower()
        for available in self._available_models:
            # Exakter Match oder Prefix-Match (qwen3:32b matched qwen3:32b-instruct)
            if available == model_lower or available.startswith(model_lower):
                return True
            # Auch umgekehrt: model_name koennte laenger sein
            if model_lower.startswith(available):
                return True
        return False

    def _cap_model(self, requested_model: str) -> str:
        """
        Begrenzt das Modell auf das beste verfuegbare.
        Wenn Deep nicht da ist -> Smart. Wenn Smart nicht da ist -> Fast.
        """
        if requested_model == self.model_deep and not self._deep_available:
            fallback = self.model_smart if self._smart_available else self.model_fast
            logger.debug("Deep nicht verfuegbar, Fallback: %s", fallback)
            return fallback

        if requested_model == self.model_smart and not self._smart_available:
            logger.debug("Smart nicht verfuegbar, Fallback: %s", self.model_fast)
            return self.model_fast

        return requested_model

    def select_model(self, text: str) -> str:
        """
        Waehlt das passende Modell fuer die Anfrage (3 Stufen).

        Routing-Logik:
          1. Kurze Befehle mit Fast-Keywords → Fast (3B)
          2. Deep-Keywords oder sehr lange Anfragen → Deep (32B)
          3. Alles andere → Smart (14B)

        Falls ein Modell nicht verfuegbar ist, wird automatisch
        auf das naechstkleinere zurueckgefallen.

        Args:
            text: User-Eingabe

        Returns:
            Modellname fuer Ollama
        """
        text_lower = text.lower().strip()
        word_count = len(text_lower.split())

        # 1. Kurze Befehle -> schnelles Modell
        if word_count <= 4:
            for keyword in self.fast_keywords:
                if keyword in text_lower:
                    logger.debug("FAST model fuer: '%s' (keyword: %s)", text, keyword)
                    return self.model_fast

        # 2. Deep-Keywords -> Deep-Modell
        for keyword in self.deep_keywords:
            if keyword in text_lower:
                model = self._cap_model(self.model_deep)
                logger.debug("DEEP model fuer: '%s' (keyword: %s, actual: %s)",
                             text, keyword, model)
                return model

        # 3. Sehr lange Anfragen (>15 Woerter) -> Deep
        if word_count >= self.deep_min_words:
            model = self._cap_model(self.model_deep)
            logger.debug("DEEP model fuer lange Anfrage (%d Woerter): '%s' (actual: %s)",
                         word_count, text[:80], model)
            return model

        # 4. Fragen -> schlaues Modell
        if any(text_lower.startswith(w) for w in [
            "was ", "wie ", "warum ", "wann ", "wo ", "wer ",
        ]):
            model = self._cap_model(self.model_smart)
            logger.debug("SMART model fuer Frage: '%s' (actual: %s)", text, model)
            return model

        # Default: schlaues Modell
        model = self._cap_model(self.model_smart)
        logger.debug("SMART model (default) fuer: '%s' (actual: %s)", text, model)
        return model

    def get_best_available(self) -> str:
        """Gibt das beste verfuegbare Modell zurueck."""
        if self._deep_available:
            return self.model_deep
        if self._smart_available:
            return self.model_smart
        return self.model_fast

    def get_tier(self, text: str) -> str:
        """Gibt die Tier-Bezeichnung zurueck (fast/smart/deep)."""
        model = self.select_model(text)
        if model == self.model_fast:
            return "fast"
        elif model == self.model_deep:
            return "deep"
        return "smart"

    def get_model_info(self) -> dict:
        """Gibt Info ueber die konfigurierten Modelle zurueck."""
        return {
            "fast": self.model_fast,
            "smart": self.model_smart,
            "deep": self.model_deep,
            "deep_available": self._deep_available,
            "smart_available": self._smart_available,
            "best_available": self.get_best_available(),
            "available_models": self._available_models,
            "fast_keywords_count": len(self.fast_keywords),
            "deep_keywords_count": len(self.deep_keywords),
            "cooking_keywords_count": len(self.cooking_keywords),
            "deep_min_words": self.deep_min_words,
        }
