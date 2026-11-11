# Weather (Open-Meteo) — session 20

Source of an on-water/outdoor workout's conditions. Chosen because the **archive API needs no key**,
returns hourly temperature, wind speed/direction/gusts, precipitation, humidity, pressure and a WMO
weather code back to 1940, and its data is CC BY 4.0. Facts below were read from Open-Meteo's own
terms/pricing/docs pages and confirmed with live read-only calls on 2026-11-11 (neutral coordinates).

## Endpoint

`GET https://archive-api.open-meteo.com/v1/archive`

| param | value | why |
|---|---|---|
| `latitude`, `longitude` | rounded to 0.1° | privacy + matches the grid + makes cache keys stable |
| `start_date`, `end_date` | the same UTC day | one cell-day per request |
| `hourly` | `temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl` | pressure is `pressure_msl`, not `pressure` |
| `timezone` | `GMT` | cell-days are UTC days; `start_date`/`end_date` are read in the requested timezone |
| `timeformat` | `unixtime` | UTC hour-start stamps, no DST ambiguity |
| `wind_speed_unit` | `kmh` | the default, stated explicitly |

Response: `hourly.time[]` (24 stamps) plus one array per variable; also `latitude`/`longitude` (the
grid cell the model snapped to) and `elevation`. Confirmed live: wind direction is the direction the
wind blows **from** (degrees); `precipitation` is a preceding-hour sum, the rest are instantaneous
(`docs/analytics.md` §28.5).

**Recent days.** Data for yesterday and today returned 24 hours with no nulls (the IFS model has no
delay), but ERA5 reanalysis lands ~5 days late and the recent hours are model analysis that can later
be revised. A day newer than 7 days is therefore stored as *provisional* (`complete = false`) and
re-fetched at most every 12 h until final; a day still incomplete after 30 days is left alone.

## Limits, licence, attribution

- **Free API: non-commercial use only.** Non-commercial per the terms includes "private or non-profit
  websites or apps that do not have subscriptions or advertising" and personal use. Commercial includes
  "websites or apps that have subscriptions or display advertisements". The terms don't address a
  self-hosted app explicitly; a personal, single-user install is the clearest case of the first kind.
  **A public deployment with subscriptions/ads needs a paid plan** (Standard 1M calls/month and up; the
  pricing page showed no figures when read — contact info@open-meteo.com). Recorded as a launch blocker
  in PLAN.md.
- Rate limits (free): 600/min, 5,000/hour, 10,000/day, 300,000/month, by IP and application. A request
  for > 10 variables or > 2 weeks counts as several calls — ours is one day and 8 variables. Catch
  self-limits to 30/min and 2,000/day (`catch/sync/weather_client.py`).
- **Data licence CC BY 4.0**: appropriate credit is required. Every weather payload and coach-tool
  result carries `attribution` + `attribution_url`, and the UI renders them as a link:
  *"Weather data by Open-Meteo.com (CC BY 4.0), based on ECMWF ERA5 / IFS reanalysis (contains modified
  Copernicus Climate Change Service information)."* The values are interpolated in time, which counts
  as a modification and is stated in the card's own text.
- **Retention / caching**: the terms impose no storage restriction on responses. Catch keeps each
  response indefinitely in `weather_cells` (≈3 KB per cell-day), keyed `(provider, lat×10, lon×10,
  utc_date)`, so a given cell-day is requested once it is final. Open-Meteo keeps its own web-server
  logs (which can contain coordinates) for 90 days — another reason coordinates are rounded to 0.1°
  before being sent.
- No API key is used. The User-Agent is the generic `Catch/1.0 (self-hosted training log)` — never an
  email address.

## What is, and is not, claimed

The numbers are gridded model/reanalysis data for a ~9–25 km cell, not a measurement at the water.
Catch shows them as context, says so on the card ("not a measurement taken at the water … never a
performance correction"), and does not compute a head/tail-wind component or any corrected time.

## Map tiles (separate from weather)

The route map uses OpenStreetMap's public tile server (`web/src/lib/mapConfig.ts`). That's fine for
light personal use with the required visible attribution ("© OpenStreetMap contributors"); OSM's tile
usage policy is **not** intended for commercial-scale traffic, so a public build should swap
`TILE_URL` for a self-hosted or commercial tile source. Tiles are fetched directly by the browser
(cross-origin, so the service worker never caches them) and the track is a vector overlay, so an
offline page still shows the route on a blank background.
