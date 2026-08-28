"""The actual point of spec §3: crop to the Marikina AOI and visually compare the
before/after SAR imagery.

Raw Sentinel-1 GRD is georeferenced only via GCPs (ground control points), not an
affine transform (as confirmed by tools/visualize_scene.py) — so strictly
speaking, a bbox crop isn't valid until proper reprojection (e.g. gdalwarp -geoloc,
owned by spec §7's preprocess.run stage) has been done.

Instead of that full reprojection, this script estimates an approximate affine
transform from the GCPs (rasterio.transform.from_gcps) to quickly cut out a pixel
window near the AOI — an **approximation** that does not correct for SAR
range/azimuth distortion, so the boundary can be off by a few to a few dozen
pixels. Use this only to quickly check "is there a visible signal" during the
spike; redo the precise comparison once preprocess.run is actually implemented.

Usage:
  python -m tools.aoi_crop_compare --baseline <tif> --post <tif>
"""
import argparse
from pathlib import Path

import numpy as np

from pipeline import config


def crop_to_aoi_approx(tif_path: Path, bbox, pad_ratio: float = 0.15):
    """Read a window near bbox using a GCP-based approximate affine transform.
    Returns (src, array, approx_transform)."""
    import rasterio
    from rasterio.transform import from_gcps
    from rasterio.windows import Window

    src = rasterio.open(tif_path)
    gcps, gcp_crs = src.gcps
    if not gcps:
        raise RuntimeError(f"{tif_path.name}: no GCPs, cannot do an approximate crop")

    approx_transform = from_gcps(gcps)

    west, south, east, north = bbox
    w = east - west
    h = north - south
    west -= w * pad_ratio
    east += w * pad_ratio
    south -= h * pad_ratio
    north += h * pad_ratio

    # The sign of the transform's row/col progression can vary with SAR orbit
    # direction, so we can't trust from_bounds()'s orientation assumptions —
    # invert the four corners directly and build the window from their min/max.
    inv = ~approx_transform
    corners = [(west, south), (west, north), (east, south), (east, north)]
    cols, rows = zip(*(inv * (lon, lat) for lon, lat in corners))
    col_off, row_off = min(cols), min(rows)
    col_end, row_end = max(cols), max(rows)

    window = Window(
        col_off=col_off, row_off=row_off,
        width=col_end - col_off, height=row_end - row_off,
    ).round_lengths().round_offsets()
    # Clip to the raster's actual extent
    window = window.intersection(Window(0, 0, src.width, src.height))

    if window.width <= 0 or window.height <= 0:
        raise RuntimeError(
            f"{tif_path.name}: computed AOI window falls outside this scene's GCP extent — "
            f"either the approximate transform is off, or this scene doesn't actually cover the AOI"
        )

    arr = src.read(1, window=window)
    print(f"{tif_path.name}: crop window {window.width}x{window.height}px @ ({window.col_off},{window.row_off})")
    return src, arr, approx_transform


def save_side_by_side(arr_a, arr_b, label_a, label_b, out_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def stretch(a):
        a = a.astype("float64")
        a = np.where(a > 0, a, np.nan)  # 0 = nodata
        lo, hi = np.nanpercentile(a, [2, 98])
        return np.clip(a, lo, hi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for ax, arr, label in zip(axes, [arr_a, arr_b], [label_a, label_b]):
        ax.imshow(stretch(arr), cmap="gray")
        ax.set_title(label)
        ax.axis("off")
    fig.suptitle("Marikina AOI approx crop — left: baseline(pre) / right: post_event")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved comparison PNG: {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--post", required=True)
    parser.add_argument("--output", default=str(config.DATA_OUTPUT_DIR / "aoi_compare.png"))
    args = parser.parse_args()

    print(f"AOI bbox (approx): {config.AOI_BBOX}")

    src_a, arr_a, _ = crop_to_aoi_approx(Path(args.baseline), config.AOI_BBOX)
    src_b, arr_b, _ = crop_to_aoi_approx(Path(args.post), config.AOI_BBOX)

    save_side_by_side(arr_a, arr_b, "baseline (10/14)", "post_event (10/26)", Path(args.output))

    src_a.close()
    src_b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
