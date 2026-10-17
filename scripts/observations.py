"""Live observations for the Snells Beach page.

Home weather stations (Weather Underground PWS) need an API key: weather.com only gives
PWS API keys to people who register a station (free). Set WU_API_KEY to switch them on.
Without a key we fall back to the official airport METAR (aviationweather.gov, keyless),
which is 50+ km away, so it is shown but NOT blended into near-term scoring.
Nothing is invented: missing or stale readings are dropped.
"""
import datetime as dt, json, os, sys, urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Pacific/Auckland")
KMH_TO_KN = 0.539957
# Seen on wunderground.com / weatherwatch.co.nz (Oct 2026), nearest first.
WU_STATIONS = [
    ("ISNELL2", "Snells Beach"), ("ISNELL4", "HeronLane, Snells Beach"),
    ("IWARKW35", "Algies Bay"), ("IWARKW15", "Algies Bay"),
    ("IWARKW133", "Warkworth WS3900"), ("IWARKW119", "Warkworth"), ("IWARKW126", "Warkworth"),
    ("IWARKW18", "Warkworth"), ("IWARKW82", "Pohuehue"), ("IMATAK12", "MartySpace, Matakana"),
]
METAR_IDS = ["NZWP", "NZAA"]
MAX_AGE_MIN = 90


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "snells-beach/1.0 github.com/sjurgis/snells-beach"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def _fresh(t, now):
    return t is not None and (now - t).total_seconds() / 60 <= MAX_AGE_MIN


def wu(key, now):
    out = []
    for sid, name in WU_STATIONS:
        try:
            j = _get("https://api.weather.com/v2/pws/observations/current?stationId=" + sid
                     + "&format=json&units=m&numericPrecision=decimal&apiKey=" + key)
        except Exception as e:  # offline stations answer 204/404
            print(f"warning: WU {sid}: {e}", file=sys.stderr); continue
        for o in (j or {}).get("observations", []):
            t = dt.datetime.fromisoformat(o["obsTimeUtc"].replace("Z", "+00:00")).astimezone(TZ)
            m = o.get("metric") or {}
            if not _fresh(t, now) or m.get("windSpeed") is None: continue
            out.append({
                "id": sid, "name": o.get("neighborhood") or name, "kind": "home",
                "lat": o.get("lat"), "lon": o.get("lon"), "time": t.replace(microsecond=0).isoformat(),
                "windKn": round(m["windSpeed"] * KMH_TO_KN, 1),
                "gustKn": None if m.get("windGust") is None else round(m["windGust"] * KMH_TO_KN, 1),
                "windDirDeg": o.get("winddir"), "airC": m.get("temp"), "pressureHpa": m.get("pressure"),
                "rainRateMmH": m.get("precipRate"), "rainTodayMm": m.get("precipTotal"),
                "url": f"https://www.wunderground.com/dashboard/pws/{sid}",
            })
    return out


def metar(now):
    try:
        j = _get("https://aviationweather.gov/api/data/metar?format=json&ids=" + ",".join(METAR_IDS))
    except Exception as e:
        print(f"warning: METAR: {e}", file=sys.stderr); return []
    by = {o.get("icaoId"): o for o in j or []}
    for icao in METAR_IDS:  # nearest available airport only
        o = by.get(icao)
        if not o or o.get("wspd") is None: continue
        t = dt.datetime.fromtimestamp(o["obsTime"], dt.timezone.utc).astimezone(TZ)
        if not _fresh(t, now): continue
        wdir = o.get("wdir"); raw = o.get("rawOb") or ""
        return [{
            "id": icao, "name": (o.get("name") or icao).split(",")[0], "kind": "airport",
            "lat": o.get("lat"), "lon": o.get("lon"), "time": t.replace(microsecond=0).isoformat(),
            "windKn": float(o["wspd"]), "gustKn": None if o.get("wgst") is None else float(o["wgst"]),
            "windDirDeg": wdir if isinstance(wdir, (int, float)) else None,
            "airC": o.get("temp"), "pressureHpa": o.get("altim"), "rainRateMmH": None, "rainTodayMm": None,
            "raining": any(w in raw for w in ("RA ", "DZ ", "SHRA")),
            "url": f"https://aviationweather.gov/data/metar/?id={icao}",
        }]
    return []


def collect(now=None):
    """(observations dict or None, sources entry or None)."""
    now = now or dt.datetime.now(TZ)
    key = os.environ.get("WU_API_KEY", "").strip()
    st = wu(key, now) if key else []
    if st:
        kind = "home"
        src = {"what": "Live wind & rain (home stations)", "name": f"Weather Underground PWS, {len(st)} stations", "url": "https://www.wunderground.com/wundermap"}
    else:
        st = metar(now); kind = "airport"
        src = {"what": "Live wind (airport, shown only)", "name": "aviationweather.gov METAR", "url": "https://aviationweather.gov/"}
    if not st: return None, None
    return {"fetched": now.replace(microsecond=0).isoformat(), "kind": kind, "blend": kind == "home", "stations": st}, src


DIRS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def live_line(obs):
    if not obs: return "Live: no station readings right now."
    def one(s):
        t = dt.datetime.fromisoformat(s["time"]); h = t.hour % 12 or 12
        d = DIRS[round(s["windDirDeg"] / 22.5) % 16] + " " if s.get("windDirDeg") is not None and s["windKn"] >= 1 else ""
        g = f" gust {round(s['gustKn'])}" if s.get("gustKn") else ""
        tc = f", {round(s['airC'])}°C" if s.get("airC") is not None else ""
        r = f", rain {s['rainRateMmH']} mm/h" if s.get("rainRateMmH") else (", raining" if s.get("raining") else "")
        return f"{s['name']} {d}{round(s['windKn'])} kn{g}{tc}{r} (at {h}:{t.minute:02d}{'pm' if t.hour >= 12 else 'am'})"
    lead = "Live home stations" if obs["kind"] == "home" else "Live (airport obs, 50+ km away; home stations need a WU key)"
    return lead + ": " + "; ".join(one(s) for s in obs["stations"][:3])
