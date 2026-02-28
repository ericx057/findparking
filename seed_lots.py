"""Seed parking lot data for all supported cities."""

from backend.database import get_connection, initialize_schema

LOTS = {
    "waterloo": [
        {
            "lot_id": "waterloo-town-square",
            "name": "Waterloo Town Square",
            "latitude": 43.4621,
            "longitude": -80.5241,
            "capacity": 400,
        },
        {
            "lot_id": "uw-lot-c",
            "name": "UW Lot C",
            "latitude": 43.4723,
            "longitude": -80.5449,
            "capacity": 600,
        },
        {
            "lot_id": "uw-lot-x",
            "name": "UW Lot X",
            "latitude": 43.4710,
            "longitude": -80.5382,
            "capacity": 350,
        },
        {
            "lot_id": "uptown-garage",
            "name": "Uptown Waterloo Garage",
            "latitude": 43.4648,
            "longitude": -80.5226,
            "capacity": 500,
        },
        {
            "lot_id": "conestoga-mall",
            "name": "Conestoga Mall",
            "latitude": 43.4979,
            "longitude": -80.5283,
            "capacity": 2000,
        },
    ],
    "toronto": [
        {
            "lot_id": "tor-union-station",
            "name": "Union Station Parking",
            "latitude": 43.6453,
            "longitude": -79.3806,
            "capacity": 800,
        },
        {
            "lot_id": "tor-eaton-centre",
            "name": "CF Toronto Eaton Centre",
            "latitude": 43.6544,
            "longitude": -79.3807,
            "capacity": 1200,
        },
        {
            "lot_id": "tor-nathan-phillips",
            "name": "Nathan Phillips Square Garage",
            "latitude": 43.6525,
            "longitude": -79.3834,
            "capacity": 600,
        },
        {
            "lot_id": "tor-yorkville",
            "name": "Yorkville Village Parking",
            "latitude": 43.6707,
            "longitude": -79.3930,
            "capacity": 500,
        },
        {
            "lot_id": "tor-kensington",
            "name": "Kensington Market Lot",
            "latitude": 43.6547,
            "longitude": -79.4006,
            "capacity": 150,
        },
    ],
    "vancouver": [
        {
            "lot_id": "van-pacific-centre",
            "name": "Pacific Centre Parkade",
            "latitude": 49.2838,
            "longitude": -123.1186,
            "capacity": 1000,
        },
        {
            "lot_id": "van-robson-square",
            "name": "Robson Square Parking",
            "latitude": 49.2827,
            "longitude": -123.1216,
            "capacity": 400,
        },
        {
            "lot_id": "van-gastown",
            "name": "Gastown Parkade",
            "latitude": 49.2843,
            "longitude": -123.1064,
            "capacity": 300,
        },
        {
            "lot_id": "van-granville-island",
            "name": "Granville Island Lot",
            "latitude": 49.2713,
            "longitude": -123.1340,
            "capacity": 500,
        },
        {
            "lot_id": "van-stanley-park",
            "name": "Stanley Park Lot",
            "latitude": 49.2986,
            "longitude": -123.1418,
            "capacity": 600,
        },
    ],
}


def seed(db_path: str = "findparking.db", city: str | None = None) -> None:
    conn = get_connection(db_path)
    initialize_schema(conn)

    cities_to_seed = [city] if city else list(LOTS.keys())
    total = 0

    for city_key in cities_to_seed:
        lots = LOTS.get(city_key, [])
        for lot in lots:
            conn.execute(
                "INSERT OR REPLACE INTO parking_lots "
                "(lot_id, name, latitude, longitude, capacity, current_occupancy, city) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (lot["lot_id"], lot["name"], lot["latitude"],
                 lot["longitude"], lot["capacity"], city_key),
            )
            total += 1

    conn.commit()
    print(f"Seeded {total} parking lots for {', '.join(cities_to_seed)}.")
    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed parking lot data")
    parser.add_argument(
        "--city",
        default=None,
        choices=list(LOTS.keys()),
        help="Seed lots for a specific city (default: all cities)",
    )
    parser.add_argument(
        "--db", default="findparking.db", help="Database file path",
    )
    args = parser.parse_args()
    seed(db_path=args.db, city=args.city)
