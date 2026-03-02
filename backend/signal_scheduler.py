"""Background scheduler for signal data refresh jobs."""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import httpx

from backend.signals.events_sports import VENUES
from backend.signals.weather import classify_wmo_code
from backend.estimation import compute_blended_score
from backend.probability_engine import compute_vacancy_ratio

logger = logging.getLogger("findparking.signal_scheduler")


# --- City coordinates for Open-Meteo ---
_CITY_COORDS = {
    "toronto": (43.6532, -79.3832, "America/Toronto"),
    "waterloo": (43.4643, -80.5204, "America/Toronto"),
    "vancouver": (49.2827, -123.1207, "America/Vancouver"),
}


def refresh_weather(conn: sqlite3.Connection) -> None:
    """Fetch current conditions from Open-Meteo for all configured cities."""
    for city, (lat, lon, tz) in _CITY_COORDS.items():
        try:
            _fetch_open_meteo_weather(conn, city, lat, lon, tz)
            logger.info("weather_refresh city=%s status=ok source=open-meteo", city)
        except Exception:
            logger.exception("weather_refresh city=%s status=error", city)


def _fetch_open_meteo_weather(
    conn: sqlite3.Connection, city: str, lat: float, lon: float, tz: str,
) -> None:
    """Fetch current weather from Open-Meteo and upsert into cached_weather."""
    resp = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,precipitation,weathercode,windspeed_10m,uv_index,surface_pressure,windgusts_10m",
            "hourly": "precipitation_probability",
            "timezone": tz,
            "forecast_days": 1,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()

    current = data.get("current", {})
    if not current:
        logger.warning("weather_refresh city=%s no current data", city)
        return

    weather_code = current.get("weathercode")
    condition = classify_wmo_code(weather_code) if weather_code is not None else "clear"
    temp_celsius = current.get("temperature_2m")
    apparent_temp = current.get("apparent_temperature")
    wind_kph = current.get("windspeed_10m")
    uv_index = current.get("uv_index")
    precipitation_mm = current.get("precipitation")
    surface_pressure = current.get("surface_pressure")
    wind_gusts = current.get("windgusts_10m")

    # Get current hour's precipitation probability from hourly data
    precip_prob = None
    hourly = data.get("hourly", {})
    hourly_times = hourly.get("time", [])
    hourly_precip_probs = hourly.get("precipitation_probability", [])
    current_time = current.get("time", "")
    # Match current hour in hourly array
    current_hour_prefix = current_time[:13] if current_time else ""
    for i, t in enumerate(hourly_times):
        if t.startswith(current_hour_prefix) and i < len(hourly_precip_probs):
            precip_prob = hourly_precip_probs[i]
            break

    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT OR REPLACE INTO cached_weather "
        "(city, observed_at, condition, temp_celsius, wind_kph, precipitation_mm, "
        "apparent_temp_celsius, uv_index, precip_probability_pct, weather_code, "
        "surface_pressure_hpa, wind_gusts_kph, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (city, observed_at, condition, temp_celsius, wind_kph, precipitation_mm,
         apparent_temp, uv_index, precip_prob, weather_code,
         surface_pressure, wind_gusts),
    )

    # Store pressure reading for trend analysis
    if surface_pressure is not None:
        conn.execute(
            "INSERT OR REPLACE INTO cached_pressure_history "
            "(city, observed_at, pressure_hpa) VALUES (?, ?, ?)",
            (city, observed_at, surface_pressure),
        )

    conn.commit()


