class Tripwire:
    """Bidirectional virtual tripwire using cross-product line-crossing detection."""

    def __init__(self, x1, y1, x2, y2):
        self.p1 = (x1, y1)
        self.p2 = (x2, y2)
        self._previous_side: dict[int, float] = {}

    def _cross_product_sign(self, point):
        """Positive = left side, negative = right side, zero = on the line."""
        dx = self.p2[0] - self.p1[0]
        dy = self.p2[1] - self.p1[1]
        px = point[0] - self.p1[0]
        py = point[1] - self.p1[1]
        return dx * py - dy * px

    def check_crossing(self, track_id: int, centroid: tuple) -> str | None:
        """Returns 'inbound', 'outbound', or None."""
        current_side = self._cross_product_sign(centroid)
        previous_side = self._previous_side.get(track_id)
        self._previous_side[track_id] = current_side

        if previous_side is None:
            return None

        if previous_side > 0 and current_side <= 0:
            return "inbound"
        elif previous_side <= 0 and current_side > 0:
            return "outbound"

        return None

    def clear_stale_tracks(self, active_track_ids: set) -> None:
        """Remove tracks no longer being tracked by DeepSORT."""
        stale = set(self._previous_side.keys()) - active_track_ids
        for track_id in stale:
            del self._previous_side[track_id]
