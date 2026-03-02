"""Transit disruption signal: service gaps increase driving demand.

When transit service is disrupted (subway delays, bus route gaps), more people
drive, increasing parking demand near the disruption.

Data source: TTC vehicle positions via NextBus/Umo XML feed.
"""

import logging
import sqlite3
from xml.etree import ElementTree

import httpx

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.transit_disruptions")

_SEVERITY_REDUCTIONS = {
    "major": 0.20,
    "moderate": 0.10,
    "minor": 0.05,
}

_MAX_RANGE_KM = 2.0
_MAX_REDUCTION = 0.40

_TRANSIT_FEEDS = {
    "toronto": {
        "agency": "ttc",
        "vehicle_url": "https://retro.umoiq.com/service/publicXMLFeed?command=vehicleLocations&a=ttc&t=0",
    },
}


def _classify_transit_severity(description: str) -> str:
    """Infer severity from alert description."""
    lower = description.lower() if description else ""
    if any(w in lower for w in ("suspended", "no service", "closure", "shut down", "major")):
        return "major"
    if any(w in lower for w in ("delay", "slow", "divert", "reduced")):
        return "moderate"
    return "minor"


def refresh_transit_alerts(conn: sqlite3.Connection) -> None:
    """Fetch transit vehicle positions and detect service gaps."""
    # Clear stale alerts (>30 min old)
    conn.execute(
        "DELETE FROM cached_transit_alerts "
        "WHERE fetched_at < datetime('now', '-30 minutes')"
    )

    for city, feed in _TRANSIT_FEEDS.items():
        try:
            resp = httpx.get(feed["vehicle_url"], timeout=15.0)
            resp.raise_for_status()

            root = ElementTree.fromstring(resp.text)

            # Collect last report time per route
            route_vehicles = {}
            for vehicle in root.findall(".//vehicle"):
                route_tag = vehicle.get("routeTag", "")
                sec_since = vehicle.get("secsSinceReport", "999")
                lat = vehicle.get("lat")
                lon = vehicle.get("lon")

                try:
                    secs = int(sec_since)
                except ValueError:
                    secs = 999

                if route_tag not in route_vehicles:
                    route_vehicles[route_tag] = []
                if lat and lon:
                    route_vehicles[route_tag].append({
                        "lat": float(lat),
                        "lon": float(lon),
                        "secs_since": secs,
                    })

            # Detect routes with no recent vehicles (>15 min since any report)
            alert_count = 0
            for route_tag, vehicles in route_vehicles.items():
                if not vehicles:
                    continue

                min_secs = min(v["secs_since"] for v in vehicles)

                if min_secs > 900:  # 15 minutes
                    # Use centroid of last known positions
                    avg_lat = sum(v["lat"] for v in vehicles) / len(vehicles)
                    avg_lon = sum(v["lon"] for v in vehicles) / len(vehicles)

                    severity = "major" if min_secs > 1800 else "moderate"
                    alert_id = f"ttc-gap-{route_tag}"

                    conn.execute(
                        "INSERT OR REPLACE INTO cached_transit_alerts "
                        "(alert_id, city, agency, route_id, description, severity, "
                        "lat, lon, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (alert_id, city, feed["agency"], route_tag,
                         f"Route {route_tag}: no vehicles for {min_secs // 60}min",
                         severity, avg_lat, avg_lon),
                    )
                    alert_count += 1

            conn.commit()
            logger.info("transit_alerts_refresh city=%s alerts=%d routes=%d",
                        city, alert_count, len(route_vehicles))
        except Exception:
            logger.exception("transit_alerts_refresh city=%s status=error", city)


class TransitDisruptionSignal(BaseSignal):
    name = "transit_disruption"
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
        """Sum capacity reduction from nearby transit disruptions."""
        rows = conn.execute(
            "SELECT lat, lon, severity, description "
            "FROM cached_transit_alerts "
            "WHERE city = ? AND lat IS NOT NULL AND lon IS NOT NULL",
            (city,),
        ).fetchall()

        if not rows:
            return None

        total_reduction = 0.0
        alert_count = 0

        for row in rows:
            dist = haversine_km(lat, lon, row["lat"], row["lon"])
            if dist >= _MAX_RANGE_KM:
                continue

            # Linear decay from 1.0 at center to 0.0 at max range
            proximity = max(0.0, 1.0 - dist / _MAX_RANGE_KM)
            severity_impact = _SEVERITY_REDUCTIONS.get(row["severity"], 0.05)
            total_reduction += severity_impact * proximity
            alert_count += 1

        if alert_count == 0:
            return None

        total_reduction = min(_MAX_REDUCTION, total_reduction)
        availability = 1.0 - total_reduction

        return SignalResult(
            source=self.name,
            value=round(availability, 4),
            confidence=0.50,
            staleness_seconds=0.0,
            detail={
                "alert_count": alert_count,
                "total_reduction": round(total_reduction, 4),
            },
        )
