"""Demand heatmap signal: thermodynamic model of parking pressure.

Models parking demand as a 2D scalar field using Gaussian heat sources.
Each demand node (transit hub, commercial core, retail zone, entertainment
district) contributes a Gaussian-weighted term whose intensity varies by
hour-of-day and day-of-week.  During peak hours the Gaussian sigma expands,
modelling demand diffusing outward as prime spots fill (the heat equation
analogy: dT/dt = alpha * laplacian(T) + S(x,y,t)).

The raw demand temperature is normalised via Michaelis-Menten saturation
to produce an occupancy fraction, then inverted to availability.
"""

import logging
import math
import sqlite3
import time as _time
from datetime import datetime, timezone

import httpx

from backend.demand_nodes import (
    CITY_TIMEZONES,
    DAY_SCALES,
    DEFAULT_TZ,
    DEMAND_NODES,
    DEMAND_SCALE,
    PEAK_EXPANSION,
    TIME_PROFILES,
)
from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.demand_heatmap")

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ---------------------------------------------------------------------------
# Pure math functions
# ---------------------------------------------------------------------------

def gaussian_kernel(distance_km: float, sigma_km: float) -> float:
    """Evaluate Gaussian kernel: exp(-d^2 / (2 * sigma^2)).

    Returns 1.0 at distance 0, decays to ~0.01 at 3*sigma.
    """
    if sigma_km <= 0:
        return 0.0
    return math.exp(-(distance_km ** 2) / (2.0 * sigma_km ** 2))


def effective_sigma(sigma_base: float, intensity: float, peak_expansion: float) -> float:
    """Compute time-expanded sigma.

    sigma(t) = sigma_base * (1 + peak_expansion * intensity)

    At zero intensity sigma equals sigma_base.
    At full intensity sigma grows by peak_expansion fraction,
    modelling demand diffusing outward as prime spots fill.
    """
    return sigma_base * (1.0 + peak_expansion * intensity)


def node_intensity(hour: int, day_of_week: int, category: str) -> float:
    """Time-varying intensity for a demand node category.

    Returns hour_profile * day_scale.
    """
    hourly = TIME_PROFILES.get(category, TIME_PROFILES["retail"])
    daily = DAY_SCALES.get(category, DAY_SCALES["retail"])
    return hourly[hour] * daily[day_of_week]


def demand_field_at(
    lat: float,
    lon: float,
    nodes: list[dict],
    hour: int,
    day_of_week: int,
    peak_expansion: float = PEAK_EXPANSION,
) -> float:
    """Evaluate the 2D demand field T(x,y,t) at a given point.

    T = SUM_i [ A_i * I_i(t) * G(d_i, sigma_i(t)) ]

    Each node contributes a Gaussian-weighted amount based on distance,
    amplitude, and time-varying intensity.
    """
    total = 0.0
    for node in nodes:
        intensity = node_intensity(hour, day_of_week, node["category"])
        if intensity < 0.01:
            continue

        sigma = effective_sigma(node["sigma_km"], intensity, peak_expansion)
        dist = haversine_km(lat, lon, node["lat"], node["lon"])

        # Early cutoff: beyond 4*sigma the Gaussian contribution < 0.0003
        if dist > 4.0 * sigma:
            continue

        g = gaussian_kernel(dist, sigma)
        total += node["amplitude"] * intensity * g

    return total


def demand_gradient_at(
    lat: float,
    lon: float,
    nodes: list[dict],
    hour: int,
    day_of_week: int,
    peak_expansion: float = PEAK_EXPANSION,
) -> tuple[float, float]:
    """Compute gradient of the demand field at a point.

    Returns (dT/dx_km, dT/dy_km) where x is east and y is north.
    The gradient points in the direction of increasing demand.
    Negate it to find the direction toward available parking.
    """
    grad_x = 0.0
    grad_y = 0.0

    for node in nodes:
        intensity = node_intensity(hour, day_of_week, node["category"])
        if intensity < 0.01:
            continue

        sigma = effective_sigma(node["sigma_km"], intensity, peak_expansion)
        dist = haversine_km(lat, lon, node["lat"], node["lon"])

        if dist > 4.0 * sigma:
            continue

        g = gaussian_kernel(dist, sigma)

        # Approximate km offsets (equirectangular)
        dy = (lat - node["lat"]) * 111.32
        dx = (lon - node["lon"]) * 111.32 * math.cos(math.radians(lat))

        coeff = node["amplitude"] * intensity * g / (sigma ** 2)
        grad_x += -coeff * dx
        grad_y += -coeff * dy

    return grad_x, grad_y


