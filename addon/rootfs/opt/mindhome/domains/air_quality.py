"""
MindHome - Air Quality Domain Plugin
Tracks CO2, VOC, humidity, particulate matter.
"""

from .base import DomainPlugin


class AirQualityDomain(DomainPlugin):
    DOMAIN_NAME = "air_quality"
    HA_DOMAINS = ["sensor", "binary_sensor"]
    DEVICE_CLASSES = ["carbon_dioxide", "volatile_organic_compounds",
                      "humidity", "moisture", "pm25", "pm10", "aqi"]

    def on_start(self):
        self.logger.info("Air Quality domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state):
        if not self.is_entity_tracked(entity_id):
            return

        device_class = new_state.get("attributes", {}).get("device_class", "")
        if device_class not in self.DEVICE_CLASSES:
            return

        self.logger.debug(
            f"Air Quality {entity_id}: {new_state.get('state')} "
            f"{new_state.get('attributes', {}).get('unit_of_measurement', '')}"
        )

    def get_trackable_features(self):
        return [
            {"key": "co2", "label_de": "CO2 (ppm)", "label_en": "CO2 (ppm)"},
            {"key": "voc", "label_de": "VOC", "label_en": "VOC"},
            {"key": "humidity", "label_de": "Luftfeuchtigkeit", "label_en": "Humidity"},
            {"key": "pm25", "label_de": "Feinstaub PM2.5", "label_en": "PM2.5"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities
                    if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        return {
            "total": len(relevant),
            "sensors": len(relevant)
        }
