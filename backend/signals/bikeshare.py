"""Bikeshare signal: dock fill levels as a foot traffic proxy.

High bike usage (many bikes checked out) near a parking lot correlates with
high foot traffic, suggesting increased parking demand.  Conversely, full
docks (bikes returned) imply lower activity.

Data source: Bike Share Toronto GBFS (General Bikeshare Feed Specification).
"""

import logging
import math
import sqlite3
import time as _time

import httpx

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.bikeshare")

_SEARCH_RADIUS_KM = 0.5
_MAX_AVAILABILITY_REDUCTION = 0.4
_STALE_THRESHOLD_SECONDS = 1800  # 30 minutes

_BIKESHARE_FEEDS = {
    "toronto": {
        "info": "https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_information",
        "status": "https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_status",
    },
}


def refresh_bikeshare(conn: sqlite3.Connection) -> None:
    """Fetch station info + status from GBFS and cache."""
    for city, urls in _BIKESHARE_FEEDS.items():
        try:
            info_resp = httpx.get(urls["info"], timeout=10.0)
            info_resp.raise_for_status()
            info_data = info_resp.json()

            status_resp = httpx.get(urls["status"], timeout=10.0)
            status_resp.raise_for_status()
            status_data = status_resp.json()

            # Build station info lookup
            stations_info = {}
            for stn in info_data.get("data", {}).get("stations", []):
                sid = str(stn.get("station_id", ""))
                if sid:
                    stations_info[sid] = stn

            # Merge status with info and upsert
            count = 0
            for stn in status_data.get("data", {}).get("stations", []):
                sid = str(stn.get("station_id", ""))
                info = stations_info.get(sid)
                if not info:
                    continue

                lat = info.get("lat")
                lon = info.get("lon")
                cap = info.get("capacity", 0)
                if lat is None or lon is None or cap <= 0:
                    continue

                conn.execute(
                    "INSERT OR REPLACE INTO cached_bikeshare_stations "
                    "(station_id, city, name, lat, lon, capacity, "
                    "num_bikes_available, num_docks_available, last_reported, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (
                        sid, city, info.get("name", ""),
                        lat, lon, cap,
                        stn.get("num_bikes_available", 0),
                        stn.get("num_docks_available", 0),
                        stn.get("last_reported", int(_time.time())),
                    ),
                )
                count += 1

            conn.commit()
            logger.info("bikeshare_refresh city=%s stations=%d", city, count)
        except Exception:
            logger.exception("bikeshare_refresh city=%s status=error", city)


class BikeshareSignal(BaseSignal):
    name = "bikeshare"
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
        """Evaluate nearby bikeshare dock fill as foot traffic proxy."""
        if city not in _BIKESHARE_FEEDS:
            return None

        # Bounding-box pre-filter (~0.5 km margin)
        lat_margin = _SEARCH_RADIUS_KM / 111.0
        lon_margin = _SEARCH_RADIUS_KM / (111.0 * math.cos(math.radians(lat)))

        rows = conn.execute(
            "SELECT lat, lon, capacity, num_bikes_available, last_reported "
            "FROM cached_bikeshare_stations "
            "WHERE city = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (city, lat - lat_margin, lat + lat_margin,
             lon - lon_margin, lon + lon_margin),
        ).fetchall()

        if not rows:
            return None

        # Filter by exact haversine distance and aggregate
        total_bikes = 0
        total_capacity = 0
        min_last_reported = None
        now_epoch = int(_time.time())

        for row in rows:
            dist = haversine_km(lat, lon, row["lat"], row["lon"])
            if dist > _SEARCH_RADIUS_KM:
                continue

            total_bikes += row["num_bikes_available"]
            total_capacity += row["capacity"]

            if min_last_reported is None or row["last_reported"] < min_last_reported:
                min_last_reported = row["last_reported"]

        if total_capacity == 0:
            return None

        fill_ratio = total_bikes / total_capacity
        value = 1.0 - (fill_ratio * _MAX_AVAILABILITY_REDUCTION)

        # Staleness-based confidence
        staleness = now_epoch - (min_last_reported or now_epoch)
        if staleness > _STALE_THRESHOLD_SECONDS:
            confidence = 0.30
        else:
            # Linear decay from 0.55 to 0.35 over 30 min
            confidence = 0.55 - 0.20 * (staleness / _STALE_THRESHOLD_SECONDS)

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=round(confidence, 4),
            staleness_seconds=float(staleness),
            detail={
                "fill_ratio": round(fill_ratio, 4),
                "total_bikes": total_bikes,
                "total_capacity": total_capacity,
                "stations_nearby": sum(
                    1 for r in rows
                    if haversine_km(lat, lon, r["lat"], r["lon"]) <= _SEARCH_RADIUS_KM
                ),
            },
        )
