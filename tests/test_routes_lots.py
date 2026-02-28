import pytest


def test_get_lots_empty(client):
    response = client.get("/api/lots")
    assert response.status_code == 200
    assert response.json() == []


def test_get_lots_returns_scores(client):
    # Seed a lot directly via the app's db connection
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lot-001", "Town Square", 43.4621, -80.5241, 400, 100),
    )
    conn.commit()

    response = client.get("/api/lots")
    assert response.status_code == 200
    lots = response.json()
    assert len(lots) == 1

    lot = lots[0]
    assert "probability_score" in lot
    assert "availability" in lot
    assert "vacancy_ratio" in lot
    assert lot["availability"] in ("high", "medium", "low")


def test_get_lot_by_id(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lot-002", "UW Lot C", 43.4723, -80.5449, 600, 50),
    )
    conn.commit()

    response = client.get("/api/lots/lot-002")
    assert response.status_code == 200
    lot = response.json()
    assert lot["lot_id"] == "lot-002"
    assert lot["name"] == "UW Lot C"
    assert "probability_score" in lot


def test_get_lot_not_found(client):
    response = client.get("/api/lots/nonexistent")
    assert response.status_code == 404


def test_get_lot_history(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lot-003", "Uptown Garage", 43.4648, -80.5226, 500, 0),
    )
    conn.execute(
        "INSERT INTO occupancy_snapshots (lot_id, occupancy, vacancy_ratio, probability_score) "
        "VALUES (?, ?, ?, ?)",
        ("lot-003", 100, 0.8, 0.8),
    )
    conn.commit()

    response = client.get("/api/lots/lot-003/history")
    assert response.status_code == 200
    history = response.json()
    assert len(history) >= 1
    assert history[0]["lot_id"] == "lot-003"
