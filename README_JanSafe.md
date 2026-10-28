# JanSafe — Bengaluru Heat, Weather & Travel Awareness Dashboard

JanSafe is a Streamlit prototype that combines current Bengaluru weather, ward boundary data, an estimated heat-priority score, and a simple travel checklist. It is intended as a healthcare/public-safety hackathon demonstration—not as an official warning system or a clinically validated health-risk prediction tool.

> **Important:** The current version does **not** use machine learning. Its heat-hazard, vulnerability, and priority scores are transparent rule-based heuristics. Some ward-level indicators are simulated. Do not use the output as an official measurement of ward conditions or an individual medical recommendation.

## Features

- Fetches current weather and a short hourly forecast for Bengaluru from the Open-Meteo API.
- Shows temperature, relative humidity, apparent temperature (“feels like”), and an hourly temperature chart.
- Displays a map of wards or illustrative zones.
- Calculates an estimated heat-hazard score and combines it with population-vulnerability indicators to rank areas.
- Retrieves model-grid rainfall and humidity values for ward-centroid locations when the weather service is available.
- Provides map layers for heat risk, rainfall, humidity, and illustrative traffic, air-quality (AQI), and vegetation (NDVI) indicators.
- Includes “what-if” controls for hypothetical temperature, rainfall, and humidity changes.
- Gives general travel-preparation suggestions based on the displayed conditions.
- Falls back to clearly labelled sample weather when the weather API is unavailable.

## Requirements

- Python 3.10 or newer recommended
- Internet access for live weather and map tiles
- The packages listed in `requirements.txt`

## Run locally

Open a terminal in the project directory and run:

```bash
python -m venv .venv
```

Activate the environment:

**Windows PowerShell**
```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
source .venv/bin/activate
```

Install dependencies and start the app:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Streamlit will print a local URL, usually `http://localhost:8501`, to open in your browser.

No API key is required for the current Open-Meteo integration used by this prototype. If the weather service is unreachable, the app attempts to use offline sample weather and labels it as sample data.

## Use real ward boundaries

The app looks for files at these exact paths:

- `data/wards.geojson`
- `data/vulnerability.csv`

The uploaded GeoJSON files in the project root are source files; the app does **not** load those root-level files directly. Use `prepare_wards.py` to convert one into the expected `data/` files.

### Recommended: Bengaluru GBA ward file

The provided `wards_bengaluru_gba.geojson` contains ward names and a `TOT_P` population field. From the project root, run:

```bash
python prepare_wards.py wards_bengaluru_gba.geojson ward_name TOT_P
```

This creates:

- `data/wards.geojson` — normalized ward boundaries with a `ward_name` property.
- `data/vulnerability.csv` — population and estimated population density derived from the source population field and polygon area.

Restart Streamlit after generating these files.

**Data limitation:** The generated CSV includes `total_pop` and `pop_density`. The current scoring code only uses `pop_density` from this generated CSV; age share, distance to a health facility, and cooling-access score remain illustrative unless you supply those columns from a credible source. Population density estimates depend on the source population data and boundary geometry, so sanity-check them before presenting them as factual.

### Alternative: BBMP ward file

The provided `BBMP.geojson` contains the `KGISWardName` field but does not have the same `TOT_P` population field used above. To use its boundaries without generating a population CSV, run:

```bash
python prepare_wards.py BBMP.geojson KGISWardName
```

This creates `data/wards.geojson`. Vulnerability indicators will remain illustrative unless you separately provide `data/vulnerability.csv`.

### Expected vulnerability CSV columns

To provide real values for the current scoring code, `data/vulnerability.csv` should contain a `ward_name` column matching the names in `data/wards.geojson`, plus any available columns from:

| Column | Meaning expected by the app |
|---|---|
| `pct_65_plus` | Percentage of residents aged 65 or older |
| `pop_density` | Population per square kilometre |
| `km_to_health_facility` | Distance to a health facility, in kilometres |
| `cooling_access_score` | Cooling access score from 0 to 1; higher means better access |

The app fills missing indicators with illustrative values. Use reliable, documented sources and matching ward names if replacing them with real data.

