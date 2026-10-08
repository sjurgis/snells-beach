# `data/forecast.json` — the daily file

This is the **only** file the morning job rewrites. The page (`index.html`, `app.js`, `style.css`) and the
beach guide (`data/beaches.json`) stay as they are. The page scores every beach from this file, so it needs
numbers, not prose.

Easiest path: `python3 scripts/update_forecast.py && python3 scripts/validate.py` (fetches everything below
and writes the file). If you fill it by hand or from other sources, follow this spec exactly.

All times are **local Pacific/Auckland wall-clock time**, `"HH:MM"` 24-hour (e.g. `"07:00"`, `"19:17"`).
Units are in the field names: `Kn` knots, `M` metres, `S` seconds, `Deg` degrees true, `C` °C, `Mm` mm, `Pct` %.

## Top level

| field | type | required | meaning |
|---|---|---|---|
| `schemaVersion` | number | yes | always `1` |
| `updated` | string | yes | ISO 8601 **with offset**, when this file was made, e.g. `"2026-10-09T07:19:00+13:00"` (NZDT +13, NZST +12) |
| `timezone` | string | yes | always `"Pacific/Auckland"` |
| `location` | object | no | `{ "name": "Snells Beach", "lat": -36.42, "lon": 174.73 }` (info only) |
| `sources` | array | yes | non-empty; each `{ "what": "Wind & weather", "name": "met.no Locationforecast", "url": "https://…", "issued": "<ISO time, optional>" }`. Shown in the footer. |
| `days` | array | yes | consecutive dates, **today first**, normally 4 days (today + 3) |

## `days[]`

| field | type | required | meaning |
|---|---|---|---|
| `date` | `"YYYY-MM-DD"` | yes | local date |
| `sunrise`, `sunset` | `"HH:MM"` | yes | local times; slots outside daylight are ignored for picks |
| `airMaxC` | number | no | daily max air temp °C |
| `waterTempC` | number | no | sea surface temp °C (daytime mean, Kawau Bay) |
| `tides` | array | yes | every high/low turn that day **in time order, alternating**: `{ "time": "06:59", "type": "high", "heightM": 2.7 }`. Mahurangi Harbour. At least 2. |
| `slots` | array | yes | weather at fixed times, in time order. Use `07:00, 09:00, 11:00, 13:00, 15:00, 17:00, 19:00` (at least 2, at least one in daylight). |
| `swell` | array | yes | sea state at `06:00, 09:00, 12:00, 15:00, 18:00` (at least 1). The nearest entry to each slot is used. |
| `traffic` | object | no | `{ "level": "light" \| "moderate" \| "busy", "note": "short text" }`. Put it on Saturdays, Sundays and public holidays (Labour Day = 4th Monday of October). Its presence turns on the Matakana chip and a small score penalty for beaches through Matakana; weekends get the chip even without it. It is a heuristic note, not live traffic. |

### `slots[]`

| field | type | required | meaning |
|---|---|---|---|
| `time` | `"HH:MM"` | yes | local |
| `windDirDeg` | number 0–360 | yes | direction the wind blows **from**, degrees true (90 = easterly) |
| `windKn` | number | yes | mean wind speed, knots (met.no gives m/s: × 1.94384) |
| `gustKn` | number | no | gust, knots (≥ `windKn`) |
| `rainMm` | number | no | rain in the hour, mm |
| `airC` | number | no | air temp °C |
| `cloudPct` | number 0–100 | no | cloud cover |
| `sky` | string | no | one of `sun`, `partly`, `cloud`, `fog`, `showers`, `rain`, `storm` (drives the icon and a small rain penalty) |
| `src` | string | no | where the slot came from, e.g. `"met.no"` or `"open-meteo"` (info only) |

### `swell[]`

| field | type | required | meaning |
|---|---|---|---|
| `time` | `"HH:MM"` | yes | local |
| `open.swellM` | number | yes | swell height off Te Ārai (open coast), metres. Drives surf scores. |
| `open.periodS` | number | yes | swell period, seconds |
| `open.dirDeg` | number | yes | direction swell comes **from**, degrees true (45 = NE) |
| `open.waveM` | number | no | total significant wave height off Te Ārai, metres (flatness at open beaches) |
| `inner.waveM` | number | yes | total significant wave height in Kawau Bay, metres (flatness at the inner bays) |
| `inner.periodS`, `inner.dirDeg` | number | no | as above, Kawau Bay |

