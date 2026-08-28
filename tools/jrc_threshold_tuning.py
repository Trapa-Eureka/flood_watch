"""Week 2-5: JRC baseline.diff precision tuning.

Two things, both against real backtest predictions (already cloud-masked,
from the A-stage backtests — no new inference needed):

1. Diagnostic (once per site, at the current default threshold=50/buffer=0):
   for every pixel baseline.diff currently calls "new flood", how far (in
   30m JRC pixels) is it from the nearest JRC-permanent-water pixel? If the
   narrow-river false positives really are a mixed-pixel edge effect (the
   A-4 hypothesis — docs/design-notes.md), most of Marikina's "new flood"
   pixels should sit right next to permanent water (distance ~1px), while
   Cagayan's (already "clean" per A-4) should be more spread out.

2. Sweep: occurrence threshold x mask-dilation-buffer, both sites, reporting
   new-flood area for each combination — to see which setting shrinks
   Marikina's (presumed-artifact) new-flood area without also shrinking
   Cagayan's (presumed-genuine) new-flood area. The JRC occurrence layer is
   fetched ONCE per site (network call) and re-thresholded locally for every
   combination — see pipeline.baseline_diff.fetch_occurrence_on_grid.

Usage:
  python -m tools.jrc_threshold_tuning
"""
import sys

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

sys.path.insert(0, ".")
from pipeline.baseline_diff import (
    CLOUD_MASKED_VALUE,
    WATER_VALUE,
    fetch_occurrence_on_grid,
    permanent_water_from_occurrence,
)

SITES = {
    "marikina": "data/output/marikina_inference/pred_s2_marikina_nov2_cloudmasked.tiff",
    "cagayan": "data/output/cagayan_inference/pred_cagayan_cloudmasked.tiff",
}

THRESHOLDS = [30, 40, 50, 60]
BUFFERS = [0, 1, 2]


def load_pred(path):
    with rasterio.open(path) as src:
        pred = src.read(1)
        target_transform, target_crs = src.transform, src.crs
        target_h, target_w = src.height, src.width
        bbox = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    return pred, target_transform, target_crs, target_h, target_w, bbox


def compute_new_flood(pred, permanent_water):
    is_flood_class = pred == WATER_VALUE
    is_cloud_masked = pred == CLOUD_MASKED_VALUE
    new_flood = is_flood_class & ~permanent_water & ~is_cloud_masked
    n_total = (~is_cloud_masked).sum()
    return new_flood, 100 * new_flood.sum() / n_total


def diagnostic(site: str, pred, permanent_water_baseline):
    from scipy.ndimage import distance_transform_edt

    new_flood, pct = compute_new_flood(pred, permanent_water_baseline)
    print(f"\n=== [{site}] diagnostic: how far is 'new flood' from permanent water? (threshold=50, buffer=0) ===")
    print(f"  new_flood: {new_flood.sum():,} px ({pct:.2f}% of valid area)")

    dist = distance_transform_edt(~permanent_water_baseline)
    new_flood_dist = dist[new_flood]

    if new_flood_dist.size == 0:
        print("  (no new_flood pixels — nothing to characterize)")
        return

    buckets = [(0, 1), (1, 2), (2, 3), (3, float("inf"))]
    for lo, hi in buckets:
        frac = 100 * ((new_flood_dist >= lo) & (new_flood_dist < hi)).mean()
        hi_label = f"{hi}px" if hi != float("inf") else "inf"
        print(f"  distance [{lo}px, {hi_label}): {frac:.1f}% of new_flood pixels")
    print(f"  median distance to nearest permanent water: {np.median(new_flood_dist):.2f}px")


def sweep(site: str, pred, occurrence_on_target):
    print(f"\n=== [{site}] threshold x buffer sweep (occurrence fetched once, re-thresholded locally) ===")
    header = "threshold\\buffer  " + "  ".join(f"{b}px" for b in BUFFERS)
    print(f"  {header}")
    for t in THRESHOLDS:
        row = []
        for b in BUFFERS:
            permanent_water = permanent_water_from_occurrence(occurrence_on_target, threshold=t, buffer_px=b)
            _, pct = compute_new_flood(pred, permanent_water)
            row.append(f"{pct:6.2f}%")
        print(f"  {t:>9}%      " + "  ".join(row))


def main():
    for site, path in SITES.items():
        pred, target_transform, target_crs, target_h, target_w, bbox = load_pred(path)
        occurrence_on_target = fetch_occurrence_on_grid(bbox, 0.05, target_transform, target_h, target_w, target_crs)

        permanent_water_baseline = permanent_water_from_occurrence(occurrence_on_target, threshold=50, buffer_px=0)
        diagnostic(site, pred, permanent_water_baseline)
        sweep(site, pred, occurrence_on_target)


if __name__ == "__main__":
    main()
