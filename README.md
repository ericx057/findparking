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

https://findparking.onrender.com