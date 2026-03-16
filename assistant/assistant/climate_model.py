"""
Climate Digital Twin - Einfaches thermisches Modell fuer Was-waere-wenn-Fragen.

Medium Effort Feature: Simuliert Temperaturverlauf basierend auf:
- Aktuellem Zustand (Innen-/Aussentemperatur, Heizung, Fenster)
- Einfacher thermischer Modellierung (Waermeverlust, Heizleistung)
- Ermoeglicht Vorhersagen: "Wenn du das Fenster schliesst, ist es in 20 Min warm"

Konfigurierbar in der Jarvis Assistant UI unter "Intelligenz".
"""

import logging
import math
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Typische thermische Eigenschaften (vereinfacht)
DEFAULT_ROOM_THERMAL = {
    "heat_loss_coefficient": 0.015,   # Waermeverlust pro Minute pro Grad Delta (gut isoliert)
    "heating_power_per_min": 0.08,    # Grad pro Minute bei voller Heizleistung
    "cooling_power_per_min": 0.1,     # Grad pro Minute bei voller Kuehlung
    "window_open_factor": 5.0,        # Multiplikator fuer Waermeverlust bei offenem Fenster
    "sun_gain_per_min": 0.02,         # Grad pro Minute bei direkter Sonneneinstrahlung
    "thermal_mass_factor": 1.0,       # Traegheit (1.0 = normal, >1 = schwerer Beton)
}


class RoomThermalState:
    """Thermischer Zustand eines Raumes."""

    def __init__(
        self,
        room: str,
        current_temp: float,
        target_temp: float = 21.0,
        outdoor_temp: float = 10.0,
        heating_active: bool = False,
        cooling_active: bool = False,
        windows_open: int = 0,
        sun_exposure: bool = False,
        humidity: float = 50.0,
    ):
        self.room = room
        self.current_temp = current_temp
        self.target_temp = target_temp
        self.outdoor_temp = outdoor_temp
        self.heating_active = heating_active
        self.cooling_active = cooling_active
        self.windows_open = windows_open
        self.sun_exposure = sun_exposure
        self.humidity = humidity

    def to_dict(self) -> dict:
        return {
            "room": self.room,
            "current_temp": round(self.current_temp, 1),
            "target_temp": self.target_temp,
            "outdoor_temp": self.outdoor_temp,
            "heating_active": self.heating_active,
            "cooling_active": self.cooling_active,
            "windows_open": self.windows_open,
            "sun_exposure": self.sun_exposure,
            "humidity": round(self.humidity, 1),
        }


