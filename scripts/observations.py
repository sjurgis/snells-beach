"""Live observations for the Snells Beach page.

Home weather stations (Weather Underground PWS) need an API key: weather.com only gives
PWS API keys to people who register a station (free). Set WU_API_KEY to switch them on.
Without a key we read the public station pages (below), then fall back to the official airport METAR (aviationweather.gov, keyless),
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


def _page_urls(sid, now):
    d = now.date().isoformat()
    return [f"https://www.wunderground.com/dashboard/pws/{sid}",
            f"https://www.wunderground.com/dashboard/pws/{sid}/table/{d}/{d}/daily",
            f"https://www.wunderground.com/dashboard/pws/{sid}/graph/{d}/{d}/daily"]


def _parse_state(html, sid):
    """Latest 5-minute reading from the server-rendered app-root-state, or None if this page variant has none.
    WU is A/B-testing a new front end (x-origin-hint: WuNext-Preview-Phased) that renders nothing server-side;
    those pages carry no readings at all, so the only legitimate option is to ask again."""
    from bs4 import BeautifulSoup
    tag = BeautifulSoup(html, "html.parser").find("script", id="app-root-state")
    if not tag or not tag.string: return None
    raw = tag.string
    for x, y in (("&q;", '"'), ("&s;", "'"), ("&l;", "<"), ("&g;", ">"), ("&a;", "&")): raw = raw.replace(x, y)
    obs = []
    for v in json.loads(raw).values():
        bb = v.get("b") if isinstance(v, dict) else None
        if isinstance(bb, dict) and isinstance(bb.get("observations"), list) and "/pws/observations/" in str(v.get("u", "")):
            obs = [o for o in bb["observations"] if o.get("stationID") == sid and o.get("epoch")] or obs
    return max(obs, key=lambda o: o["epoch"]) if obs else None


def page_station(sid, name, now, log):
    import requests, time
    headers = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-NZ,en;q=0.9"}
    urls = _page_urls(sid, now)
    o, tries = None, []
    for i in range(4):   # fresh request each time (no cookies), so each try gets a new A/B assignment
        url = urls[i % len(urls)]
        try:
            r = requests.get(url, headers=headers, timeout=15)
            variant = r.headers.get("x-origin-hint", "?")
            tries.append(f"{r.status_code}:{variant}")
            if r.status_code == 200: o = _parse_state(r.text, sid)
        except Exception as e:
            tries.append(f"err:{type(e).__name__}")
        if o: break
        time.sleep(2 * (i + 1))
    entry = {"id": sid, "ok": False, "attempts": len(tries), "tries": tries}
    log.append(entry)
    if not o: entry["error"] = "no readings in served page (client-rendered variant)"; raise ValueError(entry["error"])
    t = dt.datetime.fromtimestamp(o["epoch"], dt.timezone.utc).astimezone(TZ)
    if not _fresh(t, now): entry["error"] = f"latest reading old ({t:%H:%M})"; raise ValueError(entry["error"])
    if "metric" in o and isinstance(o["metric"], dict):
        m = o["metric"]; k = KMH_TO_KN
        wind, gust, temp, pres = m.get("windspeedAvg"), m.get("windgustHigh"), m.get("tempAvg"), m.get("pressureMax")
        rate, tot = m.get("precipRate"), m.get("precipTotal"); pk, rk = 1, 1
        tc = lambda v: v
    else:
        m = o.get("imperial") or {}; k = MPH_TO_KN
        wind, gust, temp, pres = m.get("windspeedAvg"), m.get("windgustHigh"), m.get("tempAvg"), m.get("pressureMax")
        rate, tot = m.get("precipRate"), m.get("precipTotal"); pk, rk = INHG_TO_HPA, IN_TO_MM
        tc = lambda f: None if f is None else (f - 32) * 5 / 9
    if wind is None: entry["error"] = "no wind in latest reading"; raise ValueError(entry["error"])
    r1 = lambda v, f: None if v is None else round(v * f, 1)
    entry["ok"] = True
    return {
        "id": sid, "name": name, "kind": "home", "lat": o.get("lat"), "lon": o.get("lon"),
        "time": t.replace(microsecond=0).isoformat(),
        "windKn": r1(wind, k), "gustKn": r1(gust, k), "windDirDeg": o.get("winddirAvg"),
        "airC": None if temp is None else round(tc(temp), 1), "pressureHpa": r1(pres, pk),
        "rainRateMmH": r1(rate, rk), "rainTodayMm": r1(tot, rk),
        "url": f"https://www.wunderground.com/dashboard/pws/{sid}", "via": "page",
    }


def pages(now, log):
    out = []
    for sid, name in PAGE_STATIONS:
        try: out.append(page_station(sid, name, now, log))
        except Exception as e: print(f"warning: WU page {sid}: {e}", file=sys.stderr)
    return out


def collect(now=None):
    """(observations dict or None, sources entry or None)."""
    now = now or dt.datetime.now(TZ)
    key = os.environ.get("WU_API_KEY", "").strip()
    st = wu(key, now) if key else []
    log = []
    if not st:
        st = pages(now, log)
        if st:
            return ({"fetched": now.replace(microsecond=0).isoformat(), "kind": "home", "blend": True, "stations": st, "fetchLog": log},
                    {"what": "Live wind & rain (home stations)", "name": "Weather Underground station pages: " + ", ".join(f"{x['name']} ({x['id']})" for x in st),
                     "url": st[0]["url"]})
    if st:
        kind = "home"
        src = {"what": "Live wind & rain (home stations)", "name": f"Weather Underground PWS, {len(st)} stations", "url": "https://www.wunderground.com/wundermap"}
    else:
        st = metar(now); kind = "airport"
        src = {"what": "Live wind (airport, shown only)", "name": "aviationweather.gov METAR", "url": "https://aviationweather.gov/"}
    if not st: return None, None
    return {"fetched": now.replace(microsecond=0).isoformat(), "kind": kind, "blend": kind == "home", "stations": st, "fetchLog": log}, src


DIRS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def live_line(obs):
    if not obs: return "Live: no station readings right now."
    def one(s):
        t = dt.datetime.fromisoformat(s["time"]); h = t.hour % 12 or 12
        d = DIRS[round(s["windDirDeg"] / 22.5) % 16] + " " if s.get("windDirDeg") is not None and s["windKn"] >= 1 else ""
        g = f" gust {round(s['gustKn'])}" if s.get("gustKn") else ""
        tc = f", {round(s['airC'])}°C" if s.get("airC") is not None else ""
        r = f", rain {s['rainRateMmH']} mm/h" if s.get("rainRateMmH") else (", raining" if s.get("raining") else "")
        return f"{s['name']} ({s['id']}) {('calm' if s['windKn'] < 1 else d + str(round(s['windKn'])) + ' kn')}{g}{tc}{r} (at {h}:{t.minute:02d}{'pm' if t.hour >= 12 else 'am'})"
    if obs["kind"] == "home" and len(obs["stations"]) == 1:
        return "Live: " + one(obs["stations"][0]).replace(" (", " home station (", 1)
    lead = "Live home stations" if obs["kind"] == "home" else "Live (airport, 50+ km away; the Algies/Snells station pages did not load this run)"
    return lead + ": " + "; ".join(one(s) for s in obs["stations"][:3])
