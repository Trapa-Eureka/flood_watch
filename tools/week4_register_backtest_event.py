"""Week 4-3: register the "event2" Marikina basin backtest (pre 2025-06-15,
post 2025-08-04) as a real, dashboard-visible event.

This data predates the formalized Week 1-2 pipeline entirely (pure spike-era
local exploration — data/output/event2_*.tif, no scene_refs/pipeline_events
audit trail exists for it, no original STAC item ids were ever recorded).
Week 3-8's design-notes explicitly deferred formally registering it as
"Week 5-1's job" — but that scoping was about re-running INFERENCE in
production to compare against spike results, not about registering an event
row at all. This script does the latter only: reuses the already-computed
local rasters (composites + flood diff, already verified real) to populate
real DB rows via the already-built Week 2/3 functions — no new inference, no
re-run, matching Week 3-9's own "recomputed and got the same answer" pattern.

Why this event, not just Marikina/Kristine alone: Kristine's baseline scene
was never usable (Week 1-5/1-8: real cloud cover made it fail the AOI-local
quality bar) so it has no "before" image at all — fine for exposure_stats,
but a genuinely broken demo for Week 4-3's before/after slider. event2 has
both.

Geography note: reverse-geocoded (Nominatim, live) rather than assumed — its
composite bounds resolve to Marikina again (District II, Marikina), not a
different city, so this reuses the existing "Marikina River Basin" AOI row
rather than creating a new one.

No original STAC ids exist for these composites, so no scene_refs rows are
created here — this event's tile images are addressed by event_id+role via
data/output/tiles/{event_id}/, independent of scene_refs (a deliberate design
choice, see docs/design-notes.md: scene_refs stays a STAC/audit concern,
display tiles are their own thing).

Usage:
  python -m tools.week4_register_backtest_event
"""
import sys

sys.path.insert(0, ".")
from pipeline import config, repository
from pipeline.db import pipeline_step
from pipeline.exposure import compute_exposure_stats
from pipeline.tiles import publish_event_tiles
from pipeline.vectorize import vectorize_new_flood

MARIKINA_AOI_ID = "002ed740-fcad-468e-b80c-9f8caddedaf5"
PRE_COMPOSITE = "data/output/event2_pre_20250615.tif"
POST_COMPOSITE = "data/output/event2_post_20250804.tif"
FLOOD_RASTER = "data/output/event2_inference/new_flood_event2.tiff"

# Backfilled from the actual cloudmasked prediction file (real values, read
# live in this session — not estimated) — see docs/design-notes.md.
BACKFILLED_METRICS = {
    "water_pct": 1.22, "cloud_masked_pct": 23.51, "dry_pct": 75.27,
    "pred_shape": [2677, 2636],
    "backfilled_note": (
        "This inference_runs row documents a real local inference already computed "
        "before this project's pipeline_events/scene_refs tracking existed (pure "
        "spike-era exploration) — registered here after the fact from its actual "
        "output file, not re-run live. started_at/finished_at approximate the file's "
        "own mtime, not this script's run time."
    ),
}
# File mtime read live (2026-08-29): data/output/event2_inference/pred_event2_cloudmasked.tiff.
# started_at is a rough estimate (a few minutes earlier, not a real measurement
# — nothing recorded the actual inference start time back then) purely to
# satisfy the inference_runs_finished_after_started CHECK constraint honestly
# (finished_at must be >= started_at); the metrics/backfilled_note above are
# what's real here, not this specific duration.
BACKFILLED_FINISHED_AT = "2026-08-28T21:13:39+00:00"
BACKFILLED_STARTED_AT = "2026-08-28T21:11:00+00:00"


def main():
    event = repository.create_event(
        aoi_id=MARIKINA_AOI_ID, name="Marikina Basin 2025-08 backtest",
        kind="backtest", pre_event_date="2025-06-15", post_event_date="2025-08-04",
    )
    event_id = event["id"]

    run = repository.create_inference_run(
        event_id=event_id, model=config.PRITHVI_CHECKPOINT_PRIMARY, model_version="backfilled-local",
        input_scene_ids=[], status="running", started_at=BACKFILLED_STARTED_AT,
    )
    run_id = run["id"]
    repository.update_inference_run(
        run_id, status="succeeded", finished_at=BACKFILLED_FINISHED_AT, metrics=BACKFILLED_METRICS,
    )

    with pipeline_step("vectorize.extract", event_id=event_id, run_id=run_id,
                        input={"raster": FLOOD_RASTER}) as step:
        vec = vectorize_new_flood(FLOOD_RASTER)
        assert vec is not None, "expected real new-flood area for this backtest"
        flood_extent = repository.create_flood_extent(
            event_id=event_id, run_id=run_id, geom_wkt=vec["geom_wkt"], area_km2=vec["area_km2"],
        )
        step.output = {"flood_extent_id": flood_extent["id"], "area_km2": vec["area_km2"]}
        print(f"vectorize.extract: area_km2={vec['area_km2']}")

    with pipeline_step("exposure.compute", event_id=event_id, run_id=run_id,
                        input={"flood_extent_id": flood_extent["id"]}) as step:
        adm3 = compute_exposure_stats(vec["geom_wkt"], level="adm3_municipality")
        for s in adm3:
            repository.upsert_exposure_stat(
                event_id=event_id, admin_boundary_id=s["admin_boundary_id"],
                flooded_area_km2=s["flooded_area_km2"], flooded_area_pct=s["flooded_area_pct"],
                est_population_affected=s["est_population_affected"],
                est_buildings_affected=s["est_buildings_affected"],
                population_source=s["population_source"], building_source=s["building_source"],
            )
        step.output = {"adm3_count": len(adm3)}
        print(f"exposure.compute: {len(adm3)} adm3 rows")

    with pipeline_step("tiles.publish", event_id=event_id, run_id=run_id,
                        input={"pre": PRE_COMPOSITE, "post": POST_COMPOSITE, "flood": FLOOD_RASTER}) as step:
        tiles = publish_event_tiles(
            event_id, pre_composite_path=PRE_COMPOSITE, post_composite_path=POST_COMPOSITE,
            flood_raster_path=FLOOD_RASTER,
        )
        step.output = {k: (v is not None) for k, v in tiles.items()}
        print(f"tiles.publish: {step.output}")

    repository.update_event_status(event_id, "completed")
    repository.update_event_visibility(event_id, "public")

    print(f"\nDone. event_id={event_id}, status=completed, visibility=public")


if __name__ == "__main__":
    main()
