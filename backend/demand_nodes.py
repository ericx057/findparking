"""Demand node definitions and time-varying intensity constants.

Each demand node represents a geographic point that generates parking pressure.
Nodes are categorised by type (transit, commercial, retail, entertainment)
and have time profiles that describe how their intensity varies over a 24-hour
cycle and across days of the week.
"""

from zoneinfo import ZoneInfo

# --- City timezone mapping (local time drives the intensity profiles) ---

CITY_TIMEZONES = {
    "toronto": ZoneInfo("America/Toronto"),
    "waterloo": ZoneInfo("America/Toronto"),
    "vancouver": ZoneInfo("America/Vancouver"),
}

DEFAULT_TZ = ZoneInfo("America/Toronto")


# --- Thermodynamic constants ---

# At full intensity, sigma grows by this fraction (demand diffuses outward).
PEAK_EXPANSION = 0.5

# Michaelis-Menten half-saturation parameter.
# Raw demand temperature at which occupancy fraction equals 50%.
DEMAND_SCALE = 0.8


# --- Hour-of-day intensity profiles (0-23, local time) ---
# Values represent relative demand pressure from this category at each hour.

TIME_PROFILES = {
    "transit": [
        #  0     1     2     3     4     5     6     7     8     9
        0.02, 0.02, 0.02, 0.02, 0.03, 0.10, 0.40, 0.80, 1.00, 0.85,
        # 10    11    12    13    14    15    16    17    18    19
        0.60, 0.50, 0.55, 0.50, 0.55, 0.65, 0.85, 1.00, 0.80, 0.45,
        # 20    21    22    23
        0.20, 0.10, 0.05, 0.03,
    ],
    "commercial": [
        0.02, 0.02, 0.02, 0.02, 0.03, 0.05, 0.15, 0.45, 0.80, 0.92,
        0.95, 0.90, 0.78, 0.85, 0.92, 0.90, 0.82, 0.50, 0.20, 0.08,
        0.04, 0.03, 0.02, 0.02,
    ],
    "retail": [
        0.02, 0.02, 0.02, 0.02, 0.02, 0.03, 0.05, 0.08, 0.18, 0.35,
        0.55, 0.70, 0.80, 0.82, 0.85, 0.85, 0.82, 0.78, 0.65, 0.45,
        0.25, 0.12, 0.05, 0.03,
    ],
    "entertainment": [
        0.02, 0.02, 0.03, 0.02, 0.02, 0.02, 0.03, 0.05, 0.08, 0.10,
        0.15, 0.25, 0.45, 0.42, 0.35, 0.30, 0.35, 0.50, 0.70, 0.85,
        0.92, 0.80, 0.50, 0.15,
    ],
}


# --- Day-of-week multipliers (Mon=0 through Sun=6) ---

DAY_SCALES = {
    "transit":       [1.00, 1.00, 1.00, 1.00, 0.95, 0.35, 0.30],
    "commercial":    [1.00, 1.00, 1.00, 1.00, 0.95, 0.35, 0.30],
    "retail":        [0.75, 0.75, 0.75, 0.78, 0.85, 1.10, 1.05],
    "entertainment": [0.60, 0.65, 0.70, 0.75, 0.90, 1.10, 1.00],
}


# --- Hardcoded demand nodes per city ---

