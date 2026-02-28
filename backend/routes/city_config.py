from fastapi import APIRouter, Request

from cv_pipeline.city_config import CITIES

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config(request: Request):
    """Return city configuration for the frontend.

    Includes the active city setting plus all available cities
    with their map center, zoom, label, and bounds.
    """
    settings = request.app.state.settings
    active_city = settings.city

    active_config = CITIES.get(active_city)
    if active_config is None:
        active_config = CITIES["waterloo"]
        active_city = "waterloo"

    return {
        "active_city": active_city,
        "label": active_config["label"],
        "center": active_config["center"],
        "zoom": active_config["zoom"],
        "cities": {
            key: {
                "label": cfg["label"],
                "center": cfg["center"],
                "zoom": cfg["zoom"],
            }
            for key, cfg in CITIES.items()
        },
    }
