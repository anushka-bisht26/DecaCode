import random, folium, pandas as pd, streamlit as st
from streamlit_folium import st_folium
import core

st.set_page_config(page_title="JanSafe", page_icon="🛡️", layout="wide")
st.title("🛡️ JanSafe")
st.markdown("**Know before you go.** Heat, rain and travel conditions across Bengaluru, ward by ward.")

# ---------- weather (live, with graceful fallback) ----------
def load_weather():
    try:
        st.session_state.weather = core.fetch_weather()
        st.session_state.error = None
    except Exception as e:
        st.session_state.error = str(e)
        if "weather" not in st.session_state:
            st.session_state.weather = core.sample_weather()

@st.cache_data(ttl=600, show_spinner=False)
def _ward_weather(items):
    return core.fetch_ward_weather({n: (la, lo) for n, la, lo in items})

if "weather" not in st.session_state:
    load_weather()
if "sim_seed" not in st.session_state:
    st.session_state.sim_seed = random.randrange(10**9)
if st.sidebar.button("🔄 Refresh data"):
    load_weather()
    _ward_weather.clear()
    st.session_state.sim_seed = random.randrange(10**9)

w = st.session_state.weather
if st.session_state.error:
    st.warning(f"Weather service unavailable ({st.session_state.error}). Showing "
               + ("the last successful data." if w["live"] else "an offline sample — not real weather."))
if not w["live"]:
    st.error("⚠️ Offline sample data — not real weather.")
cur = w["current"]
st.sidebar.markdown(f"**Observation time:** {cur['time']}  \n**Last fetched:** {w['fetched_at']:%H:%M:%S}")

# ---------- what-if ----------
st.sidebar.header("What-if scenarios")
delta = st.sidebar.slider("Temperature change (°C)", -5.0, 20.0, 0.0, 0.5,
                          help="Heat level maxes out at 100 once apparent temperature reaches 41 °C.")
rain_delta = st.sidebar.slider("Extra rainfall in next 24h (mm)", -20, 100, 0, 5)
hum_delta = st.sidebar.slider("Humidity change (percentage points)", -30, 30, 0, 5)
at_actual = cur["apparent_temperature"]
at_used = at_actual + delta
scenario = delta != 0
active = [s for s, on in [(f"temperature {delta:+.1f} °C", delta != 0), (f"rainfall {rain_delta:+d} mm", rain_delta != 0),
                          (f"humidity {hum_delta:+d} pts", hum_delta != 0)] if on]
if active:
    st.warning("🧪 What-if scenario active (" + ", ".join(active) + "). The map and advice below show a hypothetical "
               "day, not real conditions.")
    if delta != 0 and at_used > 41:
        st.caption("Above 41 °C apparent temperature the heat level is capped at 100.")

# ---------- city weather panel ----------
c1, c2, c3 = st.columns(3)
c1.metric("Temperature now", f"{cur['temperature_2m']:.1f} °C")
c2.metric("Humidity now", f"{cur['relative_humidity_2m']:.0f} %")
c3.metric("Feels like", f"{at_actual:.1f} °C")
h = w["hourly"].set_index("time")[["temperature_2m", "apparent_temperature"]]
st.line_chart(h.rename(columns={"temperature_2m": "Temp °C", "apparent_temperature": "Feels like °C"}))

# ---------- scoring ----------
gj, vdf, notes = core.load_wards()
df, comp = core.score_wards(vdf, at_used)

# ---------- ward-wise rainfall & humidity ----------
cents = core.ward_centroids(gj)
ww = None
try:
    ww = _ward_weather(tuple((n, la, lo) for n, (la, lo) in cents.items()))
    df = df.merge(ww, on="ward_name", how="left")
    df["rain_24h_actual"], df["humidity_actual"] = df.rain_24h, df.humidity
    df["rain_24h"] = (df.rain_24h + rain_delta).clip(lower=0).round(1)
    df["humidity"] = (df.humidity + hum_delta).clip(0, 100)
except Exception as e:
    st.warning(f"Ward-wise rainfall/humidity unavailable ({e}). Other information is unaffected.")
df = df.merge(core.generate_illustrative_layers(vdf, st.session_state.sim_seed), on="ward_name", how="left")
SIM = {"Traffic": ("sim_traffic", core.TRAFFIC_BINS, "/100"),
       "AQI": ("sim_aqi", core.AQI_BINS, ""),
       "NDVI greenness": ("sim_ndvi", core.NDVI_BINS, "")}
modes = ["Heat risk"] + (["Rainfall, next 24h", "Humidity, now"] if ww is not None else []) + list(SIM)
map_mode = st.sidebar.radio("Map colors", modes)

# ---------- category counts + ranking ----------
left, right = st.columns([3, 2])
with right:
    st.subheader("Wards by heat-risk level")
    counts = df.category.value_counts().reindex(["Very High", "High", "Moderate", "Low", "Incomplete"]).fillna(0).astype(int)
    st.dataframe(counts.rename("wards"), use_container_width=True)
    st.subheader("Wards ranked by heat risk")
    cols = ["ward_name", "category", "priority"] + (["rain_24h", "humidity"] if ww is not None else []) + ["sim_traffic", "sim_aqi", "sim_ndvi"]
    st.dataframe(df[cols].rename(columns={"priority": "heat_score", "sim_traffic": "traffic", "sim_aqi": "aqi", "sim_ndvi": "ndvi"}).round(1),
                 use_container_width=True, hide_index=True, height=300)

