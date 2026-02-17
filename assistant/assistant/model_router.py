"""
Model Router - 3-Stufen LLM Routing (fast / smart / deep)

Waehlt das richtige lokale LLM basierend auf Komplexitaet der Anfrage:
  - Fast (3B): Einfache Befehle ("Licht an", "Musik stopp")
  - Smart (14B): Fragen, Konversation, Standard-Interaktion
  - Deep (32B): Komplexe Planung, Multi-Step Reasoning, Simulationen
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

        # Minimale Wortanzahl fuer Deep-Routing (lange Anfragen = komplex)
        self.deep_min_words = models_config.get("deep_min_words", 15)

    def select_model(self, text: str) -> str:
        """
        Waehlt das passende Modell fuer die Anfrage (3 Stufen).

        Routing-Logik:
          1. Kurze Befehle mit Fast-Keywords → Fast (3B)
          2. Deep-Keywords oder sehr lange Anfragen → Deep (32B)
          3. Alles andere → Smart (14B)

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
                logger.debug("DEEP model fuer: '%s' (keyword: %s)", text, keyword)
                return self.model_deep

        # 3. Sehr lange Anfragen (>15 Woerter) -> Deep
        if word_count >= self.deep_min_words:
            logger.debug("DEEP model fuer lange Anfrage (%d Woerter): '%s'",
                         word_count, text[:80])
            return self.model_deep

        # 4. Fragen -> schlaues Modell
        if any(text_lower.startswith(w) for w in [
            "was ", "wie ", "warum ", "wann ", "wo ", "wer ",
        ]):
            logger.debug("SMART model fuer Frage: '%s'", text)
            return self.model_smart

        # Default: schlaues Modell
        logger.debug("SMART model (default) fuer: '%s'", text)
        return self.model_smart

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
            "fast_keywords_count": len(self.fast_keywords),
            "deep_keywords_count": len(self.deep_keywords),
            "deep_min_words": self.deep_min_words,
        }
