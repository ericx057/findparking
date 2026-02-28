"""Tests for the city config API and city-filtered lots."""


def test_get_config_returns_active_city(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "active_city" in data
    assert "label" in data
    assert "center" in data
    assert "zoom" in data
    assert "cities" in data
    assert isinstance(data["cities"], dict)
    assert "waterloo" in data["cities"]
    assert "toronto" in data["cities"]
    assert "vancouver" in data["cities"]


def test_get_config_city_has_center_and_zoom(client):
    response = client.get("/api/config")
    data = response.json()
    for city_key, city_cfg in data["cities"].items():
        assert "center" in city_cfg, f"{city_key} missing center"
        assert "zoom" in city_cfg, f"{city_key} missing zoom"
        assert "label" in city_cfg, f"{city_key} missing label"
        assert len(city_cfg["center"]) == 2


def test_get_lots_filtered_by_city(client):
    conn = client.app.state.db_conn
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("wl-001", "Waterloo Lot", 43.46, -80.52, 100, 0, "waterloo"),
    )
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tor-001", "Toronto Lot", 43.65, -79.38, 200, 0, "toronto"),
    )
    conn.commit()

    # No filter: returns all
    response = client.get("/api/lots")
    assert response.status_code == 200
    assert len(response.json()) == 2

    # Filter by waterloo
    response = client.get("/api/lots?city=waterloo")
    assert response.status_code == 200
    lots = response.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "wl-001"

    # Filter by toronto
    response = client.get("/api/lots?city=toronto")
    assert response.status_code == 200
    lots = response.json()
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "tor-001"

    # Filter by vancouver: empty
    response = client.get("/api/lots?city=vancouver")
    assert response.status_code == 200
    assert len(response.json()) == 0
