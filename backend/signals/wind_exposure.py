"""Wind exposure signal: wind-driven behavioral split between lot types.

High winds push demand away from uncovered/above-ground lots toward
covered or underground structures. Extreme gusts amplify the effect.

Data source: cached_weather table (wind_kph, wind_gusts_kph columns).
"""

import logging
import sqlite3
from datetime import datetime, timezone

from backend.signals import BaseSignal, SignalResult, get_signal_param

logger = logging.getLogger("findparking.signals.wind_exposure")

_STALE_THRESHOLD_SECONDS = 3600  # 1 hour
_WIND_THRESHOLD_KPH = 30
_GUST_BONUS_THRESHOLD_KPH = 80
_GUST_BONUS = 0.05
_MULTI_LEVEL_FACTOR = 0.6


class WindExposureSignal(BaseSignal):
    name = "wind_exposure"
    base_weight = 0.02

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
        """Evaluate wind exposure effect on parking lot demand."""
        # 1. Get most recent weather
        row = conn.execute(
            "SELECT wind_kph, wind_gusts_kph, observed_at "
            "FROM cached_weather WHERE city = ? "
            "ORDER BY observed_at DESC LIMIT 1",
            (city,),
        ).fetchone()

        if row is None:
            return None

        # 2. Staleness check
        try:
            observed = datetime.strptime(row["observed_at"], "%Y-%m-%d %H:%M:%S")
            observed = observed.replace(tzinfo=timezone.utc)
            staleness = (datetime.now(timezone.utc) - observed).total_seconds()
        except (ValueError, TypeError):
            return None

        if staleness > _STALE_THRESHOLD_SECONDS:
            return None

        # 3. Effective wind
        wind_kph = row["wind_kph"] or 0
        wind_gusts_kph = row["wind_gusts_kph"] or 0
        effective_wind = max(wind_kph, wind_gusts_kph)

        if effective_wind < _WIND_THRESHOLD_KPH:
            return None

        # 4. Lot type
        lot_row = conn.execute(
            "SELECT is_covered, is_multi_level, is_above_ground "
            "FROM parking_lots WHERE lot_id = ?",
            (lot_id,),
        ).fetchone()

        if lot_row is None:
            return None

        is_covered = bool(lot_row["is_covered"])
        is_multi_level = bool(lot_row["is_multi_level"])
        is_above_ground = bool(lot_row["is_above_ground"])

        # 5. Compute value based on lot type and wind speed
        if is_covered or not is_above_ground:
            value = self._covered_value(conn, effective_wind)
        else:
            value = self._uncovered_value(conn, effective_wind, wind_gusts_kph)
            if is_multi_level:
                # Multi-level gets 60% of the uncovered effect
                effect = value - 1.0
                value = 1.0 + effect * _MULTI_LEVEL_FACTOR

        return SignalResult(
            source=self.name,
            value=round(value, 4),
            confidence=0.50,
            staleness_seconds=staleness,
            detail={
                "effective_wind_kph": effective_wind,
                "wind_gusts_kph": wind_gusts_kph,
                "is_covered": is_covered,
                "is_multi_level": is_multi_level,
                "is_above_ground": is_above_ground,
            },
        )

    def _uncovered_value(self, conn: sqlite3.Connection,
                         effective_wind: float, gusts: float) -> float:
        """Compute value for uncovered above-ground lots."""
        if effective_wind > 60:
            base = get_signal_param(conn, self.name, "uncovered_severe", 1.12)
        elif effective_wind >= 40:
            base = get_signal_param(conn, self.name, "uncovered_strong", 1.07)
        else:
            base = get_signal_param(conn, self.name, "uncovered_moderate", 1.03)

        # Gust bonus
        if gusts > _GUST_BONUS_THRESHOLD_KPH:
            base += _GUST_BONUS

        return base

    def _covered_value(self, conn: sqlite3.Connection,
                       effective_wind: float) -> float:
        """Compute value for covered or underground lots."""
        if effective_wind > 60:
            return get_signal_param(conn, self.name, "covered_severe", 0.92)
        if effective_wind >= 40:
            return get_signal_param(conn, self.name, "covered_strong", 0.95)
        return get_signal_param(conn, self.name, "covered_moderate", 0.98)
