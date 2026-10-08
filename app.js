/* Snells Beach daily pick. Template code: reads data/beaches.json + data/forecast.json, scores, renders.
   Nothing in here changes day to day. See data/SCHEMA.md. */
"use strict";

const TZ = "Pacific/Auckland";
const PREF_KEY = "snells-beach-prefs-v1";
const DEFAULT_PREFS = { activity: "swim", drive: 1, dog: false };
const ACT = {
  swim: { label: "Swim / family", short: "swim" },
  surf: { label: "Surf", short: "surf" },
  snorkel: { label: "Snorkel", short: "snorkel" },
  sup: { label: "SUP / kayak", short: "SUP" },
};
const DIR16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
const DIR8 = ["N","NE","E","SE","S","SW","W","NW"];

/* ---------- small helpers ---------- */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const norm = (d) => ((d % 360) + 360) % 360;
const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);
const dir16 = (d) => DIR16[Math.round(norm(d) / 22.5) % 16];
const dir8 = (d) => DIR8[Math.round(norm(d) / 45) % 8];
const hm = (s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };
const dayNum = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d) / 86400000; };
const icon = (id, cls = "ic") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${id}"/></svg>`;

function lerp(points, x) {
  if (x <= points[0][0]) return points[0][1];
  for (let i = 1; i < points.length; i++) {
    const [x1, y1] = points[i];
    if (x <= x1) { const [x0, y0] = points[i - 1]; return y0 + (y1 - y0) * (x - x0) / (x1 - x0); }
  }
  return points[points.length - 1][1];
}

function fmtTime(min) {
  min = ((Math.round(min) % 1440) + 1440) % 1440;
  const h = Math.floor(min / 60), m = min % 60;
  const ap = h >= 12 ? "pm" : "am", h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12}${ap}` : `${h12}:${String(m).padStart(2, "0")}${ap}`;
}
function fmtRange(a, b) {
  const A = fmtTime(a), B = fmtTime(b);
  const sameAp = A.slice(-2) === B.slice(-2);
  return `${sameAp ? A.slice(0, -2) : A}–${B}`;
}
function fmtDate(iso, opts) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString("en-NZ", { timeZone: "UTC", ...opts });
}
function nzNow() {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date()).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, min: (+p.hour % 24) * 60 + +p.minute };
}
const isWeekend = (iso) => { const w = new Date(dayNum(iso) * 86400000).getUTCDay(); return w === 0 || w === 6; };

/* ---------- prefs ---------- */
function loadPrefs() {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREF_KEY) || "{}") }; }
  catch { return { ...DEFAULT_PREFS }; }
}
function savePrefs(p) { try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch { /* private mode */ } }

/* ---------- data ---------- */
async function getJSON(path) {
  const v = new Date().toISOString().slice(0, 13).replace(/\D/g, "");   // changes hourly: busts caches
  const r = await fetch(`${path}?v=${v}`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path} returned HTTP ${r.status}`);
  return r.json();
}

/* ---------- tides ---------- */
function buildTides(days) {
  const base = dayNum(days[0].date);
  const list = [];
  for (const d of days) for (const t of d.tides || []) {
    list.push({ t: (dayNum(d.date) - base) * 1440 + hm(t.time), type: t.type, h: t.heightM });
  }
  list.sort((a, b) => a.t - b.t);
  return { base, list };
}
const absMin = (tides, iso, min) => (dayNum(iso) - tides.base) * 1440 + min;
function tideHeight(tides, t) {
  const L = tides.list;
  if (!L.length) return null;
  let i = L.findIndex((x) => x.t >= t);
  if (i === -1) { const a = L[L.length - 1]; return a.h + ((a.type === "high" ? -1 : 1) * 2.1) * (1 - Math.cos(Math.PI * clamp((t - a.t) / 372, 0, 1))) / 2; }
  if (i === 0) { const b = L[0]; return b.h + ((b.type === "high" ? -1 : 1) * 2.1) * (1 - Math.cos(Math.PI * clamp((b.t - t) / 372, 0, 1))) / 2; }
  const a = L[i - 1], b = L[i];
  return a.h + (b.h - a.h) * (1 - Math.cos(Math.PI * (t - a.t) / (b.t - a.t))) / 2;
}
function nearestHigh(tides, t) {
  let best = null;
  for (const x of tides.list) if (x.type === "high" && (!best || Math.abs(x.t - t) < Math.abs(best.t - t))) best = x;
  return best;
}