Open-Meteo Marine grid points used: inner `-36.42, 174.80` (snaps to -36.458, 174.875) and open `-36.13, 174.85`
(snaps to -36.125, 174.875), `cell_selection=sea`, hourly `swell_wave_height, swell_wave_period,
swell_wave_direction, wave_height, wave_period, wave_direction, sea_surface_temperature`.

## Minimal example (one day shown)

```json
{
  "schemaVersion": 1,
  "updated": "2026-10-09T07:19:00+13:00",
  "timezone": "Pacific/Auckland",
  "sources": [
    {"what": "Wind & weather", "name": "met.no Locationforecast", "url": "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=-36.42&lon=174.73"},
    {"what": "Swell & sea temp", "name": "Open-Meteo Marine", "url": "https://open-meteo.com/en/docs/marine-weather-api"},
    {"what": "Tides", "name": "tides4fishing Mahurangi Harbour", "url": "https://tides4fishing.com/nz/auckland/mahurangi-harbour"}
  ],
  "days": [
    {
      "date": "2026-10-10",
      "sunrise": "06:44", "sunset": "19:32",
      "airMaxC": 19.0, "waterTempC": 16.1,
      "tides": [
        {"time": "01:36", "type": "low",  "heightM": 0.6},
        {"time": "07:51", "type": "high", "heightM": 2.8},
        {"time": "13:57", "type": "low",  "heightM": 0.6},
        {"time": "20:06", "type": "high", "heightM": 2.8}
      ],
      "slots": [
        {"time": "07:00", "windDirDeg": 345, "windKn": 6.8, "gustKn": 6.8, "rainMm": 0, "sky": "cloud"},
        {"time": "13:00", "windDirDeg": 11,  "windKn": 12.2, "gustKn": 22.7, "rainMm": 0, "sky": "partly"}
      ],
      "swell": [
        {"time": "09:00", "open": {"swellM": 0.5, "periodS": 6.5, "dirDeg": 46, "waveM": 0.62},
                          "inner": {"waveM": 0.32, "periodS": 6.2, "dirDeg": 54}}
      ],
      "traffic": {"level": "busy", "note": "Weekend: expect queues through Matakana village, worst late morning to mid-afternoon"}
    }
  ]
}
```

## Rules of thumb

- Never invent numbers. If a source is down, use another real one (MetService marine, Open-Meteo forecast) and name it in `sources`.
- Keep `updated` honest; the page warns if it is more than 30 hours old.
- After writing: `python3 scripts/validate.py` must print `OK`. Exit code 1 means fix and re-run.

# `data/beaches.json` — the standing guide (rarely edited)

Per beach: `id`, `name`, `area`, `lat`/`lon`, `driveMin`/`driveKm` (OSRM from Snells Beach township),
`viaMatakana`, `facingDeg` (direction the beach looks out to sea; wind from there is onshore, from the opposite side
offshore), `shelteredFrom` (8-point wind directions that the local knowledge says are sheltered, e.g. `["SE"]`),
`tide` (`{"mode":"high","hours":3}` = good within 3 h of high; `{"mode":"all"}`), `exposure`
(`{"source":"inner"|"open","factor":0–1}` scales the Kawau Bay or Te Ārai wave height to this beach),
`suits` (0–1 per activity), `notes` (short bullets), optional `doc` (Goat Island DOC limits), and `dog`:
`{verified, checked, source, rules:[{from:"MM-DD", to:"MM-DD", status, chip, text}, …, {status, chip, text}]}`.
Dog rules are matched in order by date (ranges may wrap the new year); the last rule has no dates and is the
catch-all. `status` is `offlead` | `leash` | `limited` (time-restricted) | `banned`. A beach whose rule is not
verified should have `"verified": false` and the page shows "unverified, check signs".
