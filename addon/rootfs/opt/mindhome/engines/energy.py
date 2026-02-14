# MindHome - engines/energy.py | see version.py for version info
"""
Energy optimization, PV management, standby monitoring, and forecasting.
Features: #1 Energieoptimierung, #2 PV-Lastmanagement, #3 Standby-Killer, #26 Energieprognose
"""

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from db import get_db_session, get_db_readonly
from models import EnergyReading, EnergyConfig, EnergyForecast, StandbyConfig
from routes.health import is_feature_enabled

logger = logging.getLogger("mindhome.engines.energy")


class EnergyOptimizer:
    """Analyzes consumption patterns and suggests optimizations (#1).

    Detects peak loads, compares daily usage to averages, generates saving tips.
    Also handles PV surplus management (#2).
    """

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self._is_running = False
        self._recommendations = []
        self._savings = {"estimated_monthly_eur": 0, "potential_kwh": 0}
        self._last_analysis = None

    def start(self):
        self._is_running = True
        logger.info("EnergyOptimizer started")

    def stop(self):
        self._is_running = False
        logger.info("EnergyOptimizer stopped")

    def daily_analysis(self):
        """Run daily energy analysis. Called by scheduler at 00:05."""
        if not self._is_running:
            return
        if not is_feature_enabled("phase4.energy_optimization"):
            return

        try:
            recommendations = []
            total_savings_kwh = 0

            with get_db_readonly() as session:
                cfg = session.query(EnergyConfig).first()
                price = cfg.price_per_kwh if cfg else 0.25

                now = datetime.now(timezone.utc)
                cutoff_30d = now - timedelta(days=30)
                cutoff_1d = now - timedelta(days=1)

                # --- Analyze hourly consumption pattern ---
                readings_30d = session.query(EnergyReading).filter(
                    EnergyReading.created_at >= cutoff_30d,
                    EnergyReading.power_w.isnot(None)
                ).all()

                if not readings_30d:
                    self._recommendations = [{
                        "type": "info",
                        "message_de": "Noch keine Energiedaten vorhanden.",
                        "message_en": "No energy data available yet.",
                    }]
                    self._last_analysis = now
                    return

                # Group by hour for peak detection
                hourly = defaultdict(list)
                for r in readings_30d:
                    if r.created_at:
                        hourly[r.created_at.hour].append(r.power_w)

                # Find peak hours (top 3 by average wattage)
                hourly_avg = {}
                for hour, vals in hourly.items():
                    hourly_avg[hour] = sum(vals) / len(vals) if vals else 0

                if hourly_avg:
                    overall_avg = sum(hourly_avg.values()) / len(hourly_avg)
                    peak_hours = sorted(hourly_avg.items(), key=lambda x: x[1], reverse=True)[:3]

                    for hour, avg_w in peak_hours:
                        if avg_w > overall_avg * 1.5:
                            saving = (avg_w - overall_avg) * 0.001 * 30
                            recommendations.append({
                                "type": "peak_load",
                                "hour": hour,
                                "avg_watts": round(avg_w, 1),
                                "message_de": f"Spitzenlast um {hour:02d}:00 ({avg_w:.0f}W). Verbraucher verschieben.",
                                "message_en": f"Peak load at {hour:02d}:00 ({avg_w:.0f}W). Consider shifting loads.",
                                "savings_kwh": round(saving, 2),
                            })
                            total_savings_kwh += saving

                # --- Compare today vs. 30-day average ---
                readings_today = [r for r in readings_30d if r.created_at and r.created_at >= cutoff_1d]
                today_total = sum(r.energy_kwh or 0 for r in readings_today)
                days_with_data = len(set(r.created_at.date() for r in readings_30d if r.created_at))
                all_kwh = sum(r.energy_kwh or 0 for r in readings_30d)
                daily_avg = all_kwh / max(days_with_data, 1)

                if daily_avg > 0 and today_total > 0:
                    diff_pct = ((today_total - daily_avg) / daily_avg) * 100
                    if diff_pct > 20:
                        recommendations.append({
                            "type": "above_average",
                            "today_kwh": round(today_total, 2),
                            "average_kwh": round(daily_avg, 2),
                            "diff_percent": round(diff_pct, 1),
                            "message_de": f"Verbrauch ({today_total:.1f} kWh) liegt {diff_pct:.0f}% ueber Durchschnitt ({daily_avg:.1f} kWh).",
                            "message_en": f"Consumption ({today_total:.1f} kWh) is {diff_pct:.0f}% above average ({daily_avg:.1f} kWh).",
                        })
                    elif diff_pct < -20:
                        recommendations.append({
                            "type": "below_average",
                            "today_kwh": round(today_total, 2),
                            "average_kwh": round(daily_avg, 2),
                            "diff_percent": round(diff_pct, 1),
                            "message_de": f"Gut! Verbrauch ({today_total:.1f} kWh) liegt {abs(diff_pct):.0f}% unter Durchschnitt.",
                            "message_en": f"Great! Consumption ({today_total:.1f} kWh) is {abs(diff_pct):.0f}% below average.",
                        })

                # --- Per-entity high consumers ---
                entity_totals = defaultdict(float)
                for r in readings_30d:
                    if r.energy_kwh:
                        entity_totals[r.entity_id] += r.energy_kwh

                if entity_totals:
                    top_consumers = sorted(entity_totals.items(), key=lambda x: x[1], reverse=True)[:5]
                    for entity_id, total_kwh in top_consumers:
                        if total_kwh > 10:
                            monthly_cost = total_kwh * price
                            recommendations.append({
                                "type": "high_consumer",
                                "entity_id": entity_id,
                                "monthly_kwh": round(total_kwh, 2),
                                "monthly_cost": round(monthly_cost, 2),
                                "message_de": f"{entity_id}: {total_kwh:.1f} kWh/Monat ({monthly_cost:.2f} EUR)",
                                "message_en": f"{entity_id}: {total_kwh:.1f} kWh/month ({monthly_cost:.2f} EUR)",
                            })

            self._recommendations = recommendations
            self._savings = {
                "estimated_monthly_eur": round(total_savings_kwh * price, 2),
                "potential_kwh": round(total_savings_kwh, 2),
            }
            self._last_analysis = datetime.now(timezone.utc)
            logger.info(f"Energy analysis: {len(recommendations)} recommendations, {total_savings_kwh:.1f} kWh potential")

        except Exception as e:
            logger.error(f"Energy analysis error: {e}")

    def get_recommendations(self):
        """Return current optimization recommendations."""
        return self._recommendations

    def get_savings_estimate(self):
        """Return estimated savings in EUR."""
        return self._savings

    # --- PV Management (#2) ---

    def get_pv_status(self):
        """Return current PV status (production, consumption, surplus)."""
        if not is_feature_enabled("phase4.pv_management"):
            return None

        try:
            with get_db_readonly() as session:
                cfg = session.query(EnergyConfig).first()
                if not cfg or not cfg.solar_enabled or not cfg.solar_entity:
                    return None
                solar_entity = cfg.solar_entity
                grid_import = cfg.grid_import_entity
                grid_export = cfg.grid_export_entity
                pv_priorities = cfg.pv_priority_entities or []
                pv_mgmt = cfg.pv_load_management

            production_w = self._read_power(solar_entity)
            consumption_w = self._read_power(grid_import)
            export_w = self._read_power(grid_export)

            surplus_w = max(0, production_w - consumption_w)
            self_pct = round((1 - export_w / production_w) * 100, 1) if production_w > 0 else 0

            return {
                "production_w": round(production_w, 1),
                "consumption_w": round(consumption_w, 1),
                "export_w": round(export_w, 1),
                "surplus_w": round(surplus_w, 1),
                "self_consumption_pct": self_pct,
                "pv_load_management": pv_mgmt,
                "priority_entities": pv_priorities,
            }
        except Exception as e:
            logger.error(f"PV status error: {e}")
            return None

    def check_pv_surplus(self):
        """Check PV surplus and manage loads accordingly. Called every 5 min."""
        if not self._is_running:
            return
        if not is_feature_enabled("phase4.pv_management"):
            return

        try:
            status = self.get_pv_status()
            if not status or not status.get("pv_load_management"):
                return

            surplus_w = status.get("surplus_w", 0)
            priorities = status.get("priority_entities") or []

            if surplus_w < 100 or not priorities:
                return

            remaining = surplus_w
            for entity_id in priorities:
                if remaining < 50:
                    break
                state = self.ha.get_state(entity_id)
                if not state:
                    continue
                if state.get("state", "off") == "off":
                    domain = entity_id.split(".")[0]
                    self.ha.call_service(domain, "turn_on", entity_id=entity_id)
                    remaining -= 200  # conservative estimate
                    logger.info(f"PV surplus: Activated {entity_id} ({surplus_w:.0f}W surplus)")

        except Exception as e:
            logger.error(f"PV surplus check error: {e}")

    def _read_power(self, entity_id):
        """Read a power value from HA entity state."""
        if not entity_id:
            return 0
        state = self.ha.get_state(entity_id)
        if not state:
            return 0
        try:
            val = float(state.get("state", 0))
            unit = state.get("attributes", {}).get("unit_of_measurement", "W")
            if unit == "kW":
                val *= 1000
            return abs(val)
        except (ValueError, TypeError):
            return 0