def refresh_lot_probabilities(conn: sqlite3.Connection) -> None:
    """Recompute blended probability scores for all lots and store snapshots.

    Runs every 10 minutes to keep probability data, trends, and time-weight
    inputs constantly fresh --- even when no vehicle events are arriving.

    For lots without recent camera events, also updates last_updated so they
    are not incorrectly marked as stale.  Lots with recent camera events keep
    their camera-driven last_updated (preserving accurate camera confidence).
    """
    lots = conn.execute(
        "SELECT lot_id, latitude, longitude, city, capacity, current_occupancy "
        "FROM parking_lots",
    ).fetchall()

    if not lots:
        return

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    snapshot_count = 0

    for lot in lots:
        lot_id = lot["lot_id"]
        capacity = lot["capacity"]
        occupancy = lot["current_occupancy"]

        if capacity <= 0:
            continue

        try:
            estimate = compute_blended_score(
                conn, lot_id, lot["latitude"], lot["longitude"],
                lot["city"], capacity, occupancy,
            )
        except Exception:
            logger.debug("probability_refresh lot=%s skipped (error)", lot_id)
            continue

        vacancy = compute_vacancy_ratio(capacity, occupancy)

        conn.execute(
            "INSERT INTO occupancy_snapshots "
            "(lot_id, occupancy, vacancy_ratio, probability_score) "
            "VALUES (?, ?, ?, ?)",
            (lot_id, occupancy, round(vacancy, 4), round(estimate.score, 4)),
        )
        snapshot_count += 1

        # Only touch last_updated for lots without recent camera events.
        # This avoids inflating camera-signal confidence for stale feeds.
        recent_events = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events "
            "WHERE lot_id = ? AND timestamp > ?",
            (lot_id, one_hour_ago),
        ).fetchone()[0]

        if recent_events == 0:
            conn.execute(
                "UPDATE parking_lots SET last_updated = ? WHERE lot_id = ?",
                (now_str, lot_id),
            )

    conn.commit()
    logger.info("probability_refresh snapshots=%d lots=%d", snapshot_count, len(lots))


