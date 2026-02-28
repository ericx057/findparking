import pytest
from fastapi.testclient import TestClient

from backend.database import get_connection, initialize_schema
from backend.main import create_app


@pytest.fixture
def app():
    return create_app(db_path=":memory:")


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def db_conn():
    """In-memory SQLite connection with schema initialized."""
    conn = get_connection(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _insert_lot(conn, lot_id="lot-001", name="Test Lot", latitude=43.46,
                longitude=-80.52, capacity=100, current_occupancy=0):
    """Helper to insert a parking lot for tests."""
    conn.execute(
        "INSERT INTO parking_lots (lot_id, name, latitude, longitude, capacity, current_occupancy) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (lot_id, name, latitude, longitude, capacity, current_occupancy),
    )
    conn.commit()


@pytest.fixture
def seeded_db(db_conn):
    """DB with 3 test lots pre-inserted."""
    _insert_lot(db_conn, "lot-001", "Town Square", 43.4621, -80.5241, 400, 0)
    _insert_lot(db_conn, "lot-002", "UW Lot C", 43.4723, -80.5449, 600, 50)
    _insert_lot(db_conn, "lot-003", "Uptown Garage", 43.4648, -80.5226, 500, 250)
    return db_conn
