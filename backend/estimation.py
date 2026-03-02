"""Estimation orchestrator: blends multiple signals into a single availability score."""

import logging
import sqlite3
from dataclasses import dataclass, field

from backend.signals import SignalResult
from backend.signals.camera import CameraSignal
from backend.signals.events_sports import SportsEventSignal
from backend.signals.demand_heatmap import DemandHeatmapSignal
from backend.signals.road_disruptions import RoadDisruptionsSignal
from backend.signals.time_weights import TimeWeightsSignal
from backend.signals.weather import WeatherSignal
from backend.signals.festival_events import FestivalEventSignal
from backend.signals.bikeshare import BikeshareSignal
from backend.signals.transit_disruptions import TransitDisruptionSignal
from backend.signals.air_quality import AirQualitySignal
from backend.signals.holiday_calendar import HolidayCalendarSignal
from backend.signals.economic_climate import EconomicClimateSignal
from backend.signals.construction_proximity import ConstructionProximitySignal
from backend.signals.wind_exposure import WindExposureSignal

logger = logging.getLogger("findparking.estimation")


@dataclass
class BlendedEstimate:
    """Result of the multi-signal blending."""

    score: float  # 0.0-1.0 blended availability
    signals_used: list[str] = field(default_factory=list)
    signal_details: list[dict] = field(default_factory=list)


# Registry of all signal instances, evaluated in order of weight.
# Confounding signals removed after reassessment:
#   - PressureTrend: confounds with WeatherSignal's precip_probability_modifier
#   - SunPosition: confounds with TimeWeightsSignal's hour-of-day patterns
#   - LunarCycle: effect size indistinguishable from noise at 0.01 weight
#   - Geomagnetic: fires too rarely, negligible contribution
_SIGNALS = [
    CameraSignal(),                # 0.50
    DemandHeatmapSignal(),         # 0.30
    SportsEventSignal(),           # 0.12
    TimeWeightsSignal(),           # 0.10
    WeatherSignal(),               # 0.08
    HolidayCalendarSignal(),       # 0.06
    FestivalEventSignal(),         # 0.06
    RoadDisruptionsSignal(),       # 0.05
    ConstructionProximitySignal(), # 0.04
    BikeshareSignal(),             # 0.04
    TransitDisruptionSignal(),     # 0.04
    AirQualitySignal(),            # 0.03
    WindExposureSignal(),          # 0.02
    EconomicClimateSignal(),       # 0.02
]


def _get_effective_weight(conn: sqlite3.Connection, signal_name: str,
                          base_weight: float) -> float:
    """Read adaptive weight multiplier from signal_params, default 1.0.

    The calibration system stores multipliers in signal_params. The effective
    weight is base_weight * multiplier, clamped to [0.25x, 2.0x].
    """
    try:
        row = conn.execute(
            "SELECT param_value FROM signal_params "
            "WHERE signal_name = ? AND param_key = 'effective_weight_multiplier'",
            (signal_name,),
        ).fetchone()
        multiplier = row[0] if row else 1.0
    except Exception:
        multiplier = 1.0
    return base_weight * max(0.25, min(2.0, multiplier))


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

    Weights are dynamically adjusted by the adaptive calibration system.
    When no signals are available, falls back to raw vacancy ratio.
    """
    results: list[tuple[float, SignalResult]] = []

    for signal in _SIGNALS:
        try:
            result = signal.evaluate(conn, lot_id, lat, lon, city, capacity, occupancy)
        except Exception:
            logger.debug("signal %s raised exception for lot=%s", signal.name, lot_id)
            continue
        if result is not None:
            effective_weight = _get_effective_weight(conn, signal.name, signal.base_weight)
            results.append((effective_weight, result))

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
            "weight": round(weight, 4),
            "contribution": round(contribution, 4),
        })

    blended = numerator / denominator if denominator > 0 else 0.0
    blended = max(0.0, min(1.0, blended))

    return BlendedEstimate(
        score=round(blended, 4),
        signals_used=signals_used,
        signal_details=signal_details,
    )
