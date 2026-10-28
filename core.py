"""HeatShield core logic: weather fetch, ward data, hazard/vulnerability/priority scoring.
NOTE: Everything here is a transparent RULE-BASED heuristic. There is NO machine learning,
and nothing is clinically validated."""
import json, os
from datetime import datetime
import numpy as np
import pandas as pd
import requests

CITY_NAME, CITY_LAT, CITY_LON = "Bengaluru", 12.9716, 77.5946
API_URL = "https://api.open-meteo.com/v1/forecast"
HERE = os.path.dirname(__file__)
GEOJSON_PATH = os.path.join(HERE, "data", "wards.geojson")        # optional real boundaries
VULN_CSV_PATH = os.path.join(HERE, "data", "vulnerability.csv")   # optional real indicators

# ---------------- Weather ----------------
def fetch_weather():
    """Live call to Open-Meteo. Raises on failure (caller handles)."""
    params = dict(latitude=CITY_LAT, longitude=CITY_LON,
                  current="temperature_2m,relative_humidity_2m,apparent_temperature,precipitation",
                  hourly="temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,precipitation_probability",
                  forecast_days=2, timezone="auto")
    r = requests.get(API_URL, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    hourly = pd.DataFrame(j["hourly"])
    hourly["time"] = pd.to_datetime(hourly["time"])
    return dict(current=j["current"], hourly=hourly, fetched_at=datetime.now(), live=True)

def sample_weather():
    """OFFLINE SAMPLE (not real observations) so the app still runs without the API."""
    t = pd.date_range(datetime.now().replace(minute=0, second=0, microsecond=0), periods=48, freq="h")
    temp = 31 + 5 * np.sin((t.hour - 9) / 24 * 2 * np.pi)
    hourly = pd.DataFrame(dict(time=t, temperature_2m=temp, relative_humidity_2m=55.0,
                               apparent_temperature=temp + 2))
    cur = dict(time=str(t[0]), temperature_2m=float(temp[0]), relative_humidity_2m=55.0,
               apparent_temperature=float(temp[0] + 2))
    return dict(current=cur, hourly=hourly, fetched_at=datetime.now(), live=False)

# ---------------- Ward-wise rainfall & humidity (model grid cells, NOT ward measurements) ----------------
RAIN_BINS = [(0.5, "#f7fbff", "<0.5"), (2, "#c6dbef", "0.5–2"), (10, "#6baed6", "2–10"),
             (30, "#2171b5", "10–30"), (1e9, "#08306b", ">30")]          # mm in next 24h (display bins only)
HUM_BINS = [(40, "#fff7bc", "<40"), (55, "#d9f0a3", "40–55"), (70, "#78c679", "55–70"),
            (85, "#238443", "70–85"), (101, "#004529", ">85")]            # % relative humidity (display bins only)

def bin_color(v, bins):
    if v is None or pd.isna(v): return "#95a5a6"
    return next(col for lim, col, _ in bins if v < lim)

def next_24h(hourly, now_str):
    """Rows of an hourly frame from the current observation hour onward (24 rows)."""
    return hourly[hourly["time"] >= pd.to_datetime(now_str).floor("h")].head(24)

def ward_centroids(gj):
    """Bounding-box centre of each ward (rough)."""
    out = {}
    for ft in gj["features"]:
        pts, stack = [], [ft["geometry"]["coordinates"]]
        while stack:
            c = stack.pop()
            if isinstance(c[0], (int, float)): pts.append(c)
            else: stack.extend(c)
        lons, lats = [p[0] for p in pts], [p[1] for p in pts]
        out[ft["properties"]["ward_name"]] = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    return out

def fetch_ward_weather(centroids, cell=0.1, chunk_size=50):
    """Open-Meteo is a gridded model (~10 km class). Wards are snapped to 0.1-degree cells and ONE request
    covers all distinct cells, so wards in the same cell share a value. Raises on failure."""
    key = {n: (round(round(la / cell) * cell, 3), round(round(lo / cell) * cell, 3)) for n, (la, lo) in centroids.items()}
    cells = sorted(set(key.values()))
    res = {}
    for i in range(0, len(cells), chunk_size):
        chunk = cells[i:i + chunk_size]
        params = dict(latitude=",".join(str(c[0]) for c in chunk), longitude=",".join(str(c[1]) for c in chunk),
                      current="relative_humidity_2m,precipitation", hourly="precipitation",
                      forecast_days=2, timezone="auto")
        r = requests.get(API_URL, params=params, timeout=20)
        r.raise_for_status()
        j = r.json()
        items = j if isinstance(j, list) else [j]
        if len(items) != len(chunk):
            raise RuntimeError("Unexpected number of locations returned by the API")
        for cc, it in zip(chunk, items):
            h = pd.DataFrame(it["hourly"]); h["time"] = pd.to_datetime(h["time"])
            nxt = next_24h(h, it["current"]["time"])
            res[cc] = dict(humidity=it["current"]["relative_humidity_2m"], rain_now=it["current"]["precipitation"],
                           rain_24h=round(float(nxt.precipitation.sum()), 1))
    rows = [dict(ward_name=n, grid_lat=key[n][0], grid_lon=key[n][1], **res[key[n]]) for n in centroids]
    out = pd.DataFrame(rows)
    out.attrs["n_cells"] = len(cells)
    return out

# ---------------- Hazard (weather only) ----------------
def hazard_index(apparent_c):
    """0-100 heuristic: 27C apparent temp -> 0, 41C -> 100. Loosely inspired by common heat-index
    bands; thresholds are NOT validated. Tune them in README if your city/health dept uses others."""
    return float(np.clip((apparent_c - 27) / (41 - 27) * 100, 0, 100))

# ---------------- Wards ----------------
def _grid_wards(rows=4, cols=5, step=0.025):
    feats = []
    lat0 = CITY_LAT - rows * step / 2
    lon0 = CITY_LON - cols * step / 2
    k = 1
    for r in range(rows):
        for c in range(cols):
            la, lo = lat0 + r * step, lon0 + c * step
            ring = [[lo, la], [lo + step, la], [lo + step, la + step], [lo, la + step], [lo, la]]
            feats.append({"type": "Feature", "properties": {"ward_name": f"Zone-{k:02d}"},
                          "geometry": {"type": "Polygon", "coordinates": [ring]}})
            k += 1
    return {"type": "FeatureCollection", "features": feats}

def _illustrative_vuln(names):
    rng = np.random.default_rng(42)
    n = len(names)
    return pd.DataFrame(dict(
        ward_name=names,
        pct_65_plus=rng.uniform(5, 18, n).round(1),
        pop_density=rng.uniform(4000, 28000, n).round(-2),
        km_to_health_facility=rng.uniform(0.3, 4.5, n).round(1),
        cooling_access_score=rng.uniform(0.1, 0.9, n).round(2)))

IND = ["pct_65_plus", "pop_density", "km_to_health_facility", "cooling_access_score"]

def load_wards():
    """Returns (geojson, vuln_df, notes). Real files in data/ are used where present; every
    indicator that is NOT in the CSV is filled with ILLUSTRATIVE random values and flagged."""
    notes = []
    if os.path.exists(GEOJSON_PATH):
        with open(GEOJSON_PATH, encoding="utf-8") as f:
            gj = json.load(f)
        for i, ft in enumerate(gj["features"]):
            ft["properties"].setdefault("ward_name", f"Ward-{i+1}")
        notes.append("Ward boundaries: user-supplied data/wards.geojson")
    else:
        gj = _grid_wards()
        notes.append("Ward boundaries: ILLUSTRATIVE GRID (not real wards). Add data/wards.geojson for real ones.")
    names = [f["properties"]["ward_name"] for f in gj["features"]]
    v = _illustrative_vuln(names)
    real = []
    if os.path.exists(VULN_CSV_PATH):
        csv = pd.read_csv(VULN_CSV_PATH).drop_duplicates("ward_name").set_index("ward_name")
        for c in IND:
            if c in csv.columns:
                vals = v.ward_name.map(csv[c])
                if vals.notna().any():
                    v[c] = vals.fillna(v[c]); real.append(c)
    fake = [c for c in IND if c not in real]
    v["real_cols"] = ",".join(real)
    if not real:
        v["data_status"] = "ILLUSTRATIVE (simulated, not real demographics)"
        notes.append("Vulnerability indicators: ILLUSTRATIVE random values with fixed seed.")
    else:
        v["data_status"] = ("PARTLY REAL (" + ", ".join(real) + ") + ILLUSTRATIVE (" + ", ".join(fake) + ")") if fake else "USER-SUPPLIED"
        notes.append("Real indicators from data/vulnerability.csv: " + ", ".join(real)
                     + (". ILLUSTRATIVE random placeholders: " + ", ".join(fake) if fake else ""))
    return gj, v, notes

# ---------------- Vulnerability + priority ----------------
VULN_WEIGHTS = {"Older-adult share": 0.30, "Population density": 0.20,
                "Distance to health facility": 0.25, "Low cooling access": 0.25}

def vulnerability(df):
    comp = pd.DataFrame({
        "Older-adult share": (df.pct_65_plus / 20).clip(0, 1),
        "Population density": (df.pop_density / 30000).clip(0, 1),
        "Distance to health facility": (df.km_to_health_facility / 5).clip(0, 1),
        "Low cooling access": (1 - df.cooling_access_score).clip(0, 1)})
    score = sum(comp[k] * w for k, w in VULN_WEIGHTS.items()) * 100
    return score, comp

CATS = [(25, "Low", "#2ecc71"), (50, "Moderate", "#f1c40f"), (75, "High", "#e67e22"), (101, "Very High", "#c0392b")]
def category(p):
    if pd.isna(p): return "Incomplete", "#95a5a6"
    for lim, name, col in CATS:
        if p < lim: return name, col

def score_wards(vdf, apparent_c):
    df = vdf.copy()
    df["hazard"] = hazard_index(apparent_c)               # same city-wide: API gives ~11km grid
    df["vulnerability"], comp = vulnerability(df)
    df["priority"] = df.hazard * (0.4 + 0.6 * df.vulnerability / 100)  # hazard x vulnerability
    df[["category", "color"]] = df.priority.apply(lambda p: pd.Series(category(p)))
    df["top_factors"] = comp.apply(lambda r: ", ".join(r.sort_values(ascending=False).index[:2]), axis=1)
    return df.sort_values("priority", ascending=False).reset_index(drop=True), comp

def recommendations(row):
    recs = []
    if row.category in ("High", "Very High"):
        recs += ["Issue a targeted heat advisory (SMS / local loudspeaker / ward WhatsApp groups).",
                 "Set up temporary drinking-water points and shaded rest areas."]
    if row.category == "Very High":
        recs.append("Prioritise this ward for outreach teams this afternoon.")
    if "Older-adult" in row.top_factors:
        recs.append("Ask ASHA/community workers to check on older residents living alone.")
    if "cooling" in row.top_factors:
        recs.append("Open public cooling spaces (community halls, libraries) during peak hours.")
    if "health facility" in row.top_factors:
        recs.append("Alert the nearest clinic and pre-position ORS and first-aid supplies.")
    if not recs:
        recs.append("Routine monitoring; share general hydration advice.")
    return recs
