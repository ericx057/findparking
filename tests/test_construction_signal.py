"""Tests for the construction proximity signal module."""

import json
import math
import sqlite3

import pytest

from backend.database import initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_construction(conn, project_id="proj-001", city="toronto",
                         lat=43.65, lon=-79.38, description="Road work",
                         status="active", start_year=2025,
                         geometry_type=None, geometry_json=None):
    conn.execute(
        "INSERT INTO cached_construction "
        "(project_id, city, description, lat, lon, status, start_year, "
        "geometry_type, geometry_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (project_id, city, description, lat, lon, status, start_year,
         geometry_type, geometry_json),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_construction_returns_none(db_conn):
    """No construction data cached -> None."""
    from backend.signals.construction_proximity import ConstructionProximitySignal

    signal = ConstructionProximitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_project_100m_away_increases_value(db_conn):
    """Construction ~100m away should increase availability (hard to reach)."""
    from backend.signals.construction_proximity import ConstructionProximitySignal

    # ~100m north of lot
    _insert_construction(db_conn, lat=43.6509, lon=-79.38)

    signal = ConstructionProximitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.source == "construction_proximity"
    assert result.value > 1.0
    # impact ~ 0.15 * exp(-0.693 * 0.1 / 0.3) ~ 0.119 -> value ~ 1.119
    assert 1.08 < result.value < 1.16
    assert result.confidence == 0.50


def test_project_2km_away_returns_none(db_conn):
    """Construction 2km away is beyond the 1.0km range -> None."""
    from backend.signals.construction_proximity import ConstructionProximitySignal

    # ~2km north of lot
    _insert_construction(db_conn, lat=43.668, lon=-79.38)

    signal = ConstructionProximitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)
    assert result is None


def test_multiple_projects_capped(db_conn):
    """Multiple nearby projects stack but impact is capped at 0.25."""
    from backend.signals.construction_proximity import ConstructionProximitySignal

    # Three projects very close (~50m, ~100m, ~135m)
    for i in range(3):
        _insert_construction(
            db_conn,
            project_id=f"proj-{i}",
            lat=43.65 + 0.00045 * (i + 1),
            lon=-79.38,
        )

    signal = ConstructionProximitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.value == round(1.0 + 0.25, 4)  # capped at 0.25


def test_line_geometry_distance(db_conn):
    """Line geometry uses vertex-based minimum distance."""
    from backend.signals.construction_proximity import ConstructionProximitySignal

    # LineString passing near the lot (GeoJSON: [lon, lat])
    line_coords = [
        [-79.3788, 43.648],   # south vertex
        [-79.3788, 43.652],   # north vertex
    ]
    _insert_construction(
        db_conn,
        project_id="line-001",
        lat=43.65,         # centroid lat
        lon=-79.3788,      # centroid lon
        geometry_type="line",
        geometry_json=json.dumps(line_coords),
    )

    signal = ConstructionProximitySignal()
    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert result.value > 1.0


def test_configurable_half_life(db_conn):
    """Half-life can be overridden via signal_params."""
    from backend.signals.construction_proximity import ConstructionProximitySignal

    # Insert a project ~100m away
    _insert_construction(db_conn, lat=43.6509, lon=-79.38)

    signal = ConstructionProximitySignal()

    # Get baseline result with default half-life (0.3 km)
    baseline = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    # Set a larger half-life (slower decay -> more impact at same distance)
    db_conn.execute(
        "INSERT INTO signal_params (signal_name, param_key, param_value) "
        "VALUES (?, ?, ?)",
        ("construction_proximity", "half_life_km", 0.6),
    )
    db_conn.commit()

    result = signal.evaluate(db_conn, "lot-001", 43.65, -79.38, "toronto", 100, 0)

    assert result is not None
    assert baseline is not None
    # Larger half-life means slower decay, so more impact -> higher value
    assert result.value > baseline.value
