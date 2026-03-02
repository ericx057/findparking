"""Holiday calendar signal: statutory holidays alter parking demand.

Office holidays (Canada Day, Labour Day, etc.) empty downtown office areas,
increasing parking availability.  Retail holidays (Boxing Day) pack malls,
reducing availability near retail nodes.

Data source: cached_holidays table (populated by external refresh job) with
a mathematical fallback for known Canadian statutory holidays.
"""

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from backend.geo import haversine_km
from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.holiday_calendar")

_CITY_PROVINCE = {"toronto": "ON", "waterloo": "ON", "vancouver": "BC"}

_OFFICE_HOLIDAYS = {
    "Canada Day", "Labour Day", "Labor Day", "New Year",
    "New Year's Day", "Family Day", "Victoria Day",
    "Civic Holiday", "Thanksgiving",
}

_RETAIL_HOLIDAYS = {"Boxing Day"}

_NODE_SEARCH_RADIUS_KM = 1.0

_BRIDGE_FACTOR = 0.30
_DAY_AFTER_FACTOR = 0.25


def _utc_today() -> date:
    """Return today's date in UTC. Extracted for testability."""
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Mathematical fallback: compute known Canadian statutory holidays
# ---------------------------------------------------------------------------

def _easter_date(year: int) -> date:
    """Anonymous Gregorian Easter algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of weekday (0=Mon) in given month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _monday_before(year: int, month: int, day: int) -> date:
    """Return the Monday on or before the given date."""
    target = date(year, month, day)
    offset = (target.weekday() - 0) % 7  # 0 = Monday
    return target - timedelta(days=offset)


def _compute_statutory_holidays(year: int, province: str | None = None) -> list[tuple[date, str]]:
    """Return list of (date, name) for known Canadian statutory holidays."""
    holidays = [
        (date(year, 1, 1), "New Year's Day"),
        (_easter_date(year) - timedelta(days=2), "Good Friday"),
        (_monday_before(year, 5, 24), "Victoria Day"),
        (date(year, 7, 1), "Canada Day"),
        (_nth_weekday(year, 9, 0, 1), "Labour Day"),
        (_nth_weekday(year, 10, 0, 2), "Thanksgiving"),
        (date(year, 11, 11), "Remembrance Day"),
        (date(year, 12, 25), "Christmas Day"),
        (date(year, 12, 26), "Boxing Day"),
    ]
    # Province-specific
    if province == "ON":
        holidays.append((_nth_weekday(year, 2, 0, 3), "Family Day"))
        holidays.append((_nth_weekday(year, 8, 0, 1), "Civic Holiday"))
    return holidays


# ---------------------------------------------------------------------------
# Proximity helpers
# ---------------------------------------------------------------------------

def _has_nearby_nodes(conn: sqlite3.Connection, city: str, lat: float,
                      lon: float, categories: list[str]) -> bool:
    """Check if any demand nodes of given categories are within search radius."""
    placeholders = ",".join("?" for _ in categories)
    rows = conn.execute(
        f"SELECT lat, lon FROM cached_demand_nodes "
        f"WHERE city = ? AND category IN ({placeholders})",
        [city] + categories,
    ).fetchall()
    for row in rows:
        if haversine_km(lat, lon, row["lat"], row["lon"]) <= _NODE_SEARCH_RADIUS_KM:
            return True
    return False


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

class HolidayCalendarSignal(BaseSignal):
    name = "holiday_calendar"
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
        today = _utc_today()
        province = _CITY_PROVINCE.get(city.lower())

        # Try cached holidays first
        holiday_name, proximity_factor = self._find_holiday(
            conn, today, province,
        )

        # Mathematical fallback if no cached holidays at all
        if holiday_name is None:
            total_cached = conn.execute(
                "SELECT COUNT(*) FROM cached_holidays"
            ).fetchone()[0]
            if total_cached == 0:
                holiday_name, proximity_factor = self._fallback_holiday(
                    today, province,
                )

        if holiday_name is None:
            return None

        # Classify and compute value
        value = self._classify_holiday(
            conn, holiday_name, city, lat, lon,
        )

        # Apply proximity factor for adjacent-day effects
        if proximity_factor < 1.0:
            value = 1.0 + (value - 1.0) * proximity_factor

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.70,
            detail={
                "holiday": holiday_name,
                "proximity_factor": proximity_factor,
                "date": today.isoformat(),
            },
        )

    def _find_holiday(
        self,
        conn: sqlite3.Connection,
        today: date,
        province: str | None,
    ) -> tuple[str | None, float]:
        """Search cached_holidays for today or adjacent days.

        Returns (holiday_name, proximity_factor) where factor is 1.0 for
        exact match, _BRIDGE_FACTOR for Friday-before, _DAY_AFTER_FACTOR
        for day-after.
        """
        today_str = today.isoformat()

        # Check today
        if province:
            rows = conn.execute(
                "SELECT name FROM cached_holidays "
                "WHERE date = ? AND (is_global = 1 OR provinces LIKE ?)",
                (today_str, f"%{province}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name FROM cached_holidays "
                "WHERE date = ? AND is_global = 1",
                (today_str,),
            ).fetchall()

        if rows:
            return rows[0]["name"], 1.0

        # Check adjacent: tomorrow is holiday AND today is Friday
        tomorrow_str = (today + timedelta(days=1)).isoformat()
        if today.weekday() == 4:  # Friday
            if province:
                rows = conn.execute(
                    "SELECT name FROM cached_holidays "
                    "WHERE date = ? AND (is_global = 1 OR provinces LIKE ?)",
                    (tomorrow_str, f"%{province}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT name FROM cached_holidays "
                    "WHERE date = ? AND is_global = 1",
                    (tomorrow_str,),
                ).fetchall()
            if rows:
                return rows[0]["name"], _BRIDGE_FACTOR

        # Check adjacent: yesterday was a holiday
        yesterday_str = (today - timedelta(days=1)).isoformat()
        if province:
            rows = conn.execute(
                "SELECT name FROM cached_holidays "
                "WHERE date = ? AND (is_global = 1 OR provinces LIKE ?)",
                (yesterday_str, f"%{province}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name FROM cached_holidays "
                "WHERE date = ? AND is_global = 1",
                (yesterday_str,),
            ).fetchall()
        if rows:
            return rows[0]["name"], _DAY_AFTER_FACTOR

        return None, 0.0

    def _fallback_holiday(
        self,
        today: date,
        province: str | None,
    ) -> tuple[str | None, float]:
        """Mathematical fallback for known Canadian statutory holidays."""
        statutory = _compute_statutory_holidays(today.year, province)
        for h_date, h_name in statutory:
            if h_date == today:
                return h_name, 1.0

        # Check adjacent: tomorrow is Friday bridge
        if today.weekday() == 4:
            tomorrow = today + timedelta(days=1)
            for h_date, h_name in statutory:
                if h_date == tomorrow:
                    return h_name, _BRIDGE_FACTOR

        # Check adjacent: yesterday was holiday
        yesterday = today - timedelta(days=1)
        for h_date, h_name in statutory:
            if h_date == yesterday:
                return h_name, _DAY_AFTER_FACTOR

        return None, 0.0

    def _classify_holiday(
        self,
        conn: sqlite3.Connection,
        holiday_name: str,
        city: str,
        lat: float,
        lon: float,
    ) -> float:
        """Classify a holiday and return its raw value based on proximity."""
        if holiday_name in _RETAIL_HOLIDAYS or "Boxing" in holiday_name:
            # Retail holiday
            near_retail = _has_nearby_nodes(
                conn, city, lat, lon, ["retail"],
            )
            if near_retail:
                return 0.85
            return 1.05

        # Check if it matches a known office holiday pattern
        is_office = False
        for keyword in _OFFICE_HOLIDAYS:
            if keyword.lower() in holiday_name.lower():
                is_office = True
                break

        if is_office:
            near_office = _has_nearby_nodes(
                conn, city, lat, lon, ["commercial", "transit_hub"],
            )
            if near_office:
                return get_signal_param(
                    conn, "holiday_calendar", "office_holiday_value", 1.12,
                )
            near_retail = _has_nearby_nodes(
                conn, city, lat, lon, ["retail"],
            )
            if near_retail:
                return 0.97
            return 1.05

        # Unclassified holiday
        return 1.05
