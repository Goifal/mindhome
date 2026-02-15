# MindHome - engines/health_dashboard.py | see version.py for version info
"""
Health Dashboard Aggregator - Batch 5
Aggregates all health data from Batch 1-4 engines into a unified dashboard.
Stores periodic HealthMetric snapshots and generates weekly reports.
"""

import logging
from datetime import datetime, timezone, timedelta

from helpers import get_setting

logger = logging.getLogger("mindhome.engines.health_dashboard")


class HealthAggregator:
    """Aggregates all health data for the dashboard and weekly report.

    Collects data from: SleepDetector, ComfortCalculator, VentilationMonitor,
    ScreenTimeMonitor, MoodEstimator, WeatherAlertManager, EnergyOptimizer.
    Stores periodic snapshots in HealthMetric model.
    """

    def __init__(self, ha_connection, db_session_factory, event_bus, engines=None):
        self.ha = ha_connection
        self.get_session = db_session_factory
        self.event_bus = event_bus
        self.engines = engines or {}
        self._is_running = False
        self._cached_dashboard = None
        self._cached_report = None

    def start(self):
        self._is_running = True
        logger.info("HealthAggregator started")

    def stop(self):
        self._is_running = False
        logger.info("HealthAggregator stopped")

    def aggregate(self):
        """Periodic aggregation — collect current data and store HealthMetrics."""
        if not self._is_running:
            return
        try:
            from routes.health import is_feature_enabled
            if not is_feature_enabled("phase4.health_dashboard"):
                return

            dashboard = self._build_dashboard()
            self._cached_dashboard = dashboard

            # Store key metrics in DB for historical tracking
            self._store_metrics(dashboard)

            logger.debug("HealthAggregator: dashboard data refreshed")
        except Exception as e:
            logger.error(f"HealthAggregator aggregate error: {e}")

    def get_dashboard(self):
        """Return current dashboard data (cached or freshly built)."""
        if self._cached_dashboard:
            return self._cached_dashboard
        try:
            return self._build_dashboard()
        except Exception as e:
            logger.error(f"HealthAggregator get_dashboard error: {e}")
            return self._empty_dashboard()

    def get_weekly_report(self):
        """Generate weekly report from stored HealthMetric data."""
        try:
            return self._build_weekly_report()
        except Exception as e:
            logger.error(f"HealthAggregator weekly report error: {e}")
            return {"period": None, "sections": {}, "generated_at": None}

    def get_metric_history(self, metric_type, days=30):
        """Get historical values for a specific metric type."""
        try:
            from models import HealthMetric
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            with self.get_session() as session:
                rows = session.query(HealthMetric).filter(
                    HealthMetric.metric_type == metric_type,
                    HealthMetric.created_at >= cutoff,
                ).order_by(HealthMetric.created_at.asc()).all()
                return [
                    {
                        "value": r.value,
                        "unit": r.unit,
                        "context": r.context,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"HealthAggregator metric_history error: {e}")
            return []

    # ── Internal: Build Dashboard ──

    def _build_dashboard(self):
        """Collect live data from all engines."""
        now = datetime.now(timezone.utc)

        # Sleep
        sleep_data = None
        sleep_detector = self.engines.get("sleep_detector")
        if sleep_detector:
            try:
                sessions = sleep_detector.get_recent_sessions(days=7)
                completed = [s for s in sessions if s.get("quality_score") is not None and s.get("duration_hours")]
                avg_quality = round(sum(s["quality_score"] for s in completed) / len(completed), 1) if completed else None
                avg_duration = round(sum(s["duration_hours"] for s in completed) / len(completed), 1) if completed else None
                sleep_data = {
                    "avg_quality": avg_quality,
                    "avg_duration": avg_duration,
                    "nights_tracked": len(completed),
                    "last_session": sessions[0] if sessions else None,
                    "trend": self._calc_trend("sleep_quality", 7),
                }
            except Exception as e:
                logger.debug(f"Dashboard sleep error: {e}")

        # Comfort
        comfort_data = None
        comfort_calculator = self.engines.get("comfort_calculator")
        if comfort_calculator:
            try:
                scores = comfort_calculator.get_scores()
                if scores:
                    avg_score = round(sum(s.get("score", 0) for s in scores) / len(scores), 1)
                    worst_room = min(scores, key=lambda s: s.get("score", 100))
                    best_room = max(scores, key=lambda s: s.get("score", 0))
                    comfort_data = {
                        "avg_score": avg_score,
                        "room_count": len(scores),
                        "worst_room": {"name": worst_room.get("room_name", "?"), "score": worst_room.get("score")},
                        "best_room": {"name": best_room.get("room_name", "?"), "score": best_room.get("score")},
                        "traffic_lights": comfort_calculator.get_traffic_lights(),
                        "trend": self._calc_trend("comfort_avg", 7),
                    }
            except Exception as e:
                logger.debug(f"Dashboard comfort error: {e}")

        # Ventilation
        ventilation_data = None
        ventilation_monitor = self.engines.get("ventilation_monitor")
        if ventilation_monitor:
            try:
                status = ventilation_monitor.get_status()
                rooms_needing = [r for r in status if r.get("needs_ventilation")]
                ventilation_data = {
                    "rooms_monitored": len(status),
                    "rooms_needing_ventilation": len(rooms_needing),
                    "rooms_detail": rooms_needing[:5],
                }
            except Exception as e:
                logger.debug(f"Dashboard ventilation error: {e}")

        # Screen Time
        screen_time_data = None
        screen_time_monitor = self.engines.get("screen_time_monitor")
        if screen_time_monitor:
            try:
                usage = screen_time_monitor.get_usage(None)
                if usage:
                    total_min = sum(u.get("today_minutes", 0) for u in usage) if isinstance(usage, list) else 0
                    screen_time_data = {
                        "total_today_min": round(total_min, 1),
                        "entity_count": len(usage) if isinstance(usage, list) else 0,
                        "trend": self._calc_trend("screen_time", 7),
                    }
            except Exception as e:
                logger.debug(f"Dashboard screen_time error: {e}")

        # Mood
        mood_data = None
        mood_estimator = self.engines.get("mood_estimator")
        if mood_estimator:
            try:
                mood_data = mood_estimator.estimate()
            except Exception as e:
                logger.debug(f"Dashboard mood error: {e}")

        # Weather alerts
        weather_data = None
        weather_alert_manager = self.engines.get("weather_alert_manager")
        if weather_alert_manager:
            try:
                alerts = weather_alert_manager.get_active_alerts()
                weather_data = {
                    "active_alerts": len(alerts),
                    "alerts": alerts[:5],
                }
            except Exception as e:
                logger.debug(f"Dashboard weather error: {e}")

        # Energy summary
        energy_data = None
        energy_optimizer = self.engines.get("energy_optimizer")
        if energy_optimizer:
            try:
                energy_data = {
                    "optimization_available": True,
                }
            except Exception as e:
                logger.debug(f"Dashboard energy error: {e}")

        # Overall health score (weighted average of available metrics)
        overall_score = self._calc_overall_score(sleep_data, comfort_data, screen_time_data, ventilation_data)

        return {
            "overall_score": overall_score,
            "sleep": sleep_data,
            "comfort": comfort_data,
            "ventilation": ventilation_data,
            "screen_time": screen_time_data,
            "mood": mood_data,
            "weather": weather_data,
            "energy": energy_data,
            "updated_at": now.isoformat(),
        }

    def _calc_overall_score(self, sleep_data, comfort_data, screen_time_data, ventilation_data):
        """Calculate weighted overall health score (0-100)."""
        w_sleep = float(get_setting("phase4.health_dashboard.weight_sleep", "35")) / 100.0
        w_comfort = float(get_setting("phase4.health_dashboard.weight_comfort", "30")) / 100.0
        w_screen = float(get_setting("phase4.health_dashboard.weight_screen_time", "15")) / 100.0
        w_vent = float(get_setting("phase4.health_dashboard.weight_ventilation", "20")) / 100.0

        scores = []
        weights = []

        if sleep_data and sleep_data.get("avg_quality") is not None:
            scores.append(sleep_data["avg_quality"])
            weights.append(w_sleep)

        if comfort_data and comfort_data.get("avg_score") is not None:
            scores.append(comfort_data["avg_score"])
            weights.append(w_comfort)

        if screen_time_data and screen_time_data.get("total_today_min") is not None:
            # Score: 100 if <60min, decreasing linearly to 0 at 480min
            st_min = screen_time_data["total_today_min"]
            st_score = max(0, min(100, 100 - (st_min - 60) * (100 / 420)))
            scores.append(st_score)
            weights.append(w_screen)

        if ventilation_data:
            total = ventilation_data.get("rooms_monitored", 0)
            needing = ventilation_data.get("rooms_needing_ventilation", 0)
            if total > 0:
                vent_score = round(((total - needing) / total) * 100, 1)
                scores.append(vent_score)
                weights.append(w_vent)

        if not scores:
            return None

        total_weight = sum(weights)
        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        return round(weighted_sum / total_weight, 1) if total_weight > 0 else None

    def _calc_trend(self, metric_type, days):
        """Calculate trend direction from stored metrics."""
        try:
            from models import HealthMetric
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=days)
            midpoint = now - timedelta(days=days / 2)

            with self.get_session() as session:
                older = session.query(HealthMetric).filter(
                    HealthMetric.metric_type == metric_type,
                    HealthMetric.created_at >= cutoff,
                    HealthMetric.created_at < midpoint,
                ).all()
                newer = session.query(HealthMetric).filter(
                    HealthMetric.metric_type == metric_type,
                    HealthMetric.created_at >= midpoint,
                ).all()

                if not older or not newer:
                    return "stable"

                avg_older = sum(r.value for r in older) / len(older)
                avg_newer = sum(r.value for r in newer) / len(newer)
                diff = avg_newer - avg_older

                if abs(diff) < 2:
                    return "stable"
                return "improving" if diff > 0 else "declining"
        except Exception:
            return "stable"

    def _store_metrics(self, dashboard):
        """Store current metric values in HealthMetric table."""
        try:
            from models import HealthMetric
            now = datetime.now(timezone.utc)

            metrics_to_store = []

            if dashboard.get("sleep") and dashboard["sleep"].get("avg_quality") is not None:
                metrics_to_store.append(HealthMetric(
                    metric_type="sleep_quality",
                    value=dashboard["sleep"]["avg_quality"],
                    unit="score",
                    context={"avg_duration": dashboard["sleep"].get("avg_duration")},
                    created_at=now,
                ))

            if dashboard.get("comfort") and dashboard["comfort"].get("avg_score") is not None:
                metrics_to_store.append(HealthMetric(
                    metric_type="comfort_avg",
                    value=dashboard["comfort"]["avg_score"],
                    unit="score",
                    context={"room_count": dashboard["comfort"].get("room_count")},
                    created_at=now,
                ))

            if dashboard.get("screen_time") and dashboard["screen_time"].get("total_today_min") is not None:
                metrics_to_store.append(HealthMetric(
                    metric_type="screen_time",
                    value=dashboard["screen_time"]["total_today_min"],
                    unit="minutes",
                    created_at=now,
                ))

            if dashboard.get("overall_score") is not None:
                metrics_to_store.append(HealthMetric(
                    metric_type="overall_health",
                    value=dashboard["overall_score"],
                    unit="score",
                    created_at=now,
                ))

            if metrics_to_store:
                with self.get_session() as session:
                    for m in metrics_to_store:
                        session.add(m)
                    session.flush()

        except Exception as e:
            logger.error(f"HealthAggregator store_metrics error: {e}")

    # ── Internal: Weekly Report ──

    def _build_weekly_report(self):
        """Build a weekly health report from the last 7 days of stored metrics."""
        from models import HealthMetric
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        with self.get_session() as session:
            # This week
            this_week = session.query(HealthMetric).filter(
                HealthMetric.created_at >= week_ago,
            ).all()
            # Previous week (for comparison)
            prev_week = session.query(HealthMetric).filter(
                HealthMetric.created_at >= two_weeks_ago,
                HealthMetric.created_at < week_ago,
            ).all()

        def _avg_for_type(metrics, metric_type):
            vals = [m.value for m in metrics if m.metric_type == metric_type and m.value is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        def _comparison(current, previous):
            if current is None or previous is None:
                return {"change": None, "direction": "stable"}
            diff = round(current - previous, 1)
            direction = "improving" if diff > 0 else "declining" if diff < 0 else "stable"
            return {"change": diff, "direction": direction}

        # Build report sections
        sleep_quality_this = _avg_for_type(this_week, "sleep_quality")
        sleep_quality_prev = _avg_for_type(prev_week, "sleep_quality")

        comfort_this = _avg_for_type(this_week, "comfort_avg")
        comfort_prev = _avg_for_type(prev_week, "comfort_avg")

        screen_this = _avg_for_type(this_week, "screen_time")
        screen_prev = _avg_for_type(prev_week, "screen_time")

        overall_this = _avg_for_type(this_week, "overall_health")
        overall_prev = _avg_for_type(prev_week, "overall_health")

        # Generate recommendations
        recommendations = []
        if sleep_quality_this is not None and sleep_quality_this < 60:
            recommendations.append({
                "category": "sleep",
                "icon": "mdi-sleep",
                "text_de": "Schlafqualitaet unter 60 — Raumtemperatur und Laerm pruefen.",
                "text_en": "Sleep quality below 60 — check room temperature and noise.",
            })
        if comfort_this is not None and comfort_this < 60:
            recommendations.append({
                "category": "comfort",
                "icon": "mdi-thermometer-alert",
                "text_de": "Komfort-Score niedrig — Raumklima (CO2, Temperatur) verbessern.",
                "text_en": "Comfort score low — improve room climate (CO2, temperature).",
            })
        if screen_this is not None and screen_this > 180:
            recommendations.append({
                "category": "screen_time",
                "icon": "mdi-monitor-eye",
                "text_de": "Bildschirmzeit ueber 3h/Tag — Pausen einlegen.",
                "text_en": "Screen time above 3h/day — consider taking breaks.",
            })
        if not recommendations:
            recommendations.append({
                "category": "general",
                "icon": "mdi-check-circle",
                "text_de": "Alles im gruenen Bereich! Weiter so.",
                "text_en": "Everything looking good! Keep it up.",
            })

        return {
            "period": {
                "from": week_ago.strftime("%Y-%m-%d"),
                "to": now.strftime("%Y-%m-%d"),
            },
            "sections": {
                "overall": {
                    "value": overall_this,
                    "unit": "score",
                    "comparison": _comparison(overall_this, overall_prev),
                },
                "sleep": {
                    "value": sleep_quality_this,
                    "unit": "score",
                    "comparison": _comparison(sleep_quality_this, sleep_quality_prev),
                },
                "comfort": {
                    "value": comfort_this,
                    "unit": "score",
                    "comparison": _comparison(comfort_this, comfort_prev),
                },
                "screen_time": {
                    "value": screen_this,
                    "unit": "min/day",
                    "comparison": _comparison(
                        screen_prev, screen_this  # inverted: lower is better
                    ) if screen_this is not None and screen_prev is not None else {"change": None, "direction": "stable"},
                },
            },
            "recommendations": recommendations,
            "data_points": len(this_week),
            "generated_at": now.isoformat(),
        }

    def _empty_dashboard(self):
        return {
            "overall_score": None,
            "sleep": None,
            "comfort": None,
            "ventilation": None,
            "screen_time": None,
            "mood": None,
            "weather": None,
            "energy": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
