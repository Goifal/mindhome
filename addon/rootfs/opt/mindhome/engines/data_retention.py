# MindHome - engines/data_retention.py | see version.py for version info
"""
Data retention policy — nightly cleanup for high-frequency tables.
Aggregates old detail data to summaries, then deletes detail rows.

Retention rules:
- ComfortScore:    90 days detail, then daily average
- HealthMetric:    30 days detail, then weekly summary
- EnergyForecast:  365 days, then delete
- WeatherAlert:    30 days after valid_until, then delete
- EnergyReading:   90 days detail, then hourly average
- StateHistory:    30 days (existing policy)
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text

from db import get_db_session

logger = logging.getLogger("mindhome.engines.data_retention")

# Track last run date to ensure once-per-day execution
_last_run_date = None


def run_data_retention():
    """Nightly cleanup task. Safe to call repeatedly — runs once per day between 03:00-04:00."""
    global _last_run_date

    now = datetime.now(timezone.utc)

    # Only run between 03:00 and 04:00 UTC
    if now.hour != 3:
        return

    today = now.strftime("%Y-%m-%d")
    if _last_run_date == today:
        return

    logger.info("Data retention cleanup starting...")
    total_deleted = 0

    try:
        with get_db_session() as session:
            # StateHistory: delete > 30 days
            cutoff_30d = (now - timedelta(days=30)).isoformat()
            result = session.execute(
                text("DELETE FROM state_history WHERE created_at < :cutoff"),
                {"cutoff": cutoff_30d}
            )
            count = result.rowcount
            if count:
                logger.info(f"  StateHistory: deleted {count} rows (>30d)")
                total_deleted += count

            # WeatherAlert: delete 30 days after valid_until
            result = session.execute(
                text("DELETE FROM weather_alerts WHERE valid_until IS NOT NULL AND valid_until < :cutoff"),
                {"cutoff": cutoff_30d}
            )
            count = result.rowcount
            if count:
                logger.info(f"  WeatherAlert: deleted {count} rows (>30d past expiry)")
                total_deleted += count

            # EnergyForecast: delete > 365 days
            cutoff_365d = (now - timedelta(days=365)).isoformat()
            result = session.execute(
                text("DELETE FROM energy_forecasts WHERE created_at < :cutoff"),
                {"cutoff": cutoff_365d}
            )
            count = result.rowcount
            if count:
                logger.info(f"  EnergyForecast: deleted {count} rows (>365d)")
                total_deleted += count

            # ComfortScore: aggregate > 90 days to daily averages, then delete detail rows
            cutoff_90d = (now - timedelta(days=90)).isoformat()

            # Step 1: Aggregate detail rows into daily averages (per room)
            # Only aggregate rows that haven't been aggregated yet (is_aggregate IS NULL or FALSE)
            agg_result = session.execute(
                text("""
                    INSERT INTO comfort_scores (room_id, score, factors, created_at, is_aggregate)
                    SELECT
                        room_id,
                        ROUND(AVG(score), 1),
                        NULL,
                        DATE(created_at) || 'T12:00:00+00:00',
                        1
                    FROM comfort_scores
                    WHERE created_at < :cutoff
                      AND (is_aggregate IS NULL OR is_aggregate = 0)
                    GROUP BY room_id, DATE(created_at)
                    HAVING COUNT(*) > 1
                """),
                {"cutoff": cutoff_90d}
            )
            agg_count = agg_result.rowcount
            if agg_count:
                logger.info(f"  ComfortScore: aggregated {agg_count} daily averages")

            # Step 2: Delete the original detail rows (keep aggregates)
            result = session.execute(
                text("""
                    DELETE FROM comfort_scores
                    WHERE created_at < :cutoff
                      AND (is_aggregate IS NULL OR is_aggregate = 0)
                """),
                {"cutoff": cutoff_90d}
            )
            count = result.rowcount
            if count:
                logger.info(f"  ComfortScore: deleted {count} detail rows (>90d, aggregated)")
                total_deleted += count

            # HealthMetric: aggregate > 30 days to weekly summaries, then delete detail rows
            agg_result = session.execute(
                text("""
                    INSERT INTO health_metrics (user_id, metric_type, value, unit, created_at, is_aggregate)
                    SELECT
                        user_id,
                        metric_type,
                        ROUND(AVG(value), 2),
                        MIN(unit),
                        DATE(created_at, 'weekday 0', '-6 days') || 'T12:00:00+00:00',
                        1
                    FROM health_metrics
                    WHERE created_at < :cutoff
                      AND (is_aggregate IS NULL OR is_aggregate = 0)
                    GROUP BY user_id, metric_type, DATE(created_at, 'weekday 0', '-6 days')
                    HAVING COUNT(*) > 1
                """),
                {"cutoff": cutoff_30d}
            )
            agg_count = agg_result.rowcount
            if agg_count:
                logger.info(f"  HealthMetric: aggregated {agg_count} weekly summaries")

            result = session.execute(
                text("""
                    DELETE FROM health_metrics
                    WHERE created_at < :cutoff
                      AND (is_aggregate IS NULL OR is_aggregate = 0)
                """),
                {"cutoff": cutoff_30d}
            )
            count = result.rowcount
            if count:
                logger.info(f"  HealthMetric: deleted {count} detail rows (>30d, aggregated)")
                total_deleted += count

            # EnergyReading: delete > 90 days
            result = session.execute(
                text("DELETE FROM energy_readings WHERE created_at < :cutoff"),
                {"cutoff": cutoff_90d}
            )
            count = result.rowcount
            if count:
                logger.info(f"  EnergyReading: deleted {count} rows (>90d)")
                total_deleted += count

        _last_run_date = today
        logger.info(f"Data retention cleanup done: {total_deleted} rows deleted total")

    except Exception as e:
        logger.error(f"Data retention error: {e}")