## How the scoring works

The scores are heuristic indicators, not a trained ML model and not clinically validated.

### 1. Heat-hazard index

The app uses the current city-level apparent temperature:

```text
hazard = clip((apparent_temperature - 27) / 14 * 100, 0, 100)
```

This maps 27 °C to 0 and 41 °C to 100, with values clipped to that range. These thresholds are prototype assumptions, not validated local health thresholds. The same city-level heat-hazard value is applied to all wards.

### 2. Vulnerability score

The vulnerability score combines four normalized indicators:

- Older-adult share: 30%
- Population density: 20%
- Distance to a health facility: 25%
- Low cooling access: 25%

The normalized components are combined into a 0–100 score. The implementation uses these assumptions: age share is scaled against 20%, population density against 30,000 people/km², distance against 5 km, and cooling access is inverted so lower access means higher vulnerability.

### 3. Priority score

```text
priority = hazard * (0.4 + 0.6 * vulnerability / 100)
```

The app assigns categories using the resulting score: Low, Moderate, High, and Very High. These categories are prototype bands and should not be interpreted as official public-health risk levels.

## Data sources and limitations

- **Weather:** [Open-Meteo](https://open-meteo.com/), with attribution under CC BY 4.0 as stated in the app.
- **Map tiles:** © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
- **Ward boundaries:** The included GeoJSON files are user-provided source data. Check their original publisher, date, licence, and geographic definitions before redistributing or treating them as official.
- **Ward rainfall and humidity:** These are obtained from weather-model grid cells near rough ward bounding-box centres. They are not direct measurements for each ward; multiple wards can share a grid-cell value.
- **Traffic, AQI, and NDVI:** Currently simulated for demonstration and regenerated when the simulation seed changes. They are not live observations.
- **Vulnerability indicators:** Generated illustrative values are used for any missing fields. The app should not be presented as having complete real ward-level vulnerability data unless those fields have been sourced and checked.
- **Fallback weather:** Offline sample weather is synthetic, not real-time weather.
- **Travel checklist:** Advice is rule-based general guidance, not medical advice, a route-safety guarantee, or a substitute for official weather/emergency guidance.

## File guide

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface: weather panels, charts, map, map-layer selection, what-if controls, ward ranking, and travel checklist. |
| `core.py` | Core functions: weather API requests, fallback weather, ward loading, illustrative data, heat/vulnerability/priority scoring, and travel suggestions. |
| `prepare_wards.py` | Converts a source ward GeoJSON into the file format expected by the app; can also derive population density when a population field is supplied. |
| `requirements.txt` | Python dependencies needed to run the app. |
| `BBMP.geojson` | Source GeoJSON containing 243 ward features and KGIS ward-name properties. |
| `wards_bengaluru_gba.geojson` | Source GeoJSON containing 369 ward features, ward names, and the `TOT_P` population field. |
| `README.md` | Project overview, setup instructions, data notes, and file documentation. |
| `data/wards.geojson` | Generated by `prepare_wards.py`; used by the app when present. |
| `data/vulnerability.csv` | Optional/generated indicator file used by the app when present. |

## Troubleshooting

- **`ModuleNotFoundError`:** Activate the virtual environment and run `python -m pip install -r requirements.txt`.
- **Map shows `Zone-01`, `Zone-02`, etc.:** The app did not find `data/wards.geojson`. Run one of the `prepare_wards.py` commands above from the project root, then restart the app.
- **Weather unavailable:** Check the internet connection. The app should display a warning and use sample weather if no previous live response is available.
- **Some ward indicators look repetitive or implausible:** They may be simulated or based on coarse weather-grid data. Check the source and the data-status caveats before using them in a presentation.
- **Ward names do not match:** Ensure the `ward_name` values in the GeoJSON and CSV match exactly.

## Intended use

JanSafe is an educational hackathon prototype to explore how weather information and population-vulnerability indicators might support heat-awareness planning. It is not an official alerting system, medical device, or validated predictor of illness. Decisions affecting public safety should use verified data and guidance from relevant authorities.
