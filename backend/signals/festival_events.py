"""Festival event signal: city festivals and events increase parking demand.

Large festivals (music, food, cultural) create significant parking demand
in their vicinity, sometimes exceeding sports events in scale.

Data source: Toronto Open Data festivals/events calendar.
"""

import logging
import math
import sqlite3
from datetime import datetime, timezone, timedelta

import httpx

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.festival_events")

_DISTANCE_HALF_LIFE_KM = 1.0  # wider than sports events (festivals disperse foot traffic)
_MAX_IMPACT = 0.70

# Known Toronto venue coordinates for geocoding event locations
_TORONTO_VENUES = {
    "nathan phillips square": (43.6534, -79.3842),
    "harbourfront centre": (43.6388, -79.3819),
    "harbourfront": (43.6388, -79.3819),
    "exhibition place": (43.6341, -79.4179),
    "yonge-dundas square": (43.6561, -79.3802),
    "dundas square": (43.6561, -79.3802),
    "distillery district": (43.6503, -79.3596),
    "distillery": (43.6503, -79.3596),
    "woodbine park": (43.6642, -79.3106),
    "trinity bellwoods": (43.6461, -79.4137),
    "high park": (43.6465, -79.4637),
    "queen's park": (43.6603, -79.3919),
    "queens park": (43.6603, -79.3919),
    "mel lastman square": (43.7677, -79.4131),
    "scarborough civic centre": (43.7735, -79.2578),
    "centennial park": (43.6508, -79.5733),
    "toronto city hall": (43.6534, -79.3842),
    "city hall": (43.6534, -79.3842),
    "fort york": (43.6390, -79.4042),
    "evergreen brick works": (43.6847, -79.3658),
    "ontario place": (43.6286, -79.4130),
    "aga khan museum": (43.7255, -79.3356),
    "royal ontario museum": (43.6677, -79.3948),
    "rom": (43.6677, -79.3948),
    "cn tower": (43.6426, -79.3871),
    "rogers centre": (43.6414, -79.3894),
}

_FESTIVAL_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "9201059e-43ed-4369-885e-0b867652feac/resource/"
    "8900fdb2-7f6c-4f50-8581-b463311ff05d/download/file.json"
)


def _geocode_location(location_name: str) -> tuple[float, float] | None:
    """Attempt to geocode a Toronto location name using the lookup table."""
    if not location_name:
        return None
    lower = location_name.lower().strip()
    for key, coords in _TORONTO_VENUES.items():
        if key in lower:
            return coords
    return None


def refresh_festival_events(conn: sqlite3.Connection) -> None:
    """Fetch festival events from Toronto Open Data."""
    try:
        resp = httpx.get(_FESTIVAL_URL, timeout=30.0)
        resp.raise_for_status()
        events = resp.json()

        if not isinstance(events, list):
            logger.warning("festival_refresh unexpected format")
            return

        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=7)

        # Clear old festival events
        conn.execute("DELETE FROM cached_festival_events WHERE city = 'toronto'")

        count = 0
        for event in events:
            event_name = event.get("eventName", event.get("calEvent", {}).get("eventName", ""))
            if not event_name:
                continue

            # Try multiple date field patterns
            start_date = event.get("startDate", event.get("calEvent", {}).get("startDate", ""))
            end_date = event.get("endDate", event.get("calEvent", {}).get("endDate", ""))

            if not start_date:
                continue

            # Parse date (could be ISO or YYYY-MM-DD)
            start_str = start_date[:10] if len(start_date) >= 10 else start_date
            end_str = end_date[:10] if end_date and len(end_date) >= 10 else start_str

            # Filter to relevant time window
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            if end_dt < now - timedelta(days=1):
                continue  # Already over
            if start_dt > window_end:
                continue  # Too far in the future

            # Geocode location
            location_name = event.get("locationName", event.get("calEvent", {}).get("locations", {}).get("locationName", ""))
            coords = _geocode_location(location_name)
            lat = coords[0] if coords else None
            lon = coords[1] if coords else None

            if lat is None:
                continue  # Can't use events without coordinates

            category = event.get("category", event.get("calEvent", {}).get("category", ""))

            event_id = f"fest-tor-{hash(event_name + start_str) % 100000}"
            conn.execute(
                "INSERT OR REPLACE INTO cached_festival_events "
                "(event_id, city, event_name, category, lat, lon, "
                "start_date, end_date, location_name, fetched_at) "
                "VALUES (?, 'toronto', ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (event_id, event_name, category, lat, lon,
                 start_str, end_str, location_name),
            )
            count += 1

        conn.commit()
        logger.info("festival_refresh city=toronto events=%d", count)
    except Exception:
        logger.exception("festival_refresh status=error")


def _distance_decay(km: float) -> float:
    """Exponential decay with half-life at 1.0 km."""
    if km <= 0:
        return 1.0
    return math.exp(-0.693 * km / _DISTANCE_HALF_LIFE_KM)


class FestivalEventSignal(BaseSignal):
    name = "festival_event"
    base_weight = 0.06

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
        """Find active festivals near this lot and compute demand impact."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # Fetch festivals that overlap with today (allowing 2h pre-start)
        two_hours_ago = (now - timedelta(hours=2)).strftime("%Y-%m-%d")

        rows = conn.execute(
            "SELECT lat, lon, event_name, start_date, end_date "
            "FROM cached_festival_events "
            "WHERE city = ? AND lat IS NOT NULL AND lon IS NOT NULL "
            "AND start_date <= ? AND (end_date >= ? OR end_date IS NULL)",
            (city, today, two_hours_ago),
        ).fetchall()

        if not rows:
            return None

        max_impact = 0.0
        best_event = None

        for row in rows:
            dist_km = haversine_km(lat, lon, row["lat"], row["lon"])
            d_decay = _distance_decay(dist_km)

            if d_decay < 0.05:
                continue  # Too far

            # Time factor: full impact during event dates
            try:
                start_dt = datetime.strptime(row["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                end_str = row["end_date"] or row["start_date"]
                end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                # End includes the full day
                end_dt = end_dt + timedelta(hours=23, minutes=59)
            except ValueError:
                continue

            if now < start_dt - timedelta(hours=2):
                continue  # Not started yet
            if now > end_dt + timedelta(hours=1):
                continue  # Already over

            # Ramp: 2h before -> 0.5, during -> 1.0, 1h after -> 0.5
            if now < start_dt:
                time_factor = 0.5
            elif now > end_dt:
                time_factor = 0.5
            else:
                time_factor = 1.0

            impact = d_decay * time_factor * _MAX_IMPACT
            if impact > max_impact:
                max_impact = impact
                best_event = row["event_name"]

        if max_impact < 0.01:
            return None

        availability = max(0.10, 1.0 - max_impact)

        return SignalResult(
            source=self.name,
            value=round(availability, 4),
            confidence=0.55,
            staleness_seconds=0.0,
            detail={
                "event": best_event,
                "impact": round(max_impact, 4),
            },
        )
