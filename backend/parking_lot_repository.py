import sqlite3
from datetime import datetime, timezone


def get_all_lots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parking_lots ORDER BY name"
    ).fetchall()


def get_lots_by_city(conn: sqlite3.Connection, city: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parking_lots WHERE city = ? ORDER BY name",
        (city,),
    ).fetchall()


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
