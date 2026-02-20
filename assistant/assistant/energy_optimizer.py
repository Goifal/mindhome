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

        # Aktueller Strompreis
        price = self._find_sensor_value(states, self.price_sensor, ["price", "strom", "electricity"])
        if price is not None:
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

    async def check_energy_events(self) -> list[dict]:
        """Periodischer Check fuer proaktive Energie-Meldungen.

        Wird von proactive.py aufgerufen.

        Returns:
            Liste von Meldungen (kann leer sein)
        """
        if not self.enabled:
            return []

        alerts = []
        states = await self.ha.get_states()
        if not states:
            return []

        # 1. Guenstiger Strom
        price = self._find_sensor_value(states, self.price_sensor, ["price", "strom", "electricity"])
        if price is not None and price < self.price_low:
            if not await self._was_recently_alerted("low_price", cooldown_minutes=120):
                await self._mark_alerted("low_price")
                alerts.append({
                    "type": "energy_price_low",
                    "message": f"Strom ist gerade guenstig ({price:.1f} ct/kWh). "
                               f"Guter Zeitpunkt fuer Waschmaschine oder Trockner.",
                    "urgency": "low",
                })

        # 2. Solar-Ueberschuss
        solar = self._find_sensor_value(states, self.solar_sensor, ["solar", "pv"])
        export = self._find_sensor_value(states, self.grid_export_sensor, ["export", "einspeisung"])
        if solar is not None and solar > self.solar_high_watts and export and export > 500:
            if not await self._was_recently_alerted("solar_high", cooldown_minutes=180):
                await self._mark_alerted("solar_high")
                alerts.append({
                    "type": "solar_surplus",
                    "message": f"Solar-Ertrag ist hoch ({solar:.0f} W) mit {export:.0f} W Einspeisung. "
                               f"Eigenverbrauch optimieren, z.B. Waschmaschine starten.",
                    "urgency": "low",
                })

        # 3. Hoher Strompreis
        if price is not None and price > self.price_high:
            if not await self._was_recently_alerted("high_price", cooldown_minutes=240):
                await self._mark_alerted("high_price")
                alerts.append({
                    "type": "energy_price_high",
                    "message": f"Strompreis ist hoch ({price:.1f} ct/kWh). "
                               f"Grosse Verbraucher besser spaeter einschalten.",
                    "urgency": "low",
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

        return recs

    def _find_sensor_value(self, states: list[dict], configured_entity: str,
                           search_keywords: list[str]) -> Optional[float]:
        """Findet einen Sensor-Wert (konfiguriert oder per Keyword-Suche)."""
        # 1. Konfiguriertes Entity
        if configured_entity:
            for s in states:
                if s.get("entity_id") == configured_entity:
                    try:
                        return float(s.get("state", 0))
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
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    continue

        return None

    async def _was_recently_alerted(self, alert_type: str, cooldown_minutes: int = 120) -> bool:
        """Prueft ob bereits kuerzlich ein Alert dieses Typs gesendet wurde."""
        if not self.redis:
            return False
        key = f"mha:energy:alert:{alert_type}"
        val = await self.redis.get(key)
        return val is not None

    async def _mark_alerted(self, alert_type: str, cooldown_minutes: int = 120):
        """Markiert einen Alert als gesendet."""
        if not self.redis:
            return
        key = f"mha:energy:alert:{alert_type}"
        await self.redis.setex(key, cooldown_minutes * 60, "1")
