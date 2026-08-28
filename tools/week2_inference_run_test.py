"""Week 2-6: inference_runs DB wiring — real test, not throwaway.

Continues the SAME real Kristine/Trami backtest event Week 1-8 registered
(event_id below) one stage further: runs actual local inference (Modal not
needed for this — 2-6 is DB wiring, not a Modal concern) on the composite
already built in Week 1-6/2-2/2-3, applies the cloud mask, and records a real
inference_runs row with real metrics. Wrapped in pipeline.db.pipeline_step
(Week 1-7 pattern) so it also lands in the pipeline_events audit log.

Usage:
  python -m tools.week2_inference_run_test
"""
import sys
import time

sys.path.insert(0, ".")
from pipeline import config
from pipeline.db import pipeline_step
from pipeline.preprocess import cloud_mask, s2_composite
from pipeline.repository import create_inference_run, update_inference_run

# The real event Week 1-8 registered (Kristine/Trami 2024-10 backtest, Marikina).
EVENT_ID = "71426a18-da5c-4a99-a527-1600a32ea24e"
STAC_ID = "S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159"
COMPOSITE_PATH = config.DATA_OUTPUT_DIR / f"{STAC_ID}_composite.tif"


def load_model():
    from terratorch.cli_tools import LightningInferenceModel

    checkpoint_dir = config.REPO_ROOT / ".cache" / "prithvi_official_demo"
    lightning_model = LightningInferenceModel.from_config(
        str(checkpoint_dir / "config.yaml"), str(checkpoint_dir / "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt"),
    )
    lightning_model.model.eval()
    return lightning_model


def main():
    bbox = tuple(config.AOI_BBOX)

    print(f"Using event {EVENT_ID} (Week 1-8's real Kristine/Trami backtest)")
    print(f"Composite: {COMPOSITE_PATH.name}")

    run = create_inference_run(
        EVENT_ID, model=config.PRITHVI_CHECKPOINT_PRIMARY, model_version=None,
        input_scene_ids=[STAC_ID], status="running",
    )
    run_id = run["id"]

    with pipeline_step("inference.run", event_id=EVENT_ID, run_id=run_id,
                        input={"stac_id": STAC_ID, "run_id": run_id}) as step:
        from pipeline.inference.prithvi_inference import _convert_np_uint8, load_example, run_model, save_geotiff

        t0 = time.time()
        print("Loading model (local, cached checkpoint)...")
        lightning_model = load_model()

        print("Running inference...")
        input_data, temporal_coords, location_coords, meta_data = load_example(
            file_paths=[str(COMPOSITE_PATH)], indices=[0, 1, 2, 3, 4, 5],
        )
        meta_data = meta_data[0]
        if input_data.mean() > 1:
            input_data = input_data / 10000
        pred = run_model(input_data, temporal_coords, location_coords,
                          lightning_model.model, lightning_model.datamodule, 512)
        inference_elapsed = time.time() - t0

        pred_path = config.DATA_OUTPUT_DIR / f"{STAC_ID}_pred.tiff"
        meta_data.update(count=1, dtype="uint8", compress="lzw", nodata=0)
        # pred is already (1, H, W) — run_model() squeezes the batch dim internally
        # (see prithvi_inference.py's own main(), which calls save_geotiff on it
        # directly with no further indexing — matched here on purpose).
        save_geotiff(_convert_np_uint8(pred), str(pred_path), meta_data)
        print(f"  inference took {inference_elapsed:.1f}s, saved {pred_path.name}")

        print("Applying cloud mask...")
        item = s2_composite.fetch_item(STAC_ID)
        masked_path = cloud_mask.mask_prediction(item, pred_path, bbox, pad_ratio=0.05)

        import rasterio
        import numpy as np

        with rasterio.open(masked_path) as src:
            masked = src.read(1)
        n_total = masked.size
        n_water = (masked == 255).sum()
        n_cloud = (masked == 128).sum()
        n_dry = (masked == 0).sum()

        metrics = {
            "inference_seconds": round(inference_elapsed, 1),
            "tile_count": 12,  # 904x2677 @ img_size=512 -> 2x6 (Week 2-3)
            "water_pct": round(100 * n_water / n_total, 2),
            "cloud_masked_pct": round(100 * n_cloud / n_total, 2),
            "dry_pct": round(100 * n_dry / n_total, 2),
            "pred_shape": list(masked.shape),
        }
        print(f"  metrics: {metrics}")

        step.output = {"run_id": run_id, "masked_pred_path": str(masked_path), "metrics": metrics}

    update_inference_run(run_id, status="succeeded", metrics=metrics)

    print(f"\ninference_runs row {run_id} -> succeeded")
    return run_id


if __name__ == "__main__":
    main()
