# HeatShield
Run: `pip install -r requirements.txt` then `streamlit run app.py`
Real data (optional): put ward polygons in `data/wards.geojson` (property `ward_name`) and indicators in
`data/vulnerability.csv` (columns: ward_name, pct_65_plus, pop_density, km_to_health_facility, cooling_access_score).
Sources: Open-Meteo (weather, CC BY 4.0), OpenStreetMap contributors (tiles). Bengaluru ward boundaries: check OpenCity / data.opencity.in.
