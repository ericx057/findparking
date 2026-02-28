"""Multi-city camera discovery.

Supports four camera feed providers:
  - ontario_511:           Ontario 511 traffic cameras (Waterloo, Toronto, all Ontario)
  - toronto_opendata:      City of Toronto RESCU cameras via Open Data portal
  - drivebc:               BC Ministry of Transportation cameras (Vancouver, all BC)
  - vancouver_trafficcams: City of Vancouver intersection cameras (scraped from HTML index)

Usage:
    python -m cv_pipeline.camera_discovery --city toronto
    python -m cv_pipeline.camera_discovery --city vancouver
"""

import json
import logging
import re
import time

import httpx

from cv_pipeline.city_config import CITIES, get_city_config

logger = logging.getLogger("findparking.camera_discovery")

# Ontario 511 API (rate limit: 10 calls per 60 seconds)
_ONTARIO_511_API = "https://511on.ca/api/v2/get/cameras"

# Toronto Open Data -- GeoJSON with all 336 RESCU cameras
_TORONTO_GEOJSON_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "a3309088-5fd4-4d34-8297-77c8301840ac/resource/"
    "4a568300-c7f8-496d-b150-dff6f5dc6d4f/download/"
    "Traffic%20Cameras%20Data%20-%204326.geojson"
)
_TORONTO_IMAGE_BASE = (
    "https://opendata.toronto.ca/transportation/tmc/"
    "rescucameraimages/CameraImages/loc{rec_id}.jpg"
)

# DriveBC REST API
_DRIVEBC_API = "https://images.drivebc.ca/webcam/api/v1/webcams"
_DRIVEBC_IMAGE_BASE = "https://images.drivebc.ca/bchighwaycam/pub/cameras/{cam_id}.jpg"

# Vancouver traffic cams (no API, scrape HTML index)
_VANCOUVER_INDEX_URL = "https://trafficcams.vancouver.ca/"
_VANCOUVER_IMAGE_BASE = "https://trafficcams.vancouver.ca/cameraimages/{filename}"


def _in_bounds(lat: float, lon: float, bounds: dict) -> bool:
    return (
        bounds["lat_min"] <= lat <= bounds["lat_max"]
        and bounds["lon_min"] <= lon <= bounds["lon_max"]
    )


# ---------------------------------------------------------------------------
# Provider: Ontario 511
# ---------------------------------------------------------------------------

def _discover_ontario_511(bounds: dict) -> list[dict]:
    """Fetch cameras from the Ontario 511 API and filter by bounding box."""
    try:
        response = httpx.get(_ONTARIO_511_API, params={"format": "json"}, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Ontario 511 API fetch failed: %s", exc)
        return []

    all_cameras = response.json()
    logger.info("Ontario 511: fetched %d cameras total", len(all_cameras))

    results = []
    for cam in all_cameras:
        lat = cam.get("Latitude")
        lon = cam.get("Longitude")
        if lat is None or lon is None:
            continue
        if not _in_bounds(lat, lon, bounds):
            continue

        views = cam.get("Views", [])
        if views:
            view_url = views[0].get("Url") or f"https://511on.ca/map/Cctv/{views[0].get('Id')}"
        else:
            view_url = f"https://511on.ca/map/Cctv/{cam.get('Id')}"

        results.append({
            "camera_id": f"on511-{cam.get('Id')}",
            "name": cam.get("Location") or cam.get("Description", "Unknown"),
            "latitude": lat,
            "longitude": lon,
            "image_url": view_url,
            "source": "ontario_511",
        })

    logger.info("Ontario 511: %d cameras within bounds", len(results))
    return results


# ---------------------------------------------------------------------------
# Provider: Toronto Open Data (RESCU cameras)
# ---------------------------------------------------------------------------

def _discover_toronto_opendata(bounds: dict) -> list[dict]:
    """Fetch the City of Toronto RESCU camera GeoJSON and extract image URLs."""
    try:
        response = httpx.get(_TORONTO_GEOJSON_URL, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Toronto Open Data fetch failed: %s", exc)
        return []

    geojson = response.json()
    features = geojson.get("features", [])
    logger.info("Toronto Open Data: fetched %d camera features", len(features))

    results = []
    for feature in features:
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])

        if not coords or not coords[0]:
            continue

        # GeoJSON MultiPoint: coordinates is [[lon, lat]]
        if geom.get("type") == "MultiPoint":
            lon, lat = coords[0][0], coords[0][1]
        else:
            lon, lat = coords[0], coords[1]

        if not _in_bounds(lat, lon, bounds):
            continue

        rec_id = props.get("REC_ID")
        if rec_id is None:
            continue

        main_road = props.get("MAINROAD", "")
        cross_road = props.get("CROSSROAD", "")
        name = f"{main_road} / {cross_road}".strip(" /")

        results.append({
            "camera_id": f"tor-{rec_id}",
            "name": name or f"Camera {rec_id}",
            "latitude": lat,
            "longitude": lon,
            "image_url": _TORONTO_IMAGE_BASE.format(rec_id=rec_id),
            "source": "toronto_opendata",
        })

    logger.info("Toronto Open Data: %d cameras within bounds", len(results))
    return results


# ---------------------------------------------------------------------------
# Provider: DriveBC
# ---------------------------------------------------------------------------

