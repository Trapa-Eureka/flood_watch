"""Week 2-3: does non-overlapping sliding-window inference (prithvi_inference.py's
run_model — stride == img_size == 512, no overlap/blending) leave visible seams
at tile boundaries?

Two checks, both against the real Marikina composite (2677x904 -> padded to
3072x1024 -> a 6x2 = 12-tile grid, so this already exercises multi-tile
stitching, not just one tile — the original sprint-plan note assumed the
spike's AOI might have stayed within one tile; it didn't, see
docs/design-notes.md):

1. Statistical: class-flip rate row-by-row and column-by-column across the
   whole prediction. If tile boundaries (rows/cols at multiples of 512) show
   a spike in flip rate vs. their neighbors, that's a seam signature (real
   water-body edges don't know where the tile grid is, so they shouldn't
   correlate with multiples of 512).

2. Direct: crop a 512x512 window so a real tile boundary lands in the
   *middle* of it, run inference on that crop alone (now boundary-free for
   that region), and diff against the same pixels' prediction from the full
   sliding-window run (where that same location WAS a boundary). If tiling
   doesn't matter, the two should agree almost everywhere.

Usage:
  python -m tools.tile_stitching_check
"""
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

sys.path.insert(0, ".")
from pipeline import config
from pipeline.inference.prithvi_inference import (
    _convert_np_uint8,
    load_example,
    run_model,
    save_geotiff,
)

COMPOSITE_PATH = config.DATA_OUTPUT_DIR / "S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159_composite.tif"
CHECKPOINT_DIR = config.REPO_ROOT / ".cache" / "prithvi_official_demo"
IMG_SIZE = 512


def load_model():
    from terratorch.cli_tools import LightningInferenceModel

    config_path = CHECKPOINT_DIR / "config.yaml"
    checkpoint_path = CHECKPOINT_DIR / "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt"
    lightning_model = LightningInferenceModel.from_config(str(config_path), str(checkpoint_path))
    lightning_model.model.eval()
    return lightning_model


def infer(lightning_model, data_file: str) -> np.ndarray:
    input_data, temporal_coords, location_coords, meta_data = load_example(
        file_paths=[data_file], indices=[0, 1, 2, 3, 4, 5],
    )
    if input_data.mean() > 1:
        input_data = input_data / 10000
    pred = run_model(
        input_data, temporal_coords, location_coords,
        lightning_model.model, lightning_model.datamodule, IMG_SIZE,
    )
    return pred[0].numpy()  # (H, W)


def flip_rate_by_line(pred: np.ndarray, axis: int) -> np.ndarray:
    """For axis=0 (rows): flip_rate[i] = fraction of columns where pred[i,:] != pred[i-1,:].
    For axis=1 (cols): same, transposed. Length = size along axis - 1."""
    a = pred if axis == 0 else pred.T
    diffs = (a[1:] != a[:-1])
    return diffs.mean(axis=1)


def check_statistical(pred: np.ndarray):
    h, w = pred.shape
    print(f"\n=== 1) Statistical: class-flip rate at tile boundaries vs. neighbors ===")
    print(f"  prediction shape: {h}x{w}")

    for axis, size, label in ((0, h, "row"), (1, w, "col")):
        boundaries = [b for b in range(IMG_SIZE, size, IMG_SIZE)]
        if not boundaries:
            print(f"  ({label}) size {size} < {IMG_SIZE} — no interior tile boundary on this axis, skipping")
            continue
        rates = flip_rate_by_line(pred, axis)
        baseline = np.median(rates)
        print(f"  ({label}) boundaries at {boundaries}, baseline median flip rate={baseline:.4f}")
        for b in boundaries:
            # flip_rate index i corresponds to the transition between line i and i+1
            idx = b - 1
            if idx < 0 or idx >= len(rates):
                continue
            at_boundary = rates[idx]
            ratio = at_boundary / baseline if baseline > 0 else float("inf")
            flag = "  <-- ELEVATED" if ratio > 3 else ""
            print(f"    {label}={b}: flip_rate={at_boundary:.4f}  ({ratio:.1f}x baseline){flag}")


