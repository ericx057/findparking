"""Tests for lot attribute filters on the nearby endpoint."""


def _insert_lot(conn, lot_id, name, lat, lon, capacity=100, city="toronto",
                fare_type="paid", hourly_rate=None, is_covered=0,
                is_multi_level=0, is_above_ground=1):
    conn.execute(
        "INSERT INTO parking_lots "
        "(lot_id, name, latitude, longitude, capacity, current_occupancy, city, "
        "fare_type, hourly_rate, is_covered, is_multi_level, is_above_ground) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
        (lot_id, name, lat, lon, capacity, city,
         fare_type, hourly_rate, is_covered, is_multi_level, is_above_ground),
    )
    conn.commit()


def test_nearby_filter_by_fare_type(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-free", "Free Lot", 43.653, -79.383, fare_type="free")
    _insert_lot(conn, "lot-hourly", "Hourly Lot", 43.654, -79.384, fare_type="hourly", hourly_rate=5.0)

    resp = client.get("/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5&fare_type=free")
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "lot-free"


def test_nearby_filter_by_max_hourly_rate(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-cheap", "Cheap Lot", 43.653, -79.383, fare_type="hourly", hourly_rate=3.0)
    _insert_lot(conn, "lot-expensive", "Expensive Lot", 43.654, -79.384, fare_type="hourly", hourly_rate=10.0)
    _insert_lot(conn, "lot-free", "Free Lot", 43.655, -79.385, fare_type="free")

    resp = client.get("/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5&max_hourly_rate=5.0")
    assert resp.status_code == 200
    lots = resp.json()
    lot_ids = [l["lot_id"] for l in lots]
    assert "lot-cheap" in lot_ids
    assert "lot-free" in lot_ids
    assert "lot-expensive" not in lot_ids


def test_nearby_filter_by_covered(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-covered", "Covered Lot", 43.653, -79.383, is_covered=1)
    _insert_lot(conn, "lot-open", "Open Lot", 43.654, -79.384, is_covered=0)

    resp = client.get("/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5&is_covered=true")
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "lot-covered"


def test_nearby_filter_by_multi_level(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-ml", "Multi-Level", 43.653, -79.383, is_multi_level=1)
    _insert_lot(conn, "lot-flat", "Flat Lot", 43.654, -79.384, is_multi_level=0)

    resp = client.get("/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5&is_multi_level=true")
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "lot-ml"


def test_nearby_filter_by_above_ground(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-above", "Above Ground", 43.653, -79.383, is_above_ground=1)
    _insert_lot(conn, "lot-under", "Underground", 43.654, -79.384, is_above_ground=0)

    resp = client.get("/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5&is_above_ground=true")
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "lot-above"


def test_nearby_multiple_filters_combined(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-match", "Match", 43.653, -79.383,
                fare_type="hourly", hourly_rate=4.0, is_covered=1, is_multi_level=1)
    _insert_lot(conn, "lot-no-cover", "No Cover", 43.654, -79.384,
                fare_type="hourly", hourly_rate=4.0, is_covered=0, is_multi_level=1)
    _insert_lot(conn, "lot-expensive", "Expensive", 43.655, -79.385,
                fare_type="hourly", hourly_rate=20.0, is_covered=1, is_multi_level=1)

    resp = client.get(
        "/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5"
        "&is_covered=true&is_multi_level=true&max_hourly_rate=5.0"
    )
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "lot-match"


def test_nearby_no_filter_returns_all(client):
    conn = client.app.state.db_conn
    _insert_lot(conn, "lot-a", "Lot A", 43.653, -79.383, fare_type="free")
    _insert_lot(conn, "lot-b", "Lot B", 43.654, -79.384, fare_type="hourly", hourly_rate=10.0)

    resp = client.get("/api/lots/nearby?lat=43.653&lon=-79.383&radius_km=5")
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 2
