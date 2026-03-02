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
        CREATE TABLE IF NOT EXISTS cached_demand_nodes (
            node_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            source TEXT NOT NULL,
            category TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            amplitude REAL NOT NULL DEFAULT 1.0,
            sigma_km REAL NOT NULL DEFAULT 0.4,
            name TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_signal_audit_lot_time
            ON signal_audit_log(lot_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_demand_nodes_city
            ON cached_demand_nodes(city);

        CREATE TABLE IF NOT EXISTS cached_bikeshare_stations (
            station_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            name TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            capacity INTEGER NOT NULL,
            num_bikes_available INTEGER NOT NULL,
            num_docks_available INTEGER NOT NULL,
            last_reported INTEGER NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_bikeshare_city
            ON cached_bikeshare_stations(city);

        CREATE TABLE IF NOT EXISTS cached_transit_alerts (
            alert_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            agency TEXT NOT NULL,
            route_id TEXT,
            description TEXT,
            severity TEXT NOT NULL DEFAULT 'moderate',
            lat REAL,
            lon REAL,
            start_time TEXT,
            end_time TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_transit_alerts_city
            ON cached_transit_alerts(city);

        CREATE TABLE IF NOT EXISTS cached_sun_times (
            city TEXT NOT NULL,
            date TEXT NOT NULL,
            sunrise TEXT NOT NULL,
            sunset TEXT NOT NULL,
            civil_twilight_begin TEXT,
            civil_twilight_end TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (city, date)
        );

        CREATE TABLE IF NOT EXISTS cached_festival_events (
            event_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            event_name TEXT NOT NULL,
            category TEXT,
            lat REAL,
            lon REAL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            location_name TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_festival_events_city_date
            ON cached_festival_events(city, start_date);

        CREATE TABLE IF NOT EXISTS cached_team_streaks (
            team_abbrev TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            streak_code TEXT NOT NULL,
            streak_count INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS signal_params (
            signal_name TEXT NOT NULL,
            param_key TEXT NOT NULL,
            param_value REAL NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (signal_name, param_key)
        );

        CREATE TABLE IF NOT EXISTS cached_air_quality (
            city TEXT PRIMARY KEY,
            us_aqi INTEGER,
            pm2_5 REAL,
            pm10 REAL,
            observed_at TEXT NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cached_pressure_history (
            city TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            pressure_hpa REAL NOT NULL,
            PRIMARY KEY (city, observed_at)
        );

        CREATE TABLE IF NOT EXISTS cached_economic_indicators (
            indicator TEXT PRIMARY KEY,
            value REAL NOT NULL,
            period TEXT NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cached_holidays (
            date TEXT NOT NULL,
            country_code TEXT NOT NULL DEFAULT 'CA',
            name TEXT NOT NULL,
            is_global INTEGER NOT NULL DEFAULT 0,
            provinces TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (date, name)
        );

        CREATE TABLE IF NOT EXISTS cached_construction (
            project_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            description TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            status TEXT,
            start_year INTEGER,
            geometry_type TEXT,
            geometry_json TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_construction_city
            ON cached_construction(city);

        CREATE TABLE IF NOT EXISTS cached_geomagnetic (
            observed_at TEXT PRIMARY KEY,
            kp_index REAL NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Add weather micro-effect columns (idempotent via try/except)
    for col_stmt in [
        "ALTER TABLE cached_weather ADD COLUMN apparent_temp_celsius REAL",
        "ALTER TABLE cached_weather ADD COLUMN uv_index REAL",
        "ALTER TABLE cached_weather ADD COLUMN precip_probability_pct REAL",
        "ALTER TABLE cached_weather ADD COLUMN weather_code INTEGER",
        "ALTER TABLE cached_weather ADD COLUMN surface_pressure_hpa REAL",
        "ALTER TABLE cached_weather ADD COLUMN wind_gusts_kph REAL",
    ]:
        try:
            conn.execute(col_stmt)
        except sqlite3.OperationalError:
            pass  # Column already exists
