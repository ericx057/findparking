import time
import threading

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


class _RateLimiter:
    """Simple per-IP token bucket rate limiter.

    Allows `max_tokens` requests per `refill_seconds` window per client IP.
    """

    def __init__(self, max_tokens: int = 30, refill_seconds: float = 60.0):
        self._max_tokens = max_tokens
        self._refill_seconds = refill_seconds
        self._buckets: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last_refill)
        self._lock = threading.Lock()

    def allow(self, client_ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last_refill = self._buckets.get(client_ip, (self._max_tokens, now))
            elapsed = now - last_refill
            tokens = min(self._max_tokens, tokens + elapsed * (self._max_tokens / self._refill_seconds))
            last_refill = now
            if tokens >= 1.0:
                self._buckets[client_ip] = (tokens - 1.0, last_refill)
                return True
            self._buckets[client_ip] = (tokens, last_refill)
            return False


_event_limiter = _RateLimiter(max_tokens=30, refill_seconds=60.0)


@router.post("/lots/{lot_id}/events", status_code=201)
def post_vehicle_event(lot_id: str, event: VehicleEventCreate, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _event_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

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
