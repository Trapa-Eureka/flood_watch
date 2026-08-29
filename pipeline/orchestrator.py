"""Week 4-6 admin trigger UI backend: run the full pipeline for one DB event,
driven entirely by that event's own row — spec.md §7's named steps
(scenes.fetch -> preprocess.run -> inference.run -> baseline.diff ->
vectorize.extract -> exposure.compute -> tiles.publish), in order, each
wrapped in pipeline_step() for the same audit-log contract every prior
manual/backfill script in this project has used.

Every one of these steps already existed as an independently real, tested
function (Week 1-8 through Week 3-9) — this is the first time they're wired
together GENERICALLY for an arbitrary event a user just registered through
/admin, rather than a one-off script hardcoding a specific backtest's paths
and dates (tools/week4_register_backtest_event.py and friends). Nothing here
re-derives pipeline logic; it only sequences existing modules and persists
their results via pipeline/repository.py, exactly as those modules' own
integration tests (tools/week*_integration_test.py) already did by hand.

Honest scope note (see docs/design-notes.md "Week 4-6"): inference.run shells
out to `modal run` (Week 2's proven ephemeral-invocation path) rather than
calling a deployed Modal app directly — the app isn't `modal deploy`d yet,
formalizing that deployment is Week 4-8's job specifically, not this one's.

Usage:
  python -m pipeline.orchestrator <event_id>
"""
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from pipeline import config, repository
from pipeline.db import pipeline_step

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Half-width of the STAC search window centered on each target date. Wide
# enough to cover a couple of Sentinel-2 revisit cycles (~5 days each) so a
# cloudy pass on the exact target date doesn't dead-end the search, narrow
# enough that "pre/post event" still means something close to the actual dates.
SEARCH_WINDOW_DAYS = 10


def _date_window(anchor: str, days: int = SEARCH_WINDOW_DAYS) -> tuple[str, str]:
    d = date.fromisoformat(anchor)
    return (d - timedelta(days=days)).isoformat(), (d + timedelta(days=days)).isoformat()


def run_inference_via_modal(composite_path: Path, out_path: Path) -> None:
    """Invokes pipeline/inference/modal_app.py's @app.local_entrypoint() as a
    subprocess — the exact command Week 2-2/2-4's real GPU tests already used
    by hand (`modal run pipeline/inference/modal_app.py --composite-path ...
    --output-path ...`), just issued programmatically here instead of typed.
    Needs `modal setup`'s auth (~/.modal.toml, Week 2-1) already done, which
    it is — nothing new to authenticate for this step."""
    cmd = [
        sys.executable, "-m", "modal", "run",
        str(config.REPO_ROOT / "pipeline" / "inference" / "modal_app.py"),
        "--composite-path", str(composite_path),
        "--output-path", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"modal run failed (exit {result.returncode}): {result.stderr[-4000:]}")
    if not out_path.exists():
        raise RuntimeError(f"modal run exited 0 but did not write {out_path} — stdout tail: {result.stdout[-2000:]}")


