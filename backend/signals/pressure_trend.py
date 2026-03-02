"""Pressure trend signal: barometric pressure changes predict weather shifts.

A rapid pressure drop signals an approaching storm front. People cancel trips
before rain starts -- this captures ANTICIPATION that the weather signal misses.
A rapid rise means clearing weather, releasing pent-up demand.

Data source: cached_pressure_history table populated by weather refresh.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.pressure_trend")

_MIN_READINGS = 3
_LOOKBACK_HOURS = 6
_TREND_WINDOW_HOURS = 3


class PressureTrendSignal(BaseSignal):
    name = "pressure_trend"
    base_weight = 0.02

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
        now = datetime.now(timezone.utc)
        lookback = (now - timedelta(hours=_LOOKBACK_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

        rows = conn.execute(
            "SELECT observed_at, pressure_hpa FROM cached_pressure_history "
            "WHERE city = ? AND observed_at >= ? ORDER BY observed_at ASC",
            (city, lookback),
        ).fetchall()

        if len(rows) < _MIN_READINGS:
            return None

        # Latest reading
        latest_pressure = rows[-1]["pressure_hpa"]
        latest_time_str = rows[-1]["observed_at"]

        # Find reading closest to 3 hours ago
        target_time = now - timedelta(hours=_TREND_WINDOW_HOURS)
        target_str = target_time.strftime("%Y-%m-%d %H:%M:%S")

        older_pressure = None
        for row in rows:
            if row["observed_at"] <= target_str:
                older_pressure = row["pressure_hpa"]

        if older_pressure is None:
            # Use earliest available reading
            older_pressure = rows[0]["pressure_hpa"]

        delta = latest_pressure - older_pressure

        # Configurable thresholds
        severe_drop = get_signal_param(conn, self.name, "rapid_drop_hpa_per_3h", 6.0)
        moderate_drop = get_signal_param(conn, self.name, "moderate_drop_hpa_per_3h", 4.0)
        moderate_rise = get_signal_param(conn, self.name, "moderate_rise_hpa_per_3h", 4.0)
        severe_rise = get_signal_param(conn, self.name, "rapid_rise_hpa_per_3h", 6.0)

        if delta <= -severe_drop:
            value = 1.08
        elif delta <= -moderate_drop:
            value = 1.04
        elif delta >= severe_rise:
            value = 0.93
        elif delta >= moderate_rise:
            value = 0.96
        else:
            return None

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.45,
            staleness_seconds=0.0,
            detail={
                "pressure_delta_hpa": round(delta, 2),
                "latest_hpa": latest_pressure,
                "readings_count": len(rows),
                "trend": "dropping" if delta < 0 else "rising",
            },
        )
