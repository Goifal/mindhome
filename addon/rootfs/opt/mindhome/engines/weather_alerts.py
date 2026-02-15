# MindHome - engines/weather_alerts.py | see version.py for version info
"""
Weather forecast alerting.
Feature: #21 Wetter-Vorwarnung

Checks HA weather forecast for: rain/storm, frost, heat, snow.
Sends alerts 2-6 hours before event. Deduplicates via WeatherAlert model.
"""

import logging
from datetime import datetime, timezone, timedelta

from helpers import get_setting

logger = logging.getLogger("mindhome.engines.weather_alerts")

# Alert thresholds
THRESHOLDS = {
    "frost": {"temp_below": 0},
    "heat": {"temp_above": 33},
    "heavy_rain": {"precipitation_above": 10},  # mm/h
    "storm": {"wind_above": 60},  # km/h
    "snow": {"temp_below": 2, "condition_contains": ["snow", "schnee"]},
}

# German alert messages
MESSAGES_DE = {
    "frost": "Frostwarnung: Temperatur sinkt unter 0°C in den naechsten Stunden",
    "heat": "Hitzewarnung: Temperatur steigt ueber 33°C",
    "heavy_rain": "Starkregenwarnung: Niederschlag > 10mm/h erwartet",
    "storm": "Sturmwarnung: Windgeschwindigkeit > 60 km/h erwartet",
    "snow": "Schneewarnung: Schneefall erwartet bei niedrigen Temperaturen",
}

MESSAGES_EN = {
    "frost": "Frost warning: Temperature dropping below 0°C in the next hours",
    "heat": "Heat warning: Temperature rising above 33°C",
    "heavy_rain": "Heavy rain warning: Precipitation > 10mm/h expected",
    "storm": "Storm warning: Wind speed > 60 km/h expected",
    "snow": "Snow warning: Snowfall expected at low temperatures",
}


