"""City configuration: search zones, camera providers, map centers, and lot seed data.

Each city defines its bounding box, available camera API sources, and default
map center for the frontend. Adding a new city is a config change -- add an
entry to CITIES and implement any new provider functions in camera_discovery.py.
"""

CITIES = {
    "waterloo": {
        "label": "Waterloo, ON",
        "center": [43.4643, -80.5204],
        "zoom": 14,
        "bounds": {
            "lat_min": 43.40,
            "lat_max": 43.55,
            "lon_min": -80.65,
            "lon_max": -80.40,
        },
        "providers": ["ontario_511"],
    },
    "toronto": {
        "label": "Toronto, ON",
        "center": [43.6532, -79.3832],
        "zoom": 12,
        "bounds": {
            "lat_min": 43.58,
            "lat_max": 43.78,
            "lon_min": -79.55,
            "lon_max": -79.25,
        },
        "providers": ["toronto_opendata", "ontario_511"],
    },
    "vancouver": {
        "label": "Vancouver, BC",
        "center": [49.2827, -123.1207],
        "zoom": 13,
        "bounds": {
            "lat_min": 49.18,
            "lat_max": 49.35,
            "lon_min": -123.30,
            "lon_max": -122.70,
        },
        "providers": ["drivebc", "vancouver_trafficcams"],
    },
}


def get_city_config(city: str) -> dict:
    """Return config for a city. Raises ValueError if unknown."""
    if city not in CITIES:
        raise ValueError(
            f"Unknown city: {city}. Available: {', '.join(CITIES.keys())}"
        )
    return CITIES[city]


def get_bounds(city: str) -> dict:
    return get_city_config(city)["bounds"]


def list_cities() -> list[str]:
    return list(CITIES.keys())
