"""Camera signal: wraps existing vacancy_ratio with staleness-based confidence decay."""

import sqlite3
from datetime import datetime, timezone

from backend.probability_engine import compute_vacancy_ratio
from backend.signals import BaseSignal, SignalResult


# Confidence thresholds by staleness (seconds)
_CONFIDENCE_TIERS = [
    (300, 0.95),    # <5 min
    (600, 0.70),    # <10 min
    (1800, 0.40),   # <30 min
]
_STALE_CONFIDENCE = 0.20  # >30 min


def camera_confidence(staleness_seconds: float | None) -> float:
    """Map staleness in seconds to a confidence score."""
    if staleness_seconds is None:
        return _STALE_CONFIDENCE
    for threshold, confidence in _CONFIDENCE_TIERS:
        if staleness_seconds < threshold:
            return confidence
    return _STALE_CONFIDENCE


class CameraSignal(BaseSignal):
    name = "camera"
    base_weight = 0.50

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
        if capacity <= 0:
            return None

        # No vehicle event history means occupancy=0 is the seeded default, not observed empty
        event_count = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE lot_id = ?", (lot_id,)
        ).fetchone()[0]
        if event_count == 0:
            return None

        vacancy_ratio = compute_vacancy_ratio(capacity, occupancy)

        # Compute staleness from last_updated
        row = conn.execute(
            "SELECT last_updated FROM parking_lots WHERE lot_id = ?",
            (lot_id,),
        ).fetchone()

        staleness = None
        if row and row["last_updated"]:
            try:
                last = datetime.fromisoformat(row["last_updated"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                staleness = (datetime.now(timezone.utc) - last).total_seconds()
            except (ValueError, TypeError):
                pass

        confidence = camera_confidence(staleness)

        return SignalResult(
            source=self.name,
            value=vacancy_ratio,
            confidence=confidence,
            staleness_seconds=staleness if staleness is not None else 0.0,
            detail={"vacancy_ratio": vacancy_ratio},
        )