/* ---------- scoring ---------- */
const EFF = { onshore: 1, "cross-on": 0.8, "cross-off": 0.55, offshore: 0.45, sheltered: 0.3 };
function windRel(b, dirDeg) {
  if ((b.shelteredFrom || []).includes(dir8(dirDeg))) return "sheltered";
  const d = angDiff(dirDeg, b.facingDeg);
  return d <= 50 ? "onshore" : d <= 90 ? "cross-on" : d <= 130 ? "cross-off" : "offshore";
}
function nearestSwell(day, min) {
  let best = null;
  for (const s of day.swell || []) if (!best || Math.abs(hm(s.time) - min) < Math.abs(hm(best.time) - min)) best = s;
  return best;
}
function dogRule(b, iso) {
  const md = iso.slice(5);
  for (const r of b.dog?.rules || []) {
    if (!r.from) return r;
    const inR = r.from <= r.to ? md >= r.from && md <= r.to : md >= r.from || md <= r.to;
    if (inR) return r;
  }
  return { status: "unknown", chip: "Unverified: check signs", text: "Unverified: check signs" };
}

function evalSlot(b, day, slot, act, tides) {
  const t = hm(slot.time);
  const kn = slot.windKn, gust = slot.gustKn ?? kn, dir = slot.windDirDeg;
  const rel = windRel(b, dir);
  const sw = nearestSwell(day, t);
  const open = sw?.open || {}, inner = sw?.inner || {};
  const fac = b.exposure?.factor ?? 0.5;
  const water = (b.exposure?.source === "open" ? (open.waveM ?? open.swellM ?? 0) : (inner.waveM ?? 0)) * fac;
  const surfH = (open.swellM ?? 0) * (b.exposure?.source === "open" ? fac : fac * 0.5);
  const period = open.periodS ?? 0;
  const tAbs = absMin(tides, day.date, t);
  const hi = nearestHigh(tides, tAbs);
  const hrsFromHigh = hi ? Math.abs(tAbs - hi.t) / 60 : 0;
  const tideMode = b.tide?.mode || "all";
  const W = b.tide?.hours ?? 2;
  const tideQ = tideMode === "high" ? lerp([[0, 1], [W, 1], [W + 1.5, 0.35], [W + 3, 0.1]], hrsFromHigh) : 1;
  const rain = slot.rainMm ?? 0;
  const weatherQ = Math.min(lerp([[0, 1], [0.2, 0.95], [1, 0.75], [3, 0.5]], rain), slot.sky === "storm" ? 0.4 : (slot.sky === "rain" || slot.sky === "showers") ? (rain >= 0.3 ? 0.8 : 0.93) : 1);
  const effWind = (kn * 0.75 + gust * 0.25) * EFF[rel];
  const suit = b.suits?.[act] ?? 0;
  let score, windQ, waterQ, extra = [];

  if (act === "surf") {
    const shelteredLike = rel === "offshore" || rel === "sheltered";
    windQ = shelteredLike ? lerp([[0, 1], [15, 1], [22, 0.7], [30, 0.4]], kn)
      : rel === "cross-off" ? lerp([[0, 0.95], [8, 0.8], [15, 0.55], [25, 0.3]], kn)
      : rel === "cross-on" ? lerp([[0, 0.85], [6, 0.6], [12, 0.35], [20, 0.15]], kn)
      : lerp([[0, 0.8], [5, 0.5], [10, 0.25], [18, 0.1]], kn);
    const dirQ = open.dirDeg == null ? 0.8 : lerp([[0, 1], [45, 1], [90, 0.7], [135, 0.3]], angDiff(open.dirDeg, b.facingDeg));
    waterQ = lerp([[0, 0], [0.3, 0.03], [0.5, 0.15], [0.8, 0.45], [1.0, 0.75], [1.3, 0.95], [2.0, 1], [2.8, 0.8], [3.5, 0.5]], surfH)
      * lerp([[4, 0.5], [6, 0.7], [8, 0.9], [10, 1.05], [13, 1.1]], period) * dirQ;
    score = 100 * suit * Math.min(1, waterQ) * (0.35 + 0.65 * windQ) * Math.sqrt(weatherQ);
  } else if (act === "snorkel") {
    windQ = lerp([[0, 1], [5, 1], [9, 0.7], [13, 0.4], [18, 0.15], [25, 0]], effWind);
    waterQ = lerp([[0, 1], [0.15, 1], [0.3, 0.75], [0.5, 0.4], [0.8, 0.15], [1.2, 0]], water);
    const tq = tideMode === "high" ? 0.5 + 0.5 * tideQ : 1;
    score = 100 * suit * tq * (0.4 * windQ + 0.6 * waterQ) * weatherQ;
  } else if (act === "sup") {
    windQ = lerp([[0, 1], [4, 1], [7, 0.7], [10, 0.4], [14, 0.15], [20, 0]], effWind);
    waterQ = lerp([[0, 1], [0.15, 1], [0.3, 0.65], [0.5, 0.3], [0.8, 0.08]], water);
    const tq = tideMode === "high" ? 0.3 + 0.7 * tideQ : 1;
    score = 100 * suit * tq * (0.6 * windQ + 0.4 * waterQ) * weatherQ;
    if ((rel === "offshore" || rel === "cross-off") && kn > 12) { score *= 0.6; extra.push({ k: "bad", t: `Offshore ${Math.round(kn)} kn: could blow you out` }); }
  } else { // swim
    windQ = lerp([[0, 1], [6, 1], [10, 0.8], [15, 0.5], [20, 0.25], [28, 0.05]], effWind);
    waterQ = lerp([[0, 1], [0.3, 1], [0.5, 0.8], [0.8, 0.45], [1.2, 0.2], [2, 0.05]], water);
    score = 100 * suit * tideQ * (0.55 * windQ + 0.45 * waterQ) * weatherQ;
  }

  // DOC guidance for Goat Island: skip in E/NE wind over ~20 kn or E/NE swell over 1 m
  let docOff = null;
  if (b.doc) {
    const inDir = (d) => d != null && norm(d) >= b.doc.dirFromDeg && norm(d) <= b.doc.dirToDeg;
    if (inDir(dir) && kn > b.doc.maxWindKn) docOff = `${dir16(dir)} ${Math.round(kn)} kn`;
    else if (inDir(open.dirDeg) && (open.swellM ?? 0) > b.doc.maxSwellM) docOff = `${dir16(open.dirDeg)} swell ${open.swellM.toFixed(1)} m`;
    if (docOff) score = Math.min(score, 8);
  }

  return { t, score: clamp(score, 0, 100), kn, gust, dir, rel, water, surfH, period, open, tideQ, tideMode, W, hi, hrsFromHigh, rain, sky: slot.sky, docOff, extra, windQ, waterQ };
}