# ---------- map ----------
with left:
    mode_scen = {"Heat risk": scenario, "Rainfall, next 24h": rain_delta != 0, "Humidity, now": hum_delta != 0}.get(map_mode, False)
    st.subheader("Ward map" + (" — what-if scenario" if mode_scen else ""))
    lookup = df.set_index("ward_name")
    m = folium.Map(location=[core.CITY_LAT, core.CITY_LON], zoom_start=11, tiles="OpenStreetMap")
    def fill(n):
        r = lookup.loc[n]
        if map_mode == "Rainfall, next 24h": return core.bin_color(r.rain_24h, core.RAIN_BINS)
        if map_mode == "Humidity, now": return core.bin_color(r.humidity, core.HUM_BINS)
        if map_mode in SIM:
            col, bins, _ = SIM[map_mode]
            return core.bin_color(r[col], bins)
        return r.color
    def style(f):
        return dict(fillColor=fill(f["properties"]["ward_name"]), color="#333", weight=1, fillOpacity=0.6)
    for f in gj["features"]:
        n = f["properties"]["ward_name"]; r = lookup.loc[n]
        tip = f"{n}: {r.category} ({r.priority:.0f})"
        if ww is not None:
            tip += f" | rain 24h {r.rain_24h} mm | humidity {r.humidity:.0f}%"
        tip += f" | traffic {r.sim_traffic:.0f} | AQI {r.sim_aqi:.0f} | NDVI {r.sim_ndvi:.2f}"
        f["properties"]["tip"] = tip
    folium.GeoJson(gj, style_function=style, tooltip=folium.GeoJsonTooltip(fields=["tip"], labels=False),
                   popup=folium.GeoJsonPopup(fields=["tip"], labels=False)).add_to(m)
    map_data = st_folium(m, height=450, use_container_width=True,
                         returned_objects=["last_active_drawing", "last_object_clicked_tooltip"]) or {}
    names = set(df.ward_name)
    clicked = ((map_data.get("last_active_drawing") or {}).get("properties") or {}).get("ward_name")
    if clicked not in names:
        tt = map_data.get("last_object_clicked_tooltip") or ""
        clicked = tt.split(":")[0].strip() if tt.split(":")[0].strip() in names else None
    if clicked and clicked != st.session_state.get("last_click"):
        st.session_state["last_click"] = clicked
        st.session_state["sel_ward"] = clicked
    if st.session_state.get("sel_ward") not in names:
        st.session_state["sel_ward"] = df.ward_name.iloc[0]
    srow = df[df.ward_name == st.session_state["sel_ward"]].iloc[0]
    st.success(f"**{srow.ward_name}** — {srow.category} heat-risk level. Click any ward to change; "
               "your travel checklist is below.")
    bins_unit = {"Rainfall, next 24h": (core.RAIN_BINS, "mm"), "Humidity, now": (core.HUM_BINS, "%")}
    if map_mode in SIM: bins_unit[map_mode] = SIM[map_mode][1:]
    if map_mode in bins_unit:
        bins, unit = bins_unit[map_mode]
        st.markdown(" ".join(f"<span style='background:{c};padding:2px 8px;border:1px solid #888;color:#000'>{lab} {unit}</span>"
                             for _, c, lab in bins), unsafe_allow_html=True)
    if map_mode in SIM:
        st.caption("Sample values for demonstration.")
    elif map_mode in ("Rainfall, next 24h", "Humidity, now"):
        st.caption(f"Weather-model values on a coarse grid ({ww.attrs.get('n_cells', '?')} cells of roughly 10 km); "
                   "neighbouring wards can share a value.")

# ---------- ward detail & travel checklist ----------
st.subheader("Your trip: conditions & checklist")
sel = st.selectbox("Select ward (or click one on the map)", df.ward_name.tolist(), key="sel_ward")
r = df[df.ward_name == sel].iloc[0]
st.markdown(f"### {sel} — {r.category} heat-risk level")
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Heat level", f"{r.hazard:.0f}/100")
m2.metric("Rain (24h)", f"{r.rain_24h} mm" if ww is not None else "n/a")
m3.metric("Humidity", f"{r.humidity:.0f}%" if ww is not None else "n/a")
m4.metric("Traffic", f"{r.sim_traffic:.0f}/100")
m5.metric("AQI", f"{r.sim_aqi:.0f}", core.aqi_category(r.sim_aqi), delta_color="off")
m6.metric("Greenery (NDVI)", f"{r.sim_ndvi:.2f}")
carry, plan = core.travel_advice(r.hazard, r.humidity if ww is not None else None,
                                 r.rain_24h if ww is not None else None, r.sim_aqi, r.sim_traffic, r.sim_ndvi, r.top_factors)
a, b = st.columns(2)
with a:
    st.markdown("#### 🎒 What to carry")
    for e, t in carry: st.write(f"{e} {t}")
with b:
    st.markdown("#### 🧭 Plan ahead")
    for e, t in plan: st.write(f"{e} {t}")

with st.expander("How JanSafe works"):
    st.markdown("""
- **Heat level** comes from the city's "feels like" temperature (27 °C → 0, 41 °C → 100). The **heat-risk level** also
  weighs community vulnerability: older-adult share, population density, distance to health facilities and cooling access.
- Rainfall and humidity are weather-model values per ward area. Traffic, AQI and greenery are sample layers.
- The checklist is rule-based: simple thresholds on the values above, not a prediction of anyone's health.
""")

# ---------- footer ----------
st.divider()
st.markdown("<p style='font-size:11px;color:#888;text-align:center;line-height:1.4'>"
            "Some data shown on JanSafe (including traffic, air quality, vegetation and certain population indicators) is "
            "illustrative and not 100% accurate. Suggestions are general guidance, not medical advice.<br>"
            "Weather: Open-Meteo.com (CC BY 4.0) · Map © OpenStreetMap contributors · Ward boundaries: public ward-delimitation data."
            "</p>", unsafe_allow_html=True)
