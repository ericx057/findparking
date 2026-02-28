"""Ticketmaster event signal: concerts and festivals via Discovery API.

Gated by PARKING_TICKETMASTER_API_KEY environment variable.
Free tier: 5,000 requests/day.
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import httpx

from backend.signals.events_sports import distance_decay, time_decay, attendance_factor

logger = logging.getLogger("findparking.signals.events_ticketmaster")

_CITIES = {
    "toronto": {"lat": 43.6532, "lon": -79.3832},
    "waterloo": {"lat": 43.4643, "lon": -80.5204},
    "vancouver": {"lat": 49.2827, "lon": -123.1207},
}


def refresh_ticketmaster_events(conn: sqlite3.Connection, api_key: str) -> None:
    """Fetch upcoming events from Ticketmaster Discovery API."""
    if not api_key:
        return

    for city, coords in _CITIES.items():
        try:
            resp = httpx.get(
                "https://app.ticketmaster.com/discovery/v2/events.json",
                params={
                    "apikey": api_key,
                    "countryCode": "CA",
                    "city": city,
                    "radius": "25",
                    "unit": "km",
                    "size": "50",
                    "sort": "date,asc",
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

            events = data.get("_embedded", {}).get("events", [])
            count = 0
            for event in events:
                event_id = f"tm-{event.get('id', '')}"
                event_name = event.get("name", "Unknown Event")

                # Extract venue coords
                venues = event.get("_embedded", {}).get("venues", [])
                if not venues:
                    continue
                venue = venues[0]
                location = venue.get("location", {})
                venue_lat = location.get("latitude")
                venue_lon = location.get("longitude")
                if venue_lat is None or venue_lon is None:
                    continue

                try:
                    venue_lat = float(venue_lat)
                    venue_lon = float(venue_lon)
                except (ValueError, TypeError):
                    continue

                venue_name = venue.get("name", "Unknown Venue")

                # Extract start time
                dates = event.get("dates", {})
                start_info = dates.get("start", {})
                start_dt_str = start_info.get("dateTime", "")
                if not start_dt_str:
                    continue

                start_str = start_dt_str.replace("T", " ").replace("Z", "")[:19]
                try:
                    start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                end_dt = start_dt + timedelta(hours=3)

                # Estimate attendance from venue capacity or seatmap
                capacity = None
                seatmap = event.get("seatmap", {})
                if seatmap:
                    # Ticketmaster doesn't reliably give capacity
                    capacity = 5000  # conservative default for concerts

                conn.execute(
                    "INSERT OR REPLACE INTO cached_events "
                    "(event_id, source, venue_name, venue_lat, venue_lon, city, "
                    "event_name, start_time, end_time, expected_attendance, fetched_at) "
                    "VALUES (?, 'ticketmaster', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (event_id, venue_name, venue_lat, venue_lon, city, event_name,
                     start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                     end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                     capacity or 5000),
                )
                count += 1

            conn.commit()
            logger.info("ticketmaster_refresh city=%s count=%d", city, count)
        except Exception:
            logger.exception("ticketmaster_refresh city=%s status=error", city)
