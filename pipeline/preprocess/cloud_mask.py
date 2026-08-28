"""Spec §7 preprocess.run: cloud mask. Fixes the false-positive problem found in
pipeline/inference/prithvi_inference.py's output — the model was never trained on cloud
pixels (they're excluded via ignore_index=-1 in the sen1floods11 config), so at
inference time it has no defined behavior for them and tends to call bright
cloud tops "water".

Rather than trying to make the model itself cloud-aware (would need retraining),
this masks the model's *output* using Sentinel-2 L2A's own Scene Classification
Layer (SCL) band — the standard, already-computed cloud/shadow/cirrus
classification that ships with every L2A product. Pixels SCL marks as
no-data/saturated/cloud-shadow/cloud/cirrus are excluded from the result.

SCL class codes used here (ESA's standard L2A SCL legend):
  0 = no data, 1 = saturated/defective, 3 = cloud shadow,
  8 = cloud medium probability, 9 = cloud high probability, 10 = thin cirrus

Usage:
  python -m pipeline.preprocess.cloud_mask \
      --item-id <stac_item_id> --pred pred_xxx.tiff --output masked_pred.tiff
"""
import argparse
import os
from pathlib import Path

import numpy as np

from pipeline import config
from pipeline.preprocess import s2_composite

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

CLOUD_SCL_CLASSES = {0, 1, 3, 8, 9, 10}
SCL_ASSET_KEY = "SCL_20m"


def build_cloud_mask(item, band_cache: Path, ref_band_path: Path, bbox, pad_ratio: float) -> np.ndarray:
    """Returns a boolean array (True = cloud/shadow/invalid, same grid as the
    6-band composite built from *ref_band_path*)."""
    from rasterio.enums import Resampling

    token = s2_composite.get_access_token()
    scl_path = s2_composite.download_band(item, SCL_ASSET_KEY, token, band_cache)

    target_transform, target_h, target_w, _ = s2_composite.compute_aoi_window(
        ref_band_path, bbox, pad_ratio
    )
    # SCL is a categorical label map — must use nearest-neighbor, never bilinear/average.
    scl = s2_composite.read_band_at_target(
        scl_path, target_transform, target_h, target_w, Resampling.nearest
    )
    cloud_mask = np.isin(scl, list(CLOUD_SCL_CLASSES))
    return cloud_mask


def apply_mask(pred_path: Path, cloud_mask: np.ndarray, out_path: Path):
    import rasterio

    with rasterio.open(pred_path) as src:
        pred = src.read(1)
        meta = src.meta.copy()

    if pred.shape != cloud_mask.shape:
        raise RuntimeError(
            f"Shape mismatch: pred {pred.shape} vs cloud_mask {cloud_mask.shape} — "
            f"did you use the same --pad-ratio and AOI as when the prediction was made?"
        )

    masked = pred.copy()
    MASKED_VALUE = 128  # distinct from 0 (no water) and 255 (water) so it's visibly "excluded", not "no water"
    masked[cloud_mask] = MASKED_VALUE
    n_masked = cloud_mask.sum()
    print(f"Masked {n_masked:,} / {cloud_mask.size:,} pixels ({100*n_masked/cloud_mask.size:.1f}%) as cloud/invalid")

    meta.update(nodata=None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(masked, 1)
    print(f"Saved cloud-masked prediction: {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-id", required=True, help="the Sentinel-2 STAC item the prediction came from")
    parser.add_argument("--pred", required=True, help="path to the pred_*.tiff from prithvi_inference.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--pad-ratio", type=float, default=0.05, help="must match what built the composite/pred")
    parser.add_argument("--band-cache-dir", default=str(config.DATA_RAW_DIR / "s2_bands"))
    parser.add_argument(
        "--bbox", type=float, nargs=4, default=None, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="must match whatever --bbox (or the config.AOI_BBOX default) built the composite/pred",
    )
    args = parser.parse_args()
    bbox = tuple(args.bbox) if args.bbox else config.AOI_BBOX

    item = s2_composite.fetch_item(args.item_id)
    band_cache = Path(args.band_cache_dir)
    ref_band_path = band_cache / f"{item.id}_B02_10m.jp2"
    if not ref_band_path.exists():
        raise RuntimeError(
            f"{ref_band_path} not found — run `python -m pipeline.preprocess.s2_composite` for this "
            f"item first (needed to reproduce the same target grid)."
        )

    cloud_mask = build_cloud_mask(item, band_cache, ref_band_path, bbox, args.pad_ratio)
    apply_mask(Path(args.pred), cloud_mask, Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
