# Snells Beach · where to go today

Live: https://sjurgis.github.io/snells-beach/

A static page (no build step) that picks the best beach around Snells Beach / Mahurangi for today and the next
three days, from wind, swell, tide, rain and your activity (swim, surf, snorkel, SUP/kayak, hang out), how far you'll drive and
whether the dog is coming. Preferences are saved in the browser (and can be set by URL, e.g.
`?activity=hangout&drive=2&dog=1`). Testing only: `&at=20:30` pretends it is that time today.

| file | role | changes |
|---|---|---|
| `index.html`, `style.css`, `app.js` | template, scoring and rendering | rarely |
| `data/beaches.json` | standing beach guide: aspect, shelter, tide needs, drive time, dog rules with sources | rarely |
| `data/forecast.json` | today + 3 days, hourly 6am–8pm: wind (met.no + Open-Meteo blend), gusts, rain mm + chance, swell, tide, sun | **every morning** |
| `data/SCHEMA.md` | exact format of `forecast.json` | |
| `scripts/update_forecast.py` | fetches met.no, Open-Meteo (+ marine) and tides4fishing, writes `forecast.json` | |
| `scripts/validate.py` | checks `forecast.json` and `beaches.json`; non-zero exit on problems | |

Daily update:

```sh
python3 scripts/update_forecast.py      # writes data/forecast.json from live sources
python3 scripts/validate.py             # must print OK
git add data/forecast.json && git commit -m "Forecast for $(TZ=Pacific/Auckland date +'%A %-d %B')" && git push origin main
```

Run it in the morning (it can run any time; the page works out "right now" itself). Wind is a blend of two
models per hour, so one noisy light-air hour can't flip the direction; `models` keeps each source's raw value.
Do not invent figures. If a source is down, use another real one and name it in `sources`.