class WeatherAlertManager:
    """Monitors weather forecast and generates alerts with lead time.

    Alert types: heavy_rain, storm, frost, heat, snow.
    Stores in WeatherAlert table, deduplicates by type + valid_from window.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self._is_running = False
        self._cached_alerts = []

    def start(self):
        self._is_running = True
        logger.info("WeatherAlertManager started")

    def stop(self):
        self._is_running = False
        logger.info("WeatherAlertManager stopped")

    def _get_thresholds(self):
        return {
            "frost": float(get_setting("phase4.weather_alerts.frost_threshold_c", "0")),
            "heat": float(get_setting("phase4.weather_alerts.heat_threshold_c", "33")),
            "heavy_rain": float(get_setting("phase4.weather_alerts.rain_threshold_mmh", "10")),
            "storm": float(get_setting("phase4.weather_alerts.storm_threshold_kmh", "60")),
            "snow": float(get_setting("phase4.weather_alerts.snow_threshold_c", "2")),
        }

    def check(self):
        """Check weather forecast for upcoming alerts. Called every 30 min by scheduler."""
        if not self._is_running:
            return
        try:
            from models import WeatherAlert
            from routes.health import is_feature_enabled

            if not is_feature_enabled("phase4.weather_alerts"):
                return

            # Find weather entity in HA
            states = self.ha.get_states() or []
            weather_entity = None
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("weather."):
                    weather_entity = s
                    break

            if not weather_entity:
                return

            now = datetime.now(timezone.utc)
            forecast = weather_entity.get("attributes", {}).get("forecast", [])
            new_alerts = []
            thresholds = self._get_thresholds()

            for fc in forecast:
                fc_time_str = fc.get("datetime")
                if not fc_time_str:
                    continue
                try:
                    fc_time = datetime.fromisoformat(fc_time_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue

                # Only look 2-12 hours ahead
                hours_ahead = (fc_time - now).total_seconds() / 3600
                if hours_ahead < 0 or hours_ahead > 12:
                    continue

                temp = fc.get("temperature")
                temp_low = fc.get("templow", temp)
                wind = fc.get("wind_speed", 0)
                precip = fc.get("precipitation", 0)
                condition = (fc.get("condition") or "").lower()

                # Check frost
                if temp_low is not None and temp_low < thresholds["frost"]:
                    new_alerts.append(self._make_alert("frost", fc_time, fc, "warning"))

                # Check heat
                if temp is not None and temp > thresholds["heat"]:
                    new_alerts.append(self._make_alert("heat", fc_time, fc, "warning"))

                # Check heavy rain
                if precip and precip > thresholds["heavy_rain"]:
                    new_alerts.append(self._make_alert("heavy_rain", fc_time, fc, "warning"))

                # Check storm
                if wind and wind > thresholds["storm"]:
                    severity = "severe" if wind > 90 else "warning"
                    new_alerts.append(self._make_alert("storm", fc_time, fc, severity))

                # Check snow
                if (temp_low is not None and temp_low < thresholds["snow"]
                        and any(kw in condition for kw in ["snow", "schnee"])):
                    new_alerts.append(self._make_alert("snow", fc_time, fc, "info"))

            # Deduplicate and store
            with self.get_session() as session:
                stored_count = 0
                for alert_data in new_alerts:
                    # Check for duplicate (same type within 6h window)
                    existing = session.query(WeatherAlert).filter(
                        WeatherAlert.alert_type == alert_data["alert_type"],
                        WeatherAlert.valid_from > alert_data["valid_from"] - timedelta(hours=6),
                        WeatherAlert.valid_from < alert_data["valid_from"] + timedelta(hours=6),
                    ).first()
                    if existing:
                        continue

                    wa = WeatherAlert(
                        alert_type=alert_data["alert_type"],
                        severity=alert_data["severity"],
                        message_de=alert_data["message_de"],
                        message_en=alert_data["message_en"],
                        valid_from=alert_data["valid_from"],
                        valid_until=alert_data["valid_from"] + timedelta(hours=6),
                        forecast_data=alert_data["forecast_data"],
                    )
                    session.add(wa)
                    stored_count += 1

                    self.event_bus.emit("weather.alert_created", {
                        "alert_type": alert_data["alert_type"],
                        "severity": alert_data["severity"],
                        "valid_from": alert_data["valid_from"].isoformat(),
                    })

                if stored_count:
                    logger.info(f"WeatherAlertManager: {stored_count} new alerts created")

            # Update cached alerts
            self._refresh_cache()

        except Exception as e:
            logger.error(f"WeatherAlertManager check error: {e}")

    def _make_alert(self, alert_type, valid_from, forecast_data, severity="warning"):
        """Create alert dict."""
        return {
            "alert_type": alert_type,
            "severity": severity,
            "message_de": MESSAGES_DE.get(alert_type, f"Wetterwarnung: {alert_type}"),
            "message_en": MESSAGES_EN.get(alert_type, f"Weather alert: {alert_type}"),
            "valid_from": valid_from,
            "forecast_data": forecast_data,
        }

    def _refresh_cache(self):
        """Refresh cached active alerts."""
        try:
            from models import WeatherAlert
            with self.get_session() as session:
                now = datetime.now(timezone.utc)
                alerts = session.query(WeatherAlert).filter(
                    WeatherAlert.valid_until > now
                ).order_by(WeatherAlert.valid_from).all()
                self._cached_alerts = [{
                    "id": a.id,
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "message_de": a.message_de,
                    "message_en": a.message_en,
                    "valid_from": a.valid_from.isoformat() if a.valid_from else None,
                    "valid_until": a.valid_until.isoformat() if a.valid_until else None,
                    "was_notified": a.was_notified,
                    "forecast_data": a.forecast_data,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                } for a in alerts]
        except Exception as e:
            logger.error(f"_refresh_cache error: {e}")

    def get_active_alerts(self):
        """Return currently active weather alerts."""
        if self._cached_alerts:
            return self._cached_alerts
        self._refresh_cache()
        return self._cached_alerts
