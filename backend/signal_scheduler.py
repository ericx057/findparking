"""Background scheduler for signal data refresh jobs."""

import logging
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

import httpx

from backend.signals.events_sports import VENUES
from backend.signals.weather import WEATHER_FEEDS, _WEATHER_BASE_URL, classify_condition

logger = logging.getLogger("findparking.signal_scheduler")


def refresh_weather(conn: sqlite3.Connection) -> None:
    """Fetch current conditions from Environment Canada for all configured cities."""
    for city, feed_info in WEATHER_FEEDS.items():
        try:
            xml_text = _fetch_latest_weather_xml(feed_info["province"], feed_info["station"])
            if xml_text is None:
                logger.warning("weather_refresh city=%s no xml found", city)
                continue
            _parse_and_store_weather(conn, city, xml_text)
            logger.info("weather_refresh city=%s status=ok", city)
        except Exception:
            logger.exception("weather_refresh city=%s status=error", city)


def _fetch_latest_weather_xml(province: str, station: str) -> str | None:
    """Fetch the latest weather XML for a station from HPFX directory listing.

    The new Environment Canada HPFX server organises files under:
      /today/citypage_weather/{province}/{hour}/
    Each file is named like:
      20260228T000119.052Z_MSC_CitypageWeather_{station}_en.xml

    Strategy: scan hour directories from most recent backwards, find the
    first file matching our station code, and fetch it.
    """
    now_utc = datetime.now(timezone.utc)

    # Try last 6 hours of directories (most recent first)
    for hours_back in range(6):
        hour = (now_utc - timedelta(hours=hours_back)).strftime("%H")
        dir_url = f"{_WEATHER_BASE_URL}/{province}/{hour}/"

        try:
            resp = httpx.get(dir_url, timeout=10.0)
            if resp.status_code != 200:
                continue

            # Parse directory listing HTML for links matching our station
            pattern = rf'href="([^"]*CitypageWeather_{station}_en\.xml)"'
            matches = re.findall(pattern, resp.text)
            if not matches:
                continue

            # Take the last match (most recent timestamp in sorted listing)
            filename = matches[-1]
            # Handle both relative and absolute URLs
            if filename.startswith("http"):
                file_url = filename
            else:
                file_url = f"{dir_url}{filename}"

            xml_resp = httpx.get(file_url, timeout=15.0)
            xml_resp.raise_for_status()
            return xml_resp.text

        except Exception:
            continue

    return None


def _parse_and_store_weather(conn: sqlite3.Connection, city: str, xml_text: str) -> None:
    """Parse Environment Canada XML and upsert into cached_weather."""
    root = ElementTree.fromstring(xml_text)
    ns = {"ec": "http://dd.weather.gc.ca/citypage_weather/"}

    current = root.find(".//currentConditions")
    if current is None:
        # Try without namespace
        current = root.find("currentConditions")
    if current is None:
        logger.warning("weather_parse city=%s no currentConditions element", city)
        return

    condition_el = current.find("condition")
    raw_condition = condition_el.text if condition_el is not None and condition_el.text else "clear"

    temp_el = current.find("temperature")
    temp_celsius = None
    if temp_el is not None and temp_el.text:
        try:
            temp_celsius = float(temp_el.text)
        except ValueError:
            pass

    wind_el = current.find("wind/speed")
    wind_kph = None
    if wind_el is not None and wind_el.text:
        try:
            wind_kph = float(wind_el.text)
        except ValueError:
            pass

    # Use dateTime element for observation time (extract year/month/day/hour/minute components)
    observed_at = None
    for dt_el in current.findall("dateTime"):
        zone = dt_el.get("zone", "")
        if zone == "UTC":
            year_el = dt_el.find("year")
            month_el = dt_el.find("month")
            day_el = dt_el.find("day")
            hour_el = dt_el.find("hour")
            minute_el = dt_el.find("minute")
            if all(el is not None and el.text for el in [year_el, month_el, day_el, hour_el, minute_el]):
                observed_at = (
                    f"{year_el.text}-{month_el.text.zfill(2)}-{day_el.text.zfill(2)} "
                    f"{hour_el.text.zfill(2)}:{minute_el.text.zfill(2)}:00"
                )
                break

    if observed_at is None:
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    canonical_condition = classify_condition(raw_condition)

    conn.execute(
        "INSERT OR REPLACE INTO cached_weather "
        "(city, observed_at, condition, temp_celsius, wind_kph, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (city, observed_at, canonical_condition, temp_celsius, wind_kph),
    )
    conn.commit()


def register_signal_jobs(scheduler, conn: sqlite3.Connection, ticketmaster_api_key: str = "") -> None:
    """Register all signal refresh jobs with the APScheduler instance."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    # Weather: every 30 minutes
    scheduler.add_job(
        refresh_weather,
        trigger=IntervalTrigger(minutes=30),
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

    logger.info("signal_scheduler registered jobs")


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

def refresh_road_disruptions(conn: sqlite3.Connection) -> None:
    """Fetch Toronto road restrictions from open data API."""
    try:
        resp = httpx.get(
            "https://secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json",
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # Clear old Toronto disruptions before inserting fresh data
        conn.execute("DELETE FROM cached_road_disruptions WHERE city = 'toronto'")

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
        logger.info("road_disruptions_refresh city=toronto count=%d", count)
    except Exception:
        logger.exception("road_disruptions_refresh status=error")


def _classify_road_severity(description: str) -> str:
    """Infer severity from road restriction description."""
    lower = description.lower() if description else ""
    if any(w in lower for w in ("full closure", "closed", "emergency", "major")):
        return "major"
    if any(w in lower for w in ("lane reduction", "construction", "partial")):
        return "moderate"
    return "minor"


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
