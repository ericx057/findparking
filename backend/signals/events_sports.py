"""Sports event signal: NHL/MLB/NBA/CFL venue proximity and time decay."""

import logging
import math
import sqlite3
from datetime import datetime, timezone, timedelta

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult

logger = logging.getLogger("findparking.signals.events_sports")

# --- Venue registry ---

VENUES = {
    "scotiabank_arena": {
        "lat": 43.6435, "lon": -79.3791,
        "city": "toronto", "capacity": 19800,
        "teams": ["Maple Leafs", "Raptors"],
    },
    "rogers_centre": {
        "lat": 43.6414, "lon": -79.3894,
        "city": "toronto", "capacity": 49286,
        "teams": ["Blue Jays"],
    },
    "rogers_arena": {
        "lat": 49.2778, "lon": -123.1089,
        "city": "vancouver", "capacity": 18910,
        "teams": ["Canucks"],
    },
    "bc_place": {
        "lat": 49.2768, "lon": -123.1117,
        "city": "vancouver", "capacity": 54500,
        "teams": ["BC Lions", "Whitecaps"],
    },
    "bmo_field": {
        "lat": 43.6332, "lon": -79.4186,
        "city": "toronto", "capacity": 30000,
        "teams": ["Argonauts", "Toronto FC"],
    },
}

# --- Team abbreviation to venue mapping for streak lookup ---

_TEAM_VENUE_MAP = {
    # NHL
    "TOR": "scotiabank_arena",
    "VAN": "rogers_arena",
    # MLB
    "TOR-MLB": "rogers_centre",
    # NBA
    "TOR-NBA": "scotiabank_arena",
}

# keywords in event_name to map to team abbreviations
_EVENT_TEAM_PATTERNS = {
    "Maple Leafs": "TOR",
    "Toronto": "TOR",       # NHL context
    "Canucks": "VAN",
    "Blue Jays": "TOR-MLB",
    "Raptors": "TOR-NBA",
}

# --- Decay functions ---

_DISTANCE_HALF_LIFE_KM = 0.8


def distance_decay(km: float) -> float:
    """Exponential decay with half-life at 0.8km.

    At 0km: 1.0, at 0.8km: 0.5, at 1.6km: 0.25, etc.
    """
    if km <= 0:
        return 1.0
    return math.exp(-0.693 * km / _DISTANCE_HALF_LIFE_KM)


def time_decay(now: datetime, start: datetime, end: datetime) -> float:
    """Linear ramp based on time relative to event.

    - 3h+ before: 10%
    - 2h before: 40%
    - 1h before: 80%
    - 30min before to start: 100%
    - During event: 90%
    - 30min after end: 70%
    - 1h+ after end: 0%
    """
    seconds_to_start = (start - now).total_seconds()
    seconds_since_end = (now - end).total_seconds()

    # After event
    if seconds_since_end > 0:
        if seconds_since_end > 3600:
            return 0.0
        if seconds_since_end > 1800:
            # 30min-1h after: linear 0.70 -> 0.0
            return 0.70 * (1.0 - (seconds_since_end - 1800) / 1800)
        # 0-30min after: 0.70
        return 0.70

    # During event
    if seconds_to_start <= 0:
        return 0.90

    # Before event
    hours_before = seconds_to_start / 3600

    if hours_before > 3:
        return 0.10
    if hours_before > 2:
        # 3h-2h: linear 0.10 -> 0.40
        return 0.10 + 0.30 * (3.0 - hours_before)
    if hours_before > 1:
        # 2h-1h: linear 0.40 -> 0.80
        return 0.40 + 0.40 * (2.0 - hours_before)
    if hours_before > 0.5:
        # 1h-30min: linear 0.80 -> 1.00
        return 0.80 + 0.40 * (1.0 - hours_before)
    # <30min: 1.00
    return 1.00


def attendance_factor(expected_attendance: int) -> float:
    """Scale impact by attendance. Capped at 0.90."""
    return min(0.90, 0.15 + 0.65 * (expected_attendance / 50000))


# --- Event window for queries ---

_EVENT_WINDOW_HOURS_BEFORE = 4
_EVENT_WINDOW_HOURS_AFTER = 2


def streak_multiplier(conn: sqlite3.Connection, event_name: str) -> float:
    """Look up team streak and return an impact multiplier.

    Win streak 5+: 1.15 (more excitement, more fans attend)
    Win streak 3-4: 1.08
    Loss streak 5+: 0.88 (fewer fans, less parking demand)
    Loss streak 3-4: 0.94
    Otherwise: 1.0
    """
    if not event_name:
        return 1.0

    # Identify team abbreviation from event name
    team_abbrev = None
    upper_name = event_name.upper()
    for keyword, abbrev in _EVENT_TEAM_PATTERNS.items():
        if keyword.upper() in upper_name:
            team_abbrev = abbrev
            break

    if team_abbrev is None:
        return 1.0

    row = conn.execute(
        "SELECT streak_code, streak_count FROM cached_team_streaks WHERE team_abbrev = ?",
        (team_abbrev,),
    ).fetchone()

    if row is None:
        return 1.0

    code = (row["streak_code"] or "").upper()
    count = row["streak_count"] or 0

    if code == "W":
        if count >= 5:
            return 1.15
        if count >= 3:
            return 1.08
    elif code == "L":
        if count >= 5:
            return 0.88
        if count >= 3:
            return 0.94

    return 1.0


class SportsEventSignal(BaseSignal):
    name = "sports_event"
    base_weight = 0.12

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
        """Find active/upcoming events near this lot and compute impact."""
        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(hours=_EVENT_WINDOW_HOURS_AFTER)).strftime("%Y-%m-%d %H:%M:%S")
        window_end = (now + timedelta(hours=_EVENT_WINDOW_HOURS_BEFORE)).strftime("%Y-%m-%d %H:%M:%S")

        rows = conn.execute(
            "SELECT venue_lat, venue_lon, start_time, end_time, expected_attendance, event_name "
            "FROM cached_events "
            "WHERE city = ? AND start_time <= ? AND (end_time >= ? OR end_time IS NULL)",
            (city, window_end, window_start),
        ).fetchall()

        if not rows:
            return None

        # Find the event with the highest impact on this lot
        max_impact = 0.0
        best_event = None

        for row in rows:
            dist_km = haversine_km(lat, lon, row["venue_lat"], row["venue_lon"])
            d_decay = distance_decay(dist_km)

            if d_decay < 0.05:
                continue  # Too far, skip

            start = datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if row["end_time"]:
                end = datetime.strptime(row["end_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            else:
                end = start + timedelta(hours=3)

            t_decay = time_decay(now, start, end)
            att_fact = attendance_factor(row["expected_attendance"] or 20000)

            impact = att_fact * d_decay * t_decay

            if impact > max_impact:
                max_impact = impact
                best_event = row["event_name"]

        if max_impact < 0.01:
            return None

        # Apply streak multiplier from cached team streaks
        s_mult = streak_multiplier(conn, best_event) if best_event else 1.0
        max_impact = min(0.95, max_impact * s_mult)

        # Availability = 1.0 - impact (clamped)
        availability = max(0.05, 1.0 - max_impact)

        return SignalResult(
            source=self.name,
            value=round(availability, 4),
            confidence=0.75,  # events are scheduled, confidence is moderate
            staleness_seconds=0.0,
            detail={
                "event": best_event,
                "impact": round(max_impact, 4),
                "streak_multiplier": s_mult,
            },
        )
