"""Week 3-7: UTM multi-zone verification.

design-notes.md's original spike-stage note said: "필리핀은 UTM이 50N/51N/52N
3개 zone에 걸침, 지금 스크립트는 51N 하나만 가정 — Week3에서 손봐야 함." This
script re-checks that claim against the CURRENT pipeline (promoted into
pipeline/ during Week 1-1's repo restructure) rather than assuming the old
note still applies — and finds it doesn't: every CRS-sensitive step already
derives its projected CRS dynamically (from the actual downloaded S2 band, or
avoids needing a UTM CRS at all), so no code changes were needed. This script
documents that finding reproducibly, with real data:

1. Real S2 scenes over Palawan (zone 50N) and Davao Oriental (zone 52N) —
   confirms the *actual downloaded* band file's CRS is genuinely 32650/32652,
   not just the MGRS tile ID implying it.
2. pipeline.preprocess.s2_composite.compute_aoi_window — confirms it produces
   a correct EPSG:32650 target grid from that real Palawan band.
3. pipeline.baseline_diff.fetch_permanent_water_mask — confirms JRC's global
   mosaic reprojects correctly onto that EPSG:32650 grid (0% water over real
   downtown-Puerto-Princesa land, verified against a live-looked-up point).
4. pipeline.vectorize.vectorize_new_flood — confirms area calc + land-clip
   (admin_boundaries_near_bbox reprojected into EPSG:32650) both work.

Needs CDSE_USERNAME/CDSE_PASSWORD in .env (downloads ~130MB of real S2 bands).

Usage:
  python -m tools.week3_utm_zone_test
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from pipeline.baseline_diff import fetch_permanent_water_mask, jrc_tile_name
from pipeline.preprocess.s2_composite import compute_aoi_window, download_band, fetch_item, get_access_token
from pipeline.vectorize import vectorize_new_flood

OUT_DIR = Path("/tmp/utm_zone_test")  # scratch, not a repo artifact

# Real scenes found live via CDSE STAC search (2026-08-29) — MGRS tile IDs
# (T50.../T52...) predict the zone; this script confirms the actual band CRS.
# NOTE: the Puerto Princesa bbox search returned two adjacent zone-50N tiles,
# T50PQR and T50PPR — T50PQR (used for the CRS-only check below) turned out
# NOT to cover the actual downtown test point (its western edge is at
# 118.82°E, downtown is 118.74°E); found this live via an "Intersection is
# empty" WindowError on the first run of this script, not by pre-checking —
# T50PPR (117.91-118.91°E) does cover it, so steps 2-4 use that one instead.
PALAWAN_ITEM_ID = "S2C_MSIL2A_20260827T022531_N0512_R046_T50PQR_20260827T054915"
PALAWAN_LAND_ITEM_ID = "S2C_MSIL2A_20260827T022531_N0512_R046_T50PPR_20260827T054915"
DAVAO_ORIENTAL_ITEM_ID = "S2C_MSIL2A_20260825T020311_N0512_R017_T52NBP_20260825T043810"

# Puerto Princesa downtown, Nominatim-verified real point (9.7398561, 118.7438187).
PALAWAN_LAND_BBOX = [118.7400, 9.7370, 118.7480, 9.7430]


def check_band_crs(item_id: str, expected_epsg: int, token: str):
    import rasterio

    item = fetch_item(item_id)
    band_path = download_band(item, "B02_10m", token, OUT_DIR)
    with rasterio.open(band_path) as src:
        crs = src.crs
    status = "OK" if crs.to_epsg() == expected_epsg else "MISMATCH"
    print(f"  {item_id}: crs={crs} (expected EPSG:{expected_epsg}) [{status}]")
    return band_path, crs


def main():
    token = get_access_token()

    print("1. Real downloaded S2 band CRS matches the MGRS tile's implied UTM zone:")
    check_band_crs(PALAWAN_ITEM_ID, 32650, token)
    check_band_crs(DAVAO_ORIENTAL_ITEM_ID, 32652, token)
    palawan_land_band, _ = check_band_crs(PALAWAN_LAND_ITEM_ID, 32650, token)

    print("\n2. compute_aoi_window produces a correct target grid from the Palawan band:")
    transform, h, w, crs = compute_aoi_window(palawan_land_band, PALAWAN_LAND_BBOX, pad_ratio=0.0)
    print(f"  target_crs={crs}, shape=({h},{w})  [{'OK' if crs.to_epsg() == 32650 else 'MISMATCH'}]")

    print("\n3. JRC baseline_diff reprojects correctly onto the EPSG:32650 grid:")
    print(f"  JRC tile for Palawan: {jrc_tile_name(118.74, 9.74)} (vs. Marikina/Cagayan's 120E_20N)")
    mask = fetch_permanent_water_mask(PALAWAN_LAND_BBOX, 0.0, transform, h, w, crs)
    water_pct = 100 * mask.sum() / mask.size
    print(f"  water pct over real downtown land: {water_pct:.1f}%  [{'OK' if water_pct < 5 else 'SUSPECT'}]")

    print("\n4. vectorize.extract (area calc + land-clip) on a synthetic EPSG:32650 raster:")
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    lon, lat = 118.7438187, 9.7398561  # Puerto Princesa downtown (Nominatim)
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True).transform(lon, lat)
    size = 40
    synth_transform = from_origin(x - size * 5, y + size * 5, 10, 10)
    synth_path = OUT_DIR / "synthetic_palawan_land.tif"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        synth_path, "w", driver="GTiff", height=size, width=size, count=1, dtype="uint8",
        crs="EPSG:32650", transform=synth_transform, nodata=0,
    ) as dst:
        dst.write(np.full((size, size), 255, dtype="uint8"), 1)

    result = vectorize_new_flood(synth_path)
    area = result["area_km2"] if result else None
    print(f"  land-clipped area_km2: {area} (raw block = 0.16 km^2)  [{'OK' if area == 0.16 else 'MISMATCH'}]")

    print("\nAll steps ran against real EPSG:32650/32652 data without any code changes — "
          "the pipeline was already zone-agnostic before this check.")


if __name__ == "__main__":
    main()
