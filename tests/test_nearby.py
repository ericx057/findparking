"""Tests for the nearby lots API endpoint."""

import pytest


def test_nearby_returns_sorted_by_distance(client):
    conn = client.app.state.db_conn
    # Seed 3 Toronto lots at known coordinates
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tor-far", "Far Lot", 43.67, -79.40, 100, 0, "toronto"),
    )
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tor-near", "Near Lot", 43.6455, -79.3810, 100, 0, "toronto"),
    )
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tor-mid", "Mid Lot", 43.655, -79.39, 100, 0, "toronto"),
    )
    conn.commit()

    # Search from Union Station (43.6453, -79.3806)
    response = client.get("/api/lots/nearby?lat=43.6453&lon=-79.3806&radius_km=5")
    assert response.status_code == 200
    lots = response.json()
    assert len(lots) == 3
    # Should be sorted by distance
    assert lots[0]["lot_id"] == "tor-near"
    assert lots[1]["lot_id"] == "tor-mid"
    assert lots[2]["lot_id"] == "tor-far"


def test_nearby_respects_radius(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("close-lot", "Close", 43.646, -79.381, 100, 0, "toronto"),
    )
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("far-lot", "Far Away", 49.28, -123.12, 100, 0, "vancouver"),
    )
    conn.commit()

    # Small radius: only close lot
    response = client.get("/api/lots/nearby?lat=43.6453&lon=-79.3806&radius_km=1")
    assert response.status_code == 200
    lots = response.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "close-lot"


def test_nearby_includes_distance_km(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("dist-lot", "Distance Test", 43.655, -79.39, 200, 50, "toronto"),
    )
    conn.commit()

    response = client.get("/api/lots/nearby?lat=43.6453&lon=-79.3806&radius_km=5")
    lots = response.json()
    assert len(lots) == 1
    assert "distance_km" in lots[0]
    assert lots[0]["distance_km"] > 0


def test_nearby_includes_probability_fields(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("prob-lot", "Prob Test", 43.646, -79.381, 400, 100, "toronto"),
    )
    conn.commit()

    response = client.get("/api/lots/nearby?lat=43.6453&lon=-79.3806&radius_km=5")
    lots = response.json()
    assert len(lots) == 1
    lot = lots[0]
    assert "probability_score" in lot
    assert "availability" in lot
    assert "vacancy_ratio" in lot
    assert lot["availability"] in ("high", "medium", "low", "stale")


def test_nearby_respects_limit(client):
    conn = client.app.state.db_conn
    for i in range(5):
        conn.execute(
            "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"lim-{i}", f"Lot {i}", 43.645 + i * 0.001, -79.381, 100, 0, "toronto"),
        )
    conn.commit()

    response = client.get("/api/lots/nearby?lat=43.645&lon=-79.381&radius_km=5&limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_nearby_missing_params_returns_422(client):
    response = client.get("/api/lots/nearby")
    assert response.status_code == 422

    response = client.get("/api/lots/nearby?lat=43.65")
    assert response.status_code == 422


def test_nearby_empty_radius_returns_empty(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("empty-lot", "Empty Radius", 43.65, -79.38, 100, 0, "toronto"),
    )
    conn.commit()

    # Search from Vancouver -- nothing in 0.1 km radius
    response = client.get("/api/lots/nearby?lat=49.28&lon=-123.12&radius_km=0.1")
    assert response.status_code == 200
    assert response.json() == []
