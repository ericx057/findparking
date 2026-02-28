"""Fetch parking lot data from OpenStreetMap via the Overpass API.

Queries for amenity=parking within a bounding box and maps OSM tags
to our internal parking lot schema. Used during seeding to populate
real-world parking lot locations.
"""

import logging

import httpx

from backend.geo import haversine_km

logger = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_TIMEOUT = 60

# OSM access values that indicate non-public parking
_PRIVATE_ACCESS = {"private", "no", "customers", "permit", "delivery"}

# Default capacity when OSM doesn't have the tag
_DEFAULT_CAPACITY = 50


def _parse_osm_element(element: dict, city: str) -> dict | None:
    """Convert a single OSM element to our lot dict format.

    Returns None if the element should be skipped (private, missing coords).
    """
    tags = element.get("tags", {})

    # Skip private/restricted lots
    access = tags.get("access", "")
    if access in _PRIVATE_ACCESS:
        return None

    # Get coordinates
    elem_type = element["type"]
    if elem_type == "node":
        lat = element.get("lat")
        lon = element.get("lon")
    else:
        # Ways and relations use center from 'out center'
        center = element.get("center")
        if not center:
            return None
        lat = center.get("lat")
        lon = center.get("lon")

    if lat is None or lon is None:
        return None

    # lot_id from OSM type + id
    lot_id = f"osm-{elem_type}-{element['id']}"

    # Name: use tag or fallback
    name = tags.get("name", "Parking Lot")

    # Capacity
    capacity = _DEFAULT_CAPACITY
    raw_cap = tags.get("capacity", "")
    try:
        parsed = int(raw_cap)
        if parsed > 0:
            capacity = parsed
    except (ValueError, TypeError):
        pass

    # Fare type from fee tag
    fee = tags.get("fee", "").lower()
    if fee in ("no", "free"):
        fare_type = "free"
    elif fee in ("yes",):
        fare_type = "hourly"
    else:
        fare_type = "free"  # Default unknown to free

    # Structure from parking tag
    parking_type = tags.get("parking", "surface").lower()

    if parking_type in ("multi-storey",):
        is_covered = 1
        is_multi_level = 1
        is_above_ground = 1
    elif parking_type in ("underground",):
        is_covered = 1
        is_multi_level = 1
        is_above_ground = 0
    elif parking_type in ("rooftop",):
        is_covered = 0
        is_multi_level = 0
        is_above_ground = 1
    else:
        # surface, street_side, etc.
        is_covered = 0
        is_multi_level = 0
        is_above_ground = 1

    return {
        "lot_id": lot_id,
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "capacity": capacity,
        "fare_type": fare_type,
        "hourly_rate": None,
        "is_covered": is_covered,
        "is_multi_level": is_multi_level,
        "is_above_ground": is_above_ground,
        "city": city,
    }


def _is_duplicate(
    lat: float, lon: float, existing: list[dict], threshold_km: float = 0.1
) -> bool:
    """Check if a coordinate is within threshold_km of any existing lot."""
    for lot in existing:
        dist = haversine_km(lat, lon, lot["latitude"], lot["longitude"])
        if dist <= threshold_km:
            return True
    return False


def fetch_osm_parking(bounds: dict, city: str) -> list[dict]:
    """Fetch all public parking lots within bounds from OpenStreetMap.

    Args:
        bounds: dict with lat_min, lat_max, lon_min, lon_max
        city: city name to tag lots with

    Returns:
        List of lot dicts ready for DB insertion.
    """
    bbox = f"{bounds['lat_min']},{bounds['lon_min']},{bounds['lat_max']},{bounds['lon_max']}"

    query = f"""
    [out:json][timeout:{_OVERPASS_TIMEOUT}];
    (
      node["amenity"="parking"]({bbox});
      way["amenity"="parking"]({bbox});
      relation["amenity"="parking"]({bbox});
    );
    out center;
    """

    try:
        resp = httpx.post(
            _OVERPASS_URL,
            data={"data": query},
            timeout=_OVERPASS_TIMEOUT + 10,
        )
        resp.raise_for_status()
    except Exception:
        logger.warning("overpass API request failed for %s", city, exc_info=True)
        return []

    data = resp.json()
    elements = data.get("elements", [])
    logger.info("overpass returned %d elements for %s", len(elements), city)

    lots = []
    for elem in elements:
        lot = _parse_osm_element(elem, city)
        if lot is not None:
            lots.append(lot)

    return lots
