"""MindHome - Weather Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class WeatherDomain(DomainPlugin):
    DOMAIN_NAME = "weather"
    HA_DOMAINS = ["weather"]
    DEFAULT_SETTINGS = {"enabled": "true", "mode": "suggest"}

    def on_start(self):
        self.logger.info("Weather domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Weather {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "condition", "label_de": "Zustand", "label_en": "Condition"},
            {"key": "temperature", "label_de": "Temperatur", "label_en": "Temperature"},
            {"key": "forecast", "label_de": "Vorhersage", "label_en": "Forecast"},
        ]

    def get_current_status(self, room_id=None):
        weather = self.get_weather()
        if not weather:
            return {"condition": "unknown", "temperature": None}
        return {
            "condition": weather.get("condition", "unknown"),
            "temperature": weather.get("temperature"),
            "humidity": weather.get("humidity"),
        }

    def get_plugin_actions(self):
        return [
            {"key": "rain_window_warn", "label_de": "Warnung Regen + Fenster offen", "label_en": "Rain + window open warning", "default": True},
            {"key": "cold_heating_suggest", "label_de": "Kaelte-Empfehlung Heizung", "label_en": "Cold weather heating suggestion", "default": True},
        ]

    def evaluate(self, context):
        return []  # Weather triggers handled by door_window and climate plugins
