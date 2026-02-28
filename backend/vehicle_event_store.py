import sqlite3
from datetime import datetime, timezone


def record_event(
    conn: sqlite3.Connection,
    lot_id: str,
    direction: str,
    confidence: float = 1.0,
) -> int:
    if direction not in ("inbound", "outbound"):
        raise ValueError(f"Invalid direction: {direction}")

    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO vehicle_events (lot_id, direction, timestamp, confidence) "
        "VALUES (?, ?, ?, ?)",
        (lot_id, direction, now, confidence),
    )
    conn.commit()
    return cursor.lastrowid


def get_events_since(
    conn: sqlite3.Connection,
    lot_id: str,
    since_timestamp: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM vehicle_events WHERE lot_id = ? AND timestamp >= ? ORDER BY timestamp",
        (lot_id, since_timestamp),
    ).fetchall()


def get_recent_event_count(
    conn: sqlite3.Connection,
    lot_id: str,
    since_timestamp: str,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM vehicle_events WHERE lot_id = ? AND timestamp >= ?",
        (lot_id, since_timestamp),
    ).fetchone()
    return row["cnt"]
