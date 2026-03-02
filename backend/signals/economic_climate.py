"""Economic climate signal: macroeconomic conditions as slow-moving demand pressure.

High inflation reduces discretionary trips (more parking available).
A weak Canadian dollar (high USDCAD) boosts inbound tourism, filling
entertainment/tourist area parking.

Data source: cached_economic_indicators table populated by external refresh.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.economic_climate")

_NODE_SEARCH_RADIUS_KM = 1.0
_STALE_DAYS = 60

_PRESSURE_CAP = 0.10
_TOURISM_BOOST_CAP = 0.05
_TOURISM_DRAG_CAP = 0.03
_NEGLIGIBLE_THRESHOLD = 0.005

_VALUE_FLOOR = 0.90
_VALUE_CEILING = 1.10


def _has_nearby_entertainment(conn: sqlite3.Connection, city: str,
                              lat: float, lon: float) -> bool:
    """Check for entertainment/tourist demand nodes within search radius."""
    rows = conn.execute(
        "SELECT lat, lon FROM cached_demand_nodes "
        "WHERE city = ? AND category = 'entertainment'",
        (city,),
    ).fetchall()
    for row in rows:
        if haversine_km(lat, lon, row["lat"], row["lon"]) <= _NODE_SEARCH_RADIUS_KM:
            return True
    return False


class EconomicClimateSignal(BaseSignal):
    name = "economic_climate"
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
        # Read indicators
        cpi_row = conn.execute(
            "SELECT value, fetched_at FROM cached_economic_indicators "
            "WHERE indicator = 'cpi_yoy_pct'",
        ).fetchone()
        usdcad_row = conn.execute(
            "SELECT value, fetched_at FROM cached_economic_indicators "
            "WHERE indicator = 'usdcad_rate'",
        ).fetchone()

        if not cpi_row and not usdcad_row:
            return None

        # Staleness check: if oldest fetched_at > 60 days, bail
        stale_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_STALE_DAYS)
        ).strftime("%Y-%m-%d %H:%M:%S")

        for row in (cpi_row, usdcad_row):
            if row and row["fetched_at"] < stale_cutoff:
                return None

        cpi = cpi_row["value"] if cpi_row else 2.0
        usdcad = usdcad_row["value"] if usdcad_row else 1.35

        # Configurable CPI threshold
        cpi_threshold = get_signal_param(
            conn, "economic_climate", "cpi_threshold", 3.0,
        )

        # Consumer pressure from inflation
        pressure = 0.0
        if cpi > cpi_threshold:
            pressure = 0.03 * (cpi - cpi_threshold)
            pressure = min(pressure, _PRESSURE_CAP)

        # Tourism effect from exchange rate
        tourism_boost = 0.0
        if usdcad > 1.40:
            tourism_boost = (usdcad - 1.40) * 0.50
            tourism_boost = min(tourism_boost, _TOURISM_BOOST_CAP)
        elif usdcad < 1.25:
            # Strong CAD = tourism drag (fewer visitors)
            tourism_drag = (1.25 - usdcad) * 0.30
            tourism_drag = min(tourism_drag, _TOURISM_DRAG_CAP)
            # Drag means less tourism -> more availability -> acts like pressure
            pressure += tourism_drag

        # Proximity to entertainment/tourist nodes
        near_tourist = _has_nearby_entertainment(conn, city, lat, lon)

        if near_tourist:
            value = 1.0 + pressure - tourism_boost
        else:
            value = 1.0 + pressure

        # Clamp
        value = max(_VALUE_FLOOR, min(_VALUE_CEILING, value))

        # Negligible check
        if abs(value - 1.0) < _NEGLIGIBLE_THRESHOLD:
            return None

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.40,
            detail={
                "cpi_yoy_pct": cpi,
                "usdcad_rate": usdcad,
                "pressure": round(pressure, 4),
                "tourism_boost": round(tourism_boost, 4),
                "near_tourist_area": near_tourist,
            },
        )
