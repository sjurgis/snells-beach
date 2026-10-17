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


# --- Public station pages (Jurgis asked for this): parse the HTML wunderground.com serves.
# The dashboard is Angular SSR; the server embeds the station's recent 5-minute readings in
# <script id="app-root-state">. We read only that served content: no API key is extracted or
# reused, one request per station, short timeout, and any block/captcha just means "no data".
PAGE_STATIONS = [("IWARKW15", "Algies Bay"), ("ISNELL2", "Snells Beach")]
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
MPH_TO_KN, INHG_TO_HPA, IN_TO_MM = 0.868976, 33.8639, 25.4


def page_station(sid, name, now):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(f"https://www.wunderground.com/dashboard/pws/{sid}", headers={"User-Agent": BROWSER_UA}, timeout=15)
    r.raise_for_status()
    tag = BeautifulSoup(r.text, "html.parser").find("script", id="app-root-state")
    if not tag or not tag.string: raise ValueError("no app-root-state in page")
    raw = tag.string
    for a, b in (("&q;", '"'), ("&s;", "'"), ("&l;", "<"), ("&g;", ">"), ("&a;", "&")): raw = raw.replace(a, b)
    state = json.loads(raw)
    obs = []
    for v in state.values():
        b = v.get("b") if isinstance(v, dict) else None
        if isinstance(b, dict) and isinstance(b.get("observations"), list) and "/pws/observations/" in str(v.get("u", "")):
            obs = [o for o in b["observations"] if o.get("stationID") == sid] or obs
    if not obs: raise ValueError("no observations in page state")
    o = max(obs, key=lambda x: x.get("epoch", 0))
    t = dt.datetime.fromtimestamp(o["epoch"], dt.timezone.utc).astimezone(TZ)
    if not _fresh(t, now): raise ValueError(f"latest reading is old ({t:%Y-%m-%d %H:%M})")
    i = o.get("imperial") or {}
    if i.get("windspeedAvg") is None: raise ValueError("no wind in latest reading")
    f2c = lambda f: None if f is None else round((f - 32) * 5 / 9, 1)
    r1 = lambda x, k: None if x is None else round(x * k, 1)
    return {
        "id": sid, "name": name, "kind": "home", "lat": o.get("lat"), "lon": o.get("lon"),
        "time": t.replace(microsecond=0).isoformat(),
        "windKn": r1(i["windspeedAvg"], MPH_TO_KN), "gustKn": r1(i.get("windgustHigh"), MPH_TO_KN),
        "windDirDeg": o.get("winddirAvg"), "airC": f2c(i.get("tempAvg")),
        "pressureHpa": r1(i.get("pressureMax"), INHG_TO_HPA),
        "rainRateMmH": r1(i.get("precipRate"), IN_TO_MM), "rainTodayMm": r1(i.get("precipTotal"), IN_TO_MM),
        "url": f"https://www.wunderground.com/dashboard/pws/{sid}", "via": "page",
    }


def pages(now):
    out = []
    for sid, name in PAGE_STATIONS:
        try: out.append(page_station(sid, name, now))
        except Exception as e: print(f"warning: WU page {sid}: {e}", file=sys.stderr)
    return out


def collect(now=None):
    """(observations dict or None, sources entry or None)."""
    now = now or dt.datetime.now(TZ)
    key = os.environ.get("WU_API_KEY", "").strip()
    st = wu(key, now) if key else []
    if not st:
        st = pages(now)
        if st:
            return ({"fetched": now.replace(microsecond=0).isoformat(), "kind": "home", "blend": True, "stations": st},
                    {"what": "Live wind & rain (home stations)", "name": "Weather Underground station pages: " + ", ".join(f"{x['name']} ({x['id']})" for x in st),
                     "url": st[0]["url"]})
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
        return f"{s['name']} ({s['id']}) {d}{round(s['windKn'])} kn{g}{tc}{r} (at {h}:{t.minute:02d}{'pm' if t.hour >= 12 else 'am'})"
    if obs["kind"] == "home" and len(obs["stations"]) == 1:
        return "Live: " + one(obs["stations"][0]).replace(" (", " home station (", 1)
    lead = "Live home stations" if obs["kind"] == "home" else "Live (airport obs, 50+ km away; home stations need a WU key)"
    return lead + ": " + "; ".join(one(s) for s in obs["stations"][:3])
