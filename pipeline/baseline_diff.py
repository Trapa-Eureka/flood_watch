"""Spec §7 baseline.diff: subtract permanent water from the flood prediction so
only *new* flooding remains, not rivers/reservoirs that are wet year-round.

Rather than running Prithvi a second time on a separate pre-event scene (today's
session already found how hard it is to get a genuinely cloud-free optical scene
right around a typhoon — see pipeline/preprocess/s2_composite.py's two failed
attempts), this uses the JRC Global Surface Water "occurrence" layer as the
permanent-water baseline: a global, 30m, publicly downloadable dataset giving
the % of time (1984-2024) each pixel was observed as water. This is also the
more correct approach generally — a single pre-event pass could show transient
water (recent rain, etc.), while JRC occurrence reflects genuinely permanent
water over decades.

Source: EC Joint Research Centre, public bucket, no auth needed:
  https://s3.waw4-1.cloudferro.com/swift/v1/global-surface-water/
  download2024/Aggregated/VER1-5/occurrence/occurrence_<lon>_<lat>_v1_5_2024.tif
  (10x10 degree tiles named by their NW corner, e.g. "120E_20N")

Usage:
  python -m pipeline.baseline_diff \
      --pred data/output/marikina_inference/pred_s2_marikina_nov2_cloudmasked.tiff \
      --output data/output/marikina_new_flood.tiff
"""
import argparse
from pathlib import Path

import numpy as np

from pipeline import config

JRC_BASE_URL = (
    "https://s3.waw4-1.cloudferro.com/swift/v1/global-surface-water/"
    "download2024/Aggregated/VER1-5/occurrence"
)

# Value used in pipeline/preprocess/cloud_mask.py for "excluded, cloud/invalid" pixels.
CLOUD_MASKED_VALUE = 128
WATER_VALUE = 255

# occurrence >= this % (0-100) of the 1984-2024 record counts as "permanent water".
# Week 2-5 tuning (docs/design-notes.md) tested lowering this and found it a worse
# lever than DEFAULT_WATER_BUFFER_PX below — a lower global threshold reduces
# false positives everywhere uniformly, including areas with no boundary-adjacency
# reason to, so it risks suppressing genuine new-flood signal in areas that just
# happen to have some historical flood recurrence. Left at 50 (unchanged).
PERMANENT_WATER_THRESHOLD = 50

# Dilate the permanent-water mask by this many 30m JRC pixels before diffing.
# Week 2-5 finding: only ~17-30% of "new flood" pixels sit within 3px of known
# permanent water (i.e., only a MINORITY is explained by the narrow-river mixed-
# pixel hypothesis from A-4 — the majority is genuine signal or a different,
# still-unexplained source, see docs/design-notes.md). A 1px buffer is a
# conservative, well-justified partial fix (measured ~14-25% area reduction on
# the two backtest sites) — NOT a claim that this fully resolves the issue.
DEFAULT_WATER_BUFFER_PX = 1


def jrc_tile_name(lon: float, lat: float) -> str:
    """JRC tiles are named by the NW corner of a 10x10 degree cell."""
    tile_lon = int(np.floor(lon / 10) * 10)
    tile_lat = int(np.ceil(lat / 10) * 10)
    lon_str = f"{abs(tile_lon)}{'E' if tile_lon >= 0 else 'W'}"
    lat_str = f"{abs(tile_lat)}{'N' if tile_lat >= 0 else 'S'}"
    return f"occurrence_{lon_str}_{lat_str}_v1_5_2024.tif"


def fetch_occurrence_on_grid(bbox, pad_ratio: float, target_transform, target_h: int, target_w: int, target_crs) -> np.ndarray:
    """Read JRC GSW occurrence for *bbox* directly off the remote server (no full
    download — GDAL's /vsicurl/ uses HTTP range requests) and warp it onto the
    same grid as the prediction raster. Returns a float32 array, 0-100 (occurrence %).

    Split out from fetch_permanent_water_mask (Week 2-5) so a threshold/buffer
    sweep (tools/jrc_threshold_tuning.py) can fetch the network data ONCE per
    site and re-threshold it locally many times, instead of re-fetching for
    every combination tested.
    """
    import rasterio
    from rasterio.warp import reproject, Resampling

    west, south, east, north = bbox
    w, h = east - west, north - south
    west, east = west - w * pad_ratio, east + w * pad_ratio
    south, north = south - h * pad_ratio, north + h * pad_ratio

    tile = jrc_tile_name((west + east) / 2, (south + north) / 2)
    url = f"/vsicurl/{JRC_BASE_URL}/{tile}"
    print(f"Reading JRC Global Surface Water tile (remote, windowed): {tile}")

    with rasterio.open(url) as src:
        window = rasterio.windows.from_bounds(west, south, east, north, transform=src.transform)
        occurrence = src.read(1, window=window)
        src_window_transform = src.window_transform(window)
        src_crs = src.crs

    # Reproject/resample the (small) EPSG:4326 window onto our UTM target grid.
    occurrence_on_target = np.zeros((target_h, target_w), dtype="float32")
    reproject(
        source=occurrence.astype("float32"),
        destination=occurrence_on_target,
        src_transform=src_window_transform,
        src_crs=src_crs,
        dst_transform=target_transform,
        dst_crs=target_crs,
        resampling=Resampling.bilinear,
        src_nodata=255,  # JRC uses 255 as nodata/no-observation in some products; harmless if unused
        dst_nodata=0,
    )
    return occurrence_on_target