function rating(score) {
  if (score >= 72) return { key: "great", label: "Great" };
  if (score >= 50) return { key: "good", label: "Good" };
  if (score >= 30) return { key: "meh", label: "Meh" };
  return { key: "nope", label: "Nope" };
}

function evalBeachDay(b, day, act, tides, ctx) {
  const sr = hm(day.sunrise || "06:30"), ss = hm(day.sunset || "19:30");
  let slots = (day.slots || []).filter((s) => { const t = hm(s.time); return t >= sr - 30 && t <= ss + 15; });
  let done = false;
  if (ctx.isToday) {
    const future = slots.filter((s) => hm(s.time) >= ctx.nowMin - 60);
    if (future.length) slots = future; else done = true;
  }
  const evals = slots.map((s) => evalSlot(b, day, s, act, tides));
  if (!evals.length) return null;
  let bi = 0;
  evals.forEach((e, i) => { if (e.score > evals[bi].score) bi = i; });
  const best = evals[bi];
  const ok = (e) => e.score >= best.score - 12 && e.score >= best.score * 0.8;
  let lo = bi, hi = bi;
  while (lo > 0 && ok(evals[lo - 1])) lo--;
  while (hi < evals.length - 1 && ok(evals[hi + 1])) hi++;
  let start = Math.max(evals[lo].t - 60, sr), end = Math.min(evals[hi].t + 60, ss);
  if (best.tideMode === "high" && act !== "surf" && best.hi) {
    const hiLocal = best.hi.t - (dayNum(day.date) - tides.base) * 1440;
    const s2 = Math.max(start, hiLocal - best.W * 60), e2 = Math.min(end, hiLocal + best.W * 60);
    if (e2 - s2 >= 45) { start = s2; end = e2; }
  }
  let nowStart = false;
  if (ctx.isToday && !done && start <= ctx.nowMin) { start = ctx.nowMin; nowStart = true; }
  if (end - start < 30 && !done) end = Math.min(start + 60, ss + 30);

  let score = best.score;
  const traffic = b.viaMatakana && (ctx.weekend || !!day.traffic);
  if (traffic) score *= 0.93;
  const dog = dogRule(b, day.date);
  const filters = [];
  if (b.driveMin > ctx.maxDrive) filters.push(`Too far · ${b.driveMin} min`);
  if (ctx.dog && dog.status === "banned") filters.push("Dogs banned");
  const window = done ? "Earlier today" : nowStart ? `Now–${fmtTime(end)}` : fmtRange(start, end);
  return { b, best, score: Math.round(score), rating: rating(score), window, start, end, done, traffic, dog, filters, eligible: !filters.length };
}

