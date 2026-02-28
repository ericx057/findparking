"""Tests for OSM parking data fetcher."""

import pytest
from unittest.mock import patch, MagicMock

from backend.osm_parking import (
    _parse_osm_element,
    _is_duplicate,
    fetch_osm_parking,
)


# --- _parse_osm_element ---

def test_parse_node_with_full_tags():
    element = {
        "type": "node",
        "id": 12345,
        "lat": 43.47,
        "lon": -80.52,
        "tags": {
            "amenity": "parking",
            "name": "Downtown Lot",
            "capacity": "200",
            "fee": "yes",
            "parking": "surface",
            "access": "public",
        },
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is not None
    assert result["lot_id"] == "osm-node-12345"
    assert result["name"] == "Downtown Lot"
    assert result["latitude"] == 43.47
    assert result["longitude"] == -80.52
    assert result["capacity"] == 200
    assert result["fare_type"] == "hourly"
    assert result["is_covered"] == 0
    assert result["is_multi_level"] == 0
    assert result["is_above_ground"] == 1
    assert result["city"] == "waterloo"


def test_parse_way_uses_center():
    element = {
        "type": "way",
        "id": 67890,
        "center": {"lat": 43.46, "lon": -80.53},
        "tags": {
            "amenity": "parking",
            "name": "Mall Parking",
            "capacity": "500",
            "fee": "no",
        },
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is not None
    assert result["lot_id"] == "osm-way-67890"
    assert result["latitude"] == 43.46
    assert result["longitude"] == -80.53
    assert result["fare_type"] == "free"
    assert result["capacity"] == 500


def test_parse_relation_uses_center():
    element = {
        "type": "relation",
        "id": 111,
        "center": {"lat": 49.28, "lon": -123.12},
        "tags": {
            "amenity": "parking",
            "parking": "multi-storey",
        },
    }
    result = _parse_osm_element(element, "vancouver")
    assert result is not None
    assert result["lot_id"] == "osm-relation-111"
    assert result["is_multi_level"] == 1
    assert result["is_covered"] == 1
    assert result["is_above_ground"] == 1


def test_parse_underground_parking():
    element = {
        "type": "node",
        "id": 222,
        "lat": 43.65,
        "lon": -79.38,
        "tags": {
            "amenity": "parking",
            "parking": "underground",
            "name": "Underground Garage",
        },
    }
    result = _parse_osm_element(element, "toronto")
    assert result is not None
    assert result["is_covered"] == 1
    assert result["is_multi_level"] == 1
    assert result["is_above_ground"] == 0


def test_parse_rooftop_parking():
    element = {
        "type": "node",
        "id": 333,
        "lat": 43.65,
        "lon": -79.38,
        "tags": {
            "amenity": "parking",
            "parking": "rooftop",
        },
    }
    result = _parse_osm_element(element, "toronto")
    assert result is not None
    assert result["is_covered"] == 0
    assert result["is_above_ground"] == 1


def test_parse_missing_name_generates_default():
    element = {
        "type": "node",
        "id": 444,
        "lat": 43.47,
        "lon": -80.52,
        "tags": {"amenity": "parking"},
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is not None
    assert result["name"] == "Parking Lot"


def test_parse_missing_capacity_uses_default():
    element = {
        "type": "node",
        "id": 555,
        "lat": 43.47,
        "lon": -80.52,
        "tags": {"amenity": "parking"},
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is not None
    assert result["capacity"] == 50


def test_parse_invalid_capacity_uses_default():
    element = {
        "type": "node",
        "id": 666,
        "lat": 43.47,
        "lon": -80.52,
        "tags": {"amenity": "parking", "capacity": "lots"},
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is not None
    assert result["capacity"] == 50


def test_parse_skips_private_access():
    element = {
        "type": "node",
        "id": 777,
        "lat": 43.47,
        "lon": -80.52,
        "tags": {"amenity": "parking", "access": "private"},
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is None


def test_parse_skips_no_access():
    element = {
        "type": "node",
        "id": 888,
        "lat": 43.47,
        "lon": -80.52,
        "tags": {"amenity": "parking", "access": "no"},
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is None


def test_parse_way_without_center_skipped():
    element = {
        "type": "way",
        "id": 999,
        "tags": {"amenity": "parking"},
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is None


def test_parse_no_tags_still_works():
    element = {
        "type": "node",
        "id": 1010,
        "lat": 43.47,
        "lon": -80.52,
    }
    result = _parse_osm_element(element, "waterloo")
    assert result is not None
    assert result["name"] == "Parking Lot"


# --- _is_duplicate ---

def test_is_duplicate_within_threshold():
    existing = [{"latitude": 43.4621, "longitude": -80.5241}]
    assert _is_duplicate(43.4622, -80.5240, existing, threshold_km=0.1) is True


def test_is_not_duplicate_beyond_threshold():
    existing = [{"latitude": 43.4621, "longitude": -80.5241}]
    assert _is_duplicate(43.47, -80.53, existing, threshold_km=0.1) is False


def test_is_not_duplicate_empty_list():
    assert _is_duplicate(43.47, -80.52, [], threshold_km=0.1) is False


# --- fetch_osm_parking (mocked HTTP) ---

def test_fetch_returns_parsed_lots():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 43.47,
                "lon": -80.52,
                "tags": {"amenity": "parking", "name": "Lot A", "capacity": "100"},
            },
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 43.48, "lon": -80.53},
                "tags": {"amenity": "parking", "name": "Lot B"},
            },
        ],
    }

    bounds = {"lat_min": 43.40, "lat_max": 43.55, "lon_min": -80.65, "lon_max": -80.40}

    with patch("backend.osm_parking.httpx.post", return_value=mock_response):
        lots = fetch_osm_parking(bounds, "waterloo")

    assert len(lots) == 2
    assert lots[0]["lot_id"] == "osm-node-1"
    assert lots[1]["lot_id"] == "osm-way-2"


def test_fetch_skips_private_lots():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 43.47,
                "lon": -80.52,
                "tags": {"amenity": "parking", "access": "private"},
            },
            {
                "type": "node",
                "id": 2,
                "lat": 43.48,
                "lon": -80.53,
                "tags": {"amenity": "parking", "name": "Public Lot"},
            },
        ],
    }

    bounds = {"lat_min": 43.40, "lat_max": 43.55, "lon_min": -80.65, "lon_max": -80.40}

    with patch("backend.osm_parking.httpx.post", return_value=mock_response):
        lots = fetch_osm_parking(bounds, "waterloo")

    assert len(lots) == 1
    assert lots[0]["name"] == "Public Lot"


def test_fetch_returns_empty_on_api_error():
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = Exception("Server error")

    bounds = {"lat_min": 43.40, "lat_max": 43.55, "lon_min": -80.65, "lon_max": -80.40}

    with patch("backend.osm_parking.httpx.post", return_value=mock_response):
        lots = fetch_osm_parking(bounds, "waterloo")

    assert lots == []


def test_fetch_returns_empty_on_timeout():
    bounds = {"lat_min": 43.40, "lat_max": 43.55, "lon_min": -80.65, "lon_max": -80.40}

    with patch("backend.osm_parking.httpx.post", side_effect=Exception("Timeout")):
        lots = fetch_osm_parking(bounds, "waterloo")

    assert lots == []
