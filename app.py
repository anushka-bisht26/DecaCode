import folium, pandas as pd, streamlit as st
from streamlit_folium import st_folium
import core

st.set_page_config(page_title="HeatShield", layout="wide")
st.title("🔥 HeatShield — Live Heat-Risk Mapping & Intervention Prioritization")
st.caption("Decision-support prototype. Rule-based heuristic scores — NOT machine learning, NOT clinically validated.")

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
if st.sidebar.button("🔄 Refresh weather"):
    load_weather()
    _ward_weather.clear()

w = st.session_state.weather
if st.session_state.error:
    st.warning(f"Weather API failed ({st.session_state.error}). Showing "
               + ("last successful data." if w["live"] else "an OFFLINE SAMPLE — not real observations."))
if not w["live"]:
    st.error("⚠️ OFFLINE SAMPLE DATA — not real weather.")
cur = w["current"]
st.sidebar.markdown(f"**Observation time:** {cur['time']}  \n**Last fetched:** {w['fetched_at']:%H:%M:%S}")

# ---------- what-if ----------
st.sidebar.header("What-if scenarios (hypothetical)")
delta = st.sidebar.slider("Temperature change (°C)", -5.0, 20.0, 0.0, 0.5,
                          help="Heat hazard saturates at 100 once apparent temperature reaches 41 °C.")
rain_delta = st.sidebar.slider("Extra rainfall in next 24h (mm)", -20, 100, 0, 5,
                               help="Added to each ward's forecast; totals never go below 0.")
hum_delta = st.sidebar.slider("Humidity change (percentage points)", -30, 30, 0, 5,
                              help="Affects only the humidity map layer, not the heat score.")
at_actual = cur["apparent_temperature"]
at_used = at_actual + delta
scenario = delta != 0
if scenario:
    st.error(f"🧪 HYPOTHETICAL HEAT SCENARIO: apparent temp = {at_used:.1f}°C "
             f"(actual {at_actual:.1f}°C {delta:+.1f}°C). Heat scores are NOT based on real weather.")
    if at_used > 41:
        st.info("Above 41 °C apparent temperature the hazard index is capped at 100, so raising it further "
                "will not change the colours.")
if rain_delta != 0:
    st.error(f"🧪 HYPOTHETICAL RAINFALL SCENARIO: {rain_delta:+d} mm added to every ward's 24h forecast. Not a real forecast.")
if hum_delta != 0:
    st.error(f"🧪 HYPOTHETICAL HUMIDITY SCENARIO: {hum_delta:+d} percentage points. Not a real observation.")

# ---------- city weather panel ----------
c1, c2, c3 = st.columns(3)
c1.metric("Temperature (actual)", f"{cur['temperature_2m']:.1f} °C")
c2.metric("Humidity (actual)", f"{cur['relative_humidity_2m']:.0f} %")
c3.metric("Apparent temp (actual)", f"{at_actual:.1f} °C")
h = w["hourly"].set_index("time")[["temperature_2m", "apparent_temperature"]]
st.line_chart(h.rename(columns={"temperature_2m": "Temp °C", "apparent_temperature": "Apparent °C"}))
st.caption("Weather: Open-Meteo.com (CC BY 4.0). City-level point forecast.")

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
    df["rain_24h"] = (df.rain_24h + rain_delta).clip(lower=0).round(1)      # scenario values when sliders != 0
    df["humidity"] = (df.humidity + hum_delta).clip(0, 100)
except Exception as e:
    st.warning(f"Ward-wise rainfall/humidity unavailable ({e}). Heat results are unaffected.")
modes = ["Heat priority"] + (["Rainfall, next 24h", "Humidity, now"] if ww is not None else [])
map_mode = st.sidebar.radio("Map colors", modes)

# ---------- category counts + priority list ----------
left, right = st.columns([3, 2])
with right:
    st.subheader("Wards by category")
    counts = df.category.value_counts().reindex(["Very High", "High", "Moderate", "Low", "Incomplete"]).fillna(0).astype(int)
    st.dataframe(counts.rename("wards"), use_container_width=True)
    st.subheader("Priority ranking")
    cols = ["ward_name", "category", "priority", "hazard", "vulnerability"] + (["rain_24h", "humidity"] if ww is not None else []) + ["data_status"]
    st.dataframe(df[cols].round(1), use_container_width=True, hide_index=True, height=300)