def register_signal_jobs(scheduler, conn: sqlite3.Connection, ticketmaster_api_key: str = "") -> None:
    """Register all signal refresh jobs with the APScheduler instance."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    # Weather: every 15 minutes
    scheduler.add_job(
        refresh_weather,
        trigger=IntervalTrigger(minutes=15),
        args=[conn],
        id="refresh_weather",
        replace_existing=True,
    )

    # Sports events: every 6 hours
    scheduler.add_job(
        refresh_sports_events,
        trigger=IntervalTrigger(hours=6),
        args=[conn],
        id="refresh_sports_events",
        replace_existing=True,
    )

    # Road disruptions: every 2 hours
    scheduler.add_job(
        refresh_road_disruptions,
        trigger=IntervalTrigger(hours=2),
        args=[conn],
        id="refresh_road_disruptions",
        replace_existing=True,
    )

    # Time weights recalculation: daily at 04:00 UTC
    scheduler.add_job(
        recalculate_time_weights,
        trigger=CronTrigger(hour=4),
        args=[conn],
        id="recalculate_time_weights",
        replace_existing=True,
    )

    # Ticketmaster: every 4 hours (only if API key configured)
    if ticketmaster_api_key:
        from backend.signals.events_ticketmaster import refresh_ticketmaster_events
        scheduler.add_job(
            refresh_ticketmaster_events,
            trigger=IntervalTrigger(hours=4),
            args=[conn, ticketmaster_api_key],
            id="refresh_ticketmaster_events",
            replace_existing=True,
        )
        logger.info("ticketmaster signal enabled")

    # Demand heatmap OSM POI nodes: weekly refresh (POIs don't change frequently)
    from backend.signals.demand_heatmap import refresh_osm_demand_nodes
    scheduler.add_job(
        refresh_osm_demand_nodes,
        trigger=IntervalTrigger(days=7),
        args=[conn],
        id="refresh_demand_nodes",
        replace_existing=True,
    )

    # Bikeshare: every 5 minutes
    from backend.signals.bikeshare import refresh_bikeshare
    scheduler.add_job(
        refresh_bikeshare,
        trigger=IntervalTrigger(minutes=5),
        args=[conn],
        id="refresh_bikeshare",
        replace_existing=True,
    )

    # Transit disruptions: every 10 minutes
    from backend.signals.transit_disruptions import refresh_transit_alerts
    scheduler.add_job(
        refresh_transit_alerts,
        trigger=IntervalTrigger(minutes=10),
        args=[conn],
        id="refresh_transit_alerts",
        replace_existing=True,
    )

    # Festival events: every 12 hours
    from backend.signals.festival_events import refresh_festival_events
    scheduler.add_job(
        refresh_festival_events,
        trigger=IntervalTrigger(hours=12),
        args=[conn],
        id="refresh_festival_events",
        replace_existing=True,
    )

    # Team streaks: every 6 hours
    scheduler.add_job(
        refresh_team_streaks,
        trigger=IntervalTrigger(hours=6),
        args=[conn],
        id="refresh_team_streaks",
        replace_existing=True,
    )

    # Probability refresh: every 10 minutes
    # Recomputes blended scores for all lots and stores snapshots,
    # keeping trends, time-weights, and freshness constantly up to date.
    scheduler.add_job(
        refresh_lot_probabilities,
        trigger=IntervalTrigger(minutes=10),
        args=[conn],
        id="refresh_lot_probabilities",
        replace_existing=True,
    )

    # Air quality: every 30 minutes
    scheduler.add_job(
        refresh_air_quality,
        trigger=IntervalTrigger(minutes=30),
        args=[conn],
        id="refresh_air_quality",
        replace_existing=True,
    )

    # Construction: daily at 05:00 UTC
    scheduler.add_job(
        refresh_construction,
        trigger=CronTrigger(hour=5),
        args=[conn],
        id="refresh_construction",
        replace_existing=True,
    )

    # Holidays: weekly (Sunday 00:30 UTC)
    scheduler.add_job(
        refresh_holidays,
        trigger=CronTrigger(day_of_week=0, hour=0, minute=30),
        args=[conn],
        id="refresh_holidays",
        replace_existing=True,
    )

    # Economic indicators: weekly (Tuesday 01:00 UTC)
    scheduler.add_job(
        refresh_economic_indicators,
        trigger=CronTrigger(day_of_week=1, hour=1),
        args=[conn],
        id="refresh_economic_indicators",
        replace_existing=True,
    )

    # Adaptive weight calibration: daily at 04:30 UTC (after time weights @ 04:00)
    from backend.calibration import calibrate_weights
    scheduler.add_job(
        calibrate_weights,
        trigger=CronTrigger(hour=4, minute=30),
        args=[conn],
        id="calibrate_weights",
        replace_existing=True,
    )

    logger.info("signal_scheduler registered jobs")


# --- Air quality fetcher ---

def refresh_air_quality(conn: sqlite3.Connection) -> None:
    """Fetch current air quality from Open-Meteo for all configured cities."""
    for city, (lat, lon, _tz) in _CITY_COORDS.items():
        try:
            resp = httpx.get(
                "https://air-quality.open-meteo.com/v1/air-quality",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "us_aqi,pm2_5,pm10",
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

            current = data.get("current", {})
            if not current:
                continue

            observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT OR REPLACE INTO cached_air_quality "
                "(city, us_aqi, pm2_5, pm10, observed_at, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (city, current.get("us_aqi"), current.get("pm2_5"),
                 current.get("pm10"), observed_at),
            )
            conn.commit()
            logger.info("air_quality_refresh city=%s status=ok", city)
        except Exception:
            logger.exception("air_quality_refresh city=%s status=error", city)


# --- Construction fetcher ---

def refresh_construction(conn: sqlite3.Connection) -> None:
    """Fetch road construction data from Toronto Open Data CKAN."""
    try:
        resp = httpx.get(
            "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/datastore_search",
            params={
                "id": "40d94b5a-cbf2-4e04-8d48-24038d163d0c",
                "limit": 500,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        records = data.get("result", {}).get("records", [])
        count = 0

        for record in records:
            project_id = str(record.get("_id", ""))
            if not project_id:
                continue

            # Extract geometry
            geometry = record.get("geometry", {})
            geo_type = geometry.get("type", "") if isinstance(geometry, dict) else ""
            coords = geometry.get("coordinates", []) if isinstance(geometry, dict) else []

            lat, lon = None, None
            geometry_type = None
            geometry_json = None

            if geo_type == "LineString" and coords:
                # Compute centroid from LineString vertices
                lats = [c[1] for c in coords if len(c) >= 2]
                lons = [c[0] for c in coords if len(c) >= 2]
                if lats and lons:
                    lat = sum(lats) / len(lats)
                    lon = sum(lons) / len(lons)
                    geometry_type = "line"
                    import json
                    geometry_json = json.dumps(coords)
            elif geo_type == "Point" and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
                geometry_type = "point"

            if lat is None or lon is None:
                continue

            description = record.get("DESCRIPTION", record.get("LINEAR_NAME_FULL", ""))
            status = record.get("ACTIVITY_STATUS", "")

            conn.execute(
                "INSERT OR REPLACE INTO cached_construction "
                "(project_id, city, description, lat, lon, status, start_year, "
                "geometry_type, geometry_json, fetched_at) "
                "VALUES (?, 'toronto', ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (f"tor-{project_id}", description, lat, lon, status,
                 record.get("YEAR", None), geometry_type, geometry_json),
            )
            count += 1

        conn.commit()
        logger.info("construction_refresh city=toronto count=%d", count)
    except Exception:
        logger.exception("construction_refresh status=error")


# --- Holiday fetcher ---

def refresh_holidays(conn: sqlite3.Connection) -> None:
    """Fetch Canadian public holidays from Nager.at API."""
    year = datetime.now(timezone.utc).year
    for yr in [year, year + 1]:
        try:
            resp = httpx.get(
                f"https://date.nager.at/api/v3/PublicHolidays/{yr}/CA",
                timeout=15.0,
            )
            resp.raise_for_status()
            holidays = resp.json()

            for h in holidays:
                h_date = h.get("date", "")
                h_name = h.get("localName", h.get("name", ""))
                is_global = 1 if h.get("global", False) else 0
                counties = h.get("counties") or []
                # Nager.at uses "CA-ON", "CA-BC" format
                provinces = ",".join(c.replace("CA-", "") for c in counties) if counties else None

                conn.execute(
                    "INSERT OR REPLACE INTO cached_holidays "
                    "(date, country_code, name, is_global, provinces, fetched_at) "
                    "VALUES (?, 'CA', ?, ?, ?, datetime('now'))",
                    (h_date, h_name, is_global, provinces),
                )

            conn.commit()
            logger.info("holidays_refresh year=%d count=%d", yr, len(holidays))
        except Exception:
            logger.exception("holidays_refresh year=%d status=error", yr)


# --- Economic indicators fetcher ---

def refresh_economic_indicators(conn: sqlite3.Connection) -> None:
    """Fetch CPI and USD/CAD from Bank of Canada Valet API."""
    _fetch_boc_series(conn, "STATIC_TOTALCPICHANGE", "cpi_yoy_pct")
    _fetch_boc_series(conn, "FXUSDCAD", "usdcad_rate")


def _fetch_boc_series(conn: sqlite3.Connection, series: str, indicator: str) -> None:
    """Fetch a single series from Bank of Canada Valet API."""
    try:
        resp = httpx.get(
            f"https://www.bankofcanada.ca/valet/observations/{series}/json",
            params={"recent": 1},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        observations = data.get("observations", [])
        if not observations:
            return

        obs = observations[-1]
        period = obs.get("d", "")
        # Value is under the series key
        value = None
        for key, val in obs.items():
            if key == "d":
                continue
            if isinstance(val, dict):
                value = val.get("v")
            elif isinstance(val, (int, float)):
                value = val

        if value is None:
            return

        conn.execute(
            "INSERT OR REPLACE INTO cached_economic_indicators "
            "(indicator, value, period, fetched_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (indicator, float(value), period),
        )
        conn.commit()
        logger.info("economic_refresh indicator=%s value=%.4f", indicator, float(value))
    except Exception:
        logger.exception("economic_refresh indicator=%s status=error", indicator)


# --- Geomagnetic fetcher ---

def refresh_geomagnetic(conn: sqlite3.Connection) -> None:
    """Fetch Kp index from NOAA SWPC."""
    try:
        resp = httpx.get(
            "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data or len(data) < 2:
            return

        # Data format: list of lists. First row is headers, rest are data.
        # Columns: time_tag, Kp, a_running, station_count
        count = 0
        for row in data[1:]:
            if len(row) < 2:
                continue
            time_tag = row[0]
            try:
                kp = float(row[1])
            except (ValueError, TypeError):
                continue

            observed_at = time_tag.replace("T", " ")[:19]

            conn.execute(
                "INSERT OR REPLACE INTO cached_geomagnetic "
                "(observed_at, kp_index, fetched_at) "
                "VALUES (?, ?, datetime('now'))",
                (observed_at, kp),
            )
            count += 1

        conn.commit()
        logger.info("geomagnetic_refresh readings=%d", count)
    except Exception:
        logger.exception("geomagnetic_refresh status=error")


# --- Sports event fetchers ---

# NHL team IDs for Canadian teams in our cities
_NHL_TEAMS = {
    "TOR": {"city": "toronto", "venue": "scotiabank_arena"},
    "VAN": {"city": "vancouver", "venue": "rogers_arena"},
}

# MLB team IDs
_MLB_TEAMS = {
    141: {"city": "toronto", "venue": "rogers_centre", "name": "Blue Jays"},
}

# NBA team abbreviations
_NBA_TEAMS = {
    "TOR": {"city": "toronto", "venue": "scotiabank_arena", "name": "Raptors"},
}


def refresh_sports_events(conn: sqlite3.Connection) -> None:
    """Fetch upcoming games from NHL, MLB, and NBA APIs."""
    _fetch_nhl_schedule(conn)
    _fetch_mlb_schedule(conn)
    _fetch_nba_schedule(conn)


def _fetch_nhl_schedule(conn: sqlite3.Connection) -> None:
    """Fetch NHL schedule from the public API."""
    try:
        resp = httpx.get("https://api-web.nhle.com/v1/schedule/now", timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()

        for game_week in data.get("gameWeek", []):
            for game in game_week.get("games", []):
                home_abbrev = game.get("homeTeam", {}).get("abbrev", "")
                away_abbrev = game.get("awayTeam", {}).get("abbrev", "")

                # Check if either team is one we track
                for abbrev in [home_abbrev, away_abbrev]:
                    team_info = _NHL_TEAMS.get(abbrev)
                    if team_info is None:
                        continue

                    venue = VENUES[team_info["venue"]]
                    game_id = f"nhl-{game.get('id', '')}"
                    start_utc = game.get("startTimeUTC", "")

                    # Parse start time
                    if not start_utc:
                        continue
                    start_str = start_utc.replace("T", " ").replace("Z", "")[:19]
                    try:
                        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    end_dt = start_dt + timedelta(hours=3)

                    home_name = game.get("homeTeam", {}).get("placeName", {})
                    away_name = game.get("awayTeam", {}).get("placeName", {})
                    if isinstance(home_name, dict):
                        home_name = home_name.get("default", "")
                    if isinstance(away_name, dict):
                        away_name = away_name.get("default", "")
                    event_name = f"NHL: {away_name} @ {home_name}"

                    conn.execute(
                        "INSERT OR REPLACE INTO cached_events "
                        "(event_id, source, venue_name, venue_lat, venue_lon, city, "
                        "event_name, start_time, end_time, expected_attendance, fetched_at) "
                        "VALUES (?, 'nhl', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (game_id, team_info["venue"], venue["lat"], venue["lon"],
                         team_info["city"], event_name,
                         start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                         end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                         venue["capacity"]),
                    )

        conn.commit()
        logger.info("nhl_refresh status=ok")
    except Exception:
        logger.exception("nhl_refresh status=error")


def _fetch_mlb_schedule(conn: sqlite3.Connection) -> None:
    """Fetch MLB schedule for tracked teams."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")

    for team_id, team_info in _MLB_TEAMS.items():
        try:
            url = (
                f"https://statsapi.mlb.com/api/v1/schedule"
                f"?sportId=1&teamId={team_id}&startDate={today}&endDate={end_date}"
            )
            resp = httpx.get(url, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()

            venue = VENUES[team_info["venue"]]

            for date_entry in data.get("dates", []):
                for game in date_entry.get("games", []):
                    game_id = f"mlb-{game.get('gamePk', '')}"
                    game_date = game.get("gameDate", "")
                    if not game_date:
                        continue

                    start_str = game_date.replace("T", " ").replace("Z", "")[:19]
                    try:
                        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    end_dt = start_dt + timedelta(hours=3, minutes=30)

                    away_team = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
                    home_team = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
                    event_name = f"MLB: {away_team} @ {home_team}"

                    conn.execute(
                        "INSERT OR REPLACE INTO cached_events "
                        "(event_id, source, venue_name, venue_lat, venue_lon, city, "
                        "event_name, start_time, end_time, expected_attendance, fetched_at) "
                        "VALUES (?, 'mlb', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (game_id, team_info["venue"], venue["lat"], venue["lon"],
                         team_info["city"], event_name,
                         start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                         end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                         venue["capacity"]),
                    )

            conn.commit()
            logger.info("mlb_refresh team=%d status=ok", team_id)
        except Exception:
            logger.exception("mlb_refresh team=%d status=error", team_id)