def permanent_water_from_occurrence(occurrence_on_target: np.ndarray,
                                     threshold: float = PERMANENT_WATER_THRESHOLD, buffer_px: int = 0) -> np.ndarray:
    """threshold/buffer_px (Week 2-5, docs/design-notes.md): occurrence >= threshold
    is the base permanent-water call; buffer_px then dilates that mask by N
    pixels (30m each at JRC's native resolution) to absorb mixed-pixel edge
    effects around narrow rivers — a real 30m pixel straddling a riverbank
    often averages to an occurrence *below* any reasonable threshold even
    though the water there is genuinely permanent, which is what caused the
    narrow-river false positives found in the A-4 backtest (Marikina, narrow,
    vs. Cagayan, wide, which didn't show the problem).
    """
    permanent_water = occurrence_on_target >= threshold
    pct_before = 100 * permanent_water.sum() / permanent_water.size

    if buffer_px > 0:
        from scipy.ndimage import binary_dilation

        permanent_water = binary_dilation(permanent_water, iterations=buffer_px)

    pct = 100 * permanent_water.sum() / permanent_water.size
    buf_note = f", +{buffer_px}px buffer -> {pct:.1f}%" if buffer_px > 0 else ""
    print(f"Permanent water (occurrence >= {threshold}%): {pct_before:.1f}% of AOI{buf_note}")
    return permanent_water


def fetch_permanent_water_mask(bbox, pad_ratio: float, target_transform, target_h: int, target_w: int, target_crs,
                                threshold: float = PERMANENT_WATER_THRESHOLD, buffer_px: int = 0):
    """Convenience wrapper: fetch_occurrence_on_grid + permanent_water_from_occurrence
    in one call — what scripts/CLIs that only need one (threshold, buffer_px)
    combination should use. Returns a boolean array, True = permanent water."""
    occurrence_on_target = fetch_occurrence_on_grid(bbox, pad_ratio, target_transform, target_h, target_w, target_crs)
    return permanent_water_from_occurrence(occurrence_on_target, threshold=threshold, buffer_px=buffer_px)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pred", required=True, help="cloud-masked prediction from pipeline/preprocess/cloud_mask.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--pad-ratio", type=float, default=0.05, help="must match what built the composite/pred")
    parser.add_argument(
        "--bbox", type=float, nargs=4, default=None, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="must match the AOI actually used for --pred (this picks which JRC tile(s) to read — "
             "wrong bbox silently reads the wrong location's permanent-water data)",
    )
    parser.add_argument(
        "--threshold", type=float, default=PERMANENT_WATER_THRESHOLD,
        help="occurrence %% (0-100) that counts as permanent water (Week 2-5 tuning)",
    )
    parser.add_argument(
        "--water-buffer-px", type=int, default=DEFAULT_WATER_BUFFER_PX,
        help="dilate the permanent-water mask by N pixels (30m each) to absorb narrow-river "
             "mixed-pixel edges (Week 2-5 tuning) — pass 0 to reproduce the original A-stage behavior",
    )
    args = parser.parse_args()
    bbox = tuple(args.bbox) if args.bbox else config.AOI_BBOX

    import rasterio

    with rasterio.open(args.pred) as src:
        pred = src.read(1)
        meta = src.meta.copy()
        target_transform, target_crs = src.transform, src.crs
        target_h, target_w = src.height, src.width

    permanent_water = fetch_permanent_water_mask(
        bbox, args.pad_ratio, target_transform, target_h, target_w, target_crs,
        threshold=args.threshold, buffer_px=args.water_buffer_px,
    )

    is_flood_class = pred == WATER_VALUE
    is_cloud_masked = pred == CLOUD_MASKED_VALUE

    new_flood = is_flood_class & ~permanent_water & ~is_cloud_masked

    out = np.zeros(pred.shape, dtype="uint8")
    out[is_cloud_masked] = CLOUD_MASKED_VALUE
    out[permanent_water & ~is_cloud_masked] = 180  # existing/permanent water, distinct from new flood
    out[new_flood] = WATER_VALUE  # new flood — same "255" convention as upstream water class

    n_new = new_flood.sum()
    n_total = (~is_cloud_masked).sum()  # denominator excludes cloud-obscured area
    print(f"New (non-permanent) flooded pixels: {n_new:,} / {n_total:,} valid pixels ({100*n_new/n_total:.2f}%)")

    meta.update(nodata=None)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(args.output, "w", **meta) as dst:
        dst.write(out, 1)
    print(f"Saved: {args.output}  (255=new flood, 180=pre-existing/permanent water, 128=cloud-excluded, 0=dry land)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