def _run_baseline_diff(masked_pred_path: Path, bbox, out_path: Path) -> None:
    """Same array logic as pipeline/baseline_diff.py's main() (that module
    exposes fetch_permanent_water_mask as a real function but bakes the
    actual diff into main()'s CLI body, not a separate callable) — kept here
    rather than duplicated as a second copy inside baseline_diff.py itself."""
    import numpy as np
    import rasterio

    from pipeline.baseline_diff import CLOUD_MASKED_VALUE, WATER_VALUE, fetch_permanent_water_mask

    with rasterio.open(masked_pred_path) as src:
        pred = src.read(1)
        meta = src.meta.copy()
        target_transform, target_crs = src.transform, src.crs
        target_h, target_w = src.height, src.width

    permanent_water = fetch_permanent_water_mask(bbox, 0.05, target_transform, target_h, target_w, target_crs)

    is_flood_class = pred == WATER_VALUE
    is_cloud_masked = pred == CLOUD_MASKED_VALUE
    new_flood = is_flood_class & ~permanent_water & ~is_cloud_masked

    out = np.zeros(pred.shape, dtype="uint8")
    out[is_cloud_masked] = CLOUD_MASKED_VALUE
    out[permanent_water & ~is_cloud_masked] = 180
    out[new_flood] = WATER_VALUE

    meta.update(nodata=None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(out, 1)


def run_event_pipeline(event_id: str) -> dict:
    """The Week4-6 orchestration entry point. Marks events.status
    'processing' -> 'completed'/'failed' (never leaves it stuck at
    'registered', which is exactly the Week4-3 Kristine bug this project
    already hit once with a *manually* run pipeline — this function's whole
    purpose is to make that status transition automatic instead). On any
    real failure, marks 'failed' and re-raises rather than swallowing it —
    the caller (the /run API route's background process) is expected to let
    this crash loudly into its own log file, matching every other
    fail-honestly pattern already established in this project."""
    ev = repository.get_event_with_aoi(event_id)
    if ev is None:
        raise RuntimeError(f"event {event_id} not found")
    bbox = (ev["west"], ev["south"], ev["east"], ev["north"])
    out_dir = config.DATA_OUTPUT_DIR / "events" / event_id
    out_dir.mkdir(parents=True, exist_ok=True)

    repository.update_event_status(event_id, "processing")

    try:
        with pipeline_step("scenes.fetch", event_id=event_id, input={"bbox": bbox}) as ctx:
            from pipeline.stac_client import fetch_best_s2_scenes

            pre_start, pre_end = _date_window(ev["pre_event_date"])
            if ev["post_event_date"]:
                post_start, post_end = _date_window(ev["post_event_date"])
            else:
                # No fixed end date ("ongoing") — search for the most recent
                # scene up to today instead of around a date that doesn't exist.
                post_start, post_end = _date_window(date.today().isoformat())
            scenes = fetch_best_s2_scenes(bbox, pre_start, pre_end, post_start, post_end)
            ctx.output = {
                role: (None if r is None else {
                    "item_id": r["item"].id if r["item"] else None,
                    "ok": r["ok"], "local_cloud_pct": r["local_cloud_pct"],
                })
                for role, r in scenes.items()
            }

        post_result_wrap = scenes.get("post_event")
        if not post_result_wrap or not post_result_wrap["item"]:
            raise RuntimeError(
                f"no usable Sentinel-2 post-event scene found in {post_start}..{post_end} for this AOI"
            )
        post_item = post_result_wrap["item"]

        for role, wrap in scenes.items():
            if wrap and wrap["item"]:
                repository.record_scene_ref(event_id, wrap["item"], role=role)

        from pipeline.preprocess.s2_composite import preprocess_scene

        with pipeline_step("preprocess.run", event_id=event_id, input={"item_id": post_item.id, "role": "post_event"}) as ctx:
            post_composite = preprocess_scene(post_item, bbox, pad_ratio=0.05, out_path=out_dir / "post_composite.tif")
            ctx.output = {"composite_path": str(post_composite["composite_path"])}

        pre_composite_path = None
        baseline_wrap = scenes.get("baseline")
        # ok=True only — an ok=False baseline is select_best_scene's "best
        # available anyway" fallback (often a near-100%-cloud scene, see
        # docs/design-notes.md), and this project's own established
        # convention (Week4-3's Kristine event, BeforeAfterSlider.tsx) is to
        # treat that as "no usable pre-event image" rather than build and
        # show a composite that's mostly cloud. post_event has no such
        # option (inference needs *some* scene to run on), which is why only
        # this branch is gated on ok.
        if baseline_wrap and baseline_wrap["item"] and baseline_wrap["ok"]:
            with pipeline_step("preprocess.run", event_id=event_id, input={"item_id": baseline_wrap["item"].id, "role": "baseline"}) as ctx:
                pre_composite = preprocess_scene(baseline_wrap["item"], bbox, pad_ratio=0.05, out_path=out_dir / "pre_composite.tif")
                pre_composite_path = pre_composite["composite_path"]
                ctx.output = {"composite_path": str(pre_composite_path)}

        run_row = repository.create_inference_run(
            event_id, model=config.PRITHVI_CHECKPOINT_PRIMARY, input_scene_ids=[post_item.id],
        )
        run_id = run_row["id"]

        pred_path = out_dir / "pred.tiff"
        try:
            with pipeline_step("inference.run", event_id=event_id, run_id=run_id, input={"composite_path": str(post_composite["composite_path"])}) as ctx:
                run_inference_via_modal(post_composite["composite_path"], pred_path)
                ctx.output = {"pred_path": str(pred_path)}
        except Exception as e:
            repository.update_inference_run(run_id, status="failed", metrics={"error": f"{type(e).__name__}: {e}"})
            raise

        masked_path = out_dir / "pred_masked.tif"
        with pipeline_step("preprocess.run", event_id=event_id, run_id=run_id, input={"stage": "cloud_mask"}) as ctx:
            from pipeline.preprocess.cloud_mask import mask_prediction

            mask_prediction(post_item, pred_path, bbox, pad_ratio=0.05, out_path=masked_path)
            ctx.output = {"masked_path": str(masked_path)}

        import numpy as np
        import rasterio

        with rasterio.open(masked_path) as src:
            arr = src.read(1)
        water_pct = 100 * float((arr == 255).sum()) / arr.size
        cloud_pct = 100 * float((arr == 128).sum()) / arr.size
        repository.update_inference_run(
            run_id, status="succeeded",
            metrics={"water_pct": round(water_pct, 2), "cloud_masked_pct": round(cloud_pct, 2), "pred_shape": list(arr.shape)},
        )

        new_flood_path = out_dir / "new_flood.tif"
        with pipeline_step("baseline.diff", event_id=event_id, run_id=run_id) as ctx:
            _run_baseline_diff(masked_path, bbox, new_flood_path)
            ctx.output = {"new_flood_path": str(new_flood_path)}

        from pipeline.vectorize import vectorize_new_flood

        with pipeline_step("vectorize.extract", event_id=event_id, run_id=run_id) as ctx:
            vec = vectorize_new_flood(new_flood_path)
            ctx.output = {"has_flood": vec is not None, "area_km2": vec["area_km2"] if vec else 0.0}

        if vec is None:
            # A real, valid outcome (spec.md — not every AOI floods every
            # time) — complete honestly with no flood_extents/exposure_stats
            # rows rather than fabricating a zero-area one.
            repository.update_event_status(event_id, "completed")
            return {"event_id": event_id, "status": "completed", "area_km2": 0.0, "note": "no new flood detected"}

        flood_extent = repository.create_flood_extent(event_id, run_id, vec["geom_wkt"], vec["area_km2"])

        with pipeline_step("exposure.compute", event_id=event_id, run_id=run_id) as ctx:
            from pipeline.exposure import compute_exposure_stats

            n_rows = 0
            # Both levels, same as every prior real run (Week3-6/3-9/4-3) —
            # the ADM3-only-when-summing rule lives in the *readers*
            # (events/[id]/page.tsx etc.), not in what gets computed/stored.
            for level in ("adm3_municipality", "adm4_barangay"):
                for row in compute_exposure_stats(vec["geom_wkt"], level=level):
                    repository.upsert_exposure_stat(
                        event_id, row["admin_boundary_id"], row["flooded_area_km2"], row["flooded_area_pct"],
                        row["est_population_affected"], row["est_buildings_affected"],
                        row["population_source"], row["building_source"],
                    )
                    n_rows += 1
            ctx.output = {"rows_written": n_rows}

        with pipeline_step("tiles.publish", event_id=event_id, run_id=run_id) as ctx:
            from pipeline.tiles import publish_event_tiles

            tiles_result = publish_event_tiles(
                event_id, pre_composite_path=pre_composite_path,
                post_composite_path=post_composite["composite_path"], flood_raster_path=new_flood_path,
            )
            ctx.output = {k: (v is not None) for k, v in tiles_result.items()}

        repository.update_event_status(event_id, "completed")
        return {"event_id": event_id, "status": "completed", "area_km2": vec["area_km2"], "flood_extent_id": flood_extent["id"]}

    except Exception:
        repository.update_event_status(event_id, "failed")
        raise


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    args = parser.parse_args()

    result = run_event_pipeline(args.event_id)
    print(f"Pipeline finished: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