def normalize_demand(raw_demand: float, demand_scale: float = DEMAND_SCALE) -> float:
    """Convert raw demand temperature to occupancy fraction [0, 1].

    Uses Michaelis-Menten saturation: f(T) = T / (T + k)

    T = 0     -> 0.0  (no demand)
    T = k     -> 0.5  (half saturation)
    T -> inf  -> 1.0  (full saturation)
    """
    if raw_demand <= 0:
        return 0.0
    return raw_demand / (raw_demand + demand_scale)


# ---------------------------------------------------------------------------
# Signal class
# ---------------------------------------------------------------------------

class DemandHeatmapSignal(BaseSignal):
    name = "demand_heatmap"
    base_weight = 0.30

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
        """Evaluate thermodynamic demand field at the lot's location."""
        nodes = self._gather_nodes(conn, city)
        if not nodes:
            return None

        local_tz = CITY_TIMEZONES.get(city, DEFAULT_TZ)
        now_local = datetime.now(timezone.utc).astimezone(local_tz)
        hour = now_local.hour
        day_of_week = now_local.weekday()

        raw_demand = demand_field_at(lat, lon, nodes, hour, day_of_week)

        occupancy_estimate = normalize_demand(raw_demand, DEMAND_SCALE)
        occupancy_estimate = min(0.95, occupancy_estimate)

        availability = max(0.05, min(0.95, 1.0 - occupancy_estimate))

        has_osm = any(n.get("source") == "osm_poi" for n in nodes)
        confidence = self._compute_confidence(conn, city, has_osm)

        return SignalResult(
            source=self.name,
            value=round(availability, 4),
            confidence=confidence,
            staleness_seconds=0.0,
            detail={
                "raw_demand": round(raw_demand, 4),
                "occupancy_estimate": round(occupancy_estimate, 4),
                "hour": hour,
                "day_of_week": day_of_week,
                "node_count": len(nodes),
                "has_osm_data": has_osm,
            },
        )

    def _gather_nodes(self, conn: sqlite3.Connection, city: str) -> list[dict]:
        """Merge hardcoded demand nodes with cached OSM POI nodes."""
        hardcoded = DEMAND_NODES.get(city, [])
        if not hardcoded:
            return []

        nodes = [{**n, "source": "hardcoded"} for n in hardcoded]

        rows = conn.execute(
            "SELECT lat, lon, amplitude, sigma_km, category "
            "FROM cached_demand_nodes "
            "WHERE city = ? AND source = 'osm_poi'",
            (city,),
        ).fetchall()

        for row in rows:
            nodes.append({
                "lat": row["lat"],
                "lon": row["lon"],
                "amplitude": row["amplitude"],
                "sigma_km": row["sigma_km"],
                "category": row["category"],
                "source": "osm_poi",
            })

        return nodes

    def _compute_confidence(
        self, conn: sqlite3.Connection, city: str, has_osm: bool,
    ) -> float:
        """Confidence based on data richness.

        With hardcoded + fresh OSM: 0.60
        With only hardcoded: 0.45
        With stale OSM (>14 days): 0.50
        """
        if not has_osm:
            return 0.45

        row = conn.execute(
            "SELECT MIN(fetched_at) as oldest "
            "FROM cached_demand_nodes "
            "WHERE city = ? AND source = 'osm_poi'",
            (city,),
        ).fetchone()

        if row is None or row["oldest"] is None:
            return 0.45

        try:
            oldest = datetime.strptime(row["oldest"], "%Y-%m-%d %H:%M:%S")
            oldest = oldest.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - oldest).total_seconds() / 86400
            if age_days > 14:
                return 0.50
        except (ValueError, TypeError):
            return 0.45

        return 0.60


# ---------------------------------------------------------------------------
# OSM POI refresh
# ---------------------------------------------------------------------------

# Overpass queries by demand category
_POI_QUERIES = {
    "transit": (
        'node["railway"="station"]({bbox});'
        'node["station"="subway"]({bbox});'
        'node["amenity"="bus_station"]({bbox});'
    ),
    "commercial": (
        'node["office"]({bbox});'
        'way["office"]({bbox});'
    ),
    "retail": (
        'node["shop"]({bbox});'
        'way["shop"]({bbox});'
    ),
    "entertainment": (
        'node["amenity"~"restaurant|cafe|bar|pub|theatre|cinema|nightclub"]({bbox});'
    ),
}

