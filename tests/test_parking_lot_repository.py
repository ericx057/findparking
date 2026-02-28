from tests.conftest import _insert_lot
from backend.parking_lot_repository import (
    get_all_lots,
    get_lot,
    update_occupancy,
    reset_occupancy,
)


def test_get_all_lots_empty(db_conn):
    lots = get_all_lots(db_conn)
    assert lots == []


def test_get_all_lots_returns_all(seeded_db):
    lots = get_all_lots(seeded_db)
    assert len(lots) == 3


def test_get_lot_by_id(seeded_db):
    lot = get_lot(seeded_db, "lot-001")
    assert lot is not None
    assert lot["lot_id"] == "lot-001"
    assert lot["name"] == "Town Square"
    assert lot["capacity"] == 400


def test_get_nonexistent_lot_returns_none(db_conn):
    assert get_lot(db_conn, "nonexistent") is None


def test_update_occupancy_increments(db_conn):
    _insert_lot(db_conn, "lot-t1", capacity=100, current_occupancy=0)
    update_occupancy(db_conn, "lot-t1", delta=1)
    lot = get_lot(db_conn, "lot-t1")
    assert lot["current_occupancy"] == 1


def test_update_occupancy_decrements(db_conn):
    _insert_lot(db_conn, "lot-t2", capacity=100, current_occupancy=5)
    update_occupancy(db_conn, "lot-t2", delta=-1)
    lot = get_lot(db_conn, "lot-t2")
    assert lot["current_occupancy"] == 4


def test_occupancy_never_below_zero(db_conn):
    _insert_lot(db_conn, "lot-t3", capacity=100, current_occupancy=0)
    update_occupancy(db_conn, "lot-t3", delta=-1)
    lot = get_lot(db_conn, "lot-t3")
    assert lot["current_occupancy"] == 0


def test_occupancy_never_above_capacity(db_conn):
    _insert_lot(db_conn, "lot-t4", capacity=2, current_occupancy=2)
    update_occupancy(db_conn, "lot-t4", delta=1)
    lot = get_lot(db_conn, "lot-t4")
    assert lot["current_occupancy"] == 2


def test_reset_occupancy(db_conn):
    _insert_lot(db_conn, "lot-t5", capacity=100, current_occupancy=50)
    reset_occupancy(db_conn, "lot-t5")
    lot = get_lot(db_conn, "lot-t5")
    assert lot["current_occupancy"] == 0
