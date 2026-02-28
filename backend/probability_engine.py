def compute_vacancy_ratio(capacity: int, current_occupancy: int) -> float:
    """V(t) = (C - O(t)) / C, clamped to [0.0, 1.0]."""
    if capacity <= 0:
        raise ValueError(f"Capacity must be positive, got {capacity}")
    clamped = max(0, min(current_occupancy, capacity))
    return (capacity - clamped) / capacity


def compute_spot_probability(vacancy_ratio: float, time_weight: float) -> float:
    """P_spot = V(t) * W_h, clamped to [0.0, 1.0]."""
    if time_weight < 0:
        raise ValueError(f"Time weight must be non-negative, got {time_weight}")
    return max(0.0, min(1.0, vacancy_ratio * time_weight))


def classify_availability(probability_score: float) -> str:
    """Map probability to availability tier for frontend pin color."""
    if probability_score >= 0.75:
        return "high"
    elif probability_score >= 0.40:
        return "medium"
    else:
        return "low"


def compute_occupancy_delta(direction: str) -> int:
    """Convert direction string to occupancy change: inbound=+1, outbound=-1."""
    if direction == "inbound":
        return 1
    elif direction == "outbound":
        return -1
    else:
        raise ValueError(f"Invalid direction: {direction}")


def pin_color_from_probability(score: float) -> str:
    """Interpolate from red at 0.0 to green at 1.0 via HSL hue rotation.

    Returns an HSL color string usable in both CSS and Leaflet.
    Hue 0 = red, hue 142 = green (matching --accent-green).
    """
    clamped = max(0.0, min(1.0, score))
    hue = int(clamped * 142)
    return f"hsl({hue}, 72%, 52%)"
