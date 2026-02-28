import logging

logger = logging.getLogger("findparking.tracker")


class VehicleTracker:
    """DeepSORT wrapper for multi-object tracking."""

    def __init__(self, max_age: int = 30):
        self.max_age = max_age
        self._tracker = None

    def _init_tracker(self):
        from deep_sort_realtime.deepsort_tracker import DeepSort
        self._tracker = DeepSort(max_age=self.max_age)
        logger.info("DeepSORT tracker initialized (max_age=%d)", self.max_age)

    def update(self, detections, frame):
        """Update tracker with new detections.

        Args:
            detections: list of ((x1, y1, x2, y2), confidence, class_id) tuples
            frame: the current frame (used for appearance features)

        Returns:
            list of (track_id, bbox, centroid) tuples for active tracks
        """
        if self._tracker is None:
            self._init_tracker()

        # Convert detections to DeepSORT format: [[x1, y1, w, h], confidence, class_id]
        ds_detections = []
        for (x1, y1, x2, y2), conf, cls_id in detections:
            w = x2 - x1
            h = y2 - y1
            ds_detections.append(([x1, y1, w, h], conf, cls_id))

        tracks = self._tracker.update_tracks(ds_detections, frame=frame)

        results = []
        for track in tracks:
            if not track.is_confirmed():
                continue
            track_id = track.track_id
            ltrb = track.to_ltrb()
            x1, y1, x2, y2 = ltrb
            centroid = ((x1 + x2) / 2, (y1 + y2) / 2)
            results.append((track_id, (x1, y1, x2, y2), centroid))

        return results
