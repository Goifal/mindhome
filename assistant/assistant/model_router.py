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
            "jalousie", "szene", "alarm", "tuer", "gute nacht",
            "guten morgen", "musik", "pause", "stopp", "stop",
            "leiser", "lauter", "an", "aus", "schalte", "mach",
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

        self.cooking_keywords = models_config.get("cooking_keywords", [
            "kochen", "backen", "rezept", "zubereiten",
            "braten", "grillen",
        ])

        self.deep_min_words = models_config.get("deep_min_words", 15)

    def reload_config(self):
        """
        Laedt Enabled-Status und Keywords neu aus yaml_config.
        Aufgerufen nach Settings-Aenderung ueber die UI.
        """
        old_fast = self._fast_enabled
        old_smart = self._smart_enabled
        old_deep = self._deep_enabled

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
            return True  # Kein Check moeglich -> optimistisch

        model_lower = model_name.lower()
        for available in self._available_models:
            if available == model_lower or available.startswith(model_lower):
                return True
            if model_lower.startswith(available):
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

    def select_model(self, text: str) -> str:
        """
        Waehlt das passende Modell fuer die Anfrage (3 Stufen).

        Routing-Logik:
          1. Kurze Befehle mit Fast-Keywords → Fast (3B)
          2. Deep-Keywords oder sehr lange Anfragen → Deep (32B)
          3. Alles andere → Smart (14B)

        Falls ein Modell nicht verfuegbar oder deaktiviert ist,
        wird automatisch auf das naechstkleinere zurueckgefallen.
        """
        text_lower = text.lower().strip()
        word_count = len(text_lower.split())

        # 1. Kurze Befehle -> schnelles Modell (wenn aktiviert)
        if word_count <= 6 and self._fast_enabled:
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

    def get_fallback_model(self, current_model: str) -> str:
        """Gibt ein schnelleres Fallback-Modell zurueck wenn das aktuelle nicht antwortet.

        Deep -> Smart -> Fast. Gibt None zurueck wenn kein Fallback moeglich.
        """
        if current_model == self.model_deep:
            if self._smart_available:
                return self.model_smart
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
        }
