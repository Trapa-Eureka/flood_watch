"""Week 2-7: Week 2 integration test — DB event -> Modal inference -> JRC diff
-> vectorize -> flood_extents, end to end, on the live Supabase project.

Continues the SAME real event Week 1-8/2-6 have been building on (Kristine/
Trami 2024-10 backtest) one more full lap: this time inference.run goes
through Modal (not local, unlike 2-6 — 2-7 explicitly wants the Modal path
exercised end-to-end), then baseline.diff (with 2-5's tuned 1px water buffer)
and a first (minimal, Week 2-7 scoped) vectorize.extract, landing a real row
in flood_extents.

Usage:
  python -m tools.week2_integration_test
"""
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, ".")
from pipeline import config
from pipeline.baseline_diff import CLOUD_MASKED_VALUE, WATER_VALUE, fetch_permanent_water_mask
from pipeline.db import pipeline_step
from pipeline.inference.modal_app import PrithviInference, app
from pipeline.preprocess import cloud_mask, s2_composite
from pipeline.repository import create_flood_extent, create_inference_run, update_inference_run
from pipeline.vectorize import vectorize_new_flood

EVENT_ID = "71426a18-da5c-4a99-a527-1600a32ea24e"  # the real Kristine/Trami backtest event (Week 1-8)
STAC_ID = "S2A_MSIL2A_20241102T021841_N0511_R003_T51PUS_20241102T150159"
COMPOSITE_PATH = config.DATA_OUTPUT_DIR / f"{STAC_ID}_composite.tif"


def main():
    bbox = tuple(config.AOI_BBOX)
    print(f"Event: {EVENT_ID}  (Week 1-8's real Kristine/Trami backtest, continuing its lifecycle)")

    # --- inference.run (via Modal, unlike 2-6's local run) ---------------
    run = create_inference_run(
        EVENT_ID, model=config.PRITHVI_CHECKPOINT_PRIMARY,
        model_version="modal-t4",  # distinguishes this from 2-6's local run in the same table
        input_scene_ids=[STAC_ID], status="running",
    )
    run_id = run["id"]

    pred_path = config.DATA_OUTPUT_DIR / f"{STAC_ID}_pred_modal_w27.tiff"
    with pipeline_step("inference.run", event_id=EVENT_ID, run_id=run_id,
                        input={"stac_id": STAC_ID, "deployment": "modal-t4"}) as step:
        composite_bytes = COMPOSITE_PATH.read_bytes()
        print(f"Sending {len(composite_bytes)/1e6:.1f}MB composite to Modal...")
        t0 = time.time()
        pred_bytes = PrithviInference().run.remote(composite_bytes, input_indices=[0, 1, 2, 3, 4, 5])
        inference_elapsed = time.time() - t0
        pred_path.write_bytes(pred_bytes)
        print(f"  Modal inference took {inference_elapsed:.1f}s, saved {pred_path.name}")
        step.output = {"inference_seconds": round(inference_elapsed, 1)}

    # --- preprocess.run (cloud mask half) ---------------------------------
    with pipeline_step("preprocess.run", event_id=EVENT_ID, run_id=run_id,
                        input={"stac_id": STAC_ID}) as step:
        item = s2_composite.fetch_item(STAC_ID)
        masked_path = cloud_mask.mask_prediction(item, pred_path, bbox, pad_ratio=0.05)
        step.output = {"masked_pred_path": str(masked_path)}

    import numpy as np
    import rasterio

    with rasterio.open(masked_path) as src:
        masked = src.read(1)
    n_total = masked.size
    inference_metrics = {
        "inference_seconds": round(inference_elapsed, 1),
        "deployment": "modal-t4",
        "water_pct": round(100 * (masked == WATER_VALUE).sum() / n_total, 2),
        "cloud_masked_pct": round(100 * (masked == CLOUD_MASKED_VALUE).sum() / n_total, 2),
    }
    update_inference_run(run_id, status="succeeded", metrics=inference_metrics)

    # --- baseline.diff (2-5's tuned 1px water buffer, threshold=50) ------
    diff_path = config.DATA_OUTPUT_DIR / f"{STAC_ID}_new_flood_w27.tiff"
    with pipeline_step("baseline.diff", event_id=EVENT_ID, run_id=run_id,
                        input={"pred": str(masked_path)}) as step:
        with rasterio.open(masked_path) as src:
            pred = src.read(1)
            meta = src.meta.copy()
            target_transform, target_crs = src.transform, src.crs
            target_h, target_w = src.height, src.width

        permanent_water = fetch_permanent_water_mask(
            bbox, 0.05, target_transform, target_h, target_w, target_crs,
        )  # threshold/buffer_px default to the Week 2-5 tuned values

        is_flood_class = pred == WATER_VALUE
        is_cloud_masked = pred == CLOUD_MASKED_VALUE
        new_flood = is_flood_class & ~permanent_water & ~is_cloud_masked

        out = np.zeros(pred.shape, dtype="uint8")
        out[is_cloud_masked] = CLOUD_MASKED_VALUE
        out[permanent_water & ~is_cloud_masked] = 180
        out[new_flood] = WATER_VALUE

        n_new = int(new_flood.sum())
        n_valid = int((~is_cloud_masked).sum())
        meta.update(nodata=None)
        with rasterio.open(diff_path, "w", **meta) as dst:
            dst.write(out, 1)
        print(f"  new_flood: {n_new:,} / {n_valid:,} valid px ({100*n_new/n_valid:.2f}%) -> {diff_path.name}")
        step.output = {"new_flood_px": n_new, "new_flood_pct": round(100 * n_new / n_valid, 2)}

    # --- vectorize.extract (Week 2-7 minimal version) ----------------------
    with pipeline_step("vectorize.extract", event_id=EVENT_ID, run_id=run_id,
                        input={"raster": str(diff_path)}) as step:
        vec = vectorize_new_flood(diff_path)
        if vec is None:
            print("  no new_flood polygons at all — nothing to vectorize")
            step.output = {"polygon_found": False}
            return
        print(f"  vectorized: area_km2={vec['area_km2']:.4f}")
        step.output = {"polygon_found": True, "area_km2": round(vec["area_km2"], 4)}

    # --- flood_extents row --------------------------------------------------
    flood_extent = create_flood_extent(
        EVENT_ID, run_id, vec["geom_wkt"], vec["area_km2"],
        confidence_mean=None,  # run_model() only keeps argmax hard labels, not softmax probabilities — known gap
        raster_storage_key=None,  # R2 credentials not set yet (Week 1-4, still pending) — nullable since 2-7's migration
    )

    print(f"\n=== Week 2-7 integration test complete ===")
    print(f"inference_run={run_id}  flood_extent={flood_extent['id']}  area_km2={vec['area_km2']:.4f}")


if __name__ == "__main__":
    with modal.enable_output(), app.run():
        main()
