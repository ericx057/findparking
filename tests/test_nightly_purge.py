import logging

from tests.conftest import _insert_lot
from backend.nightly_purge import purge_all_lots
from backend.parking_lot_repository import get_lot


def test_purge_resets_all_lots(db_conn):
    _insert_lot(db_conn, "lot-p1", capacity=100, current_occupancy=80)
    _insert_lot(db_conn, "lot-p2", capacity=200, current_occupancy=150)

    purge_all_lots(db_conn)

    assert get_lot(db_conn, "lot-p1")["current_occupancy"] == 0
    assert get_lot(db_conn, "lot-p2")["current_occupancy"] == 0


def test_purge_handles_empty_db(db_conn):
    # Should not raise when no lots exist
    purge_all_lots(db_conn)


def test_purge_logs_action(db_conn, caplog):
    _insert_lot(db_conn, "lot-p3", capacity=100, current_occupancy=42)

    with caplog.at_level(logging.INFO):
        purge_all_lots(db_conn)

    assert "purge" in caplog.text.lower() or "reset" in caplog.text.lower()