/* ---------- reasons + chips ---------- */
function reasons(r, act, day) {
  const e = r.best, out = [];
  const W = `${dir16(e.dir)} ${Math.round(e.kn)} kn`;
  if (e.docOff) out.push({ k: "bad", t: `DOC: skip Goat Island (${e.docOff})` });
  if (e.rel === "sheltered") out.push({ k: "good", t: `Sheltered from ${dir16(e.dir)} ${Math.round(e.kn)} kn` });
  else if (e.rel === "offshore") out.push({ k: act === "surf" || e.kn <= 15 ? "good" : "mid", t: `Offshore ${W}${act === "surf" ? ": clean" : ""}` });
  else if (e.kn < 6) out.push({ k: "good", t: `Light wind, ${W}` });
  else if (e.rel === "onshore") out.push({ k: e.kn >= 10 || act === "surf" ? "bad" : "mid", t: `Onshore ${W}${e.kn >= 10 ? ": choppy" : ""}` });
  else out.push({ k: e.kn >= 14 ? "bad" : "mid", t: `Cross-shore ${W}` });

  if (act === "surf") {
    const h = e.surfH;
    if (h < 0.6) out.push({ k: "bad", t: `Swell ${h.toFixed(1)} m · ${Math.round(e.period)} s: too small` });
    else if (h < 0.8) out.push({ k: "mid", t: `Swell ${h.toFixed(1)} m · ${Math.round(e.period)} s: small` });
    else out.push({ k: "good", t: `Swell ${h.toFixed(1)} m · ${Math.round(e.period)} s` });
  } else {
    const h = e.water;
    const flatT = act === "swim" ? 0.3 : 0.2;
    if (h < flatT) out.push({ k: "good", t: "Flat water" });
    else if (h < 0.5) out.push({ k: act === "swim" ? "good" : "mid", t: `Small waves ~${h.toFixed(1)} m` });
    else out.push({ k: "bad", t: `Waves ~${h.toFixed(1)} m: lumpy` });
  }

  if (act !== "surf") {
    if (e.tideMode === "high" && e.hi) {
      const hiT = fmtTime(e.hi.t - (dayNum(day.date) - r._tidesBase) * 1440);
      if (e.tideQ >= 0.9) out.push({ k: "good", t: `High tide ${hiT}` });
      else out.push({ k: "bad", t: `Tide's out: best near ${hiT} high` });
    } else out.push({ k: "good", t: "Any tide" });
  }
  for (const x of e.extra) out.push(x);
  if (e.rain >= 0.5 || e.sky === "rain" || e.sky === "showers") out.push({ k: "mid", t: e.sky === "showers" ? "Showers around" : "Rain likely" });
  if (r.traffic) out.push({ k: "mid", t: "Weekend: Matakana queues" });
  if (r.b.doc && !e.docOff && act === "snorkel") out.push({ k: "good", t: "Within DOC limits" });
  return out.slice(0, 4);
}
function relClass(e, act) {
  if (e.rel === "sheltered" || e.kn < 6) return "good";
  if (e.rel === "offshore") return act === "surf" || e.kn <= 15 ? "good" : "mid";
  if (e.rel === "onshore") return e.kn >= 10 || act === "surf" ? "bad" : "mid";
  return e.kn >= 14 ? "bad" : "mid";
}
function chips(r, act, prefs, day, { compact = false } = {}) {
  const e = r.best, c = [];
  c.push(`<span class="chip c-${relClass(e, act)}" title="Wind ${esc(e.rel)}">${icon("arrow", `ic arrow" style="transform:rotate(${Math.round(e.dir + 180)}deg)`)}${dir16(e.dir)} ${Math.round(e.kn)}<small>kn</small></span>`);
  if (act === "surf") c.push(`<span class="chip c-${e.surfH >= 0.8 ? "good" : e.surfH >= 0.6 ? "mid" : "bad"}">${icon("wave")}${e.surfH.toFixed(1)}<small>m</small> · ${Math.round(e.period)}<small>s</small></span>`);
  else c.push(`<span class="chip c-${e.water < 0.3 ? "good" : e.water < 0.5 ? "mid" : "bad"}">${icon("wave")}${e.water < 0.2 ? "Flat" : e.water.toFixed(1) + "<small>m</small>"}</span>`);
  if (act !== "surf") {
    if (e.tideMode === "high" && e.hi) c.push(`<span class="chip c-${e.tideQ >= 0.9 ? "good" : "bad"}">${icon("tide")}High ${fmtTime(e.hi.t - (dayNum(day.date) - r._tidesBase) * 1440)}</span>`);
    else if (!compact) c.push(`<span class="chip c-good">${icon("tide")}Any tide</span>`);
  }
  if (prefs.dog) {
    const s = r.dog.status, cls = s === "offlead" ? "good" : s === "banned" ? "bad" : "mid";
    c.push(`<span class="chip c-${cls}" title="${esc(r.dog.text)}">${icon("dog")}${esc(r.dog.chip)}</span>`);
  }
  if (!compact || r.b.driveMin > 15) c.push(`<span class="chip c-plain">${icon("car")}${r.b.driveMin}<small>min</small></span>`);
  if (r.traffic) c.push(`<span class="chip c-mid" title="${esc(day.traffic?.note || "Weekend traffic through Matakana")}">${icon("traffic")}Matakana</span>`);
  return `<div class="chips">${c.join("")}</div>`;
}
const bullets = (list) => `<ul class="reasons">${list.map((x) => `<li class="r-${x.k}">${icon(x.k === "good" ? "check" : x.k === "bad" ? "x" : "dot")}<span>${esc(x.t)}</span></li>`).join("")}</ul>`;
const pill = (r) => `<span class="pill p-${r.rating.key}">${r.rating.label}</span>`;
function ring(score, key) {
  const C = 2 * Math.PI * 26, f = clamp(score, 0, 100) / 100;
  return `<svg class="ring k-${key}" viewBox="0 0 64 64" role="img" aria-label="Score ${score} out of 100"><circle cx="32" cy="32" r="26" class="ring-bg"/><circle cx="32" cy="32" r="26" class="ring-fg" stroke-dasharray="${(C * f).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 32 32)"/><text x="32" y="37" text-anchor="middle">${score}</text></svg>`;
}
const skyIcon = (s) => icon(s === "sun" ? "sun" : s === "partly" ? "partly" : s === "rain" || s === "showers" || s === "storm" ? "rain" : "cloud", `ic sky sky-${s || "cloud"}`);

