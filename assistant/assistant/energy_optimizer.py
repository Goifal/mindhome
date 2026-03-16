"""
Energy Optimizer - Intelligentes Energiemanagement.

Features:
- Guenstig-Strom-Aktionen: Benachrichtigung wenn Strom billig
- Solar-Optimierung: "Solar-Ertrag hoch -> Waschmaschine jetzt starten?"
- Verbrauchs-Analyse: Wochen-Vergleich
- Anomalie-Erkennung: Ungewoehnlich hoher Verbrauch
- Proaktive Tipps bei Preis-Schwankungen

Nutzt bestehende HA energy/solar/price Sensoren.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Redis Keys
KEY_DAILY_ENERGY = "mha:energy:daily:"
KEY_LAST_PRICE_ALERT = "mha:energy:last_price_alert"
KEY_PRICE_HISTORY = "mha:energy:price_history"

# Standard flexible Lasten — konfigurierbar ueber config.yaml (energy.flexible_loads)
DEFAULT_FLEXIBLE_LOADS: dict[str, dict] = {
    "waschmaschine": {"kwh": 1.5, "duration_h": 2.0, "entities": ["switch.waschmaschine"]},
    "trockner": {"kwh": 3.0, "duration_h": 2.5, "entities": ["switch.trockner"]},
    "spuelmaschine": {"kwh": 1.2, "duration_h": 2.0, "entities": ["switch.spuelmaschine"]},
    "e_auto": {"kwh": 11.0, "duration_h": 3.0, "entities": ["switch.wallbox"]},
}


class EnergyOptimizer:
    """Intelligentes Energiemanagement."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None

        # Konfiguration
        energy_cfg = yaml_config.get("energy", {})
        self.enabled = energy_cfg.get("enabled", True)

        # Entity-IDs (konfigurierbar)
        entities = energy_cfg.get("entities", {})
        self.price_sensor = entities.get("electricity_price", "")
        self.consumption_sensor = entities.get("total_consumption", "")
        self.solar_sensor = entities.get("solar_production", "")
        self.grid_export_sensor = entities.get("grid_export", "")

        # Schwellwerte
        thresholds = energy_cfg.get("thresholds", {})
        self.price_low = thresholds.get("price_low_cent", 15)  # Cent/kWh
        self.price_high = thresholds.get("price_high_cent", 35)
        self.solar_high_watts = thresholds.get("solar_high_watts", 2000)
        self.anomaly_percent = thresholds.get("anomaly_increase_percent", 30)

        # Flexible Lasten fuer Lastverschiebung (konfigurierbar)
        self.flexible_loads: dict[str, dict] = {
            **DEFAULT_FLEXIBLE_LOADS,
            **energy_cfg.get("flexible_loads", {}),
        }

        # F-056: Essentielle Geraete die nie abgeschaltet werden duerfen
        self.essential_entities = set(energy_cfg.get("essential_entities", [
            "switch.kuehlschrank", "switch.gefrierschrank", "switch.tiefkuehler",
            "switch.server", "switch.nas", "switch.aquarium",
        ]))

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert den EnergyOptimizer."""
        self.redis = redis_client
        logger.info("EnergyOptimizer initialisiert (enabled: %s)", self.enabled)

    async def get_energy_report(self) -> dict:
        """Erstellt einen Energie-Bericht.

        Returns:
            Dict mit success und message (formatierter Bericht)
        """
        if not self.enabled:
            return {"success": False, "message": "Energiemanagement ist deaktiviert."}

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Keine Verbindung zu Home Assistant."}

        parts = ["Energie-Bericht:"]

        # Aktueller Strompreis (mit Einheiten-Erkennung)
        price_raw = self._find_sensor_value(states, self.price_sensor, ["price", "strom", "electricity"])
        price = None
        if price_raw is not None:
            # Einheit des Sensors pruefen und nach ct/kWh normalisieren
            price_unit = self._find_sensor_unit(states, self.price_sensor, ["price", "strom", "electricity"])
            price_unit_lower = (price_unit or "").lower().replace(" ", "")
            if "eur/mwh" in price_unit_lower or "€/mwh" in price_unit_lower:
                price = price_raw / 10.0  # EUR/MWh -> ct/kWh
            elif "eur/kwh" in price_unit_lower or "€/kwh" in price_unit_lower:
                price = price_raw * 100.0  # EUR/kWh -> ct/kWh
            elif price_raw > 100:
                # Heuristik: Wert > 100 ist wahrscheinlich EUR/MWh
                price = price_raw / 10.0
            elif price_raw < 1:
                # Heuristik: Wert < 1 ist wahrscheinlich EUR/kWh
                price = price_raw * 100.0
            else:
                price = price_raw  # Bereits ct/kWh
            price_status = "guenstig" if price < self.price_low else "teuer" if price > self.price_high else "normal"
            parts.append(f"  Strompreis: {price:.1f} ct/kWh ({price_status})")

        # Solar-Produktion
        solar = self._find_sensor_value(states, self.solar_sensor, ["solar", "pv", "photovoltaik"])
        if solar is not None:
            parts.append(f"  Solar-Ertrag: {solar:.0f} W")

        # Aktueller Verbrauch
        consumption = self._find_sensor_value(states, self.consumption_sensor, ["consumption", "verbrauch", "power"])
        if consumption is not None:
            parts.append(f"  Aktueller Verbrauch: {consumption:.0f} W")

        # Netz-Export
        export = self._find_sensor_value(states, self.grid_export_sensor, ["export", "einspeisung"])
        if export is not None and export > 0:
            parts.append(f"  Netz-Einspeisung: {export:.0f} W")

        # Empfehlungen
        recommendations = await self._get_recommendations(price, solar, consumption)
        if recommendations:
            parts.append("\nEmpfehlungen:")
            for rec in recommendations:
                parts.append(f"  - {rec}")

        if len(parts) == 1:
            return {"success": True, "message": "Keine Energie-Sensoren konfiguriert. Bitte energy-Entities in der Config hinterlegen."}

        return {"success": True, "message": "\n".join(parts)}

    @property
    def has_configured_entities(self) -> bool:
        """True wenn mindestens ein Energie-Entity explizit konfiguriert ist."""
        return bool(self.price_sensor or self.consumption_sensor
                     or self.solar_sensor or self.grid_export_sensor)

    async def check_energy_events(self) -> list[dict]:
        """Periodischer Check fuer proaktive Energie-Meldungen.

        Wird von proactive.py aufgerufen.
        Proaktive Alerts NUR wenn Entities explizit konfiguriert sind.
        Auto-Discovery (Keyword-Suche) bleibt fuer manuelle Abfragen verfuegbar.

        Returns:
            Liste von Meldungen (kann leer sein)
        """
        if not self.enabled:
            return []

        # Keine proaktiven Alerts ohne explizite Konfiguration
        if not self.has_configured_entities:
            return []

        alerts = []
        states = await self.ha.get_states()
        if not states:
            return []

        # 1. Guenstiger Strom — deaktiviert (Owner-Feedback: uninteressant)
        price = self._find_sensor_value(states, self.price_sensor, ["price", "strom", "electricity"])

        # 2. Solar-Ueberschuss + Cloud-Forecast
        solar = self._find_sensor_value(states, self.solar_sensor, ["solar", "pv"])
        export = self._find_sensor_value(states, self.grid_export_sensor, ["export", "einspeisung"])
        if solar is not None and solar > self.solar_high_watts and export is not None and export > 500:
            # Cloud-Forecast: Bewoelkung in den naechsten Stunden pruefen
            clouds_coming = self._check_cloud_forecast(states)
            if clouds_coming and not await self._was_recently_alerted("solar_cloud_shift"):
                await self._mark_alerted("solar_cloud_shift", cooldown_minutes=120)
                alerts.append({
                    "type": "solar_cloud_shift",
                    "message": f"Solar-Ertrag aktuell hoch ({solar:.0f} W), aber Bewoelkung "
                               f"vorhergesagt. Energieintensive Geraete JETZT starten "
                               f"(Waschmaschine, Trockner, Spuelmaschine).",
                    "urgency": "low",
                })
            elif not await self._was_recently_alerted("solar_high"):
                await self._mark_alerted("solar_high", cooldown_minutes=180)
                alerts.append({
                    "type": "solar_surplus",
                    "message": f"Solar-Ertrag ist hoch ({solar:.0f} W) mit {export:.0f} W Einspeisung. "
                               f"Eigenverbrauch optimieren, z.B. Waschmaschine starten.",
                    "urgency": "low",
                })

        # 3. Hoher Strompreis
        if price is not None and price > self.price_high:
            if not await self._was_recently_alerted("high_price"):
                await self._mark_alerted("high_price", cooldown_minutes=240)
                alerts.append({
                    "type": "energy_price_high",
                    "message": f"Strompreis ist hoch ({price:.1f} ct/kWh). "
                               f"Grosse Verbraucher besser spaeter einschalten.",
                    "urgency": "low",
                })

        # 4. Anomalie-Erkennung: Ungewoehnlich hoher Verbrauch
        consumption = self._find_sensor_value(states, self.consumption_sensor,
                                              ["consumption", "verbrauch", "power"])
        anomaly_msg = await self._check_anomaly(consumption)
        if anomaly_msg:
            if not await self._was_recently_alerted("anomaly"):
                await self._mark_alerted("anomaly", cooldown_minutes=360)
                alerts.append({
                    "type": "energy_anomaly",
                    "message": anomaly_msg,
                    "urgency": "medium",
                })

        return alerts

    async def _get_recommendations(self, price, solar, consumption) -> list[str]:
        """Generiert Empfehlungen basierend auf aktuellen Werten."""
        recs = []

        if price is not None:
            if price < self.price_low:
                recs.append("Strom ist guenstig — guter Zeitpunkt fuer energieintensive Geraete.")
            elif price > self.price_high:
                recs.append("Strom ist teuer — grosse Verbraucher besser verschieben.")

        if solar is not None and solar > self.solar_high_watts:
            recs.append(f"Hoher Solar-Ertrag ({solar:.0f} W) — Eigenverbrauch maximieren.")

        # Anomalie-Hinweis
        anomaly = await self._check_anomaly(consumption)
        if anomaly:
            recs.append(anomaly)

        # Wochen-Vergleich
        comparison = await self._get_weekly_comparison()
        if comparison:
            recs.append(comparison)

        # Device-Dependency-Kontext: Konflikte die Energieverbrauch beeinflussen
        try:
            from .state_change_log import StateChangeLog
            states = await self.ha.get_states() if self.ha else []
            if states:
                state_dict = {
                    s["entity_id"]: s.get("state", "")
                    for s in states if "entity_id" in s
                }
                scl = StateChangeLog.__new__(StateChangeLog)
                conflicts = scl.detect_conflicts(state_dict)
                energy_relevant = [
                    c for c in conflicts
                    if c.get("affected_active") and any(
                        kw in c.get("effect", "").lower()
                        for kw in ["heiz", "kuehl", "energie", "strom", "ineffizient"]
                    )
                ]
                for c in energy_relevant[:2]:
                    room = f" ({c.get('trigger_room', '')})" if c.get("trigger_room") else ""
                    recs.append(f"Energiehinweis: {c['hint']}{room}")
        except Exception as _dep_err:
            logger.debug("Energy Dependency-Kontext: %s", _dep_err)

        return recs

    # ------------------------------------------------------------------
    # Lastverschiebung / Energie-Arbitrage
    # ------------------------------------------------------------------

    def calculate_load_shift_savings(self, current_price: float, avg_price: float,
                                     estimated_kwh: float) -> float:
        """Berechnet Ersparnis in Cent wenn eine Last in guenstigere Zeit verschoben wird.

        Args:
            current_price: Aktueller Strompreis in ct/kWh
            avg_price: Durchschnittspreis in ct/kWh (Referenz)
            estimated_kwh: Typischer Verbrauch des Geraets in kWh

        Returns:
            Ersparnis in Cent (positiv = guenstiger als Durchschnitt)
        """
        price_diff = avg_price - current_price  # positiv = jetzt guenstiger
        return round(price_diff * estimated_kwh, 1)

    async def get_optimal_schedule(self, ha_client: HomeAssistantClient) -> list[dict]:
        """Analysiert aktuelle Strompreise und schlaegt guenstige Zeitfenster fuer flexible Lasten vor.

        Nutzt bestehende Preis-Sensoren und identifiziert Fenster die unter dem
        Durchschnittspreis liegen. Gibt Empfehlungen fuer jedes flexible Geraet zurueck.

        Returns:
            Liste von Empfehlungen mit device, suggestion, savings_estimate_ct, optimal_window
        """
        if not self.enabled:
            return []

        states = await ha_client.get_states()
        if not states:
            return []

        # Aktuellen Preis ermitteln (normalisiert auf ct/kWh)
        price_raw = self._find_sensor_value(states, self.price_sensor, ["price", "strom", "electricity"])
        if price_raw is None:
            return []

        # Einheit normalisieren (gleiche Logik wie get_energy_report)
        price_unit = self._find_sensor_unit(states, self.price_sensor, ["price", "strom", "electricity"])
        price_unit_lower = (price_unit or "").lower().replace(" ", "")
        if "eur/mwh" in price_unit_lower or "€/mwh" in price_unit_lower:
            current_price = price_raw / 10.0
        elif "eur/kwh" in price_unit_lower or "€/kwh" in price_unit_lower:
            current_price = price_raw * 100.0
        elif price_raw > 100:
            current_price = price_raw / 10.0
        elif price_raw < 1:
            current_price = price_raw * 100.0
        else:
            current_price = price_raw

        # Durchschnittspreis aus Preishistorie oder Schwellwert-Mittel
        avg_price = await self._get_avg_price(current_price)

        schedule: list[dict] = []
        now = datetime.now()

        for device_key, load_info in self.flexible_loads.items():
            estimated_kwh = load_info["kwh"]
            duration_h = load_info["duration_h"]
            savings_ct = self.calculate_load_shift_savings(current_price, avg_price, estimated_kwh)

            # Geraetename fuer Anzeige (Grossbuchstabe)
            display_name = device_key.replace("_", "-").capitalize()
            if device_key == "e_auto":
                display_name = "E-Auto"

            if current_price < avg_price:
                # Jetzt ist guenstig — sofort starten empfehlen
                discount_pct = ((avg_price - current_price) / avg_price) * 100 if avg_price > 0 else 0
                end_time = now + timedelta(hours=duration_h)
                window = f"{now.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
                schedule.append({
                    "device": display_name,
                    "suggestion": f"Jetzt starten — Strom ist {discount_pct:.0f}% guenstiger als Durchschnitt",
                    "savings_estimate_ct": abs(savings_ct),
                    "optimal_window": window,
                })
            else:
                # Jetzt teuer — guenstigeres Fenster vorschlagen
                # Heuristik: Nachtstunden (1:00-5:00) und Mittagsstunden (12:00-14:00) sind oft guenstig
                cheap_windows = self._estimate_cheap_windows(now, duration_h)
                if cheap_windows:
                    window = cheap_windows[0]
                    schedule.append({
                        "device": display_name,
                        "suggestion": f"Besser spaeter starten — aktuell {current_price:.1f} ct/kWh "
                                      f"(Durchschnitt {avg_price:.1f} ct/kWh)",
                        "savings_estimate_ct": abs(savings_ct),
                        "optimal_window": window,
                    })

        return schedule

    async def get_solar_surplus_actions(self, ha_client: HomeAssistantClient) -> list[dict]:
        """Empfehlungen bei Solar-Ueberschuss: Welche Geraete jetzt gestartet werden koennten.

        Priorisiert nach Verbrauch — groesste Verbraucher zuerst, damit der
        Ueberschuss maximal genutzt wird.

        Returns:
            Liste von Aktions-Empfehlungen mit device, message, power_kw
        """
        if not self.enabled:
            return []

        states = await ha_client.get_states()
        if not states:
            return []

        solar = self._find_sensor_value(states, self.solar_sensor, ["solar", "pv", "photovoltaik"])
        consumption = self._find_sensor_value(states, self.consumption_sensor,
                                              ["consumption", "verbrauch", "power"])

        if solar is None or consumption is None:
            return []

        # Ueberschuss berechnen (in kW)
        surplus_w = solar - consumption
        if surplus_w <= 0:
            return []

        surplus_kw = surplus_w / 1000.0

        actions: list[dict] = []

        # Nach Verbrauch sortieren (groesste zuerst fuer maximale Eigenverbrauchsquote)
        sorted_loads = sorted(self.flexible_loads.items(),
                              key=lambda x: x[1]["kwh"] / max(x[1]["duration_h"], 0.1),
                              reverse=True)

        remaining_kw = surplus_kw
        for device_key, load_info in sorted_loads:
            # Durchschnittliche Leistung des Geraets in kW
            avg_power_kw = load_info["kwh"] / max(load_info["duration_h"], 0.1)

            display_name = device_key.replace("_", "-").capitalize()
            if device_key == "e_auto":
                display_name = "E-Auto"

            if remaining_kw >= avg_power_kw * 0.5:
                # Genuegend Ueberschuss fuer dieses Geraet (mind. 50% der Leistung)
                actions.append({
                    "device": display_name,
                    "message": f"Solarueberschuss von {surplus_kw:.1f} kW — "
                               f"gute Zeit fuer {display_name}"
                               f" ({avg_power_kw:.1f} kW Verbrauch)",
                    "power_kw": round(avg_power_kw, 1),
                })
                remaining_kw -= avg_power_kw

            if remaining_kw <= 0:
                break

        return actions

    # ------------------------------------------------------------------
    # Hilfsfunktionen fuer Lastverschiebung
    # ------------------------------------------------------------------

    async def _get_avg_price(self, fallback_price: float) -> float:
        """Ermittelt den Durchschnittspreis aus Redis-Historie oder Schwellwerten.

        Wenn keine Historie verfuegbar, wird der Mittelwert von price_low und price_high
        als Annaeherung verwendet.
        """
        if self.redis:
            try:
                raw = await self.redis.get(KEY_PRICE_HISTORY)
                if raw:
                    history = json.loads(raw)
                    if isinstance(history, list) and history:
                        return sum(history) / len(history)
            except Exception as e:
                logger.debug("Preishistorie nicht verfuegbar: %s", e)

        # Fallback: Mittelwert der konfigurierten Schwellwerte
        return (self.price_low + self.price_high) / 2.0

    @staticmethod
    def _estimate_cheap_windows(now: datetime, duration_h: float) -> list[str]:
        """Schaetzt guenstige Zeitfenster basierend auf typischen Preis-Mustern.

        Typische guenstige Zeiten (dynamische Tarife):
        - Nachts: 01:00-05:00 (niedrige Nachfrage)
        - Mittags: 12:00-14:00 (hohe Solar-Einspeisung drueckt Preise)

        Returns:
            Liste von Zeitfenster-Strings (z.B. ["14:00-16:00"])
        """
        windows = []
        # Guenstige Slots (Stunde, Prioritaet)
        cheap_slots = [(13, 1), (12, 2), (14, 3), (2, 4), (3, 5), (1, 6)]

        for start_hour, _prio in cheap_slots:
            slot_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            # Wenn Slot heute schon vorbei, naechsten Tag nehmen
            if slot_start <= now:
                slot_start += timedelta(days=1)
            slot_end = slot_start + timedelta(hours=duration_h)
            windows.append(f"{slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}")

        return windows

    # ------------------------------------------------------------------
    # Kostentracking
    # ------------------------------------------------------------------

    async def track_daily_cost(self):
        """Speichert die taeglichen Energiekosten in Redis.

        Wird taeglich um Mitternacht von brain.py aufgerufen.
        """
        if not self.redis or not self.enabled or not self.has_configured_entities:
            return

        states = await self.ha.get_states()
        if not states:
            return

        consumption = self._find_sensor_value(states, self.consumption_sensor,
                                              ["consumption", "verbrauch", "energy_total"])
        price = self._find_sensor_value(states, self.price_sensor,
                                        ["price", "strom", "electricity"])

        if consumption is None:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        key = f"{KEY_DAILY_ENERGY}{today}"

        try:
            # Tagesverbrauch (kWh) und Durchschnittspreis speichern
            data = json.dumps({
                "consumption_wh": consumption,
                "avg_price_cent": price or 0,
                "timestamp": datetime.now().isoformat(),
            })
            await self.redis.setex(key, 90 * 86400, data)  # 90 Tage aufheben
            logger.info("Tagesverbrauch gespeichert: %.1f Wh, %.1f ct/kWh", consumption, price or 0)
        except Exception as e:
            logger.debug("Tagesverbrauch nicht gespeichert: %s", e)

    # ------------------------------------------------------------------
    # Anomalie-Erkennung
    # ------------------------------------------------------------------

    async def _check_anomaly(self, current_consumption: Optional[float]) -> Optional[str]:
        """Vergleicht aktuellen Verbrauch mit 7-Tage-Durchschnitt."""
        if not self.redis or current_consumption is None:
            return None

        try:
            # Letzte 7 Tage per mget laden
            days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
            keys = [f"{KEY_DAILY_ENERGY}{day}" for day in days]
            raw_results = await self.redis.mget(keys)
            values = []
            for raw in raw_results:
                if raw:
                    try:
                        data = json.loads(raw)
                        val = data.get("consumption_wh", 0)
                        if val > 0:
                            values.append(val)
                    except (json.JSONDecodeError, TypeError):
                        continue

            if len(values) < 3:
                return None  # Zu wenig Daten

            avg = sum(values) / len(values)
            if avg <= 0:
                return None

            increase_pct = ((current_consumption - avg) / avg) * 100

            if increase_pct > self.anomaly_percent:
                return (f"Verbrauch liegt {increase_pct:.0f}% ueber dem 7-Tage-Durchschnitt "
                        f"({current_consumption:.0f} vs. {avg:.0f} Durchschnitt). "
                        f"Ungewoehnlicher Verbraucher aktiv?")
        except Exception as e:
            logger.debug("Anomalie-Check Fehler: %s", e)

        return None

    # ------------------------------------------------------------------
    # Wochen-Vergleich
    # ------------------------------------------------------------------

    async def _get_weekly_comparison(self) -> Optional[str]:
        """Vergleicht diese Woche mit der letzten Woche."""
        if not self.redis:
            return None

        try:
            this_week = []
            last_week = []
            now = datetime.now()

            # Alle 14 Tage per mget laden (7 diese Woche + 7 letzte Woche)
            all_keys = []
            for i in range(7):
                all_keys.append(f"{KEY_DAILY_ENERGY}{(now - timedelta(days=i)).strftime('%Y-%m-%d')}")
                all_keys.append(f"{KEY_DAILY_ENERGY}{(now - timedelta(days=i + 7)).strftime('%Y-%m-%d')}")
            raw_results = await self.redis.mget(all_keys)

            for idx in range(7):
                raw = raw_results[idx * 2]
                if raw:
                    try:
                        data = json.loads(raw)
                        val = data.get("consumption_wh", 0)
                        if val > 0:
                            this_week.append(val)
                    except (json.JSONDecodeError, TypeError):
                        pass

                raw_lw = raw_results[idx * 2 + 1]
                if raw_lw:
                    try:
                        data_lw = json.loads(raw_lw)
                        val_lw = data_lw.get("consumption_wh", 0)
                        if val_lw > 0:
                            last_week.append(val_lw)
                    except (json.JSONDecodeError, TypeError):
                        pass

            if len(this_week) < 3 or len(last_week) < 3:
                return None

            avg_this = sum(this_week) / len(this_week)
            avg_last = sum(last_week) / len(last_week)

            if avg_last <= 0:
                return None

            diff_pct = ((avg_this - avg_last) / avg_last) * 100

            if abs(diff_pct) < 5:
                return None  # Kaum Unterschied

            direction = "mehr" if diff_pct > 0 else "weniger"
            return f"Diese Woche {abs(diff_pct):.0f}% {direction} Verbrauch als letzte Woche."

        except Exception as e:
            logger.debug("Wochen-Vergleich Fehler: %s", e)

        return None

    @staticmethod
    def _check_cloud_forecast(states: list[dict]) -> bool:
        """Prueft ob in den naechsten 3 Stunden Bewoelkung/Regen kommt.

        Nutzt weather.* forecast Daten. True = Solar wird bald sinken.
        """
        cloudy_conditions = {"cloudy", "rainy", "pouring", "fog", "lightning-rainy"}
        for s in states:
            if not s.get("entity_id", "").startswith("weather."):
                continue
            forecast = s.get("attributes", {}).get("forecast", [])
            if not forecast:
                continue
            # Naechste 3 Forecast-Eintraege pruefen
            for fc in forecast[:3]:
                condition = fc.get("condition", "").lower()
                if condition in cloudy_conditions:
                    return True
            break
        return False

    def _find_sensor_unit(self, states: list[dict], configured_entity: str,
                          search_keywords: list[str]) -> str:
        """Findet die unit_of_measurement eines Sensors."""
        if configured_entity:
            for s in states:
                if s.get("entity_id") == configured_entity:
                    return s.get("attributes", {}).get("unit_of_measurement", "")
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("sensor."):
                continue
            if any(kw in eid.lower() for kw in search_keywords):
                return s.get("attributes", {}).get("unit_of_measurement", "")
        return ""

    def _find_sensor_value(self, states: list[dict], configured_entity: str,
                           search_keywords: list[str]) -> Optional[float]:
        """Findet einen Sensor-Wert (konfiguriert oder per Keyword-Suche)."""
        # 1. Konfiguriertes Entity
        if configured_entity:
            for s in states:
                if s.get("entity_id") == configured_entity:
                    state_val = s.get("state")
                    if state_val is None or state_val in ("unavailable", "unknown", ""):
                        return None
                    try:
                        return float(state_val)
                    except (ValueError, TypeError):
                        return None

        # 2. Keyword-Suche
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("sensor."):
                continue
            eid_lower = eid.lower()
            if any(kw in eid_lower for kw in search_keywords):
                try:
                    val = float(s.get("state", 0))
                    return val  # Negative Werte = Netzeinspeisung (Solar)
                except (ValueError, TypeError):
                    continue

        return None

    async def _was_recently_alerted(self, alert_type: str) -> bool:
        """Prueft ob bereits kuerzlich ein Alert dieses Typs gesendet wurde (TTL kommt von _mark_alerted)."""
        if not self.redis:
            return False
        try:
            key = f"mha:energy:alert:{alert_type}"
            val = await self.redis.get(key)
            return val is not None
        except Exception as e:
            logger.debug("Alert-Check fehlgeschlagen: %s", e)
            return False

    async def _mark_alerted(self, alert_type: str, cooldown_minutes: int = 120):
        """Markiert einen Alert als gesendet."""
        if not self.redis:
            return
        try:
            key = f"mha:energy:alert:{alert_type}"
            await self.redis.setex(key, cooldown_minutes * 60, "1")
        except Exception as e:
            logger.debug("Alert markieren fehlgeschlagen: %s", e)
