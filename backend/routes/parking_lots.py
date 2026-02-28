import math
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from backend.parking_lot_repository import get_all_lots, get_lot, get_lots_by_city
from backend.probability_engine import (
    classify_availability,
    compute_spot_probability,
    compute_vacancy_ratio,
)
from backend.vehicle_event_store import get_recent_event_count

router = APIRouter(prefix="/api", tags=["parking_lots"])


def _compute_lot_response(lot, conn) -> dict:
    """Build a lot response dict with computed probability fields."""
    capacity = lot["capacity"]
    occupancy = lot["current_occupancy"]

    vacancy_ratio = compute_vacancy_ratio(capacity, occupancy)

    # For MVP, time weight is hardcoded at 1.0
    time_weight = 1.0
    probability_score = compute_spot_probability(vacancy_ratio, time_weight)
    availability = classify_availability(probability_score)

    # Freshness: seconds since last update
    freshness_seconds = None
    if lot["last_updated"]:
        try:
            last = datetime.fromisoformat(lot["last_updated"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            freshness_seconds = (datetime.now(timezone.utc) - last).total_seconds()
        except (ValueError, TypeError):
            pass

    # Override availability to stale if data is old
    if freshness_seconds is not None and freshness_seconds > 600:
        availability = "stale"

    # Confidence interval based on recent event count
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    event_count = get_recent_event_count(conn, lot["lot_id"], one_hour_ago)
    confidence_range = None
    if event_count > 0:
        margin = 1.0 / math.sqrt(event_count)
        low_pct = max(0, round((probability_score - margin) * 100))
        high_pct = min(100, round((probability_score + margin) * 100))
        confidence_range = f"{low_pct}-{high_pct}%"

    # Trend: compute from recent snapshots
    snapshots = conn.execute(
        "SELECT occupancy FROM occupancy_snapshots "
        "WHERE lot_id = ? ORDER BY timestamp DESC LIMIT 6",
        (lot["lot_id"],),
    ).fetchall()

    trend = "stable"
    if len(snapshots) >= 2:
        recent = snapshots[0]["occupancy"]
        older = snapshots[-1]["occupancy"]
        if recent > older:
            trend = "filling"
        elif recent < older:
            trend = "emptying"

    return {
        "lot_id": lot["lot_id"],
        "name": lot["name"],
        "latitude": lot["latitude"],
        "longitude": lot["longitude"],
        "capacity": capacity,
        "current_occupancy": occupancy,
        "vacancy_ratio": round(vacancy_ratio, 4),
        "probability_score": round(probability_score, 4),
        "availability": availability,
        "trend": trend,
        "freshness_seconds": round(freshness_seconds, 1) if freshness_seconds is not None else None,
        "confidence_range": confidence_range,
        "last_updated": lot["last_updated"],
    }


@router.get("/lots")
def list_lots(request: Request, city: str | None = Query(default=None)):
    conn = request.app.state.db_conn
    if city:
        lots = get_lots_by_city(conn, city)
    else:
        lots = get_all_lots(conn)
    return [_compute_lot_response(lot, conn) for lot in lots]


@router.get("/lots/{lot_id}")
def get_lot_detail(lot_id: str, request: Request):
    conn = request.app.state.db_conn
    lot = get_lot(conn, lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail=f"Lot not found: {lot_id}")
    return _compute_lot_response(lot, conn)


@router.get("/lots/{lot_id}/history")
def get_lot_history(lot_id: str, request: Request):
    conn = request.app.state.db_conn
    lot = get_lot(conn, lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail=f"Lot not found: {lot_id}")

    snapshots = conn.execute(
        "SELECT * FROM occupancy_snapshots WHERE lot_id = ? ORDER BY timestamp DESC LIMIT 100",
        (lot_id,),
    ).fetchall()

    return [dict(s) for s in snapshots]