DEMAND_NODES = {
    "toronto": [
        {
            "node_id": "tor-union-stn",
            "name": "Union Station",
            "category": "transit",
            "lat": 43.6453, "lon": -79.3806,
            "amplitude": 1.0, "sigma_km": 0.5,
        },
        {
            "node_id": "tor-financial",
            "name": "Financial District",
            "category": "commercial",
            "lat": 43.6488, "lon": -79.3817,
            "amplitude": 0.9, "sigma_km": 0.4,
        },
        {
            "node_id": "tor-eaton",
            "name": "Eaton Centre",
            "category": "retail",
            "lat": 43.6544, "lon": -79.3807,
            "amplitude": 0.85, "sigma_km": 0.35,
        },
        {
            "node_id": "tor-dundas-sq",
            "name": "Yonge-Dundas Square",
            "category": "entertainment",
            "lat": 43.6561, "lon": -79.3802,
            "amplitude": 0.7, "sigma_km": 0.3,
        },
        {
            "node_id": "tor-bloor-yonge",
            "name": "Bloor-Yonge Station",
            "category": "transit",
            "lat": 43.6709, "lon": -79.3857,
            "amplitude": 0.8, "sigma_km": 0.45,
        },
        {
            "node_id": "tor-king-west",
            "name": "King Street West",
            "category": "entertainment",
            "lat": 43.6441, "lon": -79.3947,
            "amplitude": 0.65, "sigma_km": 0.3,
        },
        {
            "node_id": "tor-st-lawrence",
            "name": "St. Lawrence Market",
            "category": "retail",
            "lat": 43.6487, "lon": -79.3716,
            "amplitude": 0.6, "sigma_km": 0.25,
        },
        {
            "node_id": "tor-yorkville",
            "name": "Yorkville",
            "category": "retail",
            "lat": 43.6707, "lon": -79.3930,
            "amplitude": 0.7, "sigma_km": 0.3,
        },
        {
            "node_id": "tor-kensington",
            "name": "Kensington Market",
            "category": "entertainment",
            "lat": 43.6547, "lon": -79.4006,
            "amplitude": 0.55, "sigma_km": 0.25,
        },
    ],
    "waterloo": [
        {
            "node_id": "wat-uptown",
            "name": "Uptown Waterloo",
            "category": "retail",
            "lat": 43.4648, "lon": -80.5226,
            "amplitude": 0.8, "sigma_km": 0.35,
        },
        {
            "node_id": "wat-uw-campus",
            "name": "UW Campus",
            "category": "commercial",
            "lat": 43.4723, "lon": -80.5449,
            "amplitude": 0.9, "sigma_km": 0.5,
        },
        {
            "node_id": "wat-conestoga",
            "name": "Conestoga Mall",
            "category": "retail",
            "lat": 43.4979, "lon": -80.5283,
            "amplitude": 0.75, "sigma_km": 0.4,
        },
        {
            "node_id": "wat-town-square",
            "name": "Waterloo Town Square",
            "category": "retail",
            "lat": 43.4621, "lon": -80.5241,
            "amplitude": 0.65, "sigma_km": 0.3,
        },
        {
            "node_id": "wat-ion-square",
            "name": "ION LRT Public Square",
            "category": "transit",
            "lat": 43.4625, "lon": -80.5220,
            "amplitude": 0.7, "sigma_km": 0.4,
        },
        {
            "node_id": "wat-laurier",
            "name": "Wilfrid Laurier University",
            "category": "commercial",
            "lat": 43.4730, "lon": -80.5280,
            "amplitude": 0.7, "sigma_km": 0.4,
        },
    ],
    "vancouver": [
        {
            "node_id": "van-waterfront",
            "name": "Waterfront Station",
            "category": "transit",
            "lat": 49.2856, "lon": -123.1115,
            "amplitude": 1.0, "sigma_km": 0.5,
        },
        {
            "node_id": "van-pacific",
            "name": "Pacific Centre",
            "category": "retail",
            "lat": 49.2838, "lon": -123.1186,
            "amplitude": 0.85, "sigma_km": 0.35,
        },
        {
            "node_id": "van-robson",
            "name": "Robson Street",
            "category": "retail",
            "lat": 49.2827, "lon": -123.1216,
            "amplitude": 0.75, "sigma_km": 0.3,
        },
        {
            "node_id": "van-gastown",
            "name": "Gastown",
            "category": "entertainment",
            "lat": 49.2843, "lon": -123.1064,
            "amplitude": 0.7, "sigma_km": 0.3,
        },
        {
            "node_id": "van-granville",
            "name": "Granville Island",
            "category": "entertainment",
            "lat": 49.2713, "lon": -123.1340,
            "amplitude": 0.65, "sigma_km": 0.35,
        },
        {
            "node_id": "van-commercial",
            "name": "Commercial-Broadway Station",
            "category": "transit",
            "lat": 49.2625, "lon": -123.0691,
            "amplitude": 0.8, "sigma_km": 0.45,
        },
        {
            "node_id": "van-metrotown",
            "name": "Metrotown",
            "category": "retail",
            "lat": 49.2269, "lon": -123.0029,
            "amplitude": 0.8, "sigma_km": 0.4,
        },
        {
            "node_id": "van-stanley",
            "name": "Stanley Park Entrance",
            "category": "entertainment",
            "lat": 49.2986, "lon": -123.1418,
            "amplitude": 0.5, "sigma_km": 0.35,
        },
    ],
}
