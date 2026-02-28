import logging
import threading

from cv_pipeline.frame_source import FrameSource
from cv_pipeline.vehicle_detector import VehicleDetector
from cv_pipeline.vehicle_tracker import VehicleTracker
from cv_pipeline.tripwire import Tripwire
from cv_pipeline.event_emitter import HttpEventEmitter

logger = logging.getLogger("findparking.pipeline")


class ParkingPipeline:
    """Main CV pipeline: frame -> detect -> track -> tripwire -> emit."""

    def __init__(
        self,
        frame_source: FrameSource,
        detector: VehicleDetector,
        tracker: VehicleTracker,
        tripwires: list[Tripwire],
        emitter: HttpEventEmitter,
        lot_id: str,
        stop_event: threading.Event | None = None,
    ):
        self.frame_source = frame_source
        self.detector = detector
        self.tracker = tracker
        self.tripwires = tripwires
        self.emitter = emitter
        self.lot_id = lot_id
        self.stop_event = stop_event or threading.Event()
        self._frame_count = 0

    def run(self):
        logger.info("Pipeline started for lot=%s", self.lot_id)
        self.detector.warmup()

        while not self.stop_event.is_set():
            try:
                self._process_frame()
            except Exception:
                logger.exception("Unhandled error in pipeline for lot=%s", self.lot_id)

        logger.info("Pipeline stopped for lot=%s", self.lot_id)

    def _process_frame(self):
        frame = self.frame_source.get_frame()
        if frame is None:
            logger.debug("pipeline.%s.frame_skipped reason=source_returned_none", self.lot_id)
            return

        self._frame_count += 1

        detections = self.detector.detect(frame)
        logger.debug(
            "pipeline.%s.detections count=%d", self.lot_id, len(detections)
        )

        tracked = self.tracker.update(detections, frame)
        active_ids = {t[0] for t in tracked}
        logger.debug(
            "pipeline.%s.tracks_active count=%d", self.lot_id, len(tracked)
        )

        for track_id, bbox, centroid in tracked:
            for tw in self.tripwires:
                crossing = tw.check_crossing(track_id, centroid)
                if crossing is not None:
                    avg_conf = sum(d[1] for d in detections) / len(detections) if detections else 1.0
                    logger.info(
                        "pipeline.%s.crossing_detected direction=%s track_id=%s confidence=%.2f",
                        self.lot_id, crossing, track_id, avg_conf,
                    )
                    self.emitter.emit(self.lot_id, crossing, avg_conf)

        # Clean up stale tracks from tripwires
        for tw in self.tripwires:
            tw.clear_stale_tracks(active_ids)
