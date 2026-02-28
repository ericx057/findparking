import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import ParkingFinderSettings
from backend.database import get_connection, initialize_schema
from backend.middleware.request_logger import RequestLoggerMiddleware
from backend.nightly_purge import purge_all_lots
from backend.routes.health import router as health_router
from backend.routes.parking_lots import router as lots_router
from backend.routes.vehicle_events import router as events_router
from backend.routes.city_config import router as config_router

logger = logging.getLogger("findparking")


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

    # Mount frontend static files last (catch-all)
    frontend_dir = Path(__file__).parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
