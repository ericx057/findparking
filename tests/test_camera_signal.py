"""Tests for camera signal -- specifically the no-event guard."""

import sqlite3

import pytest

from backend.database import initialize_schema
from backend.signals.camera import CameraSignal


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, city) "
        "VALUES ('test-lot', 'Test Lot', 43.0, -79.0, 200, 'toronto')"
    )
    conn.commit()
    return conn


def test_camera_returns_none_when_no_events():
    conn = _make_conn()
    signal = CameraSignal()
    result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "toronto", 200, 0)
    assert result is None


def test_camera_returns_result_when_events_exist():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO vehicle_events (lot_id, direction, confidence) "
        "VALUES ('test-lot', 'inbound', 1.0)"
    )
    conn.commit()
    signal = CameraSignal()
    result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "toronto", 200, 1)
    assert result is not None
    assert result.source == "camera"
    assert 0.0 <= result.value <= 1.0


def test_camera_returns_none_for_zero_capacity():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO vehicle_events (lot_id, direction, confidence) "
        "VALUES ('test-lot', 'inbound', 1.0)"
    )
    conn.commit()
    signal = CameraSignal()
    result = signal.evaluate(conn, "test-lot", 43.0, -79.0, "toronto", 0, 0)
    assert result is None
