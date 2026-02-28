"""Camera-to-lot auto-assignment by proximity.

For each parking lot in a city, find the nearest camera within max_distance_km
and store the assignment in the camera_assignments table.
"""

import sqlite3
from datetime import datetime, timezone

from backend.geo import haversine_km


def assign_cameras_to_lots(
    conn: sqlite3.Connection,
    city: str,
    cameras: list[dict],
    max_distance_km: float = 2.0,
    max_cameras_per_lot: int = 1,
) -> int:
    """Assign nearest camera(s) to each lot in the given city.

    Clears existing assignments for the city's lots before reassigning.
    Returns the number of assignments made.
    """
    lots = conn.execute(
        "SELECT lot_id, latitude, longitude FROM parking_lots WHERE city = ?",
        (city,),
    ).fetchall()

    # Filter cameras that have coordinates
    geo_cameras = [c for c in cameras if c.get("latitude") is not None and c.get("longitude") is not None]

    # Clear old assignments for these lots
    lot_ids = [lot["lot_id"] for lot in lots]
    if lot_ids:
        placeholders = ",".join("?" * len(lot_ids))
        conn.execute(f"DELETE FROM camera_assignments WHERE lot_id IN ({placeholders})", lot_ids)

    assignment_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for lot in lots:
        # Compute distance to each camera
        distances = []
        for cam in geo_cameras:
            dist = haversine_km(lot["latitude"], lot["longitude"], cam["latitude"], cam["longitude"])
            if dist <= max_distance_km:
                distances.append((dist, cam))

        distances.sort(key=lambda x: x[0])

        for dist, cam in distances[:max_cameras_per_lot]:
            conn.execute(
                "INSERT INTO camera_assignments (lot_id, camera_id, distance_km, image_url, source, assigned_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (lot["lot_id"], cam["camera_id"], round(dist, 3), cam.get("image_url"), cam.get("source"), now),
            )
            assignment_count += 1

    conn.commit()
    return assignment_count


def generate_cameras_config(conn: sqlite3.Connection, city: str) -> dict:
    """Generate cameras.json format from DB assignments for a city.

    Returns dict with {"cameras": [...]} where each camera has:
        lot_id, camera_url, poll_interval_seconds, tripwires
    Default tripwire: horizontal midline {x1:0, y1:240, x2:640, y2:240}
    """
    rows = conn.execute(
        "SELECT ca.lot_id, ca.camera_id, ca.image_url "
        "FROM camera_assignments ca "
        "JOIN parking_lots pl ON ca.lot_id = pl.lot_id "
        "WHERE pl.city = ? "
        "ORDER BY ca.lot_id",
        (city,),
    ).fetchall()

    cameras = []
    for row in rows:
        cameras.append({
            "lot_id": row["lot_id"],
            "camera_url": row["image_url"],
            "poll_interval_seconds": 10.0,
            "tripwires": [{"x1": 0, "y1": 240, "x2": 640, "y2": 240}],
        })

    return {"cameras": cameras}