def _fetch_nba_schedule(conn: sqlite3.Connection) -> None:
    """Fetch NBA schedule from the static CDN."""
    try:
        resp = httpx.get(
            "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
            timeout=15.0,
            headers={"User-Agent": "findparking/0.1"},
        )
        resp.raise_for_status()
        data = resp.json()

        league_schedule = data.get("leagueSchedule", {})
        game_dates = league_schedule.get("gameDates", [])

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        window_end = now + timedelta(days=7)

        for date_entry in game_dates:
            for game in date_entry.get("games", []):
                home_abbrev = game.get("homeTeam", {}).get("teamTricode", "")
                away_abbrev = game.get("awayTeam", {}).get("teamTricode", "")

                for abbrev in [home_abbrev, away_abbrev]:
                    team_info = _NBA_TEAMS.get(abbrev)
                    if team_info is None:
                        continue

                    game_id = f"nba-{game.get('gameId', '')}"
                    game_dt_str = game.get("gameDateTimeUTC", "")
                    if not game_dt_str:
                        continue

                    start_str = game_dt_str.replace("T", " ").replace("Z", "")[:19]
                    try:
                        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    # Only games within our window
                    start_dt_utc = start_dt.replace(tzinfo=timezone.utc)
                    if start_dt_utc < window_start or start_dt_utc > window_end:
                        continue

                    end_dt = start_dt + timedelta(hours=2, minutes=30)
                    venue = VENUES[team_info["venue"]]

                    home_name = game.get("homeTeam", {}).get("teamName", "")
                    away_name = game.get("awayTeam", {}).get("teamName", "")
                    event_name = f"NBA: {away_name} @ {home_name}"

                    conn.execute(
                        "INSERT OR REPLACE INTO cached_events "
                        "(event_id, source, venue_name, venue_lat, venue_lon, city, "
                        "event_name, start_time, end_time, expected_attendance, fetched_at) "
                        "VALUES (?, 'nba', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (game_id, team_info["venue"], venue["lat"], venue["lon"],
                         team_info["city"], event_name,
                         start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                         end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                         venue["capacity"]),
                    )

        conn.commit()
        logger.info("nba_refresh status=ok")
    except Exception:
        logger.exception("nba_refresh status=error")


