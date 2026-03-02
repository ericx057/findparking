"""Air quality signal: poor AQI reduces outdoor trips, increasing parking availability.

People stay home or reduce discretionary travel when air quality is poor.
This is an *inverse* signal -- bad air INCREASES parking availability.

Data source: cached_air_quality table populated by external refresh job.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.air_quality")

_STALE_THRESHOLD_SECONDS = 7200  # 2 hours


class AirQualitySignal(BaseSignal):
    name = "air_quality"
    base_weight = 0.03

    def evaluate(
        self,
        conn: sqlite3.Connection,
        lot_id: str,
        lat: float,
        lon: float,
        city: str,
        capacity: int,
        occupancy: int,
    ) -> SignalResult | None:
        row = conn.execute(
            "SELECT us_aqi, observed_at FROM cached_air_quality WHERE city = ?",
            (city,),
        ).fetchone()

        if row is None or row["us_aqi"] is None:
            return None

        # Staleness check
        try:
            observed = datetime.strptime(row["observed_at"], "%Y-%m-%d %H:%M:%S")
            observed = observed.replace(tzinfo=timezone.utc)
            staleness = (datetime.now(timezone.utc) - observed).total_seconds()
        except (ValueError, TypeError):
            return None

        if staleness > _STALE_THRESHOLD_SECONDS:
            return None

        aqi = row["us_aqi"]

        # Configurable thresholds
        threshold_usg = get_signal_param(conn, self.name, "aqi_threshold_usg", 100.0)
        threshold_unhealthy = get_signal_param(conn, self.name, "aqi_threshold_unhealthy", 150.0)
        threshold_very_unhealthy = get_signal_param(conn, self.name, "aqi_threshold_very_unhealthy", 200.0)
        threshold_hazardous = get_signal_param(conn, self.name, "aqi_threshold_hazardous", 300.0)

        if aqi < threshold_usg:
            return None

        if aqi >= threshold_hazardous:
            value = 1.15
        elif aqi >= threshold_very_unhealthy:
            value = 1.10
        elif aqi >= threshold_unhealthy:
            value = 1.06
        else:
            value = 1.03

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.55,
            staleness_seconds=staleness,
            detail={
                "us_aqi": aqi,
                "aqi_category": self._aqi_category(aqi),
            },
        )

    @staticmethod
    def _aqi_category(aqi: int) -> str:
        if aqi <= 50:
            return "good"
        if aqi <= 100:
            return "moderate"
        if aqi <= 150:
            return "usg"
        if aqi <= 200:
            return "unhealthy"
        if aqi <= 300:
            return "very_unhealthy"
        return "hazardous"
