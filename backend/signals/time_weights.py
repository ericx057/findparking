"""Time weights signal: reads precomputed time-of-day/day-of-week patterns."""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.prediction import get_historical_prediction
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.time_weights")


class TimeWeightsSignal(BaseSignal):
    name = "time_weights"
    base_weight = 0.10

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
        """Look up precomputed weight for current hour+day, fall back to rolling avg."""
        now = datetime.now(timezone.utc)
        hour = now.hour
        day_of_week = now.weekday()

        # Try precomputed weights first
        row = conn.execute(
            "SELECT weight FROM time_of_day_weights "
            "WHERE lot_id = ? AND hour = ? AND day_of_week = ?",
            (lot_id, hour, day_of_week),
        ).fetchone()

        if row is not None:
            weight = row["weight"]
            return SignalResult(
                source=self.name,
                value=max(0.0, min(1.0, weight)),
                confidence=0.55,
                staleness_seconds=0.0,
                detail={"source": "precomputed", "hour": hour, "day": day_of_week},
            )

        # Fallback: 3-day rolling average from occupancy_snapshots
        prediction = get_historical_prediction(conn, lot_id, hour)
        if prediction is not None:
            return SignalResult(
                source=self.name,
                value=max(0.0, min(1.0, prediction)),
                confidence=0.45,
                staleness_seconds=0.0,
                detail={"source": "rolling_avg", "hour": hour},
            )

        return None