def check_direct_crossing(lightning_model, pred_full: np.ndarray, boundary_row: int):
    print(f"\n=== 2) Direct: same pixels, boundary-at-edge vs. boundary-in-middle (row={boundary_row}) ===")

    crop_row_off, crop_h = boundary_row - 256, 512
    crop_col_off, crop_w = 0, 512

    with rasterio.open(COMPOSITE_PATH) as src:
        window = Window(crop_col_off, crop_row_off, crop_w, crop_h)
        crop_data = src.read(window=window)
        crop_transform = src.window_transform(window)
        crop_meta = src.meta.copy()
        crop_meta.update(height=crop_h, width=crop_w, transform=crop_transform)

    crop_path = config.DATA_OUTPUT_DIR / f"TEST_boundary_crop_{boundary_row}.tif"
    with rasterio.open(crop_path, "w", **crop_meta) as dst:
        dst.write(crop_data)

    print(f"  cropped rows[{crop_row_off}:{crop_row_off+crop_h}) cols[{crop_col_off}:{crop_col_off+crop_w}) "
          f"-> saved {crop_path.name} (single 512x512 tile, no internal boundary)")

    print("  reusing full-image inference already computed (boundary WAS at the edge of tiles there)...")
    pred_full_crop = pred_full[crop_row_off:crop_row_off + crop_h, crop_col_off:crop_col_off + crop_w]

    print("  running cropped-alone inference (boundary now in the MIDDLE, no seam)...")
    pred_crop_alone = infer(lightning_model, str(crop_path))

    assert pred_full_crop.shape == pred_crop_alone.shape, "shape mismatch — crop logic bug"

    mismatch = pred_full_crop != pred_crop_alone
    total_mismatch_pct = 100 * mismatch.sum() / mismatch.size
    print(f"\n  overall mismatch: {mismatch.sum():,} / {mismatch.size:,} px ({total_mismatch_pct:.2f}%)")

    # Local row index 256 in the crop == global row *boundary_row* == the former seam location.
    seam_local_row = 256
    near_seam = mismatch[seam_local_row - 20:seam_local_row + 20, :]
    away_from_seam = np.concatenate([mismatch[:seam_local_row - 40, :], mismatch[seam_local_row + 40:, :]], axis=0)
    near_pct = 100 * near_seam.mean()
    away_pct = 100 * away_from_seam.mean()
    print(f"  mismatch rate within 20px of the former seam (row {seam_local_row}): {near_pct:.2f}%")
    print(f"  mismatch rate elsewhere (>40px from the seam): {away_pct:.2f}%")
    ratio = near_pct / away_pct if away_pct > 0 else float("inf")
    if ratio > 3 and near_pct > 1:
        print(f"  --> SEAM ARTIFACT DETECTED: {ratio:.1f}x higher mismatch right at the former tile boundary")
    else:
        print(f"  --> no meaningful seam artifact ({ratio:.1f}x — mismatch is not concentrated at the boundary)")

    crop_path.unlink()
    return total_mismatch_pct, near_pct, away_pct


def main():
    print("Loading Prithvi model (local, cached checkpoint)...")
    lightning_model = load_model()

    print(f"Running full-image inference on {COMPOSITE_PATH.name}...")
    pred_full = infer(lightning_model, str(COMPOSITE_PATH))

    check_statistical(pred_full)
    # 512: the "clean" default boundary. 2048/1536: check 1's most-elevated
    # statistical outliers, tested directly to see if they're real seam
    # artifacts or just check 1's naive-heuristic false positives (a real
    # water-body edge crossing near that row would also spike its flip rate).
    for boundary_row in (512, 1536, 2048):
        check_direct_crossing(lightning_model, pred_full, boundary_row)


if __name__ == "__main__":
    main()
