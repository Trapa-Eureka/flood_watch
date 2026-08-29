"""Week 3-4: OSM vs Google Open Buildings source comparison + demonstration of
the chosen source (Google Open Buildings, via VIDA's merged GeoParquet — see
pipeline/buildings.py's module docstring for the full live-verified decision).

Re-running this reproduces the comparison numbers cited in pipeline/buildings.py
and docs/design-notes.md (OSM via Overpass API, live query each run — counts
may drift slightly over time as OSM is continuously community-edited).

Usage:
  python -m tools.load_buildings
"""
import sys

import requests

sys.path.insert(0, ".")
from pipeline import config
from pipeline.buildings import DEFAULT_MIN_CONFIDENCE, building_count_in_bbox, fetch_buildings_in_bbox

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Cagayan Valley backtest AOI (rural/riverine) — bounds of the real prediction
# raster from the earlier spike (data/output/cagayan_inference/), not a fresh
# guess: config.py only has a Marikina bbox, so this reuses actual project
# geometry rather than inventing a second one.
CAGAYAN_BBOX = [121.5839550910802, 17.426029524107875, 121.92047175698136, 17.78635899534779]

AOIS = {
    "Marikina (urban)": config.MARIKINA_CITY_BBOX,
    "Cagayan Valley (rural)": CAGAYAN_BBOX,
}


def osm_building_count(bbox) -> int:
    west, south, east, north = bbox
    query = f"""
        [out:json][timeout:120];
        (way["building"]({south},{west},{north},{east}););
        out count;
    """
    headers = {"User-Agent": "ph-flood-watch/0.1 (research spike; contact via repo)"}
    resp = requests.post(OVERPASS_URL, data={"data": query}, headers=headers, timeout=150)
    resp.raise_for_status()
    return int(resp.json()["elements"][0]["tags"]["total"])


def bbox_area_km2(bbox) -> float:
    import math

    west, south, east, north = bbox
    mid_lat = (south + north) / 2
    km_per_deg_lon = 111.32 * math.cos(math.radians(mid_lat))
    km_per_deg_lat = 111.32
    return (east - west) * km_per_deg_lon * (north - south) * km_per_deg_lat


def main():
    print(f"{'AOI':<24}{'area_km2':>10}{'OSM':>10}{'OSM/km2':>10}{'G+MS':>10}{'G+MS/km2':>10}{'ratio':>8}")
    for name, bbox in AOIS.items():
        area = bbox_area_km2(bbox)
        osm_n = osm_building_count(bbox)
        gms_n = building_count_in_bbox(bbox, min_confidence=DEFAULT_MIN_CONFIDENCE)
        ratio = gms_n / osm_n
        print(f"{name:<24}{area:>10.1f}{osm_n:>10,}{osm_n / area:>10.1f}{gms_n:>10,}{gms_n / area:>10.1f}{ratio:>7.2f}x")

    print(f"\nDemo: fetch_buildings_in_bbox (full geometries, confidence >= {DEFAULT_MIN_CONFIDENCE}) for Marikina")
    gdf = fetch_buildings_in_bbox(config.MARIKINA_CITY_BBOX)
    print(f"  rows: {len(gdf)}, columns: {list(gdf.columns)}, crs: {gdf.crs}")
    print(f"  bf_source counts:\n{gdf['bf_source'].value_counts().to_string()}")
    print(f"  total footprint area (m^2): {gdf['area_in_meters'].sum():,.0f}")
    print(f"  sample geometry valid: {gdf.geometry.iloc[0].is_valid}, type: {gdf.geometry.iloc[0].geom_type}")


if __name__ == "__main__":
    main()
