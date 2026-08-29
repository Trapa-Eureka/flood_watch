"""Week 3-6: exposure_stats calculation, exercised against the real Marikina
Kristine/Trami flood_extents row (Week 3-5's updated geom, area_km2=0.4420)
already sitting in the live Supabase DB — the same event used throughout this
project since Week 1-8.

Usage:
  python -m tools.week3_exposure_test
"""
import os
import sys

import requests

sys.path.insert(0, ".")
from pipeline import config, repository
from pipeline.exposure import compute_exposure_stats

EVENT_ID = "71426a18-da5c-4a99-a527-1600a32ea24e"  # Kristine/Trami backtest event, Week 1-8


def fetch_flood_extent_geom(event_id: str) -> str:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    resp = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/flood_extents",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params={"event_id": f"eq.{event_id}", "select": "id,geom,area_km2"},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(f"no flood_extents row for event_id={event_id}")
    row = rows[0]
    print(f"flood_extents: id={row['id']} area_km2={row['area_km2']}")
    # PostgREST returns geom as a GeoJSON dict by default — convert to WKT for
    # compute_exposure_stats' interface (which takes WKT, matching how
    # vectorize.vectorize_new_flood already hands geom around as WKT).
    from shapely.geometry import shape
    return shape(row["geom"]).wkt


def main():
    geom_wkt = fetch_flood_extent_geom(EVENT_ID)

    print("\n--- ADM3 (municipality) level ---")
    adm3_stats = compute_exposure_stats(geom_wkt, level="adm3_municipality")
    for s in adm3_stats:
        print(f"  {s['name']}: {s['flooded_area_km2']}km^2 ({s['flooded_area_pct']}%) "
              f"pop~{s['est_population_affected']} buildings~{s['est_buildings_affected']}")

    print("\n--- ADM4 (barangay) level ---")
    adm4_stats = compute_exposure_stats(geom_wkt, level="adm4_barangay")
    for s in adm4_stats:
        print(f"  {s['name']}: {s['flooded_area_km2']}km^2 ({s['flooded_area_pct']}%) "
              f"pop~{s['est_population_affected']} buildings~{s['est_buildings_affected']}")

    print(f"\nWriting {len(adm3_stats) + len(adm4_stats)} rows to exposure_stats...")
    for s in adm3_stats + adm4_stats:
        repository.upsert_exposure_stat(
            event_id=EVENT_ID, admin_boundary_id=s["admin_boundary_id"],
            flooded_area_km2=s["flooded_area_km2"], flooded_area_pct=s["flooded_area_pct"],
            est_population_affected=s["est_population_affected"],
            est_buildings_affected=s["est_buildings_affected"],
            population_source=s["population_source"], building_source=s["building_source"],
        )


if __name__ == "__main__":
    main()
