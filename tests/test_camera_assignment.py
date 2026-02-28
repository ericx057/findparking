"""Tests for camera-to-lot auto-assignment."""

import sqlite3

from backend.database import get_connection, initialize_schema
from backend.geo import haversine_km


def _make_conn():
    conn = get_connection(":memory:")
    initialize_schema(conn)
    return conn


def _insert_lot(conn, lot_id, name, lat, lon, capacity=100, city="toronto"):
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (lot_id, name, lat, lon, capacity, city),
    )
    conn.commit()


def _make_camera(camera_id, name, lat, lon, image_url="http://example.com/cam.jpg", source="test"):
    return {
        "camera_id": camera_id,
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "image_url": image_url,
        "source": source,
    }


def test_assign_nearest_camera_to_lot():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Test Lot", 43.6532, -79.3832, city="toronto")

    cameras = [
        _make_camera("cam-far", "Far Cam", 43.70, -79.40),
        _make_camera("cam-near", "Near Cam", 43.6535, -79.3835),
    ]

    assign_cameras_to_lots(conn, "toronto", cameras, max_distance_km=5.0)

    rows = conn.execute("SELECT * FROM camera_assignments WHERE lot_id = 'lot-1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["camera_id"] == "cam-near"


def test_assign_respects_max_distance():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Test Lot", 43.6532, -79.3832, city="toronto")

    # Camera 50+ km away
    cameras = [
        _make_camera("cam-far", "Far Cam", 44.0, -79.0),
    ]

    assign_cameras_to_lots(conn, "toronto", cameras, max_distance_km=2.0)

    rows = conn.execute("SELECT * FROM camera_assignments WHERE lot_id = 'lot-1'").fetchall()
    assert len(rows) == 0


def test_assign_multiple_lots():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Lot A", 43.6532, -79.3832, city="toronto")
    _insert_lot(conn, "lot-2", "Lot B", 43.6600, -79.3900, city="toronto")

    cameras = [
        _make_camera("cam-1", "Cam 1", 43.6535, -79.3835),
        _make_camera("cam-2", "Cam 2", 43.6605, -79.3905),
    ]

    assign_cameras_to_lots(conn, "toronto", cameras, max_distance_km=2.0)

    rows_1 = conn.execute("SELECT * FROM camera_assignments WHERE lot_id = 'lot-1'").fetchall()
    rows_2 = conn.execute("SELECT * FROM camera_assignments WHERE lot_id = 'lot-2'").fetchall()
    assert len(rows_1) == 1
    assert len(rows_2) == 1
    assert rows_1[0]["camera_id"] == "cam-1"
    assert rows_2[0]["camera_id"] == "cam-2"


def test_assign_no_cameras_nearby():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Test Lot", 43.6532, -79.3832, city="toronto")

    # No cameras at all
    assign_cameras_to_lots(conn, "toronto", [], max_distance_km=2.0)

    rows = conn.execute("SELECT * FROM camera_assignments WHERE lot_id = 'lot-1'").fetchall()
    assert len(rows) == 0


def test_assignment_stored_in_db():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Test Lot", 43.6532, -79.3832, city="toronto")

    cameras = [
        _make_camera("cam-1", "Cam 1", 43.6535, -79.3835, "http://example.com/cam1.jpg", "toronto_opendata"),
    ]

    assign_cameras_to_lots(conn, "toronto", cameras, max_distance_km=2.0)

    row = conn.execute("SELECT * FROM camera_assignments WHERE lot_id = 'lot-1'").fetchone()
    assert row is not None
    assert row["camera_id"] == "cam-1"
    assert row["image_url"] == "http://example.com/cam1.jpg"
    assert row["source"] == "toronto_opendata"
    assert row["distance_km"] > 0
    assert row["assigned_at"] is not None


def test_reassignment_replaces_old():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Test Lot", 43.6532, -79.3832, city="toronto")

    # First assignment
    cameras_v1 = [
        _make_camera("cam-old", "Old Cam", 43.654, -79.384),
    ]
    assign_cameras_to_lots(conn, "toronto", cameras_v1, max_distance_km=5.0)

    row = conn.execute("SELECT camera_id FROM camera_assignments WHERE lot_id = 'lot-1'").fetchone()
    assert row["camera_id"] == "cam-old"

    # Second assignment with a closer camera
    cameras_v2 = [
        _make_camera("cam-new", "New Cam", 43.6533, -79.3833),
    ]
    assign_cameras_to_lots(conn, "toronto", cameras_v2, max_distance_km=5.0)

    rows = conn.execute("SELECT camera_id FROM camera_assignments WHERE lot_id = 'lot-1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["camera_id"] == "cam-new"


def test_generate_cameras_json_format():
    from cv_pipeline.camera_assignment import assign_cameras_to_lots, generate_cameras_config

    conn = _make_conn()
    _insert_lot(conn, "lot-1", "Test Lot", 43.6532, -79.3832, city="toronto")

    cameras = [
        _make_camera("cam-1", "Cam 1", 43.6535, -79.3835, "http://example.com/cam1.jpg"),
    ]

    assign_cameras_to_lots(conn, "toronto", cameras, max_distance_km=2.0)

    config = generate_cameras_config(conn, "toronto")
    assert "cameras" in config
    assert len(config["cameras"]) == 1

    cam_cfg = config["cameras"][0]
    assert cam_cfg["lot_id"] == "lot-1"
    assert cam_cfg["camera_url"] == "http://example.com/cam1.jpg"
    assert "tripwires" in cam_cfg
    assert len(cam_cfg["tripwires"]) == 1
    tw = cam_cfg["tripwires"][0]
    assert "x1" in tw and "y1" in tw and "x2" in tw and "y2" in tw