# ---------- map ----------
with left:
    mode_scen = {"Heat priority": scenario, "Rainfall, next 24h": rain_delta != 0, "Humidity, now": hum_delta != 0}[map_mode]
    st.subheader("Ward map" + (" — HYPOTHETICAL SCENARIO" if mode_scen else ""))
    lookup = df.set_index("ward_name")
    m = folium.Map(location=[core.CITY_LAT, core.CITY_LON], zoom_start=11, tiles="OpenStreetMap")
    def fill(n):
        r = lookup.loc[n]
        if map_mode == "Rainfall, next 24h": return core.bin_color(r.rain_24h, core.RAIN_BINS)
        if map_mode == "Humidity, now": return core.bin_color(r.humidity, core.HUM_BINS)
        return r.color
    def style(f):
        return dict(fillColor=fill(f["properties"]["ward_name"]), color="#333", weight=1, fillOpacity=0.6)
    for f in gj["features"]:
        n = f["properties"]["ward_name"]; r = lookup.loc[n]
        tip = f"{n}: {r.category} ({r.priority:.0f})"
        if ww is not None:
            tip += f" | rain 24h {r.rain_24h} mm | humidity {r.humidity:.0f}%"
        f["properties"]["tip"] = tip
    folium.GeoJson(gj, style_function=style, tooltip=folium.GeoJsonTooltip(fields=["tip"], labels=False),
                   popup=folium.GeoJsonPopup(fields=["tip"], labels=False)).add_to(m)
    # only click events trigger a rerun (panning/zooming does not)
    map_data = st_folium(m, height=450, use_container_width=True,
                         returned_objects=["last_active_drawing", "last_object_clicked_tooltip"]) or {}
    names = set(df.ward_name)
    clicked = ((map_data.get("last_active_drawing") or {}).get("properties") or {}).get("ward_name")
    if clicked not in names:                       # fallback: parse the clicked tooltip text
        tt = map_data.get("last_object_clicked_tooltip") or ""
        clicked = tt.split(":")[0].strip() if tt.split(":")[0].strip() in names else None
    if clicked and clicked != st.session_state.get("last_click"):
        st.session_state["last_click"] = clicked
        st.session_state["sel_ward"] = clicked     # the dropdown below follows the map click
    if st.session_state.get("sel_ward") not in names:
        st.session_state["sel_ward"] = df.ward_name.iloc[0]
    srow = df[df.ward_name == st.session_state["sel_ward"]].iloc[0]
    st.success(f"**Selected: {srow.ward_name}** — {srow.category} priority ({srow.priority:.0f}/100). "
               "Click any ward to change; full details and actions are below.")
    if map_mode != "Heat priority":
        bins, unit = (core.RAIN_BINS, "mm") if map_mode.startswith("Rain") else (core.HUM_BINS, "%")
        st.markdown(" ".join(f"<span style='background:{c};padding:2px 8px;border:1px solid #888;color:#000'>{lab} {unit}</span>"
                             for _, c, lab in bins), unsafe_allow_html=True)
        if mode_scen:
            st.warning("Colours show a hypothetical scenario, not actual or forecast conditions.")
        st.info(f"{map_mode}: weather-MODEL values on a coarse grid ({ww.attrs.get('n_cells', '?')} distinct cells "
                "of roughly 10 km), not measurements in each ward. Neighbouring wards share values. Colour bins are for "
                "display only, not risk categories. Heat priority is unchanged.")
    st.caption("Map © OpenStreetMap contributors. " + " | ".join(notes))
    if any("ILLUSTRATIVE" in n for n in notes):
        st.warning("Some wards/indicators are ILLUSTRATIVE placeholders, not real data.")

# ---------- ward detail ----------
st.subheader("Ward detail & suggested actions")
sel = st.selectbox("Select ward (or click one on the map)", df.ward_name.tolist(), key="sel_ward")
r = df[df.ward_name == sel].iloc[0]
a, b = st.columns(2)
with a:
    st.markdown(f"### {sel} — **{r.category}** priority ({r.priority:.0f}/100)")
    st.progress(int(r.hazard), text=f"Weather hazard: {r.hazard:.0f}/100 (city-wide)")
    st.progress(int(r.vulnerability) if r.vulnerability == r.vulnerability else 0,
                text=f"Vulnerability: {r.vulnerability:.0f}/100")
    st.write(f"Main contributing vulnerability factors: **{r.top_factors}**")
    st.caption(f"Data status: {r.data_status}")
with b:
    v = vdf[vdf.ward_name == sel].iloc[0]
    real = str(v.get("real_cols", "")).split(",")
    tag = lambda col: "✅ from file" if col in real else "⚠️ ILLUSTRATIVE (random placeholder)"
    st.write(f"- Age 65+ share: {v.pct_65_plus}% — {tag('pct_65_plus')}\n"
             f"- Density: {v.pop_density:,.0f} /km² — {tag('pop_density')} (population ÷ polygon area)\n"
             f"- Distance to health facility: {v.km_to_health_facility} km — {tag('km_to_health_facility')}\n"
             f"- Cooling access (0–1): {v.cooling_access_score} — {tag('cooling_access_score')}")
    if ww is not None:
        st.write(f"**Rainfall/humidity (model grid cell, ~10 km):** rain now {r.rain_now} mm · "
                 f"next 24h {r.rain_24h_actual} mm · humidity {r.humidity_actual:.0f}% *(actual model values)*")
        if rain_delta != 0 or hum_delta != 0:
            st.caption(f"🧪 Scenario values: rain next 24h {r.rain_24h} mm · humidity {r.humidity:.0f}% (hypothetical)")
st.markdown("**Suggested actions**")
for x in core.recommendations(r):
    st.write("•", x)
st.info("These are decision-support suggestions from a simple heuristic, not validated medical predictions. "
        "Local health officials should apply judgement.")

with st.expander("Method & limitations"):
    st.markdown("""
- **Hazard** = linear scale of apparent temperature (27 °C→0, 41 °C→100). Unvalidated heuristic.
- **Vulnerability** = weighted mix of older share, density, distance to facility, low cooling access.
- **Priority** = hazard × (0.4 + 0.6 × vulnerability/100). Rainfall and humidity are NOT part of it.
- Heat hazard uses one city-level weather point, so it is identical across wards.
- Rainfall/humidity are weather-model values on a coarse grid (Open-Meteo), shown for context only.
- **No ML model**: no openly available, ward-level heat-health outcome labels could be obtained; we refused to invent labels.
""")
