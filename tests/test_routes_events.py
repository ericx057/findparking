import pytest


def test_post_event_inbound(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lot-ev1", "Test Lot", 43.46, -80.52, 100, 0),
    )
    conn.commit()

    response = client.post("/api/lots/lot-ev1/events", json={"direction": "inbound"})
    assert response.status_code == 201

    # Verify occupancy increased
    lot_resp = client.get("/api/lots/lot-ev1")
    assert lot_resp.json()["current_occupancy"] == 1


def test_post_event_outbound(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lot-ev2", "Test Lot 2", 43.46, -80.52, 100, 5),
    )
    conn.commit()

    response = client.post("/api/lots/lot-ev2/events", json={"direction": "outbound"})
    assert response.status_code == 201

    lot_resp = client.get("/api/lots/lot-ev2")
    assert lot_resp.json()["current_occupancy"] == 4


def test_post_event_invalid_direction(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lot-ev3", "Test Lot 3", 43.46, -80.52, 100, 0),
    )
    conn.commit()

    response = client.post("/api/lots/lot-ev3/events", json={"direction": "sideways"})
    assert response.status_code == 422


def test_post_event_nonexistent_lot(client):
    response = client.post("/api/lots/nonexistent/events", json={"direction": "inbound"})
    assert response.status_code == 404
