"""Signal interface for the multi-signal estimation hierarchy."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import sqlite3

logger = logging.getLogger("findparking.signals")


@dataclass
class SignalResult:
    """Output of a single signal evaluation."""

    source: str
    value: float  # 0.0 = no availability, 1.0 = fully available
    confidence: float  # 0.0 = no confidence, 1.0 = perfect confidence
    staleness_seconds: float = 0.0
    detail: dict = field(default_factory=dict)


class BaseSignal(ABC):
    """Abstract base for all estimation signals."""

    # Subclasses must set these
    name: str = ""
    base_weight: float = 0.0

    @abstractmethod
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
        """Evaluate this signal for a given lot.

        Returns SignalResult if the signal has data, None if unavailable.
        """


def get_signal_param(
    conn: sqlite3.Connection, signal_name: str, key: str, default: float,
) -> float:
    """Read a configurable parameter from signal_params table.

    Falls back to the provided default if the table doesn't exist,
    the row is missing, or any error occurs.
    """
    try:
        row = conn.execute(
            "SELECT param_value FROM signal_params "
            "WHERE signal_name = ? AND param_key = ?",
            (signal_name, key),
        ).fetchone()
        return row[0] if row else default
    except Exception:
        return default