# Spatial binning: ~500m grid cells
_GRID_SIZE_LAT = 0.0045   # ~500m
_GRID_SIZE_LON = 0.0060   # ~500m at mid-latitudes

# Minimum POIs in a cell to generate a demand node
_MIN_COUNTS = {
    "transit": 1,
    "commercial": 5,
    "retail": 5,
    "entertainment": 5,
}

# POI count at which amplitude reaches 1.0
_SATURATION_COUNTS = {
    "transit": 3,
    "commercial": 30,
    "retail": 40,
    "entertainment": 25,
}

# Base sigma per category for OSM-derived nodes
_OSM_SIGMA = {
    "transit": 0.45,
    "commercial": 0.35,
    "retail": 0.30,
    "entertainment": 0.25,
}


def _bin_pois_to_nodes(
    elements: list[dict],
    city: str,
    category: str,
    bounds: dict,
) -> list[dict]:
    """Bin POI elements into grid cells and create demand nodes."""
    # Gather coordinates
    points = []
    for elem in elements:
        if elem.get("type") == "node":
            lat = elem.get("lat")
            lon = elem.get("lon")
        else:
            center = elem.get("center", {})
            lat = center.get("lat")
            lon = center.get("lon")
        if lat is not None and lon is not None:
            points.append((lat, lon))

    if not points:
        return []

    # Bin into grid cells
    cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lat, lon in points:
        row = int((lat - bounds["lat_min"]) / _GRID_SIZE_LAT)
        col = int((lon - bounds["lon_min"]) / _GRID_SIZE_LON)
        cells.setdefault((row, col), []).append((lat, lon))

    min_count = _MIN_COUNTS.get(category, 5)
    sat_count = _SATURATION_COUNTS.get(category, 30)
    sigma = _OSM_SIGMA.get(category, 0.3)

    nodes = []
    for (row, col), cell_points in cells.items():
        if len(cell_points) < min_count:
            continue

        # Centroid
        avg_lat = sum(p[0] for p in cell_points) / len(cell_points)
        avg_lon = sum(p[1] for p in cell_points) / len(cell_points)

        amplitude = min(1.0, len(cell_points) / sat_count)

        nodes.append({
            "node_id": f"osm-{city}-{category}-{row}-{col}",
            "lat": round(avg_lat, 6),
            "lon": round(avg_lon, 6),
            "amplitude": round(amplitude, 3),
            "sigma_km": sigma,
            "name": f"{category} cluster ({len(cell_points)} POIs)",
        })

    return nodes


def refresh_osm_demand_nodes(conn: sqlite3.Connection) -> None:
    """Fetch POI density from Overpass and generate demand nodes per city."""
    from cv_pipeline.city_config import CITIES

    for city_name, city_cfg in CITIES.items():
        bounds = city_cfg["bounds"]
        bbox = f"{bounds['lat_min']},{bounds['lon_min']},{bounds['lat_max']},{bounds['lon_max']}"

        conn.execute(
            "DELETE FROM cached_demand_nodes WHERE city = ? AND source = 'osm_poi'",
            (city_name,),
        )

        total_nodes = 0
        for category, query_fragment in _POI_QUERIES.items():
            try:
                query = f"[out:json][timeout:60];({query_fragment.format(bbox=bbox)});out center;"
                resp = httpx.post(
                    _OVERPASS_URL,
                    data={"data": query},
                    timeout=70,
                )
                resp.raise_for_status()
                elements = resp.json().get("elements", [])

                nodes = _bin_pois_to_nodes(elements, city_name, category, bounds)

                for node in nodes:
                    conn.execute(
                        "INSERT OR REPLACE INTO cached_demand_nodes "
                        "(node_id, city, source, category, lat, lon, amplitude, sigma_km, name, fetched_at) "
                        "VALUES (?, ?, 'osm_poi', ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (node["node_id"], city_name, category,
                         node["lat"], node["lon"], node["amplitude"],
                         node["sigma_km"], node.get("name")),
                    )
                    total_nodes += 1

                _time.sleep(2)  # rate-limit courtesy
            except Exception:
                logger.exception(
                    "demand_node_refresh city=%s category=%s failed",
                    city_name, category,
                )

        conn.commit()
        logger.info(
            "demand_node_refresh city=%s nodes=%d",
            city_name, total_nodes,
        )
