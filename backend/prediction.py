"""Historical prediction: 3-day rolling average at a given hour."""

import sqlite3
from datetime import datetime, timezone, timedelta


def get_historical_prediction(conn: sqlite3.Connection, lot_id: str, hour: int) -> float | None:
    """Average probability_score for this lot at this hour over the past 3 days.

    Returns None if no snapshots exist for the given lot/hour window.
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=3)
    cutoff = cutoff_dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT AVG(probability_score) as avg_prob "
        "FROM occupancy_snapshots "
        "WHERE lot_id = ? "
        "AND CAST(strftime('%H', timestamp) AS INTEGER) = ? "
        "AND timestamp >= ?",
        (lot_id, hour, cutoff),
    ).fetchone()
    if row is None or row["avg_prob"] is None:
        return None
    return round(row["avg_prob"], 4)
