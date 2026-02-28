"""Estimation orchestrator: blends multiple signals into a single availability score."""

import sqlite3
from dataclasses import dataclass, field

from backend.signals import SignalResult
from backend.signals.camera import CameraSignal
from backend.signals.events_sports import SportsEventSignal
from backend.signals.heuristic_baseline import HeuristicBaselineSignal
from backend.signals.road_disruptions import RoadDisruptionsSignal
from backend.signals.time_weights import TimeWeightsSignal
from backend.signals.weather import WeatherSignal


@dataclass
class BlendedEstimate:
    """Result of the multi-signal blending."""

    score: float  # 0.0-1.0 blended availability
    signals_used: list[str] = field(default_factory=list)
    signal_details: list[dict] = field(default_factory=list)


# Registry of all signal instances, evaluated in order
_SIGNALS = [
    CameraSignal(),
    HeuristicBaselineSignal(),
    SportsEventSignal(),
    TimeWeightsSignal(),
    WeatherSignal(),
    RoadDisruptionsSignal(),
]


def compute_blended_score(
    conn: sqlite3.Connection,
    lot_id: str,
    lat: float,
    lon: float,
    city: str,
    capacity: int,
    occupancy: int,
) -> BlendedEstimate:
    """Evaluate all registered signals and blend into a single score.

    Formula: blended = SUM(w_i * c_i * v_i) / SUM(w_i * c_i)

    When no signals are available, falls back to raw vacancy ratio.
    """
    results: list[tuple[float, SignalResult]] = []

    for signal in _SIGNALS:
        result = signal.evaluate(conn, lot_id, lat, lon, city, capacity, occupancy)
        if result is not None:
            results.append((signal.base_weight, result))

    if not results:
        # Fallback: raw vacancy ratio
        from backend.probability_engine import compute_vacancy_ratio

        raw = compute_vacancy_ratio(capacity, occupancy) if capacity > 0 else 0.0
        return BlendedEstimate(score=raw, signals_used=[], signal_details=[])

    numerator = 0.0
    denominator = 0.0
    signals_used = []
    signal_details = []

    for weight, result in results:
        contribution = weight * result.confidence * result.value
        norm_factor = weight * result.confidence
        numerator += contribution
        denominator += norm_factor
        signals_used.append(result.source)
        signal_details.append({
            "source": result.source,
            "value": round(result.value, 4),
            "confidence": round(result.confidence, 4),
            "weight": weight,
            "contribution": round(contribution, 4),
        })

    blended = numerator / denominator if denominator > 0 else 0.0
    blended = max(0.0, min(1.0, blended))

    return BlendedEstimate(
        score=round(blended, 4),
        signals_used=signals_used,
        signal_details=signal_details,
    )
