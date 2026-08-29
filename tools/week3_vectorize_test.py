"""Week 3-5: exercise the full production vectorize.extract (sliver removal +
land-clip + simplification) against the two real backtest rasters this
project already has, and compare against Week 2-7's minimal-version numbers
(no sliver removal, no land-clip, no simplification) already sitting in the
live flood_extents table.

Usage:
  python -m tools.week3_vectorize_test
"""
import sys
import time

sys.path.insert(0, ".")
from pipeline.vectorize import vectorize_new_flood

RASTERS = {
    "Marikina (Kristine/Trami, Week2-7's actual input)":
        "data/output/S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_new_flood_w27.tiff",
    "Cagayan (Aug-2025 monsoon backtest)":
        "data/output/cagayan_inference/new_flood_cagayan.tiff",
}


def main():
    for label, path in RASTERS.items():
        print(f"\n=== {label} ===")
        print(f"  input: {path}")

        t0 = time.time()
        no_clip = vectorize_new_flood(path, clip_to_land=False, min_polygon_area_m2=0, simplify_tolerance_deg=0)
        raw_area = no_clip["area_km2"] if no_clip else 0.0
        print(f"  raw (no sliver removal, no land-clip, no simplify): {raw_area:.4f} km^2")

        t1 = time.time()
        full = vectorize_new_flood(path)
        full_area = full["area_km2"] if full else 0.0
        print(f"  full (Week 3-5): {full_area:.4f} km^2  ({time.time() - t1:.1f}s incl. land-boundary fetch)")

        if full:
            print(f"  WKT length: {len(full['geom_wkt']):,} chars")
        print(f"  total elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
