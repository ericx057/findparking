"""Construction proximity signal: nearby road construction alters lot accessibility.

Active construction reduces the number of people attempting to reach a lot,
increasing its availability. Effects decay exponentially with distance
(half-life 300m).

Data source: cached_construction table populated by external refresh job.
"""

import json
import logging
import math
import sqlite3

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.construction_proximity")

_SEARCH_RADIUS_KM = 1.0
_DEFAULT_HALF_LIFE_KM = 0.3
_MAX_AMPLITUDE = 0.15
_MAX_TOTAL_IMPACT = 0.25
_LN2 = 0.693147


def _min_distance_to_vertices(lat: float, lon: float, coords_json: str) -> float | None:
    """Minimum haversine distance from point to any vertex in a coordinate list.

    coords_json is a JSON array of [lon, lat] pairs (GeoJSON order).
    """
    try:
        coords = json.loads(coords_json)
    except (json.JSONDecodeError, TypeError):
        return None

    if not coords:
        return None

    min_dist = float("inf")
    for coord in coords:
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            continue
        c_lon, c_lat = coord[0], coord[1]
        dist = haversine_km(lat, lon, c_lat, c_lon)
        if dist < min_dist:
            min_dist = dist

    return min_dist if min_dist < float("inf") else None


class ConstructionProximitySignal(BaseSignal):
    name = "construction_proximity"
    base_weight = 0.04

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
        # Bounding box pre-filter
        lat_margin = _SEARCH_RADIUS_KM / 111.0
        lon_margin = _SEARCH_RADIUS_KM / (111.0 * max(math.cos(math.radians(lat)), 0.01))

        rows = conn.execute(
            "SELECT project_id, lat, lon, geometry_type, geometry_json "
            "FROM cached_construction "
            "WHERE city = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (city, lat - lat_margin, lat + lat_margin,
             lon - lon_margin, lon + lon_margin),
        ).fetchall()

        if not rows:
            return None

        half_life = get_signal_param(conn, self.name, "half_life_km", _DEFAULT_HALF_LIFE_KM)
        amplitude = get_signal_param(conn, self.name, "amplitude", _MAX_AMPLITUDE)

        total_impact = 0.0
        project_count = 0

        for row in rows:
            # Compute distance
            if row["geometry_type"] == "line" and row["geometry_json"]:
                dist = _min_distance_to_vertices(lat, lon, row["geometry_json"])
                if dist is None:
                    dist = haversine_km(lat, lon, row["lat"], row["lon"])
            else:
                dist = haversine_km(lat, lon, row["lat"], row["lon"])

            if dist > _SEARCH_RADIUS_KM:
                continue

            # Exponential decay: impact = amplitude * exp(-ln2 * dist / half_life)
            impact = amplitude * math.exp(-_LN2 * dist / half_life)
            total_impact += impact
            project_count += 1

        if project_count == 0:
            return None

        # Cap total impact
        total_impact = min(total_impact, _MAX_TOTAL_IMPACT)

        value = 1.0 + total_impact

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.50,
            staleness_seconds=0.0,
            detail={
                "projects_nearby": project_count,
                "total_impact": round(total_impact, 4),
            },
        )
