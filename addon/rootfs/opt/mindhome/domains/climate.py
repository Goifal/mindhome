"""MindHome - Climate Domain Plugin (Phase 3)
Unterstuetzt zwei Heizungsmodi:
  - room_thermostat: Einzelraumregelung mit climate.* Entities pro Raum
  - heating_curve:   Feste Heizkurve, nur Vorlauftemperatur-Offset steuerbar
"""
from .base import DomainPlugin


class ClimateDomain(DomainPlugin):
    DOMAIN_NAME = "climate"
    HA_DOMAINS = ["climate"]
    DEFAULT_SETTINGS = {
        "enabled": "true", "mode": "suggest",
        "away_temp": "17", "night_temp": "18", "preheat_minutes": "30",
        # Heizungsmodus: "room_thermostat" oder "heating_curve"
        "heating_mode": "room_thermostat",
        # Nur fuer heating_curve: Entity-ID und Offsets
        "curve_entity": "",
        "away_offset": "-3",
        "night_offset": "-2",
    }

    def on_start(self):
        hm = self.get_setting("heating_mode", "room_thermostat")
        self.logger.info(f"Climate domain ready (mode: {hm})")

    def on_stop(self):
        pass

    def on_state_change(self, entity_id, old_state, new_state, context=None):
        if not self.is_entity_tracked(entity_id):
            return
        state = new_state.get("state", "") if isinstance(new_state, dict) else new_state
        attrs = new_state.get("attributes", {}) if isinstance(new_state, dict) else {}
        temp = attrs.get("current_temperature")
        self.logger.debug(f"Climate {entity_id}: -> {state} ({temp}C)")

    def get_trackable_features(self):
        return [
            {"key": "temperature", "label_de": "Temperatur", "label_en": "Temperature"},
            {"key": "hvac_mode", "label_de": "Modus", "label_en": "Mode"},
            {"key": "humidity", "label_de": "Luftfeuchtigkeit", "label_en": "Humidity"},
        ]

    def get_current_status(self, room_id=None):
        entities = self.get_entities()
        heating = sum(1 for e in entities if e.get("attributes", {}).get("hvac_action") == "heating")
        return {"total": len(entities), "heating": heating, "idle": len(entities) - heating}

    def get_plugin_actions(self):
        return [
            {"key": "away_lower", "label_de": "Bei Abwesenheit absenken", "label_en": "Lower when away", "default": True},
            {"key": "night_lower", "label_de": "Nachtabsenkung", "label_en": "Night setback", "default": True},
            {"key": "preheat", "label_de": "Vorausschauend heizen", "label_en": "Predictive heating", "default": True},
        ]

    def evaluate(self, context):
        if not self.is_enabled():
            return []
        ctx = context or self.get_context()

        heating_mode = self.get_setting("heating_mode", "room_thermostat")
        if heating_mode == "heating_curve":
            return self._evaluate_curve(ctx)
        return self._evaluate_room_thermostat(ctx)

    def _evaluate_curve(self, ctx):
        """Heizkurven-Modus: Offset auf zentrales Entity anpassen."""
        actions = []
        curve_entity = self.get_setting("curve_entity", "")
        if not curve_entity:
            return actions

        # Aktuelles Entity finden
        entities = self.get_entities()
        target = None
        for e in entities:
            if e.get("entity_id") == curve_entity:
                target = e
                break
        if not target or target.get("state") in ("off", "unavailable"):
            return actions

        current_temp = target.get("attributes", {}).get("temperature")
        if not current_temp:
            return actions
        current_temp = float(current_temp)
        name = target.get("attributes", {}).get("friendly_name", curve_entity)

        # Nobody home -> away offset
        if self.get_setting("away_lower", True):
            if not ctx.get("anyone_home"):
                away_offset = float(self.get_setting("away_offset", -3))
                new_temp = current_temp + away_offset
                actions.append({
                    "entity_id": curve_entity, "service": "set_temperature",
                    "data": {"temperature": new_temp},
                    "reason_de": f"Niemand zuhause: {name} Offset {away_offset}°C",
                    "reason_en": f"Nobody home: {name} offset {away_offset}°C",
                })

        # Night mode -> night offset
        if self.get_setting("night_lower", True):
            phase = ctx.get("day_phase", "")
            if phase in ("Nacht", "Nachtruhe", "Night"):
                night_offset = float(self.get_setting("night_offset", -2))
                new_temp = current_temp + night_offset
                actions.append({
                    "entity_id": curve_entity, "service": "set_temperature",
                    "data": {"temperature": new_temp},
                    "reason_de": f"Nachtabsenkung: {name} Offset {night_offset}°C",
                    "reason_en": f"Night setback: {name} offset {night_offset}°C",
                })

        return self.execute_or_suggest(actions)

    def _evaluate_room_thermostat(self, ctx):
        """Raumthermostat-Modus: Einzelne Thermostate steuern (wie bisher)."""
        actions = []
        entities = self.get_entities()
        away_temp = float(self.get_setting("away_temp", 17))
        night_temp = float(self.get_setting("night_temp", 18))

        # Nobody home -> lower temperature
        if self.get_setting("away_lower", True):
            if not ctx.get("anyone_home"):
                for e in entities:
                    if e.get("state") not in ("off", "unavailable"):
                        current = e.get("attributes", {}).get("temperature")
                        if current and float(current) > away_temp:
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "set_temperature",
                                "data": {"temperature": away_temp},
                                "reason_de": f"Niemand zuhause: {name} auf {away_temp}C",
                                "reason_en": f"Nobody home: {name} to {away_temp}C",
                            })

        # Night mode -> lower temperature
        if self.get_setting("night_lower", True):
            phase = ctx.get("day_phase", "")
            if phase in ("Nacht", "Nachtruhe", "Night"):
                for e in entities:
                    if e.get("state") not in ("off", "unavailable"):
                        current = e.get("attributes", {}).get("temperature")
                        if current and float(current) > night_temp:
                            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
                            actions.append({
                                "entity_id": e["entity_id"], "service": "set_temperature",
                                "data": {"temperature": night_temp},
                                "reason_de": f"Nachtabsenkung: {name} auf {night_temp}C",
                                "reason_en": f"Night setback: {name} to {night_temp}C",
                            })

        return self.execute_or_suggest(actions)
