import logging

logger = logging.getLogger("findparking.detector")


class VehicleDetector:
    """YOLOv8 wrapper that filters detections to vehicle classes only."""

    # COCO class IDs for vehicles
    VEHICLE_CLASSES = {2, 5, 7}  # car, bus, truck

    def __init__(self, model_path: str = "yolov8n.pt", confidence_threshold: float = 0.4):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._model = None

    def _load_model(self):
        from ultralytics import YOLO
        self._model = YOLO(self.model_path)
        logger.info("YOLOv8 model loaded: %s", self.model_path)

    def warmup(self):
        """Force model download and initialization at startup."""
        if self._model is None:
            self._load_model()

    def detect(self, frame):
        """Detect vehicles in a frame. Returns list of (bbox, confidence, class_id) tuples.

        bbox format: (x1, y1, x2, y2) in pixel coordinates.
        """
        if self._model is None:
            self._load_model()

        results = self._model.predict(
            frame,
            conf=self.confidence_threshold,
            verbose=False,
        )

        detections = []
        for result in results:
            for box in result.boxes:
                class_id = int(box.cls[0])
                if class_id not in self.VEHICLE_CLASSES:
                    continue
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(((x1, y1, x2, y2), conf, class_id))

        return detections
