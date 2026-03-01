"""MindHome - Solar Domain Plugin (Phase 3/4)"""
from .base import DomainPlugin


class SolarDomain(DomainPlugin):
    DOMAIN_NAME = "solar"
    HA_DOMAINS = ["sensor"]
    DEVICE_CLASSES = ["power", "energy"]
    DEFAULT_SETTINGS = {
        "enabled": "false", "mode": "suggest",
        "surplus_threshold_w": "500",
        "low_production_threshold_w": "100",
        "grid_export_entity": "",
        "production_entity": "",
        "consumption_entity": "",
    }

    def on_start(self):
        self.logger.info("Solar domain ready")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        self.logger.debug(f"Solar {entity_id}: -> {state}")

    def get_trackable_features(self):
        return [
            {"key": "production", "label_de": "Erzeugung", "label_en": "Production"},
            {"key": "self_consumption", "label_de": "Eigenverbrauch", "label_en": "Self consumption"},
            {"key": "grid_export", "label_de": "Netzeinspeisung", "label_en": "Grid export"},
        ]

    def get_current_status(self, room_id=None):
        production = self._read_sensor(self.get_setting("production_entity", ""))
        grid_export = self._read_sensor(self.get_setting("grid_export_entity", ""))
        consumption = self._read_sensor(self.get_setting("consumption_entity", ""))

        self_consumption = max(0, production - grid_export) if production and grid_export else 0
        self_sufficiency = round(self_consumption / consumption * 100, 1) if consumption else 0

        return {
            "total": len([e for e in self.get_entities()]),
            "production_w": production or 0,
            "grid_export_w": grid_export or 0,
            "consumption_w": consumption or 0,
            "self_consumption_w": self_consumption,
            "self_sufficiency_pct": self_sufficiency,
        }

    def evaluate(self, context):
        """Bewertet Solar-Produktion und gibt Optimierungsvorschlaege zurueck."""
        if not self.is_enabled():
            return []

        suggestions = []
        status = self.get_current_status()
        production = status.get("production_w", 0)
        grid_export = status.get("grid_export_w", 0)
        consumption = status.get("consumption_w", 0)

        surplus_threshold = float(self.get_setting("surplus_threshold_w", 500))
        low_threshold = float(self.get_setting("low_production_threshold_w", 100))

        # Solar-Ueberschuss: Verbraucher einschalten empfehlen
        if grid_export > surplus_threshold:
            suggestions.append({
                "type": "solar_surplus",
                "priority": "medium",
                "message_de": (
                    f"Solar-Ueberschuss: {grid_export:.0f}W werden ins Netz eingespeist. "
                    f"Guter Zeitpunkt fuer Waschmaschine, Trockner oder E-Auto-Ladung."
                ),
                "message_en": (
                    f"Solar surplus: {grid_export:.0f}W exported to grid. "
                    f"Good time to run washer, dryer, or charge EV."
                ),
                "data": {"grid_export_w": grid_export, "production_w": production},
            })

        # Hohe Eigenverbrauchsquote loben
        sufficiency = status.get("self_sufficiency_pct", 0)
        if production > low_threshold and sufficiency > 80:
            suggestions.append({
                "type": "solar_efficiency",
                "priority": "low",
                "message_de": (
                    f"Solar-Autarkie bei {sufficiency:.0f}% — "
                    f"{production:.0f}W Erzeugung, nur {grid_export:.0f}W Einspeisung."
                ),
                "message_en": (
                    f"Solar self-sufficiency at {sufficiency:.0f}% — "
                    f"{production:.0f}W production, only {grid_export:.0f}W export."
                ),
                "data": {"self_sufficiency_pct": sufficiency},
            })

        # Niedrige Produktion bei Tageslicht: moeglicherweise verschattet
        sun = self.get_sun_state()
        if sun and sun.get("state") == "above_horizon" and production < low_threshold:
            weather = self.get_weather()
            condition = weather.get("state", "") if weather else ""
            if condition not in ("cloudy", "rainy", "pouring", "fog", "snowy"):
                suggestions.append({
                    "type": "solar_low_production",
                    "priority": "low",
                    "message_de": (
                        f"Solar-Erzeugung ungewoehnlich niedrig ({production:.0f}W) "
                        f"trotz Sonnenschein. Module verschattet oder verschmutzt?"
                    ),
                    "message_en": (
                        f"Solar production unusually low ({production:.0f}W) "
                        f"despite sunshine. Panels shaded or dirty?"
                    ),
                    "data": {"production_w": production, "weather": condition},
                })

        return suggestions

    def _read_sensor(self, entity_id):
        """Liest einen numerischen Sensorwert. Gibt None bei Fehler zurueck."""
        if not entity_id:
            return None
        try:
            state = self.get_entity_state(entity_id)
            if state and isinstance(state, dict):
                val = state.get("state", "")
            else:
                val = state
            return float(val)
        except (ValueError, TypeError):
            return None
