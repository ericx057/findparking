import logging
import time

import httpx

logger = logging.getLogger("findparking.emitter")


class HttpEventEmitter:
    """Posts vehicle crossing events to the backend API."""

    def __init__(self, backend_url: str, max_retries: int = 3):
        self.backend_url = backend_url.rstrip("/")
        self.max_retries = max_retries

    def emit(self, lot_id: str, direction: str, confidence: float = 1.0) -> bool:
        url = f"{self.backend_url}/api/lots/{lot_id}/events"
        payload = {"direction": direction, "confidence": confidence}

        for attempt in range(1, self.max_retries + 1):
            try:
                response = httpx.post(url, json=payload, timeout=10)
                if response.status_code == 201:
                    logger.info(
                        "Event emitted: lot=%s direction=%s confidence=%.2f",
                        lot_id, direction, confidence,
                    )
                    return True
                else:
                    logger.warning(
                        "Backend returned %d for event: lot=%s direction=%s",
                        response.status_code, lot_id, direction,
                    )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Emit attempt %d/%d failed: %s", attempt, self.max_retries, exc
                )

            if attempt < self.max_retries:
                time.sleep(1.0 * attempt)

        logger.error("Failed to emit event after %d attempts: lot=%s", self.max_retries, lot_id)
        return False
