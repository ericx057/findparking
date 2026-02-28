# FindParking

FindParking helps you decide where to park before you arrive.

It shows nearby lots and gives each one a probability score that represents how likely you are to find an open spot right now. Instead of driving lot-to-lot, you can compare options on one map and pick the best chance first.

## What You See

- A map of parking lots
- Live availability probability for each lot
- Lot details such as occupancy trend and status

## Who This Is For

- Drivers choosing between lots before a trip
- Anyone who wants a quick estimate instead of guessing parking availability

## How the Estimate Is Produced

FindParking blends multiple signals into a single confidence-weighted score:

- **Camera feed** -- Vehicle tripwire detections (highest weight, confidence decays with staleness)
- **Sports events** -- NHL, MLB, NBA schedules from free APIs; reduces nearby lot scores before and during games
- **Weather** -- Environment Canada current conditions; rain, snow, and extreme temperatures shift demand patterns
- **Time-of-day patterns** -- Historical occupancy trends by hour and day of week
- **Road disruptions** -- Toronto open data road closures and construction
- **Ticketmaster events** -- Concerts and festivals (optional, requires API key)

When some signals are unavailable, weights renormalize across whatever is present. The result is a practical probability score, not a guarantee.

## Deploy to Render

### One-click deploy

1. Push this repo to GitHub.
2. Go to [Render Dashboard](https://dashboard.render.com/) and select **New > Blueprint**.
3. Connect your GitHub repo. Render will detect `render.yaml` and configure the service automatically.
4. Optionally set `PARKING_TICKETMASTER_API_KEY` in the Render dashboard for concert/festival event data.
5. Deploy. The app creates the database and seeds parking lots on first startup.

### What happens on deploy

- Render installs production dependencies from `requirements.txt`.
- Uvicorn starts on the port Render assigns.
- SQLite database is created at `/tmp/findparking.db`.
- If the database is empty, 15 lots across 3 cities are seeded automatically.
- Background scheduler fetches weather and sports event data on startup.
- The filesystem is ephemeral: the database resets on every deploy or restart. Fresh signal data is fetched on each startup.

### Environment variables

All prefixed with `PARKING_`. Set in the Render dashboard or in a local `.env` file.

| Variable | Default | Description |
|---|---|---|
| `PARKING_DB_PATH` | `findparking.db` | Path to SQLite database file |
| `PARKING_CITY` | `waterloo` | Default city for frontend |
| `PARKING_LOG_LEVEL` | `INFO` | Python log level |
| `PARKING_TICKETMASTER_API_KEY` | *(empty)* | Optional Ticketmaster API key |

## Quick Start (Local)

https://findparking.onrender.com