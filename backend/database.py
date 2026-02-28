import sqlite3


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS parking_lots (
            lot_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            capacity INTEGER NOT NULL,
            current_occupancy INTEGER NOT NULL DEFAULT 0,
            last_updated TEXT NOT NULL DEFAULT (datetime('now')),
            camera_source_url TEXT,
            tripwire_config TEXT,
            city TEXT NOT NULL DEFAULT 'waterloo',
            fare_type TEXT NOT NULL DEFAULT 'paid',
            hourly_rate REAL,
            is_covered INTEGER NOT NULL DEFAULT 0,
            is_multi_level INTEGER NOT NULL DEFAULT 0,
            is_above_ground INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS vehicle_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id TEXT NOT NULL REFERENCES parking_lots(lot_id),
            direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            confidence REAL NOT NULL DEFAULT 1.0
        );

        CREATE TABLE IF NOT EXISTS occupancy_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id TEXT NOT NULL REFERENCES parking_lots(lot_id),
            occupancy INTEGER NOT NULL,
            vacancy_ratio REAL NOT NULL,
            probability_score REAL NOT NULL,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS time_of_day_weights (
            lot_id TEXT NOT NULL REFERENCES parking_lots(lot_id),
            hour INTEGER NOT NULL CHECK(hour >= 0 AND hour <= 23),
            day_of_week INTEGER NOT NULL CHECK(day_of_week >= 0 AND day_of_week <= 6),
            weight REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (lot_id, hour, day_of_week)
        );

        CREATE TABLE IF NOT EXISTS camera_assignments (
            lot_id TEXT NOT NULL REFERENCES parking_lots(lot_id),
            camera_id TEXT NOT NULL,
            distance_km REAL NOT NULL,
            image_url TEXT,
            source TEXT,
            assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (lot_id, camera_id)
        );

        CREATE TABLE IF NOT EXISTS cached_events (
            event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            venue_name TEXT NOT NULL,
            venue_lat REAL NOT NULL,
            venue_lon REAL NOT NULL,
            city TEXT NOT NULL,
            event_name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            expected_attendance INTEGER,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cached_weather (
            city TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            condition TEXT NOT NULL,
            temp_celsius REAL,
            wind_kph REAL,
            precipitation_mm REAL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (city, observed_at)
        );

        CREATE TABLE IF NOT EXISTS cached_road_disruptions (
            disruption_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            description TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            radius_km REAL NOT NULL DEFAULT 0.2,
            severity TEXT NOT NULL DEFAULT 'moderate',
            start_date TEXT,
            end_date TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cached_municipal_occupancy (
            lot_reference TEXT NOT NULL,
            city TEXT NOT NULL,
            mapped_lot_id TEXT,
            occupancy_pct REAL NOT NULL,
            observation_period TEXT NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (lot_reference, observation_period)
        );

        CREATE TABLE IF NOT EXISTS signal_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            signal_source TEXT NOT NULL,
            raw_value REAL NOT NULL,
            confidence REAL NOT NULL,
            weighted_contribution REAL NOT NULL,
            final_blended_score REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cached_events_city_time
            ON cached_events(city, start_time);
        CREATE INDEX IF NOT EXISTS idx_cached_weather_city_fetched
            ON cached_weather(city, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_cached_road_disruptions_city
            ON cached_road_disruptions(city);
        CREATE INDEX IF NOT EXISTS idx_signal_audit_lot_time
            ON signal_audit_log(lot_id, timestamp);
    """)
