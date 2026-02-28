"""Entry point for the CV pipeline. Runs one thread per camera."""

import json
import logging
import signal
import threading

from cv_pipeline.config import load_cameras_config
from cv_pipeline.event_emitter import HttpEventEmitter
from cv_pipeline.frame_source import HttpJpegSource
from cv_pipeline.pipeline import ParkingPipeline
from cv_pipeline.tripwire import Tripwire
from cv_pipeline.vehicle_detector import VehicleDetector
from cv_pipeline.vehicle_tracker import VehicleTracker

logger = logging.getLogger("findparking.runner")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cameras = load_cameras_config("cameras.json")
    if not cameras:
        logger.error("No cameras configured in cameras.json")
        return

    backend_url = "http://localhost:8000"
    stop_event = threading.Event()
    threads = []

    for cam in cameras:
        source = HttpJpegSource(cam.camera_url, cam.poll_interval_seconds)
        detector = VehicleDetector()
        tracker = VehicleTracker()
        tripwires = [
            Tripwire(tw.x1, tw.y1, tw.x2, tw.y2) for tw in cam.tripwires
        ]
        emitter = HttpEventEmitter(backend_url)

        pipeline = ParkingPipeline(
            source, detector, tracker, tripwires, emitter, cam.lot_id, stop_event
        )

        t = threading.Thread(
            target=pipeline.run,
            name=f"pipeline-{cam.lot_id}",
            daemon=True,
        )
        threads.append(t)
        t.start()
        logger.info("Started pipeline thread for lot=%s", cam.lot_id)

    def handle_signal(*_):
        logger.info("Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("All pipelines running. Press Ctrl+C to stop.")
    stop_event.wait()

    for t in threads:
        t.join(timeout=5)

    logger.info("All pipelines stopped.")


if __name__ == "__main__":
    main()
