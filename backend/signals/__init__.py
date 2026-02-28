"""Signal interface for the multi-signal estimation hierarchy."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import sqlite3


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
