"""Tests for the Haversine distance utility."""

import math

import pytest

from backend.geo import haversine_km


def test_haversine_same_point_is_zero():
    assert haversine_km(43.65, -79.38, 43.65, -79.38) == 0.0


def test_haversine_known_distance():
    """Toronto to Vancouver is approximately 3357 km."""
    dist = haversine_km(43.6532, -79.3832, 49.2827, -123.1207)
    assert 3340 < dist < 3380


def test_haversine_short_distance():
    """Union Station to Eaton Centre is approximately 1.0-1.2 km."""
    dist = haversine_km(43.6453, -79.3806, 43.6544, -79.3807)
    assert 0.9 < dist < 1.3


def test_haversine_symmetry():
    d1 = haversine_km(43.65, -79.38, 49.28, -123.12)
    d2 = haversine_km(49.28, -123.12, 43.65, -79.38)
    assert d1 == pytest.approx(d2, abs=1e-6)
