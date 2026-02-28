"""Mock event generator for development and demos.

Generates realistic vehicle flow events with a sinusoidal pattern
to simulate rush hours and quiet periods.
"""

import logging
import math
import random
import time
from datetime import datetime

import httpx

logger = logging.getLogger("findparking.mock_pipeline")

# Default lots to generate events for (keyed by city)
DEFAULT_LOT_IDS = {
    "waterloo": [
        "waterloo-town-square",
        "uw-lot-c",
        "uw-lot-x",
        "uptown-garage",
        "conestoga-mall",
    ],
    "toronto": [
        "tor-union-station",
        "tor-eaton-centre",
        "tor-nathan-phillips",
        "tor-yorkville",
        "tor-kensington",
    ],
    "vancouver": [
        "van-pacific-centre",
        "van-robson-square",
        "van-gastown",
        "van-granville-island",
        "van-stanley-park",
    ],
}


class MockEventGenerator:
    def __init__(
        self,
        backend_url: str = "http://localhost:8000",
        lot_ids: list[str] | None = None,
        city: str = "waterloo",
        base_events_per_minute: float = 6.0,
    ):
        self.backend_url = backend_url.rstrip("/")
        if lot_ids:
            self.lot_ids = lot_ids
        else:
            self.lot_ids = DEFAULT_LOT_IDS.get(city, DEFAULT_LOT_IDS["waterloo"])
        self.base_rate = base_events_per_minute

    def _current_rate_multiplier(self) -> float:
        """Sinusoidal multiplier peaking at morning rush (8-9 AM) and evening (5-6 PM)."""
        hour = datetime.now().hour + datetime.now().minute / 60.0
        # Two peaks: 8.5 and 17.5
        morning = math.exp(-((hour - 8.5) ** 2) / 4)
        evening = math.exp(-((hour - 17.5) ** 2) / 4)
        return 0.3 + 1.5 * (morning + evening)

    def _inbound_bias(self) -> float:
        """Morning favors inbound, evening favors outbound."""
        hour = datetime.now().hour
        if 7 <= hour <= 10:
            return 0.75  # 75% inbound during morning
        elif 16 <= hour <= 19:
            return 0.25  # 25% inbound during evening
        return 0.50

    def _emit_event(self, lot_id: str) -> None:
        direction = "inbound" if random.random() < self._inbound_bias() else "outbound"
        confidence = round(random.uniform(0.7, 0.99), 2)

        url = f"{self.backend_url}/api/lots/{lot_id}/events"
        try:
            response = httpx.post(
                url,
                json={"direction": direction, "confidence": confidence},
                timeout=5,
            )
            if response.status_code == 201:
                logger.info("Mock event: lot=%s direction=%s confidence=%.2f", lot_id, direction, confidence)
            else:
                logger.warning("Mock event rejected (%d): lot=%s", response.status_code, lot_id)
        except httpx.HTTPError as exc:
            logger.warning("Mock emit failed: %s", exc)

    def run(self) -> None:
        logger.info(
            "Mock pipeline started: %d lots, base_rate=%.1f events/min",
            len(self.lot_ids), self.base_rate,
        )

        try:
            while True:
                multiplier = self._current_rate_multiplier()
                effective_rate = self.base_rate * multiplier

                # Pick a random lot and emit an event
                lot_id = random.choice(self.lot_ids)
                self._emit_event(lot_id)

                # Sleep for the interval
                interval = 60.0 / effective_rate
                jitter = random.uniform(-interval * 0.3, interval * 0.3)
                time.sleep(max(1.0, interval + jitter))
        except KeyboardInterrupt:
            logger.info("Mock pipeline stopped by user")


def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Mock event generator")
    parser.add_argument(
        "--city", default="waterloo",
        choices=list(DEFAULT_LOT_IDS.keys()),
        help="City to generate mock events for",
    )
    args = parser.parse_args()

    generator = MockEventGenerator(city=args.city)
    generator.run()


if __name__ == "__main__":
    main()
