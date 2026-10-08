#!/usr/bin/env python3
"""Fetch fresh forecasts and rewrite data/forecast.json (stdlib only).

Sources:
  wind/weather  met.no locationforecast 2.0 (compact) for Snells Beach
  gusts, gaps   Open-Meteo forecast (hourly, knots)   - fills slots met.no no longer covers
  swell, sea    Open-Meteo marine: Kawau Bay (inner) and off Te Arai (open coast)
  sun           Open-Meteo daily sunrise/sunset
  tides         tides4fishing.com Mahurangi Harbour table

Usage:  python3 scripts/update_forecast.py [--days 4] [--start YYYY-MM-DD] [--out data/forecast.json]
Then:   python3 scripts/validate.py
See data/SCHEMA.md for the file format.
"""
import argparse, datetime as dt, html, json, re, sys, urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Pacific/Auckland")
UA = "snells-beach-site/1.0 github.com/sjurgis/snells-beach"
LAT, LON = -36.42, 174.73                 # Snells Beach
INNER = (-36.42, 174.80)                  # Kawau Bay (Open-Meteo snaps to -36.458, 174.875)
OPEN = (-36.13, 174.85)                   # off Te Arai (snaps to -36.125, 174.875)
SLOT_HOURS = [7, 9, 11, 13, 15, 17, 19]
SWELL_HOURS = [6, 9, 12, 15, 18]
MS_TO_KN = 1.943844
TIDE_URL = "https://tides4fishing.com/nz/auckland/mahurangi-harbour"


def get(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA if "met.no" in url else
                                               "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", "ignore")
    return body if raw else json.loads(body)


def sky(symbol):
    s = symbol or ""
    if "thunder" in s: return "storm"
    if "showers" in s: return "showers"
    if "rain" in s or "sleet" in s or "snow" in s: return "rain"
    if s.startswith("partlycloudy"): return "partly"
    if s.startswith("clearsky") or s.startswith("fair"): return "sun"
    if s.startswith("fog"): return "fog"
    if s: return "cloud"
    return None


