"""Turn a downloaded Bengaluru ward GeoJSON into data/wards.geojson (+ data/vulnerability.csv if it has population).
Usage:
  python prepare_wards.py FILE.geojson                      (lists the property names it found)
  python prepare_wards.py FILE.geojson NAME_FIELD [POP_FIELD]   e.g.  ward_name TOT_P
"""
import json, math, os, sys

def walk(c, fn):
    """Apply fn to every [x, y, ...] position in nested coordinate lists."""
    if isinstance(c[0], (int, float)):
        return fn(c)
    return [walk(x, fn) for x in c]

def first_pos(c):
    while isinstance(c[0], list):
        c = c[0]
    return c

def ring_area_km2(ring):                      # shoelace on a local flat projection (fine at city scale)
    kx, ky = 111.32 * math.cos(math.radians(13)), 110.57
    pts = [(p[0] * kx, p[1] * ky) for p in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2

def area_km2(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return sum(ring_area_km2(p[0]) - sum(ring_area_km2(h) for h in p[1:]) for p in polys)

def polys_of(g):
    """Return a list of polygons (each = list of rings) from Polygon / MultiPolygon / GeometryCollection."""
    if not g:
        return []
    t = g.get("type")
    if t == "Polygon":
        return [g["coordinates"]]
    if t == "MultiPolygon":
        return list(g["coordinates"])
    if t == "GeometryCollection":
        return [p for sub in g.get("geometries", []) for p in polys_of(sub)]
    return []

src = sys.argv[1]
with open(src, encoding="utf-8") as f:
    feats = json.load(f)["features"]
print(f"Found {len(feats)} features. Property names: {list(feats[0]['properties'].keys())}")

types = {}
for ft in feats:
    t = (ft.get("geometry") or {}).get("type", "None")
    types[t] = types.get(t, 0) + 1
print("Geometry types:", types)
first = next((polys_of(ft.get("geometry")) for ft in feats if polys_of(ft.get("geometry"))), None)
if not first:
    sys.exit("No polygon geometry found in this file.")
a, b = first_pos(first[0])[:2]
swap = (12 < a < 14 and 77 < b < 78)          # stored as lat, lon -> needs flipping
if swap:
    print("Coordinates are stored as (lat, lon); flipping to (lon, lat).")
elif not (77 < a < 78 and 12 < b < 14):
    sys.exit(f"First coordinate ({a}, {b}) is not near Bengaluru. Convert the file to EPSG:4326 in QGIS first.")

if len(sys.argv) < 3:
    sys.exit(f"\nRe-run with the NAME field (and optionally the population field):\n  python prepare_wards.py {src} ward_name TOT_P")

name_f = sys.argv[2]
pop_f = sys.argv[3] if len(sys.argv) > 3 else None
seen, out, rows, skipped = {}, [], [], []
for i, ft in enumerate(feats, 1):
    p = ft["properties"]
    name = str(p.get(name_f) or f"Ward-{i}").strip()
    seen[name] = seen.get(name, 0) + 1
    if seen[name] > 1:
        name = f"{name} ({seen[name]})"
    polys = polys_of(ft.get("geometry"))
    if not polys:
        skipped.append(name)
        continue
    fix = (lambda c: [c[1], c[0]]) if swap else (lambda c: c[:2])
    geom = {"type": "MultiPolygon", "coordinates": walk(polys, fix)}
    out.append({"type": "Feature", "properties": {"ward_name": name}, "geometry": geom})
    if pop_f:
        try:
            pop = float(p[pop_f]); ar = area_km2(geom)
            rows.append((name, pop, round(pop / ar) if ar > 0 else None))
        except (KeyError, ValueError):
            rows.append((name, None, None))

os.makedirs("data", exist_ok=True)
with open("data/wards.geojson", "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": out}, f)
print(f"Wrote data/wards.geojson with {len(out)} wards.")
if skipped:
    print(f"WARNING: skipped {len(skipped)} wards with no usable shape: {skipped[:10]}")
if rows:
    with open("data/vulnerability.csv", "w", encoding="utf-8") as f:
        f.write("ward_name,total_pop,pop_density\n")
        for n, pop, d in rows:
            f.write(f'"{n}",{"" if pop is None else int(pop)},{"" if d is None else d}\n')
    ds = sorted(d for _, _, d in rows if d)
    print(f"Wrote data/vulnerability.csv (pop_density = population / polygon area). "
          f"Median density {ds[len(ds)//2]:,}/km2, max {ds[-1]:,}/km2. Sanity-check these!")
print("Restart the app.")
