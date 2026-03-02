"""Sun position signal: daylight and golden hour effects on parking demand.

Parking activity is subtly affected by solar position:
- Night: slightly reduced demand in non-residential areas
- Golden hour (1h before sunset): increased demand near entertainment areas
- Civil twilight: moderate transition period

Data source: sunrise-sunset.org API.
"""

import logging
import sqlite3
from datetime import datetime, timezone

import httpx

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.sun_position")

_CITY_COORDS = {
    "toronto": (43.6532, -79.3832),
    "waterloo": (43.4643, -80.5204),
    "vancouver": (49.2827, -123.1207),
}

_ENTERTAINMENT_SEARCH_RADIUS_KM = 0.5


def refresh_sun_times(conn: sqlite3.Connection) -> None:
    """Fetch today's sunrise/sunset for each city from sunrise-sunset.org."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for city, (lat, lon) in _CITY_COORDS.items():
        try:
            resp = httpx.get(
                "https://api.sunrise-sunset.org/json",
                params={"lat": lat, "lng": lon, "formatted": 0, "date": today},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "OK":
                logger.warning("sun_times_refresh city=%s status=%s", city, data.get("status"))
                continue

            results = data.get("results", {})
            conn.execute(
                "INSERT OR REPLACE INTO cached_sun_times "
                "(city, date, sunrise, sunset, civil_twilight_begin, "
                "civil_twilight_end, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    city, today,
                    results.get("sunrise", ""),
                    results.get("sunset", ""),
                    results.get("civil_twilight_begin", ""),
                    results.get("civil_twilight_end", ""),
                ),
            )
            conn.commit()
            logger.info("sun_times_refresh city=%s date=%s status=ok", city, today)
        except Exception:
            logger.exception("sun_times_refresh city=%s status=error", city)


def _parse_iso(iso_str: str) -> datetime | None:
    """Parse ISO 8601 datetime string to UTC datetime."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


class SunPositionSignal(BaseSignal):
    name = "sun_position"
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
        """Evaluate sun position effect on parking demand."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        row = conn.execute(
            "SELECT sunrise, sunset, civil_twilight_begin, civil_twilight_end "
            "FROM cached_sun_times "
            "WHERE city = ? AND date = ?",
            (city, today),
        ).fetchone()

        if row is None:
            return None

        sunrise = _parse_iso(row["sunrise"])
        sunset = _parse_iso(row["sunset"])
        civil_begin = _parse_iso(row["civil_twilight_begin"])
        civil_end = _parse_iso(row["civil_twilight_end"])

        if sunrise is None or sunset is None:
            return None

        # Determine solar period
        period = self._classify_period(now, sunrise, sunset, civil_begin, civil_end)

        if period == "daylight":
            return None  # Normal conditions, no signal

        near_entertainment = self._near_entertainment(conn, city, lat, lon)

        if period == "golden_hour":
            if not near_entertainment:
                return None  # Golden hour only matters near entertainment
            value = 0.85
        elif period == "twilight":
            value = 0.92
        elif period == "night":
            value = 0.95
        else:
            return None

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.70,
            staleness_seconds=0.0,
            detail={
                "period": period,
                "near_entertainment": near_entertainment,
                "sunrise": row["sunrise"],
                "sunset": row["sunset"],
            },
        )

    @staticmethod
    def _classify_period(
        now: datetime,
        sunrise: datetime,
        sunset: datetime,
        civil_begin: datetime | None,
        civil_end: datetime | None,
    ) -> str:
        """Classify current time into solar period."""
        # Golden hour: within 1h before sunset
        golden_start = sunset.replace(hour=sunset.hour - 1) if sunset.hour >= 1 else sunset
        # More robust: subtract 3600 seconds
        from datetime import timedelta
        golden_start = sunset - timedelta(hours=1)

        if golden_start <= now < sunset:
            return "golden_hour"

        # Full daylight: between sunrise and golden hour start
        if sunrise <= now < golden_start:
            return "daylight"

        # Twilight: between civil_begin and sunrise, or between sunset and civil_end
        if civil_begin and civil_begin <= now < sunrise:
            return "twilight"
        if civil_end and sunset <= now < civil_end:
            return "twilight"

        # Night: outside civil twilight
        return "night"

    def _near_entertainment(
        self, conn: sqlite3.Connection, city: str, lat: float, lon: float,
    ) -> bool:
        """Check if lot is near an entertainment demand node."""
        rows = conn.execute(
            "SELECT lat, lon FROM cached_demand_nodes "
            "WHERE city = ? AND category = 'entertainment'",
            (city,),
        ).fetchall()

        for row in rows:
            dist = haversine_km(lat, lon, row["lat"], row["lon"])
            if dist <= _ENTERTAINMENT_SEARCH_RADIUS_KM:
                return True
        return False