def parse_tides(page, year, month):
    """Return {date: [ {time, type, heightM} ]} from the tides4fishing monthly table."""
    t = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", "", page)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    toks = [x.strip() for x in t.splitlines() if x.strip()]
    start = toks.index("SOLUNAR ACTIVITY", toks.index("TIDES FOR MAHURANGI"))
    toks = toks[start:]
    days, i = {}, 0
    wd = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    while i < len(toks) - 1:
        if toks[i].isdigit() and toks[i + 1] in wd:
            day = int(toks[i]); i += 2
            times, j = [], i
            while j < len(toks) - 1:
                m = re.fullmatch(r"(\d{1,2}):(\d{2})", toks[j])
                if m and toks[j + 1] in ("am", "pm"):
                    h = int(m.group(1)) % 12 + (12 if toks[j + 1] == "pm" else 0)
                    hm = f"{h:02d}:{m.group(2)}"
                    if j + 3 < len(toks) and re.fullmatch(r"\d+\.\d+", toks[j + 2]) and toks[j + 3] == "m":
                        times.append((hm, float(toks[j + 2]))); j += 4
                    else:
                        times.append((hm, None)); j += 2
                else:
                    break
            tides = [(hm, h) for hm, h in times if h is not None]   # first two are sunrise/sunset
            key = dt.date(year, month, day)
            if key in days:          # the page repeats day rows in later sections: first table wins
                break
            days[key] = tides
            i = j
        else:
            i += 1
    allh = [h for v in days.values() for _, h in v]
    mid = (max(allh) + min(allh)) / 2
    return {d: [{"time": hm, "type": "high" if h > mid else "low", "heightM": h} for hm, h in v]
            for d, v in days.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--start", help="first day YYYY-MM-DD (default today in Pacific/Auckland)")
    ap.add_argument("--out", default="data/forecast.json")
    a = ap.parse_args()
    now = dt.datetime.now(TZ)
    start = dt.date.fromisoformat(a.start) if a.start else now.date()
    dates = [start + dt.timedelta(days=k) for k in range(a.days)]
    end = dates[-1]

    met = get(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}")
    metno = {}
    for ts in met["properties"]["timeseries"]:
        t = dt.datetime.fromisoformat(ts["time"].replace("Z", "+00:00")).astimezone(TZ)
        d = ts["data"]; inst = d["instant"]["details"]
        nx = d.get("next_1_hours") or d.get("next_6_hours") or {}
        hours = 1 if "next_1_hours" in d else 6
        rain = nx.get("details", {}).get("precipitation_amount")
        metno[t.replace(minute=0, second=0, microsecond=0)] = {
            "windDirDeg": round(inst["wind_from_direction"]),
            "windKn": round(inst["wind_speed"] * MS_TO_KN, 1),
            "airC": round(inst["air_temperature"], 1),
            "cloudPct": round(inst.get("cloud_area_fraction", 0)),
            "rainMm": None if rain is None else round(rain / hours, 1),
            "sky": sky(nx.get("summary", {}).get("symbol_code")),
        }

    om = get("https://api.open-meteo.com/v1/forecast?"
             f"latitude={LAT}&longitude={LON}&timezone=Pacific%2FAuckland&wind_speed_unit=kn"
             f"&start_date={start}&end_date={end}"
             "&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,temperature_2m,cloud_cover,weather_code"
             "&daily=sunrise,sunset,temperature_2m_max")
    oh = om["hourly"]; ohi = {t: i for i, t in enumerate(oh["time"])}

    mar = get("https://marine-api.open-meteo.com/v1/marine?"
              f"latitude={INNER[0]},{OPEN[0]}&longitude={INNER[1]},{OPEN[1]}&cell_selection=sea"
              "&hourly=swell_wave_height,swell_wave_period,swell_wave_direction,wave_height,wave_period,wave_direction,sea_surface_temperature"
              f"&timezone=Pacific%2FAuckland&start_date={start}&end_date={end}")
    inner, open_ = mar[0]["hourly"], mar[1]["hourly"]

    tides = {}
    months = sorted({(d.year, d.month) for d in dates + [start - dt.timedelta(days=1), end + dt.timedelta(days=1)]})
    page = get(TIDE_URL, raw=True)
    tides.update(parse_tides(page, *months[0]))
    for y, m in months[1:]:
        if not all(d in tides for d in dates):
            try:
                tides.update(parse_tides(get(f"{TIDE_URL}/forecast/{y}-{m:02d}", raw=True), y, m))  # best effort
            except Exception as e:  # noqa
                print("warning: tides for", y, m, e, file=sys.stderr)

    def wmo_sky(code):
        if code is None: return None
        if code >= 95: return "storm"
        if code >= 80: return "showers"
        if code >= 51: return "rain"
        if code >= 45: return "fog"
        if code == 3: return "cloud"
        if code in (1, 2): return "partly"
        return "sun"

    days = []
    for di, d in enumerate(dates):
        slots = []
        for h in SLOT_HOURS:
            t = dt.datetime(d.year, d.month, d.day, h, tzinfo=TZ)
            key = f"{d}T{h:02d}:00"
            m = metno.get(t)
            src = "met.no"
            if m is None:   # met.no is 6-hourly after ~2.5 days: accept a met.no step within 1 h, else Open-Meteo
                near = [metno[k] for k in (t - dt.timedelta(hours=1), t + dt.timedelta(hours=1)) if k in metno]
                m = near[0] if near else None
            if m is None:
                if key not in ohi: continue
                i = ohi[key]; src = "open-meteo"
                m = {"windDirDeg": round(oh["wind_direction_10m"][i]), "windKn": round(oh["wind_speed_10m"][i], 1),
                     "airC": round(oh["temperature_2m"][i], 1), "cloudPct": round(oh["cloud_cover"][i]),
                     "rainMm": round(oh["precipitation"][i], 1), "sky": wmo_sky(oh["weather_code"][i])}
            slot = {"time": f"{h:02d}:00", **{k: v for k, v in m.items() if v is not None}, "src": src}
            if key in ohi and oh["wind_gusts_10m"][ohi[key]] is not None:
                slot["gustKn"] = round(max(oh["wind_gusts_10m"][ohi[key]], slot["windKn"]), 1)
            slots.append(slot)
        swell = []
        for h in SWELL_HOURS:
            key = f"{d}T{h:02d}:00"
            if key not in inner["time"]: continue
            i = inner["time"].index(key); j = open_["time"].index(key)
            swell.append({"time": f"{h:02d}:00",
                          "open": {"swellM": open_["swell_wave_height"][j], "periodS": open_["swell_wave_period"][j],
                                   "dirDeg": open_["swell_wave_direction"][j], "waveM": open_["wave_height"][j]},
                          "inner": {"waveM": inner["wave_height"][i], "periodS": inner["wave_period"][i],
                                    "dirDeg": inner["wave_direction"][i]}})
        sst = [inner["sea_surface_temperature"][k] for k, t in enumerate(inner["time"])
               if t.startswith(str(d)) and 9 <= int(t[11:13]) <= 18 and inner["sea_surface_temperature"][k] is not None]
        di_om = om["daily"]["time"].index(str(d))
        day = {"date": str(d),
               "sunrise": om["daily"]["sunrise"][di_om][11:16],
               "sunset": om["daily"]["sunset"][di_om][11:16],
               "airMaxC": om["daily"]["temperature_2m_max"][di_om],
               "waterTempC": round(sum(sst) / len(sst), 1) if sst else None,
               "tides": tides.get(d, []),
               "slots": slots, "swell": swell}
        if d.weekday() >= 5:
            day["traffic"] = {"level": "busy",
                              "note": "Weekend: expect queues through Matakana village, worst late morning to mid-afternoon"}
        if day["waterTempC"] is None: del day["waterTempC"]
        days.append(day)

    out = {
        "schemaVersion": 1,
        "updated": now.replace(microsecond=0).isoformat(),
        "timezone": "Pacific/Auckland",
        "location": {"name": "Snells Beach", "lat": LAT, "lon": LON},
        "sources": [
            {"what": "Wind & weather", "name": "met.no Locationforecast (Snells Beach)",
             "url": f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}",
             "issued": dt.datetime.fromisoformat(met["properties"]["meta"]["updated_at"].replace("Z", "+00:00")).astimezone(TZ).replace(microsecond=0).isoformat()},
            {"what": "Gusts, sunrise/sunset, gaps", "name": "Open-Meteo forecast", "url": "https://open-meteo.com/"},
            {"what": "Swell & sea temp", "name": "Open-Meteo Marine (Kawau Bay; off Te Ārai)", "url": "https://open-meteo.com/en/docs/marine-weather-api"},
            {"what": "Tides", "name": "tides4fishing Mahurangi Harbour", "url": TIDE_URL},
        ],
        "days": days,
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"wrote {a.out}: {len(days)} days, updated {out['updated']}")


if __name__ == "__main__":
    main()