# --- Road disruptions fetcher ---

def _city_from_coords(lat: float, lon: float) -> str | None:
    """Determine which tracked city a coordinate falls within, using bounding boxes."""
    from cv_pipeline.city_config import CITIES
    for city_name, cfg in CITIES.items():
        b = cfg["bounds"]
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return city_name
    return None


def refresh_road_disruptions(conn: sqlite3.Connection) -> None:
    """Fetch road disruptions from Toronto Open Data and Ontario 511."""
    _fetch_toronto_road_restrictions(conn)
    _fetch_ontario_511_events(conn)


def _fetch_toronto_road_restrictions(conn: sqlite3.Connection) -> None:
    """Fetch Toronto road restrictions from open data API."""
    try:
        resp = httpx.get(
            "https://secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json",
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # Clear old Toronto disruptions (only toronto-prefixed, not on511)
        conn.execute(
            "DELETE FROM cached_road_disruptions WHERE city = 'toronto' AND disruption_id NOT LIKE 'on511-%'",
        )

        restrictions = data if isinstance(data, list) else data.get("Restrictions", data.get("restrictions", []))
        if not isinstance(restrictions, list):
            logger.warning("road_disruptions unexpected format")
            conn.commit()
            return

        count = 0
        for item in restrictions:
            lat = item.get("latitude") or item.get("lat")
            lon = item.get("longitude") or item.get("lng") or item.get("lon")
            if lat is None or lon is None:
                continue

            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError):
                continue

            disruption_id = str(item.get("id", item.get("_id", f"tor-{count}")))
            description = item.get("description", item.get("name", "Road restriction"))
            severity = _classify_road_severity(description)

            conn.execute(
                "INSERT OR REPLACE INTO cached_road_disruptions "
                "(disruption_id, city, description, lat, lon, radius_km, severity, fetched_at) "
                "VALUES (?, 'toronto', ?, ?, ?, 0.2, ?, datetime('now'))",
                (disruption_id, description, lat, lon, severity),
            )
            count += 1

        conn.commit()
        logger.info("road_disruptions_refresh city=toronto source=opendata count=%d", count)
    except Exception:
        logger.exception("road_disruptions_refresh source=opendata status=error")


