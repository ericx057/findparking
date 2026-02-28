"""Road disruptions signal: proximity-based capacity reduction from road closures."""

import logging
import sqlite3

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.road_disruptions")


_SEVERITY_IMPACTS = {
    "minor": 0.05,
    "moderate": 0.12,
    "major": 0.25,
}


def severity_impact(severity: str) -> float:
    """Return capacity reduction fraction for a given severity level."""
    return _SEVERITY_IMPACTS.get(severity, 0.05)


def proximity_decay(distance_km: float, disruption_radius_km: float) -> float:
    """Linear decay from 1.0 at center to 0.0 at 2x the disruption radius."""
    max_range = disruption_radius_km * 2
    if distance_km >= max_range:
        return 0.0
    return max(0.0, 1.0 - distance_km / max_range)


class RoadDisruptionsSignal(BaseSignal):
    name = "road_disruptions"
    base_weight = 0.05

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
        """Sum capacity reduction from nearby road disruptions."""
        rows = conn.execute(
            "SELECT lat, lon, radius_km, severity, description "
            "FROM cached_road_disruptions "
            "WHERE city = ?",
            (city,),
        ).fetchall()

        if not rows:
            return None

        total_reduction = 0.0
        disruption_count = 0

        for row in rows:
            dist = haversine_km(lat, lon, row["lat"], row["lon"])
            prox = proximity_decay(dist, row["radius_km"])
            if prox <= 0:
                continue

            impact = severity_impact(row["severity"])
            total_reduction += impact * prox
            disruption_count += 1

        if disruption_count == 0:
            return None

        # Cap total reduction at 60%
        total_reduction = min(0.60, total_reduction)
        availability = 1.0 - total_reduction

        return SignalResult(
            source=self.name,
            value=round(availability, 4),
            confidence=0.60,
            staleness_seconds=0.0,
            detail={
                "disruption_count": disruption_count,
                "total_reduction": round(total_reduction, 4),
            },
        )