/* ---------- today's strip: hourly wind + tide curve ---------- */
function todayStrip(day, tides, ctx) {
  const x0 = 6 * 60, x1 = 20 * 60, Wd = 700, H = 92;
  const X = (m) => ((m - x0) / (x1 - x0)) * Wd;
  const slots = (day.slots || []).filter((s) => hm(s.time) > x0 && hm(s.time) < x1);
  const pts = [];
  for (let m = x0; m <= x1; m += 10) pts.push([X(m), tideHeight(tides, absMin(tides, day.date, m))]);
  let svg = "";
  if (pts.every((p) => p[1] != null)) {
    const hs = pts.map((p) => p[1]), hmin = Math.min(...hs, 0.3), hmax = Math.max(...hs, 3);
    const Y = (h) => H - 14 - ((h - hmin) / (hmax - hmin)) * (H - 34);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    const sr = hm(day.sunrise || "06:30"), ss = hm(day.sunset || "19:30");
    let marks = "";
    for (const t of day.tides || []) {
      const m = hm(t.time); if (m < x0 || m > x1) continue;
      const y = Y(t.heightM), lx = clamp(X(m) / Wd * 100, 7, 93);
      marks += `<i class="tdot ${t.type}" style="left:${(X(m) / Wd * 100).toFixed(2)}%;top:${(y / H * 100).toFixed(2)}%"></i><span class="tlbl ${t.type}" style="left:${lx.toFixed(2)}%;top:${(y / H * 100).toFixed(2)}%">${t.type === "high" ? "High" : "Low"} ${fmtTime(m)}</span>`;
    }
    const night = `<rect x="0" y="0" width="${Math.max(0, X(sr)).toFixed(1)}" height="${H}" class="night"/><rect x="${Math.min(Wd, X(ss)).toFixed(1)}" y="0" width="${Math.max(0, Wd - X(ss)).toFixed(1)}" height="${H}" class="night"/>`;
    const showNow = ctx.isToday && ctx.nowMin > x0 && ctx.nowMin < x1;
    const now = showNow ? `<line x1="${X(ctx.nowMin).toFixed(1)}" x2="${X(ctx.nowMin).toFixed(1)}" y1="2" y2="${H}" class="nowline"/>` : "";
    const nowLbl = showNow ? `<span class="nowlbl" style="left:${(X(ctx.nowMin) / Wd * 100).toFixed(2)}%">now</span>` : "";
    svg = `<svg class="tidecurve" viewBox="0 0 ${Wd} ${H}" preserveAspectRatio="none" role="img" aria-label="Tide curve for today">${night}<path d="${line}L${Wd},${H}L0,${H}Z" class="tfill"/><path d="${line}" class="tline"/>${now}</svg><div class="tidelabels" aria-hidden="true">${marks}${nowLbl}</div>`;
  }
  const cols = slots.map((s) => {
    const past = ctx.isToday && hm(s.time) < ctx.nowMin - 60;
    return `<div class="hr${past ? " past" : ""}" style="left:${(X(hm(s.time)) / Wd * 100).toFixed(2)}%"><span class="t">${fmtTime(hm(s.time))}</span>${skyIcon(s.sky)}${icon("arrow", `ic arrow" style="transform:rotate(${Math.round(s.windDirDeg + 180)}deg)`)}<b>${Math.round(s.windKn)}</b><span class="d">${dir16(s.windDirDeg)}</span></div>`;
  }).join("");
  return `<section class="card strip" aria-label="Today hour by hour"><div class="hours">${cols}</div><div class="tidewrap">${svg}</div><p class="legend"><span>${icon("tide")}Tide · Mahurangi Harbour</span><span>wind kn</span></p></section>`;
}