def _fetch_ontario_511_events(conn: sqlite3.Connection) -> None:
    """Fetch road events from Ontario 511 API for all tracked Ontario cities."""
    try:
        resp = httpx.get(
            "https://511on.ca/api/v2/get/event",
            timeout=20.0,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        events = resp.json()

        if not isinstance(events, list):
            logger.warning("ontario_511 unexpected format")
            return

        # Clear old Ontario 511 disruptions across all cities
        conn.execute("DELETE FROM cached_road_disruptions WHERE disruption_id LIKE 'on511-%'")

        count = 0
        for event in events:
            # Extract coordinates
            lat = event.get("Latitude") or event.get("latitude")
            lon = event.get("Longitude") or event.get("longitude")
            if lat is None or lon is None:
                # Try nested geography
                geo = event.get("Geography", event.get("geography", {}))
                if isinstance(geo, dict):
                    lat = geo.get("Latitude") or geo.get("latitude")
                    lon = geo.get("Longitude") or geo.get("longitude")
            if lat is None or lon is None:
                continue

            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError):
                continue

            # Only keep events within a tracked city
            city = _city_from_coords(lat, lon)
            if city is None:
                continue

            event_id = event.get("ID") or event.get("id") or event.get("EventId")
            if event_id is None:
                continue
            disruption_id = f"on511-{event_id}"

            description = (
                event.get("Description")
                or event.get("description")
                or event.get("EventType", "Road event")
            )
            severity = _classify_road_severity(description)

            conn.execute(
                "INSERT OR REPLACE INTO cached_road_disruptions "
                "(disruption_id, city, description, lat, lon, radius_km, severity, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, 0.3, ?, datetime('now'))",
                (disruption_id, city, description, lat, lon, severity),
            )
            count += 1

        conn.commit()
        logger.info("road_disruptions_refresh source=ontario_511 count=%d", count)
    except Exception:
        logger.exception("road_disruptions_refresh source=ontario_511 status=error")


