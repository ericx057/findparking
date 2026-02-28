def test_health_returns_200(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_health_timestamp_is_iso_format(client):
    response = client.get("/api/health")
    body = response.json()
    # ISO 8601 timestamps contain 'T' separator
    assert "T" in body["timestamp"]