def _discover_drivebc(bounds: dict) -> list[dict]:
    """Fetch cameras from the DriveBC REST API and filter by bounding box."""
    try:
        response = httpx.get(_DRIVEBC_API, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("DriveBC API fetch failed: %s", exc)
        return []

    data = response.json()
    # API returns {"webcams": [...], "links": {...}}
    all_cameras = data.get("webcams", []) if isinstance(data, dict) else data
    logger.info("DriveBC: fetched %d cameras total", len(all_cameras))

    results = []
    for cam in all_cameras:
        location = cam.get("location", {})
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is None or lon is None:
            continue
        if not _in_bounds(lat, lon, bounds):
            continue

        cam_id = cam.get("id")
        is_on = cam.get("isOn", False)
        if not is_on:
            continue

        # Prefer image URL from API links, fall back to template
        links = cam.get("links", {})
        image_url = links.get("imageDisplay") or _DRIVEBC_IMAGE_BASE.format(cam_id=cam_id)

        results.append({
            "camera_id": f"drivebc-{cam_id}",
            "name": cam.get("camName") or cam.get("caption", f"Camera {cam_id}"),
            "latitude": lat,
            "longitude": lon,
            "image_url": image_url,
            "source": "drivebc",
        })

    logger.info("DriveBC: %d cameras within bounds", len(results))
    return results


# ---------------------------------------------------------------------------
# Provider: Vancouver Traffic Cams (HTML scrape)
# ---------------------------------------------------------------------------

def _discover_vancouver_trafficcams(bounds: dict) -> list[dict]:
    """Scrape the City of Vancouver traffic camera index for image filenames.

    These cameras do NOT include GPS coordinates in the source data.
    latitude/longitude will be None -- must be geocoded separately.
    """
    try:
        response = httpx.get(_VANCOUVER_INDEX_URL, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Vancouver traffic cams index fetch failed: %s", exc)
        return []

    html = response.text
    htm_links = re.findall(r'href="([^"]+\.htm)"', html, re.IGNORECASE)
    logger.info("Vancouver traffic cams: found %d intersection pages", len(htm_links))

    results = []
    for i, htm_link in enumerate(htm_links):
        if i > 0 and i % 20 == 0:
            time.sleep(1.0)

        page_url = _VANCOUVER_INDEX_URL + htm_link
        try:
            page_resp = httpx.get(page_url, timeout=15)
            page_resp.raise_for_status()
        except httpx.HTTPError:
            continue

        images = re.findall(r'src="cameraimages/([^"]+\.jpg)"', page_resp.text, re.IGNORECASE)
        if not images:
            continue

        intersection_name = htm_link.replace(".htm", "").replace("_", " & ").title()

        for img_filename in images:
            camera_id = f"van-{img_filename.split('.')[0]}"
            results.append({
                "camera_id": camera_id,
                "name": intersection_name,
                "latitude": None,
                "longitude": None,
                "image_url": _VANCOUVER_IMAGE_BASE.format(filename=img_filename),
                "source": "vancouver_trafficcams",
            })

    logger.info("Vancouver traffic cams: scraped %d camera images", len(results))
    return results


# ---------------------------------------------------------------------------
# Unified discovery
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "ontario_511": _discover_ontario_511,
    "toronto_opendata": _discover_toronto_opendata,
    "drivebc": _discover_drivebc,
    "vancouver_trafficcams": _discover_vancouver_trafficcams,
}


def discover_cameras(city: str) -> list[dict]:
    """Discover all cameras for a city by querying its configured providers sequentially.

    Returns a list of camera dicts with keys:
        camera_id, name, latitude, longitude, image_url, source
    """
    config = get_city_config(city)
    bounds = config["bounds"]
    providers = config["providers"]

    all_cameras = []
    for provider_name in providers:
        provider_fn = _PROVIDERS.get(provider_name)
        if provider_fn is None:
            logger.warning("Unknown camera provider: %s", provider_name)
            continue

        logger.info("Querying provider '%s' for city '%s'...", provider_name, city)
        cameras = provider_fn(bounds)
        all_cameras.extend(cameras)

    logger.info(
        "Discovery complete for '%s': %d cameras from %d providers",
        city, len(all_cameras), len(providers),
    )
    return all_cameras


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Discover traffic cameras for a city")
    parser.add_argument(
        "--city",
        default="waterloo",
        choices=list(CITIES.keys()),
        help="City to discover cameras for",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (prints to stdout if omitted)",
    )
    parser.add_argument(
        "--assign",
        action="store_true",
        help="Assign nearest camera to each lot and write cameras.json",
    )
    parser.add_argument(
        "--db",
        default="findparking.db",
        help="Database path (default: findparking.db)",
    )
    args = parser.parse_args()

    cameras = discover_cameras(args.city)

    if args.assign:
        from backend.database import get_connection, initialize_schema
        from cv_pipeline.camera_assignment import assign_cameras_to_lots, generate_cameras_config

        conn = get_connection(args.db)
        initialize_schema(conn)

        count = assign_cameras_to_lots(conn, args.city, cameras)
        logger.info("Assigned %d cameras to lots for %s", count, args.city)

        config = generate_cameras_config(conn, args.city)
        output_path = args.output or "cameras.json"
        with open(output_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Assigned {count} cameras. Wrote config to {output_path}")
        conn.close()
    else:
        output = json.dumps(cameras, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Wrote {len(cameras)} cameras to {args.output}")
        else:
            print(output)

    if not cameras:
        print(f"No cameras found for {args.city}.")


if __name__ == "__main__":
    main()
