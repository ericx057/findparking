"""Heuristic baseline signal: time/day/lot-type occupancy estimates.

Provides a reasonable availability estimate when no camera data exists.
Uses built-in curves based on lot classification (mall, downtown, generic),
hour of day, and weekday vs weekend patterns.
"""

import sqlite3
from datetime import datetime, timezone

from backend.signals import BaseSignal, SignalResult


# --- Hour-indexed occupancy curves (0-23), values = fraction occupied ---

_MALL_HOURS = [
    #  0     1     2     3     4     5     6     7     8     9
    0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.06, 0.10, 0.18, 0.32,
    # 10    11    12    13    14    15    16    17    18    19
    0.50, 0.65, 0.75, 0.78, 0.82, 0.82, 0.80, 0.78, 0.70, 0.58,
    # 20    21    22    23
    0.40, 0.18, 0.08, 0.04,
]

_DOWNTOWN_HOURS = [
    #  0     1     2     3     4     5     6     7     8     9
    0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.08, 0.35, 0.70, 0.88,
    # 10    11    12    13    14    15    16    17    18    19
    0.92, 0.90, 0.82, 0.88, 0.92, 0.90, 0.85, 0.55, 0.25, 0.12,
    # 20    21    22    23
    0.06, 0.05, 0.04, 0.04,
]

_GENERIC_HOURS = [
    #  0     1     2     3     4     5     6     7     8     9
    0.10, 0.08, 0.07, 0.07, 0.07, 0.08, 0.12, 0.20, 0.35, 0.45,
    # 10    11    12    13    14    15    16    17    18    19
    0.52, 0.55, 0.55, 0.52, 0.50, 0.52, 0.50, 0.48, 0.42, 0.35,
    # 20    21    22    23
    0.25, 0.18, 0.14, 0.11,
]

_CURVES = {
    "mall": _MALL_HOURS,
    "downtown": _DOWNTOWN_HOURS,
    "generic": _GENERIC_HOURS,
}

# Day-of-week multipliers. Python weekday(): Mon=0 .. Sun=6
_DAY_SCALES = {
    "mall":     [0.75, 0.75, 0.75, 0.78, 0.85, 1.10, 1.05],
    "downtown": [1.00, 1.00, 1.00, 1.00, 0.95, 0.40, 0.35],
    "generic":  [0.85, 0.85, 0.85, 0.85, 0.88, 0.90, 0.88],
}


def _classify_lot(fare_type: str, capacity: int) -> str:
    """Classify a lot based on fare type and capacity."""
    if capacity >= 1000:
        return "mall"
    if fare_type == "free" and capacity >= 500:
        return "mall"
    if fare_type in ("hourly", "daily", "flat"):
        return "downtown"
    return "generic"


def _hour_occupancy(hour: int, lot_type: str) -> float:
    """Estimated fraction occupied for this hour (0.0-1.0)."""
    return _CURVES[lot_type][hour]


def _day_scale(day_of_week: int, lot_type: str) -> float:
    """Multiplier for day of week. day_of_week: 0=Monday .. 6=Sunday."""
    return _DAY_SCALES[lot_type][day_of_week]


class HeuristicBaselineSignal(BaseSignal):
    name = "heuristic_baseline"
    base_weight = 0.15

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
        # Look up fare_type from DB
        row = conn.execute(
            "SELECT fare_type FROM parking_lots WHERE lot_id = ?", (lot_id,)
        ).fetchone()
        if row is None:
            return None

        fare_type = row["fare_type"] or "free"
        lot_type = _classify_lot(fare_type, capacity)

        now = datetime.now(timezone.utc)
        hour = now.hour
        day_of_week = now.weekday()

        occupancy_estimate = _hour_occupancy(hour, lot_type) * _day_scale(day_of_week, lot_type)
        occupancy_estimate = min(0.95, occupancy_estimate)

        availability = 1.0 - occupancy_estimate

        return SignalResult(
            source=self.name,
            value=round(max(0.05, availability), 4),
            confidence=0.35,
            staleness_seconds=0.0,
            detail={
                "lot_type": lot_type,
                "hour": hour,
                "day_of_week": day_of_week,
                "occupancy_estimate": round(occupancy_estimate, 4),
            },
        )