/* ---------- render ---------- */
let STATE = null;

function render() {
  const { beaches, fc, prefs } = STATE;
  const now = nzNow();
  const app = $("#app");
  const stops = beaches.drive?.stops || [{ label: "Local", maxMin: 15 }, { label: "Nearby", maxMin: 35 }, { label: "Road trip", maxMin: 999 }];
  const stop = stops[clamp(prefs.drive, 0, stops.length - 1)];
  $("#driveLabel").textContent = stop.maxMin >= 999 ? `${stop.label} · any distance` : `${stop.label} · ≤${stop.maxMin} min`;

  const tides = buildTides(fc.days);
  let days = fc.days.filter((d) => d.date >= now.date);
  const stale = !days.length;
  if (stale) days = fc.days.slice(-1);
  const updated = new Date(fc.updated);
  const ageH = (Date.now() - updated.getTime()) / 3.6e6;

  const results = days.slice(0, 4).map((day) => {
    const ctx = { isToday: day.date === now.date, nowMin: now.min, weekend: isWeekend(day.date), maxDrive: stop.maxMin, dog: prefs.dog };
    const rs = beaches.beaches.map((b) => evalBeachDay(b, day, prefs.activity, tides, ctx)).filter(Boolean);
    rs.forEach((r) => (r._tidesBase = tides.base));
    rs.sort((a, b) => (b.eligible - a.eligible) || (b.score - a.score) || ((b.end - b.start) - (a.end - a.start)) || (a.b.driveMin - b.b.driveMin));
    return { day, ctx, rs };
  });

  const today = results[0];
  const dLabel = (d, ctx) => ctx.isToday ? "Today" : (dayNum(d.date) - dayNum(now.date) === 1 ? "Tomorrow" : fmtDate(d.date, { weekday: "long" }));
  $("#title").textContent = today.ctx.isToday ? `Where to ${ACT[prefs.activity].short} today` : `Where to ${ACT[prefs.activity].short} · ${fmtDate(today.day.date, { weekday: "long" })}`;
  $("#subtitle").innerHTML = `${esc(fmtDate(today.day.date, { weekday: "short", day: "numeric", month: "short" }))}${today.day.airMaxC != null ? ` · ${icon("temp")}${Math.round(today.day.airMaxC)}° air` : ""}${today.day.waterTempC != null ? ` · ${icon("wave")}${Math.round(today.day.waterTempC)}° water` : ""} · ${icon("sun")}${fmtTime(hm(today.day.sunrise))}–${fmtTime(hm(today.day.sunset))}`;

  let html = "";
  if (stale || ageH > 30) {
    html += `<div class="notice warn">${icon("clock")}<span>This forecast is from <b>${esc(updated.toLocaleString("en-NZ", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }))}</b>. The morning update hasn't run yet, so treat it as a rough guide.</span></div>`;
  }

  const elig = today.rs.filter((r) => r.eligible);
  if (prefs.activity === "snorkel") {
    const goat = today.rs.find((r) => r.b.doc);
    if (goat?.best.docOff) html += `<div class="notice bad">${icon("x")}<span><b>Goat Island is off today</b>: ${esc(goat.best.docOff)}. DOC says skip it in E/NE wind over ~20 kn or E/NE swell over 1 m.</span></div>`;
    else if (goat && !goat.eligible) html += `<div class="notice">${icon("dot")}<span>Goat Island is the snorkel spot, but it's hidden: ${esc(goat.filters.join(", ").toLowerCase())}.</span></div>`;
  }

  if (!elig.length) {
    html += `<section class="hero r-nope"><h2>Nothing fits</h2><p class="when">Every beach is filtered out by your settings. Try a longer drive${prefs.dog ? " or leave the dog home" : ""}.</p></section>`;
  } else {
    const top = elig[0];
    const lowNote = top.score < 30 ? `<p class="lownote">Nothing's really on for ${esc(ACT[prefs.activity].label.toLowerCase())}. This is the least-bad option.</p>` : "";
    html += `<div class="topgrid"><section class="hero r-${top.rating.key}" aria-label="Top pick">
      <div class="hero-head"><div><span class="badge">${today.ctx.isToday ? "Today's pick" : esc(dLabel(today.day, today.ctx)) + "'s pick"}</span>${pill(top)}</div>${ring(top.score, top.rating.key)}</div>
      <h2>${esc(top.b.name)}</h2>
      <p class="when">${icon("clock")}<span>${top.done ? "" : "Best "}<b>${esc(top.window)}</b></span></p>
      ${chips(top, prefs.activity, prefs, today.day)}
      ${bullets(reasons(top, prefs.activity, today.day))}
      ${lowNote}
    </section>`;
    const ru = elig.slice(1, 3);
    html += `<div class="side">`;
    if (ru.length) {
      html += `<h3 class="sec">${ru.every((r) => r.score >= 50) ? (today.ctx.isToday ? "Also good today" : "Also good") : "Next best"}</h3><div class="runners">${ru.map((r) => `
        <article class="card runner r-${r.rating.key}">
          <div class="rhead"><h4>${esc(r.b.name)}</h4>${pill(r)}</div>
          <p class="when sm">${icon("clock")}<b>${esc(r.window)}</b></p>
          ${chips(r, prefs.activity, prefs, today.day, { compact: true })}
          ${bullets(reasons(r, prefs.activity, today.day).slice(0, 2))}
        </article>`).join("")}</div>`;
    }
    html += `</div></div>`;
  }

  if (today.ctx.isToday || stale) html += `<h3 class="sec">${stale ? "Last forecast day" : "Today"} at a glance</h3>` + todayStrip(today.day, tides, today.ctx);

  const ahead = results.slice(1, 4);
  if (ahead.length) {
    html += `<h3 class="sec">Next days</h3><div class="days">${ahead.map(({ day, ctx, rs }) => {
      const top = rs.find((r) => r.eligible);
      const slot = (day.slots || []).reduce((a, s) => (a && Math.abs(hm(a.time) - 13 * 60) < Math.abs(hm(s.time) - 13 * 60) ? a : s), null);
      const wk = ctx.weekend ? `<span class="tag">Weekend</span>` : "";
      if (!top) return `<article class="card day"><div class="dhead"><h4>${esc(dLabel(day, ctx))}</h4>${wk}</div><p class="muted">Nothing fits your filters.</p></article>`;
      return `<article class="card day r-${top.rating.key}">
        <div class="dhead"><div><h4>${esc(dLabel(day, ctx))}</h4><span class="muted">${esc(fmtDate(day.date, { day: "numeric", month: "short" }))}</span></div>${wk}<span class="wx">${slot ? skyIcon(slot.sky) : ""}${day.airMaxC != null ? Math.round(day.airMaxC) + "°" : ""}</span></div>
        <div class="dpick"><span class="dname">${esc(top.b.name)}</span>${pill(top)}</div>
        <p class="when sm">${icon("clock")}<b>${esc(top.window)}</b></p>
        ${chips(top, prefs.activity, prefs, day, { compact: true })}
        ${bullets(reasons(top, prefs.activity, day).slice(0, 2))}
      </article>`;
    }).join("")}</div>`;
  }

  html += `<h3 class="sec">All beaches · ${today.ctx.isToday ? "today" : esc(fmtDate(today.day.date, { weekday: "short" }))}</h3><div class="list">${today.rs.map((r) => {
    const dogLine = r.dog ? `<p class="dogrule">${icon("dog")}<span>${esc(r.dog.text)}${r.b.dog?.source ? ` · <a href="${esc(r.b.dog.source)}" rel="noopener">source</a>` : ""}${r.b.dog?.verified === false ? " · <b>unverified, check signs</b>" : ""}</span></p>` : "";
    return `<details class="row ${r.eligible ? "r-" + r.rating.key : "off"}">
      <summary>
        <span class="rname"><b>${esc(r.b.name)}</b><small>${esc(r.b.area)} · ${r.b.driveMin} min</small></span>
        ${r.eligible ? `<span class="bar"><i style="width:${r.score}%"></i></span><span class="rs">${r.score}</span>${pill(r)}` : `<span class="why">${esc(r.filters.join(" · "))}</span>`}
      </summary>
      <div class="rbody">
        <p class="when sm">${icon("clock")}<b>${esc(r.window)}</b></p>
        ${chips(r, prefs.activity, { ...prefs, dog: true }, today.day)}
        ${bullets(reasons(r, prefs.activity, today.day))}
        <ul class="notes">${(r.b.notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
        ${dogLine}
      </div>
    </details>`;
  }).join("")}</div>`;

  app.innerHTML = html;

  const src = (fc.sources || []).map((s) => `<li><b>${esc(s.what)}</b>: ${s.url ? `<a href="${esc(s.url)}" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}</li>`).join("");
  $("#foot").innerHTML = `
    <p class="upd">${icon("clock")}Updated ${esc(updated.toLocaleString("en-NZ", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }))} NZT</p>
    <ul class="srcs">${src}
      <li><b>Drive times</b>: ${esc(beaches.drive?.source || "")}, from ${esc(beaches.origin?.name || "Snells Beach")}</li>
      <li><b>Dog rules</b>: Auckland Council park pages and DOC, checked ${esc(beaches.beaches[0]?.dog?.checked || "")}. Tap a beach for its rule and link.</li>
    </ul>
    <p class="muted">Scores are a rough guide from the forecast. Check <a href="https://safeswim.org.nz/" rel="noopener">Safeswim</a> for water quality and lifeguards, and the signs at the beach.</p>`;
}

function showError(err) {
  $("#app").innerHTML = `<section class="card errorcard"><h2>Can't load today's forecast</h2><p>${esc(err?.message || err)}</p><p class="muted">It's usually a blip with the connection. Try again in a moment.</p><button type="button" id="retry">Try again</button></section>`;
  $("#subtitle").textContent = "Forecast unavailable";
  $("#retry")?.addEventListener("click", () => location.reload());
}

function wirePrefs() {
  const prefs = STATE.prefs;
  for (const el of document.querySelectorAll('input[name="activity"]')) {
    el.checked = el.value === prefs.activity;
    el.addEventListener("change", () => { prefs.activity = el.value; savePrefs(prefs); render(); });
  }
  const drive = $("#drive"); drive.value = prefs.drive;
  drive.addEventListener("input", () => { prefs.drive = +drive.value; savePrefs(prefs); render(); });
  const dog = $("#dog"); dog.checked = !!prefs.dog;
  dog.addEventListener("change", () => { prefs.dog = dog.checked; savePrefs(prefs); render(); });
}

async function main() {
  const prefs = loadPrefs();
  // URL overrides, handy for sharing: ?activity=surf&drive=2&dog=1
  const q = new URLSearchParams(location.search);
  if (q.has("activity")) prefs.activity = q.get("activity");
  if (q.has("drive")) prefs.drive = clamp(parseInt(q.get("drive"), 10) || 0, 0, 2);
  if (q.has("dog")) prefs.dog = q.get("dog") === "1" || q.get("dog") === "true";
  if (!ACT[prefs.activity]) prefs.activity = DEFAULT_PREFS.activity;
  if (q.has("activity") || q.has("drive") || q.has("dog")) savePrefs(prefs);
  STATE = { prefs };
  wirePrefs();
  try {
    const [beaches, fc] = await Promise.all([getJSON("data/beaches.json"), getJSON("data/forecast.json")]);
    if (!fc?.days?.length) throw new Error("forecast.json has no days in it");
    Object.assign(STATE, { beaches, fc });
    render();
    setInterval(render, 10 * 60 * 1000);   // keep "now" and today's windows fresh if left open
  } catch (err) {
    console.error(err);
    showError(err);
  }
}

if (typeof document !== "undefined") main();
