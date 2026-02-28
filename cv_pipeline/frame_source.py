import abc
import logging
import time

import numpy as np

logger = logging.getLogger("findparking.frame_source")


class FrameSource(abc.ABC):
    """Abstract base class for frame acquisition."""

    @abc.abstractmethod
    def get_frame(self) -> np.ndarray | None:
        """Return a frame as a numpy array, or None on failure."""
        ...


class HttpJpegSource(FrameSource):
    """Fetches JPEG snapshots from an HTTP URL at a fixed interval."""

    def __init__(self, url: str, poll_interval_seconds: float = 10.0):
        self.url = url
        self.poll_interval = poll_interval_seconds
        self._last_fetch_time = 0.0

    def get_frame(self) -> np.ndarray | None:
        import cv2
        import requests

        elapsed = time.monotonic() - self._last_fetch_time
        if elapsed < self.poll_interval:
            time.sleep(self.poll_interval - elapsed)

        try:
            response = requests.get(self.url, timeout=15)
            response.raise_for_status()
            self._last_fetch_time = time.monotonic()

            arr = np.frombuffer(response.content, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning("Failed to decode JPEG from %s", self.url)
                return None
            return frame
        except requests.RequestException as exc:
            logger.warning("HTTP fetch failed for %s: %s", self.url, exc)
            return None


class FileSource(FrameSource):
    """Reads frames from a directory of image files (for testing/replay)."""

    def __init__(self, directory: str, loop: bool = True):
        import os
        self.files = sorted(
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        )
        self.loop = loop
        self._index = 0

    def get_frame(self) -> np.ndarray | None:
        import cv2

        if not self.files:
            return None
        if self._index >= len(self.files):
            if self.loop:
                self._index = 0
            else:
                return None

        frame = cv2.imread(self.files[self._index])
        self._index += 1
        return frame


class MockSource(FrameSource):
    """Returns synthetic frames for unit tests. No OpenCV dependency."""

    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self._frame_count = 0

    def get_frame(self) -> np.ndarray | None:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        self._frame_count += 1
        return frame
