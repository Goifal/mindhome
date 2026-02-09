"""MindHome - Air Quality Domain Plugin (Phase 3)"""
from .base import DomainPlugin


class AirQualityDomain(DomainPlugin):
    DOMAIN_NAME = "air_quality"
    HA_DOMAINS = ["sensor"]
    DEVICE_CLASSES = ["moisture", "humidity", "co2", "volatile_organic_compounds", "pm25", "pm10"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "co2_warning": "1000", "co2_critical": "1500",
        "humidity_low": "30", "humidity_high": "65",
    }

    def on_start(self):
        self.logger.info("Air Quality domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        if isinstance(new_state, dict):
            dc = new_state.get("attributes", {}).get("device_class", "")
            if dc not in self.DEVICE_CLASSES:
                return
            state = new_state.get("state", "")
        else:
            state = new_state
        self.logger.debug(f"AirQuality {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "co2", "label_de": "CO2", "label_en": "CO2"},
            {"key": "humidity", "label_de": "Luftfeuchtigkeit", "label_en": "Humidity"},
            {"key": "pm25", "label_de": "Feinstaub PM2.5", "label_en": "PM2.5"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        relevant = [e for e in entities if e.get("attributes", {}).get("device_class") in self.DEVICE_CLASSES]
        return {"total": len(relevant)}

    def get_plugin_actions(self):
        return [
            {"key": "co2_warning", "label_de": "CO2 Warnung", "label_en": "CO2 warning", "default": True},
            {"key": "humidity_warning", "label_de": "Feuchtigkeitswarnung (Schimmel)", "label_en": "Humidity warning (mold)", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        actions = []
        entities = self.get_entities()
        co2_warn = float(self.get_setting("co2_warning", 1000))
        hum_high = float(self.get_setting("humidity_high", 65))

        for e in entities:
            dc = e.get("attributes", {}).get("device_class", "")
            try:
                val = float(e.get("state", 0))
            except (ValueError, TypeError):
                continue
            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])

            if dc == "co2" and val > co2_warn and self.get_setting("co2_warning_enabled", True):
                actions.append({
                    "entity_id": e["entity_id"], "service": "notify",
                    "reason_de": f"CO2 hoch ({val:.0f} ppm): {name} - Lueften empfohlen",
                    "reason_en": f"CO2 high ({val:.0f} ppm): {name} - Ventilate recommended",
                })

            if dc in ("humidity", "moisture") and val > hum_high and self.get_setting("humidity_warning_enabled", True):
                actions.append({
                    "entity_id": e["entity_id"], "service": "notify",
                    "reason_de": f"Feuchtigkeit hoch ({val:.0f}%): {name} - Schimmelgefahr",
                    "reason_en": f"Humidity high ({val:.0f}%): {name} - Mold risk",
                })

        return self.execute_or_suggest(actions)
