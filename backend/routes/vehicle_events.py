from fastapi import APIRouter, HTTPException, Request

from backend.domain import VehicleEventCreate
from backend.parking_lot_repository import get_lot, update_occupancy
from backend.probability_engine import (
    compute_occupancy_delta,
    compute_spot_probability,
    compute_vacancy_ratio,
)
from backend.vehicle_event_store import record_event

router = APIRouter(prefix="/api", tags=["vehicle_events"])


@router.post("/lots/{lot_id}/events", status_code=201)
def post_vehicle_event(lot_id: str, event: VehicleEventCreate, request: Request):
    conn = request.app.state.db_conn

    lot = get_lot(conn, lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail=f"Lot not found: {lot_id}")

    if event.direction not in ("inbound", "outbound"):
        raise HTTPException(status_code=422, detail=f"Invalid direction: {event.direction}")

    delta = compute_occupancy_delta(event.direction)
    update_occupancy(conn, lot_id, delta)
    event_id = record_event(conn, lot_id, event.direction, event.confidence)

    # Record an occupancy snapshot
    refreshed_lot = get_lot(conn, lot_id)
    vacancy = compute_vacancy_ratio(refreshed_lot["capacity"], refreshed_lot["current_occupancy"])
    prob = compute_spot_probability(vacancy, 1.0)

    conn.execute(
        "INSERT INTO occupancy_snapshots (lot_id, occupancy, vacancy_ratio, probability_score) "
        "VALUES (?, ?, ?, ?)",
        (lot_id, refreshed_lot["current_occupancy"], vacancy, prob),
    )
    conn.commit()

    return {
        "event_id": event_id,
        "lot_id": lot_id,
        "direction": event.direction,
        "new_occupancy": refreshed_lot["current_occupancy"],
    }
