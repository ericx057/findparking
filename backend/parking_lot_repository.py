import math
import sqlite3
from datetime import datetime, timezone

from backend.geo import haversine_km


def get_all_lots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parking_lots ORDER BY name"
    ).fetchall()


def get_lots_by_city(conn: sqlite3.Connection, city: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parking_lots WHERE city = ? ORDER BY name",
        (city,),
    ).fetchall()


def get_lots_nearby(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_km: float = 2.0,
    limit: int = 10,
    fare_type: str | None = None,
    max_hourly_rate: float | None = None,
    is_covered: bool | None = None,
    is_multi_level: bool | None = None,
    is_above_ground: bool | None = None,
) -> list[dict]:
    """Return lots within radius_km of (lat, lon), sorted by distance.

    Uses a bounding-box SQL pre-filter then exact Haversine in Python.
    Each returned dict includes all lot columns plus 'distance_km'.
    Optional filters applied at the SQL level.
    """
    lat_margin = radius_km / 111.0
    lon_margin = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))

    conditions = [
        "latitude BETWEEN ? AND ?",
        "longitude BETWEEN ? AND ?",
    ]
    params: list = [
        lat - lat_margin, lat + lat_margin,
        lon - lon_margin, lon + lon_margin,
    ]

    if fare_type is not None:
        conditions.append("fare_type = ?")
        params.append(fare_type)

    if max_hourly_rate is not None:
        conditions.append("(hourly_rate IS NULL OR hourly_rate <= ?)")
        params.append(max_hourly_rate)

    if is_covered is not None:
        conditions.append("is_covered = ?")
        params.append(1 if is_covered else 0)

    if is_multi_level is not None:
        conditions.append("is_multi_level = ?")
        params.append(1 if is_multi_level else 0)

    if is_above_ground is not None:
        conditions.append("is_above_ground = ?")
        params.append(1 if is_above_ground else 0)

    where_clause = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM parking_lots WHERE {where_clause}",
        params,
    ).fetchall()

    results = []
    for row in rows:
        dist = haversine_km(lat, lon, row["latitude"], row["longitude"])
        if dist <= radius_km:
            lot_dict = dict(row)
            lot_dict["distance_km"] = round(dist, 3)
            results.append(lot_dict)

    results.sort(key=lambda x: x["distance_km"])
    return results[:limit]


def get_lot(conn: sqlite3.Connection, lot_id: str) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM parking_lots WHERE lot_id = ?", (lot_id,)
    ).fetchone()
    return row


def update_occupancy(conn: sqlite3.Connection, lot_id: str, delta: int) -> None:
    lot = get_lot(conn, lot_id)
    if lot is None:
        raise ValueError(f"Lot not found: {lot_id}")

    new_occupancy = lot["current_occupancy"] + delta
    # Boundary enforcement: 0 <= O(t) <= C
    new_occupancy = max(0, min(new_occupancy, lot["capacity"]))

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE parking_lots SET current_occupancy = ?, last_updated = ? WHERE lot_id = ?",
        (new_occupancy, now, lot_id),
    )
    conn.commit()


def reset_occupancy(conn: sqlite3.Connection, lot_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE parking_lots SET current_occupancy = 0, last_updated = ? WHERE lot_id = ?",
        (now, lot_id),
    )
    conn.commit()


def reset_all_occupancies(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE parking_lots SET current_occupancy = 0, last_updated = ?",
        (now,),
    )
    conn.commit()
