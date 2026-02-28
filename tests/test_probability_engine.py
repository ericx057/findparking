import pytest

from backend.probability_engine import (
    classify_availability,
    compute_occupancy_delta,
    compute_spot_probability,
    compute_vacancy_ratio,
)


# --- compute_vacancy_ratio ---

def test_vacancy_ratio_empty_lot():
    assert compute_vacancy_ratio(100, 0) == 1.0


def test_vacancy_ratio_full_lot():
    assert compute_vacancy_ratio(100, 100) == 0.0


def test_vacancy_ratio_half_full():
    assert compute_vacancy_ratio(100, 50) == 0.5


def test_vacancy_ratio_clamps_over_capacity():
    assert compute_vacancy_ratio(100, 150) == 0.0


def test_vacancy_ratio_clamps_negative_occupancy():
    assert compute_vacancy_ratio(100, -5) == 1.0


def test_vacancy_ratio_rejects_zero_capacity():
    with pytest.raises(ValueError, match="positive"):
        compute_vacancy_ratio(0, 0)


def test_vacancy_ratio_rejects_negative_capacity():
    with pytest.raises(ValueError, match="positive"):
        compute_vacancy_ratio(-10, 5)


# --- compute_spot_probability ---

def test_spot_probability_normal():
    assert compute_spot_probability(0.5, 1.0) == 0.5


def test_spot_probability_with_high_weight():
    assert compute_spot_probability(0.8, 0.5) == pytest.approx(0.4)


def test_spot_probability_clamps_above_one():
    assert compute_spot_probability(0.9, 1.5) == 1.0


def test_spot_probability_zero_vacancy():
    assert compute_spot_probability(0.0, 1.2) == 0.0


def test_spot_probability_rejects_negative_weight():
    with pytest.raises(ValueError, match="non-negative"):
        compute_spot_probability(0.5, -1.0)


# --- classify_availability ---

def test_classify_high_above_threshold():
    assert classify_availability(0.80) == "high"


def test_classify_medium():
    assert classify_availability(0.50) == "medium"


def test_classify_low():
    assert classify_availability(0.20) == "low"


def test_classify_boundary_75_is_high():
    assert classify_availability(0.75) == "high"


def test_classify_boundary_40_is_medium():
    assert classify_availability(0.40) == "medium"


def test_classify_zero_is_low():
    assert classify_availability(0.0) == "low"


def test_classify_one_is_high():
    assert classify_availability(1.0) == "high"


# --- compute_occupancy_delta ---

def test_delta_inbound():
    assert compute_occupancy_delta("inbound") == 1


def test_delta_outbound():
    assert compute_occupancy_delta("outbound") == -1


def test_delta_invalid_direction():
    with pytest.raises(ValueError, match="Invalid direction"):
        compute_occupancy_delta("sideways")