class ClimateModel:
    """Einfaches thermisches Modell fuer Raumsimulation."""

    def __init__(self):
        cfg = yaml_config.get("climate_model", {})
        self.enabled = cfg.get("enabled", True)
        self.simulation_step_minutes = cfg.get("simulation_step_minutes", 1)
        self.max_simulation_minutes = cfg.get("max_simulation_minutes", 240)

        # Thermische Parameter (konfigurierbar pro Raum oder global)
        self._room_params = cfg.get("room_params", {})
        self._default_params = {
            **DEFAULT_ROOM_THERMAL,
            **cfg.get("default_params", {}),
        }

    def _get_params(self, room: str) -> dict:
        """Gibt thermische Parameter fuer einen Raum zurueck."""
        room_lower = room.lower()
        if room_lower in self._room_params:
            return {**self._default_params, **self._room_params[room_lower]}
        return dict(self._default_params)

    def simulate(
        self,
        state: RoomThermalState,
        duration_minutes: int = 60,
        changes: dict = None,
    ) -> dict:
        """Simuliert den Temperaturverlauf.

        Args:
            state: Aktueller thermischer Zustand
            duration_minutes: Simulationsdauer in Minuten
            changes: Aenderungen die simuliert werden sollen
                     z.B. {"close_windows": True, "set_target": 23, "heating_off": True}

        Returns:
            Dict mit:
                final_temp: Endtemperatur
                timeline: Liste von (minute, temp) Tupeln
                reaches_target: bool
                time_to_target_minutes: int oder None
                description: Natuerlichsprachliche Beschreibung
        """
        if not self.enabled:
            return {"error": "Climate Model deaktiviert"}

        if state.current_temp < 5 or state.current_temp > 35:
            logger.warning(
                "Temperatur ausserhalb des normalen Bereichs (5-35°C) in %s: %.1f°C",
                state.room, state.current_temp,
            )
        if state.target_temp < 5 or state.target_temp > 35:
            logger.warning(
                "Zieltemperatur ausserhalb des normalen Bereichs (5-35°C) in %s: %.1f°C",
                state.room, state.target_temp,
            )

        duration = min(duration_minutes, self.max_simulation_minutes)
        params = self._get_params(state.room)
        step = self.simulation_step_minutes

        # Aenderungen anwenden
        sim_state = RoomThermalState(
            room=state.room,
            current_temp=state.current_temp,
            target_temp=state.target_temp,
            outdoor_temp=state.outdoor_temp,
            heating_active=state.heating_active,
            cooling_active=state.cooling_active,
            windows_open=state.windows_open,
            sun_exposure=state.sun_exposure,
            humidity=state.humidity,
        )

        if changes:
            if "set_target" in changes:
                target = changes["set_target"]
                if not (5 <= target <= 35):
                    logger.warning("Temperature %.1f°C is outside recommended range (5-35°C)", target)
            if changes.get("close_windows"):
                sim_state.windows_open = 0
            if changes.get("open_windows"):
                sim_state.windows_open = max(1, sim_state.windows_open + changes.get("open_windows", 1))
            if "set_target" in changes:
                sim_state.target_temp = changes["set_target"]
            if changes.get("heating_off"):
                sim_state.heating_active = False
            if changes.get("heating_on"):
                sim_state.heating_active = True
            if changes.get("cooling_off"):
                sim_state.cooling_active = False
            if changes.get("cooling_on"):
                sim_state.cooling_active = True

        # Simulation
        temp = sim_state.current_temp
        timeline = [(0, round(temp, 1))]
        time_to_target = None
        reached_target = False

        heat_loss_coeff = params["heat_loss_coefficient"]
        heating_power = params["heating_power_per_min"]
        cooling_power = params["cooling_power_per_min"]
        window_factor = params["window_open_factor"]
        sun_gain = params["sun_gain_per_min"]
        thermal_mass = params["thermal_mass_factor"]

        for minute in range(step, duration + step, step):
            delta = sim_state.outdoor_temp - temp
            # Waermeverlust/-gewinn durch Temperatur-Differenz
            loss = delta * heat_loss_coeff / thermal_mass

            # Fenster verstaerken den Waermeaustausch
            if sim_state.windows_open > 0:
                loss *= 1 + (window_factor * sim_state.windows_open)

            # Heizung
            heating_gain = 0
            if sim_state.heating_active and temp < sim_state.target_temp:
                heating_gain = heating_power / thermal_mass

            # Kuehlung
            cooling_loss = 0
            if sim_state.cooling_active and temp > sim_state.target_temp:
                cooling_loss = cooling_power / thermal_mass

            # Sonneneinstrahlung
            solar = 0
            if sim_state.sun_exposure:
                solar = sun_gain / thermal_mass

            # Temperaturveraenderung pro Schritt
            temp += (loss + heating_gain - cooling_loss + solar) * step

            # Clamp auf realistische Werte
            temp = max(sim_state.outdoor_temp - 5, min(40, temp))

            if minute % 5 == 0 or minute == duration:
                timeline.append((minute, round(temp, 1)))

            # Zieltemperatur erreicht?
            if not reached_target:
                if sim_state.heating_active and temp >= sim_state.target_temp - 0.5:
                    reached_target = True
                    time_to_target = minute
                elif sim_state.cooling_active and temp <= sim_state.target_temp + 0.5:
                    reached_target = True
                    time_to_target = minute
                elif not sim_state.heating_active and not sim_state.cooling_active:
                    # Ohne aktive Regelung: Ziel = Gleichgewicht
                    if abs(temp - sim_state.target_temp) < 0.5:
                        reached_target = True
                        time_to_target = minute

        final_temp = round(temp, 1)
        temp_change = round(final_temp - state.current_temp, 1)

        # Beschreibung generieren
        description = self._generate_description(
            state, sim_state, changes or {},
            final_temp, temp_change, duration,
            reached_target, time_to_target,
        )

        return {
            "room": state.room,
            "initial_temp": state.current_temp,
            "final_temp": final_temp,
            "temp_change": temp_change,
            "timeline": timeline,
            "reaches_target": reached_target,
            "time_to_target_minutes": time_to_target,
            "duration_minutes": duration,
            "changes_applied": changes or {},
            "description": description,
        }

    def what_if(
        self,
        state: RoomThermalState,
        question: str,
    ) -> dict:
        """Beantwortet eine Was-waere-wenn-Frage.

        Args:
            state: Aktueller Zustand
            question: Frage (z.B. "Fenster schliessen", "Heizung auf 23")

        Returns:
            Simulations-Ergebnis
        """
        changes = self._parse_what_if(question)
        if not changes:
            return {"error": f"Konnte Frage nicht interpretieren: {question}"}

        return self.simulate(state, duration_minutes=120, changes=changes)

    def _parse_what_if(self, question: str) -> Optional[dict]:
        """Parst eine Was-waere-wenn-Frage in Aenderungen."""
        q = question.lower()
        changes = {}

        # Fenster
        if any(w in q for w in ["fenster schliess", "fenster zu", "fenster zumach"]):
            changes["close_windows"] = True
        elif any(w in q for w in ["fenster oeffn", "fenster auf", "fenster aufmach"]):
            changes["open_windows"] = 1

        # Heizung
        if any(w in q for w in ["heizung aus", "heizung ab", "heizung abstell"]):
            changes["heating_off"] = True
        elif any(w in q for w in ["heizung an", "heizung ein", "heizung anstell"]):
            changes["heating_on"] = True

        # Kuehlung
        if any(w in q for w in ["klima aus", "kuehlung aus", "ac aus"]):
            changes["cooling_off"] = True
        elif any(w in q for w in ["klima an", "kuehlung an", "ac an"]):
            changes["cooling_on"] = True

        # Zieltemperatur
        import re
        temp_match = re.search(r"(\d{1,2})[°\s]*(grad|c)?", q)
        if temp_match:
            target = int(temp_match.group(1))
            if 15 <= target <= 30:
                changes["set_target"] = target
                # Heizung/Kuehlung implizit aktivieren
                if target > 22:
                    changes["heating_on"] = True
                elif target < 18:
                    changes["cooling_on"] = True

        return changes if changes else None

    def estimate_comfort_time(
        self,
        state: RoomThermalState,
        comfort_temp: float = 21.0,
    ) -> dict:
        """Schaetzt wie lange es dauert bis die Komforttemperatur erreicht ist.

        Args:
            state: Aktueller Zustand
            comfort_temp: Ziel-Komforttemperatur

        Returns:
            Dict mit minutes, description
        """
        if abs(state.current_temp - comfort_temp) < 0.5:
            return {
                "minutes": 0,
                "description": f"{state.room}: Bereits bei Komforttemperatur ({state.current_temp}°C).",
            }

        sim_state = RoomThermalState(
            room=state.room,
            current_temp=state.current_temp,
            target_temp=comfort_temp,
            outdoor_temp=state.outdoor_temp,
            heating_active=state.current_temp < comfort_temp,
            cooling_active=state.current_temp > comfort_temp,
            windows_open=state.windows_open,
            sun_exposure=state.sun_exposure,
            humidity=state.humidity,
        )

        result = self.simulate(sim_state, duration_minutes=180)
        if result.get("reaches_target"):
            minutes = result["time_to_target_minutes"]
            return {
                "minutes": minutes,
                "description": f"{state.room}: Komforttemperatur ({comfort_temp}°C) wird in ca. {minutes} Minuten erreicht.",
            }
        else:
            return {
                "minutes": None,
                "description": f"{state.room}: Komforttemperatur ({comfort_temp}°C) wird voraussichtlich nicht innerhalb von 3 Stunden erreicht.",
            }

    def get_context_hint(self, rooms: list[RoomThermalState] = None) -> str:
        """Gibt einen Kontext-Hinweis fuer den LLM-Prompt zurueck."""
        if not self.enabled or not rooms:
            return ""

        hints = []
        for room_state in rooms[:3]:
            if room_state.windows_open > 0 and room_state.heating_active:
                hints.append(
                    f"WARNUNG: {room_state.room} — Fenster offen bei laufender Heizung. "
                    f"Waermeverlust ca. {self._estimate_loss_rate(room_state):.1f}°C/Stunde."
                )

            if abs(room_state.current_temp - room_state.target_temp) > 3:
                direction = "steigt" if room_state.current_temp < room_state.target_temp else "sinkt"
                hints.append(
                    f"{room_state.room}: Temperatur {direction} "
                    f"(aktuell: {room_state.current_temp}°C, Ziel: {room_state.target_temp}°C)."
                )

        return " ".join(hints)

    def simulate_scenario(
        self,
        scenario: str,
        duration_hours: int = 24,
        params: dict = None,
    ) -> dict:
        """Simuliert ein vordefiniertes Szenario ueber mehrere Stunden.

        Unterstuetzte Szenarien:
        - "heating_off": Heizung komplett aus, natuerlicher Temperaturverlauf
        - "windows_open": Fenster geoeffnet, verstaerkter Waermeverlust
        - "vacation_3days": 72h reduzierte Heizung (16°C Absenkung)
        - "all_covers_closed": Alle Rolladen zu, reduzierter Waermeverlust

        Args:
            scenario: Name des Szenarios
            duration_hours: Simulationsdauer in Stunden (default 24)
            params: Optionale Parameter (room, current_temp, outdoor_temp, target_temp)

        Returns:
            Dict mit scenario, timeline, min_temp, time_to_critical, recommendation
        """
        if not self.enabled:
            return {"error": "Climate Model deaktiviert"}

        p = params or {}
        room = p.get("room", "wohnzimmer")
        current_temp = p.get("current_temp", 21.5)
        outdoor_temp = p.get("outdoor_temp", 5.0)
        target_temp = p.get("target_temp", 21.0)
        critical_temp = p.get("critical_temp", 17.0)

        # Szenario-spezifische Anpassungen
        if scenario == "vacation_3days":
            duration_hours = 72
            target_temp = 16.0

        thermal = self._get_params(room)
        step_minutes = 10  # Groessere Schritte fuer Langzeit-Simulation
        total_minutes = duration_hours * 60

        temp = current_temp
        timeline = [{"hour": 0, "temp": round(temp, 1)}]
        min_temp = temp
        time_to_critical = None

        heat_loss_coeff = thermal["heat_loss_coefficient"]
        heating_power = thermal["heating_power_per_min"]
        window_factor = thermal["window_open_factor"]
        thermal_mass = thermal["thermal_mass_factor"]

        # Szenario-Flags
        heating_active = scenario not in ("heating_off",)
        windows_open = 1 if scenario == "windows_open" else 0
        # Geschlossene Rolladen reduzieren Waermeverlust um ca. 30%
        cover_factor = 0.7 if scenario == "all_covers_closed" else 1.0

        for minute in range(step_minutes, total_minutes + step_minutes, step_minutes):
            delta = outdoor_temp - temp
            # Waermeverlust durch Temperaturdifferenz
            loss = delta * heat_loss_coeff * cover_factor / thermal_mass

            # Fenster verstaerken Waermeaustausch
            if windows_open > 0:
                loss *= 1 + (window_factor * windows_open)

            # Heizung: nur aktiv wenn unter Zieltemperatur
            heating_gain = 0
            if heating_active and temp < target_temp:
                heating_gain = heating_power / thermal_mass

            temp += (loss + heating_gain) * step_minutes
            temp = max(outdoor_temp - 5, min(40, temp))

            # Timeline: jede volle Stunde
            if minute % 60 == 0:
                hour = minute // 60
                timeline.append({"hour": hour, "temp": round(temp, 1)})

            if temp < min_temp:
                min_temp = temp

            # Kritische Temperatur erreicht?
            if time_to_critical is None and temp < critical_temp:
                time_to_critical = minute // 60

        min_temp = round(min_temp, 1)

        # Empfehlung generieren
        recommendation = self._generate_scenario_recommendation(
            scenario, min_temp, time_to_critical, critical_temp, outdoor_temp,
        )

        return {
            "scenario": scenario,
            "timeline": timeline,
            "min_temp": min_temp,
            "time_to_critical": time_to_critical,
            "recommendation": recommendation,
        }

    def _generate_scenario_recommendation(
        self,
        scenario: str,
        min_temp: float,
        time_to_critical: Optional[int],
        critical_temp: float,
        outdoor_temp: float,
    ) -> str:
        """Generiert eine Empfehlung basierend auf Simulationsergebnis."""
        if scenario == "heating_off":
            if time_to_critical is not None:
                return (
                    f"Nach {time_to_critical}h faellt die Temperatur unter "
                    f"{critical_temp}°C — nicht empfohlen bei aktueller "
                    f"Aussentemperatur"
                )
            return (
                f"Temperatur bleibt ueber {critical_temp}°C. "
                f"Heizung kann voruebergehend ausgeschaltet werden."
            )

        elif scenario == "windows_open":
            if time_to_critical is not None:
                return (
                    f"Bei geoeffneten Fenstern faellt die Temperatur nach "
                    f"{time_to_critical}h unter {critical_temp}°C. "
                    f"Stosslüften (max. 15 Min) empfohlen statt Dauerlüften."
                )
            return "Lueften moeglich ohne kritischen Temperaturabfall."

        elif scenario == "vacation_3days":
            if min_temp < 10:
                return (
                    f"WARNUNG: Temperatur sinkt auf {min_temp}°C — "
                    f"Frostschutz-Absenkung auf 16°C reicht bei {outdoor_temp}°C "
                    f"Aussentemperatur nicht aus. Hoehere Absenktemperatur empfohlen."
                )
            return (
                f"Absenkung auf 16°C ist sicher. Minimum: {min_temp}°C. "
                f"Energieersparnis wird erwartet."
            )

        elif scenario == "all_covers_closed":
            return (
                f"Geschlossene Rolladen reduzieren den Waermeverlust um ca. 30%. "
                f"Minimum-Temperatur: {min_temp}°C."
            )

        return ""

    def estimate_energy_cost(
        self,
        scenario: str,
        duration_hours: int,
        price_per_kwh: float = 0.30,
        params: dict = None,
    ) -> dict:
        """Schaetzt Energieverbrauch und Kosten fuer ein Szenario.

        Basiert auf vereinfachter Berechnung:
        - Heizleistung ca. 2-5 kW je nach Raumdelta
        - Vergleich mit Normalbetrieb (21°C Zieltemperatur)

        Args:
            scenario: Name des Szenarios
            duration_hours: Dauer in Stunden
            price_per_kwh: Strompreis pro kWh (Default: 0.30 EUR)
            params: Optionale Parameter (room, current_temp, outdoor_temp)

        Returns:
            Dict mit kwh_total, cost_eur, vs_normal_pct
        """
        if not self.enabled:
            return {"error": "Climate Model deaktiviert"}

        p = params or {}
        room = p.get("room", "wohnzimmer")
        outdoor_temp = p.get("outdoor_temp", 5.0)
        thermal = self._get_params(room)

        # Typische Heizleistung in kW (vereinfacht aus thermischen Parametern)
        # heating_power_per_min in °C/min → umgerechnet auf kW
        base_heating_kw = 3.0  # Typische Heizleistung fuer einen Raum

        # Normalbetrieb: Heizung haelt 21°C, Anteil der Zeit aktiv
        normal_target = 21.0
        normal_delta = normal_target - outdoor_temp
        # Heizanteil: wie viel % der Zeit muss geheizt werden
        normal_duty = min(1.0, max(0.0, normal_delta * thermal["heat_loss_coefficient"] /
                                   thermal["heating_power_per_min"])) if normal_delta > 0 else 0.0
        normal_kwh = base_heating_kw * normal_duty * duration_hours

        # Szenario-Verbrauch berechnen
        if scenario == "heating_off":
            scenario_kwh = 0.0
        elif scenario == "vacation_3days":
            vacation_target = 16.0
            vacation_delta = vacation_target - outdoor_temp
            vacation_duty = min(1.0, max(0.0, vacation_delta * thermal["heat_loss_coefficient"] /
                                         thermal["heating_power_per_min"])) if vacation_delta > 0 else 0.0
            scenario_kwh = base_heating_kw * vacation_duty * duration_hours
        elif scenario == "windows_open":
            # Fenster offen: mehr Waermeverlust, Heizung muss mehr arbeiten
            window_loss_factor = 1 + thermal["window_open_factor"]
            window_duty = min(1.0, normal_duty * window_loss_factor)
            scenario_kwh = base_heating_kw * window_duty * duration_hours
        elif scenario == "all_covers_closed":
            # Rolladen reduzieren Waermeverlust um ~30%
            cover_duty = min(1.0, max(0.0, normal_duty * 0.7))
            scenario_kwh = base_heating_kw * cover_duty * duration_hours
        else:
            scenario_kwh = normal_kwh

        scenario_kwh = round(scenario_kwh, 1)
        cost_eur = round(scenario_kwh * price_per_kwh, 2)
        vs_normal_pct = round(((scenario_kwh - normal_kwh) / normal_kwh * 100)
                              if normal_kwh > 0 else 0)

        return {
            "kwh_total": scenario_kwh,
            "cost_eur": cost_eur,
            "vs_normal_pct": vs_normal_pct,
        }

    def _estimate_loss_rate(self, state: RoomThermalState) -> float:
        """Schaetzt den Waermeverlust pro Stunde."""
        params = self._get_params(state.room)
        delta = state.outdoor_temp - state.current_temp
        loss_per_min = abs(delta) * params["heat_loss_coefficient"]
        if state.windows_open > 0:
            loss_per_min *= 1 + (params["window_open_factor"] * state.windows_open)
        return loss_per_min * 60

    def _generate_description(
        self,
        original: RoomThermalState,
        simulated: RoomThermalState,
        changes: dict,
        final_temp: float,
        temp_change: float,
        duration: int,
        reached_target: bool,
        time_to_target: Optional[int],
    ) -> str:
        """Generiert eine natuerlichsprachliche Beschreibung."""
        parts = []

        # Was wurde geaendert
        change_parts = []
        if changes.get("close_windows"):
            change_parts.append("Fenster geschlossen")
        if changes.get("open_windows"):
            change_parts.append("Fenster geöffnet")
        if changes.get("heating_on"):
            change_parts.append("Heizung eingeschaltet")
        if changes.get("heating_off"):
            change_parts.append("Heizung ausgeschaltet")
        if changes.get("cooling_on"):
            change_parts.append("Kuehlung eingeschaltet")
        if changes.get("cooling_off"):
            change_parts.append("Kuehlung ausgeschaltet")
        if "set_target" in changes:
            change_parts.append(f"Zieltemperatur auf {changes['set_target']}°C")

        if change_parts:
            parts.append(f"Simulation fuer {original.room}: {', '.join(change_parts)}.")

        # Temperaturverlauf
        if abs(temp_change) < 0.5:
            parts.append(f"Die Temperatur bleibt in {duration} Minuten bei ca. {final_temp}°C.")
        elif temp_change > 0:
            parts.append(f"Die Temperatur steigt in {duration} Minuten von {original.current_temp}°C auf {final_temp}°C (+{temp_change}°C).")
        else:
            parts.append(f"Die Temperatur sinkt in {duration} Minuten von {original.current_temp}°C auf {final_temp}°C ({temp_change}°C).")

        # Ziel erreicht?
        if reached_target and time_to_target:
            parts.append(f"Zieltemperatur ({simulated.target_temp}°C) wird in ca. {time_to_target} Minuten erreicht.")
        elif not reached_target and (simulated.heating_active or simulated.cooling_active):
            parts.append(f"Zieltemperatur ({simulated.target_temp}°C) wird in {duration} Minuten voraussichtlich nicht erreicht.")

        return " ".join(parts)