class StandbyMonitor:
    """Monitors configured devices for standby power draw (#3).

    If power < threshold_watts for > idle_minutes: notify or auto-off.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._standby_tracking = {}  # entity_id -> {"since": datetime, "watts": float, "config": dict}

    def start(self):
        self._is_running = True
        logger.info("StandbyMonitor started")

    def stop(self):
        self._is_running = False
        self._standby_tracking.clear()
        logger.info("StandbyMonitor stopped")

    def check(self):
        """Check all standby-configured devices. Called every 5 min."""
        if not self._is_running:
            return
        if not is_feature_enabled("phase4.standby_killer"):
            return

        try:
            with get_db_readonly() as session:
                configs = session.query(StandbyConfig).filter_by(is_active=True).all()
                config_data = [{
                    "id": c.id,
                    "entity_id": c.entity_id,
                    "device_id": c.device_id,
                    "threshold_watts": c.threshold_watts,
                    "idle_minutes": c.idle_minutes,
                    "auto_off": c.auto_off,
                    "notify_dashboard": c.notify_dashboard,
                } for c in configs]

            now = datetime.now(timezone.utc)

            for cfg in config_data:
                entity_id = cfg["entity_id"]
                if not entity_id:
                    continue

                state = self.ha.get_state(entity_id)
                if not state:
                    continue

                try:
                    power_w = float(state.get("state", 0))
                except (ValueError, TypeError):
                    continue

                if power_w < cfg["threshold_watts"]:
                    # Device is in standby range
                    if entity_id not in self._standby_tracking:
                        self._standby_tracking[entity_id] = {
                            "since": now, "watts": power_w, "config": cfg,
                        }
                    else:
                        self._standby_tracking[entity_id]["watts"] = power_w

                    entry = self._standby_tracking[entity_id]
                    idle_min = (now - entry["since"]).total_seconds() / 60

                    if idle_min >= cfg["idle_minutes"]:
                        if cfg["auto_off"]:
                            self._auto_off(entity_id)
                        elif cfg["notify_dashboard"]:
                            self._notify_standby(entity_id, power_w, idle_min)
                else:
                    # Device is active — remove from tracking
                    self._standby_tracking.pop(entity_id, None)

        except Exception as e:
            logger.error(f"Standby check error: {e}")

    def _auto_off(self, sensor_entity):
        """Turn off a device detected as standby."""
        try:
            # Power sensors: sensor.xxx_power → switch.xxx
            base = sensor_entity.replace("sensor.", "")
            for suffix in ("_power", "_energy", "_watt", "_leistung"):
                base = base.replace(suffix, "")
            switch_entity = f"switch.{base}"

            state = self.ha.get_state(switch_entity)
            if state and state.get("state") == "on":
                self.ha.call_service("switch", "turn_off", entity_id=switch_entity)
                logger.info(f"Standby auto-off: {switch_entity}")
                self._standby_tracking.pop(sensor_entity, None)

                if self.event_bus:
                    self.event_bus.publish("energy.standby_off", {
                        "entity_id": switch_entity, "sensor": sensor_entity,
                    })
        except Exception as e:
            logger.error(f"Auto-off error for {sensor_entity}: {e}")

    def _notify_standby(self, entity_id, watts, minutes):
        """Publish standby detection event for notification system."""
        if self.event_bus:
            self.event_bus.publish("energy.standby_detected", {
                "entity_id": entity_id,
                "watts": round(watts, 1),
                "minutes": round(minutes),
            })

    def get_standby_status(self):
        """Return list of devices currently in standby."""
        now = datetime.now(timezone.utc)
        result = []
        for entity_id, entry in self._standby_tracking.items():
            idle_min = (now - entry["since"]).total_seconds() / 60
            result.append({
                "entity_id": entity_id,
                "power_w": round(entry["watts"], 1),
                "standby_since": entry["since"].isoformat(),
                "idle_minutes": round(idle_min),
                "auto_off": entry.get("config", {}).get("auto_off", False),
            })
        return result


class EnergyForecaster:
    """Predicts daily energy consumption using historical data + weather (#26).

    Uses weighted average of same weekday + similar weather from last 30 days.
    """

    def __init__(self, ha_connection, db_session_factory):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self._is_running = False

    def start(self):
        self._is_running = True
        logger.info("EnergyForecaster started")

    def stop(self):
        self._is_running = False
        logger.info("EnergyForecaster stopped")

    def daily_forecast(self):
        """Generate forecast for next 7 days. Called by scheduler at 00:05."""
        if not self._is_running:
            return
        if not is_feature_enabled("phase4.energy_forecast"):
            return

        try:
            with get_db_session() as session:
                now = datetime.now(timezone.utc)
                cutoff_30d = now - timedelta(days=30)

                readings = session.query(EnergyReading).filter(
                    EnergyReading.created_at >= cutoff_30d,
                    EnergyReading.energy_kwh.isnot(None)
                ).all()

                if not readings:
                    logger.info("EnergyForecaster: No historical data for forecast")
                    return

                # Group total kWh by date
                daily_totals = defaultdict(float)
                daily_weekday = {}
                for r in readings:
                    if r.created_at:
                        d = r.created_at.date()
                        daily_totals[d] += r.energy_kwh or 0
                        daily_weekday[d] = d.weekday()

                if not daily_totals:
                    return

                weather_condition = self._get_weather_condition()
                today = now.date()

                # Generate 7-day forecast
                for offset in range(1, 8):
                    forecast_date = today + timedelta(days=offset)
                    target_weekday = forecast_date.weekday()
                    day_type = "weekend" if target_weekday >= 5 else "weekday"

                    # Weighted average: same weekday 2x, recency bonus
                    weighted_sum = 0
                    weight_total = 0
                    for d, kwh in daily_totals.items():
                        weight = 2.0 if daily_weekday.get(d) == target_weekday else 1.0
                        days_ago = (today - d).days
                        recency = max(0.5, 1.0 - days_ago * 0.02)
                        w = weight * recency
                        weighted_sum += kwh * w
                        weight_total += w

                    predicted = weighted_sum / weight_total if weight_total > 0 else 0
                    date_str = forecast_date.isoformat()

                    existing = session.query(EnergyForecast).filter_by(date=date_str).first()
                    if existing:
                        existing.predicted_kwh = round(predicted, 2)
                        existing.weather_condition = weather_condition
                        existing.day_type = day_type
                    else:
                        session.add(EnergyForecast(
                            date=date_str,
                            predicted_kwh=round(predicted, 2),
                            weather_condition=weather_condition,
                            day_type=day_type,
                            model_version="v1",
                        ))

                # Update actual_kwh for yesterday
                yesterday = today - timedelta(days=1)
                yesterday_str = yesterday.isoformat()
                yesterday_kwh = daily_totals.get(yesterday, 0)
                existing_y = session.query(EnergyForecast).filter_by(date=yesterday_str).first()
                if existing_y and yesterday_kwh > 0:
                    existing_y.actual_kwh = round(yesterday_kwh, 2)

            logger.info("EnergyForecaster: 7-day forecast generated")

        except Exception as e:
            logger.error(f"Energy forecast error: {e}")

    def _get_weather_condition(self):
        """Get current weather condition from HA weather entity."""
        try:
            states = self.ha.get_states() or []
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    return s.get("state", "unknown")
        except Exception:
            pass
        return "unknown"

    def get_forecast(self, days=7):
        """Return forecast for next N days."""
        try:
            with get_db_readonly() as session:
                today = datetime.now(timezone.utc).date()
                forecasts = session.query(EnergyForecast).filter(
                    EnergyForecast.date >= today.isoformat()
                ).order_by(EnergyForecast.date).limit(days).all()

                return [{
                    "date": f.date,
                    "predicted_kwh": f.predicted_kwh,
                    "actual_kwh": f.actual_kwh,
                    "weather_condition": f.weather_condition,
                    "day_type": f.day_type,
                    "model_version": f.model_version,
                } for f in forecasts]
        except Exception as e:
            logger.error(f"Get forecast error: {e}")
            return []
