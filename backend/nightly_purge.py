import logging
import sqlite3

from backend.parking_lot_repository import reset_all_occupancies

logger = logging.getLogger("findparking.purge")


def purge_all_lots(conn: sqlite3.Connection) -> None:
    """Reset all lot occupancies to zero. Called nightly to clear drift."""
    reset_all_occupancies(conn)
    logger.info("Nightly purge complete: all lot occupancies reset to 0")
