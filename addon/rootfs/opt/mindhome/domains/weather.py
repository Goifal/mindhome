"""
MindHome - Weather Domain Plugin
Uses external weather data as influence factor.
"""

from .base import DomainPlugin


class WeatherDomain(DomainPlugin):
    DOMAIN_NAME = "weather"
    HA_DOMAINS = ["weather"]

    def on_start(self):
        self.logger.info("Weather domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        self.logger.debug(
            f"Weather {entity_id}: {new_state.get('state')} "
            f"temp={new_state.get('attributes', {}).get('temperature', '?')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "condition", "label_de": "Wetterlage", "label_en": "Condition"},
            {"key": "temperature", "label_de": "Außentemperatur", "label_en": "Outside Temperature"},
            {"key": "forecast", "label_de": "Vorhersage", "label_en": "Forecast"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        if entities:
            weather = entities[0]
            attrs = weather.get("attributes", {})
            return {
                "condition": weather.get("state", "unknown"),
                "temperature": attrs.get("temperature"),
                "humidity": attrs.get("humidity"),
                "wind_speed": attrs.get("wind_speed")
            }
        return {"condition": "unavailable"}
