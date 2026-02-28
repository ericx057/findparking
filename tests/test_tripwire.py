from cv_pipeline.tripwire import Tripwire


def test_first_observation_returns_none():
    tw = Tripwire(0, 0, 10, 0)
    assert tw.check_crossing(1, (5, 5)) is None


def test_no_crossing_same_side():
    tw = Tripwire(0, 0, 10, 0)  # horizontal line
    tw.check_crossing(1, (5, 5))   # above line
    assert tw.check_crossing(1, (5, 3)) is None  # still above


def test_inbound_crossing():
    tw = Tripwire(0, 0, 10, 0)
    tw.check_crossing(1, (5, 5))   # above line (positive side)
    assert tw.check_crossing(1, (5, -5)) == "inbound"


def test_outbound_crossing():
    tw = Tripwire(0, 0, 10, 0)
    tw.check_crossing(1, (5, -5))  # below line (negative side)
    assert tw.check_crossing(1, (5, 5)) == "outbound"


def test_multiple_vehicles_tracked_independently():
    tw = Tripwire(0, 0, 10, 0)
    tw.check_crossing(1, (5, 5))
    tw.check_crossing(2, (5, -5))
    assert tw.check_crossing(1, (5, -5)) == "inbound"
    assert tw.check_crossing(2, (5, 5)) == "outbound"


def test_diagonal_tripwire():
    tw = Tripwire(0, 0, 10, 10)  # diagonal line
    tw.check_crossing(1, (0, 10))  # left side of diagonal
    assert tw.check_crossing(1, (10, 0)) == "inbound"


def test_clear_stale_tracks():
    tw = Tripwire(0, 0, 10, 0)
    tw.check_crossing(1, (5, 5))
    tw.check_crossing(2, (5, 5))
    tw.clear_stale_tracks({1})
    assert 2 not in tw._previous_side
    assert 1 in tw._previous_side


def test_vehicle_on_line_exact():
    tw = Tripwire(0, 0, 10, 0)
    tw.check_crossing(1, (5, 5))
    # Moving from above to exactly on the line (cross product = 0)
    result = tw.check_crossing(1, (5, 0))
    assert result == "inbound"
