import logging
import threading
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import ParkingFinderSettings
from backend.database import get_connection, initialize_schema
from backend.middleware.request_logger import RequestLoggerMiddleware
from backend.nightly_purge import purge_all_lots
from backend.signal_scheduler import (
    register_signal_jobs, refresh_weather, refresh_sports_events, refresh_lot_probabilities,
    refresh_team_streaks, refresh_air_quality, refresh_construction, refresh_holidays,
    refresh_economic_indicators,
)
from backend.routes.health import router as health_router
from backend.routes.parking_lots import router as lots_router
from backend.routes.vehicle_events import router as events_router
from backend.routes.city_config import router as config_router

logger = logging.getLogger("findparking")


def _initial_data_fetch(conn) -> None:
    """Best-effort startup data fetch. Runs in a daemon thread so the server
    can start accepting requests immediately. Every signal already returns
    None when its cache table is empty, so stale/missing data at startup is
    handled gracefully.
    """
    fetches = [
        ("weather", lambda: refresh_weather(conn)),
        ("sports_events", lambda: refresh_sports_events(conn)),
        ("demand_nodes", lambda: __import__(
            "backend.signals.demand_heatmap", fromlist=["refresh_osm_demand_nodes"]
        ).refresh_osm_demand_nodes(conn)),
        ("bikeshare", lambda: __import__(
            "backend.signals.bikeshare", fromlist=["refresh_bikeshare"]
        ).refresh_bikeshare(conn)),
        ("transit_alerts", lambda: __import__(
            "backend.signals.transit_disruptions", fromlist=["refresh_transit_alerts"]
        ).refresh_transit_alerts(conn)),
        ("festival_events", lambda: __import__(
            "backend.signals.festival_events", fromlist=["refresh_festival_events"]
        ).refresh_festival_events(conn)),
        ("team_streaks", lambda: refresh_team_streaks(conn)),
        ("lot_probabilities", lambda: refresh_lot_probabilities(conn)),
        ("air_quality", lambda: refresh_air_quality(conn)),
        ("construction", lambda: refresh_construction(conn)),
        ("holidays", lambda: refresh_holidays(conn)),
        ("economic_indicators", lambda: refresh_economic_indicators(conn)),
    ]

    for name, fetch_fn in fetches:
        try:
            fetch_fn()
        except Exception:
            logger.warning("initial %s fetch failed, will retry on schedule", name)

    logger.info("startup data fetch complete")


def create_app(db_path: str | None = None) -> FastAPI:
    settings = ParkingFinderSettings()
    resolved_db_path = db_path if db_path is not None else settings.db_path

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app = FastAPI(title="findparking", version="0.1.0")

    conn = get_connection(resolved_db_path)
    initialize_schema(conn)

    # Auto-seed if database has no parking lots (fresh deploy, skip for in-memory test DBs)
    if resolved_db_path != ":memory:":
        row = conn.execute("SELECT COUNT(*) FROM parking_lots").fetchone()
        if row[0] == 0:
            from seed_lots import seed
            logger.info("empty database detected, seeding parking lots")
            seed(db_path=resolved_db_path)
            # Re-read connection since seed() opens its own
            conn = get_connection(resolved_db_path)

    app.state.db_conn = conn
    app.state.settings = settings

    app.add_middleware(RequestLoggerMiddleware)

    app.include_router(health_router)
    app.include_router(lots_router)
    app.include_router(events_router)
    app.include_router(config_router)

    # Schedule nightly purge (skip for in-memory test DBs)
    if resolved_db_path != ":memory:":
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            purge_all_lots,
            trigger=CronTrigger(hour=settings.purge_hour),
            args=[conn],
            id="nightly_purge",
        )
        scheduler.start()
        app.state.scheduler = scheduler

        # Register signal refresh jobs
        register_signal_jobs(scheduler, conn, ticketmaster_api_key=settings.ticketmaster_api_key)

        # Run initial data fetches in a background thread so the server
        # starts accepting requests immediately instead of blocking on
        # 12 sequential external API calls (~30-120s).
        t = threading.Thread(target=_initial_data_fetch, args=(conn,), daemon=True)
        t.start()

    # Mount frontend static files last (catch-all)
    frontend_dir = Path(__file__).parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
