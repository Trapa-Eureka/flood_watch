"""Spec §14 step 3: open a downloaded scene with rasterio, print basic info, and
render a PNG for a visual sanity check.

Usage:
  python -m tools.visualize_scene --input path/to/scene.tif --output out.png
  python -m tools.visualize_scene --self-test   # verify the script logic without a real scene
"""
import argparse
from pathlib import Path

import numpy as np


def print_scene_info(src) -> None:
    print("-" * 60, flush=True)
    print(f"band count:         {src.count}")
    print(f"size (width x height): {src.width} x {src.height}  ({src.width*src.height/1e6:.0f} Mpixel)")
    print(f"pixel size:         {src.res}")
    print(f"CRS:                {src.crs}")
    print(f"bounds:             {src.bounds}")
    print(f"dtype:              {src.dtypes}")
    print(f"nodata:             {src.nodata}")
    if src.crs is None and src.gcps[0]:
        # Raw Sentinel-1 GRD is usually georeferenced only via GCPs, not an affine
        # transform — meaning it hasn't been geocoded (reprojected) yet. That's
        # handled in spec §7's preprocess.run stage.
        print(f"GCP count:          {len(src.gcps[0])}  (GCP CRS: {src.gcps[1]})")
        print("  → CRS being None is expected: raw GRD is GCP-based; bbox crop/reprojection belongs to preprocess")
    print("-" * 60, flush=True)


def save_png(array: np.ndarray, out_path: Path, is_sar_db: bool = False) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arr = array.astype("float64")
    arr = np.where(np.isfinite(arr), arr, np.nan)

    # SAR amplitude/dB has a large dynamic range — a 2-98 percentile stretch is
    # needed to make it visible.
    lo, hi = np.nanpercentile(arr, [2, 98])
    arr = np.clip(arr, lo, hi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(arr, cmap="gray")
    ax.set_title(out_path.stem)
    ax.axis("off")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved PNG: {out_path}")


def run_self_test() -> int:
    """Verify the band-read/stretch/PNG-save logic works, without a real satellite scene."""
    import tempfile

    import rasterio
    from rasterio.transform import from_origin

    print("self-test: verifying pipeline logic against a synthetic raster...")
    h, w = 256, 256
    data = (np.random.default_rng(0).random((1, h, w)) * 40 - 25).astype("float32")  # fake SAR dB
    transform = from_origin(121.08, 14.68, 0.0001, 0.0001)

    with tempfile.TemporaryDirectory() as tmp:
        tif_path = Path(tmp) / "synthetic.tif"
        with rasterio.open(
            tif_path, "w", driver="GTiff", height=h, width=w, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(data)

        with rasterio.open(tif_path) as src:
            print_scene_info(src)
            band1 = src.read(1)
            save_png(band1, Path(tmp) / "synthetic.png", is_sar_db=True)

    print("self-test passed — re-run with --input pointing at a real scene.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=str, default=None, help="path to a raster rasterio can open")
    parser.add_argument("--output", type=str, default=None, help="path to save the PNG to")
    parser.add_argument("--band", type=int, default=1)
    parser.add_argument(
        "--max-size", type=int, default=2000,
        help="max pixels on the long side. A full Sentinel-1 GRD scene is 400M+ "
             "pixels, so imshow at native resolution hangs — read a downsampled "
             "version via the overview instead.",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test or not args.input:
        return run_self_test()

    import rasterio

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else in_path.with_suffix(".png")

    with rasterio.open(in_path) as src:
        print_scene_info(src)

        scale = min(1.0, args.max_size / max(src.width, src.height))
        out_h, out_w = max(1, round(src.height * scale)), max(1, round(src.width * scale))
        if scale < 1.0:
            print(f"Downsampling for preview: {src.width}x{src.height} → {out_w}x{out_h} (via overview)", flush=True)

        band = src.read(args.band, out_shape=(out_h, out_w))
        save_png(band, out_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