def _classify_road_severity(description: str) -> str:
    """Infer severity from road restriction description."""
    lower = description.lower() if description else ""
    if any(w in lower for w in ("full closure", "closed", "emergency", "major")):
        return "major"
    if any(w in lower for w in ("lane reduction", "construction", "partial")):
        return "moderate"
    return "minor"


# --- Team streaks fetcher ---

def refresh_team_streaks(conn: sqlite3.Connection) -> None:
    """Fetch team streaks from NHL and MLB public APIs."""
    _fetch_nhl_streaks(conn)
    _fetch_mlb_streaks(conn)


def _fetch_nhl_streaks(conn: sqlite3.Connection) -> None:
    """Fetch NHL standings and extract streak data."""
    try:
        resp = httpx.get(
            "https://api-web.nhle.com/v1/standings/now",
            timeout=15.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()

        standings = data.get("standings", [])
        count = 0
        for team in standings:
            abbrev = team.get("teamAbbrev", {})
            if isinstance(abbrev, dict):
                abbrev = abbrev.get("default", "")
            if not abbrev:
                continue

            streak_code = team.get("streakCode", "")
            streak_count = team.get("streakCount", 0)

            conn.execute(
                "INSERT OR REPLACE INTO cached_team_streaks "
                "(team_abbrev, league, streak_code, streak_count, fetched_at) "
                "VALUES (?, 'NHL', ?, ?, datetime('now'))",
                (abbrev, streak_code, streak_count),
            )
            count += 1

        conn.commit()
        logger.info("streak_refresh league=NHL teams=%d", count)
    except Exception:
        logger.exception("streak_refresh league=NHL status=error")


def _fetch_mlb_streaks(conn: sqlite3.Connection) -> None:
    """Fetch MLB standings and extract streak data."""
    try:
        year = datetime.now(timezone.utc).year
        resp = httpx.get(
            f"https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={year}",
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # MLB team ID to abbreviation mapping for our tracked teams
        mlb_team_abbrevs = {
            141: "TOR-MLB",  # Blue Jays
        }

        count = 0
        for record_group in data.get("records", []):
            for team_record in record_group.get("teamRecords", []):
                team_id = team_record.get("team", {}).get("id")
                abbrev = mlb_team_abbrevs.get(team_id)
                if abbrev is None:
                    continue

                streak = team_record.get("streak", {})
                streak_code = streak.get("streakCode", "")
                # Parse "W5" or "L3" format
                if streak_code and len(streak_code) >= 2:
                    code_letter = streak_code[0].upper()
                    try:
                        count_val = int(streak_code[1:])
                    except ValueError:
                        code_letter = ""
                        count_val = 0
                else:
                    code_letter = ""
                    count_val = 0

                conn.execute(
                    "INSERT OR REPLACE INTO cached_team_streaks "
                    "(team_abbrev, league, streak_code, streak_count, fetched_at) "
                    "VALUES (?, 'MLB', ?, ?, datetime('now'))",
                    (abbrev, code_letter, count_val),
                )
                count += 1

        conn.commit()
        logger.info("streak_refresh league=MLB teams=%d", count)
    except Exception:
        logger.exception("streak_refresh league=MLB status=error")


# --- Time weights recalculation ---

def recalculate_time_weights(conn: sqlite3.Connection) -> None:
    """Recompute time_of_day_weights from 30-day rolling window of occupancy_snapshots."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    rows = conn.execute(
        "SELECT lot_id, "
        "CAST(strftime('%%H', timestamp) AS INTEGER) as hour, "
        "CAST(strftime('%%w', timestamp) AS INTEGER) as dow, "
        "AVG(probability_score) as avg_prob, "
        "COUNT(*) as cnt "
        "FROM occupancy_snapshots "
        "WHERE timestamp >= ? "
        "GROUP BY lot_id, hour, dow "
        "HAVING cnt >= 3",
        (cutoff,),
    ).fetchall()

    if not rows:
        logger.info("time_weights_recalc no data")
        return

    count = 0
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO time_of_day_weights (lot_id, hour, day_of_week, weight) "
            "VALUES (?, ?, ?, ?)",
            (row["lot_id"], row["hour"], row["dow"], round(row["avg_prob"], 4)),
        )
        count += 1

    conn.commit()
    logger.info("time_weights_recalc updated %d entries", count)
