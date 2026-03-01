"""Tests for the demand heatmap signal module."""

import math
from unittest.mock import patch
from datetime import datetime, timezone

import pytest

from backend.database import get_connection, initialize_schema
from backend.demand_nodes import TIME_PROFILES, DAY_SCALES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", city="toronto", lat=43.65, lon=-79.38,
                capacity=100, fare_type="hourly"):
    conn.execute(
        "INSERT INTO parking_lots "
        "(lot_id, name, latitude, longitude, capacity, current_occupancy, city, fare_type) "
        "VALUES (?, 'Test', ?, ?, ?, 0, ?, ?)",
        (lot_id, lat, lon, capacity, city, fare_type),
    )
    conn.commit()


def _insert_demand_node(conn, node_id="osm-001", city="toronto",
                         category="retail", lat=43.65, lon=-79.38,
                         amplitude=0.5, sigma_km=0.3):
    conn.execute(
        "INSERT INTO cached_demand_nodes "
        "(node_id, city, source, category, lat, lon, amplitude, sigma_km, fetched_at) "
        "VALUES (?, ?, 'osm_poi', ?, ?, ?, ?, ?, datetime('now'))",
        (node_id, city, category, lat, lon, amplitude, sigma_km),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# gaussian_kernel tests
# ---------------------------------------------------------------------------

def test_gaussian_kernel_at_zero():
    from backend.signals.demand_heatmap import gaussian_kernel
    assert gaussian_kernel(0.0, 0.5) == 1.0


def test_gaussian_kernel_at_one_sigma():
    from backend.signals.demand_heatmap import gaussian_kernel
    result = gaussian_kernel(0.5, 0.5)
    expected = math.exp(-0.5)  # ~0.6065
    assert abs(result - expected) < 0.001


def test_gaussian_kernel_at_three_sigma():
    from backend.signals.demand_heatmap import gaussian_kernel
    result = gaussian_kernel(1.5, 0.5)
    assert result < 0.02  # effectively zero


def test_gaussian_kernel_zero_sigma():
    from backend.signals.demand_heatmap import gaussian_kernel
    assert gaussian_kernel(1.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# effective_sigma tests
# ---------------------------------------------------------------------------

def test_effective_sigma_no_intensity():
    from backend.signals.demand_heatmap import effective_sigma
    assert effective_sigma(0.5, 0.0, 0.5) == 0.5


def test_effective_sigma_half_intensity():
    from backend.signals.demand_heatmap import effective_sigma
    result = effective_sigma(0.5, 0.5, 0.5)
    assert abs(result - 0.625) < 0.001  # 0.5 * (1 + 0.5 * 0.5)


def test_effective_sigma_full_intensity():
    from backend.signals.demand_heatmap import effective_sigma
    result = effective_sigma(0.5, 1.0, 0.5)
    assert abs(result - 0.75) < 0.001  # 0.5 * (1 + 0.5 * 1.0)


# ---------------------------------------------------------------------------
# node_intensity tests
# ---------------------------------------------------------------------------

def test_node_intensity_transit_rush_hour():
    from backend.signals.demand_heatmap import node_intensity
    # Hour 8 (8am), Monday (0) -- peak commute
    result = node_intensity(8, 0, "transit")
    assert result >= 0.9  # TIME_PROFILES["transit"][8] * DAY_SCALES["transit"][0] = 1.0 * 1.0


def test_node_intensity_transit_overnight():
    from backend.signals.demand_heatmap import node_intensity
    # Hour 3 (3am), Monday
    result = node_intensity(3, 0, "transit")
    assert result < 0.05


def test_node_intensity_retail_weekend_afternoon():
    from backend.signals.demand_heatmap import node_intensity
    # Hour 14 (2pm), Saturday (5)
    result = node_intensity(14, 5, "retail")
    expected = TIME_PROFILES["retail"][14] * DAY_SCALES["retail"][5]
    assert abs(result - expected) < 0.001
    assert result > 0.8  # retail peaks on weekends


def test_node_intensity_commercial_sunday():
    from backend.signals.demand_heatmap import node_intensity
    # Hour 10 (10am), Sunday (6) -- offices closed
    result = node_intensity(10, 6, "commercial")
    expected = TIME_PROFILES["commercial"][10] * DAY_SCALES["commercial"][6]
    assert abs(result - expected) < 0.001
    assert result < 0.35  # commercial dead on weekends


# ---------------------------------------------------------------------------
# normalize_demand tests
# ---------------------------------------------------------------------------

def test_normalize_demand_zero():
    from backend.signals.demand_heatmap import normalize_demand
    assert normalize_demand(0.0) == 0.0


def test_normalize_demand_at_scale():
    from backend.signals.demand_heatmap import normalize_demand
    result = normalize_demand(0.8, 0.8)
    assert abs(result - 0.5) < 0.001


def test_normalize_demand_high():
    from backend.signals.demand_heatmap import normalize_demand
    result = normalize_demand(5.0, 0.8)
    assert result > 0.85


def test_normalize_demand_negative():
    from backend.signals.demand_heatmap import normalize_demand
    assert normalize_demand(-1.0) == 0.0


# ---------------------------------------------------------------------------
# demand_field_at tests
# ---------------------------------------------------------------------------

def test_demand_field_single_node_at_center():
    """Lot at the same location as a single node at peak intensity."""
    from backend.signals.demand_heatmap import demand_field_at

    nodes = [{"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "transit"}]
    # Monday 8am = peak transit
    result = demand_field_at(43.65, -79.38, nodes, hour=8, day_of_week=0)
    # amplitude * intensity * kernel_at_0 = 1.0 * 1.0 * 1.0 = 1.0
    assert abs(result - 1.0) < 0.01


def test_demand_field_single_node_far_away():
    """Lot 5km from node should get near-zero contribution."""
    from backend.signals.demand_heatmap import demand_field_at

    nodes = [{"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "transit"}]
    # ~5km north
    result = demand_field_at(43.695, -79.38, nodes, hour=8, day_of_week=0)
    assert result < 0.01


def test_demand_field_multiple_nodes_stack():
    """Two overlapping nodes produce more demand than one."""
    from backend.signals.demand_heatmap import demand_field_at

    single = [{"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "transit"}]
    double = [
        {"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "transit"},
        {"lat": 43.651, "lon": -79.381, "amplitude": 0.8, "sigma_km": 0.4, "category": "commercial"},
    ]
    r1 = demand_field_at(43.65, -79.38, single, hour=8, day_of_week=0)
    r2 = demand_field_at(43.65, -79.38, double, hour=8, day_of_week=0)
    assert r2 > r1


def test_demand_field_off_peak_lower_than_peak():
    """Same location, off-peak produces less demand than peak."""
    from backend.signals.demand_heatmap import demand_field_at

    nodes = [{"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "commercial"}]
    peak = demand_field_at(43.65, -79.38, nodes, hour=10, day_of_week=1)   # Tues 10am
    off = demand_field_at(43.65, -79.38, nodes, hour=3, day_of_week=1)     # Tues 3am
    assert peak > off * 5  # large difference


# ---------------------------------------------------------------------------
# demand_gradient_at tests
# ---------------------------------------------------------------------------

def test_gradient_near_zero_at_node_center():
    """Gradient should be near zero at the exact center of a single node."""
    from backend.signals.demand_heatmap import demand_gradient_at

    nodes = [{"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "transit"}]
    gx, gy = demand_gradient_at(43.65, -79.38, nodes, hour=8, day_of_week=0)
    magnitude = math.sqrt(gx ** 2 + gy ** 2)
    assert magnitude < 0.01


def test_gradient_points_toward_node():
    """From a point south of a node, the gradient y-component should be positive (toward node)."""
    from backend.signals.demand_heatmap import demand_gradient_at

    nodes = [{"lat": 43.65, "lon": -79.38, "amplitude": 1.0, "sigma_km": 0.5, "category": "transit"}]
    # Point south of node (lower lat)
    gx, gy = demand_gradient_at(43.645, -79.38, nodes, hour=8, day_of_week=0)
    # Gradient of demand points toward the source, which is north (positive y)
    assert gy > 0


# ---------------------------------------------------------------------------
# DemandHeatmapSignal.evaluate tests
# ---------------------------------------------------------------------------

def test_signal_returns_result_with_hardcoded_nodes(db_conn):
    """Toronto has hardcoded nodes, so a Toronto lot should get a result."""
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, city="toronto")
    signal = DemandHeatmapSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.source == "demand_heatmap"


def test_signal_returns_none_for_unknown_city(db_conn):
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, lot_id="lot-x", city="calgary", lat=51.05, lon=-114.07)
    signal = DemandHeatmapSignal()
    result = signal.evaluate(db_conn, "lot-x", 51.05, -114.07, "calgary", 100, 0)
    assert result is None


def test_signal_value_bounded(db_conn):
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, city="toronto")
    signal = DemandHeatmapSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert 0.05 <= result.value <= 0.95


def test_signal_confidence_without_osm(db_conn):
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, city="toronto")
    signal = DemandHeatmapSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.confidence == 0.45


def test_signal_confidence_with_osm(db_conn):
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, city="toronto")
    _insert_demand_node(db_conn, node_id="osm-1", city="toronto", lat=43.65, lon=-79.38)
    signal = DemandHeatmapSignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is not None
    assert result.confidence == 0.60


def test_downtown_peak_hour_low_availability(db_conn):
    """Near Financial District on a weekday morning should show low availability."""
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, city="toronto", lat=43.6488, lon=-79.3817)
    signal = DemandHeatmapSignal()

    # Mock time to Monday 10am EST (15:00 UTC)
    mock_dt = datetime(2026, 3, 2, 15, 0, 0, tzinfo=timezone.utc)  # Monday
    with patch("backend.signals.demand_heatmap.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        result = signal.evaluate(db_conn, "lot-001", 43.6488, -79.3817, "toronto", 100, 0)

    assert result is not None
    assert result.value < 0.40  # high demand = low availability


def test_night_time_high_availability(db_conn):
    """At 3am, even downtown should show high availability."""
    from backend.signals.demand_heatmap import DemandHeatmapSignal
    _insert_lot(db_conn, city="toronto", lat=43.6488, lon=-79.3817)
    signal = DemandHeatmapSignal()

    # Mock time to Monday 3am EST (08:00 UTC)
    mock_dt = datetime(2026, 3, 2, 8, 0, 0, tzinfo=timezone.utc)  # Monday 3am local
    with patch("backend.signals.demand_heatmap.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime
        result = signal.evaluate(db_conn, "lot-001", 43.6488, -79.3817, "toronto", 100, 0)

    assert result is not None
    assert result.value > 0.80  # very low demand = high availability
